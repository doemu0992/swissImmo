"""Spur der Abrufe bei externen Diensten: letzter Erfolg, letzter Fehler, Fehlversuche in Folge.

WARUM: Ein Abruf, der still auf die Tabelle im Code zurückfällt, ist richtig und gefährlich zugleich — niemand
merkt, dass die Quelle seit Wochen nichts mehr liefert (Architekturnotizen R7, die ausgefallene LIK-Nachführung).
`melde_erfolg` und `melde_fehler` schreiben die Spur, `ausfaelle` liefert sie der Betreiber-Startseite.

Das Protokoll darf den Abruf NIE stören: Jeder Fehler beim Schreiben wird geschluckt (und geloggt).
"""
import logging

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

#: Bekannte Abrufe: Schlüssel → Anzeigename. Ein unbekannter Schlüssel ist ein Programmfehler.
ABRUFE = {
    'lik': _('Landesindex der Konsumentenpreise (HEV)'),
    'referenzzins': _('Referenzzinssatz (BWO)'),
    'groq': _('Belegerkennung (Groq)'),
}
#: Ab so vielen Fehlversuchen in Folge gilt ein Abruf als ausgefallen.
AUSFALL_AB = 3
#: Ein Abruf ohne Erfolg seit so vielen Tagen gilt ebenfalls als ausgefallen.
AUSFALL_NACH_TAGEN = 7


def _holen(name):
    from core.models import AbrufStatus
    eintrag, _neu = AbrufStatus.objects.get_or_create(name=name)
    return eintrag


def melde_erfolg(name):
    try:
        eintrag = _holen(name)
        jetzt = timezone.now()
        eintrag.letzter_versuch = jetzt
        eintrag.letzter_erfolg = jetzt
        eintrag.letzter_fehler = ''
        eintrag.fehler_in_folge = 0
        eintrag.save()
    except Exception:                                        # noqa: BLE001 — das Protokoll darf den Abruf nie stören
        logger.exception('Abrufstatus %s: Erfolg nicht gespeichert', name)


def melde_fehler(name, grund):
    """`grund`: kurzer Text ohne Zugangsdaten und ohne Daten einer Verwaltung."""
    try:
        eintrag = _holen(name)
        eintrag.letzter_versuch = timezone.now()
        eintrag.letzter_fehler = str(grund)[:300]
        eintrag.fehler_in_folge += 1
        eintrag.save()
    except Exception:                                        # noqa: BLE001
        logger.exception('Abrufstatus %s: Fehler nicht gespeichert', name)
    logger.warning('Abruf %s fehlgeschlagen: %s', name, grund)


def ausfaelle(jetzt=None):
    """Texte zu allen Abrufen, die ausgefallen aussehen — leer, wenn alles läuft."""
    from core.models import AbrufStatus
    jetzt = jetzt or timezone.now()
    texte = []
    for eintrag in AbrufStatus.objects.order_by('name'):
        if eintrag.fehler_in_folge == 0:
            continue
        seit_erfolg = (jetzt - eintrag.letzter_erfolg).days if eintrag.letzter_erfolg else None
        if eintrag.fehler_in_folge < AUSFALL_AB and (seit_erfolg is None or seit_erfolg < AUSFALL_NACH_TAGEN):
            continue
        name = ABRUFE.get(eintrag.name, eintrag.name)
        letzter = eintrag.letzter_erfolg.strftime('%d.%m.%Y') if eintrag.letzter_erfolg else _('noch nie')
        texte.append(_('Abruf ausgefallen: %(name)s — %(n)s Fehlversuche in Folge, letzter Erfolg %(erfolg)s. Grund: %(grund)s')
                     % {'name': name, 'n': eintrag.fehler_in_folge, 'erfolg': letzter, 'grund': eintrag.letzter_fehler})
    return texte


#: So lange darf der letzte fehlerfreie Abruf des Plattform-Postfachs zurückliegen (der Lauf kommt im Minutentakt).
POSTFACH_STILLE_STUNDEN = 6


def postfach_ausfall(jetzt=None):
    """Hinweistext, wenn das eingerichtete Plattform-Postfach nicht mehr abgerufen wird — sonst ''.

    Der Abruf führt seinen eigenen Status (`core.PlattformEingangStatus`, sichtbar für den Inhaber unter «E-Mail-
    Eingang»). Hier liest ihn die Betreiber-Startseite mit: Bleibt der Dauerläufer stehen oder lehnt der Mailserver
    die Anmeldung ab, kommen Antworten auf Tickets und Rechnungen nicht mehr an, und das soll der Betreiber sehen."""
    from core.models import PlattformEingangStatus
    from core.services import plattform_postfach
    if plattform_postfach.konfiguration() is None:
        return ''                                             # nicht eingerichtet: nichts zu melden
    jetzt = jetzt or timezone.now()
    eintrag = PlattformEingangStatus.objects.filter(pk=1).first()
    erfolg = eintrag.letzter_erfolg if eintrag else None
    if erfolg is not None and (jetzt - erfolg).total_seconds() < POSTFACH_STILLE_STUNDEN * 3600:
        return ''
    letzter = erfolg.strftime('%d.%m.%Y %H:%M') if erfolg else _('noch nie')
    grund = (eintrag.letzter_fehler if eintrag else '') or _('kein Abruf verzeichnet (läuft fetch_plattform_eingang?)')
    return _('Abruf ausgefallen: Plattform-Postfach — letzter Abruf ohne Fehler %(erfolg)s. Grund: %(grund)s') % {
        'erfolg': letzter, 'grund': grund}
