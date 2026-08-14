# E1 — Die alte SPA entfernen

**Stand:** 14.08.2026
**Grundlage:** `docs/PHASE-2-PLAN.md` (Entscheid E1), `docs/ANALYSE.md` (TS-6, TS-7)
**Basis:** `main`
**Agent:** `aufraeumer` — Nachweispflicht gilt für **jede** Datei

---

## Warum das der grösste Hebel ist

Die `/neu/`-Oberfläche ruft die API nicht auf. Von 82 Endpunkten bedienen zwei etwas, das bleiben muss; die übrigen 80 existieren nur für die abgelöste Vue-SPA unter `/app/`.

Mit ihnen fällt der ID-Offset-Hack aus TS-6 weg — `id + 10000` mit Rückrechnung beim Löschen, an vier Stellen, alle in SPA-Code. Damit erledigt sich ein Befund, ohne dass jemand die beiden `Dokument`-Modelle anfassen muss.

Und es halbiert die Fläche für alles Folgende: Jede Isolationsregel, jedes Entitlement und jede Übersetzung muss danach durch **eine** Oberfläche statt durch zwei.

---

## Ein Befund vorweg, der die Aufgabe verändert

**Die `api.py`-Dateien sind keine reine API-Schicht.** In `finance/api.py` liegt `erstelle_storno_buchung` — und die Funktion wird an **vier Stellen aus `core/views/fw.py`** importiert, mit acht Aufrufen. Das ist Fachlogik der `/neu/`-Oberfläche, die zufällig im API-Modul wohnt.

Wer `finance/api.py` löscht, bricht die Stornobuchung in der laufenden Anwendung.

Zusätzlich greifen die Tests direkt in die API-Module: `finance.api.pay_kreditor`, `finance.api.create_zahlung`, `finance.api.import_standard_kontenplan`, `rentals.api.verarbeite_docuseal_event`, `rentals.api._vertrag_id_aus_name`, `rentals.api._erster_dokument_url`, `rentals.api.docuseal_webhook`. Diese Funktionen sind teils Endpunkte, teils Hilfsfunktionen — das ist vor dem Löschen je Fall zu unterscheiden.

**Deshalb ist E1 kein Löschauftrag, sondern drei PRs.** Der erste bewegt Code, ohne etwas zu entfernen.

---

## E1a — Fachlogik aus den API-Modulen herausziehen

Reiner Umzug. Kein Verhalten ändert sich, keine Zeile Logik wird angefasst.

Jede Funktion in einem `api.py`, die **kein** Endpunkt ist (also ohne `@router`-Dekorator) und von ausserhalb des eigenen Moduls verwendet wird, wandert in ein Servicemodul — `finance/services.py`, `rentals/services.py` und so weiter, passend zur bestehenden Struktur (`core/services/` ist bereits so organisiert).

Bekannt sind:

| Funktion | Herkunft | Verwendet von |
|---|---|---|
| `erstelle_storno_buchung` | `finance/api.py` | `core/views/fw.py` (4 Importe, 8 Aufrufe), Tests |
| `pay_kreditor`, `create_zahlung`, `import_standard_kontenplan` | `finance/api.py` | Tests |
| `verarbeite_docuseal_event`, `_vertrag_id_aus_name`, `_erster_dokument_url` | `rentals/api.py` | Tests |

**Die Liste ist nicht vollständig — sie ist der Ausgangspunkt.** Vor dem Umzug für jede Funktion in allen sechs `api.py` prüfen, ob sie ausserhalb ihres Moduls vorkommt:

```bash
for a in crm finance mietprozess portfolio rentals tickets; do
  for f in $(grep -oE "^def [a-z_]+" $a/api.py | sed 's/def //'); do
    n=$(grep -rn "\b$f\b" --include=*.py . | grep -v "^\./$a/api.py" | wc -l)
    [ "$n" -gt 0 ] && echo "$a.$f -> $n Fundstellen ausserhalb"
  done
done
```

Achtung bei diesem Lauf: Gleiche Funktionsnamen gibt es mehrfach im Bestand (`sanitize_filename` und `link_callback` existieren auch in `core/views/docuseal.py`). Ein Treffer allein genügt nicht — es zählt, ob **aus diesem Modul** importiert wird. Massgeblich ist die `from <app>.api import`-Zeile, nicht der blosse Name.

**Abnahme E1a:** Testsuite grün, Testzahl unverändert, im Diff nur verschobene Zeilen und angepasste Importe. Zeilenbilanz geht auf.

---

## E1b — Die SPA-Oberfläche entfernen

Zwölf Templates, dazu die Route und der View.

| Datei | Rolle |
|---|---|
| `core/templates/core/spa_master.html` | Master |
| `core/templates/core/tabs/home.html` | Tab |
| `core/templates/core/tabs/crm.html` | Tab |
| `core/templates/core/tabs/portfolio.html` | Tab |
| `core/templates/core/tabs/rentals.html` | Tab |
| `core/templates/core/tabs/finance.html` | Tab |
| `core/templates/core/tabs/tickets.html` | Tab |
| `core/templates/core/tabs/mietprozess.html` | Tab |
| `core/templates/core/includes/scripts.html` | 1'399 Zeilen Inline-JavaScript |
| `core/templates/core/includes/head.html` | Vue 3, Tailwind-CDN, Chart.js |
| `core/templates/core/includes/header.html` | SPA-Kopfzeile |
| `core/templates/core/components/modals.html` | SPA-Modals |

Dazu: `path('app/', spa_master_view, name='spa_master')` in `swiss_immo/urls.py` und `spa_master_view` in `core/views/dashboard_view.py`.

**Nachweispflicht je Datei.** Vor dem Löschen belegen, dass sie ausschliesslich von der SPA verwendet wird:

```bash
grep -rn "includes/head.html\|includes/header.html\|components/modals.html" --include=*.html .
grep -rn "spa_master\|core/tabs/" --include=*.py --include=*.html .
```

Die drei `includes/`- und `components/`-Dateien sind die riskantesten: Namen wie `head.html` und `header.html` klingen allgemein. Wird eine davon auch von `fw/base.html` oder einem öffentlichen Formular eingebunden, bleibt sie — dann gehört das in die PR-Beschreibung, nicht in den Papierkorb.

Der Fall `core/views/webhooks.py` aus P0.4 ist die Erinnerung daran, warum: **nicht verdrahtet ist nicht dasselbe wie tot**, und umgekehrt ist ein allgemein klingender Name kein Beleg für Zugehörigkeit.

**Abnahme E1b:** Alle verbleibenden URLs auflösbar, Testsuite grün, `/neu/`, `/portal/` und `/mieter/` per Testclient erreichbar.

### E1b — erledigt am 14.08.2026

Abnahme erfüllt: 293 benannte Routen auflösbar, 1'074 Tests grün, `/neu/` liefert 200,
`/portal/` und `/mieter/` leiten rollenrichtig nach `/neu/` (200 nach Redirect), `/app/` ist 404.

Zwei Abweichungen von dieser Vorgabe — beide zugunsten des Bestands:

**1. Es waren fünfzehn Dateien, nicht zwölf.** Die Nachweispflicht oben hat drei weitere
SPA-Dateien zutage gefördert, die hier nicht aufgeführt waren:

| Datei | Einzige Referenz |
|---|---|
| `core/templates/core/components/side_panels.html` | `spa_master.html` |
| `core/templates/core/components/toasts_and_loader.html` | `spa_master.html` |
| `core/templates/core/includes/sidebar.html` | `spa_master.html` |

Für alle fünfzehn gilt dasselbe Muster: genau eine Referenz, und die führt auf
`spa_master.html`, das seinerseits nur von `spa_master_view` gerendert wurde. Die im
Auftrag als riskant markierten `head.html`/`header.html`/`modals.html` haben sich damit
als eindeutig SPA-eigen erwiesen — `fw/base.html` bindet keine davon ein.

**2. `swiss_immo/settings.py` musste mitgeändert werden.** Nicht Aufräumen bei der
Gelegenheit, sondern zwingende Folge: die Unfold-Konfiguration hielt an zwei Stellen ein
`reverse_lazy("spa_master")` (Zeile 343 `SITE_URL`, Zeile 378 Navigationseintrag
„Zurück zur App 🚀"). `reverse_lazy` löst erst beim Zugriff auf — die Route zu entfernen
hätte das Admin also nicht beim Start, sondern beim Rendern zerrissen. Beide Stellen zeigen
jetzt auf `fw_dashboard`, der Navigationseintrag heisst „Zur Verwaltung 🚀".

Mit entfernt wurden `_generate_dashboard_context` und `_render_error` in
`core/views/dashboard_view.py` — beide dienten ausschliesslich `spa_master_view`.
`_berechne_aufgaben` bleibt: es wird von `core/views/fw.py:25` gebraucht.
Die Datei schrumpft damit von 252 auf 141 Zeilen.

---

## E1c — Die API-Endpunkte entfernen

82 Endpunkte, verteilt auf sechs Router: `portfolio` 26, `finance` 23, `crm` 12, `rentals` 8, `tickets` 8, `mietprozess` 5.

**Genau zwei müssen bleiben**, beide bewusst öffentlich und im Code begründet:

| Endpunkt | Gebraucht von |
|---|---|
| `POST /api/mietprozess/public/bewerben` | `core/templates/core/bewerbung.html`, `core/templates/core/public_bewerbung_form.html` |
| `POST /api/rentals/webhook/docuseal` | DocuSeal-Rücklauf |

Beim DocuSeal-Webhook zuerst klären: Es gibt **zwei** Rücklaufpfade — diesen und `docuseal_webhook` in `core/views/docuseal.py`. Welcher ist in der DocuSeal-Konfiguration tatsächlich eingetragen? Wird der falsche entfernt, kommen unterzeichnete Verträge nicht mehr zurück, und es fällt erst auf, wenn ein Vertrag fehlt. **Diese Frage nicht selbst beantworten — vorlegen.**

Danach fallen: die Router-Registrierungen in `swiss_immo/urls.py`, die nicht mehr gebrauchten `api.py` und `schemas.py`, und die `NinjaAPI`-Instanz mitsamt `/api/docs`. Ob `django-ninja` in `requirements.txt` bleibt, hängt daran, ob die zwei öffentlichen Endpunkte weiter über Ninja laufen oder auf normale Views umgestellt werden — das ist eine eigene Entscheidung, kein Nebenprodukt.

**Der ID-Offset-Hack verschwindet hier mit**: `crm/api.py`, `crm/schemas.py`, `portfolio/api.py`, `portfolio/schemas.py`. Wenn nach diesem PR noch ein `+ 10000` im Bestand steht, war die Annahme falsch und gehört geprüft.

### Zur Testzahl

Rund 48 Testmethoden in sechs Klassen sprechen `/api/`-Pfade an. Die Zahl wird in diesem PR **sinken** — und das ist richtig, nicht verdächtig.

Die Definition of Done verlangt eine Erklärung für jede Abnahme. Sie gehört mit exakten Zahlen in die PR-Beschreibung: vorher, nachher, Differenz, und welche Testklassen entfallen sind. Was einen Endpunkt testet, der nicht mehr existiert, wird gelöscht. Was über einen Endpunkt Fachlogik testet, die weiterlebt, wird auf den neuen Aufrufweg umgeschrieben — nicht gelöscht.

**Abnahme E1c:** Beide öffentlichen Endpunkte antworten anonym wie zuvor, alle übrigen `/api/`-Pfade liefern 404, Testsuite grün, Abnahme der Testzahl beziffert und begründet, kein `+ 10000` mehr im Bestand.

### E1c — erledigt am 14.08.2026

Abnahme erfüllt: 80 von 82 Endpunkten entfernt, `/api/docs` abgeschaltet, kein `+ 10000` mehr
im Bestand, 1'073 Tests grün. `ApiOberflaecheNachE1cTests` hält beides fest — je ein Pfad aus
jedem entfernten Router liefert 404 (angemeldet geprüft, damit der 404 nicht bloss die
Anmeldeweiche ist), und beide öffentlichen Endpunkte antworten weiterhin anonym.

**Entscheid: `django-ninja` bleibt.** Der DocuSeal-Webhook wäre trivial auf einen normalen
View umzustellen — er verzichtet bewusst auf ein Body-Schema. Das Bewerbungsformular nicht:
`public_submit_bewerbung` hat **40 `Form(...)`-Parameter und 5 Datei-Felder**. Die durch
Handarbeit zu ersetzen, an genau dem öffentlichen Formular, das in P5 DSG-fest gemacht wurde,
gehört nicht in denselben PR wie 80 Löschungen. Die Angriffsfläche sinkt trotzdem von 82
Endpunkten auf 2. Ob Ninja ganz raus soll, ist danach eine isolierte Frage.

`NinjaAPI` behält `auth=auth_lesen` als Standard — nicht weil noch etwas darauf angewiesen
wäre, sondern als Sicherung: Käme je ein Endpunkt dazu, ohne dass jemand an die Berechtigung
denkt, wäre er session-pflichtig statt offen.

#### Zur Testzahl: 1'074 → 1'073

Die Zahl im Auftrag oben („rund 48 Testmethoden in sechs Klassen") stimmt nicht. Tatsächlich
waren es **11 Tests**, und die meisten sprachen keinen URL-Pfad an, sondern importierten die
API-Funktion und riefen sie mit `RequestFactory` auf. Es sind Regressionstests für echte
Fehler, keine Endpunkt-Tests — entsprechend wurden acht davon **umgeschrieben statt gelöscht**:

| Bisher geprüft über | Jetzt geprüft über |
|---|---|
| `crm.api.delete_mieter` (409 bei aktivem Vertrag) | `POST /neu/personen/<id>/loeschen/` |
| `crm.api.delete_mieter` (Portal-Login mitlöschen) | `POST /neu/personen/<id>/loeschen/` |
| `portfolio.api.delete_liegenschaft` (409) | `POST /neu/liegenschaften/<id>/loeschen/` |
| `finance.api.pay_kreditor` (keine Doppelzahlung) | `POST /neu/kreditoren/bezahlen/` |
| `finance.api.create_zahlung` (negativer Betrag) | `POST /neu/bankabgleich/verbuchen/` |
| `crm.api.list_mieter` (GET seiteneffektfrei) | `GET /neu/personen/` |
| `finance.api.import_standard_kontenplan` | `ensure_kontenplan()` — die eine Quelle |
| `DELETE /api/finance/debitoren-rechnungen/<id>` | `POST /neu/debitoren/<id>/stornieren/` |

Bilanz: **−3 entfernt, +2 neu, netto −1.** Die drei entfernten sind unten begründet.

#### Drei Zusicherungen ohne Zuhause in `/neu/`

**`delete_einheit` — Einheit löschen mit Vertragsschutz.** In `/neu/` gibt es überhaupt kein
Einheit-Löschen; der API-Endpunkt war der einzige Weg. Erreichbar war er nur über die in E1b
entfernte Vue-Oberfläche — die Fähigkeit ist also seit **E1b** weg, nicht erst durch E1c.
E1c entfernt nur den toten Code dahinter.

**`cancel_umzug` — Umzug stornieren, manuell erfasste Adressen schonen.** Gleiche Lage: kein
`/neu/`-Pfad, einziger Zugang war die SPA.

Beides gehört als Rückstand nach `/neu/`, wenn es gebraucht wird — eigener Auftrag, nicht
Teil von E1.

**`get_ticket` — reine Leserolle darf ein Ticket nicht als gelesen markieren.** Dieser Test
liess sich **nicht** umschreiben, weil `/neu/` die Zusicherung nicht einhält:
`fw_schaden_detail` läuft unter `TEAM_ROLLEN` (Leserolle eingeschlossen) und setzt
`gelesen = True` beim Öffnen. Das ist ein bestehender kleiner Fehler in `/neu/`, nicht von
E1c verursacht — und ein Ein-Zeilen-Fix. Er gehört in einen eigenen PR, nicht in diesen.

#### Nebenbefund: drei PDF-Helfer in dreifacher Ausführung

`rentals/api.py` hielt eigene Fassungen von `generate_vertrag_pdf_bytes`, `sanitize_filename`
und `link_callback`. Sie wurden nur innerhalb derselben Datei gebraucht — die übrige
Anwendung nutzt die Fassungen in `core/services/pdf_service.py`, und `core/views/docuseal.py`
hält eine **dritte**. Die Kopien in `rentals/api.py` sind mit den Endpunkten weg; die
verbleibende Doppelung `pdf_service.py` ↔ `views/docuseal.py` ist ein eigener Posten.

---

## Reihenfolge und Sicherung

E1a → E1b → E1c, drei getrennte PRs. Jeder einzeln zurückrollbar.

Der Grund für genau diese Reihenfolge: Nach E1a ist die Fachlogik in Sicherheit, danach kann gelöscht werden, ohne dass ein Fund mitten im Umbau alles blockiert. Umgekehrt liefe man Gefahr, unter Zeitdruck Logik nachzuziehen, die man gerade gelöscht hat.

Vor E1c einmal `mandanten-auditor` über den Gesamtdiff laufen lassen — nicht wegen Mandantentrennung, sondern weil er gegnerisch liest und Löschungen findet, die zu weit gehen.

---

## Was nicht Teil von E1 ist

- **Der Unfold-Admin** — das ist E2, eigener Auftrag.
- **`fw.py` zerlegen** — Etappe 1, braucht das Freeze-Fenster.
- **Die beiden `Dokument`-Modelle zusammenführen** — bleibt TS-6/P2.1, wird durch E1 nur billiger.
- **Aufräumen „bei der Gelegenheit"** — jeder Fund, der nicht zur SPA gehört, kommt in die PR-Beschreibung und in einen eigenen PR.
