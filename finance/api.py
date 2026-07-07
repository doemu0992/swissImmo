# finance/api.py
from ninja import Router, File, Schema
from ninja.files import UploadedFile
from django.shortcuts import get_object_or_404
from django.db.models import Sum
from django.utils import timezone
from django.db import transaction
from typing import List, Optional
from decimal import Decimal
from datetime import date
import calendar

from .models import Zahlungseingang, KreditorenRechnung, Buchungskonto, Buchung, DebitorenRechnung, AbrechnungsPeriode
from rentals.models import Mietvertrag
from crm.models import Verwaltung
from core.utils.qr_code import generate_mahnung_pdf
from .utils import scan_invoice_pdf

from core.auth import auth_schreiben, auth_verwaltung, log_aktion

router = Router(tags=["Finanzen"])

# ========================================================
# HILFSFUNKTION: STORNO BUCHUNG (Revisionssicherheit)
# ========================================================
def erstelle_storno_buchung(original_buchung, benutzer=None):
    """Erstellt eine exakte Umkehrbuchung für die Revisionssicherheit."""
    return Buchung.objects.create(
        datum=timezone.now().date(),
        beleg_text=f"STORNO: {original_buchung.beleg_text}",
        liegenschaft=original_buchung.liegenschaft,
        soll_konto=original_buchung.haben_konto,  # Konten getauscht
        haben_konto=original_buchung.soll_konto,  # Konten getauscht
        betrag=original_buchung.betrag,
        ist_storno=True,
        storniert_am=timezone.now(),
        erstellt_von=benutzer
    )


# ========================================================
# DEBITOREN / SOLLSTELLUNG / ZAHLUNGEN
# ========================================================

class SollstellungSchema(Schema):
    monat: int
    jahr: int

@router.post("/debitoren/sollstellung", response={200: dict, 400: dict}, auth=auth_verwaltung)
@transaction.atomic
def run_sollstellung(request, payload: SollstellungSchema):
    """Führt den monatlichen Mietenlauf durch (inkl. Pro-Rata Berechnung)."""
    start_date = date(payload.jahr, payload.monat, 1)
    _, last_day = calendar.monthrange(payload.jahr, payload.monat)
    end_date = date(payload.jahr, payload.monat, last_day)
    tage_im_monat = last_day

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
        if DebitorenRechnung.objects.filter(vertrag=v, titel=titel_vorlage).exclude(status='storniert').exists():
            continue

        # PRO-RATA BERECHNUNG FÜR TEIL-MONATE (Ein-/Auszug mitten im Monat)
        vertrag_start = max(start_date, v.beginn)
        vertrag_ende = min(end_date, v.ende) if v.ende else end_date
        tage_aktiv = (vertrag_ende - vertrag_start).days + 1

        faktor = Decimal(tage_aktiv) / Decimal(tage_im_monat)

        netto = round((v.netto_mietzins or Decimal('0.00')) * faktor, 2)
        nk = round((v.nebenkosten or Decimal('0.00')) * faktor, 2)
        total_betrag = netto + nk

        if total_betrag <= 0:
            continue

        rechnung = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=v.einheit.liegenschaft, einheit=v.einheit,
            titel=titel_vorlage, betrag=total_betrag, faellig_am=start_date
        )

        if netto > 0:
            Buchung.objects.create(
                datum=start_date, beleg_text=f"Mietertrag {v.mieter} - {payload.monat:02d}/{payload.jahr}",
                liegenschaft=v.einheit.liegenschaft, soll_konto=konto_debitoren, haben_konto=konto_ertrag,
                betrag=netto, debitoren_rechnung=rechnung, erstellt_von=request.user
            )
        if nk > 0:
            Buchung.objects.create(
                datum=start_date, beleg_text=f"NK-Akonto {v.mieter} - {payload.monat:02d}/{payload.jahr}",
                liegenschaft=v.einheit.liegenschaft, soll_konto=konto_debitoren, haben_konto=konto_nk_akonto,
                betrag=nk, debitoren_rechnung=rechnung, erstellt_von=request.user
            )
        erstellt += 1

    log_aktion(request, "Sollstellung ausgeführt", titel_vorlage, f"{erstellt} Rechnungen erstellt")
    return 200, {"success": True, "erstellt": erstellt}

class ZahlungCreateSchema(Schema):
    vertrag_id: int
    betrag: Decimal
    datum_eingang: date
    buchungs_monat: date
    bemerkung: str = ""

@router.post("/zahlungen", response={201: dict, 400: dict}, auth=auth_schreiben)
@transaction.atomic
def create_zahlung(request, payload: ZahlungCreateSchema):
    """Verbucht einen Zahlungseingang (Bank an Debitoren) und verknüpft OPs."""
    vertrag = get_object_or_404(Mietvertrag, id=payload.vertrag_id)

    # Suche passende offene Rechnung für diesen Monat
    offene_rechnung = DebitorenRechnung.objects.filter(
        vertrag=vertrag,
        status__in=['offen', 'teilbezahlt']
    ).order_by('faellig_am').first()

    zahlung = Zahlungseingang.objects.create(
        vertrag=vertrag,
        betrag=payload.betrag,
        datum_eingang=payload.datum_eingang,
        buchungs_monat=payload.buchungs_monat.replace(day=1),
        bemerkung=payload.bemerkung,
        liegenschaft=vertrag.einheit.liegenschaft,
        debitoren_rechnung=offene_rechnung,
        erstellt_von=request.user
    )

    # OP-Status der Rechnung aktualisieren, falls verknüpft
    if offene_rechnung:
        if offene_rechnung.offener_betrag <= 0:
            offene_rechnung.status = 'bezahlt'
        else:
            offene_rechnung.status = 'teilbezahlt'
        offene_rechnung.save()

    try:
        konto_bank = Buchungskonto.objects.get(nummer="1020")
        konto_debitoren = Buchungskonto.objects.get(nummer="1100")

        Buchung.objects.create(
            datum=payload.datum_eingang,
            beleg_text=f"Zahlungseingang {vertrag.mieter} - {payload.bemerkung or 'Miete/NK'}",
            liegenschaft=vertrag.einheit.liegenschaft,
            soll_konto=konto_bank,
            haben_konto=konto_debitoren,
            betrag=payload.betrag,
            zahlungseingang=zahlung,
            erstellt_von=request.user
        )
    except Buchungskonto.DoesNotExist:
        pass

    return 201, {"success": True}

@router.get("/zahlungen", response=List[dict])
def list_zahlungen(request):
    """Liste der letzten 50 aktiven Zahlungseingänge."""
    zahlungen = Zahlungseingang.objects.filter(status='verbucht').select_related('vertrag__mieter').order_by('-datum_eingang')[:50]
    return [
        {
            "id": z.id,
            "datum_eingang": z.datum_eingang.strftime('%d.%m.%Y'),
            "bemerkung": z.bemerkung,
            "betrag": float(z.betrag)
        } for z in zahlungen
    ]

@router.delete("/zahlungen/{zahlung_id}", response={200: dict}, auth=auth_verwaltung)
@transaction.atomic
def storniere_zahlung(request, zahlung_id: int):
    """REVISIONSSICHER: Zahlungen werden storniert, nicht gelöscht."""
    zahlung = get_object_or_404(Zahlungseingang, id=zahlung_id)
    if zahlung.status == 'storniert':
        return 200, {"success": True}

    fuer_storno = Buchung.objects.filter(zahlungseingang=zahlung, ist_storno=False)
    for b in fuer_storno:
        erstelle_storno_buchung(b, benutzer=request.user)

    zahlung.status = 'storniert'
    zahlung.save()

    # Rechnungsstatus wieder aufrollen
    if zahlung.debitoren_rechnung:
        rech = zahlung.debitoren_rechnung
        if rech.offener_betrag >= rech.betrag:
            rech.status = 'offen'
        else:
            rech.status = 'teilbezahlt'
        rech.save()

    log_aktion(request, "Zahlung storniert", f"Zahlung #{zahlung.id}",
               f"CHF {zahlung.betrag}, Vertrag-ID {zahlung.vertrag_id}")
    return 200, {"success": True}


@router.get("/mietzins-kontrolle", response=List[dict])
def get_kontrolle(request):
    """Soll-Ist-Abgleich für den aktuellen Monat."""
    heute = timezone.now().date()
    aktueller_monat = heute.replace(day=1)
    aktive_vertraege = Mietvertrag.objects.filter(status='aktiv').select_related('mieter', 'einheit__liegenschaft')
    ergebnis = []

    for v in aktive_vertraege:
        # Soll aus der Sollstellung holen (falls vorhanden), ansonsten Standardmiete
        rechnung = DebitorenRechnung.objects.filter(vertrag=v, datum__year=heute.year, datum__month=heute.month).exclude(status='storniert').first()
        soll = rechnung.betrag if rechnung else ((v.netto_mietzins or 0) + (v.nebenkosten or 0))

        ist = Zahlungseingang.objects.filter(
            vertrag=v, buchungs_monat=aktueller_monat, status='verbucht'
        ).aggregate(total=Sum('betrag'))['total'] or Decimal('0.00')

        diff = soll - ist
        status = 'Bezahlt' if ist >= soll else ('Teilzahlung' if ist > 0 else 'Offen')

        ergebnis.append({
            "vertrag_id": v.id,
            "mieter_name": str(v.mieter),
            "objekt": f"{v.einheit.liegenschaft.strasse} ({v.einheit.bezeichnung})",
            "soll": float(soll),
            "ist": float(ist),
            "differenz": float(diff),
            "status": status
        })
    return ergebnis

@router.get("/mahnung/{vertrag_id}")
def erstelle_mahnung(request, vertrag_id: int, offener_betrag: float):
    vertrag = get_object_or_404(Mietvertrag, id=vertrag_id)
    verwaltung = Verwaltung.objects.first()
    if not verwaltung: return 400, {"success": False, "error": "Keine Verwaltung hinterlegt."}
    try:
        pdf_url = generate_mahnung_pdf(vertrag, offener_betrag, verwaltung)
        return {"success": True, "url": pdf_url}
    except Exception as e:
        return 500, {"success": False, "error": str(e)}


# ========================================================
# KREDITOREN (2-STUFIGE BUCHHALTUNG)
# ========================================================

class KreditorUpdateSchema(Schema):
    lieferant: str
    betrag: Decimal
    datum: date
    referenz: str = ""
    liegenschaft_id: Optional[int] = None
    konto_id: Optional[int] = None
    is_hnk_relevant: bool = False

@router.post("/kreditoren/upload", auth=auth_schreiben)
def upload_kreditor(request, file: UploadedFile = File(...)):
    rechnung = KreditorenRechnung.objects.create(beleg_scan=file, status='neu')
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
    kreditoren = KreditorenRechnung.objects.exclude(status='storniert').order_by('-id')
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

@router.put("/kreditoren/{rechnung_id}", response={200: dict}, auth=auth_schreiben)
@transaction.atomic
def update_kreditor(request, rechnung_id: int, payload: KreditorUpdateSchema):
    """Freigabe der Rechnung -> Erzeugt den Aufwand in der Buchhaltung."""
    rechnung = get_object_or_404(KreditorenRechnung.objects.select_for_update(), id=rechnung_id)
    war_neu = rechnung.status == 'neu'

    for attr, value in payload.dict(exclude_unset=True).items():
        setattr(rechnung, attr, value)

    rechnung.status = 'freigegeben'
    rechnung.save()

    # SCHRITT 1: Aufwand buchen (Aufwand an Kreditoren)
    if war_neu and rechnung.konto:
        try:
            konto_kreditoren = Buchungskonto.objects.get(nummer="2000")
            Buchung.objects.create(
                datum=rechnung.datum or timezone.now().date(),
                beleg_text=f"Rechnung {rechnung.lieferant} - {rechnung.referenz}",
                liegenschaft=rechnung.liegenschaft,
                soll_konto=rechnung.konto,          # Aufwand
                haben_konto=konto_kreditoren,       # Verbindlichkeit
                betrag=rechnung.betrag,
                kreditoren_rechnung=rechnung,
                erstellt_von=request.user
            )
        except Buchungskonto.DoesNotExist:
            pass

    return 200, {"success": True}

@router.post("/kreditoren/{rechnung_id}/pay", response={200: dict, 400: dict}, auth=auth_verwaltung)
@transaction.atomic
def pay_kreditor(request, rechnung_id: int):
    """Bezahlung der Rechnung -> Bucht das Geld vom Bankkonto ab."""
    rechnung = get_object_or_404(KreditorenRechnung.objects.select_for_update(), id=rechnung_id)
    if rechnung.status == 'bezahlt': return 400, {"success": False, "error": "Bereits bezahlt!"}

    rechnung.status = 'bezahlt'
    rechnung.save()
    log_aktion(request, "Kreditorenrechnung bezahlt", rechnung.lieferant or f"Rechnung #{rechnung.id}",
               f"CHF {rechnung.betrag}")

    # SCHRITT 2: Zahlung buchen (Kreditoren an Bank)
    try:
        konto_bank = Buchungskonto.objects.get(nummer="1020")
        konto_kreditoren = Buchungskonto.objects.get(nummer="2000")
        Buchung.objects.create(
            datum=timezone.now().date(),
            beleg_text=f"Zahlung {rechnung.lieferant} - {rechnung.referenz}",
            liegenschaft=rechnung.liegenschaft,
            soll_konto=konto_kreditoren,    # Verbindlichkeit sinkt
            haben_konto=konto_bank,         # Geldabfluss
            betrag=rechnung.betrag,
            kreditoren_rechnung=rechnung,
            erstellt_von=request.user
        )
    except Buchungskonto.DoesNotExist:
        pass

    return 200, {"success": True}

@router.delete("/kreditoren/{rechnung_id}", response={200: dict}, auth=auth_verwaltung)
@transaction.atomic
def storniere_kreditor(request, rechnung_id: int):
    """REVISIONSSICHER: Kreditor stornieren."""
    rechnung = get_object_or_404(KreditorenRechnung, id=rechnung_id)
    if rechnung.status == 'storniert': return 200, {"success": True}

    fuer_storno = Buchung.objects.filter(kreditoren_rechnung=rechnung, ist_storno=False)
    for b in fuer_storno:
        erstelle_storno_buchung(b, benutzer=request.user)

    rechnung.status = 'storniert'
    rechnung.save()
    log_aktion(request, "Kreditorenrechnung storniert", rechnung.lieferant or f"Rechnung #{rechnung.id}",
               f"CHF {rechnung.betrag}")
    return 200, {"success": True}


# ========================================================
# MANUELLE DEBITORENRECHNUNGEN / WEITERVERRECHNUNG
# ========================================================

class DebitorenRechnungCreateSchema(Schema):
    vertrag_id: int
    titel: str
    beschreibung: str = ""
    betrag: Decimal
    faellig_am: Optional[date] = None
    konto_haben_id: Optional[int] = None

@router.post("/debitoren-rechnungen", response={201: dict}, auth=auth_schreiben)
@transaction.atomic
def create_debitorenrechnung(request, payload: DebitorenRechnungCreateSchema):
    vertrag = get_object_or_404(Mietvertrag, id=payload.vertrag_id)
    rechnung = DebitorenRechnung.objects.create(
        vertrag=vertrag, liegenschaft=vertrag.einheit.liegenschaft, einheit=vertrag.einheit,
        titel=payload.titel, beschreibung=payload.beschreibung, betrag=payload.betrag,
        faellig_am=payload.faellig_am, konto_haben_id=payload.konto_haben_id
    )
    try:
        konto_debitoren = Buchungskonto.objects.get(nummer="1100")
        konto_haben = rechnung.konto_haben or Buchungskonto.objects.get(nummer="3000")
        Buchung.objects.create(
            datum=timezone.now().date(), beleg_text=f"Rechnung an {vertrag.mieter}: {rechnung.titel}",
            liegenschaft=vertrag.einheit.liegenschaft, soll_konto=konto_debitoren, haben_konto=konto_haben,
            betrag=rechnung.betrag, debitoren_rechnung=rechnung, erstellt_von=request.user
        )
    except Buchungskonto.DoesNotExist:
        pass
    return 201, {"success": True, "id": rechnung.id}

@router.get("/debitoren-rechnungen", response=List[dict])
def list_debitorenrechnungen(request):
    rechnungen = DebitorenRechnung.objects.exclude(status='storniert').order_by('-id')
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

@router.delete("/debitoren-rechnungen/{rechnung_id}", response={200: dict}, auth=auth_verwaltung)
@transaction.atomic
def storniere_debitorenrechnung(request, rechnung_id: int):
    """REVISIONSSICHER: Rechnung stornieren statt löschen (Gegenbuchung)."""
    rechnung = get_object_or_404(DebitorenRechnung, id=rechnung_id)
    if rechnung.status == 'storniert': return 200, {"success": True}

    fuer_storno = Buchung.objects.filter(debitoren_rechnung=rechnung, ist_storno=False)
    for b in fuer_storno:
        erstelle_storno_buchung(b, benutzer=request.user)

    rechnung.status = 'storniert'
    rechnung.save()
    log_aktion(request, "Debitorenrechnung storniert", rechnung.titel, f"CHF {rechnung.betrag}")
    return 200, {"success": True}


# ========================================================
# KONTENPLAN & ERFOLGSRECHNUNG
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
            "id": k.id, "nummer": k.nummer, "bezeichnung": k.bezeichnung, "typ": k.typ,
            "typ_display": k.get_typ_display(), "is_hnk_relevant": k.is_hnk_relevant,
            "standard_verteilschluessel": k.standard_verteilschluessel
        } for k in konten
    ]

@router.post("/konten", response={201: dict, 400: dict}, auth=auth_schreiben)
def create_konto(request, payload: KontoCreateSchema):
    if Buchungskonto.objects.filter(nummer=payload.nummer).exists():
        return 400, {"success": False, "error": "Diese Kontonummer existiert bereits."}
    Buchungskonto.objects.create(**payload.dict())
    return 201, {"success": True}

@router.post("/konten/import-standard", response={200: dict}, auth=auth_verwaltung)
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
    for k in standard_konten:
        Buchungskonto.objects.get_or_create(nummer=k['nummer'], defaults={
            'bezeichnung': k['bezeichnung'], 'typ': k['typ'], 'is_hnk_relevant': k['is_hnk_relevant'],
            'standard_verteilschluessel': k.get('standard_verteilschluessel', 'm2')
        })
    return 200, {"success": True}

@router.get("/erfolgsrechnung", response=dict)
def get_erfolgsrechnung(request, liegenschaft_id: Optional[int] = None):
    # WICHTIG: Stornos werden NICHT ausgefiltert. Ein Storno-Paar (Original +
    # Umkehrbuchung) hebt sich arithmetisch selbst auf — nur so stimmt die
    # Erfolgsrechnung. (Nur das Storno auszufiltern liesse die stornierte
    # Original-Buchung fälschlich weiterzählen.)
    qs = Buchung.objects.all()
    if liegenschaft_id: qs = qs.filter(liegenschaft_id=liegenschaft_id)
    konten = Buchungskonto.objects.filter(typ__in=['ertrag', 'aufwand'])

    ertraege, aufwaende = [], []
    total_ertrag, total_aufwand = Decimal('0.00'), Decimal('0.00')

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

    return {
        "ertraege": ertraege, "aufwaende": aufwaende,
        "total_ertrag": float(total_ertrag), "total_aufwand": float(total_aufwand),
        "erfolg": float(total_ertrag - total_aufwand)
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
    if liegenschaft_id: qs = qs.filter(liegenschaft_id=liegenschaft_id)
    return [
        {
            "id": p.id, "liegenschaft": p.liegenschaft.strasse, "bezeichnung": p.bezeichnung,
            "start_datum": p.start_datum.strftime('%d.%m.%Y'), "ende_datum": p.ende_datum.strftime('%d.%m.%Y'),
            "abgeschlossen": p.abgeschlossen, "total_kosten": float(p.total_kosten)
        } for p in qs
    ]

@router.post("/nebenkosten/perioden", response={201: dict}, auth=auth_schreiben)
def create_periode(request, payload: PeriodeCreateSchema):
    p = AbrechnungsPeriode.objects.create(**payload.dict())
    return 201, {"success": True, "id": p.id}

@router.get("/nebenkosten/perioden/{periode_id}/abrechnung", response=dict)
def calculate_hnk_abrechnung(request, periode_id: int):
    """HNK-Abrechnung berechnen (Vorschau) — wird vom SPA-Finanz-Tab genutzt."""
    periode = get_object_or_404(AbrechnungsPeriode, id=periode_id)
    liegenschaft = periode.liegenschaft

    kosten_rechnungen = KreditorenRechnung.objects.filter(
        liegenschaft=liegenschaft,
        is_hnk_relevant=True,
        datum__gte=periode.start_datum,
        datum__lte=periode.ende_datum
    ).exclude(status='storniert')
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

@router.delete("/nebenkosten/perioden/{periode_id}", response={204: None, 400: dict}, auth=auth_verwaltung)
@transaction.atomic
def delete_periode(request, periode_id: int):
    periode = get_object_or_404(AbrechnungsPeriode, id=periode_id)
    if periode.abgeschlossen:
        return 400, {"success": False, "error": "Verbuchte Perioden können nicht gelöscht werden (Revisionssicherheit)."}
    log_aktion(request, "Abrechnungsperiode gelöscht", periode.bezeichnung)
    periode.delete()
    return 204, None

@router.post("/nebenkosten/perioden/{periode_id}/verbuchen", response={200: dict, 400: dict}, auth=auth_verwaltung)
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
                debitoren_rechnung=rechnung,
                erstellt_von=request.user
            )

        elif saldo < 0:
            gutschrift_betrag = abs(saldo)
            Buchung.objects.create(
                datum=timezone.now().date(),
                beleg_text=f"HNK Gutschrift {vertrag.mieter} - {periode.bezeichnung}",
                liegenschaft=vertrag.einheit.liegenschaft,
                soll_konto=konto_nk_ertrag,
                haben_konto=konto_debitoren,
                betrag=gutschrift_betrag,
                erstellt_von=request.user
            )

    periode.abgeschlossen = True
    periode.save()
    log_aktion(request, "HNK-Abrechnung verbucht", periode.bezeichnung,
               f"{len(abrechnung_data['mieter_abrechnungen'])} Mieter-Abrechnungen")

    return 200, {"success": True}
