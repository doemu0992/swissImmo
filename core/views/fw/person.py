# core/views/fw/person.py
#
# Personen (Mieter und Kontakte): Detailseite, Stammdaten, Adresshistorie,
# Mieterkonto, Lieferantenkonten, Kommunikation, Dokumentfreigabe,
# Portal-Zugang, Loeschen samt DSG-Loeschung.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# fw_person_loeschen und fw_person_dsg_loeschen sind seit E2 die einzigen
# Schreibpfade fuer diese Daten (der Admin ist lesend) -- und der
# Loeschschutz bei aktivem Vertrag wird seit E1c genau hier getestet.

import logging
from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from crm.models import Mieter
from finance.models import DebitorenRechnung, Zahlungseingang
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag

logger = logging.getLogger(__name__)

from ._basis import _global_filter, _num, VERTRAG_PILL


# ============================================================
# PERSON-DETAIL (Mieter) — in der neuen Shell
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_person_detail(request, pk):
    from rentals.models import Dokument as RentalsDokument
    from tickets.models import SchadenMeldung
    m = get_object_or_404(Mieter, id=pk)
    basis = _global_filter(request)
    from django.db.models import Q as _Q

    # Verträge, in denen die Person Haupt- ODER Mitmieter ist (2-Personen-Vertrag)
    vertraege = (Mietvertrag.objects.filter(_Q(mieter=m) | _Q(mitmieter=m))
                 .select_related('einheit__liegenschaft').distinct().order_by('-beginn'))
    aktive = [v for v in vertraege if v.status == 'aktiv']
    _vids = list(vertraege.values_list('id', flat=True))

    offene = (DebitorenRechnung.objects
              .filter(vertrag_id__in=_vids, status__in=['offen', 'teilbezahlt'])
              .select_related('vertrag__einheit').order_by('faellig_am'))
    total_offen = sum((r.offener_betrag for r in offene), Decimal('0.00'))
    # Aktive Verträge mit offenem Posten → Ziel(e) für den 257d-Verzugsdialog
    # (roter Zahlungsverzug-Alarm im Finanzen-Tab, analog zur Vertrag-Detailseite).
    _seen_v = set()
    offene_vertraege = []
    for r in offene:
        vt = r.vertrag
        if vt and vt.id not in _seen_v and vt.status == 'aktiv':
            _seen_v.add(vt.id)
            offene_vertraege.append(vt)

    # Offene, datierte Fristen/Pendenzen über ALLE Verträge der Person — damit die
    # 257d-Frist (inkl. Einschreiben-Zugang) auch am Kontakt sichtbar/erledigbar ist.
    from core.models import Pendenz as _Pendenz
    _heute_p = timezone.localdate()
    person_fristen = []
    for p in (_Pendenz.objects.filter(erledigt=False, faellig_am__isnull=False, vertrag_id__in=_vids)
              .select_related('vertrag__einheit__liegenschaft').order_by('faellig_am')):
        person_fristen.append({'p': p, 'ueberfaellig': p.faellig_am < _heute_p,
                               'tage': (p.faellig_am - _heute_p).days})

    zahlungen = (Zahlungseingang.objects.filter(vertrag_id__in=_vids, status='verbucht')
                 .order_by('-datum_eingang')[:15])
    # Dokumente am Mieter ODER an seinen Verträgen (Vertrags-PDF, Mietzins,
    # Kündigung …) — pro Objekt gruppiert (Objekt = Einheit des Vertrags).
    # Gruppierung nach Mietverhältnis (= Vertrag) — konsistent zum «Verhältnisse»-
    # Tab am Objekt. Ohne Vertragsbezug → «Persönlich».
    from collections import defaultdict
    dok_buckets = defaultdict(list)
    vtr_meta = {}
    for d in (RentalsDokument.objects.filter(_Q(mieter=m) | _Q(vertrag_id__in=_vids))
              .select_related('einheit__liegenschaft', 'vertrag__einheit__liegenschaft')
              .distinct().order_by('-datum')):
        vid = d.vertrag_id
        if vid and vid not in vtr_meta:
            vtr_meta[vid] = d.vertrag
        dok_buckets[vid].append(d)   # Modell-Objekt behalten (Portal-Toggle braucht d.id)

    def _verhaeltnis_label(v):
        e = v.einheit
        obj = f"{e.bezeichnung} · {e.liegenschaft.strasse}" if e else 'Objekt'
        bis = v.ende.strftime('%d.%m.%Y') if v.ende else 'laufend'
        return f"{obj} · {v.beginn:%d.%m.%Y}–{bis}"

    dok_gruppen = []
    # Reihenfolge: Verhältnisse (Verträge) wie in der Vertragsliste (neueste zuerst)
    geordnet = list(vertraege) + [v for vid, v in vtr_meta.items()
                                  if vid not in {x.id for x in vertraege}]
    for v in geordnet:
        docs = dok_buckets.get(v.id)
        if docs:
            dok_gruppen.append({'einheit': v.einheit, 'vertrag': v,
                                'label': _verhaeltnis_label(v), 'dokumente': docs})
    if dok_buckets.get(None):
        dok_gruppen.append({'einheit': None, 'vertrag': None,
                            'label': 'Persönlich (ohne Vertragsbezug)',
                            'dokumente': dok_buckets[None]})
    dok_total = sum(len(g['dokumente']) for g in dok_gruppen)

    vertrag_rows = []
    for v in vertraege:
        label, cls = VERTRAG_PILL.get(v.status, (v.status, 'bg-slate-100 text-slate-500'))
        vertrag_rows.append({'v': v, 'label': label, 'cls': cls,
                             'brutto': (v.netto_mietzins or Decimal('0')) + (v.nebenkosten or Decimal('0'))})

    from core.models import AktivitaetsLog
    verlauf = list(AktivitaetsLog.objects.filter(
        _Q(ziel_typ='person', ziel_id=m.id) | _Q(ziel_typ='vertrag', ziel_id__in=_vids)
    ).select_related('benutzer')[:50])

    # Etappe 4b.3: Reiter aus dem Aktenregister statt aus dieser View.
    # `aktivitaet` und `verlauf` fallen beide auf `chronik` — ihre Zaehler
    # werden von `aus_alt` addiert, nicht ueberschrieben.
    from django.contrib.contenttypes.models import ContentType

    from faelle.akten import aus_alt as _reiter_aus_alt
    from faelle.models import Fall
    from core.tenancy import aktuelle_organisation as _akt_org

    person_faelle = list(
        Fall.objects.filter(akte_typ=ContentType.objects.get_for_model(Mieter),
                            akte_id=m.id)
        .select_related('fallart', 'zustaendig').order_by('-eroeffnet_am'))

    tab_liste = _reiter_aus_alt('person', [
        ('uebersicht', 'Übersicht', None),
        ('vertraege', 'Verträge', vertraege.count() or None),
        ('finanzen', 'Finanzen', offene.count() or None),
        ('dokumente', 'Dokumente', dok_total or None),
        ('aktivitaet', 'Journal', m.kommunikationen.count() or None),
        ('verlauf', 'Verlauf', len(verlauf) or None),
    ], organisation=getattr(request, 'organisation', None) or _akt_org())
    return render(request, 'fw/person_detail.html', {
        **basis, 'nav': 'personen', 'm': m, 'verlauf': verlauf,
        'vertrag_rows': vertrag_rows,
        'person_faelle': person_faelle,
        'anzahl_aktive': len(aktive),
        'brutto_monat': sum((r['brutto'] for r in vertrag_rows if r['v'].status == 'aktiv'), Decimal('0.00')),
        'offene': offene, 'total_offen': total_offen, 'offene_vertraege': offene_vertraege,
        'person_fristen': person_fristen, 'heute_iso': _heute_p.isoformat(),
        'pe_zugang_next': f'/neu/personen/{m.id}/',
        'zahlungen': zahlungen, 'dok_gruppen': dok_gruppen, 'dok_total': dok_total,
        'telefon': m.mobile or m.telefon_privat or m.telefon_geschaeft,
        'kommunikationen': m.kommunikationen.select_related('vertrag', 'erstellt_von')[:50],
        'portal_user': getattr(m, 'benutzer', None),
        'tab_liste': tab_liste,
        'adress_verlauf': list(m.adressen.all()),
        'heute': timezone.localdate().isoformat(),
    })


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_mieter_portal_zugang(request, pk):
    """Erstellt/aktualisiert einen Mieterportal-Login und zeigt die Zugangsdaten einmalig."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.contrib.auth import get_user_model
    from core.auth import log_aktion
    import secrets

    User = get_user_model()
    m = get_object_or_404(Mieter, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/personen/{m.id}/')
    aktion = request.POST.get('aktion', 'erstellen')
    if aktion == 'entfernen':
        if m.benutzer_id:
            u = m.benutzer
            m.benutzer = None
            m.save(update_fields=['benutzer'])
            # Konto vollständig entfernen (kein verwaistes .1/.2-Konto zurücklassen)
            from core.auth import konto_freigeben
            konto_freigeben(u, getattr(request, 'organisation', None))
        messages.success(request, "Portal-Zugang entfernt.")
        return redirect(f'/neu/personen/{m.id}/')

    # Benutzername: E-Mail bevorzugt, sonst mieter<id>
    basis_name = (m.email or f"mieter{m.id}").strip().lower()
    passwort = secrets.token_urlsafe(9)
    if m.benutzer_id:
        u = m.benutzer
        u.set_password(passwort)
        u.is_active = True
        u.save()
    else:
        username = basis_name
        i = 1
        while User.objects.filter(username=username).exists():
            username = f"{basis_name}.{i}"
            i += 1
        u = User.objects.create_user(username=username, email=m.email or '', password=passwort)
        m.benutzer = u
        m.save(update_fields=['benutzer'])
    log_aktion(request, "Mieterportal-Zugang erstellt", m.display_name, u.username)

    # Zugangsdaten per E-Mail an den Mieter senden (Benutzername, Passwort, Login-Link)
    mail_ok = False
    if m.email:
        from core.utils.email_service import send_mieter_portal_zugang
        # Absender der Zugangsmail: die Verwaltung DIESES Mieters.
        vw = m.organisation
        # Feste Produktions-Basis-URL (settings) statt Request-Host — der Link
        # muss immer auf die öffentliche Portal-Adresse zeigen.
        from django.conf import settings as _settings
        login_url = _settings.PORTAL_BASE_URL.rstrip('/') + '/portal/login/'
        anrede = (f"{m.anrede} " if m.anrede else "") + (m.nachname or m.display_name)
        mail_ok = send_mieter_portal_zugang(
            m.email, anrede.strip(), u.username, passwort, login_url,
            absender_firma=(vw.firma if vw else ''))

    if mail_ok:
        messages.success(request, f"✅ Portal-Zugang aktiv. Zugangsdaten wurden an {m.email} gesendet. (Benutzername: {u.username})")
    elif m.email:
        messages.warning(request, f"⚠️ Portal-Zugang aktiv, aber E-Mail-Versand fehlgeschlagen. Benutzername: {u.username} · Passwort: {passwort} — bitte manuell mitteilen.")
    else:
        messages.success(request, f"✅ Portal-Zugang aktiv. Keine E-Mail hinterlegt — Benutzername: {u.username} · Passwort: {passwort} (bitte dem Mieter sicher mitteilen, wird nur einmal angezeigt).")
    return redirect(f'/neu/personen/{m.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mieterkonto_pdf(request, pk):
    """Kontoauszug (PDF) eines Mieters für die Verwaltung."""
    from django.http import HttpResponse
    from crm.models import Organisation
    from core.services.mieterkonto import generate_mieterkonto_pdf
    m = get_object_or_404(Mieter, id=pk)
    pdf = generate_mieterkonto_pdf(m, verwaltung=m.organisation)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Kontoauszug_{m.nachname or m.id}.pdf"'
    return resp


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mieterkonto(request, pk):
    """Mieterkontoblatt (on-screen): alle Forderungen (Sollstellungen) und Zahlungen
    chronologisch mit laufendem Saldo — dieselbe Datenbasis wie der PDF-Auszug."""
    from core.services.mieterkonto import berechne_mieterkonto
    from django.db.models import Q as _Q
    m = get_object_or_404(Mieter, id=pk)
    basis = _global_filter(request)

    von = bis = None
    try:
        if request.GET.get('von'):
            von = date.fromisoformat(request.GET['von'])
        if request.GET.get('bis'):
            bis = date.fromisoformat(request.GET['bis'])
    except ValueError:
        von = bis = None

    zeilen, endsaldo = berechne_mieterkonto(m, von=von, bis=bis)
    total_soll = sum((z['soll'] for z in zeilen), Decimal('0.00'))
    total_haben = sum((z['haben'] for z in zeilen), Decimal('0.00'))

    # Offene Posten (OP): noch nicht (voll) bezahlte Forderungen
    vids = list(Mietvertrag.objects.filter(_Q(mieter=m) | _Q(mitmieter=m)).values_list('id', flat=True))
    op = [r for r in DebitorenRechnung.objects.filter(vertrag_id__in=vids, status__in=['offen', 'teilbezahlt'])
          .select_related('vertrag__einheit__liegenschaft').order_by('faellig_am') if r.offener_betrag > 0]
    heute = timezone.localdate()
    op_rows = [{
        'r': r, 'offen': r.offener_betrag,
        'faellig': r.faellig_am or r.datum,
        'ueberfaellig': bool((r.faellig_am or r.datum) and (r.faellig_am or r.datum) < heute),
    } for r in op]

    return render(request, 'fw/mieterkonto.html', {
        **basis, 'nav': 'mieterkonten', 'm': m,
        'zeilen': zeilen, 'endsaldo': endsaldo,
        'total_soll': total_soll, 'total_haben': total_haben,
        'op_rows': op_rows, 'op_total': sum((o['offen'] for o in op_rows), Decimal('0.00')),
        'von': von, 'bis': bis,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mieterkonten(request):
    """Übersicht aller Mieterkonten: pro Mieter der aktuelle Saldo (Forderungen −
    Zahlungen). Einstieg ins einzelne Kontoblatt."""
    from core.services.mieterkonto import saldi_fuer_mieter
    from django.db.models import Q as _Q
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    filter_op = request.GET.get('filter') == 'offen'

    vtr = Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft')
    if aktive_lg:
        vtr = vtr.filter(einheit__liegenschaft=aktive_lg)
    # Ein Mieter kann mehrere Verträge haben → pro Mieter EIN Konto.
    mieter_map = {}
    for v in vtr:
        if not v.mieter_id:
            continue
        eintrag = mieter_map.setdefault(v.mieter_id, {'mieter': v.mieter, 'objekte': set(), 'aktiv': False})
        if v.einheit_id and v.einheit.liegenschaft_id:
            eintrag['objekte'].add(f"{v.einheit.liegenschaft.strasse} · {v.einheit.bezeichnung}")
        if v.status == 'aktiv':
            eintrag['aktiv'] = True

    # Suche: bei mehr als einer Handvoll Mieter ist Scrollen keine Bedienung.
    q = (request.GET.get('q') or '').strip()
    q_klein = q.lower()

    rows = []
    total_offen = Decimal('0.00')
    gesamt_n = 0            # alle Mieter — unabhängig von Filter und Suche
    offen_gesamt_n = 0
    # Alle Salden auf einmal statt drei Abfragen je Mieter (gemessen: 98 → 8).
    # Die Liste zeigt nur den Saldo; den vollen Auszug baut erst das Kontoblatt.
    saldi = saldi_fuer_mieter([d['mieter'] for d in mieter_map.values()])
    for mid, data in mieter_map.items():
        saldo = saldi.get(mid, Decimal('0'))
        gesamt_n += 1
        if saldo > 0:
            total_offen += saldo
            offen_gesamt_n += 1
        if filter_op and saldo <= 0:
            continue
        objekt_text = ' · '.join(sorted(data['objekte'])[:1]) or '—'
        if q_klein and q_klein not in (data['mieter'].display_name or '').lower() \
                and q_klein not in objekt_text.lower():
            continue
        rows.append({
            'm': data['mieter'], 'saldo': saldo,
            'objekt': objekt_text,
            'objekte_n': len(data['objekte']),
            'aktiv': data['aktiv'],
        })
    # offene zuerst (grösster Schuldsaldo oben), dann Name
    rows.sort(key=lambda r: (-(r['saldo'] if r['saldo'] > 0 else Decimal('0')), (r['m'].nachname or '').lower()))

    return render(request, 'fw/mieterkonten.html', {
        **basis, 'nav': 'mieterkonten', 'rows': rows, 'q': q,
        # «Alle (N)» zählte bisher die bereits gefilterten Zeilen — in der
        # gefilterten Ansicht stand am «Alle»-Knopf also die falsche Zahl.
        'total_offen': total_offen, 'anzahl': gesamt_n,
        'offen_n': offen_gesamt_n, 'treffer_n': len(rows),
        'filter_op': filter_op,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_lieferantenkonten(request):
    """Übersicht Lieferantenkonten (Kreditoren): pro Lieferant offener Betrag
    (was die Verwaltung dem Lieferanten noch schuldet). Einstieg ins Kontoblatt."""
    from finance.models import KreditorenRechnung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    filter_op = request.GET.get('filter') == 'offen'

    kred = KreditorenRechnung.objects.exclude(status='storniert')
    if aktive_lg:
        kred = kred.filter(liegenschaft=aktive_lg)

    gruppen = {}
    for k in kred:
        name = (k.lieferant or '').strip() or '— ohne Lieferant —'
        g = gruppen.setdefault(name, {'name': name, 'anzahl': 0, 'offen': Decimal('0.00'),
                                      'volumen': Decimal('0.00')})
        g['anzahl'] += 1
        g['offen'] += k.offener_betrag
        g['volumen'] += (k.betrag or Decimal('0.00'))

    rows = list(gruppen.values())
    total_offen = sum((g['offen'] for g in rows), Decimal('0.00'))
    if filter_op:
        rows = [g for g in rows if g['offen'] > 0]
    rows.sort(key=lambda g: (-g['offen'], g['name'].lower()))

    return render(request, 'fw/lieferantenkonten.html', {
        **basis, 'nav': 'lieferantenkonten', 'rows': rows,
        'total_offen': total_offen, 'anzahl': len(gruppen),
        'offen_n': sum(1 for g in gruppen.values() if g['offen'] > 0),
        'filter_op': filter_op,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_lieferantenkonto(request):
    """Kontoblatt eines Lieferanten: alle Rechnungen (Belastung) und Zahlungen
    (Ausgang) chronologisch mit laufendem offenem Saldo. Lieferant via ?name=."""
    from finance.models import KreditorenRechnung, KreditorenZahlung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    name = (request.GET.get('name') or '').strip()

    kred = KreditorenRechnung.objects.exclude(status='storniert')
    if aktive_lg:
        kred = kred.filter(liegenschaft=aktive_lg)
    if name == '— ohne Lieferant —':
        kred = kred.filter(Q(lieferant='') | Q(lieferant__isnull=True))
    else:
        kred = kred.filter(lieferant=name)
    kred = list(kred.select_related('liegenschaft').prefetch_related('zahlungen'))

    bewegungen = []
    for k in kred:
        d = k.datum or k.faellig_am or heute
        bewegungen.append({'datum': d, 'text': f"Rechnung{(' ' + k.referenz) if k.referenz else ''}",
                           'belastung': k.betrag or Decimal('0.00'), 'zahlung': Decimal('0.00'), 'sort': 0})
        for z in k.zahlungen.all():
            if z.status != 'verbucht':
                continue
            bewegungen.append({'datum': z.datum, 'text': z.bemerkung or 'Zahlung',
                               'belastung': Decimal('0.00'), 'zahlung': z.betrag or Decimal('0.00'), 'sort': 1})
    bewegungen.sort(key=lambda b: (b['datum'], b['sort']))
    saldo = Decimal('0.00')
    for b in bewegungen:
        saldo += b['belastung'] - b['zahlung']
        b['saldo'] = saldo

    total_belastung = sum((b['belastung'] for b in bewegungen), Decimal('0.00'))
    total_zahlung = sum((b['zahlung'] for b in bewegungen), Decimal('0.00'))

    # Offene Posten (unbezahlte/teilbezahlte Rechnungen)
    op = [{'k': k, 'offen': k.offener_betrag, 'faellig': k.faellig_am or k.datum,
           'ueberfaellig': bool((k.faellig_am or k.datum) and (k.faellig_am or k.datum) < heute)}
          for k in kred if k.offener_betrag > 0]
    op.sort(key=lambda o: (o['faellig'] or heute))

    # Verlauf: alle protokollierten Aktionen zu diesem Lieferanten (Rechnung
    # erstellt/gescannt/bearbeitet/freigegeben/bezahlt/gelöscht, Dienstleister-
    # Änderungen). Kreditorenrechnungen tragen den Lieferanten als Log-Objekt —
    # der Abgleich läuft über den Namen (kein FK am Modell).
    from core.models import AktivitaetsLog
    verlauf = []
    if name and name != '— ohne Lieferant —':
        verlauf = list(AktivitaetsLog.objects.filter(objekt__iexact=name)
                       .select_related('benutzer')[:50])

    return render(request, 'fw/lieferantenkonto.html', {
        **basis, 'nav': 'lieferantenkonten', 'name': name,
        'bewegungen': bewegungen, 'endsaldo': saldo,
        'total_belastung': total_belastung, 'total_zahlung': total_zahlung,
        'op_rows': op, 'op_total': sum((o['offen'] for o in op), Decimal('0.00')),
        'rechnungen_n': len(kred),
        'verlauf': verlauf,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kommunikation_neu(request):
    """Schnelle Telefonnotiz / Kommunikation zu einem Kontakt erfassen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Kommunikation
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/personen/')
    P = request.POST
    m = get_object_or_404(Mieter, id=P.get('mieter_id'))
    inhalt = (P.get('inhalt') or '').strip()
    if not inhalt:
        messages.error(request, "Bitte einen Inhalt/Notiztext erfassen.")
        return redirect(f'/neu/personen/{m.id}/')
    vertrag = m.vertraege.order_by('-beginn').first()
    Kommunikation.objects.create(
        mieter=m, vertrag=vertrag,
        liegenschaft=vertrag.einheit.liegenschaft if vertrag and vertrag.einheit_id else None,
        typ=P.get('typ', 'telefon'), richtung=P.get('richtung', 'eingehend'),
        betreff=(P.get('betreff') or '').strip(), inhalt=inhalt,
        erstellt_von=request.user,
    )
    log_aktion(request, "Kommunikation erfasst", str(m), P.get('typ', 'telefon'))
    messages.success(request, "✅ Notiz im Kontaktjournal erfasst.")
    return redirect(f'/neu/personen/{m.id}/#p-aktivitaet')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kommunikation_loeschen(request, pk):
    """Journal-Eintrag (Kommunikation) löschen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Kommunikation
    from core.auth import log_aktion
    k = get_object_or_404(Kommunikation.objects.select_related('mieter'), id=pk)
    mid = k.mieter_id
    if request.method == 'POST':
        log_aktion(request, "Journal-Eintrag gelöscht", str(k.mieter) if k.mieter_id else '', k.typ)
        k.delete()
        messages.success(request, "🗑️ Journal-Eintrag gelöscht.")
    return redirect(f'/neu/personen/{mid}/?tab=aktivitaet')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_dokument_portal_toggle(request, pk):
    """Schaltet die Mieterportal-Sichtbarkeit eines Dokuments um."""
    from django.shortcuts import redirect
    from rentals.models import Dokument as RentalsDokument
    from core.auth import log_aktion
    d = get_object_or_404(RentalsDokument, id=pk)
    if request.method == 'POST':
        d.im_portal_sichtbar = not d.im_portal_sichtbar
        d.save(update_fields=['im_portal_sichtbar'])
        log_aktion(request, "Dokument-Portalsichtbarkeit", d.bezeichnung or d.titel,
                   'sichtbar' if d.im_portal_sichtbar else 'ausgeblendet')
    return redirect(request.META.get('HTTP_REFERER') or (f'/neu/personen/{d.mieter_id}/' if d.mieter_id else '/neu/dokumente/'))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_rentals_dokument_loeschen(request, pk):
    """Dokument (Vertrags-/Mieter-Ablage) löschen — überall dort, wo Dokumente
    in Akten gezeigt werden (Person, Vertrag, Objekt, Liegenschaft, Portal)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Dokument as RentalsDokument
    from core.auth import log_aktion
    d = get_object_or_404(RentalsDokument, id=pk)
    ref = request.META.get('HTTP_REFERER')
    ziel = ref or (f'/neu/personen/{d.mieter_id}/' if d.mieter_id else '/neu/dokumente/')
    if request.method == 'POST':
        titel = d.bezeichnung or d.titel or 'Dokument'
        d.delete()
        log_aktion(request, "Dokument gelöscht", titel, '')
        messages.success(request, "🗑️ Dokument gelöscht.")
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_person_loeschen(request, pk):
    """Person (Mieter/Kontakt) löschen. Blockiert bei aktivem Vertrag —
    dieser muss zuerst gekündigt/beendet werden. Entfernt auch den
    verknüpften Mieterportal-Zugang."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    m = get_object_or_404(Mieter, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/personen/{m.id}/')

    aktive = m.vertraege.filter(status='aktiv').count()
    if aktive:
        messages.error(request, f"❌ Person kann nicht gelöscht werden: {aktive} aktive(r) Vertrag/Verträge. Bitte zuerst kündigen/beenden.")
        return redirect(f'/neu/personen/{m.id}/')

    name = m.display_name
    anz_vertraege = m.vertraege.count()
    # Verknüpften Portal-Login mitentfernen
    if m.benutzer_id:
        from core.auth import konto_freigeben
        _konto = m.benutzer
        m.benutzer = None
        m.save(update_fields=['benutzer'])
        konto_freigeben(_konto, getattr(request, 'organisation', None))
    log_aktion(request, "Person gelöscht", name,
               f"inkl. {anz_vertraege} Vertrag/Verträge + zugehörige Daten" if anz_vertraege else "")
    m.delete()   # cascade: Verträge (beendet/Entwurf), Kommunikation, Dokumente etc.
    zusatz = f" inkl. {anz_vertraege} beendete(r)/Entwurf-Vertrag/Verträge" if anz_vertraege else ""
    messages.success(request, f'🗑️ „{name}" gelöscht{zusatz}.')
    return redirect('/neu/personen/')


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_person_dsg_loeschen(request, pk):
    """DSG-Löschung: anonymisiert die Personendaten (Recht auf Löschung), behält
    aber die Buchungsbelege (10-Jahres-Aufbewahrung Art. 958f OR). Bewerber-
    Dokumente (Ausweis/Lohn/Betreibung) werden physisch gelöscht."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.services.dsg import anonymisiere_person
    from core.auth import log_aktion
    m = get_object_or_404(Mieter, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/personen/{m.id}/')
    name = m.display_name
    grund = (request.POST.get('grund') or '').strip()
    ok, meldung = anonymisiere_person(m, grund=grund, user=request.user)
    if ok:
        log_aktion(request, "DSG-Anonymisierung", name, grund or "Personendaten anonymisiert (Belege bleiben).")
        messages.success(request, f"🔒 {meldung}")
    else:
        messages.error(request, f"❌ {meldung}")
    return redirect(f'/neu/personen/{m.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_person_adresse_neu(request, pk):
    """Fügt eine datierte Adress-Zeile hinzu (Wohn- oder Korrespondenzadresse)
    mit «gültig ab» — analog zum Sollmietzins. Der Auto-Sync führt danach die
    effektive Zustelladresse nach."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import MieterAdresse
    from core.auth import log_aktion
    m = get_object_or_404(Mieter, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/personen/{m.id}/')
    P = request.POST
    art = P.get('art', 'wohn')
    if art not in ('wohn', 'korrespondenz'):
        art = 'wohn'
    try:
        gab = date.fromisoformat((P.get('gueltig_ab') or '').strip())
    except ValueError:
        messages.error(request, "❌ Ungültiges «gültig ab»-Datum.")
        return redirect(f'/neu/personen/{m.id}/')
    strasse = P.get('strasse', '').strip()
    plz = P.get('plz', '').strip()
    ort = P.get('ort', '').strip()
    if not (strasse or plz or ort):
        messages.error(request, "❌ Bitte mindestens Strasse oder PLZ/Ort erfassen.")
        return redirect(f'/neu/personen/{m.id}/')
    MieterAdresse.objects.update_or_create(
        mieter=m, art=art, gueltig_ab=gab,
        defaults=dict(strasse=strasse, adresszusatz=P.get('adresszusatz', '').strip(),
                      plz=plz, ort=ort, quelle='manuell',
                      notiz=P.get('notiz', '').strip()))
    m.sync_effektive_adresse()
    log_aktion(request, "Adresse hinterlegt", m.display_name,
               f"{art} ab {gab:%d.%m.%Y}: {strasse}, {plz} {ort}", ziel=m)
    messages.success(request, "✅ Adresse gespeichert.")
    return redirect(f'/neu/personen/{m.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_person_adresse_loeschen(request, pk):
    """Entfernt eine datierte Adress-Zeile und führt die effektive Adresse nach."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import MieterAdresse
    from core.auth import log_aktion
    adr = get_object_or_404(MieterAdresse, id=pk)
    m = adr.mieter
    if request.method == 'POST':
        info = f"{adr.get_art_display()} ab {adr.gueltig_ab:%d.%m.%Y}"
        adr.delete()
        m.sync_effektive_adresse()
        log_aktion(request, "Adresse entfernt", m.display_name, info, ziel=m)
        messages.success(request, "✅ Adress-Zeile entfernt.")
    return redirect(f'/neu/personen/{m.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_person_form(request, pk=None):
    """Person (Mieter/Kontakt) erfassen oder bearbeiten — Fairwalter-Stil."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion, snapshot_model, diff_model
    m = get_object_or_404(Mieter, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
        # Alt-Zustand für Vorher→Nachher (nur beim Bearbeiten, frisch aus der DB).
        alt_snap = snapshot_model(Mieter.objects.get(pk=m.pk)) if m is not None else {}
        obj = m or Mieter()
        obj.typ = P.get('typ', 'person')
        obj.anrede = P.get('anrede', '').strip()
        obj.vorname = P.get('vorname', '').strip()
        obj.nachname = P.get('nachname', '').strip()
        obj.firmen_name = P.get('firmen_name', '').strip()
        obj.uid_nummer = P.get('uid_nummer', '').strip()
        obj.kontaktperson = P.get('kontaktperson', '').strip()
        obj.email = P.get('email', '').strip()
        obj.telefon_privat = P.get('telefon_privat', '').strip()
        obj.mobile = P.get('mobile', '').strip()
        obj.strasse = P.get('strasse', '').strip()
        obj.adresszusatz = P.get('adresszusatz', '').strip()
        obj.plz = P.get('plz', '').strip()
        obj.ort = P.get('ort', '').strip()
        obj.land = P.get('land', '').strip() or 'Schweiz'
        gd = P.get('geburtsdatum', '').strip()
        try:
            obj.geburtsdatum = date.fromisoformat(gd) if gd else None
        except ValueError:
            obj.geburtsdatum = None
        # --- Identität / Vermietungsprüfung ---
        obj.zivilstand = P.get('zivilstand', '').strip()
        obj.nationalitaet = P.get('nationalitaet', '').strip()
        obj.heimatort = P.get('heimatort', '').strip()
        obj.ahv_nummer = P.get('ahv_nummer', '').strip()
        obj.sprache = P.get('sprache', 'de').strip() or 'de'
        obj.telefon_geschaeft = P.get('telefon_geschaeft', '').strip()
        # --- Aufenthalt ---
        obj.aufenthaltsbewilligung = P.get('aufenthaltsbewilligung', '').strip()
        bgb = P.get('bewilligung_gueltig_bis', '').strip()
        try:
            obj.bewilligung_gueltig_bis = date.fromisoformat(bgb) if bgb else None
        except ValueError:
            obj.bewilligung_gueltig_bis = None
        # --- Beruf & Bonität ---
        obj.erwerbsstatus = P.get('erwerbsstatus', '').strip()
        obj.beruf = P.get('beruf', '').strip()
        obj.arbeitgeber = P.get('arbeitgeber', '').strip()
        obj.einkommen_jahr = P.get('einkommen_jahr', '').strip()
        bd = P.get('bonitaet_datum', '').strip()
        try:
            obj.bonitaet_datum = date.fromisoformat(bd) if bd else None
        except ValueError:
            obj.bonitaet_datum = None
        # --- Versicherung & Notfall ---
        obj.haftpflicht_gesellschaft = P.get('haftpflicht_gesellschaft', '').strip()
        obj.haftpflicht_police = P.get('haftpflicht_police', '').strip()
        obj.notfall_name = P.get('notfall_name', '').strip()
        obj.notfall_telefon = P.get('notfall_telefon', '').strip()
        obj.notfall_beziehung = P.get('notfall_beziehung', '').strip()
        # --- Haushalt ---
        def _pint(key):
            try:
                return max(0, int(P.get(key, '') or 0))
            except ValueError:
                return 0
        obj.haushalt_erwachsene = _pint('haushalt_erwachsene')
        obj.haushalt_kinder = _pint('haushalt_kinder')
        obj.haustiere = P.get('haustiere') == 'on'
        obj.haustiere_details = P.get('haustiere_details', '').strip()
        # --- Finanzen ---
        obj.bank_name = P.get('bank_name', '').strip()
        obj.iban = P.get('iban', '').strip()
        obj.betreibung_ergebnis = P.get('betreibung_ergebnis', '').strip()
        # --- Zahlungsverkehr ---
        obj.zahlungsart = P.get('zahlungsart', '').strip()
        obj.ebill_email = P.get('ebill_email', '').strip()
        obj.mahnsperre = P.get('mahnsperre') == 'on'
        obj.zahler_name = P.get('zahler_name', '').strip()
        obj.zahler_adresse = P.get('zahler_adresse', '').strip()
        obj.zahler_iban = P.get('zahler_iban', '').strip()
        # --- Vorvermieter-Referenz ---
        obj.ref_vermieter_name = P.get('ref_vermieter_name', '').strip()
        obj.ref_vermieter_telefon = P.get('ref_vermieter_telefon', '').strip()
        obj.ref_vermieter_email = P.get('ref_vermieter_email', '').strip()
        # --- Vertretung / Beistand ---
        obj.vertretung_art = P.get('vertretung_art', '').strip()
        obj.vertretung_name = P.get('vertretung_name', '').strip()
        obj.vertretung_kontakt = P.get('vertretung_kontakt', '').strip()
        obj.notizen = P.get('notizen', '').strip()

        # --- Pflichtfeld-Validierung ---
        # Nachname nur bei Privatpersonen Pflicht; Firma UND Verein/Stiftung
        # brauchen stattdessen den Firmen-/Organisationsnamen.
        fehler = []
        if obj.typ in ('firma', 'verein'):
            if not obj.firmen_name:
                fehler.append("Firmen-/Organisationsname ist erforderlich.")
        else:
            if not obj.nachname:
                fehler.append("Nachname ist erforderlich.")
        if obj.email and '@' not in obj.email:
            fehler.append("E-Mail-Adresse ist ungültig.")
        if obj.iban:
            from core.services.iban import ist_gueltige_iban, formatiere_iban
            if not ist_gueltige_iban(obj.iban):
                fehler.append("IBAN ist ungültig (Prüfsumme stimmt nicht).")
            else:
                obj.iban = formatiere_iban(obj.iban)
        if fehler:
            for f in fehler:
                messages.error(request, f"❌ {f}")
            # Die eingegebene Korrespondenzadresse zurückgeben, sonst rendert das
            # Formular die k_*-Felder leer (sie kommen sonst aus `korr_adr`) — und
            # beim nächsten Speichern löscht der leere-Felder-Zweig unten die
            # bestehende Korrespondenzadresse. Ein Fehler in EINEM Feld (z.B. der
            # IBAN) darf keine andere, gültige Angabe stillschweigend wegräumen.
            from types import SimpleNamespace
            korr_eingabe = SimpleNamespace(
                strasse=P.get('k_strasse', ''), adresszusatz=P.get('k_adresszusatz', ''),
                plz=P.get('k_plz', ''), ort=P.get('k_ort', ''))
            return render(request, 'fw/person_form.html', {
                **basis, 'nav': 'personen', 'm': obj, 'ist_neu': pk is None,
                'korr_adr': korr_eingabe,
            })

        # --- Dublettenprüfung (nur neue Person, überspringbar) ---
        if not pk and P.get('dublette_ok') != '1':
            dubletten = _finde_dubletten(obj.typ, obj.vorname, obj.nachname,
                                         obj.firmen_name, obj.email, obj.plz)
            if dubletten:
                return render(request, 'fw/person_form.html', {
                    **basis, 'nav': 'personen', 'm': obj, 'ist_neu': True,
                    'dubletten': dubletten, 'dublette_warnung': True,
                })

        obj.save()
        # --- Datierte Adress-Historie pflegen (Wohn- + Korrespondenzadresse) ---
        # Die Formularfelder bearbeiten die AKTUELLE Zeile (Korrektur), nicht einen
        # Umzug — ein Umzug entsteht über Vertragsbeginn/Auszug mit eigenem «gültig ab».
        from crm.models import MieterAdresse
        from datetime import date as _date
        heute = timezone.localdate()
        SENTINEL = _date(2000, 1, 1)
        w = (P.get('strasse', '').strip(), P.get('adresszusatz', '').strip(),
             P.get('plz', '').strip(), P.get('ort', '').strip())
        wohn = obj.aktuelle_wohnadresse(heute)
        if any(w):
            if wohn:
                if (wohn.strasse, wohn.adresszusatz, wohn.plz, wohn.ort) != w:
                    wohn.strasse, wohn.adresszusatz, wohn.plz, wohn.ort = w
                    wohn.save()
            else:
                MieterAdresse.objects.create(
                    mieter=obj, art='wohn', gueltig_ab=SENTINEL,
                    strasse=w[0], adresszusatz=w[1], plz=w[2], ort=w[3], quelle='manuell')
        k = (P.get('k_strasse', '').strip(), P.get('k_adresszusatz', '').strip(),
             P.get('k_plz', '').strip(), P.get('k_ort', '').strip())
        korr = obj.aktuelle_korrespondenzadresse(heute)
        if any(k):
            if korr:
                korr.strasse, korr.adresszusatz, korr.plz, korr.ort = k
                korr.save()
            else:
                MieterAdresse.objects.create(
                    mieter=obj, art='korrespondenz', gueltig_ab=SENTINEL,
                    strasse=k[0], adresszusatz=k[1], plz=k[2], ort=k[3], quelle='manuell')
        elif korr and korr.quelle == 'manuell':
            korr.delete()  # Korrespondenzadresse geleert → kein Zustell-Vorrang mehr
        obj.sync_effektive_adresse(heute)
        aenderungen = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
        log_aktion(request, "Person bearbeitet" if pk else "Person erstellt",
                   obj.display_name, aenderungen, ziel=obj)
        messages.success(request, f"✅ {obj.display_name} gespeichert.")
        return redirect(f'/neu/personen/{obj.id}/')

    return render(request, 'fw/person_form.html', {
        **basis, 'nav': 'personen', 'm': m,
        'ist_neu': m is None,
        'korr_adr': m.aktuelle_korrespondenzadresse() if m else None,
    })


def _finde_dubletten(typ, vorname, nachname, firmen_name, email, plz, exclude_id=None):
    """Findet mögliche Dubletten: gleiche E-Mail ODER (Name + PLZ)."""
    from django.db.models import Q
    qs = Mieter.objects.all()
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    bedingung = Q(pk__in=[])
    if email:
        bedingung |= Q(email__iexact=email)
    if typ in ('firma', 'verein') and firmen_name:
        bedingung |= Q(firmen_name__iexact=firmen_name)
    elif nachname:
        namensfilter = Q(nachname__iexact=nachname)
        if vorname:
            namensfilter &= Q(vorname__iexact=vorname)
        if plz:
            namensfilter &= Q(plz=plz)
        bedingung |= namensfilter
    treffer = qs.filter(bedingung).distinct()[:5]
    return [{'id': t.id, 'name': t.display_name, 'email': t.email,
             'ort': f"{t.plz} {t.ort}".strip()} for t in treffer]
