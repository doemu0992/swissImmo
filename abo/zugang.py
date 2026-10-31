"""Der Guard: Welche Pfade und Views hängen an welchem Merkmal.

EINE TABELLE, NICHT EIN `if` PRO VIEW

`PFAD_MODULE` ordnet URL-Präfixe einem Merkmal aus `core/funktionen.py` zu. Die
Middleware (`abo/middleware.py`) liest sie bei jeder Anfrage; die Navigation
liest sie, um Einträge als gesperrt zu kennzeichnen. Ein neuer Pfad unter einem
Präfix ist damit ab der ersten Zeile mitgeschützt — auch die Seiten, die ein
anderer Auftrag später dazubaut (Eigentümerportal v2 unter `/portal/`).

Einzelne Views, die in keinem Präfix liegen, hängen den Dekorator
`funktion_erforderlich` an. Er prüft selbst und merkt sich das Merkmal an der
View (`benoetigtes_merkmal`), wie `rolle_erforderlich` seine Rollen.

Ein Merkmal wird über seinen NAMEN abgefragt, nie über die Stufe.

GESPERRT HEISST GESPERRT, NICHT GELÖSCHT

`lesen=True`: Lesende Anfragen (GET/HEAD) gehen durch, schreibende nicht. Wer
die Funktion gestern benutzt hat, sieht seine Daten weiter und liest den
Hinweis mit dem Weg zum Upgrade im Banner. `lesen=False` sperrt die ganze
Seite (Portale, Import).
"""
from functools import wraps

from django.shortcuts import render

from core.funktionen import FUNKTIONEN, MODULE, hat_funktion
from core.tenancy import aktuelle_organisation

LESENDE_METHODEN = ('GET', 'HEAD', 'OPTIONS')

#: (Präfix, Merkmal, lesen_bleibt). Die ERSTE passende Zeile gilt; `None` als
#: Merkmal nimmt einen Pfad ausdrücklich aus (Anmeldung muss erreichbar bleiben).
PFAD_MODULE = (
    ('/portal/login/', None, False),
    ('/portal/stweg/', 'stweg', False),
    ('/portal/', 'eigentuemerportal', False),
    ('/mieter/', 'mieterportal', False),
    ('/neu/stweg/', 'stweg', True),
    ('/neu/betreibungen/', 'betreibung', True),
    ('/neu/einstellungen/daten/import/', 'datenimport', False),
    ('/neu/einstellungen/daten/export/', 'datenexport', True),
)

#: Pfade, die im Lesemodus schreibend bleiben: Anmeldung und Sprache, das Konto
#: (Passwort, zweiter Faktor), das Abonnement selbst und der Export.
LESEMODUS_OFFEN = (
    '/login/', '/logout/', '/i18n/', '/konto/', '/neu/account/',
    '/neu/abonnement/', '/neu/einstellungen/daten/export/',
)


def modul_fuer_pfad(pfad):
    """(Merkmal, lesen_bleibt) für diesen Pfad, oder (None, False)."""
    for praefix, schluessel, lesen in PFAD_MODULE:
        if pfad.startswith(praefix):
            return schluessel, lesen
    return None, False


def merkmal_der_view(pfad):
    """Das Merkmal, an dem der Pfad hängt: aus der Tabelle oder vom Dekorator."""
    schluessel, _lesen = modul_fuer_pfad(pfad)
    if schluessel:
        return schluessel
    from django.urls import resolve
    try:
        return getattr(resolve(pfad.split('?')[0]).func, 'benoetigtes_merkmal', None)
    except Exception:                                    # noqa: BLE001 — unbekannter Pfad: nichts sperren
        return None


def lesemodus_offen(pfad):
    return any(pfad.startswith(p) for p in LESEMODUS_OFFEN)


def merkmal_name(schluessel):
    return str(FUNKTIONEN.get(schluessel) or MODULE.get(schluessel) or schluessel)


def _darf_upgraden(request):
    from core.auth import TEAM_ROLLEN, hat_rolle
    return hat_rolle(getattr(request, 'user', None), TEAM_ROLLEN)


def sperre_modul(request, schluessel):
    """Die Seite statt einer 403: sagt, was fehlt, und wo man es freischaltet."""
    return render(request, 'abo/sperre.html', {
        'art': 'modul', 'merkmal': merkmal_name(schluessel), 'schluessel': schluessel,
        'darf_upgraden': _darf_upgraden(request),
    }, status=402)


def sperre_lesemodus(request):
    return render(request, 'abo/sperre.html', {
        'art': 'lesemodus', 'darf_upgraden': _darf_upgraden(request),
    }, status=402)


def sperre_grenze(request, ausnahme):
    return render(request, 'abo/sperre.html', {
        'art': 'grenze', 'was': ausnahme.was, 'grenze': ausnahme.grenze,
        'darf_upgraden': _darf_upgraden(request),
    }, status=402)


def funktion_erforderlich(schluessel, lesen=False):
    """Hängt eine View an ein Merkmal. Steht INNERHALB von `rolle_erforderlich`.

    Reihenfolge: erst die Rolle (wer sie nicht hat, soll nicht erfahren, welche
    Stufe ihm fehlt), dann das Merkmal.
    """
    # Ein Tippfehler im Schlüssel soll beim Import auffallen, nicht erst beim
    # ersten Aufruf: der Aufruf wirft UnbekannteFunktion.
    hat_funktion(None, schluessel)

    def deko(view):
        @wraps(view)
        def gehuellt(request, *args, **kwargs):
            user = getattr(request, 'user', None)
            if (user is not None and user.is_superuser) or hat_funktion(aktuelle_organisation(), schluessel):
                return view(request, *args, **kwargs)
            if lesen and request.method in LESENDE_METHODEN:
                request.abo_modul_gesperrt = schluessel
                return view(request, *args, **kwargs)
            return sperre_modul(request, schluessel)
        gehuellt.benoetigtes_merkmal = schluessel
        return gehuellt
    return deko
