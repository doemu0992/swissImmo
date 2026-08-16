#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Umzug SQLite → PostgreSQL. Einmalig, auf der Produktion.
#
# Der Umzug ist NICHT `migrate` — das legt nur leere Tabellen an. Die Daten
# müssen hinüber, und dabei gibt es genau zwei Stellen, an denen so ein Umzug
# still schiefgeht:
#
#   1. Die Sequenzen. SQLite vergibt IDs anders als Postgres. Nach dem Laden
#      steht der Zähler auf 1, obwohl schon 1'050 Buchungen da sind — die
#      nächste neue Buchung kollidiert mit einer bestehenden ID. Es funktioniert
#      alles, bis jemand den ersten neuen Datensatz anlegt. Schritt 6 behebt das.
#
#   2. Die Umgebungsvariablen. Auf PythonAnywhere hat JEDER Prozess seine
#      eigenen: Web-App, Always-on-Task und Konsole. Setzt man sie nur im
#      Web-Tab, läuft die Website auf Postgres und der Deploy migriert weiter
#      die SQLite-Datei — er meldet Erfolg, die Website bekommt die Migration
#      nie. Dagegen steht `.datenbank-erwartet` im Repo; `deploy.sh` bricht ab,
#      wenn die tatsächliche Engine nicht dazu passt.
#
# AUFRUF (Bash-Konsole auf PythonAnywhere, im Projektordner):
#
#     bash umzug_postgres.sh
#
# Vorher gesetzt sein müssen (in DIESER Konsole):
#     export DB_ENGINE=postgres
#     export DB_NAME=swissimmo DB_USER=super DB_PASSWORD=...
#     export DB_HOST=swissimmo-5420.postgres.pythonanywhere-services.com
#     export DB_PORT=15420
#
# Das Skript ändert an der SQLite-Datei NICHTS. Geht etwas schief, ist der
# Rückweg: Umgebungsvariablen entfernen, Web-App neu laden — die alte Datenbank
# ist unberührt.
# ---------------------------------------------------------------------------
set -uo pipefail
cd "$(dirname "$0")"

PY="${PA_PY:-$HOME/.virtualenvs/myenv/bin/python}"
STAND="$HOME/umzug-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$STAND"

echo "→ Arbeitsordner: $STAND"

# --- 1. Sicherung ----------------------------------------------------------
# Die SQLite-Datei IST der ganze Bestand. Vor allem anderen eine Kopie.
if [ -f db.sqlite3 ]; then
    cp db.sqlite3 "$STAND/db.sqlite3"
    echo "✓ Sicherung: $STAND/db.sqlite3 ($(du -h db.sqlite3 | cut -f1))"
else
    echo "✗ db.sqlite3 nicht gefunden — im falschen Ordner?"; exit 1
fi

# --- 2. Zählen, solange noch SQLite gilt -----------------------------------
# `env -u` entfernt die Postgres-Variablen NUR für diesen Aufruf.
echo "→ Bestand auf SQLite zählen"
if ! env -u DB_ENGINE "$PY" manage.py bestand_zaehlen > "$STAND/vorher.txt"; then
    echo "✗ Zählen auf SQLite fehlgeschlagen."; exit 1
fi
echo "  $(wc -l < "$STAND/vorher.txt") Modelle erfasst"

# --- 3. Daten ausspielen ---------------------------------------------------
# Ohne contenttypes/permissions/sessions: Django legt sie auf der Zieldatenbank
# selbst an, mit eigenen IDs. Sie mitzunehmen erzeugt Kollisionen. Geprüft: Das
# Projekt hat KEINE Fremdschlüssel auf ContentType, es hängt also nichts daran.
echo "→ Daten ausspielen (dumpdata)"
if ! env -u DB_ENGINE "$PY" manage.py dumpdata \
        --exclude contenttypes --exclude auth.Permission \
        --exclude sessions.Session --exclude admin.logentry \
        --indent 1 -o "$STAND/daten.json"; then
    echo "✗ dumpdata fehlgeschlagen — SQLite unberührt, nichts passiert."; exit 1
fi
echo "  $(du -h "$STAND/daten.json" | cut -f1)"

# --- 4. Zieldatenbank prüfen und aufbauen ----------------------------------
if [ "${DB_ENGINE:-}" != "postgres" ] && [ "${DB_ENGINE:-}" != "postgresql" ]; then
    echo "✗ DB_ENGINE steht nicht auf postgres — die Variablen fehlen in DIESER Konsole."
    echo "  Der Umzug bricht hier ab, BEVOR etwas geschrieben wird."
    exit 1
fi
echo "→ Ziel: ${DB_ENGINE} auf ${DB_HOST:-?}:${DB_PORT:-?}/${DB_NAME:-?}"

echo "→ migrate auf der Zieldatenbank"
if ! "$PY" manage.py migrate --noinput; then
    echo "✗ migrate auf Postgres fehlgeschlagen. SQLite ist unberührt —"
    echo "  Umgebungsvariablen entfernen, dann läuft alles weiter wie bisher."
    exit 1
fi

# --- 5. Daten einlesen -----------------------------------------------------
echo "→ Daten einlesen (loaddata)"
if ! "$PY" manage.py loaddata "$STAND/daten.json"; then
    echo "✗ loaddata fehlgeschlagen. SQLite ist unberührt."
    echo "  Die Postgres-Datenbank ist jetzt halb gefüllt — vor einem zweiten"
    echo "  Versuch leeren: manage.py flush --noinput"
    exit 1
fi

# --- 6. Sequenzen zurücksetzen — DER kritische Schritt ---------------------
# Ohne das steht jeder ID-Zähler auf 1, obwohl die Tabellen voll sind. Der
# erste neue Datensatz kollidiert dann mit einer bestehenden ID. Der Fehler
# tritt NICHT beim Umzug auf, sondern beim ersten Schreibzugriff danach — und
# sieht dort aus wie ein Programmfehler, nicht wie ein Umzugsproblem.
echo "→ Sequenzen zurücksetzen"
APPS=$("$PY" -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','swiss_immo.settings'); django.setup()
from django.apps import apps
print(' '.join(a.label for a in apps.get_app_configs()
                if a.models_module is not None))
")
if ! "$PY" manage.py sqlsequencereset $APPS > "$STAND/sequenzen.sql"; then
    echo "✗ sqlsequencereset fehlgeschlagen."; exit 1
fi
if ! "$PY" manage.py dbshell < "$STAND/sequenzen.sql"; then
    echo "✗ Sequenzen konnten nicht gesetzt werden — NICHT in Betrieb nehmen."
    echo "  Ohne diesen Schritt kollidiert der erste neue Datensatz."
    exit 1
fi
echo "  $(grep -c setval "$STAND/sequenzen.sql") Sequenzen gesetzt"

# --- 7. Nachzählen und vergleichen ----------------------------------------
echo "→ Bestand auf Postgres gegen SQLite prüfen"
if ! "$PY" manage.py bestand_zaehlen --pruefe "$STAND/vorher.txt"; then
    echo
    echo "✗ DER BESTAND WEICHT AB. Nicht in Betrieb nehmen."
    echo "  SQLite ist unberührt: Umgebungsvariablen entfernen, Web-App neu laden."
    exit 1
fi

echo
echo "✓ Umzug abgeschlossen. Was jetzt noch fehlt:"
echo
echo "  1. Umgebungsvariablen an ALLEN DREI Stellen setzen:"
echo "     · Web  → Environment variables   (die Web-App)"
echo "     · den Always-on-Task neu starten (er erbt sie NICHT vom Web-Tab —"
echo "       sie gehören in ~/.bashrc oder in die Task-Zeile)"
echo "     · diese Konsole (hier stehen sie schon)"
echo
echo "  2. In .datenbank-erwartet 'engine = sqlite' auf 'engine = postgres'"
echo "     aendern und pushen. Ab dann bricht deploy.sh ab, statt still die"
echo "     falsche Datenbank zu migrieren."
echo
echo "     Reihenfolge beachten: Erst die Variablen setzen und den Task neu"
echo "     starten, dann pushen. Andersherum schlaegt der Deploy fehl — was"
echo "     richtig ist, aber unnoetig Laerm macht."
echo
echo "  3. Web-App neu laden und /version/ pruefen."
echo
echo "  Rückweg jederzeit: Variablen entfernen, neu laden. SQLite liegt"
echo "  unberührt in $STAND/db.sqlite3 und im Projektordner."
