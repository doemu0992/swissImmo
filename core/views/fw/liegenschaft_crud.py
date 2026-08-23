# core/views/fw/liegenschaft_crud.py
#
# Liegenschaften und Objekte anlegen und bearbeiten, GWR-Abgleich,
# Versicherungspolicen, globale Suche. Etappe 1, siehe
# docs/ETAPPE-1-ZERLEGEN.md.

from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from crm.models import Mieter
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag

from ._basis import _global_filter, _num


# ============================================================
# LIEGENSCHAFT + OBJEKT CRUD (neu / bearbeiten)
# ============================================================

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_liegenschaft_form(request, pk=None):
    """Liegenschaft erfassen oder bearbeiten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Eigentuemer
    from core.auth import log_aktion, snapshot_model, diff_model
    lg = get_object_or_404(Liegenschaft, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
        alt_snap = snapshot_model(Liegenschaft.objects.get(pk=pk)) if pk else {}
        obj = lg or Liegenschaft()
        obj.strasse = P.get('strasse', '').strip()
        obj.plz = P.get('plz', '').strip()
        obj.ort = P.get('ort', '').strip()
        obj.kanton = P.get('kanton', '').strip()
        obj.egid = P.get('egid', '').strip()
        obj.kataster_nummer = P.get('kataster_nummer', '').strip()

        def intval(key):
            v = P.get(key, '').strip()
            try:
                return int(v) if v else None
            except ValueError:
                return None

        def decval(key):
            v = _num(P.get(key))
            try:
                return Decimal(v) if v else None
            except Exception:
                return None
        obj.baujahr = intval('baujahr')
        md_id = P.get('eigentuemer_id') or ''
        obj.eigentuemer = Eigentuemer.objects.filter(id=md_id).first() if md_id else None
        obj.versicherungswert = decval('versicherungswert')
        obj.grundstuecksflaeche_m2 = decval('grundstuecksflaeche_m2')
        obj.gebaeudevolumen_m3 = decval('gebaeudevolumen_m3')
        # Bewertung (Rendite) + Energie/GEAK
        obj.verkehrswert = decval('verkehrswert')
        obj.anlagekosten = decval('anlagekosten')
        obj.kaufpreis = decval('kaufpreis')
        obj.energiebezugsflaeche_m2 = decval('energiebezugsflaeche_m2')
        _heiz = P.get('heizsystem', '').strip()
        obj.heizsystem = _heiz if _heiz in dict(Liegenschaft.HEIZ_CHOICES) else ''
        _ww = P.get('warmwasser', '').strip()
        obj.warmwasser = _ww if _ww in dict(Liegenschaft.WARMWASSER_CHOICES) else ''
        _gk = P.get('geak_klasse', '').strip().upper()
        obj.geak_klasse = _gk if _gk in dict(Liegenschaft.GEAK_KLASSEN) else ''
        _gkg = P.get('geak_klasse_gesamt', '').strip().upper()
        obj.geak_klasse_gesamt = _gkg if _gkg in dict(Liegenschaft.GEAK_KLASSEN) else ''
        obj.energietraeger = P.get('energietraeger', '').strip()
        try:
            _gd = P.get('geak_datum') or ''
            obj.geak_datum = date.fromisoformat(_gd) if _gd else None
        except ValueError:
            obj.geak_datum = None
        obj.hauswart_name = P.get('hauswart_name', '').strip()
        obj.hauswart_telefon = P.get('hauswart_telefon', '').strip()
        obj.sanitaer_name = P.get('sanitaer_name', '').strip()
        obj.sanitaer_telefon = P.get('sanitaer_telefon', '').strip()
        obj.elektriker_name = P.get('elektriker_name', '').strip()
        obj.elektriker_telefon = P.get('elektriker_telefon', '').strip()
        obj.bank_name = P.get('bank_name', '').strip()
        obj.iban = P.get('iban', '').strip()
        obj.hkvo_aktiv = P.get('hkvo_aktiv') == 'on'
        try:
            obj.hkvo_grundkosten_prozent = int(P.get('hkvo_grundkosten_prozent') or 40)
        except ValueError:
            obj.hkvo_grundkosten_prozent = 40
        obj.save()
        _diff = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
        log_aktion(request, "Liegenschaft bearbeitet" if pk else "Liegenschaft erstellt",
                   f"{obj.strasse}, {obj.ort}", _diff, ziel=obj)
        messages.success(request, f"✅ Liegenschaft {obj.strasse} gespeichert.")

        # Automatischer GWR/EGID-Import (nur wenn gewünscht) — ermittelt die EGID
        # aus der Adresse und importiert die Objekte (Wohnungen) vom Bundesamt.
        if P.get('gwr_import', 'on') == 'on' and (not obj.egid or obj.einheiten.count() == 0):
            try:
                from portfolio.services import sync_liegenschaft_with_gwr
                res = sync_liegenschaft_with_gwr(obj)
                if res.get('egid_found'):
                    messages.success(request, f"📍 EGID {res['egid_found']} automatisch ermittelt.")
                if res.get('units_created'):
                    messages.success(request, f"🏠 {res['units_created']} Objekt(e) automatisch aus dem Gebäude- und Wohnungsregister importiert.")
                if not obj.egid and not res.get('egid_found'):
                    messages.warning(request, "⚠️ EGID konnte nicht automatisch ermittelt werden — bitte Adresse prüfen oder EGID manuell erfassen.")
                elif res.get('error'):
                    messages.warning(request, f"⚠️ GWR-Import teilweise fehlgeschlagen: {res['error']}")
            except Exception as e:
                messages.warning(request, f"⚠️ Automatischer GWR-Import nicht möglich: {e}")
        return redirect(f'/neu/liegenschaften/{obj.id}/')

    return render(request, 'fw/liegenschaft_form.html', {
        **basis, 'nav': 'liegenschaften', 'lg': lg, 'ist_neu': lg is None,
        'eigentuemer': Eigentuemer.objects.all().order_by('firma_oder_name'),
        'heiz_choices': Liegenschaft.HEIZ_CHOICES,
        'warmwasser_choices': Liegenschaft.WARMWASSER_CHOICES,
        'geak_klassen': [k for k, _ in Liegenschaft.GEAK_KLASSEN],
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_liegenschaft_gwr(request, pk):
    """GWR/EGID-Import manuell (erneut) auslösen — z.B. wenn er beim Anlegen
    fehlschlug oder die Objekte nachträglich vom Bund geladen werden sollen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    lg = get_object_or_404(Liegenschaft, id=pk)
    try:
        from portfolio.services import sync_liegenschaft_with_gwr
        res = sync_liegenschaft_with_gwr(lg)
        if res.get('egid_found'):
            messages.success(request, f"📍 EGID {res['egid_found']} ermittelt.")
        if res.get('units_created'):
            messages.success(request, f"🏠 {res['units_created']} Objekt(e) aus dem GWR importiert.")
        if not res.get('egid_found') and not res.get('units_created'):
            if lg.egid and lg.einheiten.count() > 0:
                messages.info(request, "Objekte bereits erfasst — kein weiterer Import nötig.")
            elif not lg.egid:
                messages.warning(request, "⚠️ EGID konnte nicht ermittelt werden — Adresse prüfen.")
            else:
                messages.info(request, "Keine neuen Objekte im GWR gefunden.")
        if res.get('error'):
            messages.warning(request, f"⚠️ Hinweis: {res['error']}")
    except Exception as e:
        messages.warning(request, f"⚠️ GWR-Import nicht möglich: {e}")
    return redirect(f'/neu/liegenschaften/{lg.id}/')


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_liegenschaft_loeschen(request, pk):
    """Liegenschaft löschen. Blockiert, solange aktive Verträge bestehen —
    diese müssen zuerst beendet werden (Schutz vor versehentlichem Datenverlust)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    lg = get_object_or_404(Liegenschaft, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/liegenschaften/{lg.id}/')

    aktive = Mietvertrag.objects.filter(einheit__liegenschaft=lg, status='aktiv').count()
    if aktive:
        messages.error(request, f"❌ Liegenschaft kann nicht gelöscht werden: {aktive} aktive(r) Vertrag/Verträge. Bitte zuerst kündigen/beenden.")
        return redirect(f'/neu/liegenschaften/{lg.id}/')

    name = f"{lg.strasse}, {lg.plz} {lg.ort}"
    anz_obj = lg.einheiten.count()
    log_aktion(request, "Liegenschaft gelöscht", name, f"inkl. {anz_obj} Objekt(e)")
    lg.delete()   # cascade: Objekte, Zähler, Geräte, beendete Verträge etc.
    messages.success(request, f'🗑️ Liegenschaft „{name}" inkl. {anz_obj} Objekt(e) gelöscht.')
    return redirect('/neu/liegenschaften/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_versicherung_add(request, lg_id):
    """Versicherungspolice zu einer Liegenschaft erfassen (Register)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Versicherung
    from core.auth import log_aktion
    lg = get_object_or_404(Liegenschaft, id=lg_id)
    if request.method != 'POST':
        return redirect(f'/neu/liegenschaften/{lg.id}/')
    P = request.POST

    def dec(key):
        v = _num(P.get(key))
        try:
            return Decimal(v) if v else None
        except Exception:
            return None
    art = P.get('art', 'gebaeude')
    ablauf = None
    try:
        ablauf = date.fromisoformat((P.get('ablauf_datum') or '').strip()) if P.get('ablauf_datum') else None
    except ValueError:
        ablauf = None
    Versicherung.objects.create(
        liegenschaft=lg, art=art if art in dict(Versicherung.ART_CHOICES) else 'andere',
        gesellschaft=P.get('gesellschaft', '').strip(),
        policennummer=P.get('policennummer', '').strip(),
        versicherungssumme=dec('versicherungssumme'), jahrespraemie=dec('jahrespraemie'),
        ablauf_datum=ablauf, notiz=P.get('notiz', '').strip())
    log_aktion(request, "Versicherung erfasst", f"{lg.strasse}", P.get('gesellschaft', ''), ziel=lg)
    messages.success(request, "✅ Versicherung erfasst.")
    return redirect(f'/neu/liegenschaften/{lg.id}/?tab=finanzen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_versicherung_loeschen(request, pk):
    """Versicherungspolice entfernen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Versicherung
    vs = get_object_or_404(Versicherung, id=pk)
    lg_id = vs.liegenschaft_id
    if request.method == 'POST':
        vs.delete()
        messages.success(request, "✅ Versicherung entfernt.")
    return redirect(f'/neu/liegenschaften/{lg_id}/?tab=finanzen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_objekt_form(request, pk=None):
    """Mietobjekt (Einheit) erfassen oder bearbeiten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion, snapshot_model, diff_model
    e = get_object_or_404(Einheit, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
        alt_snap = snapshot_model(Einheit.objects.get(pk=pk)) if pk else {}
        obj = e or Einheit()
        lg_id = P.get('liegenschaft_id') or (e.liegenschaft_id if e else None)
        obj.liegenschaft = get_object_or_404(Liegenschaft, id=lg_id)
        obj.bezeichnung = P.get('bezeichnung', '').strip()
        obj.typ = P.get('typ', 'whg')
        obj.etage = P.get('etage', '').strip()
        obj.ewid = P.get('ewid', '').strip()

        def dec(key):
            v = _num(P.get(key))
            try:
                return Decimal(v) if v else None
            except Exception:
                return None
        obj.zimmer = dec('zimmer')
        obj.flaeche_m2 = dec('flaeche_m2')
        obj.volumen_m3 = dec('volumen_m3')
        _wq = dec('wertquote')
        if _wq is not None:
            obj.wertquote = _wq
        obj.keller = P.get('keller', '').strip()
        obj.estrich = P.get('estrich', '').strip()
        obj.oto_dose = P.get('oto_dose', '').strip()
        obj.bodenbelag = P.get('bodenbelag', '').strip()
        obj.bodenbelag_nassraum = P.get('bodenbelag_nassraum', '').strip()

        def intval(key):
            v = str(P.get(key) or '').strip()
            try:
                return int(v) if v else None
            except ValueError:
                return None
        obj.letzte_renovation = intval('letzte_renovation')
        _km = intval('standard_kautionsmonate')
        if _km is not None:
            obj.standard_kautionsmonate = _km
        # Nebenobjekt-Zuordnung (Parkplatz/Keller → Hauptobjekt derselben Liegenschaft)
        gz_id = P.get('gehoert_zu_id') or ''
        if gz_id and gz_id != str(obj.pk or ''):
            obj.gehoert_zu = Einheit.objects.filter(id=gz_id, liegenschaft=obj.liegenschaft).first()
        else:
            obj.gehoert_zu = None
        obj.notizen = P.get('notizen', '').strip()
        # Der Mietzins wird NICHT mehr direkt am Objekt gepflegt — einzige Quelle
        # ist der datierte Sollmietzins (Objekt → Mietzins). nettomiete_aktuell/
        # nebenkosten_aktuell sind rein abgeleitet (sync_aktuelle_miete beim
        # Speichern einer Sollmietzins-Zeile) → kein Drift mehr zwischen Objekt-
        # Maske und Mietzins-Tab.
        obj.save()
        # Nur bei NEUanlage: optionalen Anfangsmietzins als erste Sollmietzins-Zeile
        # seeden (single source). Bestehende Objekte pflegen die Miete ausschliesslich
        # über den Mietzins-Tab.
        from portfolio.models import Sollmietzins
        if not pk:
            netto0 = dec('nettomiete_aktuell') or Decimal('0.00')
            nk0 = Decimal('0.00') if obj.ist_einstellplatz else (dec('nebenkosten_aktuell') or Decimal('0.00'))
            if netto0 > 0 or nk0 > 0:
                soll_ab_raw = (P.get('soll_gueltig_ab') or '').strip()
                try:
                    soll_ab = date.fromisoformat(soll_ab_raw) if soll_ab_raw else timezone.localdate()
                except ValueError:
                    soll_ab = timezone.localdate()
                Sollmietzins.objects.create(
                    einheit=obj, gueltig_ab=soll_ab,
                    netto_mietzins=netto0, nebenkosten=nk0, notiz='Ersterfassung')
        _diff = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
        log_aktion(request, "Objekt bearbeitet" if pk else "Objekt erstellt",
                   f"{obj.bezeichnung} ({obj.liegenschaft.strasse})", _diff, ziel=obj)
        messages.success(request, f"✅ Objekt {obj.bezeichnung} gespeichert.")
        return redirect(f'/neu/objekte/{obj.id}/')

    vorwahl_lg = request.GET.get('lg') or (e.liegenschaft_id if e else None)
    sollmietzinse = list(e.sollmietzinse.all()) if e else []
    aktueller_soll = e.aktueller_sollmietzins() if e else None
    # Mögliche Hauptobjekte für die Nebenobjekt-Zuordnung (gehoert_zu): übrige
    # Einheiten derselben Liegenschaft (ohne sich selbst).
    hauptobjekte = []
    if e and e.liegenschaft_id:
        hauptobjekte = list(Einheit.objects.filter(liegenschaft_id=e.liegenschaft_id)
                            .exclude(id=e.id).order_by('bezeichnung'))
    return render(request, 'fw/objekt_form.html', {
        **basis, 'nav': 'objekte', 'e': e, 'ist_neu': e is None,
        'liegenschaften': Liegenschaft.objects.all().order_by('strasse'),
        'vorwahl_lg': str(vorwahl_lg) if vorwahl_lg else '',
        'typ_choices': Einheit.TYP_CHOICES,
        'sollmietzinse': sollmietzinse,
        'aktueller_soll_id': aktueller_soll.id if aktueller_soll else None,
        'heute_iso': timezone.localdate().isoformat(),
        'hauptobjekte': hauptobjekte,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_suche(request):
    """Globale Suche über Personen, Liegenschaften, Objekte und Verträge."""
    q = (request.GET.get('q') or '').strip()
    basis = _global_filter(request)
    personen, liegenschaften, objekte, vertraege = [], [], [], []

    if q:
        # Telefon-Suche: Nummern werden in vielen Formaten erfasst («079 123 45 67»,
        # «+41791234567») — Query UND Feldwerte auf reine Ziffern normalisieren,
        # damit der Anrufer vom Display direkt gefunden wird.
        personen_q = (Q(vorname__icontains=q) | Q(nachname__icontains=q)
                      | Q(firmen_name__icontains=q) | Q(email__icontains=q)
                      | Q(ort__icontains=q)
                      | Q(mobile__icontains=q) | Q(telefon_privat__icontains=q)
                      | Q(telefon_geschaeft__icontains=q))
        personen = list(Mieter.objects.filter(personen_q)
                        .order_by('nachname', 'firmen_name')[:20])
        ziffern = ''.join(ch for ch in q if ch.isdigit())
        if len(ziffern) >= 5 and len(personen) < 20:
            # Format-agnostischer Nachfilter über die Telefon-Felder.
            vorhandene = {p.id for p in personen}
            for p in Mieter.objects.exclude(id__in=vorhandene).exclude(
                    mobile='', telefon_privat='', telefon_geschaeft='')[:500]:
                nummern = ''.join(ch for ch in f"{p.mobile}|{p.telefon_privat}|{p.telefon_geschaeft}" if ch.isdigit())
                if ziffern in nummern:
                    personen.append(p)
                    if len(personen) >= 20:
                        break

        liegenschaften = list(Liegenschaft.objects.filter(
            Q(strasse__icontains=q) | Q(ort__icontains=q) | Q(plz__icontains=q) | Q(egid__icontains=q)
        ).order_by('strasse')[:20])

        objekte = list(Einheit.objects.select_related('liegenschaft').filter(
            Q(bezeichnung__icontains=q) | Q(etage__icontains=q)
            | Q(liegenschaft__strasse__icontains=q) | Q(liegenschaft__ort__icontains=q)
        ).order_by('liegenschaft__strasse', 'bezeichnung')[:20])

        vertraege = list(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft').filter(
            Q(mieter__vorname__icontains=q) | Q(mieter__nachname__icontains=q)
            | Q(mieter__firmen_name__icontains=q) | Q(einheit__bezeichnung__icontains=q)
            | Q(einheit__liegenschaft__strasse__icontains=q)
        ).order_by('-beginn')[:20])

    total = len(personen) + len(liegenschaften) + len(objekte) + len(vertraege)
    return render(request, 'fw/suche.html', {
        **basis, 'nav': '', 'q': q, 'total': total,
        'personen': personen, 'liegenschaften': liegenschaften,
        'objekte': objekte, 'vertraege': vertraege,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_palette_suche(request):
    """Datensätze für die ⌘K-Palette, als JSON.

    WARUM ES DIESEN ENDPUNKT GIBT (B7, E1.2)

    Die Palette kannte bis hierher nur SEITEN — sie war die flache Liste der
    Menü-Labels. Wer «Blaser» tippte, bekam «Keine Seite gefunden» und musste
    die Eingabe mit ↵ an `/neu/suche/` weiterreichen, also eine zweite Suche
    starten und eine zweite Ergebnisseite lesen.

    Für eine Verwaltung mit 300 Mietverhältnissen ist die Datensatzsuche aber
    der Normalfall und die Seitensuche die Ausnahme: Man sucht Frau Blaser,
    nicht die Seite «Mietverhältnisse». Ein Werkzeug hat dafür EIN Feld.

    WAS ZURÜCKKOMMT

    Höchstens 15 Treffer über vier Arten, mit Typ, Beschriftung, Zusatz und
    Adresse. Wenig genug, um ohne Blättern lesbar zu sein — die vollständige
    Trefferliste bleibt `/neu/suche/`, und die Palette verweist am Ende
    dorthin.

    MANDANTENTRENNUNG

    Über die Manager der Modelle, wie überall: `Mieter.objects` &c. liefern
    nur den eigenen Mandanten. Dieser Endpunkt enthält KEINE eigene
    Organisationslogik — genau deshalb kann er sie auch nicht falsch machen.
    `core/tests/test_palette_suche.py` prüft das mit einem zweiten Mandanten.
    """
    from django.http import JsonResponse

    q = (request.GET.get('q') or '').strip()
    if len(q) < 2:
        # Ein einzelner Buchstabe trifft fast alles und kostet vier Abfragen
        # bei jedem Tastendruck. Die Palette zeigt bis dahin die Seiten.
        return JsonResponse({'treffer': [], 'q': q})

    def ueber_felder(*felder):
        """Jedes Wort der Eingabe muss in IRGENDEINEM der Felder vorkommen.

        WARUM WORTWEISE UND NICHT AM STÜCK

        Menschen tippen «Anna Blaser», das Programm speichert Vorname und
        Nachname getrennt. Ein `icontains` über die ganze Eingabe prüft dann
        «enthält der Vorname die Zeichenkette 'Anna Blaser'?» — nein, und
        «enthält der Nachname sie?» — auch nicht. Die Suche fand die Person
        also genau dann nicht, wenn man ihren vollen Namen kannte.

        Jedes Wort einzeln, alle mit UND verknüpft: «Anna Blaser» findet die
        Person, «Blaser Anna» ebenso, «Blaser Bahnhofstrasse» grenzt weiter
        ein statt mehr zu liefern.
        """
        bedingung = Q()
        for wort in q.split():
            oder = Q()
            for feld in felder:
                oder |= Q(**{f'{feld}__icontains': wort})
            bedingung &= oder
        return bedingung

    treffer = []

    for m in (Mieter.objects.filter(
            ueber_felder('vorname', 'nachname', 'firmen_name', 'email', 'ort'))
            .order_by('nachname', 'firmen_name')[:5]):
        treffer.append({
            'art': 'Person',
            'label': str(m),
            'zusatz': m.ort or m.email or '',
            'url': f'/neu/personen/{m.id}/',
        })

    for lg in (Liegenschaft.objects.filter(
            ueber_felder('strasse', 'ort', 'plz'))
            .order_by('strasse')[:4]):
        treffer.append({
            'art': 'Liegenschaft',
            'label': lg.strasse,
            'zusatz': f'{lg.plz} {lg.ort}'.strip(),
            'url': f'/neu/liegenschaften/{lg.id}/',
        })

    for e in (Einheit.objects.select_related('liegenschaft').filter(
            ueber_felder('bezeichnung', 'liegenschaft__strasse'))
            .order_by('liegenschaft__strasse', 'bezeichnung')[:3]):
        treffer.append({
            'art': 'Objekt',
            'label': e.bezeichnung,
            'zusatz': e.liegenschaft.strasse if e.liegenschaft_id else '',
            'url': f'/neu/objekte/{e.id}/',
        })

    for v in (Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft').filter(
            ueber_felder('mieter__vorname', 'mieter__nachname', 'mieter__firmen_name',
                         'einheit__liegenschaft__strasse', 'einheit__bezeichnung'))
            .order_by('-beginn')[:3]):
        ort = ''
        if v.einheit_id and v.einheit.liegenschaft_id:
            ort = f'{v.einheit.liegenschaft.strasse}, {v.einheit.bezeichnung}'
        treffer.append({
            'art': 'Mietverhältnis',
            'label': str(v.mieter) if v.mieter_id else f'MV-{v.id}',
            'zusatz': ort,
            'url': f'/neu/vertraege/{v.id}/',
        })

    return JsonResponse({'treffer': treffer[:15], 'q': q})
