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


SIGNIERT_TITEL = "Mietvertrag (unterzeichnet)"


def _file_sha256(fieldfile):
    """SHA-256 des Datei-Inhalts eines FieldFile (oder None)."""
    import hashlib
    try:
        fieldfile.open('rb')
        try:
            data = fieldfile.read()
        finally:
            fieldfile.close()
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return None


def ablage_signierter_vertrag(vertrag, pdf_bytes=None):
    """Legt den UNTERZEICHNETEN Mietvertrag zentral als rentals.Dokument ab —
    dadurch erscheint er überall dort, wo Verträge/Dokumente gezeigt werden:
    Mieterportal (im_portal_sichtbar), Person-Akte, Objekt-/Liegenschafts-Akte.

    **Genau EIN kanonisches signiertes Dokument pro Vertrag** (verhindert die
    Explosion bei Mehrfach-Versand/Neu-Unterschrift):
      - Ist der eingehende PDF-Inhalt identisch zu einem bereits abgelegten
        signierten Dokument (z.B. wiederholtes save() derselben Fassung), passiert
        NICHTS — kein Duplikat.
      - Kommt eine NEUE Unterschrift zurück (anderer Inhalt), wird das bestehende
        signierte Dokument **in-place aktualisiert** (Datei + Zeitstempel) und
        etwaige Alt-Dubletten werden zusammengeführt. So bleibt immer die aktuellste
        unterschriebene Fassung erhalten — nichts Wertvolles geht verloren, aber die
        Ablage bläht nicht auf.
    Gibt das Dokument zurück (oder None)."""
    from django.utils import timezone
    from django.core.files.base import ContentFile
    import hashlib
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

    from rentals.models import Dokument
    neu_hash = hashlib.sha256(pdf_bytes).hexdigest()
    # Alle bereits abgelegten signierten Fassungen dieses Vertrags (auch alt-
    # datierte aus früheren Versionen der Ablage-Logik).
    bestehende = list(Dokument.objects.filter(
        vertrag=vertrag, kategorie='vertrag',
        bezeichnung__startswith=SIGNIERT_TITEL).order_by('id'))

    # 1) Inhaltlich identisch bereits vorhanden → kein Duplikat.
    for d in bestehende:
        if d.datei and _file_sha256(d.datei) == neu_hash:
            return d

    stamp = timezone.localtime(timezone.now()).strftime('%d.%m.%Y %H:%M')
    stamp_file = timezone.localtime(timezone.now()).strftime('%Y%m%d_%H%M')
    titel = f"{SIGNIERT_TITEL} — {stamp}"
    dateiname = f"Mietvertrag_unterzeichnet_{getattr(vertrag, 'id', '')}_{stamp_file}.pdf"

    # 2) Neue Fassung: bestehendes kanonisches Dokument in-place aktualisieren,
    #    überzählige Alt-Dubletten entfernen (auf genau eines zusammenführen).
    if bestehende:
        ziel = bestehende[0]
        for d in bestehende[1:]:
            try:
                d.delete()
            except Exception:
                pass
        try:
            ziel.bezeichnung = titel[:200]
            ziel.titel = titel[:200]
            ziel.erstellt_am = timezone.now()
            ziel.datei.save(dateiname, ContentFile(pdf_bytes), save=True)
            return ziel
        except Exception:
            return None

    # 3) Noch keine Fassung → erstmals ablegen.
    return ablegen(pdf_bytes, titel, kategorie='vertrag', vertrag=vertrag,
                   dateiname=dateiname, dedup=False)


def bereinige_signierte_dubletten():
    """Einmalige/manuelle Aufräumung: reduziert je Vertrag ALLE signierten
    Dokumente auf das neueste (nach erstellt_am, dann id) — behebt bereits
    entstandene Ablage-Explosionen (Person-/Objekt-/Liegenschafts-Akte, Portal).
    Gibt die Anzahl entfernter Dubletten zurück."""
    from django.db.models import Count
    from rentals.models import Dokument
    geloescht = 0
    vids = (Dokument.objects
            .filter(kategorie='vertrag', bezeichnung__startswith=SIGNIERT_TITEL,
                    vertrag__isnull=False)
            .values('vertrag').annotate(n=Count('id')).filter(n__gt=1)
            .values_list('vertrag', flat=True))
    for vid in list(vids):
        docs = list(Dokument.objects.filter(
            vertrag_id=vid, kategorie='vertrag',
            bezeichnung__startswith=SIGNIERT_TITEL).order_by('-erstellt_am', '-id'))
        for d in docs[1:]:
            try:
                d.delete()
                geloescht += 1
            except Exception:
                pass
    return geloescht


def _slug(text):
    import re
    text = (text or '').strip().lower()
    text = (text.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')
                .replace('à', 'a').replace('é', 'e').replace('è', 'e')
                .replace('ß', 'ss'))
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text[:60] or 'dokument'
