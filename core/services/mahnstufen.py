"""Konfigurierbare Mahnstufen pro Mandant (feste 3 Stufen: aktiv / ab-Tage /
Gebuehr / Kuendigungsandrohung).

EINE Quelle der Wahrheit — vorher dreifach hartcodiert (fw._mahnstufe,
fw.MAHN_STUFEN, automation.MAHN_STUFEN_TAGE + MAHN_GEBUEHR). Die Konfiguration
liegt pro Mandant (crm.Mandant.mahn_konfig, JSON). Fehlt sie, gilt der Standard
(14/30/60 Tage, Gebuehr 0/20/40, Kuendigungsandrohung ab Stufe 3) — damit ist das
bisherige Verhalten Default und aendert sich fuer bestehende Mandanten nicht.
"""
from decimal import Decimal

# Standard = bisheriges Verhalten. gebuehr als String, damit JSON-serialisierbar.
MAHN_KONFIG_DEFAULT = [
    {'stufe': 1, 'aktiv': True, 'ab_tage': 14, 'gebuehr': '0.00',  'kuendigung': False},
    {'stufe': 2, 'aktiv': True, 'ab_tage': 30, 'gebuehr': '20.00', 'kuendigung': False},
    {'stufe': 3, 'aktiv': True, 'ab_tage': 60, 'gebuehr': '40.00', 'kuendigung': True},
]

_STD_TAGE   = {1: 14, 2: 30, 3: 60}
_STD_GEBUEHR = {1: '0.00', 2: '20.00', 3: '40.00'}
_LABEL = {1: '1. Mahnung', 2: '2. Mahnung', 3: '3. Mahnung'}
_CLS   = {1: 'bg-amber-100 text-amber-700', 2: 'bg-rose-50 text-rose-600', 3: 'bg-rose-100 text-rose-700'}
_DOT   = {1: 'bg-amber-500', 2: 'bg-rose-400', 3: 'bg-rose-500'}
_UNTER_STD = {1: 'Erste Zahlungserinnerung', 2: 'Zweite schriftliche Erinnerung',
              3: 'Dritte Mahnung'}
_UNTER_KUEND = 'Kündigungsandrohung (Art. 257d OR)'


def _normalize(roh):
    """Roh-Konfig (DB-JSON oder Default) -> angereicherte, aktive Stufenliste,
    absteigend nach ab_tage (hoechste Stufe zuerst) — passend zu MAHN_STUFEN."""
    by_stufe = {}
    for c in (roh or MAHN_KONFIG_DEFAULT):
        try:
            by_stufe[int(c['stufe'])] = c
        except (KeyError, TypeError, ValueError):
            continue
    stufen = []
    for s in (1, 2, 3):
        c = by_stufe.get(s, {})
        if not c.get('aktiv', True):
            continue
        kuend = bool(c.get('kuendigung', s == 3))
        try:
            ab = int(c.get('ab_tage', _STD_TAGE[s]))
        except (TypeError, ValueError):
            ab = _STD_TAGE[s]
        ab = max(0, ab)
        try:
            geb = Decimal(str(c.get('gebuehr', _STD_GEBUEHR[s])))
        except Exception:
            geb = Decimal(_STD_GEBUEHR[s])
        stufen.append({
            'stufe': s, 'ab_tage': ab, 'gebuehr': geb, 'kuendigung': kuend,
            'label': _LABEL[s], 'unter': _UNTER_KUEND if kuend else _UNTER_STD[s],
            'cls': _CLS[s], 'dot': _DOT[s],
        })
    stufen.sort(key=lambda x: x['ab_tage'], reverse=True)
    return stufen


def mahnstufen_config(mandant):
    """Effektive, aktive Mahnstufen eines Mandanten (oder Standard bei None/leer)."""
    roh = getattr(mandant, 'mahn_konfig', None) if mandant is not None else None
    return _normalize(roh)


def stufe_fuer_tage(tage, mandant=None):
    """Hoechste zutreffende Stufe (dict) fuer 'tage' ueberfaellig — oder None."""
    for s in mahnstufen_config(mandant):
        if tage >= s['ab_tage']:
            return s
    return None


def roh_konfig(mandant):
    """Alle 3 Stufen (auch inaktive) zum BEARBEITEN — DB-Werte über den Default
    gelegt. Anders als mahnstufen_config(): filtert nicht und sortiert nach Stufe."""
    by = {}
    roh = getattr(mandant, 'mahn_konfig', None) if mandant is not None else None
    for c in (roh or []):
        try:
            by[int(c['stufe'])] = c
        except (KeyError, TypeError, ValueError):
            continue
    out = []
    for s in (1, 2, 3):
        d = dict(next(x for x in MAHN_KONFIG_DEFAULT if x['stufe'] == s))
        c = by.get(s)
        if c:
            try:
                d['aktiv'] = bool(c.get('aktiv', True))
                d['ab_tage'] = max(0, int(c.get('ab_tage', d['ab_tage'])))
                d['gebuehr'] = str(Decimal(str(c.get('gebuehr', d['gebuehr']))))
                d['kuendigung'] = bool(c.get('kuendigung', d['kuendigung']))
            except Exception:
                pass
        out.append(d)
    return out


def mandant_von_rechnung(r):
    """Mandant (Eigentuemer) einer DebitorenRechnung ueber ihre Liegenschaft."""
    lg = getattr(r, 'liegenschaft', None)
    if lg is None and getattr(r, 'vertrag_id', None) and getattr(r.vertrag, 'einheit_id', None):
        lg = r.vertrag.einheit.liegenschaft
    return getattr(lg, 'mandant', None) if lg is not None else None
