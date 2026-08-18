# Sicherung und Wiederherstellung

Stand: 18.08.2026 — Wiederherstellung durchgespielt (siehe unten).

Eine Sicherung, die niemand je zurückgespielt hat, ist eine Hoffnung. Der
zweite Teil dieses Dokuments — **Wiederherstellen** — ist deshalb der
wichtigere. Er ist am 18.08.2026 einmal vollständig durchgespielt worden;
was dabei herauskam, steht unter «Durchgespielt am 18.08.2026».

## Was gesichert wird

| | Warum |
|---|---|
| Datenbank | Der Bestand: Mandate, Verträge, Buchungen, Mieter |
| `media/` | Verträge, Belege, Schadensfotos — bei einer Hausverwaltung ein **erheblicher** Teil der Kundendaten, und nicht in der Datenbank |

Eine Sicherung nur der Datenbank stellt im Ernstfall eine Verwaltung mit lauter
toten Verweisen wieder her. Beides gehört zusammen.

## Sichern

```bash
workon myenv
cd ~/swiss-manager
python manage.py sicherung
```

Legt in `~/sicherungen/` ab:

```
20260817-030000-db.sqlite3        # bzw. -db.dump auf PostgreSQL
20260817-030000-medien.tar.gz
```

| Option | Bedeutung |
|---|---|
| `--ziel ORDNER` | anderer Ablageort |
| `--behalten N` | so viele Datenbank-Stände aufbewahren (Standard 14) |
| `--medien-behalten N` | so viele Medien-Archive (Standard 4) |
| `--ohne-medien` | nur die Datenbank |

Datenbank und Medien werden **getrennt** aufbewahrt, weil sie sich verschieden
verhalten: Die Datenbank ist klein und ändert sich täglich, das Medien-Archiv
ist gross und ändert sich kaum. Gemeinsam rotiert müsste man sich zwischen
»zu wenig Datenbank-Stände« und »Platte voll« entscheiden.

### Was der Befehl anders macht als ein `cp`

**SQLite wird gesichert, nicht kopiert.** Die Datenbank läuft im WAL-Modus.
Bestätigte Transaktionen stehen dabei zunächst in einer Nebendatei
(`db.sqlite3-wal`) und wandern erst später in die Hauptdatei. Wer nur
`db.sqlite3` kopiert, bekommt auf einem laufenden Server einen Stand, dem die
letzten Buchungen fehlen — **ohne dass irgendetwas fehlschlägt**. Der Befehl
nutzt die `sqlite3`-Sicherungsschnittstelle und schreibt das Ergebnis als
**eine** Datei (kein `-wal`, kein `-shm`, nichts, das man beim Zurückspielen
vergessen kann).

**Jede Sicherung wird gelesen, bevor sie als gelungen gilt.** SQLite-Stände mit
`PRAGMA integrity_check` und einer Zeilenzählung, PostgreSQL-Stände mit
`pg_restore --list`. Was die Prüfung nicht besteht, wird gelöscht statt
gemeldet — ein unbrauchbarer Stand, der wie ein guter aussieht, ist schlimmer
als gar keiner.

## Täglich laufen lassen

Bei PythonAnywhere unter **Tasks → Scheduled tasks**, täglich:

```
/home/swissimmo/.virtualenvs/myenv/bin/python /home/swissimmo/swiss-manager/manage.py sicherung
```

Eine Uhrzeit ausserhalb der Bürozeiten wählen (z. B. 03:00). Der Befehl läuft
neben dem laufenden Betrieb — SQLite muss dafür nicht angehalten werden.

## Wiederherstellen

### SQLite

```bash
# 1. Web-App anhalten (Web-Tab → Disable), sonst schreibt sie weiter.
# 2. Den aktuellen Stand beiseitelegen — nicht überschreiben.
cd ~/swiss-manager
mv db.sqlite3 db.sqlite3.vorher
rm -f db.sqlite3-wal db.sqlite3-shm        # Reste des alten Standes

# 3. Sicherung einsetzen.
cp ~/sicherungen/20260817-030000-db.sqlite3 db.sqlite3

# 4. Vor dem Einschalten nachzählen.
workon myenv
python manage.py bestand_zaehlen | head -20
python manage.py migrate --check           # passt der Code zum Stand?

# 5. Medien, falls nötig.
mv media media.vorher
tar -xzf ~/sicherungen/20260817-030000-medien.tar.gz    # entpackt nach ./media

# 6. Web-App wieder einschalten und neu laden.
```

> `migrate --check` in Schritt 4 ist wichtig: Eine ältere Sicherung kennt
> eventuell die neuesten Migrationen nicht. Meldet der Befehl offene Schritte,
> danach `python manage.py migrate` laufen lassen — **vor** dem Einschalten.
> Sonst greift die Wartungsseite und die Anwendung ist ohnehin nicht erreichbar.

### PostgreSQL

```bash
# Web-App anhalten. Dann in eine FRISCHE Datenbank zurückspielen, nicht in die
# bestehende — solange der alte Stand da ist, kann man ihn noch ansehen.
createdb -h $DB_HOST -p $DB_PORT -U super -O swissimmo_app swissimmo_wieder

pg_restore -h $DB_HOST -p $DB_PORT -U swissimmo_app \
           -d swissimmo_wieder ~/sicherungen/20260817-030000-db.dump

# Nachzählen, bevor umgeschaltet wird:
DB_NAME=swissimmo_wieder python manage.py bestand_zaehlen | head -20

# Und die Dateien mitprüfen — Zeilen zählen sieht sie nicht:
DB_NAME=swissimmo_wieder python manage.py medien_pruefen \
        --sicherung ~/sicherungen/20260817-030000-medien.tar.gz

# Passt es: DB_NAME in der .env umstellen (sie bedient Web-App,
# Always-on-Task und Konsole), .datenbank-erwartet nachziehen,
# Web-App neu laden.
```

> Steht statt `-db.dump` eine Datei `-db.dumpdata.json` da, war `pg_dump` auf
> dem Rechner nicht vorhanden und es wurde ersatzweise gesichert. Dieser Stand
> enthält die **Daten**, aber weder Sequenzen noch Rechte. Wiederherstellung:
> `migrate` auf einer leeren Datenbank, dann `loaddata <datei>`, dann
> **`python manage.py sequenzen_richten`** — ohne den letzten Schritt kollidiert
> der erste neue Datensatz.

## Was diese Sicherung nicht leistet

Die Stände liegen auf **demselben Rechner**. Das schützt gegen »versehentlich
gelöscht«, gegen einen missratenen Deploy und gegen eine kaputte Migration.
Es schützt **nicht** gegen den Verlust des Kontos oder der Maschine.

Eine Kopie ausser Haus wäre der nächste Schritt. Sie bedeutet einen externen
Dienst, laufende Kosten und Kundendaten, die das System verlassen — bei
Personendaten von Mietern also auch eine Frage des Datenschutzes (Standort,
Auftragsverarbeitung). Das ist ein Entscheid, kein Implementierungsdetail, und
deshalb hier bewusst nicht eingebaut. Aufgeführt in `PHASE-2-PLAN.md` unter den
offenen Entscheiden.

## Durchgespielt am 18.08.2026

Der Probelauf hat stattgefunden — gegen einen **echten PostgreSQL 16.13**, mit
dem vollständigen Bestand, in eine **separate Datenbank** (`swissimmo_probe`).
Die Ausgangsdatenbank blieb unberührt.

### Die Zahlen

| | |
|---|---|
| Sicherung (`manage.py sicherung`) | **41 s** — 412 kB Datenbank, 100 MB Medien |
| Gegengelesen | 826 Objekte (`pg_restore --list`), 24 678 Mediendateien |
| `pg_restore` | **1 s**, Exitcode 0, **keine einzige Warnung** |
| Medien entpacken | 4 s |
| Nachzählung | 67 Modelle, 3067 Datensätze — **identisch** |
| Sequenzen | 76 von 76, `last_value` **überall identisch** |

Die Wiederherstellung selbst dauert also **Sekunden**. Der Zeitaufwand im
Ernstfall liegt bei der Sicherung und beim Entpacken der Medien, nicht beim
Zurückspielen — und er wächst mit den Medien, nicht mit dem Bestand.

### Was der Probelauf beantwortet hat

**`sequenzen_richten` wird nach `pg_restore` NICHT gebraucht.** Das war die
offene Frage, denn nach dem `loaddata`-Weg ist es zwingend. Gemessen: Alle 76
Sequenzen kamen mit ihrem `last_value` aus dem Dump, und ein `INSERT` in der
zurückgespielten Datenbank vergab die nächste freie ID sauber:

```
hoechste bestehende Mieter-ID: 52
INSERT ergab ID: 53      → keine Kollision
```

> Für den **JSON-Ersatzstand** (`-db.dumpdata.json`, wenn `pg_dump` fehlt) gilt
> das Gegenteil unverändert: dort ist `sequenzen_richten` Pflicht.

**Die fachliche Stichprobe stimmt.** Verglichen wurden nicht Zeilenzahlen,
sondern Inhalte: ein Mietvertrag mit Anpassung, Mietzins-Komponenten,
27 Debitorenrechnungen und einer Kündigung, dazu eine Abrechnungsperiode —
33 Objekte, über Djangos Serializer ausgegeben und Zeichen für Zeichen
verglichen. Identisch.

### Was nicht funktioniert hat

Das ist der eigentliche Ertrag.

**1. Vier Dateiverweise zeigten ins Leere.** 165 Verweise geprüft, 4 ohne
Datei (`schaden_fotos/2026-08-08/…`). Nachgesehen: Die Dateien fehlten **auch
im Original**. Die Sicherung war treu, der Bestand nicht. `bestand_zaehlen`
meldete gleichzeitig «identisch» — Zeilen zählen sieht Dateien nicht.

Daraus ist `manage.py medien_pruefen` entstanden:

```bash
python manage.py medien_pruefen                              # nur melden
python manage.py medien_pruefen --sicherung ~/sicherungen/…-medien.tar.gz
```

Er trennt die beiden Fälle, die verschiedene Ursachen haben:

| Befund | Bedeutung |
|---|---|
| Verweis ohne Datei auf der Platte | Mangel im **Bestand** — was fehlt, kann nicht gesichert werden |
| Datei da, aber nicht im Tar | Die **Sicherung** ist unvollständig — der gefährliche Fall |

**Gehört auf der Produktion einmal gelaufen.** Die vier Funde stammen aus den
Entwicklungsdaten; wie viele es produktiv sind, ist offen.

**2. Zwei Vergleiche verglichen nichts — und meldeten Erfolg.** Beim Aufbau der
Stichprobe lief das Skript zweimal in einen Fehler (`ModuleNotFoundError`,
danach ein falscher Feldname). Beide Male blieben beide Ausgabedateien leer,
und `diff` meldete pflichtgemäss Übereinstimmung:

```
Original: 0 Bytes, Probe: 0 Bytes
→ fachlich identisch
```

Zwei fehlgeschlagene Läufe sehen im Vergleich aus wie ein geglückter. Seither
prüft das Skript auf leere Ausgabe und endet mit Code 2. Dieselbe Falle steckte
im Feldkatalog von Hand: Er ging bei einer Umbenennung kaputt und erzeugte
genau diese leere Ausgabe — deshalb serialisiert die Stichprobe jetzt über
Djangos eigenen Serializer, der die Felder aus dem Modell nimmt.

**3. `manage.py backup_db` sicherte unter PostgreSQL nicht** und meldete
trotzdem Erfolg (Exitcode 0, keine Datei — nur ein Hinweistext auf `pg_dump`).
Der Befehl ist **entfernt**; `manage.py sicherung` kann beide Motoren, bricht
bei Fehlschlag mit `CommandError` ab und liest den Stand gegen. Zwei Befehle
für dieselbe Aufgabe, von denen einer stillschweigend nichts tut, sind
gefährlicher als einer. Ein Aufruf von `backup_db` scheitert jetzt laut.

### Was weiterhin offen ist

**Der Probelauf lief nicht auf der Produktion**, sondern auf einer
gleichwertigen PostgreSQL-16-Installation mit demselben Bestand. Was er
belegt, ist der Weg und das Werkzeug. Was er nicht belegt, sind die Laufzeiten
auf PythonAnywhere — dort teilen sich mehrere Konten einen Server, und die
100 MB Medien gehen über das Netz statt über einen lokalen Socket. Rechne
eher mit Minuten als mit Sekunden.

**Eine Kopie ausser Haus** fehlt weiterhin (siehe oben) — daran ändert ein
geglückter Probelauf nichts.
