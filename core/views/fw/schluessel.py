# core/views/fw/schluessel.py
#
# Modul 2 (27.10.2026): Schliessanlage, Türen, Schlüssel, Ausgabe und
# Rücknahme mit Unterschrift und Quittung. Die Fachlogik steht in
# core/services/schluessel.py; hier stehen Eingabe, Berechtigung und Antwort.
#
# Jede ID aus dem Aufruf geht durch `get_object_or_404(Modell.objects, …)` —
# der Mandantenmanager liefert für fremde IDs nichts, also 404. Zusätzlich
# wird jedes Unterobjekt (Einheit, Anlage, Tür, Schlüssel) gegen DIE
# Liegenschaft geprüft, um die es geht: Eine eigene Tür einer anderen
# eigenen Liegenschaft gehört auch nicht an diesen Schlüssel.

from datetime import date

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from core.auth import SCHREIB_ROLLEN, TEAM_ROLLEN, log_aktion, rolle_erforderlich
from core.services import schluessel as sl
from portfolio.models import (Einheit, Liegenschaft, Schliessanlage, Schliesspunkt, Schluessel,
                              SchluesselAusgabe)

from ._basis import _global_filter

__all__ = [
    'schliessanlage_kontext',
    'fw_liegenschaft_schliessanlage', 'fw_schliessanlage_loeschen',
    'fw_liegenschaft_schliesspunkt', 'fw_schliesspunkt_loeschen',
    'fw_liegenschaft_schluessel_neu', 'fw_schluessel_bearbeiten',
    'fw_liegenschaft_schluessel_ausgabe', 'fw_liegenschaft_schluessel_ruecknahme',
    'fw_schluessel_faellig',
]


def _lg_ziel(lg):
    return f'/neu/liegenschaften/{lg.pk}/?tab=stammdaten#schliessanlage'


def _weiter(request, standard):
    """`next` aus dem Formular, aber nur innerhalb von /neu/ — keine offene Weiterleitung."""
    ziel = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if ziel.startswith('/neu/') and not ziel.startswith('//') and '\\' not in ziel:
        return ziel
    return standard


def _organisation(request):
    from core.tenancy import aktuelle_organisation
    return getattr(request, 'organisation', None) or aktuelle_organisation()


def _datum(text):
    try:
        return date.fromisoformat((text or '').strip())
    except ValueError:
        return None


def _zahl(text, standard=0):
    text = (text or '').strip()
    return int(text) if text.isdigit() and int(text) < 1000 else standard


def _text(P, feld, laenge):
    return ' '.join((P.get(feld) or '').split())[:laenge]


# ---------------------------------------------------------------------------
# Abschnitt «Schliessanlage» der Liegenschaft
# ---------------------------------------------------------------------------

def schliessanlage_kontext(request, lg, einheiten=None):
    """Der Kontext für `fw/_schliessanlage.html` in der Liegenschaftsakte.

    `?tuer=<id>` filtert die Karten auf die Schlüssel, die durch diese Tür
    kommen («Wer kommt durch diese Tür?»)."""
    heute = timezone.localdate()
    anlagen = list(lg.schliessanlagen.all())
    punkte = list(Schliesspunkt.objects.filter(liegenschaft=lg).select_related('einheit', 'anlage'))
    alle = sl.karten(Schluessel.objects.filter(liegenschaft=lg), heute)
    aktiv = [k for k in alle if not k['s'].archiviert]
    tuer = None
    tuer_id = request.GET.get('tuer') or ''
    if tuer_id.isdigit():
        tuer = next((p for p in punkte if p.pk == int(tuer_id)), None)
    gezeigt = [k for k in aktiv if sl.oeffnet_tuer(k, tuer)] if tuer else aktiv
    durch = []
    if tuer:
        for k in gezeigt:
            for a in k['offene']:
                durch.append({'a': a, 'k': k})
    faellig = list(sl.faellige(heute, lg))
    for a in faellig:
        a.ruecknahme_url = sl.ruecknahme_url(a)
        a.tage = (heute - a.rueckgabe_bis).days
    return {
        'sl_anlagen': anlagen,
        'sl_punkte': punkte,
        'sl_karten': gezeigt,
        'sl_archiv': [k for k in alle if k['s'].archiviert],
        'sl_bestand': sl.bestand(alle),
        'sl_faellig': faellig,
        'sl_verluste': list(sl.offene_verluste(lg)[:5]),
        'sl_tuer': tuer,
        'sl_durch': durch,
        'sl_einheiten': einheiten if einheiten is not None else list(lg.einheiten.order_by('bezeichnung')),
        'sl_arten': Schluessel.ART_CHOICES,
        'sl_ziel': _lg_ziel(lg),
    }


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_liegenschaft_schliessanlage(request, pk):
    """Legt eine Schliessanlage an oder ändert sie (`anlage_id`)."""
    lg = get_object_or_404(Liegenschaft.objects, pk=pk)
    P = request.POST
    anlage = None
    if (P.get('anlage_id') or '').isdigit():
        anlage = get_object_or_404(Schliessanlage.objects, pk=int(P['anlage_id']), liegenschaft=lg)
    werte = {'hersteller': _text(P, 'hersteller', 80), 'system': _text(P, 'system', 80),
             'sicherungskarte_nr': _text(P, 'sicherungskarte_nr', 60),
             'bestellberechtigte': (P.get('bestellberechtigte') or '').strip()[:2000],
             'notiz': (P.get('notiz') or '').strip()[:2000]}
    if not (werte['hersteller'] or werte['system'] or werte['sicherungskarte_nr']):
        messages.error(request, gettext('Bitte Hersteller, System oder Sicherungskarte angeben.'))
        return redirect(_lg_ziel(lg))
    if anlage is None:
        anlage = Schliessanlage.objects.create(liegenschaft=lg, **werte)
        log_aktion(request, "Schliessanlage erfasst", lg.strasse, str(anlage))
    else:
        for k, v in werte.items():
            setattr(anlage, k, v)
        anlage.save()
        log_aktion(request, "Schliessanlage geändert", lg.strasse, str(anlage))
    messages.success(request, gettext('Schliessanlage gespeichert.'))
    return redirect(_lg_ziel(lg))


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_schliessanlage_loeschen(request, pk):
    """Entfernt eine Anlage. Schlüssel und Türen bleiben, ohne Anlage."""
    anlage = get_object_or_404(Schliessanlage.objects.select_related('liegenschaft'), pk=pk)
    lg = anlage.liegenschaft
    log_aktion(request, "Schliessanlage entfernt", lg.strasse, str(anlage))
    anlage.delete()
    messages.success(request, gettext('Schliessanlage entfernt. Schlüssel und Türen bleiben erhalten.'))
    return redirect(_lg_ziel(lg))


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_liegenschaft_schliesspunkt(request, pk):
    """Erfasst eine Tür bzw. einen Zylinder."""
    lg = get_object_or_404(Liegenschaft.objects, pk=pk)
    P = request.POST
    bezeichnung = _text(P, 'bezeichnung', 80)
    if not bezeichnung:
        messages.error(request, gettext('Bitte die Tür bezeichnen, z. B. Haustür oder Keller.'))
        return redirect(_lg_ziel(lg))
    anlage = einheit = None
    if (P.get('anlage_id') or '').isdigit():
        anlage = get_object_or_404(Schliessanlage.objects, pk=int(P['anlage_id']), liegenschaft=lg)
    if (P.get('einheit_id') or '').isdigit():
        einheit = get_object_or_404(Einheit.objects, pk=int(P['einheit_id']), liegenschaft=lg)
    Schliesspunkt.objects.create(liegenschaft=lg, anlage=anlage, einheit=einheit, bezeichnung=bezeichnung)
    messages.success(request, gettext('Tür «%(t)s» erfasst.') % {'t': bezeichnung})
    return redirect(_lg_ziel(lg))


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_schliesspunkt_loeschen(request, pk):
    punkt = get_object_or_404(Schliesspunkt.objects.select_related('liegenschaft'), pk=pk)
    lg = punkt.liegenschaft
    punkt.delete()
    messages.success(request, gettext('Tür entfernt.'))
    return redirect(_lg_ziel(lg))


def _schluessel_felder(request, lg, sch=None):
    """Liest das Schlüsselformular. Gibt (Werte, Türen, Fehler) zurück."""
    P = request.POST
    fehler = []
    werte = {'typ': _text(P, 'typ', 50), 'schluessel_nummer': _text(P, 'schluessel_nummer', 50),
             'anzahl': max(1, _zahl(P.get('anzahl'), 1)),
             'art': P.get('art') if P.get('art') in dict(Schluessel.ART_CHOICES) else 'einzel',
             'einheit': None, 'schliessanlage': None}
    if not werte['typ'] or not werte['schluessel_nummer']:
        fehler.append(gettext('Bezeichnung und Schlüssel-Nr. sind Pflichtfelder.'))
    if (P.get('einheit_id') or '').isdigit():
        werte['einheit'] = get_object_or_404(Einheit.objects, pk=int(P['einheit_id']), liegenschaft=lg)
    if (P.get('schliessanlage') or '').isdigit():
        werte['schliessanlage'] = get_object_or_404(Schliessanlage.objects, pk=int(P['schliessanlage']),
                                                    liegenschaft=lg)
    ids = [int(x) for x in P.getlist('oeffnet') if x.isdigit()]
    tueren = list(Schliesspunkt.objects.filter(liegenschaft=lg, pk__in=ids))
    if len(tueren) != len(set(ids)):
        fehler.append(gettext('Eine gewählte Tür gehört nicht zu dieser Liegenschaft.'))
    if sch is not None:
        belegt = sch.anzahl - sl.verfuegbar(sch)
        if werte['anzahl'] < belegt:
            fehler.append(gettext('%(n)s Stück sind ausgegeben oder verloren — weniger geht nicht.') % {'n': belegt})
    return werte, tueren, fehler


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_liegenschaft_schluessel_neu(request, pk):
    """Erfasst einen Schlüssel an der Liegenschaft — mit oder ohne Einheit
    (Haustür, Briefkasten, Gruppenschlüssel)."""
    lg = get_object_or_404(Liegenschaft.objects, pk=pk)
    ziel = _weiter(request, _lg_ziel(lg))
    werte, tueren, fehler = _schluessel_felder(request, lg)
    if fehler:
        for f in fehler:
            messages.error(request, f)
        return redirect(ziel)
    sch = Schluessel.objects.create(liegenschaft=lg, **werte)
    sch.oeffnet.set(tueren)
    log_aktion(request, "Schlüssel erfasst", lg.strasse,
               f"{sch.typ} {sch.schluessel_nummer} × {sch.anzahl}")
    messages.success(request, gettext('Schlüssel %(nr)s erfasst.') % {'nr': sch.schluessel_nummer})
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_schluessel_bearbeiten(request, pk):
    """Ändert einen Schlüssel: Bezeichnung, Nummer, Stück, Art, Anlage, Türen.
    `archiviert=0` holt einen archivierten Schlüssel zurück."""
    sch = get_object_or_404(Schluessel.objects.select_related('liegenschaft'), pk=pk)
    lg = sch.liegenschaft
    ziel = _weiter(request, _lg_ziel(lg))
    if request.POST.get('archiviert') == '0' and 'typ' not in request.POST:
        sch.archiviert = False
        sch.save(update_fields=['archiviert'])
        messages.success(request, gettext('Schlüssel %(nr)s ist wieder aktiv.') % {'nr': sch.schluessel_nummer})
        return redirect(ziel)
    werte, tueren, fehler = _schluessel_felder(request, lg, sch)
    if fehler:
        for f in fehler:
            messages.error(request, f)
        return redirect(ziel)
    for k, v in werte.items():
        setattr(sch, k, v)
    sch.save()
    sch.oeffnet.set(tueren)
    log_aktion(request, "Schlüssel geändert", lg.strasse, f"{sch.typ} {sch.schluessel_nummer}")
    messages.success(request, gettext('Schlüssel %(nr)s gespeichert.') % {'nr': sch.schluessel_nummer})
    return redirect(ziel)


# ---------------------------------------------------------------------------
# Ausgabe und Rücknahme (mobile Kartenseiten)
# ---------------------------------------------------------------------------

def _embed(request):
    return (request.GET.get('embed') or request.POST.get('embed')) == '1'


def _fertig(request, ziel, text):
    if _embed(request):
        return render(request, 'fw/_modal_done.html', {'msg': text})
    messages.success(request, text)
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_liegenschaft_schluessel_ausgabe(request, pk):
    """Schlüssel ausgeben: Empfänger, Schlüssel, «zurück bis», Unterschrift.

    Daraus entsteht die Quittung als PDF in der Ablage (am Vertrag, sonst am
    Objekt oder an der Liegenschaft)."""
    lg = get_object_or_404(Liegenschaft.objects.select_related('organisation'), pk=pk)
    org = _organisation(request)
    heute = timezone.localdate()
    P = request.POST if request.method == 'POST' else None
    karten = [k for k in sl.karten(Schluessel.objects.filter(liegenschaft=lg, archiviert=False), heute)]
    auswahl = sl.empfaenger_auswahl(lg, org)
    vorwahl_empf = (P.get('empfaenger') if P else request.GET.get('an')) or ''
    if vorwahl_empf.startswith('mieter:'):
        # Aus der Personenakte: der Mieter, gewählt wird sein Vertrag an dieser Liegenschaft.
        v = next((v for v in auswahl['vertraege'] if f'mieter:{v.mieter_id}' == vorwahl_empf), None)
        vorwahl_empf = v.sk_code if v else vorwahl_empf
    gewaehlt = {}
    if P:
        for k in karten:
            if str(k['s'].pk) in P.getlist('schluessel'):
                gewaehlt[k['s'].pk] = _zahl(P.get(f'anzahl_{k["s"].pk}'), 1)
    else:
        vor = request.GET.get('schluessel') or ''
        vor_einheit = request.GET.get('einheit') or ''
        for k in karten:
            if (vor.isdigit() and k['s'].pk == int(vor)) or \
                    (vor_einheit.isdigit() and k['s'].einheit_id == int(vor_einheit)):
                if k['verfuegbar']:
                    gewaehlt[k['s'].pk] = 1
    rueckgabe_bis = _datum(P.get('rueckgabe_bis')) if P else None
    if P:
        empf = sl.empfaenger_lesen(P.get('empfaenger'), lg, org)
        unterschrift = sl.unterschrift_lesen(P.get('unterschrift', ''))
        posten = [(k['s'], gewaehlt[k['s'].pk]) for k in karten if k['s'].pk in gewaehlt][:sl.MAX_POSTEN]
        if (P.get('rueckgabe_bis') or '').strip() and rueckgabe_bis is None:
            fehler = [gettext('«Zurück bis» ist kein gültiges Datum.')]
        else:
            fehler = sl.ausgabe_pruefen(lg, posten, empf, rueckgabe_bis, unterschrift, heute)
        if not fehler:
            neu, dok = sl.ausgeben(lg, posten, empf, rueckgabe_bis=rueckgabe_bis, unterschrift=unterschrift,
                                   unterschrift_name=_text(P, 'unterschrift_name', 120),
                                   notiz=P.get('notiz', ''), datum=heute, user=request.user)
            log_aktion(request, "Schlüssel ausgegeben", empf['name'],
                       ', '.join(f"{n} × {s.typ} {s.schluessel_nummer}" for s, n in posten),
                       ziel=empf.get('vertrag'))
            if dok is None:
                messages.warning(request, gettext('Die Ausgabe ist gebucht, die Quittung konnte aber nicht '
                                                  'abgelegt werden.'))
            text = gettext('%(n)s Schlüssel an %(name)s ausgegeben. Quittung in der Ablage.') % {
                'n': sum(a.anzahl for a in neu), 'name': empf['name']}
            return _fertig(request, _weiter(request, _lg_ziel(lg)), text)
        for f in fehler:
            messages.error(request, f)
    for k in karten:
        k['gewaehlt'] = k['s'].pk in gewaehlt
        k['stueck'] = gewaehlt.get(k['s'].pk, 1)
    embed = _embed(request)
    return render(request, 'fw/schluessel_ausgabe.html', {
        **_global_filter(request), 'nav': 'liegenschaften', 'lg': lg,
        'karten': karten, 'auswahl': auswahl, 'vorwahl_empf': vorwahl_empf,
        'rueckgabe_bis': (P.get('rueckgabe_bis') if P else '') or '',
        'notiz': (P.get('notiz') if P else '') or '',
        'unterschrift_name': (P.get('unterschrift_name') if P else '') or '',
        'heute_iso': heute.isoformat(), 'weiter': _weiter(request, ''),
        'embed_base': 'fw/base_embed.html' if embed else None, 'embed': embed,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_liegenschaft_schluessel_ruecknahme(request, pk):
    """Schlüssel zurücknehmen — je Ausgabe «zurück» oder «verloren», mit
    Unterschrift und Quittung. Ohne `?an=` zeigt die Seite, wer an dieser
    Liegenschaft Schlüssel hat."""
    lg = get_object_or_404(Liegenschaft.objects.select_related('organisation'), pk=pk)
    org = _organisation(request)
    heute = timezone.localdate()
    P = request.POST if request.method == 'POST' else None
    code = (P.get('an') if P else request.GET.get('an')) or ''
    empf = sl.empfaenger_lesen(code, lg, org) if code else None
    embed = _embed(request)
    basis = {**_global_filter(request), 'nav': 'liegenschaften', 'lg': lg,
             'embed_base': 'fw/base_embed.html' if embed else None, 'embed': embed,
             'weiter': _weiter(request, '')}
    if empf is None:
        inhaber = {}
        for a in (SchluesselAusgabe.objects.filter(schluessel__liegenschaft=lg, status='ausgegeben')
                  .select_related('schluessel', 'mieter', 'handwerker', 'benutzer', 'vertrag__einheit')
                  .order_by('ausgegeben_am', 'id')):
            eintrag = inhaber.setdefault(sl.empfaenger_code(a), {'name': a.empfaenger_name, 'a': a,
                                                                   'stueck': 0, 'ueberfaellig': False})
            eintrag['stueck'] += a.anzahl
            if a.rueckgabe_bis and a.rueckgabe_bis < heute:
                eintrag['ueberfaellig'] = True
        if code:
            messages.error(request, gettext('Diesen Empfänger gibt es an dieser Liegenschaft nicht.'))
        return render(request, 'fw/schluessel_ruecknahme.html', {
            **basis, 'empf': None, 'inhaber': [{'code': c, **e} for c, e in inhaber.items()]})
    offene = list(sl.ausgaben_von(empf, lg).filter(status='ausgegeben')
                  .select_related('schluessel__einheit').prefetch_related('schluessel__oeffnet')
                  .order_by('schluessel__typ', 'id'))
    for a in offene:
        a.kuerzel = sl.kuerzel(a.schluessel)
        a.ueberfaellig = bool(a.rueckgabe_bis and a.rueckgabe_bis < heute)
        a.wahl = (P.get(f'status_{a.pk}') if P else '') or ''
        a.verloren_n = _zahl(P.get(f'verloren_{a.pk}'), 0) if P else 0
    if P:
        posten = []
        for a in offene:
            if a.wahl == 'zurueck':
                v = min(a.verloren_n, a.anzahl - 1) if a.anzahl > 1 else 0
                posten.append((a, a.anzahl - v, v))
            elif a.wahl == 'verloren':
                posten.append((a, 0, a.anzahl))
        unterschrift = sl.unterschrift_lesen(P.get('unterschrift', ''))
        fehler = sl.ruecknahme_pruefen(posten, unterschrift)
        if not fehler:
            verluste, dok = sl.zuruecknehmen(lg, posten, empf, unterschrift=unterschrift,
                                             unterschrift_name=_text(P, 'unterschrift_name', 120),
                                             notiz=P.get('notiz', ''), datum=heute, user=request.user)
            log_aktion(request, "Schlüssel zurückgenommen", empf['name'],
                       ', '.join(f"{z}/{v} × {a.schluessel.typ} {a.schluessel.schluessel_nummer}"
                                 for a, z, v in posten), ziel=empf.get('vertrag'))
            if dok is None:
                messages.warning(request, gettext('Die Rücknahme ist gebucht, die Quittung konnte aber nicht '
                                                  'abgelegt werden.'))
            text = gettext('Rücknahme gebucht. Quittung in der Ablage.')
            if verluste:
                text += ' ' + gettext('%(n)s Verlust(e): Pendenz «Zylinder ersetzen» angelegt.') % {'n': len(verluste)}
            return _fertig(request, _weiter(request, _lg_ziel(lg)), text)
        for f in fehler:
            messages.error(request, f)
    return render(request, 'fw/schluessel_ruecknahme.html', {
        **basis, 'empf': empf, 'offene': offene,
        'notiz': (P.get('notiz') if P else '') or '',
        'unterschrift_name': (P.get('unterschrift_name') if P else '') or '',
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_schluessel_faellig(request):
    """Alle Schlüssel, deren Rückgabefrist erreicht ist — über alle
    Liegenschaften oder gefiltert mit `?lg=`. Ziel der Kachel «Schlüssel»."""
    basis = _global_filter(request)
    heute = timezone.localdate()
    liste = list(sl.faellige(heute, basis.get('aktive_lg')))
    for a in liste:
        a.kuerzel = sl.kuerzel(a.schluessel)
        a.tage = (heute - a.rueckgabe_bis).days
        a.ruecknahme_url = sl.ruecknahme_url(a)
    return render(request, 'fw/schluessel_faellig.html', {
        **basis, 'nav': 'liegenschaften', 'liste': liste, 'heute': heute})
