# core/views/fw/bankabgleich.py
#
# Offene Posten mit Zahlungseingaengen abgleichen: camt.053- und CSV-Import,
# Zuordnung, Verbuchung, und das Rueckgaengigmachen eines Imports.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Der groesste bisher verschobene Block (1'087 Zeilen) und zugleich einer der
# heikelsten: camt.053, QR-Referenz (QRR, 27 Stellen) und die
# revisionssichere Storno-Kette beim Rueckgaengigmachen stehen im Skill
# schweizer-fachlogik. Der Umzug aendert nichts -- Blockinhalt gegen HEAD
# Zeile fuer Zeile geprueft.
#
# Drei der neun paketweit weitergereichten Helfer stehen hier:
# _bank_csv_parse, _camt_kopf, _camt_parse. Das __init__.py holt sie jetzt
# von hier, FwFassadeTests haelt fest, dass sie erreichbar bleiben.

import logging
import os
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
from crm.models import Mieter
from finance.models import DebitorenRechnung, Zahlungseingang
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag

logger = logging.getLogger(__name__)

from ._basis import _global_filter, _num, _park_konto


# ============================================================
# ETAPPE D: BANKABGLEICH (offene Posten mit Zahlung abgleichen)
# ============================================================

def _qrr_referenz(rechnung):
    """Erzeugt eine strukturierte 27-stellige QRR-Referenz mit Modulo-10-rekursiv-Prüfziffer
    aus Vertrags- und Rechnungs-ID (stabil, damit Zahlungseingänge zuordenbar sind)."""
    basis = f"{(rechnung.vertrag_id or 0):010d}{rechnung.id:016d}"
    tabelle = [0, 9, 4, 6, 8, 2, 7, 1, 3, 5]
    uebertrag = 0
    for z in basis:
        uebertrag = tabelle[(uebertrag + int(z)) % 10]
    pruef = (10 - uebertrag) % 10
    ref = basis + str(pruef)
    return ' '.join([ref[0:2], ref[2:7], ref[7:12], ref[12:17], ref[17:22], ref[22:27]])


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_bankabgleich(request):
    from django.db.models import Q as _Q, Sum
    from finance.models import Buchungskonto, KreditorenRechnung
    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (DebitorenRechnung.objects
          .filter(status__in=['offen', 'teilbezahlt'])
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft')
          .prefetch_related('zahlungseingaenge')
          .order_by('faellig_am'))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))

    rows = []
    total_offen = Decimal('0.00')
    for r in qs:
        offen = r.offener_betrag
        if offen <= 0:
            continue
        total_offen += offen
        lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
        faellig = r.faellig_am or r.datum
        rows.append({
            'r': r, 'offen': offen,
            'mieter': r.vertrag.mieter.display_name if r.vertrag_id else '—',
            'objekt': f"{lg.strasse}, {lg.ort}" if lg else '—',
            'faellig': faellig,
            'ueberfaellig': bool(faellig and faellig < heute),
            'qrr': _qrr_referenz(r) if r.vertrag_id else '—',
            'kann_verbuchen': bool(r.vertrag_id),
        })

    # Kürzliche Abgleiche (verbuchte Zahlungen) als Kontext.
    # Erst filtern, DANN slicen — ein bereits geslicetes QuerySet lässt sich nicht
    # mehr filtern (TypeError → HTTP 500, sobald ein Liegenschaftsfilter aktiv ist).
    letzte_qs = (Zahlungseingang.objects.filter(status='verbucht')
                 .select_related('vertrag__mieter')
                 .prefetch_related('bankbewegungen'))
    if aktive_lg:
        letzte_qs = letzte_qs.filter(vertrag__einheit__liegenschaft=aktive_lg)
    letzte = list(letzte_qs.order_by('-erstellt_am')[:8])
    # Wer wurde da abgeglichen? Die Zeile zeigte «Mieter · Bemerkung» in EINER
    # gekürzten Spalte — auf dem Handy blieb davon «B..» übrig. Titel (wer) und
    # Herkunft (woher der Beleg kam) werden deshalb getrennt bereitgestellt;
    # ohne Vertrag tritt der erkannte Absender an die Stelle des Mieternamens,
    # sonst begann die Zeile mit einem führenden « · ».
    from core.services import zahler as _zahler
    for z in letzte:
        bew = next(iter(z.bankbewegungen.all()), None)
        name, rest, _geraten = _zahler.aus_bewegung(
            (bew.gegenpartei if bew else ''),
            (bew.text if bew else '') or (z.bemerkung or ''))
        if z.vertrag_id and z.vertrag.mieter_id:
            z.titel = z.vertrag.mieter.display_name
            z.zusatz = ' · '.join(t for t in [name, rest] if t)
        else:
            z.titel = name or (rest or 'Ohne Vertrag')
            z.zusatz = rest if name else ''

    # Geparkte Zahlungen (Durchlaufkonto 1190 / Mieterguthaben 2030) mit
    # Zuordnungs-Aktion — Audit-Befund: ohne diese Liste ist jede ungeklärte
    # Gutschrift eine Sackgasse.
    # Der Liegenschaftsfilter greift nur auf Positionen, die überhaupt einer
    # Liegenschaft zugeordnet sind; wirklich ungeklärtes Geld (ohne Vertrag und
    # ohne Liegenschaft) bleibt immer sichtbar, sonst wäre es erneut unauffindbar.
    geparkt_qs = (Zahlungseingang.objects
                  .filter(status='verbucht', konto__nummer__in=['1190', '2030'])
                  .select_related('vertrag__mieter', 'konto'))
    if aktive_lg:
        geparkt_qs = geparkt_qs.filter(
            _Q(liegenschaft=aktive_lg)
            | _Q(vertrag__einheit__liegenschaft=aktive_lg)
            | _Q(liegenschaft__isnull=True, vertrag__isnull=True))
    geparkt = list(geparkt_qs.order_by('-datum_eingang')
                   .prefetch_related('bankbewegungen'))
    # Wer hat bezahlt? Stand bisher nirgends — die Zeile zeigte nur den
    # abgeschnittenen Importtext («Bank-CSV UNG…»). Der Auftraggeber liegt in
    # der zugehörigen Auszugszeile (Bankbewegung.gegenpartei); Mitteilung und
    # Referenz gleich mit, das sind die Anhaltspunkte für die Zuordnung.
    from core.services import zahler as _zahler
    for z in geparkt:
        bew = next(iter(z.bankbewegungen.all()), None)
        roh_text = (bew.text if bew else '') or ''
        if not roh_text:
            # Altbestand (vor der Auszugszeile) trägt den Text nur in der Bemerkung.
            t = (z.bemerkung or '').split('UNGEKLÄRT:', 1)
            roh_text = (t[1] if len(t) > 1 else t[0]).strip()
        z.zahler, z.mitteilung, z.zahler_geraten = _zahler.aus_bewegung(
            (bew.gegenpartei if bew else ''), roh_text)
        if not z.zahler and z.vertrag_id and z.vertrag.mieter_id:
            z.zahler, z.zahler_geraten = z.vertrag.mieter.display_name, False
        z.ref = ((bew.referenz if bew else '') or '').strip()
    # 1190 (Aktiv, ungeklärt) und 2030 (Passiv, Mieterguthaben) sind fachlich
    # verschieden und werden nicht zu einer Summe vermischt.
    geparkt_unklar = sum((z.betrag for z in geparkt if z.konto and z.konto.nummer == '1190'),
                         Decimal('0.00'))
    geparkt_guthaben = sum((z.betrag for z in geparkt if z.konto and z.konto.nummer == '2030'),
                           Decimal('0.00'))

    # --- BANK-EINGANG: offene Auszugszeilen ---
    # Das war der Kern des Befunds: Der Screen hiess «Bankabgleich», zeigte aber
    # nie eine Bankbewegung — nur offene Debitoren zum Quittieren. Abstimmen
    # konnte man damit nichts (Praxis-Audit).
    from finance.models import Bankbewegung, Kontoauszug
    bew_qs = (Bankbewegung.objects.filter(status='offen')
              .select_related('konto', 'liegenschaft').order_by('-datum', '-id'))
    if aktive_lg:
        bew_qs = bew_qs.filter(_Q(liegenschaft=aktive_lg) | _Q(liegenschaft__isnull=True))
    bewegungen = list(bew_qs[:100])
    bew_offen_n = bew_qs.count()
    # Summen über ALLE offenen Bewegungen, nicht nur die ersten 100 — sonst
    # unterschlägt der Kopf Geld, das weiter unten in der Liste liegt.
    bew_eingang = (bew_qs.filter(betrag__gt=0).aggregate(t=Sum('betrag'))['t']
                   or Decimal('0.00'))
    bew_ausgang = (bew_qs.filter(betrag__lt=0).aggregate(t=Sum('betrag'))['t']
                   or Decimal('0.00'))

    # Letzte Importe (für «Import rückgängig machen»).
    letzte_auszuege = list(Kontoauszug.objects.select_related('konto')
                           .order_by('-importiert_am', '-id')[:6])
    # Letzter Auszug je Bankkonto + Saldoabgleich
    letzter_auszug = Kontoauszug.objects.select_related('konto').order_by('-bis', '-id').first()
    saldo_abgleich = None
    if letzter_auszug and letzter_auszug.schlusssaldo is not None:
        from finance.models import Buchung as _BB
        # Ohne `storniert_am__isnull=True` meldete der Abstimmungsnachweis eine
        # Differenz zum Auszug, die es nicht gibt (storniertes Original zählte
        # weiter, Gegenbuchung war ausgeblendet).
        _bq = _BB.objects.filter(ist_storno=False, storniert_am__isnull=True)
        if letzter_auszug.bis:
            _bq = _bq.filter(datum__lte=letzter_auszug.bis)
        _s = _bq.filter(soll_konto=letzter_auszug.konto).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        _h = _bq.filter(haben_konto=letzter_auszug.konto).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        _buch = (_s - _h).quantize(Decimal('0.01'))
        saldo_abgleich = {
            'auszug': letzter_auszug, 'buchhaltung': _buch,
            'differenz': (letzter_auszug.schlusssaldo - _buch).quantize(Decimal('0.01')),
        }

    # Mieter-Auswahl für die Sammelzuordnung: je Vertrag EIN Eintrag, nur wo es
    # überhaupt etwas zu tilgen gibt. `rows` enthält je offene Rechnung eine Zeile.
    sammel_vertraege = []
    _gesehen = set()
    for _r in rows:
        _v = getattr(_r.get('r'), 'vertrag', None) if isinstance(_r, dict) else None
        if _v is None or _v.id in _gesehen:
            continue
        _gesehen.add(_v.id)
        _offene = sum(1 for x in rows
                      if isinstance(x, dict) and getattr(x.get('r'), 'vertrag_id', None) == _v.id)
        sammel_vertraege.append({
            'id': _v.id,
            'label': f"{_r.get('mieter')} · {_r.get('objekt')} ({_offene} offen)",
        })
    sammel_vertraege.sort(key=lambda x: x['label'].lower())

    bankkonten = Buchungskonto.objects.filter(nummer__startswith='10').order_by('nummer')

    from django.contrib import messages
    return render(request, 'fw/bankabgleich.html', {
        **basis, 'nav': 'bankabgleich', 'rows': rows,
        'bewegungen': bewegungen, 'bew_offen_n': bew_offen_n,
        'bew_eingang': bew_eingang, 'bew_ausgang': bew_ausgang,
        'saldo_abgleich': saldo_abgleich, 'bankkonten': bankkonten,
        'letzte_auszuege': letzte_auszuege,
        'aufwandkonten': Buchungskonto.objects.all().order_by('nummer'),
        # 'neu' gehört dazu: die Belastung hat die Bank BEREITS verlassen. Wer nur
        # freigegebene Rechnungen anbietet, lässt eine reale Zahlung unzuordenbar.
        'offene_kreditoren': (KreditorenRechnung.objects
                              .filter(status__in=['neu', 'freigegeben', 'in_zahlung',
                                                  'teilbezahlt'])
                              .select_related('liegenschaft')
                              .order_by('faellig_am', 'id')[:200]),
        'total_offen': total_offen, 'anzahl': len(rows),
        'letzte': letzte,
        'geparkt': geparkt,
        # Für die Sammelzuordnung: je Mieter EIN Eintrag mit der Zahl seiner
        # offenen Forderungen — die Auswahl trifft den Mieter, nicht die
        # einzelne Rechnung; getilgt wird dann automatisch die älteste zuerst.
        'sammel_vertraege': sammel_vertraege,
        'geparkt_unklar': geparkt_unklar, 'geparkt_guthaben': geparkt_guthaben,
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bankabgleich_verbuchen(request):
    """Verbucht eine (Teil-)Zahlung für einen offenen Posten — Bank an Debitoren,
    dieselbe Doppelbuchung + OP-Fortschreibung wie die Finanz-API."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_bankabgleich')

    rechnung = get_object_or_404(DebitorenRechnung, id=request.POST.get('rechnung_id'))
    if not rechnung.vertrag_id:
        messages.error(request, "Position ohne Vertrag kann nicht automatisch verbucht werden.")
        return redirect('fw_bankabgleich')
    # Status-Guard: auf stornierte/bezahlte Rechnungen darf keine Zahlung gebucht
    # werden — sonst springt eine STORNIERTE Rechnung auf «bezahlt» und das
    # Mieterkonto zeigt ein Haben ohne Soll (real im Audit passiert).
    if rechnung.status not in ('offen', 'teilbezahlt'):
        messages.error(request, f"«{rechnung.titel}» ist {rechnung.get_status_display()} — "
                                "darauf kann keine Zahlung verbucht werden.")
        return redirect('fw_bankabgleich')

    offen = rechnung.offener_betrag
    raw = (request.POST.get('betrag') or '').strip()
    if raw:
        try:
            betrag = Decimal(_num(raw))
        except Exception:
            messages.error(request, f"Ungültiger Betrag «{raw}».")
            return redirect('fw_bankabgleich')
    else:
        betrag = offen
    # Explizite 0/Negativ-Eingabe ist ein Tippfehler — abbrechen statt still
    # auf 0.01 zu klemmen (verwirrende Mini-Teilzahlung).
    if betrag <= 0:
        messages.error(request, "Betrag muss grösser als 0 sein.")
        return redirect('fw_bankabgleich')
    betrag = min(betrag, offen)

    heute = timezone.localdate()
    vertrag = rechnung.vertrag
    with transaction.atomic():
        zahlung = Zahlungseingang.objects.create(
            vertrag=vertrag, betrag=betrag, datum_eingang=heute,
            buchungs_monat=(rechnung.faellig_am or rechnung.datum or heute).replace(day=1),
            bemerkung=f"Bankabgleich {rechnung.titel}",
            liegenschaft=vertrag.einheit.liegenschaft,
            debitoren_rechnung=rechnung, erstellt_von=request.user, status='verbucht',
        )
        rechnung.status = 'bezahlt' if rechnung.offener_betrag <= 0 else 'teilbezahlt'
        rechnung.save()
        from finance.booking import buche
        buche("1020", "1100", betrag, f"Bankabgleich {vertrag.mieter} - {rechnung.titel}",
              datum=heute, liegenschaft=vertrag.einheit.liegenschaft, zahlung=zahlung,
              user=request.user)

    log_aktion(request, "Zahlung via Bankabgleich verbucht", str(vertrag),
               f"CHF {betrag} auf {rechnung.titel}")
    messages.success(request, f"✅ CHF {betrag} verbucht — {vertrag.mieter.display_name} ({rechnung.titel}).")
    from django.shortcuts import redirect as _r
    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'
    return _r(ziel)


def _camt_localname(tag):
    """Entfernt den XML-Namespace ({...}Ntry -> Ntry)."""
    return tag.split('}')[-1] if '}' in tag else tag


def _camt_find(el, *pfad):
    """Namespace-agnostisches Suchen entlang eines Pfads von Localnames."""
    cur = el
    for name in pfad:
        gefunden = None
        for kind in list(cur):
            if _camt_localname(kind.tag) == name:
                gefunden = kind
                break
        if gefunden is None:
            return None
        cur = gefunden
    return cur


def _camt_tx_details(el, richtung='CRDT'):
    """Liest Referenz / Mitteilung / Bank-Tx-Ref / Gegenpartei aus einem
    camt-Teilbaum (<Ntry> oder einzelne <TxDtls>).

    Die Gegenpartei ist bei einer Gutschrift der Auftraggeber (<Dbtr>), bei einer
    Belastung der Zahlungsempfaenger (<Cdtr>) — sonst bleibt der Lieferantenname
    im Bank-Eingang leer."""
    referenz = info = acct_ref = dbtr_name = ''
    gegen_tag = 'Dbtr' if richtung == 'CRDT' else 'Cdtr'
    in_dbtr = False
    for sub in el.iter():
        ln = _camt_localname(sub.tag)
        if ln == 'CdtrRefInf':
            ref_el = _camt_find(sub, 'Ref')
            if ref_el is not None and ref_el.text:
                referenz = ref_el.text.strip().replace(' ', '')
        elif ln == 'Ustrd' and not info and sub.text:
            info = sub.text.strip()
        elif ln in ('AcctSvcrRef', 'TxId', 'EndToEndId') and not acct_ref and sub.text:
            # 'NOTPROVIDED' ist bei Swiss-QR-Gutschriften der Standardwert und
            # KEINE eindeutige Transaktionsreferenz.
            _cand = sub.text.strip()
            if _cand.upper() != 'NOTPROVIDED':
                acct_ref = _cand
        elif ln == gegen_tag:
            in_dbtr = True
        elif ln == 'Nm' and in_dbtr and not dbtr_name and sub.text:
            dbtr_name = sub.text.strip(); in_dbtr = False
    return {'referenz': referenz, 'info': info,
            'acct_ref': acct_ref, 'dbtr_name': dbtr_name}


def _camt_kopf(xml_bytes):
    """Liest Kopfdaten des Auszugs: IBAN, Periode und Schlusssaldo.

    Ohne den Schlusssaldo gibt es keinen Abstimmungsnachweis — man kann Zahlungen
    zuordnen, aber nie belegen, dass das Buchhaltungskonto mit dem realen
    Bankkonto übereinstimmt (Praxis-Audit).
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return {}
    kopf = {'iban': '', 'von': None, 'bis': None,
            'eroeffnung': None, 'schluss': None}
    # IBAN des Auszugskontos
    for el in root.iter():
        if _camt_localname(el.tag) == 'IBAN' and el.text:
            kopf['iban'] = el.text.strip().replace(' ', '')
            break
    # Periode <FrToDt><FrDtTm>/<ToDtTm>
    for el in root.iter():
        ln = _camt_localname(el.tag)
        if ln in ('FrDtTm', 'ToDtTm') and el.text:
            try:
                d = date.fromisoformat(el.text.strip()[:10])
            except ValueError:
                continue
            kopf['von' if ln == 'FrDtTm' else 'bis'] = d
    # Salden: <Bal> mit <Cd> OPBD (Eröffnung) bzw. CLBD (Schluss)
    for bal in root.iter():
        if _camt_localname(bal.tag) != 'Bal':
            continue
        code = ''
        for sub in bal.iter():
            if _camt_localname(sub.tag) == 'Cd' and sub.text:
                code = sub.text.strip().upper()
                break
        amt = _camt_find(bal, 'Amt')
        if amt is None or not (amt.text or '').strip():
            continue
        try:
            wert = Decimal(amt.text.strip())
        except Exception:
            continue
        # Ein Habensaldo auf dem Bankkonto (CRDT) ist Guthaben → positiv.
        vz = _camt_find(bal, 'CdtDbtInd')
        if vz is not None and (vz.text or '').strip() == 'DBIT':
            wert = -wert
        if code in ('OPBD', 'PRCD'):
            kopf['eroeffnung'] = wert
        elif code in ('CLBD', 'CLAV'):
            kopf['schluss'] = wert
    return kopf


def _camt_parse(xml_bytes, nur_gutschriften=True):
    """Parst einen camt.053-Kontoauszug (ISO 20022) namespace-agnostisch.

    `nur_gutschriften=False` liefert AUCH Belastungen (negatives Vorzeichen).
    Ohne Belastungen — Lieferantenzahlungen, Gebühren, Zinsen, Daueraufträge —
    ist das Bankkonto strukturell nicht abstimmbar (Praxis-Audit).
    """
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_bytes)
    eintraege = []
    # Alle <Ntry>-Elemente unabhängig von der Verschachtelungstiefe
    for ntry in root.iter():
        if _camt_localname(ntry.tag) != 'Ntry':
            continue
        cdtdbt = _camt_find(ntry, 'CdtDbtInd')
        richtung = (cdtdbt.text or '').strip() if cdtdbt is not None else ''
        if richtung not in ('CRDT', 'DBIT'):
            continue
        if nur_gutschriften and richtung != 'CRDT':
            continue
        vorzeichen = Decimal('1') if richtung == 'CRDT' else Decimal('-1')
        amt_el = _camt_find(ntry, 'Amt')
        if amt_el is None or not (amt_el.text or '').strip():
            continue
        try:
            betrag = Decimal((amt_el.text or '0').strip())
        except Exception:
            continue
        # Buchungsdatum (Element mit Text ist in ET „falsy", daher explizit is-None prüfen)
        datum = None
        dt_el = _camt_find(ntry, 'BookgDt', 'Dt')
        if dt_el is None:
            dt_el = _camt_find(ntry, 'ValDt', 'Dt')
        if dt_el is not None and dt_el.text:
            try:
                datum = date.fromisoformat(dt_el.text.strip()[:10])
            except Exception:
                datum = None
        # Valutadatum separat — es ist das buchhalterisch massgebende Datum und
        # wich bisher stillschweigend dem Erfassungstag (Praxis-Audit).
        valuta = None
        v_el = _camt_find(ntry, 'ValDt', 'Dt')
        if v_el is not None and v_el.text:
            try:
                valuta = date.fromisoformat(v_el.text.strip()[:10])
            except Exception:
                valuta = None
        # Sammelbuchung: enthält der Eintrag mehrere <TxDtls>, ist jede davon eine
        # eigene Zahlung mit eigener QRR. Ohne diese Aufteilung würde der GESAMT-
        # betrag der zuletzt gefundenen Referenz zugeordnet und alle übrigen Mieter
        # blieben unbezahlt (Audit, kritisch) — Schweizer Banken fassen QR-Eingänge
        # eines Tages regelmässig so zusammen.
        txdtls = [t for t in ntry.iter() if _camt_localname(t.tag) == 'TxDtls']
        if len(txdtls) > 1:
            summe_tx = Decimal('0.00')
            teil_eintraege = []
            for tx in txdtls:
                tx_amt = _camt_find(tx, 'Amt')
                try:
                    tx_betrag = Decimal((tx_amt.text or '0').strip()) if tx_amt is not None else None
                except Exception:
                    tx_betrag = None
                if tx_betrag is None or tx_betrag <= 0:
                    teil_eintraege = []      # unvollständig → als Ganzes behandeln
                    break
                teil_eintraege.append((tx, tx_betrag))
                summe_tx += tx_betrag
            # Nur aufteilen, wenn die Einzelbeträge den Eintrag exakt ergeben —
            # sonst ginge Geld verloren oder würde doppelt verbucht.
            if teil_eintraege and summe_tx == betrag:
                for tx, tx_betrag in teil_eintraege:
                    eintraege.append({
                        'betrag': tx_betrag * vorzeichen, 'datum': datum, 'valuta': valuta,
                        **_camt_tx_details(tx, richtung),
                    })
                continue

        # Referenz + Info + Bank-Tx-Ref (Duplikatschutz) + Auftraggebername (Fuzzy)
        referenz = ''
        info = ''
        acct_ref = ''
        dbtr_name = ''
        # Bei einer BELASTUNG ist die Gegenpartei der Zahlungsempfänger (<Cdtr>),
        # nicht der Auftraggeber — sonst bleibt der Lieferantenname im Bank-Eingang
        # leer und die Zeile ist für den Buchhalter nicht zuordenbar (Praxis-Audit).
        gegen_tag = 'Dbtr' if richtung == 'CRDT' else 'Cdtr'
        in_dbtr = False
        for sub in ntry.iter():
            ln = _camt_localname(sub.tag)
            if ln == 'CdtrRefInf':
                ref_el = _camt_find(sub, 'Ref')
                if ref_el is not None and ref_el.text:
                    referenz = ref_el.text.strip().replace(' ', '')
            elif ln == 'Ustrd' and not info and sub.text:
                info = sub.text.strip()
            elif ln in ('AcctSvcrRef', 'TxId', 'EndToEndId') and not acct_ref and sub.text:
                # 'NOTPROVIDED' ist bei Swiss-QR-Gutschriften der Standard-EndToEndId
                # und KEINE eindeutige Transaktionsreferenz — sonst würden mehrere
                # verschiedene Zahlungen fälschlich als Duplikat verworfen (Datenverlust).
                _cand = sub.text.strip()
                if _cand.upper() != 'NOTPROVIDED':
                    acct_ref = _cand
            elif ln == gegen_tag:
                in_dbtr = True
            elif ln == 'Nm' and in_dbtr and not dbtr_name and sub.text:
                dbtr_name = sub.text.strip(); in_dbtr = False
        eintraege.append({'betrag': betrag * vorzeichen, 'referenz': referenz,
                          'datum': datum, 'valuta': valuta,
                          'info': info, 'acct_ref': acct_ref, 'dbtr_name': dbtr_name})
    return eintraege


def _bank_csv_parse(raw):
    """Parst einen Bank-Kontoauszug als CSV (PostFinance/Raiffeisen/ZKB/UBS-Exporte).

    Header-basiert und tolerant: Trennzeichen (; , Tab) wird erkannt, Spalten
    werden über Schlüsselwörter gefunden (Datum, Betrag/Gutschrift, Referenz,
    Text/Mitteilung, Auftraggeber). Nur Gutschriften (positive Beträge bzw.
    Gutschrift-Spalte) werden übernommen. Rückgabe: gleiche Struktur wie
    _camt_parse → derselbe Zuordnungs-/Verbuchungspfad."""
    import csv as _csv
    import io as _io
    import re as _re

    text = None
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, AttributeError):
            continue
    if text is None:
        raise ValueError("Datei-Codierung nicht erkannt")

    # Trennzeichen aus den ersten nicht-leeren Zeilen bestimmen
    probe = [z for z in text.splitlines() if z.strip()][:10]
    if not probe:
        return []
    zaehl = {d: sum(z.count(d) for z in probe) for d in (';', ',', '\t')}
    delim = max(zaehl, key=zaehl.get)
    zeilen = list(_csv.reader(_io.StringIO(text), delimiter=delim))

    KEY = {
        'datum': ('datum', 'date', 'buchungsdatum', 'valuta', 'booking'),
        'betrag': ('betrag', 'amount', 'umsatz'),
        'gut': ('gutschrift', 'credit', 'haben', 'eingang'),
        'last': ('lastschrift', 'belastung', 'debit', 'soll', 'ausgang'),
        'ref': ('referenz', 'reference', 'qrr', 'esr', 'referenznummer'),
        'text': ('mitteilung', 'buchungstext', 'beschreibung', 'verwendungszweck',
                 'text', 'details', 'avisierung', 'zahlungszweck'),
        # Ohne Treffer hier bleibt der Auftraggeber leer und die Zeile im
        # Bankabgleich sagt nur «von der Bank nicht geliefert» — darum breit fassen.
        'name': ('auftraggeber', 'absender', 'zahlungspflichtiger', 'einzahler',
                 'name', 'gegenpartei', 'debitor', 'begünstigter', 'beguenstigter',
                 'partner', 'kontoinhaber', 'zahler', 'counterparty', 'payer'),
    }

    def _spalte(kopf, schluessel):
        for i, z in enumerate(kopf):
            zl = (z or '').strip().lower()
            if any(k in zl for k in KEY[schluessel]):
                return i
        return None

    # Header-Zeile suchen (erste Zeile mit Datum- UND Betrag/Gutschrift-Spalte)
    kopf_idx = None
    sp = {}
    for i, z in enumerate(zeilen[:15]):
        if _spalte(z, 'datum') is not None and (
                _spalte(z, 'betrag') is not None or _spalte(z, 'gut') is not None):
            kopf_idx = i
            sp = {k: _spalte(z, k) for k in KEY}
            break
    if kopf_idx is None:
        raise ValueError("Keine Kopfzeile mit Datum- und Betrag-/Gutschrift-Spalte gefunden. "
                         "Erwartet werden Spalten wie «Datum», «Betrag» oder «Gutschrift», "
                         "optional «Referenz», «Mitteilung», «Auftraggeber».")

    def _dec(s):
        s = (s or '').strip().replace("'", '').replace(' ', '').replace(' ', '')
        s = s.replace('CHF', '').replace('chf', '')
        if not s:
            return None
        if ',' in s and '.' not in s:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
        try:
            return Decimal(s)
        except Exception:
            return None

    def _datum(s):
        from datetime import datetime as _dt
        s = (s or '').strip()[:10]
        for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%d.%m.%y'):
            try:
                return _dt.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    eintraege = []
    for z in zeilen[kopf_idx + 1:]:
        if not any((c or '').strip() for c in z):
            continue

        def wert(k):
            i = sp.get(k)
            return z[i] if i is not None and i < len(z) else ''

        # Gutschrift bestimmen: eigene Spalte hat Vorrang, sonst positiver Betrag
        betrag = _dec(wert('gut')) if sp.get('gut') is not None else None
        if betrag is None:
            b = _dec(wert('betrag'))
            if b is None or b <= 0:
                continue   # Belastung/Leerzeile → kein Zahlungseingang
            if sp.get('last') is not None and _dec(wert('last')):
                continue   # Zeile ist als Belastung markiert
            betrag = b
        if betrag is None or betrag <= 0:
            continue

        info = (wert('text') or '').strip()
        referenz = (wert('ref') or '').strip().replace(' ', '')
        if not referenz:
            # QRR (27-stellig) auch aus dem Buchungstext fischen
            m27 = _re.search(r'\b(\d[\d ]{25,40}\d)\b', info)
            if m27:
                kandidat = m27.group(1).replace(' ', '')
                if len(kandidat) == 27:
                    referenz = kandidat
        eintraege.append({
            'betrag': betrag, 'referenz': referenz, 'datum': _datum(wert('datum')),
            'info': info, 'acct_ref': '', 'dbtr_name': (wert('name') or '').strip(),
        })
    return eintraege


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_camt_import(request):
    """Importiert einen Bank-Kontoauszug — camt.053 (ISO 20022) ODER CSV-Export
    der Bank. Gutschriften werden per QRR-Referenz den offenen Debitoren-
    rechnungen zugeordnet und als Zahlungseingang (Bank an Debitoren) verbucht;
    Unzuordenbares wird auf dem Durchlaufkonto 1190 geparkt."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.utils.qr_code import qrr_referenz
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_bankabgleich')

    datei = request.FILES.get('camt_datei')
    if not datei:
        messages.error(request, "Keine Datei ausgewählt.")
        return redirect('fw_bankabgleich')

    roh = datei.read()
    # Format erkennen: XML (camt.053) beginnt mit '<' — alles andere als Bank-CSV parsen.
    kopf_bytes = roh.lstrip(b'\xef\xbb\xbf \t\r\n')
    ist_xml = kopf_bytes.startswith(b'<')
    try:
        if ist_xml:
            # nur_gutschriften=False: Belastungen (Lieferantenzahlungen, Gebühren,
            # Zinsen, Daueraufträge) gehören dazu, sonst ist die Bank nicht
            # abstimmbar (Praxis-Audit).
            eintraege = _camt_parse(roh, nur_gutschriften=False)
            auszug_kopf = _camt_kopf(roh)
        else:
            eintraege = _bank_csv_parse(roh)
            auszug_kopf = {}
    except Exception as e:
        messages.error(request, f"Datei konnte nicht gelesen werden "
                                f"({'kein gültiges camt.053' if ist_xml else 'CSV-Format nicht erkannt'}): {e}")
        return redirect('fw_bankabgleich')

    quelle = 'camt.053' if ist_xml else 'Bank-CSV'
    if not eintraege:
        messages.warning(request, "Keine Bewegungen im Kontoauszug gefunden.")
        return redirect('fw_bankabgleich')

    # Zielkonto der Bank: wählbar, damit mehrere Bankkonten buchbar sind.
    # Vorher war «1020» im ganzen Import hart verdrahtet (Praxis-Audit).
    bank_nr = (request.POST.get('bank_konto') or '1020').strip()
    konto_bank_obj = Buchungskonto.objects.filter(nummer=bank_nr).first()
    if konto_bank_obj is None:
        bank_nr, konto_bank_obj = '1020', _park_konto('1020')

    # Kontoauszug mit Schlusssaldo festhalten — die Grundlage des Abstimmungsnachweises.
    from finance.models import Kontoauszug, Bankbewegung
    auszug = Kontoauszug.objects.create(
        konto=konto_bank_obj, iban=(auszug_kopf.get('iban') or '')[:34],
        von=auszug_kopf.get('von'), bis=auszug_kopf.get('bis'),
        eroeffnungssaldo=auszug_kopf.get('eroeffnung'),
        schlusssaldo=auszug_kopf.get('schluss'),
        dateiname=datei.name[:255], quelle=quelle, importiert_von=request.user)

    # Referenz-Index aller offenen/teilbezahlten Rechnungen aufbauen
    offene = list(DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
                  .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'))
    ref_index = {}
    for r in offene:
        schluessel = set()
        if r.qr_referenz:
            schluessel.add(r.qr_referenz.replace(' ', ''))
        if r.vertrag_id:
            raw, _ = qrr_referenz(r.vertrag_id, r.id)
            schluessel.add(raw)
        for s in schluessel:
            ref_index.setdefault(s, r)

    verbucht = 0
    zugeordnet_summe = Decimal('0.00')
    fuzzy = 0
    gelernt_treffer = 0     # über einen früher von Hand zugeordneten Absender
    geklaert = 0            # auf Durchlaufkonto 1190 geparkt (Mieter unbekannt)
    guthaben = 0            # Überzahlung auf 2030 (Mieter bekannt)
    duplikate = 0
    gesperrt = 0            # von der Periodensperre abgewiesen
    belastungen = 0         # Ausgänge — landen im Bank-Eingang zur Zuordnung
    bewegungen_neu = []     # persistierte Auszugszeilen
    komposit_lauf = {}      # Laufnummern für referenzlose Zahlungen
    heute = timezone.localdate()

    # Das Bankkonto steckt in bank_nr/konto_bank_obj — kein hart verdrahtetes 1020 mehr.
    konto_clearing, _ = Buchungskonto.objects.get_or_create(
        nummer="1190", defaults={'bezeichnung': 'Durchlaufkonto (ungeklärte Zahlungen)', 'typ': 'bilanz'})
    # W6: Überzahlung eines BEKANNTEN Mieters ist kein ungeklärter Posten, sondern
    # eine echte Verbindlichkeit → 2030 «Guthaben Mieter» statt Durchlaufkonto 1190.
    konto_guthaben = _park_konto("2030")

    # Fuzzy-Index: offener Betrag → Rechnungen (für referenzlose Gutschriften)
    def _norm(s):
        return ''.join(ch for ch in (s or '').lower() if ch.isalnum())

    def _name_tokens(s):
        """Wortweise normalisierte Tokens eines Namens (Reihenfolge erhalten)."""
        return [t for t in (_norm(w) for w in re.split(r'\s+', s or '')) if t]

    def _nachname_passt(nachname, dbtr):
        """Nachname passt zum Auftraggeber, wenn er als zusammenhängende
        Tokenfolge im Auftraggebernamen vorkommt.

        Nicht als reine Teilzeichenkette (`_norm(nachname) in _norm(dbtr)`) —
        ein kurzer Nachname («Ott») steckte sonst in einem fremden Namen
        («Scott») und die Zahlung würde dem falschen Mieter automatisch
        gutgeschrieben. Die Tokenfolge-Prüfung trägt mehrteilige Nachnamen
        («Von Gunten») weiterhin, verlangt aber Wortgrenzen."""
        ziel = _name_tokens(nachname)
        hay = _name_tokens(dbtr)
        if not ziel or not hay:
            return False
        n = len(ziel)
        return any(hay[i:i + n] == ziel for i in range(len(hay) - n + 1))

    def _verbuche(rechnung, betrag, e, via):
        vertrag = rechnung.vertrag
        with transaction.atomic():
            zahlung = Zahlungseingang.objects.create(
                vertrag=vertrag, betrag=betrag, datum_eingang=e['datum'] or heute,
                buchungs_monat=(rechnung.faellig_am or rechnung.datum or heute).replace(day=1),
                bemerkung=f"{quelle}-Import ({via}) {rechnung.titel}",
                bank_referenz=e.get('acct_ref', ''),
                liegenschaft=vertrag.einheit.liegenschaft if vertrag and vertrag.einheit_id else None,
                debitoren_rechnung=rechnung, erstellt_von=request.user, status='verbucht',
            )
            rechnung.status = 'bezahlt' if rechnung.offener_betrag <= 0 else 'teilbezahlt'
            rechnung.save()
            from finance.booking import buche
            buche(bank_nr, "1100", betrag, f"{quelle} {vertrag.mieter} - {rechnung.titel}",
                  datum=e['datum'] or heute,
                  liegenschaft=vertrag.einheit.liegenschaft if vertrag and vertrag.einheit_id else None,
                  zahlung=zahlung, user=request.user)
        # Auszugszeile als erledigt markieren und mit der Zahlung verknüpfen —
        # so ist im Bank-Eingang sichtbar, was noch offen ist.
        _bew = Bankbewegung.objects.filter(bank_referenz=e.get('acct_ref', ''),
                                           status='offen').first()
        if _bew is not None:
            _bew.status = 'verbucht'
            _bew.zahlung = zahlung
            _bew.liegenschaft = zahlung.liegenschaft
            _bew.save(update_fields=['status', 'zahlung', 'liegenschaft'])
        if rechnung.status == 'bezahlt':
            for k in [k for k, v in ref_index.items() if v is rechnung]:
                ref_index.pop(k, None)

    def _eintrag_verarbeiten(e):
        """Verarbeitet EINEN Kontoauszugs-Eintrag. Läuft in der Schleife unten in
        einem try/except für die Periodensperre — sonst reisst eine gesperrte
        Periode den ganzen Import mit HTTP 500 ab: die bis dahin verbuchten Zeilen
        blieben gespeichert, der Rest ginge kommentarlos verloren (Audit)."""
        nonlocal verbucht, geklaert, guthaben, duplikate, fuzzy, zugeordnet_summe, belastungen
        nonlocal gelernt_treffer

        # 0) Duplikatschutz über Bank-Transaktionsreferenz. Fehlt eine eindeutige
        #    Referenz (kein AcctSvcrRef/TxId, EndToEndId=NOTPROVIDED), wird ein
        #    zusammengesetzter Schlüssel aus Datum|Betrag|Auftraggeber|QRR gebildet —
        #    so wird der erneute Import derselben Datei nicht doppelt verbucht, ohne
        #    verschiedene ref-lose Zahlungen fälschlich zu verschmelzen.
        aref = e.get('acct_ref', '')
        if not aref:
            _dat = (e.get('datum') or heute)
            aref = f"camt:{_dat:%Y-%m-%d}|{e.get('betrag','')}|{_norm(e.get('dbtr_name',''))}|{e.get('referenz','')}"
            # Laufnummer je Schlüssel: zwei ECHTE Zahlungen am selben Tag über
            # denselben Betrag (z.B. zwei Mieter mit gleicher Miete, beide ohne
            # Auftraggebername) ergaben sonst denselben Schlüssel — die zweite
            # wurde als «Duplikat» verworfen und das Geld verschwand (Audit).
            # Beim erneuten Import derselben Datei entstehen dieselben Nummern,
            # die Idempotenz bleibt also erhalten.
            # Auf Feldlänge kürzen (bank_referenz = 140 Zeichen), bevor die
            # Laufnummer angehängt wird — ein langer Auftraggebername hätte den
            # Import sonst mit einem DataError abgebrochen. Die Kürzung ist
            # deterministisch, der Wiederholungs-Import erzeugt denselben Wert.
            aref = aref[:130]
            komposit_lauf[aref] = komposit_lauf.get(aref, 0) + 1
            if komposit_lauf[aref] > 1:
                aref = f"{aref}#{komposit_lauf[aref]}"
        aref = aref[:140]
        e['acct_ref'] = aref
        # Stornierte Zahlungen NICHT als Duplikat werten — sonst liesse sich eine
        # rückgängig gemachte Import-Datei nie wieder importieren (jede Zeile fiele
        # als «Duplikat» durch). Nur aktive (verbuchte) Zahlungen/Bewegungen zählen.
        if (Zahlungseingang.objects.filter(bank_referenz=aref).exclude(status='storniert').exists()
                or Bankbewegung.objects.filter(bank_referenz=aref).exists()):
            duplikate += 1
            return

        betrag_e = e['betrag']

        # Jede Zeile des Auszugs wird festgehalten — auch die, die sich nicht
        # automatisch zuordnen lässt. Erst dadurch ist das Bankkonto abstimmbar
        # und der Auszug im Programm nachvollziehbar (Praxis-Audit).
        bew = Bankbewegung.objects.create(
            auszug=auszug, konto=konto_bank_obj,
            datum=e.get('datum') or heute, valuta=e.get('valuta'),
            betrag=betrag_e,
            text=(e.get('info') or '')[:255],
            gegenpartei=(e.get('dbtr_name') or '')[:160],
            referenz=(e.get('referenz') or '')[:40],
            bank_referenz=aref, status='offen')
        bewegungen_neu.append(bew)

        def _bew_erledigt(zahlung_obj=None, notiz=''):
            """Auszugszeile abhaken. Auch eine auf 1190 geparkte Gutschrift IST
            gebucht — bliebe sie «offen», zeigte der Saldoabgleich eine Differenz,
            die es gar nicht gibt."""
            bew.status = 'verbucht'
            if zahlung_obj is not None:
                bew.zahlung = zahlung_obj
                bew.liegenschaft = zahlung_obj.liegenschaft
            if notiz:
                bew.bemerkung = notiz[:255]
            bew.save(update_fields=['status', 'zahlung', 'liegenschaft', 'bemerkung'])

        # Belastungen wandern in den Bank-Eingang zur Zuordnung. Automatisch
        # buchen wäre geraten — das Gegenkonto (Lieferant, Gebühr, Zins, Miete
        # des Eigentümers) steht nicht im Auszug.
        if betrag_e < 0:
            belastungen += 1
            return

        rechnung = ref_index.get(e['referenz']) if e['referenz'] else None

        # 1) Exakte QRR-Referenz
        if rechnung and rechnung.vertrag_id and rechnung.offener_betrag > 0:
            offen = rechnung.offener_betrag
            betrag = min(max(betrag_e, Decimal('0.01')), offen)
            _verbuche(rechnung, betrag, e, 'Referenz')
            verbucht += 1; zugeordnet_summe += betrag
            # Überzahlung: den vollen Bankeingang abbilden — der Überschuss wird als
            # Mieterguthaben auf 2030 gebucht. Ohne das läge auf 1020 weniger als auf
            # dem realen Kontoauszug → Bankabgleich geht nie auf und die Überzahlung
            # verschwindet. 2030 statt 1190 (Audit W6): der Mieter ist bekannt, das
            # ist eine echte Verbindlichkeit und kein ungeklärter Durchlaufposten.
            ueberschuss = betrag_e - offen
            if ueberschuss > 0:
                with transaction.atomic():
                    z_ueber = Zahlungseingang.objects.create(
                        vertrag=rechnung.vertrag, betrag=ueberschuss,
                        datum_eingang=e['datum'] or heute,
                        buchungs_monat=(e['datum'] or heute).replace(day=1),
                        bemerkung=f"{quelle} Überzahlung {rechnung.titel} (Guthaben Mieter)"[:255],
                        bank_referenz=f"{aref}:ueber"[:140], konto=konto_guthaben,
                        liegenschaft=rechnung.vertrag.einheit.liegenschaft if rechnung.vertrag.einheit_id else None,
                        erstellt_von=request.user, status='verbucht')
                    from finance.booking import buche
                    buche(bank_nr, "2030", ueberschuss,
                          f"{quelle} Überzahlung {rechnung.vertrag.mieter} - {rechnung.titel}",
                          datum=e['datum'] or heute,
                          liegenschaft=rechnung.vertrag.einheit.liegenschaft if rechnung.vertrag.einheit_id else None,
                          zahlung=z_ueber, user=request.user)
                guthaben += 1; zugeordnet_summe += ueberschuss
            return

        # 2) Fuzzy: exakter Betrag + Name des Auftraggebers passt eindeutig
        _dbtr_raw = e.get('dbtr_name', '')
        if not _name_tokens(_dbtr_raw):
            _dbtr_raw = e.get('info', '')
        kandidaten = [r for r in offene if r.vertrag_id and r.offener_betrag == betrag_e
                      and r.vertrag.mieter
                      and _nachname_passt(r.vertrag.mieter.nachname, _dbtr_raw)]
        if len(kandidaten) == 1:
            r = kandidaten[0]
            _verbuche(r, betrag_e, e, 'Name+Betrag')
            verbucht += 1; fuzzy += 1; zugeordnet_summe += betrag_e
            return

        # 2b) Gelernter Absender: Wurde dieser Zahler schon einmal von Hand
        # zugeordnet, gilt die Entscheidung weiter. Konservativ — nur wenn der
        # Vertrag GENAU EINE offene Rechnung hat und der Betrag hineinpasst.
        # Bei mehreren offenen Rechnungen wäre die Wahl geraten, und geratene
        # Zahlungszuordnungen sind teurer als eine Minute Handarbeit.
        from core.services import zahler as _zahler
        absender, _rest_txt, _ = _zahler.aus_bewegung(e.get('dbtr_name'), e.get('info'))
        gelernter_vertrag = _zahler.finde_vertrag(absender) if absender else None
        if gelernter_vertrag is not None:
            kand = [r for r in offene if r.vertrag_id == gelernter_vertrag.id
                    and r.offener_betrag > 0]
            if len(kand) == 1 and betrag_e <= kand[0].offener_betrag:
                _verbuche(kand[0], betrag_e, e, f'gelernter Absender {absender}')
                _zahler.zaehle_treffer(absender)
                verbucht += 1; gelernt_treffer += 1; zugeordnet_summe += betrag_e
                return

        # 3) Nicht zuordenbar → parken (nichts geht verloren).
        # Trägt die Zahlung eine QRR, deren Rechnung bereits bezahlt ist, ist der
        # Zahler bekannt: das ist eine Doppelzahlung des Mieters und gehört als
        # Guthaben auf 2030, nicht als «ungeklärt» auf 1190 — dort wäre sie
        # optisch ein Fremdeingang und der Mieter bekäme sein Geld nie zurück.
        bekannte = ref_index.get(e['referenz']) if e['referenz'] else None
        if bekannte is None and e['referenz']:
            bekannte = (DebitorenRechnung.objects
                        .filter(qr_referenz=e['referenz'], vertrag__isnull=False)
                        .select_related('vertrag__einheit__liegenschaft').first())
        with transaction.atomic():
            from finance.booking import buche
            if bekannte is not None and bekannte.vertrag_id:
                v_b = bekannte.vertrag
                lg_b = v_b.einheit.liegenschaft if v_b.einheit_id else None
                zahlung = Zahlungseingang.objects.create(
                    vertrag=v_b, betrag=betrag_e, datum_eingang=e['datum'] or heute,
                    buchungs_monat=(e['datum'] or heute).replace(day=1),
                    bemerkung=f"{quelle} Doppelzahlung {bekannte.titel} (Guthaben Mieter)"[:255],
                    bank_referenz=aref, konto=konto_guthaben, liegenschaft=lg_b,
                    erstellt_von=request.user, status='verbucht')
                buche(bank_nr, "2030", betrag_e,
                      f"{quelle} Doppelzahlung {v_b.mieter} - {bekannte.titel}",
                      datum=e['datum'] or heute, liegenschaft=lg_b,
                      zahlung=zahlung, user=request.user)
                _bew_erledigt(zahlung, f"Doppelzahlung → 2030 ({bekannte.titel})")
                guthaben += 1
                return
            zahlung = Zahlungseingang.objects.create(
                betrag=betrag_e, datum_eingang=e['datum'] or heute,
                buchungs_monat=(e['datum'] or heute).replace(day=1),
                bemerkung=f"{quelle} UNGEKLÄRT: {e.get('dbtr_name','') or e.get('info','') or e.get('referenz','')}"[:255],
                bank_referenz=aref, konto=konto_clearing,
                erstellt_von=request.user, status='verbucht')
            buche(bank_nr, "1190", betrag_e,
                  f"{quelle} ungeklärt: {e.get('dbtr_name','') or e.get('referenz','')}",
                  datum=e['datum'] or heute, zahlung=zahlung, user=request.user)
        _bew_erledigt(zahlung, "ungeklärt → Durchlaufkonto 1190")
        geklaert += 1

    for e in eintraege:
        try:
            _eintrag_verarbeiten(e)
        except PermissionError:
            gesperrt += 1
            # Die Bankbewegung wird in Autocommit angelegt, BEVOR die Buchung läuft;
            # scheitert die Buchung an der Periodensperre, rollt nur das atomic der
            # Buchung/Zahlung zurück — die Bewegung bliebe als Waise stehen. Beim
            # Re-Import (nach Entsperren) gälte die Auszugszeile dann als Duplikat und
            # die Zahlung würde NIE gebucht (QS-Befund). Deshalb die noch nicht mit
            # einer Zahlung verknüpfte Bewegung dieser Zeile entfernen, damit der
            # Re-Import sie neu anlegt und bucht.
            _aref = e.get('acct_ref')
            if _aref:
                Bankbewegung.objects.filter(bank_referenz=_aref, zahlung__isnull=True,
                                            status='offen').delete()

    log_aktion(request, f"{quelle}-Import", datei.name,
               f"{verbucht} verbucht (davon {fuzzy} fuzzy, {gelernt_treffer} gelernter "
               f"Absender), CHF {zugeordnet_summe}, "
               f"{geklaert} auf 1190, {guthaben} Guthaben auf 2030, {duplikate} Duplikate, "
               f"{gesperrt} Periodensperre")
    if verbucht or geklaert or guthaben or belastungen:
        teile = [f"{verbucht} Zahlung(en) zugeordnet (CHF {zugeordnet_summe})"]
        if fuzzy:
            teile.append(f"davon {fuzzy} über Name/Betrag")
        if gelernt_treffer:
            teile.append(f"{gelernt_treffer} über einen früher zugeordneten Absender")
        if guthaben:
            teile.append(f"{guthaben} Überzahlung(en) als Mieterguthaben (2030)")
        if geklaert:
            teile.append(f"{geklaert} ungeklärt auf Durchlaufkonto 1190 geparkt")
        if duplikate:
            teile.append(f"{duplikate} Duplikat(e) übersprungen")
        messages.success(request, f"✅ {quelle}-Import: " + ", ".join(teile) + ".")
    else:
        messages.warning(request,
            f"Keine neuen Gutschriften verbucht ({duplikate} Duplikat(e) übersprungen).")
    if belastungen:
        messages.info(request, f"ℹ️ {belastungen} Belastung(en) übernommen — sie liegen im "
                               f"Bank-Eingang zur Zuordnung. Das Gegenkonto (Lieferant, "
                               f"Gebühr, Zins) steht nicht im Auszug und wird bewusst nicht geraten.")
    # Saldoabgleich: der Nachweis, dass Buchhaltung und Bankkonto übereinstimmen.
    if auszug.schlusssaldo is not None:
        from django.db.models import Sum as _SumB
        _bq = Buchung.objects.filter(ist_storno=False, storniert_am__isnull=True)
        if auszug.bis:
            _bq = _bq.filter(datum__lte=auszug.bis)
        _s = _bq.filter(soll_konto=konto_bank_obj).aggregate(t=_SumB('betrag'))['t'] or Decimal('0.00')
        _h = _bq.filter(haben_konto=konto_bank_obj).aggregate(t=_SumB('betrag'))['t'] or Decimal('0.00')
        buch_saldo = (_s - _h).quantize(Decimal('0.01'))
        diff = (auszug.schlusssaldo - buch_saldo).quantize(Decimal('0.01'))
        if diff == 0:
            messages.success(request, f"✅ Saldoabgleich {bank_nr}: Buchhaltung und Auszug "
                                      f"stimmen überein (CHF {buch_saldo}).")
        else:
            messages.warning(request, f"⚠️ Saldoabgleich {bank_nr}: Auszug CHF "
                                      f"{auszug.schlusssaldo}, Buchhaltung CHF {buch_saldo} — "
                                      f"Differenz CHF {diff}. Offene Bewegungen im Bank-Eingang "
                                      f"zuordnen, dann stimmt es.")
    if gesperrt:
        # Nie stillschweigend überspringen — der Import gälte sonst als vollständig.
        messages.error(request, f"⚠️ {gesperrt} Zahlung(en) konnten nicht verbucht werden: "
                                f"die Buchungsperiode ist gesperrt. Periode öffnen und die "
                                f"Datei erneut importieren — bereits verbuchte Zahlungen "
                                f"werden dabei als Duplikat übersprungen.")

    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'
    return redirect(ziel)


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_kontoauszug_rueckgaengig(request, pk):
    """Macht einen Bank-Import (camt.053 / CSV) rückgängig.

    Storniert REVISIONSSICHER alle aus diesem Auszug erzeugten Zahlungen
    (Gegenbuchung, Rechnungsstatus rollt auf offen/teilbezahlt zurück) und löscht
    danach den Kontoauszug samt Auszugszeilen. Bereits stornierte Zahlungen werden
    übersprungen. Läuft in EINER Transaktion — scheitert eine Gegenbuchung (z.B.
    gesperrte Periode), bleibt der Import unverändert."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.db.models import Q as _Q
    from finance.models import Kontoauszug, Zahlungseingang, Buchung
    from finance.services import erstelle_storno_buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_bankabgleich')

    auszug = get_object_or_404(Kontoauszug.objects.prefetch_related('bewegungen'), id=pk)
    # Alle aus diesem Auszug gebuchten Zahlungen: über die Bank-Referenz der
    # Auszugszeilen — inkl. der Überzahlungs-Zahlung (Suffix ':ueber').
    arefs = {b.bank_referenz for b in auszug.bewegungen.all() if b.bank_referenz}
    zahlungen = []
    if arefs:
        zahlungen = list(Zahlungseingang.objects.filter(
            _Q(bank_referenz__in=arefs)
            | _Q(bank_referenz__in=[f"{a}:ueber" for a in arefs])))

    dateiname = auszug.dateiname or f"Auszug #{auszug.id}"
    storniert = 0
    uebersprungen = 0
    try:
        with transaction.atomic():
            for z in zahlungen:
                if z.status == 'storniert':
                    uebersprungen += 1
                    continue
                for b in Buchung.objects.filter(zahlungseingang=z, ist_storno=False,
                                                storniert_am__isnull=True):
                    erstelle_storno_buchung(b, benutzer=request.user)
                z.status = 'storniert'
                z.save(update_fields=['status'])
                # Rechnungsstatus zurückrollen (Gegenstück zu _verbuche()).
                if z.debitoren_rechnung_id:
                    rech = z.debitoren_rechnung
                    rech.status = 'offen' if rech.offener_betrag >= rech.betrag else 'teilbezahlt'
                    rech.save(update_fields=['status'])
                storniert += 1
            # Auszug + Auszugszeilen (Rohdaten, keine Buchungen) entfernen.
            auszug.delete()
    except PermissionError as exc:
        messages.error(request, f"❌ Rückgängig nicht möglich — die Buchungsperiode ist "
                                f"gesperrt: {exc}. Periode öffnen und erneut versuchen.")
        return redirect('fw_bankabgleich')
    except Exception as exc:
        messages.error(request, f"❌ Import konnte nicht rückgängig gemacht werden: {exc}")
        return redirect('fw_bankabgleich')

    log_aktion(request, "Bank-Import rückgängig gemacht", dateiname,
               f"{storniert} Zahlung(en) storniert" + (f", {uebersprungen} bereits storniert"
                                                       if uebersprungen else ""))
    messages.success(request, f"✅ Import '{dateiname}' rückgängig gemacht — {storniert} "
                              f"Zahlung(en) revisionssicher storniert, Auszug entfernt."
                              + (f" {uebersprungen} bereits zuvor storniert." if uebersprungen else ""))
    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'
    return redirect(ziel)
