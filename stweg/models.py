"""STWEG: Akonto-Beiträge und Jahresabrechnung.

Eine STWEG erzielt keinen Ertrag — es gibt nur Kosten, die nach Wertquoten auf
die Stockwerkeigentümer verteilt werden. Die Eigentümer zahlen Akonto-Beiträge
(monatlich oder quartalsweise); die Jahresabrechnung stellt ihren Kostenanteil
den geleisteten Akontos gegenüber: Zahllast oder Guthaben.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.organisation_kette import OrganisationAusKette
from core.utils import get_smart_upload_path


class StwegAkonto(OrganisationAusKette):
    """Eine Akonto-Zahlung eines Stockwerkeigentümers für seine Einheit."""
    ORGANISATION_PFAD = 'einheit__liegenschaft'
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='stweg_akontos')
    datum = models.DateField(default=timezone.localdate)
    betrag = models.DecimalField("Betrag (CHF)", max_digits=10, decimal_places=2)
    bemerkung = models.CharField(max_length=200, blank=True, default='')
    #: Wofür die Zahlung ist. Die Jahresabrechnung und das Kontokorrent rechnen nur «akonto» an;
    #: Einlagen in den Erneuerungsfonds sind keine Kosten und dürfen den Kostenanteil nicht decken.
    AKONTO, FONDS = 'akonto', 'fonds'
    ZWECK_CHOICES = [(AKONTO, _('Akonto-Beitrag')), (FONDS, _('Einlage Erneuerungsfonds'))]
    zweck = models.CharField(max_length=10, choices=ZWECK_CHOICES, default=AKONTO)
    #: Die Buchung im Hauptbuch (leer bei Zahlungen aus der Zeit vor der Hauptbuch-Anbindung).
    buchung = models.ForeignKey('finance.Buchung', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='+')
    #: Stammt die Zahlung aus dem Kontoauszug-Import (auf dem Durchlaufkonto 1190 geparkt), wird sie
    #: von dort zugeordnet — sonst läge der Betrag zweimal auf dem Bankkonto.
    zahlungseingang = models.ForeignKey('finance.Zahlungseingang', on_delete=models.SET_NULL, null=True,
                                        blank=True, related_name='+')
    #: Die Rate, für die der Eigentümer bezahlt hat (Bestimmung des Schuldners, Art. 86 OR). Ohne Angabe wird die
    #: Zahlung der ältesten offenen Forderung angerechnet (`stweg.inkasso`).
    vorschreibung = models.ForeignKey('stweg.StwegVorschreibung', on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='+')

    class Meta:
        db_table = 'stweg_akonto'
        ordering = ['datum', 'id']
        verbose_name = 'Akonto-Zahlung'
        verbose_name_plural = 'Akonto-Zahlungen'

    def __str__(self):
        return f"{self.einheit.bezeichnung}: CHF {self.betrag} ({self.datum})"


class StwegAbrechnung(OrganisationAusKette):
    """Jahresabrechnung einer STWEG-Gemeinschaft (ein Kopf je Liegenschaft und Jahr)."""
    ORGANISATION_PFAD = 'liegenschaft'
    STATUS_ENTWURF = 'entwurf'
    STATUS_ABGESCHLOSSEN = 'abgeschlossen'
    STATUS_CHOICES = [(STATUS_ENTWURF, _('Entwurf')), (STATUS_ABGESCHLOSSEN, _('Abgeschlossen'))]

    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE,
                                     related_name='stweg_abrechnungen')
    jahr = models.PositiveIntegerField()
    gesamtkosten = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=14, choices=STATUS_CHOICES, default=STATUS_ENTWURF)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'stweg_abrechnung'
        ordering = ['-jahr']
        constraints = [models.UniqueConstraint(fields=['liegenschaft', 'jahr'],
                                               name='stweg_abrechnung_je_liegenschaft_und_jahr')]

    def __str__(self):
        return f"STWEG-Abrechnung {self.jahr}: {self.liegenschaft}"


class StwegAbrechnungKosten(OrganisationAusKette):
    """Eine Kostenzeile der Abrechnung — Momentaufnahme zum Zeitpunkt der Berechnung.

    Die Abrechnung muss auch dann stimmen, wenn eine Rechnung später geändert
    oder storniert wird; sie liest ihre Kosten deshalb aus dieser Tabelle, nicht
    aus den Kreditorenrechnungen."""
    ORGANISATION_PFAD = 'abrechnung'
    abrechnung = models.ForeignKey(StwegAbrechnung, on_delete=models.CASCADE, related_name='kostenzeilen')
    datum = models.DateField(null=True, blank=True)
    lieferant = models.CharField(max_length=200, blank=True, default='')
    text = models.CharField(max_length=200, blank=True, default='')
    betrag = models.DecimalField(max_digits=12, decimal_places=2)
    #: Nach welchem Schlüssel diese Zeile verteilt wurde (Name als Momentaufnahme: die
    #: Abrechnung muss lesbar bleiben, auch wenn der Schlüssel später umbenannt wird).
    schluessel = models.ForeignKey('stweg.StwegSchluessel', on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='+')
    schluessel_name = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        db_table = 'stweg_abrechnung_kosten'
        ordering = ['datum', 'id']


class StwegAbrechnungPosition(OrganisationAusKette):
    """Anteil einer Einheit an der Jahresabrechnung."""
    ORGANISATION_PFAD = 'abrechnung'
    abrechnung = models.ForeignKey(StwegAbrechnung, on_delete=models.CASCADE, related_name='positionen')
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.PROTECT, related_name='stweg_positionen')
    eigentuemer = models.ForeignKey('crm.Eigentuemer', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    wertquote = models.DecimalField(max_digits=7, decimal_places=2)
    wertquote_total = models.PositiveIntegerField()
    kostenanteil = models.DecimalField(max_digits=12, decimal_places=2)
    akonto = models.DecimalField(max_digits=12, decimal_places=2)
    #: Kostenanteil − Akonto. Positiv = Nachzahlung (Zahllast), negativ = Guthaben.
    saldo = models.DecimalField(max_digits=12, decimal_places=2)
    #: Die Buchungen des Abschlusses dieser Position (Hauptbuch).
    buchungen = models.ManyToManyField('finance.Buchung', blank=True, related_name='+')

    class Meta:
        db_table = 'stweg_abrechnung_position'
        ordering = ['einheit_id']

    @property
    def ist_zahllast(self):
        return self.saldo > 0

    @property
    def guthaben(self):
        return -self.saldo if self.saldo < 0 else Decimal('0.00')

    @property
    def zahllast(self):
        return self.saldo if self.saldo > 0 else Decimal('0.00')


# ──────────────────────────────────────────────────────────────────────────
# DIGITALER ABLAUF: Versammlung, Traktanden, Beschlüsse, Anfragen, Versand
#
# Rechtswerte stehen hier NICHT fest verdrahtet. Weder die Einladungsfrist noch
# die nötige Mehrheit werden aus dem Gedächtnis eingesetzt: Die Frist ist ein
# Datenfeld (Vorgabe 10 Tage, Reglement kann abweichen), die Mehrheitsart wählt
# die Verwaltung je Traktandum. Das System RECHNET einen Vorschlag; festgestellt
# wird das Ergebnis von einer Person (`StwegTraktandum.feststellen`).
# ──────────────────────────────────────────────────────────────────────────

class Versammlung(OrganisationAusKette):
    """Eine Stockwerkeigentümerversammlung (ordentlich oder ausserordentlich)."""
    ORGANISATION_PFAD = 'liegenschaft'
    ART_CHOICES = [('ordentlich', _('Ordentliche Versammlung')),
                   ('ausserordentlich', _('Ausserordentliche Versammlung'))]
    ENTWURF, EINGELADEN, DURCHGEFUEHRT, PROTOKOLLIERT = (
        'entwurf', 'eingeladen', 'durchgefuehrt', 'protokolliert')
    STATUS_CHOICES = [(ENTWURF, _('Entwurf')), (EINGELADEN, _('Eingeladen')),
                      (DURCHGEFUEHRT, _('Durchgeführt')), (PROTOKOLLIERT, _('Protokoll versendet'))]

    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE,
                                     related_name='versammlungen')
    art = models.CharField(max_length=20, choices=ART_CHOICES, default='ordentlich')
    titel = models.CharField(max_length=200)
    datum = models.DateTimeField("Beginn")
    ort = models.CharField(max_length=200, blank=True, default='')
    #: Mindestabstand Einladung → Versammlung in Tagen. Vorgabe 10; das Reglement
    #: der Gemeinschaft kann eine andere Frist vorsehen — hier eintragen. Die
    #: Rechtsgrundlage ist vor Gebrauch von der Verwaltung zu bestätigen.
    einladungsfrist_tage = models.PositiveSmallIntegerField(default=10)
    #: Digitale Teilnahme und Stimmabgabe im Portal (E-Voting) während der Versammlung. Die
    #: Verwaltung kann Stimmen weiterhin von Hand erfassen (Anwesende im Saal).
    evoting = models.BooleanField("E-Voting im Portal", default=False)
    evoting_bis = models.DateTimeField("E-Voting offen bis", null=True, blank=True)
    status = models.CharField(max_length=14, choices=STATUS_CHOICES, default=ENTWURF)
    leitung = models.CharField("Versammlungsleitung", max_length=120, blank=True, default='')
    protokollfuehrung = models.CharField(max_length=120, blank=True, default='')
    einladung_versendet_am = models.DateTimeField(null=True, blank=True)
    protokoll_text = models.TextField(blank=True, default='')
    protokoll_versendet_am = models.DateTimeField(null=True, blank=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'stweg_versammlung'
        ordering = ['-datum']
        verbose_name = 'Versammlung'
        verbose_name_plural = 'Versammlungen'

    def __str__(self):
        return f"{self.titel} ({self.datum:%d.%m.%Y})"


class Traktandum(OrganisationAusKette):
    """Ein Traktandum mit Antrag, Mehrheitsart und (nach der Versammlung) Ergebnis."""
    ORGANISATION_PFAD = 'versammlung'
    #: Wie die Mehrheit GERECHNET wird. Welche davon für ein Geschäft verlangt
    #: ist (Gesetz oder Reglement), bestimmt die Verwaltung — nicht dieses System.
    MEHRHEIT_CHOICES = [
        ('einfach_koepfe', _('Mehrheit der Stimmenden (nach Köpfen)')),
        ('einfach_quoten', _('Mehrheit der Stimmenden (nach Wertquoten)')),
        ('doppelt', _('Mehrheit nach Köpfen UND Wertquoten (der Stimmenden)')),
        ('doppelt_aller', _('Mehrheit aller Eigentümer UND aller Wertquoten')),
        ('doppelt_anwesende', _('Mehrheit der anwesenden Eigentümer UND mehr als die Hälfte aller Wertquoten')),
        ('einstimmig', _('Einstimmigkeit aller Eigentümer')),
        ('kenntnisnahme', _('Zur Kenntnisnahme (keine Abstimmung)')),
    ]
    OFFEN, ANGENOMMEN, ABGELEHNT, VERTAGT, KENNTNIS = (
        'offen', 'angenommen', 'abgelehnt', 'vertagt', 'kenntnis')
    ERGEBNIS_CHOICES = [(OFFEN, _('Offen')), (ANGENOMMEN, _('Angenommen')), (ABGELEHNT, _('Abgelehnt')),
                        (VERTAGT, _('Vertagt')), (KENNTNIS, _('Zur Kenntnis genommen'))]

    versammlung = models.ForeignKey(Versammlung, on_delete=models.CASCADE, related_name='traktanden')
    nr = models.PositiveSmallIntegerField()
    titel = models.CharField(max_length=200)
    beschreibung = models.TextField(blank=True, default='')
    antrag = models.TextField("Antrag der Verwaltung", blank=True, default='')
    mehrheitsart = models.CharField(max_length=20, choices=MEHRHEIT_CHOICES, default='einfach_koepfe')
    rechtsgrundlage = models.CharField(
        "Rechtsgrundlage / Reglement", max_length=200, blank=True, default='',
        help_text='Von der Verwaltung zu bestätigen; wird nicht automatisch ermittelt.')
    ergebnis = models.CharField(max_length=10, choices=ERGEBNIS_CHOICES, default=OFFEN)
    beschlusstext = models.TextField(blank=True, default='')
    # Zahlen zum Zeitpunkt der Feststellung (das Protokoll muss stabil bleiben,
    # auch wenn später Anwesenheit oder Stimmen noch korrigiert werden).
    ja_koepfe = models.PositiveSmallIntegerField(default=0)
    nein_koepfe = models.PositiveSmallIntegerField(default=0)
    enthaltung_koepfe = models.PositiveSmallIntegerField(default=0)
    ja_quoten = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'))
    nein_quoten = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'))
    enthaltung_quoten = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'))
    festgestellt_am = models.DateTimeField(null=True, blank=True)
    # Vollzug: aus einem angenommenen Beschluss entsteht eine Pendenz.
    vollzug_aufgabe = models.CharField("Vollzug (Aufgabe)", max_length=200, blank=True, default='')
    vollzug_faellig_am = models.DateField(null=True, blank=True)
    #: Hängt ein Budget an diesem Traktandum, löst ein angenommener Beschluss die
    #: Akonto-Vorschreibungen aus (`stweg.budget.budget_genehmigen`), ein abgelehnter
    #: setzt das Budget zurück auf «abgelehnt».
    budget = models.ForeignKey('stweg.StwegBudget', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='traktanden')
    #: Ergebnis festgestellt, obwohl die Gemeinschaft laut ihren Vorgaben nicht beschlussfähig war
    #: (die Verwaltung hat das ausdrücklich bestätigt). Steht im Protokoll.
    ohne_beschlussfaehigkeit = models.BooleanField(default=False)

    class Meta:
        db_table = 'stweg_traktandum'
        ordering = ['versammlung_id', 'nr']
        constraints = [models.UniqueConstraint(fields=['versammlung', 'nr'],
                                               name='stweg_traktandum_nr_je_versammlung')]

    def __str__(self):
        return f"{self.nr}. {self.titel}"


class Anwesenheit(OrganisationAusKette):
    """Wer ist für welche Einheit in der Versammlung (selbst oder vertreten)?"""
    ORGANISATION_PFAD = 'versammlung'
    ANWESEND, VERTRETEN, ABWESEND = 'anwesend', 'vertreten', 'abwesend'
    ART_CHOICES = [(ANWESEND, _('Anwesend')), (VERTRETEN, _('Vertreten (Vollmacht)')),
                   (ABWESEND, _('Abwesend'))]
    versammlung = models.ForeignKey(Versammlung, on_delete=models.CASCADE, related_name='anwesenheiten')
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='+')
    art = models.CharField(max_length=10, choices=ART_CHOICES, default=ABWESEND)
    vertreter = models.CharField("Vertreten durch", max_length=120, blank=True, default='')

    class Meta:
        db_table = 'stweg_anwesenheit'
        constraints = [models.UniqueConstraint(fields=['versammlung', 'einheit'],
                                               name='stweg_anwesenheit_je_einheit')]

    @property
    def stimmberechtigt_vertreten(self):
        return self.art in (self.ANWESEND, self.VERTRETEN)


class Stimme(OrganisationAusKette):
    """Die Stimme einer Einheit zu einem Traktandum."""
    ORGANISATION_PFAD = 'traktandum'
    JA, NEIN, ENTHALTUNG = 'ja', 'nein', 'enthaltung'
    WERT_CHOICES = [(JA, _('Ja')), (NEIN, _('Nein')), (ENTHALTUNG, _('Enthaltung'))]
    traktandum = models.ForeignKey(Traktandum, on_delete=models.CASCADE, related_name='stimmen')
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='+')
    wert = models.CharField(max_length=10, choices=WERT_CHOICES)
    #: Wie und wann die geltende Stimme abgegeben wurde. Jede Abgabe und Änderung steht
    #: zusätzlich unveränderlich in `StimmeEreignis`.
    kanal = models.CharField(max_length=10, default='verwaltung')
    abgegeben_am = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'stweg_stimme'
        constraints = [models.UniqueConstraint(fields=['traktandum', 'einheit'],
                                               name='stweg_stimme_je_einheit')]


class StwegAnfrage(OrganisationAusKette):
    """Anfrage eines Stockwerkeigentümers an die Verwaltung (Portal, Mail, Telefon …)."""
    ORGANISATION_PFAD = 'liegenschaft'
    NEU, IN_BEARBEITUNG, BEANTWORTET, ERLEDIGT = 'neu', 'in_bearbeitung', 'beantwortet', 'erledigt'
    STATUS_CHOICES = [(NEU, _('Neu')), (IN_BEARBEITUNG, _('In Bearbeitung')),
                      (BEANTWORTET, _('Beantwortet')), (ERLEDIGT, _('Erledigt'))]
    KANAL_CHOICES = [('portal', _('Portal')), ('email', _('E-Mail')), ('telefon', _('Telefon')),
                     ('brief', _('Brief')), ('persoenlich', _('Persönlich'))]
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE,
                                     related_name='stweg_anfragen')
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='stweg_anfragen')
    eigentuemer = models.ForeignKey('crm.Eigentuemer', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='stweg_anfragen')
    betreff = models.CharField(max_length=200)
    text = models.TextField(blank=True, default='')
    kanal = models.CharField(max_length=12, choices=KANAL_CHOICES, default='portal')
    status = models.CharField(max_length=14, choices=STATUS_CHOICES, default=NEU)
    antwort = models.TextField(blank=True, default='')
    beantwortet_am = models.DateTimeField(null=True, blank=True)
    faellig_am = models.DateField(null=True, blank=True)
    #: Anfrage soll an einer Versammlung behandelt werden.
    traktandum = models.ForeignKey(Traktandum, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='anfragen')
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'stweg_anfrage'
        ordering = ['-erstellt_am']
        verbose_name = 'Anfrage'
        verbose_name_plural = 'Anfragen'

    def __str__(self):
        return self.betreff


class StwegVersand(OrganisationAusKette):
    """Protokoll jeder Zustellung (Einladung, Protokoll) an einen Eigentümer.

    Beweisfunktion: Wer wann auf welchem Weg eingeladen wurde, muss sich später
    belegen lassen — etwa wenn ein Beschluss wegen Einladungsmängeln angefochten
    wird. Fehlschläge werden festgehalten, nicht verschluckt.
    """
    ORGANISATION_PFAD = 'versammlung'
    EINLADUNG, PROTOKOLL = 'einladung', 'protokoll'
    ART_CHOICES = [(EINLADUNG, _('Einladung')), (PROTOKOLL, _('Protokoll'))]
    GESENDET, FEHLER, POST = 'gesendet', 'fehler', 'post_noetig'
    STATUS_CHOICES = [(GESENDET, _('Per E-Mail gesendet')), (FEHLER, _('Fehler beim Versand')),
                      (POST, _('Per Post zustellen (keine E-Mail-Adresse)'))]
    versammlung = models.ForeignKey(Versammlung, on_delete=models.CASCADE, related_name='versaende')
    art = models.CharField(max_length=10, choices=ART_CHOICES)
    eigentuemer = models.ForeignKey('crm.Eigentuemer', on_delete=models.SET_NULL, null=True,
                                    related_name='+')
    email = models.CharField(max_length=254, blank=True, default='')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES)
    zeitpunkt = models.DateTimeField(auto_now_add=True)
    fehler = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        db_table = 'stweg_versand'
        ordering = ['-zeitpunkt']


class Vollmacht(OrganisationAusKette):
    """Vollmacht eines Stockwerkeigentümers für EINE Versammlung und EINE Einheit.

    Wer nicht teilnimmt, benennt vorab, wer ihn vertritt. Beim Eröffnen der
    Versammlung (`durchfuehren`) wird die Einheit als «vertreten» erfasst. Ein
    Widerruf bleibt als Zeile erhalten (`widerrufen_am`) — wer wann wen
    bevollmächtigt hat, ist später belegbar."""
    ORGANISATION_PFAD = 'versammlung'
    versammlung = models.ForeignKey(Versammlung, on_delete=models.CASCADE, related_name='vollmachten')
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='+')
    bevollmaechtigter = models.CharField("Vertreten durch", max_length=120)
    erteilt_von = models.ForeignKey('crm.Eigentuemer', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    kanal = models.CharField(max_length=12, default='portal',
                             choices=[('portal', _('Portal')), ('verwaltung', _('Von der Verwaltung erfasst'))])
    erteilt_am = models.DateTimeField(auto_now_add=True)
    widerrufen_am = models.DateTimeField(null=True, blank=True)
    #: Optional: das unterschriebene Original als Scan (PDF oder Bild). Die digitale Erfassung gilt auch
    #: ohne; das System prüft die Unterschrift nicht und führt keine Beglaubigung.
    dokument = models.FileField(upload_to=get_smart_upload_path, null=True, blank=True)

    class Meta:
        db_table = 'stweg_vollmacht'
        ordering = ['erteilt_am']
        constraints = [models.UniqueConstraint(
            fields=['versammlung', 'einheit'], condition=models.Q(widerrufen_am__isnull=True),
            name='stweg_vollmacht_eine_gueltige_je_einheit')]

    @property
    def gueltig(self):
        return self.widerrufen_am is None


class Zirkularbeschluss(OrganisationAusKette):
    """Beschluss auf dem Zirkularweg: Antrag an alle Eigentümer, Abstimmung bis zu einer Frist,
    ohne Versammlung.

    Welche Mehrheit gilt — und ob ein Zirkularbeschluss für das Geschäft überhaupt
    zulässig ist —, bestimmen Gesetz und Reglement. Vorgabe ist die strengste Art
    (Einstimmigkeit aller Eigentümer); die Verwaltung wählt sie je Beschluss und
    hält die Grundlage fest. Wie bei der Versammlung rechnet das System einen
    Vorschlag, festgestellt wird er von einer Person."""
    ORGANISATION_PFAD = 'liegenschaft'
    ENTWURF, LAUFEND, ABGESCHLOSSEN = 'entwurf', 'laufend', 'abgeschlossen'
    STATUS_CHOICES = [(ENTWURF, _('Entwurf')), (LAUFEND, _('Läuft')), (ABGESCHLOSSEN, _('Abgeschlossen'))]

    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE,
                                     related_name='zirkularbeschluesse')
    titel = models.CharField(max_length=200)
    antrag = models.TextField("Antrag")
    begruendung = models.TextField(blank=True, default='')
    mehrheitsart = models.CharField(max_length=20, choices=Traktandum.MEHRHEIT_CHOICES, default='einstimmig')
    rechtsgrundlage = models.CharField(max_length=200, blank=True, default='')
    frist_bis = models.DateField("Abstimmung bis")
    status = models.CharField(max_length=14, choices=STATUS_CHOICES, default=ENTWURF)
    versendet_am = models.DateTimeField(null=True, blank=True)
    ergebnis = models.CharField(max_length=10, choices=Traktandum.ERGEBNIS_CHOICES, default=Traktandum.OFFEN)
    beschlusstext = models.TextField(blank=True, default='')
    ja_koepfe = models.PositiveSmallIntegerField(default=0)
    nein_koepfe = models.PositiveSmallIntegerField(default=0)
    enthaltung_koepfe = models.PositiveSmallIntegerField(default=0)
    ja_quoten = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'))
    nein_quoten = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'))
    enthaltung_quoten = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'))
    festgestellt_am = models.DateTimeField(null=True, blank=True)
    ergebnis_versendet_am = models.DateTimeField(null=True, blank=True)
    vollzug_aufgabe = models.CharField(max_length=200, blank=True, default='')
    vollzug_faellig_am = models.DateField(null=True, blank=True)
    #: Wird ein Budget auf dem Zirkularweg beschlossen, löst ein angenommener Beschluss die
    #: Akonto-Vorschreibungen aus (wie beim Traktandum).
    budget = models.ForeignKey('stweg.StwegBudget', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='zirkulare')
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'stweg_zirkular'
        ordering = ['-erstellt_am']
        verbose_name = 'Zirkularbeschluss'
        verbose_name_plural = 'Zirkularbeschlüsse'

    def __str__(self):
        return self.titel


class ZirkularStimme(OrganisationAusKette):
    """Die Stimme einer Einheit zu einem Zirkularbeschluss."""
    ORGANISATION_PFAD = 'zirkular'
    zirkular = models.ForeignKey(Zirkularbeschluss, on_delete=models.CASCADE, related_name='stimmen')
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='+')
    wert = models.CharField(max_length=10, choices=Stimme.WERT_CHOICES)
    kanal = models.CharField(max_length=12, default='portal',
                             choices=[('portal', _('Portal')), ('verwaltung', _('Von der Verwaltung erfasst'))])
    abgegeben_am = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'stweg_zirkular_stimme'
        constraints = [models.UniqueConstraint(fields=['zirkular', 'einheit'],
                                               name='stweg_zirkular_stimme_je_einheit')]


class ZirkularVersand(OrganisationAusKette):
    """Zustellprotokoll zum Zirkularbeschluss (Antrag, Ergebnis)."""
    ORGANISATION_PFAD = 'zirkular'
    ANTRAG, ERGEBNIS = 'antrag', 'ergebnis'
    ART_CHOICES = [(ANTRAG, _('Antrag')), (ERGEBNIS, _('Ergebnis'))]
    zirkular = models.ForeignKey(Zirkularbeschluss, on_delete=models.CASCADE, related_name='versaende')
    art = models.CharField(max_length=10, choices=ART_CHOICES)
    eigentuemer = models.ForeignKey('crm.Eigentuemer', on_delete=models.SET_NULL, null=True,
                                    related_name='+')
    email = models.CharField(max_length=254, blank=True, default='')
    status = models.CharField(max_length=12, choices=StwegVersand.STATUS_CHOICES)
    zeitpunkt = models.DateTimeField(auto_now_add=True)
    fehler = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        db_table = 'stweg_zirkular_versand'
        ordering = ['-zeitpunkt']


# ──────────────────────────────────────────────────────────────────────────
# VERTEILSCHLÜSSEL
#
# Nicht jede Kostenart wird nach Wertquote verteilt: Der Lift kostet das Erdgeschoss
# nichts, die Heizung richtet sich nach Fläche oder Volumen. Je Liegenschaft sind
# beliebig viele Schlüssel definierbar; jede Kostenart (Buchungskonto) ist einem
# Schlüssel zugeordnet, nicht zugeordnete Kosten laufen über den Standardschlüssel.
# ──────────────────────────────────────────────────────────────────────────

class StwegSchluessel(OrganisationAusKette):
    """Ein Verteilschlüssel der Gemeinschaft."""
    ORGANISATION_PFAD = 'liegenschaft'
    WERTQUOTE, FLAECHE, VOLUMEN, MANUELL = 'wertquote', 'flaeche', 'volumen', 'manuell'
    ART_CHOICES = [
        (WERTQUOTE, _('Wertquote (aus der Einheit)')),
        (FLAECHE, _('Fläche m² (aus der Einheit)')),
        (VOLUMEN, _('Volumen m³ (aus der Einheit)')),
        (MANUELL, _('Eigene Anteile je Einheit (z. B. Lift)')),
    ]
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE,
                                     related_name='stweg_schluessel')
    name = models.CharField(max_length=100)
    art = models.CharField(max_length=10, choices=ART_CHOICES, default=WERTQUOTE)
    #: Genau ein Standardschlüssel je Gemeinschaft nimmt alle Kosten ohne Zuordnung auf.
    ist_standard = models.BooleanField(default=False)
    bemerkung = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        db_table = 'stweg_schluessel'
        ordering = ['name']
        verbose_name = 'Verteilschlüssel'
        verbose_name_plural = 'Verteilschlüssel'
        constraints = [
            models.UniqueConstraint(fields=['liegenschaft', 'name'], name='stweg_schluessel_name_je_lg'),
            models.UniqueConstraint(fields=['liegenschaft'], condition=models.Q(ist_standard=True),
                                    name='stweg_schluessel_ein_standard_je_lg'),
        ]

    def __str__(self):
        return self.name


class StwegSchluesselAnteil(OrganisationAusKette):
    """Anteil einer Einheit an einem Schlüssel der Art «manuell». 0 = trägt nichts."""
    ORGANISATION_PFAD = 'schluessel'
    schluessel = models.ForeignKey(StwegSchluessel, on_delete=models.CASCADE, related_name='anteile')
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='+')
    anteil = models.DecimalField(max_digits=12, decimal_places=4)

    class Meta:
        db_table = 'stweg_schluessel_anteil'
        constraints = [
            models.UniqueConstraint(fields=['schluessel', 'einheit'], name='stweg_anteil_je_einheit'),
            models.CheckConstraint(condition=models.Q(anteil__gte=0), name='stweg_anteil_nicht_negativ'),
        ]


class StwegKostenzuordnung(OrganisationAusKette):
    """Welcher Schlüssel gilt für Kosten auf diesem Buchungskonto?"""
    ORGANISATION_PFAD = 'liegenschaft'
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE,
                                     related_name='stweg_kostenzuordnungen')
    konto = models.ForeignKey('finance.Buchungskonto', on_delete=models.CASCADE, related_name='+')
    schluessel = models.ForeignKey(StwegSchluessel, on_delete=models.PROTECT, related_name='zuordnungen')

    class Meta:
        db_table = 'stweg_kostenzuordnung'
        constraints = [models.UniqueConstraint(fields=['liegenschaft', 'konto'],
                                               name='stweg_zuordnung_je_konto')]


class StwegAbrechnungAnteil(OrganisationAusKette):
    """Wie sich der Kostenanteil einer Einheit auf die Schlüssel verteilt (Momentaufnahme)."""
    ORGANISATION_PFAD = 'position'
    position = models.ForeignKey(StwegAbrechnungPosition, on_delete=models.CASCADE,
                                 related_name='schluesselanteile')
    schluessel = models.ForeignKey(StwegSchluessel, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    schluessel_name = models.CharField(max_length=100)
    gewicht = models.DecimalField(max_digits=14, decimal_places=4)
    gewicht_total = models.DecimalField(max_digits=14, decimal_places=4)
    kosten_total = models.DecimalField(max_digits=12, decimal_places=2)
    betrag = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = 'stweg_abrechnung_anteil'
        ordering = ['schluessel_name', 'id']


# ──────────────────────────────────────────────────────────────────────────
# BUDGET und AKONTO-VORSCHREIBUNG
#
# Die Verwaltung stellt das Jahresbudget auf (Positionen je Verteilschlüssel), die
# Versammlung genehmigt es. Mit dem angenommenen Beschluss entstehen die Akonto-
# Vorschreibungen: je Einheit der Jahresbetrag nach den Schlüsseln der Positionen,
# in Raten. Der Erneuerungsfonds ist nicht Teil davon (`stweg.fonds`).
# ──────────────────────────────────────────────────────────────────────────

class StwegBudget(OrganisationAusKette):
    ORGANISATION_PFAD = 'liegenschaft'
    ENTWURF, VORGELEGT, GENEHMIGT, ABGELEHNT = 'entwurf', 'vorgelegt', 'genehmigt', 'abgelehnt'
    STATUS_CHOICES = [(ENTWURF, _('Entwurf')), (VORGELEGT, _('Der Versammlung vorgelegt')),
                      (GENEHMIGT, _('Genehmigt')), (ABGELEHNT, _('Abgelehnt'))]
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE,
                                     related_name='stweg_budgets')
    jahr = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ENTWURF)
    #: Zahl der Akonto-Raten und Fälligkeit der ersten (die weiteren folgen im gleichen Abstand).
    raten = models.PositiveSmallIntegerField(default=4)
    erste_faelligkeit = models.DateField(null=True, blank=True)
    bemerkung = models.TextField(blank=True, default='')
    genehmigt_am = models.DateTimeField(null=True, blank=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'stweg_budget'
        ordering = ['-jahr']
        verbose_name = 'Budget'
        constraints = [models.UniqueConstraint(fields=['liegenschaft', 'jahr'],
                                               name='stweg_budget_je_lg_und_jahr'),
                       models.CheckConstraint(condition=models.Q(raten__in=(1, 2, 3, 4, 6, 12)),
                                              name='stweg_budget_raten_gueltig')]

    def __str__(self):
        return f'Budget {self.jahr} {self.liegenschaft}'

    @property
    def total(self):
        return sum((p.betrag for p in self.positionen.all()), Decimal('0.00'))


class StwegBudgetPosition(OrganisationAusKette):
    ORGANISATION_PFAD = 'budget'
    budget = models.ForeignKey(StwegBudget, on_delete=models.CASCADE, related_name='positionen')
    bezeichnung = models.CharField(max_length=200)
    schluessel = models.ForeignKey(StwegSchluessel, on_delete=models.PROTECT, related_name='+')
    betrag = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = 'stweg_budget_position'
        ordering = ['id']


class StwegVorschreibung(OrganisationAusKette):
    """Eine Akonto-Rate, die einer Einheit nach dem genehmigten Budget vorgeschrieben wird."""
    ORGANISATION_PFAD = 'budget'
    budget = models.ForeignKey(StwegBudget, on_delete=models.CASCADE, related_name='vorschreibungen')
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.PROTECT, related_name='stweg_vorschreibungen')
    eigentuemer = models.ForeignKey('crm.Eigentuemer', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    rate_nr = models.PositiveSmallIntegerField()
    rate_total = models.PositiveSmallIntegerField()
    faellig_am = models.DateField()
    betrag = models.DecimalField(max_digits=12, decimal_places=2)
    #: Jahresbetrag der Einheit und seine Aufteilung nach Schlüsseln (Momentaufnahme).
    jahresbetrag = models.DecimalField(max_digits=12, decimal_places=2)
    aufteilung = models.JSONField(default=list, blank=True)
    versendet_am = models.DateTimeField(null=True, blank=True)
    #: Buchung im Hauptbuch: Soll 1110 Forderungen Stockwerkeigentümer / Haben 2035 Akonto-Beiträge.
    buchung = models.ForeignKey('finance.Buchung', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='+')

    class Meta:
        db_table = 'stweg_vorschreibung'
        ordering = ['faellig_am', 'einheit_id']
        constraints = [models.UniqueConstraint(fields=['budget', 'einheit', 'rate_nr'],
                                               name='stweg_vorschreibung_je_rate')]


class StimmeEreignis(OrganisationAusKette):
    """Protokoll jeder Stimmabgabe oder -änderung (nur anhängen, nie ändern).

    Wer hat wann auf welchem Weg für welche Einheit welche Stimme abgegeben? Das muss sich später
    belegen lassen, etwa bei der Anfechtung eines Beschlusses. `stimme_abgeben` schreibt hier
    bei jedem Aufruf mit."""
    ORGANISATION_PFAD = 'traktandum'
    traktandum = models.ForeignKey(Traktandum, on_delete=models.CASCADE, related_name='stimm_ereignisse')
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='+')
    wert = models.CharField(max_length=10)
    vorher = models.CharField(max_length=10, blank=True, default='')
    kanal = models.CharField(max_length=10)
    eigentuemer = models.ForeignKey('crm.Eigentuemer', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    zeitpunkt = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'stweg_stimme_ereignis'
        ordering = ['zeitpunkt', 'id']


# ──────────────────────────────────────────────────────────────────────────
# DOKUMENTEN-REPOSITORY
#
# Die Unterlagen der Gemeinschaft liegen an einer Stelle. Der Eigentümer sieht nur, was für
# ihn freigegeben ist (`sichtbar`), und nur in Gemeinschaften, an denen er beteiligt ist.
# Ausgeliefert wird ausschliesslich über geprüfte Views, nie über /media/ (Ordner «dokumente/»
# ist dort Team-Sache).
# ──────────────────────────────────────────────────────────────────────────

class StwegDokument(OrganisationAusKette):
    ORGANISATION_PFAD = 'liegenschaft'
    BEGRUENDUNGSAKT, REGLEMENT, NUTZUNGSORDNUNG, VERSICHERUNG, JAHRESRECHNUNG, SONSTIGES = (
        'begruendungsakt', 'reglement', 'nutzungsordnung', 'versicherung', 'jahresrechnung', 'sonstiges')
    KATEGORIE_CHOICES = [
        (BEGRUENDUNGSAKT, _('Begründungsakt')),
        (REGLEMENT, _('STWEG-Reglement')),
        (NUTZUNGSORDNUNG, _('Nutzungs- und Verwaltungsordnung')),
        (VERSICHERUNG, _('Versicherungspolice')),
        (JAHRESRECHNUNG, _('Jahresrechnung')),
        (SONSTIGES, _('Sonstiges')),
    ]
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE,
                                     related_name='stweg_dokumente')
    kategorie = models.CharField(max_length=20, choices=KATEGORIE_CHOICES)
    titel = models.CharField(max_length=200)
    datei = models.FileField(upload_to=get_smart_upload_path)
    gueltig_ab = models.DateField(default=timezone.localdate)
    gueltig_bis = models.DateField(null=True, blank=True)
    #: Für Eigentümer im Portal freigegeben?
    sichtbar = models.BooleanField(default=True)
    hochgeladen_am = models.DateTimeField(auto_now_add=True)
    hochgeladen_von = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                        blank=True, related_name='+')

    class Meta:
        db_table = 'stweg_dokument'
        ordering = ['kategorie', '-gueltig_ab', '-id']
        verbose_name = 'Dokument'


# ──────────────────────────────────────────────────────────────────────────
# VORGABEN DER GEMEINSCHAFT (Reglement)
#
# Werte, die aus dem Reglement oder dem Gesetz folgen und die das System NICHT kennt:
# Einladungsfrist, Beschlussfähigkeit (Quorum), Anfechtungsfrist. Sie sind leer, bis eine Person sie
# einträgt und bestätigt. Leer heisst: das System urteilt nicht darüber.
# ──────────────────────────────────────────────────────────────────────────

class StwegVorgaben(OrganisationAusKette):
    ORGANISATION_PFAD = 'liegenschaft'
    liegenschaft = models.OneToOneField('portfolio.Liegenschaft', on_delete=models.CASCADE,
                                        related_name='stweg_vorgaben')
    einladungsfrist_tage = models.PositiveSmallIntegerField(
        "Einladungsfrist (Tage)", null=True, blank=True,
        help_text='Vorgabe für neue Versammlungen; leer = 10 Tage (Systemvorgabe, nicht geprüft).')
    quorum_koepfe_prozent = models.DecimalField(
        "Beschlussfähig ab Anteil der Köpfe (%)", max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Anteil aller Stockwerkeigentümer, der anwesend oder vertreten sein muss. Leer = nicht beurteilt.')
    quorum_quoten_prozent = models.DecimalField(
        "Beschlussfähig ab Anteil der Wertquoten (%)", max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Anteil aller Wertquoten, der anwesend oder vertreten sein muss. Leer = nicht beurteilt.')
    anfechtungsfrist_tage = models.PositiveSmallIntegerField(
        "Anfechtungsfrist (Tage ab Versand des Protokolls)", null=True, blank=True,
        help_text='Leer = es wird keine Frist geführt.')
    bemerkung = models.TextField("Quelle (Reglement, Artikel)", blank=True, default='')
    bestaetigt_am = models.DateTimeField(null=True, blank=True)
    bestaetigt_von = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name='+')

    class Meta:
        db_table = 'stweg_vorgaben'
        verbose_name = 'Vorgaben der Gemeinschaft'
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(quorum_koepfe_prozent__isnull=True)
                           | (models.Q(quorum_koepfe_prozent__gte=0) & models.Q(quorum_koepfe_prozent__lte=100))),
                name='stweg_vorgaben_quorum_koepfe_0_100'),
            models.CheckConstraint(
                condition=(models.Q(quorum_quoten_prozent__isnull=True)
                           | (models.Q(quorum_quoten_prozent__gte=0) & models.Q(quorum_quoten_prozent__lte=100))),
                name='stweg_vorgaben_quorum_quoten_0_100'),
        ]


# ──────────────────────────────────────────────────────────────────────────
# INKASSO
#
# Gegen einen Stockwerkeigentümer gibt es KEINE Kündigung: Er ist Eigentümer, nicht Mieter (Art. 257d OR gilt
# nicht). Die Gemeinschaft sichert ihre Beitragsforderungen stattdessen durch das Retentionsrecht an beweglichen
# Sachen (Art. 712k ZGB) und das Gemeinschaftspfandrecht am Anteil (Art. 712i ZGB, nur für die Beitragsforderungen
# der letzten drei Jahre). Der Ablauf: Mahnstufen 1–3 → Retentionsrecht geltend machen → Pfandrecht anmelden.
# ──────────────────────────────────────────────────────────────────────────

class StwegInkassoFall(OrganisationAusKette):
    """Der Inkassofall einer Einheit; höchstens einer ist offen."""
    ORGANISATION_PFAD = 'einheit__liegenschaft'
    OFFEN, ERLEDIGT = 'offen', 'erledigt'
    STATUS_CHOICES = [(OFFEN, _('Offen')), (ERLEDIGT, _('Erledigt'))]
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='stweg_inkassofaelle')
    eigentuemer = models.ForeignKey('crm.Eigentuemer', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=OFFEN)
    eroeffnet_am = models.DateField(default=timezone.localdate)
    erledigt_am = models.DateField(null=True, blank=True)
    retention_erklaert_am = models.DateField(null=True, blank=True)
    retention_gegenstaende = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'stweg_inkassofall'
        ordering = ['-eroeffnet_am', '-id']
        constraints = [models.UniqueConstraint(fields=['einheit'], condition=models.Q(status='offen'),
                                               name='stweg_inkasso_ein_offener_fall_je_einheit')]


class StwegMahnung(OrganisationAusKette):
    ORGANISATION_PFAD = 'fall'
    fall = models.ForeignKey(StwegInkassoFall, on_delete=models.CASCADE, related_name='mahnungen')
    stufe = models.PositiveSmallIntegerField()
    datum = models.DateField(default=timezone.localdate)
    betrag = models.DecimalField(max_digits=12, decimal_places=2)
    frist_bis = models.DateField()
    versendet_am = models.DateTimeField(null=True, blank=True)
    kanal = models.CharField(max_length=10, blank=True, default='')       # email | post

    class Meta:
        db_table = 'stweg_mahnung'
        ordering = ['stufe']
        constraints = [
            models.UniqueConstraint(fields=['fall', 'stufe'], name='stweg_mahnung_eine_je_stufe'),
            models.CheckConstraint(condition=models.Q(stufe__gte=1) & models.Q(stufe__lte=3),
                                   name='stweg_mahnung_stufe_1_bis_3'),
        ]


class StwegPfandrecht(OrganisationAusKette):
    """Anmeldung eines Gemeinschaftspfandrechts (Art. 712i ZGB) beim Grundbuchamt — Momentaufnahme der Forderungen."""
    ORGANISATION_PFAD = 'fall'
    fall = models.ForeignKey(StwegInkassoFall, on_delete=models.CASCADE, related_name='pfandrechte')
    stichtag = models.DateField()
    #: Alle offenen Beitragsforderungen, nur die der letzten 36 Monate (pfandberechtigt) und der Rest.
    betrag_gesamt = models.DecimalField(max_digits=12, decimal_places=2)
    betrag_pfandberechtigt = models.DecimalField(max_digits=12, decimal_places=2)
    betrag_ausgeschlossen = models.DecimalField(max_digits=12, decimal_places=2)
    zeilen = models.JSONField(default=list, blank=True)
    angemeldet_am = models.DateTimeField(auto_now_add=True)
    angemeldet_von = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+')
    eingetragen_am = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'stweg_pfandrecht'
        ordering = ['-angemeldet_am']
