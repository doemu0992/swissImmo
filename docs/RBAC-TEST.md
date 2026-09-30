# Rollen- und Berechtigungstest (RBAC)

Stand 30.09.2026. Tests: `core/tests/test_rbac.py`.

## Rollen

| Rolle | Herkunft | Zugang |
|---|---|---|
| Inhaber / Verwalter / Sachbearbeiter / Lesezugriff | `Mitgliedschaft.rolle` | `/neu/…` je nach `@rolle_erforderlich` |
| **Hauswart** | `Mitgliedschaft.rolle = 'Hauswart'` | nur Schadensmeldungen **der ihm zugeordneten Liegenschaften**: Liste, Detail, Status (`HAUSWART_ROLLEN`, `TICKET_LESE_ROLLEN`, `TICKET_SCHREIB_ROLLEN`; Zuordnung `Liegenschaft.hauswarte`) |
| Eigentümer | `Eigentuemer.benutzer`, keine Mitgliedschaft | nur `/portal/` |
| Mieter | `Mieter.benutzer`, keine Mitgliedschaft | nur `/mieter/` |

Der Hauswart steht bewusst **nicht** in `TEAM_ROLLEN`: Jede View, die nur das
Team zulässt (Finanzen, Mietzinse, Verträge, Personen, Einstellungen), sperrt
ihn ohne weiteres Zutun.

## Zuordnung Hauswart → Liegenschaft

`Liegenschaft.hauswarte` (M2M auf `Benutzer`, getrennt von `betreut_von`).
Der Inhaber setzt sie in «Benutzer & Rollen» beim Hauswart; ein Rollenwechsel
löscht sie. `ist_nur_hauswart()` und `hauswart_darf_liegenschaft()`
(`core/auth.py`) entscheiden; Schadensliste und Liegenschaftsmenü
(`_global_filter`) filtern, Detail und Status einer fremden Liegenschaft
antworten mit 403. Ohne Zuordnung sieht der Hauswart nichts. Team und
Superuser gelten nie als «nur Hauswart». Die Schadensliste blendet das
Formular «Schaden erfassen» aus, wenn die Rolle nicht schreiben darf.

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

- Die Detailseite eines Schadens zeigt dem Hauswart noch Knöpfe, die 403
  ergeben (Auftrag, Antwort, Löschen); nur das Erfassungsformular der Liste ist
  ausgeblendet.
- Bestehende Hauswart-Konten mit «Lesezugriff» werden nicht automatisch
  umgestellt (Umstellung von Hand in «Benutzer & Rollen»).
- Portal-Objektprüfung (fremdes Ticket im Mieterportal) antwortet 404 statt
  403 — gewollt, um die Existenz nicht zu verraten.
