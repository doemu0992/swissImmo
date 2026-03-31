import os
import re

# Mapping deiner Modelle zu den neuen Apps (alles in Kleinbuchstaben für URLs)
MODEL_APP_MAP = {
    # CRM
    'verwaltung': 'crm', 'mandant': 'crm', 'mieter': 'crm', 'handwerker': 'crm',
    # Portfolio
    'liegenschaft': 'portfolio', 'einheit': 'portfolio', 'zaehler': 'portfolio',
    'zaehlerstand': 'portfolio', 'geraet': 'portfolio', 'unterhalt': 'portfolio',
    'schluessel': 'portfolio', 'schluesselausgabe': 'portfolio',
    # Rentals
    'mietvertrag': 'rentals', 'mietzinsanpassung': 'rentals', 'leerstand': 'rentals', 'dokument': 'rentals',
    # Tickets
    'schadenmeldung': 'tickets', 'handwerkerauftrag': 'tickets', 'ticketnachricht': 'tickets',
    # Finance
    'buchungskonto': 'finance', 'kreditorenrechnung': 'finance', 'zahlungseingang': 'finance',
    'jahresabschluss': 'finance', 'mietzinskontrolle': 'finance', 'abrechnungsperiode': 'finance',
    'nebenkostenbeleg': 'finance'
}

# Verzeichnisse, die ignoriert werden sollen
IGNORE_DIRS = {'.git', '.venv', 'venv', 'env', '__pycache__', 'migrations', 'static', 'media'}

def fix_html_urls(content, filepath):
    """Sucht nach {% url 'admin:core_modell_...' %} und ersetzt 'core' durch die richtige App."""
    new_content = content
    changes_made = False

    for model_lower, correct_app in MODEL_APP_MAP.items():
        # Sucht nach admin:core_mietvertrag_add, admin:core_mietvertrag_change etc.
        pattern = rf"(admin|url\s*['\"]admin):core_{model_lower}_"
        # Ersetzt es mit admin:rentals_mietvertrag_
        replacement = rf"\1:{correct_app}_{model_lower}_"

        # Regex anwenden
        new_content, count = re.subn(pattern, replacement, new_content)
        if count > 0:
            changes_made = True

    return new_content if changes_made else None

def fix_python_imports(content, filepath):
    """Einfache Ersetzungen für Python Import-Pfade."""
    new_content = content
    changes_made = False

    # Ersetzt einfache 'core.models.ModellName' durch 'app.models.ModellName'
    # Achtung: Komplexe Multi-Imports in einer Zeile (from core.models import A, B)
    # müssen oft noch manuell nachgebessert werden.
    for model_lower, correct_app in MODEL_APP_MAP.items():
        # Finde den Model-Namen in seiner Original-Schreibweise (Case-Insensitive Search)
        pattern = re.compile(rf"core\.models(\s+import\s+|\.)({model_lower})\b", re.IGNORECASE)

        # Wenn gefunden, ersetze 'core' durch die korrekte App
        def replace_func(match):
            return f"{correct_app}.models{match.group(1)}{match.group(2)}"

        new_content, count = pattern.subn(replace_func, new_content)
        if count > 0:
            changes_made = True

    return new_content if changes_made else None

def run_script(root_dir='.'):
    print("🚀 Starte Refactoring Skript...\n")
    changed_files = 0

    for subdir, dirs, files in os.walk(root_dir):
        # Ignoriere bestimmte Ordner
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for file in files:
            filepath = os.path.join(subdir, file)

            # HTML Templates anpassen
            if file.endswith('.html'):
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                updated_content = fix_html_urls(content, filepath)
                if updated_content:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(updated_content)
                    print(f"✅ HTML angepasst: {filepath}")
                    changed_files += 1

            # Python Dateien anpassen
            elif file.endswith('.py') and file != 'fix_imports.py':
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                updated_content = fix_python_imports(content, filepath)
                if updated_content:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(updated_content)
                    print(f"✅ Python angepasst: {filepath}")
                    changed_files += 1

    print(f"\n🎉 Fertig! {changed_files} Dateien wurden aktualisiert.")
    print("⚠️ Überprüfe Python-Dateien mit mehrfachen Imports (z.B. from core.models import Mieter, Mietvertrag) ggf. noch manuell.")

if __name__ == "__main__":
    run_script()