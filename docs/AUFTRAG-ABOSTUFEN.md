# Vier Abostufen: eine Quelle für Stufen, Grenzen und Preise

**Stand:** 29.09.2026 · freigegeben (A1–A4 mit Empfehlung) und umgesetzt, siehe «Umsetzung» am Ende
**Basis:** `main` (`573abf7`)
**Agenten:** `erweiterungen` (führend), `ui-ux` (Preisseite), `testabteilung` (Abnahme)
**Bezug:** `docs/PLAN-V7.md` D7 · `docs/PHASE-3-ENTITLEMENTS.md` §6, Schritte 1 und 7 · `docs/MARKT.md` §4–5 · `MARKET_RESEARCH_COMPETITORS.md` §6.2

---

## Worum es geht

Im Bestand gibt es heute **drei Stufenmodelle, die sich widersprechen**:

| Wo | Stufen | Wirkung |
|---|---|---|
| `core/views/fw/profil.py:1035`, `ABO_PLAENE` | `start` / `pro` / `premium`, CHF 0.90 / 1.90 / 2.90 **pro Einheit** | Für Kunden sichtbar auf `/neu/abonnement/`, sperrt aber nichts |
| `crm/models.py:99`, `Organisation.ABO_CHOICES` | `start` / `pro` / `premium` | Speichert nur die Auswahl (TS-11: «Abo-Feld ohne Wirkung») |
| `core/funktionen.py:70`, `_AUFBAUEND` / `GRENZEN` | `basis` / `aufbau` / `verwaltung` / `portfolio` | Die einzige Stufe, die wirkt. `VORGABE_STUFE = 'verwaltung'` gilt fest für alle Organisationen. |

Das Preismodell auf der Preisseite ist ab mittlerer Portfoliogrösse nicht verkäuflich. Bei 400 Einheiten zeigt sie CHF 760 pro Monat, Fairwalter verlangt CHF 359 (`MARKET_RESEARCH_COMPETITORS.md` §4). Zudem steigt dort der Einheitspreis mit der Stufe, während er im Markt mit der Menge sinkt.

**Ziel dieses Auftrags:** Es gibt nur noch **eine** Quelle für Stufen, Grenzen und Preise, mit den Marktnamen `start` / `team` / `professional` / `enterprise` (Entscheid D7). Die Preisseite und die Auswahlliste werden aus dieser Quelle gespeist. **Für die Anwender ändert sich dabei keine einzige Freigabe.**

---

## Die Zielwerte

**Preise gelten als vorläufig** (`PHASE-3-ENTITLEMENTS.md` §7.1: «Struktur ja, Preise später»). Sie werden im Code als solche gekennzeichnet und erst nach der Kostenrechnung pro Mandant bestätigt. Die Struktur ist mit diesem Auftrag verbindlich.

| | `start` | `team` | `professional` | `enterprise` |
|---|---|---|---|---|
| Klartext | Start | Team | Professional | Enterprise |
| Preis / Monat, exkl. MWST | CHF 39 | CHF 119 | CHF 329 | CHF 749 |
| Jahresabo | −15 % | −15 % | −15 % | −15 % |
| Einheiten inklusive | 25 | 150 | 500 | 2'000 |
| Nutzer | 2 | 5 | 15 | unbegrenzt (`None`) |
| +100 Einheiten / Monat | – | CHF 60 | CHF 45 | CHF 30 |
| Deckel Einheiten mit Zusatz | 25 | 300 | 1'000 | unbegrenzt |
| Support | E-Mail | E-Mail + Telefon | E-Mail + Telefon | SLA, Onboarding inklusive |

Der Deckel verhindert, dass Professional mit Zusatzeinheiten die Enterprise-Stufe verdrängt (`MARKET_RESEARCH_COMPETITORS.md` §4, «Widerspruch im Vorschlag selbst»).

**Die Speichergrenze entfällt in dieser Fassung.** Es gibt keine Speicher-Buchhaltung (`PHASE-3-ENTITLEMENTS.md` §5.4 und §7.4). Die Preisseite nennt deshalb keine GB-Werte.

---

## Die Abbildung der Funktionen: verhaltensneutral

Der Funktionskatalog in `core/funktionen.py` bleibt unverändert. Neu verteilt wird nur, **ab welcher Stufe** ein Schlüssel gilt.

| Schlüssel | heute ab | neu ab | Begründung |
|---|---|---|---|
| `akten`, `dokumente` | basis | **start** | Grundlage |
| `fristenwaechter` | aufbau | **start** | Fristen sind Pflicht, nicht Komfort |
| `nebenkostenlauf` | verwaltung | **start** | Im Markt überall im Grundpreis (MARKT.md §5) |
| `vor_ort` (Abnahme) | verwaltung | **start** | Unterscheidungsmerkmal: Fairwalter verlangt CHF 9.90 pro Abnahme |
| `mieterportal` | verwaltung | **start** | Unterscheidungsmerkmal |
| `monatslauf` | basis | **start** | ~~team~~ — korrigiert nach dem Prüfauftrag unten: Der Schlüssel trägt die Pflichtläufe. |
| `faelle`, `zulauf` | aufbau | **team** | Zusammenarbeit im Team |
| `eigentuemerportal` | verwaltung | **team** | Wichtigster Hebel: Bei Fairwalter gibt es das erst ab CHF 299 |
| `mandatsrentabilitaet` | portfolio | **professional** | Mandatsgeschäft |
| `schnittstellen` | portfolio | **professional** | pain.001, Export (MARKT.md §5) |

**Warum das verhaltensneutral ist, nachgerechnet:** Die neue Stufe `team` enthält genau dieselben zehn Schlüssel wie die heutige `verwaltung`: akten, dokumente, monatslauf, faelle, fristenwaechter, zulauf, nebenkostenlauf, vor_ort, eigentuemerportal, mieterportal. Das gilt unabhängig davon, ob `monatslauf` in `start` oder `team` steht. Die neue Stufe `professional` enthält genau dieselben wie `portfolio`. Deshalb gilt:

> `VORGABE_STUFE` wird `'team'`. Die Menge der freigegebenen Schlüssel für jede Organisation ist vor und nach dem Umbau identisch.

Das ist kein Nebenbefund, sondern die Abnahmebedingung Nummer 1.

**Prüfauftrag zu `monatslauf`:** Vor dem Umbau nachsehen, was dieser Schlüssel heute konkret sperrt. Belegt ist nur ein Aufrufer, die Reiter in `faelle/akten.py:165`. Deckt er die manuelle Sollstellung, den Bankabgleich oder das Mahnwesen ab, gehört er aufgeteilt, **bevor** er auf `team` wandert. Pflichtfunktionen bleiben in jeder Stufe.

> **Ergebnis (29.09.2026):** `monatslauf` ist der Funktionsschlüssel aller
> Pflichtläufe — Sollstellung, Bankabgleich, Mahnlauf, Zahllauf Kreditoren und
> MWST-Abrechnung (`faelle/management/commands/laeufe_planen.py:22–32`). Heute
> wertet ihn keine Stelle aus (einziger Aufrufer von `hat_funktion` sind die
> Reiter in `faelle/akten.py`, und die fragen nur `faelle`). Eine künftige
> Sperre darauf nähme Start-Kunden aber Pflichtarbeit weg. Er bleibt deshalb
> in `start`. Wer später den *automatischen* Lauf ab `team` verkaufen will,
> braucht einen eigenen Schlüssel dafür.

---

## Vorgehen

Es sind vier Schritte. Jeder Schritt ist ein eigener Commit, alle zusammen ergeben einen PR.

### Schritt 1: Eine Quelle (`core/funktionen.py`)

- `_AUFBAUEND` auf die vier Marktcodes umstellen, mit der Verteilung aus der Tabelle oben.
- `GRENZEN` auf 25/2, 150/5, 500/15 und 2000/`None` setzen.
- Die Preise **in derselben Datei** als `PREISE` führen, mit Kennzeichnung «vorläufig, nicht aus Kostenrechnung». Dazu gehören Monatspreis, Zusatzpreis pro 100 Einheiten, Deckel, Jahresrabatt und Klartextname je Stufe.
- `VORGABE_STUFE = 'team'`.
- **Kein** neues `core/entitlements.py`. D7 legt `funktionen.py` als die eine Quelle fest. `PHASE-3-ENTITLEMENTS.md` §3.1 ist in diesem Punkt überholt und bekommt einen datierten Vermerk.

### Schritt 2: Auswahlliste am Modell (`crm/models.py`)

- `ABO_CHOICES` wird aus `core/funktionen.py` abgeleitet und nicht ein zweites Mal geschrieben.
- Die Datenmigration bildet so ab: `start` → `start`, `pro` → `team`, `premium` → `professional`. Der Default wird `'team'`.
- **Es gibt eine Organisation** (`PHASE-3-ENTITLEMENTS.md` §5.3). Ihr Wert wird in der Migration bewusst gesetzt und im PR genannt.
- `core/services/onboarding.py:117–130`: Der Kommentar «bleibt bewusst auf `'pro'`» wird gegenstandslos und muss nachgeführt werden.
- `Organisation.abo_plan` **bleibt als Feld bestehen**. Die Ablösung durch `abo.Abonnement` (D7) braucht Zahlungsanbieter und Testphase und ist nicht Teil dieses Auftrags.

### Schritt 3: Preisseite (`core/views/fw/profil.py`, `core/templates/fw/abonnement.html`)

- `ABO_PLAENE` entfällt. Der View liest Preise, Grenzen und Freigaben aus `core/funktionen.py`.
- **Preisrechnung neu:** Grundpreis der kleinsten Stufe, deren Deckel die aktuelle Einheitenzahl fasst, plus nötige Zusatzpakete. Die Seite zeigt je Stufe, ob sie für den heutigen Bestand reicht.
- **Merkmalslisten** werden aus dem Funktionskatalog erzeugt, nicht als freier Text geführt.
  - «API-Zugang» wird gestrichen (`PHASE-3-ENTITLEMENTS.md` §7.5).
  - «KI-Analysen & Report-Assistent» wird gestrichen, weil es das im Code nicht gibt.
  - Keine GB-Angaben.
- Die Auswahl darf weiterhin nur der Inhaber treffen (`profil.py:1076`, unverändert).
- Alle neuen Texte laufen durch `gettext` und werden in DE/FR/IT/EN übersetzt. **Messung bei 390 px**, nicht nur am Desktop (`ui-ux`).

### Schritt 4: Tests (`testabteilung`)

| Test | Prüft | Gegenprobe |
|---|---|---|
| Freigabe-Gleichheit | Für `VORGABE_STUFE` ist die Schlüsselmenge identisch mit der fest hinterlegten Liste der zehn Schlüssel von heute | Einen Schlüssel testweise auf `professional` schieben: Der Test muss rot werden |
| Eine Quelle | `ABO_CHOICES`-Codes = Stufencodes in `funktionen.py`; Preisseite zeigt genau die Stufen aus `PREISE` | Eine fünfte Stufe nur im Modell eintragen: rot |
| Preisrechnung | 50 → CHF 119 (Team, weil Start bei 25 endet), 150 → CHF 119, 400 → CHF 329, 1'000 → CHF 554, 2'500 → Enterprise mit Zusatz | Deckel entfernen: 1'000 in Team muss den Test brechen |
| Keine Phantommerkmale | Kein «API» und kein «GB» im gerenderten HTML der Preisseite | – |
| Migration | `pro` → `team`, `premium` → `professional`; `makemigrations --check` bleibt leer | – |
| Bestand | `test_plattform.py:28–30` und `test_rollentabelle.py:36–42` auf die neuen Codes nachgeführt, **nicht gelöscht** | – |
| Sweep | Die bestehenden Tests `faelle/test_akten.py:164/171` mit `override_settings` auf die neuen Codes | `SWISSIMMO_VORGABE_STUFE='start'` blendet die Reiter aus |

Die gesamte Suite läuft in Blöcken nach `swissimmo-review`, nicht am Stück.

---

## Was dieser Auftrag bewusst nicht tut

- **Keine Sperren einziehen.** `stufe_von` bleibt fest hinterlegt. Wer welche Stufe *hat*, entscheidet erst P3.1 nach dem Onboarding (`PHASE-3-ENTITLEMENTS.md` §5.3a: «Onboarding vor Entitlements»).
- **Keine Grenzen durchsetzen.** `GRENZEN` bekommt neue Werte, geprüft wird weiterhin nirgends. Das ist `PHASE-3-ENTITLEMENTS.md` §6, Schritt 5.
- **Kein Zahlungsanbieter, kein `abo.Abonnement`, keine Testphase.** Das ist D6 und freigabepflichtig.
- **Keine nutzungsabhängige Abrechnung** für Signatur und KI-Belege. Die Preise dafür folgen aus der Kostenrechnung.
- **Keine öffentliche Preisseite ausserhalb der Anwendung.** Die Preise bleiben vorläufig, bis die Kostenrechnung steht.

---

## Vor der Freigabe zu entscheiden

| # | Frage | Empfehlung |
|---|---|---|
| A1 | Gilt die Funktionsverteilung aus der Tabelle, insbesondere Mieterportal und Abnahme in `start` und Eigentümerportal ab `team`? | **Ja.** Sie ist verhaltensneutral und setzt die Positionierung aus dem Marktaudit um. |
| A2 | Werden Preise im Produkt angezeigt, obwohl sie vorläufig sind? | **Ja, mit Hinweis** «Einführungspreise, Stand …». Die heutige Seite zeigt schlechtere Preise ohne Hinweis. |
| A3 | Deckel und Zusatzpreise pro Stufe (Team bis 300, Professional bis 1'000)? | **Ja.** Ohne Deckel kannibalisiert Professional Enterprise. |
| A4 | Jahresrabatt 15 % beibehalten? | **Ja.** Er steht schon im Code, und Fairwalter bietet keinen. |

---

## Abnahme

Der PR ist fertig, wenn:

1. Die Freigabe-Gleichheit belegt ist: Test grün, Gegenprobe rot, beides im PR dokumentiert.
2. `grep -rn "ABO_PLAENE\|'pro'\|'premium'"` ausserhalb von Migrationen nichts mehr findet.
3. Die Preisseite bei 390 px und am Desktop als Screenshot im PR liegt, in DE und FR.
4. Die sechs Punkte aus `swissimmo-review` belegt sind.
5. `docs/ANALYSE.md` TS-11, `docs/PHASE-3-ENTITLEMENTS.md` §3.1/§6 und `docs/PLAN-V7.md` D7 datiert nachgeführt sind.

---

## Umsetzung (29.09.2026)

| Schritt | Stand |
|---|---|
| 1 · Eine Quelle | `core/funktionen.py`: vier Stufen, `STUFEN_NAMEN`, `GRENZEN`, `PREISE` (vorläufig), `JAHRESRABATT`, `PREISSTAND`, `SUPPORT`, `monatspreis()`, `passende_stufe()`; `VORGABE_STUFE = 'team'`. Klartexte des Katalogs sind übersetzbar. |
| 2 · Modell | `ABO_CHOICES` aus `funktionen.py` abgeleitet, Feld auf 20 Zeichen, Default `team`; `crm/migrations/0045_abostufen_marktnamen.py` schreibt `pro` → `team`, `premium` → `professional`. |
| 3 · Preisseite | `ABO_PLAENE` entfallen, `_abo_plaene()` liest nur `funktionen.py`. Vier Karten mit Grundpreis, Preis für den heutigen Bestand, Zusatzpaketen samt Deckel, Merkmalen aus dem Katalog, Support. Kein «API», keine GB, Hinweis «Einführungspreise». DE/FR/IT/EN übersetzt, bei 390 px ohne horizontalen Überlauf. |
| 4 · Tests | `core/tests/test_abostufen.py` neu (Freigabe-Gleichheit, eine Quelle, Preisrechnung, Preisseite), bestehende Tests nachgeführt, drei Gegenproben rot gesehen. |
