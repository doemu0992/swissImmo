# crm/schemas.py
from ninja import ModelSchema, Schema
from typing import List, Optional
from datetime import date
from .models import Mieter

class MieterDokumentSchema(Schema):
    id: int
    titel: str
    kategorie: str
    datei_url: str
    datum: date
    is_vertrag: bool = False # 🔥 Steuert den Papierkorb-Button im Frontend

class MieterSchemaOut(ModelSchema):
    display_name: str
    dokumente: List[MieterDokumentSchema] = []

    class Meta:
        model = Mieter
        fields = [
            'id', 'typ', 'anrede', 'vorname', 'nachname', 'firmen_name',
            'strasse', 'plz', 'ort', 'email', 'mobile', 'telefon_privat',
            'telefon_geschaeft', 'iban', 'bank_name', 'geburtsdatum',
            'nationalitaet', 'ahv_nummer', 'zivilstand', 'bonitaet_datum', 'notizen'
        ]

    @staticmethod
    def resolve_display_name(obj):
        return obj.display_name

    @staticmethod
    def resolve_dokumente(obj):
        try:
            from rentals.models import Dokument
            docs = Dokument.objects.filter(mieter=obj).order_by('-datum')
            return [{
                # 🔥 WICHTIG: Hier addieren wir 10000, damit die Delete-API weiss,
                # dass es sich um ein Dokument aus dem Rentals-Modul handelt!
                "id": d.id + 10000,
                "titel": d.titel or d.bezeichnung,
                "kategorie": d.get_kategorie_display() if hasattr(d, 'get_kategorie_display') else d.kategorie,
                "datei_url": d.datei.url if d.datei and hasattr(d.datei, 'url') else "",
                "datum": d.datum or date.today(),
                "is_vertrag": d.kategorie == 'vertrag' # Verträge werden markiert (für Sicherheits-Prompt)
            } for d in docs]
        except Exception:
            return []

class MieterUpdateSchema(Schema):
    typ: Optional[str] = None
    firmen_name: Optional[str] = None
    uid_nummer: Optional[str] = None
    kontaktperson: Optional[str] = None
    anrede: Optional[str] = None
    vorname: Optional[str] = None
    nachname: Optional[str] = None
    geburtsdatum: Optional[date] = None
    ahv_nummer: Optional[str] = None
    zivilstand: Optional[str] = None
    nationalitaet: Optional[str] = None
    email: Optional[str] = None
    telefon_privat: Optional[str] = None
    telefon_geschaeft: Optional[str] = None
    mobile: Optional[str] = None
    sprache: Optional[str] = None
    strasse: Optional[str] = None
    adresszusatz: Optional[str] = None
    postfach: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None
    land: Optional[str] = None
    iban: Optional[str] = None
    bank_name: Optional[str] = None
    bonitaet_datum: Optional[date] = None
    notizen: Optional[str] = None