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
- referenz (string, QR-Referenz oder Rechnungsnummer, sonst "")
- iban (string, IBAN ohne Leerzeichen, sonst "")"""


def _leer(methode, hinweis):
    return {"lieferant": "", "iban": "", "betrag": 0.0, "datum": None,
            "referenz": "", "methode": methode, "hinweis": hinweis}


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
    datum = daten.get("datum")
    if datum:
        try:
            out["datum"] = datetime.strptime(str(datum)[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            out["datum"] = None
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

    ref_match = re.search(r'(\d{2}\s(?:\d{5}\s?){5})', text)
    reference = ref_match.group(0).replace(" ", "") if ref_match else ""

    lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 2]
    lieferant = lines[0][:100] if lines else ""

    return _normalisiere({"lieferant": lieferant, "iban": iban, "betrag": amount,
                          "datum": date_val, "referenz": reference}, "regex", hinweis)


def scan_beleg(file_path):
    """Scannt einen Kreditoren-Beleg (PDF oder Bild). Gibt immer ein Dict mit
    lieferant/iban/betrag/datum/referenz + methode/hinweis zurück — wirft nie."""
    api_key = getattr(settings, "GROQ_API_KEY", None)
    endung = os.path.splitext(str(file_path))[1].lower()

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
                return _scan_text_ki(full_text, api_key)
            except Exception as e:
                logger.warning("Rechnungsscan: Groq-Text fehlgeschlagen: %s", e)
                return _fallback_regex_scan(
                    full_text, hinweis=f"KI nicht erreichbar ({e}) — regelbasierte Erkennung, bitte Werte prüfen")
        return _fallback_regex_scan(full_text)

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
