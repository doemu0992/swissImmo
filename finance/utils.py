# finance/utils.py
import os
import re
import json
import requests
import pdfplumber
from decimal import Decimal
from datetime import datetime
from django.conf import settings

def scan_invoice_pdf(file_path):
    print(f"\n--- 🚀 AUTO-SCAN START FÜR: {file_path} ---")
    full_text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    full_text += extracted + "\n"
    except Exception as e:
        print(f"❌ PDF-Read-Fehler: {e}")
        raise ValueError(f"PDF konnte nicht gelesen werden: {e}")

    # Sicherheits-Check für Bild-PDFs
    if not full_text.strip():
        print("⚠️ WARNUNG: Das PDF enthält keinen lesbaren Text! (Wahrscheinlich ein reines Bild/Foto-Scan)")
        return {
            "lieferant": "Foto-Scan (Bitte manuell tippen)",
            "iban": "",
            "betrag": 0.0,
            "datum": None,
            "referenz": ""
        }

    print(f"📝 Extrahierte Text-Länge: {len(full_text)} Zeichen.")

    # API-Key Check
    api_key = getattr(settings, "GROQ_API_KEY", None)
    print(f"🔑 Groq API-Key gefunden: {'JA' if api_key else 'NEIN'}")

    if api_key:
        prompt = f"""
        Du bist ein präziser Schweizer Buchhaltungs-Scanner.
        Lies den folgenden Text einer Rechnung und extrahiere die Kerndaten.
        Antworte AUSSCHLIESSLICH im gültigen JSON-Format mit exakt diesen Keys:
        - lieferant (string, der Name der Firma/des Rechnungsstellers)
        - betrag (float, der Rechnungsbetrag, max. 2 Nachkommastellen)
        - datum (string, das Rechnungsdatum zwingend im Format YYYY-MM-DD, falls nicht gefunden: null)
        - referenz (string, Rechnungsnummer oder QR-Referenz, falls nicht gefunden: "")
        - iban (string, die IBAN Nummer ohne Leerzeichen, falls nicht gefunden: "")

        Rechnungstext:
        {full_text}
        """

        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "llama3-8b-8192",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": { "type": "json_object" }
            }

            print("🤖 Sende Daten an Groq API...")
            resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=15)
            resp.raise_for_status()

            raw_content = resp.json()['choices'][0]['message']['content']
            print(f"📥 Antwort von Groq erhalten: {raw_content}")

            extracted_json = json.loads(raw_content)
            return extracted_json

        except Exception as e:
            print(f"❌ Groq-KI fehlgeschlagen: {e} -> Wechsle zu Regex-Fallback.")

    # Fallback
    print("🔍 Starte lokalen Regex-Muster-Scanner...")
    return _fallback_regex_scan(full_text)


def _fallback_regex_scan(text):
    text_lower = text.lower()

    iban_match = re.search(r'CH\d{2}\s?(?:\d{4}\s?){4}\d', text)
    iban = iban_match.group(0).replace(" ", "") if iban_match else ""

    amount_matches = re.findall(r'(?:chf|total|betrag|summe)[\s\:\.]*([\d\'\s]+\.\d{2})', text_lower)
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
        except:
            pass

    ref_match = re.search(r'(\d{2}\s(?:\d{5}\s?){5})', text)
    reference = ref_match.group(0).replace(" ", "") if ref_match else ""

    lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 2]
    lieferant = lines[0][:100] if lines else "Unbekannter Lieferant"

    return {
        "lieferant": lieferant,
        "iban": iban,
        "betrag": amount,
        "datum": date_val,
        "referenz": reference
    }