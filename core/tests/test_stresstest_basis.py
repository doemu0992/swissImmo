"""Stresstest 30.09.2026, Punkt 9: Ein neuer Vertrag startet mit dem Stand von heute."""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _test_organisation, _team_user


class NeuerVertragBasisTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        org = _test_organisation()
        org.aktueller_referenzzinssatz = Decimal('1.00')
        org.aktueller_lik_punkte = Decimal('108.4')
        org.save()
        # Stand der Einheit vom Tag ihrer Erfassung — veraltet.
        self.e.ref_zinssatz = Decimal('1.25'); self.e.lik_punkte = Decimal('107.1')
        self.e.save()

    def test_vertragsentwurf_aus_bewerbung_nimmt_den_aktuellen_stand(self):
        from mietprozess.models import Mietbewerbung
        from rentals.models import Mietvertrag
        self.e.zur_ausschreibung = True; self.e.save()
        b = Mietbewerbung.objects.create(einheit=self.e, vorname='Nora', nachname='Neu',
                                         email='nora@example.ch', status='neu',
                                         geburtsdatum=date(1990, 1, 1))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        v = Mietvertrag.objects.get(einheit=self.e, status='entwurf')
        self.assertEqual(v.basis_referenzzinssatz, Decimal('1.00'),
                         'Der Nachmieter startet mit dem veralteten Satz der Einheit.')
        self.assertEqual(v.basis_lik_punkte, Decimal('108.4'))

    def test_helfer_faellt_nicht_auf_einen_festen_wert_zurueck(self):
        from core.views.fw.mietprozess import _aktuelle_basis
        from portfolio.models import Einheit
        frisch = Einheit.objects.select_related('liegenschaft').get(pk=self.e.pk)
        zins, lik = _aktuelle_basis(frisch)
        self.assertEqual(zins, Decimal('1.00'))
        self.assertEqual(lik, Decimal('108.4'))
