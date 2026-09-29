# Audit: Weg zum SaaS-Niveau — Funktionen, Abläufe, Gestaltung

Stand `42cd3cc`, 29.09.2026. Nur Befund, keine Änderung am Code.

**Methode.** Die Phase 1 ist gemessen, nicht geschätzt: Alle 518 registrierten
URL-Muster wurden aus Django ausgelesen (`get_resolver()`) und gegen sämtliche
Vorlagen, JS-Stellen, `core/navigation.py` und Python-Redirects abgeglichen. Da
die Oberfläche fast nur mit festen Pfaden verlinkt (562 `/neu/…`-Pfade in
Vorlagen gegenüber 30 `{% url %}`-Tags), lief der Abgleich über die Routen
selbst. Jeder Treffer wurde danach von Hand geprüft. Die Zahlen in Phase 2 und
3 sind Zählungen über `core/templates/**` (178 Vorlagen, 99 davon auf
`fw/base.html`).

**Vorbemerkung zum Produkt.** swissImmo ist keine Inseratplattform, sondern
Verwaltungssoftware für Bewirtschafter. Die «Listings» sind hier Akten
(Liegenschaft, Objekt, Mietverhältnis). Gemessen wird deshalb an Werkzeugen
wie Fairwalter, ImmoTop2 und Rimo R5, nicht an Homegate.

---

## Kurzfassung

| Phase | Urteil |
|---|---|
| 1 Funktionen vs. Oberfläche | Gut abgedeckt. Von rund 300 fachlichen Routen sind **6 Funktionen ohne Einstieg** und **5 Altlasten** übrig. Zwei davon sind geschäftlich wichtig: das öffentliche Bewerbungsformular und die Mängelrüge nach Art. 267a OR. |
| 2 Abläufe | Die Navigation ist sauber (5 Bereiche). Die grösste Schwäche sind **Formulare**: Eingaben gehen bei Fehlern verloren, ungültige Werte werden stillschweigend als leer gespeichert. Dazu kommen drei **GET-Aufrufe mit Nebenwirkung** (einer verschickt E-Mails). |
| 3 Gestaltung | Farben, Tokens, Dark Mode und Icons sind **auf SaaS-Niveau**. Die **Struktur** ist es nicht: 145 verschiedene Button-Klassen, 470 frei gewählte Pixel-Schriftgrössen, nur 16 von 107 Tabellen auf der Tabellenkomponente. |

**Einschätzung.** Fachlich ist swissImmo einem 10k-MRR-Produkt voraus. Der
Funktionsumfang (QR-Rechnung, camt.053, pain.001, Formularpflicht,
Mietzinsanpassung) ist grösser als bei vielen Mitbewerbern. Was fehlt, ist
Verlässlichkeit im Kleinen: Formulare, die Fehler zeigen, Seiten, die gleich
aussehen, und Bestätigungen, die nicht aus dem Browser stammen. Das ist
Handwerk, keine Architekturfrage, und damit gut planbar.

---

## Phase 1 — Feature-Mapping & verwaiste Funktionen

### 1.1 Funktionen ohne Einstieg in der Oberfläche

| # | Funktion | Route / View | Befund | Gewicht |
|---|---|---|---|---|
| F1 | **Öffentliches Bewerbungsformular** | `/bewerben/<einheit_id>/` · `core/views/application.py` | Die Verwaltung findet den Link nirgends: kein Kopierknopf, kein QR-Code, kein Eintrag in Vermarktung, Ausschreibung oder Exposé. Der Feed (`profil.py:920`) enthält ihn ebenfalls nicht. Bewerbungen kommen nur herein, wenn jemand die URL von Hand baut. | **hoch** — der ganze Vermietungstrichter (Bewerbungen → Vergleich → Entscheid → Vertrag) hängt daran |
| F2 | **Mängelrüge Art. 267a OR aus dem Abnahmeprotokoll** | `/neu/abnahme/<pk>/ruege-267a/` · `abnahme.py:167` | Die View ist fertig (PDF, Ablage, Pendenz abhaken). `abnahme_detail.html` hat aber keinen Knopf dafür. `abnahme_neu.html:64` erklärt dem Nutzer sogar, dass die Rüge *sofort* erfolgen muss, bietet sie aber nicht an. | **hoch** — ohne rechtzeitige Rüge verwirken die Ersatzansprüche |
| F3 | **Lebensdauertabelle** (paritätisch, pflegbar) | `/neu/lebensdauer/` · `detailseiten.py` | Es gibt keinen Link, keinen Nav-Eintrag und keine Kachel in den Einstellungen (`aktionen.py:830ff`). Die Seite verlinkt nur auf sich selbst. Sie speist Abnahme und Ersatzplanung. | mittel |
| F4 | **Hausflur-Aushang mit QR** (Schadenmeldung) | `/liegenschaft/<id>/poster/` | Nur im Django-Admin (`/admin/`) verlinkt, nicht in der Liegenschaftsakte. | mittel |
| F5 | ~~Fall-Übersicht~~ | `/neu/?ansicht=alle` | **Korrigiert in Etappe 1: kein Befund.** «Heute» mit der Ansicht «Alle» und Fallart-Filter *ist* die Fall-Liste — so entschieden in KONZEPT-UI G2 («Ein Arbeitsvorrat, nicht zwei Listen»). Eine zweite Liste hätte den Entscheid gebrochen. Echt war nur: Die Fallakte nannte ihre Akte ohne Link (behoben). Ein Link Mieterwechsel → Fall hat kein Ziel, weil der Mieterwechsel heute keinen Fall eröffnet; das ist die geplante Einbindung in die Fallmaschine (`ZUORDNUNG-VIEWS.md` Abschnitt 2), kein Quick Win. | – |
| F6 | ~~Suche in der Objektliste~~ | `listen.py:1079` liest `q` | **Korrigiert in Etappe 1: kein Befund.** Das zweite Suchfeld wurde bewusst entfernt; das Suchfeld der Kopfzeile filtert die Liste (`faelle/test_objektliste.py::test_es_gibt_kein_zweites_suchfeld_mehr`). Ein zweites Feld wurde gebaut, vom Wächter abgelehnt und zurückgenommen. | – |

### 1.2 Altlasten: Endpunkte, die weg oder umgebaut gehören

| # | Route | Befund |
|---|---|---|
| A1 | `vertrag/<id>/mahnung/mail/` (`send_mahnung_mail`) | Nirgends verlinkt, **verschickt aber bei GET eine Mahnung** und legt sie ab. Ein Link-Prefetch oder Crawler löst Mahnungen aus. Entfernen. |
| A2 | `neu/vertrag-mietzins/<pk>/` (+ `/loeschen/`) | Durch den Objekt-Sollmietzins abgelöst; `vertrag_detail.html:470` sagt «nur Ansicht». Toter Endpunkt, entfernen. |
| A3 | `abrechnung/<id>/send-mail/` | Liefert bewusst 404 (`email_views.py:206`), der Admin-Knopf (`finance/admin.py:86`) zeigt aber noch darauf. |
| A4 | `fw_stub` + `fw/stub.html` | Platzhalterseite «In Vorbereitung», wird nicht mehr aufgerufen. |
| A5 | `/neu/arbeit/`, `/neu/assets/` | Reine Weiterleitungen für alte Lesezeichen. Harmlos, können bleiben. |

### 1.3 Was *nicht* verwaist ist

Gut ist, dass alle Listen, Akten, Läufe, Finanz- und Berichtsseiten über die
Navigation oder die Akte erreichbar sind. Die elf Bausteine, die
`ZUORDNUNG-VIEWS.md` Abschnitt 2 nennt (Verzug 257d, Bewerbervergleich,
Zahlerregeln, Vorlagen, Akontoanpassung …), haben alle einen Einstieg. Die
Webhooks (DocuSeal, Brevo), `/healthz` und `/version` haben zu Recht keinen.

### 1.4 Nebenbefund: Links als feste Pfade

562 feste `/neu/…`-Pfade in Vorlagen stehen 30 `{% url %}`-Tags gegenüber.
Jede Umbenennung einer Route bricht still. Das ist kein sichtbarer Fehler, es
verteuert aber jeden künftigen Umbau. Eine Umstellung lohnt sich
schrittweise, bei jeder Datei, die ohnehin angefasst wird.

---

## Phase 2 — Abläufe & UX

### 2.1 Navigation

**Stark.** `core/navigation.py` definiert 5 Bereiche (Heute, Akten, Läufe,
Finanzen, Berichte) mit Sektionen, ⌘K-Palette und globaler Suche. Fast alle
Akten und Formulare haben einen Brotkrumenpfad. Befund B1 aus
`UX-ANALYSE-V7.md` ist behoben.

**Brüche:**

- **Bereichskopf = Unterpunkt.** «Akten» führt auf die Liegenschaftsliste,
  «Berichte» und «Übersicht» sind dieselbe URL. Ein Klick auf den
  Bereichskopf zeigt also keine eigene Übersicht.
- **Falscher Brotkrumen.** Die Fall-Akte heisst im Pfad «Arbeit»
  (`fall_detail.html:8`), in der Navigation aber «Heute».
- **Toter Link «Löschbegehren»** (`person_detail.html:131`). Die View
  akzeptiert nur POST und leitet jeden GET zurück. Die DSG-Löschung selbst
  ist über das Formular in Zeile 64 erreichbar, der Link tut aber nichts.
- **Fehlerseiten führen ins Team.** `403.html`, `404.html` und `500.html`
  verlinken fest auf `/neu/`. Mieter und Eigentümer aus dem Portal landen so
  vor einer Anmeldemaske der Verwaltung. Das Favicon dort ist noch das alte
  Indigo (`#4f46e5`).
- **Doppelte Arbeitsliste** (B3 teilweise offen). `finanzen.html:59-86` zeigt
  weiterhin einen eigenen «Arbeitskorb» neben «Heute».

### 2.2 Kernabläufe

| Akte | Liste | Detail | Neu | Bearbeiten | Löschen | Suche / Filter / Sortierung / Seiten |
|---|---|---|---|---|---|---|
| Liegenschaft | ✓ | ✓ | ✓ | ✓ | ✓ | nur Suche im Browser; keine Seiten, keine Sortierung |
| Objekt | ✓ | ✓ | ✓ | ✓ | **fehlt** | Suche über die Kopfzeile; Filter nach Typ und Status |
| Mietverhältnis | ✓ | ✓ | ✓ (Assistent) | ✓ | ✓ | Suche + Status; keine Seiten, keine Sortierung |
| Person | ✓ | ✓ | ✓ | ✓ | ✓ + DSG | Suche + Typ |
| Mandat, Dienstleister | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| Mieterwechsel | ✓ | **keine** (nur Modals) | – | – | – | – |

- **Seiten gibt es nur** bei Debitoren, Kreditoren und Logbuch; eine Sortierung
  nur bei Kreditoren. Ab etwa 300 Objekten wird die Objektliste träge.
- **CSV-Export fehlt** auf allen Kernlisten (B10 offen). Für
  Bewirtschafter, die Excel gewohnt sind, ist das ein Verkaufsargument.
- **Sollstellung und Mahnlauf** sind sauber gebaut: Vorschau, dann POST mit
  Bestätigung.

### 2.3 SaaS-Grundlagen

| Grundlage | Stand | Beleg |
|---|---|---|
| **Formularfehler** | ❌ **grösste Lücke** | Die `fw`-Formulare sind handgeschrieben und werten `request.POST` von Hand aus. **0 Vorlagen** zeigen Feldfehler an. In **176 Codepfaden** folgt auf `messages.error` ein `redirect`: Die Eingaben sind weg. Ungültige Zahlen und Daten werden **stillschweigend als leer gespeichert** (`liegenschaft_crud.py:74-110`: `intval` und `decval` geben bei Fehlern `None` zurück). |
| **GET mit Nebenwirkung** | ❌ | `send_mahnung_email_view` verschickt eine E-Mail, `send_via_docuseal` ruft die DocuSeal-API auf, `update_market_data_view` startet einen Import. Dazu hakt `fw_abnahme_ruege_267a` schon bei GET die Checklisten-Pendenz ab. *(Korrigiert in Etappe 0: Die Annahme, Kautionsbeleg und Rüge erzeugten Dubletten, stimmte nicht — beide legen mit `dedup=True` ab.)* |
| **Ladezustände** | ⚠️ minimal | 0 Skeletons, 0 `aria-busy`. Es gibt nur einen globalen Schutz vor doppeltem Absenden (`base.html:497`), und der sperrt immer den *ersten* Knopf eines Formulars statt des geklickten. Iframe-Modals zeigen beim Laden nichts an. Der GWR-Import läuft synchron im Request. |
| **Modals** | ⚠️ | Die Iframe-Modals (`_fwmodal.html`, 22×) haben kein `role="dialog"`, verwerfen ungespeicherte Eingaben bei Esc ohne Rückfrage und laden die Seite **bei jedem Schliessen neu**, auch beim Abbrechen. |
| **Rückmeldungen** | ✓ solide, ⚠️ Details | Die Toasts oben rechts funktionieren (Erfolg verschwindet nach 6 s, Fehler bleiben). Es fehlt `aria-live`. 196 Meldungen beginnen mit einem Emoji (✅ ❌ 📍), das nicht zum Icon-Satz passt. |
| **Leere Zustände** | ⚠️ 65 % | 60 von 92 Listen-Vorlagen haben einen. Die gute Komponente `_empty.html` (Icon, Titel, Handlungsknopf) nutzen nur 7 Dateien, 33 Stellen sind noch kursive Einzeiler. **Keinen** leeren Zustand haben MWST, Zahllauf, Weiterverrechnung, Massenanpassung und Bewerbervergleich. |
| **Bestätigungen** | ✓ vollständig, ⚠️ Optik | Alle 90 destruktiven Formulare nutzen POST **und** `confirm()`. Löschungen per GET gibt es in `fw` nicht. Nur ist `confirm()` ein Browserdialog, kein gestalteter. |
| **Pflichtfelder** | ⚠️ | Es gibt drei Schreibweisen: `*` im übersetzten Text (49×), `<span class="fw-kritisch">*</span>` und `fw-pflicht` (11×). |
| **Fehlerseiten** | ✓ | 403, 404 und 500 sind eigenständig gestaltet. `DEBUG` ist standardmässig aus. |
| **Übersetzung** | ⚠️ | 12 `fw`-Vorlagen haben noch kein einziges `{% trans %}`, darunter `vertrag_neu`, `kuendigung_form`, `schlussabrechnung` und `mietzins_anpassung`. |

---

## Phase 3 — Gestaltung

### 3.1 Was bereits auf SaaS-Niveau ist

- **Tokens und Dark Mode.** Rund 26 `--ds-*`-Tokens in `fw/_schicht.html`, je
  mit Hell- und Dunkelwert. Der Dark Mode folgt dem Betriebssystem und lässt
  sich umschalten. Die Farben entsprechen dem Konzept v7 (Petrol `#0f6f6a`)
  fast 1:1, und Tests sichern sie ab.
- **Farbmigration** ist nahezu fertig: Es sind nur noch 119 rohe
  Tailwind-Farbklassen in 9 Dateien übrig.
- **Schrift und Icons.** IBM Plex Sans und Mono sind selbst gehostet. 61
  Icons liegen in einem SVG-Sprite und werden 1060× über `{% zeichen %}`
  eingebunden. Font Awesome und Bootstrap sind praktisch verschwunden.
- **Fokus** ist global per `:focus-visible` in Markenfarbe gelöst.

Das ist mehr Fundament, als viele 10k-Produkte haben.

### 3.2 Was fehlt: die Struktur

Die Farbwerkzeuge wurden durch `fw-*`-Farbklassen ersetzt, **nicht durch
Komponenten**. Deshalb sieht jede Seite ein wenig anders aus:

| Element | Befund | Wirkung |
|---|---|---|
| **Buttons** | 328 `<button>`, **145 verschiedene Klassenketten**. Nur 47 % nutzen `fw-btn`, und auch der Primärknopf kommt in vier Varianten mit überschriebenem Padding und Radius. | Die Knöpfe haben je nach Seite unterschiedliche Höhen. |
| **Karten** | `fw-card` in **74 Varianten** plus **178 selbst gebaute Karten** (`rounded-xl border …`). | Die Abstände springen zwischen den Seiten. |
| **Tabellen** | **16 von 107** nutzen `fw-table`. | Zeilenhöhen, Kopfzeilen und Hover-Effekte sind uneinheitlich; das fällt bei datenlastiger Software am stärksten auf. |
| **Eingabefelder** | **159 von 625** nutzen `fw-feld`. Am häufigsten ist die rohe Kette `w-full fw-flaeche2 rounded-lg text-sm px-3 py-2.5` (256×). | Fokus- und Fehlerzustände lassen sich nicht zentral gestalten. |
| **Schriftgrössen** | **470 frei gewählte `text-[..px]`** (`[11px]` 247×, `[10px]` 128×, `[9px]` 48×, `[8px]` 8×). Die Schicht selbst kennt 16 verschiedene Pixelgrössen. | Es gibt **keine Typo-Skala**. 9 und 8 px sind am Telefon kaum lesbar. |
| **Überschriften** | h2 in 21 Varianten, h3 in 24 Varianten. Die vorgesehene Kartenüberschrift `.fw-t` wird nur etwa 9× genutzt. | Die Hierarchie ist unscharf. |
| **Schriftschnitte** | `font-black` (900) steht 79× und `font-extrabold` (800) 32× in den Vorlagen, `.fw-phead h1` setzt 800. **Plex ist aber nur bis 700 ausgeliefert** (`static/fonts/`). | Der Browser zeichnet ein **künstliches Fett**. Seitentitel wirken dadurch verschmiert, genau dort, wo der erste Eindruck entsteht. |
| **Radius** | Die Tokens sind 10 und 7 px, verwendet werden aber `rounded-lg` (8 px, 900×), `rounded-xl` (199×) und `rounded-2xl` (59×). | Die Tokens greifen nicht. |
| **Schatten** | Sechs Stufen gemischt (`shadow-sm` bis `shadow-2xl`); das Token `--ds-shadow` gilt nur in `fw-*`-Klassen. | Die Tiefenwirkung ist nicht einheitlich. |
| **Inline-Stile** | 429 `style=""`-Attribute in 67 Dateien (182 davon in `fw`, z. B. 33 in `vertrag_detail.html`), dazu 36 `<style>`-Blöcke. | Das umgeht die Tokens, auch im Dark Mode. |
| **Micro-Interactions** | 221 `transition`, aber **0 Transitions in der Schicht** selbst; 1× `active:`, 4× `disabled:`. | Die Knöpfe geben beim Drücken kein Feedback, und deaktivierte Zustände sind uneinheitlich. |

### 3.3 Einschätzung

**Nein, das Layout entspricht heute noch nicht einem 10k-SaaS, und zwar
wegen fehlender Gleichförmigkeit, nicht wegen Farbe oder Stil.** Ein
Interessent merkt es nach drei Klicks: Der Knopf ist hier 36 px hoch und dort
40 px, die Tabelle hier dicht und dort luftig, der Titel künstlich fett.
Premium wirkt Software, deren Seiten sich *gleich* anfühlen. Das Fundament
(Tokens, Dark Mode, Icons, Schrift) steht. Es fehlt eine
**Komponentenschicht**, die es erzwingt.

Die Guard-Tests prüfen heute nur Farben. Radius, Abstände, Typo-Skala und die
Nutzung der Komponenten prüft niemand, deshalb driftet es.

---

## Aktionsplan (priorisiert)

### Etappe 0 — Vertrauen & Korrektheit (klein, zuerst)

Das sind Fehler, keine Gestaltungsfragen. Rund 1–2 Tage, ein PR.

1. **GET-Nebenwirkungen beseitigen:** Mahnungsversand per Mail, DocuSeal-Versand,
   Marktdaten-Import und Rüge 267a verlangen POST. *(Umgesetzt: `send_mahnung_mail`
   bleibt als Route, aber nur per POST — gelöscht wird eine funktionierende
   Versandstelle erst auf Entscheid.)*
2. Den toten Link «Löschbegehren» und den Brotkrumen «Arbeit» korrigieren;
   Fehlerseiten nach Kontext (Portal oder Team) verlinken lassen und das
   Favicon tauschen.
3. Tote Endpunkte entfernen: A3 (Admin-Knopf), A4. *(A2 bleibt bewusst stehen:
   Die Endpunkte sind getestet und schreiben `VertragMietzins`, das die
   Sollstellung liest — ob der Weg stirbt oder wieder eine Oberfläche bekommt,
   ist ein fachlicher Entscheid.)*

### Etappe 1 — Verwaiste Funktionen anschliessen (Quick Wins)

Rund 2–3 Tage. Grosser Nutzen, weil die Logik schon fertig ist.

1. **Bewerbungslink** (F1): In Vermarktung und Ausschreibung «Link kopieren»
   und einen QR-Code anbieten, im Exposé-PDF den QR-Code.
2. **Rüge 267a** (F2): Knopf in `abnahme_detail.html`, sobald dem Mieter
   zugeordnete Mängel erfasst sind, mit deutlichem Hinweis auf die Frist.
3. **Lebensdauertabelle** (F3) als Kachel in den Einstellungen,
   **Hausaushang** (F4) als Aktion in der Liegenschaftsakte.
4. Fallakte → Akte verlinken (Rest von F5). F6 entfällt (siehe Tabelle).

*Umgesetzt auf Branch `audit-fixes-ui`. Zusätzlich geschärft:
`core/tests/test_erreichbarkeit.py` lässt Verweise aus der eigenen Vorlage und
der eigenen Ansicht nicht mehr als «Weg» gelten — genau diese Lücke hatte die
Lebensdauertabelle unsichtbar gemacht.*

### Etappe 2 — Formulare, die Fehler zeigen (grösster UX-Hebel)

Rund 1–2 Wochen. Pilot an der Liegenschaft, danach Objekt, Person,
Mietverhältnis und Kreditor.

- Die handgeschriebene POST-Auswertung durch Django-Forms ersetzen: bei
  Fehlern **neu rendern statt umleiten**, Eingaben behalten, Fehler am Feld
  anzeigen. Ungültige Zahlen oder Daten dürfen nie mehr stillschweigend als
  leer gespeichert werden.
- Dafür ein Feld-Partial `_feld.html` (Label, Pflichtmarke, Hilfetext,
  Fehler, `aria-invalid`). **Das ist zugleich der Einstieg in Etappe 3**:
  Jedes umgebaute Formular wandert damit auf `fw-feld`.

*Stand 29.09.2026 (Branch `audit-fixes-ui`): Liegenschaft, Objekt und Kreditor
umgestellt (`portfolio/forms.py`, `finance/forms.py`, gemeinsames Feld
`core/formfelder.py`, Bausteine `fw/_feld.html` und `fw/_feldfehler.html`).
Beim Kreditor behoben: ein unlesbares Rechnungsdatum war ein Serverfehler, ein
unlesbarer MWST-Satz wurde still 0 %. Offen: Person (`core/views/fw/person.py`
wird parallel für die Korrespondenzsprache umgebaut — erst danach) und
Mietverhältnis (Vertragsassistent, eigener Schritt).
Beim Bau gemessen: `type="number"` verwirft Fehleingaben im Browser, deshalb
`inputmode`; `core/forms.py` baut beim Import eine mandantenabhängige Queryset
(`SchadenForm`) und wird deshalb nicht importiert.*

*Nachtrag Person (`crm/forms.py`): Ein unlesbares Geburtsdatum,
Bewilligungsende oder Bonitätsdatum wurde still leer gespeichert — eine
ablaufende Aufenthaltsbewilligung fiel so aus jeder Frist heraus. Eine
unlesbare Personenzahl wurde still 0, die IBAN des abweichenden Zahlers blieb
ungeprüft (ein bestehender Test speicherte `CH..`), ein zu langer Text wäre
auf PostgreSQL ein Serverfehler gewesen. Jetzt: Status 400, Hinweis am Feld,
Zusammenfassung oben, Eingaben bleiben stehen. Schweizer PLZ vierstellig,
ausländische frei. Dabei gefunden: Die Feldmeldungen der Etappe-2-Formulare
waren nie übersetzt, weil der Übersetzungswächter `_t('…')` nicht erkannte;
beides nachgeholt.*

*Nachtrag Mietverhältnis (`rentals/forms.py`):
- «Vertrag bearbeiten»: Ein unlesbares Vertragsende wurde still leer — bei
  einem aktiven Vertrag folgt die Befristung dem Ende, aus befristet wurde
  so unbefristet. Unlesbare Frist oder Personenzahl blieben still beim alten
  Wert, im Entwurf wurde ein unlesbarer Nettomietzins CHF 0. Jetzt Status
  400 mit Hinweis am Feld; Ende vor Beginn wird abgelehnt; Beträge mit der
  Stellenzahl des Modells. Die Kürzung einer Index-Weitergabe über 100 %
  bleibt (Entscheid E2.53).
- Assistent: Unlesbare Eingaben wurden still ersetzt — Referenzzinssatz
  1.25 %, LIK-Stand 107.1, Mietbeginn heute, Nettomiete 0; eine unlesbare
  Personenzahl war ein Serverfehler. Jetzt wird vor jeder Änderung
  abgelehnt; leere Felder behalten ihre Vorgabe.
Offen: Der Assistent meldet Fehler weiterhin oben und lädt leer neu (Umbau
seiner Oberfläche ist ein eigener Schritt; im Browser verhindern die
Zahlen- und Datumsfelder die meisten Fehleingaben schon vorher).*

### Etappe 3 — Komponentenschicht & Typo-Skala («der 10k-Look»)

Rund 2–3 Wochen, seitenweise.

1. **Typo-Skala** mit 6 Stufen (z. B. 12 / 13 / 14 / 16 / 20 / 26 px) als
   Tokens; die 470 frei gewählten Grössen auf die Skala abbilden; 800/900 auf
   700 senken (oder Plex ExtraBold ausliefern). Das ist der **schnellste
   sichtbare Gewinn**.
2. **Komponenten als Include-Partials:** Button (primär, sekundär, Gefahr,
   Geist; je 2 Grössen), Karte mit Kopf, Tabelle, Badge, Seitenkopf, leerer
   Zustand. Die Radius- und Schatten-Tokens werden in diesen Komponenten
   verbindlich.
3. **Gestalteter Bestätigungsdialog** statt `confirm()`; Modal mit
   `role="dialog"`, Ladezustand und ohne Neuladen beim Abbrechen; Toasts mit
   `aria-live`; Emojis aus den Meldungen entfernen.
4. **Guard-Tests erweitern** (wie bei den Farben): Anzahl der
   `text-[..px]`, der Inline-Stile und der Button-Varianten darf nur sinken.

*Stand 29.09.2026 (Branch `audit-fixes-ui`), Teil 1 umgesetzt:
- Schriftgewichte: `font-black`/`font-extrabold` und `font-weight:800` → 700 in
  allen Vorlagen und der Schicht. Ausgenommen die zwei Font-Awesome-Glyphen der
  Schicht (Solid IST 900). Offen: eigene `<style>`-Blöcke der Anmeldeseiten.
- Kleine Schriftgrade: 422 frei gewählte `text-[Npx]` in `fw/` auf vier Stufen
  (`fw-fs-mikro` 10 · `fw-fs-klein` 11 · `fw-fs-fein` 13 · `fw-fs-text` 14 px);
  49 Stellen ausserhalb von `fw/` (Portal, PDF, E-Mail) bewusst noch nicht.
- Nebenbefund behoben: `fw/base_embed.html` (Modals) lud weder Stilschicht noch
  Icon-Sprite — ungestaltet und 570 px breit am Telefon.
Offen: Teile 2–4 (Komponenten, Bestätigungsdialog/Modal/Toasts, Wächter für
Radius und Inline-Stile).*

### Etappe 4 — Listen-Werkzeugkasten

Seiten, Sortierung und CSV-Export für Liegenschaften, Objekte,
Mietverhältnisse und Personen; die fehlenden leeren Zustände nachrüsten.

*Stand 29.09.2026, Pilot Liegenschaften umgesetzt:
- Baustein `core/views/fw/_liste.py` (Suche, Sortierung, Seiten, CSV) und
  Blätterleiste `fw/_seiten.html`. Die Reihenfolge ist fest: alle Zeilen →
  Suche → Befundfilter → Sortierung → CSV oder Seite.
- Liegenschaften: Suche auf dem Server (Strasse, PLZ, Ort, Kanton,
  Eigentümer; mehrere Wörter grenzen ein), Sortierung nach Befund, Adresse,
  Ort, Anzahl Objekte und Ist-Miete (Hausnummern als Zahlen), Seiten zu 50,
  CSV im Menü «Mehr» mit denselben Filtern, aber allen Zeilen. Die CSV-Datei
  ist für Excel aufbereitet (Semikolon, BOM, Beträge mit Punkt) und
  entschärft Zellen, die mit `=`, `+`, `-` oder `@` beginnen (Formeln).
- Chips, Blättern und Suche behalten die übrigen Parameter; ein Wechsel
  beginnt wieder auf Seite 1. Die Chip-Zahlen folgen der Suche.
- Nebenbefund behoben: Die Zeile las den Eigentümer mit einer Abfrage je
  Liegenschaft (`select_related` fehlte).
Danach die übrigen drei Listen:
- Gemeinsame Werkzeugleiste `fw/_listwerkzeug.html` (Suche, Sortierung,
  «Anwenden»). Der Baustein sortiert und blättert jetzt auch Abfragen in der
  Datenbank (`Sortierung.felder`), jede Sortierung endet mit `id`, damit
  Seiten stabil bleiben.
- Mietverhältnisse: Sortierung nach Beginn, nächstem Ende, Mieter, Objekt,
  höchster Miete; Seiten zu 50; die Kopfzahlen zählen über die Abfrage,
  nicht über die Seite; CSV mit Netto, Nebenkosten, Brutto und Status.
- Personen: Sortierung nach Name, Ort, zuletzt erfasst; Seiten zu 50; CSV
  bewusst nur mit Kontaktdaten (keine AHV-Nummer, kein Einkommen, keine
  Bankverbindung) und mit Eintrag im Logbuch. Der eigene Sofortfilter im
  Browser ist durch den gemeinsamen ersetzt und greift nur, solange alles
  auf einer Seite steht.
- Objekte: Gruppierung nach Liegenschaft und kein zweites Suchfeld bleiben
  (Entscheid G9). Geblättert wird in ganzen Liegenschaften (20 je Seite),
  damit eine Gruppe nie auf zwei Seiten zerfällt; CSV aller Objekte.*

---

### Empfehlung: womit beginnen

**Etappe 0 und 1 zusammen als erster PR.** Sie sind klein, risikoarm und
schliessen echte Lücken, darunter einen Mahnungsversand per GET und einen
Vermietungstrichter ohne Eingang. Danach **Etappe 2 am Pilot Liegenschaft**,
weil sie die grösste Frustquelle im Alltag behebt und die Feldkomponente für
Etappe 3 gleich mitbringt. Die Typo-Skala aus Etappe 3.1 kann parallel
laufen: Sie ändert fast nur CSS und wirkt sofort auf jede Seite.
