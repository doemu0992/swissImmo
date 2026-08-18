"""Der Medien-Umzug — und die zwei Fallen, die er auf der Produktion fand.

GEFUNDEN AM 18.08.2026, mitten im Lauf, nach zwei von zehn Dateien:

    OrganisationsFehler: crm.Eigentuemer.objects ohne gesetzte Organisation.

Der Befehl liest bewusst über `alle_organisationen` — er läuft ausserhalb jeder
Anfrage und soll alle Verwaltungen erfassen. Sein `save()` tat das nicht:
`crm.Eigentuemer.save` ruft `_unterschrift_aufbereiten`, und das liest über
`objects`, also über den TenantManager. Ohne Kontext wirft der.

DIE ZWEITE FALLE STEHT NICHT IM TRACEBACK und ist die gefährlichere. Wo der
Hook NICHT wirft — bei `crm.Organisation`, die keinen TenantManager hat —,
arbeitet er: Er vergleicht den neuen Feldwert mit dem in der Datenbank, hält
die Datei für frisch hochgeladen, rechnet den Hintergrund heraus und speichert
sie über `upload_to` unter einem NEUEN Namen. Das Feld landet dann irgendwo,
nur nicht unter `organisation/<id>/`. Der Befehl hätte gemeldet, was er nicht
getan hat — und ein Umzug, der Erfolg meldet und nichts bewegt, ist genau die
Sorte Fehler, gegen die die Prüfwerkzeuge dieses Projekts gebaut sind.

Beides hat dieselbe Ursache: **Ein Pfadwechsel ist kein neuer Upload.** Der
Befehl schreibt deshalb nur noch die Spalte (`.update()`), ohne `save()` und
ohne Signale.
"""
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from ._isolation import MandantenFixture


class MedienUmziehenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def setUp(self):
        self.medien = Path(tempfile.mkdtemp())

    def datei_anlegen(self, name, inhalt=b'x'):
        ziel = self.medien / name
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(inhalt)
        return ziel

    def png_anlegen(self, name):
        """Ein ECHTES PNG — der Unterschied ist prüfungsrelevant.

        `_unterschrift_aufbereiten` öffnet die Datei mit Pillow und schluckt
        jeden Fehler dabei. Mit einer Attrappe (`b'x'`) scheitert es still, der
        Hook tut nichts, und ein Test darüber prüft nichts. Erst mit einem
        lesbaren Bild zeigt sich, was der Hook wirklich anstellt.
        """
        import io

        from PIL import Image

        bild = Image.new('RGBA', (2, 2), (255, 255, 255, 255))
        puffer = io.BytesIO()
        bild.save(puffer, format='PNG')
        return self.datei_anlegen(name, puffer.getvalue())

    def umziehen(self, wirklich=True):
        raus = StringIO()
        with override_settings(MEDIA_ROOT=str(self.medien)):
            call_command('medien_umziehen', wirklich=wirklich, stdout=raus, stderr=raus)
        return raus.getvalue()

    # -- Falle 1: der Abbruch --------------------------------------------
    def test_ein_modell_mit_tenant_hook_im_save_bricht_nicht_ab(self):
        """`crm.Eigentuemer.save` liest über `objects` — ohne Kontext wirft das.

        Genau daran ist der Lauf auf der Produktion gescheitert. Der Test legt
        einen Eigentümer mit Unterschriftsbild an und verlangt, dass der Umzug
        durchläuft.
        """
        from crm.models import Eigentuemer

        self.png_anlegen('unterschriften/sig_alt.png')
        eig = Eigentuemer.alle_organisationen.filter(
            organisation=self.a.organisation).first()
        if eig is None:
            self.skipTest('Fixture hat keinen Eigentümer')
        Eigentuemer.alle_organisationen.filter(pk=eig.pk).update(
            unterschrift_bild='unterschriften/sig_alt.png')

        ausgabe = self.umziehen()      # darf NICHT werfen

        eig.refresh_from_db()
        self.assertEqual(eig.unterschrift_bild.name,
                         f'organisation/{self.a.organisation.pk}/unterschriften/sig_alt.png',
                         f'Feld nicht nachgezogen.\n{ausgabe}')

    # -- Falle 2: der stille Nichtumzug ----------------------------------
    def test_das_feld_zeigt_danach_wirklich_unter_organisation(self):
        """Der Hook darf die Datei nicht unter einem neuen Namen neu ablegen.

        Ohne `.update()` schrieb `_unterschrift_aufbereiten` sie über
        `upload_to` weg — der Befehl meldete den Umzug, das Feld zeigte
        woanders hin.
        """
        from crm.models import Organisation

        self.png_anlegen('unterschriften/sig_vw.png')
        Organisation.objects.filter(pk=self.a.organisation.pk).update(
            unterschrift_bild='unterschriften/sig_vw.png')

        self.umziehen()

        self.a.organisation.refresh_from_db()
        self.assertEqual(
            self.a.organisation.unterschrift_bild.name,
            f'organisation/{self.a.organisation.pk}/unterschriften/sig_vw.png',
            'Das Feld zeigt nicht unter organisation/<id>/ — der Umzug hat '
            'gemeldet, was er nicht getan hat.')

    # -- die Zusagen, die schon vorher galten ----------------------------
    def test_die_datei_liegt_danach_am_neuen_ort(self):
        from portfolio.models import Dokument

        self.datei_anlegen('dokumente/alt.pdf', b'%PDF-1.4')
        Dokument.objects.create(liegenschaft=self.a.liegenschaft, titel='X',
                                datei='dokumente/alt.pdf')

        self.umziehen()

        neu = self.medien / f'organisation/{self.a.organisation.pk}/dokumente/alt.pdf'
        self.assertTrue(neu.is_file(), 'Datei nicht am neuen Ort.')
        self.assertFalse((self.medien / 'dokumente/alt.pdf').exists(),
                         'Das Original blieb liegen.')

    def test_trockenlauf_veraendert_nichts(self):
        from portfolio.models import Dokument

        self.datei_anlegen('dokumente/alt.pdf', b'%PDF-1.4')
        dok = Dokument.objects.create(liegenschaft=self.a.liegenschaft, titel='X',
                                      datei='dokumente/alt.pdf')

        self.umziehen(wirklich=False)

        dok.refresh_from_db()
        self.assertEqual(dok.datei.name, 'dokumente/alt.pdf')
        self.assertTrue((self.medien / 'dokumente/alt.pdf').is_file())

    def test_zweiter_lauf_ist_ein_leerlauf(self):
        # Der Befehl muss wiederholbar sein — nach einem Abbruch wird er
        # erneut gestartet, und dann darf er das bereits Umgezogene nicht
        # noch einmal anfassen.
        from portfolio.models import Dokument

        self.datei_anlegen('dokumente/alt.pdf', b'%PDF-1.4')
        Dokument.objects.create(liegenschaft=self.a.liegenschaft, titel='X',
                                datei='dokumente/alt.pdf')
        self.umziehen()
        ausgabe = self.umziehen()
        self.assertIn('0 Verweis(e)', ausgabe)

    def test_zwei_datensaetze_auf_dieselbe_datei(self):
        # Der zweite fände sie nach dem Verschieben sonst nicht mehr.
        from portfolio.models import Dokument

        self.datei_anlegen('dokumente/geteilt.pdf', b'%PDF-1.4')
        a = Dokument.objects.create(liegenschaft=self.a.liegenschaft, titel='A',
                                    datei='dokumente/geteilt.pdf')
        b = Dokument.objects.create(liegenschaft=self.a.liegenschaft, titel='B',
                                    datei='dokumente/geteilt.pdf')

        self.umziehen()

        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.datei.name, b.datei.name)
        self.assertTrue((self.medien / a.datei.name).is_file())
