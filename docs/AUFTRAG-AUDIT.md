# Auditlauf über Phase 2

**Stand:** 18.08.2026 · letzter offener Punkt aus `docs/PHASE-2-ABSCHLUSS.md`
**Basis:** `main`
**Agent:** `mandanten-auditor`

---

## Warum am Stück und nicht je PR

Jeder einzelne PR der Etappe 6 wurde geprüft. Der Gesamtdiff seit `d0b5d39` umfasst **20 Commits, 102 Dateien, 5'753 hinzugefügte und 556 entfernte Zeilen** — und er hat vier Schichten gleichzeitig verändert: Manager, Views, Dateiablage, Hintergrundläufe.

**Lücken entstehen an den Nahtstellen, nicht in der Mitte.** Eine View, die sich auf den Manager verlässt, ein Command, der sich auf die View verlässt, ein Export, der beides umgeht — jede dieser Kombinationen war in einem anderen PR und wurde nie zusammen gelesen.

Das Muster ist in dieser Phase schon zweimal aufgetreten: Die Zeile in `_global_filter` sah aus wie die tragende Prüfung und war schwächer als der Manager. Und das Suite-Skript meldete grün für Module, an die es gedacht hatte. Beides fällt nur beim Blick aufs Ganze auf.

```bash
git diff d0b5d39..HEAD
```

---

## Was der Auditor prüfen soll

Die Prüfpunkte stehen in `.claude/agents/mandanten-auditor.md`. Für diesen Lauf besonders:

**Nahtstellen zwischen den Schichten.** Wo verlässt sich eine Ebene auf eine andere? Der Manager filtert die Einstiegsmodelle — was ist mit Modellen ohne eigenen Manager, die über Rückbezüge erreicht werden? Die bewusste Entscheidung war, dass Rückbezüge den Filter nicht erben. Hält die Begründung über den ganzen Diff?

**`alle_organisationen` und `ohne_organisation`.** Jede Verwendung ist eine bewusste Umgehung. Ist sie begründet, und stimmt die Begründung noch? Besonders dort, wo sie in einem PR eingeführt und in einem späteren umgebaut wurde.

**Die drei verbliebenen handgeschriebenen `organisation=`-Filter** in `check_rents`, `fristen_digest`, `detailseiten`. Sie gelten als redundant, aber nicht schwächer. Stimmt das? Der vierte war schwächer und wurde entfernt — die Prüfung darauf ist dieselbe: Was passiert ohne Kontext?

**Schreibpfade.** Löschen und Bearbeiten waren in der Analyse als am häufigsten ungeschützt benannt. Sie sind jetzt getestet — aber der Auditor liest gegnerisch, nicht gegen die Testliste.

**Was den Prozess verlässt.** Dateiablage, PDF-Absender, E-Mail, Exporte, Cache-Keys, `AktivitaetsLog`. Enthält ein Export nur Daten einer Organisation, auch wenn ein Superuser ihn auslöst?

---

## Wie der Bericht aussehen soll

Gegliedert nach Schwere, wie in der Agentendefinition: **Leck** (fremde Daten erreichbar), **Lücke** (noch kein Leck, aber die Isolation hängt an einer einzigen Stelle), **Hinweis**.

Je Fund: Datei und Zeile, das Muster, die konkrete Auswirkung, ein Vorschlag.

**Ohne Fund: ausdrücklich sagen, was geprüft wurde und was nicht.** Ein Bericht, der Prüftiefe suggeriert, die es nicht gab, ist schlechter als kein Bericht — und dieser hier ist der letzte Blick, bevor eine zweite Organisation entsteht.

Der Bericht gehört **ins Repo**, nicht nur in die Sitzung: `docs/AUDIT-PHASE-2.md`. Ein Befund, der nur in einem Chatverlauf steht, ist beim nächsten Mal nicht auffindbar — und beim übernächsten weiss niemand mehr, ob überhaupt geprüft wurde.

---

## Abnahme

- `docs/AUDIT-PHASE-2.md` im Repo, mit Datum und Commit-Bereich
- Jeder Fund der Stufe **Leck** behoben, jede **Lücke** entweder behoben oder begründet stehen gelassen
- Volle Suite grün — `manage.py test` **ohne Labels**, Zahl gegen Djangos Discovery abgeglichen. Erwartungswert: **1'256**
- `check`, `makemigrations --check`, Ruff sauber

---

## Danach ist Phase 2 zu

`docs/PHASE-2-PLAN.md` bekommt den Abschlussvermerk mit Datum und den Zahlen: 63 von 65 Modellen mit Organisationsbezug, 25 Isolationstests grün, 1'256 Testfälle, `Organisation.objects.first()` von 76 auf 0, sieben Rückfälle getilgt.

Und dann gilt die Reihenfolge aus `docs/PHASE-2-ABSCHLUSS.md`: **PostgreSQL, Wiederherstellungs-Probelauf, 2FA — und erst dann die zweite Organisation.**
