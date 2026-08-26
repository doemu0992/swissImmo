# core/views/fw/bankkonten.py
#
# Bankkonten mit QR-IBAN-Erkennung und Mietertrag je Konto. Etappe 1, siehe
# docs/ETAPPE-1-ZERLEGEN.md.
#
# QR-IBAN heisst hier: der Bereich 30000-31999 in Stellen 5-9. Das steht im
# Skill schweizer-fachlogik und wird von diesem Umzug nicht beruehrt.

from decimal import Decimal

from django.db.models import Q, Sum
from django.shortcuts import render

from core.auth import rolle_erforderlich, TEAM_ROLLEN
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag

from ._basis import _global_filter
from core.tenancy import aktuelle_organisation


# ============================================================
# ETAPPE D: BANKKONTEN (QR-IBAN-Erkennung + Mietertrag je Konto)
# ============================================================

def _iban_clean(iban):
    return (iban or '').replace(' ', '').upper()


def _iban_format(iban):
    """Gruppiert die IBAN in 4er-Blöcke (CH93 0076 2011 6238 5295 7)."""
    s = _iban_clean(iban)
    return ' '.join(s[i:i + 4] for i in range(0, len(s), 4)) if s else ''


def _ist_qr_iban(iban):
    """QR-IBAN: Institut-ID (Stellen 5–9) im Bereich 30000–31999 (Schweizer QR-IID)."""
    s = _iban_clean(iban)
    if len(s) < 9 or not s.startswith(('CH', 'LI')):
        return False
    try:
        iid = int(s[4:9])
    except ValueError:
        return False
    return 30000 <= iid <= 31999


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_bankkonten(request):
    from crm.models import Organisation, Eigentuemer
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    liegenschaften = Liegenschaft.objects.all().order_by('strasse')
    if aktive_lg:
        liegenschaften = liegenschaften.filter(id=aktive_lg.id)

    konten = []
    qr_count = 0
    # 1) Liegenschafts-Mietkonten (das Konto, auf das die Mieten laufen)
    for lg in liegenschaften:
        if not _iban_clean(lg.iban):
            continue
        aktive = Mietvertrag.objects.filter(einheit__liegenschaft=lg, status='aktiv')
        soll = aktive.aggregate(s=Sum('netto_mietzins'), n=Sum('nebenkosten'))
        mietertrag = (soll['s'] or Decimal('0')) + (soll['n'] or Decimal('0'))
        is_qr = _ist_qr_iban(lg.iban)
        qr_count += 1 if is_qr else 0
        konten.append({
            'typ': 'Mietkonto', 'typ_icon': 'liegenschaft', 'typ_cls': 'fw-markenflaeche fw-marke',
            'inhaber': lg.strasse, 'kontext': f"{lg.plz} {lg.ort}",
            'bank': lg.bank_name, 'iban': _iban_format(lg.iban),
            'ist_qr': is_qr, 'mietertrag': mietertrag,
            'lg_id': lg.id,
        })

    # 2) Verwaltungs- und Eigentümer-Konten (nur ohne aktiven LG-Filter)
    if not aktive_lg:
        vw = aktuelle_organisation()
        if vw and _iban_clean(vw.iban):
            is_qr = _ist_qr_iban(vw.iban)
            qr_count += 1 if is_qr else 0
            konten.append({
                'typ': 'Verwaltung', 'typ_icon': 'dokument', 'typ_cls': 'fw-flaeche2 fw-mutet',
                'inhaber': vw.firma, 'kontext': 'Verwaltungskonto',
                'bank': getattr(vw, 'bank_name', ''), 'iban': _iban_format(vw.iban),
                'ist_qr': is_qr, 'mietertrag': None, 'lg_id': None,
            })
        for m in Eigentuemer.objects.all().order_by('firma_oder_name'):
            if not _iban_clean(m.iban):
                continue
            is_qr = _ist_qr_iban(m.iban)
            qr_count += 1 if is_qr else 0
            konten.append({
                'typ': 'Eigentümer', 'typ_icon': 'person', 'typ_cls': 'fw-gut-flaeche fw-gut',
                'inhaber': m.firma_oder_name, 'kontext': 'Eigentümer-Auszahlungskonto',
                'bank': m.bank_name, 'iban': _iban_format(m.iban),
                'ist_qr': is_qr, 'mietertrag': None, 'lg_id': None,
            })

    fehlend = liegenschaften.filter(Q(iban='') | Q(iban__isnull=True)).count()

    return render(request, 'fw/bankkonten.html', {
        **basis, 'nav': 'bankkonten', 'konten': konten,
        'anzahl': len(konten), 'qr_count': qr_count,
        'fehlend': fehlend,
    })
