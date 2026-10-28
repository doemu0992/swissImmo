# core/views/fw/zahlungsklaerung.py
#
# Zahlungs-Cockpit V12 (26.10.2026): Assistent «Zahlung aufteilen» (Split-Screen),
# Suche offener Posten, Kaution erkennen, Klärungsnotiz, Verwendung eines
# Guthabens. Die Buchungslogik liegt in core/services/zahlungsklaerung.py; hier
# stehen nur Eingabe, Rechteprüfung und Rücksprung.

from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext, ngettext

from core.auth import (ROLLE_VERWALTER, SCHREIB_ROLLEN, VERWALTUNGS_ROLLEN, hat_rolle, log_aktion,
                       rolle_erforderlich)
from finance.models import DebitorenRechnung, Zahlungseingang
from rentals.models import Mietvertrag

from ._basis import _global_filter
from .bankabgleich import _ziel
from finance.booking import bankkonten as bankkonten_der_verwaltung, bank_nr_aus_eingabe


def _geparkt(zahlung):
    return (zahlung.status == 'verbucht' and zahlung.konto_id
            and zahlung.konto.nummer in ('1190', '2030'))


def _herkunft(zahlung):
    """(Absender, Mitteilung, Referenz, geraten) aus der Auszugszeile."""
    from core.services import zahler as _zahler
    bew = zahlung.bankbewegungen.first()
    roh = (bew.text if bew else '') or ''
    if not roh:
        t = (zahlung.bemerkung or '').split('UNGEKLÄRT:', 1)
        roh = (t[1] if len(t) > 1 else '').strip()
    name, rest, geraten = _zahler.aus_bewegung((bew.gegenpartei if bew else ''), roh)
    return name, rest, ((bew.referenz if bew else '') or '').strip(), geraten


def _vorbefuellen(zahlung, gruppen, vorschlaege):
    """Vorschlag für die Zuteilung: Posten des ersten Vorschlags (bzw. des
    Guthaben-Mieters), älteste Fälligkeit zuerst (Art. 87 OR), bis der Betrag
    verteilt ist. Passt der Betrag genau auf einen Posten, nur dieser.

    Vorbefüllt wird nur, wenn Referenz, gelernter Absender oder Name den Mieter
    belegen. Passt nur der Betrag, bleibt alles leer — sonst landet die Zahlung
    eines Fremden mit einem Klick auf der Miete eines beliebigen Mieters, der
    zufällig gleich viel schuldet (Korrektur 26.10.2026)."""
    if zahlung.vertrag_id:
        ziel_ids = [r.pk for g in gruppen for r in (p['r'] for p in g['posten'])
                    if r.vertrag_id == zahlung.vertrag_id]
    elif any(v.get('zusammen') for v in vorschlaege):
        # Sammelzahlung mehrerer genannter Mieter: alle ihre Posten.
        ziel_ids = [r.pk for v in vorschlaege if v.get('zusammen') for r in v['rechnungen']]
    elif vorschlaege and vorschlaege[0].get('stark'):
        ziel_ids = [r.pk for r in vorschlaege[0]['rechnungen']]
    else:
        return {}
    alle = {p['r'].pk: p for g in gruppen for p in g['posten']}
    genau = [pk for pk in ziel_ids if pk in alle and alle[pk]['offen'] == zahlung.betrag]
    if genau:
        return {genau[0]: zahlung.betrag}
    rest = zahlung.betrag
    vorschlag = {}
    for pk in ziel_ids:
        if pk not in alle or rest <= 0:
            continue
        b = min(rest, alle[pk]['offen'])
        vorschlag[pk] = b
        rest -= b
    return vorschlag


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zahlung_aufteilen(request, pk):
    """Split-Screen-Assistent: links die Zahlung, rechts die offenen Posten.

    GET zeigt Vorschläge und Suchtreffer (mit `fragment=1` nur die Trefferliste
    für die Suche ohne Neuladen), POST bucht über `zahlungsklaerung.aufteilen`.
    """
    from core.services import zahlungsklaerung as zk

    zahlung = get_object_or_404(Zahlungseingang.objects.select_related('konto', 'vertrag__mieter',
                                                                       'vertrag__einheit__liegenschaft'),
                                pk=pk)
    ziel = _ziel(request)
    if not _geparkt(zahlung):
        messages.info(request, gettext('Diese Zahlung ist bereits zugeordnet oder storniert.'))
        return redirect(ziel)

    if request.method == 'POST':
        return _aufteilen_buchen(request, zahlung, ziel)

    absender, mitteilung, referenz, geraten = _herkunft(zahlung)
    vorschl = [] if zahlung.vertrag_id else zk.vorschlaege(
        zahlung, absender=absender, mitteilung=mitteilung, referenz=referenz)
    q = (request.GET.get('q') or '').strip()
    vertrag_ids = ([zahlung.vertrag_id] if zahlung.vertrag_id
                   else [v['vertrag'].id for v in vorschl])
    posten = zk.suche_posten(q, vertrag_ids=vertrag_ids)
    if zahlung.vertrag_id:
        # Ein Guthaben gehört einem Mieter — nur dessen Posten.
        posten = [r for r in posten if r.vertrag_id == zahlung.vertrag_id]
    gruppen = zk.gruppiert(posten)
    if request.GET.get('fragment'):
        return render(request, 'fw/_posten_gruppen.html', {'gruppen': gruppen, 'vorschlag': {}})

    vorschlag = {} if q else _vorbefuellen(zahlung, gruppen, vorschl)
    for g in gruppen:
        for p in g['posten']:
            p['vorschlag'] = vorschlag.get(p['r'].pk)
    # Für den Rest als Guthaben: die Mieter, die gerade in der Auswahl stehen.
    rest_vertraege = [g['vertrag'] for g in gruppen]
    if zahlung.vertrag_id and zahlung.vertrag not in rest_vertraege:
        rest_vertraege.insert(0, zahlung.vertrag)
    from finance.models import Buchungskonto
    return render(request, 'fw/zahlung_aufteilen.html', {
        **_global_filter(request), 'nav': 'bankabgleich',
        'z': zahlung, 'ist_guthaben': zahlung.konto.nummer == '2030',
        'absender': absender, 'absender_geraten': geraten, 'mitteilung': mitteilung,
        'referenz': referenz, 'tage': zk.tage_ungeklaert(zahlung),
        'vorschlaege': vorschl, 'gruppen': gruppen, 'q': q, 'vorschlag': vorschlag,
        'vorschlag_summe': sum(vorschlag.values(), Decimal('0.00')),
        'rest_vertraege': rest_vertraege,
        'darf_zurueck': hat_rolle(request.user, (ROLLE_VERWALTER,)),
        'bankkonten': bankkonten_der_verwaltung(),
        'ziel': ziel,
    })


def _aufteilen_buchen(request, zahlung, ziel):
    from core.services import zahlungsklaerung as zk
    from core.services.zahlungszuordnung import ZuordnungsFehler

    zurueck = f"/neu/bankabgleich/zahlung/{zahlung.pk}/aufteilen/"
    teile_roh = []
    for key, wert in request.POST.items():
        if not key.startswith('teil_') or not key[5:].isdigit():
            continue
        b = zk.betrag_aus(wert)
        if wert.strip() and b is None:
            messages.error(request, gettext('Ungültiger Betrag «%(raw)s».') % {'raw': wert})
            return redirect(zurueck)
        if b:
            teile_roh.append((int(key[5:]), b))
    rest_ziel = request.POST.get('rest_ziel') or 'offen'
    if rest_ziel == 'zurueck' and not hat_rolle(request.user, (ROLLE_VERWALTER,)):
        messages.error(request, gettext('Zurücküberweisen dürfen nur Verwalter und Inhaber.'))
        return redirect(zurueck)
    try:
        with transaction.atomic():
            z = (Zahlungseingang.objects.select_for_update(of=('self',))
                 .select_related('konto', 'vertrag').get(pk=zahlung.pk))
            rechnungen = {r.pk: r for r in DebitorenRechnung.objects.select_for_update(of=('self',))
                          .filter(pk__in=[i for i, _b in teile_roh])
                          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft')}
            if len(rechnungen) != len({i for i, _b in teile_roh}):
                raise ZuordnungsFehler(gettext('Eine gewählte Rechnung gibt es nicht (mehr).'))
            # Reihenfolge wie angezeigt: älteste Fälligkeit zuerst.
            teile = sorted(((rechnungen[i], b) for i, b in teile_roh),
                           key=lambda t: (t[0].faellig_am or t[0].datum, t[0].pk))
            rest_vertrag = None
            if rest_ziel == 'guthaben':
                rest_vertrag = (Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft')
                                .filter(pk=request.POST.get('rest_vertrag') or 0).first())
            erg = zk.aufteilen(z, teile, rest_ziel=rest_ziel, rest_vertrag=rest_vertrag,
                               bank_nr=bank_nr_aus_eingabe(request.POST.get('bank_konto')),
                               user=request.user)
    except ZuordnungsFehler as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(zurueck)
    except PermissionError as exc:
        messages.error(request, gettext('Periodensperre: %(e)s') % {'e': exc})
        return redirect(zurueck)

    log_aktion(request, "Zahlung aufgeteilt", f"Zahlung #{zahlung.pk}",
               f"CHF {erg['summe']} auf {erg['teile']} Posten, Rest CHF {erg['rest']} ({erg['rest_ziel']})")
    teile_txt = gettext('CHF %(summe)s auf %(n)s Posten verbucht') % {'summe': erg['summe'], 'n': erg['teile']}
    if erg['rest'] > 0:
        rest_txt = {
            'offen': gettext('Rest CHF %(rest)s bleibt ungeklärt'),
            'guthaben': gettext('Rest CHF %(rest)s als Guthaben'),
            'zurueck': gettext('Rest CHF %(rest)s zurücküberwiesen'),
        }[erg['rest_ziel']] % {'rest': erg['rest']}
        teile_txt = f"{teile_txt} · {rest_txt}" if erg['teile'] else rest_txt
    messages.success(request, '✅ ' + teile_txt + '.')
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zahlung_kaution(request, pk):
    """Ungeklärte Zahlung (1190) als Kaution eines Vertrags erkennen."""
    from core.services.zahlungsklaerung import als_kaution
    from core.services.zahlungszuordnung import ZuordnungsFehler
    ziel = _ziel(request)
    if request.method != 'POST':
        return redirect(ziel)
    try:
        with transaction.atomic():
            z = get_object_or_404(Zahlungseingang.objects.select_for_update(of=('self',))
                                  .select_related('konto'), pk=pk)
            v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'),
                                  pk=request.POST.get('vertrag_id') or 0)
            als_kaution(z, v, user=request.user)
    except ZuordnungsFehler as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(ziel)
    except PermissionError as exc:
        messages.error(request, gettext('Periodensperre: %(e)s') % {'e': exc})
        return redirect(ziel)
    log_aktion(request, "Zahlung als Kaution erkannt", str(v.mieter), f"CHF {z.betrag} (1190 an 2010)", ziel=v)
    messages.success(request, '✅ ' + gettext('CHF %(betrag)s als Kaution von %(mieter)s verbucht. Eine Pendenz erinnert an die Überweisung auf das Sperrkonto.') % {'betrag': z.betrag, 'mieter': v.mieter.display_name})
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zahlung_notiz(request, pk):
    """Klärungsnotiz an einer ungeklärten Zahlung."""
    ziel = _ziel(request)
    if request.method != 'POST':
        return redirect(ziel)
    z = get_object_or_404(Zahlungseingang, pk=pk)
    z.klaerung_notiz = (request.POST.get('notiz') or '').strip()[:255]
    z.save(update_fields=['klaerung_notiz'])
    messages.success(request, gettext('Notiz gespeichert.'))
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_guthaben_verwendung(request, pk):
    """Wofür ein Mieterguthaben (2030) gedacht ist."""
    ziel = _ziel(request)
    if request.method != 'POST':
        return redirect(ziel)
    z = get_object_or_404(Zahlungseingang.objects.select_related('konto'), pk=pk)
    wert = request.POST.get('verwendung')
    if (z.status != 'verbucht' or not z.konto_id or z.konto.nummer != '2030'
            or wert not in dict(Zahlungseingang.GUTHABEN_VERWENDUNG)):
        messages.error(request, gettext('Nur für ein Mieterguthaben (Konto 2030).'))
        return redirect(ziel)
    z.guthaben_verwendung = wert
    z.save(update_fields=['guthaben_verwendung'])
    messages.success(request, gettext('Guthaben: %(wert)s.') % {'wert': z.get_guthaben_verwendung_display()})
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_verrechnung_rueckgaengig(request, pk):
    """Nur die Verrechnung eines Guthabens aufheben — der Geldeingang bleibt."""
    from core.services.zahlungsklaerung import verrechnung_rueckgaengig
    from core.services.zahlungszuordnung import ZuordnungsFehler
    ziel = _ziel(request)
    if request.method != 'POST':
        return redirect(ziel)
    try:
        with transaction.atomic():
            z = get_object_or_404(Zahlungseingang.objects.select_for_update(of=('self',)), pk=pk)
            rechnung = verrechnung_rueckgaengig(z, user=request.user)
    except ZuordnungsFehler as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(ziel)
    except PermissionError as exc:
        messages.error(request, gettext('Periodensperre: %(e)s') % {'e': exc})
        return redirect(ziel)
    log_aktion(request, "Verrechnung eines Guthabens rückgängig", str(z.vertrag),
               f"CHF {z.betrag} wieder auf 2030" + (f", {rechnung.titel} wieder offen" if rechnung else ''),
               ziel=z.vertrag)
    messages.success(request, '✅ ' + gettext('Verrechnung aufgehoben: CHF %(betrag)s stehen wieder als Guthaben, «%(titel)s» ist wieder offen.') % {
        'betrag': z.betrag, 'titel': rechnung.titel if rechnung else '—'})
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zuordnung_aufheben(request, pk):
    """Eine falsch zugeordnete Bankzahlung zurück in die Klärungsfälle — der
    Geldeingang bleibt, nur die Zuordnung fällt weg (anders als «Stornieren»)."""
    from core.services.zahlungsklaerung import zuordnung_aufheben
    from core.services.zahlungszuordnung import ZuordnungsFehler
    ziel = _ziel(request)
    if request.method != 'POST':
        return redirect(ziel)
    z = get_object_or_404(Zahlungseingang, pk=pk)
    try:
        zahlung, n, vergessen = zuordnung_aufheben(z, user=request.user)
    except ZuordnungsFehler as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(ziel)
    except PermissionError as exc:
        messages.error(request, gettext('Periodensperre: %(e)s') % {'e': exc})
        return redirect(ziel)
    text = ngettext('Zuordnung aufgehoben: CHF %(betrag)s sind wieder ein Klärungsfall, %(n)s Rechnung ist wieder offen.',
                    'Zuordnung aufgehoben: CHF %(betrag)s sind wieder ein Klärungsfall, %(n)s Rechnungen sind wieder offen.',
                    n) % {'betrag': zahlung.betrag, 'n': n}
    if vergessen:
        text += ' ' + gettext('Der Absender «%(name)s» ist vergessen und wird nicht mehr automatisch zugeordnet.') % {'name': vergessen}
    messages.success(request, '✅ ' + text)
    return redirect(ziel)


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_guthaben_wiederherstellen(request, pk):
    """Den Eingang einer samt Zuordnung stornierten Zahlung wiederherstellen —
    als Guthaben (2030) oder als Klärungsfall (1190)."""
    from core.services.zahlungsklaerung import guthaben_wiederherstellen
    from core.services.zahlungszuordnung import ZuordnungsFehler
    ziel = _ziel(request)
    if request.method != 'POST':
        return redirect(ziel)
    try:
        with transaction.atomic():
            z = get_object_or_404(Zahlungseingang.objects.select_for_update(of=('self',)), pk=pk)
            neu = guthaben_wiederherstellen(z, user=request.user)
    except ZuordnungsFehler as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(ziel)
    except PermissionError as exc:
        messages.error(request, gettext('Periodensperre: %(e)s') % {'e': exc})
        return redirect(ziel)
    log_aktion(request, "Storniertes Guthaben wiederhergestellt", str(z.vertrag),
               f"Zahlung #{z.pk} → neues Guthaben #{neu.pk}, CHF {neu.betrag}", ziel=z.vertrag)
    if neu.vertrag_id:
        messages.success(request, '✅ ' + gettext('Guthaben von CHF %(betrag)s wiederhergestellt (2030, «offen lassen»). Die damit verrechneten Posten sind wieder offen.') % {'betrag': neu.betrag})
    else:
        messages.success(request, '✅ ' + gettext('Zahlung von CHF %(betrag)s wiederhergestellt — sie steht wieder unter «Klärungsfälle» und kann richtig zugeordnet werden.') % {'betrag': neu.betrag})
    return redirect(ziel)
