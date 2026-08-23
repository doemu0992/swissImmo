"""Die Vorprüfung des Umzugs — gefunden in einem echten Probelauf.

WIE DIESER TESTSATZ ENTSTANDEN IST

Am 18.08.2026 wurde der PostgreSQL-Umzug einmal vollständig durchgespielt:
echter PostgreSQL-Server, echter Bestand, `umzug_postgres.sh` von vorne bis
hinten. Er brach in Schritt 3 ab:

    CommandError: Unable to serialize database:
        [<class 'decimal.InvalidOperation'>]

Kein Modell, keine Zeile, kein Feld. Ursache waren zwei Datensätze mit
`betrag = 999999999999.99` in einem Feld `DecimalField(max_digits=10,
decimal_places=2)` — erlaubt wären 99'999'999.99.

DER GRUND, WARUM SO ETWAS ÜBERHAUPT IN DER DATENBANK STEHT: SQLite erzwingt
Spaltenbreiten **nicht**. `max_digits` und `max_length` sind dort
Absichtserklärungen. PostgreSQL erzwingt beide und weist mit `numeric field
overflow` bzw. `value too long` ab. Ein Bestand kann also jahrelang laufen und
beim Umzug an einer einzigen Zeile scheitern.

Gelesen hätte man das nie gefunden — die Zeilen sehen im Code unauffällig aus.
Nur ein Probelauf findet sie.

WARUM DIESE TESTS AUF POSTGRESQL ÜBERSPRUNGEN WERDEN (E0.3)

Sie legen absichtlich Daten an, die zu breit für ihre Spalte sind — genau die
Daten, die der Befehl finden soll. Auf PostgreSQL lässt sich dieser Zustand
nicht herstellen: Der Server weist schon das INSERT ab
(`StringDataRightTruncation`, `numeric field overflow`). Die Tests scheiterten
dort deshalb nicht am Befehl, sondern an ihrer eigenen Vorbereitung — fünf rote
Zeilen, die aussahen wie ein Fehler und keiner waren.

Dass sie auf PostgreSQL nicht laufen, ist kein Verlust, sondern der Beweis der
Aussage: Der Zustand, gegen den der Befehl schützt, kann dort nicht entstehen.
Geprüft wird er auf SQLite — also genau dort, wo der Bestand vor dem Umzug
liegt.
"""
from io import StringIO
from unittest import skipIf

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from ._isolation import MandantenFixture


@skipIf(connection.vendor == 'postgresql',
        'Zu breite Werte lassen sich auf PostgreSQL nicht anlegen — der '
        'Zustand, den dieser Befehl findet, entsteht nur unter SQLite.')
class UmzugPruefenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def pruefen(self, streng=False):
        raus = StringIO()
        call_command('umzug_pruefen', streng=streng, stdout=raus, stderr=raus)
        return raus.getvalue()

    def test_sauberer_bestand_meldet_nichts(self):
        self.assertIn('Alle Werte passen', self.pruefen())

    def _zu_grossen_betrag_einschmuggeln(self):
        """Am ORM vorbei — genau so entstehen solche Zeilen auch im Betrieb.

        Über `Model.objects.create()` liesse sich das gar nicht anlegen; die
        Validierung greift. In der Datenbank stehen sie trotzdem: aus einem
        Import, einer Datenmigration oder einem `cursor.execute`.
        """
        from finance.models import KreditorenRechnung

        with connection.cursor() as cur:
            cur.execute(
                'UPDATE "%s" SET betrag = 999999999999.99 WHERE id = %%s'
                % KreditorenRechnung._meta.db_table,
                [self.a.kreditor.pk])

    def test_zu_grosser_betrag_wird_gefunden(self):
        self._zu_grossen_betrag_einschmuggeln()
        ausgabe = self.pruefen()
        self.assertIn('passen NICHT', ausgabe)
        self.assertIn('finance.KreditorenRechnung', ausgabe)
        self.assertIn('betrag', ausgabe)

    def test_die_meldung_nennt_zeile_feld_und_grenzwert(self):
        # Die Meldung von `dumpdata` nannte nichts davon — deshalb gibt es
        # diesen Befehl überhaupt.
        self._zu_grossen_betrag_einschmuggeln()
        ausgabe = self.pruefen()
        self.assertIn(f'pk={self.a.kreditor.pk}', ausgabe)
        self.assertIn('max_digits=10', ausgabe)
        self.assertIn('99999999.99', ausgabe)

    def test_streng_endet_mit_fehlercode(self):
        # `umzug_postgres.sh` haengt daran: Ohne Exitcode liefe der Umzug
        # weiter und braeche erst beim `dumpdata` ab — dann aber ohne Hinweis,
        # WAS nicht passt.
        self._zu_grossen_betrag_einschmuggeln()
        with self.assertRaises(SystemExit):
            self.pruefen(streng=True)

    def test_ohne_streng_kein_fehlercode(self):
        # Zum blossen Nachsehen soll der Befehl nicht abbrechen.
        self._zu_grossen_betrag_einschmuggeln()
        self.pruefen()   # wirft nicht

    def test_zu_langer_text_wird_gefunden(self):
        # Dieselbe Falle bei CharField: SQLite kuerzt nicht, PostgreSQL weist ab.
        from crm.models import Mieter

        with connection.cursor() as cur:
            cur.execute('UPDATE "%s" SET nachname = %%s WHERE id = %%s'
                        % Mieter._meta.db_table,
                        ['X' * 500, self.a.mieter.pk])
        ausgabe = self.pruefen()
        self.assertIn('passen NICHT', ausgabe)
        self.assertIn('crm.Mieter', ausgabe)
        self.assertIn('max_length', ausgabe)
