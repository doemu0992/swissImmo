# core/views/fw/kreditoren_aktionen.py
#
# Kreditoren anlegen, scannen, bearbeiten, freigeben, loeschen; Positionen.
# Aus aktionen.py herausgeloest (reiner Umzug ohne Aenderung am Code).

from decimal import Decimal

from django.utils.translation import gettext
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER)
from core.auth import FINANZ_SCHREIB_ROLLEN, FINANZ_VERWALTUNGS_ROLLEN
from core.services.iban import formatiere_iban, ist_gueltige_iban, normalisiere_iban
from portfolio.models import Einheit, Liegenschaft


from ._basis import (_num)


# ============================================================
# CREATE-/ACTION-VIEWS: alles in /neu/ (ersetzt /app/-Links)
# ============================================================

@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
def fw_kreditor_neu(request):
    """Kreditorenrechnung erfassen (Status neu → im Kreditoren-Tab freigeben)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, Buchungskonto
    from core.auth import log_aktion
    from finance.forms import KreditorForm
    from .kreditoren import fw_kreditoren, formular_eingabe, formular_fehler
    if request.method != 'POST':
        return redirect('fw_kreditoren')

    # Audit Etappe 2: Prüfen statt raten. Vorher war ein unlesbares Datum ein
    # Serverfehler, ein unlesbarer MWST-Satz still 0 %.
    form = KreditorForm(request.POST, erfassen=True)
    feld_fehler = {}
    lg = None
    if request.POST.get('liegenschaft_id'):
        lg = Liegenschaft.objects.filter(id=request.POST['liegenschaft_id']).first() \
            if request.POST['liegenschaft_id'].isdigit() else None
        if lg is None:
            feld_fehler['liegenschaft_id'] = gettext('Diese Liegenschaft ist nicht (mehr) erfasst.')
    konto = None
    if request.POST.get('konto_id'):
        konto = Buchungskonto.objects.filter(id=request.POST['konto_id']).first() \
            if request.POST['konto_id'].isdigit() else None
        if konto is None:
            feld_fehler['konto_id'] = gettext('Dieses Konto ist nicht (mehr) erfasst.')
    if not form.is_valid() or feld_fehler:
        return fw_kreditoren(request, formular={
            'neu_werte': formular_eingabe(request.POST),
            'neu_fehler': formular_fehler(form, feld_fehler)})
    c = form.cleaned_data
    lieferant, betrag = c['lieferant'].strip(), c['betrag']

    # Kein Konto gewählt? Aus Lieferanten-Gedächtnis bzw. Schlüsselwörtern vorschlagen
    # (setzt darüber auch die HNK-Relevanz — is_hnk_relevant leitet unten aus dem Konto ab).
    if konto is None:
        from finance.lieferanten import lieferant_vorschlag, konto_aus_text
        from finance.booking import konto as _konto
        _vp = lieferant_vorschlag(lieferant)
        if _vp and _vp.standard_konto_id:
            konto = _vp.standard_konto
        else:
            _nr = konto_aus_text(lieferant)
            if _nr:
                konto = _konto(_nr)

    # Anschrift für die Zahlungsdatei: wie eingegeben, sonst die gelernte des
    # Lieferanten (Profil). Nichts davon wird geraten.
    from finance.kreditor_adresse import (FELDER as _ADR, adresse_von_profil,
                                          iban_abweichung, iban_meldung)
    from finance.lieferanten import lieferant_vorschlag
    _profil = lieferant_vorschlag(lieferant)
    adresse = {f: c[f'lieferant_{f}'] for f in _ADR}
    if not adresse['ort'] and _profil and _profil.ort:
        adresse = adresse_von_profil(_profil)

    kr = KreditorenRechnung.objects.create(
        lieferant=lieferant, betrag=betrag,
        lieferant_strasse=adresse['strasse'], lieferant_hausnummer=adresse['hausnummer'],
        lieferant_plz=adresse['plz'], lieferant_ort=adresse['ort'],
        lieferant_land=adresse['land'] or 'CH',
        # Leer heisst «ohne MWST» (0 %), wie bisher. Unlesbar ist ein Feldfehler.
        mwst_satz=(c['mwst_satz'] if c['mwst_satz'] is not None else Decimal('0.0')),
        liegenschaft=lg, konto=konto,
        leistungs_von=c['leistungs_von'], leistungs_bis=c['leistungs_bis'],
        datum=c['datum'] or timezone.localdate(),
        faellig_am=c['faellig_am'],
        referenz=c['referenz'].strip(),
        menge_liter=c['menge_liter'],
        # IBAN wurde bisher nur im Bearbeiten-Formular erfasst — eine manuell
        # angelegte Rechnung konnte damit NIE in einen Zahllauf (Praxis-Audit).
        iban=c['iban'],
        # NK-relevant, wenn Checkbox gesetzt ODER das gewählte Konto HNK-relevant ist
        is_hnk_relevant=(request.POST.get('is_hnk_relevant') == 'on'
                         or bool(konto and konto.is_hnk_relevant)),
        status='neu',
    )
    if request.FILES.get('beleg_scan'):
        kr.beleg_scan = request.FILES['beleg_scan']
        kr.save()
    log_aktion(request, "Kreditorenrechnung erfasst", lieferant, f"CHF {betrag}")
    messages.success(request, '✅ ' + gettext("Kreditorenrechnung '%(lieferant)s' über CHF %(betrag)s erfasst (Status: Neu — bitte freigeben).") % {'lieferant': lieferant, 'betrag': betrag})
    _gelernt = iban_abweichung(kr, profil=_profil)
    if _gelernt:
        messages.warning(request, '⚠️ ' + iban_meldung(kr.iban, _gelernt))
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
def fw_kreditor_scan(request):
    """KI-Rechnungsscanner: Belege hochladen (auch MEHRERE gleichzeitig) → jeder
    wird DIREKT gescannt (Groq-KI, Vision für Foto-Belege, Regex-Fallback) und
    als Kreditorenrechnung (Status Neu) mit den erkannten Daten angelegt. Die
    Erkennungs-Methode wird ehrlich gemeldet; Werte sind per Klick auf die
    Zeile korrigierbar (Edit-Panel mit Beleg-Vorschau)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.services.belegimport import beleg_importieren
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kreditoren')

    dateien = request.FILES.getlist('beleg_scan')[:20]
    if not dateien:
        messages.error(request, gettext('Bitte mindestens einen Beleg (PDF oder Foto) auswählen.'))
        return redirect('fw_kreditoren')

    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    for datei in dateien:
        kr, daten = beleg_importieren(datei, liegenschaft=lg)
        methode = daten.get('methode')
        log_aktion(request, "Beleg gescannt (KI-Rechnungsscanner)",
                   kr.lieferant or datei.name, f"Methode: {methode} · CHF {kr.betrag or 0}")
        _kreditor_scan_meldung(request, kr, daten, datei.name)
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


def _kreditor_scan_meldung(request, kr, daten, dateiname):
    """Toast je gescanntem Beleg — Methode ehrlich ausweisen."""
    from django.contrib import messages
    methode = daten.get('methode')
    zusammenfassung = (f"«{kr.lieferant or 'Lieferant unbekannt'}»"
                       f"{f' · CHF {kr.betrag}' if kr.betrag else ''}"
                       f"{f' · {kr.datum.strftime(chr(37)+chr(100)+chr(46)+chr(37)+chr(109)+chr(46)+chr(37)+chr(89))}' if kr.datum else ''}")
    konto_hint = f" · Konto {daten['konto_auto']} automatisch zugeteilt" if daten.get('konto_auto') else ''
    if methode in ('ki', 'vision', 'qr'):
        messages.success(request, '🤖 ' + gettext('Beleg gescannt (%(get)s): %(zusammenfassung)s%(konto_hint)s — bitte prüfen und freigeben.') % {'get': daten.get('hinweis'), 'zusammenfassung': zusammenfassung, 'konto_hint': konto_hint})
    elif methode == 'regex':
        messages.warning(request, gettext('Beleg regelbasiert ausgelesen (KI nicht aktiv/erreichbar): %(zusammenfassung)s — bitte Werte prüfen.') % {'zusammenfassung': zusammenfassung})
    else:
        messages.warning(request, gettext('Beleg «%(dateiname)s» gespeichert, aber nicht auslesbar: %(get)s Werte bitte manuell ergänzen.') % {'dateiname': dateiname, 'get': daten.get('hinweis')})


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
def fw_kreditor_bearbeiten(request, pk):
    """Korrigiert eine noch nicht verbuchte Kreditorenrechnung (Status Neu) —
    v.a. zum Nachbessern gescannter Werte. Verbuchte Rechnungen sind gesperrt."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, Buchungskonto
    from core.auth import log_aktion
    k = get_object_or_404(KreditorenRechnung, id=pk)
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    if k.status != 'neu':
        messages.error(request, gettext('Nur unverbuchte Rechnungen (Status Neu) können bearbeitet werden.'))
        return redirect('fw_kreditoren')

    from finance.forms import KreditorForm
    from .kreditoren import fw_kreditoren, formular_eingabe, formular_fehler
    # Audit Etappe 2: Vorher wurde ein unlesbarer Betrag still leer, die IBAN
    # ungeprüft übernommen. Jetzt kommt die Zeile mit der Meldung zurück.
    form = KreditorForm(request.POST)
    feld_fehler = {}
    neue_lg, neues_konto = k.liegenschaft, k.konto
    if request.POST.get('liegenschaft_id'):
        neue_lg = Liegenschaft.objects.filter(id=request.POST['liegenschaft_id']).first() \
            if request.POST['liegenschaft_id'].isdigit() else None
        if neue_lg is None:
            feld_fehler['liegenschaft_id'] = gettext('Diese Liegenschaft ist nicht (mehr) erfasst.')
    if request.POST.get('konto_id'):
        neues_konto = Buchungskonto.objects.filter(id=request.POST['konto_id']).first() \
            if request.POST['konto_id'].isdigit() else None
        if neues_konto is None:
            feld_fehler['konto_id'] = gettext('Dieses Konto ist nicht (mehr) erfasst.')
    if not form.is_valid() or feld_fehler:
        return fw_kreditoren(request, formular={
            'bearb_id': k.id, 'bearb_werte': formular_eingabe(request.POST),
            'bearb_fehler': formular_fehler(form, feld_fehler)})
    c = form.cleaned_data
    k.lieferant = c['lieferant'].strip()
    k.betrag = c['betrag']
    k.datum = c['datum'] or k.datum
    k.faellig_am = c['faellig_am']
    k.leistungs_von = c['leistungs_von']
    k.leistungs_bis = c['leistungs_bis']
    k.referenz = c['referenz'].strip()
    k.menge_liter = c['menge_liter']
    alte_iban = k.iban
    k.iban = c['iban']
    from finance.kreditor_adresse import adresse_setzen, iban_abweichung, iban_meldung
    adresse_setzen(k, {f: c[f'lieferant_{f}'] for f in ('strasse', 'hausnummer', 'plz', 'ort', 'land')})
    k.liegenschaft = neue_lg
    k.konto = neues_konto
    # NK-Relevanz: Checkbox ODER (neu zugewiesenes) HNK-Konto
    k.is_hnk_relevant = (request.POST.get('is_hnk_relevant') == 'on'
                         or bool(k.konto and k.konto.is_hnk_relevant))
    k.fehlermeldung = ''
    k.save()
    log_aktion(request, "Kreditorenrechnung bearbeitet", k.lieferant, f"CHF {k.betrag or 0}")
    messages.success(request, '✅ ' + gettext('Rechnung «%(lieferant)s» aktualisiert.') % {'lieferant': k.lieferant})
    # Betrugsschutz: Eine geänderte Kontonummer fällt auf, bevor sie bezahlt wird
    # (FIN-09). Verglichen wird mit dem, was vorher an der Rechnung stand, und mit
    # dem gelernten Lieferantenprofil.
    if alte_iban and k.iban and normalisiere_iban(alte_iban) != normalisiere_iban(k.iban):
        log_aktion(request, "Kreditor-IBAN geändert", k.lieferant, f"{alte_iban} → {k.iban}")
        messages.warning(request, '⚠️ ' + gettext(
            'Die IBAN wurde geändert (vorher %(alt)s). Vor der Zahlung beim Lieferanten bestätigen lassen.') % {
            'alt': formatiere_iban(alte_iban)})
    _gelernt = iban_abweichung(k)
    if _gelernt:
        messages.warning(request, '⚠️ ' + iban_meldung(k.iban, _gelernt))
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_kreditor_freigeben(request, pk):
    """Kreditorenrechnung freigeben: bucht Aufwand (netto) an Kreditoren (2000)
    + Vorsteuer-Split (1170). Erfordert ein Aufwandskonto."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, Buchungskonto, Buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    k = get_object_or_404(KreditorenRechnung, id=pk)
    if k.status != 'neu':
        messages.info(request, gettext('Rechnung ist bereits freigegeben oder bezahlt.'))
        return redirect('fw_kreditoren')
    # Eigentümerfreigabe der Reparatur: eine Sperre, nicht nur eine Anzeige.
    from finance.freigabe import freigabe_sperre
    sperre = freigabe_sperre(k)
    if sperre:
        messages.error(request, f'⛔ {sperre}')
        return redirect('fw_kreditoren')

    # IBAN: Prüfsumme (Mod 97) und Abgleich mit dem gelernten Lieferantenprofil.
    # Eine KI-gelesene oder per Mail eingegangene IBAN wurde bisher ungeprüft
    # freigegeben und in die Zahlungsdatei übernommen (FIN-09).
    from finance.kreditor_adresse import (adresse_von_rechnung, aus_profil_uebernehmen,
                                          iban_abweichung, iban_meldung)
    if k.iban and not ist_gueltige_iban(k.iban):
        messages.error(request, '⛔ ' + gettext(
            'Die IBAN «%(iban)s» ist ungültig (Prüfziffer oder Länge). Bitte die Rechnung bearbeiten und die IBAN korrigieren.') % {
            'iban': k.iban})
        return redirect('fw_kreditoren')
    _gelernt = iban_abweichung(k)
    if _gelernt and request.POST.get('iban_bestaetigt') != '1':
        messages.error(request, '⛔ ' + iban_meldung(k.iban, _gelernt) + ' ' + gettext(
            'Freigabe erst nach Bestätigung: Kreuz «IBAN-Wechsel geprüft» in der Zeile setzen.'))
        return redirect('fw_kreditoren')

    # Aufwandskonto zuweisen (aus Formular oder bestehendes). Mit Kostenaufteilung
    # ist das Kopf-Konto optional — dann bucht jede Position ihr eigenes Konto.
    if request.POST.get('konto_id'):
        k.konto = Buchungskonto.objects.filter(id=request.POST['konto_id']).first()
    positionen = list(k.positionen.select_related('konto', 'liegenschaft'))
    if positionen:
        # Aufteilung muss aufgehen (Summe der Positionen == Rechnungsbetrag).
        if abs(k.positionen_differenz) > Decimal('0.01'):
            messages.error(request, gettext('Die Kostenaufteilung stimmt nicht: Summe der Positionen weicht um CHF %(positionen_differenz)s vom Rechnungsbetrag ab.') % {'positionen_differenz': k.positionen_differenz})
            return redirect('fw_kreditoren')
    elif not k.konto:
        messages.error(request, gettext('Bitte zuerst ein Aufwandskonto zuweisen (oder die Rechnung aufteilen).'))
        return redirect('fw_kreditoren')

    with transaction.atomic():
        # Zeilensperre + Re-Check gegen Doppelklick-Race: der Status-Check oben ist
        # ohne Lock — zwei parallele Requests würden sonst doppelten Aufwand buchen.
        gesperrt = KreditorenRechnung.objects.select_for_update().filter(id=k.id).first()
        if not gesperrt or gesperrt.status != 'neu':
            messages.info(request, gettext('Rechnung ist bereits freigegeben oder bezahlt.'))
            return redirect('fw_kreditoren')
        # NK-Relevanz automatisch vom Konto ableiten: HNK-Konto (4100–4140/4400)
        # ⇒ Rechnung fliesst in die Nebenkostenabrechnung — kein vergessenes
        # Häkchen mehr. (Nur aktivieren, nie eine manuelle Wahl deaktivieren.)
        if positionen and any(p.is_hnk_relevant for p in positionen) and not k.is_hnk_relevant:
            k.is_hnk_relevant = True
        elif k.konto and k.konto.is_hnk_relevant and not k.is_hnk_relevant:
            k.is_hnk_relevant = True
        k.status = 'freigegeben'
        # Fehlt die Anschrift, kommt die gelernte des Lieferanten (falls bekannt).
        aus_profil_uebernehmen(k)
        k.save()
        from finance.booking import buche
        datum_b = k.datum or timezone.localdate()
        brutto = k.betrag or Decimal('0.00')
        satz = k.mwst_satz or Decimal('0')

        def _netto(brutto_teil):
            if satz > 0:
                vs = (brutto_teil * satz / (Decimal('100') + satz)).quantize(Decimal('0.01'))
                return brutto_teil - vs, vs
            return brutto_teil, Decimal('0.00')

        vorsteuer_total = Decimal('0.00')
        if positionen:
            # Jede Position einzeln buchen (eigenes Konto/Objekt).
            for p in positionen:
                netto_p, vs_p = _netto(p.betrag)
                vorsteuer_total += vs_p
                text = f"Rechnung {k.lieferant}{f' · {p.bezeichnung}' if p.bezeichnung else ''}"
                buche(p.konto, "2000", netto_p, text[:255], datum=datum_b,
                      liegenschaft=p.liegenschaft or k.liegenschaft, kreditor=k, user=request.user)
        else:
            netto, vorsteuer_total = _netto(brutto)
            buche(k.konto, "2000", netto, f"Rechnung {k.lieferant} - {k.referenz}",
                  datum=datum_b, liegenschaft=k.liegenschaft, kreditor=k, user=request.user)
        if vorsteuer_total > 0:
            k.mwst_betrag = vorsteuer_total
            k.save(update_fields=['mwst_betrag'])
            buche("1170", "2000", vorsteuer_total, f"Vorsteuer {k.mwst_satz}% {k.lieferant}",
                  datum=datum_b, liegenschaft=k.liegenschaft, kreditor=k, user=request.user)
        # Lieferanten-Gedächtnis fortschreiben: dieses Konto wird künftig für
        # denselben Lieferanten automatisch vorgeschlagen.
        from finance.lieferanten import lerne_lieferant
        lerne_lieferant(k.lieferant, konto=k.konto, iban=k.iban, adresse=adresse_von_rechnung(k))
    if _gelernt:
        log_aktion(request, "Kreditor-IBAN-Wechsel bestätigt", k.lieferant,
                   f"{formatiere_iban(_gelernt)} → {formatiere_iban(k.iban)}")
    log_aktion(request, "Kreditorenrechnung freigegeben", k.lieferant, f"CHF {k.betrag}")
    messages.success(request, '✅ ' + gettext("'%(lieferant)s' freigegeben und verbucht.") % {'lieferant': k.lieferant})
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
def fw_kreditor_position_add(request, pk):
    """Fügt einer noch nicht verbuchten Kreditorenrechnung eine Kostenposition
    hinzu (Konto + optional Objekt + Betrag + HNK). Ermöglicht das Aufteilen
    einer Sammel-/Mischrechnung."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, KreditorPosition, Buchungskonto
    from core.auth import log_aktion
    k = get_object_or_404(KreditorenRechnung, id=pk)
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    if k.status != 'neu':
        messages.error(request, gettext('Nur unverbuchte Rechnungen (Status Neu) können aufgeteilt werden.'))
        return redirect('fw_kreditoren')
    konto = Buchungskonto.objects.filter(id=request.POST.get('konto_id') or None).first()
    try:
        betrag = Decimal(_num(request.POST.get('betrag')))
    except Exception:
        betrag = None
    if not konto or not betrag or betrag <= 0:
        messages.error(request, gettext('Konto und Betrag (> 0) sind für eine Position erforderlich.'))
        return redirect('fw_kreditoren')
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first() or k.liegenschaft
    einheit = Einheit.objects.filter(id=request.POST.get('einheit_id') or None).first()
    KreditorPosition.objects.create(
        rechnung=k, konto=konto, betrag=betrag,
        bezeichnung=(request.POST.get('bezeichnung') or '').strip()[:200],
        liegenschaft=lg, einheit=einheit,
        is_hnk_relevant=(request.POST.get('is_hnk_relevant') == 'on' or bool(konto.is_hnk_relevant)))
    log_aktion(request, "Kreditor-Position hinzugefügt", k.lieferant, f"{konto.nummer} · CHF {betrag}")
    messages.success(request, '✅ ' + gettext('Position %(nummer)s über CHF %(betrag)s hinzugefügt.') % {'nummer': konto.nummer, 'betrag': betrag})
    return redirect('/neu/kreditoren/')


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
def fw_kreditor_position_del(request, pk):
    """Entfernt eine Kostenposition (nur solange die Rechnung unverbucht ist)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorPosition
    p = get_object_or_404(KreditorPosition.objects.select_related('rechnung'), id=pk)
    if request.method == 'POST':
        if p.rechnung.status != 'neu':
            messages.error(request, gettext('Nur unverbuchte Rechnungen können geändert werden.'))
        else:
            p.delete()
            messages.success(request, gettext('Position entfernt.'))
    return redirect('/neu/kreditoren/')


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_kreditor_loeschen(request, pk):
    """Kreditorenrechnung löschen — NUR solange sie noch nicht verbucht ist
    (Status 'neu'). Verbuchte Rechnungen werden aus Revisionsgründen nicht
    gelöscht, sondern per Storno der Buchung rückgängig gemacht."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung
    from core.auth import log_aktion
    k = get_object_or_404(KreditorenRechnung, id=pk)
    if request.method == 'POST':
        if k.status != 'neu':
            messages.error(request, gettext('Bereits verbuchte Rechnung kann nicht gelöscht werden — bitte die zugehörige Buchung stornieren.'))
        else:
            lief = k.lieferant
            k.delete()
            log_aktion(request, "Kreditorenrechnung gelöscht", lief, '')
            messages.success(request, '🗑️ ' + gettext("Kreditorenrechnung '%(lief)s' gelöscht.") % {'lief': lief})
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)
