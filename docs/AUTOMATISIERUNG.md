# Automatisierung — Scheduled Tasks (PythonAnywhere)

Die wiederkehrenden Prozesse laufen als Management-Commands und werden über die
**Scheduled Tasks** von PythonAnywhere zeitgesteuert (kein Celery nötig).

Basis-Kommando (Pfad/venv anpassen):
`cd ~/swiss-manager && python manage.py <command>`

| Command | Empfohlener Rhythmus | Wirkung |
|---------|---------------------|---------|
| `taeglicher_lauf` | täglich (z.B. 06:00) | Auto-Pendenzen aus Fristen (Vertragsende, Auszug, Geräte-Garantien) + Referenzzins/LIK-Update + Bereinigung der Bewerbungsdossiers (siehe unten) |
| `mahnlauf` | wöchentlich (z.B. Mo 07:00) | Sammel-Mahnlauf über alle fälligen Debitoren + Zahlungserinnerung per E-Mail. Optional `--zins` (5% Verzugszins), `--kein-versand` |
| `monatslauf` | monatlich (1. um 05:00) | Sollstellung (Mietenlauf) für den aktuellen Monat. `--jahr/--monat` überschreiben |
| `jahresabschluss_lauf` | jährlich (2. Januar) | Lineare Abschreibungen (AfA) + Erneuerungsfonds-Einlagen fürs Vorjahr. `--jahr` überschreibt |

Alle Läufe sind **idempotent** — mehrfaches Ausführen erzeugt keine Duplikate.
Jeder Lauf schreibt einen Eintrag ins Aktivitätslog (`AktivitaetsLog`).

Die Buttons in der App (Sollstellung, Mahnlauf) rufen dieselbe Logik
(`core/services/automation.py`) auf — Scheduler und manuelle Auslösung sind
deckungsgleich.

## Deploy

Auch das Ausrollen läuft als Scheduled Task, nicht von Hand:

| Task | Rhythmus | Wirkung |
|------|----------|---------|
| `bash deploy.sh` | Always-on-Task, Schleife alle 30 s | Holt `claude/fairwalter-rebuild`, migriert, sammelt statische Dateien, lädt die Web-App neu |

Der Always-on-Task besteht aus **einem Befehl ohne jede Shell-Konstruktion**:

```
bash /home/swissimmo/swiss-manager/deploy.sh --dauerlauf
```

Keine Schleife, keine Variablen, keine Anführungszeichen, keine zweite Zeile.
Das ist Absicht: Ein Task-Feld ist ein Ort ohne Versionierung, ohne
Syntaxprüfung und mit genau einer Zeile Platz. Die alte Fassung enthielt dort
ein vollständiges `while true; do … done` samt `&&`-Kette — erst war sie
inhaltlich falsch, dann startete die mehrzeilige Ersatzfassung gar nicht erst.
Schleife und Intervall stecken jetzt in `deploy.sh --dauerlauf` (Standard 30 s,
über `PA_INTERVALL` änderbar), wo sie im Git stehen und geprüft werden können.

**Den Python sucht sich das Skript selbst.** Der Reihe nach: `$PA_PY`,
`python`, `python3`, dann `$HOME/.virtualenvs/*/bin/python`. Genommen wird der
erste, der Django importieren kann — nicht der mit dem passenden Namen. Ein
gesetztes `PA_PY`, das nicht trägt, wird dabei **gemeldet** und nicht
stillschweigend übergangen: Der Ersatz mag funktionieren, aber wer den Wert
gesetzt hat, meinte ihn.

`deploy.sh` läuft alle 30 Sekunden und tut in aller Regel **nichts** — es
meldet `· nichts zu tun` und endet. Gearbeitet wird nur, wenn einer von **zwei**
Gründen vorliegt:

| Grund | Warum er dazugehört |
|---|---|
| **Neuer Commit** auf dem Branch | der Normalfall |
| **Offene Migrationen** | die Datenbank hängt hinterher — egal warum |

Der zweite ist der, der am 16.08.2026 gefehlt hat. Die alte Schleife fragte
**nur** nach einem neuen Commit; eine Datenbank, die aus irgendeinem Grund
hinter dem Code zurückblieb, wurde nie wieder eingeholt. Jetzt migriert der
Task von selbst, auch wenn sich am Code nichts geändert hat.

Kann der Migrationsstand gar nicht festgestellt werden, gilt das ebenfalls als
Grund zu laufen — nicht als „null offene". Ein Zähler, der bei einem Fehler
still 0 meldet, hätte dieselbe Bauart wie der Fehler, den er verhindern soll.

Die Web-App wird nur bei einem echten Lauf neu geladen. Sonst startete ein
30-Sekunden-Task die Anwendung alle 30 Sekunden durch.

Was gepusht ist, geht damit beim nächsten Lauf von selbst live — **inklusive
Migrationen**. Es gibt keinen separaten Migrationsschritt, den jemand von Hand
nachziehen müsste.

Der Ablauf ist bewusst absichernd: `git reset --hard` (liegengebliebene lokale
Dateien blockieren den Deploy nicht — die Produktionsdaten `db.sqlite3`,
`media/`, `staticfiles/` liegen nicht im Git), und **bei gescheiterter
Migration wird NICHT neu geladen**. Dann bleibt die alte Version aktiv, statt
eine halb migrierte auszuliefern.

### Ein Schritt vor `migrate`: `benutzer_uebernahme`

Seit Etappe 3 (15.08.2026) hat swissImmo ein eigenes Benutzermodell
(`benutzer.Benutzer`), das die bestehende Tabelle `auth_user` übernimmt. Auf
einer **Bestandsdatenbank** bricht `migrate` sonst ab, **bevor** überhaupt eine
Migration läuft:

```
InconsistentMigrationHistory: Migration admin.0001_initial is applied
before its dependency benutzer.0001_initial
```

Djangos Konsistenzprüfung greift vor allen Migrationen — keine Migration kann
das lösen. Deshalb ruft `deploy.sh` davor auf:

```
python manage.py benutzer_uebernahme
```

Der Command ist **idempotent**: Er benennt einmalig zwei Spalten um und trägt
`benutzer.0001_initial` als angewendet ein; danach — und auf jeder frischen
Datenbank — ist er ein Leerlauf. **Keine Datenzeile wird bewegt**, IDs,
Passwort-Hashes, Gruppen und Sitzungen bleiben unberührt. `--rueckwaerts` nimmt
ihn zurück, `--trocken` zeigt nur an.

Die Zusicherung oben gilt damit unverändert: Es gibt weiterhin keinen Schritt,
den jemand von Hand nachziehen müsste.

### Was am 16.08.2026 schiefging — und was daraus folgt

Die Startseite antwortete mit `OperationalError: no such table:
crm_mitgliedschaft`. Der neue Code war live, die Migrationen waren es nicht.

Die Migrationen sind nicht die Ursache: Die Sequenz `benutzer_uebernahme` →
`migrate` läuft aus dem Ausgangszustand sauber durch, auf einer Kopie
nachgespielt. Ursache war der **Always-on-Task**, der damals alles selbst tat,
statt `deploy.sh` aufzurufen:

```bash
while true; do cd ~/swiss-manager && git fetch -q origin … \
  && [ "$(git rev-parse HEAD)" != "$(git rev-parse FETCH_HEAD)" ] \
  && git reset --hard FETCH_HEAD && pip install -q -r requirements.txt \
  && python manage.py migrate --noinput && … ; sleep 30; done
```

Drei Fehler, die zusammen genau dieses Bild ergeben:

1. **`benutzer_uebernahme` fehlte.** `migrate` bricht auf einer
   Bestandsdatenbank deshalb mit `InconsistentMigrationHistory` ab — belegt
   durch Nachspielen auf einer Kopie.
2. **`git reset --hard` lief vorher und blieb stehen.** Der neue Code lag
   damit auf der Platte, das alte Schema in der Datenbank. Der laufende
   Prozess merkte nichts; der nächste Worker-Neustart lud den neuen Code gegen
   das alte Schema — der Fehler auf der Startseite.
3. **Die Schleife versuchte es nie wieder.** Nach dem `reset` gilt
   `HEAD == FETCH_HEAD`; der Test davor ist falsch, die `&&`-Kette bricht ab,
   bevor `migrate` überhaupt erneut aufgerufen wird. Alle 30 Sekunden aufs
   Neue — ein Deploy, der einmal scheitert, bleibt für immer halb.

Der Python-Pfad war übrigens korrekt. Eine erste Vermutung, es liege am
System-Python ohne Django, war falsch; erst der Blick auf den echten Task hat
es geklärt.

**„Die alte Version bleibt aktiv" galt nur für den laufenden Prozess, nicht
über einen Worker-Neustart hinweg.** Der Task ruft jetzt `deploy.sh` auf, und
dort schliessen drei Änderungen die Lücke:

1. **Django-Prüfung vor dem ersten Eingriff.** Ein Scheduled Task startet ohne
   aktiviertes virtualenv; ein blosses `python` ist dann der System-Python, in
   dem Django fehlt. Das wird jetzt gefragt, solange ein Abbruch folgenlos ist.
   Im Task deshalb den venv-Python angeben:
   `PA_PY=$HOME/.virtualenvs/myenv/bin/python bash deploy.sh`
2. **Rückrollen des Codes**, wenn Übernahme oder Migration scheitern. Danach
   passen Platte und Datenbank wieder zusammen — auch für den nächsten
   Worker-Neustart.
3. **Nachkontrolle**: `showmigrations --plan` nach dem `migrate`. Bleiben
   offene Schritte, obwohl der Befehl durchlief, wird ebenfalls
   zurückgerollt und nicht neu geladen.

Das Rückrollen macht die Schleife zugleich **selbstheilend**: Nach einem
Fehlschlag zeigt `HEAD` wieder auf den alten Stand, `HEAD != FETCH_HEAD` ist
erneut wahr, und der nächste Durchlauf probiert es in 30 Sekunden wieder. Ein
dauerhaft kaputter Commit führt damit zu einem Deploy-Versuch alle 30 Sekunden
— laut im Protokoll, aber die Website bleibt auf der alten, laufenden Version.
Das ist der Zustand, den man will: sichtbar kaputt statt still halb.

**Wiederherstellung von Hand**, falls es doch einmal auftritt:

```bash
cd ~/swiss-manager
~/.virtualenvs/myenv/bin/python manage.py benutzer_uebernahme
~/.virtualenvs/myenv/bin/python manage.py migrate
# danach die Web-App im Web-Tab neu laden
```

Welcher Stand gerade läuft: <https://swissimmo.pythonanywhere.com/version/>

### Media-Schutz-Prüfung am Ende jedes Deploys

Hochgeladene Dateien — Fotos aus Mieterwohnungen, gescannte Verträge, Belege —
liefert `core/views/media_protected.py` nur an angemeldete Team-Mitglieder aus.
Diese Schranke greift jedoch **nur, wenn die /media/-Anfragen bei Django
ankommen**. Ist `/media/` im Web-Tab von PythonAnywhere als statisches
Verzeichnis gemappt, liefert deren Webserver die Dateien direkt aus; der View
wird nie aufgerufen und der Schutz ist wirkungslos — ohne jedes Anzeichen.

Aus dem Code heraus lässt sich das nicht feststellen. Deshalb prüft `deploy.sh`
es nach dem Reload von aussen:

```
python manage.py pruefe_media_schutz
```

Der Befehl legt kurz eine Kanarienvogel-Datei unter einem geschützten Prefix
ab, ruft sie ohne Anmeldung über ihre öffentliche URL auf und löscht sie wieder.
Kommt der Dateiinhalt zurück, steht der Befund im Deploy-Protokoll:

```
✗ MEDIA-SCHUTZ WIRKUNGSLOS
```

Dann im Web-Tab das statische Mapping für `/media/` entfernen. Für `/static/`
bleibt es richtig — dort liegen nur öffentliche Assets.

---

## Aufbewahrung von Personendaten (DSG)

Zwei Automatismen, die Personendaten wieder loswerden. Beide sind nötig, weil
sie unterschiedliche Menschen betreffen.

### Bewerbungsdossiers — läuft täglich mit

Ein Dossier enthält Ausweiskopie, Lohnausweis, Betreibungsauszug, dazu
Geburtsdatum, Nationalität, Zivilstand, Einkommen, Arbeitgeber und Kinder —
die heikelsten Daten der Anwendung. Die Wohnung bekommt **eine** Bewerberin;
alle übrigen Dossiers stammen von Menschen ohne jedes Vertragsverhältnis zur
Verwaltung und sind nach dem Entscheid zwecklos. Das DSG verlangt dann
Vernichtung oder Anonymisierung (Art. 6 Abs. 4); eine Aufbewahrungspflicht wie
für Buchungsbelege (Art. 958f OR) besteht hier gerade **nicht**.

| Nach dem Entscheid | Was geschieht |
|---|---|
| 7 Tage | Die hochgeladenen Dateien werden gelöscht. Der EDÖB verlangt Vernichtung «möglichst rasch»; die wenigen Tage sind Nachlauf für den Versand der Absagen, keine Aufbewahrung. |
| 365 Tage | Das ganze Dossier wird anonymisiert. Die Hülle bleibt, damit nachvollziehbar ist, wie viele Bewerbungen ein Objekt hatte. |

Als «entschieden» gilt eine Bewerbung, die **abgelehnt** wurde — oder deren
Objekt **inzwischen vermietet** ist. Der zweite Weg ist in der Praxis der
häufigere: Wer keine Absage verschickt, hat trotzdem entschieden. Ohne ihn
bliebe der grösste Teil der Dossiers für immer liegen.

Nicht angetastet wird, wer die **Zusage** erhalten hat — daraus entsteht das
Mietverhältnis. Diese Daten laufen über die Personen-Anonymisierung.

```
python manage.py bewerbungen_bereinigen             # Vorschau
python manage.py bewerbungen_bereinigen --apply     # ausführen
python manage.py bewerbungen_bereinigen --dokumente-tage 3 --anonym-tage 180 --apply
```

### Ehemalige Mieterinnen und Mieter — von Hand anstossen

```
python manage.py dsg_anonymisieren            # Vorschau
python manage.py dsg_anonymisieren --apply    # ausführen
```

Anonymisiert Personen, deren letztes Mietverhältnis vor mehr als 10 Jahren
endete (`--jahre`), die kein aktives Verhältnis und keine offenen Forderungen
mehr haben. Die **Buchungsbelege bleiben** — sie unterliegen der zehnjährigen
Aufbewahrungspflicht (Art. 958f OR). Deshalb wird die Person nicht gelöscht,
sondern ihre Stammdaten werden anonymisiert: Die Revision kann die Historie
weiter prüfen, der Personenbezug ist aber weg.

Bewusst **nicht** im täglichen Lauf: Diese Anonymisierung ist endgültig und
betrifft Menschen mit einer Vertragsgeschichte. Sie soll jemand auslösen, der
vorher in die Vorschau geschaut hat.
