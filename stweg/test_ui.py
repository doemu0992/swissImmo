"""Die Oberfläche des STWEG-Moduls — der ganze Ablauf über HTTP, wie ihn die Verwaltung bedient."""
from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from core.tests._helfer import _team_user
from stweg.models import Anwesenheit, Stimme, Traktandum, Versammlung
from stweg.test_versammlung import sonnenblick


class OberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.user = _team_user('Verwaltung')
        self.client.force_login(self.user)

    def post(self, url, daten=None, folgen=False):
        return self.client.post(url, daten or {}, follow=folgen)

    def test_seiten_laden(self):
        for url in ('/neu/stweg/', f'/neu/stweg/{self.lg.pk}/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get('/neu/stweg/'), 'Sonnenblickweg 1')

    def test_ganzer_ablauf(self):
        c = self.client
        datum = (timezone.now() + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M')
        r = self.post(f'/neu/stweg/{self.lg.pk}/versammlung/neu/',
                      {'titel': 'Ordentliche Versammlung 2026', 'datum': datum, 'ort': 'Saal',
                       'art': 'ordentlich', 'einladungsfrist_tage': '10'})
        v = Versammlung.objects.get()
        self.assertRedirects(r, f'/neu/stweg/versammlung/{v.pk}/')

        # Einladung ohne Traktandum ist blockiert und sagt warum
        r = self.post(f'/neu/stweg/versammlung/{v.pk}/einladung/', folgen=True)
        self.assertContains(r, 'kein Traktandum')
        self.assertEqual(len(mail.outbox), 0)

        self.post(f'/neu/stweg/versammlung/{v.pk}/traktandum/neu/',
                  {'titel': 'Jahresrechnung', 'antrag': 'Genehmigen', 'mehrheitsart': 'einfach_koepfe',
                   'vollzug_aufgabe': 'Rechnung ablegen'})
        t = Traktandum.objects.get()

        r = self.post(f'/neu/stweg/versammlung/{v.pk}/einladung/', folgen=True)
        self.assertContains(r, '3 per E-Mail versendet')
        self.assertEqual(len(mail.outbox), 3)
        v.refresh_from_db()
        self.assertEqual(v.status, 'eingeladen')

        # Traktanden sind nach dem Versand gesperrt
        self.post(f'/neu/stweg/versammlung/{v.pk}/traktandum/neu/', {'titel': 'Nachträglich'})
        self.assertEqual(Traktandum.objects.count(), 1)

        self.post(f'/neu/stweg/versammlung/{v.pk}/durchfuehren/')
        daten = {f'art_{e.pk}': 'anwesend' for e in self.e[:2]}
        daten[f'art_{self.e[2].pk}'] = 'abwesend'
        daten['leitung'] = 'Verwalter'
        self.post(f'/neu/stweg/versammlung/{v.pk}/anwesenheit/', daten)
        self.assertEqual(Anwesenheit.objects.filter(art='anwesend').count(), 2)

        self.post(f'/neu/stweg/traktandum/{t.pk}/stimmen/',
                  {f'stimme_{self.e[0].pk}': 'ja', f'stimme_{self.e[1].pk}': 'ja'})
        self.assertEqual(Stimme.objects.filter(wert='ja').count(), 2)
        seite = c.get(f'/neu/stweg/versammlung/{v.pk}/')
        self.assertContains(seite, 'Rechnerischer Vorschlag')

        # Protokoll erst nach Feststellung
        r = self.post(f'/neu/stweg/versammlung/{v.pk}/protokoll/versenden/', folgen=True)
        self.assertContains(r, 'noch kein festgestelltes Ergebnis')
        mail.outbox.clear()
        self.post(f'/neu/stweg/traktandum/{t.pk}/feststellen/',
                  {'ergebnis': 'angenommen', 'beschlusstext': 'Genehmigt'})
        t.refresh_from_db()
        self.assertEqual(t.ergebnis, 'angenommen')

        r = self.post(f'/neu/stweg/versammlung/{v.pk}/protokoll/versenden/', folgen=True)
        self.assertContains(r, 'Protokoll an 3 Eigentümer versendet')
        self.assertEqual(len(mail.outbox), 3)
        v.refresh_from_db()
        self.assertEqual(v.status, 'protokolliert')

        # Vollzug des Beschlusses steht als Aufgabe in den offenen Punkten
        self.assertContains(c.get(f'/neu/stweg/{self.lg.pk}/'), 'Rechnung ablegen')
        for art in ('einladung', 'protokoll'):
            pdf = c.get(f'/neu/stweg/versammlung/{v.pk}/pdf/{art}/')
            self.assertEqual(pdf.status_code, 200)
            self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.assertEqual(c.get(f'/neu/stweg/versammlung/{v.pk}/pdf/xyz/').status_code, 404)

    def test_anfrage_und_aufgabe_ueber_oberflaeche(self):
        self.post(f'/neu/stweg/{self.lg.pk}/anfrage/neu/',
                  {'betreff': 'Waschküche', 'einheit': self.e[0].pk, 'kanal': 'telefon'})
        from stweg.models import StwegAnfrage
        a = StwegAnfrage.objects.get()
        self.assertContains(self.client.get(f'/neu/stweg/{self.lg.pk}/'), 'Waschküche')
        self.post(f'/neu/stweg/anfrage/{a.pk}/beantworten/', {'antwort': 'Wird repariert.'})
        a.refresh_from_db()
        self.assertEqual(a.status, 'beantwortet')
        self.assertEqual(mail.outbox[-1].to, ['a@x.ch'])
        self.post(f'/neu/stweg/{self.lg.pk}/aufgabe/neu/', {'titel': 'Schlüssel bestellen'})
        from core.models import Pendenz
        p = Pendenz.objects.get(titel='Schlüssel bestellen')
        self.post(f'/neu/stweg/aufgabe/{p.pk}/erledigt/')
        p.refresh_from_db()
        self.assertTrue(p.erledigt)

    def test_lesezugriff_darf_nichts_aendern(self):
        lese = _team_user('Lesend')
        self.client.force_login(lese)
        self.assertEqual(self.client.get(f'/neu/stweg/{self.lg.pk}/').status_code, 200)
        r = self.post(f'/neu/stweg/{self.lg.pk}/aufgabe/neu/', {'titel': 'Nein'})
        self.assertEqual(r.status_code, 403)

    def test_get_auf_aktion_ist_nicht_erlaubt(self):
        self.assertEqual(self.client.get(f'/neu/stweg/{self.lg.pk}/aufgabe/neu/').status_code, 405)

    def test_anonym_wird_zur_anmeldung_geleitet(self):
        self.client.logout()
        self.assertEqual(self.client.get('/neu/stweg/').status_code, 302)


class OberflaecheIsolationTests(TestCase):
    """Eine fremde Verwaltung kommt über keine Adresse an Daten dieser Gemeinschaft."""

    def setUp(self):
        from core.tenancy import organisation_kontext
        from crm.models import Organisation
        from stweg import anfragen
        from stweg.test_versammlung import versammlung
        self.lg, self.e, self.eigs = sonnenblick()
        self.v = versammlung(self.lg)
        self.t = self.v.traktanden.get()
        self.anfrage = anfragen.anfrage_erfassen(self.lg, 'Geheim')
        fremd = Organisation.objects.create(firma='Fremd AG', strasse='X 1', plz='9000', ort='SG')
        from crm.models import Mitgliedschaft
        self.user = _team_user('Verwaltung')
        # Der Benutzer arbeitet in der FREMDEN Verwaltung.
        Mitgliedschaft.objects.filter(benutzer=self.user).update(organisation=fremd)
        self.client.force_login(self.user)
        self.fremd = fremd
        with organisation_kontext(fremd):
            pass

    def test_fremde_objekte_sind_404(self):
        v, t, a, lg = self.v.pk, self.t.pk, self.anfrage.pk, self.lg.pk
        for methode, url in [
            ('get', f'/neu/stweg/{lg}/'),
            ('get', f'/neu/stweg/versammlung/{v}/'),
            ('get', f'/neu/stweg/versammlung/{v}/pdf/einladung/'),
            ('get', f'/neu/stweg/{lg}/einheiten/'),
            ('post', f'/neu/stweg/{lg}/einheiten/speichern/'),
            ('post', f'/neu/stweg/{lg}/einheiten/neu/'),
            ('post', f'/neu/stweg/{lg}/eigentuemer/neu/'),
            ('post', f'/neu/stweg/{lg}/aktivieren/'),
            ('post', f'/neu/stweg/{lg}/versammlung/neu/'),
            ('post', f'/neu/stweg/{lg}/anfrage/neu/'),
            ('post', f'/neu/stweg/{lg}/aufgabe/neu/'),
            ('post', f'/neu/stweg/versammlung/{v}/einladung/'),
            ('post', f'/neu/stweg/versammlung/{v}/traktandum/neu/'),
            ('post', f'/neu/stweg/versammlung/{v}/durchfuehren/'),
            ('post', f'/neu/stweg/versammlung/{v}/protokoll/versenden/'),
            ('post', f'/neu/stweg/traktandum/{t}/loeschen/'),
            ('post', f'/neu/stweg/traktandum/{t}/stimmen/'),
            ('post', f'/neu/stweg/traktandum/{t}/feststellen/'),
            ('post', f'/neu/stweg/anfrage/{a}/beantworten/'),
            ('post', f'/neu/stweg/anfrage/{a}/erledigt/'),
        ]:
            antwort = getattr(self.client, methode)(url, {'antwort': 'x', 'titel': 'x'})
            self.assertEqual(antwort.status_code, 404, f'{methode} {url}')
        self.assertNotContains(self.client.get('/neu/stweg/'), 'Sonnenblick')
