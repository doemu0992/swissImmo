# core/services/pdf_service.py
import os
import io
from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.utils import timezone
from xhtml2pdf import pisa
from crm.models import Verwaltung

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

def generate_vertrag_pdf_bytes(vertrag):
    einheit = vertrag.einheit
    liegenschaft = einheit.liegenschaft
    mandant = liegenschaft.mandant

    verwaltung = liegenschaft.verwaltung
    if not verwaltung:
        verwaltung = Verwaltung.objects.first()

    netto = vertrag.netto_mietzins or 0
    nk = vertrag.nebenkosten or 0
    brutto = netto + nk
    kaution = vertrag.kautions_betrag or 0

    unterschrift_path = None
    if verwaltung and hasattr(verwaltung, 'unterschrift') and verwaltung.unterschrift:
        unterschrift_path = verwaltung.unterschrift.path
    elif mandant and hasattr(mandant, 'unterschrift_bild') and mandant.unterschrift_bild:
        unterschrift_path = mandant.unterschrift_bild.path

    if not unterschrift_path:
        dummy = finders.find("img/unterschrift_dummy.png")
        if dummy: unterschrift_path = dummy

    # 🔥 HIER WENDEN WIR DEN ZAUBERFILTER AN:
    if unterschrift_path:
        unterschrift_path = make_image_transparent(unterschrift_path)

    template_name = 'core/mietvertrag_garage.html' if einheit.typ in ['pp', 'bas', 'gar'] else 'core/mietvertrag_pdf.html'

    context = {
        'vertrag': vertrag,
        'mieter': vertrag.mieter,
        'einheit': einheit,
        'liegenschaft': liegenschaft,
        'mandant': mandant,
        'verwaltung': verwaltung,
        'heute': timezone.now().date(),
        'miete_fmt': f"{netto:,.2f}".replace(",", "'"),
        'nk_fmt': f"{nk:,.2f}".replace(",", "'"),
        'brutto_fmt': f"{brutto:,.2f}".replace(",", "'"),
        'kaution_fmt': f"{kaution:,.2f}".replace(",", "'"),
        'unterschrift_path': unterschrift_path,
    }

    html = get_template(template_name).render(context)
    result_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=result_buffer, link_callback=link_callback, encoding='utf-8')

    if pisa_status.err: raise Exception(f"Fehler bei der PDF Generierung: {pisa_status.err}")
    return result_buffer.getvalue()