# core/views/fw/sicherheit.py
"""Einstellungen → Sicherheit: Zustand der Verschlüsselung und die Handgriffe, die früher ein Terminal brauchten.

NUR FÜR DEN BETREIBER (Superuser), nicht für den Inhaber einer Verwaltung: Der Schlüssel gilt für die ganze Installation,
die Zähler und das Umschreiben betreffen die Werte ALLER Verwaltungen. Eine Verwaltung darf weder deren Anzahl sehen
noch deren Werte umstellen. Das Wichtigste läuft ohnehin von selbst — der Schlüssel entsteht beim ersten Bedarf, der
Altbestand wird nach jedem Deploy verschlüsselt (`core/services/geheimnis_pflege.py`); die Seite zeigt es und bietet
Knöpfe für den Rest.

Protokolliert wird jeder Handgriff im Aktivitätslog — nie ein Schlüssel, nie ein Wert.
"""
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext

from core.auth import BETREIBER_ROLLEN, log_aktion, rolle_erforderlich
from core.services import geheimnis, geheimnis_pflege


ZIEL = '/betreiber/sicherheit/'


@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_sicherheit(request):
    if request.method == 'POST':
        return _aktion(request)
    try:
        z = geheimnis_pflege.zustand()
        fehler = ''
    except geheimnis.SchluesselFehlt as exc:
        z, fehler = geheimnis_pflege.Zustand(), str(exc)
    return render(request, 'fw/sicherheit.html', {
        'aktiv': 'sicherheit', 'z': z, 'fehler': fehler,
        'quelle_text': {
            'einstellung': gettext('Einstellung der Anwendung'),
            'umgebung': gettext('Umgebungsvariable (.env)'),
            'datei': gettext('Schlüsseldatei (GEHEIMNIS_SCHLUESSEL_DATEI)'),
            'automatisch': gettext('von der Anwendung selbst angelegt'),
        }.get(z.quelle, gettext('keiner')),
    })


def _aktion(request):
    aktion = request.POST.get('aktion', '')
    try:
        if aktion == 'nachholen':
            n = geheimnis_pflege.nachholen()
            log_aktion(request, 'Verschlüsselung nachgeholt', details=f'{n} Werte', kategorie='sicherheit')
            messages.success(request, gettext('%(n)s Werte verschlüsselt.') % {'n': n})
        elif aktion == 'umstellen':
            n, unlesbar = geheimnis_pflege.umstellen()
            log_aktion(request, 'Werte auf aktuellen Schlüssel umgestellt', details=f'{n} Werte', kategorie='sicherheit')
            messages.success(request, gettext('%(n)s Werte auf den aktuellen Schlüssel umgestellt.') % {'n': n})
            if unlesbar:
                messages.error(request, gettext('%(n)s Werte lassen sich mit keinem gesetzten Schlüssel lesen.') % {'n': len(unlesbar)})
        elif aktion == 'erneuern':
            n, unlesbar = geheimnis_pflege.erneuern()
            log_aktion(request, 'Schlüssel erneuert', details=f'{n} Werte umgestellt', kategorie='sicherheit')
            if unlesbar:
                messages.error(request, gettext(
                    'Der neue Schlüssel ist gesetzt, aber %(n)s Werte lassen sich nicht lesen. Der alte Schlüssel bleibt '
                    'deshalb in der Datei erhalten.') % {'n': len(unlesbar)})
            else:
                messages.success(request, gettext('Neuer Schlüssel gesetzt, %(n)s Werte umgestellt. Der alte Schlüssel ist entfernt.') % {'n': n})
        elif aktion == 'kopie':
            return _kopie(request)
        else:
            messages.error(request, gettext('Unbekannte Aktion.'))
    except geheimnis_pflege.ErneuernNichtMoeglich:
        messages.error(request, gettext('Der Schlüssel liegt nicht in der selbst angelegten Datei und lässt sich hier nicht erneuern.'))
    except geheimnis.SchluesselFehlt as exc:
        messages.error(request, str(exc))
    return redirect(ZIEL)


def _kopie(request):
    """Die Schlüssel als Textdatei zum Ablegen im Passwortmanager. Protokolliert, nie im Cache."""
    roh = geheimnis._roh_schluessel()
    if not roh:
        messages.error(request, gettext('Es ist kein Schlüssel vorhanden.'))
        return redirect(ZIEL)
    log_aktion(request, 'Schlüsselkopie heruntergeladen', kategorie='sicherheit')
    antwort = HttpResponse('\n'.join(geheimnis._schluesselliste()) + '\n', content_type='text/plain; charset=utf-8')
    antwort['Content-Disposition'] = 'attachment; filename="immoswiss-geheimnis-schluessel.txt"'
    antwort['Cache-Control'] = 'no-store, private'
    return antwort
