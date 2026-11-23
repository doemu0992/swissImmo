# immoswiss

Web-Anwendung für Schweizer Immobilienverwaltungen: Mandate, Liegenschaften, Mietverhältnisse und die dazugehörige
Buchhaltung an einem Ort. Die Anwendung ist mandantenfähig — mehrere Verwaltungen arbeiten strikt getrennt in
derselben Installation — und wird als Monatsabo betrieben; neue Kunden schaltet der Betreiber im Betreiber-Portal frei.

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — wie die Anwendung gebaut ist: Aufbau, Mandantentrennung, Abläufe, Sicherheit, Betrieb.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — Regeln für Änderungen: Ablauf, Namen, Design, Tests.

## Was die Anwendung kann

| Bereich | Inhalt |
|---|---|
| Arbeitsvorrat | Startseite «Heute», Pendenzen, Fristen (automatisch aus Verträgen), Termine, Fälle |
| Bestand | Mandate, Liegenschaften, Objekte, Mietverhältnisse, Personen, Dienstleister, Dokumente |
| Vermietung | Mieterwechsel, Vermarktung, Bewerbungen, Kündigung und Mietzinsanpassung mit amtlichen Formularen |
| Finanzen | Sollstellung, QR-Rechnungen, Bankabgleich (camt und CSV), Mahnwesen, Betreibung, Zahllauf (pain.001), Nebenkostenabrechnung, MWST, Kautionen, doppelte Buchhaltung, Jahresabschluss |
| Kommunikation | Mitteilungen und Rundschreiben mit Live-Vorschau, Vorlagen mit Platzhaltern, Serienbrief-PDF, E-Mail, Einschreiben; Ablage in der Akte, Fristen automatisch im Fristen-Center |
| Gebäude | Schadenmeldungen (auch per QR-Aushang), Handwerker-Aufträge, Ersatzplanung, Zähler, Schlüssel |
| Stockwerkeigentum | Beschlüsse, Budget, Erneuerungsfonds, Abstimmung, Inkasso |
| Portale | Mieterportal, Eigentümerportal, Handwerker-Zugang per Link |
| Betrieb der Plattform | Betreiber-Portal: Kunden, Abonnemente, zentrales Protokoll |
| Sicherheit | Rollen je Verwaltung, Zwei-Faktor-Anmeldung, verschlüsselte Geheimnisse, Auskunft und Anonymisierung nach DSG |
| Sprachen | Deutsch, Französisch, Italienisch, Englisch |

## Voraussetzungen

- Python 3.11 (die CI testet gegen 3.11)
- Optional PostgreSQL 16 (Produktion; lokal genügt SQLite)
- Optional Node.js 22 — nur für die E2E-Tests und um das CSS neu zu bauen

## Einrichten

```bash
git clone https://github.com/doemu0992/swissImmo.git
cd swissImmo
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt        # Entwicklung: Linter

cp .env.example .env                       # lokal: DEBUG=True setzen
python manage.py migrate
python manage.py organisation_anlegen --firma "Muster Verwaltung AG" --benutzer chef --email chef@example.ch --passwort "…"
python manage.py runserver                 # http://127.0.0.1:8000/login/ — danach /neu/
```

Mit `DEBUG=False` leitet die Anwendung auf HTTPS um und setzt sichere Cookies; über `http://127.0.0.1` ist dann keine
Anmeldung möglich. Ohne `SECRET_KEY` und ohne `GEHEIMNIS_SCHLUESSEL` legt die Anwendung beide selbst an (Dateien
`.secret_key` und `.geheimnis_schluessel`, nicht im Repository).

## Prüfen

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
ruff check .
python manage.py test --noinput --parallel 4      # rund 7'600 Tests, einige Minuten

npm install && npx playwright install chromium
npm run e2e                                       # Browser-Tests; startet den Testserver selbst
```

Tests gegen PostgreSQL: `DB_ENGINE=postgres` und die `DB_*`-Variablen setzen, dann `migrate` und `test`.

## Bauen

```bash
npm run css                        # Tailwind neu bauen (nur nach neuen Utility-Klassen)
python manage.py schicht_bauen     # nach jeder Änderung an core/templates/fw/_schicht.html
```

Übersetzungen: Texte mit `makemessages` einsammeln, übersetzen, `compilemessages`; die `.mo`-Dateien gehören ins
Repository (Einzelheiten in [CONTRIBUTING.md](CONTRIBUTING.md)).

## Betrieb

Produktion läuft auf PythonAnywhere mit PostgreSQL. Eingespielt wird mit `bash deploy.sh`. Welche Dauerläufer und
geplanten Aufgaben nötig sind, wie gesichert, wiederhergestellt und der Schlüssel gewechselt wird, steht in
[ARCHITECTURE.md](ARCHITECTURE.md), Abschnitt «Betrieb».

Konfiguration über Umgebungsvariablen: Vorlage `.env.example`, vollständige Liste in `swiss_immo/settings.py`.
