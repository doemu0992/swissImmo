# core/views/fw/schaeden.py
#
# Schadensfaelle und Handwerkerauftraege: Meldung, Kosten, Fotos, Auftrag,
# Status, Antwort an den Mieter, Ersatzplanung.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Offener Posten, hier NICHT mitkorrigiert (Fund aus E1c): fw_schaden_detail
# setzt `gelesen = True` auch fuer die reine Leserolle, obwohl der Test
# test_ticket_gelesen_nur_mit_schreibrolle das ausgeschlossen hatte. Ein
# Ein-Zeilen-Fix -- und trotzdem nicht in einem Umzugs-PR.

import logging
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, TICKET_LESE_ROLLEN, TICKET_SCHREIB_ROLLEN,
                       VERWALTUNGS_ROLLEN)
from portfolio.models import Einheit, Liegenschaft
from stweg import bauteile as _stweg_bauteile
from rentals.models import Mietvertrag

logger = logging.getLogger(__name__)

from ._basis import _global_filter, _num
from core.auth import hauswart_darf_liegenschaft, ist_nur_hauswart


def _hauswart_pruefen(request, ticket):
    """403, wenn ein Hauswart eine Meldung fremder Liegenschaften anfasst."""
    from django.core.exceptions import PermissionDenied
    if not hauswart_darf_liegenschaft(request.user, ticket.liegenschaft_id):
        raise PermissionDenied('Diese Liegenschaft ist dem Hauswart nicht zugeordnet.')
from core.tenancy import aktuelle_organisation
from core.services.dokumentsprache import auf_deutsch


# ============================================================
# ETAPPE D: SCHADENSFÄLLE (Tickets)
# ============================================================

TICKET_PILL = {
    'neu':                   (gettext_lazy('Neu'),                'fw-krit-flaeche fw-kritisch'),
    'in_bearbeitung':        (gettext_lazy('In Bearbeitung'),     'fw-info-flaeche fw-info'),
    'warte_auf_mieter':      (gettext_lazy('Warte auf Mieter'),   'fw-warn-flaeche fw-warnton'),
    'warte_auf_handwerker':  (gettext_lazy('Warte auf Handwerker'),'fw-warn-flaeche fw-warnton'),
    'wartet_auf_rechnung':   (gettext_lazy('Wartet auf Rechnung'),'fw-warn-flaeche fw-warnton'),
    'erledigt':              (gettext_lazy('Erledigt'),           'fw-gut-flaeche fw-gut'),
}
PRIO_PILL = {
    'hoch':   (gettext_lazy('Hoch'),   'fw-krit-flaeche fw-kritisch'),
    'mittel': (gettext_lazy('Mittel'), 'fw-warn-flaeche fw-warnton'),
    'tief':   (gettext_lazy('Tief'),   'fw-flaeche2 fw-mutet'),
    'niedrig':(gettext_lazy('Tief'),   'fw-flaeche2 fw-mutet'),
}


@rolle_erforderlich(*TICKET_LESE_ROLLEN)
def fw_schaeden(request):
    """Schadensliste nach G9 — sortiert nach Befund, nicht nach Eingang.

    Vorher stand `-erstellt_am` allein: Der Wasserschaden von heute Morgen
    stand ueber der Meldung, die seit sechs Wochen ungelesen liegt.

    Die Sichten oben bilden die ARBEIT ab, nicht die Statustabelle. «Neu» und
    «In Bearbeitung» sind Systemzustaende; niemand beginnt den Tag mit «zeig
    mir alle in Bearbeitung». Der Feinfilter bleibt ueber `?status=`
    erreichbar — gespeicherte Adressen brechen also nicht.
    """
    from faelle.schaeden import streifen, zeilen
    from tickets.models import SchadenMeldung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    # `prefetch_related` ist hier keine Feinabstimmung, sondern die Bedingung
    # dafuer, dass die Seite ueberhaupt benutzbar bleibt: `_befunde` liest je
    # Meldung die Auftraege UND die Nachrichten. Ohne Vorladen sind das zwei
    # zusaetzliche Abfragen JE ZEILE.
    qs = (SchadenMeldung.objects
          .select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von')
          .prefetch_related('handwerker_auftraege', 'nachrichten'))
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)
    # Der Hauswart sieht nur die Meldungen seiner Liegenschaften.
    if ist_nur_hauswart(request.user):
        qs = qs.filter(liegenschaft__hauswarte=request.user)

    # Der Feinfilter der Vorfassung bleibt erhalten (gespeicherte Adressen).
    status_filter = request.GET.get('status', '')
    if status_filter in TICKET_PILL:
        qs = qs.filter(status=status_filter)
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(titel__icontains=q) | Q(beschreibung__icontains=q)
                       | Q(kategorie__icontains=q) | Q(liegenschaft__strasse__icontains=q))

    alle = zeilen(qs)
    kopf = streifen(alle)

    # Die Sicht wirkt NACH der Befundrechnung — der Kopf zeigt weiterhin den
    # ganzen Bestand. Wuerde er mitfiltern, stuende unter «Mit Befund» bei
    # aktiver Sicht immer die Zahl der gerade sichtbaren Zeilen.
    sicht = request.GET.get('sicht', 'offen' if not status_filter else '')
    if sicht == 'offen':
        rows = [z for z in alle if z['offen']]
    elif sicht == 'befund':
        rows = [z for z in alle if z['befunde']]
    elif sicht == 'wartet':
        rows = [z for z in alle if z['wartet']]
    elif sicht == 'erledigt':
        rows = [z for z in alle if not z['offen']]
    else:
        sicht = ''
        rows = alle

    for zeile in rows:
        t = zeile['t']
        zeile['s_label'], zeile['s_cls'] = TICKET_PILL.get(
            t.status, (t.status, 'fw-flaeche2 fw-mutet'))
        zeile['p_label'], zeile['p_cls'] = PRIO_PILL.get(
            (t.prioritaet or '').lower(),
            (t.prioritaet or 'Mittel', 'fw-flaeche2 fw-mutet'))
        zeile['objekt'] = (f"{t.liegenschaft.strasse}, {t.liegenschaft.ort}"
                           if t.liegenschaft_id else '—')
        zeile['melder'] = (t.gemeldet_von.display_name if t.gemeldet_von_id
                           else f"{t.melder_vorname or ''} {t.melder_nachname or ''}".strip()
                           or '—')

    from django.contrib import messages
    return render(request, 'fw/schaeden.html', {
        **basis, 'nav': 'schadensfaelle', 'rows': rows, 'kopf': kopf,
        'sicht': sicht, 'status_filter': status_filter, 'q': q,
        'gefiltert': len(rows) != len(alle),
        'sicht_chips': [('offen', gettext('Offen (%(n)s)') % {'n': kopf["offen"]}),
                        ('befund', gettext('Mit Befund (%(n)s)') % {'n': kopf["mit_befund"]}),
                        ('wartet', gettext('Wartet auf Dritte (%(n)s)') % {'n': kopf["wartet"]}),
                        ('erledigt', gettext('Erledigt')), ('', gettext('Alle'))],
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
        'stweg_bauteile': _stweg_bauteile.auswahl(),
        'kt_traeger': _stweg_bauteile.KOSTENTRAEGER_CHOICES,
        'einheiten': Einheit.objects.select_related('liegenschaft')
                     .order_by('liegenschaft__strasse', 'bezeichnung'),
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_schaden_kosten(request):
    """Reparaturkosten-Übersicht je Liegenschaft: Kostenschätzungen (offen) und
    effektive Kosten aus den Handwerker-Aufträgen — das Reparaturbudget im Blick."""
    from tickets.models import SchadenMeldung, HandwerkerAuftrag
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    try:
        jahr = int(request.GET.get('jahr') or 0)
    except ValueError:
        jahr = 0

    auf = (HandwerkerAuftrag.objects.exclude(status='storniert')
           .select_related('ticket__liegenschaft', 'handwerker'))
    if aktive_lg:
        auf = auf.filter(ticket__liegenschaft=aktive_lg)
    if jahr:
        auf = auf.filter(beauftragt_am__year=jahr)

    gruppen = {}
    for a in auf:
        lg = a.ticket.liegenschaft if a.ticket_id else None
        key = lg.id if lg else 0
        g = gruppen.setdefault(key, {'lg': lg, 'auftraege': 0, 'geschaetzt': Decimal('0.00'),
                                     'effektiv': Decimal('0.00'), 'offen': Decimal('0.00')})
        g['auftraege'] += 1
        gesch = a.kosten_geschaetzt or Decimal('0.00')
        eff = a.kosten_effektiv
        g['geschaetzt'] += gesch
        if eff is not None:
            g['effektiv'] += eff
        else:
            g['offen'] += gesch   # noch nicht abgerechnet → offene Kostenschätzung

    # Schaden-Zähler je Liegenschaft
    schaeden = SchadenMeldung.objects.all()
    if aktive_lg:
        schaeden = schaeden.filter(liegenschaft=aktive_lg)
    if jahr:
        schaeden = schaeden.filter(erstellt_am__year=jahr)
    s_total, s_offen = {}, {}
    for t in schaeden.values('liegenschaft_id', 'status'):
        k = t['liegenschaft_id'] or 0
        s_total[k] = s_total.get(k, 0) + 1
        if t['status'] != 'erledigt':
            s_offen[k] = s_offen.get(k, 0) + 1

    rows = []
    for key, g in gruppen.items():
        g['schaeden'] = s_total.get(key, 0)
        g['schaeden_offen'] = s_offen.get(key, 0)
        g['name'] = f"{g['lg'].strasse}, {g['lg'].ort}" if g['lg'] else '— ohne Liegenschaft —'
        # Gesamt (effektiv + offen) IN PYTHON summieren — der Template-Filter |add
        # coerct Decimals nach int und schneidet die Rappen ab (Live-Test J).
        g['gesamt'] = g['effektiv'] + g['offen']
        rows.append(g)
    rows.sort(key=lambda g: (-g['gesamt'], g['name'].lower()))

    total = {
        'auftraege': sum(g['auftraege'] for g in rows),
        'geschaetzt': sum((g['geschaetzt'] for g in rows), Decimal('0.00')),
        'effektiv': sum((g['effektiv'] for g in rows), Decimal('0.00')),
        'offen': sum((g['offen'] for g in rows), Decimal('0.00')),
        'schaeden': sum(g['schaeden'] for g in rows),
    }
    total['gesamt'] = total['effektiv'] + total['offen']
    return render(request, 'fw/schaden_kosten.html', {
        **basis, 'nav': 'schadensfaelle', 'rows': rows, 'total': total,
        'jahr': jahr, 'jahre': list(range(heute.year, heute.year - 5, -1)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_neu(request):
    """Intern erfassten Schaden (z.B. telefonisch gemeldet) anlegen — sendet dem
    Melder (falls E-Mail) automatisch die Eingangsbestätigung."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung
    from core.services.ticket_workflow import vorlage_text
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_schaeden')

    titel = (request.POST.get('titel') or '').strip()
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    if not titel or not lg:
        messages.error(request, gettext('Titel und Liegenschaft sind erforderlich.'))
        return redirect('fw_schaeden')

    einheit = Einheit.objects.filter(id=request.POST.get('einheit_id') or None).first() if request.POST.get('einheit_id') else None
    bauteil = (request.POST.get('bauteil') or '').strip()
    kostentraeger = (request.POST.get('kostentraeger') or '').strip()
    if lg.ist_stweg:                                    # STWEG: ohne Deklaration wird kein Schaden erfasst
        from stweg import bauteile
        fehler = []
        if bauteil not in bauteile.BAUTEILE or kostentraeger not in dict(bauteile.KOSTENTRAEGER_CHOICES):
            fehler.append(gettext('Bei einer STWEG bitte Bauteil und Kostenträger (Sonderrecht oder gemeinschaftlich) '
                                  'angeben.'))
        elif bauteile.sperre(bauteil, kostentraeger):
            fehler.append(bauteile.sperre(bauteil, kostentraeger))
        if fehler:
            for f in fehler:
                messages.error(request, '⛔ ' + f)
            return redirect('fw_schaeden')
    t = SchadenMeldung.objects.create(
        liegenschaft=lg, betroffene_einheit=einheit,
        bauteil=bauteil if lg.ist_stweg else '', kostentraeger=kostentraeger if lg.ist_stweg else '',
        titel=titel, beschreibung=(request.POST.get('beschreibung') or '').strip(),
        kategorie=(request.POST.get('kategorie') or '').strip(),
        melder_vorname=(request.POST.get('melder_vorname') or '').strip(),
        melder_nachname=(request.POST.get('melder_nachname') or '').strip(),
        email_melder=(request.POST.get('email_melder') or '').strip(),
        tel_melder=(request.POST.get('tel_melder') or '').strip(),
        prioritaet=request.POST.get('prioritaet', 'mittel'), status='neu',
    )
    # Fotos (Mehrfach-Upload) anhängen
    from tickets.models import SchadenFoto
    for f in request.FILES.getlist('fotos'):
        SchadenFoto.objects.create(schaden=t, bild=f, hochgeladen_von=request.user)
    ok = False
    if t.email_melder:
        from crm.models import Vorlage
        from core.services.ticket_workflow import ticket_kontext
        betreff = f"Eingangsbestätigung: {t.titel} (Ticket #{t.id})"
        v = Vorlage.objects.filter(kategorie='ticket_eingang').first()
        if v and v.inhalt:
            k = ticket_kontext(t)
            body = v.inhalt
            for kk, vv in k.items():
                body = body.replace('{' + kk + '}', str(vv))
            if v.betreff:
                betreff = v.betreff
                for kk, vv in k.items():
                    betreff = betreff.replace('{' + kk + '}', str(vv))
        else:
            body = (f"Guten Tag\n\nWir haben Ihre Schadenmeldung '{t.titel}' erhalten (Ticket #{t.id}) "
                    f"und kümmern uns darum. Wir melden uns, sobald ein Handwerker beauftragt wurde.\n\n"
                    f"Freundliche Grüsse\nIhre Liegenschaftsverwaltung")
        ok = send_ticket_email(t.email_melder, betreff, body)

    log_aktion(request, "Schaden intern erfasst", f"Ticket #{t.id}", titel)
    if ok:
        meldung = gettext('Ticket #%(id)s erstellt · Eingangsbestätigung an %(email)s gesendet.') % {
            'id': t.id, 'email': t.email_melder}
    else:
        meldung = gettext('Ticket #%(id)s erstellt.') % {'id': t.id}
    messages.success(request, '✅ ' + meldung)
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(*TICKET_LESE_ROLLEN)
def fw_schaden_detail(request, pk):
    from tickets.models import SchadenMeldung
    t = get_object_or_404(
        SchadenMeldung.objects.select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von'), id=pk)
    _hauswart_pruefen(request, t)
    basis = _global_filter(request)

    # Beim Öffnen als gelesen markieren (entfernt den Sidebar-Badge-Zähler)
    if not t.gelesen:
        t.gelesen = True
        t.save(update_fields=['gelesen'])

    s_label, s_cls = TICKET_PILL.get(t.status, (t.status, 'fw-flaeche2 fw-mutet'))
    p_label, p_cls = PRIO_PILL.get((t.prioritaet or '').lower(), (t.prioritaet or 'Mittel', 'fw-flaeche2 fw-mutet'))
    nachrichten = t.nachrichten.order_by('erstellt_am')
    auftraege = t.handwerker_auftraege.select_related('handwerker').order_by('-beauftragt_am')
    melder = (t.gemeldet_von.display_name if t.gemeldet_von_id
              else f"{t.melder_vorname or ''} {t.melder_nachname or ''}".strip() or '—')

    auftraege = list(auftraege)
    kosten_geschaetzt = sum((a.kosten_geschaetzt or Decimal('0')) for a in auftraege)
    kosten_effektiv = sum((a.kosten_effektiv or Decimal('0')) for a in auftraege)

    from crm.models import Handwerker
    from core.services.ticket_workflow import vorlage_text
    handwerker_liste = Handwerker.objects.all().order_by('firma')
    # Auftragstext-Vorschlag (Vorlage ticket_handwerker) für das Beauftragen-Formular
    _, auftrag_vorschlag = vorlage_text('ticket_handwerker', t)
    melder_email = t.email_melder or (t.gemeldet_von.email if t.gemeldet_von_id else '')

    fotos = list(t.fotos.all())
    # Raumbuch-Elemente des betroffenen Objekts (zum Verknüpfen)
    from portfolio.models import Ausstattung
    ausstattung_elemente = (list(Ausstattung.objects.filter(einheit=t.betroffene_einheit))
                            if t.betroffene_einheit_id else [])
    # Etappe 4b.3: Reiter aus dem Aktenregister statt aus dieser View.
    # Die Panels in fw/schaden_detail.html sind auf denselben Satz umbenannt —
    # beides muss gemeinsam wandern, sonst zeigt ein Reiter auf kein Panel und
    # der Klick hinterlaesst eine leere Seite (`faelle/test_reiter_panels.py`).
    from django.contrib.contenttypes.models import ContentType

    from faelle.akten import aus_alt as _reiter_aus_alt
    from faelle.models import Fall
    from core.tenancy import aktuelle_organisation as _akt_org

    schaden_faelle = list(
        Fall.objects.filter(akte_typ=ContentType.objects.get_for_model(SchadenMeldung),
                            akte_id=t.id)
        .select_related('fallart', 'zustaendig').order_by('-eroeffnet_am'))

    # Kennzahlen des Aktenkopfs (4b.3). Vier Werte, die zusammen sagen, ob
    # dieser Schaden gut dasteht: was er kostet, wer dran ist, wie lange er
    # laeuft und wann zuletzt etwas geschah.
    offen_seit = (timezone.localdate() - t.erstellt_am.date()).days if t.erstellt_am else None
    letzte_nachricht = nachrichten.last()

    # Verknüpfbare Rechnungen: dieselbe Liegenschaft (oder ohne), nicht storniert, an keinem
    # Auftrag hängend. `objects` filtert auf die eigene Verwaltung.
    from finance.models import KreditorenRechnung
    rechnungen_frei = []
    if any(a.status != 'storniert' and not a.kreditoren_rechnung_id for a in auftraege):
        rechnungen_frei = list(
            KreditorenRechnung.objects.filter(handwerker_auftraege__isnull=True)
            .exclude(status='storniert')
            .filter(Q(liegenschaft=t.liegenschaft) | Q(liegenschaft__isnull=True))
            .order_by('-id')[:50])

    tab_liste = _reiter_aus_alt('schaden', [
        ('uebersicht', 'Übersicht', None),
        ('verlauf', 'Verlauf', nachrichten.count() or None),
        ('handwerker', 'Handwerker & Kosten', len(auftraege) or None),
        ('fotos', 'Fotos', len(fotos) or None),
    ], organisation=getattr(request, 'organisation', None) or _akt_org())
    from django.contrib import messages
    kt = {}
    if t.liegenschaft.ist_stweg:
        from stweg import bauteile
        kt = {'stweg_bauteile': bauteile.auswahl(), 'kt_probleme': bauteile.probleme(t),
              'kt_traeger': bauteile.KOSTENTRAEGER_CHOICES}
    return render(request, 'fw/schaden_detail.html', {
        **basis, **kt, 'nav': 'schadensfaelle', 't': t,
        's_label': s_label, 's_cls': s_cls, 'p_label': p_label, 'p_cls': p_cls,
        'nachrichten': nachrichten, 'auftraege': auftraege, 'melder': melder,
        'kosten_geschaetzt': kosten_geschaetzt, 'kosten_effektiv': kosten_effektiv,
        'fotos': fotos,
        'schaden_faelle': schaden_faelle,
        'offen_seit': offen_seit, 'letzte_nachricht': letzte_nachricht,
        'tab_liste': tab_liste,
        'ausstattung_elemente': ausstattung_elemente,
        'handwerker_liste': handwerker_liste, 'auftrag_vorschlag': auftrag_vorschlag,
        'melder_email': melder_email, 'status_wahl': TICKET_PILL,
        'rechnungen_frei': rechnungen_frei,
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_ausstattung(request, pk):
    """Verknüpft eine Schadenmeldung mit einem Raumbuch-Element (oder löst die
    Verknüpfung). Baut die Reparaturhistorie/Lebenszykluskosten am Element auf."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung
    from portfolio.models import Ausstattung
    from core.auth import log_aktion
    t = get_object_or_404(SchadenMeldung, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/schaeden/{t.id}/')
    aid = (request.POST.get('ausstattung_id') or '').strip()
    if aid.isdigit() and t.betroffene_einheit_id:
        el = Ausstattung.objects.filter(id=int(aid), einheit=t.betroffene_einheit).first()
        t.ausstattung = el
        t.save(update_fields=['ausstattung'])
        if el:
            log_aktion(request, "Schaden mit Element verknüpft", f"Ticket #{t.id}", f"{el.raum} · {el.kategorie}")
            messages.success(request, '✅ ' + gettext('Mit «%(kategorie)s» (%(raum)s) verknüpft.') % {'kategorie': el.kategorie, 'raum': el.raum})
    else:
        t.ausstattung = None
        t.save(update_fields=['ausstattung'])
        messages.success(request, gettext('Verknüpfung aufgehoben.'))
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_ersatzplanung(request):
    """Garantie- & Ersatzplanung: Raumbuch-Elemente nach Restnutzungsdauer
    (Lebensdauertabelle), Jahres-Ersatzbudget und Lebenszykluskosten.
    ?pdf=1 → Budget-Report als PDF."""
    from core.services.ersatzplanung import berechne_ersatzplanung, fonds_deckung
    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    daten = berechne_ersatzplanung(aktive_lg=aktive_lg, heute=heute)
    deckung = fonds_deckung(aktive_lg, daten['budget_total'], daten['horizont_jahre'])

    if request.GET.get('pdf') == '1':
        from django.http import HttpResponse
        from crm.models import Organisation
        from core.services.ersatzplanung_pdf import generate_ersatzplanung_pdf
        lg_name = (f"{aktive_lg.strasse}, {aktive_lg.ort}" if aktive_lg
                   else "Alle Liegenschaften")
        pdf = generate_ersatzplanung_pdf(daten, lg_name, verwaltung=aktuelle_organisation(),
                                         deckung=deckung)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = 'inline; filename="Ersatzplanung.pdf"'
        return resp

    f = request.GET.get('status', '')
    rows = [r for r in daten['rows'] if not f or f == r['status']]

    chips = [('', gettext('Alle')), ('faellig', gettext('Ersatz fällig')),
             ('bald', gettext('Bald fällig')), ('ok', gettext('Im Nutzungszeitraum')),
             ('unbekannt', gettext('Keine Datenbasis'))]
    return render(request, 'fw/ersatzplanung.html', {
        **basis, 'nav': 'assets', 'rows': rows, 'status_filter': f, 'chips': chips,
        'n_faellig': daten['n_faellig'], 'n_bald': daten['n_bald'],
        'n_ok': daten['n_ok'], 'n_unbekannt': daten['n_unbekannt'],
        'jahres_budget': daten['jahres_budget'], 'budget_total': daten['budget_total'],
        'horizont_jahre': daten['horizont_jahre'], 'deckung': deckung,
        'anzahl': len(rows),
        # Wie viele Zeilen NICHT im Budget stehen, weil kein Neuwert erfasst
        # ist (4b.20: Geraete). Die Zahl gehoert auf die Seite — ein Budget,
        # dem die Heizung fehlt, sieht sonst aus wie ein vollstaendiges.
        'budget_ohne_neuwert': daten['budget_ohne_neuwert'],
        'n_geraete': daten['n_geraete'],
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_foto_upload(request, pk):
    """Hängt ein oder mehrere Fotos an eine Schadenmeldung (Dokumentation)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung, SchadenFoto
    from core.auth import log_aktion
    from core.utils.uploads import validiere_bild
    t = get_object_or_404(SchadenMeldung, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/schaeden/{t.id}/')
    dateien = request.FILES.getlist('fotos')
    n = 0
    abgelehnt = 0
    for f in dateien:
        ok, _fehler = validiere_bild(f)
        if not ok:
            abgelehnt += 1
            continue
        SchadenFoto.objects.create(schaden=t, bild=f, hochgeladen_von=request.user)
        n += 1
    if n:
        log_aktion(request, "Schaden-Fotos hochgeladen", f"Ticket #{t.id}", f"{n} Foto(s)")
        messages.success(request, '✅ ' + gettext('%(n)s Foto(s) hinzugefügt.') % {'n': n})
    if abgelehnt:
        messages.error(request, gettext('%(abgelehnt)s Datei(en) abgelehnt (kein gültiges Bild oder zu gross).') % {'abgelehnt': abgelehnt})
    elif not n:
        messages.error(request, gettext('Keine Datei ausgewählt.'))
    return redirect(f'/neu/schaeden/{t.id}/#sc-fotos')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_foto_loeschen(request, pk):
    """Entfernt ein einzelnes Schaden-Foto."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenFoto
    from core.auth import log_aktion
    foto = get_object_or_404(SchadenFoto.objects.select_related('schaden'), id=pk)
    tid = foto.schaden_id
    if request.method == 'POST':
        foto.delete()
        log_aktion(request, "Schaden-Foto gelöscht", f"Ticket #{tid}", '')
        messages.success(request, gettext('Foto entfernt.'))
    return redirect(f'/neu/schaeden/{tid}/#sc-fotos')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_loeschen(request, pk):
    """Schadensmeldung (Ticket) löschen — inkl. Fotos/Nachrichten (cascade)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung
    from core.auth import log_aktion
    t = get_object_or_404(SchadenMeldung, id=pk)
    if request.method == 'POST':
        titel = t.titel or (t.beschreibung or '')[:40]
        t.delete()
        log_aktion(request, "Schadensmeldung gelöscht", titel, '')
        messages.success(request, '🗑️ ' + gettext('Schadensmeldung gelöscht.'))
    return redirect('/neu/schaeden/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_auftrag(request, pk):
    """Handwerker beauftragen — automatisiert: Auftrag anlegen, Mail an Handwerker
    (aus Vorlage) + Info-Mail an Melder, Status → in Bearbeitung, Verlaufseintrag."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung, HandwerkerAuftrag, TicketNachricht
    from crm.models import Handwerker
    from core.services.ticket_workflow import vorlage_text
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect(f'/neu/schaeden/{pk}/')
    t = get_object_or_404(SchadenMeldung.objects.select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von'), id=pk)
    hw = get_object_or_404(Handwerker, id=request.POST.get('handwerker_id'))
    auftragstext = (request.POST.get('auftragstext') or '').strip()

    from django.core.exceptions import ValidationError
    from tickets.workflow import auftrag_vergeben
    try:
        res = auftrag_vergeben(t, hw, auftragstext)
    except ValidationError as e:
        messages.error(request, '⛔ ' + ' '.join(e.messages))
        return redirect(f'/neu/schaeden/{t.id}/')
    hw_ok, melder_ok = res['handwerker_versendet'], res['melder_informiert']
    melder_email = t.email_melder or (t.gemeldet_von.email if t.gemeldet_von_id else '')

    log_aktion(request, "Handwerker beauftragt", f"Ticket #{t.id}", f"{hw.firma}")
    hinweise = []
    hinweise.append(gettext('Mail an Handwerker gesendet') if hw_ok else (
        gettext('Handwerker ohne E-Mail') if not hw.email else gettext('Mail an Handwerker fehlgeschlagen')))
    hinweise.append(gettext('Melder informiert') if melder_ok else (
        gettext('Melder ohne E-Mail') if not melder_email else gettext('Melder-Mail fehlgeschlagen')))
    messages.success(request, '✅ ' + gettext('%(firma)s beauftragt · Status: In Bearbeitung · %(hinweise)s.')
                     % {'firma': hw.firma, 'hinweise': ' · '.join(hinweise)})
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(*TICKET_SCHREIB_ROLLEN)
def fw_schaden_kostentraeger(request, pk):
    """STWEG: Bauteil und Kostenträger (Sonderrecht / gemeinschaftlich) deklarieren. «Sonderrecht» auf einem zwingend
    gemeinschaftlichen Bauteil (Dach, Fassade, Fenster aussen …) wird abgewiesen (Art. 712b ZGB)."""
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.shortcuts import redirect
    from tickets.models import SchadenMeldung
    if request.method != 'POST':
        return redirect(f'/neu/schaeden/{pk}/')
    t = get_object_or_404(SchadenMeldung.objects.select_related('liegenschaft'), id=pk)
    if not t.liegenschaft.ist_stweg:
        messages.error(request, gettext('Bauteil und Kostenträger gelten nur bei einer Stockwerkeigentümergemeinschaft.'))
        return redirect(f'/neu/schaeden/{pk}/')
    t.bauteil = (request.POST.get('bauteil') or '').strip()
    t.kostentraeger = (request.POST.get('kostentraeger') or '').strip()
    try:
        from stweg import bauteile
        if t.bauteil not in bauteile.BAUTEILE or t.kostentraeger not in dict(bauteile.KOSTENTRAEGER_CHOICES):
            raise ValidationError(gettext('Bitte Bauteil und Kostenträger wählen.'))
        t.save(update_fields=['bauteil', 'kostentraeger'])
        messages.success(request, gettext('Kostenträger gespeichert.'))
    except ValidationError as e:
        messages.error(request, '⛔ ' + ' '.join(e.messages))
    return redirect(f'/neu/schaeden/{pk}/')


@rolle_erforderlich(*TICKET_SCHREIB_ROLLEN)
def fw_schaden_status(request, pk):
    """Ticket-Status ändern; optional Melder automatisch informieren
    (bei „erledigt" die Erledigt-Vorlage)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung, TicketNachricht
    from core.services.ticket_workflow import vorlage_text
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect(f'/neu/schaeden/{pk}/')
    t = get_object_or_404(SchadenMeldung.objects.select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von'), id=pk)
    _hauswart_pruefen(request, t)
    neu = request.POST.get('status')
    if neu not in dict(SchadenMeldung.STATUS_CHOICES):
        messages.error(request, gettext('Ungültiger Status.'))
        return redirect(f'/neu/schaeden/{t.id}/')
    from django.core.exceptions import ValidationError
    from tickets.workflow import wechsle_status
    informieren = request.POST.get('melder_informieren') == 'on'
    melder_email = t.email_melder or (t.gemeldet_von.email if t.gemeldet_von_id else '')
    n_vorher = t.nachrichten.count()
    try:
        wechsle_status(t, neu, melder_informieren=informieren)
    except ValidationError as e:
        messages.error(request, '⛔ ' + ' '.join(e.messages))
        return redirect(f'/neu/schaeden/{t.id}/')
    melder_informiert = t.nachrichten.count() > n_vorher   # Service hat Mail protokolliert
    TicketNachricht.objects.create(ticket=t, absender_name="System", typ='system',
                                   nachricht=f"Status geändert: {auf_deutsch(t.get_status_display)}.", is_intern=True)

    info = ""
    if informieren and melder_informiert:
        info = f" · Melder informiert ({melder_email})"

    log_aktion(request, "Ticket-Status geändert", f"Ticket #{t.id}", auf_deutsch(t.get_status_display))
    messages.success(request, '✅ ' + gettext('Status: %(get_status_display)s%(info)s.') % {'get_status_display': t.get_status_display(), 'info': info})
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_antwort(request, pk):
    """Antwort/Nachricht an den Melder — als Verlaufseintrag + E-Mail."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung, TicketNachricht
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect(f'/neu/schaeden/{pk}/')
    t = get_object_or_404(SchadenMeldung.objects.select_related('liegenschaft', 'gemeldet_von'), id=pk)
    text = (request.POST.get('text') or '').strip()
    if not text:
        return redirect(f'/neu/schaeden/{t.id}/')

    absender = (request.user.get_full_name() or request.user.username or 'Verwaltung')
    TicketNachricht.objects.create(ticket=t, absender_name=absender, typ='antwort_senden',
                                   nachricht=text, is_von_verwaltung=True)
    if t.status == 'neu':
        t.status = 'in_bearbeitung'
        t.save()

    melder_email = t.email_melder or (t.gemeldet_von.email if t.gemeldet_von_id else '')
    ok = send_ticket_email(melder_email, f"Ihre Meldung (Ticket #{t.id})", text) if melder_email else False
    log_aktion(request, "Ticket-Antwort gesendet", f"Ticket #{t.id}", '')
    if ok:
        messages.success(request, '✅ ' + gettext('Antwort an %(melder_email)s gesendet.') % {'melder_email': melder_email})
    elif melder_email:
        messages.error(request, gettext('Antwort gespeichert, aber E-Mail-Versand fehlgeschlagen.'))
    else:
        messages.success(request, gettext('Antwort im Verlauf gespeichert (Melder ohne E-Mail).'))
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_auftrag_pdf(request, pk):
    """Reparaturauftrag (PDF) für einen Handwerker-Auftrag."""
    from django.http import HttpResponse
    from tickets.models import HandwerkerAuftrag
    from crm.models import Organisation
    from core.services.handwerker_auftrag_pdf import generate_auftrag_pdf
    a = get_object_or_404(
        HandwerkerAuftrag.objects.select_related('ticket__liegenschaft', 'ticket__betroffene_einheit', 'handwerker'),
        id=pk)
    # Der Reparaturauftrag geht an einen Handwerker und nennt den Auftraggeber —
    # das ist die Verwaltung des Tickets, nicht die erste im Bestand.
    pdf = generate_auftrag_pdf(a, a.ticket.organisation)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Reparaturauftrag_{a.id}.pdf"'
    return resp


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_auftrag_nachricht(request, pk):
    """Freitext-Mail an den Handwerker eines Auftrags (Antwort kommt ins Ticket zurück)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import HandwerkerAuftrag
    from tickets.workflow import nachricht_an_handwerker
    from core.auth import log_aktion
    a = get_object_or_404(HandwerkerAuftrag.objects.select_related('ticket', 'handwerker'), id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/schaeden/{a.ticket_id}/?tab=handwerker')
    text = (request.POST.get('text') or '').strip()
    if not text:
        messages.error(request, gettext('Bitte eine Nachricht eingeben.'))
    elif not a.handwerker.email:
        messages.error(request, gettext('Der Handwerker hat keine E-Mail-Adresse.'))
    elif nachricht_an_handwerker(a, text, absender=(request.user.get_full_name() or request.user.username)):
        log_aktion(request, "Nachricht an Handwerker", f"Ticket #{a.ticket_id}", a.handwerker.firma)
        messages.success(request, '✅ ' + gettext('Nachricht an %(firma)s gesendet.') % {'firma': a.handwerker.firma})
    else:
        messages.error(request, gettext('Versand fehlgeschlagen — die Nachricht steht im Verlauf.'))
    return redirect(f'/neu/schaeden/{a.ticket_id}/?tab=handwerker')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_auftrag_termin(request, pk):
    """Termin eines Auftrags setzen/verschieben oder absagen; Mieter und Handwerker
    bekommen Mail mit Kalendereintrag."""
    from datetime import datetime
    from django.core.exceptions import ValidationError
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import HandwerkerAuftrag
    from tickets.workflow import termin_festlegen, termin_absagen
    from core.auth import log_aktion
    a = get_object_or_404(HandwerkerAuftrag.objects.select_related('ticket', 'handwerker'), id=pk)
    ziel = f'/neu/schaeden/{a.ticket_id}/?tab=handwerker'
    if request.method != 'POST':
        return redirect(ziel)
    try:
        if request.POST.get('aktion') == 'absagen':
            termin_absagen(a)
            log_aktion(request, "Termin abgesagt", f"Ticket #{a.ticket_id}", a.handwerker.firma)
            messages.success(request, '✅ ' + gettext('Termin abgesagt, beide Seiten informiert.'))
        else:
            try:
                wann = datetime.strptime(request.POST.get('termin', ''), '%Y-%m-%dT%H:%M')
            except ValueError:
                raise ValidationError(gettext('Ungültiges Datum.'))
            termin_festlegen(a, wann)
            log_aktion(request, "Termin festgelegt", f"Ticket #{a.ticket_id}", a.handwerker.firma)
            messages.success(request, '✅ ' + gettext('Termin gesetzt, Mieter und Handwerker informiert.'))
    except ValidationError as e:
        messages.error(request, '⛔ ' + ' '.join(e.messages))
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_auftrag_rechnung(request, pk):
    """Bestehende Kreditorenrechnung mit dem Auftrag verknüpfen; optional das Ticket abschliessen."""
    from django.core.exceptions import ValidationError
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung
    from tickets.models import HandwerkerAuftrag
    from tickets.workflow import rechnung_verknuepfen
    from core.auth import log_aktion
    a = get_object_or_404(HandwerkerAuftrag.objects.select_related('ticket', 'handwerker'), id=pk)
    ziel = f'/neu/schaeden/{a.ticket_id}/?tab=handwerker'
    if request.method != 'POST':
        return redirect(ziel)
    try:
        try:
            rechnung_id = int(request.POST.get('rechnung_id') or 0)
        except ValueError:
            raise ValidationError(gettext('Bitte eine Rechnung wählen.'))
        kr = get_object_or_404(KreditorenRechnung.objects, id=rechnung_id)
        if kr.handwerker_auftraege.exclude(pk=a.pk).exists():
            raise ValidationError(gettext('Die Rechnung hängt schon an einem anderen Auftrag.'))
        rechnung_verknuepfen(a, kr, abschliessen=request.POST.get('abschliessen') == 'on')
        log_aktion(request, "Rechnung mit Auftrag verknüpft", f"Ticket #{a.ticket_id}", f"Kreditor #{kr.id}")
        a.ticket.refresh_from_db()
        if a.ticket.status == 'erledigt':
            messages.success(request, '✅ ' + gettext('Rechnung verknüpft — Ticket abgeschlossen.'))
        else:
            messages.success(request, '✅ ' + gettext('Rechnung verknüpft.'))
    except ValidationError as e:
        messages.error(request, '⛔ ' + ' '.join(e.messages))
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_auftrag_storno(request, pk):
    """Auftrag stornieren; der Handwerker erfährt es, ein Termin wird abgesagt."""
    from django.core.exceptions import ValidationError
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import HandwerkerAuftrag
    from tickets.workflow import auftrag_stornieren
    from core.auth import log_aktion
    a = get_object_or_404(HandwerkerAuftrag.objects.select_related('ticket', 'handwerker'), id=pk)
    ziel = f'/neu/schaeden/{a.ticket_id}/?tab=handwerker'
    if request.method != 'POST':
        return redirect(ziel)
    try:
        auftrag_stornieren(a, request.POST.get('grund', ''))
        log_aktion(request, "Auftrag storniert", f"Ticket #{a.ticket_id}", a.handwerker.firma)
        messages.success(request, '✅ ' + gettext('Auftrag storniert, Handwerker informiert.'))
    except ValidationError as e:
        messages.error(request, '⛔ ' + ' '.join(e.messages))
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_auftrag_kosten(request, pk):
    """Reparaturkosten auf einem Handwerker-Auftrag erfassen; optional eine
    Kreditorenrechnung erzeugen und verknüpfen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import HandwerkerAuftrag
    from finance.models import KreditorenRechnung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_schaeden')
    a = get_object_or_404(HandwerkerAuftrag.objects.select_related('ticket__liegenschaft', 'handwerker'), id=pk)

    def _dec(name):
        raw = _num(request.POST.get(name))
        if not raw:
            return None
        try:
            return Decimal(raw)
        except Exception:
            return None

    a.kosten_geschaetzt = _dec('kosten_geschaetzt')
    a.kosten_effektiv = _dec('kosten_effektiv')

    # Reparaturfreigabe anfordern: manuell oder ab Schwellenwert (CHF 1'000)
    REPARATUR_FREIGABE_SCHWELLE = Decimal('1000')
    freigabe_anfordern = request.POST.get('freigabe_anfordern') == 'on'
    ueber_schwelle = (a.kosten_geschaetzt or Decimal('0')) >= REPARATUR_FREIGABE_SCHWELLE
    # KOSTENABWEICHUNG (Stresstest 30.09.2026: Schätzung 900 → effektiv 1240, +38 %,
    # und nichts geschah): Die Freigabe gilt für die geschätzte Summe. Liegen die
    # effektiven Kosten über der Schwelle, oder überschreiten sie die freigegebene
    # Schätzung um mehr als 20 %, braucht es eine (Nach-)Freigabe.
    ABWEICHUNG_NACHFREIGABE = Decimal('1.20')
    eff = a.kosten_effektiv or Decimal('0')
    schaetz = a.kosten_geschaetzt or Decimal('0')
    if eff >= REPARATUR_FREIGABE_SCHWELLE:
        ueber_schwelle = True
    nachfreigabe = (a.freigabe_status == 'freigegeben' and schaetz > 0
                    and eff > schaetz * ABWEICHUNG_NACHFREIGABE)
    if nachfreigabe:
        a.freigabe_status = 'ausstehend'
        a.freigabe_datum = None
        messages.warning(request, '⚠️ ' + gettext(
            'Die effektiven Kosten (CHF %(eff)s) liegen mehr als 20 %% über der freigegebenen Schätzung (CHF %(schaetz)s) — Nachfreigabe der Eigentümerschaft nötig.') % {'eff': eff, 'schaetz': schaetz})
    if nachfreigabe or (a.freigabe_status in ('nicht_noetig', 'abgelehnt') and (freigabe_anfordern or ueber_schwelle)):
        a.freigabe_status = 'ausstehend'
        a.freigabe_datum = None
        # Eigentümer aktiv informieren — sonst bemerkt er die Anfrage erst beim
        # nächsten Portal-Login und die Reparatur liegt tagelang auf Eis.
        eigentuemer = getattr(a.ticket.liegenschaft, 'eigentuemer', None) if a.ticket.liegenschaft_id else None
        mail_info = ""
        if eigentuemer and eigentuemer.email:
            from core.utils.email_service import send_ticket_email
            lg = a.ticket.liegenschaft
            kosten_txt = f"CHF {a.kosten_geschaetzt}" if a.kosten_geschaetzt else "noch offen"
            text = (f"Guten Tag {eigentuemer.kontaktperson or eigentuemer.firma_oder_name}\n\n"
                    f"Für Ihre Liegenschaft {lg.strasse}, {lg.plz} {lg.ort} liegt eine Reparatur "
                    f"zur Freigabe bereit:\n\n"
                    f"Schaden: {a.ticket.titel}\n"
                    f"Geschätzte Kosten: {kosten_txt}\n\n"
                    f"Bitte melden Sie sich im Eigentümer-Portal an, um die Reparatur "
                    f"freizugeben oder abzulehnen.\n\nFreundliche Grüsse\nIhre Verwaltung")
            if send_ticket_email(eigentuemer.email, f"Reparaturfreigabe angefragt — {lg.strasse}", text):
                mail_info = f" E-Mail an {eigentuemer.email} gesendet."
        messages.info(request, 'ℹ️ ' + gettext('Reparatur zur Freigabe an den Eigentümer weitergeleitet (Portal).%(mail_info)s') % {'mail_info': mail_info})

    # Optional Kreditorenrechnung erstellen
    if request.POST.get('kreditor_erstellen') == 'on' and a.kosten_effektiv and not a.kreditoren_rechnung_id:
        kr = KreditorenRechnung.objects.create(
            liegenschaft=a.ticket.liegenschaft,
            lieferant=(a.handwerker.firma if a.handwerker_id else 'Handwerker'),
            betrag=a.kosten_effektiv,
            status='neu',
        )
        # Über den Service: gleiche Prüfungen und ein Verlaufseintrag. Nur verknüpfen — das
        # Ticket schliesst nicht von selbst, nur weil die Kosten erfasst wurden.
        from tickets.workflow import rechnung_verknuepfen
        a.save()
        rechnung_verknuepfen(a, kr, abschliessen=False)
        a.refresh_from_db()
        messages.success(request, '✅ ' + gettext('Kosten erfasst und Kreditorenrechnung über CHF %(kosten_effektiv)s erstellt (Status: Neu — im Kreditoren-Tab freigeben).') % {'kosten_effektiv': a.kosten_effektiv})
    else:
        messages.success(request, '✅ ' + gettext('Kosten erfasst.'))
    a.save()
    log_aktion(request, "Reparaturkosten erfasst", f"Ticket #{a.ticket_id}",
               f"geschätzt {a.kosten_geschaetzt}, effektiv {a.kosten_effektiv}")
    return redirect(f'/neu/schaeden/{a.ticket_id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_versicherungsfall(request, pk):
    """Versicherungsfall zu einem Schaden (core/services/versicherungsfall.py).

    Melden und Ablehnen-Vermerk gehören zur Schadenbearbeitung (Schreib-Rollen); was Geld
    bucht — Selbstbehalt überwälzen, Entschädigung verbuchen — Inhabern und Verwaltern."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from core.auth import VERWALTUNGS_ROLLEN, hat_rolle, log_aktion
    from core.services import versicherungsfall as vs
    from portfolio.models import Versicherung
    from tickets.models import SchadenMeldung

    t = get_object_or_404(SchadenMeldung.objects.select_related('liegenschaft', 'betroffene_einheit'), id=pk)
    basis = _global_filter(request)
    heute = timezone.localdate()
    ziel = f'/neu/schaeden/{t.id}/versicherung/'

    def dec(key):
        roh = _num(request.POST.get(key))
        try:
            return Decimal(roh) if roh else None
        except Exception:
            return None

    if request.method == 'POST':
        aktion = request.POST.get('aktion')
        geld = aktion in ('ueberwaelzen', 'entschaedigung')
        if geld and not hat_rolle(request.user, VERWALTUNGS_ROLLEN):
            messages.error(request, gettext('Buchungen zum Versicherungsfall sind Inhabern und Verwaltern vorbehalten.'))
            return redirect(ziel)
        try:
            if aktion == 'melden':
                police = Versicherung.objects.filter(
                    pk=request.POST.get('police') or 0, liegenschaft=t.liegenschaft).first()
                if request.POST.get('police') and police is None:
                    # Eine gewählte, aber nicht zur Liegenschaft gehörende Police wird nicht
                    # still weggelassen — sonst gälte der Fall ohne Police und ohne Selbstbehalt.
                    raise ValueError(gettext('Die gewählte Police gehört nicht zu dieser Liegenschaft.'))
                try:
                    gemeldet = date.fromisoformat(request.POST.get('gemeldet_am') or '') if request.POST.get('gemeldet_am') else heute
                except ValueError:
                    gemeldet = heute
                vf = vs.melden(t, police=police, schadennummer=request.POST.get('schadennummer') or '',
                               gemeldet_am=gemeldet, schadensumme=dec('schadensumme'),
                               traeger=request.POST.get('selbstbehalt_traeger') or 'eigentuemer',
                               benutzer=request.user, bemerkung=(request.POST.get('bemerkung') or '').strip())
                log_aktion(request, 'Versicherungsfall gemeldet', f'Ticket #{t.id}',
                           f'{vf.schadennummer or "ohne Schadennummer"}, Selbstbehalt CHF {vf.selbstbehalt}')
                messages.success(request, '✅ ' + gettext('Versicherungsfall erfasst.'))
                if police is None:
                    messages.warning(request, gettext('Keine Police gewählt — der Selbstbehalt ist mit CHF 0.00 angesetzt.'))
                elif police.selbstbehalt is None:
                    messages.warning(request, gettext('Bei der Police ist kein Selbstbehalt hinterlegt — mit CHF 0.00 angesetzt.'))
            elif aktion in ('ueberwaelzen', 'entschaedigung', 'ablehnen'):
                from tickets.models import Versicherungsfall
                vf = get_object_or_404(Versicherungsfall, pk=request.POST.get('fall') or 0, ticket=t)
                if aktion == 'ueberwaelzen':
                    vertrag = get_object_or_404(Mietvertrag, pk=request.POST.get('vertrag') or 0)
                    r = vs.selbstbehalt_ueberwaelzen(vf, vertrag, benutzer=request.user)
                    log_aktion(request, 'Selbstbehalt überwälzt', str(vertrag.mieter), f'CHF {r.betrag}', ziel=vertrag)
                    messages.success(request, '✅ ' + gettext('Selbstbehalt von CHF %(betrag)s dem Mieter in Rechnung gestellt.') % {'betrag': r.betrag})
                elif aktion == 'entschaedigung':
                    try:
                        datum = date.fromisoformat(request.POST.get('datum') or '') if request.POST.get('datum') else heute
                    except ValueError:
                        datum = heute
                    vs.entschaedigung_verbuchen(vf, dec('betrag'), datum=datum,
                                                bank=(request.POST.get('bank_konto') or '1020').strip(),
                                                benutzer=request.user)
                    log_aktion(request, 'Versicherungsleistung verbucht', f'Ticket #{t.id}', f'CHF {vf.entschaedigung_erhalten}')
                    messages.success(request, '✅ ' + gettext('Versicherungsleistung verbucht.'))
                else:
                    vs.ablehnen(vf, benutzer=request.user)
                    messages.info(request, gettext('Als abgelehnt vermerkt.'))
        except ValueError as exc:
            messages.error(request, f'❌ {exc}')
        except PermissionError as exc:
            messages.error(request, f'❌ {exc}')
        return redirect(ziel)

    faelle = list(t.versicherungsfaelle.select_related('police', 'selbstbehalt_rechnung'))
    vertraege = []
    if t.betroffene_einheit_id:
        vertraege = list(Mietvertrag.objects.filter(einheit=t.betroffene_einheit, status__in=('aktiv', 'gekuendigt'))
                         .select_related('mieter'))
    return render(request, 'fw/versicherungsfall.html', {
        **basis, 'nav': 'schaeden', 't': t, 'faelle': faelle,
        'policen': Versicherung.objects.filter(liegenschaft=t.liegenschaft),
        'vorschlag': vs.schadensumme_vorschlag(t), 'vertraege': vertraege,
        'heute_iso': heute.isoformat(),
    })
