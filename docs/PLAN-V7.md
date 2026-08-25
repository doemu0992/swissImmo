# swissImmo — Plan zum 10k-Produkt

Vorschlag zur Besprechung. Nichts davon ist im Repo; nichts wird umgesetzt, bevor die Entscheidungen in Abschnitt 8 gefallen sind. Die Befunde B1–B13, auf die ich mich beziehe, stehen in `UX-Analyse.md`. Das Zielbild ist in `konzept-v7.html` klickbar.

---

## 1. Was «10k Franken» bedeutet

`docs/MARKT.md` setzt die Stufen bei CHF 39 / 119 / 329 / 749 pro Monat. Eine Verwaltung mit 2–5 Personen und 150–800 Einheiten landet bei Professional oder Enterprise: CHF 4'000–9'000 pro Jahr, plus nutzungsabhängige Module (Signaturen, Belegerkennung), plus Onboarding/Datenimport. Das ist der 10k-Kunde.

Wofür zahlt er das? Nicht für Funktionen — die hat Fairwalter auch. Er zahlt für vier Dinge:

1. **Nichts fällt runter.** Fristen, Läufe, Vorgänge sind Zustände, die die Software hält, nicht Listen, die jemand pflegt.
2. **Kein Widerspruch.** Eine Zahl hat eine Quelle. Was die Startseite sagt, sagt die Akte auch.
3. **Der Eigentümer ist beeindruckt.** Reporting und Portal sind die Visitenkarte der Verwaltung beim Kunden.
4. **Das Team arbeitet ohne Schulung.** Wer eine Akte kann, kann alle; wer einen Lauf kann, kann alle.

Daraus folgen die Leitsätze für alles Weitere: **Ein Arbeitsvorrat. Eine Wahrheit je Zahl. Ein Reitersatz. Ein Laufrahmen. Ein Suchfeld.**

---

## 2. Informationsarchitektur v7

### 2.1 Fünf Bereiche statt vier — warum ich vom Konzept abweiche

G1 sagt `Arbeit · Akten · Läufe · Zahlen`. Ich schlage `Heute · Akten · Läufe · Finanzen · Berichte` vor.

**Was bleibt:** Arbeit (als «Heute»), Akten, Läufe, Zahlen (als «Berichte»). Die Grundidee — Arbeit vor Datenmodell, Fall als Zentrum, Zulauf als Startfläche — bleibt vollständig.

**Was dazukommt:** `Finanzen` als eigener Bereich. Begründung:

- Die Zielkundin hat «Buchhaltung im Haus» (Konzept, Kopfzeile). Die Buchhalterin hat einen anderen Tagesrhythmus als die Bewirtschafterin: Bank, Kreditoren, Journal, Abschluss. Das Konzept legt Kontenplan und Journal unter «Läufe › Abschluss» (`ZUORDNUNG-VIEWS.md` §4) — ein Register ist aber kein Lauf. Wer das Journal sucht, sucht es unter Finanzen.
- Heute stehen 16 Finanz-Seiten im Profimodus und 12 davon unter «Erweitert» im Einfachmodus (B1). Das sind reale, gebaute Funktionen, die einen Ort brauchen.
- **Die Bedingung:** Finanzen ist ein Register-Bereich, **kein Arbeitskorb**. Das Finanz-Cockpit mit eigener Aufgabenliste entfällt (B3). Was zu tun ist, steht unter Heute und Läufe — aus derselben Quelle (`faelle.Lauf`).

**Was entfällt:** Einfach-/Profimodus, «Erweitert», «Kontakte» (→ Akten), «Vermietung» (→ Fälle und Mietverhältnis-Akte), «Portfolio» (→ Akten).

### 2.2 Die Bereiche und ihre Unterleisten

| Bereich | Unterleiste | Inhalt |
|---|---|---|
| **Heute** | Arbeitsvorrat · Zulauf · Termine · Vertretung | Fälle, Läufe-Fristen, Pendenzen in fünf Ansichten (Heute, Diese Woche, Wartet auf Dritte, Liegengeblieben, Alle) × Fallart-Filter (Mieterwechsel, Schaden, Zahlungsverzug, Mietzinsanpassung, Kündigung, Lauf). Lage-Streifen nur mit Vergleich (4b.13 bleibt). |
| **Akten** | Mandate · Liegenschaften · Objekte · Mietverhältnisse · Personen · Dienstleister | Sechs Register, sechs Listen nach Befund sortiert, ein Reitersatz. Schaden ist keine Akte im Menü, sondern ein Fall (Aktentyp bleibt technisch bestehen). |
| **Läufe** | Übersicht · Monat · Nebenkosten · Mietzinsanpassung · MWST & Abschluss | Jeder Lauf im gleichen Rahmen: Betroffene → Berechnen → Prüfen → Ausführen → Protokoll, mit Blockaden vorne. Monat = Sollstellung, Bankabgleich, Mahnlauf, Zahllauf. |
| **Finanzen** | Bank · Mieterkonten · Kreditoren · Kautionen · Buchhaltung · Hypotheken & Anlagen | Register und Konten. Handlungen (abgleichen, mahnen, zahlen) springen in den zugehörigen Lauf. |
| **Berichte** | Eigentümer · Leerstand & Ertrag · Debitoren · Mandatsrentabilität · Auswertungen | Das heutige «Zahlen». Jede Auswertung mit Export und «an Eigentümer senden». |
| **Einstellungen** | Organisation · Team & Rollen · Abo & Module · Vorlagen · Regelwerk · Postfächer & Schnittstellen · Sicherheit | Inhaber-Dinge nach Rolle ausgeblendet, nicht nur gesperrt. |

Querliegend, überall: **Suche** (⌘K) über Datensätze *und* Seiten (B7), **Neu** als Schnellanlage (Fall, Mietverhältnis, Person, Schaden, Eingang), **Mandantenwechsel** im Kopf der Leiste (`Mitgliedschaft` kann es bereits), **Benachrichtigungen**.

### 2.3 Zuordnung der heutigen Menüpunkte

| Heute in `navigation.py` | v7 |
|---|---|
| Heute, Zulauf, Termine, Abwesenheiten, Pendenzen, Fristen-Center | Heute (Fristen-Center geht im Arbeitsvorrat «Diese Woche/Alle» auf) |
| Regelwerk | Einstellungen › Regelwerk |
| Liegenschaften, Objekte | Akten |
| Schadensfälle | Heute › Fallart Schaden + Reiter «Fälle» je Akte |
| Ersatz & Ausstattung, Hypotheken | Akten › Objekt/Liegenschaft › typeigener Reiter; Hypotheken → Finanzen |
| Vermarktung, Bewerbungen, Mieterwechsel | Fall Mieterwechsel, Schritte 3–4 |
| Verträge | Akten › Mietverhältnisse |
| Mietzins (anpassen) | Läufe › Mietzinsanpassung; Einzelfall als Fall |
| Finanz-Cockpit | **entfällt** (B3) |
| Bankabgleich, Sollstellung, Mahnwesen, Zahllauf | Läufe › Monat (Zustand) + Finanzen (Register) |
| Bankkonten, Debitoren, Mieterkonten, Kautionen, Kreditoren, Lieferantenkonten, Buchhaltung, Kontenplan, Anlagen | Finanzen |
| Nebenkosten, MWST | Läufe |
| Berichte-Hub, Auswertung | Berichte |
| Personen, Dienstleister, Eigentümer & Mandate | Akten |
| Einstellungen, Benutzer, Abonnement, Logbuch, Vorlagen, Integrationen, Rechtsgrundlagen | Einstellungen |

Keine Seite geht verloren; jede bekommt genau einen Ort.

---

## 3. Design-System v7

### 3.1 Was bleibt

Petrol `#0f6f6a` bleibt die Markenfarbe — geprüft, in `test_palette.py` festgeschrieben, ein zweiter Wechsel wäre Verschleiss. Die semantischen Töne (good/warn/crit/info) und der Dunkelmodus-Satz aus `base.html` bleiben als Werte.

### 3.2 Was sich ändert

| Thema | v7 | Grund |
|---|---|---|
| **Rahmen** | Helle Leiste auf hellem Grund, eine Linie, keine Verläufe | Der dunkle Verlaufsblock ist das Erkennungsmerkmal jeder Admin-Vorlage; er frisst 240 px Gewicht und macht Mandanten-Branding schwer lesbar. Im Prototyp per Schalter vergleichbar (hell/dunkel). |
| **Schrift** | IBM Plex Sans (Oberfläche, Tabellenziffern) + IBM Plex Mono (Fall-Nr, IBAN, Referenzen) — selbst gehostet | Tabellenziffern überall, nicht nur in `fw-num`; Mono macht Identifikatoren erkennbar. Inter bleibt als Rückfall zulässig (Entscheidung D3). |
| **Grund** | 14 px Basis, 13 px in Tabellen, 11 px Eyebrows in Versalien | Dichte eines Arbeitswerkzeugs, nicht einer Marketingseite |
| **Akzent als ein Token** | `--akzent` (+ `-2`, `-soft`) statt Indigo-Rampe | Mandanten-Branding (höhere Stufe) = ein Wert je Organisation; der Prototyp zeigt es live |
| **Icons** | Ein Satz von ~40 Inline-SVGs mit fester Bedeutung (Sprite in `base.html`) | B8; kein Font-Download, keine 178 Varianten |
| **Komponenten** | Rahmen, Aktenkopf, Register, Kennzahlen, Befund, Arbeitszeile, Tabelle, Formular, Leerzustand, Stufenband, Laufrahmen, Messbalken, Dialog, Toast | Alles, was in v7 vorkommt, ist eine dieser Komponenten |
| **Leere Zustände** | Eine Aussage + eine Handlung («Kein Eingang unzugeordnet. Postfach abrufen →») | statt kursiver Einzeiler |
| **Tailwind** | Build-Schritt (Datei im Repo, ohne CDN), Utilities nur in Übergangsphase; Wächter zählt `bg-/text-/border-`-Farbklassen in fw-Templates **abwärts** bis 0 | B2 |

### 3.3 Messbare Abnahme

- `test_palette.py` erweitern: Kontrast jeder Text/Grund-Kombination in Leiste, Surface, Dunkelmodus ≥ 4.5:1 (Kopie der Lambda-Kette aus der WCAG-Prüfung).
- Neuer Wächter: Anzahl Tailwind-Farbklassen je Template als Zahl im Test; jede Etappe senkt sie, keine erhöht sie.
- Kein externer Host in `base.html`, `base_embed.html`, `_modal_done.html` (Test greift).

---

## 4. Neue und erweiterte Module

Sortiert nach Verkaufswirkung. «Bestand» = was im Code schon liegt.

| # | Modul | Bestand | Was fehlt | Stufe / Modul |
|---|---|---|---|---|
| M1 | **Mietzinsanpassung als Lauf** (Referenzzins, Teuerung, Kostensteigerung; Senkung wie Erhöhung; amtliches Formular je Kanton; Vier-Augen-Freigabe) | `mietzins.py`, `mietzins_formular.py`, `lik.py`, `formularpflicht.py`, `MietzinsAnpassung` | Laufrahmen, Massenberechnung, Blockaden (fehlende Basis), Protokoll, Versand | Team |
| M2 | **Vor-Ort-Modus** (Abnahme, Besichtigung, Zähler, Mängel mit Lebensdauertabelle, Unterschrift, offline-fähig als PWA) | `Abnahmeprotokoll`, `AbnahmeMangel`, `Lebensdauer`, `Zaehler`, `Schluessel` | Mobile Oberfläche, Offline-Puffer, Foto-Upload, PDF am Ende | Verwaltung |
| M3 | **Nebenkostenabrechnung als geführter Lauf** | `AbrechnungsPeriode`, `NebenkostenBeleg`, `Verteilschluessel`, `nk_abrechnung.py` | Laufrahmen mit Blockaden (Ablesung fehlt, Beleg ohne Konto), Vorschau je Mieter, Versand mit QR | alle Stufen (`MARKT.md` §5) |
| M4 | **Eigentümerportal v2 / Mieterportal v2** | `views/portal.py`, beide vollständig | Branding, Selbstbedienung (Schaden melden mit Foto, Dokumente, Zahlungsstand, Freigaben), Mehrsprachigkeit, Mail-Digest | Team |
| M5 | **Datenimport-Assistent** (Excel/CSV aus Fairwalter, ImmoTop, Rimo; Mapping, Probelauf, Protokoll) | — | ganz | Onboarding-Leistung; Voraussetzung für jeden Wechselkunden |
| M6 | **Suche & Listen-Werkzeugkasten** (⌘K über Datensätze, gespeicherte Ansichten, Spaltenwahl, Mehrfachauswahl, CSV) | `fw_suche`, Filterleisten | B7, B10 | alle |
| M7 | **Zuständigkeit** (Person ↔ Mandat/Liegenschaft, Vertretung) | `Abwesenheit.vertreten_durch` | Modell `Zustaendigkeit`, Filter im Arbeitsvorrat, «meine Mandate» | Team |
| M8 | **Abo & Module** (Phase 3) | `funktionen.py`-Naht, `Organisation.abo_plan` | Modelle `Abonnement`, `Kontingent`, `Rechnung`; Anbieter; MWST; Testphase; Downgrade/Zahlungsausfall | — |
| M9 | **STWE-Modul** (Stockwerkeigentum: Eigentümerversammlung, Beschlüsse, Erneuerungsfonds, Wertquoten, Jahresrechnung) | `Einheit.typ='stwe'`, `Erneuerungsfonds` | Fast alles; separates, abschaltbares Modul | Zubuchbar (neu, nicht in der Projektanweisung — Vorschlag) |
| M10 | **Buchhaltungsexport** (Banana, Abacus, Bexio als CSV/XML) und **Kalender-Feed** | `ical.py`, django-ninja-API | Exportvorlagen, Doku | Professional |

### 4.1 Modelle, die neu entstehen

- `abo.Abonnement` (Organisation, Stufe, Intervall, Status, Testphase bis, Anbieter-Referenz, gekündigt auf)
- `abo.Kontingent` (Organisation, Art: belege/signaturen/speicher, Periode, inklusive, verbraucht)
- `abo.Rechnung` (Organisation, Periode, Betrag netto, MWST 8.1 %, Status, QR-Referenz)
- `crm.Zustaendigkeit` (Mitgliedschaft, Mandat oder Liegenschaft, Rolle: federführend/Stellvertretung)
- `core.GespeicherteAnsicht` (Benutzer, Seite, Filter als JSON, Name, geteilt ja/nein)
- `core.Benachrichtigung` (Benutzer, Quelle, gelesen, Zustellweg)
- `crm.Branding` oder Felder an `Organisation`: `akzentfarbe`, Logo (existiert), Absendername für Portale
- M9: `stwe.Versammlung`, `stwe.Traktandum`, `stwe.Beschluss`, `stwe.Wertquote`

Alle mit `OrganisationAusKette`, alle mit Isolationstests, wie in Phase 2 etabliert.

---

## 5. Etappen

Die Projektanweisung ist bindend: Phase 3 vor 4 vor 5 vor 6. Konzept 13.1 hat 4a vorgezogen und 4b mit i18n verknüpft; daran halte ich fest. Reihenfolge unten ist eine Abfolge von Gates, keine Kalenderplanung — jede Etappe endet mit grünen Tests, geprüfter Mandantentrennung, nachgeführter Doku, gemergtem PR. Grössenangaben: S (eine Sitzung), M (mehrere), L (viele).

| Nr | Etappe | Inhalt | Gate | Grösse |
|---|---|---|---|---|
| **E0** | **Fundament reparieren** | `seed_e2e` in Kontext setzen (B6); Tailwind-Build-Datei statt CDN, Font- und Icon-Dateien ins Repo (B2); Kontrastregel auf helle Flächen beschränken (B4); Finanz-Cockpit-Arbeitskorb auf `faelle.Lauf` umhängen oder entfernen (B3) | E2E läuft auf frischer DB; kein externer Host in den Hüllen; Kontrasttest grün; Heute und Finanzen nennen dieselben Läufe | M |
| **E1** | **Rahmen v7** | `navigation.py` auf fünf Bereiche, Modi entfernen, Unterleisten, Mandantenwechsel, Tab-Leiste mobil, ⌘K über Datensätze (B1, B7, B11) | Alle 312 Views an genau einem Ort erreichbar (Erreichbarkeits-Wächter aus 4b.10 erweitern); keine toten Pfade; Redirects gesetzt | M |
| **E2** | **Komponenten v7 + Template-Durchgang mit i18n** | Komponentenschicht komplett; dann die 113 fw-Templates in Tranchen je Bereich — gleichzeitig `{% trans %}` und `gettext` (B5, B13). Reihenfolge: Heute → Akten → Läufe → Finanzen → Berichte → Einstellungen → Portale | Tailwind-Farbklassen-Zähler = 0 in der Tranche; Dunkelmodus vollständig; `.po` für DE vollständig, FR/IT/EN maschinell vorübersetzt und markiert | L |
| **E3** | **Phase 3: Abo & Module** | Modelle aus 4.1, `stufe_von()` an echte Daten, Anbieter-Anbindung, MWST, Testphase, Downgrade/Zahlungsausfall, Seite «Abo & Module» (Prototyp Screen 6) | Sperrverhalten getestet (Daten bleiben, Schreiben gesperrt, Export offen); Rechnungen mit QR; Isolationstests | L |
| **E4** | **Läufe vereinheitlichen** | Ein Laufrahmen; M1 Mietzinsanpassung, M3 Nebenkosten darin; Monat-Läufe migrieren | Jeder Lauf hat Blockaden, Protokoll, Vier-Augen wo Geld oder Recht | L |
| **E5** | **Listen & Suche** | M6 | Gespeicherte Ansichten mandantengetrennt; Export je Kernliste | M |
| **E6** | **Vor Ort** | M2 als PWA-Teil derselben Anwendung | Abnahme offline erfassbar, PDF mit Unterschriften, Mängel in Ersatzplanung | L |
| **E7** | **Portale v2, Berichte, Export** | M4, M10, Eigentümer-Quartalsreport | Eigentümer erhält Report aus dem System ohne Handarbeit | M |
| **E8** | **Zuständigkeit, Benachrichtigungen** | M7 | Arbeitsvorrat nach «meine Mandate»; Vertretung automatisch | M |
| **E9** | **Datenimport** | M5 | Ein echter Fairwalter-Export läuft durch | M |
| **E10** | **Handbuch** (Phase 6) | `docs/handbuch/` DE, dann EN/FR/IT, mit Stufenkennzeichnung | je Funktion ein Kapitel | L |
| — | **STWE** (M9) | separater Entscheid nach E7 | | L |

E0 ist nicht verhandelbar — alles Weitere baut darauf. E1 und E2 sind der Kern der Phase 4; E3 ist Phase 3 nachgeholt. Ab E4 ist es Phase 5.

---

## 6. Was ich bewusst nicht empfehle

- **Einfach-/Profimodus** — Unterschiede gehören ins Entitlement und in die Rolle (Konzept §1).
- **Zweiter Arbeitskorb** irgendwo (Finanzen, Berichte, Akten) — eine Liste, viele Ansichten.
- **Kanban-Boards, KI-Chat, Dashboards mit Donuts** — der Kunde will Fristen halten, nicht Kacheln ansehen (4b.13).
- **Eigenes Frontend-Framework** — Django-Templates mit kleinem JS reichen; der Vor-Ort-Modus braucht einen Service Worker, keine SPA (`E1-SPA-ENTFERNEN.md` hat das schon einmal entschieden).
- **Brand-Wechsel** — Petrol bleibt.

---

## 7. Abhängigkeiten, die eine Freigabe brauchen

Laut Projektanweisung nicht ohne ausdrückliche Freigabe. Ich setze nichts davon um, bevor du es entschieden hast.

| Was | Wofür | Kosten | Alternative |
|---|---|---|---|
| `tailwindcss` als npm-Dev-Abhängigkeit (v3, wie heute per CDN) | Build-Datei statt Laufzeit-JIT (E0) | keine | Tailwind ganz entfernen — dann müssen 15'619 Utilities vor E2 weg; nicht realistisch |
| IBM Plex Sans/Mono als Dateien in `static/fonts/` (OFL-Lizenz) | Schrift v7, kein Google-Fonts-Aufruf | keine | Inter selbst hosten (gleicher Aufwand, weniger Charakter) |
| Lucide-Icons als SVG-Sprite (ISC-Lizenz), nur die ~40 gebrauchten Pfade kopiert, keine Paketabhängigkeit | Icon-System (B8) | keine | Eigene SVGs zeichnen |
| Zahlungsanbieter: **Payrexx** (CH, TWINT, Rechnung mit QR, MWST-tauglich) oder **Stripe** (Karten, Abos, grössere Doku) | Phase 3 | Gebühren je Transaktion | Rechnungsversand mit QR aus dem System selbst + manuelle Bestätigung (tiefere Stufe, kein Anbieter) |
| Service Worker / Web-App-Manifest (`swiss_immo/manifest.json` existiert) | Vor-Ort offline (E6) | keine | — |

---

## 8. Entscheidungen, die ich von dir brauche

| # | Frage | Meine Empfehlung |
|---|---|---|
| D1 | Fünf Bereiche (Heute · Akten · Läufe · Finanzen · Berichte) oder die vier aus G1? | **Fünf.** Finanzen als Register ohne Arbeitskorb. |
| D2 | Leiste hell oder dunkel? (im Prototyp umschaltbar) | **Hell.** Ruhiger, Branding-fähig, ein Dunkelmodus für alles statt zwei Paletten. |
| D3 | Schrift: IBM Plex oder Inter bleiben? | **Plex.** Tabellenziffern überall, Mono für Referenzen. |
| D4 | Tailwind als Build behalten (Übergang) oder sofort reine Token-CSS? | **Build behalten**, Zähler abwärts bis 0 über E2. |
| D5 | Icon-Satz: Lucide-Sprite (Freigabe nötig) oder eigene SVGs? | **Lucide-Sprite**, ~40 Zeichen, im Repo, keine Paketabhängigkeit. |
| D6 | Zahlungsanbieter: Payrexx, Stripe oder vorerst eigene QR-Rechnung? | **Payrexx** prüfen (TWINT, CH-Rechnung); bis dahin eigene QR-Rechnung. |
| D7 | Stufennamen: `Start/Team/Professional/Enterprise` (MARKT) — und die Codes `basis/aufbau/verwaltung/portfolio` (funktionen.py) darauf abbilden? | **Ja**, eine Quelle: `funktionen.py` bekommt die Marktnamen als Klartext, `Organisation.abo_plan` entfällt zugunsten `Abonnement`. |
| D8 | Bereichsnamen: «Heute» oder «Arbeit»? «Berichte» oder «Zahlen»? «Fall» oder «Vorgang»? | Heute · Berichte · Fall. |
| D9 | STWE als neues zubuchbares Modul ins Zielbild aufnehmen? | **Ja, nach E7 entscheiden** — Markt ist gross, Bestand (Erneuerungsfonds, stwe-Einheit) ist ein Anfang. |
| D10 | Mobile: Tab-Leiste + Vor-Ort-Modus in derselben Anwendung (PWA) oder getrennte App? | **Dieselbe Anwendung.** |

Wenn D1–D5 entschieden sind, schreibe ich E0 als idempotentes Skript und lege den Prototyp als `mockups/konzept-v7.html` samt `docs/KONZEPT-UI.md`-Nachtrag ab — und nicht vorher.
