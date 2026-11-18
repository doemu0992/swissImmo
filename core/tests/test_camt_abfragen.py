"""camt-Import ohne QR-Referenz: die Zahl der Abfragen wächst linear mit den Einträgen (Audit F8).

Gemessen am 18.11.2026: rund 15 Abfragen je Gutschrift (Duplikatprüfung, Auszugszeile, Zuordnung, Buchung auf das
Durchlaufkonto 1190). Ein Eintrag mehr kostet immer gleich viel, nicht mehr. Dieser Test hält das fest: wer die
Importschleife so umbaut, dass jede weitere Zeile teurer wird (eine Abfrage über alle bisherigen Zeilen), fällt hier auf.
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext

from .test_geld_parallel import GeldPfadBasis, _camt_datei

#: Obergrenze je Gutschrift; gemessen sind rund 15.
ABFRAGEN_JE_EINTRAG = 20


class CamtAbfragenTests(GeldPfadBasis):

    def _abfragen(self, n, praefix):
        datei = SimpleUploadedFile('a.xml', _camt_datei(n, praefix=praefix), content_type='text/xml')
        with CaptureQueriesContext(connection) as ctx:
            self.neuer_client().post('/neu/bankabgleich/camt-import/', {'camt_datei': datei})
        return len(ctx)

    def test_jede_weitere_gutschrift_kostet_gleich_viel(self):
        klein, mittel, gross = self._abfragen(5, 'A'), self._abfragen(15, 'B'), self._abfragen(30, 'C')
        je_eintrag_1 = (mittel - klein) / 10
        je_eintrag_2 = (gross - mittel) / 15
        self.assertLessEqual(je_eintrag_1, ABFRAGEN_JE_EINTRAG, f'{je_eintrag_1:.1f} Abfragen je Eintrag')
        self.assertLessEqual(je_eintrag_2, ABFRAGEN_JE_EINTRAG, f'{je_eintrag_2:.1f} Abfragen je Eintrag')
        # linear: der zweite Abschnitt kostet je Eintrag nicht mehr als der erste (kleine Toleranz)
        self.assertLessEqual(je_eintrag_2, je_eintrag_1 + 1, 'Die Kosten je Eintrag steigen mit der Zahl der Einträge.')
