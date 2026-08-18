# Wiederherstellungs-Probelauf

**Stand:** 18.08.2026 · nach dem PostgreSQL-Umzug
**Basis:** `main`
**Agent:** `aufraeumer`
**Steht vor:** der zweiten Organisation

---

## Warum das jetzt kommt

`docs/SICHERUNG.md` beschreibt den Weg vollständig — Sichern, Prüfen, Rotation, täglicher Lauf, Wiederherstellen mit `pg_restore`. Was fehlt, ist der Beweis, dass er funktioniert.

**Eine Sicherung, aus der nie zurückgespielt wurde, ist eine Vermutung.** Und seit dem Umzug ist sie es doppelt: Der Wiederherstellungsweg für PostgreSQL ist ein anderer als der für SQLite, und der neue ist noch nie gelaufen.

Bis heute war das Risiko theoretisch. Mit der zweiten Verwaltung wird daraus eine Haftung für fremde Daten — und der Datenreset-Fall L1 aus dem Audit hat gezeigt, dass ein Totalverlust nicht hypothetisch ist. Er war ein `POST` und ein Bestätigungswort entfernt.

---

## Ein Befund vorweg

`manage.py backup_db` **sichert unter PostgreSQL nicht mehr.** Der Code prüft die Engine und gibt bei `postgresql` nur einen Hinweistext aus:

```python
elif 'postgresql' in engine:
    self.stdout.write("PostgreSQL erkannt. Bitte pg_dump verwenden, z.B.: …")
    return
```

Der Befehl endet mit Erfolg, ohne etwas zu sichern. Wer ihn wie bisher aufruft — etwa vor einer Migration —, hält danach eine Sicherung für vorhanden, die es nicht gibt.

**Das gehört in diesen Auftrag**, denn ein Probelauf der Wiederherstellung ist wertlos, wenn die Sicherung selbst nicht zuverlässig entsteht. Zwei mögliche Wege:

- `backup_db` ruft `pg_dump` selbst auf und meldet Erfolg nur, wenn eine Datei entstanden ist.
- Oder der Befehl **bricht ab** statt „Erfolg" zu melden, und die Sicherung läuft ausschliesslich über den in `SICHERUNG.md` beschriebenen Weg.

Der erste Weg ist der sichere: Ein Befehl, der je nach Datenbank etwas anderes tut, aber immer dasselbe verspricht, ist eine Falle. Entscheidung gehört begründet.

### Richtigstellung zum Befund (Vorrang des Bestands, 18.08.2026)

Der Befund stimmt in der Sache und wurde im Code nachgesehen — `core/management/commands/backup_db.py:46–51`, Rückgabe ohne Ausgabe einer Datei, Exitcode 0. Zwei Angaben drumherum stimmen **nicht** und sind hier korrigiert, damit die Umsetzung nicht auf einer falschen Lage aufsetzt:

**1. `deploy.sh` ruft `backup_db` nicht auf.** Der Auftragstext nennt `deploy.sh` als Stelle, an der der Befehl vor einer Migration empfohlen wird. Gesucht wurde über alle Skripte und Dokumente:

```
umzug_postgres.sh:91:  env -u DB_ENGINE "$PY" manage.py sicherung --ziel "$STAND" …
```

`backup_db` erscheint dort **nirgends** — es taucht nur in `docs/ANALYSE.md` in zwei Aufzählungen von Management-Commands auf. Die Gefahr ist damit kleiner als beschrieben: Kein automatischer Lauf verlässt sich auf den Befehl. Wer ihn von Hand aufruft, ist trotzdem betroffen.

**2. Die produktive Sicherung ist `manage.py sicherung`, und die kann PostgreSQL.** Sie ist der Weg, den `docs/SICHERUNG.md` beschreibt, den der tägliche Lauf nutzt und den `umzug_postgres.sh` in Schritt 1 aufruft. Sie schaltet selbst auf `pg_dump -Fc` um (`sicherung.py:79–80`, `144–189`), bricht bei Fehlschlag mit `CommandError` ab statt Erfolg zu melden, und liest den Stand mit `pg_restore --list` gegen — was die Prüfung nicht besteht, wird verworfen:

```python
if lauf.returncode != 0:
    raise CommandError(f'pg_dump fehlgeschlagen:\n{lauf.stderr.strip()}')
…
if pruef.returncode != 0:
    raise CommandError('Sicherung nicht lesbar (pg_restore --list) — verworfen.')
```

Belegt im Betrieb: Der Umzug am 18.08.2026 hat sie zweimal ausgeführt (SQLite-Seite: „78 Tabellen, 203 Migrationen", 336 Mediendateien), und `docs/UMZUG-POSTGRESQL.md:170` hält den PostgreSQL-Lauf mit 826 gegengelesenen Objekten fest.

**Was das für den Auftrag ändert:** Nicht das Ziel, aber die Reihenfolge der Argumente. `backup_db` ist kein kaputter Sicherungsweg, sondern ein **zweiter, überflüssiger** neben einem funktionierenden. Damit wird die dritte Möglichkeit die naheliegendste — sie fehlt oben:

- `backup_db` **entfernen** und alle Verweise auf `sicherung` zeigen lassen.

Zwei Befehle für dieselbe Aufgabe, von denen einer stillschweigend nichts tut, sind die eigentliche Falle. Welcher Weg gewählt wird, gehört weiterhin begründet — aber die Wahl steht jetzt auf der richtigen Grundlage.

---

## Der Probelauf

**Nicht auf der Produktion.** Zurückgespielt wird in eine **zweite, leere Datenbank** auf demselben Server — Rolle und Vorgehen wie bei `postgres_anlegen.py`, nur mit anderem Namen, etwa `swissimmo_probe`.

Ablauf:

1. Sicherung erzeugen, wie sie täglich entsteht — nicht von Hand mit anderen Schaltern
2. Zieldatenbank anlegen
3. `pg_restore` gemäss `docs/SICHERUNG.md`, Abschnitt „Wiederherstellen"
4. **Nachzählen**, nicht danebenschauen

Der Nachweis ist die Zählung, nicht das Ausbleiben von Fehlern. `pg_restore` meldet Warnungen, die harmlos aussehen und es nicht immer sind. Zu vergleichen:

- Zeilenzahl je Tabelle, Original gegen Wiederherstellung
- Sequenzen: Legt ein `INSERT` in der zurückgespielten Datenbank die nächste ID sauber an, oder kollidiert sie? Genau dafür gibt es `sequenzen_richten` — der Probelauf muss zeigen, ob er nötig ist und ob er reicht
- Stichprobe fachlich: ein Mietvertrag mit Mietzinshistorie, eine Abrechnungsperiode mit Belegen, ein Dokument mit Datei

`manage.py bestand_zaehlen` deckt den ersten Punkt bereits ab und wurde für genau diesen Zweck gebaut.

**Die Medien nicht vergessen.** Die Datenbank verweist auf Dateien; eine wiederhergestellte Datenbank ohne die zugehörigen Dateien ist ein halbes Ergebnis. Der Probelauf prüft beides zusammen.

**Zeit messen.** Wie lange dauert die Wiederherstellung? Das ist die Zahl, die im Ernstfall zählt — und die man vorher wissen will, nicht währenddessen.

---

## Was dokumentiert werden soll

`docs/SICHERUNG.md` bekommt einen Abschnitt **„Durchgespielt am …"** mit: Datum, Grösse der Sicherung, Dauer der Wiederherstellung, verglichene Zeilenzahlen, aufgetretene Warnungen und ob `sequenzen_richten` nötig war.

Und, mindestens so wichtig: **was dabei nicht funktioniert hat.** Ein Probelauf, der nur Erfolge festhält, ist eine Werbebroschüre. Die Stolpersteine sind der eigentliche Ertrag — sie stehen im Ernstfall zwischen einer halben Stunde und einem halben Tag.

---

## Abnahme

- Wiederherstellung in eine separate Datenbank durchgeführt, Produktion unberührt
- Zeilenzahlen Original gegen Wiederherstellung verglichen, Ergebnis dokumentiert
- Sequenzen geprüft: ein `INSERT` nach der Wiederherstellung funktioniert
- Medien mitgeprüft
- Dauer gemessen und notiert
- `backup_db` unter PostgreSQL entschieden und umgesetzt — sichert, bricht ab oder ist entfernt, meldet aber nie folgenlos Erfolg
- Probedatenbank danach entfernt
- Testsuite grün: `manage.py test` **ohne Labels**, Zahl gegen Discovery abgeglichen

---

## Danach

Von den drei Punkten vor der zweiten Organisation bleibt dann nur noch **2FA** — Fairwalter führt es in allen Preisstufen, im Bestand fehlt es.

Und ein Punkt, der in `SICHERUNG.md` selbst als offen benannt ist: **eine Kopie ausser Haus.** Solange Sicherung und Produktion auf demselben Konto liegen, trägt sie den Ausfall eines Datenträgers, aber nicht den Verlust des Kontos. Das ist ein externer Dienst mit Kosten — also eine Entscheidung für Dominik, kein Auftrag.
