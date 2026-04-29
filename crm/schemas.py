# crm/schemas.py
from ninja import ModelSchema, Schema
from typing import Optional
from datetime import date
from .models import Mieter

class MieterSchemaOut(ModelSchema):
    display_name: str
    class Meta:
        model = Mieter
        fields = [
            'id', 'typ', 'firmen_name', 'uid_nummer', 'kontaktperson',
            'anrede', 'vorname', 'nachname', 'geburtsdatum', 'ahv_nummer', 'zivilstand', 'nationalitaet',
            'email', 'telefon_privat', 'telefon_geschaeft', 'mobile', 'sprache',
            'strasse', 'adresszusatz', 'postfach', 'plz', 'ort', 'land',
            'iban', 'bank_name', 'bonitaet_datum', 'notizen'
        ]

    @staticmethod
    def resolve_display_name(obj):
        return obj.display_name

class MieterUpdateSchema(Schema):
    typ: str = 'person'
    firmen_name: str = ""
    uid_nummer: str = ""
    kontaktperson: str = ""
    anrede: str = ""
    vorname: str = ""
    nachname: str = ""
    geburtsdatum: Optional[date] = None
    ahv_nummer: str = ""
    zivilstand: str = ""
    nationalitaet: str = ""
    email: str = ""
    telefon_privat: str = ""
    telefon_geschaeft: str = ""
    mobile: str = ""
    sprache: str = "de"
    strasse: str = ""
    adresszusatz: str = ""
    postfach: str = ""
    plz: str = ""
    ort: str = ""
    land: str = "Schweiz"
    iban: str = ""
    bank_name: str = ""
    bonitaet_datum: Optional[date] = None
    notizen: str = ""