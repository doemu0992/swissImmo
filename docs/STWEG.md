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
   bei «abgelehnt» wird es «abgelehnt», bei «vertagt» bleibt alles offen.
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

## Korrekturen an der Dokumentation

* `ENTSCHEIDE-V7.md` D9 («bleibt Vorschlag, nicht gebaut») gilt nicht mehr: Das
  Modul wurde auf ausdrücklichen Auftrag gebaut. `PLAN-V7.md` M9 nennt die App
  `stwe` mit `Versammlung/Traktandum/Beschluss/Wertquote`; gebaut ist sie als
  `stweg`, `Wertquote` liegt an `Einheit`, ein `Beschluss` ist das festgestellte
  Ergebnis am `Traktandum`.

## Offen — bewusst nicht getan

* **Rechtswerte nicht geprüft.** Einladungsfrist (Vorgabe 10 Tage, je Versammlung
  einstellbar) und erforderliche Mehrheit (je Traktandum bzw. Zirkularbeschluss
  gewählt: Köpfe, Quoten, beides, aller, einstimmig) sind Daten, keine Rechtsnorm.
  Beim Zirkularbeschluss ist die strengste Art (einstimmig) vorgegeben; ob ein
  Zirkularbeschluss für ein Geschäft überhaupt zulässig ist, entscheidet die
  Verwaltung. Vor Gebrauch juristisch bestätigen.
* Beschlussfähigkeit und Anfechtungsfrist werden nicht beurteilt bzw. geführt.
* Die Jahresabrechnung bucht nicht ins Hauptbuch (nur der Fonds tut es). Das ist
  eine Buchhaltungsentscheid (Akonto gegen Bank 1020 riskiert Doppelbuchung mit
  dem Bankabgleich), keine Lücke im Code.
* Vollmachten sind digital erfasst (Name des Vertreters), nicht als hochgeladenes
  Dokument; eine Beglaubigung oder Unterschrift führt das System nicht.
* Oberfläche und Portal sind viersprachig (de/en/fr/it); Einladung, Protokoll, Abrechnung, Zirkular
  und Akonto-Rechnung (PDF/Mail) bleiben deutsch (Entscheid D11). Meldungen der Services
  (`beschluss`, `budget`, `evoting`, …) und die Mehrheitsarten stehen noch deutsch.
* Ein Budget wird nur über ein Versammlungs-Traktandum genehmigt; ein Zirkularbeschluss kann ein Budget
  (noch) nicht auslösen.
* Das Akonto wird nicht ins Hauptbuch gebucht (siehe oben).
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
