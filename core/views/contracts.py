import io
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.utils import timezone
from docxtpl import DocxTemplate

from core.models import Mietvertrag, MietzinsAnpassung
from core.forms import MietanpassungForm

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

    return render(request, 'core/mietzins_form.html', {'form': form, 'vertrag': vertrag})

def generiere_amtliches_formular(request, vertrag_id):
    return redirect('mietzins_anpassung', vertrag_id=vertrag_id)