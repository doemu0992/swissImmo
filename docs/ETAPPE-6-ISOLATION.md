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

**Auch die 12 Modelle mit eigener Organisationsspalte sind angebunden** (17.08.2026): `Eigentuemer`, `Mieter`, `Handwerker`, `Mitgliedschaft`, `Liegenschaft`, `Lebensdauer`, `Buchungskonto`, `LieferantProfil`, `NebenkostenLernRegel`, `EigentuemerAuszahlung`, `AktivitaetsLog` — und `Vorlage` über den eigenen Manager aus 6.4.

Die volle Suite meldete dabei **zwei** Fehler, beide in Testcode, der absichtlich über Verwaltungsgrenzen prüft. Dass es nach 195 im ersten Anlauf nur noch zwei waren, liegt an der Grundlage: Testläufer, Kontext im Testaufbau und die wiederherstellende Middleware waren zu diesem Zeitpunkt schon da.

**Zwei Modelle stellten eigene Fragen:**

- **`Mitgliedschaft` bestimmt den Kontext** und darf ihn deshalb nicht voraussetzen. Die zwei Stellen, die ihn *herleiten* — die Middleware und der Rückfall in `log_aktion` — nutzen `alle_organisationen`. Alle übrigen Abfragen (Benutzerverwaltung, Rollenprüfung) laufen im Kontext und filtern richtig.
- **`AktivitaetsLog`** hat nichts abzuleiten: Sein einziger Fremdschlüssel ist `benutzer`, und der trägt bewusst keinen Organisationsbezug. Der Bezug muss beim Schreiben gesetzt werden.

**Zwei weitere Isolationstests sind dadurch grün geworden** — beide zum Audit-Trail, beide mit protokollierter Gegenprobe:

| Test | Was er verhindert |
|---|---|
| `test_logbuch_filtert_nicht_auf_fremden_benutzer` | `/neu/logbuch/?benutzer=<fremd>` zeigt fremde Vorgänge |
| `test_csv_export_enthaelt_keine_fremden_daten` | der CSV-Export nimmt den fremden Audit-Trail mit |

Damit stehen **3 von 13** Isolationstests auf grün. Die übrigen zehn gehören zu 6.3 und 6.5.

---

**6.3 — erledigt (17.08.2026).** Die sieben Rückfälle sind getilgt, `ORGANISATION_RUECKFALL` existiert nicht mehr, und `organisation_oder_einzige()` heisst jetzt `organisation_bestimmen()` — ohne den mittleren Schritt.

```
vorher:  Argument → Kontext → die EINZIGE vorhandene Organisation → Fehler
jetzt:   Argument → Kontext → Fehler
```

**Der gestrichene Schritt ratete nicht** — mit mehreren Organisationen brach er ab. Genau darin lag das Problem: Er hielt jeden Pfad am Leben, der ohne Mandantenkontext schrieb, und beim ersten zweiten Mandanten wären sie **alle gleichzeitig** ausgefallen. Solange es eine Organisation gab, sah alles in Ordnung aus.

Tilgen liess er sich erst nach 6.1 und 6.2: Erst dort haben die öffentlichen Endpunkte, die Management-Commands und die Services ihren Kontext bekommen. Die Zahl, die den ersten Versuch gestoppt hatte — 140 Fehlschläge in drei Testmodulen —, war die Rechnung für genau diese fehlende Vorarbeit. Diesmal: **volle Suite grün, kein einziger Fehlschlag.**

**Das Attribut ist weg, nicht auf `False` gesetzt.** Die Regel gilt jetzt für jedes Modell gleich: Trägt die Kette nicht, entscheidet der Kontext; ohne Kontext bricht das Speichern ab. Eine Ausnahmeliste, die pflegen muss, wer ein Modell hinzufügt, gibt es nicht mehr.

**Zwei Tests haben ihre Aufgabe erfüllt und wurden ersetzt:**

- `RueckfallBestandTests` zählte über die Registry, welche Modelle ausweichen — und fand, dass es **sieben** waren, nicht die vier, die das Plandokument nannte. An seiner Stelle steht jetzt ein Wächter, dass das Attribut nicht zurückkommt (ein `grep` genügte dafür nicht, weil es vererbt würde).
- `test_rueckfall_nur_wo_kein_weg_garantiert_ist` prüfte die Verkabelung. An seiner Stelle steht die **Zusicherung selbst**: Ein Modell mit lauter optionalen Wegen, gespeichert ohne jeden Weg und ohne Kontext, muss abbrechen.

**6.4 — erledigt (17.08.2026).** Die Lesezugriffe waren nur die Hälfte.

`crm.Vorlage` ist die einzige begründete Ausnahme von „nie `null=True` als Dauerlösung": NULL bezeichnet die **mitgelieferte Systemvorlage**, die für alle Verwaltungen gilt. Der Plan sah vor, die sechs Lesezugriffe auf `Q(organisation=org) | Q(organisation__isnull=True)` umzustellen. Beim Umsetzen zeigte sich, dass das an sieben Stellen zu wiederholen wäre — und dass die Schreibseite die grösseren Löcher hatte.

**Gelöst über einen eigenen Manager statt über sieben Abfragen.** `VorlagenManager(TenantManager)` überschreibt genau eine Methode (`_einschraenken`) und zeigt eigene *und* mitgelieferte Vorlagen. Alles Übrige — Rückbezüge, Kontextzwang, `create` — erbt er, damit es nur eine Stelle gibt, an der sich das ändern kann. Die sieben Abfragestellen brauchten keine Änderung; an einer davon wäre die Q-Bedingung irgendwann vergessen worden, und dann hätten in einer einzelnen Maske Vorlagen gefehlt.

**Drei Schreibpfade, die die Trennung ausgehebelt hätten:**

| Fund | Folge | Lösung |
|---|---|---|
| Eine im Formular angelegte Vorlage bekam `organisation = NULL` | Jede selbst geschriebene Vorlage war eine **System**vorlage — sichtbar für jede Verwaltung | `Vorlage.save()` setzt beim **Anlegen** die Organisation des Kontexts. Ohne Kontext bleibt NULL — genau so entstehen die mitgelieferten beim Seeden. |
| Eine Systemvorlage liess sich im Bearbeiten-Formular überschreiben | Schreibzugriff über die Mandantengrenze, ausgelöst durch ein gewöhnliches Formular | Kopie statt Überschreiben: Es entsteht eine eigene Fassung, das Original bleibt. |
| Eine Systemvorlage liess sich löschen | Sie fehlte danach **allen** | Abgelehnt, mit Hinweis auf den Bearbeiten-Weg. |

Der erste Fund kam nicht aus dem Code-Lesen, sondern aus dem Fixture: Dessen Vorlage tauchte plötzlich in **beiden** Beständen auf. Deshalb sitzt die Korrektur im Modell und nicht in der View — dort gilt sie für jeden Aufrufer, auch für Code und Tests.

`seed_standard_vorlagen()` nutzt `alle_organisationen`: Die Systemvorlagen sind per Definition kontextlos, und die Vorhandenseins-Prüfung muss sie unabhängig vom Kontext sehen — sonst legte jeder Lauf Duplikate an.

**Gegenprobe durchgeführt:** Mit zurückgebautem Manager, `save()` und Kopier-Regel fallen 5 der 12 Tests.

**6.5 — Dateiablage erledigt (17.08.2026); Absender und Cache-Keys geprüft.**

**Der Befund war nicht das Ordnerlayout, sondern die Zugriffsregel.** `geschuetzte_media` prüfte genau eine Sache: „ist im Team". In **welchem** Team, stand nirgends. Jedes angemeldete Team-Mitglied konnte jede geschützte Datei abrufen, sofern es den Pfad kannte — und die Pfade sind ratbar (Ordner, Datum, Dateiname). Dort liegen Ausweiskopien, Betreibungsauszüge und Lohnausweise von Mietbewerbern, Wohnungsaufnahmen aus Schadenmeldungen, gescannte Verträge.

Zwei Mechanismen schliessen das:

1. **Pfad-Präfix `organisation/<id>/`** bei neuen Uploads — die Zugehörigkeit ohne Datenbankabfrage ablesbar.
2. **Rückgriff auf die Datenbank** für den Alt-Bestand: nachsehen, welcher Datensatz auf die Datei zeigt (dieselbe Technik, die `ist_objektfoto` schon benutzte).

Lässt sich die Zugehörigkeit nicht bestimmen, wird **verweigert** — 404, nicht 403, damit kein Existenz-Leak entsteht.

> **Eine Falle, in die das Präfix beim Einbau selbst geführt hat.** Die Sensibilität wird am *Ordner* abgelesen (`schaden_fotos/`, `dokumente/`). Das Präfix schiebt sich davor — ohne Abziehen begann kein Pfad mehr mit einem sensiblen Ordner, die Prüfung lief ins Leere, und jedes Bild wäre über seine Endung **anonym** abrufbar gewesen. Gefunden vom bestehenden `test_fremder_bekommt_schadenfoto_nicht`, im ersten Lauf nach der Änderung. `ohne_organisationspraefix()` zieht das Präfix jetzt ab, bevor die Ordnerprüfung greift; ein eigener Testsatz hält den Fall fest.

**`medien_umziehen`** zieht den Bestand nach — Trockenlauf ist die Voreinstellung. Auf der Entwicklungsdatenbank: 161 Verweise, 4 übersprungen (Dateien fehlen auf der Platte; gemeldet statt verschwiegen). Der Befehl kopiert erst, setzt dann das Feld, löscht das Original zuletzt — bricht es dazwischen ab, liegt die Datei doppelt: Speicherplatz, kein Datenverlust. Mehrfachverweise auf dieselbe Datei bekommen denselben neuen Pfad, ohne sie erneut zu bewegen.

**Absender in PDF und E-Mail** waren bereits in 6.1 erledigt — sie kommen aus der Organisation des jeweiligen Objekts (Vertrag, Mieter, Liegenschaft, Ticket), nicht aus dem Bestand.

**Cache-Keys:** Es gibt zwei. Der LIK-Cache (`core/services/lik.py`) hält eine **nationale** Zahl des BFS; ein geteilter Key ist dort richtig und kein Leck. Die Ratenbremse (`core/utils/throttle.py`) begrenzt Bewerbungen je IP — sie koppelt heute Verwaltungen aneinander (fünf Bewerbungen bei A sperren die Bewerbung bei B), was mildes Denial-of-Service, aber kein Datenleck ist. Vermerkt, nicht mitkorrigiert.


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
