"""Keine Aktion darf beim Umbau verlorengehen.

WARUM

Beim Umbau des Aktenkopfs am 19.08.2026 verschwand der Statusumschalter
(Entwurf / Aktiv / Inaktiv) ersatzlos — er stand vor dem Bereich, den das
Umbauskript uebernahm. Die damalige Verlustpruefung zaehlte
`{% if %}`/`{% for %}`-Bloecke und meldete «nichts verloren»: Der Umschalter
besteht aus einem Formular mit drei Knoepfen, nicht aus Kontrollstrukturen.

Zaehlen ist die falsche Pruefung. Dieser Test vergleicht **Zieladressen** —
jedes `action=` und jedes `href=` auf eine Anwendungs-URL muss weiterhin
vorkommen. Eine Aktion, die niemand mehr ausloesen kann, ist verlorene
Funktion, egal wie gut die Seite aussieht.
"""
import pathlib
import re

from django.test import TestCase

WURZEL = pathlib.Path('core/templates')

#: Aktionen, die die Vertragsakte fuehren MUSS. Abgeschrieben aus dem Stand
#: vor dem Umbau. Wer eine streicht, muss das hier begruenden.
PFLICHT = {
    'mietverhaeltnis': ('fw/vertrag_detail.html', [
        '/status/',              # Entwurf / Aktiv / Inaktiv
        '/bearbeiten/',
        '/kuendigen/',
        '/schlussabrechnung/',
        '/abnahme/neu/',
        '/maengelruege/',
        '/untermiete/',
        '/signieren/',
        '/loeschen/',
        '/kaution/',
        '/wg-mieter/',
        '/verzug/',
    ]),
}


def ziele(pfad):
    quelle = (WURZEL / pfad).read_text(encoding='utf-8')
    return set(re.findall(r'(?:action|href)="([^"]+)"', quelle))


class AktionenTests(TestCase):
    def test_jede_pflichtaktion_ist_erreichbar(self):
        for typ, (pfad, pflicht) in PFLICHT.items():
            vorhanden = ziele(pfad)
            for teil in pflicht:
                with self.subTest(typ=typ, aktion=teil):
                    self.assertTrue(
                        any(teil in z for z in vorhanden),
                        f'{pfad} fuehrt keine Adresse mit {teil!r} mehr — '
                        f'die Aktion ist ueber die Oberflaeche nicht ausloesbar.')

    def test_die_pruefung_wuerde_einen_verlust_bemerken(self):
        """Gegenprobe: eine erfundene Aktion darf nicht als vorhanden gelten."""
        vorhanden = ziele(PFLICHT['mietverhaeltnis'][0])
        self.assertFalse(any('/gibtsnicht/' in z for z in vorhanden))
