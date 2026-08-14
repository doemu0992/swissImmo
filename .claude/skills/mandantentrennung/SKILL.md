---
name: mandantentrennung
description: Die verbindlichen Regeln, wie in swissImmo Mandantentrennung hergestellt und geprüft wird — Modelle, Queries, Views, Dateiablage, Hintergrundjobs, Exporte, Logs. Nutze diesen Skill immer, wenn ein Modell, eine Query, ein View, eine Migration, ein Management-Command, ein Upload-Pfad oder ein PDF-/E-Mail-Versand angefasst wird, auch wenn Mandantenfähigkeit im Auftrag gar nicht erwähnt ist. Auch bei Code-Reviews und beim Schreiben von Tests heranziehen. Im Zweifel gilt: lieber einmal zu viel konsultiert.
---

# Mandantentrennung in swissImmo

Mehrere Verwaltungen nutzen dieselbe Instanz und dürfen **nie** Daten anderer Mandanten sehen. Diese Eigenschaft ist nicht das Ergebnis sorgfältiger Einzelfallprüfung in jeder View — sie wird zentral erzwungen. Jede Stelle, die das umgeht, ist ein Fehler, auch wenn sie funktioniert.

## Begriffe — hier passieren die meisten Fehler

Der Code enthält eine historische Namenskollision. Beim Lesen und Schreiben immer explizit sein:

| Begriff | Bedeutung im Code | Achtung |
|---|---|---|
| **`Organisation`** | Der Mandant im SaaS-Sinn: ein Verwaltungsunternehmen, ein Abo | Der Tenant-Anker. Neu ab Phase 2. |
| **`crm.Verwaltung`** | Historisch der Singleton der einen Verwaltung | Wird von `Organisation` abgelöst bzw. darin überführt |
| **`crm.Mandant`** | **Der Eigentümer einer Liegenschaft** — *nicht* der Tenant | Umbenennung nach `Eigentuemer` ist beschlossen. Bis dahin: nie unqualifiziert „Mandant" schreiben. |

Wenn in einem Auftrag „Mandant" steht, zuerst klären, welche Bedeutung gemeint ist. Falsch geraten heisst hier: Daten des falschen Kreises freigegeben.

## Die fünf Regeln

### 1. Jedes Fachdatenmodell trägt den Bezug

Kein Modell mit Fachdaten ohne Weg zur `Organisation`. Bei Modellen, die über eine **Pflicht**-Kette an der `Liegenschaft` hängen, genügt diese Kette; bei allen anderen kommt eine eigene `organisation`-Spalte dazu.

`null=True` als Dauerlösung ist keine Option. Ein Datensatz ohne Organisation ist ein Datensatz, den niemand besitzt und den folglich jeder sehen kann. Wenn während einer Migration vorübergehend `null=True` nötig ist, gehört im selben PR die Datenmigration und das Umstellen auf `null=False` dazu.

Neue Modelle: Bezug von Anfang an. Ein nachträglich ergänzter Fremdschlüssel kostet eine Datenmigration über den Produktivbestand.

### 2. Isolation wird zentral erzwungen, nie pro View

Der Default-Manager filtert auf die Organisation aus dem Request-Kontext. Eine View, die selbst filtert, ist ein Symptom — sie bedeutet, dass jemand den Manager umgangen hat oder ihm nicht traut.

Verboten, ausser mit Kommentar und begründetem Einzelfall:

- `Model._base_manager`, `Model.objects.all()` in Verbindung mit einem bewusst ungefilterten Manager
- `.using()` auf eine andere Verbindung
- rohes SQL über `raw()` oder `connection.cursor()`
- `get_object_or_404(Model, pk=...)` ohne Organisationsbezug — IDs sind fortlaufend und damit ratbar

Berechtigte Ausnahmen gibt es: Systemläufe, die absichtlich über alle Organisationen iterieren, und der Login-Vorgang selbst. Diese tragen einen Kommentar, der erklärt **warum**, und laufen über einen ausdrücklich benannten Weg (z. B. `Model.alle_organisationen`), nicht über eine stille Umgehung.

### 3. Der Einstiegspunkt der Oberfläche ist kein Ersatz für die Isolation

`_global_filter()` in `core/views/fw.py` liest die aktive Liegenschaft aus `?lg=` und ist der Einstieg jeder `/neu/`-View. Diese Funktion muss den Besitz prüfen — aber sie ist die **Bequemlichkeit**, nicht die Sicherheit. Auch wenn sie perfekt prüft, muss der Manager unabhängig davon filtern. Zwei Schichten, weil die obere irgendwann jemand umgeht.

### 4. Alles, was den Prozess verlässt, trägt den Bezug

| Bereich | Regel |
|---|---|
| **Dateiablage** | Pfad beginnt mit `organisation/<id>/`. Kein gemeinsamer Ordner, auch nicht für „harmlose" Dateien. |
| **Hintergrundjobs** | Iterieren über Organisationen. Ein Command, der global über alle Verträge läuft, verschickt Mahnungen im Namen der falschen Verwaltung. |
| **PDF und E-Mail** | Absender, Logo, Fusszeile, Antwortadresse aus der Organisation des Datensatzes — nie aus einem Singleton-Lookup. |
| **Exporte** | Enthalten nur Daten einer Organisation, auch wenn der Auslöser Superuser ist. |
| **Logs und Audit** | `AktivitaetsLog` trägt die Organisation. Auch strukturierte Logzeilen. |
| **Caches** | Cache-Keys enthalten die Organisations-ID. Ein geteilter Key ist ein Datenleck mit Zeitverzögerung. |

### 5. Unique-Constraints sind mandantenweit, nicht global

Ein global eindeutiges Feld verhindert, dass zwei Verwaltungen dasselbe Konto 4000 oder denselben Lieferanten führen — es ist ein Blocker auf Datenbankebene, nicht nur ein Schönheitsfehler.

Jede `unique=True` auf einem Fachdatenfeld wird zu einer `UniqueConstraint` über `(organisation, feld)`. Bekannte Fälle im Bestand:

`finance.Buchungskonto.nummer`, `finance.NebenkostenLernRegel.suchwort`, `finance.LieferantProfil.name_key`, `finance.Buchung.beleg_nr`, `finance.ZahlerZuordnung.name_norm`, `portfolio.Lebensdauer.kategorie`.

Bei `beleg_nr` zusätzlich beachten: Der Nummernkreis muss **je Organisation** fortlaufend sein, sonst sieht eine Verwaltung an Lücken in ihrer Belegnummerierung, wie viel die andere bucht.

## Prüfen statt annehmen

Eine Isolation, die nur behauptet ist, gilt als nicht vorhanden. Zu jeder Änderung gehört mindestens ein Test, der einen Zugriff über die Mandantengrenze **aktiv versucht** und fehlschlagen muss:

```python
def test_fremde_liegenschaft_nicht_abrufbar(self):
    """Ein Benutzer von Organisation A darf ein Objekt von B nicht sehen —
    und zwar mit 404, nicht 403: ein 403 verrät, dass die ID existiert."""
    self.client.force_login(self.user_a)
    antwort = self.client.get(f'/neu/liegenschaft/{self.lg_von_b.pk}/')
    self.assertEqual(antwort.status_code, 404)
```

Der Test muss **rot werden, wenn man die Isolation entfernt**. Ein Test, der auch ohne Filter grün ist, prüft nichts. Vor dem Commit einmal gegenprobieren: Filter auskommentieren, Test laufen lassen, muss fehlschlagen.

Für jeden dieser Bereiche ein eigener Test: Detailansicht, Liste, Bearbeiten, Löschen, API-Endpunkt, Dateidownload, Export.

## Warum 404 und nicht 403

Bei fremden Datensätzen immer 404. Ein 403 bestätigt die Existenz des Datensatzes und erlaubt, über fortlaufende IDs den Bestand eines Wettbewerbers abzuzählen. `core/views/media_protected.py` macht das bereits richtig und ist als Vorbild lesenswert.

## Wenn etwas nicht sauber zuordenbar ist

Manche Bestandsmodelle haben heute keinen Weg zur Organisation — Stammdaten wie `Handwerker` oder `Buchungskonto`, Querschnittsdaten wie `AktivitaetsLog`. Hier ist eine **fachliche** Entscheidung nötig, keine technische:

- Gehört es **je Organisation**? Dann eigene Spalte, Bestand duplizieren.
- Ist es **echte Referenzdaten** für alle (z. B. eine Lebensdauertabelle nach Branchenstandard)? Dann als solche kennzeichnen, schreibgeschützt, und nur dann global lassen.

Diese Frage nicht selbst entscheiden, sondern vorlegen. Falsch geraten heisst entweder Datenleck oder verlorene Kundendaten.
