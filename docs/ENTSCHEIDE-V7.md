# Entscheide zum Zielbild v7

Entschieden am 22.08.2026 von Dominik. Bindend für alle folgenden Etappen. Wer davon abweicht, ändert diese Datei zuerst — mit Datum und Grund, wie überall in `docs/`.

Grundlage: `docs/UX-ANALYSE-V7.md` (Befunde B1–B13), `docs/PLAN-V7.md` (Etappen E0–E10), `mockups/konzept-v7.html` (Zielbild).

---

## D1 · Fünf Bereiche statt vier

`Heute · Akten · Läufe · Finanzen · Berichte`, dazu `Einstellungen`.

G1 in `KONZEPT-UI.md` sah vier vor (`Arbeit · Akten · Läufe · Zahlen`). Finanzen kommt dazu, weil die Buchhalterin einen anderen Tagesrhythmus hat als die Bewirtschafterin und weil 16 gebaute Finanzseiten sonst keinen Ort haben. Kontenplan und Journal sind Register, keine Läufe.

**Bedingung, die den Zusatz erst zulässig macht:** Finanzen ist ein Register-Bereich **ohne eigenen Arbeitskorb**. Was zu tun ist, steht unter Heute und Läufe — aus `faelle.Lauf`, einer Quelle. Das heutige Finanz-Cockpit mit eigener Aufgabenliste entfällt (B3).

Ersatzlos gestrichen: Einfach-/Profimodus, «Erweitert», die Bereiche Portfolio, Vermietung und Kontakte.

## D2 · Helle Seitenleiste

Kein dunkler Verlaufsblock. Gründe: Er ist das Erkennungsmerkmal jeder Admin-Vorlage, er trägt Mandanten-Branding schlecht, und die heutige Kontrastregel kollidiert mit ihm (B4). Ein Dunkelmodus für die ganze Oberfläche statt zwei paralleler Paletten.

## D3 · IBM Plex Sans und IBM Plex Mono, selbst gehostet

Plex Sans für die Oberfläche, Plex Mono für Identifikatoren (Fall-Nr., IBAN, QR-Referenz, Kontonummer). Tabellenziffern überall, nicht nur in `fw-num`. Lizenz OFL, Dateien liegen im Repo — kein Google-Fonts-Aufruf mehr.

## D4 · Tailwind bleibt, aber als Build

Kein `cdn.tailwindcss.com` mehr (B2). Die erzeugte CSS-Datei liegt im Repo; `tailwindcss` kommt als npm-Dev-Abhängigkeit dazu. Utilities sind Übergang, nicht Ziel: Ein Wächter zählt die Farb-Utilities (`bg-`, `text-`, `border-`) je Template. Jede Etappe senkt die Zahl, keine erhöht sie, Ziel 0 am Ende von E2.

## D5 · Ein Icon-Satz, ~40 Zeichen

Inline-SVG-Sprite in `base.html`, Pfade im Lucide-Stil (ISC-Lizenz), kopiert statt als Paket eingebunden. Ersetzt 178 verschiedene Font-Awesome-Klassen (B8). Jedes Zeichen hat eine feste Bedeutung; wer ein neues braucht, trägt es in die Tabelle im Design-System ein.

## D6 · Vorerst kein Zahlungsanbieter

Payrexx ist die zu prüfende Option (Schweiz, TWINT, QR-Rechnung, MWST). **Nicht angebunden, bis Dominik das ausdrücklich freigibt.** Phase 3 rechnet bis dahin über die eigene QR-Rechnung mit manueller Zahlungsbestätigung; die Abo-Modelle sind so gebaut, dass eine Anbieter-Referenz später ohne Migrationsbruch dazukommt.

## D7 · Eine Quelle für die Abostufe

Klartextnamen aus `MARKT.md`: **Start · Team · Professional · Enterprise**. Die Codes in `core/funktionen.py` (`basis`, `aufbau`, `verwaltung`, `portfolio`) bleiben als technische Schlüssel und bekommen diese Namen als Anzeige. `crm.Organisation.abo_plan` (`start/pro/premium`) entfällt zugunsten von `abo.Abonnement`; `stufe_von()` liest dann echte Daten statt einer Settings-Konstante.

## D8 · Begriffe

**Heute** (nicht «Arbeit»), **Berichte** (nicht «Zahlen»), **Fall** (nicht «Vorgang»). Die übrigen Begriffe aus `KONZEPT-UI.md` bleiben unverändert: Akte, Lauf, Zulauf, Blockade, Regelwerk, Befund.

## D9 · Stockwerkeigentum bleibt Vorschlag

Als zubuchbares Modul im Zielbild sichtbar, aber **nicht gebaut**. Entscheid nach E7. Bestand heute: `Einheit.typ='stwe'` und `finance.Erneuerungsfonds`.

## D10 · Eine Anwendung, auch vor Ort

Der Vor-Ort-Modus (Abnahme, Besichtigung, Zähler, Mängel, Unterschrift) ist eine Ansicht derselben Anwendung mit Service Worker, keine zweite App: dieselben Adressen, dieselben Rechte, dieselbe Mandantentrennung.

---

## Was weiterhin eine ausdrückliche Freigabe braucht

Nach der Projektanweisung nicht ohne Entscheid: neue Python-/JS-Abhängigkeiten, Plugins, MCP-Connectors, externe Dienste, alles mit Kosten oder Datenzugriff.

| Was | Stand |
|---|---|
| `tailwindcss` als npm-Dev-Abhängigkeit | freigegeben mit D4 |
| IBM Plex als Schriftdateien im Repo (OFL) | freigegeben mit D3 |
| Lucide-SVG-Pfade, kopiert (ISC) | freigegeben mit D5 |
| Service Worker / Web-App-Manifest | freigegeben mit D10 |
| **Payrexx oder ein anderer Zahlungsanbieter** | **offen — nicht umsetzen** |
