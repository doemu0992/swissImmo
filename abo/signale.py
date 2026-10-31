"""Mengengrenzen beim ANLEGEN, an einer Stelle für alle Wege.

Ein `pre_save`-Empfänger je begrenztem Modell, der nur NEUE Datensätze prüft.
So greift die Grenze in der Oberfläche, im Datenimport, in Management-Commands
und in der Admin gleichermassen — eine Prüfung pro Anlegeansicht wäre an der
vergessenen Ansicht lückenhaft.

Bestehende Datensätze sind nie betroffen: Speichern, Ändern und Lesen eines
vorhandenen Datensatzes geht immer (`_state.adding` ist dort False).
"""
from django.db.models.signals import pre_save
from django.dispatch import receiver

from crm.models import Mitgliedschaft
from portfolio.models import Einheit

from abo.dienst import pruefe_anlegen


@receiver(pre_save, sender=Einheit, dispatch_uid='abo_grenze_einheit')
def _grenze_einheit(sender, instance, raw=False, **kwargs):
    if raw or not instance._state.adding:
        return
    pruefe_anlegen(instance.organisation_id, 'einheiten')


@receiver(pre_save, sender=Mitgliedschaft, dispatch_uid='abo_grenze_nutzer')
def _grenze_nutzer(sender, instance, raw=False, **kwargs):
    if raw or not instance._state.adding:
        return
    pruefe_anlegen(instance.organisation_id, 'nutzer')
