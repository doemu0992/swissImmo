# Mannschaft und Arbeitsteilung

Diese Datei beschreibt, welche Skills und Agenten es gibt, wofür sie zuständig sind und in welcher Reihenfolge sie zum Einsatz kommen. Grundlage ist `docs/ANALYSE.md`.

## Warum diese Aufteilung

Die Phase-2-Arbeit zerfällt in drei Sorten, und nur eine davon skaliert über parallele Arbeit:

- **Kette** — Custom User Model, `Organisation`, FK auf 63 Modelle, `TenantManager`. Jeder Schritt setzt den vorherigen voraus, jeder ist irreversibel-teuer. Eine Hand, sorgfältiges Review. Mehr Parallelität macht das schlechter.
- **Masse** — `fw.py` zerlegen, Tests aufteilen, Migrationen je App, später die Übersetzung. Repetitiv, mechanisch, überprüfbar. Hier zahlt sich Arbeitsteilung aus.
- **Urteil** — Abo-Stufen, Zahlungsanbieter, Oberflächenstrategie. Wird nicht delegiert.

Dass Agenten auf dieser Codebasis überhaupt tragen, liegt an den rund 1'070 Tests und der CI. Ohne diese Rückkopplung produzieren sie auf 68'000 Zeilen plausibel aussehenden Unsinn. Mit ihr haben sie eine harte Abnahme.

## Skills

Regeln, die über Sitzungen hinweg gelten. Werden von den Agenten gelesen.

| Skill | Inhalt | Wann |
|---|---|---|
| `mandantentrennung` | Die Invariante: wie Modelle, Queries, Views, Dateien, Jobs, Exporte und Logs den Bezug herstellen | Immer, wenn eines davon angefasst wird |
| `swissimmo-review` | Definition of Done, Prüfbefehle, wie die Testsuite in dieser Umgebung durchläuft | Vor jedem Commit und PR |
| `phase-2-migration` | Drei Rezepte für die Modellgruppen A, B und C | Bei jeder Migration für Mandantenfähigkeit |
| `schweizer-fachlogik` | Wo Recht und Zahlungsstandards fest verdrahtet sind | Bei Mietrecht, Fristen, QR, MWST, Nebenkosten, Formularen |

## Agenten

| Agent | Auftrag | Abnahme |
|---|---|---|
| `aufraeumer` | P0-Liste: tote Importe, ungenutzte Pakete, Ruff | Tests grün, im Diff nur Löschungen |
| `zerleger` | `fw.py` → 34 Module, `core/tests.py` aufteilen | URLs auflösbar, Tests grün, Zeilenbilanz geht auf |
| `chirurg` | Die Kette: User Model, Organisation, TenantManager, Rollen | Ein Schritt pro PR, jeder von Hand gelesen |
| `migrations-handwerker` | Organisationsbezug je App nachrüsten | `makemigrations --check` leer, Rückwärtsmigration läuft |
| `mandanten-auditor` | Gegnerische Diff-Prüfung | Findet absichtlich eingebaute Lecks |

Der `mandanten-auditor` ist die wichtigste Rolle. Das Hauptrisiko ist nicht, dass ein Agent keinen Mandantenfilter schreibt — sondern dass er einen schreibt, der überzeugend aussieht und nicht isoliert.

## Reihenfolge

```
P0   aufraeumer          Aufräumen, Ruff, Mandant → Eigentuemer
     zerleger            fw.py und core/tests.py aufteilen
     ↓
     Isolationstests schreiben — rot, bevor Organisation existiert
     ↓
P1   chirurg             1. Custom User Model
                         2. Organisation
                         3. TenantManager
                         4. Rollen je Organisation
     ↓
     migrations-handwerker   je App den Bezug nachrüsten
     ↓
     mandanten-auditor       auf jeden Diff, bis die roten Tests grün sind
```

## Isolationstests zuerst

Der Vorschlag mit der grössten Wirkung: die rund 150 Isolationstests **schreiben, bevor `Organisation` existiert**. Sie sind dann alle rot, weil das Modell fehlt.

Damit ist die Definition of Done kein Versprechen mehr, sondern eine Zahl — und keine Agentenarbeit kann durchrutschen, ohne dass es auffällt. Ein Test, der auch ohne Filter grün wäre, prüft nichts; dieser Fehler fällt bei rot geschriebenen Tests sofort auf und bei nachträglich geschriebenen fast nie.

## Was Agenten nicht entscheiden

Diese Fragen werden vorgelegt, nicht beantwortet:

- Ob ein Stammdatenmodell je Organisation gehört oder echte Referenzdatei ist
- Was mit Bestandsdatensätzen ohne Bezug geschieht
- Zuschnitt der Abo-Stufen und Module
- Neue Abhängigkeiten, externe Dienste, alles mit Kosten oder Datenabfluss
- Jede unklare Fachregel im Schweizer Recht

Im Zweifel anhalten und fragen. Eine fehlende Funktion ist ein bekanntes Problem, eine falsch geratene Frist ein unbekanntes.
