# core/views/fw/kreditoren.py
#
# Rechnungseingang, Freigabe, Zahlung, Zahllauf und pain.001-Datei.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# pain.001 ist im Skill schweizer-fachlogik als Zahlungsstandard gefuehrt.
# Reiner Umzug, Blockinhalt gegen HEAD geprueft.

import logging
import os
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.utils.translation import gettext
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext_lazy

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from core.auth import (FINANZ_LESE_ROLLEN, FINANZ_SCHREIB_ROLLEN, FINANZ_VERWALTUNGS_ROLLEN,
                       ZAHLUNGSFREIGABE_ROLLEN)
from portfolio.models import Liegenschaft

logger = logging.getLogger(__name__)

from ._basis import _global_filter, _num
from core.tenancy import aktuelle_organisation


# ============================================================
# ETAPPE D: KREDITOREN (Rechnungseingang -> Freigabe -> Zahlung)
# ============================================================

KRED_PILL = {
    'neu':         (gettext_lazy('Neu / Prüfen'), 'fw-warn-flaeche fw-warnton'),
    'freigegeben': (gettext_lazy('Freigegeben'),  'fw-info-flaeche fw-info'),
    'in_zahlung':  (gettext_lazy('In Zahlung'),   'fw-markenflaeche fw-marke'),
    'teilbezahlt': (gettext_lazy('Teilbezahlt'),  'fw-warn-flaeche fw-warnton'),
    'bezahlt':     (gettext_lazy('Bezahlt'),      'fw-gut-flaeche fw-gut'),
    'storniert':   (gettext_lazy('Storniert'),    'fw-flaeche2 fw-mutet'),
}


def _formularwerte(k):
    """Die Werte des Bearbeiten-Formulars einer Zeile, als Text — so, wie sie
    im Feld stehen. Nach einem Fehler ersetzt die Eingabe diese Werte (Audit
    Etappe 2), deshalb stehen sie an EINER Stelle statt in der Vorlage."""
    def _d(wert):
        return wert.isoformat() if wert else ''
    return {
        'lieferant': k.lieferant or '',
        'betrag': f'{k.betrag:.2f}' if k.betrag else '',
        'datum': _d(k.datum), 'faellig_am': _d(k.faellig_am),
        'leistungs_von': _d(k.leistungs_von), 'leistungs_bis': _d(k.leistungs_bis),
        'referenz': k.referenz or '', 'iban': k.iban or '',
        'lieferant_strasse': k.lieferant_strasse or '',
        'lieferant_hausnummer': k.lieferant_hausnummer or '',
        'lieferant_plz': k.lieferant_plz or '', 'lieferant_ort': k.lieferant_ort or '',
        'lieferant_land': k.lieferant_land or 'CH',
        'liegenschaft_id': str(k.liegenschaft_id or ''), 'konto_id': str(k.konto_id or ''),
        'is_hnk_relevant': bool(k.is_hnk_relevant),
    }


def formular_eingabe(post):
    """Rohe Eingabe eines Kreditor-Formulars in derselben Form wie
    `_formularwerte` — für die Anzeige nach einem Fehler."""
    werte = {name: post.get(name, '') for name in (
        'lieferant', 'betrag', 'mwst_satz', 'datum', 'faellig_am', 'leistungs_von',
        'leistungs_bis', 'referenz', 'iban', 'liegenschaft_id', 'konto_id',
        'lieferant_strasse', 'lieferant_hausnummer', 'lieferant_plz', 'lieferant_ort',
        'lieferant_land')}
    werte['is_hnk_relevant'] = post.get('is_hnk_relevant') == 'on'
    return werte


def formular_fehler(form, feld_fehler):
    """Erste Meldung je Feld — aus dem Formular und aus den Prüfungen der
    Ansicht (Liegenschaft, Konto)."""
    fehler = {name: liste[0] for name, liste in form.errors.items() if name != '__all__'}
    fehler.update(feld_fehler)
    return fehler


def _name(user):
    return (user.get_full_name() or user.get_username()) if user else ''


def _vier_augen(k, user, organisation, darf_freigeben):
    """Der Stand des Vier-Augen-Prinzips einer Rechnung für Liste und Zahllauf.

    `sperre`: Die Zahlung ist gesperrt, bis eine zweite Person freigibt.
    `kann_freigeben`: Diese Person darf freigeben (Rolle UND nicht der Vorleger)."""
    from finance.freigabe import braucht_zahlungsfreigabe, freigabe_gueltig
    if not braucht_zahlungsfreigabe(k, organisation):
        return {'noetig': False, 'sperre': False}
    gueltig = freigabe_gueltig(k)
    vorgelegt = bool(k.zahlung_beantragt_von_id) and not gueltig
    return {
        'noetig': True, 'sperre': not gueltig, 'gueltig': gueltig, 'vorgelegt': vorgelegt,
        'vorleger': _name(k.zahlung_beantragt_von), 'freigeber': _name(k.zahlung_freigegeben_von),
        'geaendert': bool(k.zahlung_freigegeben_von_id) and not gueltig,
        'kann_freigeben': bool(vorgelegt and darf_freigeben and k.zahlung_beantragt_von_id != user.pk),
        'selbst_vorgelegt': bool(vorgelegt and k.zahlung_beantragt_von_id == user.pk),
    }


def _vier_augen_pruefen(request, k):
    """Sperre des Vier-Augen-Prinzips für eine Zahlung. Gibt die Meldung zurück oder `None`.

    Eine gesperrte Zahlung wird zugleich zur Freigabe vorgelegt (wer sie auslösen
    wollte, steht damit als Vorleger fest), und der Versuch kommt ins Protokoll —
    die zweite Person sieht sie dann in der Liste, ohne dass jemand nachfassen muss."""
    from core.auth import log_aktion
    from finance.freigabe import vorlegen, zahlung_sperre
    sperre = zahlung_sperre(k, aktuelle_organisation())
    if not sperre:
        return None
    if vorlegen(k, request.user):
        log_aktion(request, 'Zahlung zur Freigabe vorgelegt', k.lieferant or f'Rechnung #{k.id}',
                   f'CHF {k.betrag} · automatisch beim Auslösen der Zahlung')
    log_aktion(request, 'Zahlung gesperrt (Vier-Augen-Prinzip)', k.lieferant or f'Rechnung #{k.id}',
               f'CHF {k.betrag} · {sperre}')
    return sperre


@rolle_erforderlich(*FINANZ_LESE_ROLLEN)
def fw_kreditoren(request, *, formular=None):
    """Kreditorenliste. `formular` (Audit Etappe 2): Kommt ein Erfassen- oder
    Bearbeiten-Formular mit Fehlern zurück, rendert die Liste es mit der
    Eingabe und den Meldungen am Feld, statt umzuleiten und alles zu verwerfen
    — Status 400. Schlüssel: `neu_werte`/`neu_fehler` oder
    `bearb_id`/`bearb_werte`/`bearb_fehler`."""
    formular = formular or {}
    from finance.models import KreditorenRechnung
    from core.auth import hat_rolle, FINANZ_VERWALTUNGS_ROLLEN, ZAHLUNGSFREIGABE_ROLLEN
    from django.contrib import messages
    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    # prefetch_related: ohne 'zahlungen' löst offener_betrag je Zeile eine eigene
    # SUM-Abfrage aus, ohne 'positionen' je Zeile zwei weitere (N+1 → Timeout).
    qs = (KreditorenRechnung.objects.exclude(status='storniert')
          .select_related('liegenschaft', 'konto', 'zahlung_beantragt_von', 'zahlung_freigegeben_von')
          .prefetch_related('zahlungen', 'positionen__konto', 'positionen__einheit'))
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    status_filter = request.GET.get('status', '')
    if status_filter in KRED_PILL:
        qs = qs.filter(status=status_filter)

    # Volltextsuche über Lieferant, Referenz und Betrag — bei einigen hundert
    # Rechnungen ist Scrollen keine Suche (Praxis-Audit).
    suche = (request.GET.get('q') or '').strip()
    if suche:
        from django.db.models import Q as _Qk
        bedingung = (_Qk(lieferant__icontains=suche) | _Qk(referenz__icontains=suche)
                     | _Qk(iban__icontains=suche.replace(' ', '')))
        try:
            bedingung |= _Qk(betrag=Decimal(_num(suche)))
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)
        qs = qs.filter(bedingung)

    # Sortierung: Fälligkeit zuerst ist die Arbeitsreihenfolge der Kreditoren-
    # buchhaltung; '-id' (Erfassungsreihenfolge) bleibt als Option erhalten.
    SORTIERUNGEN = {
        'faellig': ['faellig_am', 'id'],
        '-faellig': ['-faellig_am', '-id'],
        'betrag': ['betrag', 'id'],
        '-betrag': ['-betrag', '-id'],
        'lieferant': ['lieferant', 'id'],
        'neu': ['-id'],
    }
    sortierung = request.GET.get('sort') or 'faellig'
    if sortierung not in SORTIERUNGEN:
        sortierung = 'faellig'
    qs = qs.order_by(*SORTIERUNGEN[sortierung])

    # Kennzahlen über den GANZEN gefilterten Bestand — die Seite zeigt nur einen
    # Ausschnitt, die Summen dürfen davon nicht abhängen.
    from django.db.models import Sum as _SumK, Count as _CountK
    _kpi = (KreditorenRechnung.objects.exclude(status='storniert')
            .filter(status='neu'))
    if aktive_lg:
        _kpi = _kpi.filter(liegenschaft=aktive_lg)
    _kpi_agg = _kpi.aggregate(s=_SumK('betrag'), n=_CountK('id'))
    total_neu = _kpi_agg['s'] or Decimal('0.00')
    anzahl_neu = _kpi_agg['n'] or 0
    gesamt_anzahl = qs.count()

    from django.core.paginator import Paginator
    paginator = Paginator(qs, 50)
    seite = paginator.get_page(request.GET.get('seite') or 1)

    rows = []
    total_offen = Decimal('0.00')     # freigegeben, noch nicht bezahlt (diese Seite)
    zeilen = list(seite.object_list)
    bearb_id = formular.get('bearb_id')
    if bearb_id and not any(k.id == bearb_id for k in zeilen):
        # Die Rechnung mit dem Fehler steht nicht auf dieser Seite (nach einem
        # POST gibt es keinen Seitenparameter) — oben dazunehmen, sonst wäre
        # die Meldung unsichtbar.
        zeilen = list(qs.filter(id=bearb_id)) + zeilen
    # Lieferantenprofile der noch nicht freigegebenen Zeilen in EINER Abfrage:
    # Sie liefern die gelernte IBAN für den Abgleich (Betrugsschutz, FIN-09).
    from finance.kreditor_adresse import (adresse_vollstaendig, adresse_von_rechnung,
                                          iban_abweichung, iban_meldung)
    from finance.lieferanten import lieferant_key
    from finance.models import LieferantProfil
    _neu = [k for k in zeilen if k.status == 'neu' and k.iban]
    _profile = {p.name_key: p for p in LieferantProfil.objects.filter(
        name_key__in={lieferant_key(k.lieferant) for k in _neu})} if _neu else {}
    organisation = aktuelle_organisation()
    darf_freigeben = hat_rolle(request.user, ZAHLUNGSFREIGABE_ROLLEN)
    zur_freigabe = 0
    for k in zeilen:
        va = _vier_augen(k, request.user, organisation, darf_freigeben) \
            if k.status in ('freigegeben', 'in_zahlung', 'teilbezahlt') else {'noetig': False, 'sperre': False}
        if va.get('kann_freigeben'):
            zur_freigabe += 1
        label, cls = KRED_PILL.get(k.status, (k.status, 'fw-flaeche2 fw-mutet'))
        _gelernt = (iban_abweichung(k, profil=_profile.get(lieferant_key(k.lieferant)))
                    if k.status == 'neu' and k.iban else '')
        _zahlbar = k.status in ('neu', 'freigegeben', 'in_zahlung', 'teilbezahlt')
        betrag = k.betrag or Decimal('0.00')
        offen_betrag = k.offener_betrag
        faellig = k.faellig_am
        # Letzte VERBUCHTE Zahlung (für «Zahlung stornieren»). Nutzt den Prefetch —
        # keine Extra-Abfrage je Zeile.
        _verbuchte = sorted((z for z in k.zahlungen.all() if z.status == 'verbucht'),
                            key=lambda z: (z.datum, z.id))
        letzte_zahlung = _verbuchte[-1] if _verbuchte else None
        if k.status in ('freigegeben', 'in_zahlung', 'teilbezahlt'):
            total_offen += offen_betrag
        rows.append({
            'k': k, 'betrag': betrag, 'status_label': label, 'pill_cls': cls,
            'faellig': faellig,
            'ueberfaellig': bool(faellig and faellig < heute and k.status != 'bezahlt'),
            'lieferant': k.lieferant or 'Wird gescannt …',
            'objekt': f"{k.liegenschaft.strasse}, {k.liegenschaft.ort}" if k.liegenschaft else '—',
            'konto': f"{k.konto.nummer} {k.konto.bezeichnung}" if k.konto else None,
            'beleg_url': k.beleg_scan.url if k.beleg_scan else None,
            'beleg_ist_pdf': bool(k.beleg_scan and str(k.beleg_scan.name).lower().endswith('.pdf')),
            'kann_bezahlen': k.status in ('freigegeben', 'in_zahlung', 'teilbezahlt'),
            'va': va,
            'in_zahlung': k.status == 'in_zahlung',
            'teilbezahlt': k.status == 'teilbezahlt',
            'letzte_zahlung': letzte_zahlung,
            'offen_betrag': offen_betrag,
            'offen_wv': k.offen_weiterzuverrechnen,
            'kann_weiterverrechnen': (k.status in ('freigegeben', 'in_zahlung', 'teilbezahlt', 'bezahlt')
                                      and k.offen_weiterzuverrechnen > 0),
            'positionen': list(k.positionen.all()) if k.status == 'neu' else [],
            'pos_summe': k.positionen_summe if k.status == 'neu' else Decimal('0.00'),
            'pos_diff': k.positionen_differenz if k.status == 'neu' else Decimal('0.00'),
            'adr_idp': f'kc-adr-{k.id}',
            'iban_warnung': iban_meldung(k.iban, _gelernt) if _gelernt else '',
            'adresse_fehlt': _zahlbar and not adresse_vollstaendig(adresse_von_rechnung(k)),
            'adresse_nachtragbar': k.status in ('freigegeben', 'in_zahlung', 'teilbezahlt'),
            'werte': formular['bearb_werte'] if k.id == bearb_id else _formularwerte(k),
            'fehler': formular.get('bearb_fehler', {}) if k.id == bearb_id else {},
            'offen': k.id == bearb_id,
        })

    status_chips = [('', gettext_lazy('Alle'))] + [(k, v[0]) for k, v in KRED_PILL.items() if k != 'storniert']

    from finance.models import Buchungskonto
    aufwand_konten = Buchungskonto.objects.filter(typ='aufwand').order_by('nummer')
    liegenschaften = Liegenschaft.objects.order_by('strasse')
    # Für pain.001: freigegebene Rechnungen mit gültiger IBAN
    # «Zahlbar» zählt über den ganzen Bestand, nicht nur die aktuelle Seite —
    # sonst behauptet der Zahllauf-Knopf eine falsche Zahl.
    _zb = KreditorenRechnung.objects.filter(status='freigegeben').exclude(iban='')
    if aktive_lg:
        _zb = _zb.filter(liegenschaft=aktive_lg)
    # Querystring ohne 'seite' — damit Filter/Suche/Sortierung beim Blättern
    # erhalten bleiben (bisher fiel der Filter beim Seitenwechsel weg).
    _qp = request.GET.copy()
    _qp.pop('seite', None)
    query_ohne_seite = _qp.urlencode()
    return render(request, 'fw/kreditoren.html', {
        **basis, 'nav': 'kreditoren', 'rows': rows,
        'status_filter': status_filter, 'status_chips': status_chips,
        'suche': suche, 'sortierung': sortierung,
        'seite': seite, 'query_ohne_seite': query_ohne_seite,
        'total_offen': total_offen, 'total_neu': total_neu, 'anzahl_neu': anzahl_neu,
        'anzahl': gesamt_anzahl,
        'anzahl_zahlbar': _zb.count(),
        'darf_bezahlen': hat_rolle(request.user, FINANZ_VERWALTUNGS_ROLLEN),
        'zur_freigabe': zur_freigabe,
        'aufwand_konten': aufwand_konten, 'liegenschaften': liegenschaften,
        'ki_aktiv': bool(getattr(settings, 'GROQ_API_KEY', None)),
        'rechnungs_mail': os.environ.get('RECHNUNGS_IMAP_USER', ''),
        'meldung': list(messages.get_messages(request)),
        'neu_werte': formular.get('neu_werte', {}),
        'neu_fehler': formular.get('neu_fehler', {}),
        'anzahl_fehler': len(formular.get('neu_fehler') or formular.get('bearb_fehler') or {}),
    }, status=400 if formular else 200)


# `fw_kreditoren_pain001` IST IN E2.45 ENTFERNT.
#
# Sie erzeugte eine gueltige pain.001-Datei aus ALLEN freigegebenen
# Kreditorenrechnungen — ohne Auswahl und ohne den Vorgang als Zahllauf
# festzuhalten. Aus der Navigation war sie laengst verschwunden, die Adresse
# antwortete aber weiter.
#
# WAS DAS BEDEUTETE: Wer sie kannte oder ein Lesezeichen hatte, erzeugte eine
# Zahlungsdatei, die in KEINEM Zahllauf steht. Beim naechsten
# Periodenabschluss fehlte sie in der Aufstellung, waehrend das Geld die Bank
# verlassen hatte. Nicht falsch, sondern unbemerkt — die Fehlerart, vor der
# G7 warnt.
#
# `fw_zahllauf` unten leistet dasselbe MIT Auswahl und Buchfuehrung: Es setzt
# ebenfalls `in_zahlung` (nachgesehen, nicht angenommen) und haelt den Lauf
# fest. Das ist der Weg, den die Oberflaeche anbietet.


# DER ROLLEN-WAECHTER GEHOERT HIERHER — ER WAR IN E2.45 MIT VERSCHWUNDEN.
#
# Der Patch, der `fw_kreditoren_pain001` entfernte, nahm eine Dekorator-Zeile
# zu viel mit: die von DIESER Ansicht. Gemessen, was das bedeutete:
#
#   Lesezugriff  -> HTTP 302, Rechnung auf «bezahlt», eine Buchung angelegt
#   anonym       -> erreicht den Buchungscode und legt eine
#                   `KreditorenZahlung` an, bevor er an `erstellt_von`
#                   scheitert
#
# `rolle_erforderlich` ersetzt zugleich `login_required` — ohne den Dekorator
# gibt es also GAR KEINE Anmeldepruefung, nicht bloss keine Rollenpruefung.
@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_kreditor_bezahlen(request):
    """Bezahlt eine freigegebene Kreditorenrechnung — Kreditoren 2000 an Bank 1020
    (dieselbe Doppelbuchung wie die Finanz-API pay_kreditor)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, Buchungskonto, Buchung
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_kreditoren')

    from finance.models import KreditorenZahlung
    from finance.freigabe import freigabe_sperre
    from core.sperren import erwarteter_betrag
    # Die Mandantengrenze zuerst (fremde ID -> 404); was vom ZUSTAND der Rechnung
    # abhaengt, wird erst nach dem Sperren geprueft.
    k = get_object_or_404(KreditorenRechnung, id=request.POST.get('rechnung_id'))

    # Optionaler Teilbetrag; Standard = offener Betrag
    def _dec(x):
        try:
            return Decimal(_num(x))
        except Exception:
            return None
    # Leeres Feld = Vollzahlung; eine EXPLIZITE 0 ist ein Tippfehler und darf
    # NICHT still zur Vollzahlung werden (Decimal('0') ist falsy — die frühere
    # `or offen`-Logik zahlte bei Eingabe «0» kommentarlos den vollen Betrag).
    raw = (request.POST.get('betrag') or '').strip()
    eingabe = _dec(raw) if raw else None
    if raw and (eingabe is None or eingabe <= 0):
        messages.error(request, gettext('Ungültiger Betrag «%(raw)s» — Zahlung nicht ausgeführt.') % {'raw': raw})
        return redirect('fw_kreditoren')

    # Valutadatum und Bankkonto sind wählbar — «heute» und «1020» waren stille
    # Annahmen und bei mehreren Bankkonten schlicht falsch (Praxis-Audit).
    try:
        valuta = date.fromisoformat(request.POST.get('valuta') or '')
    except ValueError:
        valuta = timezone.localdate()
    bank_nr = (request.POST.get('bank_konto') or '1020').strip()
    if not Buchungskonto.objects.filter(nummer=bank_nr).exists():
        bank_nr = '1020'
    erwartet = erwarteter_betrag(request.POST)
    try:
        with transaction.atomic():
            # SPERREN, DANN PRÜFEN (Audit FIN-02): Vier parallele Klicks buchten
            # viermal 800 auf eine Rechnung über 800. Status und offener Betrag
            # gelten für den Stand NACH dem Warten auf die Zeile.
            k = KreditorenRechnung.objects.select_for_update(of=('self',)).get(pk=k.pk)
            if k.status in ('bezahlt', 'storniert', 'neu'):
                messages.error(request, gettext('Diese Rechnung kann nicht (mehr) bezahlt werden.'))
                return redirect('fw_kreditoren')
            sperre = freigabe_sperre(k)
            if sperre:
                messages.error(request, f'⛔ {sperre}')
                return redirect('fw_kreditoren')
            sperre = _vier_augen_pruefen(request, k)
            if sperre:
                messages.error(request, '⛔ ' + gettext(
                    'Zahlung nicht ausgelöst: Ab dem Freigabelimit gibt eine zweite Person die Zahlung frei. '
                    'Sie ist vorgelegt und erscheint dort in der Liste.'))
                return redirect('fw_kreditoren')
            offen = k.offener_betrag
            if erwartet is not None and erwartet != offen:
                messages.error(request, gettext(
                    "«%(lieferant)s»: Der offene Betrag hat sich seit dem Öffnen der Maske geändert "
                    "(jetzt CHF %(offen)s) — die Zahlung wurde vermutlich schon verbucht. Nichts doppelt gebucht.")
                    % {'lieferant': k.lieferant or gettext('Lieferant'), 'offen': offen})
                return redirect('fw_kreditoren')
            betrag = min(eingabe if eingabe is not None else offen, offen)
            if betrag <= 0:
                messages.error(request, gettext('Kein offener Betrag zu bezahlen.'))
                return redirect('fw_kreditoren')
            from finance.booking import buche
            zahlung = KreditorenZahlung.objects.create(
                kreditor=k, betrag=betrag, datum=valuta,
                bemerkung=f"Zahlung {k.lieferant}", erstellt_von=request.user)
            buche("2000", bank_nr, betrag, f"Zahlung {k.lieferant} - {k.referenz}",
                  datum=valuta, liegenschaft=k.liegenschaft, kreditor=k, user=request.user)
            k.status = 'bezahlt' if k.offener_betrag <= 0 else 'teilbezahlt'
            k.save(update_fields=['status'])
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect('fw_kreditoren')

    log_aktion(request, "Kreditorenrechnung bezahlt", k.lieferant or f"Rechnung #{k.id}",
               f"CHF {betrag}" + (f" (offen CHF {k.offener_betrag})" if k.status == 'teilbezahlt' else ""))
    empfaenger = k.lieferant or gettext('Lieferant')
    if k.status == 'teilbezahlt':
        meldung = gettext('CHF %(betrag)s an %(lieferant)s bezahlt — noch offen CHF %(offen)s.') % {
            'betrag': betrag, 'lieferant': empfaenger, 'offen': k.offener_betrag}
    else:
        meldung = gettext('CHF %(betrag)s an %(lieferant)s bezahlt.') % {'betrag': betrag, 'lieferant': empfaenger}
    messages.success(request, '✅ ' + meldung)
    ziel = '/neu/kreditoren/'
    if lg := request.POST.get('lg'):
        ziel += f'?lg={lg}'
    return redirect(ziel)


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_zahllauf(request):
    """Zahllauf: Vorschlagsliste → Auswahl → pain.001 → Sammelbestätigung.

    Vorher war der Zahllauf ein einzelner Link, der ALLE freigegebenen Rechnungen
    ungefragt in eine Datei packte, und danach musste jede der ~40 Zahlungen
    einzeln als bezahlt geklickt werden. Beides ist in der Praxis unbrauchbar:
    ein Zahllauf ist eine bewusste Auswahl, und die Rückmeldung der Bank betrifft
    den ganzen Lauf, nicht eine Rechnung.
    """
    from django.http import HttpResponse
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, KreditorenZahlung, Buchungskonto
    from crm.models import Organisation
    from core.services.pain001 import (ZahlungsdateiFehler, auftraggeber_adresse,
                                       generate_pain001, pruefe_zahlung)
    from core.auth import log_aktion

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    def _ziel():
        z = '/neu/zahllauf/'
        if aktive_lg:
            z += f'?lg={aktive_lg.id}'
        return z

    def _auswahl(status, sperren=False, vier_augen=True):
        """Die gewählten Rechnungen im verlangten Status. Mit `sperren=True` werden
        die Zeilen gesperrt UND der Status erst danach gelesen — nur innerhalb
        von `transaction.atomic()` zu benutzen."""
        ids = [i for i in request.POST.getlist('rechnung_ids') if str(i).isdigit()]
        qs = KreditorenRechnung.objects.filter(id__in=ids, status__in=status)
        if sperren:
            qs = qs.select_for_update(of=('self',)).order_by('id')   # feste Reihenfolge: keine Sperr-Kreuze
        if aktive_lg:
            qs = qs.filter(liegenschaft=aktive_lg)
        # Rechnungen mit ausstehender/abgelehnter Eigentümerfreigabe fallen aus
        # der Auswahl — laut, nicht still (finance/freigabe.py).
        from finance.freigabe import freigabe_sperre
        frei, gesperrt_n, vier_augen_n = [], 0, 0
        for k in qs.select_related('liegenschaft'):
            if freigabe_sperre(k):
                gesperrt_n += 1
            elif vier_augen and _vier_augen_pruefen(request, k):
                # Vier-Augen-Prinzip: Rechnungen ab dem Limit fallen aus dem Lauf,
                # bis eine zweite Person die Zahlung freigegeben hat — laut, nicht still.
                vier_augen_n += 1
            else:
                frei.append(k)
        if gesperrt_n:
            messages.error(request, '⛔ ' + gettext(
                '%(n)s Rechnung(en) ausgelassen: Eigentümerfreigabe der Reparatur fehlt oder wurde abgelehnt.') % {'n': gesperrt_n})
        if vier_augen_n:
            messages.error(request, '⛔ ' + gettext(
                '%(n)s Rechnung(en) ausgelassen: Die Zahlung braucht die Freigabe einer zweiten Person '
                '(Freigabelimit). Sie ist vorgelegt.') % {'n': vier_augen_n})
        return frei

    def _datum(name, standard):
        try:
            return date.fromisoformat(request.POST.get(name) or '')
        except ValueError:
            return standard

    if request.method == 'POST':
        aktion = request.POST.get('aktion')

        # --- 1) Zahlungsdatei für die AUSGEWÄHLTEN Rechnungen ---
        if aktion == 'datei':
            vw = aktuelle_organisation()
            debtor_iban = ((vw.iban if vw else '') or '').strip()
            if not debtor_iban:
                messages.error(request, gettext('Für die Zahlungsdatei fehlt die IBAN der Verwaltung (Profil → Account).'))
                return redirect(_ziel())
            # Ausführungsdatum ist frei wählbar — die Bank führt den Lauf an
            # diesem Tag aus; «heute» war eine stille Annahme (Praxis-Audit).
            exec_date = _datum('ausfuehrungsdatum', heute)
            with transaction.atomic():
                # GESPERRT UND DANACH AUSGEWÄHLT (Audit FIN-02): Zwei parallele
                # Läufe lasen dieselben Rechnungen als «freigegeben» und lieferten
                # zwei Dateien mit denselben Zahlungen — in zwei Dateien ins
                # E-Banking geladen, zahlt die Bank doppelt. Jetzt sperrt der
                # erste die Zeilen und setzt sie auf «in Zahlung»; der zweite
                # wartet und findet sie nicht mehr «freigegeben».
                rechnungen = _auswahl(['freigegeben'], sperren=True)
                if not rechnungen:
                    messages.error(request, gettext('Keine Rechnung ausgewählt — oder die Rechnungen sind bereits in einer Zahlungsdatei.'))
                    return redirect(_ziel())
                jetzt = timezone.now()
                msg_id = f"SWISSIMMO-{jetzt.strftime('%Y%m%d%H%M%S')}"
                # Vor der Dateierzeugung wird JEDE Zahlung geprüft (IBAN-Prüfsumme,
                # Anschrift, Referenzart). Eine fehlerhafte Zahlung wird nicht
                # stillschweigend ausgelassen, sondern der ganze Lauf abgelehnt und je
                # Kreditor gemeldet — sonst wüsste niemand, dass sie fehlt. Die Ablehnung
                # ändert nichts: Kein Status wechselt, die Sperre endet mit dem Block.
                try:
                    xml, anzahl, summe = generate_pain001(
                        rechnungen, debtor_name=(vw.firma if vw else ''),
                        debtor_iban=debtor_iban, msg_id=msg_id,
                        exec_date=exec_date.isoformat(),
                        now_iso=jetzt.strftime('%Y-%m-%dT%H:%M:%S'),
                        debtor_adresse=auftraggeber_adresse(vw))
                except ZahlungsdateiFehler as exc:
                    request.session['zahllauf_fehler'] = [
                        {'id': p.rechnung_id, 'lieferant': str(p.lieferant),
                         'texte': [str(t) for t in p.texte],
                         'adresse': 'adresse' in p.codes}
                        for p in exc.probleme]
                    messages.error(request, '⛔ ' + gettext(
                        'Zahlungsdatei nicht erzeugt: %(n)s Eintrag/Einträge sind unvollständig. '
                        'Unten steht, was je Kreditor fehlt.') % {'n': len(exc.probleme)})
                    log_aktion(request, "Zahllauf abgelehnt", msg_id,
                               f"{len(exc.probleme)} unvollständige Zahlung(en)")
                    return redirect(_ziel())
                n = 0
                for r in rechnungen:
                    r.status = 'in_zahlung'
                    r.zahlung_ausfuehrung = exec_date
                    r.save(update_fields=['status', 'zahlung_ausfuehrung'])
                    n += 1
            # Die Datei allein erledigt den Zahllauf nicht: Gezahlt ist erst,
            # was die Sammelbestätigung verbucht. Bis dahin «läuft» der Lauf.
            from faelle.lauf_dienst import lauf_gestartet, periode_von
            lauf_gestartet('zahllauf', periode_von(heute))
            log_aktion(request, "Zahllauf erzeugt", msg_id,
                       f"{anzahl} Zahlungen, CHF {summe}, Ausführung {exec_date}")
            resp = HttpResponse(xml, content_type='application/xml')
            resp['Content-Disposition'] = f'attachment; filename="{msg_id}.xml"'
            return resp

        # --- 2) Sammelbestätigung: ausgewählte Zahlungen verbuchen ---
        if aktion == 'bezahlt':
            rechnungen = _auswahl(['in_zahlung', 'freigegeben', 'teilbezahlt'])
            if not rechnungen:
                messages.error(request, gettext('Keine Rechnung ausgewählt.'))
                return redirect(_ziel())
            bank_nr = (request.POST.get('bank_konto') or '1020').strip()
            if not Buchungskonto.objects.filter(nummer=bank_nr).exists():
                bank_nr = '1020'
            valuta = _datum('valuta', heute)
            from finance.booking import buche
            n, summe, gesperrt, schon = 0, Decimal('0.00'), 0, 0
            for r in rechnungen:
                try:
                    with transaction.atomic():
                        # SPERREN, DANN PRÜFEN (Audit FIN-02): Drei parallele
                        # Bestätigungen buchten 8 statt 3 Zahlungen (4'000 statt
                        # 1'500). Was die Auswahl oben gelesen hat, ist veraltet,
                        # sobald ein anderer Lauf dieselbe Rechnung bezahlt.
                        r = KreditorenRechnung.objects.select_for_update(of=('self',)).get(pk=r.pk)
                        offen = r.offener_betrag
                        if r.status not in ('in_zahlung', 'freigegeben', 'teilbezahlt') or offen <= 0:
                            schon += 1
                            continue
                        KreditorenZahlung.objects.create(
                            kreditor=r, betrag=offen, datum=valuta,
                            bemerkung=f"Zahllauf {valuta:%d.%m.%Y}"[:255],
                            erstellt_von=request.user)
                        buche('2000', bank_nr, offen,
                              f"Zahlung {r.lieferant} - {r.referenz}"[:255],
                              datum=valuta, liegenschaft=r.liegenschaft,
                              kreditor=r, user=request.user)
                        r.status = 'bezahlt' if r.offener_betrag <= 0 else 'teilbezahlt'
                        r.save(update_fields=['status'])
                    n += 1
                    summe += offen
                except PermissionError:
                    # Nie stillschweigend überspringen — der Lauf gälte sonst
                    # als vollständig verbucht.
                    gesperrt += 1
            # Abschluss erst, wenn keine Rechnung mehr in einer Zahlungsdatei
            # hängt: Bei einer Teilbestätigung steht der Rest noch aus.
            if n and not KreditorenRechnung.objects.filter(status='in_zahlung').exists():
                from faelle.lauf_dienst import lauf_erledigt, periode_von
                lauf_erledigt('zahllauf', periode_von(heute),
                              benutzer=request.user, auch_aeltere=True, verbucht=n)
            log_aktion(request, "Zahllauf verbucht", f"{n} Zahlungen",
                       f"CHF {summe} · Valuta {valuta} · Konto {bank_nr}")
            if n:
                messages.success(request, '✅ ' + gettext('%(n)s Zahlung(en) über CHF %(summe)s verbucht (2000 an %(bank_nr)s, Valuta %(valuta)s).') % {'n': n, 'summe': summe, 'bank_nr': bank_nr, 'valuta': format(valuta, '%d.%m.%Y')})
            if gesperrt:
                messages.error(request, '⚠️ ' + gettext('%(gesperrt)s Zahlung(en) nicht verbucht: die Buchungsperiode ist gesperrt.') % {'gesperrt': gesperrt})
            if schon:
                messages.info(request, gettext('%(schon)s Rechnung(en) waren schon bezahlt — nicht noch einmal verbucht.') % {'schon': schon})
            return redirect(_ziel())

        # --- 3) Auswahl zurück auf «freigegeben» (Lauf nicht ausgeführt) ---
        if aktion == 'zuruecksetzen':
            with transaction.atomic():
                # Gesperrt: Läuft gleichzeitig die Sammelbestätigung, darf eine
                # eben bezahlte Rechnung nicht wieder «freigegeben» werden.
                rechnungen = _auswahl(['in_zahlung'], sperren=True, vier_augen=False)
                for r in rechnungen:
                    r.status = 'freigegeben'
                    r.save(update_fields=['status'])
            log_aktion(request, "Zahllauf zurückgesetzt", f"{len(rechnungen)} Rechnungen", '')
            messages.success(request, '↩︎ ' + gettext('%(len)s Rechnung(en) wieder freigegeben.') % {'len': len(rechnungen)})
            return redirect(_ziel())

        return redirect(_ziel())

    # --- GET: Vorschlagsliste ---
    # 'teilbezahlt' MUSS mit rein: Nach einer Teilzahlung bleibt ein offener Rest —
    # ohne diesen Status verschwand die Rechnung aus dem Zahllauf und der Rest wurde
    # nie zur Zahlung vorgeschlagen (Live-Test H9).
    qs = (KreditorenRechnung.objects
          .filter(status__in=['freigegeben', 'in_zahlung', 'teilbezahlt'])
          .select_related('liegenschaft', 'zahlung_beantragt_von', 'zahlung_freigegeben_von')
          .prefetch_related('zahlungen')
          .order_by('faellig_am', 'id'))
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    from core.auth import ZAHLUNGSFREIGABE_ROLLEN, hat_rolle
    vw = aktuelle_organisation()
    darf_freigeben = hat_rolle(request.user, ZAHLUNGSFREIGABE_ROLLEN)
    vorschlag, laufend = [], []
    summe_vorschlag = Decimal('0.00')
    summe_laufend = Decimal('0.00')
    ohne_iban = 0
    for r in qs:
        offen = r.offener_betrag
        zeile = {
            'k': r, 'offen': offen,
            'iban': (r.iban or '').strip(),
            'faellig': r.faellig_am,
            'ueberfaellig': bool(r.faellig_am and r.faellig_am < heute),
            'objekt': (f"{r.liegenschaft.strasse}, {r.liegenschaft.ort}"
                       if r.liegenschaft else '—'),
        }
        if r.status == 'in_zahlung':
            laufend.append(zeile); summe_laufend += offen
        else:
            # Was die Zahlungsdatei an dieser Rechnung beanstanden würde — vor dem
            # Klick sichtbar, statt erst als Ablehnung danach.
            beanstandet = pruefe_zahlung(r)
            zeile['probleme'] = [t for _c, t in beanstandet]
            zeile['va'] = _vier_augen(r, request.user, vw, darf_freigeben)
            zeile['adresse_fehlt'] = any(c == 'adresse' for c, _t in beanstandet)
            vorschlag.append(zeile); summe_vorschlag += offen
            if not zeile['iban']:
                ohne_iban += 1

    vw = aktuelle_organisation()
    from django.contrib import messages as _msg
    # nav 'zahllauf' (bis v8: 'kreditoren'): Der Zahllauf steht in der
    # Navigation unter «Läufe» (core/navigation.py), und die Brotkrume der
    # Seite sagt «Läufe / Zahllauf» — mit 'kreditoren' leuchtete «Finanzen».
    return render(request, 'fw/zahllauf.html', {
        **basis, 'nav': 'zahllauf',
        'vorschlag': vorschlag, 'laufend': laufend,
        'summe_vorschlag': summe_vorschlag, 'summe_laufend': summe_laufend,
        'ohne_iban': ohne_iban, 'heute': heute,
        'fehler_liste': request.session.pop('zahllauf_fehler', []),
        'verwaltung_iban': ((vw.iban if vw else '') or '').strip(),
        'bankkonten': Buchungskonto.objects.filter(nummer__startswith='10').order_by('nummer'),
        'meldung': list(_msg.get_messages(request)),
    })


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_kreditor_zahlung_zuruecksetzen(request, pk):
    """Setzt eine 'in Zahlung' stehende Rechnung auf 'freigegeben' zurück —
    falls die pain.001-Datei doch nicht ausgeführt wurde. Dann kommt sie im
    nächsten Zahllauf wieder mit."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    k = get_object_or_404(KreditorenRechnung, id=pk)
    with transaction.atomic():
        # Gesperrt und danach geprüft: Eine Rechnung, die gerade bezahlt wird,
        # darf nicht wieder «freigegeben» werden.
        k = KreditorenRechnung.objects.select_for_update(of=('self',)).get(pk=k.pk)
        zurueckgesetzt = k.status == 'in_zahlung'
        if zurueckgesetzt:
            k.status = 'freigegeben'
            k.save(update_fields=['status'])
    if zurueckgesetzt:
        log_aktion(request, "Zahllauf zurückgesetzt", k.lieferant or f"Rechnung #{k.id}", '')
        messages.success(request, '↩︎ ' + gettext("'%(lieferant)s' wieder freigegeben (nicht mehr in Zahlung).") % {'lieferant': k.lieferant})
    ziel = '/neu/kreditoren/'
    if lg := request.POST.get('lg'):
        ziel += f'?lg={lg}'
    return redirect(ziel)


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_kreditor_zahlung_stornieren(request, pk):
    """Storniert eine VERBUCHTE Lieferantenzahlung revisionssicher: Gegenbuchung
    zur Zahlungsbuchung (2000 an Bank), Zahlung → 'storniert', der offene Posten
    der Kreditorenrechnung öffnet sich wieder.

    Live-Test H9: `fw_zahlung_stornieren` deckt nur EINGEHENDE Zahlungen
    (Zahlungseingang) ab. Eine an den falschen Lieferanten oder mit falschem
    Betrag AUSGEFÜHRTE Zahlung liess sich gar nicht mehr rückgängig machen — nur
    per Handbuchung, und der offene Posten blieb falsch (bezahlt, obwohl das Geld
    zurückkommt)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenZahlung, Buchung
    from finance.services import erstelle_storno_buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    naechstes = request.POST.get('next') or '/neu/kreditoren/'
    try:
        with transaction.atomic():
            # Zeilensperre gegen Doppel-Storno (zwei parallele Requests).
            z = get_object_or_404(
                KreditorenZahlung.objects.select_for_update().select_related('kreditor'), id=pk)
            if z.status == 'storniert':
                messages.info(request, gettext('Diese Zahlung ist bereits storniert.'))
                return redirect(naechstes)
            k = z.kreditor
            # Die zur Zahlung gehörende Buchung finden und gegenbuchen. Diskriminator:
            # Sollkonto 2000 (die Rechnungsbuchung trägt 2000 im HABEN, nur die
            # Zahlung im SOLL), Betrag und Datum der Zahlung. Bei mehreren identischen
            # Zahlungen ist jede Umkehr finanziell gleichwertig (gleiche Konten/Betrag).
            buchung = (Buchung.objects.filter(
                kreditoren_rechnung=k, soll_konto__nummer='2000',
                betrag=z.betrag, datum=z.datum,
                ist_storno=False, storniert_am__isnull=True).order_by('id').first())
            if buchung is not None:
                erstelle_storno_buchung(buchung, benutzer=request.user)
            z.status = 'storniert'
            z.save(update_fields=['status'])
            # Rechnungsstatus nachführen (offener_betrag zählt nur 'verbucht'):
            if k.status != 'storniert':
                if k.offener_betrag <= 0:
                    k.status = 'bezahlt'
                elif k.offener_betrag >= (k.betrag or Decimal('0.00')):
                    k.status = 'freigegeben'
                else:
                    k.status = 'teilbezahlt'
                k.save(update_fields=['status'])
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(naechstes)
    except Exception as exc:
        messages.error(request, '❌ ' + gettext('Zahlung konnte nicht storniert werden: %(exc)s') % {'exc': exc})
        return redirect(naechstes)
    log_aktion(request, "Lieferantenzahlung storniert", k.lieferant or f"Rechnung #{k.id}",
               f"CHF {z.betrag}")
    messages.success(request, '✅ ' + gettext('Zahlung über CHF %(betrag)s an %(wert)s storniert — offener Posten wieder offen.') % {'betrag': z.betrag, 'wert': k.lieferant or 'Lieferant'})
    return redirect(naechstes)


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
def fw_kreditor_adresse(request, pk):
    """Anschrift einer Kreditorenrechnung ergänzen — auch nach der Freigabe.

    Das Bearbeiten-Formular gilt nur für Rechnungen im Status «Neu». Die
    Zahlungsdatei verlangt die Anschrift aber gerade von den freigegebenen
    (Swiss Payment Standards ab 14.11.2026). Diese Seite ändert deshalb NUR die
    fünf Anschriftsfelder: keine Buchung, kein Betrag, keine IBAN.

    Die Anschrift wird zugleich im Lieferantenprofil gemerkt und, wenn gewünscht,
    bei den übrigen offenen Rechnungen desselben Lieferanten eingetragen, die
    noch keine haben (nie überschrieben)."""
    from django.contrib import messages
    from django.shortcuts import redirect
    from django.utils.http import url_has_allowed_host_and_scheme
    from core.auth import log_aktion
    from finance.forms import KreditorAdresseForm
    from finance.kreditor_adresse import adresse_setzen, adresse_von_rechnung
    from finance.lieferanten import lerne_adresse, lieferant_key
    from finance.models import KreditorenRechnung

    k = get_object_or_404(KreditorenRechnung, id=pk)
    ziel = request.POST.get('next') or request.GET.get('next') or '/neu/kreditoren/'
    if not (ziel.startswith('/neu/') and url_has_allowed_host_and_scheme(
            ziel, allowed_hosts={request.get_host()})):
        ziel = '/neu/kreditoren/'
    if k.status in ('bezahlt', 'storniert'):
        messages.error(request, gettext('Bei einer bezahlten oder stornierten Rechnung wird die Anschrift nicht mehr geändert.'))
        return redirect(ziel)

    werte, fehler = adresse_von_rechnung(k), {}
    werte = {f'lieferant_{f}': v for f, v in werte.items()}
    if request.method == 'POST':
        form = KreditorAdresseForm(request.POST)
        werte = {n: request.POST.get(n, '') for n in werte}
        if form.is_valid():
            c = form.cleaned_data
            adresse = {f: c[f'lieferant_{f}'] for f in ('strasse', 'hausnummer', 'plz', 'ort', 'land')}
            adresse_setzen(k, adresse)
            k.save(update_fields=[f'lieferant_{f}' for f in adresse])
            lerne_adresse(k.lieferant, adresse)
            weitere = 0
            schluessel = lieferant_key(k.lieferant)
            if request.POST.get('weitere') == '1' and schluessel:
                for w in KreditorenRechnung.objects.filter(
                        status__in=['neu', 'freigegeben', 'in_zahlung', 'teilbezahlt'],
                        lieferant_ort='').exclude(id=k.id):
                    if lieferant_key(w.lieferant) == schluessel:
                        adresse_setzen(w, adresse)
                        w.save(update_fields=[f'lieferant_{f}' for f in adresse])
                        weitere += 1
            log_aktion(request, "Kreditor-Anschrift ergänzt", k.lieferant or f"Rechnung #{k.id}",
                       f"{adresse['plz']} {adresse['ort']} ({adresse['land']})"
                       + (f", {weitere} weitere Rechnung(en)" if weitere else ""))
            messages.success(request, '✅ ' + gettext('Anschrift von «%(lieferant)s» gespeichert.') % {
                'lieferant': k.lieferant}
                + (' ' + gettext('Auch bei %(n)s weiteren offenen Rechnungen eingetragen.') % {'n': weitere}
                   if weitere else ''))
            return redirect(ziel)
        fehler = {name: liste[0] for name, liste in form.errors.items() if name != '__all__'}
    basis = _global_filter(request)
    return render(request, 'fw/kreditor_adresse.html', {
        **basis, 'nav': 'kreditoren', 'k': k, 'werte': werte, 'fehler': fehler,
        'anzahl_fehler': len(fehler), 'ziel': ziel,
    }, status=400 if fehler else 200)


# ---------------------------------------------------------------------------
# VIER-AUGEN-PRINZIP: Zahlung vorlegen, freigeben, zurücknehmen
# ---------------------------------------------------------------------------

def _zurueck(request):
    ziel = '/neu/kreditoren/'
    if lg := request.POST.get('lg'):
        ziel += f'?lg={lg}'
    return ziel


def _gesperrt_holen(pk):
    """Die Rechnung gesperrt lesen: Vorlegen und Freigeben stehen nicht gleichzeitig an."""
    from finance.models import KreditorenRechnung
    get_object_or_404(KreditorenRechnung, id=pk)         # Mandantengrenze zuerst (fremde ID -> 404)
    return KreditorenRechnung.objects.select_for_update(of=('self',)).get(pk=pk)


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_kreditor_zahlung_vorlegen(request, pk):
    """Eine Zahlung ab dem Freigabelimit der zweiten Person zur Freigabe vorlegen."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from core.auth import log_aktion
    from finance.freigabe import braucht_zahlungsfreigabe, vorlegen
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    with transaction.atomic():
        k = _gesperrt_holen(pk)
        if k.status not in ('freigegeben', 'in_zahlung', 'teilbezahlt'):
            messages.error(request, gettext('Nur eine freigegebene, offene Rechnung lässt sich zur Zahlung vorlegen.'))
        elif not braucht_zahlungsfreigabe(k, aktuelle_organisation()):
            messages.info(request, gettext('Diese Rechnung liegt unter dem Freigabelimit — keine Freigabe nötig.'))
        elif vorlegen(k, request.user):
            log_aktion(request, 'Zahlung zur Freigabe vorgelegt', k.lieferant or f'Rechnung #{k.id}',
                       f'CHF {k.betrag}')
            messages.success(request, '✅ ' + gettext('Die Zahlung ist zur Freigabe durch eine zweite Person vorgelegt.'))
        else:
            messages.info(request, gettext('Die Zahlung ist bereits vorgelegt oder freigegeben.'))
    return redirect(_zurueck(request))


@rolle_erforderlich(*ZAHLUNGSFREIGABE_ROLLEN)
def fw_kreditor_zahlung_freigeben(request, pk):
    """Die vorgelegte Zahlung freigeben. Nur Verwalter und Inhaber, und nie die Person,
    die sie vorgelegt hat (Vier-Augen-Prinzip)."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from core.auth import log_aktion
    from finance.freigabe import FreigabeFehler, freigeben
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    with transaction.atomic():
        k = _gesperrt_holen(pk)
        try:
            freigeben(k, request.user)
        except FreigabeFehler as exc:
            log_aktion(request, 'Zahlungsfreigabe abgelehnt', k.lieferant or f'Rechnung #{k.id}',
                       f'CHF {k.betrag} · {exc}')
            messages.error(request, '⛔ ' + str(exc))
        else:
            log_aktion(request, 'Zahlung freigegeben (Vier-Augen-Prinzip)', k.lieferant or f'Rechnung #{k.id}',
                       f'CHF {k.betrag} · IBAN {k.zahlung_freigabe_iban} · vorgelegt von '
                       f'{_name(k.zahlung_beantragt_von)}')
            messages.success(request, '✅ ' + gettext('Die Zahlung ist freigegeben und kann ausgelöst werden.'))
    return redirect(_zurueck(request))


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_kreditor_zahlung_zuruecknehmen(request, pk):
    """Vorlage oder Freigabe verwerfen. Die Zahlung ist danach wieder gesperrt."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from core.auth import log_aktion
    from finance.freigabe import zuruecknehmen
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    with transaction.atomic():
        k = _gesperrt_holen(pk)
        if k.zahlung_beantragt_von_id or k.zahlung_freigegeben_von_id:
            zuruecknehmen(k)
            log_aktion(request, 'Zahlungsfreigabe zurückgenommen', k.lieferant or f'Rechnung #{k.id}',
                       f'CHF {k.betrag}')
            messages.success(request, gettext('Vorlage und Freigabe sind verworfen.'))
    return redirect(_zurueck(request))
