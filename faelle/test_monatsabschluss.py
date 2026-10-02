"""Härtetest des Monatsabschlusses: Sollstellung → Bankabgleich → Mahnlauf →
Zahllauf → Abschluss, plus die Fehlerfälle, die einem Buchhalter passieren.

Jeder Schutz hat seine Gegenprobe im Testnamen: «blockiert», «rollt zurück»,
«lehnt ab». Die Fehler werden wirklich hergestellt (zerstörte Datei, Fehler
mitten im Import), nicht nur behauptet.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils import timezone

from core.tests._helfer import (_basis_objekte, _seed_konten, _team_user,
                                _test_organisation)
from faelle.lauf_dienst import periode_von, planen
from faelle.lauf_models import Lauf

HEUTE = timezone.localdate()
PERIODE = periode_von(HEUTE)


def _camt(eintraege):
    """camt.053-Auszug; eintraege = [(referenz, betrag, acct_ref)]."""
    ntrys = ''.join(
        '<Ntry><CdtDbtInd>CRDT</CdtDbtInd>'
        f'<Amt Ccy="CHF">{betrag}</Amt><BookgDt><Dt>{HEUTE.isoformat()}</Dt></BookgDt>'
        f'<NtryDtls><TxDtls><Refs><AcctSvcrRef>{acct}</AcctSvcrRef></Refs>'
        f'<RmtInf><Strd><CdtrRefInf><Ref>{ref}</Ref></CdtrRefInf></Strd></RmtInf>'
        '</TxDtls></NtryDtls></Ntry>'
        for ref, betrag, acct in eintraege)
    return (f'<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt>{ntrys}'
            '</Stmt></BkToCstmrStmt></Document>').encode()


class _Basis(TestCase):
    def setUp(self):
        _seed_konten()
        self.org = _test_organisation(firma='V AG', iban='CH9300762011623852957')
        self.lg, self.einheit, self.mieter, self.vertrag = _basis_objekte()
        self.verwalter = _team_user('Verwalter')
        self.lesend = _team_user('Lesezugriff')
        self.c = Client()
        self.c.force_login(self.verwalter)
        planen(self.org, HEUTE)

    def lauf(self, schluessel):
        return Lauf.alle_organisationen.get(laufart__schluessel=schluessel, periode=PERIODE)

    def sollstellung(self, client=None):
        return (client or self.c).post(
            '/neu/sollstellung/starten/', {'jahr': HEUTE.year, 'monat': HEUTE.month},
            follow=True)

    def import_camt(self, daten, name='auszug.xml'):
        f = SimpleUploadedFile(name, daten, content_type='application/xml')
        return self.c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f}, follow=True)


def _meldungen(antwort):
    return ' | '.join(str(m) for m in antwort.context['messages']) if antwort.context else ''


class HappyPathTests(_Basis):
    def test_voller_monatsabschluss_setzt_alle_laeufe_auf_abgeschlossen(self):
        from finance.models import (DebitorenRechnung, KreditorenRechnung,
                                    KreditorenZahlung, Zahlungseingang)
        from finance.booking import konto as _k

        # 1) Sollstellung
        self.sollstellung()
        r = DebitorenRechnung.objects.get(titel=f'Miete & NK {HEUTE.month:02d}/{HEUTE.year}')
        self.assertEqual(self.lauf('sollstellung').status, Lauf.ABGESCHLOSSEN)

        # 2) Bankabgleich: Zahlungseingang per QR-Referenz
        self.import_camt(_camt([(r.qr_referenz, '1700.00', 'TX-HAPPY')]))
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(Zahlungseingang.objects.filter(status='verbucht').count(), 1)
        self.assertEqual(self.lauf('bankabgleich').status, Lauf.ABGESCHLOSSEN)

        # 3) Mahnlauf (nichts überfällig → 0 Mahnungen, Lauf trotzdem erledigt)
        self.c.post('/neu/mahnwesen/lauf/', {'kein_versand': 'on'})
        self.assertEqual(self.lauf('mahnlauf').status, Lauf.ABGESCHLOSSEN)

        # 4) Zahllauf Kreditoren: Sammelbestätigung
        k = KreditorenRechnung.objects.create(
            lieferant='Elektro AG', betrag=Decimal('800'), status='freigegeben',
            liegenschaft=self.lg, konto=_k('4000'),
            iban='CH9300762011623852957', referenz='R-1')
        self.c.post('/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': [str(k.id)]})
        k.refresh_from_db()
        self.assertEqual(k.status, 'bezahlt')
        self.assertEqual(KreditorenZahlung.objects.count(), 1)
        self.assertEqual(self.lauf('zahllauf').status, Lauf.ABGESCHLOSSEN)

        # 5) Alle vier stehen sauber auf «abgeschlossen», mit Zeitstempel und Benutzer
        for art in ('sollstellung', 'bankabgleich', 'mahnlauf', 'zahllauf'):
            lauf = self.lauf(art)
            self.assertEqual(lauf.status, Lauf.ABGESCHLOSSEN, art)
            self.assertIsNotNone(lauf.abgeschlossen_am, art)
            self.assertEqual(lauf.abgeschlossen_durch, self.verwalter, art)
        self.assertFalse(Lauf.objects.offen().filter(
            periode=PERIODE, laufart__schluessel__in=('sollstellung', 'bankabgleich',
                                                      'mahnlauf', 'zahllauf')).exists())

    def test_abschluss_per_knopf_quittiert_den_lauf(self):
        lauf = self.lauf('mahnlauf')
        antwort = self.c.post(f'/neu/laeufe/{lauf.pk}/abschliessen/', follow=True)
        self.assertEqual(antwort.status_code, 200)
        lauf.refresh_from_db()
        self.assertEqual(lauf.status, Lauf.ABGESCHLOSSEN)
        self.assertEqual(lauf.abgeschlossen_durch, self.verwalter)

    def test_blockierter_lauf_laesst_sich_nicht_per_knopf_abschliessen(self):
        lauf = self.lauf('bankabgleich')
        lauf.blockieren('Sieben unzugeordnete Eingänge')
        self.c.post(f'/neu/laeufe/{lauf.pk}/abschliessen/')
        lauf.refresh_from_db()
        self.assertNotEqual(lauf.status, Lauf.ABGESCHLOSSEN)

    def test_lesezugriff_darf_weder_abschliessen_noch_zuruecksetzen(self):
        lauf = self.lauf('mahnlauf')
        c = Client(); c.force_login(self.lesend)
        self.assertEqual(c.post(f'/neu/laeufe/{lauf.pk}/abschliessen/').status_code, 403)
        lauf.refresh_from_db()
        self.assertEqual(lauf.status, Lauf.OFFEN)


class DetailAnsichtTests(_Basis):
    def test_detail_zeigt_belege_und_knoepfe_vor_dem_abschluss(self):
        self.sollstellung()
        lauf = self.lauf('sollstellung')
        antwort = self.c.get(f'/neu/laeufe/{lauf.pk}/')
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'Muster')
        self.assertContains(antwort, 'Miete &amp; NK')
        self.assertContains(antwort, 'CHF 1700,00')
        self.assertContains(antwort, 'id="lauf-zuruecksetzen"')
        self.assertNotContains(antwort, 'id="lauf-abschliessen"')

    def test_detail_eines_offenen_laufs_hat_abschliessen_knopf(self):
        lauf = self.lauf('mahnlauf')
        antwort = self.c.get(f'/neu/laeufe/{lauf.pk}/')
        self.assertContains(antwort, 'id="lauf-abschliessen"')
        self.assertNotContains(antwort, 'id="lauf-zuruecksetzen"')

    def test_laeufe_liste_verlinkt_das_detail(self):
        lauf = self.lauf('mahnlauf')
        self.assertContains(self.c.get('/neu/laeufe/'), f'/neu/laeufe/{lauf.pk}/')


class DoppelausfuehrungTests(_Basis):
    def test_zweiter_klick_auf_sollstellung_wird_blockiert(self):
        from finance.models import Buchung, DebitorenRechnung
        self.sollstellung()
        rechnungen = DebitorenRechnung.objects.count()
        buchungen = Buchung.objects.count()
        antwort = self.sollstellung()
        self.assertIn('bereits abgeschlossen', _meldungen(antwort))
        self.assertEqual(DebitorenRechnung.objects.count(), rechnungen)
        self.assertEqual(Buchung.objects.count(), buchungen)

    def test_sollstellung_ist_auch_ohne_laufsperre_idempotent(self):
        """Zweite Schicht: Der Dienst selbst stellt nichts doppelt (Scheduler + Knopf)."""
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        self.assertEqual(run_sollstellung(HEUTE.year, HEUTE.month), 1)
        self.assertEqual(run_sollstellung(HEUTE.year, HEUTE.month), 0)
        self.assertEqual(DebitorenRechnung.objects.count(), 1)

    def test_zweiter_mahnlauf_im_selben_monat_wird_blockiert(self):
        self.c.post('/neu/mahnwesen/lauf/', {'kein_versand': 'on'})
        mit = mock.patch('core.services.automation.run_mahnlauf')
        with mit as run:
            antwort = self.c.post('/neu/mahnwesen/lauf/', {'kein_versand': 'on'}, follow=True)
        run.assert_not_called()
        self.assertIn('bereits abgeschlossen', _meldungen(antwort))


class BankabgleichFehlerTests(_Basis):
    def _rechnung(self):
        from finance.models import DebitorenRechnung
        self.sollstellung()
        return DebitorenRechnung.objects.get(titel=f'Miete & NK {HEUTE.month:02d}/{HEUTE.year}')

    def _zustand(self):
        from finance.models import Bankbewegung, Buchung, Kontoauszug, Zahlungseingang
        return (Kontoauszug.objects.count(), Bankbewegung.objects.count(),
                Zahlungseingang.objects.count(), Buchung.objects.count())

    def test_zerstoerte_datei_speichert_nichts(self):
        self._rechnung()
        vorher = self._zustand()
        antwort = self.import_camt(b'<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt><Ntry><Amt')
        self.assertIn('nicht gelesen', _meldungen(antwort))
        self.assertEqual(self._zustand(), vorher)

    def test_fehler_mitten_im_import_rollt_alles_zurueck(self):
        r = self._rechnung()
        vorher = self._zustand()
        # Zeile 1 passt auf die Rechnung, Zeile 2 ist unbekannt (→ Durchlaufkonto).
        daten = _camt([(r.qr_referenz, '1700.00', 'TX-1'), ('000000000000000000000000000', '50.00', 'TX-2')])
        from finance import booking
        echte_buche = booking.buche
        aufrufe = []

        def buche_mit_defekt(*a, **kw):
            aufrufe.append(1)
            if len(aufrufe) == 2:
                raise RuntimeError('Datenbank weg')
            return echte_buche(*a, **kw)

        with mock.patch('finance.booking.buche', buche_mit_defekt):
            antwort = self.import_camt(daten)
        self.assertGreaterEqual(len(aufrufe), 2, 'Der Fehler wurde gar nicht erreicht.')
        self.assertIn('zurückgerollt', _meldungen(antwort))
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen')
        self.assertEqual(self._zustand(), vorher)
        # Gegenprobe: ohne Defekt geht derselbe Import durch.
        self.import_camt(daten)
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')

    def test_wiederholter_import_derselben_datei_bucht_nicht_doppelt(self):
        from finance.models import Zahlungseingang
        r = self._rechnung()
        daten = _camt([(r.qr_referenz, '1700.00', 'TX-DUP')])
        self.import_camt(daten)
        self.import_camt(daten)
        self.assertEqual(Zahlungseingang.objects.filter(bank_referenz='TX-DUP').count(), 1)


class StornoTests(_Basis):
    def _stelle(self):
        from finance.models import DebitorenRechnung
        self.sollstellung()
        return DebitorenRechnung.objects.get(titel=f'Miete & NK {HEUTE.month:02d}/{HEUTE.year}')

    def test_zuruecksetzen_braucht_eine_begruendung(self):
        self._stelle()
        lauf = self.lauf('sollstellung')
        self.c.post(f'/neu/laeufe/{lauf.pk}/zuruecksetzen/', {'grund': '  '})
        lauf.refresh_from_db()
        self.assertEqual(lauf.status, Lauf.ABGESCHLOSSEN)

    def test_sollstellung_stornieren_hebt_rechnung_auf_und_oeffnet_den_lauf(self):
        from finance.models import Buchung
        r = self._stelle()
        lauf = self.lauf('sollstellung')
        antwort = self.c.post(f'/neu/laeufe/{lauf.pk}/zuruecksetzen/',
                              {'grund': 'Falscher Monat', 'stornieren': '1'}, follow=True)
        self.assertIn('zurückgesetzt', _meldungen(antwort))
        r.refresh_from_db(); lauf.refresh_from_db()
        self.assertEqual(r.status, 'storniert')
        self.assertEqual(lauf.status, Lauf.OFFEN)
        self.assertIn('Falscher Monat', lauf.bemerkung)
        # Revisionssicher: Gegenbuchungen statt Löschen
        self.assertTrue(Buchung.objects.filter(ist_storno=True).exists())
        # Neu stellen ist danach wieder möglich — genau eine gültige Rechnung
        self.sollstellung()
        from finance.models import DebitorenRechnung
        self.assertEqual(DebitorenRechnung.objects.exclude(status='storniert').count(), 1)

    def test_storno_mit_verbuchter_zahlung_blockiert_und_aendert_nichts(self):
        r = self._stelle()
        self.import_camt(_camt([(r.qr_referenz, '1700.00', 'TX-PAID')]))
        lauf = self.lauf('sollstellung')
        antwort = self.c.post(f'/neu/laeufe/{lauf.pk}/zuruecksetzen/',
                              {'grund': 'Irrtum', 'stornieren': '1'}, follow=True)
        self.assertIn('Zahlungen', _meldungen(antwort))
        r.refresh_from_db(); lauf.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(lauf.status, Lauf.ABGESCHLOSSEN)

    def test_sachbearbeiter_darf_nicht_stornieren(self):
        r = self._stelle()
        lauf = self.lauf('sollstellung')
        c = Client(); c.force_login(_team_user('Sachbearbeiter'))
        c.post(f'/neu/laeufe/{lauf.pk}/zuruecksetzen/', {'grund': 'x', 'stornieren': '1'})
        r.refresh_from_db(); lauf.refresh_from_db()
        self.assertEqual(r.status, 'offen')
        self.assertEqual(lauf.status, Lauf.ABGESCHLOSSEN)

    def test_zuruecksetzen_ohne_storno_laesst_die_buchhaltung_unberuehrt(self):
        r = self._stelle()
        lauf = self.lauf('sollstellung')
        self.c.post(f'/neu/laeufe/{lauf.pk}/zuruecksetzen/', {'grund': 'Nachzügler'})
        r.refresh_from_db(); lauf.refresh_from_db()
        self.assertEqual(r.status, 'offen')
        self.assertEqual(lauf.status, Lauf.OFFEN)


class ZahllaufZweiSchritteTests(_Basis):
    """Die Datei erledigt den Zahllauf nicht — erst die Bank-Bestätigung."""

    def _kreditoren(self, n=2):
        from finance.booking import konto as _k
        from finance.models import KreditorenRechnung
        return [KreditorenRechnung.objects.create(
            lieferant=f'Lieferant {i}', betrag=Decimal('800'), status='freigegeben',
            liegenschaft=self.lg, konto=_k('4000'),
            iban='CH9300762011623852957', referenz=f'R-{i}') for i in range(n)]

    def test_datei_setzt_den_lauf_auf_laeuft_und_nicht_auf_abgeschlossen(self):
        k = self._kreditoren(1)
        self.c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': [str(k[0].id)]})
        k[0].refresh_from_db()
        self.assertEqual(k[0].status, 'in_zahlung')
        self.assertEqual(self.lauf('zahllauf').status, Lauf.LAEUFT)

    def test_bestaetigung_schliesst_den_lauf(self):
        k = self._kreditoren(1)
        self.c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': [str(k[0].id)]})
        self.c.post('/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': [str(k[0].id)]})
        self.assertEqual(self.lauf('zahllauf').status, Lauf.ABGESCHLOSSEN)

    def test_teilbestaetigung_laesst_den_lauf_offen(self):
        a, b = self._kreditoren(2)
        self.c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': [str(a.id), str(b.id)]})
        self.c.post('/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': [str(a.id)]})
        self.assertEqual(self.lauf('zahllauf').status, Lauf.LAEUFT)
        self.c.post('/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': [str(b.id)]})
        self.assertEqual(self.lauf('zahllauf').status, Lauf.ABGESCHLOSSEN)


class DublettenPruefungTests(_Basis):
    def _lauf_befehl(self):
        from io import StringIO

        from django.core.management import call_command
        aus = StringIO()
        try:
            call_command('sollstellung_dubletten_pruefen', stdout=aus)
            return 0, aus.getvalue()
        except SystemExit as e:
            return e.code, aus.getvalue()

    def test_sauberer_bestand_meldet_keine_dubletten(self):
        self.sollstellung()
        code, text = self._lauf_befehl()
        self.assertEqual(code, 0)
        self.assertIn('Keine Dubletten', text)

    def test_doppelte_rechnung_wird_gefunden_und_nicht_veraendert(self):
        from finance.models import DebitorenRechnung
        self.sollstellung()
        r = DebitorenRechnung.objects.get(titel=f'Miete & NK {HEUTE.month:02d}/{HEUTE.year}')
        # Altlast herstellen: am Dienst vorbei eine zweite Rechnung anlegen.
        DebitorenRechnung.objects.create(vertrag=r.vertrag, titel=r.titel, betrag=r.betrag,
                                         faellig_am=r.faellig_am, status='offen')
        vorher = DebitorenRechnung.objects.count()
        code, text = self._lauf_befehl()
        self.assertEqual(code, 1)
        self.assertIn('2×', text)
        self.assertEqual(DebitorenRechnung.objects.count(), vorher)

    def test_stornierte_rechnung_zaehlt_nicht_als_dublette(self):
        from finance.models import DebitorenRechnung
        self.sollstellung()
        r = DebitorenRechnung.objects.get(titel=f'Miete & NK {HEUTE.month:02d}/{HEUTE.year}')
        DebitorenRechnung.objects.create(vertrag=r.vertrag, titel=r.titel, betrag=r.betrag,
                                         faellig_am=r.faellig_am, status='storniert')
        self.assertEqual(self._lauf_befehl()[0], 0)


class RueckgaengigHinweisTests(_Basis):
    def test_detail_nennt_den_rueckgaengig_weg_der_laufart(self):
        lauf = self.lauf('bankabgleich')
        self.c.post(f'/neu/laeufe/{lauf.pk}/abschliessen/')
        antwort = self.c.get(f'/neu/laeufe/{lauf.pk}/')
        self.assertContains(antwort, 'Import rückgängig')
        self.assertContains(antwort, 'href="/neu/bankabgleich/"')
        self.assertContains(antwort, 'gebuchte Belege bleiben bestehen')
