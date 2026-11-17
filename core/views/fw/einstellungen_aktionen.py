# core/views/fw/einstellungen_aktionen.py
#
# Einstellungen-Hub und Mandantenwechsel.
# Aus aktionen.py herausgeloest (reiner Umzug ohne Aenderung am Code).


from django.shortcuts import render
from django.utils.translation import gettext as _

from core.auth import (rolle_erforderlich, TEAM_ROLLEN)


from ._basis import (_global_filter)


# ══════════════════════════════════════════════════════════════
# UI-MODUS (Einfach/Profi) + EINSTELLUNGEN-HUB
# ══════════════════════════════════════════════════════════════
@rolle_erforderlich(*TEAM_ROLLEN)
def fw_einstellungen(request):
    """Zentrale Einstellungen-Seite — bündelt die früheren 8 Profil-Dropdown-
    Punkte (Account, Abonnement, Benutzer, Logbuch, Vorlagen, Integrationen,
    Rechtsgrundlagen) als eine Hub-Seite mit Sektionen."""
    basis = _global_filter(request)
    # Dieselbe Quelle wie das Feld der Schiene (`core/navigation.py`). Was die Rolle nicht öffnen darf (Logbuch, Archiv …),
    # führte in die 403 (DESIGN-07): Die Rollen werden einmal gelesen, nicht je Eintrag.
    from core.auth import darf_oeffnen, eigene_rollen
    from core.navigation import einstellungen_gruppen
    meine = eigene_rollen(request.user)
    gruppen = []
    for g in einstellungen_gruppen():
        eintraege = [k for k in g['eintraege'] if darf_oeffnen(request.user, k['url'], meine)]
        if eintraege:
            gruppen.append(dict(g, eintraege=eintraege))
    return render(request, 'fw/einstellungen.html', {
        **basis, 'nav': 'einstellungen', 'gruppen': gruppen,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mandant_wechseln(request):
    """Wechselt die aktive Organisation — nur in eine eigene.

    WARUM ES DAS BRAUCHT (E1.2)

    `crm.Mitgliedschaft` erlaubt seit Etappe 4.1 mehrere Organisationen je
    Person; die Middleware liest dafür längst einen Sessionwert. Was fehlte,
    war die Auswahl: Wer für zwei Verwaltungen arbeitet, landete immer in der
    ältesten. Die Middleware protokolliert das seither bei jeder Anfrage —
    ein Hinweis, den niemand liest.

    DER HEIKLE TEIL

    Dieser View setzt den Mandantenkontext. Ein POST mit einer fremden
    Organisations-ID darf ihn NICHT setzen, sonst ist die gesamte
    Mandantentrennung mit einem Formularfeld auszuhebeln — sie hängt an
    genau diesem Wert.

    Geprüft wird deshalb nicht «gibt es diese Organisation?», sondern «hat
    DIESER Benutzer dort eine Mitgliedschaft?». `alle_organisationen` ist hier
    richtig und nicht etwa der Fehler: Die Abfrage bestimmt den Kontext erst,
    kann ihn also nicht voraussetzen — deshalb ist sie auf `benutzer` und
    `organisation_id` zugleich eingeschränkt.

    ZWEITE SCHICHT: `core.middleware_tenancy._organisation_fuer` ehrt den
    Sessionwert ohnehin nur, wenn er zu einer echten Mitgliedschaft passt.
    Wird eine Mitgliedschaft später entzogen, greift der alte Sessionwert
    also nicht mehr. Das ist Absicht — die obere Schicht umgeht irgendwann
    jemand.

    Bei einer unbekannten oder fremden ID passiert nichts: keine Änderung,
    keine Fehlermeldung, die verrät, ob es die Organisation gibt.
    """
    from django.shortcuts import redirect
    from crm.models import Mitgliedschaft
    from core.middleware_tenancy import SESSION_SCHLUESSEL

    if request.method == 'POST':
        try:
            gewuenscht = int(request.POST.get('organisation') or 0)
        except (TypeError, ValueError):
            gewuenscht = 0
        if gewuenscht and Mitgliedschaft.alle_organisationen.filter(
                benutzer=request.user, organisation_id=gewuenscht).exists():
            request.session[SESSION_SCHLUESSEL] = gewuenscht
            # Der globale Liegenschaftsfilter braucht hier nichts: Er steht im
            # URL-Parameter `?lg=`, nicht in der Session (`_basis._global_filter`).
            # Die Umleitung auf `/neu/` laesst ihn ohnehin fallen.

    return redirect('/neu/')
