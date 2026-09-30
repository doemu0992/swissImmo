# Chaos-Engineering — Ausfälle und Extremeingaben

Stand 30.09.2026. Tests: `core/tests/test_chaos.py` (38 Fälle, jeder injiziert
den Fehler selbst). Jede Schutzschicht wurde einzeln ausgebaut; der zuständige
Test wurde rot (Tabelle unten).

## Befunde und Massnahmen

| # | Szenario | Befund vorher | Jetzt |
|---|---|---|---|
| 1 | DB bricht mitten in der Sollstellung ab | **Kein Datenchaos:** `run_sollstellung` lief schon in *einer* Transaktion, der Rollback war sauber. Aber: die View fing nur `RuntimeError`; jeder DB-Fehler war ein nackter HTTP 500, der Benutzer wusste nicht, ob er nochmals starten darf. | Test belegt den Rollback (30 Verträge, Abbruch im 40. Buchungsaufruf → 0 Rechnungen, 0 Buchungen; zweiter Lauf erzeugt genau 30, dritter 0). View meldet «nichts wurde gebucht, gefahrlos wiederholbar». |
| 2 | Ein Vertrag mit unrechenbaren Daten | Ein einziger Vertrag brach den ganzen Lauf ab (alle 500 blockiert). Negativer Mietzins wurde **still** übersprungen. | Savepoint je Vertrag: nur dieser wird übersprungen, seine halben Buchungen rollen mit zurück, `fehler`-Liste + Log + Warnung in der View + Aktivitätslog im Scheduler. Negativer Mietzins wird gemeldet. DB-Fehler und gesperrte Periode brechen weiterhin den *ganzen* Lauf ab (bewusst). |
| 3 | PDF: RAM voll / Renderer stürzt ab | Generischer `Exception`; Views: 500 mit Klartext. `erzeuge_und_ablege_vertragspaket` schluckte Fehler auf Debug-Ebene, der Assistent meldete «0 Dokumente» ohne Hinweis. | `PdfFehler` (MemoryError, Renderer-Absturz, `err`, Nicht-PDF-Ausgabe). 5 MB-Grenze auf dem HTML (50 MB «Besondere Vereinbarungen» erreichen den Renderer nicht mehr). Views: 503 + `Retry-After`, nichts abgelegt. Paket nennt fehlgeschlagene Teile (`.fehler`, Header `X-Fehlende-Dokumente`); Assistent warnt. |
| 4 | Mietzins `NaN`, `Infinity`, `1e999` | **HTTP 500:** `Decimal('NaN')` liest sich ohne Fehler, der Vergleich `< 0` wirft `InvalidOperation`. | `endliche_zahl()`; als «nicht lesbar» abgelehnt. |
| 5 | Mietzins −500 | war schon abgelehnt | unverändert, jetzt zentral. |
| 6 | Mietzins CHF 0 | nur Warnung | **bewusst so gelassen** (Hauswartwohnung, Gratis-Parkplatz). Test dokumentiert es. |
| 7 | Mietzins 10¹² | SQLite speichert, `_dezimalfeld_guard` wirft `ValueError` → **500**; auf PostgreSQL Serverfehler | Obergrenze = Feldbreite des Modells (CHF 999'999.99 / NK 9'999.99); Meldung am Feld. |
| 8 | Einzug vor Baujahr / Jahr 0001 / 9999 | ungeprüft | `pruefe_vertragswerte`: nicht vor Baujahr der Liegenschaft, nicht vor 1900, nicht mehr als 10 Jahre voraus. Auch im Bearbeitenformular und im Weg Bewerbung → Entwurf (dort stammt das Datum aus dem öffentlichen Formular). |
| 9 | Personenzahl −3 / 99999999999 | Assistent: ungeprüft (Bearbeitenformular ja) | 1–30, in beiden. |
| 10 | Neuer Mieter, danach scheitert das Speichern | **Waisen-Mieter** (`Mieter.objects.create` ausserhalb der Transaktion), beim erneuten Absenden ein zweiter | Mieter-Anlage, Vertrag, Staffel, WG, Wohnadresse in *einer* Transaktion; DB-Fehler → Assistent mit Eingaben zurück. |
| 11 | 500-MB-Upload | Keine globale Grenze. Der Body wurde auf die Platte gestreamt, bevor irgendeine View prüfen konnte. 9 Upload-Stellen ohne jede Prüfung (Dokumentablage, Schaden intern erfassen, Kautionszertifikat, Kreditorenbeleg, Kreditor-Scan, Raumbuch-Fotos ×2, Bewerbungsunterlagen, Logo, Abnahme-Mängelfotos). | `UploadGrenzeMiddleware`: 413 anhand `Content-Length`, bevor der Body gelesen wird (60 MB). Alle Stellen prüfen jetzt mit `validiere_bild` / `validiere_dokument` / neu `validiere_ablage` (Positivliste, kein html/svg/exe, PDF am Inhalt). |
| 12 | Dokumentablage ohne Liegenschaft/Objekt | **HTTP 500** (`CHECK hat_bezug`) | Meldung. |

## Gegenprobe

Schutz ausgebaut → Test rot (Ergebnis siehe PR-Beschreibung, dort aus dem Lauf
eingetragen).

## Bewusst nicht getan

- **Webserver-Grenze:** `client_max_body_size` (nginx) bzw. das Pendant beim
  Hoster gehört zusätzlich gesetzt; die Middleware vertraut dem Header
  `Content-Length`. Ein Client, der ihn falsch angibt, wird von den
  Prüfungen der Views aufgefangen, füllt aber vorher die Platte. Das ist
  Serverkonfiguration, nicht Code.
- **Datenbank-CheckConstraint** (`netto_mietzins >= 0`): bräuchte eine
  Migration und die Gewissheit, dass der Produktivbestand keine Verletzung
  enthält. Nicht ohne Bestandsprüfung.
- **Antivirus** auf Uploads: externer Dienst / Kosten → Freigabe nötig.
- **Andere PDF-Erzeuger** (`docuseal_service`, `views/docuseal.py`, Briefe,
  Abrechnungen) nutzen weiter `pisa.CreatePDF` direkt. Nur Mietvertrag und
  Begleitdokumente laufen über `html_zu_pdf`. Nächster Schritt: dieselbe
  Umstellung, je Erzeuger ein eigener PR.
- **Sollstellung mit 500 echten Verträgen auf PostgreSQL:** die Tests laufen auf
  SQLite mit 30. Das Verhalten (eine Transaktion, Savepoints) ist auf beiden
  gleich, aber nicht gemessen.
