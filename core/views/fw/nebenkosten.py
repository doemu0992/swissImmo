# core/views/fw/nebenkosten.py
#
# Heiz- und Nebenkostenabrechnung: Perioden, Verteilschluessel, Verbuchung,
# Versand, Akonto-Anpassung. Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Nebenkosten sind im Skill schweizer-fachlogik ausdruecklich als Bereich
# genannt, in dem nichts umgerechnet oder geraten werden darf. Deshalb hier
# derselbe Nachweis wie ueberall: Blockinhalt Zeile fuer Zeile identisch mit
# HEAD, geaendert sind nur die Importe.

import logging
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext as _

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN, TEAM_ROLLEN,
                       VERWALTUNGS_ROLLEN)
from crm.models import Mieter
from finance.models import DebitorenRechnung, Zahlungseingang


#: Ab dieser Abweichung wird eine Anpassung des Akontobetrags empfohlen:
#: 10 % des heutigen Akontos, mindestens aber CHF 10.
AKONTO_ANTEIL = Decimal('0.10')
AKONTO_UNTERGRENZE = Decimal('10')


def akonto_empfehlung(kosten_monat, akonto_monat):
    """Empfohlener Akonto, Abweichung und Schwelle — als reine Rechnung.

    WARUM DAS EINE EIGENE FUNKTION IST (E2.25)

    Die vier Zeilen standen bis hierher mitten in `fw_nebenkosten_detail`,
    eingebettet in eine Schleife ueber die fertige Abrechnung. Pruefbar waren
    sie damit nur ueber die ganze Kette — Periode, Verteilschluessel,
    Buchungen — oder gar nicht.

    Die erste Fassung des Waechters las deshalb den QUELLTEXT und suchte die
    Zahlen mit einem regulaeren Ausdruck. Das faengt den Zahlendreher (aus
    10 wird 100), aber NICHT die gekippte Vergleichsrichtung: Wird aus
    `>=` ein `>`, bleibt der Text mit den Zahlen unveraendert und der
    Waechter gruen — nachgemessen, nicht vermutet. Ein Test, der eine Datei
    liest statt Code auszufuehren, prueft die Schreibweise, nicht das
    Verhalten.

    Herausgeloest ist die Grenze an ihrem Rand pruefbar: genau auf der
    Schwelle wird empfohlen, einen Rappen darunter nicht.

    WARUM ZWEI ZAHLEN, NICHT EINE

    Der Anteil allein erzeugte bei kleinen Akontobetraegen sinnlose
    Empfehlungen (10 % von CHF 30 sind CHF 3). Die Untergrenze allein wuerde
    bei grossen Betraegen jede Schwankung melden. `max()` nimmt die hoehere.

    Der Rundungsschritt auf CHF 5 bleibt unveraendert — ein Akonto von
    CHF 247 vorzuschlagen waere rechnerisch richtig und praktisch unbrauchbar.

    DECIMAL STATT FLOAT (NK-Wizard, Fehler j)

    Die Rechnung lief über `float` und `round()`. Jetzt durchgehend Decimal; die
    Rundung bleibt dieselbe wie bisher bei `round()`: auf die nächste Fünferstufe,
    genau in der Mitte zur geraden Stufe (ROUND_HALF_EVEN).
    """
    from decimal import ROUND_HALF_EVEN
    stufen = (Decimal(kosten_monat) / Decimal('5')).quantize(Decimal('1'), rounding=ROUND_HALF_EVEN)
    empfohlen = (stufen * 5).quantize(Decimal('1'))
    diff = empfohlen - akonto_monat
    schwelle = max(AKONTO_UNTERGRENZE, (akonto_monat * AKONTO_ANTEIL))
    empfehlen = abs(diff) >= schwelle and empfohlen > 0
    return empfohlen, diff, schwelle, empfehlen
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag

from ._basis import _global_filter, _num

logger = logging.getLogger(__name__)


# ============================================================
# ETAPPE D: NEBENKOSTEN (HNK-Abrechnungsperioden)
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_nebenkosten(request):
    from finance.models import AbrechnungsPeriode
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = AbrechnungsPeriode.objects.select_related('liegenschaft').order_by('-start_datum')
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    status_filter = request.GET.get('status', '')
    rows = []
    n_offen = n_zu = 0
    total_kosten_offen = Decimal('0.00')
    for p in qs:
        kosten = p.total_kosten
        if p.abgeschlossen:
            n_zu += 1
        else:
            n_offen += 1
            total_kosten_offen += kosten
        if status_filter == 'offen' and p.abgeschlossen:
            continue
        if status_filter == 'abgeschlossen' and not p.abgeschlossen:
            continue
        rows.append({
            'p': p, 'kosten': kosten,
            'lg': p.liegenschaft.strasse if p.liegenschaft_id else '—',
            'belege': p.belege.count(),
        })

    chips = [('', 'Alle'), ('offen', 'Offen'), ('abgeschlossen', 'Abgeschlossen')]
    return render(request, 'fw/nebenkosten.html', {
        **basis, 'nav': 'nebenkosten', 'rows': rows,
        'status_filter': status_filter, 'status_chips': chips,
        'n_offen': n_offen, 'n_zu': n_zu, 'total_kosten_offen': total_kosten_offen,
        'anzahl': len(rows),
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_nebenkosten_detail(request, pk):
    """Offene Periode: der Wizard beim ersten Schritt, der nicht erledigt ist
    (core/views/fw/nk_wizard.py). Verbuchte Periode: die Leseansicht mit dem
    EINGEFRORENEN Stand — dieselben Zahlen wie Buchungen, PDF und Versand.

    Die Leseansicht behebt, was die alte Detailseite falsch zeigte (Fehler i):
    Mieter-Link über die Vertrags-ID (nicht ein leeres `a.v`), Fläche aus der
    Abrechnung, kein Fusstext «Vorschau — verbindlich in der klassischen Ansicht»,
    Positionen inkl. Kreditoren (aus dem Snapshot, nicht nur die Belege).
    """
    from finance.models import AbrechnungsPeriode
    from core.utils.billing import hole_abrechnung
    from portfolio.models import Verteilschluessel
    from .nk_wizard import _karten, kennzahlen, wizard_aktueller_schritt
    p = get_object_or_404(AbrechnungsPeriode.objects.select_related('liegenschaft'), id=pk)
    if not p.abgeschlossen:
        return wizard_aktueller_schritt(request, p)
    basis = _global_filter(request)
    result = hole_abrechnung(p)
    namen = dict(Verteilschluessel.KOSTENART_CHOICES)
    positionen = [{**b, 'kostenart_name': namen.get(b.get('kostenart'), '')} for b in result.get('belege_details', [])]
    return render(request, 'fw/nebenkosten_detail.html', {
        **basis, 'nav': 'nebenkosten', 'p': p, 'result': result, 'kz': kennzahlen(result),
        'karten': _karten(result), 'positionen': positionen,
        'warnungen': result.get('warnungen', []), 'hinweise': result.get('hinweise', []),
        'hkvo_angewendet': result.get('hkvo_angewendet', False),
    })


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_nebenkosten_verbuchen(request, pk):
    """Verbucht die Abrechnung mit den GLEICHEN Zahlen wie Anzeige/PDF (kanonische Engine)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import AbrechnungsPeriode, Buchungskonto, Buchung
    from core.utils.billing import berechne_abrechnung
    from core.auth import log_aktion
    p = get_object_or_404(AbrechnungsPeriode, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/nebenkosten/{p.id}/')
    if p.abgeschlossen:
        messages.error(request, gettext('Diese Periode ist bereits abgeschlossen und verbucht.'))
        return redirect(f'/neu/nebenkosten/{p.id}/')

    result = berechne_abrechnung(p.id)
    from finance.booking import buche, konto as _konto
    konto_nk = _konto("3020")

    heute = timezone.localdate()
    n_nach = n_gut = 0
    nachzahler, nachzahlungen = [], []
    with transaction.atomic():
        # Zeilensperre + Re-Check gegen Doppelklick-Race: der p.abgeschlossen-Check
        # oben läuft ohne Lock — zwei parallele Requests würden sonst beide buchen
        # (doppelte NK-Nachzahlungsdebitoren + Buchungen).
        p = AbrechnungsPeriode.objects.select_for_update().get(id=p.id)
        if p.abgeschlossen:
            messages.error(request, gettext('Diese Periode ist bereits abgeschlossen und verbucht.'))
            return redirect(f'/neu/nebenkosten/{p.id}/')
        for a in result.get('abrechnungen', []):
            vid = a.get('vertrag_id')
            saldo = Decimal(str(a.get('saldo', 0)))
            if not vid or a.get('typ') == 'leerstand' or abs(saldo) < Decimal('0.01'):
                continue
            v = Mietvertrag.objects.filter(id=vid).select_related('einheit__liegenschaft').first()
            if not v:
                continue
            # Der Saldo der Abrechnung ist NETTO. Bei optiertem Gewerbe teilen die
            # Nebenkosten den MWST-Satz der Miete (Sollstellung belastet sie ebenso):
            # Die Steuer kommt obendrauf und gehört auf 2200. Wohnraum: satz = 0.
            satz = v.mwst_satz_wirksam
            mwst = (abs(saldo) * satz / Decimal('100')).quantize(Decimal('0.01')) if satz > 0 else Decimal('0.00')
            if saldo > 0:  # Nachzahlung -> Debitor
                rech = DebitorenRechnung.objects.create(
                    vertrag=v, liegenschaft=v.einheit.liegenschaft, einheit=v.einheit,
                    titel=f"NK-Abrechnung Nachzahlung - {p.bezeichnung}",
                    beschreibung=f"Periode {p.start_datum:%d.%m.%Y}–{p.ende_datum:%d.%m.%Y}",
                    betrag=saldo + mwst, faellig_am=heute + timezone.timedelta(days=30), konto_haben=konto_nk,
                    mwst_satz=satz if mwst else Decimal('0.0'), mwst_betrag=mwst)
                buche("1100", "3020", saldo, f"NK-Nachzahlung {v.mieter} - {p.bezeichnung}",
                      datum=heute, liegenschaft=v.einheit.liegenschaft, debitor=rech, user=request.user)
                buche("1100", "2200", mwst, f"MWST {satz}% NK-Nachzahlung {v.mieter} - {p.bezeichnung}",
                      datum=heute, liegenschaft=v.einheit.liegenschaft, debitor=rech, user=request.user)
                n_nach += 1
                nachzahler.append(v.pk)
                nachzahlungen.append(rech.pk)
            else:  # Guthaben → als ECHTES Mieterguthaben führen (Audit-Befund W1):
                # 3020 an 2030 (Verbindlichkeit gegenüber Mieter) statt 3020/1100 —
                # 1100 wurde sonst ohne Nebenbuch-Beleg entlastet und das Guthaben
                # war nirgends sichtbar. Der Zahlungseingang (Konto 2030) erscheint
                # im Mieterkonto als Haben und kann dort mit einer offenen
                # Rechnung verrechnet oder ausbezahlt werden.
                konto_2030 = _konto("2030")
                # Zahlungseingang ZUERST, dann mit `zahlung=` buchen: nur so hebt der
                # Storno des Guthabens auch die Buchung 3020/2030 auf (sonst bleibt 2030
                # im Hauptbuch stehen, das Nebenbuch nicht).
                z_nk = Zahlungseingang.objects.create(
                    vertrag=v, betrag=abs(saldo) + mwst, datum_eingang=heute,
                    buchungs_monat=heute.replace(day=1),
                    bemerkung=f"NK-Gutschrift {p.bezeichnung} (Guthaben Mieter)",
                    konto=konto_2030, liegenschaft=v.einheit.liegenschaft,
                    erstellt_von=request.user, status='verbucht')
                buche("3020", "2030", abs(saldo), f"NK-Gutschrift {v.mieter} - {p.bezeichnung}",
                      datum=heute, liegenschaft=v.einheit.liegenschaft, zahlung=z_nk, user=request.user)
                # Umsatzminderung: auch die geschuldete MWST wird zurückgenommen.
                buche("2200", "2030", mwst, f"MWST-Korrektur {satz}% NK-Gutschrift {v.mieter} - {p.bezeichnung}",
                      datum=heute, liegenschaft=v.einheit.liegenschaft, zahlung=z_nk, user=request.user)
                n_gut += 1
        p.abgeschlossen = True
        # Ergebnis EINFRIEREN: ab jetzt zeigen Detailseite/PDF/Versand genau diese
        # verbuchten Zahlen, auch wenn Belege/Flächen/Verträge später ändern.
        from core.utils.billing import _jsonable as _nk_jsonable
        import json as _nk_json
        p.snapshot_json = _nk_json.dumps(_nk_jsonable(result))
        p.save(update_fields=['abgeschlossen', 'snapshot_json'])
    # Guthaben, die für die NK-Abrechnung reserviert oder für die nächste Rechnung
    # vorgesehen sind, tilgen jetzt die Nachzahlung (Zahlungs-Cockpit V12).
    verrechnet = Decimal('0.00')
    if nachzahler:
        try:
            from core.services.zahlungsklaerung import guthaben_verrechnen
            # Nur die eben gebuchten Nachzahlungen — nie ein älterer Rückstand.
            _n, verrechnet = guthaben_verrechnen(nachzahler, arten=('naechste_rechnung', 'nk_abrechnung'),
                                                 rechnung_ids=nachzahlungen, user=request.user)
        except Exception:
            logger.warning('Guthaben-Verrechnung nach NK %s fehlgeschlagen', p.pk, exc_info=True)
    log_aktion(request, "NK-Abrechnung verbucht", p.bezeichnung, f"{n_nach} Nachzahlungen, {n_gut} Gutschriften")
    if verrechnet:
        messages.info(request, gettext('CHF %(betrag)s Mieterguthaben mit Nachzahlungen verrechnet.') % {'betrag': verrechnet})
    messages.success(request, '✅ ' + gettext('Abrechnung verbucht: %(n_nach)s Nachzahlung(en), %(n_gut)s Gutschrift(en).') % {'n_nach': n_nach, 'n_gut': n_gut})
    for _w in result.get('warnungen', []):
        messages.warning(request, f"⚠️ {_w}")
    return redirect(f'/neu/nebenkosten/{p.id}/')


# Inhaber und Verwalter (seit 28.09.2026, vorher auch die Sachbearbeitung).
# Der Versand legt die Abrechnung jedes Mieters in dessen Akte und damit sofort
# ins Mieterportal — das ist die Freigabe an die Mieter, und «Nebenkosten-
# abrechnung freigeben» ist nach docs/KONZEPT-UI.md §8 Inhaber und Verwaltern
# vorbehalten. Er ging auch für eine NICHT abgeschlossene Periode (dann live
# gerechnet): Die Sachbearbeitung konnte so eine Abrechnung, die niemand
# verbucht hatte, allen Mietern der Liegenschaft zustellen.
@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_nebenkosten_versand(request, pk):
    """Erzeugt je Mieter eine Nebenkosten-Abrechnung (PDF), legt sie in dessen
    Akte (→ Mieterportal) und liefert alle zusammen als Sammel-PDF."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from finance.models import AbrechnungsPeriode
    from crm.models import Organisation
    from core.utils.billing import hole_abrechnung
    from core.services.nk_abrechnung import generate_nk_pdf_einzeln, generate_nk_pdf_sammel
    from core.services.ablage import ablegen
    from core.auth import log_aktion

    p = get_object_or_404(AbrechnungsPeriode.objects.select_related('liegenschaft'), id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/nebenkosten/{p.id}/')
    # Fehler g: Ohne diese Prüfung ging der Versand auch für eine NICHT verbuchte Periode —
    # live gerechnet, in die Akten und das Portal aller Mieter. Wie beim E-Mail-Versand gilt:
    # erst verbuchen (eingefrorener Stand), dann zustellen.
    if not p.abgeschlossen:
        messages.error(request, gettext('Die Abrechnung ist noch nicht verbucht — erst verbuchen, dann versenden.'))
        return redirect(f'/neu/nebenkosten/{p.id}/abschluss/')

    # Verbuchte Periode → eingefrorener Stand (gleiche Zahlen wie die Buchungen).
    result = hole_abrechnung(p)
    if result.get('error'):
        messages.error(request, result['error'])
        return redirect(f'/neu/nebenkosten/{p.id}/')

    # Kontext je Mieter (Absender = Verwaltung DIESER Periode): core/services/nk_versand.py
    from core.services.nk_versand import mieter_kontexte
    kontexte = []
    abgelegt = 0
    for eintrag in mieter_kontexte(p, result):
        v, m, k = eintrag['vertrag'], eintrag['mieter'], eintrag['k']
        kontexte.append(k)
        # Einzel-PDF in die Akte des Mieters (erscheint im Portal)
        try:
            einzel = generate_nk_pdf_einzeln(k)
            if ablegen(einzel, f"Nebenkostenabrechnung {p.bezeichnung}", kategorie='korrespondenz',
                       vertrag=v, mieter=m, dedup=True, im_portal_sichtbar=True):
                abgelegt += 1
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)
        # Modul 5: Regel «NK versandt» — Begleitschreiben je Mieter.
        from core.services.dokument_regeln import dokument_fuer_ereignis
        dokument_fuer_ereignis('nk_versandt', organisation=p.organisation, vertrag=v)

    if not kontexte:
        messages.error(request, gettext('Keine abzurechnenden Mieter in dieser Periode gefunden.'))
        return redirect(f'/neu/nebenkosten/{p.id}/')

    log_aktion(request, "NK-Abrechnungen versendet", p.bezeichnung, f"{abgelegt} abgelegt")
    sammel = generate_nk_pdf_sammel(kontexte)
    resp = HttpResponse(sammel, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="Nebenkostenabrechnungen_{p.bezeichnung}.pdf"'
    return resp


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_akonto_anpassen(request, pk):
    """E1: Das Akonto wird hier NICHT mehr überschrieben — auch nicht gesenkt.

    Eine Erhöhung der Akontozahlung ist eine einseitige Vertragsänderung und geht wie der
    Mietzins über Formular und Termin (Art. 269d OR). Die Route bleibt für alte Formulare und
    Lesezeichen: Sie leitet in den Ablauf «Mietzinsanpassung» des ersten gewählten Vertrags
    weiter, vorbelegt mit dem vorgeschlagenen Akonto — oder in den Schritt «Prüfen».
    """
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import AbrechnungsPeriode
    p = get_object_or_404(AbrechnungsPeriode, id=pk)
    for vid in (request.POST.getlist('vertrag_id') if request.method == 'POST' else []):
        v = Mietvertrag.objects.filter(id=vid, einheit__liegenschaft=p.liegenschaft).first()
        if v is None:
            continue
        try:
            betrag = Decimal(_num(request.POST.get(f'akonto_{vid}')))
        except Exception:
            betrag = None
        ziel = f'/neu/mietzins/{v.id}/anpassung/?nk_periode={p.id}'
        if betrag is not None and betrag > 0:
            ziel += f'&nk={betrag.quantize(Decimal("1"))}'
        messages.info(request, gettext('Das Akonto wird über die Mietzinsanpassung angepasst (Formular und Termin).'))
        return redirect(ziel)
    return redirect(f'/neu/nebenkosten/{p.id}/pruefen/#akonto')


# Nur Inhaber und Verwalter — wie der Versand ins Portal: Die Mail ist die Zustellung der
# Abrechnung an die Mieter und setzt den Beginn der Einsprachefrist.
@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_nebenkosten_mail(request, pk):
    """Schickt jedem Mieter seine Nebenkostenabrechnung (PDF) per E-Mail.

    Nur für eine VERBUCHTE Periode: Es gilt der eingefrorene Stand, nicht eine Live-Rechnung.
    Die Zustellung (`versendet_am`, Kanal «E-Mail», damit die Einsprachefrist) wird nur
    festgehalten, wenn ALLE Mieter erreicht wurden. Fehlt eine Adresse oder scheitert ein
    Versand, bleibt die Zustellung offen und die Meldung nennt die Betroffenen — sie
    erhalten die Abrechnung per Brief (Sammel-PDF), danach wird die Zustellung von Hand erfasst.
    """
    from django.contrib import messages
    from django.shortcuts import redirect

    from core.auth import log_aktion
    from core.services.ablage import ablegen
    from core.services.nk_abrechnung import generate_nk_pdf_einzeln
    from core.services.nk_versand import antwortadresse, mail_text, mieter_kontexte
    from core.utils.billing import hole_abrechnung
    from core.utils.email_service import journal_email, send_via_hoststar
    from finance.models import AbrechnungsPeriode

    p = get_object_or_404(AbrechnungsPeriode.objects.select_related('liegenschaft'), pk=pk)
    ziel = f'/neu/nebenkosten/{p.id}/'
    if request.method != 'POST':
        return redirect(ziel)
    if not p.abgeschlossen:
        messages.error(request, gettext('Die Abrechnung ist noch nicht verbucht — erst verbuchen, dann versenden.'))
        return redirect(ziel)
    if p.versendet_am and p.versand_kanal == 'email' and request.POST.get('nochmals') != '1':
        messages.error(request, gettext('Die Abrechnung wurde am %(d)s per E-Mail versendet. Zum erneuten Senden bitte bestätigen.')
                       % {'d': p.versendet_am.strftime('%d.%m.%Y')})
        return redirect(ziel)

    result = hole_abrechnung(p)
    if result.get('error'):
        messages.error(request, result['error'])
        return redirect(ziel)
    eintraege = mieter_kontexte(p, result)
    if not eintraege:
        messages.error(request, gettext('Keine abzurechnenden Mieter in dieser Periode gefunden.'))
        return redirect(ziel)

    reply_to = antwortadresse(p.organisation_id)
    gesendet, ohne_adresse, gescheitert = 0, [], []
    for e in eintraege:
        v, m, k = e['vertrag'], e['mieter'], e['k']
        adresse = (m.email or '').strip()
        name = m.display_name
        if not adresse:
            ohne_adresse.append(name)
            continue
        try:
            pdf = generate_nk_pdf_einzeln(k)
        except Exception:
            logger.exception('NK-PDF für %s nicht erzeugt', name)
            gescheitert.append(name)
            continue
        betreff = f"Nebenkostenabrechnung {p.bezeichnung}"
        html = mail_text(k, p.bezeichnung)
        dateiname = f"Nebenkostenabrechnung_{p.bezeichnung}_{v.id}.pdf".replace(' ', '_').replace('/', '-')
        if not send_via_hoststar(adresse, betreff, html, dateiname, pdf, reply_to=reply_to):
            gescheitert.append(name)
            continue
        gesendet += 1
        ablegen(pdf, f"Nebenkostenabrechnung {p.bezeichnung}", kategorie='korrespondenz',
                vertrag=v, mieter=m, dedup=True, im_portal_sichtbar=True)
        # Modul 5: Regel «NK versandt» — Begleitschreiben je Mieter.
        from core.services.dokument_regeln import dokument_fuer_ereignis
        dokument_fuer_ereignis('nk_versandt', organisation=p.organisation, vertrag=v)
        journal_email(betreff, f"Nebenkostenabrechnung {p.bezeichnung} (PDF) versendet.", mieter=m, vertrag=v,
                      liegenschaft=p.liegenschaft, user=request.user, empfaenger=adresse)

    vollstaendig = gesendet == len(eintraege)
    if vollstaendig:
        p.versendet_am = timezone.localdate()
        p.versand_kanal = 'email'
        p.save(update_fields=['versendet_am', 'versand_kanal'])
    log_aktion(request, 'NK-Abrechnung per E-Mail versendet', p.bezeichnung,
               f'{gesendet} von {len(eintraege)}')
    if vollstaendig:
        messages.success(request, gettext('Abrechnung an %(n)s Mieter versendet. Einsprachefrist bis %(d)s.')
                         % {'n': gesendet, 'd': p.einsprache_bis.strftime('%d.%m.%Y')})
    else:
        if gesendet:
            messages.warning(request, gettext('%(n)s von %(m)s Abrechnungen versendet. Die Zustellung ist noch nicht erfasst.')
                             % {'n': gesendet, 'm': len(eintraege)})
        if ohne_adresse:
            messages.error(request, gettext('Keine E-Mail-Adresse: %(namen)s. Diese Mieter erhalten die Abrechnung per Brief (Sammel-PDF).')
                           % {'namen': ', '.join(ohne_adresse)})
        if gescheitert:
            messages.error(request, gettext('Versand fehlgeschlagen: %(namen)s.') % {'namen': ', '.join(gescheitert)})
    return redirect(ziel)
