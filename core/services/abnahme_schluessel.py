"""Schlüsselverzeichnis und Unterschrift der Abnahme."""
import base64
import binascii
import io

from django.core.files.base import ContentFile

MAX_UNTERSCHRIFT_BYTES = 750 * 1024        # eine Unterschrift als PNG ist wenige Kilobyte
MAX_UNTERSCHRIFT_PIXEL = (2000, 1000)
_PRAEFIX = 'data:image/png;base64,'
MAX_ZEILEN = 30


def schluessel_anlegen(prot, vorgaenger=None):
    """Legt die Zeilen des Schlüsselverzeichnisses für ein neues Protokoll an.

    Quelle in dieser Rangfolge: das Vorgänger-Protokoll (Soll übernommen, Ist
    wird neu gezählt), sonst das Schlüsselregister der Einheit und der
    Liegenschaft (Typ, Nummer, Anzahl)."""
    from portfolio.models import Schluessel
    from rentals.models import AbnahmeSchluessel
    if vorgaenger is not None and vorgaenger.schluessel.exists():
        # Der Ersatzpreis gehört zum Schlüssel, nicht zum Mieter: er wandert mit.
        zeilen = [(z.bezeichnung, z.anlage, z.soll, z.kosten_je_stueck) for z in vorgaenger.schluessel.all()]
    else:
        einheit = prot.vertrag.einheit
        # Einheit zuerst, dann die Schlüssel der Liegenschaft ohne Einheitsbezug (Haustür, Briefkasten …)
        register = list(Schluessel.objects.filter(einheit=einheit).order_by('id')) + list(
            Schluessel.objects.filter(liegenschaft=einheit.liegenschaft, einheit__isnull=True).order_by('id'))
        zeilen = [(r.typ, r.schluessel_nummer, r.anzahl, None) for r in register]
    for nr, (bezeichnung, anlage, soll, je_stueck) in enumerate(zeilen):
        AbnahmeSchluessel.objects.create(protokoll=prot, bezeichnung=bezeichnung[:80], anlage=anlage[:80],
                                         soll=max(0, int(soll or 0)), kosten_je_stueck=je_stueck, sortierung=nr)


def _zahl(text):
    text = (text or '').strip()
    return int(text) if text.isdigit() and int(text) < 1000 else None


def _betrag(text):
    """CHF-Betrag aus dem Formular; None bei leer, unlesbar oder negativ.
    Höchstens 99'999.99 (Feldgrösse) — ein Schlüssel kostet nicht mehr."""
    from decimal import Decimal, InvalidOperation
    text = (text or '').strip().replace("'", '').replace(',', '.')
    if not text:
        return None
    try:
        wert = Decimal(text).quantize(Decimal('0.01'))
    except InvalidOperation:
        return None
    return wert if Decimal('0') <= wert < Decimal('100000') else None


def schluessel_speichern(prot, P):
    """Ersetzt das Schlüsselverzeichnis durch die Zeilen aus dem Formular
    (parallele Listen `s_bezeichnung`, `s_anlage`, `s_soll`, `s_ist`,
    `s_kosten` — Ersatz je fehlendem Schlüssel).

    Leere Zeilen entfallen. Ist mindestens ein Ist gezählt, wird die Summe in
    `schluessel_anzahl` («Schlüssel zurück») übernommen — daran hängt die
    Pendenz «Schlüssel» beim Auszug."""
    from rentals.models import AbnahmeSchluessel
    bezeichnungen = P.getlist('s_bezeichnung')
    anlagen, solls, ists = P.getlist('s_anlage'), P.getlist('s_soll'), P.getlist('s_ist')
    kosten = P.getlist('s_kosten')
    zeilen = []
    for i, bez in enumerate(bezeichnungen[:MAX_ZEILEN]):
        bez = ' '.join((bez or '').split())[:80]
        if not bez:
            continue
        zeilen.append((bez, ' '.join((anlagen[i] if i < len(anlagen) else '').split())[:80],
                       _zahl(solls[i] if i < len(solls) else '') or 0,
                       _zahl(ists[i] if i < len(ists) else ''),
                       _betrag(kosten[i] if i < len(kosten) else '')))
    prot.schluessel.all().delete()
    for nr, (bez, anlage, soll, ist, je_stueck) in enumerate(zeilen):
        AbnahmeSchluessel.objects.create(protokoll=prot, bezeichnung=bez, anlage=anlage, soll=soll,
                                         ist=ist, kosten_je_stueck=je_stueck, sortierung=nr)
    gezaehlt = [ist for _b, _a, _s, ist, _k in zeilen if ist is not None]
    if gezaehlt:
        prot.schluessel_anzahl = sum(gezaehlt)
    return len(zeilen)


def unterschrift_pruefen(data_url):
    """Prüft eine Unterschrift aus dem Zeichenfeld und gibt die PNG-Bytes zurück.

    Erwartet `data:image/png;base64,…`. Abgelehnt (None) wird alles andere:
    anderer Typ, kaputtes Base64, zu gross, kein lesbares PNG. Das Zeichenfeld
    ist Eingabe von aussen — ein beliebiger Upload gehört hier nicht durch."""
    if not data_url or not data_url.startswith(_PRAEFIX):
        return None
    try:
        roh = base64.b64decode(data_url[len(_PRAEFIX):], validate=True)
    except (binascii.Error, ValueError):
        return None
    if not roh or len(roh) > MAX_UNTERSCHRIFT_BYTES:
        return None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(roh)) as bild:
            bild.verify()
        with Image.open(io.BytesIO(roh)) as bild:
            if bild.format != 'PNG' or bild.width > MAX_UNTERSCHRIFT_PIXEL[0] or bild.height > MAX_UNTERSCHRIFT_PIXEL[1]:
                return None
    except Exception:
        return None
    return roh


def unterschrift_speichern(prot, feld, data_url):
    """Speichert die Unterschrift am Protokoll; True, wenn eine gültige ankam.
    `feld` ist `unterschrift_mieter_bild` oder `unterschrift_verwalter_bild`."""
    assert feld in ('unterschrift_mieter_bild', 'unterschrift_verwalter_bild')
    roh = unterschrift_pruefen(data_url)
    if roh is None:
        return False
    getattr(prot, feld).save(f'{feld.replace("_bild", "")}.png', ContentFile(roh), save=False)
    return True
