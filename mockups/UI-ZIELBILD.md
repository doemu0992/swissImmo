# UI-Zielbild: Mockup → Anwendung

`immoswiss-ui-ziel.html` ist das **Zielbild** für Darstellung und Bedienung. Es ist kein Produktivcode.
Beispieldaten, keine Verbindung zur Anwendung. Im Browser öffnen: links «Stand» (Ist, Phase 0–3) und
15 Schalter, rechts die durchklickbare App (alle Bereiche, Dialoge, ⌘K, Profilmenü).

**Vorgabe des Auftraggebers:** Listen, Dialoge, Popups und Bedienung sollen sich in der Anwendung
**genau so anfühlen** wie im Zielbild. Abweichungen sind zu begründen, nicht stillschweigend zu wählen.

Dieses Dokument ist ein Abbild eines Zeitpunkts (19.11.2026). Widerspricht der Bestand, gilt der Bestand,
und diese Datei wird im selben PR korrigiert (Skill `swissimmo-review`).

## Regeln für jeden Umsetzungs-PR

- Ein Thema pro PR. Kein Umbau von Fachlogik «bei der Gelegenheit».
- Quelle der Stile ist `core/templates/fw/_schicht.html` / `static/css/schicht.src.css`; danach
  `python manage.py schicht_bauen`. Tokens heissen `--ds-*`. Neue Tokens nur mit Eintrag, der
  `core/tests/test_ds_tokens.py` besteht.
- Skripte mit `nonce="{{ csp_nonce }}"` oder als Datei unter `static/js/`. Keine Fremdbibliothek.
- Texte über `{% trans %}`; DE, FR, IT, EN in `locale/` nachführen.
- Messen bei **390 × 844**, dann 1280. `e2e/tests/telefon.spec.ts` als Vorbild.
- Rollen und Mandantenbezug an jedem neuen Endpunkt (`mandantentrennung`).
- Vor dem Melden «fertig»: sechs Punkte aus `swissimmo-review` belegen.

## Abgleich Zielbild ↔ Bestand

Status: **da** = im Code gelesen · **fehlt** = im Code nicht gefunden · **prüfen** = noch nicht gelesen.

| Zielbild | Bestand | Status | Hinweis |
|---|---|---|---|
| Schiene links, Tab-Leiste mobil, Schublade | `fw/base.html`, `fw-schiene.js` | da | Zielbild nur im Detail vergleichen (Masse, Zahlen) |
| ⌘K-Suche | `fw-omnisearch.js`, `core/services/palette_suche.py` | da | Bestand sucht über mehr Gruppen als das Zielbild |
| Dark Mode im Profilmenü | `fw-thema.js` | da | Optik der Schalter-Zeile angleichen |
| Zahlen sofort statt Hochzählen (Phase 0) | `static/js/fw-kapsel.js` zählt hoch | fehlt | kleinster PR, zuerst |
| Heute: Statuszeile statt Hero-Kachel | `fw/dashboard.html` (Hero bereits entfernt) | prüfen | Schwerpunkt «Übersicht» zeigt noch Kennzahl-Kacheln |
| Heute: Arbeitsvorrat mit Dringlichkeitsstufen | `fw/_arbeitsvorrat_abschnitte.html` | prüfen | «Überfällig bis 30 Tage» / «seit über 30 Tagen» |
| Zeilen: Button nennt die Aufgabe, Haken «Erledigt» | `fw/_arbeitsvorrat_abschnitte.html` | prüfen | |
| Rückgängig nach «Erledigt» (Toast, Taste Z) | nicht gefunden | fehlt | **braucht Entscheid**, siehe unten |
| Zuordnen-Dialog Bankabgleich | `fw/bankabgleich.html` (Seite «Zuordnen / Aufteilen») | da | Zielbild ist ein Dialog; Bestand ein Assistent auf eigener Seite |
| Schäden: Statuszeile, Liste/Board, leerer Zustand | `tickets`, Vorlagen `fw/schaden_*.html` | prüfen | |
| Liegenschaften: Sortierung sofort, Filterchips | `fw/liegenschaften.html` | prüfen | «Anwenden»-Knopf im Zielbild entfernt |
| Monatsabschluss als Schritte | `fw/laeufe.html`, `faelle/` | prüfen | Fachlogik der Läufe nicht anfassen |
| Finanzen: Abschluss mit Haken statt Durchstreichen | `fw/finanzen.html` | prüfen | |
| Berichte: gruppiert, Suche, Ziellinie im Diagramm | `fw/berichte.html` | prüfen | |
| Einstellungen: Suche, «Häufig genutzt» | `fw/einstellungen.html`, `core/navigation.py` | prüfen | Gruppen kommen aus `einstellungen_gruppen()` |
| Neuer Fall: Pflichtfelder leer, Fristenchips, Fehler sofort | `fw/fall_neu.html` | prüfen | Vorbelegung nur, wenn sie fachlich sicher ist |
| Dichte Listen ab ~10 Vorgängen | | fehlt | Phase 3 |
| Lesbare Schrift ≥ 12 px, Tippfläche 36/44 px | `_schicht.html` | prüfen | Messen |

## Reihenfolge der PRs (Vorschlag)

1. **Phase 0:** Hochzählen aus, Texte und Kürzel, kleine Korrekturen (Sortierung, Haken).
2. **Bausteine:** Dialog, Toast mit Rückgängig, Statuszeile (Komponenten in der Schicht, mit Wächtern).
3. **Heute:** Arbeitsvorrat und Dringlichkeit.
4. **Finanzen:** Zuordnen als Dialog, Abschlussblock.
5. **Schäden, Liegenschaften, Monatsabschluss, Berichte, Einstellungen, Neuer Fall:** je ein PR.
6. **Phase 2:** Profilmenü, Akzent, Tab-Leiste mobil (Abgleich mit Bestand).
7. **Phase 3:** Dichte, Design-System-Bereinigung.

## Offene Entscheide (nicht selbst auflösen)

1. **Akzentfarbe.** Anwendung: Orange `--ds-brand #b04416`. Zielbild: Blau `#2347c5` als Vorschlag.
   `test_palette` und `test_ds_tokens` fixieren die Palette. Markenpaket nennt Navy/Coral/Warm-White.
2. **«Rückgängig».** Das Zielbild hält den Zustand nur im Browser. In der Anwendung braucht es für
   Buchhaltungsvorgänge entweder verzögerte Ausführung oder eine echte Rücknahme.
   Buchungen sind nicht löschbar (`finance/db_schutz.py`); Zahlungszuordnung hat eigene Regeln
   (`core/services/zahlungsklaerung.py`).
3. **Zuordnen als Dialog oder Seite.** Der Bestand-Assistent kann auf mehrere Posten aufteilen.
4. **Schrift.** Zielbild und Anwendung nutzen DM Sans (lokal unter `static/fonts/`). Entscheid D3 nennt IBM Plex.
   Nachsehen, welche tatsächlich ausgeliefert wird.

## Was im Zielbild erfundene Beispieldaten sind

Namen («Mieter A»), Beträge, Vorgänge, Berichtsliste und Einstellungsliste sind Beispiele.
Die Listen der Anwendung kommen aus `core/navigation.py` und den Ansichten, nicht aus dem Zielbild.
