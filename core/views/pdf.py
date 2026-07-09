# core/views/pdf.py
from core.auth import rolle_erforderlich, ROLLE_VERWALTUNG, ROLLE_SACHBEARBEITUNG, ROLLE_LESEND
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils.text import slugify
from rentals.models import Mietvertrag
from core.services.pdf_service import generate_vertrag_pdf_bytes
from core.services.dokument_service import generate_dokument_pdf_bytes, DOKUMENT_TYPEN

@rolle_erforderlich(ROLLE_VERWALTUNG, ROLLE_SACHBEARBEITUNG, ROLLE_LESEND)
def generate_pdf_view(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    try:
        pdf_bytes = generate_vertrag_pdf_bytes(vertrag)
        _ablegen_vertragsdokument(pdf_bytes, "Mietvertrag", vertrag)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        filename = f"Mietvertrag_{vertrag.einheit.bezeichnung}_{vertrag.mieter.nachname}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        return HttpResponse(f'Fehler beim Erstellen des PDFs: {str(e)}', status=500)


def _ablegen_vertragsdokument(pdf_bytes, titel, vertrag):
    """Legt ein beim Vertrag generiertes PDF automatisch in die Akte
    (mit Dedup) — erscheint dann auch im Mieterportal."""
    try:
        from core.services.ablage import ablegen
        ablegen(pdf_bytes, titel, kategorie='vertrag', vertrag=vertrag, dedup=True)
    except Exception:
        pass


# Dokumentpaket, das bei Vertragserstellung erzeugt wird (ohne situative
# Dokumente wie Begleitbrief-signiert / Kündigungsbestätigung).
VERTRAGSPAKET = ['allgemeine-bedingungen', 'hausordnung', 'merkblatt-lueften',
                 'wohnungsausweis', 'begleitbrief']


def erzeuge_und_ablege_vertragspaket(vertrag):
    """Erzeugt Mietvertrag + Standard-Beilagen, legt jedes einzeln in die Akte
    (→ Mieterportal). Gibt eine Liste (dateiname, pdf_bytes) zurück."""
    dateien = []
    try:
        pdf = generate_vertrag_pdf_bytes(vertrag)
        _ablegen_vertragsdokument(pdf, "Mietvertrag", vertrag)
        dateien.append((f"01_Mietvertrag_{slugify(vertrag.mieter.nachname)}.pdf", pdf))
    except Exception:
        pass
    for i, doc_type in enumerate(VERTRAGSPAKET, start=2):
        if doc_type not in DOKUMENT_TYPEN:
            continue
        try:
            pdf = generate_dokument_pdf_bytes(vertrag, doc_type)
            _tpl, titel, _extra = DOKUMENT_TYPEN[doc_type]
            _ablegen_vertragsdokument(pdf, titel, vertrag)
            dateien.append((f"{i:02d}_{slugify(titel)}.pdf", pdf))
        except Exception:
            continue
    return dateien


@rolle_erforderlich(ROLLE_VERWALTUNG, ROLLE_SACHBEARBEITUNG, ROLLE_LESEND)
def generate_vertragspaket_zip(request, vertrag_id):
    """Erzeugt Mietvertrag + Beilagen, legt sie einzeln in die Akte und liefert
    alles zusammen als ZIP zum Download."""
    import io
    import zipfile
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    dateien = erzeuge_und_ablege_vertragspaket(vertrag)
    if not dateien:
        return HttpResponse("Keine Dokumente erzeugt.", status=500)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, pdf in dateien:
            zf.writestr(name, pdf)
    buf.seek(0)
    resp = HttpResponse(buf.getvalue(), content_type='application/zip')
    resp['Content-Disposition'] = f'attachment; filename="Vertragsdokumente_{slugify(vertrag.mieter.nachname)}.zip"'
    return resp


@rolle_erforderlich(ROLLE_VERWALTUNG, ROLLE_SACHBEARBEITUNG, ROLLE_LESEND)
def generate_dokument_view(request, vertrag_id, doc_type):
    """Erstellt eines der Fairwalter-Begleitdokumente (Allgemeine Bedingungen,
    Hausordnung, Merkblatt, Wohnungsausweis, Begleitbriefe) als PDF."""
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    if doc_type not in DOKUMENT_TYPEN:
        return HttpResponse('Unbekannter Dokumenttyp.', status=404)
    try:
        pdf_bytes = generate_dokument_pdf_bytes(vertrag, doc_type)
        _tpl, titel, _extra = DOKUMENT_TYPEN[doc_type]
        _ablegen_vertragsdokument(pdf_bytes, titel, vertrag)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        filename = f"{slugify(titel)}_{vertrag.mieter.nachname}.pdf"
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response
    except Exception as e:
        return HttpResponse(f'Fehler beim Erstellen des PDFs: {str(e)}', status=500)