"""Stilschuld darf nur kleiner werden (Audit Etappe 3, Teil 4).

Drei Arten, an der Komponentenschicht vorbei zu gestalten — gezählt je
Vorlage, mit einer Obergrenze, die nur sinken darf. Dasselbe Muster wie
`test_farbklassen.py`: Wer aufräumt, trägt die neue Zahl ein; wer eine Stelle
dazubaut, wird rot.

PIXELGROESSE   `text-[13px]` statt einer Stufe der Skala (`fw-fs-*`).
               In `fw/` bereits auf null (`test_audit_etappe3`); übrig sind
               Portal, PDF- und E-Mail-Vorlagen.
INLINE_STIL    `style="…"` am Element statt einer Klasse der Schicht.
FREIE_RUNDUNG  `rounded-[…]` oder `border-radius:` ohne Token
               (`var(--ds-radius…)`).
SELBSTGEBAUTER_KNOPF  `<button|a class="… px-3 py-1.5 rounded-lg font-semibold …">`
               ohne `fw-btn`. Seit Etappe 3 Teil 2 gibt es die Varianten
               (`fw-knapp`, `fw-leise`, `fw-rand-marke` …); übrig sind Knöpfe,
               deren Klassen ein Skript umschaltet.

Stand beim Einführen, 29.09.2026:
  PIXELGROESSE   47 in 15 Vorlagen
  INLINE_STIL    451 in 70 Vorlagen
  FREIE_RUNDUNG  112 in 20 Vorlagen
  SELBSTGEBAUTER_KNOPF  53 in 22 Vorlagen (nach Teil 2; vorher 90 allein in fw/)

NICHT GEZÄHLT: Kommentare. Ein Erklärtext, der `style="…"` nennt, ist keine
Verwendung (dieselbe Falle wie beim Farbwächter).

NICHT JEDE STELLE IST SCHULD. Ein `style="width:{{ prozent }}%"` für einen
Balken ist ein Datenwert, keine Gestaltung — der gehört nicht in eine Klasse.
Die Obergrenzen sagen deshalb nicht «muss auf null», sondern «darf nicht
wachsen».
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)
VORLAGEN = WURZEL / 'core' / 'templates'

MUSTER = {
    'PIXELGROESSE': re.compile('(?<![\\w:-])text-\\[[0-9.]+px\\]'),
    'INLINE_STIL': re.compile('\\sstyle=\\"'),
    'SELBSTGEBAUTER_KNOPF': re.compile('<(?:button|a)\\b[^>]*\\bclass="(?![^"]*\\bfw-btn\\b)(?=[^"]*\\bpx-\\d)(?=[^"]*\\bpy-\\d)(?=[^"]*\\brounded)(?=[^"]*\\bfont-(?:semibold|bold)\\b)[^"]*"'),
    'FREIE_RUNDUNG': re.compile('\\brounded(?:-[a-z]+)?-\\[[^\\]]+\\]|border-radius\\s*:\\s*(?!var\\(--ds-)'),
}

OBERGRENZE = {
    'PIXELGROESSE': {
    'admin/finance/abrechnung_vorschau.html': 1,
    'core/dossier/base.html': 3,
    'core/dossier/liegenschaft.html': 4,
    'core/dossier/mieter.html': 4,
    'core/dossier/vertrag.html': 8,
    'core/mieter_dokumente.html': 1,
    'core/mieter_konto.html': 1,
    'core/mieter_portal.html': 7,
    'core/mieter_ticket_detail.html': 3,
    'core/passwort_reset.html': 1,
    'core/passwort_reset_confirm.html': 2,
    'core/schaden_melden.html': 8,
},
    'INLINE_STIL': {
    'admin/base.html': 26,
    'admin/crm/eigentuemer_header.html': 22,
    'admin/crm/handwerker_header.html': 22,
    'admin/crm/mieter_header.html': 24,
    'admin/crm/verwaltung_header.html': 22,
    'admin/finance/abrechnung_vorschau.html': 1,
    'admin/portfolio/einheit_header.html': 20,
    'admin/portfolio/liegenschaft_header.html': 19,
    'admin/rentals/mietvertrag_header.html': 20,
    'core/dok_base.html': 1,
    'core/dok_begleitbrief.html': 8,
    'core/dok_kuendigungsbestaetigung.html': 9,
    'core/login.html': 1,
    'core/mieter_kuendigung.html': 1,
    'core/mietvertrag_garage.html': 23,
    'core/mietvertrag_pdf.html': 35,
    'core/portal.html': 1,
    'core/portal_login.html': 1,
    'core/schaden_melden.html': 4,
    'core/zweifaktor_einrichten.html': 1,
    'emails/base_email.html': 1,
    'emails/email_mahnung.html': 2,
    'fw/_listwerkzeug.html': 1,
    'fw/_unterschrift_feld.html': 2,
    'fw/_zeichen.html': 1,
    'fw/abonnement.html': 2,
    'fw/auswertung.html': 2,
    'fw/dashboard.html': 1,
    'fw/ersatzplanung.html': 1,
    'fw/fall_detail.html': 5,
    'fw/kommunikation.html': 1,
    'fw/leerstand_verlauf.html': 1,
    'fw/regelwerk_protokoll.html': 1,
    'fw/schaden_detail.html': 2,
    'fw/vertrag_detail.html': 5,
    'fw/vertrag_neu.html': 1,
    'fw/zulauf.html': 1,
},
    'SELBSTGEBAUTER_KNOPF': {
    'core/dossier/base.html': 7,
    'core/dossier/vertrag.html': 4,
    'core/mieter_konto.html': 1,
    'core/mieter_kuendigung.html': 2,
    'core/mieter_rechnungen.html': 2,
    'core/mieter_schaden.html': 1,
    'core/mieter_ticket_detail.html': 1,
    'core/mieter_tickets.html': 2,
    'core/mietzins_form.html': 1,
    'core/public_bewerbung_form.html': 1,
    'fw/_unterschrift_feld.html': 1,
},
    'FREIE_RUNDUNG': {
    'admin/base.html': 3,
    'admin/crm/eigentuemer_header.html': 6,
    'admin/crm/handwerker_header.html': 6,
    'admin/crm/mieter_header.html': 7,
    'admin/crm/verwaltung_header.html': 6,
    'admin/portfolio/einheit_header.html': 6,
    'admin/portfolio/liegenschaft_header.html': 6,
    'admin/rentals/mietvertrag_header.html': 6,
    'core/dossier/base.html': 1,
    'core/index.html': 4,
    'core/login.html': 9,
    'core/portal.html': 14,
    'core/portal_login.html': 10,
    'core/public_ticket_form.html': 1,
    'emails/base_email.html': 4,
    'fw/_schicht.html': 12,
    'fw/vertrag_neu.html': 1,
},
}

KOMMENTARE = (
    re.compile(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', re.S),
    re.compile(r'\{#.*?#\}', re.S),
    re.compile(r'<!--.*?-->', re.S),
    re.compile(r'/\*.*?\*/', re.S),
)


def _ohne_kommentare(text):
    for muster in KOMMENTARE:
        text = muster.sub(' ', text)
    return text


def _zaehlung(art):
    ergebnis = {}
    for pfad in sorted(VORLAGEN.rglob('*.html')):
        n = len(MUSTER[art].findall(_ohne_kommentare(pfad.read_text(encoding='utf-8'))))
        if n:
            ergebnis[pfad.relative_to(VORLAGEN).as_posix()] = n
    return ergebnis


class StilschuldTest(SimpleTestCase):

    def test_keine_vorlage_bekommt_mehr(self):
        gewachsen = []
        for art in MUSTER:
            for rel, ist in _zaehlung(art).items():
                grenze = OBERGRENZE[art].get(rel, 0)
                if ist > grenze:
                    gewachsen.append(f'{art} {rel}: {grenze} → {ist}')
        self.assertEqual(
            gewachsen, [],
            'Mehr Stilschuld als zuvor:\n  ' + '\n  '.join(gewachsen)
            + '\n\nStatt `text-[13px]` eine Stufe `fw-fs-*`, statt `style="…"` eine '
              'Klasse der Schicht (fw/_schicht.html), statt einer freien Rundung '
              '`var(--ds-radius…)`.')

    def test_gesunkene_zahlen_werden_nachgefuehrt(self):
        """Sonst darf eine aufgeräumte Vorlage unbemerkt zurückwachsen."""
        gesunken = []
        for art in MUSTER:
            ist = _zaehlung(art)
            for rel, grenze in OBERGRENZE[art].items():
                if ist.get(rel, 0) < grenze:
                    gesunken.append(f'{art} {rel}: {grenze} → {ist.get(rel, 0)}')
        self.assertEqual(
            gesunken, [],
            'Hier wurde aufgeräumt — bitte OBERGRENZE nachführen:\n  '
            + '\n  '.join(gesunken) + '\n\n(Bei 0 den Eintrag streichen.)')

    def test_die_zaehlung_findet_ueberhaupt_etwas(self):
        """Gegenprobe: Ein Muster, das nie greift, wäre immer grün."""
        probe = {
            'PIXELGROESSE': '<p class="text-[13px]">',
            'INLINE_STIL': '<p style="color:red">',
            'FREIE_RUNDUNG': '<p class="rounded-[5px]">',
            'SELBSTGEBAUTER_KNOPF': '<button class="px-3 py-1.5 rounded-lg font-semibold">',
        }
        for art, text in probe.items():
            with self.subTest(art=art):
                self.assertEqual(len(MUSTER[art].findall(text)), 1)
        self.assertEqual(MUSTER['FREIE_RUNDUNG'].findall('border-radius:var(--ds-radius)'), [])
        self.assertEqual(MUSTER['SELBSTGEBAUTER_KNOPF'].findall(
            '<button class="fw-btn px-3 py-1.5 rounded-lg font-semibold">'), [])
        self.assertEqual(MUSTER['INLINE_STIL'].findall(_ohne_kommentare('{# style="x" #}')), [])


def _kursive_leere_zustaende(text):
    """Stellen, an denen direkt nach `{% empty %}` ein kursiver Einzeiler steht."""
    zeilen = _ohne_kommentare(text).split('\n')
    return [i + 1 for i, z in enumerate(zeilen)
            if '{% empty %}' in z and 'italic' in ' '.join(zeilen[i:i + 3])]


class KursiveLeereZustaende(SimpleTestCase):
    """Leere Zustände nur über `fw/_empty.html` (Audit Etappe 4).

    Vorher: 33 kursive Einzeiler «Keine …» in 23 Vorlagen, jeder etwas anders
    gebaut. Jetzt alle über den Baustein — in Tabellen und Nebenlisten die
    knappe Form (`knapp=True`). Die Zahl steht auf null und bleibt dort.
    """

    def test_keine_kursiven_einzeiler_in_fw(self):
        funde = []
        for pfad in sorted((VORLAGEN / 'fw').glob('*.html')):
            for nr in _kursive_leere_zustaende(pfad.read_text(encoding='utf-8')):
                funde.append(f'fw/{pfad.name}:{nr}')
        self.assertEqual(
            funde, [],
            'Leerer Zustand als kursiver Einzeiler:\n  ' + '\n  '.join(funde)
            + "\n\nStattdessen {% include 'fw/_empty.html' with knapp=True icon='…' "
              "titel=_('…') %} (in einer Tabellenzeile in <td class=\"fw-leerzeile\">).")

    def test_die_erkennung_greift(self):
        """Gegenprobe: Eine Erkennung, die nie greift, wäre immer grün."""
        self.assertEqual(_kursive_leere_zustaende(
            '{% for x in y %}\n{% empty %}\n<p class="fw-faint italic">Keine</p>\n{% endfor %}'), [2])
        self.assertEqual(_kursive_leere_zustaende(
            "{% empty %}{% include 'fw/_empty.html' with knapp=True titel='x' %}"), [])
