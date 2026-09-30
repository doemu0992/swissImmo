# Rollen- und Berechtigungstest (RBAC)

Stand 30.09.2026. Tests: `core/tests/test_rbac.py`.

## Rollen

| Rolle | Herkunft | Zugang |
|---|---|---|
| Inhaber / Verwalter / Sachbearbeiter / Lesezugriff | `Mitgliedschaft.rolle` | `/neu/…` je nach `@rolle_erforderlich` |
| **Hauswart** (neu) | `Mitgliedschaft.rolle = 'Hauswart'` | nur Schadensmeldungen: Liste, Detail, Status (`HAUSWART_ROLLEN`, `TICKET_LESE_ROLLEN`, `TICKET_SCHREIB_ROLLEN`) |
| Eigentümer | `Eigentuemer.benutzer`, keine Mitgliedschaft | nur `/portal/` |
| Mieter | `Mieter.benutzer`, keine Mitgliedschaft | nur `/mieter/` |

Der Hauswart steht bewusst **nicht** in `TEAM_ROLLEN`: Jede View, die nur das
Team zulässt (Finanzen, Mietzinse, Verträge, Personen, Einstellungen), sperrt
ihn ohne weiteres Zutun.

## Was geprüft wird

1. Benannte Angriffe: Mieter → fremdes Ticket auf «erledigt»; Hauswart →
   Finanzseiten/Mietzinse; Eigentümer → Einstellungen/Benutzer/Admin.
   Jeweils mit Nachweis, dass der Bestand unverändert ist.
2. Sweep: **jede** Route des Projekts (aktuell 282 ausserhalb der offenen
   Pfade) gegen Mieter, Eigentümer und Hauswart, GET und POST → 403.
   Neue Views ohne `@rolle_erforderlich` machen den Test rot.

Ausnahmen stehen mit Begründung in `OFFEN_FUER_ANGEMELDETE` und
`NUR_WEITERLEITUNG`; jeder neue Eintrag ist eine Entscheidung.

## Gefundene Lücken (behoben)

- `@require_POST` stand **vor** `@rolle_erforderlich`: GET auf 9 Views
  antwortete mit 405 statt 403 (auch anonym). Reihenfolge getauscht.
- `generiere_amtliches_formular` (`/formular/amtlich/<id>/`) hatte keine
  Rollenprüfung (leitete nur weiter). Jetzt `ROLLE_VERWALTER`.

## Bewusst offen

- Der Hauswart sieht die Schadensmeldungen **aller** Liegenschaften der
  Verwaltung; eine Zuordnung Hauswart → Liegenschaft gibt es im Modell nicht.
- Portal-Objektprüfung (fremdes Ticket im Mieterportal) antwortet 404 statt
  403 — gewollt, um die Existenz nicht zu verraten.
