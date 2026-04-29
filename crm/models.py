# crm/models.py
import io
from PIL import Image
from django.core.files.base import ContentFile
from django.db import models

class Verwaltung(models.Model):
    firma = models.CharField("Firmenname", max_length=100)
    strasse = models.CharField("Strasse & Nr.", max_length=100)
    plz = models.CharField("PLZ", max_length=10)
    ort = models.CharField("Ort", max_length=100)
    telefon = models.CharField("Telefon", max_length=30, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    logo = models.ImageField("Firmenlogo", upload_to="logos/", blank=True, null=True)
    unterschrift_bild = models.ImageField("Digitale Unterschrift", upload_to="unterschriften/", blank=True, null=True)
    aktueller_referenzzinssatz = models.DecimalField("Aktueller Ref.Zins", max_digits=4, decimal_places=2, default=1.75)
    aktueller_lik_punkte = models.DecimalField("Aktueller LIK", max_digits=6, decimal_places=1, default=107.1)
    letztes_update_marktdaten = models.DateTimeField("Letztes Update Marktdaten", null=True, blank=True)

    class Meta:
        verbose_name = "Meine Verwaltung"
        verbose_name_plural = "Meine Verwaltung"
        db_table = 'core_verwaltung'

    def __str__(self):
        return self.firma

    def save(self, *args, **kwargs):
        if self.unterschrift_bild:
            try:
                img = Image.open(self.unterschrift_bild)
                img = img.convert("RGBA")
                datas = img.getdata()
                newData = []
                for item in datas:
                    if item[0] > 200 and item[1] > 200 and item[2] > 200:
                        newData.append((255, 255, 255, 0))
                    else:
                        newData.append(item)
                img.putdata(newData)
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                filename = f"sig_vw_{self.id or 'new'}.png"
                self.unterschrift_bild.save(filename, ContentFile(buffer.getvalue()), save=False)
            except Exception as e:
                print(f"Fehler bei Hintergrund-Entfernung (Verwaltung): {e}")
        super().save(*args, **kwargs)


class Mandant(models.Model):
    firma_oder_name = models.CharField("Name / Firma (Eigentümer)", max_length=100)
    kontaktperson = models.CharField("Kontaktperson", max_length=100, blank=True)
    strasse = models.CharField("Strasse & Nr.", max_length=100, blank=True)
    plz = models.CharField("PLZ", max_length=10, blank=True)
    ort = models.CharField("Ort", max_length=100, blank=True)
    telefon = models.CharField("Telefon", max_length=30, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    bank_name = models.CharField("Bankname (Mandant)", max_length=100, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    unterschrift_bild = models.ImageField("Digitale Unterschrift", upload_to="unterschriften/", blank=True, null=True)

    class Meta:
        verbose_name = "Mandant (Eigentümer)"
        verbose_name_plural = "Mandanten (Eigentümer)"
        db_table = 'core_mandant'

    def __str__(self):
        return self.firma_oder_name

    def save(self, *args, **kwargs):
        if self.unterschrift_bild:
            try:
                img = Image.open(self.unterschrift_bild)
                img = img.convert("RGBA")
                datas = img.getdata()
                newData = []
                for item in datas:
                    if item[0] > 200 and item[1] > 200 and item[2] > 200:
                        newData.append((255, 255, 255, 0))
                    else:
                        newData.append(item)
                img.putdata(newData)
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                filename = f"sig_man_{self.id or 'new'}.png"
                self.unterschrift_bild.save(filename, ContentFile(buffer.getvalue()), save=False)
            except Exception as e:
                print(f"Fehler bei Hintergrund-Entfernung (Mandant): {e}")
        super().save(*args, **kwargs)


# 🔥 DER NEUE, AUFGERÜSTETE MIETER
class Mieter(models.Model):
    TYP_CHOICES = [
        ('person', 'Privatperson'),
        ('firma', 'Firma / Unternehmen'),
        ('verein', 'Verein / Stiftung')
    ]
    typ = models.CharField("Kunden-Typ", max_length=20, choices=TYP_CHOICES, default='person')

    # --- FIRMA / VEREIN ---
    firmen_name = models.CharField("Firmenname", max_length=200, blank=True, default='')
    uid_nummer = models.CharField("UID / CHE-Nummer", max_length=50, blank=True, default='')
    kontaktperson = models.CharField("Kontaktperson", max_length=100, blank=True, default='')

    # --- PRIVATPERSON ---
    anrede = models.CharField("Anrede", max_length=20, blank=True, default='Herr')
    vorname = models.CharField("Vorname", max_length=100, blank=True, default='')
    nachname = models.CharField("Nachname", max_length=100, blank=True, default='')
    geburtsdatum = models.DateField("Geburtsdatum", null=True, blank=True)
    ahv_nummer = models.CharField("AHV-Nummer", max_length=20, blank=True, default='')
    zivilstand = models.CharField("Zivilstand", max_length=50, blank=True, default='')
    nationalitaet = models.CharField("Nationalität", max_length=100, blank=True, default='')

    # --- KONTAKT ---
    email = models.EmailField("E-Mail", blank=True, default='')
    telefon_privat = models.CharField("Telefon Privat", max_length=50, blank=True, default='')
    telefon_geschaeft = models.CharField("Telefon Geschäft", max_length=50, blank=True, default='')
    mobile = models.CharField("Mobile", max_length=50, blank=True, default='')
    sprache = models.CharField("Korrespondenzsprache", max_length=2, default='de', choices=[('de', 'Deutsch'), ('fr', 'Französisch'), ('it', 'Italienisch'), ('en', 'Englisch')])

    # --- ADRESSE ---
    strasse = models.CharField("Strasse & Nr.", max_length=200, blank=True, default='')
    adresszusatz = models.CharField("Adresszusatz", max_length=100, blank=True, default='')
    postfach = models.CharField("Postfach", max_length=50, blank=True, default='')
    plz = models.CharField("PLZ", max_length=10, blank=True, default='')
    ort = models.CharField("Ort", max_length=100, blank=True, default='')
    land = models.CharField("Land", max_length=50, default='Schweiz')

    # --- FINANZEN & ADMIN ---
    iban = models.CharField("IBAN", max_length=34, blank=True, default='')
    bank_name = models.CharField("Bank", max_length=100, blank=True, default='')
    bonitaet_datum = models.DateField("Betreibungsauszug vom", null=True, blank=True)
    notizen = models.TextField("Interne Notizen", blank=True, default='')

    class Meta:
        verbose_name = "Mieter"
        verbose_name_plural = "Mieter"
        db_table = 'core_mieter'

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        if self.typ in ['firma', 'verein'] and self.firmen_name:
            return self.firmen_name
        return f"{self.vorname} {self.nachname}".strip() or "Unbekannter Kontakt"


class Handwerker(models.Model):
    firma = models.CharField("Firma", max_length=100)
    gewerk = models.CharField("Gewerk (z.B. Sanitär, Elektro)", max_length=100)
    kontaktperson = models.CharField("Kontaktperson", max_length=100, blank=True)
    strasse = models.CharField("Strasse & Nr.", max_length=100, blank=True)
    plz = models.CharField("PLZ", max_length=10, blank=True)
    ort = models.CharField("Ort", max_length=100, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    telefon = models.CharField("Telefon", max_length=30, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    notizen = models.TextField("Interne Notizen", blank=True)

    class Meta:
        verbose_name = "Handwerker"
        verbose_name_plural = "Handwerker"
        db_table = 'core_handwerker'

    def __str__(self):
        return self.firma