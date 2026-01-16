#!/bin/bash

# Ordner, die wir auf "Leichen" untersuchen wollen
TARGET_DIRS="static templates media"

echo "Suche nach ungenutzten Dateien in: $TARGET_DIRS"
echo "---------------------------------------------"

# Wir suchen alle Dateien in den Zielordnern
find $TARGET_DIRS -type f | while read filepath; do
    
    # Wir holen uns nur den Dateinamen (z.B. "style.css")
    filename=$(basename "$filepath")
    
    # Wir suchen diesen Namen im gesamten Projekt (außer in .git, __pycache__ und dem file selbst)
    # Wir zählen wie oft der Name vorkommt
    count=$(grep -r "$filename" . --exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=myenv --exclude="$filepath" | wc -l)

    # Wenn der Count 0 ist, wird die Datei nirgends erwähnt
    if [ "$count" -eq "0" ]; then
        echo "❌ MÖGLICHE LEICHE: $filepath"
    fi
done


