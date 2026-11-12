"""Prüft, wie viel Macht die Datenbankrolle der Anwendung hat (nur PostgreSQL).

Die Trigger auf `core_buchung` und `core_aktivitaetslog` halten rohes SQL auf, nicht aber `TRUNCATE`,
`DROP TABLE` und `ALTER TABLE ... DISABLE TRIGGER`. Das darf, wer Superuser oder Eigentümer der Tabelle ist.
Läuft die Anwendung mit der Rolle, die die Tabellen angelegt hat (der Normalfall), ist der Schutz nur so stark wie
ihr Passwort. Diese Prüfung macht das sichtbar; die Abhilfe steht in `docs/AUTOMATISIERUNG.md` (Abschnitt «Datenbankrolle»).
"""
from django.db import connection

#: Tabellen, deren Schutz am Trigger hängt.
GESCHUETZT = ('core_buchung', 'core_aktivitaetslog')


def pruefen():
    """Liste der Befunde (Texte); leer = Rolle ist eingeschränkt. `None` auf Datenbanken ohne Rollen (SQLite)."""
    if connection.vendor != 'postgresql':
        return None
    befunde = []
    with connection.cursor() as c:
        c.execute('SELECT current_user, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user')
        rolle, superuser, createdb, createrole = c.fetchone()
        if superuser:
            befunde.append(f'Die Rolle «{rolle}» ist Superuser: Sie kann Trigger abschalten und jede Tabelle leeren.')
        elif createrole:
            befunde.append(f'Die Rolle «{rolle}» darf Rollen anlegen und kann sich damit weitere Rechte verschaffen.')
        for tabelle in GESCHUETZT:
            c.execute('SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = %s AND relkind = %s', [tabelle, 'r'])
            zeile = c.fetchone()
            if zeile is None:
                continue
            if zeile[0] == rolle:
                befunde.append(f'«{rolle}» ist Eigentümerin von {tabelle}: TRUNCATE, DROP und DISABLE TRIGGER sind erlaubt.')
            else:
                c.execute('SELECT has_table_privilege(current_user, %s, %s)', [tabelle, 'TRUNCATE'])
                if c.fetchone()[0]:
                    befunde.append(f'«{rolle}» hat TRUNCATE auf {tabelle}.')
    return befunde
