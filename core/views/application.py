# core/views/application.py
from django.shortcuts import render, get_object_or_404
from portfolio.models import Einheit

def public_application_view(request, einheit_id):
    """Öffentliches Bewerbungsformular für ein ausgeschriebenes Objekt.

    Ohne Anmeldung erreichbar. Das Formular gibt es deshalb nur, solange das
    Objekt tatsächlich ausgeschrieben ist (`zur_ausschreibung`) — derselbe
    Schalter, den der Portal-Feed nutzt und den die App automatisch löscht,
    sobald ein Vertrag aktiv wird.

    Vorher rendete jede Objektnummer das Formular. Zwei Folgen: Über die
    Nummer in der Adresse liess sich der ganze Bestand durchprobieren
    (Adresse und Objektbezeichnung standen auf der Seite), und ein alter,
    geteilter Link sammelte weiter Bewerbungen — mit Lohnausweis,
    Ausweiskopie und Betreibungsauszug — für eine längst vergebene Wohnung.
    """
    einheit = get_object_or_404(Einheit, id=einheit_id)

    if not einheit.zur_ausschreibung:
        return render(request, 'core/public_bewerbung_geschlossen.html', status=410)

    return render(request, 'core/public_bewerbung_form.html', {
        'einheit': einheit
    })