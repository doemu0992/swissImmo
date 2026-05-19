# finance/api.py
from ninja import Router, File, Schema
from ninja.files import UploadedFile
from django.shortcuts import get_object_or_404
from django.db.models import Sum
from django.utils import timezone
from django.db import transaction # 🔥 NEU: Der Schutz vor Doppelbuchungen
from typing import List, Optional
from decimal import Decimal
from datetime import date
import calendar

from .models import Zahlungseingang, KreditorenRechnung, Buchungskonto, Buchung, DebitorenRechnung, AbrechnungsPeriode
from rentals.models import Mietvertrag
from crm.models import Verwaltung
from core.utils.qr_code import generate_mahnung_pdf
from .utils import scan_invoice_pdf
from .schemas import ZahlungSchemaOut, ZahlungCreateSchema, MietzinsKontrolleSchema

router = Router(tags=["Finanzen"])

# ========================================================
# DEBITOREN / ZAHLUNGEN / SOLLSTELLUNG
# ========================================================

class SollstellungSchema(Schema):
    monat: int
    jahr: int

@router.post("/debitoren/sollstellung", response={200: dict, 400: dict})
@transaction.atomic # 🔥 Schützt vor parallelen Ausführungen
def run_sollstellung(request, payload: SollstellungSchema):
    """Führt den monatlichen Mietenlauf durch und bucht die Sollstellungen."""
    start_date = date(payload.jahr, payload.monat, 1)
    _, last_day = calendar.monthrange(payload.jahr, payload.monat)
    end_date = date(payload.jahr, payload.monat, last_day)

    vertraege = Mietvertrag.objects.filter(
        status='aktiv',
        beginn__lte=end_date
    ).exclude(ende__lt=start_date)

    try:
        konto_debitoren = Buchungskonto.objects.get(nummer="1100")
        konto_ertrag = Buchungskonto.objects.get(nummer="3000")
        konto_nk_akonto = Buchungskonto.objects.get(nummer="3020")
    except Buchungskonto.DoesNotExist:
        return 400, {"success": False, "error": "Standard-Konten (1100, 3000, 3020) fehlen. Bitte zuerst Kontenplan laden."}

    erstellt = 0
    titel_vorlage = f"Miete & NK {payload.monat:02d}/{payload.jahr}"

    for v in vertraege:
        # 🔥 STRIKTERER CHECK: Gibt es in diesem Monat schon eine Debitorenrechnung für diesen Vertrag?
        if DebitorenRechnung.objects.filter(vertrag=v, titel=titel_vorlage).exists():
            continue

        total_betrag = (v.netto_mietzins or Decimal('0.00')) + (v.nebenkosten or Decimal('0.00'))
        if total_betrag <= 0:
            continue

        rechnung = DebitorenRechnung.objects.create(
            vertrag=v,
            liegenschaft=v.einheit.liegenschaft,
            einheit=v.einheit,
            titel=titel_vorlage,
            betrag=total_betrag,
            faellig_am=start_date
        )

        if v.netto_mietzins and v.netto_mietzins > 0:
            Buchung.objects.create(
                datum=start_date,
                beleg_text=f"Mietertrag {v.mieter} - {payload.monat:02d}/{payload.jahr}",
                liegenschaft=v.einheit.liegenschaft,
                soll_konto=konto_debitoren,
                haben_konto=konto_ertrag,
                betrag=v.netto_mietzins,
                debitoren_rechnung=rechnung
            )

        if v.nebenkosten and v.nebenkosten > 0:
            Buchung.objects.create(
                datum=start_date,
                beleg_text=f"NK-Akonto {v.mieter} - {payload.monat:02d}/{payload.jahr}",
                liegenschaft=v.einheit.liegenschaft,
                soll_konto=konto_debitoren,
                haben_konto=konto_nk_akonto,
                betrag=v.nebenkosten,
                debitoren_rechnung=rechnung
            )

        erstellt += 1

    return 200, {"success": True, "erstellt": erstellt}

@router.get("/zahlungen", response=List[ZahlungSchemaOut])
def list_zahlungen(request):
    """Liste der letzten 50 Zahlungseingänge."""
    return Zahlungseingang.objects.all().select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft').order_by('-datum_eingang')[:50]

@router.post("/zahlungen", response={201: dict, 400: dict})
@transaction.atomic # 🔥
def create_zahlung(request, payload: ZahlungCreateSchema):
    """Verbucht einen Zahlungseingang und erstellt automatisch die Buchhaltungssätze."""
    vertrag = get_object_or_404(Mietvertrag, id=payload.vertrag_id)

    zahlung = Zahlungseingang.objects.create(
        vertrag=vertrag,
        betrag=payload.betrag,
        datum_eingang=payload.datum_eingang,
        buchungs_monat=payload.buchungs_monat.replace(day=1),
        bemerkung=payload.bemerkung,
        liegenschaft=vertrag.einheit.liegenschaft
    )

    try:
        konto_bank = Buchungskonto.objects.get(nummer="1020")
        konto_debitoren = Buchungskonto.objects.get(nummer="1100") # Zahlungen mindern die Forderung!

        Buchung.objects.create(
            datum=payload.datum_eingang,
            beleg_text=f"Zahlungseingang {vertrag.mieter} - {payload.bemerkung or 'Miete/NK'}",
            liegenschaft=vertrag.einheit.liegenschaft,
            soll_konto=konto_bank, # Bank nimmt zu
            haben_konto=konto_debitoren, # Debitoren nehmen ab
            betrag=payload.betrag,
            zahlungseingang=zahlung
        )
    except Buchungskonto.DoesNotExist:
        pass

    return 201, {"success": True}

@router.get("/mietzins-kontrolle", response=List[MietzinsKontrolleSchema])
def get_kontrolle(request):
    """Berechnet den Soll-Ist-Abgleich für den aktuellen Monat."""
    heute = timezone.now().date()
    aktueller_monat = heute.replace(day=1)

    aktive_vertraege = Mietvertrag.objects.filter(status='aktiv').select_related('mieter', 'einheit__liegenschaft')
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
@transaction.atomic
def delete_zahlung(request, zahlung_id: int):
    Buchung.objects.filter(zahlungseingang_id=zahlung_id).delete()
    get_object_or_404(Zahlungseingang, id=zahlung_id).delete()
    return 204, None

@router.get("/mahnung/{vertrag_id}")
def erstelle_mahnung(request, vertrag_id: int, offener_betrag: float):
    """Generiert einen Mahnbrief inkl. QR-Code als PDF"""
    vertrag = get_object_or_404(Mietvertrag, id=vertrag_id)
    verwaltung = Verwaltung.objects.first()

    if not verwaltung:
        return 400, {"success": False, "error": "Keine Verwaltung hinterlegt."}

    try:
        pdf_url = generate_mahnung_pdf(vertrag, offener_betrag, verwaltung)
        return {"success": True, "url": pdf_url}
    except Exception as e:
        return 500, {"success": False, "error": str(e)}


# ========================================================
# KREDITOREN / KI-SCANNER
# ========================================================

class KreditorUpdateSchema(Schema):
    lieferant: str
    betrag: Decimal
    datum: date
    referenz: str = ""
    liegenschaft_id: Optional[int] = None
    einheit_id: Optional[int] = None
    konto_id: Optional[int] = None
    is_hnk_relevant: bool = False

@router.post("/kreditoren/upload")
def upload_kreditor(request, file: UploadedFile = File(...)):
    """Lädt eine Rechnung hoch und extrahiert die Daten per KI/OCR."""
    rechnung = KreditorenRechnung.objects.create(
        beleg_scan=file,
        status='neu'
    )

    try:
        scanned_data = scan_invoice_pdf(rechnung.beleg_scan.path)

        rechnung.lieferant = scanned_data.get('lieferant', 'Unbekannt')
        rechnung.iban = scanned_data.get('iban', '')
        rechnung.betrag = scanned_data.get('betrag')
        rechnung.datum = scanned_data.get('datum')
        rechnung.referenz = scanned_data.get('referenz', '')
        rechnung.save()

        return {"success": True, "id": rechnung.id, "data": scanned_data}

    except Exception as e:
        rechnung.fehlermeldung = str(e)
        rechnung.save()
        return 500, {"success": False, "error": f"Scan-Fehler: {str(e)}"}

@router.get("/kreditoren", response=List[dict])
def list_kreditoren(request):
    """Gibt eine Liste aller erfassten Kreditorenrechnungen zurück."""
    kreditoren = KreditorenRechnung.objects.all().order_by('-id')
    return [
        {
            "id": k.id,
            "lieferant": k.lieferant or "Wird gescannt...",
            "betrag": float(k.betrag or 0),
            "status": k.status,
            "datum": k.datum.strftime('%d.%m.%Y') if k.datum else "Unbekannt",
            "file_url": k.beleg_scan.url if k.beleg_scan else "#",
            "liegenschaft_id": k.liegenschaft_id,
            "konto_id": k.konto_id,
            "referenz": k.referenz,
            "is_hnk_relevant": k.is_hnk_relevant
        } for k in kreditoren
    ]

@router.put("/kreditoren/{rechnung_id}", response={200: dict})
@transaction.atomic
def update_kreditor(request, rechnung_id: int, payload: KreditorUpdateSchema):
    """Aktualisiert eine gescannte Rechnung und weist sie einem Objekt zu."""
    rechnung = get_object_or_404(KreditorenRechnung, id=rechnung_id)
    data = payload.dict(exclude_unset=True)

    for attr, value in data.items():
        setattr(rechnung, attr, value)

    rechnung.status = 'freigegeben'
    rechnung.save()
    return 200, {"success": True}

@router.post("/kreditoren/{rechnung_id}/pay", response={200: dict, 400: dict})
@transaction.atomic # 🔥 Setzt eine Transaktion
def pay_kreditor(request, rechnung_id: int):
    """Markiert eine Lieferantenrechnung als bezahlt und erstellt die Buchung."""
    # 🔥 .select_for_update() sperrt diese Rechnungsebene für andere gleichzeitige Anfragen
    rechnung = get_object_or_404(KreditorenRechnung.objects.select_for_update(), id=rechnung_id)

    if rechnung.status == 'bezahlt':
        return 400, {"success": False, "error": "Diese Rechnung wurde bereits gebucht!"}

    rechnung.status = 'bezahlt'
    rechnung.save()

    try:
        konto_bank = Buchungskonto.objects.get(nummer="1020")
        konto_aufwand = rechnung.konto or Buchungskonto.objects.get(nummer="4000")

        Buchung.objects.create(
            datum=timezone.now().date(),
            beleg_text=f"Rechnung {rechnung.lieferant} - {rechnung.referenz or 'ohne Ref'}",
            liegenschaft=rechnung.liegenschaft,
            soll_konto=konto_aufwand,
            haben_konto=konto_bank,
            betrag=rechnung.betrag or Decimal('0.00'),
            kreditoren_rechnung=rechnung
        )
    except Buchungskonto.DoesNotExist:
        pass

    return 200, {"success": True}

@router.delete("/kreditoren/{rechnung_id}", response={204: None})
@transaction.atomic
def delete_kreditor(request, rechnung_id: int):
    rechnung = get_object_or_404(KreditorenRechnung, id=rechnung_id)
    Buchung.objects.filter(kreditoren_rechnung=rechnung).delete()
    rechnung.delete()
    return 204, None

# ========================================================
# DEBITORENRECHNUNGEN (WEITERVERRECHNUNG)
# ========================================================

class DebitorenRechnungCreateSchema(Schema):
    vertrag_id: int
    titel: str
    beschreibung: str = ""
    betrag: Decimal
    faellig_am: Optional[date] = None
    konto_haben_id: Optional[int] = None

@router.post("/debitoren-rechnungen", response={201: dict})
@transaction.atomic
def create_debitorenrechnung(request, payload: DebitorenRechnungCreateSchema):
    """Erstellt eine ausgehende Rechnung (z.B. Weiterverrechnung) für einen Mieter."""
    vertrag = get_object_or_404(Mietvertrag, id=payload.vertrag_id)

    rechnung = DebitorenRechnung.objects.create(
        vertrag=vertrag,
        liegenschaft=vertrag.einheit.liegenschaft,
        einheit=vertrag.einheit,
        titel=payload.titel,
        beschreibung=payload.beschreibung,
        betrag=payload.betrag,
        faellig_am=payload.faellig_am,
        konto_haben_id=payload.konto_haben_id
    )

    try:
        konto_debitoren = Buchungskonto.objects.get(nummer="1100")
        konto_haben = rechnung.konto_haben or Buchungskonto.objects.get(nummer="3000")

        Buchung.objects.create(
            datum=timezone.now().date(),
            beleg_text=f"Rechnung an {vertrag.mieter}: {rechnung.titel}",
            liegenschaft=vertrag.einheit.liegenschaft,
            soll_konto=konto_debitoren,
            haben_konto=konto_haben,
            betrag=rechnung.betrag,
            debitoren_rechnung=rechnung
        )
    except Buchungskonto.DoesNotExist:
        pass

    return 201, {"success": True, "id": rechnung.id}

@router.get("/debitoren-rechnungen", response=List[dict])
def list_debitorenrechnungen(request):
    rechnungen = DebitorenRechnung.objects.all().order_by('-id')
    return [
        {
            "id": r.id,
            "mieter": str(r.vertrag.mieter) if r.vertrag else "Unbekannt",
            "titel": r.titel,
            "betrag": float(r.betrag),
            "status": r.status,
            "datum": r.datum.strftime('%d.%m.%Y'),
            "pdf_url": r.pdf_dokument.url if r.pdf_dokument else None
        } for r in rechnungen
    ]

# 🔥 NEU: Delete-Endpunkt für Debitorenrechnungen
@router.delete("/debitoren-rechnungen/{rechnung_id}", response={204: None})
@transaction.atomic
def delete_debitorenrechnung(request, rechnung_id: int):
    """Löscht eine ausgehende Rechnung / Sollstellung inkl. Buchungssätzen."""
    rechnung = get_object_or_404(DebitorenRechnung, id=rechnung_id)

    # 1. Die zugehörigen Buchungssätze in der Buchhaltung löschen (nimmt den Ertrag wieder raus!)
    Buchung.objects.filter(debitoren_rechnung=rechnung).delete()

    # 2. Rechnung selbst löschen
    rechnung.delete()
    return 204, None

# ========================================================
# BUCHHALTUNG / ERFOLGSRECHNUNG / KONTENPLAN
# ========================================================

class KontoCreateSchema(Schema):
    nummer: str
    bezeichnung: str
    typ: str
    is_hnk_relevant: bool = False
    standard_verteilschluessel: str = 'm2'

@router.get("/konten", response=List[dict])
def list_konten(request):
    konten = Buchungskonto.objects.all().order_by('nummer')
    return [
        {
            "id": k.id,
            "nummer": k.nummer,
            "bezeichnung": k.bezeichnung,
            "typ": k.typ,
            "typ_display": k.get_typ_display(),
            "is_hnk_relevant": k.is_hnk_relevant,
            "standard_verteilschluessel": k.standard_verteilschluessel
        } for k in konten
    ]

@router.post("/konten", response={201: dict, 400: dict})
def create_konto(request, payload: KontoCreateSchema):
    if Buchungskonto.objects.filter(nummer=payload.nummer).exists():
        return 400, {"success": False, "error": "Diese Kontonummer existiert bereits."}

    Buchungskonto.objects.create(**payload.dict())
    return 201, {"success": True}

@router.post("/konten/import-standard", response={200: dict})
def import_standard_kontenplan(request):
    standard_konten = [
        {"nummer": "1020", "bezeichnung": "Bank", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "1100", "bezeichnung": "Forderungen (Debitoren)", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "1190", "bezeichnung": "Durchlaufkonto Weiterverrechnungen", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "2000", "bezeichnung": "Verbindlichkeiten (Kreditoren)", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "3000", "bezeichnung": "Mieterträge Wohnungen", "typ": "ertrag", "is_hnk_relevant": False},
        {"nummer": "3010", "bezeichnung": "Mieterträge Gewerbe/Parkplätze", "typ": "ertrag", "is_hnk_relevant": False},
        {"nummer": "3020", "bezeichnung": "Nebenkosten Akonto-Zahlungen", "typ": "ertrag", "is_hnk_relevant": False},
        {"nummer": "4000", "bezeichnung": "Unterhalt & Reparaturen", "typ": "aufwand", "is_hnk_relevant": False},
        {"nummer": "4100", "bezeichnung": "Heizkosten / Brennstoffe", "typ": "aufwand", "is_hnk_relevant": True, "standard_verteilschluessel": "m2"},
        {"nummer": "4110", "bezeichnung": "Wasser / Abwasser", "typ": "aufwand", "is_hnk_relevant": True, "standard_verteilschluessel": "m3"},
        {"nummer": "4120", "bezeichnung": "Hauswartung & Reinigung", "typ": "aufwand", "is_hnk_relevant": True, "standard_verteilschluessel": "m2"},
        {"nummer": "4130", "bezeichnung": "Allgemeinstrom", "typ": "aufwand", "is_hnk_relevant": True, "standard_verteilschluessel": "m2"},
        {"nummer": "4140", "bezeichnung": "Kehricht / Abgaben", "typ": "aufwand", "is_hnk_relevant": True, "standard_verteilschluessel": "einheit"},
        {"nummer": "4400", "bezeichnung": "Sachversicherungen", "typ": "aufwand", "is_hnk_relevant": True, "standard_verteilschluessel": "m3"},
        {"nummer": "4500", "bezeichnung": "Verwaltungshonorar", "typ": "aufwand", "is_hnk_relevant": False},
    ]

    for konto in standard_konten:
        Buchungskonto.objects.get_or_create(
            nummer=konto['nummer'],
            defaults={
                'bezeichnung': konto['bezeichnung'],
                'typ': konto['typ'],
                'is_hnk_relevant': konto['is_hnk_relevant'],
                'standard_verteilschluessel': konto.get('standard_verteilschluessel', 'm2')
            }
        )
    return 200, {"success": True}

@router.get("/erfolgsrechnung", response=dict)
def get_erfolgsrechnung(request, liegenschaft_id: Optional[int] = None):
    qs = Buchung.objects.all()

    if liegenschaft_id:
        qs = qs.filter(liegenschaft_id=liegenschaft_id)

    konten = Buchungskonto.objects.filter(typ__in=['ertrag', 'aufwand'])

    ertraege = []
    aufwaende = []
    total_ertrag = Decimal('0.00')
    total_aufwand = Decimal('0.00')

    for k in konten:
        soll_sum = qs.filter(soll_konto=k).aggregate(total=Sum('betrag'))['total'] or Decimal('0.00')
        haben_sum = qs.filter(haben_konto=k).aggregate(total=Sum('betrag'))['total'] or Decimal('0.00')

        if k.typ == 'ertrag':
            saldo = haben_sum - soll_sum
            if saldo != 0:
                ertraege.append({"nummer": k.nummer, "bezeichnung": k.bezeichnung, "saldo": float(saldo)})
                total_ertrag += saldo

        elif k.typ == 'aufwand':
            saldo = soll_sum - haben_sum
            if saldo != 0:
                aufwaende.append({"nummer": k.nummer, "bezeichnung": k.bezeichnung, "saldo": float(saldo)})
                total_aufwand += saldo

    erfolg = total_ertrag - total_aufwand

    return {
        "ertraege": ertraege,
        "aufwaende": aufwaende,
        "total_ertrag": float(total_ertrag),
        "total_aufwand": float(total_aufwand),
        "erfolg": float(erfolg)
    }

# ========================================================
# HEIZ- UND NEBENKOSTEN (HNK) ABRECHNUNG
# ========================================================

class PeriodeCreateSchema(Schema):
    liegenschaft_id: int
    bezeichnung: str
    start_datum: date
    ende_datum: date

@router.get("/nebenkosten/perioden", response=List[dict])
def list_perioden(request, liegenschaft_id: Optional[int] = None):
    qs = AbrechnungsPeriode.objects.all().order_by('-start_datum')
    if liegenschaft_id:
        qs = qs.filter(liegenschaft_id=liegenschaft_id)

    return [
        {
            "id": p.id,
            "liegenschaft": p.liegenschaft.strasse,
            "bezeichnung": p.bezeichnung,
            "start_datum": p.start_datum.strftime('%d.%m.%Y'),
            "ende_datum": p.ende_datum.strftime('%d.%m.%Y'),
            "abgeschlossen": p.abgeschlossen,
            "total_kosten": float(p.total_kosten)
        } for p in qs
    ]

@router.post("/nebenkosten/perioden", response={201: dict})
def create_periode(request, payload: PeriodeCreateSchema):
    periode = AbrechnungsPeriode.objects.create(**payload.dict())
    return 201, {"success": True, "id": periode.id}

@router.get("/nebenkosten/perioden/{periode_id}/abrechnung", response=dict)
def calculate_hnk_abrechnung(request, periode_id: int):
    periode = get_object_or_404(AbrechnungsPeriode, id=periode_id)
    liegenschaft = periode.liegenschaft

    kosten_rechnungen = KreditorenRechnung.objects.filter(
        liegenschaft=liegenschaft,
        is_hnk_relevant=True,
        datum__gte=periode.start_datum,
        datum__lte=periode.ende_datum
    )
    total_kosten = sum((r.betrag or Decimal('0.00')) for r in kosten_rechnungen)

    alle_einheiten = liegenschaft.einheiten.all()
    total_flaeche = sum(e.flaeche_m2 for e in alle_einheiten if e.flaeche_m2) or 1

    vertraege = Mietvertrag.objects.filter(
        einheit__liegenschaft=liegenschaft,
        beginn__lte=periode.ende_datum
    ).exclude(ende__lt=periode.start_datum)

    mieter_abrechnungen = []

    for v in vertraege:
        v_start = max(v.beginn, periode.start_datum)
        v_ende = min(v.ende, periode.ende_datum) if v.ende else periode.ende_datum
        tage_bewohnt = (v_ende - v_start).days + 1
        tage_periode = (periode.ende_datum - periode.start_datum).days + 1
        zeit_faktor = Decimal(tage_bewohnt) / Decimal(tage_periode)

        mieter_flaeche = v.einheit.flaeche_m2 or 0
        anteil_prozent = Decimal(mieter_flaeche) / Decimal(total_flaeche)
        mieter_kosten = total_kosten * anteil_prozent * zeit_faktor

        monate_bewohnt = round(tage_bewohnt / 30)
        akonto_total = (v.nebenkosten or Decimal('0.00')) * Decimal(monate_bewohnt)

        saldo = mieter_kosten - akonto_total

        mieter_abrechnungen.append({
            "vertrag_id": v.id,
            "mieter_name": str(v.mieter),
            "einheit": v.einheit.bezeichnung,
            "tage_bewohnt": tage_bewohnt,
            "anteil_kosten": float(round(mieter_kosten, 2)),
            "akonto_bezahlt": float(round(akonto_total, 2)),
            "saldo": float(round(saldo, 2)),
        })

    return {
        "periode": {
            "id": periode.id,
            "bezeichnung": periode.bezeichnung,
            "start": periode.start_datum.strftime('%d.%m.%Y'),
            "ende": periode.ende_datum.strftime('%d.%m.%Y'),
            "liegenschaft": liegenschaft.strasse,
            "abgeschlossen": periode.abgeschlossen
        },
        "zusammenfassung": {
            "total_kosten": float(total_kosten),
            "total_flaeche": float(total_flaeche),
            "anzahl_rechnungen": kosten_rechnungen.count()
        },
        "kosten_details": [
            {"lieferant": r.lieferant, "betrag": float(r.betrag), "datum": r.datum.strftime('%d.%m.%Y')}
            for r in kosten_rechnungen
        ],
        "mieter_abrechnungen": mieter_abrechnungen
    }

@router.delete("/nebenkosten/perioden/{periode_id}", response={204: None})
@transaction.atomic
def delete_periode(request, periode_id: int):
    periode = get_object_or_404(AbrechnungsPeriode, id=periode_id)
    periode.delete()
    return 204, None

@router.post("/nebenkosten/perioden/{periode_id}/verbuchen", response={200: dict, 400: dict})
@transaction.atomic # 🔥 Schützt vor Doppelbuchung per Doppelklick
def verbuchen_hnk_abrechnung(request, periode_id: int):
    # .select_for_update() sperrt den Datensatz auf Datenbankebene solange die Funktion läuft
    periode = get_object_or_404(AbrechnungsPeriode.objects.select_for_update(), id=periode_id)

    if periode.abgeschlossen:
        return 400, {"success": False, "error": "Periode ist bereits abgeschlossen und verbucht."}

    abrechnung_data = calculate_hnk_abrechnung(request, periode_id)

    try:
        konto_debitoren = Buchungskonto.objects.get(nummer="1100")
        konto_nk_ertrag = Buchungskonto.objects.get(nummer="3020")
    except Buchungskonto.DoesNotExist:
        return 400, {"success": False, "error": "Systemkonten (1100, 3020) fehlen. Bitte Standard-Kontenplan laden."}

    for m_data in abrechnung_data["mieter_abrechnungen"]:
        vertrag = Mietvertrag.objects.get(id=m_data["vertrag_id"])
        saldo = Decimal(str(m_data["saldo"]))

        if saldo > 0:
            rechnung = DebitorenRechnung.objects.create(
                vertrag=vertrag,
                liegenschaft=vertrag.einheit.liegenschaft,
                einheit=vertrag.einheit,
                titel=f"HNK Nachzahlung - {periode.bezeichnung}",
                beschreibung=f"Abrechnung für {periode.start_datum.strftime('%d.%m.%Y')} bis {periode.ende_datum.strftime('%d.%m.%Y')}",
                betrag=saldo,
                faellig_am=timezone.now().date() + timezone.timedelta(days=30),
                konto_haben_id=konto_nk_ertrag.id
            )

            Buchung.objects.create(
                datum=timezone.now().date(),
                beleg_text=f"HNK Nachzahlung {vertrag.mieter}",
                liegenschaft=vertrag.einheit.liegenschaft,
                soll_konto=konto_debitoren,
                haben_konto=konto_nk_ertrag,
                betrag=saldo,
                debitoren_rechnung=rechnung
            )

        elif saldo < 0:
            gutschrift_betrag = abs(saldo)
            Buchung.objects.create(
                datum=timezone.now().date(),
                beleg_text=f"HNK Gutschrift {vertrag.mieter} - {periode.bezeichnung}",
                liegenschaft=vertrag.einheit.liegenschaft,
                soll_konto=konto_nk_ertrag,
                haben_konto=konto_debitoren,
                betrag=gutschrift_betrag
            )

    periode.abgeschlossen = True
    periode.save()

    return 200, {"success": True}