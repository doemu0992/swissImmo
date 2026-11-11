# core/views/fw/stammdaten_aktionen.py
#
# Vertragsmietzins-Komponenten, Dienstleister, Dokumente, Nebenkosten anlegen/loeschen.
# Aus aktionen.py herausgeloest (reiner Umzug ohne Aenderung am Code).

from datetime import date
from decimal import Decimal

from django.utils.translation import gettext
from django.shortcuts import get_object_or_404

from core.auth import (rolle_erforderlich, SCHREIB_ROLLEN)
from portfolio.models import Liegenschaft


from ._basis import (_num)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_mietzins_add(request, pk):
    """Fügt dem Mietverhältnis eine datierte Mietzins-Komponente hinzu (gültig ab,
    Netto, NK) — für Gratismonate/gestaffelten Start. Massgeblich für die Sollstellung."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Mietvertrag, VertragMietzins
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=pk)
    # Rücksprung: Objekt-Mietzins-Tab (wenn von dort erfasst) sonst Vertrag-Tab.
    _nxt = request.POST.get('next') or ''
    ziel = _nxt if _nxt.startswith('/neu/') else f'/neu/vertraege/{v.id}/?tab=mietzins'
    if request.method != 'POST':
        return redirect(ziel)

    def _dec(name):
        raw = _num(request.POST.get(name))
        try:
            return Decimal(raw)
        except Exception:
            return None
    try:
        gab = date.fromisoformat(request.POST.get('gueltig_ab') or '')
    except ValueError:
        gab = None
    netto = _dec('netto_mietzins')
    nk = _dec('nebenkosten')
    if not gab or netto is None or nk is None or netto < 0 or nk < 0:
        messages.error(request, gettext('Gültig-ab-Datum, Netto und NK (≥ 0) sind erforderlich.'))
        return redirect(ziel)
    # Rabatt/Erlass (Option B): mindert nur die Verrechnung, nicht die Referenz.
    # "mietzinsfrei" = Nettomietzins voll erlassen → Rabatt = Netto-Referenz.
    if request.POST.get('mietzinsfrei'):
        rabatt_netto = netto
    else:
        rabatt_netto = _dec('rabatt_netto') or Decimal('0.00')
    rabatt_nk = _dec('rabatt_nk') or Decimal('0.00')
    if rabatt_netto < 0 or rabatt_nk < 0:
        messages.error(request, gettext('Rabatt-Werte dürfen nicht negativ sein.'))
        return redirect(ziel)
    rabatt_netto = min(rabatt_netto, netto)   # Rabatt nie grösser als Referenz
    rabatt_nk = min(rabatt_nk, nk)
    VertragMietzins.objects.update_or_create(
        vertrag=v, gueltig_ab=gab,
        defaults={'netto_mietzins': netto, 'nebenkosten': nk,
                  'rabatt_netto': rabatt_netto, 'rabatt_nk': rabatt_nk,
                  'notiz': (request.POST.get('notiz') or '').strip()[:200]})
    zu_zahlen = max(Decimal('0'), netto - rabatt_netto) + max(Decimal('0'), nk - rabatt_nk)
    log_aktion(request, "Mietzins-Komponente erfasst", str(v),
               f"ab {gab:%d.%m.%Y}: Referenz Netto {netto} / NK {nk}, "
               f"Rabatt {rabatt_netto}/{rabatt_nk}, zu zahlen {zu_zahlen}", ziel=v)
    messages.success(request, '✅ ' + gettext('Komponente ab %(gab)s gespeichert (Referenz CHF %(wert)s, zu zahlen CHF %(zu_zahlen)s).') % {'gab': format(gab, '%d.%m.%Y'), 'wert': netto + nk, 'zu_zahlen': zu_zahlen})
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_mietzins_del(request, pk):
    """Entfernt eine Mietzins-Komponente."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import VertragMietzins
    k = get_object_or_404(VertragMietzins.objects.select_related('vertrag'), id=pk)
    vid = k.vertrag_id
    _nxt = request.POST.get('next') or ''
    ziel = _nxt if _nxt.startswith('/neu/') else f'/neu/vertraege/{vid}/?tab=mietzins'
    if request.method == 'POST':
        k.delete()
        messages.success(request, gettext('Komponente entfernt.'))
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_dienstleister_neu(request):
    """Handwerker / Dienstleister erfassen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Handwerker
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_dienstleister')
    firma = (request.POST.get('firma') or '').strip()
    if not firma:
        messages.error(request, gettext('Firma ist erforderlich.'))
        return redirect('fw_dienstleister')
    Handwerker.objects.create(
        firma=firma, branche=request.POST.get('branche', 'allgemein'),
        kontaktperson=(request.POST.get('kontaktperson') or '').strip(),
        email=(request.POST.get('email') or '').strip(),
        telefon=(request.POST.get('telefon') or '').strip(),
    )
    log_aktion(request, "Dienstleister erfasst", firma, '')
    messages.success(request, '✅ ' + gettext("Dienstleister '%(firma)s' erfasst.") % {'firma': firma})
    return redirect('fw_dienstleister')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_dokument_neu(request):
    """Dokument hochladen (Portfolio-Ablage)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Dokument as PDokument, Einheit
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_dokumente')
    if not request.FILES.get('datei'):
        messages.error(request, gettext('Bitte eine Datei auswählen.'))
        return redirect('fw_dokumente')
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    PDokument.objects.create(
        titel=(request.POST.get('titel') or request.FILES['datei'].name).strip(),
        kategorie=request.POST.get('kategorie', 'sonstiges'),
        liegenschaft=lg,
        einheit=Einheit.objects.filter(id=request.POST.get('einheit_id') or None).first() if request.POST.get('einheit_id') else None,
        datei=request.FILES['datei'],
        im_portal_sichtbar=request.POST.get('im_portal_sichtbar') == '1',
    )
    log_aktion(request, "Dokument hochgeladen", request.POST.get('titel', ''), '')
    messages.success(request, '✅ ' + gettext('Dokument hochgeladen.'))
    ziel = '/neu/dokumente/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_dokument_loeschen(request, pk):
    """Portfolio-/Objekt-Dokument löschen (hochgeladene Ablage)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Dokument as PDokument
    from core.auth import log_aktion
    d = get_object_or_404(PDokument, id=pk)
    if request.method == 'POST':
        # Kein hartes Löschen (Art. 958f OR): Das Dokument geht ins Archiv und bleibt zehn Jahre.
        from core.services import archiv
        titel = d.titel
        try:
            archiv.archivieren(d, user=request.user, grund='Dokument entfernt')
        except archiv.ArchivFehler as fehler:
            messages.error(request, '❌ ' + str(fehler))
        else:
            log_aktion(request, "Dokument archiviert", titel, '')
            messages.success(request, '📦 ' + gettext('Dokument archiviert.'))
    ziel = '/neu/dokumente/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_nebenkosten_neu(request):
    """Neue Nebenkosten-Abrechnungsperiode anlegen — Schritt 1 des Wizards.

    GET zeigt das Formular (vorher ein Ausklapp-Formular auf der Liste), POST legt an und
    führt in den Wizard. Höchstens 12 Monate (`core.services.nk_wizard.periode_pruefen`);
    Fehler stehen am Feld, die Eingabe bleibt.
    """
    from django.shortcuts import redirect, render
    from django.contrib import messages
    from finance.models import AbrechnungsPeriode
    from core.auth import log_aktion
    from core.services.nk_wizard import periode_pruefen
    from ._basis import _global_filter
    from .nk_wizard import einstieg_assistent
    basis = _global_filter(request)

    def _formular(eingabe, fehler, status):
        return render(request, 'fw/nk/neu.html', {
            **basis, 'nav': 'nebenkosten', 'eingabe': eingabe, 'fehler': fehler,
            'assistent': einstieg_assistent(basis.get('lg_query', '')),
            'liegenschaften': Liegenschaft.objects.order_by('strasse')}, status=status)

    if request.method != 'POST':
        vorwahl = basis['aktive_lg'].id if basis.get('aktive_lg') else ''
        return _formular({'liegenschaft_id': str(vorwahl)}, {}, 200)
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    bez = (request.POST.get('bezeichnung') or '').strip()[:100]
    start, ende, fehler = periode_pruefen(request.POST.get('start_datum'), request.POST.get('ende_datum'))
    if not lg:
        fehler['liegenschaft_id'] = gettext('Bitte eine Liegenschaft wählen.')
    if not bez:
        fehler['bezeichnung'] = gettext('Bitte eine Bezeichnung angeben.')
    if fehler:
        messages.error(request, gettext('Liegenschaft, Bezeichnung, Start- und Enddatum sind erforderlich; '
                                        'eine Periode umfasst höchstens 12 Monate.'))
        return _formular(request.POST.dict(), fehler, 400)
    p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung=bez, start_datum=start, ende_datum=ende)
    log_aktion(request, "Abrechnungsperiode erstellt", bez, str(lg))
    messages.success(request, '✅ ' + gettext("Abrechnungsperiode '%(bez)s' erstellt.") % {'bez': bez})
    return redirect(f'/neu/nebenkosten/{p.id}/periode/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_dienstleister_bearbeiten(request, pk):
    """Dienstleister / Handwerker bearbeiten (Stammdaten)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Handwerker
    from core.auth import log_aktion
    h = get_object_or_404(Handwerker, id=pk)
    if request.method != 'POST':
        return redirect('fw_dienstleister')
    firma = (request.POST.get('firma') or '').strip()
    if not firma:
        messages.error(request, gettext('Firma ist erforderlich.'))
        return redirect('fw_dienstleister')
    h.firma = firma
    h.branche = request.POST.get('branche', h.branche) or h.branche
    h.kontaktperson = (request.POST.get('kontaktperson') or '').strip()
    h.email = (request.POST.get('email') or '').strip()
    h.telefon = (request.POST.get('telefon') or '').strip()
    h.save()
    log_aktion(request, "Dienstleister bearbeitet", firma, '')
    messages.success(request, '✅ ' + gettext("Dienstleister '%(firma)s' aktualisiert.") % {'firma': firma})
    return redirect('fw_dienstleister')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_dienstleister_loeschen(request, pk):
    """Dienstleister / Handwerker löschen (Stammdaten)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Handwerker
    from core.auth import log_aktion
    h = get_object_or_404(Handwerker, id=pk)
    if request.method == 'POST':
        firma = h.firma
        h.delete()
        log_aktion(request, "Dienstleister gelöscht", firma, '')
        messages.success(request, '🗑️ ' + gettext("Dienstleister '%(firma)s' gelöscht.") % {'firma': firma})
    return redirect('fw_dienstleister')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_nebenkosten_loeschen(request, pk):
    """Nebenkosten-Abrechnungsperiode löschen — nur solange nicht abgeschlossen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import AbrechnungsPeriode
    from core.auth import log_aktion
    p = get_object_or_404(AbrechnungsPeriode, id=pk)
    if request.method == 'POST':
        if getattr(p, 'abgeschlossen', False):
            messages.error(request, gettext('Abgeschlossene Periode kann nicht gelöscht werden.'))
            return redirect(f'/neu/nebenkosten/{p.id}/')
        bez = p.bezeichnung
        p.delete()
        log_aktion(request, "Abrechnungsperiode gelöscht", bez, '')
        messages.success(request, '🗑️ ' + gettext("Abrechnungsperiode '%(bez)s' gelöscht.") % {'bez': bez})
    return redirect('fw_nebenkosten')
