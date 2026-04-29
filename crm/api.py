# crm/api.py
from ninja import Router
from django.shortcuts import get_object_or_404
from typing import List
from .models import Mieter
from .schemas import MieterSchemaOut, MieterUpdateSchema

router = Router(tags=["CRM"])

@router.get("/mieter", response=List[MieterSchemaOut])
def list_mieter(request):
    return sorted(list(Mieter.objects.all()), key=lambda x: x.display_name.lower())

@router.get("/mieter/{mieter_id}", response=MieterSchemaOut)
def get_mieter(request, mieter_id: int):
    return get_object_or_404(Mieter, id=mieter_id)

@router.post("/mieter", response={201: MieterSchemaOut})
def create_mieter(request, payload: MieterUpdateSchema):
    data = payload.dict(exclude_unset=True)
    neuer_mieter = Mieter.objects.create(**data)
    return 201, neuer_mieter

@router.put("/mieter/{mieter_id}", response={200: dict})
def update_mieter(request, mieter_id: int, payload: MieterUpdateSchema):
    m = get_object_or_404(Mieter, id=mieter_id)
    for k, v in payload.dict(exclude_unset=True).items():
        setattr(m, k, v)
    m.save()
    return 200, {"success": True}

@router.delete("/mieter/{mieter_id}", response={204: None})
def delete_mieter(request, mieter_id: int):
    get_object_or_404(Mieter, id=mieter_id).delete()
    return 204, None

# 🔥 NEU: QR-Code Endpunkt
@router.get("/mieter/{mieter_id}/qr-rechnung")
def generate_mieter_qr(request, mieter_id: int):
    m = get_object_or_404(Mieter, id=mieter_id)
    # Hier simulieren wir die PDF-Rückgabe fürs Frontend.
    # (Der echte PDF-Generator wird hier später eingebunden)
    return {"success": True, "url": f"/media/qr/qr_demo_mieter_{m.id}.pdf"}