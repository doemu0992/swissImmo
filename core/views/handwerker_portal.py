# core/views/handwerker_portal.py
"""Handwerkerportal: ein Auftrag, ein geheimer Link, kein Konto (Modul 3, E6).

ÖFFENTLICHER EINSTIEGSPUNKT — bewusst ohne `rolle_erforderlich`. Wer den Link
hat, sieht genau diesen einen Auftrag: Adresse, Einheit, Zutritt, Fotos, das
Auftrags-PDF und — solange der Auftrag offen ist — die Telefonnummer des
Melders. Nichts sonst: keine Navigation, keine anderen Aufträge, keine Liste.

Die Schranken, in dieser Reihenfolge:

1. **Sperre nach Fehlversuchen** je IP. Wer Tokens rät, bekommt nach
   `FEHLVERSUCHE` erfolglosen Versuchen eine Stunde lang nur noch 404 —
   auch für einen gültigen Link.
2. **Rate-Limit** je IP über alle Anfragen (429).
3. **Lookup nur über den Hash** (`tickets.handwerker_zugang.auftrag_zum_token`),
   über `alle_organisationen`, weil es keinen Mandantenkontext gibt. Jeder
   Fehler — unbekannt, falsch, abgelaufen, widerrufen — ist derselbe 404.
4. Danach läuft alles im **Kontext der Organisation des Auftrags**
   (`kontext_des_objekts`). Fotos und Dateien kommen nur über diesen Auftrag,
   nie über einen Pfad aus der Anfrage.
5. Antwortköpfe: `X-Robots-Tag: noindex`, `Referrer-Policy: no-referrer`
   (der Token steht in der Adresse), kein Cache (`never_cache`).

Ist der Auftrag abgeschlossen, ist die Seite nur noch lesend: Jede Aktion wird
abgewiesen, Telefonnummer und Auftrags-PDF (das sie enthält) entfallen.
"""
import logging
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext
from django.views.decorators.cache import never_cache
from django.views.defaults import page_not_found

logger = logging.getLogger(__name__)

#: Erfolglose Token-Versuche je IP und Stunde, danach nur noch 404.
FEHLVERSUCHE = 10
FEHLVERSUCHE_FENSTER = 3600
#: Anfragen je IP in zehn Minuten (Seite, Fotos, Aktionen zusammen).
ANFRAGEN = 120
ANFRAGEN_FENSTER = 600
#: Ein Protokolleintrag «geöffnet» je Auftrag und IP und Stunde — sonst füllt
#: jedes Neuladen das Aktivitätslog.
OEFFNEN_LOG_FENSTER = 3600


def _koepfe(antwort):
    antwort['X-Robots-Tag'] = 'noindex, nofollow'
    antwort['Referrer-Policy'] = 'no-referrer'
    return antwort


def _nicht_gefunden(request):
    return _koepfe(page_not_found(request, Http404()))


def _mit_auftrag(view):
    """Rate-Limit, Lookup über den Hash, Kontext der Verwaltung des Auftrags."""
    @wraps(view)
    def gehuellt(request, token, *args, **kwargs):
        from core.tenancy import kontext_des_objekts
        from core.utils.throttle import client_ip, fehlversuch, ist_gesperrt, rate_limit
        from tickets.handwerker_zugang import auftrag_zum_token

        ip = client_ip(request)
        fehl_key = f'hw-link-fehl:{ip}'
        if ist_gesperrt(fehl_key, FEHLVERSUCHE):
            return _nicht_gefunden(request)
        if not rate_limit(f'hw-link:{ip}', ANFRAGEN, ANFRAGEN_FENSTER):
            return _koepfe(HttpResponse(
                gettext('Zu viele Anfragen. Bitte versuchen Sie es später erneut.'),
                status=429, content_type='text/plain; charset=utf-8'))
        auftrag = auftrag_zum_token(token)
        if auftrag is None:
            fehlversuch(fehl_key, FEHLVERSUCHE_FENSTER)
            return _nicht_gefunden(request)
        with kontext_des_objekts(auftrag):
            return _koepfe(view(request, auftrag, token, *args, **kwargs))
    return never_cache(gehuellt)


def _protokoll(request, auftrag, aktion, details=''):
    from core.auth import log_aktion
    log_aktion(request, aktion, f"Ticket #{auftrag.ticket_id}",
               f"Auftrag #{auftrag.pk} · {auftrag.handwerker.firma}" + (f" · {details}" if details else ''),
               ziel=auftrag.ticket, kategorie='sicherheit')


def _betrag(roh):
    roh = (roh or '').replace("'", '').replace(' ', '').replace(',', '.').strip()
    if not roh:
        return None
    try:
        wert = Decimal(roh).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None
    return wert if wert > 0 else None


def _datei(request, feld):
    """Hochgeladene Datei, geprüft wie die Bewerbungsunterlagen: PDF oder Bild,
    am Inhalt erkannt, mit Grössengrenze (`core.utils.uploads.validiere_dokument`)."""
    from core.utils.uploads import validiere_dokument
    f = request.FILES.get(feld)
    if f is None:
        raise ValidationError(gettext('Bitte eine Datei wählen (PDF oder Bild).'))
    ok, fehler = validiere_dokument(f)
    if not ok:
        raise ValidationError(fehler)
    return f


def _melder_telefon(ticket):
    if ticket.tel_melder:
        return ticket.tel_melder
    m = ticket.gemeldet_von if ticket.gemeldet_von_id else None
    return (m.mobile or m.telefon_privat or '') if m else ''


def _fotos(ticket):
    """(Nummer, Foto) — die Nummer ist die Position, nicht die Datenbank-ID;
    `0` ist das Einzelfoto der Erstmeldung."""
    liste = [(0, ticket.foto)] if ticket.foto else []
    liste += [(f.pk, f.bild) for f in ticket.fotos.all() if f.bild]
    return liste


@_mit_auftrag
def handwerker_auftrag(request, auftrag, token):
    """Die Einzelseite des Auftrags; POST führt eine Aktion aus."""
    from tickets.handwerker_zugang import ist_abgeschlossen
    from tickets.meldung import ohne_kontaktblock
    from tickets import workflow

    abgeschlossen = ist_abgeschlossen(auftrag)
    ticket = auftrag.ticket

    if request.method == 'POST':
        if abgeschlossen:
            messages.error(request, gettext('Der Auftrag ist abgeschlossen — der Link ist nur noch lesbar.'))
            return redirect('handwerker_auftrag', token=token)
        aktion = request.POST.get('aktion', '')
        try:
            if aktion == 'termin':
                try:
                    wann = datetime.strptime(request.POST.get('termin', ''), '%Y-%m-%dT%H:%M')
                except ValueError:
                    raise ValidationError(gettext('Bitte Datum und Zeit angeben.'))
                wann = timezone.make_aware(wann)
                if wann < timezone.now():
                    raise ValidationError(gettext('Der Termin liegt in der Vergangenheit.'))
                workflow.termin_festlegen(auftrag, wann)
                messages.success(request, gettext('Termin gesetzt. Der Mieter erhält eine Mail mit Kalendereintrag.'))
            elif aktion == 'termin_bestaetigen':
                workflow.termin_bestaetigen(auftrag)
                messages.success(request, gettext('Termin bestätigt.'))
            elif aktion in workflow.HANDWERKER_MELDUNGEN:
                workflow.handwerker_meldet(auftrag, aktion)
                messages.success(request, gettext('Danke, die Verwaltung ist informiert.'))
            elif aktion == 'nachricht':
                workflow.nachricht_von_handwerker(auftrag, request.POST.get('text', '')[:4000])
                messages.success(request, gettext('Nachricht an die Verwaltung gesendet.'))
            elif aktion == 'offerte':
                betrag = _betrag(request.POST.get('betrag'))
                if betrag is None:
                    raise ValidationError(gettext('Bitte einen Betrag in CHF angeben.'))
                if workflow.offerte_erfassen(auftrag, betrag, _datei(request, 'datei')):
                    messages.success(request, gettext('Offerte erhalten. Sie braucht die Freigabe der Eigentümerschaft — die Verwaltung meldet sich.'))
                else:
                    messages.success(request, gettext('Offerte erhalten.'))
            elif aktion == 'rechnung':
                betrag = _betrag(request.POST.get('betrag'))
                if betrag is None:
                    raise ValidationError(gettext('Bitte einen Betrag in CHF angeben.'))
                workflow.rechnung_einreichen(auftrag, betrag, _datei(request, 'datei'))
                messages.success(request, gettext('Rechnung erhalten. Die Verwaltung prüft sie.'))
            else:
                raise ValidationError(gettext('Unbekannte Aktion.'))
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
            return redirect('handwerker_auftrag', token=token)
        _protokoll(request, auftrag, 'Handwerkerportal: Aktion', aktion)
        return redirect('handwerker_auftrag', token=token)

    # Ein Eintrag «geöffnet» je Auftrag, IP und Stunde.
    from core.tenancy import cache_key
    from core.utils.throttle import client_ip
    if cache.add(cache_key('hw-link-offen', auftrag.pk, client_ip(request)), 1, OEFFNEN_LOG_FENSTER):
        _protokoll(request, auftrag, 'Handwerker-Link geöffnet')

    lg = ticket.liegenschaft
    einheit = ticket.betroffene_einheit if ticket.betroffene_einheit_id else None
    hw = auftrag.handwerker
    verlauf = (ticket.nachrichten.filter(typ='handwerker_mail', empfaenger_handwerker=hw)
               .order_by('erstellt_am'))
    return render(request, 'core/handwerker_auftrag.html', {
        'auftrag': auftrag, 't': ticket, 'lg': lg, 'einheit': einheit, 'hw': hw,
        'token': token, 'abgeschlossen': abgeschlossen,
        'telefon': '' if abgeschlossen else _melder_telefon(ticket),
        'beschreibung': ohne_kontaktblock(ticket.beschreibung),
        'fotos': [nr for nr, _bild in _fotos(ticket)],
        'verlauf': verlauf,
        'termin_min': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
        'verwaltung': ticket.organisation,
    })


@_mit_auftrag
def handwerker_auftrag_pdf(request, auftrag, token):
    """Das Auftrags-PDF — nur solange der Auftrag offen ist: Es nennt Name,
    Telefon und E-Mail des Melders."""
    from core.services.handwerker_auftrag_pdf import generate_auftrag_pdf
    from tickets.handwerker_zugang import ist_abgeschlossen
    if ist_abgeschlossen(auftrag):
        return _nicht_gefunden(request)
    pdf = generate_auftrag_pdf(auftrag, auftrag.ticket.organisation)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Reparaturauftrag_{auftrag.pk}.pdf"'
    return resp


@_mit_auftrag
def handwerker_auftrag_foto(request, auftrag, token, nr):
    """Ein Foto DIESES Auftrags. `nr` wählt aus der Liste des Tickets — ein
    Foto eines anderen Tickets ist darüber nicht adressierbar."""
    bild = dict(_fotos(auftrag.ticket)).get(nr)
    if not bild:
        return _nicht_gefunden(request)
    try:
        datei = bild.open('rb')
    except (FileNotFoundError, OSError):
        return _nicht_gefunden(request)
    endung = os.path.splitext(bild.name.lower())[1]
    typ = {'.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif',
           '.heic': 'image/heic', '.heif': 'image/heif', '.bmp': 'image/bmp'}.get(endung, 'image/jpeg')
    resp = FileResponse(datei, content_type=typ)
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp
