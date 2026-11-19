# Mitarbeit

Regeln, die heute gelten. Fast jede wird von einem Test durchgesetzt; der Test steht jeweils dabei.
Wie die Anwendung gebaut ist, steht in [ARCHITECTURE.md](ARCHITECTURE.md); Einstieg und Befehle in [README.md](README.md).

## 1. Ablauf einer Änderung

1. Auf einem eigenen Zweig arbeiten, ein Thema je Pull Request. Hauptzweig ist `main`.
2. Vor dem Pull Request lokal prüfen:
   ```
   python manage.py check
   python manage.py makemigrations --check --dry-run
   ruff check .
   python manage.py test --noinput --parallel 4
   ```
   Meldet `--parallel` einen Fehler ohne lesbaren Text, den betroffenen Testblock ohne `--parallel` wiederholen.
3. Commit-Betreff deutsch, im Muster «Bereich: was geändert wurde». Beschreibung des Pull Requests: Was, Warum,
   Verhaltensänderung, Einspielen (Migration, Umgebung), Tests, bewusst nicht getan.
4. Gemergt wird erst bei grüner CI.

### CI (`.github/workflows/ci.yml`)

| Job | Prüft |
|---|---|
| `lint` | Ruff |
| `pip-audit` | bekannte Schwachstellen in Abhängigkeiten (Ausnahmen in `pip-audit-ignore.txt`) |
| `test` | `check`, Migrations-Check, `check --deploy` (Ausnahmen in `deploy-check-ignore.txt`), alle Tests auf SQLite |
| `test-postgres` | alle Tests auf PostgreSQL 16 |
| `e2e` | Playwright im Browser, mit scharfer Content Security Policy |
| `wartung` | wöchentlich: Aktualität der LIK-Tabelle |
| `zeitlauf` | monatlich: Szenarien mit verschobener Uhr |

Dependabot-PRs werden einzeln geprüft: Patch- und Minor-Updates mit grüner CI auf aktuellem `main` kommen sofort
hinein. Hauptversionen, die eine Migration verlangen (Tailwind 4: neue CLI, neue Konfiguration) oder in der CI nicht
installierbar sind (reportlab 5), werden mit `@dependabot ignore this major version` zurückgestellt und als eigenes
Arbeitspaket geplant.

### Was eine Freigabe braucht

Neue Python- oder JavaScript-Pakete, neue externe Dienste, alles mit Kosten oder Datenabfluss ins Ausland, Änderungen
an Preisen und Abo-Stufen, Löschen von Daten. Jeder Fremd-Import muss in `requirements.txt` stehen
(`test_abhaengigkeiten_deklariert`).

## 2. Namensgebung

- **Deutsch überall:** Bezeichner, Kommentare, Commit-Texte. In Namen `ae`, `oe`, `ue` statt Umlauten.
  Schweizer Schreibweise: «ss», kein «ß».
- **Ansichten der Verwaltung:** Funktionen `fw_…` in `core/views/fw/`, URL-Namen `fw_…`, Adressen `/neu/<bereich>/…`,
  Aktionen als Endung (`…/bearbeiten/`, `…/loeschen/`). Routen in `swiss_immo/urls_neu_*.py`.
- **Vorlagen:** `core/templates/fw/`, Bausteine mit `_` am Anfang (`_feld.html`, `_empty.html`, `_seiten.html`).
- **Skripte:** `static/js/fw-*.js`, eingebunden mit `{% statisch %}`. Keine Fremdbibliothek unter `static/js/`
  (`test_vendor_dateien`).
- **Tests:** `core/tests/test_<thema>.py`, Helfer mit `_` (`_helfer.py`, `_isolation.py`, `_uhr.py`); in `faelle/`
  und `abo/` liegen die Tests direkt in der App.
- **Migrationen:** ein Strang je App, sprechende Namen statt `auto_…` (`test_migrationen_ordnung`).
- **Namen nachsehen, nie raten.** Vor dem Gebrauch im Code prüfen, wie ein Feld, eine Route oder eine Klasse heisst.

## 3. Mandantentrennung

- `Model.objects` filtert auf die aktive Organisation und wirft ohne Kontext. Ausserhalb einer Anfrage:
  `with organisation_kontext(org):`. Bewusst über alle Verwaltungen: `Model.alle_organisationen` — jede solche Stelle
  braucht einen Grund im Kommentar.
- Jedes Fachmodell hat einen Weg zur Organisation; Ausnahmen sind begründet (`test_isolation`). Jedes Mandantenmodell
  hat eine Zeile im Testbestand (`test_isolation_abdeckung`).
- Eine fremde ID ergibt 404, nicht 403. IDs aus Formularen werden über den Manager **aufgelöst**, nie als nackte Zahl
  übernommen (`core/utils/formularid.eigenes_objekt`).
- Eindeutigkeit gilt je Organisation; Cache-Schlüssel tragen die Organisation; Dateien liegen unter `organisation/<id>/…`.
- `Benutzer` hat keinen Mandantenfilter: Personen einer Verwaltung über `Mitgliedschaft` auswählen.
- Ein Isolationstest zählt erst, wenn er mit entferntem Filter einmal rot war (siehe Gegenprobe, Abschnitt 7).

## 4. Rechte

- Jede Ansicht trägt `@rolle_erforderlich(*…_ROLLEN)` direkt über der Funktion — nichts dazwischen einfügen
  (`test_rbac` prüft alle Routen).
- Die Oberfläche bietet nur an, was die Rolle öffnen darf: `{% if kann_schreiben %}` oder
  `{% load rechte %}{% if request.user|darf:"/neu/…" %}` (`test_oberflaeche_rolle`).
- Jede Seite der Verwaltung meldet einen `nav`-Schlüssel (`test_menueband_zuordnung`) und ist von irgendwo erreichbar
  (`test_erreichbarkeit`).

### Rollentabelle

| Handlung | Inhaber | Verwalter | Sachbearbeiter | Lesezugriff |
|---|---|---|---|---|
| Lesen, Daten exportieren | ✓ | ✓ | ✓ | ✓ |
| Akten bearbeiten, Fälle führen | ✓ | ✓ | ✓ | — |
| Kündigung erfassen, bestätigen, zurücknehmen | ✓ | ✓ | — | — |
| Rechnungen freigeben, Zahlung auslösen, Zahllauf | ✓ | ✓ | — | — |
| Mahnlauf, Betreibung, Frist nach Art. 257d OR | ✓ | ✓ | — | — |
| Nebenkostenabrechnung freigeben und versenden | ✓ | ✓ | — | — |
| Freigabelimite einstellen | ✓ | — | — | — |
| Mitglieder und Rollen, Abo und Module | ✓ | — | — | — |

Buchhaltung: Finanzen wie Verwalter, ohne Betreibung, Mitglieder und Abo. Revision: Finanzen und Logbuch lesen.
Hauswart: Schadenfälle seiner Liegenschaften.

## 5. Oberfläche

### Design-System
- Live-Filter im Browser (`<input data-suche="#liste">`, `fw-rahmen.js`): Zeilen tragen `data-zeile`, Gruppen `data-gruppe` (verschwinden ohne
  Treffer), die Meldung `data-keine`; nur dort, wo alles auf einer Seite steht (Einstellungen, Berichte: `e2e/tests/einstellungen-suche.spec.ts`,
  `berichte-suche.spec.ts`).
- Schrift mindestens 12 px; Ausnahmen (Zahlen in kleinen Kreisen, Diagrammachsen, Mikroschrift) stehen mit Begründung in
  `core/tests/test_schrift_mindestgroesse.py`.
- Tippflächen am Handy (bis 640 px): Filter-Chips und kleine Knöpfe mindestens 40 px, Segmente 36 px, Schliessen-Knopf 36 px;
  kleine Zeichen (Hilfe-«i») behalten ihre Optik und bekommen die Fläche unsichtbar dazu (`::before`). Wächter:
  `e2e/tests/tippflaechen-handy.spec.ts`.
- «Rückgängig» nur mit geprüfter Rücknahme (`meldung_mit_rueckgaengig`, siehe ARCHITECTURE «Rückgängig (Toast)»); Buchungen werden nie
  gelöscht, die Rücknahme storniert (`faelle/test_rueckgaengig_toast.py`).
- Avatare tragen das Kürzel aus Vor- und Nachname (`{% load kuerzel %}`, `|kuerzel`: «DG»), nicht die ersten zwei Buchstaben des
  Namens (`test_kuerzel`).
- Erledigtes wird mit Haken markiert (`zeichen 'gut'`), nie durchgestrichen: Durchgestrichen heisst «storniert»
  (`test_finanzen_abschluss_darstellung`). Ein Titel steht einmal auf der Seite.
- Listen: Die Sortierung wirkt sofort, «Anwenden» (`fw/_listwerkzeug.html`) ist nur ohne Skript sichtbar; Gesucht wird auf dem Server
  (Enter), weil mit Seiten ein Filter im Browser nur die aktuelle Seite träfe (`e2e/tests/liste-sortierung.spec.ts`).
- Kennzahlen stehen sofort im Endwert, nie als Hochzähl-Animation (`test_kennzahlen_sofort`).
- Quelle der Stilschicht ist `core/templates/fw/_schicht.html`; ausgeliefert wird `static/css/schicht.css`. Nach jeder
  Änderung `python manage.py schicht_bauen` (`test_schicht_gebaut`).
- Farben nur über Tokens `--ds-*`. Jedes benutzte Token ist definiert, kein totes Token, beide Dunkelblöcke führen
  dieselben Tokens (`test_ds_tokens`). Textfarben erreichen 4,5:1 in hell und dunkel (`test_palette`).
- Klassen `fw-*`; jede in einer Vorlage benutzte Klasse braucht eine Regel (`test_fw_klassen_wirken`).
- Tailwind nur als Build (`npm run css`); Farb-Utilities dürfen nur weniger werden (`test_farbklassen`).
- Kein `style="…"` in Vorlagen und kein `el.style` in Skripten: dynamische Masse über `fwStil()` aus
  `static/js/fw-stil.js` oder `data-breite`, `data-hoehe` (`test_stilschuld`). Ausnahmen: E-Mail und PDF.
- Leere Zustände über `fw/_empty.html`. Lange Listen blättern mit `core/views/fw/_liste.blaettern` und `fw/_seiten.html`.
- Symbole nur über `{% load zeichen %}{% zeichen 'name' %}`. Die erlaubten Namen stehen in
  `core/templatetags/zeichen_tabelle.md`; ein neues Symbol zuerst dort eintragen (`test_zeichen_sprite`).
- Schrift: DM Sans, für Zahlen und Kennungen IBM Plex Mono; lokal ausgeliefert, keine fremden Hosts
  (`test_fremdschrift`, `test_keine_fremdquellen`).
- Geprüft wird bei Telefonbreite 390 × 844, nicht nur am Desktop.
- Neue Seite im Menü: Eintrag in `core/navigation.py` (Bereich, `keys`), die View meldet einen dieser Schlüssel als
  `nav`. `test_menueband_zuordnung` prüft, dass jede Menüseite ihren eigenen Punkt hervorhebt; `test_erreichbarkeit`,
  dass jede Seite einen Weg hat. Der Aufbau der Schiene steht in ARCHITECTURE.md, «Navigation».
- Beträge: Feld `type="text" inputmode="decimal" data-chf`, ein Parser (`core/utils/betrag.py`), intern `Decimal`.
- Jedes Modellfeld, das ein Mensch setzt, braucht einen Eingabeweg (`test_felder_ohne_eingabe`); jedes Formularfeld
  einen zugänglichen Namen (`test_feldnamen`).
- Mehrzeilige Kommentare in Vorlagen mit `{% comment %}`, nie `{# #}` über mehrere Zeilen.

### Tailwind (Version 4)
- Gebaut wird mit `npm run css` (`tailwind.bauen.js`): Das Skript löst die Muster aus `tailwind.inhalt.js` (mit `!` für die
  Testdateien) zu einzelnen Dateien auf, schreibt daraus eine Eingabedatei mit einem `@source` je Datei und ruft
  `@tailwindcss/cli` auf. Ergebnis ist die eingecheckte `static/css/tailwind.css`; nach jeder neuen Utility-Klasse neu bauen
  (`test_tailwind_gebaut`). Palette und Tokens stehen weiter in `tailwind.config.js` / `tailwind.palette.js` (Weiterleitung per
  `@config`).
- `tailwind.eingang.css` hält fest, was von Tailwind 3 unverändert bleibt, damit die Seiten gleich aussehen (Vergleich am
  19.11.2026: 124 Seiten bei 1280 und 390 px, Bild für Bild): Utilities stehen **nicht** in einer `@layer` (sonst schlüge jede
  ungeschichtete `fw-*`-Regel auch eine stärkere Utility, z. B. `space-y-4` gegen `.fw-hilfe`), `space-y-*` setzt den Abstand wie
  früher vor jedes sichtbare Kind, Rand-, Platzhalter- und Knopf-Vorgaben, die Höhe der Datumsfelder und der Knopf der Dateiwahl.
- Tailwind 4 setzt moderne Browser voraus (Safari 16.4, Chrome 111, Firefox 128).

### Palette

`test_palette` vergleicht diese Tabelle mit `core/templates/fw/_schicht.html`. Vorbild: `mockups/konzept-v8-cockpit.html`;
Info-Farbe `#7f959c`.

| Token | Hell | Dunkel |
|---|---|---|
| `--ds-brand` | `#b04416` | `#f08a55` |
| `--ds-brand-600` | `#8a3410` | `#f6a77c` |
| `--ds-brand-soft` | `#fbe7dc` | `#3a2317` |
| `--ds-ink` | `#17181b` | `#f1efec` |
| `--ds-muted` | `#5d6068` | `#b9b6b0` |
| `--ds-faint` | `#62656d` | `#9e9b94` |
| `--ds-line` | `#e7e5e1` | `#2c2d32` |
| `--ds-hover` | `#f3f1ee` | `#28292e` |

Rundung: 24 px für Karten, 14 px für kleine Flächen. Kapseln `var(--ds-pill)`, Kreise `var(--ds-kreis)` (50 %), nie `999px`
oder `50%` von Hand. Frei bleiben in `_schicht.html` nur vier Werte (6/3/2 px an Fokusring, Legendenpunkt, Marker); der Zähler
steht in `core/tests/test_stilschuld.py` und darf nur sinken. Hex-Farben stehen ausserhalb der Token-Definitionen nur als
Weiss auf Akzent oder mit Begründung (STWEG-Warnrot).

### Kennzahlen
- Oben auf Listenseiten steht eine Statuszeile (`.fw-statuszeile` / `.fw-sz`), keine Kachelwand. Farbklassen ausgeschrieben
  (`fw-sz-good`, `fw-sz-warn`, `fw-sz-crit`), nicht zusammengesetzt (`test_fw_klassen_wirken`).
- Neue Kennzahlen: weiter `.fw-kpis > .fw-kpi` mit `.fw-l` (Beschriftung), `.fw-v` (Wert, optional `fw-good|warn|crit` für den Farbpunkt)
  und `.fw-f` (Zusatz). Die Stilschicht macht daraus von selbst die Kapselzeile. Grosse Kacheln (`fw-gross`) gibt es nur auf Finanzen
  (`core/tests/test_statuszeile_standard.py`).

### Formulare
- Mehrere Wege zu einer Sache gehören in **einen** Dialog mit wählbaren Karten statt in mehrere Einzelformulare (Vorbild:
  `fw/_zuordnen_dialog.html`). Die Wege nutzen die bestehenden Routen; der Dialog stellt nur Adresse und Felder um. Ohne Skript
  bleibt ein Link zur Vollseite (`fw-nur-js` / `fw-ohne-js`).
- Pflichtentscheidungen nicht vorbelegen (Radio/Select ohne Vorauswahl, `required`); `data-knopf-erst-gueltig` am `<form>`
  sperrt den Absende-Knopf bis zur gültigen Eingabe. Auswahl-Vergleiche in Vorlagen ohne `add` auf Zahlen bauen
  (`'' == ''`-Falle, siehe `ARCHITECTURE.md`, «Formulare ohne riskante Vorbelegung»).

### Skripte und Content Security Policy
- Jedes Inline-`<script>` trägt `nonce="{{ csp_nonce }}"`. Keine Inline-Handler (`onclick=` …): stattdessen
  `data-bei-klick` oder `addEventListener` (`test_csp`).
- `<style>` nur mit Nonce.
- Werte in HTML-Strings durch `fwEsc` (`static/js/fw-sicher.js`), sonst `textContent`. Neue `innerHTML`-Zuweisungen
  brauchen eine Durchsicht (`test_markup_einschleusung`).
- Rückfragen über `data-bestaetigen="{% filter escapejs %}…{% endfilter %}"`.
- Geheimnisse gehören nicht in Adressen, die im Protokoll landen; neue Pfade mit Token in `core/logschutz.py` eintragen.

### Sprachen
- Jeder sichtbare Text ist ausgezeichnet (`{% trans %}`, `{% blocktrans %}`, `gettext`) und in allen vier Sprachen
  übersetzt; kein Eintrag `fuzzy`, die `.mo`-Dateien sind aktuell und im Repository (`test_uebersetzung`).
- Eine neue Vorlage in die Liste `UEBERSETZT` in `core/tests/test_uebersetzung.py` eintragen.
- Dokumente und Mails folgen der Sprache des Empfängers. Logik hängt an festen Schlüsseln, nie an übersetzten Texten.

## 6. Daten und Fachlogik

- **Schweizer Fachwerte nie aus dem Gedächtnis.** Referenzzinssatz, Landesindex, Fristen, Feiertage, Mahnstufen,
  MWST-Sätze und Formularpflichten kommen aus dem Bestand (`core/services/mietrecht.py`, `lik.py`, `fristen.py`,
  `mahnstufen.py`, `formularpflicht.py`, `mwst_estv.py`) oder aus einer genannten amtlichen Quelle.
- Geld ist `Decimal`. Auf Rappen wird mit `core.utils.betrag.runde_rappen` gerundet (kaufmännisch: 0.125 → 0.13); das eingebaute
  `round(Decimal, 2)` rundet zur geraden Zahl (0.125 → 0.12) und gehört nicht in Abrechnung und Sollstellung.
  Buchungen werden storniert, nie gelöscht.
- Geldpfade: sperren, prüfen, buchen — in dieser Reihenfolge und in einer Transaktion.
- Was länger dauert (viele Mails, viele Buchungen), läuft als Hintergrundauftrag und muss wiederholbar sein.
- Eingaben aus Formularen stürzen nie ab: Daten über `core.utils.eingabe` (`datum_oder_none`, `zeit_oder_none`;
  `parse_date` wirft bei «2026-02-30» einen Fehler 500, ein Wächtertest verbietet den direkten Import in Ansichten),
  Beträge über `core.utils.betrag` und `endlicher_betrag` (`NaN`/`Infinity` sind für `Decimal` gültig und knallen erst
  beim Vergleichen). Ungültiges ergibt eine Meldung, nie ein stilles Leeren und keine Fehlerseite.
- Alles, was eine Mail oder einen Datensatz auslöst, wirkt bei Doppelklick, Zurück-Taste oder zweitem Tab nur einmal:
  Zustand prüfen, bevor etwas entsteht (Kündigung im Portal, Besichtigungseinladung), und den auslösenden Zustand unter
  der Sperre verbrauchen, nicht erst danach (Terminbestätigung, `tickets/termin_abstimmung.py`). Test: zweimal
  abschicken, es gibt genau einen Datensatz und eine Mail (`core/tests/test_doppelausloesung.py`).
- Migrationen: `makemigrations --check --dry-run` bleibt leer; ein neues Pflichtfeld am Bestand in drei Schritten
  (Spalte, Daten füllen, Pflicht).

## 7. Tests

- **Gegenprobe ist Pflicht.** Zu jedem neuen Test den Fehler einmal einbauen, den Test rot sehen, zurückbauen. Die
  Gegenprobe steht im Kopf der Testdatei. Ein Wächter bekommt einen Selbsttest («findet überhaupt etwas»).
- Jeder Test enthält eine Prüfung (`test_tests_pruefen_etwas`).
- **Feste Uhr:** `@bei_stichtag(date(…))` aus `core/tests/_uhr.py` oder `timezone.localdate()`; keine neuen
  `date.today()` in Tests (`test_zeit_waechter`).
- **Abfragezahl:** Eine Liste darf nicht mit ihren Zeilen wachsen. Geprüft wird die Eigenschaft (gleiche Zahl bei
  mehr Zeilen), nicht eine feste Zahl (`test_skalierung_kernseiten`).
- **Obergrenzen:** Offene Spalten der Boards bleiben unbegrenzt (Arbeitsvorrat). Was sich nur ansammelt, ist begrenzt
  und verweist auf die Liste: Erledigtes im Schadenboard (30 Tage, 20 Karten), «Vertrag generiert» im Bewerbungsboard
  (20 Karten), ältere Absagen (30 Tage). Der Zähler der Spalte nennt immer die Gesamtzahl.
- **Ratschen:** Zahlen, die nur sinken dürfen (Farbklassen, Stilschuld, Inline-Handler, Uhr-Zugriffe,
  `innerHTML`-Stellen). Sinkt die Zahl, die Erlaubnis nachführen.
- Zwei Verwaltungen im Test: `MandantenFixture` aus `core/tests/_isolation.py`.
- Wer Skripte oder Vorlagen des Rahmens ändert, lässt die E2E-Tests laufen (`npm run e2e`).
