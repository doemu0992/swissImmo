# core/views/fw/debitoren_aktionen.py
#
# Debitoren: neu, Weiterverrechnung, abschreiben, stornieren.
# Aus listen.py herausgeloest (reiner Umzug ohne Aenderung am Code).

from datetime import timedelta as _timedelta
from decimal import Decimal

from django.utils.translation import gettext
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, VERWALTUNGS_ROLLEN)
from core.auth import FINANZ_SCHREIB_ROLLEN, FINANZ_VERWALTUNGS_ROLLEN
from finance.models import DebitorenRechnung
from rentals.models import Mietvertrag


from ._basis import (_global_filter, _num)


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
def fw_debitor_neu(request):
    """Ad-hoc-Debitorenrechnung (Weiterverrechnung: Sonnerie/Schlüssel/Ersatz …).
    Bucht Debitor an das gewählte Ertragskonto (Standard 3600 «Übrige Erträge»)
    und ermöglicht anschliessend die QR-Rechnung. NICHT auf 3000 — Schlüssel-
    ersatz & Co. sind kein Mietertrag (verfälscht Mieterspiegel + Honorarbasis)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_debitoren')

    titel = (request.POST.get('titel') or '').strip()
    try:
        betrag = Decimal((_num(request.POST.get('betrag')) or '0'))
    except Exception:
        betrag = Decimal('0')
    if not titel or betrag <= 0:
        messages.error(request, gettext('Titel und ein Betrag > 0 sind erforderlich.'))
        return redirect('fw_debitoren')

    vertrag = None
    if request.POST.get('vertrag_id'):
        vertrag = Mietvertrag.objects.filter(id=request.POST['vertrag_id']).select_related('einheit__liegenschaft').first()
    lg = vertrag.einheit.liegenschaft if vertrag and vertrag.einheit_id else None
    heute = timezone.localdate()
    faellig = heute + _timedelta(days=30)

    # Ertragskonto: explizit gewählt (Feld konto_haben) oder Standard 3600.
    konto_haben = None
    if request.POST.get('konto_haben'):
        konto_haben = Buchungskonto.objects.filter(id=request.POST['konto_haben']).first()
    haben_nr = konto_haben.nummer if konto_haben else "3600"

    # Der erfasste Betrag ist NETTO; bei optiertem Vertrag kommt die MWST obendrauf.
    satz = vertrag.mwst_satz_wirksam if vertrag else Decimal('0')
    mwst = (betrag * satz / Decimal('100')).quantize(Decimal('0.01')) if satz > 0 else Decimal('0.00')
    with transaction.atomic():
        rechnung = DebitorenRechnung.objects.create(
            vertrag=vertrag, liegenschaft=lg,
            einheit=(vertrag.einheit if vertrag else None),
            titel=titel, beschreibung=(request.POST.get('beschreibung') or '').strip(),
            datum=heute, faellig_am=faellig, betrag=betrag + mwst, status='offen',
            forderungsart='sonstige',     # freie Rechnung, kein Mietzins (Art. 257d OR)
            konto_haben=konto_haben,
            mwst_satz=satz if mwst else Decimal('0.0'), mwst_betrag=mwst,
        )
        from finance.booking import buche
        buche("1100", haben_nr, betrag, f"Weiterverrechnung: {titel}", datum=heute,
              liegenschaft=lg, debitor=rechnung, user=request.user)
        buche("1100", "2200", mwst, f"MWST {satz}% {titel}", datum=heute,
              liegenschaft=lg, debitor=rechnung, user=request.user)

    log_aktion(request, "Ad-hoc-Debitorenrechnung erstellt", titel, f"CHF {betrag}")
    messages.success(request, '✅ ' + gettext("Rechnung '%(titel)s' über CHF %(betrag)s erstellt — QR-Rechnung via QR-Button.") % {'titel': titel, 'betrag': betrag})
    ziel = '/neu/debitoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
def fw_weiterverrechnung(request, kreditor_id):
    """Geführte Weiterverrechnung einer Lieferantenrechnung an einen Mieter.

    GET: Formular (Mieter/Vertrag wählen, Betrag = offener weiterzuverrechnender
    Anteil, optionaler Zuschlag). POST: erstellt eine mit der Kreditorenrechnung
    VERKNÜPFTE Debitorenrechnung und bucht ertragsneutral über das Durchlaufkonto
    1190 (Grundbetrag mindert den Aufwand), der Zuschlag wird als Ertrag gebucht."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, DebitorenRechnung
    from finance.booking import buche
    from core.auth import log_aktion
    k = get_object_or_404(KreditorenRechnung.objects.select_related('liegenschaft', 'konto'), id=kreditor_id)
    basis = _global_filter(request)
    heute = timezone.localdate()

    # Gegenkonto der Aufwandsminderung: Kopf-Konto, sonst (bei Split) das Konto der
    # grössten Position, sonst 4000. So trifft die Weiterverrechnung einer aufge-
    # teilten Rechnung das tatsächliche Aufwandskonto statt pauschal 4000.
    if k.konto_id:
        aufwand_konto = k.konto.nummer
    else:
        _grp = k.positionen.order_by('-betrag').first()
        aufwand_konto = _grp.konto.nummer if _grp else '4000'

    if request.method == 'POST':
        # Alle Schreibvorgänge dieser Weiterverrechnung in EINER Transaktion +
        # Zeilensperre auf die Kreditorenrechnung: verhindert Teilzustände (einige
        # Mieter belastet, andere nicht) bei Abbruch und den Über-Weiterverrechnungs-
        # Race (min(grund, offen) ist ohne Lock ein Check-then-act).
        with transaction.atomic():
            k = KreditorenRechnung.objects.select_for_update().get(id=k.id)
            # Serverseitig, nicht nur als ausgeblendeter Knopf: Eine noch nicht
            # freigegebene Rechnung hat keinen gebuchten Aufwand. Ihre
            # Weiterverrechnung buchte eine Aufwandsminderung gegen nichts —
            # der Aufwand der Liegenschaft würde negativ.
            from finance.freigabe import freigabe_sperre
            _sperre = freigabe_sperre(k)
            if _sperre:
                messages.error(request, f'⛔ {_sperre}')
                return redirect(request.path)
            if k.status not in ('freigegeben', 'in_zahlung', 'teilbezahlt', 'bezahlt'):
                messages.error(request, '❌ ' + gettext(
                    'Nur freigegebene Lieferantenrechnungen können weiterverrechnet werden.'))
                return redirect(request.path)
            def _dec(x, d='0'):
                try:
                    return Decimal(_num(x) or d)
                except Exception:
                    return Decimal(d)

            def _verrechne(vertrag, grund, zuschlag, titel):
                """Erstellt eine verknüpfte Debitorenrechnung + ertragsneutrale
                Durchreichung über 1190 (Zuschlag als Ertrag 3600). Gibt (rechnung, total)."""
                lg2 = vertrag.einheit.liegenschaft if vertrag.einheit_id else k.liegenschaft
                zuschlag = max(zuschlag, Decimal('0'))
                total = (grund + zuschlag).quantize(Decimal('0.01'))
                rechnung = DebitorenRechnung.objects.create(
                    vertrag=vertrag, liegenschaft=lg2, einheit=vertrag.einheit,
                    titel=titel, beschreibung=f"Weiterverrechnung Lieferantenrechnung {k.lieferant}"
                                              + (f" · {k.referenz}" if k.referenz else ''),
                    datum=heute, faellig_am=heute + _timedelta(days=30), betrag=total,
                    status='offen', quell_kreditor=k, weiterverrechnung_zuschlag=zuschlag,
                    forderungsart='sonstige')
                buche("1100", "1190", grund, f"Weiterverrechnung {vertrag.mieter}: {titel}",
                      datum=heute, liegenschaft=lg2, debitor=rechnung, kreditor=k, user=request.user)
                # Der Aufwand wurde bei der Freigabe nur mit dem NETTO gebucht (Vorsteuer
                # separat auf 1170). Die Aufwandsminderung darf ihn deshalb ebenfalls nur
                # netto entlasten; der im durchgereichten Brutto enthaltene MWST-Anteil ist
                # AUSGANGS-Umsatzsteuer (2200) — sonst würde der Aufwand negativ und die
                # zurückgeholte Vorsteuer bliebe unversteuert.
                satz = k.mwst_satz or Decimal('0')
                if satz > 0:
                    netto = (grund / (Decimal('1') + satz / Decimal('100'))).quantize(Decimal('0.01'))
                    mwst = grund - netto
                else:
                    netto, mwst = grund, Decimal('0.00')
                buche("1190", aufwand_konto, netto, f"Aufwandsminderung Weiterverrechnung: {k.lieferant}",
                      datum=heute, liegenschaft=lg2, debitor=rechnung, kreditor=k, user=request.user)
                if mwst > 0:
                    # MWST JE VERTRAG (beides kommt vor):
                    #  · Steuerpflichtig vermietet (Gewerbe mit Option): Die durchgereichte Leistung
                    #    ist steuerbar → Ausgangssteuer 2200.
                    #  · Nicht steuerpflichtig (Wohnraum, Art. 21 Abs. 2 Ziff. 21 MWSTG): Es
                    #    entsteht keine Ausgangssteuer. Die bei der Freigabe abgezogene Vorsteuer
                    #    ist dann zu korrigieren (1170 zurück) — nicht als Ausgangssteuer zu
                    #    buchen, die es nicht gibt.
                    if vertrag.mwst_satz_wirksam > 0:
                        buche("1190", "2200", mwst, f"MWST Weiterverrechnung {satz}% {vertrag.mieter}",
                              datum=heute, liegenschaft=lg2, debitor=rechnung, kreditor=k, user=request.user)
                    else:
                        buche("1190", "1170", mwst,
                              f"Vorsteuerkorrektur Weiterverrechnung {satz}% {vertrag.mieter} (nicht steuerbar)",
                              datum=heute, liegenschaft=lg2, debitor=rechnung, kreditor=k, user=request.user)
                zmwst = Decimal('0.00')
                if zuschlag > 0:
                    buche("1100", "3600", zuschlag, f"Zuschlag Weiterverrechnung {vertrag.mieter}",
                          datum=heute, liegenschaft=lg2, debitor=rechnung, user=request.user)
                    # Ein Zuschlag ist eine eigene Leistung des Vermieters: Bei steuerpflichtiger
                    # Vermietung mit MWST — bisher ohne, auch wenn der Mieter optiert hat.
                    if vertrag.mwst_satz_wirksam > 0:
                        zmwst = (zuschlag * vertrag.mwst_satz_wirksam / Decimal('100')).quantize(Decimal('0.01'))
                        if zmwst > 0:
                            buche("1100", "2200", zmwst, f"MWST auf Zuschlag {vertrag.mwst_satz_wirksam}% {vertrag.mieter}",
                                  datum=heute, liegenschaft=lg2, debitor=rechnung, user=request.user)
                            rechnung.betrag = total + zmwst
                            # Der Abstimmung gilt der Zuschlag samt Steuer nicht als durchgereichte Kosten.
                            rechnung.weiterverrechnung_zuschlag = zuschlag + zmwst
                            rechnung.save(update_fields=['betrag', 'weiterverrechnung_zuschlag'])
                            total = total + zmwst
                # MWST-Ausweis auf der Rechnung: nur bei steuerpflichtigem Vertrag
                # (Grund-MWST wurde auf 2200 gebucht, Zuschlags-MWST oben).
                if vertrag.mwst_satz_wirksam > 0:
                    ausgewiesen = mwst + zmwst
                    if ausgewiesen > 0:
                        rechnung.mwst_satz = vertrag.mwst_satz_wirksam
                        rechnung.mwst_betrag = ausgewiesen
                        rechnung.save(update_fields=['mwst_satz', 'mwst_betrag'])
                return rechnung, total

            # --- Doppelverrechnungs-Schutz (bindend): eine HNK-relevante Rechnung
            # fliesst bereits über die periodische NK-Abrechnung an die Mieter. Sie
            # zusätzlich direkt weiterzuverrechnen würde doppelt belasten. Nur mit
            # bewusstem Override (Häkchen) zulassen.
            if (k.is_hnk_relevant or k.hnk_betrag > 0) and request.POST.get('hnk_override') != 'on':
                messages.error(request, gettext('Diese Rechnung ist HNK-relevant und wird bereits über die Nebenkostenabrechnung verteilt. Direkte Weiterverrechnung nur, wenn du das Häkchen «Trotzdem direkt weiterverrechnen» setzt (sonst doppelte Belastung).'))
                return redirect(request.path)

            # --- Modus «verteilen»: Fremdkosten in EINEM Schritt nach Verteilschlüssel
            # auf alle aktiven Mieter der Liegenschaft aufteilen. ---
            if request.POST.get('modus') == 'verteilen':
                lg = k.liegenschaft
                if not lg:
                    messages.error(request, gettext('Für die Verteilung muss die Rechnung einer Liegenschaft zugeordnet sein.'))
                    return redirect(request.path)
                schluessel = request.POST.get('schluessel') or 'm2'
                grund_total = k.offen_weiterzuverrechnen
                if grund_total <= 0:
                    messages.error(request, gettext('Nichts mehr offen zum Weiterverrechnen.'))
                    return redirect(request.path)
                # Stichtag = Rechnungsdatum: Wer damals in der Wohnung war, trägt mit — auch
                # ein bereits GEKÜNDIGTER Mieter (wohnt bis zum Ende dort). Leere Einheiten
                # gehören zum Schlüssel, ihr Anteil bleibt beim Eigentümer: Vorher verteilte
                # der Modus alles auf die aktiven Mieter, und bei 4 Einheiten mit einem
                # Leerstand zahlten die 3 Mieter 100 % statt 75 % (Stresstest, Audit).
                stichtag = k.datum or heute
                einheiten = list(lg.einheiten.all())
                vertrag_je_einheit = {}
                for v in (Mietvertrag.objects.filter(status__in=('aktiv', 'gekuendigt'),
                                                     einheit__liegenschaft=lg, beginn__lte=stichtag)
                          .filter(Q(ende__isnull=True) | Q(ende__gte=stichtag))
                          .select_related('mieter', 'einheit').order_by('beginn')):
                    vertrag_je_einheit.setdefault(v.einheit_id, v)
                if not vertrag_je_einheit:
                    messages.error(request, gettext('Keine aktiven Mietverhältnisse in dieser Liegenschaft.'))
                    return redirect(request.path)

                def _gewicht(e):
                    if schluessel == 'einheit':
                        return Decimal('1')
                    if schluessel == 'wertquote':
                        return Decimal(str(e.wertquote or 0))
                    return Decimal(str(e.flaeche_m2 or 0))   # Default m²

                total_w = sum((_gewicht(e) for e in einheiten), Decimal('0'))
                if total_w <= 0:
                    messages.error(request, gettext('Für diesen Verteilschlüssel fehlen die Werte (m²/Wertquote) an den Objekten.'))
                    return redirect(request.path)
                gew = [(vertrag_je_einheit[e.pk], _gewicht(e)) for e in einheiten
                       if e.pk in vertrag_je_einheit and _gewicht(e) > 0]
                leerstand_w = sum((_gewicht(e) for e in einheiten if e.pk not in vertrag_je_einheit),
                                  Decimal('0'))
                anteile = [(v, (grund_total * w / total_w).quantize(Decimal('0.01'))) for v, w in gew]
                if leerstand_w <= 0 and anteile:
                    # Kein Leerstand: Der Rundungsrest geht an den letzten Mieter (Summe = Rechnung).
                    v_l, _a = anteile[-1]
                    anteile[-1] = (v_l, grund_total - sum((a for _, a in anteile[:-1]), Decimal('0.00')))
                eigentuemer_anteil = grund_total - sum((a for _, a in anteile), Decimal('0.00'))

                verteilt = Decimal('0.00'); anzahl = 0
                titel = (request.POST.get('titel') or f"Weiterverrechnung: {k.lieferant}").strip()
                for v, anteil in anteile:
                    if anteil <= 0:
                        continue
                    _verrechne(v, anteil, Decimal('0'), titel)
                    verteilt += anteil; anzahl += 1
                if eigentuemer_anteil > 0:
                    k.weiterverrechnung_eigentuemer = (k.weiterverrechnung_eigentuemer or Decimal('0.00')) + eigentuemer_anteil
                    k.save(update_fields=['weiterverrechnung_eigentuemer'])
                grund_total = verteilt
                log_aktion(request, "Weiterverrechnung verteilt", str(lg),
                           f"CHF {grund_total} aus {k.lieferant} auf {anzahl} Mieter ({schluessel})")
                messages.success(request, '✅ ' + gettext('CHF %(grund_total)s nach %(schluessel)s auf %(anzahl)s Mieter verteilt — QR-Rechnungen über den QR-Button in den Debitoren.') % {'grund_total': grund_total, 'schluessel': schluessel, 'anzahl': anzahl})
                if eigentuemer_anteil > 0:
                    messages.info(request, gettext('CHF %(betrag)s (Leerstand) bleiben beim Eigentümer.') % {'betrag': eigentuemer_anteil})
                return redirect('/neu/debitoren/')

            # --- Einzel-Weiterverrechnung an einen Mieter ---
            vertrag_id = request.POST.get('vertrag_id')
            vertrag = Mietvertrag.objects.filter(id=vertrag_id).select_related('mieter', 'einheit__liegenschaft').first()
            if not vertrag:
                messages.error(request, gettext('Bitte einen Mieter/Vertrag wählen.'))
                return redirect(request.path)
            grund = _dec(request.POST.get('betrag'), str(k.offen_weiterzuverrechnen))
            zuschlag = _dec(request.POST.get('zuschlag'), '0')
            if grund <= 0:
                messages.error(request, gettext('Betrag muss grösser als 0 sein.'))
                return redirect(request.path)
            grund = min(grund, k.offen_weiterzuverrechnen)
            titel = (request.POST.get('titel') or f"Weiterverrechnung: {k.lieferant}").strip()
            rechnung, total = _verrechne(vertrag, grund, zuschlag, titel)

            log_aktion(request, "Weiterverrechnung erstellt", str(vertrag.mieter),
                       f"CHF {total} aus {k.lieferant} (#{k.id})", ziel=vertrag)
            messages.success(request, '✅ ' + gettext('CHF %(total)s an %(mieter)s weiterverrechnet — QR-Rechnung über den QR-Button in den Debitoren.') % {'total': total, 'mieter': vertrag.mieter})
            if request.POST.get('embed') == '1':
                return render(request, 'fw/_modal_done.html', {})
            return redirect('/neu/debitoren/')

    # GET — aktive Verträge zur Auswahl
    vertraege = (Mietvertrag.objects.filter(status='aktiv')
                 .select_related('mieter', 'einheit__liegenschaft').order_by('einheit__liegenschaft__strasse'))
    if k.liegenschaft_id:
        bevorzugt = vertraege.filter(einheit__liegenschaft=k.liegenschaft)
        vertraege = list(bevorzugt) + [v for v in vertraege if v.einheit and v.einheit.liegenschaft_id != k.liegenschaft_id]
    else:
        vertraege = list(vertraege)

    # Live-Vorschau (wie bei der Ad-hoc-Rechnung): Empfänger je Vertrag + Absender
    vertrag_daten = {}
    for v in vertraege:
        m = v.mieter
        lg = v.einheit.liegenschaft if v.einheit_id else None
        vertrag_daten[str(v.id)] = {
            'mieter': m.display_name if m else '',
            'strasse': (m.strasse or '') if m else '',
            'plz': (m.plz or '') if m else '', 'ort': (m.ort or '') if m else '',
            'objekt': (v.einheit.bezeichnung if v.einheit_id else ''),
            'adresse': (f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else ''),
        }
    # Absenderblock INKLUSIVE IBAN — der gehoert der Verwaltung dieser
    # Kreditorenrechnung, nicht der ersten der Installation. Eine fremde IBAN
    # im Absender heisst im schlechtesten Fall: Der Mieter zahlt an die
    # falsche Bankverbindung (Audit 18.08.2026; der Alias `_Vw` liess die
    # Zeile durch jede Suche nach `Organisation.objects.first()` fallen).
    _vw = k.organisation
    absender = {
        'firma': _vw.firma if _vw else '', 'strasse': _vw.strasse if _vw else '',
        'plz': _vw.plz if _vw else '', 'ort': _vw.ort if _vw else '',
        'iban': (_vw.iban or '') if _vw else '',
    }
    # Verteil-Vorschau: aktive Mieter der Liegenschaft je Schlüssel
    verteil_mieter = 0
    if k.liegenschaft_id:
        verteil_mieter = Mietvertrag.objects.filter(status='aktiv', einheit__liegenschaft=k.liegenschaft).count()
    return render(request, 'fw/weiterverrechnung.html', {
        **basis, 'nav': 'kreditoren', 'k': k, 'vertraege': vertraege,
        'offen_wv': k.offen_weiterzuverrechnen, 'aufwand_konto': aufwand_konto,
        'vertrag_daten': vertrag_daten, 'absender': absender,
        'heute_iso': heute.isoformat(),
        'faellig_iso': (heute + _timedelta(days=30)).isoformat(),
        'ist_hnk': bool(k.is_hnk_relevant or k.hnk_betrag > 0),
        'verteil_mieter': verteil_mieter,
    })


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_debitor_abschreiben(request, pk):
    """Bucht eine uneinbringliche Forderung als Debitorenverlust ab (Aufwand 3805
    an Forderungen 1100 über den offenen Betrag, Status 'abgeschrieben').
    Teilzahlungen bleiben verbucht — abgeschrieben wird nur der Rest. Grund
    (z.B. Verlustschein) wird im Beleg + Logbuch festgehalten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    # Rücksprung: aus dem Zahlungs-Cockpit («Kleindifferenz ausbuchen») zurück
    # dorthin; nur eigene /neu/-Pfade (kein offener Redirect).
    _n = (request.POST.get('next') or '').strip()
    ziel = _n if _n.startswith('/neu/') and '//' not in _n and '\\' not in _n else 'fw_debitoren'
    if request.method != 'POST':
        return redirect(ziel)
    with transaction.atomic():
        # Zeilensperre: ohne sie schreiben zwei parallele Requests denselben
        # Betrag zweimal ab (Aufwand + MWST-Korrektur doppelt).
        r = get_object_or_404(
            DebitorenRechnung.objects.select_for_update(of=('self',))
            .select_related('vertrag__mieter'), id=pk)
        if r.status not in ('offen', 'teilbezahlt'):
            messages.info(request, gettext('Nur offene oder teilbezahlte Forderungen können abgeschrieben werden.'))
            return redirect(ziel)
        grund = (request.POST.get('grund') or '').strip()
        # Buchung und MWST-Korrektur im Dienst — dieselbe Stelle schreibt beim
        # Verlustschein einer Betreibung ab (core/services/debitorenverlust.py).
        from core.services.debitorenverlust import AbschreibungNichtMoeglich, forderung_abschreiben
        try:
            offen = forderung_abschreiben(r, grund, user=request.user)
        except AbschreibungNichtMoeglich as exc:
            messages.info(request, str(exc))
            return redirect(ziel)
    log_aktion(request, "Forderungsverlust gebucht", r.titel,
               f"CHF {offen} · {grund or 'ohne Grundangabe'}")
    messages.success(request, '✅ ' + gettext("Forderung '%(titel)s' als Debitorenverlust abgeschrieben (CHF %(offen)s, Konto 3805).") % {'titel': r.titel, 'offen': offen})
    return redirect(ziel)


def _mahngebuehr_historie_ausgleichen(rechnung, user=None):
    """Wird eine Mahngebühr-Forderung storniert, ist die in der Mahn-Historie
    (finance.Mahnung.gebuehr) ausgewiesene Gebühr gegenstandslos → auf 0 setzen
    (mit Vermerk). Ohne das zeigt die Historie z.B. weiter 40.-, obwohl die Gebühr
    per Gegenbuchung zurückgenommen wurde (Nutzer-Bug). Gibt die Anzahl korrigierter
    Historien-Einträge zurück."""
    import re
    from finance.models import Mahnung
    if not rechnung.stammrechnung_id:
        return 0
    m = re.match(r'\s*Mahngeb.hr\s+(\d)\.', rechnung.titel or '')
    if not m:
        return 0
    stufe = int(m.group(1))
    n = 0
    for mn in Mahnung.objects.filter(debitoren_rechnung_id=rechnung.stammrechnung_id,
                                     stufe=stufe, gebuehr__gt=0):
        alt = mn.gebuehr
        mn.gebuehr = Decimal('0.00')
        verm = f"Mahngebühr CHF {alt} storniert"
        mn.bemerkung = (f"{mn.bemerkung} · {verm}" if mn.bemerkung else verm)[:255]
        mn.save(update_fields=['gebuehr', 'bemerkung'])
        n += 1
    return n


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_debitor_stornieren(request, pk):
    """Storniert eine (versehentlich erstellte) Debitorenrechnung revisionssicher:
    Status → storniert und alle zugehörigen Buchungen werden per Gegenbuchung
    aufgehoben. Bereits (teil-)bezahlte Rechnungen werden blockiert — dort müssen
    zuerst die Zahlungen storniert werden."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchung, Zahlungseingang
    from finance.services import erstelle_storno_buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_debitoren')

    get_object_or_404(DebitorenRechnung, id=pk)         # fremde ID -> 404, bevor gesperrt wird
    n_folge = 0
    with transaction.atomic():
        # SPERREN, DANN PRÜFEN (Audit FIN-04): Drei parallele Klicks kehrten die
        # Buchungen der Rechnung mehrfach um (1100 um 2'200 überstorniert). Die
        # Prüfungen unten gelten für den Stand NACH dem Warten — und eine
        # Zahlung, die gerade verbucht wird, hält dieselbe Zeile.
        r = DebitorenRechnung.objects.select_for_update(of=('self',)).get(id=pk)
        if r.status == 'storniert':
            messages.info(request, gettext('Rechnung ist bereits storniert.'))
            return redirect('fw_debitoren')

        bezahlt = (Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht')
                   .exists())
        if bezahlt:
            messages.error(request, gettext('Diese Rechnung hat verbuchte Zahlungen — bitte zuerst die Zahlung(en) stornieren.'))
            return redirect('fw_debitoren')

        # Abgeleitete Mahngebühren/Zins-Forderungen mitstornieren: Wird die
        # Hauptforderung aufgehoben, ist auch die darauf gestellte Mahngebühr
        # gegenstandslos. Nur unbezahlte Folgeforderungen — eine bereits bezahlte
        # Mahngebühr bräuchte erst eine Zahlungsstornierung (Live-Test E).
        folge = list(DebitorenRechnung.objects.select_for_update(of=('self',))
                     .filter(stammrechnung=r).exclude(status='storniert'))
        folge_bezahlt = [f for f in folge
                         if Zahlungseingang.objects.filter(debitoren_rechnung=f, status='verbucht').exists()]
        # Nur noch nicht stornierte Originale umkehren (Doppel-Storno-Schutz).
        for b in Buchung.objects.filter(debitoren_rechnung=r, ist_storno=False,
                                        storniert_am__isnull=True):
            erstelle_storno_buchung(b, benutzer=request.user)
        r.status = 'storniert'
        r.save()
        # Wird eine Mahngebühr-Forderung selbst storniert, die Historien-Gebühr
        # gleich mit auf 0 ziehen (sonst zeigt die Mahn-Historie weiter z.B. 40.-).
        _mahngebuehr_historie_ausgleichen(r, request.user)
        for f in folge:
            if f in folge_bezahlt:
                continue
            for b in Buchung.objects.filter(debitoren_rechnung=f, ist_storno=False,
                                            storniert_am__isnull=True):
                erstelle_storno_buchung(b, benutzer=request.user)
            f.status = 'storniert'
            f.save(update_fields=['status'])
            _mahngebuehr_historie_ausgleichen(f, request.user)
            n_folge += 1

    log_aktion(request, "Debitorenrechnung storniert", r.titel,
               f"CHF {r.betrag}" + (f" · {n_folge} Mahngebühr(en) mitstorniert" if n_folge else ""))
    hinweis = f" {n_folge} zugehörige Mahngebühr(en) mitstorniert." if n_folge else ""
    if folge_bezahlt:
        hinweis += (f" {len(folge_bezahlt)} bereits bezahlte Mahngebühr(en) blieben bestehen — "
                    f"dort zuerst die Zahlung stornieren.")
    messages.success(request, '✅ ' + gettext("Rechnung '%(titel)s' storniert (revisionssicher, mit Gegenbuchung).%(hinweis)s") % {'titel': r.titel, 'hinweis': hinweis})
    ziel = '/neu/debitoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)
