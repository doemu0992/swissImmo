# Automatisierung — Scheduled Tasks (PythonAnywhere)

Die wiederkehrenden Prozesse laufen als Management-Commands und werden über die
**Scheduled Tasks** von PythonAnywhere zeitgesteuert (kein Celery nötig).

Basis-Kommando (Pfad/venv anpassen):
`cd ~/swiss-manager && python manage.py <command>`

| Command | Empfohlener Rhythmus | Wirkung |
|---------|---------------------|---------|
| `taeglicher_lauf` | täglich (z.B. 06:00) | Auto-Pendenzen aus Fristen (Vertragsende, Auszug, Geräte-Garantien) + Referenzzins/LIK-Update |
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

Welcher Stand gerade läuft: <https://swissimmo.pythonanywhere.com/version/>
