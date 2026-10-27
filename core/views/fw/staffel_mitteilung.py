# core/views/fw/staffel_mitteilung.py
#
# Staffelmiete: Mitteilung jeder Erhöhung (Art. 269d Abs. 5 OR, Art. 19a VMWG).
# Zwei Aktionen auf der Vertragsakte (Reiter «Mietzins»): Schreiben erstellen und
# als versandt markieren. Die Fachregeln stehen in core/services/staffel_mitteilung.py.
#
# Beide Ansichten schreiben, also nur für Rollen mit Schreibrecht (SCHREIB_ROLLEN,
# wie `fw_staffel_add`). Die Stufe wird über `Staffelstufe.objects` gesucht — der
# Manager filtert auf die Verwaltung des Benutzers, die ID einer fremden Stufe
# ergibt 404 (Skill mandantentrennung).

from datetime import date

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext

from core.auth import SCHREIB_ROLLEN, log_aktion, rolle_erforderlich
from rentals.models import Staffelstufe


def _stufe(pk):
    return get_object_or_404(
        Staffelstufe.objects.select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'), pk=pk)


def _ziel(stufe):
    return f'/neu/vertraege/{stufe.vertrag_id}/?tab=mietzins'


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffel_mitteilung_erstellen(request, pk):
    """Erzeugt das Schreiben zur Erhöhung dieser Stufe und legt es in der Akte ab (nur POST)."""
    from core.services import staffel_mitteilung as sm
    stufe = _stufe(pk)
    if request.method != 'POST':
        return redirect(_ziel(stufe))
    try:
        sm.schreiben_erstellen(stufe, timezone.localdate(), benutzer=request.user)
    except ValueError as fehler:
        messages.error(request, f'❌ {fehler}')
        return redirect(_ziel(stufe))
    log_aktion(request, "Staffelmiete: Mitteilung erstellt", str(stufe.vertrag),
               f"Erhöhung ab {stufe.ab_datum}", ziel=stufe.vertrag)
    messages.success(request, '✅ ' + gettext(
        'Schreiben zur Erhöhung ab %(datum)s erstellt und in der Akte abgelegt (Reiter «Dokumente»).') % {
            'datum': stufe.ab_datum.strftime('%d.%m.%Y')})
    return redirect(_ziel(stufe))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffel_mitteilung_versandt(request, pk):
    """Markiert die Mitteilung dieser Stufe als versandt (nur POST); beendet die Erinnerung."""
    from core.services import staffel_mitteilung as sm
    stufe = _stufe(pk)
    if request.method != 'POST':
        return redirect(_ziel(stufe))
    heute = timezone.localdate()
    try:
        am = date.fromisoformat((request.POST.get('versandt_am') or '').strip()) \
            if request.POST.get('versandt_am') else heute
    except ValueError:
        messages.error(request, '❌ ' + gettext('Bitte ein gültiges Versanddatum angeben.'))
        return redirect(_ziel(stufe))
    try:
        sm.als_versandt_markieren(stufe, am, heute)
    except ValueError as fehler:
        messages.error(request, f'❌ {fehler}')
        return redirect(_ziel(stufe))
    log_aktion(request, "Staffelmiete: Mitteilung versandt", str(stufe.vertrag),
               f"Erhöhung ab {stufe.ab_datum}, versandt {am}", ziel=stufe.vertrag)
    messages.success(request, '✅ ' + gettext('Mitteilung zur Erhöhung ab %(datum)s als versandt markiert.') % {
        'datum': stufe.ab_datum.strftime('%d.%m.%Y')})
    return redirect(_ziel(stufe))
