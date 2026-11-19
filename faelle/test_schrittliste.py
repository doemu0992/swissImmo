"""Monatsabschluss als Schrittliste (UI-Zielbild «Schritte in dieser Reihenfolge»).

Die Liste ist reine Darstellung der Läufe: offene Läufe plus die in diesem Monat abgeschlossenen, in Reihenfolge der Laufarten,
zuletzt der Periodenabschluss. Er ist gesperrt, solange ein Lauf offen ist.
"""
from faelle.lauf_models import Lauf
from faelle.test_monatsabschluss import PERIODE, _Basis


class SchrittlisteTests(_Basis):
    def _seite(self):
        antwort = self.c.get('/neu/laeufe/')
        self.assertEqual(antwort.status_code, 200)
        return antwort

    def test_offene_laeufe_sind_schritte_und_der_abschluss_ist_gesperrt(self):
        antwort = self._seite()
        schritte = antwort.context['schritte']
        laeufe = [s for s in schritte if not s.get('abschluss')]
        self.assertTrue(laeufe, 'Die geplanten Läufe stehen als Schritte da.')
        self.assertEqual([s['zustand'] for s in laeufe][0], 'jetzt')       # der erste offene ist der aktuelle
        self.assertTrue(all(s['zustand'] in ('jetzt', 'offen') for s in laeufe))
        self.assertEqual(schritte[-1]['zustand'], 'gesperrt')              # Periodenabschluss wartet
        self.assertContains(antwort, 'Schritte in dieser Reihenfolge')
        self.assertContains(antwort, 'Möglich, sobald')

    def test_reihenfolge_folgt_den_laufarten(self):
        laeufe = [s for s in self._seite().context['schritte'] if not s.get('abschluss')]
        folge = [(s['lauf'].laufart.reihenfolge, s['lauf'].faellig_am) for s in laeufe]
        self.assertEqual(folge, sorted(folge))

    def test_alle_erledigt_gibt_den_abschluss_frei(self):
        for lauf in Lauf.alle_organisationen.filter(periode=PERIODE):
            lauf.status = Lauf.UEBERSPRUNGEN
            lauf.abgeschlossen_am = __import__('django').utils.timezone.now()
            lauf.save()
        antwort = self._seite()
        schritte = antwort.context['schritte']
        self.assertEqual(schritte[-1]['zustand'], 'jetzt')
        self.assertEqual(antwort.context['schritte_erledigt'], len(schritte) - 1)
        self.assertContains(antwort, 'Abschliessen')
