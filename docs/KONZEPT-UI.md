# Konzept: Struktur und Oberfläche

Stand 19.08.2026 · gilt ab Phase 4a · ersetzt keine bestehende Phasenvorgabe ausser der unten
festgehaltenen Teilung von Phase 4.

Dieses Dokument beschreibt, **wie swissImmo bedient wird** — nicht, wie es aussieht. Farben,
Typografie und Komponenten folgen in Phase 4b. Die Prototypen unter `mockups/` sind
absichtlich zurückhaltend gestaltet, damit die Anordnung beurteilt wird und nicht die Optik.

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

**G3 — Der Fall ist das zentrale Objekt.** Vorgänge mit Lebenszyklus, Schritten, Frist,
Zuständigkeit und Verknüpfungen zu anderen Fällen.

**G4 — Der Zulauf ist die Startfläche.** In einem kleinen Büro beginnt der Tag mit 40
Eingängen; die Arbeit ist das Zuordnen. Der Zulauf steht links im Arbeitsbereich, nicht als
Icon in der Topbar.

**G5 — Person ≠ Mietverhältnis.** Eine Person kann nacheinander zwei Mietverhältnisse haben,
zugleich Notfallkontakt für jemand anderen und früher Bewerberin gewesen sein. Konto, Kaution,
Fristen und Nebenkosten hängen am **Mietverhältnis**; Identität, Kontaktweg und
Datenschutzrelevantes an der **Person**.

**G6 — Ein Reitersatz für alle Aktentypen.** `Chronik · Stammdaten · Finanzen · Dokumente ·
Fälle`, plus höchstens ein typeigener Reiter. Wer eine Akte bedienen kann, kann alle.

**G7 — Regeln statt Listen.** Eine Fristenliste warnt nicht. Eine Regel, die einen falschen
Kündigungstermin gar nicht durchlässt, warnt. Regeln liegen als **Daten** vor, nicht als Code.

**G8 — Zuständigkeit statt Rolle.** In einer Verwaltung mit drei Personen hat niemand nur eine
Rolle. Gefiltert wird nach Zuständigkeit für Mandat oder Liegenschaft, plus Vertretung.

**G9 — Was fehlt, ist wichtiger als was da ist.** Eine Akte, die nur anzeigt, was erfasst
wurde, spart keine Zeit. Eine, die merkt, was fehlt oder nicht zusammenpasst, schon.

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
| Mandat | Chronik, Stammdaten, Finanzen, Dokumente, Fälle | Liegenschaften |
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

### 13.3 Neue Abhängigkeiten

Keine erforderlich. DocuSeal (Signatur) und die bestehende OCR-Kette decken die
Modulanforderungen ab. Sollte sich in 4a.3 zeigen, dass die Zuordnungsqualität ohne
zusätzliche Bibliothek nicht reicht, wird das als Antrag im PR vorgelegt und **nicht**
umgesetzt.

---

## 14. Prototypen

Unter `mockups/` liegen sieben klickbare HTML-Dateien. Sie sind Diskussionsgrundlage, kein
Zielbild der Gestaltung.

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
