"""Die Mehrsprachigkeit — gemessen, nicht behauptet.

WAS E2 VERLANGT UND WO ES STAND

`docs/PLAN-V7.md` nennt fuer E2 zwei Haelften: den Vorlagendurchgang auf die
Komponentenschicht UND `{% trans %}` im selben Griff, mit dem Gate «.po fuer
DE vollstaendig, FR/IT/EN voruebersetzt». Die erste Haelfte war am 21.09.2026
praktisch fertig, die zweite hatte **nie begonnen**: Gemessen trugen genau
**1 von 177** Vorlagen ein `{% trans %}`, `locale/` enthielt nur `.gitkeep`,
und im Python-Code stand kein einziges `gettext`. Der Kommentar in
`settings.py` hielt denselben Stand schon zu Beginn von E2 fest — es hatte
sich seither nichts bewegt.

E2.85 macht den Anfang mit der Tranche «Heute» (`dashboard`, `zulauf`,
`termine`, `abwesenheiten`) — der Reihenfolge aus PLAN-V7 folgend, und
denselben vier Vorlagen, die schon bei der Komponentenschicht die ersten
waren.

WARUM DIESE DATEI DREI VERSCHIEDENE DINGE PRUEFT

Eine Uebersetzung kann an drei unabhaengigen Stellen kaputtgehen, und zwei
davon **lautlos**:

1. Die Vorlage traegt keine Auszeichnung  -> Text bleibt deutsch.
2. Der Katalog hat Luecken               -> Text faellt auf Deutsch zurueck.
3. Das `.mo` fehlt oder ist veraltet     -> ALLES bleibt deutsch, obwohl
   die `.po` vollstaendig aussieht.

Fall 3 ist der gefaehrlichste: `deploy.sh` ruft **kein** `compilemessages`
(nachgesehen am 21.09.2026 — es laeuft `migrate` und `collectstatic`).
Django liest aber `.mo`, nicht `.po`. Eine gepflegte `.po` ohne gebautes
`.mo` ist damit eine Uebersetzung, die es nur auf dem Papier gibt.

Deshalb liegen die `.mo` im Repo und werden hier gegen die `.po` geprueft —
dasselbe Muster wie `test_schicht_gebaut.py` fuer das erzeugte CSS.

WER EINE NEUE TRANCHE MACHT
    python manage.py makemessages -l de -l fr -l it -l en \\
        --ignore=node_modules --ignore=e2e --ignore=staticfiles
    # uebersetzen, dann:
    python manage.py compilemessages
    # und UEBERSETZT unten ergaenzen.

Dafuer braucht es `gettext` (msgfmt/xgettext) auf dem Rechner — in dieser
Umgebung war es nicht vorinstalliert.
"""
import gettext as gettext_modul
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import translation

WURZEL = pathlib.Path(settings.BASE_DIR)
LOCALE = WURZEL / 'locale'
SPRACHEN = ('de', 'fr', 'it', 'en')

#: Vorlagen, die bereits ausgezeichnet sind. Diese Liste darf nur WACHSEN —
#: dieselbe Sperrklinke wie beim Farbklassen-Zaehler, nur andersherum.
UEBERSETZT = (
    'fw/abwesenheiten.html',
    'fw/dashboard.html',
    'fw/fall_detail.html',
    'fw/termine.html',
    'fw/zulauf.html',
    'fw/_arbeitsvorrat_abschnitte.html',
)

#: Eine Stichprobe je Vorlage, mit der erwarteten Fassung je Sprache.
#:
#: Absichtlich Text, den ein Mensch im Bildschirm sieht — kein Kunstwort.
#: Faellt eine Sprache auf Deutsch zurueck (fehlender Eintrag, fehlendes
#: `.mo`), schlaegt genau das hier fehl.
STICHPROBE = {
    'Abwesenheiten':      {'de': 'Abwesenheiten', 'fr': 'Absences',
                           'it': 'Assenze', 'en': 'Absences'},
    'Niemand abwesend.':  {'de': 'Niemand abwesend.', 'fr': "Personne n'est absent.",
                           'it': 'Nessuno assente.', 'en': 'Nobody is away.'},
    'Arbeitsvorrat':      {'de': 'Arbeitsvorrat', 'fr': 'Charge de travail',
                           'it': 'Carico di lavoro', 'en': 'Work queue'},
    'Kommende Termine':   {'de': 'Kommende Termine', 'fr': 'Rendez-vous à venir',
                           'it': 'Prossimi appuntamenti', 'en': 'Upcoming appointments'},
    'Zuletzt erledigt':   {'de': 'Zuletzt erledigt', 'fr': 'Traité récemment',
                           'it': 'Completati di recente', 'en': 'Recently done'},
    # Fallakte
    'Fortschritt':        {'de': 'Fortschritt', 'fr': 'Progrès',
                           'it': 'Progresso', 'en': 'Progress'},
    'Aufwand erfassen':   {'de': 'Aufwand erfassen', 'fr': 'Saisir le travail',
                           'it': 'Registrare il lavoro', 'en': 'Record effort'},
    'Buchen':             {'de': 'Buchen', 'fr': 'Enregistrer',
                           'it': 'Registrare', 'en': 'Book'},
    'Erledigt':           {'de': 'Erledigt', 'fr': 'Terminé',
                           'it': 'Completato', 'en': 'Done'},
    'Für diesen Fall sind keine Schritte angelegt.': {
        'de': 'Für diesen Fall sind keine Schritte angelegt.',
        'fr': "Aucune étape n'est définie pour ce dossier.",
        'it': 'Nessuna fase è definita per questa pratica.',
        'en': 'No steps are defined for this case.'},
    # Arbeitsvorrat
    'Läufe':              {'de': 'Läufe', 'fr': 'Processus', 'it': 'Processi', 'en': 'Processes'},
    'Termine':            {'de': 'Termine', 'fr': 'Rendez-vous', 'it': 'Appuntamenti', 'en': 'Appointments'},
    'Vertretung':         {'de': 'Vertretung', 'fr': 'Remplacement', 'it': 'Sostituzione', 'en': 'Replacement'},
    'Wartet auf Freigabe': {'de': 'Wartet auf Freigabe', 'fr': "En attente d'approbation", 'it': "In attesa di approvazione", 'en': 'Waiting for approval'},
}


def _po_eintraege(pfad):
    """msgid -> msgstr aus einer .po, Mehrzahl als msgid -> [form0, form1].

    Ein eigener Parser und keine Bibliothek: `polib` waere eine Abhaengigkeit
    fuer dreissig Zeilen. Er kann genau so viel, wie diese Kataloge brauchen —
    mehrzeilige Zeichenketten und Mehrzahlformen.
    """
    eintraege = {}
    schluessel = None
    ziel = None
    puffer = {}
    for zeile in pfad.read_text(encoding='utf-8').split('\n'):
        zeile = zeile.strip()
        if zeile.startswith('#') or not zeile:
            continue
        m = re.match(r'^(msgid|msgid_plural|msgstr(?:\[\d\])?) "(.*)"$', zeile)
        if m:
            marke, text = m.group(1), m.group(2)
            if marke == 'msgid':
                if schluessel is not None:
                    eintraege[schluessel] = puffer
                schluessel, puffer, ziel = text, {}, 'msgid'
            else:
                ziel = marke
                puffer[marke] = text
            continue
        f = re.match(r'^"(.*)"$', zeile)
        if f and ziel:
            if ziel == 'msgid':
                schluessel += f.group(1)
            else:
                puffer[ziel] = puffer.get(ziel, '') + f.group(1)
    if schluessel is not None:
        eintraege[schluessel] = puffer
    eintraege.pop('', None)          # Dateikopf
    return eintraege


class KatalogTests(SimpleTestCase):

    def test_jede_sprache_hat_einen_katalog(self):
        fehlend = [s for s in SPRACHEN
                   if not (LOCALE / s / 'LC_MESSAGES' / 'django.po').exists()]
        self.assertEqual(
            fehlend, [],
            f'Ohne Katalog gibt es fuer diese Sprachen keine Uebersetzung: {fehlend}. '
            'Anlegen mit `manage.py makemessages -l <sprache>`.')

    def test_die_sprachen_stimmen_mit_den_einstellungen_ueberein(self):
        """Ein Katalog, den `LANGUAGES` nicht kennt, wird nie ausgeliefert."""
        eingestellt = {code for code, _ in settings.LANGUAGES}
        self.assertEqual(
            set(SPRACHEN), eingestellt,
            'settings.LANGUAGES und die Kataloge hier laufen auseinander.')

    def test_kein_eintrag_ist_unuebersetzt(self):
        """Das Gate aus PLAN-V7, mechanisch geprueft.

        DEUTSCH IST MITGEZAEHLT, obwohl es die Ausgangssprache ist und ein
        leerer `msgstr` dort auf die `msgid` zurueckfaellt — also gar nichts
        kaputtginge. Mit gefuelltem `de` sagt `msgfmt --statistics` fuer alle
        vier Sprachen dasselbe, und eine geaenderte deutsche Quelle markiert
        den Eintrag beim naechsten `makemessages` als `fuzzy`. Fuzzy ignoriert
        gettext — es faellt also weiterhin sauber auf die `msgid` zurueck,
        faellt aber jemandem auf.
        """
        for sprache in SPRACHEN:
            with self.subTest(sprache=sprache):
                pfad = LOCALE / sprache / 'LC_MESSAGES' / 'django.po'
                offen = [mid for mid, w in _po_eintraege(pfad).items()
                         if not any(v for k, v in w.items() if k.startswith('msgstr'))]
                self.assertEqual(
                    offen, [],
                    f'{len(offen)} Eintraege ohne Uebersetzung in {sprache}: '
                    f'{offen[:5]}')

    def test_das_mo_ist_gebaut_und_aktuell(self):
        """Der gefaehrlichste stille Fehler bekommt einen lauten Test.

        `deploy.sh` ruft kein `compilemessages`; Django liest `.mo`. Eine
        gepflegte `.po` ohne passendes `.mo` ist deshalb eine Uebersetzung,
        die nur im Quelltext existiert.

        Verglichen werden die EINTRAEGE, nicht die Bytes: Zwei msgfmt-Fassungen
        duerfen dieselbe Tabelle verschieden ablegen.
        """
        for sprache in SPRACHEN:
            with self.subTest(sprache=sprache):
                mo = LOCALE / sprache / 'LC_MESSAGES' / 'django.mo'
                self.assertTrue(
                    mo.exists(),
                    f'{mo.relative_to(WURZEL)} fehlt — `manage.py compilemessages` '
                    'laufen lassen und mitcommitten.')
                with mo.open('rb') as f:
                    gebaut = gettext_modul.GNUTranslations(f)._catalog
                quelle = _po_eintraege(LOCALE / sprache / 'LC_MESSAGES' / 'django.po')
                fehlend = [mid for mid, w in quelle.items()
                           if 'msgstr' in w and w['msgstr'] and mid not in gebaut]
                self.assertEqual(
                    fehlend, [],
                    f'Das .mo fuer {sprache} ist aelter als die .po — '
                    f'{len(fehlend)} Eintraege fehlen darin, z.B. {fehlend[:3]}. '
                    '`manage.py compilemessages` laeuft nicht im Deploy.')


class AusgezeichneteVorlagenTests(SimpleTestCase):

    def test_die_tranche_traegt_die_auszeichnung(self):
        """`{% load i18n %}` UND mindestens ein `{% trans %}`/`{% blocktrans %}`.

        Beides, weil das eine ohne das andere nichts tut: Ein `{% trans %}`
        ohne `{% load i18n %}` ist ein Vorlagenfehler, ein `{% load i18n %}`
        ohne Auszeichnung ist eine Zeile ohne Wirkung.

        ALLE VIER SCHREIBWEISEN: Django kennt `trans`/`blocktrans` und die
        neueren `translate`/`blocktranslate`. Der erste Entwurf dieses Tests
        suchte nur die kurzen — aufgefallen an `admin/base.html`, das
        `{% translate 'Home' %}` traegt und damit unbemerkt durchgefallen
        waere. Ein Waechter, der eine gueltige Schreibweise nicht kennt,
        laesst genau die durch.
        """
        for name in UEBERSETZT:
            with self.subTest(vorlage=name):
                text = (WURZEL / 'core' / 'templates' / name).read_text(encoding='utf-8')
                self.assertRegex(
                    text, r'{%\s*load[^%]*\bi18n\b',
                    f'{name} zeichnet Text aus, laedt aber `i18n` nicht.')
                self.assertRegex(
                    text, r'{%\s*(trans|translate|blocktrans|blocktranslate)\b',
                    f'{name} steht in UEBERSETZT, traegt aber keine Auszeichnung.')

    def test_die_liste_schrumpft_nicht(self):
        """Sperrklinke: Eine einmal ausgezeichnete Vorlage bleibt es.

        Der umgekehrte Fall zum Farbklassen-Zaehler — dort darf eine Zahl nur
        kleiner werden, hier darf eine Liste nur laenger werden.
        """
        for name in UEBERSETZT:
            with self.subTest(vorlage=name):
                self.assertTrue(
                    (WURZEL / 'core' / 'templates' / name).exists(),
                    f'{name} ist verschwunden — dann gehoert sie auch hier raus.')

    def test_keine_vorlage_faellt_durch_die_liste(self):
        """Wer auszeichnet, traegt es hier ein — sonst prueft nichts es nach."""
        ausgezeichnet = set()
        for pfad in sorted((WURZEL / 'core' / 'templates' / 'fw').glob('*.html')):
            text = pfad.read_text(encoding='utf-8')
            if re.search(r'{%\s*(trans|translate|blocktrans|blocktranslate)\b', text):
                ausgezeichnet.add(f'fw/{pfad.name}')
        fehlend = sorted(ausgezeichnet - set(UEBERSETZT))
        self.assertEqual(
            fehlend, [],
            f'Diese Vorlagen sind ausgezeichnet, stehen aber nicht in '
            f'UEBERSETZT: {fehlend}. Eintragen, damit die Stichprobe sie deckt.')


class UebersetzungWirktTests(SimpleTestCase):

    def test_die_stichprobe_kommt_in_jeder_sprache_richtig_an(self):
        """Der Test, der wirklich zaehlt: gettext ueber den gebauten Katalog.

        Nicht die `.po` gelesen, sondern uebersetzt — damit haengt dieser Test
        an derselben Kette wie die Anwendung: Katalog, `.mo`, `LOCALE_PATHS`.
        """
        for quelle, erwartet in STICHPROBE.items():
            for sprache, soll in erwartet.items():
                with self.subTest(sprache=sprache, text=quelle):
                    with translation.override(sprache):
                        self.assertEqual(
                            translation.gettext(quelle), soll,
                            f'«{quelle}» kommt auf {sprache} als '
                            f'«{translation.gettext(quelle)}» an, erwartet «{soll}».')

    def test_eine_andere_sprache_ist_wirklich_eine_andere(self):
        """Gegenprobe gegen den haeufigsten stillen Fehler.

        Faellt eine Sprache auf Deutsch zurueck — fehlendes `.mo`, falscher
        `LOCALE_PATHS`, Tippfehler im Sprachcode —, sind die Tests oben
        trotzdem gruen, solange das deutsche Wort zufaellig passt. Deshalb
        hier ausdruecklich: Franzoesisch darf nicht Deutsch sein.
        """
        with translation.override('fr'):
            franzoesisch = translation.gettext('Abwesenheiten')
        self.assertNotEqual(
            franzoesisch, 'Abwesenheiten',
            'Franzoesisch liefert den deutschen Text — der Katalog greift nicht.')
