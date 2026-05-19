# core/views/application.py
from django.shortcuts import render, get_object_or_404
from portfolio.models import Einheit

def public_application_view(request, einheit_id):
    """
    Diese View rendert das öffentliche Bewerbungsformular für eine bestimmte Wohneinheit.
    Mietinteressenten können über diese Seite ihre Personalien eingeben und Dokumente hochladen.
    """
    # Holt die Wohneinheit anhand der ID oder wirft einen sauberen 404-Fehler, falls das Objekt nicht existiert
    einheit = get_object_or_404(Einheit, id=einheit_id)

    # Rendert das Template aus deinem core/templates/core/ Verzeichnis
    return render(request, 'core/public_bewerbung_form.html', {
        'einheit': einheit
    })