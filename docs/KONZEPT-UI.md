# Konzept: Struktur und Oberfläche

Stand 20.08.2026 · gilt ab Phase 4a · ersetzt keine bestehende Phasenvorgabe ausser der unten
festgehaltenen Teilung von Phase 4.

Dieses Dokument beschreibt in den Abschnitten 1 bis 15, **wie swissImmo bedient wird**.
Abschnitt 16 kam mit Phase 4b dazu und hält fest, **wie es aussieht** — Palette,
Komponentenschicht und die Regel, dass der Aktenkopf gerechnete Zustände zeigt statt Felder.

> Bis 20.08.2026 stand hier, Farben und Komponenten „folgen in Phase 4b". Sie waren zu dem
> Zeitpunkt längst gebaut und durch `core/tests/test_palette.py` festgeschrieben, das seinerseits
> auf dieses Dokument verwies. Nachgetragen, damit die Verweise wieder zusammenpassen.

Zielkunde: **Verwaltung mit 2 bis 5 Personen**, 150 bis 800 Einheiten, mehrere
Eigentümermandate, Buchhaltung im Haus. Alle Entwurfsentscheidungen sind an diesem Profil
ausgerichtet.

---

## 1. Warum die bestehende Struktur ersetzt wird

Die heutige Navigation (`core/navigation.py`) hat sechs Bereiche — Heute, Portfolio,
Vermietung, Finanzen, Berichte, Kontakte — in zwei Modi. Sie ist nach **Datenmodell**
geschnitten, nicht nach Arbeit. Vier Befunde:

**Es gibt Module, aber keine Vorgänge.** Ein Mieterwechsel läuft vier Monate über Kündigung,
Bestätigung, Ausschreibung, Bewerbung, Abnahme und Endabrechnung. In `core/views/fw/` sind
diese Schritte als eigene Module vorhanden (`kuendigung.py`, `mietprozess.py`, `abnahme.py`,
`vertragserstellung.py`), aber nichts hält sie zusammen. Status, Zuständigkeit und Frist des
Gesamtvorgangs existieren nur im Kopf der Bewirtschaftung. **Der fallengelassene Vorgang ist
in einem Büro mit drei Personen der teuerste Fehler.**

**„Heute" skaliert nicht.** Eine ungefilterte globale Inbox ist bei 8 Wohnungen eine Hilfe und
bei 350 ein zweiter Posteingang, den man ebenfalls ignoriert. Sie mischt zudem Rhythmen: Ein
Wasserschaden ist heute, die Nebenkostenabrechnung ist ein Quartalsprozess.

**Kennzahlen stehen am falschen Ort.** Leerstandsquote und Rendite gehören ins
Eigentümergespräch, nicht auf den Arbeitsbildschirm um 08:15.

**Einfach- und Profimodus lösen das falsche Problem.** Ein privater Eigentümer mit acht
Wohnungen und eine Bewirtschafterin mit 350 haben nicht denselben Beruf. „Geld" statt
„Finanzen" zu schreiben überbrückt das nicht. Der Unterschied gehört ins Entitlement
(Phase 3), nicht in einen Sessionschalter.

---

## 2. Grundentscheidungen

**G1 — Vier Bereiche statt sechs.** `Arbeit · Akten · Läufe · Zahlen`, dazu Einstellungen.

**G2 — Ein Arbeitsvorrat, nicht zwei Listen.** „Heute" und „Fälle" sind dasselbe: eine
Vorgangsliste mit vorgefilterten Ansichten (Heute, Diese Woche, Wartet auf Dritte,
Liegengeblieben, Alle).

> **Umgesetzt in 4b.5 — und beinahe verletzt.** Ein Entwurf stellte den neuen Abschnitt
> «Was reisst» **neben** die bestehende Inbox. Beide sammelten einzelne Pendenzen im
> 14-Tage-Fenster; dieselbe Pendenz hätte zweimal auf einem Bildschirm gestanden. Die
> Pendenz- und Wartungsfristen-Blöcke sind deshalb aus `core/services/inbox.py` in
> `faelle/arbeitsvorrat.py` **gewandert**, nicht kopiert. Die Arbeitsteilung: EINZELNE
> datierte Vorgänge in den Arbeitsvorrat, SAMMELPOSTEN («12 Rechnungen prüfen») in die
> Inbox. `test_keine_doppelung_zwischen_inbox_und_vorrat` hält das fest.

**G3 — Der Fall ist das zentrale Objekt.** Vorgänge mit Lebenszyklus, Schritten, Frist,
Zuständigkeit und Verknüpfungen zu anderen Fällen.

**G4 — Der Zulauf ist die Startfläche.** In einem kleinen Büro beginnt der Tag mit 40
Eingängen; die Arbeit ist das Zuordnen. Der Zulauf steht links im Arbeitsbereich, nicht als
Icon in der Topbar.

**G5 — Person ≠ Mietverhältnis.** Eine Person kann nacheinander zwei Mietverhältnisse haben,
zugleich Notfallkontakt für jemand anderen und früher Bewerberin gewesen sein. Konto, Kaution,
Fristen und Nebenkosten hängen am **Mietverhältnis**; Identität, Kontaktweg und
Datenschutzrelevantes an der **Person**.

**G6 — Ein Reitersatz für alle Aktentypen.** `Stammdaten · Chronik · Finanzen · Dokumente ·
Fälle`, plus höchstens ein typeigener Reiter. Wer eine Akte bedienen kann, kann alle.

**G7 — Regeln statt Listen.** Eine Fristenliste warnt nicht. Eine Regel, die einen falschen
Kündigungstermin gar nicht durchlässt, warnt. Regeln liegen als **Daten** vor, nicht als Code.

**G8 — Zuständigkeit statt Rolle.** In einer Verwaltung mit drei Personen hat niemand nur eine
Rolle. Gefiltert wird nach Zuständigkeit für Mandat oder Liegenschaft, plus Vertretung.

> **Vertretung umgesetzt in 4b.8.** `faelle.Abwesenheit` trägt Zeitraum, Grund und
> `vertreten_durch`. Bis dahin war die Vertretung eine Absprache im Flur: Die Fälle der
> abwesenden Person blieben in ihrem Namen liegen und niemand sah sie. Eine Abwesenheit **ohne**
> Vertretung ist dabei kein Fehler, sondern eine Aussage — und wird als «ohne Vertretung»
> ausdrücklich gemeldet, statt still wie eine gedeckte auszusehen.

**G9 — Was fehlt, ist wichtiger als was da ist.** Eine Akte, die nur anzeigt, was erfasst
wurde, spart keine Zeit. Eine, die merkt, was fehlt oder nicht zusammenpasst, schon.

> Umgesetzt seit 4b.2 auf dem Mietverhältnis (`_akte_kopfzahlen()`), seit 4b.3 auf Person
> (`_person_kopf()`) und Liegenschaft (`_liegenschaft_kopf()`), seit 4b.5 auf der Fallakte.
> Offen: Objekt, Mandat, Dienstleister.

---

## 3. Informationsarchitektur

### 3.1 Arbeit

Eine Liste aller offenen Vorgänge mit vorgefilterten Ansichten. Links der **Zulauf** als
eigene Spalte, rechts der Arbeitsvorrat.

| Ansicht | Inhalt |
|---|---|
| Heute | Fällige Schritte, Termine, Freigaben, überfällige Fristen |
| Diese Woche | Alles mit Frist in den nächsten 7 Tagen |
| Wartet auf Dritte | Fälle im Wartestatus (Eigentümer, Handwerker, Behörde, Versicherung) |
| Liegengeblieben | Fälle, die die Verfallsregel ausgelöst haben |
| Alle | Vollständige Liste |

Zusätzlich: Filter nach Zuständigkeit (Person) und Mandat. **Keine Kennzahlen.**

**Die Abschnitte der Heute-Ansicht.** Der Prototyp (`mockups/konzept-struktur.html`, Screen
«Heute») nennt fünf. Seit 4b.8 sind alle fünf gebaut:

| Abschnitt (Prototyp) | in der Anwendung | Quelle |
|---|---|---|
| Was reisst | Was reisst | Fallschritte, Läufe, Pendenzen, Wartungsfristen |
| Posteingang | Zulauf | `faelle.Eingang` mit Vorschlag |
| Termine | Termine | `faelle.Termin` + abgeleitet: `Abnahmeprotokoll`, `Mietbewerbung.besichtigung_am` |
| Wartet auf mich | **Wartet auf Freigabe** | Kreditoren `neu`, Handwerker-Offerten `ausstehend`, Vertragsentwürfe |
| Vertretung | Vertretung | `faelle.Abwesenheit` |

Zwei Abweichungen vom Prototyp, beide bewusst:

- **«Wartet auf mich» heisst «Wartet auf Freigabe».** Das Datenmodell trägt das «mich» nicht:
  Weder `KreditorenRechnung` noch `HandwerkerAuftrag` führen einen Freigeber, und
  `crm.Mitgliedschaft` kennt keine Zuständigkeit je Vorgang. In einem Büro mit zwei bis fünf
  Personen ist die Warteschlange ohnehin gemeinsam — die Überschrift darf sie nur nicht als
  persönlich ausgeben.
- **Abnahmen und Besichtigungen werden abgeleitet, nicht erfasst.** Sie stehen am Vertrag und
  an der Bewerbung. Würde das Erfassen einer Abnahme zusätzlich einen `Termin` anlegen, stünde
  dieselbe Wohnungsabnahme zweimal im Tag — derselbe Fehler wie die Inbox-Doppelung in 4b.5,
  nur eine Ebene tiefer. `test_abgeleitete_termine_werden_nicht_dupliziert` schliesst das aus.

Ebenfalls weggelassen: der Verweis «Kalender» unter den Terminen — es gibt keine
Kalenderansicht, und ein Knopf ins Leere ist schlechter als keiner.

### 3.2 Akten

`Mandat › Liegenschaft › Objekt › Mietverhältnis`, quer dazu `Person` und `Dienstleister`.

### 3.3 Läufe

Wiederkehrende Verarbeitung mit Zustand: Sollstellung, Bankabgleich, Mahnlauf, Zahllauf,
Nebenkostenabrechnung, MWST, Jahresabschluss. Jeder Lauf kennt `fällig / läuft / abgeschlossen`
und **was ihn blockiert**. Ein überfälliger Lauf erscheint dadurch von selbst unter Arbeit.

### 3.4 Zahlen

Eigentümerreporting, Leerstand und Ertrag, Debitorenspiegel, Mandatsrentabilität.

---

## 4. Aktentypen

| Typ | Fixe Reiter | Typeigener Reiter |
|---|---|---|
| Mandat | Stammdaten, Chronik, Finanzen, Dokumente, Fälle | Liegenschaften |
| Liegenschaft | dieselben | Einheiten |
| Objekt | dieselben | Ausstattung (mit Lebensdauer) |
| Mietverhältnis | dieselben | Nebenkosten |
| Person | dieselben | Rollen |
| Dienstleister | dieselben | Aufträge |

Jede Akte trägt eine Kennzahlenleiste aus **vier** Werten, die zusammen die Frage beantworten
„steht diese Akte gut da". Beim Mietverhältnis: Bruttomiete, Saldo, Kaution, nächste Frist.

---

## 5. Die Fallmaschine

### 5.1 Modell

```
Fall
  nummer            F-2026-0184
  art               → Fallart (Daten, nicht Code)
  akte              generischer Bezug (Mietverhältnis, Objekt, Liegenschaft, Mandat)
  organisation      Mandantenbindung (Phase 2)
  zustaendig        Benutzer
  status            offen | wartet_auf_dritte | ruht | abgeschlossen | abgebrochen
  eroeffnet_am / abgeschlossen_am
  letzte_bewegung   für die Verfallsregel
  frist_naechste    abgeleitet aus dem aktuellen Schritt

Fallart
  schluessel        mieterwechsel | zahlungsverzug | schaden | mietzinsanpassung |
                    erstvermietung | …
  etappen           [ { nr, bezeichnung, schritte: [...] } ]
  entitlement       Funktionsschlüssel (Phase 3)

Schritt
  bezeichnung, etappe, pflicht (ja/nein)
  frist_regel       relativ ("Vertragsende − 0 Tage", "Rückgabe + 30 Tage")
  erledigt_am, erledigt_durch
  ausloeser         was beim Erledigen automatisch passiert
```

**Schrittdefinitionen sind Daten.** Sonst ist jede Prozessänderung ein Deployment. Eine
Verwaltung, die ihren Mieterwechsel um einen Schritt ergänzt, darf dafür keinen Entwickler
brauchen.

### 5.2 Verfallsregel

Ein Fall ohne Bewegung meldet sich von selbst:

- Status `wartet_auf_dritte`: nach **10 Tagen**
- sonst: nach **14 Tagen**

Er erscheint dann unter „Liegengeblieben" mit Angabe, worauf gewartet wird. Werte sind pro
Organisation einstellbar.

### 5.3 Verknüpfte Fälle

Fälle zur selben Akte kennen einander und melden Kollisionen. Der dokumentierte Fall: Ein
Zahlungsverzug erreicht Stufe 4 (Fristansetzung mit Kündigungsandrohung), das Mietverhältnis
ist aber bereits gekündigt — die Kündigung wäre gegenstandslos. Der Fall wird auf Verrechnung
gegen die Kaution umgestellt und läuft in die Endabrechnung des Mieterwechsels ein.

Kollisionsregeln gehören ins Regelwerk (Abschnitt 7), nicht in die Views.

### 5.4 Zeiterfassung

Für die Mandatsrentabilität (Abschnitt 9) wird Zeit **pro Fall** erfasst. Das ist eine
Zumutung an den Alltag und funktioniert nur, wenn es fast beiläufig geht. **Offene
Entscheidung** — siehe Abschnitt 12.

---

## 6. Zulauf

Jeder Eingang — E-Mail, Post-Scan, Portalmeldung, Beleg — wird zu genau einem der drei:

1. einer Akte zugeordnet und abgelegt,
2. Auslöser eines neuen Falls,
3. bewusst abgelegt ohne Folge.

Was übrig bleibt, ist der Arbeitsvorrat. Der Zuordnungsvorschlag stammt aus QR-Referenz,
Absenderadresse, Zahlername und Textmerkmalen. **Ein Vorschlag ohne ausreichende Sicherheit
wird als solcher gekennzeichnet — nicht geraten.**

Gelernte Regeln: Wiederkehrende Muster (etwa ein Sozialdienst, der für einen bestimmten Mieter
zahlt) werden als Regel gespeichert und greifen beim nächsten Import.

---

## 7. Regelwerk

Regeln liegen als Daten vor, **pro Kanton und pro Vertrag konfigurierbar**, mit Protokoll,
wenn eine Regel greift.

Erfasste Regelfamilien:

| Bereich | Prüfung |
|---|---|
| Kündigung Wohnraum | Frist ab **Zugang** (nicht Poststempel), gültiger Termin, Vorschlag des nächstmöglichen |
| Zahlungsverzug | Mindestfrist mit Kündigungsandrohung, danach Kündigungsfrist; Teilzahlung unterbricht nicht |
| Mietzinsänderung | Amtliches Formular, Zustellfrist vor Beginn der Kündigungsfrist, Begründung, Anfechtungsfrist |
| Anfangsmietzins | Formularpflicht je nach Kanton bei Erhöhung gegenüber dem Vormieter |
| Kaution | Höchstbetrag, Sperrkonto lautend auf den Mieter, Freigabefrist ohne Anspruchsanmeldung |
| Rückgabe | Rüge bei Rückgabe, Lebensdaueranrechnung |
| Mangel | Herabsetzungsanspruch bei eingeschränkter Nutzung |

> **Diese Regeln sind ein Entwurf aus allgemeiner Kenntnis, kein geprüftes Recht.** Vor der
> Umsetzung muss jede Regel juristisch abgesichert werden. Zusätzlich braucht es eine Antwort
> auf die Frage: **Was passiert, wenn eine Regel irrt?** Vorschlag: Regeln blockieren nie
> endgültig, sondern warnen mit Begründung und lassen ein dokumentiertes Übersteuern zu; jedes
> Übersteuern wird protokolliert.

---

## 8. Rollen und Kompetenzen

Rollen gemäss Vorgabe: **Inhaber, Verwalter, Sachbearbeiter, Lesezugriff**. Die
Mandatszuteilung begrenzt zusätzlich, **welche** Akten überhaupt sichtbar sind.

| Handlung | Inhaber | Verwalter | Sachbearbeiter | Lesezugriff |
|---|---|---|---|---|
| Akten und Fälle lesen | ✓ | ✓ | ✓ | ✓ |
| Akten bearbeiten, Fälle führen | ✓ | ✓ | ✓ | — |
| Kündigung erfassen und bestätigen | ✓ | ✓ | — | — |
| Rechnungen freigeben | ✓ | bis Limit | bis Limit | — |
| Zahllauf auslösen | ✓ | ✓ | — | — |
| Mahnlauf und Betreibung | ✓ | ✓ | — | — |
| Nebenkostenabrechnung freigeben | ✓ | ✓ | — | — |
| Mitglieder und Rollen verwalten | ✓ | — | — | — |
| Abonnement und Module ändern | ✓ | — | — | — |
| Daten exportieren | ✓ | ✓ | — | — |

**Vertretung** ist zeitlich begrenzt, nicht dauerhafte Rechteerweiterung. Sie endet
automatisch; offene Fristen bleiben bei beiden sichtbar.

**Vier-Augen-Prinzip** beim Zahllauf: erfassen und freigeben nie dieselbe Person.

Kompetenzsummen für Rechnungsfreigaben sind **pro Mandat** einstellbar und gehören in den
Verwaltungsvertrag. Vorschlag für Notfälle (Wasser, Heizung, Sicherheit): Sofortkompetenz mit
nachträglicher Meldung — solche Fälle kosten sonst mehr an Herabsetzung und Folgeschaden als
an Reparatur.

---

## 9. Externe Rollen

### 9.1 Eigentümerportal

Eigene Oberfläche ohne die vier Bereiche. Sichtbar ist ausschliesslich das eigene Mandat —
das ist zugleich der sichtbare Beweis der Mandantentrennung aus Phase 2. Inhalt: Kennzahlen,
offene Freigaben, Liegenschaften, Dokumente, Ausschüttungen, Ansprechperson.

Eine Freigabe im Portal ist derselbe Vorgang wie der Freigabeschritt im Fall — nur von der
anderen Seite bedient.

**Mandatsrentabilität** (Honorarertrag gegen erfassten Aufwand) ist eine interne Auswertung,
nicht Portalinhalt.

### 9.2 Mieterportal

Miete und Kontostand, QR-Rechnung, Schaden melden mit Fotos, Dokumente, Ansprechperson,
Notfallnummer. Eine Schadenmeldung wird unmittelbar ein Fall mit Objekt-, Raum- und Zeitbezug.

**Bewusst nicht enthalten:** Mahnstufe und Betreibungsstand (gehört in ein zugestelltes
Schreiben), Daten anderer Mieter einschliesslich Verbrauchsvergleichen, Kündigung per Klick
(Schriftform).

**Bedingung:** Ein Portal ohne zugesagte Rückmeldezeit erzeugt mehr Ärger als es löst. Die
Zusage gehört ins Konzept, nicht in die Werbung.

---

## 10. Mehrsprachigkeit

Deutsch, Französisch, Italienisch, Englisch — Oberfläche **und** Dokumentvorlagen.

Sprachwahl für ein Schreiben:

1. Korrespondenzsprache des Mietverhältnisses
2. sonst Sprache der Liegenschaft
3. sonst Sprache der Organisation

**Fehlt eine Übersetzung, hält der Versand an und meldet die Lücke.** Es wird nicht
stillschweigend auf eine andere Sprache gewechselt — bei einem Serienbrief an 171
Mietverhältnisse fällt das sonst erst beim Rückruf auf.

Amtliche kantonale Formulare werden befüllt, aber **nicht inhaltlich verändert**. Eine eigene
Fassung wäre nichtig.

Serienfelder ziehen aus Fall und Akte. Ein Detail mit Absicht: Das Feld heisst
`{{kuendigung.termin_geprueft}}` und nicht `{{kuendigung.termin}}` — eingesetzt wird der vom
Regelwerk bestätigte Termin, nicht der genannte.

Stand heute: **0 projekteigene `gettext`-Vorkommen**, kein `locale/`, keine `LocaleMiddleware`.
Deshalb die Zusammenlegung mit Phase 4b (Abschnitt 13).

---

## 11. Zuordnung der bestehenden Views

`core/views/fw/` umfasst 33 Fachmodule mit **235** öffentlichen Viewfunktionen (nachgemessen,
siehe Abschnitt 15). Die Zuordnung zur neuen Struktur:

| Modul | Views | Wird zu |
|---|---|---|
| `detailseiten` | 34 | **Akten** — verteilt auf die Reiter der sechs Aktentypen |
| `aktionen` | 32 | **Fallschritte** — je Aktion ein Schritt mit Auslöser |
| `profil` | 22 | **Akten** (Person, Mietverhältnis) und Einstellungen |
| `person` | 16 | **Akte Person** und Akte Mietverhältnis |
| `listen` | 15 | **Akten**-Listenansichten |
| `schaeden` | 14 | **Fallart Schaden** |
| `mietprozess` | 9 | **Fallart Mieterwechsel** und Erstvermietung |
| `kuendigung` | 7 | **Fallart Mieterwechsel** + Regelwerk |
| `abnahme` | 7 | **Fallart Mieterwechsel**, Schritt 5 (Vor-Ort-Modus, Phase 5) |
| `pendenzen` | 7 | **Arbeit** — geht im Arbeitsvorrat auf |
| `liegenschaft_crud` | 7 | **Akte Liegenschaft** |
| `kreditoren` | 6 | **Lauf Zahllauf** + Zulauf |
| `kautionen` | 6 | **Akte Mietverhältnis**, Reiter Finanzen |
| `vertragserstellung` | 5 | **Fallart Mieterwechsel**, Schritt 4 |
| `mietzins` | 5 | **Fallart Mietzinsanpassung** (Sammelfall) |
| `nebenkosten` | 5 | **Lauf Nebenkosten** |
| `buchhaltung` | 5 | **Läufe** und Zahlen |
| `eigentuemer_abrechnung` | 5 | **Akte Mandat** + Zahlen |
| `mahnwesen` | 4 | **Lauf Mahnlauf** + Fallart Zahlungsverzug |
| `bankabgleich` | 4 | **Lauf Bankabgleich** (1'127 Zeilen — eigene Etappe) |
| `dashboard` | 2 | **Arbeit** — Kennzahlen wandern nach Zahlen |
| `sollstellung` | 2 | **Lauf Sollstellung** |
| `benutzer` | 2 | Einstellungen · Organisation und Team |
| übrige 10 Module | je 1–3 | Akten-Reiter oder Läufe |

Diese Tabelle ist eine **erste Zuordnung auf Modulebene**. Vor Etappe 4a.5 braucht es die
Zuordnung auf Ebene der einzelnen Viewfunktion — inklusive der Frage, welche Views ersatzlos
entfallen.

---

## 12. Was gegengelesen werden muss

Punkte, die aus allgemeiner Kenntnis konstruiert sind und vom Praktiker oder juristisch
bestätigt werden müssen, bevor sie gebaut werden:

- **Das gesamte Regelwerk** (Abschnitt 7), insbesondere Kündigungstermine, Formularpflichten,
  Zustell- und Anfechtungsfristen
- **Abrechenbarkeit von Nebenkosten** — welche Positionen überwälzbar sind, hängt am Vertrag
- **Lebensdauertabelle** für die Abnahme
- **Kompetenzsummen** für Rechnungsfreigaben
- Ob **Sachbearbeitung** wirklich keine Kündigung erfassen darf
- Ob die **Zeiterfassung pro Fall** im Alltag durchhaltbar ist — davon hängt die
  Mandatsrentabilität ab
- Ob ein **Marktvergleich** (Mietzinsniveau, Aufruf-zu-Anfrage-Quote) mit belastbaren Daten
  befüllbar ist
- ~~Ob ein **gemeinsames Postfach** oder persönliche Postfächer verwendet werden~~ — seit
  dem Postfach-Umbau (Commit `bb92332`) entschieden: **ein gemeinsames Postfach je Verwaltung
  und je Zweck** (Ticket-Antworten, Rechnungseingang), eingerichtet unter
  Einstellungen › Postfächer. Der Zulauf ist damit eine geteilte Fläche. Persönliche Postfächer
  sind nicht vorgesehen und wären ein eigener Entscheid.

---

## 13. Umsetzung

### 13.1 Änderung an der Phasenvorgabe

Phase 4 wird geteilt:

| Phase | Inhalt |
|---|---|
| 3 | Abo, Module, Entitlements |
| **4a** | Struktur und Fallmaschine (dieses Dokument) |
| **4b** | Design-System **und** Mehrsprachigkeit |
| 5 | Funktionsvertiefung: Vor-Ort-Modus, Portale, Reporting, Vorlagen |
| 6 | Benutzerhandbuch |

Begründung für 4b: Design-System und i18n berühren **dieselben 173 Templates**. Getrennt
ausgeführt wird jedes Template zweimal angefasst.

Reihenfolge 3 vor 4a war vorgesehen; auf Entscheid vom 19.08.2026 wird **4a vorgezogen**. Um
zu verhindern, dass die neuen Funktionen an verstreuten `if`-Abfragen hängen, wird in 4a.0
eine Entitlement-Naht eingezogen: eine einzige Funktion `hat_funktion(organisation,
schluessel)`, vorerst mit fest hinterlegten Werten. Phase 3 füllt sie später mit echten
Abodaten, ohne dass Aufrufstellen geändert werden.

### 13.2 Etappen 4a

| Nr | Inhalt | Gate |
|---|---|---|
| 4a.0 | Entitlement-Naht `hat_funktion()`; Restarbeiten Phase 2 (L1-Schutztest, 3 Modelle ohne Organisations-FK) | Isolationstests grün, L1-Gegenprobe schlägt fehl wie erwartet |
| 4a.1 | App `faelle`: Modelle Fall, Fallart, Schritt; Schrittdefinitionen als Daten | Fall anlegbar, Schritte abarbeitbar, Mandantentrennung getestet |
| 4a.2 | Regelwerk als Daten, beginnend mit Kündigungsterminen; Übersteuern mit Protokoll | Regel greift, Übersteuern protokolliert, Tests je Regel |
| 4a.3 | Zulauf: Eingang, Zuordnungsvorschlag, gelernte Regeln | Eingang wird zu Akte oder Fall, Vorschlag ohne Sicherheit wird gekennzeichnet |
| 4a.4 | Läufe erhalten Zustand und Blockierungsgründe | Überfälliger Lauf erscheint unter Arbeit |
| 4a.5 | Aktenrahmen mit einheitlichem Reitersatz; bestehende Views einhängen | Alle sechs Aktentypen erreichbar, keine Funktion verloren |
| 4a.6 | Navigation auf vier Bereiche; alte Navigation entfernen | Keine toten Pfade, Redirects gesetzt |
| 4a.7 | Rückwirkende Fallerzeugung aus dem Bestand (offene Kündigungen, Schäden, Mahnfälle) | Bestandsvorgänge erscheinen als Fälle mit korrektem Schritt |

Vorgehen additiv: Die 235 bestehenden Views laufen unverändert weiter, während die Maschine
daneben entsteht. Erst in 4a.6 wird umgehängt.

### 13.3 Etappen 4b

Anders als 4a war 4b nicht vorab in Etappen geschnitten — die Schritte entstanden aus dem
Vergleich von Server und Prototyp. Nachgetragen, damit der Stand ablesbar ist:

| Nr | Inhalt | Stand |
|---|---|---|
| 4b.0 | Aktenkopf und Reiterleiste aus Tokens statt Tailwind-Utilities; Komponentenschicht in `base.html` | erledigt (`b0e3757`) |
| 4b.1 | Konzeptpalette Petrol in `:root`, beide Dunkelblöcke; Wächter `test_palette.py` | erledigt (`ce92c88`) |
| 4b.2 | Kennzahlen, Chips und Hinweise als **gerechnete Zustände** (`_akte_kopfzahlen`); Stammdaten in vier Gruppen | erledigt (`301e81b`) |
| 4b.3 | **Reitersatz und Aktenkopf** der vier übrigen Detailseiten — Schaden, Person und Liegenschaft erledigt, **Objekt** offen | **teilweise** |
| 4b.4 | **Die Bereichsinhalte** auf die Komponentenschicht — Person und Liegenschaft erledigt, Schaden (104) und Vertrag (177) offen | **teilweise** |
| 4b.5 | **Phase 4a wird bedienbar**: `/neu/arbeit/` (fünf Ansichten + Zulauf-Spalte), `/neu/faelle/<id>/` (Fallakte mit Verfallsregel), `/neu/laeufe/`, `/neu/zulauf/`; Arbeitsvorrat auf der Startseite | erledigt |

> **Warum 4b.5 dazwischenkam.** `Fall`, `Fallschritt`, `Eingang`, `Zuordnungsregel`, `Lauf`
> und `Blockade` waren nach vier Etappen vollständig gebaut und vollständig getestet — und
> hatten **null Views, null URLs, null Templates**. Ein grüner Modelltest sagt nichts darüber,
> ob ein Mensch die Sache je zu Gesicht bekommt. Die vier Seiten sind der Beleg, dass Phase 4a
> trägt; die Verfallsregel aus Abschnitt 5.2 wird dort zum ersten Mal angezeigt.

Der Wächter für 4b.3 steht bereits: `faelle/test_reiter_panels.py::test_umstellung_erzeugt_nur_
erreichbare_reiter` ist als `expectedFailure` markiert und nennt in seiner Meldung jedes
fehlende Panel je Vorlage. Er ist damit die Arbeitsliste — und schlägt um, sobald 4b.3 fertig
ist, weil Django einen unerwarteten Erfolg als Fehlschlag meldet.

> **Richtigstellung, 20.08.2026.** Bis heute stand in Zeile 4b.3 «Schaden und Person erledigt»
> und in 4b.4 «die 178 Farbklassen **der Vertragsakte**». Beides war zu grosszügig. «Erledigt»
> meinte nur Reitersatz und Kopf; die Reiter*inhalte* waren unberührt. Eine Messung je Bereich
> ergab: **drei von achtzehn** Bereichen waren gestalterisch umgestellt, **sechs** enthielten
> keine einzige Komponentenklasse. Und der Rückstand lag nicht nur beim Vertrag — 177 Stellen
> dort, 106 im Schaden, 171 bei Person, zusammen **454**. Kein Wächter hat das gemeldet, weil
> keiner nach dem Aussehen eines Bereichs fragte; alle prüften die Verdrahtung. Diese Lücke
> schliesst `faelle/test_bereichsgestaltung.py`: Er zählt je Bereich und hält jede Zahl unter
> ihrem Deckel — 0 für die fertigen, der heutige Stand für die offenen. Die Deckel dürfen nur
> sinken.

### 13.4 Neue Abhängigkeiten

Keine erforderlich. DocuSeal (Signatur) und die bestehende OCR-Kette decken die
Modulanforderungen ab. Sollte sich in 4a.3 zeigen, dass die Zuordnungsqualität ohne
zusätzliche Bibliothek nicht reicht, wird das als Antrag im PR vorgelegt und **nicht**
umgesetzt.

---

## 14. Prototypen

Unter `mockups/` liegen sieben klickbare HTML-Dateien. Sie sind Diskussionsgrundlage für
Aufbau und Abläufe, kein Zielbild der Gestaltung.

> **Eine Ausnahme, seit 4b.1.** Für die **Farben** gilt der Satz nicht mehr:
> `core/tests/test_palette.py` pinnt die Palette aus `konzept-v3.html` fest und behandelt jede
> Abweichung als Konzeptänderung. Bis 4b.1 stand hier ein Widerspruch — der Test nannte
> `KONZEPT-UI.md` als Quelle, das Dokument führte aber gar keine Palette. Sie steht jetzt in
> Abschnitt 16. Layout, Abstände und Wortlaut der Prototypen bleiben unverbindlich.

| Datei | Inhalt |
|---|---|
| `design-varianten.html` | Vier Gestaltungsrichtungen auf denselben Screens (Phase 4b) |
| `konzept-struktur.html` | Erste Fassung der Architektur: Arbeit, Fälle, Akte, Läufe |
| `konzept-v2.html` | Fristenwächter, Vor-Ort-Modus, Mandatscockpit |
| `konzept-v3.html` | Aktentypen: Mietverhältnis mit Reitern, Person, Objekt, Liegenschaft, Dienstleister |
| `konzept-v4.html` | Nebenkostenlauf, Bankabgleich, Bewerbervergleich, Eigentümerportal, Abo |
| `konzept-v5.html` | Datenübernahme, Mieterportal, Mietzinsanpassung, Kreditoren, Organisation |
| `konzept-v6.html` | Fall im Detail, Schadensfall, Vermarktung, Reporting, Vorlagen |

Alle Zahlen und Namen darin sind erfunden.

---

## 15. Richtigstellung zum Ist-Zustand

Vorrang des Bestands: Wo dieses Konzept den Code beschreibt und der Code etwas anderes sagt,
gilt der Code. Nachgemessen am 19.08.2026 auf `claude/fairwalter-rebuild`, Stand `bb92332`.
Die Zahlen im Text oben sind bereits berichtigt; hier steht, **was** gemessen wurde und
**wie**, damit die nächste Prüfung nicht wieder schätzt.

| Aussage im Entwurf | Gemessen | Folge |
|---|---|---|
| `core/views/fw/` = 33 Module, **rund 253** Viewfunktionen | 33 Fachmodule (dazu `__init__.py` und `_basis.py`), **235** öffentliche Funktionen auf Modulebene; mit privaten Helfern 279 | Text auf 235 korrigiert |
| Modultabelle in Abschnitt 11, Zeile für Zeile | **stimmt für jedes aufgeführte Modul** — die Tabelle summiert selbst auf 235 | Tabelle unverändert |
| „übrige **11** Module" | **10**: `eigentuemer` 3, `mwst` 3, dazu `anlagen`, `assets`, `bankkonten`, `debitor_qr`, `dienstleister`, `dokumente`, `hypotheken`, `kommunikation` mit je 1 | auf 10 korrigiert |
| **183** Templates | **173** projekteigene: 101 unter `fw/`, 45 unter `core/`, 7 direkt in `core/templates/`, 5 E-Mail-Vorlagen, 4 Dossier, 11 Admin-Overrides | auf 173 korrigiert |
| 0 `gettext`, kein `locale/`, keine `LocaleMiddleware` | **bestätigt**, alle drei | — |
| `bankabgleich` = 1'127 Zeilen | **bestätigt** | — |
| `core/navigation.py`: 6 Bereiche in zwei Modi | **bestätigt** (`nav_gruppen(modus)`, `UI_MODI = ('einfach', 'profi')`) | — |
| 4a.0: „3 Modelle ohne Organisations-FK" | **bestätigt**, und benennbar: `core.SicherheitsEreignis`, `core.ZweiterFaktor`, `core.Wiederherstellungscode`. Von 63 eigenen Modellen hat sonst jedes den Bezug; `crm.Organisation` ist der Mandant selbst und zählt nicht mit | Namen ergänzt |
| Rollen Inhaber · Verwalter · Sachbearbeiter · Lesezugriff | **bestätigt** (`TEAM_ROLLEN`) | — |
| 13.3: keine neuen Abhängigkeiten nötig, DocuSeal und OCR vorhanden | **bestätigt** (`core/services/docuseal_service.py`, Groq-Belegerkennung) | — |

**Messweg zum Nachvollziehen.** Viewfunktionen über den Syntaxbaum, nicht über `grep` — ein
`def` in einem Docstring oder in einem Kommentar zählt sonst mit:

```bash
python3 - <<'PY'
import ast, pathlib
gesamt = 0
for p in sorted(pathlib.Path('core/views/fw').glob('*.py')):
    baum = ast.parse(p.read_text())
    fns = [k for k in baum.body
           if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
           and not k.name.startswith('_')]
    gesamt += len(fns)
    print(f'{p.stem:28} {len(fns):4}')
print('gesamt:', gesamt)
PY

find . -name '*.html' -path '*/templates/*' -not -path './.git/*' | wc -l
```

**Zwei Bemerkungen, die über die Zahlen hinausgehen.**

Die Modultabelle in Abschnitt 11 war richtig, die Summe darüber nicht. Das ist der harmlosere
Fall — er fällt beim Nachrechnen auf. Der gefährlichere wäre umgekehrt gewesen: eine plausible
Summe über einer Tabelle, die einzelne Module falsch einordnet. Die Zuordnung selbst ist
deshalb **nicht** geprüft; sie ist eine Absicht, keine Messung. Abschnitt 11 sagt das bereits
(„erste Zuordnung auf Modulebene"), und das bleibt so bis 4a.5.

Die Zahlen altern. `core/views/fw/` wächst in Phase 4a additiv weiter (13.2: „laufen
unverändert weiter, während die Maschine daneben entsteht"), 173 Templates werden mehr. Wer
sie im Text fortschreibt, ohne neu zu messen, baut denselben Fehler wieder ein. Sinnvoller ist,
sie beim nächsten Etappenabschluss neu zu messen — der Messweg oben steht dafür da.

---

## 16. Gestaltung

Nachgetragen am 20.08.2026. Bis dahin war die Gestaltung nur in den Prototypen und im Code
belegt; `core/tests/test_palette.py` verwies auf dieses Dokument, das dazu nichts sagte.

### 16.1 Palette

Verbindlich, geprüft von `core/tests/test_palette.py`. Definiert in `core/templates/fw/base.html`
unter `:root`, im `@media (prefers-color-scheme:dark)`-Block und unter `:root[data-theme="dark"]`.

| Token | Hell | Dunkel | Rolle |
|---|---|---|---|
| `--ds-brand` | `#0f6f6a` | `#4fb3aa` | Petrol, Markenfarbe |
| `--ds-brand-600` | `#0b5450` | `#6fcac2` | gedrückter Zustand |
| `--ds-brand-soft` | `#d9efed` | `#0f2f2e` | Fläche hinter Markenfarbe |
| `--ds-ink` | `#0e2227` | `#e4edee` | Fliesstext |
| `--ds-muted` | `#4c6169` | `#a8c0c5` | Zweitrangiges |
| `--ds-faint` | `#5c757c` | `#8ba4aa` | Beschriftungen |
| `--ds-line` | `#dde6e8` | `#22404a` | Trennlinien |
| `--ds-radius` / `-sm` | `10px` / `7px` | dieselben | Geometrie, im Dunkeln unverändert |

Dazu `good` / `warn` / `crit` / `info`, jeweils mit `-soft`-Fläche.

**Eine bewusste Abweichung vom Prototyp.** Dessen `--ds-faint` (`#7f959c`) erreicht auf Weiss
nur **3.14:1** und verfehlt WCAG AA; die Prototypen entstanden ohne Kontrastprüfung. Hier steht
`#5c757c` — derselbe Petrolton eine Stufe dunkler, **4.89:1**. Jeder andere Wert liegt ohnehin
über AA; der knappste ist `--ds-warn` auf `--ds-warn-soft` mit **4.56:1**.

Wer die Palette ändert, ändert das Konzept: Tabelle hier, Werte in `base.html` und Erwartung in
`test_palette.py` gehören zusammen. Der Test rechnet den Kontrast selbst nach und hat dafür eine
eigene Gegenprobe (`test_der_kontrastrechner_stimmt`).

### 16.2 Komponentenschicht

Alle Klassen `fw-`-präfixiert, alle Farben aus Tokens. `core/tests/test_ds_tokens.py` prüft, dass
jedes benutzte `var(--ds-…)` definiert ist, dass kein Token tot herumsteht und dass **beide**
Dunkelblöcke dieselben Farben führen.

| Klasse | Zweck |
|---|---|
| `fw-aktenkopf` | Rahmen um Kopf, Kennzahlen und Reiter |
| `fw-akte-oben` / `-bild` / `-typ` / `-pfad` / `-rechts` | Kopfzeile: Symbol, Typ, Titel, Pfad, Aktionen |
| `fw-kzn` | Kennzahlenleiste, vier Spalten |
| `fw-reiter` | Reiterleiste; aktiver Reiter trägt `hier` |
| `fw-gruppe` / `fw-dz` / `fw-dl` / `fw-dv` | Leseansicht: Gruppentitel, Zeile, Bezeichnung, Wert |
| `fw-aufklapp` | Erfassen in einer Leseansicht — zugeklappt bis gebraucht |
| `fw-hinweis` | „Was auffällt", eingefärbt nach Dringlichkeit |
| `fw-statuswahl` | Umschalter Entwurf · Aktiv · Inaktiv |

Für die **Bereichsinhalte** kamen mit 4b.4 vier Bausteine dazu. Sie fehlten, und ihr Fehlen war
der Grund, warum die Reiterinhalte weiter Tailwind trugen: Für Karte, Zeile und Tabelle gab es
Komponenten, für Beträge, Formularfelder und Symbolknöpfe nicht.

| Klasse | Zweck |
|---|---|
| `fw-betrag` | Geldbetrag, Ziffern gleich breit; `.crit` / `.good` / `.mut` als Ton |
| `fw-feld` | Eingabefeld, Auswahl, Textfeld — erbt die Schrift des Fliesstexts |
| `fw-ikon` als `<button>` | Symbolknopf; `.mut` im Ruhezustand, `.gefahr` färbt erst beim Darüberfahren |
| `fw-menuzeile` / `fw-menutrenner` | Zeile in einem Aktionsmenü («Mehr»), `.warn` / `.crit` nach Tragweite |

Geprüft von `faelle/test_bereichsgestaltung.py` — er zählt je Bereich, wie viele Tailwind-Farb\-
klassen übrig sind, und lässt die Zahl nur sinken. **Gemessen wird Farbe, nicht Raster:**
`flex`, `gap-2` und `lg:col-span-2` bleiben Tailwind, die Komponentenschicht regelt sie nicht.

**Der Pfad führt eine Angabe je Zeile** (`fw-pz`), Beschriftungen ausgerichtet. Als Kette mit
`›` und `·` brach er bei langen Objektnamen an beliebiger Stelle um.

### 16.3 Zustände statt Felder

Die Umsetzung von **G9**. Der Aktenkopf zeigt nicht, was in der Datenbank steht, sondern was
daraus folgt. Gerechnet in `_akte_kopfzahlen()`, geprüft von `faelle/test_akte_zustaende.py`.

**Kennzahlen der Liegenschaft** (seit 4b.3): Vermietung (belegt/gesamt, Quote), Soll/Monat,
Bruttorendite (mit dem Wert, auf dem sie rechnet) und die nächste Frist — Titel **ungekürzt**.
Chips sind gerechnet: «2 von 5 leer» statt eines Statusfelds. Hinweise: fehlender Verkehrswert,
überfällige Wartungsfrist, keine Notfallkontakte — jeder mit Ziel. Nicht gebaut sind der
Prototyp-Chip «Sanierung geplant» und die Kennzahl «Rücklagen»: `portfolio.Liegenschaft` führt
weder einen Sanierungsstatus noch einen Erneuerungsfonds.

**Kennzahlen des Mietverhältnisses** — die vier aus Abschnitt 4:

| Feld | Zeigt | Fusszeile |
|---|---|---|
| Bruttomiete | netto + NK | die Aufteilung |
| Saldo Mieterkonto | offener Betrag | Monat der ältesten offenen Position, Mahnstufe |
| Kaution | Betrag oder „keine" | Sperrkonto / Versicherer, Anzahl Monatsmieten |
| Nächste Frist | Datum | Titel der Frist, **ungekürzt** |

**Chips** sind gerechnet, nicht abgeschrieben: „2 Monatsmieten offen" statt des Statusfelds,
„Senkungsanspruch offen" aus `Mietvertrag.mietzinspotenzial`.

**Hinweise** — Regel: *jeder Hinweis führt zu einer Handlung.* Ein Hinweis ohne Ziel ist eine
Beschwerde; `test_jeder_hinweis_fuehrt_zu_einer_handlung` hält das fest. Heute zwei:
offener Senkungsanspruch, vereinbarte aber unbestätigte Kaution.

Ein dritter („Referenzzins-Basis fehlt") war entworfen und wurde beim Bauen entfernt:
`basis_referenzzinssatz` ist NOT NULL mit Vorgabewert, die Bedingung konnte nie zutreffen.

### 16.4 Die Palette unter Tailwind

Bis 4b.5 war die Anwendung **zweifarbig**: Die Aktenseiten liefen auf der Komponentenschicht
in Petrol, alles andere — Seitenleiste, Topbar, Listen, Formulare, Berichte — auf fest
verdrahteten Tailwind-Klassen in Indigo. Gemessen am 20.08.2026: **7490 Farbklassen in 176
Vorlagen** (4959 `slate`, 1250 `indigo`, dazu rose, emerald, amber).

Von den beiden Wegen, die hier standen — «Klassen schrittweise auf Tokens umstellen, oder
Tailwind eine Petrol-Palette unterschieben» — ist der **zweite** umgesetzt: `tailwind.config`
in `base.html` definiert die Farbrampen um. Aus `bg-indigo-600` wird die Markenfarbe, aus
`text-slate-500` das petrolgetönte Grau. Die Klassennamen bleiben; sie zeigen woanders hin.

**Die Rampen hängen an den Tokens.** Wo eine Stufe einen Token trifft, steht derselbe Wert:

| Tailwind | Token | Wert |
|---|---|---|
| `indigo-600` | `--ds-brand` | `#0f6f6a` |
| `indigo-700` | `--ds-brand-600` | `#0b5450` |
| `indigo-100` | `--ds-brand-soft` | `#d9efed` |
| `slate-200` | `--ds-line` | `#dde6e8` |
| `slate-500` | `--ds-faint` | `#5c757c` |
| `slate-600` | `--ds-muted` | `#4c6169` |
| `slate-900` | `--ds-ink` | `#0e2227` |
| `emerald-600` / `-50` | `--ds-good` / `-soft` | `#166534` / `#e0f2e5` |
| `amber-600` / `-50` | `--ds-warn` / `-soft` | `#a35a09` / `#fbeeda` |
| `rose-600` / `-50` | `--ds-crit` / `-soft` | `#b32133` / `#fbe6e9` |
| `sky-600` / `-50` | `--ds-info` / `-soft` | `#0b5c8f` / `#e0eff8` |

Ohne diese Bindung wären es wieder zwei Paletten, nur beide petrolfarben. `gray`/`zinc` folgen
`slate`, `green`/`orange`/`red`/`blue` ihren semantischen Geschwistern — sie werden im Bestand
gleichbedeutend benutzt. **Rot bleibt Rot und Grün bleibt Grün:** Eine Warnung in Petrol wäre
keine Warnung mehr; angeglichen ist nur die Sättigung.

Geprüft von `core/tests/test_tailwind_palette.py`: Bindung an die Tokens, Helligkeitstreppe je
Rampe, Kontrast der gebrauchten Textfarben, Gleichlauf der Zwillingsfamilien.

**Was das nicht löst: den Dunkelmodus.** Tailwind-Klassen sind statisch — `bg-white` bleibt
weiss, auch wenn die Tokens umschalten. Das war vorher so und ist es weiterhin. Der Weg dorthin
ist die Komponentenschicht; die Aktenseiten gehen ihn bereits.

### 16.5 Was hier bewusst nicht steht

Der **Aufbau** ausserhalb der Aktenseiten. Die Palette gilt seit 4b.6 überall (16.4) — Farbe ist
damit erledigt. Karten, Zeilen, Tabellen und Formulare der übrigen Seiten laufen aber weiter auf
Tailwind-Utilities statt auf `fw-card`, `fw-zeile`, `fw-table`, `fw-feld`. Das ist kein
Farbproblem mehr, sondern eines der Bausteine: Abstände, Radien, Schatten und Zustände weichen
von Seite zu Seite ab.

> **Richtigstellung, 20.08.2026.** Hier stand, das Erscheinungsbild ausserhalb des Aktenkopfs sei
> ungeregelt, mit „**1412 Stellen** Indigo in 131 von 172 Vorlagen". Die Zahl war zu eng gefasst:
> Sie zählte nur `indigo`. Über alle Farbfamilien waren es **7490 Klassen in 176 Vorlagen** —
> 4959 davon `slate`. Genau diese Grössenordnung hat die Entscheidung in 16.4 erzwungen: 7490
> Einzeländerungen sind kein Weg, eine Palettenumdefinition schon.
