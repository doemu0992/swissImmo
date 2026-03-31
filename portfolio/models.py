# portfolio/models.py
from django.db import models
from django.utils import timezone
from core.utils import get_current_ref_zins, get_current_lik, get_smart_upload_path

class Liegenschaft(models.Model):
    mandant = models.ForeignKey('crm.Mandant', on_delete=models.CASCADE, related_name='liegenschaften', null=True, blank=True)
    verwaltung = models.ForeignKey('crm.Verwaltung', on_delete=models.SET_NULL, null=True, blank=True, related_name='liegenschaften')
    strasse = models.CharField("Strasse & Nr.", max_length=200)
    plz = models.CharField("PLZ", max_length=10)
    ort = models.CharField("Ort", max_length=100)
    egid = models.CharField("EGID", max_length=20, blank=True, null=True)

    baujahr = models.IntegerField("Baujahr", null=True, blank=True)
    kataster_nummer = models.CharField("Kataster-Nr.", max_length=50, blank=True)
    versicherungswert = models.DecimalField("Versicherungswert", max_digits=12, decimal_places=2, null=True, blank=True)

    kanton = models.CharField("Kanton", max_length=2, blank=True)
    bank_name = models.CharField("Bankname", max_length=100, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    verteilschluessel_text = models.CharField("Verteilschlüssel", max_length=200, default="nach Wohnfläche (m2)")

    class Meta:
        verbose_name = "Liegenschaft"
        verbose_name_plural = "Liegenschaften"
        db_table = 'core_liegenschaft'

    def __str__(self): return f"{self.strasse}, {self.ort}"

class Einheit(models.Model):
    TYP_CHOICES = [('whg', 'Wohnung'), ('gew', 'Gewerbe'), ('pp', 'Parkplatz'), ('bas', 'Bastelraum')]
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, related_name='einheiten')
    bezeichnung = models.CharField("Objektbezeichnung", max_length=50)
    typ = models.CharField("Typ", max_length=10, choices=TYP_CHOICES, default='whg')

    ewid = models.CharField("EWID", max_length=20, blank=True, null=True)
    etage = models.CharField("Etage", max_length=50, blank=True)
    wertquote = models.DecimalField("Wertquote", max_digits=6, decimal_places=2, default=10.00)

    zimmer = models.DecimalField("Anz. Zimmer", max_digits=3, decimal_places=1, null=True, blank=True)
    flaeche_m2 = models.DecimalField("Fläche (m²)", max_digits=6, decimal_places=2, null=True, blank=True)
    nettomiete_aktuell = models.DecimalField("Soll-Miete", max_digits=8, decimal_places=2, default=0.00)
    nebenkosten_aktuell = models.DecimalField("Soll-Nebenkosten", max_digits=6, decimal_places=2, default=0.00)
    nk_abrechnungsart = models.CharField("NK-Art", max_length=20, default='pauschal', choices=[('akonto', 'Akonto'), ('pauschal', 'Pauschal')])
    ref_zinssatz = models.DecimalField("Basis Ref.Zins", max_digits=4, decimal_places=2, default=get_current_ref_zins)
    lik_punkte = models.DecimalField("Basis LIK", max_digits=6, decimal_places=1, default=get_current_lik)

    class Meta:
        verbose_name = "Einheit"
        verbose_name_plural = "Einheiten"
        db_table = 'core_einheit'

    def __str__(self): return f"{self.liegenschaft.strasse} - {self.bezeichnung}"

    @property
    def aktiver_vertrag(self): return self.vertraege.filter(aktiv=True).first()

class Zaehler(models.Model):
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='zaehler')
    typ = models.CharField(max_length=20, choices=[('strom', 'Strom'), ('wasser', 'Wasser'), ('heizung', 'Heizung')])
    zaehler_nummer = models.CharField(max_length=50); standort = models.CharField(max_length=100, blank=True)
    class Meta: verbose_name = "Zähler"; verbose_name_plural = "Zähler"; db_table = 'core_zaehler'
    def __str__(self): return f"{self.typ} {self.zaehler_nummer}"

class ZaehlerStand(models.Model):
    zaehler = models.ForeignKey(Zaehler, on_delete=models.CASCADE, related_name='staende')
    datum = models.DateField(default=timezone.now); wert = models.DecimalField(max_digits=10, decimal_places=2)
    class Meta: verbose_name = "Zählerstand"; db_table = 'core_zaehlerstand'

class Geraet(models.Model):
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='geraete')
    typ = models.CharField(max_length=50); marke = models.CharField(max_length=50); modell = models.CharField(max_length=100, blank=True)
    installations_datum = models.DateField(null=True, blank=True); garantie_bis = models.DateField(null=True, blank=True)
    class Meta: verbose_name = "Gerät"; verbose_name_plural = "Geräte"; db_table = 'core_geraet'

class Unterhalt(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE)
    einheit = models.ForeignKey(Einheit, on_delete=models.SET_NULL, null=True, blank=True)
    titel = models.CharField(max_length=200); datum = models.DateField(default=timezone.now)
    kosten = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    beleg = models.FileField(upload_to=get_smart_upload_path, blank=True, null=True)
    class Meta: verbose_name = "Unterhalt"; db_table = 'core_unterhalt'

class Schluessel(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE)
    schluessel_nummer = models.CharField(max_length=50)
    class Meta: verbose_name = "Schlüssel"; db_table = 'core_schluessel'

class SchluesselAusgabe(models.Model):
    schluessel = models.ForeignKey(Schluessel, on_delete=models.CASCADE, related_name='ausgaben')
    mieter = models.ForeignKey('crm.Mieter', on_delete=models.SET_NULL, null=True, blank=True)
    handwerker = models.ForeignKey('crm.Handwerker', on_delete=models.SET_NULL, null=True, blank=True)
    ausgegeben_am = models.DateField(default=timezone.now); rueckgabe_am = models.DateField(null=True, blank=True)
    class Meta: verbose_name = "Schlüsselausgabe"; db_table = 'core_schluesselausgabe'