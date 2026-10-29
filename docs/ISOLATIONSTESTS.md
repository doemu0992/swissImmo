# Isolationstests — Katalog und Bauplan

**Stand:** 14.08.2026
**Gehört zu:** Etappe 2 aus `docs/PHASE-2-PLAN.md`
**Zweck:** Vollständig erfassen, was gegen die Mandantengrenze geprüft werden muss, und festlegen, wie diese Prüfungen gebaut werden.

---

## Korrektur einer früheren Schätzung

In `docs/PHASE-2-PLAN.md` steht „rund 150 Tests". Die Auszählung ergibt ein anderes Bild — sowohl in der Menge als auch in der Bauform.

**Gemessen am Bestand:**

| Prüffläche | Anzahl |
|---|---|
| Benannte URLs gesamt | 294 |
| davon mit genau einem ID-Parameter | 152 (119 × `pk`, 19 × `vertrag_id`, 4 × `einheit_id`, 3 × `liegenschaft_id`, 2 × `periode_id`, je 1 × `mieter_id`, `nummer`, `pfad`) |
| Modelle | 63 |
| Globale Unique-Constraints | 6 |
| Management-Commands | 19 |
| Download- und Export-Views in `fw.py` | 10 |
| Portal-Downloads | 8 |

Von Hand geschrieben wären das über 240 Testmethoden — und jede neue View bräuchte eine weitere, die jemand vergessen wird.

**Deshalb der bessere Zuschnitt:** Die Masse wird **datengetrieben** aus der URL- und Modell-Registry erzeugt, nicht abgetippt. Rund 35 bis 40 Testmethoden decken damit über 240 Fälle ab — und neue Views sind automatisch mitgeprüft, ohne dass jemand daran denken muss.

Das ist zugleich die Antwort auf das Hauptrisiko: Ein handgeschriebener Testkatalog veraltet ab dem Tag, an dem er fertig ist. Ein registrygetriebener nicht.

---

## Die vier Bauformen

### A. Registrylauf über alle objektbezogenen URLs

Eine Testmethode, rund 148 abgedeckte Fälle.

Der Test legt zwei Organisationen mit je einem vollständigen Datensatz an, meldet sich als Benutzer von A an und ruft jede URL mit der ID eines Objekts von B auf. Erwartet wird durchgängig **404** — nicht 403, weil ein 403 die Existenz des Datensatzes bestätigt und über fortlaufende IDs das Abzählen fremder Bestände erlaubt.

```python
def test_keine_fremde_id_ueber_benannte_urls(self):
    """Jede URL mit ID-Parameter muss für fremde Objekte 404 liefern.

    Datengetrieben aus der URL-Registry: neue Views sind automatisch
    mitgeprüft. subTest, damit ein Treffer nicht die übrigen verdeckt.
    """
    self.client.force_login(self.user_a)
    for name, param, objekt_b in self.fremde_objekte():
        with self.subTest(url=name):
            antwort = self.client.get(reverse(name, args=[objekt_b.pk]))
            self.assertEqual(antwort.status_code, 404)
```

**Zwei Dinge, die dabei sauber gelöst sein müssen:**

Erstens braucht der Test zu jedem ID-Parameter ein passendes Objekt aus Organisation B. Die Zuordnung von Parametername zu Modell (`vertrag_id` → `Mietvertrag`, `einheit_id` → `Einheit`, `periode_id` → `AbrechnungsPeriode`) gehört in eine explizite Tabelle im Testmodul, nicht in Rateheuristik. Was sich nicht zuordnen lässt, muss **auffallen** — ein stilles Überspringen wäre genau die Lücke, die der Test verhindern soll.

Zweitens gibt es echte Ausnahmen: `geschuetzte_media` (Pfad statt ID), `public_bewerbung` und `public_report` (bewusst öffentlich), der token-gesicherte Portal-Feed. Diese gehören in eine benannte Ausnahmeliste **mit Begründung im Code** — nicht ausgefiltert, sondern dokumentiert.

### B. Registrylauf über alle Modelle

Eine Testmethode, 63 abgedeckte Fälle.

Prüft auf ORM-Ebene, dass der Default-Manager filtert: Im Kontext von Organisation A darf `Model.objects.all()` keinen Datensatz von B enthalten. Das ist die Schicht unter den Views — sie greift auch dort, wo später jemand eine View ohne Besitzprüfung hinzufügt.

Zweite Methode derselben Bauform: Ohne gesetzten Organisationskontext muss der Manager **einen Fehler werfen**, nicht stillschweigend alles liefern. Dieser Test ist wichtiger, als er aussieht — ein Manager, der im Zweifel alles zurückgibt, täuscht Sicherheit vor.

### C. Handgeschrieben, wo Registry nicht hinkommt

Rund 25 Methoden. Diese Fälle haben keine URL und kein Modell, an dem man sie automatisch findet:

| Bereich | Was geprüft wird |
|---|---|
| **Schreibpfade** | POST auf Bearbeiten und Löschen mit fremder ID. 22 `_loeschen`- und 5 `_bearbeiten`-Views. Löschpfade sind erfahrungsgemäss am häufigsten ungeschützt — und am teuersten, wenn sie es sind. |
| **Dateiablage** | `geschuetzte_media` liefert eine Datei von B nicht an einen Benutzer von A aus, auch nicht über `%2e/`-Umwege. Der Pfadauflösungs-Schutz existiert bereits und ist gegen Organisationen zu erweitern. |
| **Portal-Downloads** | 8 Views (`portal_dokument_download`, `portal_steuerauszug_pdf`, `mieter_kontoauszug_pdf` und weitere). Eigentümer und Mieter sind bereits datensatzbezogen isoliert — hier ist zu prüfen, dass die Organisationsgrenze zusätzlich hält. |
| **Exporte und PDFs** | 10 Views in `fw.py`. Ein Export darf nur Daten einer Organisation enthalten, auch wenn ihn ein Superuser auslöst. Geprüft wird der Inhalt, nicht nur der Statuscode. |
| **Hintergrundjobs** | `monatslauf`, `mahnlauf`, `taeglicher_lauf`, `jahresabschluss_lauf`, `fristen_digest`, `send_eigentuemer_reports`, `dsg_anonymisieren`, `bewerbungen_bereinigen`. Je Command: läuft er für A, bleibt der Bestand von B unberührt? |
| **Absender in Dokumenten** | Ein PDF für einen Datensatz von B trägt nie den Absender von A. Deckt die 132 Singleton-Lookups ab, die heute `Verwaltung.objects.first()` verwenden. |
| **Unique-Constraints** | Sechs Fälle. Zwei Organisationen müssen dasselbe Konto 4000, dasselbe Suchwort, denselben Lieferantenschlüssel führen können. Zusätzlich: Der Belegnummernkreis zählt je Organisation — sonst verrät die Lückenfolge, wie viel die andere bucht. |
| **Admin** | Der Unfold-Admin umgeht den Manager über `_base_manager` und als Superuser. Nach Entscheid E2 ist er lesend und auf Superuser beschränkt — das ist zu prüfen, nicht anzunehmen. |
| **Cache** | Ein Cache-Key ohne Organisations-ID ist ein Datenleck mit Zeitverzögerung: A füllt den Cache, B liest ihn. |

### D. Der Wächter

Eine Testmethode, die dafür sorgt, dass der Katalog nicht veraltet.

Sie läuft über die Modell-Registry und schlägt fehl, sobald ein Modell existiert, das weder eine `organisation`-Spalte noch eine Pflicht-Kette dorthin hat und nicht in einer begründeten Ausnahmeliste steht.

Damit ist die Vollständigkeit nicht mehr Gedächtnisleistung. Wer in einem Jahr ein Modell hinzufügt und den Bezug vergisst, bekommt einen roten Test statt eines Datenlecks.

---

### F. Fremde IDs im Body, alle Rollen (28.10.2026, SICH-01 / SICH-27)

Die Bauformen A bis E setzen fremde IDs in den **Pfad** oder den **Querystring**.
Die drei Löcher des Audits vom 28.10.2026 standen im **Formular**: `fw_pendenz_neu`
(`liegenschaft_id` → Zeile in der Organisation der fremden Liegenschaft), der
QR-Aushang (`einheit_id`) und `fw_abwesenheit_neu` (`benutzer`, `vertreten_durch`;
`Benutzer` hat keinen Mandantenfilter). Jeder Weg hatte einen grünen Test, der die
Frage an die falsche Stelle stellte.

`FremdeIdImBodyTests` (`core/tests/test_isolation.py`, Messung in
`core/tests/_koerper_ids.py`) schickt an **jede** POST-Route einen Body, in dem jedes
bekannte Feld auf Mandant B zeigt — als Inhaber, Verwalter und Sachbearbeiter, als
Formular und als JSON — und misst danach den **Bestand**, nicht den Statuscode:
neue/geänderte/gelöschte Zeilen von B, Fremdschlüssel von A nach B, Benutzer ohne
Mitgliedschaft in der Organisation der Zeile. Nur Tabellen, in die geschrieben wurde,
werden neu gelesen. Die Messung weist sich selbst nach
(`test_der_nachweis_findet_ein_leck`). Ausnahmen stehen mit Grund in
`OEFFENTLICH_BY_DESIGN` (`/schaden/melden/`, Bewerbungsformular).
`ZweiPfadParameterTests` deckt die Routen mit zwei Pfadparametern ab, `stweg` steht in
`EIGENE_APPS`.

Darunter liegt ein **Netz**: `OrganisationAusKette.save()` bricht mit
`FremdeOrganisation` ab, wenn die aus der Kette abgeleitete Organisation vom Kontext
der Anfrage abweicht. Es ersetzt die Prüfung in der Ansicht nicht (das Ergebnis wäre
ein 500), verhindert aber die stille Zeile im fremden Mandanten. Der Weg für Ansichten:
`core/utils/formularid.eigenes_objekt(Modell, roh, …)`; für Personen des Teams
`team_der_organisation(request.organisation)`.

### G. Was das Fixture nicht anlegt (29.10.2026, SICH-27e)

`MandantenFixture` legt nur Objekte an, die beim Bau schon bekannt waren. Der Manager-Test überspringt jedes
Modell ohne Zeile bei B (richtig: er könnte nichts beweisen). Es hiess aber: 53 von 123 Modellen mit
Mandantenfilter — Mahnung, Hypothek, Jahresabschluss, Zahlungsvereinbarung, Kreditorenzahlung,
Eigentümerauszahlung, die STWEG-Abrechnung — waren nie geprüft. Das gemeinsame Fixture zu erweitern, verschiebt
Zahlen in rund hundert Tests; darum erweitert `core/tests/test_isolation_abdeckung.py` es nur für die eigenen
Läufe (`ErweiterterBestand`) und wacht darüber:

* `test_jedes_mandantenmodell_hat_eine_zeile`: Ein neues Modell mit Mandantenfilter muss dort eine Zeile
  bekommen (`_zusatz`) oder mit Grund in `OHNE_ZEILE` stehen. Sonst ist der Test rot.
* `test_manager_zeigt_keine_fremden_zeilen`: Im Kontext von A sichtbar ist nichts von B und umgekehrt.

**Rollen.** `test_isolation_rollen.py` fährt den Body-Fuzz (F) auch für Buchhaltung, Hauswart und Lesezugriff;
`test_lesezugriff_schreibt_nie.py` verlangt, dass Lesezugriff auf KEINER POST-Route Zeilen schreibt (Ausnahmen:
`DARF_AENDERN`, `OEFFENTLICH`, mit Grund).

## Wann ist ein Test ein Test

Ein Isolationstest, der auch **ohne** den Filter grün wäre, prüft nichts. Das ist kein theoretisches Problem — es ist die wahrscheinlichste Art, wie diese Etappe scheitert, weil ein falsch aufgesetzter Test genauso grün aussieht wie ein richtiger.

**Deshalb ist die Gegenprobe Teil der Abnahme:** Filter auskommentieren, Suite laufen lassen, die Tests **müssen** rot werden. Erst dann gilt der Test als geschrieben. Das gehört ins PR-Protokoll, nicht in die gute Absicht.

---

## Reihenfolge

Etappe 2 läuft parallel zu Etappe 1, weil die Tests gegen **URL-Namen** geschrieben werden — die überleben das Zerlegen von `fw.py` unverändert.

| Schritt | Inhalt | Zustand danach |
|---|---|---|
| 2.1 | Testinfrastruktur: zwei Organisationen mit vollständigem Datensatz als Fixture | rot (kein `Organisation`) |
| 2.2 | Bauform A und B, datengetrieben | rot |
| 2.3 | Bauform C, handgeschrieben | rot |
| 2.4 | Bauform D, der Wächter | rot |

**Alle rot — das ist der Zweck.** Ab hier ist die Definition of Done keine Behauptung mehr, sondern eine Zahl. Sie werden grün in den Etappen 4 bis 6, und Phase 2 endet genau dann, wenn keine mehr rot ist.

Der Aufbau des Fixtures aus Schritt 2.1 ist die eigentliche Arbeit: zwei vollständige Mandanten mit Liegenschaft, Einheit, Mietvertrag, Mieter, Eigentümer, Buchungen, Rechnungen, Dokumenten, Abrechnungsperiode und Schadenmeldung. Ohne diese Basis prüfen die Registryläufe ins Leere, weil zu vielen URL-Parametern kein Objekt existiert.

---

## Was diese Tests nicht leisten

Sie prüfen die Grenze zwischen Organisationen. Sie prüfen **nicht**:

- ob die Rollen innerhalb einer Organisation richtig greifen — das deckt die bestehende Suite ab
- ob die Fachlogik stimmt — Fristen, Abrechnungen, MWST bleiben Sache der 1'068 vorhandenen Tests
- ob die Isolation auch unter Last hält — Nebenläufigkeit und Kontextvariablen sind ein eigenes Thema, das nach Etappe 4 eine gesonderte Betrachtung braucht

Der letzte Punkt ist der, den ich am ehesten unterschätzt sehe: Eine Kontextvariable, die zwischen Requests nicht sauber zurückgesetzt wird, produziert ein Leck, das kein Einzeltest findet.
