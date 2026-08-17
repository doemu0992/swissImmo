"""Zeilenzahlen je Modell — die Kontrolle vor und nach dem Datenbankumzug.

Ein Umzug, den niemand nachzählt, ist eine Hoffnung. Dieser Befehl schreibt
eine stabil sortierte Liste, die sich mit `diff` vergleichen lässt:

    python manage.py bestand_zaehlen > vorher.txt      # auf SQLite
    ... Umzug ...
    python manage.py bestand_zaehlen > nachher.txt     # auf Postgres
    diff vorher.txt nachher.txt && echo "identisch"

`--pruefe` vergleicht direkt gegen eine frühere Ausgabe und endet mit Code 1
bei Abweichung — damit lässt es sich in ein Skript hängen, das dann abbricht.

AUSGENOMMEN sind die Tabellen, die beim Umzug bewusst NICHT mitkommen:
`contenttypes` und `auth.Permission` legt Django auf der Zieldatenbank selbst
an (mit anderen IDs), `sessions` ist flüchtig, und `admin.LogEntry` verweist
auf ContentType. Sie zu übertragen erzeugt Kollisionen, sie wegzulassen kostet
nichts.
"""
from django.apps import apps
from django.core.management.base import BaseCommand

#: Nicht mitzählen — sie werden beim Umzug bewusst nicht übertragen.
AUSGENOMMEN = {
    'contenttypes.ContentType',
    'auth.Permission',
    'sessions.Session',
    'admin.LogEntry',
}


class Command(BaseCommand):
    help = 'Zeilenzahlen je Modell, stabil sortiert — zum Vergleich vor/nach dem Umzug.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--pruefe', metavar='DATEI',
            help='Gegen eine frühere Ausgabe vergleichen. Endet mit Code 1 bei Abweichung.')

    def handle(self, *args, **optionen):
        zeilen = []
        for modell in apps.get_models():
            label = modell._meta.label
            if label in AUSGENOMMEN:
                continue
            try:
                # Ausdrücklich über ALLE Verwaltungen zählen (Skill
                # `mandantentrennung`, Regel 2): Der Umzug bewegt die ganze
                # Datenbank, nicht den Bestand einer Verwaltung. Über `objects`
                # gezählt lieferte jede Zeile seit Etappe 6.2 nur noch
                # `FEHLER:OrganisationsFehler` — die Nachzählung, die den Umzug
                # absichern soll, hätte also gar nichts mehr abgesichert.
                manager = getattr(modell, 'alle_organisationen', None) or modell._base_manager
                zeilen.append(f'{label} {manager.count()}')
            except Exception as fehler:                 # noqa: BLE001
                # Eine Tabelle, die nicht lesbar ist, gehört gemeldet und nicht
                # übersprungen — sonst sieht ein unvollständiger Umzug wie ein
                # vollständiger aus.
                zeilen.append(f'{label} FEHLER:{type(fehler).__name__}')
        zeilen.sort()
        ausgabe = '\n'.join(zeilen)

        if not optionen.get('pruefe'):
            self.stdout.write(ausgabe)
            return

        with open(optionen['pruefe'], encoding='utf-8') as datei:
            erwartet = datei.read().strip().split('\n')
        tatsaechlich = zeilen

        fehlend = [z for z in erwartet if z not in tatsaechlich]
        zuviel = [z for z in tatsaechlich if z not in erwartet]
        if not fehlend and not zuviel:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Bestand identisch — {len(zeilen)} Modelle, '
                f'{sum(int(z.split()[-1]) for z in zeilen if z.split()[-1].isdigit())} Datensätze.'))
            return

        self.stderr.write(self.style.ERROR('✗ Bestand weicht ab.'))
        for z in fehlend:
            self.stderr.write(f'   erwartet, fehlt oder anders: {z}')
        for z in zuviel:
            self.stderr.write(f'   unerwartet vorhanden:        {z}')
        raise SystemExit(1)
