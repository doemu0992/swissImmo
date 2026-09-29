"""Etappe 2 aus docs/AUDIT-SAAS-NIVEAU.md: Formulare, die Fehler zeigen.

Pilot ist die Liegenschaft. Vorher galt: Eine unlesbare Zahl wurde still als
leer gespeichert, eine fremde Betreuungsperson warf per Umleitung alle übrigen
Eingaben weg. Jetzt: Status 400, Meldung am Feld, Eingaben bleiben stehen,
nichts ist gespeichert.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, Client

from portfolio.models import Liegenschaft

from ._helfer import _team_user, _basis_objekte


GUELTIGE_IBAN = 'CH93 0076 2011 6238 5295 7'


# Der GWR-Abgleich fragt beim Bund nach (api3.geo.admin.ch). Ein Test darf das
# nicht — er haengt sonst am Netz und schickt Adressen nach draussen.
@patch('portfolio.services.sync_liegenschaft_with_gwr', return_value={})
class LiegenschaftFormular(TestCase):

    def setUp(self):
        self.lg, _e, _m, _v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())
        self.pfad = f'/neu/liegenschaften/{self.lg.id}/bearbeiten/'

    def _daten(self, **ueber):
        daten = {'strasse': 'Neue Strasse 5', 'plz': '8001', 'ort': 'Zürich', 'kanton': 'ZH',
                 'hkvo_grundkosten_prozent': '40'}
        daten.update(ueber)
        return daten

    def _fehler_am_feld(self, antwort, feld):
        body = antwort.content.decode()
        self.assertIn(f'id="id_{feld}_fehler"', body)
        self.assertIn(f'aria-describedby="id_{feld}_fehler"', body)
        return body

    def test_unlesbares_baujahr_wird_nicht_still_leer_gespeichert(self, _gwr):
        self.lg.baujahr = 1965
        self.lg.save()
        r = self.c.post(self.pfad, self._daten(baujahr='ca. 1970'))
        self.assertEqual(r.status_code, 400)
        body = self._fehler_am_feld(r, 'baujahr')
        # Die Eingabe steht noch da — auch die, die sich nicht speichern liess.
        self.assertIn('value="ca. 1970"', body)
        self.assertIn('value="Neue Strasse 5"', body)
        self.lg.refresh_from_db()
        self.assertEqual(self.lg.baujahr, 1965)
        self.assertEqual(self.lg.strasse, 'Teststrasse 1')

    def test_hkvo_anteil_ueber_100_prozent(self, _gwr):
        """Das Modell kennt keine Grenze; bisher hielt nur `max` im Browser."""
        r = self.c.post(self.pfad, self._daten(hkvo_aktiv='on', hkvo_grundkosten_prozent='140'))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'hkvo_grundkosten_prozent')

    def test_baujahr_tippfehler(self, _gwr):
        r = self.c.post(self.pfad, self._daten(baujahr='198'))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'baujahr')

    def test_keine_zahlenfelder_die_eingaben_verwerfen(self, _gwr):
        """`type="number"` verwirft im Browser jede Nicht-Zahl — nach einem
        Fehler stünde dort ein leeres Feld statt der Eingabe. Gemessen mit
        Chromium bei 390 px, bevor dieser Test entstand."""
        body = self.c.post(self.pfad, self._daten(baujahr='ca. 1970')).content.decode()
        self.assertNotIn('type="number"', body[body.index('<form method="post" class="max-w-3xl'):])
        self.assertIn('inputmode="numeric"', body)

    def test_unbekannte_heizart_ist_ein_fehler(self, _gwr):
        r = self.c.post(self.pfad, self._daten(heizsystem='kohleofen-xl'))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'heizsystem')

    def test_ungueltige_iban(self, _gwr):
        r = self.c.post(self.pfad, self._daten(iban='CH93 0076 2011 6238 5295 8'))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'iban')

    def test_plz_muss_vierstellig_sein(self, _gwr):
        r = self.c.post(self.pfad, self._daten(plz='80011'))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'plz')

    def test_pflichtfeld_leer(self, _gwr):
        r = self.c.post(self.pfad, self._daten(strasse=''))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'strasse')
        self.assertIn('role="alert"', r.content.decode())

    def test_fremde_betreuung_behaelt_die_uebrigen_eingaben(self, _gwr):
        """Vorher: Umleitung — und «Neue Strasse 5» war weg."""
        r = self.c.post(self.pfad, self._daten(betreut_von='999999'))
        self.assertEqual(r.status_code, 400)
        body = self._fehler_am_feld(r, 'betreut_von')
        self.assertIn('value="Neue Strasse 5"', body)
        self.lg.refresh_from_db()
        self.assertIsNone(self.lg.betreut_von_id)

    def test_unbekannter_eigentuemer_wird_nicht_still_geloescht(self, _gwr):
        r = self.c.post(self.pfad, self._daten(eigentuemer_id='999999'))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'eigentuemer_id')

    def test_gueltige_eingaben_werden_gespeichert(self, _gwr):
        r = self.c.post(self.pfad, self._daten(
            kanton='zh', verkehrswert="CHF 1'250'000.50", iban=GUELTIGE_IBAN,
            baujahr='1988', hkvo_grundkosten_prozent='', geak_klasse='c'))
        self.assertEqual(r.status_code, 302, r.content.decode()[:300])
        self.lg.refresh_from_db()
        self.assertEqual(self.lg.strasse, 'Neue Strasse 5')
        self.assertEqual(self.lg.kanton, 'ZH')
        self.assertEqual(self.lg.verkehrswert, Decimal('1250000.50'))
        self.assertEqual(self.lg.baujahr, 1988)
        self.assertEqual(self.lg.hkvo_grundkosten_prozent, 40)
        self.assertEqual(self.lg.geak_klasse, 'C')
        self.assertEqual(self.lg.iban, GUELTIGE_IBAN)
        self.assertEqual(self.lg.egid, '')

    def test_neu_anlegen_und_fehlerfall_legt_nichts_an(self, _gwr):
        vorher = Liegenschaft.objects.count()
        r = self.c.post('/neu/liegenschaften/neu/', self._daten(plz='x', gwr_import=''))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Liegenschaft.objects.count(), vorher)
        r = self.c.post('/neu/liegenschaften/neu/', {**self._daten()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Liegenschaft.objects.count(), vorher + 1)

    def test_betrag_ohne_tausendertrennzeichen_im_feld(self, _gwr):
        """Im Feld steht die Zahl so, wie sie wieder gespeichert werden kann."""
        self.lg.verkehrswert = Decimal('1250000.00')
        self.lg.save()
        body = self.c.get(self.pfad).content.decode()
        self.assertIn('value="1250000.00"', body)
