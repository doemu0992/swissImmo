"""Die Fallmaschine — Vorgänge mit Schritten, Fristen und Zeiterfassung.

WARUM ES DIESE APP GIBT

Ein Mieterwechsel läuft vier Monate über Kündigung, Bestätigung, Ausschreibung,
Bewerbung, Abnahme und Endabrechnung. Diese Schritte gibt es im Bestand
längst — `core/views/fw/kuendigung.py`, `mietprozess.py`, `abnahme.py`,
`vertragserstellung.py`. Was fehlte, ist die Klammer: Status, Zuständigkeit und
Frist des **Gesamtvorgangs**. Bisher lag beides im Kopf der Bewirtschaftung.

In einer Verwaltung mit drei Personen und je dreissig parallelen Vorgängen ist
der fallengelassene Vorgang der teuerste Fehler. Diese App ist die Antwort
darauf.

WARUM SCHRITTDEFINITIONEN DATEN SIND UND KEIN CODE

`Fallart` und `SchrittVorlage` sind Tabellen, keine Python-Konstanten. Eine
Verwaltung, die ihren Mieterwechsel um einen Schritt ergänzt, darf dafür keinen
Entwickler und kein Deployment brauchen. Der Preis ist eine Einrichtung je
Organisation (`manage.py fallarten_anlegen`), und der ist bewusst gezahlt.

WARUM FALLARTEN JE ORGANISATION UND NICHT GLOBAL

Eine globale Tabelle wäre gemeinsam veränderlich: Die Verwaltung A ändert einen
Schritt, und bei B ändert er sich mit. Das ist genau die Sorte Kopplung, die
Phase 2 beseitigt hat. Also je Organisation eine eigene Zeile — mit dem
akzeptierten Nachteil, dass eine Standardänderung nachgezogen werden muss.
"""
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from core.organisation_kette import OrganisationAusKette, organisation_aus_kontext
from core.tenancy import AlleOrganisationenManager, TenantManager, TenantQuerySet


class Fallart(models.Model):
    """Eine Vorgangsart mit ihren Schritten — je Organisation.

    `entitlement` verweist auf einen Schlüssel aus `core.funktionen`. Damit
    hängt die Sichtbarkeit einer Fallart an der Abostufe, ohne dass irgendwo im
    Code eine `if`-Abfrage dafür steht.
    """

    organisation = models.ForeignKey(
        'crm.Organisation', on_delete=models.CASCADE,
        related_name='fallarten', verbose_name='Organisation')
    schluessel = models.SlugField('Schlüssel', max_length=40)
    bezeichnung = models.CharField('Bezeichnung', max_length=120)
    entitlement = models.CharField(
        'Funktionsschlüssel', max_length=40, default='faelle',
        help_text='Schlüssel aus core.funktionen — steuert die Sichtbarkeit.')
    aktiv = models.BooleanField('Aktiv', default=True)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Fallart'
        verbose_name_plural = 'Fallarten'
        ordering = ('bezeichnung',)
        constraints = [
            models.UniqueConstraint(
                fields=('organisation', 'schluessel'),
                name='fallart_je_organisation_eindeutig'),
        ]

    def __str__(self):
        return self.bezeichnung

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_aus_kontext()
        super().save(*args, **kwargs)


class SchrittVorlage(OrganisationAusKette):
    """Ein Schritt einer Fallart, mit Etappe und Fristregel."""

    ORGANISATION_PFAD = 'fallart'

    fallart = models.ForeignKey(
        Fallart, on_delete=models.CASCADE, related_name='schrittvorlagen')
    nr = models.PositiveSmallIntegerField('Reihenfolge')
    etappe_nr = models.PositiveSmallIntegerField('Etappe')
    etappe = models.CharField('Etappenbezeichnung', max_length=80)
    bezeichnung = models.CharField('Schritt', max_length=200)
    hinweis = models.TextField('Hinweis', blank=True)
    pflicht = models.BooleanField('Pflichtschritt', default=True)

    #: Relative Fristregel als Klartext, etwa «vertragsende-0» oder
    #: «rueckgabe+30». Ausgewertet wird sie erst in Etappe 4a.2 zusammen mit
    #: dem Regelwerk; bis dahin nur festgehalten, nicht gerechnet.
    frist_regel = models.CharField('Fristregel', max_length=60, blank=True)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Schrittvorlage'
        verbose_name_plural = 'Schrittvorlagen'
        ordering = ('fallart', 'nr')
        constraints = [
            models.UniqueConstraint(
                fields=('fallart', 'nr'), name='schrittvorlage_nr_eindeutig'),
        ]

    def __str__(self):
        return f'{self.nr}. {self.bezeichnung}'


class FallQuerySet(TenantQuerySet):
    def offen(self):
        return self.exclude(status__in=(Fall.ABGESCHLOSSEN, Fall.ABGEBROCHEN))

    def liegengeblieben(self, stichtag=None):
        """Fälle, bei denen zu lange nichts passiert ist.

        Die Regel steht in `Fall.TAGE_OHNE_BEWEGUNG`: kürzere Duldung, wenn auf
        Dritte gewartet wird, weil dort das Nachfassen die eigentliche Arbeit
        ist.
        """
        from datetime import timedelta
        stichtag = stichtag or timezone.now()
        wartend = stichtag - timedelta(days=Fall.TAGE_OHNE_BEWEGUNG['wartet'])
        sonst = stichtag - timedelta(days=Fall.TAGE_OHNE_BEWEGUNG['sonst'])
        return self.offen().filter(
            models.Q(status=Fall.WARTET, letzte_bewegung__lt=wartend)
            | models.Q(letzte_bewegung__lt=sonst)
            & ~models.Q(status=Fall.WARTET))


class FallManager(TenantManager.from_queryset(FallQuerySet)):
    pass


class FallAlleManager(AlleOrganisationenManager.from_queryset(FallQuerySet)):
    pass


class Fall(models.Model):
    """Ein Vorgang mit Lebenszyklus.

    WARUM DIE AKTE EIN GENERISCHER BEZUG IST

    Ein Fall hängt je nach Art an einem Mietverhältnis, einem Objekt, einer
    Liegenschaft oder einem Mandat. Vier nullbare Fremdschlüssel wären die
    Alternative — und damit vier Stellen, an denen ein Fall zu keiner oder zu
    zwei Akten gehören kann. Der generische Bezug erzwingt: genau eine.

    Der Preis ist, dass die Datenbank die Gültigkeit nicht prüfen kann. Deshalb
    steht in `AKTENTYPEN`, was erlaubt ist, und `clean()` hält sich daran.
    """

    OFFEN, WARTET, RUHT, ABGESCHLOSSEN, ABGEBROCHEN = (
        'offen', 'wartet_auf_dritte', 'ruht', 'abgeschlossen', 'abgebrochen')
    STATUS = [
        (OFFEN, 'Offen'),
        (WARTET, 'Wartet auf Dritte'),
        (RUHT, 'Ruht'),
        (ABGESCHLOSSEN, 'Abgeschlossen'),
        (ABGEBROCHEN, 'Abgebrochen'),
    ]

    #: Verfallsregel. Kürzer beim Warten auf Dritte: dort ist das Nachfassen
    #: die Arbeit, und wer nicht nachfasst, wartet ewig.
    TAGE_OHNE_BEWEGUNG = {'wartet': 10, 'sonst': 14}

    #: Welche Modelle als Akte zulässig sind. `app_label.modell`, kleingeschrieben.
    AKTENTYPEN = (
        'rentals.mietvertrag',
        'portfolio.einheit',
        'portfolio.liegenschaft',
        'crm.eigentuemer',
        'crm.mieter',
        'tickets.schadenmeldung',
    )

    organisation = models.ForeignKey(
        'crm.Organisation', on_delete=models.CASCADE,
        related_name='faelle', editable=False, verbose_name='Organisation')
    nummer = models.CharField('Fallnummer', max_length=20, blank=True)
    fallart = models.ForeignKey(
        Fallart, on_delete=models.PROTECT, related_name='faelle')

    akte_typ = models.ForeignKey(
        ContentType, on_delete=models.PROTECT, null=True, blank=True)
    akte_id = models.PositiveIntegerField(null=True, blank=True)
    akte = GenericForeignKey('akte_typ', 'akte_id')

    zustaendig = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='faelle')
    status = models.CharField('Status', max_length=20, choices=STATUS, default=OFFEN)
    betreff = models.CharField('Betreff', max_length=200, blank=True)
    notiz = models.TextField('Notiz', blank=True)

    eroeffnet_am = models.DateTimeField('Eröffnet', default=timezone.now)
    abgeschlossen_am = models.DateTimeField('Abgeschlossen', null=True, blank=True)
    letzte_bewegung = models.DateTimeField('Letzte Bewegung', default=timezone.now)

    objects = FallManager()
    alle_organisationen = FallAlleManager()

    class Meta:
        verbose_name = 'Fall'
        verbose_name_plural = 'Fälle'
        ordering = ('-letzte_bewegung',)
        indexes = [
            models.Index(fields=('organisation', 'status')),
            models.Index(fields=('akte_typ', 'akte_id')),
        ]

    def __str__(self):
        return f'{self.nummer or "Fall"} · {self.fallart}'

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            # Die Akte kennt ihre Organisation — sie ist die genauere Quelle
            # als der Kontext. Nur wenn keine Akte hängt, entscheidet er.
            self.organisation_id = (
                getattr(self.akte, 'organisation_id', None)
                or organisation_aus_kontext())
        super().save(*args, **kwargs)
        if not self.nummer:
            self.nummer = f'F-{self.eroeffnet_am:%Y}-{self.pk:04d}'
            super().save(update_fields=['nummer'])

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.akte_typ_id:
            label = f'{self.akte_typ.app_label}.{self.akte_typ.model}'
            if label not in self.AKTENTYPEN:
                raise ValidationError(
                    {'akte_typ': f'{label} ist kein zulässiger Aktentyp. '
                                 f'Zulässig: {", ".join(self.AKTENTYPEN)}'})

    # -- Schritte ----------------------------------------------------------
    def schritte_anlegen(self):
        """Erzeugt die Schritte aus den Vorlagen der Fallart.

        Idempotent: Ein zweiter Aufruf legt nichts doppelt an. Sonst würde ein
        versehentlicher Doppelaufruf einen Fall mit zwölf statt sechs Schritten
        hinterlassen, und das fiele erst beim Abarbeiten auf.
        """
        vorhanden = set(self.schritte.values_list('nr', flat=True))
        neu = [
            Fallschritt(fall=self, vorlage=v, nr=v.nr, etappe_nr=v.etappe_nr,
                        etappe=v.etappe, bezeichnung=v.bezeichnung,
                        pflicht=v.pflicht)
            for v in self.fallart.schrittvorlagen.all() if v.nr not in vorhanden
        ]
        for s in neu:            # kein bulk_create: `save()` leitet die Organisation ab
            s.save()
        return len(neu)

    @property
    def naechster_schritt(self):
        return self.schritte.filter(erledigt_am__isnull=True).order_by('nr').first()

    @property
    def fortschritt(self):
        """(erledigt, gesamt) — für die Anzeige im Arbeitsvorrat."""
        gesamt = self.schritte.count()
        return self.schritte.filter(erledigt_am__isnull=False).count(), gesamt

    def bewegt(self, speichern=True):
        """Setzt die Verfallsuhr zurück. Jede Änderung am Fall ruft das auf."""
        self.letzte_bewegung = timezone.now()
        if speichern:
            self.save(update_fields=['letzte_bewegung'])

    @property
    def tage_ohne_bewegung(self):
        return (timezone.now() - self.letzte_bewegung).days

    @property
    def ist_liegengeblieben(self):
        if self.status in (self.ABGESCHLOSSEN, self.ABGEBROCHEN):
            return False
        grenze = self.TAGE_OHNE_BEWEGUNG[
            'wartet' if self.status == self.WARTET else 'sonst']
        return self.tage_ohne_bewegung >= grenze

    @property
    def erfasste_minuten(self):
        return self.zeiteintraege.aggregate(
            s=models.Sum('minuten'))['s'] or 0


class Fallschritt(OrganisationAusKette):
    """Ein Schritt in einem konkreten Fall.

    Bezeichnung und Etappe sind **kopiert**, nicht nur verlinkt: Ändert jemand
    die Vorlage, sollen laufende Fälle nicht rückwirkend anders aussehen. Ein
    abgeschlossener Fall muss zeigen, was damals zu tun war.
    """

    ORGANISATION_PFAD = 'fall'

    fall = models.ForeignKey(Fall, on_delete=models.CASCADE, related_name='schritte')
    vorlage = models.ForeignKey(
        SchrittVorlage, on_delete=models.SET_NULL, null=True, blank=True)
    nr = models.PositiveSmallIntegerField('Reihenfolge')
    etappe_nr = models.PositiveSmallIntegerField('Etappe', default=1)
    etappe = models.CharField('Etappenbezeichnung', max_length=80, blank=True)
    bezeichnung = models.CharField('Schritt', max_length=200)
    pflicht = models.BooleanField('Pflichtschritt', default=True)

    frist = models.DateField('Frist', null=True, blank=True)
    erledigt_am = models.DateTimeField('Erledigt', null=True, blank=True)
    erledigt_durch = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='erledigte_fallschritte')
    bemerkung = models.TextField('Bemerkung', blank=True)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Fallschritt'
        verbose_name_plural = 'Fallschritte'
        ordering = ('fall', 'nr')
        constraints = [
            models.UniqueConstraint(
                fields=('fall', 'nr'), name='fallschritt_nr_eindeutig'),
        ]

    def __str__(self):
        return f'{self.nr}. {self.bezeichnung}'

    def erledigen(self, benutzer=None):
        self.erledigt_am = timezone.now()
        self.erledigt_durch = benutzer
        self.save(update_fields=['erledigt_am', 'erledigt_durch'])
        self.fall.bewegt()
        return self


class Zeiteintrag(OrganisationAusKette):
    """Aufwand auf einem Fall.

    WARUM AM FALL UND NICHT AM MANDAT

    Die Frage, die beantwortet werden soll, lautet: Verdiene ich an diesem
    Mandat noch etwas? Die Antwort braucht den Aufwand **je Vorgang**, sonst
    lässt sich nicht sagen, welche Art von Arbeit das Honorar aufzehrt. Ein
    Erbteilungsprozess mit 22 Stunden ausserhalb des Honorars sieht in einer
    Mandatssumme aus wie normale Bewirtschaftung.

    WAS DIESES MODELL NICHT LÖST

    Eine Zeiterfassung, die nicht beiläufig geht, wird nicht gepflegt, und
    ungepflegte Zahlen sind schlimmer als keine — sie sehen aus wie Wissen.
    `minuten` statt Stunden und ein Fallbezug statt freier Eingabe sind ein
    Anfang; ob es im Alltag trägt, entscheidet die Oberfläche in Phase 5, nicht
    dieses Modell.
    """

    ORGANISATION_PFAD = 'fall'

    BEWIRTSCHAFTUNG, BUCHHALTUNG, KORRESPONDENZ, SONDER = (
        'bewirtschaftung', 'buchhaltung', 'korrespondenz', 'sonder')
    TAETIGKEITEN = [
        (BEWIRTSCHAFTUNG, 'Bewirtschaftung'),
        (BUCHHALTUNG, 'Buchhaltung'),
        (KORRESPONDENZ, 'Korrespondenz'),
        (SONDER, 'Sonderaufwand'),
    ]

    fall = models.ForeignKey(Fall, on_delete=models.CASCADE, related_name='zeiteintraege')
    benutzer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='zeiteintraege')
    datum = models.DateField('Datum', default=timezone.localdate)
    minuten = models.PositiveIntegerField('Minuten')
    taetigkeit = models.CharField(
        'Tätigkeit', max_length=20, choices=TAETIGKEITEN, default=BEWIRTSCHAFTUNG)
    notiz = models.CharField('Notiz', max_length=200, blank=True)
    #: Aufwand ausserhalb des Verwaltungshonorars — der Treiber, den die
    #: Mandatsrentabilität sichtbar machen soll.
    verrechenbar = models.BooleanField('Separat verrechenbar', default=False)
    #: Abweichender Stundensatz fuer DIESEN Eintrag (E2.46).
    #:
    #: Leer = die Vorgabe der Organisation gilt. Ein eigener Wert traegt den
    #: Fall, in dem ein Einsatz anders kostet — Notfall am Sonntag, ein
    #: vereinbarter Pauschalsatz fuer ein Mandat, eine Kulanz.
    #:
    #: Nicht `default=organisation.stundensatz`: Ein kopierter Wert friert den
    #: Satz zum Erfassungszeitpunkt ein, und niemand sieht spaeter, ob er
    #: bewusst gesetzt oder nur mitgeschrieben wurde.
    satz = models.DecimalField(
        'Stundensatz (CHF)', max_digits=8, decimal_places=2,
        null=True, blank=True)

    @property
    def betrag(self):
        """Der verrechenbare Betrag — oder `None`, wenn er sich nicht ergibt.

        `None` heisst «nicht berechenbar», nicht «null Franken»: entweder ist
        der Aufwand nicht separat verrechenbar, oder es ist gar kein Satz
        hinterlegt. Beides ist eine Aussage, eine Null waere eine falsche.
        """
        if not self.verrechenbar:
            return None
        satz = self.satz if self.satz is not None else self.organisation.stundensatz
        if satz is None:
            return None
        from decimal import Decimal
        # AUF RAPPEN, WIE ALLES ANDERE — und `0.01`, nicht `0.05`.
        #
        # Hier stand `quantize(Decimal('0.05'))`. Das liest sich wie die
        # 5-Rappen-Rundung, die der Zahlungsverkehr an manchen Stellen
        # verlangt, TUT SIE ABER NICHT: Das Argument bestimmt nur den
        # Exponenten, nicht die Schrittweite. Nachgerechnet — 100 CHF/h fuer
        # 7 Minuten ergibt 11.6667 und wird mit BEIDEN Schreibweisen zu
        # 11.67. Gleiches Ergebnis, irrefuehrende Schreibweise.
        #
        # Der Bestand rundet Geld an 36 Stellen auf `0.01`; das ist der
        # vorhandene Wert, und er gilt auch hier.
        return (satz * Decimal(self.minuten) / Decimal(60)).quantize(Decimal('0.01'))

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Zeiteintrag'
        verbose_name_plural = 'Zeiteinträge'
        ordering = ('-datum', '-id')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(minuten__gt=0),
                name='zeiteintrag_minuten_positiv'),
        ]

    def __str__(self):
        return f'{self.datum} · {self.minuten} Min.'

# Die Regelwerksmodelle stehen in einer eigenen Datei, damit diese hier
# lesbar bleibt. Django findet Modelle nur ueber `models`, deshalb der Import.
from faelle.regelwerk_models import (  # noqa: E402,F401
    Regel, Regelanwendung, Regelsatz,
)
from faelle.zulauf_models import (  # noqa: E402,F401
    Eingang, Zuordnungsregel,
)
from faelle.lauf_models import (  # noqa: E402,F401
    Blockade, Lauf, Laufart,
)
from faelle.termin_models import (  # noqa: E402,F401
    Abwesenheit, Termin,
)
