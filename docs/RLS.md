# Row-Level-Security (RLS) — die Datenbank trennt die Verwaltungen ein zweites Mal

Stand 14.11.2026. Code: `core/rls.py`, Befehl `manage.py rls_einrichten`, Tests `core/tests/test_rls.py`.

## Was es ist

Die Trennung der Verwaltungen liegt im Code (`TenantManager`, Fehler ohne Kontext). RLS ist die zweite Schicht: PostgreSQL
blendet beim **Lesen** der **Finanztabellen** (27 Tabellen der App `finance`) Zeilen einer anderen Verwaltung aus. Ein
Programmierfehler, der den Filter im Code umgeht, bekommt von der Datenbank trotzdem nichts.

Bewusst vorsichtig:

* **Nur Lesen.** Schreiben bleibt wie bisher.
* **Nur mit gesetzter Verwaltung.** Läuft etwas ohne Kontext (Migrationen, Sicherungen, tägliche Läufe über alle
  Verwaltungen, Anmeldung), lässt die Datenbank alles durch. Geschützt ist: Eine Anfrage in Verwaltung A liest Daten von B.
* **Nichts geschieht beim Deploy.** Einschalten sind zwei Handgriffe, jeder einzeln rücknehmbar.

## Die drei Stufen (`RLS_MODUS` in der `.env`)

| Wert | Wirkung |
|---|---|
| `aus` (Vorgabe) | nichts |
| `probe` | sperrt nichts; protokolliert jeden Finanzdatensatz, der mit gesetzter Verwaltung geladen wird und einer anderen gehört |
| `scharf` | die Anwendung setzt je Abfrage die Sitzungsvariable `swissimmo.organisation`; mit den Regeln aus `rls_einrichten` blendet PostgreSQL fremde Zeilen aus |

## Einführung, Schritt für Schritt

1. **Probe einschalten.** In der `.env`: `RLS_MODUS=probe`, Web-App neu laden. Zwei Wochen laufen lassen, alle üblichen
   Arbeiten einmal ausführen (Monatslauf, Mahnlauf, Abschluss, Berichte).
2. **Befunde lesen.** Die Betreiber-Startseite nennt die Zahl der letzten 14 Tage; die Einträge selbst zeigt
   `python manage.py sicherheitslog` (Aktion «RLS-Probe: fremde Zeile gelesen», mit Datei und Zeile der Stelle).
   Jeder Befund ist eine Stelle, die `scharf` verändern würde: beheben oder bewusst so lassen, **bevor** es weitergeht.
3. **Rolle prüfen.** `python manage.py rls_einrichten --status`. Steht dort, die Rolle sei Superuser oder habe
   `BYPASSRLS`, gilt für sie keine Regel: Die Anwendung braucht eine Rolle ohne diese Rechte (wie bei
   `datenbank_rolle_pruefen`, siehe `docs/AUTOMATISIERUNG.md`, Abschnitt «Datenbankrolle»).
4. **Regeln anlegen.** Als Eigentümerin der Tabellen (dieselbe Rolle wie `migrate`):
   `python manage.py rls_einrichten`. Solange `RLS_MODUS` nicht `scharf` ist, ändert das am Verhalten nichts.
5. **Scharf schalten.** `RLS_MODUS=scharf`, Web-App und alle Dauerläufer neu laden.

## Zurück

* Sofort: `RLS_MODUS=aus` (oder `probe`) und neu laden. Die Regeln bleiben, lassen ohne Variable aber alles durch.
* Ganz: `python manage.py rls_einrichten --entfernen`.

## Grenzen

* Ein Superuser und Rollen mit `BYPASSRLS` umgehen RLS immer. `FORCE ROW LEVEL SECURITY` ist gesetzt, damit die Regeln
  auch für die Eigentümerin der Tabellen gelten.
* Die Probe prüft **geladene Datensätze**. Zählungen und Summen über fremde Zeilen sieht sie nicht.
* Neue Tabellen der App `finance` (nach einer Migration) sind erst nach einem erneuten `rls_einrichten` geschützt;
  `--status` zeigt offene Tabellen.
* Weitere Apps: `APPS` in `core/rls.py` erweitern, zuerst wieder mit der Probe.
* Nach einem Zurückspielen der Datenbank (`pg_restore`) den Zustand mit `--status` prüfen.
