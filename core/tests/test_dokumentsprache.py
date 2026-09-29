"""Dokumente folgen der Sprache des Empfängers (D11), nicht der Oberfläche.

Erster Schnitt (29.09.2026): Begleitbrief, Wohnungsausweis und Merkblatt
Lüften entstehen in der Korrespondenzsprache des Mieters (`Mieter.sprache`).
Dokumente mit Rechtstext bleiben Deutsch, bis ihr Wortlaut juristisch geprüft
übersetzt ist — auch dann, wenn die Sachbearbeitung französisch arbeitet.

Geprüft wird das HTML, das an die PDF-Erzeugung geht (xhtml2pdf): Dort steht
der Text, den der Mieter liest.

Gegenprobe: in core/services/dokument_service.py den Block
`with in_sprache(sprache):` entfernen (Rendern in der Oberflächensprache) —
`test_franzoesischer_mieter_bekommt_franzoesisch`,
`test_oberflaeche_franzoesisch_mieter_deutsch` und
`test_rechtstext_bleibt_deutsch` werden rot.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import translation

from core.services import dokument_service
from core.services.dokumentsprache import sprache_von
from core.tests._helfer import _basis_objekte


def _html(vertrag, doc_type):
    gefangen = {}

    def _create(html, dest, **_kw):
        gefangen['html'] = html
        return SimpleNamespace(err=0)

    with mock.patch.object(dokument_service.pisa, 'CreatePDF', side_effect=_create):
        dokument_service.generate_dokument_pdf_bytes(vertrag, doc_type)
    return gefangen['html']


class SpracheVonTests(SimpleTestCase):

    def test_hinterlegte_sprache(self):
        self.assertEqual(sprache_von(SimpleNamespace(sprache='fr')), 'fr')

    def test_leer_oder_unbekannt_heisst_deutsch(self):
        for wert in ('', None, 'xx', 'rm'):
            with self.subTest(wert=wert):
                self.assertEqual(sprache_von(SimpleNamespace(sprache=wert)), 'de')
        self.assertEqual(sprache_von(object()), 'de')


class DokumentFolgtDemMieterTests(TestCase):

    def setUp(self):
        _lg, _e, self.m, self.v = _basis_objekte()

    def _mieter_sprache(self, code):
        self.m.sprache = code
        self.m.save(update_fields=['sprache'])

    def test_franzoesischer_mieter_bekommt_franzoesisch(self):
        self._mieter_sprache('fr')
        html = _html(self.v, 'wohnungsausweis')
        self.assertIn('Fiche du logement', html)
        self.assertIn('lang="fr"', html)
        self.assertNotIn('Wohnungsausweis</h1>', html)
        brief = _html(self.v, 'begleitbrief')
        self.assertIn('Votre contrat de bail à signer', brief)
        self.assertIn('Avec nos meilleures salutations', brief)

    def test_oberflaeche_franzoesisch_mieter_deutsch(self):
        # Genau der Fall, den D11 regelt: Die Sachbearbeitung arbeitet
        # französisch, die Mieterin liest Deutsch.
        self._mieter_sprache('de')
        with translation.override('fr'):
            html = _html(self.v, 'merkblatt-lueften')
        self.assertIn('Richtig Lüften', html)
        self.assertNotIn('Aérer correctement', html)

    def test_rechtstext_bleibt_deutsch(self):
        # Hausordnung ist Vertragsbestandteil: bleibt Deutsch, und der
        # gemeinsame Rahmen (Fusszeile) darf nicht in die Oberflächensprache
        # rutschen — sonst entsteht ein Dokument in zwei Sprachen.
        self._mieter_sprache('fr')
        with translation.override('fr'):
            html = _html(self.v, 'hausordnung')
        self.assertIn('lang="de"', html)
        self.assertIn('erstellt am', html)
        self.assertNotIn('établi le', html)
