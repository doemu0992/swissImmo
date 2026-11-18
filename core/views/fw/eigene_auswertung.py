"""Eigene Auswertungen und Exportvorlagen (Modul «Erweitertes Reporting»).

Liste und Erfassung der Vorlagen, Ausführen mit Vorschau, CSV-Export. Die Fachlogik (Quellen, Spalten, Zeitraum)
steht in `core/services/eigene_auswertung.py`; hier nur Rechte, Eingabe und Darstellung.

Rechte: lesen und ausführen darf, wer die Daten der Quelle sehen darf (Finanzquellen nur mit Finanzrolle); anlegen,
ändern und löschen dürfen Schreibrollen und die Buchhaltung.
"""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext

from abo.zugang import funktion_erforderlich
from core.auth import (FINANZ_LESE_ROLLEN, FINANZ_SCHREIB_ROLLEN, REVISIONS_ROLLEN, hat_rolle, log_aktion,
                       rolle_erforderlich)
from core.models import Auswertungsvorlage
from core.services import eigene_auswertung as dienst
from core.utils.formularid import eigenes_objekt
from portfolio.models import Liegenschaft

from ._basis import _global_filter
from ._liste import blaettern, csv_antwort

LESE_ROLLEN = FINANZ_LESE_ROLLEN + REVISIONS_ROLLEN
LISTE = '/neu/auswertung/eigene/'


def _darf_finanzen(user):
    return user.is_superuser or hat_rolle(user, FINANZ_LESE_ROLLEN + REVISIONS_ROLLEN)


def _sichtbar(request):
    """Die Vorlagen, deren Quelle diese Person sehen darf."""
    erlaubt = [k for k, _n in dienst.quellen_fuer(_darf_finanzen(request.user))]
    return Auswertungsvorlage.objects.filter(quelle__in=erlaubt).select_related('liegenschaft')


def _formular(request, vorlage=None, werte=None, fehler=None):
    quellen = dienst.quellen_fuer(_darf_finanzen(request.user))
    werte = werte or ({'name': vorlage.name, 'quelle': vorlage.quelle, 'spalten': vorlage.spalten,
                       'zeitraum': vorlage.zeitraum, 'liegenschaft': vorlage.liegenschaft_id} if vorlage else
                      {'name': '', 'quelle': quellen[0][0], 'spalten': [], 'zeitraum': 'jahr', 'liegenschaft': None})
    gewaehlt = set(werte['spalten'])
    gruppen = [{'schluessel': k, 'name': name,
                'spalten': [{'schluessel': s, 'name': n, 'an': k == werte['quelle'] and s in gewaehlt}
                            for s, n, _pfad in dienst.QUELLEN[k]['spalten']]}
               for k, name in quellen]
    return {'vorlage': vorlage, 'werte': werte, 'fehler': fehler or [], 'quellen': quellen, 'gruppen': gruppen,
            'zeitraeume': dienst.ZEITRAEUME, 'liegenschaften': Liegenschaft.objects.order_by('strasse'),
            'darf_schreiben': request.user.is_superuser or hat_rolle(request.user, FINANZ_SCHREIB_ROLLEN)}


@rolle_erforderlich(*LESE_ROLLEN)
@funktion_erforderlich('reporting_erweitert')
def fw_eigene_auswertungen(request):
    """Die gespeicherten Vorlagen der Verwaltung und das Formular für eine neue."""
    vorlagen = list(_sichtbar(request))
    for v in vorlagen:
        v.quelle_name = dienst.QUELLEN[v.quelle]['name']
        v.zeitraum_name = dict(dienst.ZEITRAEUME).get(v.zeitraum, v.zeitraum)
    return render(request, 'fw/eigene_auswertungen.html', {
        **_global_filter(request), 'nav': 'eigene_auswertung', 'vorlagen': vorlagen, **_formular(request)})


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
@funktion_erforderlich('reporting_erweitert')
def fw_eigene_auswertung_speichern(request, pk=None):
    """Vorlage anlegen (ohne `pk`) oder ändern."""
    vorlage = get_object_or_404(_sichtbar(request), pk=pk) if pk else None
    if request.method != 'POST':
        if vorlage is None:
            return redirect(LISTE)
        return render(request, 'fw/eigene_auswertungen.html', {
            **_global_filter(request), 'nav': 'eigene_auswertung', 'vorlagen': [], 'bearbeiten': True,
            **_formular(request, vorlage)})
    erlaubt = dict(dienst.quellen_fuer(_darf_finanzen(request.user)))
    quelle = request.POST.get('quelle') or ''
    name = (request.POST.get('name') or '').strip()
    zeitraum = request.POST.get('zeitraum') or 'alle'
    fehler = []
    if not name:
        fehler.append(gettext('Bitte einen Namen angeben.'))
    elif len(name) > 120:
        fehler.append(gettext('Der Name ist zu lang (höchstens 120 Zeichen).'))
    if quelle not in erlaubt:
        fehler.append(gettext('Diese Datenquelle gibt es nicht.'))
        quelle = next(iter(erlaubt))
    # Ein Feld `spalten`, jeder Wert «quelle:schluessel»: Es zählen nur die Spalten der gewählten Quelle.
    gewaehlt = [w.split(':', 1)[1] for w in request.POST.getlist('spalten') if w.startswith(f'{quelle}:')]
    spalten = [k for k, _n, _p in dienst.spalten_von(quelle, gewaehlt)]
    if not spalten and quelle in erlaubt:
        fehler.append(gettext('Bitte mindestens eine Spalte wählen.'))
    if zeitraum not in dict(dienst.ZEITRAEUME):
        zeitraum = 'alle'
    # Die Liegenschaft wird über den Mandanten-Manager aufgelöst, nie als nackte Nummer übernommen.
    liegenschaft = None
    if (request.POST.get('liegenschaft') or '').strip():
        liegenschaft = eigenes_objekt(Liegenschaft, request.POST.get('liegenschaft'))
        if liegenschaft is None:
            fehler.append(gettext('Diese Liegenschaft gibt es nicht.'))
    if name and not fehler:
        doppelt = Auswertungsvorlage.objects.filter(name=name)
        if vorlage is not None:
            doppelt = doppelt.exclude(pk=vorlage.pk)
        if doppelt.exists():
            fehler.append(gettext('Eine Vorlage mit diesem Namen gibt es schon.'))
    if fehler:
        werte = {'name': name, 'quelle': quelle, 'spalten': spalten, 'zeitraum': zeitraum,
                 'liegenschaft': liegenschaft.pk if liegenschaft else None}
        return render(request, 'fw/eigene_auswertungen.html', {
            **_global_filter(request), 'nav': 'eigene_auswertung', 'bearbeiten': vorlage is not None,
            'vorlagen': [] if vorlage is not None else list(_sichtbar(request)),
            **_formular(request, vorlage, werte, fehler)}, status=400)
    neu = vorlage is None
    if neu:
        vorlage = Auswertungsvorlage(erstellt_von=request.user)
    vorlage.name, vorlage.quelle, vorlage.spalten = name, quelle, spalten
    vorlage.zeitraum, vorlage.liegenschaft = zeitraum, liegenschaft
    vorlage.save()
    log_aktion(request, 'Auswertungsvorlage angelegt' if neu else 'Auswertungsvorlage geändert', name,
               f'{quelle} · {len(spalten)} Spalten')
    messages.success(request, gettext('Vorlage «%(name)s» gespeichert.') % {'name': name})
    return redirect(f'{LISTE}{vorlage.pk}/')


@rolle_erforderlich(*LESE_ROLLEN)
@funktion_erforderlich('reporting_erweitert')
def fw_eigene_auswertung(request, pk):
    """Vorlage ausführen: Vorschau mit Blättern, `?export=csv` liefert alle Zeilen als Datei."""
    vorlage = get_object_or_404(_sichtbar(request), pk=pk)
    kopf, zeilen = dienst.zeilen(vorlage)
    if request.GET.get('export') == 'csv':
        log_aktion(request, 'Eigene Auswertung exportiert', vorlage.name, f'{len(zeilen)} Zeilen')
        dateiname = ''.join(z if z.isalnum() or z in '-_' else '_' for z in vorlage.name)[:60] or 'auswertung'
        return csv_antwort(f'{dateiname}.csv', kopf, zeilen)
    seite, query_ohne_seite = blaettern(request, zeilen)
    return render(request, 'fw/eigene_auswertung.html', {
        **_global_filter(request), 'nav': 'eigene_auswertung', 'vorlage': vorlage, 'kopf': kopf,
        'zeilen': [[dienst.anzeige(w) for w in z] for z in seite], 'seite': seite,
        'query_ohne_seite': query_ohne_seite, 'anzahl': len(zeilen), 'gekappt': len(zeilen) >= dienst.MAX_ZEILEN,
        'max_zeilen': dienst.MAX_ZEILEN, 'quelle_name': dienst.QUELLEN[vorlage.quelle]['name'],
        'zeitraum_name': dict(dienst.ZEITRAEUME).get(vorlage.zeitraum, vorlage.zeitraum),
        'darf_schreiben': request.user.is_superuser or hat_rolle(request.user, FINANZ_SCHREIB_ROLLEN)})


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
@funktion_erforderlich('reporting_erweitert')
def fw_eigene_auswertung_loeschen(request, pk):
    vorlage = get_object_or_404(_sichtbar(request), pk=pk)
    if request.method == 'POST':
        name = vorlage.name
        vorlage.delete()
        log_aktion(request, 'Auswertungsvorlage gelöscht', name, '')
        messages.success(request, gettext('Vorlage «%(name)s» gelöscht.') % {'name': name})
    return redirect(LISTE)
