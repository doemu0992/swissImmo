"""Brief aus einer Vorlage erstellen: Empfänger wählen, Einschreiben und Frist festlegen, ablegen.

Die Fachlogik steht in ``core/services/brief_aus_vorlage.py``; hier nur Formular, Prüfung der Eingabe und Anzeige."""
import datetime
import logging

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext

from core.auth import SCHREIB_ROLLEN, log_aktion, rolle_erforderlich
from core.tenancy import organisation_der_anfrage

from ._basis import _global_filter

logger = logging.getLogger(__name__)


def _datum(roh):
    try:
        return datetime.date.fromisoformat((roh or '').strip())
    except ValueError:
        return None


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vorlage_brief(request, pk):
    """Formular (GET) und Erstellen (POST) der Briefe zu einer Vorlage."""
    from crm.models import Mieter, Vorlage
    from core.services.brief_aus_vorlage import brief_erzeugen, frist_vorgabe
    vorlage = get_object_or_404(Vorlage, pk=pk)
    org = organisation_der_anfrage(request)
    vorgabe = frist_vorgabe(vorlage)
    fehler, gewaehlt = [], []
    werte = {'einschreiben': vorgabe['einschreiben'], 'frist_art': vorgabe['art'],
             'frist_datum': vorgabe['datum'], 'frist_tage': vorgabe['tage']}
    if request.method == 'POST':
        P = request.POST
        gewaehlt = [int(i) for i in P.getlist('mieter') if i.isdigit()]
        werte['einschreiben'] = 'einschreiben' in P
        werte['frist_art'] = vorlage.frist_art or ''
        werte['frist_datum'] = _datum(P.get('frist_datum')) if werte['frist_art'] == 'datum' else None
        tage = (P.get('frist_tage') or '').strip()
        werte['frist_tage'] = int(tage) if tage.isdigit() else None
        if not gewaehlt:
            fehler.append(gettext('Bitte mindestens einen Empfänger wählen.'))
        elif werte['frist_art'] == 'datum' and werte['frist_datum'] is None:
            fehler.append(gettext('Bitte das Fristdatum angeben.'))
        if not fehler:
            try:
                ergebnis = brief_erzeugen(
                    vorlage, gewaehlt, org, request.user, einschreiben=werte['einschreiben'],
                    frist_art=werte['frist_art'], frist_datum=werte['frist_datum'],
                    frist_tage=werte['frist_tage'])
            except ValidationError as e:
                fehler.extend(e.messages)
            else:
                log_aktion(request, 'Brief aus Vorlage erstellt', f'{vorlage.name}: {len(ergebnis["briefe"])}', '')
                request.session['brief_ergebnis'] = [b['dokument'].pk for b in ergebnis['briefe']]
                return redirect('fw_vorlage_brief_fertig', pk=vorlage.pk)
    from django.db.models import Q
    empfaenger = (Mieter.objects.filter(Q(vertraege__status='aktiv') | Q(vertraege_als_mitmieter__status='aktiv'))
                  .distinct().order_by('nachname', 'vorname'))
    return render(request, 'fw/vorlage_brief.html', {
        **_global_filter(request), 'nav': 'vorlagen', 'vorlage': vorlage, 'werte': werte, 'fehler': fehler,
        'empfaenger': empfaenger[:500], 'gewaehlt': gewaehlt, 'heute': timezone.localdate()})


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vorlage_brief_fertig(request, pk):
    """Ergebnisseite: die abgelegten Briefe und ihre Pendenzen."""
    from crm.models import Vorlage
    from core.models import Pendenz
    from rentals.models import Dokument
    vorlage = get_object_or_404(Vorlage, pk=pk)
    ids = request.session.get('brief_ergebnis') or []
    dokumente = list(Dokument.objects.filter(pk__in=ids).select_related('mieter', 'vertrag'))
    quellen = {f'brief:{d.pk}': d for d in dokumente}
    pendenzen = {p.quelle: p for p in Pendenz.objects.filter(quelle__in=list(quellen))}
    zeilen = [{'dokument': d, 'pendenz': pendenzen.get(f'brief:{d.pk}')} for d in dokumente]
    if not zeilen:
        messages.info(request, gettext('Keine Briefe zum Anzeigen.'))
        return redirect('fw_vorlagen')
    return render(request, 'fw/vorlage_brief_fertig.html', {
        **_global_filter(request), 'nav': 'vorlagen', 'vorlage': vorlage, 'zeilen': zeilen})
