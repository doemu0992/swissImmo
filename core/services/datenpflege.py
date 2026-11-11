"""Von Hand gepflegte Daten, die veralten: Was ist beim Betreiber jetzt fällig?

Zwei Tabellen im Code werden nicht aus einer Quelle geladen, sondern vom Betreiber nachgetragen:
* der Landesindex der Konsumentenpreise (`core/services/lik.py`, Monatswerte des BFS), und
* das Verzeichnis der Formularpflicht (`core/services/formularpflicht.py`, jedes Jahr im November neu).

Veralten sie still, rechnen Indexanpassungen mit einem zu alten Wert oder die Formularpflicht eines Kantons stimmt nicht
mehr. Dieser Dienst liefert die Erinnerungen; angezeigt werden sie auf der Betreiber-Startseite, nur wenn etwas fällig ist.
"""
from django.utils.translation import gettext as _

from core.services import formularpflicht, lik

#: Das BFS veröffentlicht den Monatswert Anfang des Folgemonats: Ab einem Monat Rückstand ist ein Nachtrag fällig.
LIK_RUECKSTAND_FAELLIG = 1
#: So lange gilt eine Prüfung des Formularpflicht-Registers.
FORMULARPFLICHT_PRUEFINTERVALL_TAGE = 365


def faellig(heute):
    """Liste der fälligen Pflegeaufgaben als Texte (leer = nichts zu tun)."""
    aufgaben = []
    rueckstand = lik.tabelle_rueckstand_monate(heute)
    if rueckstand is None or rueckstand > LIK_RUECKSTAND_FAELLIG:
        letzter = lik.letzter_tabellenmonat()
        stand = f'{letzter[1]:02d}/{letzter[0]}' if letzter else _('kein Monat')
        aufgaben.append(_('LIK-Tabelle nachtragen: Sie endet im Monat %(stand)s (core/services/lik.py).') % {'stand': stand})
    # Das BWO gibt das Verzeichnis jährlich neu heraus; ein Register, das vor mehr als einem Jahr geprüft wurde, ist zu prüfen.
    if (heute - formularpflicht.GEPRUEFT_AM).days > FORMULARPFLICHT_PRUEFINTERVALL_TAGE:
        aufgaben.append(_('Formularpflicht prüfen: Das Register (core/services/formularpflicht.py, Stand %(stand)s) wurde '
                          'zuletzt am %(datum)s geprüft; das BWO gibt das Verzeichnis jedes Jahr neu heraus.')
                        % {'stand': formularpflicht._STAND_VERZEICHNIS, 'datum': formularpflicht.GEPRUEFT_AM.strftime('%d.%m.%Y')})
    return aufgaben
