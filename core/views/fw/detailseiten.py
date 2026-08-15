# core/views/fw/detailseiten.py
#
# Die Detailseiten mit Breadcrumb und Tabs: Liegenschaft, Objekt, Vertrag —
# samt allem, was daran haengt (Ausstattung, Geraete, Zaehler, Schluessel,
# Sollmietzins, Staffeln, Fotos, Schlussabrechnung).
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Der groesste Block der Datei: 1'800 Zeilen, 33 Views. Bewusst zuletzt
# verschoben — nach 29 kleineren Bloecken war das Verfahren eingespielt und
# die geteilten Helfer laengst in _basis.py.

import logging
from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (darf_oeffnen, rolle_erforderlich, ROLLE_VERWALTUNG, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from crm.models import Mieter, Organisation
from finance.models import DebitorenRechnung, Zahlungseingang
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag

logger = logging.getLogger(__name__)

from ._basis import (_global_filter, _kaution_bilanziert, _num, _pendenz_ziel,
                     STATUS_PILL, VERTRAG_PILL)


# ============================================================
# ETAPPE C: DETAILSEITEN MIT BREADCRUMB + TABS
# ============================================================

def _vertrag_status_pill(v):
    label, cls = VERTRAG_PILL.get(v.status, (v.status, 'bg-slate-100 text-slate-500'))
    return {'label': label, 'cls': cls}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_liegenschaft_detail(request, pk):
    from portfolio.models import Unterhalt
    from portfolio.models import Dokument as PortfolioDokument
    from rentals.models import Dokument as RentalsDokument
    from tickets.models import SchadenMeldung

    lg = get_object_or_404(Liegenschaft.objects.select_related('eigentuemer', 'organisation'), id=pk)
    basis = _global_filter(request)

    einheiten_rows = []
    soll_monat = Decimal('0.00')
    vermietet = 0
    for e in lg.einheiten.all().order_by('bezeichnung'):
        vertrag = (Mietvertrag.objects.filter(einheit=e, status='aktiv')
                   .select_related('mieter').order_by('-beginn').first())
        if vertrag:
            vermietet += 1
            soll_monat += vertrag.brutto_mietzins
        einheiten_rows.append({'einheit': e, 'vertrag': vertrag})

    tickets = (SchadenMeldung.objects.filter(liegenschaft=lg)
               .exclude(status='erledigt').order_by('-erstellt_am')[:10])

    # Dokumente der Liegenschaft — nach Objekt (Einheit) gruppiert. Vertrags-
    # gebundene Dokumente (Mietvertrag, Mietzinsanpassung, Kündigung …) erscheinen
    # hier bewusst NICHT — sie leben am Mietverhältnis (Objekt → «Verhältnisse»)
    # und bei der Person. Der Liegenschafts-Tab zeigt nur gebäude-/objektbezogene
    # Dokumente ohne Vertragsbezug (Versicherung, Pläne, Reglemente …).
    einheiten = [row['einheit'] for row in einheiten_rows]
    from collections import defaultdict
    buckets = defaultdict(list)
    from datetime import datetime as _dt
    def _sortkey(val):
        # date ODER datetime → immer als datetime vergleichbar machen
        if val is None:
            return _dt.min
        if isinstance(val, _dt):
            return val.replace(tzinfo=None)
        return _dt.combine(val, _dt.min.time())
    for d in (RentalsDokument.objects
              .filter(Q(liegenschaft=lg) | Q(einheit__liegenschaft=lg))
              .filter(vertrag__isnull=True)
              .select_related('einheit').distinct().order_by('-datum')):
        eid = d.einheit_id
        buckets[eid].append({'titel': d.bezeichnung or d.titel, 'kategorie': d.kategorie,
                             'datum': d.ablage_zeit, 'url': d.datei.url if d.datei else None,
                             'id': d.id, 'del_url': f'/neu/dokument/{d.id}/loeschen/'})
    for d in (PortfolioDokument.objects
              .filter(Q(liegenschaft=lg) | Q(einheit__liegenschaft=lg))
              .select_related('einheit').distinct().order_by('-datum')):
        buckets[d.einheit_id].append({'titel': d.titel, 'kategorie': d.kategorie,
                                      'datum': d.datum, 'url': d.datei.url if d.datei else None,
                                      'id': d.id, 'del_url': f'/neu/dokumente/{d.id}/loeschen/'})
    for lst in buckets.values():
        lst.sort(key=lambda d: _sortkey(d['datum']), reverse=True)
    # Reihenfolge: Liegenschaft (allgemein) zuerst, dann je Objekt
    dok_gruppen = []
    if buckets.get(None):
        dok_gruppen.append({'einheit': None, 'label': 'Liegenschaft (allgemein)',
                            'dokumente': buckets[None]})
    for e in einheiten:
        if buckets.get(e.id):
            dok_gruppen.append({'einheit': e, 'label': e.bezeichnung,
                                'dokumente': buckets[e.id]})
    dok_total = sum(len(g['dokumente']) for g in dok_gruppen)

    unterhalt = Unterhalt.objects.filter(liegenschaft=lg).order_by('-datum')[:10]
    perioden = lg.abrechnungen.order_by('-start_datum')[:6]

    from portfolio.models import Wartungsfrist
    heute = timezone.localdate()
    wartungsfristen = []
    for wf in lg.wartungsfristen.filter(aktiv=True).order_by('naechste_faelligkeit'):
        tage = (wf.naechste_faelligkeit - heute).days
        wartungsfristen.append({
            'wf': wf, 'tage': tage,
            'faellig_bald': 0 <= tage <= 60, 'ueberfaellig': tage < 0,
        })

    # Technik: allgemeine Geräte (Heizung/Boiler/…) + Zähler (Allgemeinstrom/…)
    from portfolio.models import Geraet, Zaehler
    lg_geraete = list(Geraet.objects.filter(liegenschaft=lg).order_by('kategorie'))
    lg_zaehler = list(Zaehler.objects.filter(liegenschaft=lg).order_by('typ'))
    technik_count = len(lg_geraete) + len(lg_zaehler)

    tab_liste = [
        ('objekte', 'Objekte', len(einheiten_rows)),
        ('finanzen', 'Finanzen', None),
        ('technik', 'Technik', technik_count or None),
        ('unterhalt', 'Unterhalt', unterhalt.count() or None),
        ('fristen', 'Fristen', len(wartungsfristen) or None),
        ('schaeden', 'Schäden', tickets.count() or None),
        ('dokumente', 'Dokumente', dok_total or None),
    ]
    from core.services.rendite import liegenschaft_rendite
    rendite = liegenschaft_rendite(lg)
    return render(request, 'fw/liegenschaft_detail.html', {
        **basis, 'nav': 'liegenschaften', 'lg': lg,
        'einheiten_rows': einheiten_rows,
        'total_einheiten': len(einheiten_rows),
        'vermietet': vermietet,
        'leerstand': len(einheiten_rows) - vermietet,
        'soll_monat': soll_monat,
        'rendite': rendite,
        'tickets': tickets,
        'dok_gruppen': dok_gruppen,
        'dok_total': dok_total,
        'unterhalt': unterhalt,
        'wartungsfristen': wartungsfristen,
        'perioden': perioden,
        'versicherungen': list(lg.versicherungen.all()),
        'heute_iso': timezone.localdate().isoformat(),
        'lg_geraete': lg_geraete,
        'lg_zaehler': lg_zaehler,
        'geraet_kategorien': GERAET_KATEGORIEN,
        'zaehler_typen': ZAEHLER_TYPEN,
        'tab_liste': tab_liste,
    })


# Kuratierte Standard-Ausstattungsmerkmale (CH) für die schnelle Häkchen-Liste
MERKMALE_STANDARD = [
    'Balkon', 'Terrasse', 'Sitzplatz', 'Garten (Mitbenützung)', 'Lift',
    'Einbauküche', 'Geschirrspüler', 'Glaskeramik-Kochfeld', 'Steamer / Dampfgarer',
    'Waschmaschine (in Wohnung)', 'Waschturm', 'Anschluss Waschmaschine',
    'Keller / Kellerabteil', 'Estrich / Estrichabteil', 'Reduit',
    'Cheminée', 'Parkett', 'Plattenboden', 'Laminat',
    'Bad/WC', 'Sep. WC', 'Dusche', 'Badewanne',
    'Kabel-TV', 'Glasfaser', 'Rollläden / Storen', 'Lamellenstoren',
    'Barrierefrei / Rollstuhlgängig', 'Minergie', 'Bodenheizung',
    'Garage', 'Aussenparkplatz', 'Veloraum', 'Trockenraum',
    'Möbliert', 'Haustiere erlaubt',
]


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_merkmale_speichern(request, pk):
    """Speichert die Ausstattungsmerkmale (Häkchen + eigene) eines Objekts."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    e = get_object_or_404(Einheit, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/objekte/{e.id}/')
    gewaehlt = [m.strip() for m in request.POST.getlist('merkmale') if m.strip()]
    # Eigene Merkmale (Komma- oder Zeilen-getrennt) ergänzen
    eigene = (request.POST.get('merkmale_eigene') or '').replace('\n', ',')
    for m in eigene.split(','):
        m = m.strip()
        if m and m not in gewaehlt:
            gewaehlt.append(m)
    # Reihenfolge stabil + dedupliziert
    seen, clean = set(), []
    for m in gewaehlt:
        if m not in seen:
            seen.add(m); clean.append(m)
    e.merkmale = clean
    e.save(update_fields=['merkmale'])
    log_aktion(request, "Ausstattungsmerkmale gespeichert", e.bezeichnung, f"{len(clean)} Merkmale")
    messages.success(request, "✅ Ausstattungsmerkmale gespeichert.")
    return redirect(f'/neu/objekte/{e.id}/')


def merkmale_optionen(aktuelle=None):
    """Standardliste + alle bereits irgendwo verwendeten eigenen Merkmale."""
    optionen = list(MERKMALE_STANDARD)
    seen = set(optionen)
    for e in Einheit.objects.exclude(merkmale=[]).only('merkmale'):
        for m in (e.merkmale or []):
            if m and m not in seen:
                seen.add(m); optionen.append(m)
    for m in (aktuelle or []):
        if m and m not in seen:
            seen.add(m); optionen.append(m)
    return optionen


# Vorschlagslisten (datalist) für Geräte-Kategorien und Zähler-Typen
GERAET_KATEGORIEN = [
    'Heizung', 'Boiler / Wassererwärmer', 'Wärmepumpe', 'Lüftung', 'Klimaanlage',
    'Aufzug', 'Waschmaschine', 'Tumbler', 'Geschirrspüler', 'Backofen', 'Kochfeld',
    'Kühlschrank', 'Dampfabzug', 'Rauchmelder', 'Solaranlage', 'Photovoltaik',
    'Gartengerät', 'Tor / Antrieb', 'Sonstiges',
]
ZAEHLER_TYPEN = [
    'Allgemeinstrom', 'Strom', 'Wasser kalt', 'Wasser warm', 'Gas',
    'Wärmezähler', 'Öl', 'Fernwärme', 'Sonstiges',
]


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_wartungsfrist_neu(request, pk):
    """Wartungs-/Versicherungsfrist zu einer Liegenschaft erfassen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Wartungsfrist
    from core.auth import log_aktion
    lg = get_object_or_404(Liegenschaft, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/liegenschaften/{lg.id}/')
    bez = (request.POST.get('bezeichnung') or '').strip()
    faellig = (request.POST.get('naechste_faelligkeit') or '').strip()
    if not bez or not faellig:
        messages.error(request, "Bezeichnung und Fälligkeitsdatum sind erforderlich.")
        return redirect(f'/neu/liegenschaften/{lg.id}/')
    try:
        faellig_d = date.fromisoformat(faellig)
    except ValueError:
        messages.error(request, "Ungültiges Datum.")
        return redirect(f'/neu/liegenschaften/{lg.id}/')
    try:
        intervall = int(request.POST.get('intervall_monate') or 12)
    except ValueError:
        intervall = 12
    Wartungsfrist.objects.create(
        liegenschaft=lg, art=request.POST.get('art', 'wartung'),
        bezeichnung=bez, anbieter=(request.POST.get('anbieter') or '').strip(),
        naechste_faelligkeit=faellig_d, intervall_monate=max(0, intervall),
        notiz=(request.POST.get('notiz') or '').strip())
    log_aktion(request, "Wartungsfrist erfasst", str(lg), bez)
    messages.success(request, f'✅ Frist „{bez}" gespeichert.')
    return redirect(f'/neu/liegenschaften/{lg.id}/?tab=fristen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_wartungsfrist_loeschen(request, pk):
    """Wartungs-/Versicherungsfrist löschen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Wartungsfrist
    wf = get_object_or_404(Wartungsfrist.objects.select_related('liegenschaft'), id=pk)
    lg_id = wf.liegenschaft_id
    if request.method == 'POST':
        from core.auth import log_aktion
        from core.models import Pendenz
        bez = f"{wf.bezeichnung} · {wf.liegenschaft}"
        # Zugehörige Auto-Frist-Pendenz(en) mitlöschen — sie hängen nur über einen
        # `quelle`-String (kein FK) und würden sonst als verwaiste Frist stehen bleiben.
        Pendenz.objects.filter(quelle__startswith=f"auto:wartung:{wf.id}:").delete()
        wf.delete()
        log_aktion(request, "Wartungsfrist gelöscht", bez, '')
        messages.success(request, "🗑️ Frist gelöscht.")
    return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_wartungsfrist_bearbeiten(request, pk):
    """Wartungs-/Versicherungsfrist bearbeiten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Wartungsfrist
    from core.auth import log_aktion
    wf = get_object_or_404(Wartungsfrist.objects.select_related('liegenschaft'), id=pk)
    lg_id = wf.liegenschaft_id
    if request.method != 'POST':
        return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')
    bez = (request.POST.get('bezeichnung') or '').strip()
    faellig = (request.POST.get('naechste_faelligkeit') or '').strip()
    if not bez or not faellig:
        messages.error(request, "Bezeichnung und Fälligkeitsdatum sind erforderlich.")
        return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')
    try:
        wf.naechste_faelligkeit = date.fromisoformat(faellig)
    except ValueError:
        messages.error(request, "Ungültiges Datum.")
        return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')
    wf.art = request.POST.get('art', wf.art) or wf.art
    wf.bezeichnung = bez
    wf.anbieter = (request.POST.get('anbieter') or '').strip()
    try:
        wf.intervall_monate = max(0, int(request.POST.get('intervall_monate') or wf.intervall_monate))
    except ValueError:
        pass
    wf.notiz = (request.POST.get('notiz') or '').strip()
    wf.save()
    log_aktion(request, "Wartungsfrist bearbeitet", bez, '')
    messages.success(request, f'✅ Frist „{bez}" aktualisiert.')
    return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_objekt_detail(request, pk):
    from portfolio.models import Geraet, Zaehler, Ausstattung
    from core.services.raumkatalog import RAUMTYPEN, RAUM_KATALOG
    e = get_object_or_404(Einheit.objects.select_related('liegenschaft'), id=pk)
    basis = _global_filter(request)

    aktiver_vertrag = (Mietvertrag.objects.filter(einheit=e, status='aktiv')
                       .select_related('mieter').order_by('-beginn').first())
    if not aktiver_vertrag:
        aktiver_vertrag = (Mietvertrag.objects
                           .filter(nebenobjekte=e, status='aktiv')
                           .select_related('mieter').order_by('-beginn').first())
    # «Verhältnisse»: jedes Mietverhältnis (= Vertrag) an diesem Objekt — aktiv
    # UND beendet — als Bündel mit den zugehörigen Dokumenten (Vertrag, Mietzins-
    # anpassung, Kündigung, Protokoll …). Das Verhältnis IST der Vertrag; die
    # Dokumente hängen bereits per FK daran (rentals.Dokument.vertrag).
    from rentals.models import Dokument as RentalsDokument
    from django.db.models import Q as _Q
    from collections import defaultdict
    _vertraege = (Mietvertrag.objects.filter(_Q(einheit=e) | _Q(nebenobjekte=e))
                  .select_related('mieter', 'mitmieter')
                  .distinct().order_by('-beginn'))
    _dok_pro_vertrag = defaultdict(list)
    for d in (RentalsDokument.objects.filter(vertrag__in=_vertraege)
              .order_by('-datum')):
        _dok_pro_vertrag[d.vertrag_id].append(d)
    verhaeltnisse = []
    for v in _vertraege:
        namen = [v.mieter.display_name if v.mieter else '']
        if v.mitmieter_id:
            namen.append(v.mitmieter.display_name)
        elif v.mitmieter_name:
            namen.append(v.mitmieter_name)
        verhaeltnisse.append({
            'v': v,
            'namen': ' · '.join(n for n in namen if n),
            'pill': _vertrag_status_pill(v),
            'dokumente': _dok_pro_vertrag.get(v.id, []),
        })
    verhaeltnisse_dok_total = sum(len(x['dokumente']) for x in verhaeltnisse)

    geraete = Geraet.objects.filter(einheit=e).order_by('kategorie')
    zaehler = Zaehler.objects.filter(einheit=e).order_by('typ')
    fotos = list(e.fotos.all())

    # Sollmietzins-Komponenten (datierte Netto-/NK-Historie). Die aktuell gültige
    # Zeile wird markiert; sie steuert nettomiete_aktuell/nebenkosten_aktuell.
    sollmietzinse = list(e.sollmietzinse.all())
    aktueller_soll = e.aktueller_sollmietzins()
    aktueller_soll_id = aktueller_soll.id if aktueller_soll else None

    # Staffelmiete (Art. 269c):
    #  - OBJEKT-Vorlage (Plan, belegt neue Verträge vor) — wie Sollmietzins.
    #  - Stufen des AKTIVEN Vertrags (live, verrechnungswirksam) — nur wenn der
    #    laufende Vertrag tatsächlich eine Staffelmiete ist.
    staffelvorlagen = list(e.staffelvorlagen.all())
    zeige_staffelvorlage = (e.mietrecht_kategorie == 'gewerbe')
    staffelstufen = list(aktiver_vertrag.staffelstufen.all()) if aktiver_vertrag else []
    zeige_staffel = bool(aktiver_vertrag) and aktiver_vertrag.mietzins_modell == 'staffel'


    # Aktuelle Marktwerte als Vorbelegung für die Indexbasis neuer Sollmietzins-Zeilen
    from crm.models import Organisation as _Vw
    _vw = _Vw.objects.first()
    aktueller_ref_zins = _vw.aktueller_referenzzinssatz if _vw else Decimal('1.25')
    aktueller_lik = _vw.aktueller_lik_punkte if _vw else Decimal('107.1')

    # Ausstattung/Raumbuch — die Räume entstehen aus den erfassten Assets.
    ausst = list(Ausstattung.objects.filter(einheit=e)
                 .prefetch_related('schaeden__handwerker_auftraege'))
    raeume = []
    for a in ausst:
        zw = a.zeitwert()
        n_schaden = a.schaeden.count()
        row = {'a': a, 'zeitwert': zw, 'lebensdauer': a.effektive_lebensdauer(),
               'rest': a.rest_jahre(), 'ersatz_status': a.ersatz_status(),
               'schaden_anzahl': n_schaden,
               'reparaturkosten': a.reparatur_kosten_total() if n_schaden else None}
        if raeume and raeume[-1]['raum'] == a.raum:
            raeume[-1]['elemente'].append(row)
        else:
            raeume.append({'raum': a.raum, 'elemente': [row]})
    ausst_count = len(ausst)

    # Schlüsselregister: Bestand + offene Ausgaben je Schlüssel, Empfänger-Auswahl
    from portfolio.models import Schluessel
    from crm.models import Handwerker as _Hw
    schluessel_rows = []
    for sch in (Schluessel.objects.filter(einheit=e)
                .prefetch_related('ausgaben__mieter', 'ausgaben__handwerker')):
        offene = [a for a in sch.ausgaben.all() if a.rueckgabe_am is None]
        schluessel_rows.append({'s': sch, 'offene': offene,
                                'verfuegbar': max(0, sch.anzahl - len(offene))})
    schluessel_empfaenger = {
        'mieter': list({v.mieter for v in _vertraege if v.status == 'aktiv' and v.mieter_id}),
        'handwerker': list(_Hw.objects.order_by('firma')),
    }
    schluessel_offen_count = sum(len(r['offene']) for r in schluessel_rows)

    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('fotos', 'Fotos', len(fotos) or None),
        ('raumbuch', 'Raumbuch', ausst_count or None),
        ('verhaeltnisse', 'Verhältnisse', len(verhaeltnisse) or None),
        ('mietzins', 'Mietzins', len(sollmietzinse) or None),
        ('geraete', 'Geräte', geraete.count() or None),
        ('zaehler', 'Zähler', zaehler.count() or None),
        ('schluessel', 'Schlüssel', len(schluessel_rows) or None),
    ]
    from django.contrib import messages
    return render(request, 'fw/objekt_detail.html', {
        **basis, 'nav': 'objekte', 'e': e,
        'aktiver_vertrag': aktiver_vertrag,
        'vertrag_pill': _vertrag_status_pill(aktiver_vertrag) if aktiver_vertrag else None,
        'verhaeltnisse': verhaeltnisse,
        'verhaeltnisse_dok_total': verhaeltnisse_dok_total,
        'geraete': geraete,
        'zaehler': zaehler,
        'sollmietzinse': sollmietzinse,
        'aktueller_soll_id': aktueller_soll_id,
        'staffelstufen': staffelstufen,
        'zeige_staffel': zeige_staffel,
        'staffelvorlagen': staffelvorlagen,
        'zeige_staffelvorlage': zeige_staffelvorlage,
        'aktueller_ref_zins': aktueller_ref_zins,
        'aktueller_lik': aktueller_lik,
        'fotos': fotos,
        'raeume': raeume,
        'ausst_count': ausst_count,
        'raumtypen': RAUMTYPEN,
        'raum_katalog': RAUM_KATALOG,
        'zustand_choices': Ausstattung.ZUSTAND,
        'geraet_kategorien': GERAET_KATEGORIEN,
        'zaehler_typen': ZAEHLER_TYPEN,
        'merkmale_gewaehlt': e.merkmale or [],
        'merkmale_optionen': merkmale_optionen(e.merkmale or []),
        'tab_liste': tab_liste,
        'schluessel_rows': schluessel_rows,
        'schluessel_empfaenger': schluessel_empfaenger,
        'schluessel_offen_count': schluessel_offen_count,
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_add(request, pk):
    """Erfasst ein Ausstattungselement (Raumbuch) am Objekt. Der Raum ergibt sich
    aus dem eingegebenen Raumnamen — kein separates Raum-CRUD nötig."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    from core.auth import log_aktion
    e = get_object_or_404(Einheit, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/objekte/{e.id}/#obj-raumbuch')

    raum = (request.POST.get('raum') or '').strip()
    kategorie = (request.POST.get('kategorie') or '').strip()
    if not raum or not kategorie:
        messages.error(request, "Raum und Kategorie sind Pflichtfelder.")
        return redirect(f'/neu/objekte/{e.id}/#obj-raumbuch')

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else None
        except Exception:
            return None

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    def _int(x, default=None):
        try:
            return int(x)
        except Exception:
            return default

    # Sortierung ans Ende des jeweiligen Raums
    letzte = (Ausstattung.objects.filter(einheit=e, raum=raum)
              .order_by('-sortierung').first())
    sort = (letzte.sortierung + 1) if letzte else 0

    a = Ausstattung.objects.create(
        einheit=e, raum=raum, kategorie=kategorie,
        bezeichnung=(request.POST.get('bezeichnung') or '').strip(),
        marke=(request.POST.get('marke') or '').strip(),
        modell=(request.POST.get('modell') or '').strip(),
        material=(request.POST.get('material') or '').strip(),
        menge=_int(request.POST.get('menge'), 1) or 1,
        einbau_datum=_date(request.POST.get('einbau_datum')),
        neuwert=_dec(request.POST.get('neuwert')),
        lebensdauer_jahre=_int(request.POST.get('lebensdauer_jahre')),
        zustand=request.POST.get('zustand') or 'gut',
        garantie_bis=_date(request.POST.get('garantie_bis')),
        notiz=(request.POST.get('notiz') or '').strip(),
        sortierung=sort,
    )
    if request.FILES.get('foto'):
        a.foto = request.FILES['foto']
        a.save(update_fields=['foto'])
    log_aktion(request, "Ausstattung erfasst", e.bezeichnung, f"{raum} · {kategorie}")
    messages.success(request, f"✅ «{kategorie}» im Raum «{raum}» erfasst.")
    return redirect(f'/neu/objekte/{e.id}/#obj-raumbuch')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_edit(request, pk):
    """Bearbeitet ein bestehendes Ausstattungselement (Marke/Modell/Material,
    Neuwert, Einbaudatum, Zustand, Garantie, Lebensdauer, Notiz, Foto). So lassen
    sich die aus dem Katalog geladenen Elemente mit echten Daten ergänzen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    from core.auth import log_aktion
    a = get_object_or_404(Ausstattung.objects.select_related('einheit'), id=pk)
    eid = a.einheit_id
    if request.method != 'POST':
        return redirect(f'/neu/objekte/{eid}/#obj-raumbuch')

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else None
        except Exception:
            return None

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    def _int(x, default=None):
        try:
            return int(x)
        except Exception:
            return default

    P = request.POST
    raum = (P.get('raum') or '').strip()
    kategorie = (P.get('kategorie') or '').strip()
    if not raum or not kategorie:
        messages.error(request, "Raum und Kategorie sind Pflichtfelder.")
        return redirect(f'/neu/objekte/{eid}/#obj-raumbuch')
    a.raum = raum
    a.kategorie = kategorie
    a.bezeichnung = (P.get('bezeichnung') or '').strip()
    a.marke = (P.get('marke') or '').strip()
    a.modell = (P.get('modell') or '').strip()
    a.material = (P.get('material') or '').strip()
    a.menge = _int(P.get('menge'), a.menge) or 1
    a.einbau_datum = _date(P.get('einbau_datum'))
    a.neuwert = _dec(P.get('neuwert'))
    a.lebensdauer_jahre = _int(P.get('lebensdauer_jahre'))
    a.zustand = P.get('zustand') or a.zustand
    a.garantie_bis = _date(P.get('garantie_bis'))
    a.notiz = (P.get('notiz') or '').strip()
    if request.FILES.get('foto'):
        a.foto = request.FILES['foto']
    a.save()
    log_aktion(request, "Ausstattung bearbeitet", a.einheit.bezeichnung, f"{raum} · {kategorie}")
    messages.success(request, f"✅ «{kategorie}» aktualisiert.")
    return redirect(f'/neu/objekte/{eid}/#obj-raumbuch')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_katalog(request, pk):
    """Legt für einen Raumtyp die Standard-Ausstattung aus dem Katalog an
    (Schnellerfassung). Vorhandene Elemente werden nicht dupliziert."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    from core.services.raumkatalog import RAUM_KATALOG
    from core.auth import log_aktion
    e = get_object_or_404(Einheit, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/objekte/{e.id}/#obj-raumbuch')

    raumtyp = (request.POST.get('raumtyp') or '').strip()
    elemente = RAUM_KATALOG.get(raumtyp)
    if not elemente:
        messages.error(request, "Unbekannter Raumtyp.")
        return redirect(f'/neu/objekte/{e.id}/#obj-raumbuch')

    vorhanden = set(Ausstattung.objects.filter(einheit=e, raum=raumtyp)
                    .values_list('kategorie', flat=True))
    n = 0
    for i, (kat, jahre) in enumerate(elemente):
        if kat in vorhanden:
            continue
        Ausstattung.objects.create(
            einheit=e, raum=raumtyp, kategorie=kat,
            lebensdauer_jahre=jahre, zustand='gut', sortierung=i)
        n += 1
    if n:
        log_aktion(request, "Raumkatalog geladen", e.bezeichnung, f"{raumtyp}: {n} Elemente")
        messages.success(request, f"✅ {n} Element(e) für «{raumtyp}» angelegt — jetzt Details ergänzen.")
    else:
        messages.info(request, f"«{raumtyp}» ist bereits vollständig erfasst.")
    return redirect(f'/neu/objekte/{e.id}/#obj-raumbuch')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_del(request, pk):
    """Entfernt ein Ausstattungselement."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    a = get_object_or_404(Ausstattung.objects.select_related('einheit'), id=pk)
    eid = a.einheit_id
    if request.method == 'POST':
        a.delete()
        messages.success(request, "Ausstattungselement entfernt.")
    return redirect(f'/neu/objekte/{eid}/#obj-raumbuch')


# --- Geräte (Objekt + allgemeine Liegenschafts-Geräte wie Heizung/Boiler) ---

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_geraet_add(request):
    """Erfasst ein Gerät. Ziel ist entweder ein Objekt (`einheit_id`) oder eine
    Liegenschaft (`liegenschaft_id`, z.B. Heizung, Boiler, Lüftung)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/liegenschaften/')

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    eid = request.POST.get('einheit_id')
    lid = request.POST.get('liegenschaft_id')
    kategorie = (request.POST.get('kategorie') or '').strip()
    if not kategorie:
        kategorie = (request.POST.get('sonstiges_bezeichnung') or 'sonstiges').strip() or 'sonstiges'

    kwargs = dict(
        kategorie=kategorie,
        sonstiges_bezeichnung=(request.POST.get('sonstiges_bezeichnung') or '').strip(),
        marke=(request.POST.get('marke') or '').strip(),
        modell=(request.POST.get('modell') or '').strip(),
        seriennummer=(request.POST.get('seriennummer') or '').strip(),
        kapazitaet=(request.POST.get('kapazitaet') or '').strip(),
        standort=(request.POST.get('standort') or '').strip(),
        installations_datum=_date(request.POST.get('installations_datum')),
        garantie_bis=_date(request.POST.get('garantie_bis')),
        notiz=(request.POST.get('notiz') or '').strip(),
    )
    if eid:
        e = get_object_or_404(Einheit, id=eid)
        Geraet.objects.create(einheit=e, **kwargs)
        log_aktion(request, "Gerät erfasst", e.bezeichnung, kategorie)
        messages.success(request, f"✅ Gerät «{kategorie}» erfasst.")
        return redirect(f'/neu/objekte/{e.id}/?tab=geraete')
    if lid:
        lg = get_object_or_404(Liegenschaft, id=lid)
        Geraet.objects.create(liegenschaft=lg, **kwargs)
        log_aktion(request, "Gerät erfasst", str(lg), kategorie)
        messages.success(request, f"✅ Gerät «{kategorie}» erfasst.")
        return redirect(f'/neu/liegenschaften/{lg.id}/?tab=technik')
    messages.error(request, "Kein Ziel angegeben.")
    return redirect('/neu/liegenschaften/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_geraet_del(request, pk):
    """Entfernt ein Gerät (Objekt- oder Liegenschaftsebene)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    g = get_object_or_404(Geraet, id=pk)
    eid, lid = g.einheit_id, g.liegenschaft_id
    if request.method == 'POST':
        from core.models import Pendenz
        # Verwaiste Auto-Garantie-Pendenz mitlöschen (hängt nur über `quelle`).
        Pendenz.objects.filter(quelle=f"auto:garantie:{g.id}").delete()
        g.delete()
        messages.success(request, "Gerät entfernt.")
    if eid:
        return redirect(f'/neu/objekte/{eid}/?tab=geraete')
    return redirect(f'/neu/liegenschaften/{lid}/?tab=technik')


# --- Zähler (Objekt + allgemeine Liegenschafts-Zähler wie Allgemeinstrom) ---

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zaehler_add(request):
    """Erfasst einen Zähler. Ziel ist entweder ein Objekt (`einheit_id`) oder eine
    Liegenschaft (`liegenschaft_id`, z.B. Allgemeinstrom, Hauptwasser)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Zaehler
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/liegenschaften/')

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else Decimal('0.00')
        except Exception:
            return Decimal('0.00')

    typ = (request.POST.get('typ') or '').strip()
    nummer = (request.POST.get('zaehler_nummer') or '').strip()
    if not typ or not nummer:
        messages.error(request, "Typ und Zähler-Nr. sind Pflichtfelder.")
        ref = request.META.get('HTTP_REFERER') or '/neu/liegenschaften/'
        return redirect(ref)

    kwargs = dict(
        typ=typ, zaehler_nummer=nummer,
        standort=(request.POST.get('standort') or '').strip(),
        aktueller_stand=_dec(request.POST.get('aktueller_stand')),
    )
    eid = request.POST.get('einheit_id')
    lid = request.POST.get('liegenschaft_id')
    if eid:
        e = get_object_or_404(Einheit, id=eid)
        Zaehler.objects.create(einheit=e, **kwargs)
        log_aktion(request, "Zähler erfasst", e.bezeichnung, f"{typ} · {nummer}")
        messages.success(request, f"✅ Zähler «{typ}» erfasst.")
        return redirect(f'/neu/objekte/{e.id}/?tab=zaehler')
    if lid:
        lg = get_object_or_404(Liegenschaft, id=lid)
        Zaehler.objects.create(liegenschaft=lg, **kwargs)
        log_aktion(request, "Zähler erfasst", str(lg), f"{typ} · {nummer}")
        messages.success(request, f"✅ Zähler «{typ}» erfasst.")
        return redirect(f'/neu/liegenschaften/{lg.id}/?tab=technik')
    messages.error(request, "Kein Ziel angegeben.")
    return redirect('/neu/liegenschaften/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zaehler_edit(request, pk):
    """Bearbeitet einen bestehenden Zähler (Typ/Nr./Standort/Stand)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Zaehler
    from core.auth import log_aktion
    z = get_object_or_404(Zaehler, id=pk)
    eid, lid = z.einheit_id, z.liegenschaft_id
    ziel = (f'/neu/objekte/{eid}/?tab=zaehler' if eid
            else f'/neu/liegenschaften/{lid}/?tab=technik')
    if request.method != 'POST':
        return redirect(ziel)

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else Decimal('0.00')
        except Exception:
            return z.aktueller_stand

    typ = (request.POST.get('typ') or '').strip()
    nummer = (request.POST.get('zaehler_nummer') or '').strip()
    if not typ or not nummer:
        messages.error(request, "Typ und Zähler-Nr. sind Pflichtfelder.")
        return redirect(ziel)
    z.typ = typ
    z.zaehler_nummer = nummer
    z.standort = (request.POST.get('standort') or '').strip()
    z.aktueller_stand = _dec(request.POST.get('aktueller_stand'))
    z.save()
    log_aktion(request, "Zähler bearbeitet", f"{typ} · {nummer}", '')
    messages.success(request, f"✅ Zähler «{typ}» aktualisiert.")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zaehler_del(request, pk):
    """Entfernt einen Zähler (Objekt- oder Liegenschaftsebene)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Zaehler
    z = get_object_or_404(Zaehler, id=pk)
    eid, lid = z.einheit_id, z.liegenschaft_id
    if request.method == 'POST':
        z.delete()
        messages.success(request, "Zähler entfernt.")
    if eid:
        return redirect(f'/neu/objekte/{eid}/?tab=zaehler')
    return redirect(f'/neu/liegenschaften/{lid}/?tab=technik')


# --- Schlüsselverwaltung (Register + Ausgabe/Rücknahme je Objekt) ---

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schluessel_add(request):
    """Erfasst einen Schlüssel im Register eines Objekts."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Schluessel
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/objekte/')
    e = get_object_or_404(Einheit.objects.select_related('liegenschaft'),
                          id=request.POST.get('einheit_id'))
    nummer = (request.POST.get('schluessel_nummer') or '').strip()
    typ = (request.POST.get('typ') or 'Wohnung').strip()
    try:
        anzahl = max(1, int(request.POST.get('anzahl') or 1))
    except (TypeError, ValueError):
        anzahl = 1
    if not nummer:
        messages.error(request, "Schlüssel-Nr. ist ein Pflichtfeld.")
        return redirect(f'/neu/objekte/{e.id}/?tab=schluessel')
    Schluessel.objects.create(liegenschaft=e.liegenschaft, einheit=e,
                              typ=typ, schluessel_nummer=nummer, anzahl=anzahl)
    log_aktion(request, "Schlüssel erfasst", f"{e.bezeichnung}", f"{typ} {nummer} × {anzahl}")
    messages.success(request, f"✅ Schlüssel {nummer} ({typ}, {anzahl}×) erfasst.")
    return redirect(f'/neu/objekte/{e.id}/?tab=schluessel')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schluessel_del(request, pk):
    """Entfernt einen Schlüssel aus dem Register (inkl. Ausgabe-Historie)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Schluessel
    sch = get_object_or_404(Schluessel, id=pk)
    eid = sch.einheit_id
    if request.method == 'POST':
        if sch.ausgaben.filter(rueckgabe_am__isnull=True).exists():
            messages.error(request, "Schlüssel ist noch ausgegeben — zuerst Rücknahme erfassen.")
        else:
            sch.delete()
            messages.success(request, "Schlüssel entfernt.")
    return redirect(f'/neu/objekte/{eid}/?tab=schluessel' if eid else '/neu/objekte/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schluessel_ausgabe(request, pk):
    """Gibt einen Schlüssel an einen Mieter oder Handwerker aus."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Schluessel, SchluesselAusgabe
    from crm.models import Handwerker
    from core.auth import log_aktion
    sch = get_object_or_404(Schluessel, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/objekte/{sch.einheit_id}/?tab=schluessel')
    offen = sch.ausgaben.filter(rueckgabe_am__isnull=True).count()
    if offen >= sch.anzahl:
        messages.error(request, f"Alle {sch.anzahl} Exemplare von {sch.schluessel_nummer} sind bereits ausgegeben.")
        return redirect(f'/neu/objekte/{sch.einheit_id}/?tab=schluessel')
    empf = (request.POST.get('empfaenger') or '')
    mieter = handwerker = None
    name = ''
    if empf.startswith('mieter:'):
        mieter = Mieter.objects.filter(id=empf.split(':', 1)[1]).first()
        name = mieter.display_name if mieter else ''
    elif empf.startswith('handwerker:'):
        handwerker = Handwerker.objects.filter(id=empf.split(':', 1)[1]).first()
        name = handwerker.firma if handwerker else ''
    if not (mieter or handwerker):
        messages.error(request, "Bitte Empfänger (Mieter oder Handwerker) wählen.")
        return redirect(f'/neu/objekte/{sch.einheit_id}/?tab=schluessel')
    SchluesselAusgabe.objects.create(schluessel=sch, mieter=mieter, handwerker=handwerker,
                                     ausgegeben_am=timezone.localdate())
    log_aktion(request, "Schlüssel ausgegeben", sch.schluessel_nummer, name)
    messages.success(request, f"✅ Schlüssel {sch.schluessel_nummer} an {name} ausgegeben.")
    return redirect(f'/neu/objekte/{sch.einheit_id}/?tab=schluessel')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schluessel_rueckgabe(request, pk):
    """Erfasst die Rücknahme einer offenen Schlüsselausgabe."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import SchluesselAusgabe
    from core.auth import log_aktion
    a = get_object_or_404(SchluesselAusgabe.objects.select_related('schluessel'), id=pk)
    if request.method == 'POST' and a.rueckgabe_am is None:
        a.rueckgabe_am = timezone.localdate()
        a.save(update_fields=['rueckgabe_am'])
        wer = a.mieter.display_name if a.mieter_id else (a.handwerker.firma if a.handwerker_id else '')
        log_aktion(request, "Schlüssel zurückgenommen", a.schluessel.schluessel_nummer, wer)
        messages.success(request, f"✅ Schlüssel {a.schluessel.schluessel_nummer} zurückgenommen.")
    return redirect(f'/neu/objekte/{a.schluessel.einheit_id}/?tab=schluessel')


# --- Sollmietzins-Komponenten (datierte Netto-/NK-Historie je Objekt) ---

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_sollmietzins_add(request):
    """Erfasst eine datierte Sollmietzins-Zeile (gültig ab) für ein Objekt.
    Der aktuell gültige Wert wird automatisch auf die Einheit abgeleitet;
    neue Verträge übernehmen ihn ab dem Mietbeginn (Bestand bleibt unberührt)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Sollmietzins
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/objekte/')

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else Decimal('0.00')
        except Exception:
            return Decimal('0.00')

    e = get_object_or_404(Einheit, id=request.POST.get('einheit_id'))
    ziel = f'/neu/objekte/{e.id}/?tab=mietzins'
    ab_raw = (request.POST.get('gueltig_ab') or '').strip()
    try:
        ab = date.fromisoformat(ab_raw)
    except ValueError:
        messages.error(request, "Bitte ein gültiges «gültig ab»-Datum angeben.")
        return redirect(ziel)
    netto = _dec(request.POST.get('netto_mietzins'))
    # Einstellplatz → keine Nebenkosten
    nk = Decimal('0.00') if e.ist_einstellplatz else _dec(request.POST.get('nebenkosten'))
    # Rabatt/Erlass (Gratismonat): mindert nur die Verrechnung, nicht die Referenz.
    # "mietzinsfrei" = voller Netto-Erlass → Rabatt = Netto-Referenz.
    if request.POST.get('mietzinsfrei'):
        rabatt_netto = netto
    else:
        rabatt_netto = _dec(request.POST.get('rabatt_netto'))
    rabatt_nk = _dec(request.POST.get('rabatt_nk'))
    rabatt_netto = min(max(rabatt_netto, Decimal('0.00')), netto)   # 0..Referenz
    rabatt_nk = min(max(rabatt_nk, Decimal('0.00')), nk)

    def _dec_opt(x):
        v = _num(x)
        try:
            return Decimal(v) if v else None
        except Exception:
            return None

    Sollmietzins.objects.create(
        einheit=e, gueltig_ab=ab, netto_mietzins=netto, nebenkosten=nk,
        rabatt_netto=rabatt_netto, rabatt_nk=rabatt_nk,
        basis_referenzzinssatz=_dec_opt(request.POST.get('basis_referenzzinssatz')),
        basis_lik_punkte=_dec_opt(request.POST.get('basis_lik_punkte')),
        notiz=(request.POST.get('notiz') or '').strip()[:200],
    )
    zu_zahlen = max(Decimal('0'), netto - rabatt_netto) + max(Decimal('0'), nk - rabatt_nk)
    log_aktion(request, "Sollmietzins erfasst", e.bezeichnung,
               f"ab {ab}: Referenz {netto}+{nk}, Rabatt {rabatt_netto}/{rabatt_nk}, zu zahlen {zu_zahlen}")
    # Ein Erlass ist eine Geld-Entscheidung — die Bestätigung muss ihn benennen
    # und nicht nur eine Summe zeigen, in der er schon verrechnet ist. Ein voller
    # Erlass bekommt zusätzlich einen Warnton statt eines Häkchens.
    if rabatt_netto >= netto > 0:
        messages.warning(
            request,
            f"⚠️ Sollmietzins ab {ab.strftime('%d.%m.%Y')} erfasst — "
            f"Nettomietzins CHF {netto} VOLLSTÄNDIG ERLASSEN (Gratismonat). "
            f"Verrechnet wird nur CHF {zu_zahlen}. War das nicht beabsichtigt, "
            f"Zeile löschen und ohne Rabatt neu erfassen.")
    elif rabatt_netto > 0 or rabatt_nk > 0:
        messages.success(
            request,
            f"✅ Sollmietzins ab {ab.strftime('%d.%m.%Y')} erfasst — Referenz "
            f"CHF {netto + nk}, davon CHF {rabatt_netto + rabatt_nk} Rabatt, "
            f"zu zahlen CHF {zu_zahlen}.")
    else:
        messages.success(request, f"✅ Sollmietzins ab {ab.strftime('%d.%m.%Y')} erfasst "
                         f"(CHF {zu_zahlen}).")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_sollmietzins_del(request, pk):
    """Entfernt eine Sollmietzins-Zeile und führt den Aktuellwert der Einheit nach."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Sollmietzins
    s = get_object_or_404(Sollmietzins, id=pk)
    e = s.einheit
    if request.method == 'POST':
        s.delete()
        e.sync_aktuelle_miete()
        messages.success(request, "Sollmietzins-Zeile entfernt.")
    return redirect(f'/neu/objekte/{e.id}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffelvorlage_add(request):
    """Erfasst eine datierte Stufe der OBJEKT-Staffelmiete-Vorlage (Plan). Belegt
    neue Verträge im Wizard vor — wird selbst nicht verrechnet."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import StaffelVorlage
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/objekte/')
    e = get_object_or_404(Einheit, id=request.POST.get('einheit_id'))
    ziel = f'/neu/objekte/{e.id}/?tab=mietzins'
    try:
        ab = date.fromisoformat((request.POST.get('gueltig_ab') or '').strip())
    except ValueError:
        messages.error(request, "Bitte ein gültiges «gültig ab»-Datum angeben.")
        return redirect(ziel)

    def _dec(x):
        try:
            return Decimal(_num(x))
        except Exception:
            return None

    netto = _dec(request.POST.get('netto_mietzins'))
    if netto is None or netto <= 0:
        messages.error(request, "Bitte einen gültigen Netto-Mietzins angeben.")
        return redirect(ziel)
    StaffelVorlage.objects.create(
        einheit=e, gueltig_ab=ab, netto_mietzins=netto,
        notiz=(request.POST.get('notiz') or '').strip()[:200])
    log_aktion(request, "Staffel-Vorlage erfasst", e.bezeichnung, f"ab {ab}: {netto}")
    messages.success(request, f"✅ Staffel-Vorlage ab {ab.strftime('%d.%m.%Y')} erfasst.")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffelvorlage_del(request, pk):
    """Entfernt eine Stufe der Objekt-Staffelmiete-Vorlage."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import StaffelVorlage
    s = get_object_or_404(StaffelVorlage, id=pk)
    eid = s.einheit_id
    if request.method == 'POST':
        s.delete()
        messages.success(request, "Staffel-Vorlage-Zeile entfernt.")
    return redirect(f'/neu/objekte/{eid}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffel_add(request):
    """Erfasst eine Staffelstufe (Art. 269c) für den AKTIVEN Vertrag eines Objekts.
    Staffelmiete ist vertragsgebunden — die Stufe treibt direkt die Sollstellung
    (effektiver_netto_mietzins ab Stichtag)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Mietvertrag, Staffelstufe
    if request.method != 'POST':
        return redirect('/neu/objekte/')
    v = get_object_or_404(Mietvertrag, id=request.POST.get('vertrag_id'))
    ziel = f'/neu/objekte/{v.einheit_id}/?tab=mietzins'
    try:
        ab = date.fromisoformat((request.POST.get('ab_datum') or '').strip())
    except ValueError:
        messages.error(request, "Bitte ein gültiges Stichtag-Datum angeben.")
        return redirect(ziel)

    def _dec(x):
        try:
            return Decimal(_num(x))
        except Exception:
            return None

    netto = _dec(request.POST.get('netto_mietzins'))
    if netto is None or netto <= 0:
        messages.error(request, "Bitte einen gültigen Netto-Mietzins angeben.")
        return redirect(ziel)
    Staffelstufe.objects.create(vertrag=v, ab_datum=ab, netto_mietzins=netto)
    # Damit die Stufe im Mietenlauf greift, muss das Vertragsmodell 'staffel' sein.
    if v.mietzins_modell != 'staffel':
        v.mietzins_modell = 'staffel'
        v.save(update_fields=['mietzins_modell'])
    messages.success(request, f"✅ Staffelstufe ab {ab.strftime('%d.%m.%Y')} erfasst.")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffel_del(request, pk):
    """Entfernt eine Staffelstufe des aktiven Vertrags."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Staffelstufe
    s = get_object_or_404(Staffelstufe, id=pk)
    eid = s.vertrag.einheit_id
    if request.method == 'POST':
        s.delete()
        messages.success(request, "Staffelstufe entfernt.")
    return redirect(f'/neu/objekte/{eid}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_anpassung_del(request, pk):
    """Entfernt eine (versehentlich erstellte) Mietzinsanpassung. Danach folgt die
    Sollstellung wieder dem vorherigen Mietzins — bereits gestellte Rechnungen
    bleiben unverändert (nur künftige Sollläufe)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import MietzinsAnpassung
    from core.auth import log_aktion
    from portfolio.models import Sollmietzins
    a = get_object_or_404(MietzinsAnpassung, id=pk)
    vid = a.vertrag_id
    if request.method == 'POST':
        log_aktion(request, "Mietzinsanpassung gelöscht", str(a.vertrag),
                   f"wirksam {a.wirksam_ab}: CHF {a.neuer_netto_mietzins}")
        # Die aus dieser Anpassung erzeugte Sollmietzins-Zeile im Objekt
        # ebenfalls entfernen und den aktuellen Mietzins der Einheit neu ableiten.
        einheiten = {z.einheit for z in a.sollmietzins_zeilen.all()}
        Sollmietzins.objects.filter(quelle_anpassung=a).delete()
        a.delete()
        for e in einheiten:
            if e:
                e.sync_aktuelle_miete()
        messages.success(request, "Mietzinsanpassung entfernt.")
    return redirect(f'/neu/vertraege/{vid}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_objekt_nkart(request, pk):
    """Setzt die Nebenkosten-Abrechnungsart des Objekts (Standard für neue Verträge)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    e = get_object_or_404(Einheit, id=pk)
    if request.method == 'POST':
        art = request.POST.get('nk_abrechnungsart')
        if art in ('akonto', 'pauschal'):
            e.nk_abrechnungsart = art
            e.save(update_fields=['nk_abrechnungsart'])
            messages.success(request, "Nebenkosten-Abrechnungsart aktualisiert.")
    return redirect(f'/neu/objekte/{e.id}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_geraet_edit(request, pk):
    """Bearbeitet ein bestehendes Gerät (Kategorie/Marke/Modell/Daten)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    from core.auth import log_aktion
    g = get_object_or_404(Geraet, id=pk)
    eid, lid = g.einheit_id, g.liegenschaft_id
    ziel = (f'/neu/objekte/{eid}/?tab=geraete' if eid
            else f'/neu/liegenschaften/{lid}/?tab=technik')
    if request.method != 'POST':
        return redirect(ziel)

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    kategorie = (request.POST.get('kategorie') or '').strip()
    if not kategorie:
        messages.error(request, "Kategorie ist ein Pflichtfeld.")
        return redirect(ziel)
    g.kategorie = kategorie
    g.sonstiges_bezeichnung = (request.POST.get('sonstiges_bezeichnung') or '').strip()
    g.marke = (request.POST.get('marke') or '').strip()
    g.modell = (request.POST.get('modell') or '').strip()
    g.seriennummer = (request.POST.get('seriennummer') or '').strip()
    g.kapazitaet = (request.POST.get('kapazitaet') or '').strip()
    g.standort = (request.POST.get('standort') or '').strip()
    g.installations_datum = _date(request.POST.get('installations_datum'))
    g.garantie_bis = _date(request.POST.get('garantie_bis'))
    g.notiz = (request.POST.get('notiz') or '').strip()
    g.save()
    log_aktion(request, "Gerät bearbeitet", kategorie, '')
    messages.success(request, f"✅ Gerät «{kategorie}» aktualisiert.")
    return redirect(ziel)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_lebensdauer(request):
    """Editierbare paritätische Lebensdauertabelle (Mieterverband/HEV).
    Grundlage für den Zeitwert-/Mieteranteil bei der Wohnungsabnahme."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Lebensdauer
    from core.auth import log_aktion, hat_rolle
    basis = _global_filter(request)

    if request.method == 'POST':
        if not hat_rolle(request.user, SCHREIB_ROLLEN):
            messages.error(request, "Keine Berechtigung zum Bearbeiten.")
            return redirect('/neu/lebensdauer/')
        aktion = request.POST.get('aktion')
        if aktion == 'speichern':
            n = 0
            for row in Lebensdauer.objects.all():
                val = request.POST.get(f'jahre_{row.id}')
                bem = request.POST.get(f'bemerkung_{row.id}')
                changed = False
                if val and val.isdigit() and int(val) != row.jahre and int(val) > 0:
                    row.jahre = int(val); changed = True
                if bem is not None and bem.strip() != row.bemerkung:
                    row.bemerkung = bem.strip(); changed = True
                if changed:
                    row.save(); n += 1
            log_aktion(request, "Lebensdauertabelle bearbeitet", f"{n} Werte")
            messages.success(request, f"✅ {n} Wert(e) aktualisiert." if n else "Keine Änderung.")
        elif aktion == 'neu':
            kat = (request.POST.get('kategorie') or '').strip()
            jahre = request.POST.get('jahre')
            if kat and jahre and jahre.isdigit() and int(jahre) > 0:
                _, created = Lebensdauer.objects.get_or_create(
                    kategorie=kat, defaults={'jahre': int(jahre),
                                             'bemerkung': (request.POST.get('bemerkung') or '').strip()})
                messages.success(request, f"✅ «{kat}» hinzugefügt." if created else "Kategorie existiert bereits.")
            else:
                messages.error(request, "Kategorie und Jahre (> 0) sind Pflicht.")
        elif aktion == 'loeschen':
            Lebensdauer.objects.filter(id=request.POST.get('id') or None).delete()
            messages.success(request, "Kategorie entfernt.")
        elif aktion == 'seed':
            from core.services.raumkatalog import seed_lebensdauer
            n = seed_lebensdauer()
            messages.success(request, f"✅ {n} Standardwert(e) ergänzt." if n else "Alle Standardwerte bereits vorhanden.")
        return redirect('/neu/lebensdauer/')

    from django.contrib import messages as _m
    return render(request, 'fw/lebensdauer.html', {
        **basis, 'nav': 'assets',
        'rows': Lebensdauer.objects.all(),
        'meldung': list(_m.get_messages(request)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_objekt_foto_upload(request, pk):
    """Hängt Fotos an ein Mietobjekt (für Exposé, Portal-Feed, Vermarktung)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import EinheitFoto
    from core.auth import log_aktion
    from core.utils.uploads import validiere_bild
    e = get_object_or_404(Einheit, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/objekte/{e.id}/')
    start = e.fotos.count()
    n = 0
    abgelehnt = 0
    for f in request.FILES.getlist('fotos'):
        ok, _fehler = validiere_bild(f)
        if not ok:
            abgelehnt += 1
            continue
        EinheitFoto.objects.create(einheit=e, bild=f, reihenfolge=start + n)
        n += 1
    if n:
        log_aktion(request, "Objekt-Fotos hochgeladen", e.bezeichnung, f"{n} Foto(s)")
        messages.success(request, f"✅ {n} Foto(s) hinzugefügt.")
    if abgelehnt:
        messages.error(request, f"{abgelehnt} Datei(en) abgelehnt (kein gültiges Bild oder zu gross).")
    elif not n:
        messages.error(request, "Keine Datei ausgewählt.")
    return redirect(f'/neu/objekte/{e.id}/#obj-fotos')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_objekt_foto_loeschen(request, pk):
    """Entfernt ein einzelnes Objekt-Foto."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import EinheitFoto
    foto = get_object_or_404(EinheitFoto.objects.select_related('einheit'), id=pk)
    eid = foto.einheit_id
    if request.method == 'POST':
        foto.delete()
        messages.success(request, "Foto entfernt.")
    return redirect(f'/neu/objekte/{eid}/#obj-fotos')


# --- Erstellbare Dokumente pro Vertrag (Fairwalter-Stil) ---
def _erstellbare_dokumente(v):
    """Verlinkt die bestehenden PDF-/Prozess-Endpunkte als 'Erstellbare Dokumente'."""
    docs = [
        {'titel': 'Mietvertrag (PDF)', 'icon': 'fa-file-contract',
         'url': f'/vertrag/{v.id}/pdf/', 'sub': 'Kompletter Vertrag als PDF'},
        {'titel': 'QR-Rechnung', 'icon': 'fa-qrcode',
         'url': f'/vertrag/{v.id}/qr/', 'sub': 'Einzahlungsschein mit QR-IBAN'},
        {'titel': 'Mahnung (Art. 257d OR)', 'icon': 'fa-triangle-exclamation',
         'url': f'/vertrag/{v.id}/mahnung/', 'sub': 'Zahlungsfrist mit Kündigungsandrohung'},
        {'titel': 'Mietzinsanpassung', 'icon': 'fa-percent',
         'url': f'/mietzins/{v.id}/', 'sub': 'Amtliches Formular berechnen'},
        {'titel': 'Begleitbrief Mietvertrag', 'icon': 'fa-envelope',
         'url': f'/vertrag/{v.id}/dokument/begleitbrief/', 'sub': 'Anschreiben zur Unterzeichnung'},
        {'titel': 'Begleitbrief unterzeichnet', 'icon': 'fa-envelope-circle-check',
         'url': f'/vertrag/{v.id}/dokument/begleitbrief-signiert/', 'sub': 'Zustellung des signierten Vertrags'},
        {'titel': 'Allgemeine Bedingungen', 'icon': 'fa-file-lines',
         'url': f'/vertrag/{v.id}/dokument/allgemeine-bedingungen/', 'sub': 'Vertragsbeilage'},
        {'titel': 'Hausordnung', 'icon': 'fa-list-check',
         'url': f'/vertrag/{v.id}/dokument/hausordnung/', 'sub': 'Vertragsbeilage'},
        {'titel': 'Merkblatt Lüften & Pflegen', 'icon': 'fa-wind',
         'url': f'/vertrag/{v.id}/dokument/merkblatt-lueften/', 'sub': 'Vertragsbeilage'},
        {'titel': 'Wohnungsausweis', 'icon': 'fa-id-card',
         'url': f'/vertrag/{v.id}/dokument/wohnungsausweis/', 'sub': 'Mieter- und Objektdaten'},
    ]
    if v.kuendigungen.exists():
        docs.append({'titel': 'Kündigungsbestätigung', 'icon': 'fa-file-circle-xmark',
                     'url': f'/vertrag/{v.id}/dokument/kuendigungsbestaetigung/', 'sub': 'Bestätigung mit Vertragsende'})
    return docs


def _formulare_prozesse(v, user=None):
    """Bündelt ALLE für diesen Vertrag zutreffenden Formulare/Prozesse in Gruppen —
    kontextabhängig nach Status/Objektart, mit «bereits erstellt»-Kennzeichnung.
    Ein Ort für alles: der «Formulare & Prozesse»-Tab am Vertrag."""
    from rentals.models import Dokument
    from core.services.formularpflicht import formularpflicht_fuer_liegenschaft
    e = v.einheit
    lg = e.liegenschaft if e else None
    wohnraum = bool(e) and getattr(e, 'mietrecht_kategorie', '') != 'gewerbe' and not getattr(e, 'ist_einstellplatz', False)
    aktiv = v.status == 'aktiv'
    gek = v.status == 'gekuendigt'
    beendet = v.status in ('gekuendigt', 'archiviert')
    hat_kaution = bool(v.kautions_einbezahlt_am)
    sperrkonto = hat_kaution and not getattr(v, 'ist_kautionsversicherung', False)
    pflicht = formularpflicht_fuer_liegenschaft(lg)[0] if lg else 'unbekannt'

    labels = [b or '' for b in Dokument.objects.filter(vertrag=v).values_list('bezeichnung', flat=True)]

    def hat(prefix):
        return any(b.startswith(prefix) for b in labels)

    gruppen = [
        {'titel': 'Mietrechtliche Formulare', 'icon': 'fa-scale-balanced', 'items': [
            {'titel': 'Anfangsmietzins (Art. 270)', 'icon': 'fa-file-invoice',
             'url': f'/neu/mietzins/{v.id}/anfangsmietzins/', 'erledigt': hat('Anfangsmietzins'),
             'pflicht': (pflicht == 'ja' and wohnraum),
             'sub': ('Formularpflicht' if (pflicht == 'ja' and wohnraum) else 'Mitteilung des Anfangsmietzinses')},
            {'titel': 'Mietzinsanpassung (Art. 269d)', 'icon': 'fa-arrow-trend-up',
             'url': f'/neu/mietzins/{v.id}/anpassung/', 'verfuegbar': aktiv,
             'sub': 'Erhöhung / Senkung amtlich mitteilen'},
            {'titel': 'Kündigung (Art. 266)', 'icon': 'fa-file-circle-xmark',
             'url': f'/neu/vertraege/{v.id}/kuendigen/', 'verfuegbar': not gek,
             'erledigt': v.kuendigungen.exists(), 'sub': 'Vermieter- / Mieterkündigung'},
        ]},
        {'titel': 'Kaution (Art. 257e)', 'icon': 'fa-shield-halved', 'items': [
            {'titel': 'Hinterlegungsbestätigung', 'icon': 'fa-file-pdf',
             'url': f'/neu/vertraege/{v.id}/kaution-beleg/hinterlegung/', 'verfuegbar': hat_kaution,
             'erledigt': hat('Kaution-Bestätigung'), 'sub': 'an die Mieterschaft'},
            {'titel': 'Freigabe an Bank', 'icon': 'fa-building-columns',
             'url': f'/neu/vertraege/{v.id}/kaution-beleg/freigabe/', 'verfuegbar': sperrkonto,
             'erledigt': hat('Kaution-Freigabe'), 'sub': 'Sperrkonto freigeben'},
        ]},
        {'titel': 'Prozesse', 'icon': 'fa-gears', 'items': [
            {'titel': 'Zahlungsverzug (Art. 257d)', 'icon': 'fa-gavel',
             'url': f'/neu/vertraege/{v.id}/verzug/', 'sub': 'Frist + Kündigungsandrohung'},
            {'titel': 'Mängelrüge (Art. 259)', 'icon': 'fa-triangle-exclamation',
             'url': f'/neu/vertraege/{v.id}/maengelruege/', 'erledigt': hat('Mängelrüge'),
             'sub': 'Fristansetzung zur Mängelbehebung'},
            {'titel': 'Untermiete (Art. 262)', 'icon': 'fa-people-arrows',
             'url': f'/neu/vertraege/{v.id}/untermiete/', 'erledigt': hat('Untermiete-'),
             'sub': 'Zustimmung / Ablehnung'},
            {'titel': 'Wohnungsabnahme', 'icon': 'fa-clipboard-check',
             'url': f'/neu/vertraege/{v.id}/abnahme/neu/', 'sub': 'Ein- / Auszugsprotokoll'},
            {'titel': 'Schlussabrechnung', 'icon': 'fa-file-invoice-dollar',
             'url': f'/neu/vertraege/{v.id}/schlussabrechnung/', 'verfuegbar': (aktiv or beendet),
             'sub': 'beim Auszug'},
        ]},
        {'titel': 'Vertrag & Beilagen', 'icon': 'fa-file-contract', 'items': [
            {'titel': 'Mietvertrag (PDF)', 'icon': 'fa-file-contract', 'url': f'/vertrag/{v.id}/pdf/', 'sub': 'kompletter Vertrag'},
            {'titel': 'QR-Rechnung', 'icon': 'fa-qrcode', 'url': f'/vertrag/{v.id}/qr/', 'sub': 'Einzahlungsschein QR-IBAN'},
            {'titel': 'Begleitbrief', 'icon': 'fa-envelope', 'url': f'/vertrag/{v.id}/dokument/begleitbrief/', 'sub': 'Anschreiben zur Unterzeichnung'},
            {'titel': 'Allgemeine Bedingungen', 'icon': 'fa-file-lines', 'url': f'/vertrag/{v.id}/dokument/allgemeine-bedingungen/', 'sub': 'Vertragsbeilage'},
            {'titel': 'Hausordnung', 'icon': 'fa-list-check', 'url': f'/vertrag/{v.id}/dokument/hausordnung/', 'sub': 'Vertragsbeilage'},
            {'titel': 'Wohnungsausweis', 'icon': 'fa-id-card', 'url': f'/vertrag/{v.id}/dokument/wohnungsausweis/', 'sub': 'Mieter- und Objektdaten'},
        ]},
    ]
    for g in gruppen:
        for it in g['items']:
            it.setdefault('verfuegbar', True)
            it.setdefault('erledigt', False)
            it.setdefault('pflicht', False)
            # Was die Rolle ohnehin nicht öffnen darf, gar nicht erst als
            # Verknüpfung anbieten — sonst führt der Klick in eine Absage.
            # Die Rollen stehen an der View selbst (siehe `darf_oeffnen`), es
            # gibt hier also keine zweite Liste, die veralten könnte.
            if user is not None and not darf_oeffnen(user, it['url']):
                it['verfuegbar'] = False
                it['gesperrt'] = True
    return gruppen


def _wg_kandidaten(vertrag):
    """Personen, die als weitere WG-Mieter hinzugefügt werden können — alle Mieter
    ausser den bereits am Vertrag beteiligten Parteien (max. 50 für die Auswahl)."""
    from crm.models import Mieter
    aus = {vertrag.mieter_id, vertrag.mitmieter_id}
    if vertrag.pk:
        aus |= {m.id for m in vertrag.weitere_mieter.all()}
    return list(Mieter.objects.exclude(id__in=[i for i in aus if i])
                .order_by('nachname', 'vorname')[:50])


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_vertrag_detail(request, pk):
    from rentals.models import Dokument as RentalsDokument
    v = get_object_or_404(
        Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=pk)
    basis = _global_filter(request)

    rechnungen = (DebitorenRechnung.objects.filter(vertrag=v)
                  .exclude(status='storniert').order_by('-datum')[:15])
    offene = [r for r in rechnungen if r.status in ('offen', 'teilbezahlt')]
    total_offen = sum((r.offener_betrag for r in offene), Decimal('0.00'))

    zahlungen = (Zahlungseingang.objects.filter(vertrag=v, status='verbucht')
                 .order_by('-datum_eingang')[:15])
    anpassungen = v.anpassungen.order_by('-wirksam_ab')[:10]
    mietzins_komponenten = list(v.mietzins_komponenten.all())
    dokumente = RentalsDokument.objects.filter(vertrag=v).order_by('-datum')[:15]

    rechnungs_rows = []
    for r in rechnungen:
        label, pill_cls = STATUS_PILL.get(r.status, (r.status, 'bg-slate-100 text-slate-500'))
        rechnungs_rows.append({'r': r, 'status_label': label, 'pill_cls': pill_cls,
                               'offen': r.offener_betrag if r.status in ('offen', 'teilbezahlt') else Decimal('0.00')})

    from core.models import AktivitaetsLog
    verlauf = list(AktivitaetsLog.objects.filter(ziel_typ='vertrag', ziel_id=v.id)
                   .select_related('benutzer')[:50])
    # Meilensteine, die NICHT über log_aktion laufen (z.B. der Webhook-Rücklauf
    # der digitalen Unterschrift), als synthetische Ereignisse einmischen — der
    # Rücklauf-Zeitstempel gehört in den Verlauf, nicht in den Seitenkopf.
    from types import SimpleNamespace
    if v.unterzeichnet_am:
        verlauf.append(SimpleNamespace(
            benutzer=None,
            aktion="Unterschriebener Vertrag zurückerhalten",
            details=f"Digital unterzeichnet von {v.mieter.display_name} — Rücklauf via DocuSeal, automatisch abgelegt.",
            zeitpunkt=v.unterzeichnet_am))
    verlauf.sort(key=lambda x: x.zeitpunkt, reverse=True)

    # Akte komplettieren: Schäden am Mietobjekt + offene Pendenzen/Fristen zum
    # Vertrag — alles zum Mietverhältnis an EINEM Ort (kein Menü-Wechsel nötig).
    from tickets.models import SchadenMeldung
    from core.models import Pendenz
    schaeden = list(SchadenMeldung.objects.filter(betroffene_einheit=v.einheit)
                    .order_by('-erstellt_am')[:15]) if v.einheit_id else []
    vertrag_pendenzen = []
    _heute = timezone.localdate()
    for p in Pendenz.objects.filter(erledigt=False, vertrag=v).order_by('faellig_am'):
        _purl, _plabel, _pwide, _pmodal = _pendenz_ziel(p)
        vertrag_pendenzen.append({'p': p, 'url': _purl, 'label': _plabel or 'Öffnen',
                                  'wide': _pwide, 'modal': _pmodal,
                                  'ueberfaellig': bool(p.faellig_am and p.faellig_am < _heute)})
    # Datierte Fristen (Teilmenge) für die Finanzen-Karte — analog zum Kontakt, damit
    # die 257d-Frist + Track & Trace auch unter «Finanzen» direkt sichtbar ist.
    vertrag_fristen = [e for e in vertrag_pendenzen if e['p'].faellig_am]

    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('finanzen', 'Finanzen', len(offene) or None),
        ('mietzins', 'Mietzins', anpassungen.count() or None),
        ('schaeden', 'Schäden', len(schaeden) or None),
        ('pendenzen', 'Pendenzen', len(vertrag_pendenzen) or None),
        ('formulare', 'Formulare', None),
        ('dokumente', 'Dokumente', None),
        ('verlauf', 'Verlauf', len(verlauf) or None),
    ]
    from core.services.docuseal_service import docuseal_konfiguriert
    return render(request, 'fw/vertrag_detail.html', {
        'formular_gruppen': _formulare_prozesse(v, request.user),
        **basis, 'nav': 'vertraege', 'v': v, 'verlauf': verlauf,
        'vertrag_pill': _vertrag_status_pill(v),
        'brutto': (v.netto_mietzins or Decimal('0')) + (v.nebenkosten or Decimal('0')),
        'rechnungs_rows': rechnungs_rows,
        'total_offen': total_offen,
        'anzahl_offen': len(offene),
        'zahlungen': zahlungen,
        'anpassungen': anpassungen,
        'mietzins_komponenten': mietzins_komponenten,
        'heute_iso': timezone.localdate().isoformat(),
        'dokumente': dokumente,
        'nebenobjekte': v.nebenobjekte.all(),
        'weitere_mieter': list(v.weitere_mieter.all()),
        'wg_kandidaten': _wg_kandidaten(v),
        'erstellbare_dokumente': _erstellbare_dokumente(v),
        'kuendigungen': v.kuendigungen.all(),
        'formular_kanton': _formular_kanton_label(v),
        'tab_liste': tab_liste,
        'vertrag_schaeden': schaeden,
        'vertrag_pendenzen': vertrag_pendenzen,
        'vertrag_fristen': vertrag_fristen,
        'vt_zugang_next': f'/neu/vertraege/{v.id}/?tab=pendenzen',
        'vt_fin_zugang_next': f'/neu/vertraege/{v.id}/?tab=finanzen',
        'docuseal_konfiguriert': docuseal_konfiguriert(),
    })


def _formular_kanton_label(vertrag):
    """Kürzel des Kantons für das amtliche Formular (SO/ZH/BE/…). Leer, wenn
    keine Liegenschaft/kein Kanton bestimmbar."""
    from core.services.kantone import kanton_fuer_liegenschaft
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
    return kanton_fuer_liegenschaft(lg) if lg else ''




GUTHABEN_AUSBEZAHLT = '[ausbezahlt]'


def _guthaben_positionen(vertrag):
    """Noch nicht ausbezahlte Mieterguthaben (2030) dieses Vertrags."""
    from finance.models import Zahlungseingang as _Z
    return list(_Z.objects.filter(vertrag=vertrag, status='verbucht', konto__nummer='2030')
                .exclude(bemerkung__contains=GUTHABEN_AUSBEZAHLT))


def _guthaben_bilanziert(vertrag):
    """Summe der noch offenen Mieterguthaben (2030) dieses Vertrags."""
    return sum((z.betrag for z in _guthaben_positionen(vertrag)),
               Decimal('0.00')).quantize(Decimal('0.01'))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schlussabrechnung(request, vertrag_id):
    """Schlussabrechnung beim Auszug: offene Forderungen + NK-Saldo + Schäden −
    Kaution = Saldo. GET zeigt Formular, POST erzeugt PDF (aktion=pdf) oder
    verbucht Kaution + Nachzahlung (aktion=buchen)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from crm.models import Organisation
    from core.services.schlussabrechnung import berechne_schlussabrechnung, generate_schlussabrechnung_pdf
    from core.auth import log_aktion

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)

    def _dec(x):
        try:
            return Decimal(_num(x))
        except Exception:
            return Decimal('0.00')

    if request.method == 'POST':
        try:
            auszug = date.fromisoformat(request.POST.get('auszug_datum') or '')
        except Exception:
            auszug = v.ende or timezone.localdate()
        kaution_verrechnen = request.POST.get('kaution_verrechnen') == 'on'

        positionen = []
        texte = request.POST.getlist('pos_text')
        betraege = request.POST.getlist('pos_betrag')
        richtungen = request.POST.getlist('pos_richtung')
        # `pos_mwst` ist ein <select> (nicht Checkbox), damit die Indizes mit den
        # übrigen Listen ausgerichtet bleiben — eine nicht angehakte Checkbox
        # sendet gar nichts und würde die Zuordnung verschieben.
        steuerflags = request.POST.getlist('pos_mwst')
        for i, txt in enumerate(texte):
            txt = (txt or '').strip()
            betr = _dec(betraege[i] if i < len(betraege) else '0')
            if not txt or betr == 0:
                continue
            richtung = richtungen[i] if i < len(richtungen) else 'zulasten'
            steuerbar = (steuerflags[i] if i < len(steuerflags) else '0') == '1'
            positionen.append({'text': txt, 'betrag': betr,
                               'zulasten': (richtung == 'zulasten'),
                               'steuerbar': steuerbar})

        # Die bilanzierte Kaution (2010-Saldo) als Obergrenze mitgeben, damit
        # Anzeige/PDF exakt das gutschreiben, was die Buchung freigibt (QS-Befund).
        daten = berechne_schlussabrechnung(v, auszug, positionen,
                                           kaution_verrechnen=kaution_verrechnen,
                                           kaution_bilanziert=_kaution_bilanziert(v))
        aktion = request.POST.get('aktion', 'pdf')

        if aktion == 'buchen':
            # Idempotenz: eine Schlussabrechnung wird pro Vertrag nur EINMAL verbucht.
            # Ohne diese Sperre erzeugte ein Doppelklick / Zurück-Navigieren einen
            # zweiten Nachzahlungs-Debitor + eine doppelte 1100/3000-Buchung.
            #
            # Geprüft werden die BUCHUNGSSPUREN, nicht `kautions_zurueckbezahlt_am`:
            # Letzteres wird auch gesetzt, wenn die Kaution separat zurückbezahlt
            # wurde — dann war die Schlussabrechnung komplett blockiert, obwohl sie
            # noch nie lief. Umgekehrt fehlte eine Sperre für den Gutschrift-Fall
            # ohne Kaution, wo ein Doppelklick zweimal Mieterguthaben buchte (Audit).
            from finance.models import Buchung as _BIdem
            schon_verbucht = (
                DebitorenRechnung.objects.filter(
                    vertrag=v, titel="Schlussabrechnung (Nachzahlung)"
                ).exclude(status='storniert').exists()
                # storniert_am mitprüfen — sonst widerspricht diese Hälfte der
                # ersten: die schliesst stornierte Rechnungen bereits aus, damit
                # eine Schlussabrechnung nach einem Storno neu erstellt werden
                # kann. Ohne den Filter blockierte die stehengebliebene
                # Original-Buchung genau das.
                or _BIdem.objects.filter(
                    beleg_text__contains=f"Schlussabrechnung [V{v.pk}]",
                    ist_storno=False, storniert_am__isnull=True
                ).exists()
            )
            if schon_verbucht:
                if request.POST.get('embed'):
                    return render(request, 'fw/_modal_done.html', {'msg': 'Schlussabrechnung bereits verbucht'})
                messages.info(request, "Diese Schlussabrechnung wurde bereits verbucht.")
                return redirect(f'/neu/vertraege/{v.id}/')
            try:
                with transaction.atomic():
                    from finance.booking import buche
                    heute = timezone.localdate()
                    lg_s = v.einheit.liegenschaft if v.einheit_id else None
                    dat_s = auszug or heute

                    # ── 1) NUR die NEUEN Positionen buchen (Schäden, Reinigung, NK-Saldo) ──
                    # Bereits gestellte Mietforderungen bleiben unangetastet: Storno +
                    # Neubuchung auf 3000 (früheres Verhalten) vernichtete deren MWST-
                    # Abgrenzung (2200) und verschob Schadenersatz in den Mietertrag —
                    # was Mieterspiegel und Honorarbasis verfälschte (Audit K2/W5).
                    neu_saldo = (daten['zwischen'] - daten['offen_total']).quantize(Decimal('0.01'))
                    # MWST-Anteil aus dem Gesamtbetrag herauslösen: `zwischen`
                    # enthält ihn bereits als eigene Zeile. Der Ertrag (3600) darf
                    # nur den Nettoteil bekommen, die Steuer gehört auf 2200 —
                    # sonst fehlt sie in der ESTV-Abrechnung (Audit).
                    mwst_neu = daten.get('mwst_neu') or Decimal('0.00')
                    netto_neu = (neu_saldo - mwst_neu).quantize(Decimal('0.01'))
                    if neu_saldo > 0:
                        rech = DebitorenRechnung.objects.create(
                            vertrag=v, liegenschaft=lg_s, einheit=v.einheit,
                            titel="Schlussabrechnung (Nachzahlung)", datum=dat_s,
                            faellig_am=dat_s + _timedelta(days=30), betrag=neu_saldo, status='offen')
                        if netto_neu != 0:
                            buche("1100", "3600", netto_neu,
                                  f"Schlussabrechnung [V{v.pk}] {v.mieter} (Schäden/Nebenkosten)",
                                  datum=dat_s, liegenschaft=lg_s, debitor=rech, user=request.user)
                        if mwst_neu > 0:
                            buche("1100", "2200", mwst_neu,
                                  f"MWST Schlussabrechnung [V{v.pk}] {v.mieter}",
                                  datum=dat_s, liegenschaft=lg_s, debitor=rech, user=request.user)
                    elif neu_saldo < 0:
                        # Gutschrift zugunsten Mieter → als echtes Guthaben (2030) führen,
                        # damit es im Mieterkonto sichtbar und auszahlbar ist.
                        from finance.booking import konto as _k_s
                        if netto_neu != 0:
                            buche("3600", "2030", abs(netto_neu),
                                  f"Schlussabrechnung [V{v.pk}] {v.mieter} — Gutschrift",
                                  datum=dat_s, liegenschaft=lg_s, user=request.user)
                        if mwst_neu < 0:
                            # Spiegelbildliche Steuerkorrektur: der Umsatz wird
                            # gemindert, also auch die geschuldete MWST.
                            buche("2200", "2030", abs(mwst_neu),
                                  f"MWST-Korrektur Schlussabrechnung [V{v.pk}] {v.mieter}",
                                  datum=dat_s, liegenschaft=lg_s, user=request.user)
                        Zahlungseingang.objects.create(
                            vertrag=v, betrag=abs(neu_saldo), datum_eingang=dat_s,
                            buchungs_monat=dat_s.replace(day=1),
                            bemerkung="Schlussabrechnung — Guthaben Mieter"[:255],
                            konto=_k_s("2030"), liegenschaft=lg_s,
                            erstellt_von=request.user, status='verbucht')

                    # ── 2) Kaution bilanziell abwickeln (Audit K3) ──
                    # Früher wurden nur Vertragsfelder gesetzt — 1015/2010 blieben ewig
                    # in der Bilanz stehen (stille Drift bei jedem Mieterwechsel).
                    #   Sperrkonto freigeben:  1020 an 1015
                    #   Verrechnung mit OP:    2010 an 1100
                    #   Rest an Mieter:        2010 an 1020
                    # Freigegeben werden darf nur, was tatsächlich in der Bilanz steht.
                    # Das Vertragsfeld `kautions_betrag` ist bloss der VEREINBARTE Betrag —
                    # ohne diese Prüfung wurde eine nie einbezahlte Kaution «freigegeben»
                    # und ausbezahlt: 1015 und 2010 rutschten ins Minus und offene
                    # Mietforderungen galten als getilgt (Audit, kritisch).
                    kaution_bil = _kaution_bilanziert(v)
                    if kaution_verrechnen and (v.kautions_betrag or 0) > 0 \
                            and kaution_bil <= 0 and not v.ist_kautionsversicherung:
                        # Kaution vereinbart, aber nie eingegangen (oder bereits
                        # aufgelöst): das Kautionsthema ist mit dem Auszug erledigt,
                        # es gibt aber nichts freizugeben und nichts auszuzahlen.
                        v.kautions_zurueckbezahlt_am = auszug
                        v.kautions_rueckzahlung_betrag = Decimal('0.00')
                        v.kautions_abzug_betrag = Decimal('0.00')
                        v.save(update_fields=['kautions_zurueckbezahlt_am',
                                              'kautions_rueckzahlung_betrag',
                                              'kautions_abzug_betrag'])
                        messages.warning(request,
                            f"Hinweis: Für diesen Vertrag ist keine Kaution bilanziert "
                            f"(vereinbart CHF {v.kautions_betrag}). Es wurde weder ein "
                            f"Sperrkonto freigegeben noch eine Rückzahlung gebucht.")
                    if kaution_verrechnen and (v.kautions_betrag or 0) > 0 \
                            and (kaution_bil > 0 or v.ist_kautionsversicherung):
                        kaution = min(v.kautions_betrag or Decimal('0.00'), kaution_bil)
                        v.kautions_zurueckbezahlt_am = auszug
                        if v.ist_kautionsversicherung:
                            # Versicherung: kein Depot, keine Rückzahlung an den Mieter.
                            v.kautions_rueckzahlung_betrag = Decimal('0.00')
                            v.save()
                        else:
                            # Offene Forderungen NACH Schritt 1 (inkl. neuer Schlussabrechnung)
                            offene_op = list(DebitorenRechnung.objects
                                             .filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
                                             .order_by('faellig_am', 'id'))
                            offen_nachher = sum((r.offener_betrag for r in offene_op), Decimal('0.00'))
                            verrechnet = min(kaution, offen_nachher)
                            rueck = (kaution - verrechnet).quantize(Decimal('0.01'))
                            v.kautions_rueckzahlung_betrag = rueck
                            v.kautions_abzug_betrag = verrechnet
                            v.save()
                            from finance.models import Buchung as _BS
                            beleg_k = f"Kaution Schlussabrechnung [V{v.pk}] {v.mieter}"
                            if not _BS.objects.filter(beleg_text__startswith=beleg_k,
                                                      ist_storno=False,
                                                      storniert_am__isnull=True).exists():
                                buche("1020", "1015", kaution, f"{beleg_k} — Sperrkonto freigegeben",
                                      datum=dat_s, liegenschaft=lg_s, user=request.user)
                                if verrechnet > 0:
                                    buche("2010", "1100", verrechnet,
                                          f"{beleg_k} — Verrechnung offene Forderungen",
                                          datum=dat_s, liegenschaft=lg_s, user=request.user)
                                if rueck > 0:
                                    buche("2010", "1020", rueck, f"{beleg_k} — Rückzahlung an Mieter",
                                          datum=dat_s, liegenschaft=lg_s, user=request.user)
                            # OP-Nebenbuch nachführen: die verrechnete Kaution tilgt die
                            # offenen Rechnungen (sonst Drift Hauptbuch 1100 ↔ Debitorenliste).
                            rest_v = verrechnet
                            for r_op in offene_op:
                                if rest_v <= 0:
                                    break
                                teil = min(rest_v, r_op.offener_betrag)
                                if teil <= 0:
                                    continue
                                Zahlungseingang.objects.create(
                                    vertrag=v, betrag=teil, datum_eingang=dat_s,
                                    buchungs_monat=(r_op.faellig_am or r_op.datum or dat_s).replace(day=1),
                                    bemerkung=f"Verrechnung Mietkaution — {r_op.titel}"[:255],
                                    debitoren_rechnung=r_op, liegenschaft=lg_s,
                                    erstellt_von=request.user, status='verbucht')
                                r_op.status = 'bezahlt' if r_op.offener_betrag <= 0 else 'teilbezahlt'
                                r_op.save(update_fields=['status'])
                                rest_v -= teil

                    # ── 3) Mieterguthaben (2030) mit auszahlen ──
                    # Ein Guthaben aus Schritt 1 wäre sonst eine Sackgasse: die
                    # Schlussabrechnung weist es dem Mieter als Rückzahlung aus, gebucht
                    # wurde aber nur die Kaution — der Rest bliebe für einen längst
                    # ausgezogenen Mieter dauerhaft auf 2030 stehen (Audit).
                    guthaben_pos = _guthaben_positionen(v)
                    guthaben_offen = sum((z.betrag for z in guthaben_pos), Decimal('0.00'))
                    if guthaben_offen > 0:
                        buche("2030", "1020", guthaben_offen,
                              f"Schlussabrechnung [V{v.pk}] {v.mieter} — Guthaben ausbezahlt",
                              datum=dat_s, liegenschaft=lg_s, user=request.user)
                        for z_g in guthaben_pos:
                            z_g.bemerkung = f"{z_g.bemerkung} {GUTHABEN_AUSBEZAHLT}"[:255]
                            z_g.save(update_fields=['bemerkung'])
                        v.kautions_rueckzahlung_betrag = (
                            (v.kautions_rueckzahlung_betrag or Decimal('0.00')) + guthaben_offen)
                        v.save(update_fields=['kautions_rueckzahlung_betrag'])
            except PermissionError as exc:
                # Rückdatierter Auszug in eine gesperrte Periode: als Meldung
                # zeigen statt als HTTP 500 (Audit).
                messages.error(request, f"❌ {exc}")
                return redirect(f'/neu/vertraege/{v.id}/')
            from core.services.automation import erledige_pendenzen_fuer
            erledige_pendenzen_fuer(v, ['Schlussabrechnung', 'Kaution'], user=request.user)
            log_aktion(request, "Schlussabrechnung verbucht", str(v.mieter), f"Saldo CHF {daten['saldo']}", ziel=v)
            if request.POST.get('embed'):
                return render(request, 'fw/_modal_done.html', {'msg': 'Schlussabrechnung verbucht'})
            messages.success(request, "✅ Schlussabrechnung verbucht (Kaution abgerechnet"
                             + (", Nachzahlung als Debitor gestellt" if daten['nachzahlung'] else "") + ").")
            return redirect(f'/neu/vertraege/{v.id}/')

        try:
            pdf = generate_schlussabrechnung_pdf(v, daten, verwaltung=Organisation.objects.first())
        except Exception as e:
            messages.error(request, f"❌ PDF konnte nicht erstellt werden: {e}")
            return redirect(f'/neu/vertraege/{v.id}/schlussabrechnung/')
        from core.services.ablage import ablegen
        ablegen(pdf, "Schlussabrechnung", kategorie='korrespondenz', vertrag=v, dedup=True)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Schlussabrechnung_{v.mieter.nachname}.pdf"'
        return resp

    # GET
    offene = DebitorenRechnung.objects.filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
    offen_total = sum((r.offener_betrag for r in offene), Decimal('0.00'))
    # Bereits erfasste Schaden-/Einbehalts-Forderung (z.B. aus „Police auflösen") als
    # Position vorbelegen, damit sie in der Schlussabrechnung sichtbar mitzählt.
    schaden_betrag = v.kautions_abzug_betrag or Decimal('0.00')
    schaden_text = v.kautions_abzug_grund or ('Schadenforderung' if schaden_betrag > 0 else '')
    # Mängel aus einem Abnahmeprotokoll (Verursacher = Mieter) als Positionen vorbelegen
    prefill_positionen = []
    ab_id = request.GET.get('abnahme')
    if ab_id:
        from rentals.models import Abnahmeprotokoll
        ab = Abnahmeprotokoll.objects.filter(id=ab_id, vertrag=v).first()
        if ab:
            for m in ab.maengel_mieter:
                betrag = m.mieteranteil if m.mieteranteil is not None else m.kostenschaetzung
                if betrag:
                    txt = f"{m.raum + ': ' if m.raum else ''}{m.beschreibung}"
                    if m.mieteranteil is not None and m.ausstattung_id:
                        txt += " (Zeitwert)"
                    prefill_positionen.append({'text': txt[:90], 'betrag': betrag})
    if schaden_betrag > 0:
        prefill_positionen.insert(0, {'text': schaden_text, 'betrag': schaden_betrag})
    return render(request, 'fw/schlussabrechnung.html', {
        **basis, 'nav': 'vertraege', 'v': v,
        'offen_total': offen_total,
        'kaution': v.kautions_betrag or Decimal('0.00'),
        'ist_versicherung': v.ist_kautionsversicherung,
        'schaden_prefill_betrag': schaden_betrag,
        'schaden_prefill_text': schaden_text,
        'prefill_positionen': prefill_positionen,
        'auszug_default': (v.ende or timezone.localdate()).isoformat(),
        'abnahmen': v.abnahmen.all(),
        'embed_base': ('fw/base_embed.html' if request.GET.get('embed') == '1' else None),
    })
