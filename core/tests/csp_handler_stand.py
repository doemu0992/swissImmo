"""Die Zählung der Inline-Handler (`onclick=` …) in den Vorlagen — Hilfe für `test_csp` und die Nachführung.

    python -c "from core.tests.csp_handler_stand import zaehlen; import json; print(json.dumps(zaehlen(), indent=1, sort_keys=True))"
"""
import pathlib
import re

HANDLER = re.compile(
    r'\son(?:click|dblclick|submit|change|input|focus|blur|keydown|keyup|keypress|load|error|mouseover|mouseout|'
    r'mouseenter|mouseleave|dragover|dragenter|dragleave|dragstart|dragend|drop|toggle|paste|select|reset|invalid)'
    r'\s*=\s*(?:"[^"]*"|\'[^\']*\')', re.I)
KOMMENTAR = re.compile(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}|<!--.*?-->|\{#.*?#\}', re.S)


def zaehlen(wurzel='core/templates'):
    stand = {}
    for pfad in sorted(pathlib.Path(wurzel).rglob('*.html')):
        n = len(HANDLER.findall(KOMMENTAR.sub(' ', pfad.read_text(encoding='utf-8'))))
        if n:
            stand[pfad.relative_to(wurzel).as_posix()] = n
    return stand
