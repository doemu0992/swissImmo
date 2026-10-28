"""Abfrageparameter lesen, ohne bei Unsinn abzustürzen (ROUTE-05).

Ein veralteter Lesezeichen- oder Mail-Link kann `?lg=abc`, `?jahr=99999` oder
`?monate=999999999999` tragen. Früher endete jedes davon in einem `ValueError`
oder einer Datenbankausnahme: HTTP 500 auf 136 von 166 Seiten. Ein ungültiger
Wert gilt jetzt als nicht angegeben — die Seite zeigt ihren Standard.
"""

#: Grösste Kennung, die in ein `bigint`-Feld passt (PostgreSQL). Alles darüber
#: kann keine Zeile bezeichnen und würde dort einen `DataError` auslösen.
GROESSTE_ID = 2 ** 63 - 1

#: Kalenderjahre, mit denen die Berichte und Perioden rechnen (`datetime.date`).
JAHR_MIN, JAHR_MAX = 1900, 2200


def int_param(roh, standard=None, minimum=None, maximum=None):
    """Der Parameter als ganze Zahl — oder `standard`, wenn er fehlt, keine Zahl
    ist oder ausserhalb von [minimum, maximum] liegt.

    Nur Ziffern (mit optionalem Minus) zählen: `' 5 '`, `'5.0'`, `'1e3'` und
    `'٣'` (nicht-lateinische Ziffern) sind keine Kennungen.
    """
    if roh is None:
        return standard
    text = str(roh).strip()
    ziffern = text[1:] if text[:1] == '-' else text
    if not (ziffern.isascii() and ziffern.isdigit()) or len(ziffern) > 19:
        return standard
    wert = int(text)
    if minimum is not None and wert < minimum:
        return standard
    if maximum is not None and wert > maximum:
        return standard
    return wert


def id_param(roh, standard=None):
    """Eine Datensatz-Kennung: positive Zahl, die in ein `bigint` passt."""
    return int_param(roh, standard, minimum=1, maximum=GROESSTE_ID)


def jahr_param(roh, standard=None):
    """Ein Kalenderjahr zwischen 1900 und 2200, sonst `standard`."""
    return int_param(roh, standard, minimum=JAHR_MIN, maximum=JAHR_MAX)


def jahr_streng(roh):
    """Wie `jahr_param`, wirft aber `ValueError` bei ungültigem Wert.

    Für die vielen Stellen, die `int(request.GET.get('jahr'))` mit
    `except ValueError: <Standardjahr>` lesen: Ein Jahr wie 99999 war dort eine
    gültige Zahl und scheiterte erst später in `date(jahr, 1, 1)` — als 500."""
    wert = jahr_param(roh)
    if wert is None:
        raise ValueError(f'Kein gültiges Jahr: {roh!r}')
    return wert


def sicheres_ziel(request, standard, feld='next'):
    """Das Rücksprungziel aus dem Formular — nur eine Adresse dieser Anwendung.

    `redirect(request.POST.get('next'))` nahm jede Zeichenkette: Eine Nicht-URL
    ergab `NoReverseMatch` (500), eine fremde Adresse eine offene Weiterleitung
    (ROUTE-06/16). Zugelassen sind nur Pfade auf dem eigenen Server."""
    from django.utils.http import url_has_allowed_host_and_scheme
    ziel = (request.POST.get(feld) or request.GET.get(feld) or '').strip()
    if (ziel.startswith('/') and not ziel.startswith('//') and '\\' not in ziel
            and url_has_allowed_host_and_scheme(ziel, allowed_hosts={request.get_host()},
                                                require_https=request.is_secure())):
        return ziel
    return standard
