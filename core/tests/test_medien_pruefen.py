"""Die Medienprüfung — entstanden im Wiederherstellungs-Probelauf vom 18.08.2026.

Der Probelauf hat gezeigt, dass Zeilenzahlen die eine Hälfte der Wahrheit sind.
`bestand_zaehlen` meldete «Bestand identisch — 67 Modelle, 3067 Datensätze», und
gleichzeitig zeigten 4 von 165 Dateiverweisen ins Leere. Für jede Zählung war
das ein fehlerfreier Stand.

Zwei Fälle, die dieser Befehl auseinanderhält — und die man auseinanderhalten
MUSS, weil sie verschiedene Ursachen haben:

  · Verweis ohne Datei auf der Platte  → der Bestand hat einen toten Verweis
  · Datei da, aber nicht im Sicherungs-Tar → die SICHERUNG ist unvollständig

Der zweite Fall ist der gefährliche: im Betrieb unauffällig, im Ernstfall weg.
"""
import tarfile
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from ._isolation import MandantenFixture


class MedienPruefenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def setUp(self):
        self.medien = Path(tempfile.mkdtemp())
        self._fixture_dateien_anlegen()

    def _fixture_dateien_anlegen(self):
        """Die Dateien anlegen, auf die `MandantenFixture` bereits verweist.

        Ohne das schlagen die «sauber»-Tests an der Fixture selbst an: Sie legt
        `portfolio.Dokument` und `rentals.Dokument` mit Verweisen an, ohne
        Dateien dazu. Beim ersten Lauf war genau das der Befund — ein
        unfreiwilliger Beleg, dass der Befehl findet, was er finden soll.
        """
        from django.apps import apps
        from django.db import connection, models

        for modell in apps.get_models():
            felder = [f for f in modell._meta.get_fields()
                      if isinstance(f, models.FileField) and getattr(f, 'concrete', False)]
            if not felder:
                continue
            spalten = ', '.join('"%s"' % f.column for f in felder)
            with connection.cursor() as cur:
                cur.execute('SELECT %s FROM "%s"' % (spalten, modell._meta.db_table))
                zeilen = cur.fetchall()
            for zeile in zeilen:
                for wert in zeile:
                    if wert:
                        ziel = self.medien / str(wert)
                        ziel.parent.mkdir(parents=True, exist_ok=True)
                        ziel.write_bytes(b'x')

    def pruefen(self, **optionen):
        raus = StringIO()
        with override_settings(MEDIA_ROOT=str(self.medien)):
            call_command('medien_pruefen', stdout=raus, stderr=raus, **optionen)
        return raus.getvalue()

    def _dokument_mit_datei(self, name='dokumente/probe.pdf', anlegen=True):
        """Legt einen Datensatz mit Dateiverweis an — die Datei wahlweise nicht."""
        from portfolio.models import Dokument

        if anlegen:
            ziel = self.medien / name
            ziel.parent.mkdir(parents=True, exist_ok=True)
            ziel.write_bytes(b'%PDF-1.4 Probe')
        return Dokument.objects.create(
            liegenschaft=self.a.liegenschaft, titel='Probe', datei=name)

    # -- der gute Fall ------------------------------------------------
    def test_vollstaendiger_bestand_meldet_nichts(self):
        self._dokument_mit_datei()
        self.assertIn('Jeder Verweis zeigt auf eine vorhandene Datei', self.pruefen())

    # -- Fall 1: toter Verweis ----------------------------------------
    def test_verweis_ohne_datei_wird_gefunden(self):
        self._dokument_mit_datei(name='dokumente/fehlt.pdf', anlegen=False)
        ausgabe = self.pruefen()
        self.assertIn('zeigen ins Leere', ausgabe)
        self.assertIn('dokumente/fehlt.pdf', ausgabe)
        self.assertIn('portfolio.Dokument', ausgabe)

    def test_streng_endet_mit_fehlercode(self):
        self._dokument_mit_datei(name='dokumente/fehlt.pdf', anlegen=False)
        with self.assertRaises(SystemExit):
            self.pruefen(streng=True)

    def test_ohne_streng_kein_fehlercode(self):
        self._dokument_mit_datei(name='dokumente/fehlt.pdf', anlegen=False)
        self.pruefen()   # wirft nicht

    # -- Fall 2: Datei da, Sicherung unvollständig --------------------
    def _tar_mit(self, *pfade):
        tar_datei = self.medien.parent / 'medien.tar.gz'
        with tarfile.open(tar_datei, 'w:gz') as tar:
            for p in pfade:
                quelle = self.medien / p
                tar.add(str(quelle), arcname=f'{self.medien.name}/{p}')
        return str(tar_datei)

    def test_datei_fehlt_in_der_sicherung(self):
        self._dokument_mit_datei(name='dokumente/wichtig.pdf')
        leer = self.medien.parent / 'leer.tar.gz'
        with tarfile.open(leer, 'w:gz'):
            pass
        ausgabe = self.pruefen(sicherung=str(leer))
        self.assertIn('fehlen aber in der Sicherung', ausgabe)
        self.assertIn('dokumente/wichtig.pdf', ausgabe)

    def test_gegenprobe_vollstaendige_sicherung_schweigt(self):
        # Ohne diese Gegenprobe wäre nicht belegt, dass die Prüfung das
        # Tar-Präfix richtig abräumt — sonst meldete sie IMMER alles als
        # fehlend, und ein Fehlalarm über den ganzen Bestand ist so
        # unbrauchbar wie gar keine Prüfung.
        self._dokument_mit_datei(name='dokumente/wichtig.pdf')
        alle = [str(p.relative_to(self.medien))
                for p in self.medien.rglob('*') if p.is_file()]
        with override_settings(MEDIA_ROOT=str(self.medien)):
            tar = self._tar_mit(*alle)
        ausgabe = self.pruefen(sicherung=tar)
        self.assertIn('Jeder Verweis zeigt auf eine vorhandene Datei', ausgabe)
        self.assertNotIn('fehlen aber in der Sicherung', ausgabe)

    def test_fehlender_sicherungsstand_ist_ein_fehler(self):
        # Still weiterlaufen wäre hier das Schlimmste: Der Aufrufer glaubte,
        # gegen einen Stand geprüft zu haben.
        self._dokument_mit_datei()
        with self.assertRaises(CommandError):
            self.pruefen(sicherung='/gibt/es/nicht/medien.tar.gz')

    # -- der Grund für rohes SQL --------------------------------------
    def test_prueft_ohne_gesetzten_mandantenkontext(self):
        """Der Befehl läuft im Betrieb ohne Anmeldung — also ohne Kontext.

        Über `Modell.objects` würde der TenantManager werfen oder still auf
        eine Verwaltung filtern. Ein Betriebsbefehl, der die Dateien EINER
        Verwaltung prüft und «keine Funde» meldet, wäre schlimmer als keiner.
        """
        from core.tenancy import aktuelle_organisation

        self._dokument_mit_datei(name='dokumente/fehlt.pdf', anlegen=False)
        self.assertIsNone(aktuelle_organisation(),
                          'Der Test setzt beiläufig einen Kontext — dann prüft er das Falsche.')
        self.assertIn('dokumente/fehlt.pdf', self.pruefen())
