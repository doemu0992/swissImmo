"""Etappe 6.5 — Dateien: nur für die Verwaltung, der sie gehören.

DER BEFUND, um den es hier geht: `geschuetzte_media` prüfte bis 6.5 genau eine
Sache — „ist im Team". In **welchem** Team, stand nirgends. Jedes angemeldete
Team-Mitglied konnte damit jede geschützte Datei abrufen, sofern es den Pfad
kannte, und die Pfade sind ratbar (Ordner, Datum, Dateiname).

Was dort liegt, ist nicht beliebig: Ausweiskopien, Betreibungsauszüge und
Lohnausweise von Mietbewerbern, Wohnungsaufnahmen aus Schadenmeldungen,
gescannte Verträge.

Zwei Mechanismen schliessen das:

1. **Das Pfad-Präfix** `organisation/<id>/` bei neuen Dateien — daran lässt
   sich die Zugehörigkeit ohne Datenbankabfrage ablesen.
2. **Der Rückgriff auf die Datenbank** für den Alt-Bestand: nachsehen, welcher
   Datensatz auf die Datei zeigt.

Lässt sich die Zugehörigkeit nicht bestimmen, wird **verweigert**. Bei einer
Datei, deren Besitzer niemand kennt, ist das die einzige vertretbare Antwort.
"""
import os
import shutil

from django.conf import settings
from django.test import Client, TestCase

from crm.models import Organisation

from ._isolation import MandantenFixture


def _datei_anlegen(rel, inhalt=b'\xff\xd8\xff\xe0JFIF-Testbild'):
    pfad = os.path.join(settings.MEDIA_ROOT, rel)
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, 'wb') as fh:
        fh.write(inhalt)
    return pfad


class MedienBasis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        assert Organisation.objects.order_by('pk').first().pk == cls.a.organisation.pk

    def tearDown(self):
        shutil.rmtree(os.path.join(settings.MEDIA_ROOT, 'organisation'), ignore_errors=True)
        shutil.rmtree(os.path.join(settings.MEDIA_ROOT, 'schaden_fotos'), ignore_errors=True)


class ZugehoerigkeitTests(MedienBasis):
    """Der eigentliche Schutz: Team allein genügt nicht."""

    def setUp(self):
        self.rel_b = f'organisation/{self.b.organisation.pk}/schaden_fotos/2026-01-01/bad.jpg'
        _datei_anlegen(self.rel_b)

    def test_die_eigene_verwaltung_bekommt_die_datei(self):
        c = Client()
        c.force_login(self.b.benutzer)
        self.assertEqual(c.get('/media/' + self.rel_b).status_code, 200)

    def test_die_fremde_verwaltung_bekommt_404(self):
        # Der Kern. Vorher: 200, weil „im Team" die ganze Prüfung war.
        c = Client()
        c.force_login(self.a.benutzer)
        self.assertEqual(
            c.get('/media/' + self.rel_b).status_code, 404,
            'Ein Team-Mitglied von A hat die Schadenaufnahme von B bekommen.')

    def test_anonym_bekommt_404(self):
        self.assertEqual(Client().get('/media/' + self.rel_b).status_code, 404)


class SensibilitaetTrotzPraefixTests(MedienBasis):
    """Die Falle, in die das Präfix beim Einbau geführt hat.

    Die Sensibilität wird am ORDNER abgelesen (`schaden_fotos/`, `dokumente/`).
    Das Präfix `organisation/<id>/` schiebt sich davor — ohne Abziehen begänne
    kein Pfad mehr mit einem sensiblen Ordner, die Prüfung liefe ins Leere, und
    jedes Bild wäre über seine Endung **anonym** abrufbar.

    Der Fehler war beim ersten Lauf sofort da und wurde von
    `test_fremder_bekommt_schadenfoto_nicht` gefangen. Dieser Testsatz hält ihn
    fest, damit er beim nächsten Umbau am Pfad nicht zurückkommt.
    """

    def test_schadenfoto_bleibt_sensibel_auch_mit_praefix(self):
        from core.views.media_protected import ist_oeffentlich
        self.assertFalse(
            ist_oeffentlich(f'organisation/{self.b.organisation.pk}/schaden_fotos/x.jpg'),
            'Mit Präfix gilt das Schadenfoto als öffentlich — die Ordnerprüfung '
            'greift dann nicht mehr.')

    def test_gegenprobe_ohne_praefix_ebenso(self):
        # Ohne diese Gegenprobe wäre nicht belegt, dass die Funktion das
        # Präfix behandelt und nicht schlicht alles als sensibel meldet.
        from core.views.media_protected import ist_oeffentlich
        self.assertFalse(ist_oeffentlich('schaden_fotos/x.jpg'))

    def test_objektfoto_bleibt_oeffentlich_auch_mit_praefix(self):
        # Die Gegenrichtung: Inserat-Bilder müssen anonym abrufbar bleiben,
        # sonst zeigt kein Portal mehr ein Bild.
        from core.views.media_protected import ist_oeffentlich
        self.assertTrue(
            ist_oeffentlich(f'organisation/{self.b.organisation.pk}/objekt_fotos/inserat.jpg'))

    def test_praefix_abziehen(self):
        from core.views.media_protected import ohne_organisationspraefix
        self.assertEqual(ohne_organisationspraefix('organisation/7/dokumente/a.pdf'),
                         'dokumente/a.pdf')
        # Kein Präfix, und auch kein falsch erkanntes: `organisation` ohne Zahl
        # dahinter ist ein gewöhnlicher Ordnername.
        self.assertEqual(ohne_organisationspraefix('dokumente/a.pdf'), 'dokumente/a.pdf')
        self.assertEqual(ohne_organisationspraefix('organisation/abc/a.pdf'),
                         'organisation/abc/a.pdf')


class AltbestandTests(MedienBasis):
    """Dateien ohne Präfix: Die Zugehörigkeit kommt aus der Datenbank."""

    def test_datei_ohne_datensatz_bekommt_niemand(self):
        # Fail closed. Eine Datei, deren Besitzer niemand kennt, darf nicht
        # deshalb für alle offen sein, weil sie alt ist.
        rel = 'schaden_fotos/2026-01-01/verwaist.jpg'
        _datei_anlegen(rel)
        c = Client()
        c.force_login(self.b.benutzer)
        self.assertEqual(c.get('/media/' + rel).status_code, 404)

    def test_altdatei_mit_datensatz_geht_an_die_richtige_verwaltung(self):
        from tickets.models import SchadenFoto

        from core.tenancy import organisation_kontext
        rel = 'schaden_fotos/2026-01-01/alt.jpg'
        _datei_anlegen(rel)
        with organisation_kontext(self.b.organisation):
            SchadenFoto.objects.create(schaden=self.b.schaden, bild=rel)

        eigen = Client(); eigen.force_login(self.b.benutzer)
        self.assertEqual(eigen.get('/media/' + rel).status_code, 200,
                         'Die eigene Verwaltung kommt an ihre Altdatei nicht heran.')

        fremd = Client(); fremd.force_login(self.a.benutzer)
        self.assertEqual(fremd.get('/media/' + rel).status_code, 404,
                         'Eine fremde Verwaltung bekommt die Altdatei.')


class AblagepfadTests(MedienBasis):
    """Neue Dateien landen unter der Organisation, die sie hochlädt."""

    def test_pfad_traegt_die_organisation(self):
        from core.tenancy import organisation_kontext
        from core.utils import get_smart_upload_path
        from tickets.models import SchadenFoto

        foto = SchadenFoto(schaden=self.b.schaden)
        with organisation_kontext(self.b.organisation):
            pfad = get_smart_upload_path(foto, 'bild.jpg')
        self.assertTrue(pfad.startswith(f'organisation/{self.b.organisation.pk}/'), pfad)
        self.assertIn('schaden_fotos', pfad)

    def test_ohne_kontext_und_ohne_bezug_bleibt_der_alte_pfad(self):
        # Kein Raten: Ohne bestimmbare Organisation entsteht der Pfad wie
        # bisher. Die Zugriffsregel behandelt ihn dann als sensibel und sieht
        # in der Datenbank nach.
        from core.tenancy import ohne_organisation
        from core.utils import get_smart_upload_path
        from tickets.models import SchadenFoto

        with ohne_organisation():
            pfad = get_smart_upload_path(SchadenFoto(), 'bild.jpg')
        self.assertFalse(pfad.startswith('organisation/'), pfad)


class UmzugsbefehlTests(MedienBasis):
    """`medien_umziehen` — der Teil, der Produktivdaten anfasst."""

    def _foto(self, fixture, rel):
        from tickets.models import SchadenFoto

        from core.tenancy import organisation_kontext
        _datei_anlegen(rel)
        with organisation_kontext(fixture.organisation):
            return SchadenFoto.objects.create(schaden=fixture.schaden, bild=rel)

    def test_trockenlauf_veraendert_nichts(self):
        # Die Voreinstellung. Wer nichts angibt, riskiert nichts.
        from io import StringIO

        from django.core.management import call_command
        foto = self._foto(self.b, 'schaden_fotos/2026-01-01/t.jpg')
        call_command('medien_umziehen', stdout=StringIO())
        foto.refresh_from_db()
        self.assertEqual(str(foto.bild), 'schaden_fotos/2026-01-01/t.jpg')
        self.assertTrue(os.path.exists(
            os.path.join(settings.MEDIA_ROOT, 'schaden_fotos/2026-01-01/t.jpg')))

    def test_umzug_verschiebt_datei_und_zieht_das_feld_nach(self):
        from io import StringIO

        from django.core.management import call_command
        foto = self._foto(self.b, 'schaden_fotos/2026-01-01/w.jpg')
        call_command('medien_umziehen', wirklich=True, stdout=StringIO())

        foto.refresh_from_db()
        erwartet = f'organisation/{self.b.organisation.pk}/schaden_fotos/2026-01-01/w.jpg'
        self.assertEqual(str(foto.bild), erwartet,
                         'Das Feld zeigt noch auf den alten Pfad — der Verweis läuft ins Leere.')
        self.assertTrue(os.path.exists(os.path.join(settings.MEDIA_ROOT, erwartet)),
                        'Die Datei liegt nicht am neuen Ort.')
        self.assertFalse(
            os.path.exists(os.path.join(settings.MEDIA_ROOT,
                                        'schaden_fotos/2026-01-01/w.jpg')),
            'Das Original blieb liegen.')

    def test_zwei_verweise_auf_dieselbe_datei(self):
        # Kommt vor (dieselbe PDF an Vertrag und Dokument). Der zweite
        # Datensatz fände die Datei nach dem Verschieben nicht mehr, wenn der
        # Befehl sie nicht je Quellpfad merkte.
        from io import StringIO

        from django.core.management import call_command
        rel = 'schaden_fotos/2026-01-01/geteilt.jpg'
        eins = self._foto(self.b, rel)
        from tickets.models import SchadenFoto

        from core.tenancy import organisation_kontext
        with organisation_kontext(self.b.organisation):
            zwei = SchadenFoto.objects.create(schaden=self.b.schaden, bild=rel)

        call_command('medien_umziehen', wirklich=True, stdout=StringIO())
        eins.refresh_from_db(); zwei.refresh_from_db()
        self.assertEqual(str(eins.bild), str(zwei.bild))
        self.assertTrue(os.path.exists(os.path.join(settings.MEDIA_ROOT, str(zwei.bild))))

    def test_danach_greift_die_zugehoerigkeitspruefung_am_pfad(self):
        # Der Zweck des Umzugs: Die Zugehörigkeit steht danach im Pfad und
        # kostet keine Datenbankabfrage mehr.
        from io import StringIO

        from django.core.management import call_command
        self._foto(self.b, 'schaden_fotos/2026-01-01/z.jpg')
        call_command('medien_umziehen', wirklich=True, stdout=StringIO())
        neu = f'organisation/{self.b.organisation.pk}/schaden_fotos/2026-01-01/z.jpg'

        eigen = Client(); eigen.force_login(self.b.benutzer)
        self.assertEqual(eigen.get('/media/' + neu).status_code, 200)
        fremd = Client(); fremd.force_login(self.a.benutzer)
        self.assertEqual(fremd.get('/media/' + neu).status_code, 404)
