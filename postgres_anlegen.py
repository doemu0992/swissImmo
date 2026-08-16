#!/usr/bin/env python
"""Legt Rolle und Datenbank für swissImmo auf einem frischen PostgreSQL-Server an.

Django kann eine Datenbank nicht selbst erzeugen — `migrate` setzt voraus, dass
sie schon da ist. Dieser Schritt geschieht also genau einmal, von Hand. Dieses
Skript nimmt ihm die Fallen ab:

  · Die Datenbank bekommt die Anwendungs-Rolle als **Eigentümerin**. Das ist
    nicht Kosmetik: Seit PostgreSQL 15 darf eine beliebige Rolle im Schema
    `public` nichts mehr anlegen. Wer die Datenbank dem Superuser gibt und der
    Anwendung nur `GRANT ALL ON DATABASE`, bekommt beim ersten `migrate`
    `permission denied for schema public` — eine Meldung, die nach einem
    Django-Problem aussieht und keines ist. Als Eigentümerin hat die Rolle das
    Recht ohne jeden zusätzlichen GRANT.

  · Die Anwendung läuft nicht als Superuser. Ein Superuser kann fremde
    Datenbanken auf demselben Server lesen und Dateien des Systems anfassen.
    Für das, was swissImmo tut, braucht es das nie.

  · Passwörter werden abgefragt, nicht als Argument oder Umgebungsvariable
    übergeben. Beides landet sonst im Shell-Verlauf oder in der Prozessliste,
    wo andere sie lesen können.

Das Skript ist wiederholbar: Was schon da ist, wird gemeldet und übersprungen.
Es verändert eine bestehende Datenbank NICHT.

AUFRUF (Bash-Konsole, in der virtuellen Umgebung — `workon myenv`):

    python postgres_anlegen.py \\
        --host swissimmo-5420.postgres.pythonanywhere-services.com \\
        --port 15420
"""
import argparse
import getpass
import sys


def frage_passwort(text, bestaetigen=False):
    while True:
        eins = getpass.getpass(f'{text}: ')
        if not eins:
            print('  Leer ist kein Passwort.')
            continue
        if not bestaetigen:
            return eins
        zwei = getpass.getpass('  Zur Sicherheit nochmals: ')
        if eins == zwei:
            return eins
        print('  Die beiden stimmen nicht überein.')


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--host', required=True, help='Adresse des PostgreSQL-Servers.')
    p.add_argument('--port', required=True, help='Port des PostgreSQL-Servers.')
    p.add_argument('--admin', default='super', help='Verwaltende Rolle (Standard: super).')
    p.add_argument('--datenbank', default='swissimmo', help='Anzulegende Datenbank.')
    p.add_argument('--rolle', default='swissimmo_app', help='Anzulegende Anwendungs-Rolle.')
    a = p.parse_args()

    # Erst nach dem Parsen — sonst beantwortet nicht einmal `--help` etwas,
    # wenn die Konsole gerade nicht in der virtuellen Umgebung steht.
    try:
        import psycopg
        from psycopg import sql
    except ImportError:
        print('✗ psycopg fehlt. Erst `workon myenv`, dann `pip install -r requirements.txt`.',
              file=sys.stderr)
        return 1

    print(f'→ Ziel: {a.host}:{a.port}')
    print(f'  Datenbank «{a.datenbank}», Anwendungs-Rolle «{a.rolle}»\n')

    admin_pw = frage_passwort(f'Passwort der Rolle «{a.admin}»')

    # Verbindung auf `postgres` — die Verwaltungsdatenbank, die immer da ist.
    # `autocommit`, weil CREATE DATABASE nicht in einer Transaktion laufen darf.
    try:
        verbindung = psycopg.connect(
            host=a.host, port=a.port, user=a.admin, password=admin_pw,
            dbname='postgres', autocommit=True, connect_timeout=15)
    except psycopg.OperationalError as fehler:
        # Die häufigsten Ursachen benennen, statt die rohe Meldung stehen zu lassen.
        print(f'\n✗ Keine Verbindung: {fehler}', file=sys.stderr)
        print('  Häufigste Ursachen: Passwort für «super» auf der PythonAnywhere-Seite',
              file=sys.stderr)
        print('  noch nicht gesetzt, Server nicht gestartet, oder Adresse/Port vertippt.',
              file=sys.stderr)
        return 1

    with verbindung:
        cur = verbindung.cursor()

        # --- Rolle ---------------------------------------------------------
        cur.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (a.rolle,))
        if cur.fetchone():
            print(f'· Rolle «{a.rolle}» besteht bereits — unverändert gelassen.')
        else:
            rollen_pw = frage_passwort(f'Neues Passwort für «{a.rolle}»', bestaetigen=True)
            cur.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                sql.Identifier(a.rolle), sql.Literal(rollen_pw)))
            print(f'✓ Rolle «{a.rolle}» angelegt.')

        # --- Datenbank -----------------------------------------------------
        cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (a.datenbank,))
        if cur.fetchone():
            print(f'· Datenbank «{a.datenbank}» besteht bereits — NICHT angefasst.')
            print('  Ist sie leer, kann der Umzug weiterlaufen. Enthält sie schon Daten,')
            print('  erst klären, welche — loaddata würde sonst auf Bestehendes treffen.')
        else:
            # OWNER ist der springende Punkt (siehe Kopf der Datei).
            cur.execute(sql.SQL('CREATE DATABASE {} OWNER {} ENCODING {}').format(
                sql.Identifier(a.datenbank), sql.Identifier(a.rolle), sql.Literal('UTF8')))
            print(f'✓ Datenbank «{a.datenbank}» angelegt, Eigentümerin ist «{a.rolle}».')

    print()
    print('Nächster Schritt — diese Zeilen in DIESER Konsole setzen')
    print('(das Passwort selbst eintragen, es steht bewusst nicht hier):')
    print()
    print('  export DB_ENGINE=postgres')
    print(f'  export DB_NAME={a.datenbank}')
    print(f'  export DB_USER={a.rolle}')
    print("  export DB_PASSWORD='...'")
    print(f'  export DB_HOST={a.host}')
    print(f'  export DB_PORT={a.port}')
    print()
    print('Dann: bash umzug_postgres.sh')
    return 0


if __name__ == '__main__':
    sys.exit(main())
