# core/views/fw/verteilschluessel.py
#
# Pflege der Verteilschlüssel einer Liegenschaft (Phase-2-Folgearbeit zum Audit):
# Standard-Schlüssel je Kostenart (Zimmer, Wertquote, Prozent je Einheit) und das
# Prozentraster. Wirksam in der Nebenkostenabrechnung nur, wenn
# `Liegenschaft.verteilschluessel_aktiv` gesetzt ist (core/utils/billing.py).
#
# Fehler erscheinen am Feld (HTTP 400, Eingabe bleibt) — wie bei den Formularen aus
# `phase2_formulare.py`. Die Vorlage schreibt die Eingabefelder aus (`name="…"`).

from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext

from core.auth import SCHREIB_ROLLEN, TEAM_ROLLEN, hat_rolle, log_aktion, rolle_erforderlich
from portfolio.models import Liegenschaft, LiegenschaftVerteilschluessel, Verteilschluessel

from ._basis import _global_filter

#: Auswahl im Formular: nur die Arten, die die Abrechnung über diese Tabelle anwendet
#: (`core.utils.billing._STD_TYPEN`) — Fläche, Volumen, Einheit und Personen wählt man am Beleg.
TYPEN = [(k, v) for k, v in Verteilschluessel.TYP_CHOICES if k in ('zimmer', 'anteil', 'prozent')]
#: Heizkosten laufen über HKVO/Heizgradtage und nehmen an der Tabelle nicht teil.
KOSTENARTEN = [(k, v) for k, v in Verteilschluessel.KOSTENART_CHOICES if k != 'heizung']


def _datum(roh):
    try:
        return date.fromisoformat((roh or '').strip())
    except ValueError:
        return None


def _neu_pruefen(daten, lg):
    """Prüft das Formular «Schlüssel hinzufügen». Gibt (Werte, Fehler je Feld) zurück."""
    fehler = {}
    ka, typ = daten.get('kostenart', ''), daten.get('typ', '')
    ab, bis = _datum(daten.get('gueltig_ab')), _datum(daten.get('gueltig_bis'))
    if ka not in dict(KOSTENARTEN):
        fehler['kostenart'] = gettext('Bitte eine Kostenart wählen (Heizkosten laufen über die Heizkostenabrechnung).')
    if typ not in dict(TYPEN):
        fehler['typ'] = gettext('Bitte eine Verteilung wählen.')
    if ab is None:
        fehler['gueltig_ab'] = gettext('Bitte ein gültiges Datum angeben.')
    if (daten.get('gueltig_bis') or '').strip() and bis is None:
        fehler['gueltig_bis'] = gettext('Bitte ein gültiges Datum angeben.')
    elif ab and bis and bis < ab:
        fehler['gueltig_bis'] = gettext('«Gültig bis» liegt vor «Gültig ab».')
    if not fehler:
        # Zwei Schlüssel derselben Kostenart dürfen sich zeitlich nicht überlappen: sonst
        # hinge das Ergebnis der Abrechnung davon ab, welcher «zuletzt» gespeichert wurde.
        # Ein offener Vorgänger (ohne «gültig bis»), der früher beginnt, zählt nicht als Konflikt:
        # er wird beim Speichern am Vortag beendet (`_vorgaenger_beenden`).
        for s in lg.standard_schluessel.filter(kostenart=ka):
            if s.gueltig_bis is None and s.gueltig_ab < ab:
                continue
            s_bis = s.gueltig_bis or date.max
            if ab <= s_bis and (bis or date.max) >= s.gueltig_ab:
                fehler['gueltig_ab'] = gettext('Für diese Kostenart gibt es im selben Zeitraum schon einen Schlüssel.')
                break
    return fehler


def _vorgaenger_beenden(lg, kostenart, ab):
    """Beendet offene Schlüssel derselben Kostenart, die vor `ab` beginnen, am Vortag.

    Auch ihre Prozentzeilen (`Verteilschluessel`) bekommen das Enddatum: Sonst würden sie für
    einen späteren Schlüssel gleicher Kostenart weitergelten und die Abrechnung mit veralteten
    Anteilen rechnen.
    """
    from datetime import timedelta
    ende = ab - timedelta(days=1)
    beendet = []
    for s in lg.standard_schluessel.filter(kostenart=kostenart, gueltig_bis__isnull=True, gueltig_ab__lt=ab):
        s.gueltig_bis = ende
        s.save(update_fields=['gueltig_bis'])
        Verteilschluessel.objects.filter(einheit__liegenschaft=lg, kostenart=kostenart, typ='prozent',
                                         gueltig_ab=s.gueltig_ab, gueltig_bis__isnull=True).update(gueltig_bis=ende)
        beendet.append(s)
    return beendet


def _raster_pruefen(daten, einheiten):
    """Prozentraster: je Einheit 0–100, Summe 100. Gibt (Werte, Fehler je Einheit, Summenfehler) zurück."""
    werte, fehler, summe = {}, {}, Decimal('0')
    for e in einheiten:
        roh = (daten.get(f'pct_{e.id}') or '').strip().replace(',', '.')
        if roh == '':
            werte[e.id] = Decimal('0')
            continue
        try:
            w = Decimal(roh)
        except InvalidOperation:
            fehler[e.id] = gettext('Bitte eine Zahl angeben.')
            continue
        if w < 0 or w > 100:
            fehler[e.id] = gettext('Der Anteil liegt zwischen 0 und 100.')
            continue
        werte[e.id] = w
        summe += w
    summenfehler = None
    if not fehler and abs(summe - Decimal('100')) > Decimal('0.01'):
        summenfehler = gettext('Die Anteile ergeben %(summe)s statt 100.') % {'summe': summe}
    return werte, fehler, summenfehler


def _seite(request, lg, *, status=200, neu=None, neu_fehler=None, raster_id=None, raster=None,
           raster_fehler=None, summenfehler=None):
    einheiten = list(lg.einheiten.order_by('bezeichnung'))
    standards = list(lg.standard_schluessel.order_by('kostenart', '-gueltig_ab'))
    namen_ka, namen_typ = dict(Verteilschluessel.KOSTENART_CHOICES), dict(Verteilschluessel.TYP_CHOICES)
    for s in standards:
        s.kostenart_name, s.typ_name = namen_ka.get(s.kostenart, s.kostenart), namen_typ.get(s.typ, s.typ)
        if s.typ == 'prozent':
            vorhanden = {z.einheit_id: z.wert for z in Verteilschluessel.objects.filter(
                einheit__liegenschaft=lg, kostenart=s.kostenart, typ='prozent', gueltig_ab=s.gueltig_ab)}
            if raster_id == s.id and raster is not None:
                s.raster = [{'e': e, 'wert': raster.get(e.id, ''), 'fehler': (raster_fehler or {}).get(e.id)} for e in einheiten]
            else:
                s.raster = [{'e': e, 'wert': vorhanden.get(e.id, ''), 'fehler': None} for e in einheiten]
            s.summenfehler = summenfehler if raster_id == s.id else None
    ctx = {**_global_filter(request), 'lg': lg, 'standards': standards, 'typen': TYPEN, 'kostenarten': KOSTENARTEN,
           'neu': neu or {'gueltig_ab': date.today().isoformat()}, 'neu_fehler': neu_fehler or {},
           'kann_schreiben': hat_rolle(request.user, SCHREIB_ROLLEN)}
    return render(request, 'fw/verteilschluessel.html', ctx, status=status)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_verteilschluessel(request, pk):
    """Verteilschlüssel der Liegenschaft ansehen und pflegen (pk = Liegenschaft)."""
    lg = get_object_or_404(Liegenschaft, pk=pk)
    if request.method != 'POST':
        return _seite(request, lg)
    if not hat_rolle(request.user, SCHREIB_ROLLEN):
        raise PermissionDenied
    aktion = request.POST.get('aktion')

    if aktion == 'neu':
        fehler = _neu_pruefen(request.POST, lg)
        if fehler:
            return _seite(request, lg, status=400, neu=request.POST.dict(), neu_fehler=fehler)
        ab = _datum(request.POST.get('gueltig_ab'))
        beendet = _vorgaenger_beenden(lg, request.POST['kostenart'], ab)
        s = LiegenschaftVerteilschluessel.objects.create(
            liegenschaft=lg, kostenart=request.POST['kostenart'], typ=request.POST['typ'],
            gueltig_ab=ab, gueltig_bis=_datum(request.POST.get('gueltig_bis')))
        log_aktion(request, 'Verteilschlüssel angelegt', str(lg), f'{s.kostenart}: {s.typ}')
        messages.success(request, gettext('Verteilschlüssel gespeichert.'))
        if beendet:
            messages.info(request, gettext('Der bisherige Schlüssel dieser Kostenart wurde am Vortag beendet.'))
        return redirect(f'/neu/liegenschaften/{lg.id}/verteilschluessel/')

    if aktion == 'loeschen':
        s = get_object_or_404(LiegenschaftVerteilschluessel.objects.filter(liegenschaft=lg), pk=request.POST.get('id') or 0)
        Verteilschluessel.objects.filter(einheit__liegenschaft=lg, kostenart=s.kostenart, typ='prozent',
                                         gueltig_ab=s.gueltig_ab).delete()
        log_aktion(request, 'Verteilschlüssel gelöscht', str(lg), f'{s.kostenart}: {s.typ}')
        s.delete()
        messages.success(request, gettext('Verteilschlüssel gelöscht.'))
        return redirect(f'/neu/liegenschaften/{lg.id}/verteilschluessel/')

    if aktion == 'prozente':
        s = get_object_or_404(LiegenschaftVerteilschluessel.objects.filter(liegenschaft=lg, typ='prozent'),
                              pk=request.POST.get('id') or 0)
        einheiten = list(lg.einheiten.all())
        werte, fehler, summenfehler = _raster_pruefen(request.POST, einheiten)
        if fehler or summenfehler:
            roh = {e.id: request.POST.get(f'pct_{e.id}', '') for e in einheiten}
            return _seite(request, lg, status=400, raster_id=s.id, raster=roh, raster_fehler=fehler, summenfehler=summenfehler)
        for e in einheiten:
            Verteilschluessel.objects.update_or_create(
                einheit=e, kostenart=s.kostenart, typ='prozent', gueltig_ab=s.gueltig_ab,
                defaults={'wert': werte[e.id], 'gueltig_bis': s.gueltig_bis})
        log_aktion(request, 'Prozentverteilung gespeichert', str(lg), s.kostenart)
        messages.success(request, gettext('Prozentanteile gespeichert.'))
        return redirect(f'/neu/liegenschaften/{lg.id}/verteilschluessel/')

    messages.error(request, gettext('Unbekannte Aktion.'))
    return redirect(f'/neu/liegenschaften/{lg.id}/verteilschluessel/')
