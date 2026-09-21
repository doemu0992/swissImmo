"""Jede Ansicht ist zugeordnet — entweder frei oder hinter einer Abo-Stufe.

Schritt 2 aus `docs/PHASE-3-ENTITLEMENTS.md`.

WAS DIESER TEST VERHINDERT

Nicht, dass eine Sperre falsch ist — dafür ist er zu früh. Sondern, dass eine
Ansicht **gar nicht bedacht** wurde. Das ist der Fehler, der bei 326 URLs
unweigerlich passiert und den niemand bemerkt: Eine neue Seite entsteht, sie
kann etwas, was die Stufe eigentlich nicht enthält, und sie ist für alle
offen. Kein Testlauf meldet das, kein Kunde beschwert sich, und der Ertrag
fehlt still.

WIE DIE VORLAGE DAFÜR AUSSIEHT

Zwei Bauformen aus diesem Bestand, zusammengelegt:

- Der Registrylauf der Isolationstests (`core/tests/test_isolation.py`) geht
  über `get_resolver().reverse_dict` und fasst damit JEDE benannte URL an —
  datengetrieben, nicht abgetippt. Eine neue Ansicht ist automatisch dabei.
- Die `NOCH_HINTEN`-Ratsche aus `faelle/test_akten_neu.py`: eine Liste, die
  nur schrumpfen darf. Ein blosser Kommentar wäre nach zwei Etappen
  vergessen.

WAS HEUTE GILT

Alle 326 stehen auf der Freiliste, keine trägt ein Merkmal. Das ist der
ehrliche Ausgangszustand — Schritt 1 ist die Tabelle, Schritt 3 sind die
Sperren, und dazwischen steht ein Entscheid.
"""
import pathlib

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import get_resolver

from core.entitlements import MERKMALE, merkmal_der_ansicht

WURZEL = pathlib.Path(settings.BASE_DIR)
FREILISTE = WURZEL / 'core' / 'tests' / 'entitlement_freiliste.txt'


def _freiliste():
    zeilen = FREILISTE.read_text(encoding='utf-8').split('\n')
    return {z.strip() for z in zeilen
            if z.strip() and not z.lstrip().startswith('#')}


def _benannte_urls():
    """Name -> aufgeloeste Ansicht, fuer jede benannte URL der Registry."""
    aufloeser = get_resolver()
    aus = {}
    for name in aufloeser.reverse_dict:
        if not isinstance(name, str):
            continue
        aus[name] = _ansicht_zu(aufloeser, name)
    return aus


def _ansicht_zu(aufloeser, name):
    """Die Funktion hinter einem URL-Namen — oder `None`.

    Ueber `reverse()` und `resolve()` waere es ein Umweg ueber echte Pfade mit
    erfundenen Parametern. Der Weg ueber `_reverse_dict` ist direkt, aber
    liefert nicht fuer jeden Namen eine Funktion; wo nicht, gilt die Ansicht
    als nicht zugeordnet — und faellt damit auf die Freiliste zurueck, was
    der sichere Fall ist.
    """
    for muster in aufloeser.url_patterns:
        treffer = _suche(muster, name)
        if treffer is not None:
            return treffer
    return None


def _suche(muster, name):
    if getattr(muster, 'name', None) == name:
        return getattr(muster, 'callback', None)
    for unter in getattr(muster, 'url_patterns', ()):
        treffer = _suche(unter, name)
        if treffer is not None:
            return treffer
    return None


class AbdeckungTests(SimpleTestCase):

    def test_jede_benannte_url_ist_zugeordnet(self):
        """Frei oder gesperrt — aber nie unbedacht.

        Eine neue Ansicht fehlt auf der Freiliste und traegt kein Merkmal;
        dieser Test wird dann rot und verlangt die Entscheidung, statt sie
        stillschweigend zugunsten von «frei» zu faellen.
        """
        frei = _freiliste()
        offen = sorted(name for name, ansicht in _benannte_urls().items()
                       if name not in frei and merkmal_der_ansicht(ansicht) is None)
        self.assertEqual(
            offen, [],
            'Diese Ansichten sind weder frei noch einer Abo-Stufe zugeordnet:\n  '
            + '\n  '.join(offen)
            + '\n\nEntweder gehoeren sie in core/tests/entitlement_freiliste.txt '
              '(dann kostet die Funktion nichts) oder hinter ein Merkmal aus '
              'core/entitlements.py.')

    def test_die_freiliste_kennt_keine_toten_namen(self):
        """Sonst waechst sie still weiter, waehrend Ansichten verschwinden.

        Eine Ratsche, die alte Eintraege behaelt, sieht nach Abdeckung aus und
        ist keine: Beim naechsten Durchsehen weiss niemand mehr, welche Zeilen
        noch etwas bedeuten.
        """
        bekannt = set(_benannte_urls())
        tot = sorted(_freiliste() - bekannt)
        self.assertEqual(
            tot, [],
            'Diese Namen stehen auf der Freiliste, aber es gibt sie nicht '
            '(mehr):\n  ' + '\n  '.join(tot))

    def test_kein_name_ist_beides(self):
        """Die Richtung der Ratsche.

        Wer eine Ansicht hinter eine Stufe stellt, streicht sie aus der
        Freiliste. Bleibt sie stehen, waere unklar, was gilt — und der
        naechste Leser muesste raten.
        """
        frei = _freiliste()
        beides = sorted(name for name, ansicht in _benannte_urls().items()
                        if name in frei and merkmal_der_ansicht(ansicht) is not None)
        self.assertEqual(
            beides, [],
            'Diese Ansichten tragen ein Merkmal UND stehen auf der Freiliste:\n  '
            + '\n  '.join(beides))

    def test_heute_traegt_keine_ansicht_ein_merkmal(self):
        """Der Stand von Schritt 1, festgehalten.

        Wird dieser Test rot, hat jemand die erste Sperre eingezogen. Dann
        gehoert er GESTRICHEN, nicht angepasst — zusammen mit dem Entscheid
        im Ruecken, der Schritt 3 freigibt.
        """
        gesperrt = sorted(name for name, ansicht in _benannte_urls().items()
                          if merkmal_der_ansicht(ansicht) is not None)
        self.assertEqual(gesperrt, [])

    def test_der_sweep_sieht_ueberhaupt_etwas(self):
        """Belegt, dass oben nicht ueber eine leere Menge geprueft wurde.

        Ohne diese Zusicherung bestuenden die Tests auch, wenn `_benannte_urls`
        aus irgendeinem Grund leer zurueckkaeme — und meldeten Abdeckung, wo
        nichts angesehen wurde. Dieselbe Falle wie ein Isolationstest auf einem
        leeren Bestand.

        HIER STAND ZUERST `assertEqual(_freiliste(), set(bekannt))`, also
        Gleichheit statt Teilmenge. Das war heute richtig und als Waechter
        falsch: Sobald die erste Ansicht ein Merkmal traegt, verlaesst sie die
        Freiliste — und der Test waere rot geworden, obwohl genau das der
        vorgesehene Weg ist. Aufgefallen in der Gegenprobe, die den RICHTIGEN
        Weg durchspielte.

        Ein Waechter, der den vorgesehenen naechsten Schritt bestraft, wird
        beim ersten Mal umgangen statt verstanden.
        """
        bekannt = _benannte_urls()
        self.assertGreater(len(bekannt), 300,
                           'Die Registry liefert kaum URLs — dann misst dieser '
                           'Testsatz nichts.')
        self.assertTrue(
            _freiliste() <= set(bekannt),
            'Die Freiliste nennt Namen, die es nicht gibt — siehe den Test '
            'darueber, der sie einzeln aufzaehlt.')

    def test_die_merkmale_sind_noch_alle_unbenutzt(self):
        """Zusammenhang zu Schritt 1: Die Tabelle steht, sie wirkt nicht.

        Dass MERKMALE nicht leer ist, gehoert dazu — sonst liesse sich der
        Test oben auch dadurch erfuellen, dass es gar nichts zu vergeben gibt.
        """
        self.assertTrue(MERKMALE, 'Es gibt keine Merkmale — dann ist Schritt 1 weg.')
        vergeben = {merkmal_der_ansicht(a) for a in _benannte_urls().values()}
        self.assertEqual(vergeben - {None}, set())
