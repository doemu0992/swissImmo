# tickets/meldung.py
"""Was ein Melder angibt — an EINER Stelle für alle Meldeformulare.

Das QR-Aushangformular (`core/public_ticket_form.html`) und das Mieterportal
(`core/mieter_schaden.html`) fragen dieselbe Erreichbarkeit ab. Bis Modul 3
standen die Zeitfenster nur als vier abgetippte Checkboxen im QR-Formular.

- **Kategorie** («Anliegen»): die fünf Werte aus `raumkatalog.ANLIEGEN`, als
  deutsches Wort gespeichert (`SchadenMeldung.kategorie`).
- **Zutritt**: `SchadenMeldung.ZUTRITT_CHOICES`, gespeichert in `zutritt`.
- **Erreichbarkeit**: die Zeitfenster unten. Es gibt dafür kein Feld; wie im
  QR-Formular steht sie als Zeile «Erreichbar: …» in der Beschreibung.
"""

#: Zeitfenster, in denen der Melder für den Handwerker erreichbar ist.
ZEITFENSTER = ('08:00 - 10:00', '10:00 - 12:00', '14:00 - 16:00', '16:00 - 18:00')

#: Kopf des Kontaktblocks, den `process_public_ticket_form` an die
#: Beschreibung hängt (Name, Telefon, E-Mail des Melders).
KONTAKT_KOPF = '--- KONTAKT ---'
GERAET_KOPF = '--- GERÄT ---'
ERREICHBAR = 'Erreichbar:'


def erreichbarkeit_zeile(fenster):
    """«Erreichbar: 08:00 - 10:00, 14:00 - 16:00» — oder '' ohne Auswahl."""
    fenster = [f for f in (fenster or []) if f]
    return f"{ERREICHBAR} {', '.join(fenster)}" if fenster else ''


def gueltige_zeitfenster(werte):
    """Nur bekannte Zeitfenster, in der Reihenfolge von `ZEITFENSTER`."""
    werte = set(werte or [])
    return [f for f in ZEITFENSTER if f in werte]


def ohne_kontaktblock(text):
    """Beschreibung ohne Name, Telefon und E-Mail des Melders.

    Für Leser, die den Melder nicht kennen dürfen: den Handwerker nach dem
    Abschluss und Mitbewohner einer Einheit, deren Meldung jemand anders
    erfasst hat. Die Zeile «Erreichbar: …» und der Geräteblock bleiben.
    """
    if not text or KONTAKT_KOPF not in text:
        return text or ''
    vorne, _, rest = text.partition(KONTAKT_KOPF)
    behalten = []
    geraet = ''
    if GERAET_KOPF in rest:
        rest, _, geraet = rest.partition(GERAET_KOPF)
        geraet = f"{GERAET_KOPF}{geraet}"
    for zeile in rest.splitlines():
        if zeile.strip().startswith(ERREICHBAR):
            behalten.append(zeile.strip())
    teile = [vorne.rstrip()] + behalten + ([geraet.strip()] if geraet else [])
    return '\n\n'.join(t for t in teile if t)
