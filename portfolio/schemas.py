# portfolio/schemas.py
from ninja import ModelSchema, Schema
from typing import List, Optional
from decimal import Decimal
from datetime import date
from django.db import models
from .models import Liegenschaft, Einheit, Geraet, Zaehler, Schluessel, Unterhalt, Dokument, Verteilschluessel, LiegenschaftVerteilschluessel

class DokumentSchemaOut(Schema):
    id: int
    titel: str
    kategorie: str
    datum: date
    datei_url: str
    is_vertrag: bool = False

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

class VerteilschluesselSchemaOut(Schema):
    id: int
    kostenart: str
    kostenart_display: str
    typ: str
    typ_display: str
    wert: Decimal
    gueltig_ab: date
    gueltig_bis: Optional[date] = None
    notizen: str = ""

class LiegenschaftVerteilschluesselSchemaOut(ModelSchema):
    kostenart_display: str
    typ_display: str

    class Meta:
        model = LiegenschaftVerteilschluessel
        fields = ['id', 'kostenart', 'typ', 'wert', 'gueltig_ab', 'gueltig_bis', 'notizen']

    @staticmethod
    def resolve_kostenart_display(obj):
        return obj.get_kostenart_display()

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
    verteilschluessel: List[VerteilschluesselSchemaOut] = []

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
        except Exception: pass
        return history

    @staticmethod
    def resolve_dokumente(obj):
        docs_out = []
        seen_urls = set()
        try:
            for d in obj.dokument_set.all():
                url = d.datei.url if d.datei and hasattr(d.datei, 'url') else ""
                if not url or url in seen_urls: continue
                seen_urls.add(url)
                docs_out.append({"id": d.id, "titel": d.titel or "Dokument", "kategorie": getattr(d, 'kategorie', 'Allgemein'), "datum": getattr(d, 'datum', date.today()), "datei_url": url, "is_vertrag": False})
        except Exception: pass

        try:
            from rentals.models import Dokument as RentalsDokument
            for d in RentalsDokument.objects.filter(einheit=obj):
                url = d.datei.url if d.datei and hasattr(d.datei, 'url') else ""
                if not url or url in seen_urls: continue
                seen_urls.add(url)
                kat = d.get_kategorie_display() if hasattr(d, 'get_kategorie_display') else 'Vertrag'
                docs_out.append({"id": d.id + 10000, "titel": d.titel or d.bezeichnung, "kategorie": kat, "datum": getattr(d, 'datum', date.today()), "datei_url": url, "is_vertrag": True})
        except Exception: pass
        docs_out.sort(key=lambda x: x["datum"], reverse=True)
        return docs_out

    @staticmethod
    def resolve_verteilschluessel(obj):
        result = []
        manual_keys = list(obj.verteilschluessel.all())
        manual_kostenarten = [k.kostenart for k in manual_keys]

        # 1. Manuelle Schlüssel immer anzeigen (egal ob Garage oder Wohnung)
        for mk in manual_keys:
            result.append({
                "id": mk.id, "kostenart": mk.kostenart, "kostenart_display": mk.get_kostenart_display(),
                "typ": mk.typ, "typ_display": mk.get_typ_display(), "wert": mk.wert,
                "gueltig_ab": mk.gueltig_ab, "gueltig_bis": mk.gueltig_bis, "notizen": mk.notizen or "Individuell"
            })

        # 🔥 GEFIXT: Standards der Liegenschaft NUR bei Hauptobjekten anwenden!
        if obj.typ in ['whg', 'gew', 'stwe']:
            try:
                standards = obj.liegenschaft.standard_schluessel.all()
                for std in standards:
                    if std.kostenart in manual_kostenarten: continue

                    calc_wert = std.wert # Bei Pauschal wird der Wert des Standards genommen
                    if std.typ == 'm2' and obj.flaeche_m2: calc_wert = obj.flaeche_m2
                    elif std.typ == 'm3' and obj.volumen_m3: calc_wert = obj.volumen_m3
                    elif std.typ == 'wertquote' and obj.wertquote: calc_wert = obj.wertquote
                    elif std.typ == 'zimmer' and obj.zimmer: calc_wert = obj.zimmer
                    elif std.typ == 'einheit': calc_wert = Decimal('1.00')

                    result.append({
                        "id": -std.id,
                        "kostenart": std.kostenart, "kostenart_display": std.get_kostenart_display(),
                        "typ": std.typ, "typ_display": std.get_typ_display(), "wert": calc_wert,
                        "gueltig_ab": std.gueltig_ab, "gueltig_bis": std.gueltig_bis,
                        "notizen": std.notizen or "Automatisch (Liegenschafts-Standard)"
                    })
            except Exception: pass

        return result

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

class VerteilschluesselUebersichtSchema(Schema):
    einheit_bezeichnung: str
    kostenart_display: str
    typ_display: str
    wert: Decimal
    is_auto: bool = False

class LiegenschaftListSchema(ModelSchema):
    einheiten: List[NebenobjektSchemaOut] = []
    class Meta:
        model = Liegenschaft
        fields = ['id', 'strasse', 'plz', 'ort', 'kanton']

class LiegenschaftDetailSchema(ModelSchema):
    einheiten: List[EinheitSchemaOut]
    dokumente: List[DokumentSchemaOut] = []
    allgemeine_geraete: List[GeraetSchemaOut] = []
    verteilschluessel_uebersicht: List[VerteilschluesselUebersichtSchema] = []
    standard_schluessel: List[LiegenschaftVerteilschluesselSchemaOut] = []

    class Meta:
        model = Liegenschaft
        exclude = ['mandant', 'verwaltung']

    @staticmethod
    def resolve_verteilschluessel_uebersicht(obj):
        uebersicht = []
        try:
            einheiten = obj.einheiten.all()
            standards = obj.standard_schluessel.all()
            for e in einheiten:
                manual_keys = {k.kostenart: k for k in e.verteilschluessel.all()}

                # Manuelle Schlüssel immer laden
                for mk in manual_keys.values():
                    uebersicht.append({"einheit_bezeichnung": e.bezeichnung, "kostenart_display": mk.get_kostenart_display(), "typ_display": mk.get_typ_display(), "wert": mk.wert, "is_auto": False})

                # 🔥 GEFIXT: Standards nur für Hauptobjekte in die Übersicht laden!
                if e.typ in ['whg', 'gew', 'stwe']:
                    for std in standards:
                        if std.kostenart not in manual_keys:
                            calc_wert = std.wert
                            if std.typ == 'm2' and e.flaeche_m2: calc_wert = e.flaeche_m2
                            elif std.typ == 'm3' and e.volumen_m3: calc_wert = e.volumen_m3
                            elif std.typ == 'wertquote' and e.wertquote: calc_wert = e.wertquote
                            elif std.typ == 'zimmer' and e.zimmer: calc_wert = e.zimmer
                            elif std.typ == 'einheit': calc_wert = Decimal('1.00')

                            uebersicht.append({"einheit_bezeichnung": e.bezeichnung, "kostenart_display": std.get_kostenart_display(), "typ_display": std.get_typ_display(), "wert": calc_wert, "is_auto": True})

            uebersicht.sort(key=lambda x: (x["kostenart_display"], x["einheit_bezeichnung"]))
        except Exception: pass
        return uebersicht

    @staticmethod
    def resolve_dokumente(obj):
        docs_out = []
        seen_urls = set()
        try:
            for d in obj.dokument_set.all():
                url = d.datei.url if d.datei and hasattr(d.datei, 'url') else ""
                if not url or url in seen_urls: continue
                seen_urls.add(url)
                docs_out.append({"id": d.id, "titel": d.titel or "Dokument", "kategorie": getattr(d, 'kategorie', 'Allgemein'), "datum": getattr(d, 'datum', date.today()), "datei_url": url, "is_vertrag": False})
        except Exception: pass

        try:
            from rentals.models import Dokument as RentalsDokument
            for d in RentalsDokument.objects.filter(liegenschaft=obj):
                url = d.datei.url if d.datei and hasattr(d.datei, 'url') else ""
                if not url or url in seen_urls: continue
                seen_urls.add(url)
                kat = d.get_kategorie_display() if hasattr(d, 'get_kategorie_display') else 'Vertrag'
                docs_out.append({"id": d.id + 10000, "titel": d.titel or d.bezeichnung, "kategorie": kat, "datum": getattr(d, 'datum', date.today()), "datei_url": url, "is_vertrag": True})
        except Exception: pass

        docs_out.sort(key=lambda x: x["datum"], reverse=True)
        return docs_out

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