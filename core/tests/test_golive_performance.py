"""Go-Live-Härtetest, Schritt 3: Abfragezahl darf nicht mit den Zeilen wachsen."""
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext

from ._helfer import _basis_objekte, _team_user


class RollenCacheTests(TestCase):

    def test_hundert_rollenpruefungen_kosten_eine_abfrage(self):
        from core.auth import hat_rolle
        _basis_objekte()
        u = _team_user('Verwalter')
        u = type(u).objects.get(pk=u.pk)
        with CaptureQueriesContext(connection) as ctx:
            for _ in range(100):
                self.assertTrue(hat_rolle(u, ('Verwalter',)))
        self.assertLessEqual(len(ctx.captured_queries), 1, 'N+1: Rolle wird je Prüfung neu gelesen.')

    def test_rollenwechsel_wird_sofort_gesehen(self):
        from core.auth import hat_rolle
        from crm.models import Mitgliedschaft
        _basis_objekte()
        u = _team_user('Verwalter')
        self.assertTrue(hat_rolle(u, ('Verwalter',)))
        Mitgliedschaft.objects.filter(benutzer=u).delete()
        self.assertFalse(hat_rolle(u, ('Verwalter',)), 'Zwischenspeicher überlebt den Entzug der Rolle.')

    def test_vertragsliste_waechst_nicht_mit_den_zeilen(self):
        from datetime import date
        from decimal import Decimal
        from crm.models import Mieter
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user('Verwalter'))

        def messen():
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(c.get('/neu/vertraege/', secure=True).status_code, 200)
            return len(ctx.captured_queries)

        c.get('/neu/vertraege/', secure=True)
        wenig = messen()
        for i in range(25):
            ei = Einheit.objects.create(liegenschaft=lg, bezeichnung=f'W{i}', typ='whg',
                                        nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
            mi = Mieter.objects.create(typ='person', vorname='A', nachname=f'B{i}')
            Mietvertrag.objects.create(mieter=mi, einheit=ei, beginn=date(2024, 1, 1), status='aktiv',
                                       netto_mietzins=Decimal('1000'), nebenkosten=Decimal('100'))
        viel = messen()
        self.assertLessEqual(viel, wenig + 3, f'N+1: {wenig} → {viel} Abfragen bei 25 weiteren Verträgen.')
