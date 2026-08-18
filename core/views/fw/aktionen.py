# core/views/fw/aktionen.py
#
# Anlegen, Bearbeiten, Loeschen und Buchen quer durch die Fachbereiche —
# der Block, den der urspruengliche Autor "alles in /neu/" genannt hat, weil
# er beim Ersetzen der /app/-Links entstand.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# 32 Views, thematisch gemischt (Kreditoren, Dienstleister, Assets,
# Dokumente, Nebenkosten, Buchungen, Zahlungszuordnung). Sie auf die
# fachlichen Module zu verteilen waere naheliegend — und genau das darf ein
# Umzugs-PR nicht: Dann waere nicht mehr pruefbar, ob nur verschoben wurde.
# Als eigener PR nach Etappe 1 sinnvoll.

import calendar as _calendar
import logging
import re
from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from crm.models import Mieter, Organisation
from finance.models import DebitorenRechnung, Zahlungseingang
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag

logger = logging.getLogger(__name__)

from ._basis import (_global_filter, _mwst_beleg, _mwst_bereits_verbucht,
                     _mwst_periode, _num)
from core.tenancy import aktuelle_organisation


# ============================================================
# CREATE-/ACTION-VIEWS: alles in /neu/ (ersetzt /app/-Links)
# ============================================================

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kreditor_neu(request):
    """Kreditorenrechnung erfassen (Status neu → im Kreditoren-Tab freigeben)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, Buchungskonto
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kreditoren')

    def _dec(name):
        raw = _num(request.POST.get(name))
        try:
            return Decimal(raw) if raw else None
        except Exception:
            return None

    lieferant = (request.POST.get('lieferant') or '').strip()
    betrag = _dec('betrag')
    if not lieferant or not betrag or betrag <= 0:
        messages.error(request, "Lieferant und Betrag (> 0) sind erforderlich.")
        return redirect('fw_kreditoren')

    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    konto = Buchungskonto.objects.filter(id=request.POST.get('konto_id') or None).first() if request.POST.get('konto_id') else None
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

    def _dat_iso(name):
        try:
            return date.fromisoformat(request.POST.get(name) or '')
        except ValueError:
            return None
    kr = KreditorenRechnung.objects.create(
        lieferant=lieferant, betrag=betrag, mwst_satz=(_dec('mwst_satz') or Decimal('0.0')),
        liegenschaft=lg, konto=konto,
        leistungs_von=_dat_iso('leistungs_von'), leistungs_bis=_dat_iso('leistungs_bis'),
        datum=(date.fromisoformat(request.POST['datum']) if request.POST.get('datum') else timezone.localdate()),
        faellig_am=(date.fromisoformat(request.POST['faellig_am']) if request.POST.get('faellig_am') else None),
        referenz=(request.POST.get('referenz') or '').strip(),
        # IBAN wurde bisher nur im Bearbeiten-Formular erfasst — eine manuell
        # angelegte Rechnung konnte damit NIE in einen Zahllauf (Praxis-Audit).
        iban=(request.POST.get('iban') or '').strip().replace(' ', ''),
        # NK-relevant, wenn Checkbox gesetzt ODER das gewählte Konto HNK-relevant ist
        is_hnk_relevant=(request.POST.get('is_hnk_relevant') == 'on'
                         or bool(konto and konto.is_hnk_relevant)),
        status='neu',
    )
    if request.FILES.get('beleg_scan'):
        kr.beleg_scan = request.FILES['beleg_scan']
        kr.save()
    log_aktion(request, "Kreditorenrechnung erfasst", lieferant, f"CHF {betrag}")
    messages.success(request, f"✅ Kreditorenrechnung '{lieferant}' über CHF {betrag} erfasst (Status: Neu — bitte freigeben).")
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
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
        messages.error(request, "Bitte mindestens einen Beleg (PDF oder Foto) auswählen.")
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
        messages.success(request, f"🤖 Beleg gescannt ({daten.get('hinweis')}): {zusammenfassung}{konto_hint} — bitte prüfen und freigeben.")
    elif methode == 'regex':
        messages.warning(request, f"Beleg regelbasiert ausgelesen (KI nicht aktiv/erreichbar): {zusammenfassung} — bitte Werte prüfen.")
    else:
        messages.warning(request, f"Beleg «{dateiname}» gespeichert, aber nicht auslesbar: {daten.get('hinweis')} Werte bitte manuell ergänzen.")


@rolle_erforderlich(*SCHREIB_ROLLEN)
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
        messages.error(request, "Nur unverbuchte Rechnungen (Status Neu) können bearbeitet werden.")
        return redirect('fw_kreditoren')

    def _dec(name):
        raw = _num(request.POST.get(name))
        try:
            return Decimal(raw) if raw else None
        except Exception:
            return None

    def _dat(name):
        try:
            return date.fromisoformat(request.POST.get(name) or '')
        except ValueError:
            return None

    k.lieferant = (request.POST.get('lieferant') or '').strip()
    betrag = _dec('betrag')
    k.betrag = betrag if betrag and betrag > 0 else None
    k.datum = _dat('datum') or k.datum
    k.faellig_am = _dat('faellig_am')
    k.leistungs_von = _dat('leistungs_von')
    k.leistungs_bis = _dat('leistungs_bis')
    k.referenz = (request.POST.get('referenz') or '').strip()
    k.iban = re.sub(r'\s+', '', request.POST.get('iban') or '')[:50]
    if request.POST.get('liegenschaft_id'):
        k.liegenschaft = Liegenschaft.objects.filter(id=request.POST['liegenschaft_id']).first()
    if request.POST.get('konto_id'):
        k.konto = Buchungskonto.objects.filter(id=request.POST['konto_id']).first()
    # NK-Relevanz: Checkbox ODER (neu zugewiesenes) HNK-Konto
    k.is_hnk_relevant = (request.POST.get('is_hnk_relevant') == 'on'
                         or bool(k.konto and k.konto.is_hnk_relevant))
    k.fehlermeldung = ''
    k.save()
    log_aktion(request, "Kreditorenrechnung bearbeitet", k.lieferant, f"CHF {k.betrag or 0}")
    messages.success(request, f"✅ Rechnung «{k.lieferant}» aktualisiert.")
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTER)
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
        messages.info(request, "Rechnung ist bereits freigegeben oder bezahlt.")
        return redirect('fw_kreditoren')

    # Aufwandskonto zuweisen (aus Formular oder bestehendes). Mit Kostenaufteilung
    # ist das Kopf-Konto optional — dann bucht jede Position ihr eigenes Konto.
    if request.POST.get('konto_id'):
        k.konto = Buchungskonto.objects.filter(id=request.POST['konto_id']).first()
    positionen = list(k.positionen.select_related('konto', 'liegenschaft'))
    if positionen:
        # Aufteilung muss aufgehen (Summe der Positionen == Rechnungsbetrag).
        if abs(k.positionen_differenz) > Decimal('0.01'):
            messages.error(request, f"Die Kostenaufteilung stimmt nicht: Summe der Positionen "
                                    f"weicht um CHF {k.positionen_differenz} vom Rechnungsbetrag ab.")
            return redirect('fw_kreditoren')
    elif not k.konto:
        messages.error(request, "Bitte zuerst ein Aufwandskonto zuweisen (oder die Rechnung aufteilen).")
        return redirect('fw_kreditoren')

    with transaction.atomic():
        # Zeilensperre + Re-Check gegen Doppelklick-Race: der Status-Check oben ist
        # ohne Lock — zwei parallele Requests würden sonst doppelten Aufwand buchen.
        gesperrt = KreditorenRechnung.objects.select_for_update().filter(id=k.id).first()
        if not gesperrt or gesperrt.status != 'neu':
            messages.info(request, "Rechnung ist bereits freigegeben oder bezahlt.")
            return redirect('fw_kreditoren')
        # NK-Relevanz automatisch vom Konto ableiten: HNK-Konto (4100–4140/4400)
        # ⇒ Rechnung fliesst in die Nebenkostenabrechnung — kein vergessenes
        # Häkchen mehr. (Nur aktivieren, nie eine manuelle Wahl deaktivieren.)
        if positionen and any(p.is_hnk_relevant for p in positionen) and not k.is_hnk_relevant:
            k.is_hnk_relevant = True
        elif k.konto and k.konto.is_hnk_relevant and not k.is_hnk_relevant:
            k.is_hnk_relevant = True
        k.status = 'freigegeben'
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
        lerne_lieferant(k.lieferant, konto=k.konto, iban=k.iban)
    log_aktion(request, "Kreditorenrechnung freigegeben", k.lieferant, f"CHF {k.betrag}")
    messages.success(request, f"✅ '{k.lieferant}' freigegeben und verbucht.")
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


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
        messages.error(request, "Gültig-ab-Datum, Netto und NK (≥ 0) sind erforderlich.")
        return redirect(ziel)
    # Rabatt/Erlass (Option B): mindert nur die Verrechnung, nicht die Referenz.
    # "mietzinsfrei" = Nettomietzins voll erlassen → Rabatt = Netto-Referenz.
    if request.POST.get('mietzinsfrei'):
        rabatt_netto = netto
    else:
        rabatt_netto = _dec('rabatt_netto') or Decimal('0.00')
    rabatt_nk = _dec('rabatt_nk') or Decimal('0.00')
    if rabatt_netto < 0 or rabatt_nk < 0:
        messages.error(request, "Rabatt-Werte dürfen nicht negativ sein.")
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
    messages.success(request, f"✅ Komponente ab {gab:%d.%m.%Y} gespeichert "
                     f"(Referenz CHF {netto + nk}, zu zahlen CHF {zu_zahlen}).")
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
        messages.success(request, "Komponente entfernt.")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
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
        messages.error(request, "Nur unverbuchte Rechnungen (Status Neu) können aufgeteilt werden.")
        return redirect('fw_kreditoren')
    konto = Buchungskonto.objects.filter(id=request.POST.get('konto_id') or None).first()
    try:
        betrag = Decimal(_num(request.POST.get('betrag')))
    except Exception:
        betrag = None
    if not konto or not betrag or betrag <= 0:
        messages.error(request, "Konto und Betrag (> 0) sind für eine Position erforderlich.")
        return redirect('fw_kreditoren')
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first() or k.liegenschaft
    einheit = Einheit.objects.filter(id=request.POST.get('einheit_id') or None).first()
    KreditorPosition.objects.create(
        rechnung=k, konto=konto, betrag=betrag,
        bezeichnung=(request.POST.get('bezeichnung') or '').strip()[:200],
        liegenschaft=lg, einheit=einheit,
        is_hnk_relevant=(request.POST.get('is_hnk_relevant') == 'on' or bool(konto.is_hnk_relevant)))
    log_aktion(request, "Kreditor-Position hinzugefügt", k.lieferant, f"{konto.nummer} · CHF {betrag}")
    messages.success(request, f"✅ Position {konto.nummer} über CHF {betrag} hinzugefügt.")
    return redirect('/neu/kreditoren/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kreditor_position_del(request, pk):
    """Entfernt eine Kostenposition (nur solange die Rechnung unverbucht ist)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorPosition
    p = get_object_or_404(KreditorPosition.objects.select_related('rechnung'), id=pk)
    if request.method == 'POST':
        if p.rechnung.status != 'neu':
            messages.error(request, "Nur unverbuchte Rechnungen können geändert werden.")
        else:
            p.delete()
            messages.success(request, "Position entfernt.")
    return redirect('/neu/kreditoren/')


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
        messages.error(request, "Firma ist erforderlich.")
        return redirect('fw_dienstleister')
    Handwerker.objects.create(
        firma=firma, branche=request.POST.get('branche', 'allgemein'),
        kontaktperson=(request.POST.get('kontaktperson') or '').strip(),
        email=(request.POST.get('email') or '').strip(),
        telefon=(request.POST.get('telefon') or '').strip(),
    )
    log_aktion(request, "Dienstleister erfasst", firma, '')
    messages.success(request, f"✅ Dienstleister '{firma}' erfasst.")
    return redirect('fw_dienstleister')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_asset_neu(request):
    """Gerät / Asset erfassen (Portfolio)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet, Einheit
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_assets')
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    if not lg:
        messages.error(request, "Liegenschaft ist erforderlich.")
        return redirect('fw_assets')
    g = Geraet.objects.create(
        liegenschaft=lg,
        einheit=Einheit.objects.filter(id=request.POST.get('einheit_id') or None).first() if request.POST.get('einheit_id') else None,
        kategorie=request.POST.get('kategorie', 'sonstiges'),
        sonstiges_bezeichnung=(request.POST.get('sonstiges_bezeichnung') or '').strip(),
        marke=(request.POST.get('marke') or '').strip(),
        modell=(request.POST.get('modell') or '').strip(),
        seriennummer=(request.POST.get('seriennummer') or '').strip(),
        kapazitaet=(request.POST.get('kapazitaet') or '').strip(),
        standort=(request.POST.get('standort') or '').strip(),
        installations_datum=(date.fromisoformat(request.POST['installations_datum']) if request.POST.get('installations_datum') else None),
        garantie_bis=(date.fromisoformat(request.POST['garantie_bis']) if request.POST.get('garantie_bis') else None),
        notiz=(request.POST.get('notiz') or '').strip(),
    )
    log_aktion(request, "Asset erfasst", f"{g.marke} {g.modell}", str(lg))
    messages.success(request, "✅ Asset / Gerät erfasst.")
    ziel = '/neu/assets/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


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
        messages.error(request, "Bitte eine Datei auswählen.")
        return redirect('fw_dokumente')
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    PDokument.objects.create(
        titel=(request.POST.get('titel') or request.FILES['datei'].name).strip(),
        kategorie=request.POST.get('kategorie', 'sonstiges'),
        liegenschaft=lg,
        einheit=Einheit.objects.filter(id=request.POST.get('einheit_id') or None).first() if request.POST.get('einheit_id') else None,
        datei=request.FILES['datei'],
    )
    log_aktion(request, "Dokument hochgeladen", request.POST.get('titel', ''), '')
    messages.success(request, "✅ Dokument hochgeladen.")
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
        titel = d.titel
        d.delete()
        log_aktion(request, "Dokument gelöscht", titel, '')
        messages.success(request, "🗑️ Dokument gelöscht.")
    ziel = '/neu/dokumente/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_nebenkosten_neu(request):
    """Neue Nebenkosten-Abrechnungsperiode anlegen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import AbrechnungsPeriode
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_nebenkosten')
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    bez = (request.POST.get('bezeichnung') or '').strip()
    try:
        start = date.fromisoformat(request.POST.get('start_datum'))
        ende = date.fromisoformat(request.POST.get('ende_datum'))
    except Exception:
        start = ende = None
    if not lg or not bez or not start or not ende:
        messages.error(request, "Liegenschaft, Bezeichnung, Start- und Enddatum sind erforderlich.")
        return redirect('fw_nebenkosten')
    p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung=bez, start_datum=start, ende_datum=ende)
    log_aktion(request, "Abrechnungsperiode erstellt", bez, str(lg))
    messages.success(request, f"✅ Abrechnungsperiode '{bez}' erstellt.")
    return redirect(f'/neu/nebenkosten/{p.id}/')


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
        messages.error(request, "Firma ist erforderlich.")
        return redirect('fw_dienstleister')
    h.firma = firma
    h.branche = request.POST.get('branche', h.branche) or h.branche
    h.kontaktperson = (request.POST.get('kontaktperson') or '').strip()
    h.email = (request.POST.get('email') or '').strip()
    h.telefon = (request.POST.get('telefon') or '').strip()
    h.save()
    log_aktion(request, "Dienstleister bearbeitet", firma, '')
    messages.success(request, f"✅ Dienstleister '{firma}' aktualisiert.")
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
        messages.success(request, f"🗑️ Dienstleister '{firma}' gelöscht.")
    return redirect('fw_dienstleister')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_asset_bearbeiten(request, pk):
    """Asset / Gerät (Portfolio-Assetliste) bearbeiten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    from core.auth import log_aktion
    g = get_object_or_404(Geraet, id=pk)
    ziel = '/neu/assets/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    if request.method != 'POST':
        return redirect(ziel)

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    kategorie = (request.POST.get('kategorie') or '').strip()
    if kategorie:
        g.kategorie = kategorie
    g.sonstiges_bezeichnung = (request.POST.get('sonstiges_bezeichnung') or '').strip()
    g.marke = (request.POST.get('marke') or '').strip()
    g.modell = (request.POST.get('modell') or '').strip()
    g.seriennummer = (request.POST.get('seriennummer') or '').strip()
    g.kapazitaet = (request.POST.get('kapazitaet') or '').strip()
    g.standort = (request.POST.get('standort') or '').strip()
    g.installations_datum = _date(request.POST.get('installations_datum'))
    g.garantie_bis = _date(request.POST.get('garantie_bis'))
    g.notiz = (request.POST.get('notiz') or '').strip()
    g.save()
    log_aktion(request, "Asset bearbeitet", f"{g.kategorie} {g.marke}".strip(), '')
    messages.success(request, "✅ Asset aktualisiert.")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_asset_loeschen(request, pk):
    """Asset / Gerät (Portfolio-Assetliste) löschen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    from core.auth import log_aktion
    g = get_object_or_404(Geraet, id=pk)
    if request.method == 'POST':
        from core.models import Pendenz
        bez = f"{g.kategorie} {g.marke}".strip()
        # Verwaiste Auto-Garantie-Pendenz mitlöschen (hängt nur über `quelle`).
        Pendenz.objects.filter(quelle=f"auto:garantie:{g.id}").delete()
        g.delete()
        log_aktion(request, "Asset gelöscht", bez, '')
        messages.success(request, "🗑️ Asset gelöscht.")
    ziel = '/neu/assets/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


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
            messages.error(request, "Bereits verbuchte Rechnung kann nicht gelöscht werden — "
                                    "bitte die zugehörige Buchung stornieren.")
        else:
            lief = k.lieferant
            k.delete()
            log_aktion(request, "Kreditorenrechnung gelöscht", lief, '')
            messages.success(request, f"🗑️ Kreditorenrechnung '{lief}' gelöscht.")
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


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
            messages.error(request, "Abgeschlossene Periode kann nicht gelöscht werden.")
            return redirect(f'/neu/nebenkosten/{p.id}/')
        bez = p.bezeichnung
        p.delete()
        log_aktion(request, "Abrechnungsperiode gelöscht", bez, '')
        messages.success(request, f"🗑️ Abrechnungsperiode '{bez}' gelöscht.")
    return redirect('fw_nebenkosten')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_buchung_neu(request):
    """Manuelle Buchung erfassen (Soll an Haben)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_buchhaltung')

    def _konto_aus_post(feld_nummer, feld_id):
        """Akzeptiert die KONTONUMMER (Tastatureingabe) oder die ID (Alt-Formulare).
        Die Nummer ist der Weg, den ein Buchhalter erwartet — vorher gab es nur
        ein <select> über den ganzen Kontenplan (Audit)."""
        nr = (request.POST.get(feld_nummer) or '').strip()
        if nr:
            # Die datalist zeigt «4000 Unterhalt» — nur der führende Zahlenteil zählt.
            nr = nr.split()[0].strip()
            k = Buchungskonto.objects.filter(nummer=nr).first()
            if k:
                return k
        return Buchungskonto.objects.filter(id=request.POST.get(feld_id) or None).first()

    # Serienerfassung: zurück zur Maske statt auf die Übersicht, damit ein Stapel
    # ohne Neuaufklappen und ohne erneutes Tippen von Datum/Konten läuft.
    weiter = request.POST.get('weiter') == '1'

    def _zurueck(fehler=False):
        if not weiter:
            return redirect('fw_buchhaltung')
        # Werte für die nächste Zeile in der Session merken.
        request.session['bu_serie'] = True
        return redirect('/neu/buchhaltung/?tab=journal#buchform')

    soll = _konto_aus_post('soll_konto', 'soll_konto_id')
    haben = _konto_aus_post('haben_konto', 'haben_konto_id')
    try:
        betrag = Decimal((_num(request.POST.get('betrag')) or '0'))
    except Exception:
        betrag = Decimal('0')
    text = (request.POST.get('beleg_text') or '').strip()
    if not soll or not haben or betrag <= 0 or not text:
        messages.error(request, "Soll-, Haben-Konto (gültige Nummer), Betrag (> 0) und Belegtext sind erforderlich.")
        return _zurueck(fehler=True)
    if soll.id == haben.id:
        messages.error(request, "Soll- und Haben-Konto müssen unterschiedlich sein.")
        return _zurueck(fehler=True)
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first() if request.POST.get('liegenschaft_id') else None
    bu_datum = (date.fromisoformat(request.POST['datum']) if request.POST.get('datum')
                else timezone.localdate())
    try:
        Buchung.objects.create(
            datum=bu_datum, beleg_text=text, liegenschaft=lg,
            soll_konto=soll, haben_konto=haben,
            betrag=betrag, erstellt_von=request.user)
    except PermissionError as exc:          # Periodensperre
        messages.error(request, f"❌ {exc}")
        return _zurueck(fehler=True)
    log_aktion(request, "Manuelle Buchung", text, f"{soll.nummer}/{haben.nummer} CHF {betrag}")
    messages.success(request, f"✅ Buchung erfasst: {soll.nummer} an {haben.nummer} · CHF {betrag}.")
    # Datum, Konten und Liegenschaft für den nächsten Beleg vorhalten.
    request.session['bu_letzt'] = {
        'datum': bu_datum.isoformat(), 'soll': soll.nummer, 'haben': haben.nummer,
        'lg': lg.id if lg else None,
    }
    return _zurueck()


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_buchung_stornieren(request, pk):
    """Storniert eine Journalbuchung durch eine revisionssichere Gegenbuchung.
    Die Originalbuchung bleibt erhalten (append-only, OR 958f). Nur Verwaltung —
    ein Storno ist ein buchhalterischer Korrektureingriff (nicht Sachbearbeitung)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchung
    from finance.booking import storniere_buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_buchhaltung')
    b = get_object_or_404(Buchung, id=pk)
    # Eine EINZELNE Abschlussbuchung darf nicht im Journal storniert werden — das
    # liesse das Geschäftsjahr halb geschlossen zurück (ein Teil der Erfolgskonten
    # gegen 2970 saldiert, der Rest offen) und verschöbe Vorjahresaufwand ins
    # laufende Jahr. Ein Abschluss wird atomar über «Abschluss zurücknehmen»
    # gelöst (Audit-Befund H6).
    from core.services.jahresabschluss import BELEG_PREFIX as _ABSCHLUSS_PREFIX
    if b.beleg_text.startswith(_ABSCHLUSS_PREFIX):
        messages.error(request, "Abschlussbuchungen lassen sich nicht einzeln stornieren. "
                                "Bitte den Jahresabschluss gesamthaft über «Abschluss zurücknehmen» aufheben.")
        return redirect('fw_buchhaltung')
    try:
        gegen = storniere_buchung(b, user=request.user)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('fw_buchhaltung')
    except PermissionError as e:
        messages.error(request, str(e))
        return redirect('fw_buchhaltung')
    log_aktion(request, "Buchung storniert", b.beleg_text,
               f"Beleg #{b.beleg_nr} → Storno #{gegen.beleg_nr} · CHF {b.betrag}")
    messages.success(request, f"✅ Beleg #{b.beleg_nr} storniert (Gegenbuchung #{gegen.beleg_nr}).")
    return redirect('fw_buchhaltung')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kommunikation_senden(request):
    """Verschickt die verfasste Mitteilung per E-Mail an die gewählten Mieter."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kommunikation')
    betreff = (request.POST.get('betreff') or 'Mitteilung').strip()
    text = (request.POST.get('text') or '').strip()
    ids = request.POST.getlist('empfaenger_id')
    if not text or not ids:
        messages.error(request, "Text und mindestens ein Empfänger erforderlich.")
        return redirect('fw_kommunikation')
    from core.utils.email_service import journal_email
    gesendet = 0
    for mid in ids:
        m = Mieter.objects.filter(id=mid).first()
        if m and m.email:
            if send_ticket_email(m.email, betreff, text):
                gesendet += 1
                journal_email(betreff, text, mieter=m, user=request.user, empfaenger=m.email)
    log_aktion(request, "Rundschreiben per E-Mail", betreff, f"{gesendet} Empfänger")
    messages.success(request, f"✅ {gesendet} E-Mail(s) versendet." if gesendet else "Keine E-Mail versendet (fehlende Adressen).")
    return redirect('fw_kommunikation')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_serienbrief_pdf(request):
    """Erzeugt ein Sammel-PDF (ein Brief pro Empfänger, Fenstercouvert) für
    einen echten postalischen Rundbrief an alle gewählten Mieter."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from crm.models import Organisation
    from core.auth import log_aktion
    from core.services.serienbrief import generate_serienbrief_pdf
    from core.services.ablage import ablegen
    if request.method != 'POST':
        return redirect('fw_kommunikation')
    betreff = (request.POST.get('betreff') or 'Mitteilung').strip()
    text = (request.POST.get('text') or '').strip()
    ids = request.POST.getlist('empfaenger_id')
    if not text or not ids:
        messages.error(request, "Text und mindestens ein Empfänger erforderlich.")
        return redirect('fw_kommunikation')

    vw = aktuelle_organisation()
    absender = {
        'firma': vw.firma if vw else 'Meine Verwaltung',
        'strasse': vw.strasse if vw else '',
        'plz': vw.plz if vw else '', 'ort': vw.ort if vw else '',
    }

    # Empfänger auflösen (Adresse + Objekt/Liegenschaft aus aktivem Vertrag).
    # Bei 2-Personen-Verträgen werden BEIDE Namen adressiert; sind beide Personen
    # gewählt, entsteht trotzdem nur EIN Brief (Dedup über Vertrag).
    from django.db.models import Q as _Q
    empfaenger = []
    verarbeitete_vertraege = set()
    for mid in ids:
        m = Mieter.objects.filter(id=mid).first()
        if not m:
            continue
        v = (Mietvertrag.objects.filter(_Q(mieter=m) | _Q(mitmieter=m), status='aktiv')
             .select_related('einheit__liegenschaft', 'mieter', 'mitmieter').first())
        if v:
            if v.id in verarbeitete_vertraege:
                continue  # zweite Person desselben Vertrags → kein Doppelbrief
            verarbeitete_vertraege.add(v.id)
            lg = v.einheit.liegenschaft if v.einheit_id else None
            prim = v.mieter or m
            zweit = (v.mitmieter.display_name if v.mitmieter else (v.mitmieter_name or '')).strip()
            name = prim.display_name + (f" & {zweit}" if zweit else '')
            empfaenger.append({
                '_mieter_id': prim.id, '_vertrag_id': v.id,
                'name': name, 'anrede': prim.anrede or '',
                'strasse': prim.strasse or (lg.strasse if lg else ''),
                'plz': prim.plz or (lg.plz if lg else ''),
                'ort': prim.ort or (lg.ort if lg else ''),
                'objekt': (f"{lg.strasse}, {lg.ort} · {v.einheit.bezeichnung}" if lg else ''),
                'liegenschaft': (f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else ''),
            })
        else:
            empfaenger.append({
                '_mieter_id': m.id, '_vertrag_id': None,
                'name': m.display_name, 'anrede': m.anrede or '',
                'strasse': m.strasse or '', 'plz': m.plz or '', 'ort': m.ort or '',
                'objekt': '', 'liegenschaft': '',
            })
    if not empfaenger:
        messages.error(request, "Keine gültigen Empfänger gefunden.")
        return redirect('fw_kommunikation')

    logo_path = None
    if vw and getattr(vw, 'logo', None):
        try:
            logo_path = vw.logo.path
        except Exception:
            logo_path = None

    pdf = generate_serienbrief_pdf(absender, betreff, text, empfaenger,
                                   logo_path=logo_path, signatur=(vw,))

    # Auto-Ablage: pro Empfänger eine eigene (einseitige) Brief-Kopie in dessen
    # Akte ablegen — erscheint automatisch im Mieterportal (portal-sichtbar).
    abgelegt = 0
    for e in empfaenger:
        m = Mieter.objects.filter(id=e.get('_mieter_id')).first()
        if not m:
            continue
        v = Mietvertrag.objects.filter(id=e.get('_vertrag_id')).first() if e.get('_vertrag_id') else None
        einzel = generate_serienbrief_pdf(absender, betreff, text, [e],
                                          logo_path=logo_path, signatur=(vw,))
        # Titel mit aufgelösten Platzhaltern ({liegenschaft} etc.) — nicht roh.
        from core.services.serienbrief import _ersetze
        betreff_aufgeloest = _ersetze(betreff, e) or betreff
        # Ablage am Vertrag (erscheint im Portal beider Personen) + am Hauptmieter
        if ablegen(einzel, f"Brief: {betreff_aufgeloest}", kategorie='korrespondenz', vertrag=v, mieter=m):
            abgelegt += 1

    log_aktion(request, "Serienbrief-PDF erzeugt", betreff, f"{len(empfaenger)} Empfänger · {abgelegt} abgelegt")
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="serienbrief_{date.today().isoformat()}.pdf"'
    return resp


# ══════════════════════════════════════════════════════════════
# UI-MODUS (Einfach/Profi) + EINSTELLUNGEN-HUB
# ══════════════════════════════════════════════════════════════

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_modus_wechsel(request):
    """Schaltet die Oberfläche zwischen Einfach- und Profi-Modus um (Session)."""
    from django.shortcuts import redirect
    from core.navigation import UI_MODI, SESSION_KEY
    if request.method == 'POST':
        modus = request.POST.get('modus')
        if modus in UI_MODI:
            request.session[SESSION_KEY] = modus
    ziel = request.META.get('HTTP_REFERER') or '/neu/'
    return redirect(ziel)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_einstellungen(request):
    """Zentrale Einstellungen-Seite — bündelt die früheren 8 Profil-Dropdown-
    Punkte (Account, Abonnement, Benutzer, Logbuch, Vorlagen, Integrationen,
    Rechtsgrundlagen) als eine Hub-Seite mit Sektionen."""
    basis = _global_filter(request)
    karten = [
        {'titel': 'Account', 'sub': 'Verwaltungs-Stammdaten, Logo, Absender', 'url': '/neu/account/', 'icon': 'fa-id-card'},
        {'titel': 'Benutzer & Rollen', 'sub': 'Team-Mitglieder und Berechtigungen', 'url': '/neu/benutzer/', 'icon': 'fa-users'},
        {'titel': 'Vorlagen', 'sub': 'Textvorlagen mit Platzhaltern', 'url': '/neu/vorlagen/', 'icon': 'fa-file-lines'},
        {'titel': 'Integrationen', 'sub': 'E-Mail, DocuSeal, KI, Banken, Portal-Feed', 'url': '/neu/integrationen/', 'icon': 'fa-plug'},
        {'titel': 'Abonnement', 'sub': 'Plan und Rechnungsstellung', 'url': '/neu/abonnement/', 'icon': 'fa-star'},
        {'titel': 'Anmeldung & Sicherheit', 'sub': 'Zwei-Faktor-Anmeldung für Sie und Ihr Team',
         'url': '/konto/zwei-faktor/', 'icon': 'fa-shield-halved'},
        {'titel': 'Postfächer', 'sub': 'E-Mail-Eingang für Ticket-Antworten und Rechnungen',
         'url': '/neu/postfaecher/', 'icon': 'fa-inbox'},
        {'titel': 'Logbuch', 'sub': 'Wer hat wann was geändert', 'url': '/neu/logbuch/', 'icon': 'fa-clock-rotate-left'},
        {'titel': 'Rechtsgrundlagen', 'sub': 'OR/VMWG-Artikel mit Anwendung im Programm', 'url': '/neu/rechtsgrundlagen/', 'icon': 'fa-scale-balanced'},
    ]
    return render(request, 'fw/einstellungen.html', {
        **basis, 'nav': 'einstellungen', 'karten': karten,
    })




@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zahlung_zuordnen(request):
    """Ordnet eine geparkte Zahlung (Durchlaufkonto 1190 / Mieterguthaben 2030)
    nachträglich einer offenen Debitorenrechnung zu — Audit-Befund «1190 ist
    eine Sackgasse». Bucht Parkkonto an 1100, verknüpft den Zahlungseingang
    mit Vertrag+Rechnung und führt den OP-Status nach. Ein Überschuss über den
    offenen Betrag bleibt als Rest-Guthaben auf dem Parkkonto liegen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.booking import buche
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_bankabgleich')

    from core.services.zahlungszuordnung import zuordnen, ZuordnungsFehler

    with transaction.atomic():
        # Zeilensperre: ohne sie buchen zwei parallele Zuordnungen dieselbe
        # Forderung doppelt aus.
        zahlung = get_object_or_404(
            Zahlungseingang.objects.select_for_update(), id=request.POST.get('zahlung_id'))
        rechnung = get_object_or_404(
            DebitorenRechnung.objects.select_for_update(), id=request.POST.get('rechnung_id'))
        park_nr = zahlung.konto.nummer if zahlung.konto_id else ''
        vertrag = rechnung.vertrag
        try:
            betrag, rest, gelernt = zuordnen(zahlung, rechnung, user=request.user)
        except ZuordnungsFehler as e:
            messages.error(request, str(e))
            return redirect('fw_bankabgleich')
        except PermissionError as e:
            messages.error(request, f"Periodensperre: {e}")
            return redirect('fw_bankabgleich')

    log_aktion(request, "Geparkte Zahlung zugeordnet", str(vertrag),
               f"CHF {betrag} von {park_nr} auf {rechnung.titel}"
               + (f" · Absender «{gelernt}» gemerkt" if gelernt else ""))
    messages.success(request, f"✅ CHF {betrag} zugeordnet — {vertrag.mieter.display_name} "
                              f"({rechnung.titel}){f' · Rest CHF {rest} bleibt als Guthaben' if rest > 0 else ''}.")
    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'
    from django.shortcuts import redirect as _r
    return _r(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zahlungen_sammel_zuordnen(request):
    """Ordnet mehrere geparkte Zahlungen auf einen Schlag EINEM Mieter zu.

    Zahlt jemand monatlich ohne QR-Referenz, sammeln sich auf dem Durchlaufkonto
    schnell ein Dutzend gleich aussehender Posten an — einzeln zugeordnet ist das
    eine Viertelstunde Klickarbeit. Hier wird pro Zahlung die ÄLTESTE offene
    Forderung des Mieters getilgt; ein Überschuss bleibt als Guthaben stehen.
    """
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    from core.services.zahlungszuordnung import sammel_zuordnen

    if request.method != 'POST':
        return redirect('fw_bankabgleich')

    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'

    ids = [i for i in request.POST.getlist('zahlung_ids') if i.isdigit()]
    vertrag = Mietvertrag.objects.filter(id=request.POST.get('vertrag_id') or 0) \
        .select_related('mieter', 'einheit__liegenschaft').first()
    if not ids:
        messages.warning(request, "Keine Zahlung ausgewählt.")
        return redirect(ziel)
    if vertrag is None:
        messages.error(request, "Kein Mieter gewählt — die Zahlungen bleiben ungeklärt.")
        return redirect(ziel)

    with transaction.atomic():
        # Zeilensperre wie bei der Einzelzuordnung: sonst bucht ein paralleler
        # Lauf dieselbe Forderung ein zweites Mal aus.
        zahlungen = list(Zahlungseingang.objects.select_for_update()
                         .filter(id__in=ids, status='verbucht',
                                 konto__nummer__in=['1190', '2030'])
                         .select_related('konto'))
        anzahl, summe, rest, fehler, gelernt = sammel_zuordnen(
            zahlungen, vertrag, user=request.user)

    if anzahl:
        log_aktion(request, "Zahlungen sammelweise zugeordnet", str(vertrag),
                   f"{anzahl} Zahlung(en), CHF {summe}"
                   + (f", Rest CHF {rest} als Guthaben" if rest else "")
                   + (f" · Absender «{gelernt}» gemerkt" if gelernt else ""))
        messages.success(
            request,
            f"✅ {anzahl} Zahlung(en) zugeordnet (CHF {summe}) — "
            f"{vertrag.mieter.display_name}"
            + (f" · CHF {rest} bleiben als Guthaben" if rest else "")
            + (f" · Absender «{gelernt}» gemerkt, künftige Zahlungen treffen selbst"
               if gelernt else "") + ".")
    for f in fehler:
        messages.warning(request, f"Nicht zugeordnet — {f}")
    if not anzahl and not fehler:
        messages.warning(request, "Nichts zugeordnet — die gewählten Zahlungen liegen "
                                  "nicht mehr auf einem Parkkonto.")
    return redirect(ziel)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_zahler_zuordnungen(request):
    """Die gelernten Absender: wer zahlt für welchen Mietvertrag.

    Diese Zuordnungen entstehen still im Hintergrund — jede manuelle Zuordnung
    einer geparkten Zahlung merkt sich den Absender, und beim nächsten Import
    trifft die Zahlung von allein. Genau deshalb braucht es diese Seite: Eine
    Automatik, die niemand einsehen und korrigieren kann, ist keine Hilfe,
    sondern ein blinder Fleck. Zieht ein Mieter aus und der Nachmieter heisst
    zufällig ähnlich, oder wurde beim ersten Mal danebengegriffen, ordnet das
    Programm sonst dauerhaft falsch zu — und niemand sieht, warum.
    """
    from finance.models import ZahlerZuordnung
    basis = _global_filter(request)

    zuordnungen = list(ZahlerZuordnung.objects
                       .select_related('vertrag__mieter',
                                       'vertrag__einheit__liegenschaft')
                       .order_by('-treffer', 'name_anzeige', 'name_norm'))

    # Auswahl zum Umbiegen: aktive Verträge reichen — auf einen beendeten
    # Vertrag zu zeigen wäre eine neue Fehlerquelle, keine Korrektur.
    vertraege = []
    for v in (Mietvertrag.objects.filter(status='aktiv')
              .select_related('mieter', 'einheit__liegenschaft')
              .order_by('id')):
        lg = v.einheit.liegenschaft if v.einheit_id and v.einheit.liegenschaft_id else None
        teile = [v.mieter.display_name if v.mieter_id else '—']
        if lg:
            teile.append(lg.strasse)
        if v.einheit_id and v.einheit.bezeichnung:
            teile.append(v.einheit.bezeichnung)
        vertraege.append({'id': v.id, 'label': ' · '.join(teile)})
    vertraege.sort(key=lambda x: x['label'].lower())

    return render(request, 'fw/zahler_zuordnungen.html', {
        **basis, 'nav': 'bankabgleich',
        'zuordnungen': zuordnungen, 'vertraege': vertraege,
        'getroffen_n': sum(z.treffer for z in zuordnungen),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zahler_zuordnung_speichern(request):
    """Gelernten Absender auf einen anderen Vertrag umbiegen oder vergessen.

    Bewusst ohne Buchungswirkung: Bereits verbuchte Zahlungen bleiben, wie sie
    gebucht wurden. Geändert wird nur, was das Programm beim NÄCHSTEN Import
    tut — eine Regel für die Zukunft, keine rückwirkende Umbuchung.
    """
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    from finance.models import ZahlerZuordnung

    if request.method != 'POST':
        return redirect('fw_zahler_zuordnungen')

    eintrag = (ZahlerZuordnung.objects
               .filter(id=request.POST.get('id') or 0)
               .select_related('vertrag__mieter').first())
    if eintrag is None:
        messages.error(request, "Diese Zuordnung gibt es nicht mehr.")
        return redirect('fw_zahler_zuordnungen')

    name = eintrag.name_anzeige or eintrag.name_norm

    if request.POST.get('aktion') == 'loeschen':
        eintrag.delete()
        log_aktion(request, "Zahler-Zuordnung gelöscht", name, '')
        messages.success(request, f"✅ «{name}» wird nicht mehr automatisch zugeordnet — "
                                  f"künftige Zahlungen landen wieder zur Prüfung "
                                  f"im Bankabgleich.")
        return redirect('fw_zahler_zuordnungen')

    ziel = (Mietvertrag.objects.filter(id=request.POST.get('vertrag_id') or 0)
            .select_related('mieter').first())
    if ziel is None:
        messages.error(request, "Kein Mieter gewählt — die Zuordnung bleibt unverändert.")
        return redirect('fw_zahler_zuordnungen')
    if ziel.id == eintrag.vertrag_id:
        return redirect('fw_zahler_zuordnungen')

    alt = (eintrag.vertrag.mieter.display_name
           if eintrag.vertrag_id and eintrag.vertrag.mieter_id else '—')
    eintrag.vertrag = ziel
    # Die Trefferzahl gehört zur alten Regel und würde die neue fälschlich
    # als bewährt ausweisen.
    eintrag.treffer = 0
    eintrag.zuletzt = None
    eintrag.save(update_fields=['vertrag', 'treffer', 'zuletzt'])
    log_aktion(request, "Zahler-Zuordnung geändert", name,
               f"{alt} → {ziel.mieter.display_name}")
    messages.success(request, f"✅ «{name}» zahlt neu für {ziel.mieter.display_name}. "
                              f"Bereits verbuchte Zahlungen bleiben unverändert.")
    return redirect('fw_zahler_zuordnungen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bankbewegung_zuordnen(request):
    """Ordnet eine offene Bankbewegung zu und bucht sie.

    Ohne diesen Schritt bleibt eine Belastung ewig im Eingang liegen: Der Auszug
    nennt kein Gegenkonto — ob eine Zahlung an einen Lieferanten, eine Gebühr,
    ein Hypothekarzins oder eine Eigentümer-Auszahlung dahintersteckt, weiss nur
    der Buchhalter. Deshalb wird geraten NICHTS, sondern gefragt.

    Drei Wege:
      kreditor  — Belastung tilgt eine Kreditorenrechnung: 2000 an Bank
      konto     — freies Gegenkonto (Gebühr, Zins, Eigentümer): Gegenkonto an Bank
                  bzw. bei einer Gutschrift Bank an Gegenkonto
      ignorieren— gehört nicht in diese Buchhaltung (z.B. Umbuchung eigenes Konto)
    """
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Bankbewegung, KreditorenRechnung, Buchungskonto
    from finance.booking import buche
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_bankabgleich')
    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'

    bew = get_object_or_404(Bankbewegung, id=request.POST.get('bewegung_id'))
    if bew.status != 'offen':
        messages.info(request, "Diese Bankbewegung ist bereits erledigt.")
        return redirect(ziel)

    art = request.POST.get('art')
    # Das VALUTADATUM ist buchhalterisch massgebend; vorher landete jede Zahlung
    # im Datum des Erfassungstags (Praxis-Audit).
    dat = bew.valuta or bew.datum
    bank_nr = bew.konto.nummer
    betrag = abs(bew.betrag)

    if art == 'ignorieren':
        bew.status = 'ignoriert'
        bew.bemerkung = (request.POST.get('bemerkung') or 'Nicht buchungsrelevant')[:255]
        bew.save(update_fields=['status', 'bemerkung'])
        log_aktion(request, "Bankbewegung ignoriert", str(bew), bew.bemerkung)
        messages.success(request, "Bewegung als nicht buchungsrelevant markiert.")
        return redirect(ziel)

    try:
        with transaction.atomic():
            if art == 'kreditor':
                from finance.models import KreditorenZahlung
                kr = get_object_or_404(KreditorenRechnung,
                                       id=request.POST.get('kreditor_id'))
                if bew.betrag >= 0:
                    messages.error(request, "Eine Gutschrift kann keine Lieferantenrechnung tilgen.")
                    return redirect(ziel)
                offen_kr = kr.offener_betrag
                if offen_kr <= 0:
                    messages.error(request, "Diese Lieferantenrechnung ist bereits bezahlt.")
                    return redirect(ziel)
                # Nie mehr tilgen als offen ist — der Rest bleibt im Eingang.
                betrag = min(betrag, offen_kr)
                # Gleicher Weg wie die manuelle Zahlung (KreditorenZahlung +
                # 2000 an Bank), damit es nur EINEN Zahlungspfad gibt.
                KreditorenZahlung.objects.create(
                    kreditor=kr, betrag=betrag, datum=dat,
                    bemerkung=f"Bankabgleich {bew.text or bew.gegenpartei}"[:255],
                    erstellt_von=request.user)
                buchung = buche('2000', bank_nr, betrag,
                                f"Zahlung {kr.lieferant} - {kr.referenz}"[:255],
                                datum=dat, liegenschaft=kr.liegenschaft, kreditor=kr,
                                user=request.user)
                kr.status = 'bezahlt' if kr.offener_betrag <= 0 else 'teilbezahlt'
                kr.save(update_fields=['status'])
                bew.liegenschaft = kr.liegenschaft
                text = f"Kreditor {kr.lieferant}"
            else:
                gegen_nr = (request.POST.get('gegenkonto') or '').strip().split()[0] if request.POST.get('gegenkonto') else ''
                gegen = Buchungskonto.objects.filter(nummer=gegen_nr).first()
                if not gegen:
                    messages.error(request, "Bitte ein gültiges Gegenkonto angeben.")
                    return redirect(ziel)
                lg_b = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
                bez = (request.POST.get('beleg_text') or bew.text or 'Bankbewegung')[:255]
                if bew.betrag < 0:      # Ausgang: Aufwand/Aktivum an Bank
                    buchung = buche(gegen, bank_nr, betrag, bez, datum=dat,
                                    liegenschaft=lg_b, user=request.user)
                else:                   # Eingang: Bank an Ertrag/Passivum
                    buchung = buche(bank_nr, gegen, betrag, bez, datum=dat,
                                    liegenschaft=lg_b, user=request.user)
                bew.liegenschaft = lg_b
                text = f"{gegen.nummer} {gegen.bezeichnung}"
            bew.status = 'verbucht'
            bew.bemerkung = text[:255]
            # Beleg an der Auszugszeile festhalten — sonst ist im Nachhinein nicht
            # belegbar, WELCHE Buchung diese Bankbewegung erledigt hat (Revision).
            bew.buchung = buchung
            bew.save(update_fields=['status', 'bemerkung', 'liegenschaft', 'buchung'])
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(ziel)
    except Exception as exc:
        messages.error(request, f"❌ Bewegung konnte nicht gebucht werden: {exc}")
        return redirect(ziel)

    log_aktion(request, "Bankbewegung verbucht", str(bew), text)
    messages.success(request, f"✅ CHF {betrag} verbucht ({text}) — Valuta {dat:%d.%m.%Y}.")
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_mwst_verbuchen(request):
    """Bucht die MWST-Abrechnung einer Periode aus (Audit K4/N2).

    Effektiv:  2200 an 1170 (Vorsteuer verrechnen) + 2200 an 2201 (Schuld ESTV)
    Saldosatz: 2200 an 2201 über die Saldosatz-Zahllast; der Überschuss auf 2200
               (Differenz Normalsatz ./. Saldosatz) ist Ertrag → 2200 an 3600.
    Ohne diese Ausbuchung wächst Konto 2200 unbegrenzt weiter.

    Gegenkonto ist das Abrechnungskonto 2201, NICHT die Bank: Am Periodenende
    entsteht nur die Schuld, gezahlt wird erst mit der Abrechnung (Frist 60
    Tage). Die frühere Buchung gegen 1020 liess den Banksaldo ab dem Stichtag
    vom realen Kontoauszug abweichen — der Bankabgleich zeigte eine
    Dauerdifferenz, und die echte Zahlung wurde beim Import ein zweites Mal
    gebucht (Audit). Die Zahlung selbst läuft später als 2201 an 1020."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.booking import buche
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_mwst')
    heute = timezone.localdate()
    # Der globale Filter kommt aus der Query-String — hier wird per POST gesendet.
    # Ohne diese Zeile lief die Verbuchung immer über das GESAMTE Portfolio, während
    # die Anzeige daneben nur eine Liegenschaft zeigte (Audit).
    aktive_lg = None
    if lg_id := (request.POST.get('lg') or request.GET.get('lg')):
        aktive_lg = Liegenschaft.objects.filter(id=lg_id).first()
    try:
        jahr = int(request.POST.get('jahr') or heute.year)
    except ValueError:
        jahr = heute.year
    quartal = request.POST.get('quartal', '')
    ziel = f'/neu/mwst/?jahr={jahr}' + (f'&quartal={quartal}' if quartal else '')
    if aktive_lg:
        ziel += f'&lg={aktive_lg.id}'

    if _mwst_bereits_verbucht(jahr, quartal, aktive_lg):
        messages.info(request, "Diese MWST-Periode wurde bereits verbucht.")
        return redirect(ziel)

    # Beträge NEU aus dem Hauptbuch rechnen statt aus dem POST übernehmen — sonst
    # bestimmt der Client, was der ESTV geschuldet wird (Audit).
    p = _mwst_periode(jahr, quartal, aktive_lg)
    umsatzsteuer, vorsteuer = p['umsatzsteuer'], p['vorsteuer']
    zahllast, methode = p['zahllast'], p['methode']
    if umsatzsteuer <= 0 and vorsteuer <= 0:
        messages.info(request, "Für diese Periode gibt es keine MWST zu verbuchen.")
        return redirect(ziel)

    beleg = _mwst_beleg(jahr, quartal)
    ende = date(jahr, 12, 31) if quartal not in ('1', '2', '3', '4') else \
        date(jahr, int(quartal) * 3, _calendar.monthrange(jahr, int(quartal) * 3)[1])
    try:
        with transaction.atomic():
            if methode == 'saldo':
                if zahllast > 0:
                    buche('2200', '2201', zahllast, f"{beleg} — Zahllast ESTV (Saldosatz)",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
                # Rest von 2200 ist der Saldosatz-Vorteil (Ertrag) bzw. — falls der
                # Saldosatz teurer war als die effektiv fakturierte Steuer — ein
                # Aufwand. Beide Richtungen ausbuchen, sonst bleibt 2200 stehen und
                # die Erfolgsmeldung wäre unehrlich.
                vorteil = (umsatzsteuer - zahllast).quantize(Decimal('0.01'))
                if vorteil > 0:
                    buche('2200', '3600', vorteil,
                          f"{beleg} — Saldosteuersatz-Vorteil (Ertrag)",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
                elif vorteil < 0:
                    buche('4500', '2200', abs(vorteil),
                          f"{beleg} — Saldosteuersatz-Nachteil (Aufwand)",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
                # Bei der Saldosatz-Methode ist der Vorsteuerabzug mit dem Satz
                # abgegolten. Ein Soll-Saldo auf 1170 würde sonst ewig stehen
                # bleiben und die Bilanz aufblähen → als Aufwand ausbuchen.
                if vorsteuer > 0:
                    buche('4500', '1170', vorsteuer,
                          f"{beleg} — Vorsteuer im Saldosatz abgegolten",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
            else:
                # Nur den tatsächlich verrechenbaren Teil umbuchen; negative
                # Beträge (2200 im Soll) darf buche() gar nicht erst sehen.
                verrechenbar = min(vorsteuer, umsatzsteuer)
                if verrechenbar > 0:
                    buche('2200', '1170', verrechenbar,
                          f"{beleg} — Vorsteuer verrechnet",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
                if zahllast > 0:
                    buche('2200', '2201', zahllast, f"{beleg} — Zahllast ESTV",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
                elif zahllast < 0:
                    buche('2201', '1170', abs(zahllast), f"{beleg} — Vorsteuerguthaben ESTV",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(ziel)
    except Exception as exc:
        messages.error(request, f"❌ MWST-Abrechnung konnte nicht verbucht werden: {exc}")
        return redirect(ziel)

    log_aktion(request, "MWST-Abrechnung verbucht", beleg, f"Zahllast CHF {zahllast}")
    messages.success(request, f"✅ {beleg} verbucht — Zahllast CHF {zahllast} "
                              f"({'Saldosteuersatz' if methode == 'saldo' else 'effektive Methode'}).")
    return redirect(ziel)


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_zahlung_stornieren(request, pk):
    """Storniert einen Zahlungseingang revisionssicher (Audit W7): Gegenbuchungen
    zu allen Buchungen der Zahlung, Status → storniert, OP-Status der Rechnung
    wird zurückgerollt. Bisher gab es das nur in der Alt-API — eine falsch
    zugeordnete Zahlung war in der neuen Oberfläche nur per Handbuchung zu
    korrigieren (und der OP-Status blieb falsch)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchung
    from finance.services import erstelle_storno_buchung
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_bankabgleich')
    try:
        with transaction.atomic():
            # Zeilensperre: zwei parallele Stornos würden sonst doppelte
            # Gegenbuchungen erzeugen.
            z = get_object_or_404(
                Zahlungseingang.objects.select_for_update()
                .select_related('debitoren_rechnung', 'vertrag__mieter'), id=pk)
            if z.status == 'storniert':
                messages.info(request, "Diese Zahlung ist bereits storniert.")
                return redirect(request.POST.get('next') or '/neu/bankabgleich/')

            # Eine Bankgutschrift kann sich auf mehrere Zahlungseingänge verteilt
            # haben: der zugeordnete Teil plus ein Überschuss als Mieterguthaben
            # (bank_referenz «…:ueber») bzw. ein Rest aus der Zuordnung («…:rest»).
            # Ohne diese Geschwister bliebe das Guthaben nach dem Storno stehen —
            # der Mieter behielte ein Guthaben aus einer Zahlung, die es nicht gibt.
            zahlungen = [z]
            if z.bank_referenz:
                zahlungen += list(Zahlungseingang.objects.select_for_update().filter(
                    bank_referenz__startswith=f"{z.bank_referenz}:", status='verbucht')
                    .exclude(id=z.id))
            for zz in zahlungen:
                for b in Buchung.objects.filter(zahlungseingang=zz, ist_storno=False,
                                                storniert_am__isnull=True):
                    erstelle_storno_buchung(b, benutzer=request.user)
                zz.status = 'storniert'
                zz.save(update_fields=['status'])
            rech = z.debitoren_rechnung
            if rech and rech.status not in ('storniert', 'abgeschrieben'):
                rech.status = 'offen' if rech.offener_betrag >= rech.betrag else 'teilbezahlt'
                rech.save(update_fields=['status'])
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(request.POST.get('next') or '/neu/bankabgleich/')
    except Exception as exc:
        messages.error(request, f"❌ Zahlung konnte nicht storniert werden: {exc}")
        return redirect(request.POST.get('next') or '/neu/bankabgleich/')

    log_aktion(request, "Zahlungseingang storniert", f"Zahlung #{z.id}",
               f"CHF {z.betrag} · {z.vertrag.mieter if z.vertrag_id else 'ohne Vertrag'}")
    messages.success(request, f"✅ Zahlung über CHF {z.betrag} storniert — offener Posten wieder offen.")
    return redirect(request.POST.get('next') or '/neu/bankabgleich/')
