"""Abonnement und Plattform-Rechnung einer Organisation (PLAN-V7 M8, D6/D7).

WAS HIER LIEGT UND WAS NICHT

Stufe und Abrechnungsintervall bleiben an `crm.Organisation.abo_plan` und
`abo_jaehrlich` (D7: eine Quelle fuer die Stufe ist `core/funktionen.py`). Hier
liegt, was dazukommt: zugebuchte Module, Bestandsschutz, der Abrechnungsstand
und der Zahlungszustand. Der Umzug von `abo_plan` in diese Tabelle ist
mechanisch und bleibt offen; er brauchte eine crm-Migration und aendert nichts am
Verhalten.

DER ZUSTAND IST GESPEICHERT, NICHT BERECHNET

`Abonnement.zustand` wird vom Abrechnungslauf und beim Zahlungseingang
nachgefuehrt. Eine Berechnung aus den Rechnungen bei jeder Anfrage kostete eine
Abfrage auf jeder Seite; so reicht `select_related` beim Laden der Organisation.

NIE LOESCHEN

Weder `Abonnement` noch `AboRechnung` werden von der Oberflaeche geloescht. Eine
Rechnung wird storniert, nicht entfernt (OR 958f: Aufbewahrung).
"""
from decimal import Decimal

from django.db import models

from core.funktionen import STUFEN_NAMEN, STUFEN_REIHENFOLGE
from core.organisation_kette import organisation_bestimmen
from core.tenancy import AlleOrganisationenManager, TenantManager


class Abonnement(models.Model):
    ZUSTAND_AKTIV = 'aktiv'
    ZUSTAND_MAHNUNG = 'mahnung'
    ZUSTAND_LESEMODUS = 'lesemodus'
    ZUSTAND_GESPERRT = 'gesperrt'
    ZUSTAENDE = [
        (ZUSTAND_AKTIV, 'Aktiv'),
        (ZUSTAND_MAHNUNG, 'Zahlung überfällig (Mahnung)'),
        (ZUSTAND_LESEMODUS, 'Lesemodus (Zahlung lange überfällig)'),
        (ZUSTAND_GESPERRT, 'Zugang gesperrt (Zahlung sehr lange überfällig)'),
    ]

    organisation = models.OneToOneField(
        'crm.Organisation', on_delete=models.CASCADE, editable=False,
        related_name='abonnement', verbose_name='Organisation')
    zusatzmodule = models.JSONField(
        'Zugebuchte Module', default=list, blank=True,
        help_text='Schlüssel aus MODULE (und einzelne Funktionen), die über die Stufe hinaus freigeschaltet sind.')
    uneingeschraenkt = models.BooleanField(
        'Bestandsschutz (alles offen, keine Grenzen)', default=False,
        help_text='Bestehende Verwaltungen behalten bis zu ihrer eigenen Planwahl jede Funktion '
                  'und jede Menge. Die Planwahl im Abonnement hebt das auf.')
    abrechnung_ab = models.DateField(
        'Abrechnung ab', null=True, blank=True,
        help_text='Leer = es wird nichts in Rechnung gestellt (Testphase / noch nicht freigegeben).')
    abgerechnet_bis = models.DateField(
        'Abgerechnet bis', null=True, blank=True,
        help_text='Letzter Tag der zuletzt in Rechnung gestellten Periode.')
    zustand = models.CharField('Zahlungszustand', max_length=12, choices=ZUSTAENDE, default=ZUSTAND_AKTIV)
    ueberfaellig_seit = models.DateField(
        'Überfällig seit', null=True, blank=True,
        help_text='Fälligkeitstag der ältesten unbezahlten Rechnung; leer = nichts überfällig.')

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Abonnement'
        verbose_name_plural = 'Abonnemente'

    def __str__(self):
        return f'Abonnement {self.organisation_id}'

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_bestimmen().pk
        super().save(*args, **kwargs)


class AboRechnung(models.Model):
    """Eine Rechnung der Plattform an eine Organisation (Debitor «Plattform»).

    Das ist NICHT `finance.Rechnung`: Dort stellt die Verwaltung ihren Mietern
    Rechnungen. Hier stellt der Betreiber der Verwaltung eine. Die Zahlung wird
    von Hand bestaetigt (ENTSCHEIDE-V7 D6: kein Zahlungsanbieter).
    """
    STATUS_OFFEN = 'offen'
    STATUS_BEZAHLT = 'bezahlt'
    STATUS_STORNIERT = 'storniert'
    STATUS = [(STATUS_OFFEN, 'Offen'), (STATUS_BEZAHLT, 'Bezahlt'), (STATUS_STORNIERT, 'Storniert')]
    INTERVALLE = [('monatlich', 'Monatlich'), ('jaehrlich', 'Jährlich')]

    organisation = models.ForeignKey(
        'crm.Organisation', on_delete=models.PROTECT, editable=False,
        related_name='abo_rechnungen', verbose_name='Organisation')
    nummer = models.CharField('Rechnungsnummer', max_length=20, blank=True, default='')
    periode_von = models.DateField('Periode von')
    periode_bis = models.DateField('Periode bis')
    stufe = models.CharField('Stufe', max_length=20, choices=[(s, STUFEN_NAMEN[s]) for s in STUFEN_REIHENFOLGE])
    intervall = models.CharField('Intervall', max_length=10, choices=INTERVALLE)
    einheiten = models.PositiveIntegerField('Einheiten bei Rechnungsstellung')
    netto = models.DecimalField('Netto (CHF)', max_digits=10, decimal_places=2)
    mwst_satz = models.DecimalField('MWST-Satz (%)', max_digits=5, decimal_places=2, null=True, blank=True,
                                    help_text='Leer = vom Betreiber nicht festgelegt, keine MWST ausgewiesen.')
    mwst_betrag = models.DecimalField('MWST (CHF)', max_digits=10, decimal_places=2, default=Decimal('0'))
    brutto = models.DecimalField('Brutto (CHF)', max_digits=10, decimal_places=2)
    rechnungsdatum = models.DateField('Rechnungsdatum')
    faellig_am = models.DateField('Fällig am')
    status = models.CharField('Status', max_length=10, choices=STATUS, default=STATUS_OFFEN)
    bezahlt_am = models.DateField('Bezahlt am', null=True, blank=True)
    erinnert_am = models.DateField('Zahlungserinnerung versandt am', null=True, blank=True)
    versendet_am = models.DateField(
        'Per Mail versandt am', null=True, blank=True,
        help_text='Letzter erfolgreicher Versand der Rechnung (oder einer Mahnung dazu) an die Verwaltung; leer = nie versandt.')
    positionen = models.JSONField(
        'Rechnungspositionen', default=list, blank=True,
        help_text='Die Zeilen der Rechnung zum Zeitpunkt der Rechnungsstellung: [{text, betrag}]. Leer bei älteren Rechnungen.')
    mahnstufe = models.PositiveSmallIntegerField(
        'Mahnstufe', default=0, help_text='0 = nicht gemahnt, 1 = 1. Mahnung versandt, 2 = 2. Mahnung (mit Mahngebühr) versandt.')
    mahngebuehr = models.DecimalField(
        'Mahngebühr (CHF)', max_digits=8, decimal_places=2, default=Decimal('0'),
        help_text='Mit der 2. Mahnung fällig; kommt zum Rechnungsbetrag und steht auf dem Einzahlungsschein.')
    qr_referenz = models.CharField('QR-Referenz', max_length=27, blank=True, default='')
    platzhalter = models.BooleanField(
        'Mit Platzhalterpreisen erstellt', default=False,
        help_text='Die Preise waren zur Rechnungsstellung noch nicht vom Betreiber festgelegt.')
    bemerkung = models.CharField('Bemerkung', max_length=240, blank=True, default='')

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Abo-Rechnung'
        verbose_name_plural = 'Abo-Rechnungen'
        ordering = ['-periode_von', '-pk']
        constraints = [
            models.UniqueConstraint(fields=['organisation', 'periode_von'],
                                    name='uniq_aborechnung_organisation_periode'),
        ]

    def __str__(self):
        return f'{self.nummer or self.pk} · {self.periode_von:%d.%m.%Y}–{self.periode_bis:%d.%m.%Y}'

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_bestimmen().pk
        super().save(*args, **kwargs)
        if not self.nummer:
            self.nummer = f'AB-{self.rechnungsdatum.year}-{self.pk:06d}'
            type(self).alle_organisationen.filter(pk=self.pk).update(nummer=self.nummer)


class Kundenstamm(models.Model):
    """Die Kundenkartei des Betreibers zu einer Verwaltung: Kontaktdaten, Ansprechperson, Status, interne Notizen.

    GEHÖRT DEM BETREIBER, NICHT DER VERWALTUNG. Die Kartei ist nur im Betreiber-Portal sichtbar und steht deshalb in
    `abo` (Datenexport und Datenreset der Verwaltung kennen diese App nicht: interne Notizen fliessen nie zum Kunden).
    Firma, Adresse, Telefon, E-Mail und MWST-Nummer stehen weiter an der `Organisation`; hier steht, was nur der Betreiber
    braucht. Die Kundennummer ergibt sich aus der Organisation (`K-0001`), sie braucht keinen eigenen Zähler.
    """
    STATUS_INTERESSENT = 'interessent'
    STATUS_TEST = 'test'
    STATUS_KUNDE = 'kunde'
    STATUS_GEKUENDIGT = 'gekuendigt'
    STATUS = [(STATUS_INTERESSENT, 'Interessent'), (STATUS_TEST, 'Testphase'), (STATUS_KUNDE, 'Kunde'),
              (STATUS_GEKUENDIGT, 'Gekündigt')]

    organisation = models.OneToOneField(
        'crm.Organisation', on_delete=models.CASCADE, editable=False, related_name='kundenstamm',
        verbose_name='Organisation')
    status = models.CharField('Kundenstatus', max_length=12, choices=STATUS, default=STATUS_KUNDE)
    natel = models.CharField('Natel (Firma)', max_length=30, blank=True, default='')
    website = models.CharField('Website', max_length=200, blank=True, default='')
    ansprechperson = models.CharField('Ansprechperson', max_length=120, blank=True, default='')
    ansprech_funktion = models.CharField('Funktion', max_length=120, blank=True, default='')
    ansprech_email = models.EmailField('E-Mail der Ansprechperson', blank=True, default='')
    ansprech_telefon = models.CharField('Telefon der Ansprechperson', max_length=30, blank=True, default='')
    ansprech_natel = models.CharField('Natel der Ansprechperson', max_length=30, blank=True, default='')
    rechnung_email = models.EmailField(
        'E-Mail für Rechnungen', blank=True, default='',
        help_text='Leer = Rechnungen und Mahnungen gehen an die E-Mail-Adresse der Verwaltung.')
    notizen = models.TextField('Interne Notizen', blank=True, default='')
    geaendert_am = models.DateTimeField('Zuletzt geändert', auto_now=True)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Kundenkartei'
        verbose_name_plural = 'Kundenkarteien'

    def __str__(self):
        return f'Kundenkartei {self.organisation_id}'

    @property
    def kundennummer(self):
        return f'K-{self.organisation_id:04d}'

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_bestimmen().pk
        super().save(*args, **kwargs)


class KundenKontakt(models.Model):
    """Ein Eintrag im Verlauf einer Kundenkartei: Anruf, Mail, Besuch oder Notiz. Nur im Betreiber-Portal sichtbar."""
    ART_ANRUF = 'anruf'
    ART_MAIL = 'mail'
    ART_BESUCH = 'besuch'
    ART_NOTIZ = 'notiz'
    #: Eine Anfrage der Verwaltung über den Support-Knopf. Sie ist offen, bis der Betreiber sie als erledigt markiert.
    ART_SUPPORT = 'support'
    ARTEN = [(ART_ANRUF, 'Anruf'), (ART_MAIL, 'E-Mail'), (ART_BESUCH, 'Besuch'), (ART_NOTIZ, 'Notiz'),
             (ART_SUPPORT, 'Support-Anfrage')]

    organisation = models.ForeignKey(
        'crm.Organisation', on_delete=models.CASCADE, editable=False, related_name='kunden_kontakte',
        verbose_name='Organisation')
    zeitpunkt = models.DateTimeField('Zeitpunkt', db_index=True)
    art = models.CharField('Art', max_length=10, choices=ARTEN, default=ART_NOTIZ)
    text = models.TextField('Eintrag')
    erfasst_von = models.CharField('Erfasst von', max_length=150, blank=True, default='')
    erledigt_am = models.DateTimeField('Erledigt am', null=True, blank=True,
                                       help_text='Nur bei Support-Anfragen: leer = noch offen.')

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Kontakteintrag'
        verbose_name_plural = 'Kontakteinträge'
        ordering = ['-zeitpunkt', '-pk']

    def __str__(self):
        return f'{self.get_art_display()} {self.zeitpunkt:%d.%m.%Y}'

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_bestimmen().pk
        super().save(*args, **kwargs)

