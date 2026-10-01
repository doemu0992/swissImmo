# core/views/fw/mahnstufen.py
#
# Die Mahnstufen der eigenen Verwaltung: ansehen, ändern, ergänzen, löschen.
#
# Hier entscheidet eine Verwaltung, ab wie vielen Tagen Verzug sie mahnt — im
# Code steht keine Frist. Die Stufen liegen in `crm.MahnStufe` (je Organisation),
# gelesen werden sie über `core.services.mahnstufen`.
#
# Isolation: `MahnStufe.objects` filtert auf die Organisation des Kontexts. Eine
# fremde Stufe ist darum nicht «verboten», sondern schlicht nicht da (404).

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext

from core.auth import rolle_erforderlich, VERWALTUNGS_ROLLEN, log_aktion
from core.tenancy import organisation_der_anfrage
from crm.models import MahnStufe

from ._basis import _global_filter

ZIEL = '/neu/mahnstufen/'


def _zahl(roh, standard=None):
    """Ganze Zahl >= 0 aus einem Formularfeld, sonst `standard`."""
    try:
        wert = int(str(roh).strip())
    except (TypeError, ValueError):
        return standard
    return wert if wert >= 0 else standard


def _betrag(roh):
    """Betrag >= 0 (Komma oder Punkt), leer = 0.00; ungültig = None."""
    text = str(roh or '0').strip().replace(',', '.') or '0'
    try:
        betrag = Decimal(text).quantize(Decimal('0.01'))
    except InvalidOperation:
        return None
    return betrag if betrag >= 0 else None


def _reihenfolge_fehler(paare):
    from core.services.mahnstufen import pruefe_reihenfolge
    schlecht = pruefe_reihenfolge(paare)
    if not schlecht:
        return None
    s1, t1, s2, t2 = schlecht
    return gettext('Stufe %(s2)s (%(t2)s Tage) muss später greifen als Stufe %(s1)s (%(t1)s Tage).') % {
        's1': s1, 't1': t1, 's2': s2, 't2': t2}


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_mahnstufen(request):
    """Alle Stufen der Verwaltung; POST speichert alle Änderungen auf einmal."""
    stufen = list(MahnStufe.objects.order_by('stufe'))
    if request.method == 'POST':
        fehler, neue_werte = [], []
        for s in stufen:
            name = (request.POST.get(f'bezeichnung_{s.pk}') or '').strip()
            tage = _zahl(request.POST.get(f'ab_tage_{s.pk}'))
            geb = _betrag(request.POST.get(f'gebuehr_{s.pk}'))
            if not name or tage is None or geb is None:
                fehler.append(gettext('Stufe %(stufe)s: Bezeichnung, Tage (ganze Zahl) und Spesen (Betrag) ausfüllen.')
                              % {'stufe': s.stufe})
                continue
            brief = ((request.POST.get(f'brief_titel_{s.pk}') or '').strip()[:120],
                     (request.POST.get(f'brief_text_{s.pk}') or '').strip())
            neue_werte.append((s, name, tage, geb, request.POST.get(f'art_257d_{s.pk}') == 'on', brief))
        if not fehler:
            reihenfolge = _reihenfolge_fehler([(s.stufe, tage) for s, _n, tage, _g, _a, _b in neue_werte])
            if reihenfolge:
                fehler.append(reihenfolge)
        if fehler:
            for f in fehler:
                messages.error(request, '❌ ' + f)
        else:
            for s, name, tage, geb, art, (titel, text) in neue_werte:
                s.bezeichnung, s.ab_tage, s.gebuehr, s.art_257d = name, tage, geb, art
                s.brief_titel, s.brief_text = titel, text
                s.save(update_fields=['bezeichnung', 'ab_tage', 'gebuehr', 'art_257d',
                                      'brief_titel', 'brief_text'])
            log_aktion(request, "Mahnstufen geändert", "Mahnstufen",
                       " · ".join(f"St{s.stufe}:{s.ab_tage}T/CHF {s.gebuehr}" for s in stufen))
            messages.success(request, '✅ ' + gettext('Mahnstufen gespeichert.'))
        return redirect(ZIEL)
    return render(request, 'fw/mahnstufen.html', {
        **_global_filter(request), 'nav': 'mahnwesen', 'stufen': stufen,
        'org': organisation_der_anfrage(request),
        'naechste_stufe': (stufen[-1].stufe + 1) if stufen else 1,
    })


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_mahnstufe_neu(request):
    """Hängt eine Stufe an (Nummer = höchste + 1)."""
    if request.method != 'POST':
        return redirect(ZIEL)
    name = (request.POST.get('bezeichnung') or '').strip()
    tage = _zahl(request.POST.get('ab_tage'))
    geb = _betrag(request.POST.get('gebuehr'))
    if not name or tage is None or geb is None:
        messages.error(request, '❌ ' + gettext('Bezeichnung, Tage (ganze Zahl) und Spesen (Betrag) ausfüllen.'))
        return redirect(ZIEL)
    hoechste = MahnStufe.objects.aggregate(m=Max('stufe'))['m'] or 0
    stufe = hoechste + 1
    bestehende = list(MahnStufe.objects.values_list('stufe', 'ab_tage'))
    fehler = _reihenfolge_fehler(bestehende + [(stufe, tage)])
    if fehler:
        messages.error(request, '❌ ' + fehler)
        return redirect(ZIEL)
    MahnStufe.objects.create(stufe=stufe, bezeichnung=name, ab_tage=tage, gebuehr=geb,
                             art_257d=request.POST.get('art_257d') == 'on')
    log_aktion(request, "Mahnstufe hinzugefügt", "Mahnstufen", f"Stufe {stufe}: {name} ab {tage} Tagen")
    messages.success(request, '✅ ' + gettext('Mahnstufe hinzugefügt.'))
    return redirect(ZIEL)


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_mahnstufe_loeschen(request, pk):
    """Löscht eine Stufe der eigenen Verwaltung. Bereits erfasste Mahnungen
    bleiben in der Historie stehen (sie tragen nur die Stufennummer)."""
    if request.method != 'POST':
        return redirect(ZIEL)
    # 404 bei fremder ID: MahnStufe.objects filtert auf die Organisation des Kontexts.
    s = get_object_or_404(MahnStufe, pk=pk)
    log_aktion(request, "Mahnstufe gelöscht", "Mahnstufen", f"Stufe {s.stufe}: {s.bezeichnung}")
    s.delete()
    messages.success(request, '✅ ' + gettext('Mahnstufe gelöscht.'))
    return redirect(ZIEL)


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_mahnwesen_einstellungen(request):
    """Verzugsbeginn, Mindestabstand und Verzugszins der eigenen Verwaltung.

    Geschrieben wird immer die Organisation der Anfrage — es gibt keine ID im
    Pfad, die man auf eine fremde Verwaltung richten könnte."""
    if request.method != 'POST':
        return redirect(ZIEL)
    org = organisation_der_anfrage(request)
    ab_tag = _zahl(request.POST.get('mahn_verzug_ab_tag'))
    abstand = _zahl(request.POST.get('mahn_mindestabstand_tage'))
    zins = _betrag(request.POST.get('verzugszins_prozent'))
    if ab_tag is None or abstand is None or zins is None or ab_tag > 365 or abstand > 365 or zins > 100:
        messages.error(request, '❌ ' + gettext('Verzugsbeginn und Mindestabstand (ganze Tage) sowie Verzugszins (Prozent) prüfen.'))
        return redirect(ZIEL)
    org.mahn_verzug_ab_tag, org.mahn_mindestabstand_tage, org.verzugszins_prozent = ab_tag, abstand, zins
    org.save(update_fields=['mahn_verzug_ab_tag', 'mahn_mindestabstand_tage', 'verzugszins_prozent'])
    log_aktion(request, "Mahnwesen-Einstellungen geändert", "Mahnstufen",
               f"Verzug ab Tag {ab_tag} · Mindestabstand {abstand} Tage · Verzugszins {zins} %")
    messages.success(request, '✅ ' + gettext('Mahnwesen-Einstellungen gespeichert.'))
    return redirect(ZIEL)
