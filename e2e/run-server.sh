#!/bin/bash
# Bootet Django für die Playwright-E2E-Tests: separate SQLite-DB, migrieren,
# deterministisch seeden, dann runserver. DEBUG=True + SECURE_SSL_REDIRECT=False,
# damit der Login über HTTP funktioniert (CSRF-/Secure-Cookie sonst blockiert).
set -euo pipefail
cd "$(dirname "$0")/.."

export DJANGO_SETTINGS_MODULE=swiss_immo.settings
export DEBUG=True
export SECURE_SSL_REDIRECT=False
export SQLITE_NAME="${SQLITE_NAME:-$PWD/e2e_db.sqlite3}"
export EXTRA_ALLOWED_HOSTS="127.0.0.1,localhost"

rm -f "$SQLITE_NAME"
python manage.py migrate -v0
python manage.py seed_e2e
exec python manage.py runserver 127.0.0.1:8811 --noreload
