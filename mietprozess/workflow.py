"""Ablauf einer Mietbewerbung: erlaubte Statuswechsel und die Spalten des Boards.

Nach dem Muster von `tickets.workflow.UEBERGAENGE`. Board (Ziehen und
Auswahlfeld), das Statusformular der Detailansicht, Zusage/Absage aus dem
Vergleich und die Umwandlung in einen Vertrag lesen dieselbe Tabelle.

DIE SPALTEN DES BOARDS

Vier Spalten auf fünf Zustände plus den Vertragsbezug:

* **Eingegangen** — `neu`.
* **Geprüft** — `geprueft`, `besichtigung` und `zugesagt`, solange kein
  Vertrag verknüpft ist. Ein Chip an der Karte nennt den genauen Zustand.
* **Abgelehnt** — `abgelehnt`.
* **Vertrag generiert** — `Mietbewerbung.vertrag` ist gesetzt. Allein der
  verknüpfte Vertrag zählt, nicht der Status: `fw_bewerber_entscheid` setzt
  «zugesagt» auch ohne Entwurf.

Eine Bewerbung mit Vertrag ist abgeschlossen. Von dort führt kein Wechsel
weg; wer den Entwurf verwirft und löscht, bekommt die Bewerbung über
`on_delete=SET_NULL` als «zugesagt ohne Vertrag» in «Geprüft» zurück.
"""
from django.utils.translation import gettext_lazy as _

#: Status → Status, auf die von dort gewechselt werden darf.
#: Zurück nach `neu` führt kein Weg: «Eingegangen» heisst «noch nie angesehen».
#: Aus `abgelehnt` nur zurück nach `geprueft` (Absage irrtümlich gesetzt) —
#: nicht direkt zur Zusage, denn die Absage-Mail ist dann schon versandt.
UEBERGAENGE = {
    'neu':          {'geprueft', 'besichtigung', 'zugesagt', 'abgelehnt'},
    'geprueft':     {'besichtigung', 'zugesagt', 'abgelehnt'},
    'besichtigung': {'geprueft', 'zugesagt', 'abgelehnt'},
    'zugesagt':     {'geprueft', 'besichtigung', 'abgelehnt'},
    'abgelehnt':    {'geprueft'},
}

#: (Schlüssel, Beschriftung, Zielstatus beim Ablegen)
SPALTEN = (
    ('eingegangen', _('Eingegangen'), 'neu'),
    ('geprueft', _('Geprüft'), 'geprueft'),
    ('abgelehnt', _('Abgelehnt'), 'abgelehnt'),
    ('vertrag', _('Vertrag generiert'), 'zugesagt'),
)
SPALTEN_SCHLUESSEL = tuple(k for k, _l, _z in SPALTEN)

#: Abgelehnte bleiben so lange auf dem Board — danach stehen sie nur noch in der Liste.
ABGELEHNT_TAGE = 30


def spalte_von(bewerbung):
    """In welcher Board-Spalte steht diese Bewerbung?"""
    if bewerbung.vertrag_id:
        return 'vertrag'
    if bewerbung.status == 'neu':
        return 'eingegangen'
    if bewerbung.status == 'abgelehnt':
        return 'abgelehnt'
    return 'geprueft'


def status_erlaubt(bewerbung, neu):
    """Darf die Bewerbung auf `neu` wechseln? Gleichbleiben ist immer erlaubt,
    ausser es ist ein Vertrag verknüpft und der Status würde sich ändern."""
    if neu == bewerbung.status:
        return True
    if bewerbung.vertrag_id:
        return False
    return neu in UEBERGAENGE.get(bewerbung.status, ())


def erlaubte_status(bewerbung):
    """Zielstatus für das Statusformular, sortiert in der Reihenfolge der Choices."""
    from mietprozess.models import Mietbewerbung
    return [k for k, _l in Mietbewerbung.STATUS_CHOICES
            if k != bewerbung.status and status_erlaubt(bewerbung, k)]


def spalte_erlaubt(bewerbung, spalte):
    """Darf die Karte in diese Spalte? Die eigene Spalte zählt nicht als Wechsel."""
    if spalte not in SPALTEN_SCHLUESSEL or spalte == spalte_von(bewerbung):
        return False
    # Die Vertragssperre steht EINMAL, in `status_erlaubt`: Jede Spalte führt
    # auf einen anderen Status als «zugesagt mit Vertrag».
    if spalte == 'vertrag':
        return status_erlaubt(bewerbung, 'zugesagt')
    ziel = dict((k, z) for k, _l, z in SPALTEN)[spalte]
    return status_erlaubt(bewerbung, ziel)


def erlaubte_spalten(bewerbung):
    """[(Schlüssel, Beschriftung)] für das Auswahlfeld «Verschieben nach…»."""
    return [(k, l) for k, l, _z in SPALTEN if spalte_erlaubt(bewerbung, k)]
