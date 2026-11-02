# core/views/fw/mahngebuehr.py
#
# Ob der Vertrag Mahn- und Umtriebsgebühren vorsieht (`Mietvertrag.mahngebuehr_vereinbart`).
# Mahngebühren brauchen eine vertragliche Grundlage (oder einen nachgewiesenen Verzugsschaden, Art. 106 OR);
# die Vertragsvorlage von immoswiss enthält die Klausel, Verträge anderer Herkunft nicht unbedingt.
# Schreibend, also nur für Schreibrollen; die ID eines fremden Vertrags ergibt 404 (Mandantenfilter).

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext

from core.auth import SCHREIB_ROLLEN, log_aktion, rolle_erforderlich
from rentals.models import Mietvertrag


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_mahngebuehr(request, pk):
    """Setzt «Mahngebühren im Vertrag vereinbart» (nur POST; Feld `vereinbart` = 1 oder 0)."""
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), pk=pk)
    ziel = f'/neu/vertraege/{v.pk}/'
    if request.method != 'POST':
        return redirect(ziel)
    wert = request.POST.get('vereinbart')
    if wert not in ('0', '1'):
        messages.error(request, '❌ ' + gettext('Bitte wählen, ob Mahngebühren vereinbart sind.'))
        return redirect(ziel)
    neu = wert == '1'
    if neu != v.mahngebuehr_vereinbart:
        v.mahngebuehr_vereinbart = neu
        v.save(update_fields=['mahngebuehr_vereinbart'])
        log_aktion(request, 'Mahngebühren im Vertrag ' + ('vereinbart' if neu else 'nicht vereinbart'), str(v), '', ziel=v)
    if neu:
        messages.success(request, '✅ ' + gettext('Mahngebühren sind im Vertrag vereinbart: Das Mahnwesen verrechnet sie.'))
    else:
        messages.success(request, '✅ ' + gettext(
            'Mahngebühren sind nicht vereinbart: Das Mahnwesen verrechnet für diesen Vertrag keine Gebühr '
            '(Mahnung und Verzugszins bleiben).'))
    return redirect(ziel)
