"""Laufzeit-Version des tatsächlich geladenen Prozesses.

Der Commit wird beim ERSTEN Aufruf erfasst (Prozess-Import) und via lru_cache
für die Lebensdauer des Workers eingefroren. Dadurch zeigt `/version/` den
Stand, der WIRKLICH läuft — nicht bloss, was auf der Platte liegt. Wurde der
Code gepullt, aber die Web-App NICHT neu geladen, serviert der alte Worker
weiterhin den alten Commit → man sieht sofort, dass der Reload fehlte.
"""
import functools
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Zeitpunkt, an dem dieser Worker-Prozess dieses Modul importiert hat.
PROCESS_STARTED = datetime.now(timezone.utc)


def _read_head_from_files():
    """Fallback ohne git-Binary: .git/HEAD + Ref (loose oder packed) lesen."""
    git = BASE_DIR / '.git'
    try:
        head = (git / 'HEAD').read_text().strip()
    except OSError:
        return None, None
    if not head.startswith('ref:'):
        return head, '(detached)'
    ref = head.split(' ', 1)[1].strip()
    branch = ref.rsplit('/', 1)[-1]
    loose = git / ref
    if loose.exists():
        return loose.read_text().strip(), branch
    packed = git / 'packed-refs'
    if packed.exists():
        for line in packed.read_text().splitlines():
            if line.strip().endswith(ref):
                return line.split(' ', 1)[0].strip(), branch
    return None, branch


@functools.lru_cache(maxsize=1)
def deployed_version():
    """Commit-Hash + Branch des laufenden Prozesses (eingefroren beim Start)."""
    commit = branch = None
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=BASE_DIR, text=True,
            stderr=subprocess.DEVNULL, timeout=5).strip()
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=BASE_DIR, text=True,
            stderr=subprocess.DEVNULL, timeout=5).strip()
    except (subprocess.SubprocessError, OSError):
        commit, branch = _read_head_from_files()
    return {
        'commit': (commit or 'unknown')[:10],
        'commit_full': commit or 'unknown',
        'branch': branch or 'unknown',
        'process_started': PROCESS_STARTED.isoformat(timespec='seconds'),
    }
