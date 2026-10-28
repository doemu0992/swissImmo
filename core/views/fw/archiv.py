# core/views/fw/archiv.py
#
# Archiv und Mandatsende (Etappe 2): archivieren, wiederherstellen, nach Ablauf der
# Aufbewahrungsfrist endgültig löschen. Die Regeln stehen in `core/services/archiv.py`.
#
# Isolation: `get_object_or_404(Modell, pk=…)` läuft über den Tenant-Manager; eine
# fremde ID ist darum nicht «verboten», sondern nicht da (404).
from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from core.auth import SCHREIB_ROLLEN, VERWALTUNGS_ROLLEN, hat_rolle, log_aktion, rolle_erforderlich
from core.services import archiv
from core.services.loeschschutz import LoeschSperre, sperrmeldung

from ._basis import _global_filter

ZIEL = '/neu/archiv/'


#: Diese Typen darf auch die Sachbearbeitung archivieren (wie vorher das Löschen);
#: Liegenschaft, Objekt, Person, Vertrag und Mandat bleiben bei Inhaber/Verwalter.
SCHREIB_TYPEN = ('dokument', 'ablage', 'schaden', 'stwegdokument')


def _objekt(request, kuerzel, pk):
    modell = archiv.modell_von_kuerzel(kuerzel)
    if modell is None:
        raise Http404
    if kuerzel not in SCHREIB_TYPEN and not hat_rolle(request.user, VERWALTUNGS_ROLLEN):
        raise PermissionDenied('Archivieren braucht die Rolle Inhaber oder Verwalter.')
    return get_object_or_404(modell, pk=pk)


def _zurueck(request):
    ziel = request.POST.get('weiter') or ''
    return redirect(ziel if ziel.startswith('/neu/') else ZIEL)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_archiv(request):
    """Alles Archivierte der Verwaltung, nach Typ, mit Frist und Wiederherstellen."""
    from core.models import Archiveintrag
    heute = timezone.localdate()
    gruppen = {}
    for e in Archiveintrag.objects.select_related('archiviert_von'):
        if e.typ not in archiv.TYPEN:
            continue
        kuerzel, name = archiv.TYPEN[e.typ]
        gruppen.setdefault(e.typ, {'name': name, 'eintraege': []})['eintraege'].append({
            'e': e, 'kuerzel': kuerzel, 'loeschbar': e.aufbewahren_bis < heute})
    return render(request, 'fw/archiv.html', {
        **_global_filter(request), 'nav': 'archiv',
        'gruppen': list(gruppen.values()), 'anzahl': sum(len(g['eintraege']) for g in gruppen.values()),
        'jahre': archiv.AUFBEWAHRUNG_JAHRE})


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_archivieren(request, kuerzel, pk):
    obj = _objekt(request, kuerzel, pk)
    # Mandatsende ohne Angabe: heute.
    mandatsende = timezone.localdate() if kuerzel == 'mandat' else None
    if request.POST.get('mandatsende'):
        try:
            mandatsende = date.fromisoformat(request.POST['mandatsende'])
        except ValueError:
            messages.error(request, '❌ ' + gettext('Ungültiges Datum für das Mandatsende.'))
            return _zurueck(request)
    try:
        archiv.archivieren(obj, user=request.user, grund=(request.POST.get('grund') or '').strip(),
                           mandatsende=mandatsende)
    except archiv.ArchivFehler as fehler:
        messages.error(request, '❌ ' + str(fehler))
        return _zurueck(request)
    log_aktion(request, 'Archiviert', archiv.bezeichnung(obj), request.POST.get('grund', ''))
    messages.success(request, '📦 ' + gettext('«%(name)s» ist archiviert und wird bis zum %(bis)s aufbewahrt.')
                     % {'name': archiv.bezeichnung(obj), 'bis': archiv.aufbewahren_bis().strftime('%d.%m.%Y')})
    return redirect(ZIEL)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_wiederherstellen(request, kuerzel, pk):
    obj = _objekt(request, kuerzel, pk)
    try:
        archiv.wiederherstellen(obj)
    except archiv.ArchivFehler as fehler:
        messages.error(request, '❌ ' + str(fehler))
        return redirect(ZIEL)
    log_aktion(request, 'Aus dem Archiv wiederhergestellt', archiv.bezeichnung(obj), '')
    messages.success(request, '♻️ ' + gettext('«%(name)s» ist wiederhergestellt.') % {'name': archiv.bezeichnung(obj)})
    return redirect(ZIEL)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_archiv_endgueltig_loeschen(request, kuerzel, pk):
    """Erst nach Ablauf der Aufbewahrungsfrist, und nur, wenn nichts mehr daran hängt."""
    obj = _objekt(request, kuerzel, pk)
    name = archiv.bezeichnung(obj)
    try:
        archiv.endgueltig_loeschen(obj)
    except archiv.ArchivFehler as fehler:
        messages.error(request, '❌ ' + str(fehler))
        return redirect(ZIEL)
    except LoeschSperre as sperre:
        messages.error(request, '❌ ' + sperrmeldung(obj, sperre.hindernisse, name))
        return redirect(ZIEL)
    log_aktion(request, 'Nach Ablauf der Aufbewahrungsfrist gelöscht', name, '')
    messages.success(request, '🗑️ ' + gettext('«%(name)s» ist endgültig gelöscht.') % {'name': name})
    return redirect(ZIEL)
