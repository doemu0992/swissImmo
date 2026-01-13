import os
import datetime
from itertools import chain
from django.db import models
from django.utils import timezone
from django.db.models import Sum, Q

# --- KONFIGURATION ---
STANDARD_REF_ZINS = 1.75
STANDARD_LIK_PUNKTE = 107.1

def get_smart_upload_path(instance, filename):
    heute = datetime.date.today().strftime("%Y-%m-%d")
    return os.path.join("uploads", heute, filename)

# ==============================================================================
# 1. VERWALTUNG (Deine Firma / "Crew")
# ==============================================================================
class Verwaltung(models.Model):
    """
    Hier werden deine Firmendaten gespeichert, die im Vertrag unter
    'Vertreten durch' erscheinen.
    """
    firma = models.CharField("Firmenname", max_length=100)
    strasse = models.CharField("Strasse & Nr.", max_length=100)
    plz = models.CharField("PLZ", max_length=10)
    ort = models.CharField("Ort", max_length=100)
    telefon = models.CharField("Telefon", max_length=30, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    webseite = models.URLField("Webseite", blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True, null=True)

    class Meta:
        verbose_name = "Meine Verwaltung"
        verbose_name_plural = "Meine Verwaltung"

    def __str__(self): return self.firma

class Mandant(models.Model):
    """
    Der Eigentümer der Liegenschaft.
    """
    firma_oder_name = models.CharField("Name / Firma (Eigentümer)", max_length=100)
    strasse = models.CharField("Strasse (Eigentümer)", max_length=100, blank=True)
    plz = models.CharField("PLZ", max_length=10, blank=True)
    ort = models.CharField("Ort", max_length=100, blank=True)
    unterschrift_bild = models.ImageField(upload_to="unterschriften/", blank=True, null=True, help_text="Scan der Unterschrift")
    bank_name = models.CharField("Bankname (Mandant)", max_length=100, blank=True)

    class Meta: verbose_name = "Mandant (Eigentümer)"; verbose_name_plural = "Mandanten (Eigentümer)"
    def __str__(self): return self.firma_oder_name

class Liegenschaft(models.Model):
    mandant = models.ForeignKey(Mandant, on_delete=models.CASCADE, related_name='liegenschaften', null=True, blank=True)

    # Verknüpfung zur Verwaltung (Wer betreut das Haus?)
    verwaltung = models.ForeignKey(Verwaltung, on_delete=models.SET_NULL, null=True, blank=True, related_name='liegenschaften', verbose_name="Zuständige Verwaltung")

    strasse = models.CharField("Strasse & Nr.", max_length=200)
    plz = models.CharField("PLZ", max_length=10)
    ort = models.CharField("Ort", max_length=100)

    egid = models.CharField("EGID", max_length=20, blank=True, null=True)
    kanton = models.CharField("Kanton", max_length=2, blank=True)
    baujahr = models.IntegerField("Baujahr", null=True, blank=True)
    kataster_nummer = models.CharField("Kataster-Nr.", max_length=50, blank=True)
    versicherungswert = models.DecimalField("Versicherungswert", max_digits=12, decimal_places=2, null=True, blank=True)

    bank_name = models.CharField("Bankname (Mietkonto)", max_length=100, blank=True, help_text="z.B. ZKB")
    iban = models.CharField("IBAN (Miete/NK)", max_length=34, blank=True, help_text="CH...")
    verteilschluessel_text = models.CharField("Verteilschlüssel (Text)", max_length=200, default="nach Wohnfläche (m2)")

    class Meta: verbose_name = "Liegenschaft"; verbose_name_plural = "Liegenschaften"
    def __str__(self): return f"{self.strasse}, {self.ort}"

class Einheit(models.Model):
    TYP_CHOICES = [('whg', 'Wohnung'), ('gew', 'Gewerbe'), ('pp', 'Parkplatz'), ('bas', 'Bastelraum')]
    POS_CHOICES = [('links', 'links'), ('rechts', 'rechts'), ('mitte', 'mitte'), ('hinten', 'hinten'), ('vorne', 'vorne'), ('oben', 'oben'), ('unten', 'unten')]
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, related_name='einheiten')
    ewid = models.CharField("EWID", max_length=20, blank=True, null=True)
    bezeichnung = models.CharField("Objektbezeichnung", max_length=50)
    typ = models.CharField("Typ", max_length=10, choices=TYP_CHOICES, default='whg')
    etage = models.CharField("Etage", max_length=20, blank=True)
    position = models.CharField("Position", max_length=20, choices=POS_CHOICES, blank=True)
    zimmer = models.DecimalField("Anz. Zimmer", max_digits=3, decimal_places=1, null=True, blank=True)
    flaeche_m2 = models.DecimalField("Fläche (m²)", max_digits=6, decimal_places=2, null=True, blank=True)
    wertquote = models.IntegerField("Wertquote (‰)", default=0)
    nettomiete_aktuell = models.DecimalField("Soll-Miete (Netto)", max_digits=8, decimal_places=2, default=0.00)
    nebenkosten_aktuell = models.DecimalField("Soll-Nebenkosten", max_digits=6, decimal_places=2, default=0.00)
    nk_abrechnungsart = models.CharField("NK-Art", max_length=20, default='pauschal', choices=[('akonto', 'Akonto'), ('pauschal', 'Pauschal')])
    ref_zinssatz = models.DecimalField("Basis Ref.Zins", max_digits=4, decimal_places=2, default=STANDARD_REF_ZINS)
    lik_punkte = models.DecimalField("Basis LIK", max_digits=6, decimal_places=1, default=STANDARD_LIK_PUNKTE)

    class Meta: verbose_name = "Einheit"; verbose_name_plural = "Einheiten"
    def __str__(self): return f"{self.liegenschaft.strasse} - {self.bezeichnung}"

    @property
    def navigation_label(self):
        vertrag = self.vertraege.filter(aktiv=True).first()
        if vertrag: return f"({vertrag.mieter.nachname} {vertrag.mieter.vorname})"
        return "(Leerstand)"

    @property
    def aktiver_vertrag(self): return self.vertraege.filter(aktiv=True).first()

    @property
    def verhaeltnisse(self):
        return sorted(chain(self.vertraege.all(), self.leerstaende.all()), key=lambda x: x.beginn, reverse=True)

# ==============================================================================
# 2. PERSONEN
# ==============================================================================

class Mieter(models.Model):
    ZIVILSTAND_CHOICES = [('ledig', 'ledig'), ('verheiratet', 'verheiratet'), ('geschieden', 'geschieden'), ('verwitwet', 'verwitwet'), ('partnerschaft', 'eingetragene Partnerschaft')]
    anrede = models.CharField(max_length=20, default='Herr', choices=[('Herr', 'Herr'), ('Frau', 'Frau'), ('Familie', 'Familie')])
    vorname = models.CharField(max_length=100)
    nachname = models.CharField(max_length=100)
    geburtsdatum = models.DateField("Geburtsdatum", null=True, blank=True)
    heimatort = models.CharField("Heimatort", max_length=100, blank=True)
    zivilstand = models.CharField("Zivilstand", max_length=20, choices=ZIVILSTAND_CHOICES, default='ledig')
    strasse = models.CharField("Strasse (Aktuell)", max_length=200, blank=True)
    plz = models.CharField("PLZ (Aktuell)", max_length=10, blank=True)
    ort = models.CharField("Ort (Aktuell)", max_length=100, blank=True)
    telefon = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    partner_name = models.CharField("Partner / Solidarhafter", max_length=200, blank=True)

    def __str__(self): return f"{self.nachname} {self.vorname}"
    class Meta: verbose_name = "Mieter"; verbose_name_plural = "Mieter"

class Handwerker(models.Model):
    firma = models.CharField(max_length=100)
    kontaktperson = models.CharField(max_length=100, blank=True)
    gewerk = models.CharField(max_length=100)
    telefon = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    iban = models.CharField(max_length=34, blank=True)
    def __str__(self): return f"{self.firma} ({self.gewerk})"

# ==============================================================================
# 3. VERTRÄGE
# ==============================================================================

class Mietvertrag(models.Model):
    STATUS_CHOICES = [('offen', 'Offen'), ('gesendet', 'Versendet (DocuSeal)'), ('unterzeichnet', 'Unterzeichnet')]

    mieter = models.ForeignKey(Mieter, on_delete=models.CASCADE, related_name='vertraege')
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='vertraege')
    beginn = models.DateField()
    ende = models.DateField(null=True, blank=True)
    netto_mietzins = models.DecimalField(max_digits=8, decimal_places=2)
    nebenkosten = models.DecimalField(max_digits=6, decimal_places=2)
    kautions_betrag = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    basis_referenzzinssatz = models.DecimalField(max_digits=4, decimal_places=2, default=STANDARD_REF_ZINS)
    basis_lik_punkte = models.DecimalField(max_digits=6, decimal_places=1, default=STANDARD_LIK_PUNKTE)
    aktiv = models.BooleanField(default=True)

    # DocuSeal
    sign_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offen')
    jotform_submission_id = models.CharField("DocuSeal ID", max_length=100, blank=True, null=True)
    pdf_datei = models.FileField(upload_to='vertraege_pdfs/', blank=True, null=True)

    class Meta: verbose_name = "Mietvertrag"; verbose_name_plural = "Mietverträge"; ordering = ['-beginn']
    def __str__(self): return f"{self.mieter} - {self.einheit}"

    @property
    def is_mietvertrag(self): return True

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and self.aktiv:
            self.einheit.leerstaende.filter(Q(ende__isnull=True)|Q(ende__gte=self.beginn), beginn__lt=self.beginn).update(ende=self.beginn - datetime.timedelta(days=1))

# ==============================================================================
# 4. SONSTIGES (Wichtig für Admin!)
# ==============================================================================

class Leerstand(models.Model):
    GRUND_CHOICES = [('mietersuche', 'Mietersuche'), ('sanierung', 'Sanierung'), ('eigenbedarf', 'Eigenbedarf'), ('verkauf', 'Verkauf'), ('kuendigung', 'Gekündigt')]
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='leerstaende')
    beginn = models.DateField("Beginn"); ende = models.DateField("Ende", null=True, blank=True)
    grund = models.CharField("Grund", max_length=50, choices=GRUND_CHOICES, default='mietersuche')
    bemerkung = models.TextField(blank=True)
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new: self.einheit.vertraege.filter(aktiv=True).update(ende=self.beginn - datetime.timedelta(days=1), aktiv=False)

class SchadenMeldung(models.Model):
    STATUS = [('neu', 'Neu'), ('beauftragt', 'Beauftragt'), ('erledigt', 'Erledigt')]
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE)
    einheit = models.ForeignKey(Einheit, on_delete=models.SET_NULL, null=True, blank=True)
    gemeldet_von = models.ForeignKey(Mieter, on_delete=models.SET_NULL, null=True, blank=True)
    betreff = models.CharField(max_length=200); beschreibung = models.TextField(); foto = models.ImageField(upload_to=get_smart_upload_path, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS, default='neu')
    erstellt_am = models.DateTimeField(auto_now_add=True)

class Unterhalt(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE)
    einheit = models.ForeignKey(Einheit, on_delete=models.SET_NULL, null=True, blank=True)
    titel = models.CharField(max_length=200); beschreibung = models.TextField(blank=True)
    datum = models.DateField(default=timezone.now); kosten = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    beleg = models.FileField(upload_to=get_smart_upload_path, blank=True, null=True)
    art = models.CharField(max_length=50, choices=[('reparatur', 'Reparatur'), ('renovation', 'Renovation'), ('investition', 'Investition')], default='reparatur')

class Zaehler(models.Model):
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='zaehler')
    typ = models.CharField(max_length=20, choices=[('strom', 'Strom'), ('wasser', 'Wasser'), ('heizung', 'Heizung')])
    zaehler_nummer = models.CharField(max_length=50); standort = models.CharField(max_length=100, blank=True)
    def __str__(self): return f"{self.typ} {self.zaehler_nummer}"

class ZaehlerStand(models.Model):
    zaehler = models.ForeignKey(Zaehler, on_delete=models.CASCADE, related_name='staende')
    datum = models.DateField(default=timezone.now); wert = models.DecimalField(max_digits=10, decimal_places=2)

class Geraet(models.Model):
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='geraete')
    typ = models.CharField("Gerätetyp", max_length=50); marke = models.CharField(max_length=50); modell = models.CharField(max_length=100, blank=True)
    installations_datum = models.DateField(null=True, blank=True); garantie_bis = models.DateField(null=True, blank=True)

class Dokument(models.Model):
    mandant = models.ForeignKey(Mandant, on_delete=models.SET_NULL, null=True, blank=True)
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, null=True, blank=True)
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, null=True, blank=True)
    mieter = models.ForeignKey(Mieter, on_delete=models.CASCADE, null=True, blank=True)
    vertrag = models.ForeignKey(Mietvertrag, on_delete=models.SET_NULL, null=True, blank=True, related_name='dokumente')
    titel = models.CharField(max_length=200, blank=True)
    bezeichnung = models.CharField(max_length=200, default="Dokument")
    datei = models.FileField(upload_to=get_smart_upload_path)
    kategorie = models.CharField(max_length=50, choices=[('vertrag', 'Vertrag'), ('Mietvertrag', 'Mietvertrag'), ('protokoll', 'Protokoll'), ('korrespondenz', 'Korrespondenz'), ('sonstiges', 'Sonstiges')])
    erstellt_am = models.DateTimeField(auto_now_add=True)
    def save(self, *args, **kwargs):
        if not self.bezeichnung and self.titel: self.bezeichnung = self.titel
        super().save(*args, **kwargs)
    def __str__(self): return self.bezeichnung

class AbrechnungsPeriode(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, related_name='abrechnungen')
    bezeichnung = models.CharField("Titel", max_length=100); start_datum = models.DateField(); ende_datum = models.DateField(); abgeschlossen = models.BooleanField(default=False)
    def __str__(self): return self.bezeichnung

class NebenkostenBeleg(models.Model):
    periode = models.ForeignKey(AbrechnungsPeriode, on_delete=models.CASCADE, related_name='belege')
    datum = models.DateField(); text = models.CharField(max_length=200); kategorie = models.CharField(max_length=100, choices=[('heizung', 'Heizung'), ('wasser', 'Wasser'), ('hauswart', 'Hauswart'), ('strom', 'Allgemeinstrom'), ('admin', 'Verwaltung')])
    betrag = models.DecimalField(max_digits=10, decimal_places=2); verteilschluessel = models.CharField(max_length=50, default='m2'); beleg_scan = models.FileField(upload_to=get_smart_upload_path, blank=True, null=True)

class MietzinsAnpassung(models.Model):
    vertrag = models.ForeignKey(Mietvertrag, on_delete=models.CASCADE)
    neuer_referenzzinssatz = models.DecimalField(max_digits=4, decimal_places=2); neuer_lik_index = models.DecimalField(max_digits=6, decimal_places=1); neue_miete = models.DecimalField(max_digits=8, decimal_places=2)
    datum_wirksam = models.DateField(); datum_erstellt = models.DateField(auto_now_add=True); pdf_datei = models.FileField(upload_to='mietzinsanpassungen/', blank=True, null=True)

class Schluessel(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE)
    schluessel_nummer = models.CharField(max_length=50); funktion = models.CharField(max_length=100, blank=True)
    def __str__(self): return f"{self.schluessel_nummer} ({self.funktion})"

class SchluesselAusgabe(models.Model):
    schluessel = models.ForeignKey(Schluessel, on_delete=models.CASCADE, related_name='ausgaben')
    mieter = models.ForeignKey(Mieter, on_delete=models.SET_NULL, null=True, blank=True); handwerker = models.ForeignKey(Handwerker, on_delete=models.SET_NULL, null=True, blank=True)
    ausgegeben_am = models.DateField(default=timezone.now); rueckgabe_am = models.DateField(null=True, blank=True); bemerkung = models.CharField(max_length=200, blank=True)