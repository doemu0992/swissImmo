# core/views/fw/objekt_detail.py
#
# Die Objekt-Akte (Einheit): Kopf, Detailseite, Merkmale, Nebenkostenart und Fotos.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md. Herausgeloest aus detailseiten.py.

from decimal import Decimal

from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext, ngettext

from core.auth import (rolle_erforderlich, SCHREIB_ROLLEN,
                       TEAM_ROLLEN)
from portfolio.models import Einheit
from rentals.models import Mietvertrag

from ._basis import (_global_filter, VERTRAG_PILL)
from .ausstattung import _raumbuch_zeilen
from .objekt_geraete import GERAET_KATEGORIEN, ZAEHLER_TYPEN


def _objekt_kopf(e, aktiver_vertrag, verhaeltnisse, raeume, ausst_rows,
                 schluessel_offen, geraete, zaehler, faelle):
    """Der Aktenkopf des Objekts — gerechnete Zustaende, keine Felder.

    Umsetzung von G9 (KONZEPT-UI.md 16.3) fuer den vierten und letzten
    Aktentyp. Die Kennzahlen beantworten, was man vor einem Objekt zuerst
    wissen will: Ist es vermietet und zu welchem Zins, wie gross ist es, wie
    alt ist die Ausstattung, und was steht als Naechstes an.

    **Was hier bewusst NICHT steht.** Der Prototyp fuehrt beim Objekt einen
    Chip «Sanierungsbedarf» mit einer Ampel. Dafuer gibt es keine belastbare
    Grundlage: `Ausstattung.ersatz_status()` bewertet ein einzelnes Element,
    nicht das Objekt, und eine Summe daraus waere eine erfundene Kennzahl.
    Statt einer Ampel steht deshalb die tatsaechliche Zahl der ueberfaelligen
    Elemente — die ist gezaehlt, nicht geschaetzt.
    """
    chips = []
    if aktiver_vertrag:
        chips.append({'text': gettext('vermietet an %(name)s') % {'name': aktiver_vertrag.mieter.display_name},
                      'ton': 'fw-good'})
    else:
        chips.append({'text': gettext('Leerstand'), 'ton': 'fw-warn'})
    if e.zur_ausschreibung:
        chips.append({'text': gettext('ausgeschrieben'), 'ton': 'fw-info'})
    if schluessel_offen:
        chips.append({'text': gettext('%(n)s Schlüssel ausgegeben') % {'n': schluessel_offen}, 'ton': 'fw-mut'})

    # Ueberfaellige Ausstattung: gezaehlt aus `ersatz_status()`, nicht aus
    # einem Mittelwert. `ersatz_status` liefert je Element eine Einstufung;
    # 'faellig' heisst, die Lebensdauer ist ueberschritten.
    faellig = [r for r in ausst_rows if r.get('ersatz_status') == 'faellig']
    if faellig:
        chips.append({'text': ngettext('%(n)s Element am Ende der Lebensdauer',
                                       '%(n)s Elemente am Ende der Lebensdauer',
                                       len(faellig)) % {'n': len(faellig)}, 'ton': 'fw-warn'})
    offene_faelle = [f for f in faelle if f.status not in ('abgeschlossen', 'abgebrochen')]
    if offene_faelle:
        chips.append({'text': ngettext('%(n)s offener Fall', '%(n)s offene Fälle',
                                       len(offene_faelle)) % {'n': len(offene_faelle)},
                      'ton': 'fw-warn'})

    hinweise = []
    if not aktiver_vertrag and not e.zur_ausschreibung:
        hinweise.append({
            'ton': 'warn', 'symbol': 'senden',
            'titel': gettext('Leer und nicht ausgeschrieben'),
            'text': gettext('Das Objekt steht leer, ist aber nicht zur Vermarktung '
                            'freigegeben — es sucht niemand einen Nachmieter.'),
            'url': f'/neu/objekte/{e.id}/', 'knopf': gettext('Ausschreiben')})
    if not raeume:
        hinweise.append({
            'ton': 'info', 'symbol': 'dokument',
            'titel': gettext('Kein Raumbuch erfasst'),
            'text': gettext('Ohne erfasste Ausstattung lässt sich bei der Rückgabe kein '
                            'Lebensdaueranteil berechnen — die Mängelabrechnung wird '
                            'dann Verhandlungssache.'),
            'url': '?tab=ausstattung', 'knopf': gettext('Ausstattung erfassen')})
    if faellig:
        hinweise.append({
            'ton': 'warn', 'symbol': 'wartet',
            'titel': ngettext('%(n)s Element am Ende der Lebensdauer',
                              '%(n)s Elemente am Ende der Lebensdauer',
                              len(faellig)) % {'n': len(faellig)},
            # Haftungsaussage (Zeitwert) — bleibt deutsch bis zur juristischen Prüfung.
            'text': 'Bei einem Mieterwechsel trägt der Vermieter die Kosten '
                    'vollständig — der Zeitwert ist aufgebraucht.',
            'url': '?tab=ausstattung', 'knopf': gettext('Ersatzplanung')})

    return {
        'objekt_nummer': f'O-{e.id:06d}',
        'objekt_chips': chips,
        'objekt_hinweise': hinweise,
        'objekt_miete': (aktiver_vertrag.brutto_mietzins if aktiver_vertrag else None),
        'objekt_faellig': len(faellig),
        'objekt_technik': geraete + zaehler,
    }


def _vertrag_status_pill(v):
    """Der Chip im Aktenkopf — nach ANZEIGE-Status.

    Zeigte die Akte weiterhin «Gekuendigt», waehrend die Liste denselben
    Vertrag als «Beendet» fuehrt, waere der Widerspruch schlimmer als die
    urspruengliche Ungenauigkeit: Man wuesste nicht, welcher Seite zu
    trauen ist.
    """
    anzeige = v.anzeige_status
    label, cls = VERTRAG_PILL.get(anzeige, (anzeige, 'fw-flaeche2 fw-mutet'))
    return {'label': label, 'cls': cls}


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
    messages.success(request, '✅ ' + gettext('Ausstattungsmerkmale gespeichert.'))
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


def _assistent_zimmer(einheit):
    """Zimmerzahl der Einheit für den Raumbuch-Assistenten, auf halbe Zimmer gerundet und auf 1…8 begrenzt."""
    from decimal import Decimal
    z = einheit.zimmer if einheit.zimmer else Decimal('3')
    z = min(max(Decimal(z), Decimal('1')), Decimal('8'))
    return (z * 2).to_integral_value() / 2


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_objekt_detail(request, pk):
    from portfolio.models import Geraet, Zaehler, Ausstattung
    from core.services.raumkatalog import RAUMTYPEN, RAUM_KATALOG
    from core.services import raumbuch_assistent as _ra
    from core.services.raumbuch_assistent import ASSISTENT_TYPEN
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
    from core.services.archiv import ausblenden
    for d in (ausblenden(RentalsDokument.objects.neueste()).filter(vertrag__in=_vertraege)
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
    # Referenzzins und LIK der Verwaltung DIESES Objekts: An ihnen haengt
    # die Begruendung einer Mietzinsanpassung nach OR 269a. Aus der ersten
    # Verwaltung der Installation genommen, stuende in der Anpassung eine
    # fremde Basis (Audit 18.08.2026 — der Alias `_Vw` machte die Zaehlung
    # der `Organisation.objects.first()`-Stellen blind).
    _vw = e.liegenschaft.organisation if e.liegenschaft_id else None
    aktueller_ref_zins = _vw.aktueller_referenzzinssatz if _vw else Decimal('1.25')
    aktueller_lik = _vw.aktueller_lik_punkte if _vw else Decimal('107.1')

    # Ausstattung/Raumbuch — die Räume entstehen aus den erfassten Assets.
    from core.services.zustandsvergleich import verlauf_je_element
    ausst = list(Ausstattung.objects.filter(einheit=e)
                 .prefetch_related('schaeden__handwerker_auftraege'))
    raeume = _raumbuch_zeilen(ausst, verlauf_je_element(e))
    ausst_count = len(ausst)

    # Schlüssel des Objekts als Karten (Modul 2). Ausgabe und Rücknahme laufen
    # über die Kartenseiten der Liegenschaft (Unterschrift, Quittung).
    from core.services.schluessel import karten as _schluessel_karten
    from portfolio.models import Schluessel
    schluessel_karten = _schluessel_karten(Schluessel.objects.filter(einheit=e, archiviert=False))
    schluessel_offen_count = sum(k['n_offen'] for k in schluessel_karten)

    # Etappe 4b.11: Reiter aus dem Aktenregister statt aus dieser View. Acht
    # alte Reiter fallen auf sechs — `raumbuch`, `geraete`, `zaehler` und
    # `schluessel` werden zu Abschnitten INNERHALB von «Ausstattung», ihre
    # Zaehler addiert `aus_alt`. `fotos` fallen unter «Dokumente».
    from django.contrib.contenttypes.models import ContentType

    from core.models import AktivitaetsLog
    from core.tenancy import aktuelle_organisation as _akt_org
    from faelle.akten import aus_alt as _reiter_aus_alt
    from faelle.models import Fall

    objekt_faelle = list(
        Fall.objects.filter(akte_typ=ContentType.objects.get_for_model(Einheit),
                            akte_id=e.id)
        .select_related('fallart', 'zustaendig').order_by('-eroeffnet_am'))

    # Schaeden an diesem Objekt gehoeren in denselben Reiter: Ein Schaden ist
    # ein Vorgang, kein Stammdatum. Bis 4b.11 waren sie auf der Objektakte
    # ueberhaupt nicht zu sehen — sie standen nur an der Liegenschaft.
    from tickets.models import SchadenMeldung
    from core.services.archiv import ausblenden
    objekt_schaeden = list(ausblenden(SchadenMeldung.objects.filter(betroffene_einheit=e))
                           .order_by('-erstellt_am')[:20])
    objekt_schaeden_offen = [s for s in objekt_schaeden if s.status != 'erledigt']

    # Chronik. `AktivitaetsLog` kennt den Ziel-Typ 'vertrag' — fuer ein Objekt
    # fuehrt der belastbare Bezug ueber seine Vertraege, genau wie bei der
    # Liegenschaft. Ein Abgleich ueber die Bezeichnung waere geraten.
    _vids = [v.id for v in _vertraege]
    verlauf = list(AktivitaetsLog.objects
                   .filter(ziel_typ='vertrag', ziel_id__in=_vids)
                   .select_related('benutzer')[:50]) if _vids else []

    # Abnahmen: gehören zur Einheit, über alle Mieter hinweg (nicht nur zum aktuellen Vertrag).
    abnahmen_objekt = list(e.abnahmen.select_related('vertrag__mieter')
                           .annotate(n_maengel=Count('maengel', distinct=True)).order_by('-datum', '-id'))

    tab_liste = _reiter_aus_alt('objekt', [
        ('uebersicht', 'Übersicht', None),
        ('fotos', 'Fotos', len(fotos) or None),
        ('raumbuch', 'Raumbuch', ausst_count or None),
        ('verhaeltnisse', 'Verhältnisse', len(verhaeltnisse) or None),
        ('mietzins', 'Mietzins', len(sollmietzinse) or None),
        ('geraete', 'Geräte', geraete.count() or None),
        ('zaehler', 'Zähler', zaehler.count() or None),
        ('schluessel', 'Schlüssel', len(schluessel_karten) or None),
        ('dokumente', 'Dokumente', verhaeltnisse_dok_total or None),
    ], organisation=getattr(request, 'organisation', None) or _akt_org())

    _ausst_flach = [row for r in raeume for row in r['elemente']]
    from django.contrib import messages
    return render(request, 'fw/objekt_detail.html', {
        **basis, 'nav': 'objekte', 'e': e,
        'objekt_faelle': objekt_faelle,
        'abnahmen_objekt': abnahmen_objekt,
        'objekt_schaeden': objekt_schaeden,
        'objekt_schaeden_offen': objekt_schaeden_offen,
        'verlauf': verlauf,
        **_objekt_kopf(e, aktiver_vertrag, verhaeltnisse, raeume, _ausst_flach,
                       schluessel_offen_count, geraete.count(), zaehler.count(),
                       objekt_faelle),
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
        'rb_basis': f'/neu/objekte/{e.id}',
        'assistent_typen': ASSISTENT_TYPEN,
        'assistent_zimmer': _assistent_zimmer(e),
        'assistent_start': _ra.vorschlag(_assistent_zimmer(e)),
        'assistent_vorschlaege': _ra.vorschlaege_je_zimmerzahl(),
        'zustand_choices': Ausstattung.ZUSTAND,
        'geraet_kategorien': GERAET_KATEGORIEN,
        'zaehler_typen': ZAEHLER_TYPEN,
        'merkmale_gewaehlt': e.merkmale or [],
        'merkmale_optionen': merkmale_optionen(e.merkmale or []),
        'tab_liste': tab_liste,
        'schluessel_karten': schluessel_karten,
        'schluessel_offen_count': schluessel_offen_count,
        'schluessel_arten': Schluessel.ART_CHOICES,
        'meldung': list(messages.get_messages(request)),
    })


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
            messages.success(request, gettext('Nebenkosten-Abrechnungsart aktualisiert.'))
    return redirect(f'/neu/objekte/{e.id}/?tab=mietzins')


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
        messages.success(request, '✅ ' + gettext('%(n)s Foto(s) hinzugefügt.') % {'n': n})
    if abgelehnt:
        messages.error(request, gettext('%(abgelehnt)s Datei(en) abgelehnt (kein gültiges Bild oder zu gross).') % {'abgelehnt': abgelehnt})
    elif not n:
        messages.error(request, gettext('Keine Datei ausgewählt.'))
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
        messages.success(request, gettext('Foto entfernt.'))
    return redirect(f'/neu/objekte/{eid}/#obj-fotos')


# --- Erstellbare Dokumente pro Vertrag (Fairwalter-Stil) ---
