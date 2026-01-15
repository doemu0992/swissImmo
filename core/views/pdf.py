import os
import io
import tempfile
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.template.loader import render_to_string, get_template
from django.db.models import Sum
from django.utils import timezone
from django.conf import settings
from django.contrib.staticfiles import finders
from xhtml2pdf import pisa

from core.models import AbrechnungsPeriode, Mietvertrag

try:
    from swiss_qr_bill import QRBill, Bill, Address
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

def link_callback(uri, rel):
    """
    Wandelt Pfade für xhtml2pdf um.
    Behebt 'SuspiciousFileOperation' indem absolute Systempfade direkt akzeptiert werden.
    """
    # 1. Ist es bereits ein absoluter Pfad auf der Festplatte? (z.B. Media-Uploads)
    if os.path.isfile(uri):
        return uri

    # 2. Ist es ein relativer Pfad? Dann Static Finder nutzen.
    if not uri.startswith('/') and not uri.startswith('http'):
        result = finders.find(uri)
        if result:
            if isinstance(result, (list, tuple)):
                result = result[0]
            return result

    # 3. Standard URL-Umwandlung (Static & Media)
    sUrl = settings.STATIC_URL
    sRoot = settings.STATIC_ROOT
    mUrl = settings.MEDIA_URL
    mRoot = settings.MEDIA_ROOT

    if uri.startswith(mUrl):
        path = os.path.join(mRoot, uri.replace(mUrl, ""))
    elif uri.startswith(sUrl):
        path = os.path.join(sRoot, uri.replace(sUrl, ""))
    else:
        return uri

    if not os.path.isfile(path):
        return None

    return path


# --- NEBENKOSTEN ABRECHNUNG ---
def abrechnung_pdf_view(request, pk):
    periode = get_object_or_404(AbrechnungsPeriode, pk=pk)
    liegenschaft = periode.liegenschaft
    einheiten = liegenschaft.einheiten.all()
    belege = periode.belege.all()
    gesamt_flaeche = einheiten.aggregate(Sum('flaeche_m2'))['flaeche_m2__sum'] or 1
    temp_dir = tempfile.gettempdir()
    abrechnungen = []

    for einheit in einheiten:
        mietvertrag = einheit.vertraege.filter(aktiv=True).first()
        mieter_name = str(mietvertrag.mieter) if mietvertrag else "Leerstand / Eigentümer"
        anteil_kosten = 0.0
        details = []
        for beleg in belege:
            if beleg.verteilschluessel == 'm2':
                anteil_faktor = float(einheit.flaeche_m2) / float(gesamt_flaeche)
                kosten = float(beleg.betrag) * anteil_faktor
                anteil_kosten += kosten
                details.append({
                    'kategorie': beleg.get_kategorie_display(),
                    'text': beleg.text,
                    'total': beleg.betrag,
                    'anteil': kosten
                })
        akonto = float(einheit.nebenkosten_aktuell) * 12
        saldo = akonto - anteil_kosten
        qr_data_uri = None

        if saldo < -0.05 and QR_AVAILABLE and liegenschaft.iban:
            try:
                creditor = Address(name="Verwaltung", line1=liegenschaft.strasse, line2=f"{liegenschaft.plz} {liegenschaft.ort}", country='CH')
                debtor = Address(name=mieter_name, line1=einheit.liegenschaft.strasse, line2=f"{einheit.liegenschaft.plz} {einheit.liegenschaft.ort}", country='CH')
                bill = Bill(account=liegenschaft.iban.replace(" ", ""), creditor=creditor, debtor=debtor, amount=abs(saldo), currency='CHF')
                canvas = QRBill.generate(bill)
                filename = f"qr_temp_{periode.id}_{einheit.id}.svg"
                full_path = os.path.join(temp_dir, filename)
                with open(full_path, 'wb') as f:
                    f.write(canvas.get_content().encode('utf-8') if isinstance(canvas.get_content(), str) else canvas.get_content())
                qr_data_uri = f"file://{full_path}"
            except Exception: pass

        abrechnungen.append({
            'einheit': einheit.bezeichnung,
            'mieter': mieter_name,
            'details': details,
            'total_kosten': round(anteil_kosten, 2),
            'akonto': akonto,
            'saldo': round(saldo, 2),
            'qr_data_uri': qr_data_uri
        })

    html_string = render_to_string('core/abrechnung_pdf.html', {'abrechnungen': abrechnungen, 'datum': timezone.now()})
    pdf_file = io.BytesIO()
    pisa.CreatePDF(html_string, dest=pdf_file, link_callback=link_callback)
    pdf_file.seek(0)
    response = HttpResponse(pdf_file.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'filename="NK_Abrechnung_{periode.pk}.pdf"'
    return response


# --- MIETVERTRAG GENERIEREN ---
def generate_pdf_view(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)

    # Objekte laden
    einheit = vertrag.einheit
    liegenschaft = einheit.liegenschaft
    mandant = liegenschaft.mandant  # Der Eigentümer

    # Formatierung
    netto = vertrag.netto_mietzins or 0
    nk = vertrag.nebenkosten or 0
    brutto = netto + nk
    kaution = vertrag.kautions_betrag or 0

    # Unterschrift Bild holen
    unterschrift_path = None
    if mandant and mandant.unterschrift_bild:
        try:
             unterschrift_path = mandant.unterschrift_bild.path
        except: pass

    if not unterschrift_path:
        dummy = finders.find("img/unterschrift_dummy.png")
        if dummy:
            unterschrift_path = dummy

    # TEMPLATE AUSWAHL
    if einheit.typ in ['pp', 'bas', 'gar']:
        template_name = 'core/mietvertrag_garage.html'
    else:
        template_name = 'core/mietvertrag_pdf.html'

    context = {
        'vertrag': vertrag,
        'mieter': vertrag.mieter,
        'einheit': einheit,
        'liegenschaft': liegenschaft,
        'mandant': mandant,        # WICHTIG: Das Mandant-Objekt für den Vermieter-Namen
        'heute': timezone.now().date(),
        'miete_fmt': f"{netto:.2f}",
        'nk_fmt': f"{nk:.2f}",
        'brutto_fmt': f"{brutto:.2f}",
        'kaution_fmt': f"{kaution:.2f}",
        'unterschrift_path': unterschrift_path,
    }

    template = get_template(template_name)
    html = template.render(context)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Mietvertrag_{vertrag.id}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback)

    if pisa_status.err:
        return HttpResponse(f'Fehler beim Erstellen des PDFs: {pisa_status.err}', status=500)

    return response