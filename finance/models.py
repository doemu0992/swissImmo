# finance/models.py
import json
import datetime
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.conf import settings

try:
    import google.generativeai as genai
except ImportError:
    genai = None

class Buchungskonto(models.Model):
    nummer = models.CharField("Kontonummer", max_length=10, unique=True)
    bezeichnung = models.CharField("Bezeichnung", max_length=100)
    typ = models.CharField("Typ", max_length=20, choices=[('aufwand', 'Aufwand'), ('ertrag', 'Ertrag'), ('bilanz', 'Bilanz')])

    class Meta:
        verbose_name = "Buchungskonto"
        verbose_name_plural = "Kontenplan (Buchhaltung)"
        ordering = ['nummer']
        db_table = 'core_buchungskonto'

    def __str__(self): return f"{self.nummer} - {self.bezeichnung}"

class AbrechnungsPeriode(models.Model):
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE, related_name='abrechnungen')
    bezeichnung = models.CharField("Titel", max_length=100)
    start_datum = models.DateField()
    ende_datum = models.DateField()
    abgeschlossen = models.BooleanField(default=False)
    class Meta: verbose_name = "Abrechnungsperiode"; verbose_name_plural = "Abrechnungsperioden"; db_table = 'core_abrechnungsperiode'
    def __str__(self): return self.bezeichnung

class NebenkostenLernRegel(models.Model):
    suchwort = models.CharField("Schlüsselwort", max_length=100, unique=True)
    kategorie_zuweisung = models.CharField("Wird zugewiesen zu", max_length=50)
    text_vorschlag = models.CharField("Standard-Beschreibung", max_length=200)
    treffer_quote = models.IntegerField("Erfolgreich angewendet", default=0)
    class Meta: verbose_name = "KI Lern-Regel"; verbose_name_plural = "KI Lern-Regeln"; db_table = 'core_nebenkostenlernregel'
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

    class Meta: verbose_name = "Nebenkostenbeleg"; ordering = ['datum']; db_table = 'core_nebenkostenbeleg'

    def analyze_pdf_with_ai(self):
        if not self.beleg_scan: return
        if not genai:
            self.text = "SYSTEM-FEHLER: Das 'google-generativeai' Paket fehlt!"
            return

        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]

            chosen_model = next((name for name in available_models if '1.5-flash' in name), None)
            if not chosen_model: chosen_model = next((name for name in available_models if 'vision' in name or 'gemini-1.0-pro' in name), None)
            if not chosen_model and available_models: chosen_model = available_models[0]

            if not chosen_model:
                self.text = "KI-FEHLER: Keine passenden Modelle gefunden."
                return

            model = genai.GenerativeModel(chosen_model)
            beleg_file = genai.upload_file(self.beleg_scan.path)

            # --- Formatierter Prompt ohne Unterbrüche ---
            prompt = (
                "Du bist ein professioneller Buchhalter für Schweizer Immobilien. "
                "Analysiere den angehängten Beleg (Rechnung/Quittung). "
                "Antworte AUSSCHLIESSLICH im JSON-Format. "
                "Struktur: {\"betrag\": 1250.50, \"datum\": \"2024-03-15\", "
                "\"lieferant\": \"Müller Sanitär AG\", \"kategorie\": \"hauswart\"}"
            )

            response = model.generate_content([beleg_file, prompt])

            try: beleg_file.delete()
            except: pass

            raw_json = response.text.replace('```json', '').replace('```', '').strip()
            data = json.loads(raw_json)

            if data.get("betrag"): self.betrag = Decimal(str(data["betrag"]))
            if data.get("datum"): self.datum = datetime.datetime.strptime(data["datum"], "%Y-%m-%d").date()
            if not self.text and data.get("lieferant"): self.text = data["lieferant"][:255]

            ermittelte_kategorie = data.get("kategorie", "diverse")
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
            if not regel_angewendet: self.kategorie = ermittelte_kategorie
        except Exception as e:
            self.text = f"KI-FEHLER ({chosen_model}): {str(e)}"[:250]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        current_betrag = self.betrag
        super().save(*args, **kwargs)

        if self.beleg_scan and (not current_betrag or is_new):
            self.analyze_pdf_with_ai()
            super().save(update_fields=['betrag', 'datum', 'text', 'kategorie'])

        if self.kategorie != 'diverse' and self.text and len(self.text) > 3 and not self.text.startswith("KI-FEHLER") and not self.text.startswith("SYSTEM-FEHLER"):
            suchwort = self.text.lower().strip()
            if not NebenkostenLernRegel.objects.filter(suchwort=suchwort).exists():
                NebenkostenLernRegel.objects.create(suchwort=suchwort, kategorie_zuweisung=self.kategorie, text_vorschlag=self.text)

    def __str__(self): return f"{self.datum} - {self.text} (CHF {self.betrag})"

class KreditorenRechnung(models.Model):
    STATUS_CHOICES = [('offen', 'Offen (Unbezahlt)'), ('freigegeben', 'Freigegeben zur Zahlung'), ('bezahlt', 'Bezahlt')]

    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.SET_NULL, null=True, blank=True)
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.SET_NULL, null=True, blank=True)
    konto = models.ForeignKey(Buchungskonto, on_delete=models.SET_NULL, null=True, blank=True)

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
        db_table = 'core_kreditorenrechnung'

    def analyze_invoice_with_ai(self):
        if not self.beleg_scan or not genai: return
        chosen_model = "Unbekannt"
        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            chosen_model = next((name for name in available_models if '1.5-flash' in name), None)
            if not chosen_model: chosen_model = next((name for name in available_models if 'vision' in name or 'flash' in name), None)
            if not chosen_model and available_models: chosen_model = available_models[0]

            if not chosen_model:
                self.fehlermeldung = "KI-FEHLER: Keine passenden Modelle gefunden."
                return

            model = genai.GenerativeModel(chosen_model)
            beleg_file = genai.upload_file(self.beleg_scan.path)

            # --- Formatierter Prompt ohne Unterbrüche ---
            prompt = (
                "Du bist ein professioneller Buchhalter in der Schweiz. "
                "Analysiere diese Kreditorenrechnung. Antworte AUSSCHLIESSLICH im JSON-Format. "
                "Wenn du einen Wert nicht findest, setze null. Die IBAN soll ohne Leerzeichen formatiert sein. "
                "Struktur: {\"betrag\": 1250.50, \"datum\": \"2024-03-15\", \"faellig_am\": \"2024-04-14\", "
                "\"lieferant\": \"Müller Sanitär AG\", \"iban\": \"CH1234567890123456789\", "
                "\"referenz\": \"123456789012345678901234567\"}"
            )

            response = model.generate_content([beleg_file, prompt])

            try: beleg_file.delete()
            except: pass

            raw_json = response.text.replace('```json', '').replace('```', '').strip()
            data = json.loads(raw_json)

            if data.get("betrag"): self.betrag = Decimal(str(data["betrag"]))
            if data.get("datum"): self.datum = datetime.datetime.strptime(data["datum"], "%Y-%m-%d").date()
            if data.get("faellig_am"): self.faellig_am = datetime.datetime.strptime(data["faellig_am"], "%Y-%m-%d").date()
            if not self.lieferant and data.get("lieferant"): self.lieferant = data["lieferant"][:200]
            if not self.iban and data.get("iban"): self.iban = data["iban"].replace(" ", "")[:50]
            if not self.referenz and data.get("referenz"): self.referenz = str(data["referenz"]).replace(" ", "")[:100]

            self.fehlermeldung = "KI-Scan erfolgreich"
        except Exception as e:
            self.fehlermeldung = f"KI-FEHLER ({chosen_model}): {str(e)}"[:250]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        current_betrag = self.betrag
        super().save(*args, **kwargs)
        if self.beleg_scan and (not current_betrag or is_new):
            self.analyze_invoice_with_ai()
            super().save(update_fields=['betrag', 'datum', 'faellig_am', 'lieferant', 'iban', 'referenz', 'fehlermeldung'])

    def __str__(self): return f"{self.lieferant} - CHF {self.betrag} ({self.get_status_display()})"

class Zahlungseingang(models.Model):
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE, related_name='zahlungen', null=True, blank=True)
    vertrag = models.ForeignKey('rentals.Mietvertrag', on_delete=models.SET_NULL, null=True, related_name='zahlungen')
    buchungs_monat = models.DateField("Für Monat/Jahr", help_text="Bitte immer den 1. des Monats wählen")
    datum_eingang = models.DateField("Bezahlt am", default=timezone.now)
    betrag = models.DecimalField("Eingezahlter Betrag", max_digits=10, decimal_places=2)
    konto = models.ForeignKey(Buchungskonto, on_delete=models.SET_NULL, null=True, limit_choices_to={'typ': 'ertrag'})
    bemerkung = models.CharField("Bemerkung / Verwendungszweck", max_length=200, blank=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Zahlungseingang (Miete)"
        verbose_name_plural = "Zahlungseingänge (Mieten)"
        ordering = ['-datum_eingang']
        db_table = 'core_zahlungseingang'

    def __str__(self):
        mieter_name = self.vertrag.mieter if self.vertrag else "Unbekannt"
        monat = self.buchungs_monat.strftime('%m/%Y') if self.buchungs_monat else ""
        return f"{mieter_name} - {monat} (CHF {self.betrag})"

    def save(self, *args, **kwargs):
        if self.vertrag and not self.liegenschaft: self.liegenschaft = self.vertrag.einheit.liegenschaft
        if not self.konto:
            try: self.konto = Buchungskonto.objects.get(nummer='3000')
            except: pass
        super().save(*args, **kwargs)

class Jahresabschluss(models.Model):
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE)
    jahr = models.IntegerField("Abrechnungsjahr", default=datetime.date.today().year)
    notizen = models.TextField("Interne Notizen", blank=True)

    class Meta:
        verbose_name = "Erfolgsrechnung (GuV)"
        verbose_name_plural = "Erfolgsrechnungen (GuV)"
        unique_together = ('liegenschaft', 'jahr')
        db_table = 'core_jahresabschluss'

    def __str__(self): return f"Erfolgsrechnung {self.jahr} - {self.liegenschaft.strasse}"

class MietzinsKontrolle(models.Model):
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE)
    monat = models.DateField("Für Monat/Jahr", help_text="Immer den 1. des Monats wählen")
    notizen = models.TextField("Interne Notizen", blank=True)

    class Meta:
        verbose_name = "Mietzins-Kontrolle (Scanner)"
        verbose_name_plural = "Mietzins-Kontrollen (Scanner)"
        unique_together = ('liegenschaft', 'monat')
        db_table = 'core_mietzinskontrolle'

    def __str__(self): return f"Mietzinskontrolle {self.monat.strftime('%m/%Y')} - {self.liegenschaft.strasse}"