"""Die CI-Konfiguration hält ihre Zusagen (SICH-28, SICH-45).

WARUM
Die Konfiguration einer CI läuft nie lokal; ein Tippfehler fällt erst im Lauf auf, oft erst im nächsten
Monat (Zeitlauf) oder nie (ein Auslöser, der still nicht feuert). Diese Tests lesen die Dateien und prüfen
die Zusagen, die Etappe 3 gemacht hat:

* Alle Jobs laufen auf `ubuntu-24.04`. `ubuntu-latest` ist 26.04, und Playwright 1.56 unterstützt es nicht.
* Es gibt einen Wochentakt für `pip-audit`, und die Wartungs- und Zeitlaufjobs hängen an einem Auslöser,
  der in `schedule` wirklich vorkommt (ein Vergleich mit dem falschen Cron-Text liesse den Job nie laufen).
* Dependabot deckt pip, npm und GitHub Actions ab.

Gegenprobe: in ci.yml einen Job auf `ubuntu-latest` stellen, oder den Cron des Zeitlaufs ändern, ohne die
`if:`-Bedingung nachzuziehen. Beides macht einen Test rot.
"""
import re
from pathlib import Path

import yaml
from django.conf import settings
from django.test import SimpleTestCase

WURZEL = Path(settings.BASE_DIR)


def _ci():
    return yaml.safe_load((WURZEL / '.github/workflows/ci.yml').read_text(encoding='utf-8'))


class CiKonfigurationTests(SimpleTestCase):

    def test_alle_jobs_laufen_auf_festem_runner(self):
        unfest = {name: job.get('runs-on') for name, job in _ci()['jobs'].items()
                  if job.get('runs-on') != 'ubuntu-24.04'}
        self.assertEqual(unfest, {}, '`ubuntu-latest` wandert mit (zuletzt auf 26.04, wo Playwright 1.56 nicht läuft): '
                                     'jeder Job auf einen festen Runner stellen.')

    def test_zeitgesteuerte_jobs_haengen_an_einem_vorhandenen_cron(self):
        ci = _ci()
        auslöser = ci.get('on') or ci.get(True)
        crons = {e['cron'] for e in auslöser['schedule']}
        for name in ('wartung', 'zeitlauf'):
            self.assertIn(name, ci['jobs'])
        bedingung = ci['jobs']['zeitlauf']['if']
        genannt = set(re.findall(r"github\.event\.schedule == '([^']+)'", bedingung))
        self.assertTrue(genannt, 'der Zeitlauf nennt keinen Cron')
        self.assertTrue(genannt <= crons, f'Cron der Bedingung ({genannt}) steht nicht in `schedule` ({crons}): '
                                          'der Job liefe nie')

    def test_pip_audit_laeuft_im_wochentakt_und_die_prs_laufen_ohne_wartung(self):
        ci = _ci()
        self.assertNotIn('if', ci['jobs']['pip-audit'], 'pip-audit muss auch im Zeitplan laufen')
        for name in ('lint', 'test', 'test-postgres', 'e2e'):
            self.assertIn("!= 'schedule'", ci['jobs'][name].get('if', ''),
                          f'{name} würde mit jedem Wartungstakt mitlaufen (Kosten, Rauschen)')

    def test_der_lik_waechter_wird_im_wartungslauf_scharf_gestellt(self):
        schritte = _ci()['jobs']['wartung']['steps']
        scharf = [s for s in schritte if (s.get('env') or {}).get('ZEIT_WAECHTER') == '1']
        self.assertEqual(len(scharf), 1)
        self.assertIn('test_lik_tabelle', scharf[0]['run'])

    def test_zeitlauf_szenarien_gibt_es_im_werkzeug(self):
        szenarien = _ci()['jobs']['zeitlauf']['strategy']['matrix']['szenario']
        quelle = (WURZEL / '_tools/zeitlauf_epoche.py').read_text(encoding='utf-8')
        for s in szenarien:
            self.assertIn(f"szenario == '{s}'", quelle, f'Szenario {s} kennt _tools/zeitlauf_epoche.py nicht')

    def test_dependabot_deckt_alle_oekosysteme(self):
        d = yaml.safe_load((WURZEL / '.github/dependabot.yml').read_text(encoding='utf-8'))
        self.assertEqual({u['package-ecosystem'] for u in d['updates']}, {'pip', 'npm', 'github-actions'})
        for u in d['updates']:
            self.assertEqual(u['schedule']['interval'], 'weekly')
        pip = next(u for u in d['updates'] if u['package-ecosystem'] == 'pip')
        self.assertTrue(any(i['dependency-name'] == 'django' for i in pip['ignore']),
                        'Django bleibt auf 5.2 (LTS): kein stiller Sprung auf eine neue Reihe')
