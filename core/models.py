from django.db import models
from ckeditor.fields import RichTextField
import uuid
from datetime import date

# --- STAMMDATEN ---
class Liegenschaft(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    strasse = models.CharField("Strasse & Nr.", max_length=100)
    plz = models.CharField("PLZ", max_length=10)
    ort = models.CharField("Ort", max_length=100)
    kanton = models.CharField(max_length=2, default='ZH')
    egid = models.PositiveIntegerField("EGID", null=True, blank=True)
    konto_iban = models.CharField("Mietzins-Konto IBAN", max_length=34)

    class Meta: verbose_name_plural = "Liegenschaften"
    def __str__(self): return f"{self.strasse}, {self.ort}"

class Einheit(models.Model):
    TYP_CHOICES = [('WOHNEN', 'Wohnung'), ('GEWERBE', 'Gewerbe'), ('PARK', 'Parkplatz')]
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, related_name="einheiten")
    bezeichnung = models.CharField(max_length=50)
    typ = models.CharField(max_length=10, choices=TYP_CHOICES, default='WOHNEN')
    zimmer = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    flaeche_m2 = models.DecimalField("Fläche (m²)", max_digits=6, decimal_places=2)
    etage = models.IntegerField(default=0)

    class Meta: verbose_name_plural = "Einheiten"
    def __str__(self): return f"{self.bezeichnung} ({self.liegenschaft.strasse})"

class Mieter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma = models.CharField(max_length=100, blank=True)
    vorname = models.CharField(max_length=100, blank=True)
    nachname = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    telefon = models.CharField(max_length=30, blank=True)
    bank_iban = models.CharField("Auszahlungs-IBAN", max_length=34, blank=True)

    class Meta: verbose_name_plural = "Mieter"
    def __str__(self): return f"{self.nachname} {self.vorname}"

# --- VERTRAGSWESEN ---
class Mietvertrag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    einheit = models.ForeignKey(Einheit, on_delete=models.PROTECT, related_name="vertraege")
    mieter = models.ForeignKey(Mieter, on_delete=models.PROTECT, related_name="vertraege")
    vertragsbeginn = models.DateField()
    vertragsende = models.DateField(null=True, blank=True)
    netto_mietzins = models.DecimalField(max_digits=8, decimal_places=2)
    nk_akonto = models.DecimalField("HK/NK Akonto", max_digits=8, decimal_places=2, default=0.00)
    basis_referenzzinssatz = models.DecimalField("Ref.Zins (%)", max_digits=4, decimal_places=2, default=1.75)
    mietzinsdepot = models.DecimalField("Depot", max_digits=8, decimal_places=2, null=True, blank=True)
    aktiv = models.BooleanField(default=True)

    class Meta: verbose_name_plural = "Mietverträge"
    def __str__(self): return f"{self.mieter} - {self.einheit}"
    
    @property
    def bruttomietzins(self):
        return self.netto_mietzins + self.nk_akonto

# --- DOKUMENTE ---
class DokumentVorlage(models.Model):
    titel = models.CharField(max_length=100)
    inhalt = RichTextField(help_text="Platzhalter: {{ mieter_name }}, {{ netto_mietzins }}, {{ brutto_total }}")
    def __str__(self): return self.titel

# --- SCHLÜSSEL ---
class Schluessel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE)
    system = models.CharField(max_length=100)
    schluessel_nummer = models.CharField(max_length=50)
    funktion = models.CharField(max_length=100)
    bestand_total = models.PositiveIntegerField(default=1)

    class Meta: verbose_name_plural = "Schlüsselverwaltung"
    def __str__(self): return f"{self.schluessel_nummer} ({self.funktion})"
    
    def verfuegbar(self):
        ausgegeben = self.ausleihen.filter(rueckgabe_datum__isnull=True).count()
        return self.bestand_total - ausgegeben

class SchluesselAusgabe(models.Model):
    schluessel = models.ForeignKey(Schluessel, on_delete=models.CASCADE, related_name="ausleihen")
    mieter = models.ForeignKey(Mieter, on_delete=models.SET_NULL, null=True, blank=True)
    empfaenger_extern = models.CharField(max_length=100, blank=True)
    ausgabe_datum = models.DateField(default=date.today)
    rueckgabe_datum = models.DateField(null=True, blank=True)
    unterschrift_vorhanden = models.BooleanField(default=False)

# --- SCHÄDEN ---
class Handwerker(models.Model):
    firmenname = models.CharField(max_length=100)
    branche = models.CharField(max_length=50)
    email = models.EmailField()
    telefon = models.CharField(max_length=30)
    def __str__(self): return self.firmenname

class SchadenMeldung(models.Model):
    STATUS_CHOICES = [('NEU', 'Neu'), ('IN_ARBEIT', 'In Arbeit'), ('ERLEDIGT', 'Erledigt')]
    PRIORITAET_CHOICES = [('HOCH', 'Notfall'), ('MITTEL', 'Normal'), ('NIEDRIG', 'Schönheit')]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mietvertrag = models.ForeignKey(Mietvertrag, on_delete=models.CASCADE)
    betreff = models.CharField(max_length=100)
    beschreibung = models.TextField()
    foto = models.ImageField(upload_to='schaden_fotos/', null=True, blank=True)
    prioritaet = models.CharField(max_length=10, choices=PRIORITAET_CHOICES, default='MITTEL')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NEU')
    beauftragter_handwerker = models.ForeignKey(Handwerker, on_delete=models.SET_NULL, null=True, blank=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name_plural = "Schadensmeldungen"
        ordering = ['-erstellt_am']
