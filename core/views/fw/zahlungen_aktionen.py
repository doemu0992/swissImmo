# core/views/fw/zahlungen_aktionen.py
#
# Zahlungen zuordnen, Bankbewegungen, MWST verbuchen, Zahlung stornieren.
# Aus aktionen.py herausgeloest (reiner Umzug ohne Aenderung am Code).

import calendar as _calendar
from datetime import date
from decimal import Decimal

from django.utils.translation import gettext
from django.db import transaction
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich)
from core.auth import FINANZ_LESE_ROLLEN, FINANZ_SCHREIB_ROLLEN, FINANZ_VERWALTUNGS_ROLLEN
from finance.models import DebitorenRechnung, Zahlungseingang
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag


from ._basis import (_global_filter, _mwst_beleg, _mwst_bereits_verbucht,
                     _mwst_periode)


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
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
            messages.error(request, gettext('Periodensperre: %(e)s') % {'e': e})
            return redirect('fw_bankabgleich')

    log_aktion(request, "Geparkte Zahlung zugeordnet", str(vertrag),
               f"CHF {betrag} von {park_nr} auf {rechnung.titel}"
               + (f" · Absender «{gelernt}» gemerkt" if gelernt else ""))
    messages.success(request, '✅ ' + gettext('CHF %(betrag)s zugeordnet — %(display_name)s (%(titel)s)%(wert)s.') % {'betrag': betrag, 'display_name': vertrag.mieter.display_name, 'titel': rechnung.titel, 'wert': f' · Rest CHF {rest} bleibt als Guthaben' if rest > 0 else ''})
    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'
    from django.shortcuts import redirect as _r
    return _r(ziel)


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
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
        messages.warning(request, gettext('Keine Zahlung ausgewählt.'))
        return redirect(ziel)
    if vertrag is None:
        messages.error(request, gettext('Kein Mieter gewählt — die Zahlungen bleiben ungeklärt.'))
        return redirect(ziel)

    with transaction.atomic():
        # Zeilensperre wie bei der Einzelzuordnung: sonst bucht ein paralleler
        # Lauf dieselbe Forderung ein zweites Mal aus.
        #
        # HIER BRAUCHT ES KEIN `of=('self',)`, obwohl `Zahlungseingang.konto`
        # optional ist. Der Grund ist der `filter` eine Zeile darunter: Eine
        # Bedingung auf `konto__nummer` kann nur erfuellt sein, wenn ein Konto
        # da ist, also joint Django INNER — und `select_related('konto')`
        # benutzt denselben Join weiter. Auf PostgreSQL nachgemessen (E0.3):
        # kein LEFT JOIN, die Sperre laeuft.
        #
        # Faellt der `konto__nummer`-Filter jemals weg, kippt der Join auf LEFT
        # und PostgreSQL verweigert die Sperre. Dann gehoert `of=('self',)`
        # dazu, wie bei den beiden Stellen, die es schon tragen.
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
        teile = [gettext('%(anzahl)s Zahlung(en) zugeordnet (CHF %(summe)s) — %(name)s')
                 % {'anzahl': anzahl, 'summe': summe, 'name': vertrag.mieter.display_name}]
        if rest:
            teile.append(gettext('CHF %(rest)s bleiben als Guthaben') % {'rest': rest})
        if gelernt:
            teile.append(gettext('Absender «%(gelernt)s» gemerkt, künftige Zahlungen treffen selbst')
                         % {'gelernt': gelernt})
        messages.success(request, '✅ ' + ' · '.join(teile) + '.')
    for f in fehler:
        messages.warning(request, gettext('Nicht zugeordnet — %(f)s') % {'f': f})
    if not anzahl and not fehler:
        messages.warning(request, gettext('Nichts zugeordnet — die gewählten Zahlungen liegen nicht mehr auf einem Parkkonto.'))
    return redirect(ziel)


@rolle_erforderlich(*FINANZ_LESE_ROLLEN)
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


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
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
        messages.error(request, gettext('Diese Zuordnung gibt es nicht mehr.'))
        return redirect('fw_zahler_zuordnungen')

    name = eintrag.name_anzeige or eintrag.name_norm

    if request.POST.get('aktion') == 'loeschen':
        eintrag.delete()
        log_aktion(request, "Zahler-Zuordnung gelöscht", name, '')
        messages.success(request, '✅ ' + gettext('«%(name)s» wird nicht mehr automatisch zugeordnet — künftige Zahlungen landen wieder zur Prüfung im Bankabgleich.') % {'name': name})
        return redirect('fw_zahler_zuordnungen')

    ziel = (Mietvertrag.objects.filter(id=request.POST.get('vertrag_id') or 0)
            .select_related('mieter').first())
    if ziel is None:
        messages.error(request, gettext('Kein Mieter gewählt — die Zuordnung bleibt unverändert.'))
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
    messages.success(request, '✅ ' + gettext('«%(name)s» zahlt neu für %(display_name)s. Bereits verbuchte Zahlungen bleiben unverändert.') % {'name': name, 'display_name': ziel.mieter.display_name})
    return redirect('fw_zahler_zuordnungen')


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
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
        messages.info(request, gettext('Diese Bankbewegung ist bereits erledigt.'))
        return redirect(ziel)

    art = request.POST.get('art')
    # Das VALUTADATUM ist buchhalterisch massgebend; vorher landete jede Zahlung
    # im Datum des Erfassungstags (Praxis-Audit).
    dat = bew.valuta or bew.datum
    bank_nr = bew.konto.nummer
    betrag = abs(bew.betrag)

    if art == 'ignorieren':
        with transaction.atomic():
            # Gesperrt und danach geprüft: Läuft gleichzeitig eine Verbuchung
            # derselben Bewegung, darf «ignorieren» sie nicht überschreiben.
            bew = Bankbewegung.objects.select_for_update().get(pk=bew.pk)
            if bew.status != 'offen':
                messages.info(request, gettext('Diese Bankbewegung ist bereits erledigt.'))
                return redirect(ziel)
            bew.status = 'ignoriert'
            bew.bemerkung = (request.POST.get('bemerkung') or 'Nicht buchungsrelevant')[:255]
            bew.save(update_fields=['status', 'bemerkung'])
        log_aktion(request, "Bankbewegung ignoriert", str(bew), bew.bemerkung)
        messages.success(request, gettext('Bewegung als nicht buchungsrelevant markiert.'))
        return redirect(ziel)

    if art == 'rueckbuchung':
        # Die Bank bucht eine Mieterzahlung zurück (Rücklastschrift, Rückweisung):
        # Die ursprüngliche Zahlung wird storniert, die Rechnung ist wieder offen.
        # Die Stornobuchung ist die Buchung dieser Belastung (Zahlungs-Cockpit V12).
        from core.services.zahlungsklaerung import rueckbuchung, ZuordnungsFehler
        z = get_object_or_404(Zahlungseingang, id=request.POST.get('zahlung_id'))
        try:
            with transaction.atomic():
                bew = Bankbewegung.objects.select_for_update().get(pk=bew.pk)
                rueckbuchung(bew, z, user=request.user)
        except ZuordnungsFehler as exc:
            messages.error(request, f"❌ {exc}")
            return redirect(ziel)
        except PermissionError as exc:
            messages.error(request, f"❌ {exc}")
            return redirect(ziel)
        log_aktion(request, "Rückbuchung einer Mieterzahlung", str(bew),
                   f"Zahlung #{z.pk} CHF {abs(bew.betrag)} storniert")
        messages.success(request, '✅ ' + gettext('Rückbuchung erfasst: Die Zahlung vom %(datum)s ist storniert, die Rechnung wieder offen.') % {'datum': format(z.datum_eingang, '%d.%m.%Y')})
        return redirect(ziel)

    try:
        with transaction.atomic():
            # SPERREN, DANN PRÜFEN: Der Status oben stammt von VOR dem Warten.
            # Zwei parallele Verbuchungen derselben Auszugszeile buchten sonst
            # zweimal; die Zeile wird gesperrt und ihr Zustand neu gelesen.
            bew = Bankbewegung.objects.select_for_update().get(pk=bew.pk)
            if bew.status != 'offen':
                messages.info(request, gettext('Diese Bankbewegung ist bereits erledigt.'))
                return redirect(ziel)
            if art == 'kreditor':
                from finance.models import KreditorenZahlung
                kr = get_object_or_404(KreditorenRechnung.objects.select_for_update(of=('self',)),
                                       id=request.POST.get('kreditor_id'))
                if bew.betrag >= 0:
                    messages.error(request, gettext('Eine Gutschrift kann keine Lieferantenrechnung tilgen.'))
                    return redirect(ziel)
                offen_kr = kr.offener_betrag
                if offen_kr <= 0:
                    messages.error(request, gettext('Diese Lieferantenrechnung ist bereits bezahlt.'))
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
                    messages.error(request, gettext('Bitte ein gültiges Gegenkonto angeben.'))
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
        messages.error(request, '❌ ' + gettext('Bewegung konnte nicht gebucht werden: %(exc)s') % {'exc': exc})
        return redirect(ziel)

    log_aktion(request, "Bankbewegung verbucht", str(bew), text)
    messages.success(request, '✅ ' + gettext('CHF %(betrag)s verbucht (%(text)s) — Valuta %(dat)s.') % {'betrag': betrag, 'text': text, 'dat': format(dat, '%d.%m.%Y')})
    return redirect(ziel)


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
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
        messages.info(request, gettext('Diese MWST-Periode wurde bereits verbucht.'))
        return redirect(ziel)

    # Beträge NEU aus dem Hauptbuch rechnen statt aus dem POST übernehmen — sonst
    # bestimmt der Client, was der ESTV geschuldet wird (Audit).
    p = _mwst_periode(jahr, quartal, aktive_lg)
    umsatzsteuer, vorsteuer = p['umsatzsteuer'], p['vorsteuer']
    zahllast, methode = p['zahllast'], p['methode']
    if umsatzsteuer <= 0 and vorsteuer <= 0:
        messages.info(request, gettext('Für diese Periode gibt es keine MWST zu verbuchen.'))
        return redirect(ziel)

    beleg = _mwst_beleg(jahr, quartal)
    ende = date(jahr, 12, 31) if quartal not in ('1', '2', '3', '4') else \
        date(jahr, int(quartal) * 3, _calendar.monthrange(jahr, int(quartal) * 3)[1])
    try:
        with transaction.atomic():
            # GESPERRT, DANN ERNEUT GEPRÜFT: «Schon verbucht?» oben stammt von VOR
            # dem Warten. Zwei gleichzeitige Klicks buchten die Zahllast doppelt.
            from core.sperren import sperre_organisation
            from core.tenancy import organisation_der_anfrage
            sperre_organisation('mwst_verbuchen', organisation_der_anfrage(request).pk)
            if _mwst_bereits_verbucht(jahr, quartal, aktive_lg):
                messages.info(request, gettext('Diese MWST-Periode wurde bereits verbucht.'))
                return redirect(ziel)
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
        messages.error(request, '❌ ' + gettext('MWST-Abrechnung konnte nicht verbucht werden: %(exc)s') % {'exc': exc})
        return redirect(ziel)

    log_aktion(request, "MWST-Abrechnung verbucht", beleg, f"Zahllast CHF {zahllast}")
    messages.success(request, '✅ ' + gettext('%(beleg)s verbucht — Zahllast CHF %(zahllast)s (%(wert)s).') % {'beleg': beleg, 'zahllast': zahllast, 'wert': 'Saldosteuersatz' if methode == 'saldo' else 'effektive Methode'})
    return redirect(ziel)


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_zahlung_stornieren(request, pk):
    """Storniert einen Zahlungseingang revisionssicher (Audit W7): Gegenbuchungen
    zu allen Buchungen der Zahlung, Status → storniert, OP-Status der Rechnung
    wird zurückgerollt. Bisher gab es das nur in der Alt-API — eine falsch
    zugeordnete Zahlung war in der neuen Oberfläche nur per Handbuchung zu
    korrigieren (und der OP-Status blieb falsch)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    from core.services.zahlungsklaerung import stornieren

    if request.method != 'POST':
        return redirect('fw_bankabgleich')
    try:
        with transaction.atomic():
            # Zeilensperre: zwei parallele Stornos würden sonst doppelte
            # Gegenbuchungen erzeugen.
            z = get_object_or_404(
                Zahlungseingang.objects.select_for_update(of=('self',))
                .select_related('debitoren_rechnung', 'vertrag__mieter'), id=pk)
            if z.status == 'storniert':
                messages.info(request, gettext('Diese Zahlung ist bereits storniert.'))
                return redirect(request.POST.get('next') or '/neu/bankabgleich/')
            # Eine Bankgutschrift kann sich auf mehrere Zahlungseingänge verteilt
            # haben: Teile einer Aufteilung, ein Überschuss als Guthaben
            # («…:ueber»), ein Rest aus der Zuordnung («…:rest»). Der Dienst
            # storniert sie zusammen; ein Teil einer Aufteilung nur mit dem Ganzen
            # (core/services/zahlungsklaerung.py).
            storniert = stornieren(z, user=request.user)
            teil = any(':teil' in (x.bank_referenz or '') or (x.bank_referenz or '').endswith(':offen')
                       for x in storniert)
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(request.POST.get('next') or '/neu/bankabgleich/')
    except Exception as exc:
        messages.error(request, '❌ ' + gettext('Zahlung konnte nicht storniert werden: %(exc)s') % {'exc': exc})
        return redirect(request.POST.get('next') or '/neu/bankabgleich/')

    log_aktion(request, "Zahlungseingang storniert", f"Zahlung #{z.id}",
               f"CHF {z.betrag} · {z.vertrag.mieter if z.vertrag_id else 'ohne Vertrag'}")
    if teil:
        messages.success(request, '✅ ' + gettext('Die Zahlung war aufgeteilt — alle %(n)s Teile sind storniert, die offenen Posten wieder offen.') % {'n': len(storniert)})
    else:
        messages.success(request, '✅ ' + gettext('Zahlung über CHF %(betrag)s storniert — offener Posten wieder offen.') % {'betrag': z.betrag})
    return redirect(request.POST.get('next') or '/neu/bankabgleich/')
