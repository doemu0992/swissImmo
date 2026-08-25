# swissImmo — UX-Analyse (Stand main, 21.08.2026)

Gemessen am Tarball von `doemu0992/swissImmo@main`, nicht an Annahmen. Ergänzend habe ich die Anwendung lokal gestartet (SQLite, 195 Migrationen, eigene Demo-Organisation mit 3 Liegenschaften, 12 Objekten, 10 Mietverhältnissen, 2 Schäden, Fallarten, Regelwerk, Läufe) und 17 Seiten unter `/neu/` in Desktop- und Handybreite fotografiert. Die bestehenden Prototypen `mockups/konzept-v3…v6.html` habe ich ebenfalls gerendert.

**Nicht gemacht:** Die 2'060 Tests habe ich nicht laufen lassen; die Produktion auf PythonAnywhere habe ich nicht angeschaut. Aussagen zu Testzustand oder Produktionsverhalten stehen hier deshalb nicht.

---

## 1. Der Bestand in Zahlen

| Mass | Wert | Quelle |
|---|---|---|
| Python (ohne Migrationen) | 86'452 Zeilen | `find -name "*.py"` |
| Migrationen | 195 Dateien, 13'443 Zeilen | `*/migrations/` |
| Modelle | 75 in 9 Apps (finance 22, portfolio 18, faelle 14, rentals 9, crm 8, core 6, tickets 4, mietprozess 1, benutzer 1) | `models.py`, `*_models.py` |
| Templates | 185 (113 unter `core/templates/fw/`, 95 erben `fw/base.html`) | |
| Views | 312 Funktionen in 37 Dateien unter `core/views/fw/` (17'760 Zeilen); `detailseiten.py` allein 2'378 Zeilen | |
| Tests | 81 Dateien, 2'060 `def test_` | |
| Eigenes CSS / JS | 202 / 485 Zeilen | `static/`, `core/static/` |
| Design-Tokens | 26 `--ds-*` | `fw/base.html` `:root` |
| Komponentenklassen | ~60 `fw-*` | `fw/base.html` `<style>` |
| Tailwind-Utilities in fw-Templates | 15'619 Vorkommen | grep über `class="…"` |
| Inline `style="…"` | 190 | |
| Verschiedene Font-Awesome-Icons | 178 | `fa-*` |
| Templates mit `{% trans %}` | **1 von 185** | |
| Docs | 26 Dateien, darunter `KONZEPT-UI.md` (72 KB), `ANALYSE.md` (54 KB), `MARKT.md`, `ZUORDNUNG-VIEWS.md` | `docs/` |

Fachlich ist der Bestand deutlich breiter, als ein Aussenstehender erwarten würde: QR-Rechnung (`core/utils/qr_code.py`, `services/debitor_qr.py`), pain.001 (`services/pain001.py`), camt-Import (`views/fw/bankabgleich.py`, 1'127 Zeilen), Referenzzins/LIK (`services/mietrecht.py`, `services/lik.py`, `services/mietzins_formular.py`), amtliche Formulare (`services/amtliche_formulare_so.py`, `formularpflicht.py`, `kantone.py`), Kündigungsfristen als Regelwerk (`faelle/regelwerk.py`), Eigentümer- **und** Mieterportal (`views/portal.py`), 2FA (`middleware_zweifaktor.py`), IMAP mit OAuth2, Fallmaschine, Läufe mit Blockaden, Termine und Abwesenheiten, Lebensdauertabelle (`portfolio.Lebensdauer`), Erneuerungsfonds (STWEG-tauglich), Mandatsabrechnung, Verwaltungshonorar.

---

## 2. Was gut ist und bleibt

- **Die Mandantentrennung zwingt.** `core/tenancy.py` wirft ohne Kontext (`OrganisationsFehler`), `organisation_kette.py` bestimmt den Eigentümer jedes Datensatzes. Mein erster Seed-Versuch ist sauber daran gescheitert — genau so soll es sein.
- **Die Fallmaschine ist das richtige Zentrum.** `faelle.Fall` mit Schritten, Frist, Verfallsregel, Verknüpfungen; Läufe mit Zustand und Blockierungsgrund (`faelle/lauf_models.py`). Das ist die Substanz, die Fairwalter und LIMMOBI nicht haben.
- **Die Akten nach G6/G9.** Aktenkopf, Kennzahlenleiste, «Was auffällt», ein Reitersatz für alle sieben Typen — die Vertragsakte ist heute die beste Seite der Anwendung (Screenshot: Reto Amstutz, MV-4).
- **Die Befund-Logik in den Listen** (4b.15/4b.17/4b.18): Zeilen sortiert nach dem, was fehlt, nicht nach Alphabet. Das ist der Kern eines Premium-Werkzeugs.
- **Die Entitlement-Naht** (`core/funktionen.py`): ein Katalog, ein Aufruf, Tippfehler werfen. Phase 3 kann einhängen, ohne Aufrufer zu ändern.
- **Der Doku-Stil.** Jede Entscheidung hat Datum, Grund und Wächter-Test. Das ist selten und wertvoll.

---

## 3. Befunde

Schwere: **A** = steht dem 10k-Anspruch direkt im Weg · **B** = kostet täglich Vertrauen oder Zeit · **C** = Qualitätsrückstand.

### B1 · Die Navigation ist nicht das Konzept — A

`docs/KONZEPT-UI.md` Abschnitt 2, G1: «Vier Bereiche statt sechs. `Arbeit · Akten · Läufe · Zahlen`». Abschnitt 1 begründet, warum Einfach-/Profimodus das falsche Problem lösen.

`core/navigation.py` Zeile 1–3: «6 Bereiche ("Türen") … mit zwei Modi: 'einfach' … 'profi'». Die Gruppen heissen Heute, Portfolio/Meine Immobilien, Vermietung/Vermieten, Finanzen/Geld, Berichte/Übersichten, Kontakte/Personen & Handwerker. Im Einfachmodus hängen **18 Einträge** unter «Erweitert» (darunter Läufe, Regelwerk, Mandate), im Profimodus **16 unter Finanzen**. Etappe 4a.6 («Navigation auf vier Bereiche; alte Navigation entfernen») ist nie ausgeführt worden; die Tabelle 13.2 im Konzept führt sie ohne Stand.

**Wirkung:** Die neuen Seiten aus 4b.5–4b.13 (Arbeit, Zulauf, Läufe, Termine, Fallakte) hängen als Untereinträge in einer Struktur, die das Konzept abschaffen wollte. Wer die Anwendung zum ersten Mal sieht, sieht die alte. Der Modus-Schalter («Einfach/Profi» in der Kopfzeile) ist ein Sessionschalter für ein Problem, das ins Entitlement gehört.

### B2 · Die Oberfläche hängt an drei Fremdservern — A

`core/templates/fw/base.html` Zeile 9: `<script src="https://cdn.tailwindcss.com">` (Browser-JIT, kein Build). Zeile 11: Font Awesome 6.4 von cdnjs. Zeile 13: Inter von Google Fonts. `fw/base_embed.html` und die Modale laden dasselbe.

Im Test ohne Zugang zu diesen Hosts rendert die Anwendung **komplett unformatiert** (Screenshot liegt vor). Dazu: 15'619 Utility-Klassen in 113 Templates gegen ~60 Komponentenklassen; 190 Inline-Styles; die Petrol-Palette wird über `_tailwind_palette.html` **zur Laufzeit in Tailwind eingeschoben**, und der Dunkelmodus funktioniert nur dort, wo `fw-*` steht (der Palette-Kommentar sagt das selbst: «Was das nicht löst: der Dunkelmodus»).

`docs/UEBERGABE-PHASE-4.md` Abschnitt 2 («Der CDN-Punkt ist nicht nur technisch») kennt den Befund. Er ist nicht behoben.

**Wirkung:** Kein Offline-/Vor-Ort-Modus möglich, Ladezeit hängt an Dritten, Datenschutz-Fussnote (Google Fonts), und das Design-System-Ziel aus der Projektanweisung («bis kein Einzelfall-Styling mehr existiert») ist bei 15'619 Utilities nicht erreichbar, solange kein Build existiert.

### B3 · Zwei Arbeitskörbe, drei Wahrheiten — A

Gleiche Instanz, gleicher Tag:

- **Heute** (`faelle/arbeitsvorrat.py` Z. 85–95, Quelle `faelle.Lauf`): «Sollstellung 2026-08 nicht ausgelöst · 20 Tage über», «Bankabgleich … 16 Tage über», «Mahnlauf … 6 Tage über».
- **Finanz-Cockpit** (`core/views/fw/dashboard.py` Z. 140–252, Quelle `DebitorenRechnung.objects.filter(titel=soll_titel)`): Arbeitskorb «Zahlungseingänge abgleichen — erledigt», «Überfällige Forderungen mahnen — erledigt», grüner Balken «Alle Finanzaufgaben erledigt — nichts offen». Der Block «Monatsabschluss 08/2026» daneben sagt «3/4» und führt nur die Sollstellung als offen.

Drei Bildschirmaussagen zu denselben drei Läufen. Der Grund ist struktureller Natur: Das Finanz-Cockpit ist ein zweiter Arbeitskorb mit eigener Logik — genau die Doppelung, die G2 («Ein Arbeitsvorrat, nicht zwei Listen») in 4b.5 zwischen Inbox und Arbeitsvorrat behoben hat, eine Ebene tiefer.

**Wirkung:** Für eine Buchhalterin ist das ein Vertrauensbruch; ein «10k-Werkzeug» darf sich nicht widersprechen.

### B4 · Kontrast der Seitenleiste verfehlt WCAG AA — B

`fw/base.html` Z. 59–60 setzt global `.text-slate-400, .text-slate-300 { color: var(--ds-muted) !important }` — richtig für helle Flächen (8.4:1 auf Surface, so der Kommentar Z. 731). Die Seitenleiste (Z. 791, Verlauf `#122b31 → #0a1c20`) verwendet für inaktive Einträge aber genau diese Klassen (Z. 824, 835, 847). Gerechnet: `#4c6169` auf `#122b31` = **2.28:1**; Tailwinds ursprüngliches slate-300 hätte 9.99:1 erreicht. Die Screenshots zeigen es: «Vermieten», «Geld», «Übersichten» sind kaum lesbar.

`core/tests/test_palette.py` prüft Tokens, nicht Kontraste auf dunklem Grund.

### B5 · Mehrsprachigkeit: 1 von 185 — A

`settings.py`: `USE_I18N = True`, `LANGUAGE_CODE = 'de-ch'`, kein `LANGUAGES`, kein `LOCALE_PATHS`, kein `locale/`-Verzeichnis. Ein Template verwendet `{% trans %}`; 27 Python-Dateien `gettext`. Die Projektanweisung verlangt DE/FR/IT/EN «vollständig übersetzte Oberfläche und Dokumentvorlagen». Konzept 13.1 bindet i18n bewusst an den Design-System-Durchgang («dieselben 173 Templates»). Beides steht noch bevor — und muss zusammen geschehen, sonst wird jedes Template zweimal angefasst.

### B6 · `seed_e2e` ist seit Etappe 6.3 kaputt — B

`core/management/commands/seed_e2e.py` legt Organisation und Liegenschaft **ohne** `organisation_kontext` an. Ausführung bricht mit `ValueError: Kein Mandantenkontext` ab (`core/organisation_kette.py` Z. 101). Damit kann `playwright.config.ts` / `e2e/` nicht mehr gegen eine frische Datenbank laufen. Das UI hat aktuell keinen automatischen Wächter ausserhalb der Django-Tests.

### B7 · Das ⌘K findet Seiten, keine Datensätze — B

`core/navigation.py` Z. 178–196: `fw_palette` ist die flache Liste der Menü-Labels plus vier feste Einträge. Die Datensatzsuche liegt separat in `fw_suche` (`views/fw/listen.py`). Ein Premium-Werkzeug hat **eine** Stelle: Tippen → Akte, Person, Objekt, IBAN, Fall-Nummer, Seite.

### B8 · Icons: 178 verschiedene, kein System — C

178 unterschiedliche `fa-*`-Klassen in den fw-Templates; die Prototypen v3–v6 arbeiten mit Inline-SVG. Die Anwendung wirkt dadurch «zusammengestellt»: gleiche Bedeutung, verschiedene Icons (z. B. Dokument/Datei/Akte). Für Phase 4 braucht es ein Icon-Set von ~40 Zeichen mit fester Bedeutung.

### B9 · Abo-Modell: zwei Quellen, kein Anbieter — A (Phase 3)

`crm.Organisation.abo_plan` kennt `start/pro/premium` (Z. 85). `core/funktionen.py` kennt `basis/aufbau/verwaltung/portfolio`. `docs/MARKT.md` schlägt `Start/Team/Professional/Enterprise` vor. Drei Vokabulare, keine Verbindung; `stufe_von()` liest eine Settings-Konstante. Kein Zahlungsanbieter im Code (kein Stripe/Payrexx/Datatrans-Treffer), kein Modell für Abo-Periode, Testphase, Kontingente oder Zahlungsausfall. Phase 3 ist faktisch nicht begonnen — nur die Naht existiert.

### B10 · Listen ohne Werkzeugkasten — B

Gemessen an `fw_vertraege.html`, `fw_liegenschaften.html`, `fw_objekte.html`: keine Mehrfachauswahl, keine Spaltenwahl, keine gespeicherten Filter, kein CSV-Export auf den Kernlisten (Export gibt es nur in Bankabgleich, Buchhaltung, Kontenplan, MWST, Logbuch, Fristen). Bei 150–800 Einheiten ist das die tägliche Reibung: «alle gekündigten Mietverhältnisse im Mandat X mit Rückgabe im Q4 als Liste an den Eigentümer».

### B11 · Mobile: funktioniert, ist aber nicht gedacht — B

Die Seiten stapeln sauber (Screenshots Heute, Verträge, Liegenschaften in 390 px). Aber: Die Navigation ist nur über ein Icon im Kopf erreichbar (hängt an Font Awesome), es gibt keine Tab-Leiste, die Reiterleisten laufen aus dem Bild («Vermarktung · Bewerbungen · …» abgeschnitten), und der Vor-Ort-Fall (Abnahme mit Fotos, Zählerständen, Unterschrift) — laut `funktionen.py` Schlüssel `vor_ort` — existiert nicht. `Abnahmeprotokoll` und `AbnahmeMangel` sind Desktop-Formulare.

### B12 · G9 noch nicht überall — C

Konzept Abschnitt 2: «Umgesetzt seit 4b.2 … Offen: Objekt, Mandat, Dienstleister» für «Was auffällt». Die Kennzahlenleisten sind seit 4b.12 überall, die Befunde nicht.

### B13 · Visuelle Reife — B

Die Anwendung sieht heute aus wie ein gut gemachtes Tailwind-Admin: graue Karten auf grauem Grund, überall gleiche Kartenradien, Kopfzeilen-Icon in Pastellkästchen, dunkler Verlauf links. Das ist sauber, aber austauschbar — nichts daran sagt «Schweizer Verwaltung, Präzision, Fristen». Typografie: Inter 400–800, keine Tabellenziffern ausserhalb `fw-num`, Beträge in Listen teils fett, teils nicht. Leere Zustände sind kursive Einzeiler («Nichts Unzugeordnetes.») statt Einladungen zum Handeln.

---

## 4. Bewertung gegen den 10k-Anspruch

Skala 1–5. «10k» heisst hier: eine Verwaltung zahlt CHF 8'000–12'000 pro Jahr (Enterprise-Stufe plus Module plus Onboarding nach `MARKT.md`) — und empfindet das als günstig, weil das Werkzeug Fristen hält, Prozesse trägt und Eigentümer beeindruckt.

| Dimension | Ist | Ziel | Was fehlt |
|---|---|---|---|
| Fachliche Tiefe (CH-Mietrecht, Finanzen) | 4 | 5 | Mietzinsanpassung als Lauf, NK-Lauf geführt, Formulare je Kanton |
| Prozess-Sicherheit (Fälle, Fristen, Regeln) | 4 | 5 | Rückwirkende Fallerzeugung (4a.7), Regelfamilien ausser Kündigung |
| Informationsarchitektur | 2 | 5 | B1, B3 |
| Design-System / visuelle Reife | 2 | 5 | B2, B8, B13 |
| Zugänglichkeit (WCAG AA) | 3 | 5 | B4, Tastaturpfade, Fokus in Modalen |
| Mobile / Vor Ort | 2 | 4 | B11 |
| Suche & Listen | 2 | 5 | B7, B10 |
| Mandantenfähigkeit & Rollen | 4 | 5 | Mandantenwechsel im UI, Zuständigkeit je Mandat (G8) |
| Abo, Module, Abrechnung | 1 | 5 | B9 |
| Mehrsprachigkeit | 1 | 5 | B5 |
| Portale (Eigentümer, Mieter) | 3 | 5 | Gestaltung, Selbstbedienung (Schaden, Dokumente, Zahlungen), Branding |
| Schnittstellen | 3 | 4 | Buchhaltungsexport, Kalender, API-Doku |
| Qualitätsnetz (Tests, E2E) | 4 | 5 | B6 |

**Summe:** Der Unterbau ist ein 4, die Oberfläche ein 2. Der Hebel liegt deshalb fast vollständig in Struktur, Design-System und den drei Phase-3-/Phase-5-Lücken (Abo, i18n, Vor-Ort). Das ist die gute Nachricht: Es muss wenig neu erfunden, aber viel zu Ende gebracht werden.

Der Plan dazu steht in `Plan-10k.md`, das Zielbild in `konzept-v7.html`.
