# immoswiss – Architekturnotizen

**Stand:** 14.11.2026, gemessen an `main` nach PR #260.
**Zweck:** Orientierung für alle, die neue Funktionen in diese Codebasis einbauen.
**Methode:** Lektüre der Kernmodule (Mandantenschicht, Rechte, Abo, Buchhaltung, Fallmaschine, Oberflächenschicht),
der Projektdokumente unter `docs/` und Zählungen über das Repository. Zahlen sind gezählt, nicht geschätzt; wo etwas
nicht geprüft werden konnte, steht das dabei.

> Dieses Dokument ersetzt `docs/ANALYSE.md` nicht, es ist dessen Fortschreibung. Die Analyse vom 14.08.2026 beschreibt
> einen Stand ohne Mandantenmodell, mit einer 15'000-Zeilen-Viewdatei und einer Vue-SPA. Alle drei Befunde sind
> seither erledigt.

---

## 1. Architektur und Datenfluss

### 1.1 Das System in einem Absatz

immoswiss ist ein **serverseitig gerenderter Django-Monolith** für Schweizer Liegenschaftsverwaltungen (B2B-SaaS,
mandantenfähig). Es gibt kein separates Frontend: Django-Templates liefern fertiges HTML, eine eigene CSS-Schicht und
rund 2'400 Zeilen handgeschriebenes JavaScript ergänzen es. Hintergrundarbeit läuft nicht über eine Queue, sondern als
Management-Commands, die der Hoster zeitgesteuert startet. Die Datenbank ist PostgreSQL im Betrieb und SQLite in der
lokalen Entwicklung und im schnellen CI-Job.

### 1.2 Die Apps

| App | Rolle | Modelle (Auswahl) |
|---|---|---|
| `benutzer` | Benutzermodell (`AUTH_USER_MODEL`) | `Benutzer` |
| `crm` | Mandant und Personen | `Organisation` (der Tenant), `Mitgliedschaft`, `Eigentuemer`, `Mieter`, `Handwerker`, `Vorlage`, `Kommunikation` |
| `portfolio` | Bestand | `Liegenschaft`, `Einheit`, `Sollmietzins`, `Verteilschluessel`, `Zaehler`, `Geraet`, `Schluessel`, `Wartungsfrist` |
| `rentals` | Mietverhältnis | `Mietvertrag`, `VertragMietzins`, `MietzinsAnpassung`, `Kuendigung`, `Abnahmeprotokoll`, `Leerstand` |
| `finance` | Buchhaltung | `Buchungskonto`, `Buchung`, `DebitorenRechnung`, `Zahlungseingang`, `Mahnung`, `KreditorenRechnung`, `AbrechnungsPeriode`, `Jahresabschluss`, `Bankbewegung`, `Hypothek` |
| `tickets` | Schäden | `SchadenMeldung`, `HandwerkerAuftrag`, `Versicherungsfall`, `EingegangeneMail` |
| `mietprozess` | Bewerbungen | `Mietbewerbung` |
| `faelle` | Fallmaschine und Arbeitsvorrat | `Fallart`, `SchrittVorlage`, `Fall`, `Fallschritt`, `Zeiteintrag` |
| `stweg` | Stockwerkeigentum | Versammlung, Abstimmung, Budget, Abrechnung, Inkasso (rund 30 Modelle) |
| `abo` | Abonnement der Plattform | `Abonnement`, `AboRechnung`, `Kundenstamm` |
| `core` | Die Zentrale | Views, Dienste, Middleware, Rechte, Audit-Log, `ApiToken`, `Aenderungsanfrage`, `Pendenz` |

`core` ist mit Abstand die grösste App (rund 172'000 Zeilen Python inklusive Tests). Sie hält **85 Viewmodule**
unter `core/views/fw/`, **133 Dienste** unter `core/services/` und 318 Testdateien. Die Fachapps halten fast nur
Modelle; die Logik dazu liegt in `core`. Das ist historisch gewachsen (alles war einmal `core`) und zeigt sich bis
heute in Tabellennamen: `crm.Mieter` liegt in `core_mieter`, `crm.Organisation` in `core_verwaltung`.

### 1.3 Datenmodell im Kern

```
Organisation (Tenant) ── Mitgliedschaft ── Benutzer (Rolle über Django-Gruppen)
   │      └── Abonnement (Stufe, Module, Zustand)
   │
   ├── Eigentuemer ──┐
   │                 ├── Liegenschaft ── Einheit ── Mietvertrag ── VertragMietzins / MietzinsAnpassung
   │                 │        │             │            ├── Kuendigung, Abnahmeprotokoll
   │                 │        │             │            └── DebitorenRechnung ── Zahlungseingang ── Mahnung
   │                 │        │             ├── Sollmietzins, Leerstand, Mietbewerbung
   │                 │        │             └── Zaehler ── ZaehlerStand
   │                 │        ├── AbrechnungsPeriode ── NebenkostenBeleg
   │                 │        ├── SchadenMeldung ── HandwerkerAuftrag, Versicherungsfall
   │                 │        ├── KreditorenRechnung ── KreditorenZahlung
   │                 │        └── Anlage, Hypothek, Erneuerungsfonds, Jahresabschluss
   │                 └── EigentuemerAuszahlung
   ├── Buchungskonto ── Buchung (Soll/Haben, unveränderbar)
   ├── Fallart ── SchrittVorlage;  Fall ── Fallschritt   (hängt per GenericForeignKey an beliebigen Objekten)
   └── AktivitaetsLog (Hash-Kette), ApiToken, Aenderungsanfrage, Pendenz
```

Zwei Bauformen tragen den Mandantenbezug:

- **Direkt:** Modelle mit eigener `organisation`-Spalte und `TenantManager`.
- **Abgeleitet (`OrganisationAusKette`, `core/organisation_kette.py`):** Modelle unterhalb der Liegenschaft tragen eine
  denormalisierte `organisation`-Spalte, die `save()` aus dem Elternobjekt füllt. Der Aufrufer gibt sie nie selbst an.

### 1.4 Weg einer Anfrage

Die Reihenfolge der Middleware ist die eigentliche Architektur. Jede Schicht setzt voraus, was die vorherige geleistet hat:

```
Browser
  │
  ▼
SecurityMiddleware
WartungsMiddleware            Schema passt nicht zum Code → Wartungsseite, nichts dahinter läuft
NulBytesMiddleware            PostgreSQL verträgt kein NUL
GZip → Session → Common → CSRF → Authentication
OrganisationMiddleware        setzt den Mandantenkontext (ContextVar) aus der Mitgliedschaft
ZweiFaktorPflichtMiddleware   erzwingt die Einrichtung des zweiten Faktors je Rolle
AboMiddleware                 sperrt Module ausserhalb der Stufe; Lesemodus bei Zahlungsverzug
CSP (Nonce je Anfrage)        style-src und script-src ohne 'unsafe-inline', Modus `enforce`
  │
  ▼
View (core/views/fw/*.py)     @rolle_erforderlich(...)  → Rollenprüfung
  │                           _global_filter(request)   → Liegenschaftsfilter der Seite
  ▼
Dienst (core/services/*.py)   Fachlogik, Buchungen, PDF, Briefe
  │
  ▼
ORM über TenantManager        ohne Kontext: OrganisationsFehler statt «alles»
  │
  ▼
PostgreSQL                    Trigger schützen Buchungen und das Audit-Log
```

Drei Eigenschaften davon sind tragend:

1. **Fehler statt Leck.** `Model.objects` wirft ohne gesetzte Organisation `OrganisationsFehler`. Wer bewusst über alle
   Mandanten lesen muss, schreibt `Model.alle_organisationen`. Das Wort ist greifbar: 255 Stellen im Produktivcode,
   jede davon ein bewusst markierter Systempfad.
2. **Kontext ausserhalb von Requests ist Handarbeit.** Commands, Signale und die Shell haben keine Middleware und
   müssen `with organisation_kontext(org):` selbst setzen.
3. **Rechte sind dreistufig und unabhängig:** Mandant (wessen Daten), Rolle (was jemand darf, `core/auth.py`), Abo
   (was die Verwaltung gebucht hat, `core/funktionen.py`). Eine neue Funktion muss alle drei Fragen beantworten.

### 1.5 Oberflächen

| Pfad | Publikum | Bemerkung |
|---|---|---|
| `/neu/…` | Team der Verwaltung | Hauptoberfläche, 400 der 494 Routen |
| `/mieter/…`, `/portal/…` | Mieter, Eigentümer, Stockwerkeigentümer | Portal-Konten ohne Mitgliedschaft; Organisation aus dem Datensatz |
| `/auftrag/…`, `/direkt/…`, `/bewerben/…`, `/schaden/…` | Handwerker, Bewerber, Melder | Token-Links ohne Anmeldung |
| `/betreiber/…` | Plattformbetreiber | Kundenliste, Abo-Verwaltung, CSP-Meldungen |
| `/api/…` | Maschinen | django-ninja: Bewerbungsformular, DocuSeal-Webhook, lesende Finanz-API `/api/v1` mit API-Schlüssel |

Alle 494 Routen stehen in **einer** Datei (`swiss_immo/urls.py`); nur `stweg` hat eigene URL-Module.

### 1.6 Frontend-Schicht

- **Stil:** Eine eigene Komponentenschicht in `core/templates/fw/_schicht.html` (3'498 Zeilen), aus der
  `manage.py schicht_bauen` die ausgelieferte `static/css/schicht.css` erzeugt. Design-Tokens `--ds-*`, Hell und
  Dunkel. Daneben ein gebautes Tailwind für Altbestand.
- **Verhalten:** Kein Framework. `fw-aktionen.js` ersetzt Inline-Handler durch `data-*`-Attribute (deklarativ),
  `fw-bausteine.js` (Assistenten, Schubladen), `fw-omnisearch.js`, `fw-stil.js` (Laufzeit-Masse über ein
  konstruiertes Stylesheet, weil die CSP Inline-Stile verbietet).
- **Rahmen:** `fw/base.html` (837 Zeilen) mit mehreren Inline-Skripten unter Nonce. 46 Vorlagen tragen eigene
  Inline-Skripte.
- **Sprache:** de, fr, it, en über gettext; vier `.po`-Dateien, ein Wächtertest verlangt jeden ausgezeichneten Text
  im Katalog.

### 1.7 Hintergrundarbeit

Kein Celery, kein Redis. Geplante Läufe sind Management-Commands (`taeglicher_lauf`, `monatslauf`, `mahnlauf`,
`jahresabschluss_lauf`, `fetch_plattform_eingang`, `log_kette_anker`, `abo_abrechnung`), ausgelöst über die Scheduled
Tasks des Hosters. Die Knöpfe in der Oberfläche rufen dieselben Dienste auf (`core/services/automation.py`). Alle
Läufe sind idempotent angelegt. Das Ausrollen selbst ist ebenfalls ein Dauerläufer (`deploy.sh --dauerlauf`), der den
Zweig holt, migriert und die Web-App neu lädt.

### 1.8 Geld und Nachvollziehbarkeit

- **Doppelte Buchhaltung** über `finance/booking.py` (`buche`, `storniere_buchung`). Buchungen sind unveränderbar:
  Manager-Schutz in Django, dazu PostgreSQL-Trigger (`finance/db_schutz.py`), die Löschen und inhaltliche Änderungen
  abweisen und die Periodensperre durchsetzen. Korrektur heisst Storno.
- **Sperrregel** (`docs/GELDPFADE.md`): erst sperren (`select_for_update` oder `sperre_organisation`), dann prüfen,
  dann buchen. Vier-Augen-Freigabe für Zahlungen und Auszahlungen.
- **Audit-Log** (`AktivitaetsLog`) als Hash-Kette je Organisation (`core/log_kette.py`) mit täglichem Ankerpunkt
  ausserhalb der Datenbank.
- **Verschlüsselung im Feld** (Fernet) für AHV-Nummern und Postfachzugänge (`core/verschluesselt.py`).

---

## 2. Abhängigkeiten und Tech-Stack

### 2.1 Laufzeit

| Bereich | Technik |
|---|---|
| Framework | Django 5.2 (LTS), django-ninja 1.7 (drei Router), django-ckeditor 6.7 |
| Datenbank | PostgreSQL über psycopg 3 im Betrieb; SQLite (WAL) lokal und im schnellen Testjob |
| Cache | `FileBasedCache` in einem gemeinsamen Verzeichnis (Drosselung, Login-Sperren, LIK-Live-Wert) |
| PDF | xhtml2pdf und reportlab (Erzeugung), pypdf und pdfrw (amtliche Formulare befüllen), pdfplumber und pdfminer (Lesen), pyHanko (Signatur) |
| QR-Rechnung | segno, qrcodegen, zxing-cpp (Lesen), python-stdnum (IBAN, Referenzen) |
| Dokumente | python-docx (Vorlagen), Pillow, pdf2image |
| Krypto | cryptography (Fernet, Sicherungen), eigene TOTP-Umsetzung nach RFC 6238 |
| Frontend-Bau | Tailwind (Node, nur zur Bauzeit), eigenes `schicht_bauen` |
| Tests | Django-Testrunner (`MandantenTestRunner`), Playwright für 59 End-to-End-Dateien |
| Qualität | Ruff, pip-audit mit begründeter Ausnahmeliste, `check --deploy` in der CI |

### 2.2 Externe Schnittstellen

| Dienst | Zweck | Stelle | Ausfallverhalten |
|---|---|---|---|
| SMTP | Versand von E-Mails | `core/utils/email_service.py` | Versandfehler werden protokolliert |
| Brevo (Webhook für eingehende Post, API für Anhänge) | Antworten auf Ticket-Mails, einer von zwei Eingangskanälen | `core/views/webhooks.py`, `core/services/plattform_postfach.py` | Webhook mit Geheimnis geprüft |
| IMAP (Plattform-Postfach, eigene Postfächer der Verwaltung) | Antworten auf Tickets, Rechnungseingang | `core/services/plattform_postfach.py`, `postfach_abruf.py`, `rechnungseingang.py` | Lauf meldet und endet |
| DocuSeal | Elektronische Unterschrift | `core/services/docuseal_service.py`, `core/views/docuseal.py` | Webhook mit Geheimnis geprüft |
| Groq | Belegerkennung (Text und Bild) | `finance/utils.py` | ohne Schlüssel oder bei Ausfall nur der Regex-Pfad |
| geo.admin.ch, madd.bfs.admin.ch | Adressen und Gebäudedaten (EGID) | `portfolio/services.py` | optional |
| hev-schweiz.ch, bwo.admin.ch | LIK-Stand, Referenzzinssatz | `core/services/lik.py`, `core/utils/market_data.py` | Rückfall auf die Tabelle im Code |
| Banken (Dateien, keine API) | camt.053/054 einlesen, pain.001 erzeugen | `core/views/fw/bankabgleich.py`, `core/services/pain001.py` | – |

Konfiguration ausschliesslich über Umgebungsvariablen (`.env`): rund 45 Schlüssel, darunter `SECRET_KEY`, `DB_*`,
`BREVO_*`, `DOCUSEAL_*`, `GROQ_*`, `IMAP_SCHLUESSEL`, `PLATTFORM_IMAP_*`, `ABO_STELLER_*`, `CSP_MODUS`,
`LIK_LIVE_ABRUF`.

### 2.3 Betrieb

PythonAnywhere, ein Rechner, WSGI. CI auf GitHub Actions mit fünf Jobs: `lint`, `pip-audit`, `test` (SQLite),
`test-postgres`, `e2e`; dazu ein geplanter Job `wartung`, der die Aktualität der LIK-Tabelle prüft. Ein grüner Lauf
dauert rund 20 Minuten.

---

## 3. Risiken und Unbekannte

Geordnet nach dem Schaden, den sie bei neuer Entwicklung anrichten können.

### 3.1 Hoch

**R1 – Mandantenkontext ausserhalb von Requests.**
Die Isolation hängt an einer ContextVar. Jeder Pfad ohne Middleware (Command, Signal, Webhook, künftiger Worker) muss
den Kontext selbst setzen. Die sichere Seite ist eingebaut (ohne Kontext wirft der Manager), die gefährliche Seite ist
`alle_organisationen`: Wer es in einer Schleife über Organisationen verwendet und danach ohne Filter weiterliest,
mischt Mandanten. Mit 255 Stellen ist das der grösste Prüfaufwand je Änderung. Die Wächtertests
(`test_isolation*.py`, `test_isolation_abdeckung.py`) fangen neue Routen und Modelle ab, aber keinen falsch gefilterten
Systemlauf.

**R2 – `update()` und `bulk_create()` umgehen `save()`.**
`OrganisationAusKette` füllt die Organisation in `save()`. Massenoperationen gehen daran vorbei, ebenso an Signalen
und am Diff des Audit-Logs. Der Code dokumentiert das selbst als «echte Lücke». Wer einen Import oder eine
Massenänderung baut, muss die Organisation ausdrücklich setzen.

**R3 – SQLite und PostgreSQL verhalten sich an den heiklen Stellen verschieden.**
Zeilensperren, Advisory Locks und die Trigger auf Buchungen und Audit-Log gibt es nur auf PostgreSQL. Lokal und im
schnellen Testjob läuft SQLite: Ein Wettlauf beim Buchen oder ein Verstoss gegen die Unveränderbarkeit fällt dort
nicht auf. Tests für Parallelität sind als `NUR_POSTGRES` markiert und laufen nur im Job `test-postgres`. Für
Geldpfade zählt deshalb allein dieser Job.

**R4 – Fachwerte im Code, die veralten.**
Die LIK-Tabelle (`core/services/lik.py`), das Formularpflicht-Register, die Feiertage der Fristenrechnung und der
Standard-Kontenplan sind Python-Konstanten. Die LIK-Tabelle endet im Monat 09/2026. Der Live-Abruf liest eine HTML-Seite des HEV und
sucht dort «2020 = 100»; das BFS hat auf «Dezember 2025 = 100» umbasiert, einen geprüften Verkettungsfaktor gibt es
im Code nicht. **Unbekannt:** ob der Abruf im Betrieb noch Werte liefert, und wie bestehende Verträge mit alter Basis
nach der Umbasierung gerechnet werden sollen. Das ist eine fachliche Entscheidung, keine technische.

**R5 – Hintergrundarbeit ohne Queue.**
Lange Arbeiten (Serienbrief, Mahnlauf, Belegerkennung über Groq, PDF-Stapel) laufen entweder im Request oder im
nächsten geplanten Lauf. Im Request droht das Zeitlimit des Hosters; ein abgebrochener Lauf hat keinen Wiederanlauf
ausser der Idempotenz des Ganzen. Es gibt keinen Ort, an dem ein Benutzer den Stand einer laufenden Arbeit sieht.
Jede neue Funktion mit mehr als wenigen Sekunden Laufzeit stösst an diese Grenze.

### 3.2 Mittel

**R6 – `core` als Schwerpunkt.**
85 Viewmodule, 133 Dienste und 494 Routen in einer URL-Datei. Die Zerlegung der früheren Riesendatei ist erledigt,
aber die Abhängigkeiten laufen weiter kreuz und quer; viele Importe stehen bewusst innerhalb von Funktionen, um
Zyklen zu umgehen (`_basis.py` warnt ausdrücklich davor, sie hochzuziehen). Folge: Ein Importfehler zeigt sich erst
zur Laufzeit im betroffenen Pfad, nicht beim Start.

**R7 – 386 Stellen mit `except Exception`.**
Viele sind begründet (ein Hinweis darf die Startseite nicht stören, ein Mailfehler nicht die Buchung). Die Kehrseite:
Ausfälle externer Dienste bleiben still. Der LIK-Abruf gibt bei jedem Fehler `None` zurück, ohne den Grund
festzuhalten; genau so ist die ausgefallene Nachführung entstanden, ohne dass es jemand bemerkt hat.

**R8 – Zustand im Frontend ist dezentral.**
Kein Framework, dafür `data-*`-Attribute, mehrere Inline-Skripte in `base.html` und 46 Vorlagen mit eigenem Skript.
Unter der strengen CSP ist jedes `style="…"`, jeder Inline-Handler und jeder per JavaScript gesetzte Inline-Stil ein
Verstoss, der in Chromium oft nicht auffällt und in Safari gemeldet wird. Die Wächter (`test_csp.py`,
`test_stilschuld.py`, der Playwright-Sweep `csp-stile.spec.ts`) decken Vorlagen ab, dynamisch erzeugtes Markup nur
auf den durchlaufenen Seiten. In `base.html`, `fw-bausteine.js` und `fw-omnisearch.js` stehen noch einzelne
`el.style`-Zuweisungen in ereignisgesteuerten Pfaden.

**R9 – Zwei Stilquellen und ein Bauschritt.**
`_schicht.html` ist die Quelle, `schicht.css` das Erzeugnis; dazu ein gebautes Tailwind. Wer die Quelle ändert und
`schicht_bauen` vergisst, bekommt lokal ein anderes Bild als ausgeliefert. Ein Test fängt die Abweichung, kostet aber
einen CI-Durchlauf.

**R10 – Wächtertests mit festen Zählständen.**
Mehrere Tests halten Zahlen fest (Stilschuld je Vorlage, Abfragen je Seite, Ausnahmelisten der Isolation,
Befehlslisten des Abos). Sie verhindern Rückschritte zuverlässig, schlagen aber bei fast jeder grösseren Änderung
an und müssen bewusst nachgeführt werden. Wer die Zahl nur anhebt, ohne zu verstehen warum, entwertet den Wächter.

**R11 – Portal-Konten haben keine Mitgliedschaft.**
Die Organisation eines Mieters oder Eigentümers ergibt sich aus seinem Datensatz (Vertrag → Liegenschaft, sonst die
Organisation des Profils). Ein Portal-Konto hat genau ein Profil (`OneToOne`) und damit genau eine Organisation; ein
Konto bei zwei Verwaltungen ist nicht vorgesehen. Für Teammitglieder mit mehreren Mitgliedschaften gibt es die
Mandantenwahl in der Oberfläche (siehe 4.5, Punkt 5). Bleibt als Grenzfall: ein Portal-Konto ohne Vertrag, das die
Middleware über die Organisation des Profils auflöst. (Eine frühere Fassung dieses Absatzes behauptete fälschlich, die
Auswahl fehle.)

**R12 – Cache als Datei ohne atomares Zählen.**
`incr` ist nicht atomar und der Cache gilt nur auf einem Rechner (im Code selbst so vermerkt). Für die Drosselung
reicht das; als harte Sperre oder als Koordination zwischen Prozessen taugt es nicht. Ein zweiter Rechner bräuchte
Redis.

**R13 – Generische Verknüpfungen in der Fallmaschine.**
`Fall` hängt per `GenericForeignKey` an beliebigen Objekten. Das ist flexibel, aber es gibt keine referenzielle
Integrität über die Verknüpfung, und der Mandantenfilter greift nur am Fall selbst, nicht am Ziel; Löschen des Zielobjekts lässt den Fall verwaist zurück,
und Listen über viele Fälle laden die Ziele einzeln nach, wenn man nicht vorsorgt.

### 3.3 Niedrig, aber gut zu wissen

- **Altlasten im Namen:** Tabellen `core_*` für Modelle anderer Apps, `core_verwaltung` für `Organisation`. Rohes SQL
  und die Trigger hängen an diesen Namen.
- **`django.contrib.admin` ist installiert, aber ohne Oberfläche,** allein wegen eines Fremdschlüssels im Admin-Log.
- **Testdateien im Repository-Wurzelbereich von `core`** (`tests_perf.py`, `tests_perf2.py`, `tests_verify_perf.py`)
  neben dem Paket `core/tests/`: Herkunft und Aktualität sind unklar.
- **Python-Versionen:** Die CI läuft auf 3.11, die Entwicklungsumgebung auf 3.13, der Betrieb nach Angabe auf einem
  virtualenv `env313`. `docs/AUTOMATISIERUNG.md` nennt an einer Stelle noch 3.10 und den alten Zweig
  `claude/fairwalter-rebuild` als Deploy-Quelle. **Unbekannt:** welche Angabe im Betrieb gilt.
- **Dokumente veralten schnell:** `docs/` enthält 46 Dateien; mehrere beschreiben überholte Stände (ANALYSE,
  UEBERGABE-PHASE-4). Verlässlich sind der Code, die Tests und die Skills unter `.claude/skills/`.

### 3.4 Offene fachliche Entscheide

Diese Punkte blockieren Funktionen und lassen sich nicht technisch entscheiden: Kautionszins, zweiter Faktor für
Eigentümer, kantonale Feiertage, Abacus-Export (braucht eine Beispieldatei), Typfeld im Jahresabschluss,
Row-Level-Security in PostgreSQL als zweite Isolationsschicht, VMWG Art. 13, Umgang mit der LIK-Umbasierung.

---

## 4. Leitlinien für Ergänzungen

### 4.1 Wo was hingehört

| Was | Ort | Regel |
|---|---|---|
| Modell | Fachapp (`rentals`, `finance`, …), nicht `core` | Mandantenbezug nach einer der beiden Bauformen; `objects = TenantManager()`, `alle_organisationen` daneben |
| Fachlogik | `core/services/<thema>.py` | Reine Funktionen mit ausdrücklichen Parametern; kein `request` |
| View | `core/views/fw/<thema>.py` | Dünn: Rechte prüfen, Dienst rufen, Vorlage füllen |
| Route | `swiss_immo/urls.py` unter `/neu/…` | Neue grosse Bereiche nach dem Muster von `stweg` in ein eigenes URL-Modul |
| Vorlage | `core/templates/fw/` | Erbt `fw/base.html`; nur Klassen der Schicht, keine Inline-Stile, keine Inline-Handler |
| Geplanter Lauf | `core/management/commands/` | Schleife über Organisationen mit `organisation_kontext`; idempotent; Eintrag ins Aktivitätslog |
| Endpunkt | django-ninja-Router | Authentifizierung ausdrücklich; Mandant aus dem Token, nie aus dem Request |

### 4.2 Die fünf Fragen vor jeder neuen Funktion

1. **Wessen Daten?** Jede Abfrage läuft über `objects`. IDs aus Formularen und URLs werden immer über den gefilterten
   Manager geholt (`get_object_or_404(Modell.objects, pk=…)`), nie über `alle_organisationen`.
2. **Wer darf?** Rollenmenge aus `core/auth.py` wählen und mit `@rolle_erforderlich` setzen. Lesende und schreibende
   Rollen getrennt denken (Revision und Lesezugriff schreiben nie).
3. **Wer hat es gebucht?** Gehört die Funktion zu einer Abostufe, bekommt sie einen Schlüssel in
   `core/funktionen.py` und eine Pfadzuordnung in `abo/zugang.py`. Der Lesemodus bei Zahlungsverzug muss sie sperren,
   wenn sie schreibt.
4. **Bewegt sie Geld oder einen Status?** Dann gilt `docs/GELDPFADE.md`: sperren, danach prüfen, dann buchen, alles in
   einer Transaktion; Buchungen nur über `finance.booking.buche`; Korrektur nur als Storno; ein Test mit echten
   Threads auf PostgreSQL.
5. **Hinterlässt sie eine Spur?** Schreibende Aktionen rufen `log_aktion`. Sensible Felder stehen in
   `SENSIBLE_FELDER` und erscheinen nicht im Diff.

### 4.3 Regeln, die Wächter durchsetzen

Diese Tests schlagen an, wenn eine Regel verletzt wird. Sie sind keine Hindernisse, sondern die Checkliste:

- **Isolation:** Jede neue Route braucht einen Fremdzugriffstest oder einen begründeten Eintrag in den Ausnahmen;
  jedes neue Modell einen Mandantenbezug.
- **Rechte:** `test_rbac.py` prüft jede Route gegen jede Rolle.
- **CSP:** Kein `style="…"`, kein `onclick=…`; Verhalten über `data-*` und `fw-aktionen.js`, Masse über `data-breite`
  und ähnliche Attribute oder `fwStil(el, {...})`.
- **Übersetzung:** Jeder Text in `{% trans %}` oder `gettext`; danach Einträge in alle vier `.po` und `.mo` neu bauen.
  Ein fehlender Eintrag kostet einen roten CI-Lauf (zuletzt bei PR #256).
- **Beträge und Zeit:** Beträge nur über `core.utils.betrag.betrag_parsen`, nie ein eigener Parser; «heute» nur über
  `timezone.localdate()`; `date.today()` und `datetime.now()` weist ein Wächter in Tests ab.
- **Abfragen:** Die Hauptseiten haben Obergrenzen für die Zahl der Datenbankabfragen. Neue Spalten in Listen brauchen
  `select_related`, `prefetch_related` oder eine Annotation.
- **Stilschicht:** Nach jeder Änderung an `_schicht.html` `manage.py schicht_bauen` ausführen.
- **Migrationen:** `makemigrations --check` muss leer sein; Datenmigrationen über den Bestand arbeiten mit
  `alle_organisationen` und sind auf PostgreSQL zu prüfen.

### 4.4 Empfohlener Ablauf

1. **Bestand lesen, nicht raten.** Namen von Feldern, Routen und Rollen im Code nachschlagen. Die Skills
   `bekannte-fallen`, `mandantentrennung` und `schweizer-fachlogik` unter `.claude/skills/` halten die bereits
   gemachten Fehler fest.
2. **Dienst zuerst, mit Tests.** Die Fachlogik als Funktion in `core/services/`, geprüft ohne HTTP. Zu jedem neuen
   Test die Gegenprobe: Der Test muss rot werden, wenn man die Logik bricht.
3. **Dann View, Vorlage, Route.** Fremdzugriffstest und Rollentest gleich mitschreiben.
4. **Lokal die betroffenen Wächter laufen lassen** (Isolation, RBAC, CSP, Übersetzung, Stilschuld, Schicht), bevor
   gepusht wird. Der volle Lauf dauert in der CI rund 20 Minuten; ein vermeidbarer roter Lauf kostet diese Zeit.
5. **Ein PR je Arbeitspaket,** klein genug zum Durchlesen. Für Geldpfade zählt der Job `test-postgres`.
6. **Schweizer Fachwerte nie schätzen.** Zinssätze, Indexstände, Fristen, Formularpflichten und Referenzformate
   kommen aus einer benannten Quelle oder werden erfragt.

### 4.5 Was vor grösseren Ausbauten zuerst kommen sollte

Stand 14.11.2026. In dieser Reihenfolge, weil jeder Punkt den nächsten billiger macht:

1. **Ausfälle externer Dienste sichtbar machen — erledigt (PR 257).** `core.AbrufStatus` hält je Abruf (LIK,
   Referenzzins) letzten Erfolg, Grund und Fehlversuche in Folge; ab 3 Fehlversuchen oder 7 Tagen ohne Erfolg steht
   ein Hinweis auf der Betreiber-Startseite. Offen: IMAP, Brevo und Groq melden noch nicht in diese Tabelle.
2. **Fachtabellen aus dem Code in die Datenbank — für den LIK erledigt (PR 258), sonst bewusst nicht.** Der
   tägliche Lauf holt fehlende Monatswerte beim HEV und speichert sie selbst (Entscheid des Betreibers vom
   14.11.2026, mit Abgleich und Schranken); die Seite «LIK-Werte» (`/betreiber/lik/`) bleibt als Notbehelf. Ein
   Nachtrag gewinnt gegen den Code. Der Referenzzinssatz steht ohnehin je Organisation in der Datenbank. Das Formularpflicht-Register bleibt im
   Code: Es ist ein kleiner, rechtlich geprüfter Text mit einem jährlichen Update und einer Pflege-Erinnerung; eine
   Datenbankpflege brächte dort mehr Risiko als Nutzen. Die kantonalen Feiertage warten auf den fachlichen Entscheid
   (siehe 3.4).
3. **Auftragstabelle für lange Arbeiten — Grundlage erledigt (PR 259).** `core.Auftrag`, `core/services/auftraege.py`,
   `manage.py auftraege_abarbeiten` und die Seite «Aufträge» (`/neu/auftraege/`). Die Sollstellung geht ab 150
   Verträgen in den Hintergrund, aber nur, wenn der Läufer sich meldet (`auftraege.laeufer_aktiv`); sonst läuft sie
   sofort wie bisher. Dasselbe Muster gilt für jede weitere Umstellung: nie in die Warteschlange, wenn niemand sie
   abholt. Mahnlauf, Serienbrief und Belegerkennung laufen noch wie bisher. Der Läufer muss einmal als Always-on-Task eingerichtet werden.
4. **URL-Module je Bereich — erledigt (PR 260).** `swiss_immo/urls.py` ist in sechs Module aufgeteilt; Routen und
   Reihenfolge sind nachweislich unverändert (geflachter Routenbaum vorher und nachher gleich, 594 Einträge).
5. **Auswahl der Organisation bei mehreren Mitgliedschaften — gab es bereits.** Die Mandantenwahl im Kopf und im
   Profilmenü schreibt `aktive_organisation_id` in die Sitzung (`einstellungen_aktionen.py`, Tests
   `test_mandant_wechsel` und `test_profilmenue_mandant`); die Middleware ehrt den Wert nur bei echter Mitgliedschaft.
   Die frühere Aussage in R11 war falsch. Ein Portal-Konto hat genau ein Profil (`OneToOne`) und damit genau eine
   Organisation.
6. **Row-Level-Security in PostgreSQL** als zweite Schicht unter dem `TenantManager`, sobald die Systemläufe ihren
   Kontext sauber setzen (der Auftragsläufer tut es seit PR 259 je Auftrag). Das ist ein eigener, bewusst zu
   entscheidender Schritt und noch offen.

### 4.6 Was man nicht tun sollte

- Einen zweiten Weg zu Daten bauen (zweite Oberfläche, zweite API mit Schreibrechten, Admin mit Schreibzugriff). Jede
  Mandanten-, Rollen- und Abo-Regel müsste dort ein zweites Mal stimmen.
- Den Mandanten aus dem Request lesen (`?org=`, Header, Formularfeld).
- `alle_organisationen` in einer View verwenden. Es gehört in Systemläufe und in die Betreiber-Konsole.
- Buchungen ändern oder löschen, auch nicht in einer Datenmigration, ausser über die benannte, protokollierte
  Ausnahme.
- Einen Wächtertest abschalten oder seine Zahl anheben, um grün zu werden, ohne die Ursache zu verstehen.
- Ein Frontend-Framework für einen einzelnen Bildschirm einführen. Die Schicht aus `data-*`-Attributen trägt die
  vorhandenen Assistenten und Schubladen; ein zweites Zustandsmodell daneben wäre die teurere Schuld.
