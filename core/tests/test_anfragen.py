"""Änderungsanfragen aus den Portalen: das Portal ändert nichts selbst, die Verwaltung bestätigt, nur Berechtigte, nur die eigene Verwaltung."""
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase

from core.models import AktivitaetsLog, Aenderungsanfrage
from core.services import anfragen as dienst
from core.tenancy import organisation_kontext

from ._helfer import _team_user
from ._isolation import MandantenFixture

User = get_user_model()
ART = Aenderungsanfrage


class AnfragenTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        for f in (cls.a, cls.b):
            with organisation_kontext(f.organisation):
                f.mieter.benutzer = User.objects.create_user(username=f'portal-{f.kuerzel}', password='x')
                f.mieter.email = f'mieter-{f.kuerzel.lower()}@example.ch'
                f.mieter.mobile = '079 000 00 00'
                f.mieter.save()
                f.eigentuemer.benutzer = User.objects.create_user(username=f'eig-{f.kuerzel}', password='x')
                f.eigentuemer.save()

    def _mieter_client(self, f=None):
        f = f or self.a
        c = Client()
        c.force_login(f.mieter.benutzer)
        return c

    def _verwaltung(self, f=None):
        f = f or self.a
        c = Client()
        c.force_login(f.benutzer)
        return c

    def _anfrage(self, f=None, mobile='079 111 22 33'):
        f = f or self.a
        with organisation_kontext(f.organisation):
            return dienst.stellen(art=ART.ART_KONTAKT, mieter=f.mieter, daten={'mobile': mobile})

    # --- Das Portal ändert nichts selbst -----------------------------------------------------------------------
    def test_mieter_aenderung_ist_nur_eine_anfrage(self):
        r = self._mieter_client().post('/mieter/daten/', {'mobile': '079 999 88 77', 'telefon_privat': '',
                                                          'email': self.a.mieter.email, 'adresse_meldung': ''})
        self.assertEqual(r.status_code, 302)
        with organisation_kontext(self.a.organisation):
            self.a.mieter.refresh_from_db()
            self.assertEqual(self.a.mieter.mobile, '079 000 00 00')              # unverändert
            anfrage, = Aenderungsanfrage.objects.all()
        self.assertEqual((anfrage.art, anfrage.status), (ART.ART_KONTAKT, ART.STATUS_OFFEN))
        self.assertIn('079 999 88 77', anfrage.zusammenfassung)
        self.assertEqual(anfrage.daten, {'mobile': '079 999 88 77'})

    def test_ohne_aenderung_keine_anfrage(self):
        self._mieter_client().post('/mieter/daten/', {'mobile': '079 000 00 00', 'telefon_privat': '',
                                                      'email': self.a.mieter.email, 'adresse_meldung': ''})
        self.assertFalse(Aenderungsanfrage.alle_organisationen.exists())

    def test_mitteilung_ist_eine_anfrage(self):
        self._mieter_client().post('/mieter/daten/', {'mobile': '079 000 00 00', 'email': self.a.mieter.email,
                                                      'adresse_meldung': 'Neue Korrespondenzadresse: Bahnhofstr. 1'})
        anfrage, = Aenderungsanfrage.alle_organisationen.all()
        self.assertEqual(anfrage.art, ART.ART_MITTEILUNG)
        self.assertIn('Bahnhofstr. 1', anfrage.zusammenfassung)

    def test_nicht_erlaubte_felder_werden_nie_uebernommen(self):
        with organisation_kontext(self.a.organisation):
            anfrage = dienst.stellen(art=ART.ART_KONTAKT, mieter=self.a.mieter,
                                     daten={'mobile': '079 5', 'benutzer': 1, 'organisation': 2, 'iban': 'X'})
        self.assertEqual(anfrage.daten, {'mobile': '079 5'})

    # --- Die Verwaltung entscheidet ---------------------------------------------------------------------------------
    def test_bestaetigen_fuehrt_die_aenderung_aus_protokolliert_und_meldet(self):
        anfrage = self._anfrage()
        mail.outbox.clear()
        r = self._verwaltung().post(f'/neu/anfragen/{anfrage.pk}/bestaetigen/')
        self.assertEqual(r.status_code, 302)
        anfrage.refresh_from_db()
        self.assertEqual(anfrage.status, ART.STATUS_BESTAETIGT)
        self.assertEqual(anfrage.entschieden_von, self.a.benutzer)
        with organisation_kontext(self.a.organisation):
            self.a.mieter.refresh_from_db()
        self.assertEqual(self.a.mieter.mobile, '079 111 22 33')
        self.assertTrue(AktivitaetsLog.alle_organisationen.filter(
            organisation=self.a.organisation, aktion='Änderungsanfrage bestätigt', kategorie='sicherheit').exists())
        self.assertTrue(any(m.to == [self.a.mieter.email] for m in mail.outbox))

    def test_ablehnen_aendert_nichts_und_nennt_den_grund(self):
        anfrage = self._anfrage()
        self._verwaltung().post(f'/neu/anfragen/{anfrage.pk}/ablehnen/', {'antwort': 'Nummer ungültig'})
        anfrage.refresh_from_db()
        self.assertEqual((anfrage.status, anfrage.antwort), (ART.STATUS_ABGELEHNT, 'Nummer ungültig'))
        with organisation_kontext(self.a.organisation):
            self.a.mieter.refresh_from_db()
        self.assertEqual(self.a.mieter.mobile, '079 000 00 00')
        self.assertContains(self._mieter_client().get('/mieter/daten/'), 'Nummer ungültig')

    def test_eine_entschiedene_anfrage_laesst_sich_nicht_nochmals_entscheiden(self):
        anfrage = self._anfrage()
        self._verwaltung().post(f'/neu/anfragen/{anfrage.pk}/ablehnen/')
        self._verwaltung().post(f'/neu/anfragen/{anfrage.pk}/bestaetigen/')
        anfrage.refresh_from_db()
        self.assertEqual(anfrage.status, ART.STATUS_ABGELEHNT)
        with organisation_kontext(self.a.organisation):
            self.a.mieter.refresh_from_db()
        self.assertEqual(self.a.mieter.mobile, '079 000 00 00')

    def test_get_entscheidet_nicht(self):
        anfrage = self._anfrage()
        self._verwaltung().get(f'/neu/anfragen/{anfrage.pk}/bestaetigen/')
        anfrage.refresh_from_db()
        self.assertEqual(anfrage.status, ART.STATUS_OFFEN)

    # --- Wer darf, und nur die eigene Verwaltung ---------------------------------------------------------------------
    def test_fremde_verwaltung_sieht_und_entscheidet_nichts(self):
        anfrage = self._anfrage()
        b = self._verwaltung(self.b)
        self.assertNotContains(b.get('/neu/anfragen/'), anfrage.zusammenfassung)
        self.assertEqual(b.post(f'/neu/anfragen/{anfrage.pk}/bestaetigen/').status_code, 404)
        anfrage.refresh_from_db()
        self.assertEqual(anfrage.status, ART.STATUS_OFFEN)

    def test_liste_zeigt_offene_und_mit_alle_auch_entschiedene(self):
        offen = self._anfrage(mobile='079 1')
        erledigt = self._anfrage(mobile='079 2')
        self._verwaltung().post(f'/neu/anfragen/{erledigt.pk}/ablehnen/')
        body = self._verwaltung().get('/neu/anfragen/').content.decode()
        self.assertIn(offen.zusammenfassung.split('→')[-1].strip(), body)
        self.assertNotIn('079 2', body)
        self.assertIn('079 2', self._verwaltung().get('/neu/anfragen/?alle=1').content.decode())

    def test_rollen(self):
        anfrage = self._anfrage()
        with organisation_kontext(self.a.organisation):
            for rolle, erwartet in (('Buchhaltung', 403), ('Lesezugriff', 403), ('Sachbearbeiter', 200)):
                c = Client()
                c.force_login(_team_user(rolle))
                self.assertEqual(c.get('/neu/anfragen/').status_code, erwartet, rolle)
        c = Client()
        c.force_login(self.a.mieter.benutzer)
        self.assertEqual(c.get('/neu/anfragen/').status_code, 403)
        self.assertEqual(c.post(f'/neu/anfragen/{anfrage.pk}/bestaetigen/').status_code, 403)

    def test_bankverbindung_bestaetigen_nur_inhaber_und_verwalter(self):
        with organisation_kontext(self.a.organisation):
            anfrage = dienst.stellen(art=ART.ART_EIG_BANK, eigentuemer=self.a.eigentuemer,
                                     daten={'iban': 'CH9300762011623852957', 'bank_name': 'Testbank'})
        self.assertIsNotNone(anfrage)
        from crm.models import Mitgliedschaft
        sb = User.objects.create_user(username='sachb', password='x')
        Mitgliedschaft.alle_organisationen.create(
            organisation=self.a.organisation, benutzer=sb, rolle=Mitgliedschaft.ROLLE_SACHBEARBEITER)
        c = Client()
        c.force_login(sb)
        self.assertEqual(c.post(f'/neu/anfragen/{anfrage.pk}/bestaetigen/').status_code, 403)
        anfrage.refresh_from_db()
        self.assertEqual(anfrage.status, ART.STATUS_OFFEN)
        self._verwaltung().post(f'/neu/anfragen/{anfrage.pk}/bestaetigen/')
        with organisation_kontext(self.a.organisation):
            self.a.eigentuemer.refresh_from_db()
        self.assertEqual(self.a.eigentuemer.iban, 'CH9300762011623852957')

    # --- Mieterportal: nur die eigenen Anfragen -----------------------------------------------------------------------
    def test_mieter_sieht_nur_seine_anfragen(self):
        self._anfrage(mobile='079 AAA')
        self._anfrage(self.b, mobile='079 BBB')
        body = self._mieter_client().get('/mieter/daten/').content.decode()
        self.assertIn('079 AAA', body)
        self.assertNotIn('079 BBB', body)
