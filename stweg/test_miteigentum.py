"""Miteigentum: mehrere Personen an einer Einheit, eine Stimme."""
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase

from core.tests._helfer import _team_user
from crm.models import Eigentuemer
from stweg import beschluss, zirkular
from stweg.models import Anwesenheit, StwegAnfrage, Vollmacht
from stweg.test_versammlung import sonnenblick, versammlung
from stweg.test_zirkular import neuer_zirkular
from stweg.versammlung import durchfuehren, einladung_versenden, empfaenger

User = get_user_model()


def mit_ehepartner():
    """Sonnenblick; Whg 1 gehört Anna UND ihrem Mann Max (Hauptansprechperson: Anna)."""
    lg, e, eigs = sonnenblick()
    max_ = Eigentuemer.objects.create(firma_oder_name='Max', email='max@x.ch')
    e[0].miteigentuemer.add(max_)
    return lg, e, eigs, max_


class MiteigentumServiceTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs, self.max = mit_ehepartner()

    def test_miteigentuemer_bekommen_einladung_und_protokoll(self):
        eig, ohne = empfaenger(versammlung(self.lg))
        self.assertEqual({x.firma_oder_name for x in eig}, {'Anna', 'Bruno', 'Carla', 'Max'})
        self.assertEqual(ohne, [])
        v = versammlung(self.lg)
        einladung_versenden(v)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['a@x.ch', 'b@x.ch', 'c@x.ch', 'max@x.ch'])

    def test_wer_miteigentuemer_und_eigentuemer_ist_wird_nur_einmal_eingeladen(self):
        self.e[1].miteigentuemer.add(self.eigs[0])                # Anna auch bei Whg 2
        eig, _ = empfaenger(versammlung(self.lg))
        self.assertEqual(sorted(x.firma_oder_name for x in eig), ['Anna', 'Bruno', 'Carla', 'Max'])

    def test_miteigentuemer_ersetzt_nicht_die_hauptansprechperson(self):
        self.e[0].stockwerkeigentuemer = None
        self.e[0].save()
        _, ohne = empfaenger(versammlung(self.lg))
        self.assertEqual([x.pk for x in ohne], [self.e[0].pk])

    def test_eine_einheit_hat_genau_eine_stimme_und_einen_kopf(self):
        v = versammlung(self.lg)
        einladung_versenden(v)
        durchfuehren(v)
        for e in self.e:
            beschluss.anwesenheit_setzen(v, e, Anwesenheit.ANWESEND)
            beschluss.stimme_abgeben(v.traktanden.get(), e, 'ja')
        z = beschluss.auswerten(v.traktanden.get())
        self.assertEqual((z['ja_koepfe'], z['total_koepfe']), (3, 3))     # Max zählt nicht extra

    def test_zirkularversand_erreicht_auch_die_miteigentuemer(self):
        zirkular.versenden(neuer_zirkular(self.lg))
        self.assertIn('max@x.ch', [m.to[0] for m in mail.outbox])


class MiteigentumPortalTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs, self.max = mit_ehepartner()
        self.v = versammlung(self.lg)
        einladung_versenden(self.v)
        self.z = neuer_zirkular(self.lg)
        zirkular.versenden(self.z)
        u = User.objects.create_user(username='max', password='x')
        self.max.benutzer = u
        self.max.save()
        self.c = Client()
        self.c.force_login(u)
        ua = User.objects.create_user(username='anna_m', password='x')
        self.eigs[0].benutzer = ua
        self.eigs[0].save()
        self.anna = Client()
        self.anna.force_login(ua)

    def test_miteigentuemer_sieht_einheit_einladung_und_antrag(self):
        seite = self.c.get('/portal/stweg/')
        self.assertContains(seite, 'Whg 1')
        self.assertContains(seite, 'Miteigentum — Hauptansprechperson: Anna')
        self.assertNotContains(seite, 'Whg 2')
        self.assertContains(seite, self.v.titel)
        self.assertContains(seite, self.z.titel)
        r = self.c.get(f'/portal/stweg/einladung/{self.v.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.get(f'/portal/stweg/zirkular/{self.z.pk}/').status_code, 200)

    def test_miteigentuemer_hat_keine_handlungsformulare(self):
        seite = self.c.get('/portal/stweg/')
        self.assertContains(seite, 'Die Stimme für Ihre Einheit gibt die Hauptansprechperson ab.')
        self.assertNotContains(seite, 'Ihre Stimme für Whg 1')
        self.assertNotContains(seite, 'Anfrage an die Verwaltung')
        self.assertNotContains(seite, 'Vollmacht erteilen')

    def test_miteigentuemer_kann_weder_abstimmen_noch_bevollmaechtigen_noch_anfragen(self):
        from stweg.models import ZirkularStimme
        self.c.post(f'/portal/stweg/abstimmen/{self.z.pk}/', {f'stimme_{self.e[0].pk}': 'ja'})
        self.assertEqual(ZirkularStimme.objects.count(), 0)
        r = self.c.post(f'/portal/stweg/vollmacht/{self.v.pk}/erteilen/',
                        {'einheit': self.e[0].pk, 'bevollmaechtigter': 'Fremder'})
        self.assertEqual((r.status_code, Vollmacht.objects.count()), (404, 0))
        r = self.c.post(f'/portal/stweg/anfrage/{self.lg.pk}/', {'betreff': 'Hallo'})
        self.assertEqual((r.status_code, StwegAnfrage.objects.count()), (404, 0))

    def test_miteigentuemer_kann_fremde_vollmacht_nicht_widerrufen(self):
        from stweg.vollmacht import erteilen
        vm = erteilen(self.v, self.e[0], 'Tante')
        self.assertEqual(self.c.post(f'/portal/stweg/vollmacht/{vm.pk}/widerrufen/').status_code, 404)
        vm.refresh_from_db()
        self.assertTrue(vm.gueltig)

    def test_hauptansprechperson_kann_alles_wie_bisher(self):
        from stweg.models import ZirkularStimme
        self.anna.post(f'/portal/stweg/abstimmen/{self.z.pk}/', {f'stimme_{self.e[0].pk}': 'ja'})
        self.assertEqual(ZirkularStimme.objects.count(), 1)

    def test_nur_die_eigene_gemeinschaft_ist_sichtbar(self):
        from stweg.tests import neue_stweg
        nachbar_lg, nachbar_e = neue_stweg(name='Nachbar')
        nachbar_e[0].miteigentuemer.add(self.max)                  # Max ist dort ebenfalls Miteigentümer
        seite = self.c.get('/portal/stweg/')
        self.assertContains(seite, 'Nachbarweg 1')                 # …und sieht sie
        # aber nicht die Versammlungen einer dritten Gemeinschaft
        dritte_lg, dritte_e = neue_stweg(name='Dritte')
        dritte_v = versammlung(dritte_lg)
        from django.utils import timezone
        dritte_v.einladung_versendet_am = timezone.now()
        dritte_v.save()
        self.assertEqual(self.c.get(f'/portal/stweg/einladung/{dritte_v.pk}/').status_code, 404)


class MiteigentumOberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.max = Eigentuemer.objects.create(firma_oder_name='Max')
        self.client.force_login(_team_user('Verwaltung'))
        self.url = f'/neu/stweg/{self.lg.pk}/einheiten/speichern/'

    def test_miteigentuemer_zuteilen_aendern_und_entfernen(self):
        self.client.post(self.url, {f'mit_set_{self.e[0].pk}': '1', f'mit_{self.e[0].pk}': [self.max.pk]})
        self.assertEqual(list(self.e[0].miteigentuemer.all()), [self.max])
        self.client.post(self.url, {f'mit_set_{self.e[0].pk}': '1'})        # nichts gewählt → leer
        self.assertEqual(self.e[0].miteigentuemer.count(), 0)

    def test_ohne_marker_bleibt_alles_unveraendert(self):
        self.e[0].miteigentuemer.add(self.max)
        self.client.post(self.url, {f'quote_{self.e[0].pk}': '200'})
        self.assertEqual(self.e[0].miteigentuemer.count(), 1)

    def test_hauptansprechperson_wird_nie_zugleich_miteigentuemer(self):
        self.client.post(self.url, {f'eig_{self.e[0].pk}': self.eigs[0].pk,
                                    f'mit_set_{self.e[0].pk}': '1',
                                    f'mit_{self.e[0].pk}': [self.eigs[0].pk, self.max.pk]})
        self.assertEqual(list(self.e[0].miteigentuemer.all()), [self.max])

    def test_fremder_miteigentuemer_wird_abgelehnt_und_nichts_gespeichert(self):
        from core.tenancy import organisation_kontext
        from crm.models import Organisation
        fremd = Organisation.objects.create(firma='Fremd AG', strasse='X 1', plz='9000', ort='SG')
        with organisation_kontext(fremd):
            f_eig = Eigentuemer.objects.create(firma_oder_name='Fritz')
        r = self.client.post(self.url, {f'quote_{self.e[1].pk}': '300',
                                        f'mit_set_{self.e[0].pk}': '1',
                                        f'mit_{self.e[0].pk}': [f_eig.pk]}, follow=True)
        self.assertContains(r, 'Miteigentümer ist nicht (mehr) erfasst')
        self.assertEqual(self.e[0].miteigentuemer.count(), 0)

    def test_seite_zeigt_miteigentuemer(self):
        self.e[0].miteigentuemer.add(self.max)
        seite = self.client.get(f'/neu/stweg/{self.lg.pk}/einheiten/')
        self.assertContains(seite, 'Miteigentümer von «Whg 1» (1)')
