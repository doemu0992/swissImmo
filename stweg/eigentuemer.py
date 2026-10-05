"""Handänderung: wer war an einem Tag Eigentümer einer Einheit, und wer schuldet welchen Beitrag.

ANNAHMEN (nicht rechtlich geprüft — vor Gebrauch bestätigen):
  · Ein Beitrag schuldet persönlich, wer am Tag seiner Fälligkeit Eigentümer war. Fällig am Tag des Übergangs gilt
    noch für den NEUEN Eigentümer (Übergang um 00:00). Bei einer Jahresabrechnung gilt der Eigentümer, der in der
    Abrechnung steht (`StwegAbrechnungPosition.eigentuemer`).
  · Das Gemeinschaftspfandrecht (Art. 712i ZGB) hängt am Stockwerkeigentumsanteil, nicht am Eigentümer: es
    umfasst auch Forderungen gegen einen früheren Eigentümer. Die Mahnung dagegen richtet sich nur an den Schuldner.
  · Nicht abgebildet: anteilige Aufteilung eines Beitrags auf den Übergangstag, Vereinbarungen im Kaufvertrag.
  · Die Miteigentümer der Einheit werden beim Wechsel gelöscht: Sie gehörten zum bisherigen Eigentümer.
"""
from django.db import transaction
from django.utils.translation import gettext

from stweg.models import StwegEigentuemerwechsel


class WechselFehler(ValueError):
    pass


def eigentuemer_am(einheit, datum):
    """Die Eigentümer-ID am Tag `datum` (None = unbekannt/keiner)."""
    wechsel = list(einheit.stweg_wechsel.order_by('datum', 'id'))
    if not wechsel:
        return einheit.stockwerkeigentuemer_id
    if datum < wechsel[0].datum:
        return wechsel[0].bisheriger_id
    aktuell = wechsel[0].neu_id
    for w in wechsel:
        if w.datum <= datum:
            aktuell = w.neu_id
    return aktuell


@transaction.atomic
def wechseln(einheit, neu, datum, *, bemerkung='', user=None):
    """Erfasst die Handänderung und setzt `neu` als Eigentümer der Einheit."""
    if neu is None:
        raise WechselFehler(gettext('Bitte den neuen Eigentümer wählen.'))
    if einheit.stockwerkeigentuemer_id == neu.pk:
        raise WechselFehler(gettext('Dieser Eigentümer ist bereits eingetragen.'))
    if datum is None:
        raise WechselFehler(gettext('Bitte das Datum des Eigentumsübergangs angeben.'))
    letzter = einheit.stweg_wechsel.order_by('-datum', '-id').first()
    if letzter is not None and datum <= letzter.datum:
        raise WechselFehler(gettext('Der Übergang muss nach dem letzten erfassten Wechsel (%(datum)s) liegen.')
                            % {'datum': f'{letzter.datum:%d.%m.%Y}'})
    w = StwegEigentuemerwechsel.objects.create(
        einheit=einheit, datum=datum, bisheriger=einheit.stockwerkeigentuemer, neu=neu,
        bemerkung=(bemerkung or '')[:200], erfasst_von=user)
    einheit.stockwerkeigentuemer = neu
    einheit.save(update_fields=['stockwerkeigentuemer'])
    einheit.miteigentuemer.clear()
    return w
