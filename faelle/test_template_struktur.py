"""Die umgestellten Aktenseiten muessen strukturell heil sein.

WARUM

Beim Umbau des Aktenkopfs am 19.08.2026 blieb ein `</div>` aus: `fw-akte-oben`
wurde nie geschlossen, und die Kennzahlenleiste sass dadurch **innerhalb** des
Kopfblocks statt darunter. Django rendert das anstandslos, der Browser repariert
es nach eigenem Gutduenken, und kein einziger der damals 205 Tests merkte es.

Ein blosses Zaehlen von `<div>` gegen `</div>` findet nur die Anzahl, nicht die
Verschachtelung. Deshalb laeuft hier ein echter Parser darueber.
"""
import pathlib
import re
from html.parser import HTMLParser

from django.test import TestCase

from faelle.test_reiter_panels import TEMPLATES, UMGESTELLT, WURZEL

#: Tags, die ohne schliessendes Gegenstueck vorkommen duerfen.
LEER = {'br', 'img', 'input', 'hr', 'meta', 'link', 'i', 'source', 'path'}


class _Pruefer(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stapel = []
        self.fehler = []

    def handle_starttag(self, tag, attrs):
        if tag not in LEER:
            self.stapel.append(tag)

    def handle_endtag(self, tag):
        if tag in LEER:
            return
        if self.stapel and self.stapel[-1] == tag:
            self.stapel.pop()
        elif tag in self.stapel:
            i = self.stapel.index(tag)
            self.fehler.append(
                f'</{tag}> schliesst uebersprungene Tags: {self.stapel[i + 1:]}')
            del self.stapel[i:]
        else:
            self.fehler.append(f'</{tag}> ohne oeffnendes Tag')


def pruefen(pfad):
    roh = (WURZEL / pfad).read_text(encoding='utf-8')
    # ZUERST die `{% comment %}`-BLOECKE mitsamt Inhalt entfernen, erst danach
    # die einzelnen Template-Tags.
    #
    # WARUM DIESE REIHENFOLGE: Die frühere Fassung entfernte nur die Tags und
    # liess den Text dazwischen stehen. In einem Kommentar steht aber Prosa
    # ueber HTML — «die Klasse sm:col-span-4 auf dem <label> selbst». Der
    # Parser las dieses `<label>` als echtes Tag, fand kein schliessendes und
    # meldete vier Folgefehler in einer Datei, die in Ordnung war.
    #
    # Es ist das dritte Mal, dass eine Pruefung ihre eigene Erklaerung fuer
    # eine Tatsache haelt (vorher: `test_gestapelte_tabellen` und der
    # Favicon-Test). Deshalb steht es hier ausgeschrieben.
    rein = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '', roh, flags=re.S)
    rein = re.sub(r'\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}', '', rein, flags=re.S)
    p = _Pruefer()
    p.feed(rein)
    return p.stapel, p.fehler


class StrukturTests(TestCase):
    def test_umgestellte_seiten_sind_ausbalanciert(self):
        for typ in sorted(UMGESTELLT):
            pfad = TEMPLATES[typ][0]
            offen, fehler = pruefen(pfad)
            with self.subTest(typ=typ):
                self.assertEqual(
                    offen, [],
                    f'{pfad}: nie geschlossen — {", ".join(offen)}')
                self.assertEqual(
                    fehler, [],
                    f'{pfad}: falsch verschachtelt — {"; ".join(fehler[:3])}')

    def test_prosa_im_kommentar_wird_nicht_als_html_gelesen(self):
        """Gegenprobe zur Reihenfolge in `pruefen`.

        Ohne das Entfernen der Kommentar-BLOECKE meldet der Parser hier ein
        offenes `<label>` — in einer Datei, die einwandfrei ist.
        """
        import tempfile
        inhalt = ('<div>{% comment %} die Klasse auf dem <label> selbst '
                  '{% endcomment %}<p>Text</p></div>')
        with tempfile.NamedTemporaryFile('w', suffix='.html', dir=WURZEL,
                                         delete=False, encoding='utf-8') as f:
            f.write(inhalt)
            name = pathlib.Path(f.name).name
        try:
            offen, fehler = pruefen(name)
            self.assertEqual((offen, fehler), ([], []))
        finally:
            (WURZEL / name).unlink()

    def test_der_pruefer_erkennt_ein_fehlendes_tag(self):
        """Gegenprobe. Ein Pruefer, der nie anschlaegt, besteht jede Datei."""
        p = _Pruefer()
        p.feed('<div><span>Text</div>')
        self.assertTrue(p.stapel or p.fehler)


class KommentarTests(TestCase):
    """`{# … #}` ist in Django **einzeilig**. Mehrzeilig wird es zu Text.

    WARUM

    Djangos Lexer benutzt `({%.*?%}|{{.*?}}|{#.*?#})` — **ohne** `re.DOTALL`.
    Ein `{# … #}`, das eine Zeilengrenze ueberschreitet, wird deshalb gar nicht
    als Kommentar erkannt und landet woertlich auf der Seite.

    Am 19.08.2026 stand deswegen ein voller Absatz Entwicklerkommentar mitten
    in der Vertragsakte, im Fliesstext zwischen Zustands-Chip und
    Statusumschalter — auf der Produktivseite, fuer jeden Nutzer sichtbar.
    Aufgefallen ist es einem Menschen im Browser, nicht der Suite: 1616 Tests
    waren gruen. Sie fragten nach Panel-IDs, Tokens und Verschachtelung, nie
    danach, ob Text auf der Seite steht, der dort nicht hingehoert.

    Zwei weitere Bloecke gleicher Art lagen schon laenger im Bestand
    (`public_datenschutz.html`, `base.html`) und waren nie bemerkt worden.
    """

    #: Alle Vorlagen, nicht nur die umgestellten: Der Fehler ist nicht an den
    #: Aktenumbau gebunden, und zwei der drei Altfaelle standen ausserhalb.
    def test_keine_mehrzeiligen_rautenkommentare(self):
        import re
        gefunden = []
        for pfad in sorted(WURZEL.rglob('*.html')):
            for nr, zeile in enumerate(pfad.read_text(encoding='utf-8').split('\n'), 1):
                for treffer in re.finditer(r'\{#', zeile):
                    if '#}' not in zeile[treffer.start():]:
                        gefunden.append(f'{pfad}:{nr}')
        self.assertEqual(
            gefunden, [],
            'Diese `{# … #}` gehen ueber mehrere Zeilen und erscheinen damit '
            'als Text auf der Seite. Fuer mehrzeilige Kommentare '
            '`{% comment %} … {% endcomment %}` verwenden:\n  '
            + '\n  '.join(gefunden))

    def test_die_vertragsakte_zeigt_keine_kommentarzeichen(self):
        """Gegenprobe am fertigen HTML.

        Die Pruefung darueber liest Vorlagen. Diese hier ruft die Seite auf —
        sie faellt auch dann um, wenn der Text ueber einen anderen Weg
        durchschlaegt, etwa aus einem eingebundenen Baustein.
        """
        from django.test import Client

        from core.tenancy import organisation_kontext as mandant
        from core.tests._isolation import MandantenFixture
        a = MandantenFixture('K', '8000', 'Zürich')
        c = Client()
        c.force_login(a.benutzer)
        with mandant(a.organisation):
            antwort = c.get(f'/neu/vertraege/{a.vertrag.pk}/')
        self.assertEqual(antwort.status_code, 200)
        html = antwort.content.decode()
        for zeichen in ('{#', '#}', '{% comment %}', '{% endcomment %}'):
            with self.subTest(zeichen=zeichen):
                self.assertNotIn(
                    zeichen, html,
                    f'{zeichen!r} steht im ausgelieferten HTML — ein '
                    f'Kommentar wurde nicht als solcher erkannt.')
