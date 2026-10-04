"""Vollmachten für eine Versammlung erteilen und widerrufen."""
from django.utils import timezone
from django.utils.translation import gettext

from stweg.models import Vollmacht


class VollmachtFehler(ValueError):
    pass


def erteilen(versammlung, einheit, bevollmaechtigter, *, erteilt_von=None, kanal='portal'):
    """Gültig ist immer höchstens eine Vollmacht je Einheit; eine neue ersetzt die alte."""
    v = versammlung
    if v.status != v.EINGELADEN:
        raise VollmachtFehler(gettext('Vollmachten lassen sich nur nach der Einladung und vor der Versammlung erteilen.'))
    if einheit.liegenschaft_id != v.liegenschaft_id:
        raise VollmachtFehler(gettext('Die Einheit gehört nicht zu dieser Gemeinschaft.'))
    name = (bevollmaechtigter or '').strip()
    if not name:
        raise VollmachtFehler(gettext('Bitte angeben, wer vertreten soll.'))
    for alt in Vollmacht.objects.filter(versammlung=v, einheit=einheit, widerrufen_am__isnull=True):
        widerrufen(alt)
    return Vollmacht.objects.create(versammlung=v, einheit=einheit, bevollmaechtigter=name[:120],
                                    erteilt_von=erteilt_von or einheit.stockwerkeigentuemer, kanal=kanal)


def widerrufen(vollmacht):
    if vollmacht.versammlung.status == vollmacht.versammlung.DURCHGEFUEHRT or \
            vollmacht.versammlung.status == vollmacht.versammlung.PROTOKOLLIERT:
        raise VollmachtFehler(gettext('Die Versammlung hat bereits stattgefunden.'))
    vollmacht.widerrufen_am = timezone.now()
    vollmacht.save(update_fields=['widerrufen_am'])
    return vollmacht


def gueltige(versammlung):
    return Vollmacht.objects.filter(versammlung=versammlung, widerrufen_am__isnull=True)
