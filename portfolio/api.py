# portfolio/api.py
from ninja import Router, Schema, File, Form
from ninja.files import UploadedFile
from django.shortcuts import get_object_or_404
from typing import List, Optional
from datetime import date
from decimal import Decimal
from .models import Liegenschaft, Einheit, Geraet, Zaehler, Schluessel, Unterhalt, Dokument
from .schemas import LiegenschaftListSchema, LiegenschaftDetailSchema, LiegenschaftUpdateSchema, EinheitSchemaOut, EinheitCreateSchema
from .services import sync_liegenschaft_with_gwr

router = Router(tags=["Portfolio"])

# ========================================================
# LIEGENSCHAFTEN
# ========================================================
@router.get("/liegenschaften", response=List[LiegenschaftListSchema])
def list_liegenschaften(request):
    return Liegenschaft.objects.all()

@router.get("/liegenschaften/{liegenschaft_id}", response=LiegenschaftDetailSchema)
def get_liegenschaft(request, liegenschaft_id: int):
    return get_object_or_404(Liegenschaft, id=liegenschaft_id)

@router.post("/liegenschaften", response={201: LiegenschaftListSchema})
def create_liegenschaft(request, payload: LiegenschaftUpdateSchema):
    neue_liegenschaft = Liegenschaft.objects.create(**payload.dict(exclude_unset=True))
    try: sync_liegenschaft_with_gwr(neue_liegenschaft)
    except Exception: pass
    return 201, neue_liegenschaft

@router.put("/liegenschaften/{liegenschaft_id}", response={200: dict})
def update_liegenschaft(request, liegenschaft_id: int, payload: LiegenschaftUpdateSchema):
    l = get_object_or_404(Liegenschaft, id=liegenschaft_id)
    for k, v in payload.dict(exclude_unset=True).items():
        setattr(l, k, v)
    l.save()
    return 200, {"success": True}

@router.delete("/liegenschaften/{liegenschaft_id}", response={204: None})
def delete_liegenschaft(request, liegenschaft_id: int):
    get_object_or_404(Liegenschaft, id=liegenschaft_id).delete()
    return 204, None


# ========================================================
# EINHEITEN
# ========================================================
@router.post("/liegenschaften/{liegenschaft_id}/einheiten", response={201: dict})
def create_einheit(request, liegenschaft_id: int, payload: EinheitCreateSchema):
    data = payload.dict(exclude_unset=True)
    Einheit.objects.create(liegenschaft=get_object_or_404(Liegenschaft, id=liegenschaft_id), **data)
    return 201, {"success": True}

@router.put("/einheiten/{einheit_id}", response=EinheitSchemaOut)
def update_einheit(request, einheit_id: int, payload: EinheitCreateSchema):
    einheit = get_object_or_404(Einheit, id=einheit_id)
    for attr, value in payload.dict(exclude_unset=True).items():
        setattr(einheit, attr, value)
    einheit.save()
    return einheit

@router.delete("/einheiten/{einheit_id}", response={204: None})
def delete_einheit(request, einheit_id: int):
    get_object_or_404(Einheit, id=einheit_id).delete()
    return 204, None


class LinkSchema(Schema): gehoert_zu_id: Optional[int]
@router.patch("/einheiten/{einheit_id}/link", response={200: dict})
def link_einheit(request, einheit_id: int, payload: LinkSchema):
    einheit = get_object_or_404(Einheit, id=einheit_id); einheit.gehoert_zu_id = payload.gehoert_zu_id; einheit.save(); return 200, {"success": True}

# ========================================================
# DOKUMENTE & UNTERHALT
# ========================================================
@router.post("/dokumente", response={201: dict})
def upload_dokument(request, titel: str = Form(...), kategorie: str = Form(...), liegenschaft_id: Optional[int] = Form(None), einheit_id: Optional[int] = Form(None), datei: UploadedFile = File(...)):
    Dokument.objects.create(titel=titel, kategorie=kategorie, liegenschaft_id=liegenschaft_id, einheit_id=einheit_id, datei=datei); return 201, {"success": True}

@router.delete("/dokumente/{id}", response={204: None})
def delete_dokument(request, id: int): get_object_or_404(Dokument, id=id).delete(); return 204, None

class UnterhaltCreateSchema(Schema): einheit_id: int; titel: str; beschreibung: str = ""; datum: date; kosten: Decimal = Decimal('0.00')
@router.post("/unterhalt", response={201: dict})
def create_unterhalt(request, payload: UnterhaltCreateSchema):
    e = get_object_or_404(Einheit, id=payload.einheit_id); Unterhalt.objects.create(liegenschaft=e.liegenschaft, einheit=e, titel=payload.titel, beschreibung=payload.beschreibung, datum=payload.datum, kosten=payload.kosten); return 201, {"success": True}
@router.delete("/unterhalt/{id}", response={204: None})
def delete_unterhalt(request, id: int): get_object_or_404(Unterhalt, id=id).delete(); return 204, None

# ========================================================
# GERÄTE (Hier ist der Fix für die Haustechnik!)
# ========================================================
class GeraetCreateSchema(Schema):
    # 🔥 GEFIXT: Beide IDs sind jetzt optional!
    einheit_id: Optional[int] = None
    liegenschaft_id: Optional[int] = None
    kategorie: str
    sonstiges_bezeichnung: str = ""
    marke: str = ""
    modell: str = ""
    installations_datum: Optional[date] = None
    garantie_bis: Optional[date] = None

@router.post("/geraete", response={201: dict})
def create_geraet(request, payload: GeraetCreateSchema):
    data = payload.dict(exclude={'einheit_id', 'liegenschaft_id'}, exclude_unset=True)

    # Checken, ob das Gerät zur Liegenschaft oder zur Einheit gehört
    if payload.liegenschaft_id:
        l = get_object_or_404(Liegenschaft, id=payload.liegenschaft_id)
        Geraet.objects.create(liegenschaft=l, **data)
    elif payload.einheit_id:
        e = get_object_or_404(Einheit, id=payload.einheit_id)
        Geraet.objects.create(einheit=e, **data)

    return 201, {"success": True}

@router.put("/geraete/{id}", response={200: dict})
def update_geraet(request, id: int, payload: GeraetCreateSchema):
    g = get_object_or_404(Geraet, id=id)
    for k, v in payload.dict(exclude_unset=True, exclude={'einheit_id', 'liegenschaft_id'}).items():
        setattr(g, k, v)
    g.save()
    return 200, {"success": True}

@router.delete("/geraete/{id}", response={204: None})
def delete_geraet(request, id: int):
    get_object_or_404(Geraet, id=id).delete()
    return 204, None

# ========================================================
# ZÄHLER & SCHLÜSSEL
# ========================================================
class ZaehlerCreateSchema(Schema): einheit_id: int; typ: str; zaehler_nummer: str; standort: str = ""; aktueller_stand: Decimal = Decimal('0.00')
@router.post("/zaehler", response={201: dict})
def create_zaehler(request, payload: ZaehlerCreateSchema): Zaehler.objects.create(einheit=get_object_or_404(Einheit, id=payload.einheit_id), **payload.dict(exclude={'einheit_id'})); return 201, {"success": True}
@router.delete("/zaehler/{id}", response={204: None})
def delete_zaehler(request, id: int): get_object_or_404(Zaehler, id=id).delete(); return 204, None

class SchluesselCreateSchema(Schema): einheit_id: int; typ: str; schluessel_nummer: str; anzahl: int
@router.post("/schluessel", response={201: dict})
def create_schluessel(request, payload: SchluesselCreateSchema): e = get_object_or_404(Einheit, id=payload.einheit_id); Schluessel.objects.create(liegenschaft=e.liegenschaft, einheit=e, **payload.dict(exclude={'einheit_id'})); return 201, {"success": True}
@router.delete("/schluessel/{id}", response={204: None})
def delete_schluessel(request, id: int): get_object_or_404(Schluessel, id=id).delete(); return 204, None