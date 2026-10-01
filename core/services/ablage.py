"""Auto-Ablage: legt generierte PDFs automatisch in die Dokument-Akte
(core_dokument / rentals.Dokument) ab und verknüpft sie mit Vertrag,
Mieter, Einheit und Liegenschaft."""
import logging
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)



def ablegen(pdf_bytes, titel, kategorie='korrespondenz', *,
            vertrag=None, mieter=None, einheit=None, liegenschaft=None,
            dateiname=None, dedup=False, zugang_pflichtig=False):
    """Speichert ``pdf_bytes`` als Dokument in der Akte.

    Fehlende Bezüge werden - soweit möglich - aus dem Vertrag abgeleitet.
    Mit ``dedup=True`` wird ein bereits vorhandenes Dokument gleicher
    Bezeichnung (am selben Vertrag) überschrieben statt dupliziert.
    `zugang_pflichtig`: Das Schreiben muss dem Mieter nachweislich zugehen (Art. 257d) —
    es gilt als «nicht zugestellt», bis der Zugang bestätigt ist (`Dokument.zustellstatus`).
    Gibt das (erstellte oder aktualisierte) Dokument zurück (oder ``None``)."""
    from rentals.models import Dokument
    if vertrag is not None:
        mieter = mieter or getattr(vertrag, 'mieter', None)
        einheit = einheit or getattr(vertrag, 'einheit', None)
    if einheit is not None and liegenschaft is None:
        liegenschaft = getattr(einheit, 'liegenschaft', None)

    if dedup and vertrag is not None:
        # `alle_organisationen`: Gesucht wird das Dokument zu GENAU DIESEM
        # Vertrag — die Mandantengrenze steht in derselben Zeile
        # (`vertrag=vertrag`), und ein Vertrag gehoert genau einer Verwaltung.
        # Mit `objects` braeche die Ablage ueberall dort ab, wo sie aus einem
        # Lauf heraus geschieht: Mahnung, Sollstellung, Vertragsversand.
        vorhanden = Dokument.alle_organisationen.filter(
            vertrag=vertrag, bezeichnung=(titel or 'Dokument')[:200]).first()
        if vorhanden is not None:
            try:
                if not (dateiname or '').lower().endswith('.pdf'):
                    dateiname = f"{_slug(dateiname or titel or 'dokument')}.pdf"
                vorhanden.datei.save(dateiname, ContentFile(pdf_bytes), save=True)
                if zugang_pflichtig and not vorhanden.zugang_pflichtig:
                    vorhanden.zugang_pflichtig = True
                    vorhanden.save(update_fields=['zugang_pflichtig'])
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
            zugang_pflichtig=zugang_pflichtig,
        )
        dok.datei.save(dateiname, ContentFile(pdf_bytes), save=True)
        return dok
    except Exception:
        return None


SIGNIERT_TITEL = "Mietvertrag (unterzeichnet)"


def ablage_mahnung(vertrag, *, stufe=None, monat='', betrag='', datum=None,
                   pdf_bytes=None, rechnung=None, gebuehr=None, letzte_stufe=False,
                   zugang_pflichtig=None):
    """Legt die Mahnung als PDF in der Vertrags-Akte ab.

    Eine Mahnung ist der Beleg für eine Zahlungsaufforderung. Ohne `pdf_bytes`
    entsteht das Schreiben der MAHNSTUFE (`core/services/mahnbrief.py`). Seit dem
    Entscheid vom 01.10.2026 ist das bei einer Stufe mit Art.-257d-Häkchen das
    257d-Schreiben selbst — die Akte würde dann einen Brief belegen, der noch nicht
    zugestellt ist. Deshalb trägt so ein Dokument `zugang_pflichtig` und gilt als
    «nicht zugestellt», bis die eingeschriebene Fristansetzung erfasst und ihr Zugang
    bestätigt ist (`Dokument.zustellstatus`). `zugang_pflichtig=None` heisst: wie
    `letzte_stufe`. Die 257d-Fristansetzung (eingeschrieben, unterschrieben)
    kommt als fertiges `pdf_bytes` aus `fw_verzug_257d`. Sie landete bisher nirgends in der Akte:
    Historie und Gebühr wurden gebucht, das Schreiben selbst existierte nur als
    Download im Moment des Klicks. Wer später nachweisen musste, WAS dem Mieter
    zugestellt wurde, fand unter Vertrag → Dokumente nichts.

    Der Titel trägt Stufe und Datum, `dedup=True` überschreibt denselben Titel am
    selben Vertrag — mehrfaches Klicken am selben Tag erzeugt kein Duplikat, eine
    spätere Stufe aber ein eigenes Dokument.

    Gibt das Dokument zurück (oder None). Die Ablage darf den Mahnvorgang nie
    scheitern lassen — Buchung und Historie sind wichtiger als der Beleg.
    """
    from django.utils import timezone
    if vertrag is None:
        return None
    datum = datum or timezone.localdate()
    if pdf_bytes is None:
        # Die ABGELEGTE Mahnung ist das Schreiben der Stufe (bei Häkchen: das 257d-Schreiben,
        # siehe core/services/mahnbrief.py). Die formelle, eingeschriebene Fristansetzung legt
        # `fw_verzug_257d` selbst ab, wenn sie gesetzt wird.
        try:
            from core.services.mahnbrief import forderungs_monat, mahnbrief_pdf, monat_text
            if not monat:
                monat = forderungs_monat(rechnung) if rechnung is not None else monat_text(datum)
            if not betrag:
                betrag = (f"{rechnung.offener_betrag:.2f}" if rechnung is not None else
                          f"{(vertrag.netto_mietzins or 0) + (vertrag.nebenkosten or 0):.2f}")
            # Absender: die Verwaltung DIESES Vertrags (nie ein Singleton).
            pdf_bytes = mahnbrief_pdf(
                vertrag, vertrag.organisation, stufe=stufe or 1, monat=monat,
                betrag=str(betrag), datum=datum, gebuehr=gebuehr,
                letzte_stufe=letzte_stufe, rechnung=rechnung)
        except Exception:
            return None
    if not pdf_bytes:
        return None

    stufe_txt = f"{stufe}. Mahnung" if stufe else "Mahnung"
    titel = f"{stufe_txt} vom {datum.strftime('%d.%m.%Y')}"
    dateiname = f"Mahnung_{stufe or ''}_{getattr(vertrag, 'id', '')}_{datum:%Y%m%d}.pdf"
    return ablegen(pdf_bytes, titel, kategorie='korrespondenz',
                   vertrag=vertrag, dateiname=dateiname, dedup=True,
                   zugang_pflichtig=bool(letzte_stufe if zugang_pflichtig is None else zugang_pflichtig))


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
                logger.debug("Fehler bewusst übergangen", exc_info=True)
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
                logger.debug("Fehler bewusst übergangen", exc_info=True)
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
                logger.debug("Fehler bewusst übergangen", exc_info=True)
    return geloescht


def bereinige_vertragsbeilagen_dubletten():
    """Einmalige/manuelle Aufräumung der automatisch erzeugten Vertrags-Beilagen
    (Mietvertrag, Allgemeine Bedingungen, Hausordnung, Merkblatt, Wohnungsausweis,
    Begleitbrief): je (Objekt, Titel) nur das neueste behalten. Der UNTERZEICHNETE
    Vertrag (eigene Logik) bleibt unberührt. Gibt die Anzahl entfernter Dubletten
    zurück."""
    from django.db.models import Count
    from rentals.models import Dokument
    geloescht = 0
    gruppen = (Dokument.objects
               .filter(kategorie='vertrag', einheit__isnull=False)
               .exclude(bezeichnung__startswith=SIGNIERT_TITEL)
               .values('einheit', 'bezeichnung')
               .annotate(n=Count('id')).filter(n__gt=1))
    for g in gruppen:
        docs = list(Dokument.objects.filter(
            kategorie='vertrag', einheit_id=g['einheit'], bezeichnung=g['bezeichnung'])
            .exclude(bezeichnung__startswith=SIGNIERT_TITEL)
            .order_by('-erstellt_am', '-id'))
        for d in docs[1:]:
            try:
                d.delete()
                geloescht += 1
            except Exception:
                logger.debug("Fehler bewusst übergangen", exc_info=True)
    return geloescht


def _slug(text):
    import re
    text = (text or '').strip().lower()
    text = (text.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')
                .replace('à', 'a').replace('é', 'e').replace('è', 'e')
                .replace('ß', 'ss'))
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text[:60] or 'dokument'
