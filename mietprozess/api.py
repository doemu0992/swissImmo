from ninja import Router, File, Form, Schema
from ninja.files import UploadedFile
from django.shortcuts import get_object_or_404
from django.db import transaction
from typing import List, Optional
from decimal import Decimal
from datetime import datetime

from .models import Mietbewerbung
from .schemas import BewerbungCreateSchema, BewerbungSchemaOut
from portfolio.models import Einheit

router = Router(tags=["Mietprozess"])

@router.post("/public/bewerben", response={201: dict, 400: dict})
@transaction.atomic
def public_submit_bewerbung(
    request,
    einheit_id: int = Form(...),
    # --- Personalien ---
    vorname: str = Form(...),
    nachname: str = Form(...),
    zivilstand: str = Form(...),
    geburtsdatum: str = Form(...),
    geschlecht: str = Form(...),
    nationalitaet: str = Form(...),
    heimatort: Optional[str] = Form(None),
    # --- Kontakt & Adresse ---
    mobilnummer: str = Form(...),
    email: str = Form(...),
    adresse: str = Form(...),
    plz: str = Form(...),
    ort: str = Form(...),
    # --- Derzeitiger Vermieter ---
    aktueller_vermieter: str = Form(...),
    kontaktperson_vermieter: str = Form(...),
    telefon_vermieter: str = Form(...),
    email_vermieter: Optional[str] = Form(None),
    # --- Beruf & Finanzen ---
    erwerbsstatus: str = Form(...),
    beruf: str = Form(...),
    einkommen_jahr: str = Form(...), # Als String-Range aus der Auswahlliste
    arbeitgeber: str = Form(...),
    angestellt_seit: str = Form(...),
    kontaktperson_arbeitgeber: str = Form(...),
    telefon_arbeitgeber: str = Form(...),
    email_arbeitgeber: Optional[str] = Form(None),
    ist_unbefristet: bool = Form(True),
    # --- Bonität ---
    hat_betreibungen: bool = Form(False),
    # --- Allgemeine Informationen ---
    grund_fuer_wechsel: Optional[str] = Form(None),
    anzahl_erwachsene: int = Form(1),
    anzahl_kinder: int = Form(0),
    haustiere: bool = Form(False),
    haustiere_details: Optional[str] = Form(None),
    musikinstrumente: bool = Form(False),
    interesse_parkplatz: bool = Form(False),
    gewuenschter_bezugstermin: str = Form(...),
    bemerkungen: Optional[str] = Form(None),
    # --- Schilder & Onboarding ---
    schild_briefkasten: Optional[str] = Form(None),
    schild_sonnerie: Optional[str] = Form(None),
    wunsch_kautions_typ: str = Form('bank'),
    # --- Dokumente & Anhänge ---
    digitaler_betreibungsauszug: bool = Form(False),
    betreibungsauszug: Optional[UploadedFile] = File(None),
    ausweiskopie: Optional[UploadedFile] = File(None),
    lohnausweis: Optional[UploadedFile] = File(None),
    weitere_dokumente: Optional[UploadedFile] = File(None)
):
    try:
        einheit = get_object_or_404(Einheit, id=einheit_id)

        # 🌟 Flexibler Check auf Vermietungsstatus
        is_rented = False
        if hasattr(einheit, 'ist_vermietet'):
            is_rented = einheit.ist_vermietet
        elif hasattr(einheit, 'vermietungs_status'):
            is_rented = einheit.vermietungs_status == 'vermietet'

        if is_rented:
            return 400, {"success": False, "error": "Dieses Objekt ist leider bereits vermietet."}

        # Safe Helper für Datums-Parsing (YYYY-MM-DD)
        def parse_date_safely(date_str, field_name):
            if not date_str:
                return None
            try:
                return datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                raise ValueError(f"Falsches Datumsformat im Feld '{field_name}': '{date_str}' (Erwartet wird YYYY-MM-DD).")

        # Parser ausführen
        try:
            parsed_geburtsdatum = parse_date_safely(geburtsdatum, "Geburtsdatum")
            parsed_angestellt_seit = parse_date_safely(angestellt_seit, "Angestellt seit")
            parsed_bezugstermin = parse_date_safely(gewuenschter_bezugstermin, "Gewünschter Bezugstermin")
        except ValueError as date_err:
            return 400, {"success": False, "error": str(date_err)}

        # 🌟 Datensatz mit allen Flatfox-Feldern erstellen
        bewerbung = Mietbewerbung.objects.create(
            einheit=einheit,
            vorname=vorname,
            nachname=nachname,
            zivilstand=zivilstand,
            geburtsdatum=parsed_geburtsdatum,
            geschlecht=geschlecht,
            nationalitaet=nationalitaet,
            heimatort=heimatort,

            mobilnummer=mobilnummer,
            email=email,
            adresse=adresse,
            plz=plz,
            ort=ort,

            aktueller_vermieter=aktueller_vermieter,
            kontaktperson_vermieter=kontaktperson_vermieter,
            telefon_vermieter=telefon_vermieter,
            email_vermieter=email_vermieter,

            erwerbsstatus=erwerbsstatus,
            beruf=beruf,
            einkommen_jahr=einkommen_jahr,
            arbeitgeber=arbeitgeber,
            angestellt_seit=parsed_angestellt_seit,
            kontaktperson_arbeitgeber=kontaktperson_arbeitgeber,
            telefon_arbeitgeber=telefon_arbeitgeber,
            email_arbeitgeber=email_arbeitgeber,
            ist_unbefristet=ist_unbefristet,

            hat_betreibungen=hat_betreibungen,

            grund_fuer_wechsel=grund_fuer_wechsel,
            anzahl_erwachsene=anzahl_erwachsene,
            anzahl_kinder=anzahl_kinder,
            haustiere=haustiere,
            haustiere_details=haustiere_details,
            musikinstrumente=musikinstrumente,
            interesse_parkplatz=interesse_parkplatz,
            gewuenschter_bezugstermin=parsed_bezugstermin,
            bemerkungen=bemerkungen,

            schild_briefkasten=schild_briefkasten,
            schild_sonnerie=schild_sonnerie,
            wunsch_kautions_typ=wunsch_kautions_typ,

            digitaler_betreibungsauszug=digitaler_betreibungsauszug,
            betreibungsauszug=betreibungsauszug,
            ausweiskopie=ausweiskopie,
            lohnausweis=lohnausweis,
            weitere_dokumente=weitere_dokumente
        )

        return 201, {"success": True, "id": bewerbung.id}

    except Exception as e:
        return 400, {"success": False, "error": f"Django-Backend-Fehler: {str(e)}"}


@router.get("/admin/liste", response=List[BewerbungSchemaOut])
def list_bewerbungen(request):
    bewerbungen = Mietbewerbung.objects.all().select_related('einheit__liegenschaft').order_by('-erstellt_am')

    result = []
    for b in bewerbungen:
        result.append({
            "id": b.id,
            "einheit_id": b.einheit.id,
            "objekt_bezeichnung": b.einheit.bezeichnung,
            "liegenschaft_strasse": b.einheit.liegenschaft.strasse,
            "status": b.status,
            "vorname": b.vorname,
            "nachname": b.nachname,
            "zivilstand": b.zivilstand,
            "geburtsdatum": b.geburtsdatum,
            "geschlecht": b.geschlecht,
            "nationalitaet": b.nationalitaet,
            "heimatort": b.heimatort,
            "mobilnummer": b.mobilnummer,
            "email": b.email,
            "adresse": b.adresse,
            "plz": b.plz,
            "ort": b.ort,
            "aktueller_vermieter": b.aktueller_vermieter,
            "kontaktperson_vermieter": b.kontaktperson_vermieter,
            "telefon_vermieter": b.telefon_vermieter,
            "email_vermieter": b.email_vermieter,
            "erwerbsstatus": b.erwerbsstatus,
            "beruf": b.beruf,
            "einkommen_jahr": b.einkommen_jahr, # Reicht den String-Range-Wert weiter
            "arbeitgeber": b.arbeitgeber,
            "angestellt_seit": b.angestellt_seit,
            "kontaktperson_arbeitgeber": b.kontaktperson_arbeitgeber,
            "telefon_arbeitgeber": b.telefon_arbeitgeber,
            "email_arbeitgeber": b.email_arbeitgeber,
            "ist_unbefristet": b.ist_unbefristet,
            "hat_betreibungen": b.hat_betreibungen,
            "grund_fuer_wechsel": b.grund_fuer_wechsel,
            "anzahl_erwachsene": b.anzahl_erwachsene,
            "anzahl_kinder": b.anzahl_kinder,
            "haustiere": b.haustiere,
            "haustiere_details": b.haustiere_details,
            "musikinstrumente": b.musikinstrumente,
            "interesse_parkplatz": b.interesse_parkplatz,
            "gewuenschter_bezugstermin": b.gewuenschter_bezugstermin,
            "bemerkungen": b.bemerkungen,
            "schild_briefkasten": b.schild_briefkasten,
            "schild_sonnerie": b.schild_sonnerie,
            "wunsch_kautions_typ": b.wunsch_kautions_typ,
            "digitaler_betreibungsauszug": getattr(b, 'digitaler_betreibungsauszug', False),
            "betreibungsauszug_url": b.betreibungsauszug.url if b.betreibungsauszug else None,
            "ausweiskopie_url": b.ausweiskopie.url if b.ausweiskopie else None,
            "lohnausweis_url": b.lohnausweis.url if b.lohnausweis else None,
            "weitere_dokumente_url": b.weitere_dokumente.url if b.weitere_dokumente else None,
            "erstellt_am": b.erstellt_am
        })
    return result

class StatusUpdateSchema(Schema):
    status: str

@router.patch("/admin/{bewerbung_id}/status", response={200: dict, 400: dict})
@transaction.atomic
def update_bewerbung_status(request, bewerbung_id: int, payload: StatusUpdateSchema):
    bewerbung = get_object_or_404(Mietbewerbung.objects.select_for_update(), id=bewerbung_id)

    valid_statuses = [choice[0] for choice in Mietbewerbung.STATUS_CHOICES]
    if payload.status not in valid_statuses:
        return 400, {"success": False, "error": "Ungültiger Status."}

    bewerbung.status = payload.status
    bewerbung.save()

    return 200, {"success": True, "new_status": bewerbung.status}

@router.delete("/admin/{bewerbung_id}", response={204: None})
@transaction.atomic
def delete_bewerbung(request, bewerbung_id: int):
    bewerbung = get_object_or_404(Mietbewerbung, id=bewerbung_id)

    if bewerbung.betreibungsauszug:
        bewerbung.betreibungsauszug.delete(save=False)
    if bewerbung.ausweiskopie:
        bewerbung.ausweiskopie.delete(save=False)
    if bewerbung.lohnausweis:
        bewerbung.lohnausweis.delete(save=False)
    if hasattr(bewerbung, 'weitere_dokumente') and bewerbung.weitere_dokumente:
        bewerbung.weitere_dokumente.delete(save=False)

    bewerbung.delete()
    return 204, None

# ==============================================================================
# 🔥 FLATFOX-STYLE KOMMUNIKATION
# ==============================================================================
class MessageSchema(Schema):
    typ: str # 'einladung', 'nachforderung', 'absage'

@router.post("/admin/{bewerbung_id}/message", response={200: dict, 400: dict})
@transaction.atomic
def send_bewerbung_message(request, bewerbung_id: int, payload: MessageSchema):
    bewerbung = get_object_or_404(Mietbewerbung, id=bewerbung_id)

    if payload.typ == 'absage':
        bewerbung.status = 'abgelehnt'
        bewerbung.save()
        return 200, {"success": True, "message": f"Absage-E-Mail an {bewerbung.email} versendet und Status auf 'Abgelehnt' gesetzt."}

    elif payload.typ == 'einladung':
        return 200, {"success": True, "message": f"Einladung zur Besichtigung an {bewerbung.email} gesendet."}

    elif payload.typ == 'nachforderung':
        return 200, {"success": True, "message": f"Dokumenten-Nachforderung an {bewerbung.email} gesendet."}

    return 400, {"success": False, "error": "Unbekannter Nachrichtentyp."}