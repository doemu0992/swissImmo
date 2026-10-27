# Audit Phase 1 — Schweizer Feature-Vollständigkeit

Stand 05.10.2026. Methode: Code gelesen und stichprobenweise am Verhalten geprüft
(Parser-Aufruf, Tests). Die Matrix zu HK/NK, Mahnwesen, Tickets und STWEG stammt von
einem Lese-Durchgang; die als **kritisch** eingestuften Befunde wurden einzeln am Code
nachgeprüft (Grep über den Bestand) und bestätigt.

**Vorbemerkung.** swissImmo ist kein Prototyp: über 100 Modelle, rund 520 Routen,
mandantenfähig, mit Playwright-Suite. Die REST-API (django-ninja) besteht nur aus
Webhooks und dem öffentlichen Bewerbungsformular — die Oberfläche ist serverseitig
gerendert. Fehlerbehandlung im Frontend heisst hier: Formularvalidierung der Django-Views.

## 1. Pflichtbereiche

| Bereich | Stand | Beleg |
|---|---|---|
| Mietwesen (Vertrag, Mietzins, Anpassung, Kündigung, Abnahme) | vollständig | `rentals/`, Formularpflicht je Kanton |
| STWEG | breit, stark getestet (28 Testdateien) | `stweg/`; Lücken siehe 3.4 |
| HK/NK-Abrechnung | Engine vorhanden, **drei kritische Lücken** | 3.1 |
| Kaution Art. 257e OR | vollständig: Register, Obergrenze, Sperrkonto/Versicherung, Freigabefrist Abs. 3, PDF-Belege | `core/views/fw/kautionen.py`, `automation.py:816` |
| Inkasso/Mahnwesen | Mahnstufen, Mahnlauf, Verzugszins, Art. 257d, Zahlungsvereinbarung; **Betreibung fehlte** | 3.2 |
| Ticketsystem | Workflow, Handwerker, Portal, Mieter-Meldung; **keine interne Zuweisung, kein SLA** | 3.3 |
| Bankabgleich | camt.053 und CSV; **camt.054 war nicht deklariert** | 2 |

## 2. In Phase 1 umgesetzt (Basis-Strukturen im Backend)

| # | Änderung | Dateien |
|---|---|---|
| U1 | **camt.054** (Einzelavisierung): Typerkennung 052/053/054, Quelle des Kontoauszugs entsprechend gespeichert; Parser las 054 bereits, aber ohne Nachweis | `core/views/fw/bankabgleich.py`, `faelle/test_camt054.py` |
| U2 | **Ticket-Zuweisung intern** (`zugewiesen_an`) und **SLA-Frist** (`faellig_bis`, aus Priorität: notfall 0 / hoch 2 / mittel 7 / tief 14 Tage) | `tickets/models.py`, `tickets/sla.py` |
| U3 | **NK-Zustellung**: `versendet_am`, `versand_kanal`, `einsprache_bis` (30 Tage, Branchenpraxis) | `finance/models.py` |
| U4 | **Betreibung** (SchKG): Modell `Betreibung` mit Stand, Daten, Fristen Art. 74 und Art. 88 SchKG, mandantengetrennt | `finance/models.py` |

Tests: `faelle/test_camt054.py` (4), `core/tests/test_phase1_basis.py` (6, inkl.
Mandantengrenze und Gegenproben). Die Felder aus U2–U4 haben **noch keine Oberfläche** —
das ist Phase 2.

## 3. Verbleibende Lücken (nach Priorität)

### 3.1 HK/NK
- **K — Zählerstände nicht erfassbar:** `ZaehlerStand` wird in keiner View angelegt (nur Admin lesend). HKVO fällt in der Praxis auf m³ zurück. → Erfassungsformular, Zählerart als Enum.
- ~~**K — Verteilschlüssel-Modelle ungenutzt**~~ — **erledigt** (siehe «Nachtrag» unten): opt-in je Liegenschaft, Zimmer/Wertquote/Prozent, Pflegeseite.
- ~~**K — Versand/Einsprache**~~ — **erledigt** (siehe «Nachtrag»): Versand per E-Mail mit PDF, Zustellung und Einsprachefrist werden festgehalten. Brief bleibt das Sammel-PDF.
- M — keine Korrekturabrechnung nach Verbuchen; Leerstandsanteil wird ausgewiesen, aber nicht beim Eigentümer verbucht; kein Mieterbrief bei Akonto-Erhöhung (Art. 269d OR).

### 3.2 Inkasso
- ~~**K — Betreibungs-Workflow**~~ — **erledigt 26.10.2026:** Assistent «Betreibung einleiten» (mehrere Mieten je Betreibung), Datenblatt-PDF für das Betreibungsbegehren, Fristen Art. 74/88 SchKG mit Stillstand, Pendenzen, Mahnlauf ruht für betriebene Forderungen, Tilgung nach Art. 87 OR, «Kosten belasten» (Art. 68 SchKG), Verlustschein schreibt auf 3805 ab (`core/services/betreibung.py`).
- ~~M — Zahlungsvereinbarung ohne PDF/Unterschrift~~ — **erledigt 26.10.2026:** Schreiben «Zahlungsvereinbarung mit Schuldanerkennung» (Art. 82 SchKG), in der Vertragsakte abgelegt. Die Mahnsperre gilt seither nur den gedeckten Forderungen, nicht mehr dem ganzen Mieter (`core/services/mahnsperre.py`, Datenmigration finance 0048). Offen: keine Inkasso-/Anwaltsübergabe.

### 3.3 Tickets
- **K — interne Zuweisung/SLA:** Felder jetzt da (U2); Filter «Meine Tickets», Ampel, Benachrichtigung fehlen. Eskalationsstufen fehlen.
- M — `prioritaet` ist Freitext ohne `choices` (bewusst nicht geändert: Altwerte); Kostenträger-Feld fehlt; kein Bezug STWEG ↔ Ticket.

### 3.4 STWEG
- M — Erneuerungsfonds- und Unterhaltsplanung (die vorhandene `ersatzplanung.py` ist nur im Mietbereich angebunden).
- M — Hauswart-/Dienstleisterverträge, Versicherungsbezug, strukturiertes Reglement (Sondernutzungsrechte), Ämter/Revisoren, Anfechtungs-Erfassung (Art. 75 ZGB).
- K-M — Verbrauchsabrechnung (Heizung/Wasser) der Gemeinschaft, wie 3.1.

## 4. Korrekturen / Beobachtungen
- Die Matrix vermerkte «Betreibung komplett fehlend»; richtig ist: für **Mietzins** fehlte sie, im STWEG-Inkasso gibt es zwei Felder (Datum, Amt).
- Die UI-Texte nennen weiter nur «camt.053». Nicht geändert, weil `msgfmt` fehlt und eine Änderung der Quelltexte die Übersetzungen in DE/EN/FR/IT verwaisen würde. Nachziehen zusammen mit `compilemessages`.
- Entwicklungsdatenbank im Container ist nicht migriert (Wartungsmodus-Meldung beim Start); Tests sind davon nicht betroffen.

---

# Fortsetzung: Phasen 2–4

## Phase 2 — Oberfläche für die Basis-Strukturen

| Prozess | Einstieg | Schutz |
|---|---|---|
| Ticket intern zuweisen, SLA-Frist | Block «Zuständigkeit» im Ticket, Filter «Meine Tickets», Chip «SLA überfällig» | nur Inhaber/Verwalter/Sachbearbeiter (nicht Hauswart, `core/tests/test_rbac.py`) |
| NK-Zustellung, Einsprachefrist | Knopf in der Nebenkostenabrechnung | erst nach Verbuchen; Datum nicht vor Periodenende, nicht in der Zukunft |
| Betreibung (SchKG) | Mahnwesen → «Betreibung» (Assistent), Vertrags- und Personenakte, Liste `/neu/betreibungen/` | Datumsfolge, Stand↔Datum, Forderung > 0; Rechtsvorschlag nach 10 Tagen (Art. 74) seit 26.10.2026 nur noch als **Warnung** — Art. 31, 63, 77 SchKG können ihn rechtzeitig machen; Verlustschein nur Verwalter/Inhaber |
| Zählerstand (HKVO) | Liegenschaft → «Zählerstand erfassen» | Stand darf nicht sinken, nicht vor/nach Nachbarständen |

**Fehlerbehandlung.** Die REST-API besteht nur aus Webhooks; die Oberfläche ist
serverseitig. «422 am Eingabefeld» heisst hier: Die Formulare sind Django-Forms, ein Fehler
liefert HTTP 400, die Seite bleibt, die Eingabe bleibt, der Text steht am Feld
(`fw/_feldfehler.html`, `aria-invalid`). Belegt in `core/tests/test_phase2_formulare.py`,
jeweils mit Gegenprobe (Validierung entfernt → Test rot).

**Button-Check.** Mahnlauf (inkl. Trockenlauf), Jahresabschluss (Buchen/Zurücknehmen mit
Rückfrage), STWEG-Handänderung, Mieterwechsel, Sollstellung: vorhanden und bedienbar.

## Phase 3 — Gestaltung auf dem vorhandenen System

Das Designsystem v8 (Tokens, Dunkelmodus, Wächtertests) wurde **nicht** ersetzt, sondern
ergänzt (Quelle `core/templates/fw/_schicht.html`, gebaut mit `manage.py schicht_bauen`):
dezentes Glas (Seitenleiste, Dialoge, Palette; Rückfall und `prefers-reduced-transparency`),
stehender Tabellenkopf (`fw-sticky`), Spaltenfilter (`data-spaltenfilter`, filtert die
geladenen Zeilen), Randmarkierung überfällig/bezahlt, Inhaltsbreite bis 2000 px.

## Phase 4 — Arbeitstag über die Oberfläche

`e2e/tests/arbeitstag.spec.ts`: Login → Mandat → Liegenschaft → Objekt → Mieter → Mietvertrag
(7-stufiger Assistent) → Ticket erfassen und zuweisen → Sollstellung → Miete steht in den
Debitoren. `e2e/tests/navigation-links.spec.ts`: 103 interne Adressen ohne Fehlerseite/JS-Fehler;
Cockpit-Modale laden zu Ende (kein endloser Spinner).

**Befund und Korrektur.** Nach abgeschlossenem Monatslauf bot die Sollstellung bei einem
Nachzügler-Vertrag den Knopf «Sollstellung starten (1)» an, den die Sperre gegen Doppelausführung
danach ablehnte. Die Sperre ist Absicht und bleibt; die Seite nennt jetzt den Grund und führt zu
«Läufe → Lauf zurücksetzen» (`faelle/test_sollstellung_nachzuegler.py`).

## Bewusst offen
- ~~Priorität «Notfall»~~ — erledigt: wählbar im Meldeformular (nur bekannte Stufen), Frist heute, steht vor «Hoch» in der Liste, Chip und Admin-Badge (`faelle/test_prioritaet_notfall.py`). Im Mieterportal und im öffentlichen Formular bleibt es bei «mittel» — Mieter stufen nicht selbst als Notfall ein.
- Spaltenfilter wirken nur auf die geladene Seite, nicht serverseitig über alle Seiten.
- Debitorentabelle ist bei 1440 px breiter als der Rahmen (Aktionsspalte scrollt) — schon vorher so.
- Übersetzungen FR/IT/EN der neuen Texte stammen von der KI; Rechtsbegriffe fachlich gegenlesen.
- NK-Versand per E-Mail/Brief, Verteilschlüssel-Anbindung der Engine, STWEG-Planung: siehe 3.1–3.4.

## Nachtrag — Verteilschlüssel und NK-Versand per E-Mail

**Verteilschlüssel (opt-in).** `Liegenschaft.verteilschluessel_aktiv` (Standard **aus**) schaltet die
Schlüssel der Liegenschaft in der Abrechnung frei. Ohne Kennzeichen rechnet die Engine wie bisher —
die Schlüsseltabellen waren bis dahin wirkungslos, vorhandene Zeilen dürfen nicht über Nacht Abrechnungen
verändern (Regressionstest in `core/tests/test_verteilschluessel.py`, mit Gegenprobe).

| Schlüssel | Basis |
|---|---|
| Zimmer | `Einheit.zimmer` |
| Wertquote | `Einheit.wertquote` |
| Prozent | je Einheit erfasst (`Verteilschluessel.wert`), Summe 100 |

Gilt für Belege (`NebenkostenBeleg`) der Kostenart und **überschreibt** die Wahl am Beleg. Bewusst nicht
angeschlossen: Heizkosten (bleiben bei HKVO/Heizgradtagen), «Pauschal» (CHF je Einheit — fachlich offen,
wird nicht geraten), Kreditoren-Rechnungen (keine Zuordnung Konto → Kostenart). Fehlt die Basis (keine
Zimmerzahl, Prozent ≠ 100), wird nach Fläche verteilt und gewarnt — die Kosten verschwinden nicht.
Der Schlüssel gilt zum **Periodenende**; ein Wechsel innerhalb der Periode wird nicht anteilig gerechnet.
Pflege: `/neu/liegenschaften/<pk>/verteilschluessel/` (ein neuer Schlüssel beendet einen offenen Vorgänger
am Vortag).

**NK-Versand per E-Mail.** `/neu/nebenkosten/<pk>/mail/` (Inhaber/Verwalter): nur verbuchte Periode,
je Mieter das PDF als Anhang, Antwortadresse = «Antworten»-Postfach der Verwaltung, Ablage in der
Mieterakte und im Kommunikationsjournal. Die Zustellung (`versendet_am`, Kanal «E-Mail», Einsprachefrist)
wird **nur bei vollständigem Versand** festgehalten; fehlende Adressen und Fehlversand werden genannt.
Mailtext und PDF sind deutsch (das Dokument ist fest deutsch).

Weiterhin offen: Kreditoren-Zuordnung zur Kostenart für die Schlüssel, Briefversand mit Nachweis
(Sammel-PDF + manuelle Zustellung bleibt), STWEG-Planung (3.4).


## Nachtrag 23.10.2026 — Funktionen für die drei Nutzergruppen

Analyse: Die Anwendung ist eine serverseitig gerenderte Django-Oberfläche (rund 300 Routen unter
`/neu/`), kein React-Projekt. shadcn/ui, recharts und lucide-react gibt es dort nicht; die Entsprechungen sind
die `fw-`-Bausteine (`docs/DESIGN-V8.md`), die Zeichen aus `docs/ZEICHEN.md` und die serverseitigen SVG-Diagramme
(`core/templatetags/diagramm.py`). Das Navy-Design (V9) gilt global über die Tokens. Der React-Weg ist als Zielbild
in `mockups/immoswiss-next/` hinterlegt (Next.js, Tailwind, shadcn/ui, lucide-react, recharts, Dummy-Daten).

Was fehlte, und was jetzt steht (alles auf der bestehenden Geschäftslogik, keine neuen Modelle):

| Gruppe | Lücke | Umsetzung |
|---|---|---|
| Bewirtschafter | Tickets nur als Liste | **Ticket-Board** `/neu/schaeden/board/`: vier Spalten, Ziehen oder Auswahlfeld, nur erlaubte Übergänge (`tickets.workflow`), Sperre «nicht erledigt ohne Handwerkerrechnung» gilt beim Ziehen; Filter Meine / Dringend / SLA überfällig; Schnellaktionen «Neues Ticket», «Mieter kontaktieren» |
| Bewirtschafter | Termine nur als Liste, Quellen auf vier Seiten verteilt | **Monatskalender** `/neu/termine/kalender/`: Termine, Fristen, Ticket-Zielzeiten, Auszüge; Monatswechsel, Eintragsarten ein-/ausblenden, Tagesliste; am Telefon Agenda |
| Buchhalter | Kein Ampelsystem, kein Export der Debitoren | **Ampel** (grün bezahlt · gelb offen, nicht fällig · rot überfällig) als Karten und Filter; **CSV-Export** (alle Zeilen, mit Ampel und Tagen überfällig, folgt den Filtern, Formelschutz) |
| Eigentümer | Keine Portfolio-Sicht | **Portfolio** `/neu/portfolio/`: Soll-Mietertrag, Brutto-/Nettorendite (nur mit Verkehrswert oder Anlagekosten — sonst «–» und Hinweis), Leerstand, Zahlungsquote, Cashflow 6/12/24 Monate, Donut nach Ertrag oder Nutzung, Performance je Liegenschaft, CSV |

Wächter: `core/tests/test_rollen_funktionen.py` (36 Tests, Gegenprobe an Ampelfilter und Workflow), E2E
`e2e/tests/rollen.spec.ts`; RBAC-Sweep kennt Board und «verschieben» als Hauswart-Rechte (wie Liste und Statuswechsel).

Nicht gebaut (bewusst, mit Grund): Kanban für Aufgaben ohne Ticket (die Pendenzen haben keinen Zustandsfluss);
Rechnungs-Workflow als eigene Seite (Kreditoren führen ihn schon: erfasst → freigegeben → bezahlt); Zeitreihe der
Portfolio-Rendite (es gibt keine Verkehrswert-Historie — eine Linie wäre erfunden).
Die Übersetzungen FR/IT/EN der neuen Texte sind KI-erzeugt und brauchen eine Fachprüfung.


## Nachtrag 26.10.2026 — UI-Audit nach dem Ember-Redesign

Vorgehen: ein Crawler über alle erreichbaren Seiten unter `/neu/` (119 Seiten) bei 1440, 820 und 390 px —
horizontaler Überlauf, verdeckte Bedienelemente (`elementFromPoint`), Text, der aus seiner Karte ragt, und
JEDES Aktionsmenü geöffnet und auf Lage und Klickbarkeit geprüft. Der erste Lauf mit abgeschalteten Animationen
(automatisierte Browser setzen `html.fw-ruhig`) fand nur die Hälfte; erst mit echten Animationen zeigte sich der
Hauptfehler.

| Befund | Ursache | Behebung |
|---|---|---|
| Alle «Mehr»-Menüs unbedienbar, auf jeder Breite | Einblend-Animation mit `animation-fill-mode: both`: jeder Inhaltsblock blieb dauerhaft ein eigener Stapelkontext, das Menü im Seitenkopf lag unter den Kennzahlen | `backwards` statt `both`; der Block mit offenem Menü wird angehoben (`:has`); Menüs `z-index:70` |
| Acht Akten-Menüs ragten am Tablet/Telefon links aus dem Bild (x = −149) | eigenes `onclick` + Schliess-Skript je Akte, rechtsbündig verankert | alle auf den zentralen `data-menu`-Mechanismus; `fwMenuEinpassen` passt jedes offene Menü ins Bild, klappt bei Platzmangel nach oben; Escape, Klick daneben, Pfeiltasten, `aria-expanded` |
| Reiterleisten wirkten abgeschnitten («schaften») | 13 Akten-Reiter breiter als der Bildschirm | kompaktere Reiter ab 1024 px, weich auslaufende Ränder, wo die Leiste weiterläuft; Hauptkapsel am Telefon verdichtet |
| Tooltip der letzten Balkensäule ragte 5 px aus der Karte | zentriert verankert | letzte Säule nach innen |
| Navigation zeigte Ziele ohne Berechtigung | Reiter und ⌘K-Palette ungefiltert | `darf`-Filter (liest die Rollen am View-Dekorator) |

Nachher: 119 Seiten × 3 Breiten ohne Befund. Wächter: `e2e/tests/menues.spec.ts` (mit echter Animation;
Gegenprobe: alte CSS → rot auf allen Breiten).

Neu für den Betrieb einer Verwaltung (Lücken aus der Simulation Bewirtschaftung / Buchhaltung / Geschäftsleitung):

| Gruppe | Lücke | Umsetzung |
|---|---|---|
| Bewirtschaftung | Leerstand nur als Zahl, Verlauf oder Befund zwischen allen Objekten | **Leerstands-Cockpit** `/neu/leerstand/`: leer und «wird frei» (180 Tage, ohne Nachmieter), Leerdauer, Netto-Ausfall je Monat und aufgelaufen (geschätzt), Inserat und offene Bewerbungen, EIN nächster Schritt je Einheit (Mietzins festlegen → Ausschreiben → Bewerbungen prüfen → Vertrag erfassen); Filter Zustand und Objektart; CSV. Belegungsregel aus `faelle.objekte._belegung` — dieselbe wie Objekt- und Liegenschaftsliste |
| Geschäftsleitung | Keine Sicht auf Verteilung der Arbeit und Termintreue | **Team & Auslastung** `/neu/team/` (nur Inhaber/Verwalter): je Person Tickets (überfällig), Fälle (liegengeblieben), Termine der Woche, betreute Liegenschaften, Abwesenheit mit Vertretung, Lastbalken; was niemandem zugeteilt ist (Absprung `?zustaendig=niemand` in die Ticketliste); offene Tickets nach Alter, Ø Durchlaufzeit, Termintreue |

Schon vorhanden und deshalb nicht neu gebaut: Ticket-Board, Mahnlauf mit Trockenlauf, OP-Altersstruktur
(`/neu/mahnwesen/aging/`), Debitoren-Ampel, Portfolio, Leerstands-Verlauf.

Wächter: `core/tests/test_leerstand_team.py` (10 Tests; Gegenprobe 6 von 7 Mutanten erkannt, der siebte ist
fachlich gleichwertig). Bekannte Grenze: Die Ticket-Durchlaufzeit misst bis zur letzten Änderung, weil das Ticket
kein eigenes Erledigt-Datum führt — die Seite sagt das.

## Nachtrag 26.10.2026 — UX-Refactoring V11 (Assistenten und Hilfe)

Analyse Modul für Modul, Massnahmenplan freigegeben, dann umgesetzt. Befunde und Umsetzung:

| Befund | Umsetzung |
|---|---|
| Mieter- und Eigentümerportal ohne Navigation am Desktop (Leiste nur als Telefon-Schublade) | Leiste wird ab 1024 px zur Ember-Kopfleiste; Kacheln ohne Rand, Badge lesbar |
| «Person erfassen»: 59 Felder auf einer halben Bildschirmbreite | Assistent in 5 Schritten (Art & Name, Kontakt, Adresse, Details optional, Zahlung & Notizen optional) + Prüfen |
| Liegenschaft, Kündigung, Weiterverrechnung als lange Einzelformulare | je ein Assistent; Weiterverrechnung: erst «an einen Mieter» oder «auf alle verteilen» wählen, Kennzahlen oben |
| Nebenkostenabrechnung: Schritte über Seiten und Knöpfe verstreut | Prozessleiste mit sieben Schritten und Zustand; neue Periode als Assistent mit Schnellwahl (Vorjahr, Heizperiode, laufendes Jahr) |
| Fachbegriffe nur als `title`-Tooltip erklärt | Katalog mit 45 Begriffen (`core/hilfe.py`) und ⓘ-Blasen auf 23 Seiten; sechs «So funktioniert's»-Kästen |
| Formulare brachen auf Tablet-Breite um (Tailwind-Grids ohne Ember-Abstände) | Ember-Raster `fw-raster` / `fw-formseite`, 172 Grids umgestellt |
| Heute zeigte zweimal dieselben Zahlen | dritte Zahl: Termine diese Woche |

Bewusst nicht umgesetzt: Bearbeiten in einer Schublade (Akten-Detail, Kreditoren) — es hätte die
Bearbeitungsseiten und ihre Wächter verdoppelt; Bearbeiten bleibt eine Seite mit `fw-formseite`.
Die Übersichten Finanzen, Berichte und Läufe waren schon Ember-konsistent und blieben.

Übersetzungen der neuen Texte (fr/it/en) sind maschinell erstellt und brauchen eine fachliche Durchsicht.

Wächter: `core/tests/test_bausteine.py` (15 Tests: jeder Hilfe-Schlüssel steht im Katalog und ist
übersetzt, Prozesszustände und ihre Links, Assistent ohne verlorene Felder; Gegenprobe: falscher
Schlüssel, falscher Zustand, verschwundenes Feld → rot), `e2e/tests/assistenten.spec.ts` (1440 und 390 px:
Pflichtfeld hält an, Zurück behält Eingaben, Prüfen zeigt die Angaben, Hilfe-Blase im Bild,
Prozessleiste ohne Querscrollen).

## Nachtrag 26.10.2026 — Zahlungs-Cockpit V12 (Sonderfälle im Zahlungseingang)

Analyse des Buchhaltungs- und Zahlungsmoduls, Konzept freigegeben, umgesetzt. Bestehende
Buchungslogik (Periodensperre, Storno über die Bank-Referenz, Zeilensperren, gelernter
Absender) bleibt; neu ist, was im Alltag fehlte:

| Sonderfall | Umsetzung | Buchung |
|---|---|---|
| Sammelzahlung (eine Zahlung, mehrere Posten/Verträge/Mieter) | Split-Screen-Assistent «Zuordnen / Aufteilen»; Vorschlag: genannte Mieter, deren Posten zusammen den Betrag ergeben; Import: Überzahlung per Referenz mit weiterem passendem Posten desselben Mieters wird Klärungsfall statt stilles Guthaben | je Teil Parkkonto an 1100; Teile `…:teilN`, Rest `…:offen` / `:rest` / `:zurueck`; Storno nur als Ganzes |
| Teilzahlung | Spur «Teilzahlungen» mit Fortschritt, Mahnstand und nächstem Schritt: Rest mahnen, Ratenplan, Kleindifferenz ausbuchen (≤ CHF 5.00); «Teilweise bezahlt» auch im Mieterportal | Rest bleibt offen und läuft in den Mahnlauf (bestehend) |
| Überzahlung / Guthaben | Verwendung je Guthaben: mit nächster Rechnung verrechnen (Standard für neue Guthaben), für die NK-Abrechnung reservieren, offen lassen; Rückerstattung bleibt ein Knopf | Sollstellung bzw. NK-Verbuchen tilgen automatisch 2030 an 1100 — nur die Rechnung, die der Lauf gerade erzeugt hat (Korrektur unten) |
| Unklare Zahlung | Spur «Klärungsfälle»: Alter, Vorschlag mit Begründung, Notiz, Zuordnen/Aufteilen, an den Absender zurück; ab 10 Tagen Warnmarke und Pendenz | 1190 an 1100 / 1190 an Bank |
| Kaution auf dem Mietzinskonto | «Als Kaution verbuchen» (nur exakter Betrag, Vertrag ohne bilanzierte Kaution) + Pendenz «auf Sperrkonto überweisen» | 1190 an 2010 mit `Mietkaution [V…]` — zählt für Freigabe, keine Doppelbuchung |
| Rückbuchung der Bank | Belastung im Bank-Eingang → «Als Rückbuchung erfassen» (Kandidaten: gleicher Betrag, 120 Tage) | Storno der Zahlung = Buchung der Belastung; Rechnung wieder offen |

Bestand: Guthaben, die vor V12 entstanden, stehen auf «offen lassen» (Migration
`finance.0046`) und werden nicht ungefragt verrechnet.

Wächter: `core/tests/test_zahlungsklaerung.py` (25 Tests; Gegenprobe: sechs Mutanten —
Suche ohne Mandantengrenze, Storno eines Teils allein, Kaution ohne Vertragsmarke, Lernen bei
mehreren Mietern, Sollstellung ohne Verrechnung, Import ohne Sammelzahlungs-Hinweis — alle
rot), `e2e/tests/zahlungs-cockpit.spec.ts` (1440 und 390 px).

Nebenbei behoben: Ein zurückerstattetes Guthaben stand im Mieterkonto (Team und Portal)
weiter als Haben — der Mieter schien ein Guthaben zu haben, das er längst zurückbekommen
hatte. Die Rückerstattung (Buchung 2030 an Bank) erscheint jetzt als Soll-Zeile.


### Korrektur 26.10.2026 — Fehlzuordnung im Betrieb

Fall: Die Zahlung eines Fremden (CHF 100, ohne Referenz) wurde im Assistenten auf die
Oktobermiete eines Parkplatzmieters vorbefüllt — nur weil der Betrag passte. Ein Klick
genügte: Miete «bezahlt», 257d-Frist «durch Zahlung erledigt», Zahlungsverzugsfall
geschlossen, Absender für diesen Mieter gelernt. Der Mieter mit Rückstand und letzter
Mahnung war aus allen Listen verschwunden.

| Was | Jetzt |
|---|---|
| Vorbefüllen | nur bei Referenz, gelerntem Absender, Name oder Sammelzahlung; «Betrag passt» allein ist als «nur Betrag» markiert und füllt nichts vor |
| Falsch zugeordnet | «Zuordnung aufheben» (Spur Klärungsfälle → «Zugeordnete Klärungsfälle», «Kürzlich abgeglichen»): Zahlung samt Teilen zurück auf 1190, Bankbuchung bleibt unberührt, Rechnungen wieder offen, gelernter Absender gelöscht |
| Stattdessen storniert | «Stornierte Zuordnungen» / «Stornierte Guthaben-Verrechnungen» (60 Tage): Eingang neu buchen — als Klärungsfall (1190) bzw. Guthaben (2030, «offen lassen») |
| 257d | `zahlungsverzug._wieder_oeffnen`: Ist der gemahnte Rückstand einer «durch Zahlung» erledigten Frist wieder offen (Storno, Rückbuchung, aufgehobene Zuordnung), läuft die Frist wieder, der Sperrvermerk für die Kündigung fällt weg, der Fall ist wieder offen |
| Guthaben «mit nächster Rechnung» | tilgt nur die neu erzeugte Monats- bzw. NK-Rechnung, nie Rückstände oder Mahngebühren (Art. 86 OR); jede Verrechnung im Logbuch; «Verrechnung rückgängig» hebt nur 2030 an 1100 auf |
| Rest ohne Bankreferenz | bekommt `MAN<id>`, damit ein Storno ihn erreicht |

Wächter: `FehlzuordnungTests` und `KorrekturVerrechnungTests` in
`core/tests/test_zahlungsklaerung.py`; Gegenprobe mit sieben Mutanten (Vorbefüllen ohne
Beleg, kein Wiederöffnen, Sperrvermerk bleibt, Absender bleibt, Bankbuchung wird
storniert/neu gebucht, 1190 nicht wiederherstellbar, zurücküberwiesener Teil) — alle rot.

## Production-Readiness-Check (26./27.10.2026)

Tiefen-Audit aller Routen (Browser-Crawl: 129 Seitentypen im Team-Bereich, Mieter- und
Eigentümerportal, je 1440 und 390 px) und Fachprüfung Finanzen/Recht, Verträge,
Abnahme. Ergebnis nach dem Umbau: keine Seite ausserhalb der neuen Hülle, kein
Querüberlauf, keine alte Farbklasse im DOM; Farbwächter 135 → 55 (Rest: PDF-/Mail-
Vorlagen und Admin-Tabellen, bewusst).

| Bereich | Umgesetzt |
|---|---|
| Design | QR-Schadenformular ohne 3-s-Ladekreisel; tote Vorlagen gelöscht (`core/mietzins_form.html`, `fw/_menu_item.html`); alte Reiter-Umschaltung entfernt; Admin (Unfold) im Ember-Schema |
| Ratenplan | Mahnsperre nur für die gedeckten Forderungen (`core/services/mahnsperre.py`), neue Mieten werden gemahnt; Schreiben mit Schuldanerkennung (Art. 82 SchKG); Hilfe, Übersetzung, Einstiege aus Mahnwesen/Akte; Handschalter `Mieter.mahnsperre` auch in der Mahnwesen-Liste |
| Betreibung | Rechtsvorschlag nach Tag 10 nur Warnung; Fortsetzungsfrist mit Stillstand (Art. 88 Abs. 2 SchKG); Stände Rechtsöffnung beantragt/erteilt (prov./def.), Pfändung; Zins, Grund, mehrere Forderungen; Mahnlauf überspringt Betriebenes; Zahlung schliesst die Betreibung; Tilgung nach Art. 87 OR; Datenblatt Betreibungsbegehren (PDF); Kosten belasten; Verlustschein → Abschreibung 3805; Fristen-Pendenzen; Assistent; Anzeige auf Vertrag und Person |
| Abnahme | Abschluss mit Unterschriftsregeln für beide Wege; Warnung ohne Lebensdauer; Mängelrüge Abnahme + 2 Arbeitstage, erledigt erst mit Versand; neue Adresse und Allgemeinzustand vor Ort; Foto-Zuordnung; Löschschutz; PDF vollständig mit Seitenzahlen; Nachrüge versteckter Mängel (Art. 267a Abs. 3); Schlüsselersatz; Handwerker aus Mangel; Depot-Text nur bei Sperrkonto; Foto-Ablage je Mandant; Bestandsschutz für alte Protokolle (rentals.0047) |
| Mietzins | Folgeanpassung auf dem effektiven Mietzins; Vorrang vor Gratismonat/Komponenten; Ablauf Entwurf → versandt (Zugang + 30 Tage Anfechtung) → wirksam/angefochten, Vorschau bucht nicht; Massenanpassung ohne Index/Staffel; Basisdaten fortgeschrieben; Senkungs-Pendenzen gegen die effektive Basis; Assistent mit Live-Rechnung und beziffertem Vorbehalt; Antwortbrief Herabsetzungsbegehren; Indexsenkung; Art. 12 statt 16 VMWG; versandte Anpassung nur durch die Verwaltung löschbar |
| Kündigung | Termine aus Ziffern gelesen, leeres Feld nicht als «jedes Monatsende»; Zugang mit Zustellpuffer; Art. 266m Zustimmung; Art. 264 Ersatzmieter; strukturierte ausserordentliche Gründe; Erstreckung wirkt auf Vertragsende |
| Amtliche Formulare | Nur mit erfasstem Kanton (keine PLZ-Schätzung bei Überlappung); ausserhalb BE/SO/ZH sperrende Warnung, Nachbildung nur als Entwurf mit Wasserzeichen |

### Offen — juristische Prüfung bzw. Fachentscheid (bewusst nicht geraten)

- Referenzzins ab 5 % (VMWG Art. 13 Abs. 1): Sätze im Repo nicht belegt; Hinweis «ab 5 % von Hand prüfen» bleibt.
- Art. 14 VMWG (wertvermehrende Investitionen): kein Rechner.
- Fristen für Art. 257f Abs. 3, 266h, 266k: Datum ist Pflicht, die Seite warnt; keine Berechnung.
- Verrechnung bei angefochtener Anpassung bis zum Entscheid: Buchung bleibt, Pendenz verlangt die Prüfung.
- Zinsbasis 360 Tage (Verzugszins), Stillstand Art. 88 Abs. 2 als Differenz gezählt; Kostenbuchung Betreibung 1100/3600 (wie Mahngebühr) statt Kostenvorschuss 1110/1020 (STWEG).
- Mahngebühren setzen eine vertragliche Grundlage voraus (Hinweis in der Hilfe).
- Rechtstexte der Abnahme: «Für nicht gemeldete Mängel haftet der Mieter» (Einzug), Haftungsanerkennung durch Unterschrift, Depot-Verrechnung bei Kautionsversicherung (`rueckgabe_maengelruege_pdf`), Wortlaut Nachrüge, Regel «2 Arbeitstage» (ohne Feiertage), Vorsatz ohne Zeitwertabzug, Lebensdauerwerte (`raumkatalog.py`) gegen die paritätische Tabelle.
- Texte Schuldanerkennung und Betreibungs-Datenblatt.
- Originalformulare für die übrigen 23 Kantone.

Wächter: `test_betreibung` (29), `test_zahlungsvereinbarung_sperre` (10), `test_abnahme_produktionsreife` (40), Mietzins-/Kündigungstests; Gegenproben je Test (u. a. 53 von 54 bzw. 28 von 29 Mutanten sofort rot, die übrigen nach Korrektur).
