# rentals/models.py
from django.db import models
from django.utils import timezone
from decimal import Decimal
from core.utils import get_current_ref_zins, get_current_lik, get_smart_upload_path

class Mietvertrag(models.Model):
    STATUS_CHOICES = [('offen', 'Offen'), ('gesendet', 'Versendet'), ('unterzeichnet', 'Unterzeichnet')]
    mieter = models.ForeignKey('crm.Mieter', on_delete=models.CASCADE, related_name='vertraege')

    # Das Hauptobjekt (z.B. Wohnung)
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='vertraege')

    # 🔥 NEU: Zusätzliche Objekte (Bastelraum, Parkplatz etc.)
    nebenobjekte = models.ManyToManyField('portfolio.Einheit', blank=True, related_name='als_nebenobjekt_in_vertraegen')

    beginn = models.DateField()
    ende = models.DateField(null=True, blank=True)
    netto_mietzins = models.DecimalField(max_digits=8, decimal_places=2)
    nebenkosten = models.DecimalField(max_digits=6, decimal_places=2)
    basis_referenzzinssatz = models.DecimalField(max_digits=4, decimal_places=2, default=get_current_ref_zins)
    basis_lik_punkte = models.DecimalField(max_digits=6, decimal_places=1, default=get_current_lik)
    aktiv = models.BooleanField(default=True)
    sign_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offen')
    pdf_datei = models.FileField(upload_to='vertraege_pdfs/', blank=True, null=True)
    kautions_betrag = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)

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

    # 🔥 NEU: Die intelligente Mietzins-Prüfung 🔥
    @property
    def mietzinspotenzial(self):
        try:
            from crm.models import Verwaltung
            vw = Verwaltung.objects.first()
            if not vw: return 'neutral'

            curr_zins = vw.aktueller_referenzzinssatz
            curr_lik = vw.aktueller_lik_punkte

            # 1. Priorität: Wenn der aktuelle Zins KLEINER ist als im Vertrag -> Senkungsrisiko!
            if curr_zins < self.basis_referenzzinssatz:
                return 'decrease'

            # 2. Wenn aktueller Zins GRÖSSER ist -> Erhöhungspotenzial!
            if curr_zins > self.basis_referenzzinssatz:
                return 'increase'

            # 3. LIK Prüfung (ab 1.5 Punkten Differenz lohnt sich meist eine Teuerungsausgleich)
            if curr_lik > (self.basis_lik_punkte + Decimal('1.5')):
                return 'increase'

            return 'neutral'
        except Exception:
            return 'neutral'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.sign_status == 'unterzeichnet' and self.pdf_datei:
            exists = Dokument.objects.filter(vertrag=self, kategorie='vertrag').exists()
            if not exists:
                Dokument.objects.create(
                    titel=f"Mietvertrag {self.mieter}",
                    kategorie='vertrag',
                    vertrag=self,
                    mieter=self.mieter,
                    einheit=self.einheit,
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
        verbose_name = "Mietzinsanpassung"
        db_table = 'core_mietzinsanpassung'

class Leerstand(models.Model):
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='leerstaende')
    beginn = models.DateField()
    ende = models.DateField(null=True, blank=True)
    grund = models.CharField(max_length=50, default='mietersuche')
    bemerkung = models.TextField(blank=True)

    class Meta:
        verbose_name = "Leerstand"
        db_table = 'core_leerstand'

class Dokument(models.Model):
    mandant = models.ForeignKey('crm.Mandant', on_delete=models.SET_NULL, null=True, blank=True)
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE, null=True, blank=True)
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, null=True, blank=True)
    mieter = models.ForeignKey('crm.Mieter', on_delete=models.CASCADE, null=True, blank=True)
    vertrag = models.ForeignKey(Mietvertrag, on_delete=models.SET_NULL, null=True, blank=True, related_name='dokumente')
    bezeichnung = models.CharField(max_length=200, default="Dokument")
    titel = models.CharField(max_length=200, blank=True)
    datei = models.FileField(upload_to=get_smart_upload_path)
    kategorie = models.CharField(max_length=50, choices=[('vertrag', 'Vertrag'), ('protokoll', 'Protokoll'), ('korrespondenz', 'Korrespondenz'), ('sonstiges', 'Sonstiges')])
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Dokument"
        verbose_name_plural = "Dokumente"
        db_table = 'core_dokument'

    def __str__(self): return self.bezeichnung