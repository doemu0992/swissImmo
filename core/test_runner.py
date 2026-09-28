"""Testläufer, der jeden Test in einer eigenen Kopie des Kontexts ausführt.

WARUM ES DEN BRAUCHT
--------------------
Seit Etappe 4.3 lebt die aktive Organisation in einer `contextvars.ContextVar`.
In der Anwendung setzt die Middleware sie je Anfrage und räumt sie danach ab.
Im Test gibt es keine Middleware — wer den Kontext dort setzt (und ab Etappe
6.2 muss er gesetzt sein, weil `Model.objects` sonst wirft), setzt ihn für den
ganzen Prozess.

Damit entstünde die unangenehmste Sorte Test: einer, der grün ist, weil ein
*anderer* Test vorher etwas gesetzt hat, und rot, sobald jemand die Reihenfolge
ändert oder ihn einzeln laufen lässt. Ein Testsatz, dessen Ergebnis von der
Reihenfolge abhängt, sagt über den Code nichts mehr aus.

WIE
---
`contextvars.copy_context().run(...)` führt eine Funktion in einer **Kopie** des
aktuellen Kontexts aus. Alles, was darin gesetzt wird, ist danach wieder weg —
ohne dass dieser Läufer wissen muss, welche Variablen es überhaupt gibt. Genau
dafür sind ContextVars gemacht; die Alternative (in jedem `tearDown` von Hand
aufräumen) wäre eine Liste, die irgendwann unvollständig ist.

Der Eingriff sitzt an `SimpleTestCase.run`, also an genau einer Stelle, und er
ändert am Testergebnis nichts — er begrenzt nur die Lebensdauer der
Kontextvariablen auf den einzelnen Test.
"""
import contextvars
import os
import shutil
import tempfile

from django.test import SimpleTestCase, override_settings
from django.test.runner import DiscoverRunner, ParallelTestSuite

#: Übergibt den MEDIA-Ordner des Laufs an die Parallelprozesse — über die
#: Umgebung, weil sie mit `fork` wie mit `spawn` vererbt wird.
_MEDIEN_UMGEBUNG = 'SWISSIMMO_TESTLAUF_MEDIA'

#: Merker, damit ein zweiter Aufruf nicht doppelt umhüllt.
_UMHUELLT = '_mandanten_kontext_umhuellt'


def kontext_je_test_aktivieren():
    """Hüllt `SimpleTestCase.run` in eine Kontext-Kopie. Idempotent."""
    if getattr(SimpleTestCase, _UMHUELLT, False):
        return

    original = SimpleTestCase.run

    def run(self, result=None):
        return contextvars.copy_context().run(original, self, result)

    SimpleTestCase.run = run
    setattr(SimpleTestCase, _UMHUELLT, True)


def _init_worker_mit_medien(counter, *args, **kwargs):
    """Djangos Worker-Start, plus ein eigener MEDIA-Unterordner je Prozess.

    Jeder Parallelprozess hat eine eigene Test-Datenbank, in der die erste
    Organisation `pk=1` heisst. Teilen sich die Prozesse einen MEDIA-Ordner,
    kollidieren die Pfade `organisation/1/…` — ein Prozess löscht die Datei,
    die ein anderer gerade prüft (so gesehen an
    `MediaSchutzTests.test_anonymer_zugriff_auf_sensible_datei_404`).
    """
    from django.test import runner as django_runner
    django_runner._init_worker(counter, *args, **kwargs)
    basis = os.environ.get(_MEDIEN_UMGEBUNG) or tempfile.mkdtemp(prefix='swissimmo-tests-media-')
    wurzel = os.path.join(basis, f'prozess-{django_runner._worker_id}')
    os.makedirs(wurzel, exist_ok=True)
    # Nie deaktiviert: Das Override lebt so lange wie der Prozess.
    override_settings(MEDIA_ROOT=wurzel).enable()


class MandantenParallelSuite(ParallelTestSuite):
    init_worker = _init_worker_mit_medien


class MandantenTestRunner(DiscoverRunner):
    """Djangos Standardläufer, plus Kontext-Kopie je Test und eigener MEDIA_ROOT.

    EIGENER MEDIA_ROOT (seit 28.09.2026)
    Tests, die Dateien hochladen oder PDFs ablegen, schrieben in den echten
    `media/`-Ordner des Projekts — nach einem Lauf lagen dort Hunderte
    Testdateien zwischen den echten Uploads, und `test_medien_isolation`
    löschte per `rmtree` sogar echte Ordner. Der Läufer lenkt `MEDIA_ROOT`
    für den ganzen Lauf in einen temporären Ordner um; ein Test, der das
    vergisst, kann damit nichts mehr anrichten. Tests mit eigenem
    `override_settings(MEDIA_ROOT=…)` sind davon unberührt. Unter
    `--parallel` bekommt jeder Prozess darin einen eigenen Unterordner
    (`MandantenParallelSuite`).
    """

    parallel_test_suite = MandantenParallelSuite

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        kontext_je_test_aktivieren()
        self._medien_wurzel = tempfile.mkdtemp(prefix='swissimmo-tests-media-')
        self._medien_override = override_settings(MEDIA_ROOT=self._medien_wurzel)
        self._medien_override.enable()
        os.environ[_MEDIEN_UMGEBUNG] = self._medien_wurzel

    def teardown_test_environment(self, **kwargs):
        override = getattr(self, '_medien_override', None)
        if override is not None:
            override.disable()
            os.environ.pop(_MEDIEN_UMGEBUNG, None)
            shutil.rmtree(self._medien_wurzel, ignore_errors=True)
        super().teardown_test_environment(**kwargs)
