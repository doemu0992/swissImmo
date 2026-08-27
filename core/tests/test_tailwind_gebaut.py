"""Der Tailwind-Bau muss zu den Vorlagen passen.

DIE LÜCKE STAND SEIT E0.2 IM NACHBARTEST ANGESCHRIEBEN

`core/tests/test_schicht_gebaut.py` erklärt, warum die gebaute Schicht gegen
ihre Quelle geprüft wird — und nennt dabei ausdrücklich «dieselbe Lücke wie
beim Tailwind-Bau in E0.2». Für die Schicht wurde sie geschlossen, für
Tailwind nicht.

WAS DABEI PASSIERT

Tailwind baut nur die Klassen, die es beim Bau in den Vorlagen findet
(`tailwind.inhalt.js`). Wer eine Klasse ergänzt und `npm run css:alle`
vergisst, hat eine **richtige Vorlage und ein unvollständiges Stylesheet**:
Die Klasse steht im HTML, der Browser findet keine Regel dazu und tut
nichts. Kein Fehler, keine Meldung — der Abstand fehlt einfach.

Beim CDN fiel das nie auf, weil dort zur Laufzeit im Browser übersetzt wurde.
Seit E0.2 wird gebaut, und seither kann der Bau veralten.

GEFUNDEN IN E2.48, ENTSTANDEN IN E2.46

E2.46 hat die Zeiterfassung auf der Fallseite gebaut und dabei
`<td class="py-1.5 pl-3">` ergänzt (`fw/fall_detail.html`). `.pl-3` gab es im
gebauten `tailwind.css` nicht. Die Spalte stand seither ohne linken Einzug an
der Trennlinie — nachgewiesen, indem der Bau nachgeholt wurde: genau diese
eine Regel kam dazu.

WAS DIESER TEST PRÜFT UND WAS NICHT

Er ruft Tailwind NICHT auf — kein Node in der Testsammlung. Stattdessen sucht
er in denselben Dateien, die auch `tailwind.inhalt.js` nennt, nach einer
**engen, eindeutigen** Auswahl von Utility-Klassen (Abstände, Grössen,
Rasterspalten) und prüft, dass zu jeder eine Regel im gebauten Stylesheet
steht.

Die Auswahl ist bewusst klein. Sie muss eine **Teilmenge** dessen sein, was
Tailwinds eigener Scanner aus demselben Text zieht — sonst entstünden
Fehlalarme. Farb- und Zustandsklassen bleiben deshalb aussen vor: Sie
unterscheiden sich zwischen den zwei Bauten (Petrol-Palette innen,
Voreinstellung aussen), und dort läge die Grenze nicht mehr eindeutig.

Damit findet er nicht jede vergessene Klasse — aber jede vergessene aus der
häufigsten Gruppe, und das genügt, um einen veralteten Bau zu bemerken.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)

#: Dieselben Orte wie `tailwind.inhalt.js`. Läuft die Liste dort auseinander,
#: schlägt `test_die_orte_stimmen_mit_der_baukonfiguration_ueberein` an.
ORTE = (
    'core/templates/**/*.html',
    'templates/**/*.html',
    'core/**/*.py',
    'faelle/**/*.py',
    'finance/**/*.py',
    'portfolio/**/*.py',
    'rentals/**/*.py',
    'crm/**/*.py',
    'tickets/**/*.py',
    'mietprozess/**/*.py',
)

#: Das gebaute Stylesheet der Anwendung. Für die geprüfte Auswahl ist es eine
#: Obermenge des Aussen-Baus: Beide lesen dieselben Dateien, und Abstände und
#: Grössen hängen nicht an der Palette.
GEBAUT = 'static/css/tailwind.css'

_VARIANTE = (r'(?:(?:sm|md|lg|xl|2xl|hover|focus|focus-within|active|group-hover'
             r'|dark|first|last|odd|even|disabled|print):)*')
_KERN = (r'(?:[pm][trblxy]?-\d+(?:\.\d+)?'
         r'|gap(?:-[xy])?-\d+(?:\.\d+)?'
         r'|space-[xy]-\d+(?:\.\d+)?'
         r'|w-\d+(?:\.\d+)?|h-\d+(?:\.\d+)?'
         r'|grid-cols-\d+|col-span-\d+)')

#: Links darf KEIN Bindestrich stehen. Ohne diese Grenze findet `h-60` sich
#: mitten in `max-h-60` — sechs Fehlalarme in der ersten Fassung, alle
#: erfunden.
NUTZKLASSE = re.compile(
    r'''(?:^|[\s"'`])(''' + _VARIANTE + _KERN + r''')(?=$|[\s"'`])''', re.M)


def _selektor(klasse: str) -> str:
    """`md:py-1.5` → `.md\\:py-1\\.5` — so steht es im gebauten CSS."""
    return '.' + klasse.replace(':', r'\:').replace('.', r'\.')


def _benutzte_klassen():
    """Jede gefundene Utility-Klasse mit einer Fundstelle."""
    gefunden = {}
    for muster in ORTE:
        for p in WURZEL.glob(muster):
            if 'node_modules' in p.parts or not p.is_file():
                continue
            if 'tests' in p.parts or p.name.startswith('test_'):
                # Tailwind LIEST diese Dateien (`./core/**/*.py` in
                # tailwind.inhalt.js schliesst die Testsammlung ein) und baut
                # brav Regeln aus Beispielzeichenketten. Dieser Test wäre
                # sonst der erste Fall: Seine eigenen Beispiele — `h-60`,
                # `md:mt-2` — meldete er als fehlend, weil sie beim letzten
                # Bau noch nicht existierten.
                #
                # Weglassen ist unbedenklich: Die geprüfte Menge bleibt eine
                # Teilmenge dessen, was Tailwind zieht, und Testdateien
                # gestalten keine Oberfläche.
                #
                # Dass der Bau überhaupt Testdateien einliest, ist ein eigener
                # Punkt — er bläht das Stylesheet um Klassen auf, die nie
                # jemand sieht. Die Baukonfiguration bleibt hier unangetastet;
                # sie zu ändern gehört nicht in diese Etappe.
                continue
            try:
                text = p.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            for klasse in NUTZKLASSE.findall(text):
                gefunden.setdefault(klasse, p.relative_to(WURZEL).as_posix())
    return gefunden


def _steht_im_css(klasse: str, css: str) -> bool:
    """Der Selektor muss vorkommen — und zwar als ganzer.

    Nach dem Selektor folgt je nach Regel `{`, ein Komma, ein Kombinator oder
    ein Leerzeichen. `space-y-4` etwa erzeugt
    `.space-y-4 > :not([hidden]) ~ :not([hidden])`.
    """
    s = _selektor(klasse)
    return any(s + zeichen in css for zeichen in ('{', ',', ' ', '>', ':'))


class TailwindGebautTest(SimpleTestCase):

    def setUp(self):
        self.css = (WURZEL / GEBAUT).read_text(encoding='utf-8')

    def test_jede_benutzte_klasse_steht_im_gebauten_stylesheet(self):
        fehlend = sorted(
            f'{klasse} ({ort})'
            for klasse, ort in _benutzte_klassen().items()
            if not _steht_im_css(klasse, self.css)
        )
        self.assertEqual(
            fehlend, [],
            'Diese Klassen stehen in den Vorlagen, aber nicht im gebauten '
            'Stylesheet — der Bau ist veraltet. `npm run css:alle` ausführen: '
            f'{fehlend}')

    def test_die_suche_findet_ueberhaupt_klassen(self):
        """Gegenprobe: Ein Muster, das nie greift, ist immer grün."""
        self.assertGreater(len(_benutzte_klassen()), 150)

    def test_die_linke_grenze_haelt(self):
        """`max-h-60` ist nicht `h-60`.

        Ohne diese Grenze meldete die erste Fassung sechs Klassen als fehlend,
        die es gar nicht gibt — und hätte damit den echten Fund verdeckt.
        """
        self.assertEqual(NUTZKLASSE.findall('class="max-h-60 max-w-4"'), [])
        self.assertEqual(NUTZKLASSE.findall('class="h-60 w-4"'), ['h-60', 'w-4'])

    def test_der_selektor_wird_richtig_maskiert(self):
        self.assertEqual(_selektor('pl-3'), '.pl-3')
        self.assertEqual(_selektor('py-1.5'), r'.py-1\.5')
        self.assertEqual(_selektor('md:mt-2'), r'.md\:mt-2')

    def test_die_orte_stimmen_mit_der_baukonfiguration_ueberein(self):
        """Sucht dieser Test woanders als der Bau, prüft er die falschen Dateien."""
        quelle = (WURZEL / 'tailwind.inhalt.js').read_text(encoding='utf-8')
        aus_datei = re.findall(r"'(\./[^']+)'", quelle)
        self.assertEqual(
            [p.removeprefix('./') for p in aus_datei], list(ORTE),
            'ORTE und tailwind.inhalt.js sind auseinandergelaufen.')

    def test_die_baukonfiguration_ist_unversehrt(self):
        """`tailwind.inhalt.js` muss ladbar bleiben — sonst baut gar nichts.

        DER FALL, DER DIESE PRÜFUNG AUSGELÖST HAT

        E2.49 ergänzte einen Kommentar, der einen Glob ausschrieb. Ein Glob für
        «alle .py unterhalb» enthält die Zeichenfolge, die einen Blockkommentar
        SCHLIESST — der Kommentar endete mitten im Satz, der Rest wurde zu Code,
        und `npm run css:alle` brach mit `SyntaxError: Unexpected token (9:15)`
        ab. Das Stylesheet blieb auf dem alten Stand.

        Die anderen Prüfungen hier merkten davon nichts: Sie vergleichen
        Vorlagen mit dem GEBAUTEN CSS, und das war ja noch da — nur veraltet.
        Solange keine neue Klasse dazukam, blieb alles grün, während der Bau
        seit Tagen nicht mehr lief.

        WIE GEPRÜFT WIRD, OHNE NODE

        Kommentare entfernen; übrig bleiben muss genau `module.exports = [ … ];`
        mit Zeichenketten darin. Endet ein Kommentar zu früh, steht dort Prosa —
        und die fällt auf.
        """
        quelle = (WURZEL / 'tailwind.inhalt.js').read_text(encoding='utf-8')
        rest = re.sub(r'/\*.*?\*/', '', quelle, flags=re.S).strip()
        self.assertTrue(
            rest.startswith('module.exports'),
            'Nach dem Entfernen der Kommentare beginnt die Datei nicht mit '
            '`module.exports` — vermutlich hat ein Kommentar zu früh geendet '
            f'(ein ausgeschriebener Glob?). Rest beginnt mit: {rest[:70]!r}')
        # Nur Zuweisung, Klammern, Zeichenketten, Kommas, Leerraum.
        erlaubt = re.compile(
            r"""^module\.exports\s*=\s*\[\s*(?:'[^']*'\s*,\s*)*'[^']*'\s*,?\s*\]\s*;?$""")
        self.assertRegex(
            rest, erlaubt,
            'Zwischen den Kommentaren steht etwas anderes als die Musterliste. '
            f'Das lädt Node nicht mehr:\n{rest[:400]}')
