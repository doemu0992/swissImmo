# crm/api.py
from ninja import Router, Schema
from django.shortcuts import get_object_or_404
from django.core.exceptions import ObjectDoesNotExist
from typing import List, Optional
from .models import Mieter, Verwaltung, Handwerker  # 🔥 Handwerker importiert
from .schemas import MieterSchemaOut, MieterUpdateSchema
from core.utils import get_current_ref_zins, get_current_lik
from core.utils.qr_code import generate_mieter_qr_pdf

from core.auth import auth_schreiben, auth_verwaltung, log_aktion

router = Router(tags=["CRM"])

# ==========================================
# MIETER / KONTAKTE
# ==========================================

@router.get("/mieter", response=List[MieterSchemaOut])
def list_mieter(request):
    # Fällige Adresswechsel werden NICHT hier (Lesepfad) mutiert — GET muss
    # seiteneffektfrei bleiben (Leserolle darf nichts schreiben). Der Wechsel
    # läuft im täglichen Scheduler (run_adress_umzuege / taeglicher_lauf).
    return sorted(list(Mieter.objects.all()), key=lambda x: x.display_name.lower())

@router.get("/mieter/{mieter_id}", response=MieterSchemaOut)
def get_mieter(request, mieter_id: int):
    return get_object_or_404(Mieter, id=mieter_id)

@router.post("/mieter", response={201: MieterSchemaOut}, auth=auth_schreiben)
def create_mieter(request, payload: MieterUpdateSchema):
    data = payload.dict(exclude_unset=True)
    neuer_mieter = Mieter.objects.create(**data)
    return 201, neuer_mieter

@router.put("/mieter/{mieter_id}", response={200: dict}, auth=auth_schreiben)
def update_mieter(request, mieter_id: int, payload: MieterUpdateSchema):
    m = get_object_or_404(Mieter, id=mieter_id)
    for k, v in payload.dict(exclude_unset=True).items():
        setattr(m, k, v)
    m.save()
    return 200, {"success": True}

@router.delete("/mieter/{mieter_id}", response={204: None, 409: dict}, auth=auth_verwaltung)
def delete_mieter(request, mieter_id: int):
    mieter = get_object_or_404(Mieter, id=mieter_id)
    # Wie im UI-Pfad (fw_person_loeschen): bei aktivem Vertrag blockieren …
    aktive = mieter.vertraege.filter(status='aktiv').count()
    if aktive:
        return 409, {"success": False,
                     "error": f"Person hat {aktive} aktive(n) Vertrag/Verträge — zuerst kündigen/beenden."}
    # … und den verknüpften Mieterportal-Login mitentfernen (sonst bleibt ein
    # Login zurück, dessen user.mieter_profil ins Leere zeigt).
    if mieter.benutzer_id:
        try:
            mieter.benutzer.delete()
        except Exception:
            pass
    log_aktion(request, "Mieter gelöscht", mieter.display_name, f"Mieter-ID {mieter.id}")
    mieter.delete()
    return 204, None

@router.post("/mieter/{mieter_id}/cancel-umzug", auth=auth_schreiben)
def cancel_umzug(request, mieter_id: int):
    m = get_object_or_404(Mieter, id=mieter_id)
    m.zukuenftige_strasse = ''
    m.zukuenftige_plz = ''
    m.zukuenftiger_ort = ''
    m.zukuenftig_ab = None
    m.save()
    return 200, {"success": True}


# ==========================================
# 🔥 NEU: HANDWERKER / PARTNER
# ==========================================

class HandwerkerInSchema(Schema):
    firma: str
    kontaktperson: Optional[str] = None
    email: str
    telefon: Optional[str] = None
    branche: str

@router.post("/handwerker", response={200: dict}, auth=auth_schreiben)
def create_handwerker(request, payload: HandwerkerInSchema):
    h = Handwerker.objects.create(**payload.dict())
    return 200, {"success": True, "id": h.id}

@router.put("/handwerker/{h_id}", response={200: dict}, auth=auth_schreiben)
def update_handwerker(request, h_id: int, payload: HandwerkerInSchema):
    h = get_object_or_404(Handwerker, id=h_id)
    for attr, value in payload.dict().items():
        setattr(h, attr, value)
    h.save()
    return 200, {"success": True}

@router.delete("/handwerker/{h_id}", response={200: dict}, auth=auth_verwaltung)
def delete_handwerker(request, h_id: int):
    h = get_object_or_404(Handwerker, id=h_id)
    h.delete()
    return 200, {"success": True}


# ==========================================
# DOKUMENTE & TOOLS
# ==========================================

@router.delete("/dokumente/{id}", response={200: dict, 404: dict, 500: dict}, auth=auth_verwaltung)
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

@router.get("/mieter/{mieter_id}/qr-rechnung")
def generate_mieter_qr(request, mieter_id: int):
    m = get_object_or_404(Mieter, id=mieter_id)
    verwaltung = Verwaltung.objects.first()

    if not verwaltung:
        return 400, {"success": False, "error": "Keine Verwaltungsdaten hinterlegt."}

    vertrag = m.vertraege.filter(status='aktiv').first()
    if not vertrag:
        vertrag = m.vertraege.order_by('-id').first()

    if not vertrag:
        return 400, {"success": False, "error": "Kein Mietvertrag für diesen Mieter gefunden."}

    try:
        pdf_url = generate_mieter_qr_pdf(m, vertrag, verwaltung)
        return {"success": True, "url": pdf_url}
    except Exception as e:
        return 500, {"success": False, "error": f"Fehler bei der QR-Erstellung: {str(e)}"}

@router.get("/basiswerte", response=dict)
def get_global_basiswerte(request):
    return {
        "ref_zins": get_current_ref_zins(),
        "lik_punkte": get_current_lik()
    }