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
| Anfragen, Aufgaben, offene Punkte (als `core.Pendenz`) | `stweg/anfragen.py`, `stweg/aufgaben.py` |
| Oberfläche Verwaltung | `/neu/stweg/` (`stweg/views.py`) |
| Eigentümerportal | `/portal/stweg/` (`stweg/portal.py`) |

## Buchhaltung

Der Fonds gehört der Gemeinschaft, nicht der Verwaltung: Einlage = Soll 1110
(Forderungen Stockwerkeigentümer) an Haben 2800 (Erneuerungsfonds, **Passivum**);
Entnahme = Soll 2800 an Haben 1020 (Bank). Kein Aufwand, kein Ertrag.
`run_erneuerungsfonds_einlage` (Aufwand 6900 an 2800) bleibt Mietliegenschaften
vorbehalten und überspringt STWEG.

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
* Die Jahresabrechnung bucht nicht ins Hauptbuch (nur der Fonds tut es) und hat
  keinen QR-Einzahlschein für Nachzahlungen.
* Vollmachten sind digital erfasst (Name des Vertreters), nicht als hochgeladenes
  Dokument; eine Beglaubigung oder Unterschrift führt das System nicht.
* Neue Texte der Oberfläche, Einladung, Protokoll, Abrechnung und Zirkular nur
  deutsch (Entscheid D11).
* Einzelspeicherung von Einheiten prüft die Quoten nicht; geprüft wird bei
  Aktivierung, Einlage, Einladung, Zirkularversand und Abrechnung.
  `QuerySet.update()` umgeht `save()`.
* Eine STWEG wird im Liegenschaftsformular angelegt (Art «Stockwerkeigentum»); das
  Feld «Eigentümer» entfällt dort bewusst (`Liegenschaft.eigentuemer` bleibt leer,
  denn Mietlogik und Portal lesen es). Danach führt die Seite «Einheiten und
  Eigentümer» durch Quoten, Eigentümer und Aktivierung.
* **Nebenräume** (`gehoert_zu` gesetzt) haben weder Quote noch Stimme und zählen
  nirgends mit (`stimm_einheiten`). Eine selbständige Garage mit eigener Quote wird
  als eigenständiges Objekt erfasst.
* **Wertquote-Vorgabe:** Das Feld stammt aus dem Mietmodul (Vorgabe 10). Neue
  Einheiten einer STWEG und GWR-importierte Einheiten bekommen 0.
