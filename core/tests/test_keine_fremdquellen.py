"""Die Oberfläche hängt an keiner fremden Adresse.

WARUM

Bis E0.2 zogen die Hüllen drei Fremdquellen: Tailwind als Browser-JIT von
cdn.tailwindcss.com, Font Awesome von cdnjs, Inter von Google Fonts. Ohne
Zugang zu diesen Hosts rendert swissImmo **völlig unformatiert** — kein Layout,
keine Farben, keine Icons. Dazu drei Fremdaufrufe pro Seitenaufbau und die
IP-Adresse jeder Mieterin bei Dritten.

Der Rückfall ist leicht: Wer eine neue Hülle oder eine öffentliche Seite baut,
kopiert die zwei Zeilen aus einer bestehenden Vorlage, und das CDN ist wieder da.
Genau so kam es beim letzten Mal — `_tailwind_palette.html` lag auf drei Hüllen,
die Aussenseiten hatten es nie.

WAS DIESER TEST NICHT PRÜFT

Es gibt weitere Fremdbibliotheken im Bestand (Vue, Alpine, Bootstrap, Chart.js,
signature_pad) auf öffentlichen Formularen und im Admin. Die stehen in
`ANDERE_FREMDQUELLEN` namentlich und sind bewusst noch NICHT gesperrt: Sie
einzulagern ist eine eigene Etappe. Wer eine davon erledigt, streicht sie hier
aus der Liste — dann schlägt der Test zu, sobald sie zurückkehrt.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# Die Quellen, die E0.2 entfernt hat. Ab hier gesperrt.
#
# E2.23 hat `cdn.jsdelivr.net` und `unpkg.com` dazugenommen: Alpine, Vue,
# signature_pad, bootstrap-icons und chart.js liegen jetzt unter `static/`,
# geholt ueber npm statt ueber ein CDN. Damit schickt keine oeffentliche Seite
# mehr die IP-Adresse eines Mieters oder Bewerbers an einen fremden Server —
# und sie funktioniert auch, wenn das CDN nicht erreichbar ist.
GESPERRT = (
    'cdn.tailwindcss.com',
    'cdnjs.cloudflare.com',
    'fonts.googleapis.com',
    'fonts.gstatic.com',
    'cdn.jsdelivr.net',
    'unpkg.com',
)

# Noch offen, mit Namen und Ort. Kein Freibrief, sondern eine Liste, die kürzer
# werden soll — jede Zeile ist eine offene Aufgabe.
ANDERE_FREMDQUELLEN = set()
# LEER SEIT E2.23 — und das ist der Punkt.
#
# Diese Liste stand seit E0.2 fuer die fuenf Bibliotheken, die noch von fremden
# Servern kamen: bootstrap-icons, Alpine (zweimal), signature_pad, Vue und
# chart.js. Drei der vier Vorlagen sind oeffentlich; jeder Aufruf schickte die
# IP-Adresse eines Mieters oder Bewerbers an einen Dritten, und die Seite brach,
# wenn das CDN nicht erreichbar war.
#
# Die Dateien liegen jetzt unter `static/`, geholt ueber npm — dieselbe Quelle
# wie das CDN, nur ohne Laufzeitabhaengigkeit. Ihre Herkunft ist nachgemessen
# (byteweise gegen das npm-Paket), nicht angenommen; welche Fassung wo liegt,
# steht in `docs/FREMDBIBLIOTHEKEN.md`. `cdn.jsdelivr.net` und `unpkg.com`
# stehen darum oben in GESPERRT.
#
# Eine leere Liste ist kein Freibrief: Wer eine neue Fremdquelle einbaut, muss
# sie hier eintragen UND begruenden. Der Test darueber faellt sonst.

WURZEL = Path(settings.BASE_DIR)


def _vorlagen():
    """Alle Vorlagen UND eigene Stylesheets, ausser Prototypen und Fremdcode.

    CSS KAM ERST IN E2.50 DAZU — UND DAS WAR DIE LUECKE

    Der Waechter las ausschliesslich `*.html`. `static/css/fairwalter_theme.css`
    rief in Zeile 4 `fonts.googleapis.com` auf, und die Datei wird ueber
    `UNFOLD["STYLES"]` in JEDE Admin-Seite geladen — ein Fremdaufruf bei jedem
    Aufruf, seit E0.2 unbemerkt.

    Ein Wächter, der nur eine Dateiart liest, sperrt auch nur diese. Das ist
    dieselbe Fehlerart wie die Farbklassen in Python-Views (E2.20) und die
    Zeichen in Datenwerten (E2.41): Die Regel stimmte, der Suchbereich nicht.

    Die gebauten Dateien (`tailwind*.css`, `schicht*.css`) sind ausgenommen —
    sie entstehen aus Quellen, die hier ohnehin geprueft werden, und ein
    Treffer dort waere ein Symptom, keine Ursache.
    """
    GEBAUT = ('static/css/tailwind.css', 'static/css/tailwind-aussen.css',
              'static/css/schicht.css', 'static/css/schicht.src.css')
    for muster in ('*.html', '*.css'):
        for pfad in WURZEL.rglob(muster):
            rel = pfad.relative_to(WURZEL).as_posix()
            if rel.startswith(('mockups/', 'node_modules/', 'staticfiles/')):
                continue
            if rel in GEBAUT:
                continue
            # Fremde Bibliotheken: bootstrap-icons, fontawesome und Aehnliches
            # tragen ihre eigenen Verweise; die sind nicht unsere Entscheidung.
            if rel.startswith('static/css/') and any(
                    x in rel for x in ('fontawesome', 'bootstrap-icons')):
                continue
            yield rel, pfad


class KeineFremdquellenTest(SimpleTestCase):

    def test_keine_vorlage_laedt_tailwind_fontawesome_oder_google_fonts(self):
        funde = []
        for rel, pfad in _vorlagen():
            text = pfad.read_text(encoding='utf-8')
            # KOMMENTARE FALLEN IMMER WEG, NICHT NUR IN ZWEI DATEIEN.
            #
            # Bis E2.50 galt das nur für `_assets.html` und
            # `_assets_aussen.html`. Beim Ausweiten auf CSS meldete der
            # Wächter sofort `schriften.css` — wo der Host in der BEGRÜNDUNG
            # steht, warum er nicht mehr benutzt wird.
            #
            # Ein Wächter, der die Erklärung seines eigenen Verbots als
            # Verstoss meldet, wird weggeklickt. Achtes Mal in dieser Reihe,
            # dass Erklärtext für Inhalt gehalten wurde.
            text = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '',
                          text, flags=re.S)
            text = re.sub(r'\{#.*?#\}|<!--.*?-->|/\*.*?\*/', '', text, flags=re.S)
            for host in GESPERRT:
                if host in text:
                    funde.append(f'{rel}: {host}')

        self.assertEqual(
            funde, [],
            'Diese Vorlagen laden wieder von fremden Adressen:\n  '
            + '\n  '.join(funde)
            + '\n\nDie Stilbausteine liegen im Repo. Statt der CDN-Zeilen gehört '
              "dorthin {% include 'fw/_assets.html' %} (Anwendung, Petrol-Palette) "
              "oder {% include 'core/_assets_aussen.html' %} (Mieterportal, "
              'öffentliche Formulare, Fehlerseiten — Tailwind in Voreinstellung).')

    def test_das_ausblenden_der_kommentare_ist_nicht_zu_grosszuegig(self):
        """Gegenprobe zur Ausnahme oben.

        Der Baustein darf seinen Erklärtext behalten, aber die Ausnahme darf
        nicht so weit gehen, dass sie eine echte CDN-Zeile mitverschluckt.
        """
        beispiel = ("{% comment %}nennt cdn.tailwindcss.com{% endcomment %}\n"
                    '<script src="https://cdn.tailwindcss.com"></script>')
        ohne = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '',
                      beispiel, flags=re.S)
        self.assertIn('cdn.tailwindcss.com', ohne,
                      'Die Ausnahme verschluckt echte Verweise ausserhalb des '
                      'Kommentars — dann prüft der Wächter darüber nichts mehr.')

    def test_die_liste_der_offenen_fremdquellen_stimmt_noch(self):
        """Die Liste darf schrumpfen, aber nicht heimlich wachsen."""
        tatsaechlich = set()
        for rel, pfad in _vorlagen():
            text = pfad.read_text(encoding='utf-8')
            if re.search(r'https?://(cdn\.jsdelivr\.net|unpkg\.com)', text):
                tatsaechlich.add(rel)

        neu = tatsaechlich - ANDERE_FREMDQUELLEN
        self.assertEqual(
            neu, set(),
            'Neue Fremdbibliothek in einer Vorlage:\n  ' + '\n  '.join(sorted(neu))
            + '\n\nBibliotheken gehören ins Repo, nicht auf ein fremdes CDN. '
              'Wenn es einen Grund gibt, trag die Vorlage hier ein — mit Namen '
              'der Bibliothek als Kommentar.')

        erledigt = ANDERE_FREMDQUELLEN - tatsaechlich
        self.assertEqual(
            erledigt, set(),
            'Diese Vorlagen laden keine Fremdbibliothek mehr:\n  '
            + '\n  '.join(sorted(erledigt))
            + '\n\nSchön — bitte aus ANDERE_FREMDQUELLEN streichen, damit der '
              'Wächter ab jetzt auf sie aufpasst.')


class StilbausteineVorhandenTest(SimpleTestCase):
    """Die Dateien, auf die die Bausteine zeigen, müssen im Repo liegen."""

    ERWARTET = (
        'static/css/tailwind.css',
        'static/css/tailwind-aussen.css',
        'static/css/schriften.css',
        'static/css/fontawesome.css',
        'static/fonts/IBMPlexSans-Regular-Latin1.woff2',
        'static/fonts/IBMPlexMono-Regular-Latin1.woff2',
        'static/webfonts/fa-solid-900.woff2',
    )

    def test_dateien_liegen_im_repo(self):
        fehlend = [d for d in self.ERWARTET if not (WURZEL / d).exists()]
        self.assertEqual(
            fehlend, [],
            'Diese Stildateien fehlen:\n  ' + '\n  '.join(fehlend)
            + '\n\nOhne sie rendert die Anwendung unformatiert. '
              'Tailwind neu bauen: `npm run css:alle`.')

    def test_schriften_css_verweist_nur_auf_vorhandene_dateien(self):
        css = (WURZEL / 'static/css/schriften.css').read_text(encoding='utf-8')
        verweise = re.findall(r"url\('([^']+)'\)", css)
        self.assertTrue(verweise,
                        'schriften.css nennt keine einzige Schriftdatei — dann '
                        'prüft die Schleife darunter nichts.')
        fehlend = []
        for verweis in verweise:
            ziel = (WURZEL / 'static/css' / verweis).resolve()
            if not ziel.exists():
                fehlend.append(verweis)
        self.assertEqual(
            fehlend, [],
            'schriften.css verweist auf Dateien, die es nicht gibt:\n  '
            + '\n  '.join(fehlend)
            + '\n\nDer Browser lädt dann ins Leere und fällt still auf eine '
              'Systemschrift zurück — sichtbar erst, wenn jemand hinschaut.')

    def test_fontawesome_css_verweist_nur_auf_vorhandene_dateien(self):
        css = (WURZEL / 'static/css/fontawesome.css').read_text(encoding='utf-8')
        verweise = set(re.findall(r'url\((?:"|\')?([^)"\']+\.woff2)', css))
        self.assertTrue(verweise, 'fontawesome.css nennt keine Schriftdatei.')
        fehlend = []
        for verweis in verweise:
            ziel = (WURZEL / 'static/css' / verweis).resolve()
            if not ziel.exists():
                fehlend.append(verweis)
        self.assertEqual(
            fehlend, [],
            'fontawesome.css verweist auf Schriftdateien, die nicht ausgeliefert '
            'werden:\n  ' + '\n  '.join(fehlend)
            + '\n\nBrands und v4compatibility sind bewusst nicht dabei (im Bestand '
              'kommt kein einziges Marken-Icon vor, das spart 117 KB). Wer ein '
              'Marken-Icon braucht, legt die Datei dazu.')
