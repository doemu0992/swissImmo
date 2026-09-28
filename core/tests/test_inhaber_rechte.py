"""Der Inhaber darf, was das Team darf.

Nach der Rollentabelle (`docs/KONZEPT-UI.md`, Abschnitt 8) hat der Inhaber
jede Befugnis der übrigen Team-Rollen. Rund zwanzig Views verlangten aber nur
`ROLLE_VERWALTER`: Der Inhaber einer mit `organisation_anlegen` frisch
angelegten Verwaltung bekam auf Logbuch, Zahllauf, Anlagen und — ausgerechnet
— «Benutzer & Rollen» ein 403.

Gegenprobe: Ohne die Erweiterung in `hat_rolle()` sind die beiden ersten
Tests rot (403 statt 200 bzw. False statt True).
"""
from django.test import TestCase

from core.auth import (
    ROLLE_EIGENTUEMER, ROLLE_INHABER, ROLLE_LESEZUGRIFF, ROLLE_VERWALTER,
    VERWALTUNGS_ROLLEN, hat_rolle,
)
from core.tests._helfer import _team_user

#: Seiten, die nur `ROLLE_VERWALTER` verlangen — der Kern des Befunds.
NUR_VERWALTER_SEITEN = (
    '/neu/logbuch/',
    '/neu/zahllauf/',
    '/neu/anlagen/',
    '/neu/benutzer/neu/',
)


class InhaberRechteTests(TestCase):

    def test_inhaber_oeffnet_verwalter_seiten(self):
        self.client.force_login(_team_user('Inhaber'))
        for pfad in NUR_VERWALTER_SEITEN:
            with self.subTest(pfad=pfad):
                self.assertEqual(self.client.get(pfad).status_code, 200)

    def test_inhaber_erfuellt_jede_team_rolle(self):
        u = _team_user('Inhaber')
        self.assertTrue(hat_rolle(u, [ROLLE_VERWALTER]))
        self.assertTrue(hat_rolle(u, [ROLLE_LESEZUGRIFF]))
        self.assertTrue(hat_rolle(u, VERWALTUNGS_ROLLEN))

    def test_lesezugriff_bleibt_ausgesperrt(self):
        """Die Erweiterung gilt der Inhaber-Rolle, nicht allen."""
        self.client.force_login(_team_user('Lesezugriff'))
        for pfad in NUR_VERWALTER_SEITEN:
            with self.subTest(pfad=pfad):
                self.assertEqual(self.client.get(pfad).status_code, 403)

    def test_verwalter_bekommt_keine_inhaber_rechte(self):
        """Die Richtung ist einseitig: Verwalter ⊉ Inhaber."""
        u = _team_user('Verwalter')
        self.assertFalse(hat_rolle(u, [ROLLE_INHABER]))

    def test_portal_rolle_wird_nicht_erweitert(self):
        """Inhaber ist Team-Rolle; die Eigentümer-Prüfung bleibt unberührt."""
        u = _team_user('Inhaber')
        self.assertFalse(hat_rolle(u, [ROLLE_EIGENTUEMER]))
