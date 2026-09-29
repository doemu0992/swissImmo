import os, json, subprocess, time
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
TASKS_FILE = os.path.join(os.path.dirname(__file__), 'tasks.json')
DEPARTMENTS = ["Engineering", "QA", "DevOps", "Marketing & Docs"]

def read_json():
    if not os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, 'w') as f: json.dump([], f)
    with open(TASKS_FILE, 'r') as f: return json.load(f)

def write_json(data):
    with open(TASKS_FILE, 'w') as f: json.dump(data, f, indent=4)

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/tasks', methods=['GET', 'POST'])
def handle_tasks():
    tasks = read_json()
    if request.method == 'POST':
        new_task = request.json
        new_task['id'] = len(tasks) + 1
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

@app.route('/api/system', methods=['GET'])
def system_status():
    root = os.path.dirname(os.path.dirname(__file__))
    
    # Letzte Commits
    try: commits = subprocess.check_output(['git', 'log', '--all', '--pretty=format:%h|%an|%s|%ar', '-n', '5'], cwd=root, text=True).splitlines()
    except: commits = []

    # Live-Dateien (Wer tippt wo?)
    try: 
        find_cmd = 'find . -type f -mmin -2 -not -path "*/\.git/*" -not -path "*/venv/*" -not -path "*/node_modules/*"'
        files = subprocess.check_output(find_cmd, shell=True, cwd=root, text=True).splitlines()
    except: files = []

    # Agenten-Status inferieren
    agents = []
    tasks = read_json()
    for dept in DEPARTMENTS:
        active_task = next((t for t in tasks if t['department'] == dept and t['status'] == 'In Progress'), None)
        is_typing = any(dept.split()[0].lower() in f.lower() or '.py' in f or '.html' in f for f in files) if active_task else False
        
        status_text = "Idle"
        if active_task: status_text = f"Arbeitet an #{active_task['id']}"
        
        agents.append({
            "name": f"{dept} Agent",
            "department": dept,
            "status": status_text,
            "is_active": bool(active_task),
            "recently_modified": len(files) if active_task else 0
        })

    return jsonify({"commits": commits, "active_files": files[:5], "agents": agents, "departments": DEPARTMENTS})

if __name__ == '__main__':
    print("🚀 CEO Dashboard v2 (Premium) läuft auf Port 8080")
    app.run(port=8080, debug=True)
