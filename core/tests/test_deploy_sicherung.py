"""deploy.sh sichert die Datenbank vor einer ausstehenden Migration (Befund Revision 2.8)."""
import os

from django.conf import settings
from django.test import SimpleTestCase


class DeploySicherungTests(SimpleTestCase):
    def setUp(self):
        with open(os.path.join(settings.BASE_DIR, 'deploy.sh')) as fh:
            self.skript = fh.read()

    def test_sicherung_steht_vor_dem_migrate(self):
        sicherung = self.skript.index('manage.py sicherung --ohne-medien')
        migrate = self.skript.index('manage.py migrate --noinput')
        self.assertLess(sicherung, migrate)

    def test_nur_bei_ausstehender_migration_und_mit_notausgang(self):
        self.assertIn('"${OFFEN:-0}" -gt 0', self.skript)
        self.assertIn('DEPLOY_OHNE_SICHERUNG', self.skript)

    def test_scheitern_der_sicherung_stoppt_vor_dem_migrate(self):
        stelle = self.skript[self.skript.index('manage.py sicherung --ohne-medien'):]
        self.assertIn('zurueckrollen "Sicherung vor der Migration fehlgeschlagen', stelle.split('manage.py migrate --noinput')[0])
