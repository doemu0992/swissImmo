"""Ordnung der Migrationen: ein Strang je App, keine doppelten Nummern, sprechende Namen.

WARUM
Mehrere Arbeitszweige legen parallel Migrationen an. Zwei Dateien `0057_…` in derselben App ergeben
zwei Enden im Graphen; `migrate` bricht dann mit «Conflicting migrations» ab, aber erst dort, wo es
jemand zum ersten Mal ausführt (Produktion, frische CI-Datenbank). Und eine Migration, die Django
selbst benannt hat (`auto_20261028_1412`), sagt dem Leser nach einem Jahr nichts mehr.

`makemigrations --check` (CI) fängt fehlende Migrationen, aber weder doppelte Nummern noch den Namen.

DIE REGELN
1. Jede App hat genau ein Ende im Migrationsgraphen (`detect_conflicts`).
2. Die Nummer einer Migration kommt in ihrer App nur einmal vor. Ausnahme: die unten benannten Altlasten,
   die ein Zusammenführen überstanden haben. Die Liste wird nie länger.
3. Der Name ist `NNNN_kleinbuchstaben_mit_unterstrich`; `auto_…` und `…_auto` sind nicht erlaubt
   (`makemigrations --name <sprechend>`).

Gegenprobe: eine Datei `core/migrations/0001_doppelt.py` anlegen (Regel 2), eine zweite Wurzel ohne
Abhängigkeit (Regel 1) oder `0999_auto_20261028_1412.py` (Regel 3), und der Test wird rot.
"""
import re
from collections import defaultdict
from pathlib import Path

from django.apps import apps
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase

#: Bekannte doppelte Nummern aus der Zeit vor diesem Wächter: (App, Nummer). Nur streichen, nie ergänzen.
ALTLASTEN = {('finance', '0006')}

NAME = re.compile(r'^\d{4}_[a-z0-9_]+$')
UNSPRECHEND = re.compile(r'(^\d{4}_auto_|_auto$|_auto_\d{8})')


def _migrationsdateien():
    """{App-Label: [Dateiname ohne .py, …]} aus den Ordnern der eigenen Apps."""
    erg = defaultdict(list)
    for konfig in apps.get_app_configs():
        ordner = Path(konfig.path) / 'migrations'
        if ordner.is_dir() and 'site-packages' not in str(ordner) and 'dist-packages' not in str(ordner):
            for datei in sorted(ordner.glob('*.py')):
                if datei.name != '__init__.py':
                    erg[konfig.label].append(datei.stem)
    return erg


class MigrationenOrdnungTests(SimpleTestCase):

    def test_jede_app_hat_genau_ein_ende(self):
        konflikte = MigrationLoader(None, ignore_no_migrations=True).detect_conflicts()
        self.assertEqual(konflikte, {}, 'Mehrere Enden im Migrationsgraphen (zwei Zweige haben dieselbe Nummer '
                                        'vergeben?): Eine Migration umnummerieren oder mit '
                                        '`makemigrations --merge` zusammenführen.')

    def test_keine_doppelten_nummern(self):
        doppelt = []
        for app, namen in _migrationsdateien().items():
            nummern = defaultdict(list)
            for n in namen:
                nummern[n[:4]].append(n)
            doppelt += [(app, nr, namen_) for nr, namen_ in nummern.items()
                        if len(namen_) > 1 and (app, nr) not in ALTLASTEN]
        self.assertEqual(doppelt, [], 'Nummer in einer App doppelt vergeben: eine der Migrationen umnummerieren '
                                      '(und `dependencies` der Folgenden nachführen).')

    def test_die_altlasten_gibt_es_noch(self):
        """Ratsche: Eine Altlast, die keine mehr ist, wird gestrichen, sonst gäbe sie Platz für neue."""
        vorhanden = {(app, n[:4]) for app, namen in _migrationsdateien().items()
                     for n in namen if sum(m[:4] == n[:4] for m in namen) > 1}
        self.assertEqual(ALTLASTEN - vorhanden, set())

    def test_namen_sind_sprechend(self):
        schlecht = [(app, n) for app, namen in _migrationsdateien().items() for n in namen
                    if not NAME.match(n) or UNSPRECHEND.search(n)]
        self.assertEqual(schlecht, [], 'Migrationsname unzulässig: `makemigrations <app> --name <sprechend>`.')

    def test_die_regeln_erkennen_ihre_faelle(self):
        """Selbstprüfung der Muster, damit ein Wächter, der nichts findet, kein blinder ist."""
        self.assertTrue(UNSPRECHEND.search('0057_auto_20261028_1412'))
        self.assertTrue(UNSPRECHEND.search('0057_auto'))
        self.assertFalse(UNSPRECHEND.search('0057_vier_augen_zahlungsfreigabe'))
        self.assertFalse(NAME.match('0057_Gross'))
        self.assertFalse(NAME.match('57_zu_kurz'))
