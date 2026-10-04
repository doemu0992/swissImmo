"""Tests des STWEG-Moduls."""
from decimal import Decimal

from django.test import TestCase

from core.tests._helfer import _test_organisation
from portfolio.models import Einheit, Liegenschaft
from stweg.validierung import WertquotenFehler, pruefe_wertquoten


def neue_stweg(name='Sonnenblick', quoten=(200, 300, 500), total=1000, status='entwurf'):
    """STWEG als Entwurf mit Einheiten; Status wird erst danach gesetzt."""
    lg = Liegenschaft.objects.create(
        strasse=f'{name}weg 1', plz='8000', ort='Zürich', typ='STWEG',
        status='entwurf', wertquote_total=total, organisation=_test_organisation())
    einheiten = [
        Einheit.objects.create(liegenschaft=lg, bezeichnung=f'Whg {i + 1}', typ='stwe',
                               wertquote=Decimal(q))
        for i, q in enumerate(quoten)]
    if status != 'entwurf':
        lg.status = status
        lg.save()
    return lg, einheiten


class WertquotenValidierungTests(TestCase):
    def test_999_von_1000_blockiert_aktivierung(self):
        lg, _ = neue_stweg(quoten=(200, 300, 499))
        lg.status = 'aktiv'
        with self.assertRaises(WertquotenFehler) as ctx:
            lg.save()
        self.assertIn('999/1000', str(ctx.exception))
        lg.refresh_from_db()
        self.assertEqual(lg.status, 'entwurf')      # nichts gespeichert

    def test_1001_von_1000_blockiert_ebenfalls(self):
        lg, _ = neue_stweg(quoten=(200, 300, 501))
        lg.status = 'aktiv'
        with self.assertRaises(WertquotenFehler):
            lg.save()

    def test_exakt_1000_wird_aktiv(self):
        lg, _ = neue_stweg(quoten=(200, 300, 500))
        lg.status = 'aktiv'
        lg.save()
        lg.refresh_from_db()
        self.assertEqual(lg.status, 'aktiv')

    def test_anderer_nenner_100(self):
        lg, _ = neue_stweg(quoten=(20, 30, 50), total=100)
        lg.status = 'aktiv'
        lg.save()

    def test_neue_stweg_nicht_direkt_aktiv(self):
        with self.assertRaises(WertquotenFehler):
            Liegenschaft.objects.create(
                strasse='X 1', plz='8000', ort='Zürich', typ='STWEG', status='aktiv',
                organisation=_test_organisation())

    def test_mietliegenschaft_wird_nicht_geprueft(self):
        lg = Liegenschaft.objects.create(
            strasse='Miete 1', plz='8000', ort='Zürich', organisation=_test_organisation())
        Einheit.objects.create(liegenschaft=lg, bezeichnung='A', typ='whg')   # Quote Default 10
        lg.save()
        pruefe_wertquoten(lg)                       # wirft nicht
        self.assertEqual((lg.typ, lg.status), ('MIETE', 'aktiv'))

    def test_entwurf_darf_unvollstaendig_sein(self):
        lg, _ = neue_stweg(quoten=(200, 300))
        lg.save()                                   # Entwurf: keine Prüfung
