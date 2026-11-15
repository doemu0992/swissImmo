"""Die Geldzeilen der Startseite kommen aus schlanken Zeilen — mit demselben Ergebnis wie zuvor das Laden aller Rechnungen.

Audit 15.11.2026: `sammle_inbox` lud jede offene Rechnung als Objekt samt Eigentümerkette und Zahlungseingängen und
filterte in Python (bei 510 Einheiten rund 8000 Objekte, drei Viertel der Rechenzeit der Startseite). Jetzt lädt die
Stelle je Rechnung sechs Werte und eine Summe der verbuchten Zahlungen: zwei Abfragen, keine Objekte.

`_referenz` ist eine Abschrift des früheren Rechenwegs. Jeder Test vergleicht die Geldzeilen damit.
Gegenprobe: in `inbox.py` den Filter `status='verbucht'` der Zahlungen entfernen -> `test_gleichheit_in_allen_lagen` rot;
die Bedingung `if r['_o'] > 0` entfernen -> ebenfalls rot (vollständig bezahlte Forderung im Status «offen» zählte mit).
"""
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.models import Max, Q
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from ._helfer import _basis_objekte, _seed_konten


def _referenz(aktive_lg=None):
    """(anzahl_offen, chf_offen, anzahl_mahnen, chf_mahnen, anzahl_zahlen, chf_zahlen) nach dem Rechenweg bis 15.11.2026."""
    from core.services.mahnstufen import Mahnstufen, eigentuemer_von_rechnung
    from finance.models import DebitorenRechnung, KreditorenRechnung, Mahnung
    heute = timezone.localdate()
    deb_qs = DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
    if aktive_lg:
        deb_qs = deb_qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    deb = [r for r in deb_qs.select_related('liegenschaft__eigentuemer', 'vertrag__einheit__liegenschaft__eigentuemer')
           .prefetch_related('zahlungseingaenge') if r.offener_betrag > 0]
    ueberf = [r for r in deb if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) <= heute]
    hoechste = {row['debitoren_rechnung_id']: row['mx'] for row in
                Mahnung.objects.filter(debitoren_rechnung_id__in=[r.id for r in ueberf])
                .values('debitoren_rechnung_id').annotate(mx=Max('stufe'))}
    stufen = Mahnstufen()

    def zu_mahnen(r):
        tage = stufen.tage_im_verzug(r.faellig_am or r.datum, heute, eigentuemer_von_rechnung(r))
        if tage is None:
            return False
        s = stufen.stufe_fuer_tage(tage, eigentuemer_von_rechnung(r))
        return bool(s) and s['stufe'] > (hoechste.get(r.id) or 0)
    mahnen = [r for r in ueberf if zu_mahnen(r)]
    kred_qs = KreditorenRechnung.objects.exclude(status='storniert')
    if aktive_lg:
        kred_qs = kred_qs.filter(liegenschaft=aktive_lg)
    zahlen = [k for k in kred_qs.prefetch_related('zahlungen')
              if k.status in ('freigegeben', 'teilbezahlt') and k.offener_betrag > 0]
    null = Decimal('0.00')
    return (len(deb), sum((r.offener_betrag for r in deb), null), len(mahnen), sum((r.offener_betrag for r in mahnen), null),
            len(zahlen), sum((k.offener_betrag or null for k in zahlen), null))


def _aus_inbox(aktive_lg=None):
    """Dieselben sechs Werte, gelesen aus den Geldzeilen von `sammle_inbox` (Zeile fehlt = 0)."""
    from core.services.inbox import sammle_inbox
    eintraege, _mehr, _typen = sammle_inbox(aktive_lg=aktive_lg)
    nach_ziel = {e['url'].split('?')[0]: e for e in eintraege if e['typ'] == 'geld'}

    def zahl(ziel):
        e = nach_ziel.get(ziel)
        if e is None:
            return 0, Decimal('0.00')
        return int(''.join(z for z in e['titel'].split(' ')[0] if z.isdigit())), e['chf']
    return zahl('/neu/bankabgleich/') + zahl('/neu/mahnwesen/') + zahl('/neu/kreditoren/')


class GeldzeilenTests(TestCase):

    def setUp(self):
        from finance.models import DebitorenRechnung
        _seed_konten()
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = timezone.localdate()
        self.DR = DebitorenRechnung

    def _rechnung(self, betrag, tage_faellig, status='offen', mit_liegenschaft=True, faellig=True):
        tag = self.heute - timedelta(days=tage_faellig)
        return self.DR.objects.create(vertrag=self.v, liegenschaft=self.lg if mit_liegenschaft else None, titel='Miete',
                                      datum=tag, faellig_am=tag if faellig else None, betrag=Decimal(betrag), status=status)

    def _zahlung(self, rechnung, betrag, status='verbucht'):
        from finance.models import Zahlungseingang
        return Zahlungseingang.objects.create(vertrag=self.v, debitoren_rechnung=rechnung, betrag=Decimal(betrag),
                                              datum_eingang=self.heute, status=status)

    def _gleich(self, lage, aktive_lg=None):
        with self.subTest(lage=lage):
            self.assertEqual(_aus_inbox(aktive_lg), _referenz(aktive_lg))

    def test_gleichheit_in_allen_lagen(self):
        from finance.models import Mahnung
        self._gleich('leer')
        a = self._rechnung('1700', 65)                                   # lange überfällig
        self._gleich('eine überfällige Forderung')
        b = self._rechnung('1700', 3, status='teilbezahlt')
        self._zahlung(b, '700')                                           # teilbezahlt: offen 1000
        self._gleich('Teilzahlung')
        c = self._rechnung('900', 40)
        self._zahlung(c, '900')                                           # ganz bezahlt, Status noch «offen»
        self._gleich('vollständig bezahlt im Status offen')
        d = self._rechnung('500', 20)
        self._zahlung(d, '500', status='vorgemerkt')                      # nicht verbucht: zählt nicht als bezahlt
        self._gleich('Zahlung nicht verbucht')
        self._rechnung('1200', -10)                                       # erst in zehn Tagen fällig
        self._gleich('noch nicht fällig')
        self._rechnung('800', 30, status='storniert')
        self._rechnung('650', 30, status='bezahlt')
        self._gleich('storniert und bezahlt zählen nicht')
        self._rechnung('1100', 45, mit_liegenschaft=False)                # Liegenschaft nur über den Vertrag
        self._rechnung('300', 15, faellig=False)                          # ohne Fälligkeit: das Rechnungsdatum gilt
        self._gleich('ohne Liegenschaft, ohne Fälligkeit')
        Mahnung.objects.create(debitoren_rechnung=a, vertrag=self.v, stufe=3, datum=self.heute, betrag_offen=Decimal('1700'))
        self._gleich('höchste Stufe schon gemahnt')
        self._gleich('mit Liegenschaftsfilter', aktive_lg=self.lg)
        self.assertGreater(_referenz()[0], 3)                             # die Lage ist nicht leer

    def test_kreditoren_nur_im_zahlstatus_mit_offenem_betrag(self):
        from finance.models import Buchungskonto, KreditorenRechnung, KreditorenZahlung
        konto = Buchungskonto.objects.filter(nummer='4000').first() or Buchungskonto.objects.first()

        def kreditor(betrag, status):
            return KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal(betrag), status=status,
                                                     liegenschaft=self.lg, konto=konto)
        kreditor('800', 'freigegeben')
        teil = kreditor('1000', 'teilbezahlt')
        KreditorenZahlung.objects.create(kreditor=teil, betrag=Decimal('300'), datum=self.heute)
        ganz = kreditor('400', 'freigegeben')
        KreditorenZahlung.objects.create(kreditor=ganz, betrag=Decimal('400'), datum=self.heute)
        kreditor('999', 'bezahlt')
        kreditor('555', 'storniert')
        kreditor('222', 'neu')
        self._gleich('Kreditoren gemischt')
        self.assertEqual(_referenz()[4:], (2, Decimal('1500.00')))        # 800 + 700, die bezahlte zählt nicht

    def test_geladen_werden_keine_rechnungsobjekte_je_forderung(self):
        """Die Abfragezahl der Geldzeilen hängt nicht von der Zahl der offenen Forderungen ab."""
        from core.services.inbox import sammle_inbox

        def zaehlen():
            with CaptureQueriesContext(connection) as abfragen:
                sammle_inbox()
            return len(abfragen)
        for _ in range(3):
            self._rechnung('1700', 65)
        zaehlen()
        klein = zaehlen()
        for _ in range(40):
            self._rechnung('1700', 65)
        self.assertEqual(zaehlen(), klein)
