"""LIK-Hilfsfunktionen: einheitliche Beschriftung mit Basis + Stand-Monat.

Der Landesindex der Konsumentenpreise (LIK) wird auf einer Basis geführt
(aktuell «Dezember 2020 = 100»). Für die Teuerungsberechnung bei
Mietzinsanpassungen müssen der alte und der neue LIK-Wert auf DERSELBEN Basis
stehen, und auf dem amtlichen Formular müssen Basis + Stand-Monat ausgewiesen
werden (Art. 269a lit. b OR / VMWG)."""

_MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
           "August", "September", "Oktober", "November", "Dezember"]

# Aktive LIK-Serie (Name = Basis) und die offiziellen Monatswerte des BFS.
LIK_BASIS = "Dezember 2020"

# Landesindex der Konsumentenpreise, Basis «Dezember 2020 = 100» (Quelle: BFS).
# None = Monat noch nicht veröffentlicht. Bei neuer BFS-Publikation hier ergänzen.
LIK_DEZ2020 = {
    2020: [None, None, None, None, None, None, None, None, None, None, None, 100.0],
    2021: [100.1, 100.2, 100.6, 100.8, 101.0, 101.1, 101.0, 101.3, 101.3, 101.6, 101.6, 101.5],
    2022: [101.7, 102.4, 103.0, 103.3, 104.0, 104.5, 104.5, 104.8, 104.6, 104.6, 104.6, 104.4],
    2023: [105.0, 105.8, 106.0, 106.0, 106.3, 106.3, 106.2, 106.4, 106.3, 106.4, 106.2, 106.2],
    2024: [106.4, 107.1, 107.1, 107.4, 107.7, 107.7, 107.5, 107.5, 107.2, 107.1, 106.9, 106.9],
    2025: [106.8, 107.4, 107.5, 107.5, 107.6, 107.8, 107.8, 107.7, 107.5, 107.2, 107.0, 106.9],
    2026: [106.9, 107.6, 107.8, 108.1, 108.3, 108.3],
}


def lik_punkte_fuer(jahr, monat):
    """LIK-Punkte (Decimal) eines Monats aus der Tabelle, oder None."""
    from decimal import Decimal
    reihe = LIK_DEZ2020.get(jahr)
    if not reihe or monat < 1 or monat > len(reihe):
        return None
    val = reihe[monat - 1]
    return Decimal(str(val)) if val is not None else None


def _tabelle_wert():
    """Neuester Wert aus der eingebauten BFS-Tabelle (Offline-Netz)."""
    import datetime
    from decimal import Decimal
    best = None
    for jahr in sorted(LIK_DEZ2020):
        reihe = LIK_DEZ2020[jahr]
        for i, val in enumerate(reihe):
            if val is not None:
                best = (jahr, i + 1, val)
    if best is None:
        return None, None
    j, mo, val = best
    return datetime.date(j, mo, 1), Decimal(str(val))


def _fetch_live_lik(timeout=8):
    """Best-effort Live-Abruf des neuesten LIK (Basis Dez. 2020) inkl. Monat
    von der HEV-Tabelle. Gibt (date, Decimal) oder None. Fängt JEDEN Fehler ab
    (kein Internet, Layout-Änderung …) → dann greift die Tabelle."""
    import re
    import datetime
    from decimal import Decimal, InvalidOperation
    try:
        import requests
    except Exception:
        return None
    url = "https://www.hev-schweiz.ch/vermieten/statistiken/landesindex-der-konsumentenpreise"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
               'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        html = requests.get(url, headers=headers, timeout=timeout).text
    except Exception:
        return None
    try:
        pos = html.find("2020 = 100")
        if pos < 0:
            return None
        snip = html[pos:pos + 8000]
        heute = datetime.date.today()
        for yr in (heute.year, heute.year - 1):
            row = re.search(rf">\s*{yr}\s*<.*?(?=>\s*{yr - 1}\s*<|</table>)", snip, re.S)
            if not row:
                continue
            vals = re.findall(r"1\d{2}[.,]\d", row.group(0))
            if len(vals) >= 13:      # 12 Monate + Jahres-Ø → Ø abschneiden
                vals = vals[:12]
            monat = len(vals)
            if not (1 <= monat <= 12):
                continue
            if yr == heute.year and monat > heute.month:
                monat = heute.month
                vals = vals[:monat]
            if not vals:
                continue
            try:
                wert = Decimal(vals[monat - 1].replace(',', '.'))
            except (InvalidOperation, ValueError):
                continue
            if Decimal('100') <= wert <= Decimal('140'):
                return datetime.date(yr, monat, 1), wert
    except Exception:
        return None
    return None


def _live_lik_cached():
    """Live-Wert mit 24-h-Cache (schont die Quelle, hält es aktuell)."""
    try:
        from django.core.cache import cache
    except Exception:
        return _fetch_live_lik()
    key = 'lik_live_dez2020_v1'
    cached = cache.get(key)
    if cached is not None:
        return cached or None      # False-Sentinel = letzter Versuch fehlgeschlagen
    got = _fetch_live_lik()
    cache.set(key, got or False, 60 * 60 * 24)
    return got


def aktueller_lik_wert(live=True):
    """Neuester LIK-Wert (stand_date, punkte, basis) — vollautomatisch.

    Priorität: Live-Abruf (BFS/HEV, 24-h-Cache) → eingebaute BFS-Tabelle.
    Der Live-Wert gewinnt nur, wenn er mindestens so aktuell ist wie die
    Tabelle (verhindert Rückschritte durch fehlerhaftes Parsing).
    """
    t_stand, t_pkt = _tabelle_wert()
    if live:
        got = _live_lik_cached()
        if got and got[0] and (t_stand is None or got[0] >= t_stand):
            return got[0], got[1], LIK_BASIS
    return t_stand, t_pkt, LIK_BASIS


def stand_label(stand):
    """DateField -> 'August 2024' (oder '' wenn None)."""
    if not stand:
        return ""
    try:
        return f"{_MONATE[stand.month - 1]} {stand.year}"
    except Exception:
        return ""


def lik_bezeichnung(punkte, basis="Dezember 2020", stand=None):
    """'107,2 Punkte · Basis Dezember 2020 · Stand August 2024'."""
    if punkte is None:
        return "—"
    try:
        p = f"{float(punkte):.1f}".replace('.', ',')
    except Exception:
        p = str(punkte)
    teile = [f"{p} Punkte"]
    if basis:
        teile.append(f"Basis {basis}")
    s = stand_label(stand)
    if s:
        teile.append(f"Stand {s}")
    return " · ".join(teile)


def vertrag_lik_context(vertrag, verwaltung=None):
    """Einheitliche LIK-Angaben eines Vertrags für alle Ansichten/PDFs.

    Gibt {lik_basis, lik_stand, lik_stand_label, lik_pkt, lik_voll} zurück.
    - Basis: `Verwaltung.lik_basis` (Default «Dezember 2020»)
    - Stand: `Vertrag.basis_lik_stand`, sonst `Verwaltung.aktueller_lik_stand`
    - Punkte: `Vertrag.basis_lik_punkte` (Schweizer Format mit Komma)
    """
    basis = (getattr(verwaltung, 'lik_basis', None) or "Dezember 2020")
    stand = getattr(vertrag, 'basis_lik_stand', None) or getattr(verwaltung, 'aktueller_lik_stand', None)
    punkte = getattr(vertrag, 'basis_lik_punkte', None)
    try:
        pkt = f"{float(punkte):.1f}".replace('.', ',') if punkte is not None else "—"
    except Exception:
        pkt = str(punkte)
    return {
        'lik_basis': basis,
        'lik_stand': stand,
        'lik_stand_label': stand_label(stand),
        'lik_pkt': pkt,
        'lik_voll': lik_bezeichnung(punkte, basis=basis, stand=stand),
    }
