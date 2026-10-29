"""Raum- und Objektkatalog der öffentlichen Meldeformulare, mit Anzeigenamen.

Das öffentliche Meldeformular (`core/schaden_melden.html`, erreichbar als
`/schaden/melden/` und als Treppenhaus-Aushang `/report/<id>/`) führt Räume,
Objekte und Anliegen als deutsche Wörter. Bis Etappe 3 standen sie doppelt in den
Alpine-Daten zweier Vorlagen; jetzt stehen sie hier, einmal. Diese Wörter
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

#: Die Anliegen (Kategorie einer Meldung). Eigener Name, weil auch das
#: Mieterportal sie als Auswahl anbietet (Modul 3) — dieselben Werte, nicht
#: ein zweites Mal abgetippt.
ANLIEGEN = (
    pgettext_lazy('Raumkatalog', 'Schadensmeldung'), pgettext_lazy('Raumkatalog', 'Allgemeine Anfrage'),
    pgettext_lazy('Raumkatalog', 'Namensschilder'), pgettext_lazy('Raumkatalog', 'Schlüsselbestellung'),
    pgettext_lazy('Raumkatalog', 'Frage zu Dokumenten'),
)


def anliegen_auswahl():
    """[(gespeicherter deutscher Wert, Anzeige in der aktuellen Sprache), …]."""
    with translation.override(None):
        werte = [str(a) for a in ANLIEGEN]
    return list(zip(werte, [str(a) for a in ANLIEGEN]))


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
) + ANLIEGEN


# Die Räume, in der Reihenfolge der Auswahl: (deutscher Wert, Zeichen im Sprite).
# «Anderer Raum» ist der Ausweg für alles, was die Liste nicht kennt (Garage,
# Sitzplatz) — ohne ihn müsste man einen falschen Raum wählen, und die Verwaltung
# bekäme einen Auftrag mit falschem Ort.
RAEUME = (
    ('Küche', 'kueche'), ('Bad', 'bad'), ('Korridor', 'korridor'), ('Zimmer', 'zimmer'),
    ('Reduit', 'reduit'), ('Balkon/Terrasse', 'balkon'), ('Treppenhaus', 'treppenhaus'),
    ('Waschküche', 'waschkueche'), ('Keller', 'keller'), ('Estrich', 'estrich'),
    ('Veloraum', 'veloraum'), ('Briefkasten', 'briefkasten'), ('Anderer Raum', 'einheit'),
)

#: Was es in einem Raum gibt — aber nicht in jedem: Ein Briefkasten hat keine Decke, ein
#: Balkon keine Steckdose. Wer das anwählt, meldet einen Schaden an etwas, das es dort
#: nicht gibt, und die Verwaltung schickt einen Handwerker los (E2.51). `alle` gilt für
#: die Innenräume, die hier nicht eigens aufgeführt sind.
ALLGEMEIN = {
    'alle': ('Licht', 'Steckdose', 'Fenster', 'Storen/Markise', 'Boden', 'Wand', 'Decke'),
    'Reduit': ('Licht', 'Steckdose', 'Boden', 'Wand', 'Decke'),
    'Balkon/Terrasse': ('Licht', 'Boden'),
    'Keller': ('Licht', 'Steckdose', 'Boden', 'Wand', 'Decke'),
    'Estrich': ('Licht', 'Boden', 'Wand', 'Decke'),
    'Veloraum': ('Licht', 'Steckdose', 'Boden', 'Wand'),
    'Treppenhaus': ('Licht', 'Boden', 'Wand', 'Decke', 'Fenster'),
    'Briefkasten': (),
}

#: Gegenstände je Raum: (deutscher Wert, ist ein Gerät). Bei einem Gerät fragt das
#: Aushang-Formular nach Marke und Seriennummer.
OBJEKTE = {
    'Küche': (('Kühlschrank', True), ('Geschirrspüler', True), ('Dampfabzug', True), ('Kochherd', True),
              ('Backofen/Steamer', True), ('Spülbecken', False)),
    'Bad': (('Lavabo', False), ('WC', False), ('Dusche', False), ('Badewanne', False),
            ('Spiegelschrank', False), ('Lüftung', False)),
    'Korridor': (('Wohnungstür', False), ('Gegensprechanlage', False), ('Einbauschrank', False)),
    'Zimmer': (('Heizkörper', False), ('Einbauschrank', False), ('Zimmertür', False)),
    'Reduit': (('Waschturm', True), ('Regal', False), ('Anschluss', False)),
    'Balkon/Terrasse': (('Geländer', False), ('Sonnenstore', False), ('Abfluss', False), ('Balkontür', False)),
    'Treppenhaus': (('Haustür', False), ('Treppe/Geländer', False), ('Lift', True)),
    # `Secomat` steht hier seit jeher: ein Trocknungsgerät, in Schweizer Waschküchen so
    # häufig wie der Tumbler und ein gängiger Störungsfall.
    'Waschküche': (('Waschmaschine', True), ('Tumbler', True), ('Secomat', True),
                   ('Waschbecken', False), ('Abfluss', False)),
    'Keller': (('Kellerabteil', False), ('Kellertür', False), ('Feuchtigkeit', False)),
    'Estrich': (('Estrichabteil', False), ('Dachfenster', False), ('Feuchtigkeit', False)),
    'Veloraum': (('Veloständer', False), ('Tür/Schloss', False)),
    'Briefkasten': (('Schloss', False), ('Beschriftung', False), ('Klappe', False)),
    # Bewusst leer: Was dort steht, weiss nur die Meldung selbst.
    'Anderer Raum': (),
}

#: Letzter Eintrag jeder Gegenstandsliste: der Ausweg für alles andere.
ANDERES = 'Anderes'


def _anzeige_tabelle():
    """{deutscher Wert: Anzeige in der aktiven Sprache} für alle BEGRIFFE."""
    with translation.override(None):
        werte = [str(b) for b in BEGRIFFE]
    return dict(zip(werte, (str(b) for b in BEGRIFFE)))


def raum_katalog():
    """Räume mit Gegenständen: [{'wert', 'anzeige', 'zeichen', 'objekte': [{'wert', 'anzeige', 'geraet'}]}].

    Pro Raum zuerst, was dort steht, dann die allgemeinen Posten dieses Raums, zuletzt
    «Anderes». Der Wert ist deutsch (er wird gespeichert), die Anzeige folgt der Sprache.
    """
    t = _anzeige_tabelle()
    katalog = []
    for raum, zeichen in RAEUME:
        eigene = [(name, geraet) for name, geraet in OBJEKTE.get(raum, ())]
        allgemein = [(name, False) for name in ALLGEMEIN.get(raum, ALLGEMEIN['alle'])]
        objekte = [{'wert': n, 'anzeige': t[n], 'geraet': g} for n, g in eigene + allgemein + [(ANDERES, False)]]
        katalog.append({'wert': raum, 'anzeige': t[raum], 'zeichen': zeichen, 'objekte': objekte})
    return katalog


register.simple_tag(raum_katalog, name='raum_katalog')


#: Zeichen je Anliegen (docs/ZEICHEN.md: eines je Anliegen, kein Raumsymbol).
ANLIEGEN_ZEICHEN = ('kritisch', 'senden', 'person', 'schluessel', 'dokument')


def anliegen_karten():
    """[{'wert' (deutsch, gespeichert), 'anzeige', 'zeichen', 'schaden'}] für die Auswahlkarten.

    `schaden` ist wahr für die Schadensmeldung: Nur sie fragt nach Raum und Gegenstand.
    """
    return [{'wert': wert, 'anzeige': anzeige, 'zeichen': zeichen, 'schaden': i == 0}
            for i, ((wert, anzeige), zeichen) in enumerate(zip(anliegen_auswahl(), ANLIEGEN_ZEICHEN))]


register.simple_tag(anliegen_karten, name='anliegen_karten')


@register.simple_tag
def raum_anzeige(element_id='raum-anzeige'):
    """`<script id=… type="application/json">{"Küche": "Cuisine", …}</script>`.

    Der Schlüssel ist der deutsche Wert: Ohne aktive Sprache
    (`override(None)`) liefert gettext den Originaltext zurück.
    """
    with translation.override(None):
        werte = [str(b) for b in BEGRIFFE]
    return json_script(dict(zip(werte, (str(b) for b in BEGRIFFE))), element_id)
