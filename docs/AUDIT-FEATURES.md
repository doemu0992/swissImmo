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
- **K — Verteilschlüssel-Modelle ungenutzt:** `Verteilschluessel`/`LiegenschaftVerteilschluessel` werden von `core/utils/billing.py` nicht gelesen; die Engine kennt vier feste Schlüssel.
- **K — Versand/Einsprache:** Es gibt nur Sammel-PDF und Portal-Ablage, keinen Mail-/Briefversand. (Felder jetzt vorhanden, U3.)
- M — keine Korrekturabrechnung nach Verbuchen; Leerstandsanteil wird ausgewiesen, aber nicht beim Eigentümer verbucht; kein Mieterbrief bei Akonto-Erhöhung (Art. 269d OR).

### 3.2 Inkasso
- **K — Betreibungs-Workflow:** Struktur jetzt da (U4), Oberfläche und Kopplung an Mahnstufe/Abschreibung fehlen (Verlustschein).
- M — Zahlungsvereinbarung ohne PDF/Unterschrift; keine Inkasso-/Anwaltsübergabe.

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
