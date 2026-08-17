# Phase 2 abschliessen

**Stand:** 17.08.2026 · nach Etappe 6
**Basis:** `main`
**Agent:** `aufraeumer`, plus `mandanten-auditor` für den Gesamtdiff
**Nicht Teil dieses Auftrags:** der PostgreSQL-Umzug

---

## Wo wir stehen

Alle **25 Isolationstests sind grün**, kein `expectedFailure` mehr. Volle Suite: 1'123 Tests, 1'254 Testfälle, `check` und Ruff sauber, Rückwärtsmigration läuft.

Unabhängig gegengeprüft am 17.08.2026: `TenantManager` auf `Liegenschaft` ausgebaut → drei Tests rot, darunter `test_default_manager_liefert_keine_fremden_daten` und zwei POST-Pfade. Der Manager filtert je Kontext, wirft ohne Kontext einen `OrganisationsFehler` und liefert über `alle_organisationen` bewusst beides.

Es fehlen vier Dinge, alle klein. Danach ist Phase 2 zu.

---

## 1 — Der Auditor über den Gesamtdiff

`mandanten-auditor` über den vollständigen Diff der Etappe 6, nicht über einzelne Commits. Grund: Jeder einzelne PR war für sich geprüft, aber die Etappe hat vier Schichten gleichzeitig angefasst — Manager, Views, Dateiablage, Hintergrundläufe. Lücken entstehen an den Nahtstellen, nicht in der Mitte.

```bash
git diff d0b5d39..HEAD
```

Der Bericht gehört ins Repo, nicht nur in die Sitzung — als Abschnitt in `PHASE-2-PLAN.md` oder als eigene Datei. Ein Auditbefund, der nur in einem Chatverlauf steht, ist beim nächsten Mal nicht auffindbar.

## 2 — Die Gegenproben protokollieren

Die Abnahmeregel lautet: Ein Test ohne durchgeführte Gegenprobe gilt als nicht geschrieben. Für die 25 Tests fehlt dieses Protokoll bisher.

Je Test: welche Schicht wurde ausgebaut, welche Tests wurden dabei rot, mit Datum. Tabelle genügt.

**Ein Fund dabei, den ich beim Nachprüfen hatte** und der ins Protokoll gehört: Die Besitzprüfung in `_global_filter` auszubauen macht **keinen** Test rot. Vor der Manager-Anbindung waren es drei. Der Grund ist harmlos — `Liegenschaft.objects.all()` läuft jetzt durch den `TenantManager` und ist damit schon gefiltert; die Zeile im View ist redundant geworden.

Trotzdem zu entscheiden: **entfernen oder behalten.** Eine Zeile, die wie eine Sicherheitsprüfung aussieht und von keinem Test abgedeckt ist, führt beim nächsten Lesen in die Irre. Behalten ist vertretbar als Tiefenstaffelung — dann aber mit Kommentar, dass sie nicht die tragende Schicht ist. Meine Empfehlung: entfernen, weil der Skill die zentrale Erzwingung verlangt und zwei Stellen zwei Wahrheiten bedeuten können.

## 3 — Die redundante Sicherheitszeile

Siehe Punkt 2. Gleiche Prüfung für alle Stellen, an denen nach der Manager-Anbindung noch von Hand auf `organisation` gefiltert wird: Ist der Filter jetzt tautologisch? Dann weg oder kommentieren.

## 4 — Den Plan nachführen

`docs/PHASE-2-PLAN.md`: Etappe 4, 5 und 6 mit Datum als abgeschlossen markieren, wie bei 0 bis 3. Und einen Abschlussabschnitt mit den Zahlen: 63 von 65 Modellen mit Bezug, 25 Isolationstests grün, 1'254 Testfälle, `Organisation.objects.first()` von 76 auf 0.

Ausserdem im selben Zug: die drei verwaisten Zweige auf `origin` entfernen — `docs/e1-auftrag`, `refactor/e1a-api-fachlogik`, `claude/swiss-immo-code-analysis-753mld`. Ihr Inhalt ist längst in `main`; sie stehen nur noch herum und verleiten dazu, auf einem toten Zweig weiterzuarbeiten.

---

## Abnahme

- Auditbericht im Repo, ohne Leckfund
- Gegenproben-Protokoll für alle 25 Tests
- Entscheidung zur redundanten Filterzeile getroffen und umgesetzt
- `PHASE-2-PLAN.md` nachgeführt, Etappen 4–6 mit Datum
- Verwaiste Zweige entfernt
- Testsuite grün, Testfälle nicht unter **1'254**, `check` und Ruff sauber

---

## Was danach ansteht — und in welcher Reihenfolge

Die harte Grenze bleibt: **keine zweite Organisation, bevor diese drei Punkte erledigt sind.**

| | Was | Warum davor |
|---|---|---|
| 1 | **PostgreSQL-Umzug** | SQLite bleibt bei einem Schreiber, auch mit WAL. Zwei Verwaltungen mit gleichzeitigen Massenläufen — Sollstellung, Mahnlauf — treffen genau diese Grenze. Datenbank und Werkzeug stehen seit 17.08. bereit; der Umzug ist ein Befehl. |
| 2 | **Wiederherstellungs-Probelauf** | Der Weg ist beschrieben, aber nie ganz durchlaufen. Eine Sicherung, aus der nie zurückgespielt wurde, ist eine Vermutung. Vor dem ersten Fremdmandanten. |
| 3 | **2FA** | Fairwalter führt es in allen Preisstufen. Bei Mieterdaten, Betreibungsauszügen und Lohnausweisen eine Ausschreibungsanforderung, kein Komfortmerkmal. |

Erst dann die zweite Organisation — und mit ihr der erste echte Beweis, dass die Trennung im Betrieb hält.

**Parallel möglich, ohne Abhängigkeit:** Phase 3 vorbereiten. `docs/MARKT.md` enthält den Vorschlag für die vier Stufen (CHF 39/119/329/749) und den Modulzuschnitt. Offen sind dort die Kostenrechnung je Mandant, die Gespräche mit fünf bis zehn Verwaltungen und die Zahlungsanbieter-Offerten — alles drei bei Dominik, nicht delegierbar.

**Ebenfalls offen und nicht vergessen:** Groq-Auftragsbearbeitungsvertrag (P0.7), Hosting-Standort, Sicherung ausser Haus, Python-Version angleichen (produktiv 3.10.12, Ruff `py311`, Konsole 3.13).
