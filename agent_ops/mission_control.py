import os
import json
import subprocess
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
TASKS_FILE = os.path.join(os.path.dirname(__file__), 'tasks.json')

def init_db():
    if not os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, 'w') as f:
            json.dump([], f)

def read_tasks():
    init_db()
    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_tasks(tasks):
    with open(TASKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, indent=4, ensure_ascii=False)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/tasks', methods=['GET', 'POST'])
def handle_tasks():
    tasks = read_tasks()
    if request.method == 'POST':
        new_task = request.json
        new_task['id'] = len(tasks) + 1
        new_task['status'] = 'To Do'
        tasks.append(new_task)
        write_tasks(tasks)
        return jsonify(new_task), 201
    return jsonify(tasks)

@app.route('/api/tasks/<int:task_id>', methods=['PATCH'])
def update_task(task_id):
    tasks = read_tasks()
    for task in tasks:
        if task['id'] == task_id:
            task['status'] = request.json.get('status', task['status'])
            write_tasks(tasks)
            return jsonify(task)
    return jsonify({'error': 'Task not found'}), 404

@app.route('/api/status', methods=['GET'])
def get_status():
    project_root = os.path.dirname(os.path.dirname(__file__))
    
    try:
        git_log = subprocess.check_output(['git', 'log', '--all', '--oneline', '-n', '10'], cwd=project_root, text=True).splitlines()
    except:
        git_log = ["Git nicht initialisiert oder Fehler"]

    try:
        git_branches = subprocess.check_output(['git', 'branch', '-a'], cwd=project_root, text=True).splitlines()
    except:
        git_branches = ["Keine Branches"]

    try:
        find_cmd = 'find . -type f -mmin -5 -not -path "*/\.git/*" -not -path "*/node_modules/*" -not -path "*/venv/*" -not -path "*/__pycache__/*"'
        recent_files = subprocess.check_output(find_cmd, shell=True, cwd=project_root, text=True).splitlines()
        if not recent_files:
            recent_files = ["Keine Änderungen in den letzten 5 Minuten"]
    except:
        recent_files = ["Fehler beim Lesen der Dateien"]
        
    return jsonify({'git_log': git_log, 'git_branches': git_branches, 'recent_files': recent_files})

if __name__ == '__main__':
    init_db()
    print("🚀 CEO Mission Control startet auf http://localhost:8080")
    app.run(port=8080, debug=True)
