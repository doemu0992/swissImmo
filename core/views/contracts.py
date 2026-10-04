import logging
from rentals.models import Mietvertrag, MietzinsAnpassung
from core.utils import get_current_ref_zins, get_current_lik

import io
import datetime
from decimal import Decimal, InvalidOperation
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse
from core.auth import rolle_erforderlich, ROLLE_VERWALTER

# PDF Tools
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors

logger = logging.getLogger(__name__)


# Hilfsfunktionen für Marktdaten

def parse_decimal(value):
    """Hilfsfunktion: Verwandelt Eingaben sicher in Decimal-Zahlen."""
    if not value: return Decimal('0.00')
    try:
        clean_value = str(value).replace(',', '.').strip()
        return Decimal(clean_value)
    except (InvalidOperation, ValueError):
        return Decimal('0.00')

@rolle_erforderlich(ROLLE_VERWALTER)
def mietzins_anpassung_view(request, vertrag_id):
    """Alter Einstieg `/mietzins/<id>/` — leitet auf das amtliche Formular um.

    Die frühere Fassung rechnete mit einer eigenen, linearen Formel (Senkung −3 % je
    Schritt statt der Überwälzungstabelle), setzte die Kostenpauschale fest auf 0.5 %,
    prüfte weder Ankündigungsfrist noch Wirksamkeitstermin und erzeugte ein PDF, das
    nicht das kantonale amtliche Formular ist (Art. 269d OR: sonst nichtig). Berechnung,
    Fristen und Formular liegen an genau einer Stelle: `fw_mietzins_anpassung`.
    """
    get_object_or_404(Mietvertrag, pk=vertrag_id)
    return redirect('fw_mietzins_anpassung', vertrag_id=vertrag_id)


@rolle_erforderlich(ROLLE_VERWALTER)
def generiere_amtliches_formular(request, vertrag_id):
    return redirect('mietzins_anpassung', vertrag_id=vertrag_id)