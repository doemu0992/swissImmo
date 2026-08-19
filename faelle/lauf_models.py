"""Läufe mit Zustand — die wiederkehrende Verarbeitung wird sichtbar.

WARUM ES DIESE MODELLE GIBT

Sollstellung, Bankabgleich, Mahnlauf, Zahllauf, Nebenkostenabrechnung und MWST
existieren im Bestand als Views, die auf Zuruf rechnen. Niemand hält fest, ob
ein Lauf für August überhaupt stattgefunden hat. Der Mahnlauf, der am 15. fällig
war und nicht ausgelöst wurde, fällt deshalb erst auf, wenn jemand nachschaut —
oder gar nicht.

Diese App gibt jedem Lauf einen **Zustand je Periode** und, wichtiger, einen
**Grund, wenn er nicht weitergeht**. Ein überfälliger Lauf erscheint dadurch von
selbst im Arbeitsvorrat, statt auf Aufmerksamkeit zu warten.

WARUM BLOCKADEN EIGENE DATENSÄTZE SIND

Ein Statusfeld «blockiert» beantwortet die falsche Frage. Interessant ist nicht,
*dass* etwas klemmt, sondern *was* — und seit wann. Im Konzept ist das der
Nebenkostenlauf, der auf die VHKA-Ablesung wartet, und der Mahnlauf, der auf
sieben unzugeordnete Bankeingänge wartet. Beides sind Hinweise, die zu einer
Handlung führen; «blockiert» führt zu einer Rückfrage.

WAS DIESE ETAPPE NICHT TUT

Sie rechnet nichts. Die bestehenden Views bleiben unverändert und machen die
Arbeit weiter. Hier entsteht nur die Buchführung darüber — additiv, wie der
ganze Rest von Phase 4a.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from core.organisation_kette import OrganisationAusKette, organisation_aus_kontext
from core.tenancy import AlleOrganisationenManager, TenantManager, TenantQuerySet


class Laufart(models.Model):
    """Eine wiederkehrende Verarbeitung, je Organisation.

    `faellig_am_tag` ist der Tag im Monat, an dem der Lauf spätestens laufen
    soll. Er ist eine Vorgabe der Verwaltung, keine Rechtsfrage — deshalb frei
    einstellbar.
    """

    MONATLICH, QUARTALSWEISE, JAEHRLICH = 'monatlich', 'quartalsweise', 'jaehrlich'
    RHYTHMEN = [
        (MONATLICH, 'Monatlich'),
        (QUARTALSWEISE, 'Quartalsweise'),
        (JAEHRLICH, 'Jährlich'),
    ]

    organisation = models.ForeignKey(
        'crm.Organisation', on_delete=models.CASCADE,
        related_name='laufarten', verbose_name='Organisation')
    schluessel = models.SlugField('Schlüssel', max_length=40)
    bezeichnung = models.CharField('Bezeichnung', max_length=120)
    rhythmus = models.CharField('Rhythmus', max_length=15, choices=RHYTHMEN,
                                default=MONATLICH)
    faellig_am_tag = models.PositiveSmallIntegerField(
        'Fällig am Tag im Monat', default=1,
        help_text='Vorgabe der Verwaltung, keine Frist aus dem Gesetz.')
    reihenfolge = models.PositiveSmallIntegerField('Reihenfolge', default=10)
    entitlement = models.CharField('Funktionsschlüssel', max_length=40,
                                   default='monatslauf')
    ziel_ansicht = models.CharField(
        'Ansicht', max_length=80, blank=True,
        help_text='Name der bestehenden View, die den Lauf tatsächlich ausführt.')
    aktiv = models.BooleanField('Aktiv', default=True)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Laufart'
        verbose_name_plural = 'Laufarten'
        ordering = ('reihenfolge', 'bezeichnung')
        constraints = [
            models.UniqueConstraint(fields=('organisation', 'schluessel'),
                                    name='laufart_je_organisation_eindeutig'),
        ]

    def __str__(self):
        return self.bezeichnung

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_aus_kontext()
        super().save(*args, **kwargs)


class LaufQuerySet(TenantQuerySet):
    def offen(self):
        return self.exclude(status__in=(Lauf.ABGESCHLOSSEN, Lauf.UEBERSPRUNGEN))

    def ueberfaellig(self, stichtag=None):
        stichtag = stichtag or timezone.localdate()
        return self.offen().filter(faellig_am__lt=stichtag)

    def blockiert(self):
        return self.offen().filter(blockaden__behoben_am__isnull=True).distinct()


class Lauf(OrganisationAusKette):
    """Ein Lauf für eine bestimmte Periode.

    Die Periode ist eine Zeichenkette wie `2026-08` oder `2025` — kein Datum,
    weil ein Jahreslauf keinen Monat hat und ein Monatslauf keinen Tag. Sie ist
    zusammen mit der Laufart eindeutig: Es gibt genau einen Mahnlauf August 2026.
    """

    ORGANISATION_PFAD = 'laufart'

    OFFEN, LAEUFT, ABGESCHLOSSEN, UEBERSPRUNGEN = (
        'offen', 'laeuft', 'abgeschlossen', 'uebersprungen')
    STATUS = [
        (OFFEN, 'Offen'),
        (LAEUFT, 'Läuft'),
        (ABGESCHLOSSEN, 'Abgeschlossen'),
        (UEBERSPRUNGEN, 'Bewusst übersprungen'),
    ]

    laufart = models.ForeignKey(Laufart, on_delete=models.PROTECT,
                                related_name='laeufe')
    periode = models.CharField('Periode', max_length=10)
    status = models.CharField('Status', max_length=15, choices=STATUS, default=OFFEN)
    faellig_am = models.DateField('Fällig am')

    gestartet_am = models.DateTimeField('Gestartet', null=True, blank=True)
    abgeschlossen_am = models.DateTimeField('Abgeschlossen', null=True, blank=True)
    abgeschlossen_durch = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='abgeschlossene_laeufe')

    #: Was der Lauf bewegt hat — Anzahl Positionen, Summe, Ausnahmen.
    #: Frei, weil jede Laufart andere Zahlen hat.
    kennzahlen = models.JSONField('Kennzahlen', default=dict, blank=True)
    bemerkung = models.TextField('Bemerkung', blank=True)

    objects = TenantManager.from_queryset(LaufQuerySet)()
    alle_organisationen = AlleOrganisationenManager.from_queryset(LaufQuerySet)()

    class Meta:
        verbose_name = 'Lauf'
        verbose_name_plural = 'Läufe'
        ordering = ('faellig_am', 'laufart__reihenfolge')
        constraints = [
            models.UniqueConstraint(fields=('laufart', 'periode'),
                                    name='lauf_je_art_und_periode_eindeutig'),
        ]
        indexes = [
            models.Index(fields=('organisation', 'status', 'faellig_am')),
        ]

    def __str__(self):
        return f'{self.laufart} {self.periode}'

    # -- Zustand -----------------------------------------------------------
    @property
    def offene_blockaden(self):
        return self.blockaden.filter(behoben_am__isnull=True)

    @property
    def ist_blockiert(self):
        return self.offene_blockaden.exists()

    @property
    def ist_ueberfaellig(self):
        if self.status in (self.ABGESCHLOSSEN, self.UEBERSPRUNGEN):
            return False
        return self.faellig_am < timezone.localdate()

    @property
    def tage_ueberfaellig(self):
        if not self.ist_ueberfaellig:
            return 0
        return (timezone.localdate() - self.faellig_am).days

    def starten(self):
        if self.status == self.OFFEN:
            self.status = self.LAEUFT
            self.gestartet_am = timezone.now()
            self.save(update_fields=['status', 'gestartet_am'])
        return self

    def abschliessen(self, benutzer=None, **kennzahlen):
        """Schliesst den Lauf ab — aber nicht, solange etwas offen blockiert.

        Ein Lauf, der sich trotz offener Blockade abschliessen liesse, wäre die
        gefährlichste Variante: Er verschwindet aus dem Arbeitsvorrat, obwohl
        die Ursache steht.
        """
        if self.ist_blockiert:
            gruende = ', '.join(b.grund for b in self.offene_blockaden)
            raise ValueError(
                f'{self} lässt sich nicht abschliessen — offene Blockade: {gruende}')
        self.status = self.ABGESCHLOSSEN
        self.abgeschlossen_am = timezone.now()
        self.abgeschlossen_durch = benutzer
        if kennzahlen:
            self.kennzahlen = {**(self.kennzahlen or {}), **kennzahlen}
        self.save(update_fields=['status', 'abgeschlossen_am',
                                 'abgeschlossen_durch', 'kennzahlen'])
        return self

    def ueberspringen(self, bemerkung, benutzer=None):
        """Bewusst auslassen — mit Begründung, sonst nicht.

        Ohne Begründung wäre «übersprungen» von «vergessen» nicht zu
        unterscheiden, und genau diese Unterscheidung ist der Zweck.
        """
        if not bemerkung or not bemerkung.strip():
            raise ValueError('Überspringen ohne Begründung wird nicht gespeichert.')
        self.status = self.UEBERSPRUNGEN
        self.bemerkung = bemerkung.strip()
        self.abgeschlossen_am = timezone.now()
        self.abgeschlossen_durch = benutzer
        self.save(update_fields=['status', 'bemerkung', 'abgeschlossen_am',
                                 'abgeschlossen_durch'])
        return self

    def blockieren(self, grund, quelle=''):
        """Legt eine Blockade an, oder gibt die bestehende gleichen Grundes zurück."""
        vorhanden = self.offene_blockaden.filter(grund=grund).first()
        if vorhanden:
            return vorhanden
        b = Blockade(lauf=self, grund=grund, quelle=quelle)
        b.save()
        return b


class Blockade(OrganisationAusKette):
    """Was einen Lauf aufhält — und seit wann.

    Der Grund ist Klartext und kein Schlüssel: Er wird gelesen, nicht
    ausgewertet. «Verbrauchsablesung Techem fehlt seit 50 Tagen» führt zu einer
    Handlung; ein Aufzählungswert `VHKA_FEHLT` führt zu einer Übersetzungstabelle.
    """

    ORGANISATION_PFAD = 'lauf'

    lauf = models.ForeignKey(Lauf, on_delete=models.CASCADE, related_name='blockaden')
    grund = models.CharField('Grund', max_length=200)
    quelle = models.CharField(
        'Quelle', max_length=120, blank=True,
        help_text='Woher der Hinweis stammt — Akte, Lauf oder Prüfung.')
    seit = models.DateTimeField('Seit', default=timezone.now)
    behoben_am = models.DateTimeField('Behoben', null=True, blank=True)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Blockade'
        verbose_name_plural = 'Blockaden'
        ordering = ('-seit',)

    def __str__(self):
        return self.grund

    @property
    def tage_offen(self):
        ende = self.behoben_am or timezone.now()
        return (ende - self.seit).days

    def beheben(self):
        if self.behoben_am is None:
            self.behoben_am = timezone.now()
            self.save(update_fields=['behoben_am'])
        return self
