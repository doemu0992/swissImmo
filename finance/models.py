# finance/models.py
import pdfplumber
import re
import datetime
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.db.models import Sum

class Buchungskonto(models.Model):
    nummer = models.CharField("Kontonummer", max_length=10, unique=True)
    bezeichnung = models.CharField("Bezeichnung", max_length=100)
    typ = models.CharField("Typ", max_length=20, choices=[('aufwand', 'Aufwand'), ('ertrag', 'Ertrag'), ('bilanz', 'Bilanz')])

    class Meta:
        verbose_name = "Buchungskonto"
        verbose_name_plural = "Kontenplan"
        ordering = ['nummer']
        db_table = 'core_buchungskonto'

    def __str__(self): return f"{self.nummer} - {self.bezeichnung}"

class AbrechnungsPeriode(models.Model):
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE, related_name='abrechnungen')
    bezeichnung = models.CharField("Titel", max_length=100)
    start_datum = models.DateField()
    ende_datum = models.DateField()
    abgeschlossen = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Abrechnungsperiode"
        verbose_name_plural = "Abrechnungsperioden"
        db_table = 'core_abrechnungsperiode'

    def __str__(self): return self.bezeichnung

    # --- 🧮 DER LIVE RECHNER FÜR DIE KOSTENVERTEILUNG 🧮 ---

    @property
    def total_kosten(self):
        """Rechnet alle Belege dieser Periode zusammen"""
        summe = self.belege.aggregate(total=Sum('betrag'))['total']
        return summe or Decimal('0.00')

    def berechne_mieter_anteil(self, vertrag):
        """
        Berechnet den exakten Anteil eines Mietvertrags an dieser Periode.
        Berücksichtigt Verteilschlüssel (m2 / Einheit) und Wohndauer (Tage).
        """
        # 1. Zeit-Faktor berechnen (Wie viele Tage war der Mieter da?)
        v_start = vertrag.beginn
        v_ende = vertrag.ende or self.ende_datum

        # Überschneidung der Daten herausfinden (Pro-Rata-Temporis)
        overlap_start = max(v_start, self.start_datum)
        overlap_end = min(v_ende, self.ende_datum)

        if overlap_start > overlap_end:
            return Decimal('0.00') # Mieter hat in dieser Periode gar nicht hier gewohnt

        tage_bewohnt = (overlap_end - overlap_start).days + 1
        tage_periode = (self.ende_datum - self.start_datum).days + 1
        zeit_faktor = Decimal(tage_bewohnt) / Decimal(tage_periode)

        # 2. Gesamtkosten nach Verteilschlüssel trennen
        kosten_m2 = self.belege.filter(verteilschluessel='m2').aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')
        kosten_einheit = self.belege.filter(verteilschluessel='einheit').aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')

        # 3. Kennzahlen des Gebäudes holen
        alle_einheiten = self.liegenschaft.einheiten.all()
        total_flaeche = sum(e.flaeche_m2 for e in alle_einheiten if e.flaeche_m2) or 1
        anzahl_einheiten = alle_einheiten.count() or 1

        # 4. Kennzahlen des Mieters holen
        mieter_flaeche = vertrag.einheit.flaeche_m2 or 0

        # 5. Finale Mathematik (Kosten * Anteil * Zeitfaktor)
        anteil_m2 = (kosten_m2 * Decimal(mieter_flaeche) / Decimal(total_flaeche)) * zeit_faktor
        anteil_einheit = (kosten_einheit / Decimal(anzahl_einheiten)) * zeit_faktor

        # Abrunden auf 2 Dezimalstellen
        total_anteil = round(anteil_m2 + anteil_einheit, 2)
        return Decimal(str(total_anteil))

    def berechne_mieter_saldo(self, vertrag):
        """Berechnet: Effektive Kosten minus bereits geleistete Akonto-Zahlungen"""
        effektive_kosten = self.berechne_mieter_anteil(vertrag)

        # Zahlungen des Mieters in dieser Zeitspanne addieren
        akonto_zahlungen = vertrag.zahlungen.filter(
            datum_eingang__range=[self.start_datum, self.ende_datum]
        ).aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')

        # Positiv = Mieter muss nachzahlen / Negativ = Mieter kriegt Geld zurück
        return effektive_kosten - akonto_zahlungen

class NebenkostenLernRegel(models.Model):
    suchwort = models.CharField("Schlüsselwort (z.B. Firmenname)", max_length=100, unique=True)
    kategorie_zuweisung = models.CharField("Wird zugewiesen zu", max_length=50)
    treffer_quote = models.IntegerField("Erfolgreich angewendet", default=0)

    class Meta:
        verbose_name = "KI Lern-Regel"
        verbose_name_plural = "KI Lern-Regeln"
        db_table = 'core_nebenkostenlernregel'

    def __str__(self): return f"'{self.suchwort}' -> {self.kategorie_zuweisung}"

class NebenkostenBeleg(models.Model):
    NK_KATEGORIE_CHOICES = [
        ('heizung', 'Heizung & Warmwasser'),
        ('wasser', 'Wasser / Abwasser'),
        ('hauswart', 'Hauswartung & Reinigung'),
        ('strom', 'Allgemeinstrom'),
        ('lift', 'Serviceabo Lift'),
        ('verwaltung', 'Verwaltungshonorar'),
        ('tv', 'TV / Kabelgebühren'),
        ('kehricht', 'Kehricht / Entsorgung'),
        ('diverse', 'Diverse Betriebskosten'),
    ]
    VERTEIL_CHOICES = [('m2', 'Nach Fläche (m²)'), ('einheit', 'Pro Wohnung')]

    periode = models.ForeignKey(AbrechnungsPeriode, on_delete=models.CASCADE, related_name='belege')
    datum = models.DateField(default=timezone.now, blank=True, null=True)
    text = models.CharField("Beschreibung / Lieferant", max_length=255, blank=True)
    kategorie = models.CharField(max_length=50, choices=NK_KATEGORIE_CHOICES, default='diverse')
    verteilschluessel = models.CharField("Verteilschlüssel", max_length=20, choices=VERTEIL_CHOICES, default='m2')
    betrag = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    beleg_scan = models.FileField(upload_to='nebenkosten_belege/', blank=True, null=True)

    class Meta:
        verbose_name = "Nebenkostenbeleg"
        db_table = 'core_nebenkostenbeleg'

    def extract_data_locally(self):
        """Liest das PDF aus und wendet smarte Logik an (ohne externe KI)"""
        if not self.beleg_scan: return

        try:
            full_text = ""
            with pdfplumber.open(self.beleg_scan.path) as pdf:
                for page in pdf.pages:
                    full_text += page.extract_text() + "\n"

            text_lower = full_text.lower()

            # --- 1. KATEGORIE AUTOMATISCH BESTIMMEN ---
            # Überschreibe nur, wenn die Kategorie noch auf dem Standard "diverse" steht
            if self.kategorie == 'diverse':
                kategorie_gefunden = False

                # A) Zuerst eigene Lern-Regeln aus der Datenbank prüfen
                for regel in NebenkostenLernRegel.objects.all():
                    if regel.suchwort.lower() in text_lower:
                        self.kategorie = regel.kategorie_zuweisung
                        regel.treffer_quote += 1
                        regel.save()
                        kategorie_gefunden = True
                        break

                # B) Wenn keine eigene Regel greift, Fallback auf Standard-Schlagworte
                if not kategorie_gefunden:
                    mapping = {
                        'strom': ['strom', 'ewz', 'bkw', 'ckw', 'energie', 'elektro', 'beleuchtung'],
                        'wasser': ['wasser', 'abwasser', 'wasserversorgung', 'kanalisation'],
                        'heizung': ['heizöl', 'brennstoff', 'erdgas', 'fernwärme', 'pellets', 'wärme'],
                        'hauswart': ['hauswartung', 'reinigung', 'garten', 'schneeräumung', 'unterhalt'],
                        'kehricht': ['kehricht', 'entsorgung', 'abfall', 'müll', 'container'],
                        'lift': ['aufzug', 'lift', 'schindler', 'otis', 'kone']
                    }
                    for cat, keywords in mapping.items():
                        if any(key in text_lower for key in keywords):
                            self.kategorie = cat
                            break

            # --- 2. BETRAG FINDEN ---
            # Nur ausfüllen, wenn du das Feld im Formular leer gelassen hast
            if not self.betrag:
                # Sucht nach "CHF", "Total" oder "Betrag" gefolgt von einer Schweizer Zahl (z.B. 1'250.00)
                matches = re.findall(r'(?:chf|total|betrag|summe)[\s\:\.]*([\d\'\s]+\.\d{2})', text_lower)

                if not matches:
                    # Fallback: Einfach nach allen Beträgen im Dokument suchen
                    matches = re.findall(r'\b(\d{1,3}(?:[\' ]\d{3})*\.\d{2})\b', full_text)

                if matches:
                    clean_amounts = []
                    for m in matches:
                        clean_val = m.replace("'", "").replace(" ", "")
                        try: clean_amounts.append(float(clean_val))
                        except: pass

                    if clean_amounts:
                        # Nimm den höchsten Betrag (Rechnungstotal ist fast immer die grösste Zahl)
                        max_amount = max(clean_amounts)
                        if max_amount < 100000: # Plausibilitätscheck (keine absurden Zahlen)
                            self.betrag = Decimal(str(max_amount))

            # --- 3. LIEFERANT / TEXT ---
            # Nur ausfüllen, wenn manuell noch nichts eingetragen wurde
            if not self.text:
                lines = [l.strip() for l in full_text.split('\n') if len(l.strip()) > 3]
                if lines:
                    self.text = lines[0][:255] # Nimmt oft den Briefkopf/Absender

        except Exception as e:
            if not self.text:
                self.text = f"Lokaler Scan Info: {str(e)[:50]}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        # Zuerst speichern, damit die Datei auf der Festplatte ist
        super().save(*args, **kwargs)

        # Nur bei einem komplett neuen Upload scannen (Verhindert überschreiben bei späteren Edits)
        if self.beleg_scan and is_new:
            self.extract_data_locally()

            # Falls gar nichts gefunden wurde und manuell nichts eingetragen ist -> 0.00
            if self.betrag is None:
                self.betrag = Decimal('0.00')

            super().save(update_fields=['betrag', 'text', 'kategorie'])

    def __str__(self): return f"{self.text or 'Beleg'} (CHF {self.betrag})"

# --- Hilfsklassen ---

class KreditorenRechnung(models.Model):
    lieferant = models.CharField(max_length=200, blank=True)
    betrag = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    beleg_scan = models.FileField(upload_to='kreditoren_belege/', blank=True, null=True)
    class Meta: db_table = 'core_kreditorenrechnung'

class Zahlungseingang(models.Model):
    vertrag = models.ForeignKey('rentals.Mietvertrag', on_delete=models.SET_NULL, null=True, related_name='zahlungen')
    betrag = models.DecimalField(max_digits=10, decimal_places=2)
    datum_eingang = models.DateField(default=timezone.now)
    buchungs_monat = models.DateField("Für Monat/Jahr", null=True)
    class Meta: db_table = 'core_zahlungseingang'

class Jahresabschluss(models.Model):
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE)
    jahr = models.IntegerField(default=2026)
    class Meta: db_table = 'core_jahresabschluss'

class MietzinsKontrolle(models.Model):
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE)
    monat = models.DateField()
    class Meta: db_table = 'core_mietzinskontrolle'