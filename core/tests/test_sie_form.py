"""Anrede «Sie» (UI-Zielbild, Entscheidung vom 20.11.2026): Texte der Oberfläche siezen.

Die Oberfläche war gemischt: Mal «du kannst», mal «Erfasse die IBAN» (Befehlsform), mal «Sie». Jetzt gilt überall «Sie».
Der Wächter durchsucht die deutschen Texte der Anwendung (Vorlagen `fw/`, Ansichten, Dienste, Hilfetexte) nach
Du-Pronomen und nach Befehlsformen am Satzanfang. Kommentare zählen nicht.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)
ORTE = ['core/templates/fw', 'core/views/fw', 'core/services', 'core/hilfe.py', 'faelle', 'finance/services', 'portfolio', 'rentals']
PRONOMEN = re.compile(r"\b(du|dich|dir|dein|deine|deinen|deinem|deiner|deines)\b|\bDu\b")
BEFEHL = re.compile(r"(?:^|['\"«>]|[.:;!?—] )(?:Bitte )?(Wähle|Erfasse|Lege|Setze|Beende|Archiviere|Lade|Gib|Klicke|Importiere|Versende|Sende|Passe|Starte|Trage|Prüfe)\b")
#: Stellen, an denen das Wort etwas anderes ist (Schlüsselwort, Fremdsprache, Beispiel im Kommentar)
AUSNAHMEN = ('formular_fill.py', 'fristen.py', 'datenschutz/_text_fr', 'tests', 'migrations')


def _dateien():
    for ort in ORTE:
        p = WURZEL / ort
        for f in ([p] if p.is_file() else sorted(p.rglob('*'))):
            if f.suffix in ('.py', '.html', '.txt') and not any(a in str(f) for a in AUSNAHMEN):
                yield f


def _ohne_kommentar(zeile):
    s = zeile.strip()
    return None if s.startswith('#') or s.startswith('{#') or s.startswith('//') else zeile


class SieFormTests(SimpleTestCase):
    def _treffer(self, muster):
        out = []
        for f in _dateien():
            in_kommentar = False
            for n, zeile in enumerate(f.read_text(encoding='utf-8').splitlines(), 1):
                if '{% comment' in zeile:
                    in_kommentar = True
                if in_kommentar:
                    if '{% endcomment' in zeile:
                        in_kommentar = False
                    continue
                z = _ohne_kommentar(zeile)
                if z and muster.search(z):
                    out.append(f'{f.relative_to(WURZEL)}:{n}: {zeile.strip()[:90]}')
        return out

    def test_keine_du_pronomen(self):
        self.assertEqual(self._treffer(PRONOMEN), [], 'Du-Form in einem Text der Oberfläche: «Sie» verwenden')

    def test_keine_befehlsform_am_satzanfang(self):
        self.assertEqual(self._treffer(BEFEHL), [], 'Befehlsform in der Du-Anrede: «Erfassen Sie …» statt «Erfasse …»')

    def test_gegenprobe_die_muster_erkennen_du_formen(self):
        self.assertTrue(PRONOMEN.search('Hier kannst du das ändern.'))
        self.assertTrue(BEFEHL.search("_('Erfasse die IBAN.')"))
        self.assertFalse(BEFEHL.search("_('Erfassen Sie die IBAN.')"))
