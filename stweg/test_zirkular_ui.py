"""Zirkularbeschluss über Oberfläche und Portal."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase
from django.utils import timezone

from core.models import Pendenz
from core.tests._helfer import _team_user
from stweg import zirkular
from stweg.models import Zirkularbeschluss, ZirkularStimme
from stweg.test_versammlung import sonnenblick
from stweg.test_zirkular import neuer_zirkular

User = get_user_model()


class ZirkularOberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.client.force_login(_team_user('Verwaltung'))

    def test_ganzer_ablauf_ueber_die_oberflaeche(self):
        frist = (timezone.localdate() + timedelta(days=14)).isoformat()
        r = self.client.post(f'/neu/stweg/{self.lg.pk}/zirkular/neu/', {
            'titel': 'Waschmaschine ersetzen', 'antrag': 'Ersatz für CHF 3000', 'frist_bis': frist,
            'mehrheitsart': 'einstimmig', 'vollzug_aufgabe': 'Waschmaschine bestellen'})
        z = Zirkularbeschluss.objects.get()
        self.assertRedirects(r, f'/neu/stweg/zirkular/{z.pk}/')
        self.assertContains(self.client.get(f'/neu/stweg/zirkular/{z.pk}/'), 'Versandbereit')

        r = self.client.post(f'/neu/stweg/zirkular/{z.pk}/versenden/', follow=True)
        self.assertContains(r, '3 per E-Mail versendet')
        self.assertEqual(len(mail.outbox), 3)

        self.client.post(f'/neu/stweg/zirkular/{z.pk}/stimmen/',
                         {f'stimme_{e.pk}': 'ja' for e in self.e[:2]})
        self.assertEqual(ZirkularStimme.objects.filter(kanal='verwaltung').count(), 2)
        seite = self.client.get(f'/neu/stweg/zirkular/{z.pk}/')
        self.assertContains(seite, 'Die Frist läuft noch')
        # feststellen vor Fristende blockiert und sagt warum
        r = self.client.post(f'/neu/stweg/zirkular/{z.pk}/feststellen/', {'ergebnis': 'angenommen'}, follow=True)
        self.assertContains(r, 'Frist läuft noch')

        self.client.post(f'/neu/stweg/zirkular/{z.pk}/stimmen/', {f'stimme_{self.e[2].pk}': 'ja'})
        self.client.post(f'/neu/stweg/zirkular/{z.pk}/feststellen/',
                         {'ergebnis': 'angenommen', 'beschlusstext': 'Genehmigt'})
        z.refresh_from_db()
        self.assertEqual((z.status, z.ergebnis), ('abgeschlossen', 'angenommen'))
        self.assertTrue(Pendenz.objects.filter(quelle=f'stweg:zirkular:{z.pk}').exists())

        mail.outbox.clear()
        r = self.client.post(f'/neu/stweg/zirkular/{z.pk}/ergebnis/', follow=True)
        self.assertContains(r, 'Ergebnis an 3 Eigentümer versendet')
        self.assertEqual(len(mail.outbox), 3)
        self.assertTrue(self.client.get(f'/neu/stweg/zirkular/{z.pk}/pdf/').content.startswith(b'%PDF'))

    def test_eingaben_werden_geprueft(self):
        self.client.post(f'/neu/stweg/{self.lg.pk}/zirkular/neu/', {'titel': 'Nur Titel'})
        self.assertEqual(Zirkularbeschluss.objects.count(), 0)

    def test_kenntnisnahme_ist_beim_zirkular_nicht_waehlbar(self):
        frist = (timezone.localdate() + timedelta(days=5)).isoformat()
        self.client.post(f'/neu/stweg/{self.lg.pk}/zirkular/neu/', {
            'titel': 'T', 'antrag': 'A', 'frist_bis': frist, 'mehrheitsart': 'kenntnisnahme'})
        self.assertEqual(Zirkularbeschluss.objects.get().mehrheitsart, 'einstimmig')

    def test_erscheint_in_den_offenen_punkten(self):
        z = neuer_zirkular(self.lg)
        self.assertContains(self.client.get(f'/neu/stweg/{self.lg.pk}/'), f'/neu/stweg/zirkular/{z.pk}/')

    def test_lesezugriff_darf_nicht_aendern(self):
        z = neuer_zirkular(self.lg)
        self.client.force_login(_team_user('Lesend'))
        self.assertEqual(self.client.get(f'/neu/stweg/zirkular/{z.pk}/').status_code, 200)
        for pfad in ('versenden/', 'stimmen/', 'feststellen/', 'ergebnis/'):
            self.assertEqual(self.client.post(f'/neu/stweg/zirkular/{z.pk}/{pfad}', {}).status_code, 403, pfad)


class ZirkularPortalTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.z = neuer_zirkular(self.lg)
        zirkular.versenden(self.z)
        self.z.refresh_from_db()
        self.c = {}
        for eig in self.eigs:
            u = User.objects.create_user(username=f'z_{eig.firma_oder_name}', password='x')
            eig.benutzer = u
            eig.save()
            cl = Client()
            cl.force_login(u)
            self.c[eig.firma_oder_name] = cl

    def test_eigentuemer_stimmt_ab_und_aendert(self):
        seite = self.c['Anna'].get('/portal/stweg/')
        self.assertContains(seite, 'Waschmaschine ersetzen')
        self.assertContains(seite, 'Ihre Stimme für Whg 1')
        self.assertNotContains(seite, 'Ihre Stimme für Whg 2')
        self.c['Anna'].post(f'/portal/stweg/abstimmen/{self.z.pk}/', {f'stimme_{self.e[0].pk}': 'ja'})
        self.assertEqual(ZirkularStimme.objects.get().wert, 'ja')
        self.c['Anna'].post(f'/portal/stweg/abstimmen/{self.z.pk}/', {f'stimme_{self.e[0].pk}': 'nein'})
        s = ZirkularStimme.objects.get()
        self.assertEqual((s.wert, s.kanal), ('nein', 'portal'))

    def test_nur_fuer_die_eigene_einheit(self):
        self.c['Anna'].post(f'/portal/stweg/abstimmen/{self.z.pk}/',
                            {f'stimme_{self.e[1].pk}': 'ja', f'stimme_{self.e[2].pk}': 'ja'})
        self.assertEqual(ZirkularStimme.objects.count(), 0)

    def test_nach_der_frist_keine_portalstimme(self):
        Zirkularbeschluss.objects.filter(pk=self.z.pk).update(frist_bis=timezone.localdate() - timedelta(days=1))
        r = self.c['Anna'].post(f'/portal/stweg/abstimmen/{self.z.pk}/',
                                {f'stimme_{self.e[0].pk}': 'ja'}, follow=True)
        self.assertEqual(ZirkularStimme.objects.count(), 0)
        self.assertContains(r, 'Abstimmungsfrist ist abgelaufen')
        self.assertNotContains(self.c['Anna'].get('/portal/stweg/'), 'Ihre Stimme für Whg 1')

    def test_entwurf_ist_unsichtbar(self):
        entwurf = neuer_zirkular(self.lg)
        entwurf.titel = 'Geheimer Entwurf'
        entwurf.save()
        self.assertNotContains(self.c['Anna'].get('/portal/stweg/'), 'Geheimer Entwurf')
        self.assertEqual(self.c['Anna'].get(f'/portal/stweg/zirkular/{entwurf.pk}/').status_code, 404)
        self.assertEqual(self.c['Anna'].post(f'/portal/stweg/abstimmen/{entwurf.pk}/', {}).status_code, 404)

    def test_ergebnis_wird_sichtbar(self):
        for e in self.e:
            zirkular.stimme_abgeben(self.z, e, 'ja')
        zirkular.feststellen(self.z, 'angenommen')
        seite = self.c['Bruno'].get('/portal/stweg/')
        self.assertContains(seite, 'Angenommen')
        self.assertEqual(self.c['Bruno'].get(f'/portal/stweg/zirkular/{self.z.pk}/').status_code, 200)

    def test_nachbargemeinschaft_derselben_verwaltung_ist_404(self):
        from crm.models import Eigentuemer
        from stweg.tests import neue_stweg
        nachbar_lg, nachbar_e = neue_stweg(name='Nachbar')
        dora = Eigentuemer.objects.create(firma_oder_name='Dora')
        nachbar_e[0].stockwerkeigentuemer = dora
        nachbar_e[0].save()
        u = User.objects.create_user(username='dora', password='x')
        dora.benutzer = u
        dora.save()
        c = Client()
        c.force_login(u)
        self.assertEqual(c.get(f'/portal/stweg/zirkular/{self.z.pk}/').status_code, 404)
        self.assertEqual(c.post(f'/portal/stweg/abstimmen/{self.z.pk}/',
                                {f'stimme_{self.e[0].pk}': 'ja'}).status_code, 404)
        self.assertEqual(ZirkularStimme.objects.count(), 0)
        self.assertNotContains(c.get('/portal/stweg/'), 'Waschmaschine ersetzen')
