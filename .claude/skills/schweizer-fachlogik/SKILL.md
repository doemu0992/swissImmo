---
name: schweizer-fachlogik
description: Wo in swissImmo Schweizer Recht und Zahlungsstandards fest verdrahtet sind, und welche Werte niemals geraten oder umgerechnet werden dürfen — Mietrecht (OR), QR-Rechnung, Fristen, Nebenkosten, MWST, kantonale Formularpflicht. Nutze diesen Skill, sobald Mietzins, Kündigung, Fristen, Kaution, Mahnung, QR-Code, IBAN, Referenznummer, Nebenkosten, MWST oder amtliche Formulare berührt werden — auch bei einem scheinbar rein technischen Umbau wie einer Modulverschiebung oder Übersetzung.
---

# Schweizer Fachlogik

Der fachliche Kern ist der eigentliche Wert dieser Codebasis. Vieles davon sieht wie eine beliebige Zahl aus und ist eine Rechtsvorschrift. Wer sie beim Refaktorieren „vereinfacht", erzeugt Fehler, die erst vor Gericht auffallen.

**Grundregel: Fachwerte nie aus dem Gedächtnis einsetzen.** Immer im Bestandscode nachsehen und den vorhandenen Wert übernehmen. Wenn ein Wert falsch scheint, das melden statt korrigieren.

## Wo die Logik liegt

| Bereich | Ort |
|---|---|
| Mietrecht allgemein | `core/services/mietrecht.py` |
| Mahnstufen (Art. 257d OR) | `core/services/mahnstufen.py` |
| Kündigungsschreiben und Fristen | `core/services/kuendigung_brief.py` |
| Kantonale Formularpflicht | `core/services/formularpflicht.py`, `core/services/kantone.py` |
| Amtliche Formulare (Original-PDFs) | `core/services/formulare/` |
| QR-Rechnung | `core/utils/qr_code.py` |
| Zahlungsauftrag pain.001 | `core/services/pain001.py` |
| Nebenkostenabrechnung | `core/services/nk_abrechnung.py` |
| MWST | `core/services/mwst_estv.py` |
| Referenzzins und LIK | `core/services/lik.py` |
| Datenschutz (DSG) | `core/services/dsg.py` |

## Werte, die feststehen

**Kaution (Art. 257e OR).** Bei Wohnräumen höchstens drei Monatsmieten. Die Grenze wird serverseitig in `Mietvertrag.save()` durchgesetzt und der überschiessende Teil geklemmt — das ist Absicht, keine übervorsichtige Validierung. Nicht zu einer blossen Warnung abschwächen.

**Zahlungsfrist bei Zahlungsverzug (Art. 257d OR).** Die Fristen und Mahnstufen stehen in `mahnstufen.py`. Eine Kündigung wegen Zahlungsverzugs ist an die korrekte Fristsetzung gebunden; eine um einen Tag verkürzte Frist macht sie anfechtbar.

**Kündigungsfristen und -termine.** Ortsüblichkeit und Vertragsart bestimmen den Termin. Nie auf „drei Monate" verallgemeinern.

**Formularpflicht bei Anfangsmietzins.** Gilt nicht überall gleich. `kantone.py` deckt alle 26 Kantone ab; Original-PDFs liegen für BE, SO und ZH vor. Fehlt ein Kanton, ist das eine Lücke, die gemeldet gehört — nicht eine, die man mit einem generischen Formular überbrückt.

**QR-Rechnung.** Die QR-IBAN ist nicht irgendeine IBAN: Nach `CHxx` folgt eine Kennung im Bereich **30000–31999**. Die QR-Referenz hat **27 Ziffern** mit Prüfziffer nach Modulo 10 rekursiv — sie ist nicht die Rechnungs- oder Kundennummer. Der Belegscanner-Prompt in `finance/utils.py` erklärt diese Unterscheidung ausdrücklich; sie ist der häufigste Erkennungsfehler.

**MWST.** Effektive Methode und Saldosteuersatz führen zu unterschiedlichen Ergebnissen und sind beide implementiert. Nicht zusammenlegen.

**Nebenkosten.** Heizgradtage, unterjähriger Mieterwechsel und Verwaltungshonorar sind eigenständige Regeln. Ein Mieterwechsel mitten in der Abrechnungsperiode ist der Fall, der am ehesten falsch vereinfacht wird.

## Beträge und Rundung

Geldbeträge sind `Decimal`, nie `float`. Bei Rundung immer auf 5 Rappen prüfen, wo es der Zahlungsverkehr verlangt. Ein `float`-Zwischenschritt in einer Abrechnung erzeugt Rappendifferenzen, die in der Buchhaltung als Fehler auflaufen.

## Bei Mehrsprachigkeit besonders aufpassen

Ab Phase 5 wird die Oberfläche übersetzt. Drei Fallen:

**Rechtsbegriffe sind keine freie Übersetzung.** „Kündigung", „Anfangsmietzins", „Nebenkostenabrechnung" haben in FR und IT festgelegte Entsprechungen aus dem Gesetzestext. Die amtlichen Formulare existieren offiziell mehrsprachig — deren Wortlaut ist massgeblich, nicht eine sinngemässe Übertragung.

**Stichwortbasierte Logik bricht.** Die Kategorisierung im Audit-Trail und die Kategorienliste im Belegscanner arbeiten mit deutschen Schlüsselwörtern. Werden die Texte übersetzt, greifen sie ins Leere. Solche Stellen brauchen stabile Schlüssel statt übersetzbarer Texte.

**Dokumente folgen dem Empfänger.** Die Sprache eines Mietvertrags oder einer Mahnung richtet sich nach dem Mieter (`Mieter.sprache`), nicht nach dem eingeloggten Sachbearbeiter.

## Im Zweifel

Wenn eine Fachregel unklar ist: nicht plausibel ergänzen, sondern die Stelle markieren und vorlegen. Eine fehlende Funktion ist ein bekanntes Problem. Eine falsch geratene Frist ist ein unbekanntes.
