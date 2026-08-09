import logging
# rentals/models.py
from django.db import models
from django.utils import timezone
from decimal import Decimal
from core.utils import get_current_ref_zins, get_current_lik, get_smart_upload_path

logger = logging.getLogger(__name__)


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
    # `ist_befristet` trennt sauber das befristete Verhältnis (endet ohne Kündigung
    # mit Zeitablauf, Art. 266 OR) vom unbefristeten (läuft bis zur Kündigung).
    # `ende` wird auch bei einem gekündigten UNbefristeten Vertrag gesetzt
    # (per_datum) — erst dieses Flag macht die Unterscheidung eindeutig, statt
    # `ende IS NOT NULL` mehrdeutig als «befristet» zu interpretieren.
    ist_befristet = models.BooleanField("Befristetes Mietverhältnis", default=False)
    ende = models.DateField(null=True, blank=True)
    erstmals_kuendbar_auf = models.DateField("Erstmals kündbar auf", null=True, blank=True) # 🔥 NEU
    kuendigungsfrist_monate = models.IntegerField("Kündigungsfrist (Monate)", default=3)
    kuendigungstermine = models.CharField("Kündigungstermine", max_length=100, default="Ende jedes Monats ausser Dezember", blank=True)

    # --- OBJEKT & NUTZUNG (🔥 NEU) ---
    familienwohnung = models.BooleanField("Familienwohnung", default=False)
    mitmieter_name = models.CharField("Ehegatte / Mitmieter", max_length=150, blank=True, default='') # 🔥 NEU
    mitmieter = models.ForeignKey('crm.Mieter', on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='vertraege_als_mitmieter', verbose_name="Zweiter Mieter")  # 🔥 NEU (volle Adresse)
    # WG / mehr als zwei Mieter: zusätzliche gleichberechtigte Mitmieter (3., 4., …).
    # Additiv zum FK `mitmieter` (2. Mieter/Ehegatte) — der bewährte Ehepaar-/
    # Familienwohnungs-Pfad bleibt unverändert; `weitere_mieter` deckt echte WGs.
    weitere_mieter = models.ManyToManyField('crm.Mieter', blank=True,
                                            related_name='vertraege_als_weiterer_mieter',
                                            verbose_name="Weitere Mieter (WG)")
    # Solidarhaftung (Art. 143 ff. OR): bei einer WG haften alle Mieter solidarisch
    # für den ganzen Mietzins. Standard True — das ist die übliche WG-Vereinbarung.
    solidarhaftung = models.BooleanField("Solidarische Haftung aller Mieter", default=True)
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
        indexes = [
            models.Index(fields=['status'], name='idx_mietvertrag_status'),
            models.Index(fields=['aktiv'], name='idx_mietvertrag_aktiv'),
        ]

    def __str__(self):
        base_str = f"{self.mieter} - {self.einheit}"
        if self.pk and self.nebenobjekte.exists():
            count = self.nebenobjekte.count()
            return f"{base_str} (+{count} Nebenobjekt{'e' if count > 1 else ''})"
        return base_str

    @property
    def brutto_mietzins(self):
        return (self.netto_mietzins or Decimal('0.00')) + (self.nebenkosten or Decimal('0.00'))

    @property
    def alle_mieter(self):
        """Alle Vertragsparteien in Reihenfolge: Hauptmieter, 2. Mieter (FK),
        weitere WG-Mieter (M2M). Deduped, ohne None. Grundlage für Adressblöcke
        auf amtlichen Formularen und die Zustellung."""
        parteien = [self.mieter] if self.mieter_id else []
        if self.mitmieter_id:
            parteien.append(self.mitmieter)
        if self.pk:
            for m in self.weitere_mieter.all():
                parteien.append(m)
        gesehen, out = set(), []
        for p in parteien:
            if p and p.pk not in gesehen:
                gesehen.add(p.pk)
                out.append(p)
        return out

    @property
    def mitmieter_alle(self):
        """Alle Mitmieter (ohne Hauptmieter) — 2. Mieter + WG-Mieter."""
        return [m for m in self.alle_mieter if not (self.mieter_id and m.pk == self.mieter_id)]

    @property
    def ist_wg(self):
        """Wohngemeinschaft = mehr als zwei Vertragsparteien (Haupt + ≥ 2 weitere)."""
        return len(self.alle_mieter) > 2

    @property
    def vertragsdauer_art(self):
        """'befristet' | 'unbefristet' — massgeblich für Mieterwechsel-Pipeline,
        Kündigungspflicht und amtliches Formular. Ein befristeter Vertrag endet
        ohne Kündigung mit Zeitablauf (Art. 266 OR); ein unbefristeter läuft bis
        zur Kündigung."""
        return 'befristet' if self.ist_befristet else 'unbefristet'

    @property
    def laeuft_aus_am(self):
        """Vereinbartes Zeitablauf-Ende — nur bei befristeten Verträgen. Ein bei
        einem UNbefristeten Vertrag gesetztes `ende` stammt aus einer Kündigung
        (per_datum) und ist hier bewusst None, damit die Auslauf-Pipeline nur
        echte befristete Verhältnisse listet."""
        return self.ende if self.ist_befristet else None

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
        # Datierte Komponenten am Verhältnis haben Vorrang (Gratismonate/gestaffelter
        # Start): die jüngste Komponente mit gueltig_ab <= Stichtag gilt.
        # Python-Filter über .all() statt .filter() → nutzt prefetch_related (kein N+1).
        komps = [k for k in self.mietzins_komponenten.all()
                 if k.gueltig_ab and k.gueltig_ab <= stichtag]
        komp = max(komps, key=lambda k: (k.gueltig_ab, k.id or 0)) if komps else None
        if komp:
            return komp.netto_mietzins or Decimal('0.00')
        # Datierter Sollmietzins-Zeitplan am OBJEKT (Gratismonate direkt in der
        # Sollmiete): die zum Stichtag gültige Zeile treibt die Sollstellung.
        soll = self._sollmietzins_zeile(stichtag)
        if soll:
            return soll.netto_mietzins or Decimal('0.00')
        if self.mietzins_modell == 'staffel':
            stufen = [s for s in self.staffelstufen.all()
                      if s.ab_datum and s.ab_datum <= stichtag]
            stufe = max(stufen, key=lambda s: (s.ab_datum, s.id or 0)) if stufen else None
            return stufe.netto_mietzins if stufe else basis
        anps = [a for a in self.anpassungen.all()
                if a.wirksam_ab and a.wirksam_ab <= stichtag]
        anp = max(anps, key=lambda a: (a.wirksam_ab, a.id or 0)) if anps else None
        return anp.neuer_netto_mietzins if anp else basis

    def effektive_nebenkosten(self, fuer_datum=None):
        """Nebenkosten (Akonto/Pauschal), die an einem Datum gelten — verrechnungs-
        wirksam. Datierte Komponenten haben Vorrang; sonst der flache Vertragswert."""
        from datetime import date as _d
        stichtag = fuer_datum or _d.today()
        if self.pk:
            komps = [k for k in self.mietzins_komponenten.all()
                     if k.gueltig_ab and k.gueltig_ab <= stichtag]
            komp = max(komps, key=lambda k: (k.gueltig_ab, k.id or 0)) if komps else None
            if komp:
                return komp.nebenkosten or Decimal('0.00')
            soll = self._sollmietzins_zeile(stichtag)
            if soll:
                return soll.nebenkosten or Decimal('0.00')
        return self.nebenkosten or Decimal('0.00')

    def _sollmietzins_zeile(self, fuer_datum=None):
        """Die zum Stichtag geltende, MANUELL erfasste Sollmietzins-Zeile des
        Objekts (Gratismonat-Zeitplan). Nur wirksam, wenn für DIESES Verhältnis
        ein Zeitplan hinterlegt ist (mind. eine manuelle Zeile mit gueltig_ab >=
        Mietbeginn) — so treiben stehen gebliebene Alt-Zeilen die Sollstellung
        nicht ungewollt. Amtliche-Anpassungs-Zeilen (quelle_anpassung) sind
        ausgeschlossen — die laufen weiter über den Anpassungs-Pfad."""
        from datetime import date as _d
        if not self.pk or not self.einheit_id:
            return None
        stichtag = fuer_datum or _d.today()
        # Python-Filter über .all() statt .filter() → nutzt prefetch (einheit__sollmietzinse).
        zeilen = [z for z in self.einheit.sollmietzinse.all() if z.quelle_anpassung_id is None]
        if not zeilen:
            return None
        # Zeitplan muss zu diesem Verhältnis gehören (eine Zeile ab Mietbeginn).
        if not any(z.gueltig_ab >= self.beginn for z in zeilen):
            return None
        passend = [z for z in zeilen if z.gueltig_ab <= stichtag]
        if not passend:
            return None
        return max(passend, key=lambda z: (z.gueltig_ab, z.id or 0))

    def _aktive_komponente(self, fuer_datum=None):
        """Die am Stichtag geltende Mietzins-Komponente (jüngste mit
        gueltig_ab <= Stichtag), oder None wenn keine erfasst ist.

        Python-Filter über `.all()` statt `.filter()` — genau wie in
        `effektiver_netto_mietzins` und `_sollmietzins_zeile`: `.filter()`
        umgeht prefetch_related und stellt pro Vertrag eine eigene Abfrage.
        Die Sollstellungs-Vorschau ruft das zweimal je Vertrag auf (Netto und
        Nebenkosten) — gemessen 128 Abfragen allein für diese Tabelle."""
        from datetime import date as _d
        if not self.pk:
            return None
        stichtag = fuer_datum or _d.today()
        komps = [k for k in self.mietzins_komponenten.all()
                 if k.gueltig_ab and k.gueltig_ab <= stichtag]
        return max(komps, key=lambda k: (k.gueltig_ab, k.id or 0)) if komps else None

    def verrechneter_netto_mietzins(self, fuer_datum=None):
        """Netto-Mietzins, der an einem Datum tatsächlich VERRECHNET wird
        (Sollstellung/Debitor) = Referenz − Rabatt/Erlass. In einem Gratismonat
        (Rabatt == Referenz) ist das 0, während `effektiver_netto_mietzins` den
        vollen Referenzwert für Mieterspiegel/Bilanz behält (Option B: brutto
        buchen, Rabatt als Ertragsminderung)."""
        komp = self._aktive_komponente(fuer_datum)
        if komp:
            return komp.verrechnet_netto
        soll = self._sollmietzins_zeile(fuer_datum)
        if soll:
            return soll.verrechnet_netto
        return self.effektiver_netto_mietzins(fuer_datum)

    def verrechnete_nebenkosten(self, fuer_datum=None):
        """Nebenkosten, die an einem Datum tatsächlich verrechnet werden =
        Referenz-NK − Rabatt-NK. Ohne Komponente = effektive Nebenkosten."""
        komp = self._aktive_komponente(fuer_datum)
        if komp:
            return komp.verrechnet_nk
        soll = self._sollmietzins_zeile(fuer_datum)
        if soll:
            return soll.verrechnet_nk
        return self.effektive_nebenkosten(fuer_datum)

    def rabatt_netto_am(self, fuer_datum=None):
        """Netto-Rabatt/-Erlass der am Datum geltenden Komponente (0 ohne)."""
        komp = self._aktive_komponente(fuer_datum)
        if komp:
            return min(komp.rabatt_netto or Decimal('0.00'), komp.netto_mietzins or Decimal('0.00'))
        soll = self._sollmietzins_zeile(fuer_datum)
        if soll:
            return min(soll.rabatt_netto or Decimal('0.00'), soll.netto_mietzins or Decimal('0.00'))
        return Decimal('0.00')

    def rabatt_nk_am(self, fuer_datum=None):
        """NK-Rabatt/-Erlass der am Datum geltenden Komponente (0 ohne)."""
        komp = self._aktive_komponente(fuer_datum)
        if komp:
            return min(komp.rabatt_nk or Decimal('0.00'), komp.nebenkosten or Decimal('0.00'))
        soll = self._sollmietzins_zeile(fuer_datum)
        if soll:
            return min(soll.rabatt_nk or Decimal('0.00'), soll.nebenkosten or Decimal('0.00'))
        return Decimal('0.00')

    def mietzins_zeitplan(self):
        """Die datierten Mietzins-Zeilen, die diesen Vertrag steuern — für Anzeige
        (Vertragsdetail) und das Vertragsdokument. Priorität wie in der Sollstellung:
        vertragseigene Komponenten (falls vorhanden), sonst der Gratismonat-/Rabatt-
        Zeitplan aus dem Objekt-Sollmietzins ab Mietbeginn. Beide Typen liefern
        dieselben Anzeige-Properties (gueltig_ab, netto_mietzins, nebenkosten,
        rabatt_gesamt, verrechnet_brutto, hat_rabatt, notiz). Leer, wenn nur ein
        einzelner Mietzins gilt (kein datierter Verlauf). Funktioniert auch für
        einen noch NICHT gespeicherten Vertrag (Live-Vorschau) — dann zählt nur
        der Objekt-Sollmietzins ab Mietbeginn."""
        komps = list(self.mietzins_komponenten.all().order_by('gueltig_ab', 'id')) if self.pk else []
        if komps:
            return komps
        if not self.einheit_id or not self.beginn:
            return []
        zeilen = list(self.einheit.sollmietzinse
                      .filter(quelle_anpassung__isnull=True)
                      .order_by('gueltig_ab', 'id'))
        tenancy = [z for z in zeilen if z.gueltig_ab >= self.beginn]
        # Nur als "Zeitplan" zeigen, wenn es mehr als eine Zeile ODER ein Rabatt gibt
        # (ein einzelner Mietzins ohne Rabatt ist der normale Fall, keine Staffel).
        if len(tenancy) > 1 or any(z.hat_rabatt for z in tenancy):
            return tenancy
        return []

    def mietzins_hinweise(self):
        """Klartext-Sätze für gestaffelte Mietzinsen/Gratismonate — z.B. «Vom
        01.08.2026 bis 30.09.2026 ist der Nettomietzins erlassen (mietzinsfrei);
        es sind nur die Nebenkosten von CHF 200.00 geschuldet. Ab 01.10.2026 gilt
        der volle Mietzins von CHF 1'000.00.» Fürs Vertragsdokument + Vorschau,
        damit der Gratismonat auch in Worten ausgewiesen ist."""
        from datetime import timedelta

        def _chf(x):
            return f"{(x or Decimal('0')):,.2f}".replace(",", "'")

        zp = self.mietzins_zeitplan()
        if not zp:
            return []
        hinweise = []
        for i, z in enumerate(zp):
            bis = None
            if i + 1 < len(zp):
                bis = zp[i + 1].gueltig_ab - timedelta(days=1)
            zeitraum = f"Ab {z.gueltig_ab:%d.%m.%Y}"
            if bis:
                zeitraum = f"Vom {z.gueltig_ab:%d.%m.%Y} bis {bis:%d.%m.%Y}"
            netto_frei = z.hat_rabatt and z.verrechnet_netto == 0 and (z.netto_mietzins or 0) > 0
            if netto_frei:
                if (z.verrechnet_nk or 0) > 0:
                    hinweise.append(f"{zeitraum} ist der Nettomietzins erlassen (mietzinsfrei); "
                                    f"es sind nur die Nebenkosten von CHF {_chf(z.verrechnet_nk)} geschuldet.")
                else:
                    hinweise.append(f"{zeitraum} ist die Miete vollständig erlassen (mietzinsfrei).")
            elif z.hat_rabatt:
                hinweise.append(f"{zeitraum} gilt ein Rabatt von CHF {_chf(z.rabatt_gesamt)} — "
                                f"zu bezahlen sind CHF {_chf(z.verrechnet_brutto)} "
                                f"(statt CHF {_chf(z.brutto)}).")
            else:
                hinweise.append(f"{zeitraum} gilt der volle Mietzins von CHF {_chf(z.verrechnet_brutto)}"
                                + ("." if self.einheit and self.einheit.ist_einstellplatz
                                   else f" (netto CHF {_chf(z.netto_mietzins)} + NK CHF {_chf(z.nebenkosten)})."))
        return hinweise

    def effektive_basis(self, fuer_datum=None):
        """(Referenzzins, LIK), auf denen der aktuell verrechnete Mietzins beruht:
        aus der jüngsten am Stichtag wirksamen Anpassung, sonst die Vertragsbasis.
        Damit rechnet das Erhöhungs-/Senkungspotenzial nach einer Anpassung nicht
        mehr auf der veralteten Ursprungsbasis weiter."""
        from datetime import date as _d
        stichtag = fuer_datum or _d.today()
        if self.pk:
            anps = [a for a in self.anpassungen.all()
                    if a.wirksam_ab and a.wirksam_ab <= stichtag]
            anp = max(anps, key=lambda a: (a.wirksam_ab, a.id or 0)) if anps else None
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
        # `aktiv` folgt IMMER dem Status (Single Source of Truth = status) — verhindert
        # die Drift, dass ein Entwurf (Default aktiv=True) oder ein gekündigter Vertrag
        # fälschlich als „aktiv" in Dashboards/Filtern auftaucht.
        soll_aktiv = (self.status == 'aktiv')
        if self.aktiv != soll_aktiv:
            self.aktiv = soll_aktiv
            uf = kwargs.get('update_fields')
            if uf is not None:
                kwargs['update_fields'] = list(set(uf) | {'aktiv'})
        # Kaution-Obergrenze durchsetzen (Art. 257e OR: max. 3 Monatsmieten bei
        # Wohnräumen). Bisher nur eine JS-Warnung — der überschiessende Teil ist
        # gesetzlich nicht durchsetzbar, daher serverseitig auf 3× (netto+NK) klemmen.
        if self.kaution_max_monate and self.kautions_betrag:
            basis = (self.netto_mietzins or Decimal('0')) + (self.nebenkosten or Decimal('0'))
            maxbetrag = basis * self.kaution_max_monate
            if maxbetrag > 0 and self.kautions_betrag > maxbetrag:
                self.kautions_betrag = maxbetrag
                uf = kwargs.get('update_fields')
                if uf is not None:
                    kwargs['update_fields'] = list(set(uf) | {'kautions_betrag'})
        super().save(*args, **kwargs)

        # Unterzeichneten Vertrag zentral ablegen → erscheint überall (Portal,
        # Person, Objekt/Liegenschaft). Jeder Rücklauf wird als NEUES, mit
        # Zeitstempel versehenes Dokument abgelegt (bestehende nicht überschrieben).
        if self.sign_status == 'unterzeichnet' and self.pdf_datei:
            try:
                from core.services.ablage import ablage_signierter_vertrag
                ablage_signierter_vertrag(self)
            except Exception:
                logger.debug("Fehler bewusst übergangen", exc_info=True)

    def delete(self, *args, **kwargs):
        # Automatisch erzeugte Vertragspaket-Dokumente (Mietvertrag + Standard-
        # Beilagen) mitlöschen. `Dokument.vertrag` ist SET_NULL — ohne diese
        # Bereinigung blieben die Kopien als verwaiste (vertrag=None) Belege in der
        # Personen-/Objekt-Akte und im Mieterportal hängen und tauchten dort
        # doppelt / „ohne Vertragsbezug" auf. Zentral hier, damit UI (fw_vertrag_
        # loeschen) UND API (delete_vertrag) und jeder künftige Löschpfad greifen.
        try:
            from core.views.pdf import VERTRAGSPAKET_TITEL
            self.dokument_ablage.filter(
                kategorie='vertrag', bezeichnung__in=VERTRAGSPAKET_TITEL
            ).delete()
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)
        return super().delete(*args, **kwargs)

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


class VertragMietzins(models.Model):
    """Datierte Mietzins-Komponente eines Mietverhältnisses: ab `gueltig_ab` gelten
    `netto_mietzins` und `nebenkosten`. Erlaubt gestaffelte Starts und Gratismonate
    ganz ohne Sonderfall — z.B. ab Mietbeginn eine Komponente mit Netto 0.00 (die
    ersten Monate netto-mietzinsfrei), ab einem späteren Datum eine mit dem vollen
    Netto. Sind Komponenten erfasst, sind sie die massgebliche Quelle für die
    Sollstellung (pro Monat gilt die jüngste Komponente mit `gueltig_ab <= Monat`)."""
    vertrag = models.ForeignKey(Mietvertrag, on_delete=models.CASCADE, related_name='mietzins_komponenten')
    gueltig_ab = models.DateField("Gültig ab")
    # Referenz-/Sollmiete = die ECHTE vereinbarte Miete dieser Periode. Massgeblich
    # für Mieterspiegel, Ertragspotenzial und die Bilanz-Sollwerte — bleibt auch in
    # Gratismonaten der volle Betrag (nie 0 für ein vermietetes Objekt).
    netto_mietzins = models.DecimalField("Netto-Mietzins (Referenz)", max_digits=8, decimal_places=2, default=0)
    nebenkosten = models.DecimalField("Nebenkosten (Referenz)", max_digits=8, decimal_places=2, default=0)
    # Rabatt/Erlass für diese Periode — mindert NUR die Verrechnung (Sollstellung),
    # nicht die Referenz. Gratismonat = Rabatt Netto == Referenz Netto.
    rabatt_netto = models.DecimalField("Rabatt Netto", max_digits=8, decimal_places=2, default=0)
    rabatt_nk = models.DecimalField("Rabatt NK", max_digits=8, decimal_places=2, default=0)
    notiz = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        db_table = 'rentals_vertragmietzins'
        ordering = ['gueltig_ab', 'id']
        verbose_name = "Mietzins-Komponente"

    @property
    def brutto(self):
        """Referenz-Brutto (Sollmiete) — für Reporting."""
        return (self.netto_mietzins or Decimal('0.00')) + (self.nebenkosten or Decimal('0.00'))

    @property
    def verrechnet_netto(self):
        return max(Decimal('0.00'), (self.netto_mietzins or Decimal('0.00')) - (self.rabatt_netto or Decimal('0.00')))

    @property
    def verrechnet_nk(self):
        return max(Decimal('0.00'), (self.nebenkosten or Decimal('0.00')) - (self.rabatt_nk or Decimal('0.00')))

    @property
    def verrechnet_brutto(self):
        return self.verrechnet_netto + self.verrechnet_nk

    @property
    def rabatt_gesamt(self):
        """Effektiver Rabatt/Erlass (Netto + NK), geklemmt auf die Referenz."""
        rn = min(self.rabatt_netto or Decimal('0.00'), self.netto_mietzins or Decimal('0.00'))
        rk = min(self.rabatt_nk or Decimal('0.00'), self.nebenkosten or Decimal('0.00'))
        return rn + rk

    @property
    def hat_rabatt(self):
        return (self.rabatt_netto or 0) > 0 or (self.rabatt_nk or 0) > 0

    def __str__(self):
        return f"ab {self.gueltig_ab:%d.%m.%Y}: Netto CHF {self.netto_mietzins} / NK CHF {self.nebenkosten}"


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

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Die Anpassung wird IMMER auch als datierte Sollmietzins-Zeile am OBJEKT
        # geführt (gültig ab = wirksam_ab) — egal über welchen Weg sie entsteht
        # (amtliches Formular, Alt-View, Import, Admin). So erscheint sie im
        # Objekt-Mietzins und neue Verträge starten ab dem Termin mit dem neuen
        # Wert. Gelöscht wird sie via CASCADE (Sollmietzins.quelle_anpassung).
        self._sync_objekt_sollmietzins()

    def _sync_objekt_sollmietzins(self):
        from decimal import Decimal as _D
        einheit = self.vertrag.einheit if self.vertrag_id else None
        if not einheit or self.neuer_netto_mietzins is None:
            return
        from portfolio.models import Sollmietzins
        nk = _D('0.00') if getattr(einheit, 'ist_einstellplatz', False) \
            else (einheit.nebenkosten_aktuell or _D('0.00'))
        teile = ["Amtliche Mietzinsanpassung"]
        grund = (self.begruendung or '').strip()
        if grund:
            teile.append(grund)
        name = self.vertrag.mieter.display_name if self.vertrag.mieter_id else ''
        if name:
            teile.append(name)
        Sollmietzins.objects.update_or_create(
            einheit=einheit, gueltig_ab=self.wirksam_ab,
            defaults={
                'netto_mietzins': self.neuer_netto_mietzins,
                'nebenkosten': nk,
                'basis_referenzzinssatz': self.neuer_referenzzinssatz,
                'basis_lik_punkte': self.neuer_lik_index,
                'quelle_anpassung': self,
                'notiz': " · ".join(teile),
            })

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
    # Das VOR der Kündigung gültige Vertragsende (Snapshot). Bei einer
    # ausserordentlichen Kündigung eines BEFRISTETEN Vertrags wird `vertrag.ende`
    # auf den früheren Kündigungstermin gesetzt; wird die Kündigung später
    # zurückgenommen, stellt dieser Snapshot die ursprünglich vereinbarte Laufzeit
    # wieder her (sonst wäre sie unwiederbringlich verloren, QS-Befund).
    ende_vorher = models.DateField("Vertragsende vor Kündigung", null=True, blank=True)
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
