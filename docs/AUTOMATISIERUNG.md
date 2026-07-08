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

Alle Läufe sind **idempotent** — mehrfaches Ausführen erzeugt keine Duplikate.
Jeder Lauf schreibt einen Eintrag ins Aktivitätslog (`AktivitaetsLog`).

Die Buttons in der App (Sollstellung, Mahnlauf) rufen dieselbe Logik
(`core/services/automation.py`) auf — Scheduler und manuelle Auslösung sind
deckungsgleich.
