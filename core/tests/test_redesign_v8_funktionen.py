"""Redesign v8: Jede Logik der alten Hülle und Startseite ist noch da.

WARUM

Das Redesign vom 30.09.2026 (`mockups/konzept-v8-cockpit.html`) hat
`fw/base.html`, `fw/dashboard.html`, `fw/_fwmodal.html` und die Portalhülle
neu geschrieben. Oberste Regel war: keine Funktion geht verloren. Vor dem
Umbau wurde jede Logikstelle der alten Hülle erhoben — Ids, Funktionen,
Ereignisse, Formulare, Speicherschlüssel, Endpunkte, Kontextwerte. Dieser
Test hält die Liste fest und prüft sie an den neuen Vorlagen.

Er prüft das VORHANDENSEIN im Quelltext (bzw. im gerenderten HTML), nicht das
Verhalten — das tun die Fachtests (test_mietprozess, test_pendenzen,
test_audit_etappe3, test_sprachwahl, test_mandant_wechsel, faelle.test_lage …).
Was hier steht, ist die Abhakliste, gegen die «kein Funktionsverlust» belegt
wurde; fällt ein Eintrag weg, wird es rot, bevor ein Fachtest es merkt.

GEGENPROBE: In `fw/base.html` `function fwNavToggle(` umbenennen → rot.
"""
import pathlib

from django.conf import settings
from django.test import SimpleTestCase, TestCase, Client

VORLAGEN = pathlib.Path(settings.BASE_DIR) / 'core' / 'templates'


def _quelle(name):
    return (VORLAGEN / name).read_text(encoding='utf-8')


#: Hülle der Anwendung — erhoben aus der alten `fw/base.html` (692 Zeilen).
HUELLE = {
    'Ids': [
        'id="fwBackdrop"', 'id="fwSidebar"', 'id="navgrp-', 'id="navsub-',
        'id="fwProfil"', 'id="fw-toasts"', 'fw-palette-data',
    ],
    'Funktionen': [
        'function fwToggleSidebar(', 'function fwOpenMobileNav(', 'function fwCloseMobileNav(',
        'function fwNavToggle(',
        'function fwProfilMenu(', 'function fwTab(', 'function fwTabellenStapeln(',
        'function fwSetTheme(', 'function fwSyncThemeButtons(',
    ],
    'Ereignisse und Mechanik': [
        "e.key === 'Escape'", "button[onclick=\"fwProfilMenu()\"]",
        "get('tab')", "addEventListener('submit'", "data-no-guard", "form.target === '_blank'",
        "'#z-laedt'", "'fw-dreht'", "[data-suche]", "[data-zeile]", "[data-menu-btn]",
        "[data-menu-list]", "addEventListener('fw:content'", "nodeName !== 'BR'",
        "data-persist", ":not([data-persist])", "setTimeout",
    ],
    # Die ⌘K-Palette als Fenster ist am 27.10.2026 in der Omnisearch der
    # Kopfzeile aufgegangen. Ihre Logik steht jetzt in `fw/_omnisearch.html` und
    # `static/js/fw-omnisearch.js` und wird unten (`OMNISEARCH_*`) geprüft; in
    # der Hülle bleiben nur die Daten (`fw-palette-data`, oben) und das Skript.
    'Omnisearch': [
        "{% include 'fw/_omnisearch.html' %}", "js/fw-omnisearch.js", 'fw-kopf-z1', 'fw-kopf-z2',
    ],
    'Speicher und frühe Skripte': [
        "localStorage.getItem('fw-theme')", "localStorage.setItem('fw-theme'",
        "localStorage.getItem('sbCollapsed')", "localStorage.setItem('sbCollapsed'",
        "classList.add('_sbc')", 'window.self !== window.top', "classList.add('_embed')",
        "get('embed') === '1'",
    ],
    'Formulare': [
        'action="/neu/mandant/"', 'name="organisation"', 'name="lg"',
        "core/_sprachwahl.html", '{% csrf_token %}',
    ],
    'Verweise': [
        '/neu/einstellungen/{{ lg_query }}', '/neu/dokumente/{{ lg_query }}',
        '/neu/kommunikation/{{ lg_query }}', 'href="/logout/"', '{{ g.ziel }}{{ lg_query }}',
        '{{ it.ziel }}{{ lg_query }}',
    ],
    'Kontextwerte': [
        'fw_mandant', 'fw_mandanten', 'fw_nav_gruppen', 'alle_liegenschaften', 'aktive_lg',
        'schaeden_ungelesen', 'fw_palette', 'fw_einstellungen_keys', 'nav in g.alle_keys',
        'nav in it.keys', 'g.badge', 'it.section', 'messages', 'ohne_emoji',
    ],
    'Bausteine': [
        "{% include 'fw/_assets.html' %}", "{% include 'fw/_schicht_link.html' %}",
        "{% include 'fw/_zeichen.html' %}", "{% include 'fw/_bestaetigen.html' %}",
        '{% block title %}', '{% block content %}', '{% block scripts %}',
        "aria-label=\"{% trans 'Bereiche' %}\"", 'aria-current="page"',
    ],
}

#: Die Omnisearch (früher ⌘K-Palette + Suchfeld) — Markup und Skript.
OMNISEARCH_MARKUP = [
    'id="fwOs"', 'id="fwOsEingabe"', 'id="fwOsListe"', 'id="fwOsPop"', 'id="fwOsFilter"', 'id="fwOsAlle"',
    'id="fwOsTexte"', 'action="{{ fw_suche_ziel|default:\'/neu/suche/\' }}"', 'name="q"', 'role="combobox"', 'role="listbox"',
    'aria-controls="fwOsListe"', 'data-palette-url="/neu/palette/"',
]
OMNISEARCH_SKRIPT = [
    "PALETTE_URL + '?q='", "'X-Requested-With': 'fetch'", 'MIN_ZEICHEN = 2', 'VERZOEGERUNG = 150',
    'AbortController', "SUCHE_URL + '?q='", 'fw-palette-data', '(e.metaKey || e.ctrlKey)',
    "e.key === 'k'", "e.key === 'Escape'", "'ArrowDown'", "'ArrowUp'", "e.key === 'Enter'",
    'aria-activedescendant', 'window.fwSucheOeffnen',
]

#: Die Schublade (früher Popup) — `fw/_fwmodal.html`.
SCHUBLADE = [
    'id="fwModal"', 'id="fwModalBox"', 'role="dialog"', 'aria-modal="true"',
    'aria-labelledby="fwModalTitle"', 'id="fwModalTitle"', 'id="fwModalZu"', 'id="fwModalLaedt"',
    'id="fwModalFrame"', 'function fwModalOpenUrl(', 'function fwModalOpen(', 'function fwModalClose(',
    'fwModalGetippt', 'fwModalLadungen', 'fwModalVorher', "'embed=1'", "e.data.fwModal === 'done'",
    'confirm(', 'window.location.reload()',
]

#: Startseite — Kontextwerte, Formulare und Verweise der alten `fw/dashboard.html`.
STARTSEITE = [
    # Der Zulauf-Knopf im Kopf ist seit dem zweiten Durchgang der Verweis
    # «Posteingang» in der Zulauf-Karte (wie im Mockup).
    'ansicht_titel', 'kw', 'vertretung_fuer', 'aktive_lg', 'href="/neu/zulauf/"',
    'name="wer"', 'name="mandat"', 'name="ansicht"', 'f_wer_auswahl', 'f_mandat_auswahl',
    'lg_streifen', 'delta_einheit', 'fw-trend', 'ansichten', 'f_query',
    'av_band', 'av_band_gesamt', 'f_query_ohne_fallart', 'fallart=', 'faelle', 'tage_ohne_bewegung',
    'vorrat', 'e.dringlichkeit', 'e.marke', 'e.nummer', 'e.fortschritt', 'e.schritt', 'e.wer',
    'e.wofuer', 'e.tage', 'e.ziel', 'e.modal', 'e.knopf', 'fwModalOpen(this',
    "{% include 'fw/_arbeitsvorrat_abschnitte.html'", 'av_eingaenge', 'av_eingaenge_gesamt',
    'z.sicher', 'z.fallart', 'inbox', 'inbox_mehr', 'e.chip_cls', 'e.cta', 'e.wide',
    '/neu/pendenzen/{{ lg_query }}', 'lg_mandate', 'm.belegung', 'lg_abweichungen',
    'lg_abweichungen_anzahl', '/neu/berichte/', "{% include 'fw/_fwmodal.html' %}",
    # Dashboard-Reduktion (26.10.2026): «Ausserdem» ist der Reiter «Ohne Frist»,
    # Freigaben und Läufe sind Aufgabenkacheln je Schwerpunkt; Schublade und Tastatur.
    "teil='ohnefrist'", "teil='rechts'", 'kacheln', 'k.zahl', 'k.knopf', 'schwerpunkte',
    '/neu/schwerpunkt/', 'termine_kurz',
    '/neu/fallschritte/{{ e.schritt_pk }}/erledigen/', '/neu/fallschritte/{{ e.schritt_pk }}/verschieben/',
    'fwVorgangAuf', 'fwVorgangZu', "e.key === 'j'", "e.key === 'k'", "e.key === 'e'",
]
# Läufe und Termine (sieben Tage) sind seit der Dashboard-Reduktion keine
# Abschnitte mehr: Läufe sind eine Kachel der Buchhaltung, Termine «Heute & morgen».
ABSCHNITTE = [
    'av_freigaben', 'av_liegezeit', '/neu/kreditoren/',
    'av_vertretung', 'vertretung_faelle', '/neu/abwesenheiten/', 'v.ungedeckt',
]

#: Portalhülle — `core/portal_base.html`.
PORTAL = [
    'id="pSidebar"', 'id="pBackdrop"', 'function pOpenNav(', 'function pCloseNav(',
    '{% block brand_icon %}', '{% block brand %}', '{% block brand_mobile %}', '{% block nav %}',
    '{% block content %}', '{% block footer %}', '{% block scripts %}', 'action="/logout/"',
    "core/_sprachwahl.html", "include 'core/_assets_aussen.html'",
]


class FunktionsinventarTests(SimpleTestCase):

    def _pruefe(self, datei, eintraege):
        quelle = _quelle(datei)
        fehlend = [e for e in eintraege if e not in quelle]
        self.assertEqual(fehlend, [], f'{datei}: diese Logikstellen fehlen seit dem Redesign: {fehlend}')

    def test_huelle(self):
        for gruppe, eintraege in HUELLE.items():
            with self.subTest(gruppe=gruppe):
                self._pruefe('fw/base.html', eintraege)

    def test_omnisearch(self):
        self._pruefe('fw/_omnisearch.html', OMNISEARCH_MARKUP)
        skript = (pathlib.Path(settings.BASE_DIR) / 'static' / 'js' / 'fw-omnisearch.js').read_text(encoding='utf-8')
        fehlend = [e for e in OMNISEARCH_SKRIPT if e not in skript]
        self.assertEqual(fehlend, [], f'fw-omnisearch.js: diese Logikstellen fehlen: {fehlend}')

    def test_schublade(self):
        self._pruefe('fw/_fwmodal.html', SCHUBLADE)

    def test_startseite(self):
        self._pruefe('fw/dashboard.html', STARTSEITE)

    def test_abschnitte_der_startseite(self):
        self._pruefe('fw/_arbeitsvorrat_abschnitte.html', ABSCHNITTE)

    def test_portalhuelle(self):
        self._pruefe('core/portal_base.html', PORTAL)

    def test_die_pruefung_greift(self):
        """Gegenprobe: Ein erfundener Eintrag muss als fehlend gemeldet werden."""
        with self.assertRaises(AssertionError):
            self._pruefe('fw/base.html', ['function gibtEsNicht('])


class GerendertTests(TestCase):
    """Dieselben Hooks im ausgelieferten HTML der Startseite (angemeldet)."""

    def test_startseite_liefert_huelle_omnisearch_und_schublade(self):
        from core.tests.test_debitoren import _team_user
        c = Client()
        c.force_login(_team_user())
        html = c.get('/neu/').content.decode('utf-8')
        for hook in ('id="fwSidebar"', 'id="fwOs"', 'fw-palette-data', 'id="fwModal"',
                     'id="fwBestaetigen"', 'aria-label="Bereiche"', 'name="lg"', 'name="q"',
                     'class="fw-schwerpunkt"', 'id="h-vorrat"', 'fw-reiter', 'fwThemeWechseln'):
            with self.subTest(hook=hook):
                self.assertIn(hook, html)
