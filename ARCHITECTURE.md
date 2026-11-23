# Architektur

Ist-Zustand der Anwendung. Diese Datei beschreibt, was im Code steht — keine Pläne, keine Geschichte.
Regeln für die Mitarbeit stehen in [CONTRIBUTING.md](CONTRIBUTING.md), Einstieg und Befehle in [README.md](README.md).

## 1. Überblick

immoswiss ist eine mandantenfähige Web-Anwendung für Schweizer Immobilienverwaltungen. Eine Installation bedient
viele Verwaltungen («Organisationen»); der Betreiber schaltet neue Kunden im Betreiber-Portal frei. Die Seiten werden
serverseitig gerendert (Django-Vorlagen), es gibt keine Einzelseiten-Anwendung.

| Baustein | Stand |
|---|---|
| Sprache, Rahmenwerk | Python 3.11 (CI), Django 5.2, django-ninja für die API |
| Datenbank | PostgreSQL in Produktion (`DB_ENGINE=postgres`), SQLite für Entwicklung und Tests |
| Oberfläche | Django-Vorlagen, Tailwind (nur zur Bauzeit), eigene Skripte unter `static/js/`, keine Fremdbibliothek im Browser |
| PDF, QR | xhtml2pdf, reportlab, pypdf, pdfplumber, segno, zxing-cpp |
| Hintergrundarbeit | eigene Auftragstabelle mit Läufer (`core/services/auftraege.py`); kein Celery, kein Redis |
| Cache | Datei-Cache (`core/cache_config.py`, `CACHE_VERZEICHNIS`) |
| Sprachen | Deutsch, Französisch, Italienisch, Englisch (`locale/`) |
| Betrieb | PythonAnywhere, `deploy.sh` |
| Prüfung | Django-Tests, Playwright (E2E), Ruff, pip-audit (`.github/workflows/ci.yml`) |

## 2. Aufbau

### Apps

| App | Zuständigkeit |
|---|---|
| `benutzer` | Benutzermodell (`AUTH_USER_MODEL = 'benutzer.Benutzer'`) |
| `core` | Ansichten (`core/views/fw/`), Dienste (`core/services/`), Middleware, Rechte, Management-Befehle, Vorlagen |
| `crm` | Organisation, Mitgliedschaft (Rolle je Verwaltung), Mieter, Eigentümer (Mandate), Handwerker |
| `portfolio` | Liegenschaften, Einheiten, Zähler, Ausstattung, Geräte, Dokumente der Objekte |
| `rentals` | Mietverträge, Mietzinsanpassungen, Abnahmen, Dokumente der Verträge |
| `finance` | Buchhaltung, Debitoren, Kreditoren, Zahlungen, Nebenkosten, Periodensperre |
| `tickets` | Schadenmeldungen, Handwerker-Aufträge, Direktkanal Mieter–Handwerker |
| `mietprozess` | Bewerbungen und Vermietung |
| `faelle` | Fälle, Läufe (Sollstellung, Mahnlauf, …), Termine, Zulauf |
| `stweg` | Stockwerkeigentum: Beschlüsse, Budget, Fonds, Abstimmung, Inkasso |
| `abo` | Abonnement, Abrechnung der Plattform, Sperren nach Stufe und Zahlungsstand |

### Adressen

- `swiss_immo/urls.py` bindet `urls_neu_bestand.py`, `urls_neu_betrieb.py`, `urls_neu_mietprozess.py`,
  `urls_neu_verwaltung.py`, `urls_portale.py` und `urls_betreiber.py` ein.
- Verwaltung: `/neu/…`. Mieterportal: `/mieter/…`. Eigentümerportal: `/portal/…`. Betreiber: `/betreiber/…`.
- Öffentlich ohne Anmeldung: `/schaden/melden/`, `/aushang/<token>/`, `/bewerben/<id>/`, `/auftrag/<token>/`,
  `/direkt/<signiert>/`, `/fristen.ics?token=…`, `/healthz/`, `/version/`.
- API (django-ninja): `/api/rentals`, `/api/mietprozess`, `/api/v1` (lesende Finanz-API mit Schlüssel,
  `core/finanz_api.py`). Webhooks: `/docuseal/webhook/`, `/webhooks/brevo/inbound/`.

### Middleware (Reihenfolge aus `settings.py`)

Security → `WartungsMiddleware` → `NulBytesMiddleware` → GZip → Session → Common → CSRF → Auth →
`AngemeldetNichtZwischenspeichern` → Locale → `OrganisationMiddleware` → `ZweiFaktorPflichtMiddleware` →
`AboMiddleware` → Messages → XFrame → `CspMiddleware` → `EingabeFehlerMiddleware` → `FeldnamenMiddleware`.

### Navigation

- Eine Liste ist die Quelle: `core/navigation.py` (`nav_gruppen()`), sieben Bereiche — Heute, Schäden, Liegenschaften, Kontakte,
  Monatsabschluss, Finanzen, Berichte (Namen wie im UI-Zielbild; die Schlüssel `betrieb`, `akten`, `laeufe` bleiben, weil Adressen,
  Tastenkürzel und Zähler an ihnen hängen). «Schäden» führt neben den Schäden die Aufträge, Anfragen, Vermietung, Ablesung und Ersatz,
  «Liegenschaften» die Register der Objekte (Mandate, Liegenschaften, Objekte, Mietverhältnisse, Stockwerkeigentum, Dokumente),
  «Kontakte» (Schlüssel `kontakte`, Taste «K») Personen und Dienstleister — bis 20.11.2026 standen sie unter «Liegenschaften», der Name passte
  nicht mehr (Betreiber-Entscheid). «Monatsabschluss» führt die Läufe. Heute,
  Monatsabschluss, Finanzen und Berichte beginnen mit «Übersicht», Schäden und Liegenschaften mit ihrer ersten Seite. Die erste Stufe
  der Brotkrume trägt denselben Namen (`fw-krumen`). Einstellungen stehen im Fuss der Schiene, nicht in den Bereichen
  (`EINSTELLUNGEN_ZIELE`).
- Der Context-Processor `fw_navigation` liefert die Liste an `fw/base.html`, gefiltert nach Rolle (`erlaubt`) und
  Abo-Stufe (`gesperrt`). Jede Seite meldet ihren `nav`-Schlüssel; `keys` je Eintrag verbindet ihn mit dem Punkt.
  «Vermietung» ist ein Punkt für vier Seiten (Mieterwechsel, Leerstand, Vermarktung, Bewerbungen).
- Darstellung: Die Bereiche stehen in der Schiene links (`#fwSchiene`): ab 1024 px 88 px mit Beschriftung, von 641 bis
  1023 px 56 px schmal nur mit Symbolen (Beschriftung im Tooltip). Am Telefon (bis 640 px) ist dieselbe Schiene eine
  Schublade von links mit Beschriftung und roten Zahlen; der Menüknopf in der Kopfzeile (`#fwMenueKnopf`, Zahl = Summe der
  roten Zahlen) öffnet sie, der Inhalt hat die volle Breite. Dort öffnet ein Bereich sein Feld über der Schublade
  («Bereiche» führt zurück). Ein Tipp bzw. Klick klappt das Feld mit den Seiten des
  Bereichs auf (`#fwFach`, `static/js/fw-schiene.js`), ein Klick daneben, Esc oder die Wahl einer Seite schliesst es.
  **Handy-Tableiste** (`#fwTabbar`, Mix-Entwurf 20.11.2026): Nur bis 640 px steht unten eine Leiste mit Heute, Schäden, «Neu»,
  Finanzen und «Mehr»; «Mehr» öffnet dieselbe Schublade mit allen Bereichen. Sie liest dieselbe Quelle (`fw_nav_gruppen`) und ist eine
  zweite Tür zu denselben Zielen — nichts entfällt, fehlt der Rolle ein Bereich, fehlt er auch dort. Hauswartung und Portal-Rollen
  bekommen sie nicht (`fw_kopf_reduziert`). Test: `e2e/tests/tableiste.spec.ts`.
  **Breite Navigation** (Mix-Entwurf, 21.11.2026): Ab 1280 px ist die Schiene Vorgabe eine Spalte (248 px) mit Marke, Beschriftung und dem
  **Baum** der Seiten des Bereichs, in dem man steht (`html.fw-breit`; die Abschnitte des Seitenfeldes `#fwFach` ziehen per Skript
  unter ihren Bereich um — nichts wird doppelt geführt). Ein Klick auf einen Bereich führt auf dessen Seite; «G» dann H/B/A/K/L/F/R
  springt dorthin, 1–9 wählt die Seite im Baum. Der Knopf «Schmal» im Fuss (`[data-schiene-fest]`) stellt Symbolschiene und Seitenfeld
  wieder her; der Wunsch liegt im Browser (`localStorage` `fwSchieneBreit`). Unter 1280 px und am Telefon ändert sich nichts.
  Test: `e2e/tests/schiene-anheften.spec.ts` (breit), `schiene.spec.ts` (schmal).
  **Handy-Navigation als Blatt (22.11.2026, nach Mockup):** Bis 640 px ist die Schiene kein Einschub von links mehr, sondern ein Blatt
  von unten über die ganze Breite (Griff, ohne Marke). Oben steht der Arbeitsbereich (`#fwArbeit`, dieselbe Wahl von Verwaltung und
  Bestand wie in der breiten Navigation, das Feld liegt über dem Blatt), darunter die Bereiche. Ein Tipp auf einen Bereich klappt seine
  Seiten IM Blatt auf (`html.fw-blatt`; die Abschnitte des Feldes ziehen wie in der breiten Navigation unter ihren Bereich), offen ist
  zuerst der Bereich, in dem man steht. Das frühere Feld über der Schublade und «Bereiche» (zurück) gibt es am Telefon nicht mehr;
  alle Bereiche und Seiten bleiben erreichbar. `fwMenuEinpassen` (`fw-rahmen.js`) lässt die Schiene als linke Grenze weg, wenn sie
  die ganze Breite einnimmt. Test: `e2e/tests/schiene.spec.ts` («Schublade am Telefon»), `omnisearch.spec.ts`, `tableiste.spec.ts`.
  **Rahmen, Modul 1 (22.11.2026):** In der breiten Navigation trägt die Spalte den Rahmen, die Kopfleiste gehört der Seite.
  Oben in der Spalte steht der **Arbeitsbereich** (`#fwArbeit`, `#fwArbeitPop`): Verwaltung und Bestand in einem Schalter, mit
  Suchfeld; die Wahl ist dieselbe wie bisher (`?lg=` bzw. POST `/neu/mandant/`). Darunter die Suchzeile (`#fwSchieneSuche`): sie und
  Strg+K öffnen die bestehende Omnisearch als mittige Palette. «Zuletzt geöffnet» steht in der Spalte, das Profil im Fuss
  (`.fw-schiene-profil`, öffnet `#fwProfil`). Die Kopfleiste zeigt nur Brotkrume (`.fw-krumen` zieht per Skript hinein), «Neu» und
  Mitteilungen. Die Taste `[` schaltet breit und schmal. In der schmalen Navigation und am Telefon bleibt die bisherige Kopfzeile
  (Bestand, Suchfeld, Werkzeuge) — deren Tests laufen ausdrücklich schmal (`fwSchieneBreit=0`).
  **Nichts geht verloren:** `core/tests/routen_baseline.txt` hält alle Adressen (mit Namen) vom 20.11.2026 fest;
  `test_routen_baseline` schlägt fehl, wenn eine fehlt oder ihren Namen wechselt. Neue Adressen dürfen dazukommen, eine Adresse darf
  nur mit Begründung in `ABSICHTLICH_ENTFERNT` stehen.
  Tastatur: G dann H/B/A/K/L/F/R/E öffnet den Bereich, 1–9 wählt die Seite. Hauswartung und Portal-Rollen bekommen keine
  Schiene (`fw_kopf_reduziert`); sie behalten die Marke in der Kopfzeile. Eine Bereichskapsel oder ein Menüband in der
  Kopfzeile gibt es nicht mehr (entfernt 18.11.2026).
  Bestandsfilter (`.fw-bestand`, globaler Filter `?lg=`): Am Telefon (bis 640 px) zeigt der Knopf bei gewähltem Bestand die
  Strasse gekürzt (`.fw-bestand-name`, höchstens 9,5 rem) statt nur eines Punktes; ohne Filter bleibt das Haus-Symbol.
  Die native Auswahl liegt weiter unsichtbar darüber. E2E: `e2e/tests/bestand-name-handy.spec.ts` (390 px, kein Überlauf).
- Rote Zahlen zeigen, wo etwas zu tun ist: an den Bereichen (`/neu/leistenzahlen/`: Heute, Monatsabschluss, Zulauf) und an den
  einzelnen Seiten im Feld (`punkte` derselben Antwort, `_punktzahlen` in `core/views/fw/arbeit.py`; Schlüssel = erster
  `keys`-Eintrag des Menüpunkts). Jede Zahl zählt dasselbe wie ihre Seite; eine Quelle, die ausfällt, fehlt und steht im
  Protokoll.
- Einstellungen: `einstellungen_gruppen()` in `core/navigation.py` ist die eine Liste (fünf Gruppen: Verwaltung, Team & Zugriff,
  Vorlagen & Regeln, Schnittstellen, Daten & Protokoll). Aus ihr kommen die Hub-Seite `/neu/einstellungen/`, das Feld der
  Schiene (Symbol «Einstellungen», Taste G dann E) und der Pfad «Einstellungen / Gruppe» auf jeder Einstellungsseite.
  Die Hub-Seite hat eine Live-Suche (Filter im Browser über `data-suche`, siehe CONTRIBUTING «Listen»); Gruppen ohne Treffer
  verschwinden, ohne Treffer erscheint «Keine Einstellung gefunden».
- «Zuletzt geöffnet» liegt im Browser, je Person und Verwaltung (`zuletztSchluessel` im Datenblock der Vorlage).

## 3. Mandantentrennung

Jede fachliche Zeile gehört genau einer Organisation. Die Trennung hat drei Schichten.

1. **Kontext und Manager** (`core/tenancy.py`). Die aktive Organisation steht in einer `ContextVar`. `Model.objects`
   ist ein `TenantManager`: Er filtert auf die aktive Organisation und wirft ohne Kontext einen `OrganisationsFehler`.
   Der benannte Umweg über alle Verwaltungen heisst `Model.alle_organisationen`. Helfer: `organisation_kontext`,
   `kontext_des_objekts` (für Einstiege ohne Anmeldung), `je_organisation` (für geplante Läufe, mit Fehlerisolation).
2. **Middleware** (`core/middleware_tenancy.py`). Die Organisation kommt aus der Mitgliedschaft des Benutzers, nie
   aus der Anfrage. Bei mehreren Mitgliedschaften gilt die in der Sitzung gewählte, sonst die älteste.
3. **Datenbank** (`core/rls.py`, Befehl `rls_einrichten`). Row Level Security für die Tabellen von `finance`, Stufen
   `aus`, `probe`, `scharf` über `RLS_MODUS`. In Tests immer `aus`.

Die Spalte `organisation` wird bei abhängigen Modellen aus dem Elternobjekt abgeleitet (`core/organisation_kette.py`).

## 4. Rollen und Rechte

Rollen hängen an der Mitgliedschaft je Organisation (`crm.Mitgliedschaft`), nicht an Django-Gruppen (`core/auth.py`).

| Rolle | Darf |
|---|---|
| Inhaber | alles, was das Team darf, dazu Benutzer und Abonnement |
| Verwalter | Verwaltung der Organisation, Läufe, Freigaben |
| Sachbearbeiter | Tagesgeschäft, schreibend |
| Lesezugriff | nur lesen |
| Buchhaltung | Finanzen (Debitoren, Kreditoren, Buchungen, Läufe) |
| Revision | Finanzen lesen |
| Hauswart | Schadenfälle seiner Liegenschaften |
| Eigentümer, Mieter | das jeweilige Portal |
| Betreiber | Betreiber-Portal (Superuser) |

- Ansichten tragen `@rolle_erforderlich(…)`. Vorlagen blenden Knöpfe über den Filter `darf` aus (`core/templatetags/rechte.py`).
- Die Rollen werden je Anfrage einmal gelesen (`rollen_der_anfrage`); eine Änderung an Mitgliedschaften verwirft den Merker.
- Zwei-Faktor-Anmeldung ist Pflicht für Inhaber, Verwalter, Buchhaltung und Revision (`ZWEIFAKTOR_ROLLENPFLICHT`).

## 5. Datenfluss der wichtigsten Abläufe

### Sollstellung und Mahnlauf
`monatslauf` bzw. der Knopf in der Oberfläche → `core/services/sollstellung_lauf.py` → `automation.run_sollstellung`.
`mahnlauf` bzw. Knopf → `core/services/mahnlauf_lauf.py` → `automation.run_mahnlauf`.
Ab der Schwelle (150 Verträge, 100 offene Rechnungen; Rundschreiben ab 30 Empfängern) entsteht **immer** ein
Hintergrundauftrag, nie eine Berechnung im Seitenaufruf.
Ein laufender Auftrag meldet ab dem Start und bei jedem Fortschritt ein Lebenszeichen (Cache) und erneuert damit auch den Puls des
Läufers («Läufer läuft nicht» erscheint nicht bei langen Aufträgen); nur ohne Lebenszeichen gilt er nach 30 Minuten als
abgestürzt und wird neu eingereiht. Beenden darf einen Auftrag nur der Lauf, der ihn gestartet hat.

### Hintergrundaufträge
`auftraege.anlegen` schreibt eine Zeile, `manage.py auftraege_abarbeiten` holt sie ab (im Mandantenkontext, mit
Sperre gegen doppelte Abholung). Ein Auftrag, der 30 Minuten «läuft», gilt als abgestürzt und wird bis zu dreimal
neu gestartet; die Funktionen müssen deshalb wiederholbar sein. Der Läufer meldet einen Puls im Cache; fehlt er,
warnt die Seite «Aufträge» und das Betreiber-Protokoll.

### Zahlungseingang
Bankauszug (camt.053/054 oder CSV) → `core/views/fw/bankabgleich.py`: Gutschriften werden über die QR-Referenz den
offenen Rechnungen zugeordnet und verbucht; Unzuordenbares wird geparkt (`core/services/zahlungszuordnung.py`).
Klärungsfälle (Durchlaufkonto 1190): Jede Zeile hat einen Knopf «Zuordnen», der den einen Dialog der Seite öffnet
(`fw/_zuordnen_dialog.html`, `static/js/fw-zuordnen.js`; Angaben je Zahlung als `zuordnen_daten`-JSON aus `fw_bankabgleich`).
Vier Wege, alle über die bestehenden Routen mit ihren Prüfungen: Mietzins zuordnen (`/neu/bankabgleich/zuordnen/`, die
vorgeschlagene Rechnung ist vorgewählt), Als Kaution erfassen (`…/zahlung/<id>/kaution/`, mit Rückfrage), Aufteilen (Assistent
`fw/zahlung_aufteilen.html`), Zurückweisen (`…/guthaben/rueckerstatten/`, mit Rückfrage). Nach dem Zuordnen bietet der Toast «Rückgängig».
Ohne JavaScript führt «Zuordnen / Aufteilen» direkt in den Assistenten.
Die Klärungszeile (`.fw-bzeile`, Mockup «Bankabgleich im Zielbild») trägt Farbbalken (rot ab `KLAERUNG_WARN_TAGE`), Name, Valuta, Alters- und
Vorschlags-Chip, grünen Betrag und den einen Knopf; Notiz zur Klärung und der Hinweis «Absender wird gemerkt» stehen im Dialog.
Der Assistent «Aufteilen» (`fw/zahlung_aufteilen.html`, Hooks `data-split`, `data-rest-wahl`, `data-teil` unverändert für
`static/js/fw-zahlungen.js`): Posten als Karten mit Betragsfeld und «alles zuteilen», Rest-Wahl als drei Karten, feste Summenkarte
(Zugeteilt/Rest, Balken, Buchen). Ab 1024 px Posten links, Zahlung und Summenkarte rechts; am Handy erst Posten, dann Angaben zur Zahlung.
Test: `e2e/tests/bankabgleich-zielbild.spec.ts` (390 und 1280 px, kein Überlauf).
Zahlungsausgang: `core/services/pain001.py` (Zahllauf, ab Freigabelimit mit zweiter Person).
Storno gehört an die Quelle: Eine Buchung, die zu einer Zahlung oder Rechnung gehört, wird im Journal nicht storniert
(`fw_buchung_stornieren` verweist auf Bankabgleich bzw. Rechnung), und «Import rückgängig» ist gesperrt, solange
verbuchte Belastungen am Auszug hängen — sonst stimmt das Nebenbuch nicht mehr, oder die Belastung wird beim erneuten
Import doppelt gebucht. Eine Belastung, die grösser ist als die offene Kreditorenrechnung, wird abgelehnt (nicht auf den
Rest gekürzt). Der Zahllauf nimmt auch teilbezahlte Rechnungen auf und überweist den offenen Rest. Die Kautionsauflösung gibt
das Sperrkonto in Höhe des bilanzierten Betrags frei. Eine MWST-Periode für den ganzen Bestand und eine je Liegenschaft schliessen sich aus
(`_mwst_bereits_verbucht`).

### Nebenkosten
Rechenkern `core/utils/billing.py` (`berechne_abrechnung`), Assistent `core/views/fw/nk_wizard.py`, PDF und Versand
in `core/services/nk_*.py`.

### «Häufig genutzt» (Berichte und Einstellungen)

Beide Seiten zeigen über der Liste eine **feste** Auswahl von drei Einträgen (kein lernendes Verfahren): Berichte «Mieterspiegel»,
«Debitoren-Altersstruktur», «MWST-Abrechnung»; Einstellungen «Benutzer & Rollen», «Zahlungsfreigabe», «Vorlagen». Die Ansichten
(`core/views/fw/berichte.py`, `einstellungen_aktionen.py`) wählen sie aus der bereits nach Rolle gefilterten Liste, die Rolle sieht also nie einen
Eintrag, den sie nicht öffnen darf. Der Block trägt `data-haeufig` (nicht `data-gruppe`/`data-zeile`) und wird während der Suche ausgeblendet
(`static/js/fw-rahmen.js`), damit kein Treffer doppelt erscheint. Die Ziellinie im Diagramm fehlt weiter: Ein Zielwert müsste der Betreiber festlegen.

### Anrede «Sie»

Alle Texte der Oberfläche siezen (Entscheidung vom 20.11.2026). Vorher mischte die Anwendung «du kannst», «Erfasse die IBAN» und «Sie». 86 Texte
wurden umgestellt, im Code und mit neuen Einträgen in den vier `.po`-Dateien (die alten Du-Einträge bleiben als ungenutzte Zeilen stehen,
weil Übersetzungen nur angehängt werden). Französisch und Italienisch sind formell («vous», «Lei»). Der Wächter `core/tests/test_sie_form.py`
sucht Du-Pronomen und Befehlsformen am Satzanfang in `fw/`-Vorlagen, Ansichten, Diensten und Hilfetexten; Kommentare zählen nicht. Der Satz
auf «Heute» heisst «N Vorgänge brauchen heute Ihre Aufmerksamkeit».

### Dunkelmodus nach Zielbild

Die Dunkelwerte folgen dem Prototyp: Hintergrund `#16171a`, Karte `#202227`, Fläche 2 `#2b2d33`, Tinte `#ecebe7`, Sekundärtext `#a0a3a9`, Linie `#33363c`
(vorher `#111113` / `#1a1b1e` / `#f1efec` / `#b9b6b0` / `#2c2d32`). Der Akzent bleibt Orange `#f08a55` (Betreiber-Entscheid), nicht das Blau des Prototyps.
Die Palettentabelle in `CONTRIBUTING.md` ist nachgezogen (`test_palette` vergleicht sie mit der Schicht); die Kontrastwächter laufen unverändert grün.
### Zielbild-Masse (UI-Abgleich vom 20.11.2026)

Gemessen an den berechneten Stilen des Prototyps (`mockups/immoswiss-ui-ziel.html`) und der App, bei 390 und 1280 px: Zeilen mit Titel 15 px und
Zweitzeile 14 px, Statuschips und Kapseln 14 px (Höhe 36 px am PC, 44 px am Handy), Zeilenknöpfe als Kapsel (36 / 44 px), Karten mit Radius 24 px,
Seitentitel auf Unterseiten 36 px (Handy 22 px; «Heute» bleibt gross). Die Werte stehen im Modul «Zielbild-Masse» von `_schicht.html`, der Titel
von 36 px ist als Anzeigegrösse im Wächter `test_schriftskala` erlaubt. Der vollständige Bericht liegt in der Konversation; offene Punkte sind die
Zeilendichte als Standard und die Ziellinie im Diagramm (beides Entscheidungen des Betreibers).

### Zeilen am Handy

Am Handy (bis 640 px) steht das Etikett (Status bei Schäden, Art bei «Heute») **neben** dem Titel statt darüber, wie im Prototyp; darunter folgen Zweitzeile,
«seit N Tagen» und der Knopf. Gemessen sank die Zeile bei Schäden von 182 auf 162 px, bei «Heute» von 142 auf 120 px (Prototyp: 86 / 105 px, ohne
Zweitzeile und ohne Freigabe-Chips, die die App fachlich braucht). Der Chip «Freigabe ausstehend …» bricht um, statt über den Kartenrand zu laufen; der Knopf
steht rechts. Regeln im Modul «Zeilen am Handy» von `_schicht.html`.

### Kopfzeile nach Zielbild

Am PC sind die Steuerelemente der Kopfzeile so hoch wie im Prototyp: Bestand-Pille 44 px (Symbolkreis 32 px), Suchfeld 36 px, Werkzeugknöpfe 36 px
(vorher 52 / 44 / 40 px). Das Suchfeld ist unterhalb von 1440 px etwas breiter (11,5 rem), damit «Suchen …» und das Kürzel nicht abgeschnitten werden.
Zeilenknöpfe heben sich beim Zeigen nicht mehr an (in dichten Listen sprang die Zeile), der aktive Eintrag der Schiene ist 500 statt 600 stark.

### Diagramm: Datenstand am Endpunkt

Der Endwert der Zahlungsquote nennt seinen Datenstand, wie im Prototyp: «66,7 % (Stand Bankimport 26.10.)». Das Datum ist der Importzeitpunkt des letzten
Kontoauszugs (`Kontoauszug.importiert_am`); ohne Auszug steht nur der Wert. Das Template-Tag `linien_diagramm` nimmt dafür den Parameter `stand`
(`core/templatetags/diagramm.py`, Test `core/tests/test_diagramm_stand.py`). Die gestrichelte Ziellinie des Prototyps (95 %) fehlt weiter: Ihr Zielwert muss der Betreiber festlegen.
Kartenköpfe haben jetzt `18 px 22 px 14 px` Innenabstand (vorher 20 / 24 px).

### Mix-Entwurf als Gestalt (21.11.2026)

Das freigegebene Mockup («Immoswiss Prototyp», `prototyp.html`) ist die Vorlage für die Darstellung aller Seiten. Umgesetzt wird
nur die Gestalt; Markup, Ziele und Funktionen bleiben (Wächter `test_routen_baseline`, `test_erreichbarkeit`).

- Schriften: Inter für die Oberfläche (`--ds-font`), Sora für Seitentitel und grosse Zahlen (`--ds-disp`), IBM Plex Mono für
  Kennungen — alle lokal in `static/fonts/` (OFL), keine fremden Hosts.
- Modul «Mix-Entwurf» am Ende von `fw/_schicht.html`: weisse Kopfleiste mit Linie, Titel 24 px Sora, Karten mit Rand statt Schatten,
  Tabellenkopf als Band, Knöpfe und Reiter als Pillen (aktiver Reiter dunkel), Hauptknöpfe in der Markenfarbe.
- «Heute»: Datum, Begrüssung und die Aufgaben als grosse Zahlen in einer dunklen Karte (`.fw-hero`, Tokens `--ds-hero*`, in beiden
  Modi dunkel); der Schwerpunkt steht darüber. Die Zahlen sind dieselben Links wie zuvor die Kapseln (`data-kachel`).
- Seiten (Mix B): Monatsabschluss als einzelne Schritt-Karten mit Nummer (CSS-Zähler), aktueller Schritt mit Markenrand, gesperrte
  blass; Kennzahlen (`.fw-kpi`) mit Etikett in Versalien und Zahl in Sora; Statuspunkte statt Balken in allen Zeilen am PC.
- Schmale Lesespalte (984 px, wie `.wrap` im Mockup) ab 1280 px für Seiten ohne Tabelle, Cockpit, Kachelraster, Kennzahlen,
  Zweispalter und Assistent (`:has()`-Regel im Modul «Mix-Entwurf»); Arbeitsflächen behalten die volle Breite.
- Handy (bis 640 px): weisse Kopfleiste mit Linie; Listenzeilen (`.fw-card > .fw-zeile`) als einzelne Karten mit Statuspunkt
  auf dem Seitengrund, wie im Mockup.
- Breite Navigation: «Einstellungen» bleibt unten ohne Baum (alle Punkte auf der Seite selbst); Versalien-Etiketten nur in den
  grossen Kennzahlkarten (`.fw-kpis.fw-gross`, Finanzen), nicht in den Statuskapseln.
- Tabellen: `min-w-max` und `whitespace-nowrap` (Tailwind) gelten in `table.fw-table` wieder; vorher brachen Namen in Kreditoren
  über mehrere Zeilen um. Breite Tabellen scrollen in `.fw-tablewrap` quer.
- Arbeitsvorrat auf «Heute» (`.fw-vz`) am PC wie die Mockup-Zeilen: Statuspunkt statt Balken, keine Trennlinien.
- **Akten, Modul 2 (22.11.2026):** Alle Akten mit `.fw-aktenkopf` (Liegenschaft, Objekt, Mietverhältnis, Person, Dienstleister,
  Mandat, Schaden, Fall) folgen einem Muster: Kopf ohne Karte auf dem Seitengrund, Titelbild ausgeblendet (`.fw-akte-bild`),
  Pfad als Metazeile, Kennzahlen als ein Band (`.fw-kzn`, `.fw-kpis.fw-band`), Reiter als Text mit Markenstrich statt Pillen.
  Der Brotkrumen (`.fw-krumen`, `.fw-brotkrume`) wandert in der breiten Navigation in die Kopfleiste (`fw-schiene.js`).
  **Bewusste Abweichung vom Mockup:** kein eigener Reiter «Übersicht». Das Aktenregister (`faelle/akten.py`, `test_reiter_panels`)
  legt die Reiter fest, und «Was auffällt» bleibt nach Entscheid E2.73 auf jedem Reiter sichtbar.
- **Schäden, Modul 4 (22.11.2026):** Die Schadenliste (`.fw-schadenliste`) nutzt die volle Breite, die Sichten sind Text mit
  Markenstrich, und ab 900 px stehen die Zeilen im Spaltenraster (Nummer, Schaden, Zuständig als Kürzel, Dauer, Aktion; die
  Aktion ist immer sichtbar). Die Akte bleibt beim Aktenregister (Stammdaten, Chronik, Finanzen, Dokumente, Fälle, Handwerker &
  Kosten) und trägt das Muster aus Modul 2. **Nebenbefund behoben:** Im Fenster (`html._embed`, iframe) standen Kopfleiste und
  Handy-Tableiste; die alte Ausblend-Regel hatte ihr `display:none` verloren.
  **Zweiter Teil:** Die Suche steht in der Filterzeile (`.fw-schaden-suche`, sendet `q` und trägt Sicht, «Meine Tickets» und
  Bestandsfilter mit). «Schaden erfassen» ist ab 900 px eine Schublade von rechts (`#neuschaden.fw-schublade-rechts`, derselbe
  Knopf öffnet und schliesst, dazu das Kreuz); am Telefon klappt das Formular wie bisher in der Seite auf. Die Boards
  (`.fw-spalte`: Schäden, Bewerbungen) nutzen die volle Breite, die Spaltenköpfe stehen in Versalien.
- **Platzhalter im Mitteilungs-Assistenten (23.11.2026):** Vorschau, Serienbrief-PDF und E-Mail lösen Platzhalter aus EINER Quelle
  auf (`core.services.serienbrief.empfaenger_kontext` → `platzhalter.kontext_fuer`). Vorher kannte die Live-Vorschau nur die alten
  Kurznamen (`{name}`, `{objekt}`), das PDF nur einen Teil der neuen (`{mieter.anrede}`, `{objekt.adresse}`, `{verwaltung.telefon}`
  blieben stehen) und die E-Mail ersetzte gar nichts. Die Vorschau holt die Werte des ersten Empfängers von
  `/neu/kommunikation/platzhalter/` (JSON, mandantengefiltert); ohne Empfänger zeigt sie die Beschriftung in eckigen Klammern. Die
  alten Kurznamen behalten Vorrang und Bedeutung. `{frist}` / `{frist.tage}`: Nennt der Text eine Frist, erscheinen die Felder
  «Frist bis» und «Frist in Tagen», vorbelegt aus der Vorlage (`brief_aus_vorlage.frist_vorgabe`); ohne Wert bleibt der Platzhalter
  sichtbar stehen — es wird kein Datum erfunden.
- **Portale aus einem Guss (23.11.2026):** Mieter-, Eigentümer-, Betreiber- und Handwerker-Portal wurden wie die Verwaltung am
  gerenderten Bild vermessen (Desktop und 390 px). Das Betreiber-Portal nutzte schon die gemeinsamen Bausteine. Mieter- und
  Eigentümerportal wichen ab und sind über den Block «Portale aus einem Guss» in `fw/_schicht.html` angeglichen
  (`.fw-portal-inhalt`, `.fw-hw-seite`): Seitentitel in Sora 700 (vorher Inter 600), Karten `.fw-flaeche.rounded-2xl` und Kacheln
  mit 24 px und Linie statt 12 px mit Schatten, Akzentkachel («Etwas melden», «Leerstand») als normale Karte mit Primärknopf,
  «Ihr Mietobjekt» als helle Karte statt dunklem Verlauf, Felder 40 px. Handgebaute Knöpfe (Tailwind-Klassen) in
  `mieter_kuendigung`, `mieter_tickets`, `mieter_ticket_detail` und den Passwort-Seiten sind `fw-btn fw-primary`.
  Wächter: `e2e/tests/guss-portale.spec.ts` (Titel, Karten, Knöpfe, Felder, Querscrollen auf allen Seiten beider Portale).
  **Navigation (23.11.2026, Entscheid «alles aus einem Guss»):** Die Portale haben ab 1024 px dieselbe Seitenleiste wie die
  Verwaltung (`#pSidebar`: 248 px links, Marke oben, Seiten mit Zeichen untereinander, Abschnittstitel, Sprache und Abmelden im
  Fuss, aktive Seite wie in der Schiene). Vorher wurde dieselbe Leiste am Desktop zur Kopfleiste mit Kapseln umgestellt; das
  Markup ist unverändert.
  **Telefon (bis 640 px, 23.11.2026):** untere Leiste `#pTabbar` mit denselben Regeln wie `#fwTabbar` der Verwaltung
  (`.fw-tabbar`, `.fw-tab`, `.fw-tab-plus`). Belegung an einer Stelle in `core/templatetags/portal_tabs.py`, nach dem Pfad
  der Anfrage: Mieter (Übersicht, Rechnungen, + Schaden melden, Meldungen), Eigentümer (Übersicht, Abrechnung, Objekte,
  Dokumente), Betreiber (Kunden, Protokoll mit Fehlerzahl, + Kunde anlegen, LIK-Werte), dazu immer «Mehr». «Mehr» öffnet
  die vollständige Liste `#pSidebar` (`pOpenNav`), die die untere Leiste überdeckt; kein Ziel steht nur unten
  (`core/tests/test_portal_tabbar.py`). Der Menüknopf der Kopfzeile entfällt bis 640 px (dort das Markenzeichen), von 641
  bis 1023 px bleibt er. Das Handwerker-Portal ist eine einzelne Seite ohne Navigation und hat keine Leiste.
  **Anmeldeseiten** (`core/login.html`, `core/portal_login.html`, auch Betreiber): Titel in der Titelschrift, Felder 40 px,
  Knopf und Sprachwahl als Pille, Karte mit Linie statt Schatten. Die geteilte Seite mit der Markenfläche bleibt.
  Die Markenfläche ist seit 23.11.2026 eine ruhige helle Fläche wie die Seitenleiste (Fläche + Linie, Titel in der
  Titelschrift, Markenzeichen in der Markenfarbe) statt eines Farbverlaufs; der Wächter prüft das mit.
  **Aussenseiten (23.11.2026):** Startseite `/`, Passwort zurücksetzen (Hülle `_passwort_shell_top.html`), Fehlerseiten
  400/403/404/500, Zwei-Faktor-Bestätigung und «nicht mehr ausgeschrieben» tragen dieselben Bausteine: Titel in der
  Titelschrift, Karte mit Linie statt Schatten, Felder 40 px, Knöpfe als Pille. Die Klasse `fw-aussen-guss` am `<body>`
  holt die Regeln der Schicht; Seiten in `aussen_base.html` bekommen den Titel über `.fw-aussen-inhalt h1`. Wächter:
  `e2e/tests/guss-aussen.spec.ts` (acht Seiten, 1280 und 390 px) und `core/tests/test_guss_aussen.py` (Fehlerseiten und
  Zwei-Faktor, die der Testserver nicht zeigt).
  Das offene Bewerbungsformular war bereits stimmig; `zz-a-oeffentlich-bewerbung.spec.ts` hält das mit einem Guss-Test fest.
  **Assistenten (23.11.2026):** Alle Assistenten der Verwaltung haben denselben Aufbau: volle Inhaltsbreite, Schrittliste
  links, Inhalt, bei Vertrag, Kommunikation und Weiterverrechnen die Vorschau rechts als `.fw-assistent-vorschau`
  (`fw-assistent-mit-vorschau`). Weiterverrechnen nutzte die schmale Variante mit liegender Schrittleiste und eigener
  Vorschaukarte, die Betreibung stand in einer 672-px-Spalte; beide sind umgestellt. Der Fuss bleibt einzeilig: In einem
  schmalen Inhalt (Container-Abfrage auf `.fw-assistent-inhalt`, bis 520 px) entfällt «Schritt x von y», das über dem
  Schritttitel und unter der Schrittliste steht. Kommunikation und Weiterverrechnen haben eine Pfadzeile; `.fw-brotkrume`
  und `.fw-krumen` zeigen dasselbe Trennzeichen. Die Brief-Vorschau der Kommunikation steht in normaler Schriftstärke wie
  der gedruckte Brief (nur der Betreff fett). Wächter: `e2e/tests/guss-assistenten.spec.ts`.
  **Seitenformulare (23.11.2026):** Der Fuss eines Seitenformulars ist `.fw-formular-fuss`: Abbrechen zuerst, Hauptknopf
  rechts aussen (vorher in 25 Formularen links, in 8 rechts). Die Reihenfolge im Bild regelt `order`
  (`.fw-geist` −1, `.fw-primary` 9), damit der Hauptknopf im Quelltext der erste Absendeknopf bleibt: Enter in einem Feld
  löst ihn aus (Zahlungsverzug: «Frist ansetzen», nicht «Zusätzlich als PDF öffnen»). Zahlungsverzug und Schlussabrechnung
  tragen `.fw-lesebreite` (920 px) statt 672 und 768 px. Zeilenformulare in Tabellen und Akten (Bearbeiten einer Zeile)
  bleiben, wie sie sind: rechtsbündig in ihrer Zeile. Wächter: `e2e/tests/guss-formulare.spec.ts`,
  `core/tests/test_guss_formulare.py`. Die Nebenkosten-Schritte 2 bis 6 sind vermessen (stimmig) und stehen im
  Assistenten-Wächter; die Vertragsvorschau zeigt bewusst die Schrift des gedruckten Vertrags.
  Die Kachel «Kosten total» im Nebenkosten-Assistenten ist ruhig (`.fw-assistent .fw-kachel.akzent`, kein Farbverlauf);
  die Heute-Karte bleibt der einzige Blickfang dieser Art in der Verwaltung.
  **Betreiber-Portal im Wächter:** `seed_e2e` legt `e2e-betreiber` (Superuser, `e2e-pass`) an, aber nur bei `DEBUG`
  (so startet `e2e/run-server.sh`); ohne `DEBUG` entsteht kein Konto mit bekanntem Passwort (`core/tests/test_seed_e2e.py`).
  `guss-portale.spec.ts` prüft damit alle neun Betreiber-Seiten. Das Kennzahlenband `.fw-kzn` gilt dort wie in den Akten der
  Verwaltung als eigener Baustein (14 px).
- **Brief aus dem Mitteilungs-Assistenten (23.11.2026):** «Als Brief drucken» druckte die Vorschau aus einem leeren Browserfenster
  ohne Stilregeln (Logo in voller Grösse, kein Adressfeld). Jetzt liefern «Serienbrief-PDF» und «Als Brief drucken» denselben
  formatierten Brief (`generate_serienbrief_pdf`, Briefgerüst `DokCanvas.brief`); der Unterschied ist nur Herunterladen oder im
  Browser öffnen (`anzeigen=1`). Beide legen je Empfänger ab. **Einschreiben** ist wählbar (`#mk-einschreiben`, vorbelegt aus der
  Vorlage): Vermerk über dem Adressfeld. **Frist:** Setzt der Brieftext eine Frist (`frist_art_im_text`: massgebend ist der Text,
  nicht das Formularfeld) oder ist Einschreiben gewählt, entsteht je Empfänger dieselbe Pendenz wie beim Brief aus Vorlage
  (`brief_aus_vorlage._pendenz_anlegen`, Quelle `brief:<Dokument>`); sie steht damit im Fristen-Center. Der Brief setzt
  «Freundliche Grüsse», Unterschrift und Absender selbst; eine Grussformel am Schluss des Textes wird nicht doppelt gedruckt
  (`_ohne_schlussgruss`). Ein langer Text läuft auf die Folgeseite (vorher brach er am Seitenende ohne Hinweis ab).
  **E-Mail (23.11.2026):** Auch der E-Mail-Versand (`rundschreiben.versenden`, sofort und als Hintergrundauftrag) legt die
  versandte Mitteilung als PDF in der Akte ab (Titel «E-Mail: …», Mieter und Vertrag) und trägt eine im Text gesetzte Frist
  ein (`_ablegen_und_frist`). Abgelegt wird nur nach gelungenem Versand; scheitert die Ablage, wird protokolliert und nicht
  nochmals gesendet. Alle abgelegten Briefe und E-Mails sind im Mieterportal sichtbar (`im_portal_sichtbar=True`, Entscheid 23.11.2026).
- **Listenform (23.11.2026, Mockup «Immoswiss Listenform»):** Listen, die keine `<table>` sind, bekommen dieselbe Form wie die
  Tabellen: Karte `.fw-card.fw-lf`, Filter im Kartenkopf (`.fw-lf-kopf`), Spaltenkopf (`.fw-lf-spalten`), Zeilen (`.fw-lf-zeile`) im
  selben Raster (`.fw-lf-raster`; die Spalten setzt eine Seitenklasse wie `.fw-lf-objekte`). Zeile: Statuspunkt, Titel mit Unterzeile
  (`.fw-lf-titel`), Zellen (`.fw-lf-zelle`, `.fw-lf-chips`), Zahl rechts (`.fw-lf-zahl`), Aktion beim Überfahren (`.fw-lf-akt`).
  Gruppen sind `details.fw-lf-gruppe` und bleiben zuklappbar. Unter 900 px entfällt der Spaltenkopf, die Zeile stapelt.
  **Umgestellt:** Objekte (`/neu/objekte/`: eine Karte statt einer Karte je Liegenschaft; Mieter, Befund, Mietzins als Spalten).
  Schäden (`/neu/schaeden/`): Die Zeile behält ihr Markup (`.fw-zeile.fw-schadenzeile`, Klick öffnet weiter das Fenster); ab 900 px
  löst `display:contents` die Mitte auf, sodass Titel, Unterzeile (mit Nummer), Status und Befund Rasterzellen unter dem
  Spaltenkopf `.fw-schaden-spalten` werden. Darunter bleibt die gestapelte Zeile.
  Pendenzen (`/neu/pendenzen/`, `.fw-lf-pendenzen`): Die offenen Pendenzen stehen in EINER Karte, der Bezug ist eine Gruppenzeile
  (`.fw-lf-gruppenkopf.fw-lf-fest`, nicht zuklappbar); Fristen, Pendenzen und Erledigtes haben einen Spaltenkopf
  (`.fw-lf-zweispaltig`), die Fälligkeit steht ab 900 px in einer festen Spalte rechts. Die Zeilen behalten ihr Markup samt
  Formularen zum Erledigen und Löschen.
  Fristen (`/neu/fristen/`) und Ablesung (`/neu/ablesung/`) nutzen dieselben Klassen (`.fw-lf.fw-lf-pendenzen` mit Spaltenkopf).
  **Alle übrigen Zeilenlisten** (`.fw-zeile`: Einstellungs-Übersicht, Abonnement, Daten, MWST, Rechtsgrundlagen, E-Mail-Eingang,
  «Als Nächstes fällig» auf Finanzen u. a.) tragen ab 641 px dieselbe Zeile wie die Listenform: Trennlinie über die ganze Breite
  statt abgerundeter Fläche mit Seitenrand, Titel 14 px/600, Unterzeile 12 px, Mindesthöhe 56 px. Sie sind Menüs oder kurze
  Listen und haben darum keinen Spaltenkopf. `guss.spec.ts` prüft die Zeilenform auf allen Seiten.
- **Aus einem Guss (22.11.2026):** Jeder Baustein hat auf allen Seiten EINE Form; `e2e/tests/guss.spec.ts` misst das am
  gerenderten Bild über alle Seiten der Navigation (61 Adressen) und 14 Detailseiten und nennt die Seite, die abweicht. Die Regeln stehen im Block
  «Aus einem Guss» in `fw/_schicht.html`:
  - **Knöpfe** (`.fw-btn`, auch `.fw-knapp` und im Seitenkopf): 36 px hoch, 14 px Schrift, 16 px Rand (vorher 40/13, 36/14/16 und
    36/14/14). Am Telefon gilt weiter die Fingergrösse.
  - **Karten** (`.fw-card`) und die übrigen Kacheln (Hilfebox, Freigabe-Leiste, Ampel, Regel-/Importkachel): Linie,
    Kartenradius, kein Schatten. Listen ohne Kartenrahmen (`border:0` im Modul) bleiben.
  - **Kennzahlen** (`.fw-kpis`): überall ein Band mit Linien wie auf Berichte und Finanzen; die Kapselzeile mit Farbpunkt ist
    entfallen. `.fw-accent` (Hauptzahl oder gewählter Filter) trägt nur einen ruhigen Grund. Ausnahme bleibt `.fw-gross` (Finanzen).
  - **Felder** (`input.fw-feld`, `select.fw-feld`): 40 px hoch (vorher 38, 39, 41).
  - **Linker Rand:** Schmale Seiten (Lesespalte) stehen nicht mehr mittig; ihr Inhalt ist 920 px breit und beginnt am selben Rand
    wie jede andere Seite.
  - **Seitenkopf zuoberst:** Die Ablaufleiste der Vermietung steht auch auf «Mietverhältnisse» unter dem Inhalt.
  - **Listen (23.11.2026):** Die Aktenliste (`.fw-akten-karte`: Liegenschaften, Mietverhältnisse) steht in derselben Karte wie jede
    andere Liste statt rahmenlos auf dem Seitengrund. Die Zahlenzeile (`.fw-statuszeile` mit `.fw-sz`: Liegenschaften, Personen,
    Dienstleister, Schäden, Bankabgleich) ist dasselbe Band wie die Kennzahlen, der Farbpunkt bleibt. Umschalter (`.fw-segment`)
    haben die Masse der Filterknöpfe.
  - **Detailseiten und Telefon (23.11.2026):** Der Wächter prüft zusätzlich 14 Detailseiten und Formulare und läuft ein zweites Mal
    bei 390 px: nichts scrollt quer, alle Knöpfe haben die Fingergrösse 44 px (vorher 40 und 44 gemischt), Karten tragen die Linie.
  Neue Seiten bauen auf diesen Bausteinen auf, statt eigene Grössen zu setzen.
- **Einstellungen, Modul 9 (22.11.2026):** Die Übersicht (`/neu/einstellungen/`) und jede Einstellungsseite (`fw_einst_rahmen` aus
  dem Context-Processor) stehen im selben Rahmen: ab 1024 px links die Liste aller Einstellungen (`.fw-einst-spalten` >
  `nav.fw-einst-nav#fwEinstNav` + `.fw-einst-seite`, in `fw/base.html` um `block content` gelegt) mit Suchfeld (generischer Filter
  `data-suche`), Gruppen und markierter offener Seite (`aria-current="page"`, `aktiv` je Eintrag). Quelle bleibt
  `einstellungen_gruppen()`, gefiltert nach Rolle und Abo-Stufe. Am Telefon bleibt die Liste weg; die Krume führt zur Übersicht.
  **Aus einem Guss, per Test gesichert** (`EinstellungenSeitenlisteTests`): Der Seitentitel ist der Name aus der Liste, es gibt genau
  eine Pfadzeile (die Krume des Rahmens, keine eigene `.fw-brotkrume`), die Leiste markiert «Einstellungen», und der Inhalt hat eine
  Breite (860 px ohne Tabelle, volle Breite mit; eigene `max-w-*` der Seiten gelten im Rahmen nicht). Neue Einstellungsseiten
  halten sich daran. Der Verweis Lebensdauertabelle → Ersatzplanung ist jetzt ein Knopf im Seitenkopf.
  **Nicht gebaut:** die schwebende Speicherleiste und neue Schalter aus dem Mockup (die Seiten behalten ihre Formulare).
- **Berichte, Modul 8 (22.11.2026):** Übersicht, Portfolio, Auswertung und Team zeigen ihre Kennzahlen als ein Band
  (`.fw-kpis.fw-band.fw-ber-band`) statt als Kapselzeile oder mit oranger Akzentzelle. Die Übersicht (`/neu/berichte/`) hat neu ein
  Band über den Diagrammen: letzter gemessener Monat der Zahlungsquote, Summe der Ausstände über 30 Tage mit der Zahl betroffener
  Liegenschaften, Zahl der Liegenschaften; die Zellen sind Verweise (Auswertung, Debitoren-Aging, Portfolio). Die Werte kommen aus
  `_berichte_v8`, ohne weitere Abfrage. **Nicht gebaut** (bräuchte neue Rechenregeln): «Bester Monat» und «Gegenüber Vorjahr» in
  der Auswertung, Auslastung in Prozent im Team; die Schublade für eigene Auswertungen (die eigene Seite bleibt).
- **Kontakte, Modul 7 (22.11.2026):** Personen (`/neu/personen/`) und Dienstleister (`/neu/dienstleister/`) haben denselben Aufbau:
  Zahlenzeile, Kartenkopf mit Filter und Suche, Tabelle mit den Spalten Name, Kontakt, dritte Spalte (Adresse bzw. Kontaktperson),
  Stand, Aktion. Ab 1100 px zeigt «Vorschau» die Eckdaten rechts (`#fwVorschau`, `static/js/fw-vorschau.js`, der Inhalt steht in der
  `template`-Marke der Zeile); mit offener Vorschau weicht die dritte Spalte. Die Dienstleister waren Kacheln und sind jetzt eine
  Tabelle: Bearbeiten klappt unter der Zeile auf (`tr#dledit-<id>`), Löschen steht an der Zeile, «Auftrag per E-Mail» und «Anrufen»
  stehen in der Vorschau, «Handwerker erfassen» ist ab 900 px eine Schublade (`.fw-schublade-rechts`). «Stand» nutzt vorhandene
  Daten (aktuelles Mietobjekt bzw. offene Aufträge), keine weitere Abfrage. Test: `e2e/tests/kontakte-modul7.spec.ts`.
  Nebenbei behoben: Die 46 % breite Vorschau der Mieterkonten (Modul 6) galt versehentlich für jede Liste mit Vorschau, auch
  für die Liegenschaften; sie hängt jetzt an `.fw-mk-spalten`. Leere Felder im Bearbeiten-Formular zeigten «None».
- **Finanzen, Modul 6 (22.11.2026):** Übersicht (`/neu/finanzen/`): die vier Kennzahlen stehen als ein Band und sind Verweise
  (Bankkonten, Kreditoren, Debitoren-Aging, Kautionen). Ab 1100 px zwei Spalten: links «Ausstände nach Alter» mit einem
  Altersbalken (SVG ohne Inline-Stil; Anteile der vier Klassen am überfälligen Total, `aus_balken`), rechts der Bankabgleich und
  «Als Nächstes fällig» (offene Kreditoren, fällig bis in sieben Tagen oder überfällig, `kred_woche`). Beides aus den schon
  geladenen Daten, ohne weitere Abfrage. **Kreditoren:** «Tabelle | Spalten» (`#krAnsicht`, `localStorage` `fwKrAnsicht`); die
  Spalten zeigen dieselben Rechnungen nach Status, bearbeitet und freigegeben wird weiter in der Tabelle («In der Tabelle zeigen»).
  **Mieterkonten:** ab 1100 px öffnet «Kontoblatt» das Kontoblatt rechts neben der Liste (dieselbe Seite im Rahmen, `?embed=1`);
  die Zeile öffnet weiter die Seite. Skript: `static/js/fw-finanzen.js`. Test: `e2e/tests/finanzen-modul6.spec.ts`.
- **Monatsabschluss, Modul 5 (22.11.2026):** Die Übersicht (`/neu/laeufe/`) nutzt die volle Breite. Unter dem Titel steht der
  Fortschritt als Balken (`progress.fw-la-fortschritt`, dieselben Zahlen wie die Unterzeile, die auch den nächsten Schritt nennt).
  **Monatswahl:** `?monat=JJJJ-MM` blättert in frühere Monate (`_monat_aus_anfrage`; Unsinn und Zukunft fallen auf den laufenden
  Monat). Der laufende Monat zeigt wie bisher alle offenen Läufe plus die in ihm erledigten, ein früherer genau die Läufe seiner
  Periode. **Monat in Zahlen** (rechts ab 1100 px): im Monat fällige Sollstellung, was davon offen ist, Anzahl offener Positionen
  und Eingangsquote, gerechnet mit `faelle.lage._eingangsquote`, also derselben Definition wie der Kennzahlenstreifen auf «Heute».
  **Übersprungen:** Ein übersprungener Lauf steht als «Übersprungen am …» mit seiner Begründung da (nicht mehr als
  «Abgeschlossen») und lässt sich an der Zeile zurücknehmen; das ist derselbe Weg wie «Zurücksetzen» in der Laufakte
  (`fw_lauf_zuruecksetzen`, nur mit Begründung, im Logbuch). Test: `faelle/test_schrittliste.py`.
  **Bewusst nicht gebaut:** einzelne Positionen in der Sollstellung auslassen. Der Lauf würde als abgeschlossen gelten, obwohl
  Mieten fehlen; das ändert die Fachlogik und braucht einen eigenen Entscheid.
- **Liegenschaftsliste, Modul 2 (22.11.2026):** Ab 1100 px zeigt «Vorschau» je Zeile die Eckdaten rechts neben der Liste (Mandat,
  Objekte, Belegung, Soll, alle Befunde; Knöpfe «Akte öffnen», «Objekte», «Mietverhältnisse»), ohne die Akte zu öffnen. Der Inhalt
  steht fertig in einer `template`-Marke der Zeile, `static/js/fw-liegenschaften.js` setzt ihn nur um. Ab 641 px stellt der Schalter
  «Liste | Karten» dieselbe Tabelle als Karten dar (`#lgListe.fw-karten`, `localStorage` `fwLgAnsicht`). Keine neue Adresse, keine
  neue Abfrage; ohne Skript bleibt die Tabelle. Test: `e2e/tests/liegenschaften-vorschau.spec.ts`.
- **Listen, Modul 2b (22.11.2026):** Die Akten von Mandat, Mietverhältnis, Person und Dienstleister tragen das Muster aus Modul 2
  bereits über `.fw-aktenkopf`. An den Listen: Zeilenaktionen der Mandate stehen in einer Zeile (`.fw-zeilenakt`, am Handy
  umbrechend, damit keine Aktion abgeschnitten wird); die Dienstleister-Karten (`.fw-raster.l3`) sind von der Lesespalte
  ausgenommen und nutzen die volle Breite.

### Schriftskala

Die Stilschicht kennt acht Schriftstufen: 12, 13, 14, 15, 18, 22, 24, 28 px (24 px seit dem Mix-Entwurf für Seitentitel) (vorher 28 verschiedene Werte, viele nur 0,5 px
auseinander). Jede alte Grösse wurde auf die nächste Stufe gerundet (12,5 → 13, 13,5 → 14, 16/17/19 → 18, 20/21/23/24 → 22,
26/30/32 → 28); fast nichts wird kleiner, vieles minimal grösser. Ausserhalb der Skala bleiben die Mikroschrift unter 12 px
(nur die Selektoren in `test_schrift_mindestgroesse`) und die Anzeigezahlen 34/40/52 px. Wächter: `core/tests/test_schriftskala.py`.

### Zeilenabstand als Standard

Am PC haben Zeilen den Abstand des Prototyps als Standard: `7 px 18 px 7 px 14 px` (vorher 14 px 24 px), auf «Heute» entsprechend; die Zeile bleibt zweizeilig.
Am Handy (bis 640 px) bleibt der grosse Abstand wegen der Tippflächen. Die Ansicht «Dicht» (Zweitzeile neben dem Titel, Schalter ab 10 Einträgen)
bleibt zusätzlich wählbar. Entscheidung des Betreibers vom 20.11.2026 («nach Empfehlung»).

### Dichte Listen

Karten mit mindestens 10 Zeilen (`.fw-zeile`) bekommen ab 641 px die Klasse `fw-dicht`: halber Abstand, Titel und Zweitzeile nebeneinander
(Titel kürzt mit «…», der volle Text steht im Tooltip). Ein Schalter «Bequem | Dicht» sitzt im Kartenkopf; die Wahl bleibt je Gerät
im `localStorage` (`fwDichte`), ohne Wahl gilt die Automatik. Schrift, Farben und Marker bleiben unverändert. Am Handy ist die Ansicht
nicht verfügbar, damit die Tippflächen halten. Skript `static/js/fw-rahmen.js` (`fwDichteInit`), Vorlage des Schalters
`#fwDichteVorlage` in `fw/base.html`.

### «Neuer Fall» und «Mitteilungen» (Zielbild)

«Neuer Fall» zeigt die Brotkrumen «Heute / Neuer Fall» (nicht in der Schublade, `?embed=1`). Die Frist-Kapseln sind «Heute»,
«In 7 Tagen», «In 30 Tagen» und «Ohne Frist»; `data-frist-tage="keine"` leert das Datumsfeld (`static/js/fw-aktionen.js`).
Die Seite `/neu/zulauf/` heisst für die Anwender «Mitteilungen»; Adresse, Ansichten und Code-Namen («Zulauf») bleiben. Ohne offene
Eingänge steht «Alles zugeordnet» mit dem Weg zurück zu «Heute».

### Berichtskatalog (`/neu/berichte/`)

Der Katalog «Alle Reports und Exporte an einem Ort» steht nach dem UI-Zielbild in **einer** Karte: Suche oben, darunter je Gruppe
eine Überschrift und ein Kachelraster (`fw-katalog*`, `fw-kachel-bericht`). Die Hooks der Live-Suche (`#berichtListe`,
`data-gruppe`, `data-zeile`, `data-keine`) sind unverändert (`e2e/tests/berichte-suche.spec.ts`). Noch nicht umgesetzt, weil
Entscheidungen offen sind: die Gruppe «Häufig» und die Ziellinie im Diagramm. Die Kennzahl der Kachel heisst `fw-katalog-wert`;
`fw-kachel-zahl` ist die grosse Zahl der Bento-Kacheln und darf hier nicht wiederverwendet werden.

### «Heute» (`/neu/`)
Nach UI-Zielbild: oben der Schwerpunkt als **sichtbares Segment** (Bewirtschaftung | Buchhaltung | Übersicht, `.fw-schwerpunkt-segment`, POST
`/neu/schwerpunkt/`; «Neuer Fall» steht in «+ Neu»), darunter eine **Statuszeile** statt der Aufgabenkacheln (`faelle/heute_kacheln.py` liefert
unverändert Zahl, Titel, Text, Ziel, Ton; im Schwerpunkt «Übersicht» bleibt der Lage-Streifen `fw-lage`). Der Arbeitsvorrat «Heute» und
«Diese Woche» ist nach Dringlichkeit gruppiert (`_dringlichkeitsgruppen` in `core/views/fw/dashboard.py`: «Überfällig · bis 30 Tage», «Seit über
30 Tagen offen · vermutlich festgefahren»; `FESTGEFAHREN_TAGE`). Der Zeilenknopf nennt die Aufgabe (Läufe über `LAUF_AKTION` in
`faelle/arbeitsvorrat.py`: Auslösen, Importieren, Freigeben); dazu ein ✓ «Erledigt» bei Fallschritten (`/neu/fallschritte/<id>/erledigen/`,
Toast «Rückgängig»). Test: `faelle/test_heute_zielbild.py`, `e2e/tests/heute-zielbild.spec.ts`, `heute.spec.ts`.
**Heute, Modul 3 (22.11.2026):** Die dunkle Karte ist weg. Begrüssung und Datum stehen ruhig auf dem Seitengrund, der Schwerpunkt
rechts daneben; die Aufgabenzahlen bilden ein Band mit Zellen (dieselben Links, `.fw-hallo .fw-statuszeile`). Die Reiter des
Arbeitsvorrats sind Text mit Markenstrich, die gewählte Zeile trägt den Markenton, Karten haben eine Linie. Nur Gestalt in
`_schicht.html` («Heute, Modul 3»); Vorlage, Ansicht und Adressen sind unverändert. Die Eckdaten-Spalte aus dem Mockup bleibt die
bestehende Vorschau (`fw-vg`).

### Statuszeile statt Kennzahl-Kacheln
Listenseiten zeigen oben eine **Statuszeile** (`.fw-statuszeile` mit `.fw-sz`, UI-Zielbild): schmale Kapseln mit Farbpunkt (grün/gelb/rot nach
`fw-sz-good|warn|crit`), Zahl und Wort in einem («3 offen», «2 leer (40 %)»). Schäden (`faelle/schaeden.py::streifen`), Liegenschaften
(`kennzahlen`) und Bankabgleich (Kapseln öffnen die Arbeitslisten, `data-spur-link`). Klassen **immer ausgeschrieben** (`fw-sz-warn`),
nie `fw-sz-{{ x }}`: `test_fw_klassen_wirken` findet zusammengesetzte Namen nicht. Zahlen, die die Seite nicht liefert, werden nicht
dazugebaut. Test: `e2e/tests/statuszeile.spec.ts`.
**Standard auf allen Seiten:** Jede `.fw-kpis`-Gruppe (rund 55 Vorlagen, auch die Aktenleiste `fw-stats` und die Portale) wird in der Stilschicht
(Modul «Kennzahlen als Statuszeile», `html .fw-kpis:not(.fw-gross)`) zur Kapselzeile; das Markup (`.fw-kpi > .fw-l/.fw-v/.fw-f`) bleibt. Der
Farbpunkt folgt `fw-good|warn|crit` am Wert, der Zusatz (`.fw-f`) steht gedämpft dahinter, am Telefon entfällt er bei der Aktenleiste
(bleibt flach, `telefon.spec.ts`). **Ausnahme `fw-gross`:** nur die grossen Kontostände und der Abschluss-Block auf Finanzen, wie im Zielbild;
`core/tests/test_statuszeile_standard.py` lässt `fw-gross` nur dort zu. Nicht Teil davon: die Status-Kacheln `fw-lage` (z. B. Debitoren) und die
Kacheln von «Heute» (eigenes Paket).

### Monatsabschluss als Schrittliste (`/neu/laeufe/`)
Die Seite zeigt die Läufe als eine Liste «Schritte in dieser Reihenfolge» (UI-Zielbild): offene Läufe plus die in diesem Monat
abgeschlossenen, geordnet nach `Laufart.reihenfolge`, zuletzt der **Periodenabschluss**. Zustand je Schritt: `fertig` (Haken),
`jetzt` (der erste offene Lauf, Knopf in Hauptfarbe), `offen` (weitere offene, eigener Knopf), `gesperrt` (Periodenabschluss, solange
ein Lauf offen ist; Text «Möglich, sobald … erledigt ist»). Der Knopf nennt die Aufgabe (`LAUF_AKTION`: Auslösen, Importieren,
Freigeben, sonst Öffnen). Nur Darstellung (`_monatsschritte` in `core/views/fw/arbeit.py`): Zustand und Blockaden bleiben die der Läufe,
«Überspringen» (mit Begründung) und das Lauf-Detail bleiben erreichbar; frühere Monate stehen unter «Zuletzt abgeschlossen».
Test: `faelle/test_schrittliste.py`, `e2e/tests/monatsabschluss-schritte.spec.ts`.

### Formulare ohne riskante Vorbelegung («Neuer Fall»)

Pflichtentscheidungen (Art, Akte) stehen im Formular **leer**; vorgewählt wird nur, was aus der Adresse kommt (`?akte=`).
Das Formular trägt `data-knopf-erst-gueltig`: `static/js/fw-aktionen.js` sperrt den Absende-Knopf, bis `checkValidity()`
stimmt (ohne JS bleibt er bedienbar, der Server prüft immer). Frist-Chips (`data-frist-tage="N"`, `data-frist-ziel="id"`)
setzen das Datum auf heute + N Tage. Vergleiche in Vorlagen nie mit `'präfix-'|add:zahl` bauen: `add` liefert bei Zahlen
leer (`'' == ''` wählte still den letzten Eintrag vor) – Test: `core/tests/test_fall_neu_formular.py`.

### Rückgängig (Toast)
- Eine Handlung kann nach dem Speichern einen Toast mit «Rückgängig» zeigen (`core.views.fw._basis.meldung_mit_rueckgaengig`,
  Filter `rueckgaengig_url`, Vorlage `fw/base.html`, zehn Sekunden). Die Handlung läuft sofort; der Knopf ruft per POST eine
  vorhandene, geprüfte Rücknahme (nicht: verzögert ausführen, denn wer die Seite schliesst, verlöre die Handlung ohne Meldung).
- Eingebaut: Schritt erledigt → `Fallschritt.wieder_oeffnen` (`/neu/fallschritte/<pk>/wiederoeffnen/`); Zahlung aus der Klärung
  (Durchlaufkonto 1190) zugeordnet → `zahlungsklaerung.zuordnung_aufheben` (Gegenbuchungen im Journal, Rechnung wieder offen,
  Absender vergessen). Nie bei Läufen, Monatsabschluss, Zahllauf, Kaution oder versandten Mails.

### Schadenmeldungen und Mail
- Schadensliste (`fw/schaeden.html`, UI-Zielbild): Titel «Schäden», Sichten als Reiter mit Zahl in der Karte (`sicht_chips` = Wert, Text, Zahl), je Zeile
  Statuschip (plus Notfall/Hoch/SLA) über dem Titel, «seit N Tagen» und die **nächste Aktion** als Knopf (`aktion` in `fw_schaeden`: «Auftrag erteilen» bei
  offener Meldung ohne laufenden Auftrag, «Handeln» bei Befund, «Nachfassen» beim Warten auf Dritte, «Ansehen» bei erledigt, sonst «Öffnen»).
  Jeder Knopf öffnet den Schaden in der Schublade (bei «Auftrag erteilen» auf dem Reiter «Handwerker & Kosten», `?tab=handwerker`) und versendet nichts;
  Handwerker, Text und Versand bleiben dort. Die Aufträge sind vorgeladen, keine Zusatzabfragen. Test: `e2e/tests/schaeden-zielbild.spec.ts`.
- Eingang: Mieterportal, internes Erfassen, Webformular `/schaden/melden/` (ordnet über die hinterlegte E-Mail-Adresse
  zu, antwortet immer gleich) und QR-Aushang `/aushang/<token>/` (Token je Liegenschaft, erneuerbar).
- Antwortadressen: Jede Verwaltung hat `<antwort_kennung>@ANTWORT_DOMAIN` für Antworten und eine eigene
  `<rechnungs_kennung>@ANTWORT_DOMAIN` für Kreditorenrechnungen (`core/services/antwort_eingang.py`).
- Eingehende Mail kommt über das Sammelpostfach (`fetch_plattform_eingang`), den Brevo-Webhook oder ein eigenes
  Postfach der Verwaltung (`fetch_replies`, `fetch_rechnungen`). Nur Absender, die zum Ticket gehören, werden als
  Antwort geführt; alles andere wird als interne Notiz abgelegt (`tickets/workflow.py`).
- Reparaturfreigabe: Sie gilt für die Schätzung, die die Eigentümerschaft gesehen hat. Liegen die effektiven Kosten
  mehr als 20 % darüber (`ABWEICHUNG_NACHFREIGABE`) oder ab der Schwelle, braucht es eine Nachfreigabe; verglichen wird
  mit der bisher gespeicherten Schätzung, nicht mit der soeben eingegebenen (`fw_auftrag_kosten`).
- Direktkanal Mieter–Handwerker (`tickets/direktkanal.py`): Die Marke im Betreff trägt eine Kennung der
  Empfängerseite; sie bestimmt, wer antwortet. Ein Widerruf entwertet Links und Marken beider Seiten.

### Täglicher Lauf
`manage.py taeglicher_lauf`: Auto-Pendenzen, Referenzzins und LIK, alte Logdateien löschen, montags Fristen-Mail;
je Verwaltung Adresswechsel, Bereinigung der Bewerbungen, Laufplanung, Erinnerungen.

## 6. Abonnement

Einzige Quelle für Stufen, Grenzen, Preise und Module ist `core/funktionen.py`.

- Vier aufbauende Stufen (`start`, `team`, `professional`, `enterprise`) mit Grenzen für Einheiten und Benutzer;
  zubuchbare Module (`signatur`, `belegerkennung`, `reporting_erweitert`; die beiden letzten sind ab `professional`
  inklusive).
- Eigene Auswertungen (`reporting_erweitert`): gespeicherte Vorlagen aus festen Datenquellen und Spalten mit
  CSV-Export (`core/services/eigene_auswertung.py`, Modell `core.Auswertungsvorlage`, Seiten unter
  `/neu/auswertung/eigene/`).
- Schnittstellen (`schnittstellen`, ab `professional`): Journal-Formate Banana und bexio, Vermarktungs-Feed,
  Kalender-Abonnement — alle fragen `abo.zugang.schnittstelle_frei`.
- Im Katalog steht nur, was gebaut ist und geprüft wird: Jeder Schlüssel über `start` und jedes Modul braucht eine
  Prüfstelle (`abo/test_freigabe.py`, `KatalogHaeltWasErVersprichtTests`).
- Durchsetzung: `hat_funktion()`, die Pfadtabelle und der Dekorator in `abo/zugang.py`, `AboMiddleware`. Eine
  gesperrte Funktion antwortet mit der Sperrseite (HTTP 402). Mengengrenzen prüft `abo/signale.py` beim Anlegen.
- Abrechnung: `manage.py abo_abrechnung` (täglich, eigener Task). Rechnung im Voraus als QR-Rechnung; der
  Zahlungseingang wird von Hand bestätigt. Bei Bestandsschutz (`Abonnement.uneingeschraenkt`) stellt `rechnung_stellen`
  nie eine Rechnung, auch mit gesetztem Abrechnungsbeginn. Der Zahlungszustand gilt immer für heute, nie für das
  (rückdatierte) Zahlungsdatum (`als_bezahlt`).
- Eskalation ab Fälligkeit: Mahnung, zweite Mahnung, Lesemodus, Sperre (Tage in `settings.py`, `ABO_*`). Im
  Lesemodus bleiben Anmeldung, Abonnement und Export offen; es wird nichts gelöscht.
- Neuer Kunde: Betreiber-Portal `/betreiber/neu/` → `core/services/onboarding.py`; der Inhaber bekommt einen
  Einladungslink. Eine öffentliche Registrierung gibt es nicht.

## 7. Sicherheit

| Thema | Umsetzung |
|---|---|
| Content Security Policy | `core/csp.py`: Nonce je Anfrage, Modus über `CSP_MODUS`, Meldestelle `/csp-bericht/` |
| Zwei-Faktor | eigene TOTP-Umsetzung (`core/services/totp.py`, `core/views/zweifaktor.py`) |
| Bremsen | `core/utils/throttle.py`: festes Zeitfenster, IP aus dem rechten Eintrag von `X-Forwarded-For` |
| Geheimnisse | Fernet-Verschlüsselung (`core/services/geheimnis.py`) für Postfach-Zugänge, AHV-Nummern, 2FA-Geheimnisse |
| Zugänge ohne Anmeldung | Zufallstoken je Objekt oder Person: Aushang, Handwerker-Link, Kalender-Link, Portal-Einladung |
| Protokoll | `core/logschutz.GeheimnisFilter` kürzt Zugangslinks vor dem Schreiben; Löschfrist `LOG_AUFBEWAHRUNG_TAGE` |
| Revisionsspur | verkettetes Logbuch (`core/log_kette.py`), Buchungen sind nicht löschbar (`finance/db_schutz.py`) |
| Geldpfade | «sperren, prüfen, buchen» (`core/sperren.py`), Periodensperre nur mit zweiter Person lockerbar |
| Datenschutz | Auskunft und Export (`core/services/auskunft.py`, `datenexport.py`), Anonymisierung statt Löschung (`core/services/dsg.py`) |

## 8. Externe Dienste

| Dienst | Wofür | Schalter |
|---|---|---|
| SMTP und IMAP (Hoststar) | Mailversand, Sammelpostfach | `EMAIL_HOST_*`, `PLATTFORM_IMAP_*` |
| Brevo | eingehende Mail per Webhook | `BREVO_API_KEY`, `BREVO_WEBHOOK_SECRET` |
| DocuSeal | elektronische Signatur (Modul) | `DOCUSEAL_API_KEY`, `DOCUSEAL_WEBHOOK_SECRET` |
| Groq | Belegerkennung (Modul); ohne Schlüssel nur Mustererkennung | `GROQ_API_KEY` |
| HEV, BWO | Landesindex und Referenzzinssatz | `LIK_LIVE_ABRUF` |

## 9. Betrieb

### Einspielen
`bash deploy.sh` holt `main`, installiert Abhängigkeiten, prüft die Datenbank, sichert bei offenen Migrationen,
migriert, sammelt statische Dateien, lädt die Web-App neu und führt die Betriebsprüfungen aus. Bei einem Fehler
wird zurückgerollt.

### Dauerläufer und geplante Aufgaben

| Art | Befehl |
|---|---|
| Dauerläufer | `bash deploy.sh --dauerlauf`, `manage.py auftraege_abarbeiten --dauerlauf`, `manage.py fetch_plattform_eingang --dauerlauf` |
| täglich | `taeglicher_lauf`, `abo_abrechnung`, `sicherung --ohne-medien`, `log_kette_anker` |
| wöchentlich | `sicherung` (voll), `log_kette_pruefen` |
| monatlich | `monatslauf`, `mahnlauf` (oder über die Oberfläche) |
| bei Bedarf | `fetch_replies`, `fetch_rechnungen`, `send_eigentuemer_reports`, `jahresabschluss_lauf`, `dsg_anonymisieren --apply` |

Der Auftragsläufer ist Pflicht, sobald ein Kunde über einer der Schwellen aus Abschnitt 5 liegt.

### Umgebungsvariablen (Auswahl, vollständig in `swiss_immo/settings.py`)

`SECRET_KEY`, `DEBUG`, `EXTRA_ALLOWED_HOSTS`, `EXTRA_CSRF_ORIGINS`, `PORTAL_BASE_URL`, `DB_ENGINE` und `DB_*`,
`RLS_MODUS`, `CSP_MODUS`, `CACHE_VERZEICHNIS`, `GEHEIMNIS_SCHLUESSEL`, `SICHERUNG_SCHLUESSEL`, `ANTWORT_DOMAIN`,
`LOG_AUFBEWAHRUNG_TAGE`, `AUSHANG_ID_ROUTE_BIS`, `RECHNUNGSADRESSE_ALT_BIS`, `ABO_STELLER_*`, `ABO_MAHNGEBUEHR`.

### Sicherung
`manage.py sicherung` (`--ziel`, `--behalten`, `--ohne-medien`, `--medien-behalten`). PostgreSQL über `pg_dump -Fc`,
jeder Stand wird gegengelesen. Ausser Haus: `SICHERUNG_SCHLUESSEL` setzen und `--offsite ORDNER`; zurück mit
`--entschluesseln DATEI --nach ZIEL`. Die Passphrase getrennt von der Sicherung aufbewahren.

### Wiederherstellung (PostgreSQL)
1. Web-App anhalten.
2. Neue Datenbank anlegen und `pg_restore -d <neu> <sicherung>` ausführen.
3. Mit `DB_NAME=<neu> manage.py bestand_zaehlen` und `medien_pruefen --sicherung <tar>` prüfen.
4. `DB_NAME` in der `.env` und `.datenbank-erwartet` umstellen, Web-App neu laden.
5. `manage.py rls_einrichten --status` prüfen.

### Schlüsselwechsel (`GEHEIMNIS_SCHLUESSEL`)
1. Neuen Fernet-Schlüssel erzeugen und in der `.env` als `<NEU>,<ALT>` eintragen; neu laden.
2. `manage.py schluessel_wechseln` (Prüfung), dann `schluessel_wechseln --ausfuehren`.
3. In der `.env` nur `<NEU>` stehen lassen; neu laden.

Ohne den Schlüssel sind AHV-Nummern, Postfach-Zugänge und 2FA-Geheimnisse unlesbar. Alte Sicherungen brauchen den
alten Schlüssel.

### RLS scharf schalten
1. `RLS_MODUS=probe`, neu laden, rund zwei Wochen alle üblichen Läufe ausführen.
2. Befunde lesen: `manage.py sicherheitslog` (Aktion «RLS-Probe: fremde Zeile gelesen») und Betreiber-Protokoll.
3. `manage.py rls_einrichten --status`, dann `rls_einrichten` als Eigentümerin der Tabellen.
4. `RLS_MODUS=scharf`, Web-App und alle Dauerläufer neu starten.

Zurück: `RLS_MODUS=aus` oder `rls_einrichten --entfernen`. Nach neuen Tabellen in `finance` erneut einrichten.

### Neue Instanz auf PostgreSQL
`postgres_anlegen.py` legt Rolle und Datenbank an; `bash umzug_postgres.sh` prüft, sichert, überträgt die Daten,
richtet die Sequenzen und vergleicht den Bestand. Erst danach `DB_*` in die `.env` und `.datenbank-erwartet` anpassen.

### Wartungsseite
Sind Migrationen nicht angewendet, antwortet die Anwendung mit einer Wartungsseite (HTTP 503) statt mit Fehlern
(`core/wartung.py`). Behebung: `manage.py migrate`, Web-App neu laden. `/version/` und `/healthz/` zeigen den Stand.
Die Prüfung läuft einmal beim Start, nie je Anfrage.

### Betreiber-Portal
`/betreiber/`: Kunden und Abonnemente, Protokoll (Fehler der Anwendung, Abrufe, Aufträge, RLS-Probe, CSP, Pflege,
Sicherheit; mit CSV-Export), LIK-Werte, Sicherheit.
