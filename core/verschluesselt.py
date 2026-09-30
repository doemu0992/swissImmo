"""Datenbankfeld, das seinen Inhalt verschlüsselt ablegt (Fernet).

WOFÜR: Angaben, die im Klartext in jedem `pg_dump`, jeder Sicherung und jedem
Datenbankzugang stünden und die nie gesucht werden müssen — heute die
AHV-Nummer. Der Schlüssel ist derselbe wie für die Postfachzugänge
(`IMAP_SCHLUESSEL`, siehe `core/services/geheimnis.py`); dort steht auch, was
das Verfahren leistet und was nicht.

VERHALTEN
- Schreiben: immer verschlüsseln. Fehlt der Schlüssel, wird NICHT im Klartext
  gespeichert, sondern `SchluesselFehlt` geworfen — stilles Zurückfallen auf
  Klartext wäre genau der Zustand, den das Feld verhindern soll.
- Lesen: entschlüsselt. Alt-Bestand im Klartext (vor der Migration) wird
  unverändert geliefert und beim nächsten Speichern verschlüsselt.
  Lässt sich ein Geheimtext nicht lesen (Schlüssel gewechselt/fehlt), kommt der
  Geheimtext unverändert zurück und wird beim Speichern NICHT nochmals
  verschlüsselt — so geht beim Bearbeiten anderer Felder nichts verloren.
- Filtern (`filter(ahv_nummer=…)`) findet nichts: Fernet setzt je Aufruf einen
  Zufallswert. Das ist gewollt; wer suchen muss, braucht kein solches Feld.
"""
import logging

from django.db import models

logger = logging.getLogger(__name__)

#: Fernet-Token beginnen immer mit dieser Kennung (Version 0x80, Base64).
_KENNUNG = 'gAAAAA'
#: Kürzester denkbarer Token (Kopf + IV + ein Block + HMAC), Base64.
_MIN_LAENGE = 100


def sieht_verschluesselt_aus(wert) -> bool:
    return isinstance(wert, str) and wert.startswith(_KENNUNG) and len(wert) >= _MIN_LAENGE


class VerschluesseltesCharField(models.CharField):
    """Text, der als Fernet-Token gespeichert wird."""

    description = 'Verschlüsselter Text'

    def __init__(self, *args, klartext_max_laenge=None, **kwargs):
        self.klartext_max_laenge = klartext_max_laenge
        # Der Geheimtext ist deutlich länger als der Klartext (~ 4/3 · (n+57)).
        kwargs.setdefault('max_length', 512)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, pfad, args, kwargs = super().deconstruct()
        if self.klartext_max_laenge is not None:
            kwargs['klartext_max_laenge'] = self.klartext_max_laenge
        return name, pfad, args, kwargs

    def formfield(self, **kwargs):
        # Das Formular prüft die Länge des KLARTEXTS, nicht der Spalte.
        if self.klartext_max_laenge:
            kwargs.setdefault('max_length', self.klartext_max_laenge)
        return super().formfield(**kwargs)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        if sieht_verschluesselt_aus(value):
            return value          # unlesbarer Geheimtext: unverändert zurückschreiben
        from core.services.geheimnis import verschluesseln
        return verschluesseln(value)

    def from_db_value(self, value, expression, connection):
        if not value or not sieht_verschluesselt_aus(value):
            return value          # Alt-Bestand im Klartext
        from core.services.geheimnis import (
            GeheimtextKaputt, SchluesselFehlt, entschluesseln)
        try:
            return entschluesseln(value)
        except (SchluesselFehlt, GeheimtextKaputt):
            logger.warning('Verschlüsseltes Feld nicht lesbar (Schlüssel fehlt oder '
                           'gewechselt) — Geheimtext bleibt unverändert.')
            return value
