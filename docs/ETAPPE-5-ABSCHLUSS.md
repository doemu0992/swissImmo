# Etappe 5, Abschluss — die letzten 16 Modelle

**Stand:** 16.08.2026 · Waisenzahlen gegen den Produktivbestand erhoben
**Grundlage:** `docs/PHASE-2-PLAN.md` (Etappe 5), Skill `phase-2-migration`
**Basis:** `main`
**Agent:** `migrations-handwerker`

---

## Stand

48 von 64 Modellen tragen den Organisationsbezug. **16 sind offen** — es sind genau die, bei denen der Weg nicht aus der Kette folgt.

Zwei Modelle bekommen bewusst **keinen** Bezug:

- `crm.Organisation` — sie *ist* der Anker.
- `benutzer.Benutzer` — per Entscheid vom 15.08.: Die Zuordnung läuft über `crm.Mitgliedschaft`, damit eine Person für mehrere Verwaltungen arbeiten kann.

---

## Die Waisenzahlen, gemessen

Erhoben am 16.08.2026 gegen die Produktionsdatenbank, rein lesend. **Es gibt genau eine Organisation** — die Zuordnung ist damit eindeutig.

| Modell | gesamt | ohne Bezug |
|---|---:|---:|
| `rentals.Dokument` | 7 | 0 |
| `finance.Mahnung` | 1 | 0 |
| `finance.DebitorenRechnung` | 3 | **1** |
| `finance.Zahlungseingang` | 14 | **14** |
| `KreditorenRechnung`, `KreditorPosition`, `KreditorenZahlung`, `EigentuemerAuszahlung` | 0 | 0 |

### `Zahlungseingang`: 14 von 14 — und das ist kein Defekt

Alle vierzehn tragen `Bank-CSV UNGEKLÄRT`, eine `camt:`-Referenz und `konto=86`. Es sind Zahlungen aus dem Bankabgleich, die nicht automatisch zugeordnet werden konnten — verteilt über elf Monate, September 2025 bis Juli 2026, dreizehn davon vom selben Zahler.

**Der unzugeordnete Zustand ist ein regulärer Arbeitszustand, kein Altlastenproblem.** Dass `status` nur `verbucht` und `storniert` kennt, täuscht: Die Kennzeichnung steht im Bemerkungsfeld, nicht im Status.

Daraus folgt der wichtigste Entscheid dieses Auftrags — siehe unten.

### `DebitorenRechnung`: die eine Waise

Nr. 35, „Sonnerie-Beschriftung", CHF 20, **storniert**. Der Ausgangsorganisation zuordnen, **nicht löschen**: Ein Storno ist Teil der Buchhaltung, nicht deren Abfall.

---

## Die Entscheide

Alle getroffen — der `migrations-handwerker` muss hier nichts vorlegen.

| Modell | Entscheid | Begründung |
|---|---|---|
| **`finance.Zahlungseingang`** | **Eigener Fremdschlüssel, beim Import gesetzt** | Der Bezug über Vertrag oder Liegenschaft entsteht später oder nie. Ableiten funktioniert bei diesem Modell prinzipiell nicht. |
| `finance.DebitorenRechnung` | Rezept C, Waise Nr. 35 zuordnen | |
| `finance.Mahnung` | Rezept C | 0 Waisen |
| `rentals.Dokument` | Rezept C | 0 Waisen |
| `KreditorenRechnung`, `KreditorPosition`, `KreditorenZahlung`, `EigentuemerAuszahlung` | Spalte direkt `null=False` | leer — trotzdem in drei Schritten, damit das Muster über alle Apps gleich bleibt |
| `crm.Eigentuemer` | je Organisation | Ein Eigentümer ist Kunde *einer* Verwaltung |
| `crm.Mieter` | je Organisation | Mieterdaten sind das Sensibelste im System. Kein geteilter Bestand. |
| `crm.MieterAdresse` | folgt `Mieter` | reine Historie am Mieter, Pflicht-Fremdschlüssel vorhanden |
| `crm.Handwerker` | je Organisation | Konditionen und Ansprechpartner sind Geschäftsgeheimnis der Verwaltung |
| `crm.Kommunikation` | je Organisation | alle drei Wege (`mieter`, `vertrag`, `liegenschaft`) sind `null=True` — ableiten ist unzuverlässig |
| **`crm.Vorlage`** | **nullbarer Bezug** | `NULL` = mitgelieferte Systemvorlage, gesetzt = eigene. Die einzige begründete Ausnahme von „nie `null=True` als Dauerlösung" — im Modell so kommentieren. |
| `core.Pendenz` | je Organisation | `liegenschaft` und `vertrag` beide `null=True`; vor der Migration Waisen zählen |
| `core.AktivitaetsLog` | eigener Fremdschlüssel | hat als einzigen Weg `benutzer` — und der führt nach dem Entscheid vom 15.08. nirgendwohin |

### `AktivitaetsLog` ist der heikelste Fall

Der Audit-Trail hat genau einen Fremdschlüssel: `benutzer`. Da `Benutzer` bewusst keinen Organisationsbezug trägt, gibt es **keinen** ableitbaren Weg. Er braucht eine eigene Spalte, die beim Schreiben gesetzt wird.

Er wächst laufend, ist rechtlich relevant und lässt sich am schlechtesten nachträglich umschreiben. Nicht ans Ende schieben.

---

## Drei PRs

**PR 7 — `finance` abschliessen** (7 Modelle). Enthält den Sonderfall `Zahlungseingang`.

**PR 8 — `crm` abschliessen** (6 Modelle: `Eigentuemer`, `Mieter`, `MieterAdresse`, `Handwerker`, `Vorlage`, `Kommunikation`).

**PR 9 — `core` und `rentals`** (`AktivitaetsLog`, `Pendenz`, `rentals.Dokument`).

---

## Was in PR 7 dazugehört und leicht vergessen wird

**Der Bankimport muss die Organisation mitschreiben.** Ein Backfill allein genügt nicht: Jede künftige `camt.053`-Zeile braucht die Organisation aus dem Kontoauszug, sonst entstehen am Tag nach der Migration wieder Datensätze, die niemandem zuzuordnen sind — und dann greift `null=False` und der Import bricht.

`Zahlungseingang` wird an fünf Stellen erzeugt: `core/services/zahlungszuordnung.py`, `core/views/fw/bankabgleich.py`, `core/views/fw/detailseiten.py`, `core/views/fw/nebenkosten.py` und `finance/models.py`. **Alle fünf** gehören in denselben PR.

Als Nachkontrolle nach dem Backfill: Gehören Zahlung und `konto` zur selben Organisation? Alle 14 hängen an `konto=86`; sobald `Buchungskonto` seinen Bezug hat, ist das der natürliche Abgleich.

---

## Abnahme je PR

- `makemigrations --check` leer, Vorwärts- **und** Rückwärtsmigration ausgeführt
- Ein Test je Modell: nach der Migration existiert kein Datensatz ohne Organisation
- Datenmigrationen chargenweise über `.iterator(chunk_size=500)`
- Testsuite grün, Testzahl nicht unter **1'119**, Ruff und `check` sauber
- `mandanten-auditor` über den Diff

Nach PR 9: **alle 62 Fachmodelle tragen den Bezug.** Damit ist Etappe 5 abgeschlossen — und erst dann beginnt Etappe 6.

---

## Was ausdrücklich nicht dazugehört

- **Den `TenantManager` anbinden.** Das ist Etappe 6 und braucht zuerst die vier Zeilen ohne Mandantenkontext. Solange er nicht filtert, sind die Spalten Datenhaltung ohne Wirkung — die 13 roten Isolationstests belegen es.
- **Eine zweite Organisation in Produktion anlegen.** Erst nach Etappe 6. Vorher wären zwei Mandanten in derselben Instanz genau der Zustand, den diese Phase verhindern soll.
- **Den Bankabgleich verbessern.** 13 unzugeordnete Zahlungen desselben Zahlers über elf Monate sind ein Arbeitsvorrat, kein Datenfehler — eine `ZahlerZuordnung` für diesen Namen würde die künftigen automatisch treffen. Eigener PR, eigene Entscheidung, nichts für Phase 2.
