"""Die Rollentabelle (docs/KONZEPT-UI.md §8) gilt auch im Code.

Angeglichen am 28.09.2026 — vorher wich der Bestand an drei Stellen ab:

  Abo ändern                      bisher auch Sachbearbeitung → nur Inhaber
  Mitglieder und Rollen verwalten bisher Verwalter            → nur Inhaber
  Kündigung erfassen, bestätigen,
  zurücknehmen                    bisher auch Sachbearbeitung → Inhaber, Verwalter

Jede Gruppe hat eine Sperrprüfung UND ein Gegenstück, das zeigt, dass die
berechtigte Rolle die Handlung weiterhin ausführen kann — sonst bestünde die
Sperrprüfung auch dann, wenn die Funktion für niemanden mehr ginge.

Gegenprobe: Mit den alten Dekoratoren/Prüfungen sind die Sperrprüfungen rot.
"""
from datetime import date

from django.test import Client, TestCase

from core.tests._helfer import _basis_objekte, _team_user, _test_organisation


def _client(rolle):
    c = Client()
    c.force_login(_team_user(rolle))
    return c


class AboNurInhaberTests(TestCase):

    def setUp(self):
        self.org = _test_organisation()
        self.org.abo_plan = 'pro'
        self.org.save(update_fields=['abo_plan'])

    def _waehlen(self, rolle):
        _client(rolle).post('/neu/abonnement/', {'plan': 'premium'})
        self.org.refresh_from_db()
        return self.org.abo_plan

    def test_sachbearbeiter_aendert_den_plan_nicht(self):
        self.assertEqual(self._waehlen('Sachbearbeiter'), 'pro')

    def test_verwalter_aendert_den_plan_nicht(self):
        self.assertEqual(self._waehlen('Verwalter'), 'pro')

    def test_inhaber_aendert_den_plan(self):
        self.assertEqual(self._waehlen('Inhaber'), 'premium')

    def test_ansehen_bleibt_fuer_das_team_ohne_knopf(self):
        antwort = _client('Sachbearbeiter').get('/neu/abonnement/')
        self.assertEqual(antwort.status_code, 200)
        self.assertNotContains(antwort, 'Plan wählen')
        self.assertContains(antwort, 'nur der Inhaber')

    def test_inhaber_sieht_den_knopf(self):
        self.assertContains(_client('Inhaber').get('/neu/abonnement/'), 'Plan wählen')


class MitgliederNurInhaberTests(TestCase):

    def setUp(self):
        _test_organisation()
        self.ziel = _team_user('Sachbearbeiter')

    def test_verwalter_legt_niemanden_an(self):
        self.assertEqual(_client('Verwalter').get('/neu/benutzer/neu/').status_code, 403)

    def test_verwalter_macht_sich_nicht_zum_inhaber(self):
        """Der eigentliche Befund: Die Rollenauswahl enthält «Inhaber», das
        eigene Konto war nicht ausgenommen."""
        from crm.models import Mitgliedschaft
        verwalter = _team_user('Verwalter')
        c = Client(); c.force_login(verwalter)
        antwort = c.post(f'/neu/benutzer/{verwalter.pk}/bearbeiten/',
                         {'username': verwalter.username, 'rolle': 'Inhaber'})
        self.assertEqual(antwort.status_code, 403)
        self.assertEqual(Mitgliedschaft.objects.get(benutzer=verwalter).rolle, 'Verwalter')

    def test_verwalter_loescht_niemanden(self):
        from benutzer.models import Benutzer
        antwort = _client('Verwalter').post(f'/neu/benutzer/{self.ziel.pk}/loeschen/')
        self.assertEqual(antwort.status_code, 403)
        self.assertTrue(Benutzer.objects.filter(pk=self.ziel.pk).exists())

    def test_inhaber_loescht(self):
        from benutzer.models import Benutzer
        _client('Inhaber').post(f'/neu/benutzer/{self.ziel.pk}/loeschen/')
        self.assertFalse(Benutzer.objects.filter(pk=self.ziel.pk).exists())

    def test_liste_bleibt_sichtbar_ohne_bearbeiten(self):
        antwort = _client('Verwalter').get('/neu/benutzer/')
        self.assertEqual(antwort.status_code, 200)
        self.assertNotContains(antwort, '/neu/benutzer/neu/')
        self.assertNotContains(antwort, f'/neu/benutzer/{self.ziel.pk}/loeschen/')

    def test_inhaber_sieht_die_aktionen(self):
        antwort = _client('Inhaber').get('/neu/benutzer/')
        self.assertContains(antwort, '/neu/benutzer/neu/')
        self.assertContains(antwort, f'/neu/benutzer/{self.ziel.pk}/loeschen/')


class KuendigungOhneSachbearbeitungTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()   # v ist aktiv
        self.daten = {'absender': 'mieter', 'eingang_datum': date.today().isoformat(),
                      'zustellung': 'einschreiben'}

    def _offene_kuendigung(self):
        from rentals.models import Kuendigung
        return Kuendigung.objects.create(
            vertrag=self.v, absender='mieter', eingang_datum=date.today(),
            berechneter_termin=date(2027, 3, 31), per_datum=date(2027, 3, 31), status='erfasst')

    def test_sachbearbeiter_erfasst_keine_kuendigung(self):
        """Schon das Erfassen setzt den Vertrag auf «gekündigt» — darum reicht
        es nicht, nur die Bestätigung zu sperren."""
        antwort = _client('Sachbearbeiter').post(f'/neu/vertraege/{self.v.pk}/kuendigen/',
                                                 {**self.daten, 'bestaetigen': 'on'})
        self.assertEqual(antwort.status_code, 403)
        self.v.refresh_from_db()
        self.assertEqual(self.v.status, 'aktiv')

    def test_sachbearbeiter_bestaetigt_nicht(self):
        k = self._offene_kuendigung()
        antwort = _client('Sachbearbeiter').post(f'/neu/kuendigung/{k.pk}/bestaetigen/')
        self.assertEqual(antwort.status_code, 403)
        k.refresh_from_db()
        self.assertEqual(k.status, 'erfasst')

    def test_sachbearbeiter_nimmt_nicht_zurueck(self):
        k = self._offene_kuendigung()
        antwort = _client('Sachbearbeiter').post(f'/neu/kuendigung/{k.pk}/zuruecknehmen/')
        self.assertEqual(antwort.status_code, 403)
        k.refresh_from_db()
        self.assertEqual(k.status, 'erfasst')

    def test_verwalter_erfasst(self):
        _client('Verwalter').post(f'/neu/vertraege/{self.v.pk}/kuendigen/', self.daten)
        self.v.refresh_from_db()
        self.assertEqual(self.v.status, 'gekuendigt')

    def test_verwalter_bestaetigt(self):
        k = self._offene_kuendigung()
        _client('Verwalter').post(f'/neu/kuendigung/{k.pk}/bestaetigen/')
        k.refresh_from_db()
        self.assertEqual(k.status, 'bestaetigt')

    def test_sachbearbeiter_sieht_die_knoepfe_nicht(self):
        k = self._offene_kuendigung()
        antwort = _client('Sachbearbeiter').get(f'/neu/vertraege/{self.v.pk}/')
        self.assertEqual(antwort.status_code, 200)
        self.assertNotContains(antwort, f'/neu/kuendigung/{k.pk}/bestaetigen/')
        self.assertNotContains(antwort, f'/neu/vertraege/{self.v.pk}/kuendigen/')
        self.assertContains(antwort, 'Wartet auf Bestätigung')

    def test_verwalter_sieht_die_knoepfe(self):
        k = self._offene_kuendigung()
        antwort = _client('Verwalter').get(f'/neu/vertraege/{self.v.pk}/')
        self.assertContains(antwort, f'/neu/kuendigung/{k.pk}/bestaetigen/')
        self.assertContains(antwort, f'/neu/vertraege/{self.v.pk}/kuendigen/')
