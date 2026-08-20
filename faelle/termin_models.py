"""Termine und Vertretung — die beiden fehlenden Bausteine der Heute-Ansicht.

WARUM ES DIESE DATEI GIBT

Der Prototyp (`mockups/konzept-struktur.html`, Screen «Heute») führt fünf
Abschnitte: Was reisst · Posteingang · **Termine** · Wartet auf mich ·
**Vertretung**. Drei davon liessen sich aus dem Bestand rechnen. Für die
beiden hier fehlten die Daten:

    Termine      Abnahmen und Besichtigungen waren ableitbar, ein
                 Eigentümergespräch nicht — es gab kein Terminmodell.
    Vertretung   `crm.Mitgliedschaft` führt Benutzer, Organisation und Rolle.
                 Kein Abwesenheitsfeld, keine Stellvertretung.

Bis 4b.7 stand deshalb in beiden Abschnitten eine ehrliche Lücke. Jetzt
tragen sie eigene Modelle.

WAS «TERMIN» NICHT IST

Kein Kalender-Ersatz und keine Synchronisation mit Outlook oder Google. Ein
Termin hier ist ein **Arbeitsanlass**: etwas, das zu einer Uhrzeit an einem
Ort stattfindet und bei dem jemand aus der Verwaltung dabei sein muss. Die
abgeleiteten Termine (Abnahme, Besichtigung) bleiben, wo sie sind — sie
werden hier **nicht** dupliziert, sondern im Arbeitsvorrat danebengelegt.
Sonst stünde dieselbe Wohnungsabnahme zweimal im Tag.

MANDANTENTRENNUNG

Beide Modelle tragen den Bezug von Anfang an (`organisation`, nicht
nullbar, `editable=False`), filtern über `TenantManager` und leiten die
Organisation im `save()` aus dem Kontext ab — dasselbe Muster wie `Fall`,
`Lauf` und `Eingang`. Ein Termin ohne Organisation wäre ein Termin, den
jeder sieht.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from core.organisation_kette import organisation_aus_kontext
from core.tenancy import AlleOrganisationenManager, TenantManager, TenantQuerySet


class TerminQuerySet(TenantQuerySet):
    def offen(self):
        return self.exclude(status__in=(Termin.ABGESAGT, Termin.ERLEDIGT))

    def zeitraum(self, von, bis):
        """Termine, die im Fenster **beginnen**.

        Nicht «die das Fenster überschneiden»: Ein dreitägiger Eintrag wäre
        kein Termin, sondern eine Abwesenheit — und die hat ihr eigenes
        Modell.
        """
        return self.filter(beginn__gte=von, beginn__lte=bis)


class TerminManager(TenantManager.from_queryset(TerminQuerySet)):
    pass


class TerminAlleManager(AlleOrganisationenManager.from_queryset(TerminQuerySet)):
    pass


class Termin(models.Model):
    """Ein Arbeitsanlass mit Uhrzeit und Ort."""

    ABNAHME, BESICHTIGUNG, GESPRAECH, BEGEHUNG, SONSTIGES = (
        'abnahme', 'besichtigung', 'gespraech', 'begehung', 'sonstiges')
    ARTEN = [
        (ABNAHME, 'Wohnungsabnahme'),
        (BESICHTIGUNG, 'Besichtigung'),
        (GESPRAECH, 'Eigentümergespräch'),
        (BEGEHUNG, 'Begehung'),
        (SONSTIGES, 'Sonstiges'),
    ]

    GEPLANT, ERLEDIGT, ABGESAGT = 'geplant', 'erledigt', 'abgesagt'
    STATUS = [(GEPLANT, 'Geplant'), (ERLEDIGT, 'Erledigt'), (ABGESAGT, 'Abgesagt')]

    #: Welche Modelle ein Termin betreffen darf. Dieselbe Liste wie beim Fall,
    #: aus demselben Grund: ein generischer Bezug erzwingt genau eine Akte,
    #: vier nullbare Fremdschlüssel erlaubten null oder vier.
    AKTENTYPEN = (
        'rentals.mietvertrag',
        'portfolio.einheit',
        'portfolio.liegenschaft',
        'crm.eigentuemer',
        'crm.mieter',
        'tickets.schadenmeldung',
    )

    organisation = models.ForeignKey(
        'crm.Organisation', on_delete=models.CASCADE, editable=False,
        related_name='termine', verbose_name='Organisation')
    art = models.CharField('Art', max_length=15, choices=ARTEN, default=SONSTIGES)
    titel = models.CharField('Titel', max_length=200)
    beginn = models.DateTimeField('Beginn')
    dauer_minuten = models.PositiveSmallIntegerField('Dauer (Minuten)', default=60)
    ort = models.CharField('Ort', max_length=200, blank=True, default='')

    akte_typ = models.ForeignKey(
        ContentType, on_delete=models.PROTECT, null=True, blank=True)
    akte_id = models.PositiveIntegerField(null=True, blank=True)
    akte = GenericForeignKey('akte_typ', 'akte_id')

    zustaendig = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        blank=True, related_name='termine')
    status = models.CharField('Status', max_length=12, choices=STATUS, default=GEPLANT)
    notiz = models.TextField('Notiz', blank=True, default='')
    erstellt_am = models.DateTimeField('Erfasst', auto_now_add=True)

    objects = TerminManager()
    alle_organisationen = TerminAlleManager()

    class Meta:
        verbose_name = 'Termin'
        verbose_name_plural = 'Termine'
        ordering = ('beginn',)
        indexes = [models.Index(fields=('organisation', 'beginn'))]

    def __str__(self):
        return f'{self.beginn:%d.%m.%Y %H:%M} · {self.titel}'

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            # Die Akte kennt ihre Organisation genauer als der Kontext —
            # dieselbe Reihenfolge wie bei `Fall`.
            self.organisation_id = (getattr(self.akte, 'organisation_id', None)
                                    or organisation_aus_kontext())
        super().save(*args, **kwargs)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.akte_typ_id:
            label = f'{self.akte_typ.app_label}.{self.akte_typ.model}'
            if label not in self.AKTENTYPEN:
                raise ValidationError(
                    {'akte_typ': f'{label} ist kein zulässiger Aktentyp. '
                                 f'Zulässig: {", ".join(self.AKTENTYPEN)}'})

    @property
    def ende(self):
        return self.beginn + timedelta(minutes=self.dauer_minuten or 0)

    @property
    def ist_vorbei(self):
        return self.ende < timezone.now()


class AbwesenheitQuerySet(TenantQuerySet):
    def laufend(self, stichtag=None):
        """Abwesenheiten, die den Stichtag einschliessen.

        `von` und `bis` sind beide **inklusiv**: Wer «bis 25.08.» abwesend
        ist, ist am 25. noch weg. Ein exklusives Ende ist die häufigste
        stille Fehlerquelle bei Zeiträumen — hier steht es deshalb im Code
        und nicht nur im Kopf.
        """
        tag = stichtag or timezone.localdate()
        return self.filter(von__lte=tag, bis__gte=tag)


class AbwesenheitManager(TenantManager.from_queryset(AbwesenheitQuerySet)):
    pass


class AbwesenheitAlleManager(
        AlleOrganisationenManager.from_queryset(AbwesenheitQuerySet)):
    pass


class Abwesenheit(models.Model):
    """Wer wann weg ist — und wer die Arbeit übernimmt.

    Umsetzung von **G8**: «Zuständigkeit statt Rolle … plus Vertretung.» Ohne
    dieses Modell war die Vertretung eine Absprache im Flur; die Fälle der
    abwesenden Person blieben in ihrem Namen liegen und niemand sah sie.

    `vertreten_durch` darf leer sein. Eine Abwesenheit ohne Vertretung ist
    kein Fehler, sondern eine Aussage — und eine, die auffallen soll: Der
    Arbeitsvorrat zeigt sie dann ausdrücklich als ungedeckt an.
    """

    FERIEN, KRANK, SCHULUNG, SONSTIGES = 'ferien', 'krank', 'schulung', 'sonstiges'
    GRUENDE = [(FERIEN, 'Ferien'), (KRANK, 'Krank'),
               (SCHULUNG, 'Schulung'), (SONSTIGES, 'Sonstiges')]

    organisation = models.ForeignKey(
        'crm.Organisation', on_delete=models.CASCADE, editable=False,
        related_name='abwesenheiten', verbose_name='Organisation')
    benutzer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='abwesenheiten', verbose_name='Wer')
    von = models.DateField('Von')
    bis = models.DateField('Bis (einschliesslich)')
    grund = models.CharField('Grund', max_length=12, choices=GRUENDE, default=FERIEN)
    vertreten_durch = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vertretungen', verbose_name='Vertretung')
    notiz = models.CharField('Notiz', max_length=200, blank=True, default='')
    erstellt_am = models.DateTimeField('Erfasst', auto_now_add=True)

    objects = AbwesenheitManager()
    alle_organisationen = AbwesenheitAlleManager()

    class Meta:
        verbose_name = 'Abwesenheit'
        verbose_name_plural = 'Abwesenheiten'
        ordering = ('von',)
        indexes = [models.Index(fields=('organisation', 'von', 'bis'))]

    def __str__(self):
        return f'{self.benutzer} {self.von:%d.%m.} – {self.bis:%d.%m.}'

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_aus_kontext()
        super().save(*args, **kwargs)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.von and self.bis and self.bis < self.von:
            raise ValidationError({'bis': 'Das Ende liegt vor dem Beginn.'})
        if self.vertreten_durch_id and self.vertreten_durch_id == self.benutzer_id:
            raise ValidationError(
                {'vertreten_durch': 'Niemand vertritt sich selbst.'})

    @property
    def tage_verbleibend(self):
        return (self.bis - timezone.localdate()).days

    @property
    def offene_faelle(self):
        """Wie viele Fälle in dieser Abwesenheit auf die Person laufen."""
        from faelle.models import Fall
        return Fall.objects.offen().filter(zustaendig=self.benutzer).count()
