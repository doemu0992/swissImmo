# core/services/dokument_service.py
"""Erzeugt die Fairwalter-Begleitdokumente zum Mietvertrag als PDF."""
import io
from django.template.loader import get_template
from django.utils import timezone
from xhtml2pdf import pisa
from crm.models import Verwaltung
from core.services.pdf_service import link_callback

# doc_type -> (Template, Titel, zusätzliche Kontext-Flags)
DOKUMENT_TYPEN = {
    'allgemeine-bedingungen': ('core/dok_allgemeine_bedingungen.html', 'Allgemeine Bedingungen', {}),
    'hausordnung':            ('core/dok_hausordnung.html',            'Hausordnung', {}),
    'merkblatt-lueften':      ('core/dok_merkblatt_lueften.html',      'Merkblatt Lüften', {}),
    'wohnungsausweis':        ('core/dok_wohnungsausweis.html',        'Wohnungsausweis', {}),
    'begleitbrief':           ('core/dok_begleitbrief.html',           'Begleitbrief Mietvertrag', {'signed': False}),
    'begleitbrief-signiert':  ('core/dok_begleitbrief.html',           'Begleitbrief unterzeichneter Vertrag', {'signed': True}),
    'kuendigungsbestaetigung': ('core/dok_kuendigungsbestaetigung.html', 'Kündigungsbestätigung', {}),
}


def generate_dokument_pdf_bytes(vertrag, doc_type):
    if doc_type not in DOKUMENT_TYPEN:
        raise ValueError(f"Unbekannter Dokumenttyp: {doc_type}")
    template_name, _titel, extra = DOKUMENT_TYPEN[doc_type]

    einheit = vertrag.einheit
    liegenschaft = einheit.liegenschaft
    eigentuemer = liegenschaft.eigentuemer
    verwaltung = liegenschaft.verwaltung or Verwaltung.objects.first()

    # Vermieter = Eigentümer falls vorhanden, sonst Verwaltung
    if eigentuemer:
        v_name = getattr(eigentuemer, 'firma_oder_name', str(eigentuemer))
        v_str, v_plz, v_ort = eigentuemer.strasse, eigentuemer.plz, eigentuemer.ort
    elif verwaltung:
        v_name, v_str, v_plz, v_ort = verwaltung.firma, verwaltung.strasse, verwaltung.plz, verwaltung.ort
    else:
        v_name = v_str = v_plz = v_ort = ''

    netto = vertrag.netto_mietzins or 0
    nk = vertrag.nebenkosten or 0
    brutto = netto + nk
    kaution = vertrag.kautions_betrag or 0

    # Datierte Mietzins-Komponenten (Gratismonate/gestaffelter Start) für den Vertrag
    komponenten = [{
        'ab': k.gueltig_ab.strftime('%d.%m.%Y'),
        'netto': f"{(k.netto_mietzins or 0):,.2f}".replace(",", "'"),
        'nk': f"{(k.nebenkosten or 0):,.2f}".replace(",", "'"),
        'brutto': f"{k.brutto:,.2f}".replace(",", "'"),
        'notiz': k.notiz or '',
    } for k in vertrag.mietzins_komponenten.all()]

    # Zweiter Mieter (2-Personen-Vertrag): Objekt bevorzugt, sonst Freitext-Name
    mitmieter = vertrag.mitmieter
    mitmieter_name = (mitmieter.display_name if mitmieter else (vertrag.mitmieter_name or '')).strip()

    context = {
        'vertrag': vertrag, 'mieter': vertrag.mieter, 'einheit': einheit,
        'mitmieter': mitmieter, 'mitmieter_name': mitmieter_name,
        'liegenschaft': liegenschaft, 'eigentuemer': eigentuemer, 'verwaltung': verwaltung,
        'heute': timezone.localdate(),
        'vermieter_name': v_name, 'vermieter_strasse': v_str,
        'vermieter_plz': v_plz, 'vermieter_ort': v_ort,
        'brutto_fmt': f"{brutto:,.2f}".replace(",", "'"),
        'kaution_fmt': f"{kaution:,.2f}".replace(",", "'"),
        'mietzins_komponenten': komponenten,
        **extra,
    }

    html = get_template(template_name).render(context)
    buffer = io.BytesIO()
    status = pisa.CreatePDF(html, dest=buffer, link_callback=link_callback, encoding='utf-8')
    if status.err:
        raise Exception(f"Fehler bei der PDF-Generierung: {status.err}")
    return buffer.getvalue()
