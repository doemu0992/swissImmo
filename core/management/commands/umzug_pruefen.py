"""Passen die Daten überhaupt nach PostgreSQL? — die Prüfung VOR dem Umzug.

    python manage.py umzug_pruefen           # nur melden
    python manage.py umzug_pruefen --streng  # Exitcode 1 bei jedem Fund

DER UNTERSCHIED, DER DIESEN BEFEHL NÖTIG MACHT

SQLite erzwingt Spaltenbreiten **nicht**. `DecimalField(max_digits=10)` ist
dort eine Absichtserklärung: Wer 999'999'999'999.99 hineinschreibt, bekommt
sie gespeichert. `CharField(max_length=50)` ebenso. PostgreSQL erzwingt beides
und weist mit `numeric field overflow` bzw. `value too long` ab.

Ein Bestand, der auf SQLite jahrelang problemlos lief, kann deshalb beim
Umzug an einer einzigen Zeile scheitern — und zwar mitten im `loaddata`,
wenn die halbe Datenbank schon gefüllt ist.

GEFUNDEN AM 18.08.2026 in einem echten Umzugs-Probelauf: Zwei Zeilen in
`core_kreditorenrechnung` mit `betrag = 999999999999.99` bei
`max_digits=10, decimal_places=2` (erlaubt wären 99'999'999.99). Der Umzug
brach schon vorher ab — beim `dumpdata`, mit der Meldung

    CommandError: Unable to serialize database: [<class 'decimal.InvalidOperation'>]

Die sagt nicht, welches Modell, welche Zeile, welches Feld. Genau das leistet
dieser Befehl: Er nennt Tabelle, Primärschlüssel, Feld und Wert.

(Der Grund für die kryptische Meldung: Django setzt beim Lesen die
Decimal-Rechengenauigkeit auf `max_digits` und rundet dann — bei einem zu
grossen Wert wirft schon das `quantize`. Die betroffenen Zeilen sind damit
für Django ÜBERHAUPT nicht lesbar, auch im laufenden Betrieb nicht.)
"""
import decimal

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, models


class Command(BaseCommand):
    help = 'Prüft, ob alle Werte in ihre deklarierten Spaltenbreiten passen (vor dem Umzug).'

    def add_arguments(self, parser):
        parser.add_argument('--streng', action='store_true',
                            help='Bei Funden mit Code 1 enden (für Skripte).')

    def handle(self, *args, **optionen):
        vorhanden = set(connection.introspection.table_names())
        funde = []

        for modell in apps.get_models():
            tabelle = modell._meta.db_table
            if tabelle not in vorhanden:
                continue
            felder = [f for f in modell._meta.get_fields()
                      if isinstance(f, (models.DecimalField, models.CharField))
                      and getattr(f, 'concrete', False)]
            if not felder:
                continue
            funde += self._modell_pruefen(modell, felder)

        if not funde:
            self.stdout.write(self.style.SUCCESS(
                '✓ Alle Werte passen in ihre Spalten — PostgreSQL wird sie annehmen.'))
            return

        self.stdout.write(self.style.ERROR(
            f'✗ {len(funde)} Wert(e) passen NICHT in ihre deklarierte Spalte.\n'
            '  SQLite nimmt sie an, PostgreSQL weist sie ab. Vor dem Umzug bereinigen:\n'))
        for label, pk, feld, wert, grund in funde:
            self.stdout.write(f'  {label}  pk={pk}  {feld}')
            self.stdout.write(f'      Wert:  {wert!r}')
            self.stdout.write(f'      {grund}')
        self.stdout.write(
            '\n  Diese Zeilen sind fuer Django teils GAR NICHT lesbar — auch im '
            'laufenden Betrieb nicht.\n  Korrigieren oder loeschen, dann erneut pruefen.')
        if optionen['streng']:
            raise SystemExit(1)

    def _modell_pruefen(self, modell, felder):
        """Roh über SQL lesen — Djangos Konvertierung wirft ja gerade."""
        spalten = ', '.join('"%s"' % f.column for f in felder)
        try:
            with connection.cursor() as cur:
                cur.execute('SELECT "%s", %s FROM "%s"'
                            % (modell._meta.pk.column, spalten, modell._meta.db_table))
                zeilen = cur.fetchall()
        except Exception as fehler:                            # noqa: BLE001
            self.stderr.write(f'· {modell._meta.label} nicht lesbar: {fehler}')
            return []

        funde = []
        for zeile in zeilen:
            pk = zeile[0]
            for feld, wert in zip(felder, zeile[1:]):
                if wert is None:
                    continue
                grund = self._pruefen(feld, wert)
                if grund:
                    funde.append((modell._meta.label, pk, feld.name, wert, grund))
        return funde

    @staticmethod
    def _pruefen(feld, wert):
        if isinstance(feld, models.DecimalField):
            # Django liest mit einer Rechengenauigkeit von `max_digits` und
            # rundet auf `decimal_places`. Genau das hier nachstellen — sonst
            # findet die Pruefung andere Werte als der Umzug.
            kontext = decimal.Context(prec=feld.max_digits)
            try:
                kontext.create_decimal(str(wert)).quantize(
                    decimal.Decimal(1).scaleb(-feld.decimal_places), context=kontext)
            except decimal.InvalidOperation:
                erlaubt = decimal.Decimal(10) ** (feld.max_digits - feld.decimal_places)
                return (f'zu gross fuer max_digits={feld.max_digits}, '
                        f'decimal_places={feld.decimal_places} '
                        f'(erlaubt bis {erlaubt - decimal.Decimal(1).scaleb(-feld.decimal_places)})')
        elif isinstance(feld, models.CharField) and feld.max_length:
            if len(str(wert)) > feld.max_length:
                return (f'{len(str(wert))} Zeichen, erlaubt sind '
                        f'max_length={feld.max_length}')
        return None
