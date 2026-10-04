"""Dokumenten-Repository: Verwaltung (/neu/stweg/…) und Download.

Ausgeliefert wird nie über /media/, sondern hier: Login, Rolle, Mandant (`TenantManager` → fremde
ID = 404). Der Eigentümer-Download steht in `stweg.portal`."""
from django.utils.translation import gettext
import os

from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.auth import SCHREIB_ROLLEN, TEAM_ROLLEN, rolle_erforderlich
from stweg import dokumente as dok
from stweg.models import StwegDokument
from stweg.views import _gemeinschaft

INLINE = {'.pdf', '.jpg', '.jpeg', '.png', '.webp'}


def datei_antwort(d, feld='datei'):
    """Die Datei eines Dokuments; PDFs und Bilder inline, alles andere als Download, nie «sniffen»."""
    datei = getattr(d, feld)
    try:
        f = datei.open('rb')
    except (FileNotFoundError, ValueError, OSError):
        raise Http404
    name = os.path.basename(datei.name)
    antwort = FileResponse(f)
    antwort['X-Content-Type-Options'] = 'nosniff'
    antwort['Content-Disposition'] = ('inline' if os.path.splitext(name.lower())[1] in INLINE else 'attachment') \
        + f'; filename="{name}"'
    return antwort


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_dokumente(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    return render(request, 'stweg/dokumente.html', {
        'nav': 'stweg', 'lg': lg, 'status': dok.pruefen(lg),
        'dokumente': StwegDokument.objects.filter(liegenschaft=lg),
        'kategorien': StwegDokument.KATEGORIE_CHOICES})


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_dokument_neu(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    datei = request.FILES.get('datei')
    try:
        dok.hochladen(lg, request.POST.get('kategorie'), request.POST.get('titel') or '', datei,
                      gueltig_ab=parse_date(request.POST.get('gueltig_ab') or ''),
                      gueltig_bis=parse_date(request.POST.get('gueltig_bis') or ''),
                      sichtbar=bool(request.POST.get('sichtbar')), user=request.user)
        dok.aufgaben_nachziehen(lg)
        messages.success(request, gettext('Dokument abgelegt.'))
    except dok.DokumentFehler as e:
        messages.error(request, str(e))
    return redirect(f'/neu/stweg/{lg.pk}/dokumente/')


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_dokument_download(request, pk):
    return datei_antwort(get_object_or_404(StwegDokument, pk=pk))


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_dokument_loeschen(request, pk):
    d = get_object_or_404(StwegDokument.objects.select_related('liegenschaft'), pk=pk)
    lg = d.liegenschaft
    d.datei.delete(save=False)
    d.delete()
    dok.aufgaben_nachziehen(lg)
    messages.success(request, gettext('Dokument gelöscht.'))
    return redirect(f'/neu/stweg/{lg.pk}/dokumente/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_dokument_sichtbar(request, pk):
    d = get_object_or_404(StwegDokument.objects.select_related('liegenschaft'), pk=pk)
    d.sichtbar = not d.sichtbar
    d.save(update_fields=['sichtbar'])
    messages.success(request, gettext('Für Eigentümer freigegeben.') if d.sichtbar else gettext('Für Eigentümer nicht mehr sichtbar.'))
    return redirect(f'/neu/stweg/{d.liegenschaft.pk}/dokumente/')
