# swissImmo – Bestandsanalyse (Phase 1)

**Stand:** 14.08.2026
**Analysierter Branch:** `claude/fairwalter-rebuild`, Commit `f4f7e6f`
**Methode:** Vollständige Lektüre des Repositories, ergänzt durch `manage.py check`, `makemigrations --check`, die Testsuite sowie programmatische Auswertungen der Modell-Registry, der Ninja-Endpunkt-Registry und anonyme Live-Anfragen gegen den Django-Testclient. Es wurde kein bestehender Code verändert.

> **Hinweis zur Branch-Wahl.** `origin/HEAD` zeigt auf `main`; dort ist der letzte Commit vom 21.05.2026. Die produktive Entwicklung läuft auf `claude/fairwalter-rebuild` — **501 Commits voraus** (363 im Juli, 138 im August), 416 geänderte Dateien, rund 75'000 Zeilen mehr. `main` ist ein reiner Vorfahre ohne eigene Commits. Diese Analyse bezieht sich ausschliesslich auf den Rebuild-Branch; eine frühere Fassung dieses Dokuments analysierte `main` und ist damit hinfällig.

---

## 0. Kurzfassung für Eilige

Seit der letzten Betrachtung hat sich die technische Basis erheblich verbessert. Was zuvor als drei akute Sofortbefunde galt, ist überwiegend erledigt: Die API ist durchgängig authentifiziert, das Medienverzeichnis wird zugriffskontrolliert ausgeliefert, es gibt ein Rollenmodell, einen Audit-Trail, eine Logging-Konfiguration, produktionstaugliche Security-Header und eine CI-Pipeline mit über tausend Tests.

Der verbleibende Kern ist damit klar umrissen — und er ist gross:

| # | Befund | Wirkung |
|---|---|---|
| **B1** | **Kein Mandantenmodell.** Keines der 63 Modelle hat einen Tenant-Bezug. `Verwaltung` ist als Singleton implementiert und wird an **132 Stellen** über `Verwaltung.objects.first()` gelesen. | Mandantenfähigkeit ist der einzige verbleibende Architekturbruch — und der grösste. |
| **B2** | **Rollen ohne Mandantengrenze.** Das Rollenkonzept trennt sauber *was* jemand darf, aber nicht *wessen Daten* er sieht. Jede Team-Rolle sieht alle Liegenschaften. | Die vorhandene Autorisierung ist eine gute Grundlage, ersetzt die Isolation aber nicht. |
| **B3** | **`core/views/fw.py` mit 14'938 Zeilen und 232 Views in einer Datei.** | Die zentrale strukturelle Schuld. Jede mandantenbezogene Änderung muss durch diese Datei. |

Anders als beim vorigen Stand gibt es **keinen Befund mehr, der einen Hotfix vor Phase 2 erzwingt.** Die Reihenfolge der Projektanweisung kann eingehalten werden.

---

## 1. Strukturübersicht

### 1.1 Projekt und Applikationen

Django 5.2.9, Python 3.12. Datenbank standardmässig SQLite; PostgreSQL ist über Umgebungsvariablen (`DB_ENGINE=postgres`) bereits vorbereitet, inklusive `CONN_MAX_AGE`. Deployment auf PythonAnywhere.

| App | Modelle | Migrationen | Rolle |
|---|---|---|---|
| `core` | 2 | 7 | Views, Services, Utils, Auth, Management-Commands, Templates |
| `crm` | 7 | 28 | Verwaltung, Eigentümer, Mieter, Adresshistorie, Handwerker, Vorlagen, Kommunikation |
| `portfolio` | 18 | 30 | Liegenschaften, Einheiten, Sollmietzins, Verteilschlüssel, Ausstattung, Geräte, Zähler, Schlüssel, Wartungsfristen, Fotos |
| `rentals` | 9 | 30 | Mietverträge, Staffeln, Mietzinshistorie, Anpassungen, Leerstände, Kündigungen, Abnahmeprotokolle, Dokumente |
| `finance` | 22 | 33 | Buchhaltung, Debitoren, Kreditoren, Mahnwesen, Nebenkosten, Anlagen/AfA, Erneuerungsfonds, Hypotheken, Bankabgleich |
| `tickets` | 4 | 7 | Schadenmeldungen, Fotos, Handwerkeraufträge, Ticketverlauf |
| `mietprozess` | 1 | 5 | Mietbewerbungen |

**63 Modelle, 140 Migrationen.** Codeumfang: 68'141 Zeilen Python (inklusive Migrationen und Tests), 27'088 Zeilen HTML, 900 Zeilen JS/CSS/TS.

Die historische Aufteilung aus einer ursprünglichen `core`-App wirkt weiter nach: Die meisten Tabellen heissen `core_*`, obwohl das Modell in einer anderen App liegt (`crm.Mieter` → `core_mieter`). Neuere Modelle nutzen App-Präfixe (`finance_kontoauszug`, `portfolio_sollmietzins`), sodass die Benennung heute uneinheitlich ist. Das ist kosmetisch, aber es erschwert die Orientierung in SQL-Abfragen und Datenmigrationen — was in Phase 2 relevant wird.

### 1.2 Datenmodell

Der fachliche Kern:

```
Verwaltung (Singleton, faktisch der Tenant)
Mandant (= Eigentümer) ──┐
                         ├─ Liegenschaft ── Einheit ── Mietvertrag ── VertragMietzins
                         │       │             │            │          MietzinsAnpassung
                         │       │             │            │          Staffelstufe
                         │       │             │            │          Kuendigung
                         │       │             │            │          Abnahmeprotokoll ── AbnahmeMangel
                         │       │             │            └── Zahlungseingang, DebitorenRechnung, Mahnung
                         │       │             ├── Sollmietzins, Leerstand, Mietbewerbung
                         │       │             ├── Verteilschluessel, Ausstattung, EinheitFoto
                         │       │             └── Zaehler ── ZaehlerStand
                         │       ├── AbrechnungsPeriode ── NebenkostenBeleg
                         │       ├── SchadenMeldung ── SchadenFoto, HandwerkerAuftrag, TicketNachricht
                         │       ├── Versicherung, Wartungsfrist, Unterhalt, Geraet, Schluessel
                         │       ├── Anlage ── Abschreibung
                         │       └── Hypothek, Erneuerungsfonds, Jahresabschluss
                         └── EigentuemerAuszahlung

Ohne Anbindung: Mieter, MieterAdresse, Handwerker, Vorlage, Kommunikation,
                Buchungskonto, LieferantProfil, NebenkostenLernRegel, Lebensdauer,
                Kontoauszug, AktivitaetsLog
```

> **Begriffswarnung – projektweit beachten**
> `crm.Mandant` bezeichnet im bestehenden Code den **Eigentümer** einer Liegenschaft, nicht den Mandanten im SaaS-Sinn der Projektanweisung. Der Tenant-Begriff entspricht am ehesten `crm.Verwaltung`. Diese Kollision ist die grösste Verwechslungsgefahr in Phase 2 und wiegt jetzt schwerer als zuvor, weil `Mandant` inzwischen ein eigenes Login (`benutzer`), ein Portal und eine Abrechnung hat.
> Empfehlung: Der neue Tenant heisst `Organisation`; `Mandant` wird bei Gelegenheit zu `Eigentuemer`. Solange beide Begriffe koexistieren, ist jede Verwendung in Code und Doku explizit zu qualifizieren.

Zwei Benutzerverknüpfungen existieren bereits als `OneToOneField` auf `auth.User`: `Mandant.benutzer` (Eigentümer-Portal) und `Mieter.benutzer` (Mieterportal). Ein **Custom User Model gibt es nicht** — siehe TS-1.

### 1.3 Views und URLs

**298 URL-Pfade**, davon **237 unter `/neu/`**. Vier Oberflächen bedienen dieselben Daten:

1. **`/neu/` – die aktuelle Hauptoberfläche.** Serverseitig gerendertes Django, 232 Views in `core/views/fw.py`, 101 Templates unter `core/templates/fw/`. Die 34 thematischen Blöcke der Datei decken Dashboard, Listen, Detailseiten, Mahnwesen, Bankabgleich, Kreditoren, Buchhaltung, Sollstellung, Nebenkosten, Vertragsassistent, Kündigungsprozess, Kautionsregister, MWST-Auswertung, Pendenzen und Benutzerverwaltung ab.
2. **`/app/` – die alte Vue-3-SPA.** Weiterhin vorhanden und für Team-Rollen erreichbar, mit sieben Tab-Templates und 1'399 Zeilen Inline-JavaScript. Der letzte Block in `fw.py` heisst wörtlich „ersetzt die `/app/`-Links" — die SPA ist abgelöst, aber nicht entfernt.
3. **`/portal/` – Eigentümerportal** (7 Pfade) und **`/mieter/` – Mieterportal** (16 Pfade). Beide mit eigenen, auf Eigentümerschaft geprüften Download-Views.
4. **Django-Admin** mit `django-unfold`, 2'096 Zeilen `admin.py`, weiterhin als vollwertige Zweitoberfläche.

**82 API-Endpunkte** unter `/api/` (Django Ninja) bedienen im Wesentlichen noch die alte SPA.

**Bewusst öffentlich:** Landing Page, Datenschutzerklärung, Schadenmeldung, Ticketformular je Liegenschaft, Bewerbungsformular, `/version/`, `/healthz/`, DocuSeal-Webhook, Brevo-Inbound-Webhook sowie zwei token-gesicherte Feeds (Portal-Feed für Immobilienportale, iCal-Feed für Fristen).

### 1.4 Templates und Frontend

**183 Templates**, davon 101 unter `fw/`. **86 erben von `fw/base.html`** — das ist die tragfähigste Struktur, die das Projekt bisher hatte.

`fw/base.html` (905 Zeilen) enthält bereits einen **Token-Ansatz**: rund 25 CSS-Variablen mit dem Präfix `--ds-` für Hintergründe, Flächen, Text, Linien, Markenfarbe, Statusfarben (`good`/`warn`/`crit`/`info` je mit Soft-Variante), Schatten und Radien — inklusive vollständiger Dark-Mode-Variante über `prefers-color-scheme` und `data-theme`.

Für Phase 4 ist das eine erheblich bessere Ausgangslage als erwartet. Drei Einschränkungen:

- Die Tokens sind **im Basistemplate eingebettet**, nicht in einer eigenen Stildatei. Für mandantenspezifisches Branding (Phase 4, Ziel: Akzentfarbe je Organisation) müssen sie an eine überschreibbare Stelle.
- Es gibt **Token, aber keine Komponenten**. Buttons, Formularfelder, Tabellen, Modals und Statusanzeigen werden je Template neu zusammengesetzt. **512 Inline-`style`-Attribute** über alle Templates.
- **Tailwind läuft weiterhin über `cdn.tailwindcss.com`** — die Play-CDN, ausdrücklich nicht für Produktion vorgesehen. Dazu Font Awesome über cdnjs und Inter über Google Fonts. Kein Build-Prozess für das Frontend; `package.json` existiert ausschliesslich für Playwright.

Daneben leben die alten Welten weiter: Vue 3 in der `/app/`-SPA und im Bewerbungsformular, Alpine.js in den öffentlichen Formularen, Bootstrap 5.3 in zwei Legacy-Templates, Unfold im Admin.

### 1.5 Abhängigkeiten

`requirements.txt` listet 100 gepinnte Pakete. Gegenüber `main` neu: `django-ninja==1.6.2` (die frühere Lücke ist geschlossen) und `zxing-cpp==3.1.0` (QR-Code-Erkennung).

Weiterhin offen:

- **`django-jazzmin`** ist installiert, aber nirgends importiert — nur Unfold ist in Verwendung.
- **`vulture`** (Dead-Code-Analyse) steht unter den Laufzeitabhängigkeiten.
- **Ungenutzt trotz Installation:** das Google-Cluster (`google-genai`, `google-ai-generativelanguage` und Folgeabhängigkeiten), `pytesseract`, `docxtpl`, `weasyprint`, `pyHanko`.
- Vier PDF-Bibliotheken (`xhtml2pdf`, `reportlab`, `weasyprint`, `pypdf`) und zwei QR-Bibliotheken (`segno`, `qrcodegen`) nebeneinander, ohne erkennbare Zuständigkeitsteilung.
- **Für die Zielarchitektur weiterhin nicht vorhanden:** Linter (`ruff`/`flake8`), Task-Queue, PostgreSQL-Treiber (`psycopg` — die Settings sehen Postgres vor, das Paket fehlt), Objektspeicher (`django-storages`), Zahlungsanbieter-SDK.

Keine Konfigurationsdatei (`pyproject.toml`, `setup.cfg`), keine Aufteilung in `base`/`dev`/`prod`.

### 1.6 KI- und OCR-Integrationen

Hier hat sich der Ist-Zustand grundlegend geändert. `finance/utils.py` (363 Zeilen) implementiert einen echten mehrstufigen Belegscanner gegen die **Groq-API**:

| Eingabe | Weg |
|---|---|
| Bilddatei (jpg/png/webp) | Vision-Modell `meta-llama/llama-4-scout-17b-16e-instruct` |
| PDF mit Textebene | Textmodell `llama-3.3-70b-versatile`, Fallback Regex |
| PDF ohne Textebene (Foto-Scan) | Seite 1 via `pdftoppm` rendern → Vision-Modell |

Bemerkenswert und richtig gelöst: Jedes Ergebnis trägt ein Feld `methode` (`ki` / `vision` / `regex` / `leer`) und einen `hinweis`, damit die Oberfläche offenlegt, **wie** erkannt wurde, statt still zu degradieren. Ohne `GROQ_API_KEY` läuft nur der Regex-Pfad, ohne Netzwerkzugriff. Der Prompt fordert gezielt Schweizer Spezifika ein (QR-Referenz mit 27 Ziffern statt Rechnungsnummer, QR-IBAN mit Kennung 30000–31999).

Verbleibend: `GEMINI_API_KEY` wird weiterhin in `settings.py` eingelesen und **nirgends verwendet**; `pytesseract` ist installiert und wird nirgends importiert. Der Betreibungsauszug-Scanner in `mietprozess` arbeitet weiterhin rein schlüsselwortbasiert über `pdfplumber`.

> **Zur Freigabepflicht:** Groq ist ein externer Dienst mit Kosten und Datenzugriff — Rechnungsbelege verlassen die Schweiz Richtung Groq-API. Nach der Projektanweisung wäre das freigabepflichtig. Es ist bereits umgesetzt, also kein Vorschlag mehr, sondern ein Punkt, der **nachträglich bewusst entschieden** werden sollte (Auftragsbearbeitungsvertrag, DSG-Bewertung, Kostenrahmen, Abschaltbarkeit als zubuchbares Modul nach Phase 3).

Weitere externe Integrationen: **DocuSeal** (digitale Signatur, jetzt mit optionalem Webhook-Secret und SSRF-Schutz über eine Host-Allowlist), **GeoAdmin/GWR** (EGID und Gebäudedaten), **BFS** (Referenzzins und LIK), **SMTP/IMAP** (E-Mail-Ein- und -Ausgang), **Brevo** (Inbound-Webhook, optional signiert).

### 1.7 Schweizer Besonderheiten

Der fachliche Kern ist der eigentliche Wert des Repositories und deutlich breiter als zuvor:

| Bereich | Umsetzung |
|---|---|
| QR-Rechnung | `core/utils/qr_code.py` (459 Zeilen), QR-IBAN-Erkennung, Debitoren-QR |
| Zahlungsverkehr | `pain.001` (Zahlungsaufträge), Bankabgleich mit Kontoauszügen, Zahler-Zuordnung |
| Mietrecht | `mietrecht.py`, `mahnstufen.py` (Art. 257d OR), `kuendigung_brief.py`, Kautionsgrenze nach Art. 257e OR serverseitig durchgesetzt |
| Amtliche Formulare | `formularpflicht.py` + `kantone.py` mit **allen 26 Kantonen**; ausgefüllte Original-PDFs für BE, SO, ZH (Anfangsmietzins, Mietzinsanpassung, Kündigung) |
| Nebenkosten | `nk_abrechnung.py`, Heizgradtage, unterjähriger Mieterwechsel, Verwaltungshonorar |
| MWST | `mwst_estv.py`, effektive Methode und Saldosteuersatz |
| Steuern/Eigentümer | `steuerauszug.py`, `eigentuemer_kontokorrent.py`, `mandat_abrechnung.py` |
| Datenschutz | `dsg.py`, Management-Commands `dsg_anonymisieren`, `bewerbungen_bereinigen` |

### 1.8 Tests, CI und Betrieb

Die grösste Veränderung gegenüber `main`.

| Ort | Umfang |
|---|---|
| `core/tests.py` | **16'586 Zeilen, 219 Testklassen, 1'066 Tests** |
| `rentals/tests.py` | 5 Tests (Mietzinsberechnung) |
| `crm`, `portfolio`, `finance`, `tickets`, `mietprozess` | leere Vorlagendateien |
| `e2e/tests/` | 7 Playwright-Specs (Smoke, Debitoren, Buchhaltung, Zahllauf, Nebenkosten) |

`.github/workflows/ci.yml` fährt zwei Jobs: `check` + `makemigrations --check` + Tests, sowie einen separaten E2E-Job mit Playwright gegen einen selbst gestarteten Django-Server. Ausgelöst auf `main`, `claude/**` und jedem Pull Request.

Kritisch anzumerken: Die gesamte Testmasse liegt in **einer Datei** von 16'586 Zeilen — dasselbe Muster wie bei `fw.py`. Für die Isolationstests aus Phase 2 (ein Test je Modell und Endpunkt) braucht es eine Aufteilung, sonst wächst die Datei unbedienbar weiter.

Betrieb: `LOGGING` mit `RotatingFileHandler` (5 MB, 5 Generationen) ist konfiguriert. Management-Commands `backup_db`, `pruefe_media_schutz` und `pruefe_webhook_secrets` prüfen die Betriebsannahmen selbst. `docs/AUTOMATISIERUNG.md` dokumentiert die geplanten Scheduled Tasks; alle Läufe sind als idempotent beschrieben und schreiben ins Aktivitätslog.

---

## 2. Mandantenfähigkeits-Audit

Leitfrage: *Was müsste heute wahr sein, damit zwei Verwaltungen dieselbe Instanz nutzen könnten, ohne Daten der jeweils anderen zu sehen?*

### 2.1 Modelle

`crm.Verwaltung` ist der einzige Kandidat für einen Mandantenanker, wird aber weiterhin als **Singleton** behandelt: `verbose_name` „Meine Verwaltung", Zugriff durchgängig über `Verwaltung.objects.first()`. Es gibt keine Beziehung von `Verwaltung` zu `auth.User`.

**Keines der 63 Modelle hat einen Tenant-Fremdschlüssel.** Die vier vorhandenen Treffer auf `Mandant`/`Verwaltung` meinen den Eigentümer, nicht den Tenant; `Liegenschaft.verwaltung` ist weiterhin `null=True` und wird nirgends ausgewertet.

Programmatische Einstufung aller 63 Modelle nach ihrem Weg zur `Liegenschaft`:

**Gruppe A – kein Weg zur Liegenschaft, auch nicht indirekt (14 Modelle):**
`core.AktivitaetsLog`, `crm.Verwaltung`, `crm.Mandant`, `crm.Mieter`, `crm.MieterAdresse`, `crm.Handwerker`, `crm.Vorlage`, `finance.Buchungskonto`, `finance.LieferantProfil`, `finance.NebenkostenLernRegel`, `finance.Kontoauszug`, `finance.EigentuemerAuszahlung`, `finance.Erneuerungsfonds`, `portfolio.Lebensdauer`.

Diese Gruppe ist gegenüber dem alten Stand von 4 auf 14 gewachsen — jedes neue Stammdaten- oder Querschnittsmodell kam ohne Mandantenbezug hinzu. `AktivitaetsLog` ist dabei besonders heikel: Das Audit-Log führt heute alle Aktionen aller künftigen Mandanten in einer Tabelle, und es ist genau das Modell, das man später am wenigsten nachträglich umschreiben möchte.

**Gruppe B – Weg nur über optionale Fremdschlüssel (15 Modelle):**
`finance.Bankbewegung`, `finance.Buchung`, `finance.DebitorenRechnung`, `finance.KreditorPosition`, `finance.KreditorenRechnung`, `finance.KreditorenZahlung`, `finance.Mahnung`, `finance.Zahlungseingang`, `portfolio.Dokument`, `portfolio.Geraet`, `portfolio.Zaehler`, `portfolio.ZaehlerStand`, `rentals.Dokument`, `crm.Kommunikation`, `core.Pendenz`.

Bei allen sind sämtliche Wege zur Liegenschaft `null=True`. Ein Datensatz kann also vollständig beziehungslos existieren — und damit keiner Organisation zugeordnet werden. `rentals.Dokument` bleibt der Extremfall; dort liegen die Mietverträge.

**Gruppe C – geschlossene Pflicht-Kette (34 Modelle):** Erreichen die Liegenschaft über Pflicht-Fremdschlüssel. Für diese Gruppe ist eine denormalisierte `organisation`-Spalte verlustfrei nachrüstbar.

**Sechs globale Unique-Constraints sind harte Blocker** — sie verhindern Mandantenfähigkeit auf Datenbankebene, nicht nur logisch:

| Modell.Feld | Warum es blockiert |
|---|---|
| `finance.Buchungskonto.nummer` | Zwei Mandanten könnten kein gleichnamiges Konto 4000 führen |
| `finance.NebenkostenLernRegel.suchwort` | Lernregeln aller Mandanten vermischen sich |
| `finance.LieferantProfil.name_key` | Lieferantenstamm wird geteilt |
| `finance.Buchung.beleg_nr` | Belegnummernkreis wäre mandantenübergreifend fortlaufend |
| `finance.ZahlerZuordnung.name_norm` | Zahler-Zuordnungen vermischen sich |
| `portfolio.Lebensdauer.kategorie` | Lebensdauertabelle global statt je Mandant |

Alle sechs müssen zu `unique_together`/`UniqueConstraint` mit der Organisation werden.

### 2.2 Queries

**136 ungefilterte `objects.all()`/`objects.first()`-Aufrufe** ausserhalb von Migrationen und Tests. Die Basisfunktion jeder `/neu/`-Seite ist exemplarisch:

```python
def _global_filter(request):
    """Liest den globalen Liegenschafts-Filter (?lg=) und liefert Basis-Kontext."""
    lg_id = request.GET.get('lg') or None
    aktive_lg = None
    if lg_id:
        aktive_lg = Liegenschaft.objects.filter(id=lg_id).first()   # keine Besitzprüfung
    return {
        'alle_liegenschaften': Liegenschaft.objects.all().order_by('strasse'),
        ...
    }
```

Der Filter liest die Liegenschaft aus einem GET-Parameter und prüft nicht, ob sie zum Benutzer gehört. Bei einem Mandanten ist das folgerichtig; bei mehreren ist es die Sollbruchstelle — und diese Funktion ist der Einstieg **jeder** der 232 `/neu/`-Views. Das ist zugleich die gute Nachricht: Es gibt genau eine Stelle, an der die Isolation ansetzen kann.

Dasselbe Muster auf der API-Seite: `get_object_or_404(Model, id=...)` ohne Besitzprüfung, IDs fortlaufend.

### 2.3 Autorisierung

Hier hat das Projekt einen grossen Schritt gemacht. `core/auth.py` (278 Zeilen) definiert vier Rollen als Django-Gruppen, per Migration angelegt (`core/migrations/0002_rollen_gruppen.py`):

| Rolle | Umfang |
|---|---|
| Verwaltung | Alles: Buchungsläufe, Löschen, Mahnungen, Vertragsversand |
| Sachbearbeitung | Erfassen und Bearbeiten |
| Lesend | Nur Ansicht und PDFs (Treuhand, Revision) |
| Eigentümer | Nur `/portal/`, ausdrücklich kein SPA-/API-Zugriff |

Die Durchsetzung ist konsequent:

- **API:** `NinjaAPI(auth=auth_lesen)` global. Aufschlüsselung der 82 Endpunkte: 33 `auth_schreiben`, 24 `auth_verwaltung`, 23 erben `auth_lesen`, **2 sind explizit `auth=None`** (Bewerbungsformular, DocuSeal-Webhook) — beide im Code begründet. `/api/docs` ist auf Staff beschränkt.
- **Verifiziert, nicht angenommen:** Zwölf anonyme Anfragen gegen Endpunkte quer durch alle sechs Router liefern **durchgängig 401**. (Eine reine Auswertung der Ninja-Registry ist hier irreführend: Leere `auth_callbacks` bedeuten „erbt von der API", nicht „offen".)
- **`/neu/`-Views:** Von 232 `fw_`-Views tragen **231** ein `@rolle_erforderlich`. Die eine Ausnahme, `fw_vermarktung_feed`, ist der öffentliche Objekt-Feed für Immobilienportale und über einen Token mit `hmac.compare_digest` abgesichert.
- Der Dekorator unterscheidet sauber zwischen „nicht angemeldet" (Redirect zum Login) und „angemeldet, falsche Rolle" (403) und legt seine Rollen an der View ab, sodass die Oberfläche unerreichbare Aktionen ausgrauen kann, ohne eine zweite Rechteliste zu pflegen.

**Was fehlt, ist nicht die Autorisierung, sondern die Isolation.** Die Rollen beantworten „darf dieser Benutzer löschen?", nicht „darf dieser Benutzer *diesen* Datensatz löschen?". Der Kommentar im Code benennt das Problem selbst: Eigentümer sind von den Team-Rollen ausgenommen, weil sie sonst „die Daten ALLER Mandanten sehen" würden. Die Bemerkung stimmt — und sie gilt genauso für jedes künftige zweite Verwaltungsunternehmen.

Die Portale sind hier die Ausnahme und zugleich das Vorbild: `portal_view` und die Mieter-Views filtern konsequent über `request.user.mandant_profil` beziehungsweise die Mieter-Verknüpfung. Das ist datensatzbezogene Isolation — sie existiert im Projekt bereits, nur eben für Eigentümer und Mieter, nicht für Verwaltungen.

### 2.4 Dateiablage

Deutlich verbessert. `core/views/media_protected.py` ersetzt die frühere ungeschützte Auslieferung:

- Sensible Präfixe (Bewerberdokumente, Verträge, Belege, Kautionszertifikate, Abnahmefotos, Unterschriften, Schadenfotos, der Alt-Topf `uploads/`) nur für Team-Rollen.
- Öffentlich nur Logos und Objektfotos, und nur mit Bildendungen; `.svg` ist bewusst ausgeschlossen (XSS über eingebettetes JavaScript).
- Die Sensibilitätsprüfung arbeitet auf dem **aufgelösten** Pfad, nicht auf der rohen URL — der Kommentar erklärt den Umgehungsversuch über `%2e/` korrekt.
- Nicht inline-fähige Dateien gehen als `attachment` mit `nosniff` raus.
- Fehlende Berechtigung liefert 404 statt 403 (kein Existenz-Leak).
- `get_smart_upload_path` sortiert nach Modelltyp in getrennte Ordner, unbekannte Modelle landen im geschützten `uploads/`.

Für die Mandantenfähigkeit bleiben zwei Lücken:

1. **Kein Mandantenbezug im Pfad.** Die Struktur ist `<ordner>/<datum>/<dateiname>` — alle Dateien aller Verwaltungen im selben Baum. Für Phase 2 muss `organisation/<id>/` davor.
2. **Kollisionsgefahr.** Zwei Uploads mit gleichem Namen am selben Tag überschreiben sich oder erhalten Django-Suffixe.

Ein Betriebsrisiko ist im Code selbst dokumentiert: Auf PythonAnywhere darf `/media/` **nicht** als statisches Mapping konfiguriert sein, sonst umgeht der Webserver den Schutz-View vollständig. Es gibt dafür den Prüfbefehl `pruefe_media_schutz` — die Absicherung hängt damit an einer Deployment-Einstellung ausserhalb des Repositories.

### 2.5 Hintergrundjobs

Keine Task-Queue; **19 Management-Commands** laufen über den PythonAnywhere-Scheduler, dokumentiert in `docs/AUTOMATISIERUNG.md`:

| Command | Rhythmus | Mandantenbezug |
|---|---|---|
| `taeglicher_lauf` | täglich | keiner — Pendenzen, Zinsupdate, Bewerbungsbereinigung global |
| `mahnlauf` | wöchentlich | keiner — über alle fälligen Debitoren |
| `monatslauf` | monatlich | keiner — Sollstellung über alle Verträge |
| `jahresabschluss_lauf` | jährlich | keiner — AfA und Erneuerungsfonds über alle Liegenschaften |
| `update_rates`, `check_rents`, `fristen_digest`, `send_eigentuemer_reports` | div. | `Verwaltung.objects.first()` |
| `fetch_replies`, `fetch_rechnungen` | Dauerlauf | ein IMAP-Postfach für alles |
| `backup_db`, `dsg_anonymisieren`, `bewerbungen_bereinigen`, `mieter_zugang`, `seed_e2e`, `sync_contracts`, `pruefe_*` | div. | keiner |

Alle Läufe sind als idempotent beschrieben und protokollieren ins Aktivitätslog — eine gute Grundlage. Für Mandantenfähigkeit muss jeder Lauf über Organisationen iterieren statt global zu arbeiten, und `fetch_replies`/`fetch_rechnungen` brauchen je Mandant ein eigenes Postfach oder eine eindeutige Zuordnung.

`check_rents` ist weiterhin **defekt** (siehe TS-2).

### 2.6 Exporte, PDF und E-Mail

Jede PDF- und E-Mail-Erzeugung zieht den Absender über `Verwaltung.objects.first()` — verteilt über `pdf_service`, `ablage`, `debitor_qr`, `docuseal_service`, `dokument_service`, `mietprozess_briefe`, `ticket_workflow`, `billing`, `email_views`. Bei mehreren Mandanten würden **alle Dokumente und E-Mails im Namen derjenigen Verwaltung versendet, die den niedrigsten Primärschlüssel hat.**

Der SMTP-Zugang ist fest in `settings.py` verdrahtet (ein Konto für alles), immerhin jetzt mit `EMAIL_TIMEOUT`. `PORTAL_BASE_URL` ist eine einzelne globale Basis-URL — mandantenspezifische Domains sind nicht vorgesehen.

### 2.7 Logging und Audit

Der Audit-Trail existiert und ist gut gebaut. `core.AktivitaetsLog` erfasst Benutzer, Aktion, Objekt, Details, Zieltyp, Ziel-ID, Kategorie und IP-Adresse. `snapshot_model()`/`diff_model()` erzeugen Vorher-Nachher-Vergleiche automatisch aus den Modellfeldern und nutzen deren `verbose_name` als Beschriftung. Die Kategorisierung ist stichwortbasiert (`geloescht`, `sicherheit`, `finanzen`, `versand`, `erstellt`, `bearbeitet`). `log_aktion` schluckt Fehler bewusst, damit Protokollierung nie einen Geschäftsprozess bricht — richtig entschieden.

Zwei Punkte für Phase 2: Der Log hat **keine Organisationsspalte** (Gruppe A), und die stichwortbasierte Kategorisierung ist ausschliesslich auf deutsche Aktionstexte ausgelegt — sie bricht, sobald Phase 5 die Oberfläche mehrsprachig macht.

### 2.8 Zusammenfassung des Audits

| Dimension | Stand `main` (alt) | Stand `claude/fairwalter-rebuild` |
|---|---|---|
| Authentifizierung API | 0 von 82 Endpunkten | **82 von 82** (2 bewusst öffentlich) |
| Autorisierung Views | 9 von 20 | **231 von 232** (1 token-gesichert) |
| Rollenmodell | nicht vorhanden | **4 Rollen, zentral durchgesetzt** |
| Dateiablage geschützt | nein | **ja**, differenziert nach Sensibilität |
| Logging / Audit-Trail | nicht vorhanden | **vorhanden**, mit Vorher-Nachher-Diff |
| Security-Header | nicht vorhanden | **vorhanden** (HSTS, Secure-Cookies, SSL-Redirect) |
| Tests / CI | 5 Tests, keine CI | **1'071 Tests + 7 E2E-Specs, CI aktiv** |
| **Mandantenmodell** | **nicht vorhanden** | **nicht vorhanden** |
| **Fachdaten mit Mandantenbindung** | **0 von 33** | **0 von 63** |
| **Query-Isolation** | **nicht vorhanden** | **nicht vorhanden** |
| **Dateiablage mandantengetrennt** | **nein** | **nein** |
| **Hintergrundjobs mandantengetrennt** | **nein** | **nein** |
| **Exporte, PDF, E-Mail getrennt** | **nein** | **nein** |

Alles, was *innerhalb* eines Mandanten geschützt werden musste, ist geschützt. Alles, was *zwischen* Mandanten trennen müsste, fehlt vollständig.

---

## 3. Technische Schulden

**TS-1 – Kein Custom User Model.** Django verwendet `auth.User`. Ein späterer Wechsel ist nach Produktivgang unverhältnismässig teuer. Erschwerend: Es hängen bereits zwei `OneToOneField` daran (`Mandant.benutzer`, `Mieter.benutzer`), das Rollenmodell arbeitet über `user.groups`, und es gibt eine Benutzerverwaltung in `/neu/`. **Das ist die Entscheidung, die in Phase 2 zuerst fallen muss** — vor der Organisationsmodellierung, nicht als deren Nebenschritt.

**TS-2 – `core/views/fw.py` mit 14'938 Zeilen.** 232 Views, 34 thematische Blöcke, in einer Datei. Dieselbe Datei enthält 50 der 132 `Verwaltung.objects`-Aufrufe. Jede mandantenbezogene Änderung, jedes Entitlement, jede Übersetzung muss hier hindurch. Die Aufteilung entlang der bereits vorhandenen Blockgrenzen (Debitoren, Kreditoren, Buchhaltung, Nebenkosten, Objekte, Verträge, Mietprozess, Profil) ist naheliegend und sollte **vor** Phase 2 geschehen, nicht danach.

**TS-3 – `core/tests.py` mit 16'586 Zeilen.** Dasselbe Muster. 219 Testklassen in einer Datei. Die Isolationstests aus Phase 2 kommen additiv dazu; ohne Aufteilung wächst die Datei unbedienbar. Fünf von sieben Apps haben weiterhin leere `tests.py`, obwohl ihre Logik in `core/tests.py` mitgetestet wird — der Ablageort folgt nicht der fachlichen Zuständigkeit.

**TS-4 – Verweise auf nicht existierendes Modul.** `core.mietrecht_logic` wird an drei Stellen importiert (`core/dashboard.py`, `core/management/commands/check_rents.py`, `rentals/admin.py`), existiert aber nicht; die Funktion liegt in `rentals/services.py`. `check_rents` ist damit defekt. Unverändert seit dem alten Stand.

**TS-5 – Toter Code.** `core/dashboard.py` importiert zusätzlich `finance.models.Zahlung` — ein Modell, das nicht existiert (es heisst `Zahlungseingang`) — und wird von niemandem importiert. `core/views/webhooks.py` (Brevo-Inbound) ist in keiner URL-Konfiguration registriert. `core/utils/core/` enthält weiterhin gleichzeitig eine Datei `utils.py` und ein Verzeichnis `utils/` und ist damit nicht importierbar; die dort liegende zweite Fassung von `get_current_ref_zins()` liefert einen abweichenden Wert. `.debug_lik.py.swp` (Vim-Swap-Datei) liegt weiterhin im Wurzelverzeichnis.

**TS-6 – Zwei konkurrierende `Dokument`-Modelle.** `portfolio.Dokument` und `rentals.Dokument` existieren weiterhin parallel. Der ID-Offset-Hack (`id + 10000`, Rückrechnung beim Löschen) steht unverändert an vier Stellen. Ab 10'000 Dokumenten in `portfolio` kollidieren die Nummernkreise stillschweigend, und Löschanfragen träfen den falschen Datensatz. Immerhin ist der frühere Folgefehler behoben: `Mietvertrag.save()` legt jetzt über `core/services/ablage.py` korrekt ab.

**TS-7 – Zwei bis vier Oberflächen für dieselben Daten.** `/neu/`, die alte `/app/`-SPA mit 82 API-Endpunkten, der Unfold-Admin und die Portale. Die SPA ist laut Code abgelöst, aber vollständig vorhanden und für Team-Rollen erreichbar. Jede Berechtigungs-, Mandanten- und Übersetzungsregel muss derzeit **viermal** implementiert werden. Hier ist eine Entscheidung fällig, bevor Phase 2 beginnt — sie halbiert oder verdoppelt den Aufwand aller Folgephasen.

**TS-8 – Massenhaftes Verschlucken von Ausnahmen.** 21 blanke `except:` und 233 `except Exception:`-Blöcke ausserhalb der Migrationen. Ein Teil davon ist bewusst und kommentiert (`logger.debug("Fehler bewusst übergangen")` — deutlich besser als ein stilles `pass`). Der Rest bleibt problematisch: Im Betrieb ist nicht erkennbar, ob eine Operation gelungen ist.

**TS-9 – Frontend ohne Build.** Tailwind über die Play-CDN in Produktion, Font Awesome über cdnjs, Inter über Google Fonts, 512 Inline-Styles, kein Bundler. Externe Ausfälle legen die Oberfläche lahm; ausserdem verlassen bei jedem Seitenaufruf Requests die Schweiz — bei einem Produkt mit Mieterdaten ein eigenständiges Datenschutzthema. `package.json` existiert bereits, enthält aber nur Playwright.

**TS-10 – Mehrsprachigkeit bei null.** `USE_I18N = True` ist gesetzt, aber es fehlen `LocaleMiddleware`, `LOCALE_PATHS`, `LANGUAGES` und jedes `locale/`-Verzeichnis. **Kein einziger projekteigener `gettext`-Aufruf** — der einzige Treffer stammt unverändert aus Djangos Admin-Template. Sämtliche Feldbezeichnungen, Auswahllisten, Statuswerte, Vorlagen, Briefe und PDF-Texte sind hart auf Deutsch verdrahtet, ebenso die Stichwortlisten der Audit-Kategorisierung und der Belegerkennung. `Mieter.sprache` ist mit den vier Zielsprachen angelegt, wird aber nicht ausgewertet. Phase 5 bedeutet hier, praktisch jede Zeichenkette im Projekt anzufassen — bei 27'088 Zeilen HTML der grösste Einzelposten des gesamten Plans.

**TS-11 – Abo-Feld ohne Wirkung.** `Verwaltung.abo_plan` kennt drei Stufen (Start, Pro, Premium) und es gibt eine Preisseite mit Mengenstaffel nach Einheiten. Die Auswahl setzt jedoch nur ein Feld — **es gibt keine einzige Stelle, an der eine Funktion abhängig vom Plan freigegeben oder gesperrt wird.** Für Phase 3 heisst das: Die Preislogik ist vorhanden, das Entitlement-System fehlt vollständig. Ausserdem verlangt die Projektanweisung **vier** Stufen, nicht drei.

**TS-12 – Kein Linter, keine Projektkonfiguration.** Weder `ruff`/`flake8` noch `pyproject.toml`/`setup.cfg`. Die CI prüft `check`, Migrationen und Tests — die Definition of Done „keine neuen Linter-Fehler" ist derzeit nicht überprüfbar.

**TS-13 – SQLite als Produktionsdatenbank.** PostgreSQL ist in den Settings vorbereitet, aber `psycopg` fehlt in `requirements.txt`, und der Standardpfad bleibt SQLite (`timeout: 30` deutet auf Sperrkonflikte hin). Bei gleichzeitigen Schreibzugriffen mehrerer Mandanten nicht tragfähig.

**TS-14 – Ungenutzte Abhängigkeiten und Doppelungen.** `django-jazzmin`, das Google-Cluster, `pytesseract`, `docxtpl`, `weasyprint`, `pyHanko` sind installiert und ungenutzt; `vulture` steht unter den Laufzeitabhängigkeiten. Vier PDF- und zwei QR-Bibliotheken parallel. `GEMINI_API_KEY` wird eingelesen und nirgends verwendet.

---

## 4. Priorisierte Massnahmenliste

Die Nummerierung ist die empfohlene Reihenfolge.

### P0 – Aufräumen und Entscheiden (vor Phase 2, klein)

| Nr. | Massnahme | Aufwand |
|---|---|---|
| P0.1 | **Entscheidung `/app/`-SPA:** entfernen oder als Zweitoberfläche behalten. Bei Entfernen fallen 7 Tab-Templates, 1'399 Zeilen JS und der Grossteil der 82 API-Endpunkte weg — das reduziert jede Folgephase erheblich. | S (Entscheidung), M (Umsetzung) |
| P0.2 | Analoge Entscheidung für den Unfold-Admin: bleibt er, unterliegt er denselben Mandanten- und Rollenregeln | S |
| P0.3 | TS-4 beheben: Importe auf `rentals.services` korrigieren, `check_rents` wieder lauffähig machen | XS |
| P0.4 | TS-5 beheben: `core/dashboard.py`, `core/views/webhooks.py`, `core/utils/core/`, `.debug_lik.py.swp` entfernen; `.gitignore` um `*.swp` ergänzen | S |
| P0.5 | `psycopg` in `requirements.txt` nachtragen; `django-jazzmin`, `vulture` und die ungenutzten Pakete entfernen; `GEMINI_API_KEY` streichen | S |
| P0.6 | Ruff plus `pyproject.toml` einführen und in die CI aufnehmen — sonst ist die Definition of Done ab Phase 2 nicht prüfbar | S |
| P0.7 | Groq-Nutzung nachträglich formalisieren: Auftragsbearbeitungsvertrag, DSG-Bewertung, Kostenrahmen, Abschaltbarkeit dokumentieren | S |
| P0.8 | `test_foto_beleg_mit_qr_wird_dekodiert` gegen fehlendes `zxing-cpp` absichern (`skipUnless`), damit ein unvollständiger Install nicht als Fachfehler erscheint (siehe Prüfprotokoll) | XS |

### P1 – Fundament für Phase 2

| Nr. | Massnahme | Aufwand |
|---|---|---|
| P1.1 | **Custom User Model einführen** — muss vor allem anderen geschehen, danach kaum noch möglich (TS-1) | M |
| P1.2 | **`fw.py` entlang der 34 Blockgrenzen aufteilen** — Voraussetzung dafür, dass die Isolation überhaupt reviewbar wird (TS-2) | M |
| P1.3 | **`core/tests.py` nach Fachgebiet aufteilen**, in die jeweiligen Apps verschieben (TS-3) | M |
| P1.4 | Wechsel auf PostgreSQL inklusive Datenmigration (TS-13) | M |
| P1.5 | Modell `Organisation` einführen; Verhältnis zu `crm.Verwaltung` klären (Migration oder Ablösung); `Mandant` zu `Eigentuemer` umbenennen | M |
| P1.6 | `organisation`-Fremdschlüssel auf alle 63 Modelle; Datenmigration weist Bestand einer Ausgangsorganisation zu; anschliessend `null=False`. Gruppen A und B (29 Modelle) brauchen dabei zusätzlich eine fachliche Entscheidung, woher der Bezug kommt | L |
| P1.7 | Sechs globale Unique-Constraints zu `UniqueConstraint` mit der Organisation umbauen | S |
| P1.8 | **Zentrale Isolation:** `TenantManager` als Default-Manager plus Middleware mit Kontextvariable. `_global_filter()` in `fw.py` ist der natürliche Ansatzpunkt für die Oberfläche — die Erzwingung gehört aber auf die Manager-Ebene, nicht dorthin | M |
| P1.9 | Rollenmodell auf die Organisation beziehen: heute globale Django-Gruppen, künftig Mitgliedschaft je Organisation. Die Projektanweisung nennt Inhaber, Verwalter, Sachbearbeiter, Lesezugriff — Abgleich mit den bestehenden vier Rollen nötig | M |
| P1.10 | **Isolationstests:** für jedes Modell und jeden Endpunkt ein Test, der einen mandantenübergreifenden Zugriff versucht und fehlschlagen **muss** | L |
| P1.11 | Dateiablage auf `organisation/<id>/…` umstellen, Bestandsdateien migrieren; Deployment-Prüfung `pruefe_media_schutz` in die CI aufnehmen | M |
| P1.12 | Alle 19 Management-Commands über Organisationen iterieren lassen; `fetch_replies`/`fetch_rechnungen` je Mandant trennen | M |
| P1.13 | `AktivitaetsLog` um die Organisation erweitern; strukturiertes Logging mit Organisations-ID | S |
| P1.14 | Absender für PDF und E-Mail aus der Organisation statt aus `Verwaltung.objects.first()` beziehen (132 Fundstellen) | M |

### P2 – Konsolidierung (parallel zu Phase 2 möglich)

| Nr. | Massnahme | Aufwand |
|---|---|---|
| P2.1 | `Dokument`-Modelle zusammenführen, ID-Offset-Hack ersatzlos streichen (TS-6) | L |
| P2.2 | Ausnahmebehandlung überarbeiten: blanke `except` ersetzen, Fehler protokollieren (TS-8) | M |
| P2.3 | `requirements.txt` in `base`/`dev`/`prod` aufteilen; PDF- und QR-Bibliotheken auf je eine reduzieren | S |
| P2.4 | Tabellennamen vereinheitlichen (`core_*` gegenüber App-Präfix) — sinnvollerweise gebündelt mit der Postgres-Migration | S |

### P3 – Vorbereitung der Phasen 3 bis 6

| Nr. | Massnahme | Bezug |
|---|---|---|
| P3.1 | Entitlement-System als zentrale Prüfstelle entwerfen; bestehende drei Abo-Stufen auf die vier der Projektanweisung erweitern (TS-11) | Phase 3 |
| P3.2 | Zahlungsanbieter evaluieren (Schweizer MWST, Abo-Verwaltung, Testphase, Up-/Downgrade); Verhalten bei Downgrade und Zahlungsausfall definieren | Phase 3 |
| P3.3 | Modulgrenzen schneiden — Kandidaten sind bereits gut abgegrenzt: DocuSeal-Signatur, Groq-Belegerkennung, Nebenkostenabrechnung, Reporting, Schnittstellen (Portal-Feed, iCal, pain.001) | Phase 3 |
| P3.4 | Design-Tokens aus `fw/base.html` in eine eigene Stildatei herauslösen, damit mandantenspezifisches Branding nur eine Token-Überschreibung ist | Phase 4 |
| P3.5 | Komponentenschicht auf den vorhandenen Tokens aufbauen (Buttons, Formulare, Tabellen, Modals, Statusanzeigen, leere Zustände); 512 Inline-Styles auflösen | Phase 4 |
| P3.6 | Build-Prozess einführen, CDN-Abhängigkeiten auflösen, Tailwind lokal kompilieren (TS-9) | Phase 4 |
| P3.7 | i18n-Grundlage schaffen (`LocaleMiddleware`, `LOCALE_PATHS`, `LANGUAGES`); anschliessend systematische Extraktion. Die stichwortbasierte Audit-Kategorisierung und der Belegerkennungs-Prompt müssen dabei mitgedacht werden (TS-10) | Phase 5 |
| P3.8 | Amtliche Formulare über BE/SO/ZH hinaus ergänzen — `kantone.py` deckt alle 26 Kantone ab, PDFs existieren für drei | Phase 5 |
| P3.9 | Handbuch nach Nutzeraufgaben gliedern; `docs/AUTOMATISIERUNG.md` und `docs/KANTON_FORMULARE.md` sind brauchbare Bausteine | Phase 6 |

---

## 5. Einschätzung

Das Projekt hat zwischen Mai und August erheblich an technischer Reife gewonnen. Die Befunde, die zuvor als akute Datenschutzrisiken einzustufen waren — offene API, ungeschütztes Medienverzeichnis, fehlende Security-Konfiguration — sind sauber und mit nachvollziehbarer Begründung im Code behoben. Rollenkonzept, Audit-Trail, Medienschutz und Testsuite sind nicht nur vorhanden, sondern durchdacht; an mehreren Stellen dokumentiert der Code Angriffsszenarien, die man in Projekten dieser Grösse selten adressiert sieht.

Gleichzeitig ist der fachliche Umfang stark gewachsen: doppelte Buchhaltung, Bankabgleich, pain.001, MWST-Abrechnung nach beiden Methoden, AfA, Erneuerungsfonds, Kautionsregister, Kündigungsfristen, amtliche Formulare, Eigentümer- und Mieterportal. Das ist der Wert des Repositories.

Drei Punkte bestimmen die Reihenfolge in Phase 2:

1. **Das Custom User Model muss zuerst kommen.** Es hängen bereits zwei Portale, ein Rollenmodell und eine Benutzerverwaltung daran; jeder weitere Monat erhöht die Kosten.
2. **`fw.py` und `core/tests.py` müssen vor der Mandantenfähigkeit aufgeteilt werden.** Nicht aus Ästhetik: Eine Isolationsänderung, die durch 14'938 Zeilen mit 50 Singleton-Zugriffen läuft, ist nicht reviewbar — und die Definition of Done verlangt geprüfte Mandantentrennung, nicht behauptete.
3. **Die Entscheidung über `/app/` und den Admin gehört an den Anfang.** Solange vier Oberflächen dieselben Daten bedienen, wird jede Regel viermal gebaut. Das betrifft Isolation, Entitlements und Übersetzung gleichermassen — also die Phasen 2, 3 und 5.

Der eine Punkt, der sich seit Mai nicht bewegt hat, ist zugleich der zentrale: **Die Annahme „ein Mandant" steckt unverändert in allen 63 Modellen, in jeder Query, in der Dateiablage, in jedem Hintergrundjob und in jedem generierten PDF.** Sie ist inzwischen tiefer eingebaut als zuvor, weil in drei Monaten 30 weitere Modelle und 232 Views ohne Mandantenbezug entstanden sind.

Das ist kein Vorwurf — die Priorität lag erkennbar und richtig auf Fachlichkeit und Absicherung. Es ist eine Aussage über die Kostenkurve: Jeder weitere Monat ohne Organisationsmodell macht Phase 2 teurer. Nach dem Aufräumen aus P0 sollte sie beginnen.

---

## Anhang: Prüfprotokoll

| Prüfung | Ergebnis |
|---|---|
| `python manage.py check` | Keine Beanstandungen (1 unterdrückt) |
| `python manage.py makemigrations --check --dry-run` | Keine Änderungen — Modelle und Migrationen konsistent |
| `python manage.py test` | **1'068 Tests, alle grün** (in sechs Blöcken ausgeführt, siehe Anmerkung unten) |
| API-Endpunkte (Ninja-Registry) | 82 gesamt: 33 `auth_schreiben`, 24 `auth_verwaltung`, 23 geerbtes `auth_lesen`, 2 explizit `auth=None` |
| Anonyme API-Anfragen (Testclient, 12 Endpunkte quer über alle Router) | **12 × 401** |
| Anonyme View-Anfragen (`/neu/`, `/neu/debitoren/`, `/neu/liegenschaften/`, `/app/`, `/portal/`) | 5 × 302 auf `/login/` |
| `fw_`-Views mit `@rolle_erforderlich` | 231 von 232 (Ausnahme: token-gesicherter Portal-Feed) |
| Modelle gesamt | 63 über 7 Apps, 140 Migrationen |
| Modelle mit Tenant-Bezug | **0 von 63** |
| Modelle ohne Weg zur Liegenschaft | 14 (Gruppe A) |
| Modelle mit Weg nur über optionale FK | 15 (Gruppe B) |
| Globale Unique-Constraints als Mandanten-Blocker | 6 |
| `Verwaltung.objects.*` | **132 Vorkommen** (50 davon in `fw.py`, 49 in `core/tests.py`) |
| Ungefilterte `objects.all()`/`.first()` | 136 (ohne Migrationen und Tests) |
| URL-Pfade | 298, davon 237 unter `/neu/` |
| Templates | 183, davon 101 unter `fw/`, 86 erben `fw/base.html` |
| Design-Tokens (`--ds-*`) | ~25, inkl. Dark Mode, eingebettet in `fw/base.html` |
| Inline-`style`-Attribute | 512 |
| `gettext`/`{% trans %}` im Projektcode | **0** projekteigene Vorkommen |
| `locale/`, `LOCALE_PATHS`, `LANGUAGES`, `LocaleMiddleware` | keines vorhanden |
| Blanke `except:` / `except Exception:` | 21 / 233 |
| Testdateien mit Inhalt | 2 von 7 (`core/tests.py`, `rentals/tests.py`) |
| Entitlement-Prüfungen abhängig von `abo_plan` | **0** |

### Anmerkung zur Testausführung

Die Suite braucht rund zehn Minuten und liess sich in dieser Umgebung nicht am Stück fahren. Ausgeführt wurde sie deshalb in sechs Blöcken (fünf Blöcke `core.tests` nach Testklassen aufgeteilt, plus die übrigen sechs Apps), jeweils mit `--parallel 8`:

| Block | Tests | Dauer | Ergebnis |
|---|---|---|---|
| `core.tests` 1/5 | 186 | 123 s | OK |
| `core.tests` 2/5 | 213 | 112 s | OK |
| `core.tests` 3/5 | 182 | 94 s | OK |
| `core.tests` 4/5 | 269 | 149 s | OK |
| `core.tests` 5/5 | 213 | 94 s | OK |
| `crm`, `portfolio`, `rentals`, `finance`, `tickets`, `mietprozess` | 5 | < 1 s | OK |
| **Summe** | **1'068** | **~10 min** | **OK** |

Zwei Nebenbefunde aus dem Testlauf:

1. **Ein Test schlägt fehl, wenn `zxing-cpp` nicht installiert ist** (`test_foto_beleg_mit_qr_wird_dekodiert`: erwartet `methode == 'qr'`, erhält `'leer'`). Das Paket steht in `requirements.txt`; in einer Umgebung ohne vollständigen Install bricht die Suite also mit einem irreführenden Fachfehler statt mit einer klaren Meldung über die fehlende Abhängigkeit. Der Produktivcode protokolliert die Lücke korrekt (`zxing-cpp nicht installiert — QR-Decoder inaktiv`); der Test sollte sie entweder überspringen (`skipUnless`) oder die Abhängigkeit hart voraussetzen. Erschwerend: Unter `--parallel` verdeckt ein Pickle-Fehler des Multiprocessing-Pools (`cannot pickle 'traceback' object`) die eigentliche Fehlermeldung vollständig.
2. **Die Laufzeit von rund zehn Minuten** ist für eine Unit-Suite hoch und rührt daher, dass viele Tests echte PDFs erzeugen und den Testclient über volle Seitenrenderings schicken. Das ist derzeit tragbar, wird aber mit den Isolationstests aus Phase 2 (ein Test je Modell und Endpunkt, also mehrere Hundert zusätzliche) zum Engpass in der CI. Die Aufteilung aus P1.3 sollte deshalb auch nach Laufzeit gruppieren, nicht nur nach Fachgebiet.
