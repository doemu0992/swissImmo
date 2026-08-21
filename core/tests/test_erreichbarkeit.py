"""Jede gebaute Seite braucht einen Weg dorthin.

WARUM ES DIESEN WÄCHTER GIBT

Dreimal derselbe Fehler, zweimal davon in derselben Woche:

    Phase 4a    `faelle.regelwerk` — Rechenlogik, Modelle, Tests, alles grün.
                Kein Aufrufer. Vier Etappen lang unbemerkt.
    Phase 4b.5  `/neu/arbeit/`, `/neu/faelle/<id>/`, `/neu/laeufe/`,
                `/neu/zulauf/` gebaut und verlinkt — aber nicht in der
                Navigation.
    Phase 4b.8  `/neu/termine/`, `/neu/abwesenheiten/` ebenso.

Ein Test, der die View aufruft, sagt nichts darüber, ob ein Mensch sie je
findet. `self.client.get('/neu/termine/')` kennt die Adresse — der Benutzer
nicht.

WAS GEPRÜFT WIRD

Jede parameterlose `/neu/`-Adresse muss von irgendwo aus erreichbar sein:
aus der Navigation, aus einer Vorlage, oder aus einer Weiterleitung im
Programmcode. Adressen mit Parametern (`/neu/faelle/<pk>/`) sind
ausgenommen — sie werden aus einer Liste heraus verlinkt, und die Liste
prüft dieser Test bereits.

DIE AUSNAHMELISTE IST DIE EIGENTLICHE AUSSAGE

Was hier steht, ist absichtlich nicht verlinkt und trägt eine Begründung.
Sie wächst nur mit einem Grund. Eine Adresse ohne Weg und ohne Eintrag ist
ein Fehler.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import get_resolver

from core.navigation import nav_gruppen


#: Absichtlich ohne Weg in der Oberfläche — mit Grund.
OHNE_WEG = {
    # Endpunkte, die nur eine andere Seite bedient (Bruchstücke, Downloads,
    # POST-Ziele ohne eigene Darstellung).
    '/neu/regelwerk/protokoll/': 'Aus /neu/regelwerk/ verlinkt (Kopfzeile).',

    # ÜBERHOLT, ABER NOCH ERREICHBAR — vom Wächter beim ersten Lauf gefunden.
    # `fw_kreditoren_pain001` erzeugt eine Zahlungsdatei aus ALLEN freigegebenen
    # Kreditorenrechnungen, ohne Auswahl und ohne den Vorgang als Zahllauf
    # festzuhalten. `/neu/zahllauf/` leistet dasselbe mit Auswahl und
    # Buchführung und ist der Weg, den die Oberfläche anbietet.
    #
    # Die Adresse antwortet weiterhin. Wer sie kennt, erzeugt eine gültige
    # Zahlungsdatei, die in keinem Zahllauf steht — das ist der Grund, warum
    # der Eintrag hier nicht als «harmlos» steht, sondern als offener Punkt.
    # Entfernen ist eine Entscheidung des Betriebs, nicht des Umbaus.
    '/neu/kreditoren/pain001/': 'Überholt durch /neu/zahllauf/ — siehe Notiz, '
                                'noch nicht entfernt.',

    # Umleitung auf `/neu/`. Bewusst erreichbar gelassen, weil Lesezeichen und
    # aeltere Verweise darauf zeigen koennen — eine Adresse, die einmal
    # funktioniert hat, soll nicht ins Leere laufen.
    '/neu/arbeit/': 'Leitet auf /neu/ um (4b.13); aus der Navigation entfernt.',
}

#: Verzeichnisse, in denen nach Verweisen gesucht wird.
VORLAGEN = Path(settings.BASE_DIR) / 'core' / 'templates'
PROGRAMM = Path(settings.BASE_DIR)


def _parameterlose_neu_adressen():
    """Alle `/neu/`-Adressen ohne Platzhalter, aus dem URL-Verzeichnis."""
    adressen = set()
    for muster in get_resolver().url_patterns:
        _sammle(muster, '', adressen)
    return {a for a in adressen
            if a.startswith('/neu/') and '<' not in a and '(' not in a}


def _sammle(muster, praefix, hinein):
    pfad = praefix + str(getattr(muster, 'pattern', ''))
    if hasattr(muster, 'url_patterns'):
        for unter in muster.url_patterns:
            _sammle(unter, pfad, hinein)
    else:
        hinein.add('/' + pfad.lstrip('/'))


def _navigationsziele():
    ziele = set()
    for modus in ('einfach', 'profi'):
        for gruppe in nav_gruppen(modus):
            if gruppe['ziel']:
                ziele.add(gruppe['ziel'])
            for eintrag in gruppe['items']:
                ziele.add(eintrag['ziel'])
    return ziele


def _erwaehnt_in_dateien(adresse, wurzeln, endungen):
    """Kommt die Adresse irgendwo als Zeichenkette vor?

    Bewusst grob: Ein Verweis kann als `href`, in einem `redirect()`, in einer
    JavaScript-Zeile oder über `{% url %}` entstehen. Die Frage ist nicht, ob
    er syntaktisch ein Link ist, sondern ob die Adresse überhaupt irgendwo
    genannt wird. Wird sie es nicht, findet sie niemand.
    """
    nadel = adresse.rstrip('/')
    for wurzel in wurzeln:
        for endung in endungen:
            for datei in Path(wurzel).rglob(f'*{endung}'):
                if 'migrations' in datei.parts or '__pycache__' in datei.parts:
                    continue
                if datei.name.startswith('test_') or datei.parts[-2:-1] == ('tests',):
                    # Ein Test, der die Adresse aufruft, ist KEIN Weg dorthin.
                    # Genau diese Verwechslung soll der Wächter aufdecken.
                    continue
                if datei.name == 'urls.py':
                    continue      # das Verzeichnis selbst zählt nicht
                try:
                    text = datei.read_text(encoding='utf-8', errors='ignore')
                except OSError:
                    continue
                if nadel in text:
                    return True
    return False


class ErreichbarkeitTests(SimpleTestCase):

    def test_jede_neu_seite_ist_von_irgendwo_erreichbar(self):
        adressen = _parameterlose_neu_adressen()
        self.assertGreater(len(adressen), 50,
                           'Die Adressen wurden nicht gefunden — der Sammler ist kaputt, '
                           'nicht die Anwendung.')
        navigation = _navigationsziele()
        verwaist = []
        for adresse in sorted(adressen):
            if adresse in OHNE_WEG or adresse in navigation:
                continue
            if _erwaehnt_in_dateien(adresse, [VORLAGEN], ['.html']):
                continue
            if _erwaehnt_in_dateien(adresse, [PROGRAMM / 'core' / 'views'], ['.py']):
                continue
            verwaist.append(adresse)
        self.assertEqual(
            verwaist, [],
            'Diese Seiten sind gebaut, aber von nirgendwo erreichbar. Entweder '
            'in die Navigation aufnehmen, von einer Seite aus verlinken, oder '
            'mit Begruendung in OHNE_WEG eintragen:\n  '
            + '\n  '.join(verwaist))

    def test_die_neuen_seiten_stehen_in_der_navigation(self):
        """Die Seiten aus 4b.5 bis 4b.10 ausdruecklich, nicht nur pauschal.

        Der Test darueber liesse einen Querverweis aus einer anderen Vorlage
        genuegen — und genau das war der Zustand, in dem diese Seiten monatelang
        waren: verlinkt, aber nur von sich gegenseitig. Diese Liste verlangt
        einen Eintrag in der Navigation.
        """
        navigation = _navigationsziele()
        # `/neu/arbeit/` steht seit 4b.13 NICHT mehr hier: Die Ansichten sind
        # auf die Startseite gewandert, die Adresse leitet nur noch dorthin um.
        # Ein Navigationseintrag neben «Heute», der auf dieselbe Seite fuehrt,
        # waere kein Angebot, sondern eine Frage an den Benutzer.
        for adresse in ('/neu/', '/neu/zulauf/', '/neu/termine/',
                        '/neu/abwesenheiten/', '/neu/laeufe/', '/neu/regelwerk/'):
            self.assertIn(adresse, navigation,
                          f'{adresse} steht in keiner Navigationsgruppe.')

    def test_die_ausnahmeliste_ist_nicht_veraltet(self):
        """Ein Eintrag in OHNE_WEG, den es nicht mehr gibt, ist eine Lüge.

        Ohne diese Prüfung wächst die Liste zum Friedhof: Wer eine Adresse
        umbenennt, laesst den alten Eintrag stehen, und die Ausnahme deckt
        stillschweigend die neue, echte Luecke mit ab.
        """
        adressen = _parameterlose_neu_adressen()
        tot = sorted(a for a in OHNE_WEG if a not in adressen)
        self.assertEqual(tot, [],
                         'Diese Ausnahmen zeigen auf Adressen, die es nicht '
                         f'(mehr) gibt: {tot}')
