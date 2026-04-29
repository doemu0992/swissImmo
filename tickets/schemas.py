# tickets/schemas.py
from ninja import ModelSchema, Schema
from typing import Optional, List
from .models import SchadenMeldung, HandwerkerAuftrag, TicketNachricht

class TicketNachrichtSchema(ModelSchema):
    class Meta:
        model = TicketNachricht
        fields = ['id', 'typ', 'absender_name', 'nachricht', 'erstellt_am']

class HandwerkerAuftragSchema(ModelSchema):
    handwerker_name: str

    class Meta:
        model = HandwerkerAuftrag
        fields = ['id', 'status', 'bemerkung', 'beauftragt_am']

    @staticmethod
    def resolve_handwerker_name(obj):
        return str(obj.handwerker)

class SchadenMeldungListSchema(ModelSchema):
    liegenschaft_name: str
    einheit_bezeichnung: str
    mieter_name: str
    erstellt_formatiert: str

    class Meta:
        model = SchadenMeldung
        fields = ['id', 'titel', 'prioritaet', 'status', 'gelesen', 'erstellt_am']

    @staticmethod
    def resolve_liegenschaft_name(obj):
        return obj.liegenschaft.strasse if obj.liegenschaft else "-"

    @staticmethod
    def resolve_einheit_bezeichnung(obj):
        return obj.betroffene_einheit.bezeichnung if obj.betroffene_einheit else "Allgemein"

    @staticmethod
    def resolve_mieter_name(obj):
        return str(obj.gemeldet_von) if obj.gemeldet_von else "Unbekannt"

    @staticmethod
    def resolve_erstellt_formatiert(obj):
        return obj.erstellt_am.strftime('%d.%m.%Y') if obj.erstellt_am else ""

class SchadenMeldungDetailSchema(SchadenMeldungListSchema):
    beschreibung: str
    zutritt: str
    nachrichten: List[TicketNachrichtSchema] = []
    auftraege: List[HandwerkerAuftragSchema] = []

    class Meta:
        model = SchadenMeldung
        fields = ['id', 'titel', 'beschreibung', 'prioritaet', 'status', 'gelesen', 'erstellt_am', 'zutritt']

    # 🔥 DIESER RESOLVER HAT GEFEHLT! Er sagt Ninja, woher die "auftraege" kommen.
    @staticmethod
    def resolve_auftraege(obj):
        return list(obj.handwerker_auftraege.all())

# Hilfs-Schemas für die Aktionen
class TicketNachrichtCreateSchema(Schema):
    nachricht: str

class TicketStatusUpdateSchema(Schema):
    status: str

class SuccessSchema(Schema):
    success: bool