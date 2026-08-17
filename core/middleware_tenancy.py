"""Setzt die Organisation je Anfrage aus dem angemeldeten Benutzer.

Die Organisation kommt aus der `Mitgliedschaft` (Etappe 4.1), nicht aus einem
Feld am Benutzer und schon gar nicht aus dem Request. Ein Wert aus `?org=`
wäre keine Isolation, sondern eine Einladung.

DREI FÄLLE, DIE NICHT DER NORMALFALL SIND
-----------------------------------------
**Anonyme Anfragen.** Anmeldeseite, Bewerbungsformular, DocuSeal-Webhook,
statische Dateien. Hier bleibt der Kontext leer. Das ist richtig: Wer nicht
angemeldet ist, hat keine Organisation, und jeder Zugriff auf Mandantendaten
soll dann werfen statt zu liefern.

**Portal-Konten** (Mieter, Eigentümer). Sie haben keine Mitgliedschaft — das
ist Absicht (siehe `crm.Mitgliedschaft`). Ihre Organisation ergibt sich aus
dem Datensatz, an dem sie hängen: `Mieter.vertraege…liegenschaft.organisation`
bzw. `Eigentuemer` → Liegenschaften. Solange Etappe 5 die Bezüge nicht
nachgerüstet hat, wird der Kontext hier über die Liegenschaft aufgelöst.

**Mehrere Mitgliedschaften.** Heute hat niemand mehr als eine; sobald es
vorkommt, braucht es eine Auswahl in der Oberfläche und einen Wert in der
Session. Bis dahin nimmt die Middleware die älteste und protokolliert es —
stillschweigend die erstbeste zu nehmen wäre der Fall, in dem jemand
irgendwann in der falschen Organisation arbeitet, ohne es zu merken.
"""
import logging

from core.tenancy import loesche_organisation, setze_organisation

logger = logging.getLogger(__name__)

#: Schlüssel in der Session, falls später eine Auswahl dazukommt.
SESSION_SCHLUESSEL = 'aktive_organisation_id'


def _organisation_fuer(benutzer, session=None):
    """Die Organisation dieses Benutzers, oder `None`."""
    from crm.models import Mitgliedschaft

    mitgliedschaften = list(
        Mitgliedschaft.objects.filter(benutzer=benutzer)
        .select_related('organisation').order_by('pk')[:5])

    if mitgliedschaften:
        if len(mitgliedschaften) > 1 and session is not None:
            gewaehlt = session.get(SESSION_SCHLUESSEL)
            for m in mitgliedschaften:
                if m.organisation_id == gewaehlt:
                    return m.organisation
            logger.info(
                'Benutzer %s ist in %d Organisationen, keine gewählt — nimmt die älteste (%s). '
                'Eine Auswahl in der Oberfläche fehlt noch.',
                benutzer.pk, len(mitgliedschaften), mitgliedschaften[0].organisation_id)
        return mitgliedschaften[0].organisation

    # Portal-Konten: über den Datensatz, an dem sie hängen.
    profil = getattr(benutzer, 'eigentuemer_profil', None)
    if profil is not None:
        lg = profil.liegenschaften.select_related('organisation').first()
        if lg is not None:
            return lg.organisation

    profil = getattr(benutzer, 'mieter_profil', None)
    if profil is not None:
        from rentals.models import Mietvertrag
        # `alle_organisationen` (Etappe 6.2, hier vorgemerkt seit 4.3): Der
        # Kontext steht in DIESER Zeile ja gerade noch nicht fest — sie ist es,
        # die ihn bestimmt. Das ist genau der Anmeldefall, für den der benannte
        # Weg an der Isolation vorbei gedacht ist.
        vertrag = (Mietvertrag.alle_organisationen
                   .filter(mieter=profil)
                   .select_related('einheit__liegenschaft__organisation')
                   .order_by('-id').first())
        if vertrag is not None and vertrag.einheit_id:
            return vertrag.einheit.liegenschaft.organisation
    return None


class OrganisationMiddleware:
    """Setzt und räumt den Mandantenkontext je Anfrage.

    Der Kontext wird im `finally` gelöscht, nicht am Ende des Erfolgspfads:
    Eine Ausnahme im View darf die Organisation nicht in den nächsten
    Durchlauf mitnehmen. Bei wiederverwendeten Worker-Threads wäre das ein
    Datenleck mit Zeitverzögerung — dieselbe Klasse Fehler wie ein geteilter
    Cache-Key.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            benutzer = getattr(request, 'user', None)
            if benutzer is not None and benutzer.is_authenticated:
                organisation = _organisation_fuer(
                    benutzer, getattr(request, 'session', None))
                if organisation is not None:
                    setze_organisation(organisation)
                request.organisation = organisation
            else:
                request.organisation = None
            return self.get_response(request)
        finally:
            loesche_organisation()
