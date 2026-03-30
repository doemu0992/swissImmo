import os
import re
import json
import datetime
import uuid
from decimal import Decimal
from django.db import models
from django.utils import timezone

# --- GOOGLE AI IMPORT ---
try:
    import google.generativeai as genai
except ImportError:
    genai = None

# --- HELPER FUNCTIONS ---
def get_current_ref_zins():
    try:
        from .models import Verwaltung
        v = Verwaltung.objects.first()
        return v.aktueller_referenzzinssatz if v else 1.75
    except: return 1.75

def get_current_lik():
    try:
        from .models import Verwaltung
        v = Verwaltung.objects.first()
        return v.aktueller_lik_punkte if v else 107.1
    except: return 107.1

def get_smart_upload_path(instance, filename):
    heute = datetime.date.today().strftime("%Y-%m-%d")
    return os.path.join("uploads", heute, filename)

# ==============================================================================
# 1. BASIS & STAMMDATEN
# ==============================================================================

class Verwaltung(models.Model):
    firma = models.CharField("Firmenname", max_length=100)
    strasse = models.CharField("Strasse & Nr.", max_length=100)
    plz = models.CharField("PLZ", max_length=10)
    ort = models.CharField("Ort", max_length=100)
    telefon = models.CharField("Telefon", max_length=30, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True, null=True)
    aktueller_referenzzinssatz = models.DecimalField("Aktueller Ref.Zins", max_digits=4, decimal_places=2, default=1.75)
    aktueller_lik_punkte = models.DecimalField("Aktueller LIK", max_digits=6, decimal_places=1, default=107.1)
    letztes_update_marktdaten = models.DateTimeField(null=True, blank=True)
    class Meta: verbose_name = "Meine Verwaltung"; verbose_name_plural = "Meine Verwaltung"
    def __str__(self): return self.firma

class Mandant(models.Model):
    firma_oder_name = models.CharField("Name / Firma (Eigentümer)", max_length=100)
    strasse = models.CharField("Strasse", max_length=100, blank=True)
    plz = models.CharField("PLZ", max_length=10, blank=True)
    ort = models.CharField("Ort", max_length=100, blank=True)
    unterschrift_bild = models.ImageField(upload_to="unterschriften/", blank=True, null=True)
    bank_name = models.CharField("Bankname (Mandant)", max_length=100, blank=True)
    class Meta: verbose_name = "Mandant (Eigentümer)"; verbose_name_plural = "Mandanten (Eigentümer)"
    def __str__(self): return self.firma_oder_name

class Liegenschaft(models.Model):
    mandant = models.ForeignKey(Mandant, on_delete=models.CASCADE, related_name='liegenschaften', null=True, blank=True)
    verwaltung = models.ForeignKey(Verwaltung, on_delete=models.SET_NULL, null=True, blank=True, related_name='liegenschaften')
    strasse = models.CharField("Strasse & Nr.", max_length=200)
    plz = models.CharField("PLZ", max_length=10)
    ort = models.CharField("Ort", max_length=100)
    egid = models.CharField("EGID", max_length=20, blank=True, null=True)

    # --- DIESE FELDER SIND JETZT DABEI ---
    baujahr = models.IntegerField("Baujahr", null=True, blank=True)
    kataster_nummer = models.CharField("Kataster-Nr.", max_length=50, blank=True)
    versicherungswert = models.DecimalField("Versicherungswert", max_digits=12, decimal_places=2, null=True, blank=True)
    # ------------------------------------

    kanton = models.CharField("Kanton", max_length=2, blank=True)
    bank_name = models.CharField("Bankname", max_length=100, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    verteilschluessel_text = models.CharField("Verteilschlüssel", max_length=200, default="nach Wohnfläche (m2)")

    class Meta: verbose_name = "Liegenschaft"; verbose_name_plural = "Liegenschaften"
    def __str__(self): return f"{self.strasse}, {self.ort}"

class Einheit(models.Model):
    TYP_CHOICES = [('whg', 'Wohnung'), ('gew', 'Gewerbe'), ('pp', 'Parkplatz'), ('bas', 'Bastelraum')]
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, related_name='einheiten')
    bezeichnung = models.CharField("Objektbezeichnung", max_length=50)
    typ = models.CharField("Typ", max_length=10, choices=TYP_CHOICES, default='whg')

    # --- DIESE FELDER SIND JETZT DABEI ---
    ewid = models.CharField("EWID", max_length=20, blank=True, null=True)
    etage = models.CharField("Etage", max_length=50, blank=True)
    wertquote = models.DecimalField("Wertquote", max_digits=6, decimal_places=2, default=10.00)
    # ------------------------------------

    zimmer = models.DecimalField("Anz. Zimmer", max_digits=3, decimal_places=1, null=True, blank=True)
    flaeche_m2 = models.DecimalField("Fläche (m²)", max_digits=6, decimal_places=2, null=True, blank=True)
    nettomiete_aktuell = models.DecimalField("Soll-Miete", max_digits=8, decimal_places=2, default=0.00)
    nebenkosten_aktuell = models.DecimalField("Soll-Nebenkosten", max_digits=6, decimal_places=2, default=0.00)
    nk_abrechnungsart = models.CharField("NK-Art", max_length=20, default='pauschal', choices=[('akonto', 'Akonto'), ('pauschal', 'Pauschal')])
    ref_zinssatz = models.DecimalField("Basis Ref.Zins", max_digits=4, decimal_places=2, default=get_current_ref_zins)
    lik_punkte = models.DecimalField("Basis LIK", max_digits=6, decimal_places=1, default=get_current_lik)

    class Meta: verbose_name = "Einheit"; verbose_name_plural = "Einheiten"
    def __str__(self): return f"{self.liegenschaft.strasse} - {self.bezeichnung}"

    @property
    def aktiver_vertrag(self): return self.vertraege.filter(aktiv=True).first()

# ==============================================================================
# 2. PERSONEN & VERTRÄGE
# ==============================================================================

class Mieter(models.Model):
    anrede = models.CharField(max_length=20, default='Herr')
    vorname = models.CharField(max_length=100); nachname = models.CharField(max_length=100)
    telefon = models.CharField(max_length=30, blank=True); email = models.EmailField(blank=True)
    strasse = models.CharField(max_length=200, blank=True); plz = models.CharField(max_length=10, blank=True); ort = models.CharField(max_length=100, blank=True)
    geburtsdatum = models.DateField(null=True, blank=True)
    def __str__(self): return f"{self.nachname} {self.vorname}"
    class Meta: verbose_name = "Mieter"; verbose_name_plural = "Mieter"

class Handwerker(models.Model):
    firma = models.CharField(max_length=100); gewerk = models.CharField(max_length=100)
    email = models.EmailField(blank=True); telefon = models.CharField(max_length=30, blank=True)
    iban = models.CharField(max_length=34, blank=True)
    def __str__(self): return self.firma
    class Meta: verbose_name = "Handwerker"; verbose_name_plural = "Handwerker"

class Mietvertrag(models.Model):
    STATUS_CHOICES = [('offen', 'Offen'), ('gesendet', 'Versendet'), ('unterzeichnet', 'Unterzeichnet')]
    mieter = models.ForeignKey(Mieter, on_delete=models.CASCADE, related_name='vertraege')
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='vertraege')
    beginn = models.DateField(); ende = models.DateField(null=True, blank=True)
    netto_mietzins = models.DecimalField(max_digits=8, decimal_places=2); nebenkosten = models.DecimalField(max_digits=6, decimal_places=2)
    basis_referenzzinssatz = models.DecimalField(max_digits=4, decimal_places=2, default=get_current_ref_zins)
    basis_lik_punkte = models.DecimalField(max_digits=6, decimal_places=1, default=get_current_lik)
    aktiv = models.BooleanField(default=True)
    sign_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offen')
    pdf_datei = models.FileField(upload_to='vertraege_pdfs/', blank=True, null=True)
    kautions_betrag = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    def __str__(self): return f"{self.mieter} - {self.einheit}"
    class Meta: verbose_name = "Mietvertrag"; verbose_name_plural = "Mietverträge"

# ==============================================================================
# 3. NEBENKOSTEN & KI VISION PARSER MIT LERNFUNKTION (FEHLER-TRACKING)
# ==============================================================================

class AbrechnungsPeriode(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, related_name='abrechnungen')
    bezeichnung = models.CharField("Titel", max_length=100); start_datum = models.DateField(); ende_datum = models.DateField(); abgeschlossen = models.BooleanField(default=False)
    def __str__(self): return self.bezeichnung
    class Meta: verbose_name = "Abrechnungsperiode"; verbose_name_plural = "Abrechnungsperioden"

class NebenkostenLernRegel(models.Model):
    suchwort = models.CharField("Schlüsselwort", max_length=100, unique=True)
    kategorie_zuweisung = models.CharField("Wird zugewiesen zu", max_length=50)
    text_vorschlag = models.CharField("Standard-Beschreibung", max_length=200)
    treffer_quote = models.IntegerField("Erfolgreich angewendet", default=0)
    class Meta: verbose_name = "KI Lern-Regel"; verbose_name_plural = "KI Lern-Regeln"
    def __str__(self): return f"'{self.suchwort}' -> {self.kategorie_zuweisung}"

NK_KATEGORIE_CHOICES = [
    ('heizung', 'Heizung & Warmwasser'), ('wasser', 'Wasser / Abwasser'),
    ('hauswart', 'Hauswartung & Reinigung'), ('strom', 'Allgemeinstrom'),
    ('lift', 'Serviceabo Lift'), ('verwaltung', 'Verwaltungshonorar'),
    ('tv', 'TV / Kabelgebühren'), ('kehricht', 'Kehricht / Entsorgung'),
    ('diverse', 'Diverse Betriebskosten'),
]

class NebenkostenBeleg(models.Model):
    VERTEIL_CHOICES = [('m2', 'Nach Fläche (m²)'), ('einheit', 'Pro Wohnung')]
    periode = models.ForeignKey(AbrechnungsPeriode, on_delete=models.CASCADE, related_name='belege')
    datum = models.DateField(default=timezone.now, blank=True, null=True)
    text = models.CharField("Beschreibung / Lieferant", max_length=255, blank=True)
    kategorie = models.CharField(max_length=50, choices=NK_KATEGORIE_CHOICES, default='diverse')
    verteilschluessel = models.CharField(max_length=20, choices=VERTEIL_CHOICES, default='m2')
    betrag = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    beleg_scan = models.FileField(upload_to='nebenkosten_belege/', blank=True, null=True)

    class Meta: verbose_name = "Nebenkostenbeleg"; ordering = ['datum']

    def analyze_pdf_with_ai(self):
        if not self.beleg_scan:
            return

        if not genai:
            self.text = "SYSTEM-FEHLER: Das 'google-generativeai' Paket fehlt!"
            return

        try:
            # 1. API Schlüssel
            genai.configure(api_key="AIzaSyBDdF-2rAcwX9tt9HSTIDyimLekUePu4Qo")

            # --- DYNAMISCHE MODELL-SUCHE (Jetzt wirklich im Code!) ---
            available_models = []
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    available_models.append(m.name)

            chosen_model = None
            # Priorität 1: Flash
            for name in available_models:
                if '1.5-flash' in name:
                    chosen_model = name
                    break

            # Priorität 2: Irgendein anderes multimodales Modell
            if not chosen_model:
                for name in available_models:
                    if 'gemini-1.0-pro-vision' in name or 'vision' in name:
                        chosen_model = name
                        break

            # Priorität 3: Das Erstbeste
            if not chosen_model and available_models:
                chosen_model = available_models[0]

            if not chosen_model:
                self.text = "KI-FEHLER: Keine passenden Modelle gefunden."
                return

            model = genai.GenerativeModel(chosen_model)
            # ---------------------------------------------------------

            # 3. Datei hochladen
            beleg_file = genai.upload_file(self.beleg_scan.path)

            # 4. Prompt
            prompt = """
            Du bist ein professioneller Buchhalter für Schweizer Immobilien.
            Analysiere den angehängten Beleg (Rechnung/Quittung).
            Antworte AUSSCHLIESSLICH im JSON-Format ohne Markdown (```json).
            Struktur:
            {
              "betrag": 1250.50,
              "datum": "2024-03-15",
              "lieferant": "Müller Sanitär AG",
              "kategorie": "hauswart"
            }
            """

            # 5. KI Aufruf
            response = model.generate_content([beleg_file, prompt])

            try:
                beleg_file.delete() # Sauber aufräumen
            except: pass

            # 6. JSON extrahieren und bereinigen
            raw_json = response.text.replace('```json', '').replace('```', '').strip()
            data = json.loads(raw_json)

            if data.get("betrag"):
                self.betrag = Decimal(str(data["betrag"]))
            if data.get("datum"):
                self.datum = datetime.datetime.strptime(data["datum"], "%Y-%m-%d").date()
            if not self.text and data.get("lieferant"):
                self.text = data["lieferant"][:255]

            ermittelte_kategorie = data.get("kategorie", "diverse")

            # 7. Lern-Regeln prüfen
            regel_angewendet = False
            if self.text:
                text_lower = self.text.lower()
                for regel in NebenkostenLernRegel.objects.all():
                    if regel.suchwort in text_lower:
                        self.kategorie = regel.kategorie_zuweisung
                        regel.treffer_quote += 1
                        regel.save()
                        regel_angewendet = True
                        break

            if not regel_angewendet:
                self.kategorie = ermittelte_kategorie

        except Exception as e:
            # Wenn es hier crasht, speichern wir auch die Modell-Liste mit ins Textfeld!
            self.text = f"KI-FEHLER ({chosen_model}): {str(e)}"[:250]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        current_betrag = self.betrag

        super().save(*args, **kwargs)

        if self.beleg_scan and (not current_betrag or is_new):
            self.analyze_pdf_with_ai()
            super().save(update_fields=['betrag', 'datum', 'text', 'kategorie'])

        if (self.kategorie != 'diverse' and self.text and len(self.text) > 3 and
            not self.text.startswith("KI-FEHLER") and not self.text.startswith("SYSTEM-FEHLER")):

            suchwort = self.text.lower().strip()
            if not NebenkostenLernRegel.objects.filter(suchwort=suchwort).exists():
                NebenkostenLernRegel.objects.create(
                    suchwort=suchwort,
                    kategorie_zuweisung=self.kategorie,
                    text_vorschlag=self.text
                )

    def __str__(self): return f"{self.datum} - {self.text} (CHF {self.betrag})"

# ==============================================================================
# 4. TICKETS & SCHÄDEN
# ==============================================================================

class SchadenMeldung(models.Model):
    STATUS_CHOICES = [('neu', 'Neu'), ('in_bearbeitung', 'In Bearbeitung'), ('warte_auf_mieter', 'Warte auf Mieter'), ('erledigt', 'Erledigt')]
    ZUTRITT_CHOICES = [('telefon', 'Termin via Telefon'), ('passpartout', 'Passpartout (Schlüssel vorhanden)')]

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, related_name='schaeden')
    betroffene_einheit = models.ForeignKey(Einheit, on_delete=models.SET_NULL, null=True, blank=True, related_name='schaeden')
    gemeldet_von = models.ForeignKey(Mieter, on_delete=models.SET_NULL, null=True, blank=True, related_name='gemeldete_schaeden')

    titel = models.CharField("Titel / Schaden", max_length=200)
    beschreibung = models.TextField("Beschreibung")
    foto = models.ImageField(upload_to=get_smart_upload_path, blank=True, null=True)

    email_melder = models.EmailField("E-Mail Melder", blank=True, null=True)
    tel_melder = models.CharField("Telefon Melder", max_length=50, blank=True, null=True)

    zutritt = models.CharField("Zutritt / Termin", max_length=20, choices=ZUTRITT_CHOICES, default='telefon')
    mieter_email = models.EmailField("Mieter E-Mail (Legacy)", blank=True)
    mieter_telefon = models.CharField("Mieter Telefon (Legacy)", max_length=30, blank=True)

    prioritaet = models.CharField("Priorität", max_length=20, default='mittel')
    status = models.CharField("Status", max_length=20, choices=STATUS_CHOICES, default='neu')
    gelesen = models.BooleanField(default=False)
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)

    class Meta: verbose_name = "Ticket / Schaden"; verbose_name_plural = "Tickets / Schäden"; ordering = ['-erstellt_am']
    def __str__(self): return f"Ticket #{self.id}: {self.titel}"

class HandwerkerAuftrag(models.Model):
    ticket = models.ForeignKey(SchadenMeldung, on_delete=models.CASCADE, related_name='handwerker_auftraege')
    handwerker = models.ForeignKey(Handwerker, on_delete=models.CASCADE, related_name='auftraege')
    status = models.CharField(max_length=20, default='offen')
    beauftragt_am = models.DateTimeField(auto_now_add=True)
    bemerkung = models.TextField(blank=True)
    class Meta: verbose_name = "Handwerker-Auftrag"

class TicketNachricht(models.Model):
    ticket = models.ForeignKey(SchadenMeldung, on_delete=models.CASCADE, related_name='nachrichten')
    absender_name = models.CharField(max_length=100)

    TYP_CHOICES = [('chat', 'Chat'), ('system', 'System'), ('mail_antwort', 'Mail Antwort'), ('antwort_senden', 'Antwort Senden'), ('handwerker_mail', 'Handwerker Mail')]
    typ = models.CharField(max_length=20, choices=TYP_CHOICES, default='chat')

    nachricht = models.TextField()
    datei = models.FileField(upload_to='ticket_anhang/', blank=True, null=True)

    cc_email = models.CharField("CC (Optional)", max_length=200, blank=True)
    empfaenger_handwerker = models.ForeignKey(Handwerker, on_delete=models.SET_NULL, null=True, blank=True)

    gelesen = models.BooleanField(default=False)
    is_intern = models.BooleanField(default=False)
    is_von_verwaltung = models.BooleanField(default=False)
    erstellt_am = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ['-erstellt_am']; verbose_name = "Historie / Nachricht"

# ==============================================================================
# 5. GEBÄUDETECHNIK & DOKUMENTE
# ==============================================================================

class Dokument(models.Model):
    mandant = models.ForeignKey(Mandant, on_delete=models.SET_NULL, null=True, blank=True)
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, null=True, blank=True)
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, null=True, blank=True)
    mieter = models.ForeignKey(Mieter, on_delete=models.CASCADE, null=True, blank=True)
    vertrag = models.ForeignKey(Mietvertrag, on_delete=models.SET_NULL, null=True, blank=True, related_name='dokumente')
    bezeichnung = models.CharField(max_length=200, default="Dokument"); titel = models.CharField(max_length=200, blank=True)
    datei = models.FileField(upload_to=get_smart_upload_path)
    kategorie = models.CharField(max_length=50, choices=[('vertrag', 'Vertrag'), ('protokoll', 'Protokoll'), ('korrespondenz', 'Korrespondenz'), ('sonstiges', 'Sonstiges')])
    erstellt_am = models.DateTimeField(auto_now_add=True)
    class Meta: verbose_name = "Dokument"; verbose_name_plural = "Dokumente"
    def __str__(self): return self.bezeichnung

class Zaehler(models.Model):
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='zaehler')
    typ = models.CharField(max_length=20, choices=[('strom', 'Strom'), ('wasser', 'Wasser'), ('heizung', 'Heizung')])
    zaehler_nummer = models.CharField(max_length=50); standort = models.CharField(max_length=100, blank=True)
    class Meta: verbose_name = "Zähler"; verbose_name_plural = "Zähler"
    def __str__(self): return f"{self.typ} {self.zaehler_nummer}"

class ZaehlerStand(models.Model):
    zaehler = models.ForeignKey(Zaehler, on_delete=models.CASCADE, related_name='staende')
    datum = models.DateField(default=timezone.now); wert = models.DecimalField(max_digits=10, decimal_places=2)
    class Meta: verbose_name = "Zählerstand"

class Geraet(models.Model):
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='geraete')
    typ = models.CharField(max_length=50); marke = models.CharField(max_length=50); modell = models.CharField(max_length=100, blank=True)
    installations_datum = models.DateField(null=True, blank=True); garantie_bis = models.DateField(null=True, blank=True)
    class Meta: verbose_name = "Gerät"; verbose_name_plural = "Geräte"

class Unterhalt(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE)
    einheit = models.ForeignKey(Einheit, on_delete=models.SET_NULL, null=True, blank=True)
    titel = models.CharField(max_length=200); datum = models.DateField(default=timezone.now)
    kosten = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    beleg = models.FileField(upload_to=get_smart_upload_path, blank=True, null=True)
    class Meta: verbose_name = "Unterhalt"

class MietzinsAnpassung(models.Model):
    vertrag = models.ForeignKey(Mietvertrag, on_delete=models.CASCADE, related_name='anpassungen')
    wirksam_ab = models.DateField(); neuer_netto_mietzins = models.DecimalField(max_digits=10, decimal_places=2)
    class Meta: verbose_name = "Mietzinsanpassung"

class Leerstand(models.Model):
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='leerstaende')
    beginn = models.DateField(); ende = models.DateField(null=True, blank=True)
    grund = models.CharField(max_length=50, default='mietersuche'); bemerkung = models.TextField(blank=True)
    class Meta: verbose_name = "Leerstand"

class Schluessel(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE)
    schluessel_nummer = models.CharField(max_length=50)
    class Meta: verbose_name = "Schlüssel"

class SchluesselAusgabe(models.Model):
    schluessel = models.ForeignKey(Schluessel, on_delete=models.CASCADE, related_name='ausgaben')
    mieter = models.ForeignKey(Mieter, on_delete=models.SET_NULL, null=True, blank=True)
    handwerker = models.ForeignKey(Handwerker, on_delete=models.SET_NULL, null=True, blank=True)
    ausgegeben_am = models.DateField(default=timezone.now); rueckgabe_am = models.DateField(null=True, blank=True)
    class Meta: verbose_name = "Schlüsselausgabe"

# ==============================================================================
# 6. BUCHHALTUNG & KREDITOREN-SCANNER
# ==============================================================================

class Buchungskonto(models.Model):
    """Ein einfacher Kontenplan für deine Buchhaltung"""
    nummer = models.CharField("Kontonummer", max_length=10, unique=True)
    bezeichnung = models.CharField("Bezeichnung", max_length=100)
    typ = models.CharField("Typ", max_length=20, choices=[('aufwand', 'Aufwand'), ('ertrag', 'Ertrag'), ('bilanz', 'Bilanz')])

    class Meta:
        verbose_name = "Buchungskonto"
        verbose_name_plural = "Kontenplan (Buchhaltung)"
        ordering = ['nummer']

    def __str__(self):
        return f"{self.nummer} - {self.bezeichnung}"

class KreditorenRechnung(models.Model):
    STATUS_CHOICES = [
        ('offen', 'Offen (Unbezahlt)'),
        ('freigegeben', 'Freigegeben zur Zahlung'),
        ('bezahlt', 'Bezahlt'),
    ]

    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.SET_NULL, null=True, blank=True, help_text="Welchem Objekt wird die Rechnung belastet?")
    einheit = models.ForeignKey(Einheit, on_delete=models.SET_NULL, null=True, blank=True, help_text="Optional: Betroffene Einheit")
    konto = models.ForeignKey(Buchungskonto, on_delete=models.SET_NULL, null=True, blank=True, help_text="Aufwandskonto")

    lieferant = models.CharField("Kreditor / Lieferant", max_length=200, blank=True)
    datum = models.DateField("Rechnungsdatum", default=timezone.now, blank=True, null=True)
    faellig_am = models.DateField("Fällig am", blank=True, null=True)
    betrag = models.DecimalField("Rechnungsbetrag", max_digits=10, decimal_places=2, null=True, blank=True)
    iban = models.CharField("IBAN", max_length=50, blank=True)
    referenz = models.CharField("Referenznummer / QR-Ref", max_length=100, blank=True)

    status = models.CharField("Status", max_length=20, choices=STATUS_CHOICES, default='offen')
    beleg_scan = models.FileField(upload_to='kreditoren_belege/', blank=True, null=True)

    fehlermeldung = models.CharField("System-Info", max_length=255, blank=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kreditoren-Rechnung"
        verbose_name_plural = "Kreditoren-Rechnungen"
        ordering = ['-datum']

    def analyze_invoice_with_ai(self):
        """Sendet das PDF an Google Gemini zur Extraktion von IBAN, Betrag & Datum"""
        if not self.beleg_scan or not genai:
            return

        chosen_model = "Unbekannt"
        try:
            # Nutzt deinen hinterlegten Key
            genai.configure(api_key="AIzaSyBDdF-2rAcwX9tt9HSTIDyimLekUePu4Qo")

            # --- DYNAMISCHE MODELL-SUCHE (Jetzt auch für Kreditoren!) ---
            available_models = []
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    available_models.append(m.name)

            chosen_model = None
            for name in available_models:
                if '1.5-flash' in name:
                    chosen_model = name
                    break

            if not chosen_model:
                for name in available_models:
                    if 'gemini-1.0-pro-vision' in name or 'vision' in name or 'flash' in name:
                        chosen_model = name
                        break

            if not chosen_model and available_models:
                chosen_model = available_models[0]

            if not chosen_model:
                self.fehlermeldung = "KI-FEHLER: Keine passenden Modelle gefunden."
                return

            model = genai.GenerativeModel(chosen_model)
            # ---------------------------------------------------------

            beleg_file = genai.upload_file(self.beleg_scan.path)

            prompt = """
            Du bist ein professioneller Buchhalter in der Schweiz. Analysiere diese Kreditorenrechnung.
            Antworte AUSSCHLIESSLICH im JSON-Format ohne Markdown (kein ```json).
            Wenn du einen Wert nicht findest, setze null.
            Die IBAN soll ohne Leerzeichen formatiert sein.

            Struktur:
            {
              "betrag": 1250.50,
              "datum": "2024-03-15",
              "faellig_am": "2024-04-14",
              "lieferant": "Müller Sanitär AG",
              "iban": "CH1234567890123456789",
              "referenz": "123456789012345678901234567"
            }
            """

            response = model.generate_content([beleg_file, prompt])

            try:
                beleg_file.delete() # Datei bei Google aufräumen
            except: pass

            # JSON bereinigen und auslesen
            raw_json = response.text.replace('```json', '').replace('```', '').strip()
            data = json.loads(raw_json)

            # Daten eintragen
            if data.get("betrag"):
                self.betrag = Decimal(str(data["betrag"]))
            if data.get("datum"):
                self.datum = datetime.datetime.strptime(data["datum"], "%Y-%m-%d").date()
            if data.get("faellig_am"):
                self.faellig_am = datetime.datetime.strptime(data["faellig_am"], "%Y-%m-%d").date()
            if not self.lieferant and data.get("lieferant"):
                self.lieferant = data["lieferant"][:200]
            if not self.iban and data.get("iban"):
                self.iban = data["iban"].replace(" ", "")[:50]
            if not self.referenz and data.get("referenz"):
                self.referenz = str(data["referenz"]).replace(" ", "")[:100]

            self.fehlermeldung = "KI-Scan erfolgreich"

        except Exception as e:
            self.fehlermeldung = f"KI-FEHLER ({chosen_model}): {str(e)}"[:250]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        current_betrag = self.betrag

        super().save(*args, **kwargs)

        # Nur analysieren, wenn Beleg neu hochgeladen wurde und Betrag noch leer ist
        if self.beleg_scan and (not current_betrag or is_new):
            self.analyze_invoice_with_ai()
            super().save(update_fields=['betrag', 'datum', 'faellig_am', 'lieferant', 'iban', 'referenz', 'fehlermeldung'])

    def __str__(self):
        return f"{self.lieferant} - CHF {self.betrag} ({self.get_status_display()})"

# ==============================================================================
# 7. DEBITOREN & MIETEINNAHMEN
# ==============================================================================

class Zahlungseingang(models.Model):
    """Erfasst die eingehenden Mieten deiner Mieter"""

    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, related_name='zahlungen', null=True, blank=True)
    vertrag = models.ForeignKey(Mietvertrag, on_delete=models.SET_NULL, null=True, related_name='zahlungen')

    # Für welchen Monat ist die Miete gedacht? (Wichtig für die Kontrolle!)
    buchungs_monat = models.DateField("Für Monat/Jahr", help_text="Bitte immer den 1. des Monats wählen (z.B. 01.03.2026)")

    datum_eingang = models.DateField("Bezahlt am", default=timezone.now)
    betrag = models.DecimalField("Eingezahlter Betrag", max_digits=10, decimal_places=2)

    # Normalerweise "3000 Mietertrag Wohnungen"
    konto = models.ForeignKey(
        Buchungskonto,
        on_delete=models.SET_NULL,
        null=True,
        limit_choices_to={'typ': 'ertrag'}, # Zeigt im Dropdown nur Ertragskonten an!
        help_text="Ertragskonto"
    )

    bemerkung = models.CharField("Bemerkung / Verwendungszweck", max_length=200, blank=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Zahlungseingang (Miete)"
        verbose_name_plural = "Zahlungseingänge (Mieten)"
        ordering = ['-datum_eingang']

    def __str__(self):
        mieter_name = self.vertrag.mieter if self.vertrag else "Unbekannt"
        monat = self.buchungs_monat.strftime('%m/%Y') if self.buchungs_monat else ""
        return f"{mieter_name} - {monat} (CHF {self.betrag})"

    def save(self, *args, **kwargs):
        # Kleine Automatisierung: Liegenschaft automatisch aus dem Vertrag übernehmen
        if self.vertrag and not self.liegenschaft:
            self.liegenschaft = self.vertrag.einheit.liegenschaft

        # Wenn kein Konto gewählt wurde, nehmen wir automatisch "3000 Mietertrag" (falls es existiert)
        if not self.konto:
            try:
                self.konto = Buchungskonto.objects.get(nummer='3000')
            except Buchungskonto.DoesNotExist:
                pass

        super().save(*args, **kwargs)

# ==============================================================================
# 8. AUSWERTUNGEN & ERFOLGSRECHNUNG (SÄULE 3)
# ==============================================================================

class Jahresabschluss(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE)
    jahr = models.IntegerField("Abrechnungsjahr", default=datetime.date.today().year)
    notizen = models.TextField("Interne Notizen", blank=True)

    class Meta:
        verbose_name = "Erfolgsrechnung (GuV)"
        verbose_name_plural = "Erfolgsrechnungen (GuV)"
        unique_together = ('liegenschaft', 'jahr') # Verhindert doppelte pro Jahr

    def __str__(self):
        return f"Erfolgsrechnung {self.jahr} - {self.liegenschaft.strasse}"

class MietzinsKontrolle(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE)
    monat = models.DateField("Für Monat/Jahr", help_text="Immer den 1. des Monats wählen (z.B. 01.03.2026)")
    notizen = models.TextField("Interne Notizen", blank=True)

    class Meta:
        verbose_name = "Mietzins-Kontrolle (Scanner)"
        verbose_name_plural = "Mietzins-Kontrollen (Scanner)"
        unique_together = ('liegenschaft', 'monat')

    def __str__(self):
        return f"Mietzinskontrolle {self.monat.strftime('%m/%Y')} - {self.liegenschaft.strasse}"