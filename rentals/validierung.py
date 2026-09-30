"""Plausibilitätsprüfung der Vertragswerte — EINE Stelle für alle Eingänge.

Der Vertragsassistent, das Bearbeitenformular und der Weg «Bewerbung →
Vertragsentwurf» prüften bisher je für sich (oder gar nicht). Was durchkam:

- `NaN`, `Infinity`, `1e999`: `Decimal()` liest sie klaglos, der Vergleich
  `wert < 0` wirft dann `InvalidOperation` → HTTP 500.
- Ein Mietzins über der Feldbreite: SQLite speichert ihn, PostgreSQL wirft
  einen Serverfehler (Feld `DecimalField(8, 2)`).
- Ein Mietbeginn vor dem Baujahr der Liegenschaft oder im Jahr 0001/9999.

Die Grenzen sind die Feldbreiten des Modells, nicht geschätzte Plausibilität —
so ist jede Ablehnung mit «würde die Datenbank sprengen» begründbar. Ein
Mietzins von CHF 0 bleibt bewusst erlaubt (Hauswartwohnung, Gratis-Parkplatz):
Das ist eine Warnung im Assistenten, kein Fehler.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.utils.translation import gettext

#: Frühester und spätester denkbarer Mietbeginn (Jahre).
BEGINN_FRUEHESTENS = 1900
BEGINN_SPAETESTENS_JAHRE_VORAUS = 10

PERSONEN_MAX = 30


def endliche_zahl(roh):
    """Text → endliche `Decimal`. Wirft `InvalidOperation` bei NaN/Infinity/Unlesbarem.

    `Decimal('NaN')` ist KEIN Fehler beim Lesen — genau darum reicht ein
    `try: Decimal(...)` nicht.
    """
    zahl = Decimal(roh)
    if not zahl.is_finite():
        raise InvalidOperation(f"nicht endlich: {roh!r}")
    return zahl


def _obergrenze(feld):
    """Grösster Wert, den das Modellfeld aufnimmt (max_digits/decimal_places)."""
    from rentals.models import Mietvertrag
    f = Mietvertrag._meta.get_field(feld)
    return Decimal(10) ** (f.max_digits - f.decimal_places) - Decimal(1).scaleb(-f.decimal_places)


def pruefe_vertragswerte(*, netto=None, nebenkosten=None, kaution=None, beginn=None,
                         ende=None, anzahl_personen=None, einheit=None, einstellplatz=False):
    """Gibt `{feld: meldung}` zurück — leer, wenn alles plausibel ist.

    `None` heisst «nicht angegeben» und wird nicht geprüft (der Aufrufer
    entscheidet, ob das Feld Pflicht ist).
    """
    fehler = {}

    def betrag(feld, wert, bezeichnung):
        if wert is None:
            return
        if wert < 0:
            fehler[feld] = gettext('%(feld)s darf nicht negativ sein.') % {'feld': bezeichnung}
        elif wert > _obergrenze(feld):
            fehler[feld] = gettext('%(feld)s ist zu hoch (höchstens CHF %(max)s).') % {
                'feld': bezeichnung, 'max': f"{_obergrenze(feld):,.2f}".replace(',', "'")}

    betrag('netto_mietzins', netto, gettext('Der Netto-Mietzins'))
    if not einstellplatz:
        betrag('nebenkosten', nebenkosten, gettext('Die Nebenkosten'))
    betrag('kautions_betrag', kaution, gettext('Die Kaution'))

    if anzahl_personen is not None and not (1 <= anzahl_personen <= PERSONEN_MAX):
        fehler['anzahl_personen'] = gettext('Die Personenzahl muss zwischen 1 und %(max)s liegen.') % {'max': PERSONEN_MAX}

    if beginn is not None:
        heute = date.today()
        if beginn.year < BEGINN_FRUEHESTENS or beginn.year > heute.year + BEGINN_SPAETESTENS_JAHRE_VORAUS:
            fehler['beginn'] = gettext('Der Mietbeginn %(datum)s ist nicht plausibel (erlaubt: %(von)s bis %(bis)s).') % {
                'datum': beginn.isoformat(), 'von': BEGINN_FRUEHESTENS,
                'bis': heute.year + BEGINN_SPAETESTENS_JAHRE_VORAUS}
        else:
            baujahr = getattr(getattr(einheit, 'liegenschaft', None), 'baujahr', None)
            if baujahr and beginn.year < baujahr:
                fehler['beginn'] = gettext('Der Mietbeginn (%(jahr)s) liegt vor dem Baujahr der Liegenschaft (%(baujahr)s).') % {
                    'jahr': beginn.year, 'baujahr': baujahr}
    if beginn is not None and ende is not None and ende < beginn:
        fehler['ende'] = gettext('Das Vertragsende darf nicht vor dem Vertragsbeginn liegen.')
    return fehler
