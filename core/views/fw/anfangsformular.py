# core/views/fw/anfangsformular.py
#
# Nachweis zum Anfangsmietzins-Formular (MIET-04, Art. 270 Abs. 2 OR) am Vertrag erfassen.
# Wo es kein Kantonsoriginal gibt, wird das Formular der Behörde ausserhalb der Anwendung verwendet;
# hier hält die Verwaltung fest, dass und wann. Erst damit lässt sich der Entwurf aktivieren
# (`core/services/anfangsformular.py`). Schreibend, also nur für Schreibrollen; die ID eines fremden
# Vertrags ergibt 404 (Mandantenfilter des Managers).

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext

from core.auth import SCHREIB_ROLLEN, log_aktion, rolle_erforderlich
from rentals.models import Mietvertrag


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_anfangsformular_nachweis(request, pk):
    """Speichert oder entfernt den Nachweis (nur POST)."""
    from core.services.anfangsformular import (anfangsformular_lage, nachweis_aus_eingabe,
                                               pendenz_nachweis_erledigen)
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), pk=pk)
    ziel = f'/neu/vertraege/{v.pk}/'
    if request.method != 'POST':
        return redirect(ziel)
    felder = ['anfangsformular_nachweis', 'anfangsformular_datum', 'anfangsformular_notiz']
    if request.POST.get('aktion') == 'entfernen':
        v.anfangsformular_nachweis, v.anfangsformular_datum, v.anfangsformular_notiz = '', None, ''
        v.save(update_fields=felder)
        log_aktion(request, 'Anfangsmietzins-Formular: Nachweis entfernt', str(v), '', ziel=v)
        messages.success(request, gettext('Nachweis entfernt.'))
        return redirect(ziel)
    lage = anfangsformular_lage(v.einheit, v)
    if not lage['erforderlich'] or lage['original']:
        messages.error(request, '❌ ' + gettext('Für dieses Objekt ist kein Nachweis nötig.'))
        return redirect(ziel)
    art, datum, notiz, fehler = nachweis_aus_eingabe(
        lage, request.POST.get('anfangsformular_nachweis'), request.POST.get('anfangsformular_datum'),
        request.POST.get('anfangsformular_notiz'))
    if not art and not fehler:
        fehler = {'anfangsformular_nachweis': gettext('Bitte wählen, was zutrifft.')}
    if fehler:
        for text in fehler.values():
            messages.error(request, '❌ ' + text)
        return redirect(ziel)
    v.anfangsformular_nachweis, v.anfangsformular_datum, v.anfangsformular_notiz = art, datum, notiz
    v.save(update_fields=felder)
    pendenz_nachweis_erledigen(v)
    log_aktion(request, 'Anfangsmietzins-Formular: Nachweis erfasst', str(v),
               f'{v.get_anfangsformular_nachweis_display()}'
               + (f', {datum:%d.%m.%Y}' if datum else '') + (f' — {notiz}' if notiz else ''), ziel=v)
    messages.success(request, '✅ ' + gettext('Nachweis zum Anfangsmietzins-Formular festgehalten.'))
    return redirect(ziel)
