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


def ablage_mahnung(vertrag, *, stufe=None, monat='', betrag='', datum=None,
                   pdf_bytes=None):
    """Legt die Mahnung als PDF in der Vertrags-Akte ab.

    Eine Mahnung ist der Beleg für eine Zahlungsaufforderung — bei Art. 257d OR
    hängt daran die Kündigungsandrohung. Sie landete bisher nirgends in der Akte:
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
        try:
            from core.views.email_views import (generate_mahnung_combined_pdf_bytes,
                                                get_aktueller_monat)
            from crm.models import Verwaltung
            monat = monat or get_aktueller_monat()
            if not betrag:
                betrag = f"{(vertrag.netto_mietzins or 0) + (vertrag.nebenkosten or 0):.2f}"
            pdf_bytes = generate_mahnung_combined_pdf_bytes(
                vertrag, Verwaltung.objects.first(), monat, str(betrag), datum)
        except Exception:
            return None
    if not pdf_bytes:
        return None

    stufe_txt = f"{stufe}. Mahnung" if stufe else "Mahnung"
    titel = f"{stufe_txt} vom {datum.strftime('%d.%m.%Y')}"
    dateiname = f"Mahnung_{stufe or ''}_{getattr(vertrag, 'id', '')}_{datum:%Y%m%d}.pdf"
    return ablegen(pdf_bytes, titel, kategorie='korrespondenz',
                   vertrag=vertrag, dateiname=dateiname, dedup=True)


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
