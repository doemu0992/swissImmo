# core/views/fw/liegenschaft_detail.py
#
# Die Liegenschaft-Akte: Kopf, Detailseite, Wartungsfristen und Budget.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md. Herausgeloest aus detailseiten.py.

from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext, ngettext

from core.auth import (rolle_erforderlich, SCHREIB_ROLLEN,
                       TEAM_ROLLEN)
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag

from ._basis import (_global_filter)
from .schluessel import schliessanlage_kontext as _schliessanlage_kontext
from core.utils.betrag import betrag_normalisieren
from .ausstattung import _raumbuch_zeilen
from .objekt_geraete import GERAET_KATEGORIEN, ZAEHLER_TYPEN


# ============================================================
# ETAPPE C: DETAILSEITEN MIT BREADCRUMB + TABS
# ============================================================

def _liegenschaft_kopf(lg, gesamt, vermietet, soll_monat, wartungsfristen,
                       tickets, rendite):
    """Der Aktenkopf der Liegenschaft — gerechnete Zustaende, keine Felder.

    Umsetzung von G9 (KONZEPT-UI.md 16.3) fuer den dritten Aktentyp. Die
    Kennzahlen beantworten die vier Fragen, die man vor einer Liegenschaft
    zuerst stellt: Wie viel ist vermietet, was faellt monatlich an, was wirft
    sie ab, und was steht als Naechstes an.

    **Was hier bewusst NICHT steht.** Der Prototyp zeigt bei Liegenschaften
    auch einen Chip «Sanierung geplant» und eine Kennzahl «Ruecklagen». Fuer
    beides gibt es kein Feld: `portfolio.Liegenschaft` fuehrt weder einen
    Sanierungsstatus noch einen Erneuerungsfonds. Ein aus `Unterhalt`
    geschaetzter Wert waere geraten, nicht gewusst.
    """
    heute = timezone.localdate()
    leerstand = gesamt - vermietet

    chips = []
    if gesamt:
        quote = round(vermietet * 100 / gesamt)
        if leerstand:
            chips.append({'text': gettext('%(leer)s von %(gesamt)s leer') % {'leer': leerstand, 'gesamt': gesamt},
                          'ton': 'fw-warn'})
        else:
            chips.append({'text': gettext('voll vermietet (%(q)s %%)') % {'q': quote}, 'ton': 'fw-good'})
    ueberfaellig = [f for f in wartungsfristen if f['ueberfaellig']]
    if ueberfaellig:
        chips.append({'text': ngettext('%(n)s Frist überfällig', '%(n)s Fristen überfällig',
                                       len(ueberfaellig)) % {'n': len(ueberfaellig)},
                      'ton': 'fw-crit'})
    if tickets:
        chips.append({'text': ngettext('%(n)s offener Schaden', '%(n)s offene Schadensfälle',
                                       len(tickets)) % {'n': len(tickets)}, 'ton': 'fw-warn'})
    if lg.hkvo_aktiv:
        chips.append({'text': gettext('HKVO verbrauchsabhängig'), 'ton': 'fw-info'})

    # Hinweise. Regel aus 16.3: Jeder Hinweis fuehrt zu einer Handlung —
    # sonst ist er eine Beschwerde. Deshalb traegt jeder ein Ziel.
    hinweise = []
    if rendite.get('bruttorendite') is None:
        hinweise.append({
            'ton': 'info', 'symbol': 'bericht',
            'titel': gettext('Rendite nicht berechenbar'),
            'text': gettext('Ohne Verkehrswert (ersatzweise Anlagekosten) fehlt der Nenner. '
                            'Der Versicherungswert taugt dafür nicht — er bemisst den '
                            'Wiederaufbau, nicht den Marktwert.'),
            'url': f'/neu/liegenschaften/{lg.id}/bearbeiten/', 'knopf': gettext('Wert erfassen')})
    if ueberfaellig:
        aelteste = min(ueberfaellig, key=lambda f: f['wf'].naechste_faelligkeit)
        hinweise.append({
            'ton': 'crit', 'symbol': 'warnung',
            'titel': gettext('Wartungsfrist überfällig'),
            'text': gettext('«%(name)s» war am %(datum)s fällig (%(tage)s Tage).') % {
                'name': aelteste['wf'].bezeichnung,
                'datum': aelteste['wf'].naechste_faelligkeit.strftime('%d.%m.%Y'),
                'tage': abs(aelteste['tage'])},
            'url': '?tab=faelle', 'knopf': gettext('Zu den Fristen')})
    if not lg.hauswart_name and not lg.sanitaer_name and not lg.elektriker_name:
        hinweise.append({
            'ton': 'warn', 'symbol': 'arbeit',
            'titel': gettext('Keine Notfallkontakte'),
            'text': gettext('Ohne Hauswart, Sanitär oder Elektriker steht bei einem '
                            'Wasserschaden ausserhalb der Bürozeit niemand bereit.'),
            'url': f'/neu/liegenschaften/{lg.id}/bearbeiten/', 'knopf': gettext('Kontakte erfassen')})

    # Naechste Frist als vierte Kennzahl. `wartungsfristen` ist bereits nach
    # Faelligkeit sortiert; die erste ist die naechste.
    naechste = wartungsfristen[0] if wartungsfristen else None

    return {
        'lg_nummer': f'L-{lg.id:06d}',
        'lg_chips': chips,
        'lg_hinweise': hinweise,
        'lg_naechste_frist': naechste,
        'lg_quote': round(vermietet * 100 / gesamt) if gesamt else None,
        'lg_heute': heute,
    }


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

    from core.services.archiv import ausblenden
    tickets = (ausblenden(SchadenMeldung.objects.filter(liegenschaft=lg))
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
    for d in (ausblenden(RentalsDokument.objects.neueste())
              .filter(Q(liegenschaft=lg) | Q(einheit__liegenschaft=lg))
              .filter(vertrag__isnull=True)
              .select_related('einheit').distinct().order_by('-datum')):
        eid = d.einheit_id
        buckets[eid].append({'titel': d.bezeichnung or d.titel, 'kategorie': d.kategorie,
                             'datum': d.ablage_zeit, 'url': d.datei.url if d.datei else None,
                             'id': d.id, 'del_url': f'/neu/dokument/{d.id}/loeschen/'})
    for d in (ausblenden(PortfolioDokument.objects.all())
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
    # Gemeinschaftsräume des Hauses (Waschküche, Trockenraum, Veloraum …): Raumbuch der Liegenschaft.
    from portfolio.models import Ausstattung as _Ausstattung
    from core.services.raumkatalog import GEMEINSCHAFT_TYPEN as _GEM_TYPEN
    gemeinschaft_raeume = _raumbuch_zeilen(list(_Ausstattung.objects.filter(liegenschaft=lg)
                                                .prefetch_related('schaeden__handwerker_auftraege')))

    # Etappe 4b.3: Reiter aus dem Aktenregister statt aus dieser View.
    # `technik` faellt auf `stammdaten`, `fristen` und `schaeden` fallen beide
    # auf `faelle` — ihre Zaehler addiert `aus_alt`, statt den zweiten still
    # zu ueberschreiben.
    from django.contrib.contenttypes.models import ContentType

    from core.models import AktivitaetsLog
    from core.tenancy import aktuelle_organisation as _akt_org
    from faelle.akten import aus_alt as _reiter_aus_alt
    from faelle.models import Fall

    lg_faelle = list(
        Fall.objects.filter(akte_typ=ContentType.objects.get_for_model(Liegenschaft),
                            akte_id=lg.id)
        .select_related('fallart', 'zustaendig').order_by('-eroeffnet_am'))

    # Chronik. `AktivitaetsLog` kennt nur die Ziel-Typen 'person' und
    # 'vertrag' — fuer eine Liegenschaft gibt es keinen. Der einzige
    # BELASTBARE Bezug fuehrt ueber ihre Vertraege; ein Abgleich ueber
    # `objekt__icontains=strasse` waere geraten und traefe jede Liegenschaft
    # mit aehnlichem Strassennamen mit. Darum nur die Vertraege.
    _vids = list(Mietvertrag.objects.filter(einheit__liegenschaft=lg)
                 .values_list('id', flat=True))
    verlauf = list(AktivitaetsLog.objects
                   .filter(ziel_typ='vertrag', ziel_id__in=_vids)
                   .select_related('benutzer')[:50]) if _vids else []

    tab_liste = _reiter_aus_alt('liegenschaft', [
        ('objekte', 'Objekte', len(einheiten_rows)),
        ('finanzen', 'Finanzen', None),
        ('technik', 'Technik', technik_count or None),
        ('unterhalt', 'Unterhalt', unterhalt.count() or None),
        ('fristen', 'Fristen', len(wartungsfristen) or None),
        ('schaeden', 'Schäden', tickets.count() or None),
        ('dokumente', 'Dokumente', dok_total or None),
    ], organisation=getattr(request, 'organisation', None) or _akt_org())
    from core.services.rendite import liegenschaft_rendite
    rendite = liegenschaft_rendite(lg)

    # konzept-v8 (#lg-…): Kennzahl «Ausstände > 30 Tage» und die Rueckstaende
    # unter «Was auffällt». Nur lesend — zwei Abfragen fuer die Posten, eine
    # fuer die Vertraege dazu (auch beendete: ein Rueckstand ueberlebt den
    # Auszug).
    from faelle.liegenschaften import AUSSTAND_TAGE, ausstaende as _ausstaende
    _aus = _ausstaende([lg.id], heute).get(lg.id) or {'betrag': Decimal('0.00'), 'vertraege': {}}
    _rv = {v.id: v for v in Mietvertrag.objects.filter(id__in=list(_aus['vertraege']))
           .select_related('mieter', 'einheit')} if _aus['vertraege'] else {}
    lg_rueckstaende = sorted(
        ({'v': _rv[vid], 'betrag': b} for vid, b in _aus['vertraege'].items() if vid in _rv),
        key=lambda x: -x['betrag'])
    lg_faelle_offen = [f for f in lg_faelle if f.status not in ('abgeschlossen', 'abgebrochen')]
    _kopf = _liegenschaft_kopf(lg, len(einheiten_rows), vermietet, soll_monat,
                               wartungsfristen, list(tickets), rendite)
    _befunde = _lg_befunde(lg)
    _lg_befunde_liste = _befunde['lg_befunde']
    return render(request, 'fw/liegenschaft_detail.html', {
        'lg_ausstand': _aus['betrag'],
        'lg_ausstand_parteien': len(_aus['vertraege']),
        'lg_ausstand_tage': AUSSTAND_TAGE,
        'lg_rueckstaende': lg_rueckstaende,
        'lg_rueckstand_ids': [x['v'].id for x in lg_rueckstaende],
        'lg_faelle_offen': lg_faelle_offen,
        'lg_auffaellig_anzahl': (len(lg_faelle_offen) + len(lg_rueckstaende)
                                 + len(_lg_befunde_liste) + len(_kopf['lg_hinweise'])),
        **_kopf,
        **basis, 'nav': 'liegenschaften', 'lg': lg,
        'lg_faelle': lg_faelle,
        'verlauf': verlauf,
        'einheiten_rows': einheiten_rows,
        'total_einheiten': len(einheiten_rows),
        'vermietet': vermietet,
        'leerstand': len(einheiten_rows) - vermietet,
        'soll_monat': soll_monat,
        # Was die Akte von selbst bemerkt — DIESELBE Quelle wie die Liste.
        # Zwei getrennte Rechnungen waeren die klassische Stelle, an der Liste
        # und Akte auseinanderlaufen; dann weiss niemand, welcher Seite zu
        # trauen ist (dasselbe Argument wie beim Anzeigestatus, Etappe 4b.14).
        **_befunde,
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
        'gemeinschaft_raeume': gemeinschaft_raeume,
        'gem_basis': f'/neu/liegenschaften/{lg.id}',
        'gemeinschaft_typen': _GEM_TYPEN,
        'zustand_choices': _Ausstattung.ZUSTAND,
        'lg_zaehler': lg_zaehler,
        'geraet_kategorien': GERAET_KATEGORIEN,
        'zaehler_typen': ZAEHLER_TYPEN,
        'tab_liste': tab_liste,
        # Modul 2: Abschnitt «Schliessanlage» (core/views/fw/schluessel.py)
        **_schliessanlage_kontext(request, lg, einheiten),
    })


# Kuratierte Standard-Ausstattungsmerkmale (CH) für die schnelle Häkchen-Liste


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_budget_speichern(request, pk):
    """Unterhaltsbudget einer Liegenschaft fuer ein Jahr erfassen oder aendern.

    Ein bestehendes Budget desselben Jahres wird UEBERSCHRIEBEN, nicht
    verdoppelt: Die Datenbank laesst je Liegenschaft und Jahr nur eines zu,
    und ein Fehler statt einer Korrektur waere hier die falsche Antwort — wer
    das Budget eintippt, will es setzen, nicht anlegen.

    `pk` ist die LIEGENSCHAFT, nicht das Budget. Bei `fw_budget_loeschen` ist
    es das Budget. Das ist unschoen und steht deshalb hier: Die Testregistry
    (`core/tests/_isolation.py::NAME_MUSTER`) muss beide unterscheiden koennen.
    """
    from decimal import Decimal, InvalidOperation

    from django.contrib import messages
    from django.shortcuts import redirect

    from core.auth import log_aktion
    from portfolio.models import Liegenschaftsbudget

    lg = get_object_or_404(Liegenschaft, id=pk)
    ziel = f'/neu/liegenschaften/{lg.id}/?tab=finanzen'
    if request.method != 'POST':
        return redirect(ziel)

    try:
        jahr = int(request.POST.get('jahr') or 0)
    except ValueError:
        jahr = 0
    if not 2000 <= jahr <= 2100:
        messages.error(request, gettext('Bitte ein Jahr zwischen 2000 und 2100 angeben.'))
        return redirect(ziel)

    # Schweizer Schreibweise: «31'000.00» ist die Form, die auf derselben
    # Seite ausgegeben wird. Wer sie zurueckkopiert, darf nicht scheitern.
    roh = betrag_normalisieren(request.POST.get('unterhalt'))
    try:
        betrag = Decimal(roh)
    except (InvalidOperation, ValueError):
        messages.error(request, gettext('Der Betrag ist keine gültige Zahl.'))
        return redirect(ziel)
    if betrag < 0:
        messages.error(request, gettext('Ein negatives Budget ergibt keinen Sinn.'))
        return redirect(ziel)

    Liegenschaftsbudget.objects.update_or_create(
        liegenschaft=lg, jahr=jahr,
        defaults={'unterhalt': betrag,
                  'bemerkung': (request.POST.get('bemerkung') or '').strip()})
    log_aktion(request, 'Unterhaltsbudget gesetzt', str(lg), f'{jahr}: CHF {betrag}')
    messages.success(request, gettext('Unterhaltsbudget %(jahr)s: CHF %(betrag)s')
                     % {'jahr': jahr, 'betrag': format(betrag, ',.2f').replace(',', "'")})
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_budget_loeschen(request, pk):
    """Budget entfernen — damit der Unterhaltsbefund wieder schweigt.

    Ohne Loeschen liesse sich ein versehentlich erfasstes Budget nur noch
    ueberschreiben, nie zuruecknehmen. Der Befund meldet aber nur, WEIL ein
    Budget da ist; wer keines fuehren will, muss es auch wieder loswerden.
    """
    from django.contrib import messages
    from django.shortcuts import redirect

    from core.auth import log_aktion
    from portfolio.models import Liegenschaftsbudget

    b = get_object_or_404(Liegenschaftsbudget, id=pk)
    lg = b.liegenschaft
    if request.method == 'POST':
        jahr = b.jahr
        b.delete()
        log_aktion(request, 'Unterhaltsbudget entfernt', str(lg), str(jahr))
        messages.success(request, gettext('Budget %(jahr)s entfernt.') % {'jahr': jahr})
    return redirect(f'/neu/liegenschaften/{lg.id}/?tab=finanzen')


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
        messages.error(request, gettext('Bezeichnung und Fälligkeitsdatum sind erforderlich.'))
        return redirect(f'/neu/liegenschaften/{lg.id}/')
    try:
        faellig_d = date.fromisoformat(faellig)
    except ValueError:
        messages.error(request, gettext('Ungültiges Datum.'))
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
    messages.success(request, '✅ ' + gettext('Frist „%(bez)s" gespeichert.') % {'bez': bez})
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
        messages.success(request, '🗑️ ' + gettext('Frist gelöscht.'))
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
        messages.error(request, gettext('Bezeichnung und Fälligkeitsdatum sind erforderlich.'))
        return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')
    try:
        wf.naechste_faelligkeit = date.fromisoformat(faellig)
    except ValueError:
        messages.error(request, gettext('Ungültiges Datum.'))
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
    messages.success(request, '✅ ' + gettext('Frist „%(bez)s" aktualisiert.') % {'bez': bez})
    return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')


def _lg_befunde(lg):
    """Befunde und Budgetstand einer Liegenschaft fuer die Akte.

    Ruft dieselbe Funktion auf wie die Liegenschaftsliste (`faelle.
    liegenschaften.zeilen`). Der Aufwand dafuer ist eine Handvoll Abfragen fuer
    EINE Liegenschaft — das ist der Preis dafuer, dass Liste und Akte nie
    Verschiedenes sagen koennen.
    """
    from decimal import Decimal

    from django.utils import timezone

    from faelle.liegenschaften import zeilen

    heute = timezone.localdate()
    zeile = zeilen([lg], heute)[0]

    budget = ist = None
    from finance.models import KreditorenRechnung
    from portfolio.models import Liegenschaftsbudget, Unterhalt
    b = Liegenschaftsbudget.objects.filter(liegenschaft=lg, jahr=heute.year).first()
    if b:
        budget = b.unterhalt
        ist = Decimal('0')
        for kosten in Unterhalt.objects.filter(
                liegenschaft=lg, datum__year=heute.year).values_list('kosten', flat=True):
            ist += kosten or Decimal('0')
        for betrag in KreditorenRechnung.objects.filter(
                liegenschaft=lg, datum__year=heute.year
        ).exclude(status='storniert').values_list('betrag', flat=True):
            ist += betrag or Decimal('0')

    # Die Einstufung gehoert HIERHER, nicht ins Template. Ein Versuch mit
    # `{% if lg_budget_rest < lg_budget|floatformat:0|add:0 %}` rechnet nicht,
    # er sieht nur so aus — Vergleichsoperatoren in Django-Templates arbeiten
    # auf dem, was der letzte Filter zurueckgibt, und das ist hier eine
    # Zeichenkette.
    budget_stufe = ''
    if budget and ist is not None:
        if ist > budget:
            budget_stufe = 'crit'
        elif ist > budget * Decimal('0.8'):
            budget_stufe = 'warn'

    return {
        'lg_budgets': list(Liegenschaftsbudget.objects.filter(liegenschaft=lg)),
        'lg_jahr': heute.year,
        'lg_budget_stufe': budget_stufe,
        'lg_befunde': zeile['chips'],
        'lg_stufe': zeile['stufe'],
        'lg_leer': zeile['leer'],
        'lg_budget': budget,
        'lg_budget_ist': ist,
        'lg_budget_rest': ((budget - ist)
                           if (budget is not None and ist is not None) else None),
    }
