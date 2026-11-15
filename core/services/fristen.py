"""Fristende nach Art. 78 OR: Fällt der letzte Tag auf einen Sonntag oder Feiertag, gilt der nächste Werktag.

DER TEXT (Art. 78 Abs. 1 OR, Fedlex)

    «Fällt der Zeitpunkt der Erfüllung oder der letzte Tag einer Frist auf einen Sonntag oder auf einen
    andern am Erfüllungsorte staatlich anerkannten Feiertag, so gilt als Erfüllungstag oder als letzter Tag
    der Frist der nächstfolgende Werktag.»

Wer an diesem nächsten Werktag zahlt, zahlt rechtzeitig. Eine Kündigung nach Art. 257d OR, die am Montag nach
einem Sonntags-Fristende gegen einen Mieter ausgesprochen wird, der am Montag bezahlt hat, wäre gegen einen
rechtzeitig zahlenden Mieter gerichtet (Audit MIET-10).

WAS HIER ALS NICHT-WERKTAG GILT

* Sonntag und Samstag. Der Samstag ist nach der Fussnote zu Art. 78 nur für gesetzliche Fristen des
  eidgenössischen Rechts und behördlich angesetzte Fristen dem Feiertag gleichgestellt (BG über den
  Fristenlauf an Samstagen, SR 173.110.3). Die Zahlungsfrist des Vermieters ist eine private Frist. Weil der
  Fehler hier nur in eine Richtung wehtut — eine zu früh ausgesprochene Kündigung —, wird der Samstag
  trotzdem übersprungen (konservative Lesart; Fachpunkt im Bericht).
* Die Feiertage, die in praktisch allen Kantonen anerkannt sind: Neujahr, Karfreitag, Ostermontag, Auffahrt,
  Pfingstmontag, Bundesfeiertag (1. August), Weihnachten, Stephanstag. Ein Tag, der in einem einzelnen Kanton
  keiner ist, verlängert die Frist um einen Tag — das ist die sichere Seite.

KANTONALE FEIERTAGE (14.11.2026)

Erfüllungsort ist die Liegenschaft; ihr Kanton bestimmt die zusätzlichen Feiertage. Quelle ist das Verzeichnis des
Bundesamts für Justiz «Gesetzliche Feiertage und Tage, die in der Schweiz wie gesetzliche Feiertage behandelt werden»
(gestützt auf Art. 11 des Europäischen Übereinkommens über die Berechnung von Fristen, SR 0.221.122.3), STAND 1. JANUAR
2011 — eine neuere Fassung führt das Bundesamt nicht. Übernommen sind beide Gruppen des Verzeichnisses (gesetzlich
anerkannt / wie gesetzliche Feiertage behandelt).

Wie die Tabelle gelesen wird:

* Die kantonalen Tage kommen ZU den allgemeinen hinzu. Es fällt keiner weg, auch wenn ein Kanton ihn nicht führt
  (Karfreitag im Wallis und im Tessin, Stephanstag in Genf): Die Frist endet dann einen Tag später — die sichere Seite.
* Tage, die für einen Kantonsteil gelten (Freiburg ohne einige Gemeinden des Seebezirks, Appenzell I. Rh. innerer
  Landesteil, Solothurn mit und ohne Bucheggberg), gelten hier im ganzen Kanton. Halbe Tage (1. Mai in Solothurn ab
  12 Uhr) zählen als ganzer Tag. Beides aus demselben Grund.
* Tage, die nur in einzeln genannten Gemeinden gelten, fehlen: Josephstag und Patroziniumsfeste in Solothurn,
  Fronleichnam in Le Landeron (NE).
* Neuenburg: 2. Januar nur, wenn der 1. Januar ein Sonntag ist (Fussnote des Verzeichnisses).
* Bewegliche Tage nennt das Verzeichnis ohne Datum. Fronleichnam: 60 Tage nach Ostersonntag. Montag nach dem
  Eidgenössischen Bettag (VD): Montag nach dem dritten Sonntag im September. Genfer Bettag: Donnerstag nach dem ersten
  Sonntag im September. Das Glarner Fahrtsfest fehlt, weil seine Datumsregel nicht belegt ist.
  Die drei Regeln stehen nicht im Verzeichnis; der Betreiber hat sie am 15.11.2026 dem Entwickler überlassen und
  sie gelten bis auf Widerruf (allgemein bekannte Festlegungen der jeweiligen Tage).

Ohne Kanton (Liegenschaft ohne Angabe) gelten nur die allgemeinen Tage, wie bisher.
"""
from datetime import date, timedelta


def ostersonntag(jahr: int) -> date:
    """Ostersonntag des gregorianischen Kalenders (Verfahren von Meeus/Jones/Butcher)."""
    a = jahr % 19
    b, c = divmod(jahr, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    monat, tag = divmod(h + l - 7 * m + 114, 31)
    return date(jahr, monat, tag + 1)


FRONLEICHNAM, BETTAGSMONTAG, GENFER_BETTAG = 'fronleichnam', 'bettagsmontag', 'genfer_bettag'

_N = {
    (1, 2): 'Berchtoldstag', (1, 6): 'Dreikönigstag', (3, 1): 'Instauration de la République', (3, 19): 'Josephstag',
    (5, 1): 'Tag der Arbeit', (6, 23): 'Commémoration du plébiscite jurassien', (6, 29): 'Peter und Paul',
    (8, 15): 'Mariä Himmelfahrt', (9, 22): 'Mauritiustag', (9, 25): 'Bruderklausenfest', (11, 1): 'Allerheiligen',
    (12, 8): 'Mariä Empfängnis', (12, 31): 'Restauration de la République',
    FRONLEICHNAM: 'Fronleichnam', BETTAGSMONTAG: 'Montag nach dem Eidgenössischen Bettag', GENFER_BETTAG: 'Genfer Bettag',
}
_KATHOLISCH = (FRONLEICHNAM, (8, 15), (11, 1), (12, 8))

#: Zusätzliche Feiertage je Kanton, über die allgemeinen hinaus. Abschrift aus dem Verzeichnis des Bundesamts für Justiz,
#: Stand 1. Januar 2011 (siehe Modultext). Nicht aus dem Gedächtnis ergänzen: Jede Änderung braucht die Quelle.
KANTONALE_FEIERTAGE = {
    'ZH': ((1, 2), (5, 1)),
    'BE': ((1, 2),),
    'LU': ((1, 2),) + _KATHOLISCH,
    'UR': ((1, 6), (3, 19)) + _KATHOLISCH,
    'SZ': ((1, 6), (3, 19)) + _KATHOLISCH,
    'OW': ((1, 2), (9, 25)) + _KATHOLISCH,
    'NW': ((1, 2), (3, 19)) + _KATHOLISCH,
    'GL': ((1, 2), (11, 1)),
    'ZG': ((1, 2),) + _KATHOLISCH,
    'FR': ((1, 2),) + _KATHOLISCH,
    'SO': ((1, 2), (5, 1), FRONLEICHNAM, (8, 15), (11, 1)),
    'BS': ((5, 1),),
    'BL': ((5, 1),),
    'SH': ((1, 2), (5, 1)),
    'AR': (),
    'AI': ((9, 22),) + _KATHOLISCH,
    'SG': ((1, 2), (11, 1)),
    'GR': (),
    'AG': ((1, 2), (5, 1)) + _KATHOLISCH,
    'TG': ((1, 2), (5, 1)),
    'TI': ((1, 6), (3, 19), (5, 1), (6, 29)) + _KATHOLISCH,
    'VD': ((1, 2), BETTAGSMONTAG),
    'VS': ((1, 2), (3, 19)) + _KATHOLISCH,
    'NE': ((3, 1), (5, 1)),          # dazu der 2. Januar, wenn der 1. Januar ein Sonntag ist (siehe `feiertage`)
    'GE': (GENFER_BETTAG, (12, 31)),
    'JU': ((1, 2), (5, 1), FRONLEICHNAM, (6, 23), (8, 15), (11, 1)),
}


def _sonntag_im_september(jahr: int, nummer: int) -> date:
    erster = date(jahr, 9, 1)
    return erster + timedelta(days=(6 - erster.weekday()) % 7 + 7 * (nummer - 1))


def kanton_von(objekt) -> str:
    """Kanton des Erfüllungsorts: aus einer Liegenschaft, einem Mietvertrag, einer Pendenz oder einem Kürzel.
    Leer, wenn keiner hinterlegt ist — dann gelten nur die allgemeinen Feiertage."""
    if not objekt:
        return ''
    if isinstance(objekt, str):
        return objekt.strip().upper() if objekt.strip().upper() in KANTONALE_FEIERTAGE else ''
    lg = objekt if hasattr(objekt, 'kanton') else None
    if lg is None and getattr(objekt, 'liegenschaft_id', None):
        lg = objekt.liegenschaft
    if lg is None:
        vertrag = objekt if hasattr(objekt, 'einheit_id') else getattr(objekt, 'vertrag', None)
        if vertrag is not None and getattr(vertrag, 'einheit_id', None):
            lg = vertrag.einheit.liegenschaft
    return kanton_von(getattr(lg, 'kanton', '') or '') if lg is not None else ''


def feiertage(jahr: int, kanton: str = '') -> dict:
    """Die Feiertage des Jahres: {Datum: Name}. Ohne Kanton die in (fast) allen Kantonen anerkannten, mit Kanton
    zusätzlich die kantonalen nach dem Verzeichnis des Bundesamts für Justiz."""
    ostern = ostersonntag(jahr)
    tage = {
        date(jahr, 1, 1): 'Neujahr',
        ostern - timedelta(days=2): 'Karfreitag',
        ostern + timedelta(days=1): 'Ostermontag',
        ostern + timedelta(days=39): 'Auffahrt',
        ostern + timedelta(days=50): 'Pfingstmontag',
        date(jahr, 8, 1): 'Bundesfeiertag',
        date(jahr, 12, 25): 'Weihnachten',
        date(jahr, 12, 26): 'Stephanstag',
    }
    kt = kanton_von(kanton)
    for eintrag in KANTONALE_FEIERTAGE.get(kt, ()):
        if eintrag == FRONLEICHNAM:
            tag = ostern + timedelta(days=60)
        elif eintrag == BETTAGSMONTAG:
            tag = _sonntag_im_september(jahr, 3) + timedelta(days=1)
        elif eintrag == GENFER_BETTAG:
            tag = _sonntag_im_september(jahr, 1) + timedelta(days=4)
        else:
            tag = date(jahr, *eintrag)
        tage.setdefault(tag, _N[eintrag])
    if kt == 'NE' and date(jahr, 1, 1).weekday() == 6:
        tage.setdefault(date(jahr, 1, 2), _N[(1, 2)])
    return tage


def ist_werktag(tag: date, kanton: str = '') -> bool:
    """Montag bis Freitag und kein anerkannter Feiertag (am Ort der Liegenschaft, wenn `kanton` gesetzt ist)."""
    return tag.weekday() < 5 and tag not in feiertage(tag.year, kanton)


def naechster_werktag(tag: date, kanton: str = '') -> date:
    """`tag`, wenn er ein Werktag ist, sonst der nächste Werktag (Art. 78 Abs. 1 OR)."""
    while not ist_werktag(tag, kanton):
        tag += timedelta(days=1)
    return tag


def fristende(start: date, tage: int, kanton: str = '') -> date:
    """Letzter Tag einer Frist von `tage` Tagen ab `start` (der Starttag zählt nicht mit, Art. 77 Abs. 1
    Ziff. 1 OR), verschoben auf den nächsten Werktag am Ort der Liegenschaft."""
    return naechster_werktag(start + timedelta(days=tage), kanton)
