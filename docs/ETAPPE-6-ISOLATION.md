# Etappe 6 — Isolation herstellen

**Stand:** 16.08.2026 · nach Abschluss von Etappe 5
**Grundlage:** `docs/PHASE-2-PLAN.md` (Etappe 6, inkl. Schuldentabelle), Skill `mandantentrennung`
**Basis:** `main`
**Agenten:** `chirurg` für 6.1–6.2, `aufraeumer` für 6.3–6.5, `mandanten-auditor` an jedem Gate

---

## Wo wir stehen

63 von 65 Modellen tragen den Organisationsbezug. **Gefiltert wird nichts.** Die 13 Isolationstests sind unverändert rot, weil der `TenantManager` nicht angebunden ist.

Diese Etappe verwandelt Datenhaltung in Isolation. Danach ist Phase 2 fertig.

Die Schuldentabelle in `PHASE-2-PLAN.md` unter Etappe 6 ist die Arbeitsliste — mit Dateien und Zeilennummern. Dieser Auftrag ergänzt sie um **Reihenfolge**, **Abnahme** und eine **Korrektur**.

---

## Korrektur: es sind sieben, nicht vier

Der Plan nennt „`ORGANISATION_RUECKFALL = True` an vier Belegarten" in `finance/models.py`. Programmatisch über die Modell-Registry gezählt sind es **sieben** über vier Apps:

| Modell | Pfad |
|---|---|
| `core.Pendenz` | `vertrag`, `liegenschaft` |
| `crm.Kommunikation` | `mieter`, `vertrag`, `liegenschaft` |
| `rentals.Dokument` | `vertrag`, `einheit`, `liegenschaft`, `mieter`, `eigentuemer` |
| `finance.DebitorenRechnung` | `vertrag`, `einheit`, `liegenschaft`, `konto_haben` |
| `finance.Zahlungseingang` | `vertrag`, `liegenschaft`, `debitoren_rechnung`, `konto` |
| `finance.Mahnung` | `debitoren_rechnung`, `vertrag` |
| `finance.KreditorenRechnung` | `einheit`, `liegenschaft`, `konto` |

Der Prüfstein lautet also: **sieben Rückfälle**, nicht vier. Zählt eine Prüfung nur die `finance`-Modelle, bleiben drei stehen — und ausgerechnet `Pendenz` und `Kommunikation` hängen an Mieterdaten.

Verlässlich zählen lässt sich das nicht per `grep`, sondern über die Registry:

```python
[f'{m._meta.label}' for a in APPS for m in apps.get_app_config(a).get_models()
 if getattr(m, 'ORGANISATION_RUECKFALL', False)]
```

### Woher der Fehler kam, und was daraus folgt

Die Zahl „vier" stimmte, als sie geschrieben wurde: In PR 7 gab es genau die vier `finance`-Belegarten. PR 8 fügte `crm.Kommunikation` hinzu, PR 9 `core.Pendenz` und `rentals.Dokument` — und die Tabelle wurde nicht nachgezogen.

Eine Zahl in einem Dokument veraltet in dem Moment, in dem jemand anderswo etwas hinzufügt. Deshalb steht der Prüfstein jetzt **zusätzlich als Test** (`RueckfallBestandTests` in `core/tests/test_organisation_kette.py`): Er zählt über die Registry und schlägt fehl, sobald ein achter Rückfall entsteht, ohne dass die Tabelle mitwächst. Beim Tilgen in 6.3 zählt er rückwärts und ist am Ende die Abnahme selbst.

---

## Reihenfolge

Die sechs Schulden hängen voneinander ab. Diese Folge löst das auf:

**6.1 — Kontext dort setzen, wo er fehlt.** Öffentliche Endpunkte (Portal-Feed, Webhooks, öffentliche Formulare) holen die Organisation aus dem Token bzw. dem adressierten Objekt. Management-Commands und Services iterieren über Organisationen oder setzen den Kontext ausdrücklich. **Ohne diesen Schritt scheitert alles Weitere** — die gemessenen 140 Fehlschläge kamen genau von hier.

**6.2 — `TenantManager` anbinden.** Erst wenn 6.1 steht. Die beiden bekannten Klippen sind im Code benannt: Rückbezüge erben den Filter (`liegenschaft.einheiten`), und `update_or_create` liest, bevor es schreibt. Dazu die Admin-Umgehung über `_base_manager`.

---

### 6.2 — erledigt (17.08.2026, dritter Anlauf)

**Der Schalter liegt um.** `objects = TenantManager()` an `OrganisationAusKette` — 51 Modelle über eine Zeile. Volle Suite grün. Die ersten beiden Anläufe endeten bei 65 bzw. 922 Fehlschlägen; der dritte begann bei 195 im ersten Block und endete bei null, weil die Ursachen diesmal benannt statt gezählt wurden.

**Vier Dinge mussten stimmen, bevor der Filter tragen konnte:**

| | Befund | Lösung |
|---|---|---|
| 1 | Rückbezüge erben den Filter — jedes `liegenschaft.einheiten.all()` brach ohne Kontext ab | `get_queryset` filtert nicht, wenn `self.instance` gesetzt ist (Djangos Merkmal für Rückbezugs-Manager). Zulässig, weil das Kind seine Organisation seit Etappe 5 aus genau dieser Kette ableitet — der Filter wäre dort tautologisch. Die Grenze sitzt am **Einstieg**. |
| 2 | Die Middleware **löschte** den Kontext im `finally` | Sie **stellt** jetzt den vorgefundenen **wieder her**. Im Betrieb identisch; wo eine Anfrage innerhalb eines bestehenden Kontexts läuft (Test, Systemlauf), war es ein stiller Verlust. |
| 3 | Ein im Test gesetzter Kontext lebte für den ganzen Prozess weiter | `core/test_runner.py`: jeder Test in einer eigenen `contextvars`-Kopie. Ohne das entstünden reihenfolgeabhängige Tests — belegt durch `KontextLebensdauerTests`, das ohne den Läufer fehlschlägt. |
| 4 | `get_or_create` stand in der Ausnahmeliste, `create` zu Recht | Ausnahme entfernt: `create` gibt nichts heraus, `get_or_create` **liest** zuerst und gäbe ohne Filter die Zeile eines fremden Mandanten zurück. |

**Zwei Muster, die `alle_organisationen` bekommen — und warum das keine Aufweichung ist:**

- **Selbstbezogene Zugriffe.** `filter(pk=self.pk).update(...)` in `DebitorenRechnung.save()`, `filter(organisation_id=self.organisation_id)` in `Buchung.save()`, `filter(vertrag=vertrag)` in `ablage.ablegen()`, `filter(beleg_text__startswith=f"…[V{pk}]…")` in der Kautionsbuchung. In all diesen steht die Mandantengrenze bereits **im Ausdruck selbst**. Den Kontext zusätzlich zu verlangen macht nichts sicherer, bricht aber jeden Lauf ausserhalb einer Anfrage ab.
- **Öffentliche Endpunkte.** Bewerbungsformular, Datenschutzseite, Portal-Feed: kein Login, also kein Kontext. Die Grenze zieht dort das adressierte Objekt bzw. der Token — beides in 6.1 hergestellt.

**Der Kontext im Testaufbau** ist keine Abschwächung, sondern eine Korrektur: In der Anwendung hat **jede** Anfrage einen Kontext. `_test_organisation()` setzt ihn jetzt, und der Testläufer räumt ihn zwischen den Tests ab. Wirkung gemessen: `test_buchhaltung` von 49 Fehlern auf 0.

**Erster von dreizehn Isolationstests grün:** `test_ohne_kontext_wirft_der_manager` — `expectedFailure` entfernt, Gegenprobe protokolliert. Die übrigen zwölf gehören zu 6.3–6.5.

**Noch offen in 6.2:** die 12 Modelle mit eigener Organisationsspalte (ohne die abstrakte Basis) — `crm.Eigentuemer`, `crm.Mieter`, `crm.Handwerker`, `portfolio.Liegenschaft`, `finance.Buchungskonto` und weitere. Sie kommen einzeln dazu, weil jedes eine eigene Frage stellt. **`crm.Vorlage` ausdrücklich erst nach 6.4** — sonst verschwinden die Systemvorlagen (`organisation__isnull=True`) aus der Oberfläche, und das sieht wie Datenverlust aus.

---

**6.3 — Die sieben Rückfälle tilgen.** Danach ist `ORGANISATION_RUECKFALL` überflüssig; das Attribut selbst gehört mit entfernt, nicht nur auf `False` gesetzt. Ebenso `organisation_oder_einzige()` samt der fünf direkten `Buchungskonto`-Anlagen.

**6.4 — Die sechs `Vorlage`-Lesezugriffe** auf `Q(organisation=org) | Q(organisation__isnull=True)` umstellen. Sonst verschwinden ab der Filterung die mitgelieferten Systemvorlagen aus der Oberfläche — ein Fehler, der wie ein Datenverlust aussieht.

**6.5 — Alles, was den Prozess verlässt.** Dateiablage auf `organisation/<id>/` mit Migration der Bestandsdateien, PDF- und E-Mail-Absender aus der Organisation des Datensatzes, Cache-Keys mit Organisations-ID, `AktivitaetsLog` beim Schreiben.

---

## Die Gegenprobe — hier wird sie fällig

Bisher waren alle Isolationstests rot, weil `Organisation` fehlte. **Das hat nichts bewiesen:** Ein Test, der am fehlenden Modell scheitert, würde auch scheitern, wenn er gar nichts prüft.

Ab jetzt gilt für **jeden** Test, der grün wird:

1. Filter entfernen oder auskommentieren
2. Test laufen lassen — **er muss rot werden**
3. Filter zurück, Test wieder grün
4. Ergebnis mit Datum ins PR-Protokoll

**Ein Test ohne durchgeführte Gegenprobe gilt als nicht geschrieben.** Das ist die einzige Absicherung dagegen, dass ein Filter entsteht, der überzeugend aussieht und nicht isoliert — das Hauptrisiko der gesamten Phase, und der Grund, warum die Tests vor dem Code geschrieben wurden.

Wie ernst das gemeint ist, hat Etappe 5 dreimal gezeigt: Ein Test blieb grün, weil er `pk__in=[]` prüfte (trivial wahr für jedes Modell). Ein zweiter prüfte nur die Abwesenheit von Wörtern, die auf jeder normalen Seite fehlen. Ein dritter hätte den zu prüfenden Zustand gar nicht mehr herstellen können. Alle drei sahen überzeugend aus.

---

## Abnahme

Je PR: Testsuite grün, Testzahl nicht unter **1'122**, `check`, `makemigrations --check`, Ruff sauber, Vorwärts- und Rückwärtsmigration ausgeführt, `mandanten-auditor` über den Diff.

**Für die Etappe — und damit für Phase 2:**

- Alle **13** Isolationstests grün, jeder mit protokollierter Gegenprobe
- `ORGANISATION_RUECKFALL` existiert nicht mehr — weder als `True` noch als Attribut
- `organisation_oder_einzige()` entfernt
- Kein `Verwaltung.objects.first()`-Muster mehr für Absender in PDF und E-Mail
- Dateiablage unter `organisation/<id>/`, Bestandsdateien migriert
- `mandanten-auditor` findet nichts
- **Erst dann** darf eine zweite Organisation angelegt werden

Der letzte Punkt ist keine Formalie: Solange ein Rückfall existiert, ist er mit einer Organisation harmlos und mit zweien eine stille Fehlzuordnung.

---

## Danach

Phase 2 ist abgeschlossen. Offen aus früheren Etappen und für die Reihenfolge danach:

- **PostgreSQL** (P1.4) — SQLite trägt gleichzeitige Schreibzugriffe mehrerer Mandanten nicht. Vor dem zweiten Mandanten.
- **2FA** — Fairwalter führt es in allen Preisstufen, im Bestand fehlt es (`docs/MARKT.md`).
- **Hosting-Standort** — PythonAnywhere gegen das beworbene Schweizer Hosting der Konkurrenz.
- **Python-Version** — produktiv 3.10.12, Ruff auf `py311`, Konsole 3.13.
- **Phase 3** — Entitlements und die vier Abo-Stufen aus `docs/MARKT.md`.
