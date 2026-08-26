# core/views/fw/pendenzen.py
#
# Pendenzen und Fristen — persistent erfasste und automatisch aus dem
# Bestand berechnete, dazu der iCal-Feed. Etappe 1, siehe
# docs/ETAPPE-1-ZERLEGEN.md.
#
# _pendenz_ziel liegt seit Schnitt 0b in _basis.py: Der Helfer wird auch
# ausserhalb dieses Blocks gebraucht und waere sonst mit ihm ausgezogen.

import re
from datetime import date, timedelta as _timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import rolle_erforderlich, SCHREIB_ROLLEN, TEAM_ROLLEN
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag

from ._basis import _global_filter, _pendenz_ziel


# ============================================================
# PENDENZEN / FRISTEN (persistent + automatisch berechnet)
# ============================================================

def _auto_fristen(aktive_lg, horizont_tage=90):
    """Automatisch berechnete Fristen aus dem Datenbestand (read-only):
    befristete Vertragsenden, Kündigungs-Vollzüge, erstmals kündbar."""
    from rentals.models import Kuendigung
    heute = timezone.localdate()
    grenze = heute + _timedelta(days=horizont_tage)
    fristen = []

    aktive = Mietvertrag.objects.filter(status='aktiv').select_related('mieter', 'einheit__liegenschaft')
    gek = Mietvertrag.objects.filter(status='gekuendigt').select_related('mieter', 'einheit__liegenschaft')
    if aktive_lg:
        aktive = aktive.filter(einheit__liegenschaft=aktive_lg)
        gek = gek.filter(einheit__liegenschaft=aktive_lg)

    # a) Befristete Vertragsenden im Horizont (nur echte befristete Verhältnisse)
    for v in aktive.filter(ist_befristet=True, ende__range=[heute, grenze]).order_by('ende'):
        fristen.append({
            'kategorie': 'Befristetes Vertragsende', 'farbe': 'amber', 'icon': 'wartet',
            'titel': f"Vertrag {v.mieter.display_name} endet",
            'sub': f"{v.einheit.bezeichnung}, {v.einheit.liegenschaft.strasse}",
            'faellig': v.ende, 'url': f'/neu/vertraege/{v.id}/',
            'tage': (v.ende - heute).days, 'vertrag_id': v.id, 'kind': 'vertragsende',
        })

    # b) Gekündigte Verträge — Auszug/Übergabe steht an
    for v in gek.filter(ende__range=[heute, grenze]).order_by('ende'):
        fristen.append({
            'kategorie': 'Auszug (gekündigt)', 'farbe': 'rose', 'icon': 'vertrag',
            'titel': f"Auszug {v.mieter.display_name}",
            'sub': f"{v.einheit.bezeichnung} — Abnahme & Kautionsabrechnung vorbereiten",
            'faellig': v.ende, 'url': f'/neu/vertraege/{v.id}/',
            'tage': (v.ende - heute).days, 'vertrag_id': v.id, 'kind': 'auszug',
        })

    # c) Erstmals kündbar im Horizont
    for v in aktive.filter(erstmals_kuendbar_auf__range=[heute, grenze]).order_by('erstmals_kuendbar_auf'):
        fristen.append({
            'kategorie': 'Erstmals kündbar', 'farbe': 'indigo', 'icon': 'termin',
            'titel': f"{v.mieter.display_name}: erstmals kündbar",
            'sub': f"{v.einheit.bezeichnung} — Mietzins-/Konditionen-Review möglich",
            'faellig': v.erstmals_kuendbar_auf, 'url': f'/neu/vertraege/{v.id}/',
            'tage': (v.erstmals_kuendbar_auf - heute).days,
        })

    fristen.sort(key=lambda f: f['faellig'])
    return fristen




@rolle_erforderlich(*TEAM_ROLLEN)
def fw_pendenzen(request):
    from core.models import Pendenz
    from crm.models import Eigentuemer  # noqa
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    auto = _auto_fristen(aktive_lg)

    pq = Pendenz.objects.all().select_related('liegenschaft', 'vertrag__mieter')
    if aktive_lg:
        pq = pq.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg) | Q(liegenschaft__isnull=True, vertrag__isnull=True))
    offene = list(pq.filter(erledigt=False))
    erledigte = list(pq.filter(erledigt=True)[:20])

    # Doppelanzeige vermeiden: Vertragsende/Auszug erscheinen sowohl als read-only
    # Auto-Frist (_auto_fristen) als auch — nach dem Tageslauf — als persistente
    # Pendenz (auto:vertragsende:/auto:auszug:). Wo eine persistente Pendenz existiert,
    # die Auto-Frist herausfiltern (die Pendenz ist abhakbar, die Frist nicht).
    _pers = {(p.vertrag_id, 'vertragsende') for p in offene if (p.quelle or '').startswith('auto:vertragsende:')}
    _pers |= {(p.vertrag_id, 'auszug') for p in offene if (p.quelle or '').startswith('auto:auszug:')}
    if _pers:
        auto = [f for f in auto if (f.get('vertrag_id'), f.get('kind')) not in _pers]

    for p in offene:
        p.ueberfaellig = bool(p.faellig_am and p.faellig_am < heute)
        p.ziel_url, p.ziel_label, p.ziel_wide, p.ziel_modal = _pendenz_ziel(p)

    # Nach Bezug gruppieren: pro Vertrag (Auszug/Mieterwechsel) eine Gruppe,
    # Liegenschafts-Fristen je Liegenschaft, der Rest unter „Allgemein".
    # So bleiben die je ~8 Auszugs-Pendenzen mehrerer Kündigungen getrennt.
    from collections import OrderedDict
    gruppen = OrderedDict()

    def _grp(key, titel, sub, icon, url, wide):
        if key not in gruppen:
            gruppen[key] = {'titel': titel, 'sub': sub, 'icon': icon, 'url': url,
                            'wide': wide, 'pendenzen': [], 'min_faellig': None}
        return gruppen[key]

    for p in offene:
        if p.vertrag_id:
            v = p.vertrag
            obj = (v.einheit.bezeichnung if v and v.einheit_id else '')
            strasse = (v.einheit.liegenschaft.strasse if v and v.einheit_id and v.einheit.liegenschaft_id else '')
            titel = (f"{strasse} · {obj}".strip(' ·') or f"Vertrag #{p.vertrag_id}")
            g = _grp(f"v{p.vertrag_id}", titel,
                     (v.mieter.display_name if v and v.mieter_id else ''),
                     'extern', f'/neu/vertraege/{p.vertrag_id}/', True)
        elif p.liegenschaft_id:
            g = _grp(f"l{p.liegenschaft_id}", p.liegenschaft.strasse, p.liegenschaft.ort,
                     'liegenschaft', f'/neu/liegenschaften/{p.liegenschaft_id}/', True)
        else:
            g = _grp('allgemein', 'Allgemein', '', 'arbeit', None, False)
        g['pendenzen'].append(p)
        if p.faellig_am and (g['min_faellig'] is None or p.faellig_am < g['min_faellig']):
            g['min_faellig'] = p.faellig_am

    # Gruppen nach frühester Fälligkeit sortieren, „Allgemein" ans Ende
    from datetime import date as _date
    gruppen_liste = sorted(
        gruppen.values(),
        key=lambda g: (g['titel'] == 'Allgemein', g['min_faellig'] or _date.max))

    liegenschaften = Liegenschaft.objects.order_by('strasse')
    from django.contrib import messages
    return render(request, 'fw/pendenzen.html', {
        **basis, 'nav': 'pendenzen', 'auto': auto,
        'offene': offene, 'gruppen': gruppen_liste, 'erledigte': erledigte,
        'liegenschaften': liegenschaften, 'heute': heute,
        'kategorien': Pendenz.KATEGORIE_CHOICES,
        'meldung': list(messages.get_messages(request)),
    })


def _art_aus_text(text):
    """Zieht die erste Gesetzesreferenz (z. B. 'Art. 257d OR') aus einem Text."""
    import re
    m = re.search(r'Art\.\s*\d+[a-z]?(?:\s*Abs\.\s*\d+)?\s*OR', text or '')
    return m.group(0) if m else ''


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_fristen(request):
    """Fristen-Center: alle datierten, offenen Fristen chronologisch gebündelt —
    Kündigungstermine, Anfechtungs-/Zahlungsfristen (257d/270b/271), Wartung,
    Referenzzins, befristete Vertragsenden. Zeitfenster: überfällig / diese Woche /
    dieser Monat / später. Jede Frist verlinkt aufs betroffene Objekt."""
    from core.models import Pendenz
    from datetime import timedelta
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    pq = (Pendenz.objects.filter(erledigt=False, faellig_am__isnull=False)
          .select_related('liegenschaft', 'vertrag__mieter', 'vertrag__einheit__liegenschaft'))
    if aktive_lg:
        pq = pq.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg)
                       | Q(liegenschaft__isnull=True, vertrag__isnull=True))
    nur_frist = request.GET.get('nur') == 'frist'
    if nur_frist:
        pq = pq.filter(kategorie='frist')

    eintraege = []
    for p in pq.order_by('faellig_am'):
        url, label, wide, _modal = _pendenz_ziel(p)
        if p.vertrag_id and p.vertrag:
            bezug = p.vertrag.mieter.display_name if p.vertrag.mieter_id else ''
            if p.vertrag.einheit_id:
                bezug = f"{p.vertrag.einheit.liegenschaft.strasse} · {bezug}" if p.vertrag.einheit.liegenschaft_id else bezug
        elif p.liegenschaft_id:
            bezug = f"{p.liegenschaft.strasse}, {p.liegenschaft.ort}"
        else:
            bezug = ''
        eintraege.append({
            'p': p, 'faellig': p.faellig_am, 'titel': p.titel, 'bezug': bezug,
            'tage': (p.faellig_am - heute).days, 'art': _art_aus_text(p.beschreibung),
            'url': url, 'label': label or 'Öffnen', 'wide': wide,
        })

    # Zeitfenster-Buckets
    grenze_woche = heute + timedelta(days=7)
    grenze_monat = heute + timedelta(days=30)
    buckets = [
        {'key': 'ueberfaellig', 'titel': 'Überfällig', 'icon': 'warnung',
         'cls': 'fw-kritisch', 'items': [e for e in eintraege if e['faellig'] < heute]},
        {'key': 'woche', 'titel': 'Diese Woche', 'icon': 'termin',
         'cls': 'fw-warnton', 'items': [e for e in eintraege if heute <= e['faellig'] <= grenze_woche]},
        {'key': 'monat', 'titel': 'Diesen Monat', 'icon': 'termin',
         'cls': 'fw-marke', 'items': [e for e in eintraege if grenze_woche < e['faellig'] <= grenze_monat]},
        {'key': 'spaeter', 'titel': 'Später', 'icon': 'termin',
         'cls': 'fw-mutet', 'items': [e for e in eintraege if e['faellig'] > grenze_monat]},
    ]
    from core.services.ical import feed_token
    return render(request, 'fw/fristen.html', {
        **basis, 'nav': 'fristen', 'buckets': buckets, 'heute': heute,
        'heute_iso': heute.isoformat(),
        'gesamt': len(eintraege), 'nur_frist': nur_frist,
        'ueberfaellig_n': len(buckets[0]['items']),
        'feed_token': feed_token(getattr(request, 'organisation', None)),
    })


def _offene_fristen_pendenzen(aktive_lg=None):
    """Alle offenen, datierten Pendenzen (optional auf eine Liegenschaft gefiltert)."""
    from core.models import Pendenz
    pq = (Pendenz.objects.filter(erledigt=False, faellig_am__isnull=False)
          .select_related('liegenschaft', 'vertrag__mieter'))
    if aktive_lg:
        pq = pq.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg)
                       | Q(liegenschaft__isnull=True, vertrag__isnull=True))
    return pq.order_by('faellig_am')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_fristen_ical(request):
    """Fristen als .ics herunterladen (zum Import in den Kalender)."""
    from django.http import HttpResponse
    from core.services.ical import build_ics, fristen_events
    basis = _global_filter(request)
    ics = build_ics(fristen_events(_offene_fristen_pendenzen(basis['aktive_lg'])))
    resp = HttpResponse(ics, content_type='text/calendar; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="swissimmo-fristen.ics"'
    return resp


def fristen_ical_feed(request):
    """Öffentlicher, abonnierbarer iCal-Feed (Token-gesichert, ohne Login) —
    damit Outlook/Google/Apple Calendar die Fristen automatisch synchronisieren."""
    from django.http import HttpResponse, HttpResponseForbidden
    from core.services.ical import (build_ics, fristen_events,
                                    organisation_aus_token)

    from core.tenancy import kontext_des_objekts

    # Der Token sagt, WESSEN Fristen — vorher signierte er eine Konstante und
    # galt fuer jede Verwaltung. Ohne Anmeldung gibt es hier keinen anderen
    # Weg zur Organisation, und ohne sie warf `Pendenz.objects` seit Etappe
    # 6.2: Der Feed lieferte einen Serverfehler statt eines Kalenders.
    organisation = organisation_aus_token(request.GET.get('token'))
    if organisation is None:
        return HttpResponseForbidden("Ungültiger oder fehlender Token.")
    with kontext_des_objekts(organisation):
        ics = build_ics(fristen_events(_offene_fristen_pendenzen()))
    resp = HttpResponse(ics, content_type='text/calendar; charset=utf-8')
    resp['Content-Disposition'] = 'inline; filename="swissimmo-fristen.ics"'
    return resp


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_pendenz_neu(request):
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.models import Pendenz
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_pendenzen')
    titel = (request.POST.get('titel') or '').strip()
    if not titel:
        messages.error(request, "Titel fehlt.")
        return redirect('fw_pendenzen')
    faellig = None
    if request.POST.get('faellig_am'):
        try:
            faellig = date.fromisoformat(request.POST['faellig_am'])
        except Exception:
            faellig = None
    lg_id = request.POST.get('liegenschaft_id') or None
    Pendenz.objects.create(
        titel=titel,
        beschreibung=(request.POST.get('beschreibung') or '').strip(),
        kategorie=request.POST.get('kategorie', 'aufgabe'),
        faellig_am=faellig,
        liegenschaft_id=lg_id if lg_id else None,
        erstellt_von=request.user,
    )
    log_aktion(request, "Pendenz erstellt", titel, '')
    messages.success(request, f"✅ Pendenz „{titel}“ erfasst.")
    return redirect('fw_pendenzen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_pendenz_toggle(request, pk):
    from django.shortcuts import redirect
    from core.models import Pendenz
    if request.method != 'POST':
        return redirect('fw_pendenzen')
    p = get_object_or_404(Pendenz, id=pk)
    p.erledigt = not p.erledigt
    p.erledigt_am = timezone.localdate() if p.erledigt else None
    p.save()
    return redirect('fw_pendenzen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_pendenz_loeschen(request, pk):
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.models import Pendenz
    if request.method != 'POST':
        return redirect('fw_pendenzen')
    p = get_object_or_404(Pendenz, id=pk)
    from core.auth import log_aktion
    titel = p.titel
    p.delete()
    log_aktion(request, "Pendenz gelöscht", titel, '')
    messages.success(request, "Pendenz gelöscht.")
    return redirect('fw_pendenzen')
