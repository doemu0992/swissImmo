"""Zahlungs-Cockpit V12: Sonderfälle im Zahlungseingang (26.10.2026).

Geprüft wird an den Buchungen, nicht an der Oberfläche: Eine Aufteilung
bucht je Teil Parkkonto an 1100, ein Rest landet dort, wofür er bestimmt ist,
ein Storno hebt die ganze Aufteilung auf. Eine Kaution vom Mietzinskonto zählt
für die Kaution und wird nicht doppelt gebucht. Eine Rückbuchung öffnet die
Rechnung wieder. Ein Guthaben «mit nächster Rechnung» tilgt die Sollstellung.
Und ein Benutzer einer fremden Verwaltung sieht nichts davon (404).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.test import Client, TestCase
from django.utils import timezone

from core.tests._helfer import _basis_objekte, _seed_konten, _team_user
from core.tests._isolation import MandantenFixture


def _kontoblatt(nummer):
    """Saldo wie im Kontoblatt: alle Buchungen, Storno-Gegenbuchungen inklusive."""
    from finance.models import Buchung
    soll = Buchung.objects.filter(soll_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
    haben = Buchung.objects.filter(haben_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
    return soll - haben


class _Basis(TestCase):
    def setUp(self):
        _seed_konten()
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = timezone.localdate()
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))

    def zweiter_vertrag(self, nachname='Keller', kaution='0'):
        from crm.models import Mieter
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung=f'PP {nachname}', typ='pp',
                                   nettomiete_aktuell=Decimal('100'))
        m = Mieter.objects.create(typ='person', vorname='Tom', nachname=nachname,
                                  email=f'{nachname.lower()}@example.ch')
        return Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                          netto_mietzins=Decimal('100'), nebenkosten=Decimal('0'),
                                          status='aktiv', kautions_betrag=Decimal(kaution))

    def rechnung(self, vertrag, betrag, titel='Miete', tage=10):
        from finance.models import DebitorenRechnung
        f = self.heute - timedelta(days=tage)
        return DebitorenRechnung.objects.create(vertrag=vertrag, titel=titel, datum=f, faellig_am=f,
                                                betrag=Decimal(betrag))

    def geparkt(self, betrag, name='SOZIALDIENST BERN', text='Miete Muster/Keller', tage=3, konto='1190',
                vertrag=None, ref='REF-1'):
        """Eine Bankgutschrift, die auf dem Park- oder Guthabenkonto liegt — wie nach dem Import."""
        from finance.booking import buche, konto as _konto
        from finance.models import Bankbewegung, Zahlungseingang
        d = self.heute - timedelta(days=tage)
        z = Zahlungseingang.objects.create(betrag=Decimal(betrag), datum_eingang=d,
                                           bemerkung=f'camt UNGEKLÄRT: {name}', konto=_konto(konto),
                                           vertrag=vertrag, bank_referenz=ref, status='verbucht')
        buche('1020', konto, Decimal(betrag), f'camt {name}', datum=d, zahlung=z)
        Bankbewegung.objects.create(konto=_konto('1020'), datum=d, betrag=Decimal(betrag), gegenpartei=name,
                                    text=text, bank_referenz=ref, status='verbucht', zahlung=z)
        return z


class AufteilenTests(_Basis):
    def test_sammelzahlung_tilgt_zwei_vertraege_zweier_mieter(self):
        from finance.models import ZahlerZuordnung, Zahlungseingang
        v2 = self.zweiter_vertrag()
        r1, r2 = self.rechnung(self.v, '100'), self.rechnung(v2, '100')
        z = self.geparkt('200.00')
        antwort = self.c.post(f'/neu/bankabgleich/zahlung/{z.id}/aufteilen/',
                              {f'teil_{r1.id}': '100', f'teil_{r2.id}': '100.00', 'rest_ziel': 'offen'})
        self.assertEqual(antwort.status_code, 302)
        r1.refresh_from_db(); r2.refresh_from_db()
        self.assertEqual((r1.status, r2.status), ('bezahlt', 'bezahlt'))
        self.assertEqual(_kontoblatt('1190'), Decimal('0.00'))
        self.assertEqual(_kontoblatt('1100'), Decimal('-200.00'))
        teile = Zahlungseingang.objects.filter(status='verbucht', bank_referenz__startswith='REF-1')
        self.assertEqual(sorted(t.bank_referenz for t in teile), ['REF-1', 'REF-1:teil2'])
        # Zwei Mieter: der Absender wird NICHT gelernt — die nächste Zuordnung wäre geraten.
        self.assertFalse(ZahlerZuordnung.objects.exists())

    def test_teilbetrag_und_rest_als_guthaben(self):
        from finance.models import Zahlungseingang
        r = self.rechnung(self.v, '1410')
        z = self.geparkt('1500.00', name='Hans Muster')
        self.c.post(f'/neu/bankabgleich/zahlung/{z.id}/aufteilen/',
                    {f'teil_{r.id}': '1300', 'rest_ziel': 'guthaben', 'rest_vertrag': self.v.id})
        r.refresh_from_db()
        self.assertEqual(r.status, 'teilbezahlt')
        self.assertEqual(r.offener_betrag, Decimal('110.00'))
        g = Zahlungseingang.objects.get(bank_referenz='REF-1:rest')
        self.assertEqual((g.konto.nummer, g.vertrag_id, g.betrag), ('2030', self.v.id, Decimal('200.00')))
        self.assertEqual(g.guthaben_verwendung, 'naechste_rechnung')
        self.assertEqual(_kontoblatt('2030'), Decimal('-200.00'))
        self.assertEqual(_kontoblatt('1190'), Decimal('0.00'))

    def test_rest_bleibt_ungeklaert_und_storno_eines_teils_hebt_alles_auf(self):
        from finance.models import Zahlungseingang
        v2 = self.zweiter_vertrag()
        r1, r2 = self.rechnung(self.v, '100'), self.rechnung(v2, '100')
        z = self.geparkt('250.00')
        self.c.post(f'/neu/bankabgleich/zahlung/{z.id}/aufteilen/',
                    {f'teil_{r1.id}': '100', 'rest_ziel': 'offen'})
        rest = Zahlungseingang.objects.get(bank_referenz='REF-1:offen')
        self.assertEqual((rest.konto.nummer, rest.betrag), ('1190', Decimal('150.00')))
        self.assertEqual(_kontoblatt('1190'), Decimal('-150.00'))
        # Der ungeklärte Rest wird später selbst aufgeteilt …
        self.c.post(f'/neu/bankabgleich/zahlung/{rest.id}/aufteilen/',
                    {f'teil_{r2.id}': '100', 'rest_ziel': 'offen'})
        teil = Zahlungseingang.objects.get(debitoren_rechnung=r2, status='verbucht')
        # … und der Storno EINES Teils hebt die ganze Zahlung auf: Ein einzelner
        # Teil allein hinterliesse Geld auf 1190, das keine Zeile erklärt.
        self.c.post(f'/neu/zahlungen/{teil.id}/stornieren/', {})
        self.assertFalse(Zahlungseingang.objects.filter(bank_referenz__startswith='REF-1', status='verbucht').exists())
        r1.refresh_from_db(); r2.refresh_from_db()
        self.assertEqual((r1.status, r2.status), ('offen', 'offen'))
        for nummer in ('1190', '1100', '1020'):
            self.assertEqual(_kontoblatt(nummer), Decimal('0.00'), nummer)

    def test_rest_zurueck_an_den_absender(self):
        r = self.rechnung(self.v, '100')
        z = self.geparkt('130.00')
        self.c.post(f'/neu/bankabgleich/zahlung/{z.id}/aufteilen/',
                    {f'teil_{r.id}': '100', 'rest_ziel': 'zurueck'})
        self.assertEqual(_kontoblatt('1190'), Decimal('0.00'))
        self.assertEqual(_kontoblatt('1020'), Decimal('100.00'))

    def test_sachbearbeitung_darf_nicht_zurueckueberweisen(self):
        from finance.models import Zahlungseingang
        r = self.rechnung(self.v, '100')
        z = self.geparkt('130.00')
        c = Client(); c.force_login(_team_user('Sachbearbeiter'))
        c.post(f'/neu/bankabgleich/zahlung/{z.id}/aufteilen/',
               {f'teil_{r.id}': '100', 'rest_ziel': 'zurueck'})
        z.refresh_from_db()
        self.assertEqual(z.konto.nummer, '1190', 'Nichts darf gebucht sein')
        self.assertFalse(Zahlungseingang.objects.filter(debitoren_rechnung=r).exists())

    def test_ungueltige_zuteilungen_buchen_nichts(self):
        from finance.models import Zahlungseingang
        v2 = self.zweiter_vertrag()
        r = self.rechnung(self.v, '100')
        r2 = self.rechnung(v2, '100')
        z = self.geparkt('500.00')
        faelle = [
            {f'teil_{r.id}': '150'},                                    # mehr als offen
            {f'teil_{r.id}': '100', f'teil_{r2.id}': 'abc'},             # kein Betrag
            {f'teil_{r.id}': '100', 'rest_ziel': 'guthaben'},            # Guthaben ohne Mieter
            {},                                                         # nichts zugeteilt
        ]
        for daten in faelle:
            with self.subTest(daten=daten):
                self.c.post(f'/neu/bankabgleich/zahlung/{z.id}/aufteilen/', {'rest_ziel': 'offen', **daten})
                z.refresh_from_db()
                self.assertEqual((z.konto.nummer, z.betrag), ('1190', Decimal('500.00')))
                self.assertFalse(Zahlungseingang.objects.filter(debitoren_rechnung__isnull=False).exists())
        # Mehr zugeteilt als die Zahlung: 2 × 100 auf eine Zahlung von 150
        z2 = self.geparkt('150.00', ref='REF-2')
        self.c.post(f'/neu/bankabgleich/zahlung/{z2.id}/aufteilen/',
                    {f'teil_{r.id}': '100', f'teil_{r2.id}': '100', 'rest_ziel': 'offen'})
        self.assertFalse(Zahlungseingang.objects.filter(debitoren_rechnung__isnull=False).exists())

    def test_guthaben_tilgt_keine_forderung_eines_anderen_mieters(self):
        v2 = self.zweiter_vertrag()
        r2 = self.rechnung(v2, '100')
        g = self.geparkt('100.00', konto='2030', vertrag=self.v, name='Hans Muster')
        self.c.post(f'/neu/bankabgleich/zahlung/{g.id}/aufteilen/', {f'teil_{r2.id}': '100', 'rest_ziel': 'guthaben'})
        r2.refresh_from_db()
        self.assertEqual(r2.status, 'offen')

    def test_seite_schlaegt_die_genannten_mieter_vor_und_fuellt_vor(self):
        v2 = self.zweiter_vertrag()
        r1, r2 = self.rechnung(self.v, '100'), self.rechnung(v2, '100')
        z = self.geparkt('200.00')
        html = self.c.get(f'/neu/bankabgleich/zahlung/{z.id}/aufteilen/').content.decode()
        self.assertIn('Sammelzahlung', html)
        self.assertIn(f'name="teil_{r1.id}"', html)
        self.assertIn(f'name="teil_{r2.id}"', html)
        self.assertEqual(html.count('value="100.00"'), 2, 'Beide Posten sind mit 100.00 vorbefüllt')

    def test_suche_findet_nach_name_und_betrag(self):
        v2 = self.zweiter_vertrag()
        r2 = self.rechnung(v2, '123.45')
        z = self.geparkt('50.00', name='', text='')
        for q in ('Keller', '123.45', "123,45"):
            with self.subTest(q=q):
                html = self.c.get(f'/neu/bankabgleich/zahlung/{z.id}/aufteilen/',
                                  {'q': q, 'fragment': '1'}).content.decode()
                self.assertIn(f'name="teil_{r2.id}"', html)


class ZurueckUndKautionTests(_Basis):
    def test_fremdeingang_geht_an_den_absender_zurueck(self):
        z = self.geparkt('85.00', name='Unbekannt AG')
        self.c.post('/neu/bankabgleich/guthaben/rueckerstatten/', {'zahlung_id': z.id})
        z.refresh_from_db()
        self.assertIsNone(z.konto)
        self.assertEqual(_kontoblatt('1190'), Decimal('0.00'))
        self.assertEqual(_kontoblatt('1020'), Decimal('0.00'))

    def test_rueckerstattetes_guthaben_steht_nicht_mehr_im_mieterkonto(self):
        from core.services.mieterkonto import berechne_mieterkonto, berechne_vertragskonto, saldi_fuer_mieter
        self.rechnung(self.v, '100')
        g = self.geparkt('300.00', konto='2030', vertrag=self.v, name='Hans Muster')
        self.assertEqual(berechne_mieterkonto(self.m)[1], Decimal('-200.00'))
        self.c.post('/neu/bankabgleich/guthaben/rueckerstatten/', {'zahlung_id': g.id})
        # Vorher blieb das Guthaben im Konto stehen, obwohl das Geld zurück ist.
        self.assertEqual(berechne_mieterkonto(self.m)[1], Decimal('100.00'))
        self.assertEqual(berechne_vertragskonto(self.v)[1], Decimal('100.00'))
        self.assertEqual(saldi_fuer_mieter([self.m])[self.m.id], Decimal('100.00'))

    def test_kaution_vom_mietzinskonto_wird_einmal_bilanziert(self):
        from core.models import Pendenz
        from core.services.automation import buche_kaution_einzahlung
        from core.views.fw._basis import _kaution_bilanziert
        z = self.geparkt('4500.00', name='Hans Muster', text='Depot')
        self.c.post(f'/neu/bankabgleich/zahlung/{z.id}/kaution/', {'vertrag_id': self.v.id})
        self.v.refresh_from_db(); z.refresh_from_db()
        self.assertEqual(_kaution_bilanziert(self.v), Decimal('4500.00'))
        self.assertEqual(_kontoblatt('2010'), Decimal('-4500.00'))
        self.assertEqual(_kontoblatt('1190'), Decimal('0.00'))
        self.assertIsNotNone(self.v.kautions_einbezahlt_am)
        self.assertIsNone(z.vertrag_id, 'Eine Kaution ist kein Haben im Mieterkonto')
        self.assertTrue(Pendenz.objects.filter(quelle=f'auto:kaution-sperrkonto:{z.id}').exists())
        # Die spätere Bestätigung der Einzahlung bucht nicht ein zweites Mal.
        self.assertIsNone(buche_kaution_einzahlung(self.v, self.heute))
        self.assertEqual(_kontoblatt('2010'), Decimal('-4500.00'))

    def test_kaution_mit_falschem_betrag_wird_abgelehnt(self):
        z = self.geparkt('4000.00')
        self.c.post(f'/neu/bankabgleich/zahlung/{z.id}/kaution/', {'vertrag_id': self.v.id})
        z.refresh_from_db()
        self.assertEqual(z.konto.nummer, '1190')
        self.assertEqual(_kontoblatt('2010'), Decimal('0.00'))


class RueckbuchungTests(_Basis):
    def test_rueckbuchung_oeffnet_die_rechnung_wieder(self):
        from finance.booking import buche, konto
        from finance.models import Bankbewegung, Zahlungseingang
        r = self.rechnung(self.v, '1300')
        z = Zahlungseingang.objects.create(vertrag=self.v, debitoren_rechnung=r, betrag=Decimal('1300'),
                                           datum_eingang=self.heute - timedelta(days=5), status='verbucht',
                                           bank_referenz='TX-9')
        buche('1020', '1100', Decimal('1300'), 'Zahlung', datum=z.datum_eingang, zahlung=z)
        r.status = 'bezahlt'; r.save()
        bew = Bankbewegung.objects.create(konto=konto('1020'), datum=self.heute, betrag=Decimal('-1300'),
                                          text='Rückbuchung', bank_referenz='RUECK-1', status='offen')
        html = self.c.get('/neu/bankabgleich/').content.decode()
        self.assertIn('Als Rückbuchung erfassen', html)
        self.c.post('/neu/bankabgleich/bewegung/', {'bewegung_id': bew.id, 'art': 'rueckbuchung',
                                                     'zahlung_id': z.id})
        r.refresh_from_db(); z.refresh_from_db(); bew.refresh_from_db()
        self.assertEqual((r.status, z.status, bew.status), ('offen', 'storniert', 'verbucht'))
        # Die Gegenbuchung IST die Belastung: Bank und Debitoren stehen wie vor der Zahlung.
        self.assertEqual(_kontoblatt('1020'), Decimal('0.00'))
        self.assertEqual(_kontoblatt('1100'), Decimal('0.00'))

    def test_falscher_betrag_ist_keine_rueckbuchung(self):
        from finance.booking import buche, konto
        from finance.models import Bankbewegung, Zahlungseingang
        r = self.rechnung(self.v, '1300')
        z = Zahlungseingang.objects.create(vertrag=self.v, debitoren_rechnung=r, betrag=Decimal('1300'),
                                           datum_eingang=self.heute, status='verbucht')
        buche('1020', '1100', Decimal('1300'), 'Zahlung', datum=self.heute, zahlung=z)
        bew = Bankbewegung.objects.create(konto=konto('1020'), datum=self.heute, betrag=Decimal('-1200'),
                                          bank_referenz='RUECK-2', status='offen')
        self.c.post('/neu/bankabgleich/bewegung/', {'bewegung_id': bew.id, 'art': 'rueckbuchung',
                                                     'zahlung_id': z.id})
        z.refresh_from_db(); bew.refresh_from_db()
        self.assertEqual((z.status, bew.status), ('verbucht', 'offen'))


class GuthabenVerrechnenTests(_Basis):
    def test_sollstellung_verrechnet_das_vorgesehene_guthaben(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        g = self.geparkt('300.00', konto='2030', vertrag=self.v, name='Hans Muster')
        offen_gelassen = self.geparkt('50.00', konto='2030', vertrag=self.v, name='Hans Muster', ref='REF-2')
        offen_gelassen.guthaben_verwendung = 'offen'; offen_gelassen.save()
        run_sollstellung(self.heute.year, self.heute.month)
        r = DebitorenRechnung.objects.get(titel=f'Miete & NK {self.heute.month:02d}/{self.heute.year}')
        self.assertEqual(r.status, 'teilbezahlt')
        self.assertEqual(r.offener_betrag, r.betrag - Decimal('300.00'))
        g.refresh_from_db(); offen_gelassen.refresh_from_db()
        self.assertEqual((g.konto, g.debitoren_rechnung_id), (None, r.id))
        self.assertEqual(offen_gelassen.konto.nummer, '2030', '«Offen lassen» wird nicht verrechnet')

    def test_nk_reservierung_wartet_auf_die_nk_abrechnung(self):
        from core.services.zahlungsklaerung import guthaben_verrechnen
        r = self.rechnung(self.v, '120', titel='NK-Abrechnung Nachzahlung')
        g = self.geparkt('100.00', konto='2030', vertrag=self.v, name='Hans Muster')
        g.guthaben_verwendung = 'nk_abrechnung'; g.save()
        self.assertEqual(guthaben_verrechnen([self.v.id]), (0, Decimal('0.00')))
        anzahl, summe = guthaben_verrechnen([self.v.id], arten=('naechste_rechnung', 'nk_abrechnung'))
        self.assertEqual((anzahl, summe), (1, Decimal('100.00')))
        r.refresh_from_db()
        self.assertEqual(r.offener_betrag, Decimal('20.00'))

    def test_verwendung_laesst_sich_umstellen(self):
        g = self.geparkt('100.00', konto='2030', vertrag=self.v, name='Hans Muster')
        self.c.post(f'/neu/bankabgleich/zahlung/{g.id}/verwendung/', {'verwendung': 'offen'})
        g.refresh_from_db()
        self.assertEqual(g.guthaben_verwendung, 'offen')
        self.c.post(f'/neu/bankabgleich/zahlung/{g.id}/verwendung/', {'verwendung': 'erfunden'})
        g.refresh_from_db()
        self.assertEqual(g.guthaben_verwendung, 'offen')


class ImportSammelzahlungTests(_Basis):
    def _camt(self, ref, betrag, acct_ref):
        return (
            '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt><Ntry>'
            '<CdtDbtInd>CRDT</CdtDbtInd>'
            f'<Amt Ccy="CHF">{betrag}</Amt>'
            f'<BookgDt><Dt>{self.heute:%Y-%m-%d}</Dt></BookgDt>'
            '<NtryDtls><TxDtls>'
            f'<Refs><AcctSvcrRef>{acct_ref}</AcctSvcrRef></Refs>'
            f'<RmtInf><Strd><CdtrRefInf><Ref>{ref}</Ref></CdtrRefInf></Strd></RmtInf>'
            '</TxDtls></NtryDtls>'
            '</Ntry></Stmt></BkToCstmrStmt></Document>').encode()

    def _import(self, xml):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.c.post('/neu/bankabgleich/camt-import/',
                    {'camt_datei': SimpleUploadedFile('a.xml', xml, content_type='text/xml')})

    def test_ueberschuss_fuer_einen_weiteren_posten_wird_klaerungsfall(self):
        from finance.models import Zahlungseingang
        from rentals.models import Mietvertrag
        r = self.rechnung(self.v, '100')
        e2 = self.zweiter_vertrag().einheit
        v2 = Mietvertrag.objects.create(mieter=self.m, einheit=e2, beginn=date(2024, 1, 1),
                                        netto_mietzins=Decimal('100'), nebenkosten=Decimal('0'), status='aktiv')
        self.rechnung(v2, '100')
        r.refresh_from_db()
        self._import(self._camt(r.qr_referenz, '200.00', 'SAMMEL1'))
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        rest = Zahlungseingang.objects.get(bank_referenz='SAMMEL1:ueber')
        self.assertEqual(rest.konto.nummer, '1190', 'Der Überschuss ist ein Klärungsfall, kein stilles Guthaben')
        self.assertIn('Sammelzahlung', rest.klaerung_notiz)

    def test_ohne_weiteren_posten_bleibt_es_ein_guthaben(self):
        from finance.models import Zahlungseingang
        r = self.rechnung(self.v, '100')
        r.refresh_from_db()
        self._import(self._camt(r.qr_referenz, '150.00', 'UEBER1'))
        self.assertEqual(Zahlungseingang.objects.get(bank_referenz='UEBER1:ueber').konto.nummer, '2030')


class CockpitTests(_Basis):
    def test_spuren_zeigen_klaerung_teilzahlung_und_kleindifferenz(self):
        from finance.models import Zahlungseingang
        r = self.rechnung(self.v, '1410', tage=40)
        Zahlungseingang.objects.create(vertrag=self.v, debitoren_rechnung=r, betrag=Decimal('1407'),
                                       datum_eingang=self.heute, status='verbucht')
        r.status = 'teilbezahlt'; r.save()
        self.geparkt('85.00', name='Unbekannt AG', text='Rechnung 4711', tage=15)
        html = self.c.get('/neu/bankabgleich/').content.decode()
        self.assertIn('Unbekannt AG', html)
        self.assertIn('seit 15 Tagen', html)
        self.assertIn('Zuordnen / Aufteilen', html)
        self.assertIn('Teilbezahlt', html)
        self.assertIn('Kleindifferenz ausbuchen', html)       # Rest CHF 3.00 ≤ 5.00
        # Ausbuchen führt zurück ins Cockpit.
        antwort = self.c.post(f'/neu/debitoren/{r.id}/abschreiben/',
                              {'grund': 'Kleindifferenz', 'next': '/neu/bankabgleich/?spur=teil'})
        self.assertEqual(antwort['Location'], '/neu/bankabgleich/?spur=teil')
        r.refresh_from_db()
        self.assertEqual(r.status, 'abgeschrieben')

    def test_groesserer_rest_wird_gemahnt_nicht_ausgebucht(self):
        from finance.models import Zahlungseingang
        r = self.rechnung(self.v, '1410', tage=40)
        Zahlungseingang.objects.create(vertrag=self.v, debitoren_rechnung=r, betrag=Decimal('1300'),
                                       datum_eingang=self.heute, status='verbucht')
        r.status = 'teilbezahlt'; r.save()
        html = self.c.get('/neu/bankabgleich/?spur=teil').content.decode()
        self.assertIn('Rest mahnen', html)
        self.assertNotIn('Kleindifferenz ausbuchen', html)

    def test_alte_klaerungsfaelle_werden_zur_pendenz(self):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        jung = self.geparkt('20.00', tage=2, ref='J')
        alt = self.geparkt('30.00', tage=12, ref='A')
        generate_auto_pendenzen()
        self.assertTrue(Pendenz.objects.filter(quelle=f'auto:klaerung:{alt.id}', erledigt=False).exists())
        self.assertFalse(Pendenz.objects.filter(quelle=f'auto:klaerung:{jung.id}').exists())
        self.c.post('/neu/bankabgleich/guthaben/rueckerstatten/', {'zahlung_id': alt.id})
        generate_auto_pendenzen()
        self.assertTrue(Pendenz.objects.get(quelle=f'auto:klaerung:{alt.id}').erledigt)

    def test_portal_zeigt_teilzahlung(self):
        from django.contrib.auth import get_user_model
        from finance.models import Zahlungseingang
        r = self.rechnung(self.v, '1410')
        Zahlungseingang.objects.create(vertrag=self.v, debitoren_rechnung=r, betrag=Decimal('1300'),
                                       datum_eingang=self.heute, status='verbucht')
        r.status = 'teilbezahlt'; r.save()
        u = get_user_model().objects.create_user(username='mieter-p', password='x')
        self.m.benutzer = u; self.m.save()
        c = Client(); c.force_login(u)
        html = c.get('/mieter/rechnungen/').content.decode()
        self.assertIn('Teilweise bezahlt', html)
        self.assertIn('110.00', html)


class MandantenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.tenancy import organisation_kontext
        from finance.models import Zahlungseingang, Buchungskonto
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        with organisation_kontext(cls.b.organisation):
            k, _ = Buchungskonto.objects.get_or_create(nummer='1190', defaults={'bezeichnung': 'Durchlauf',
                                                                                'typ': 'bilanz'})
            cls.z_b = Zahlungseingang.objects.create(betrag=Decimal('200'), datum_eingang=date(2026, 10, 1),
                                                     konto=k, status='verbucht', bemerkung='camt UNGEKLÄRT: B')

    def test_fremde_zahlung_ist_nicht_erreichbar(self):
        c = Client(); c.force_login(self.a.benutzer)
        for pfad in ('aufteilen', 'kaution', 'notiz', 'verwendung', 'zuordnung-aufheben', 'wiederherstellen',
                     'verrechnung-rueckgaengig'):
            with self.subTest(pfad=pfad):
                url = f'/neu/bankabgleich/zahlung/{self.z_b.id}/{pfad}/'
                antwort = c.get(url) if pfad == 'aufteilen' else c.post(url, {'notiz': 'x', 'vertrag_id': self.a.vertrag.id})
                self.assertEqual(antwort.status_code, 404)
        self.z_b.refresh_from_db()
        self.assertEqual(self.z_b.klaerung_notiz, '')

    def test_suche_zeigt_keine_fremden_posten(self):
        from core.tenancy import organisation_kontext
        from finance.models import Buchungskonto, DebitorenRechnung, Zahlungseingang
        with organisation_kontext(self.a.organisation):
            k, _ = Buchungskonto.objects.get_or_create(nummer='1190', defaults={'bezeichnung': 'Durchlauf',
                                                                                'typ': 'bilanz'})
            z_a = Zahlungseingang.objects.create(betrag=Decimal('5'), datum_eingang=date(2026, 10, 1),
                                                 konto=k, status='verbucht')
            r_a = DebitorenRechnung.objects.create(vertrag=self.a.vertrag, titel='Offen A', betrag=Decimal('77'))
        with organisation_kontext(self.b.organisation):
            r_b = DebitorenRechnung.objects.create(vertrag=self.b.vertrag, titel='Offen B', betrag=Decimal('77'))
        c = Client(); c.force_login(self.a.benutzer)
        # Betrag und Titel treffen in beiden Verwaltungen — angezeigt wird nur A.
        for q in ('77', 'Offen'):
            with self.subTest(q=q):
                html = c.get(f'/neu/bankabgleich/zahlung/{z_a.id}/aufteilen/', {'q': q, 'fragment': '1'}).content.decode()
                self.assertIn(f'name="teil_{r_a.id}"', html)
                self.assertNotIn(f'name="teil_{r_b.id}"', html)


class KorrekturVerrechnungTests(_Basis):
    """Korrektur 26.10.2026: Ein Guthaben «mit nächster Rechnung» tilgte bei der
    Sollstellung die ÄLTESTEN Posten — einen Rückstand samt Mahngebühr in der
    letzten Mahnstufe. Er verschwand still aus dem Mahnwesen; das Storno, mit
    dem man ihn zurückholen wollte, hob auch den Geldeingang auf."""

    def rueckstand(self):
        alt = self.heute - timedelta(days=90)
        miete = self.rechnung(self.v, '100', titel='Miete Juli', tage=90)
        from finance.models import DebitorenRechnung
        geb = DebitorenRechnung.objects.create(vertrag=self.v, titel='Mahngebühr 3. Mahnung', datum=alt,
                                               faellig_am=self.heute - timedelta(days=20), betrag=Decimal('40'),
                                               stammrechnung=miete)
        return miete, geb

    def nk_guthaben(self, betrag='300.00'):
        """Ein Guthaben ohne Bankreferenz, wie die NK-Gutschrift es anlegt (3020 an 2030)."""
        from finance.booking import buche, konto
        from finance.models import Zahlungseingang
        z = Zahlungseingang.objects.create(vertrag=self.v, betrag=Decimal(betrag), datum_eingang=self.heute,
                                           bemerkung='NK-Gutschrift 2025 (Guthaben Mieter)', konto=konto('2030'),
                                           status='verbucht')
        buche('3020', '2030', Decimal(betrag), 'NK-Gutschrift Muster', datum=self.heute, zahlung=z)
        return z

    def test_sollstellung_tilgt_weder_rueckstand_noch_mahngebuehr(self):
        from core.models import AktivitaetsLog
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        miete, geb = self.rueckstand()
        self.nk_guthaben()
        run_sollstellung(self.heute.year, self.heute.month)
        miete.refresh_from_db(); geb.refresh_from_db()
        self.assertEqual((miete.status, geb.status), ('offen', 'offen'),
                         'Rückstand und Mahngebühr bleiben offen und im Mahnwesen')
        neu = DebitorenRechnung.objects.get(titel=f'Miete & NK {self.heute.month:02d}/{self.heute.year}')
        self.assertLess(neu.offener_betrag, neu.betrag, 'Das Guthaben tilgt die neue Monatsrechnung')
        self.assertTrue(AktivitaetsLog.objects.filter(aktion='Guthaben automatisch verrechnet').exists())
        self.assertIn('Mahngebühr', self.c.get('/neu/mahnwesen/').content.decode())

    def test_verrechnung_rueckgaengig_laesst_den_eingang_stehen(self):
        from core.services.zahlungsklaerung import guthaben_verrechnen
        from finance.models import Zahlungseingang
        miete, _geb = self.rueckstand()
        g = self.nk_guthaben('100.00')
        guthaben_verrechnen([self.v.id], rechnung_ids=[miete.id])
        miete.refresh_from_db()
        self.assertEqual(miete.status, 'bezahlt')
        html = self.c.get('/neu/bankabgleich/?spur=guthaben').content.decode()
        self.assertIn('Verrechnung rückgängig', html)
        self.c.post(f'/neu/bankabgleich/zahlung/{g.id}/verrechnung-rueckgaengig/', {})
        miete.refresh_from_db(); g.refresh_from_db()
        self.assertEqual(miete.status, 'offen')
        self.assertEqual((g.status, g.konto.nummer, g.guthaben_verwendung), ('verbucht', '2030', 'offen'))
        self.assertEqual(_kontoblatt('2030'), Decimal('-100.00'))
        self.assertEqual(_kontoblatt('3020'), Decimal('100.00'), 'Die NK-Gutschrift bleibt gebucht')
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=miete, status='verbucht').count(), 0)

    def _alte_verrechnung_dann_storno(self, guthaben):
        """Bildet den Fehler mit Altdaten nach: Verrechnung auf den ältesten Posten,
        Rest ohne Referenz (so legte `zuordnen` ihn bis zur Korrektur an), Storno."""
        from core.services.zahlungszuordnung import zuordnen
        from finance.models import Zahlungseingang
        miete, geb = self.rueckstand()
        ref = guthaben.bank_referenz
        zuordnen(guthaben, miete)
        rest = Zahlungseingang.objects.get(bank_referenz__endswith=':rest', status='verbucht')
        if not ref:
            Zahlungseingang.objects.filter(pk__in=[guthaben.pk, rest.pk]).update(bank_referenz='')
            rest.refresh_from_db()
        zuordnen(rest, geb)
        miete.refresh_from_db(); geb.refresh_from_db()
        self.assertEqual((miete.status, geb.status), ('bezahlt', 'bezahlt'))
        self.c.post(f'/neu/zahlungen/{guthaben.id}/stornieren/', {})
        return miete, geb

    def test_storniertes_nk_guthaben_wird_wiederhergestellt(self):
        g = self.nk_guthaben('300.00')
        miete, geb = self._alte_verrechnung_dann_storno(g)
        geb.refresh_from_db()
        self.assertEqual(geb.status, 'bezahlt', 'Altdaten: der Rest ohne Referenz hält die Mahngebühr bezahlt')
        html = self.c.get('/neu/bankabgleich/?spur=guthaben').content.decode()
        self.assertIn('Stornierte Guthaben-Verrechnungen', html)
        self.c.post(f'/neu/bankabgleich/zahlung/{g.id}/wiederherstellen/', {})
        miete.refresh_from_db(); geb.refresh_from_db()
        self.assertEqual((miete.status, geb.status), ('offen', 'offen'))
        self.assertEqual(_kontoblatt('2030'), Decimal('-300.00'), 'Das ganze Guthaben steht wieder auf 2030')
        self.assertEqual(_kontoblatt('3020'), Decimal('300.00'), 'Die NK-Gutschrift ist wieder gebucht')
        self.assertEqual(_kontoblatt('1100'), Decimal('0.00'))
        # Ein zweites Mal geht nicht, und die Liste ist leer.
        self.c.post(f'/neu/bankabgleich/zahlung/{g.id}/wiederherstellen/', {})
        self.assertEqual(_kontoblatt('2030'), Decimal('-300.00'))
        self.assertNotIn('Stornierte Guthaben-Verrechnungen',
                         self.c.get('/neu/bankabgleich/?spur=guthaben').content.decode())

    def test_storniertes_bankguthaben_wird_wiederhergestellt(self):
        g = self.geparkt('300.00', konto='2030', vertrag=self.v, name='Hans Muster', ref='TX-UEBER')
        miete, geb = self._alte_verrechnung_dann_storno(g)
        self.assertEqual(_kontoblatt('1020'), Decimal('0.00'), 'Das Storno hob auch den Bankeingang auf')
        self.c.post(f'/neu/bankabgleich/zahlung/{g.id}/wiederherstellen/', {})
        miete.refresh_from_db(); geb.refresh_from_db()
        self.assertEqual((miete.status, geb.status), ('offen', 'offen'))
        self.assertEqual(_kontoblatt('1020'), Decimal('300.00'))
        self.assertEqual(_kontoblatt('2030'), Decimal('-300.00'))

    def test_rest_bekommt_jetzt_immer_eine_referenz(self):
        from core.services.zahlungszuordnung import zuordnen
        from finance.models import Zahlungseingang
        miete, geb = self.rueckstand()
        g = self.nk_guthaben('300.00')
        zuordnen(g, miete)
        rest = Zahlungseingang.objects.get(bemerkung__startswith='Rest-Guthaben', status='verbucht')
        g.refresh_from_db()
        self.assertTrue(rest.bank_referenz.startswith(f'{g.bank_referenz}:'))
        zuordnen(rest, geb)
        self.c.post(f'/neu/zahlungen/{g.id}/stornieren/', {})
        geb.refresh_from_db()
        self.assertEqual(geb.status, 'offen', 'Das Storno erreicht den Rest')


class FehlzuordnungTests(_Basis):
    """Korrektur 26.10.2026, der Fall aus dem Betrieb: Die Zahlung eines Fremden
    («Narrezauber Soledurn», CHF 100) kam ohne Referenz. Der Assistent befüllte
    sie vor, weil der Betrag auf die Oktobermiete eines Parkplatzmieters passte —
    der war mit Miete und Mahngebühr im Rückstand, die 257d-Frist lief. Ein Klick
    auf «Buchen», und die Miete galt als bezahlt, die Frist als «durch Zahlung
    erledigt», der Fall war abgeschlossen und der Absender für diesen Mieter
    gelernt. Der Mieter war nicht mehr zu finden."""

    def setUp(self):
        super().setUp()
        from django.core.management import call_command
        from finance.models import DebitorenRechnung
        call_command('fallarten_anlegen', verbosity=0)
        self.miete = self.rechnung(self.v, '100', titel='Miete & NK 10/2026', tage=35)
        self.geb = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Mahngebühr 1. Mahnung', datum=self.heute - timedelta(days=20),
            faellig_am=self.heute - timedelta(days=10), betrag=Decimal('40'), stammrechnung=self.miete)
        antwort = self.c.post(f'/neu/vertraege/{self.v.id}/verzug/',
                              {'frist_bis': (self.heute + timedelta(days=37)).isoformat()})
        self.assertEqual(antwort.status_code, 302)

    def frist(self):
        from core.models import Pendenz
        return Pendenz.objects.get(vertrag=self.v, quelle=f'257d:{self.v.pk}')

    def fall(self):
        from django.contrib.contenttypes.models import ContentType
        from faelle.models import Fall
        return Fall.objects.get(akte_typ=ContentType.objects.get_for_model(self.v), akte_id=self.v.pk,
                                fallart__schluessel='zahlungsverzug')

    def falsch_zuordnen(self, betrag='100.00', **extra):
        z = self.geparkt(betrag, name='Narrezauber Soledurn', text='Zahlung', ref='TX-NARR')
        antwort = self.c.post(f'/neu/bankabgleich/zahlung/{z.id}/aufteilen/',
                              {f'teil_{self.miete.id}': '100', 'rest_ziel': 'offen', **extra})
        self.assertEqual(antwort.status_code, 302)
        self.miete.refresh_from_db()
        self.assertEqual(self.miete.status, 'bezahlt')
        self.assertTrue(self.frist().erledigt, 'Ausgangslage: die Frist galt als gewahrt')
        return z

    def test_betrag_allein_befuellt_nichts_vor(self):
        z = self.geparkt('100.00', name='Narrezauber Soledurn', text='Zahlung', ref='TX-NARR')
        antwort = self.c.get(f'/neu/bankabgleich/zahlung/{z.id}/aufteilen/')
        self.assertEqual(antwort.context['vorschlag'], {}, 'Ein passender Betrag belegt nicht, wer gezahlt hat')
        self.assertIn('nur Betrag', antwort.content.decode())
        self.assertIn('Nur der Betrag passt', self.c.get('/neu/bankabgleich/?spur=klaerung').content.decode())
        # Nennt der Absender den Mieter, bleibt der Vorschlag vorbefüllt.
        z2 = self.geparkt('100.00', name='Hans Muster', text='Miete Oktober', ref='TX-MUSTER')
        antwort = self.c.get(f'/neu/bankabgleich/zahlung/{z2.id}/aufteilen/')
        self.assertEqual(antwort.context['vorschlag'], {self.miete.id: Decimal('100.00')})

    def test_zuordnung_aufheben_holt_rueckstand_frist_und_fall_zurueck(self):
        from core.services.zahlungsverzug import VERMERK_GEWAHRT, aktive_fristen
        from faelle.models import Fall
        from finance.models import ZahlerZuordnung
        z = self.falsch_zuordnen()
        self.assertEqual(self.fall().status, Fall.ABGESCHLOSSEN)
        self.assertTrue(ZahlerZuordnung.objects.filter(vertrag=self.v).exists())
        html = self.c.get('/neu/bankabgleich/?spur=klaerung').content.decode()
        self.assertIn('Zugeordnete Klärungsfälle', html)
        self.assertIn(f'/neu/bankabgleich/zahlung/{z.id}/zuordnung-aufheben/', html)

        self.c.post(f'/neu/bankabgleich/zahlung/{z.id}/zuordnung-aufheben/', {})
        self.miete.refresh_from_db(); self.geb.refresh_from_db(); z.refresh_from_db()
        self.assertEqual((self.miete.status, self.geb.status), ('offen', 'offen'))
        self.assertEqual((z.status, z.konto.nummer, z.vertrag_id, z.betrag), ('verbucht', '1190', None, Decimal('100.00')))
        self.assertEqual(_kontoblatt('1020'), Decimal('100.00'), 'Der Geldeingang bleibt — das Geld IST auf der Bank')
        from finance.models import Buchung
        self.assertEqual(list(Buchung.objects.filter(soll_konto__nummer='1020').values_list('storniert_am', flat=True)),
                         [None], 'Die Bankbuchung wird weder storniert noch neu gebucht (Periodensperre, Revision)')
        self.assertEqual(_kontoblatt('1190'), Decimal('-100.00'))
        self.assertEqual(_kontoblatt('1100'), Decimal('0.00'))
        p = self.frist()
        self.assertFalse(p.erledigt, 'Die 257d-Frist läuft wieder')
        self.assertNotIn(VERMERK_GEWAHRT, p.beschreibung, 'Der Sperrvermerk würde eine Kündigung weiter sperren')
        self.assertTrue(aktive_fristen(self.v).exists())
        self.assertEqual(self.fall().status, Fall.OFFEN)
        self.assertFalse(ZahlerZuordnung.objects.filter(vertrag=self.v).exists(), 'Der Absender ist vergessen')
        html = self.c.get('/neu/bankabgleich/?spur=klaerung').content.decode()
        self.assertIn('Narrezauber Soledurn', html, 'Die Zahlung ist wieder ein Klärungsfall')

    def test_aufgeteilte_zahlung_mit_guthaben_rest_wird_ganz_zurueckgelegt(self):
        from finance.models import Zahlungseingang
        z = self.falsch_zuordnen('150.00', rest_ziel='guthaben', rest_vertrag=self.v.id)
        self.assertEqual(_kontoblatt('2030'), Decimal('-50.00'))
        self.c.post(f'/neu/bankabgleich/zahlung/{z.id}/zuordnung-aufheben/', {})
        z.refresh_from_db()
        self.assertEqual((z.konto.nummer, z.betrag), ('1190', Decimal('150.00')))
        self.assertEqual(_kontoblatt('2030'), Decimal('0.00'), 'Das Guthaben aus der Fehlzuordnung ist weg')
        self.assertEqual(_kontoblatt('1190'), Decimal('-150.00'))
        self.assertFalse(Zahlungseingang.objects.filter(bank_referenz__startswith='TX-NARR:', status='verbucht').exists())

    def test_storno_statt_aufheben_laesst_sich_wiederherstellen(self):
        from finance.models import Bankbewegung, Zahlungseingang
        z = self.falsch_zuordnen()
        self.c.post(f'/neu/zahlungen/{z.id}/stornieren/', {})
        self.assertEqual(_kontoblatt('1020'), Decimal('0.00'), 'Das Storno hob auch den Bankeingang auf')
        self.assertFalse(self.frist().erledigt, 'Schon das Storno öffnet die Frist wieder')
        html = self.c.get('/neu/bankabgleich/?spur=klaerung').content.decode()
        self.assertIn('Stornierte Zuordnungen', html)
        self.c.post(f'/neu/bankabgleich/zahlung/{z.id}/wiederherstellen/', {})
        neu = Zahlungseingang.objects.get(status='verbucht', konto__nummer='1190')
        self.assertEqual((neu.betrag, neu.vertrag_id), (Decimal('100.00'), None))
        self.assertEqual(_kontoblatt('1020'), Decimal('100.00'))
        self.assertEqual(Bankbewegung.objects.get(bank_referenz='TX-NARR').zahlung_id, neu.id)
        self.miete.refresh_from_db()
        self.assertEqual(self.miete.status, 'offen')
        self.assertNotIn('Stornierte Zuordnungen', self.c.get('/neu/bankabgleich/?spur=klaerung').content.decode())

    def test_zurueckueberwiesener_teil_sperrt_das_aufheben(self):
        z = self.falsch_zuordnen('150.00', rest_ziel='zurueck', bank_konto='1020')
        self.c.post(f'/neu/bankabgleich/zahlung/{z.id}/zuordnung-aufheben/', {})
        self.miete.refresh_from_db()
        self.assertEqual(self.miete.status, 'bezahlt', 'Geld, das schon zurück ist, kann nicht wieder ungeklärt sein')
