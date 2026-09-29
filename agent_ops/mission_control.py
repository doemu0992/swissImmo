import os, re, json, time, glob, shutil, subprocess, threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
TASKS_FILE = os.path.join(BASE, 'tasks.json')
CLAUDE_PROJECTS = os.environ.get('CLAUDE_PROJECTS_DIR', os.path.expanduser('~/.claude/projects'))

DEPARTMENTS = ["Engineering", "QA", "DevOps", "Marketing & Docs"]

# Welche echten Agenten (.claude/agents und eingebaute Typen) zu welcher Abteilung zählen
AGENT_DEPARTMENT = {
    'javris': 'Engineering', 'coder': 'Engineering', 'ui-ux': 'Engineering', 'api': 'Engineering',
    'erweiterungen': 'Engineering', 'chirurg': 'Engineering', 'zerleger': 'Engineering',
    'migrations-handwerker': 'Engineering', 'general-purpose': 'Engineering', 'Plan': 'Engineering',
    'testabteilung': 'QA', 'mandanten-auditor': 'QA', 'datenschutz': 'QA',
    'aufraeumer': 'DevOps', 'statusline-setup': 'DevOps',
    'Explore': 'Marketing & Docs', 'claude-code-guide': 'Marketing & Docs',
}

SESSION_ACTIVE_SEC = 5 * 60      # Sitzung gilt als aktiv, wenn ihr Protokoll so frisch ist
SUBAGENT_STALE_SEC = 60 * 60     # ein Agent-Aufruf ohne Ergebnis gilt so lange als laufend
BRANCH_ACTIVE_SEC = 30 * 60      # Branch gilt als aktiv, wenn der letzte Commit so frisch ist
SYNC_EVERY_SEC = 60              # git fetch und gh pr list
SESSION_WINDOW_SEC = 7 * 86400   # ältere Protokolle werden nicht gelesen
TAIL_BYTES = 4 * 1024 * 1024     # von grossen Protokollen nur das Ende lesen


# ---------- Aufgaben ----------

def read_json():
    if not os.path.exists(TASKS_FILE):
        write_json([])
    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(data):
    with open(TASKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/tasks', methods=['GET', 'POST'])
def handle_tasks():
    tasks = read_json()
    if request.method == 'POST':
        new_task = request.json
        new_task['id'] = max((t['id'] for t in tasks), default=0) + 1
        new_task['status'] = 'To Do'
        new_task['created_at'] = int(time.time())
        tasks.append(new_task)
        write_json(tasks)
        return jsonify(new_task)
    return jsonify(tasks)

@app.route('/api/tasks/<int:task_id>', methods=['PATCH'])
def update_task(task_id):
    tasks = read_json()
    for t in tasks:
        if t['id'] == task_id:
            t['status'] = request.json.get('status', t['status'])
            write_json(tasks)
            return jsonify(t)
    return jsonify({'error': 'Not found'}), 404


# ---------- Git und GitHub ----------

def git(*args, timeout=10):
    try:
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 1, '', str(e))

SYNC = {'last_fetch': None, 'fetch_error': None, 'gh': shutil.which('gh') is not None, 'prs': {}}
_sync_lock = threading.Lock()
_sync_started = False

def sync_once():
    r = git('fetch', '--prune', '--quiet', 'origin', timeout=45)
    SYNC['fetch_error'] = (r.stderr.strip().splitlines() or ['git fetch fehlgeschlagen'])[-1] if r.returncode else None
    if r.returncode == 0:
        SYNC['last_fetch'] = time.time()
    if SYNC['gh']:
        try:
            out = subprocess.run(['gh', 'pr', 'list', '--state', 'open', '--limit', '50',
                                  '--json', 'number,title,headRefName,url,isDraft'],
                                 cwd=ROOT, capture_output=True, text=True, timeout=20)
            if out.returncode == 0:
                SYNC['prs'] = {p['headRefName']: p for p in json.loads(out.stdout)}
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass

def ensure_sync_thread():
    # Erst beim ersten Request starten: mit debug=True läuft das Modul zweimal (Reloader)
    global _sync_started
    with _sync_lock:
        if _sync_started:
            return
        _sync_started = True
    def loop():
        while True:
            sync_once()
            time.sleep(SYNC_EVERY_SEC)
    threading.Thread(target=loop, daemon=True).start()

def main_ref():
    for ref in ('origin/main', 'origin/master'):
        if git('rev-parse', '--verify', '--quiet', ref).returncode == 0:
            return ref
    return None

def branches():
    out = git('for-each-ref', '--sort=-committerdate',
              '--format=%(refname:short)|%(committerdate:unix)|%(authorname)|%(subject)',
              'refs/remotes/origin').stdout
    base = main_ref()
    result, now = [], time.time()
    for line in out.splitlines():
        ref, ts, author, subject = (line.split('|', 3) + ['', '', ''])[:4]
        if ref in ('origin', 'origin/HEAD') or ref == base:
            continue
        name = ref[len('origin/'):]
        ts = int(ts or 0)
        ahead = git('rev-list', '--count', f'{base}..{ref}').stdout.strip() if base else ''
        result.append({
            'name': name, 'ts': ts, 'author': author, 'subject': subject,
            'ahead': int(ahead) if ahead.isdigit() else None,
            'active': now - ts < BRANCH_ACTIVE_SEC,
            'is_agent': name.startswith('claude/'),
            'pr': SYNC['prs'].get(name),
        })
        if len(result) >= 15:
            break
    return result


# ---------- Lokale Claude-Code-Sitzungen ----------

def project_dir():
    exact = os.path.join(CLAUDE_PROJECTS, re.sub(r'[^A-Za-z0-9]', '-', ROOT))
    return exact if os.path.isdir(exact) else None

def parse_ts(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (AttributeError, ValueError):
        return None

def describe(name, inp):
    inp = inp or {}
    if name in ('Agent', 'Task'):
        return f"Delegiert an {inp.get('subagent_type') or 'general-purpose'}: {inp.get('description', '')}"
    if name == 'Bash':
        return inp.get('description') or (inp.get('command') or '')[:80]
    if name in ('Read', 'Edit', 'Write', 'NotebookEdit'):
        return f"{name} {os.path.basename(inp.get('file_path') or inp.get('notebook_path') or '')}"
    if name in ('Grep', 'Glob'):
        return f"{name} {inp.get('pattern', '')}"
    return name

def tail_lines(path, size):
    with open(path, 'rb') as f:
        if size > TAIL_BYTES:
            f.seek(size - TAIL_BYTES)
            f.readline()  # angeschnittene Zeile verwerfen
        for raw in f:
            yield raw

_session_cache = {}

def parse_session(path):
    st = os.stat(path)
    cached = _session_cache.get(path)
    if cached and cached[0] == (st.st_mtime, st.st_size):
        return cached[1]

    s = {'id': os.path.basename(path)[:-6], 'branch': None, 'prompt': None,
         'last_action': None, 'last_action_ts': None, 'calls': []}
    done = set()
    for raw in tail_lines(path, st.st_size):
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        typ = d.get('type')
        if d.get('gitBranch'):
            s['branch'] = d['gitBranch']
        if typ == 'last-prompt':
            s['prompt'] = d.get('lastPrompt') or s['prompt']
        elif typ == 'queue-operation' and d.get('operation') == 'enqueue' and d.get('content'):
            s['prompt'] = d['content']
        elif typ == 'user':
            content = (d.get('message') or {}).get('content')
            if isinstance(content, list):
                done.update(c.get('tool_use_id') for c in content if c.get('type') == 'tool_result')
        elif typ == 'assistant':
            for c in (d.get('message') or {}).get('content') or []:
                if c.get('type') != 'tool_use':
                    continue
                ts = parse_ts(d.get('timestamp'))
                s['last_action'], s['last_action_ts'] = describe(c.get('name'), c.get('input')), ts
                if c.get('name') in ('Agent', 'Task'):
                    inp = c.get('input') or {}
                    s['calls'].append({'id': c.get('id'), 'type': inp.get('subagent_type') or 'general-purpose',
                                       'desc': inp.get('description') or '', 'ts': ts})
    for call in s['calls']:
        call['open'] = call['id'] not in done
    _session_cache[path] = ((st.st_mtime, st.st_size), s)
    return s

def sessions():
    pdir = project_dir()
    if not pdir:
        return []
    now, result = time.time(), []
    for path in glob.glob(os.path.join(pdir, '*.jsonl')):
        try:
            mtime = os.path.getmtime(path)
            # Subagenten schreiben teils in eigene Dateien im gleichnamigen Ordner
            side = glob.glob(os.path.join(path[:-6], '**', '*.jsonl'), recursive=True)
            mtime = max([mtime] + [os.path.getmtime(p) for p in side])
            if now - mtime > SESSION_WINDOW_SEC:
                continue
            s = dict(parse_session(path))
        except (OSError, ValueError):
            continue
        running = [c for c in s['calls'] if c['open'] and c['ts'] and now - c['ts'] < SUBAGENT_STALE_SEC]
        s.update({
            'last_ts': mtime,
            'active': now - mtime < SESSION_ACTIVE_SEC or bool(running),
            'running': running,
            'prompt': (s['prompt'] or '').strip()[:200],
        })
        result.append(s)
    return sorted(result, key=lambda x: -x['last_ts'])


# ---------- Abteilungen ----------

def department_status(all_sessions, tasks, files):
    agents = []
    for dept in DEPARTMENTS:
        running = [(c, s) for s in all_sessions for c in s['running']
                   if AGENT_DEPARTMENT.get(c['type'], 'Engineering') == dept]
        calls = [c for s in all_sessions for c in s['calls']
                 if AGENT_DEPARTMENT.get(c['type'], 'Engineering') == dept]
        active_task = next((t for t in tasks if t.get('department') == dept and t['status'] == 'In Progress'), None)

        if running:
            c, s = running[0]
            status = f"{c['type']}: {c['desc']}" if c['desc'] else c['type']
        elif active_task:
            status = f"Arbeitet an #{active_task['id']}"
        else:
            status = "Idle"

        agents.append({
            "name": f"{dept} Agent",
            "department": dept,
            "status": status,
            "is_active": bool(running or active_task),
            "live": bool(running),
            "live_agents": sorted({c['type'] for c, _ in running}),
            "live_branch": running[0][1]['branch'] if running else None,
            "since": running[0][0]['ts'] if running else None,
            "last_used": max((c['ts'] or 0 for c in calls), default=0) or None,
            "calls_7d": len(calls),
            "recently_modified": len(files) if (running or active_task) else 0,
        })
    return agents


# ---------- System ----------

@app.route('/api/system', methods=['GET'])
def system_status():
    ensure_sync_thread()

    commits = git('log', '--all', '--pretty=format:%h|%an|%s|%ar', '-n', '8').stdout.splitlines()

    find = subprocess.run(['find', '.', '-type', 'f', '-mmin', '-2',
                           '-not', '-path', '*/.git/*', '-not', '-path', '*/venv/*',
                           '-not', '-path', '*/node_modules/*', '-not', '-path', '*/__pycache__/*',
                           '-not', '-path', './agent_ops/tasks.json'],
                          cwd=ROOT, capture_output=True, text=True)
    files = find.stdout.splitlines()

    all_sessions = sessions()
    agents = department_status(all_sessions, read_json(), files)

    return jsonify({
        'commits': commits,
        'active_files': files[:6],
        'agents': agents,
        'departments': DEPARTMENTS,
        'sessions': all_sessions[:6],
        'sessions_found': project_dir() is not None,
        'branches': branches(),
        'sync': {'last_fetch': SYNC['last_fetch'], 'error': SYNC['fetch_error'], 'gh': SYNC['gh']},
        'now': time.time(),
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"🚀 CEO Mission Control läuft auf http://localhost:{port}")
    app.run(port=port, debug=True)
