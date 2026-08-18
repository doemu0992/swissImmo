"""iCalendar-Export der Fristen (RFC 5545). Erzeugt ganztägige VEVENTs, die in
Outlook/Google/Apple Calendar importiert oder als Feed abonniert werden können."""
from django.utils import timezone
from django.core import signing

FEED_SALT = 'fristen-feed'


def feed_token(organisation):
    """Signierter, nicht-ablaufender Token für die abonnierbare Feed-URL.

    DER TOKEN TRÄGT DIE VERWALTUNG (18.08.2026). Vorher signierte er die
    Konstante `'fristen'` — derselbe Token galt damit für JEDE Verwaltung.
    Mit einer war das folgenlos; ab der zweiten hätte ein Abonnent von A den
    Kalender von B abrufen können, und in den Fristen stehen Mieternamen.

    Der Token ist kein Geheimnis pro Nutzer, sondern pro Verwaltung: Wer ihn
    hat, sieht deren Fristen. Das ist die bewusste Zusage einer abonnierbaren
    URL ohne Anmeldung — sie darf nur nicht über die Mandantengrenze reichen.

    Alte Tokens werden ungültig; bestehende Kalender-Abonnements müssen einmal
    neu eingerichtet werden. Das ist der Preis dafür, dass der Token vorher
    nicht sagte, wessen Kalender er öffnet.
    """
    pk = getattr(organisation, 'pk', organisation)
    return signing.Signer(salt=FEED_SALT).sign(f'fristen:{pk}')


def organisation_aus_token(token):
    """Die Verwaltung zu einem Feed-Token — oder None.

    Gibt die Organisation zurück statt eines Wahrheitswerts: Der Aufrufer
    braucht sie, um den Mandantenkontext zu setzen, und ein `True` hätte ihn
    genau darüber im Unklaren gelassen, wessen Fristen er gleich ausliefert.
    """
    from crm.models import Organisation
    try:
        roh = signing.Signer(salt=FEED_SALT).unsign(token or '')
    except signing.BadSignature:
        return None
    if not roh.startswith('fristen:'):
        return None
    # `alle_organisationen` gibt es an `Organisation` nicht — sie IST der
    # Mandant und wird nie gefiltert (siehe `OHNE_MANDANTENFILTER`).
    return Organisation.objects.filter(pk=roh.split(':', 1)[1]).first()


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
