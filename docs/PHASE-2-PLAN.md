# Phase 2 — Etappenplan

**Stand:** 14.08.2026
**Grundlage:** `docs/ANALYSE.md` (Bestandsanalyse), `.claude/TEAM.md` (Mannschaft)
**Ziel:** Mehrere Verwaltungen nutzen dieselbe Instanz, ohne je Daten anderer Mandanten zu sehen.

---

## Getroffene Entscheide

Diese vier blockierten die Planung und gelten hiermit:

| # | Entscheid | Begründung |
|---|---|---|
| E1 | **`/app/`-SPA wird entfernt** | Kein `fw/`-Template ruft die API auf. Es fallen 80 von 82 Endpunkten, 7 Tab-Templates und 1'399 Zeilen JavaScript weg — und mit ihnen der ID-Offset-Hack aus TS-6, der ausschliesslich in SPA-Code steht. Halbiert den Aufwand jeder Folgephase. |
| E2 | **Unfold-Admin bleibt, wird aber entwaffnet** | 14 von 25 ModelAdmins sind bereits schreibgeschützt. Künftig durchgängig lesend und nur für Superuser. Damit ist er Betriebswerkzeug statt Zweitoberfläche und braucht weder Entitlements noch Übersetzung. **Pflicht dabei:** Der Admin umgeht den `TenantManager` über `_base_manager` und als Superuser — das ist in Etappe 4 ausdrücklich zu schliessen. |
| ~~E3~~ | ~~**`crm.Mandant` → `crm.Eigentuemer`**~~ — **erledigt am 14.08.2026.** | Es waren 623 Vorkommen in 56 Dateien (die Schätzung „135 Python- und 25 Template-Referenzen" zählte nur die Klassennamen, nicht die Feld- und Variablennamen). Ab Etappe 4 wäre daraus Code mit zwei kollidierenden Bedeutungen von „Mandant" geworden — kein Schönheitsfehler, sondern ein Datenleck-Risiko. |
| E4 | **`claude/fairwalter-rebuild` wird `main`** | `main` steht seit dem 21.05.2026 still, 501 Commits zurück. Die gesamte Arbeit hängt an einem Branch, dessen Name nach Wegwerf-Experiment klingt. Danach laufen alle PRs gegen `main`, das geschützt wird. |

---

## Etappen

Jede Etappe endet an einem **Gate**: einer nachprüfbaren Bedingung. Ohne erfülltes Gate beginnt die nächste Etappe nicht.

### Etappe 0 — Aufräumen *(läuft)*

P0-Liste aus `docs/ANALYSE.md`, plus E3 und E4. Agent: `aufraeumer`.

**Gate:** Alle P0-PRs gemergt. Ruff läuft in der CI. `main` ist aktuell und geschützt. `Eigentuemer` durchgängig umbenannt.

### Etappe 1 — Zerlegen

`core/views/fw.py` (14'938 Zeilen, 232 Views) in 34 Module entlang der vorhandenen Blockgrenzen. `core/tests.py` (16'586 Zeilen) nach Fachgebiet **und Laufzeit**. Agent: `zerleger`.

**Diese Etappe braucht ein Freeze-Fenster.** Ein reiner Umzug kollidiert mit jeder parallelen Änderung an derselben Datei. Solange nebenher an `fw.py` entwickelt wird, ist der Split ein Fass ohne Boden. Vorschlag: zwei bis drei Tage, in denen `fw.py` niemand sonst anfasst — Feature-Arbeit an anderen Dateien läuft weiter.

**Gate:** Alle 298 URLs auflösbar, Testsuite grün, Zeilenbilanz geht auf, im Diff keine inhaltliche Änderung.

### Etappe 2 — Isolationstests rot schreiben *(parallel zu Etappe 1)*

Katalog und Bauplan: **`docs/ISOLATIONSTESTS.md`**.

Rund 35 bis 40 Testmethoden, die über 240 Fälle abdecken — die Masse datengetrieben aus der URL- und Modell-Registry (152 URLs mit ID-Parameter, 63 Modelle), nicht abgetippt. Neue Views sind damit automatisch mitgeprüft. Dazu ein Wächter, der fehlschlägt, sobald ein Modell ohne Organisationsbezug hinzukommt.

*(Frühere Fassung dieses Plans nannte „rund 150 handgeschriebene Tests" — die Auszählung ergab eine andere Menge und eine bessere Bauform.)*

Sie sind zu diesem Zeitpunkt **alle rot**, weil `Organisation` noch nicht existiert. Genau das ist der Zweck: Ab hier ist die Definition of Done keine Behauptung mehr, sondern eine Zahl.

Läuft parallel, weil die Tests gegen URL-Namen geschrieben werden — die überleben den Split aus Etappe 1.

**Gate:** ~150 Tests vorhanden, alle rot, jeder mit nachvollziehbarer Fehlermeldung.

### Etappe 3 — Custom User Model

Ein PR, eine Hand. Agent: `chirurg`. Mitzunehmen im selben PR: `Eigentuemer.benutzer`, `Mieter.benutzer`, das Rollenmodell über `user.groups`, die Benutzerverwaltung in `/neu/`.

Danach praktisch nicht mehr möglich — deshalb vor allem anderen Architekturschritt.

**Gate:** Testsuite grün, Vorwärts- und Rückwärtsmigration ausgeführt, `mandanten-auditor` ohne Leckfund.

### Etappe 4 — Organisation und TenantManager

Drei PRs nacheinander: `Organisation` (Verhältnis zu `crm.Verwaltung` klären), `TenantManager` plus Middleware, Rollen je Organisation.

**Ohne gesetzte Organisation ist die richtige Antwort ein Fehler, nicht „alles zurückgeben".** Ein Manager, der im Zweifel alles liefert, ist schlimmer als keiner. Hier gehört auch die Admin-Umgehung aus E2 geschlossen.

**Gate:** Erste Isolationstests werden grün. `mandanten-auditor` ohne Leckfund.

### Etappe 5 — Bezug je App nachrüsten

Sieben PRs, einer je App. Agent: `migrations-handwerker`, Rezepte im Skill `phase-2-migration`. Parallelisierbar.

Zwei Stellen zum Anhalten: Gruppe B mit Waisen (Bestandsdatensätze ohne Weg zur Liegenschaft) und Gruppe A generell — beides fachliche Entscheide, keine technischen.

**Gate:** Alle 63 Modelle mit Bezug, `null=False`. Sechs globale Unique-Constraints umgebaut. `makemigrations --check` leer.

### Etappe 6 — Alles, was den Prozess verlässt

Dateiablage auf `organisation/<id>/`, 19 Management-Commands über Organisationen iterieren, PDF- und E-Mail-Absender aus der Organisation statt aus 132 Singleton-Lookups, `AktivitaetsLog` mit Organisationsspalte, Cache-Keys.

**Gate — und zugleich das Ende von Phase 2:** Alle ~150 Isolationstests grün. `mandanten-auditor` findet nichts.

---

## Parallelspur: 2FA

Unabhängig von der Kette, klein, verkaufsrelevant. Fairwalter führt Zwei-Faktor-Authentifizierung in **allen** Preisstufen; im Bestand fehlt sie (siehe `docs/MARKT.md`). Bei Mietverträgen, Lohnausweisen und Betreibungsauszügen ist das eine Ausschreibungsanforderung.

Sinnvoll nach Etappe 3, weil sie am User Model hängt.

---

## Was den Plan zum Scheitern bringen kann

**Parallele Feature-Entwicklung.** Commit `93b198d` entstand zwischen Bestandsanalyse und Push. Etappen 1, 3 und 4 fassen Dateien an, an denen sonst niemand gleichzeitig arbeiten darf. Ohne abgestimmte Fenster produziert das Konflikte, die teurer sind als die Arbeit selbst.

**Agenten, die überzeugende Filter schreiben, die nicht isolieren.** Deshalb Etappe 2 vor Etappe 3, und deshalb ist der `mandanten-auditor` an jedem Gate Pflicht — auch wenn es lästig ist.

**Etappe 5 als Fleissarbeit missverstehen.** 29 der 63 Modelle brauchen eine fachliche Entscheidung, keine Migration. Wer sie durchwinkt, löscht entweder Kundendaten oder legt sie offen.

**PostgreSQL-Wechsel zu spät.** SQLite trägt gleichzeitige Schreibzugriffe mehrerer Mandanten nicht. Der Wechsel (P1.4) gehört spätestens zwischen Etappe 4 und 5, besser früher — und `psycopg` fehlt bis heute in `requirements.txt`.

---

## Entscheide, die noch ausstehen

| Frage | Wann nötig |
|---|---|
| Freeze-Fenster für `fw.py`, zwei bis drei Tage | vor Etappe 1 |
| Kostenrechnung je Mandant — trägt CHF 39 den Betrieb? | vor Preisfestlegung |
| Hosting-Standort: PythonAnywhere oder Schweiz | vor Markteintritt, beeinflusst P1.4 |
| Zahlungsanbieter — Offerten Payrexx, wallee, Stripe | Phase 3, freigabepflichtig |
| Gespräche mit 5 bis 10 Verwaltungen zur Zahlungsbereitschaft | vor Preisfestlegung |
