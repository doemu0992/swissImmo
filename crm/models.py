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
        """Entfernt den weissen Hintergrund aus der Unterschrift vor dem Speichern."""
        if self.unterschrift_bild:
            try:
                img = Image.open(self.unterschrift_bild)
                img = img.convert("RGBA")
                datas = img.getdata()

                newData = []
                for item in datas:
                    # Macht weisse/fast-weisse Pixel transparent (Toleranzwert 200)
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
        """Entfernt den weissen Hintergrund aus der Unterschrift vor dem Speichern."""
        if self.unterschrift_bild:
            try:
                img = Image.open(self.unterschrift_bild)
                img = img.convert("RGBA")
                datas = img.getdata()

                newData = []
                for item in datas:
                    # Macht weisse/fast-weisse Pixel transparent (Toleranzwert 200)
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


class Mieter(models.Model):
    is_company = models.BooleanField("Ist eine Firma?", default=False)
    firma = models.CharField("Firmenname", max_length=150, blank=True)
    anrede = models.CharField("Anrede", max_length=20, default='Herr', blank=True)
    vorname = models.CharField("Vorname", max_length=100, blank=True)
    nachname = models.CharField("Nachname", max_length=100, blank=True)
    telefon = models.CharField("Telefon", max_length=30, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    strasse = models.CharField("Strasse & Nr.", max_length=200, blank=True)
    adresszusatz = models.CharField("Adresszusatz (z.B. c/o)", max_length=100, blank=True)
    plz = models.CharField("PLZ", max_length=10, blank=True)
    ort = models.CharField("Ort", max_length=100, blank=True)
    geburtsdatum = models.DateField("Geburtsdatum", null=True, blank=True)
    ahv_nummer = models.CharField("AHV-Nummer", max_length=20, blank=True)
    nationalitaet = models.CharField("Nationalität", max_length=50, blank=True)

    class Meta:
        verbose_name = "Mieter"
        verbose_name_plural = "Mieter"
        db_table = 'core_mieter'

    def __str__(self):
        if self.is_company and self.firma:
            return self.firma
        return f"{self.nachname} {self.vorname}".strip()


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