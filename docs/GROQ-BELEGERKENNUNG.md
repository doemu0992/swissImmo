# Groq-Belegerkennung — nachträgliche Formalisierung

**Stand:** 14.08.2026 · erstellt für **P0.7** aus `docs/ANALYSE.md`

Die KI-Belegerkennung ist bereits im Einsatz. Nach der Projektanweisung wäre ihre
Einführung freigabepflichtig gewesen (externer Dienst, laufende Kosten, Kundendaten
verlassen das System). Das ist nachzuholen — nicht als Vorwurf, sondern weil eine
Datenbekanntgabe ins Ausland ohne dokumentierte Grundlage bei der ersten Nachfrage
eines Eigentümers oder einer Aufsicht nicht verteidigbar ist.

Dieses Dokument hält den **belegten Ist-Zustand** fest und benennt am Ende, was
noch entschieden werden muss. Was hier nicht steht, ist nicht geprüft.

---

## 1. Was der Dienst tut

| | |
|---|---|
| **Anbieter** | Groq, Inc. (USA) |
| **Endpunkt** | `https://api.groq.com/openai/v1/chat/completions` |
| **Modelle** | `llama-3.3-70b-versatile` (Text), `meta-llama/llama-4-scout-17b-16e-instruct` (Bild) |
| **Code** | `finance/utils.py` — `scan_beleg()`, `_groq_call()` |
| **Aufrufer** | `core/services/belegimport.py`, ausgelöst durch `/neu/kreditoren/scan/` |
| **Zeitlimit** | 45 Sekunden je Aufruf |
| **Zweck** | Kreditorenrechnung einlesen: Lieferant, Betrag, IBAN, Referenz, Datum, Kategorie |

Ausgelöst wird **ausschliesslich** durch das manuelle Hochladen eines Kreditoren-Belegs.
Es gibt keinen Hintergrundjob, der von sich aus Daten an Groq sendet.

## 2. Welche Daten das System verlassen

Das ist der Kern der Sache, und er ist unangenehmer als „nur Rechnungsdaten":

| Pfad | Was gesendet wird |
|---|---|
| PDF mit Textebene | Die ersten **12'000 Zeichen** des extrahierten Rechnungstexts (`MAX_TEXT_CHARS`) |
| Bild-Beleg (jpg/png/webp) | Die **vollständige Bilddatei**, base64-kodiert |
| PDF ohne Textebene | **Seite 1 als PNG gerendert**, base64-kodiert |

Gesendet wird also nicht ein Auszug ausgewählter Felder, sondern **der Beleg, wie er
ist**. Eine Handwerkerrechnung nennt regelmässig die Liegenschaft, die Wohnung und
nicht selten den Namen des Mieters („Reparatur Waschmaschine, Whg. 3. OG links,
Mieter Muster"). Damit sind personenbezogene Daten Dritter betroffen — von Personen,
die dem Dienst nie zugestimmt haben und von ihm nichts wissen.

**Nicht gesendet werden** Datenbankinhalte, Mieterstammdaten, Verträge, Zahlungsdaten
aus dem System oder irgendetwas ausserhalb der einen hochgeladenen Datei.

## 3. Der Ausschalter — und dass er wirklich einer ist

Ohne `GROQ_API_KEY` findet **kein Netzwerkzugriff** statt. `scan_beleg()` fällt auf den
regelbasierten Pfad zurück (`pdfplumber` + reguläre Ausdrücke, rein lokal) und der
QR-Decoder (`zxing-cpp`, ebenfalls lokal) liefert bei Schweizer QR-Rechnungen die
Zahlungsdaten sogar verbindlich statt geschätzt.

Das ist kein toter Notausgang, sondern der getestete Normalfall: Mehrere Tests laufen
unter `override_settings(GROQ_API_KEY=None)` und prüfen genau diesen Pfad.

Praktisch heisst das: **Den Schlüssel aus der `.env` entfernen und neu starten genügt.**
Die Funktion degradiert sichtbar (jedes Ergebnis trägt `methode` und `hinweis`, die
Oberfläche zeigt beides an), sie bricht nicht.

## 4. Kosten

Abgerechnet wird nach Token. Ein Textbeleg liegt bei rund 3'000–4'000 Eingabe-Token
(12'000 Zeichen), ein Bildbeleg höher, weil das Bild in Token umgerechnet wird.

**Belastbare Zahlen fehlen**, und ich erfinde hier keine: Weder die aktuelle Groq-Preisliste
noch die tatsächliche Belegmenge pro Monat liegen mir vor. Beides gehört vor einer
Freigabe zusammengetragen — die Grössenordnung entscheidet, ob das ein Rundungsfehler
oder ein Kostenblock ist.

Was dafür feststeht: Es gibt **keine Obergrenze im Code**. Kein Zähler, kein Monatslimit,
keine Warnung. Wer hundert Belege am Tag hochlädt, löst hundert Aufrufe aus.

## 5. Datenschutz (DSG)

Die Bekanntgabe ins Ausland ist in **Art. 16 f. DSG** geregelt. Für die Beurteilung
fehlen zwei Angaben, die ich nicht aus dem Code beantworten kann und auch nicht raten
werde:

1. **Ist Groq unter dem Swiss-U.S. Data Privacy Framework zertifiziert?** Nur dann trägt
   der Angemessenheitsbeschluss. Zu prüfen auf der offiziellen DPF-Liste, auf den Eintrag
   „Groq, Inc." und darauf, dass die Zertifizierung **aktiv** ist und die **Schweiz**
   einschliesst (die EU-Zertifizierung allein genügt nicht).
2. **Gibt es einen Auftragsbearbeitungsvertrag?** Art. 9 DSG verlangt ihn für die
   Bearbeitung durch Dritte. Groq bietet ein Data Processing Addendum an; ob es für
   dieses Konto abgeschlossen wurde, ist mir nicht bekannt.

Unabhängig davon offen:

- **Aufbewahrung bei Groq.** Ob und wie lange Eingaben gespeichert oder zum Training
  verwendet werden, richtet sich nach den Bedingungen des gewählten Tarifs. Das ist
  die Frage, die einem Eigentümer gegenüber am meisten zählt.
- **Informationspflicht.** Die Datenschutzerklärung (`core/templates/core/datenschutz.html`,
  eingeführt mit P5) nennt Groq bisher nicht. Wird der Dienst weiter genutzt, gehört er dort
  hinein — mitsamt Zweck und Empfängerstaat.
- **Bearbeitungsverzeichnis.** Art. 12 DSG; für kleinere Unternehmen mit Ausnahmen, aber
  eine Bekanntgabe ins Ausland ist genau der Fall, den man verzeichnet haben will.

## 6. Was zu entscheiden ist

Vier Fragen, in dieser Reihenfolge:

| # | Frage | Ohne Antwort |
|---|---|---|
| 1 | DPF-Zertifizierung von Groq prüfen und den Beleg ablegen | fehlt die Rechtsgrundlage der Auslandsbekanntgabe |
| 2 | Auftragsbearbeitungsvertrag abschliessen (oder den bestehenden ablegen) | fehlt die Grundlage nach Art. 9 DSG |
| 3 | Datenschutzerklärung um Groq ergänzen | ist die Informationspflicht verletzt |
| 4 | Kostenrahmen festlegen und im Code durchsetzen | läuft die Nutzung unbegrenzt |

**Fällt eine der ersten beiden Antworten negativ aus**, ist der Ausschalter aus
Abschnitt 3 die sofortige Massnahme: Schlüssel entfernen, die regelbasierte Erkennung
plus QR-Decoder übernimmt. Für Schweizer QR-Rechnungen — der häufigste Fall — ist das
Ergebnis dabei nicht schlechter, sondern **verbindlicher**, weil der QR-Code die
Zahlungsdaten exakt liefert statt sie zu schätzen.

**Ab Phase 3** ist die Belegerkennung ohnehin als zubuchbares Modul vorgesehen
(P3.3). Dann wird sie pro Organisation abschaltbar, und die Frage stellt sich je
Kunde neu — wer sie nicht bucht, dessen Belege verlassen das System nie.

---

*Dieses Dokument beschreibt den Code-Stand vom 14.08.2026. Es ist keine Rechtsberatung.
Die Punkte in Abschnitt 6 sind kaufmännische und rechtliche Entscheide und bleiben beim
Betreiber.*
