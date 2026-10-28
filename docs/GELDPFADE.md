# Geldpfade: Sperren, Idempotenz, Eigentümerauszahlung, Unveränderbarkeit

Stand 28.10.2026 (Etappe 0 des Audits, Auftrag B). Befunde: FIN-01, FIN-02, FIN-04,
FIN-05, SICH-44, FUNK-01, FIN-03, FUNK-02, FIN-15/SICH-06 (Mindesthärtung).

## 1. Die Regel

Jeder Pfad, der Geld bucht oder einen Status von «offen» auf «bezahlt/bestätigt/
abgeschlossen» setzt, hält sich an dieselbe Reihenfolge:

```python
with transaction.atomic():
    zeile = Modell.objects.select_for_update(of=('self',)).get(pk=...)   # 1. sperren
    if zeile.status != 'offen': ...                                       # 2. DANACH prüfen
    ...                                                                   # 3. buchen
```

Wer eine Prüfung vor dem Sperren macht, prüft den Stand von vor dem Warten. Die vier
parallelen Klicks aus dem Audit lasen «offen» alle, bevor der erste gebucht hatte.
Läufe ohne einzelnen Datensatz (Jahresabschluss, Kontoauszug-Import, Belegnummer,
Eigentümerauszahlung) nehmen `core.sperren.sperre_organisation(name, organisation_id)`,
eine PostgreSQL-Advisory-Lock bis zum Transaktionsende. Eine Tabelle oder Migration
braucht es dafür nicht.

**SQLite:** Beide Werkzeuge sind dort wirkungslos (Django ignoriert `select_for_update`,
die Advisory Lock gibt es nicht). SQLite serialisiert Schreiber ohnehin. Dass eine Sperre
wirkt, belegen nur Tests mit echten Threads auf PostgreSQL (`core/tests/_parallel.py`,
`NUR_POSTGRES`; in der CI läuft der Job `test-postgres`).

**Doppelklick mit ausdrücklichem Teilbetrag:** Er ist von zwei echten Teilzahlungen nicht
zu unterscheiden. Die Masken «Zahlung verbuchen» (Bankabgleich) und «Bezahlen»
(Kreditoren) schicken deshalb `erwartet_offen` mit — den offenen Betrag, den sie gezeigt
haben. Stimmt er nach dem Sperren nicht mehr, ist die Anfrage ein Doppelklick und wird
abgewiesen. Ohne das Feld (API, Skript) gilt das alte Verhalten.

## 2. Abgedeckte Pfade

| Pfad | Stelle | Mittel |
|---|---|---|
| Zahlung auf Debitor | `bankabgleich.fw_bankabgleich_verbuchen` | Zeile gesperrt, Status/offen danach, `erwartet_offen` |
| Kreditor bezahlen | `kreditoren.fw_kreditor_bezahlen` | wie oben |
| Zahllauf bestätigen | `kreditoren.fw_zahllauf`, Aktion `bezahlt` | je Rechnung gesperrt und neu gelesen |
| Zahlungsdatei | `kreditoren.fw_zahllauf`, Aktion `datei` | Auswahl unter Sperre, Status in derselben Transaktion |
| Zahllauf zurücksetzen | dieselben, beide Formen | gesperrt |
| Storno Buchung | `booking.storniere_buchung` | Original gesperrt und neu gelesen (alle Aufrufer) |
| Storno Rechnung | `listen.fw_debitor_stornieren` | Rechnung gesperrt, dann Prüfungen |
| Jahresabschluss und Rücknahme | `services/jahresabschluss.py` | Organisations-Sperre |
| AfA, Erneuerungsfonds | `services/automation.py` | je Anlage/Fonds eine Transaktion mit Zeilensperre |
| camt-/CSV-Import | `bankabgleich.fw_camt_import` | Organisations-Sperre; `_verbuche` bricht bei veränderter Rechnung ab |
| Bankbewegung zuordnen | `aktionen.fw_bankbewegung_zuordnen` | Bewegung und Kreditor gesperrt |
| MWST verbuchen | `aktionen.fw_mwst_verbuchen` | Organisations-Sperre, Prüfung danach |
| Verwaltungshonorar | `services/verwaltungshonorar.py` | Organisations-Sperre |
| Kaution zurückzahlen | `kautionen.fw_kaution_aktion` | Vertrag gesperrt, Saldo 2010 danach |
| Schlussabrechnung buchen | `detailseiten.fw_schlussabrechnung` | Vertrag gesperrt, Prüfung danach |
| Versicherungsfall (Selbstbehalt, Entschädigung) | `services/versicherungsfall.py` | Fall gesperrt |
| Nutzungsentschädigung | `services/nutzungsentschaedigung.py` | Vertrag gesperrt |
| Eigentümerauszahlung | `services/eigentuemer_kontokorrent.buche_auszahlung` | Organisations-Sperre (siehe 3) |
| Belegnummer | `finance.models.Buchung._mit_belegnummer_speichern` | Nummernkreis-Sperre je Organisation, Retry mit Wartezeit nur als Gürtel |

Bereits vor Etappe 0 gesperrt und unverändert: Sollstellung, Kreditor freigeben, Zahlung
zuordnen/Sammelzuordnung, Zahlung stornieren, Kreditorzahlung stornieren, Abschreiben,
Weiterverrechnung, Betreibung, NK-Verbuchen, Zahlungsklärung.

**Ohne Schutz (bewusst nicht angefasst):** Debitor von Hand erfassen (`fw_debitor_neu`),
manuelle Buchung (`fw_buchung_neu`, Serienerfassung ist beabsichtigt), Anlage erfassen —
ein Doppelklick erzeugt zwei Belege; es gibt keinen natürlichen Schlüssel, an dem man
sie erkennt. STWEG-Buchungen (`stweg/hauptbuch.py`, `inkasso.py`) wurden nicht geprüft.
Kein DB-Constraint auf Storno-Gegenbuchungen oder `Zahlungseingang.bank_referenz`: Der
Bestand kann Dubletten aus den alten Rennen enthalten, eine Migration würde dann auf
Produktion scheitern. Erst prüfen (SQL im Bericht), dann Constraint nachziehen.

## 3. Eigentümerauszahlung: die Liquiditätsbasis

Das Kontokorrent (`kontokorrent()`) rechnet Ertrag − Aufwand aus dem Journal, also auf
Sollbasis. Eine fällige, nie bezahlte Miete steht dort als Guthaben des Eigentümers.
Ausgezahlt werden darf nur, was eingegangen ist:

```
auszahlbar = max(0, min( eingegangen − bezahlt − ausbezahlt ,  Saldo Kontokorrent ))
```

* `eingegangen`: Zahlungen auf Mietforderungen (`Bank/Durchlauf/Mieterguthaben an 1100`)
  und direkt gebuchte Erträge (`Bank an Ertrag`), abzüglich ihrer Stornos.
* `bezahlt`: Zahlungen an Lieferanten (`2000 an Bank`) und direkt bezahlter Aufwand.
* `ausbezahlt`: frühere Auszahlungen an diesen Eigentümer.
* Ausgeschlossen: Kautionen (1015/2010), Mieterguthaben und Ungeklärtes bis zur
  Zuordnung (2030/1190), unbezahlte Mieten und Rechnungen, Abschlussbuchungen.
* Die Ertragsbasis (Kontokorrent) bleibt als zweite Grenze und fängt Honorar, Fondseinlagen
  und freigegebene, unbezahlte Rechnungen ab. Sie kann den Betrag nur senken.

Die Buchung läuft unter einer Organisations-Sperre, weil das Bankkonto geteilt ist:
Geprüft werden Bankkonto (Kontengruppe 10, **nie 1015**), Stand der Maske, Obergrenze
und Deckung des Bankkontos. Zwei parallele Auszahlungen können die Deckung nicht
überschreiten. Andere Abflüsse (Kreditoren, Rückzahlungen) sind nicht gegen diese Sperre
serialisiert; sie prüfen die Bankdeckung auch nicht.

**Fachlich offen** (Entscheid der Treuhandstelle, nicht geraten): MWST-Anteil in bezahlten
Mieten (Konto 2200), Reserve/Treuhandpflichten aus dem Mandatsvertrag, Zahlungen ohne
Liegenschaftsbezug.

## 4. Unveränderbarkeit von Buchungen (Mindesthärtung)

`Buchung.objects` und `Buchung.alle_organisationen` sperren auf QuerySet-Ebene:

* `update()`/`bulk_update()` nur für die Storno-Marke und die Beleg-Verknüpfungen
  (Zahlung/Rechnung), diese nicht in einer gesperrten Periode.
* `delete()` und `bulk_create()` nie.
* `save()` auf eine bestehende Buchung: Betrag, Konten, Datum, Text, Belegnummer,
  Liegenschaft, Storno-Verweis und Ersteller sind unveränderlich; die Storno-Marke wird nur
  einmal gesetzt und nie zurückgenommen.
* Die benannten Ausnahmen `ausnahme_aendern(grund, …)` und `ausnahme_loeschen(grund)`
  verlangen eine Begründung und schreiben sie ins Log (Reparatur, Testaufbau).

Nicht geschlossen (Etappe 2): `_base_manager`, rohes SQL, Kaskade beim Löschen einer
Organisation, `QuerySet`-Umgehung per Shell. Dort helfen nur DB-Trigger und ein Revisionslog.

Folge für andere Stellen: Wer Buchungen löschen oder ändern muss, nimmt die benannte
Ausnahme. Der Datenreset (`profil.fw_datenreset`) tut das mit der Begründung «Datenreset
durch den Inhaber»; ohne sie liefe sein `Buchung.objects.all().delete()` in den
`PermissionError`, den der Reset schluckt, und das Journal bliebe stehen.

## 5. Abschlussbuchungen in Auswertungen

Der Jahresabschluss saldiert alle Erfolgskonten per 31.12. gegen 2970. Jede Auswertung der
Erfolgskonten eines Jahres schliesst sie mit `abschluss_buchungen_q()` aus, sonst zeigt
das abgeschlossene Jahr Ertrag 0. Mit diesem Ausschluss rechnen jetzt: Kontokorrent,
Honorarbasis, Erfolgsrechnung, **Mandatsabrechnung (Seite und PDF; FUNK-02)** und
**Auswertung `/neu/auswertung/`** (derselbe Fehler, bei der Suche nach dem Zwilling gefunden).
