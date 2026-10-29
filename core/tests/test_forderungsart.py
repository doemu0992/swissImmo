"""Wächter: Jede Stelle, die eine Debitorenrechnung anlegt, nennt die Art der Forderung (Audit MIET-02).

Art. 257d OR kennt nur «fällige Mietzinse oder Nebenkosten». `DebitorenRechnung.forderungsart` trennt sie von allem
anderen (Weiterverrechnung, Selbstbehalt, Schlussabrechnung, Schadenersatz, Betreibungskosten, Mahngebühr, Zins).
Der Vorgabewert ist `'miete'`, damit bestehende Aufrufer und Tests nicht brechen — das ist die UNSICHERE Seite: Eine
neue Stelle, die vergisst, `forderungsart='sonstige'` zu setzen, würde in die Fristansetzung mit Kündigungsandrohung
geraten. Dieser Wächter verlangt darum die ausdrückliche Angabe an jeder Anlagestelle im Produktivcode.

Gegenprobe (28.10.2026): In `core/services/versicherungsfall.py` die Angabe `forderungsart='sonstige'` entfernt ->
dieser Test rot, mit Dateiname und Zeile; wieder eingefügt -> grün.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)

#: Aufrufformen, die eine Forderung anlegen.
ANLAGE = re.compile(r'DebitorenRechnung(?:\.objects)?\.(?:create|get_or_create|update_or_create)\(|DebitorenRechnung\(')

#: Ausgeschlossene Pfade: Tests, Migrationen, Hilfsskripte ohne Produktivbetrieb.
AUSGESCHLOSSEN = ('migrations', 'tests', 'node_modules', 'staticfiles', '.claude', 'e2e', '_tools')


def _aufruf_text(quelle, start):
    """Der Text der Klammer, die bei `start` (hinter '(') beginnt — bis zur passenden schliessenden Klammer."""
    tiefe, i, in_str = 1, start, None
    while i < len(quelle) and tiefe:
        c = quelle[i]
        if in_str:
            if c == '\\':
                i += 1
            elif c == in_str:
                in_str = None
        elif c in '\'"':
            in_str = c
        elif c == '(':
            tiefe += 1
        elif c == ')':
            tiefe -= 1
        i += 1
    return quelle[start:i]


def _stellen():
    for pfad in sorted(WURZEL.rglob('*.py')):
        teile = pfad.relative_to(WURZEL).parts
        if any(t in AUSGESCHLOSSEN for t in teile) or pfad.name.startswith('test_') or pfad.name == 'tests_perf.py':
            continue
        quelle = pfad.read_text(encoding='utf-8')
        if 'DebitorenRechnung' not in quelle:
            continue
        for treffer in ANLAGE.finditer(quelle):
            # Die Klassendefinition `class DebitorenRechnung(` ist keine Anlage.
            zeile_anfang = quelle.rfind('\n', 0, treffer.start()) + 1
            if quelle[zeile_anfang:treffer.start()].strip().startswith('class'):
                continue
            text = _aufruf_text(quelle, treffer.end())
            yield pfad.relative_to(WURZEL), quelle.count('\n', 0, treffer.start()) + 1, text


class ForderungsartWaechterTests(SimpleTestCase):
    def test_jede_anlagestelle_nennt_die_forderungsart(self):
        gefunden = list(_stellen())
        self.assertGreaterEqual(len(gefunden), 9, 'Der Wächter findet die Anlagestellen nicht mehr (Muster prüfen).')
        fehlt = [f'{pfad}:{zeile}' for pfad, zeile, text in gefunden if 'forderungsart' not in text]
        self.assertEqual(fehlt, [], 'Diese Stellen legen eine Debitorenrechnung ohne Angabe der Forderungsart an '
                                   "(forderungsart='miete' oder 'sonstige'): " + ', '.join(fehlt))

    def test_die_art_ist_miete_oder_sonstige_und_die_bekannten_wege_sind_richtig(self):
        """Mietzins und Nebenkosten: Sollstellung und NK-Nachzahlung. Alles andere ist «sonstige»."""
        erwartet = {
            'core/services/automation.py': {'miete', 'sonstige'},      # Sollstellung / Mahngebühr und Zins
            'core/views/fw/nebenkosten.py': {'miete'},                 # NK-Abrechnung Nachzahlung
            'core/services/versicherungsfall.py': {'sonstige'},        # Selbstbehalt
            'core/services/betreibung.py': {'sonstige'},               # Betreibungskosten
            'core/services/nutzungsentschaedigung.py': {'sonstige'},   # nach Vertragsende
            'core/views/fw/mahnwesen.py': {'sonstige'},                # Mahngebühr
            'core/views/fw/kautionen.py': {'sonstige'},                # Schadenersatz (Kautionsversicherung)
            'core/views/fw/detailseiten.py': {'sonstige'},             # Schlussabrechnung
            'core/views/fw/listen.py': {'sonstige'},                   # freie Rechnung, Weiterverrechnung
        }
        gesehen = {}
        for pfad, _zeile, text in _stellen():
            m = re.search(r"forderungsart\s*=\s*['\"](\w+)['\"]", text)
            if m:
                gesehen.setdefault(str(pfad), set()).add(m.group(1))
        for datei, arten in erwartet.items():
            with self.subTest(datei=datei):
                self.assertEqual(gesehen.get(datei), arten)
