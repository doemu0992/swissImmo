# finance/models.py
import pdfplumber
import re
import datetime
import logging
from decimal import Decimal, InvalidOperation
from django.db import models
from django.utils import timezone
from django.db.models import Sum

logger = logging.getLogger(__name__)


def pruefe_dezimalfelder(instance):
    """Weist Beträge ab, die nicht in ihr DecimalField passen.

    SQLite erzwingt `max_digits` NICHT — ein Betrag mit mehr Vorkommastellen
    als das Feld erlaubt wird klaglos gespeichert und wirft dann bei JEDEM
    späteren Lesen `decimal.InvalidOperation`. Eine einzige Fehleingabe
    (z.B. 999999999999.99 in ein `max_digits=10`-Feld) legt damit die ganze
    Liste dauerhaft lahm — für alle Nutzer, und nur noch per Roh-SQL zu
    reparieren. Deshalb hier vor dem Speichern prüfen und laut abbrechen,
    statt die Datenbank zu vergiften. Gilt für jedes Modell, das diese
    Funktion in `save()` aufruft."""
    for feld in instance._meta.concrete_fields:
        if not isinstance(feld, models.DecimalField):
            continue
        wert = getattr(instance, feld.attname, None)
        if wert in (None, ''):
            continue
        try:
            d = Decimal(str(wert))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(f"{feld.name}: «{wert}» ist kein gültiger Betrag.")
        stellen = d.as_tuple()
        vorkomma = len(stellen.digits) + stellen.exponent      # exponent ≤ 0
        max_vorkomma = feld.max_digits - feld.decimal_places
        if vorkomma > max_vorkomma:
            grenze = 10 ** max_vorkomma
            raise ValueError(
                f"{feld.verbose_name or feld.name}: Betrag zu gross "
                f"(maximal {grenze:,.0f}).".replace(',', "'"))

class Buchungskonto(models.Model):
    nummer = models.CharField("Kontonummer", max_length=10, unique=True)
    bezeichnung = models.CharField("Bezeichnung", max_length=100)
    # 'bilanz' = Bilanzkonto mit dynamischer Aktiv/Passiv-Zuordnung nach Saldo-Vorzeichen
    #   (korrekt für normale Konten: z.B. Bank im Minus = Passivum). 'aktiv'/'passiv'
    #   erzwingen die Seite — nötig für Eigenkapital-/Kontokorrent-Konten, deren
    #   Soll-Saldo (z.B. Ausschüttung) das Eigenkapital MINDERT statt ein Aktivum zu sein.
    typ = models.CharField("Typ", max_length=20, choices=[
        ('aufwand', 'Aufwand'), ('ertrag', 'Ertrag'), ('bilanz', 'Bilanz'),
        ('aktiv', 'Aktivum'), ('passiv', 'Passivum / Eigenkapital')])

    # 🔥 HNK-Relevanz gemäss Experten-Feedback
    is_hnk_relevant = models.BooleanField(
        "HNK-relevant",
        default=False,
        help_text="Kennzeichnet, ob Buchungen auf diesem Konto in die Nebenkostenabrechnung fliessen (z.B. 4000er Konten)."
    )

    standard_verteilschluessel = models.CharField(
        "Standard-Verteilschlüssel",
        max_length=20,
        choices=[('m2', 'Fläche (m²)'), ('m3', 'Volumen (m³)'), ('einheit', 'Pro Einheit')],
        default='m2',
        blank=True
    )

    class Meta:
        verbose_name = "Buchungskonto"
        verbose_name_plural = "Kontenplan"
        ordering = ['nummer']
        db_table = 'core_buchungskonto'

    def __str__(self): return f"{self.nummer} - {self.bezeichnung}"


class LieferantProfil(models.Model):
    """Gelernte Stammdaten pro Lieferant (Schlüssel = normalisierter Name).

    Merkt sich das zuletzt verwendete Aufwandskonto (und die IBAN), damit
    Erfassung und KI-Scanner das Konto — und damit die HNK-Relevanz —
    automatisch vorbelegen. Wird bei jeder Kreditor-Freigabe fortgeschrieben.
    """
    name_key = models.CharField("Namensschlüssel", max_length=200, unique=True)
    name_anzeige = models.CharField("Lieferant", max_length=200)
    standard_konto = models.ForeignKey(Buchungskonto, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='lieferanten')
    iban = models.CharField(max_length=50, blank=True)
    treffer = models.PositiveIntegerField("Gelernte Belege", default=0)
    aktualisiert_am = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'finance_lieferantprofil'
        ordering = ['name_anzeige']
        verbose_name = "Lieferantenprofil"

    def __str__(self): return f"{self.name_anzeige} → {self.standard_konto or '—'}"


# 🔥 NEU: Die doppelte Buchhaltung (Soll & Haben) mit Revisionssicherheit
class Buchung(models.Model):
    datum = models.DateField(default=timezone.now)
    beleg_text = models.CharField(max_length=255)

    # Optional: Verknüpfung zur Liegenschaft (für objektbezogene Auswertungen)
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.SET_NULL, null=True, blank=True, related_name='buchungen')

    soll_konto = models.ForeignKey(Buchungskonto, on_delete=models.PROTECT, related_name='soll_buchungen')
    haben_konto = models.ForeignKey(Buchungskonto, on_delete=models.PROTECT, related_name='haben_buchungen')
    betrag = models.DecimalField(max_digits=10, decimal_places=2)

    # Verknüpfungen zu unseren Belegen
    zahlungseingang = models.ForeignKey('Zahlungseingang', on_delete=models.SET_NULL, null=True, blank=True, related_name='buchungen')
    kreditoren_rechnung = models.ForeignKey('KreditorenRechnung', on_delete=models.SET_NULL, null=True, blank=True, related_name='buchungen')
    debitoren_rechnung = models.ForeignKey('DebitorenRechnung', on_delete=models.SET_NULL, null=True, blank=True, related_name='buchungen')

    # 🔥 NEU: Revisionssicherheit (Storno)
    ist_storno = models.BooleanField(default=False)
    storniert_am = models.DateTimeField(null=True, blank=True)
    # Verweis der Gegenbuchung auf die ursprüngliche Buchung (Storno-Paar)
    storno_von = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='stornierungen')
    # Fortlaufende, lückenlose Belegnummer (OR 958f) — beim ersten Speichern vergeben
    beleg_nr = models.PositiveIntegerField("Beleg-Nr", null=True, blank=True, unique=True)

    # Audit-Trail: wer hat diese Buchung ausgelöst (None = System/Migration)
    erstellt_von = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name="Erstellt von"
    )

    def __str__(self):
        return f"{self.datum}: {self.soll_konto.nummer} an {self.haben_konto.nummer} | CHF {self.betrag}"

    def save(self, *args, **kwargs):
        from django.db import IntegrityError, transaction
        # Periodensperre: neue Buchungen in einer abgeschlossenen Periode blockieren.
        if self._state.adding:
            from crm.models import Verwaltung
            vw = Verwaltung.objects.first()
            sperre = vw.buchung_gesperrt_bis if vw else None
            if sperre and self.datum and self.datum <= sperre:
                raise PermissionError(
                    f"Periode gesperrt: Buchungen bis {sperre:%d.%m.%Y} sind abgeschlossen "
                    f"(Datum {self.datum:%d.%m.%Y}). Bitte spätere Periode wählen."
                )
            # Fortlaufende, EINDEUTIGE Belegnummer vergeben (lückenlos, OR 957a/958f).
            # beleg_nr ist unique; bei Parallel-Buchungen (Postgres) kollidiert
            # Max+1 → IntegrityError. Deshalb Retry: Nummer neu berechnen und den
            # Insert im Savepoint wiederholen (funktioniert auch verschachtelt in
            # einer äusseren transaction.atomic()).
            if self.beleg_nr is None:
                last_exc = None
                for _ in range(8):
                    letzte = Buchung.objects.aggregate(m=models.Max('beleg_nr'))['m'] or 0
                    self.beleg_nr = letzte + 1
                    try:
                        with transaction.atomic():
                            super().save(*args, **kwargs)
                        return
                    except IntegrityError as exc:
                        last_exc = exc
                        continue
                if last_exc:
                    raise last_exc
                return
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Revisionssicherheit: Buchungen sind append-only. Statt Löschen wird
        storniert (Gegenbuchung). Hard-Delete nur mit explizitem force=True
        (z.B. Testdaten-Cleanup / Storno-Paar-Bereinigung)."""
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise PermissionError(
            "Buchungen dürfen nicht gelöscht werden (Revisionssicherheit). "
            "Bitte stornieren statt löschen."
        )

    class Meta:
        verbose_name = "Buchung"
        verbose_name_plural = "Buchungen"
        ordering = ['-datum', '-id']
        db_table = 'core_buchung'


# 🔥 NEU: Debitorenrechnungen (inkl. OP-Verwaltung)
class DebitorenRechnung(models.Model):
    STATUS_CHOICES = [
        ('offen', 'Offen'),
        ('teilbezahlt', 'Teilbezahlt'), # 🔥 NEU für saubere OP-Verwaltung
        ('bezahlt', 'Bezahlt'),
        ('storniert', 'Storniert'),     # 🔥 NEU statt Löschen
        ('abgeschrieben', 'Abgeschrieben'),   # Forderungsverlust (Konto 3805)
    ]
    vertrag = models.ForeignKey('rentals.Mietvertrag', on_delete=models.SET_NULL, null=True, related_name='debitoren_rechnungen')
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.SET_NULL, null=True, blank=True)
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.SET_NULL, null=True, blank=True)

    titel = models.CharField("Titel / Grund", max_length=200)
    beschreibung = models.TextField(blank=True, default="")
    datum = models.DateField(default=timezone.now)
    faellig_am = models.DateField(null=True, blank=True)
    betrag = models.DecimalField(max_digits=10, decimal_places=2)

    konto_haben = models.ForeignKey(Buchungskonto, on_delete=models.PROTECT, null=True, blank=True, help_text="Gegenkonto (z.B. 1190 Durchlaufkonto oder 3000 Ertrag)")

    # Weiterverrechnung: Verknüpfung zur weiterverrechneten Lieferantenrechnung
    # (macht die durchgereichte Fremdleistung nachvollziehbar/abstimmbar).
    quell_kreditor = models.ForeignKey('KreditorenRechnung', on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='weiterverrechnungen',
                                       verbose_name="Weiterverrechnung aus Kreditorenrechnung")
    # Anteil des Rechnungsbetrags, der ein Ertrags-ZUSCHLAG ist (nicht durchgereichte
    # Fremdkosten). Für die Weiterverrechnungs-Abstimmung: nur (betrag − zuschlag)
    # zählt als durchgereichte Lieferantenkosten, sonst zöge der Zuschlag den offen
    # weiterzuverrechnenden Betrag fälschlich herunter.
    weiterverrechnung_zuschlag = models.DecimalField("Weiterverrechnungs-Zuschlag (CHF)",
                                                     max_digits=10, decimal_places=2, default=Decimal('0.00'))

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offen')
    # Stammrechnung: verknüpft eine ABGELEITETE Forderung (Mahngebühr, Verzugszins)
    # mit der Hauptforderung, aus der sie entstand. Wird die Hauptforderung
    # storniert, müssen ihre Mahngebühren mitstorniert werden — ohne diese
    # Verknüpfung blieben sie als offene Forderung stehen (Live-Test E).
    stammrechnung = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='folgeforderungen',
                                      verbose_name="Stammrechnung (Mahngebühr/Zins gehört zu)")
    qr_referenz = models.CharField("QRR-Referenz (27-stellig)", max_length=27, blank=True, default='', db_index=True)  # 🔥 NEU (camt.053-Abgleich)
    pdf_dokument = models.FileField(upload_to='debitoren_rechnungen/', blank=True, null=True)

    class Meta:
        verbose_name = "Debitorenrechnung (Weiterverrechnung)"
        verbose_name_plural = "Debitorenrechnungen"
        db_table = 'core_debitorenrechnung'
        indexes = [
            models.Index(fields=['status', 'faellig_am'], name='idx_debrech_status_faellig'),
            models.Index(fields=['vertrag', 'status'], name='idx_debrech_vertrag_status'),
        ]

    def __str__(self):
        return f"{self.titel} - CHF {self.betrag} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # QRR-Referenz automatisch setzen (für QR-Rechnung + camt.053-Abgleich)
        if not self.qr_referenz and self.pk:
            try:
                from core.utils.qr_code import qrr_referenz
                raw, _ = qrr_referenz(self.vertrag_id, self.pk)
                type(self).objects.filter(pk=self.pk).update(qr_referenz=raw)
                self.qr_referenz = raw
            except Exception:
                logger.warning(
                    "QRR-Referenz konnte für DebitorenRechnung %s (Vertrag %s) nicht gesetzt werden",
                    self.pk, self.vertrag_id, exc_info=True,
                )

    # 🔥 NEU: OP-Verwaltung (Offener Betrag)
    @property
    def offener_betrag(self):
        # Nutzt vorgeladene Zahlungseingänge (prefetch_related('zahlungseingaenge')),
        # sonst löst jede Zeile einer Liste eine eigene SUM-Abfrage aus (N+1 →
        # Timeout auf grossen Portfolios). .filter() umgeht den Prefetch-Cache,
        # daher hier in Python filtern, wenn die Daten bereits geladen sind.
        cache = getattr(self, '_prefetched_objects_cache', None) or {}
        if 'zahlungseingaenge' in cache:
            zahlungen = sum((z.betrag or Decimal('0.00'))
                            for z in cache['zahlungseingaenge'] if z.status == 'verbucht')
        else:
            zahlungen = self.zahlungseingaenge.filter(status='verbucht').aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')
        return max(Decimal('0.00'), self.betrag - zahlungen)


class Zahlungseingang(models.Model):
    vertrag = models.ForeignKey('rentals.Mietvertrag', on_delete=models.SET_NULL, null=True, related_name='zahlungen')
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.SET_NULL, null=True, blank=True)
    konto = models.ForeignKey(Buchungskonto, on_delete=models.SET_NULL, null=True, blank=True)

    # 🔥 NEU: Verknüpfung zur Rechnung für sauberes Matching
    debitoren_rechnung = models.ForeignKey(DebitorenRechnung, on_delete=models.SET_NULL, null=True, blank=True, related_name='zahlungseingaenge')

    betrag = models.DecimalField(max_digits=10, decimal_places=2)
    datum_eingang = models.DateField(default=timezone.now)
    buchungs_monat = models.DateField("Für Monat/Jahr", null=True)
    bemerkung = models.CharField(max_length=255, blank=True, default='')
    # Bank-Transaktionsreferenz aus camt.053 (AcctSvcrRef) — Duplikatschutz beim Import
    bank_referenz = models.CharField("Bank-Referenz", max_length=140, blank=True, default='', db_index=True)
    erstellt_am = models.DateTimeField(default=timezone.now)

    # 🔥 NEU: Status für Stornos
    status = models.CharField(max_length=20, choices=[('verbucht', 'Verbucht'), ('storniert', 'Storniert')], default='verbucht')

    # Audit-Trail: wer hat die Zahlung erfasst (None = System/Import)
    erstellt_von = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name="Erfasst von"
    )

    class Meta: db_table = 'core_zahlungseingang'


class Mahnung(models.Model):
    """Revisionssichere Mahn-Historie: pro Mahnschritt ein unveränderlicher Eintrag
    mit Stufe, offenem Betrag und (optionaler) Mahngebühr."""
    debitoren_rechnung = models.ForeignKey(DebitorenRechnung, on_delete=models.CASCADE, related_name='mahnungen', null=True, blank=True)
    vertrag = models.ForeignKey('rentals.Mietvertrag', on_delete=models.SET_NULL, null=True, blank=True, related_name='mahnungen')
    stufe = models.PositiveSmallIntegerField("Mahnstufe", default=1)
    datum = models.DateField("Mahndatum", default=timezone.now)
    betrag_offen = models.DecimalField("Offener Betrag", max_digits=10, decimal_places=2, default=Decimal('0.00'))
    gebuehr = models.DecimalField("Mahngebühr", max_digits=8, decimal_places=2, default=Decimal('0.00'))
    # Mit DIESER Mahnung fakturierter Verzugszins (nur das Delta zur Vorstufe) —
    # verhindert, dass derselbe Verzugszeitraum bei jeder Stufe erneut verzinst wird.
    zins = models.DecimalField("Verzugszins (fakturiert)", max_digits=8, decimal_places=2, default=Decimal('0.00'))
    versandart = models.CharField("Versand", max_length=20, choices=[('email', 'E-Mail'), ('brief', 'Brief'), ('manuell', 'Manuell erfasst')], default='manuell')
    bemerkung = models.CharField(max_length=255, blank=True, default='')
    erstellt_am = models.DateTimeField(auto_now_add=True)
    erstellt_von = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = "Mahnung"
        verbose_name_plural = "Mahn-Historie"
        ordering = ['-datum', '-id']
        db_table = 'core_mahnung'
        constraints = [
            # Pro Debitorenrechnung darf jede Mahnstufe nur EINMAL existieren —
            # verhindert doppelte Mahngebühren durch Doppelklick / Button+Scheduler.
            # Nur wenn eine Rechnung verknüpft ist (vertrag-lose Mahnungen ausgenommen).
            models.UniqueConstraint(
                fields=['debitoren_rechnung', 'stufe'],
                condition=models.Q(debitoren_rechnung__isnull=False),
                name='uniq_mahnung_rechnung_stufe',
            ),
        ]

    def __str__(self):
        return f"{self.stufe}. Mahnung – CHF {self.betrag_offen} ({self.datum})"


class KreditorenRechnung(models.Model):
    STATUS_CHOICES = [
        ('neu', 'Neu / Scan'),
        ('freigegeben', 'Freigegeben'),
        ('in_zahlung', 'In Zahlung'),   # in pain.001-Datei enthalten, noch nicht bestätigt
        ('teilbezahlt', 'Teilbezahlt'), # 🔥 OP: teilweise bezahlt
        ('bezahlt', 'Bezahlt'),
        ('storniert', 'Storniert'), # 🔥 NEU für Revisionssicherheit
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='neu')
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.SET_NULL, null=True, blank=True)
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.SET_NULL, null=True, blank=True)
    konto = models.ForeignKey(Buchungskonto, on_delete=models.SET_NULL, null=True, blank=True)

    # Die "Shift-Left" Felder für die HNK
    is_hnk_relevant = models.BooleanField("In HNK einbeziehen", default=False)
    leistungs_von = models.DateField("Leistungsperiode Von", null=True, blank=True)
    leistungs_bis = models.DateField("Leistungsperiode Bis", null=True, blank=True)
    menge_liter = models.DecimalField("Menge (Liter)", max_digits=10, decimal_places=2, null=True, blank=True)

    lieferant = models.CharField(max_length=200, blank=True)
    datum = models.DateField(null=True, blank=True)
    faellig_am = models.DateField(null=True, blank=True)
    betrag = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # Bruttobetrag inkl. MWST
    mwst_satz = models.DecimalField("MWST-Satz (%)", max_digits=4, decimal_places=1, default=Decimal('0.0'))  # 🔥 NEU (0 = keine Vorsteuer)
    mwst_betrag = models.DecimalField("Vorsteuer (CHF)", max_digits=10, decimal_places=2, default=Decimal('0.00'))  # 🔥 NEU
    iban = models.CharField(max_length=50, blank=True)
    referenz = models.CharField(max_length=100, blank=True)
    # Ausführungsdatum des Zahllaufs, in dem diese Rechnung enthalten ist.
    # Ohne dieses Feld ist im Nachhinein nicht belegbar, auf WELCHEN Termin die
    # Bank beauftragt wurde — «heute» war eine stille Annahme.
    zahlung_ausfuehrung = models.DateField("Ausführung Zahllauf", null=True, blank=True)

    beleg_scan = models.FileField(upload_to='kreditoren_belege/', blank=True, null=True)
    fehlermeldung = models.TextField(blank=True)

    class Meta:
        verbose_name = "Kreditorenrechnung"
        db_table = 'core_kreditorenrechnung'

    def __str__(self): return f"{self.lieferant} - {self.betrag} ({self.status})"

    @property
    def weiterverrechnet_betrag(self):
        """Summe der bereits an Mieter durchgereichten Fremdkosten (ohne Stornos).
        Der Ertrags-Zuschlag zählt NICHT als weiterverrechnete Lieferantenkosten."""
        cache = getattr(self, '_prefetched_objects_cache', None) or {}
        if 'weiterverrechnungen' in cache:
            rows = [w for w in cache['weiterverrechnungen'] if w.status != 'storniert']
            s = sum((w.betrag or Decimal('0.00')) for w in rows)
            z = sum((w.weiterverrechnung_zuschlag or Decimal('0.00')) for w in rows)
            return s - z
        agg = (self.weiterverrechnungen.exclude(status='storniert')
               .aggregate(s=Sum('betrag'), z=Sum('weiterverrechnung_zuschlag')))
        return (agg['s'] or Decimal('0.00')) - (agg['z'] or Decimal('0.00'))

    @property
    def offen_weiterzuverrechnen(self):
        """Noch nicht weiterverrechneter Anteil der Rechnung."""
        return max(Decimal('0.00'), (self.betrag or Decimal('0.00')) - self.weiterverrechnet_betrag)

    # --- OP-Verwaltung auf der Kreditorenseite (analog Debitoren) ---
    @property
    def bezahlt_betrag(self):
        cache = getattr(self, '_prefetched_objects_cache', None) or {}
        if 'zahlungen' in cache:
            return sum((z.betrag or Decimal('0.00'))
                       for z in cache['zahlungen'] if z.status == 'verbucht')
        return (self.zahlungen.filter(status='verbucht').aggregate(s=Sum('betrag'))['s']
                or Decimal('0.00'))

    @property
    def offener_betrag(self):
        return max(Decimal('0.00'), (self.betrag or Decimal('0.00')) - self.bezahlt_betrag)

    # --- Kostenaufteilung (Split auf mehrere Konten/Objekte) ---
    # Beide Properties nutzen den Prefetch-Cache (prefetch_related('positionen')),
    # sonst löst jede Zeile einer Liste eigene Abfragen aus (N+1).
    @property
    def _positionen_liste(self):
        cache = getattr(self, '_prefetched_objects_cache', None) or {}
        if 'positionen' in cache:
            return list(cache['positionen'])
        return None

    @property
    def hat_positionen(self):
        vorgeladen = self._positionen_liste
        if vorgeladen is not None:
            return bool(vorgeladen)
        return self.positionen.exists()

    @property
    def positionen_summe(self):
        vorgeladen = self._positionen_liste
        if vorgeladen is not None:
            return sum((p.betrag or Decimal('0.00') for p in vorgeladen), Decimal('0.00'))
        return (self.positionen.aggregate(s=Sum('betrag'))['s'] or Decimal('0.00'))

    @property
    def positionen_differenz(self):
        """Rechnungsbetrag minus Summe der Positionen (0 = sauber aufgeteilt)."""
        return (self.betrag or Decimal('0.00')) - self.positionen_summe

    @property
    def hnk_betrag(self):
        """Der in die Nebenkostenabrechnung fliessende Brutto-Anteil dieser Rechnung.
        Mit Split = Summe der HNK-Positionen, sonst der ganze Betrag wenn HNK-relevant."""
        if self.hat_positionen:
            return (self.positionen.filter(is_hnk_relevant=True)
                    .aggregate(s=Sum('betrag'))['s'] or Decimal('0.00'))
        return (self.betrag or Decimal('0.00')) if self.is_hnk_relevant else Decimal('0.00')


class KreditorPosition(models.Model):
    """Eine Kostenposition einer aufgeteilten Kreditorenrechnung: eigenes
    Aufwandskonto, optionales Objekt und eigenes HNK-Flag. Ermöglicht das
    Splitten einer Sammelrechnung (mehrere Häuser) bzw. das Trennen von
    Unterhalt (Eigentümer) und HNK innerhalb einer Rechnung. Jede Position
    wird bei der Freigabe einzeln gebucht."""
    rechnung = models.ForeignKey(KreditorenRechnung, on_delete=models.CASCADE, related_name='positionen')
    konto = models.ForeignKey(Buchungskonto, on_delete=models.PROTECT, related_name='kreditor_positionen')
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.SET_NULL, null=True, blank=True)
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.SET_NULL, null=True, blank=True)
    bezeichnung = models.CharField(max_length=200, blank=True, default='')
    betrag = models.DecimalField("Betrag (brutto)", max_digits=10, decimal_places=2)
    is_hnk_relevant = models.BooleanField("HNK-relevant", default=False)

    class Meta:
        db_table = 'finance_kreditorposition'
        ordering = ['id']

    def __str__(self): return f"{self.konto} · CHF {self.betrag}"


class KreditorenZahlung(models.Model):
    """Ausgangszahlung an einen Lieferanten (ermöglicht Teilzahlungen / OP)."""
    kreditor = models.ForeignKey(KreditorenRechnung, on_delete=models.CASCADE, related_name='zahlungen')
    betrag = models.DecimalField(max_digits=10, decimal_places=2)
    datum = models.DateField(default=timezone.now)
    konto = models.ForeignKey(Buchungskonto, on_delete=models.SET_NULL, null=True, blank=True)
    bank_referenz = models.CharField("Bank-Referenz", max_length=140, blank=True, default='', db_index=True)
    bemerkung = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=20, choices=[('verbucht', 'Verbucht'), ('storniert', 'Storniert')], default='verbucht')
    erstellt_am = models.DateTimeField(default=timezone.now)
    erstellt_von = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'core_kreditorenzahlung'
        ordering = ['-datum', '-id']

    def __str__(self):
        return f"Zahlung CHF {self.betrag} an {self.kreditor.lieferant}"

# ========================================================
# HNK ABRECHNUNG UND BELEGE
# ========================================================

class AbrechnungsPeriode(models.Model):
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE, related_name='abrechnungen')
    bezeichnung = models.CharField("Titel", max_length=100)
    start_datum = models.DateField()
    ende_datum = models.DateField()
    abgeschlossen = models.BooleanField(default=False)
    # Eingefrorene Abrechnung: Beim Verbuchen wird das berechnete Ergebnis (die
    # kanonische Engine-Ausgabe) als JSON festgehalten. Danach zeigen Detailseite,
    # PDF und Versand GENAU die gebuchten Zahlen — auch wenn Belege, Flächen oder
    # Verträge später geändert werden. Ohne diesen Snapshot drifteten Anzeige/PDF
    # von den tatsächlich verbuchten Nachzahlungen/Gutschriften weg (Live-Test G).
    snapshot_json = models.TextField("Eingefrorene Abrechnung (JSON)", blank=True, default='')

    # Für die Bestandesrechnung (Heizöl/Gas)
    anfangsbestand_liter = models.DecimalField("Anfangsbestand (L)", max_digits=10, decimal_places=2, default=0)
    anfangsbestand_chf = models.DecimalField("Anfangsbestand (CHF)", max_digits=10, decimal_places=2, default=0)
    endbestand_liter = models.DecimalField("Endbestand (L) am Stichtag", max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Abrechnungsperiode"
        verbose_name_plural = "Abrechnungsperioden"
        db_table = 'core_abrechnungsperiode'

    def __str__(self): return self.bezeichnung

    @property
    def total_kosten(self):
        # EINE Quelle der Wahrheit: die kanonische Abrechnungs-Engine (identisch zu
        # Detailansicht, PDF und Verbuchung). Sie ist split-aware (nur HNK-Anteile),
        # vermeidet Doppelzählung Beleg/Kreditor und enthält Honorar + Öl-Bestand.
        try:
            from core.utils.billing import hole_abrechnung
            r = hole_abrechnung(self)   # eingefroren, falls verbucht (Live-Test G)
            if not r.get('error'):
                return Decimal(str(r.get('total_kosten', 0) or 0))
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)
        # Fallback (z.B. ohne Liegenschaft): reine Belegsumme
        return self.belege.aggregate(total=Sum('betrag'))['total'] or Decimal('0.00')

    def berechne_mieter_anteil(self, vertrag):
        v_start = vertrag.beginn
        v_ende = vertrag.ende or self.ende_datum
        overlap_start = max(v_start, self.start_datum)
        overlap_end = min(v_ende, self.ende_datum)

        if overlap_start > overlap_end:
            return Decimal('0.00')

        tage_bewohnt = (overlap_end - overlap_start).days + 1
        tage_periode = (self.ende_datum - self.start_datum).days + 1
        zeit_faktor = Decimal(tage_bewohnt) / Decimal(tage_periode)

        kosten_m2 = self.belege.filter(verteilschluessel='m2').aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')
        kosten_einheit = self.belege.filter(verteilschluessel='einheit').aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')

        alle_einheiten = self.liegenschaft.einheiten.all()
        total_flaeche = sum(e.flaeche_m2 for e in alle_einheiten if e.flaeche_m2) or 1
        anzahl_einheiten = alle_einheiten.count() or 1

        mieter_flaeche = vertrag.einheit.flaeche_m2 or 0
        anteil_m2 = (kosten_m2 * Decimal(mieter_flaeche) / Decimal(total_flaeche)) * zeit_faktor
        anteil_einheit = (kosten_einheit / Decimal(anzahl_einheiten)) * zeit_faktor

        total_anteil = round(anteil_m2 + anteil_einheit, 2)
        return Decimal(str(total_anteil))

    # --- Die "Heizgradtage" Logik für Mieterwechsel ---
    def get_heizgradtage_faktor(self, monat):
        """ Gibt den Schweizer Standard-Prozentsatz der Heizenergie pro Monat zurück """
        hgt = {1: 21, 2: 18, 3: 15, 4: 10, 5: 5, 6: 0, 7: 0, 8: 0, 9: 3, 10: 8, 11: 10, 12: 10}
        return Decimal(hgt.get(monat, 0)) / Decimal('100')

class NebenkostenLernRegel(models.Model):
    suchwort = models.CharField("Schlüsselwort (z.B. Firmenname)", max_length=100, unique=True)
    kategorie_zuweisung = models.CharField("Wird zugewiesen zu", max_length=50)
    treffer_quote = models.IntegerField("Erfolgreich angewendet", default=0)

    class Meta:
        verbose_name = "KI Lern-Regel"
        verbose_name_plural = "KI Lern-Regeln"
        db_table = 'core_nebenkostenlernregel'

    def __str__(self): return f"'{self.suchwort}' -> {self.kategorie_zuweisung}"

class NebenkostenBeleg(models.Model):
    NK_KATEGORIE_CHOICES = [
        ('heizung', 'Heizung & Warmwasser'),
        ('wasser', 'Wasser / Abwasser'),
        ('hauswart', 'Hauswartung & Reinigung'),
        ('strom', 'Allgemeinstrom'),
        ('lift', 'Serviceabo Lift'),
        ('verwaltung', 'Verwaltungshonorar'),
        ('tv', 'TV / Kabelgebühren'),
        ('kehricht', 'Kehricht / Entsorgung'),
        ('diverse', 'Diverse Betriebskosten'),
    ]
    VERTEIL_CHOICES = [('m2', 'Nach Fläche (m²)'), ('m3', 'Nach Volumen (m³)'),
                       ('einheit', 'Pro Wohnung'), ('personen', 'Nach Personenzahl')]

    periode = models.ForeignKey(AbrechnungsPeriode, on_delete=models.CASCADE, related_name='belege')
    datum = models.DateField(default=timezone.now, blank=True, null=True)
    text = models.CharField("Beschreibung / Lieferant", max_length=255, blank=True)
    kategorie = models.CharField(max_length=50, choices=NK_KATEGORIE_CHOICES, default='diverse')
    verteilschluessel = models.CharField("Verteilschlüssel", max_length=20, choices=VERTEIL_CHOICES, default='m2')
    betrag = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    beleg_scan = models.FileField(upload_to='nebenkosten_belege/', blank=True, null=True)

    class Meta:
        verbose_name = "Nebenkostenbeleg"
        db_table = 'core_nebenkostenbeleg'

    def extract_data_locally(self):
        if not self.beleg_scan: return
        try:
            full_text = ""
            with pdfplumber.open(self.beleg_scan.path) as pdf:
                for page in pdf.pages:
                    full_text += page.extract_text() + "\n"

            text_lower = full_text.lower()
            if self.kategorie == 'diverse':
                kategorie_gefunden = False
                for regel in NebenkostenLernRegel.objects.all():
                    if regel.suchwort.lower() in text_lower:
                        self.kategorie = regel.kategorie_zuweisung
                        regel.treffer_quote += 1
                        regel.save()
                        kategorie_gefunden = True
                        break
                if not kategorie_gefunden:
                    mapping = {
                        'strom': ['strom', 'ewz', 'bkw', 'ckw', 'energie', 'elektro'],
                        'wasser': ['wasser', 'abwasser', 'wasserversorgung'],
                        'heizung': ['heizöl', 'brennstoff', 'erdgas', 'fernwärme'],
                        'hauswart': ['hauswartung', 'reinigung', 'garten', 'schneeräumung'],
                        'kehricht': ['kehricht', 'entsorgung', 'abfall'],
                        'lift': ['aufzug', 'lift', 'schindler', 'otis']
                    }
                    for cat, keywords in mapping.items():
                        if any(key in text_lower for key in keywords):
                            self.kategorie = cat
                            break

            if not self.betrag:
                matches = re.findall(r'(?:chf|total|betrag|summe)[\s\:\.]*([\d\'\s]+\.\d{2})', text_lower)
                if not matches:
                    matches = re.findall(r'\b(\d{1,3}(?:[\' ]\d{3})*\.\d{2})\b', full_text)
                if matches:
                    clean_amounts = []
                    for m in matches:
                        clean_val = m.replace("'", "").replace(" ", "")
                        try:
                            clean_amounts.append(Decimal(clean_val))
                        except (InvalidOperation, ValueError):
                            continue
                    if clean_amounts:
                        max_amount = max(clean_amounts)
                        if max_amount < Decimal('100000'):
                            self.betrag = max_amount

            if not self.text:
                lines = [l.strip() for l in full_text.split('\n') if len(l.strip()) > 3]
                if lines: self.text = lines[0][:255]

        except Exception as e:
            if not self.text: self.text = f"Lokaler Scan Info: {str(e)[:50]}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if self.beleg_scan and is_new:
            self.extract_data_locally()
            if self.betrag is None:
                self.betrag = Decimal('0.00')
            super().save(update_fields=['betrag', 'text', 'kategorie'])

    def __str__(self): return f"{self.text or 'Beleg'} (CHF {self.betrag})"

class Jahresabschluss(models.Model):
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE)
    jahr = models.IntegerField(default=2026)
    notizen = models.TextField(blank=True, default='')

    class Meta: db_table = 'core_jahresabschluss'

class MietzinsKontrolle(models.Model):
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE)
    monat = models.DateField()
    notizen = models.TextField(blank=True, default='')

    class Meta: db_table = 'core_mietzinskontrolle'

# ============================================================
# ANLAGENBUCHHALTUNG (lineare Abschreibung / AfA)
# ============================================================
class Anlage(models.Model):
    """Anlagegut (z.B. Heizung, Lift, Küche) mit linearer Abschreibung.
    Jährliche AfA = Anschaffungswert / Nutzungsdauer (Jahre)."""
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE, related_name='anlagen')
    bezeichnung = models.CharField("Bezeichnung", max_length=200)
    anschaffungswert = models.DecimalField("Anschaffungswert (CHF)", max_digits=12, decimal_places=2, default=Decimal('0.00'))
    anschaffungsdatum = models.DateField("Anschaffungsdatum")
    nutzungsdauer_jahre = models.PositiveSmallIntegerField("Nutzungsdauer (Jahre)", default=10)
    restwert = models.DecimalField("Restwert (CHF)", max_digits=12, decimal_places=2, default=Decimal('0.00'))
    aktiv = models.BooleanField("Aktiv", default=True)
    notizen = models.TextField(blank=True, default='')
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Anlage"
        verbose_name_plural = "Anlagen"
        db_table = 'core_anlage'
        ordering = ['liegenschaft', 'bezeichnung']

    def __str__(self):
        return f"{self.bezeichnung} ({self.anschaffungswert} CHF)"

    @property
    def jahres_afa(self):
        if not self.nutzungsdauer_jahre:
            return Decimal('0.00')
        basis = (self.anschaffungswert or Decimal('0')) - (self.restwert or Decimal('0'))
        return (basis / Decimal(self.nutzungsdauer_jahre)).quantize(Decimal('0.01'))

    @property
    def kumulierte_afa(self):
        return sum((a.betrag for a in self.abschreibungen.all()), Decimal('0.00'))

    @property
    def buchwert(self):
        return (self.anschaffungswert or Decimal('0')) - self.kumulierte_afa


class Abschreibung(models.Model):
    """Ein AfA-Buchungsvorgang pro Anlage und Jahr (idempotent)."""
    anlage = models.ForeignKey(Anlage, on_delete=models.CASCADE, related_name='abschreibungen')
    jahr = models.PositiveIntegerField("Jahr")
    betrag = models.DecimalField("AfA-Betrag", max_digits=12, decimal_places=2, default=Decimal('0.00'))
    datum = models.DateField("Buchungsdatum")
    buchung = models.ForeignKey(Buchung, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_abschreibung'
        unique_together = ('anlage', 'jahr')
        ordering = ['-jahr']

    def __str__(self):
        return f"AfA {self.jahr}: {self.anlage.bezeichnung} — CHF {self.betrag}"


class Erneuerungsfonds(models.Model):
    """Erneuerungsfonds / Rückstellung je Liegenschaft (STWEG-tauglich).
    Jährliche Einlage wird als Rückstellung gebucht."""
    liegenschaft = models.OneToOneField('portfolio.Liegenschaft', on_delete=models.CASCADE, related_name='erneuerungsfonds')
    bestand = models.DecimalField("Bestand (CHF)", max_digits=12, decimal_places=2, default=Decimal('0.00'))
    jaehrliche_einlage = models.DecimalField("Jährliche Einlage (CHF)", max_digits=10, decimal_places=2, default=Decimal('0.00'))
    letzte_einlage_jahr = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Erneuerungsfonds"
        verbose_name_plural = "Erneuerungsfonds"
        db_table = 'core_erneuerungsfonds'

    def __str__(self):
        return f"Erneuerungsfonds {self.liegenschaft} — CHF {self.bestand}"


class EigentuemerAuszahlung(models.Model):
    """Auszahlung an einen Eigentümer (Mandant) aus dem Kontokorrent Eigentümer.
    Bucht Soll 2850 (Kontokorrent Eigentümer) / Haben Bank — reduziert die
    Verbindlichkeit gegenüber dem Eigentümer und die liquiden Mittel."""
    mandant = models.ForeignKey('crm.Mandant', on_delete=models.CASCADE, related_name='auszahlungen')
    betrag = models.DecimalField(max_digits=12, decimal_places=2)
    datum = models.DateField(default=timezone.now)
    konto = models.ForeignKey(Buchungskonto, on_delete=models.SET_NULL, null=True, blank=True,
                              help_text="Bankkonto der Auszahlung (Haben)")
    bemerkung = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=20, choices=[('verbucht', 'Verbucht'), ('storniert', 'Storniert')],
                              default='verbucht')
    erstellt_am = models.DateTimeField(default=timezone.now)
    erstellt_von = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = "Eigentümer-Auszahlung"
        verbose_name_plural = "Eigentümer-Auszahlungen"
        ordering = ['-datum', '-id']
        db_table = 'core_eigentuemerauszahlung'

    def __str__(self):
        return f"Auszahlung {self.mandant_id} — CHF {self.betrag} ({self.datum})"


class Hypothek(models.Model):
    """Hypothekartranche auf einer Liegenschaft (Fest/SARON/variabel).
    Grundlage für Zinskosten und Ablauf-/Refinanzierungsplanung."""
    TYP = [('fest', 'Festhypothek'), ('saron', 'SARON'), ('variabel', 'Variabel')]
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE, related_name='hypotheken')
    bank = models.CharField("Bank / Gläubiger", max_length=120, blank=True, default='')
    bezeichnung = models.CharField("Bezeichnung / Tranche", max_length=120, blank=True, default='')
    betrag = models.DecimalField("Betrag (CHF)", max_digits=12, decimal_places=2, default=Decimal('0.00'))
    zinssatz = models.DecimalField("Zinssatz (%)", max_digits=5, decimal_places=3, default=Decimal('0.000'))
    typ = models.CharField(max_length=10, choices=TYP, default='fest')
    beginn = models.DateField("Abschluss / Beginn", null=True, blank=True)
    ablauf = models.DateField("Ablauf / Fälligkeit", null=True, blank=True)
    notiz = models.TextField(blank=True, default='')
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Hypothek"
        verbose_name_plural = "Hypotheken"
        ordering = ['ablauf', 'id']
        db_table = 'core_hypothek'

    def __str__(self):
        return f"{self.bank or 'Hypothek'} {self.betrag} ({self.get_typ_display()})"

    @property
    def jaehrlicher_zins(self):
        """Jährliche Zinskosten = Betrag × Zinssatz."""
        return (self.betrag * self.zinssatz / Decimal('100')).quantize(Decimal('0.01'))


class Kontoauszug(models.Model):
    """Ein importierter Bank-Kontoauszug mit seinem Schlusssaldo.

    Ohne den Schlusssaldo gibt es keinen Abstimmungsnachweis: Man kann zwar
    Zahlungen zuordnen, aber nie belegen, dass das Buchhaltungskonto mit dem
    realen Bankkonto übereinstimmt. Genau das ist der erste Schritt jedes
    Monatsabschlusses (Praxis-Audit).
    """
    konto = models.ForeignKey('finance.Buchungskonto', on_delete=models.PROTECT,
                              related_name='kontoauszuege',
                              help_text="Buchhaltungskonto, das dieses Bankkonto abbildet")
    iban = models.CharField("IBAN", max_length=34, blank=True, default='', db_index=True)
    von = models.DateField("Periode von", null=True, blank=True)
    bis = models.DateField("Periode bis", null=True, blank=True)
    eroeffnungssaldo = models.DecimalField("Eröffnungssaldo", max_digits=12, decimal_places=2,
                                           null=True, blank=True)
    schlusssaldo = models.DecimalField("Schlusssaldo laut Auszug", max_digits=12, decimal_places=2,
                                       null=True, blank=True)
    dateiname = models.CharField(max_length=255, blank=True, default='')
    quelle = models.CharField(max_length=30, blank=True, default='')
    importiert_am = models.DateTimeField(auto_now_add=True)
    importiert_von = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Kontoauszug"
        verbose_name_plural = "Kontoauszüge"
        ordering = ['-bis', '-id']

    def __str__(self):
        return f"Auszug {self.konto.nummer} bis {self.bis or '?'}"


class Bankbewegung(models.Model):
    """EINE Zeile eines Bank-Kontoauszugs — dauerhaft gespeichert.

    Bisher las der Import nur Gutschriften und warf sie nach der Zuordnung weg;
    Belastungen (Lieferantenzahlungen, Gebühren, Zinsen, Daueraufträge) wurden
    gar nicht erst gelesen. Damit war das Bankkonto strukturell nicht abstimmbar
    und der «Bankabgleich» faktisch eine Liste offener Debitoren (Praxis-Audit).

    Vorzeichen: positiv = Gutschrift (Eingang), negativ = Belastung (Ausgang) —
    wie auf dem Kontoauszug.
    """
    STATUS = [
        ('offen', 'Offen'),
        ('verbucht', 'Verbucht'),
        ('ignoriert', 'Ignoriert'),
    ]
    auszug = models.ForeignKey(Kontoauszug, on_delete=models.CASCADE, related_name='bewegungen',
                               null=True, blank=True)
    konto = models.ForeignKey('finance.Buchungskonto', on_delete=models.PROTECT,
                              related_name='bankbewegungen',
                              help_text="Bankkonto (Buchhaltungskonto) dieser Bewegung")
    datum = models.DateField("Buchungsdatum", db_index=True)
    valuta = models.DateField("Valutadatum", null=True, blank=True)
    betrag = models.DecimalField("Betrag", max_digits=12, decimal_places=2,
                                 help_text="positiv = Gutschrift, negativ = Belastung")
    text = models.CharField("Text / Mitteilung", max_length=255, blank=True, default='')
    gegenpartei = models.CharField("Auftraggeber / Empfänger", max_length=160, blank=True, default='')
    referenz = models.CharField("QR-Referenz", max_length=40, blank=True, default='')
    # Eindeutiger Schlüssel der Bank — verhindert Doppelimport derselben Zeile.
    bank_referenz = models.CharField(max_length=140, blank=True, default='', db_index=True)
    status = models.CharField(max_length=12, choices=STATUS, default='offen', db_index=True)
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='bankbewegungen')
    zahlung = models.ForeignKey('finance.Zahlungseingang', on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='bankbewegungen')
    buchung = models.ForeignKey('finance.Buchung', on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='bankbewegungen')
    bemerkung = models.CharField(max_length=255, blank=True, default='')
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bankbewegung"
        verbose_name_plural = "Bankbewegungen"
        ordering = ['-datum', '-id']
        indexes = [
            models.Index(fields=['status', 'datum'], name='idx_bankbew_status_datum'),
        ]

    def __str__(self):
        return f"{self.datum} {self.betrag} {self.text[:40]}"

    @property
    def ist_gutschrift(self):
        return self.betrag > 0

    @property
    def ist_belastung(self):
        return self.betrag < 0


class ZahlerZuordnung(models.Model):
    """Gelernte Zuordnung «Absendername → Mietvertrag».

    Zahlt jemand jeden Monat ohne QR-Referenz (Dauerauftrag eines Vereins, ein
    Angehöriger, der für den Mieter überweist), landete die Zahlung bisher
    jeden Monat neu auf dem Durchlaufkonto 1190 und musste jedes Mal von Hand
    zugeordnet werden. Nach der ersten manuellen Zuordnung merkt sich das
    Programm den Absender und trifft beim nächsten Import selbst.

    Der Name wird normalisiert gespeichert (nur Kleinbuchstaben und Ziffern),
    damit Schreibweisen der Bank («Muster AG», «MUSTER  AG.») zusammenfallen.
    """
    name_norm = models.CharField("Absender (normalisiert)", max_length=160,
                                 unique=True, db_index=True)
    name_anzeige = models.CharField("Absender", max_length=160, blank=True, default='')
    vertrag = models.ForeignKey('rentals.Mietvertrag', on_delete=models.CASCADE,
                                related_name='zahler_zuordnungen')
    treffer = models.PositiveIntegerField("Automatisch getroffen", default=0)
    zuletzt = models.DateTimeField("Zuletzt getroffen", null=True, blank=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Zahler-Zuordnung"
        verbose_name_plural = "Zahler-Zuordnungen"
        ordering = ['name_anzeige']

    def __str__(self):
        return f"{self.name_anzeige or self.name_norm} → {self.vertrag_id}"


# ---------------------------------------------------------------------------
# Überlauf-Schutz für ALLE Modelle mit DecimalFields (nicht nur finance).
# SQLite erzwingt max_digits nicht; ein zu grosser Betrag wird gespeichert und
# legt danach bei jedem Lesen die Seite mit InvalidOperation lahm — für alle
# Nutzer, nur per Roh-SQL zu beheben. Ein pre_save-Signal fängt es an EINER
# Stelle ab, statt in einem Dutzend save()-Methoden. Für Modelle ohne
# DecimalField ist die Prüfung ein no-op (leere Schleife).
from django.db.models.signals import pre_save as _pre_save


def _dezimalfeld_guard(sender, instance, **kwargs):
    pruefe_dezimalfelder(instance)


_pre_save.connect(_dezimalfeld_guard, dispatch_uid='finance.dezimalfeld_guard')
