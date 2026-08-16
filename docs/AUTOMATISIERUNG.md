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
| `bash deploy.sh` | zeitgesteuert | Holt `claude/fairwalter-rebuild`, migriert, sammelt statische Dateien, lädt die Web-App neu |

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

Der Grund liegt in der Reihenfolge, nicht in den Migrationen (die Sequenz
`benutzer_uebernahme` → `migrate` läuft aus dem Ausgangszustand sauber durch,
nachgespielt auf einer Kopie). `deploy.sh` holt den Code mit `git reset --hard`
**vor** der Migration. Scheitert die Migration, wird zwar nicht neu geladen —
aber auf der Platte liegt bereits der neue Code. Sobald der Hoster seinen
Worker von sich aus recycelt, lädt er ihn gegen das alte Schema.

**„Die alte Version bleibt aktiv" galt also nur für den laufenden Prozess,
nicht über einen Worker-Neustart hinweg.** Drei Änderungen schliessen das:

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
