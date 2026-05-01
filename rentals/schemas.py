# rentals/schemas.py
from ninja import ModelSchema, Schema
from typing import Optional
from datetime import date
from decimal import Decimal
from .models import Mietvertrag

class VertragSchemaOut(ModelSchema):
    mieter_name: str
    einheit_name: str
    liegenschaft_name: str
    brutto_mietzins: Decimal
    status_display: str
    pdf_datei: Optional[str] = None

    class Meta:
        model = Mietvertrag
        fields = [
            'id', 'beginn', 'ende', 'erstmals_kuendbar_auf', 'netto_mietzins', 'nebenkosten',
            'nk_abrechnungsart', 'verteilschluessel', 'ausgeschlossene_kosten', 'zahlungsrhythmus',
            'familienwohnung', 'mitmieter_name', 'anzahl_personen', 'besondere_vereinbarungen', # 🔥 HIER HINZUGEFÜGT
            'basis_referenzzinssatz', 'basis_lik_punkte', 'kostensteigerung_datum',
            'mietzinsreserve_betrag', 'mietzinsreserve_prozent', 'weitere_vorbehalte',
            'aktiv', 'sign_status', 'status', 'kuendigungsfrist_monate', 'kuendigungstermine',
            'kautions_betrag', 'kautions_konto', 'kautions_einbezahlt_am'
        ]

    @staticmethod
    def resolve_mieter_name(obj):
        return obj.mieter.display_name if obj.mieter else "Unbekannt"

    @staticmethod
    def resolve_einheit_name(obj):
        return obj.einheit.bezeichnung if obj.einheit else "Unbekannt"

    @staticmethod
    def resolve_liegenschaft_name(obj):
        return obj.einheit.liegenschaft.strasse if (obj.einheit and obj.einheit.liegenschaft) else ""

    @staticmethod
    def resolve_brutto_mietzins(obj):
        return obj.brutto_mietzins

    @staticmethod
    def resolve_status_display(obj):
        return obj.get_status_display()

    @staticmethod
    def resolve_pdf_datei(obj):
        try:
            return obj.pdf_datei.url if obj.pdf_datei else None
        except Exception:
            return None

class VertragCreateSchema(Schema):
    mieter_id: int
    einheit_id: int
    beginn: date
    ende: Optional[date] = None
    erstmals_kuendbar_auf: Optional[date] = None
    netto_mietzins: Decimal
    nebenkosten: Decimal
    status: str = 'entwurf'
    nk_abrechnungsart: str = 'akonto'
    verteilschluessel: str = 'm2'
    zahlungsrhythmus: str = 'monatlich'

    familienwohnung: bool = False
    mitmieter_name: str = "" # 🔥 HIER HINZUGEFÜGT
    anzahl_personen: int = 1
    besondere_vereinbarungen: str = ""
    ausgeschlossene_kosten: str = ""

    kautions_betrag: Optional[Decimal] = None
    kuendigungsfrist_monate: Optional[int] = 3
    kuendigungstermine: Optional[str] = "Ende jedes Monats ausser Dezember"

    basis_referenzzinssatz: Optional[Decimal] = None
    basis_lik_punkte: Optional[Decimal] = None
    kostensteigerung_datum: Optional[date] = None
    mietzinsreserve_betrag: Optional[Decimal] = None
    mietzinsreserve_prozent: Optional[Decimal] = None
    weitere_vorbehalte: str = ""

class VertragUpdateSchema(Schema):
    status: Optional[str] = None
    beginn: Optional[date] = None
    ende: Optional[date] = None
    erstmals_kuendbar_auf: Optional[date] = None
    kuendigungsfrist_monate: Optional[int] = None
    kuendigungstermine: Optional[str] = None
    netto_mietzins: Optional[Decimal] = None
    nebenkosten: Optional[Decimal] = None
    nk_abrechnungsart: Optional[str] = None
    verteilschluessel: Optional[str] = None
    zahlungsrhythmus: Optional[str] = None

    familienwohnung: Optional[bool] = None
    mitmieter_name: Optional[str] = None # 🔥 HIER HINZUGEFÜGT
    anzahl_personen: Optional[int] = None
    besondere_vereinbarungen: Optional[str] = None
    ausgeschlossene_kosten: Optional[str] = None

    kautions_betrag: Optional[Decimal] = None
    kautions_konto: Optional[str] = None
    kautions_einbezahlt_am: Optional[date] = None
    sign_status: Optional[str] = None

    basis_referenzzinssatz: Optional[Decimal] = None
    basis_lik_punkte: Optional[Decimal] = None
    kostensteigerung_datum: Optional[date] = None
    mietzinsreserve_betrag: Optional[Decimal] = None
    mietzinsreserve_prozent: Optional[Decimal] = None
    weitere_vorbehalte: Optional[str] = None