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

---

# Fortsetzung: Phasen 2–4

## Phase 2 — Oberfläche für die Basis-Strukturen

| Prozess | Einstieg | Schutz |
|---|---|---|
| Ticket intern zuweisen, SLA-Frist | Block «Zuständigkeit» im Ticket, Filter «Meine Tickets», Chip «SLA überfällig» | nur Inhaber/Verwalter/Sachbearbeiter (nicht Hauswart, `core/tests/test_rbac.py`) |
| NK-Zustellung, Einsprachefrist | Knopf in der Nebenkostenabrechnung | erst nach Verbuchen; Datum nicht vor Periodenende, nicht in der Zukunft |
| Betreibung (SchKG) | Mahnwesen → «Betreibung», Liste `/neu/betreibungen/` | Datumsfolge, Stand↔Datum, 10-Tage-Frist (Art. 74), Forderung > 0 |
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
- Priorität «Notfall» (SLA 0 Tage) ist im Modell vorgesehen, das Meldeformular bietet sie nicht an.
- Spaltenfilter wirken nur auf die geladene Seite, nicht serverseitig über alle Seiten.
- Debitorentabelle ist bei 1440 px breiter als der Rahmen (Aktionsspalte scrollt) — schon vorher so.
- Übersetzungen FR/IT/EN der neuen Texte stammen von der KI; Rechtsbegriffe fachlich gegenlesen.
- NK-Versand per E-Mail/Brief, Verteilschlüssel-Anbindung der Engine, STWEG-Planung: siehe 3.1–3.4.
