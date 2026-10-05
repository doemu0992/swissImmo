# STWEG-Modul (Stockwerkeigentum)

Stand: 04.10.2026. App `stweg`, dazu Felder an `portfolio.Liegenschaft` / `Einheit`
und `finance.Erneuerungsfonds`.

## Grundsatz

Eine STWEG erzielt keinen Ertrag, sie verteilt Kosten nach Wertquoten. Alles, was
im Mietmodul auf Ertrag und Mieter zielt (Sollstellung, Mietzinsanpassung, Mahnung),
ist hier nicht zuständig. Rechtswerte stehen nicht fest im Code (siehe «Offen»).

## Was es gibt

| Bereich | Wo |
|---|---|
| Art der Liegenschaft `MIETE`/`STWEG`, Status, `wertquote_total` | `portfolio/models.py` |
| Wertquoten-Prüfung (Summe = Total, sonst Ausnahme) | `stweg/validierung.py`, Hook in `Liegenschaft.save()` |
| Verteilung auf den Rappen (grösster Rest) | `stweg/verteilung.py` |
| Erneuerungsfonds: Einlage nach Quoten, Entnahme | `stweg/fonds.py`, `finance.ErneuerungsfondsBewegung` |
| Jahresabrechnung: Kosten − Akonto = Zahllast/Guthaben | `stweg/services.py` |
| Versammlung, Traktanden, Anwesenheit, Stimmen | `stweg/models.py`, `stweg/beschluss.py` |
| Einladung/Protokoll als PDF per E-Mail, Versandprotokoll | `stweg/versammlung.py`, `stweg/pdf.py` |
| Vollmachten (Portal und Verwaltung), wirken beim Eröffnen als «vertreten» | `stweg/vollmacht.py` |
| Zirkularbeschluss: Antrag, Frist, Abstimmung im Portal, Feststellung, Ergebnisversand | `stweg/zirkular.py` |
| Abrechnung mit Kostenschnappschuss, PDF, Akonto, Fondseinlage/-entnahme | `stweg/views.py` (`/neu/stweg/<id>/abrechnung/`), `stweg/pdf.py` |
| Einheiten, Wertquoten und Eigentümer zuteilen, Gemeinschaft aktivieren | `/neu/stweg/<id>/einheiten/` |
| Verteilschlüssel (Wertquote, Fläche, Volumen, eigene Anteile), Kostenart → Schlüssel | `stweg/schluessel.py`, `/neu/stweg/<id>/schluessel/` |
| Budget → Beschluss → Akonto-Rechnungen (Raten, PDF mit QR-Zahlteil, Versand) | `stweg/budget.py`, `/neu/stweg/<id>/budget/` |
| Kontokorrent je Einheit, Fondsstand | `stweg/konto.py` (Portal und Verwaltung) |
| E-Voting: digitale Teilnahme, Stimme im Portal, Ereignisprotokoll | `stweg/evoting.py`, `StimmeEreignis` |
| Dokumenten-Repository mit Pflichtkategorien | `stweg/dokumente.py`, `/neu/stweg/<id>/dokumente/` |
| Anfragen, Aufgaben, offene Punkte (als `core.Pendenz`) | `stweg/anfragen.py`, `stweg/aufgaben.py` |
| Oberfläche Verwaltung | `/neu/stweg/` (`stweg/views.py`) |
| Eigentümerportal | `/portal/stweg/` (`stweg/portal.py`) |

## Buchhaltung

Hauptbuch-Anbindung (`stweg/hauptbuch.py`):

| Ereignis | Buchung |
|---|---|
| Rate wird vorgeschrieben (Budget genehmigt) | Soll 1110 Forderungen Stockwerkeigentümer / Haben 2035 Akonto-Beiträge |
| Zahlung, direkt erfasst | Soll 1020 Bank / Haben 1110 |
| Zahlung aus dem Kontoauszug-Import (geparkt auf 1190) | Soll 1190 / Haben 1110 — die Bank steht schon im Import, sie wird nicht nochmals gebucht |
| Abschluss der Abrechnung, je Einheit | Soll 2035 / Haben 3100 (Vorschreibungen freigeben); Nachzahlung: Soll 1110 / Haben 3100; Guthaben: Soll 3100 / Haben 1110 |
| Storno einer Zahlung | Gegenbuchung (`storniere_buchung`); ein zugeordneter Importeingang liegt wieder auf 1190 |

3100 «Beiträge Stockwerkeigentümer» ist Ertrag in Höhe der Kostenanteile; die Aufwandskonten tragen die
Kosten, das Jahresergebnis der Gemeinschaft ist damit null, und der Saldo auf 1110 je Einheit entspricht dem
Kontokorrent. Eine gesperrte Periode (`Organisation.buchung_gesperrt_bis`) verhindert die Genehmigung eines
Budgets bzw. den Abschluss ganz (nichts wird halb gebucht). Zahlungen für den Erneuerungsfonds werden mit
Zweck «fonds» erfasst und decken nie den Kostenanteil. Der Abschluss bucht nur einmal.

Der Fonds gehört der Gemeinschaft, nicht der Verwaltung: Einlage = Soll 1110
(Forderungen Stockwerkeigentümer) an Haben 2800 (Erneuerungsfonds, **Passivum**);
Entnahme = Soll 2800 an Haben 1020 (Bank). Kein Aufwand, kein Ertrag.
`run_erneuerungsfonds_einlage` (Aufwand 6900 an 2800) bleibt Mietliegenschaften
vorbehalten und überspringt STWEG.

## Verteilschlüssel

Je Gemeinschaft beliebig viele. Ein Schlüssel liefert je Einheit ein **Gewicht**; der Betrag wird im
Verhältnis der Gewichte verteilt (grösster Rest, Summe exakt). Gewicht 0 = trägt nichts.

* `wertquote`, `flaeche` (m²), `volumen` (m³) lesen die Einheit; `manuell` hat je Einheit einen eigenen Anteil.
* **Lift:** `lift_schluessel()` setzt Einheiten auf der Etage «EG» (Schreibweisen `eg`, `erdgeschoss`,
  `parterre`, `0`) auf 0, alle anderen auf ihre Wertquote. Das Erdgeschoss trägt damit nicht «keinen
  Eintrag», sondern ausdrücklich den Anteil 0 — und mathematisch ist 0 von jeder Summe exakt 0,00 CHF
  (getestet mit 400 zufälligen Beträgen).
* **Lücken sind Fehler, keine stillen Nullen:** fehlt eine Fläche oder ein Anteil, wird weder abgerechnet
  noch ein Budget vorgelegt. Sonst fiele eine Einheit unbemerkt aus der Verteilung.
* Jede Kostenart (Buchungskonto) wird einem Schlüssel zugeordnet; ohne Zuordnung gilt der
  Standardschlüssel «Allgemeine Wertquote» (genau einer je Gemeinschaft, per Constraint).
* Der Eigentümerbeleg zeigt je Schlüssel Gewicht, Kosten und Anteil (`StwegAbrechnungAnteil`).
* **Einzelkosten:** Eine Rechnung, die an einer einzelnen Einheit hängt, wird dieser Einheit (bei einem
  Nebenraum dem Hauptobjekt) direkt belastet («Direkt belastet»). Bis dahin fiel sie aus der Abrechnung:
  die Gemeinschaft bezahlte, niemand wurde belastet.

## Budget, Beschluss und Akonto

1. Budget je Jahr mit Positionen (Betrag + Schlüssel), Raten (1, 2, 3, 4, 6, 12) und erster Fälligkeit.
2. «Vorlegen» prüft Wertquoten und Schlüssel; eine Änderung danach setzt auf «Entwurf» zurück.
3. Das Budget wird einem **Traktandum** zugewiesen (`Traktandum.budget`). `beschluss.feststellen` löst bei
   «angenommen» `budget_genehmigen` aus (atomar: scheitert das Budget, scheitert die Feststellung);
   bei «abgelehnt» wird es «abgelehnt», bei «vertagt» bleibt alles offen. Dasselbe gilt für einen
   **Zirkularbeschluss** (`Zirkularbeschluss.budget`, beim Anlegen wählbar). Jede Rate wird ins Hauptbuch gebucht.
4. Pro Einheit: Jahresbetrag = Summe der Anteile an den Positionen (je Schlüssel einmal verteilt), in
   gleich grosse Raten, die den Jahresbetrag exakt ergeben. Die Aufteilung nach Schlüsseln wird je
   Vorschreibung als Momentaufnahme gespeichert.
5. PDF «Akonto-Rechnung» je Eigentümer mit QR-Zahlteil je Rate (nur mit gültiger IBAN der Gemeinschaft),
   Versand per E-Mail wiederholbar (`versendet_am`); ohne E-Mail-Adresse wird «per Post» gemeldet.

Der Erneuerungsfonds ist **nicht** Teil des Budgets (Einlagen sind keine Kosten; sie laufen über `stweg.fonds`).

**Kontokorrent** (`stweg/konto.py`): Vorschreibung (Soll), Zahlung (Haben), und nach einer abgeschlossenen
Jahresabrechnung ein «Abgleich» (Kostenanteil − vorgeschriebene Raten). Danach ist der Saldo genau
Kostenanteil − Zahlungen. Der Saldo «fällig» zählt nur Bewegungen bis heute.

## E-Voting und Mehrheiten

* Bei der Versammlung «E-Voting im Portal» einschalten (optional bis zu einem Zeitpunkt). Der Eigentümer
  erklärt im Portal die Teilnahme (setzt seine Einheiten auf «anwesend»; eine Vollmacht wird dabei
  übersteuert, wie im Saal) und stimmt je Traktandum und eigener Einheit ab. Es handelt nur die
  Hauptansprechperson; Miteigentümer lesen.
* Jede Abgabe/Änderung/Rücknahme steht unveränderlich in `StimmeEreignis` (Zeit, Weg, Person, Vorwert).
  Nach der Feststellung des Ergebnisses sind die Stimmen **gesperrt** (Portal und Verwaltung).
* Das System rechnet einen Vorschlag; festgestellt wird er von einer Person.
* Mehrheitsarten (Daten, keine Rechtsnorm): `einfach_koepfe`, `einfach_quoten`, `doppelt` (Ja > Nein
  nach Köpfen UND Quoten), `doppelt_aller` (mehr als die Hälfte ALLER Köpfe UND ALLER Quoten),
  **`doppelt_anwesende`** (mehr als die Hälfte der ANWESENDEN Köpfe UND mehr als die Hälfte ALLER
  Quoten), `einstimmig`, `kenntnisnahme`. Welche für ein Geschäft verlangt ist, entscheidet die
  Verwaltung nach Gesetz und Reglement. `doppelt_anwesende` gibt es nur in der Versammlung.
* Köpfe: ein Eigentümer = ein Kopf, auch mit mehreren Einheiten. Enthaltungen sind keine Stimme, zählen
  bei `doppelt_anwesende` aber als anwesend. «Mehr als die Hälfte» heisst strikt grösser — genau 50 %
  genügt nicht.
* Geprüft gegen eine unabhängige Bruchrechnung über alle 3125 Zustände von fünf Einheiten (über
  18 000 Kombinationen mit allen Mehrheitsarten).

## Dokumenten-Repository

Pflichtkategorien: Begründungsakt, STWEG-Reglement, Nutzungs- und Verwaltungsordnung (jeweils die
jüngste gültige Fassung zählt, ältere bleiben als Verlauf), Versicherungspolice (mehrere parallel,
mindestens eine nicht abgelaufene), Jahresrechnung (automatisch: jede abgeschlossene Abrechnung ist für
ihre Eigentümer ein Dokument). Fehlendes oder Abgelaufenes erscheint als Hinweis und als `core.Pendenz`
(`stweg:dokument:<kategorie>`, idempotent, erledigt sich beim Hochladen).

Zugriff: Upload nur PDF/Bild (Inhalt geprüft, 10 MB). Ausgeliefert wird nie über `/media/`, sondern über
`/neu/stweg/dokument/<id>/` (Rolle + Mandant) bzw. `/portal/stweg/dokument/<id>/` (nur freigegebene
Dokumente, nur Gemeinschaften, an denen der Eigentümer beteiligt ist; sonst 404).

## Inkasso: Mahnung, Retentionsrecht, Gemeinschaftspfandrecht

Ein Stockwerkeigentümer ist Eigentümer, nicht Mieter: **Es gibt nie eine Kündigungsandrohung nach Art. 257d OR.**
Technisch erzwungen an drei Stellen: `inkasso.ohne_kuendigung` (Mahntext, schlägt zu bei «kündig»/«257d»),
`core/services/zahlungsverzug.py` (`EigentuemerSchutz` → 403; `eskalation_257d` liefert für einen Eigentümer nichts;
der Mietmahnbrief stuft die letzte Stufe herab) und der Mahn-PDF-Pfad des Mietmoduls.

* **Fall:** `StwegInkassoFall` — höchstens ein offener je Einheit. **Mahnungen:** drei Stufen (interne Richtlinie,
  keine gesetzliche Voraussetzung; Frist 10 Tage = Voreinstellung). Eine nächste Stufe gibt es erst, wenn die
  vorige versendet ist.
* **Retentionsrecht (Art. 712k ZGB):** wird mit den betroffenen Sachen festgehalten, PDF-Mitteilung.
* **Gemeinschaftspfandrecht (Art. 712i ZGB):** Button «Gemeinschaftspfandrecht anmelden». Die Pfandsumme
  enthält **nur Forderungen der letzten 36 Monate**: Grenze = Stichtag − 36 Monate (Monatsende-Klammerung),
  eine Forderung zählt, wenn ihr Datum **strikt nach** der Grenze liegt. Forderungsdatum = Fälligkeit der Rate,
  bei Abrechnungen der 31.12. des Abrechnungsjahres. Ältere Forderungen stehen getrennt im PDF («nicht
  pfandberechtigt») und nicht in der Pfandsumme; der Stand wird als Schnappschuss in `StwegPfandrecht` gespeichert.
  PDF für das Grundbuchamt: Entwurf — Grundbuchblatt/EGRID sind Platzhalter, die Unterschrift fehlt.
* **Tilgungsreihenfolge:** Zahlung mit gewählter Rate (`StwegAkonto.vorschreibung`, Art. 86 OR) tilgt diese;
  sonst die älteste offene Forderung (FIFO). Ohne diese Regel würde eine späte Zahlung alte Forderungen tilgen und die
  Pfandsumme überschätzen.
* **Verzugszins:** Das System kennt keinen Satz. Die Gemeinschaft trägt ihn bei den Vorgaben ein (mit Quelle, zu
  bestätigen); leer = es wird nichts berechnet. Berechnung: einfacher Zins auf die heute OFFENEN Beträge vom Tag nach
  der Fälligkeit bis zum Stichtag (Tage/365, auf Rappen). Zins auf spät bezahlte Teile fehlt (Vereinfachung). Die Mahnung
  nennt den Zins erst nach Bestätigung des Satzes, immer ausserhalb des Totals; in der Pfandsumme steht er nie.
* **Handänderung** (`stweg/eigentuemer.py`, «Handänderung erfassen» auf der Einheitenseite): Datum, bisheriger und
  neuer Eigentümer, Miteigentümer werden gelöscht. Jede Forderung hat einen Schuldner (Eigentümer am Fälligkeitstag;
  Übergangstag zählt zum neuen; bei Abrechnungen der in der Abrechnung genannte). Die Mahnung geht nur an den heutigen
  Eigentümer und nennt nur seine Forderungen; Forderungen gegen einen früheren Eigentümer werden auf der Inkassoseite
  ausgewiesen, das Gemeinschaftspfandrecht umfasst sie (haftet am Anteil — Annahme, rechtlich zu bestätigen). Nicht
  abgebildet: anteilige Aufteilung auf den Übergangstag, Absprachen im Kaufvertrag.
* **Nicht modelliert:** Kostenvorschuss Grundbuchamt, Mahnkosten. Die rechtliche Lesart (Forderungsdatum, Tilgung,
  36 Monate, Handänderung, Zins) ist durch eine Fachperson zu bestätigen.

## Integritätsprüfung und Audit

`python manage.py stweg_audit [--organisation ID] [--liegenschaft ID]` (Exit-Code 1 bei Fehler) und
`stweg.integritaet.pruefe(lg)`: Wertquoten 1000/1000, Einheiten ohne Eigentümer/E-Mail, Schlüssel-Lücken,
Fonds-Bestand gegen Bewegungen (auf der Gemeinschaftsseite als «Prüfung der Daten» sichtbar), Konten 2035/2800 als Passiva, Zahlungen ohne Buchung und der **Abgleich Hauptbuch ↔
Fachtabellen** (1110, 2035, 3100, 2800). **Lift nach Stockwerk:** `schluessel.lift_nach_stockwerk` (Gewicht = Stockwerknummer,
EG = 0; Unlesbares bricht ab, es wird nicht geraten). Das Reglement kann anderes vorsehen.

Das Portal zeigt dem Eigentümer bei den Fonds-Einlagen, was davon noch offen ist.

## Geschäftsjahr-Simulation

`stweg/test_geschaeftsjahr.py` spielt eine Gemeinschaft (Quoten 200/300/500) durch: Budget per Beschluss (Doppeltes
Mehr), Akonto, Rechnungen, Fonds-Einlage, Abrechnung, Mahnungen, Pfandrecht — mit Hauptbuch-Abgleich auf den Rappen.

## Korrekturen an der Dokumentation

* `ENTSCHEIDE-V7.md` D9 («bleibt Vorschlag, nicht gebaut») gilt nicht mehr: Das
  Modul wurde auf ausdrücklichen Auftrag gebaut. `PLAN-V7.md` M9 nennt die App
  `stwe` mit `Versammlung/Traktandum/Beschluss/Wertquote`; gebaut ist sie als
  `stweg`, `Wertquote` liegt an `Einheit`, ein `Beschluss` ist das festgestellte
  Ergebnis am `Traktandum`.

## Offen — bewusst nicht getan

* **Rechtswerte nicht im Code.** Einladungsfrist, Quorum (Beschlussfähigkeit) und Anfechtungsfrist trägt
  eine Person je Gemeinschaft ein, mit Quelle, und bestätigt sie (`/neu/stweg/<id>/vorgaben/`,
  `stweg/vorgaben.py`). Leer heisst: es wird nicht beurteilt; bis zur Bestätigung zeigt die
  Gemeinschaftsseite einen Hinweis. Eine Änderung der Zahlen nimmt die Bestätigung zurück. Die Systemvorgabe
  der Einladungsfrist (10 Tage) bleibt ausdrücklich ungeprüft. Welche Mehrheitsart ein Geschäft verlangt,
  wählt die Verwaltung je Traktandum; beim Zirkularbeschluss ist «einstimmig» vorgegeben, und ob ein
  Zirkularbeschluss für ein Geschäft zulässig ist, entscheidet die Verwaltung. **Vor Gebrauch juristisch
  bestätigen — das Programm kennt diese Werte nicht und setzt keine ein.**
* Fehlt das Quorum, blockiert `feststellen` ein Ergebnis («angenommen»/«abgelehnt»); «trotzdem feststellen»
  ist möglich, steht aber im Protokoll. «Vertagt» ist immer möglich.
* Vollmachten sind digital erfasst (Name des Vertreters); optional hängt der Scan der unterschriebenen
  Vollmacht daran (PDF/Bild, geschützt ausgeliefert). Das System prüft keine Unterschrift und führt
  keine Beglaubigung.
* Oberfläche, Portal, Meldungen der Services und die Bezeichnungen (Mehrheitsarten, Status) sind
  viersprachig (de/en/fr/it); Einladung, Protokoll, Abrechnung, Zirkular und Akonto-Rechnung (PDF/Mail)
  bleiben deutsch (Entscheid D11). Mail-Texte und in der Datenbank abgelegte Texte (Pendenzen, Versandfehler)
  stehen deutsch.
* Zahlungen aus der Zeit vor der Hauptbuch-Anbindung haben keine Buchung (`StwegAkonto.buchung` leer) und
  werden nicht nachgebucht; ein Storno betrifft nur gebuchte Zahlungen.
* Einzelspeicherung von Einheiten prüft die Quoten nicht; geprüft wird bei
  Aktivierung, Einlage, Einladung, Zirkularversand und Abrechnung.
  `QuerySet.update()` umgeht `save()`.
* Eine STWEG wird im Liegenschaftsformular angelegt (Art «Stockwerkeigentum»); das
  Feld «Eigentümer» entfällt dort bewusst (`Liegenschaft.eigentuemer` bleibt leer,
  denn Mietlogik und Portal lesen es). Danach führt die Seite «Einheiten und
  Eigentümer» durch Quoten, Eigentümer und Aktivierung.
* **QR-Zahlteil:** Der Beleg eines Eigentümers mit Nachzahlung (abgeschlossene
  Abrechnung) enthält einen QR-Zahlteil auf das IBAN der Gemeinschaft; ohne gültige
  IBAN steht nur ein Überweisungshinweis.
* **Portal-Anfrage:** Die Verwaltung wird per Mail benachrichtigt (betreuende
  Person, sonst Organisations-Adresse). Fehlt eine Adresse oder scheitert der
  Versand, wird nur geloggt — die Anfrage geht nie verloren.
* **Miteigentum:** `Einheit.miteigentuemer` (weitere Personen). Sie erhalten
  Einladung und sehen Unterlagen im Portal; Stimme, Vollmacht und Anfrage bleiben
  bei der Hauptansprechperson (eine Einheit, eine Stimme).
* **Nebenräume** (`gehoert_zu` gesetzt) haben weder Quote noch Stimme und zählen
  nirgends mit (`stimm_einheiten`). Eine selbständige Garage mit eigener Quote wird
  als eigenständiges Objekt erfasst.
* **Wertquote-Vorgabe:** Das Feld stammt aus dem Mietmodul (Vorgabe 10). Neue
  Einheiten einer STWEG und GWR-importierte Einheiten bekommen 0.
