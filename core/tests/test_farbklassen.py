"""Der Farbklassen-Zähler: Die Utility-Schuld darf nur kleiner werden.

WAS HIER GEZÄHLT WIRD

Fest verdrahtete Tailwind-Farbklassen in Vorlagen — `bg-slate-50`,
`text-indigo-600`, `border-white/10` und ihresgleichen.

Stand zu Beginn von E2.1: **7437 in 134 Vorlagen**. Nach der Umstellung von
`pendenzen.html` (71) und `fristen.html` (53): **STAND 7313 in 132 Vorlagen**.

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
OBERGRENZE = {
    'core/templates/403.html': 10,
    'core/templates/404.html': 10,
    'core/templates/500.html': 10,
    'core/templates/admin/crm/handwerker_header.html': 2,
    'core/templates/admin/crm/mieter_header.html': 2,
    'core/templates/admin/crm/verwaltung_header.html': 2,
    'core/templates/admin/dashboard_stats.html': 82,
    'core/templates/admin/finance/abrechnung_vorschau.html': 30,
    'core/templates/core/_mieter_nav.html': 47,
    'core/templates/core/_passwort_shell_bottom.html': 2,
    'core/templates/core/_passwort_shell_top.html': 8,
    'core/templates/core/dossier/base.html': 37,
    'core/templates/core/dossier/liegenschaft.html': 90,
    'core/templates/core/dossier/mieter.html': 108,
    'core/templates/core/dossier/vertrag.html': 118,
    'core/templates/core/mieter_daten.html': 27,
    'core/templates/core/mieter_dokumente.html': 21,
    'core/templates/core/mieter_konto.html': 40,
    'core/templates/core/mieter_kuendigung.html': 55,
    'core/templates/core/mieter_passwort.html': 16,
    'core/templates/core/mieter_portal.html': 73,
    'core/templates/core/mieter_rechnungen.html': 36,
    'core/templates/core/mieter_schaden.html': 42,
    'core/templates/core/mieter_ticket_detail.html': 37,
    'core/templates/core/mieter_tickets.html': 21,
    'core/templates/core/mietzins_form.html': 73,
    'core/templates/core/passwort_reset.html': 12,
    'core/templates/core/passwort_reset_complete.html': 8,
    'core/templates/core/passwort_reset_confirm.html': 25,
    'core/templates/core/passwort_reset_done.html': 4,
    'core/templates/core/portal_base.html': 25,
    'core/templates/core/postfach_form.html': 48,
    'core/templates/core/postfach_liste.html': 36,
    'core/templates/core/public_bewerbung_form.html': 205,
    'core/templates/core/public_bewerbung_geschlossen.html': 7,
    'core/templates/core/public_datenschutz.html': 10,
    'core/templates/core/public_ticket_form.html': 120,
    'core/templates/core/schaden_melden.html': 264,
    'core/templates/core/zweifaktor_codes.html': 14,
    'core/templates/core/zweifaktor_einrichten.html': 25,
    'core/templates/core/zweifaktor_uebersicht.html': 53,
    'core/templates/fw/_bezahlt_leer.html': 7,
    'core/templates/fw/_empty.html': 7,
    'core/templates/fw/_fwmodal.html': 7,
    'core/templates/fw/_menu_item.html': 5,
    'core/templates/fw/_modal_done.html': 5,
    'core/templates/fw/_pipeline.html': 13,
    'core/templates/fw/_unterschrift_feld.html': 34,
    'core/templates/fw/abnahme_detail.html': 57,
    'core/templates/fw/abnahme_neu.html': 64,
    'core/templates/fw/abonnement.html': 54,
    'core/templates/fw/account.html': 69,
    'core/templates/fw/anfangsmietzins.html': 64,
    'core/templates/fw/anlagen.html': 87,
    'core/templates/fw/auswertung.html': 36,
    'core/templates/fw/bankabgleich.html': 170,
    'core/templates/fw/bankkonten.html': 45,
    'core/templates/fw/base.html': 191,
    'core/templates/fw/base_embed.html': 8,
    'core/templates/fw/benutzer.html': 19,
    'core/templates/fw/benutzer_form.html': 34,
    'core/templates/fw/berichte.html': 18,
    'core/templates/fw/betriebskostenspiegel.html': 32,
    'core/templates/fw/bewerber_vergleich.html': 50,
    'core/templates/fw/bewerbung_detail.html': 91,
    'core/templates/fw/bewerbungen.html': 12,
    'core/templates/fw/buchhaltung.html': 217,
    'core/templates/fw/debitoren.html': 112,
    'core/templates/fw/debitoren_aging.html': 50,
    'core/templates/fw/dienstleister.html': 74,
    'core/templates/fw/dokumente.html': 50,
    'core/templates/fw/eigentuemer_kontokorrent.html': 88,
    'core/templates/fw/einstellungen.html': 10,
    'core/templates/fw/ersatzplanung.html': 87,
    'core/templates/fw/finanzen.html': 49,
    'core/templates/fw/hypotheken.html': 80,
    'core/templates/fw/integrationen.html': 48,
    'core/templates/fw/kautionen.html': 28,
    'core/templates/fw/kommunikation.html': 74,
    'core/templates/fw/kontenplan.html': 75,
    'core/templates/fw/kontoblatt.html': 36,
    'core/templates/fw/kreditoren.html': 233,
    'core/templates/fw/kuendigung_form.html': 50,
    'core/templates/fw/lebensdauer.html': 33,
    'core/templates/fw/leerstand_verlauf.html': 36,
    'core/templates/fw/lieferantenkonten.html': 25,
    'core/templates/fw/lieferantenkonto.html': 64,
    'core/templates/fw/liegenschaft_form.html': 93,
    'core/templates/fw/liegenschaften.html': 13,
    'core/templates/fw/logbuch.html': 80,
    'core/templates/fw/maengelruege.html': 18,
    'core/templates/fw/mahnwesen.html': 74,
    'core/templates/fw/mandat_abrechnung.html': 48,
    'core/templates/fw/mandat_form.html': 63,
    'core/templates/fw/mandate.html': 21,
    'core/templates/fw/mieterkonten.html': 37,
    'core/templates/fw/mieterkonto.html': 65,
    'core/templates/fw/mieterspiegel.html': 56,
    'core/templates/fw/mieterspiegel_auswahl.html': 21,
    'core/templates/fw/mieterwechsel.html': 101,
    'core/templates/fw/mietzins.html': 52,
    'core/templates/fw/mietzins_anpassung.html': 66,
    'core/templates/fw/mietzins_massen.html': 27,
    'core/templates/fw/mwst.html': 79,
    'core/templates/fw/nebenkosten.html': 68,
    'core/templates/fw/nebenkosten_detail.html': 82,
    'core/templates/fw/objekt_ausschreiben.html': 20,
    'core/templates/fw/objekt_detail.html': 184,
    'core/templates/fw/objekt_form.html': 81,
    'core/templates/fw/person_form.html': 187,
    'core/templates/fw/personen.html': 18,
    'core/templates/fw/rechtsgrundlagen.html': 32,
    'core/templates/fw/schaden_detail.html': 73,
    'core/templates/fw/schaden_kosten.html': 40,
    'core/templates/fw/schaeden.html': 33,
    'core/templates/fw/schlussabrechnung.html': 58,
    'core/templates/fw/sollstellung.html': 53,
    'core/templates/fw/stub.html': 8,
    'core/templates/fw/suche.html': 47,
    'core/templates/fw/untermiete.html': 20,
    'core/templates/fw/vermarktung.html': 47,
    'core/templates/fw/vertraege.html': 18,
    'core/templates/fw/vertrag_bearbeiten.html': 106,
    'core/templates/fw/vertrag_detail.html': 102,
    'core/templates/fw/vertrag_neu.html': 275,
    'core/templates/fw/verzug_257d.html': 46,
    'core/templates/fw/vorlage_form.html': 25,
    'core/templates/fw/vorlagen.html': 28,
    'core/templates/fw/weiterverrechnung.html': 72,
    'core/templates/fw/zahler_zuordnungen.html': 32,
    'core/templates/fw/zahllauf.html': 86,
    'core/templates/modern_base.html': 5,
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
