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
            if typ not in TEMPLATES:
                continue
            template, praefix = TEMPLATES[typ]
            vorhanden = panels(template, praefix)
            for alt in alte:
                with self.subTest(typ=typ, reiter=alt):
                    self.assertIn(
                        alt, vorhanden,
                        f'{template} hat kein Panel {praefix}-{alt}.')

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

        Gemessen am 19.08.2026 fehlen: Liegenschaft 4, Mietverhältnis 4,
        Objekt 6, Person 4, Schaden 5 Panels.
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
