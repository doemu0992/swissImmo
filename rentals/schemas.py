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

    class Meta:
        model = Mietvertrag
        fields = [
            'id', 'beginn', 'ende', 'netto_mietzins', 'nebenkosten',
            'nk_abrechnungsart', 'verteilschluessel', 'ausgeschlossene_kosten',
            'basis_referenzzinssatz', 'basis_lik_punkte', 'aktiv', 'sign_status',
            'status', 'kuendigungsfrist_monate', 'kuendigungstermine',
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

class VertragCreateSchema(Schema):
    mieter_id: int
    einheit_id: int
    beginn: date
    netto_mietzins: Decimal
    nebenkosten: Decimal
    status: str = 'entwurf'
    nk_abrechnungsart: str = 'akonto'
    verteilschluessel: str = 'm2'

class VertragUpdateSchema(Schema):
    status: Optional[str] = None
    beginn: Optional[date] = None
    ende: Optional[date] = None
    kuendigungsfrist_monate: Optional[int] = None
    kuendigungstermine: Optional[str] = None
    netto_mietzins: Optional[Decimal] = None
    nebenkosten: Optional[Decimal] = None
    nk_abrechnungsart: Optional[str] = None
    verteilschluessel: Optional[str] = None
    ausgeschlossene_kosten: Optional[str] = None
    kautions_betrag: Optional[Decimal] = None
    kautions_konto: Optional[str] = None
    kautions_einbezahlt_am: Optional[date] = None
    sign_status: Optional[str] = None