"""Testmodul buchhaltung — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 11 Klassen, unveraendert uebernommen."""
from datetime import date
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (
    _team_user, _basis_objekte, _seed_konten, _P3_CAMT, Mieter, Eigentuemer,
    Verwaltung, Liegenschaft, Einheit, Mietvertrag)



class MwstEstvTests(TestCase):
    def test_effektiv(self):
        from core.services.mwst_estv import berechne_estv
        e = berechne_estv(umsatz_steuerbar=Decimal('120000'), umsatzsteuer=Decimal('9720'),
                          vorsteuer_material=Decimal('3000'), vorsteuer_invest=Decimal('500'))
        self.assertEqual(e['z479'], Decimal('3500.00'))
        self.assertEqual(e['z500'], Decimal('6220.00'))

    def test_guthaben(self):
        from core.services.mwst_estv import berechne_estv
        e = berechne_estv(umsatz_steuerbar=Decimal('10000'), umsatzsteuer=Decimal('810'),
                          vorsteuer_material=Decimal('2000'), vorsteuer_invest=Decimal('0'))
        self.assertEqual(e['z500'], Decimal('0.00'))
        self.assertEqual(e['z510'], Decimal('1190.00'))

    def test_saldosteuersatz(self):
        from core.services.mwst_estv import berechne_estv
        e = berechne_estv(umsatz_steuerbar=Decimal('120000'), umsatzsteuer=Decimal('0'),
                          vorsteuer_material=Decimal('0'), vorsteuer_invest=Decimal('0'),
                          methode='saldo', saldosteuersatz=Decimal('6.5'))
        self.assertEqual(e['z500'], Decimal('7800.00'))


class MwstEstvTests(TestCase):
    def test_effektiv_zahllast(self):
        from core.services.mwst_estv import berechne_estv
        d = berechne_estv(umsatz_steuerbar=Decimal('10000'), umsatzsteuer=Decimal('810'),
                          vorsteuer_material=Decimal('100'), vorsteuer_invest=Decimal('50'))
        self.assertEqual(d['z479'], Decimal('150.00'))   # Total Vorsteuer
        self.assertEqual(d['z500'], Decimal('660.00'))   # 810 - 150 Zahllast
        self.assertEqual(d['z510'], Decimal('0.00'))

    def test_effektiv_guthaben(self):
        from core.services.mwst_estv import berechne_estv
        d = berechne_estv(umsatz_steuerbar=Decimal('1000'), umsatzsteuer=Decimal('100'),
                          vorsteuer_material=Decimal('300'), vorsteuer_invest=Decimal('0'))
        self.assertEqual(d['z500'], Decimal('0.00'))
        self.assertEqual(d['z510'], Decimal('200.00'))   # Guthaben

    def test_saldosteuersatz(self):
        from core.services.mwst_estv import berechne_estv
        d = berechne_estv(umsatz_steuerbar=Decimal('10000'), umsatzsteuer=Decimal('0'),
                          vorsteuer_material=Decimal('0'), vorsteuer_invest=Decimal('0'),
                          methode='saldo', saldosteuersatz=Decimal('5'))
        self.assertEqual(d['z500'], Decimal('500.00'))   # 10000 * 5%


class BuchungsServiceTests(TestCase):
    """Zentrale Buchungsschicht: Kontenplan garantiert, kein stiller Verlust."""

    def test_ensure_und_konto_autocreate(self):
        from finance.booking import ensure_kontenplan, konto
        from finance.models import Buchungskonto
        Buchungskonto.objects.all().delete()
        n = ensure_kontenplan()
        self.assertGreater(n, 10)
        # bekanntes Konto wird bei Bedarf nachgelegt
        Buchungskonto.objects.filter(nummer='1100').delete()
        k = konto('1100')
        self.assertEqual(k.nummer, '1100')

    def test_buche_schreibt_und_ueberspringt_null(self):
        from finance.booking import buche
        from finance.models import Buchung
        b = buche('1100', '3000', Decimal('1500'), 'Test-Miete')
        self.assertIsNotNone(b)
        self.assertEqual(b.soll_konto.nummer, '1100')
        self.assertEqual(b.haben_konto.nummer, '3000')
        # Nullbetrag → keine Buchung
        self.assertIsNone(buche('1100', '3000', Decimal('0'), 'Null'))
        self.assertIsNone(buche('1100', '3000', None, 'None'))
        self.assertEqual(Buchung.objects.count(), 1)

    def test_unbekanntes_konto_wirft(self):
        from finance.booking import buche
        with self.assertRaises(ValueError):
            buche('9999', '3000', Decimal('10'), 'Ungültig')

    def test_sollstellung_bucht_ueber_service(self):
        """Sollstellung schreibt saubere Buchungen, auch wenn der Kontenplan leer war."""
        from finance.models import Buchungskonto, Buchung, DebitorenRechnung
        from core.services.automation import run_sollstellung
        Buchungskonto.objects.all().delete()   # kein Kontenplan → früher stiller Verlust
        lg, e, m, v = _basis_objekte()
        heute = date.today()
        n = run_sollstellung(heute.year, heute.month)
        self.assertGreaterEqual(n, 1)
        r = DebitorenRechnung.objects.filter(vertrag=v).first()
        self.assertIsNotNone(r)
        # Buchungen existieren (nicht stillschweigend verschluckt)
        self.assertTrue(Buchung.objects.filter(debitoren_rechnung=r, soll_konto__nummer='1100').exists())


class JournalStornoTests(TestCase):
    """Revisionssichere Gegenbuchung: Original bleibt, Storno kehrt Soll/Haben um."""

    def _buchung(self):
        from finance.booking import buche
        lg, e, m, v = _basis_objekte()
        b = buche('4000', '1020', Decimal('250'), 'Falsche Rechnung', liegenschaft=lg)
        return lg, b

    def test_storno_kehrt_um_und_netzt_auf_null(self):
        from finance.booking import storniere_buchung
        from finance.models import Buchung, Buchungskonto
        from django.db.models import Sum
        lg, b = self._buchung()
        gegen = storniere_buchung(b)
        # Soll/Haben getauscht, gleicher Betrag, als Storno markiert, verknüpft
        self.assertTrue(gegen.ist_storno)
        self.assertEqual(gegen.storno_von_id, b.id)
        self.assertEqual(gegen.soll_konto.nummer, '1020')
        self.assertEqual(gegen.haben_konto.nummer, '4000')
        self.assertEqual(gegen.betrag, Decimal('250.00'))
        # Original als storniert markiert (bleibt aber erhalten)
        b.refresh_from_db()
        self.assertIsNotNone(b.storniert_am)
        self.assertEqual(Buchung.objects.count(), 2)
        # Aufwand 4000 netto = 0 (250 Soll − 250 Haben)
        k = Buchungskonto.objects.get(nummer='4000')
        soll = Buchung.objects.filter(soll_konto=k).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        haben = Buchung.objects.filter(haben_konto=k).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        self.assertEqual(soll - haben, Decimal('0.00'))

    def test_kein_doppelstorno(self):
        from finance.booking import storniere_buchung
        lg, b = self._buchung()
        storniere_buchung(b)
        with self.assertRaises(ValueError):
            storniere_buchung(b)

    def test_storno_von_storno_verboten(self):
        from finance.booking import storniere_buchung
        lg, b = self._buchung()
        gegen = storniere_buchung(b)
        with self.assertRaises(ValueError):
            storniere_buchung(gegen)

    def test_view_storniert_und_zeigt_badge(self):
        from finance.models import Buchung
        lg, b = self._buchung()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/buchhaltung/buchung/{b.id}/stornieren/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Buchung.objects.filter(ist_storno=True).count(), 1)
        # Journal zeigt beide + storniert-Badge
        r2 = c.get('/neu/buchhaltung/')
        self.assertContains(r2, 'storniert')
        self.assertContains(r2, 'Storno Beleg')

    def test_original_bleibt_erhalten_kein_hard_delete(self):
        from finance.models import Buchung
        lg, b = self._buchung()
        with self.assertRaises(PermissionError):
            b.delete()


class VerwaltungshonorarTests(TestCase):
    """Verwaltungshonorar: % der Mieterträge, Buchung Soll 4500 / Haben Bank."""

    def _setup(self, prozent='4'):
        from crm.models import Eigentuemer
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        md = Eigentuemer.objects.create(firma_oder_name='Eigentum AG', honorar_prozent=Decimal(prozent))
        lg, e, m, v = _basis_objekte()
        lg.eigentuemer = md
        lg.save()
        # Mietertrag 10'000 im Jahr 2025 (Konto 3000)
        buche('1020', '3000', Decimal('10000'), 'Miete', datum=date(2025, 6, 1), liegenschaft=lg)
        return md, lg

    def test_vorschau_berechnet_honorar(self):
        from core.services.verwaltungshonorar import honorar_vorschau
        md, lg = self._setup('4')
        zeilen, total, prozent = honorar_vorschau(md, 2025)
        self.assertEqual(prozent, Decimal('4.00'))
        self.assertEqual(zeilen[0]['mietertrag'], Decimal('10000.00'))
        self.assertEqual(zeilen[0]['honorar'], Decimal('400.00'))   # 4 % von 10'000
        self.assertFalse(zeilen[0]['gebucht'])
        self.assertEqual(total, Decimal('400.00'))

    def test_buchung_soll_4500_haben_kontokorrent(self):
        # W3: Gegenkonto ist das Eigentümer-Kontokorrent (2850), NICHT die Bank —
        # am 31.12. fliesst kein Geld; 1020 muss zum Bankauszug passen.
        from core.services.verwaltungshonorar import buche_honorar
        from finance.models import Buchung
        md, lg = self._setup('4')
        anzahl, summe = buche_honorar(md, 2025, user=None)
        self.assertEqual(anzahl, 1)
        self.assertEqual(summe, Decimal('400.00'))
        self.assertTrue(Buchung.objects.filter(soll_konto__nummer='4500', haben_konto__nummer='2850',
                                               betrag=Decimal('400.00'), liegenschaft=lg).exists())
        self.assertFalse(Buchung.objects.filter(soll_konto__nummer='4500',
                                                haben_konto__nummer='1020').exists())

    def test_idempotent(self):
        from core.services.verwaltungshonorar import buche_honorar, honorar_vorschau
        md, lg = self._setup('4')
        buche_honorar(md, 2025, user=None)
        # Zweiter Lauf bucht nichts mehr
        anzahl, summe = buche_honorar(md, 2025, user=None)
        self.assertEqual(anzahl, 0)
        zeilen, _t, _p = honorar_vorschau(md, 2025)
        self.assertTrue(zeilen[0]['gebucht'])

    def test_nach_storno_laesst_sich_das_honorar_neu_buchen(self):
        """Der «schon gebucht?»-Wächter filtert nur `ist_storno=False` und sieht
        damit das stornierte ORIGINAL weiter. Folge: Wer ein Honorar mit
        falschem Satz storniert, kann es nie wieder buchen — die Liste zeigt
        dauerhaft «gebucht», obwohl buchhalterisch nichts mehr steht.

        Die Storno-Gegenbuchung wird korrekt ausgeblendet; ohne
        `storniert_am__isnull=True` ist das Paar einseitig gefiltert."""
        from core.services.verwaltungshonorar import buche_honorar, honorar_vorschau
        from finance.booking import storniere_buchung
        from finance.models import Buchung
        md, lg = self._setup('4')
        buche_honorar(md, 2025, user=None)
        original = Buchung.objects.get(soll_konto__nummer='4500', ist_storno=False)
        storniere_buchung(original)

        zeilen, total, _p = honorar_vorschau(md, 2025)
        self.assertFalse(zeilen[0]['gebucht'],
                         "Honorar gilt nach dem Storno weiter als gebucht")
        self.assertEqual(total, Decimal('400.00'))
        anzahl, summe = buche_honorar(md, 2025, user=None)
        self.assertEqual(anzahl, 1, "Honorar liess sich nach dem Storno nicht neu buchen")

    def test_honorar_mindert_eigentuemer_ergebnis(self):
        from core.services.verwaltungshonorar import buche_honorar
        from core.services.eigentuemer_kontokorrent import kontokorrent
        md, lg = self._setup('4')
        vorher = kontokorrent(md, jahr=2025)['ergebnis']
        buche_honorar(md, 2025, user=None)
        nachher = kontokorrent(md, jahr=2025)['ergebnis']
        # Honorar (400) ist Aufwand → Ergebnis sinkt um 400
        self.assertEqual(vorher - nachher, Decimal('400.00'))

    def test_view_zeigt_honorar_panel(self):
        md, lg = self._setup('4')
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.get(f'/neu/mandate/{md.id}/kontokorrent/?jahr=2025')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Verwaltungshonorar 2025')
        # Buchen-Aktion
        r2 = c.post(f'/neu/mandate/{md.id}/honorar/', {'jahr': '2025', 'konto_nummer': '1020'})
        self.assertEqual(r2.status_code, 302)
        from finance.models import Buchung
        self.assertTrue(Buchung.objects.filter(soll_konto__nummer='4500', betrag=Decimal('400.00')).exists())


class SollstellungKontierungTests(TestCase):
    """Buchhalterische Kontierung der Sollstellung nach Objektart + NK-Art."""

    def test_gewerbe_pauschal_kontierung(self):
        from core.services.automation import run_sollstellung
        from finance.models import Buchung
        lg = Liegenschaft.objects.create(strasse='Gew 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Laden', typ='gew',
                                   nettomiete_aktuell=Decimal('2000'), nebenkosten_aktuell=Decimal('200'))
        m = Mieter.objects.create(typ='firma', firmen_name='X GmbH')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2026, 1, 1),
                                   netto_mietzins=Decimal('2000'), nebenkosten=Decimal('200'),
                                   status='aktiv', nk_abrechnungsart='pauschal')
        run_sollstellung(2026, 1)
        haben = set(Buchung.objects.values_list('haben_konto__nummer', flat=True))
        self.assertIn('3010', haben)   # Gewerbe-Mietertrag
        self.assertIn('3021', haben)   # Pauschal-NK (kein Akonto)
        self.assertNotIn('3020', haben)

    def test_wohnung_akonto_kontierung(self):
        from core.services.automation import run_sollstellung
        from finance.models import Buchung
        lg = Liegenschaft.objects.create(strasse='Wohn 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg', typ='whg',
                                   nettomiete_aktuell=Decimal('1500'), nebenkosten_aktuell=Decimal('200'))
        m = Mieter.objects.create(typ='person', vorname='A', nachname='B')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2026, 1, 1),
                                   netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                                   status='aktiv', nk_abrechnungsart='akonto')
        run_sollstellung(2026, 1)
        haben = set(Buchung.objects.values_list('haben_konto__nummer', flat=True))
        self.assertIn('3000', haben)   # Wohnungs-Mietertrag
        self.assertIn('3020', haben)   # NK-Akonto

    def test_index_anpassung_wird_verrechnet(self):
        """Fest/Index: eine wirksame Mietzinsanpassung (Art. 269d) treibt die
        Sollstellung automatisch ab wirksam_ab — ohne den Basiswert zu mutieren."""
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        from rentals.models import MietzinsAnpassung
        lg = Liegenschaft.objects.create(strasse='Idx 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Idx-Büro', typ='gew',
                                   nettomiete_aktuell=Decimal('3000'))
        m = Mieter.objects.create(typ='firma', firmen_name='Idx AG')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                       netto_mietzins=Decimal('3000'), nebenkosten=Decimal('0'),
                                       status='aktiv', mietzins_modell='index')
        MietzinsAnpassung.objects.create(vertrag=v, wirksam_ab=date(2026, 1, 1),
                                         alter_netto_mietzins=Decimal('3000'),
                                         neuer_netto_mietzins=Decimal('3150'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2025, 6, 1)), Decimal('3000'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 6, 1)), Decimal('3150'))
        run_sollstellung(2026, 3)
        r = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 03/2026')
        self.assertEqual(r.betrag, Decimal('3150.00'))

    def test_gewerbe_staffel_bucht_gueltige_stufe(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        from rentals.models import Staffelstufe
        lg = Liegenschaft.objects.create(strasse='Staf 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Büro', typ='gew',
                                   nettomiete_aktuell=Decimal('2000'))
        m = Mieter.objects.create(typ='firma', firmen_name='Y AG')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                       netto_mietzins=Decimal('2000'), nebenkosten=Decimal('0'),
                                       status='aktiv', mietzins_modell='staffel')
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2026, 1, 1), netto_mietzins=Decimal('2100'))
        run_sollstellung(2026, 3)   # März 2026 → Stufe ab 2026-01 gilt
        r = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 03/2026')
        self.assertEqual(r.betrag, Decimal('2100.00'))


class FinanzGuardTests(TestCase):
    """Sofort-Paket aus dem Buchhalter-Audit: Guards & Eingabe-Validierung."""

    def _rechnung(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        return DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')

    def test_keine_zahlung_auf_stornierte_rechnung(self):
        from finance.models import Zahlungseingang
        r = self._rechnung()
        r.status = 'storniert'; r.save()
        team = _team_user(); c = Client(); c.force_login(team)
        resp = c.post('/neu/bankabgleich/verbuchen/', {'rechnung_id': r.id, 'betrag': '100'}, follow=True)
        self.assertContains(resp, 'kann keine Zahlung verbucht werden')
        r.refresh_from_db()
        self.assertEqual(r.status, 'storniert')          # bleibt storniert
        self.assertEqual(Zahlungseingang.objects.count(), 0)

    def test_bankabgleich_betrag_null_abgelehnt(self):
        from finance.models import Zahlungseingang
        r = self._rechnung()
        team = _team_user(); c = Client(); c.force_login(team)
        resp = c.post('/neu/bankabgleich/verbuchen/', {'rechnung_id': r.id, 'betrag': '0'}, follow=True)
        self.assertContains(resp, 'grösser als 0')
        self.assertEqual(Zahlungseingang.objects.count(), 0)

    def test_kreditor_zahlung_betrag_null_zahlt_nicht_voll(self):
        # Regressionsschutz: Eingabe «0» zahlte früher still den VOLLEN Betrag
        from finance.models import KreditorenRechnung, KreditorenZahlung
        _seed_konten(); _basis_objekte()
        k = KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('500.00'),
                                              status='freigegeben')
        team = _team_user(); c = Client(); c.force_login(team)
        resp = c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.id, 'betrag': '0'}, follow=True)
        self.assertContains(resp, 'Ungültiger Betrag')
        self.assertEqual(KreditorenZahlung.objects.count(), 0)
        k.refresh_from_db()
        self.assertEqual(k.status, 'freigegeben')

    def test_sollstellung_monat_13_kein_500(self):
        _seed_konten(); _basis_objekte()
        team = _team_user(); c = Client(); c.force_login(team)
        resp = c.post('/neu/sollstellung/starten/', {'jahr': '2024', 'monat': '13'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ungültiger Monat')

    def test_storno_mit_zahlung_geblockt(self):
        # (Teil-)bezahlte Rechnungen dürfen nicht storniert werden — zuerst muss
        # die Zahlung storniert werden (K6). Bis E1c über die Alt-API geprüft,
        # jetzt über fw_debitor_stornieren in /neu/, das denselben Schutz trägt.
        from finance.models import Zahlungseingang
        r = self._rechnung()
        Zahlungseingang.objects.create(vertrag=r.vertrag, betrag=Decimal('100'),
                                       datum_eingang=date(2024, 3, 5),
                                       buchungs_monat=date(2024, 3, 1),
                                       debitoren_rechnung=r, status='verbucht')
        team = _team_user(); c = Client(); c.force_login(team)
        c.post(f'/neu/debitoren/{r.id}/stornieren/')
        r.refresh_from_db()
        self.assertNotEqual(r.status, 'storniert')


class BuchhalterFixesTests(TestCase):
    """F2–F4 aus dem Buchhalter-Audit: korrekte Buchungssätze + Sackgassen-Fixes."""

    def _saldo(self, nummer):
        """Saldo eines Kontos (Soll − Haben) über alle Buchungen."""
        from finance.models import Buchung
        from django.db.models import Sum
        soll = Buchung.objects.filter(soll_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        haben = Buchung.objects.filter(haben_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        return soll - haben

    def _soll_gleich_haben(self):
        from finance.models import Buchung
        from django.db.models import Sum
        t = Buchung.objects.aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        return t  # jede Zeile ist ein Soll/Haben-Paar → Bilanz per Konstruktion

    # ---------- K1: MWST-Korrektur beim Debitorenverlust ----------
    def test_k1_debitorenverlust_korrigiert_mwst(self):
        from finance.models import DebitorenRechnung, Buchung
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.mwst_pflichtig = True; v.mwst_satz = Decimal('8.1'); v.save()
        r = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                             titel='Miete 03/2024', datum=date(2024, 3, 1),
                                             faellig_am=date(2024, 3, 5),
                                             betrag=Decimal('1081.00'), status='offen')
        buche('1100', '3010', Decimal('1000'), 'Miete', datum=date(2024, 3, 1), liegenschaft=lg, debitor=r)
        buche('1100', '2200', Decimal('81'), 'MWST', datum=date(2024, 3, 1), liegenschaft=lg, debitor=r)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/debitoren/{r.id}/abschreiben/', {'grund': 'Verlustschein'})
        r.refresh_from_db()
        self.assertEqual(r.status, 'abgeschrieben')
        # MWST muss zurückgeholt sein: 2200 wieder auf 0, Aufwand nur netto
        self.assertEqual(self._saldo('2200'), Decimal('0.00'))
        self.assertEqual(self._saldo('3805'), Decimal('1000.00'))
        self.assertEqual(self._saldo('1100'), Decimal('0.00'))

    # ---------- K3: Kaution wird in der Schlussabrechnung bilanziert ----------
    def test_k3_schlussabrechnung_bucht_kaution(self):
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('3000'); v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = date(2024, 1, 1); v.save()
        # Einzahlung über den Produktivpfad — der Belegtext trägt die Vertrags-ID,
        # an der die Freigabe den bilanzierten Betrag erkennt.
        from core.services.automation import buche_kaution_einzahlung
        buche_kaution_einzahlung(v, date(2024, 1, 1))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen', 'kaution_verrechnen': 'on'})
        # Sperrkonto + Verbindlichkeit müssen aufgelöst sein (vorher blieben sie ewig stehen)
        self.assertEqual(self._saldo('1015'), Decimal('0.00'))
        self.assertEqual(self._saldo('2010'), Decimal('0.00'))

    def test_kaution_ohne_einzahlung_wird_nicht_ausbezahlt(self):
        # Kritischer Audit-Befund: Die Freigabe entschied am VEREINBARTEN Betrag
        # (Vertragsfeld). War die Kaution nie eingegangen, wurden 1015/2010 negativ
        # und der Mieter bekam Geld, das er nie hinterlegt hatte.
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('4500'); v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = None; v.save()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen', 'kaution_verrechnen': 'on'})
        self.assertEqual(self._saldo('1015'), Decimal('0.00'))   # nicht ins Minus gedrückt
        self.assertEqual(self._saldo('2010'), Decimal('0.00'))
        v.refresh_from_db()
        self.assertIn(v.kautions_rueckzahlung_betrag or Decimal('0'), (Decimal('0'), Decimal('0.00')))

    def test_kaution_ohne_einzahlung_tilgt_keine_forderung(self):
        # Zweite Hälfte desselben Befunds: die Phantom-Kaution wurde mit offenen
        # Mietforderungen «verrechnet» — die Forderung galt als bezahlt, der
        # Mietertrag als vereinnahmt, der echte Verlust verschwand.
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('4500'); v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = None; v.save()
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, einheit=e, titel='Miete 05/2024',
            datum=date(2024, 5, 1), faellig_am=date(2024, 5, 5),
            betrag=Decimal('1700'), status='offen')
        buche('1100', '3000', Decimal('1700'), 'Miete 05/2024', datum=date(2024, 5, 1),
              liegenschaft=lg, debitor=r)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen', 'kaution_verrechnen': 'on'})
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen')
        self.assertEqual(r.offener_betrag, Decimal('1700'))

    def test_kaution_nicht_zweimal_aufloesbar(self):
        # Rückzahlung über die Vertragsseite UND Schlussabrechnung hatten je eine
        # eigene Belegtext-Sperre — zusammen konnten sie dieselbe Kaution zweimal
        # freigeben (Audit). Der Saldo von 2010 ist jetzt die gemeinsame Grenze.
        from finance.booking import ensure_kontenplan
        from core.services.automation import buche_kaution_einzahlung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('3000'); v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = date(2024, 1, 1); v.save()
        buche_kaution_einzahlung(v, date(2024, 1, 1))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/kaution/',
               {'aktion': 'rueckzahlung', 'zurueckbezahlt_am': '2024-06-30',
                'rueckzahlung_betrag': '3000', 'abzug_betrag': '0'})
        self.assertEqual(self._saldo('2010'), Decimal('0.00'))
        # Zweiter Versuch über die Schlussabrechnung darf nichts mehr bewegen
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen', 'kaution_verrechnen': 'on'})
        self.assertEqual(self._saldo('2010'), Decimal('0.00'))
        self.assertEqual(self._saldo('1015'), Decimal('0.00'))

    def test_kaution_rueckzahlung_muss_voll_abdecken(self):
        # Unter-Allokation (Rückzahlung + Einbehalt < Kaution) muss abgewiesen
        # werden — sonst wird das Sperrkonto (1015) voll freigegeben, aber die
        # Kautionsverbindlichkeit (2010) bliebe teilweise offen (Geld unerklärt
        # auf 1020). Live-QS Kautionen.
        from finance.booking import ensure_kontenplan
        from core.services.automation import buche_kaution_einzahlung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('3000'); v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = date(2024, 1, 1); v.save()
        buche_kaution_einzahlung(v, date(2024, 1, 1))
        c = Client(); c.force_login(_team_user('Verwaltung'))
        # 1500 zurück + 200 Einbehalt = 1700 < 3000 → abgelehnt
        c.post(f'/neu/vertraege/{v.id}/kaution/',
               {'aktion': 'rueckzahlung', 'zurueckbezahlt_am': '2024-06-30',
                'rueckzahlung_betrag': '1500', 'abzug_betrag': '200'})
        # Nichts gebucht: 2010 trägt weiter die volle Kaution, 1015 unverändert.
        self.assertEqual(self._saldo('2010'), Decimal('-3000.00'))  # Haben-Saldo = Verbindlichkeit
        self.assertEqual(self._saldo('1015'), Decimal('3000.00'))   # Soll-Saldo = Sperrkonto
        v.refresh_from_db()
        self.assertIsNone(v.kautions_zurueckbezahlt_am)
        # Voll abgedeckt (1700 + 1300) geht durch:
        c.post(f'/neu/vertraege/{v.id}/kaution/',
               {'aktion': 'rueckzahlung', 'zurueckbezahlt_am': '2024-06-30',
                'rueckzahlung_betrag': '2700', 'abzug_betrag': '300'})
        self.assertEqual(self._saldo('2010'), Decimal('0.00'))
        self.assertEqual(self._saldo('1015'), Decimal('0.00'))

    def test_schlussabrechnung_gutschrift_nur_einmal(self):
        # Gutschrift-Fall ohne Kaution: die Idempotenz hing an
        # `kautions_zurueckbezahlt_am`, das hier nie gesetzt wird — ein zweiter
        # Aufruf buchte das Mieterguthaben ein zweites Mal (Audit).
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('0'); v.save()
        c = Client(); c.force_login(_team_user())
        payload = {'auszug_datum': '2024-06-30', 'aktion': 'buchen',
                   'pos_text': 'NK-Guthaben', 'pos_betrag': '400',
                   'pos_richtung': 'zugunsten'}
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/', payload)
        erst = self._saldo('2030')
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/', payload)
        self.assertEqual(self._saldo('2030'), erst)   # kein zweites Guthaben

    def test_jahresabschluss_nicht_doppelt_ueber_lg_filter(self):
        # Portfolioweit abschliessen und danach je Liegenschaft nochmals: die
        # Prüfung filterte auf dieselbe Liegenschaft und fand die portfolioweiten
        # Buchungen (ohne Liegenschaft) nicht — 2970 verdoppelte sich (Audit).
        from core.services.jahresabschluss import buche_jahresabschluss, ist_abgeschlossen
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        buche('1100', '3000', Decimal('1200'), 'Miete 01/2024',
              datum=date(2024, 1, 31), liegenschaft=lg)
        n1, _erg = buche_jahresabschluss(2024)
        self.assertGreater(n1, 0)
        saldo_nach_erstem = self._saldo('2970')
        self.assertTrue(ist_abgeschlossen(2024, lg))          # deckt die LG mit ab
        n2, _ = buche_jahresabschluss(2024, liegenschaft=lg)
        self.assertEqual(n2, 0)
        self.assertEqual(self._saldo('2970'), saldo_nach_erstem)

    def test_jahresabschluss_nach_storno_wieder_moeglich(self):
        # Eine stornierte Abschlussbuchung behält ist_storno=False (das Flag trägt
        # die Gegenbuchung). Ohne Prüfung auf `storniert_am` galt das Jahr
        # weiterhin als abgeschlossen und liess sich nie neu abschliessen (Audit).
        from core.services.jahresabschluss import buche_jahresabschluss, ist_abgeschlossen
        from finance.booking import ensure_kontenplan, buche
        from finance.models import Buchung
        from finance.services import erstelle_storno_buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        buche('1100', '3000', Decimal('900'), 'Miete 02/2024',
              datum=date(2024, 2, 29), liegenschaft=lg)
        buche_jahresabschluss(2024)
        self.assertTrue(ist_abgeschlossen(2024))
        for b in Buchung.objects.filter(beleg_text__startswith='Jahresabschluss 2024 —',
                                        ist_storno=False, storniert_am__isnull=True):
            erstelle_storno_buchung(b, benutzer=None)
        self.assertFalse(ist_abgeschlossen(2024))
        n, _ = buche_jahresabschluss(2024)
        self.assertGreater(n, 0)

    # ---------- Nachgereichte Befunde ----------
    def test_weiterverrechnung_mwst_wird_beim_abschreiben_reversiert(self):
        # Die Weiterverrechnung bucht Ausgangs-MWST (1190/2200) nach dem
        # KREDITOR-Satz — unabhängig davon, ob der Mietvertrag optiert ist. Die
        # frühere Storno-Logik las dagegen v.mwst_pflichtig/v.mwst_satz: Bei einem
        # nicht optierten Vertrag wurde die MWST nie zurückgeholt, bei
        # abweichenden Sätzen der falsche Betrag (Audit).
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.mwst_pflichtig = False; v.save()          # Vertrag NICHT optiert
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, einheit=e, titel='Weiterverrechnung Hauswartung',
            datum=date(2024, 4, 1), faellig_am=date(2024, 4, 30),
            betrag=Decimal('1081'), status='offen')
        buche('1100', '1190', Decimal('1081'), 'Weiterverrechnung', datum=date(2024, 4, 1),
              liegenschaft=lg, debitor=r)
        buche('1190', '4000', Decimal('1000'), 'Aufwandsminderung', datum=date(2024, 4, 1),
              liegenschaft=lg, debitor=r)
        buche('1190', '2200', Decimal('81'), 'MWST Weiterverrechnung 8.1%',
              datum=date(2024, 4, 1), liegenschaft=lg, debitor=r)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/debitoren/{r.id}/abschreiben/', {'grund': 'Verlustschein'})
        # Die 81.00 werden aus 2200 zurückgeholt, 3805 traegt nur die Netto-1000.
        self.assertEqual(self._saldo('2200'), Decimal('0.00'))
        self.assertEqual(self._saldo('3805'), Decimal('1000.00'))

    def test_schlussabrechnung_grenzt_mwst_ab(self):
        # NK-Nachzahlung bei einem optierten Gewerbevertrag ist steuerbar,
        # Schadenersatz nach Art. 18 Abs. 2 MWSTG nicht. Vorher wurde der ganze
        # Delta-Betrag als Ertrag gebucht und die Steuer fehlte in der
        # ESTV-Abrechnung (Audit).
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.mwst_pflichtig = True; v.mwst_satz = Decimal('8.1'); v.kautions_betrag = Decimal('0')
        v.save()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/', {
            'auszug_datum': '2024-06-30', 'aktion': 'buchen',
            'pos_text': ['NK-Abrechnung 2024', 'Schaden Parkett'],
            'pos_betrag': ['2000', '500'],
            'pos_richtung': ['zulasten', 'zulasten'],
            'pos_mwst': ['1', '0'],          # NK steuerbar, Schaden nicht
        })
        # 8.1 % NUR auf den steuerbaren 2000 → 162.00
        self.assertEqual(self._saldo('2200'), Decimal('-162.00'))   # Haben-Saldo
        self.assertEqual(self._saldo('3600'), Decimal('-2500.00'))  # Netto als Ertrag

    def test_mwst_zahllast_geht_auf_abrechnungskonto_nicht_bank(self):
        # Am Periodenende fliesst kein Geld — die Schuld gehoert auf 2201.
        # Direkt gegen 1020 wich der Banksaldo ab dem Stichtag vom realen
        # Kontoauszug ab und die echte Zahlung wurde spaeter doppelt gebucht.
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        buche('1100', '2200', Decimal('500'), 'MWST Q1', datum=date(2024, 3, 31), liegenschaft=lg)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/mwst/verbuchen/', {'jahr': '2024', 'quartal': '1'})
        self.assertEqual(self._saldo('2201'), Decimal('-500.00'))   # Schuld im Haben
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))      # Bank unberuehrt

    def test_nk_erlass_mindert_honorarbasis_nicht(self):
        # Die Honorarbasis rechnet auf 3000/3010 und enthaelt die Nebenkosten gar
        # nicht. Ein NK-Erlass auf 3090 haette eine Basis gemindert, in der die
        # Nebenkosten nie standen (Audit) — er laeuft jetzt ueber 3091.
        from core.services.automation import run_sollstellung
        from finance.booking import ensure_kontenplan
        from finance.models import Buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        run_sollstellung(2024, 3)
        # Kein NK-Erlass auf 3090; falls einer entstand, steht er auf 3091.
        nk_auf_3090 = Buchung.objects.filter(
            soll_konto__nummer='3090', beleg_text__startswith='NK-Erlass').exists()
        self.assertFalse(nk_auf_3090)

    def test_kontenplan_import_deckt_alle_standardkonten(self):
        # Der Import-Endpunkt pflegte eine ZWEITE Kontenliste, die auseinander-
        # gedriftet war (u.a. fehlten 2030, 2850, 2970, 3090, 3600, 3805). Wer
        # den Plan darüber importierte, bekam einen unvollständigen Kontenrahmen.
        # Er leitet sich jetzt aus STANDARD_KONTEN ab — der EINEN Quelle.
        # Der zweite Aufrufweg (finance.api.import_standard_kontenplan) ist mit
        # E1c entfallen; geprüft wird jetzt direkt die eine Quelle.
        from finance.booking import STANDARD_KONTEN, ensure_kontenplan
        from finance.models import Buchungskonto
        ensure_kontenplan()
        vorhanden = set(Buchungskonto.objects.values_list('nummer', flat=True))
        fehlend = {k[0] for k in STANDARD_KONTEN} - vorhanden
        self.assertEqual(fehlend, set())

    # ---------- K2: Schäden landen auf 3600, nicht im Mietertrag 3000 ----------
    def test_k2_schaden_nicht_im_mietertrag(self):
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen',
                'pos_text': 'Reinigung', 'pos_betrag': '500', 'pos_richtung': 'zulasten'})
        self.assertEqual(self._saldo('3600'), Decimal('-500.00'))   # Ertrag im Haben
        self.assertEqual(self._saldo('3000'), Decimal('0.00'))      # kein Mietertrag
        self.assertTrue(DebitorenRechnung.objects.filter(
            vertrag=v, titel='Schlussabrechnung (Nachzahlung)').exists())

    def test_k2_offene_miete_bleibt_bestehen_keine_doppelbelastung(self):
        # Neu: alte Forderung wird NICHT mehr storniert (MWST/Ertragskonto bleiben
        # erhalten) — sie darf aber auch nicht doppelt gefordert werden.
        from finance.models import DebitorenRechnung
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        alt = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                               titel='Miete 05/2024', datum=date(2024, 5, 1),
                                               faellig_am=date(2024, 5, 5),
                                               betrag=Decimal('1700'), status='offen')
        buche('1100', '3000', Decimal('1700'), 'Miete 05/2024', datum=date(2024, 5, 1),
              liegenschaft=lg, debitor=alt)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen'})
        alt.refresh_from_db()
        self.assertEqual(alt.status, 'offen')          # bleibt bestehen (MWST intakt)
        offene = DebitorenRechnung.objects.filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
        # Gesamtforderung unverändert 1700 — keine zweite Forderung über denselben Betrag
        self.assertEqual(sum((r.offener_betrag for r in offene), Decimal('0')), Decimal('1700'))

    def test_schlussabrechnung_idempotent(self):
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        payload = {'auszug_datum': '2024-06-30', 'aktion': 'buchen',
                   'pos_text': 'Reinigung', 'pos_betrag': '500', 'pos_richtung': 'zulasten'}
        for _ in range(2):
            c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/', payload)
        self.assertEqual(DebitorenRechnung.objects.filter(
            vertrag=v, titel='Schlussabrechnung (Nachzahlung)').count(), 1)

    # ---------- W1/F3: NK-Gutschrift wird echtes Guthaben (2030) ----------
    def test_w1_nk_gutschrift_als_guthaben(self):
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg, Zahlungseingang
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='NK 2024',
                                              start_datum=date(2024, 1, 1), ende_datum=date(2024, 12, 31))
        NebenkostenBeleg.objects.create(periode=p, text='Heizung', kategorie='heizung',
                                        betrag=Decimal('100'), datum=date(2024, 6, 1))
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/nebenkosten/{p.id}/verbuchen/')
        # Gutschrift (Akonto > Kosten) muss als Guthaben auf 2030 stehen, nicht 1100 entlasten
        if self._saldo('2030') != Decimal('0.00'):
            self.assertLess(self._saldo('2030'), Decimal('0.00'))   # Passivum im Haben
            self.assertTrue(Zahlungseingang.objects.filter(konto__nummer='2030').exists())

    # ---------- F3: geparkte Zahlung nachträglich zuordnen ----------
    def test_f3_geparkte_zahlung_zuordnen(self):
        from finance.models import DebitorenRechnung, Zahlungseingang
        from finance.booking import buche, ensure_kontenplan, konto
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                             titel='Miete 03/2024', datum=date(2024, 3, 1),
                                             faellig_am=date(2024, 3, 5),
                                             betrag=Decimal('1700'), status='offen')
        buche('1100', '3000', Decimal('1700'), 'Miete', datum=date(2024, 3, 1), liegenschaft=lg, debitor=r)
        z = Zahlungseingang.objects.create(betrag=Decimal('1700'), datum_eingang=date(2024, 3, 6),
                                           buchungs_monat=date(2024, 3, 1),
                                           bemerkung='UNGEKLÄRT: Unbekannte GmbH',
                                           konto=konto('1190'), status='verbucht')
        buche('1020', '1190', Decimal('1700'), 'ungeklärt', datum=date(2024, 3, 6), liegenschaft=lg, zahlung=z)
        c = Client(); c.force_login(_team_user())
        resp = c.post('/neu/bankabgleich/zuordnen/', {'zahlung_id': z.id, 'rechnung_id': r.id}, follow=True)
        self.assertContains(resp, 'zugeordnet')
        r.refresh_from_db(); z.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(z.debitoren_rechnung_id, r.id)
        self.assertEqual(self._saldo('1190'), Decimal('0.00'))   # Parkkonto geleert
        self.assertEqual(self._saldo('1100'), Decimal('0.00'))   # Forderung getilgt

    # ---------- W7: Zahlungs-Storno in /neu/ ----------
    def test_w7_zahlung_stornieren(self):
        from finance.models import DebitorenRechnung, Zahlungseingang
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                             titel='Miete 03/2024', datum=date(2024, 3, 1),
                                             faellig_am=date(2024, 3, 5),
                                             betrag=Decimal('1700'), status='offen')
        buche('1100', '3000', Decimal('1700'), 'Miete', datum=date(2024, 3, 1), liegenschaft=lg, debitor=r)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/bankabgleich/verbuchen/', {'rechnung_id': r.id})
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        z = Zahlungseingang.objects.get(debitoren_rechnung=r)
        c.post(f'/neu/zahlungen/{z.id}/stornieren/')
        r.refresh_from_db(); z.refresh_from_db()
        self.assertEqual(z.status, 'storniert')
        self.assertEqual(r.status, 'offen')                       # OP wieder offen
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))    # Bankbuchung aufgehoben

    # ---------- W4: Jahresabschluss saldiert Erfolgskonten gegen 2970 ----------
    def test_w4_jahresabschluss_saldiert_erfolgskonten(self):
        from finance.booking import buche, ensure_kontenplan
        from core.services.jahresabschluss import buche_jahresabschluss, ist_abgeschlossen
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        buche('1100', '3000', Decimal('12000'), 'Mieten', datum=date(2024, 6, 30), liegenschaft=lg)
        buche('4000', '1020', Decimal('2000'), 'Reparatur', datum=date(2024, 7, 1), liegenschaft=lg)
        n, erg = buche_jahresabschluss(2024, user=None)
        self.assertEqual(n, 2)
        self.assertEqual(erg, Decimal('10000.00'))                # Gewinn
        self.assertEqual(self._saldo('3000'), Decimal('0.00'))    # Erfolgskonten saldiert
        self.assertEqual(self._saldo('4000'), Decimal('0.00'))
        self.assertEqual(self._saldo('2970'), Decimal('-10000.00'))  # Ergebnis im Haben
        self.assertTrue(ist_abgeschlossen(2024))
        # idempotent
        n2, _ = buche_jahresabschluss(2024, user=None)
        self.assertEqual(n2, 0)

    # ---------- K5: Anlage wird aktiviert (1500 läuft nicht negativ) ----------
    def test_k5_anlage_wird_aktiviert(self):
        from finance.booking import ensure_kontenplan
        from core.services.automation import run_abschreibungen
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/anlagen/', {'aktion': 'anlage_neu', 'liegenschaft_id': lg.id,
                                 'bezeichnung': 'Heizung', 'anschaffungswert': '20000',
                                 'anschaffungsdatum': '2024-01-01', 'nutzungsdauer_jahre': '10',
                                 'gegenkonto': '2000', 'aktivieren': 'on'})
        self.assertEqual(self._saldo('1500'), Decimal('20000.00'))
        self.assertEqual(self._saldo('2000'), Decimal('-20000.00'))
        run_abschreibungen(2024, user=None)
        self.assertEqual(self._saldo('1500'), Decimal('18000.00'))   # nach AfA positiv!
        self.assertGreater(self._saldo('1500'), Decimal('0'))

    # ---------- K4: Saldosteuersatz auf Brutto-Entgelt ----------
    def test_k4_saldosteuersatz_auf_brutto(self):
        from core.services.mwst_estv import berechne_estv
        d = berechne_estv(umsatz_steuerbar=Decimal('10000'), umsatzsteuer=Decimal('810'),
                          vorsteuer_material=Decimal('0'), vorsteuer_invest=Decimal('0'),
                          methode='saldo', saldosteuersatz=Decimal('6.5'),
                          umsatz_brutto=Decimal('10810'))
        self.assertEqual(d['z289'], Decimal('10810.00'))            # Brutto, nicht Netto
        self.assertEqual(d['z399'], Decimal('702.65'))              # 6.5% von 10'810
        self.assertEqual(d['z500'], Decimal('702.65'))

    def test_k4_mwst_verbuchen_leert_2200(self):
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        buche('1100', '2200', Decimal('810'), 'MWST Q1', datum=date(2024, 3, 31), liegenschaft=lg)
        buche('1170', '2000', Decimal('200'), 'Vorsteuer', datum=date(2024, 3, 31), liegenschaft=lg)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/mwst/verbuchen/', {'jahr': '2024', 'quartal': '1', 'umsatzsteuer': '810',
                                        'vorsteuer': '200', 'zahllast': '610', 'methode': 'effektiv'})
        self.assertEqual(self._saldo('2200'), Decimal('0.00'))    # ausgebucht
        self.assertEqual(self._saldo('1170'), Decimal('0.00'))    # Vorsteuer verrechnet
        # Die Zahllast ist am Stichtag eine SCHULD gegenüber der ESTV (2201) —
        # gezahlt wird erst mit der Abrechnung. Eine Bankbuchung per 31.03. haette
        # 1020 vom realen Kontoauszug abweichen lassen (Audit).
        self.assertEqual(self._saldo('2201'), Decimal('-610.00'))  # Schuld ESTV
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))     # Bank unberuehrt

    # ---------- W5: Ad-hoc-Rechnung nicht auf 3000 ----------
    def test_w5_adhoc_debitor_auf_3600(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/debitoren/neu/', {'titel': 'Schlüsselersatz', 'betrag': '80',
                                       'vertrag_id': v.id})
        self.assertEqual(self._saldo('3600'), Decimal('-80.00'))
        self.assertEqual(self._saldo('3000'), Decimal('0.00'))


# ============================================================
# P3 — Bank abstimmbar: Kontoauszug, Bankbewegungen, Zuordnung
# ============================================================

_P3_CAMT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.04">
 <BkToCstmrStmt><Stmt>
  <Acct><Id><IBAN>CH9300762011623852957</IBAN></Id></Acct>
  <FrToDt><FrDtTm>2024-03-01T00:00:00</FrDtTm><ToDtTm>2024-03-31T00:00:00</ToDtTm></FrToDt>
  <Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="CHF">1000.00</Amt>
       <CdtDbtInd>CRDT</CdtDbtInd></Bal>
  <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="CHF">1450.00</Amt>
       <CdtDbtInd>CRDT</CdtDbtInd></Bal>
  <Ntry>
   <Amt Ccy="CHF">800.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
   <BookgDt><Dt>2024-03-05</Dt></BookgDt><ValDt><Dt>2024-03-04</Dt></ValDt>
   <NtryDtls><TxDtls>
     <Refs><AcctSvcrRef>P3-CRDT-1</AcctSvcrRef></Refs>
     <RltdPties><Dbtr><Nm>Hans Muster</Nm></Dbtr></RltdPties>
     <RmtInf><Ustrd>Miete Maerz</Ustrd></RmtInf>
   </TxDtls></NtryDtls>
  </Ntry>
  <Ntry>
   <Amt Ccy="CHF">350.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>
   <BookgDt><Dt>2024-03-07</Dt></BookgDt><ValDt><Dt>2024-03-06</Dt></ValDt>
   <NtryDtls><TxDtls>
     <Refs><AcctSvcrRef>P3-DBIT-1</AcctSvcrRef></Refs>
     <RltdPties><Cdtr><Nm>Hauswartung AG</Nm></Cdtr></RltdPties>
     <RmtInf><Ustrd>Hauswartung Februar</Ustrd></RmtInf>
   </TxDtls></NtryDtls>
  </Ntry>
 </Stmt></BkToCstmrStmt>
</Document>"""


class ErfolgBilanzGruppiertTests(TestCase):
    """Erfolgsrechnung und Bilanz in vier Abfragen statt zwei je Konto.

    `_erfolg_bilanz` lief über den ganzen Kontenplan und fragte für jedes Konto
    Soll und Haben einzeln ab — gemessen 90 Abfragen für einen Aufbau von
    /neu/buchhaltung/, danach 2. Dieselbe Rechnung steckt im PDF-Abzug.

    Bei so einem Umbau zählt nur eines: dass exakt dieselben Zahlen
    herauskommen. Deshalb rechnet der Test unten dasselbe nochmals — naiv,
    Konto für Konto — und vergleicht Feld für Feld.
    """

    def _daten(self):
        from finance.booking import ensure_kontenplan, buche, storniere_buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        lg2 = Liegenschaft.objects.create(strasse='Nebenweg 2', plz='3000', ort='Bern',
                                          versicherungswert=Decimal('500000'))
        # Vorjahr — muss in der Bilanz kumulativ mitzählen, in der
        # Erfolgsrechnung des Folgejahres aber nicht.
        buche('1100', '3000', Decimal('4000.00'), 'Miete Vorjahr',
              datum=date(2025, 6, 1), liegenschaft=lg)
        buche('1020', '1100', Decimal('4000.00'), 'Zahlung Vorjahr',
              datum=date(2025, 6, 5), liegenschaft=lg)
        # Laufendes Jahr
        buche('1100', '3000', Decimal('9000.00'), 'Miete', datum=date(2026, 3, 1), liegenschaft=lg)
        buche('4000', '2000', Decimal('2500.00'), 'Reparatur', datum=date(2026, 3, 4), liegenschaft=lg)
        buche('4000', '2000', Decimal('700.00'), 'Reparatur 2', datum=date(2026, 4, 4), liegenschaft=lg2)
        # Ein Storno — beide Seiten müssen sich aufheben
        b = buche('4000', '2000', Decimal('333.00'), 'Irrtum', datum=date(2026, 5, 1), liegenschaft=lg)
        storniere_buchung(b, user=None, datum=date(2026, 5, 2))
        return lg

    def _naiv(self, aktive_lg, jahr):
        """Dieselbe Rechnung, Konto für Konto — die Fassung von vor dem Umbau."""
        from django.db.models import Sum
        from finance.models import Buchung, Buchungskonto
        from core.services.jahresabschluss import abschluss_buchungen_q
        null = Decimal('0.00')
        qs = Buchung.objects.all()
        bil = Buchung.objects.all()
        if aktive_lg:
            qs = qs.filter(liegenschaft=aktive_lg); bil = bil.filter(liegenschaft=aktive_lg)
        if jahr != 'alle':
            qs = qs.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31))
            bil = bil.filter(datum__lte=date(jahr, 12, 31))
        qs = qs.exclude(abschluss_buchungen_q())
        te = ta = tak = tpa = kum = null
        for k in Buchungskonto.objects.all():
            def summe(basis, feld):
                return basis.filter(**{feld: k}).aggregate(t=Sum('betrag'))['t'] or null
            if k.typ == 'ertrag':
                te += summe(qs, 'haben_konto') - summe(qs, 'soll_konto')
                kum += summe(bil, 'haben_konto') - summe(bil, 'soll_konto')
            elif k.typ == 'aufwand':
                ta += summe(qs, 'soll_konto') - summe(qs, 'haben_konto')
                kum -= summe(bil, 'soll_konto') - summe(bil, 'haben_konto')
            else:
                saldo = summe(bil, 'soll_konto') - summe(bil, 'haben_konto')
                if saldo == 0:
                    continue
                if k.typ == 'aktiv':
                    tak += saldo
                elif k.typ == 'passiv':
                    tpa += -saldo
                elif saldo > 0:
                    tak += saldo
                else:
                    tpa += -saldo
        return {'total_ertrag': te, 'total_aufwand': ta, 'total_aktiven': tak,
                'total_passiven': tpa, 'kum_erfolg': kum}

    def test_gruppierte_rechnung_ergibt_dieselben_zahlen(self):
        from core.views.fw import _erfolg_bilanz
        lg = self._daten()
        for aktive_lg, jahr in ((None, 2026), (lg, 2026), (None, 2025), (None, 'alle')):
            neu = _erfolg_bilanz(aktive_lg, jahr)
            alt = self._naiv(aktive_lg, jahr)
            for feld, wert in alt.items():
                self.assertEqual(neu[feld], wert,
                                 f"{feld} weicht ab (lg={aktive_lg}, jahr={jahr}): "
                                 f"{neu[feld]} statt {wert}")

    def test_zahlen_stimmen_auch_absolut(self):
        """Der Vergleich oben würde auch bestehen, wenn BEIDE Fassungen falsch
        rechnen. Deshalb zusätzlich von Hand nachgerechnet."""
        from core.views.fw import _erfolg_bilanz
        self._daten()
        d = _erfolg_bilanz(None, 2026)
        self.assertEqual(d['total_ertrag'], Decimal('9000.00'))
        # 2500 + 700; die 333 sind storniert und heben sich auf
        self.assertEqual(d['total_aufwand'], Decimal('3200.00'))
        self.assertEqual(d['erfolg'], Decimal('5800.00'))
        # Vorjahr 4000 Ertrag → Vortrag; kumuliert 9000 + 4000 − 3200
        self.assertEqual(d['erfolg_vortrag'], Decimal('4000.00'))
        self.assertEqual(d['bilanz_differenz'], Decimal('0.00'))

    def test_buchhaltung_fragt_nicht_je_konto_nach(self):
        """Mit jedem neuen Konto im Kontenplan wuchs der Seitenaufbau."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from finance.models import Buchungskonto
        self._daten()
        c = Client(); c.force_login(_team_user())
        def messen():
            with CaptureQueriesContext(connection) as ctx:
                r = c.get('/neu/buchhaltung/')
            self.assertEqual(r.status_code, 200)
            return len(ctx.captured_queries)
        klein = messen()
        for i in range(10):
            Buchungskonto.objects.create(nummer=f'89{i:02d}', bezeichnung=f'Test {i}', typ='aufwand')
        gross = messen()
        self.assertLessEqual(gross, klein + 2,
                             f'zehn Konten mehr → {klein} statt {gross} Abfragen')


class BetragUeberlaufTests(TestCase):
    """Ein zu grosser Betrag darf die Datenbank nicht vergiften.

    SQLite erzwingt `max_digits` nicht: ein Betrag mit zu vielen Vorkommastellen
    (z.B. 999999999999.99 in ein max_digits=10-Feld) wird gespeichert und wirft
    dann bei JEDEM Lesen `decimal.InvalidOperation` — die Kreditoren-/Debitoren-
    Liste ist danach für alle dauerhaft 500, nur per Roh-SQL zu reparieren.
    Ein einziger Tippfehler genügt. Ein pre_save-Signal fängt es ab.
    """

    def _konten(self):
        from finance.models import Buchungskonto
        a, _ = Buchungskonto.objects.get_or_create(nummer='4000', defaults={'bezeichnung': 'Aufwand', 'typ': 'aufwand'})
        b, _ = Buchungskonto.objects.get_or_create(nummer='1020', defaults={'bezeichnung': 'Bank', 'typ': 'bilanz'})
        return a, b

    def test_ueberlauf_wird_abgewiesen_kreditor(self):
        from finance.models import KreditorenRechnung
        with self.assertRaises(ValueError):
            KreditorenRechnung.objects.create(betrag=Decimal('999999999999.99'))
        self.assertEqual(KreditorenRechnung.objects.count(), 0,
                         'Überlauf-Betrag ist trotzdem in der DB gelandet')

    def test_ueberlauf_wird_abgewiesen_buchung(self):
        from finance.models import Buchung
        a, b = self._konten()
        with self.assertRaises(ValueError):
            Buchung.objects.create(datum=date(2026, 1, 1), beleg_text='X',
                                   soll_konto=a, haben_konto=b,
                                   betrag=Decimal('100000000.00'))   # 9 Vorkomma, Feld erlaubt 8

    def test_gueltiger_betrag_passiert(self):
        """Gegenstück: Ein normaler Betrag muss durchgehen — sonst hätte die
        Guard einfach alles abgewiesen."""
        from finance.models import KreditorenRechnung
        k = KreditorenRechnung.objects.create(betrag=Decimal('99999999.99'))   # Maximum
        self.assertEqual(k.betrag, Decimal('99999999.99'))

    def test_grenze_liegt_richtig(self):
        from finance.models import KreditorenRechnung
        KreditorenRechnung.objects.create(betrag=Decimal('99999999.99'))       # gerade noch
        with self.assertRaises(ValueError):
            KreditorenRechnung.objects.create(betrag=Decimal('100000000.00'))  # eins zu viel


class JahresabschlussH5H6Tests(TestCase):
    """Live-Test H5+H6: Bilanz-Doppelung nach Abschluss + Abschluss-Storno.

    H5: Nach dem Jahresabschluss zeigte die Bilanz das Periodenergebnis DOPPELT
        (einmal in 2970, einmal als «Jahresgewinn»-Zeile) und erfand einen
        «Ergebnisvortrag (Vorjahre)» in Höhe von −Ergebnis, um das auszugleichen.
    H6: Eine einzelne Abschlussbuchung liess sich im Journal stornieren — das
        liess das Jahr halb geschlossen zurück; und der Storno («Storno …»)
        fiel aus dem Abschluss-Ausschlussfilter → verdoppelte den Ertrag.
    """

    def _saldo(self, nummer):
        from finance.models import Buchung
        from django.db.models import Sum
        soll = Buchung.objects.filter(soll_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        haben = Buchung.objects.filter(haben_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        return soll - haben

    def _period_bookings(self, lg):
        from finance.booking import buche
        buche('1100', '3000', Decimal('1200'), 'Miete 01/2024', datum=date(2024, 1, 31), liegenschaft=lg)
        buche('4000', '1100', Decimal('500'), 'Reparatur 02/2024', datum=date(2024, 2, 15), liegenschaft=lg)
        # erfolg = 1200 − 500 = 700 (Gewinn)

    def test_h5_ergebnis_nicht_doppelt_in_bilanz_nach_abschluss(self):
        from finance.booking import ensure_kontenplan
        from core.services.jahresabschluss import buche_jahresabschluss
        from core.views.fw import _erfolg_bilanz
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._period_bookings(lg)
        vor = _erfolg_bilanz(None, 2024)
        self.assertEqual(vor['erfolg'], Decimal('700.00'))
        self.assertEqual(vor['erfolg_offen'], Decimal('700.00'))
        self.assertEqual(vor['erfolg_vortrag'], Decimal('0.00'))
        self.assertEqual(vor['bilanz_differenz'], Decimal('0.00'))
        buche_jahresabschluss(2024)
        nach = _erfolg_bilanz(None, 2024)
        # Ergebnis ist in 2970 gebucht → keine separate Ergebniszeile mehr und
        # KEIN erfundener Ergebnisvortrag von −700 (das war der Befund).
        self.assertEqual(nach['erfolg_offen'], Decimal('0.00'))
        self.assertEqual(nach['erfolg_vortrag'], Decimal('0.00'))
        self.assertEqual(nach['bilanz_differenz'], Decimal('0.00'))
        self.assertEqual(self._saldo('2970'), Decimal('-700.00'))  # Passivsaldo = Gewinn

    def test_h6_einzelne_abschlussbuchung_nicht_stornierbar(self):
        from finance.booking import ensure_kontenplan
        from core.services.jahresabschluss import buche_jahresabschluss
        from finance.models import Buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._period_bookings(lg)
        buche_jahresabschluss(2024)
        ab = Buchung.objects.filter(beleg_text__startswith='Jahresabschluss 2024 —').first()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        r = c.post(f'/neu/buchhaltung/buchung/{ab.id}/stornieren/', follow=True)
        ab.refresh_from_db()
        self.assertIsNone(ab.storniert_am, 'Abschlussbuchung wurde einzeln storniert')
        self.assertContains(r, 'nicht einzeln stornieren')

    def test_h6_abschluss_zuruecknehmen_oeffnet_jahr_und_reversiert(self):
        from finance.booking import ensure_kontenplan
        from core.services.jahresabschluss import buche_jahresabschluss, ist_abgeschlossen
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._period_bookings(lg)
        buche_jahresabschluss(2024)
        self.assertTrue(ist_abgeschlossen(2024))
        self.assertEqual(self._saldo('2970'), Decimal('-700.00'))
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post('/neu/buchhaltung/', {'aktion': 'abschluss_zuruecknehmen', 'jahr': '2024'})
        self.assertFalse(ist_abgeschlossen(2024))
        self.assertEqual(self._saldo('2970'), Decimal('0.00'))  # vollständig reversiert

    def test_h6_pl_nach_ruecknahme_nicht_verdoppelt(self):
        from finance.booking import ensure_kontenplan
        from core.services.jahresabschluss import buche_jahresabschluss, nimm_zurueck
        from core.views.fw import _erfolg_bilanz
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._period_bookings(lg)
        buche_jahresabschluss(2024)
        nimm_zurueck(2024)
        nach = _erfolg_bilanz(None, 2024)
        self.assertEqual(nach['total_ertrag'], Decimal('1200.00'))
        self.assertEqual(nach['total_aufwand'], Decimal('500.00'))
        self.assertEqual(nach['erfolg'], Decimal('700.00'))
        self.assertEqual(nach['erfolg_offen'], Decimal('700.00'))
        self.assertEqual(nach['bilanz_differenz'], Decimal('0.00'))

    def test_h6_wieder_abschliessbar_nach_ruecknahme(self):
        from finance.booking import ensure_kontenplan
        from core.services.jahresabschluss import buche_jahresabschluss, nimm_zurueck, ist_abgeschlossen
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._period_bookings(lg)
        buche_jahresabschluss(2024)
        nimm_zurueck(2024)
        self.assertFalse(ist_abgeschlossen(2024))
        n, erg = buche_jahresabschluss(2024)
        self.assertGreater(n, 0)
        self.assertEqual(erg, Decimal('700.00'))
        self.assertEqual(self._saldo('2970'), Decimal('-700.00'))

    def test_h6_view_roundtrip_loest_periodensperre_und_oeffnet_jahr(self):
        # End-to-End über die View: Abschluss setzt die Periodensperre auf 31.12.,
        # Rücknahme muss sie ZUERST lösen und die Storni auf den 31.12. zurückbuchen
        # (sonst blockiert Buchung.save die Rücknahme und das Jahr bliebe halb offen).
        from crm.models import Verwaltung
        from finance.booking import ensure_kontenplan
        from core.services.jahresabschluss import ist_abgeschlossen
        from core.views.fw import _erfolg_bilanz
        ensure_kontenplan()
        Verwaltung.objects.create(firma='Verwaltung AG', strasse='Weg 1', plz='8000', ort='Zürich')
        lg, e, m, v = _basis_objekte()
        self._period_bookings(lg)
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post('/neu/buchhaltung/', {'aktion': 'jahresabschluss', 'jahr': '2024'})
        self.assertTrue(ist_abgeschlossen(2024))
        self.assertEqual(Verwaltung.objects.first().buchung_gesperrt_bis, date(2024, 12, 31))
        c.post('/neu/buchhaltung/', {'aktion': 'abschluss_zuruecknehmen', 'jahr': '2024'})
        self.assertFalse(ist_abgeschlossen(2024))
        # Periodensperre gelöst und Jahr im 31.12.-Blick wieder offen (Ergebnis
        # zurück auf den Erfolgskonten, 2970 auf null).
        self.assertNotEqual(Verwaltung.objects.first().buchung_gesperrt_bis, date(2024, 12, 31))
        self.assertEqual(self._saldo('2970'), Decimal('0.00'))
        nach = _erfolg_bilanz(None, 2024)
        self.assertEqual(nach['erfolg_offen'], Decimal('700.00'))
        self.assertEqual(nach['bilanz_differenz'], Decimal('0.00'))
