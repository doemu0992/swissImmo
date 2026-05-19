from ninja import Schema
from typing import Optional
from datetime import date, datetime

class BewerbungCreateSchema(Schema):
    # Da wir für Datei-Uploads (Multi-part Form Data) die Felder direkt via Form(...)
    # in der api.py entgegennehmen, wird dieses Schema für den POST-Request nicht zwingend benötigt.
    # Wir lassen es für eventuelle andere Importe oder spätere Erweiterungen defensiv hier stehen.
    pass

class BewerbungSchemaOut(Schema):
    id: int
    einheit_id: int
    objekt_bezeichnung: str
    liegenschaft_strasse: str
    status: str

    # --- Personalien ---
    vorname: str
    nachname: str
    zivilstand: Optional[str] = None
    geburtsdatum: date
    geschlecht: Optional[str] = None
    nationalitaet: Optional[str] = None
    heimatort: Optional[str] = None

    # --- Kontakt & Adresse ---
    mobilnummer: str
    telefon: Optional[str] = None  # Wichtiges Fallback für das Frontend-Modal
    email: str
    adresse: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None

    # --- Vorheriger Vermieter ---
    aktueller_vermieter: Optional[str] = None
    kontaktperson_vermieter: Optional[str] = None
    telefon_vermieter: Optional[str] = None
    email_vermieter: Optional[str] = None

    # --- Beruf & Finanzen ---
    erwerbsstatus: Optional[str] = None
    beruf: str
    einkommen_jahr: str  # 🌟 Umgestellt von float auf str für die Flatfox-Spannen
    arbeitgeber: Optional[str] = None
    angestellt_seit: Optional[date] = None
    kontaktperson_arbeitgeber: Optional[str] = None
    telefon_arbeitgeber: Optional[str] = None
    email_arbeitgeber: Optional[str] = None
    ist_unbefristet: bool = True

    # --- Wohnsituation & Parameter ---
    hat_betreibungen: bool = False
    grund_fuer_wechsel: Optional[str] = None
    anzahl_erwachsene: int = 1
    anzahl_kinder: int = 0
    anzahl_personen: Optional[int] = 1  # Berechnetes Fallback für die Kanban-Kärtchen
    haustiere: bool = False
    haustiere_details: Optional[str] = None
    musikinstrumente: bool = False
    interesse_parkplatz: bool = False
    gewuenschter_bezugstermin: Optional[date] = None
    bemerkungen: Optional[str] = None

    # --- Schilder & Onboarding ---
    schild_briefkasten: Optional[str] = None
    schild_sonnerie: Optional[str] = None
    wunsch_kautions_typ: str = 'bank'

    # --- Dokumente-Links ---
    digitaler_betreibungsauszug: bool = False
    betreibungsauszug_url: Optional[str] = None
    ausweiskopie_url: Optional[str] = None
    lohnausweis_url: Optional[str] = None
    weitere_dokumente_url: Optional[str] = None

    erstellt_am: datetime