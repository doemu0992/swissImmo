"""Wartungsseite bei Schemaabweichung — siehe docs/WARTUNGSSEITE.md.

Am 15.08.2026 lief die Produktion mit neuem Code auf altem Schema und
antwortete auf jeder Seite mit

    OperationalError: no such table: crm_mitgliedschaft

Der Deploy repariert das inzwischen selbst. Diese Datei ist für den Fall, dass
er es NICHT tut — dann sieht der Nutzer eine verständliche Meldung statt eines
Tracebacks, und die Anwendung schreibt nicht in eine Datenbank, deren Schema
nicht zu ihr passt.

VIER ENTSCHEIDUNGEN, die den Unterschied zwischen Absicherung und neuer
Fehlerquelle ausmachen:

1. **Einmal beim Start prüfen, nicht je Anfrage.** Ein Abgleich gegen
   `MigrationRecorder` bei jedem Seitenaufruf wäre eine zusätzliche Abfrage auf
   jeder Seite. Der Zustand ändert sich zwischen zwei Requests ohnehin nicht:
   Migrationen laufen im Deploy, und der lädt danach neu.

2. **`migrate` und `collectstatic` dürfen nie blockiert werden.** `ready()`
   läuft auch bei diesen Befehlen. Eine Anwendung, die sich wegen fehlender
   Migrationen nicht mehr migrieren lässt, wäre schlimmer als der Fehler, den
   diese Datei behebt — eine Sackgasse, aus der nur noch der Datenbankzugriff
   von Hand herausführt.

3. **Ein Fehlschlag der Prüfung blockiert nichts.** Ist die Datenbank beim
   Start kurz nicht erreichbar, startet die Anwendung normal. Die Prüfung ist
   ein Wächter, kein Türsteher: Sie darf melden, was sie sicher weiss, und
   muss schweigen, wenn sie nichts weiss.

4. **Die Seite ist öffentlich.** Kein Traceback, keine Dateipfade, kein Hinweis
   darauf, welche Tabelle fehlt. Was fehlt, gehört ins Log — dort liest es, wer
   Zugang hat.
"""
import logging
import sys
import warnings

from django.http import HttpResponse

logger = logging.getLogger(__name__)

#: Wird in `CoreConfig.ready()` gesetzt. `None` heisst „nicht geprüft".
#: Eine Liste heisst „diese Migrationen fehlen"; leer heisst „alles da".
FEHLENDE_MIGRATIONEN = None

#: Befehle, bei denen die Prüfung gar nicht erst läuft. `migrate` steht hier,
#: weil es der Befehl IST, der den Zustand behebt; `collectstatic` und die
#: übrigen, weil sie zum Deploy gehören und vor `migrate` laufen können.
UNGEPRUEFTE_BEFEHLE = frozenset({
    'migrate', 'makemigrations', 'showmigrations', 'sqlmigrate', 'squashmigrations',
    'collectstatic', 'test', 'shell', 'dbshell', 'createsuperuser', 'loaddata',
    'dumpdata', 'flush', 'check', 'benutzer_uebernahme',
})

#: Pfade, die trotz Wartungsmodus beantwortet werden. Sie sagen von aussen,
#: WELCHER Stand hängt — genau das braucht man, um den Ausfall zu beheben,
#: ohne sich auf die Konsole des Hosters verlassen zu müssen.
DURCHGELASSENE_PFADE = ('/healthz/', '/version/')


def pruefe_migrationsstand():
    """Ermittelt fehlende Migrationen und legt das Ergebnis ab.

    Gibt die Liste zurück (leer = alles angewendet). Bei jedem Problem wird
    `None` abgelegt und `None` zurückgegeben — „nicht geprüft", nicht „kaputt".
    """
    global FEHLENDE_MIGRATIONEN

    befehl = sys.argv[1] if len(sys.argv) > 1 else ''
    if befehl in UNGEPRUEFTE_BEFEHLE:
        FEHLENDE_MIGRATIONEN = None
        return None

    try:
        from django.db import connection
        from django.db.migrations.loader import MigrationLoader

        # DIE WARNUNG, DIE HIER ENTSTEHT, UND WARUM SIE UNTERDRÜCKT WIRD
        #
        #   RuntimeWarning: Accessing the database during app initialization is
        #   discouraged. To fix this warning, avoid executing queries in
        #   AppConfig.ready() or when your app modules are imported.
        #
        # Django meint damit Abfragen, die MODELLE lesen — die sind zu diesem
        # Zeitpunkt womöglich noch nicht vollständig geladen, und eine solche
        # Abfrage macht den Start von Zufällen abhängig. Hier wird kein Modell
        # angefasst: `MigrationLoader` liest `django_migrations` über rohes SQL,
        # eine Tabelle, die Django selbst verwaltet und die keiner App gehört.
        #
        # Und die Abfrage MUSS hier stehen. Der ganze Zweck ist, den Zustand
        # einmal beim Start festzustellen statt bei jeder Anfrage. Verschöbe man
        # sie in die erste Anfrage, hätte man die Datenbankabfrage im
        # Anfragepfad — genau das, was die Bauform vermeidet.
        #
        # Deshalb gezielt DIESE eine Warnung, aus DIESEM einen Modul, für DIESEN
        # Block. Ein globales `filterwarnings('ignore')` würde auch die nächste
        # verschlucken, die etwas Echtes meldet.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                'ignore',
                message='Accessing the database during app initialization is discouraged',
                category=RuntimeWarning)
            loader = MigrationLoader(connection)

        # MENGENVERGLEICH, NICHT `migration_plan`
        #
        # Die erste Fassung nahm `executor.migration_plan(graph.leaf_nodes())`.
        # Das ist die Frage „was müsste ich jetzt ausführen?" — und die
        # beantwortet Django unter der Annahme, dass die Buchführung in sich
        # stimmig ist: Ist ein SPÄTERER Schritt als angewendet vermerkt, gelten
        # seine Vorgänger als erledigt und tauchen im Plan nicht auf.
        #
        # Genau der Fall ist belegt: Entfernt man `crm.0033` aus
        # `django_migrations`, während `crm.0034` stehen bleibt, ist der Plan
        # LEER — und die Wartungsseite löste nicht aus. Das ist nicht der
        # Randfall, für den man Verständnis haben könnte, sondern die Form, in
        # der der Ausfall vom 15.08.2026 auftrat: Schema und Buchführung
        # auseinandergelaufen, `migrate` meldete „No migrations to apply",
        # während eine Tabelle fehlte.
        #
        # Der Mengenvergleich stellt die richtige Frage: „Welcher Knoten des
        # Graphen ist NICHT als angewendet vermerkt?" Darauf gibt es nur eine
        # Antwort, und sie hängt von keiner Annahme über Reihenfolge ab.
            offen = set(loader.graph.nodes) - set(loader.applied_migrations)
        FEHLENDE_MIGRATIONEN = sorted(f'{app}.{name}' for app, name in offen)
    except Exception as fehler:                     # noqa: BLE001 — siehe Punkt 3
        # Datenbank nicht erreichbar, Migrationsgraph unlesbar, was auch immer:
        # Das ist kein Grund, die Anwendung in den Wartungsmodus zu schicken.
        logger.warning('Migrationsstand nicht feststellbar (%s) — kein Wartungsmodus.', fehler)
        FEHLENDE_MIGRATIONEN = None
        return None

    if FEHLENDE_MIGRATIONEN:
        logger.error(
            'WARTUNGSMODUS: %d Migration(en) nicht angewendet: %s. '
            'Beheben mit: python manage.py benutzer_uebernahme && python manage.py migrate',
            len(FEHLENDE_MIGRATIONEN), ', '.join(FEHLENDE_MIGRATIONEN))
    return FEHLENDE_MIGRATIONEN


#: Bewusst ohne Template und ohne Kontextprozessoren: Beide könnten selbst auf
#: die Datenbank zugreifen — und die ist ja gerade der Grund, warum wir hier
#: sind. Eine Wartungsseite, die am fehlenden Schema scheitert, wäre eine
#: Pointe, aber keine Hilfe.
_SEITE = """<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wartungsarbeiten – swissImmo</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f8fafc; color: #1e293b; display: flex; align-items: center;
         justify-content: center; min-height: 100vh; margin: 0; padding: 1.5rem; }
  main { max-width: 32rem; background: #fff; border-radius: 1rem; padding: 2.5rem;
         box-shadow: 0 1px 3px rgba(0,0,0,.08); text-align: center; }
  h1 { font-size: 1.35rem; margin: 0 0 .75rem; }
  p  { line-height: 1.6; margin: 0 0 .5rem; color: #475569; }
  .klein { font-size: .85rem; color: #94a3b8; margin-top: 1.5rem; }
</style></head>
<body><main>
  <h1>Wartungsarbeiten</h1>
  <p>swissImmo wird gerade aktualisiert und ist in wenigen Minuten wieder
     erreichbar.</p>
  <p>Es gehen keine Daten verloren — gespeicherte Eingaben bleiben erhalten.</p>
  <p class="klein">Bitte in Kürze neu laden.</p>
</main></body></html>"""


class WartungsMiddleware:
    """Beantwortet jede Anfrage mit 503, solange Migrationen fehlen.

    Liest nur das beim Start gesetzte Modulattribut — keine Datenbankabfrage
    je Anfrage.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if FEHLENDE_MIGRATIONEN and request.path not in DURCHGELASSENE_PFADE:
            antwort = HttpResponse(_SEITE, status=503, content_type='text/html; charset=utf-8')
            # Suchmaschinen und Zwischenspeicher sollen den Zustand nicht
            # festhalten — er ist per Definition vorübergehend.
            antwort['Retry-After'] = '120'
            antwort['Cache-Control'] = 'no-store'
            return antwort
        return self.get_response(request)
