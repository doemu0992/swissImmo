"""Vollmachten für eine Versammlung erteilen und widerrufen."""
from django.utils import timezone
from django.utils.translation import gettext

from stweg.models import Vollmacht


class VollmachtFehler(ValueError):
    pass


def _pruefe_scan(datei):
    from core.utils.uploads import validiere_dokument
    ok, fehler = validiere_dokument(datei)
    if not ok:
        raise VollmachtFehler(fehler)


def erteilen(versammlung, einheit, bevollmaechtigter, *, erteilt_von=None, kanal='portal', dokument=None):
    """Gültig ist immer höchstens eine Vollmacht je Einheit; eine neue ersetzt die alte."""
    v = versammlung
    if v.status != v.EINGELADEN:
        raise VollmachtFehler(gettext('Vollmachten lassen sich nur nach der Einladung und vor der Versammlung erteilen.'))
    if einheit.liegenschaft_id != v.liegenschaft_id:
        raise VollmachtFehler(gettext('Die Einheit gehört nicht zu dieser Gemeinschaft.'))
    name = (bevollmaechtigter or '').strip()
    if not name:
        raise VollmachtFehler(gettext('Bitte angeben, wer vertreten soll.'))
    if dokument:
        _pruefe_scan(dokument)          # vor allem anderen: eine abgelehnte Datei ändert nichts
    for alt in Vollmacht.objects.filter(versammlung=v, einheit=einheit, widerrufen_am__isnull=True):
        widerrufen(alt)
    return Vollmacht.objects.create(versammlung=v, einheit=einheit, bevollmaechtigter=name[:120],
                                    erteilt_von=erteilt_von or einheit.stockwerkeigentuemer, kanal=kanal,
                                    dokument=dokument or None)


def dokument_anhaengen(vollmacht, datei):
    """Hängt den Scan der unterschriebenen Vollmacht an (ersetzt einen vorhandenen)."""
    if vollmacht.widerrufen_am is not None:
        raise VollmachtFehler(gettext('Die Vollmacht ist widerrufen.'))
    _pruefe_scan(datei)
    if vollmacht.dokument:
        vollmacht.dokument.delete(save=False)
    vollmacht.dokument = datei
    vollmacht.save(update_fields=['dokument'])
    return vollmacht


def widerrufen(vollmacht):
    if vollmacht.versammlung.status == vollmacht.versammlung.DURCHGEFUEHRT or \
            vollmacht.versammlung.status == vollmacht.versammlung.PROTOKOLLIERT:
        raise VollmachtFehler(gettext('Die Versammlung hat bereits stattgefunden.'))
    vollmacht.widerrufen_am = timezone.now()
    vollmacht.save(update_fields=['widerrufen_am'])
    return vollmacht


def gueltige(versammlung):
    return Vollmacht.objects.filter(versammlung=versammlung, widerrufen_am__isnull=True)
