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
    from collections import Counter, defaultdict

    from django.db.models import Count, Max

    from rentals.models import Mietvertrag
    # Je Kennzahl EINE Abfrage über alle Liegenschaften (vorher fünf je Liegenschaft: 69 -> 169 bei 25 Häusern).
    zaehler = Counter()
    for feld in ('einheit__liegenschaft', 'liegenschaft'):
        for lg_id, n in (Zaehler.objects.exclude(**{f'{feld}__isnull': True}).order_by()
                         .values_list(feld).annotate(n=Count('pk'))):
            zaehler[lg_id] += n
    letzter = dict(AktivitaetsLog.objects.filter(aktion=AKTION, ziel_typ='liegenschaft').order_by()
                   .values_list('ziel_id').annotate(z=Max('zeitpunkt')))
    empfaenger = defaultdict(set)                       # wie `_empfaenger`: aktive Mieter mit Adresse und Zugang
    for lg_id, mieter_id in (Mietvertrag.objects.filter(status='aktiv', mieter__benutzer__isnull=False)
                             .exclude(mieter__email='').exclude(mieter__email__isnull=True).order_by()
                             .values_list('einheit__liegenschaft_id', 'mieter_id')):
        empfaenger[lg_id].add(mieter_id)
    offen = defaultdict(set)
    for lg_id, anfrage_id in (Aenderungsanfrage.objects
                              .filter(art=Aenderungsanfrage.ART_ZAEHLERSTAND, status=Aenderungsanfrage.STATUS_OFFEN)
                              .order_by().values_list('mieter__vertraege__einheit__liegenschaft_id', 'pk')):
        offen[lg_id].add(anfrage_id)
    zeilen = [{'lg': lg, 'zaehler': zaehler[lg.pk], 'empfaenger': len(empfaenger[lg.pk]),
               'letzter': letzter.get(lg.pk), 'offen': len(offen[lg.pk])}
              for lg in Liegenschaft.objects.order_by('strasse')]
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
