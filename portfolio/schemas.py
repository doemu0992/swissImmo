# portfolio/schemas.py
from ninja import ModelSchema, Schema
from typing import List, Optional
from decimal import Decimal
from datetime import date
from django.db import models
from .models import Liegenschaft, Einheit, Geraet, Zaehler, Schluessel, Unterhalt, Dokument

class DokumentSchemaOut(ModelSchema):
    datei_url: str
    class Meta:
        model = Dokument
        # 🔥 GEFIXT: 'erstellt_am' zu 'datum' geändert, passend zum Modell
        fields = ['id', 'titel', 'kategorie', 'datum']

    @staticmethod
    def resolve_datei_url(obj):
        try:
            if obj.datei and hasattr(obj.datei, 'url'): return obj.datei.url
        except Exception: pass
        return ""

class UnterhaltSchemaOut(ModelSchema):
    class Meta:
        model = Unterhalt
        fields = ['id', 'titel', 'beschreibung', 'datum', 'kosten']

class ZaehlerSchemaOut(ModelSchema):
    typ_display: str
    class Meta:
        model = Zaehler
        fields = ['id', 'typ', 'zaehler_nummer', 'standort', 'aktueller_stand']

    @staticmethod
    def resolve_typ_display(obj):
        return obj.get_typ_display()

class SchluesselSchemaOut(ModelSchema):
    class Meta:
        model = Schluessel
        fields = ['id', 'typ', 'schluessel_nummer', 'anzahl']

class GeraetSchemaOut(ModelSchema):
    kategorie_display: str
    class Meta:
        model = Geraet
        fields = ['id', 'kategorie', 'sonstiges_bezeichnung', 'marke', 'modell', 'installations_datum', 'garantie_bis']

    @staticmethod
    def resolve_kategorie_display(obj):
        if obj.kategorie == 'sonstiges' and obj.sonstiges_bezeichnung: return obj.sonstiges_bezeichnung
        return obj.kategorie.title()

class HistorieSchemaOut(Schema):
    mieter_name: str
    start_datum: date
    ende_datum: Optional[date]
    nettomiete: Decimal

class NebenobjektSchemaOut(ModelSchema):
    typ_display: str
    class Meta:
        model = Einheit
        fields = ['id', 'bezeichnung', 'typ', 'nettomiete_aktuell']

    @staticmethod
    def resolve_typ_display(obj):
        return obj.get_typ_display()

class EinheitSchemaOut(ModelSchema):
    typ_display: str
    aktueller_mieter: str
    vermietungs_status: str
    geraete: List[GeraetSchemaOut] = []
    zaehler: List[ZaehlerSchemaOut] = []
    schluessel_liste: List[SchluesselSchemaOut] = []
    unterhalte: List[UnterhaltSchemaOut] = []
    dokumente: List[DokumentSchemaOut] = []
    historie: List[HistorieSchemaOut] = []
    nebenobjekte: List[NebenobjektSchemaOut] = []

    class Meta:
        model = Einheit
        fields = [
            'id', 'bezeichnung', 'typ', 'etage', 'zimmer', 'flaeche_m2', 'volumen_m3',
            'nettomiete_aktuell', 'nebenkosten_aktuell', 'nk_abrechnungsart', 'wertquote',
            'heizkosten_verteilschluessel', 'notizen', 'ewid', 'oto_dose', 'keller', 'estrich',
            'bodenbelag', 'bodenbelag_nassraum', 'letzte_renovation', 'gehoert_zu'
        ]

    @staticmethod
    def resolve_typ_display(obj):
        return obj.get_typ_display()

    @staticmethod
    def resolve_aktueller_mieter(obj):
        try:
            heute = date.today()
            aktiver_vertrag = obj.vertraege.filter(
                status__in=['aktiv', 'gekuendigt'],
                beginn__lte=heute
            ).filter(models.Q(ende__isnull=True) | models.Q(ende__gte=heute)).first()

            if aktiver_vertrag:
                return f"{aktiver_vertrag.mieter.vorname} {aktiver_vertrag.mieter.nachname}"

            zukuenftig = obj.vertraege.filter(status='aktiv', beginn__gt=heute).first()
            if zukuenftig:
                return f"Ab {zukuenftig.beginn.strftime('%d.%m.%Y')}: {zukuenftig.mieter.display_name}"

        except Exception: pass
        return "Leerstand"

    @staticmethod
    def resolve_vermietungs_status(obj):
        try:
            heute = date.today()
            ist_vermietet = obj.vertraege.filter(
                status__in=['aktiv', 'gekuendigt'],
                beginn__lte=heute
            ).filter(models.Q(ende__isnull=True) | models.Q(ende__gte=heute)).exists()

            return "vermietet" if ist_vermietet else "leerstand"
        except Exception:
            return "leerstand"

    @staticmethod
    def resolve_historie(obj):
        history = []
        try:
            for v in obj.vertraege.all().order_by('-beginn'):
                name = v.mieter.display_name if v.mieter else "Unbekannt"
                history.append({
                    'mieter_name': name,
                    'start_datum': v.beginn,
                    'ende_datum': v.ende,
                    'nettomiete': v.netto_mietzins or Decimal('0.00')
                })
        except Exception:
            pass
        return history

    # 🔥 GEFIXT: Lädt automatisch alle Dokumente der Einheit (sortiert nach datum!)
    @staticmethod
    def resolve_dokumente(obj):
        try:
            return obj.dokument_set.all().order_by('-datum')
        except Exception:
            return []

class EinheitCreateSchema(Schema):
    bezeichnung: str
    typ: str = 'whg'
    etage: str = ''
    ewid: str = ''
    oto_dose: str = ''
    bodenbelag: str = ''
    bodenbelag_nassraum: str = ''
    keller: str = ''
    estrich: str = ''
    zimmer: Optional[Decimal] = None
    flaeche_m2: Optional[Decimal] = None
    volumen_m3: Optional[Decimal] = None
    wertquote: Optional[Decimal] = None
    heizkosten_verteilschluessel: str = 'm2'
    notizen: str = ''
    letzte_renovation: Optional[int] = None
    nettomiete_aktuell: Decimal = Decimal('0.00')
    nebenkosten_aktuell: Decimal = Decimal('0.00')
    nk_abrechnungsart: str = 'akonto'

class LiegenschaftListSchema(ModelSchema):
    einheiten: List[NebenobjektSchemaOut] = []
    class Meta:
        model = Liegenschaft
        fields = ['id', 'strasse', 'plz', 'ort', 'kanton']

class LiegenschaftDetailSchema(ModelSchema):
    einheiten: List[EinheitSchemaOut]
    dokumente: List[DokumentSchemaOut] = []
    allgemeine_geraete: List[GeraetSchemaOut] = []
    class Meta:
        model = Liegenschaft
        exclude = ['mandant', 'verwaltung']

    # 🔥 GEFIXT: Lädt automatisch alle Dokumente der Liegenschaft (sortiert nach datum!)
    @staticmethod
    def resolve_dokumente(obj):
        try:
            return obj.dokument_set.all().order_by('-datum')
        except Exception:
            return []

class LiegenschaftUpdateSchema(Schema):
    strasse: str = ""
    plz: str = ""
    ort: str = ""
    egid: Optional[str] = ""
    baujahr: Optional[int] = None
    kataster_nummer: Optional[str] = ""
    versicherungswert: Optional[Decimal] = None
    grundstuecksflaeche_m2: Optional[Decimal] = None
    gebaeudevolumen_m3: Optional[Decimal] = None
    hauswart_name: str = ""
    hauswart_telefon: str = ""
    sanitaer_name: str = ""
    sanitaer_telefon: str = ""
    elektriker_name: str = ""
    elektriker_telefon: str = ""