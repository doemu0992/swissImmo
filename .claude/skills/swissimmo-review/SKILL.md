---
name: swissimmo-review
description: Die Definition of Done für swissImmo als ausführbare Checkliste — welche Prüfungen vor jedem PR laufen müssen, wie die Testsuite in dieser Umgebung überhaupt durchläuft, und woran ein PR scheitert. Nutze diesen Skill vor jedem Commit und PR, beim Review fremder Änderungen, und immer wenn behauptet werden soll, etwas sei fertig, grün oder geprüft. Auch heranziehen, wenn nur die Testsuite gestartet werden soll.
---

# Review und Definition of Done

Ein PR ist fertig, wenn alle sechs Punkte belegt sind — nicht behauptet, belegt. „Belegt" heisst: der Befehl wurde ausgeführt und seine Ausgabe steht im PR.

## Die sechs Punkte

1. **Tests grün** — vollständige Suite, nicht nur die berührten Tests
2. **Mandantentrennung geprüft** — mindestens ein Test, der die Grenze aktiv verletzt und fehlschlägt
3. **Keine neuen Linter-Fehler**
4. **Migrationen konsistent** — `makemigrations --check` meldet nichts
5. **Dokumentation nachgeführt** — bei Architekturänderungen `docs/ANALYSE.md`, bei Funktionen das Handbuch
6. **PR beschreibt, was *nicht* getan wurde** — bewusst offen Gelassenes gehört in die Beschreibung, nicht in den nächsten Überraschungsmoment

## Prüfbefehle

```bash
export DEBUG=False SECURE_SSL_REDIRECT=False
python manage.py check
python manage.py makemigrations --check --dry-run
ruff check .
```

### Die Testsuite braucht eine Vorbemerkung

Rund 1'070 Tests, etwa zehn Minuten. In Umgebungen mit Laufzeitlimit pro Befehl bricht ein Durchlauf am Stück ab, **ohne** eine Fehlermeldung zu hinterlassen — das Log endet einfach mitten im Punktemuster. Das ist kein Testfehler, sondern ein abgeschnittener Prozess. Wer das verwechselt, meldet grün, wo nichts gelaufen ist.

Sicherer Weg: in Blöcken fahren.

```bash
# Testklassen aus core/tests.py in fünf Blöcke teilen
grep -oE "^class [A-Za-z0-9_]+" core/tests.py | awk '{print $2}' > /tmp/classes.txt
split -n l/5 -d /tmp/classes.txt /tmp/chunk_

for f in /tmp/chunk_0*; do
  L=$(sed 's/^/core.tests./' "$f" | tr '\n' ' ')
  python manage.py test $L --parallel 8 --verbosity=0
done
python manage.py test crm portfolio rentals finance tickets mietprozess --parallel 8
```

Die Summe der `Ran N tests`-Zeilen gehört in den PR. Erwartungswert derzeit: **1'068**. Weicht die Zahl nach unten ab, wurden Tests übersprungen oder ein Block ist nicht gelaufen.

### Zwei Fallen beim Testlauf

**`--parallel` verschluckt Fehlermeldungen.** Schlägt ein Test fehl, meldet der Multiprocessing-Pool `TypeError: cannot pickle 'traceback' object` und die eigentliche Ursache ist weg. Wenn das auftritt: den betroffenen Block ohne `--parallel` wiederholen, dann steht die echte Meldung da.

**Unvollständig installierte Abhängigkeiten sehen aus wie Fachfehler.** Fehlt etwa `zxing-cpp`, schlägt ein QR-Test mit `'leer' != 'qr'` fehl — was nach kaputter Fachlogik aussieht und keine ist. Vor der Fehlersuche immer `pip install -r requirements.txt` gegenprüfen.

## Was einen PR scheitern lässt

| Befund | Warum |
|---|---|
| Query ohne Organisationsbezug | siehe Skill `mandantentrennung` |
| Isolationstest, der auch ohne Filter grün bliebe | prüft nichts |
| `except Exception: pass` ohne Protokollierung | im Betrieb nicht erkennbar, ob die Operation gelang |
| Neue Abhängigkeit ohne Freigabe | Projektregel, siehe unten |
| Zwei unabhängige Änderungen in einem PR | nicht reviewbar, nicht einzeln zurückrollbar |
| Zeilenzahl gewachsen bei einem reinen Umzug | dann war es kein Umzug |
| Fachlogik „bei der Gelegenheit" mitgeändert | gehört in einen eigenen PR |

## Freigabepflichtig — beschreiben, nicht umsetzen

Ohne ausdrückliche Zustimmung nicht einbauen, sondern im PR als Vorschlag beschreiben:

- neue Python-/JS-Abhängigkeiten
- Plugins, MCP-Connectors, externe Dienste
- alles mit laufenden Kosten
- alles, wo Kunden- oder Mieterdaten das System verlassen

Der letzte Punkt ist der wichtigste und wird am ehesten übersehen: Eine praktische Bibliothek, die im Hintergrund eine API aufruft, ist ein Datenabfluss, auch wenn sie sich wie eine lokale Funktion anfühlt.

## PR-Beschreibung

Knapp, aber vollständig:

```markdown
## Was
Ein Absatz. Was ändert sich fachlich?

## Warum
Der Anlass. Bei Bezug zur Analyse: die TS-/P-Nummer nennen.

## Prüfungen
- check: ohne Beanstandung
- makemigrations --check: keine Änderungen
- ruff: sauber
- Tests: 1'068 grün (Blöcke: 186/213/182/269/213/5)
- Isolationstests: N neu, gegengeprüft (Filter entfernt → rot)

## Bewusst nicht getan
Was liegen bleibt und warum.

## Freigabe nötig
Nur falls zutreffend.
```
