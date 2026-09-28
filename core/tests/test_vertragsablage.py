"""Der Mietvertrag in der Akte bleibt, was verschickt wurde.

BEFUND (28.09.2026)
`_ablegen_vertragsdokument` suchte das vorhandene Dokument über (Objekt,
Titel) und hängte es auf den gerade erzeugten Vertrag um. Das PDF für den
NACHMIETER überschrieb damit den Mietvertrag des VORMIETERS und ordnete ihn
dem neuen Mieter zu — der Vormieter hatte danach kein Vertragsdokument mehr.

Zweitens überschrieben die Download-Views die abgelegte Fassung mit einem PDF
aus den aktuellen Vertragsdaten — schon durch blosses Ansehen, auch mit
Lesezugriff. Nach einer Vertragsänderung war die verschickte Fassung weg.

Gegenprobe: Mit dem alten `_ablegen_vertragsdokument` sind die ersten beiden
Tests rot.
"""
import shutil
import tempfile
from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings

from crm.models import Mieter
from rentals.models import Dokument, Mietvertrag
from core.tests._helfer import _basis_objekte, _team_user

MEDIA = tempfile.mkdtemp()


def _inhalt(dokument):
    dokument.refresh_from_db()
    with dokument.datei.open('rb') as f:
        return f.read()


@override_settings(MEDIA_ROOT=MEDIA)
class VertragsablageTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()

    def _mietvertrag(self, vertrag):
        return Dokument.objects.get(vertrag=vertrag, bezeichnung='Mietvertrag')

    def test_nachmieter_ueberschreibt_den_vormieter_nicht(self):
        self.v.status = 'beendet'
        self.v.ende = date(2025, 12, 31)
        self.v.save()
        neu_m = Mieter.objects.create(typ='person', vorname='Anna', nachname='Neu',
                                      strasse='Weg 1', plz='8000', ort='Zürich')
        neu_v = Mietvertrag.objects.create(mieter=neu_m, einheit=self.e, beginn=date(2026, 1, 1),
                                           netto_mietzins=Decimal('1600'),
                                           nebenkosten=Decimal('200'), status='aktiv')
        self.client.force_login(_team_user('Verwalter'))

        self.client.get(f'/vertrag/{self.v.pk}/pdf/')
        alt = self._mietvertrag(self.v)
        alt_inhalt = _inhalt(alt)
        self.client.get(f'/vertrag/{neu_v.pk}/pdf/')

        alt.refresh_from_db()
        self.assertEqual(alt.vertrag_id, self.v.pk, 'Das Dokument des Vormieters wurde umgehängt.')
        self.assertEqual(alt.mieter_id, self.m.pk)
        self.assertEqual(_inhalt(alt), alt_inhalt, 'Der Vertrag des Vormieters wurde überschrieben.')
        self.assertNotEqual(self._mietvertrag(neu_v).pk, alt.pk)

    def test_ansehen_ueberschreibt_die_abgelegte_fassung_nicht(self):
        from core.views.pdf import erzeuge_und_ablege_vertragspaket
        erzeuge_und_ablege_vertragspaket(self.v)            # wie bei der Vertragserstellung
        abgelegt = self._mietvertrag(self.v)
        vorher = _inhalt(abgelegt)

        self.v.netto_mietzins = Decimal('1750')             # späterer Nachtrag
        self.v.save()
        self.client.force_login(_team_user('Lesezugriff'))
        self.assertEqual(self.client.get(f'/vertrag/{self.v.pk}/pdf/').status_code, 200)
        self.client.get(f'/vertrag/{self.v.pk}/dokumente-zip/')

        self.assertEqual(_inhalt(abgelegt), vorher, 'Ansehen hat die abgelegte Fassung ersetzt.')
        self.assertEqual(Dokument.objects.filter(vertrag=self.v, bezeichnung='Mietvertrag').count(), 1)

    def test_ansehen_legt_an_was_fehlt(self):
        """Gegenstück: Die Akte füllt sich weiterhin beim ersten Erzeugen."""
        self.client.force_login(_team_user('Verwalter'))
        self.client.get(f'/vertrag/{self.v.pk}/pdf/')
        self.assertEqual(Dokument.objects.filter(vertrag=self.v, bezeichnung='Mietvertrag').count(), 1)

    def test_vertragserstellung_aktualisiert_ohne_duplikat(self):
        """Gegenstück: Der ausdrückliche Weg (Vertrag erstellen/neu versenden)
        ersetzt die Fassung weiterhin — ohne zweites Dokument."""
        from core.views.pdf import erzeuge_und_ablege_vertragspaket
        erzeuge_und_ablege_vertragspaket(self.v)
        abgelegt = self._mietvertrag(self.v)
        vorher = _inhalt(abgelegt)
        self.v.netto_mietzins = Decimal('1750')
        self.v.save()
        erzeuge_und_ablege_vertragspaket(self.v)
        self.assertNotEqual(_inhalt(abgelegt), vorher)
        self.assertEqual(Dokument.objects.filter(vertrag=self.v, bezeichnung='Mietvertrag').count(), 1)
