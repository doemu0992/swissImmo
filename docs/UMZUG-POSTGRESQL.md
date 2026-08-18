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
(`manage.py sequenzen_richten`) und bricht ab, wenn der Schritt scheitert.

**2. Die drei Umgebungen.** Auf PythonAnywhere hat **jeder** Prozess eigene
Umgebungsvariablen: Web‑App, Always‑on‑Task und Bash‑Konsole. Setzt man sie nur
an einer Stelle, läuft die Website auf PostgreSQL, während der Deploy‑Task
weiter die SQLite‑Datei migriert. Beide Seiten funktionieren für sich, der
Deploy meldet Erfolg — und die Website bekommt die Migration nie zu sehen.
Dagegen steht `.datenbank-erwartet` (siehe unten).

**Für dieses Projekt löst sich das über die `.env`.** `settings.py` lädt beim
Start `BASE_DIR/.env` (`load_dotenv`), und alle drei Prozesse gehen durch
`settings.py`. Eine Datei genügt also; sie steht in `.gitignore`, das Passwort
kommt damit nicht ins Repo.

| Prozess | Nötig nach einer Änderung der `.env` |
|---|---|
| Web‑App | **Reload** — der Prozess liest die Datei nur beim Start |
| Always‑on‑Task (Deploy) | **nichts** — `deploy.sh` startet je Durchgang ein frisches `manage.py`, das neu liest |
| Bash‑Konsole | nichts — jeder `manage.py`‑Aufruf ist ein neuer Prozess |

> Frühere Fassungen dieses Dokuments nannten hier den Web‑Tab, `~/.bashrc` und
> die Task‑Zeile und verlangten einen Neustart des Tasks. Das ist der allgemeine
> PythonAnywhere‑Weg und für dieses Projekt unnötig umständlich — korrigiert am
> 18.08.2026, nachdem die Suche nach dem nicht existierenden Feld
> «Environment variables» im Web‑Tab Zeit gekostet hat.

**Ausnahme: der Umzug selbst.** Während `umzug_postgres.sh` läuft, gehören die
Werte als `export` in die Konsole und **nicht** in die `.env`. Grund: Die
Schritte 0–3 lesen den Bestand noch aus SQLite und schalten dafür mit
`env -u DB_ENGINE` zurück — das wirkt nur auf die Shell‑Umgebung. Stünde
`DB_ENGINE=postgres` in der `.env`, holte `load_dotenv` es trotzdem wieder
herein, und `dumpdata` liefe gegen die noch leere Zieldatenbank. In die `.env`
kommen die Werte also erst **nach** dem geglückten Lauf.

## Vorbereitung — was von Hand geschieht

Zugangsdaten gehören nicht in einen Chatverlauf und nicht ins Repo. Diese
Schritte macht der Betreiber selbst.

**1. Passwort setzen.** Auf der PostgreSQL‑Seite bei PythonAnywhere das
Passwort für die Rolle `super` vergeben. Verbindungsdaten stehen auf derselben
Seite (Adresse, Port).

**2. Datenbank anlegen.** Django kann das nicht selbst — `migrate` setzt
voraus, dass die Datenbank schon da ist. In einer Bash-Konsole:

```bash
workon myenv
cd ~/swiss-manager
python postgres_anlegen.py \
    --host swissimmo-5420.postgres.pythonanywhere-services.com \
    --port 15420
```

Das Skript fragt zuerst das Passwort von `super` ab, dann ein neues für die
Anwendungs-Rolle. Es legt an:

```
Rolle     swissimmo_app   — die Anwendung läuft nicht als Superuser
Datenbank swissimmo       — Eigentümerin ist swissimmo_app
```

Es ist wiederholbar: Was schon besteht, wird gemeldet und übersprungen; eine
vorhandene Datenbank fasst es nicht an.

> **Warum die Rolle Eigentümerin sein muss.** Seit PostgreSQL 15 darf eine
> beliebige Rolle im Schema `public` nichts mehr anlegen. Wer die Datenbank dem
> Superuser gibt und der Anwendung nur `GRANT ALL ON DATABASE`, bekommt beim
> ersten `migrate` `permission denied for schema public` — eine Meldung, die
> nach einem Django-Problem aussieht und keines ist. Als Eigentümerin hat die
> Rolle das Recht ohne jeden zusätzlichen `GRANT`.

Von Hand geht es genauso; das Skript nimmt nur die Fallstricke ab:

```sql
CREATE ROLE swissimmo_app LOGIN PASSWORD '<gutes-passwort>';
CREATE DATABASE swissimmo OWNER swissimmo_app ENCODING 'UTF8';
```

**3. Variablen setzen**, zunächst nur in der Konsole, in der der Umzug läuft —
`postgres_anlegen.py` gibt diese Zeilen am Ende auch selbst aus:

```bash
export DB_ENGINE=postgres
export DB_NAME=swissimmo
export DB_USER=swissimmo_app
export DB_PASSWORD='<passwort>'
export DB_HOST=<adresse>
export DB_PORT=<port>
```

## Der Probelauf vom 18.08.2026 — was er ergeben hat

Der Umzug wurde einmal **vollständig durchgespielt**: echter PostgreSQL-16-Server, echter Bestand, `umzug_postgres.sh` von vorne bis hinten. Nicht gelesen — gelaufen.

**Er brach beim ersten Versuch ab**, in Schritt 3:

```
CommandError: Unable to serialize database: [<class 'decimal.InvalidOperation'>]
```

Kein Modell, keine Zeile, kein Feld. Ursache: zwei Datensätze in
`core_kreditorenrechnung` mit `betrag = 999999999999.99` — bei einem Feld
`DecimalField(max_digits=10, decimal_places=2)`, das bis 99'999'999.99 reicht.

**Warum so etwas überhaupt in der Datenbank steht:** SQLite erzwingt
Spaltenbreiten **nicht**. `max_digits` und `max_length` sind dort
Absichtserklärungen; wer mehr hineinschreibt, bekommt es gespeichert.
PostgreSQL erzwingt beide. Ein Bestand kann jahrelang laufen und beim Umzug an
einer einzigen Zeile scheitern.

Diese Zeilen sind übrigens **für Django gar nicht lesbar** — auch im laufenden
Betrieb nicht: Django setzt beim Lesen die Rechengenauigkeit auf `max_digits`
und rundet dann; schon das wirft. Jede Abfrage, die sie berührt, bricht ab.

**Daraus entstanden ist `manage.py umzug_pruefen`** — Schritt 0 des Umzugs. Er
nennt Tabelle, Primärschlüssel, Feld, Wert und Grenzwert:

```
✗ 2 Wert(e) passen NICHT in ihre deklarierte Spalte.
  finance.KreditorenRechnung  pk=24  betrag
      Wert:  999999999999.99
      zu gross fuer max_digits=10, decimal_places=2 (erlaubt bis 99999999.99)
```

Nach Bereinigung lief der Umzug **vollständig durch**:

| Schritt | Ergebnis |
|---|---|
| Sicherung | 78 Tabellen, 203 Migrationen, 24'602 Mediendateien — geprüft |
| Zählen (SQLite) | 67 Modelle |
| `dumpdata --all` | 3'067 Objekte |
| `migrate` (Postgres) | alle Migrationen sauber |
| `loaddata` | 3'067 Objekte |
| **Sequenzen** | 75 gesetzt |
| Nachzählen | **Bestand identisch — 67 Modelle, 3'067 Datensätze** |

**Zusätzlich geprüft, was das Skript selbst nicht prüft:**

- **Die Sequenzen wirklich.** Eine neue Buchung bekam ID 1053 bei höchster bestehender ID 1052 — keine Kollision. Über alle 70 Tabellen mit Sequenz nachgemessen: jede liegt auf oder über der höchsten vergebenen ID. Das ist der Fehler, vor dem dieses Dokument oben warnt, und er tritt nicht ein.
- **Der Wächter in beide Richtungen.** `datenbank_pruefen` endet mit Code 1, wenn Engine und `.datenbank-erwartet` auseinanderlaufen, und mit 0, wenn sie zusammenpassen. In `deploy.sh` steht er vor beiden Schreibpfaden (Benutzer-Übernahme und `migrate`).
- **Die Sicherung auf PostgreSQL.** `manage.py sicherung` schaltet selbst auf `pg_dump -Fc` um und liest den Stand zur Kontrolle zurück: 826 Objekte.

**Was der Probelauf NICHT abdeckt:** PythonAnywhere selbst — die drei
Umgebungen, der Always-on-Task, der Web-Tab. Das lässt sich nur dort prüfen.
Und: Der Probelauf lief auf dem Entwicklungsbestand. Auf der Produktion können
weitere Werte ausserhalb ihrer Spaltenbreite liegen; **darum ist Schritt 0 Teil
des Skripts und keine einmalige Aufräumaktion.**

---

## Der Umzug

```bash
workon myenv
cd ~/swiss-manager
git pull origin main
bash umzug_postgres.sh
```

Das Skript macht acht Schritte und bricht bei jedem Fehler ab:

0. **Spaltenbreiten prüfen** (`umzug_pruefen --streng`) — findet Werte, die
   SQLite annimmt und PostgreSQL abweist. Steht vor der Sicherung, weil er
   nichts anfasst und Minuten spart.
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

**1. Die sechs `DB_`‑Zeilen in die `.env`** im Projektordner eintragen — ohne
`export`, ohne Anführungszeichen (das ist eine dotenv‑Datei, keine Shell; ein
`#` im Passwort leitet dort einen Kommentar ein). Danach die **Web‑App neu
laden**; der Always‑on‑Task braucht keinen Neustart (Tabelle oben).

**2. `.datenbank-erwartet` umstellen** und pushen:

```
engine = postgres
name   = swissimmo
```

Ab dann prüft `deploy.sh` vor jedem `migrate`, ob er auf der richtigen
Datenbank steht, und bricht sonst ab, statt still die falsche zu migrieren.

**Reihenfolge beachten:** erst die `.env` setzen, dann pushen. Andersherum
schlägt der erste Deploy fehl. Das ist richtig so — aber es macht unnötig Lärm,
weil der Task alle 30 s erneut anläuft.

**3. Prüfen:**

```bash
python manage.py datenbank_pruefen     # muss "wie erwartet" melden
```

Dann Web‑App neu laden und `/version/` sowie eine Liste im Fairwalter‑Bereich
aufrufen.

## Wenn etwas nicht stimmt

Die SQLite‑Datei liegt unberührt im Projektordner **und** als Kopie unter
`~/umzug-<zeitstempel>/db.sqlite3`. Rückweg:

1. `DB_ENGINE` aus der `.env` entfernen (die übrigen `DB_`‑Zeilen dürfen
   stehen bleiben — ohne `DB_ENGINE` betritt `settings.py` den
   PostgreSQL‑Zweig nicht)
2. `.datenbank-erwartet` zurück auf `engine = sqlite`, pushen
3. Web‑App neu laden

Alles läuft weiter wie vorher. Es geht dabei nur verloren, was **nach** dem
Umzug in PostgreSQL geschrieben wurde — deshalb den Betrieb erst freigeben,
wenn Schritt 3 oben sauber durchgelaufen ist.

## Was danach anders ist

- **Kein WAL‑Thema mehr.** Die SQLite‑Optionen in `settings.py` bleiben
  stehen, greifen aber nicht mehr — sie gelten weiter für die
  Entwicklungsumgebung und die Tests.
- **`CONN_MAX_AGE = 600`** hält Verbindungen offen. Das ist bei PostgreSQL
  richtig und bei SQLite bedeutungslos.
- **Sicherungen laufen weiter.** `manage.py sicherung` erkennt den Motor selbst
  und schaltet von der SQLite-Sicherungsschnittstelle auf `pg_dump -Fc` um; am
  geplanten Task ändert sich nichts. Siehe [`SICHERUNG.md`](SICHERUNG.md).
  Falls `pg_dump` auf dem Server fehlt, weicht der Befehl auf `dumpdata` aus —
  laut und unter anderem Dateinamen, damit bei der Wiederherstellung niemand
  das eine für das andere hält.
