"""Wertet die Ausgabe von `manage.py check --deploy` für die CI aus (SICH-28).

Django meldet Härtungslücken (Cookies, HSTS, Weiterleitung auf HTTPS, ...) nur als Warnung, und
`--fail-level WARNING` bräuchte eine Umgebung ohne jede Warnung. Dieses Skript lässt Ausnahmen mit
Begründung zu, wie `pip_audit_pruefen.py` für die Abhängigkeiten:

    security.W019   # X_FRAME_OPTIONS = SAMEORIGIN ist Absicht: die eigenen Popups und die PDF-Vorschau brauchen es; 29.10.2026

Eine Warnung ohne Ausnahme macht den Lauf rot, eine Ausnahme ohne Begründung wird abgewiesen, und eine
Ausnahme, die nichts mehr trifft, wird gemeldet.

Aufruf:  python manage.py check --deploy 2>&1 | python _tools/deploy_check_pruefen.py deploy-check-ignore.txt
Rückgabe: 0 = sauber, 1 = unbegründete Warnung oder ungültige Ausnahme.
"""
import re
import sys

KENNUNG = re.compile(r'\(([a-z_]+\.[WEC]\d{3})\)')
MUSTER_AUSNAHME = re.compile(r'^[a-z_]+\.[WEC]\d{3}$')


def ausnahmen_lesen(text):
    """({kennung: begruendung}, [fehler])."""
    ausnahmen, fehler = {}, []
    for nr, zeile in enumerate(text.splitlines(), start=1):
        roh = zeile.strip()
        if not roh or roh.startswith('#'):
            continue
        kennung, _, begruendung = roh.partition('#')
        kennung, begruendung = kennung.strip(), begruendung.strip()
        if not MUSTER_AUSNAHME.match(kennung):
            fehler.append(f'Zeile {nr}: «{roh}» ist keine Check-Kennung (z. B. security.W019)')
        elif len(begruendung) < 10:
            fehler.append(f'Zeile {nr}: {kennung} hat keine Begründung (hinter «#», mindestens ein Satz)')
        else:
            ausnahmen[kennung] = begruendung
    return ausnahmen, fehler


def pruefen(ausgabe, ausnahmen):
    """(unbegründete Funde, ungenutzte Ausnahmen) aus der Ausgabe von `check --deploy`."""
    gefunden = []
    for zeile in ausgabe.splitlines():
        treffer = KENNUNG.search(zeile)
        if treffer:
            gefunden.append(treffer.group(1))
    offen = sorted(k for k in set(gefunden) if k not in ausnahmen)
    return offen, sorted(set(ausnahmen) - set(gefunden))


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    with open(argv[1], encoding='utf-8') as f:
        ausnahmen, fehler = ausnahmen_lesen(f.read())
    ausgabe = sys.stdin.read()
    if 'System check identified' not in ausgabe and 'no issues' not in ausgabe:
        print('FEHLER  Die Eingabe ist keine Ausgabe von `manage.py check --deploy`.')
        return 1
    offen, ungenutzt = pruefen(ausgabe, ausnahmen)
    for text in fehler:
        print(f'FEHLER  {argv[1]}, {text}')
    for kennung in offen:
        print(f'FEHLER  {kennung} — Warnung ohne begründete Ausnahme')
    for kennung in ungenutzt:
        print(f'HINWEIS Ausnahme {kennung} trifft nichts mehr — aus {argv[1]} streichen')
    if offen or fehler:
        return 1
    print(f'check --deploy: keine unbegründete Warnung ({len(ausnahmen)} begründete Ausnahme(n)).')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
