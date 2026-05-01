# crm/api.py
from ninja import Router
from django.shortcuts import get_object_or_404
from django.core.exceptions import ObjectDoesNotExist
from typing import List
from .models import Mieter, Verwaltung  # 🔥 Verwaltung hinzugefügt
from .schemas import MieterSchemaOut, MieterUpdateSchema
from core.utils import get_current_ref_zins, get_current_lik
from core.utils.qr_code import generate_mieter_qr_pdf  # 🔥 Echter PDF-Generator importiert

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

# LÖSCH-ENDPUNKT FÜR DOKUMENTE
@router.delete("/dokumente/{id}", response={200: dict, 404: dict, 500: dict})
def delete_mieter_dokument(request, id: int):
    try:
        if id >= 10000:
            from rentals.models import Dokument as RentalsDokument
            doc = RentalsDokument.objects.get(id=id - 10000)
        else:
            try:
                from portfolio.models import Dokument as PortfolioDokument
                doc = PortfolioDokument.objects.get(id=id)
            except (ObjectDoesNotExist, ImportError):
                from rentals.models import Dokument as RentalsDokument
                doc = RentalsDokument.objects.get(id=id)

        if hasattr(doc, 'datei') and doc.datei:
            try:
                doc.datei.delete(save=False)
            except Exception:
                pass

        doc.delete()
        return 200, {"success": True}

    except ObjectDoesNotExist:
        return 404, {"success": False, "error": "Dokument nicht gefunden."}
    except Exception as e:
        return 500, {"success": False, "error": str(e)}

# 🔥 JETZ ECHT: QR-Code Endpunkt
@router.get("/mieter/{mieter_id}/qr-rechnung")
def generate_mieter_qr(request, mieter_id: int):
    m = get_object_or_404(Mieter, id=mieter_id)
    verwaltung = Verwaltung.objects.first()

    if not verwaltung:
        return 400, {"success": False, "error": "Keine Verwaltungsdaten hinterlegt."}

    # Den aktuellsten aktiven Vertrag suchen, um den Betrag zu erhalten
    vertrag = m.vertraege.filter(status='aktiv').first()
    if not vertrag:
        # Fallback auf den neusten Vertrag, falls keiner "aktiv" markiert ist
        vertrag = m.vertraege.order_by('-id').first()

    if not vertrag:
        return 400, {"success": False, "error": "Kein Mietvertrag für diesen Mieter gefunden."}

    try:
        # Ruft deine Logik in core/utils/qr_code.py auf
        pdf_url = generate_mieter_qr_pdf(m, vertrag, verwaltung)
        return {"success": True, "url": pdf_url}
    except Exception as e:
        return 500, {"success": False, "error": f"Fehler bei der QR-Erstellung: {str(e)}"}

# Endpunkt für die globalen Basiswerte
@router.get("/basiswerte", response=dict)
def get_global_basiswerte(request):
    return {
        "ref_zins": get_current_ref_zins(),
        "lik_punkte": get_current_lik()
    }