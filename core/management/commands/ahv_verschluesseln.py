"""Verschlüsselt AHV-Nummern, die noch im Klartext in der Datenbank stehen.

Nötig, wenn `IMAP_SCHLUESSEL` beim Einspielen der Migration
`crm.0046_ahv_nummer_verschluesselt` noch nicht gesetzt war. Idempotent.
"""
from django.core.management.base import BaseCommand, CommandError

from core.services.geheimnis import schluessel_vorhanden, verschluesseln
from core.verschluesselt import sieht_verschluesselt_aus


class Command(BaseCommand):
    help = 'AHV-Nummern im Klartext verschlüsseln (alle Verwaltungen).'

    def handle(self, *args, **opts):
        if not schluessel_vorhanden():
            raise CommandError('IMAP_SCHLUESSEL ist nicht gesetzt.')
        from crm.models import Mieter
        n = 0
        # Betreiber-Werkzeug über alle Verwaltungen; Rohwerte, kein Entschlüsseln.
        qs = Mieter.alle_organisationen.exclude(ahv_nummer='').values_list('pk', 'ahv_nummer')
        for pk, wert in list(qs):
            if wert and not sieht_verschluesselt_aus(wert):
                Mieter.alle_organisationen.filter(pk=pk).update(ahv_nummer=verschluesseln(wert))
                n += 1
        self.stdout.write(self.style.SUCCESS(f'{n} AHV-Nummer(n) verschlüsselt.'))
