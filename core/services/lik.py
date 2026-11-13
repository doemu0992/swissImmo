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
#
# QUELLEN (MIET-14):
#  * Januar 2021 – Juni 2026: Wert für Wert mit der HEV/BFS-Tabelle abgeglichen (Audit Mietrecht, 28.10.2026).
#  * Juli – September 2026 (108.2 / 108.6 / 108.5): aus dem Audit-Bericht Mietrecht, MIET-14 (HEV-Tabelle
#    «Landesindex der Konsumentenpreise», Quelle BFS, gelesen am 28.10.2026). In der Umgebung dieser
#    Änderung bestand kein Netzzugang zu bfs.admin.ch/hev-schweiz.ch: Vor dem Einsatz in Mietzinsanpassungen
#    gegen die BFS-Publikation prüfen (Fachpunkt im Bericht).
#  * Oktober 2026 erscheint Anfang November 2026 (BFS) und ist deshalb noch nicht eingetragen.
#
# BASISWECHSEL: Das BFS stellt den Index auf «Dezember 2025 = 100» um. Eine amtliche Verkettung
# (Umrechnungsfaktor) zwischen den Basen ist hier NICHT belegt und wird deshalb nicht erfunden: Die Tabelle
# bleibt auf Dezember 2020, solange das BFS diese Reihe weiterführt. Neue Verträge auf der Basis Dezember 2025
# brauchen den amtlichen Faktor (Fachpunkt).
LIK_DEZ2020 = {
    2020: [None, None, None, None, None, None, None, None, None, None, None, 100.0],
    2021: [100.1, 100.2, 100.6, 100.8, 101.0, 101.1, 101.0, 101.3, 101.3, 101.6, 101.6, 101.5],
    2022: [101.7, 102.4, 103.0, 103.3, 104.0, 104.5, 104.5, 104.8, 104.6, 104.6, 104.6, 104.4],
    2023: [105.0, 105.8, 106.0, 106.0, 106.3, 106.3, 106.2, 106.4, 106.3, 106.4, 106.2, 106.2],
    2024: [106.4, 107.1, 107.1, 107.4, 107.7, 107.7, 107.5, 107.5, 107.2, 107.1, 106.9, 106.9],
    2025: [106.8, 107.4, 107.5, 107.5, 107.6, 107.8, 107.8, 107.7, 107.5, 107.2, 107.0, 106.9],
    2026: [106.9, 107.6, 107.8, 108.1, 108.3, 108.3, 108.2, 108.6, 108.5],
}


def lik_reihen():
    """`{jahr: [12 Werte, None = nicht veröffentlicht]}`: die Reihe im Code, darüber die nachgetragenen Werte.

    Nachgetragen (`core.LikWert`) gewinnt gegen den Code. Eine Abfrage je Aufruf; wer viele Monate prüft, holt die
    Reihen einmal und schlägt dann darin nach. Ist die Datenbank nicht lesbar, gilt die Reihe im Code: Eine
    Indexrechnung darf daran nicht scheitern."""
    reihen = {jahr: list(reihe) + [None] * (12 - len(reihe)) for jahr, reihe in LIK_DEZ2020.items()}
    try:
        from core.models import LikWert
        for w in LikWert.objects.filter(basis=LIK_BASIS):
            reihen.setdefault(w.jahr, [None] * 12)[w.monat - 1] = float(w.punkte)
    except Exception:                                        # noqa: BLE001 — Rückfall auf die Reihe im Code
        import logging
        logging.getLogger(__name__).warning('LIK-Werte aus der Datenbank nicht lesbar — es gilt die Reihe im Code.')
    return reihen


def lik_punkte_fuer(jahr, monat, reihen=None):
    """LIK-Punkte (Decimal) eines Monats, oder None. `reihen`: die Reihen aus `lik_reihen()`, wenn schon geholt."""
    from decimal import Decimal
    reihe = (reihen if reihen is not None else lik_reihen()).get(jahr)
    if not reihe or monat < 1 or monat > len(reihe):
        return None
    val = reihe[monat - 1]
    return Decimal(str(val)) if val is not None else None


#: So viele Monate darf die Tabelle hinter dem Kalender zurückliegen, bevor `tabelle_hinweis` anschlägt.
#: Das BFS veröffentlicht den Monatswert Anfang des Folgemonats; drei Monate sind Luft für Verspätung.
TABELLE_MAX_RUECKSTAND_MONATE = 3


def letzter_tabellenmonat():
    """(jahr, monat) des jüngsten Monats mit Wert (Code und Nachträge), oder None."""
    letzter = None
    reihen = lik_reihen()
    for jahr in sorted(reihen):
        for i, val in enumerate(reihen[jahr]):
            if val is not None:
                letzter = (jahr, i + 1)
    return letzter


def tabelle_rueckstand_monate(heute):
    """Wie viele Monate die Tabelle hinter dem Kalendermonat von `heute` liegt (0 = aktueller Monat)."""
    letzter = letzter_tabellenmonat()
    if letzter is None:
        return None
    return (heute.year - letzter[0]) * 12 + (heute.month - letzter[1])


def tabelle_hinweis(heute):
    """Hinweistext, wenn die Tabelle zu weit hinter dem Kalender liegt — sonst ''.

    Ein Hinweis statt eines Absturzes: Fehlt der aktuelle Monat, melden die Anpassungen «kein Wert»
    (fail-safe), und die Verwaltung erfährt hier, was zu tun ist."""
    rueckstand = tabelle_rueckstand_monate(heute)
    if rueckstand is not None and rueckstand <= TABELLE_MAX_RUECKSTAND_MONATE:
        return ''
    letzter = letzter_tabellenmonat()
    stand = f"{_MONATE[letzter[1] - 1]} {letzter[0]}" if letzter else "kein Monat"
    return (f"Die LIK-Tabelle endet im {stand} und liegt mehr als "
            f"{TABELLE_MAX_RUECKSTAND_MONATE} Monate hinter dem Kalender. Bitte die Monatswerte des BFS "
            "(Landesindex der Konsumentenpreise) nachtragen; bis dahin sind Indexanpassungen für die "
            "fehlenden Monate gesperrt.")


def _tabelle_wert():
    """Neuester Wert aus der eingebauten BFS-Tabelle (Offline-Netz)."""
    import datetime
    from decimal import Decimal
    best = None
    reihen = lik_reihen()
    for jahr in sorted(reihen):
        reihe = reihen[jahr]
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
    (kein Internet, Layout-Änderung …) → dann greift die Tabelle.

    Jeder Versuch hinterlässt eine Spur (`core.services.abruf_status`): Ein stiller Ausfall bliebe sonst Wochen
    unbemerkt. Der Grund ist knapp und ohne Zugangsdaten formuliert."""
    import re
    import datetime
    from decimal import Decimal, InvalidOperation
    from core.services import abruf_status

    def fehler(grund):
        abruf_status.melde_fehler('lik', grund)
        return None

    try:
        import requests
    except Exception:
        return fehler('requests nicht verfügbar')
    url = "https://www.hev-schweiz.ch/vermieten/statistiken/landesindex-der-konsumentenpreise"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
               'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        antwort = requests.get(url, headers=headers, timeout=timeout)
    except Exception as e:                                   # noqa: BLE001
        return fehler(f'Verbindung fehlgeschlagen ({type(e).__name__})')
    if getattr(antwort, 'status_code', 200) != 200:
        return fehler(f'Quelle antwortet mit Status {antwort.status_code}')
    html = antwort.text
    try:
        pos = html.find("2020 = 100")
        if pos < 0:
            return fehler('Marke «2020 = 100» fehlt in der Quelle (Seite umgebaut oder auf neue Basis umgestellt?)')
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
                abruf_status.melde_erfolg('lik')
                return datetime.date(yr, monat, 1), wert
    except Exception as e:                                   # noqa: BLE001
        return fehler(f'Auswertung fehlgeschlagen ({type(e).__name__})')
    return fehler('Keine Monatswerte in der erwarteten Form gefunden (Tabelle der Quelle verändert?)')


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
