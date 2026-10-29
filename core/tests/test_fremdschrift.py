"""Keine Fremdschrift in eigenen Vorlagen und Stylesheets.

WARUM
Die Oberfläche hat eine Schrift (`--ds-font`, DM Sans, lokal ausgeliefert über `static/css/schriften.css`).
Die öffentlichen Formulare liefen mit einer zweiten (`IBM Plex Sans`, in einem Inline-`<style>` der Vorlage),
und niemand sah es, bis der Audit (Etappe 3) drei Fassungen desselben Formulars in drei Schriften fand.
`test_keine_fremdquellen` sperrt fremde Hosts, `test_farbklassen*` fremde Farben; diese Lücke blieb offen:
eine Schrift, die lokal liegt, aber nicht die der Anwendung ist.

DIE REGELN
1. Eine `font-family`-Angabe in einer eigenen Vorlage oder einem eigenen Stylesheet nennt nur: `var(--ds-*)`,
   `inherit`, DM Sans, Systemschriften und Monospace. Alles andere (IBM Plex, Inter, Roboto, …) ist Fremdschrift.
2. Altfälle stehen in `ALTFAELLE`, mit Datei. Die Liste wird nie länger; wer eine Datei bereinigt, streicht sie
   (ein Streichen ist nicht erzwungen, damit parallele Zweige nicht aneinander rot werden).
3. Gebaute Dateien (`tailwind.css`, `schicht.css`) und `schriften.css` (die `@font-face`-Definitionen selbst)
   sind ausgenommen.

Gegenprobe: in eine neue Vorlage `<style>body{font-family:'Roboto'}</style>` schreiben, und der Test wird rot.
"""
import os
import re
from pathlib import Path

from django.test import SimpleTestCase

WURZEL = Path(__file__).resolve().parents[2]
AUSSERHALB = {'.git', '.claude', 'node_modules', 'mockups', 'staticfiles', '__pycache__', 'docs', 'e2e'}
AUSGENOMMEN = {'static/css/tailwind.css', 'static/css/schicht.css', 'static/css/schicht.src.css',
               'static/css/schriften.css'}
ERLAUBT = re.compile(r'^(?:var\(--ds-[a-z-]+\)|inherit|initial|unset|"?dm sans"?|\'?dm sans\'?|ui-[a-z-]+|system-ui|'
                     r'-apple-system|blinkmacsystemfont|"?segoe ui"?|sans-serif|serif|monospace|menlo|consolas|'
                     r'sfmono-regular|helvetica|"?helvetica neue"?|arial|verdana|georgia|times|"?times new roman"?|'
                     r'courier|"?courier new"?|tahoma)$', re.I)
DEKLARATION = re.compile(r'font-family\s*:\s*([^;}"<]+)', re.I)

#: Dateien, die bei Einführung dieses Wächters (29.10.2026) noch Fremdschrift tragen. Nie ergänzen.
ALTFAELLE = {
    'core/templates/modern_base.html',
    'core/templates/core/public_ticket_form.html',
    'core/templates/core/dossier/base.html',
    'static/css/fairwalter_theme.css',
    'core/templates/fw/kommunikation.html',  # Druckfenster «Brief», Zeile 327: Inter ist nicht geladen
}


def fremdschriften(text):
    """Die Schriftnamen einer Textdatei, die nicht erlaubt sind."""
    funde = []
    for m in DEKLARATION.finditer(text):
        for name in m.group(1).split(','):
            name = name.strip().replace('!important', '').strip()
            if name and not ERLAUBT.match(name.strip('\'" ')) and not ERLAUBT.match(name):
                funde.append(name)
    return funde


def _quellen():
    for ordner, unterordner, dateien in os.walk(WURZEL):
        unterordner[:] = [d for d in unterordner if d not in AUSSERHALB]
        for name in dateien:
            if not name.endswith(('.html', '.css')):
                continue
            pfad = Path(ordner) / name
            rel = pfad.relative_to(WURZEL).as_posix()
            if rel in AUSGENOMMEN or ('static/css/' in rel and any(x in rel for x in ('fontawesome', 'bootstrap-icons'))):
                continue
            if rel.startswith('static/') and not rel.startswith('static/css/'):
                continue
            yield rel, pfad


class FremdschriftTests(SimpleTestCase):

    def test_keine_neue_fremdschrift(self):
        neu = {}
        for rel, pfad in _quellen():
            if rel in ALTFAELLE:
                continue
            text = re.sub(r'/\*.*?\*/|\{#.*?#\}|\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}|<!--.*?-->', '',
                          pfad.read_text(encoding='utf-8', errors='replace'), flags=re.S)
            funde = fremdschriften(text)
            if funde:
                neu[rel] = sorted(set(funde))
        self.assertEqual(neu, {}, 'Fremdschrift: Die Anwendung nutzt `var(--ds-font)` (DM Sans). Öffentliche '
                                  'Formulare nehmen die Standardoberfläche der fw-Schicht, keine eigene Schrift.')

    def test_die_altfaelle_gibt_es_wirklich(self):
        """Eine Datei, die nicht mehr existiert, gehört aus der Liste, sonst wächst totes Gewicht."""
        fehlend = sorted(rel for rel in ALTFAELLE if not (WURZEL / rel).exists())
        self.assertEqual(fehlend, [], 'Datei nicht mehr vorhanden: aus ALTFAELLE streichen.')

    def test_der_erkenner_unterscheidet(self):
        self.assertEqual(fremdschriften("body{font-family:'IBM Plex Sans', sans-serif}"), ["'IBM Plex Sans'"])
        self.assertEqual(fremdschriften('body { font-family: var(--ds-font); }'), [])
        self.assertEqual(fremdschriften("p{font-family:'DM Sans',ui-sans-serif,system-ui,sans-serif}"), [])
        self.assertEqual(fremdschriften('code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}'), [])
        self.assertEqual(fremdschriften('h1{font-family:Roboto}'), ['Roboto'])
