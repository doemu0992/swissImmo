"""E-Voting: digitale Teilnahme und Stimmabgabe der Eigentümer im Portal während der Versammlung.

ABLAUF
  1. Die Verwaltung schaltet bei der Versammlung «E-Voting im Portal» ein (optional bis zu
     einem Zeitpunkt) und führt die Versammlung durch.
  2. Der Eigentümer erklärt seine Teilnahme (`teilnehmen`): seine Einheiten gelten damit als
     anwesend — das Stimmrecht hängt, wie im Saal, an der Anwesenheit.
  3. Er stimmt je Traktandum und je eigener Einheit ab (`abstimmen`). Er kann seine Stimme
     ändern, solange das Ergebnis nicht festgestellt ist; jede Abgabe steht im Ereignisprotokoll.
  4. Das System rechnet einen Vorschlag; festgestellt wird er von einer Person (`beschluss`).

Handeln darf nur die Hauptansprechperson einer Einheit (eine Einheit, eine Stimme); Miteigentümer
lesen nur. Eine gültige Vollmacht heisst «vertreten»; kommt der Eigentümer trotzdem digital,
gilt er als anwesend (wie im Saal).
"""
from django.db import transaction
from django.utils import timezone

from portfolio.models import Einheit, Liegenschaft
from stweg import beschluss
from stweg.beschluss import BeschlussFehler
from stweg.models import Anwesenheit, Stimme, Traktandum, Versammlung


def ist_offen(versammlung, jetzt=None):
    jetzt = jetzt or timezone.now()
    return (versammlung.evoting and versammlung.status == Versammlung.DURCHGEFUEHRT
            and (versammlung.evoting_bis is None or jetzt <= versammlung.evoting_bis))


def _eigene_einheiten(versammlung, eigentuemer):
    return list(Einheit.objects.filter(stockwerkeigentuemer=eigentuemer, liegenschaft=versammlung.liegenschaft,
                                       liegenschaft__typ=Liegenschaft.TYP_STWEG, gehoert_zu__isnull=True))


def _verlange_offen(versammlung, jetzt=None):
    if not versammlung.evoting:
        raise BeschlussFehler('Für diese Versammlung ist kein E-Voting vorgesehen.')
    if versammlung.status != Versammlung.DURCHGEFUEHRT:
        raise BeschlussFehler('Das E-Voting ist nur während der durchgeführten Versammlung offen.')
    if not ist_offen(versammlung, jetzt):
        raise BeschlussFehler('Das E-Voting ist geschlossen.')


@transaction.atomic
def teilnehmen(versammlung, eigentuemer, *, jetzt=None):
    """Erklärt die digitale Teilnahme für alle Einheiten des Eigentümers in dieser Gemeinschaft."""
    _verlange_offen(versammlung, jetzt)
    einheiten = _eigene_einheiten(versammlung, eigentuemer)
    if not einheiten:
        raise BeschlussFehler('Sie haben in dieser Gemeinschaft keine stimmberechtigte Einheit.')
    for e in einheiten:
        Anwesenheit.objects.update_or_create(versammlung=versammlung, einheit=e,
                                             defaults={'art': Anwesenheit.ANWESEND, 'vertreter': ''})
    return einheiten


@transaction.atomic
def abstimmen(versammlung, eigentuemer, stimmen, *, jetzt=None):
    """`stimmen`: {(traktandum_id, einheit_id): 'ja'|'nein'|'enthaltung'}. Alles oder nichts.

    Es zählen nur Einheiten, die dem Eigentümer als Hauptansprechperson gehören und die digital
    teilnehmen. Traktanden anderer Versammlungen, entschiedene und «zur Kenntnisnahme» werden
    abgelehnt — kein stilles Überspringen."""
    _verlange_offen(versammlung, jetzt)
    eigene = {e.pk: e for e in _eigene_einheiten(versammlung, eigentuemer)}
    traktanden = {t.pk: t for t in Traktandum.objects.filter(versammlung=versammlung)}
    angemeldet = set(Anwesenheit.objects.filter(
        versammlung=versammlung, einheit_id__in=eigene, art=Anwesenheit.ANWESEND).values_list('einheit_id', flat=True))
    abgegeben = 0
    for (tid, eid), wert in stimmen.items():
        t, e = traktanden.get(tid), eigene.get(eid)
        if t is None or e is None:
            raise BeschlussFehler('Ungültige Abstimmung: Traktandum oder Einheit gehört nicht zu Ihnen.')
        if e.pk not in angemeldet:
            raise BeschlussFehler(f'Bitte zuerst die Teilnahme erklären (Einheit «{e.bezeichnung}»).')
        beschluss.stimme_abgeben(t, e, wert, kanal='portal', eigentuemer=eigentuemer)
        abgegeben += 1
    return abgegeben


def meine_stimmen(versammlung, eigentuemer):
    """Für die Anzeige im Portal: {(traktandum_id, einheit_id): wert}."""
    eigene = [e.pk for e in _eigene_einheiten(versammlung, eigentuemer)]
    return {(s.traktandum_id, s.einheit_id): s.wert for s in
            Stimme.objects.filter(traktandum__versammlung=versammlung, einheit_id__in=eigene)}
