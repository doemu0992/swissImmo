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
#: **Das Objekt gehoert in die Angabe.** Ein blosses `/loeschen/` genuegt
#: nicht: Fast jede Akte fuehrt irgendwo ein Loeschen — Dokument, Anpassung,
#: Geraet. Eine Gegenprobe, die das Loeschen der PERSON entfernte, blieb
#: deshalb gruen, weil das Loeschen eines DOKUMENTS die Bedingung erfuellte.
PFLICHT = {
    'mietverhaeltnis': ('fw/vertrag_detail.html', [
        '/vertraege/{{ v.id }}/status/',      # Entwurf / Aktiv / Inaktiv
        '/vertraege/{{ v.id }}/bearbeiten/',
        '/vertraege/{{ v.id }}/kuendigen/',
        '/vertraege/{{ v.id }}/schlussabrechnung/',
        '/vertraege/{{ v.id }}/abnahme/neu/',
        '/vertraege/{{ v.id }}/maengelruege/',
        '/vertraege/{{ v.id }}/untermiete/',
        '/vertraege/{{ v.id }}/signieren/',
        '/vertraege/{{ v.id }}/loeschen/',
        '/vertraege/{{ v.id }}/kaution/',
        '/vertraege/{{ v.id }}/wg-mieter/',
        '/vertraege/{{ v.id }}/verzug/',
    ]),
    # Ergaenzt 20.08.2026, nachdem der Umbau des Aktenkopfs bei BEIDEN Typen
    # eine Aktion mitgenommen hatte: die Personenakte verlor «Loeschen» und
    # «DSG-Loeschung», die Schadensakte den Status-Schnellwechsel. Der Waechter
    # deckte bis dahin nur den Vertrag ab und konnte es deshalb nicht melden.
    'person': ('fw/person_detail.html', [
        '/personen/{{ m.id }}/bearbeiten/',
        '/personen/{{ m.id }}/loeschen/',
        '/personen/{{ m.id }}/dsg-loeschen/',
        '/kommunikation/',
    ]),
    'schaden': ('fw/schaden_detail.html', [
        '/schaeden/{{ t.id }}/status/',
        '/schaeden/{{ t.id }}/auftrag/',
        '/schaeden/{{ t.id }}/ausstattung/',
        '/schaeden/{{ t.id }}/loeschen/',
    ]),
}


def ziele(pfad):
    """Alle Zieladressen der Vorlage, ohne Abfrageteil."""
    quelle = (WURZEL / pfad).read_text(encoding='utf-8')
    return {z.split('?')[0]
            for z in re.findall(r'(?:action|href)="([^"]+)"', quelle)}


def fuehrt(vorhanden, teil):
    """Traegt die Vorlage eine Adresse, die auf `teil` ENDET?

    Nicht `teil in z`: Das war zu locker. `/loeschen/` steckt auch in
    `/dsg-loeschen/` — die Pflichtaktion «Person loeschen» galt deshalb als
    vorhanden, solange es die DSG-Loeschung gab, und ihre Gegenprobe blieb
    gruen. Der Abfrageteil faellt vorher weg, damit
    `/neu/kommunikation/?mieter=1` weiterhin auf `/kommunikation/` passt.
    """
    return any(z.endswith(teil) for z in vorhanden)


class AktionenTests(TestCase):
    def test_jede_pflichtaktion_ist_erreichbar(self):
        for typ, (pfad, pflicht) in PFLICHT.items():
            vorhanden = ziele(pfad)
            for teil in pflicht:
                with self.subTest(typ=typ, aktion=teil):
                    self.assertTrue(
                        fuehrt(vorhanden, teil),
                        f'{pfad} fuehrt keine Adresse mit {teil!r} mehr — '
                        f'die Aktion ist ueber die Oberflaeche nicht ausloesbar.')

    def test_eingebundene_bausteine_bleiben_eingebunden(self):
        """Aktionen in einem `{% include %}` sieht `ziele()` nicht.

        Beim Zusammenlegen der doppelten Fristenliste (4b.4) wanderte der
        Einschreiben-Baustein vom Finanz- in den Fallbereich der Personenakte.
        Er traegt das einzige Bedienelement fuer «Zugang bestaetigen» (strikte
        Empfangstheorie, Art. 257d OR). Faellt die Einbindung weg, verschwindet
        die Funktion — und die Adressenpruefung oben merkt nichts davon, weil
        `action=` in einer anderen Datei steht.
        """
        for pfad in ('fw/person_detail.html', 'fw/vertrag_detail.html', 'fw/fristen.html'):
            quelle = (WURZEL / pfad).read_text(encoding='utf-8')
            with self.subTest(vorlage=pfad):
                self.assertIn(
                    "include 'fw/_einschreiben_zugang.html'", quelle,
                    f'{pfad} bindet den Einschreiben-Baustein nicht mehr ein — '
                    f'«Zugang bestaetigen» ist dort nicht mehr ausloesbar.')
        # Und der Baustein selbst muss die Aktion noch fuehren.
        self.assertTrue(
            fuehrt(ziele('fw/_einschreiben_zugang.html'), '/zugang/'),
            'Der Baustein fuehrt kein /zugang/ mehr.')

    def test_die_pruefung_wuerde_einen_verlust_bemerken(self):
        """Gegenprobe: eine erfundene Aktion darf nicht als vorhanden gelten."""
        vorhanden = ziele(PFLICHT['mietverhaeltnis'][0])
        self.assertFalse(fuehrt(vorhanden, '/gibtsnicht/'))
        # Und die Trennschaerfe, an der die erste Fassung scheiterte:
        self.assertTrue(fuehrt(vorhanden, '/vertraege/{{ v.id }}/loeschen/'))
