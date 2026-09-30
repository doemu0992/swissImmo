# core/views/fw/liegenschaft_crud.py
#
# Liegenschaften und Objekte anlegen und bearbeiten, GWR-Abgleich,
# Versicherungspolicen, globale Suche. Etappe 1, siehe
# docs/ETAPPE-1-ZERLEGEN.md.

from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.utils.translation import gettext
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from crm.models import Mieter
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag

from ._basis import _global_filter, _num, team_der_organisation


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

    from portfolio.forms import LiegenschaftForm
    # Frische Instanz fuer das Formular: `is_valid()` schreibt die Eingaben in
    # die Instanz. Kopf und Brotkrume zeigen weiter `lg`, also den Stand vor
    # dem Speichern — auch wenn das Formular mit Fehlern zurueckkommt.
    form = LiegenschaftForm(instance=lg)
    feld_fehler = {}
    betreut_wert = str(lg.betreut_von_id or '') if lg else ''
    eigentuemer_wert = str(lg.eigentuemer_id or '') if lg else ''

    if request.method == 'POST':
        P = request.POST
        alt_snap = snapshot_model(Liegenschaft.objects.get(pk=pk)) if pk else {}
        form = LiegenschaftForm(P, instance=Liegenschaft.objects.get(pk=pk) if pk else Liegenschaft())
        # DIE BETREUUNG (E2.70). `'x' in P` statt `P.get()`: Ein Formular, das
        # das Feld NICHT mitschickt, darf die Zuteilung nicht loeschen —
        # derselbe Fall wie beim Stundensatz (E2.47).
        #
        # DIE ID WIRD GEPRUEFT, NICHT GEGLAUBT.
        #
        # Ein erster Entwurf schrieb `int(wert)` direkt ins Feld. GEMESSEN: Ein
        # POST mit der ID einer Person aus einer FREMDEN Verwaltung ging durch
        # (302, Feld gesetzt) — und ueber `zulauf._betreuer_fuer` erbte diese
        # Person danach JEDEN neuen Fall an dieser Liegenschaft.
        #
        # Dieselbe Luecke, die dieselbe Etappe am Fall geschlossen hat: `Fall`
        # prueft ueber `Mitgliedschaft`, das Formular hier tat es nicht. Eine
        # Grenze, die an drei Stellen einzeln gezogen wird, ist an zweien
        # gezogen — deshalb jetzt beide ueber `team_der_organisation`.
        #
        # Seit Audit Etappe 2 ein Feldfehler statt Umleitung: Die Umleitung
        # warf alle uebrigen Eingaben weg.
        betreut_setzen, person = 'betreut_von' in P, None
        if betreut_setzen:
            betreut_wert = (P.get('betreut_von') or '').strip()
            if betreut_wert:
                if betreut_wert.isdigit():
                    person = team_der_organisation(
                        getattr(request, 'organisation', None)).filter(pk=betreut_wert).first()
                if person is None:
                    feld_fehler['betreut_von'] = gettext('Diese Person gehört nicht zu Ihrer Verwaltung.')
        # Der Eigentuemer kommt ueber den `TenantManager`: Eine fremde ID
        # findet nichts. Bisher wurde daraus STILL «kein Eigentuemer».
        eigentuemer_wert = (P.get('eigentuemer_id') or '').strip()
        eigentuemer = None
        if eigentuemer_wert:
            if eigentuemer_wert.isdigit():
                eigentuemer = Eigentuemer.objects.filter(id=eigentuemer_wert).first()
            if eigentuemer is None:
                feld_fehler['eigentuemer_id'] = gettext('Dieser Eigentümer ist nicht (mehr) erfasst.')

        if form.is_valid() and not feld_fehler:
            obj = form.save(commit=False)
            if betreut_setzen:
                obj.betreut_von = person
            obj.eigentuemer = eigentuemer
            obj.save()
            _diff = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
            log_aktion(request, "Liegenschaft bearbeitet" if pk else "Liegenschaft erstellt",
                       f"{obj.strasse}, {obj.ort}", _diff, ziel=obj)
            messages.success(request, '✅ ' + gettext('Liegenschaft %(strasse)s gespeichert.') % {'strasse': obj.strasse})

            # Automatischer GWR/EGID-Import (nur wenn gewünscht) — ermittelt die EGID
            # aus der Adresse und importiert die Objekte (Wohnungen) vom Bundesamt.
            # Ein abgewähltes Kontrollkästchen schickt der Browser gar nicht
            # mit. Mit `P.get('gwr_import', 'on')` griff dann der Vorgabewert,
            # und der Import lief trotz abgewähltem Häkchen (Audit).
            if P.get('gwr_import') == 'on' and (not obj.egid or obj.einheiten.count() == 0):
                try:
                    from portfolio.services import sync_liegenschaft_with_gwr
                    res = sync_liegenschaft_with_gwr(obj)
                    if res.get('egid_found'):
                        messages.success(request, '📍 ' + gettext('EGID %(wert)s automatisch ermittelt.') % {'wert': res['egid_found']})
                    if res.get('units_created'):
                        messages.success(request, '🏠 ' + gettext('%(wert)s Objekt(e) automatisch aus dem Gebäude- und Wohnungsregister importiert.') % {'wert': res['units_created']})
                    if not obj.egid and not res.get('egid_found'):
                        messages.warning(request, '⚠️ ' + gettext('EGID konnte nicht automatisch ermittelt werden — bitte Adresse prüfen oder EGID manuell erfassen.'))
                    elif res.get('error'):
                        messages.warning(request, '⚠️ ' + gettext('GWR-Import teilweise fehlgeschlagen: %(wert)s') % {'wert': res['error']})
                except Exception as e:
                    messages.warning(request, '⚠️ ' + gettext('Automatischer GWR-Import nicht möglich: %(e)s') % {'e': e})
            return redirect(f'/neu/liegenschaften/{obj.id}/')

    # Mit Fehlern zurueck auf dieselbe Seite — Eingaben bleiben stehen, jede
    # Meldung steht an ihrem Feld. 400, damit Tests und Werkzeuge den
    # Fehlschlag als solchen erkennen.
    anzahl_fehler = len(form.errors) + len(feld_fehler)
    return render(request, 'fw/liegenschaft_form.html', {
        'form': form, 'feld_fehler': feld_fehler, 'anzahl_fehler': anzahl_fehler,
        'betreut_wert': betreut_wert, 'eigentuemer_wert': eigentuemer_wert,
        # Wer zur Auswahl steht: die Mitglieder dieser Organisation. Der
        # `TenantManager` sorgt fuer die Grenze — eine fremde Person kann
        # keine Liegenschaft betreuen.
        'benutzer_auswahl': list(team_der_organisation(
            getattr(request, 'organisation', None))[:100]),
        **basis, 'nav': 'liegenschaften', 'lg': lg, 'ist_neu': lg is None,
        'eigentuemer': Eigentuemer.objects.all().order_by('firma_oder_name'),
        'heiz_choices': Liegenschaft.HEIZ_CHOICES,
        'warmwasser_choices': Liegenschaft.WARMWASSER_CHOICES,
        'geak_klassen': [k for k, _ in Liegenschaft.GEAK_KLASSEN],
    }, status=400 if anzahl_fehler else 200)


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
            messages.success(request, '📍 ' + gettext('EGID %(wert)s ermittelt.') % {'wert': res['egid_found']})
        if res.get('units_created'):
            messages.success(request, '🏠 ' + gettext('%(wert)s Objekt(e) aus dem GWR importiert.') % {'wert': res['units_created']})
        if not res.get('egid_found') and not res.get('units_created'):
            if lg.egid and lg.einheiten.count() > 0:
                messages.info(request, gettext('Objekte bereits erfasst — kein weiterer Import nötig.'))
            elif not lg.egid:
                messages.warning(request, '⚠️ ' + gettext('EGID konnte nicht ermittelt werden — Adresse prüfen.'))
            else:
                messages.info(request, gettext('Keine neuen Objekte im GWR gefunden.'))
        if res.get('error'):
            messages.warning(request, '⚠️ ' + gettext('Hinweis: %(wert)s') % {'wert': res['error']})
    except Exception as e:
        messages.warning(request, '⚠️ ' + gettext('GWR-Import nicht möglich: %(e)s') % {'e': e})
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
        messages.error(request, '❌ ' + gettext('Liegenschaft kann nicht gelöscht werden: %(aktive)s aktive(r) Vertrag/Verträge. Bitte zuerst kündigen/beenden.') % {'aktive': aktive})
        return redirect(f'/neu/liegenschaften/{lg.id}/')

    name = f"{lg.strasse}, {lg.plz} {lg.ort}"
    anz_obj = lg.einheiten.count()
    log_aktion(request, "Liegenschaft gelöscht", name, f"inkl. {anz_obj} Objekt(e)")
    lg.delete()   # cascade: Objekte, Zähler, Geräte, beendete Verträge etc.
    messages.success(request, '🗑️ ' + gettext('Liegenschaft „%(name)s" inkl. %(anz_obj)s Objekt(e) gelöscht.') % {'name': name, 'anz_obj': anz_obj})
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
        selbstbehalt=dec('selbstbehalt'),
        ablauf_datum=ablauf, notiz=P.get('notiz', '').strip())
    log_aktion(request, "Versicherung erfasst", f"{lg.strasse}", P.get('gesellschaft', ''), ziel=lg)
    messages.success(request, '✅ ' + gettext('Versicherung erfasst.'))
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
        messages.success(request, '✅ ' + gettext('Versicherung entfernt.'))
    return redirect(f'/neu/liegenschaften/{lg_id}/?tab=finanzen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_objekt_form(request, pk=None):
    """Mietobjekt (Einheit) erfassen oder bearbeiten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion, snapshot_model, diff_model
    e = get_object_or_404(Einheit, id=pk) if pk else None
    basis = _global_filter(request)
    from portfolio.forms import EinheitForm
    form = EinheitForm(instance=e, initial={'soll_gueltig_ab': timezone.localdate()})
    feld_fehler = {}
    lg_wert = str(e.liegenschaft_id) if e else ''
    gz_wert = str(e.gehoert_zu_id or '') if e else ''

    if request.method == 'POST':
        P = request.POST
        alt_snap = snapshot_model(Einheit.objects.get(pk=pk)) if pk else {}
        form = EinheitForm(P, instance=Einheit.objects.get(pk=pk) if pk else Einheit())
        # Liegenschaft ueber den TenantManager: Eine fremde ID findet nichts.
        # Vorher 404 — und alle Eingaben waren weg.
        lg_wert = (P.get('liegenschaft_id') or lg_wert or '').strip()
        liegenschaft = (Liegenschaft.objects.filter(id=lg_wert).first()
                        if lg_wert.isdigit() else None)
        if liegenschaft is None:
            feld_fehler['liegenschaft_id'] = gettext('Bitte eine Liegenschaft wählen.')
        # Nebenobjekt-Zuordnung (Parkplatz/Keller → Hauptobjekt derselben
        # Liegenschaft). Unbekannt oder fremd war bisher STILL «eigenständig».
        gz_wert = (P.get('gehoert_zu_id') or '').strip()
        hauptobjekt = None
        if gz_wert and gz_wert != str(pk or '') and liegenschaft is not None:
            hauptobjekt = (Einheit.objects.filter(id=gz_wert, liegenschaft=liegenschaft).first()
                           if gz_wert.isdigit() else None)
            if hauptobjekt is None:
                feld_fehler['gehoert_zu_id'] = gettext(
                    'Das Hauptobjekt muss zur selben Liegenschaft gehören.')

        if form.is_valid() and not feld_fehler:
            obj = form.save(commit=False)
            obj.liegenschaft = liegenschaft
            obj.gehoert_zu = hauptobjekt
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
                c = form.cleaned_data
                netto0 = c.get('nettomiete_aktuell') or Decimal('0.00')
                nk0 = Decimal('0.00') if obj.ist_einstellplatz else (c.get('nebenkosten_aktuell') or Decimal('0.00'))
                if netto0 > 0 or nk0 > 0:
                    # Leer heisst heute; ein UNGUELTIGES Datum ist ein Feldfehler
                    # (EinheitForm), nicht mehr still «heute».
                    soll_ab = c.get('soll_gueltig_ab') or timezone.localdate()
                    Sollmietzins.objects.create(
                        einheit=obj, gueltig_ab=soll_ab,
                        netto_mietzins=netto0, nebenkosten=nk0, notiz='Ersterfassung')
            _diff = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
            log_aktion(request, "Objekt bearbeitet" if pk else "Objekt erstellt",
                       f"{obj.bezeichnung} ({obj.liegenschaft.strasse})", _diff, ziel=obj)
            messages.success(request, '✅ ' + gettext('Objekt %(bezeichnung)s gespeichert.') % {'bezeichnung': obj.bezeichnung})
            return redirect(f'/neu/objekte/{obj.id}/')

    vorwahl_lg = lg_wert or request.GET.get('lg') or ''
    sollmietzinse = list(e.sollmietzinse.all()) if e else []
    aktueller_soll = e.aktueller_sollmietzins() if e else None
    # Mögliche Hauptobjekte für die Nebenobjekt-Zuordnung (gehoert_zu): übrige
    # Einheiten derselben Liegenschaft (ohne sich selbst).
    hauptobjekte = []
    if e and e.liegenschaft_id:
        hauptobjekte = list(Einheit.objects.filter(liegenschaft_id=e.liegenschaft_id)
                            .exclude(id=e.id).order_by('bezeichnung'))
    anzahl_fehler = len(form.errors) + len(feld_fehler)
    return render(request, 'fw/objekt_form.html', {
        'form': form, 'feld_fehler': feld_fehler, 'anzahl_fehler': anzahl_fehler,
        'gz_wert': gz_wert,
        **basis, 'nav': 'objekte', 'e': e, 'ist_neu': e is None,
        'liegenschaften': Liegenschaft.objects.all().order_by('strasse'),
        'vorwahl_lg': str(vorwahl_lg) if vorwahl_lg else '',
        'typ_choices': Einheit.TYP_CHOICES,
        'sollmietzinse': sollmietzinse,
        'aktueller_soll_id': aktueller_soll.id if aktueller_soll else None,
        'heute_iso': timezone.localdate().isoformat(),
        'hauptobjekte': hauptobjekte,
    }, status=400 if anzahl_fehler else 200)


def telefon_kern(text):
    """Eine Telefonnummer auf ihren vergleichbaren Kern reduzieren.

    DER BEFUND, DER DAZU GEFUEHRT HAT

    Die Kopfzeilensuche fand `+41 79 123 45 67` nicht, wenn die Nummer als
    `079 123 45 67` gespeichert war — auch im eigenen Bestand. Der Kommentar
    im Code nannte genau dieses Format als Ziel.

    Ursache: «Nur die Ziffern behalten» macht aus der Eingabe `41791234567`
    und aus dem Feld `0791234567`. Die Landesvorwahl ERSETZT die fuehrende
    Null, sie ergaenzt sie nicht — die eine Zeichenkette kommt in der anderen
    nicht vor.

    Betroffen ist der Alltagsfall: Ein Anrufer erscheint auf dem Display in
    internationaler Schreibweise, der Sachbearbeiter tippt sie ab und findet
    nichts.

    WAS DIE FUNKTION TUT

    Landesvorwahl (`0041`, `+41`, `41`) und fuehrende Null fallen weg. Uebrig
    bleibt die Nummer ohne Vorsatz — `791234567` in beiden Schreibweisen.

    Nur die Schweizer Vorwahl wird behandelt. Eine auslaendische Nummer
    (`+49 30 …`) bleibt vollstaendig; sie waere sonst nicht mehr von einer
    Schweizer Nummer zu unterscheiden.
    """
    ziffern = ''.join(ch for ch in (text or '') if ch.isdigit())
    if ziffern.startswith('0041'):
        ziffern = ziffern[4:]
    elif ziffern.startswith('41') and len(ziffern) >= 11:
        # `41` am Anfang ist nur dann Landesvorwahl, wenn danach eine
        # vollstaendige Nummer folgt. Sonst waere `41 22 …` (Genf, ohne Null)
        # faelschlich gekuerzt.
        ziffern = ziffern[2:]
    return ziffern.lstrip('0')


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
        ziffern = telefon_kern(q)
        if len(ziffern) >= 5 and len(personen) < 20:
            # Format-agnostischer Nachfilter über die Telefon-Felder.
            vorhandene = {p.id for p in personen}
            for p in Mieter.objects.exclude(id__in=vorhandene).exclude(
                    mobile='', telefon_privat='', telefon_geschaeft='')[:500]:
                # Jedes Feld einzeln normalisieren: Ein Zusammenkleben mit
                # Trennzeichen und anschliessendes Ziffernfiltern wuerde
                # Nummern aneinanderhaengen und Treffer ueber Feldgrenzen
                # hinweg erzeugen.
                nummern = [telefon_kern(x) for x in
                           (p.mobile, p.telefon_privat, p.telefon_geschaeft)]
                if any(ziffern in n for n in nummern if n):
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
