---
name: bekannte-fallen
description: Die Fehler, die in diesem Repository schon gemacht wurden, mit Beleg und Gegenmittel — geratene Namen, doppelt vorhandene Formulare, Dekoratoren vor der falschen Definition, Stilregeln ausserhalb ihres Geltungsbereichs, Messungen nur bei Desktop-Breite, Tests die nichts prüfen. Nutze diesen Skill vor jeder Änderung an Code, Vorlagen oder Tests und immer dann, wenn etwas "eigentlich klar" scheint. Auch heranziehen, bevor ein Ergebnis als geprüft gemeldet wird.
---

# Bekannte Fallen

Jeder Eintrag hier ist einmal passiert, in diesem Repository, und hat Zeit gekostet. Die Liste ist kein Stilkatalog — sie ist die Ausfallstatistik.

Wer sie liest, spart nicht Sorgfalt, sondern Wiederholung.

## 1. Namen werden nachgesehen, nie geraten

Häufigster Einzelfehler, neun belegte Wiederholungen: `liegenschaft_set` statt `liegenschaften`, `firma` statt `firma_oder_name`, `--ds-mute` statt `--ds-muted`, `alle_zeilen` statt `reisst`, ein erfundenes Feld `blockiert`, eine erfundene Route `/neu/zulauf/abrufen/`, geratene Testmodulnamen.

Der Reiz ist immer derselbe: Der Name klingt richtig, und Nachsehen kostet dreissig Sekunden. Das Nachsehen kostet dreissig Sekunden. Der geratene Name kostet einen Testlauf, einen Fehlerbericht und eine Nachlieferung.

```bash
# Feldnamen eines Modells
python manage.py shell -c "
from django.apps import apps
for f in apps.get_model('portfolio','Liegenschaft')._meta.get_fields():
    print(f.name)"

# Rückbezüge: wie heisst die Gegenrichtung wirklich
python manage.py shell -c "
from django.apps import apps
m = apps.get_model('crm','Eigentuemer')
print([f.get_accessor_name() for f in m._meta.related_objects])"

# Benannte URLs
python manage.py shell -c "
from django.urls import get_resolver
print(sorted(get_resolver().reverse_dict.keys())[:50])"
```

Bei CSS-Variablen genügt Grep — aber gegen die **Definition**, nicht gegen die Verwendung:

```bash
# Der Doppelpunkt ist der Punkt: Er trennt DEFINITION von Erwähnung.
grep -oE "\-\-ds-[a-z0-9-]+\s*:" core/templates/fw/_schicht.html |
  sed 's/[[:space:]]*:$//' | sort -u
```

Ohne den Doppelpunkt meldet dieser Befehl ausgerechnet `--ds-mute` als vorhanden
— der Name steht genau einmal in `_schicht.html`, in einem Kommentar, der den
Fehler festhält. Eine Prüfung, die den Beleg des Fehlers für den Beweis seiner
Richtigkeit nimmt, ist schlimmer als keine.

## 2. Gibt es die Sache zweimal?

`/schaden/melden/` wurde korrigiert und blieb falsch, weil das Schadenformular **zweimal** existiert: einmal unter `/report/<id>/`, einmal als eigene Vorlage `core/templates/core/schaden_melden.html`. Korrigiert war nur eine.

Denselben Befund gab es bei `dashboard_stats.html` — zwei Fassungen derselben Vorlage in zwei Verzeichnissen, 150 und 212 Zeilen, eine davon unerreichbar.

**Nach jeder Korrektur suchen, ob es die Sache noch einmal gibt.** Nicht nach dem
Dateinamen — nach dem, was die Vorlage ausliefert.

Am schnellsten über die Ansicht, die sie rendert: Beide Schadenformulare hängen
bis heute an **einem** Modul, und das sieht man in einer Zeile.

```bash
grep -rn "render(request, 'core/" core/views/ticket_public.py
# → schaden_melden.html (3×) UND public_ticket_form.html (2×)
```

Ein Textstück tut es auch — aber nur eines, das wirklich drinsteht:

```bash
grep -rln "Anliegen" --include=*.html core/templates/core/
```

## 2b. Derselbe Klassenname für zwei verschiedene Dinge

`fw-akte-pfad` heisst BEIDES: die Brotkrume über dem Aktenkopf (`<nav>`) und
der Schlüssel-Wert-Block IM Aktenkopf (`<div>`). Auf jeder der fünf Akten
stehen beide — acht Vorkommen je Bauform im Bestand.

Folge beim Messen: `querySelector('.fw-akte-pfad')` liefert die Brotkrume.
Wer die Höhe des Schlüssel-Wert-Blocks misst, bekommt 19 Pixel statt 190 und
schliesst daraus, seine Änderung habe nichts bewirkt. Genau so passiert, beim
Nachmessen des Vertrags-Aktenkopfs.

**Beim Messen den Vorfahren mitnennen**, nicht den Namen allein:

```javascript
document.querySelector('.fw-aktenkopf .fw-akte-pfad')   // der Block
document.querySelector('nav.fw-akte-pfad')              // die Brotkrume
```

Die Kollision ist nicht behoben — ein Umbenennen fasst acht Vorlagen und die
Stilschicht an. Hier steht sie, damit die nächste Messung nicht wieder daneben
greift.

## 2c. `objects.create` ist nicht die einzige Art, etwas anzulegen

Belegt beim Nachmessen für Phase 3, und der Befund landete bereits in einem
Dokument, bevor er auffiel: «Keine Stelle legt eine `Mitgliedschaft` an» —
gesucht worden war `Mitgliedschaft.objects.create`. Die echte Stelle benutzt
`update_or_create` und stand die ganze Zeit in `core/views/fw/benutzer.py`.

Ein zu enger Grep beweist nicht die Abwesenheit einer Sache, sondern die
Abwesenheit einer Schreibweise. Beim Ergebnis «gibt es nicht» ist das der
teuerste Irrtum: Er wird geglaubt, weil er wie eine Messung aussieht.

**Alle Formen auf einmal:**

```bash
grep -rnE "Modell(\.objects)?\.(create|get_or_create|update_or_create|bulk_create)\(" \
  --include=*.py . | grep -v "tests/\|test_\|migrations"
```

Dazu kommen Wege ohne diese Namen: ein `ModelForm` mit `.save()`, ein
`instance.save()` auf einem frisch gebauten Objekt, `loaddata`, und
`bulk_create` in einer Schleife.

**Die Gegenprobe zur Abwesenheit** ist nicht ein zweiter Grep, sondern der
Versuch: Wenn wirklich nichts anlegt, dann muss die Tabelle im Betrieb leer
bleiben — und wenn sie es nicht tut, war der Grep zu eng.

## 3. Ein Dekorator bindet an die nächste Definition

Zweimal passiert, in `core/views/fw/arbeit.py` und `core/views/fw/liegenschaft_crud.py`: eine Hilfsfunktion **zwischen** Dekorator und Ansicht eingefügt. Python bindet den Dekorator dann an die Hilfsfunktion.

Die Meldung führt in die Irre. Sie lautete `_benutzer_auswahl() missing 1 required positional argument: 'request'` — für eine Funktion, die gar kein Argument nimmt. Geklärt hat es erst `f.__code__.co_filename`.

**Vor jedem Einfügen die drei Zeilen darüber lesen.** Endet eine davon auf `)` eines Dekorators, gehört der Einschub woanders hin.

## 4. Eine Begründung ist nicht übertragbar, nur weil sie überzeugt

Der schwerste Fehler dieser Reihe, und er war ein Sicherheitsfehler.

In den Code geschrieben stand: „`Benutzer.objects` läuft durch den `TenantManager`." Das stimmt nicht. `benutzer.Benutzer` erbt von `AbstractUser` und trägt **keinen** Mandantenfilter; die Zugehörigkeit läuft über `crm.Mitgliedschaft`. Folge: Ein Fall liess sich einer fremden Verwaltung zuweisen, und die Auswahlliste zeigte alle Benutzer der Datenbank.

Die Begründung war nicht erfunden — sie stammte aus einer anderen Etappe, wo sie richtig ist. Sie wurde mitgenommen, weil sie plausibel klang.

**Gegenmittel:** Jede Aussage über einen Manager, einen Filter oder eine Grenze wird an der Modelldefinition belegt, nicht aus dem Gedächtnis übernommen.

```bash
python manage.py shell -c "
from benutzer.models import Benutzer
print(type(Benutzer._default_manager))"
```

Wer eine Personenauswahl baut, filtert über die Mitgliedschaft:

```python
from crm.models import Mitgliedschaft
Mitgliedschaft.objects.filter(organisation=request.organisation)
```

## 5. Stilregeln gelten nur in ihrem Geltungsbereich

Die Rendite-Karte blieb falsch, obwohl die Klassen stimmten: `fw-l`, `fw-w` und `fw-f` sind in `_schicht.html` **innerhalb** von `.fw-kpi`, `.fw-kzn` und `.fw-lage` definiert. In einer `fw-card` greift keine dieser Regeln.

**Vor dem Verwenden einer Klasse nachsehen, unter welchem Vorfahren sie steht.**

```bash
grep -n "fw-l\b" core/templates/fw/_schicht.html
```

Dazu gehört: `_schicht.html` ist die **Quelle**. Ausgeliefert wird `static/css/schicht.css`, gebaut von `python manage.py schicht_bauen`. Wer die Quelle ändert und nicht baut, ändert nichts — `test_schicht_gebaut` meldet es.

## 6. Bei 390 Pixel messen, nicht nur bei 1280

Eine ganze Etappe wurde bei Desktop-Breite geprüft und war am Telefon unbrauchbar: die Reiterzeile 130 Pixel hoch in drei Reihen, eine Vorratszeile 185 Pixel, der Farbmarker allein über leerem Grund.

Dominik arbeitet am Telefon. **390 × 844 ist die Prüfbreite, 1280 die Zugabe.**

Und: Zahlen, die nur im Browser stimmen, werden im Browser geprüft. Ein Entwurf zog `calc(100% - 11px)` ab, wo der `gap` 12 Pixel beträgt — ein Pixel zu wenig, die Zeile brach weiter um. Kein Quelltextleser findet das; `e2e/tests/telefon.spec.ts` misst es.

## 7. Django rendert auf dem Server, Alpine im Browser

`{% zeichen_wert r.z %}` ergab eine leere Zeichenkette, weil `r` erst im Browser durch Alpine entsteht. Für Werte, die zur Laufzeit im Browser stehen, gehört das Attribut gebunden:

```html
<use :href="'#z-' + r.z"></use>
```

## 8. Mehrzeilige `{# … #}` sind keine Kommentare

Djangos Lexer arbeitet ohne `re.DOTALL`. Ein `{# … #}`, das über zwei Zeilen geht, steht **wörtlich auf der Seite**. Zweimal passiert. Wächter: `faelle/test_template_struktur.py` und `core/tests/test_kein_kommentar_sichtbar.py`.

Mehrzeilig kommentiert wird mit `{% comment %} … {% endcomment %}`.

## 9. Stille Fehler melden sich nicht

Drei Muster, die kein Werkzeug anzeigt:

- Ein Wert, den die Vorlage nie prüft: `delta_gut_wenn = 'tief'`, während die Vorlage auf `'runter'` testet. Ergebnis: falscher Pfeil, keine Meldung.
- Eine undefinierte CSS-Variable: Die Deklaration wird ungültig und fällt weg — mit `!important` schlägt sie die Regel darunter trotzdem. Wächter: `core/tests/test_ds_tokens.py`.
- Ein `{% if %}` auf ein Feld, das es nicht gibt: Django liefert leer und schweigt.

**Gegenmittel:** Jeder neue Wert, den eine Vorlage auswertet, bekommt entweder einen Test oder eine Aufzählung im Python-Code, die falsche Werte ablehnt.

## 10. Eigenschaften in Schleifen erzeugen N+1

`Fall.fortschritt` in einer Schleife über zwölf Zeilen: 28 Abfragen statt 4. Ersetzt durch eine Annotation:

```python
.annotate(_gesamt=Count('fall__schritte', distinct=True))
```

Wer eine Liste baut, zählt die Abfragen — einmal, mit `assertNumQueries`.

## 11. `assertNumQueries` prüft Gleichheit

Nicht Obergrenze. Ein Entwurf schrieb 12 „als Reserve" und war rot, obwohl nichts kaputt war. Die tatsächliche Zahl eintragen — sie ist die Aussage des Tests.

Und: **nur einen** Zähler je Stelle. Ein zweiter neben einem bestehenden misst denselben Aufruf doppelt.

## 12. Ein Test ohne Gegenprobe beweist nichts

Belegte Fehlschläge dieser Art:

- Ein Wächter las seine Prüfliste über dieselbe verengte Funktion, gegen die er prüfte — grün, obwohl drei Zeichen fehlten.
- Ein E2E-Test besuchte nur eines von zwei Formularen; die Gegenprobe blieb grün, weil das zweite gar nicht aufgerufen wurde.
- Ein Fixture legte Fälle **ohne** zuständige Person an; `select_related('fall__zustaendig')` war damit unbelegt.
- Ein Test suchte das Wort „Inbox", das nur in einem Vorlagenkommentar stand, und war 23 Etappen lang grün.

**Pflicht:** Nach dem Schreiben den Fehler einbauen, den der Test finden soll, und nachsehen, dass er rot wird. Danach zurückbauen. Ein Test, dessen Fehlerfall sich nicht herstellen lässt, wird gestrichen oder umgeschrieben.

## 13. Protokollzeilen sind keine Fehlschläge

`RuntimeError: Abwesenheiten nicht ladbar` im Testlauf ist die **Ausgabe** des Ausfalltests, nicht sein Ergebnis. Darunter steht `OK`. Mehrfach verwechselt und als Fehler gemeldet.

Vor jeder Meldung die letzte Zeile lesen, nicht die auffälligste.

## 14. Patches werden gegen den aktuellen Stand gebaut

Ein Patch enthielt eine frühere Etappe „zur Sicherheit" mit. Sobald diese eingespielt war, schlugen 13 Blöcke fehl.

Ein Patch enthält genau seine eigene Etappe, und er wird gegen den Stand gebaut, auf den er trifft.

## 15. `None` heisst nicht erfasst, `0` heisst gemessen

Belegt bei `Geraet.neuwert`, beim Stundensatz und beim Vormonatswert. Ein Nullwert in einer Kennzahl, der aus einer Lücke stammt, behauptet etwas Falsches. Die Kachel schweigt dann lieber, oder sie nennt ihre Datenbasis.

## 16. Kürzer ist nicht richtig

Beim Neuschreiben einer Objektliste ging **Secomat** verloren — er stand seit jeher in der Waschküche. Die Liste war aus dem Kopf gefüllt statt aus dem Bestand.

Wer eine Aufzählung ersetzt, vergleicht alt gegen neu, Zeile für Zeile, bevor er die alte löscht.
