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

## Ein Widerspruch im Auftrag, der vor 4.1 aufgelöst gehört

Der Auftrag sagt an zwei Stellen Verschiedenes über dasselbe:

> **4.1:** „Ein Benutzer gehört zu genau einer Organisation."
> **4.3:** „Künftig: Mitgliedschaft je Organisation."

Das ist nicht dasselbe Modell. Entweder trägt `Benutzer` einen Fremdschlüssel `organisation` — dann ist eine Person, die für zwei Verwaltungen arbeitet, zwei Konten mit zwei Passwörtern. Oder es gibt ein Mitgliedschaftsmodell `(Benutzer, Organisation, Rolle)` — dann trägt `Benutzer` **keinen** Organisationsfremdschlüssel, und 4.1 ist so nicht ausführbar.

Der Skill `swissimmo-review` verlangt hier ausdrücklich: anhalten, nicht selbst auflösen. Deshalb steht es hier und nicht in einem Commit.

**Zwei Nebenbedingungen, die vorliegen und die Entscheidung einengen:**

`core/tests/test_isolation.py` trägt seit dem Auditor-Lauf über Etappe 3 die benannte Ausnahme

```python
'benutzer.Benutzer': 'Mitgliedschaft je Organisation statt eigener Spalte — Etappe 4',
```

Sie ist eine **Notiz**, keine Entscheidung — wer sich für den Fremdschlüssel entscheidet, streicht sie und trägt das Feld nach. Aber sie hält fest, wohin die Überlegung damals ging.

Und aus dem Mietrecht heraus: Ein Mieter oder Eigentümer, dessen Wohnung von Verwaltung A in die Verwaltung B übergeht, soll seine Zugangsdaten behalten. Mit einem Fremdschlüssel am Benutzer heisst das Kontowechsel; mit Mitgliedschaften heisst es eine Zeile mehr.

---

## Drei PRs, nacheinander

Anders als Etappe 3 ist das **kein** Ein-PR-Schritt. Die drei Teile sind einzeln lauffähig und einzeln zurückrollbar.

---

## 4.1 — Das Modell `Organisation`

Zuerst die Frage, die alles andere bestimmt: **Was wird aus `crm.Verwaltung`?**

`Verwaltung` ist heute der Singleton mit **23 konkreten Feldern** — Firma, Adresse, IBAN, Logo, Unterschrift, Referenzzins, LIK, MWST-Angaben, Portal-Token und `abo_plan`. Sie wird an **79 Stellen** im Produktivcode über `Verwaltung.objects` gelesen; **76** davon sind wörtlich `.objects.first()`. Mit den Tests sind es 131.

Zwei Wege, und die Entscheidung gehört **vorgelegt, nicht selbst getroffen**:

**Weg A — `Verwaltung` wird zu `Organisation`.** Umbenennung wie bei `Mandant` → `Eigentuemer` in E3, mit `db_table` unverändert. Die 23 Felder bleiben, wo sie sind. Vorteil: ein Modell, keine Doppelung, die 79 Fundstellen werden zu `request.organisation`. Nachteil: `Organisation` trägt dann Fachdaten (Referenzzins, LIK, MWST) neben Mandantendaten (Abo, Branding).

**Weg B — `Organisation` entsteht neu**, `Verwaltung` bleibt als Fachdatensatz daran hängen. Sauberere Trennung, aber zwei Modelle, zwei Migrationen, und jede Fundstelle muss entscheiden, welches der beiden sie meint.

Einschätzung, ohne dass sie die Entscheidung ersetzt: Weg A ist bei 79 Fundstellen der kürzere und weniger fehleranfällige Weg, und die Vermischung lässt sich später auflösen. Aber das ist eine Produktentscheidung, keine technische.

Unabhängig vom Weg braucht es in diesem PR:

- Die Verbindung `Benutzer` ↔ `Organisation` — **in der Form, die der Widerspruch oben klärt.**
- Eine Datenmigration, die den bestehenden Bestand einer Ausgangsorganisation zuweist.
- **Noch keinen Manager, noch keine Filterung.** Nur das Modell und die Zuordnung.

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
- Testzahl nicht unter **1'093**
- Noch rote Tests sind benannt, mit Zuordnung zu Etappe 5 oder 6
- **`ModellbezugWaechterTests` bleibt aussagekräftig.** Er trägt heute genau eine benannte Ausnahme (`benutzer.Benutzer`). Wird der Test in dieser Etappe grün, ist zu prüfen, ob die Ausnahme noch gilt — ein Wächter mit einer überholten Ausnahme prüft weniger, als er behauptet.

### Vorher nachzuholen: Bauform E

`docs/PHASE-2-PLAN.md` vermerkt bei Etappe 2 eine Abdeckungslücke, die vor 4.2 zu schliessen ist: Bauform A sammelt nur URLs mit genau **einem Pfadparameter**. Listen- und Exportpfade, die über den Querystring filtern, liegen vollständig ausserhalb — `/neu/logbuch/?benutzer=<pk>`, `/neu/logbuch/?export=csv`, `/neu/benutzer/`. Wer 4.2 gegen die heutige Abdeckung abnimmt, hält die Isolation für belegt, wo sie ungeprüft ist.

---

## Was nicht Teil dieser Etappe ist

- **Der `organisation`-Fremdschlüssel auf allen 64 Modellen** — Etappe 5, App für App, mit den drei Rezepten aus `phase-2-migration`.
- **Dateiablage, Hintergrundjobs, PDF-Absender, Cache-Keys** — Etappe 6.
- **Entitlements und Abo-Stufen** — Phase 3.
- **Aufräumen an den 79 `Verwaltung.objects`-Fundstellen**, soweit es über das Nötige hinausgeht. Was für die Isolation gebraucht wird, kommt mit; der Rest in einen eigenen PR.
