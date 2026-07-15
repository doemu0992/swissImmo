# rentals/models.py
from django.db import models
from django.utils import timezone
from decimal import Decimal
from core.utils import get_current_ref_zins, get_current_lik, get_smart_upload_path

class Mietvertrag(models.Model):
    STATUS_CHOICES = [('offen', 'Offen'), ('gesendet', 'Versendet'), ('unterzeichnet', 'Unterzeichnet')]

    VERTRAG_STATUS = [
        ('entwurf', 'Entwurf'),
        ('aktiv', 'Aktiv'),
        ('gekuendigt', 'Gekündigt'),
        ('archiviert', 'Archiviert')
    ]

    NK_TYP_CHOICES = [
        ('akonto', 'Akonto (Vorschuss mit Abrechnung)'),
        ('pauschal', 'Pauschal (fixer Betrag ohne Abrechnung)'),
        ('inbegriffen', 'Inbegriffen (im Nettomietzins enthalten)'),
        ('direkt', 'Direkt (Mieter zahlt direkt an Werke)'),
    ]

    VERTEIL_CHOICES = [
        ('m2', 'Fläche (m²)'),
        ('m3', 'Volumen (m³)'),
        ('quote', 'Wertquote'),
        ('einheit', 'Pro Einheit / Pauschal'),
        ('individuell', 'Individuelle Zähler (VHKA)'),
    ]

    ZAHLUNGSRHYTHMUS_CHOICES = [
        ('monatlich', 'monatlich'),
        ('vierteljahr', 'vierteljährlich'),
        ('halbjahr', 'halbjährlich'),
        ('jahr', 'jährlich'),
    ]

    mieter = models.ForeignKey('crm.Mieter', on_delete=models.CASCADE, related_name='vertraege')
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='vertraege')
    nebenobjekte = models.ManyToManyField('portfolio.Einheit', blank=True, related_name='als_nebenobjekt_in_vertraegen')

    # --- VERTRAGS-STATUS ---
    status = models.CharField("Vertragsstatus", max_length=20, choices=VERTRAG_STATUS, default='entwurf')
    aktiv = models.BooleanField(default=True)
    sign_status = models.CharField("Signatur-Status", max_length=20, choices=STATUS_CHOICES, default='offen')
    unterzeichnet_am = models.DateTimeField("Unterzeichnet am (Rücklauf)", null=True, blank=True)

    # --- FRISTEN & TERMINE ---
    beginn = models.DateField()
    ende = models.DateField(null=True, blank=True)
    erstmals_kuendbar_auf = models.DateField("Erstmals kündbar auf", null=True, blank=True) # 🔥 NEU
    kuendigungsfrist_monate = models.IntegerField("Kündigungsfrist (Monate)", default=3)
    kuendigungstermine = models.CharField("Kündigungstermine", max_length=100, default="Ende jedes Monats ausser Dezember", blank=True)

    # --- OBJEKT & NUTZUNG (🔥 NEU) ---
    familienwohnung = models.BooleanField("Familienwohnung", default=False)
    mitmieter_name = models.CharField("Ehegatte / Mitmieter", max_length=150, blank=True, default='') # 🔥 NEU
    mitmieter = models.ForeignKey('crm.Mieter', on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='vertraege_als_mitmieter', verbose_name="Zweiter Mieter")  # 🔥 NEU (volle Adresse)
    anzahl_personen = models.IntegerField("Anzahl Personen", default=1)
    besondere_vereinbarungen = models.TextField("Besondere Vereinbarungen", blank=True, default='')
    mitbenutzung = models.TextField("Zur Mitbenützung", blank=True, default='')      # 🔥 NEU (z.B. Waschküche, Estrich)
    nebenraeume = models.TextField("Nebenräume", blank=True, default='')              # 🔥 NEU (z.B. Keller, Reduit)

    # --- FINANZEN ---
    netto_mietzins = models.DecimalField(max_digits=8, decimal_places=2)
    nebenkosten = models.DecimalField(max_digits=6, decimal_places=2)
    nk_abrechnungsart = models.CharField("NK-Abrechnungsart", max_length=20, choices=NK_TYP_CHOICES, default='akonto')
    verteilschluessel = models.CharField("Verteilschlüssel", max_length=20, choices=VERTEIL_CHOICES, default='m2')
    ausgeschlossene_kosten = models.TextField("Ausgeschlossene Kosten", blank=True, help_text="Welche Kosten zahlt dieser Mieter NICHT?")
    zahlungsrhythmus = models.CharField("Zahlungsrhythmus", max_length=20, choices=ZAHLUNGSRHYTHMUS_CHOICES, default='monatlich') # 🔥 NEU
    mwst_pflichtig = models.BooleanField("MWST-pflichtig", default=False)             # 🔥 NEU (v.a. Gewerbe)
    mwst_satz = models.DecimalField("MWST-Satz (%)", max_digits=4, decimal_places=1, default=Decimal('8.1'))  # 🔥 NEU (Option Art. 22 MWSTG)

    # --- MIETZINSMODELL (v.a. Geschäftsraum: Index Art. 269b / Staffel Art. 269c) ---
    MIETZINS_MODELL_CHOICES = [
        ('fest', 'Fester Mietzins'),
        ('index', 'Indexmiete (LIK, Art. 269b)'),
        ('staffel', 'Staffelmiete (Art. 269c)'),
    ]
    mietzins_modell = models.CharField("Mietzinsmodell", max_length=10,
                                       choices=MIETZINS_MODELL_CHOICES, default='fest')
    zweckbestimmung = models.CharField("Nutzungszweck (Geschäftsraum)", max_length=200,
                                       blank=True, default='')
    # Indexmiete: Anteil der LIK-Weitergabe (Geschäftsraum i.d.R. 100 %) + Mindestintervall
    index_weitergabe_prozent = models.DecimalField("Index-Weitergabe (%)", max_digits=5,
                                                   decimal_places=1, default=Decimal('100.0'))
    index_intervall_monate = models.IntegerField("Index-Mindestintervall (Monate)", default=12)
    index_letzte_anpassung = models.DateField("Letzte Indexanpassung", null=True, blank=True)

    # --- KAUTION (Art. 257e OR: Sperrkonto auf Mietername ODER Kautionsversicherung) ---
    KAUTIONSART_CHOICES = [
        ('sperrkonto', 'Sperrkonto (Bankdepot)'),
        ('versicherung', 'Kautionsversicherung'),
    ]
    kautions_art = models.CharField("Kautionsart", max_length=20, choices=KAUTIONSART_CHOICES,
                                    default='sperrkonto', blank=True)
    kautions_betrag = models.DecimalField("Kautionsbetrag", max_digits=8, decimal_places=2, blank=True, null=True)
    kautions_konto = models.CharField("Kautionskonto (IBAN)", max_length=34, blank=True, default='')
    kautions_einbezahlt_am = models.DateField("Kaution einbezahlt am", null=True, blank=True)
    # --- Kautionsversicherung (Alternative zum Sperrkonto) ---
    kautions_versicherer = models.CharField("Versicherer / Anbieter", max_length=120, blank=True, default='')
    kautions_policennummer = models.CharField("Policennummer", max_length=60, blank=True, default='')
    kautions_zertifikat = models.FileField("Zertifikat / Police", upload_to='kautions_zertifikate/', null=True, blank=True)
    kautions_zurueckbezahlt_am = models.DateField("Kaution zurückbezahlt am", null=True, blank=True)          # 🔥 NEU
    kautions_rueckzahlung_betrag = models.DecimalField("Rückzahlung an Mieter", max_digits=8, decimal_places=2, null=True, blank=True)  # 🔥 NEU
    kautions_abzug_betrag = models.DecimalField("Einbehalt / Abzug", max_digits=8, decimal_places=2, null=True, blank=True)  # 🔥 NEU
    kautions_abzug_grund = models.TextField("Grund des Einbehalts", blank=True, default='')                    # 🔥 NEU

    # --- BASES & VORBEHALTE (🔥 ERWEITERT) ---
    basis_referenzzinssatz = models.DecimalField(max_digits=4, decimal_places=2, default=get_current_ref_zins)
    basis_lik_punkte = models.DecimalField(max_digits=6, decimal_places=1, default=get_current_lik)
    # Stand-Monat, aus dem basis_lik_punkte abgelesen wurde (für amtliches Formular)
    basis_lik_stand = models.DateField("LIK Basis Stand-Monat", null=True, blank=True)
    kostensteigerung_datum = models.DateField("Kostensteigerung ausgeglichen bis", null=True, blank=True)
    mietzinsreserve_betrag = models.DecimalField("Reserve Betrag (CHF)", max_digits=8, decimal_places=2, null=True, blank=True)
    mietzinsreserve_prozent = models.DecimalField("Reserve Prozent (%)", max_digits=5, decimal_places=2, null=True, blank=True)
    weitere_vorbehalte = models.TextField("Weitere Vorbehalte", blank=True, default='')

    pdf_datei = models.FileField(upload_to='roh_vertraege/', blank=True, null=True)

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

    @property
    def brutto_mietzins(self):
        return (self.netto_mietzins or Decimal('0.00')) + (self.nebenkosten or Decimal('0.00'))

    # --- Mietrechtliche Einordnung (aus der Objektart der Haupteinheit) ---
    @property
    def mietrecht_kategorie(self):
        """'wohnen' | 'gewerbe' | 'nebenobjekt' — bestimmt Titel, Formularpflicht,
        Erstreckung und Kautionsobergrenze."""
        return self.einheit.mietrecht_kategorie if self.einheit_id else 'wohnen'

    @property
    def ist_geschuetzt(self):
        """Wohn-/Geschäftsräume: amtliches Kündigungsformular des Vermieters +
        Erstreckung + Kaution max 3 Monatsmieten. Nebenobjekte nicht."""
        return self.mietrecht_kategorie in ('wohnen', 'gewerbe')

    @property
    def vertrag_titel(self):
        """Dynamischer Vertragstitel je Objektart (Wohnräume/Geschäftsräume/
        Parkplatz/Garage/Bastelraum)."""
        return self.einheit.vertrag_titel if self.einheit_id else 'Mietvertrag'

    @property
    def kaution_max_monate(self):
        """Gesetzliche Kautionsobergrenze: 3 Monatsmieten bei Wohnräumen
        (Art. 257e OR), frei bei Geschäftsräumen/Nebenobjekten."""
        return 3 if self.mietrecht_kategorie == 'wohnen' else None

    @property
    def kuendigungsfrist_anzeige(self):
        """Anzeigetext der Kündigungsfrist. Bei gesondert vermieteten
        Einstellplätzen gilt von Gesetzes wegen mindestens die 2-Wochen-Frist
        (Art. 266e OR); die Parteien können aber eine LÄNGERE Frist auf Ende eines
        Monats vereinbaren. `kuendigungsfrist_monate` <= 0 = gesetzliche 2 Wochen,
        > 0 = vereinbarte Monatsfrist."""
        if self.einheit_id and self.einheit.ist_einstellplatz:
            m = self.kuendigungsfrist_monate or 0
            if m <= 0:
                return "2 Wochen auf Ende einer Monatsperiode (Art. 266e OR)"
            return f"{m} Monat{'e' if m != 1 else ''} auf Ende eines Monats"
        return f"{self.kuendigungsfrist_monate} Monate"

    @property
    def nebenobjekt_kuendigung_note(self):
        """Korrekte Kündigungs-Rechtsgrundlage für gesondert vermietete
        Nebenobjekte: Einstellplatz (Art. 266e, 2 Wochen/Monatsende) vs.
        übrige unbewegliche Sache wie Bastelraum (Art. 266b, 3 Monate)."""
        if not self.einheit_id or self.mietrecht_kategorie != 'nebenobjekt':
            return ''
        gemein = ("Als gesondert vermietetes Objekt (kein Wohn- oder Geschäftsraum) "
                  "bedarf die Kündigung des Vermieters keines amtlichen Formulars, "
                  "und es besteht kein Erstreckungsanspruch. ")
        if self.einheit.ist_einstellplatz:
            return gemein + ("Für gesondert vermietete Einstellplätze gilt von "
                             "Gesetzes wegen eine Frist von zwei Wochen auf Ende einer "
                             "einmonatigen Mietdauer (Art. 266e OR), soweit oben nichts "
                             "anderes vereinbart ist.")
        return gemein + ("Es gilt die gesetzliche Frist von drei Monaten auf einen "
                         "ortsüblichen Termin bzw. das Ende einer dreimonatigen Mietdauer "
                         "(Art. 266b OR), soweit oben nichts anderes vereinbart ist.")

    def effektiver_netto_mietzins(self, fuer_datum=None):
        """Netto-Mietzins, der an einem bestimmten Datum gilt — verrechnungswirksam.

        - Staffelmiete: die zum Stichtag jüngste erreichte Staffelstufe (vorab
          vereinbart → automatisch).
        - Fest/Index: die jüngste am Stichtag WIRKSAME amtliche Mietzinsanpassung
          (Referenzzins-/Index-/Teuerungsanpassung, Art. 269d) ab `wirksam_ab` —
          so folgt die Sollstellung automatisch der angekündigten Anpassung, ohne
          den Basiswert zu mutieren. Ohne Anpassung/Stufe = Basis-Nettomietzins."""
        from datetime import date as _d
        stichtag = fuer_datum or _d.today()
        basis = self.netto_mietzins or Decimal('0.00')
        if not self.pk:
            return basis
        if self.mietzins_modell == 'staffel':
            stufe = (self.staffelstufen.filter(ab_datum__lte=stichtag)
                     .order_by('-ab_datum').first())
            return stufe.netto_mietzins if stufe else basis
        anp = (self.anpassungen.filter(wirksam_ab__lte=stichtag)
               .order_by('-wirksam_ab', '-id').first())
        return anp.neuer_netto_mietzins if anp else basis

    def effektive_basis(self, fuer_datum=None):
        """(Referenzzins, LIK), auf denen der aktuell verrechnete Mietzins beruht:
        aus der jüngsten am Stichtag wirksamen Anpassung, sonst die Vertragsbasis.
        Damit rechnet das Erhöhungs-/Senkungspotenzial nach einer Anpassung nicht
        mehr auf der veralteten Ursprungsbasis weiter."""
        from datetime import date as _d
        stichtag = fuer_datum or _d.today()
        if self.pk:
            anp = (self.anpassungen.filter(wirksam_ab__lte=stichtag)
                   .order_by('-wirksam_ab', '-id').first())
            if anp:
                return (anp.neuer_referenzzinssatz or self.basis_referenzzinssatz,
                        anp.neuer_lik_index or self.basis_lik_punkte)
        return (self.basis_referenzzinssatz, self.basis_lik_punkte)

    @property
    def kautions_status(self):
        """offen (keine) / erwartet / einbezahlt / zurueckbezahlt — für das Kautions-Register.
        Bei Versicherung entspricht 'einbezahlt' = Zertifikat hinterlegt/Police aktiv."""
        if not self.kautions_betrag or self.kautions_betrag <= 0:
            return 'keine'
        if self.kautions_zurueckbezahlt_am:
            return 'zurueckbezahlt'
        if self.kautions_einbezahlt_am:
            return 'einbezahlt'
        return 'erwartet'

    @property
    def ist_kautionsversicherung(self):
        return self.kautions_art == 'versicherung'

    @property
    def kautions_status_label(self):
        """Menschlicher, art-abhängiger Status-Text."""
        st = self.kautions_status
        vers = self.ist_kautionsversicherung
        return {
            'keine': 'Keine Kaution',
            'erwartet': 'Zertifikat ausstehend' if vers else 'Einzahlung erwartet',
            'einbezahlt': 'Police aktiv' if vers else 'Einbezahlt',
            'zurueckbezahlt': 'Police aufgelöst' if vers else 'Zurückbezahlt',
        }.get(st, st)

    @property
    def mietzinspotenzial(self):
        try:
            from crm.models import Verwaltung
            vw = Verwaltung.objects.first()
            if not vw: return 'neutral'
            curr_zins = vw.aktueller_referenzzinssatz
            curr_lik = vw.aktueller_lik_punkte
            # Auf der EFFEKTIVEN Basis rechnen (jüngste wirksame Anpassung) —
            # sonst zeigt der Mietzins-View nach einer Anpassung weiterhin
            # "Erhöhung möglich" auf der veralteten Ursprungsbasis.
            basis_zins, basis_lik = self.effektive_basis()
            if curr_zins < basis_zins: return 'decrease'
            if curr_zins > basis_zins: return 'increase'
            if curr_lik > (basis_lik + Decimal('1.5')): return 'increase'
            return 'neutral'
        except Exception:
            return 'neutral'

    def save(self, *args, **kwargs):
        # Rücklauf-Zeitstempel setzen, sobald der Vertrag als unterzeichnet gilt
        # (nur beim erstmaligen Übergang → nicht bei jedem weiteren Save).
        if self.sign_status == 'unterzeichnet' and self.unterzeichnet_am is None:
            from django.utils import timezone
            self.unterzeichnet_am = timezone.now()
        super().save(*args, **kwargs)

        # Unterzeichneten Vertrag zentral ablegen → erscheint überall (Portal,
        # Person, Objekt/Liegenschaft). Jeder Rücklauf wird als NEUES, mit
        # Zeitstempel versehenes Dokument abgelegt (bestehende nicht überschrieben).
        if self.sign_status == 'unterzeichnet' and self.pdf_datei:
            try:
                from core.services.ablage import ablage_signierter_vertrag
                ablage_signierter_vertrag(self)
            except Exception:
                pass

class Staffelstufe(models.Model):
    """Eine vereinbarte Staffelmietstufe (Art. 269c OR): ab `ab_datum` gilt
    `netto_mietzins`. Vorab im Vertrag vereinbart → im Mietenlauf automatisch
    (keine erneute Ankündigung nötig)."""
    vertrag = models.ForeignKey(Mietvertrag, on_delete=models.CASCADE, related_name='staffelstufen')
    ab_datum = models.DateField("Gültig ab")
    netto_mietzins = models.DecimalField("Netto-Mietzins ab Stichtag", max_digits=8, decimal_places=2)

    class Meta:
        db_table = 'core_staffelstufe'
        ordering = ['ab_datum']
        verbose_name = "Staffelstufe"
        verbose_name_plural = "Staffelstufen"

    def __str__(self):
        return f"ab {self.ab_datum:%d.%m.%Y}: CHF {self.netto_mietzins}"


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
        db_table = 'core_mietzinsanpassung'

class Leerstand(models.Model):
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='leerstaende')
    beginn = models.DateField()
    ende = models.DateField(null=True, blank=True)
    grund = models.CharField(max_length=50, default='mietersuche')
    bemerkung = models.TextField(blank=True)

    class Meta:
        db_table = 'core_leerstand'

class Dokument(models.Model):
    mandant = models.ForeignKey('crm.Mandant', on_delete=models.SET_NULL, null=True, blank=True)
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE, null=True, blank=True)
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, null=True, blank=True)
    mieter = models.ForeignKey('crm.Mieter', on_delete=models.CASCADE, null=True, blank=True)
    vertrag = models.ForeignKey(Mietvertrag, on_delete=models.SET_NULL, null=True, blank=True, related_name='dokument_ablage')
    bezeichnung = models.CharField(max_length=200, default="Dokument")
    titel = models.CharField(max_length=200, blank=True)
    datei = models.FileField(upload_to=get_smart_upload_path)
    kategorie = models.CharField(max_length=50, choices=[('vertrag', 'Vertrag'), ('protokoll', 'Protokoll'), ('korrespondenz', 'Korrespondenz'), ('sonstiges', 'Sonstiges')])
    # Sichtbarkeit im Mieterportal (Datenschutz): Standard sichtbar, Verwalter
    # kann sensible Dokumente (z.B. interne Vermerke) ausblenden.
    im_portal_sichtbar = models.BooleanField("Im Mieterportal sichtbar", default=True)
    datum = models.DateField(auto_now_add=True)
    # Exakter Ablage-Zeitpunkt (Datum + Uhrzeit). datum bleibt für Alt-Auswertungen.
    erstellt_am = models.DateTimeField("Abgelegt am", auto_now_add=True, null=True)

    class Meta:
        db_table = 'core_dokument'

    @property
    def ablage_zeit(self):
        """Datum + Uhrzeit der Ablage (Fallback auf datum bei Alt-Dokumenten)."""
        return self.erstellt_am or self.datum

    def __str__(self):
        return self.bezeichnung

class Kuendigung(models.Model):
    """Kündigung eines Mietvertrags (ordentlich/ausserordentlich) inkl. Fristenberechnung."""
    ABSENDER_CHOICES = [('mieter', 'Mieter'), ('vermieter', 'Vermieter')]
    ZUSTELLUNG_CHOICES = [
        ('einschreiben', 'Einschreiben (Mieter)'),
        ('amtliches_formular', 'Amtliches Formular (Vermieter)'),
        ('normal', 'Normal / persönlich'),
    ]
    STATUS_CHOICES = [
        ('erfasst', 'Erfasst'),
        ('bestaetigt', 'Bestätigt'),
        ('vollzogen', 'Vollzogen'),
        ('zurueckgezogen', 'Zurückgezogen'),
    ]

    vertrag = models.ForeignKey(Mietvertrag, on_delete=models.CASCADE, related_name='kuendigungen')
    absender = models.CharField("Gekündigt durch", max_length=20, choices=ABSENDER_CHOICES, default='mieter')
    eingang_datum = models.DateField("Eingang / Poststempel", default=timezone.localdate)
    zustellung = models.CharField("Zustellung", max_length=30, choices=ZUSTELLUNG_CHOICES, default='einschreiben')
    gewuenschtes_ende = models.DateField("Gewünschtes Vertragsende", null=True, blank=True)
    berechneter_termin = models.DateField("Nächster ordentlicher Termin", null=True, blank=True)
    per_datum = models.DateField("Vertragsende (wirksam)", null=True, blank=True)
    ausserordentlich = models.BooleanField("Ausserordentliche Kündigung", default=False)
    ausserordentlich_grund = models.CharField("Grund (ausserordentlich)", max_length=200, blank=True, default='')
    erstreckung_bis = models.DateField("Erstreckung bis", null=True, blank=True)
    status = models.CharField("Status", max_length=20, choices=STATUS_CHOICES, default='erfasst')
    bemerkung = models.TextField("Bemerkung", blank=True, default='')
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kündigung"
        verbose_name_plural = "Kündigungen"
        ordering = ['-eingang_datum']
        db_table = 'core_kuendigung'

    def __str__(self):
        return f"Kündigung {self.vertrag} durch {self.get_absender_display()}"


class Abnahmeprotokoll(models.Model):
    """Wohnungsabnahme-Protokoll (Einzug/Auszug): Zustand Raum-für-Raum mit
    Mängeln, Verursacher-Zuordnung, Fotos, Zählerständen und Unterschriften."""
    TYP_CHOICES = [('einzug', 'Einzug / Übergabe'), ('auszug', 'Auszug / Rücknahme')]
    vertrag = models.ForeignKey('rentals.Mietvertrag', on_delete=models.CASCADE, related_name='abnahmen')
    typ = models.CharField("Art", max_length=10, choices=TYP_CHOICES, default='auszug')
    datum = models.DateField("Datum", default=timezone.now)
    mieter_anwesend = models.BooleanField("Mieter anwesend", default=True)
    verwalter_name = models.CharField("Abnahme durch", max_length=120, blank=True, default='')
    allgemein_zustand = models.CharField("Allgemeinzustand", max_length=25, blank=True, default='gut',
        choices=[('neuwertig', 'Neuwertig'), ('gut', 'Gut'), ('gebraucht', 'Gebraucht'), ('renovationsbeduerftig', 'Renovationsbedürftig')])
    schluessel_anzahl = models.PositiveSmallIntegerField("Schlüssel zurück", null=True, blank=True)
    zaehler_strom = models.CharField("Zählerstand Strom", max_length=40, blank=True, default='')
    zaehler_wasser = models.CharField("Zählerstand Wasser", max_length=40, blank=True, default='')
    zaehler_gas = models.CharField("Zählerstand Gas/Wärme", max_length=40, blank=True, default='')
    neue_adresse = models.CharField("Neue Adresse des Mieters", max_length=200, blank=True, default='')
    bemerkungen = models.TextField("Bemerkungen", blank=True, default='')
    unterschrift_mieter = models.CharField("Unterschrift Mieter", max_length=120, blank=True, default='')
    unterschrift_verwalter = models.CharField("Unterschrift Verwalter", max_length=120, blank=True, default='')
    abgeschlossen = models.BooleanField("Abgeschlossen", default=False)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Abnahmeprotokoll"
        verbose_name_plural = "Abnahmeprotokolle"
        ordering = ['-datum', '-id']
        db_table = 'core_abnahmeprotokoll'

    def __str__(self):
        return f"{self.get_typ_display()} {self.vertrag} ({self.datum})"

    @property
    def maengel_mieter(self):
        return [m for m in self.maengel.all() if m.verursacher == 'mieter']

    @property
    def kosten_mieter_total(self):
        """Vom Mieter zu tragender Gesamtbetrag — Mieteranteil (nach Lebensdauer)
        wenn erfasst, sonst die volle Kostenschätzung."""
        total = Decimal('0.00')
        for m in self.maengel_mieter:
            anteil = m.mieteranteil if m.mieteranteil is not None else m.kostenschaetzung
            total += anteil or Decimal('0.00')
        return total


class AbnahmeMangel(models.Model):
    """Einzelner Mangel im Abnahmeprotokoll, einem Raum + Verursacher zugeordnet.
    Kann mit einem Ausstattungselement (Raumbuch) verknüpft werden — dann fliesst
    die paritätische Lebensdauertabelle ein: der Mieter zahlt nur den Zeitwert-
    anteil ('neu für alt'-Abzug), nicht den vollen Neuwert."""
    VERURSACHER = [('abnutzung', 'Normale Abnutzung'), ('mieter', 'Mieter (Schaden)'), ('vermieter', 'Vermieter/Unterhalt')]
    protokoll = models.ForeignKey(Abnahmeprotokoll, on_delete=models.CASCADE, related_name='maengel')
    raum = models.CharField("Raum", max_length=60, blank=True, default='')
    beschreibung = models.CharField("Mangel", max_length=255)
    verursacher = models.CharField("Verursacher", max_length=12, choices=VERURSACHER, default='abnutzung')
    kostenschaetzung = models.DecimalField("Kostenschätzung CHF", max_digits=9, decimal_places=2, null=True, blank=True)
    foto = models.ImageField("Foto", upload_to='abnahme_fotos/', null=True, blank=True)
    # Lebensdauertabelle / Zeitwert
    ausstattung = models.ForeignKey('portfolio.Ausstattung', on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='maengel')
    neuwert = models.DecimalField("Neuwert CHF", max_digits=9, decimal_places=2, null=True, blank=True)
    mieteranteil = models.DecimalField("Mieteranteil CHF (nach Lebensdauer)", max_digits=9, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'core_abnahmemangel'
        ordering = ['id']

    def __str__(self):
        return f"{self.raum}: {self.beschreibung}"

    def zeitwert_faktor(self, stichtag=None):
        """Restwertanteil 0..1 aus der Lebensdauertabelle des verknüpften Elements
        ('neu für alt'-Abzug). None, wenn keine Lebensdauer-Info vorliegt."""
        if not self.ausstattung_id:
            return None
        from datetime import date as _date
        a = self.ausstattung
        ld = a.effektive_lebensdauer()
        if not (a.einbau_datum and ld):
            return None
        tag = stichtag or (self.protokoll.datum if self.protokoll_id else None) or _date.today()
        alter = max(0.0, (tag - a.einbau_datum).days / 365.25)
        rest = max(0.0, float(ld) - alter)
        return rest / float(ld)

    def berechne_mieteranteil(self, stichtag=None):
        """Vom Mieter zu tragender Betrag: bei verknüpftem Element der Zeitwert-
        anteil der Kosten/des Neuwerts; sonst die volle Kostenschätzung.
        Nur für verursacher='mieter'; sonst 0."""
        if self.verursacher != 'mieter':
            return Decimal('0.00')
        basis = self.kostenschaetzung or self.neuwert
        if basis is None and self.ausstattung_id:
            basis = self.ausstattung.neuwert
        if basis is None:
            return Decimal('0.00')
        faktor = self.zeitwert_faktor(stichtag)
        if faktor is None:
            return Decimal(basis).quantize(Decimal('0.01'))
        return (Decimal(basis) * Decimal(str(faktor))).quantize(Decimal('0.01'))
