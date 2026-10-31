"""Setzt das Abonnement an jeder Anfrage durch: Module und Lesemodus.

Läuft NACH `OrganisationMiddleware` (sie setzt den Kontext) und der Anmeldung.
Anonyme Anfragen (Anmeldung, Bewerbung, Webhooks) gehen ungeprüft durch: Sie
haben keine Verwaltung, an die ein Abonnement hängen könnte.

Superuser sind ausgenommen (Notfallzugang, wie in `hat_rolle`).

Der Lesemodus sperrt nur Mitglieder der Verwaltung. Mieter und Eigentümer sind
nicht die Zahlenden: Wer eine Schadenmeldung absetzt, soll nicht für einen
Zahlungsverzug der Verwaltung büssen.
"""
from core.funktionen import FunktionGesperrt, GrenzeErreicht, darf_schreiben, hat_funktion
from core.tenancy import aktuelle_organisation

from abo import zugang


class AboMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated or user.is_superuser:
            return None
        organisation = aktuelle_organisation()
        if organisation is None:
            return None

        schluessel, lesen = zugang.modul_fuer_pfad(request.path_info)
        if schluessel and not hat_funktion(organisation, schluessel):
            if lesen and request.method in zugang.LESENDE_METHODEN:
                request.abo_modul_gesperrt = schluessel
            else:
                return zugang.sperre_modul(request, schluessel)

        if (request.method not in zugang.LESENDE_METHODEN
                and not darf_schreiben(organisation)
                and not zugang.lesemodus_offen(request.path_info)
                and self._ist_mitglied(user, organisation)):
            return zugang.sperre_lesemodus(request)
        return None

    @staticmethod
    def _ist_mitglied(user, organisation):
        from crm.models import Mitgliedschaft
        return Mitgliedschaft.objects.filter(benutzer=user, organisation=organisation).exists()

    def process_exception(self, request, exception):
        if isinstance(exception, FunktionGesperrt):
            return zugang.sperre_modul(request, exception.schluessel)
        if isinstance(exception, GrenzeErreicht):
            return zugang.sperre_grenze(request, exception)
        return None
