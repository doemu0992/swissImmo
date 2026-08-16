# Umzug SQLite → PostgreSQL

Stand: 16.08.2026. Betrifft die Produktion auf PythonAnywhere.

## Warum überhaupt

SQLite trägt swissImmo bis hierher gut, und seit der Härtung (WAL,
`transaction_mode=IMMEDIATE`, 30 s Timeout) auch mit mehreren Verwaltungen
gleichzeitig. Die Grenze ist nicht die Zahl der Mandanten, sondern die Zahl
gleichzeitiger **Schreiber**: SQLite lässt genau einen zu. Zwei Sollstellungs‑
läufe zur selben Sekunde blockieren einander. Genau da fängt PostgreSQL an,
sich zu lohnen — nicht früher.

Der Treiber (`psycopg[binary]==3.2.13`) liegt seit P0.5 in `requirements.txt`,
und `settings.py` schaltet über `DB_ENGINE=postgres` um. Am Code ist für den
Umzug **nichts** zu tun.

## Der Fehler, den dieser Umzug am ehesten produziert

Nicht der Datenverlust — davor schützen Sicherung und Nachzählung. Sondern
diese beiden:

**1. Die Sequenzen.** SQLite und PostgreSQL vergeben IDs unterschiedlich. Nach
`loaddata` stehen die PostgreSQL‑Zähler auf 1, obwohl in den Tabellen schon
Tausende Zeilen liegen. Alles funktioniert — bis jemand den ersten **neuen**
Datensatz anlegt, dessen ID mit einem bestehenden kollidiert. Der Fehler tritt
Tage später auf und sieht dort wie ein Programmfehler aus, nicht wie ein
Umzugsproblem. `umzug_postgres.sh` behebt das in Schritt 6
(`sqlsequencereset | dbshell`) und bricht ab, wenn der Schritt scheitert.

**2. Die drei Umgebungen.** Auf PythonAnywhere hat **jeder** Prozess eigene
Umgebungsvariablen:

| Prozess | Wo die Variablen stehen |
|---|---|
| Web‑App | Web‑Tab → *Environment variables* |
| Always‑on‑Task (Deploy) | erbt sie **nicht** vom Web‑Tab — sie gehören in `~/.bashrc` oder in die Task‑Zeile; **Neustart nötig** |
| Bash‑Konsole | `export` in der jeweiligen Sitzung, oder `~/.bashrc` |

Setzt man sie nur im Web‑Tab, läuft die Website auf PostgreSQL, während der
Deploy‑Task weiter die SQLite‑Datei migriert. Beide Seiten funktionieren für
sich, der Deploy meldet Erfolg — und die Website bekommt die Migration nie zu
sehen. Dagegen steht `.datenbank-erwartet` (siehe unten).

## Vorbereitung — was von Hand geschieht

Zugangsdaten gehören nicht in einen Chatverlauf und nicht ins Repo. Diese
Schritte macht der Betreiber selbst.

**1. Passwort setzen.** Auf der PostgreSQL‑Seite bei PythonAnywhere das
Passwort für die Rolle `super` vergeben. Verbindungsdaten stehen auf derselben
Seite (Adresse, Port).

**2. Datenbank anlegen.** In einer Bash‑Konsole:

```bash
psql -h <adresse> -p <port> -U super postgres
```

Und dort:

```sql
CREATE DATABASE swissimmo ENCODING 'UTF8';

-- Für den laufenden Betrieb eine eigene Rolle, nicht der Superuser.
-- Der Superuser gehört zur Verwaltung, nicht in die Anwendung.
CREATE ROLE swissimmo_app LOGIN PASSWORD '<gutes-passwort>';
GRANT ALL PRIVILEGES ON DATABASE swissimmo TO swissimmo_app;
\c swissimmo
GRANT ALL ON SCHEMA public TO swissimmo_app;
\q
```

> Der letzte `GRANT` ist seit PostgreSQL 15 nötig: Dort darf eine neue Rolle
> im Schema `public` standardmässig **nicht** mehr anlegen. Ohne ihn scheitert
> `migrate` mit `permission denied for schema public` — eine Meldung, die nach
> einem Django‑Problem aussieht und keines ist.

**3. Variablen setzen**, zunächst nur in der Konsole, in der der Umzug läuft:

```bash
export DB_ENGINE=postgres
export DB_NAME=swissimmo
export DB_USER=swissimmo_app
export DB_PASSWORD='<passwort>'
export DB_HOST=<adresse>
export DB_PORT=<port>
```

## Der Umzug

```bash
workon myenv
cd ~/swiss-manager
git pull origin main
bash umzug_postgres.sh
```

Das Skript macht sieben Schritte und bricht bei jedem Fehler ab:

1. Sicherung von `db.sqlite3` nach `~/umzug-<zeitstempel>/`
2. Bestand auf SQLite zählen (`bestand_zaehlen`)
3. `dumpdata` ohne contenttypes/permissions/sessions/admin.logentry
4. `migrate` auf der PostgreSQL‑Datenbank
5. `loaddata`
6. **Sequenzen zurücksetzen** — der Schritt aus Punkt 1 oben
7. Nachzählen und gegen Schritt 2 vergleichen

Es rührt die SQLite‑Datei **nicht** an. Geht etwas schief, ist der Rückweg in
jedem Schritt derselbe: Variablen entfernen, Web‑App neu laden.

> Zu den ausgelassenen Tabellen: `contenttypes` und `auth.Permission` legt
> Django auf der Zieldatenbank selbst an, mit eigenen IDs; sie mitzunehmen
> erzeugt Kollisionen. Geprüft: Das Projekt hat **keine** Fremdschlüssel auf
> `ContentType` und keine `GenericForeignKey`, es hängt also nichts daran.
> `sessions` ist flüchtig (alle werden abgemeldet, das ist alles),
> `admin.LogEntry` verweist auf ContentType.

## Nach dem Umzug

**1. Variablen an allen drei Stellen setzen** (Tabelle oben). Den Always‑on‑
Task danach **neu starten** — er übernimmt neue Variablen nicht im Lauf.

**2. `.datenbank-erwartet` umstellen** und pushen:

```
engine = postgres
name   = swissimmo
```

Ab dann prüft `deploy.sh` vor jedem `migrate`, ob er auf der richtigen
Datenbank steht, und bricht sonst ab, statt still die falsche zu migrieren.

**Reihenfolge beachten:** erst die Variablen setzen und den Task neu starten,
dann pushen. Andersherum schlägt der erste Deploy fehl. Das ist richtig so —
aber es macht unnötig Lärm, weil der Task alle 30 s erneut anläuft.

**3. Prüfen:**

```bash
python manage.py datenbank_pruefen     # muss "wie erwartet" melden
```

Dann Web‑App neu laden und `/version/` sowie eine Liste im Fairwalter‑Bereich
aufrufen.

## Wenn etwas nicht stimmt

Die SQLite‑Datei liegt unberührt im Projektordner **und** als Kopie unter
`~/umzug-<zeitstempel>/db.sqlite3`. Rückweg:

1. `DB_ENGINE` an allen drei Stellen entfernen
2. `.datenbank-erwartet` zurück auf `engine = sqlite`, pushen
3. Always‑on‑Task neu starten, Web‑App neu laden

Alles läuft weiter wie vorher. Es geht dabei nur verloren, was **nach** dem
Umzug in PostgreSQL geschrieben wurde — deshalb den Betrieb erst freigeben,
wenn Schritt 3 oben sauber durchgelaufen ist.

## Was danach anders ist

- **Kein WAL‑Thema mehr.** Die SQLite‑Optionen in `settings.py` bleiben
  stehen, greifen aber nicht mehr — sie gelten weiter für die
  Entwicklungsumgebung und die Tests.
- **`CONN_MAX_AGE = 600`** hält Verbindungen offen. Das ist bei PostgreSQL
  richtig und bei SQLite bedeutungslos.
- **Sicherungen ändern sich.** Eine Datei kopieren reicht nicht mehr; es
  braucht `pg_dump`. Das ist offen und gehört als eigener Punkt terminiert.
