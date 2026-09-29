"""Anzeigenamen für den Raum- und Objektkatalog der öffentlichen Meldeformulare.

`core/public_ticket_form.html` und `core/schaden_melden.html` führen Räume,
Objekte und Anliegen als deutsche Wörter in ihren Alpine-Daten. Diese Wörter
sind zugleich der GESPEICHERTE Wert: Sie landen als `raum`, `objekt`,
`kategorie` bzw. im Titel der Meldung und werden von der Verwaltung gelesen,
gefiltert und ausgewertet. Sie dürfen sich mit der Sprache nicht ändern.

Deshalb bleibt der Wert deutsch, und nur die ANZEIGE wird übersetzt: Dieser
Baustein liefert eine Tabelle «deutscher Wert → Anzeige in der aktuellen
Sprache» als `<script type="application/json">`, die Formulare zeigen
`t(name)` statt `name` an.

Eigener Kontext «Raumkatalog», weil dieselben Wörter anderswo anderes
bedeuten: «Zimmer» steht im Katalog bereits als Zimmerzahl («Pièces»), hier
ist es der Raum («Chambre»).
"""
from django import template
from django.utils.html import json_script
from django.utils import translation
from django.utils.translation import pgettext_lazy

register = template.Library()

#: Jeder Begriff, der in einem der beiden Formulare als Raum, Objekt oder
#: Anliegen angezeigt wird. Ein Test prüft, dass die Formulare keinen Begriff
#: führen, der hier fehlt.
BEGRIFFE = (
    # Räume
    pgettext_lazy('Raumkatalog', 'Küche'), pgettext_lazy('Raumkatalog', 'Bad'),
    pgettext_lazy('Raumkatalog', 'Korridor'), pgettext_lazy('Raumkatalog', 'Zimmer'),
    pgettext_lazy('Raumkatalog', 'Reduit'), pgettext_lazy('Raumkatalog', 'Balkon/Terrasse'),
    pgettext_lazy('Raumkatalog', 'Treppenhaus'), pgettext_lazy('Raumkatalog', 'Waschküche'),
    pgettext_lazy('Raumkatalog', 'Keller'), pgettext_lazy('Raumkatalog', 'Estrich'),
    pgettext_lazy('Raumkatalog', 'Veloraum'), pgettext_lazy('Raumkatalog', 'Briefkasten'),
    pgettext_lazy('Raumkatalog', 'Anderer Raum'),
    # Allgemeine Posten
    pgettext_lazy('Raumkatalog', 'Licht'), pgettext_lazy('Raumkatalog', 'Steckdose'),
    pgettext_lazy('Raumkatalog', 'Fenster'), pgettext_lazy('Raumkatalog', 'Storen/Markise'),
    pgettext_lazy('Raumkatalog', 'Boden'), pgettext_lazy('Raumkatalog', 'Wand'),
    pgettext_lazy('Raumkatalog', 'Decke'),
    # Objekte je Raum
    pgettext_lazy('Raumkatalog', 'Kühlschrank'), pgettext_lazy('Raumkatalog', 'Geschirrspüler'),
    pgettext_lazy('Raumkatalog', 'Dampfabzug'), pgettext_lazy('Raumkatalog', 'Kochherd'),
    pgettext_lazy('Raumkatalog', 'Backofen/Steamer'), pgettext_lazy('Raumkatalog', 'Spülbecken'),
    pgettext_lazy('Raumkatalog', 'Lavabo'), pgettext_lazy('Raumkatalog', 'WC'),
    pgettext_lazy('Raumkatalog', 'Dusche'), pgettext_lazy('Raumkatalog', 'Badewanne'),
    pgettext_lazy('Raumkatalog', 'Spiegelschrank'), pgettext_lazy('Raumkatalog', 'Lüftung'),
    pgettext_lazy('Raumkatalog', 'Waschmaschine'), pgettext_lazy('Raumkatalog', 'Tumbler'),
    pgettext_lazy('Raumkatalog', 'Secomat'), pgettext_lazy('Raumkatalog', 'Waschbecken'),
    pgettext_lazy('Raumkatalog', 'Abfluss'), pgettext_lazy('Raumkatalog', 'Wohnungstür'),
    pgettext_lazy('Raumkatalog', 'Gegensprechanlage'), pgettext_lazy('Raumkatalog', 'Einbauschrank'),
    pgettext_lazy('Raumkatalog', 'Haustür'), pgettext_lazy('Raumkatalog', 'Treppe/Geländer'),
    pgettext_lazy('Raumkatalog', 'Lift'), pgettext_lazy('Raumkatalog', 'Heizkörper'),
    pgettext_lazy('Raumkatalog', 'Zimmertür'), pgettext_lazy('Raumkatalog', 'Waschturm'),
    pgettext_lazy('Raumkatalog', 'Regal'), pgettext_lazy('Raumkatalog', 'Anschluss'),
    pgettext_lazy('Raumkatalog', 'Geländer'), pgettext_lazy('Raumkatalog', 'Sonnenstore'),
    pgettext_lazy('Raumkatalog', 'Balkontür'), pgettext_lazy('Raumkatalog', 'Kellerabteil'),
    pgettext_lazy('Raumkatalog', 'Kellertür'), pgettext_lazy('Raumkatalog', 'Feuchtigkeit'),
    pgettext_lazy('Raumkatalog', 'Estrichabteil'), pgettext_lazy('Raumkatalog', 'Dachfenster'),
    pgettext_lazy('Raumkatalog', 'Veloständer'), pgettext_lazy('Raumkatalog', 'Tür/Schloss'),
    pgettext_lazy('Raumkatalog', 'Schloss'), pgettext_lazy('Raumkatalog', 'Beschriftung'),
    pgettext_lazy('Raumkatalog', 'Klappe'), pgettext_lazy('Raumkatalog', 'Anderes'),
    pgettext_lazy('Raumkatalog', 'Sonstiges'),
    # Anliegen
    pgettext_lazy('Raumkatalog', 'Schadensmeldung'), pgettext_lazy('Raumkatalog', 'Allgemeine Anfrage'),
    pgettext_lazy('Raumkatalog', 'Namensschilder'), pgettext_lazy('Raumkatalog', 'Schlüsselbestellung'),
    pgettext_lazy('Raumkatalog', 'Frage zu Dokumenten'),
)


@register.simple_tag
def raum_anzeige(element_id='raum-anzeige'):
    """`<script id=… type="application/json">{"Küche": "Cuisine", …}</script>`.

    Der Schlüssel ist der deutsche Wert: Ohne aktive Sprache
    (`override(None)`) liefert gettext den Originaltext zurück.
    """
    with translation.override(None):
        werte = [str(b) for b in BEGRIFFE]
    return json_script(dict(zip(werte, (str(b) for b in BEGRIFFE))), element_id)
