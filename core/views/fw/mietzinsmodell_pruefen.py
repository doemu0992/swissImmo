# core/views/fw/mietzinsmodell_pruefen.py
#
# Live-Prüfung des Mietzinsmodells (Index Art. 269b OR, Staffel Art. 269c OR) für den
# Vertragsassistenten. Rechnet nur mit den mitgeschickten Eingaben und liest keinen
# Datensatz: Es gibt keine ID, die man einsetzen könnte. Die Regeln selbst stehen in
# `core/services/mietzinsmodell.py`; hier wird nur gelesen und ausgegeben.
#
# GET /neu/vertraege/mietzinsmodell/pruefen/
#   modell                 fest | index | staffel
#   beginn, ende           ISO-Datum (JJJJ-MM-TT)
#   ist_befristet          1 | 0 (fehlt: ein gesetztes Ende gilt als Befristung)
#   verzicht_bis           ISO-Datum, Kündigungsverzicht des Vermieters
#   netto                  Netto-Mietzins bei Beginn (auch: netto_mietzins)
#   staffel_ab[]           ISO-Datum je Stufe          } parallele Listen, wie im
#   staffel_erhoehung[]    Erhöhung in CHF je Stufe    } Assistenten (staffel_ab)
#   staffel_prozent[]      Prozent je Stufe (nur um den Verstoss zu melden)
#   basis_lik_punkte       Punkte der Index-Basis
#   basis_lik_stand        JJJJ-MM oder JJJJ-MM-TT
#   index_weitergabe_prozent, index_intervall_monate, index_art
#   hat_zeitplan           1, wenn zusätzlich Komponenten/Zeitplan bestehen
from datetime import date
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from core.auth import TEAM_ROLLEN, rolle_erforderlich
from core.services import mietzinsmodell as regeln
from core.views.fw._basis import _num

#: Mehr Stufen sind ein Fehler in der Eingabe, keine Staffel.
STUFEN_MAX = 60
_JAHRE = (1900, 2200)
_WAHR = {'1', 'true', 'on', 'ja', 'yes', 'y'}


def _roh(wert):
    return (wert or '').strip()


def _datum(wert):
    t = _roh(wert)
    try:
        d = date.fromisoformat(t)
    except ValueError:
        return None
    return d if _JAHRE[0] <= d.year <= _JAHRE[1] else None


def _monat(wert):
    """JJJJ-MM oder JJJJ-MM-TT → erster des Monats."""
    teile = _roh(wert).split('-')
    try:
        d = date(int(teile[0]), int(teile[1]), 1)
    except (ValueError, IndexError):
        return None
    return d if _JAHRE[0] <= d.year <= _JAHRE[1] else None


def _zahl(wert):
    t = _num(_roh(wert))
    if not t:
        return None
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    # NaN, Unendlich und absurde Grössen rechnen weiter und werfen irgendwo.
    return d if d.is_finite() and abs(d) < Decimal('1e9') else None


def _iso(d):
    return d.isoformat() if d else None


def _betrag(d):
    return None if d is None else format(d, 'f')


@rolle_erforderlich(*TEAM_ROLLEN)
@never_cache
@require_GET
def fw_mietzinsmodell_pruefen(request):
    """Die Befunde zu den bisherigen Eingaben; halb ausgefüllte Eingaben sind der Normalfall."""
    q = request.GET
    unlesbar = []

    def datum(name):
        d = _datum(q.get(name))
        if d is None and _roh(q.get(name)):
            unlesbar.append(name)
        return d

    def zahl(*namen):
        for name in namen:
            if _roh(q.get(name)):
                z = _zahl(q.get(name))
                if z is None:
                    unlesbar.append(name)
                return z
        return None

    modell = _roh(q.get('modell')) or 'fest'
    if modell not in regeln.MODELLE:
        unlesbar.append('modell')
        modell = 'fest'
    beginn = datum('beginn')
    ende = datum('ende')
    verzicht_bis = datum('verzicht_bis')
    ist_befristet = (_roh(q.get('ist_befristet')).lower() in _WAHR) if _roh(q.get('ist_befristet')) else None
    stand = _monat(q.get('basis_lik_stand'))
    if stand is None and _roh(q.get('basis_lik_stand')):
        unlesbar.append('basis_lik_stand')
    netto = zahl('netto', 'netto_mietzins')

    daten = [q.getlist('staffel_ab'), q.getlist('staffel_erhoehung'), q.getlist('staffel_prozent')]
    # Leere Zeilen behalten ihre Nummer (die Oberfläche zeigt Befunde an der Zeile), prüfen aber nichts.
    stufen = []
    for i in range(min(max(map(len, daten)), STUFEN_MAX)):
        roh = [_roh(liste[i]) if i < len(liste) else '' for liste in daten]
        ab, erh, proz = _datum(roh[0]), _zahl(roh[1]), _zahl(roh[2])
        for wert, geparst, name in ((roh[0], ab, 'staffel_ab'), (roh[1], erh, 'staffel_erhoehung'),
                                    (roh[2], proz, 'staffel_prozent')):
            if wert and geparst is None:
                unlesbar.append(f'{name}[{i}]')
        stufen.append(regeln.Stufe(ab=ab, erhoehung_chf=erh, prozent=proz))

    gemeinsam = dict(
        modell=modell, beginn=beginn, ende=ende, ist_befristet=ist_befristet, verzicht_bis=verzicht_bis,
        netto=netto, stufen=stufen)
    befunde = regeln.pruefe(
        **gemeinsam, basis_lik_punkte=zahl('basis_lik_punkte'), basis_lik_stand=stand,
        weitergabe_prozent=zahl('index_weitergabe_prozent'), intervall_monate=zahl('index_intervall_monate'),
        index_art=_roh(q.get('index_art')).lower() or None,
        hat_zeitplan=_roh(q.get('hat_zeitplan')).lower() in _WAHR)
    abg = regeln.abgeleitet(**gemeinsam)
    vorschlag_stand, vorschlag_punkte = regeln.basis_lik_vorschlag(beginn)

    return JsonResponse({
        'befunde': [b.als_dict() for b in befunde],
        'sperre': bool(regeln.sperren(befunde)),
        'abgeleitet': {
            'fest_bis': _iso(abg['fest_bis']),
            'mindest_ende': _iso(abg['mindest_ende']),
            'stufen': [{'ab': _iso(a), 'erhoehung': _betrag(e), 'neu': _betrag(n)} for a, e, n in abg['stufen']],
            'basis_lik': {'punkte': _betrag(vorschlag_punkte),
                          'stand': vorschlag_stand.strftime('%Y-%m') if vorschlag_stand else None},
        },
        'unlesbar': unlesbar,
    })
