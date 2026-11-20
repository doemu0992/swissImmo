# UI-Zielbild: Mockup → Anwendung

`immoswiss-ui-ziel.html` ist das **Zielbild** für Darstellung und Bedienung. Es ist kein Produktivcode.
Beispieldaten, keine Verbindung zur Anwendung. Im Browser öffnen: links «Stand» (Ist, Phase 0–3) und
15 Schalter, rechts die durchklickbare App (alle Bereiche, Dialoge, ⌘K, Profilmenü).

**Vorgabe des Auftraggebers:** Listen, Dialoge, Popups und Bedienung sollen sich in der Anwendung
**genau so anfühlen** wie im Zielbild. Abweichungen sind zu begründen, nicht stillschweigend zu wählen.

Dieses Dokument ist ein Abbild eines Zeitpunkts (angelegt 19.11.2026, Abgleich nachgeführt 20.11.2026). Widerspricht der Bestand, gilt der Bestand,
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

## Abgleich Zielbild ↔ Bestand (Stand 20.11.2026)

Alle Umsetzungs-PRs sind gemergt (#323 bis #346). Gemessen wurden die berechneten Stile von Prototyp und App bei 390 und 1280 px (Heute, Schäden);
die übrigen Seiten wurden per Screenshot verglichen. Details je Bereich stehen in `ARCHITECTURE.md`.

| Zielbild | Stand | Abweichung, bewusst |
|---|---|---|
| Schiene links, Tab-Leiste mobil, Schublade | umgesetzt | Handy: «+» öffnet das Drawer-Menü (Variante B) statt einer «Mehr»-Seite |
| Menü-Gruppen | umgesetzt | Sieben Bereiche: zusätzlich «Kontakte» (Personen, Dienstleister) neben «Liegenschaften» (Betreiber-Entscheid 20.11.2026) |
| ⌘K-Suche, Profilmenü, Dunkelmodus | umgesetzt | Bestand sucht über mehr Gruppen; Profilmenü zusätzlich Sprache, Dokumente, Kommunikation |
| Zahlen sofort statt Hochzählen | umgesetzt (19.11.2026) | |
| Heute: Statuszeile, Arbeitsvorrat mit Dringlichkeit, Haken «Erledigt» | umgesetzt | |
| Rückgängig nach «Erledigt» und Zuordnen (Toast) | umgesetzt | nur, wo eine geprüfte Rücknahme besteht |
| Zuordnen als Dialog (Bankabgleich) | umgesetzt | Aufteilen bleibt ein Assistent auf eigener Seite |
| Schäden, Liegenschaften, Monatsabschluss (Schrittliste), Finanzen | umgesetzt | Schäden zusätzlich Chips Notfall / Hoch / SLA; Debitoren zusätzlich Filter-Kacheln |
| Berichte (gruppiert, Suche, «Häufig genutzt», Datenstand am Endpunkt) | umgesetzt | **Ziellinie 95 % fehlt**: Der Zielwert muss der Betreiber festlegen |
| Einstellungen (Suche, «Häufig genutzt») | umgesetzt | |
| Neuer Fall, Mitteilungen (Zulauf) | umgesetzt | Art nicht vorgewählt (verhindert Fälle auf falscher Akte) |
| Dichte Listen, Zeilenabstand 7 px am PC | umgesetzt | Ansicht «Dicht» (Zweitzeile neben dem Titel) zusätzlich wählbar |
| Schriftskala 12/13/14/15/18/22/28 px, Tippflächen 36/44 px | umgesetzt | Anzeigegrössen 34/36/40/52 px ausserhalb der Skala |
| Anrede «Sie» | umgesetzt | Zielbild zeigt die Du-Variante als Alternative |
| Zeilenhöhe am Handy | teilweise | Schäden 162 statt 86 px: Zweitzeile und Freigabe-Chips braucht die App fachlich |

Nicht geprüft: Lade-, Disabled- und Fehlerzustände der Formulare, Tablet-Breiten (641–1023 px), Portale, PDF-Vorlagen, echte Produktionsdaten.

## Entscheide (Stand 20.11.2026)

1. **Akzentfarbe:** Orange `--ds-brand #b04416` bleibt, nicht das Blau des Prototyps. Dunkelmodus: `#f08a55`.
2. **«Rückgängig»:** nur mit geprüfter Rücknahme; Buchungen sind nicht löschbar (`finance/db_schutz.py`).
3. **Zuordnen:** Dialog für die vier Wege, Assistent für das Aufteilen.
4. **Schrift:** DM Sans, lokal ausgeliefert; sieben Stufen per Wächter (`test_schriftskala`).
5. **Anrede:** «Sie».
6. **Zeilendichte:** Prototyp-Abstand (7 px) ist am PC Standard.
7. **Noch offen:** Zielwert der Ziellinie im Diagramm.

## Was im Zielbild erfundene Beispieldaten sind

Namen («Mieter A»), Beträge, Vorgänge, Berichtsliste und Einstellungsliste sind Beispiele.
Die Listen der Anwendung kommen aus `core/navigation.py` und den Ansichten, nicht aus dem Zielbild.
