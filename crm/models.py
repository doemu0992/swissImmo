# crm/models.py
from django.db import models

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

    class Meta:
        verbose_name = "Meine Verwaltung"
        verbose_name_plural = "Meine Verwaltung"
        db_table = 'core_verwaltung'  # <--- SICHERT DEINE DATEN!

    def __str__(self): return self.firma

class Mandant(models.Model):
    firma_oder_name = models.CharField("Name / Firma (Eigentümer)", max_length=100)
    strasse = models.CharField("Strasse", max_length=100, blank=True)
    plz = models.CharField("PLZ", max_length=10, blank=True)
    ort = models.CharField("Ort", max_length=100, blank=True)
    unterschrift_bild = models.ImageField(upload_to="unterschriften/", blank=True, null=True)
    bank_name = models.CharField("Bankname (Mandant)", max_length=100, blank=True)

    class Meta:
        verbose_name = "Mandant (Eigentümer)"
        verbose_name_plural = "Mandanten (Eigentümer)"
        db_table = 'core_mandant'

    def __str__(self): return self.firma_oder_name

class Mieter(models.Model):
    anrede = models.CharField(max_length=20, default='Herr')
    vorname = models.CharField(max_length=100); nachname = models.CharField(max_length=100)
    telefon = models.CharField(max_length=30, blank=True); email = models.EmailField(blank=True)
    strasse = models.CharField(max_length=200, blank=True); plz = models.CharField(max_length=10, blank=True); ort = models.CharField(max_length=100, blank=True)
    geburtsdatum = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Mieter"
        verbose_name_plural = "Mieter"
        db_table = 'core_mieter'

    def __str__(self): return f"{self.nachname} {self.vorname}"

class Handwerker(models.Model):
    firma = models.CharField(max_length=100); gewerk = models.CharField(max_length=100)
    email = models.EmailField(blank=True); telefon = models.CharField(max_length=30, blank=True)
    iban = models.CharField(max_length=34, blank=True)

    class Meta:
        verbose_name = "Handwerker"
        verbose_name_plural = "Handwerker"
        db_table = 'core_handwerker'

    def __str__(self): return self.firma