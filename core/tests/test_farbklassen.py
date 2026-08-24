"""Der Farbklassen-Zähler: Die Utility-Schuld darf nur kleiner werden.

WAS HIER GEZÄHLT WIRD

Fest verdrahtete Tailwind-Farbklassen in Vorlagen — `bg-slate-50`,
`text-indigo-600`, `border-white/10` und ihresgleichen.

Stand zu Beginn von E2.1: **7437 in 134 Vorlagen**. Nach der Umstellung von
`pendenzen.html` (71) und `fristen.html` (53): 7313 in 132 Vorlagen.
E2.2 nahm die drei dichtesten Seiten — `vertrag_neu.html` (275 → 2),
`kreditoren.html` (233 → 8), `buchhaltung.html` (217 → 0):
6598 in 131 Vorlagen.
E2.3 nahm die fuenf naechsten fw-Seiten — `person_form.html` (187 → 5),
`objekt_detail.html` (184 → 0), `bankabgleich.html` (170 → 6),
`debitoren.html` (112 → 0), `vertrag_bearbeiten.html` (106 → 0):
5850 in 128 Vorlagen.
E2.5 nahm drei weitere fw-Seiten — `vertrag_detail.html` (102 → 1),
`mieterwechsel.html` (101 → 3), `liegenschaft_form.html` (93 → 0):
5558 in 127 Vorlagen.
E2.6 nahm sechs Seiten auf einmal — `bewerbung_detail.html` (91 → 3),
`eigentuemer_kontokorrent.html` (88 → 0), `anlagen.html` (87 → 3),
`ersatzplanung.html` (87 → 0), `zahllauf.html` (86 → 2),
`nebenkosten_detail.html` (82 → 3): 5048 in 125 Vorlagen.
E2.7 nahm sechs weitere Seiten — `objekt_form.html` (81 → 0),
`hypotheken.html` (80 → 0), `logbuch.html` (80 → 0), `mwst.html` (79 → 0),
`kontenplan.html` (75 → 0), `dienstleister.html` (74 → 0):
4579 in 119 Vorlagen.
E2.8 nahm acht Seiten — `kommunikation` (74 → 0), `mahnwesen` (74 → 0),
`schaden_detail` (73 → 2), `weiterverrechnung` (72 → 0), `account` (69 → 0),
`nebenkosten` (68 → 0), `mietzins_anpassung` (66 → 0), `mieterkonto` (65 → 0):
4020 in 112 Vorlagen.
E2.9 nahm sechs Seiten in EINEM Durchlauf — `abnahme_neu` (64 → 0),
`anfangsmietzins` (64 → 0), `lieferantenkonto` (64 → 0), `mandat_form`
(63 → 0), `schlussabrechnung` (58 → 0), `abnahme_detail` (57 → 0):
**STAND 408 in 52 Vorlagen**.

Eins weniger als beim Herausloesen geplant: Der Absendeknopf des
öffentlichen Bewerbungsformulars trug `fw-gut-flaeche0` (eine Klasse, die
es nicht gibt) und daneben ein `hover:bg-emerald-600`, das zur neuen
Grundklasse nicht mehr passte. Beides ersetzt durch `fw-gut-voll`.

WAS `text-white` HIER NOCH DARF: Weisse Schrift auf einer gesaettigten
Flaeche — auf `fw-vorhang`, auf einem Markenknopf, auf `fw-krit-flaeche` —
ist nicht tokenabhaengig: Diese Flaechen sind in JEDER Darstellung dunkel
genug. Sie durch eine Schichtklasse zu ersetzen waere eine Umbenennung ohne
Gewinn.

NICHT ANGERUEHRT, UND ZWAR MIT ABSICHT: die zwei dichtesten Vorlagen
ueberhaupt. `schaden_melden.html` (264) und `public_bewerbung_form.html` (205)
erben NICHT von `fw/base.html`, sondern laden `core/_assets_aussen.html` —
dort gibt es keine einzige `fw-*`-Klasse. Beim ersten Versuch in E2.3 waren
beide bereits umgestellt; die Seiten waeren vollstaendig unformatiert
ausgeliefert worden, und zwar genau die zwei, die MIETER UND BEWERBER sehen.
Zurueckgenommen vor dem Ausliefern.

Wer sie angehen will, zieht zuerst die Komponentenschicht auf die
Aussenseiten. Das ist eine eigene Entscheidung: Es aendert das Aussehen
gegenueber Dritten (siehe `core/templates/fw/_assets.html`, wo dieselbe
Trennung fuer die Palette begruendet ist).

Die Zahl in Grossbuchstaben ist kein Schmuck — `test_der_stand_im_kopf_stimmt`
liest sie aus diesem Text und vergleicht sie mit der Messung. Eine erste
Fassung dieser Datei nannte 7366 und 7444 im selben Kopf, und beide waren
falsch: Der Test, der sie prüfen sollte, verglich in Wahrheit nur die Summe
der Obergrenzen mit sich selbst.

WARUM DAS EIN PROBLEM IST

Jede dieser Klassen ist eine Gestaltungsentscheidung, die an einer einzelnen
Stelle getroffen wurde und nirgends sonst gilt. Solange sie da sind:

  * lässt sich der Dunkelmodus nicht durchziehen — `bg-white` bleibt weiss,
    egal was der Benutzer eingestellt hat;
  * lässt sich mandantenspezifisches Branding (Entscheid D3, ab Professional)
    nicht umsetzen — eine Akzentfarbe je Organisation müsste jede einzelne
    dieser Stellen erreichen;
  * kostet jede Gestaltungsänderung so viele Handgriffe, wie es Vorkommen
    gibt, statt einen im Token.

Die Palette in `tailwind.palette.js` mildert das (dieselben Klassennamen
zeigen auf die Markenfarben), löst es aber nicht: Sie kann `bg-white` nicht
dunkel machen und nicht je Mandant verschieden.

WIE DIESER TEST WIRKT

Er ist kein Verbot, sondern eine Sperrklinke. Der Stand unten ist die
Obergrenze je Vorlage. Wer eine Vorlage anfasst, darf die Zahl senken — der
Test verlangt dann, dass die neue Zahl hier eingetragen wird. Wer sie erhöht,
bekommt eine rote Meldung mit dem Hinweis auf die Komponentenschicht.

So wird aus «irgendwann räumen wir auf» eine Zahl, die man ansehen kann. Ziel
von E2 ist 0 — erreicht wird es Bereich für Bereich, nicht auf einen Schlag.

DIE KOMPONENTENSCHICHT

`core/templates/fw/base.html` führt die `fw-*`-Klassen. Vier Vorlagen des
Bereichs «Heute» stehen bereits vollständig darauf (`dashboard`, `zulauf`,
`termine`, `abwesenheiten`: je 0 Klassen) — sie sind die Vorlage dafür, wie
eine umgestellte Seite aussieht.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)

#: Alle Tailwind-Farbrampen mit den Präfixen, die eine Farbe setzen.
FARBMUSTER = re.compile(
    r'\b(?:bg|text|border|ring|from|via|to|divide|placeholder|decoration|'
    r'outline|shadow|accent|caret|fill|stroke)-'
    r'(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|'
    r'emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|'
    r'white|black)(?:-\d{2,3})?(?:/\d{1,3})?\b')

#: Stand vom 23.08.2026 (Beginn E2). Obergrenze je Vorlage — nur senken.
#: WARUM `fw/base.html` MIT 184 GANZ OBEN STEHT UND TROTZDEM WARTEN MUSS
#:
#: NACHGEMESSEN, WEIL DIE ERSTE FASSUNG «alle 184» BEHAUPTETE: Es sind
#: **51 von 184**, die im Dunkelmodus-Overlay stecken — dem Block, der
#: Tailwind-Utilities fuer `[data-theme="dark"]` umdefiniert (`.bg-slate-100`,
#: `.text-slate-400` &c.). Gezaehlt je Regelblock, nicht je Zeile: Ein
#: zeilenweiser Blick verfehlt die mehrzeiligen Regeln.
#:
#: Die **133 uebrigen** sind gewoehnliches Markup der Huelle — `text-slate-400`
#: (19x), `text-white` (15x), `text-slate-500` (12x) in Seitenleiste und
#: Kopfzeile. Die sind NICHT blockiert und koennten jederzeit umgestellt
#: werden; nur die 51 muessen warten.
#:
#: Warum die 51 warten: Sie sind die Gegenstuecke zu Klassen, die in ANDEREN
#: Vorlagen stehen. Gemessen am 24.08.2026 mit der Zaehl-Logik dieses Tests:
#: `text-slate-400` in 56 Vorlagen, `border-slate-200` in 56,
#: `bg-slate-100` in 38 (jeweils inklusive base.html selbst). Wer das Overlay
#: jetzt abbaut, nimmt diesen Seiten den Dunkelmodus — sie faerben sich nicht
#: mehr um und stehen hell in einer dunklen Anwendung.
#:
#: Das Overlay ist deshalb der LETZTE Schritt von E2, nicht der naechste: Es
#: kann verschwinden, sobald die Zahl darunter 0 erreicht. Bis dahin ist seine
#: Obergrenze eine Buchhaltung ueber fremde Schuld.

OBERGRENZE = {
    'core/templates/admin/crm/handwerker_header.html': 2,
    'core/templates/admin/crm/mieter_header.html': 2,
    'core/templates/admin/crm/verwaltung_header.html': 2,
    'core/templates/admin/dashboard_stats.html': 82,
    'core/templates/admin/finance/abrechnung_vorschau.html': 30,
    'core/templates/core/_mieter_nav.html': 9,
    'core/templates/core/_passwort_shell_bottom.html': 2,
    'core/templates/core/_passwort_shell_top.html': 1,
    'core/templates/core/dossier/base.html': 7,
    'core/templates/core/mieter_kuendigung.html': 1,
    'core/templates/core/mieter_portal.html': 3,
    'core/templates/core/mieter_rechnungen.html': 1,
    'core/templates/core/mieter_schaden.html': 1,
    'core/templates/core/mieter_ticket_detail.html': 1,
    'core/templates/core/mieter_tickets.html': 2,
    'core/templates/core/mietzins_form.html': 73,
    'core/templates/core/passwort_reset_done.html': 4,
    'core/templates/core/portal_base.html': 8,
    'core/templates/core/public_bewerbung_form.html': 1,
    'core/templates/core/public_bewerbung_geschlossen.html': 7,
    'core/templates/core/public_ticket_form.html': 1,
    'core/templates/core/schaden_melden.html': 1,
    'core/templates/fw/_bezahlt_leer.html': 7,
    'core/templates/fw/_empty.html': 7,
    'core/templates/fw/_fwmodal.html': 7,
    'core/templates/fw/_menu_item.html': 5,
    'core/templates/fw/_modal_done.html': 5,
    'core/templates/fw/_pipeline.html': 1,
    'core/templates/fw/_schicht.html': 7,
    'core/templates/fw/anlagen.html': 3,
    'core/templates/fw/bankabgleich.html': 6,
    'core/templates/fw/base.html': 74,
    'core/templates/fw/bewerber_vergleich.html': 3,
    'core/templates/fw/bewerbung_detail.html': 3,
    'core/templates/fw/dokumente.html': 1,
    'core/templates/fw/einstellungen.html': 1,
    'core/templates/fw/finanzen.html': 1,
    'core/templates/fw/integrationen.html': 1,
    'core/templates/fw/kreditoren.html': 3,
    'core/templates/fw/lieferantenkonten.html': 1,
    'core/templates/fw/mieterkonten.html': 1,
    'core/templates/fw/mieterwechsel.html': 3,
    'core/templates/fw/mietzins.html': 1,
    'core/templates/fw/nebenkosten_detail.html': 3,
    'core/templates/fw/objekt_ausschreiben.html': 1,
    'core/templates/fw/person_form.html': 5,
    'core/templates/fw/schaden_detail.html': 2,
    'core/templates/fw/stub.html': 8,
    'core/templates/fw/vermarktung.html': 2,
    'core/templates/fw/vertrag_detail.html': 1,
    'core/templates/fw/vertrag_neu.html': 2,
    'core/templates/fw/zahllauf.html': 2,
}


#: Erklaertext, der Klassennamen NENNT, ohne sie zu benutzen.
KOMMENTARE = (
    re.compile(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', re.S),
    re.compile(r'\{#.*?#\}', re.S),
    re.compile(r'<!--.*?-->', re.S),
    re.compile(r'/\*.*?\*/', re.S),
)


def _ohne_kommentare(text):
    """Kommentare entfernen, bevor gezaehlt wird.

    Beim ersten Lauf dieses Waechters ist er ueber den eigenen Erklaertext
    gestolpert: Der Kommentar zum Grundvokabular in `fw/base.html` schreibt
    «`bg-white` bleibt weiss» — und der Zaehler las das als Verwendung. Die
    Vorlage waere gewachsen, ohne dass sich an der Darstellung etwas aendert.

    Derselbe blinde Fleck wie in `test_keine_fremdquellen.py`, wo der
    Erklaertext die gesperrten Adressen nennt. Ein Waechter, der Erklaerungen
    fuer Tatsachen haelt, bestraft genau das, was man foerdern will:
    aufschreiben, warum etwas so ist.
    """
    for muster in KOMMENTARE:
        text = muster.sub(' ', text)
    return text


def _zaehle(pfad):
    return len(FARBMUSTER.findall(_ohne_kommentare(pfad.read_text(encoding='utf-8'))))


def _alle_vorlagen():
    for p in sorted((WURZEL / 'core' / 'templates').rglob('*.html')):
        yield p.relative_to(WURZEL).as_posix(), p


class FarbklassenZaehlerTest(SimpleTestCase):

    def test_keine_vorlage_bekommt_mehr_farbklassen(self):
        gewachsen = []
        for rel, pfad in _alle_vorlagen():
            ist, grenze = _zaehle(pfad), OBERGRENZE.get(rel, 0)
            if ist > grenze:
                gewachsen.append(f'{rel}: {grenze} → {ist}')
        self.assertEqual(
            gewachsen, [],
            'Diese Vorlagen haben mehr fest verdrahtete Farbklassen als zuvor:\n  '
            + '\n  '.join(gewachsen)
            + '\n\nStatt `bg-slate-50` gehört dorthin eine Klasse der '
              'Komponentenschicht (`fw-*` in fw/base.html) oder ein Token '
              '(`var(--ds-…)`). Ein Blick auf fw/dashboard.html zeigt, wie eine '
              'vollständig umgestellte Seite aussieht — sie kommt ohne eine '
              'einzige Farbklasse aus.')

    def test_gesunkene_zahlen_werden_nachgefuehrt(self):
        """Wer aufräumt, trägt die neue Zahl ein — sonst schleicht sie zurück.

        Ohne diese Hälfte wäre die Sperrklinke nur halb: Eine Vorlage, die von
        70 auf 5 fällt und deren Obergrenze bei 70 bleibt, darf danach
        unbemerkt wieder auf 70 wachsen.
        """
        gesunken = []
        for rel, pfad in _alle_vorlagen():
            ist, grenze = _zaehle(pfad), OBERGRENZE.get(rel)
            if grenze is not None and ist < grenze:
                gesunken.append(f'{rel}: {grenze} → {ist}')
        self.assertEqual(
            gesunken, [],
            'Hier wurde aufgeräumt — bitte OBERGRENZE nachführen:\n  '
            + '\n  '.join(gesunken)
            + '\n\n(Bei 0 den Eintrag ganz streichen.)')

    def test_der_stand_im_kopf_stimmt(self):
        """Die Zahl im Erklärtext darf nicht altern.

        WARUM DIESER TEST NEU GESCHRIEBEN WURDE

        Er hiess `test_die_summe_steht_im_kopf_dieser_datei` und verglich
        `sum(_zaehle(...))` mit `sum(OBERGRENZE.values())`. Das ist keine
        Prüfung des Kopftextes, sondern eine Folge des ersten Tests: Wenn
        keine Vorlage über ihrer Grenze liegt, ist die Summe zwangsläufig
        kleiner oder gleich. Der Test war also immer grün und sagte nichts.

        Und genau der Fehler, den er hätte finden sollen, war da: Der Kopf
        nannte 7366 und 7444, gemessen waren es 7437 vorher und 7313 nachher.
        Ein Test, dessen Name eine Prüfung verspricht, die er nicht macht, ist
        schlechter als gar keiner — man verlässt sich darauf.

        Jetzt wird die Zahl aus dem Kopf gelesen und mit der Messung
        verglichen. Wer aufräumt, muss sie nachführen; das ist derselbe
        Handgriff wie beim Nachführen von OBERGRENZE.
        """
        import re as _re
        treffer = _re.search(r'STAND (\d+) in (\d+) Vorlagen', __doc__ or '')
        self.assertIsNotNone(
            treffer,
            'Im Kopf dieser Datei fehlt die Zeile «STAND <n> in <m> Vorlagen». '
            'Ohne sie kann niemand prüfen, ob der Erklärtext noch stimmt.')

        gezaehlt = {rel: _zaehle(p) for rel, p in _alle_vorlagen()}
        gesamt = sum(gezaehlt.values())
        vorlagen = sum(1 for n in gezaehlt.values() if n)

        self.assertEqual(
            (gesamt, vorlagen), (int(treffer.group(1)), int(treffer.group(2))),
            f'Der Kopf dieser Datei sagt {treffer.group(1)} in '
            f'{treffer.group(2)} Vorlagen, gemessen sind es {gesamt} in '
            f'{vorlagen}. Bitte den Kopf nachführen — die Zahl ist das Mass '
            f'dieser Etappe und wird gelesen, nicht überflogen.')

    def test_die_obergrenzen_decken_genau_die_vorlagen_ab(self):
        """Ein Eintrag für eine Vorlage ohne Farbklassen täuscht Schuld vor,
        eine Vorlage ohne Eintrag hat stillschweigend die Grenze 0.

        Das zweite ist der gefährlichere Fall: Er ist richtig, solange die
        Vorlage wirklich bei 0 steht — und genau das prüft der erste Test.
        Hier geht es um das erste: Wer eine Vorlage auf 0 bringt und den
        Eintrag stehen lässt, hält die Summe künstlich hoch.
        """
        gezaehlt = {rel: _zaehle(p) for rel, p in _alle_vorlagen()}
        leer_mit_eintrag = sorted(r for r, g in OBERGRENZE.items()
                                  if gezaehlt.get(r, 0) == 0)
        self.assertEqual(
            leer_mit_eintrag, [],
            f'Diese Vorlagen stehen bei 0, haben aber noch einen Eintrag in '
            f'OBERGRENZE: {leer_mit_eintrag}. Bitte streichen.')
