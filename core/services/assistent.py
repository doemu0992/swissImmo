"""Server-seitiger Assistent (Assistenten-Standard, 27.10.2026).

Ein Ablauf, dessen Schritte eigene Seiten sind und dessen Zwischenstand gespeichert ist
(z. B. die NK-Abrechnung), zeigt dieselbe Leiste, denselben Schrittkopf und denselben Fuss
wie der client-seitige Assistent (`static/js/fw-bausteine.js`). Gerendert wird er von
`fw/_assistent_server.html` (Rahmen) bzw. `fw/_assistent_server_leiste.html` (nur Leiste);
beide lesen den Kontext `assistent`, den diese Funktion baut.

Je Schritt ein dict mit `nr`, `titel`, `info` (optional, kleine Zeile unter dem Titel),
`zustand` und `url`, optional `optional=True`.

Zustände (CSS-Klasse am `<li>`, Abschnitt «Assistent» in `_schicht.html`):

    offen      noch nicht erledigt, erreichbar
    fertig     erledigt — Akzent, ✓
    warnung    erreichbar, aber etwas ist zu prüfen — Warnfarbe, !
    gesperrt   erst nach einem früheren Schritt möglich — gedämpft, kein Link
    entfaellt  gilt hier nicht (bleibt ein Link, z. B. zum Einschalten) — «–»

`hier` ist kein Zustand des Schritts, sondern die Seite, auf der man steht: Er kommt aus
`aktuell` und steht zusätzlich zum Zustand am `<li>` (schwarz, `aria-current="step"`).
Ein unbekannter Zustand ist ein Fehler, kein stiller Leerlauf (bekannte Fallen, Nr. 9).
"""

ZUSTAENDE = ('offen', 'fertig', 'warnung', 'gesperrt', 'entfaellt')


def server_assistent(schritte, aktuell, *, abbrechen_url, abbrechen_text=None):
    """Kontext `assistent` für `fw/_assistent_server.html`.

    `schritte`: Folge von dicts (siehe oben), in der Reihenfolge der Leiste.
    `aktuell`: Nummer (`nr`) des Schritts dieser Seite.
    `abbrechen_url`: Ziel von «Abbrechen» (in der Regel die Liste, von der man kam).
    `abbrechen_text`: anderer Text für diesen Knopf, z. B. «Schliessen» nach dem Abschluss.

    Rückgabe: `schritte` (Kopien mit `hier`), `nr`, `i` und `n` («Schritt i von n», aus der
    Stelle in der Leiste, nicht aus `nr`), `schritt` (der aktuelle),
    `zurueck` und `weiter` (Nachbarschritte oder None), `abbrechen_url`, `abbrechen_text`.
    """
    liste = []
    for s in schritte:
        zustand = s.get('zustand') or 'offen'
        if zustand not in ZUSTAENDE:
            raise ValueError(f'Unbekannter Zustand {zustand!r} in Schritt {s.get("nr")!r}; '
                             f'erlaubt: {", ".join(ZUSTAENDE)}')
        liste.append({**s, 'zustand': zustand, 'info': s.get('info') or '', 'url': s.get('url') or '',
                      'hier': s.get('nr') == aktuell})
    pos = next((i for i, s in enumerate(liste) if s['hier']), None)
    if pos is None:
        raise ValueError(f'Schritt {aktuell!r} steht nicht in der Leiste')
    return {
        'schritte': liste, 'nr': aktuell, 'i': pos + 1, 'n': len(liste), 'schritt': liste[pos],
        'zurueck': liste[pos - 1] if pos > 0 else None,
        'weiter': liste[pos + 1] if pos + 1 < len(liste) else None,
        'abbrechen_url': abbrechen_url, 'abbrechen_text': abbrechen_text,
    }
