"""Nur eine Seite darf sich als Arbeitsvorrat bezeichnen.

G2 — EIN ARBEITSVORRAT, NICHT ZWEI LISTEN

Das Konzept (`docs/KONZEPT-UI.md`, Abschnitt 2) legt fest: »Heute« und
»Fälle« sind dasselbe — eine Vorgangsliste mit vorgefilterten Ansichten. Die
Arbeitsteilung dazu steht ebenda: **Einzelne datierte Vorgänge** in den
Arbeitsvorrat, **Sammelposten** (»12 Rechnungen prüfen«) in die Inbox.

WAS DER BEFUND WAR

Das Finanz-Cockpit nannte sich im Untertitel »Ihr Arbeitskorb — was ist zu
tun, in der richtigen Reihenfolge«, die Abschnittsüberschrift »Arbeitskorb«,
und der Docstring der Ansicht »EIN Arbeitskorb statt 11 Menüs«.

Strukturell war nichts falsch: Die vier Einträge dort sind Sammelposten, und
`core/services/inbox.py` holt dieselben Aggregate auf »Heute«. Es gab also
keine Doppelung — aber eine **Behauptung**, die eine Doppelung nahelegte.

Und die ist nicht harmlos. Abschnitt 1 des Konzepts warnt genau davor:

    »Heute skaliert nicht. Eine ungefilterte globale Inbox ist bei 8
     Wohnungen eine Hilfe und bei 350 ein zweiter Posteingang, den man
     ebenfalls ignoriert.«

Wer eine zweite Seite »Arbeitskorb« nennt, lädt den nächsten Bearbeiter ein,
Vorgänge dorthin zu ziehen — und dann ist der zweite Posteingang da.

WAS DIESER TEST PRÜFT

Dass ausser dem Arbeitsvorrat keine Vorlage sich als Arbeitskorb oder
Arbeitsvorrat bezeichnet. Geprüft wird der sichtbare Text, nicht der Code:
Ein Kommentar darf den Begriff erklären, eine Überschrift nicht.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)

#: Wörter, die die Rolle des Arbeitsvorrats beanspruchen.
ANSPRUCH = ('Arbeitskorb', 'Arbeitsvorrat')

#: Die Seiten, die ihn tatsächlich haben. `dashboard.html` ist »Heute«;
#: `arbeitsvorrat.html` ist die Vorgangsliste mit ihren Ansichten.
ERLAUBT = {'fw/dashboard.html', 'fw/arbeitsvorrat.html', 'fw/pendenzen.html'}

KOMMENTAR = re.compile(
    r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}|\{#.*?#\}|<!--.*?-->|/\*.*?\*/',
    re.S)

#: Der Begriff darf VERWEISEND vorkommen — «der Arbeitsvorrat steht auf Heute»
#: ist genau die Aussage, die diese Regel durchsetzt. Verboten ist nur, ihn
#: als BEZEICHNUNG der eigenen Seite zu fuehren: in einer Ueberschrift oder
#: als «Ihr Arbeitskorb».
#:
#: Eine erste Fassung dieses Waechters unterschied das nicht und meldete den
#: Verweis, der die Regel erfuellt. Ein Waechter, der die richtige Loesung
#: als Verstoss meldet, wird beim ersten Mal weggeklickt.
BEZEICHNEND = re.compile(
    r'<h[1-6][^>]*>\s*(?:Ihr\s+)?(?:Arbeitskorb|Arbeitsvorrat)\s*</h[1-6]>'
    r'|>\s*Ihr\s+(?:Arbeitskorb|Arbeitsvorrat)\b', re.I)


class NurEinArbeitsvorratTest(SimpleTestCase):

    def _vorlagen(self):
        for p in sorted((WURZEL / 'core' / 'templates').rglob('*.html')):
            rel = p.relative_to(WURZEL / 'core' / 'templates').as_posix()
            if rel in ERLAUBT:
                continue
            yield rel, p

    def test_keine_zweite_seite_nennt_sich_arbeitskorb(self):
        funde = []
        for rel, p in self._vorlagen():
            # Erklärtext darf den Begriff nennen — dort steht ja gerade,
            # warum die Seite KEINER ist.
            sichtbar = KOMMENTAR.sub(' ', p.read_text(encoding='utf-8'))
            treffer = BEZEICHNEND.search(sichtbar)
            if treffer:
                funde.append(f'{rel}: {treffer.group(0).strip()[:60]}')

        self.assertEqual(
            funde, [],
            'Diese Vorlagen beanspruchen die Rolle des Arbeitsvorrats:\n  '
            + '\n  '.join(funde)
            + '\n\nG2 lässt genau einen zu. Wer eine zweite Seite so nennt, '
              'lädt den nächsten Bearbeiter ein, Vorgänge dorthin zu ziehen — '
              'und dann steht die Arbeit an zwei Orten.')

    def test_die_suche_findet_ueberhaupt_vorlagen(self):
        """Sonst prüfte der Test oben eine leere Menge."""
        anzahl = sum(1 for _ in self._vorlagen())
        self.assertGreater(anzahl, 50, f'Nur {anzahl} Vorlagen geprüft.')

    def test_die_gegenprobe(self):
        """Der Filter darf nicht alles wegwerfen.

        Erklärtext wird ausgeblendet — wenn dabei versehentlich der ganze
        Inhalt verschwände, wäre die Prüfung oben für immer grün.
        """
        beispiel = ('{% comment %}Arbeitskorb erklärt{% endcomment %}'
                    '<h2>Arbeitskorb</h2>')
        sichtbar = KOMMENTAR.sub(' ', beispiel)
        self.assertIn('<h2>Arbeitskorb</h2>', sichtbar,
                      'Der Filter wirft sichtbaren Text weg.')
        self.assertNotIn('erklärt', sichtbar,
                         'Der Filter lässt Kommentare stehen — dann meldet er '
                         'jede Erklärung als Verstoss.')
        # Und der Ausdruck muss die Bezeichnung von der Erwaehnung trennen.
        self.assertTrue(BEZEICHNEND.search('<h2>Arbeitskorb</h2>'),
                        'Eine Ueberschrift wird nicht erkannt.')
        self.assertIsNone(
            BEZEICHNEND.search('der Arbeitsvorrat steht auf Heute'),
            'Der VERWEIS auf den Arbeitsvorrat wird als Verstoss gemeldet — '
            'dabei ist er genau die Aussage, die diese Regel will.')

    def test_der_arbeitsvorrat_selbst_traegt_den_begriff(self):
        """Gegenprobe von der anderen Seite.

        Wäre der Begriff nirgends mehr zu finden, hätte der Test oben nichts
        mehr zu tun — und niemand merkte, dass die Bezeichnung ganz
        verschwunden ist.
        """
        treffer = []
        for name in ERLAUBT:
            p = WURZEL / 'core' / 'templates' / name
            if p.exists() and any(w in p.read_text(encoding='utf-8')
                                  for w in ANSPRUCH):
                treffer.append(name)
        self.assertTrue(
            treffer,
            f'Keine der Seiten {sorted(ERLAUBT)} nennt sich noch Arbeitsvorrat '
            f'— dann ist die Bezeichnung verlorengegangen.')
