"""Jede Team-Seite gehört zu einem Bereich des Menübands (DESIGN-04, DESIGN-03).

WARUM ES DIESEN WÄCHTER GIBT

Das Audit vom 28.10.2026 zählte 19 von 225 Team-Pfaden, auf denen im Menüband
nichts leuchtete: Betreibungen, Zählerstand, Verteilschlüssel, Dokumente,
Kommunikation, die 2FA-Seiten. Einer davon war ein Tippfehler
(`'nav': 'schaeden'` statt `'schadensfaelle'`, Schlüsselname im Menüband). Eine
View, die einen Schlüssel meldet, den keine Gruppe kennt, fällt nirgends auf:
Django liefert leer und schweigt (bekannte-fallen §9).

ZWEI SICHTEN AUF DIESELBE FRAGE

1. Statisch: Jeder Schlüssel, den der Programmtext als Zeichenkette an `nav`
   hängt, steht in einer Gruppe von `core/navigation.py` (oder in den
   Einstellungen). Das findet den Tippfehler, auch auf Seiten, die die zweite
   Sicht nicht aufruft.
2. Dynamisch: Alle `/neu/`- und `/konto/`-Adressen mit höchstens einem
   Parameter werden als Inhaber abgerufen; jede Team-Vollseite muss einen
   bekannten Schlüssel melden. Das findet die Seiten, die GAR KEINEN melden
   (`nav` fehlt im Kontext), und den Schlüssel, der nur aus einer Variablen
   kommt.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase
from django.urls import NoReverseMatch, get_resolver, reverse

from core.navigation import EINSTELLUNGEN_KEYS, nav_gruppen

from ._isolation import KEINE_OBJEKT_ID, MandantenFixture


def bekannte_schluessel():
    schluessel = set(EINSTELLUNGEN_KEYS)
    for g in nav_gruppen():
        schluessel |= set(g['alle_keys'])
    return schluessel


#: Seiten, die bewusst keinen Bereich markieren — mit Grund. Heute leer: Auch
#: die Suche und die Zwei-Faktor-Seiten haben einen Bereich bekommen.
OHNE_BEREICH = {}

#: Abgerufene Adressen sind Namen aus dem URL-Verzeichnis. Diese beiden
#: Präfixe sind die Team-Oberfläche (`/neu/…`) und die Kontoseiten, die ein
#: Teammitglied mit der Team-Kopfzeile sieht.
PRAEFIXE = ('neu/', 'konto/')

#: Verzeichnisse, deren Programmtext nach `nav`-Schlüsseln durchsucht wird.
WURZEL = Path(settings.BASE_DIR)
APPS = ('core', 'stweg', 'faelle', 'portfolio', 'crm', 'finance', 'rentals', 'tickets', 'mietprozess', 'benutzer')

NAV_LITERAL = re.compile(r"""(?:['"]nav['"]\s*:|\bnav\s*=)\s*['"]([A-Za-z_]*)['"]""")


def _programmdateien():
    for app in APPS:
        for pfad in (WURZEL / app).rglob('*.py'):
            teile = set(pfad.parts)
            if 'migrations' in teile or 'tests' in teile or pfad.name.startswith('test_') or 'management' in teile:
                continue
            yield pfad


class SchluesselSindBekanntTests(SimpleTestCase):
    """Sicht 1: Kein Schlüssel im Programmtext ohne Bereich."""

    def test_jeder_nav_schluessel_im_programm_steht_in_einer_gruppe(self):
        bekannt = bekannte_schluessel()
        gefunden, unbekannt = 0, []
        for pfad in _programmdateien():
            text = pfad.read_text(encoding='utf-8')
            for treffer in NAV_LITERAL.finditer(text):
                gefunden += 1
                schluessel = treffer.group(1)
                if schluessel not in bekannt and schluessel not in OHNE_BEREICH:
                    zeile = text.count('\n', 0, treffer.start()) + 1
                    unbekannt.append(f'{pfad.relative_to(WURZEL)}:{zeile} nav={schluessel!r}')
        self.assertGreater(gefunden, 100, 'auffällig wenige nav-Schlüssel gefunden: Suchmuster prüfen')
        self.assertEqual(unbekannt, [], 'Schlüssel ohne Menüband-Gruppe (Tippfehler?)')

    def test_der_tippfehler_schaeden_waere_aufgefallen(self):
        """Selbstprüfung des Suchmusters: Es erkennt den Fehler, um den es ging."""
        treffer = NAV_LITERAL.findall("ctx = {'nav': 'schaeden'}")
        self.assertEqual(treffer, ['schaeden'])
        self.assertNotIn('schaeden', bekannte_schluessel())
        self.assertIn('schadensfaelle', bekannte_schluessel())

    def test_jeder_menueeintrag_zeigt_auf_eine_aufloesbare_adresse(self):
        from django.urls import resolve
        for g in nav_gruppen():
            for ziel in [g['ziel']] + [it['ziel'] for it in g['items']]:
                with self.subTest(ziel=ziel):
                    resolve(ziel.split('?')[0])


def _adressen_mit_hoechstens_einem_parameter():
    """(Name, Parameter oder None) aller `/neu/`- und `/konto/`-Adressen, aus dem Verzeichnis."""
    gefunden = []
    for name, eintrag in get_resolver().reverse_dict.items():
        if not isinstance(name, str):
            continue
        for pfad, params in eintrag[0]:
            if pfad.startswith(PRAEFIXE) and len(params) <= 1:
                gefunden.append((name, params[0] if params else None))
            break
    return sorted(gefunden)


class JedePfadHatEinenBereichTests(TestCase):
    """Sicht 2: Jede abgerufene Team-Vollseite meldet einen Schlüssel der Gruppen."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def setUp(self):
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.a.benutzer)

    def test_jede_team_vollseite_liegt_in_einer_menueband_gruppe(self):
        bekannt = bekannte_schluessel()
        geprueft, ohne = 0, []
        for name, parameter in _adressen_mit_hoechstens_einem_parameter():
            try:
                if parameter is None:
                    pfad = reverse(name)
                elif parameter in KEINE_OBJEKT_ID:
                    continue
                else:
                    pfad = reverse(name, args=[self.a.objekt_fuer(parameter, name).pk])
            except (NoReverseMatch, LookupError):
                continue
            antwort = self.client.get(pfad)
            if antwort.status_code != 200 or 'text/html' not in antwort.get('Content-Type', ''):
                continue
            kontext = antwort.context
            if kontext is None or 'fw_nav_gruppen' not in kontext:
                continue                                       # keine Team-Seite mit Menüband
            # Vollseite = die Hülle `fw/base.html` ist beteiligt. Bruchstücke (Teil-
            # Vorlagen für die laufende Anzeige) und die Einbettung (Schublade, iframe,
            # `fw/base_embed.html`) tragen kein Menüband.
            if 'fw/base.html' not in {t.name for t in (antwort.templates or [])}:
                continue
            geprueft += 1
            nav = kontext.get('nav')
            if nav not in bekannt and name not in OHNE_BEREICH:
                ohne.append(f'{pfad} nav={nav!r}')
        self.assertGreater(geprueft, 120, 'auffällig wenige Seiten geprüft')
        self.assertEqual(ohne, [], f'{len(ohne)} von {geprueft} Seiten ohne Bereich im Menüband')


class StwegBehaeltDenBestandsfilterTests(TestCase):
    """DESIGN-03: Wer einen Bestand gewählt hat, verliert ihn beim Besuch von «Stockwerkeigentum» nicht."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def setUp(self):
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.a.benutzer)

    def test_stweg_seiten_tragen_den_bestand_in_hauptnavigation_und_menueband(self):
        lg = self.a.liegenschaft.pk
        seiten = [reverse('stweg_uebersicht'),
                  reverse('stweg_gemeinschaft', args=[self.a.stweg_liegenschaft.pk])]
        for pfad in seiten:
            with self.subTest(pfad=pfad):
                antwort = self.client.get(pfad, {'lg': lg})
                self.assertEqual(antwort.status_code, 200)
                self.assertEqual(antwort.context['lg_query'], f'?lg={lg}')
                inhalt = antwort.content.decode()
                # Hauptnavigation und Menüband führen den Filter weiter.
                self.assertIn(f'href="/neu/vertraege/?lg={lg}"', inhalt)
                self.assertIn(f'href="/neu/liegenschaften/?lg={lg}"', inhalt)
