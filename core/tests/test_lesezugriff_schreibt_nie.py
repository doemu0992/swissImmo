"""Die Rolle «Lesezugriff» ändert nirgends Daten, auch nicht mit gefülltem Formular (SICH-27d, SICH-31).

WARUM
`test_sicherheit` prüft statisch, dass Schreib-Views einen Dekorator haben, und `test_rbac` fährt die
Nicht-Team-Rollen (Mieter, Eigentümer, Hauswart) über alle Routen. Dazwischen blieb eine Lücke: die Rolle
mit der engsten Zusage, «darf nur lesen». Der Fremd-ID-Fuzz des Audits lief als Inhaber, und der leere POST
des Rollenlaufs trifft Views, die erst bei gefüllten Feldern schreiben.

Dieser Lauf schickt an JEDE POST-Route des Projekts (Pfad: Objekte der eigenen Verwaltung) einen Body mit allen
bekannten Feldern und misst danach die Tabellen, in die geschrieben wurde (`_koerper_ids._Schreiber`): Zeilen
neu, geändert oder gelöscht heisst, der Lesezugriff hat geschrieben. Gemessen wird der Bestand, nicht der
Statuscode (ein 302 sagt nichts).

AUSNAHMEN stehen in `DARF_AENDERN` (Route -> Modelle, deren bestehende Zeilen sich ändern dürfen, nie neu oder
gelöscht) und `OEFFENTLICH`, jeweils mit Grund. Die Listen werden nie länger, ohne dass jemand den Grund liest.

Gegenprobe: bei einer Schreib-View (z. B. `fw_pendenz_neu`) den Rollen-Dekorator auf `TEAM_ROLLEN` stellen,
und der Lauf wird rot (Protokoll im Commit).
"""
import json
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase

from crm.models import Mitgliedschaft

from . import _koerper_ids as k
from ._isolation import MandantenFixture

#: Routen, die ohne Anmeldung schreiben dürfen (nicht Gegenstand dieses Laufs; das Fremd-ID-Netz deckt sie ab).
OEFFENTLICH = {
    'public_report': 'QR-Aushang im Treppenhaus: legt anonym eine Schadenmeldung in der Verwaltung des Hauses an',
}

#: Was ein Lesezugriff ändern darf: Route -> Modelle, deren BESTEHENDE Zeilen sich ändern (nie neu, nie gelöscht).
DARF_AENDERN = {
    'fw_schaden_detail': {'tickets.SchadenMeldung'},   # markiert die Meldung beim Öffnen als gelesen (Zähler im Menü)
}


class LesezugriffSchreibtNieTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        cls.leser = get_user_model().objects.create_user(username='a_lesezugriff', password='x')
        Mitgliedschaft.alle_organisationen.create(
            benutzer=cls.leser, organisation=cls.a.organisation, rolle=Mitgliedschaft.ROLLE_LESEZUGRIFF)

    def setUp(self):
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.leser)
        self.felder = k.felder_fuer(self.a, self.a.benutzer, self.leser)
        self.bestand = k.Bestand(self.a.organisation)

    def _geschrieben(self, pfad, als_json=False):
        """Zeilen, die die Anfrage in Mandantentabellen angelegt, geändert oder gelöscht hat; danach zurückgerollt."""
        from django.db import transaction
        schreiber = k._Schreiber()

        class _Zurueck(Exception):
            pass

        ergebnis = {}
        try:
            with transaction.atomic():
                with mock.patch('requests.sessions.Session.request',
                                side_effect=requests.exceptions.ConnectionError('kein Netz im Test')):
                    with connection.execute_wrapper(schreiber):
                        if als_json:
                            antwort = self.client.post(pfad, json.dumps(self.felder), content_type='application/json')
                        else:
                            antwort = self.client.post(pfad, dict(self.felder))
                ergebnis['status'] = antwort.status_code
                aenderungen = []
                for tabelle in schreiber.tabellen:
                    modell = self.bestand.nach_tabelle.get(tabelle)
                    if modell is None:
                        continue
                    jetzt, vorher = self.bestand._lese(modell), self.bestand.zeilen[modell]
                    neu = [pk for pk in jetzt if pk not in vorher]
                    geaendert = [pk for pk in jetzt if pk in vorher and jetzt[pk] != vorher[pk]]
                    weg = [pk for pk in vorher if pk not in jetzt]
                    if neu or geaendert or weg:
                        aenderungen.append((modell._meta.label, len(neu), len(geaendert), len(weg)))
                ergebnis['aenderungen'] = aenderungen
                raise _Zurueck
        except _Zurueck:
            pass
        return ergebnis['status'], ergebnis['aenderungen']

    def _lauf(self, als_json=False):
        routen, _ungebunden = k.post_routen(self.a)
        self.assertGreater(len(routen), 400, 'auffällig wenige POST-Routen im Lauf')
        schreibt, abgewiesen = [], 0
        for name, pfad in routen:
            if name in k.OEFFENTLICH_BY_DESIGN or name in OEFFENTLICH:
                continue
            status, aenderungen = self._geschrieben(pfad, als_json)
            erlaubt = DARF_AENDERN.get(name, set())
            aenderungen = [a for a in aenderungen if not (a[0] in erlaubt and a[1] == 0 and a[3] == 0)]
            if aenderungen:
                schreibt.append((name, pfad, status, aenderungen[:3]))
            elif status in (302, 403):
                abgewiesen += 1
        return schreibt, abgewiesen

    def test_formular(self):
        schreibt, abgewiesen = self._lauf()
        self.assertGreater(abgewiesen, 200, 'der Lesezugriff wird kaum abgewiesen: Aufbau des Laufs kaputt?')
        self.assertEqual(schreibt, [], 'Lesezugriff hat geschrieben:\n' + '\n'.join(str(s) for s in schreibt[:15]))

    def test_json(self):
        schreibt, _ = self._lauf(als_json=True)
        self.assertEqual(schreibt, [], 'Lesezugriff hat (per JSON) geschrieben:\n' + '\n'.join(str(s) for s in schreibt[:15]))

    def test_der_nachweis_findet_ein_schreiben(self):
        """Gegenprobe zur Messung: Ein Inhaber, der dieselbe Route aufruft, MUSS als Schreiber erscheinen.

        Sonst bewiese ein grüner Lauf nur, dass die Messung nichts sieht (zum Beispiel, weil die Felder nie
        eine Zeile anlegen).
        """
        self.client.force_login(self.a.benutzer)
        beobachtet = {}
        routen, _ = k.post_routen(self.a)
        for name, pfad in routen:
            if name in ('fw_pendenz_neu', 'fw_kommunikation_neu', 'fw_liegenschaft_bearbeiten'):
                _status, aenderungen = self._geschrieben(pfad)
                beobachtet[name] = aenderungen
        self.assertTrue(any(beobachtet.values()),
                        f'Nicht einmal der Inhaber löst im Lauf eine Änderung aus: {beobachtet}')
