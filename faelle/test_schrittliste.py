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


class MonatswahlUndZuruecknehmenTests(_Basis):
    """Modul 5, zweiter Teil: Monatswahl, «Monat in Zahlen», Überspringen zurücknehmen."""

    def _vormonat(self):
        from django.utils import timezone
        erster = timezone.localdate().replace(day=1)
        index = erster.year * 12 + erster.month - 2
        return erster.replace(year=index // 12, month=index % 12 + 1)

    def test_ohne_wahl_steht_der_laufende_monat_und_es_geht_nicht_vorwaerts(self):
        antwort = self.c.get('/neu/laeufe/')
        self.assertTrue(antwort.context['monat_ist_aktuell'])
        self.assertEqual(antwort.context['monat_nach_url'], '')
        self.assertIn('zahlen', antwort.context)

    def test_ein_frueherer_monat_zeigt_nur_seine_laeufe(self):
        vor = self._vormonat()
        periode = f'{vor.year}-{vor.month:02d}'
        vorlage = Lauf.alle_organisationen.filter(periode=PERIODE).first()
        alt = Lauf(organisation=vorlage.organisation, laufart=vorlage.laufart, periode=periode,
                   faellig_am=vor, status=Lauf.OFFEN)
        alt.save()
        antwort = self.c.get(f'/neu/laeufe/?monat={periode}')
        self.assertEqual(antwort.status_code, 200)
        self.assertFalse(antwort.context['monat_ist_aktuell'])
        self.assertEqual(antwort.context['monat'], vor)
        laeufe = [s['lauf'] for s in antwort.context['schritte'] if not s.get('abschluss')]
        self.assertEqual({lauf.periode for lauf in laeufe}, {periode})
        # Gegenprobe: vorwärts führt zurück auf den laufenden Monat (ohne Parameter).
        self.assertNotIn('monat=', antwort.context['monat_nach_url'])
        self.assertTrue(antwort.context['monat_nach_url'])

    def test_unsinn_und_zukunft_fallen_auf_den_laufenden_monat(self):
        for wert in ('abc', '2026-13', '2999-01', ''):
            antwort = self.c.get('/neu/laeufe/', {'monat': wert})
            self.assertEqual(antwort.status_code, 200, wert)
            self.assertTrue(antwort.context['monat_ist_aktuell'], wert)

    def test_uebersprungen_steht_als_uebersprungen_da_und_laesst_sich_zuruecknehmen(self):
        lauf = Lauf.alle_organisationen.filter(periode=PERIODE).first()
        self.c.post(f'/neu/laeufe/{lauf.pk}/ueberspringen/', {'bemerkung': 'keine offenen Posten'})
        lauf.refresh_from_db()
        self.assertEqual(lauf.status, Lauf.UEBERSPRUNGEN)
        antwort = self.c.get('/neu/laeufe/')
        self.assertContains(antwort, 'Übersprungen am')
        self.assertContains(antwort, 'keine offenen Posten')
        self.assertContains(antwort, f'/neu/laeufe/{lauf.pk}/zuruecksetzen/')
        # Ohne Begründung bleibt der Lauf übersprungen (Gegenprobe), mit Begründung ist er wieder offen.
        self.c.post(f'/neu/laeufe/{lauf.pk}/zuruecksetzen/', {'grund': ''})
        lauf.refresh_from_db()
        self.assertEqual(lauf.status, Lauf.UEBERSPRUNGEN)
        self.c.post(f'/neu/laeufe/{lauf.pk}/zuruecksetzen/', {'grund': 'doch offene Posten'})
        lauf.refresh_from_db()
        self.assertEqual(lauf.status, Lauf.OFFEN)
        self.assertNotContains(self.c.get('/neu/laeufe/'), 'Übersprungen am')
