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


def _live_hinweis(letzter):
    """Der Live-Wert, falls er neuer ist als die Tabelle: erspart das Nachschlagen. Nicht ungeprüft eintragen (BFS-Publikation)."""
    from django.conf import settings
    if not getattr(settings, 'LIK_LIVE_ABRUF', False):
        return ''
    try:
        stand, punkte, _basis = lik.aktueller_lik_wert(live=True)
    except Exception:                                        # noqa: BLE001 — ein Hinweis darf die Startseite nie stören
        return ''
    if stand is None or punkte is None or (letzter and (stand.year, stand.month) <= letzter):
        return ''
    return _('Der Live-Abruf nennt %(monat)s: %(punkte)s. Vor dem Eintragen gegen die BFS-Publikation prüfen.') % {
        'monat': f'{stand.month:02d}/{stand.year}', 'punkte': punkte}


def faellig(heute):
    """Liste der fälligen Pflegeaufgaben als Texte (leer = nichts zu tun)."""
    aufgaben = []
    rueckstand = lik.tabelle_rueckstand_monate(heute)
    if rueckstand is None or rueckstand > LIK_RUECKSTAND_FAELLIG:
        letzter = lik.letzter_tabellenmonat()
        stand = f'{letzter[1]:02d}/{letzter[0]}' if letzter else _('kein Monat')
        text = _('LIK-Tabelle nachtragen: Sie endet im Monat %(stand)s (core/services/lik.py).') % {'stand': stand}
        live = _live_hinweis(letzter)
        aufgaben.append(f'{text} {live}' if live else text)
    # Das BWO gibt das Verzeichnis jährlich neu heraus; ein Register, das vor mehr als einem Jahr geprüft wurde, ist zu prüfen.
    if (heute - formularpflicht.GEPRUEFT_AM).days > FORMULARPFLICHT_PRUEFINTERVALL_TAGE:
        aufgaben.append(_('Formularpflicht prüfen: Das Register (core/services/formularpflicht.py, Stand %(stand)s) wurde '
                          'zuletzt am %(datum)s geprüft; das BWO gibt das Verzeichnis jedes Jahr neu heraus.')
                        % {'stand': formularpflicht._STAND_VERZEICHNIS, 'datum': formularpflicht.GEPRUEFT_AM.strftime('%d.%m.%Y')})
    from core.services import abruf_status
    aufgaben.extend(abruf_status.ausfaelle())
    return aufgaben
