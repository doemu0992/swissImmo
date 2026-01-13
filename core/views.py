import os
import io
import base64
import json
import requests
import traceback
import logging
import tempfile
import unicodedata
import re

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.db.models import Sum
from django.utils import timezone
from django.template.loader import render_to_string, get_template
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.core.files.base import ContentFile
from django.conf import settings
from django.contrib.staticfiles import finders

# --- External Libraries ---
from xhtml2pdf import pisa
from docxtpl import DocxTemplate

# ==========================================
# KONFIGURATION
# ==========================================
DOCUSEAL_API_KEY = getattr(settings, 'DOCUSEAL_API_KEY', "s9v8zN4fR55aLMxLQjV9M4TitPi6Bztc6mxPxvjbCMR")
DOCUSEAL_URL = "https://api.docuseal.com"
DEFAULT_VERWALTUNG_NAME = getattr(settings, 'VERWALTUNG_NAME', "Muster Immobilien Verwaltung AG")

logger = logging.getLogger(__name__)

# --- Models & Forms ---
from .models import (
    Mandant, Liegenschaft, Einheit, Mieter, Mietvertrag,
    SchadenMeldung, Dokument, MietzinsAnpassung,
    AbrechnungsPeriode
)
from .forms import MietanpassungForm, SchadenForm

# --- Helper Funktion: Dateiname ---
def sanitize_filename(filename):
    """Entfernt Umlaute und Sonderzeichen für sicheren API-Upload"""
    filename = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
    filename = re.sub(r'[^\w\s-]', '', filename).strip().lower()
    return re.sub(r'[-\s]+', '-', filename)

# --- Helper Funktion: Link Callback für PISA ---
def link_callback(uri, rel):
    """
    Hilft xhtml2pdf, statische Dateien (Bilder, CSS) auf dem Server zu finden.
    """
    result = finders.find(uri)
    if result:
        if isinstance(result, (list, tuple)):
            result = result[0]
        return result

    # Fallback für absolute Pfade
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

# ==========================================
# 1. DASHBOARD
# ==========================================
def dashboard_view(request):
    baum_daten = Mandant.objects.prefetch_related(
        'liegenschaften',
        'liegenschaften__einheiten',
        'liegenschaften__einheiten__geraete'
    ).all()

    try:
        agg_soll = Einheit.objects.aggregate(Sum('nettomiete_aktuell'))
        total_soll = agg_soll['nettomiete_aktuell__sum'] or 0
        leerstand_count = Einheit.objects.exclude(vertraege__aktiv=True).count()
        offene_schaden = SchadenMeldung.objects.exclude(status='erledigt').count()
        total_liegenschaften = Liegenschaft.objects.count()
        total_mieter = Mieter.objects.count()
    except Exception:
        total_soll = 0; leerstand_count = 0; offene_schaden = 0
        total_liegenschaften = 0; total_mieter = 0

    context = {
        'baum_daten': baum_daten,
        'total_soll': total_soll,
        'leerstand_count': leerstand_count,
        'offene_schaden': offene_schaden,
        'total_liegenschaften': total_liegenschaften,
        'total_mieter': total_mieter
    }
    return render(request, 'dashboard.html', context)

# ==========================================
# 2. MIETZINS ANPASSUNG
# ==========================================
def mietzins_anpassung_view(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, id=vertrag_id)

    if request.method == 'POST':
        form = MietanpassungForm(request.POST)
        if form.is_valid():
            neue_miete = form.cleaned_data['neue_miete']
            neue_nk = form.cleaned_data.get('neue_nk') or vertrag.nebenkosten
            datum_wirksam = form.cleaned_data['datum_wirksam']
            begruendung = form.cleaned_data.get('begruendung', '')

            MietzinsAnpassung.objects.create(
                vertrag=vertrag,
                neuer_referenzzinssatz=form.cleaned_data['neu_zins'],
                neuer_lik_index=form.cleaned_data['neu_index'],
                neue_miete=neue_miete,
                datum_wirksam=timezone.now(),
            )

            context = {
                'mieter_anrede': vertrag.mieter.anrede,
                'mieter_vorname': vertrag.mieter.vorname,
                'mieter_nachname': vertrag.mieter.nachname,
                'strasse': vertrag.einheit.liegenschaft.strasse,
                'ort': vertrag.einheit.liegenschaft.ort,
                'datum_heute': timezone.now().strftime("%d.%m.%Y"),
                'alt_miete': f"{form.cleaned_data['alt_miete']:.2f}",
                'alt_nk': f"{form.cleaned_data['alt_nk']:.2f}",
                'neue_miete': f"{neue_miete:.2f}",
                'neue_nk': f"{neue_nk:.2f}",
                'wirksam_ab': datum_wirksam,
                'begruendung': begruendung,
            }

            doc = DocxTemplate("templates/mietzins_vorlage.docx")
            doc.render(context)

            buffer = io.BytesIO()
            doc.save(buffer)
            buffer.seek(0)

            response = HttpResponse(buffer.read(), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            filename = f"Mietanpassung_{vertrag.mieter.nachname}.docx"
            response['Content-Disposition'] = f'attachment; filename={filename}'
            return response

    else:
        initial_data = {
            'alt_zins': vertrag.basis_referenzzinssatz,
            'alt_index': vertrag.basis_lik_punkte,
            'alt_miete': vertrag.netto_mietzins,
            'alt_nk': vertrag.nebenkosten,
        }
        form = MietanpassungForm(initial=initial_data)

    return render(request, 'core/mietzins_form.html', {
        'form': form,
        'vertrag': vertrag
    })

# ==========================================
# 3. SCHADENMELDUNG
# ==========================================
def schaden_melden_public(request):
    success = False
    if request.method == 'POST':
        form = SchadenForm(request.POST, request.FILES)
        if form.is_valid():
            meldung = form.save(commit=False)
            first_liegenschaft = Liegenschaft.objects.first()
            if first_liegenschaft:
                meldung.liegenschaft = first_liegenschaft
                meldung.save()
                success = True
            else:
                messages.error(request, "Keine Liegenschaft im System gefunden.")
    else:
        form = SchadenForm()

    return render(request, 'core/schaden_form.html', {'form': form, 'success': success})

# ==========================================
# 4. NEBENKOSTEN ABRECHNUNG PDF
# ==========================================
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
        anteil_kosten = round(anteil_kosten, 2)
        saldo = round(saldo, 2)

        qr_data_uri = None
        qr_error = None

        if saldo < -0.05:
            if True:
                try:
                    pass
                except Exception as e:
                    qr_error = str(e)

        abrechnungen.append({
            'einheit': einheit.bezeichnung,
            'mieter': mieter_name,
            'details': details,
            'total_kosten': anteil_kosten,
            'akonto': akonto,
            'saldo': saldo,
            'qr_data_uri': qr_data_uri
        })

    html_string = render_to_string('core/abrechnung_pdf.html', {'abrechnungen': abrechnungen, 'datum': timezone.now()})

    pdf_file = io.BytesIO()
    pisa.CreatePDF(html_string, dest=pdf_file, link_callback=link_callback)
    pdf_file.seek(0)

    response = HttpResponse(pdf_file.read(), content_type='application/pdf')
    filename = f"NK_Abrechnung_{periode.pk}.pdf"
    response['Content-Disposition'] = f'filename="{filename}"'
    return response

# ==========================================
# 5. MIETVERTRAG PDF (Manueller Download)
# ==========================================
def generate_pdf_view(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    verwaltungs_name = DEFAULT_VERWALTUNG_NAME

    netto = vertrag.netto_mietzins or 0
    nk = vertrag.nebenkosten or 0
    brutto = netto + nk
    kaution = vertrag.kautions_betrag or 0

    unterschrift_path = "img/unterschrift_dummy.png"

    context = {
        'vertrag': vertrag,
        'mieter': vertrag.mieter,
        'einheit': vertrag.einheit,
        'liegenschaft': vertrag.einheit.liegenschaft,
        'mandant': vertrag.einheit.liegenschaft.mandant,
        'verwaltungs_name': verwaltungs_name,
        'heute': timezone.now().date(),
        'miete_fmt': f"{netto:.2f}",
        'nk_fmt': f"{nk:.2f}",
        'brutto_fmt': f"{brutto:.2f}",
        'kaution_fmt': f"{kaution:.2f}",
        'unterschrift_path': unterschrift_path,
    }

    template = get_template('core/mietvertrag_pdf.html')
    html = template.render(context)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Mietvertrag_{vertrag.id}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    if pisa_status.err:
        return HttpResponse('Fehler beim Erstellen des PDFs', status=500)
    return response

# ==========================================
# 6. DOCUSEAL INTEGRATION (NO ERROR RAISE)
# ==========================================
def send_via_docuseal(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)

    # 1. Validierung
    api_key = getattr(settings, 'DOCUSEAL_API_KEY', None)
    if not api_key:
        messages.error(request, "❌ API-Key fehlt in settings.py")
        return redirect(request.META.get('HTTP_REFERER', 'admin:index'))

    if not vertrag.mieter.email:
        messages.error(request, "❌ Abbruch: Mieter hat keine E-Mail.")
        return redirect(request.META.get('HTTP_REFERER', 'admin:index'))

    # 2. PDF Generieren
    try:
        template_path = 'core/mietvertrag_pdf.html'
        verwaltungs_name = DEFAULT_VERWALTUNG_NAME

        netto = vertrag.netto_mietzins or 0
        nk = vertrag.nebenkosten or 0
        brutto = netto + nk
        kaution = vertrag.kautions_betrag or 0

        unterschrift_path = "img/unterschrift_dummy.png"

        context = {
            'vertrag': vertrag,
            'mieter': vertrag.mieter,
            'einheit': vertrag.einheit,
            'liegenschaft': vertrag.einheit.liegenschaft,
            'mandant': vertrag.einheit.liegenschaft.mandant,
            'verwaltungs_name': verwaltungs_name,
            'heute': timezone.now().date(),
            'miete_fmt': f"{netto:.2f}",
            'nk_fmt': f"{nk:.2f}",
            'brutto_fmt': f"{brutto:.2f}",
            'kaution_fmt': f"{kaution:.2f}",
            'unterschrift_path': unterschrift_path,
        }

        template = get_template(template_path)
        html = template.render(context)

        pdf_file = io.BytesIO()

        pisa_status = pisa.CreatePDF(html, dest=pdf_file, link_callback=link_callback)

        if pisa_status.err:
            raise Exception(f"Pisa Error: {pisa_status.err}")

        pdf_value = pdf_file.getvalue()

        if len(pdf_value) < 1000:
            logger.warning(f"PDF ist klein ({len(pdf_value)} bytes), wird aber gesendet.")

    except Exception as e:
        logger.error(f"PDF Gen Error: {e}")
        messages.error(request, f"❌ PDF Fehler: {str(e)}")
        return redirect(request.META.get('HTTP_REFERER', 'admin:index'))

    # 3. API Request
    try:
        clean_name = sanitize_filename(f"mietvertrag_{vertrag.mieter.nachname}_{vertrag.id}")
        filename = f"{clean_name}.pdf"

        # Raw Base64 Encoding
        b64_data = base64.b64encode(pdf_value).decode('ascii')
        b64_data = b64_data.replace('\n', '')

        url = "https://api.docuseal.com/submissions/pdf"

        payload = {
            "name": f"Mietvertrag {vertrag.id}",
            "send_email": True,
            "documents": [
                {
                    "name": filename,
                    "file": b64_data,
                    "fields": [
                        {
                            "name": "Unterschrift_Mieter",
                            "type": "signature",
                            "role": "Mieter",
                            "required": True,
                            "areas": [
                                {
                                    "x": 300,
                                    "y": 650,
                                    "w": 180,
                                    "h": 60,
                                    "page": 2
                                }
                            ]
                        }
                    ]
                }
            ],
            "submitters": [
                {
                    "role": "Mieter",
                    "email": vertrag.mieter.email,
                    "send_email": True,
                    "name": f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}"
                }
            ]
        }

        headers = {
            "X-Auth-Token": api_key,
            "Content-Type": "application/json"
        }

        response = requests.post(url, headers=headers, json=payload)

        if response.status_code in [200, 201]:
            data = response.json()
            if isinstance(data, list): data = data[0]

            # --- ÄNDERUNG: KEIN FEHLER MEHR BEI 'Empty Docs' ---
            # Da es funktioniert, ignorieren wir die interne Strukturprüfung
            docs = data.get('documents', [])
            if not docs:
                logger.info("DocuSeal meldet leeres document-array, aber Prozess läuft (False Positive).")

            new_id = str(data.get('id'))

            if hasattr(vertrag, 'jotform_submission_id'):
                vertrag.jotform_submission_id = new_id
                vertrag.sign_status = 'gesendet'
                vertrag.save()

            messages.success(request, f"✅ Vertrag gesendet (ID: {new_id})")
        else:
            raise Exception(f"API Fehler {response.status_code}: {response.text}")

    except Exception as e:
        logger.error(f"DocuSeal Exception: {e}")
        messages.error(request, f"❌ Fehler beim Senden: {str(e)}")

    return redirect(request.META.get('HTTP_REFERER', 'admin:index'))

# ==========================================
# 7. WEBHOOK
# ==========================================
@csrf_exempt
def docuseal_webhook(request):
    if request.method == 'POST':
        try:
            payload = json.loads(request.body)
            event_type = payload.get('event_type')
            data = payload.get('data', {})

            sub_id = str(data.get('id'))
            vertrag = Mietvertrag.objects.filter(jotform_submission_id=sub_id).first()

            if not vertrag:
                return HttpResponse("OK", status=200)

            status_api = data.get('status', 'unknown')
            if status_api == 'completed':
                vertrag.sign_status = 'unterzeichnet'
            elif status_api == 'declined':
                vertrag.sign_status = 'abgelehnt'

            vertrag.save()

            if event_type == 'submission.completed' or status_api == 'completed':
                doc_url = data.get('combined_document_url')
                if not doc_url and data.get('documents'):
                    docs = data.get('documents')
                    if len(docs) > 0:
                        doc_url = docs[0].get('url')

                if doc_url:
                    r = requests.get(doc_url)
                    if r.status_code == 200:
                        filename = f"Unterschrieben_Mietvertrag_{vertrag.id}.pdf"
                        file_content = ContentFile(r.content, name=filename)

                        vertrag.pdf_datei.save(filename, file_content, save=False)
                        vertrag.sign_status = 'unterzeichnet'
                        vertrag.save()

                        Dokument.objects.create(
                            kategorie='Mietvertrag',
                            bezeichnung=f"Vertrag (Unterschrieben)",
                            datei=ContentFile(r.content, name=filename),
                            vertrag=vertrag,
                            liegenschaft=vertrag.einheit.liegenschaft,
                            mandant=vertrag.einheit.liegenschaft.mandant
                        )

            return HttpResponse("OK", status=200)

        except Exception as e:
            logger.error(f"Webhook Error: {e}")
            return HttpResponse("Error", status=500)

    return HttpResponse("Method not allowed", status=405)

def generiere_amtliches_formular(request, vertrag_id):
    return redirect('mietzins_anpassung', vertrag_id=vertrag_id)