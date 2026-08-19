"""Der Zulauf — jeder Eingang wird zu genau einem von drei Dingen.

WARUM DER ZULAUF EINE EIGENE FLÄCHE IST

In einer Verwaltung mit drei Personen beginnt der Tag mit vierzig Eingängen,
und die eigentliche Arbeit ist nicht das Beantworten, sondern das **Zuordnen**:
Zu welcher Akte gehört das, und löst es einen Vorgang aus? Bisher war
Kommunikation ein Icon in der Topbar. Das Konzept stellt sie nach vorn.

Ein Eingang endet in genau einem von drei Zuständen:

1. einer Akte zugeordnet und abgelegt,
2. Auslöser eines neuen Falls,
3. bewusst abgelegt ohne Folge.

Was übrig bleibt, ist der Arbeitsvorrat.

WARUM NIE GERATEN WIRD

Ein falsch zugeordneter Eingang ist teurer als ein nicht zugeordneter. Die
Rechnung einer fremden Liegenschaft im eigenen Bestand fällt niemandem auf —
eine Rechnung nun einmal kommt von aussen. Deshalb kennt `Vorschlag` einen
Zustand `keiner`, und der ist kein Versagen, sondern die richtige Antwort, wenn
die Merkmale nicht tragen.

VERHÄLTNIS ZU `finance.ZahlerZuordnung`

Für Bankzahlungen gibt es die gelernte Zuordnung «Absendername → Mietvertrag»
bereits. Sie bleibt, wo sie ist. `Zuordnungsregel` hier ist das Gegenstück für
Dokumente und Nachrichten und kennt zusätzlich das Ziel «Fall eröffnen». Beide
normalisieren Namen nach demselben Verfahren, damit sie dasselbe verstehen.
"""
import re

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from core.organisation_kette import organisation_aus_kontext
from core.tenancy import AlleOrganisationenManager, TenantManager


def normalisieren(text):
    """Kleinbuchstaben und Ziffern, alles andere weg.

    Damit fallen «Muster AG», «MUSTER  AG.» und «muster-ag» zusammen. Dasselbe
    Verfahren wie bei `finance.ZahlerZuordnung`, damit beide dieselben
    Schreibweisen gleich behandeln.
    """
    return re.sub(r'[^a-z0-9]+', '', (text or '').lower())


class ZulaufQuerySet(models.QuerySet):
    def offen(self):
        return self.filter(status=Eingang.OFFEN)


class Eingang(models.Model):
    """Ein einzelner Eingang im Zulauf."""

    MAIL, POST, SCAN, PORTAL, BANK = 'mail', 'post', 'scan', 'portal', 'bank'
    QUELLEN = [
        (MAIL, 'E-Mail'),
        (POST, 'Post'),
        (SCAN, 'Scan'),
        (PORTAL, 'Portalmeldung'),
        (BANK, 'Bankeingang'),
    ]

    OFFEN, ZUGEORDNET, ABGELEGT = 'offen', 'zugeordnet', 'abgelegt'
    STATUS = [
        (OFFEN, 'Offen'),
        (ZUGEORDNET, 'Zugeordnet'),
        (ABGELEGT, 'Abgelegt ohne Folge'),
    ]

    organisation = models.ForeignKey(
        'crm.Organisation', on_delete=models.CASCADE,
        related_name='zulauf', editable=False, verbose_name='Organisation')
    quelle = models.CharField('Quelle', max_length=10, choices=QUELLEN)
    eingegangen_am = models.DateTimeField('Eingegangen', default=timezone.now)

    betreff = models.CharField('Betreff', max_length=300, blank=True)
    absender = models.CharField('Absender', max_length=200, blank=True)
    absender_norm = models.CharField(
        'Absender (normalisiert)', max_length=200, blank=True, db_index=True)
    absender_email = models.EmailField('Absenderadresse', blank=True)
    referenz = models.CharField(
        'Referenz', max_length=60, blank=True, db_index=True,
        help_text='QR-Referenz, Sendungsnummer oder ähnliches.')
    text = models.TextField('Inhalt', blank=True)

    status = models.CharField('Status', max_length=12, choices=STATUS, default=OFFEN)
    akte_typ = models.ForeignKey(
        ContentType, on_delete=models.PROTECT, null=True, blank=True)
    akte_id = models.PositiveIntegerField(null=True, blank=True)
    akte = GenericForeignKey('akte_typ', 'akte_id')
    fall = models.ForeignKey(
        'faelle.Fall', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='eingaenge')

    erledigt_am = models.DateTimeField('Erledigt', null=True, blank=True)
    erledigt_durch = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='zulauf_erledigt')
    ablage_grund = models.CharField('Grund der Ablage', max_length=200, blank=True)

    objects = TenantManager.from_queryset(ZulaufQuerySet)()
    alle_organisationen = AlleOrganisationenManager.from_queryset(ZulaufQuerySet)()

    class Meta:
        verbose_name = 'Eingang'
        verbose_name_plural = 'Zulauf'
        ordering = ('-eingegangen_am',)
        indexes = [
            models.Index(fields=('organisation', 'status')),
        ]

    def __str__(self):
        return f'{self.get_quelle_display()} · {self.betreff or self.absender or "—"}'

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_aus_kontext()
        if self.absender and not self.absender_norm:
            self.absender_norm = normalisieren(self.absender)
        super().save(*args, **kwargs)

    def ablegen(self, grund, benutzer=None):
        """Bewusst ohne Folge ablegen.

        Der Grund ist Pflicht: Ein Eingang, der ohne Vermerk verschwindet, ist
        später von einem übersehenen nicht zu unterscheiden.
        """
        if not grund or not grund.strip():
            raise ValueError('Ablegen ohne Grund wird nicht gespeichert.')
        self.status = self.ABGELEGT
        self.ablage_grund = grund.strip()
        self.erledigt_am = timezone.now()
        self.erledigt_durch = benutzer
        self.save(update_fields=['status', 'ablage_grund', 'erledigt_am',
                                 'erledigt_durch'])
        return self


class Zuordnungsregel(models.Model):
    """Eine gelernte Regel: Merkmal → Akte, wahlweise mit Fallart.

    Entsteht, wenn jemand einen Eingang zuordnet und das Muster künftig
    automatisch greifen soll. Beispiel aus dem Konzept: Ein Sozialdienst zahlt
    regelmässig für einen bestimmten Mieter — beim nächsten Mal trifft das
    Programm selbst.
    """

    ABSENDER, EMAIL, REFERENZ = 'absender', 'email', 'referenz'
    MERKMALE = [
        (ABSENDER, 'Absendername'),
        (EMAIL, 'Absenderadresse'),
        (REFERENZ, 'Referenz'),
    ]

    organisation = models.ForeignKey(
        'crm.Organisation', on_delete=models.CASCADE,
        related_name='zuordnungsregeln', editable=False)
    merkmal = models.CharField('Merkmal', max_length=12, choices=MERKMALE)
    wert = models.CharField('Wert (normalisiert)', max_length=200, db_index=True)
    wert_anzeige = models.CharField('Wert', max_length=200, blank=True)

    akte_typ = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    akte_id = models.PositiveIntegerField()
    akte = GenericForeignKey('akte_typ', 'akte_id')

    fallart = models.ForeignKey(
        'faelle.Fallart', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='zuordnungsregeln',
        help_text='Gesetzt: Ein Treffer eröffnet einen Fall dieser Art.')

    treffer = models.PositiveIntegerField('Automatisch getroffen', default=0)
    zuletzt = models.DateTimeField('Zuletzt getroffen', null=True, blank=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktiv = models.BooleanField('Aktiv', default=True)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Zuordnungsregel'
        verbose_name_plural = 'Zuordnungsregeln'
        ordering = ('-treffer',)
        constraints = [
            models.UniqueConstraint(
                fields=('organisation', 'merkmal', 'wert'),
                name='zuordnungsregel_je_merkmal_eindeutig'),
        ]

    def __str__(self):
        return f'{self.get_merkmal_display()}: {self.wert_anzeige or self.wert}'

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_aus_kontext()
        if self.wert_anzeige and not self.wert:
            self.wert = normalisieren(self.wert_anzeige)
        super().save(*args, **kwargs)

    def getroffen(self):
        self.treffer += 1
        self.zuletzt = timezone.now()
        self.save(update_fields=['treffer', 'zuletzt'])
