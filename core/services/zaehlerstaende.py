"""Plausibilitätsprüfung für Zählerstände: Fehler (nicht speicherbar) und Warnungen (auffällig, mit Bestätigung speicherbar).

Gilt für jeden Weg, auf dem ein Stand entsteht: die Erfassung der Verwaltung und die Ablesung der Mieterschaft.

Fehler:   Der Stand liegt unter dem früheren oder über dem späteren Stand (negativer Verbrauch).
Warnung:  Der Verbrauch seit dem letzten Stand ist mehr als dreimal so hoch wie üblich (Median der bisherigen Zeiträume,
          mindestens zwei), oder es gab seit 60 Tagen oder mehr keinen Verbrauch. Beides kann stimmen (Leck, Leerstand),
          verdient aber einen zweiten Blick vor der Abrechnung.
"""
from decimal import Decimal
from statistics import median

from django.utils.translation import gettext as _

FAKTOR_AUFFAELLIG = Decimal('3')
TAGE_OHNE_VERBRAUCH = 60


def _raten(staende):
    """Verbrauch je Tag zwischen aufeinanderfolgenden Ständen (nur Zeiträume mit mindestens einem Tag)."""
    raten = []
    for a, b in zip(staende, staende[1:]):
        tage = (b.datum - a.datum).days
        if tage > 0 and b.wert >= a.wert:
            raten.append((b.wert - a.wert) / tage)
    return raten


def pruefen(zaehler, datum, wert):
    """`{'fehler': [Text, …], 'warnungen': [Text, …]}` für den Stand `wert` am `datum` des Zählers."""
    from portfolio.models import ZaehlerStand
    staende = list(ZaehlerStand.objects.filter(zaehler=zaehler).order_by('datum', 'id'))
    davor_liste = [s for s in staende if s.datum <= datum]
    davor = davor_liste[-1] if davor_liste else None
    danach = next((s for s in staende if s.datum > datum), None)
    fehler, warnungen = [], []
    if davor and wert < davor.wert:
        fehler.append(_('Der Stand liegt unter dem Stand vom %(d)s (%(w)s).')
                      % {'d': davor.datum.strftime('%d.%m.%Y'), 'w': davor.wert})
    elif danach and wert > danach.wert:
        fehler.append(_('Der Stand liegt über dem späteren Stand vom %(d)s (%(w)s).')
                      % {'d': danach.datum.strftime('%d.%m.%Y'), 'w': danach.wert})
    if fehler or davor is None:
        return {'fehler': fehler, 'warnungen': warnungen}
    tage = (datum - davor.datum).days
    verbrauch = wert - davor.wert
    if tage > 0:
        raten = _raten(davor_liste)
        if len(raten) >= 2:
            ueblich = Decimal(str(median(raten)))
            rate = verbrauch / tage
            if ueblich > 0 and rate > FAKTOR_AUFFAELLIG * ueblich:
                warnungen.append(_('Der Verbrauch seit dem %(d)s ist auffällig hoch: etwa das %(f)s-Fache des Üblichen.')
                                 % {'d': davor.datum.strftime('%d.%m.%Y'), 'f': (rate / ueblich).quantize(Decimal('0.1'))})
        if verbrauch == 0 and tage >= TAGE_OHNE_VERBRAUCH:
            warnungen.append(_('Seit dem %(d)s (%(n)s Tage) hat sich der Stand nicht verändert.')
                             % {'d': davor.datum.strftime('%d.%m.%Y'), 'n': tage})
    return {'fehler': fehler, 'warnungen': warnungen}
