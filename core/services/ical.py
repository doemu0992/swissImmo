"""iCalendar-Export der Fristen (RFC 5545). Erzeugt ganztägige VEVENTs, die in
Outlook/Google/Apple Calendar importiert oder als Feed abonniert werden können."""
from django.utils import timezone
from django.core import signing

FEED_SALT = 'fristen-feed'


def feed_token():
    """Signierter, nicht-ablaufender Token für die abonnierbare Feed-URL."""
    return signing.Signer(salt=FEED_SALT).sign('fristen')


def token_gueltig(token):
    try:
        return signing.Signer(salt=FEED_SALT).unsign(token or '') == 'fristen'
    except signing.BadSignature:
        return False


def _esc(text):
    """Text-Escaping nach RFC 5545 (Backslash, Komma, Semikolon, Zeilenumbruch)."""
    return (str(text or '')
            .replace('\\', '\\\\').replace(',', '\\,')
            .replace(';', '\\;').replace('\n', '\\n').replace('\r', ''))


def build_ics(events, name='swissImmo Fristen'):
    """events: Liste dicts mit uid, date (datetime.date), summary, description."""
    import datetime
    stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
    out = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//swissImmo//Fristen//DE',
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
