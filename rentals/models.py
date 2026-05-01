# rentals/models.py
from django.db import models
from django.utils import timezone
from decimal import Decimal
from core.utils import get_current_ref_zins, get_current_lik, get_smart_upload_path

class Mietvertrag(models.Model):
    STATUS_CHOICES = [('offen', 'Offen'), ('gesendet', 'Versendet'), ('unterzeichnet', 'Unterzeichnet')]

    VERTRAG_STATUS = [
        ('entwurf', 'Entwurf'),
        ('aktiv', 'Aktiv'),
        ('gekuendigt', 'Gekündigt'),
        ('archiviert', 'Archiviert')
    ]

    NK_TYP_CHOICES = [
        ('akonto', 'Akonto (Vorschuss mit Abrechnung)'),
        ('pauschal', 'Pauschal (fixer Betrag ohne Abrechnung)'),
        ('inbegriffen', 'Inbegriffen (im Nettomietzins enthalten)'),
        ('direkt', 'Direkt (Mieter zahlt direkt an Werke)'),
    ]

    VERTEIL_CHOICES = [
        ('m2', 'Fläche (m²)'),
        ('m3', 'Volumen (m³)'),
        ('quote', 'Wertquote'),
        ('einheit', 'Pro Einheit / Pauschal'),
        ('individuell', 'Individuelle Zähler (VHKA)'),
    ]

    ZAHLUNGSRHYTHMUS_CHOICES = [
        ('monatlich', 'monatlich'),
        ('vierteljahr', 'vierteljährlich'),
        ('halbjahr', 'halbjährlich'),
        ('jahr', 'jährlich'),
    ]

    mieter = models.ForeignKey('crm.Mieter', on_delete=models.CASCADE, related_name='vertraege')
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='vertraege')
    nebenobjekte = models.ManyToManyField('portfolio.Einheit', blank=True, related_name='als_nebenobjekt_in_vertraegen')

    # --- VERTRAGS-STATUS ---
    status = models.CharField("Vertragsstatus", max_length=20, choices=VERTRAG_STATUS, default='entwurf')
    aktiv = models.BooleanField(default=True)
    sign_status = models.CharField("Signatur-Status", max_length=20, choices=STATUS_CHOICES, default='offen')

    # --- FRISTEN & TERMINE ---
    beginn = models.DateField()
    ende = models.DateField(null=True, blank=True)
    erstmals_kuendbar_auf = models.DateField("Erstmals kündbar auf", null=True, blank=True) # 🔥 NEU
    kuendigungsfrist_monate = models.IntegerField("Kündigungsfrist (Monate)", default=3)
    kuendigungstermine = models.CharField("Kündigungstermine", max_length=100, default="Ende jedes Monats ausser Dezember", blank=True)

    # --- OBJEKT & NUTZUNG (🔥 NEU) ---
    familienwohnung = models.BooleanField("Familienwohnung", default=False)
    mitmieter_name = models.CharField("Ehegatte / Mitmieter", max_length=150, blank=True, default='') # 🔥 NEU
    anzahl_personen = models.IntegerField("Anzahl Personen", default=1)
    besondere_vereinbarungen = models.TextField("Besondere Vereinbarungen", blank=True, default='')

    # --- FINANZEN ---
    netto_mietzins = models.DecimalField(max_digits=8, decimal_places=2)
    nebenkosten = models.DecimalField(max_digits=6, decimal_places=2)
    nk_abrechnungsart = models.CharField("NK-Abrechnungsart", max_length=20, choices=NK_TYP_CHOICES, default='akonto')
    verteilschluessel = models.CharField("Verteilschlüssel", max_length=20, choices=VERTEIL_CHOICES, default='m2')
    ausgeschlossene_kosten = models.TextField("Ausgeschlossene Kosten", blank=True, help_text="Welche Kosten zahlt dieser Mieter NICHT?")
    zahlungsrhythmus = models.CharField("Zahlungsrhythmus", max_length=20, choices=ZAHLUNGSRHYTHMUS_CHOICES, default='monatlich') # 🔥 NEU

    # --- KAUTION ---
    kautions_betrag = models.DecimalField("Kautionsbetrag", max_digits=8, decimal_places=2, blank=True, null=True)
    kautions_konto = models.CharField("Kautionskonto (IBAN)", max_length=34, blank=True, default='')
    kautions_einbezahlt_am = models.DateField("Kaution einbezahlt am", null=True, blank=True)

    # --- BASES & VORBEHALTE (🔥 ERWEITERT) ---
    basis_referenzzinssatz = models.DecimalField(max_digits=4, decimal_places=2, default=get_current_ref_zins)
    basis_lik_punkte = models.DecimalField(max_digits=6, decimal_places=1, default=get_current_lik)
    kostensteigerung_datum = models.DateField("Kostensteigerung ausgeglichen bis", null=True, blank=True)
    mietzinsreserve_betrag = models.DecimalField("Reserve Betrag (CHF)", max_digits=8, decimal_places=2, null=True, blank=True)
    mietzinsreserve_prozent = models.DecimalField("Reserve Prozent (%)", max_digits=5, decimal_places=2, null=True, blank=True)
    weitere_vorbehalte = models.TextField("Weitere Vorbehalte", blank=True, default='')

    pdf_datei = models.FileField(upload_to='roh_vertraege/', blank=True, null=True)

    class Meta:
        verbose_name = "Mietvertrag"
        verbose_name_plural = "Mietverträge"
        db_table = 'core_mietvertrag'

    def __str__(self):
        base_str = f"{self.mieter} - {self.einheit}"
        if self.pk and self.nebenobjekte.exists():
            count = self.nebenobjekte.count()
            return f"{base_str} (+{count} Nebenobjekt{'e' if count > 1 else ''})"
        return base_str

    @property
    def brutto_mietzins(self):
        return (self.netto_mietzins or Decimal('0.00')) + (self.nebenkosten or Decimal('0.00'))

    @property
    def mietzinspotenzial(self):
        try:
            from crm.models import Verwaltung
            vw = Verwaltung.objects.first()
            if not vw: return 'neutral'
            curr_zins = vw.aktueller_referenzzinssatz
            curr_lik = vw.aktueller_lik_punkte
            if curr_zins < self.basis_referenzzinssatz: return 'decrease'
            if curr_zins > self.basis_referenzzinssatz: return 'increase'
            if curr_lik > (self.basis_lik_punkte + Decimal('1.5')): return 'increase'
            return 'neutral'
        except Exception:
            return 'neutral'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if self.sign_status == 'unterzeichnet' and self.pdf_datei:
            from portfolio.models import Dokument
            exists = Dokument.objects.filter(vertrag=self, kategorie='vertrag').exists()
            if not exists:
                Dokument.objects.create(
                    bezeichnung=f"Mietvertrag {self.mieter}",
                    titel=f"Unterzeichneter Mietvertrag - {self.einheit.bezeichnung}",
                    kategorie='vertrag',
                    vertrag=self,
                    mieter=self.mieter,
                    einheit=self.einheit,
                    liegenschaft=self.einheit.liegenschaft,
                    datei=self.pdf_datei
                )

class MietzinsAnpassung(models.Model):
    vertrag = models.ForeignKey(Mietvertrag, on_delete=models.CASCADE, related_name='anpassungen')
    wirksam_ab = models.DateField()
    neuer_netto_mietzins = models.DecimalField(max_digits=10, decimal_places=2)
    alter_netto_mietzins = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    alter_referenzzinssatz = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    alter_lik_index = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    neuer_referenzzinssatz = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    neuer_lik_index = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    erhoehung_prozent_total = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    begruendung = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'core_mietzinsanpassung'

class Leerstand(models.Model):
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='leerstaende')
    beginn = models.DateField()
    ende = models.DateField(null=True, blank=True)
    grund = models.CharField(max_length=50, default='mietersuche')
    bemerkung = models.TextField(blank=True)

    class Meta:
        db_table = 'core_leerstand'

class Dokument(models.Model):
    mandant = models.ForeignKey('crm.Mandant', on_delete=models.SET_NULL, null=True, blank=True)
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE, null=True, blank=True)
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, null=True, blank=True)
    mieter = models.ForeignKey('crm.Mieter', on_delete=models.CASCADE, null=True, blank=True)
    vertrag = models.ForeignKey(Mietvertrag, on_delete=models.SET_NULL, null=True, blank=True, related_name='dokument_ablage')
    bezeichnung = models.CharField(max_length=200, default="Dokument")
    titel = models.CharField(max_length=200, blank=True)
    datei = models.FileField(upload_to=get_smart_upload_path)
    kategorie = models.CharField(max_length=50, choices=[('vertrag', 'Vertrag'), ('protokoll', 'Protokoll'), ('korrespondenz', 'Korrespondenz'), ('sonstiges', 'Sonstiges')])
    datum = models.DateField(auto_now_add=True)

    class Meta:
        db_table = 'core_dokument'

    def __str__(self):
        return self.bezeichnung