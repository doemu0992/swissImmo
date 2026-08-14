# portfolio/models.py
from django.db import models
from django.utils import timezone
from datetime import date
from decimal import Decimal
from core.utils import get_current_ref_zins, get_current_lik, get_smart_upload_path

class Liegenschaft(models.Model):
    eigentuemer = models.ForeignKey('crm.Eigentuemer', on_delete=models.CASCADE, related_name='liegenschaften', null=True, blank=True)
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

    # --- BEWERTUNG / RENDITE ---
    # Verkehrswert (Marktwert) ist der massgebliche Renditenenner; Anlagekosten
    # (Gestehungskosten) sind die Alternative. Versicherungswert eignet sich NICHT
    # als Nenner (Neuwert Gebäudehülle ≠ Marktwert inkl. Land).
    verkehrswert = models.DecimalField("Verkehrswert (Marktwert)", max_digits=12, decimal_places=2, null=True, blank=True)
    anlagekosten = models.DecimalField("Anlage-/Gestehungskosten", max_digits=12, decimal_places=2, null=True, blank=True)
    kaufpreis = models.DecimalField("Kaufpreis", max_digits=12, decimal_places=2, null=True, blank=True)
    kaufdatum = models.DateField("Kaufdatum", null=True, blank=True)

    # --- ENERGIE / GEBÄUDETECHNIK (GEAK) ---
    GEAK_KLASSEN = [(c, c) for c in ('A', 'B', 'C', 'D', 'E', 'F', 'G')]
    HEIZ_CHOICES = [
        ('waermepumpe', 'Wärmepumpe'), ('gas', 'Gasheizung'), ('oel', 'Ölheizung'),
        ('fernwaerme', 'Fernwärme'), ('holz', 'Holz / Pellets'), ('elektro', 'Elektro'),
        ('solar', 'Solar / thermisch'), ('andere', 'Andere'),
    ]
    WARMWASSER_CHOICES = [
        ('zentral', 'Zentral (Heizung)'), ('boiler', 'Elektroboiler'),
        ('waermepumpe', 'Wärmepumpenboiler'), ('solar', 'Solar'), ('andere', 'Andere'),
    ]
    energiebezugsflaeche_m2 = models.DecimalField("Energiebezugsfläche (m²)", max_digits=10, decimal_places=2, null=True, blank=True)
    geak_klasse = models.CharField("GEAK-Klasse (Gebäudehülle)", max_length=1, choices=GEAK_KLASSEN, blank=True, default='')
    geak_klasse_gesamt = models.CharField("GEAK-Klasse (Gesamtenergie)", max_length=1, choices=GEAK_KLASSEN, blank=True, default='')
    geak_datum = models.DateField("GEAK ausgestellt am", null=True, blank=True)
    heizsystem = models.CharField("Heizsystem", max_length=20, choices=HEIZ_CHOICES, blank=True, default='')
    energietraeger = models.CharField("Energieträger (Zusatz)", max_length=60, blank=True, default='')
    warmwasser = models.CharField("Warmwasser", max_length=20, choices=WARMWASSER_CHOICES, blank=True, default='')

    kanton = models.CharField("Kanton", max_length=2, blank=True)
    bank_name = models.CharField("Bankname", max_length=100, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)

    verteilschluessel_text = models.CharField("Verteilschlüssel Standard", max_length=200, default="nach Wohnfläche (m2)")
    # HKVO: verbrauchsabhängige Heizkostenabrechnung
    hkvo_aktiv = models.BooleanField("Verbrauchsabhängige Heizkosten (HKVO)", default=False)
    hkvo_grundkosten_prozent = models.IntegerField("Grundkosten-Anteil (%)", default=40)  # Rest = Verbrauchskosten

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


class Versicherung(models.Model):
    """Versicherungspolice einer Liegenschaft (Gebäude, Haftpflicht, Wasser, Glas …).
    Police-Register mit Summe/Prämie/Ablauf — löst die frühere Behelfslösung
    «Versicherung als Frist-Art» ab."""
    ART_CHOICES = [
        ('gebaeude', 'Gebäudeversicherung'),
        ('haftpflicht', 'Gebäude-Haftpflicht'),
        ('wasser', 'Wasser / Elementar'),
        ('glas', 'Glasbruch'),
        ('bauherren', 'Bauherren / Bau'),
        ('rechtsschutz', 'Rechtsschutz'),
        ('andere', 'Andere'),
    ]
    liegenschaft = models.ForeignKey('Liegenschaft', on_delete=models.CASCADE, related_name='versicherungen')
    art = models.CharField("Art", max_length=20, choices=ART_CHOICES, default='gebaeude')
    gesellschaft = models.CharField("Gesellschaft", max_length=120, blank=True, default='')
    policennummer = models.CharField("Policennummer", max_length=80, blank=True, default='')
    versicherungssumme = models.DecimalField("Versicherungssumme (CHF)", max_digits=12, decimal_places=2, null=True, blank=True)
    jahrespraemie = models.DecimalField("Jahresprämie (CHF)", max_digits=10, decimal_places=2, null=True, blank=True)
    ablauf_datum = models.DateField("Ablauf / nächste Fälligkeit", null=True, blank=True)
    notiz = models.CharField("Bemerkung", max_length=200, blank=True, default='')
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Versicherung"
        verbose_name_plural = "Versicherungen"
        ordering = ['art', 'gesellschaft']
        db_table = 'core_versicherung'

    def __str__(self):
        return f"{self.get_art_display()} · {self.gesellschaft}"


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
    # Schnelle Ausstattungs-Merkmale (Häkchen): Standardliste + eigene, als Liste
    # von Strings. Ergänzt das detaillierte Raumbuch (Assets) um einen Überblick.
    merkmale = models.JSONField("Ausstattungsmerkmale", default=list, blank=True)

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

    # Vermarktung / Nachmietersuche
    zur_ausschreibung = models.BooleanField("Zur Ausschreibung", default=False)
    verfuegbar_ab = models.DateField("Verfügbar ab", null=True, blank=True)
    ausschreibung_notiz = models.TextField("Vermarktungsnotiz", blank=True, default='')

    # --- Mietrechtliche Einordnung nach Objektart (Single Source of Truth) ---
    # 'wohnen'/'gewerbe' = geschützte Wohn-/Geschäftsräume (Art. 253a ff. OR:
    # amtliches Formular bei Vermieterkündigung, Erstreckung, Kaution max 3 Mte).
    # 'nebenobjekt' = gesondert vermietete Einstellplätze/übrige Sachen
    # (Art. 266e OR: 2 Wochen auf Ende einer Monatsperiode, kein amtl. Formular).
    MIETRECHT_KATEGORIE = {
        'whg': 'wohnen', 'stwe': 'wohnen', 'gew': 'gewerbe',
        'pp': 'nebenobjekt', 'gar': 'nebenobjekt', 'bas': 'nebenobjekt',
    }
    VERTRAG_TITEL = {
        'whg': 'Mietvertrag für Wohnräume',
        'stwe': 'Mietvertrag für Wohnräume',
        'gew': 'Mietvertrag für Geschäftsräume',
        'pp': 'Mietvertrag für einen Parkplatz',
        'gar': 'Mietvertrag für eine Garage',
        'bas': 'Mietvertrag für einen Bastel-/Hobbyraum',
    }

    # Einstellplätze (Art. 266e: 2 Wochen/Monatsende) vs. übrige unbewegliche
    # Sachen wie Bastelraum (Art. 266b: 3 Monate, ortsüblicher Termin).
    EINSTELLPLATZ_TYPEN = {'pp', 'gar'}

    @property
    def mietrecht_kategorie(self):
        return self.MIETRECHT_KATEGORIE.get(self.typ, 'wohnen')

    @property
    def ist_einstellplatz(self):
        return self.typ in self.EINSTELLPLATZ_TYPEN

    @property
    def vertrag_titel(self):
        return self.VERTRAG_TITEL.get(self.typ, 'Mietvertrag')

    def aktueller_sollmietzins(self, stichtag=None):
        """Die zum Stichtag (Default heute) gültige Sollmietzins-Zeile —
        jüngstes `gueltig_ab` <= Stichtag. None, wenn keine passt."""
        tag = stichtag or date.today()
        return (self.sollmietzinse.filter(gueltig_ab__lte=tag)
                .order_by('-gueltig_ab', '-id').first())

    def sync_aktuelle_miete(self):
        """Führt nettomiete_aktuell/nebenkosten_aktuell aus der aktuell gültigen
        Sollmietzins-Zeile nach. Ohne passende Zeile bleiben die Werte bestehen.
        Ändert bestehende Verträge NICHT (Art. 269d — amtliches Formular)."""
        row = self.aktueller_sollmietzins()
        if row is None:
            return
        felder = []
        if self.nettomiete_aktuell != row.netto_mietzins:
            self.nettomiete_aktuell = row.netto_mietzins; felder.append('nettomiete_aktuell')
        if self.nebenkosten_aktuell != row.nebenkosten:
            self.nebenkosten_aktuell = row.nebenkosten; felder.append('nebenkosten_aktuell')
        if felder:
            self.save(update_fields=felder)

    class Meta:
        verbose_name = "Einheit"
        verbose_name_plural = "Einheiten"
        db_table = 'core_einheit'

    def __str__(self):
        return f"{self.liegenschaft.strasse} - {self.bezeichnung}"


class Sollmietzins(models.Model):
    """Datierte Sollmietzins-Historie je Objekt (Komponenten): ab `gueltig_ab`
    gelten die hinterlegten Netto-/Nebenkostenwerte. Der aktuell gültige Wert
    wird auf die Einheit (nettomiete_aktuell/nebenkosten_aktuell) abgeleitet;
    NEUE Verträge übernehmen automatisch die zum Mietbeginn gültige Zeile.
    Bestehende Verträge bleiben unberührt (Mietzinsänderung nur über amtliches
    Formular, Art. 269d OR)."""
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='sollmietzinse')
    gueltig_ab = models.DateField("Gültig ab", default=date.today)
    netto_mietzins = models.DecimalField("Netto-Mietzins (Referenz, CHF)", max_digits=8, decimal_places=2, default=0.00)
    nebenkosten = models.DecimalField("Nebenkosten (CHF)", max_digits=6, decimal_places=2, default=0.00)
    # Rabatt/Erlass dieser Periode (Gratismonate) — mindert NUR die Verrechnung
    # (Sollstellung/Debitor), nicht die Referenz. Ein Gratismonat = rabatt_netto ==
    # netto_mietzins → zu zahlen 0, aber der volle Referenzertrag wird gebucht
    # (Ertragsminderung Konto 3090, Option B) → Mieterspiegel/Bilanz bleiben korrekt.
    rabatt_netto = models.DecimalField("Rabatt Netto (CHF)", max_digits=8, decimal_places=2, default=0.00)
    rabatt_nk = models.DecimalField("Rabatt NK (CHF)", max_digits=8, decimal_places=2, default=0.00)
    # Indexbasis, auf welcher dieser Sollmietzins beruht (für spätere Anpassungen,
    # Art. 269a/269d). Neue Verträge übernehmen sie als Vertragsbasis.
    basis_referenzzinssatz = models.DecimalField("Basis Referenzzinssatz (%)", max_digits=4, decimal_places=2, null=True, blank=True)
    basis_lik_punkte = models.DecimalField("Basis LIK (Punkte)", max_digits=6, decimal_places=1, null=True, blank=True)
    # Herkunft: gesetzt, wenn die Zeile aus einer amtlichen Mietzinsanpassung
    # (Art. 269d) entstand — dann wird sie beim Löschen der Anpassung mit entfernt
    # (CASCADE, nicht SET_NULL!). Sonst würde eine Anpassungs-Zeile beim Löschen
    # der Anpassung (bzw. via Vertrags-CASCADE) mit quelle_anpassung=NULL zurück-
    # bleiben und sich als MANUELLE Basiszeile tarnen — die Sollstellung würde dann
    # einen alten Anpassungsbetrag als Basismiete verrechnen (`_sollmietzins_zeile`
    # / `mietzins_zeitplan` selektieren Basiszeilen über quelle_anpassung__isnull).
    quelle_anpassung = models.ForeignKey('rentals.MietzinsAnpassung', on_delete=models.CASCADE,
                                         null=True, blank=True, related_name='sollmietzins_zeilen')
    notiz = models.CharField("Bemerkung", max_length=200, blank=True, default='')
    erstellt_am = models.DateTimeField("Erfasst am", auto_now_add=True, null=True)

    class Meta:
        verbose_name = "Sollmietzins"
        verbose_name_plural = "Sollmietzinse"
        ordering = ['-gueltig_ab', '-id']
        db_table = 'portfolio_sollmietzins'

    def __str__(self):
        return f"{self.einheit.bezeichnung} ab {self.gueltig_ab}: {self.netto_mietzins}+{self.nebenkosten}"

    @property
    def brutto(self):
        """Referenz-Brutto (vereinbarte Sollmiete)."""
        return (self.netto_mietzins or Decimal('0')) + (self.nebenkosten or Decimal('0'))

    @property
    def verrechnet_netto(self):
        return max(Decimal('0.00'), (self.netto_mietzins or Decimal('0')) - (self.rabatt_netto or Decimal('0')))

    @property
    def verrechnet_nk(self):
        return max(Decimal('0.00'), (self.nebenkosten or Decimal('0')) - (self.rabatt_nk or Decimal('0')))

    @property
    def verrechnet_brutto(self):
        return self.verrechnet_netto + self.verrechnet_nk

    @property
    def rabatt_gesamt(self):
        rn = min(self.rabatt_netto or Decimal('0'), self.netto_mietzins or Decimal('0'))
        rk = min(self.rabatt_nk or Decimal('0'), self.nebenkosten or Decimal('0'))
        return rn + rk

    @property
    def hat_rabatt(self):
        return (self.rabatt_netto or 0) > 0 or (self.rabatt_nk or 0) > 0

    @property
    def ist_voller_erlass(self):
        """Der Nettomietzins wird für diese Periode ganz erlassen (Gratismonat).

        Eine Zeile mit «−500.00» sagt für sich genommen nicht, ob jemand einen
        Rabatt ausgehandelt oder versehentlich «vollständig erlassen»
        angekreuzt hat. Die Unterscheidung gehört sichtbar an die Zeile."""
        netto = self.netto_mietzins or Decimal('0')
        return netto > 0 and (self.rabatt_netto or Decimal('0')) >= netto

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Nach jeder Änderung die abgeleiteten Aktuellwerte der Einheit nachführen.
        self.einheit.sync_aktuelle_miete()


class StaffelVorlage(models.Model):
    """Objektbezogene Staffelmiete-Vorlage (Art. 269c): geplante, datierte
    Netto-Stufen. Wird NICHT direkt verrechnet — sie belegt einen NEUEN
    (Gewerbe-)Vertrag im Wizard als Staffelmiete vor. Die verrechnungswirksamen
    Stufen entstehen erst am konkreten Vertrag (rentals.Staffelstufe)."""
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='staffelvorlagen')
    gueltig_ab = models.DateField("Gültig ab", default=date.today)
    netto_mietzins = models.DecimalField("Netto-Mietzins ab Stichtag (CHF)", max_digits=8, decimal_places=2, default=0.00)
    notiz = models.CharField("Bemerkung", max_length=200, blank=True, default='')
    erstellt_am = models.DateTimeField("Erfasst am", auto_now_add=True, null=True)

    class Meta:
        verbose_name = "Staffelmiete-Vorlage"
        verbose_name_plural = "Staffelmiete-Vorlagen"
        ordering = ['gueltig_ab', 'id']
        db_table = 'portfolio_staffelvorlage'

    def __str__(self):
        return f"{self.einheit.bezeichnung} ab {self.gueltig_ab}: {self.netto_mietzins}"


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
    # Objekt-Zähler (einheit) ODER allgemeiner Liegenschafts-Zähler
    # (z.B. Allgemeinstrom, Hauptwasser) — genau eine der beiden Beziehungen ist gesetzt.
    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='zaehler',
                                null=True, blank=True)
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE,
                                     related_name='allgemeine_zaehler', null=True, blank=True)
    typ = models.CharField(max_length=40)
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
    seriennummer = models.CharField("Seriennummer", max_length=100, blank=True, default='')
    # Kapazität / Leistung als freies Feld: z.B. "300 L" (Boiler), "24 kW" (Heizung)
    kapazitaet = models.CharField("Kapazität / Leistung", max_length=60, blank=True, default='')
    standort = models.CharField("Standort", max_length=100, blank=True, default='')
    installations_datum = models.DateField(null=True, blank=True)
    garantie_bis = models.DateField(null=True, blank=True)
    notiz = models.TextField("Notiz", blank=True, default='')

    class Meta:
        verbose_name = "Gerät"
        db_table = 'core_geraet'


class Ausstattung(models.Model):
    """Ausstattungselement eines Objekts (Raumbuch). Der Raum entsteht aus den
    Assets heraus — `raum` ist ein Attribut, das Raumbuch ist die Gruppierung.
    Grundlage für Abnahme (Zeitwert nach Lebensdauertabelle) und Reparaturhistorie."""
    ZUSTAND = [('neuwertig', 'Neuwertig'), ('gut', 'Gut'),
               ('gebraucht', 'Gebraucht'), ('defekt', 'Defekt')]

    einheit = models.ForeignKey(Einheit, on_delete=models.CASCADE, related_name='ausstattung')
    raum = models.CharField("Raum", max_length=60)
    kategorie = models.CharField("Kategorie", max_length=80)
    bezeichnung = models.CharField("Bezeichnung / Detail", max_length=120, blank=True, default='')
    marke = models.CharField(max_length=80, blank=True, default='')
    modell = models.CharField(max_length=80, blank=True, default='')
    material = models.CharField(max_length=80, blank=True, default='')
    menge = models.PositiveIntegerField("Menge", default=1)
    einbau_datum = models.DateField("Einbau / Anschaffung", null=True, blank=True)
    neuwert = models.DecimalField("Neuwert (CHF)", max_digits=10, decimal_places=2, null=True, blank=True)
    lebensdauer_jahre = models.PositiveIntegerField("Lebensdauer (Jahre, optional)", null=True, blank=True)
    zustand = models.CharField(max_length=12, choices=ZUSTAND, default='gut')
    garantie_bis = models.DateField(null=True, blank=True)
    notiz = models.TextField(blank=True, default='')
    foto = models.ImageField(upload_to=get_smart_upload_path, null=True, blank=True)
    sortierung = models.PositiveIntegerField(default=0)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ausstattung"
        verbose_name_plural = "Ausstattung"
        ordering = ['raum', 'sortierung', 'id']
        db_table = 'core_ausstattung'

    def __str__(self):
        return f"{self.raum} · {self.kategorie}"

    def effektive_lebensdauer(self):
        """Lebensdauer in Jahren: manueller Wert, sonst aus der Lebensdauertabelle
        (nach Kategorie), sonst None."""
        if self.lebensdauer_jahre:
            return self.lebensdauer_jahre
        return Lebensdauer.fuer_kategorie(self.kategorie)

    def zeitwert(self, stichtag=None):
        """Zeitwert (Restwert) nach paritätischer Lebensdauertabelle:
        Neuwert × Restnutzungsdauer / Lebensdauer. None, wenn Daten fehlen."""
        from decimal import Decimal
        ld = self.effektive_lebensdauer()
        if not (self.neuwert and self.einbau_datum and ld):
            return None
        tag = stichtag or date.today()
        alter = max(0.0, (tag - self.einbau_datum).days / 365.25)
        rest = max(0.0, float(ld) - alter)
        return (self.neuwert * Decimal(str(rest / float(ld)))).quantize(Decimal('0.01'))

    def rest_jahre(self, stichtag=None):
        """Verbleibende Nutzungsdauer in Jahren (kann negativ = überfällig).
        None, wenn Einbaudatum oder Lebensdauer fehlen."""
        ld = self.effektive_lebensdauer()
        if not (self.einbau_datum and ld):
            return None
        tag = stichtag or date.today()
        alter = (tag - self.einbau_datum).days / 365.25
        return round(float(ld) - alter, 1)

    def ersatz_status(self, stichtag=None):
        """Ersatzplanung: 'faellig' (Lebensdauer erreicht), 'bald' (≤ 2 J),
        'ok' oder 'unbekannt' (keine Datenbasis)."""
        rest = self.rest_jahre(stichtag)
        if rest is None:
            return 'unbekannt'
        if rest <= 0:
            return 'faellig'
        if rest <= 2:
            return 'bald'
        return 'ok'

    def reparatur_kosten_total(self):
        """Summe der effektiven (sonst geschätzten) Reparaturkosten aller mit
        diesem Element verknüpften Schäden — Basis für Lebenszykluskosten."""
        from decimal import Decimal
        total = Decimal('0.00')
        for s in self.schaeden.all():
            for a in s.handwerker_auftraege.all():
                total += (a.kosten_effektiv or a.kosten_geschaetzt or Decimal('0.00'))
        return total

    def lebenszyklus_kosten(self):
        """Neuwert + bisher aufgelaufene Reparaturkosten."""
        from decimal import Decimal
        return (self.neuwert or Decimal('0.00')) + self.reparatur_kosten_total()


class Lebensdauer(models.Model):
    """Paritätische Lebensdauertabelle (Mieterverband/HEV): erwartete Nutzungs-
    dauer je Ausstattungs-Kategorie. Editierbar; Standardwerte werden geseedet."""
    kategorie = models.CharField(max_length=80, unique=True)
    jahre = models.PositiveIntegerField("Lebensdauer (Jahre)")
    bemerkung = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        verbose_name = "Lebensdauer"
        verbose_name_plural = "Lebensdauertabelle"
        ordering = ['kategorie']
        db_table = 'core_lebensdauer'

    def __str__(self):
        return f"{self.kategorie}: {self.jahre} J"

    @classmethod
    def fuer_kategorie(cls, kategorie):
        row = cls.objects.filter(kategorie__iexact=(kategorie or '').strip()).first()
        return row.jahre if row else None


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


class Wartungsfrist(models.Model):
    """Wiederkehrende Wartungs-/Service-/Versicherungsfrist einer Liegenschaft.
    Speist automatisch Pendenzen (generate_auto_pendenzen)."""
    ART_CHOICES = [
        ('wartung', 'Wartung / Service'),
        ('versicherung', 'Versicherung'),
        ('kontrolle', 'Kontrolle / Prüfung'),
        ('abo', 'Abonnement / Vertrag'),
        ('sonstiges', 'Sonstiges'),
    ]
    liegenschaft = models.ForeignKey(Liegenschaft, on_delete=models.CASCADE, related_name='wartungsfristen')
    art = models.CharField("Art", max_length=20, choices=ART_CHOICES, default='wartung')
    bezeichnung = models.CharField("Bezeichnung", max_length=200)
    anbieter = models.CharField("Anbieter / Dienstleister", max_length=200, blank=True, default='')
    naechste_faelligkeit = models.DateField("Nächste Fälligkeit")
    intervall_monate = models.PositiveSmallIntegerField("Intervall (Monate)", default=12)
    aktiv = models.BooleanField("Aktiv", default=True)
    notiz = models.TextField("Notiz", blank=True, default='')
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Wartungsfrist"
        verbose_name_plural = "Wartungsfristen"
        ordering = ['naechste_faelligkeit']
        db_table = 'portfolio_wartungsfrist'

    def __str__(self):
        return f"{self.get_art_display()}: {self.bezeichnung}"

class EinheitFoto(models.Model):
    """Fotos eines Mietobjekts für Exposé, Portal-Feed und Vermarktung."""
    einheit = models.ForeignKey('Einheit', on_delete=models.CASCADE, related_name='fotos')
    bild = models.ImageField(upload_to=get_smart_upload_path)
    beschreibung = models.CharField(max_length=200, blank=True, default='')
    reihenfolge = models.PositiveIntegerField(default=0)
    hochgeladen_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Objekt-Foto"
        verbose_name_plural = "Objekt-Fotos"
        ordering = ['reihenfolge', 'hochgeladen_am']
        db_table = 'core_einheitfoto'

    def __str__(self):
        return f"Foto zu {self.einheit_id}"
