# Mannschaft und Arbeitsteilung

Diese Datei beschreibt, welche Skills und Agenten es gibt, wofür sie zuständig sind und in welcher Reihenfolge sie zum Einsatz kommen. Grundlage ist `docs/ANALYSE.md` und die Projektanweisung.

## Zwei Schichten

Die Mannschaft ist in zwei Schichten gewachsen, und sie lösen einander nicht ab:

- **Die Phase-2-Rollen** (`aufraeumer`, `zerleger`, `chirurg`, `migrations-handwerker`, `mandanten-auditor`) sind für eine bestimmte, einmalige Arbeit geschnitten: die Mandantenfähigkeit einzuziehen. Sie haben ein Ende.
- **Die Fachabteilungen** (`javris` und die sechs darunter) sind die laufende Aufstellung für alles Weitere — Funktionen, Oberfläche, Schnittstellen, Abo-Modell, Sicherheit, Abnahme.

Der `mandanten-auditor` gehört zur ersten Schicht und bleibt trotzdem dauerhaft im Einsatz. Die Mandantengrenze wird nicht einmal gezogen und dann vergessen; sie wird bei jedem Diff neu verletzt oder nicht.

## Warum diese Aufteilung

Die Arbeit an dieser Codebasis zerfällt in drei Sorten, und nur eine davon skaliert über parallele Arbeit:

- **Kette** — Custom User Model, `Organisation`, FK auf 63 Modelle, `TenantManager`. Jeder Schritt setzt den vorherigen voraus, jeder ist irreversibel-teuer. Eine Hand, sorgfältiges Review. Mehr Parallelität macht das schlechter.
- **Masse** — `fw.py` zerlegen, Tests aufteilen, Migrationen je App, später die Übersetzung. Repetitiv, mechanisch, überprüfbar. Hier zahlt sich Arbeitsteilung aus.
- **Urteil** — Abo-Stufen, Zahlungsanbieter, Oberflächenstrategie, jede unklare Fachregel. Wird nicht delegiert, sondern vorgelegt.

Dass Agenten auf dieser Codebasis überhaupt tragen, liegt an den rund 2'400 Tests und der CI. Ohne diese Rückkopplung produzieren sie auf 68'000 Zeilen plausibel aussehenden Unsinn. Mit ihr haben sie eine harte Abnahme.

## Skills

Regeln, die über Sitzungen hinweg gelten. Werden von den Agenten gelesen.

| Skill | Inhalt | Wann |
|---|---|---|
| `bekannte-fallen` | Die Fehler, die hier schon gemacht wurden, mit Beleg und Gegenmittel | Vor jeder Änderung, und bevor etwas als geprüft gemeldet wird |
| `mandantentrennung` | Die Invariante: wie Modelle, Queries, Views, Dateien, Jobs, Exporte und Logs den Bezug herstellen | Immer, wenn eines davon angefasst wird |
| `swissimmo-review` | Definition of Done, Prüfbefehle, wie die Testsuite in dieser Umgebung durchläuft | Vor jedem Commit und PR |
| `phase-2-migration` | Drei Rezepte für die Modellgruppen A, B und C | Bei jeder Migration für Mandantenfähigkeit |
| `schweizer-fachlogik` | Wo Recht und Zahlungsstandards fest verdrahtet sind | Bei Mietrecht, Fristen, QR, MWST, Nebenkosten, Formularen |

`bekannte-fallen` ist die Ausfallstatistik dieses Projekts, keine Stilsammlung. Jeder Eintrag ist einmal passiert und hat eine Nachlieferung gekostet.

## Fachabteilungen

| Agent | Auftrag | Abnahme |
|---|---|---|
| `javris` | Leitung: Auftrag klären, schneiden, verteilen, zusammenführen, Abnahme verantworten | Sechs Punkte belegt, Offenes benannt, Entscheidfragen vorgelegt |
| `coder` | Umsetzung im Django-Bestand: Modelle, Views, Formulare, Dienste, Commands | Berechtigung, Validierung, Fehlerfall, leerer Zustand, Mandantenbezug |
| `ui-ux` | Oberfläche: Vorlagen, Komponentenschicht, Tokens, Zeichensatz, Konzept v7 | Messung bei 390 px, Schicht gebaut, Wächter grün |
| `api` | Endpunkte unter `/api/`, Webhooks, Integrationen | Erfolgs- **und** Abweisungsfall getestet, Organisationsbezug belegt |
| `erweiterungen` | Abo-Stufen, Entitlements, zubuchbare Module (Phase 3) | Eine Abfragestelle, Sperrfall getestet, Daten bleiben lesbar |
| `datenschutz` | DSG, Geheimnisse, Anmeldung, Uploads, Protokolle, öffentliche Einstiege | Bericht nach Schwere, Fundstellen verifiziert |
| `testabteilung` | Tests schreiben, Suite fahren, beurteilen ob ein Test etwas prüft | Gegenprobe zu jedem Test ausgeführt und benannt |

**`javris` schreibt keinen Fachcode.** Seine Arbeit ist Klären, Schneiden, Nachprüfen und Vorlegen. Ein Auftrag, dessen Abnahme er nicht formulieren kann, ist noch nicht verstanden und wird nicht verteilt.

**`testabteilung` und `datenschutz` dürfen ein Paket zurückgeben.** Sie sind keine Zuarbeit zur Umsetzung, sondern kommen danach.

## Phase-2-Rollen

| Agent | Auftrag | Abnahme |
|---|---|---|
| `aufraeumer` | P0-Liste: tote Importe, ungenutzte Pakete, Ruff | Tests grün, im Diff nur Löschungen |
| `zerleger` | `fw.py` → 34 Module, `core/tests.py` aufteilen | URLs auflösbar, Tests grün, Zeilenbilanz geht auf |
| `chirurg` | Die Kette: User Model, Organisation, TenantManager, Rollen | Ein Schritt pro PR, jeder von Hand gelesen |
| `migrations-handwerker` | Organisationsbezug je App nachrüsten | `makemigrations --check` leer, Rückwärtsmigration läuft |
| `mandanten-auditor` | Gegnerische Diff-Prüfung auf Mandantenlecks | Findet absichtlich eingebaute Lecks |

Der `mandanten-auditor` ist die wichtigste Rolle. Das Hauptrisiko ist nicht, dass ein Agent keinen Mandantenfilter schreibt — sondern dass er einen schreibt, der überzeugend aussieht und nicht isoliert.

## Abgrenzung, die zweimal erklärt werden musste

| Frage | Zuständig |
|---|---|
| Sieht Verwaltung A die Daten von Verwaltung B? | `mandanten-auditor` |
| Sieht jemand Daten, der gar nicht angemeldet sein müsste? | `datenschutz` |
| Bleiben Personendaten liegen, die weg müssten? Liegt ein Geheimnis im Klartext? | `datenschutz` |

Berührt eine Änderung beides, laufen beide. Nicht eines statt des anderen.

## Ablauf eines Auftrags

```
Auftrag (Alltagssprache)
   ↓
javris          Bestand lesen · klären · in Pakete schneiden
   ↓
coder · ui-ux · api · erweiterungen        (parallel, wenn sich die Dateien nicht treffen)
   ↓
testabteilung · datenschutz · mandanten-auditor     (parallel, lesen nur)
   ↓
javris          Abnahme nach swissimmo-review · Bericht · Entscheidfragen vorlegen
```

Parallel geht, was sich nicht in denselben Dateien trifft. Nacheinander gehört alles, was aufeinander aufbaut, und alles an der Mandantenkette. Im Zweifel nacheinander — der Engpass ist die zehnminütige Rückkopplung, nicht die Schreibgeschwindigkeit.

## Was Agenten nicht entscheiden

Diese Fragen werden vorgelegt, nicht beantwortet:

- Ob ein Stammdatenmodell je Organisation gehört oder echte Referenzdatei ist
- Was mit Bestandsdatensätzen ohne Bezug geschieht
- Zuschnitt der Abo-Stufen und Module, Preise, Verhalten bei Zahlungsausfall
- Neue Python-/JS-Abhängigkeiten, Plugins, MCP-Connectors, externe Dienste, alles mit Kosten oder Datenzugriff — nach Projektanweisung zu **beschreiben und vorzulegen, nicht umzusetzen**
- Jede unklare Fachregel im Schweizer Recht
- Löschen von Daten oder von Funktionen, die jemand benutzt

Im Zweifel anhalten und fragen. **Eine fehlende Funktion ist ein bekanntes Problem, eine falsch geratene Frist ein unbekanntes.**

## Isolationstests zuerst

Der Vorschlag mit der grössten Wirkung: die rund 150 Isolationstests **schreiben, bevor `Organisation` existiert**. Sie sind dann alle rot, weil das Modell fehlt.

Damit ist die Definition of Done kein Versprechen mehr, sondern eine Zahl — und keine Agentenarbeit kann durchrutschen, ohne dass es auffällt. Ein Test, der auch ohne Filter grün wäre, prüft nichts; dieser Fehler fällt bei rot geschriebenen Tests sofort auf und bei nachträglich geschriebenen fast nie.

## Stand der Erprobung

| Was | Stand |
|---|---|
| Inhalt der Phase-2-Definitionen | `aufraeumer` einmal durchlaufen und danach überarbeitet. Übrige ungetestet. |
| Inhalt der Fachabteilungen | **Ungetestet.** Angelegt in E2.72 aus den Befunden von E2.40 bis E2.71; der Bestand wurde dafür nachgemessen, die Rollen sind aber noch nicht im Einsatz gewesen. |
| Mechanismus (Aufruf als Subagent) | **Geprüft, greift.** Alle zwölf laden. Die `tools:`-Zeile von `javris` war dabei kaputt — gemessen, siehe unten. |

### Nachgemessen am 20.09.2026, Claude Code im Browser (Remote-Sitzung)

**Sie laden — aber nicht sofort.** Der erste Aufruf von `javris` scheiterte:

```
Agent type 'javris' not found. Available agents: claude, claude-code-guide,
Explore, general-purpose, Plan, statusline-setup
```

Darin fehlten alle zwölf, auch die fünf aus Phase 2. Ein paar Schritte später
standen alle zwölf zur Verfügung. Die Skills waren sofort da, die Agenten
kamen verzögert nach.

**Daraus folgt eine Prüfregel:** Ein einzelner fehlgeschlagener Aufruf belegt
nicht, dass die Definitionen nicht geladen werden — er belegt, dass sie in
diesem Moment noch nicht geladen waren. Wer daraus «geht nicht» schliesst,
hat zu früh gemessen. (Genau das ist hier passiert und stand eine
Commit-Fassung lang falsch in dieser Datei.)

### Und dann der eigentliche Befund

`javris` wurde mit seiner damaligen Frontmatter geladen:

```
tools: Read, Grep, Glob, Bash, Task, TodoWrite
```

Auf die Frage nach seiner tatsächlichen Werkzeugliste antwortete er:

> `Read`, `Grep`, `Glob`, `Bash` — **KEIN DELEGATIONSWERKZEUG.**
> `Task`: Nein. `TodoWrite`: Nein.

**Beide ungültigen Namen fielen ersatzlos weg, ohne eine einzige Meldung.**
Der Chef war geladen, sah vollständig aus und konnte nichts verteilen — die
einzige Aufgabe, die er hat. Kein Werkzeug zeigt das an; es sieht aus wie ein
langsamer Chef, der alles selbst macht.

Deshalb trägt `javris.md` jetzt **keine** `tools:`-Zeile mehr: Ohne sie erbt
der Subagent die Werkzeuge der Sitzung, und das gilt auch dann noch, wenn das
Delegationswerkzeug eines Tages anders heisst. Die Begründung steht in der
Datei selbst.

**Offen:** Dass die Streichung wirkt, ist hier *nicht* mehr nachgemessen — die
Definitionen waren zum Zeitpunkt des Versuchs bereits in ihrer alten Fassung
geladen. Beim nächsten Sitzungsstart denselben Diagnoselauf fahren: *«Zähle
deine Werkzeuge auf. Hast du eines zum Delegieren?»* Steht `Agent` darin, ist
es erledigt.

Das ist keine Nebenbemerkung: Eine Rollenbeschreibung, die niemand lädt, ist ein Dokument und kein Agent. Der Unterschied gehört gewusst, bevor jemand sich darauf verlässt.
