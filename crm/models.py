import logging
# crm/models.py
import io
from decimal import Decimal
from PIL import Image
from django.core.files.base import ContentFile
from django.db import models

logger = logging.getLogger(__name__)



def _unterschrift_aufbereiten(instanz, praefix):
    """Macht den weissen Hintergrund einer neu gesetzten Unterschrift transparent.

    Läuft NUR, wenn sich die Datei gegenüber der Datenbank geändert hat. Vorher
    verarbeitete jedes save() das Bild erneut und legte dabei eine weitere Datei
    an (`sig_vw_3.png`, `sig_vw_3_a1B2c3.png`, …) — schon ein paar Mal
    «Stammdaten speichern» hinterliess einen Haufen Waisen im Medienordner.
    Die ersetzte Datei wird zudem gelöscht.
    """
    bild_feld = instanz.unterschrift_bild
    if not bild_feld:
        return
    alt_name = None
    if instanz.pk:
        alt_name = (type(instanz).objects
                    .filter(pk=instanz.pk)
                    .values_list('unterschrift_bild', flat=True).first()) or None
    if bild_feld.name == alt_name:
        return                      # unverändert → nichts zu tun
    try:
        img = Image.open(bild_feld).convert("RGBA")
        img.putdata([(255, 255, 255, 0) if (p[0] > 200 and p[1] > 200 and p[2] > 200)
                     else p for p in img.getdata()])
        puffer = io.BytesIO()
        img.save(puffer, format="PNG")
        bild_feld.save(f"{praefix}{instanz.id or 'new'}.png",
                       ContentFile(puffer.getvalue()), save=False)
    except Exception as e:
        print(f"Fehler bei Hintergrund-Entfernung ({praefix}): {e}")
        return
    # Ersetzte Datei entfernen — sonst bleibt sie unreferenziert liegen.
    if alt_name and alt_name != instanz.unterschrift_bild.name:
        try:
            instanz.unterschrift_bild.storage.delete(alt_name)
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)

class Verwaltung(models.Model):
    firma = models.CharField("Firmenname", max_length=100)
    strasse = models.CharField("Strasse & Nr.", max_length=100)
    plz = models.CharField("PLZ", max_length=10)
    ort = models.CharField("Ort", max_length=100)
    telefon = models.CharField("Telefon", max_length=30, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    logo = models.ImageField("Firmenlogo", upload_to="logos/", blank=True, null=True)
    unterschrift_bild = models.ImageField("Digitale Unterschrift", upload_to="unterschriften/", blank=True, null=True)
    aktueller_referenzzinssatz = models.DecimalField("Aktueller Ref.Zins", max_digits=4, decimal_places=2, default=1.25)
    # Verwaltungshonorar auf die Nebenkosten-Abrechnung (Standard 3 %) — vorher hart codiert
    nk_honorar_prozent = models.DecimalField("NK-Verwaltungshonorar (%)", max_digits=4, decimal_places=2, default=3.00)
    aktueller_lik_punkte = models.DecimalField("Aktueller LIK", max_digits=6, decimal_places=1, default=107.1)
    # LIK-Basis (Landesindex): aktuell «Dezember 2020 = 100». Muss auf dem
    # amtlichen Formular ausgewiesen werden; alt/neu-Werte müssen dieselbe Basis haben.
    lik_basis = models.CharField("LIK-Basis", max_length=40, default="Dezember 2020")
    aktueller_lik_stand = models.DateField("LIK Stand-Monat", null=True, blank=True)
    letztes_update_marktdaten = models.DateTimeField("Letztes Update Marktdaten", null=True, blank=True)
    # Periodensperre / Revisionssicherheit: Buchungen mit Datum ≤ diesem Stichtag
    # sind gesperrt (abgeschlossene Periode). Leer = keine Sperre.
    buchung_gesperrt_bis = models.DateField("Buchungen gesperrt bis", null=True, blank=True)
    # MWST-Konfiguration (für ESTV-Abrechnung)
    MWST_METHODE_CHOICES = [('effektiv', 'Effektive Methode'), ('saldo', 'Saldosteuersatz')]
    mwst_uid = models.CharField("MWST-Nummer (CHE)", max_length=20, blank=True, default='')
    mwst_methode = models.CharField("MWST-Methode", max_length=10, choices=MWST_METHODE_CHOICES, default='effektiv')
    saldosteuersatz = models.DecimalField("Saldosteuersatz (%)", max_digits=4, decimal_places=1, default=0)
    # Vermarktungs-Portale: Token für den öffentlichen Objekt-Feed (Homegate,
    # ImmoScout24/SMG, Flatfox etc. via Feed-URL/Middleware). Leer = Feed deaktiviert.
    portal_feed_token = models.CharField("Portal-Feed-Token", max_length=64, blank=True, default='')
    # Abonnement / Preisplan
    ABO_CHOICES = [('start', 'Start'), ('pro', 'Pro'), ('premium', 'Premium')]
    abo_plan = models.CharField("Abo-Plan", max_length=10, choices=ABO_CHOICES, default='pro')
    abo_jaehrlich = models.BooleanField("Jährliche Abrechnung", default=False)

    class Meta:
        verbose_name = "Meine Verwaltung"
        verbose_name_plural = "Meine Verwaltung"
        db_table = 'core_verwaltung'

    def __str__(self):
        return self.firma

    def save(self, *args, **kwargs):
        _unterschrift_aufbereiten(self, 'sig_vw_')
        super().save(*args, **kwargs)


class Mandant(models.Model):
    # Portal-Zugang: verknüpfter Login für das Eigentümer-Portal (/portal/).
    # Eigentümer sehen dort NUR ihre eigenen Liegenschaften — kein SPA-/API-Zugriff.
    benutzer = models.OneToOneField(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='mandant_profil', verbose_name="Portal-Login",
        help_text="Optionaler Benutzer-Account für das Eigentümer-Portal."
    )
    firma_oder_name = models.CharField("Name / Firma (Eigentümer)", max_length=100)
    kontaktperson = models.CharField("Kontaktperson", max_length=100, blank=True)
    strasse = models.CharField("Strasse & Nr.", max_length=100, blank=True)
    plz = models.CharField("PLZ", max_length=10, blank=True)
    ort = models.CharField("Ort", max_length=100, blank=True)
    telefon = models.CharField("Telefon", max_length=30, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    bank_name = models.CharField("Bankname (Mandant)", max_length=100, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    # Verwaltungshonorar in % der Mieterträge (netto). 0 = kein Honorar.
    honorar_prozent = models.DecimalField("Verwaltungshonorar (%)", max_digits=5, decimal_places=2,
                                          default=Decimal('0.00'))
    unterschrift_bild = models.ImageField("Digitale Unterschrift", upload_to="unterschriften/", blank=True, null=True)

    class Meta:
        verbose_name = "Mandant (Eigentümer)"
        verbose_name_plural = "Mandanten (Eigentümer)"
        db_table = 'core_mandant'

    def __str__(self):
        return self.firma_oder_name

    def save(self, *args, **kwargs):
        _unterschrift_aufbereiten(self, 'sig_man_')
        super().save(*args, **kwargs)


# 🔥 DER NEUE, AUFGERÜSTETE MIETER (Inkl. Flatfox-Felder & Adress-Historie)
class Mieter(models.Model):
    TYP_CHOICES = [
        ('person', 'Privatperson'),
        ('firma', 'Firma / Unternehmen'),
        ('verein', 'Verein / Stiftung')
    ]
    typ = models.CharField("Kunden-Typ", max_length=20, choices=TYP_CHOICES, default='person')

    AUFENTHALT_CHOICES = [
        ('', '—'),
        ('schweizer', 'Schweizer Bürger/in'),
        ('C', 'Niederlassung C'),
        ('B', 'Aufenthalt B'),
        ('L', 'Kurzaufenthalt L'),
        ('G', 'Grenzgänger G'),
        ('Ci', 'Ci (Aufenthalt mit Erwerb)'),
        ('F', 'Vorläufig aufgenommen F'),
        ('N', 'Asylsuchend N'),
        ('andere', 'Andere'),
    ]
    ZAHLUNGSART_CHOICES = [
        ('', '—'),
        ('dauerauftrag', 'Dauerauftrag'),
        ('qr', 'QR-Einzahlung'),
        ('lsv', 'LSV / CH-DD-Lastschrift'),
        ('ebill', 'eBill'),
    ]
    BETREIBUNG_CHOICES = [
        ('', '—'),
        ('keine', 'Keine Betreibungen'),
        ('offen', 'Offene Betreibungen'),
        ('verlustscheine', 'Verlustscheine vorhanden'),
    ]
    VERTRETUNG_CHOICES = [
        ('', '—'),
        ('bevollmaechtigt', 'Bevollmächtigte Person'),
        ('beistand', 'Beistand (Erwachsenenschutz)'),
        ('kesb', 'KESB'),
        ('erbengemeinschaft', 'Erbengemeinschaft / Willensvollstrecker'),
    ]

    # --- FIRMA / VEREIN ---
    firmen_name = models.CharField("Firmenname", max_length=200, blank=True, default='')
    uid_nummer = models.CharField("UID / CHE-Nummer", max_length=50, blank=True, default='')
    kontaktperson = models.CharField("Kontaktperson", max_length=100, blank=True, default='')

    # --- PRIVATPERSON ---
    anrede = models.CharField("Anrede", max_length=20, blank=True, default='Herr')
    vorname = models.CharField("Vorname", max_length=100, blank=True, default='')
    nachname = models.CharField("Nachname", max_length=100, blank=True, default='')
    geburtsdatum = models.DateField("Geburtsdatum", null=True, blank=True)
    ahv_nummer = models.CharField("AHV-Nummer", max_length=20, blank=True, default='')
    zivilstand = models.CharField("Zivilstand", max_length=50, blank=True, default='')
    nationalitaet = models.CharField("Nationalität", max_length=100, blank=True, default='')
    heimatort = models.CharField("Heimatort", max_length=150, blank=True, default='')

    # --- BERUF & FINANZEN (Übernahme aus Bewerbung) ---
    erwerbsstatus = models.CharField("Erwerbsstatus", max_length=50, blank=True, default='')
    beruf = models.CharField("Beruf", max_length=150, blank=True, default='')
    arbeitgeber = models.CharField("Arbeitgeber", max_length=150, blank=True, default='')
    einkommen_jahr = models.CharField("Jahreseinkommen", max_length=100, blank=True, default='')

    # --- KONTAKT ---
    email = models.EmailField("E-Mail", blank=True, default='')
    telefon_privat = models.CharField("Telefon Privat", max_length=50, blank=True, default='')
    telefon_geschaeft = models.CharField("Telefon Geschäft", max_length=50, blank=True, default='')
    mobile = models.CharField("Mobile", max_length=50, blank=True, default='')
    sprache = models.CharField("Korrespondenzsprache", max_length=2, default='de', choices=[('de', 'Deutsch'), ('fr', 'Französisch'), ('it', 'Italienisch'), ('en', 'Englisch')])

    # --- ADRESSE ---
    strasse = models.CharField("Strasse & Nr.", max_length=200, blank=True, default='')
    adresszusatz = models.CharField("Adresszusatz", max_length=100, blank=True, default='')
    postfach = models.CharField("Postfach", max_length=50, blank=True, default='')
    plz = models.CharField("PLZ", max_length=10, blank=True, default='')
    ort = models.CharField("Ort", max_length=100, blank=True, default='')
    land = models.CharField("Land", max_length=50, default='Schweiz')

    # Hinweis: Die frühere «zukünftige Adresse» (zukuenftige_strasse/plz/ort +
    # zukuenftig_ab, check_and_update_adresse()) ist entfernt — die datierte
    # Adress-Historie (MieterAdresse, gültig ab) ist die alleinige Quelle für
    # Ein-/Auszugs-Adresswechsel (sync_effektive_adresse führt die Flat-Felder nach).

    # --- AUFENTHALT (bei Vermietung an Ausländer Pflichtangabe) ---
    aufenthaltsbewilligung = models.CharField("Aufenthaltsbewilligung", max_length=20,
                                              choices=AUFENTHALT_CHOICES, blank=True, default='')
    bewilligung_gueltig_bis = models.DateField("Bewilligung gültig bis", null=True, blank=True)

    # --- VERSICHERUNG & NOTFALL ---
    haftpflicht_gesellschaft = models.CharField("Haftpflicht-Versicherung", max_length=120, blank=True, default='')
    haftpflicht_police = models.CharField("Policen-Nr.", max_length=60, blank=True, default='')
    notfall_name = models.CharField("Notfallkontakt / Bürge", max_length=150, blank=True, default='')
    notfall_telefon = models.CharField("Notfall-Telefon", max_length=50, blank=True, default='')
    notfall_beziehung = models.CharField("Beziehung", max_length=80, blank=True, default='')

    # --- HAUSHALT ---
    haushalt_erwachsene = models.PositiveSmallIntegerField("Erwachsene im Haushalt", default=0)
    haushalt_kinder = models.PositiveSmallIntegerField("Kinder im Haushalt", default=0)
    haustiere = models.BooleanField("Haustiere", default=False)
    haustiere_details = models.CharField("Haustiere (Details)", max_length=200, blank=True, default='')

    # --- FINANZEN & ADMIN ---
    iban = models.CharField("IBAN", max_length=34, blank=True, default='')
    bank_name = models.CharField("Bank", max_length=100, blank=True, default='')
    bonitaet_datum = models.DateField("Betreibungsauszug vom", null=True, blank=True)
    betreibung_ergebnis = models.CharField("Betreibungsauszug-Ergebnis", max_length=20,
                                           choices=BETREIBUNG_CHOICES, blank=True, default='')

    # --- ZAHLUNGSVERKEHR ---
    zahlungsart = models.CharField("Zahlungsart", max_length=20, choices=ZAHLUNGSART_CHOICES, blank=True, default='')
    ebill_email = models.EmailField("eBill-/E-Rechnungs-Adresse", blank=True, default='')
    mahnsperre = models.BooleanField("Mahnsperre (Zahlungsvereinbarung)", default=False)
    # Abweichender Zahler / Kostenträger (z.B. Sozialamt, Firma, Elternteil)
    zahler_name = models.CharField("Abweichender Zahler", max_length=150, blank=True, default='')
    zahler_adresse = models.CharField("Zahler-Adresse", max_length=200, blank=True, default='')
    zahler_iban = models.CharField("Zahler-IBAN", max_length=34, blank=True, default='')

    # --- VORVERMIETER-REFERENZ (aus der Bewerbung übernommen) ---
    ref_vermieter_name = models.CharField("Referenz Vorvermieter", max_length=150, blank=True, default='')
    ref_vermieter_telefon = models.CharField("Vorvermieter Telefon", max_length=50, blank=True, default='')
    ref_vermieter_email = models.EmailField("Vorvermieter E-Mail", blank=True, default='')

    # --- VERTRETUNG / BEISTAND ---
    vertretung_art = models.CharField("Vertretung", max_length=30, choices=VERTRETUNG_CHOICES, blank=True, default='')
    vertretung_name = models.CharField("Vertretung Name/Behörde", max_length=150, blank=True, default='')
    vertretung_kontakt = models.CharField("Vertretung Kontakt", max_length=150, blank=True, default='')

    notizen = models.TextField("Interne Notizen", blank=True, default='')
    # DSG: Personendaten anonymisiert (Buchungsbelege bleiben aufbewahrt, OR 958f)
    anonymisiert = models.BooleanField("DSG-anonymisiert", default=False)
    anonymisiert_am = models.DateField("Anonymisiert am", null=True, blank=True)
    # Mieterportal-Login (optional): verknüpfter Benutzer für das Self-Service-Portal
    benutzer = models.OneToOneField('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='mieter_profil')

    class Meta:
        verbose_name = "Mieter"
        verbose_name_plural = "Mieter"
        db_table = 'core_mieter'

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        if self.typ in ['firma', 'verein'] and self.firmen_name:
            return self.firmen_name
        return f"{self.vorname} {self.nachname}".strip() or "Unbekannter Kontakt"

    # ===== Datierte Adress-Historie (Wohn- + Korrespondenzadresse) =====
    def _adr_zeile(self, art, stichtag=None):
        from datetime import date as _d
        if not self.pk:
            return None
        tag = stichtag or _d.today()
        return (self.adressen.filter(art=art, gueltig_ab__lte=tag)
                .order_by('-gueltig_ab', '-id').first())

    def aktuelle_wohnadresse(self, stichtag=None):
        """Die zum Stichtag gültige Wohnadress-Zeile (oder None)."""
        return self._adr_zeile('wohn', stichtag)

    def aktuelle_korrespondenzadresse(self, stichtag=None):
        """Die zum Stichtag gültige Korrespondenzadress-Zeile (oder None)."""
        return self._adr_zeile('korrespondenz', stichtag)

    def zustelladresse(self, stichtag=None):
        """Effektive Zustelladresse als (strasse, adresszusatz, plz, ort):
        Korrespondenzadresse falls gesetzt, sonst Wohnadresse, sonst Flat-Felder."""
        z = self.aktuelle_korrespondenzadresse(stichtag) or self.aktuelle_wohnadresse(stichtag)
        if z:
            return (z.strasse, z.adresszusatz, z.plz, z.ort)
        return (self.strasse, self.adresszusatz, self.plz, self.ort)

    def sync_effektive_adresse(self, stichtag=None, save=True):
        """Schreibt die effektive Zustelladresse in die Flat-Felder (strasse/…),
        damit alle bestehenden Leser (QR, Briefe, Formulare) automatisch die zum
        Stichtag gültige Adresse inkl. Korrespondenz-Vorrang erhalten — analog zur
        Sollmietzins→einheit.nettomiete_aktuell-Synchronisation. Gibt True zurück,
        wenn sich etwas geändert hat."""
        s, zusatz, plz, ort = self.zustelladresse(stichtag)
        if not (s or plz or ort):
            return False
        if (self.strasse, self.adresszusatz, self.plz, self.ort) != (s, zusatz, plz, ort):
            self.strasse, self.adresszusatz, self.plz, self.ort = s, zusatz, plz, ort
            if save and self.pk:
                self.save(update_fields=['strasse', 'adresszusatz', 'plz', 'ort'])
            return True
        return False

class MieterAdresse(models.Model):
    """Datierte Adress-Historie einer Person (wie Sollmietzins «gültig ab»).
    `wohn` = tatsächliche Wohnadresse-Zeitachse (wechselt bei Ein-/Auszug),
    `korrespondenz` = optionale «Post an»-Zeitachse (hat Vorrang für Zustellung).
    Die zum Stichtag gültige Zeile bestimmt via Mieter.sync_effektive_adresse die
    effektiven Flat-Felder am Mieter."""
    ART_CHOICES = [('wohn', 'Wohnadresse'), ('korrespondenz', 'Korrespondenzadresse')]
    mieter = models.ForeignKey(Mieter, on_delete=models.CASCADE, related_name='adressen')
    art = models.CharField("Art", max_length=20, choices=ART_CHOICES, default='wohn')
    gueltig_ab = models.DateField("Gültig ab")
    strasse = models.CharField("Strasse & Nr.", max_length=200, blank=True, default='')
    adresszusatz = models.CharField("Adresszusatz", max_length=100, blank=True, default='')
    plz = models.CharField("PLZ", max_length=10, blank=True, default='')
    ort = models.CharField("Ort", max_length=100, blank=True, default='')
    land = models.CharField("Land", max_length=50, blank=True, default='Schweiz')
    quelle = models.CharField("Quelle", max_length=50, blank=True, default='manuell')
    notiz = models.CharField("Bemerkung", max_length=200, blank=True, default='')
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mieter-Adresse"
        verbose_name_plural = "Mieter-Adressen"
        ordering = ['-gueltig_ab', '-id']
        db_table = 'core_mieteradresse'

    def __str__(self):
        return f"{self.get_art_display()} ab {self.gueltig_ab}: {self.einzeiler}"

    @property
    def einzeiler(self):
        zus = f" ({self.adresszusatz})" if self.adresszusatz else ''
        return f"{self.strasse}{zus}, {self.plz} {self.ort}".strip(' ,')


# 🔥 DER NEUE HANDWERKER-STAMM FÜR DIE API
class Handwerker(models.Model):
    BRANCHEN_CHOICES = [
        ('sanitaer', 'Sanitär / Heizung'),
        ('elektro', 'Elektroinstallation'),
        ('maler', 'Maler / Gipser'),
        ('schreiner', 'Schreiner / Zimmermann'),
        ('schloss', 'Schlosserei / Schlüsseldienst'),
        ('allgemein', 'Allround-Handwerker / Baugeschäft'),
        ('garten', 'Gartenbau / Umgebung'),
        ('reinigung', 'Reinigungsinstitut'),
    ]

    firma = models.CharField(max_length=255, verbose_name="Firmenname")
    kontaktperson = models.CharField(max_length=255, blank=True, null=True, verbose_name="Kontaktperson")
    branche = models.CharField(max_length=50, choices=BRANCHEN_CHOICES, default='allgemein')
    email = models.EmailField(verbose_name="E-Mail für Aufträge", blank=True, null=True)
    telefon = models.CharField(max_length=50, blank=True, null=True, verbose_name="Telefonnummer")
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Handwerker"
        verbose_name_plural = "Handwerkerstamm"
        ordering = ['firma']
        db_table = 'core_handwerker'

    def __str__(self):
        try:
            return f"{self.firma} ({self.get_branche_display()})"
        except:
            return self.firma

class Vorlage(models.Model):
    """Wiederverwendbare Text-/Brief-Vorlage mit Platzhaltern (z. B. {mieter_name})."""
    KATEGORIE_CHOICES = [
        ('brief', 'Brief / Anschreiben'),
        ('kuendigung', 'Kündigung'),
        ('mahnung', 'Mahnung'),
        ('info', 'Information / Rundschreiben'),
        ('protokoll', 'Protokoll'),
        ('ticket_eingang', 'Schaden – Eingangsbestätigung'),
        ('ticket_handwerker', 'Schaden – Auftrag an Handwerker'),
        ('ticket_melder', 'Schaden – Info an Melder'),
        ('ticket_erledigt', 'Schaden – Erledigt-Meldung'),
        ('bewerber_zusage', 'Bewerber – Zusage'),
        ('bewerber_absage', 'Bewerber – Absage'),
        ('sonstiges', 'Sonstiges'),
    ]
    name = models.CharField("Bezeichnung", max_length=150)
    kategorie = models.CharField("Kategorie", max_length=20, choices=KATEGORIE_CHOICES, default='brief')
    betreff = models.CharField("Betreff", max_length=200, blank=True, default='')
    inhalt = models.TextField("Inhalt", blank=True, default='')
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Vorlage"
        verbose_name_plural = "Vorlagen"
        ordering = ['kategorie', 'name']
        db_table = 'core_vorlage'

    def __str__(self):
        return self.name


class Kommunikation(models.Model):
    """Kommunikations-/Kontaktjournal: dokumentiert jede Interaktion mit einem
    Kontakt (Telefon, E-Mail, Brief, Notiz) — verknüpfbar mit Person/Vertrag/Schaden."""
    from django.utils import timezone as _tz
    TYP = [('telefon', 'Telefon'), ('email', 'E-Mail'), ('brief', 'Brief'),
           ('notiz', 'Notiz'), ('persoenlich', 'Persönlich')]
    RICHTUNG = [('eingehend', 'Eingehend'), ('ausgehend', 'Ausgehend'), ('intern', 'Intern')]
    mieter = models.ForeignKey('crm.Mieter', on_delete=models.CASCADE, null=True, blank=True, related_name='kommunikationen')
    vertrag = models.ForeignKey('rentals.Mietvertrag', on_delete=models.SET_NULL, null=True, blank=True, related_name='kommunikationen')
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.SET_NULL, null=True, blank=True)
    typ = models.CharField("Kanal", max_length=15, choices=TYP, default='telefon')
    richtung = models.CharField("Richtung", max_length=12, choices=RICHTUNG, default='eingehend')
    zeitpunkt = models.DateTimeField("Zeitpunkt", default=_tz.now)
    betreff = models.CharField("Betreff", max_length=200, blank=True, default='')
    inhalt = models.TextField("Inhalt / Notiz")
    erledigt = models.BooleanField("Erledigt", default=True)
    erstellt_von = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = "Kommunikation"
        verbose_name_plural = "Kommunikationsjournal"
        ordering = ['-zeitpunkt', '-id']
        db_table = 'core_kommunikation'

    def __str__(self):
        return f"{self.get_typ_display()} {self.zeitpunkt:%d.%m.%Y}: {self.betreff or self.inhalt[:40]}"
