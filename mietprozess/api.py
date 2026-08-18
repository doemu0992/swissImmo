# mietprozess/api.py
#
# Nach E1c ist hier nur noch EIN Endpunkt: das oeffentliche Bewerbungsformular.
# Es wird von core/templates/core/bewerbung.html und
# core/templates/core/public_bewerbung_form.html per fetch() aufgerufen; der
# Pfad /api/mietprozess/public/bewerben darf sich deshalb nicht aendern.
#
# Die vier Admin-Endpunkte (Liste, Status, Loeschen, Nachricht) sind entfallen —
# sie wurden ausschliesslich von der in E1b geloeschten Vue-Oberflaeche
# aufgerufen. Damit faellt auch mietprozess/schemas.py weg.
from ninja import Router, File, Form
from ninja.files import UploadedFile
from django.shortcuts import get_object_or_404
from django.db import transaction
from typing import Optional
from datetime import datetime

from .models import Mietbewerbung
from portfolio.models import Einheit

router = Router(tags=["Mietprozess"])


# auth=None: Bewusst öffentlich — das ist das Bewerbungsformular für Interessenten
# (alle anderen Endpoints erben die Session-Pflicht aus NinjaAPI(auth=django_auth)).
@router.post("/public/bewerben", response={201: dict, 400: dict, 429: dict}, auth=None)
@transaction.atomic
def public_submit_bewerbung(
    request,
    einheit_id: int = Form(...),
    # --- Personalien ---
    vorname: str = Form(...),
    nachname: str = Form(...),
    zivilstand: str = Form(''),      # nicht mehr im Erstformular erhoben
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
    # Spam-/Missbrauchsschutz: das Formular ist öffentlich (auth=None). Ein
    # einzelner Absender darf nur wenige Bewerbungen pro Stunde einreichen.
    from core.utils.throttle import client_ip, rate_limit
    if not rate_limit(f"bewerbung:{client_ip(request)}", limit=5, window_seconds=3600):
        return 429, {"success": False,
                     "error": "Zu viele Bewerbungen in kurzer Zeit. Bitte versuchen Sie es später erneut."}
    try:
        # `alle_organisationen`: Das Bewerbungsformular ist ÖFFENTLICH (auth=None).
        # Es gibt keine Anmeldung, aus der die Middleware eine Verwaltung
        # ableiten könnte — über `Einheit.objects` fand dieser Endpunkt seit
        # Etappe 6.2 gar nichts mehr und quittierte jede Bewerbung mit einem
        # Fehler. Wessen Objekt gemeint ist, sagt die Einheit selbst.
        #
        # Die Absicherung ist `zur_ausschreibung` weiter unten (identisch zu
        # `core/views/application.py`), nicht der Manager.
        einheit = get_object_or_404(Einheit.alle_organisationen, id=einheit_id)

        # Ab hier im Kontext DIESER Verwaltung: Die Bewerbung, die gleich
        # angelegt wird, und alles Nachgelagerte gehören ihr. Die Middleware
        # stellt den vorherigen (leeren) Kontext nach der Antwort wieder her.
        from core.tenancy import setze_organisation
        setze_organisation(einheit.organisation)

        # Bewerbungen nur für ausgeschriebene Objekte.
        #
        # Hier stand ein «flexibler Check auf Vermietungsstatus», der
        # `ist_vermietet` bzw. `vermietungs_status` per hasattr abfragte —
        # BEIDE Namen gibt es an `Einheit` nicht. `is_rented` blieb damit immer
        # False, die Prüfung lief ins Leere und die Fehlermeldung war
        # unerreichbar. Faktisch nahm die Adresse Bewerbungen für jede
        # Objektnummer entgegen, auch für seit Jahren vermietete.
        #
        # `zur_ausschreibung` ist der Schalter, den die App ohnehin führt: Der
        # Portal-Feed liefert danach aus, und beim Aktivwerden eines Vertrags
        # wird er automatisch gelöscht.
        if not einheit.zur_ausschreibung:
            return 400, {"success": False,
                         "error": "Dieses Objekt ist nicht mehr ausgeschrieben."}

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
