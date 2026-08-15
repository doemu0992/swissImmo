#!/usr/bin/env bash
# Deploy auf PythonAnywhere — selbstheilend.
#
# Holt den aktuellen Stand des Branches HART (fetch + reset --hard, damit stray
# Dateien / lokale Änderungen den Deploy NICHT mehr blockieren), installiert
# Abhängigkeiten, wendet Migrationen an, sammelt statische Dateien und lädt die
# Web-App neu.
#
# Sicher, weil die Produktionsdaten NICHT im Git liegen (db.sqlite3, media/,
# staticfiles/ sind .gitignore) — reset --hard fasst sie nicht an.
#
# Aufruf (im Repo-Ordner):        bash deploy.sh
# Anderer Branch:                 bash deploy.sh mein/anderer-branch
# WSGI-Pfad überschreiben:        PA_WSGI=/var/www/DEIN_wsgi.py bash deploy.sh
# Anderer Python (venv):          PA_PY=/home/USER/.virtualenvs/ENV/bin/python bash deploy.sh
set -uo pipefail

cd "$(dirname "$0")"
BRANCH="${1:-claude/fairwalter-rebuild}"
PY="${PA_PY:-python}"

# Repo-Umzug abfangen: Remote fest auf die kanonische neue URL setzen.
CANONICAL="https://github.com/doemu0992/swissImmo.git"
CUR_URL="$(git remote get-url origin 2>/dev/null || echo '')"
case "$CUR_URL" in
    *doemu0992/swissimmo*|*doemu0992/swissImmo*)
        if [ "$CUR_URL" != "$CANONICAL" ]; then
            echo "→ Remote auf neue URL setzen ($CANONICAL)"
            git remote set-url origin "$CANONICAL" || true
        fi ;;
esac

echo "→ git fetch origin $BRANCH"
if ! git fetch origin "$BRANCH"; then
    echo "✗ git fetch fehlgeschlagen — Abbruch (alte Version bleibt aktiv)."; exit 1
fi

echo "→ git reset --hard origin/$BRANCH"
git reset --hard "origin/$BRANCH" || { echo "✗ reset fehlgeschlagen."; exit 1; }
DEPLOY_COMMIT="$(git rev-parse --short HEAD)"
echo "  jetzt auf Commit $DEPLOY_COMMIT"

echo "→ pip install -r requirements.txt"
"$PY" -m pip install -q -r requirements.txt || echo "⚠ pip install meldete Fehler — fahre fort."

# Seit Etappe 3 hat swissImmo ein eigenes Benutzermodell (benutzer.Benutzer),
# das die bestehende Tabelle auth_user übernimmt. Auf einer Bestandsdatenbank
# bricht `migrate` sonst ab, BEVOR eine Migration läuft:
#   InconsistentMigrationHistory: admin.0001_initial is applied before its
#   dependency benutzer.0001_initial
# Keine Migration kann das lösen — Djangos Konsistenzprüfung greift davor.
# Der Command ist idempotent: Er tut genau einmal etwas und ist danach (und auf
# jeder frischen Datenbank) ein Leerlauf.
#
# Einschränkung, die für DIESEN einen Umschalt-Deploy gilt: Weiter unten steht
# "bei gescheiterter Migration bleibt die alte Version aktiv". Das galt
# uneingeschränkt, solange `migrate` an der Konsistenzprüfung abbrach, BEVOR es
# die Datenbank anfasste. Jetzt läuft die Übernahme davor. Gelingt sie und
# scheitert `migrate` danach, sind die zwei Spalten bereits umbenannt und der
# noch laufende alte WSGI-Prozess liest gegen ein Schema, das er nicht kennt —
# "alte Version bleibt aktiv" heisst dann "alte Version liefert 500", bis der
# nächste Deploy durchläuft. Scheitert dagegen die Übernahme selbst, ist die
# Datenbank unberührt und die Zusicherung gilt wie zuvor.
echo "→ manage.py benutzer_uebernahme"
if ! "$PY" manage.py benutzer_uebernahme; then
    echo "✗ Benutzer-Übernahme fehlgeschlagen — KEIN Reload (alte Version bleibt aktiv)."; exit 1
fi

echo "→ manage.py migrate"
if ! "$PY" manage.py migrate --noinput; then
    echo "✗ migrate fehlgeschlagen — KEIN Reload (alte Version bleibt aktiv)."; exit 1
fi

echo "→ manage.py collectstatic"
"$PY" manage.py collectstatic --noinput || echo "⚠ collectstatic meldete Fehler — fahre fort."

# Web-App neu laden = WSGI-Datei „berühren".
WSGI="${PA_WSGI:-/var/www/${USER}_pythonanywhere_com_wsgi.py}"
if [ -f "$WSGI" ]; then
    touch "$WSGI"
    echo "→ Web-App neu geladen ($WSGI) — Commit $DEPLOY_COMMIT ist live."
else
    echo "⚠ WSGI-Datei nicht gefunden ($WSGI)."
    echo "  PA_WSGI mit dem korrekten Pfad setzen — sonst läuft weiter die alte Version."
    exit 1
fi

# Der Zugriffsschutz für /media/ greift nur, wenn die Anfragen bei Django
# ankommen. Ist /media/ beim Hoster als statisches Verzeichnis gemappt, liefert
# der Webserver die Dateien direkt aus — sensible Uploads wären dann für jeden
# mit der URL abrufbar, ohne dass es irgendwo auffällt. Deshalb nach dem Reload
# ein Test von aussen. Schlägt er an, steht der Befund im Deploy-Protokoll.
# Webhook-Secrets: Die Endpunkte weisen ohne Secret ab (fail-closed). Wer eine
# Integration bisher ohne Secret betrieben hat, verliert sonst lautlos den
# Rücklauf — bei DocuSeal die Ablage unterschriebener Verträge.
echo "→ manage.py pruefe_webhook_secrets"
"$PY" manage.py pruefe_webhook_secrets || true

echo "→ manage.py pruefe_media_schutz"
"$PY" manage.py pruefe_media_schutz || echo "⚠ Media-Schutz-Prüfung meldete einen Befund (siehe oben)."

echo "✓ Deploy fertig — prüfen auf https://swissimmo.pythonanywhere.com/version/"
