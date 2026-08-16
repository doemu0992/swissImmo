# core/services/pdf_service.py
import os
import io
from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.utils import timezone
from xhtml2pdf import pisa
from crm.models import Organisation

def make_image_transparent(image_path):
    """ Öffnet das Bild, entfernt den weissen Hintergrund und speichert es als transparentes PNG """
    if not image_path or not os.path.exists(image_path):
        return image_path

    try:
        from PIL import Image

        dir_name, file_name = os.path.split(image_path)
        name, ext = os.path.splitext(file_name)
        transparent_path = os.path.join(dir_name, f"{name}_transparent.png")

        # Wenn wir das Bild schon mal transparent gemacht haben, nehmen wir es direkt (spart Zeit)
        if os.path.exists(transparent_path):
            return transparent_path

        img = Image.open(image_path)
        img = img.convert("RGBA")
        datas = img.getdata()

        new_data = []
        # Wir prüfen jeden einzelnen Pixel. Wenn er (fast) weiss ist, machen wir ihn unsichtbar!
        for item in datas:
            if item[0] > 220 and item[1] > 220 and item[2] > 220:
                new_data.append((255, 255, 255, 0)) # Alpha auf 0 = Transparent
            else:
                new_data.append(item)

        img.putdata(new_data)
        img.save(transparent_path, "PNG")
        return transparent_path
    except Exception as e:
        print(f"Konnte Bild nicht transparent machen: {e}")
        return image_path # Falls ein Fehler passiert, nimm das Originalbild

def link_callback(uri, rel):
    if os.path.isfile(uri): return uri
    if not uri.startswith('/') and not uri.startswith('http'):
        result = finders.find(uri)
        if result: return result[0] if isinstance(result, (list, tuple)) else result
    sUrl, sRoot = settings.STATIC_URL, settings.STATIC_ROOT
    mUrl, mRoot = settings.MEDIA_URL, settings.MEDIA_ROOT
    if uri.startswith(mUrl): path = os.path.join(mRoot, uri.replace(mUrl, ""))
    elif uri.startswith(sUrl): path = os.path.join(sRoot, uri.replace(sUrl, ""))
    else: return uri
    return path if os.path.isfile(path) else None

def _lik_ctx(vertrag, verwaltung):
    from core.services.lik import vertrag_lik_context
    return vertrag_lik_context(vertrag, verwaltung)


def build_vertrag_context(vertrag, *, mit_unterschrift=True):
    """Baut den Template-Kontext für das Vertragsdokument. EINE Quelle für PDF
    UND Live-Vorschau — so können die beiden nie auseinanderlaufen. Gibt
    (template_name, context) zurück. Funktioniert auch für einen noch nicht
    gespeicherten Vertrag (Vorschau); dann `mit_unterschrift=False`."""
    einheit = vertrag.einheit
    liegenschaft = einheit.liegenschaft if einheit else None
    eigentuemer = liegenschaft.eigentuemer if liegenschaft else None

    verwaltung = liegenschaft.organisation if liegenschaft else None

    netto = vertrag.netto_mietzins or 0
    nk = vertrag.nebenkosten or 0
    brutto = netto + nk
    kaution = vertrag.kautions_betrag or 0

    unterschrift_path = None
    if mit_unterschrift:
        if verwaltung and getattr(verwaltung, 'unterschrift', None):
            unterschrift_path = verwaltung.unterschrift.path
        elif eigentuemer and getattr(eigentuemer, 'unterschrift_bild', None):
            unterschrift_path = eigentuemer.unterschrift_bild.path
        if not unterschrift_path:
            dummy = finders.find("img/unterschrift_dummy_transparent.png")
            if dummy:
                unterschrift_path = dummy
        if unterschrift_path:
            unterschrift_path = make_image_transparent(unterschrift_path)

    template_name = ('core/mietvertrag_garage.html'
                     if (einheit and einheit.typ in ['pp', 'bas', 'gar'])
                     else 'core/mietvertrag_pdf.html')

    context = {
        'vertrag': vertrag,
        'mieter': vertrag.mieter,
        'einheit': einheit,
        'liegenschaft': liegenschaft,
        'eigentuemer': eigentuemer,
        'verwaltung': verwaltung,
        'heute': timezone.localdate(),
        'miete_fmt': f"{netto:,.2f}".replace(",", "'"),
        'nk_fmt': f"{nk:,.2f}".replace(",", "'"),
        'brutto_fmt': f"{brutto:,.2f}".replace(",", "'"),
        'kaution_fmt': f"{kaution:,.2f}".replace(",", "'"),
        'ref_fmt': f"{(vertrag.basis_referenzzinssatz or 0):.2f}",
        'lik_fmt': f"{(vertrag.basis_lik_punkte or 0):.1f}",
        # Zeitplan + Klartext-Hinweise (Gratismonate) — auch für unsaved Vertrag.
        'mietzins_zeitplan': vertrag.mietzins_zeitplan(),
        'mietzins_hinweise': vertrag.mietzins_hinweise(),
        'unterschrift_path': unterschrift_path,
        # Einheitliche LIK-Angaben (Basis Dez. 2020 + Stand-Monat)
        **_lik_ctx(vertrag, verwaltung),
    }
    return template_name, context


def render_vertrag_html(vertrag, *, mit_unterschrift=True):
    """Rendert das Vertragsdokument als HTML (für die Live-Vorschau)."""
    template_name, context = build_vertrag_context(vertrag, mit_unterschrift=mit_unterschrift)
    return get_template(template_name).render(context)


def generate_vertrag_pdf_bytes(vertrag):
    template_name, context = build_vertrag_context(vertrag)
    html = get_template(template_name).render(context)
    result_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=result_buffer, link_callback=link_callback, encoding='utf-8')

    if pisa_status.err: raise Exception(f"Fehler bei der PDF Generierung: {pisa_status.err}")
    return result_buffer.getvalue()