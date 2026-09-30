import logging
# core/views/pdf.py
from core.auth import rolle_erforderlich, ROLLE_VERWALTER, ROLLE_SACHBEARBEITER, ROLLE_LESEZUGRIFF
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils.text import slugify
from rentals.models import Mietvertrag
from core.services.pdf_service import PdfFehler, generate_vertrag_pdf_bytes
from core.services.dokument_service import generate_dokument_pdf_bytes, DOKUMENT_TYPEN

logger = logging.getLogger(__name__)


@rolle_erforderlich(ROLLE_VERWALTER, ROLLE_SACHBEARBEITER, ROLLE_LESEZUGRIFF)
def generate_pdf_view(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    try:
        pdf_bytes = generate_vertrag_pdf_bytes(vertrag)
        _ablegen_vertragsdokument(pdf_bytes, "Mietvertrag", vertrag, ueberschreiben=False)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        filename = f"Mietvertrag_{vertrag.einheit.bezeichnung}_{vertrag.mieter.nachname}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except PdfFehler:
        logger.error("PDF-Erzeugung fehlgeschlagen (Vertrag %s)", vertrag_id, exc_info=True)
        return _pdf_nicht_verfuegbar()
    except Exception:
        logger.error("PDF-Erzeugung mit unerwartetem Fehler (Vertrag %s)", vertrag_id, exc_info=True)
        return HttpResponse('Fehler beim Erstellen des PDFs.', status=500, content_type='text/plain; charset=utf-8')


def _pdf_nicht_verfuegbar():
    """503 statt 500: Der Fehler liegt an der Erzeugung, nicht an der Anfrage —
    ein erneuter Versuch nach kurzer Zeit kann gelingen. Nichts wurde abgelegt."""
    antwort = HttpResponse('Das PDF konnte gerade nicht erstellt werden. Es wurde nichts abgelegt — '
                           'bitte in einigen Minuten erneut versuchen.',
                           status=503, content_type='text/plain; charset=utf-8')
    antwort['Retry-After'] = '120'
    return antwort


def _ablegen_vertragsdokument(pdf_bytes, titel, vertrag, *, ueberschreiben=True):
    """Legt ein beim Vertrag generiertes Standard-Dokument in die Akte
    (→ Mieterportal). **Ein Beleg je (Vertrag, Titel)** — kein Duplikat bei
    erneutem Erzeugen.

    JE VERTRAG, NICHT JE OBJEKT (korrigiert am 28.09.2026)
    Bis dahin wurde das vorhandene Dokument über (Objekt, Titel) gesucht und
    dann auf den neuen Vertrag umgehängt. Erzeugte man den Mietvertrag des
    NACHMIETERS, überschrieb das den Mietvertrag des VORMIETERS und hängte
    ihn dem neuen Mieter an: Der Vormieter hatte danach kein einziges
    Vertragsdokument mehr in der Akte. `ablegen(dedup=True)` sucht je Vertrag
    — dorthin wird jetzt weitergereicht.

    ANSEHEN VERÄNDERT DIE AKTE NICHT (`ueberschreiben=False`)
    Die Download-Views erzeugen das PDF aus den AKTUELLEN Vertragsdaten. Hätten
    sie das abgelegte Dokument überschrieben, wäre nach jeder Änderung am
    Vertrag die tatsächlich verschickte Fassung weg — ausgelöst schon durch
    blosses Ansehen, auch mit Lesezugriff. Sie legen darum nur an, was fehlt.
    Überschrieben wird nur beim ausdrücklichen Erstellen des Vertrags
    (`fw/vertragserstellung.py`)."""
    try:
        from rentals.models import Dokument
        from core.services.ablage import ablegen
        if not ueberschreiben and Dokument.alle_organisationen.filter(
                vertrag=vertrag, bezeichnung=(titel or 'Dokument')[:200]).exists():
            return
        ablegen(pdf_bytes, titel, kategorie='vertrag', vertrag=vertrag, dedup=True)
    except Exception:
        logger.debug("Fehler bewusst übergangen", exc_info=True)


# Dokumentpaket, das bei Vertragserstellung erzeugt wird (ohne situative
# Dokumente wie Begleitbrief-signiert / Kündigungsbestätigung).
VERTRAGSPAKET = ['allgemeine-bedingungen', 'hausordnung', 'merkblatt-lueften',
                 'wohnungsausweis', 'begleitbrief']

# Titel der automatisch generierten Vertragspaket-Dokumente (kategorie='vertrag').
# Diese gehören zum Vertrag und werden mit ihm gelöscht (keine verwaisten Kopien).
VERTRAGSPAKET_TITEL = ['Mietvertrag', 'Allgemeine Bedingungen', 'Hausordnung',
                       'Merkblatt Lüften', 'Wohnungsausweis', 'Begleitbrief Mietvertrag']


class Vertragspaket(list):
    """Liste (dateiname, pdf_bytes) der erzeugten Dokumente. `fehler` nennt,
    was NICHT erzeugt werden konnte — vorher fehlte es im Ergebnis, ohne dass
    jemand erfuhr, dass es fehlte."""

    def __init__(self):
        super().__init__()
        self.fehler = []


def erzeuge_und_ablege_vertragspaket(vertrag, *, ueberschreiben=True):
    """Erzeugt Mietvertrag + Standard-Beilagen, legt jedes einzeln in die Akte
    (→ Mieterportal). Gibt eine Liste (dateiname, pdf_bytes) zurück; `.fehler`
    nennt die Dokumente, die scheiterten. Ein gescheitertes Dokument bricht die
    übrigen nicht ab.
    `ueberschreiben=False` für reine Downloads — siehe `_ablegen_vertragsdokument`."""
    dateien = Vertragspaket()
    try:
        pdf = generate_vertrag_pdf_bytes(vertrag)
        _ablegen_vertragsdokument(pdf, "Mietvertrag", vertrag, ueberschreiben=ueberschreiben)
        dateien.append((f"01_Mietvertrag_{slugify(vertrag.mieter.nachname)}.pdf", pdf))
    except Exception:
        logger.error("Mietvertrag-PDF fehlgeschlagen (Vertrag %s)", vertrag.pk, exc_info=True)
        dateien.fehler.append("Mietvertrag")
    for i, doc_type in enumerate(VERTRAGSPAKET, start=2):
        if doc_type not in DOKUMENT_TYPEN:
            continue
        try:
            pdf = generate_dokument_pdf_bytes(vertrag, doc_type)
            _tpl, titel, _extra = DOKUMENT_TYPEN[doc_type]
            _ablegen_vertragsdokument(pdf, titel, vertrag, ueberschreiben=ueberschreiben)
            dateien.append((f"{i:02d}_{slugify(titel)}.pdf", pdf))
        except Exception:
            logger.error("Beilage %s fehlgeschlagen (Vertrag %s)", doc_type, vertrag.pk, exc_info=True)
            dateien.fehler.append(doc_type)
    return dateien


@rolle_erforderlich(ROLLE_VERWALTER, ROLLE_SACHBEARBEITER, ROLLE_LESEZUGRIFF)
def generate_vertragspaket_zip(request, vertrag_id):
    """Erzeugt Mietvertrag + Beilagen, legt sie einzeln in die Akte und liefert
    alles zusammen als ZIP zum Download."""
    import io
    import zipfile
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    dateien = erzeuge_und_ablege_vertragspaket(vertrag, ueberschreiben=False)
    if not dateien:
        return _pdf_nicht_verfuegbar()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, pdf in dateien:
            zf.writestr(name, pdf)
    buf.seek(0)
    resp = HttpResponse(buf.getvalue(), content_type='application/zip')
    resp['Content-Disposition'] = f'attachment; filename="Vertragsdokumente_{slugify(vertrag.mieter.nachname)}.zip"'
    if dateien.fehler:
        # Teilpaket: nicht als vollständig ausgeben. Der Header ist für Skripte,
        # die Liste im Log für den Betrieb.
        resp['X-Fehlende-Dokumente'] = ','.join(dateien.fehler)
    return resp


@rolle_erforderlich(ROLLE_VERWALTER, ROLLE_SACHBEARBEITER, ROLLE_LESEZUGRIFF)
def generate_dokument_view(request, vertrag_id, doc_type):
    """Erstellt eines der Fairwalter-Begleitdokumente (Allgemeine Bedingungen,
    Hausordnung, Merkblatt, Wohnungsausweis, Begleitbriefe) als PDF."""
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    if doc_type not in DOKUMENT_TYPEN:
        return HttpResponse('Unbekannter Dokumenttyp.', status=404)
    try:
        pdf_bytes = generate_dokument_pdf_bytes(vertrag, doc_type)
        _tpl, titel, _extra = DOKUMENT_TYPEN[doc_type]
        _ablegen_vertragsdokument(pdf_bytes, titel, vertrag, ueberschreiben=False)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        filename = f"{slugify(titel)}_{vertrag.mieter.nachname}.pdf"
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response
    except PdfFehler:
        logger.error("PDF-Erzeugung fehlgeschlagen (Vertrag %s, %s)", vertrag_id, doc_type, exc_info=True)
        return _pdf_nicht_verfuegbar()
    except Exception:
        logger.error("PDF-Erzeugung mit unerwartetem Fehler (Vertrag %s, %s)", vertrag_id, doc_type, exc_info=True)
        return HttpResponse('Fehler beim Erstellen des PDFs.', status=500, content_type='text/plain; charset=utf-8')