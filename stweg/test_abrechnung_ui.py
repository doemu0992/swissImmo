"""Abrechnung, Akonto und Erneuerungsfonds über die Oberfläche — und für den Eigentümer im Portal."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.tests._helfer import _team_user
from stweg.models import StwegAbrechnung, StwegAkonto
from stweg.test_versammlung import sonnenblick
from stweg.tests import rechnung

User = get_user_model()


class AbrechnungOberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.client.force_login(_team_user('Verwaltung'))
        self.url = f'/neu/stweg/{self.lg.pk}/abrechnung/'

    def test_sonnenblick_ueber_die_oberflaeche(self):
        for e in self.e:
            self.client.post(f'/neu/stweg/{self.lg.pk}/akonto/neu/',
                             {'einheit': e.pk, 'betrag': "1'000.00", 'datum': '2026-03-01'})
        self.assertEqual(StwegAkonto.objects.count(), 3)
        rechnung(self.lg, 1500, date(2026, 2, 1), lieferant='Gebäudeversicherung')
        rechnung(self.lg, 1000, date(2026, 5, 1), lieferant='Gartenpflege')
        rechnung(self.lg, 1500, date(2026, 8, 1), lieferant='Liftwartung')

        vorschau = self.client.get(self.url, {'jahr': 2026})
        self.assertContains(vorschau, 'Gartenpflege')
        self.assertContains(vorschau, "Total <strong>CHF 4'000.00")

        r = self.client.post(self.url + 'berechnen/', {'jahr': 2026}, follow=True)
        self.assertContains(r, 'Abrechnung 2026 berechnet')
        a = StwegAbrechnung.objects.get()
        salden = {p.einheit.bezeichnung: p.saldo for p in a.positionen.all()}
        self.assertEqual(salden, {'Whg 1': Decimal('-200.00'), 'Whg 2': Decimal('200.00'),
                                  'Whg 3': Decimal('1000.00')})
        seite = self.client.get(self.url, {'jahr': 2026})
        self.assertContains(seite, 'Guthaben CHF 200.00')
        self.assertContains(seite, "Nachzahlung CHF 1'000.00")

        # PDF: gesamt und je Eigentümer
        self.assertTrue(self.client.get(f'/neu/stweg/abrechnung/{a.pk}/pdf/').content.startswith(b'%PDF'))
        eig_pdf = self.client.get(f'/neu/stweg/abrechnung/{a.pk}/pdf/?eigentuemer={self.eigs[2].pk}')
        self.assertEqual(eig_pdf.status_code, 200)

        # Abschliessen sperrt: keine Neuberechnung, kein Akonto mehr entfernen
        self.client.post(f'/neu/stweg/abrechnung/{a.pk}/abschliessen/')
        a.refresh_from_db()
        self.assertEqual(a.status, 'abgeschlossen')
        r = self.client.post(self.url + 'berechnen/', {'jahr': 2026}, follow=True)
        self.assertContains(r, 'abgeschlossen')
        k = StwegAkonto.objects.first()
        r = self.client.post(f'/neu/stweg/akonto/{k.pk}/loeschen/', follow=True)
        self.assertContains(r, 'lässt sich nicht mehr ändern')
        self.assertEqual(StwegAkonto.objects.count(), 3)

    def test_falsche_quoten_verhindern_die_abrechnung_mit_meldung(self):
        from portfolio.models import Einheit
        Einheit.objects.filter(pk=self.e[0].pk).update(wertquote=Decimal(199))
        r = self.client.post(self.url + 'berechnen/', {'jahr': 2026}, follow=True)
        self.assertContains(r, '999/1000')
        self.assertEqual(StwegAbrechnung.objects.count(), 0)

    def test_akonto_eingaben_werden_geprueft(self):
        for daten in ({'einheit': self.e[0].pk, 'betrag': '0'}, {'einheit': self.e[0].pk, 'betrag': 'x'},
                      {'einheit': 999999, 'betrag': '10'}, {'betrag': '10'}):
            self.client.post(f'/neu/stweg/{self.lg.pk}/akonto/neu/', daten)
        self.assertEqual(StwegAkonto.objects.count(), 0)

    def test_fonds_einlage_und_entnahme_ueber_die_oberflaeche(self):
        self.client.post(f'/neu/stweg/{self.lg.pk}/fonds/einlage/', {'jahr': 2026, 'betrag': '10000'})
        seite = self.client.get(self.url, {'jahr': 2026})
        self.assertContains(seite, "Bestand CHF 10'000.00")
        self.assertContains(seite, 'Einlage 2026')
        r = self.client.post(f'/neu/stweg/{self.lg.pk}/fonds/einlage/', {'jahr': 2026, 'betrag': '10'}, follow=True)
        self.assertContains(r, 'bereits belastet')
        self.client.post(f'/neu/stweg/{self.lg.pk}/fonds/entnahme/',
                         {'jahr': 2026, 'betrag': '4000', 'text': 'Dachsanierung'})
        self.assertContains(self.client.get(self.url, {'jahr': 2026}), "Bestand CHF 6'000.00")
        r = self.client.post(f'/neu/stweg/{self.lg.pk}/fonds/entnahme/',
                             {'jahr': 2026, 'betrag': '99999', 'text': 'zu viel'}, follow=True)
        self.assertContains(r, 'übersteigt')

    def test_ansehen_legt_keinen_fonds_an(self):
        from finance.models import Erneuerungsfonds
        self.client.get(self.url)
        self.assertEqual(Erneuerungsfonds.objects.count(), 0)

    def test_lesezugriff_darf_nicht_schreiben(self):
        self.client.force_login(_team_user('Lesend'))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        basis = f'/neu/stweg/{self.lg.pk}/'
        for pfad in ('abrechnung/berechnen/', 'akonto/neu/', 'fonds/einlage/', 'fonds/entnahme/'):
            self.assertEqual(self.client.post(basis + pfad, {}).status_code, 403, pfad)


class AbrechnungPortalTests(TestCase):
    def setUp(self):
        from stweg.services import StwegAbrechnungService
        self.lg, self.e, self.eigs = sonnenblick()
        for e in self.e:
            StwegAkonto.objects.create(einheit=e, betrag=Decimal('1000'), datum=date(2026, 3, 1))
        rechnung(self.lg, 4000, date(2026, 6, 1))
        self.abrechnung = StwegAbrechnungService(self.lg).abrechnen(2026)
        self.clients = {}
        for eig in self.eigs:
            u = User.objects.create_user(username=f'p_{eig.firma_oder_name}', password='x')
            eig.benutzer = u
            eig.save()
            c = Client()
            c.force_login(u)
            self.clients[eig.firma_oder_name] = c

    def test_entwurf_ist_fuer_eigentuemer_unsichtbar(self):
        self.assertEqual(self.clients['Anna'].get(f'/portal/stweg/abrechnung/{self.abrechnung.pk}/').status_code, 404)
        self.assertNotContains(self.clients['Anna'].get('/portal/stweg/'), 'Jahresabrechnung 2026')

    def test_abgeschlossen_zeigt_nur_den_eigenen_saldo(self):
        from stweg.services import StwegAbrechnungService
        StwegAbrechnungService.abschliessen(self.abrechnung)
        seite = self.clients['Anna'].get('/portal/stweg/')
        self.assertContains(seite, 'Jahresabrechnung 2026')
        self.assertContains(seite, 'Guthaben CHF 200.00')
        self.assertNotContains(seite, "Nachzahlung CHF 1'000.00")            # Carlas Saldo
        r = self.clients['Anna'].get(f'/portal/stweg/abrechnung/{self.abrechnung.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertContains(self.clients['Carla'].get('/portal/stweg/'), "Nachzahlung CHF 1'000.00")

    def test_fremder_eigentuemer_bekommt_404(self):
        from crm.models import Eigentuemer
        from portfolio.models import Einheit
        from stweg.services import StwegAbrechnungService
        from stweg.tests import neue_stweg
        StwegAbrechnungService.abschliessen(self.abrechnung)
        nachbar_lg, nachbar_e = neue_stweg(name='Nachbar')
        dora = Eigentuemer.objects.create(firma_oder_name='Dora')
        Einheit.objects.filter(pk=nachbar_e[0].pk).update(stockwerkeigentuemer=dora)
        u = User.objects.create_user(username='dora', password='x')
        dora.benutzer = u
        dora.save()
        c = Client()
        c.force_login(u)
        self.assertEqual(c.get(f'/portal/stweg/abrechnung/{self.abrechnung.pk}/').status_code, 404)
