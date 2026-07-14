"""Auto-Ablage: legt generierte PDFs automatisch in die Dokument-Akte
(core_dokument / rentals.Dokument) ab und verknüpft sie mit Vertrag,
Mieter, Einheit und Liegenschaft."""
from django.core.files.base import ContentFile


def ablegen(pdf_bytes, titel, kategorie='korrespondenz', *,
            vertrag=None, mieter=None, einheit=None, liegenschaft=None,
            dateiname=None, dedup=False):
    """Speichert ``pdf_bytes`` als Dokument in der Akte.

    Fehlende Bezüge werden - soweit möglich - aus dem Vertrag abgeleitet.
    Mit ``dedup=True`` wird ein bereits vorhandenes Dokument gleicher
    Bezeichnung (am selben Vertrag) überschrieben statt dupliziert.
    Gibt das (erstellte oder aktualisierte) Dokument zurück (oder ``None``)."""
    from rentals.models import Dokument
    if vertrag is not None:
        mieter = mieter or getattr(vertrag, 'mieter', None)
        einheit = einheit or getattr(vertrag, 'einheit', None)
    if einheit is not None and liegenschaft is None:
        liegenschaft = getattr(einheit, 'liegenschaft', None)

    if dedup and vertrag is not None:
        vorhanden = Dokument.objects.filter(vertrag=vertrag, bezeichnung=(titel or 'Dokument')[:200]).first()
        if vorhanden is not None:
            try:
                if not (dateiname or '').lower().endswith('.pdf'):
                    dateiname = f"{_slug(dateiname or titel or 'dokument')}.pdf"
                vorhanden.datei.save(dateiname, ContentFile(pdf_bytes), save=True)
                return vorhanden
            except Exception:
                return None

    if not (dateiname or '').lower().endswith('.pdf'):
        basis = (dateiname or titel or 'dokument').strip() or 'dokument'
        dateiname = f"{_slug(basis)}.pdf"

    try:
        dok = Dokument(
            bezeichnung=(titel or 'Dokument')[:200],
            titel=(titel or 'Dokument')[:200],
            kategorie=kategorie,
            vertrag=vertrag, mieter=mieter, einheit=einheit, liegenschaft=liegenschaft,
        )
        dok.datei.save(dateiname, ContentFile(pdf_bytes), save=True)
        return dok
    except Exception:
        return None


def ablage_signierter_vertrag(vertrag, pdf_bytes=None):
    """Legt den UNTERZEICHNETEN Mietvertrag zentral als rentals.Dokument ab —
    dadurch erscheint er überall dort, wo Verträge/Dokumente gezeigt werden:
    Mieterportal (im_portal_sichtbar), Person-Akte, Objekt-/Liegenschafts-Akte.
    Einmal ablegen statt drei Ablagestellen pflegen. Dedup verhindert Doppel.
    Gibt das Dokument zurück (oder None)."""
    if pdf_bytes is None:
        datei = getattr(vertrag, 'pdf_datei', None)
        if not datei:
            return None
        try:
            datei.open('rb')
            pdf_bytes = datei.read()
        except Exception:
            return None
        finally:
            try:
                datei.close()
            except Exception:
                pass
    if not pdf_bytes:
        return None
    return ablegen(pdf_bytes, "Mietvertrag (unterzeichnet)", kategorie='vertrag',
                   vertrag=vertrag,
                   dateiname=f"Mietvertrag_unterzeichnet_{getattr(vertrag, 'id', '')}.pdf",
                   dedup=True)


def _slug(text):
    import re
    text = (text or '').strip().lower()
    text = (text.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')
                .replace('à', 'a').replace('é', 'e').replace('è', 'e')
                .replace('ß', 'ss'))
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text[:60] or 'dokument'
