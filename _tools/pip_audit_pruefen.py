"""Wertet die Ausgabe von `pip-audit --format json` für die CI aus (SICH-04).

Der Job schlägt fehl, wenn eine bekannte Schwachstelle eine Fix-Version hat — dann gibt
es ein Update, das man einspielen kann, und ein Verzicht darauf muss begründet sein. Eine
Schwachstelle OHNE Fix-Version erscheint als Hinweis, ohne den Lauf rot zu machen: Man kann
sie nicht beheben, nur beobachten.

Ausnahmen stehen in `pip-audit-ignore.txt`, eine je Zeile:

    PYSEC-2026-1234   # Begründung, bis wann, wer entschieden hat

Eine Ausnahme OHNE Begründung zählt nicht (die Zeile wird abgewiesen), und eine Ausnahme, die
nichts mehr trifft (behoben oder veraltet), wird gemeldet — sonst sammelt sich Altlast an, die
beim nächsten gleichnamigen Fund still etwas durchlässt.

Aufruf:  python _tools/pip_audit_pruefen.py pip-audit.json pip-audit-ignore.txt
Rückgabe: 0 = sauber, 1 = Schwachstelle mit Fix oder ungültige Ausnahme.
"""
import json
import re
import sys

ID_MUSTER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


def ausnahmen_lesen(text):
    """{id: begruendung} und die Liste der abgewiesenen Zeilen."""
    ausnahmen, fehler = {}, []
    for nr, zeile in enumerate(text.splitlines(), start=1):
        roh = zeile.strip()
        if not roh or roh.startswith('#'):
            continue
        kennung, _, begruendung = roh.partition('#')
        kennung, begruendung = kennung.strip(), begruendung.strip()
        if not ID_MUSTER.match(kennung):
            fehler.append(f'Zeile {nr}: «{roh}» ist keine Kennung')
        elif len(begruendung) < 10:
            fehler.append(f'Zeile {nr}: {kennung} hat keine Begründung (hinter «#», mindestens ein Satz)')
        else:
            ausnahmen[kennung] = begruendung
    return ausnahmen, fehler


def pruefen(bericht, ausnahmen):
    """(Funde mit Fix, Funde ohne Fix, ungenutzte Ausnahmen) aus dem JSON-Bericht."""
    mit_fix, ohne_fix, genutzt = [], [], set()
    for paket in bericht.get('dependencies', []):
        for schwachstelle in paket.get('vulns', []):
            namen = {schwachstelle.get('id')} | set(schwachstelle.get('aliases', []))
            treffer = namen & set(ausnahmen)
            if treffer:
                genutzt |= treffer
                continue
            zeile = (paket['name'], paket['version'], schwachstelle['id'],
                     schwachstelle.get('fix_versions') or [])
            (mit_fix if zeile[3] else ohne_fix).append(zeile)
    return mit_fix, ohne_fix, sorted(set(ausnahmen) - genutzt)


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    with open(argv[1], encoding='utf-8') as f:
        bericht = json.load(f)
    with open(argv[2], encoding='utf-8') as f:
        ausnahmen, fehler = ausnahmen_lesen(f.read())
    mit_fix, ohne_fix, ungenutzt = pruefen(bericht, ausnahmen)

    for text in fehler:
        print(f'FEHLER  pip-audit-ignore.txt, {text}')
    for name, version, kennung, fix in mit_fix:
        print(f'FEHLER  {name} {version}: {kennung} — behoben ab {", ".join(fix)}')
    for name, version, kennung, _fix in ohne_fix:
        print(f'HINWEIS {name} {version}: {kennung} — noch keine behobene Fassung')
    for kennung in ungenutzt:
        print(f'HINWEIS Ausnahme {kennung} trifft nichts mehr — aus pip-audit-ignore.txt streichen')

    if mit_fix or fehler:
        print(f'\n{len(mit_fix)} Schwachstelle(n) mit Fix-Version, {len(fehler)} ungültige Ausnahme(n).')
        return 1
    print(f'Keine behebbare Schwachstelle ({len(ohne_fix)} ohne Fix-Version, '
          f'{len(ausnahmen)} begründete Ausnahme(n)).')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
