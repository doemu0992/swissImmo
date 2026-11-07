"""Roadmap Nr. 24 (Ratsche): Mail-HTML gehört in `templates/emails/`, nicht in Python-Strings.

Zählt `<html`/`<body` in Python-Dateien ausserhalb von Tests. Die Liste unten sind die Stellen, die noch
nicht umgezogen sind (heute nur noch die Wartungsseite, die keine Mail ist); sie wird nie länger. Wer eine Mail umzieht, trägt die Datei hier aus (oder senkt
die Zahl) — der Test verlangt es, damit der Fortschritt nicht verloren geht.
"""
import pathlib
import re
from django.test import SimpleTestCase

#: Datei -> Anzahl `<html`/`<body`-Vorkommen, die noch in Python stehen.
NOCH_NICHT_UMGEZOGEN = {
    'core/wartung.py': 2,              # Wartungsseite, keine Mail (bewusst eigenständig, wenn die DB fehlt)
}

MUSTER = re.compile(r'<html|<body')
AUSGENOMMEN = ('node_modules', '/tests/', 'migrations', '_tools', 'e2e')


def _zaehlen():
    gefunden = {}
    for pfad in pathlib.Path('.').rglob('*.py'):
        text_pfad = '/' + str(pfad)
        if any(a in text_pfad for a in AUSGENOMMEN) or pfad.name.startswith('test_'):
            continue
        n = len(MUSTER.findall(pfad.read_text(encoding='utf-8', errors='ignore')))
        if n:
            gefunden[str(pfad)] = n
    return gefunden


class MailHtmlNichtInPythonTests(SimpleTestCase):

    def test_keine_neue_stelle_und_keine_zunahme(self):
        gefunden = _zaehlen()
        zu_viel = {d: n for d, n in gefunden.items() if n > NOCH_NICHT_UMGEZOGEN.get(d, 0)}
        self.assertEqual(zu_viel, {}, 'Mail-HTML in Python: bitte als Vorlage unter core/templates/emails/ anlegen '
                                      '(Rahmen: rahmen_schlicht.html / rahmen_karte.html, Helfer: '
                                      'core.utils.email_service.mail_html).')

    def test_umgezogene_stellen_werden_aus_der_liste_genommen(self):
        gefunden = _zaehlen()
        zu_wenig = {d: (n, gefunden.get(d, 0)) for d, n in NOCH_NICHT_UMGEZOGEN.items() if gefunden.get(d, 0) < n}
        self.assertEqual(zu_wenig, {}, 'Diese Stellen sind umgezogen: Zahl senken oder Datei aus '
                                       'NOCH_NICHT_UMGEZOGEN streichen (Ratsche).')
