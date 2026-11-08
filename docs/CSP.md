# Content-Security-Policy (CSP)

Stand 07.11.2026 (Roadmap Nr. 23, Etappe 1).

## Warum

Ohne CSP führt der Browser jedes eingeschleuste `<script>` und jeden `onclick="…"` aus, den ein ungeschützter
Wert in eine Seite bringt. Mit CSP gilt: Skripte nur aus unseren eigenen Dateien oder mit dem **Nonce dieser
Antwort**. Fremdes Skript, auch wenn es im HTML steht, läuft nicht.

## Wie es eingeführt wird

| Etappe | Inhalt | Stand |
|---|---|---|
| 1 | Nonce an allen Inline-Skripten; Richtlinie im Modus **report-only** (der Browser meldet, sperrt nichts); Meldestelle `/csp-bericht/`; Ratsche gegen neue Inline-Handler | **erledigt** |
| 2 | Rückfragen (`return confirm('…')`, 109 Stellen) → `data-bestaetigen`, gelesen von `fw/_bestaetigen.html` | **erledigt** |
| 3 | Einfache Aktionen → `static/js/fw-aktionen.js` (`data-umschalten`, `-verstecken`, `-absenden`, `-gehe-zu`, `-stop`, `-kopieren`, `-auswaehlen`, `-scrollen`, `-entfernen`, `-neues-fenster`, `-sichtbar-wenn`), 93 Stellen | **erledigt** |
| 4 | Alle übrigen Inline-Handler (185 in 36 Vorlagen) → Datenattribute `data-bei-klick/-eingabe/-aenderung/-absenden`, `data-modal`, `data-drucken` u. a.; Ratsche steht auf 0 | **erledigt** |
| Ende | `CSP_MODUS=enforce` | offen |

`style-src` erlaubt vorerst `'unsafe-inline'` (die Oberfläche hat noch `style="…"`-Attribute, siehe
`core/tests/test_stilschuld.py`). Skripte sind das eigentliche Einfallstor und stehen deshalb zuerst an.

## Betrieb

* `CSP_MODUS` (Umgebungsvariable): `report-only` (Vorgabe), `enforce`, `aus` (nur als Notausstieg).
* Verstösse stehen als Warnung im Logger `csp` (`CSP-Verstoss: <Regel> | blockiert=… | Seite=… | Zeile=…`).
  Solange `report-only` gilt, sind sie die Arbeitsliste für die nächsten Etappen. Die Stelle ist ohne Anmeldung
  offen, gedeckelt (8 kB je Meldung, 60 Meldungen je Minute und Adresse) und schreibt nur ins Log.
* Der Verteiler `static/js/fw-aktionen.js` kennt die Datenattribute oben im Kopf der Datei; er hört einmal am Dokument zu und gilt auch für später geladene Teile (Schublade). `data-stop` ersetzt `event.stopPropagation()`: Ein Klick darauf löst die Aktion von Elementen darüber (z. B. der Zeile) nicht aus.
* Neue Inline-Handler lässt `core/tests/test_csp.py` nicht zu. Wer einen entfernt, führt
  `core/tests/csp_handler_stand.json` nach (Befehl im Kopf von `csp_handler_stand.py`).
* Inline-`<script>` brauchen `nonce="{{ csp_nonce }}"`; auch das prüft der Test.

## Vor `enforce`

1. Die Zahl der Inline-Handler ist 0 (`csp_handler_stand.json` leer).
2. Die Berichte der letzten Wochen im Log `csp` zeigen keine Verstösse mehr.
3. Die Browser-Tests (e2e) laufen mit `CSP_MODUS=enforce` grün.
4. `500.html` wird von Django ohne Anfrage gerendert (kein Nonce): Sein Inline-Skript muss bis dahin in eine
   Datei oder entfallen.
