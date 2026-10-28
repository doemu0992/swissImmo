"""Anschrift offener Kreditorenrechnungen nachtragen — vor dem 14.11.2026.

Die Zahlungsdatei verlangt ab dem Stichtag die Anschrift des Begünstigten
(Swiss Payment Standards 2026). Rechnungen, die vorher erfasst oder gescannt
wurden, haben keine. Dieser Befehl trägt sie nach, aber nur aus zwei
BELEGTEN Quellen, nie geraten:

1. dem Lieferantenprofil (die zuletzt freigegebene Anschrift desselben
   Lieferanten) und
2. dem QR-Code des gespeicherten Belegs — und zwar nur, wenn die IBAN im QR-Code
   mit der IBAN der Rechnung übereinstimmt und der Code eine strukturierte
   Anschrift («S») trägt.

Was sich so nicht klären lässt, bleibt leer; die Adressseite
(`/neu/kreditoren/<id>/adresse/`) und der Zahllauf zeigen es.

Aufruf:
    python manage.py kreditor_adressen_nachtragen --trocken       # nur anzeigen
    python manage.py kreditor_adressen_nachtragen                 # eintragen
    python manage.py kreditor_adressen_nachtragen --verwaltung 3  # eine Verwaltung
"""
import os

from django.core.management.base import BaseCommand

from core.services.iban import normalisiere_iban
from core.tenancy import organisation_kontext

OFFENE_STATUS = ['neu', 'freigegeben', 'in_zahlung', 'teilbezahlt']


class Command(BaseCommand):
    help = ('Trägt fehlende Anschriften offener Kreditorenrechnungen aus dem '
            'Lieferantenprofil und dem QR-Code des Belegs nach.')

    def add_arguments(self, parser):
        parser.add_argument('--trocken', action='store_true',
                            help='Nur anzeigen, nichts speichern.')
        parser.add_argument('--verwaltung', type=int, default=None,
                            help='Nur diese Organisations-ID bearbeiten.')

    def handle(self, *args, **options):
        from crm.models import Organisation
        organisationen = Organisation.objects.all()
        if options['verwaltung'] is not None:
            organisationen = organisationen.filter(pk=options['verwaltung'])
        gesamt = {'profil': 0, 'qr': 0, 'offen': 0}
        for organisation in organisationen:
            with organisation_kontext(organisation):
                z = self._verwaltung(organisation, trocken=options['trocken'])
            for schluessel in gesamt:
                gesamt[schluessel] += z[schluessel]
        self.stdout.write(
            f"{'Trocken: ' if options['trocken'] else ''}"
            f"{gesamt['profil']} aus dem Lieferantenprofil, {gesamt['qr']} aus dem QR-Code, "
            f"{gesamt['offen']} bleiben ohne Anschrift.")

    def _verwaltung(self, organisation, trocken):
        from finance.kreditor_adresse import adresse_setzen, aus_profil_uebernehmen
        from finance.models import KreditorenRechnung
        from finance.utils import BILD_ENDUNGEN, _qr_rechnung_dekodieren
        z = {'profil': 0, 'qr': 0, 'offen': 0}
        felder = [f'lieferant_{f}' for f in ('strasse', 'hausnummer', 'plz', 'ort', 'land')]
        self.stdout.write(f'{organisation}')
        for k in KreditorenRechnung.objects.filter(status__in=OFFENE_STATUS, lieferant_ort=''):
            if aus_profil_uebernehmen(k):
                z['profil'] += 1
                self.stdout.write(f'   #{k.id} {k.lieferant}: aus dem Lieferantenprofil ({k.lieferant_ort})')
                if not trocken:
                    k.save(update_fields=felder)
                continue
            adresse = self._aus_beleg(k, _qr_rechnung_dekodieren, BILD_ENDUNGEN)
            if adresse:
                z['qr'] += 1
                self.stdout.write(f'   #{k.id} {k.lieferant}: aus dem QR-Code ({adresse["ort"]})')
                if not trocken:
                    adresse_setzen(k, adresse)
                    k.save(update_fields=felder)
                continue
            z['offen'] += 1
            self.stdout.write(self.style.WARNING(f'   #{k.id} {k.lieferant or "(ohne Namen)"}: keine Anschrift gefunden'))
        return z

    @staticmethod
    def _aus_beleg(k, dekodieren, bild_endungen):
        """Anschrift aus dem QR-Code des Belegs — nur bei übereinstimmender IBAN."""
        if not k.beleg_scan or not k.iban:
            return None
        try:
            pfad = k.beleg_scan.path
        except (ValueError, NotImplementedError):
            return None
        if not os.path.exists(pfad):
            return None
        endung = os.path.splitext(pfad)[1].lower()
        if endung not in bild_endungen and endung != '.pdf':
            return None
        qr = dekodieren(pfad, endung)
        if not qr or not qr.get('adresse'):
            return None
        if normalisiere_iban(qr.get('iban')) != normalisiere_iban(k.iban):
            return None
        return qr['adresse']
