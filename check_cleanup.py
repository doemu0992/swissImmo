import os

# --- KONFIGURATION ---
# Ordner, die durchsucht werden sollen (nach "Leichen")
SEARCH_IN_DIRS = ['static', 'templates', 'media']

# Ordner, die wir beim Suchen ignorieren (System-Ordner)
IGNORE_DIRS = ['myenv', '.git', '__pycache__', 'staticfiles', 'venv']

# Dateiendungen, die wir prüfen
EXTENSIONS = ('.html', '.js', '.css', '.png', '.jpg', '.jpeg', '.pdf')

BASE_DIR = os.getcwd()

def get_all_files_content():
    """Liest ALLE Dateien im Projekt in den Speicher, um darin zu suchen."""
    content = ""
    print("Lese Projektdateien ein...")
    for root, dirs, files in os.walk(BASE_DIR):
        # Ignoriere System-Ordner
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            # Wir lesen nur Textdateien (.py, .html, .js, .css)
            if file.endswith(('.py', '.html', '.js', '.css', '.json')):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        content += f.read()
                except:
                    pass
    return content

def find_unused_files():
    project_content = get_all_files_content()
    
    print("\n--- VERDÄCHTIGE DATEIEN (Nirgends im Code gefunden) ---")
    print("HINWEIS: Bitte manuell prüfen, bevor du löschst!\n")
    
    found_something = False
    
    for target_dir in SEARCH_IN_DIRS:
        full_target_path = os.path.join(BASE_DIR, target_dir)
        if not os.path.exists(full_target_path):
            continue

        for root, dirs, files in os.walk(full_target_path):
            for filename in files:
                if filename.endswith(EXTENSIONS):
                    # Wir suchen den Dateinamen im gesamten Projekt-Inhalt
                    if filename not in project_content:
                        rel_path = os.path.relpath(os.path.join(root, filename), BASE_DIR)
                        print(f"❌ Nicht gefunden: {rel_path}")
                        found_something = True

    if not found_something:
        print("✅ Alles sieht sauber aus! Keine verwaisten Dateien gefunden.")

if __name__ == "__main__":
    find_unused_files()
