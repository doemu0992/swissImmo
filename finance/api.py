# finance/api.py
#
# VERALTET (Legacy /app/-SPA). Die aktive Oberfläche ist /neu/ (core/views/fw.py).
# Diese API wird nur noch von der alten SPA genutzt. Alle buchenden Endpunkte
# delegieren inzwischen an die kanonische Buchungsschicht (finance.booking.buche)
# bzw. an core.services.automation.run_sollstellung — es gibt KEINE zweite,
# abweichende Buchungslogik mehr. Neue Funktionalität gehört nach fw.py.
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
    """Führt den monatlichen Mietenlauf durch.

    DEPRECATED-Pfad (alte /app/-SPA): delegiert an den EINEN kanonischen Dienst
    ``core.services.automation.run_sollstellung`` (mit MWST + Staffel/Index),
    damit /app/ und /neu/ NICHT auseinanderlaufen. Keine eigene Buchungslogik mehr."""
    if not (1 <= payload.monat <= 12) or not (2000 <= payload.jahr <= 2100):
        return 400, {"success": False, "error": "Ungültiger Monat (1–12) oder Jahr (2000–2100)."}
    from core.services.automation import run_sollstellung as _kanonisch
    erstellt = _kanonisch(payload.jahr, payload.monat, user=request.user)
    log_aktion(request, "Sollstellung ausgeführt", f"Miete & NK {payload.monat:02d}/{payload.jahr}",
               f"{erstellt} Rechnungen erstellt")
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
    if payload.betrag <= 0 or payload.betrag > Decimal('100000000'):
        return 400, {"success": False, "error": "Betrag muss positiv und plausibel sein."}
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

    from finance.booking import buche
    buche("1020", "1100", payload.betrag,
          f"Zahlungseingang {vertrag.mieter} - {payload.bemerkung or 'Miete/NK'}",
          datum=payload.datum_eingang, liegenschaft=vertrag.einheit.liegenschaft,
          zahlung=zahlung, user=request.user)
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

    # SCHRITT 1: Aufwand buchen (Aufwand an Kreditoren) — mit Vorsteuer-Split
    if war_neu and rechnung.konto:
        from finance.booking import buche
        datum_b = rechnung.datum or timezone.now().date()
        brutto = rechnung.betrag or Decimal('0.00')
        vorsteuer = Decimal('0.00')
        if (rechnung.mwst_satz or 0) > 0:
            satz = rechnung.mwst_satz
            vorsteuer = (brutto * satz / (Decimal('100') + satz)).quantize(Decimal('0.01'))
            rechnung.mwst_betrag = vorsteuer
            rechnung.save(update_fields=['mwst_betrag'])
        buche(rechnung.konto, "2000", brutto - vorsteuer,
              f"Rechnung {rechnung.lieferant} - {rechnung.referenz}",
              datum=datum_b, liegenschaft=rechnung.liegenschaft, kreditor=rechnung, user=request.user)
        if vorsteuer > 0:
            buche("1170", "2000", vorsteuer, f"Vorsteuer {rechnung.mwst_satz}% {rechnung.lieferant}",
                  datum=datum_b, liegenschaft=rechnung.liegenschaft, kreditor=rechnung, user=request.user)

    return 200, {"success": True}

@router.post("/kreditoren/{rechnung_id}/pay", response={200: dict, 400: dict}, auth=auth_verwaltung)
@transaction.atomic
def pay_kreditor(request, rechnung_id: int):
    """Bezahlung der Rechnung -> Bucht das Geld vom Bankkonto ab."""
    from finance.models import KreditorenZahlung
    rechnung = get_object_or_404(KreditorenRechnung.objects.select_for_update(), id=rechnung_id)
    if rechnung.status in ('bezahlt', 'storniert'):
        return 400, {"success": False, "error": "Bereits bezahlt oder storniert!"}

    # Nur den OFFENEN Betrag zahlen (berücksichtigt bereits geleistete Teilzahlungen)
    # — sonst würde eine bereits teilbezahlte Rechnung nochmals voll abgebucht
    # (Bank überzahlt, Kreditor 2000 mit Soll-Saldo). Zahlung als KreditorenZahlung
    # erfassen, damit offener_betrag/OP-Liste stimmen.
    offen = rechnung.offener_betrag
    if offen <= 0:
        rechnung.status = 'bezahlt'
        rechnung.save(update_fields=['status'])
        return 400, {"success": False, "error": "Kein offener Betrag."}

    from finance.booking import buche
    KreditorenZahlung.objects.create(
        kreditor=rechnung, betrag=offen, datum=timezone.localdate(),
        bemerkung=f"Zahlung {rechnung.lieferant}", erstellt_von=request.user)
    buche("2000", "1020", offen, f"Zahlung {rechnung.lieferant} - {rechnung.referenz}",
          liegenschaft=rechnung.liegenschaft, kreditor=rechnung, user=request.user)
    rechnung.status = 'bezahlt' if rechnung.offener_betrag <= 0 else 'teilbezahlt'
    rechnung.save(update_fields=['status'])
    log_aktion(request, "Kreditorenrechnung bezahlt", rechnung.lieferant or f"Rechnung #{rechnung.id}",
               f"CHF {offen}")

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

@router.post("/debitoren-rechnungen", response={201: dict, 400: dict}, auth=auth_schreiben)
@transaction.atomic
def create_debitorenrechnung(request, payload: DebitorenRechnungCreateSchema):
    if payload.betrag <= 0 or payload.betrag > Decimal('100000000'):
        return 400, {"success": False, "error": "Betrag muss positiv und plausibel sein."}
    vertrag = get_object_or_404(Mietvertrag, id=payload.vertrag_id)
    rechnung = DebitorenRechnung.objects.create(
        vertrag=vertrag, liegenschaft=vertrag.einheit.liegenschaft, einheit=vertrag.einheit,
        titel=payload.titel, beschreibung=payload.beschreibung, betrag=payload.betrag,
        faellig_am=payload.faellig_am, konto_haben_id=payload.konto_haben_id
    )
    from finance.booking import buche
    haben = rechnung.konto_haben.nummer if rechnung.konto_haben_id else "3000"
    buche("1100", haben, rechnung.betrag, f"Rechnung an {vertrag.mieter}: {rechnung.titel}",
          datum=timezone.now().date(), liegenschaft=vertrag.einheit.liegenschaft,
          debitor=rechnung, user=request.user)
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
        {"nummer": "1015", "bezeichnung": "Kautionssperrkonten (Mieterkautionen)", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "1020", "bezeichnung": "Bank", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "1100", "bezeichnung": "Forderungen (Debitoren)", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "1170", "bezeichnung": "Vorsteuer (MWST)", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "1190", "bezeichnung": "Durchlaufkonto Weiterverrechnungen", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "1500", "bezeichnung": "Sachanlagen (Anlagegüter)", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "2000", "bezeichnung": "Verbindlichkeiten (Kreditoren)", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "2010", "bezeichnung": "Kautionsverbindlichkeiten", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "2200", "bezeichnung": "Geschuldete MWST (Umsatzsteuer)", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "2800", "bezeichnung": "Erneuerungsfonds (Rückstellung)", "typ": "bilanz", "is_hnk_relevant": False},
        {"nummer": "6800", "bezeichnung": "Abschreibungen", "typ": "aufwand", "is_hnk_relevant": False},
        {"nummer": "6900", "bezeichnung": "Einlage Erneuerungsfonds", "typ": "aufwand", "is_hnk_relevant": False},
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

    # KANONISCHE Engine verwenden — identisch zu /neu/ (fw_nebenkosten_verbuchen)
    # und der dem Mieter zugestellten PDF. Die frühere eigene Rechnung
    # (calculate_hnk_abrechnung) wich ab: unbestätigte OCR-Scans (status='neu') im
    # Kostenpool, round(tage/30)-Akonto, Verteilung nur nach Fläche (ignoriert
    # Heizung/Wasser/Einheit-Schlüssel), kein Verwaltungshonorar, kein Split — der
    # Mieter erhielt so eine andere (teils vorzeichenverkehrte) Buchung als die PDF.
    from core.utils.billing import berechne_abrechnung
    from finance.booking import buche, konto as _konto
    result = berechne_abrechnung(periode.id)
    if result.get('error'):
        return 400, {"success": False, "error": result['error']}
    try:
        konto_nk = _konto("3020")
    except Exception:
        return 400, {"success": False, "error": "Systemkonto 3020 fehlt. Bitte Standard-Kontenplan laden."}

    heute = timezone.now().date()
    n_nach = n_gut = 0
    for a in result.get('abrechnungen', []):
        vid = a.get('vertrag_id')
        saldo = Decimal(str(a.get('saldo', 0)))
        if not vid or a.get('typ') == 'leerstand' or abs(saldo) < Decimal('0.01'):
            continue
        vertrag = Mietvertrag.objects.filter(id=vid).select_related('einheit__liegenschaft').first()
        if not vertrag:
            continue
        if saldo > 0:  # Nachzahlung → Debitor
            rechnung = DebitorenRechnung.objects.create(
                vertrag=vertrag, liegenschaft=vertrag.einheit.liegenschaft, einheit=vertrag.einheit,
                titel=f"HNK Nachzahlung - {periode.bezeichnung}",
                beschreibung=f"Periode {periode.start_datum:%d.%m.%Y}–{periode.ende_datum:%d.%m.%Y}",
                betrag=saldo, faellig_am=heute + timezone.timedelta(days=30), konto_haben=konto_nk)
            buche("1100", "3020", saldo, f"HNK-Nachzahlung {vertrag.mieter} - {periode.bezeichnung}",
                  datum=heute, liegenschaft=vertrag.einheit.liegenschaft, debitor=rechnung, user=request.user)
            n_nach += 1
        else:  # Guthaben → Gutschrift
            buche("3020", "1100", abs(saldo), f"HNK-Gutschrift {vertrag.mieter} - {periode.bezeichnung}",
                  datum=heute, liegenschaft=vertrag.einheit.liegenschaft, user=request.user)
            n_gut += 1

    periode.abgeschlossen = True
    periode.save(update_fields=['abgeschlossen'])
    log_aktion(request, "HNK-Abrechnung verbucht", periode.bezeichnung,
               f"{n_nach} Nachzahlungen, {n_gut} Gutschriften")
    return 200, {"success": True}
