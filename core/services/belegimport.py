# core/services/belegimport.py — gemeinsamer Import-Pfad für Kreditoren-Belege.
#
# Wird vom Upload-Scan (/neu/kreditoren/scan/) UND vom E-Mail-Eingang
# (Management-Command fetch_rechnungen) genutzt: Beleg speichern → KI-Scanner
# (finance.utils.scan_beleg) → Kreditorenrechnung (Status Neu) mit den
# erkannten Daten. Die Erkennungs-Methode/Herkunft steht in `fehlermeldung`
# und wird im Edit-Panel der Kreditorenliste angezeigt.
import email
import logging
import re
from datetime import date
from decimal import Decimal
from email.header import decode_header

from django.core.files.base import ContentFile

from core.services.iban import ist_gueltige_iban

logger = logging.getLogger(__name__)

BELEG_ENDUNGEN = ('.pdf', '.jpg', '.jpeg', '.png', '.webp')


def beleg_importieren(datei, liegenschaft=None, quelle=''):
    """Speichert einen Beleg (UploadedFile/ContentFile), scannt ihn und legt die
    Kreditorenrechnung (Status Neu) mit den erkannten Daten an.
    Gibt (rechnung, scandaten) zurück — wirft nie wegen Scan-Fehlern."""
    from finance.models import KreditorenRechnung
    from finance.utils import scan_beleg

    kr = KreditorenRechnung.objects.create(beleg_scan=datei, status='neu',
                                           liegenschaft=liegenschaft)
    daten = scan_beleg(kr.beleg_scan.path)
    kr.lieferant = (daten.get('lieferant') or '')[:200]
    kr.iban = (daten.get('iban') or '')[:50]
    kr.referenz = (daten.get('referenz') or '')[:100]
    try:
        b = Decimal(str(daten.get('betrag') or 0)).quantize(Decimal('0.01'))
        kr.betrag = b if b > 0 else None
    except Exception:
        kr.betrag = None
    if daten.get('datum'):
        try:
            kr.datum = date.fromisoformat(daten['datum'])
        except ValueError:
            pass
    if daten.get('faellig'):
        try:
            kr.faellig_am = date.fromisoformat(daten['faellig'])
        except ValueError:
            pass
    # Leistungsperiode (für taggenaue HNK-Zuordnung) aus dem Scan übernehmen.
    for src, dst in (('leistung_von', 'leistungs_von'), ('leistung_bis', 'leistungs_bis')):
        if daten.get(src):
            try:
                setattr(kr, dst, date.fromisoformat(daten[src]))
            except ValueError:
                pass
    # Konto (+ HNK) automatisch vorbelegen: Lieferanten-Gedächtnis → KI-Kategorie →
    # Schlüsselwörter. Spart das manuelle Zuteilen.
    from finance.lieferanten import vorbelegen
    if vorbelegen(kr, kategorie=daten.get('kategorie')):
        daten['konto_auto'] = kr.konto.nummer
    # Anschrift für die Zahlungsdatei: aus dem QR-Code bzw. der KI-Erkennung, sonst
    # die gelernte des Lieferanten. Fehlt beides, bleibt sie leer (der Zahllauf
    # meldet es) — geraten wird nichts.
    from finance.kreditor_adresse import adresse_setzen, aus_profil_uebernehmen
    adresse = daten.get('adresse') or {}
    if (adresse.get('ort') or '').strip():
        adresse_setzen(kr, adresse)
    else:
        aus_profil_uebernehmen(kr)
    hinweis = '' if daten.get('methode') in ('ki', 'vision', 'qr') else (daten.get('hinweis') or '')
    if kr.iban and not ist_gueltige_iban(kr.iban):
        # Eine gelesene IBAN ohne stimmende Prüfziffer ist fast immer ein
        # Lesefehler (Ziffer vertauscht, Zeichen verwechselt). Sie bleibt zur
        # Korrektur stehen, aber die Freigabe lässt sie nicht durch.
        warnung = (f"Gelesene IBAN {kr.iban} ist ungültig (Prüfziffer) — bitte mit dem Beleg "
                   "vergleichen und korrigieren.")
        hinweis = warnung + (f" · {hinweis}" if hinweis else '')
    if quelle:
        hinweis = quelle + (f" · {hinweis}" if hinweis else '')
    kr.fehlermeldung = hinweis
    kr.save()
    return kr, daten


def _decode_mime(wert):
    if not wert:
        return ''
    teile = []
    for inhalt, enc in decode_header(wert):
        if isinstance(inhalt, bytes):
            teile.append(inhalt.decode(enc or 'utf-8', errors='ignore'))
        else:
            teile.append(str(inhalt))
    return ''.join(teile)


def importiere_rechnungsmail(msg):
    """Verarbeitet eine E-Mail (email.message.Message): jeder PDF-/Bild-Anhang
    wird als Kreditorenrechnung importiert und gescannt. Gibt die Liste der
    erstellten Rechnungen zurück (leer, wenn kein passender Anhang)."""
    absender = _decode_mime(msg.get('From', '')) or 'Unbekannt'
    # Nur die Adresse (ohne Anzeigename) für die kompakte Herkunftsangabe
    m = re.search(r'<([^>]+)>', absender)
    absender_kurz = (m.group(1) if m else absender).strip()[:100]

    rechnungen = []
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        dateiname = _decode_mime(part.get_filename() or '')
        ctype = part.get_content_type()
        ist_beleg = (dateiname.lower().endswith(BELEG_ENDUNGEN)
                     or ctype == 'application/pdf'
                     or ctype in ('image/jpeg', 'image/png', 'image/webp'))
        if not ist_beleg:
            continue
        inhalt = part.get_payload(decode=True)
        if not inhalt:
            continue
        if not dateiname:
            dateiname = 'beleg.pdf' if ctype == 'application/pdf' else f"beleg.{ctype.split('/')[-1]}"
        # Dateiname säubern (nur Basename, keine Pfad-Tricks)
        dateiname = re.sub(r'[^\w.\-]', '_', dateiname.split('/')[-1].split('\\')[-1])[:90]
        kr, daten = beleg_importieren(ContentFile(inhalt, name=dateiname),
                                      quelle=f"Per E-Mail von {absender_kurz}")
        logger.info("Rechnungsmail-Import: %s von %s → Rechnung #%s (%s)",
                    dateiname, absender_kurz, kr.id, daten.get('methode'))
        # Ins Aktivitätslog (Benutzer = System) → sichtbar im Logbuch und im
        # Verlauf des Lieferantenkontos (Abgleich über den Lieferantennamen).
        from core.auth import log_aktion
        log_aktion(None, "Rechnung per E-Mail eingegangen", kr.lieferant or dateiname,
                   f"Von {absender_kurz} · CHF {kr.betrag or 0} · Methode: {daten.get('methode')}")
        rechnungen.append(kr)
    return rechnungen


def importiere_rechnungsmail_bytes(raw_bytes):
    """Wie importiere_rechnungsmail, aber ab rohen RFC822-Bytes (IMAP-Fetch)."""
    return importiere_rechnungsmail(email.message_from_bytes(raw_bytes))
