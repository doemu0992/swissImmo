"""Prüft, ob die Datenbank die ist, auf die das Repo eingestellt ist.

Der Fall, gegen den das hier steht, ist auf PythonAnywhere kein Randfall,
sondern der Normalfall beim Umzug: Web-App, Always-on-Task und Bash-Konsole
haben **je eigene** Umgebungsvariablen. Setzt man `DB_ENGINE=postgres` nur im
Web-Tab, dann läuft die Website auf PostgreSQL — und der Deploy-Task migriert
weiter die SQLite-Datei. Er meldet Erfolg. Die Website sieht die Migration nie
und zeigt ab dem nächsten Feld einen `OperationalError` an.

Das ist ein Fehler, den niemand sieht, weil beide Seiten für sich betrachtet
funktionieren. Deshalb steht die Erwartung im Repo (`.datenbank-erwartet`) und
nicht in der Umgebung: Sie kommt mit dem Code mit, ist für alle Prozesse
dieselbe, und eine Abweichung fällt beim Deploy auf statt beim Kunden.

    python manage.py datenbank_pruefen

Endet mit Code 1 bei Abweichung. Fehlt die Datei, endet der Befehl mit 0 und
einem Hinweis — eine fehlende Erwartung soll keinen Deploy anhalten.

Dateiformat (`.datenbank-erwartet` im Projektordner), eine Angabe je Zeile,
`#` leitet einen Kommentar ein:

    engine = postgres          # Pflicht
    name   = swissimmo         # optional, nur geprüft wenn vorhanden
    host   = ...               # optional, nur geprüft wenn vorhanden
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

DATEINAME = '.datenbank-erwartet'

#: Django-Backend-Pfad → Kurzname. Nur die Motoren, die hier je in Frage kommen.
BACKENDS = {
    'django.db.backends.sqlite3': 'sqlite',
    'django.db.backends.postgresql': 'postgres',
    'django.db.backends.postgresql_psycopg2': 'postgres',
    'django.db.backends.mysql': 'mysql',
}

#: Schreibweisen, die in der Datei erlaubt sind.
SYNONYME = {
    'sqlite': 'sqlite',
    'sqlite3': 'sqlite',
    'postgres': 'postgres',
    'postgresql': 'postgres',
    'mysql': 'mysql',
}


def kurzname(engine: str) -> str:
    """`django.db.backends.postgresql` → `postgres`."""
    return BACKENDS.get(engine, engine.rsplit('.', 1)[-1])


def erwartung_lesen(pfad: Path) -> dict:
    """Liest die Datei zu einem Wörterbuch. Wirft bei kaputtem Inhalt."""
    erwartet = {}
    for nummer, roh in enumerate(pfad.read_text(encoding='utf-8').splitlines(), 1):
        zeile = roh.split('#', 1)[0].strip()
        if not zeile:
            continue
        if '=' not in zeile:
            raise CommandError(f'{DATEINAME}, Zeile {nummer}: erwartet «schlüssel = wert», gelesen «{roh.strip()}».')
        schluessel, wert = (teil.strip() for teil in zeile.split('=', 1))
        erwartet[schluessel.lower()] = wert
    if 'engine' not in erwartet:
        raise CommandError(f'{DATEINAME} nennt keinen «engine» — ohne den ist die Datei wirkungslos.')
    kurz = SYNONYME.get(erwartet['engine'].lower())
    if kurz is None:
        raise CommandError(
            f'{DATEINAME}: «{erwartet["engine"]}» ist kein bekannter Motor. '
            f'Erlaubt: {", ".join(sorted(set(SYNONYME)))}.')
    erwartet['engine'] = kurz
    return erwartet


class Command(BaseCommand):
    help = 'Vergleicht die tatsächliche Datenbank mit .datenbank-erwartet. Code 1 bei Abweichung.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--datei', metavar='PFAD',
            help=f'Abweichender Pfad zur Erwartungsdatei (Standard: {DATEINAME} im Projektordner).')

    def handle(self, *args, **optionen):
        pfad = Path(optionen['datei']) if optionen.get('datei') else Path(settings.BASE_DIR) / DATEINAME
        if not pfad.exists():
            self.stdout.write(f'· {pfad.name} nicht vorhanden — keine Erwartung hinterlegt, keine Prüfung.')
            return

        erwartet = erwartung_lesen(pfad)
        vorhanden = settings.DATABASES['default']
        tatsaechlich = {
            'engine': kurzname(vorhanden.get('ENGINE', '')),
            'name': str(vorhanden.get('NAME', '')),
            'host': str(vorhanden.get('HOST', '')),
        }

        abweichungen = [
            (schluessel, wert, tatsaechlich[schluessel])
            for schluessel, wert in erwartet.items()
            if schluessel in tatsaechlich and wert != tatsaechlich[schluessel]
        ]

        if not abweichungen:
            geprueft = ', '.join(f'{k}={erwartet[k]}' for k in ('engine', 'name', 'host') if k in erwartet)
            self.stdout.write(self.style.SUCCESS(f'✓ Datenbank wie erwartet ({geprueft}).'))
            return

        self.stderr.write(self.style.ERROR('✗ Diese Datenbank ist nicht die, auf die das Repo eingestellt ist.'))
        for schluessel, soll, ist in abweichungen:
            self.stderr.write(f'   {schluessel}: erwartet «{soll}», tatsächlich «{ist}»')
        self.stderr.write('')
        self.stderr.write('   Auf PythonAnywhere hat jeder Prozess eigene Umgebungsvariablen:')
        self.stderr.write('   Web-Tab, Always-on-Task und Konsole müssen getrennt gesetzt werden —')
        self.stderr.write('   und der Always-on-Task übernimmt neue Variablen erst nach einem Neustart.')
        self.stderr.write(f'   Ist der Wechsel gewollt, gehört er in {DATEINAME} — und zwar im Repo.')
        raise SystemExit(1)
