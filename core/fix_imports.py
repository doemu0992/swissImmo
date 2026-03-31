import os
import re
from collections import defaultdict

# Unser Wörterbuch: Welches Modell liegt jetzt wo?
MODEL_MAP = {
    'Verwaltung': 'crm', 'Mandant': 'crm', 'Mieter': 'crm', 'Handwerker': 'crm',
    'Liegenschaft': 'portfolio', 'Einheit': 'portfolio', 'Zaehler': 'portfolio',
    'ZaehlerStand': 'portfolio', 'Geraet': 'portfolio', 'Unterhalt': 'portfolio',
    'Schluessel': 'portfolio', 'SchluesselAusgabe': 'portfolio',
    'Mietvertrag': 'rentals', 'MietzinsAnpassung': 'rentals', 'Leerstand': 'rentals', 'Dokument': 'rentals',
    'Buchungskonto': 'finance', 'KreditorenRechnung': 'finance', 'Zahlungseingang': 'finance',
    'Jahresabschluss': 'finance', 'MietzinsKontrolle': 'finance', 'AbrechnungsPeriode': 'finance',
    'NebenkostenBeleg': 'finance', 'NebenkostenLernRegel': 'finance',
    'SchadenMeldung': 'tickets', 'HandwerkerAuftrag': 'tickets', 'TicketNachricht': 'tickets'
}

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Schutz: Falls die Datei schon neue Imports hat, überspringen wir sie
    if any(re.match(r'^from\s+(portfolio|crm|finance|rentals|tickets)\.models', l) for l in lines):
        return

    new_lines = []
    in_import_block = False
    import_removed = False

    # 1. Alte Importe (from core.models... oder from .models...) löschen
    for line in lines:
        stripped = line.strip()
        if re.match(r'^from\s+(core|\.)\.models\s+import', stripped):
            import_removed = True
            # Falls der Import über mehrere Zeilen geht (mit Klammern)
            if '(' in line and ')' not in line:
                in_import_block = True
            continue

        if in_import_block:
            if ')' in line:
                in_import_block = False
            continue

        new_lines.append(line)

    # 2. Prüfen, welche Modelle in dieser Datei als reiner Text vorkommen
    content = "".join(new_lines)
    needed_imports = defaultdict(list)

    for model, app in MODEL_MAP.items():
        # Sucht exakt nach dem Wort (verhindert, dass "Einheit" bei "Einheiten" anschlägt)
        if re.search(r'\b' + model + r'\b', content):
            needed_imports[app].append(model)

    # 3. Neue Importe generieren und ganz oben einfügen
    if needed_imports and import_removed:
        import_statements = []
        for app, models in needed_imports.items():
            import_statements.append(f"from {app}.models import {', '.join(models)}\n")

        final_content = "".join(import_statements) + "\n" + content

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(final_content)
        print(f"✅ Repariert: {filepath}")


print("\n🚀 Starte automatische Import-Reparatur...\n")

# Durchsuche alle Python-Dateien im 'core' Ordner
for root, dirs, files in os.walk('core'):
    for file in files:
        if file.endswith('.py'):
            filepath = os.path.join(root, file)
            # Diese Dateien überspringen (die haben wir schon gemacht oder sie brauchen es nicht)
            if 'migrations' in filepath or file in ['models.py', 'admin.py']:
                continue
            process_file(filepath)

print("\n🎉 Fertig! Alle Hintergrund-Skripte wurden aktualisiert.")