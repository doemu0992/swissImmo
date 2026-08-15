# Etappe 4 — `Organisation` und `TenantManager`

**Stand:** 15.08.2026 · gemessen an `main` nach Abschluss von Etappe 3
**Grundlage:** `docs/PHASE-2-PLAN.md` (Etappe 4), Skill `mandantentrennung`
**Basis:** `main`
**Agent:** `chirurg`

---

## Das Herzstück

Alles bisher war Vorbereitung: aufräumen, zerlegen, Tests schreiben, Benutzermodell tauschen. Hier entsteht die Mandantentrennung selbst.

Ab dieser Etappe werden die ersten der **11 roten Tests** grün — und ab hier gilt die Gegenprobe aus `docs/ETAPPE-2-ISOLATIONSTESTS.md`: Jeder Test, der grün wird, muss einmal mit entferntem Filter rot geworden sein. Sonst zählt er nicht.

---

## Zwei Entscheide, gefallen am 15.08.2026

Der Auftrag sagte an zwei Stellen Verschiedenes über dasselbe — 4.1 „Ein Benutzer gehört zu genau einer Organisation", 4.3 „Mitgliedschaft je Organisation". Das sind zwei verschiedene Datenmodelle, und der Skill `swissimmo-review` verlangt in so einem Fall anhalten statt selbst auflösen. Beide Fragen sind entschieden:

### Entscheid 1 — Mitgliedschaft, kein Fremdschlüssel am Benutzer

Es entsteht ein eigenes Modell `(Benutzer, Organisation, Rolle)`. **`Benutzer` bekommt keine Spalte `organisation`.**

Damit ist 4.1 in diesem Punkt anders auszuführen, als der Auftrag ihn formuliert: Statt eines Fremdschlüssels entsteht das Mitgliedschaftsmodell, und 4.3 baut nur noch die Rollen darauf aus, statt eine bestehende Struktur zu ersetzen.

Was das trägt: Eine Person, die für zwei Verwaltungen arbeitet, hat **ein** Konto mit **einem** Passwort und je Organisation eine eigene Rolle. Und der Fall, der im Mietrecht real vorkommt — eine Liegenschaft wechselt von Verwaltung A zu B — kostet eine Zeile statt eines Kontowechsels für jeden betroffenen Mieter und Eigentümer.

Was es kostet: Beim Login muss aufgelöst werden, in welcher Organisation jemand gerade arbeitet, sobald er in mehreren ist. Für den heutigen Bestand (alle in einer) ist das ein Vorgriff, kein Aufwand.

Die Ausnahme in `core/tests/test_isolation.py` bleibt damit richtig und wird zur Entscheidung statt zur Notiz:

```python
'benutzer.Benutzer': 'Mitgliedschaft je Organisation statt eigener Spalte — Etappe 4',
```

### Entscheid 2 — `crm.Verwaltung` wird zu `Organisation` (Weg A)

Umbenennung wie `Mandant` → `Eigentuemer` in E3, mit `db_table` unverändert. Die 23 Felder bleiben, wo sie sind; die 79 Fundstellen werden zu `request.organisation`.

**Die bekannte Schwäche, damit sie nicht vergessen wird:** `Organisation` trägt danach Fachdaten (Referenzzins, LIK, MWST-Angaben) neben Mandantendaten (Abo-Plan, Branding, Portal-Token). Das ist eine bewusst in Kauf genommene Vermischung, kein Versehen. Sie lässt sich später auflösen, indem die Fachfelder in ein eigenes Modell wandern — der umgekehrte Weg (zwei Modelle jetzt, jede der 79 Fundstellen einzeln zuordnen) ist der, bei dem Fehler entstehen.

---

## Drei PRs, nacheinander

Anders als Etappe 3 ist das **kein** Ein-PR-Schritt. Die drei Teile sind einzeln lauffähig und einzeln zurückrollbar.

---

## 4.1 — Das Modell `Organisation`

Zuerst die Frage, die alles andere bestimmt: **Was wird aus `crm.Verwaltung`?**

`Verwaltung` ist heute der Singleton mit **23 konkreten Feldern** — Firma, Adresse, IBAN, Logo, Unterschrift, Referenzzins, LIK, MWST-Angaben, Portal-Token und `abo_plan`. Sie wird an **79 Stellen** im Produktivcode über `Verwaltung.objects` gelesen; **76** davon sind wörtlich `.objects.first()`. Mit den Tests sind es 131.

**Entschieden: Weg A** (siehe oben). Was dieser PR enthält:

- `crm.Verwaltung` → `crm.Organisation`, `db_table` unverändert. Migration nach dem Muster von `crm/0029` (E3): `RenameModel` plus die abhängigen `RenameField` in den anderen Apps, in **einer** Migration mit ausdrücklichen `dependencies` über alle betroffenen Apps.
- Das Mitgliedschaftsmodell `(Benutzer, Organisation, Rolle)`. **Kein** Fremdschlüssel am Benutzer.
- Eine Datenmigration, die den bestehenden Bestand der einen vorhandenen Organisation zuweist und für jeden aktiven Benutzer eine Mitgliedschaft anlegt — mit der Rolle, die er heute über seine Django-Gruppe hat.
- **Noch keinen Manager, noch keine Filterung.** Nur die Modelle und die Zuordnung.

Nicht in diesem PR: das Ablösen der Django-Gruppen. `hat_rolle()` liest weiter `user.groups`, die Mitgliedschaft trägt die Rolle zunächst nur mit. Der Umschwung ist 4.3 — sonst hängen Anmeldung, Rollenprüfung und Datenmodell gleichzeitig in der Luft.

### Ausgeführt am 15.08.2026

| | |
|---|---|
| `crm.Verwaltung` → `crm.Organisation` | 276 NAME-Token in 67 Dateien, `db_table` unverändert |
| `Liegenschaft.verwaltung` → `.organisation` | echte Spaltenumbenennung, verlustfrei |
| `crm.Mitgliedschaft` | neu, `(benutzer, organisation)` eindeutig |
| Migrationen | `crm/0032`, `portfolio/0032`, `crm/0033`, `crm/0034` |
| Bestand zugeordnet | 12 von 12 Liegenschaften, 4 Mitgliedschaften |

Die Umbenennung lief **token-genau**, nicht per Textersetzung: Ein `sed` über `Verwaltung` hätte
auch die 209 String-Vorkommen erwischt — darunter den Rollennamen `"Verwaltung"` aus
`core/auth.py`, dessen Änderung die Rollenprüfung der ganzen Anwendung gebrochen hätte. Der
Tokenizer unterscheidet NAME von STRING und COMMENT und fasst nur das Erste an.

**Drei Stellen, die der Tokenizer prinzipbedingt nicht sieht** — und wie jede gefunden wurde:

1. `Verwaltung` **innerhalb eines f-Strings** (`profil.py:881`). Python 3.11 liefert f-Strings als
   ein einziges STRING-Token. Gefunden von **Ruff F821** beim ersten Lauf danach.
2. **Feldnamen in ORM-Strings** — `select_related('verwaltung')` an zwei Stellen, ein
   Admin-Fieldset, eine Feldliste im Test-Fixture. Für Ruff sind das gewöhnliche Zeichenketten;
   gefunden hat sie erst die **Testsuite**.
3. Der Testlauf meldete sie zunächst gar nicht, sondern `TypeError: cannot pickle 'traceback'
   object` — die im Skill `swissimmo-review` beschriebene `--parallel`-Falle. Erst der Lauf **ohne
   `--parallel`** zeigte die echte Meldung.

Das ist dasselbe Muster wie in Etappe 1: Ruff und Testsuite decken verschiedene Fehlerklassen ab,
und keine der beiden ersetzt die andere.

**Wer keine Mitgliedschaft bekommt, und warum.** Portal-Konten (Mieter, Eigentümer) hängen über
`Mieter.benutzer` und `Eigentuemer.benutzer` an ihren Datensätzen — `Eigentümer` ist eine
Portal-Rolle, keine Team-Rolle. Konten ohne Team-Gruppe und ohne Portal-Profil bekommen ebenfalls
keine: Sie haben heute keinen Team-Zugang, und eine Datenmigration ist nicht der Ort, ihnen einen
zu geben.

**Über den Auftrag hinaus:** `Mitgliedschaft` ist im Admin registriert (lesend, wie alles seit E2).
Ein Zugehörigkeitsmodell, das im Betrieb niemand einsehen kann, ist nicht diagnostizierbar.

---

## 4.2 — `TenantManager` und Kontext

Der Kern. Drei Bestandteile:

**Kontextvariable.** Eine Middleware setzt die Organisation aus `request.user`. Zusätzlich ein ausdrücklicher Weg, sie in Management-Commands, Signals und Shell zu setzen.

**Der Manager filtert.** Default-Manager auf der Organisation aus dem Kontext.

**Ohne Kontext gibt es einen Fehler — nicht „alles".** Das ist die wichtigste Zeile dieser Etappe. Ein Manager, der im Zweifel alles zurückgibt, ist schlechter als keiner: Er täuscht Sicherheit vor, und der Fehler fällt erst auf, wenn Daten schon geflossen sind. Ein Test dafür existiert bereits in `ManagerIsolationTests`.

Für Systemläufe, die absichtlich über alle Organisationen gehen, braucht es einen **benannten** Weg — etwa `Model.alle_organisationen` — nicht eine stille Umgehung. Jede Verwendung trägt einen Kommentar, der erklärt, warum.

**`_global_filter` in `core/views/fw/_basis.py`** ist der Einstiegspunkt aller 33 View-Module. Gemessen am Bestand (Zeile 50–68) liest er heute:

```python
lg_id = request.GET.get('lg') or None
if lg_id:
    aktive_lg = Liegenschaft.objects.filter(id=lg_id).first()
...
'alle_liegenschaften': Liegenschaft.objects.all().order_by('strasse'),
```

Keine Besitzprüfung an beiden Stellen — die Isolationstests weisen das bereits nach (`dossier_liegenschaft` liefert 200 statt 404). Er muss die Prüfung bekommen. Aber: **Er ist die Bequemlichkeit, nicht die Sicherheit.** Auch wenn er perfekt prüft, muss der Manager unabhängig davon filtern. Zwei Schichten, weil die obere irgendwann jemand umgeht.

**Der Admin umgeht den Manager** über `_base_manager` und als Superuser. Seit E2 ist er lesend und Superuser-beschränkt, aber `AdminUmgehungTests` weist heute nach, dass ein Vertrag von B im QuerySet für A erscheint. Das gehört in diesen PR.

### Teilweise ausgeführt am 15.08.2026 — und warum nur teilweise

**Geliefert:** `core/tenancy.py` (Kontext, `TenantManager`, `AlleOrganisationenManager`,
`cache_key`, `OrganisationsFehler`), `core/middleware_tenancy.py`, die Besitzprüfung in
`_global_filter`, und die Mitgliedschaft im Test-Fixture. **Vier Tests sind grün geworden**, jeder
mit durchgeführter und protokollierter Gegenprobe.

**Nicht geliefert: die Anbindung des `TenantManager` an die Modelle.** Sie wurde gebaut,
gemessen und wieder zurückgenommen. Der Grund steht in `.claude/agents/chirurg.md`: *„Wenn ein
Schritt grösser wird als geplant: aufhören und melden, nicht durchziehen."*

Die Messung, zweistufig:

| Zustand | Fehlschläge von 1'072 bzw. 1'088 Tests |
|---|---|
| `TenantManager` als `objects` an `Liegenschaft` + `Mietvertrag` | **922** |
| dasselbe, aber Schreiben ohne Kontext erlaubt | **638** |

Die Diagnose dahinter ist der eigentliche Ertrag dieses Versuchs. In einem einzigen Testmodul
waren **75 von 83** Fehlschlägen ein `objects.create` und nur **8** eine Abfrage — deshalb der
zweite Messpunkt. Ein `create` gibt nichts heraus und braucht keinen Kontext; das ist im Manager
jetzt so umgesetzt und begründet. Die verbleibenden 638 haben eine andere Ursache: **Testbenutzer
haben keine Mitgliedschaft**, also setzt die Middleware keinen Kontext, also wirft jede lesende
View. Das lässt sich nicht an einer Stelle beheben — es braucht die Zuordnung in jedem der
20 Testmodule, die Bestände anlegen, und in den 46 Produktivmodulen, die `Liegenschaft` oder
`Mietvertrag` lesen.

**Das ist die Form von Etappe 5, nicht die von 4.2.** Der Plan sieht dort ohnehin sieben PRs vor,
einen je App. Die Manager-Anbindung gehört in denselben PR wie der Organisationsbezug der
jeweiligen App: Dann wandert je App ein überschaubarer Satz Aufrufstellen mit, statt dass ein
einziger Schritt die ganze Anwendung gleichzeitig umstellt. Ein Big-Bang wäre genau die
„lang lebende Umbau-Verzweigung", vor der der Plan unter *Was den Plan zum Scheitern bringen kann*
warnt — nur in einem einzigen Commit statt über zwei Wochen.

`core/tenancy.py` bleibt im Bestand. Es ist fertig, geprüft und ohne Nebenwirkung, solange kein
Modell den Manager trägt — und es ist die Voraussetzung dafür, dass Etappe 5 je App nur noch zwei
Zeilen setzen muss.

**Offen aus 4.2, mitzunehmen nach Etappe 5:**

- `TenantManager` an die Modelle, App für App
- Die Admin-Umgehung über `_base_manager` (`AdminUmgehungTests` bleibt rot) — sie hängt am
  Manager und ist ohne ihn nicht sinnvoll zu schliessen
- `cache_key` ist gebaut, aber noch nirgends verwendet (`CacheSchluesselTests` bleibt rot)

---

## 4.3 — Rollen je Organisation

Heute sind Rollen globale Django-Gruppen: `hat_rolle()` prüft `user.groups.filter(name__in=…)`. Eine Person, die bei zwei Verwaltungen arbeitet, hätte damit überall dieselbe Rolle.

Künftig: Mitgliedschaft je Organisation, mit den Rollen der Projektanweisung — **Inhaber, Verwalter, Sachbearbeiter, Lesezugriff**.

Der Abgleich mit den vier bestehenden Rollen (Verwaltung, Sachbearbeitung, Lesend, Eigentümer) ist eine **fachliche Frage** und gehört vorgelegt. Ein Punkt dabei ist bereits klar: `Eigentümer` ist keine Team-Rolle, sondern eine Portal-Rolle — das nicht vermischen.

### Fünf Altlasten aus Etappe 3, die hier fällig werden

Der `mandanten-auditor` hat sie über den E3-Diff gefunden; sie stehen in `docs/PHASE-2-PLAN.md` und gehören in 4.1 bzw. 4.3 abgearbeitet. Keine ist heute ein Leck — alle fünf werden eines, sobald es eine zweite Organisation gibt.

| # | Fundstelle | Was passiert nach 4.1 |
|---|---|---|
| 1 | `Benutzer.username`, global `unique` | Zwei Verwaltungen können keinen Benutzer `info@` führen. Fehlt als **siebter** Fall in `UniqueConstraintsProOrganisationTests` |
| 2 | `core/views/fw/benutzer.py:50` | „Benutzername bereits vergeben" wird zum **Existenz-Orakel** über die Mandantengrenze |
| 3 | `core/views/fw/benutzer.py:105` | Der Aussperrschutz zählt Verwaltungs-Accounts **aller** Organisationen — A kann sich aussperren |
| 4 | `core/auth_backends.py:37` | `email` identifiziert organisationsübergreifend; der `[:10]`-Deckel wird zur stillen Grenze |
| 5 | `core/views/portal.py:29` | Konto mit Eigentümer- **und** Mieterprofil erreicht das Mieterportal nie |

Punkt 1 bis 3 hängen unmittelbar an der Entscheidung aus dem Widerspruch oben und sollten mit ihr zusammen fallen.

---

## Modellgruppen, neu gemessen

Für Etappe 5 vorbereitend, hier nur zur Kenntnis. Nach Etappe 3 sind es **64 Modelle**.

| Gruppe | Anzahl | Bedeutung |
|---|---|---|
| **A** — kein Weg zur Liegenschaft | **14** | `AktivitaetsLog`, `Benutzer`, `Buchungskonto`, `Eigentuemer`, `EigentuemerAuszahlung`, `Handwerker`, `Kontoauszug`, `Lebensdauer`, `LieferantProfil`, `Mieter`, `MieterAdresse`, `NebenkostenLernRegel`, `Verwaltung`, `Vorlage` |
| **B** — Weg nur über optionale FK | 15 | `Bankbewegung`, `Buchung`, `DebitorenRechnung`, beide `Dokument`, `Geraet`, `Kommunikation`, `KreditorPosition`, `KreditorenRechnung`, `KreditorenZahlung`, `Mahnung`, `Pendenz`, `Zaehler`, `ZaehlerStand`, `Zahlungseingang` |
| **C** — geschlossene Pflicht-Kette | **35** | denormalisierte Spalte verlustfrei nachrüstbar |

---

## Abnahme

Je PR: Testsuite grün, `manage.py check`, `makemigrations --check`, Ruff sauber, Vorwärts- **und** Rückwärtsmigration ausgeführt, `mandanten-auditor` über den Diff.

Für die Etappe insgesamt:

- Mindestens die Tests aus `ManagerIsolationTests`, `FremdeIdUeberUrlsTests` und `AdminUmgehungTests` werden grün
- **Für jeden grün gewordenen Test die Gegenprobe durchgeführt und protokolliert**: Filter entfernt → Test rot → Filter zurück. Mit Datum im PR. Ein Test ohne Gegenprobe gilt als nicht geschrieben.
- Die drei Selbstprüfungstests bleiben grün
- Testzahl nicht unter **1'099** (Stand nach Bauform E, 15.08.2026)
- Noch rote Tests sind benannt, mit Zuordnung zu Etappe 5 oder 6
- **`ModellbezugWaechterTests` bleibt aussagekräftig.** Er trägt heute genau eine benannte Ausnahme (`benutzer.Benutzer`). Wird der Test in dieser Etappe grün, ist zu prüfen, ob die Ausnahme noch gilt — ein Wächter mit einer überholten Ausnahme prüft weniger, als er behauptet.

### Bauform E — nachgeholt am 15.08.2026, vor 4.2

Die Abdeckungslücke ist geschlossen: `FremdeIdUeberQuerystringTests`, 6 Methoden, alle
`expectedFailure`. Damit wird 4.2 nicht mehr gegen eine Abdeckung abgenommen, die den
Haupteinstiegspunkt `_global_filter` gar nicht enthält.

Was die Tests dabei gemessen haben — das ist zugleich die Arbeitsliste für 4.2:

| Befund | Zahl |
|---|---|
| Parameterlose `fw_`-URLs geprüft | 107 |
| davon übernehmen ein fremdes `?lg=` | **61** |
| werten den Filter nicht aus | 46 |

Dazu drei Einzelbefunde: Der **Liegenschaftswähler** selbst liegt offen (`_global_filter` legt
`Liegenschaft.objects.all()` in den Kontext — jede fremde Adresse steht im Menü, ohne dass jemand
eine ID raten müsste). Das **Logbuch** filtert auf `?benutzer=<fremde pk>` ohne Prüfung. Der
**CSV-Export** zieht den gesamten Audit-Trail.

---

## Was nicht Teil dieser Etappe ist

- **Der `organisation`-Fremdschlüssel auf allen 64 Modellen** — Etappe 5, App für App, mit den drei Rezepten aus `phase-2-migration`.
- **Dateiablage, Hintergrundjobs, PDF-Absender, Cache-Keys** — Etappe 6.
- **Entitlements und Abo-Stufen** — Phase 3.
- **Aufräumen an den 79 `Verwaltung.objects`-Fundstellen**, soweit es über das Nötige hinausgeht. Was für die Isolation gebraucht wird, kommt mit; der Rest in einen eigenen PR.
