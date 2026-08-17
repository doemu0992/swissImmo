# Sicherung und Wiederherstellung

Stand: 17.08.2026.

Eine Sicherung, die niemand je zurückgespielt hat, ist eine Hoffnung. Der
zweite Teil dieses Dokuments — **Wiederherstellen** — ist deshalb der
wichtigere. Er gehört einmal ausprobiert, bevor man ihn braucht.

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

# Passt es: DB_NAME an allen drei Stellen umstellen (Web-Tab,
# Always-on-Task, Konsole), .datenbank-erwartet nachziehen, Task neu starten.
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

Ebenfalls offen: Ein **Wiederherstellungs-Probelauf**. Der Weg oben ist
beschrieben und die Sicherung wird bei jedem Lauf gegengelesen — aber ein
vollständiger Durchlauf auf einem Zweitsystem hat noch nicht stattgefunden.
