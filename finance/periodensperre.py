"""Periodensperre mit Vier-Augen-Prinzip fürs Lockern (Roadmap Nr. 11).

Das Datum `Organisation.buchung_gesperrt_bis` sperrt Buchungen bis zum Stichtag. Wer
es nach vorne schiebt (mehr sperrt), darf das allein. Wer es zurücknimmt oder
aufhebt, öffnet abgeschlossene Zeit: Das beantragt eine Person (`SperreAenderung`),
und eine ZWEITE Person aus der Verwaltung gibt frei.

Durchgesetzt wird es in `Organisation.save()` (`pruefe_lockerung`), nicht nur auf der
Seite: Jede Stelle, die das Datum zurückstellt, scheitert ohne Freigabe.
"""
import logging
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

logger = logging.getLogger(__name__)

_FREIGEGEBEN = ContextVar('periodensperre_freigegeben', default=False)


class SperreFehler(Exception):
    """Nicht erlaubt (gleiche Person, keine Begründung, schon entschieden …)."""


@contextmanager
def freigabe_aktiv():
    marke = _FREIGEGEBEN.set(True)
    try:
        yield
    finally:
        _FREIGEGEBEN.reset(marke)


def ist_lockerung(alt, neu):
    """True, wenn `neu` weniger sperrt als `alt` (früherer Stichtag oder aufgehoben)."""
    if alt is None:
        return False
    return neu is None or neu < alt


def pruefe_lockerung(organisation):
    """Wirft `PermissionError`, wenn `organisation.buchung_gesperrt_bis` gelockert wird, ohne Freigabe."""
    if _FREIGEGEBEN.get():
        return
    from crm.models import Organisation
    alt = (Organisation.objects.filter(pk=organisation.pk)
           .values_list('buchung_gesperrt_bis', flat=True).first())
    if ist_lockerung(alt, organisation.buchung_gesperrt_bis):
        raise PermissionError(
            'Die Periodensperre lässt sich nur mit Freigabe einer zweiten Person lockern '
            '(Vier-Augen-Prinzip, Revisionssicherheit).')


def sperre_aendern(organisation, neu_bis, user, grund=''):
    """Setzt die Sperre. Liefert ('gesetzt', None) oder ('beantragt', antrag).

    Mehr sperren geht sofort. Lockern wird zum Antrag und verlangt eine Begründung.
    Ein schon offener Antrag wird ersetzt, damit höchstens einer offen ist.
    """
    from finance.models import SperreAenderung
    alt = organisation.buchung_gesperrt_bis
    if neu_bis == alt:
        return 'gesetzt', None
    if not ist_lockerung(alt, neu_bis):
        organisation.buchung_gesperrt_bis = neu_bis
        organisation.save(update_fields=['buchung_gesperrt_bis'])
        return 'gesetzt', None
    if not (grund or '').strip():
        raise SperreFehler(gettext('Für das Lockern der Periodensperre ist eine Begründung nötig.'))
    with transaction.atomic():
        SperreAenderung.alle_organisationen.filter(organisation=organisation, status='offen').update(
            status='abgelehnt', entschieden_am=timezone.now())
        antrag = SperreAenderung.alle_organisationen.create(
            organisation=organisation, alt_bis=alt, neu_bis=neu_bis, grund=grund.strip(),
            beantragt_von=user)
    return 'beantragt', antrag


def entscheiden(antrag, user, freigeben):
    """Gibt den Antrag frei oder lehnt ihn ab. Die antragstellende Person darf es nicht selbst."""
    from finance.models import SperreAenderung
    with transaction.atomic():
        antrag = SperreAenderung.alle_organisationen.select_for_update().get(pk=antrag.pk)
        if antrag.status != 'offen':
            raise SperreFehler(gettext('Dieser Antrag ist schon entschieden.'))
        if freigeben and antrag.beantragt_von_id and antrag.beantragt_von_id == getattr(user, 'pk', None):
            raise SperreFehler(gettext('Die Freigabe muss eine zweite Person erteilen, nicht die antragstellende.'))
        antrag.status = 'freigegeben' if freigeben else 'abgelehnt'
        antrag.entschieden_von = user
        antrag.entschieden_am = timezone.now()
        antrag.save(update_fields=['status', 'entschieden_von', 'entschieden_am'])
        if freigeben:
            org = antrag.organisation
            org.buchung_gesperrt_bis = antrag.neu_bis
            with freigabe_aktiv():
                org.save(update_fields=['buchung_gesperrt_bis'])
    return antrag
