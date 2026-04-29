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

    # 🔥 NEU: HNK-Relevanz gemäss Experten-Feedback
    is_hnk_relevant = models.BooleanField(
        "HNK-relevant",
        default=False,
        help_text="Kennzeichnet, ob Buchungen auf diesem Konto in die Nebenkostenabrechnung fliessen (z.B. 4000er Konten)."
    )

    standard_verteilschluessel = models.CharField(
        "Standard-Verteilschlüssel",
        max_length=20,
        choices=[('m2', 'Fläche (m²)'), ('m3', 'Volumen (m³)'), ('einheit', 'Pro Einheit')],
        default='m2',
        blank=True
    )

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

    # 🔥 NEU: Für die Bestandesrechnung (Heizöl/Gas)
    anfangsbestand_liter = models.DecimalField("Anfangsbestand (L)", max_digits=10, decimal_places=2, default=0)
    anfangsbestand_chf = models.DecimalField("Anfangsbestand (CHF)", max_digits=10, decimal_places=2, default=0)
    endbestand_liter = models.DecimalField("Endbestand (L) am Stichtag", max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Abrechnungsperiode"
        verbose_name_plural = "Abrechnungsperioden"
        db_table = 'core_abrechnungsperiode'

    def __str__(self): return self.bezeichnung

    @property
    def total_kosten(self):
        # Summiert Nebenkostenbelege UND HNK-relevante Kreditorenrechnungen
        beleg_summe = self.belege.aggregate(total=Sum('betrag'))['total'] or Decimal('0.00')
        kreditoren_summe = KreditorenRechnung.objects.filter(
            liegenschaft=self.liegenschaft,
            is_hnk_relevant=True,
            leistungs_von__gte=self.start_datum,
            leistungs_bis__lte=self.ende_datum
        ).aggregate(total=Sum('betrag'))['total'] or Decimal('0.00')
        return beleg_summe + kreditoren_summe

    def berechne_mieter_anteil(self, vertrag):
        v_start = vertrag.beginn
        v_ende = vertrag.ende or self.ende_datum
        overlap_start = max(v_start, self.start_datum)
        overlap_end = min(v_ende, self.ende_datum)

        if overlap_start > overlap_end:
            return Decimal('0.00')

        tage_bewohnt = (overlap_end - overlap_start).days + 1
        tage_periode = (self.ende_datum - self.start_datum).days + 1
        zeit_faktor = Decimal(tage_bewohnt) / Decimal(tage_periode)

        kosten_m2 = self.belege.filter(verteilschluessel='m2').aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')
        kosten_einheit = self.belege.filter(verteilschluessel='einheit').aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')

        alle_einheiten = self.liegenschaft.einheiten.all()
        total_flaeche = sum(e.flaeche_m2 for e in alle_einheiten if e.flaeche_m2) or 1
        anzahl_einheiten = alle_einheiten.count() or 1

        mieter_flaeche = vertrag.einheit.flaeche_m2 or 0
        anteil_m2 = (kosten_m2 * Decimal(mieter_flaeche) / Decimal(total_flaeche)) * zeit_faktor
        anteil_einheit = (kosten_einheit / Decimal(anzahl_einheiten)) * zeit_faktor

        total_anteil = round(anteil_m2 + anteil_einheit, 2)
        return Decimal(str(total_anteil))

    def berechne_mieter_saldo(self, vertrag):
        effektive_kosten = self.berechne_mieter_anteil(vertrag)
        akonto_zahlungen = vertrag.zahlungen.filter(
            datum_eingang__range=[self.start_datum, self.ende_datum]
        ).aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')
        return effektive_kosten - akonto_zahlungen

    # --- Die "Heizgradtage" Logik für Mieterwechsel ---
    def get_heizgradtage_faktor(self, monat):
        """ Gibt den Schweizer Standard-Prozentsatz der Heizenergie pro Monat zurück """
        hgt = {1: 21, 2: 18, 3: 15, 4: 10, 5: 5, 6: 0, 7: 0, 8: 0, 9: 3, 10: 8, 11: 10, 12: 10}
        return Decimal(hgt.get(monat, 0)) / Decimal('100')

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
    VERTEIL_CHOICES = [('m2', 'Nach Fläche (m²)'), ('m3', 'Nach Volumen (m³)'), ('einheit', 'Pro Wohnung')]

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
        if not self.beleg_scan: return
        try:
            full_text = ""
            with pdfplumber.open(self.beleg_scan.path) as pdf:
                for page in pdf.pages:
                    full_text += page.extract_text() + "\n"

            text_lower = full_text.lower()
            if self.kategorie == 'diverse':
                kategorie_gefunden = False
                for regel in NebenkostenLernRegel.objects.all():
                    if regel.suchwort.lower() in text_lower:
                        self.kategorie = regel.kategorie_zuweisung
                        regel.treffer_quote += 1
                        regel.save()
                        kategorie_gefunden = True
                        break
                if not kategorie_gefunden:
                    mapping = {
                        'strom': ['strom', 'ewz', 'bkw', 'ckw', 'energie', 'elektro'],
                        'wasser': ['wasser', 'abwasser', 'wasserversorgung'],
                        'heizung': ['heizöl', 'brennstoff', 'erdgas', 'fernwärme'],
                        'hauswart': ['hauswartung', 'reinigung', 'garten', 'schneeräumung'],
                        'kehricht': ['kehricht', 'entsorgung', 'abfall'],
                        'lift': ['aufzug', 'lift', 'schindler', 'otis']
                    }
                    for cat, keywords in mapping.items():
                        if any(key in text_lower for key in keywords):
                            self.kategorie = cat
                            break

            if not self.betrag:
                matches = re.findall(r'(?:chf|total|betrag|summe)[\s\:\.]*([\d\'\s]+\.\d{2})', text_lower)
                if not matches:
                    matches = re.findall(r'\b(\d{1,3}(?:[\' ]\d{3})*\.\d{2})\b', full_text)
                if matches:
                    clean_amounts = []
                    for m in matches:
                        clean_val = m.replace("'", "").replace(" ", "")
                        try: clean_amounts.append(float(clean_val))
                        except: pass
                    if clean_amounts:
                        max_amount = max(clean_amounts)
                        if max_amount < 100000:
                            self.betrag = Decimal(str(max_amount))

            if not self.text:
                lines = [l.strip() for l in full_text.split('\n') if len(l.strip()) > 3]
                if lines: self.text = lines[0][:255]

        except Exception as e:
            if not self.text: self.text = f"Lokaler Scan Info: {str(e)[:50]}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if self.beleg_scan and is_new:
            self.extract_data_locally()
            if self.betrag is None:
                self.betrag = Decimal('0.00')
            super().save(update_fields=['betrag', 'text', 'kategorie'])

    def __str__(self): return f"{self.text or 'Beleg'} (CHF {self.betrag})"

class KreditorenRechnung(models.Model):
    STATUS_CHOICES = [
        ('neu', 'Neu / Scan'),
        ('freigegeben', 'Freigegeben'),
        ('bezahlt', 'Bezahlt'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='neu')
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.SET_NULL, null=True, blank=True)
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.SET_NULL, null=True, blank=True)
    konto = models.ForeignKey(Buchungskonto, on_delete=models.SET_NULL, null=True, blank=True)

    # 🔥 NEU: Die "Shift-Left" Felder für die HNK
    is_hnk_relevant = models.BooleanField("In HNK einbeziehen", default=False)
    leistungs_von = models.DateField("Leistungsperiode Von", null=True, blank=True)
    leistungs_bis = models.DateField("Leistungsperiode Bis", null=True, blank=True)
    menge_liter = models.DecimalField("Menge (Liter)", max_digits=10, decimal_places=2, null=True, blank=True)

    lieferant = models.CharField(max_length=200, blank=True)
    datum = models.DateField(null=True, blank=True)
    faellig_am = models.DateField(null=True, blank=True)
    betrag = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    iban = models.CharField(max_length=50, blank=True)
    referenz = models.CharField(max_length=100, blank=True)

    beleg_scan = models.FileField(upload_to='kreditoren_belege/', blank=True, null=True)
    fehlermeldung = models.TextField(blank=True)

    class Meta:
        verbose_name = "Kreditorenrechnung"
        db_table = 'core_kreditorenrechnung'

    def __str__(self): return f"{self.lieferant} - {self.betrag} ({self.status})"

class Zahlungseingang(models.Model):
    vertrag = models.ForeignKey('rentals.Mietvertrag', on_delete=models.SET_NULL, null=True, related_name='zahlungen')
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.SET_NULL, null=True, blank=True)
    konto = models.ForeignKey(Buchungskonto, on_delete=models.SET_NULL, null=True, blank=True)

    betrag = models.DecimalField(max_digits=10, decimal_places=2)
    datum_eingang = models.DateField(default=timezone.now)
    buchungs_monat = models.DateField("Für Monat/Jahr", null=True)
    bemerkung = models.CharField(max_length=255, blank=True, default='')
    erstellt_am = models.DateTimeField(default=timezone.now)

    class Meta: db_table = 'core_zahlungseingang'

class Jahresabschluss(models.Model):
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE)
    jahr = models.IntegerField(default=2026)
    notizen = models.TextField(blank=True, default='')

    class Meta: db_table = 'core_jahresabschluss'

class MietzinsKontrolle(models.Model):
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE)
    monat = models.DateField()
    notizen = models.TextField(blank=True, default='')

    class Meta: db_table = 'core_mietzinskontrolle'