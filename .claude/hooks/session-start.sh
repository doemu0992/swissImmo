#!/bin/bash
# SessionStart-Hook: installiert die Python-Abhängigkeiten, damit Web-Sessions
# sofort `manage.py check`/`test` fahren können (ohne manuelles pip-Install nach
# jedem Container-Start). Idempotent, nicht-interaktiv.
set -euo pipefail

# Nur in der Remote-Umgebung (Claude Code on the web) laufen — lokal ist die
# Umgebung des Entwicklers massgeblich.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

python -m pip install --disable-pip-version-check --quiet --upgrade pip >/dev/null 2>&1 || true

# Requirements installieren. Der --ignore-installed-Fallback fängt den bekannten
# Fall ab, dass eine distutils-vorinstallierte Systemabhängigkeit (z.B. PyYAML)
# den Upgrade blockiert.
if ! python -m pip install --disable-pip-version-check -r requirements.txt; then
  echo "pip: Standard-Install fehlgeschlagen — versuche mit --ignore-installed PyYAML" >&2
  python -m pip install --disable-pip-version-check --ignore-installed PyYAML -r requirements.txt
fi

echo "SessionStart-Hook fertig: Abhängigkeiten installiert."
