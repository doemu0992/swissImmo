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

from core.auth import (rolle_erforderlich, ROLLE_VERWALTUNG, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag

logger = logging.getLogger(__name__)

from ._basis import _global_filter, _num


# ============================================================
# ETAPPE D: SCHADENSFÄLLE (Tickets)
# ============================================================

TICKET_PILL = {
    'neu':                   ('Neu',                'bg-rose-50 text-rose-600'),
    'in_bearbeitung':        ('In Bearbeitung',     'bg-sky-50 text-sky-700'),
    'warte_auf_mieter':      ('Warte auf Mieter',   'bg-amber-50 text-amber-700'),
    'warte_auf_handwerker':  ('Warte auf Handwerker','bg-amber-50 text-amber-700'),
    'erledigt':              ('Erledigt',           'bg-emerald-50 text-emerald-700'),
}
PRIO_PILL = {
    'hoch':   ('Hoch',   'bg-rose-100 text-rose-700'),
    'mittel': ('Mittel', 'bg-amber-50 text-amber-700'),
    'tief':   ('Tief',   'bg-slate-100 text-slate-500'),
    'niedrig':('Tief',   'bg-slate-100 text-slate-500'),
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_schaeden(request):
    from tickets.models import SchadenMeldung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (SchadenMeldung.objects.select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von')
          .order_by('-erstellt_am'))
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    status_filter = request.GET.get('status', '')
    if status_filter == 'offen':
        qs = qs.exclude(status='erledigt')
    elif status_filter in TICKET_PILL:
        qs = qs.filter(status=status_filter)
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(titel__icontains=q) | Q(beschreibung__icontains=q)
                       | Q(kategorie__icontains=q) | Q(liegenschaft__strasse__icontains=q))

    rows = []
    offen = 0
    in_arbeit = 0
    for t in qs:
        s_label, s_cls = TICKET_PILL.get(t.status, (t.status, 'bg-slate-100 text-slate-500'))
        p_label, p_cls = PRIO_PILL.get((t.prioritaet or '').lower(), (t.prioritaet or 'Mittel', 'bg-slate-100 text-slate-500'))
        if t.status != 'erledigt':
            offen += 1
        if t.status == 'in_bearbeitung':
            in_arbeit += 1
        melder = (t.gemeldet_von.display_name if t.gemeldet_von_id
                  else f"{t.melder_vorname or ''} {t.melder_nachname or ''}".strip() or '—')
        rows.append({
            't': t, 's_label': s_label, 's_cls': s_cls, 'p_label': p_label, 'p_cls': p_cls,
            'objekt': f"{t.liegenschaft.strasse}, {t.liegenschaft.ort}" if t.liegenschaft_id else '—',
            'melder': melder,
        })

    chips = [('', 'Alle'), ('offen', 'Offen')] + [(k, v[0]) for k, v in TICKET_PILL.items()]
    liegenschaften = Liegenschaft.objects.order_by('strasse')
    einheiten = Einheit.objects.select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung')
    from django.contrib import messages
    return render(request, 'fw/schaeden.html', {
        **basis, 'nav': 'schadensfaelle', 'rows': rows,
        'status_filter': status_filter, 'status_chips': chips, 'q': q,
        'anzahl': len(rows), 'offen': offen, 'in_arbeit': in_arbeit,
        'liegenschaften': liegenschaften, 'einheiten': einheiten,
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

    auf = HandwerkerAuftrag.objects.select_related('ticket__liegenschaft', 'handwerker')
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
        messages.error(request, "Titel und Liegenschaft sind erforderlich.")
        return redirect('fw_schaeden')

    einheit = Einheit.objects.filter(id=request.POST.get('einheit_id') or None).first() if request.POST.get('einheit_id') else None
    t = SchadenMeldung.objects.create(
        liegenschaft=lg, betroffene_einheit=einheit,
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
    messages.success(request, f"✅ Ticket #{t.id} erstellt" + (f" · Eingangsbestätigung an {t.email_melder} gesendet." if ok else "."))
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_schaden_detail(request, pk):
    from tickets.models import SchadenMeldung
    t = get_object_or_404(
        SchadenMeldung.objects.select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von'), id=pk)
    basis = _global_filter(request)

    # Beim Öffnen als gelesen markieren (entfernt den Sidebar-Badge-Zähler)
    if not t.gelesen:
        t.gelesen = True
        t.save(update_fields=['gelesen'])

    s_label, s_cls = TICKET_PILL.get(t.status, (t.status, 'bg-slate-100 text-slate-500'))
    p_label, p_cls = PRIO_PILL.get((t.prioritaet or '').lower(), (t.prioritaet or 'Mittel', 'bg-slate-100 text-slate-500'))
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
    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('verlauf', 'Verlauf', nachrichten.count() or None),
        ('handwerker', 'Handwerker & Kosten', len(auftraege) or None),
        ('fotos', 'Fotos', len(fotos) or None),
    ]
    from django.contrib import messages
    return render(request, 'fw/schaden_detail.html', {
        **basis, 'nav': 'schadensfaelle', 't': t,
        's_label': s_label, 's_cls': s_cls, 'p_label': p_label, 'p_cls': p_cls,
        'nachrichten': nachrichten, 'auftraege': auftraege, 'melder': melder,
        'kosten_geschaetzt': kosten_geschaetzt, 'kosten_effektiv': kosten_effektiv,
        'fotos': fotos,
        'tab_liste': tab_liste,
        'ausstattung_elemente': ausstattung_elemente,
        'handwerker_liste': handwerker_liste, 'auftrag_vorschlag': auftrag_vorschlag,
        'melder_email': melder_email, 'status_wahl': TICKET_PILL,
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
            messages.success(request, f"✅ Mit «{el.kategorie}» ({el.raum}) verknüpft.")
    else:
        t.ausstattung = None
        t.save(update_fields=['ausstattung'])
        messages.success(request, "Verknüpfung aufgehoben.")
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
        pdf = generate_ersatzplanung_pdf(daten, lg_name, verwaltung=Organisation.objects.first(),
                                         deckung=deckung)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = 'inline; filename="Ersatzplanung.pdf"'
        return resp

    f = request.GET.get('status', '')
    rows = [r for r in daten['rows'] if not f or f == r['status']]

    chips = [('', 'Alle'), ('faellig', 'Ersatz fällig'), ('bald', 'Bald fällig'),
             ('ok', 'Im Nutzungszeitraum'), ('unbekannt', 'Keine Datenbasis')]
    return render(request, 'fw/ersatzplanung.html', {
        **basis, 'nav': 'assets', 'rows': rows, 'status_filter': f, 'chips': chips,
        'n_faellig': daten['n_faellig'], 'n_bald': daten['n_bald'],
        'n_ok': daten['n_ok'], 'n_unbekannt': daten['n_unbekannt'],
        'jahres_budget': daten['jahres_budget'], 'budget_total': daten['budget_total'],
        'horizont_jahre': daten['horizont_jahre'], 'deckung': deckung,
        'anzahl': len(rows),
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
        messages.success(request, f"✅ {n} Foto(s) hinzugefügt.")
    if abgelehnt:
        messages.error(request, f"{abgelehnt} Datei(en) abgelehnt (kein gültiges Bild oder zu gross).")
    elif not n:
        messages.error(request, "Keine Datei ausgewählt.")
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
        messages.success(request, "Foto entfernt.")
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
        messages.success(request, "🗑️ Schadensmeldung gelöscht.")
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

    with transaction.atomic():
        auftrag = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, bemerkung=auftragstext, status='offen')
        TicketNachricht.objects.create(ticket=t, absender_name="System", typ='system',
                                       nachricht=f"Auftrag an {hw.firma} vergeben.", is_intern=True)
        if t.status == 'neu':
            t.status = 'in_bearbeitung'
        t.save()

    # Mail an Handwerker (Auftragstext, Foto als Anhang)
    hw_betreff, hw_text = vorlage_text('ticket_handwerker', t, handwerker=hw)
    if auftragstext:
        hw_text = auftragstext
    hw_ok = send_ticket_email(hw.email, hw_betreff, hw_text, foto_field=t.foto) if hw.email else False

    # Info-Mail an Melder
    melder_email = t.email_melder or (t.gemeldet_von.email if t.gemeldet_von_id else '')
    m_betreff, m_text = vorlage_text('ticket_melder', t, handwerker=hw)
    melder_ok = send_ticket_email(melder_email, m_betreff, m_text) if melder_email else False

    if melder_ok:
        TicketNachricht.objects.create(ticket=t, absender_name="System", typ='system',
                                       nachricht=f"Melder automatisch informiert ({melder_email}).", is_intern=True)

    log_aktion(request, "Handwerker beauftragt", f"Ticket #{t.id}", f"{hw.firma}")
    hinweise = []
    hinweise.append("Mail an Handwerker gesendet" if hw_ok else ("Handwerker ohne E-Mail" if not hw.email else "Mail an Handwerker fehlgeschlagen"))
    hinweise.append("Melder informiert" if melder_ok else ("Melder ohne E-Mail" if not melder_email else "Melder-Mail fehlgeschlagen"))
    messages.success(request, f"✅ {hw.firma} beauftragt · Status: In Bearbeitung · " + " · ".join(hinweise) + ".")
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
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
    neu = request.POST.get('status')
    if neu not in dict(SchadenMeldung.STATUS_CHOICES):
        messages.error(request, "Ungültiger Status.")
        return redirect(f'/neu/schaeden/{t.id}/')
    t.status = neu
    t.save()
    TicketNachricht.objects.create(ticket=t, absender_name="System", typ='system',
                                   nachricht=f"Status geändert: {t.get_status_display()}.", is_intern=True)

    info = ""
    if request.POST.get('melder_informieren') == 'on':
        melder_email = t.email_melder or (t.gemeldet_von.email if t.gemeldet_von_id else '')
        kat = 'ticket_erledigt' if neu == 'erledigt' else 'ticket_melder_status'
        betreff, text = vorlage_text(kat, t, status=t.get_status_display())
        if melder_email and send_ticket_email(melder_email, betreff, text):
            info = f" · Melder informiert ({melder_email})"
            TicketNachricht.objects.create(ticket=t, absender_name="System", typ='system',
                                           nachricht=f"Melder über Status '{t.get_status_display()}' informiert.", is_intern=True)

    log_aktion(request, "Ticket-Status geändert", f"Ticket #{t.id}", t.get_status_display())
    messages.success(request, f"✅ Status: {t.get_status_display()}{info}.")
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
        messages.success(request, f"✅ Antwort an {melder_email} gesendet.")
    elif melder_email:
        messages.error(request, "Antwort gespeichert, aber E-Mail-Versand fehlgeschlagen.")
    else:
        messages.success(request, "Antwort im Verlauf gespeichert (Melder ohne E-Mail).")
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
    pdf = generate_auftrag_pdf(a, Organisation.objects.first())
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Reparaturauftrag_{a.id}.pdf"'
    return resp


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
    if a.freigabe_status in ('nicht_noetig', 'abgelehnt') and (freigabe_anfordern or ueber_schwelle):
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
        messages.info(request, f"ℹ️ Reparatur zur Freigabe an den Eigentümer weitergeleitet (Portal).{mail_info}")

    # Optional Kreditorenrechnung erstellen
    if request.POST.get('kreditor_erstellen') == 'on' and a.kosten_effektiv and not a.kreditoren_rechnung_id:
        kr = KreditorenRechnung.objects.create(
            liegenschaft=a.ticket.liegenschaft,
            lieferant=(a.handwerker.firma if a.handwerker_id else 'Handwerker'),
            betrag=a.kosten_effektiv,
            status='neu',
        )
        a.kreditoren_rechnung = kr
        messages.success(request, f"✅ Kosten erfasst und Kreditorenrechnung über CHF {a.kosten_effektiv} erstellt (Status: Neu — im Kreditoren-Tab freigeben).")
    else:
        messages.success(request, "✅ Kosten erfasst.")
    a.save()
    log_aktion(request, "Reparaturkosten erfasst", f"Ticket #{a.ticket_id}",
               f"geschätzt {a.kosten_geschaetzt}, effektiv {a.kosten_effektiv}")
    return redirect(f'/neu/schaeden/{a.ticket_id}/')
