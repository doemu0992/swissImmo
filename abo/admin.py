"""Abonnement und Abo-Rechnungen im Admin: nur zur Ansicht (core/admin_base.py).

Eingestellt wird über `manage.py abo_einstellen`, abgerechnet über
`manage.py abo_abrechnung`.
"""
from django.contrib import admin

from core.admin_base import NurLesenModelAdmin

from abo.models import AboRechnung, Abonnement


@admin.register(Abonnement)
class AbonnementAdmin(NurLesenModelAdmin):
    list_display = ('organisation', 'zustand', 'uneingeschraenkt', 'abrechnung_ab', 'abgerechnet_bis')
    list_filter = ('zustand', 'uneingeschraenkt')

    def get_queryset(self, request):
        # Der Admin sieht per Definition alle Verwaltungen (core/admin_base.py).
        return Abonnement.alle_organisationen.select_related('organisation')


@admin.register(AboRechnung)
class AboRechnungAdmin(NurLesenModelAdmin):
    list_display = ('nummer', 'organisation', 'periode_von', 'periode_bis', 'brutto', 'status', 'faellig_am')
    list_filter = ('status',)

    def get_queryset(self, request):
        return AboRechnung.alle_organisationen.select_related('organisation')
