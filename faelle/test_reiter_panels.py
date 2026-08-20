"""Jeder Reiter muss ein Panel haben, das es wirklich gibt.

WARUM DIESER TEST EXISTIERT

Das Aktenregister (`faelle.akten`) prüft, dass jeder **alte** Reiter ein Ziel im
neuen Satz hat. Das ist die halbe Frage. Die andere Hälfte ist, ob der neue
Reiter in der Oberfläche irgendwo ankommt — und die stellte niemand.

Konkret (19.08.2026): Ein Vorschlag stellte `fw_vertrag_detail` auf den
einheitlichen Satz um. `aus_alt` lieferte danach `chronik`, `stammdaten`,
`finanzen`, `dokumente`, `faelle`, `nebenkosten`. Das Template
`fw/vertrag_detail.html` führt aber `vt-uebersicht`, `vt-finanzen`,
`vt-mietzins`, `vt-schaeden`, `vt-pendenzen`, `vt-formulare`, `vt-dokumente`
und `vt-verlauf`.

`fwTab` in `base.html` blendet das Panel mit der ID `gruppe + '-' + name` ein.
Vier der sechs neuen Reiter hätten also auf nichts gezeigt: Ein Klick auf
«Chronik» hätte **alle** Panels ausgeblendet und eine leere Seite hinterlassen,
und die Inhalte von Mietzins, Schäden, Pendenzen, Formularen und Verlauf wären
über die Oberfläche nicht mehr erreichbar gewesen.

Alle Tests des Registers waren dabei grün — sie prüfen die Abbildungstabelle,
nicht die Oberfläche. Dieser Test schliesst die Lücke: Er liest die
tatsächlichen Panel-IDs aus dem Template und vergleicht sie mit den Reitern,
die eine Umstellung erzeugen würde.
"""
import pathlib
import re
from unittest import expectedFailure

from django.test import TestCase

from faelle.akten import AKTENTYPEN, aus_alt

#: Aktentyp → (Template, Präfix aus `{% include ... with gruppe=... %}`)
#: Nur die Typen, deren Detailseite heute schon eine Reiterleiste führt.
TEMPLATES = {
    'mietverhaeltnis': ('fw/vertrag_detail.html', 'vt'),
    'liegenschaft': ('fw/liegenschaft_detail.html', 'lg'),
    'objekt': ('fw/objekt_detail.html', 'obj'),
    'person': ('fw/person_detail.html', 'pd'),
    'schaden': ('fw/schaden_detail.html', 'sc'),
}

WURZEL = pathlib.Path('core/templates')

#: Typen, deren Template bereits auf den neuen Reitersatz umgebaut ist.
#: Bei ihnen sind die ALTEN Panel-Namen absichtlich verschwunden — sie werden
#: deshalb aus der Ist-Prüfung genommen und stattdessen streng gegen den NEUEN
#: Satz geprüft. Wächst diese Menge, schrumpft die Arbeitsliste von 4b.
UMGESTELLT = {'mietverhaeltnis', 'schaden', 'person', 'liegenschaft'}


def panels(template, praefix):
    """Die Panel-Namen, die dieses Template tatsächlich führt."""
    quelle = (WURZEL / template).read_text(encoding='utf-8')
    return {t for t in re.findall(rf'id="{praefix}-([a-z0-9_]+)"', quelle)}


class PanelTests(TestCase):
    def test_jedes_template_fuehrt_ueberhaupt_panels(self):
        """Ohne diesen Test wäre ein Tippfehler im Präfix ein stiller Freibrief.

        Findet die Abfrage nichts, wäre die Menge leer — und eine leere Menge
        besteht jede Teilmengenprüfung. Der eigentliche Test unten hinge dann in
        der Luft.
        """
        for typ, (template, praefix) in TEMPLATES.items():
            with self.subTest(typ=typ):
                self.assertTrue(
                    panels(template, praefix),
                    f'In {template} wurde kein einziges Panel mit dem Präfix '
                    f'{praefix!r} gefunden — stimmt der Präfix noch?')

    def test_heutige_reiter_haben_ihr_panel(self):
        """Der Ist-Zustand muss stimmen, sonst ist der Test unten wertlos."""
        from faelle.test_akten import HEUTE
        for typ, alte in HEUTE.items():
            if typ not in TEMPLATES or typ in UMGESTELLT:
                continue
            template, praefix = TEMPLATES[typ]
            vorhanden = panels(template, praefix)
            for alt in alte:
                with self.subTest(typ=typ, reiter=alt):
                    self.assertIn(
                        alt, vorhanden,
                        f'{template} hat kein Panel {praefix}-{alt}.')

    def test_umgestellte_typen_haben_jedes_neue_panel(self):
        """Für umgestellte Typen gilt die Zusage sofort und ohne Nachsicht.

        Dieser Test ist das Gegenstück zum `expectedFailure` unten: Was
        umgestellt ist, muss vollständig sein. Sonst wäre «umgestellt» eine
        Behauptung statt eines Zustands.
        """
        from faelle.test_akten import HEUTE
        for typ in sorted(UMGESTELLT):
            template, praefix = TEMPLATES[typ]
            vorhanden = panels(template, praefix)
            for reiter, _bez, _z in aus_alt(typ, HEUTE[typ]):
                with self.subTest(typ=typ, reiter=reiter):
                    self.assertIn(
                        reiter, vorhanden,
                        f'{template} hat kein Panel {praefix}-{reiter}, '
                        f'obwohl der Typ als umgestellt gilt.')

    def test_genau_das_erste_panel_ist_offen(self):
        """Beim Laden zeigt `_detail_tabs.html` den ersten Reiter als aktiv.

        Ist dessen Panel versteckt — oder sind zwei Panels offen — passt die
        Anzeige nicht zum Inhalt. Der erste Fall ergibt eine leere Seite, der
        zweite zwei Reiter untereinander. Beides fiel bis hierher durch jede
        Prüfung: Eine Gegenprobe am 19.08.2026 versteckte das Chronik-Panel,
        und alle sechs Tests blieben grün.
        """
        for typ in sorted(UMGESTELLT):
            template, praefix = TEMPLATES[typ]
            quelle = (WURZEL / template).read_text(encoding='utf-8')
            offen = re.findall(
                rf'<div data-panel="{praefix}" id="{praefix}-([a-z0-9_]+)"(?![^>]*hidden)',
                quelle)
            with self.subTest(typ=typ):
                self.assertEqual(
                    len(offen), 1,
                    f'{template} hat {len(offen)} sichtbare Panels '
                    f'({", ".join(offen) or "keines"}) — es muss genau eines sein.')
            from faelle.test_akten import HEUTE
            erster = aus_alt(typ, HEUTE[typ])[0][0]
            with self.subTest(typ=typ, erwartet=erster):
                self.assertEqual(
                    offen[:1], [erster],
                    f'Sichtbar ist {offen[:1]}, aktiv markiert wird aber '
                    f'{erster!r} — die Seite zeigt beim Laden das falsche Panel.')

    def test_umgestellte_typen_fuehren_keine_alten_panels_mehr(self):
        """Ein übriggebliebenes altes Panel wäre toter Inhalt: sichtbar im
        Quelltext, über keinen Reiter erreichbar."""
        from faelle.test_akten import HEUTE
        for typ in sorted(UMGESTELLT):
            template, praefix = TEMPLATES[typ]
            vorhanden = panels(template, praefix)
            neue = {e[0] for e in aus_alt(typ, HEUTE[typ])}
            uebrig = sorted(vorhanden - neue)
            with self.subTest(typ=typ):
                self.assertEqual(
                    uebrig, [],
                    f'{template} führt noch Panels, die kein Reiter mehr '
                    f'anspricht: {", ".join(uebrig)}')

    @expectedFailure
    def test_umstellung_erzeugt_nur_erreichbare_reiter(self):
        """Der eigentliche Wächter — **erwartet rot bis Phase 4b.**

        Solange die Templates die alten Panel-Namen führen, hat der neue
        Reitersatz dort kein Ziel. Das ist kein Versehen, sondern der Stand:
        Etappe 5a legt das Register an, die Templates folgen in 4b.

        `expectedFailure` statt Auskommentieren, aus zwei Gründen. Erstens
        bleibt die Meldung sichtbar — sie nennt jedes fehlende Panel je
        Template und ist damit die Arbeitsliste für 4b. Zweitens meldet Django
        einen **unerwarteten Erfolg** als Fehlschlag: Sobald die Templates
        umgestellt sind, wird der Lauf rot, und wer das behebt, muss diese
        Zeile entfernen. Ein auskommentierter Test bliebe dagegen für immer
        stumm.

        Gemessen am 19.08.2026 fehlten: Liegenschaft 4, Mietverhältnis 4,
        Objekt 6, Person 4, Schaden 5 Panels. Mietverhältnis ist seit Etappe
        5b umgestellt und steht in `UMGESTELLT`; die übrigen vier fehlen noch.
        """
        from faelle.test_akten import HEUTE
        fehlend = {}
        for typ, alte in HEUTE.items():
            if typ not in TEMPLATES:
                continue
            template, praefix = TEMPLATES[typ]
            vorhanden = panels(template, praefix)
            neue = {e[0] for e in aus_alt(typ, alte)}
            offen = sorted(neue - vorhanden)
            if offen:
                fehlend[typ] = (template, praefix, offen)

        meldung = '\n'.join(
            f'  {typ}: {tpl} hat keine Panels '
            + ', '.join(f'{prae}-{r}' for r in offen)
            for typ, (tpl, prae, offen) in sorted(fehlend.items()))
        self.assertEqual(
            fehlend, {},
            'Diese Reiter entstünden bei einer Umstellung, hätten in der '
            'Oberfläche aber kein Ziel — ein Klick darauf blendete alle Panels '
            'aus und hinterliesse eine leere Seite:\n' + meldung)

    def test_jeder_typ_mit_template_ist_im_register(self):
        for typ in TEMPLATES:
            with self.subTest(typ=typ):
                self.assertIn(typ, AKTENTYPEN)


class GerenderteSeiteTests(TestCase):
    """Der Nachweis am fertigen HTML — nicht an der Vorlage.

    Die Tests darüber lesen den Template-Quelltext. Das genügt für die
    Namensfrage, aber nicht für die Wirkung: Ein Panel in einem `{% if %}`,
    das zur Laufzeit falsch ist, steht im Quelltext und fehlt trotzdem auf der
    Seite. Dann zeigte der Reiter wieder ins Leere — und alle Prüfungen oben
    blieben grün.

    Dieser Test ruft die Seite auf und vergleicht, was wirklich ankommt.
    """

    @classmethod
    def setUpTestData(cls):
        from core.tests._isolation import MandantenFixture
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    #: Umgestellter Typ → (Adresse der Seite, Präfix). Waechst mit `UMGESTELLT`;
    #: `test_jede_umgestellte_seite_wird_auch_gerendert` unten haelt fest, dass
    #: keiner vergessen geht — sonst waere ein Typ «umgestellt», ohne dass je
    #: eine fertige Seite davon geprueft wurde.
    def _seiten(self):
        return {
            'mietverhaeltnis': (f'/neu/vertraege/{self.a.vertrag.pk}/', 'vt'),
            'schaden': (f'/neu/schaeden/{self.a.schaden.pk}/', 'sc'),
            'person': (f'/neu/personen/{self.a.mieter.pk}/', 'pd'),
            'liegenschaft': (f'/neu/liegenschaften/{self.a.liegenschaft.pk}/', 'lg'),
        }

    def test_jede_umgestellte_seite_wird_auch_gerendert(self):
        fehlend = sorted(UMGESTELLT - set(self._seiten()))
        self.assertEqual(
            fehlend, [],
            f'Diese Typen gelten als umgestellt, werden hier aber nie '
            f'aufgerufen: {", ".join(fehlend)}')

    def test_jeder_reiter_findet_sein_panel(self):
        from django.test import Client

        from core.tenancy import organisation_kontext as mandant
        for typ, (adresse, praefix) in sorted(self._seiten().items()):
            c = Client()
            c.force_login(self.a.benutzer)
            with mandant(self.a.organisation):
                antwort = c.get(adresse)
            with self.subTest(typ=typ):
                self.assertEqual(antwort.status_code, 200)
                html = antwort.content.decode()

                reiter = re.findall(
                    rf'data-tab="{praefix}" data-target="([a-z0-9_]+)"', html)
                vorhanden = set(re.findall(rf'id="{praefix}-([a-z0-9_]+)"', html))
                self.assertTrue(
                    reiter, 'Die Seite rendert überhaupt keine Reiterleiste.')
                self.assertEqual(
                    [r for r in reiter if r not in vorhanden], [],
                    'Diese Reiter erscheinen auf der Seite, ihr Panel aber '
                    'nicht — ein Klick blendet alles aus.')

                sichtbar = re.findall(
                    rf'<div data-panel="{praefix}" id="{praefix}-([a-z0-9_]+)"(?![^>]*hidden)',
                    html)
                self.assertEqual(
                    sichtbar, reiter[:1],
                    f'Beim Laden ist {sichtbar} offen, aktiv markiert ist aber '
                    f'{reiter[:1]}.')


class AktenkopfTests(TestCase):
    """Eine umgestellte Akte muss den Aktenkopf tragen, nicht nur den Reitersatz.

    WARUM ES DIESEN TEST GIBT

    Am 20.08.2026 galten Vertrag, Schaden und Person als «umgestellt», weil
    ihre Panels auf den einheitlichen Satz umbenannt waren. Die Personenakte
    trug aber weiterhin den alten Kopf: Tailwind-Kachel mit Initialen, darunter
    vier KPI-Kaesten. Vom Konzept war nichts zu sehen — kein `fw-aktenkopf`,
    kein Typ, kein Pfad, keine Zustands-Chips.

    Aufgefallen ist es dem Nutzer beim Vergleich mit dem Prototyp, nicht der
    Suite: `test_reiter_panels` prueft Panel-IDs, `test_akte_zustaende` prueft
    Rechnungen. Dass die Seite **aussieht** wie das Konzept, fragte niemand ab.

    Der Test prueft die Bausteine, die der Prototyp fuer JEDE Akte zeigt:
    Rahmen, Typzeile, Titel und Pfad. Die Kennzahlenleiste ist bewusst NICHT
    dabei — der Prototyp fuehrt sie fuer die Person nicht (siehe
    `KOPF_OHNE_KENNZAHLEN`).
    """

    #: Aktentypen, deren Prototyp keine Kennzahlenleiste zeigt. Fuer die Person
    #: ist das stimmig: Konto, Saldo und Kaution haengen am Mietverhaeltnis
    #: (G5). Vier Zahlen «zur Person» waeren Summen, die anderswo schon stehen.
    KOPF_OHNE_KENNZAHLEN = {'person'}

    @classmethod
    def setUpTestData(cls):
        from core.tests._isolation import MandantenFixture
        cls.a = MandantenFixture('K', '8000', 'Zürich')

    def _seiten(self):
        return {
            'mietverhaeltnis': f'/neu/vertraege/{self.a.vertrag.pk}/',
            'schaden': f'/neu/schaeden/{self.a.schaden.pk}/',
            'person': f'/neu/personen/{self.a.mieter.pk}/',
            'liegenschaft': f'/neu/liegenschaften/{self.a.liegenschaft.pk}/',
        }

    def test_jede_umgestellte_akte_wird_hier_geprueft(self):
        """Gegenprobe gegen die eigene Reichweite.

        Diese Liste stand als zweite, unabhaengige Aufzaehlung neben der in
        `GerenderteSeiteTests` — und ging beim Umbau der Liegenschaftsakte
        prompt vergessen. Die Folge waere gewesen: Ein Aktentyp gilt als
        umgestellt, sein Kopf wird nie geprueft, und eine Gegenprobe, die den
        Kopf komplett entfernt, bleibt gruen. Genau so ist es passiert (Lauf
        vom 20.08.2026, Mutation G5).
        """
        fehlend = sorted(UMGESTELLT - set(self._seiten()))
        self.assertEqual(
            fehlend, [],
            f'Diese Typen gelten als umgestellt, ihr Aktenkopf wird hier aber '
            f'nie geprueft: {", ".join(fehlend)}')

    def _html(self, adresse):
        from django.test import Client

        from core.tenancy import organisation_kontext as mandant
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            antwort = c.get(adresse)
        self.assertEqual(antwort.status_code, 200)
        return antwort.content.decode()

    @staticmethod
    def _aktenkopf(html):
        """Der Aktenkopf-Block allein — vom Rahmen bis zur Reiterleiste."""
        if 'class="fw-aktenkopf"' not in html:
            return ''
        return html.split('class="fw-aktenkopf"', 1)[1].split('class="fw-reiter"', 1)[0]

    def test_jede_umgestellte_akte_traegt_den_aktenkopf(self):
        for typ, adresse in sorted(self._seiten().items()):
            if typ not in UMGESTELLT:
                continue
            html = self._html(adresse)
            # Auf das KLASSENATTRIBUT pruefen, nicht auf den blossen Namen:
            # `base.html` traegt das Stylesheet inline, `fw-aktenkopf` steht
            # dort als CSS-Regel. Die erste Fassung fragte nur den Namen ab und
            # war damit auf jeder Seite wahr — sie bestand fuer die
            # Schadensakte, die gar keinen Aktenkopf hatte.
            for baustein, was in (('class="fw-aktenkopf"', 'der Rahmen'),
                                  ('class="fw-akte-typ"', 'die Typzeile'),
                                  ('class="fw-akte-oben"', 'der Kopfblock'),
                                  ('class="fw-akte-pfad"', 'der Pfad')):
                with self.subTest(typ=typ, baustein=baustein):
                    self.assertIn(
                        baustein, html,
                        f'{was} fehlt — die Seite fuehrt den Reitersatz, sieht '
                        f'aber nicht aus wie das Konzept.')

    def test_der_alte_kachelkopf_ist_fort(self):
        """Sonst stuenden beide Koepfe uebereinander und niemand merkte es."""
        for typ, adresse in sorted(self._seiten().items()):
            if typ not in UMGESTELLT:
                continue
            html = self._html(adresse)
            with self.subTest(typ=typ):
                self.assertNotIn(
                    'text-2xl font-extrabold text-slate-900', html,
                    'Der alte Tailwind-Kopf steht noch auf der Seite.')

    def test_die_ausnahme_ist_benannt_und_stimmt(self):
        """Wer eine Akte ohne Kennzahlen fuehrt, muss sie hier eintragen.

        Ohne diese Pruefung koennte man eine fehlende Kennzahlenleiste
        stillschweigend zur Ausnahme erklaeren.
        """
        for typ, adresse in sorted(self._seiten().items()):
            if typ not in UMGESTELLT:
                continue
            html = self._html(adresse)
            # NUR im Aktenkopf suchen. Die Schadensakte fuehrt im
            # Finanzen-Reiter ebenfalls eine `fw-kzn` — eine Gegenprobe, die
            # die Leiste aus dem KOPF entfernte, blieb deshalb gruen: der Test
            # fand die andere. Ein Ausschnitt, der zu viel umfasst, prueft
            # nicht mehr das, was er behauptet.
            kopf = self._aktenkopf(html)
            hat = 'class="fw-kzn"' in kopf
            with self.subTest(typ=typ):
                if typ in self.KOPF_OHNE_KENNZAHLEN:
                    self.assertFalse(
                        hat, f'{typ} steht als Ausnahme ohne Kennzahlenleiste, '
                             f'fuehrt jetzt aber eine — Eintrag entfernen.')
                else:
                    self.assertTrue(
                        hat, f'{typ} fuehrt keine Kennzahlenleiste. Wenn das '
                             f'Absicht ist, in KOPF_OHNE_KENNZAHLEN eintragen '
                             f'und im Konzept begruenden.')
