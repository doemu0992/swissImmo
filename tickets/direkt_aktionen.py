# tickets/direkt_aktionen.py
"""Die Aktionen des Direktkanals, wie ein Formular sie schickt — für alle drei Zugänge gleich:
Mieterportal (angemeldet), Auftragsseite des Handwerkers (Token) und signierter Mail-Link.

Die Berechtigung (wer ist ``seite``?) prüft der Aufrufer VOR dem Aufruf; hier wird nur ausgeführt.
"""
from datetime import datetime

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from . import direktkanal, termin_abstimmung

AKTIONEN = ('direkt', 'termin', 'termin_vorschlagen', 'vorschlag_bestaetigen', 'termin_absagen')


def kennung(auftrag):
    """Zeitpunkt des offenen Vorschlags als Zahl — das Formular schickt ihn mit zurück."""
    return int(auftrag.termin_vorschlag_am.timestamp()) if auftrag.termin_vorschlag_am else 0


def _zeit(roh):
    try:
        return timezone.make_aware(datetime.strptime((roh or '').strip(), '%Y-%m-%dT%H:%M'))
    except ValueError:
        raise ValidationError(_('Bitte Datum und Zeit angeben.'), code='termin_fehlt')


def ausfuehren(auftrag, seite, post):
    """Führt die Aktion aus ``post['aktion']`` für ``seite`` aus. Gibt die Erfolgsmeldung zurück oder
    wirft ``ValidationError``. ``None``, wenn die Aktion nicht zum Direktkanal gehört."""
    aktion = post.get('aktion', '')
    if aktion not in AKTIONEN:
        return None
    if aktion == 'direkt':
        direktkanal.schreiben(auftrag, seite, post.get('text', ''))
        return _('Nachricht gesendet.')
    if aktion in ('termin', 'termin_vorschlagen'):
        ok = termin_abstimmung.vorschlagen(auftrag, seite, _zeit(post.get('termin')), post.get('hinweis', ''))
        return (_('Terminvorschlag gesendet. Die Gegenseite bestätigt oder macht einen anderen Vorschlag.')
                if ok else _('Terminvorschlag gespeichert. Die Gegenseite sieht ihn im Portal.'))
    if aktion == 'vorschlag_bestaetigen':
        try:
            k = int(post.get('kennung', ''))
        except ValueError:
            k = None
        termin_abstimmung.bestaetigen(auftrag, seite, kennung=k)
        return _('Termin bestätigt. Beide Seiten erhalten den Kalendereintrag.')
    termin_abstimmung.absagen_durch(auftrag, seite, post.get('hinweis', ''))
    return _('Termin abgesagt. Schlagen Sie einen neuen Termin vor.')
