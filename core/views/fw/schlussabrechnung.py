# core/views/fw/schlussabrechnung.py
#
# Schlussabrechnung beim Auszug: Kaution, Guthaben, Restforderungen.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md. Herausgeloest aus detailseiten.py.

from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext

from core.auth import (rolle_erforderlich, SCHREIB_ROLLEN)
from finance.freigabe import AuszahlungGesperrt
from finance.models import DebitorenRechnung, Zahlungseingang
from rentals.models import Mietvertrag

from ._basis import (_global_filter, _kaution_bilanziert, _num)


GUTHABEN_AUSBEZAHLT = '[ausbezahlt]'


def _guthaben_positionen(vertrag):
    """Noch nicht ausbezahlte Mieterguthaben (2030) dieses Vertrags."""
    from finance.models import Zahlungseingang as _Z
    return list(_Z.objects.filter(vertrag=vertrag, status='verbucht', konto__nummer='2030')
                .exclude(bemerkung__contains=GUTHABEN_AUSBEZAHLT))


def _guthaben_bilanziert(vertrag):
    """Summe der noch offenen Mieterguthaben (2030) dieses Vertrags."""
    return sum((z.betrag for z in _guthaben_positionen(vertrag)),
               Decimal('0.00')).quantize(Decimal('0.01'))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schlussabrechnung(request, vertrag_id):
    """Schlussabrechnung beim Auszug: offene Forderungen + NK-Saldo + Schäden −
    Kaution = Saldo. GET zeigt Formular, POST erzeugt PDF (aktion=pdf) oder
    verbucht Kaution + Nachzahlung (aktion=buchen)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from crm.models import Organisation
    from core.services.schlussabrechnung import berechne_schlussabrechnung, generate_schlussabrechnung_pdf
    from core.auth import log_aktion

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)

    def _dec(x):
        try:
            return Decimal(_num(x))
        except Exception:
            return Decimal('0.00')

    if request.method == 'POST':
        try:
            auszug = date.fromisoformat(request.POST.get('auszug_datum') or '')
        except Exception:
            auszug = v.ende or timezone.localdate()
        kaution_verrechnen = request.POST.get('kaution_verrechnen') == 'on'

        positionen = []
        texte = request.POST.getlist('pos_text')
        betraege = request.POST.getlist('pos_betrag')
        richtungen = request.POST.getlist('pos_richtung')
        # `pos_mwst` ist ein <select> (nicht Checkbox), damit die Indizes mit den
        # übrigen Listen ausgerichtet bleiben — eine nicht angehakte Checkbox
        # sendet gar nichts und würde die Zuordnung verschieben.
        steuerflags = request.POST.getlist('pos_mwst')
        for i, txt in enumerate(texte):
            txt = (txt or '').strip()
            betr = _dec(betraege[i] if i < len(betraege) else '0')
            if not txt or betr == 0:
                continue
            richtung = richtungen[i] if i < len(richtungen) else 'zulasten'
            steuerbar = (steuerflags[i] if i < len(steuerflags) else '0') == '1'
            positionen.append({'text': txt, 'betrag': betr,
                               'zulasten': (richtung == 'zulasten'),
                               'steuerbar': steuerbar})

        # Die bilanzierte Kaution (2010-Saldo) als Obergrenze mitgeben, damit
        # Anzeige/PDF exakt das gutschreiben, was die Buchung freigibt (QS-Befund).
        daten = berechne_schlussabrechnung(v, auszug, positionen,
                                           kaution_verrechnen=kaution_verrechnen,
                                           kaution_bilanziert=_kaution_bilanziert(v))
        aktion = request.POST.get('aktion', 'pdf')

        if aktion == 'buchen':
            # Idempotenz: eine Schlussabrechnung wird pro Vertrag nur EINMAL verbucht.
            # Ohne diese Sperre erzeugte ein Doppelklick / Zurück-Navigieren einen
            # zweiten Nachzahlungs-Debitor + eine doppelte 1100/3000-Buchung.
            #
            # Geprüft werden die BUCHUNGSSPUREN, nicht `kautions_zurueckbezahlt_am`:
            # Letzteres wird auch gesetzt, wenn die Kaution separat zurückbezahlt
            # wurde — dann war die Schlussabrechnung komplett blockiert, obwohl sie
            # noch nie lief. Umgekehrt fehlte eine Sperre für den Gutschrift-Fall
            # ohne Kaution, wo ein Doppelklick zweimal Mieterguthaben buchte (Audit).
            from finance.models import Buchung as _BIdem

            def _schon_verbucht():
                return (
                    DebitorenRechnung.objects.filter(
                        vertrag=v, titel="Schlussabrechnung (Nachzahlung)"
                    ).exclude(status='storniert').exists()
                    # storniert_am mitprüfen — sonst widerspricht diese Hälfte der
                    # ersten: die schliesst stornierte Rechnungen bereits aus, damit
                    # eine Schlussabrechnung nach einem Storno neu erstellt werden
                    # kann. Ohne den Filter blockierte die stehengebliebene
                    # Original-Buchung genau das.
                    or _BIdem.objects.filter(
                        beleg_text__contains=f"Schlussabrechnung [V{v.pk}]",
                        ist_storno=False, storniert_am__isnull=True
                    ).exists()
                )

            def _bereits_verbucht_antwort():
                if request.POST.get('embed'):
                    return render(request, 'fw/_modal_done.html', {'msg': 'Schlussabrechnung bereits verbucht'})
                messages.info(request, gettext('Diese Schlussabrechnung wurde bereits verbucht.'))
                return redirect(f'/neu/vertraege/{v.id}/')

            if _schon_verbucht():
                return _bereits_verbucht_antwort()
            try:
                with transaction.atomic():
                    # GESPERRT, DANN ERNEUT GEPRÜFT: Die Prüfung oben stammt von VOR
                    # dem Warten. Zwei gleichzeitige Klicks buchten die Kaution
                    # zweimal frei und stellten zwei Nachzahlungs-Rechnungen.
                    Mietvertrag.objects.select_for_update(of=('self',)).get(pk=v.pk)
                    if _schon_verbucht():
                        return _bereits_verbucht_antwort()
                    from finance.booking import buche
                    heute = timezone.localdate()
                    lg_s = v.einheit.liegenschaft if v.einheit_id else None
                    dat_s = auszug or heute

                    # ── 1) NUR die NEUEN Positionen buchen (Schäden, Reinigung, NK-Saldo) ──
                    # Bereits gestellte Mietforderungen bleiben unangetastet: Storno +
                    # Neubuchung auf 3000 (früheres Verhalten) vernichtete deren MWST-
                    # Abgrenzung (2200) und verschob Schadenersatz in den Mietertrag —
                    # was Mieterspiegel und Honorarbasis verfälschte (Audit K2/W5).
                    neu_saldo = (daten['zwischen'] - daten['offen_total']).quantize(Decimal('0.01'))
                    # MWST-Anteil aus dem Gesamtbetrag herauslösen: `zwischen`
                    # enthält ihn bereits als eigene Zeile. Der Ertrag (3600) darf
                    # nur den Nettoteil bekommen, die Steuer gehört auf 2200 —
                    # sonst fehlt sie in der ESTV-Abrechnung (Audit).
                    mwst_neu = daten.get('mwst_neu') or Decimal('0.00')
                    netto_neu = (neu_saldo - mwst_neu).quantize(Decimal('0.01'))
                    if neu_saldo > 0:
                        rech = DebitorenRechnung.objects.create(
                            vertrag=v, liegenschaft=lg_s, einheit=v.einheit,
                            titel="Schlussabrechnung (Nachzahlung)", datum=dat_s,
                            faellig_am=dat_s + _timedelta(days=30), betrag=neu_saldo, status='offen',
                            forderungsart='sonstige',     # Schäden und Saldo gemischt: nicht Art. 257d
                            mwst_satz=(daten.get('mwst_satz') or Decimal('0.0')) if mwst_neu > 0 else Decimal('0.0'),
                            mwst_betrag=mwst_neu if mwst_neu > 0 else Decimal('0.00'))
                        if netto_neu != 0:
                            buche("1100", "3600", netto_neu,
                                  f"Schlussabrechnung [V{v.pk}] {v.mieter} (Schäden/Nebenkosten)",
                                  datum=dat_s, liegenschaft=lg_s, debitor=rech, user=request.user)
                        if mwst_neu > 0:
                            buche("1100", "2200", mwst_neu,
                                  f"MWST Schlussabrechnung [V{v.pk}] {v.mieter}",
                                  datum=dat_s, liegenschaft=lg_s, debitor=rech, user=request.user)
                    elif neu_saldo < 0:
                        # Gutschrift zugunsten Mieter → als echtes Guthaben (2030) führen,
                        # damit es im Mieterkonto sichtbar und auszahlbar ist.
                        from finance.booking import konto as _k_s
                        # REIHENFOLGE ist Pflicht: erst den Zahlungseingang anlegen, DANN
                        # mit `zahlung=` buchen. Der Storno hebt nur Buchungen auf, die an
                        # einem Zahlungseingang hängen — sonst bleibt nach einem Storno das
                        # Guthaben im Hauptbuch stehen, das Nebenbuch aber nicht (Audit).
                        z_gut = Zahlungseingang.objects.create(
                            vertrag=v, betrag=abs(neu_saldo), datum_eingang=dat_s,
                            buchungs_monat=dat_s.replace(day=1),
                            bemerkung="Schlussabrechnung — Guthaben Mieter"[:255],
                            konto=_k_s("2030"), liegenschaft=lg_s,
                            erstellt_von=request.user, status='verbucht')
                        if netto_neu != 0:
                            buche("3600", "2030", abs(netto_neu),
                                  f"Schlussabrechnung [V{v.pk}] {v.mieter} — Gutschrift",
                                  datum=dat_s, liegenschaft=lg_s, zahlung=z_gut, user=request.user)
                        if mwst_neu < 0:
                            # Spiegelbildliche Steuerkorrektur: der Umsatz wird
                            # gemindert, also auch die geschuldete MWST.
                            buche("2200", "2030", abs(mwst_neu),
                                  f"MWST-Korrektur Schlussabrechnung [V{v.pk}] {v.mieter}",
                                  datum=dat_s, liegenschaft=lg_s, zahlung=z_gut, user=request.user)

                    # ── 2) Kaution bilanziell abwickeln (Audit K3) ──
                    # Früher wurden nur Vertragsfelder gesetzt — 1015/2010 blieben ewig
                    # in der Bilanz stehen (stille Drift bei jedem Mieterwechsel).
                    #   Sperrkonto freigeben:  1020 an 1015
                    #   Verrechnung mit OP:    2010 an 1100
                    #   Rest an Mieter:        2010 an 1020
                    # Freigegeben werden darf nur, was tatsächlich in der Bilanz steht.
                    # Das Vertragsfeld `kautions_betrag` ist bloss der VEREINBARTE Betrag —
                    # ohne diese Prüfung wurde eine nie einbezahlte Kaution «freigegeben»
                    # und ausbezahlt: 1015 und 2010 rutschten ins Minus und offene
                    # Mietforderungen galten als getilgt (Audit, kritisch).
                    kaution_bil = _kaution_bilanziert(v)
                    #: Was in diesem Schritt an den Mieter geht (Kaution; unten kommt das Guthaben dazu).
                    #: Grundlage des Vier-Augen-Prinzips (Etappe 4), Schritt 3.
                    auszahlung_gesamt = Decimal('0.00')
                    if kaution_verrechnen and (v.kautions_betrag or 0) > 0 \
                            and kaution_bil <= 0 and not v.ist_kautionsversicherung:
                        # Kaution vereinbart, aber nie eingegangen (oder bereits
                        # aufgelöst): das Kautionsthema ist mit dem Auszug erledigt,
                        # es gibt aber nichts freizugeben und nichts auszuzahlen.
                        v.kautions_zurueckbezahlt_am = auszug
                        v.kautions_rueckzahlung_betrag = Decimal('0.00')
                        v.kautions_abzug_betrag = Decimal('0.00')
                        v.save(update_fields=['kautions_zurueckbezahlt_am',
                                              'kautions_rueckzahlung_betrag',
                                              'kautions_abzug_betrag'])
                        messages.warning(request,
                            gettext('Hinweis: Für diesen Vertrag ist keine Kaution bilanziert (vereinbart CHF %(kautions_betrag)s). Es wurde weder ein Sperrkonto freigegeben noch eine Rückzahlung gebucht.') % {'kautions_betrag': v.kautions_betrag})
                    if kaution_verrechnen and (v.kautions_betrag or 0) > 0 \
                            and (kaution_bil > 0 or v.ist_kautionsversicherung):
                        kaution = min(v.kautions_betrag or Decimal('0.00'), kaution_bil)
                        v.kautions_zurueckbezahlt_am = auszug
                        if v.ist_kautionsversicherung:
                            # Versicherung: kein Depot, keine Rückzahlung an den Mieter.
                            v.kautions_rueckzahlung_betrag = Decimal('0.00')
                            v.save()
                        else:
                            # Offene Forderungen NACH Schritt 1 (inkl. neuer Schlussabrechnung)
                            offene_op = list(DebitorenRechnung.objects
                                             .filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
                                             .order_by('faellig_am', 'id'))
                            offen_nachher = sum((r.offener_betrag for r in offene_op), Decimal('0.00'))
                            verrechnet = min(kaution, offen_nachher)
                            rueck = (kaution - verrechnet).quantize(Decimal('0.01'))
                            v.kautions_rueckzahlung_betrag = rueck
                            v.kautions_abzug_betrag = verrechnet
                            v.save()
                            from finance.models import Buchung as _BS
                            beleg_k = f"Kaution Schlussabrechnung [V{v.pk}] {v.mieter}"
                            noch_nicht_gebucht = not _BS.objects.filter(
                                beleg_text__startswith=beleg_k, ist_storno=False,
                                storniert_am__isnull=True).exists()
                            if noch_nicht_gebucht:
                                buche("1020", "1015", kaution, f"{beleg_k} — Sperrkonto freigegeben",
                                      datum=dat_s, liegenschaft=lg_s, user=request.user)
                                # Die VERRECHNUNG (2010 an 1100) wird unten je Forderung gebucht,
                                # jeweils am zugehörigen Zahlungseingang: nur so hebt der Storno
                                # einer Verrechnung ihre Buchung mit auf.
                                if rueck > 0:
                                    auszahlung_gesamt += rueck
                                    buche("2010", "1020", rueck, f"{beleg_k} — Rückzahlung an Mieter",
                                          datum=dat_s, liegenschaft=lg_s, user=request.user)
                            # OP-Nebenbuch nachführen: die verrechnete Kaution tilgt die
                            # offenen Rechnungen (sonst Drift Hauptbuch 1100 ↔ Debitorenliste).
                            rest_v = verrechnet
                            for r_op in offene_op:
                                if rest_v <= 0:
                                    break
                                teil = min(rest_v, r_op.offener_betrag)
                                if teil <= 0:
                                    continue
                                z_verr = Zahlungseingang.objects.create(
                                    vertrag=v, betrag=teil, datum_eingang=dat_s,
                                    buchungs_monat=(r_op.faellig_am or r_op.datum or dat_s).replace(day=1),
                                    bemerkung=f"Verrechnung Mietkaution — {r_op.titel}"[:255],
                                    debitoren_rechnung=r_op, liegenschaft=lg_s,
                                    erstellt_von=request.user, status='verbucht')
                                if noch_nicht_gebucht:
                                    buche("2010", "1100", teil,
                                          f"{beleg_k} — Verrechnung offene Forderungen ({r_op.titel})",
                                          datum=dat_s, liegenschaft=lg_s, debitor=r_op,
                                          zahlung=z_verr, user=request.user)
                                r_op.status = 'bezahlt' if r_op.offener_betrag <= 0 else 'teilbezahlt'
                                r_op.save(update_fields=['status'])
                                rest_v -= teil

                    # ── 3) Mieterguthaben (2030) mit auszahlen ──
                    # Ein Guthaben aus Schritt 1 wäre sonst eine Sackgasse: die
                    # Schlussabrechnung weist es dem Mieter als Rückzahlung aus, gebucht
                    # wurde aber nur die Kaution — der Rest bliebe für einen längst
                    # ausgezogenen Mieter dauerhaft auf 2030 stehen (Audit).
                    guthaben_pos = _guthaben_positionen(v)
                    guthaben_offen = sum((z.betrag for z in guthaben_pos), Decimal('0.00'))
                    # VIER-AUGEN-PRINZIP (Etappe 4): Kaution und Guthaben gehen zusammen an den Mieter.
                    # Erreicht die Summe die Freigabelimite, braucht die Auszahlung die Freigabe einer
                    # zweiten Person; fehlt sie, rollt die ganze Schlussabrechnung zurück
                    # (`AuszahlungGesperrt`, unten gemeldet). Die Prüfung gilt für die Summe, damit sich
                    # eine Auszahlung nicht in Kaution und Guthaben unter der Limite zerlegen lässt.
                    auszahlung_gesamt += guthaben_offen
                    if auszahlung_gesamt > 0:
                        from finance.freigabe import auszahlung_pruefen
                        auszahlung_pruefen('schlussabrechnung', v.pk, auszahlung_gesamt, v.mieter.iban,
                                           organisation=v.organisation, bezug_text=str(v.mieter))
                    if guthaben_offen > 0:
                        # Je Guthaben-Position gebucht und am Zahlungseingang verankert: Ein
                        # Storno der Position hebt so auch ihre Auszahlung auf.
                        for z_g in guthaben_pos:
                            buche("2030", "1020", z_g.betrag,
                                  f"Schlussabrechnung [V{v.pk}] {v.mieter} — Guthaben ausbezahlt",
                                  datum=dat_s, liegenschaft=lg_s, zahlung=z_g, user=request.user)
                        for z_g in guthaben_pos:
                            z_g.bemerkung = f"{z_g.bemerkung} {GUTHABEN_AUSBEZAHLT}"[:255]
                            z_g.save(update_fields=['bemerkung'])
                        v.kautions_rueckzahlung_betrag = (
                            (v.kautions_rueckzahlung_betrag or Decimal('0.00')) + guthaben_offen)
                        v.save(update_fields=['kautions_rueckzahlung_betrag'])
            except AuszahlungGesperrt as gesperrt:
                from core.views.fw.zahlungsfreigabe import auszahlung_gesperrt_melden
                auszahlung_gesperrt_melden(request, gesperrt)
                if request.POST.get('embed'):
                    return render(request, 'fw/_modal_done.html', {'msg': gettext('Die Auszahlung braucht die Freigabe einer zweiten Person.')})
                return redirect(f'/neu/vertraege/{v.id}/')
            except PermissionError as exc:
                # Rückdatierter Auszug in eine gesperrte Periode: als Meldung
                # zeigen statt als HTTP 500 (Audit).
                messages.error(request, f"❌ {exc}")
                return redirect(f'/neu/vertraege/{v.id}/')
            from core.services.automation import erledige_pendenzen_fuer
            erledige_pendenzen_fuer(v, ['Schlussabrechnung', 'Kaution'], user=request.user)
            log_aktion(request, "Schlussabrechnung verbucht", str(v.mieter), f"Saldo CHF {daten['saldo']}", ziel=v)
            if request.POST.get('embed'):
                return render(request, 'fw/_modal_done.html', {'msg': gettext('Schlussabrechnung verbucht')})
            messages.success(request, '✅ ' + (
                gettext('Schlussabrechnung verbucht (Kaution abgerechnet, Nachzahlung als Debitor gestellt).')
                if daten['nachzahlung'] else gettext('Schlussabrechnung verbucht (Kaution abgerechnet).')))
            return redirect(f'/neu/vertraege/{v.id}/')

        try:
            pdf = generate_schlussabrechnung_pdf(v, daten, verwaltung=v.organisation)
        except Exception as e:
            messages.error(request, '❌ ' + gettext('PDF konnte nicht erstellt werden: %(e)s') % {'e': e})
            return redirect(f'/neu/vertraege/{v.id}/schlussabrechnung/')
        from core.services.ablage import ablegen
        ablegen(pdf, "Schlussabrechnung", kategorie='korrespondenz', vertrag=v, dedup=True)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Schlussabrechnung_{v.mieter.nachname}.pdf"'
        return resp

    # GET
    offene = DebitorenRechnung.objects.filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
    offen_total = sum((r.offener_betrag for r in offene), Decimal('0.00'))
    # Bereits erfasste Schaden-/Einbehalts-Forderung (z.B. aus „Police auflösen") als
    # Position vorbelegen, damit sie in der Schlussabrechnung sichtbar mitzählt.
    schaden_betrag = v.kautions_abzug_betrag or Decimal('0.00')
    schaden_text = v.kautions_abzug_grund or ('Schadenforderung' if schaden_betrag > 0 else '')
    # Mängel aus einem Abnahmeprotokoll (Verursacher = Mieter) als Positionen vorbelegen
    prefill_positionen = []
    # OHNE ausdrückliche Wahl gilt das jüngste Auszugsprotokoll: Der Bewirtschafter
    # tippte die Mängel (Mieteranteil CHF 860 im Stresstest) sonst erneut ab, obwohl
    # sie im Protokoll stehen.
    from core.utils.parameter import id_param
    ab_id = id_param(request.GET.get('abnahme'))        # `?abnahme=abc` gilt als nicht angegeben
    from rentals.models import Abnahmeprotokoll
    if ab_id:
        ab = Abnahmeprotokoll.objects.filter(id=ab_id, vertrag=v).first()
    else:
        from core.services.abnahme_vorgaenger import durchgefuehrt
        ab = durchgefuehrt(v.abnahmen.filter(typ='auszug')).order_by('-datum', '-id').first()
    if ab:
        for m in ab.maengel_mieter:
            betrag = m.mieteranteil if m.mieteranteil is not None else m.kostenschaetzung
            if betrag:
                txt = f"{m.raum + ': ' if m.raum else ''}{m.beschreibung}"
                if m.mieteranteil is not None and m.ausstattung_id:
                    txt += " (Zeitwert)"
                prefill_positionen.append({'text': txt[:90], 'betrag': betrag})
        # Fehlende Schlüssel gehen wie Mängel in die Belastung des Mieters.
        from core.services.abnahme_abschluss import schluessel_positionen
        prefill_positionen.extend(schluessel_positionen(ab))
    if schaden_betrag > 0:
        prefill_positionen.insert(0, {'text': schaden_text, 'betrag': schaden_betrag})
    return render(request, 'fw/schlussabrechnung.html', {
        **basis, 'nav': 'vertraege', 'v': v,
        'offen_total': offen_total,
        'kaution': v.kautions_betrag or Decimal('0.00'),
        'ist_versicherung': v.ist_kautionsversicherung,
        'schaden_prefill_betrag': schaden_betrag,
        'schaden_prefill_text': schaden_text,
        'prefill_positionen': prefill_positionen,
        'auszug_default': (v.ende or timezone.localdate()).isoformat(),
        'abnahmen': v.abnahmen.all(),
        'embed_base': ('fw/base_embed.html' if request.GET.get('embed') == '1' else None),
    })
