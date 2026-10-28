"""Doppelklick- und Stoss-Sicherheit der Geldpfade (Etappe 0: FIN-01, FIN-02,
FIN-04, FIN-05, SICH-44).

Was geprüft wird: Dieselbe Aktion läuft mehrfach GLEICHZEITIG (Doppelklick,
zwei Tabs, Scheduler neben dem Knopf) — und bucht trotzdem genau einmal.

ZWEI SORTEN TESTS
* `*FolgeTests` laufen überall (auch SQLite): Die zweite Anfrage kommt NACH der
  ersten und muss als «bereits verbucht» enden, ohne zweite Buchung.
* `*ParallelTests` starten echte Threads gegen PostgreSQL. SQLite verdeckt
  genau diese Fehler (Schreiber werden dort ohnehin hintereinander gestellt, und
  `select_for_update` ist wirkungslos), deshalb sind sie dort übersprungen und
  müssen in der CI auf PostgreSQL laufen (`test-postgres`).

Gegenprobe (28.10.2026): `select_for_update`/`sperre_organisation` aus dem
geprüften Pfad entfernt -> der zugehörige Parallel-Test wird rot; Wortlaut je
Test im Schlussbericht.
"""
from datetime import date
from decimal import Decimal

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Sum
from django.test import Client, TransactionTestCase
from django.utils import timezone

from core.tenancy import organisation_kontext
from core.tests._helfer import _basis_objekte, _team_user, _test_organisation
from core.tests._parallel import NUR_POSTGRES, parallel


class GeldPfadBasis(TransactionTestCase):
    """Eine Verwaltung, ein Verwalter, ein Vertrag, ein Kontenplan."""

    def setUp(self):
        from finance.booking import ensure_kontenplan
        self.org = _test_organisation(iban='CH9300762011623852957')
        self.benutzer = _team_user('Verwaltung')
        self.lg, self.einheit, self.mieter, self.vertrag = _basis_objekte()
        ensure_kontenplan()

    # -- Bausteine -------------------------------------------------------
    def neuer_client(self):
        c = Client()
        c.force_login(self.benutzer)
        return c

    def post(self, url, daten=None):
        """POST als Verwalter; liefert (Statuscode, Content-Type, Meldungen)."""
        antwort = self.neuer_client().post(url, daten or {})
        meldungen = [str(m) for m in get_messages(antwort.wsgi_request)]
        return antwort.status_code, antwort.get('Content-Type', ''), meldungen

    def parallel_post(self, anzahl, url, daten=None):
        """Mehrere gleichzeitige POSTs. Ein Fehler (500) in einer Anfrage ist KEIN
        stilles Ergebnis: Er lässt den Test scheitern. Ein Doppelklick darf nie
        mit einem Absturz enden, auch wenn die Buchung selbst stimmt."""
        antworten = parallel(anzahl, lambda i: self.post(url, daten))
        abstuerze = [a for a in antworten if isinstance(a, BaseException)]
        self.assertEqual(abstuerze, [], f'{len(abstuerze)} von {anzahl} Anfragen sind abgestürzt: {abstuerze}')
        return antworten

    def rechnung(self, betrag='1700.00', titel='Miete 05/2026'):
        """Offene Mietrechnung samt Sollstellungsbuchung (1100 an 3000)."""
        from finance.booking import buche
        from finance.models import DebitorenRechnung
        heute = timezone.localdate()
        r = DebitorenRechnung.objects.create(
            vertrag=self.vertrag, liegenschaft=self.lg, einheit=self.einheit, titel=titel,
            betrag=Decimal(betrag), datum=heute, faellig_am=heute, status='offen')
        buche('1100', '3000', Decimal(betrag), f'Mietertrag {titel}', liegenschaft=self.lg, debitor=r)
        return r

    def kreditor(self, betrag='800.00', status='freigegeben', lieferant='Parallel AG'):
        from finance.models import KreditorenRechnung
        return KreditorenRechnung.objects.create(
            lieferant=lieferant, betrag=Decimal(betrag), status=status,
            iban='CH9300762011623852957', datum=timezone.localdate(),
            faellig_am=timezone.localdate(), liegenschaft=self.lg, referenz='R-1')

    def saldo(self, nummer):
        from finance.models import Buchung
        soll = Buchung.objects.filter(soll_konto__nummer=nummer).aggregate(t=Sum('betrag'))['t'] or Decimal('0')
        haben = Buchung.objects.filter(haben_konto__nummer=nummer).aggregate(t=Sum('betrag'))['t'] or Decimal('0')
        return soll - haben


# ======================================================================
# FIN-01: Zahlung auf einen Debitor (Bankabgleich «verbuchen»)
# ======================================================================
class DebitorZahlungFolgeTests(GeldPfadBasis):

    def test_zweiter_klick_bucht_nicht_noch_einmal(self):
        from finance.models import Zahlungseingang
        r = self.rechnung()
        erste = self.post('/neu/bankabgleich/verbuchen/', {'rechnung_id': r.pk})
        zweite = self.post('/neu/bankabgleich/verbuchen/', {'rechnung_id': r.pk})
        self.assertEqual(erste[0], 302)
        self.assertEqual(zweite[0], 302)
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 1)
        self.assertEqual(self.saldo('1020'), Decimal('1700.00'))
        self.assertTrue(any('bezahlt' in m.lower() for m in zweite[2]), zweite[2])

    def test_teilbetrag_doppelklick_mit_stand_wird_abgewiesen(self):
        """Ein Doppelklick mit ausdrücklichem Teilbetrag ist von zwei echten
        Teilzahlungen nicht zu unterscheiden — ausser über den Stand, den die
        Maske mitschickt (`erwartet_offen`): Er stimmt nach der ersten Buchung
        nicht mehr."""
        from finance.models import Zahlungseingang
        r = self.rechnung()
        daten = {'rechnung_id': r.pk, 'betrag': '500.00', 'erwartet_offen': '1700.00'}
        self.post('/neu/bankabgleich/verbuchen/', daten)
        zweite = self.post('/neu/bankabgleich/verbuchen/', daten)
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 1)
        self.assertEqual(self.saldo('1020'), Decimal('500.00'))
        self.assertTrue(any('geändert' in m or 'verbucht' in m for m in zweite[2]), zweite[2])

    def test_zweite_echte_teilzahlung_ohne_stand_bleibt_moeglich(self):
        """Ohne `erwartet_offen` (API, Skripte) gilt wie bisher: zwei Teilzahlungen
        sind zwei Zahlungen."""
        from finance.models import Zahlungseingang
        r = self.rechnung()
        self.post('/neu/bankabgleich/verbuchen/', {'rechnung_id': r.pk, 'betrag': '500.00'})
        self.post('/neu/bankabgleich/verbuchen/', {'rechnung_id': r.pk, 'betrag': '500.00'})
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 2)


@NUR_POSTGRES
class DebitorZahlungParallelTests(GeldPfadBasis):

    def test_vier_parallele_klicks_buchen_einmal(self):
        """FIN-01: vorher 4 Zahlungen, 6'800 statt 1'700, Bank um 5'100 zu hoch."""
        from finance.models import Zahlungseingang
        r = self.rechnung()
        antworten = self.parallel_post(4, '/neu/bankabgleich/verbuchen/', {'rechnung_id': r.pk})
        for a in antworten:
            self.assertEqual(a[0], 302, a)
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 1)
        self.assertEqual(self.saldo('1020'), Decimal('1700.00'))
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')

    def test_parallele_teilbetraege_mit_stand_buchen_einmal(self):
        from finance.models import Zahlungseingang
        r = self.rechnung()
        daten = {'rechnung_id': r.pk, 'betrag': '500.00', 'erwartet_offen': '1700.00'}
        self.parallel_post(4, '/neu/bankabgleich/verbuchen/', daten)
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 1)
        self.assertEqual(self.saldo('1020'), Decimal('500.00'))


# ======================================================================
# FIN-02: Kreditor bezahlen, Zahllauf (Sammelbestätigung, Zahlungsdatei)
# ======================================================================
class KreditorFolgeTests(GeldPfadBasis):

    def test_zweiter_klick_bezahlt_nicht_noch_einmal(self):
        from finance.models import KreditorenZahlung
        k = self.kreditor()
        self.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.pk})
        zweite = self.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.pk})
        self.assertEqual(zweite[0], 302)
        self.assertEqual(KreditorenZahlung.objects.filter(kreditor=k, status='verbucht').count(), 1)
        self.assertEqual(self.saldo('2000'), Decimal('800.00'))
        self.assertTrue(zweite[2], 'Die zweite Anfrage muss eine Meldung tragen, nicht still enden.')

    def test_teilbetrag_doppelklick_mit_stand_wird_abgewiesen(self):
        from finance.models import KreditorenZahlung
        k = self.kreditor()
        daten = {'rechnung_id': k.pk, 'betrag': '300.00', 'erwartet_offen': '800.00'}
        self.post('/neu/kreditoren/bezahlen/', daten)
        self.post('/neu/kreditoren/bezahlen/', daten)
        self.assertEqual(KreditorenZahlung.objects.filter(kreditor=k, status='verbucht').count(), 1)

    def test_sammelbestaetigung_zweimal_bucht_einmal(self):
        from finance.models import KreditorenZahlung
        ks = [self.kreditor('500.00', lieferant=f'ZL{i} AG') for i in range(3)]
        daten = {'aktion': 'bezahlt', 'rechnung_ids': [k.pk for k in ks]}
        self.post('/neu/zahllauf/', daten)
        zweite = self.post('/neu/zahllauf/', daten)
        self.assertEqual(KreditorenZahlung.objects.filter(kreditor__in=ks, status='verbucht').count(), 3)
        self.assertEqual(self.saldo('2000'), Decimal('1500.00'))
        self.assertEqual(zweite[0], 302)

    def test_datei_zweimal_liefert_die_rechnungen_nur_einmal(self):
        ks = [self.kreditor('500.00', lieferant=f'ZD{i} AG') for i in range(2)]
        daten = {'aktion': 'datei', 'rechnung_ids': [k.pk for k in ks],
                 'ausfuehrungsdatum': timezone.localdate().isoformat()}
        erste = self.post('/neu/zahllauf/', daten)
        self.assertTrue(erste[1].startswith('application/xml'),
                        f'Voraussetzung: die erste Zahlungsdatei muss entstehen ({erste}). '
                        'Verlangt pain.001 inzwischen mehr Kreditor-Stammdaten (Adresse), '
                        'gehören sie in `kreditor()` oben.')
        zweite = self.post('/neu/zahllauf/', daten)
        self.assertFalse(zweite[1].startswith('application/xml'), zweite)
        for k in ks:
            k.refresh_from_db()
            self.assertEqual(k.status, 'in_zahlung')


@NUR_POSTGRES
class KreditorParallelTests(GeldPfadBasis):

    def test_vier_parallele_klicks_bezahlen_einmal(self):
        """FIN-02: vorher 4 Zahlungen über je 800 auf eine Rechnung über 800."""
        from finance.models import KreditorenZahlung
        k = self.kreditor()
        self.parallel_post(4, '/neu/kreditoren/bezahlen/', {'rechnung_id': k.pk})
        self.assertEqual(KreditorenZahlung.objects.filter(kreditor=k, status='verbucht').count(), 1)
        self.assertEqual(self.saldo('2000'), Decimal('800.00'))
        k.refresh_from_db()
        self.assertEqual(k.status, 'bezahlt')

    def test_drei_parallele_sammelbestaetigungen_buchen_je_rechnung_einmal(self):
        """FIN-02: vorher 8 Zahlungen, 4'000 statt 1'500."""
        from finance.models import KreditorenZahlung
        ks = [self.kreditor('500.00', lieferant=f'ZL{i} AG') for i in range(3)]
        self.parallel_post(3, '/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': [k.pk for k in ks]})
        self.assertEqual(KreditorenZahlung.objects.filter(kreditor__in=ks, status='verbucht').count(), 3)
        self.assertEqual(self.saldo('2000'), Decimal('1500.00'))

    def test_zwei_parallele_zahlungsdateien_liefern_die_rechnungen_nur_einmal(self):
        """FIN-02: vorher zwei XML-Dateien mit denselben drei Rechnungen."""
        ks = [self.kreditor('500.00', lieferant=f'ZD{i} AG') for i in range(3)]
        daten = {'aktion': 'datei', 'rechnung_ids': [k.pk for k in ks],
                 'ausfuehrungsdatum': timezone.localdate().isoformat()}
        antworten = self.parallel_post(2, '/neu/zahllauf/', daten)
        dateien = [a for a in antworten if not isinstance(a, BaseException) and a[1].startswith('application/xml')]
        self.assertEqual(len(dateien), 1, antworten)
        for k in ks:
            k.refresh_from_db()
            self.assertEqual(k.status, 'in_zahlung')


# ======================================================================
# FIN-04: Storno
# ======================================================================
class StornoFolgeTests(GeldPfadBasis):

    def _buchung(self):
        from finance.booking import buche
        return buche('1020', '3000', Decimal('50.00'), 'Testbuchung', liegenschaft=self.lg)

    def test_zweiter_storno_derselben_buchung_scheitert(self):
        from finance.booking import storniere_buchung
        b = self._buchung()
        storniere_buchung(b)
        veraltet = type(b).objects.get(pk=b.pk)     # Stand von VOR dem Storno nachgebaut
        veraltet.storniert_am = None
        with self.assertRaises(ValueError):
            storniere_buchung(veraltet)             # der Zustand wird neu gelesen, nicht geglaubt

    def test_journal_storno_zweimal_erzeugt_eine_gegenbuchung(self):
        from finance.models import Buchung
        b = self._buchung()
        self.post(f'/neu/buchhaltung/buchung/{b.pk}/stornieren/')
        self.post(f'/neu/buchhaltung/buchung/{b.pk}/stornieren/')
        self.assertEqual(Buchung.objects.filter(storno_von=b).count(), 1)

    def test_rechnung_stornieren_zweimal_kehrt_einmal_um(self):
        from finance.models import Buchung
        r = self.rechnung()
        self.post(f'/neu/debitoren/{r.pk}/stornieren/')
        self.post(f'/neu/debitoren/{r.pk}/stornieren/')
        self.assertEqual(Buchung.objects.filter(debitoren_rechnung=r, ist_storno=True).count(), 1)
        self.assertEqual(self.saldo('1100'), Decimal('0.00'))


@NUR_POSTGRES
class StornoParallelTests(GeldPfadBasis):

    def test_sechs_parallele_stornos_einer_buchung(self):
        """FIN-04: vorher 6 Gegenbuchungen, Netto-Wirkung -50 statt 0."""
        from finance.booking import buche
        from finance.models import Buchung
        b = buche('1020', '3000', Decimal('50.00'), 'Testbuchung', liegenschaft=self.lg)
        self.parallel_post(6, f'/neu/buchhaltung/buchung/{b.pk}/stornieren/')
        self.assertEqual(Buchung.objects.filter(storno_von=b).count(), 1)
        self.assertEqual(self.saldo('1020'), Decimal('0.00'))

    def test_acht_parallele_storniere_buchung_aufrufe(self):
        """Die Sperre im Dienst selbst, ohne Anfrage-Rauschen davor: Alle Threads laden
        die Buchung, dann stornieren sie gleichzeitig. Genau einer gewinnt, die
        übrigen sehen «bereits storniert». (Über die Maske staffeln sich die Anfragen so
        stark, dass die Sperre dort kaum noch den Ausschlag gibt.)"""
        from finance.booking import buche, storniere_buchung
        from finance.models import Buchung
        b = buche('1020', '3000', Decimal('50.00'), 'Testbuchung', liegenschaft=self.lg)

        def lauf(i):
            with organisation_kontext(self.org):
                frisch = Buchung.objects.get(pk=b.pk)
                try:
                    storniere_buchung(frisch)
                    return 'storniert'
                except ValueError:
                    return 'schon storniert'
        ergebnisse = parallel(8, lauf)
        for e in ergebnisse:
            self.assertIn(e, ('storniert', 'schon storniert'), e)
        self.assertEqual(ergebnisse.count('storniert'), 1, ergebnisse)
        self.assertEqual(Buchung.objects.filter(storno_von=b).count(), 1)
        self.assertEqual(self.saldo('1020'), Decimal('0.00'))

    def test_drei_parallele_rechnungsstornos(self):
        """FIN-04: vorher 8 statt 4 Buchungen, 1100 um 2'200 überstorniert."""
        from finance.models import Buchung
        r = self.rechnung('2200.00')
        self.parallel_post(3, f'/neu/debitoren/{r.pk}/stornieren/')
        self.assertEqual(Buchung.objects.filter(debitoren_rechnung=r).count(), 2)
        self.assertEqual(self.saldo('1100'), Decimal('0.00'))

    def test_parallele_zahlungsstornos(self):
        from finance.models import Buchung, Zahlungseingang
        r = self.rechnung()
        self.post('/neu/bankabgleich/verbuchen/', {'rechnung_id': r.pk})
        z = Zahlungseingang.objects.get(debitoren_rechnung=r, status='verbucht')
        self.parallel_post(4, f'/neu/zahlungen/{z.pk}/stornieren/')
        self.assertEqual(Buchung.objects.filter(zahlungseingang=z, ist_storno=True).count(), 1)
        self.assertEqual(self.saldo('1020'), Decimal('0.00'))


# ======================================================================
# FIN-05: Jahresabschluss, AfA, Fonds, camt-Import
# ======================================================================
class LaeufeFolgeTests(GeldPfadBasis):

    def _erfolg_2019(self):
        from finance.booking import buche
        buche('1100', '3000', Decimal('5000'), 'Ertrag 2019', datum=date(2019, 5, 5))
        buche('4000', '2000', Decimal('1200'), 'Aufwand 2019', datum=date(2019, 6, 5))

    def test_jahresabschluss_zweimal_bucht_einmal(self):
        from core.services.jahresabschluss import buche_jahresabschluss
        from finance.models import Buchung
        self._erfolg_2019()
        self.assertEqual(buche_jahresabschluss(2019)[0], 2)
        self.assertEqual(buche_jahresabschluss(2019)[0], 0)
        self.assertEqual(Buchung.objects.filter(beleg_text__startswith='Jahresabschluss 2019').count(), 2)

    def test_afa_lauf_zweimal_bucht_einmal(self):
        from core.services.automation import run_abschreibungen
        from finance.models import Abschreibung, Anlage, Buchung
        Anlage.objects.create(liegenschaft=self.lg, bezeichnung='Heizung', anschaffungswert=Decimal('10000'),
                              anschaffungsdatum=date(2018, 1, 1), nutzungsdauer_jahre=10)
        self.assertEqual(run_abschreibungen(2020)[0], 1)
        self.assertEqual(run_abschreibungen(2020)[0], 0)
        self.assertEqual(Abschreibung.objects.count(), 1)
        self.assertEqual(Buchung.objects.filter(beleg_text='Abschreibung 2020: Heizung').count(), 1)

    def test_fonds_einlage_zweimal_bucht_einmal(self):
        from core.services.automation import run_erneuerungsfonds_einlage
        from finance.models import Buchung, Erneuerungsfonds
        self.lg.typ = 'MIETE'
        self.lg.save()
        Erneuerungsfonds.objects.create(liegenschaft=self.lg, jaehrliche_einlage=Decimal('1000'))
        self.assertEqual(run_erneuerungsfonds_einlage(2020)[0], 1)
        self.assertEqual(run_erneuerungsfonds_einlage(2020)[0], 0)
        self.assertEqual(Buchung.objects.filter(beleg_text__startswith='Einlage Erneuerungsfonds 2020').count(), 1)


@NUR_POSTGRES
class LaeufeParallelTests(GeldPfadBasis):

    def test_drei_parallele_jahresabschluesse(self):
        """FIN-05: vorher 6 statt 2 Abschlussbuchungen, 2970 = 11'400 statt 3'800."""
        from core.services.jahresabschluss import buche_jahresabschluss
        from finance.booking import buche
        from finance.models import Buchung
        buche('1100', '3000', Decimal('5000'), 'Ertrag 2019', datum=date(2019, 5, 5))
        buche('4000', '2000', Decimal('1200'), 'Aufwand 2019', datum=date(2019, 6, 5))

        def abschluss(i):
            with organisation_kontext(self.org):
                return buche_jahresabschluss(2019)
        ergebnisse = parallel(3, abschluss)
        for e in ergebnisse:
            self.assertNotIsInstance(e, BaseException, e)
        self.assertEqual(Buchung.objects.filter(beleg_text__startswith='Jahresabschluss 2019').count(), 2)
        self.assertEqual(-self.saldo('2970'), Decimal('3800.00'))
        self.assertEqual(sorted(e[0] for e in ergebnisse), [0, 0, 2])

    def test_jahresabschluss_parallel_ueber_die_maske(self):
        """Der Doppelklick auf «Jahresabschluss buchen»: Die Verlierer melden «bereits
        abgeschlossen» statt «keine Erfolgsbuchungen», und gebucht wird einmal."""
        from finance.booking import buche
        from finance.models import Buchung
        buche('1100', '3000', Decimal('5000'), 'Ertrag 2019', datum=date(2019, 5, 5))
        buche('4000', '2000', Decimal('1200'), 'Aufwand 2019', datum=date(2019, 6, 5))
        antworten = self.parallel_post(3, '/neu/buchhaltung/', {'aktion': 'jahresabschluss', 'jahr': '2019'})
        for a in antworten:
            self.assertEqual(a[0], 302, a)
        self.assertEqual(Buchung.objects.filter(beleg_text__startswith='Jahresabschluss 2019').count(), 2)
        meldungen = [m for a in antworten for m in a[2]]
        self.assertFalse(any('keine Erfolgsbuchungen' in m for m in meldungen), meldungen)

    def test_drei_parallele_afa_laeufe(self):
        """FIN-05: vorher 3 AfA-Buchungen, aber nur 1 Abschreibungsdatensatz."""
        from core.services.automation import run_abschreibungen
        from finance.models import Abschreibung, Anlage, Buchung
        Anlage.objects.create(liegenschaft=self.lg, bezeichnung='Heizung', anschaffungswert=Decimal('10000'),
                              anschaffungsdatum=date(2018, 1, 1), nutzungsdauer_jahre=10)

        def lauf(i):
            with organisation_kontext(self.org):
                return run_abschreibungen(2020)
        ergebnisse = parallel(3, lauf)
        for e in ergebnisse:
            self.assertNotIsInstance(e, BaseException, e)
        self.assertEqual(Abschreibung.objects.count(), 1)
        self.assertEqual(Buchung.objects.filter(beleg_text='Abschreibung 2020: Heizung').count(), 1)

    def test_drei_parallele_fonds_laeufe(self):
        from core.services.automation import run_erneuerungsfonds_einlage
        from finance.models import Buchung, Erneuerungsfonds
        self.lg.typ = 'MIETE'
        self.lg.save()
        f = Erneuerungsfonds.objects.create(liegenschaft=self.lg, jaehrliche_einlage=Decimal('1000'))

        def lauf(i):
            with organisation_kontext(self.org):
                return run_erneuerungsfonds_einlage(2020)
        for e in parallel(3, lauf):
            self.assertNotIsInstance(e, BaseException, e)
        f.refresh_from_db()
        self.assertEqual(f.bestand, Decimal('1000.00'))
        self.assertEqual(Buchung.objects.filter(beleg_text__startswith='Einlage Erneuerungsfonds 2020').count(), 1)


def _camt_datei(anzahl, praefix='PG'):
    """Ein minimaler camt.053 mit `anzahl` Gutschriften, je mit eigener Bank-Referenz."""
    eintraege = ''.join(
        f'<Ntry><NtryRef>{praefix}{i}</NtryRef><Amt Ccy="CHF">100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>'
        f'<Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>2026-09-05</Dt></BookgDt><ValDt><Dt>2026-09-05</Dt></ValDt>'
        f'<AcctSvcrRef>{praefix}{i}</AcctSvcrRef><NtryDtls><TxDtls><Refs><EndToEndId>NOTPROVIDED</EndToEndId></Refs>'
        f'<RltdPties><Dbtr><Pty><Nm>Zahler {i}</Nm></Pty></Dbtr></RltdPties></TxDtls></NtryDtls></Ntry>'
        for i in range(anzahl))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt>'
        '<GrpHdr><MsgId>M1</MsgId><CreDtTm>2026-10-01T00:00:00</CreDtTm></GrpHdr>'
        '<Stmt><Id>S1</Id><FrToDt><FrDtTm>2026-09-01T00:00:00</FrDtTm><ToDtTm>2026-09-30T23:59:59</ToDtTm></FrToDt>'
        '<Acct><Id><IBAN>CH9300762011623852957</IBAN></Id></Acct>'
        + eintraege + '</Stmt></BkToCstmrStmt></Document>').encode()


class CamtImportFolgeTests(GeldPfadBasis):

    def _import(self, xml):
        datei = SimpleUploadedFile('auszug.xml', xml, content_type='text/xml')
        antwort = self.neuer_client().post('/neu/bankabgleich/camt-import/', {'camt_datei': datei})
        return antwort.status_code, [str(m) for m in get_messages(antwort.wsgi_request)]

    def test_zweiter_import_derselben_datei_bucht_nichts(self):
        from finance.models import Zahlungseingang
        xml = _camt_datei(4)
        self._import(xml)
        n = Zahlungseingang.objects.count()
        self.assertEqual(n, 4)
        self._import(xml)
        self.assertEqual(Zahlungseingang.objects.count(), 4)


@NUR_POSTGRES
class CamtImportParallelTests(CamtImportFolgeTests):

    def test_zwei_parallele_importe_derselben_datei(self):
        """FIN-05: vorher 21 statt 20 Zahlungen (eine Bank-Referenz doppelt)."""
        from django.db.models import Count
        from finance.models import Zahlungseingang
        xml = _camt_datei(20)
        parallel(2, lambda i: self._import(xml))
        self.assertEqual(Zahlungseingang.objects.count(), 20)
        doppelt = (Zahlungseingang.objects.values('bank_referenz').annotate(c=Count('id'))
                   .filter(c__gt=1).count())
        self.assertEqual(doppelt, 0)


# ======================================================================
# SICH-44: Belegnummer unter Stoss
# ======================================================================
@NUR_POSTGRES
class BelegNummerStossTests(GeldPfadBasis):

    def test_sechzehn_schreiber_bekommen_luckenlose_nummern(self):
        """SICH-44: vorher brachen bei 8 Schreibern 4 bis 5 mit
        `uniq_beleg_nr_je_organisation` ab; die Wiederholung ohne Wartezeit
        reichte nicht."""
        from finance.models import Buchung, Buchungskonto
        bank = Buchungskonto.objects.get(nummer='1020')
        ertrag = Buchungskonto.objects.get(nummer='3000')

        def schreibe(i):
            with organisation_kontext(self.org):
                for j in range(10):
                    Buchung.objects.create(
                        datum=date(2026, 3, 1), beleg_text=f'Stoss {i}-{j}',
                        soll_konto=bank, haben_konto=ertrag, betrag=Decimal('1.00'))
            return i
        ergebnisse = parallel(16, schreibe)
        fehler = [e for e in ergebnisse if isinstance(e, BaseException)]
        self.assertEqual(fehler, [], fehler)
        nummern = sorted(Buchung.objects.values_list('beleg_nr', flat=True))
        self.assertEqual(nummern, list(range(1, 161)),
                         'Belegnummern müssen je Organisation lückenlos und eindeutig sein.')

    def test_zwei_organisationen_blockieren_sich_nicht_und_zaehlen_getrennt(self):
        from crm.models import Organisation
        from finance.booking import ensure_kontenplan
        from finance.models import Buchung, Buchungskonto
        andere = Organisation.objects.create(firma='Andere AG', strasse='X 1', plz='3000', ort='Bern')
        with organisation_kontext(andere):
            ensure_kontenplan()

        def schreibe(i):
            org = self.org if i % 2 == 0 else andere
            with organisation_kontext(org):
                bank = Buchungskonto.objects.get(nummer='1020')
                ertrag = Buchungskonto.objects.get(nummer='3000')
                for j in range(5):
                    Buchung.objects.create(datum=date(2026, 3, 1), beleg_text='x', soll_konto=bank,
                                           haben_konto=ertrag, betrag=Decimal('1.00'))
        for e in parallel(8, schreibe):
            self.assertNotIsInstance(e, BaseException, e)
        for org in (self.org, andere):
            nummern = sorted(Buchung.alle_organisationen.filter(organisation=org)
                             .values_list('beleg_nr', flat=True))
            self.assertEqual(nummern, list(range(1, 21)))


class BelegNummerFolgeTests(GeldPfadBasis):

    def test_nummern_zaehlen_je_organisation_ab_eins(self):
        from finance.booking import buche
        a = buche('1020', '3000', Decimal('1.00'), 'a')
        b = buche('1020', '3000', Decimal('1.00'), 'b')
        self.assertEqual((a.beleg_nr, b.beleg_nr), (1, 2))

    def test_sperre_ausserhalb_einer_transaktion_ist_ein_programmfehler(self):
        """Eine Sperre ausserhalb von `atomic` wäre sofort wieder frei. Das muss
        laut sein — auch auf SQLite, wo die Sperre sonst wirkungslos ist."""
        from django.db.transaction import TransactionManagementError
        from core.sperren import sperre
        with self.assertRaises(TransactionManagementError):
            sperre('test')


# ======================================================================
# Weitere Geldpfade desselben Musters (Etappe 0, «alle Pfade»)
# ======================================================================
class _WeitereWegeBasis(GeldPfadBasis):

    def _kaution_einbezahlt(self):
        from finance.booking import buche
        v = self.vertrag
        v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = date(2024, 1, 1)
        v.save()
        buche('1015', '2010', Decimal('4500'), f'Mietkaution [V{v.pk}] Einzahlung',
              datum=date(2024, 1, 1), liegenschaft=self.lg)

    def _honorar_aufbau(self, liegenschaften=5):
        """Ein Eigentümer mit mehreren Liegenschaften und je 10'000 Mietertrag 2025:
        Je mehr Zeilen, desto länger das Fenster zwischen «schon gebucht?» und dem Buchen."""
        from crm.models import Eigentuemer
        from finance.booking import buche
        from portfolio.models import Liegenschaft
        md = Eigentuemer.objects.create(firma_oder_name='Honorar AG', honorar_prozent=Decimal('4.00'))
        lgs = [self.lg] + [Liegenschaft.objects.create(strasse=f'Honorarweg {i}', plz='8000', ort='Zürich',
                                                        organisation=self.org)
                           for i in range(liegenschaften - 1)]
        for lg in lgs:
            lg.eigentuemer = md
            lg.save()
            buche('1020', '3000', Decimal('10000'), 'Miete 2025', datum=date(2025, 5, 1), liegenschaft=lg)
        return md, len(lgs)

    def _rueckzahlen(self):
        return self.post(f'/neu/vertraege/{self.vertrag.pk}/kaution/', {
            'aktion': 'rueckzahlung', 'abzug_betrag': '500', 'zurueckbezahlt_am': '2024-07-01'})

    def _aufloesung(self):
        from finance.models import Buchung
        return Buchung.objects.filter(beleg_text__startswith=f'Kaution Auflösung [V{self.vertrag.pk}]',
                                      ist_storno=False)


class WeitereWegeFolgeTests(_WeitereWegeBasis):

    def test_kaution_rueckzahlung_zweimal_loest_einmal_auf(self):
        self._kaution_einbezahlt()
        self._rueckzahlen()
        zweite = self._rueckzahlen()
        self.assertEqual(self._aufloesung().count(), 3)         # Freigabe, Rückzahlung, Einbehalt
        self.assertTrue(any('keine Kaution bilanziert' in m for m in zweite[2]), zweite[2])

    def test_schlussabrechnung_zweimal_stellt_eine_nachzahlung(self):
        from finance.models import DebitorenRechnung
        daten = {'aktion': 'buchen', 'auszug_datum': '2024-06-30', 'pos_text': 'Reinigung',
                 'pos_betrag': '300', 'pos_richtung': 'zulasten', 'pos_mwst': '0'}
        url = f'/neu/vertraege/{self.vertrag.pk}/schlussabrechnung/'
        self.post(url, daten)
        self.post(url, daten)
        self.assertEqual(DebitorenRechnung.objects.filter(
            vertrag=self.vertrag, titel='Schlussabrechnung (Nachzahlung)').count(), 1)

    def test_honorar_zweimal_wird_je_liegenschaft_einmal_gebucht(self):
        from finance.models import Buchung
        md, n = self._honorar_aufbau()
        url = f'/neu/mandate/{md.pk}/honorar/'
        self.post(url, {'jahr': '2025', 'konto_nummer': '2850'})
        self.post(url, {'jahr': '2025', 'konto_nummer': '2850'})
        self.assertEqual(Buchung.objects.filter(soll_konto__nummer='4500', ist_storno=False).count(), n)

    def test_bankbewegung_zweimal_verbuchen_bucht_einmal(self):
        from finance.models import Bankbewegung, Buchung, Buchungskonto
        bank = Buchungskonto.objects.get(nummer='1020')
        bew = Bankbewegung.objects.create(konto=bank, datum=date(2026, 3, 5), betrag=Decimal('-120.00'),
                                          text='Bankgebühr', bank_referenz='BG-1', status='offen')
        daten = {'bewegung_id': bew.pk, 'art': 'konto', 'gegenkonto': '4000'}
        self.post('/neu/bankabgleich/bewegung/', daten)
        zweite = self.post('/neu/bankabgleich/bewegung/', daten)
        self.assertEqual(Buchung.objects.filter(soll_konto__nummer='4000', haben_konto__nummer='1020').count(), 1)
        self.assertTrue(any('erledigt' in m for m in zweite[2]), zweite[2])


@NUR_POSTGRES
class WeitereWegeParallelTests(_WeitereWegeBasis):

    def test_kaution_rueckzahlung_parallel(self):
        """Vorher löste jeder der drei Klicks das Sperrkonto auf (Freigabe mehrfach)."""
        self._kaution_einbezahlt()
        parallel(3, lambda i: self._rueckzahlen())
        self.assertEqual(self._aufloesung().count(), 3)

    def test_schlussabrechnung_parallel(self):
        from finance.models import DebitorenRechnung
        daten = {'aktion': 'buchen', 'auszug_datum': '2024-06-30', 'pos_text': 'Reinigung',
                 'pos_betrag': '300', 'pos_richtung': 'zulasten', 'pos_mwst': '0'}
        self.parallel_post(3, f'/neu/vertraege/{self.vertrag.pk}/schlussabrechnung/', daten)
        self.assertEqual(DebitorenRechnung.objects.filter(
            vertrag=self.vertrag, titel='Schlussabrechnung (Nachzahlung)').count(), 1)

    def test_honorar_parallel(self):
        """Vorher buchten gleichzeitige Klicks das Honorar mehrfach (der Wächter «schon
        gebucht?» las den Belegtext vor dem Buchen)."""
        from finance.models import Buchung
        md, n = self._honorar_aufbau()
        self.parallel_post(4, f'/neu/mandate/{md.pk}/honorar/', {'jahr': '2025', 'konto_nummer': '2850'})
        self.assertEqual(Buchung.objects.filter(soll_konto__nummer='4500', ist_storno=False).count(), n)

    def test_bankbewegung_parallel(self):
        from finance.models import Bankbewegung, Buchung, Buchungskonto
        bank = Buchungskonto.objects.get(nummer='1020')
        bew = Bankbewegung.objects.create(konto=bank, datum=date(2026, 3, 5), betrag=Decimal('-120.00'),
                                          text='Bankgebühr', bank_referenz='BG-1', status='offen')
        self.parallel_post(4, '/neu/bankabgleich/bewegung/',
                           {'bewegung_id': bew.pk, 'art': 'konto', 'gegenkonto': '4000'})
        self.assertEqual(Buchung.objects.filter(soll_konto__nummer='4000', haben_konto__nummer='1020').count(), 1)

    def test_mwst_verbuchen_parallel(self):
        """Zwei gleichzeitige Klicks auf «MWST verbuchen» buchten die Zahllast doppelt."""
        from finance.booking import buche
        from finance.models import Buchung
        buche('1100', '2200', Decimal('810'), 'MWST 8.1% Test', datum=date(2025, 3, 1), liegenschaft=self.lg)
        antworten = self.parallel_post(3, '/neu/mwst/verbuchen/', {'jahr': '2025', 'quartal': ''})
        for a in antworten:
            self.assertEqual(a[0], 302, a)
        self.assertEqual(Buchung.objects.filter(beleg_text__contains='Zahllast ESTV').count(), 1)
