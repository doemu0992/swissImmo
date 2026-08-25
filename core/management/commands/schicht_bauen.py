"""Erzeugt die ausgelieferten CSS-Dateien aus `fw/_schicht.html`.

WARUM ES DIESEN SCHRITT GIBT

Die Komponentenschicht lag bis E2.22 als `<style>`-Block in jeder Seite:
61 KB bei JEDEM Aufruf, davon 24 KB Erklaertext. Kommentare in `/* */` werden
ausgeliefert — jedes Wort darin steht im Quelltext jeder Seite, auch auf den
oeffentlichen. (Zwei Sicherheitstests haben genau deshalb einmal angeschlagen.)

Jetzt gibt es drei Fassungen mit je einer Aufgabe:

  `core/templates/fw/_schicht.html`  QUELLE — hier wird geaendert. Die
                                     Begruendungen stehen bei den Regeln, wo
                                     sie hingehoeren.
  `static/css/schicht.src.css`       zum Lesen, mit Erklaerungen.
  `static/css/schicht.css`           ausgeliefert, ohne Kommentare.

Nach jeder Aenderung an der Quelle: `python manage.py schicht_bauen`.
`core/tests/test_schicht_gebaut.py` schlaegt an, wenn es vergessen wurde —
sonst zeigt die Anwendung eine alte Fassung, waehrend die Quelle die neue
behauptet.
"""
import pathlib
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

QUELLE = 'core/templates/fw/_schicht.html'
MIT = 'static/css/schicht.src.css'
OHNE = 'static/css/schicht.css'

KOPF_SRC = ('/* ERZEUGT AUS core/templates/fw/_schicht.html — nicht von Hand '
            'aendern.\n   Diese Fassung traegt die Erklaerungen; `schicht.css` '
            'daneben ist die\n   ausgelieferte ohne Kommentare. */\n')


def css_aus_quelle(text):
    """Den reinen CSS-Teil herausschneiden.

    Der Kopf ist ein Django-Kommentar (er verschwindet beim Rendern und darf
    deshalb Klassennamen nennen), darunter steht ein `<style>`-Block.
    """
    i = text.index('{% endcomment %}') + len('{% endcomment %}')
    rumpf = text[i:]
    a = rumpf.index('<style>') + len('<style>')
    b = rumpf.rindex('</style>')
    return rumpf[a:b]


def ohne_kommentare(css):
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return re.sub(r'\n\s*\n+', '\n', css).strip() + '\n'


class Command(BaseCommand):
    help = 'Erzeugt static/css/schicht.css und schicht.src.css aus der Vorlage.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--pruefen', action='store_true',
            help='Nur pruefen, ob die Dateien aktuell sind (schreibt nichts).')

    def handle(self, *args, **opt):
        wurzel = pathlib.Path(settings.BASE_DIR)
        quelle = wurzel / QUELLE
        if not quelle.exists():
            raise CommandError(f'{QUELLE} fehlt.')

        css = css_aus_quelle(quelle.read_text(encoding='utf-8'))
        soll_mit = KOPF_SRC + css
        soll_ohne = ohne_kommentare(css)

        if opt['pruefen']:
            abweichung = []
            for pfad, soll in ((MIT, soll_mit), (OHNE, soll_ohne)):
                p = wurzel / pfad
                if not p.exists() or p.read_text(encoding='utf-8') != soll:
                    abweichung.append(pfad)
            if abweichung:
                raise CommandError(
                    'Nicht aktuell: ' + ', '.join(abweichung)
                    + '\nBitte `python manage.py schicht_bauen` ausfuehren.')
            self.stdout.write('Die gebauten Dateien sind aktuell.')
            return

        (wurzel / MIT).write_text(soll_mit, encoding='utf-8')
        (wurzel / OHNE).write_text(soll_ohne, encoding='utf-8')
        self.stdout.write(
            f'Gebaut: {len(soll_mit)} Zeichen mit Erklaerungen, '
            f'{len(soll_ohne)} ausgeliefert '
            f'({len(soll_mit) - len(soll_ohne)} Zeichen gespart — je Aufruf).')
