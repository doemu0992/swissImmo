"""Das Portal der Stockwerkeigentümer: sehen, was ihnen gehört — und nichts sonst."""
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase

from crm.models import Eigentuemer
from stweg import anfragen
from stweg.models import StwegAnfrage
from stweg.test_versammlung import sonnenblick, versammlung
from stweg.versammlung import einladung_versenden

User = get_user_model()


class PortalTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.v = versammlung(self.lg)
        self.logins = {}
        for eig in self.eigs:
            u = User.objects.create_user(username=f'eig_{eig.firma_oder_name}', password='x')
            eig.benutzer = u
            eig.save()
            self.logins[eig.firma_oder_name] = u
        self.anna = self._client('Anna')
        self.bruno = self._client('Bruno')

    def _client(self, name):
        c = Client()
        c.force_login(self.logins[name])
        return c

    def test_seite_zeigt_nur_eigene_einheit_und_eigene_anfragen(self):
        anfragen.anfrage_erfassen(self.lg, 'Annas Frage', einheit=self.e[0])
        anfragen.anfrage_erfassen(self.lg, 'Brunos Frage', einheit=self.e[1])
        seite = self.anna.get('/portal/stweg/')
        self.assertContains(seite, 'Whg 1')
        self.assertNotContains(seite, 'Whg 2')
        self.assertContains(seite, 'Annas Frage')
        self.assertNotContains(seite, 'Brunos Frage')

    def test_entwurf_ist_unsichtbar_und_nicht_abrufbar(self):
        self.assertNotContains(self.anna.get('/portal/stweg/'), self.v.titel)
        self.assertEqual(self.anna.get(f'/portal/stweg/einladung/{self.v.pk}/').status_code, 404)

    def test_einladung_und_protokoll_erst_nach_versand(self):
        einladung_versenden(self.v)
        self.assertContains(self.anna.get('/portal/stweg/'), f'/portal/stweg/einladung/{self.v.pk}/')
        r = self.anna.get(f'/portal/stweg/einladung/{self.v.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertEqual(self.anna.get(f'/portal/stweg/protokoll/{self.v.pk}/').status_code, 404)
        from django.utils import timezone
        self.v.protokoll_versendet_am = timezone.now()
        self.v.save()
        self.assertEqual(self.anna.get(f'/portal/stweg/protokoll/{self.v.pk}/').status_code, 200)

    def test_anfrage_stellen_wird_zur_pendenz(self):
        mail.outbox.clear()
        r = self.anna.post(f'/portal/stweg/anfrage/{self.lg.pk}/', {'betreff': 'Lift?', 'text': 'Defekt'})
        self.assertEqual(r.status_code, 302)
        a = StwegAnfrage.objects.get()
        self.assertEqual((a.eigentuemer, a.einheit, a.kanal), (self.eigs[0], self.e[0], 'portal'))
        from core.models import Pendenz
        self.assertTrue(Pendenz.objects.filter(quelle=f'stweg:anfrage:{a.pk}', erledigt=False).exists())

    def test_leerer_betreff_legt_nichts_an(self):
        self.anna.post(f'/portal/stweg/anfrage/{self.lg.pk}/', {'betreff': ' '})
        self.assertEqual(StwegAnfrage.objects.count(), 0)

    def test_get_auf_anfrage_nicht_erlaubt(self):
        self.assertEqual(self.anna.get(f'/portal/stweg/anfrage/{self.lg.pk}/').status_code, 405)

    def test_nicht_angemeldet_wird_umgeleitet(self):
        self.assertEqual(Client().get('/portal/stweg/').status_code, 302)

    def test_benutzer_ohne_eigentuemerprofil_bekommt_404(self):
        c = Client()
        c.force_login(User.objects.create_user(username='niemand', password='x'))
        self.assertEqual(c.get('/portal/stweg/').status_code, 404)


class PortalFremdzugriffTests(TestCase):
    """Ein Eigentümer einer ANDEREN Gemeinschaft (auch einer anderen Verwaltung)."""

    def setUp(self):
        from core.tenancy import organisation_kontext
        from crm.models import Organisation
        from portfolio.models import Einheit, Liegenschaft
        self.lg, self.e, self.eigs = sonnenblick()
        self.v = versammlung(self.lg)
        einladung_versenden(self.v)
        self.anfrage = anfragen.anfrage_erfassen(self.lg, 'Annas Frage', einheit=self.e[0])

        # Eigentümer C: gleiche Verwaltung, andere Gemeinschaft
        self.fremd_org = Organisation.objects.create(firma='Fremd AG', strasse='X 1', plz='9000', ort='SG')
        with organisation_kontext(self.fremd_org):
            fremd_lg = Liegenschaft.objects.create(strasse='Fremdweg 1', plz='9000', ort='SG',
                                                   typ='STWEG', status='entwurf',
                                                   organisation=self.fremd_org)
            self.fremd_eig = Eigentuemer.objects.create(firma_oder_name='Fritz', email='f@x.ch')
            Einheit.objects.create(liegenschaft=fremd_lg, bezeichnung='F1', typ='stwe',
                                   stockwerkeigentuemer=self.fremd_eig, wertquote=1000)
            u = User.objects.create_user(username='fritz', password='x')
            self.fremd_eig.benutzer = u
            self.fremd_eig.save()
        self.fritz = Client()
        self.fritz.force_login(u)

    def test_fremder_sieht_nichts_von_dieser_gemeinschaft(self):
        seite = self.fritz.get('/portal/stweg/')
        self.assertNotContains(seite, 'Sonnenblick')
        self.assertNotContains(seite, self.v.titel)
        self.assertNotContains(seite, 'Annas Frage')

    def test_fremde_ids_sind_404(self):
        for url in (f'/portal/stweg/einladung/{self.v.pk}/', f'/portal/stweg/protokoll/{self.v.pk}/'):
            self.assertEqual(self.fritz.get(url).status_code, 404, url)
        r = self.fritz.post(f'/portal/stweg/anfrage/{self.lg.pk}/', {'betreff': 'Einbruch'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(StwegAnfrage.objects.count(), 1)

    def test_berechtigter_kommt_an_seine_daten(self):
        """Gegenstück: ohne das wäre jede 404-Prüfung oben wertlos."""
        c = Client()
        u = User.objects.create_user(username='anna', password='x')
        self.eigs[0].benutzer = u
        self.eigs[0].save()
        c.force_login(u)
        self.assertEqual(c.get(f'/portal/stweg/einladung/{self.v.pk}/').status_code, 200)


class PortalAndereGemeinschaftDerselbenVerwaltungTests(TestCase):
    """Die schwierigere Grenze: gleiche Verwaltung, aber nicht MEINE Gemeinschaft.

    Die Organisationsgrenze sichert der `TenantManager`; dass ein Eigentümer
    nicht in die Nachbargemeinschaft derselben Verwaltung sieht, sichert allein
    die Besitzprüfung im Portal — und braucht deshalb einen eigenen Test."""

    def setUp(self):
        from stweg.tests import neue_stweg
        self.lg, self.e, self.eigs = sonnenblick()
        self.v = versammlung(self.lg)
        einladung_versenden(self.v)
        from django.utils import timezone
        self.v.protokoll_versendet_am = timezone.now()
        self.v.save()
        nachbar_lg, nachbar_e = neue_stweg(name='Nachbar')
        dora = Eigentuemer.objects.create(firma_oder_name='Dora', email='d@x.ch')
        nachbar_e[0].stockwerkeigentuemer = dora
        nachbar_e[0].save()
        u = User.objects.create_user(username='dora', password='x')
        dora.benutzer = u
        dora.save()
        self.dora = Client()
        self.dora.force_login(u)

    def test_nachbargemeinschaft_ist_404(self):
        for url in (f'/portal/stweg/einladung/{self.v.pk}/', f'/portal/stweg/protokoll/{self.v.pk}/'):
            self.assertEqual(self.dora.get(url).status_code, 404, url)
        r = self.dora.post(f'/portal/stweg/anfrage/{self.lg.pk}/', {'betreff': 'Hallo'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(StwegAnfrage.objects.count(), 0)
        self.assertNotContains(self.dora.get('/portal/stweg/'), self.v.titel)


class PortalBenachrichtigungTests(TestCase):
    """Wer erfährt von einer neuen Portal-Anfrage — und was, wenn niemand erreichbar ist."""

    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        u = User.objects.create_user(username='anna_b', password='x')
        self.eigs[0].benutzer = u
        self.eigs[0].save()
        self.c = Client()
        self.c.force_login(u)
        self.org = self.lg.organisation
        mail.outbox.clear()

    def anfrage(self):
        return self.c.post(f'/portal/stweg/anfrage/{self.lg.pk}/', {'betreff': 'Lift?', 'text': 'Defekt'})

    def test_betreuende_person_bekommt_den_hinweis(self):
        betreuer = User.objects.create_user(username='betreuer', password='x', email='lea@verwaltung.ch')
        self.lg.betreut_von = betreuer
        self.lg.save()
        self.org.email = 'info@verwaltung.ch'
        self.org.save()
        self.anfrage()
        self.assertEqual([m.to for m in mail.outbox], [['lea@verwaltung.ch']])
        self.assertIn('Defekt', mail.outbox[0].body)
        self.assertIn('Anna', mail.outbox[0].body)

    def test_ohne_betreuung_geht_der_hinweis_an_die_verwaltung(self):
        self.org.email = 'info@verwaltung.ch'
        self.org.save()
        self.anfrage()
        self.assertEqual([m.to for m in mail.outbox], [['info@verwaltung.ch']])

    def test_ohne_adresse_bleibt_die_anfrage_erhalten_und_der_mangel_wird_protokolliert(self):
        self.org.email = ''
        self.org.save()
        with self.assertLogs('stweg.anfragen', level='WARNING') as log:
            r = self.anfrage()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(StwegAnfrage.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('keine Empfängeradresse', ' '.join(log.output))

    def test_scheitert_die_mail_bleibt_die_anfrage(self):
        from unittest import mock
        self.org.email = 'info@verwaltung.ch'
        self.org.save()
        with mock.patch('stweg.anfragen.send_mail', side_effect=OSError('SMTP weg')), \
                self.assertLogs('stweg.anfragen', level='WARNING') as log:
            r = self.anfrage()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(StwegAnfrage.objects.count(), 1)
        self.assertIn('fehlgeschlagen', ' '.join(log.output))
