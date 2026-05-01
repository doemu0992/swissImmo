# core/utils.py
import os
import unicodedata
import re
from decimal import Decimal

def get_smart_upload_path(instance, filename):
    """
    Erzeugt einen sauberen, dynamischen Pfad für Datei-Uploads.
    Beispiel: media/portfolio/Musterstrasse_1/Wohnung_EG/vertrag/mietvertrag_gerber.pdf
    """
    # 1. Hilfsfunktion: Macht aus "Musterstraße 1!" ein sauberes "musterstrasse_1"
    def slugify(value):
        value = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode('ascii')
        value = re.sub(r'[^\w\s-]', '', value).strip().lower()
        return re.sub(r'[-\s]+', '_', value)

    folder = "allgemein"

    # 2. Prüfen, wohin das Dokument gehört
    if hasattr(instance, 'liegenschaft') and instance.liegenschaft:
        l_name = slugify(instance.liegenschaft.strasse)
        if hasattr(instance, 'einheit') and instance.einheit:
            e_name = slugify(instance.einheit.bezeichnung)
            kat = slugify(getattr(instance, 'kategorie', 'dokumente'))
            folder = f"portfolio/{l_name}/{e_name}/{kat}"
        else:
            folder = f"portfolio/{l_name}/allgemein"

    elif hasattr(instance, 'mieter') and instance.mieter:
        folder = f"mieter/{slugify(instance.mieter.nachname)}"

    # 3. Dateiname ebenfalls säubern (Sonderzeichen entfernen)
    base, ext = os.path.splitext(filename)
    clean_filename = f"{slugify(base)}{ext.lower()}"

    return os.path.join(folder, clean_filename)

def get_current_ref_zins():
    """
    Standardwert für neuen Referenzzinssatz, wenn ein Vertrag erstellt wird.
    """
    return Decimal('1.50')

def get_current_lik():
    """
    Standardwert für neuen Landesindex (LIK), wenn ein Vertrag erstellt wird.
    """
    return Decimal('100.0')