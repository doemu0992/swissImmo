# portfolio/models.py
from django.db import models
from django.utils import timezone
from datetime import date
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

    grundstuecksflaeche_m2 = models.DecimalField("Grundstücksfläche (m²)", max_digits=10, decimal_places=2, null=True, blank=True)
    gebaeudevolumen_m3 = models.DecimalField("Gebäudevolumen (m³)", max_digits=10, decimal_places=2, null=True, blank=True)

    kanton = models.CharField("Kanton", max_length=2, blank=True)
    bank_name = models.CharField("Bankname", max_length=100, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)

    verteilschluessel_text = models.CharField("Verteilschlüssel Standard", max_length=200, default="nach Wohnfläche (m2)")

    # --- HAUSWARTUNG & NOTFALL ---
    hauswart_name = models.CharField("Hauswart", max_length=100, blank=True, default='')
    hauswart_telefon = models.CharField("Hauswart Telefon", max_length=50, blank=True, default='')
    sanitaer_name = models.CharField("Notfall Sanitär", max_length=100, blank=True, default='')
    sanitaer_telefon = models.CharField("Sanitär Telefon", max_length=50, blank=True, default='')
    elektriker_name = models.CharField("Notfall Elektriker", max_length=100, blank=True, default='')
    elektriker_telefon = models.CharField("Elektriker Telefon", max_length=50, blank=True, default='')

    class Meta:
        verbose_name = "Liegenschaft"
        verbose_name_plural = "Liegenschaften"
        db_table = 'core_liegenschaft'

    def __str__(self):
        return f"{self.strasse}, {self.ort}"


class Einheit(models.Model):
    TYP_CHOICES = [
        ('whg', 'Wohnung'),
        ('gew', 'Gewerbe'),
        ('stwe', 'STWEG-Einheit'),
        ('pp', 'Parkplatz'),
        ('gar', 'Garage'),
        ('bas', 'Bastelraum')
    ]
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, related_name='einheiten')
    bezeichnung = models.CharField("Objektbezeichnung", max_length=50)
    typ = models.CharField("Typ", max_length=10, choices=TYP_CHOICES, default='whg')
    etage = models.CharField("Etage", max_length=50, blank=True)

    gehoert_zu = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='nebenobjekte', verbose_name="Gehört zu Hauptobjekt")

    keller = models.CharField("Kellerabteil", max_length=50, blank=True, default='')
    estrich = models.CharField("Estrich", max_length=50, blank=True, default='')

    ewid = models.CharField("EWID", max_length=20, blank=True, null=True)
    oto_dose = models.CharField("OTO-Dose (Glasfaser)", max_length=50, blank=True, default='')

    bodenbelag = models.CharField("Bodenbelag (Wohnraum)", max_length=100, blank=True, default='')
    bodenbelag_nassraum = models.CharField("Bodenbelag (Nassraum)", max_length=100, blank=True, default='')
    letzte_renovation = models.IntegerField("Letzte Renovation (Jahr)", null=True, blank=True)

    zimmer = models.DecimalField("Anz. Zimmer", max_digits=3, decimal_places=1, null=True, blank=True)
    flaeche_m2 = models.DecimalField("Fläche (m²)", max_digits=7, decimal_places=2, null=True, blank=True)
    volumen_m3 = models.DecimalField("Volumen (m³)", max_digits=7, decimal_places=2, null=True, blank=True)
    wertquote = models.DecimalField("Wertquote", max_digits=7, decimal_places=2, default=10.00)

    # Veraltet durch neues Modell Verteilschluessel
    heizkosten_verteilschluessel = models.CharField("HK-Schlüssel", max_length=50, choices=[('m2', 'Fläche (m2)'), ('m3', 'Volumen (m3)'), ('pauschal', 'Pauschal')], default='m2')

    notizen = models.TextField("Interne Notizen", blank=True, default='')

    # 🔥 NEU: Standard Kaution
    standard_kautionsmonate = models.IntegerField("Standard Kaution (Monate)", default=3)

    nettomiete_aktuell = models.DecimalField("Soll-Miete", max_digits=8, decimal_places=2, default=0.00)
    nebenkosten_aktuell = models.DecimalField("Soll-Nebenkosten", max_digits=6, decimal_places=2, default=0.00)
    nk_abrechnungsart = models.CharField("NK-Art", max_length=20, default='akonto', choices=[('akonto', 'Akonto'), ('pauschal', 'Pauschal')])
    ref_zinssatz = models.DecimalField("Basis Ref.Zins", max_digits=4, decimal_places=2, default=get_current_ref_zins)
    lik_punkte = models.DecimalField("Basis LIK", max_digits=6, decimal_places=1, default=get_current_lik)

    class Meta:
        verbose_name = "Einheit"
        verbose_name_plural = "Einheiten"
        db_table = 'core_einheit'

    def __str__(self):
        return f"{self.liegenschaft.strasse} - {self.bezeichnung}"


class Verteilschluessel(models.Model):
    """Individuelle Verteilschlüssel pro Einheit."""
    KOSTENART_CHOICES = [
        ('heizung', 'Heizkosten'),
        ('wasser', 'Wasser / Abwasser'),
        ('lift', 'Liftkosten'),
        ('allgemeinstrom', 'Allgemeinstrom'),
        ('hauswartung', 'Hauswartung / Reinigung'),
        ('kabel_tv', 'Kabel-TV / Antenne'),
        ('garten', 'Gartenpflege'),
        ('verwaltung', 'Verwaltungshonorar'),
        ('versicherung', 'Versicherungen'),
        ('sonstiges', 'Sonstige Nebenkosten'),
    ]

    TYP_CHOICES = [
        ('m2', 'Fläche (m²)'),
        ('m3', 'Volumen (m³)'),
        ('prozent', 'Prozent (%)'),
        ('anteil', 'Anteile (z.B. Wertquote)'),
        ('pauschal', 'Pauschal (CHF)'),
        ('zimmer', 'Zimmer'),
        ('einheit', 'Pro Einheit')
    ]

    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='verteilschluessel')
    kostenart = models.CharField("Kostenart", max_length=50, choices=KOSTENART_CHOICES)
    typ = models.CharField("Berechnungstyp", max_length=20, choices=TYP_CHOICES, default='m2')
    wert = models.DecimalField("Wert", max_digits=12, decimal_places=4, default=0.00)
    gueltig_ab = models.DateField("Gültig ab", default=date.today)
    gueltig_bis = models.DateField("Gültig bis", null=True, blank=True)
    notizen = models.CharField("Bemerkung", max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "Verteilschlüssel"
        verbose_name_plural = "Verteilschlüssel"
        db_table = 'portfolio_verteilschluessel'
        ordering = ['kostenart', '-gueltig_ab']

    def __str__(self):
        return f"{self.einheit.bezeichnung} - {self.get_kostenart_display()} ({self.wert})"


class LiegenschaftVerteilschluessel(models.Model):
    """Standard-Regeln für eine Liegenschaft (Vererbung)."""
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, related_name='standard_schluessel')
    kostenart = models.CharField("Kostenart", max_length=50, choices=Verteilschluessel.KOSTENART_CHOICES)
    typ = models.CharField("Berechnung nach", max_length=20, choices=Verteilschluessel.TYP_CHOICES, default='m2')
    wert = models.DecimalField("Wert", max_digits=12, decimal_places=4, default=0.00)
    gueltig_ab = models.DateField("Gültig ab", default=date.today)
    gueltig_bis = models.DateField("Gültig bis", null=True, blank=True)
    notizen = models.CharField("Bemerkung", max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "Liegenschafts-Standard (Verteilschlüssel)"
        db_table = 'portfolio_liegenschaft_verteilschluessel'
        ordering = ['kostenart']

    def __str__(self):
        return f"{self.liegenschaft.strasse} - Standard {self.get_kostenart_display()}"


class Dokument(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, null=True, blank=True, related_name='dokumente')
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, null=True, blank=True, related_name='dokumente')
    titel = models.CharField(max_length=200)
    kategorie = models.CharField(max_length=50, default='Allgemein')
    datei = models.FileField(upload_to=get_smart_upload_path)
    datum = models.DateField(default=timezone.now)

    class Meta:
        verbose_name = "Dokument"
        db_table = 'portfolio_dokument'


class Unterhalt(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE)
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, null=True, blank=True, related_name='unterhalte')
    titel = models.CharField(max_length=200)
    beschreibung = models.TextField(blank=True, default='')
    datum = models.DateField(default=timezone.now)
    kosten = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    beleg = models.FileField(upload_to=get_smart_upload_path, blank=True, null=True)

    class Meta:
        verbose_name = "Unterhalt"
        db_table = 'core_unterhalt'


class Zaehler(models.Model):
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='zaehler')
    typ = models.CharField(max_length=20)
    zaehler_nummer = models.CharField(max_length=50)
    standort = models.CharField("Standort", max_length=100, blank=True)
    aktueller_stand = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    class Meta:
        verbose_name = "Zähler"
        db_table = 'core_zaehler'


class ZaehlerStand(models.Model):
    zaehler = models.ForeignKey(Zaehler, on_delete=models.CASCADE, related_name='staende')
    datum = models.DateField(default=timezone.now)
    wert = models.DecimalField("Zählerstand", max_digits=12, decimal_places=3)

    class Meta:
        verbose_name = "Zählerstand"
        db_table = 'core_zaehlerstand'


class Geraet(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, related_name='allgemeine_geraete', null=True, blank=True)
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='geraete', null=True, blank=True)
    kategorie = models.CharField(max_length=100, default='sonstiges')
    sonstiges_bezeichnung = models.CharField(max_length=100, blank=True, default='')
    marke = models.CharField(max_length=100, blank=True)
    modell = models.CharField(max_length=100, blank=True)
    installations_datum = models.DateField(null=True, blank=True)
    garantie_bis = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Gerät"
        db_table = 'core_geraet'


class Schluessel(models.Model):
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE)
    einheit = models.ForeignKey(Einheit, on_delete=models.SET_NULL, null=True, blank=True, related_name='schluessel_liste')
    typ = models.CharField(max_length=50, default='Wohnung')
    schluessel_nummer = models.CharField(max_length=50)
    anzahl = models.IntegerField(default=1)

    class Meta:
        verbose_name = "Schlüssel"
        db_table = 'core_schluessel'


class SchluesselAusgabe(models.Model):
    schluessel = models.ForeignKey(Schluessel, on_delete=models.CASCADE, related_name='ausgaben')
    mieter = models.ForeignKey('crm.Mieter', on_delete=models.SET_NULL, null=True, blank=True)
    handwerker = models.ForeignKey('crm.Handwerker', on_delete=models.SET_NULL, null=True, blank=True)
    ausgegeben_am = models.DateField(default=timezone.now)
    rueckgabe_am = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Schlüsselausgabe"
        db_table = 'core_schluesselausgabe'