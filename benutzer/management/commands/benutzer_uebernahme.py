"""Übergibt die bestehende Benutzertabelle an das neue Benutzermodell.

WARUM DAS NICHT ALS MIGRATION GEHT
----------------------------------
Sobald `AUTH_USER_MODEL` auf `benutzer.Benutzer` zeigt, hängen **16** bereits
angewendete Migrationen formal an `benutzer.0001_initial` — die auf einer
Bestandsdatenbank nicht angewendet ist. (Nicht 13: Zu den 13 Projektmigrationen
mit `swappable_dependency` kommen Djangos eigene `admin.0001_initial` sowie die
beiden, die dieser Schritt erzeugt hat. Der Wert stammt aus dem aufgelösten
Migrationsgraphen, nicht aus einer Textsuche.) Djangos Konsistenzprüfung läuft
**vor** der ersten Migration und bricht ab:

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

RÜCKWEG — DIE REIHENFOLGE IST NICHT BELIEBIG
--------------------------------------------
`--rueckwaerts` macht beides rückgängig: Spalten zurückbenennen, den Eintrag aus
`django_migrations` löschen.

**Erst der Command, dann der Code.** Zwischen beidem liegt ein Fenster, in dem
das ORM `auth_user_groups.benutzer_id` erwartet und die Datenbank `user_id`
hat: Die Anmeldung gelingt noch (`auth_user` ist unberührt), aber jede
Gruppenabfrage schlägt fehl — `/nach-login/` und alle `@rolle_erforderlich`-
Views liefern 500. Das ist fail-closed, nicht fail-open, aber es ist ein
Ausfall. Deshalb verlangt der Command `--code-wird-zurueckgerollt`, solange
`AUTH_USER_MODEL` noch auf dieses Modell zeigt.

**Wer den Code zuerst zurückrollt, hat kein Werkzeug mehr.** Nach einem
`git reset --hard` auf einen Stand vor Etappe 3 gibt es weder `AUTH_USER_MODEL`
noch diesen Command — nur eine Datenbank, deren M2M-Spalte `benutzer_id` heisst,
und dieselbe 500-Wand. Der Ausweg ist dann, den neuen Stand nochmals
auszuchecken, den Command zu fahren und erst danach zurückzurollen.

Der Eintrag in `django_migrations` muss ebenfalls in dieser Reihenfolge
verschwinden: Solange `AUTH_USER_MODEL` gesetzt ist, macht sein Löschen
`migrate` für alle 16 abhängigen Migrationen unbrauchbar. Erst wenn die Settings
zurückgenommen sind, wird `swappable_dependency` neu ausgewertet und der Graph
löst sich wieder auf.

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
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
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
        parser.add_argument('--code-wird-zurueckgerollt', action='store_true',
                            help='Bestätigt beim Rückweg, dass der Code unmittelbar danach auf '
                                 'einen Stand vor Etappe 3 zurückgeht.')
        parser.add_argument('--trocken', action='store_true',
                            help='Nur anzeigen, was geschähe.')

    def handle(self, *args, **optionen):
        rueckwaerts = optionen['rueckwaerts']
        trocken = optionen['trocken']

        # Der Rückweg hinterlässt ein Schema, das der laufende Code nicht mehr
        # versteht (siehe Modul-Docstring). Ohne ausdrückliche Bestätigung
        # nicht ausführen — sonst legt ein versehentlicher Aufruf die Anwendung
        # lahm, obwohl sie einwandfrei lief.
        if rueckwaerts and settings.AUTH_USER_MODEL == 'benutzer.Benutzer' \
                and not optionen['code_wird_zurueckgerollt'] and not trocken:
            raise CommandError(
                'AUTH_USER_MODEL zeigt noch auf benutzer.Benutzer. Der Rückweg macht die '
                'Anwendung dann sofort unbrauchbar (Gruppenabfragen laufen ins Leere). '
                'Reihenfolge: erst diesen Command mit --code-wird-zurueckgerollt, dann den '
                'Code zurückrollen. Nur ansehen: --trocken.'
            )

        self._pruefe_datenbank_kann_spalten_umbenennen()

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
    def _pruefe_datenbank_kann_spalten_umbenennen():
        """`ALTER TABLE … RENAME COLUMN` braucht SQLite ≥ 3.25 (2018).

        Es ist die einzige Anweisung, an der der ganze unbeaufsichtigte Deploy
        hängt. Scheitert sie mitten im Lauf, ist eine Spalte umbenannt und die
        andere nicht — deshalb vorher fragen statt hinterher aufräumen.
        PostgreSQL kann es seit jeher.
        """
        if connection.vendor != 'sqlite':
            return
        import sqlite3
        teile = tuple(int(t) for t in sqlite3.sqlite_version.split('.')[:2])
        if teile < (3, 25):
            raise CommandError(
                f'SQLite {sqlite3.sqlite_version} kann keine Spalten umbenennen '
                f'(nötig: 3.25 von 2018). Übernahme abgebrochen, bevor sie halb läuft.'
            )

    @staticmethod
    def _jetzt():
        from django.utils import timezone
        return timezone.now()
