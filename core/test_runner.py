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

from django.test import SimpleTestCase
from django.test.runner import DiscoverRunner

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


class MandantenTestRunner(DiscoverRunner):
    """Djangos Standardläufer, plus Kontext-Kopie je Test."""

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        kontext_je_test_aktivieren()
