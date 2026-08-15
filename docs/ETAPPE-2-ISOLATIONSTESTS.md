# Etappe 2 — Isolationstests rot schreiben

**Stand:** 15.08.2026 · gemessen an `main` nach Abschluss von Etappe 1
**Grundlage:** `docs/ISOLATIONSTESTS.md` (Katalog), `docs/PHASE-2-PLAN.md` (Etappe 2)
**Basis:** `main`
**Skill:** `mandantentrennung` — vor der ersten Zeile lesen

---

## Was hier anders ist als in allen bisherigen Etappen

In Etappe 0 und 1 war ein Fehler sichtbar: Der Test wurde rot, die URL löste nicht auf, die Zeilenbilanz ging nicht auf.

Hier nicht. **Ein falsch gebauter Isolationstest ist grün und prüft nichts.** Er sieht aus wie ein richtiger, läuft durch, und gibt der Definition of Done eine Bestätigung, die sie nicht verdient. Das ist die einzige Etappe, in der Sorgfalt nicht durch Werkzeuge ersetzt werden kann.

Deshalb gilt hier eine zusätzliche Abnahmebedingung, siehe „Die Gegenprobe" weiter unten.

---

## Warum die Tests vor `Organisation` entstehen

Sie sind zu diesem Zeitpunkt **alle rot** — das Modell existiert noch nicht. Genau das ist der Zweck:

- Ab hier ist die Definition of Done eine Zahl, keine Behauptung. Phase 2 endet, wenn keiner mehr rot ist.
- Ein Test, der geschrieben wird, *nachdem* der Filter existiert, wird unbewusst so gebaut, dass er zum Filter passt. Umgekehrt bestimmt der Test, wie der Filter aussehen muss.
- Ein Test, der auch ohne Filter grün wäre, fällt bei rot geschriebenen Tests sofort auf — bei nachträglich geschriebenen fast nie.

---

## Die Prüffläche, gemessen

Alle Zahlen am 15.08.2026 gegen den Bestand geprüft.

| | |
|---|---|
| Benannte URLs | 293 |
| davon mit genau einem ID-Parameter | **152** |
| Verteilung | `pk` 119, `vertrag_id` 19, `einheit_id` 4, `liegenschaft_id` 3, `periode_id` 2, `mieter_id` 1, `kreditor_id` 1, `lg_id` 1, `nummer` 1, `pfad` 1 |
| Projekt-Modelle | 63 (Django-eigene nicht mitgezählt: 69 insgesamt) |
| Global eindeutige Felder, die je Organisation gelten müssen | 6 |
| Management-Commands | **18** |

> **Zwei Korrekturen gegenüber der ersten Fassung dieses Auftrags.**
>
> **Es sind 18 Management-Commands, nicht 19.** Die Zahl 19 steht auch in `docs/ANALYSE.md` und in `docs/PHASE-2-PLAN.md` (Etappe 6) und ist an allen drei Stellen falsch. Gezählt: `backup_db`, `bewerbungen_bereinigen`, `check_rents`, `dsg_anonymisieren`, `fetch_rechnungen`, `fetch_replies`, `fristen_digest`, `jahresabschluss_lauf`, `mahnlauf`, `mieter_zugang`, `monatslauf`, `pruefe_media_schutz`, `pruefe_webhook_secrets`, `seed_e2e`, `send_eigentuemer_reports`, `sync_contracts`, `taeglicher_lauf`, `update_rates`.
>
> **„6 globale Unique-Constraints" ist richtig, aber missverständlich.** Im Bestand gibt es **zwölf** Eindeutigkeits-Zusicherungen; sechs davon sind unproblematisch, weil sie ohnehin je Datensatz gelten (`Mieter.benutzer` und `Eigentuemer.benutzer` als 1:1 auf `auth.User`, `SchadenMeldung.uuid`, `Erneuerungsfonds.liegenschaft`, `Mahnung(rechnung, stufe)`, `Abschreibung(anlage, jahr)` — alle über einen Fremdschlüssel gebunden). Umzubauen sind genau diese sechs:
>
> `Buchungskonto.nummer` · `Buchung.beleg_nr` · `LieferantProfil.name_key` · `NebenkostenLernRegel.suchwort` · `ZahlerZuordnung.name_norm` · `Lebensdauer.kategorie`

Von Hand wären das über 240 Testmethoden. Die Masse läuft deshalb **datengetrieben** über die Registry — rund 35 bis 40 Methoden decken alles ab, und neue Views sind automatisch mitgeprüft.

---

## Schritt 2.1 — Das Fixture (die eigentliche Arbeit)

Ohne zwei vollständige Mandanten laufen die Registryläufe ins Leere, weil zu vielen URL-Parametern kein Objekt existiert. **Das ist der Schritt, an dem Etappe 2 steht oder fällt** — nicht die Tests selbst.

Neues Modul `core/tests/_isolation.py`, aufbauend auf dem vorhandenen `core/tests/_helfer.py` (`_team_user`, `_basis_objekte`, `_seed_konten` sind bereits da und sollen nicht neu erfunden werden).

Gebraucht werden **zwei** vollständige Datenbestände, A und B, je mit: Verwaltung, Eigentümer, Liegenschaft, Einheit, Mieter, Mietvertrag, Buchungskonten, Buchung, Debitorenrechnung, Kreditorenrechnung, Zahlungseingang, Abrechnungsperiode, Dokument, Schadenmeldung, Pendenz, Wartungsfrist — und je ein Team-Benutzer.

Zwei Anforderungen, die leicht übersehen werden:

**Die IDs müssen sich unterscheiden.** Wird A vollständig vor B angelegt, hat A durchweg niedrigere IDs. Ein Test, der `objekt_b.pk` verwendet, trifft dann nie zufällig einen Datensatz von A — was gut ist. Umgekehrt darf der Test aber nicht davon abhängen, dass B immer die höheren IDs hat.

**Zu jedem der zehn Parameternamen muss ein Objekt aus B gehören.** Die Zuordnung von Parametername zu Modell (`vertrag_id` → `Mietvertrag`, `periode_id` → `AbrechnungsPeriode`, `kreditor_id` → `KreditorenRechnung`) gehört in eine **explizite Tabelle** im Modul, nicht in eine Namensheuristik. Was sich nicht zuordnen lässt, muss **auffallen** — ein stilles Überspringen wäre genau die Lücke, die der Test verhindern soll.

Zwei der zehn Parameter sind keine Objekt-IDs und brauchen eine eigene Behandlung: `nummer` ist eine Kontonummer (`fw_kontoblatt`), `pfad` ein Dateipfad (`geschuetzte_media`). Beide gehören in die Ausnahmeliste aus Schritt 2.2 — mit dem Vermerk, dass sie in Bauform C von Hand geprüft werden, nicht dass sie unkritisch wären.

---

## Schritt 2.2 — Bauform A und B, datengetrieben

**A — Registrylauf über alle objektbezogenen URLs.** Eine Methode, rund 148 Fälle. Angemeldet als Benutzer von A, aufgerufen mit der ID eines Objekts von B, erwartet **404**.

Warum 404 und nicht 403: Ein 403 bestätigt die Existenz des Datensatzes und erlaubt, über fortlaufende IDs den Bestand eines Wettbewerbers abzuzählen. `core/views/media_protected.py` macht das bereits richtig und ist als Vorbild lesenswert.

`subTest` je URL, damit ein Treffer nicht die übrigen verdeckt.

Echte Ausnahmen gehören in eine **benannte Liste mit Begründung im Code**, nicht in einen stillen Filter: `geschuetzte_media` (Pfad statt ID), `public_bewerbung` und `public_report` (bewusst öffentlich), der token-gesicherte Portal-Feed.

**B — Registrylauf über alle 63 Modelle.** Zwei Methoden:

1. Im Kontext von A enthält `Model.objects.all()` keinen Datensatz von B.
2. **Ohne gesetzten Organisationskontext wirft der Manager einen Fehler** — er gibt nicht stillschweigend alles zurück. Diese zweite Methode ist wichtiger, als sie aussieht: Ein Manager, der im Zweifel alles liefert, täuscht Sicherheit vor, und der Fehler fällt erst auf, wenn Daten schon geflossen sind.

---

## Schritt 2.3 — Bauform C, handgeschrieben

Rund 25 Methoden für alles, was keine URL und kein Modell hat, an dem man es automatisch findet:

| Bereich | Was geprüft wird |
|---|---|
| **Schreibpfade** | POST auf Bearbeiten und Löschen mit fremder ID. Löschpfade sind erfahrungsgemäss am häufigsten ungeschützt — und am teuersten, wenn sie es sind. |
| **Dateiablage** | `geschuetzte_media` liefert eine Datei von B nicht an A aus, auch nicht über `%2e/`-Umwege. |
| **Portal-Downloads** | Eigentümer- und Mieterportal sind bereits datensatzbezogen isoliert; hier zusätzlich die Organisationsgrenze. |
| **Exporte und PDFs** | Inhalt prüfen, nicht nur den Statuscode. Ein Export enthält nur Daten einer Organisation, auch wenn ein Superuser ihn auslöst. |
| **Hintergrundjobs** | `monatslauf`, `mahnlauf`, `taeglicher_lauf`, `jahresabschluss_lauf`, `fristen_digest`, `send_eigentuemer_reports`, `dsg_anonymisieren`, `bewerbungen_bereinigen`: läuft für A, Bestand von B unberührt? |
| **Absender in Dokumenten** | Ein PDF für einen Datensatz von B trägt nie den Absender von A. Deckt die verbliebenen `Verwaltung.objects.first()`-Stellen ab. |
| **Unique-Constraints** | Die sechs oben benannten Felder. Beide Organisationen müssen dasselbe Konto 4000, dasselbe Suchwort, denselben Lieferantenschlüssel führen können. Zusätzlich: Der Belegnummernkreis (`Buchung.beleg_nr`) zählt je Organisation. |
| **Admin** | Seit E2 lesend und auf 27 registrierte Admins beschränkt. Der Django-Admin umgeht den Manager über `_base_manager` — das ist zu prüfen, nicht anzunehmen. |
| **Cache** | Ein Cache-Key ohne Organisations-ID ist ein Datenleck mit Zeitverzögerung: A füllt, B liest. |

---

## Schritt 2.4 — Der Wächter

Eine Methode, die über die Modell-Registry läuft und fehlschlägt, sobald ein Modell existiert, das weder eine `organisation`-Spalte noch eine Pflicht-Kette dorthin hat und nicht in einer **begründeten** Ausnahmeliste steht.

Damit hört Vollständigkeit auf, Gedächtnisleistung zu sein. Wer in einem Jahr ein Modell hinzufügt und den Bezug vergisst, bekommt einen roten Test statt eines Datenlecks.

Dieselbe Bauform wie `AdminNurLesendTests` (E2) und `FwFassadeTests` (Etappe 1) — beide haben in dieser Sitzung bereits einen echten Bruch gefangen, den der Linter nicht sah.

---

## Die Gegenprobe — zusätzliche Abnahmebedingung

Für **jeden** Test dieser Etappe gilt: Er muss rot werden, wenn man die Isolation entfernt.

Solange `Organisation` nicht existiert, sind alle Tests ohnehin rot — das allein beweist nichts, denn ein Test, der am fehlenden Modell scheitert, würde auch scheitern, wenn er nichts prüft. **Die Gegenprobe ist deshalb in den Etappen 4 bis 6 nachzuholen**, sobald ein Test grün wird: Filter auskommentieren, Test muss rot werden, Filter zurück.

Das gehört mit Datum ins PR-Protokoll. Ein Test ohne durchgeführte Gegenprobe gilt als nicht geschrieben.

---

## Abnahme der Etappe

- `core/tests/_isolation.py` mit dem Fixture für zwei vollständige Mandanten
- Bauformen A, B, C, D umgesetzt, rund 35 bis 40 Methoden, über 240 Fälle
- **Alle rot**, jeder mit einer nachvollziehbaren Fehlermeldung — nicht mit einem `ImportError`, der nichts aussagt
- Die Zuordnungstabelle Parametername → Modell ist vollständig; nicht zuordenbare Parameter fallen auf
- Ausnahmelisten benannt und im Code begründet
- Testzahl steigt entsprechend; `manage.py check` und Ruff sauber

Die übrige Suite bleibt grün — die neuen Tests laufen in einem eigenen Modul und dürfen keinen bestehenden Test beeinflussen. Nach Etappe 1 sind das 22 Testmodule (19 Fachmodule in `core/tests/` plus `tests_perf`, `tests_perf2`, `tests_verify_perf`), an denen nichts geändert wird.

---

## Was nicht Teil dieser Etappe ist

- **`Organisation` einführen** — das ist Etappe 4, und der `chirurg` macht es, nicht der Testautor.
- **Bestehende Tests umschreiben.** Neues Modul, keine Eingriffe in die vorhandenen.
- **Isolation herstellen.** Hier wird nur beschrieben, was gelten muss. Wer beim Schreiben in Versuchung gerät, „schnell den Filter einzubauen, damit der Test grün wird", hat die Etappe missverstanden — dann prüft der Test wieder nur sich selbst.
