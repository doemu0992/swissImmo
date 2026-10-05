"""Vorgaben der Gemeinschaft (Reglement) — gespeichert, nicht geraten.

Das System kennt weder Einladungsfrist noch Quorum noch Anfechtungsfrist. Eine Person trägt sie ein (mit Quelle)
und bestätigt sie. Bis dahin gilt:
  · Einladungsfrist: Systemvorgabe 10 Tage, ausdrücklich ungeprüft;
  · Beschlussfähigkeit und Anfechtungsfrist: es wird nicht beurteilt bzw. keine Frist geführt.

Jede Änderung der Zahlen nimmt die Bestätigung zurück: Was bestätigt wurde, ist, was im Feld steht.
"""
from django.utils.translation import gettext
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from stweg.beschluss import praesenz
from stweg.models import StwegVorgaben

SYSTEM_EINLADUNGSFRIST = 10
FELDER = ('einladungsfrist_tage', 'quorum_koepfe_prozent', 'quorum_quoten_prozent', 'anfechtungsfrist_tage',
          'verzugszins_prozent')


class VorgabenFehler(ValueError):
    pass


def vorgaben_von(liegenschaft):
    """Die Vorgaben oder None (nur lesen, legt nichts an)."""
    return StwegVorgaben.objects.filter(liegenschaft=liegenschaft).first()


def einladungsfrist_vorgabe(liegenschaft):
    v = vorgaben_von(liegenschaft)
    return v.einladungsfrist_tage if v and v.einladungsfrist_tage is not None else SYSTEM_EINLADUNGSFRIST


def ist_bestaetigt(liegenschaft):
    v = vorgaben_von(liegenschaft)
    return bool(v and v.bestaetigt_am)


def _wert(roh, name, *, ganzzahl=False, prozent=False):
    roh = ('' if roh is None else str(roh)).strip().replace(',', '.')
    if roh == '':
        return None
    try:
        w = int(roh) if ganzzahl else Decimal(roh)
    except (ValueError, ArithmeticError):
        raise VorgabenFehler(gettext('«%(roh)s» ist keine gültige Zahl (%(name)s).') % {'roh': roh, 'name': name})
    if w < 0 or (prozent and w > 100):
        raise VorgabenFehler(
            (gettext('%(name)s: erlaubt sind Werte von 0 bis 100.') if prozent
             else gettext('%(name)s: erlaubt sind Werte ab 0.')) % {'name': name})
    return w


def speichern(liegenschaft, daten, *, bestaetigen=False, user=None):
    """Speichert die Vorgaben. `daten`: Formularwerte (leer = nicht gesetzt). Ändert sich eine Zahl,
    entfällt die Bestätigung; `bestaetigen=True` bestätigt den neuen Stand."""
    neu = {
        'einladungsfrist_tage': _wert(daten.get('einladungsfrist_tage'), 'Einladungsfrist', ganzzahl=True),
        'quorum_koepfe_prozent': _wert(daten.get('quorum_koepfe_prozent'), 'Quorum Köpfe', prozent=True),
        'quorum_quoten_prozent': _wert(daten.get('quorum_quoten_prozent'), 'Quorum Wertquoten', prozent=True),
        'anfechtungsfrist_tage': _wert(daten.get('anfechtungsfrist_tage'), 'Anfechtungsfrist', ganzzahl=True),
        'verzugszins_prozent': _wert(daten.get('verzugszins_prozent'), 'Verzugszins', prozent=True),
    }
    v = vorgaben_von(liegenschaft) or StwegVorgaben(liegenschaft=liegenschaft)
    geaendert = v.pk is None or any(
        (getattr(v, k) is None) != (w is None) or (w is not None and Decimal(getattr(v, k)) != Decimal(w))
        for k, w in neu.items())
    for k, w in neu.items():
        setattr(v, k, w)
    v.bemerkung = (daten.get('bemerkung') or '').strip()
    if geaendert:
        v.bestaetigt_am, v.bestaetigt_von = None, None
    if bestaetigen:
        v.bestaetigt_am, v.bestaetigt_von = timezone.now(), user
    v.save()
    return v


def beschlussfaehigkeit(versammlung):
    """None, wenn die Gemeinschaft kein Quorum eingetragen hat (dann wird nicht geurteilt). Sonst
    {'beschlussfaehig', 'koepfe', 'quoten', 'bestaetigt', 'gruende'} aus der Anwesenheit."""
    v = vorgaben_von(versammlung.liegenschaft)
    if v is None or (v.quorum_koepfe_prozent is None and v.quorum_quoten_prozent is None):
        return None
    p = praesenz(versammlung)
    gruende = []
    if v.quorum_koepfe_prozent is not None and p['koepfe_total']:
        anteil = Decimal(p['koepfe']) * 100 / p['koepfe_total']
        if anteil < v.quorum_koepfe_prozent:
            gruende.append(gettext('Köpfe: %(anteil)s %% anwesend, verlangt %(soll)s %%.')
                           % {'anteil': f'{anteil:.2f}', 'soll': f'{v.quorum_koepfe_prozent:g}'})
    if v.quorum_quoten_prozent is not None and p['quoten_total']:
        anteil = Decimal(p['quoten']) * 100 / p['quoten_total']
        if anteil < v.quorum_quoten_prozent:
            gruende.append(gettext('Wertquoten: %(anteil)s %% anwesend, verlangt %(soll)s %%.')
                           % {'anteil': f'{anteil:.2f}', 'soll': f'{v.quorum_quoten_prozent:g}'})
    return {'beschlussfaehig': not gruende, 'gruende': gruende, 'praesenz': p,
            'bestaetigt': bool(v.bestaetigt_am)}


def anfechtungsfrist_bis(versammlung):
    """Letzter Tag der Frist (Datum des Protokollversands + Tage) oder None."""
    v = vorgaben_von(versammlung.liegenschaft)
    if v is None or v.anfechtungsfrist_tage is None or not versammlung.protokoll_versendet_am:
        return None
    return timezone.localtime(versammlung.protokoll_versendet_am).date() + timedelta(days=v.anfechtungsfrist_tage)
