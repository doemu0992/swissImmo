"""Hinweis im Kopf der Oberfläche: Zahlung überfällig, Lesemodus, Modul gesperrt.

Kostet keine Abfrage: Das Abonnement wird mit der Organisation geladen
(`core/middleware_tenancy.py`, `select_related`).
"""
from datetime import timedelta

from django.conf import settings

from core.funktionen import ZUSTAND_AKTIV, ZUSTAND_LESEMODUS, abonnement_von


def abo_hinweis(request):
    """Der Hinweis; ein Fehler hier darf nie eine Seite verhindern (wie `fw_badges`)."""
    try:
        return _hinweis(request)
    except Exception:                                    # noqa: BLE001 — z. B. beschädigte Transaktion beim Fehlerseiten-Rendern
        return {}


def _hinweis(request):
    if not request.path_info.startswith('/neu/'):
        return {}
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    from core.tenancy import aktuelle_organisation
    organisation = aktuelle_organisation()
    hinweis = {}
    modul = getattr(request, 'abo_modul_gesperrt', None)
    if modul:
        from abo.zugang import merkmal_name
        hinweis['modul'] = merkmal_name(modul)
    abo = abonnement_von(organisation)
    if abo is not None and abo.zustand != ZUSTAND_AKTIV:
        hinweis['zustand'] = abo.zustand
        hinweis['lesemodus'] = abo.zustand == ZUSTAND_LESEMODUS
        if abo.ueberfaellig_seit:
            hinweis['lesemodus_ab'] = abo.ueberfaellig_seit + timedelta(days=settings.ABO_LESEMODUS_NACH_TAGEN)
    return {'abo_hinweis': hinweis} if hinweis else {}
