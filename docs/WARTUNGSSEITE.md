# Wartungsseite bei Schemaabweichung

**Stand:** 16.08.2026 · nach dem Ausfall vom 15.08. und der Deploy-Nachbesserung
**Basis:** `main`
**Agent:** `aufraeumer`
**Dringlichkeit:** vor Etappe 5, PR 2

---

## Der Anlass, mit der richtigen Ursache

Am 15.08.2026 lieferte die Produktion auf jeder Seite `OperationalError: no such table: crm_mitgliedschaft` — neuer Code auf altem Schema.

**Die Ursache lag im Always-on-Task, nicht in `deploy.sh`.** Der Task enthielt eine selbstgebaute Schleife, die alles selbst tat. Drei Fehler ergaben zusammen genau dieses Bild:

1. `benutzer_uebernahme` fehlte, `migrate` brach mit `InconsistentMigrationHistory` ab.
2. `git reset --hard` lief davor und blieb stehen — neuer Code auf der Platte, altes Schema in der Datenbank.
3. **Die Schleife versuchte es nie erneut.** Nach dem Reset gilt `HEAD == FETCH_HEAD`, die Bedingung davor ist falsch, die `&&`-Kette bricht ab, bevor `migrate` wieder aufgerufen wird — alle 30 Sekunden aufs Neue.

Punkt 3 machte aus einem einmaligen Fehlschlag einen Dauerzustand, den nichts meldete.

**Das ist behoben.** Der Task ruft jetzt `deploy.sh --dauerlauf` auf, und `deploy.sh` rollt bei gescheiterter Migration den Code zurück. Damit repariert sich der Zustand selbst.

**Was bleibt:** Die Selbstheilung greift nur, solange der Deploy läuft. Fällt der Always-on-Task aus, steht man wieder vor dem Bild vom 15.08. — und der Nutzer sieht einen Traceback statt einer verständlichen Meldung. Etappe 5 bringt sechs weitere Migrationsrunden über den Bestand; diese Absicherung gehört davor.

### Nachtrag vom 16.08.2026 — zwei weitere Ursachen

Die Beschreibung oben war richtig, aber nicht vollständig. Bei der Fehlersuche am 16.08. kamen zwei Ursachen dazu, die beide für sich allein denselben Ausfall erzeugt hätten:

**Der Task holte seit dem 12.08. um 14:43 gar nichts mehr.** Das Always-on-Log zeigt ab dann ausschliesslich

```
git@github.com: Permission denied (publickey).
fatal: Could not read from remote repository.
```

Die Remote-URL war SSH, der Schlüssel weg. Weil `git fetch` der erste Befehl der `&&`-Kette war, blieb der Rest stumm. Vier Tage lang. `deploy.sh` setzt die Remote-URL jetzt hart auf HTTPS — das Repository ist öffentlich, eine Anmeldung braucht es nicht.

**Die erste Nachbesserung baute eine Schleife, aus der sich der Deploy nicht befreien konnte.** Die Python-Suche läuft vor `git reset --hard`, und der Rollback setzte den Checkout zurück — samt `deploy.sh`. Jede Korrektur am Deploy entfernte sich damit selbst, sobald sie einmal fehlschlug. Behoben durch einen Selbstneustart und dadurch, dass `deploy.sh` vom Rollback ausgenommen ist.

Beides steht ausführlich in `docs/AUTOMATISIERUNG.md`.

---

## 1 — Startcheck und Wartungsseite

Beim Start prüfen, ob ungelaufene Migrationen existieren. Wenn ja, liefert jede Anfrage eine **Wartungsseite mit Status 503** statt eines Tracebacks.

Vier Dinge, die den Unterschied zwischen Absicherung und neuer Fehlerquelle machen:

**Einmal beim Start prüfen, nicht je Anfrage.** Ein `MigrationRecorder`-Abgleich pro Request wäre eine zusätzliche Datenbankabfrage auf jedem Seitenaufruf. `core/apps.py` hat bereits ein `ready()`; ein dort einmalig gesetztes Modulattribut genügt.

**Die Prüfung darf `migrate` und `collectstatic` nicht blockieren.** `ready()` läuft auch bei diesen Befehlen. Ohne Absicherung baut man eine Anwendung, die sich nicht mehr migrieren lässt — das wäre schlimmer als der Fehler, den wir beheben. Ein Test dafür ist Teil der Abnahme, nicht eine Sorgfaltszusage.

**Fehlschlagen der Prüfung darf nichts blockieren.** Ist die Datenbank kurz nicht erreichbar, startet die Anwendung normal weiter, statt in die Wartungsseite zu fallen.

**Die Seite ist öffentlich.** Kein Traceback, keine Dateipfade, kein Hinweis auf fehlende Tabellen. Ein Satz für Nutzer; der Hinweis, welcher Befehl fehlt, gehört ins Log, nicht in die Antwort.

Erwägenswert, aber nicht zwingend: `/healthz/` und `/version/` von der Wartungsseite ausnehmen, damit man von aussen sieht, welcher Stand hängt.

### Korrektur: `migration_plan` erkennt den entscheidenden Fall nicht

Die erste Umsetzung fragte `executor.migration_plan(graph.leaf_nodes())` — also „was müsste ich jetzt ausführen?". Django beantwortet das unter der Annahme, die Buchführung sei in sich stimmig: Ist ein **späterer** Schritt in `django_migrations` vermerkt, gelten seine Vorgänger als erledigt.

Belegt: Entfernt man `crm.0033` aus `django_migrations`, während `crm.0034` stehen bleibt, ist der Plan **leer** und die Wartungsseite löst nicht aus.

Das ist kein Randfall, sondern die Form, in der der Ausfall auftrat: Am 16.08. meldete die Produktion `No migrations to apply`, während `crm_mitgliedschaft` nachweislich fehlte. Eine Wartungsseite, die ausgerechnet ihren eigenen Anlass nicht erkennt, ist keine.

Richtig ist der Mengenvergleich, weil er die andere Frage stellt — „welcher Knoten des Graphen ist nicht als angewendet vermerkt?":

```python
offen = set(loader.graph.nodes) - set(loader.applied_migrations)
```

Darauf gibt es nur eine Antwort, und sie hängt von keiner Annahme über Reihenfolge ab.

### Die `RuntimeWarning` aus `ready()`

Der Startcheck löst aus:

```
RuntimeWarning: Accessing the database during app initialization is discouraged.
To fix this warning, avoid executing queries in AppConfig.ready() or when your
app modules are imported.
```

Django meint damit Abfragen, die **Modelle** lesen — die sind zu diesem Zeitpunkt womöglich noch nicht vollständig geladen. Hier wird kein Modell angefasst: `MigrationLoader` liest `django_migrations` über rohes SQL, eine Tabelle, die Django selbst verwaltet.

Und die Abfrage muss dort stehen. Der ganze Zweck ist, den Zustand **einmal** festzustellen statt bei jeder Anfrage; verschöbe man sie in die erste Anfrage, hätte man die Datenbankabfrage im Anfragepfad.

Unterdrückt wird deshalb gezielt diese eine Warnung, aus diesem einen Modul, für diesen einen Block — kein globales `filterwarnings('ignore')`, das auch die nächste verschluckt, die etwas Echtes meldet. Nachweis: `python -W error::RuntimeWarning` läuft durch.

## 2 — `deploy.sh` auf `main`

```bash
BRANCH="${1:-claude/fairwalter-rebuild}"     # Zeile 44
```

Seit E4 ist `main` der Hauptzweig. Heute zeigen beide auf denselben Commit — sobald sie auseinanderlaufen, deployt der Server den falschen Stand und meldet dabei Erfolg. Einzeiler, gehört in denselben PR oder einen eigenen.

## 3 — `DEBUG` auf dem Server

Keine Code-Änderung: `swiss_immo/settings.py` liest korrekt `os.getenv('DEBUG', 'False') == 'True'`. Am 15.08. zeigte die Produktion aber eine vollständige Django-Fehlerseite mit Traceback, Dateipfaden und Python-Pfad — also stand die Umgebungsvariable auf `True`.

**Auf PythonAnywhere unter Web → Environment variables prüfen und entfernen, dann Reload.** Auf einem öffentlich erreichbaren System mit Mieterdaten, Betreibungsauszügen und Lohnausweisen ist das ein eigenständiges Problem, unabhängig vom Ausfall.

Ergänzend: `manage.py check --deploy` in `deploy.sh` aufnehmen, Befund ins Protokoll, ohne den Deploy abzubrechen.

---

## Abnahme

- Ungelaufene Migrationen führen zu einer Wartungsseite mit 503, nicht zu einem Traceback
- **Test:** Zustand „Migration fehlt" hergestellt, Wartungsseite nachgewiesen
- **Test:** `migrate` und `collectstatic` funktionieren mit der Prüfung unverändert
- Die Wartungsseite enthält keine internen Angaben
- `deploy.sh` zieht `main`
- `DEBUG` produktiv auf `False` bestätigt
- Testsuite grün, Testzahl nicht unter **1'107**, Ruff und `check` sauber

### Zur Testzahl

Die geforderten 1'107 lassen sich mit der hier gemessenen Aufteilung nicht
nachvollziehen. Gemessen am 16.08. **nach** Etappe 5 PR 1 (der 8 Tests
hinzufügte und 1 entfernte): **1'101** — 332 + 309 + 215 + 240 + 5. Geprüft
wird deshalb gegen diese Zahl, mit derselben Regel: sie darf nicht sinken.

Ein fester Erwartungswert, dessen Herkunft niemand mehr kennt, ist genau der
Alarm, der irgendwann grundlos anschlägt und danach ignoriert wird.

---

## Was nicht dazugehört

- **Etappe 5** wartet, bis das durch ist. Danach sofort weiter.
- **Python-Version angleichen** (produktiv 3.10.12, Ruff `py311`, Prüfumgebung 3.12) — aufnehmen, entscheiden, nicht jetzt.
- **PostgreSQL** (P1.4) — eigener Schritt.
- **Weitere Nachbesserungen an `deploy.sh`.** Der Ablauf ist nach den Commits vom 16.08. in gutem Zustand; hier geht es nur noch darum, was passiert, wenn er *nicht* läuft.
