"""Fremde IDs im Body mit den übrigen Team-Rollen (SICH-27d).

`FremdeIdImBodyTests` fährt den Fuzz für Inhaber, Verwalter und Sachbearbeiter. Die Rollen Buchhaltung,
Hauswart und Lesezugriff fehlten: Gerade Buchhaltung schreibt in die Geldtabellen (`konto_id`, `rechnung_id`,
`kreditor_id` im Body), Hauswart in Schäden und Aufträge. Ein Leck, das nur diese Rolle erreicht, blieb bei
grüner Suite unentdeckt (so fielen SICH-10/11/23 nicht auf).

Dieselbe Messung, dieselben Felder, nur andere Konten. Die geerbten Läufe der drei Standardrollen sind hier
abgeschaltet (sie laufen in `test_isolation`); sonst liefe der Fuzz doppelt.

Gegenprobe: in `fw_pendenz_neu` die Besitzprüfung der Liegenschaft ausbauen, dann werden die Läufe rot, soweit die
Rolle die Route erreicht (Protokoll im Commit).
"""
from django.contrib.auth import get_user_model
from django.test import Client

from crm.models import Mitgliedschaft

from .test_isolation import FremdeIdImBodyTests


MIN_BUCHHALTUNG = 80      # gemessen 120
MIN_HAUSWART = 30         # gemessen 58


class FremdeIdImBodyWeitereRollenTests(FremdeIdImBodyTests):

    # Geerbte Tests: laufen in FremdeIdImBodyTests, hier abgeschaltet.
    test_inhaber_formular = None
    test_verwalter_formular = None
    test_sachbearbeiter_formular = None
    test_inhaber_json = None
    test_der_lauf_erreicht_die_bekannten_loecher = None
    test_der_nachweis_findet_ein_leck = None
    test_das_netz_verhindert_die_zeile_in_b_auch_ohne_pruefung_in_der_ansicht = None
    test_ohne_kontext_gilt_das_netz_nicht = None
    test_die_fremde_liegenschaft_im_formular_legt_nichts_an = None
    test_die_eigene_liegenschaft_im_formular_geht_weiterhin = None
    test_abwesenheit_nur_fuer_das_eigene_team = None

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for rolle in (Mitgliedschaft.ROLLE_BUCHHALTUNG, Mitgliedschaft.ROLLE_HAUSWART,
                      Mitgliedschaft.ROLLE_LESEZUGRIFF):
            benutzer = get_user_model().objects.create_user(username=f'a_{rolle.lower()}', password='x')
            Mitgliedschaft.objects.create(benutzer=benutzer, organisation=cls.a.organisation, rolle=rolle)
            client = Client(raise_request_exception=False)
            client.force_login(benutzer)
            cls.clients[rolle] = client

    def _erreichte_routen(self, rolle):
        """Anzahl POST-Routen, bei denen die Rolle nicht schon am Rollen-Dekorator (403) scheitert."""
        routen, _ = self.k.post_routen(self.a)
        client = self.clients[rolle]
        return sum(1 for name, pfad in routen
                   if name not in self.k.OEFFENTLICH_BY_DESIGN
                   and self.k.sende(client, self.bestand, pfad, dict(self.felder))[0] != 403)

    def _pruefen(self, rolle, als_json=False):
        befunde, _ = self._lauf(rolle, als_json=als_json)
        self.assertEqual(befunde, [], f'{rolle}: Routen schreiben über die Mandantengrenze:\n'
                         + '\n'.join(str(b) for b in befunde[:10]))

    def test_buchhaltung_formular(self):
        self._pruefen(Mitgliedschaft.ROLLE_BUCHHALTUNG)

    def test_hauswart_formular(self):
        self._pruefen(Mitgliedschaft.ROLLE_HAUSWART)

    def test_lesezugriff_formular(self):
        self._pruefen(Mitgliedschaft.ROLLE_LESEZUGRIFF)

    def test_buchhaltung_json(self):
        self._pruefen(Mitgliedschaft.ROLLE_BUCHHALTUNG, als_json=True)

    def test_hauswart_json(self):
        self._pruefen(Mitgliedschaft.ROLLE_HAUSWART, als_json=True)

    def test_die_rollen_erreichen_ihre_routen(self):
        """Gegenprobe zur Reichweite: Ein Lauf, bei dem die Rolle überall am Dekorator scheitert, wäre grün und leer.

        Die Mindestzahlen sind gemessen (29.10.2026) und bewusst darunter angesetzt.
        """
        for rolle, mindestens in ((Mitgliedschaft.ROLLE_BUCHHALTUNG, MIN_BUCHHALTUNG),
                                  (Mitgliedschaft.ROLLE_HAUSWART, MIN_HAUSWART)):
            with self.subTest(rolle=rolle):
                self.assertGreaterEqual(self._erreichte_routen(rolle), mindestens)

    def test_die_weiteren_rollen_sind_angemeldet(self):
        """Selbstprüfung: Ein Client, der nicht angemeldet ist, bekäme überall 302 und der Lauf wäre grün."""
        for rolle in (Mitgliedschaft.ROLLE_BUCHHALTUNG, Mitgliedschaft.ROLLE_HAUSWART,
                      Mitgliedschaft.ROLLE_LESEZUGRIFF):
            with self.subTest(rolle=rolle):
                antwort = self.clients[rolle].get('/neu/')
                self.assertNotEqual(antwort.status_code, 404)
                self.assertNotIn('/login', antwort.headers.get('Location', ''))
