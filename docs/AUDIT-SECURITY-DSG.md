# Auditbericht — Sicherheit und Datenschutz (revDSG)

**Datum:** 30.09.2026
**Bereich:** ganze Codebasis, Schwerpunkt öffentliche Endpunkte, Portale, Uploads, sensible Felder
**Umsetzung:** PR #71 (Commit `7066475`), Tests in `core/tests/test_pentest_dsg.py`

---

## Zusammenfassung

| Stufe | Anzahl | Status |
|---|---|---|
| **Hoch** | 3 | behoben |
| **Mittel** | 4 | behoben |
| **Niedrig** | 1 | behoben |
| **Betrieb (Hoster)** | 1 | behoben (nicht im Code) |
| **Bewusst offen** | 5 | siehe unten |

Die Mandantentrennung und der Zugriffsschutz für Dateien (Audit vom 18.08.2026) hielten
den simulierten Angriffen stand. Die Lücken lagen an den **öffentlichen Rändern**
(Login, anonyme Formulare, Schnittstellenbeschreibung) und bei **einem Klartextfeld**.

---

## Daten-Audit

**Bereits geschützt**
- Postfach-Passwörter und Refresh-Tokens: Fernet (`core/services/geheimnis.py`).
- Uploads: nur über `geschuetzte_media`, mit Rollen- und Mandantenprüfung, 404 statt 403.
- JSON-Antworten (Palette, Version, Health): keine Passwörter, AHV, IBAN.
- Templates: kein `|safe` auf Benutzereingaben.

**Im Klartext (Stand nach Audit)**
- IBAN, Zahler-IBAN, Einkommensspanne, Betreibungsergebnis: bleiben, weil die IBAN für
  den Bankabgleich gesucht wird und die übrigen Felder angezeigt und gefiltert werden.
- Dokument-Dateien (Ausweis, Lohnausweis, Betreibungsauszug): unverschlüsselt auf dem
  Datenträger, geschützt nur durch die Zugriffsprüfung.

---

## Befunde und Behebung

### Hoch

**S1 — Login ohne Brute-Force-Schutz** (`core/views/zweifaktor.py`)
Passwörter waren unbegrenzt durchprobierbar; nur der zweite Schritt war begrenzt.
Jetzt: Sperre nach 10 Fehlversuchen je Benutzername und 30 je IP (15 Minuten,
Status 429, auch mit richtigem Passwort). Fehlversuche stehen im Sicherheitslog.

**S2 — Offener Redirect über `next`** (`core/views/zweifaktor.py`)
`/login/?next=https://fremd.example` leitete nach dem Login auf die fremde Seite.
Jetzt wird `next` nur für Adressen dieser Anwendung übernommen, auch nach dem zweiten Faktor.

**S3 — Anonymes Bewerbungsformular nahm beliebige Dateien an** (`mietprozess/api.py`)
Typ, Inhalt und Grösse wurden nicht geprüft (HTML, SVG, beliebig gross).
Jetzt: nur PDF und Bild, Inhalt geprüft (`%PDF-` bzw. Pillow), höchstens 10 MB
(`core/utils/uploads.py`, `validiere_dokument`).

### Mittel

**S4 — Ausnahmetexte an Anonyme.** Das Bewerbungsformular, der Brevo-Webhook und die
PDF-Views gaben `str(e)` zurück (Tabellen, Spalten, Pfade). Jetzt generische Meldung,
Einzelheiten im Server-Log.

**S5 — Rate-Limit umgehbar** (`core/utils/throttle.py`). `client_ip` nahm den linken
`X-Forwarded-For`-Eintrag, den der Client frei setzt. Jetzt der rechte, den der Proxy anhängt.

**S6 — Schadenformular ohne Ratenbegrenzung** (`core/views/ticket_public.py`).
Jetzt 10 Meldungen je IP und Stunde.

**S7 — AHV-Nummer im Klartext** (`crm.Mieter.ahv_nummer`).
Jetzt `VerschluesseltesCharField` (`core/verschluesselt.py`, Fernet, Schlüssel
`IMAP_SCHLUESSEL`). Migration `crm.0046` verschlüsselt den Bestand, sofern der Schlüssel
gesetzt ist; sonst holt `manage.py ahv_verschluesseln` es nach. Ohne Schlüssel wird nie im
Klartext gespeichert, das Personenformular zeigt eine Meldung. Startwarnung `core.W002`.
Alt-Klartext bleibt lesbar und wird beim Speichern verschlüsselt. Filtern nach dem Feld
findet nichts (Zufallswert je Verschlüsselung) — gewollt.

### Niedrig

**S8 — `/api/openapi.json` anonym abrufbar** (`swiss_immo/urls.py`), obwohl der Kommentar
das Gegenteil sagte. Es beschrieb jedes Feld des Bewerbungsformulars. Jetzt `openapi_url=None`.

### Betrieb (nicht im Code)

**S9 — statisches `/media/`-Mapping bei PythonAnywhere.** Der Webserver lieferte alle
Uploads direkt aus und umging damit `geschuetzte_media`: Wer den Pfad einer Ausweiskopie
kannte, konnte sie ohne Login laden. Am 30.09.2026 im Web-Tab entfernt; `/media/` ohne
Login liefert seither 404. Da die Dateien bis dahin frei abrufbar waren, gehört ein Blick
in `access.log` auf fremde Zugriffe auf `/media/bewerbungen/` zur Nacharbeit.

---

## Simulierte Angriffe (bestanden)

- **IDOR:** Mieter A gegen Mieter B (gleiche und andere Verwaltung): Dokument,
  QR-Rechnung, Kündigungsbrief, Ticket lesen und beschreiben → 404. Portal-Login erreicht
  keine Team-Seiten. Team A erreicht Vertrag, Mieter, Dossier von B nicht. ID-Durchprobieren
  liefert nie fremde Daten.
- **SQL-Injection:** zehn Payloads gegen Palette und sieben Listen (`q`, `sort`, `seite`,
  `filter`): keine Fehler, keine fremden Daten, Tabellen intakt. `%%` und `_%` wirken
  wörtlich. Ursache: ORM, Sortierung auf Whitelist.

**Gegenprobe:** Ohne die Fixes werden 15 der 30 Tests rot; die IDOR- und Injection-Tests
waren schon vorher grün (Regressionstests für bestehende Schutzschichten).

---

## Bewusst offen

| # | Thema | Grund |
|---|---|---|
| O1 | Dokument-Dateien unverschlüsselt | Infrastrukturentscheidung (Festplatten-/Hoster-Verschlüsselung oder verschlüsselnder Speicher) |
| O2 | IBAN, Einkommen, Betreibungsstatus im Klartext | IBAN wird gesucht; Option: gehashtes Suchfeld neben verschlüsseltem Feld |
| O3 | Webhook-Token in `?token=` weiter akzeptiert | bestehende DocuSeal-/Brevo-Konfigurationen; Ziel: nur `X-Webhook-Secret`, dann URL-Variante entfernen (Token stehen sonst in Logs) |
| O4 | Rate-Limits im lokalen Cache je Prozess | bei mehreren Workern weicher als konfiguriert; harte Limits brauchen geteilten Cache |
| O5 | `IMAP_SCHLUESSEL` gilt jetzt auch für AHV | Verlust = AHV-Nummern unlesbar; Kopie ausserhalb des Servers halten |

---

## Prüfungen

- Testsuite grün (App-Suites 706, `core`-Blöcke in fünf Läufen), `ruff` sauber,
  `makemigrations --check` ohne Änderungen.
- Produktion: `migrate` ohne offene Migrationen, `ahv_verschluesseln` → 1 Altwert
  verschlüsselt, `check` ohne `core.W002`, `/media/` ohne Login → 404.
