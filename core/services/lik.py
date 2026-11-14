"""LIK-Hilfsfunktionen: die Reihen des Landesindex, ihre Pflege und die einheitliche Beschriftung.

Der Landesindex der Konsumentenpreise (LIK) wird in MEHREREN Basisreihen geführt («Dezember 2020 = 100»,
«Dezember 2010 = 100» usw., siehe `LIK_BASEN`). Für die Teuerungsberechnung bei Mietzinsanpassungen müssen der
alte und der neue LIK-Wert auf DERSELBEN Basis stehen, und auf dem amtlichen Formular müssen Basis + Stand-Monat
ausgewiesen werden (Art. 269a lit. b OR / VMWG).

DIE REGEL DIESES MODULS: Die Basis gehört zum VERTRAG (`Mietvertrag.lik_basis`), und gerechnet wird immer in
seiner Reihe. Zwischen den Reihen wird NIE umgerechnet und nie ein Wert einer anderen Reihe eingesetzt: Fehlt ein
Monat in der Reihe des Vertrags, gibt es keinen Wert (`None`), und die Oberfläche sagt, welcher Monat in welcher
Reihe fehlt (`fehlt_text`). Wer `basis` nicht angibt, bekommt die Standardreihe `LIK_BASIS` (Dezember 2020) —
das ist der Bestand vor der Einführung der Reihen und KEIN Rückfall für Verträge einer anderen Reihe."""
import re

_MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
           "August", "September", "Oktober", "November", "Dezember"]

# Die Standardreihe (Name = Basis): Bestand und Vorgabe, wenn weder Eigentümer noch Organisation eine andere wählen.
LIK_BASIS = "Dezember 2020"

#: Die geführten Basisreihen, die neueste zuerst (so stehen sie auch auf der HEV-Seite). EINE Liste für Modelle
#: (`choices`), Formulare, Pflegeseite und Abruf. Nur die Reihe `LIK_BASIS` hat Werte im Code; alle anderen
#: kommen ausschliesslich aus `core.LikWert` (HEV-Abruf oder Nachtrag von Hand) — hier wird kein Wert erfunden.
LIK_BASEN = ("Dezember 2025", "Dezember 2020", "Dezember 2015", "Dezember 2010", "Dezember 2005")
#: Für `choices` der Modellfelder und die Auswahllisten der Oberfläche.
LIK_BASIS_CHOICES = tuple((b, f"{b} = 100") for b in LIK_BASEN)


def basis_gueltig(basis):
    """`basis`, wenn es eine geführte Reihe ist — sonst None (leer, Freitext aus Altbestand, Tippfehler)."""
    basis = (basis or '').strip() if isinstance(basis, str) else ''
    return basis if basis in LIK_BASEN else None


def basis_monat(basis):
    """(jahr, monat) des Monats, in dem die Reihe bei 100 steht: «Dezember 2010» -> (2010, 12)."""
    return int(str(basis).rsplit(' ', 1)[1]), 12


def basis_von(vertrag):
    """Die Reihe, in der dieser Vertrag rechnet (`Mietvertrag.lik_basis`); ohne gültige Angabe die Standardreihe."""
    return basis_gueltig(getattr(vertrag, 'lik_basis', None)) or LIK_BASIS


def basis_vorgabe(objekt=None, organisation=None):
    """Die Basis, die ein NEUER Vertrag vorgeschlagen bekommt: Liegenschaft → Eigentümer (Mandat) → Organisation → 2020.

    `objekt`: Liegenschaft, Einheit oder Mietvertrag (Vertrag → Einheit → Liegenschaft → Eigentümer). Ein leeres
    oder nicht geführtes `lik_basis` (Freitext aus der Zeit vor der Auswahlliste) gilt als «nicht festgelegt», und
    die nächste Stufe entscheidet. Das ist nur die VORGABE: Gespeichert und massgeblich ist `Mietvertrag.lik_basis`;
    ein später gesetzter Standard an Liegenschaft oder Mandat ändert keinen bestehenden Vertrag."""
    lg = objekt
    if objekt is not None and hasattr(objekt, 'einheit_id'):                 # Mietvertrag
        lg = getattr(getattr(objekt, 'einheit', None), 'liegenschaft', None)
    elif objekt is not None and hasattr(objekt, 'liegenschaft_id'):          # Einheit
        lg = getattr(objekt, 'liegenschaft', None)
    eigentuemer = getattr(lg, 'eigentuemer', None) if getattr(lg, 'eigentuemer_id', None) else None
    organisation = organisation or getattr(lg, 'organisation', None)
    return (basis_gueltig(getattr(lg, 'lik_basis', None))
            or basis_gueltig(getattr(eigentuemer, 'lik_basis', None))
            or basis_gueltig(getattr(organisation, 'lik_basis', None))
            or LIK_BASIS)


def fehlt_text(basis, jahr=None, monat=None):
    """Die Meldung, wenn in der Reihe eines Vertrags ein Wert fehlt: nennt Reihe und Monat, ersetzt nichts."""
    from django.utils.translation import gettext
    if jahr and monat:
        return gettext('In der LIK-Reihe «%(basis)s = 100» fehlt der Wert für %(monat)s. Es wird kein Wert einer '
                       'anderen Reihe eingesetzt: Die Reihe unter «LIK-Werte» einlesen oder den Monat nachtragen.') % {
                           'basis': basis, 'monat': f'{monat:02d}/{jahr}'}
    return gettext('Die LIK-Reihe «%(basis)s = 100» hat noch keine Werte. Es wird kein Wert einer anderen Reihe '
                   'eingesetzt: Die Reihe unter «LIK-Werte» einlesen oder die Monate nachtragen.') % {'basis': basis}

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


#: So lange gilt die gelesene Reihe im Prozess. Kurz, damit ein Nachtrag auch in einem anderen Worker bald gilt; im
#: eigenen Prozess räumt `cache_leeren` (beim Speichern und Löschen eines Wertes) sofort auf.
CACHE_SEKUNDEN = 60
#: Je Basis ein Eintrag `{'bis', 'reihen', 'code'}`: Eine gemerkte Reihe gilt nur für IHRE Basis.
_cache = {}


def cache_leeren(*_args, **_kwargs):
    """Verwirft alle gemerkten Reihen (Signal-Empfänger und Tests)."""
    _cache.clear()


def lik_reihen(roh=False, basis=None):
    """`{jahr: [12 Werte, None = nicht veröffentlicht]}` der Reihe `basis` (ohne Angabe: `LIK_BASIS`).

    Für die Standardreihe: die Reihe im Code, darüber die nachgetragenen Werte. Für jede andere Basis NUR die
    Werte aus `core.LikWert` dieser Basis — ohne solche ist die Reihe leer (`{}`), nie die einer anderen Basis.

    Nachgetragen (`core.LikWert`) gewinnt gegen den Code. Die Reihe wird kurz im Prozess gemerkt
    (`CACHE_SEKUNDEN`): Der LIK-Wert wird auch bei jedem neuen Mietvertrag gelesen, und das soll keine
    Datenbankabfrage je Aufruf kosten. Der Rückgabewert ist eine Kopie. Ist die Datenbank nicht lesbar, gilt die
    Reihe im Code: Eine Indexrechnung darf daran nicht scheitern.

    WERTE HINTER EINER LÜCKE ZÄHLEN NICHT (ausser `roh=True`): Steht der November da und der Oktober fehlt, endet die
    Reihe für jede Rechnung im September. Ein Wert hinter einer Lücke ist fast immer ein Irrtum (14.11.2026: November
    von Hand eingetragen, bevor er veröffentlicht war) und flösse sonst als «aktueller LIK» in Verträge und
    Anpassungen. `roh=True` brauchen nur die Pflegeseite (zeigen, löschen) und der automatische Nachtrag."""
    import time
    basis = basis or LIK_BASIS
    code = LIK_DEZ2020 if basis == LIK_BASIS else {}          # nur die Standardreihe steht im Code
    gemerkt = _cache.get(basis)
    if (gemerkt is not None and time.monotonic() < gemerkt['bis']
            and gemerkt['code'] == code):                     # die Reihe im Code wurde (in Tests) ersetzt: neu lesen
        return _kopie(gemerkt['reihen'], roh)
    reihen = {jahr: list(reihe) + [None] * (12 - len(reihe)) for jahr, reihe in code.items()}
    try:
        from core.models import LikWert
        for w in LikWert.objects.filter(basis=basis):
            reihen.setdefault(w.jahr, [None] * 12)[w.monat - 1] = float(w.punkte)
    except Exception:                                        # noqa: BLE001 — Rückfall auf die Reihe im Code
        import logging
        logging.getLogger(__name__).warning('LIK-Werte aus der Datenbank nicht lesbar — es gilt die Reihe im Code.')
        return _kopie(reihen, roh)                           # nicht merken: beim nächsten Aufruf neu versuchen
    _cache[basis] = {'reihen': reihen, 'bis': time.monotonic() + CACHE_SEKUNDEN,
                     'code': {jahr: list(reihe) for jahr, reihe in code.items()}}
    return _kopie(reihen, roh)


def gefuehrte_basen():
    """Die Reihen, die Werte haben (und deshalb täglich nachgeführt werden): die Standardreihe immer, jede andere,
    sobald sie eingelesen oder von Hand begonnen wurde. Reihenfolge wie `LIK_BASEN`."""
    return [b for b in LIK_BASEN if b == LIK_BASIS or lik_reihen(roh=True, basis=b)]


def _kopie(reihen, roh):
    """Kopie der Reihen; ohne `roh` sind alle Werte hinter der ersten Lücke entfernt."""
    kopie = {jahr: list(reihe) for jahr, reihe in reihen.items()}
    if roh:
        return kopie
    begonnen = luecke = False
    for jahr in sorted(kopie):
        for i, val in enumerate(kopie[jahr]):
            if luecke:
                kopie[jahr][i] = None
            elif val is not None:
                begonnen = True
            elif begonnen:
                luecke = True
    return kopie


def lik_punkte_fuer(jahr, monat, reihen=None, basis=None):
    """LIK-Punkte (Decimal) eines Monats in der Reihe `basis`, oder None. `reihen`: die Reihen aus `lik_reihen()`,
    wenn schon geholt (dann zählt deren Basis)."""
    from decimal import Decimal
    reihe = (reihen if reihen is not None else lik_reihen(basis=basis)).get(jahr)
    if not reihe or monat < 1 or monat > len(reihe):
        return None
    val = reihe[monat - 1]
    return Decimal(str(val)) if val is not None else None


#: So viele Monate darf die Tabelle hinter dem Kalender zurückliegen, bevor `tabelle_hinweis` anschlägt.
#: Das BFS veröffentlicht den Monatswert Anfang des Folgemonats; drei Monate sind Luft für Verspätung.
TABELLE_MAX_RUECKSTAND_MONATE = 3


def letzter_tabellenmonat(reihen=None, basis=None):
    """(jahr, monat) des letzten Monats der LÜCKENLOSEN Reihe `basis` (Code und Nachträge), oder None.

    Lückenlos, nicht «jüngster Wert»: Steht der November da und der Oktober fehlt, endet die Reihe im September.
    Sonst gälte die Tabelle als aktuell, obwohl ein Monat fehlt, und der automatische Nachtrag fände keinen
    Anschluss (so geschehen am 14.11.2026 mit einem von Hand eingetragenen November)."""
    reihen = reihen if reihen is not None else lik_reihen(basis=basis)
    letzter = None
    begonnen = False
    for jahr in sorted(reihen):
        for i, val in enumerate(reihen[jahr]):
            if val is not None:
                letzter, begonnen = (jahr, i + 1), True
            elif begonnen:
                return letzter
    return letzter


def tabelle_rueckstand_monate(heute, basis=None):
    """Wie viele Monate die Reihe hinter dem Kalendermonat von `heute` liegt (0 = aktueller Monat)."""
    letzter = letzter_tabellenmonat(basis=basis)
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


def _tabelle_wert(basis=None):
    """Neuester Wert der Reihe `basis` aus Tabelle und Nachträgen (Offline-Netz)."""
    import datetime
    from decimal import Decimal
    best = None
    reihen = lik_reihen(basis=basis)
    for jahr in sorted(reihen):
        reihe = reihen[jahr]
        for i, val in enumerate(reihe):
            if val is not None:
                best = (jahr, i + 1, val)
    if best is None:
        return None, None
    j, mo, val = best
    return datetime.date(j, mo, 1), Decimal(str(val))


HEV_URL = "https://www.hev-schweiz.ch/vermieten/statistiken/landesindex-der-konsumentenpreise"


class _AbrufFehler(Exception):
    """Der Abruf ist gescheitert; der Text ist der Grund für den Abrufstatus (ohne Zugangsdaten)."""


def _hev_html(timeout=8):
    """Der Quelltext der HEV-Seite. Wirft `_AbrufFehler` mit knappem Grund."""
    try:
        import requests
    except Exception as e:                                   # noqa: BLE001
        raise _AbrufFehler('requests nicht verfügbar') from e
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
               'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        antwort = requests.get(HEV_URL, headers=headers, timeout=timeout)
    except Exception as e:                                   # noqa: BLE001
        raise _AbrufFehler(f'Verbindung fehlgeschlagen ({type(e).__name__})') from e
    if getattr(antwort, 'status_code', 200) != 200:
        raise _AbrufFehler(f'Quelle antwortet mit Status {antwort.status_code}')
    return antwort.text


_ZEILE = re.compile(r'<tr\b[^>]*>(.*?)</tr\s*>', re.S | re.I)
_ZELLE = re.compile(r'<t[dh]\b[^>]*>(.*?)</t[dh]\s*>', re.S | re.I)
_JAHR = re.compile(r'(?:19|20)\d{2}')
_WERT = re.compile(r'\d{2,3}[.,]\d')
#: Was in einer Monatszelle «kein Wert» heisst: leer oder nur Striche («---» vor dem Basismonat).
_KEIN_WERT = re.compile(r'[-–—\s]*')
#: Technische Grenze des Lesers, KEINE Fachgrenze: Eine Reihe «Basis = 100» der letzten gut zwanzig Jahre liegt
#: weit innerhalb; alles ausserhalb ist eine falsch gelesene Zelle (Jahreszahl, Prozent). Ob ein Wert in SEINER
#: Reihe plausibel ist, prüfen Abgleich und Sprung zum Vormonat (`_nachfuehren`, `reihe_einlesen`) — relativ zum
#: bekannten Stand der Reihe statt mit festen Punkten: Die frühere Grenze «100 bis 140» galt nur für die Reihe
#: Dezember 2020 und hätte die Reihe 2025 (99.9 im Januar 2026) wie auch die Reihe 2010 (unter 100 ab 2011)
#: abgewiesen.
_WERT_MIN, _WERT_MAX = 50, 200


def _zelltext(roh):
    """Der sichtbare Text einer Tabellenzelle: ohne Auszeichnung, `&nbsp;` und Umbrüche."""
    import html as html_modul
    text = html_modul.unescape(re.sub(r'<[^>]+>', ' ', roh)).replace('\xa0', ' ')
    return ' '.join(text.split())


def _tabelle_der_basis(html, basis):
    """Der Quelltext der Tabelle zur Marke «<Basis> = 100». Wirft `_AbrufFehler`, wenn sie fehlt.

    Die Seite führt je Basis eine Tabelle, davor die Marke. Genommen wird die NÄCHSTE Tabelle nach der Marke — aber
    nur, wenn dazwischen keine weitere Marke «… = 100» steht: Sonst gehörte die Tabelle einer anderen Basis (die
    Marke stand dann nur im Fliesstext), und ihre Werte flössen in die falsche Reihe."""
    marke = re.compile(r'\s+'.join(re.escape(teil) for teil in basis.split()) + r'\s*=\s*100')
    gefunden = False
    for treffer in marke.finditer(html):
        gefunden = True
        anfang = re.search(r'<table\b', html[treffer.end():], re.I)
        if not anfang:
            break
        anfang = treffer.end() + anfang.start()
        if re.search(r'=\s*100\b', html[treffer.end():anfang]):
            continue                                         # die nächste Tabelle gehört zu einer anderen Marke
        ende = re.search(r'</table\s*>', html[anfang:], re.I)
        if not ende:
            break
        return html[anfang:anfang + ende.end()]
    if not gefunden:
        raise _AbrufFehler(f'Marke «{basis} = 100» fehlt in der Quelle (Seite umgebaut oder Reihe nicht mehr geführt?)')
    raise _AbrufFehler(f'Zur Marke «{basis} = 100» steht in der Quelle keine eigene Tabelle (Seite umgebaut?)')


def _tabelle_aus_html(html, basis):
    """`{(jahr, monat): Decimal}`: ALLE Monatswerte der HEV-Tabelle der Reihe `basis`, zellenweise gelesen.

    Zeile = Jahr, Spalte = Monat (Zelle 1 bis 12 nach der Jahreszahl); die 13. Zelle (Jahresdurchschnitt «Ø») wird
    nicht gelesen. Eine leere Zelle oder «---» ist «kein Wert» und verschiebt nichts: Der Monat ergibt sich aus der
    Spalte, nicht aus der Reihenfolge der Zahlen. Steht in einer Monatszelle etwas anderes als eine Indexzahl, ist
    die Tabelle nicht in der erwarteten Form, und es wird NICHTS gelesen (`_AbrufFehler`) — lieber kein Wert als
    ein verrutschter. Steht der Basismonat in der Tabelle, muss er 100.0 sein: die Probe, dass es die Tabelle
    dieser Basis ist."""
    from decimal import Decimal, InvalidOperation
    werte, jahre = {}, set()
    for zeile in _ZEILE.findall(_tabelle_der_basis(html, basis)):
        zellen = [_zelltext(z) for z in _ZELLE.findall(zeile)]
        if not zellen or not _JAHR.fullmatch(zellen[0]):
            continue                                         # Kopfzeile («Jahr | Jan. | …»)
        jahr = int(zellen[0])
        if jahr in jahre:
            raise _AbrufFehler(f'Das Jahr {jahr} steht in der Tabelle «{basis} = 100» zweimal (Tabelle verändert?)')
        jahre.add(jahr)
        for monat, text in enumerate(zellen[1:13], start=1):
            if _KEIN_WERT.fullmatch(text):
                continue
            try:
                wert = Decimal(text.replace(',', '.')) if _WERT.fullmatch(text) else None
            except (InvalidOperation, ValueError):
                wert = None
            if wert is None or not (_WERT_MIN <= wert <= _WERT_MAX):
                raise _AbrufFehler(f'{monat:02d}/{jahr}: Die Zelle der Tabelle «{basis} = 100» enthält keine '
                                   'Indexzahl (Tabelle der Quelle verändert?)')
            werte[(jahr, monat)] = wert
    start = werte.get(basis_monat(basis)) if basis_gueltig(basis) else None
    if start is not None and start != Decimal('100.0'):
        raise _AbrufFehler(f'Die Tabelle zur Marke «{basis} = 100» steht im Basismonat bei {start} statt bei 100 '
                           '(falsche Tabelle gelesen?)')
    return werte


def _monatswerte_aus_html(html, heute, basis=None, alle=False):
    """Die Monatswerte der HEV-Tabelle der Reihe `basis` (ohne Angabe: «Dezember 2020 = 100»).

    Gibt `[(jahr, monat, Decimal), …]` aufsteigend zurück: das laufende und das Vorjahr, mit `alle=True` die ganze
    Tabelle. Wirft `_AbrufFehler`, wenn die Tabelle nicht in der erwarteten Form da ist. Monate nach dem heutigen
    werden verworfen."""
    tabelle = _tabelle_aus_html(html, basis or LIK_BASIS)
    werte = sorted((jahr, monat, wert) for (jahr, monat), wert in tabelle.items()
                   if (jahr, monat) <= (heute.year, heute.month) and (alle or jahr >= heute.year - 1))
    if not werte:
        raise _AbrufFehler('Keine Monatswerte in der erwarteten Form gefunden (Tabelle der Quelle verändert?)')
    return werte


def _fetch_live_lik(timeout=8, basis=None):
    """Best-effort Live-Abruf des neuesten LIK der Reihe `basis` (ohne Angabe: Dez. 2020) inkl. Monat
    von der HEV-Tabelle. Gibt (date, Decimal) oder None. Fängt JEDEN Fehler ab
    (kein Internet, Layout-Änderung …) → dann greift die Tabelle.

    Jeder Versuch hinterlässt eine Spur (`core.services.abruf_status`): Ein stiller Ausfall bliebe sonst Wochen
    unbemerkt. Der Grund ist knapp und ohne Zugangsdaten formuliert."""
    import datetime
    from core.services import abruf_status
    try:
        werte = _monatswerte_aus_html(_hev_html(timeout), datetime.date.today(), basis=basis)
    except _AbrufFehler as e:
        abruf_status.melde_fehler('lik', str(e))
        return None
    except Exception as e:                                   # noqa: BLE001
        abruf_status.melde_fehler('lik', f'Auswertung fehlgeschlagen ({type(e).__name__})')
        return None
    abruf_status.melde_erfolg('lik')
    jahr, monat, wert = werte[-1]
    return datetime.date(jahr, monat, 1), wert


#: Grösster Sprung zum Vormonat, den der automatische Nachtrag annimmt (Punkte). Der grösste Monatssprung der Reihe
#: seit 2021 war 0.8 Punkte; 1.5 lässt Luft und fängt einen verrutschten Wert ab.
AUTO_MAX_SPRUNG = 1.5
#: So viele bekannte Monate müssen mit der Quelle übereinstimmen, bevor ihr ein neuer Wert geglaubt wird.
AUTO_ABGLEICH_MONATE = 3


def _davor(jahr, monat):
    return (jahr, monat - 1) if monat > 1 else (jahr - 1, 12)


def _danach(jahr, monat):
    return (jahr, monat + 1) if monat < 12 else (jahr + 1, 1)


def _reihe_text(basis):
    """Vorsatz für Meldungen: leer bei der Standardreihe (Meldungen wie bisher), sonst die Reihe beim Namen."""
    return '' if basis == LIK_BASIS else f'Reihe «{basis} = 100»: '


def _nachfuehren(html, heute, basis):
    """Der Nachtrag EINER Reihe aus dem schon geholten Quelltext: `(gespeichert, fehlertext oder None)`.

    Schreibt keinen Abrufstatus (das tut der Aufrufer, damit ein Lauf über mehrere Reihen EIN Ergebnis meldet)."""
    from decimal import Decimal
    v = _reihe_text(basis)
    try:
        quelle = {(j, m): w for j, m, w in _monatswerte_aus_html(html, heute, basis=basis)}
    except _AbrufFehler as e:
        return [], str(e)
    except Exception as e:                                   # noqa: BLE001
        return [], f'{v}Auswertung fehlgeschlagen ({type(e).__name__})'

    reihen = lik_reihen(roh=True, basis=basis)                # auch Werte hinter einer Lücke sehen (nicht überschreiben)
    letzter = letzter_tabellenmonat(basis=basis)
    if letzter is None:
        return [], f'{v}Keine eigene Reihe zum Abgleich vorhanden.'

    # Abgleich der letzten bekannten Monate. Eine junge Reihe (Basis Dezember 2025) hat anfangs weniger Monate
    # als `AUTO_ABGLEICH_MONATE`: Dann wird bis zum Basismonat abgeglichen, nicht darüber hinaus.
    erster = min((j, i + 1) for j, reihe in reihen.items() for i, w in enumerate(reihe) if w is not None)
    pruef = letzter
    for _i in range(AUTO_ABGLEICH_MONATE):
        if pruef < erster:
            break
        eigen = lik_punkte_fuer(pruef[0], pruef[1], reihen)
        fremd = quelle.get(pruef)
        if fremd is None or eigen is None or fremd != eigen:
            return [], (f'{v}Abgleich gescheitert: {pruef[1]:02d}/{pruef[0]} hier {eigen}, Quelle {fremd}. '
                        'Nichts gespeichert (Tabelle der Quelle verändert oder falsch gelesen?).')
        pruef = _davor(*pruef)

    from core.models import LikWert
    gespeichert = []
    vorwert = lik_punkte_fuer(letzter[0], letzter[1], reihen)
    naechster = _danach(*letzter)
    while naechster in quelle and naechster <= (heute.year, heute.month):
        wert = quelle[naechster]
        if abs(wert - vorwert) > Decimal(str(AUTO_MAX_SPRUNG)):
            return gespeichert, (
                f'{v}{naechster[1]:02d}/{naechster[0]}: {wert} weicht um mehr als {AUTO_MAX_SPRUNG} Punkte vom '
                f'Vormonat ({vorwert}) ab. Nicht gespeichert; bitte prüfen und von Hand nachtragen.')
        vorhanden = lik_punkte_fuer(naechster[0], naechster[1], reihen)
        if vorhanden is not None:
            # Ein späterer Monat steht schon da (von Hand, hinter einer Lücke): nicht überschreiben, aber prüfen.
            if vorhanden != wert:
                return gespeichert, (
                    f'{v}{naechster[1]:02d}/{naechster[0]}: hier {vorhanden}, Quelle {wert}. Der vorhandene Wert '
                    'bleibt; bitte unter «LIK-Werte» prüfen und den falschen löschen.')
            vorwert, naechster = vorhanden, _danach(*naechster)
            continue
        _obj, neu = LikWert.objects.get_or_create(
            jahr=naechster[0], monat=naechster[1], basis=basis,
            defaults={'punkte': wert, 'quelle': f'HEV, automatischer Abruf vom {heute:%d.%m.%Y}'})
        if neu:
            gespeichert.append((naechster[0], naechster[1], wert))
        vorwert, naechster = wert, _danach(*naechster)
    return gespeichert, None


def _quelltext_oder_fehler(timeout):
    """`(html, None)` oder `(None, grund)`: der Abruf der Seite, einmal je Lauf."""
    try:
        return _hev_html(timeout), None
    except _AbrufFehler as e:
        return None, str(e)
    except Exception as e:                                   # noqa: BLE001
        return None, f'Abruf fehlgeschlagen ({type(e).__name__})'


def automatisch_nachfuehren(heute=None, timeout=8, basis=None):
    """Holt die Monatswerte beim HEV und speichert fehlende Monate der Reihe `basis` selbst (`core.LikWert`) —
    ohne Nachtrag von Hand. Ohne `basis`: die Standardreihe.

    Entscheid des Betreibers (14.11.2026): Der abgerufene Wert gilt ohne menschliche Prüfung. Deshalb die Schranken,
    für JEDE Reihe dieselben:
    * ABGLEICH: Die letzten `AUTO_ABGLEICH_MONATE` bekannten Monate müssen in der Quelle genau so stehen wie hier.
      Liest der Abruf die Tabelle falsch (Spalte verrutscht, andere Basis), stimmen sie nicht, und es wird NICHTS
      gespeichert. Der Abgleich ist auch die Sperre gegen die falsche Reihe: Zwei Basen stimmen nie drei Monate
      lang auf die Zehntelstelle überein.
    * Nur der jeweils NÄCHSTE fehlende Monat, lückenlos; nie ein Monat nach dem heutigen.
    * Höchstens `AUTO_MAX_SPRUNG` Punkte vom Vormonat entfernt. Das ersetzt die frühere feste Grenze «100 bis 140
      Punkte»: Sie passte nur zur Reihe Dezember 2020. Relativ zum letzten bekannten Wert gilt die Schranke in
      jeder Reihe gleich streng (siehe `_WERT_MIN`).
    Ein bestehender Wert (Code oder Nachtrag) wird nie überschrieben. Eine Reihe ohne eigenen Wert wird hier nicht
    begonnen (kein Abgleich möglich): Dafür gibt es `reihe_einlesen`.

    Gibt die Liste der gespeicherten `(jahr, monat, punkte)` zurück. Jeder Ausgang steht im Abrufstatus."""
    import datetime
    from core.services import abruf_status
    heute = heute or datetime.date.today()
    basis = basis or LIK_BASIS
    html, grund = _quelltext_oder_fehler(timeout)
    if html is None:
        abruf_status.melde_fehler('lik', grund)
        return []
    cache_leeren()
    gespeichert, grund = _nachfuehren(html, heute, basis)
    if grund:
        abruf_status.melde_fehler('lik', grund)
    else:
        abruf_status.melde_erfolg('lik')
    return gespeichert


def alle_reihen_nachfuehren(heute, timeout=8):
    """Der tägliche Nachtrag: führt JEDE Reihe nach, die Werte hat (`gefuehrte_basen`). `{basis: [(jahr, monat, punkte)]}`.

    Die Seite wird EINMAL geholt (sie enthält alle Tabellen). Der Abrufstatus bekommt EIN Ergebnis: Erfolg nur, wenn
    keine Reihe einen Fehler meldet — sonst überdeckte der Erfolg der letzten Reihe den Fehler einer früheren."""
    from core.services import abruf_status
    html, grund = _quelltext_oder_fehler(timeout)
    if html is None:
        abruf_status.melde_fehler('lik', grund)
        return {}
    cache_leeren()
    ergebnis, gruende = {}, []
    for basis in gefuehrte_basen():
        try:
            gespeichert, grund = _nachfuehren(html, heute, basis)
        except Exception as e:                               # noqa: BLE001 — eine Reihe darf die anderen nicht aufhalten
            gespeichert, grund = [], f'{_reihe_text(basis)}Nachtrag fehlgeschlagen ({type(e).__name__})'
        if gespeichert:
            ergebnis[basis] = gespeichert
        if grund:
            gruende.append(grund)
    if gruende:
        abruf_status.melde_fehler('lik', ' | '.join(gruende))
    else:
        abruf_status.melde_erfolg('lik')
    return ergebnis


def reihe_einlesen(basis, heute, timeout=8):
    """Liest die GANZE HEV-Tabelle der Reihe `basis` in `core.LikWert` (Quelle «HEV»): für eine Reihe, die noch
    (fast) leer ist und deshalb keinen Abgleich für `automatisch_nachfuehren` hat.

    Gibt `{'gespeichert': [(jahr, monat, punkte)], 'abweichungen': [(jahr, monat, hier, quelle)], 'fehler': text}`
    zurück. Gespeichert wird nur, wenn die Tabelle als Ganzes trägt — sonst NICHTS:
    * LÜCKENLOS vom Basismonat (der bei 100.0 stehen muss) bis zum letzten veröffentlichten Monat. Eine Lücke
      in der Quelle hiesse: Tabelle falsch gelesen.
    * Kein Sprung über `AUTO_MAX_SPRUNG` Punkte von einem Monat zum nächsten (verrutschte Zelle).
    * Der laufende Monat und spätere werden nie gespeichert: Das BFS veröffentlicht einen Monat erst im Folgemonat.
    Ein vorhandener Wert (Code oder Nachtrag) wird NICHT überschrieben; weicht er von der Quelle ab, steht er in
    `abweichungen`, und der Betreiber entscheidet (löschen und neu einlesen, oder stehen lassen)."""
    from decimal import Decimal
    from core.services import abruf_status
    ergebnis = {'gespeichert': [], 'abweichungen': [], 'fehler': ''}
    v = f'Reihe «{basis} = 100»: '
    if not basis_gueltig(basis):
        ergebnis['fehler'] = f'«{basis}» ist keine geführte LIK-Reihe.'
        return ergebnis
    html, grund = _quelltext_oder_fehler(timeout)
    if html is None:
        abruf_status.melde_fehler('lik', grund)
        ergebnis['fehler'] = grund
        return ergebnis
    try:
        tabelle = _tabelle_aus_html(html, basis)
    except _AbrufFehler as e:
        abruf_status.melde_fehler('lik', str(e))
        ergebnis['fehler'] = str(e)
        return ergebnis
    grenze = _davor(heute.year, heute.month)                  # der Vormonat: der jüngste, der veröffentlicht sein kann
    monat = basis_monat(basis)
    grund = ''
    if tabelle.get(monat) != Decimal('100.0'):
        grund = f'{v}Der Basismonat {monat[1]:02d}/{monat[0]} steht in der Quelle nicht bei 100.0. Nichts gespeichert.'
    folge, vorwert = [], None
    while not grund and monat <= grenze and monat in tabelle:
        wert = tabelle[monat]
        if vorwert is not None and abs(wert - vorwert) > Decimal(str(AUTO_MAX_SPRUNG)):
            grund = (f'{v}{monat[1]:02d}/{monat[0]}: {wert} weicht um mehr als {AUTO_MAX_SPRUNG} Punkte vom Vormonat '
                     f'({vorwert}) ab. Nichts gespeichert; bitte die Quelle prüfen.')
            break
        folge.append((monat[0], monat[1], wert))
        vorwert, monat = wert, _danach(*monat)
    if not grund:
        spaeter = sorted(m for m in tabelle if monat < m <= grenze)
        if spaeter:
            grund = (f'{v}In der Quelle fehlt {monat[1]:02d}/{monat[0]}, obwohl {spaeter[0][1]:02d}/{spaeter[0][0]} '
                     'dasteht. Nichts gespeichert (Tabelle der Quelle verändert oder falsch gelesen?).')
    if grund:
        abruf_status.melde_fehler('lik', grund)
        ergebnis['fehler'] = grund
        return ergebnis

    from django.db import transaction

    from core.models import LikWert
    cache_leeren()
    reihen = lik_reihen(roh=True, basis=basis)
    neu = []
    for jahr, mon, wert in folge:
        vorhanden = lik_punkte_fuer(jahr, mon, reihen)
        if vorhanden is None:
            neu.append(LikWert(jahr=jahr, monat=mon, basis=basis, punkte=wert,
                               quelle=f'HEV, Reihe eingelesen am {heute:%d.%m.%Y}'))
        elif vorhanden != wert:
            ergebnis['abweichungen'].append((jahr, mon, vorhanden, wert))
    with transaction.atomic():
        # `bulk_create` löst kein `post_save` aus: Der Cache wird darunter von Hand geleert.
        LikWert.objects.bulk_create(neu)
    cache_leeren()
    ergebnis['gespeichert'] = [(w.jahr, w.monat, w.punkte) for w in neu]
    abruf_status.melde_erfolg('lik')
    return ergebnis


def _live_lik_cached(basis=None):
    """Live-Wert der Reihe `basis` mit 24-h-Cache (schont die Quelle, hält es aktuell). Je Reihe ein Schlüssel:
    Der Index ist plattformweit derselbe (kein Organisationsbezug), aber nie reihenübergreifend."""
    basis = basis or LIK_BASIS
    if basis == LIK_BASIS:
        abruf = _fetch_live_lik                               # wie bisher (Tests ersetzen den Abruf ohne Argument)
    else:
        def abruf():
            return _fetch_live_lik(basis=basis)
    try:
        from django.core.cache import cache
    except Exception:
        return abruf()
    key = 'lik_live_dez2020_v1' if basis == LIK_BASIS else 'lik_live_v2_' + basis.replace(' ', '_').lower()
    cached = cache.get(key)
    if cached is not None:
        return cached or None      # False-Sentinel = letzter Versuch fehlgeschlagen
    got = abruf()
    cache.set(key, got or False, 60 * 60 * 24)
    return got


def aktueller_lik_wert(live=True, basis=None):
    """Neuester LIK-Wert (stand_date, punkte, basis) der Reihe `basis` — vollautomatisch. Ohne `basis`: Standardreihe.

    Priorität: Live-Abruf (BFS/HEV, 24-h-Cache) → eingebaute BFS-Tabelle.
    Der Live-Wert gewinnt nur, wenn er mindestens so aktuell ist wie die
    Tabelle (verhindert Rückschritte durch fehlerhaftes Parsing).

    Hat die Reihe keinen Wert, ist das Ergebnis `(None, None, basis)` — NIE der Wert einer anderen Reihe. Für eine
    andere als die Standardreihe zählt der Live-Wert nur, wenn die Reihe selbst schon Werte hat: Eine leere Reihe
    wird über «Reihe einlesen» begonnen (mit Probe am Basismonat), nicht über einen einzelnen abgerufenen Wert.
    """
    basis = basis or LIK_BASIS
    t_stand, t_pkt = _tabelle_wert(basis)
    if live and (basis == LIK_BASIS or t_stand is not None):
        got = _live_lik_cached(basis)
        if got and got[0] and (t_stand is None or got[0] >= t_stand):
            return got[0], got[1], basis
    return t_stand, t_pkt, basis


def aktuell_in_reihe(basis, wert_standardreihe=None):
    """Der «aktuelle LIK», mit dem ein Vertrag der Reihe `basis` verglichen wird, oder None.

    Für die Standardreihe der Wert, den der Aufrufer schon führt (`wert_standardreihe`, etwa
    `Organisation.aktueller_lik_punkte` — der wird in der Reihe Dezember 2020 nachgeführt); fehlt er, der letzte
    Tabellenwert. Für jede andere Reihe der letzte Wert DIESER Reihe (Tabelle, ohne Netz) — und None, wenn sie
    keinen hat. Der Wert der Standardreihe wird einem Vertrag einer anderen Reihe nie untergeschoben."""
    basis = basis or LIK_BASIS
    if basis == LIK_BASIS and wert_standardreihe is not None:
        return wert_standardreihe
    return aktueller_lik_wert(live=False, basis=basis)[1]


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
    - Basis: `Vertrag.lik_basis` — die Reihe, in der `basis_lik_punkte` steht (nicht mehr die Einstellung der
      Verwaltung: Die ist nur noch die Vorgabe für neue Verträge, siehe `basis_vorgabe`)
    - Stand: `Vertrag.basis_lik_stand`; fehlt er, bei der Standardreihe `Verwaltung.aktueller_lik_stand` (der wird
      in der Reihe Dezember 2020 geführt und passt zu keiner anderen)
    - Punkte: `Vertrag.basis_lik_punkte` (Schweizer Format mit Komma)
    """
    basis = basis_von(vertrag)
    stand = getattr(vertrag, 'basis_lik_stand', None) or (
        getattr(verwaltung, 'aktueller_lik_stand', None) if basis == LIK_BASIS else None)
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


def _empfaenger_verbinden():
    from django.db.models.signals import post_delete, post_save
    post_save.connect(cache_leeren, sender='core.LikWert', dispatch_uid='lik_cache_save')
    post_delete.connect(cache_leeren, sender='core.LikWert', dispatch_uid='lik_cache_delete')


_empfaenger_verbinden()
