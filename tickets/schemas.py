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
    gemeldet_von_name: str  # Dynamischer Name für das Frontend
    erstellt_formatiert: str

    # Sektionsfelder aus dem Multi-Step-Formular
    kategorie: Optional[str] = None
    raum: Optional[str] = None
    objekt: Optional[str] = None
    email_melder: Optional[str] = None
    tel_melder: Optional[str] = None

    # 🔥 NEU: Die neuen, getrennten Namensfelder des Melders registrieren
    melder_vorname: Optional[str] = None
    melder_nachname: Optional[str] = None

    class Meta:
        model = SchadenMeldung
        # Alle Felder müssen in der fields-Liste registriert sein, damit Ninja sie ausgibt
        fields = [
            'id', 'titel', 'prioritaet', 'status', 'gelesen', 'erstellt_am',
            'kategorie', 'raum', 'objekt', 'email_melder', 'tel_melder',
            'melder_vorname', 'melder_nachname'
        ]

    @staticmethod
    def resolve_liegenschaft_name(obj):
        return obj.liegenschaft.strasse if obj.liegenschaft else "-"

    @staticmethod
    def resolve_einheit_bezeichnung(obj):
        return obj.betroffene_einheit.bezeichnung if obj.betroffene_einheit else "Allgemein"

    @staticmethod
    def resolve_gemeldet_von_name(obj):
        # 🟢 Priorität 1: Der Melder ist als Mieter im CRM verknüpft
        if obj.gemeldet_von:
            return f"{obj.gemeldet_von.vorname} {obj.gemeldet_von.nachname}"

        # 🟡 Priorität 2: Kein CRM-Eintrag, wir nutzen die erfassten Formulardaten
        if obj.melder_vorname or obj.melder_nachname:
            return f"{obj.melder_vorname or ''} {obj.melder_nachname or ''}".strip()

        return "Unbekannter Melder"

    @staticmethod
    def resolve_erstellt_formatiert(obj):
        return obj.erstellt_am.strftime('%d.%m.%Y') if obj.erstellt_am else ""

class SchadenMeldungDetailSchema(SchadenMeldungListSchema):
    beschreibung: str
    zutritt: Optional[str] = None
    foto: Optional[str] = None # Für das Bild-Preview im Vollbild
    nachrichten: List[TicketNachrichtSchema] = []
    auftraege: List[HandwerkerAuftragSchema] = []

    class Meta:
        model = SchadenMeldung
        fields = ['id', 'titel', 'beschreibung', 'prioritaet', 'status', 'gelesen', 'erstellt_am', 'zutritt']

    # Wandelt das ImageField von Django in eine klickbare URL um
    @staticmethod
    def resolve_foto(obj):
        if obj.foto:
            return obj.foto.url
        return None

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

# ==========================================
# 🔥 NEU: Handwerker Schema für das Dropdown
# ==========================================
class HandwerkerOutSchema(Schema):
    id: int
    firma: str
    kontaktperson: Optional[str] = None
    branche: str
    branche_label: Optional[str] = None
    email: str
    telefon: Optional[str] = None