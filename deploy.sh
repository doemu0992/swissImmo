#!/usr/bin/env bash
# Deploy auf PythonAnywhere.
#
# Zieht den aktuellen Stand des Branches, wendet Migrationen an, sammelt die
# statischen Dateien und lädt die Web-App neu.
#
# Aufruf in der PythonAnywhere-Bash-Konsole (im Repo-Ordner):
#     bash deploy.sh
# Optional anderer Branch:
#     bash deploy.sh mein/anderer-branch
#
# Für den automatischen Reload muss ggf. der Pfad zur WSGI-Datei gesetzt sein:
#     PA_WSGI=/var/www/DEINNAME_pythonanywhere_com_wsgi.py bash deploy.sh
set -euo pipefail

cd "$(dirname "$0")"
BRANCH="${1:-claude/fairwalter-rebuild}"

echo "→ git pull origin $BRANCH"
git pull origin "$BRANCH"

echo "→ python manage.py migrate"
python manage.py migrate --noinput

echo "→ python manage.py collectstatic"
python manage.py collectstatic --noinput

# Web-App neu laden = WSGI-Datei „berühren". Pfad über $PA_WSGI überschreibbar;
# Standard rät ihn aus dem Benutzernamen (Standard-Domain <user>.pythonanywhere.com).
WSGI="${PA_WSGI:-/var/www/${USER}_pythonanywhere_com_wsgi.py}"
if [ -f "$WSGI" ]; then
    touch "$WSGI"
    echo "→ Web-App neu geladen ($WSGI)"
else
    echo "⚠ WSGI-Datei nicht gefunden ($WSGI)."
    echo "  Bitte einmal manuell im Web-Tab auf «Reload» klicken —"
    echo "  oder PA_WSGI mit dem korrekten Pfad setzen und erneut ausführen."
fi

echo "✓ Deploy fertig."
