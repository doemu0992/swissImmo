"""iCalendar-Export der Fristen (RFC 5545). Erzeugt ganztägige VEVENTs, die in
Outlook/Google/Apple Calendar importiert oder als Feed abonniert werden können."""
from django.utils import timezone

def feed_token(benutzer, organisation):
    """Der Kalender-Token dieser Person in dieser Verwaltung — oder '' ohne Abonnement.

    JE PERSON, ZUFÄLLIG, WIDERRUFBAR (15.11.2026). Vorher war der Token eine Signatur über die Organisations-ID:
    derselbe für alle, nie ablaufend, nicht erneuerbar. Wer ihn einmal hatte — auch nach dem Austritt —, las
    dauerhaft alle Fristen samt Mieternamen. Jetzt liegt er an der Mitgliedschaft; `token_setzen` erneuert oder
    entfernt ihn. Die alten, signierten Tokens gelten nicht mehr.
    """
    zeile = _mitgliedschaft(benutzer, organisation)
    return (zeile.fristen_feed_token if zeile else '') or ''


def _mitgliedschaft(benutzer, organisation):
    """Die Mitgliedschaft, an der der Token hängt: die erste mit einer Schreibrolle."""
    from core.auth import SCHREIB_ROLLEN
    from crm.models import Mitgliedschaft
    if benutzer is None or organisation is None:
        return None
    return (Mitgliedschaft.alle_organisationen
            .filter(benutzer=benutzer, organisation=organisation, rolle__in=SCHREIB_ROLLEN)
            .order_by('pk').first())


def darf_abonnieren(benutzer, organisation):
    """Hat diese Person in dieser Verwaltung eine Schreibrolle (und damit einen eigenen Kalender-Link)?"""
    return _mitgliedschaft(benutzer, organisation) is not None


def token_setzen(benutzer, organisation, entfernen=False):
    """Erzeugt einen neuen Token (der alte gilt sofort nicht mehr) oder entfernt ihn. Gibt den neuen Wert zurück."""
    import secrets
    zeile = _mitgliedschaft(benutzer, organisation)
    if zeile is None:
        return ''
    zeile.fristen_feed_token = '' if entfernen else secrets.token_urlsafe(32)
    zeile.save(update_fields=['fristen_feed_token'])
    return zeile.fristen_feed_token


def organisation_aus_token(token):
    """Die Verwaltung zu einem Kalender-Token — oder None.

    Gilt nur, solange die Person aktiv ist und in dieser Verwaltung noch eine Schreibrolle hat: Wer austritt oder
    auf Lesezugriff zurückgestuft wird, verliert den Kalender, ohne dass jemand an den Token denken muss.
    """
    import hmac

    from core.auth import SCHREIB_ROLLEN
    from crm.models import Mitgliedschaft
    token = (token or '').strip()
    if len(token) < 20:
        return None
    zeile = (Mitgliedschaft.alle_organisationen.select_related('benutzer', 'organisation')
             .filter(fristen_feed_token=token).first())
    if zeile is None or not hmac.compare_digest(zeile.fristen_feed_token, token):
        return None
    if not zeile.benutzer.is_active or zeile.rolle not in SCHREIB_ROLLEN:
        return None
    return zeile.organisation


def _esc(text):
    """Text-Escaping nach RFC 5545 (Backslash, Komma, Semikolon, Zeilenumbruch)."""
    return (str(text or '')
            .replace('\\', '\\\\').replace(',', '\\,')
            .replace(';', '\\;').replace('\n', '\\n').replace('\r', ''))


def build_ics(events, name='immoswiss Fristen'):
    """events: Liste dicts mit uid, date (datetime.date), summary, description."""
    import datetime
    stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
    out = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//immoswiss//Fristen//DE',
           'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
           f'X-WR-CALNAME:{_esc(name)}', 'X-PUBLISHED-TTL:PT6H']
    for e in events:
        d = e['date']
        dstart = d.strftime('%Y%m%d')
        dend = (d + datetime.timedelta(days=1)).strftime('%Y%m%d')
        out += ['BEGIN:VEVENT',
                f'UID:{e["uid"]}@swissimmo',
                f'DTSTAMP:{stamp}',
                f'DTSTART;VALUE=DATE:{dstart}',
                f'DTEND;VALUE=DATE:{dend}',
                f'SUMMARY:{_esc(e["summary"])}']
        if e.get('description'):
            out.append(f'DESCRIPTION:{_esc(e["description"])}')
        out += ['TRANSP:TRANSPARENT', 'END:VEVENT']
    out.append('END:VCALENDAR')
    return '\r\n'.join(out) + '\r\n'


def fristen_events(pendenzen):
    """Wandelt datierte Pendenzen in iCal-Event-Dicts um."""
    events = []
    for p in pendenzen:
        if not p.faellig_am:
            continue
        bezug = ''
        if p.vertrag_id and p.vertrag:
            bezug = p.vertrag.mieter.display_name if p.vertrag.mieter_id else ''
        elif p.liegenschaft_id:
            bezug = f"{p.liegenschaft.strasse}, {p.liegenschaft.ort}"
        desc = p.beschreibung or ''
        if bezug:
            desc = f"{bezug}\n{desc}".strip()
        events.append({'uid': f"pendenz-{p.id}", 'date': p.faellig_am,
                       'summary': p.titel, 'description': desc})
    return events
