"""Flash-Meldungen (messages.success/error/…) stehen in der Sprache der
angemeldeten Person.

Bis 29.09.2026 waren alle Meldungen feste deutsche Literale — auch wer die
Oberfläche auf Französisch gestellt hatte, las «Adresse gespeichert.».
Meldungen gehen an die Person am Bildschirm, nie in ein Dokument; sie folgen
deshalb der Oberflächensprache (anders als Dokumente, siehe D11).

Bewusst NICHT übersetzt: Meldungen mit Gesetzesbezug (Art. … OR usw.) —
die bleiben bis zur juristischen Durchsicht Deutsch — und Meldungen, die nur
einen fertigen Text eines Dienstes weiterreichen.

Gegenprobe:
- Wächter: ein `gettext(` in einer der Dateien zurück auf das Literal —
  `test_keine_rohen_literale` wird rot.
- Wirkung: `gettext(` in core/views/fw/person.py (Notiz ohne Inhalt) zurück
  auf das Literal — `test_franzoesisch` wird rot.
"""
import ast
from pathlib import Path

from django.test import Client, SimpleTestCase, TestCase

from core.tests._helfer import _basis_objekte, _team_user

WURZEL = Path(__file__).resolve().parents[2]

#: Dateien, deren Meldungen ausgezeichnet sind (wächst je Tranche).
AUSGEZEICHNET = (
    'core/views/fw/profil.py',
    'core/views/fw/person.py',
    'core/views/fw/kautionen.py',
    'core/views/fw/schaeden.py',
    'core/views/fw/liegenschaft_crud.py',
    'core/views/fw/benutzer.py',
    'core/views/fw/abnahme.py',
    'core/views/fw/anlagen.py',
    'core/views/fw/nebenkosten.py',
    'core/views/fw/eigentuemer.py',
    'core/views/fw/eigentuemer_abrechnung.py',
    # Teil B
    'core/views/fw/buchhaltung.py',
    'core/views/fw/listen.py',
    'core/views/fw/kreditoren.py',
    'core/views/fw/bankabgleich.py',
    'core/views/fw/arbeit.py',
    'core/views/fw/mietprozess.py',
    'core/views/portal.py',
    'core/views/zweifaktor.py',
    'core/views/docuseal.py',
    'core/views/fw/vertragserstellung.py',
)

RECHT = ('Art.', ' OR', 'ZGB', 'DSG', 'SchKG')


def _rohe_meldungen(pfad):
    """Meldungen, deren Text ein deutsches Literal ohne gettext ist."""
    quelle = (WURZEL / pfad).read_text(encoding='utf-8')
    funde = []
    for n in ast.walk(ast.parse(quelle)):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in {'success', 'error', 'warning', 'info'}
                and isinstance(n.func.value, ast.Name) and n.func.value.id == 'messages'
                and len(n.args) >= 2):
            continue
        arg = n.args[1]
        texte = [x.value for x in ast.walk(arg) if isinstance(x, ast.Constant) and isinstance(x.value, str)]
        if any(isinstance(x, ast.Call) and getattr(x.func, 'id', '') == 'gettext' for x in ast.walk(arg)):
            continue
        text = ''.join(texte)
        if not isinstance(arg, (ast.Constant, ast.JoinedStr)):
            continue  # zusammengesetzte Ausdrücke prüft ein Mensch
        if sum(c.isalpha() for c in text) < 4 or any(r in text for r in RECHT):
            continue
        funde.append(f'{pfad}:{n.lineno} {text[:60]!r}')
    return funde


class MeldungenAusgezeichnetTests(SimpleTestCase):

    def test_keine_rohen_literale(self):
        funde = [f for p in AUSGEZEICHNET for f in _rohe_meldungen(p)]
        self.assertEqual(funde, [])


class MeldungFolgtDerSpracheTests(TestCase):

    def setUp(self):
        _lg, _e, self.m, _v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))

    def _notiz_ohne_inhalt(self, **kopf):
        return self.c.post('/neu/kommunikation/notiz/', {'mieter_id': self.m.id, 'inhalt': ''},
                           follow=True, **kopf)

    def test_franzoesisch(self):
        self.c.post('/i18n/setlang/', {'language': 'fr', 'next': '/neu/'})
        seite = self._notiz_ohne_inhalt()
        self.assertContains(seite, 'Merci de saisir un contenu / texte de note.')
        self.assertNotContains(seite, 'Bitte einen Inhalt/Notiztext erfassen.')

    def test_deutsch(self):
        seite = self._notiz_ohne_inhalt(HTTP_ACCEPT_LANGUAGE='de-CH')
        self.assertContains(seite, 'Bitte einen Inhalt/Notiztext erfassen.')

    def test_termin_ohne_titel_italienisch(self):
        # Teil B: Meldung aus core/views/fw/arbeit.py.
        self.c.post('/i18n/setlang/', {'language': 'it', 'next': '/neu/'})
        seite = self.c.post('/neu/termine/neu/', {'titel': '', 'beginn': ''}, follow=True)
        self.assertContains(seite, "Il titolo e l&#x27;inizio sono necessari.")
        self.assertNotContains(seite, 'Titel und Beginn sind nötig.')
