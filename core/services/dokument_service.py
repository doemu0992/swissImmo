# core/services/dokument_service.py
"""Erzeugt die Fairwalter-Begleitdokumente zum Mietvertrag als PDF."""
from django.template.loader import get_template
from django.utils import timezone
from crm.models import Organisation
from core.services.pdf_service import link_callback
from core.services.pdf_text import format_chf, html_zu_pdf
from core.services.dokumentsprache import STANDARD, in_sprache, sprache_von

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

#: Diese Dokumente entstehen in der Sprache des Mieters (D11). Sie enthalten
#: keinen Rechtstext: Begleitbrief, Wohnungsausweis, Merkblatt. Alle übrigen
#: — Allgemeine Bedingungen, Hausordnung, Kündigungsbestätigung — bleiben
#: Deutsch, bis ihr Wortlaut juristisch geprüft übersetzt ist
#: (core/services/dokumentsprache.py).
IN_MIETERSPRACHE = frozenset({'wohnungsausweis', 'merkblatt-lueften', 'begleitbrief', 'begleitbrief-signiert'})


def generate_dokument_pdf_bytes(vertrag, doc_type):
    if doc_type not in DOKUMENT_TYPEN:
        raise ValueError(f"Unbekannter Dokumenttyp: {doc_type}")
    template_name, _titel, extra = DOKUMENT_TYPEN[doc_type]

    einheit = vertrag.einheit
    liegenschaft = einheit.liegenschaft
    eigentuemer = liegenschaft.eigentuemer
    verwaltung = liegenschaft.organisation

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
        'netto': format_chf(k.netto_mietzins or 0),
        'nk': format_chf(k.nebenkosten or 0),
        'brutto': format_chf(k.brutto),
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
        'brutto_fmt': format_chf(brutto),
        'kaution_fmt': format_chf(kaution),
        'mietzins_komponenten': komponenten,
        **extra,
    }

    sprache = sprache_von(vertrag.mieter) if doc_type in IN_MIETERSPRACHE else STANDARD
    with in_sprache(sprache):
        html = get_template(template_name).render({**context, 'dokumentsprache': sprache})
    return html_zu_pdf(html, link_callback=link_callback, quelle=_titel)
