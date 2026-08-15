"""Übergibt die bestehende Benutzertabelle an das neue Benutzermodell.

WARUM DAS NICHT ALS MIGRATION GEHT
----------------------------------
Sobald `AUTH_USER_MODEL` auf `benutzer.Benutzer` zeigt, hängen die 13 bereits
angewendeten Migrationen mit `swappable_dependency` formal an
`benutzer.0001_initial` — die auf einer Bestandsdatenbank nicht angewendet ist.
Djangos Konsistenzprüfung läuft **vor** der ersten Migration und bricht ab:

    InconsistentMigrationHistory: Migration admin.0001_initial is applied
    before its dependency benutzer.0001_initial

Keine Migration kann das lösen, weil die Prüfung vor allen Migrationen greift.
Deshalb dieser Command, und deshalb ruft `deploy.sh` ihn **vor** `migrate` auf.

WAS ER TUT
----------
Auf einer Bestandsdatenbank genau zweierlei, beides verlustfrei:

1. Die Spalte `user_id` in den beiden Zwischentabellen für Gruppen und
   Einzelrechte heisst künftig `benutzer_id` — Django leitet sie aus dem
   Modellnamen ab. Die Tabellennamen selbst bleiben, weil sie aus `db_table`
   folgen.
2. `benutzer.0001_initial` wird als angewendet eingetragen. Die Tabelle
   `auth_user` existiert bereits und wird nicht angefasst.

**Keine Datenzeile wird bewegt.** IDs, Passwort-Hashes, Gruppenmitgliedschaften,
Sitzungen und die 15 Fremdschlüssel bleiben, wie sie sind.

IDEMPOTENT
----------
Der Command läuft genau einmal wirklich. Danach — und auf jeder frischen
Datenbank, wo `migrate` die Tabelle selbst anlegt — ist er ein Leerlauf. Er darf
deshalb bei jedem Deploy mitlaufen.

RÜCKWEG
-------
`--rueckwaerts` macht beides rückgängig: Spalten zurückbenennen, den Eintrag aus
`django_migrations` löschen. Danach läuft die Anwendung wieder mit `auth.User`,
sobald `AUTH_USER_MODEL` aus den Settings genommen ist.

ROHES SQL — BEGRÜNDETE AUSNAHME
-------------------------------
Der Skill `mandantentrennung` verbietet `connection.cursor()` ausser im
begründeten Einzelfall mit Kommentar. Hier ist er begründet: Der Command
arbeitet ausschliesslich auf der **Schemaebene** — Spaltennamen und Djangos
eigene Buchführungstabelle. Er liest und schreibt keine Fachdaten, kennt kein
Modell und läuft ausdrücklich **vor** den Migrationen, also zu einem Zeitpunkt,
an dem das ORM den Zustand der Datenbank noch gar nicht abbilden kann. Ein
Manager wäre hier nicht bloss unnötig, er wäre nicht verwendbar.
"""
from django.core.management.base import BaseCommand
from django.db import connection

MIGRATION = ('benutzer', '0001_initial')

# Zwischentabelle -> Spalte alt/neu. Die Tabellennamen folgen aus
# Benutzer.Meta.db_table und ändern sich deshalb nicht.
SPALTEN = [
    ('auth_user_groups', 'user_id', 'benutzer_id'),
    ('auth_user_user_permissions', 'user_id', 'benutzer_id'),
]


def _tabellen(cursor):
    return set(connection.introspection.table_names(cursor))


def _spalten(cursor, tabelle):
    return {c.name for c in connection.introspection.get_table_description(cursor, tabelle)}


def _migration_eingetragen(cursor):
    cursor.execute(
        "SELECT COUNT(*) FROM django_migrations WHERE app = %s AND name = %s", MIGRATION
    )
    return cursor.fetchone()[0] > 0


class Command(BaseCommand):
    help = ('Übergibt die bestehende auth_user-Tabelle an benutzer.Benutzer. '
            'Idempotent — läuft bei jedem Deploy mit und tut nur beim ersten Mal etwas.')

    def add_arguments(self, parser):
        parser.add_argument('--rueckwaerts', action='store_true',
                            help='Übernahme rückgängig machen.')
        parser.add_argument('--trocken', action='store_true',
                            help='Nur anzeigen, was geschähe.')

    def handle(self, *args, **optionen):
        rueckwaerts = optionen['rueckwaerts']
        trocken = optionen['trocken']

        with connection.cursor() as cursor:
            tabellen = _tabellen(cursor)

            if 'auth_user' not in tabellen:
                self.stdout.write('Keine Tabelle auth_user — frische Datenbank, nichts zu tun.')
                return

            eingetragen = _migration_eingetragen(cursor)

            if rueckwaerts:
                self._rueckwaerts(cursor, tabellen, eingetragen, trocken)
                return

            if eingetragen:
                self.stdout.write('Übernahme bereits erfolgt — nichts zu tun.')
                return

            getan = []
            for tabelle, alt, neu in SPALTEN:
                if tabelle not in tabellen:
                    # Tabelle fehlt (sehr alte Datenbank) — migrate legt sie an.
                    continue
                spalten = _spalten(cursor, tabelle)
                if neu in spalten:
                    continue
                if alt not in spalten:
                    raise RuntimeError(
                        f'{tabelle} hat weder {alt} noch {neu}. Übernahme abgebrochen, '
                        f'damit nichts geraten wird.'
                    )
                if not trocken:
                    cursor.execute(f'ALTER TABLE "{tabelle}" RENAME COLUMN "{alt}" TO "{neu}"')
                getan.append(f'{tabelle}.{alt} → {neu}')

            if not trocken:
                cursor.execute(
                    'INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, %s)',
                    [*MIGRATION, self._jetzt()],
                )
            getan.append(f'{MIGRATION[0]}.{MIGRATION[1]} als angewendet eingetragen')

            vorsatz = '[trocken] ' if trocken else ''
            for zeile in getan:
                self.stdout.write(f'{vorsatz}{zeile}')
            self.stdout.write(self.style.SUCCESS(
                f'{vorsatz}Übernahme abgeschlossen — keine Datenzeile bewegt.'
            ))

    def _rueckwaerts(self, cursor, tabellen, eingetragen, trocken):
        vorsatz = '[trocken] ' if trocken else ''
        for tabelle, alt, neu in SPALTEN:
            if tabelle not in tabellen:
                continue
            spalten = _spalten(cursor, tabelle)
            if neu not in spalten:
                continue
            if not trocken:
                cursor.execute(f'ALTER TABLE "{tabelle}" RENAME COLUMN "{neu}" TO "{alt}"')
            self.stdout.write(f'{vorsatz}{tabelle}.{neu} → {alt}')
        if eingetragen and not trocken:
            cursor.execute(
                'DELETE FROM django_migrations WHERE app = %s AND name = %s', MIGRATION
            )
        if eingetragen:
            self.stdout.write(f'{vorsatz}{MIGRATION[0]}.{MIGRATION[1]} ausgetragen')
        self.stdout.write(self.style.SUCCESS(f'{vorsatz}Übernahme zurückgenommen.'))

    @staticmethod
    def _jetzt():
        from django.utils import timezone
        return timezone.now()
