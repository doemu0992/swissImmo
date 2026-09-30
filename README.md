# swissImmo

Webanwendung für die **Verwaltung von Schweizer Mietliegenschaften** — für
Immobilienverwaltungen, die Mandate, Liegenschaften, Mietverhältnisse und die
dazugehörige Buchhaltung an einem Ort führen wollen.

Gebaut mit **Django 5.2** (Python 3.11), serverseitig gerenderten Vorlagen mit
Tailwind CSS und Alpine.js, einer kleinen REST-Schnittstelle über
**django-ninja** und PDF-Erzeugung mit xhtml2pdf/ReportLab. Daten liegen in
SQLite (Standard) oder PostgreSQL. Die Anwendung ist mandantenfähig: mehrere
Verwaltungen (Organisationen) arbeiten strikt getrennt in derselben Instanz.

## Was die Anwendung kann

| Bereich | Inhalt |
|---|---|
| **Arbeitsvorrat** | Dashboard, Pendenzen, Fristen (automatisch aus Verträgen), Termine, Vertretungen |
| **Bestand** | Mandate, Liegenschaften (inkl. GWR-Import), Objekte, Mietverhältnisse, Personen, Dienstleister |
| **Vermietung** | Mieterwechsel, Vermarktung, Bewerbungen, Kündigungs- und Mietzins-Assistenten mit amtlichen Formularen |
| **Finanzen** | Sollstellung, QR-Rechnungen, Bankabgleich (camt.053 und CSV), Mahnwesen, Zahllauf (pain.001), Nebenkostenabrechnung, Mietzinsanpassung (Referenzzins/LIK), MWST, Kautionen, Debitoren/Kreditoren, doppelte Buchhaltung mit Kontenplan, Anlagen & Jahresabschluss, Hypotheken |
| **Gebäude** | Schadensmeldungen, Ersatzplanung & Ausstattung, Versicherungen |
| **Portale** | Eigentümer-Portal (Berichte, Steuerauszug, Freigaben), öffentliche Schadensmeldung für Mieter |
| **Kommunikation** | E-Mail-Versand, Posteingang per IMAP, optionale digitale Signatur (DocuSeal) |
| **Sicherheit** | Rollen je Organisation (Inhaber, Verwalter, Sachbearbeiter, Lesezugriff), Zwei-Faktor-Anmeldung, geschützte Uploads, DSG-Anonymisierung |
| **Sprachen** | Deutsch, Französisch, Italienisch, Englisch (Übersetzung laufend) |

---

## Voraussetzungen

- **Python 3.11** (die CI testet gegen 3.11)
- **git**
- Für `pycairo` (PDF-Erzeugung) die Cairo-Entwicklungsdateien und ein C-Compiler:
  - Debian/Ubuntu: `sudo apt install build-essential python3-dev pkg-config libcairo2-dev`
  - macOS (Homebrew): `brew install cairo pkg-config`
  - Windows: nichts zusätzlich — pip bringt fertige Pakete mit
- Optional: **PostgreSQL 14+** für den Produktivbetrieb
- Optional: **Node.js 22** — nur für die E2E-Tests und um das CSS neu zu bauen
  (das fertige CSS liegt bereits in `static/css/`)

## Installation

```bash
# 1. Repository holen
git clone https://github.com/doemu0992/swissImmo.git
cd swissImmo

# 2. Virtuelle Umgebung anlegen und aktivieren
python3.11 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 3. Abhängigkeiten installieren
pip install --upgrade pip
pip install -r requirements.txt
# für Entwicklung zusätzlich (Linter):
pip install -r requirements-dev.txt

# 4. Konfiguration anlegen
cp .env.example .env
```

Öffnen Sie danach `.env` und setzen Sie für die **lokale Entwicklung**:

```ini
DEBUG=True
```

Mehr ist für den ersten Start nicht nötig. Alle anderen Werte sind optional
(siehe [Konfiguration](#konfiguration)). Ohne `SECRET_KEY` erzeugt die Anwendung
beim ersten Start einen und legt ihn in `.secret_key` ab.

```bash
# 5. Datenbank anlegen (SQLite, Datei db.sqlite3)
python manage.py migrate

# 6. Erste Verwaltung mit Inhaber-Konto anlegen
python manage.py organisation_anlegen \
    --firma "Muster Verwaltung AG" \
    --benutzer admin \
    --email admin@example.ch \
    --passwort "EinSicheresPasswort!"
```

`organisation_anlegen` legt die Organisation, das Konto mit der Rolle
**Inhaber**, den Kontenplan und Startwerte für Referenzzins und LIK an. Mit
`--probe` sehen Sie vorher, was geschehen würde.

## Starten

```bash
python manage.py runserver
```

Dann im Browser <http://127.0.0.1:8000/login/> öffnen und mit dem eben
angelegten Konto anmelden. Sie landen im Dashboard unter `/neu/`.

| Adresse | Zweck |
|---|---|
| `/login/` | Anmeldung für das Verwaltungsteam |
| `/neu/` | Hauptanwendung (Dashboard und alle Module) |
| `/portal/` | Eigentümer-Portal |
| `/admin/` | Django-Admin (nur für Superuser, Notfallzugang) |
| `/healthz/` | Zustandsprüfung für Monitoring |
| `/api/` | REST-Schnittstelle (Session-Anmeldung, rollenbasiert) |

## Nutzung — ein erster Durchgang

1. **Einstellungen → Account**: Stammdaten der Verwaltung, Logo, Absender und IBAN erfassen.
2. **Liegenschaften → Neu**: Liegenschaft mit ihrem Mietzinskonto (IBAN) anlegen —
   ohne IBAN und vollständige Mieteradresse entsteht kein QR-Einzahlungsschein.
   Mit dem GWR-Import lassen
   sich Gebäudedaten aus dem eidgenössischen Register übernehmen.
3. **Objekte**: Wohnungen, Parkplätze und Gewerbeflächen der Liegenschaft erfassen.
4. **Personen**: Mieter und Eigentümer anlegen.
5. **Mietverhältnisse → Neu**: Vertrag mit Mietzins, Nebenkosten, Kaution.
6. **Sollstellung**: Monatliche Mietzinsrechnungen mit QR-Einzahlungsschein erzeugen.
7. **Bankabgleich**: camt.053- oder CSV-Auszug der Bank hochladen — Zahlungen werden den
   offenen Rechnungen zugeordnet.
8. **Mahnwesen / Nebenkosten / Mietzins**: Läufe starten, Dokumente als PDF erzeugen.
9. **Einstellungen → Benutzer & Rollen**: Kolleginnen und Kollegen mit passender Rolle anlegen.

### Wiederkehrende Aufgaben

Ein einziger täglicher Lauf (Cron, Scheduled Task o.ä.) genügt:

```bash
python manage.py taeglicher_lauf
```

Er erzeugt Fristen-Pendenzen, aktualisiert Referenzzins und LIK und verschickt
das wöchentliche Fristen-Mail. Weitere nützliche Befehle:

```bash
python manage.py monatslauf               # monatliche Sollstellung
python manage.py mahnlauf                 # Mahnungen erzeugen
python manage.py sicherung                # Datenbank + Uploads sichern (docs/SICHERUNG.md)
python manage.py datenbank_pruefen        # Konsistenzprüfung
python manage.py pruefe_webhook_secrets   # sind die Webhook-Secrets gesetzt?
python manage.py help                     # alle Befehle
```

## Konfiguration

Alle Einstellungen kommen aus Umgebungsvariablen oder der Datei `.env`. Die
vollständige, kommentierte Liste steht in [`.env.example`](.env.example).
Die wichtigsten:

| Variable | Zweck |
|---|---|
| `DEBUG` | `True` nur lokal. In Produktion `False` (erzwingt HTTPS und sichere Cookies) |
| `SECRET_KEY` | In Produktion zwingend fest setzen |
| `EXTRA_ALLOWED_HOSTS`, `EXTRA_CSRF_ORIGINS` | Eigene Domain freischalten |
| `DB_ENGINE=postgres` + `DB_*` | PostgreSQL statt SQLite (siehe `docs/UMZUG-POSTGRESQL.md`) |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP-Versand |
| `IMAP_SCHLUESSEL` | Fernet-Schlüssel für Postfach-Zugangsdaten UND AHV-Nummern (verschlüsselt gespeichert). Nach dem Deploy einmal `python manage.py ahv_verschluesseln` |
| `GROQ_API_KEY` | Optional: KI-Belegerkennung für Kreditorenrechnungen |
| `DOCUSEAL_API_KEY` | Optional: digitale Vertragsunterzeichnung |

Externe Dienste sind **optional**. Ohne Schlüssel läuft die Anwendung
vollständig; die jeweilige Funktion ist dann ausgeblendet oder meldet, dass sie
nicht eingerichtet ist.

## Tests und Prüfungen

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
ruff check .
python manage.py test --parallel 8        # ca. 2'500 Tests, rund 5 Minuten
```

Schlägt ein Test unter `--parallel` fehl und die Meldung lautet nur
`cannot pickle 'traceback' object`, den betroffenen Test ohne `--parallel`
wiederholen — dann erscheint die eigentliche Ursache.

E2E-Tests mit Playwright (bootet Django selbst gegen eine eigene Datenbank):

```bash
npm install
npx playwright install chromium
npm run e2e
```

CSS neu bauen, nachdem Vorlagen neue Tailwind-Klassen verwenden:

```bash
npm run css:alle
```

## Betrieb

- **PythonAnywhere**: `deploy.sh` holt den Stand, installiert, migriert, sammelt
  statische Dateien und lädt die Web-App neu (Aufruf und Optionen im Dateikopf).
- **Andere Server**: wie jede Django-Anwendung per WSGI (`swiss_immo/wsgi.py`),
  vorher `python manage.py collectstatic`, `DEBUG=False` und einen festen
  `SECRET_KEY` setzen. `staticfiles/` und `media/` vom Webserver ausliefern
  lassen — `media/` **nicht** öffentlich, Uploads laufen über geschützte Views.
- **Sicherung und Wiederherstellung**: `docs/SICHERUNG.md`.

## Projektaufbau

```
swiss_immo/    Settings, URLs, WSGI
core/          Zentrale: Views (core/views/fw = Hauptoberfläche), Dienste, Mandantentrennung, Tests
benutzer/      Benutzermodell
crm/           Organisationen, Mitgliedschaften, Personen
portfolio/     Liegenschaften und Objekte
rentals/       Mietverträge
finance/       Rechnungen, Buchhaltung, Zahlungsverkehr
tickets/       Schadensmeldungen
mietprozess/   Bewerbungen und Mieterwechsel
faelle/        Fall- und Regelwerk (Fristen nach OR)
locale/        Übersetzungen (de/fr/it/en)
docs/          Architektur-, Planungs- und Betriebsdokumente
e2e/           Playwright-Tests
```

Hintergrund zu Architektur und Entscheiden: `docs/ANALYSE.md`,
`docs/KONZEPT-UI.md`, `docs/PHASE-2-ABSCHLUSS.md`.
