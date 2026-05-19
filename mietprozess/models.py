import pdfplumber
from django.db import models
from portfolio.models import Einheit

# ==========================================
# 🔥 SMART SCANNER LOGIK
# ==========================================
def scan_pdf_for_betreibungen(file_obj):
    """
    Liest das PDF aus und sucht nach Betreibungen.
    Gibt True zurück (hat Betreibungen), False (sauber), oder None (unklar/Fehler).
    """
    try:
        text = ""
        file_obj.seek(0)  # Sicherstellen, dass wir am Anfang der Datei lesen
        with pdfplumber.open(file_obj) as pdf:
            for page in pdf.pages:
                ext = page.extract_text()
                if ext:
                    text += ext

        text_lower = text.lower()

        # 1. Alarm-Worte (Verlustscheine, Pfändungen)
        warn_keywords = ["verlustschein", "pfändung", "saisie", "acte de défaut"]
        if any(k in text_lower for k in warn_keywords):
            return True  # 🚨 Hat Betreibungen!

        # 2. Die magischen Worte für "Alles super"
        sauber_keywords = ["keine betreibungen", "aucune poursuite", "nessuna esecuzione", "nicht verzeichnet"]
        if any(k in text_lower for k in sauber_keywords):
            return False  # ✅ Alles sauber!

        return None # Unklar (muss manuell geprüft werden)
    except Exception as e:
        print(f"PDF Scanner Error: {e}")
        return None


# ==========================================
# DATENBANK MODELLE
# ==========================================
class Mietbewerbung(models.Model):
    STATUS_CHOICES = [
        ('neu', 'Neu eingegangen'),
        ('geprueft', 'Bonität geprüft'),
        ('zugesagt', 'Zusage erteilt'),
        ('abgelehnt', 'Abgelehnt'),
    ]

    KAUTIONS_TYP_CHOICES = [
        ('bank', 'Bankdepot (3 Monatsmieten)'),
        ('swisskaution', 'Swisskaution (Kautionsversicherung)'),
    ]

    ZIVILSTAND_CHOICES = [
        ('ledig', 'Ledig'),
        ('verheiratet', 'Verheiratet'),
        ('eingetragene_partnerschaft', 'Eingetragene Partnerschaft'),
        ('geschieden', 'Geschieden'),
        ('verwitwet', 'Verwitwet'),
        ('getrennt', 'Getrennt'),
    ]

    ERWERBSSTATUS_CHOICES = [
        ('angestellt', 'Angestellt'),
        ('selbstaendig', 'Selbständig'),
        ('student', 'Student'),
        ('keine_erwerbstaetigkeit', 'Keine Erwerbstätigkeit'),
        ('arbeitslos', 'Arbeitslos'),
        ('pensioniert', 'Pensioniert'),
        ('iv_bezueger', 'IV Bezüger'),
    ]

    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name="bewerbungen")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='neu')

    # --- Personalien Hauptmieter ---
    vorname = models.CharField(max_length=100)
    nachname = models.CharField(max_length=100)
    zivilstand = models.CharField(max_length=50, choices=ZIVILSTAND_CHOICES, default='ledig')
    geburtsdatum = models.DateField()
    geschlecht = models.CharField(max_length=20, choices=[('weiblich', 'Weiblich'), ('maennlich', 'Männlich')], default='weiblich')
    nationalitaet = models.CharField(max_length=100, default='Schweiz')
    heimatort = models.CharField(max_length=150, blank=True, null=True) # Für Schweizer relevant

    # --- Kontakt & Adresse ---
    mobilnummer = models.CharField(max_length=50)
    email = models.EmailField()
    adresse = models.CharField(max_length=200, blank=True, null=True)
    plz = models.CharField(max_length=20, blank=True, null=True)
    ort = models.CharField(max_length=100, blank=True, null=True)

    # --- Aktuelles Wohnverhältnis ---
    aktueller_vermieter = models.CharField(max_length=150, blank=True, null=True)
    kontaktperson_vermieter = models.CharField(max_length=150, blank=True, null=True)
    telefon_vermieter = models.CharField(max_length=50, blank=True, null=True)
    email_vermieter = models.EmailField(blank=True, null=True)

    # --- Beruf & Finanzen ---
    erwerbsstatus = models.CharField(max_length=50, choices=ERWERBSSTATUS_CHOICES, default='angestellt')
    beruf = models.CharField(max_length=150)
    einkommen_jahr = models.CharField(max_length=100, help_text="Einkommensspanne (Flatfox-Style)")
    arbeitgeber = models.CharField(max_length=150, blank=True, null=True)
    angestellt_seit = models.DateField(blank=True, null=True)
    kontaktperson_arbeitgeber = models.CharField(max_length=150, blank=True, null=True)
    telefon_arbeitgeber = models.CharField(max_length=50, blank=True, null=True)
    email_arbeitgeber = models.EmailField(blank=True, null=True)
    ist_unbefristet = models.BooleanField(default=True, help_text="Ist die Anstellung unbefristet?")

    # --- Betreibungen ---
    hat_betreibungen = models.BooleanField(default=False)

    # --- Allgemeine Informationen ---
    grund_fuer_wechsel = models.TextField(blank=True, null=True)
    anzahl_erwachsene = models.IntegerField(default=1)
    anzahl_kinder = models.IntegerField(default=0)

    haustiere = models.BooleanField(default=False)
    haustiere_details = models.CharField(max_length=200, blank=True, null=True)

    musikinstrumente = models.BooleanField(default=False)
    musikinstrumente_details = models.CharField(max_length=200, blank=True, null=True)

    interesse_parkplatz = models.BooleanField(default=False)
    gewuenschter_bezugstermin = models.DateField(blank=True, null=True)
    bemerkungen = models.TextField(blank=True, null=True)

    # --- Gewünschte Schilderbeschriftung ---
    schild_briefkasten = models.CharField(max_length=150, blank=True, null=True)
    schild_sonnerie = models.CharField(max_length=150, blank=True, null=True)
    wunsch_kautions_typ = models.CharField(max_length=20, choices=KAUTIONS_TYP_CHOICES, default='bank')

    # --- Dokumente (Schweizer Standard) ---
    digitaler_betreibungsauszug = models.BooleanField(default=False, help_text="Wird via API eingeholt")
    betreibungsauszug = models.FileField(upload_to="bewerbungen/betreibung/", blank=True, null=True)
    ausweiskopie = models.FileField(upload_to="bewerbungen/ausweis/", blank=True, null=True)
    lohnausweis = models.FileField(upload_to="bewerbungen/lohn/", blank=True, null=True)
    weitere_dokumente = models.FileField(upload_to="bewerbungen/weitere/", blank=True, null=True)

    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Bewerbung {self.vorname} {self.nachname} - {self.einheit.bezeichnung}"

    def save(self, *args, **kwargs):
        # Prüfen, ob wir die Datei scannen müssen (nur wenn sie neu hochgeladen wurde)
        scan_needed = False

        if self.betreibungsauszug:
            if not self.pk:
                scan_needed = True  # Neue Bewerbung
            else:
                alt = Mietbewerbung.objects.filter(pk=self.pk).first()
                if alt and alt.betreibungsauszug != self.betreibungsauszug:
                    scan_needed = True  # Datei wurde aktualisiert

        if scan_needed:
            try:
                ergebnis = scan_pdf_for_betreibungen(self.betreibungsauszug)
                if ergebnis is not None:
                    self.hat_betreibungen = ergebnis

                    # Automatisches Upgrade im Kanban-Board: "Bonität geprüft"
                    if self.status == 'neu':
                        self.status = 'geprueft'

            except Exception as e:
                print(f"Fehler beim Auto-Scan der Bewerbung: {e}")

        super().save(*args, **kwargs)