# core/views/alte_adressen.py
"""Adressen, die es nicht mehr gibt und die nur noch weiterleiten.

Das «Dossier» (`/dossier/mieter|liegenschaft|vertrag/<id>/`) war eine zweite, veraltete
Oberfläche und ist in Etappe 3 entfallen. Lesezeichen und alte Mails führen jetzt in die
Akte. Die Weiterleitung ist wie jede Teamseite hinter der Rollenprüfung (ohne Anmeldung:
Login, als Mieter oder Eigentümer: 403); ob die Nummer zum eigenen Mandanten gehört,
entscheidet die Akte (fremde Nummer: 404).
"""
from django.shortcuts import redirect

from core.auth import TEAM_ROLLEN, rolle_erforderlich


@rolle_erforderlich(*TEAM_ROLLEN)
def dossier_mieter(request, pk):
    return redirect('fw_person_detail', pk=pk)


@rolle_erforderlich(*TEAM_ROLLEN)
def dossier_liegenschaft(request, pk):
    return redirect('fw_liegenschaft_detail', pk=pk)


@rolle_erforderlich(*TEAM_ROLLEN)
def dossier_vertrag(request, pk):
    return redirect('fw_vertrag_detail', pk=pk)
