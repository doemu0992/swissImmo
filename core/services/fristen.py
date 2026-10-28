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

WAS FEHLT

Die kantonalen und ortsüblichen Feiertage (etwa Berchtoldstag, Fronleichnam, 1. Mai, Allerheiligen, Mariä
Empfängnis, Genfer Fasten) kennt der Bestand nicht; es gab bisher keine Feiertagslogik. Sie sind nicht
enthalten. Gehört der letzte Tag der Frist auf einen solchen Tag, rechnet die Anwendung ein Tag zu früh —
das ist ein offener Fachpunkt, keine stille Annahme.
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


def feiertage(jahr: int) -> dict:
    """Die in (fast) allen Kantonen anerkannten Feiertage des Jahres: {Datum: Name}."""
    ostern = ostersonntag(jahr)
    return {
        date(jahr, 1, 1): 'Neujahr',
        ostern - timedelta(days=2): 'Karfreitag',
        ostern + timedelta(days=1): 'Ostermontag',
        ostern + timedelta(days=39): 'Auffahrt',
        ostern + timedelta(days=50): 'Pfingstmontag',
        date(jahr, 8, 1): 'Bundesfeiertag',
        date(jahr, 12, 25): 'Weihnachten',
        date(jahr, 12, 26): 'Stephanstag',
    }


def ist_werktag(tag: date) -> bool:
    """Montag bis Freitag und kein anerkannter Feiertag."""
    return tag.weekday() < 5 and tag not in feiertage(tag.year)


def naechster_werktag(tag: date) -> date:
    """`tag`, wenn er ein Werktag ist, sonst der nächste Werktag (Art. 78 Abs. 1 OR)."""
    while not ist_werktag(tag):
        tag += timedelta(days=1)
    return tag


def fristende(start: date, tage: int) -> date:
    """Letzter Tag einer Frist von `tage` Tagen ab `start` (der Starttag zählt nicht mit, Art. 77 Abs. 1
    Ziff. 1 OR), verschoben auf den nächsten Werktag."""
    return naechster_werktag(start + timedelta(days=tage))
