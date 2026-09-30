# Design v8 — Bausteine und Regeln

Stand 30.09.2026. Quelle: `mockups/konzept-v8-cockpit.html`. Umgesetzt in
`core/templates/fw/_schicht.html` (Quelle) → `static/css/schicht.css` (gebaut mit
`python manage.py schicht_bauen`). Die Palette steht in `docs/KONZEPT-UI.md` §16.1.

Dieses Dokument sagt, **welcher Baustein wofür steht**. Eine Seite, die ein Muster
mit Tailwind-Utilities nachbaut, das es hier als Baustein gibt, ist nicht fertig.

## Grundsätze

1. **Eine Seite = Kopf, Kennzahlen (falls es welche gibt), dann Karten.** Abstand
   zwischen den Blöcken 24 px — den setzen die Bausteine selbst (`margin-bottom`),
   keine `mb-*`-Utilities dazwischen.
2. **Farbe heisst Bedeutung.** Petrol = Marke und Handlung, Rot/Orange/Grün = Zustand.
   Kein Blau, Violett oder Indigo für Zierde. Werte werden nicht eingefärbt, nur
   weil sie Geld sind; eingefärbt wird, was auffallen soll (offen, überfällig).
3. **Keine Kursivschrift** für Leerzustände oder Hinweise.
4. **Zustand in Form, nicht nur in Zahlen:** Balken (`fw-marker`), Kapsel (`fw-chip`),
   Punkt (`fw-punkt`).
5. **Schrift:** IBM Plex Sans; Nummern (Fall, MV, IBAN, QR-Referenz) in
   `fw-mono`. Grössen 28 (Seitentitel) · 15 (Kartentitel) · 14 (Text) · 13 (Tabellen)
   · 12.5 (Nebentext) · 11–12 (Beschriftung in Versalien). Gewicht max. 700.
6. **Telefon zuerst prüfen**: 390 × 844. Nichts darf quer scrollen ausser Tabellen in
   `fw-tablewrap`.

## Bausteine

| Zweck | Klassen | Bemerkung |
|---|---|---|
| Seitenkopf | `fw-phead` > `div` (`h1`, `p`) + `div.fw-phead-knoepfe` | Titel 28 px, Untertitel 13.5 px. Knöpfe rechts. Optional `div.fw-eyebrow` über dem `h1`. |
| Kennzahlen | `fw-kpis` > `fw-kpi` > `fw-l`, `fw-v` (+ `fw-crit`/`fw-warn`/`fw-good`), `fw-f` | Ein zusammenhängender Streifen, **ohne** Symbolquadrat. Ersetzt jede Kachelreihe `grid … gap-4` mit `fw-card p-5`. |
| Lagestreifen (Startseite) | `fw-lage` > `div` > `fw-l`, `fw-w`, `fw-f`, `fw-trend hoch/runter` | Nur auf «Heute». |
| Karte | `fw-card` | Radius 12, feiner Schatten, 24 px Abstand. |
| Kartenkopf | `fw-kopf` > `fw-t` (oder `h2`), `fw-neben`, `fw-rechts` | Alternative bei alten Seiten: `fw-card > fw-h` mit `fw-t`, `fw-r`. |
| Kartenfuss | `fw-fuss` | Links Erklärung, rechts `fw-link`. |
| Reiter | `fw-reiter` > `a`/`button` (`hier`) + `span.fw-z` | Unterstrich in Marke, Zähler als Kapsel. Detailseiten: `data-tab`/`data-target`/`data-panel` bleiben (fwTab). |
| Filter-Kapseln | `fw-filters` > `a.fw-fchip` (`fw-on`) oder `fw-band` > `a` (`hier`) | Aktiv = dunkel gefüllt (Tinte), nicht Marke. |
| Werkzeugleiste | `fw-listwerkzeug` > `div.fw-suchfeld` > `input.fw-feld` | Suche, Sortierung, Filter über einer Liste. |
| Tabelle | `div.fw-tablewrap` > `table.fw-table` (`fw-dicht`), `th/td.fw-right` | Kopf 12 px auf `--ds-surface-2`. Zahlen rechtsbündig, `fw-num`. Mobil stapelt `fwTabellenStapeln` automatisch. |
| Listenzeile | `fw-zeile` (`klick`) > `fw-marker`, `fw-mitte` (`fw-t`, `fw-s`), `fw-zeit`, `fw-btn fw-knapp` | Für Arbeitslisten statt Tabellen. |
| Kapsel | `fw-chip` + `fw-good/fw-warn/fw-crit/fw-info/fw-brand/fw-mut` (+ `fw-dot`) | Status. |
| Etikett | `fw-marke-kapsel` | Art (Fallart, Typ) — neutral. |
| Nummer | `fw-mono` | Fall-Nr, MV-Nr, Referenzen. |
| Knopf | `fw-btn` (+ `fw-primary`, `fw-knapp`, `fw-leise`, `fw-geist`, `fw-weich`, `fw-rand-*`, `fw-gefahr`) | Nie `px-/py-/rounded-/font-` am Knopf. |
| Link | `fw-link` | Petrol, 600. |
| Formular | `fw-formular` (Raster, 2 Spalten ab 640 px) > `div.fw-feldblock` > `label.fw-label`, `input/select/textarea.fw-feld`, `p.fw-hilfe` | `fw-feldblock.breit` über beide Spalten. Fehler: `fw/_feldfehler.html`. |
| Feld aus Formular | `{% include 'fw/_feld.html' with f=… label=… %}` | |
| Hinweis | `fw-hinweis` (+ `warn/crit/info/good`) > `fw-hi`, `fw-ht` | Mit Zeichen und Text. |
| Befund | `fw-befund` (+ Zustand) | Auffälligkeit mit Kosten. |
| Leerzustand | `{% include 'fw/_empty.html' with icon=… titel=_('…') %}`, in Tabellen und Nebenlisten `knapp=True` (in `td.fw-leerzeile`) | Baut `fw-leer` / `fw-leer-knapp` mit `fw-leer-zeichen` (`mut` = neutral). Eine Aussage + ggf. eine Handlung. Keine kursiven Einzeiler. |
| Aktenkopf | `fw-aktenkopf` > `fw-akte-oben` (`fw-akte-bild`, `fw-akte-typ`, `h1`, `fw-akte-pfad`, `fw-akte-rechts`) + `fw-kzn` | Detailseiten. |
| Schlüssel/Wert | `fw-dz` > `fw-dl`, `fw-dv` · oder `dl` > `fw-kv` | |
| Abschnittstitel | `fw-subhead` | 11 px Versalien. |
| Menü | `[data-menu]` > `[data-menu-btn]`, `[data-menu-list]` > `fw-menuzeile` | Kein eigenes Skript. |
| Schublade | `fwModalOpen(this,'Titel',wide)` | Öffnet `fw/_fwmodal.html` rechts. |
| Ablauf | `ol.fw-ablauf` > `li` (`fertig`/`jetzt`) > `span.fw-ablauf-punkt`, `b`, `span.fw-ablauf-status` | Schritte eines Falls als Zeitleiste; Punkt gefüllt = erledigt, Ring = jetzt. |
| Kartenrumpf | `fw-rumpf` | 20 px Innenabstand (16 px am Telefon), statt `p-5` an Formkarten. |
| Häkchen | `label.fw-haekchen` > `input[type=checkbox]` + Text | Checkbox und Beschriftung in einer Zeile, auch innerhalb `fw-feldblock`. |
| Freigabeleiste | `div.fw-freigabe` > `div.fw-ht` + `fw-btn fw-primary` | Haftet unten (am Telefon über der Tab-Leiste). Für Sollstellung, Zahllauf, Mahnlauf. |
| Hinweis als Fliesstext | `fw-hinweis` > `div.fw-ht.fliess` | `<b>` bleibt in der Zeile — für übersetzte Sätze mit Hervorhebung. |

## Was nicht mehr vorkommen soll

- Kachelreihen `grid grid-cols-… gap-4` aus `fw-card p-5` mit Symbolquadrat (`w-11 h-11 rounded-lg fw-*-flaeche`) → `fw-kpis`.
- Aktive Filter in Marke (`fw-balken-voll` an einer Kapsel) → `fw-fchip fw-on` / `fw-band a.hier`.
- `italic` an Leerzuständen → `fw-leer`.
- Eigene Überschriften `text-2xl font-bold` → `fw-phead h1`.
- Knöpfe aus Utilities → `fw-btn`-Varianten.
- Farbige Beträge ohne Bedeutung (`fw-info` an einer Summe) → Tinte; Farbe nur für offen/überfällig/Gewinn-Verlust.

## Was bei jeder Umstellung unverändert bleibt

Formulare (`action`, `method`, `name`, `value`, `csrf_token`), Links (`href`),
`onclick`/`onchange`/`onsubmit`, Ids, `data-*`-Attribute, `{% if %}`/`{% for %}`,
`{% trans %}`-Texte, `aria-*`. Umgestellt wird **nur** die Darstellung.
