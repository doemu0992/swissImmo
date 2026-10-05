"""Phase 2: Oberflächen für Ticket-Zuweisung, NK-Zustellung, Betreibung, Zählerstand.

Jeder Fehlerfall prüft zwei Dinge: Der Fehlertext steht am Feld (HTTP 400, Seite
bleibt, Eingabe bleibt) UND es wurde nichts gespeichert.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.tests._helfer import _basis_objekte, _seed_konten, _team_user, _test_organisation


class _Basis(TestCase):
    def setUp(self):
        _seed_konten()
        self.org = _test_organisation()
        self.lg, self.einheit, self.mieter, self.vertrag = _basis_objekte()
        self.verwalter = _team_user('Verwalter')
        self.c = Client()
        self.c.force_login(self.verwalter)
        self.heute = timezone.localdate()


class TicketZuweisenTests(_Basis):
    def setUp(self):
        super().setUp()
        from tickets.models import SchadenMeldung
        self.t = SchadenMeldung.objects.create(liegenschaft=self.lg, titel='Heizung', beschreibung='kalt',
                                               prioritaet='hoch')
        self.url = f'/neu/schaeden/{self.t.id}/zuweisen/'

    def test_zuweisen_speichert_und_protokolliert(self):
        antwort = self.c.post(self.url, {'zugewiesen_an': self.verwalter.id,
                                         'faellig_bis': (self.heute + timedelta(days=3)).isoformat()})
        self.assertRedirects(antwort, f'/neu/schaeden/{self.t.id}/', fetch_redirect_response=False)
        self.t.refresh_from_db()
        self.assertEqual(self.t.zugewiesen_an, self.verwalter)
        self.assertEqual(self.t.faellig_bis, self.heute + timedelta(days=3))
        self.assertTrue(self.t.nachrichten.filter(typ='system', nachricht__icontains='Zuständig').exists())

    def test_vergangene_frist_wird_am_feld_abgelehnt(self):
        alt = self.t.faellig_bis
        antwort = self.c.post(self.url, {'zugewiesen_an': self.verwalter.id,
                                         'faellig_bis': (self.heute - timedelta(days=30)).isoformat()})
        self.assertEqual(antwort.status_code, 400)
        self.assertContains(antwort, 'faellig_bis_fehler', status_code=400)
        self.assertContains(antwort, 'Vergangenheit', status_code=400)
        self.t.refresh_from_db()
        self.assertIsNone(self.t.zugewiesen_an)
        self.assertEqual(self.t.faellig_bis, alt)

    def test_fremder_benutzer_ist_nicht_waehlbar(self):
        from django.contrib.auth import get_user_model
        fremd = get_user_model().objects.create_user('fremd', password='x')   # ohne Mitgliedschaft
        antwort = self.c.post(self.url, {'zugewiesen_an': fremd.id, 'faellig_bis': ''})
        self.assertEqual(antwort.status_code, 400)
        self.t.refresh_from_db()
        self.assertIsNone(self.t.zugewiesen_an)

    def test_lesezugriff_darf_nicht_zuweisen(self):
        c = Client()
        c.force_login(_team_user('Lesezugriff'))
        c.post(self.url, {'zugewiesen_an': self.verwalter.id})
        self.t.refresh_from_db()
        self.assertIsNone(self.t.zugewiesen_an)

    def test_hauswart_darf_nicht_zuweisen(self):
        c = Client()
        c.force_login(_team_user('Hauswart'))
        self.assertEqual(c.get(self.url).status_code, 403)
        self.assertEqual(c.post(self.url, {'zugewiesen_an': self.verwalter.id}).status_code, 403)
        self.t.refresh_from_db()
        self.assertIsNone(self.t.zugewiesen_an)

    def test_filter_meine_tickets(self):
        from tickets.models import SchadenMeldung
        SchadenMeldung.objects.create(liegenschaft=self.lg, titel='Fremdes Ticket', beschreibung='x')
        self.t.zugewiesen_an = self.verwalter
        self.t.save()
        antwort = self.c.get('/neu/schaeden/?zustaendig=ich&sicht=')
        self.assertContains(antwort, 'Heizung')
        self.assertNotContains(antwort, 'Fremdes Ticket')


class NkZustellungTests(_Basis):
    def setUp(self):
        super().setUp()
        from finance.models import AbrechnungsPeriode
        self.p = AbrechnungsPeriode.objects.create(
            liegenschaft=self.lg, bezeichnung='NK 2025', start_datum=date(2025, 1, 1),
            ende_datum=date(2025, 12, 31))
        self.url = f'/neu/nebenkosten/{self.p.id}/zustellung/'

    def test_unverbuchte_abrechnung_wird_abgelehnt(self):
        antwort = self.c.post(self.url, {'versendet_am': date(2026, 3, 1).isoformat(), 'versand_kanal': 'brief'})
        self.assertEqual(antwort.status_code, 400)
        self.assertContains(antwort, 'noch nicht verbucht', status_code=400)
        self.p.refresh_from_db()
        self.assertIsNone(self.p.versendet_am)

    def test_zustellung_setzt_einsprachefrist(self):
        self.p.abgeschlossen = True
        self.p.save()
        self.c.post(self.url, {'versendet_am': date(2026, 3, 1).isoformat(), 'versand_kanal': 'brief'})
        self.p.refresh_from_db()
        self.assertEqual(self.p.einsprache_bis, date(2026, 3, 31))

    def test_datum_vor_periodenende_und_zukunft_am_feld(self):
        self.p.abgeschlossen = True
        self.p.save()
        a = self.c.post(self.url, {'versendet_am': date(2025, 6, 1).isoformat(), 'versand_kanal': 'brief'})
        self.assertContains(a, 'versendet_am_fehler', status_code=400)
        b = self.c.post(self.url, {'versendet_am': (self.heute + timedelta(days=5)).isoformat(), 'versand_kanal': 'brief'})
        self.assertContains(b, 'Zukunft', status_code=400)


class BetreibungTests(_Basis):
    def setUp(self):
        super().setUp()
        from finance.models import DebitorenRechnung
        self.r = DebitorenRechnung.objects.create(
            vertrag=self.vertrag, titel='Miete 08/2026', betrag=Decimal('1700'),
            datum=self.heute - timedelta(days=90), faellig_am=self.heute - timedelta(days=80), status='offen')
        self.url = f'/neu/betreibungen/neu/{self.r.id}/'

    def _daten(self, **kw):
        d = {'status': 'begehren', 'betreibungsamt': 'Betreibungsamt Zürich 1', 'betreibungsnummer': '',
             'forderung': '1700.00', 'kosten': '0', 'begehren_am': self.heute.isoformat(), 'bemerkung': ''}
        d.update(kw)
        return d

    def test_einleiten_legt_betreibung_an_und_listet_sie(self):
        from finance.models import Betreibung
        a = self.c.post(self.url, self._daten())
        self.assertRedirects(a, '/neu/betreibungen/', fetch_redirect_response=False)
        b = Betreibung.objects.get()
        self.assertEqual((b.debitoren_rechnung_id, b.vertrag_id), (self.r.id, self.vertrag.id))
        self.assertContains(self.c.get('/neu/betreibungen/'), 'Miete 08/2026')

    def test_forderung_null_wird_am_feld_abgelehnt(self):
        from finance.models import Betreibung
        a = self.c.post(self.url, self._daten(forderung='0'))
        self.assertContains(a, 'forderung_fehler', status_code=400)
        self.assertEqual(Betreibung.objects.count(), 0)

    def test_stand_ohne_passendes_datum_wird_abgelehnt(self):
        from finance.models import Betreibung
        a = self.c.post(self.url, self._daten(status='zahlungsbefehl'))
        self.assertContains(a, 'zahlungsbefehl_am_fehler', status_code=400)
        self.assertEqual(Betreibung.objects.count(), 0)

    def test_datumsfolge_wird_geprueft(self):
        a = self.c.post(self.url, self._daten(
            status='zahlungsbefehl', zahlungsbefehl_am=(self.heute - timedelta(days=5)).isoformat(),
            begehren_am=self.heute.isoformat()))
        self.assertContains(a, 'zahlungsbefehl_am_fehler', status_code=400)

    def test_rechtsvorschlag_nach_zehn_tagen_wird_beanstandet(self):
        a = self.c.post(self.url, self._daten(
            status='rechtsvorschlag', begehren_am=(self.heute - timedelta(days=40)).isoformat(),
            zahlungsbefehl_am=(self.heute - timedelta(days=30)).isoformat(),
            rechtsvorschlag_am=(self.heute - timedelta(days=5)).isoformat()))
        self.assertContains(a, '10-Tage-Frist', status_code=400)

    def test_bezahlte_rechnung_kann_nicht_betrieben_werden(self):
        from finance.models import Betreibung
        self.r.status = 'bezahlt'
        self.r.save()
        self.c.post(self.url, self._daten())
        self.assertEqual(Betreibung.objects.count(), 0)


class ZaehlerstandTests(_Basis):
    def setUp(self):
        super().setUp()
        from portfolio.models import Zaehler
        self.z = Zaehler.objects.create(einheit=self.einheit, typ='Heizung', zaehler_nummer='H-1')
        self.url = f'/neu/liegenschaften/{self.lg.id}/zaehlerstand/'

    def _post(self, wert, tage_zurueck=0, **kw):
        return self.c.post(self.url, {'zaehler': self.z.id, 'wert': wert,
                                      'datum': (self.heute - timedelta(days=tage_zurueck)).isoformat(), **kw})

    def test_erfassen_aktualisiert_aktuellen_stand(self):
        from portfolio.models import ZaehlerStand
        self._post('100.5', tage_zurueck=30)
        self._post('140.25')
        self.z.refresh_from_db()
        self.assertEqual(ZaehlerStand.objects.filter(zaehler=self.z).count(), 2)
        self.assertEqual(self.z.aktueller_stand, Decimal('140.25'))

    def test_sinkender_stand_wird_am_feld_abgelehnt(self):
        from portfolio.models import ZaehlerStand
        self._post('100', tage_zurueck=30)
        a = self._post('90')
        self.assertContains(a, 'wert_fehler', status_code=400)
        self.assertEqual(ZaehlerStand.objects.count(), 1)

    def test_nachtraeglicher_stand_ueber_spaeterem_wird_abgelehnt(self):
        self._post('200')
        a = self._post('250', tage_zurueck=60)
        self.assertContains(a, 'wert_fehler', status_code=400)

    def test_gespeicherte_staende_speisen_die_hkvo_verbrauchsrechnung(self):
        from core.utils.billing import _heiz_verbrauch_pro_einheit
        self._post('100', tage_zurueck=30)
        self._post('160')
        verbrauch = _heiz_verbrauch_pro_einheit(self.lg, self.heute - timedelta(days=60), self.heute)
        self.assertEqual(verbrauch, {self.einheit.id: Decimal('60')})


class EinstiegsseitenTests(_Basis):
    """Die bearbeiteten Seiten rendern (Button-Check): ein fehlendes `{% load %}`
    in einer Vorlage ergibt sonst eine 500 genau dort, wo der neue Knopf sitzt."""

    def test_seiten_mit_neuen_knoepfen_rendern(self):
        from finance.models import AbrechnungsPeriode, DebitorenRechnung
        from tickets.models import SchadenMeldung
        t = SchadenMeldung.objects.create(liegenschaft=self.lg, titel='Leck', beschreibung='x')
        p = AbrechnungsPeriode.objects.create(liegenschaft=self.lg, bezeichnung='NK 2025',
                                              start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31),
                                              abgeschlossen=True)
        DebitorenRechnung.objects.create(
            vertrag=self.vertrag, titel='Miete', betrag=Decimal('1700'),
            datum=self.heute - timedelta(days=90), faellig_am=self.heute - timedelta(days=80), status='offen')
        erwartet = {
            f'/neu/liegenschaften/{self.lg.id}/': f'/neu/liegenschaften/{self.lg.id}/zaehlerstand/',
            f'/neu/schaeden/{t.id}/': f'/neu/schaeden/{t.id}/zuweisen/',
            f'/neu/nebenkosten/{p.id}/': f'/neu/nebenkosten/{p.id}/zustellung/',
            '/neu/mahnwesen/': '/neu/betreibungen/',
            '/neu/schaeden/': 'zustaendig=ich',
            '/neu/betreibungen/': 'Betreibungen',
        }
        for seite, muss_enthalten in erwartet.items():
            with self.subTest(seite=seite):
                antwort = self.c.get(seite)
                self.assertEqual(antwort.status_code, 200)
                self.assertContains(antwort, muss_enthalten)
