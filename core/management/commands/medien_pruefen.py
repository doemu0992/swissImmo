"""Zeigt jeder Dateiverweis in der Datenbank auf eine Datei, die es gibt?

    python manage.py medien_pruefen
    python manage.py medien_pruefen --streng                  # Exitcode 1 bei Funden
    python manage.py medien_pruefen --sicherung <medien.tar.gz>

WARUM ES DIESEN BEFEHL GIBT

Die Datenbank und die Dateien sind zwei getrennte Stände. `bestand_zaehlen`
vergleicht Zeilen, `pg_restore` stellt Zeilen her — beide sehen die Dateien
nicht. Eine Datenbank, die auf 165 Dokumente verweist, von denen 4 fehlen, ist
für jede Zählung fehlerfrei und für den Mieter, der sein Protokoll herunterladen
will, kaputt.

GEFUNDEN AM 18.08.2026 im Wiederherstellungs-Probelauf: 4 von 165 Verweisen
zeigten ins Leere (`schaden_fotos/2026-08-08/…`). Die Dateien fehlten **auch im
Original** — die Sicherung war also treu, der Bestand war es nicht. Genau diese
Unterscheidung leistet `--sicherung`:

    ohne Datei auf der Platte   → der Bestand hat einen toten Verweis
    auf der Platte, nicht im Tar → die SICHERUNG ist unvollständig

Der zweite Fall ist der gefährlichere, denn er fällt erst im Ernstfall auf.

WARUM ROHES SQL

Gelesen wird über `connection.cursor()`, nicht über die Modelle: Der
`TenantManager` filtert auf die aktuelle Verwaltung und wirft ohne gesetzten
Kontext. Ein Betriebsbefehl, der die Dateien EINER Verwaltung prüft und
„keine Funde" meldet, wäre schlimmer als keiner.
"""
import tarfile
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, models


class Command(BaseCommand):
    help = 'Prüft, ob jeder Dateiverweis der Datenbank eine Datei hat (optional gegen eine Sicherung).'

    def add_arguments(self, parser):
        parser.add_argument('--streng', action='store_true',
                            help='Bei Funden mit Code 1 enden (für Skripte).')
        parser.add_argument('--sicherung', metavar='TAR',
                            help='Zusätzlich gegen einen Medien-Sicherungsstand prüfen.')

    def handle(self, *args, **optionen):
        verweise = self._verweise_lesen()
        if not verweise:
            self.stdout.write('· Keine Dateiverweise in der Datenbank gefunden.')
            return

        medien = Path(settings.MEDIA_ROOT)
        tot = [(label, feld, pfad) for label, feld, pfad in verweise
               if not (medien / pfad).is_file()]

        im_tar = self._sicherungspfade(optionen['sicherung']) if optionen['sicherung'] else None
        fehlt_in_sicherung = []
        if im_tar is not None:
            fehlt_in_sicherung = [(label, feld, pfad) for label, feld, pfad in verweise
                                  if (medien / pfad).is_file() and pfad not in im_tar]

        eindeutig = {pfad for _, _, pfad in verweise}
        self.stdout.write(f'· {len(verweise)} Verweis(e) auf {len(eindeutig)} Datei(en) geprüft.')
        if im_tar is not None:
            self.stdout.write(f'· Sicherungsstand enthält {len(im_tar)} Datei(en).')

        if not tot and not fehlt_in_sicherung:
            self.stdout.write(self.style.SUCCESS('✓ Jeder Verweis zeigt auf eine vorhandene Datei.'))
            return

        if tot:
            self.stdout.write(self.style.ERROR(
                f'\n✗ {len(tot)} Verweis(e) zeigen ins Leere — die Datei fehlt auf der Platte:'))
            for label, feld, pfad in tot:
                self.stdout.write(f'  {label}.{feld}  →  {pfad}')
            self.stdout.write(
                '  Das ist ein Mangel im BESTAND, nicht in der Sicherung: Was nicht da ist,\n'
                '  kann auch nicht gesichert werden. Verweis leeren oder Datei beschaffen.')

        if fehlt_in_sicherung:
            self.stdout.write(self.style.ERROR(
                f'\n✗ {len(fehlt_in_sicherung)} Datei(en) sind vorhanden, fehlen aber in der Sicherung:'))
            for label, feld, pfad in fehlt_in_sicherung:
                self.stdout.write(f'  {label}.{feld}  →  {pfad}')
            self.stdout.write(
                '  DAS IST DER GEFÄHRLICHE FALL: Im Betrieb unauffällig, im Ernstfall weg.')

        if optionen['streng']:
            raise SystemExit(1)

    # ------------------------------------------------------------------
    def _verweise_lesen(self):
        """Alle nicht leeren Dateifelder aller Modelle — roh, ohne Mandantenfilter."""
        vorhanden = set(connection.introspection.table_names())
        verweise = []
        for modell in apps.get_models():
            if modell._meta.db_table not in vorhanden:
                continue
            felder = [f for f in modell._meta.get_fields()
                      if isinstance(f, models.FileField) and getattr(f, 'concrete', False)]
            if not felder:
                continue
            spalten = ', '.join('"%s"' % f.column for f in felder)
            try:
                with connection.cursor() as cur:
                    cur.execute('SELECT %s FROM "%s"' % (spalten, modell._meta.db_table))
                    zeilen = cur.fetchall()
            except Exception as fehler:                        # noqa: BLE001
                self.stderr.write(f'· {modell._meta.label} nicht lesbar: {fehler}')
                continue
            for zeile in zeilen:
                for feld, wert in zip(felder, zeile):
                    if wert:
                        verweise.append((modell._meta.label, feld.name, str(wert)))
        return verweise

    @staticmethod
    def _sicherungspfade(tar_pfad):
        """Dateipfade im Medien-Tar, relativ zu MEDIA_ROOT.

        `manage.py sicherung` packt den Medienordner mit seinem Namen als
        Wurzel (`media/…`). Beide Schreibweisen werden abgeräumt, damit die
        Prüfung nicht an einem Präfix scheitert und dann fälschlich ALLES als
        fehlend meldet — ein Fehlalarm über den ganzen Bestand ist so
        unbrauchbar wie gar keine Prüfung.
        """
        pfad = Path(tar_pfad)
        if not pfad.is_file():
            raise CommandError(f'Sicherungsstand nicht gefunden: {pfad}')
        wurzel = Path(settings.MEDIA_ROOT).name
        pfade = set()
        with tarfile.open(pfad, 'r:*') as tar:
            for eintrag in tar:
                if not eintrag.isfile():
                    continue
                name = eintrag.name.removeprefix('./')
                if name.startswith(wurzel + '/'):
                    name = name[len(wurzel) + 1:]
                pfade.add(name)
        return pfade
