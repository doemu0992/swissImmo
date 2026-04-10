# crm/services.py
from django.db.models import Q
from .models import Mieter

def search_mieter(query):
    """
    Sucht Mieter anhand von Vorname, Nachname, Email oder Firmenname.
    Gibt ein Django QuerySet zurück.
    """
    if not query:
        return Mieter.objects.all()

    return Mieter.objects.filter(
        Q(vorname__icontains=query) |
        Q(nachname__icontains=query) |
        Q(email__icontains=query) |
        Q(firma__icontains=query)
    ).distinct()

def onboard_new_mieter(mieter_obj):
    """
    Platzhalter für zukünftige Automatisierungen.
    Hier könnte z.B. später ein Willkommens-E-Mail versendet oder
    ein Zugang für ein Mieter-Portal (Self-Service) generiert werden.
    """
    # Aktuell passiert hier noch nichts, aber die Struktur steht!
    pass