# finance/utils.py — KI-Rechnungsscanner für Kreditoren-Belege.
#
# Pipeline (scan_beleg):
#   1. Bild-Datei (jpg/png/webp)      → Groq Vision-Modell
#   2. PDF mit Textebene              → Groq Text-Modell, Fallback Regex
#   3. PDF ohne Text (Foto-Scan)      → Seite 1 via pdftoppm rendern → Vision
#
# Jedes Ergebnis trägt 'methode' ('ki' | 'vision' | 'regex' | 'leer') und
# 'hinweis' — die UI zeigt damit ehrlich, WIE erkannt wurde, statt still zu
# degradieren. Ohne GROQ_API_KEY läuft nur der Regex-Pfad (kein Netzwerk).
import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime
from decimal import Decimal

import requests
import pdfplumber
from django.conf import settings

logger = logging.getLogger(__name__)

# Aktuelle Groq-Produktionsmodelle (das frühere llama3-8b-8192 ist abgeschaltet).
GROQ_TEXT_MODEL = "llama-3.3-70b-versatile"
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_TEXT_CHARS = 12000          # lange PDFs kürzen (Kerndaten stehen vorne)
BILD_ENDUNGEN = ('.jpg', '.jpeg', '.png', '.webp')

_PROMPT = """Du bist ein präziser Schweizer Buchhaltungs-Scanner.
Lies die folgende Rechnung und extrahiere die Kerndaten.
Antworte AUSSCHLIESSLICH als gültiges JSON mit exakt diesen Keys:
- lieferant (string, Name der Firma/des Rechnungsstellers — nicht der Empfänger)
- betrag (number, der Brutto-Rechnungsbetrag/Total in CHF, max. 2 Nachkommastellen)
- datum (string, Rechnungsdatum zwingend im Format YYYY-MM-DD, sonst null)
- faellig (string, Fälligkeits-/Zahlbar-bis-Datum im Format YYYY-MM-DD — steht
  z.B. bei «Zahlbar bis», «Fällig am», «Zahlungsziel»; sonst null)
- referenz (string: die QR-REFERENZ aus dem Zahlteil/Empfangsschein — 27 Ziffern,
  gedruckt z.B. als «00 00506 37947 06000 08940 95003». NICHT die Rechnungs- oder
  Kundennummer! Nur wenn kein Zahlteil vorhanden ist: die Rechnungsnummer. Sonst "")
- iban (string ohne Leerzeichen: bevorzugt die QR-IBAN aus dem Zahlteil bei
  «Konto / Zahlbar an» — sie beginnt nach CHxx mit 30000–31999. Sonst "")"""

# --- Schweizer QR-Zahlteil: deterministische Extraktion (übersteuert die KI) ---
# Für QRR-Zahlungen zählen NUR die 27-stellige QR-Referenz (Mod10-rekursiv
# geprüft) und die QR-IBAN (IID 30000–31999) — nicht Rechnungsnummer/Konto-IBAN.
_QRR_TABELLE = [0, 9, 4, 6, 8, 2, 7, 1, 3, 5]


def _qrr_pruefziffer_ok(ref):
    c = 0
    for z in ref[:-1]:
        c = _QRR_TABELLE[(c + int(z)) % 10]
    return (10 - c) % 10 == int(ref[-1])


def _zahlteil_extrahieren(text):
    """(qr_referenz, qr_iban) aus dem Text des Zahlteils — '' wenn nicht gefunden."""
    qrr = ''
    for m in re.finditer(r'\b\d{2}(?:\s?\d{5}){5}\b', text):
        kandidat = re.sub(r'\s+', '', m.group(0))
        if len(kandidat) == 27 and _qrr_pruefziffer_ok(kandidat):
            qrr = kandidat
            break
    qriban = ''
    for m in re.finditer(r'\bCH\d{2}(?:\s?\d{4}){4}\s?\d\b', text):
        kandidat = re.sub(r'\s+', '', m.group(0))
        if len(kandidat) == 21 and kandidat[4:9].isdigit() and 30000 <= int(kandidat[4:9]) <= 31999:
            qriban = kandidat
            break
    return qrr, qriban


def _zahlteil_anwenden(ergebnis, text):
    """Übersteuert Referenz/IBAN mit den geprüften Zahlteil-Werten (falls vorhanden)."""
    qrr, qriban = _zahlteil_extrahieren(text)
    if qrr:
        ergebnis['referenz'] = qrr
    if qriban:
        ergebnis['iban'] = qriban
    return ergebnis


# --- Schweizer QR-Code (Swiss Payments Code) direkt dekodieren -----------------
# Die verbindlichste Quelle: der QR-Code des Zahlteils enthält IBAN, Referenz,
# Betrag und Zahlungsempfänger maschinenlesbar (SPC v2). Funktioniert für
# Text-PDFs, Foto-Scan-PDFs UND direkte Bilder — kein KI-Raten mehr.

def _spc_parsen(text):
    """Parst einen Swiss-Payments-Code-Payload. None, wenn kein gültiger SPC."""
    zeilen = text.replace('\r\n', '\n').split('\n')
    if len(zeilen) < 29 or zeilen[0].strip() != 'SPC':
        return None
    daten = {
        'iban': re.sub(r'\s+', '', zeilen[3]),
        'lieferant': zeilen[5].strip(),           # Zahlungsempfänger (Creditor)
        'referenz': re.sub(r'\s+', '', zeilen[28]) if len(zeilen) > 28 else '',
    }
    try:
        daten['betrag'] = round(float(zeilen[18]), 2) if zeilen[18].strip() else 0.0
    except (ValueError, IndexError):
        daten['betrag'] = 0.0
    return daten


def _qr_rechnung_dekodieren(file_path, endung):
    """Sucht in einem Beleg (PDF-Seiten via pdftoppm oder Bild) den Schweizer
    QR-Code und gibt die SPC-Daten zurück — None, wenn keiner gefunden/lesbar.
    zxing-cpp ist optional: fehlt es, greift still der Text-Fallback."""
    try:
        import zxingcpp
        from PIL import Image
    except ImportError:
        logger.info("Rechnungsscan: zxing-cpp nicht installiert — QR-Decoder inaktiv.")
        return None

    def _aus_bild(img):
        try:
            for code in zxingcpp.read_barcodes(img):
                spc = _spc_parsen(code.text or '')
                if spc:
                    return spc
        except Exception as e:
            logger.warning("Rechnungsscan: QR-Dekodierung fehlgeschlagen: %s", e)
        return None

    try:
        if endung in BILD_ENDUNGEN:
            with Image.open(file_path) as img:
                return _aus_bild(img)
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["pdftoppm", "-png", "-r", "200", "-f", "1", "-l", "8",
                            str(file_path), os.path.join(tmp, "s")],
                           check=True, capture_output=True, timeout=120)
            # Zahlteil liegt meist auf der LETZTEN Seite → rückwärts suchen
            for name in sorted(os.listdir(tmp), reverse=True):
                if not name.endswith('.png'):
                    continue
                with Image.open(os.path.join(tmp, name)) as img:
                    spc = _aus_bild(img)
                if spc:
                    return spc
    except Exception as e:
        logger.warning("Rechnungsscan: QR-Suche fehlgeschlagen: %s", e)
    return None


def _qr_anwenden(ergebnis, qr):
    """Übersteuert das Scan-Ergebnis mit den dekodierten QR-Daten (verbindlich)."""
    if not qr:
        return ergebnis
    if qr.get('iban'):
        ergebnis['iban'] = qr['iban'][:50]
    if qr.get('referenz'):
        ergebnis['referenz'] = qr['referenz'][:100]
    if qr.get('betrag'):
        ergebnis['betrag'] = qr['betrag']
    if qr.get('lieferant'):
        ergebnis['lieferant'] = qr['lieferant'][:200]
    if ergebnis.get('methode') in ('regex', 'leer'):
        ergebnis['methode'] = 'qr'
        ergebnis['hinweis'] = 'Schweizer QR-Code dekodiert — Zahlungsdaten verbindlich'
    else:
        ergebnis['hinweis'] = (ergebnis.get('hinweis') or '') + ' · QR-Code dekodiert ✓'
    return ergebnis


def _leer(methode, hinweis):
    return {"lieferant": "", "iban": "", "betrag": 0.0, "datum": None,
            "faellig": None, "referenz": "", "methode": methode, "hinweis": hinweis}


def _normalisiere(daten, methode, hinweis=""):
    """Bringt die KI-Antwort in ein garantiert verwertbares Format."""
    out = _leer(methode, hinweis)
    out["lieferant"] = str(daten.get("lieferant") or "").strip()[:200]
    out["iban"] = re.sub(r"\s+", "", str(daten.get("iban") or ""))[:50]
    out["referenz"] = str(daten.get("referenz") or "").strip()[:100]
    try:
        out["betrag"] = round(float(daten.get("betrag") or 0), 2)
    except (TypeError, ValueError):
        out["betrag"] = 0.0
    for feld in ("datum", "faellig"):
        wert = daten.get(feld)
        if wert:
            try:
                out[feld] = datetime.strptime(str(wert)[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                out[feld] = None
    return out


def _groq_call(messages, model, api_key):
    resp = requests.post(GROQ_URL, timeout=45, json={
        "model": model, "messages": messages, "temperature": 0,
        "response_format": {"type": "json_object"},
    }, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])


def _scan_text_ki(full_text, api_key):
    daten = _groq_call([{"role": "user", "content": f"{_PROMPT}\n\nRechnungstext:\n{full_text[:MAX_TEXT_CHARS]}"}],
                       GROQ_TEXT_MODEL, api_key)
    return _normalisiere(daten, "ki", "KI-Texterkennung (Groq)")


def _scan_bild_ki(png_bytes, api_key, mime="image/png"):
    b64 = base64.b64encode(png_bytes).decode()
    daten = _groq_call([{"role": "user", "content": [
        {"type": "text", "text": _PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]}], GROQ_VISION_MODEL, api_key)
    return _normalisiere(daten, "vision", "KI-Bilderkennung (Groq Vision)")


def _pdf_seite_als_png(file_path):
    """Rendert Seite 1 eines Bild-PDFs als PNG (pdftoppm/poppler). None bei Fehler."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ziel = os.path.join(tmp, "seite")
            subprocess.run(["pdftoppm", "-png", "-r", "150", "-f", "1", "-l", "1",
                            file_path, ziel], check=True, capture_output=True, timeout=60)
            for name in sorted(os.listdir(tmp)):
                if name.endswith(".png"):
                    with open(os.path.join(tmp, name), "rb") as fh:
                        return fh.read()
    except Exception as e:
        logger.warning("Rechnungsscan: PDF-Rendering fehlgeschlagen: %s", e)
    return None


def _fallback_regex_scan(text, hinweis="Regelbasierte Erkennung (ohne KI) — bitte Werte prüfen"):
    text_lower = text.lower()

    iban_match = re.search(r'CH\d{2}\s?(?:\d{4}\s?){4}\d', text)
    iban = iban_match.group(0).replace(" ", "") if iban_match else ""

    amount_matches = re.findall(r"(?:chf|total|betrag|summe)[\s\:\.]*([\d\'\s]+\.\d{2})", text_lower)
    amount = 0.0
    if amount_matches:
        clean_amounts = [Decimal(m.replace("'", "").replace(" ", "")) for m in amount_matches]
        amount = float(max(clean_amounts))

    date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
    date_val = None
    if date_match:
        try:
            d_obj = datetime.strptime(f"{date_match.group(1)}.{date_match.group(2)}.{date_match.group(3)}", '%d.%m.%Y')
            date_val = d_obj.strftime('%Y-%m-%d')
        except ValueError:
            pass

    # Fälligkeit: explizites Datum bei Zahlbar-bis/Fällig-am/Zahlungsziel …
    faellig_val = None
    fm = re.search(r'(?:zahlbar\s*bis|f[äa]llig(?:keit)?(?:\s*am)?|zahlungsziel|zahlungsfrist(?:\s*bis)?)\s*:?\D{0,10}(\d{1,2})\.(\d{1,2})\.(\d{4})', text_lower)
    if fm:
        try:
            faellig_val = datetime.strptime(f"{fm.group(1)}.{fm.group(2)}.{fm.group(3)}", '%d.%m.%Y').strftime('%Y-%m-%d')
        except ValueError:
            pass
    # … oder relative Frist «zahlbar innert 30 Tagen» ab Rechnungsdatum
    if not faellig_val and date_val:
        tm = re.search(r'(?:zahlbar|zahlung)\s*(?:innert|innerhalb|in)\s*(\d{1,3})\s*tag', text_lower)
        if tm:
            from datetime import timedelta
            faellig_val = (datetime.strptime(date_val, '%Y-%m-%d')
                           + timedelta(days=int(tm.group(1)))).strftime('%Y-%m-%d')

    ref_match = re.search(r'(\d{2}\s(?:\d{5}\s?){5})', text)
    reference = ref_match.group(0).replace(" ", "") if ref_match else ""

    lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 2]
    lieferant = lines[0][:100] if lines else ""

    return _normalisiere({"lieferant": lieferant, "iban": iban, "betrag": amount,
                          "datum": date_val, "faellig": faellig_val,
                          "referenz": reference}, "regex", hinweis)


def scan_beleg(file_path):
    """Scannt einen Kreditoren-Beleg (PDF oder Bild). Gibt immer ein Dict mit
    lieferant/iban/betrag/datum/referenz + methode/hinweis zurück — wirft nie.

    Reihenfolge: (1) Schweizer QR-Code dekodieren (verbindlichste Quelle für
    IBAN/Referenz/Betrag/Empfänger), (2) KI/Regex für die restlichen Felder
    (v.a. Datum), (3) QR-Daten übersteuern das KI-Ergebnis."""
    endung = os.path.splitext(str(file_path))[1].lower()
    qr = _qr_rechnung_dekodieren(file_path, endung)
    return _qr_anwenden(_scan_basis(file_path, endung), qr)


def _scan_basis(file_path, endung):
    """Text-/Vision-/Regex-Scan ohne QR-Overlay."""
    api_key = getattr(settings, "GROQ_API_KEY", None)

    # --- Direktes Bild (Foto der Rechnung) ---
    if endung in BILD_ENDUNGEN:
        if not api_key:
            return _leer("leer", "Bild-Beleg ohne KI nicht auslesbar — GROQ_API_KEY unter Integrationen hinterlegen.")
        try:
            with open(file_path, "rb") as fh:
                mime = "image/jpeg" if endung in (".jpg", ".jpeg") else f"image/{endung[1:]}"
                return _scan_bild_ki(fh.read(), api_key, mime=mime)
        except Exception as e:
            logger.warning("Rechnungsscan: Vision fehlgeschlagen: %s", e)
            return _leer("leer", f"KI-Bilderkennung fehlgeschlagen ({e}) — bitte manuell erfassen.")

    # --- PDF: Text extrahieren ---
    full_text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    full_text += extracted + "\n"
    except Exception as e:
        return _leer("leer", f"PDF konnte nicht gelesen werden ({e}).")

    if full_text.strip():
        if api_key:
            try:
                return _zahlteil_anwenden(_scan_text_ki(full_text, api_key), full_text)
            except Exception as e:
                logger.warning("Rechnungsscan: Groq-Text fehlgeschlagen: %s", e)
                return _zahlteil_anwenden(_fallback_regex_scan(
                    full_text, hinweis=f"KI nicht erreichbar ({e}) — regelbasierte Erkennung, bitte Werte prüfen"), full_text)
        return _zahlteil_anwenden(_fallback_regex_scan(full_text), full_text)

    # --- PDF ohne Textebene (Foto-Scan) → Vision ---
    if api_key:
        png = _pdf_seite_als_png(file_path)
        if png:
            try:
                return _scan_bild_ki(png, api_key)
            except Exception as e:
                logger.warning("Rechnungsscan: Vision fehlgeschlagen: %s", e)
                return _leer("leer", f"KI-Bilderkennung fehlgeschlagen ({e}) — bitte manuell erfassen.")
        return _leer("leer", "Foto-Scan-PDF: Seite konnte nicht gerendert werden (poppler/pdftoppm fehlt?) — bitte manuell erfassen.")
    return _leer("leer", "Foto-Scan-PDF ohne Textebene — für automatische Erkennung GROQ_API_KEY unter Integrationen hinterlegen.")


def scan_invoice_pdf(file_path):
    """Rückwärtskompatibler Alias (alter API-Endpunkt /api/finance/kreditoren/upload)."""
    return scan_beleg(file_path)
