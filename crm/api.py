# crm/api.py
from ninja import Router
from django.shortcuts import get_object_or_404
from django.core.exceptions import ObjectDoesNotExist
from typing import List
from .models import Mieter
from .schemas import MieterSchemaOut, MieterUpdateSchema
from core.utils import get_current_ref_zins, get_current_lik # 🔥 NEU: Import für die Basiswerte

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

# 🔥 LÖSCH-ENDPUNKT FÜR DOKUMENTE (Fix für den Mieter-Tab)
@router.delete("/dokumente/{id}", response={200: dict, 404: dict, 500: dict})
def delete_mieter_dokument(request, id: int):
    try:
        # 1. Wenn ID >= 10000: Es ist ein Mietvertrag aus dem Rentals-Modul
        if id >= 10000:
            from rentals.models import Dokument as RentalsDokument
            doc = RentalsDokument.objects.get(id=id - 10000)
        else:
            # 2. Normales Dokument: Erst im Portfolio suchen, sonst in Rentals
            try:
                from portfolio.models import Dokument as PortfolioDokument
                doc = PortfolioDokument.objects.get(id=id)
            except (ObjectDoesNotExist, ImportError):
                from rentals.models import Dokument as RentalsDokument
                doc = RentalsDokument.objects.get(id=id)

        # 3. Physische PDF-Datei löschen
        if hasattr(doc, 'datei') and doc.datei:
            try:
                doc.datei.delete(save=False)
            except Exception:
                pass

        # 4. Datenbank-Eintrag löschen
        doc.delete()
        return 200, {"success": True}

    except ObjectDoesNotExist:
        return 404, {"success": False, "error": "Dokument nicht gefunden."}
    except Exception as e:
        return 500, {"success": False, "error": str(e)}

# QR-Code Endpunkt
@router.get("/mieter/{mieter_id}/qr-rechnung")
def generate_mieter_qr(request, mieter_id: int):
    m = get_object_or_404(Mieter, id=mieter_id)
    return {"success": True, "url": f"/media/qr/qr_demo_mieter_{m.id}.pdf"}

# 🔥 NEU: Endpunkt für die globalen Basiswerte (Referenzzinssatz & LIK)
@router.get("/basiswerte", response=dict)
def get_global_basiswerte(request):
    return {
        "ref_zins": get_current_ref_zins(),
        "lik_punkte": get_current_lik()
    }