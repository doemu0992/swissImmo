# finance/api.py
from ninja import Router
from django.shortcuts import get_object_or_404
from django.db.models import Sum
from django.utils import timezone
from typing import List
from decimal import Decimal
from .models import Zahlungseingang
from rentals.models import Mietvertrag
from .schemas import ZahlungSchemaOut, ZahlungCreateSchema, MietzinsKontrolleSchema

router = Router(tags=["Finanzen"])

@router.get("/zahlungen", response=List[ZahlungSchemaOut])
def list_zahlungen(request):
    """Liste der letzten 50 Zahlungseingänge."""
    return Zahlungseingang.objects.all().select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft').order_by('-datum_eingang')[:50]

@router.post("/zahlungen", response={201: dict})
def create_zahlung(request, payload: ZahlungCreateSchema):
    """Verbucht einen neuen Zahlungseingang."""
    vertrag = get_object_or_404(Mietvertrag, id=payload.vertrag_id)
    Zahlungseingang.objects.create(
        vertrag=vertrag,
        betrag=payload.betrag,
        datum_eingang=payload.datum_eingang,
        buchungs_monat=payload.buchungs_monat.replace(day=1), # Immer auf den 1. des Monats normieren
        bemerkung=payload.bemerkung,
        liegenschaft=vertrag.einheit.liegenschaft
    )
    return 201, {"success": True}

@router.get("/mietzins-kontrolle", response=List[MietzinsKontrolleSchema])
def get_kontrolle(request):
    """Berechnet den Soll-Ist-Abgleich für den aktuellen Monat."""
    heute = timezone.now().date()
    aktueller_monat = heute.replace(day=1)

    aktive_vertraege = Mietvertrag.objects.filter(aktiv=True).select_related('mieter', 'einheit__liegenschaft')
    ergebnis = []

    for v in aktive_vertraege:
        soll = (v.netto_mietzins or 0) + (v.nebenkosten or 0)
        ist = Zahlungseingang.objects.filter(
            vertrag=v,
            buchungs_monat=aktueller_monat
        ).aggregate(total=Sum('betrag'))['total'] or Decimal('0.00')

        diff = soll - ist
        status = 'Bezahlt' if ist >= soll else ('Teilzahlung' if ist > 0 else 'Offen')

        ergebnis.append({
            "vertrag_id": v.id,
            "mieter_name": str(v.mieter),
            "objekt": f"{v.einheit.liegenschaft.strasse} ({v.einheit.bezeichnung})",
            "soll": soll,
            "ist": ist,
            "differenz": diff,
            "status": status
        })

    return ergebnis

@router.delete("/zahlungen/{zahlung_id}", response={204: None})
def delete_zahlung(request, zahlung_id: int):
    get_object_or_404(Zahlungseingang, id=zahlung_id).delete()
    return 204, None