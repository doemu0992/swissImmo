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

> **Die Vorgabe ist «Heute» — bewusst.** Die Startseite zeigte vorher 14 Tage voraus; seit
> 4b.13 steht sie in der Ansicht «Heute» und zeigt nur, was heute oder früher fällig ist.
> Was in 8 bis 365 Tagen ansteht, erscheint damit weder unter «Heute» noch unter «Diese
> Woche» (7 Tage), sondern erst unter «Alle». Am 21.08.2026 ausdrücklich so bestätigt: «Diese
> Woche» bleibt bei 7 Tagen, die Lücke ist gewollt. Die Zähler an den Reitern machen den
> Rest sichtbar, ohne dass man die Ansicht wechseln muss.

Zusätzlich: Filter nach Zuständigkeit (Person) und Mandat.

> ~~**Keine Kennzahlen.**~~ **Präzisiert in 4b.13.** Die Regel war gegen die vier Kacheln der
> alten Startseite gerichtet — Mietertrag-Diagramm, Portfolio-Donut, Belegung, Leerstandsliste.
> Alle vier zeigten den **Bestand** und verdrängten die Arbeit; sie sind ersatzlos entfallen.
> An ihrer Stelle steht ein schmaler vierteiliger Streifen, der **Vergleiche** trägt:
> Zahlungseingang und Leerstand je gegen den Vormonat, dazu Ausstände und offene Fälle.
> Es gilt also: Kennzahlen auf der Arbeitsfläche **nur schmal und nur mit Vergleich** —
> «Leerstand 4.8 %» ist eine Zahl, «steigt den dritten Monat in Folge» eine Information.
> Alles Ruhige steht im zugeklappten Block «Lage des Bestands» und erscheint dort
> ausdrücklich **nicht**, solange es nicht abweicht. Der Wächter dazu heisst
> `faelle/test_arbeitsvorrat.py::SeitenTests::test_die_kennzahlen_sind_ein_schmaler_streifen_und_keine_kacheln`.

> **Eine Arbeitsfläche, nicht zwei (4b.13).** Bis dahin führten `/neu/` und `/neu/arbeit/`
> dieselben Abschnitte nebeneinander; die Ansichten oben gab es nur auf der zweiten, die
> aber niemand ansteuerte. Beide sind zusammengeführt — die Ansichten stehen auf `/neu/`,
> `/neu/arbeit/` leitet dorthin um und nimmt den `ansicht`-Parameter mit.

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
| Schaden | dieselben | Handwerker & Kosten |

> **Der Schaden fehlte in dieser Tabelle** — bemerkt beim Bauen von 4b.12. `faelle/akten.py`
> führt ihn seit Etappe 5a als vollwertigen Aktentyp, und seine Detailseite ist seit 4b.3
> umgestellt. Die Tabelle nannte sechs Typen, das Register sieben. Vorrang des Bestands: Der
> Code hatte recht, das Konzept war unvollständig.

Jede Akte trägt eine Kennzahlenleiste aus **vier** Werten, die zusammen die Frage beantworten
„steht diese Akte gut da". Beim Mietverhältnis: Bruttomiete, Saldo, Kaution, nächste Frist.

> **Stand nach 4b.12: alle sieben gebaut.** Die Kennzahlen je Typ, wie sie tatsächlich
> gerechnet werden:
>
> | Typ | Kennzahlenleiste | Gebaut in |
> |---|---|---|
> | Mietverhältnis | Bruttomiete · Saldo · Kaution · nächste Frist | 4b.2 |
> | Schaden | (Kopf ohne Leiste) | 4b.3 |
> | Person | (Kopf ohne Leiste — Konto, Saldo und Kaution hängen am Mietverhältnis, G5) | 4b.3 |
> | Liegenschaft | Vermietung · Soll/Monat · Bruttorendite · nächste Frist | 4b.3 |
> | Objekt | Vermietung · Soll/Monat · Fläche · Ausstattung | 4b.11 |
> | Mandat | Liegenschaften · Soll/Monat · Honorarsatz · Auszahlungen | 4b.12 |
> | Dienstleister | offene Aufträge · Aufträge gesamt · Kosten laufendes Jahr · Schlüssel | 4b.12 |
>
> Die Person trägt bewusst keine Leiste — vier Zahlen «zur Person» wären Summen, die anderswo
> schon stehen. `AktenkopfTests.KOPF_OHNE_KENNZAHLEN` hält diese Ausnahme fest und prüft, dass
> sie benannt bleibt statt sich stillschweigend auszubreiten.

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

> **Stand nach 4b.10 — gebaut, aber nur eine Regelfamilie rechnet.**
> Von den sieben Familien oben ist **eine** umgesetzt: der Kündigungstermin. Drei weitere
> (`zahlungsfrist`, `mietzins_zustellung`, `kaution_hoechstbetrag`) stehen als Regelart im
> Datenmodell und lassen sich erfassen — `faelle.regelwerk.pruefen` wirft für sie
> `NotImplementedError`, und die Verwaltung schreibt an die Regel ausdrücklich «prüft noch
> nichts». Das ist die einzige ehrliche Darstellung: Eine erfassbare Regel, die stillschweigend
> nichts täte, wäre schlimmer als gar keine, weil sie wie eine Absicherung aussieht.
>
> Der vorgeschlagene Umgang mit dem Irrtum ist umgesetzt, und zwar strenger als vorgeschlagen:
>
> | Frage | Antwort im Code |
> |---|---|
> | Blockiert eine Regel? | Nur wenn `verbindlichkeit = sperre` **und** der Regelsatz als `geprueft` gekennzeichnet ist. `faelle.regelwerk.sperrt()` prüft beides. |
> | Was tut eine ungeprüfte Regel? | Sie warnt. Ausgeliefert wird ungeprüft, also warnt zunächst alles. |
> | Wie wird übersteuert? | `Regelanwendung.uebersteuern(benutzer, begruendung)` — ohne Begründung wirft die Methode, die Oberfläche verlangt das Feld. |
> | Wie findet man die Fälle einer irrigen Fassung? | Jede Anwendung hält den **Stand** der Regel fest, auch die ohne Beanstandung. `/neu/regelwerk/protokoll/?stand=JJJJ-MM-TT` grenzt die Kohorte ab. |
> | Wer legt Regeln an? | `/neu/regelwerk/`, Rolle Verwalter oder Inhaber. `manage.py regelwerk_grundsatz` legt einen Entwurf an — **ohne** ortsübliche Termine, weil die kantonal verschieden sind; dann gilt, was im einzelnen Vertrag steht. |
>
> Was weiterhin gegengelesen werden muss, steht unverändert: die **Inhalte**. Der Bau stellt
> nur sicher, dass eine Berichtigung eine Eingabe ist und keine Auslieferung — und dass jede
> falsch entschiedene Kündigung nachträglich auffindbar bleibt.

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
| `detailseiten` | 34 | **Akten** — verteilt auf die Reiter der sieben Aktentypen |
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
| 4b.6 | **Die Petrol-Palette unter Tailwind** (16.4): `tailwind.config` definiert die Farbrampen um, statt 7490 Klassen einzeln zu ändern | erledigt — Lücken in 4b.9 |
| 4b.7 | Die fehlenden Abschnitte der Heute-Ansicht: **Termine** und **Wartet auf Freigabe**, gebaut als `fw/_arbeitsvorrat_abschnitte.html` und von Startseite und Arbeit-Seite eingebunden | erledigt |
| 4b.8 | **Termin- und Abwesenheitsmodul**: `faelle.Termin` und `faelle.Abwesenheit`, `/neu/termine/`, `/neu/abwesenheiten/`; damit stehen alle fünf Abschnitte aus 3.1 | erledigt |
| 4b.9 | **Die drei Flächen, die 4b.6 verfehlt hat**: Seitenleiste, Dunkelmodus, eingebettete Hüllen; Palette als Baustein; Farbton-Wächter über die ganze Datei | erledigt |
| 4b.10 | **Der Fristenwächter wird angeschlossen**: `faelle/regelwerk.py` bekommt Aufrufer, Verwaltung, Protokoll und Übersteuerung; dazu der Erreichbarkeits-Wächter und die Navigation für 4b.5–4b.10 | erledigt |
| 4b.11 | **Die Objektakte** — der letzte umzustellende Aktentyp: Aktenkopf, acht Reiter auf sechs, neuer Bereich «Fälle»; Bereichsinhalte von Objekt (478→164), Vertrag (179→98) und Schaden (109→59) | erledigt |
| 4b.12 | **Mandats- und Dienstleisterakte** — die beiden Aktentypen aus dem Register, die überhaupt keine Detailseite hatten | erledigt |
| 4b.13 | **Zwei Startflächen werden eine**: `/neu/` führt die fünf Ansichten, dazu Lage-Streifen mit Vormonatsvergleich, Mandate nach Auffälligkeit und «Was abweicht»; `/neu/arbeit/` leitet um | erledigt |
| 4b.14 | **Anzeigestatus des Mietvertrags**: `Mietvertrag.anzeige_status` — eine abgelaufene Kündigung gilt als beendet, in Liste, Filter, Aktenkopf und Statuspille; `status` und die Sollstellung bleiben unberührt | erledigt |
| 4b.15 | **Liegenschaftsliste: Befunde statt Bestand** — eine Zeile je Objekt statt einer Karte, sortiert nach Befund, mit Kennzahlenstreifen und Filterleiste; Leerstandsregel in `faelle/liegenschaften.py` | erledigt |
| 4b.16 | **Liegenschaftsbudget**: `portfolio.Liegenschaftsbudget` je Liegenschaft und Jahr, Befund «Unterhalt über Plan / überschritten» in Liste UND Akte aus derselben Funktion, Erfassung im Reiter Finanzen; Bruttorendite weicht im Aktenkopf | erledigt |
| 4b.17 | **Objektliste nach G9**: Befunde je Einheit (leer seit wann, wird frei ab, kein Mietzins, nicht ausgeschrieben), Gruppen nach Befund geordnet statt nach Alphabet, eine Darstellung statt zwei; `KonsistenzTests` hält Objekt- und Liegenschaftsliste auf derselben Leerstandsregel | erledigt |
| 4b.18 | **Schadensliste nach G9**: Befunde je Meldung (ungelesen, kein Auftrag, Freigabe ausstehend, Liegenbleiber, Melder ohne Rückmeldung), vier Arbeitssichten statt sieben Statuschips, sortiert nach Befund statt nach Eingang | erledigt |
| 4b.20 | **«Assets» aufgelöst**: Geräte kommen in die bestehende Ersatzplanung (Kategorienbrücke zur Lebensdauertabelle), die doppelten `fw_asset_*`-CRUD-Pfade entfallen, `/neu/assets/` wird Weiterleitung | erledigt |

> **Warum 4b.12 nötig war.** `faelle/akten.py` führt **sieben** Aktentypen. Nach 4b.11 hatten
> fünf davon Aktenkopf und Reitersatz. Zwei hatten keine Seite: Das Mandat kannte nur Liste,
> Formular und drei Spezialseiten (Abrechnung, Kontokorrent, Auszahlung) — wer wissen wollte,
> was zu einem Eigentümer gehört, musste vier Seiten zusammensuchen. Der Dienstleister hatte
> Liste und Formular; seine Aufträge hingen einzeln an ihren Schadensmeldungen und waren
> nirgends zusammen zu sehen.
>
> Zwei Dinge sind dabei **nicht** entstanden, beide mit Grund. Die **Mandatsrentabilität** aus
> `konzept-v2.html` setzt Zeiterfassung pro Fall voraus; der Prototyp sagt dazu selbst, das sei
> «eine Zumutung an den Alltag» und nur vom Büro selbst zu entscheiden. Eine Kennzahl aus
> geschätzten Stunden wäre schlimmer als keine — der Aktenkopf zeigt an ihrer Stelle, was
> wirklich bekannt ist: Honorarsatz, verwaltete Liegenschaften, Sollmiete. Und **Dokumente am
> Dienstleister** gibt es nicht, weil `crm.Handwerker` keine Dokumentenbeziehung führt; der
> Bereich sagt das, statt einen Platzhalter zu zeigen.
>
> Nebenbefund aus den Tests: `HandwerkerAuftrag.beauftragt_am` trägt `auto_now_add=True`. Ein
> nachträglich erfasster Auftrag lässt sich damit **nicht** auf sein wirkliches
> Beauftragungsdatum setzen — die Jahreszahlen der Dienstleisterakte folgen dem Erfassungs-,
> nicht dem Auftragsdatum.

> **Warum 4b.13 dazwischenkam — und welche Konzeptregel dabei fällt.** Es gab **zwei
> Startflächen mit derselben Aufgabe**: `/neu/` mit «Was reisst», «Zulauf» und vier
> Kennzahlkacheln aus der Vorgängerzeit, und `/neu/arbeit/` (aus 4b.5) mit denselben zwei
> Abschnitten plus den Ansichten. Die ältere gewann, weil sie unter `/neu/` lag — und der
> Arbeitsvorrat berechnete `av_termine`, `av_freigaben`, `av_vertretung` und `av_liegezeit`,
> von denen dort **keiner** angezeigt wurde. Aus 4b.7 und 4b.8 war also gebaut, was auf der
> meistbesuchten Seite nicht ankam.
>
> Damit fällt eine Regel aus Abschnitt 3.1: dort stand wörtlich «**Keine Kennzahlen**» auf der
> Arbeitsfläche. Sie war gegen die vier alten Kacheln gerichtet, die den *Bestand* zeigten und
> die Arbeit verdrängten. Die Kacheln sind ersatzlos weg; an ihrer Stelle steht ein
> vierteiliger Streifen, der **Vergleiche** trägt — Zahlungseingang und Leerstand je gegen den
> Vormonat. Die Regel gilt sinngemäss weiter, präziser gefasst: Kennzahlen dürfen auf der
> Arbeitsfläche stehen, wenn sie schmal sind und einen Vergleich tragen. Der Test heisst
> entsprechend nicht mehr `test_arbeit_zeigt_keine_kennzahlen`, sondern
> `test_die_kennzahlen_sind_ein_schmaler_streifen_und_keine_kacheln` und trägt die Begründung
> in seinem Docstring.
>
> **Was beim Bauen auffiel und nicht im Auftrag stand:** Zwei Stellen der neuen Lage rechneten
> je Datensatz statt je Menge — `mandate()` fragte je Eigentümer dreimal, die
> Senkungsansprüche lasen je Vertrag Organisation und Anpassungen nach. Gemessen an einem
> Bestand mit zwanzig Mandaten und hundert Verträgen: **64 statt 1** und **203 statt 2**
> Abfragen, bei jedem Aufruf der Startseite. Beide sind auf `annotate` bzw.
> `select_related`/`prefetch_related` umgestellt, das Ergebnis ist nachweislich identisch, und
> `faelle/test_lage.py::AbfragezahlTests` hält die Grössenordnung fest.

> **~~Offener Punkt aus 4b.13~~ — erledigt in 4b.14.** Mit den vier Kacheln war eine
> **geprüfte Regel ohne Ort** geblieben: «Ein gekündigter Vertrag, dessen Ende bereits vorbei
> ist, zählt als *beendet*, nicht als *gekündigt*.» Sie stammt aus einem Live-Befund (der
> Zähler doppelte, 4 statt 5) und wurde ausschliesslich in der Startseiten-Kachel «Verträge»
> angewandt.
>
> Sie steht jetzt in **`Mietvertrag.anzeige_status`** — an einer Stelle, für jeden Aufrufer.
> Die Vertragsliste filtert und beschriftet danach, «Beendet» ist ein eigener Filter, und
> «Archiviert» geht darin auf (zwei Auswahlpunkte für dieselbe Sache wären ein Bedienfehler).
> Aktenkopf und Statuspille zeigen denselben Wert wie die Liste — stünde auf der Akte
> «Gekündigt per 14.08.», während die Liste «Beendet» sagt, wüsste niemand, welcher Seite zu
> trauen ist.
>
> **`status` bleibt unangetastet.** Er sagt, was verfügt wurde; `anzeige_status` sagt, was
> heute gilt. Die **Sollstellung läuft weiter nach `status`** und grenzt selbst gegen den
> Periodenbeginn ab (`exclude(ende__lt=start_date)`) — das ist Befund H4: Ein gekündigter
> Vertrag wird bis zum Vertragsende verrechnet. Ein Test hält fest, dass dort kein
> `anzeige_status` auftaucht; sonst fiele die letzte Monatsmiete stillschweigend aus.

> **Die Leerstandsregel (Entscheid 21.08.2026, aus 4b.15).** Die Liegenschaftsliste zeigte
> Karten mit Einheitenzahl, Ist-Miete und Vermietungsbalken — **Bestand**. Bei einem ruhigen
> Portfolio sehen alle Karten gleich aus; wer die Seite öffnet, muss jede einzeln lesen, um
> zu merken, dass in der dritten seit zwei Monaten eine Wohnung leer steht. Jetzt eine Zeile
> je Liegenschaft, **sortiert nach Befund**, mit «ohne Befund» als eigener Aussage.
>
> Drei Festlegungen tragen das, alle drei in `faelle/liegenschaften.py` begründet:
>
> 1. **Ein einziges leeres Objekt genügt.** Keine Prozentschwelle. Bei vier Wohnungen sind
>    25 % Leerstand ein Alarm, bei vierzig sind 2.5 % dieselbe eine Wohnung — und beide kosten
>    gleich viel Miete pro Monat. Die Quote steht im Streifen als Portfoliokennzahl, sie ist
>    kein Auslöser.
> 2. **Leer ist ein Objekt ab dem Ende der Kündigungsfrist, nicht ab dem Auszug.** Massgeblich
>    ist `Mietvertrag.ende` (bei einem gekündigten unbefristeten Vertrag die `per_datum` der
>    Kündigung), nicht das Abnahmeprotokoll. Wer drei Tage früher auszieht, macht das Objekt
>    nicht früher vermietbar; wer nach Vertragsende nicht räumt, macht es nicht länger belegt.
>    Dieselbe Trennung wie in 4b.14: was verfügt ist gegen was heute gilt.
> 3. **Ein Nachmieter hebt den Befund auf** — auch ein Vertrag im Entwurf. Ohne diese Regel
>    meldet die Liste genau die Objekte, um die sich schon jemand gekümmert hat.
>
> **Zwei Dinge stehen bewusst nicht in der Zeile.** *Laufblockaden*: Ein `Lauf` hängt über
> `Laufart` an der Organisation und hat kein `liegenschaft`-Feld — ein offener Mahnlauf ist
> Sache des ganzen Mandanten und gehört auf die Startseite. *Unterhalt über Budget*: Es gibt
> kein Budgetfeld je Liegenschaft (null Treffer). Ob ein Unterhaltsbudget je Mandat oder je
> Liegenschaft geführt wird, ist eine betriebliche Entscheidung — **offener Punkt**, nicht
> plausibel zu ergänzen.
>
> **Nebenbefund: Die Ist-Miete war zu tief.** Die Karte summierte nur `status='aktiv'` und
> liess jeden gekündigten, aber noch laufenden Vertrag aus dem Ertrag fallen — obwohl er bis
> zum Vertragsende Miete schuldet (Befund H4 hat das für die Sollstellung längst so
> festgelegt). Die Zahl steigt dadurch; sie war vorher falsch.
>
> **Zum vierten Mal las ein Wächter seine eigene Begründung.** Die Gegenprobe «die alte
> Kartenansicht ist weg» suchte `fw-pcard` in der ganzen Seite und war rot — getroffen hat sie
> den CSS-Kommentar in `base.html`, der erklärt, warum die Regeln entfernt wurden. Sie fragt
> jetzt nur das Markup (`_ohne_stil`), und eine zweite Prüfung hält fest, dass dieser Schnitt
> nicht zu viel wegnimmt. Muster wie bei `{% comment %}` in `test_template_struktur.py`.

> **Der offene Punkt aus 4b.15 ist beantwortet: das Budget gehört an die
> Liegenschaft (4b.16).** «Unterhalt über Budget» stand als offene betriebliche
> Entscheidung im Code — es gab kein Budgetfeld, und ob eines je Mandat oder je
> Liegenschaft geführt wird, war nicht zu erraten. Die Antwort: **je
> Liegenschaft.** Unterhalt fällt am Gebäude an, nicht am Eigentümer; ein Mandat
> mit vier Liegenschaften hat vier Dächer, vier Heizungen, vier Lifte. Ein
> gemeinsamer Topf verwischt, welches Haus Geld kostet — und die Summe je Mandat
> lässt sich aus den Einzelbudgets bilden, der umgekehrte Weg nicht.
>
> **Als Modell, nicht als Feld.** Ein Budget wechselt jährlich. Als Feld an der
> Liegenschaft gäbe es immer nur den aktuellen Wert, und «wie war es letztes
> Jahr» wäre nicht mehr zu beantworten — obwohl genau dieser Vergleich die
> interessante Aussage ist.
>
> **Die Meldung nennt immer das Restjahr.** «CHF 34'800 von 31'000 verbraucht»
> ist eine Zahl; «34'800 von 31'000 bei vier Monaten Restjahr» ist eine Aussage.
> Im Februar wären 60 % Verbrauch alarmierend, im November unauffällig. Gezählt
> werden `Unterhalt`-Einträge **und** Kreditorenrechnungen: In diesem Haus wird
> Unterhalt auf beiden Wegen erfasst, und nur einen zu zählen hiesse, je nach
> Arbeitsweise die Hälfte zu übersehen.
>
> **Ohne Budget schweigt der Befund.** Ein Hinweis «kein Budget erfasst» an
> jeder Liegenschaft wäre die klassische Dauerbeschwerde — wer keines führt,
> will keines führen. Der Befund ist der Preis dafür, eines gesetzt zu haben,
> nicht eine Mahnung, eines zu setzen. Deshalb muss sich ein Budget auch wieder
> **löschen** lassen: Sonst liesse sich ein versehentlich erfasstes nur noch
> überschreiben, nie zurücknehmen.
>
> **Erfasst wird in der Akte, Reiter Finanzen** (nicht in den Stammdaten: ein
> Budget ist eine Planzahl; nicht in den Mandatseinstellungen: wer es setzt,
> schaut gerade auf diese Liegenschaft). Ein zweites Speichern desselben Jahres
> **überschreibt**, statt zu scheitern — wer das Budget eintippt, will es
> setzen, nicht anlegen. Schweizer Schreibweise («31'000.00») wird verstanden;
> sie ist die Form, die auf derselben Seite ausgegeben wird.
>
> **Die Bruttorendite weicht im Aktenkopf** der Kennzahl «Unterhalt <Jahr>».
> Eine Renditezahl, die mangels Verkehrswert «—» anzeigt, kostet dort nur Platz
> — und ohne erfassten Wert ist das der Normalfall. Im Reiter Finanzen bleibt
> sie; dort ist sie eine Auswertung.
>
> **Zwei Bestandswächter haben zugeschlagen, beide zu Recht.** `test_jedes_
> modell_hat_einen_weg_zur_organisation` hätte ein Modell ohne
> `ORGANISATION_PFAD` gefunden — ohne Weg zur Organisation könnte ein Mandant
> die Budgetzahlen eines anderen sehen. Und `test_jeder_parameter_ist_
> zugeordnet` meldete beide neuen URLs als nicht zuordenbar: Sie wären durch
> den Fremd-Id-Sweep gefallen, ohne dass es jemand bemerkt. Achtung auf die
> Reihenfolge in `NAME_MUSTER` — `budget_loeschen` muss vor `budget_speichern`
> stehen, und `pk` bedeutet bei den beiden Verschiedenes (Budget bzw.
> Liegenschaft).

> **Die Objektliste zeigte den Befund als Gedankenstrich (4b.17).** Am
> 21.08.2026 am Bestand gesehen: Beide leeren Wohnungen an der Selzacherstrasse
> standen mit «Soll-Miete —» in der Liste. Das IST die Nachricht der Seite —
> zwei Wohnungen stehen leer und haben keinen Preis hinterlegt, man kann sie
> also nicht ausschreiben — und sie stand dort als Strich.
>
> Dazu kam, was die Vorfassung sonst noch verschwieg: sortiert nach `strasse`
> und `bezeichnung`, also nach Alphabet, wodurch ein vermieteter Parkplatz
> gleichberechtigt neben zwei leeren Wohnungen stand; «Leerstand» ohne
> Zeitangabe, sodass *seit acht Monaten leer* und *ab nächstem Monat frei*
> denselben Chip trugen; `Einheit.zur_ausschreibung` gab es, ausgewertet wurde
> es nirgends. Und der Objekttyp `bas` (Bastelraum) stand in **keiner**
> Filtergruppe — über die Filterleiste war er unerreichbar.
>
> **Eine Darstellung statt zwei.** Karten (`md:hidden`) und Tabelle
> (`hidden md:block`) standen nebeneinander: 133 Zeilen doppelte Pflege, und
> die Chips in der Tabelle trugen noch `bg-emerald-50 text-emerald-700` statt
> der Tokens — sie liefen also an der Petrol-Palette vorbei. Das zweite
> Suchfeld in der Karte ist ebenfalls weg; die Topbar hat eines.
>
> **Die Gruppierung nach Liegenschaft bleibt** (Entscheid 21.08.2026), aber die
> Gruppen sind nach BEFUND geordnet, nicht nach Alphabet, und die auffälligen
> stehen offen. Die Filter machen den Rest: «Mit Befund» reduziert zwölf
> Liegenschaften auf die drei, um die es geht. Der Kennzahlenstreifen zeigt
> dabei immer das ganze Portfolio — sonst stünde bei aktivem Filter «2 von 2
> mit Befund».
>
> **Was hier NICHT dupliziert werden durfte: die Leerstandsregel.** Das
> gelieferte Konzept behauptete in seinem Docstring, `_belegung()` rufe
> `liegenschaften._leerstand` auf — der Code implementierte sie ein zweites
> Mal, und zwar mit einem anderen Statustest (`exclude(entwurf, archiviert)`
> statt der benannten Listen). Genau die Drift, vor der derselbe Docstring
> warnt. Vollständig teilen lässt sie sich nicht: `_leerstand` rechnet je
> Liegenschaft und holt in derselben Schleife die Ist-Miete, die Objektliste
> braucht den Zustand je einzelner Einheit samt «leer seit». Zwei Dinge halten
> sie jetzt zusammen — die **Statuslisten sind importiert**, nicht
> abgeschrieben, und **`KonsistenzTests`** stellt beide Module vor dieselben
> Fälle und vergleicht das Urteil.
>
> **Und er hat beim ersten Lauf sofort etwas gefunden.** Eine heute leere
> Wohnung mit Vertrag ab nächstem Monat trug in der Objektliste weiter «Steht
> leer» und «Nicht ausgeschrieben» — zwei Rüffel für eine Wohnung, um die sich
> längst jemand gekümmert hat —, während die Liegenschaftsliste sie korrekt
> nicht als Leerstand zählte. Daraus folgte auch die Trennung von **`belegt`**
> (physisch belegt, steuert die Zeile) und **`versorgt`** (belegt oder
> Nachmieter, steuert die Leerstandszahl). Beide Seiten zeigen jetzt dieselbe
> Zahl für denselben Bestand.
>
> **Zum sechsten Mal las ein Wächter seine eigene Erklärung.** «Die doppelte
> Darstellung ist weg» suchte `bg-emerald-50` und `hidden md:block` in der
> ganzen Seite — getroffen hat er den Kommentar im Palette-Skript und eine
> JS-Erläuterung in `base.html`, die auf jeder Seite mitgeliefert werden. Er
> fragt jetzt nur das Markup (`_nur_markup` schneidet `<script>` und `<style>`
> weg), und eine zweite Prüfung hält fest, dass dieser Schnitt nicht zu viel
> wegnimmt.

> **Die Schadensliste zeigte drei Nullen (4b.18).** Am 21.08.2026 am Bestand
> gesehen: drei Kacheln übereinander, jede einen halben Bildschirm hoch, jede
> mit einer Null — «0 Offen», «0 In Bearbeitung», «0 Total angezeigt». Danach
> sieben Filterchips über drei Zeilen und ein zweites Suchfeld. Die Arbeit
> begann ausserhalb des Bildschirms.
>
> **«Total angezeigt» ist ersatzlos gestrichen.** Es zählte, was der eigene
> Filter übriggelassen hat, und sagte über den Bestand nichts aus. An seiner
> Stelle steht die Liegezeit der ältesten offenen Meldung — die einzige der
> vier Zahlen, die eine Verwaltung im Streitfall erklären muss. Die sieben
> Chips bildeten die **Statustabelle** ab, nicht die Arbeit; jetzt vier
> Arbeitssichten (Offen · Mit Befund · Wartet auf Dritte · Erledigt · Alle),
> der Feinfilter bleibt über `?status=` erreichbar. Und sortiert wurde nach
> `-erstellt_am`: Der Wasserschaden von heute Morgen stand über der Meldung,
> die seit sechs Wochen ungelesen liegt.
>
> **Das Versprechen im Untertitel wird jetzt gemessen.** Die Seite trägt den
> Satz «Meldung → Auftrag → automatische Info an Melder». Ob er eingehalten
> wurde, stand nirgends: Eine Meldung ohne eine einzige ausgehende Nachricht
> sah aus wie eine, bei der alles lief. Der Befund «Melder ohne Rückmeldung»
> prüft genau diese Zusage.
>
> **Und das Mass dafür war im gelieferten Entwurf falsch — in die gefährliche
> Richtung.** Er prüfte den Nachrichten-TYP und liess vier Typen als Echo
> gelten. Zwei davon bringen den Befund zum **Schweigen**, und das fällt
> niemandem auf:
>
> * **`mail_antwort` ist EINGEHEND** — der Typ entsteht in `webhooks.py` und
>   `fetch_replies.py`, wenn der MIETER auf die Ticket-Mail antwortet. Als Echo
>   gewertet schwiege der Befund ausgerechnet dann, wenn jemand geschrieben hat
>   und niemand geantwortet.
> * **`system` ist überwiegend INTERN** — «Auftrag an X vergeben» und «Status
>   geändert» tragen `is_intern=True`. Da eine Auftragsvergabe *immer* eine
>   solche Notiz schreibt, hätte praktisch jede Meldung mit Handwerker als
>   «Melder informiert» gegolten.
>
> Massgeblich ist jetzt, was den Mieter **tatsächlich erreicht** — und diese
> Definition gab es im Haus bereits: Das Mieterportal zeigt den Verlauf als
> `nachrichten.exclude(is_intern=True)`. Dazu kommen die zwei Systemnotizen,
> die einen nachgewiesenen Versand protokollieren (sie entstehen nur nach
> erfolgreichem `send_ticket_email`). Der dafür nötige Textabgleich ist
> zerbrechlich und deshalb sichtbar gemacht: `ProtokollWortlautTests` liest
> die beiden Erzeugerstellen im Produktivcode und wird rot, wenn jemand die
> Formulierung ändert.
>
> **Zwei Prüfungen des Entwurfs waren blind, eine prüfte toten Code.** In allen
> Sortiertests war die Meldung mit Befund zugleich die ältere — reine
> Alterssortierung lieferte dieselbe Reihenfolge, der Test war grün ohne die
> Regel zu prüfen. Der Abfragezahl-Test baute sein Queryset selbst und setzte
> das `prefetch_related` von Hand; die VIEW war ungeprüft. Und ein `elif`
> suggerierte eine Vorrangregel zwischen «Freigabe ausstehend» und «Kein
> Auftrag», die keine ist — die Zweige schliessen sich ohnehin aus.
>
> **Der Abfragezahl-Wächter mass beim ersten Anlauf die Sitzung, nicht den
> Abfrageplan.** Er verglich den ersten Seitenaufruf mit einem späteren und
> meldete einen *Rückgang* von 19 auf 15 Abfragen — der erste Aufruf einer
> Testsitzung baut Session und Berechtigungen auf. Er wärmt jetzt auf, bevor er
> misst, und sichert **Konstanz** zu statt einer festen Zahl: Eine feste Zahl
> bräche bei jeder unbeteiligten Änderung und sägte an ihrer eigenen
> Glaubwürdigkeit.

> **«Assets» war eine Seite, die nichts erfasste und doppelt schrieb (4b.20).**
> `/neu/assets/` listete Geräte und Raumbuch portfolioweit auf — beides wird
> in der Liegenschafts- und der Objektakte längst vollständig erfasst. Ihre
> CRUD-Pfade (`fw_asset_neu/bearbeiten/loeschen`) schrieben auf dasselbe Modell
> `portfolio.Geraet` wie `/neu/geraet/*`: zwei Implementierungen derselben
> Sache, die irgendwann auseinanderlaufen. Beide sind entfernt.
>
> **Gefehlt hat nicht die Seite, sondern eine Verbindung.**
> `core/services/ersatzplanung.py` gab es bereits — mit Restnutzungsdauer,
> Jahresbudget, Fondsdeckung und PDF-Report —, rechnete aber nur mit
> `Ausstattung`. Ausgerechnet die Geräte, die teuren Posten, blieben aussen
> vor. Jetzt tragen beide dieselbe Zeilenform und stehen in einer Rechnung.
>
> **Geräte tragen NICHTS zum Jahresbudget bei, und das ist Absicht.**
> `Geraet` hat kein `neuwert`-Feld. Einen Preis zu schätzen wäre die
> schlechtere Antwort als eine ehrliche Lücke: Ein erfundener Boilerpreis
> wanderte über den PDF-Report direkt in die Fondsplanung des Eigentümers und
> sähe dort aus wie eine Zahl. Die Seite nennt die Lücke ausdrücklich
> («*n* Geräte stehen in der Liste, aber nicht im Budget»). Aus demselben
> Grund hat der **Aufzug** keine Lebensdauer: Der Raumkatalog kennt keine, und
> eine Frist zu behaupten, für die es keine Grundlage gibt, ist schlechter als
> «Keine Datenbasis».
>
> **Die Kategorienbrücke** übersetzt zwischen den beiden Namensräumen — die
> Lebensdauertabelle heisst «Heizung / Wärmeerzeuger», die Geräteliste
> «Heizung». Identische Namen (Waschmaschine, Geschirrspüler, Backofen,
> Rauchmelder) findet `Lebensdauer.fuer_kategorie` von selbst.
>
> **`/neu/assets/` bleibt als Weiterleitung** auf `/neu/ersatzplanung/`, mit
> `query_string=True`, damit ein Lesezeichen mit `?lg=` seinen Filter behält.
> Den **Menüplatz** erbt die Ersatzplanung («Ersatz & Ausstattung», nav-Key
> `assets` unverändert) — sie stand bis dahin in **keiner** Navigationsgruppe
> und war nur über die Brotkrume von `/neu/lebensdauer/` zu finden. Die
> Weiterleitung selbst steht mit Begründung in `OHNE_WEG`
> (`test_erreichbarkeit.py`): `urls.py` zählt dort ausdrücklich nicht als Weg,
> sonst wäre jede Route automatisch «erreichbar».
>
> **Drei Wächter wurden umgehängt, nicht gelöscht.** `test_asset_loeschen`,
> `test_asset_bearbeiten` und `test_assets_seite_zeigt_ausstattung` prüften
> Dinge, die weiterhin gelten — nur die Adresse hat gewechselt. Die ersten
> beiden zeigen jetzt auf `/neu/geraet/*`, der dritte ist in zwei zerlegt: die
> portfolioweite Sicht auf der Ersatzplanung, die Gruppierung nach Raum in der
> Objektakte. Was **nicht** mehr gefordert wird, ist das portfolioweite
> Objekt-Akkordeon — das war die Doppelung.
>
> **Siebter Fall: Der Wächter fand sein Wort woanders.** Die erste Fassung von
> `test_das_raumbuch_gruppiert_in_der_objektakte_nach_raum` suchte «Bad» in der
> gerenderten Seite und blieb **grün**, als die Raum-Überschrift aus der
> Vorlage entfernt wurde: Das Wort steht auch im Erfassungsformular darunter
> (`<input name="raum" value="…">`). Beide Prüfungen lesen jetzt den Context
> statt das HTML. Im Nachbartest wäre es noch stiller ausgegangen — «Bad» ist
> Teilstring von «Badge» und stünde damit auf fast jeder Seite.
>
> **Ein Test zählte den Fixture-Bestand statt der Regel.** Die erste Fassung
> von `test_ein_faelliges_geraet_erhoeht_das_budget_nicht` erwartete
> `n_geraete == 1` — das `MandantenFixture` bringt selbst ein Gerät mit. Sie
> zählt jetzt relativ (vorher + 1) und wird beim nächsten Fixture-Zuwachs nicht
> aus dem falschen Grund rot.

> **Warum 4b.10 dazwischenkam — dreimal derselbe Fehler.** Der Vergleich mit
> `mockups/konzept-v2.html` (Screen «Fristenwächter») ergab, dass die Rechenlogik seit Phase 4a
> vollständig vorlag: `kuendigungstermin()`, `Regelsatz` je Kanton, `Regel` mit Verbindlichkeit,
> `Regelanwendung` als Protokoll mit Regelstand, und `sperrt()` mit genau der Zusicherung, die
> der Prototyp verlangt — eine ungeprüfte Regel warnt, sie sperrt nie. **Aufgerufen wurde davon
> nichts.** Die Kündigungserfassung rechnete mit `rentals.services.berechne_kuendigungstermin`,
> richtig, aber ohne Protokoll, ohne kantonale Fassung, und sie prüfte nur die eine Hälfte: Ein
> zu früher Termin wurde geklemmt, ein Datum, das gar kein zulässiger Termin ist, lief durch.
>
> Beim Beheben zeigte sich, dass derselbe Fehler zweimal aus **dieser** Arbeit stammt: Die in
> 4b.5 und 4b.8 gebauten Seiten (`/neu/arbeit/`, `/neu/zulauf/`, `/neu/laeufe/`, `/neu/termine/`,
> `/neu/abwesenheiten/`) standen in **keiner** Navigationsgruppe. Erreichbar war nur, wer die
> Adresse tippte oder zufällig auf einen Querverweis stiess. Daraus entstand
> `core/tests/test_erreichbarkeit.py`: Jede parameterlose `/neu/`-Adresse braucht einen Weg —
> aus der Navigation, aus einer Vorlage oder aus einer Weiterleitung; ein Test, der die Adresse
> aufruft, zählt ausdrücklich **nicht** als Weg. Beim ersten Lauf fand der Wächter einen
> weiteren, älteren Fall: `/neu/kreditoren/pain001/` erzeugt eine gültige Zahlungsdatei aus
> allen freigegebenen Rechnungen, ohne Auswahl und ohne Zahllauf-Buchung — überholt durch
> `/neu/zahllauf/`, aber weiterhin antwortend.

> **Warum 4b.5 dazwischenkam.** `Fall`, `Fallschritt`, `Eingang`, `Zuordnungsregel`, `Lauf`
> und `Blockade` waren nach vier Etappen vollständig gebaut und vollständig getestet — und
> hatten **null Views, null URLs, null Templates**. Ein grüner Modelltest sagt nichts darüber,
> ob ein Mensch die Sache je zu Gesicht bekommt. Die vier Seiten sind der Beleg, dass Phase 4a
> trägt; die Verfallsregel aus Abschnitt 5.2 wird dort zum ersten Mal angezeigt.

Der Wächter für 4b.3 war `faelle/test_reiter_panels.py::test_umstellung_erzeugt_nur_
erreichbare_reiter`, als `expectedFailure` markiert. Seine Meldung nannte jedes fehlende Panel
je Vorlage und war damit die Arbeitsliste.

**Er ist seit 4b.11 grün.** Als die Objektakte als letzte umgestellt war, meldete Django den
unerwarteten Erfolg als Fehlschlag — genau wie beabsichtigt — und die Markierung wurde
entfernt. Ab jetzt gilt er ohne Nachsicht. Beim Entfernen zeigten zwei weitere Wächter, dass
sie die Objektakte gar nicht ansahen: `GerenderteSeiteTests._seiten` und `AktenkopfTests.
_seiten` sind zweite, von Hand gepflegte Listen, und `test_bereichsgestaltung.SEITEN` war eine
dritte. Alle drei tragen die Objektakte jetzt, und `test_jede_umgestellte_akte_wird_hier_
gemessen` hält fest, dass keine vierte Liste zurückbleibt.

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

> **Nachtrag 4b.9 — «überall» stimmte nicht.** Die Umdefinition wirkt nur dort, wo sie geladen
> wird, und nur auf Klassennamen. Drei Flächen kamen daran vorbei und blieben Indigo:
>
> | Fläche | Warum vorbei | Umfang |
> |---|---|---|
> | **Seitenleiste** | stand als `from-[#15182e] to-[#0d0f1e]` in Tailwinds Notation für beliebige Werte | auf **jeder** Seite sichtbar |
> | **Dunkelmodus** | überschreibt mit `!important` und festen Hexwerten | die **ganze** Anwendung, je nach Systemeinstellung |
> | **Eingebettete Hüllen** | `fw/base_embed.html` und `fw/_modal_done.html` luden Tailwind ohne die Umdefinition | Modale, u. a. die Wohnungsabnahme |
>
> Gemerkt wurde es nicht, weil die Wächter nur den `:root`-Block und die Rampen lasen — also
> genau die Stelle, an der aufgeräumt worden war. Seit 4b.9 gilt: die Seitenleiste trägt den
> Prototyp-Verlauf `#122b31 → #0a1c20` (`--nav` aus `konzept-v2.html`); die Zustands- und
> Markenfarben des Dunkelmodus stehen als `var(--ds-*)` und können nicht mehr auseinanderlaufen;
> die neutrale Flächentreppe bleibt Hexwert, aber im Farbton 195° bei unveränderter Helligkeit
> (Kontraständerung ≤ 1 Punkt, alle Werte über AA); die Rampe liegt als Baustein
> `fw/_tailwind_palette.html` und wird von allen drei Hüllen eingebunden.
> `core/tests/test_palette.py` misst **jeden** Farbwert der Datei auf seinen Farbton und lässt
> keinen zwischen 215° und 300° durch.

**Was die Palette weiterhin nicht abdeckt: die Aussenseiten.** Zwölf Vorlagen laden Tailwind vom
CDN ohne den Baustein — Mieterportal, Bewerbungsformular (allein 79 der 92 verbliebenen
Indigo-Klassen), öffentliches Ticket-Formular, Datenschutzseite, Fehlerseiten, Dossier. Das ist
eine Entscheidung, keine Nachlässigkeit: Sie einzuziehen ändert, was **Mieter und Bewerber**
sehen. Die Zahl ist in `test_tailwind_palette.py` festgehalten, damit die Lücke benannt bleibt
und nicht stillschweigend wächst.

### 16.5 Was hier bewusst nicht steht

Der **Aufbau** ausserhalb der Aktenseiten. Die Palette gilt seit 4b.6 in der Anwendung, seit
4b.9 auch in Seitenleiste, Dunkelmodus und Modalen (16.4) — Farbe ist damit innen erledigt. Karten, Zeilen, Tabellen und Formulare der übrigen Seiten laufen aber weiter auf
Tailwind-Utilities statt auf `fw-card`, `fw-zeile`, `fw-table`, `fw-feld`. Das ist kein
Farbproblem mehr, sondern eines der Bausteine: Abstände, Radien, Schatten und Zustände weichen
von Seite zu Seite ab.

> **Richtigstellung, 20.08.2026.** Hier stand, das Erscheinungsbild ausserhalb des Aktenkopfs sei
> ungeregelt, mit „**1412 Stellen** Indigo in 131 von 172 Vorlagen". Die Zahl war zu eng gefasst:
> Sie zählte nur `indigo`. Über alle Farbfamilien waren es **7490 Klassen in 176 Vorlagen** —
> 4959 davon `slate`. Genau diese Grössenordnung hat die Entscheidung in 16.4 erzwungen: 7490
> Einzeländerungen sind kein Weg, eine Palettenumdefinition schon.
