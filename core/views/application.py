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

def public_datenschutz_view(request, einheit_id=None):
    """Datenschutzerklärung — ohne Anmeldung erreichbar.

    Wird aus dem öffentlichen Bewerbungsformular verlinkt: Nach Art. 19 revDSG
    muss die betroffene Person bei der Beschaffung informiert werden, und zwar
    bevor sie ihre Daten abschickt. Firma und Adresse kommen aus dem
    Verwaltungs-Datensatz, damit es keinen zweiten, veraltenden Ort dafür gibt.

    **Die Erklärung nennt den Verantwortlichen — und der ist je Verwaltung ein
    anderer.** Deshalb führt der Weg über das Objekt, für das man sich bewirbt:
    Die Bewerberin sieht die Verwaltung, die ihre Daten tatsächlich erhebt.
    `Organisation.objects.first()` nannte ab der zweiten Verwaltung eine
    fremde Firma als Verantwortliche — nach revDSG Art. 19 keine Kleinigkeit,
    denn an dieser Angabe hängen Auskunfts- und Löschbegehren.

    Ohne Objekt (alter Lesezeichen-Link auf `/datenschutz/`) ist die Frage
    nicht beantwortbar. Bei genau einer Verwaltung gibt es keine Zweideutigkeit;
    bei mehreren wird bewusst KEINE genannt, sondern auf den Weg über das
    Objekt verwiesen. Eine geratene Firma wäre schlimmer als keine.
    """
    from django.utils import timezone
    from crm.models import Organisation

    verwaltung, mehrdeutig = None, False
    if einheit_id is not None:
        einheit = get_object_or_404(Einheit.objects.select_related('liegenschaft'), id=einheit_id)
        verwaltung = einheit.liegenschaft.organisation
    else:
        moegliche = list(Organisation.objects.all()[:2])
        if len(moegliche) == 1:
            verwaltung = moegliche[0]
        elif len(moegliche) > 1:
            mehrdeutig = True

    return render(request, 'core/public_datenschutz.html', {
        'verwaltung': verwaltung,
        'mehrdeutig': mehrdeutig,
        'stand': timezone.localdate(),
    })
