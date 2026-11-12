# core/views/fw/ablesung.py
"""«Ablesung»: Die Verwaltung bittet die Mieterschaft einer Liegenschaft, ihre Zähler abzulesen und im Portal zu melden.

Der Aufruf geht per Mail an alle aktiven Mieter der Liegenschaft, die eine Adresse und einen Portalzugang haben; jede Meldung
kommt als Anfrage (`core/services/anfragen.py`) und zählt erst nach der Bestätigung. Der Aufruf steht im Logbuch; die Seite
zeigt, wann zuletzt aufgerufen wurde und wie viele Meldungen auf Bestätigung warten.
"""
from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext, override

from core.auth import SCHREIB_ROLLEN, log_aktion, rolle_erforderlich
from core.models import AktivitaetsLog, Aenderungsanfrage

from ._basis import _global_filter

SEITE = '/neu/ablesung/'
AKTION = 'Ablese-Aufruf gesendet'


def _empfaenger(liegenschaft):
    """Aktive Mieter der Liegenschaft mit E-Mail-Adresse und Portalzugang (je Person einmal)."""
    from rentals.models import Mietvertrag
    gesehen, liste = set(), []
    for v in Mietvertrag.objects.filter(einheit__liegenschaft=liegenschaft, status='aktiv').select_related('mieter'):
        m = v.mieter
        if m and m.pk not in gesehen and m.email and m.benutzer_id:
            gesehen.add(m.pk)
            liste.append(m)
    return liste


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ablesung(request):
    from portfolio.models import Liegenschaft, Zaehler
    zeilen = []
    offen = Aenderungsanfrage.objects.filter(art=Aenderungsanfrage.ART_ZAEHLERSTAND, status=Aenderungsanfrage.STATUS_OFFEN)
    for lg in Liegenschaft.objects.order_by('strasse'):
        n_zaehler = Zaehler.objects.filter(einheit__liegenschaft=lg).count() + Zaehler.objects.filter(liegenschaft=lg).count()
        letzter = (AktivitaetsLog.objects.filter(aktion=AKTION, ziel_typ='liegenschaft', ziel_id=lg.pk)
                   .order_by('-zeitpunkt').first())
        zeilen.append({'lg': lg, 'zaehler': n_zaehler, 'empfaenger': len(_empfaenger(lg)),
                       'letzter': letzter.zeitpunkt if letzter else None,
                       'offen': offen.filter(mieter__vertraege__einheit__liegenschaft=lg).distinct().count()})
    return render(request, 'fw/ablesung.html', {**_global_filter(request), 'nav': 'heute', 'zeilen': zeilen})


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ablesung_aufruf(request, pk):
    from core.utils.email_service import send_ticket_email
    from portfolio.models import Liegenschaft
    lg = get_object_or_404(Liegenschaft.objects.all(), pk=pk)
    if request.method != 'POST':
        return redirect(SEITE)
    gesendet = 0
    link = f"{settings.PORTAL_BASE_URL.rstrip('/')}/mieter/zaehler/"
    for m in _empfaenger(lg):
        with override((getattr(m, 'sprache', '') or 'de')[:2] if (getattr(m, 'sprache', '') or 'de')[:2] in ('de', 'fr', 'it', 'en') else 'de'):
            text = (gettext('Guten Tag') + ',\n\n'
                    + gettext('bitte lesen Sie Ihre Zähler ab und melden Sie die Stände im Mieterportal:') + f'\n{link}\n\n'
                    + gettext('Die Verwaltung bestätigt Ihre Meldung. Vielen Dank.'))
            betreff = gettext('Bitte Zählerstände ablesen')
        if send_ticket_email(m.email, betreff, text, organisation=lg.organisation):
            gesendet += 1
    log_aktion(request, AKTION, str(lg), f'{gesendet} Mail(s)', ziel=lg, kategorie='sicherheit')
    messages.success(request, gettext('Der Aufruf ging an %(n)s Mieter.') % {'n': gesendet})
    return redirect(SEITE)
