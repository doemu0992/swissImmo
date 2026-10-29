# core/views/fw/daten.py
"""Einstellungen «Daten»: Import für Wechselkunden und Export (Audit FUNK-09, FUNK-13).

Wer darf was:

* **Import**: nur Inhaber und Verwalter. Er legt Stammdaten und Verträge an.
* **Mandatsexport (ZIP mit allen Daten)**: Inhaber und Verwalter. Er enthält Personendaten; die
  Buchhaltung sieht nach dem Rollenkonzept keine Stammdaten und bekommt ihn deshalb nicht.
* **Buchungsjournal für Banana/Abacus**: Inhaber, Verwalter und Buchhaltung. Es liest nur Buchungen.

Jeder Export wird VOR der Auslieferung im Aktivitätslog festgehalten (wer, wann, Zeitraum,
Umfang). Gelingt der Eintrag nicht, wird nichts ausgeliefert: ein Export ohne Spur ist ein
Datenabfluss, den niemand nachvollziehen kann. Fremde Läufe ergeben 404.
"""
import tempfile
from datetime import date

from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext

from core.auth import (FINANZ_VERWALTUNGS_ROLLEN, VERWALTUNGS_ROLLEN, client_ip, hat_rolle,
                       rolle_erforderlich)
from core.tenancy import organisation_der_anfrage

from ._basis import _global_filter

HUB = '/neu/einstellungen/daten/'
IMPORT = '/neu/einstellungen/daten/import/'
EXPORT = '/neu/einstellungen/daten/export/'


def _protokollieren(request, aktion, objekt, details):
    """Schreibt den Audit-Eintrag und wirft, wenn er nicht geschrieben werden kann.

    `core.auth.log_aktion` schluckt Fehler, weil ein Logbucheintrag sonst einen Geschäftsvorgang
    bricht. Bei einem Export ist es umgekehrt: Ohne Eintrag darf er nicht stattfinden."""
    from core.models import AktivitaetsLog
    AktivitaetsLog.objects.create(
        organisation=organisation_der_anfrage(request), benutzer=request.user, aktion=aktion[:100],
        objekt=str(objekt)[:200], details=str(details)[:2000], kategorie='sicherheit',
        ip_adresse=client_ip(request))


# ── Hub ───────────────────────────────────────────────────────────────────────
@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_daten(request):
    """Einstiegsseite: Import und Export; jede Rolle sieht nur, was sie darf."""
    return render(request, 'fw/daten.html', {
        **_global_filter(request), 'nav': 'einstellungen',
        'darf_import': hat_rolle(request.user, VERWALTUNGS_ROLLEN),
        'darf_mandat': hat_rolle(request.user, VERWALTUNGS_ROLLEN),
    })


# ── Import ────────────────────────────────────────────────────────────────────
def _import_kontext(request, **extra):
    from core.models import DatenImportLauf
    from core.services.datenimport import ART_TITEL, ARTEN, SPALTEN
    arten = [{'art': a, 'titel': ART_TITEL[a], 'spalten': SPALTEN[a]} for a in ARTEN]
    return {**_global_filter(request), 'nav': 'einstellungen', 'arten': arten,
            'laeufe': list(DatenImportLauf.objects.select_related('benutzer')[:10]), **extra}


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_daten_import(request):
    """GET: Formular, Vorlagen und Protokoll. POST: Dateien prüfen (Trockenlauf) und die Vorschau zeigen."""
    from core.services.datenimport import ARTEN, vorschau_erstellen
    if request.method != 'POST':
        return render(request, 'fw/daten_import.html', _import_kontext(request))
    dateien = {}
    for art in ARTEN:
        f = request.FILES.get(f'datei_{art}')
        if f is not None:
            # Eine Obergrenze vor dem Lesen: der Leser prüft sie ebenfalls, aber ein 2-GB-Upload
            # soll gar nicht erst in den Speicher.
            if f.size > 5 * 1024 * 1024:
                messages.error(request, gettext('Die Datei «%(n)s» ist grösser als 5 MB.') % {'n': f.name})
                return redirect(IMPORT)
            dateien[art] = (f.name, f.read())
    if not dateien:
        messages.error(request, gettext('Bitte mindestens eine Datei wählen.'))
        return redirect(IMPORT)
    lauf = vorschau_erstellen(organisation_der_anfrage(request), request.user, dateien)
    _protokollieren(request, 'Datenimport geprüft (Trockenlauf)', f'Import {lauf.pk}',
                    f'{lauf.get_status_display()} · Fehler: {lauf.anzahl_fehler} · Hinweise: {lauf.anzahl_hinweise} · '
                    f'Arten: {", ".join(dateien)}')
    return redirect(f'{IMPORT}{lauf.pk}/')


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_daten_import_vorlage(request, art):
    """Die Vorlage (nur Kopfzeile) einer Art als CSV."""
    from core.services.datenimport import ARTEN, vorlage_csv
    if art not in ARTEN:
        raise Http404
    antwort = HttpResponse(vorlage_csv(art), content_type='text/csv; charset=utf-8')
    antwort['Content-Disposition'] = f'attachment; filename="vorlage_{art}.csv"'
    return antwort


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_daten_import_lauf(request, pk):
    """Vorschau bzw. Protokoll eines Laufs (Fehlerliste je Zeile). Ein fremder Lauf ist ein 404."""
    from core.models import DatenImportLauf
    from core.services.datenimport import ART_TITEL
    lauf = get_object_or_404(DatenImportLauf.objects.select_related('benutzer'), pk=pk)
    meldungen = {'fehler': [], 'hinweis': []}
    for m in lauf.meldungen or []:
        m = dict(m)
        m['art_titel'] = ART_TITEL.get(m.get('art'), m.get('art') or '')
        meldungen['fehler' if m.get('stufe') == 'fehler' else 'hinweis'].append(m)
    zaehler = [{'titel': ART_TITEL[a], **z} for a, z in (lauf.zaehler or {}).items() if a in ART_TITEL]
    return render(request, 'fw/daten_import_lauf.html', {
        **_global_filter(request), 'nav': 'einstellungen', 'lauf': lauf, 'meldungen': meldungen,
        'zaehler': zaehler, 'abgeschnitten': (lauf.anzahl_fehler + lauf.anzahl_hinweise) > len(lauf.meldungen or []),
        'ausfuehrbar': lauf.status == lauf.STATUS_VORSCHAU,
    })


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_daten_import_ausfuehren(request, pk):
    """Führt eine fehlerfreie Vorschau aus (POST). Alles oder nichts."""
    from core.models import DatenImportLauf
    from core.services.datenimport import AusfuehrungsFehler, lauf_ausfuehren
    if request.method != 'POST':
        return redirect(f'{IMPORT}{pk}/')
    org = organisation_der_anfrage(request)
    get_object_or_404(DatenImportLauf.objects.only('pk'), pk=pk)       # fremd -> 404, bevor etwas geschieht
    try:
        lauf = lauf_ausfuehren(org, pk, request.user)
    except AusfuehrungsFehler as e:
        messages.error(request, str(e))
        return redirect(f'{IMPORT}{pk}/')
    z = lauf.zaehler or {}
    neu = sum(v.get('neu', 0) for v in z.values())
    _protokollieren(request, 'Datenimport ausgeführt' if lauf.status == lauf.STATUS_IMPORTIERT
                    else 'Datenimport abgebrochen', f'Import {lauf.pk}',
                    f'{lauf.get_status_display()} · neu: {neu} · Fehler: {lauf.anzahl_fehler}')
    if lauf.status == lauf.STATUS_IMPORTIERT:
        messages.success(request, gettext('Import abgeschlossen: %(n)s Datensätze angelegt.') % {'n': neu})
    else:
        messages.error(request, gettext('Der Import wurde abgebrochen, es wurde nichts angelegt. '
                                        'Die Fehlerliste zeigt, was zu korrigieren ist.'))
    return redirect(f'{IMPORT}{lauf.pk}/')


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_daten_import_verwerfen(request, pk):
    from core.models import DatenImportLauf
    from core.services.datenimport import lauf_verwerfen
    if request.method != 'POST':
        return redirect(f'{IMPORT}{pk}/')
    get_object_or_404(DatenImportLauf.objects.only('pk'), pk=pk)
    lauf_verwerfen(organisation_der_anfrage(request), pk)
    messages.success(request, gettext('Die hochgeladenen Dateien wurden verworfen.'))
    return redirect(IMPORT)


# ── Export ────────────────────────────────────────────────────────────────────
def _zeitraum(quelle):
    """(von, bis, Fehlertext) aus den Feldern «von»/«bis» (TT.MM.JJJJ oder JJJJ-MM-TT)."""
    from core.services.datenimport import datum_parsen
    try:
        von, bis = datum_parsen(quelle.get('von')), datum_parsen(quelle.get('bis'))
    except ValueError as e:
        return None, None, str(e)
    if von > bis:
        return None, None, gettext('Das Datum «von» liegt nach «bis».')
    return von, bis, ''


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_daten_export(request):
    """Seite: Zeitraum, Mandatsexport, Buchungsjournal und seine Einstellungen."""
    from core.services import datenexport
    heute = date.today()
    einst = datenexport.einstellung_holen()
    return render(request, 'fw/daten_export.html', {
        **_global_filter(request), 'nav': 'einstellungen',
        'darf_mandat': hat_rolle(request.user, VERWALTUNGS_ROLLEN),
        'von': request.GET.get('von') or date(heute.year, 1, 1).isoformat(),
        'bis': request.GET.get('bis') or heute.isoformat(),
        'einst': einst,
        'spalten_liste': [{'k': k, 'standard': datenexport.SPALTEN_VORGABE[k], 'wert': datenexport.spalten_von(einst)[k]}
                          for k in datenexport.SPALTEN_REIHENFOLGE],
        'konten_text': datenexport.konten_text(einst), 'trenner_liste': datenexport.TRENNER.items(),
    })


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_daten_export_einstellung(request):
    """Speichert Überschriften, Formate und Kontenzuordnung (POST) der eigenen Organisation."""
    from core.services import datenexport
    if request.method != 'POST':
        return redirect(EXPORT)
    P = request.POST
    try:
        konten = datenexport.konten_parsen(P.get('konten', ''))
    except datenexport.ZuordnungsFehler as e:
        messages.error(request, str(e))
        return redirect(EXPORT)
    einst = datenexport.einstellung_holen(erstellen=True)
    spalten = {}
    for k in datenexport.SPALTEN_REIHENFOLGE:
        text = (P.get(f'spalte_{k}') or '').strip()
        if len(text) > 40:
            messages.error(request, gettext('Die Überschrift «%(t)s» ist zu lang (höchstens 40 Zeichen).') % {'t': text})
            return redirect(EXPORT)
        if text and text != datenexport.SPALTEN_VORGABE[k]:
            spalten[k] = text
    namen = list(datenexport.spalten_aus(spalten).values())
    if len(set(namen)) != len(namen):
        messages.error(request, gettext('Jede Spalte braucht eine eigene Überschrift.'))
        return redirect(EXPORT)
    trenner = P.get('trenner', ';')
    einst.trenner = trenner if trenner in datenexport.TRENNER else ';'
    einst.datumsformat = 'iso' if P.get('datumsformat') == 'iso' else 'ch'
    einst.dezimal = ',' if P.get('dezimal') == ',' else '.'
    einst.spalten = spalten
    einst.konten = konten
    einst.save()
    _protokollieren(request, 'Export-Einstellungen geändert', 'Buchungsjournal',
                    f'{len(konten)} Konten zugeordnet, Überschriften: {", ".join(namen)}')
    messages.success(request, gettext('Die Einstellungen für das Buchungsjournal sind gespeichert.'))
    return redirect(EXPORT)


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_daten_export_journal(request):
    """Buchungsjournal als CSV für Banana/Abacus (POST, nur lesend)."""
    from core.services import datenexport
    if request.method != 'POST':
        return redirect(EXPORT)
    von, bis, fehler = _zeitraum(request.POST)
    if fehler:
        messages.error(request, fehler)
        return redirect(EXPORT)
    text, stat = datenexport.journal_csv(von, bis)
    _protokollieren(
        request, 'Buchungsjournal exportiert', organisation_der_anfrage(request).firma,
        f'{von:%d.%m.%Y} bis {bis:%d.%m.%Y} · {stat["zeilen"]} Buchungen · CHF {stat["summe"]}'
        + (f' · Konten ohne Zuordnung: {", ".join(stat["ohne_zuordnung"])}' if stat['ohne_zuordnung'] else ''))
    antwort = HttpResponse(text, content_type='text/csv; charset=utf-8')
    antwort['Content-Disposition'] = f'attachment; filename="Buchungsjournal_{von:%Y%m%d}_{bis:%Y%m%d}.csv"'
    antwort['X-Export-Zeilen'] = str(stat['zeilen'])
    antwort['X-Export-Ohne-Zuordnung'] = str(len(stat['ohne_zuordnung']))
    return antwort


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_daten_export_mandat(request):
    """Mandatsexport (ZIP mit CSV/JSON je Tabelle und den Dokumenten), POST, nur lesend."""
    from core.services import datenexport
    if request.method != 'POST':
        return redirect(EXPORT)
    org = organisation_der_anfrage(request)
    mit_dokumenten = request.POST.get('dokumente') == 'on'
    datei = tempfile.TemporaryFile()                                   # wird beim Schliessen der Antwort gelöscht
    try:
        stat = datenexport.mandat_zip(org, datei, mit_dokumenten=mit_dokumenten,
                                      erstellt_von=request.user.get_full_name() or request.user.get_username())
        _protokollieren(
            request, 'Mandatsexport erstellt', org.firma,
            f'{len(stat["tabellen"])} Tabellen · {stat["zeilen"]} Zeilen · '
            + (f'{stat["dokumente"]} Dokumente ({stat["fehlende_dokumente"]} nicht lesbar)' if mit_dokumenten
               else 'ohne Dokumente'))
    except Exception:
        datei.close()
        raise
    datei.seek(0)
    antwort = FileResponse(datei, as_attachment=True, content_type='application/zip',
                           filename=f'Mandatsexport_{date.today():%Y%m%d}.zip')
    return antwort
