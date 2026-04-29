# finance/schemas.py
from ninja import ModelSchema, Schema
from typing import List, Optional
from datetime import date
from decimal import Decimal
from .models import Zahlungseingang, AbrechnungsPeriode

class ZahlungSchemaOut(ModelSchema):
    mieter_name: str
    objekt_info: str

    class Meta:
        model = Zahlungseingang
        fields = ['id', 'betrag', 'datum_eingang', 'buchungs_monat', 'bemerkung']

    @staticmethod
    def resolve_mieter_name(obj):
        return str(obj.vertrag.mieter) if obj.vertrag else "Unbekannt"

    @staticmethod
    def resolve_objekt_info(obj):
        if obj.vertrag and obj.vertrag.einheit:
            return f"{obj.vertrag.einheit.liegenschaft.strasse} - {obj.vertrag.einheit.bezeichnung}"
        return "-"

class ZahlungCreateSchema(Schema):
    vertrag_id: int
    betrag: Decimal
    datum_eingang: date
    buchungs_monat: date
    bemerkung: Optional[str] = ""

class MietzinsKontrolleSchema(Schema):
    vertrag_id: int
    mieter_name: str
    objekt: str
    soll: Decimal
    ist: Decimal
    differenz: Decimal
    status: str # 'Bezahlt', 'Teilzahlung', 'Offen'