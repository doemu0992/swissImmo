# finance/utils.py
import pdfplumber
import re
from decimal import Decimal
from datetime import datetime

def scan_invoice_pdf(file_path):
    """
    Extrahiert Text aus dem PDF und sucht nach Rechnungsdaten.
    """
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"

    text_lower = text.lower()

    # 1. IBAN Suche (Schweizer Format)
    iban_match = re.search(r'CH\d{2}\s?(?:\d{4}\s?){4}\d', text)
    iban = iban_match.group(0).replace(" ", "") if iban_match else ""

    # 2. Betrag Suche (Sucht nach CHF/Total gefolgt von Zahlen)
    # Erkennt Formate wie 1'250.00, 1250.00, 45.60
    amount_matches = re.findall(r'(?:chf|total|betrag|summe)[\s\:\.]*([\d\'\s]+\.\d{2})', text_lower)
    amount = None
    if amount_matches:
        # Den höchsten gefundenen Betrag nehmen (meistens das Total)
        clean_amounts = [Decimal(m.replace("'", "").replace(" ", "")) for m in amount_matches]
        amount = max(clean_amounts)

    # 3. Datum Suche (dd.mm.yyyy)
    date_match = re.search(r'(\d{1,2}\.\d{1,2}\.\d{4})', text)
    date_val = None
    if date_match:
        try:
            date_val = datetime.strptime(date_match.group(1), '%d.%m.%Y').date()
        except:
            pass

    # 4. Referenznummer (QR-Referenz oder ESR)
    ref_match = re.search(r'(\d{2}\s(?:\d{5}\s?){5})', text) # QR-Ref Format
    reference = ref_match.group(0).replace(" ", "") if ref_match else ""

    # 5. Lieferant (Einfache Heuristik: Erste Zeile des PDFs)
    lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 2]
    lieferant = lines[0][:100] if lines else "Unbekannter Lieferant"

    return {
        "lieferant": lieferant,
        "iban": iban,
        "betrag": amount,
        "datum": date_val,
        "referenz": reference,
        "raw_text": text
    }