"""Lesende Finanz-API (`/api/v1/`): Kontenplan, Buchungsjournal und offene Debitoren einer Verwaltung, für Treuhand und Buchhaltungssoftware.

Nur GET, nur Lesen, nur die Verwaltung, zu der der Schlüssel gehört (`core/api_token.py`). Jede Abfrage läuft im
Mandantenkontext des Schlüssels; ein Schlüssel kann also nie fremde Zeilen sehen. Das Journal ist seitenweise
(`offset`, `limit` ≤ 500) und nach Datum und Belegnummer sortiert; Stornobuchungen stehen als eigene Zeilen."""
from datetime import date

from ninja import Router
from ninja.errors import HttpError

from core.api_token import TokenAuth
from core.tenancy import organisation_kontext

router = Router(tags=['Finanzen'], auth=TokenAuth())

MAX_LIMIT = 500


def _konto(k):
    return {'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'typ': k.typ}


@router.get('/konten')
def konten(request):
    from finance.models import Buchungskonto
    with organisation_kontext(request.api_token.organisation):
        return {'konten': [_konto(k) for k in Buchungskonto.objects.order_by('nummer')]}


def _datum(wert, name):
    if wert in (None, ''):
        return None
    try:
        return date.fromisoformat(wert)
    except ValueError:
        raise HttpError(422, f'{name}: erwartet JJJJ-MM-TT.')


@router.get('/buchungen')
def buchungen(request, von: str = None, bis: str = None, offset: int = 0, limit: int = 100):
    from finance.models import Buchung
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    d_von, d_bis = _datum(von, 'von'), _datum(bis, 'bis')
    with organisation_kontext(request.api_token.organisation):
        qs = Buchung.objects.select_related('soll_konto', 'haben_konto')
        if d_von:
            qs = qs.filter(datum__gte=d_von)
        if d_bis:
            qs = qs.filter(datum__lte=d_bis)
        qs = qs.order_by('datum', 'beleg_nr', 'pk')
        gesamt = qs.count()
        zeilen = [{
            'beleg_nr': b.beleg_nr, 'datum': b.datum.isoformat(), 'text': b.beleg_text,
            'soll': b.soll_konto.nummer, 'haben': b.haben_konto.nummer, 'betrag': str(b.betrag),
            'storno': b.ist_storno, 'storno_von_beleg_nr': b.storno_von.beleg_nr if b.storno_von_id else None,
        } for b in qs.select_related('storno_von')[offset:offset + limit]]
    return {'gesamt': gesamt, 'offset': offset, 'limit': limit, 'buchungen': zeilen}


@router.get('/debitoren/offen')
def debitoren_offen(request, offset: int = 0, limit: int = 100):
    """Offene Posten der Debitoren (offen und teilbezahlt), nach Fälligkeit. Ohne Namen von Personen: nur Rechnungsdaten."""
    from finance.models import DebitorenRechnung
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    with organisation_kontext(request.api_token.organisation):
        qs = (DebitorenRechnung.objects.filter(status__in=('offen', 'teilbezahlt'))
              .prefetch_related('zahlungseingaenge').order_by('faellig_am', 'pk'))
        gesamt = qs.count()
        zeilen = [{
            'id': r.pk, 'titel': r.titel, 'datum': r.datum.isoformat(),
            'faellig_am': r.faellig_am.isoformat() if r.faellig_am else None, 'status': r.status,
            'betrag': str(r.betrag), 'offener_betrag': str(r.offener_betrag),
            'mwst_satz': str(r.mwst_satz), 'mwst_betrag': str(r.mwst_betrag),
        } for r in qs[offset:offset + limit]]
    return {'gesamt': gesamt, 'offset': offset, 'limit': limit, 'debitoren': zeilen}
