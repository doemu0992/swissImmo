"""Verschiebt bestehende Dateien unter `media/organisation/<id>/…`.

    python manage.py medien_umziehen --trocken     # nur anzeigen (Standard)
    python manage.py medien_umziehen --wirklich    # ausführen

Seit Etappe 6.5 legen neue Uploads ihre Datei unter `organisation/<id>/` ab.
Der Bestand liegt noch flach. Beides funktioniert — die Zugriffsregel liest die
Zugehörigkeit beim Präfix am Pfad ab und sieht sonst in der Datenbank nach —,
aber die Datenbankvariante kostet je Abruf bis zu 21 Abfragen (eine je
Dateifeld). Dieser Befehl zieht den Bestand nach.

DREI DINGE, DIE HIER SCHIEFGEHEN KÖNNEN, und was dagegen steht:

**Die Datei wird verschoben, das Feld nicht.** Dann zeigt der Datensatz ins
Leere und die Datei ist verloren, obwohl sie noch da ist. Deshalb: erst
kopieren, dann das Feld setzen, dann das Original löschen — und nur, wenn
beides gelang. Bricht es dazwischen ab, liegt die Datei doppelt; das ist
Speicherplatz, kein Datenverlust.

**Zwei Datensätze zeigen auf dieselbe Datei.** Kommt vor (dieselbe PDF an
Vertrag und Dokument). Der zweite fände sie nach dem Verschieben nicht mehr.
Deshalb wird je Quellpfad gemerkt, wohin er gewandert ist, und der zweite
Datensatz bekommt denselben neuen Pfad — ohne die Datei erneut zu bewegen.

**Ein Datensatz ohne Organisation.** Gibt es seit Etappe 5 nicht mehr, ausser
bei `crm.Vorlage` (Systemvorlagen, ohne Datei) — wird trotzdem geprüft und
übersprungen statt geraten.

Der Trockenlauf ist die Voreinstellung. Wer nichts angibt, verändert nichts.
"""
import os
import shutil

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import models


def dateifelder():
    """Alle `FileField`/`ImageField` im Projekt — aus der Registry."""
    for modell in apps.get_models():
        if modell._meta.app_label not in {'core', 'crm', 'finance', 'portfolio',
                                          'rentals', 'tickets', 'mietprozess'}:
            continue
        for feld in modell._meta.get_fields():
            if isinstance(feld, models.FileField):
                yield modell, feld.name


def organisation_von(datensatz):
    if type(datensatz).__name__ == 'Organisation':
        return datensatz.pk           # Logo/Unterschrift: sie IST der Mandant
    return getattr(datensatz, 'organisation_id', None)


class Command(BaseCommand):
    help = 'Verschiebt bestehende Medien unter organisation/<id>/ und zieht die Felder nach.'

    def add_arguments(self, parser):
        parser.add_argument('--wirklich', action='store_true',
                            help='Ausführen. Ohne diese Angabe passiert nichts.')

    def handle(self, *args, **optionen):
        trocken = not optionen['wirklich']
        if trocken:
            self.stdout.write(self.style.WARNING(
                '── TROCKENLAUF ── nichts wird verändert. Mit --wirklich ausführen.\n'))

        wurzel = settings.MEDIA_ROOT
        umgezogen = {}        # alter Pfad → neuer Pfad (fuer Mehrfachverweise)
        anzahl = uebersprungen = fehler = 0

        for modell, feldname in dateifelder():
            manager = getattr(modell, 'alle_organisationen', None) or modell._base_manager
            for datensatz in manager.exclude(**{feldname: ''}).exclude(**{f'{feldname}__isnull': True}):
                alt = str(getattr(datensatz, feldname))
                if not alt or alt.startswith('organisation/'):
                    continue

                org_id = organisation_von(datensatz)
                if org_id is None:
                    self.stdout.write(
                        f'· übersprungen (keine Organisation): {modell._meta.label} {alt}')
                    uebersprungen += 1
                    continue

                if alt in umgezogen:
                    # Zweiter Verweis auf dieselbe Datei — nur das Feld nachziehen.
                    neu = umgezogen[alt]
                else:
                    neu = f'organisation/{org_id}/{alt}'
                    quelle = os.path.join(wurzel, alt)
                    ziel = os.path.join(wurzel, neu)
                    if not os.path.exists(quelle):
                        self.stdout.write(self.style.WARNING(
                            f'⚠ Datei fehlt auf der Platte: {alt} ({modell._meta.label})'))
                        uebersprungen += 1
                        continue
                    if not trocken:
                        try:
                            os.makedirs(os.path.dirname(ziel), exist_ok=True)
                            # Erst kopieren, dann Feld setzen, dann Original weg.
                            # Bricht es dazwischen ab, liegt die Datei doppelt —
                            # Speicherplatz, kein Datenverlust.
                            shutil.copy2(quelle, ziel)
                        except OSError as e:
                            self.stderr.write(self.style.ERROR(f'✗ {alt}: {e}'))
                            fehler += 1
                            continue
                    umgezogen[alt] = neu

                if not trocken:
                    setattr(datensatz, feldname, neu)
                    datensatz.save(update_fields=[feldname])
                anzahl += 1
                self.stdout.write(f'  {alt}\n    → {neu}')

        # Originale erst ganz am Schluss — nach allen Feld-Aktualisierungen.
        if not trocken:
            for alt in umgezogen:
                quelle = os.path.join(wurzel, alt)
                if os.path.exists(quelle):
                    try:
                        os.remove(quelle)
                    except OSError as e:
                        self.stderr.write(self.style.WARNING(
                            f'⚠ Original blieb liegen: {alt} ({e})'))

        self.stdout.write('')
        self.stdout.write(f'{anzahl} Verweis(e) auf {len(umgezogen)} Datei(en), '
                          f'{uebersprungen} übersprungen, {fehler} Fehler.')
        if trocken and anzahl:
            self.stdout.write(self.style.WARNING(
                'Trockenlauf — mit --wirklich ausführen. Vorher eine Sicherung: '
                'python manage.py sicherung'))
