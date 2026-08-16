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

# Trägt dieser Python überhaupt das Projekt? Ein Scheduled Task startet ohne
# aktiviertes virtualenv; ein blosses `python` ist dann der System-Python, in
# dem Django fehlt. Der Deploy holt trotzdem den neuen Code, `migrate`
# scheitert, es wird nicht neu geladen — und beim nächsten Worker-Neustart
# läuft neuer Code gegen ein altes Schema. Deshalb VOR dem `reset --hard`
# fragen, solange ein Abbruch noch folgenlos ist.
if ! "$PY" -c "import django" 2>/dev/null; then
    echo "✗ '$PY' kann Django nicht importieren — Abbruch, BEVOR etwas angefasst wird."
    echo "  Im Scheduled Task den Python des virtualenv angeben, z.B.:"
    echo "  PA_PY=\$HOME/.virtualenvs/myenv/bin/python bash deploy.sh"
    exit 1
fi

echo "→ git fetch origin $BRANCH"
if ! git fetch origin "$BRANCH"; then
    echo "✗ git fetch fehlgeschlagen — Abbruch (alte Version bleibt aktiv)."; exit 1
fi

# Stand VOR dem Umschalten merken. Er wird gebraucht, wenn die Migration
# scheitert — siehe `zurueckrollen` unten.
VORHER_COMMIT="$(git rev-parse HEAD)"

# ---------------------------------------------------------------------------
# ZWEI GRUENDE, ETWAS ZU TUN — NICHT NUR EINER
#
# Der Always-on-Task fragte bis zum 16.08.2026 nur: „gibt es einen neuen
# Commit?" Damit war eine Datenbank, die aus IRGENDEINEM Grund hinter dem Code
# zurueckliegt, fuer immer verloren: Kein neuer Commit heisst kein Deploy,
# heisst kein `migrate`. Genau so blieb die Produktion mit neuem Code auf
# altem Schema stehen und meldete `no such table: crm_mitgliedschaft`.
#
# Deshalb sind es hier ZWEI Bedingungen. Offene Migrationen loesen einen Lauf
# auch dann aus, wenn sich am Code nichts geaendert hat — der Deploy holt die
# Datenbank von selbst wieder ein.
#
# Und nur wenn eine davon zutrifft, wird die Web-App am Ende neu geladen.
# Sonst wuerde ein Task, der alle 30 s laeuft, die Anwendung alle 30 s
# durchstarten.
# ---------------------------------------------------------------------------
NEUER_CODE=0
[ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$BRANCH")" ] && NEUER_CODE=1

# Zaehlt die noch nicht angewendeten Migrationen. Wichtig ist der Fehlerfall:
# Laesst sich das gar nicht feststellen, wird das NICHT als „null offene"
# gewertet, sondern als Grund, den Deploy laufen zu lassen. Ein Zaehler, der
# bei einem Fehler still 0 meldet, haette dieselbe Bauart wie der Bug, den er
# verhindern soll — er wuerde schweigen, wenn es darauf ankommt.
#
# (Geprueft: `showmigrations --plan` laeuft auch auf einer Datenbank, die noch
# vor der Benutzer-Uebernahme steht — anders als `migrate`, das dort mit
# InconsistentMigrationHistory abbricht. Der Zaehler meldet dort korrekt 8.)
offene_migrationen() {
    local ausgabe
    if ! ausgabe="$("$PY" manage.py showmigrations --plan 2>/dev/null)"; then
        echo "unbekannt"; return
    fi
    printf '%s\n' "$ausgabe" | grep -c '^\[ \]' || true
}
OFFEN="$(offene_migrationen)"

if [ "$OFFEN" = "unbekannt" ]; then
    echo "⚠ Migrationsstand nicht feststellbar — Deploy laeuft trotzdem."
    OFFEN=1
fi

if [ "$NEUER_CODE" = "0" ] && [ "${OFFEN:-0}" -eq 0 ]; then
    echo "· nichts zu tun (Code aktuell, keine offenen Migrationen)"
    exit 0
fi
[ "${OFFEN:-0}" -gt 0 ] && echo "→ ${OFFEN} offene Migration(en) — Lauf auch ohne neuen Commit"

if [ "$NEUER_CODE" = "1" ]; then
    echo "→ git reset --hard origin/$BRANCH"
    git reset --hard "origin/$BRANCH" || { echo "✗ reset fehlgeschlagen."; exit 1; }
fi
DEPLOY_COMMIT="$(git rev-parse --short HEAD)"
echo "  jetzt auf Commit $DEPLOY_COMMIT"

# ---------------------------------------------------------------------------
# WARUM DER CODE ZURUECKGEROLLT WIRD, WENN DIE MIGRATION SCHEITERT
#
# Die frühere Fassung sagte: „bei gescheiterter Migration wird NICHT neu
# geladen — die alte Version bleibt aktiv." Das stimmte nur für den laufenden
# Prozess. Auf der Platte lag nach `git reset --hard` bereits der NEUE Code.
# Sobald der Hoster seinen Worker recycelt — und das tut er von sich aus —
# lädt er den neuen Code gegen das ALTE Schema.
#
# Real passiert am 16.08.2026: `no such table: crm_mitgliedschaft` auf der
# Startseite, obwohl kein Reload angestossen wurde.
#
# Deshalb: Scheitert ein Schritt, der die Datenbank braucht, geht der Code auf
# den vorherigen Stand zurück. Damit passen Platte und Datenbank wieder
# zusammen, und die Zusicherung stimmt auch über einen Worker-Neustart hinweg.
# ---------------------------------------------------------------------------
zurueckrollen() {
    echo "✗ $1"
    echo "→ Code zurück auf $(git rev-parse --short "$VORHER_COMMIT") — sonst laedt der"
    echo "  naechste Worker-Neustart neuen Code gegen ein altes Schema."
    git reset --hard "$VORHER_COMMIT" || echo "⚠ Rueckrollen fehlgeschlagen — VON HAND pruefen!"
    exit 1
}

if [ "$NEUER_CODE" = "1" ]; then
    echo "→ pip install -r requirements.txt"
    "$PY" -m pip install -q -r requirements.txt || echo "⚠ pip install meldete Fehler — fahre fort."
fi

# Seit Etappe 3 hat swissImmo ein eigenes Benutzermodell (benutzer.Benutzer),
# das die bestehende Tabelle auth_user übernimmt. Auf einer Bestandsdatenbank
# bricht `migrate` sonst ab, BEVOR eine Migration läuft:
#   InconsistentMigrationHistory: admin.0001_initial is applied before its
#   dependency benutzer.0001_initial
# Keine Migration kann das lösen — Djangos Konsistenzprüfung greift davor.
# Der Command ist idempotent: Er tut genau einmal etwas und ist danach (und auf
# jeder frischen Datenbank) ein Leerlauf.
#
# Scheitert die Übernahme, ist die Datenbank unberührt und `zurueckrollen`
# stellt den alten Code wieder her.
echo "→ manage.py benutzer_uebernahme"
if ! "$PY" manage.py benutzer_uebernahme; then
    zurueckrollen "Benutzer-Übernahme fehlgeschlagen — KEIN Reload."
fi

echo "→ manage.py migrate"
if ! "$PY" manage.py migrate --noinput; then
    zurueckrollen "migrate fehlgeschlagen — KEIN Reload."
fi

# Absicherung gegen den Fall, der am 16.08.2026 die Startseite lahmlegte: Der
# Deploy meldete Erfolg, aber `migrate` war gar nicht gelaufen (falscher
# Python, kein Django im Pfad). `showmigrations --plan` listet dann offene
# Schritte. Ein Deploy, der ausstehende Migrationen zurücklaesst, darf nicht
# neu laden.
NACHHER="$(offene_migrationen)"
if [ "${NACHHER:-0}" -gt 0 ]; then
    zurueckrollen "$NACHHER Migration(en) nicht angewendet, obwohl migrate durchlief."
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
