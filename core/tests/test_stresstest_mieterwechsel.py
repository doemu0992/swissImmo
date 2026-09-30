"""Stresstest 30.09.2026: Der Auszug als durchgehender Fall «Mieterwechsel»."""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user


class MieterwechselFallTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        call_command('fallarten_anlegen', verbosity=0)      # nach dem Anlegen der Organisation
        self.heute = date.today()
        self.c = Client(); self.c.force_login(_team_user('Verwalter'))

    def _kuendigen(self, **extra):
        d = {'absender': 'mieter', 'eingang_datum': self.heute.isoformat(), 'bestaetigen': 'on',
             'gewuenschtes_ende': (self.heute + timedelta(days=120)).isoformat()}
        d.update(extra)
        return self.c.post(f'/neu/vertraege/{self.v.id}/kuendigen/', d, secure=True)

    def _fall(self):
        from django.contrib.contenttypes.models import ContentType
        from faelle.models import Fall
        return Fall.objects.get(akte_typ=ContentType.objects.get_for_model(self.v), akte_id=self.v.pk,
                                fallart__schluessel='mieterwechsel')

    def _erledigt(self, fall):
        return {s.bezeichnung for s in fall.schritte.filter(erledigt_am__isnull=False)}

    def test_kuendigung_eroeffnet_den_fall_und_hakt_die_ersten_schritte_ab(self):
        from faelle.models import Fall
        self._kuendigen()
        fall = self._fall()
        self.assertEqual(fall.status, Fall.OFFEN)
        erledigt = self._erledigt(fall)
        self.assertIn('Kündigung erfassen, Termin prüfen', erledigt)
        self.assertIn('Kündigungsbestätigung versenden', erledigt)    # als bestätigt angelegt
        self.assertEqual(fall.fortschritt[0], 2)

    def test_ohne_eingerichtete_fallart_bleibt_es_bei_den_pendenzen(self):
        from faelle.models import Fall, Fallart
        Fallart.objects.all().delete()
        self._kuendigen()
        self.assertFalse(Fall.objects.exists())

    def test_zweite_kuendigung_eroeffnet_keinen_zweiten_fall(self):
        from faelle.models import Fall
        self._kuendigen()
        from core.services.mieterwechsel_fall import eroeffnen
        eroeffnen(self.v)
        self.assertEqual(Fall.objects.filter(fallart__schluessel='mieterwechsel').count(), 1)

    def test_ereignisse_haken_die_schritte_ab_und_der_fall_schliesst_sich(self):
        """Abnahme, Schlussabrechnung, Kaution, Nachmieter — dieselben Stichwörter wie die Pendenzen."""
        from core.services.automation import erledige_pendenzen_fuer
        from crm.models import Mieter
        from faelle.models import Fall
        from rentals.models import Mietvertrag
        self._kuendigen()
        erledige_pendenzen_fuer(self.v, ['Wohnungsabnahme', 'Abnahmetermin', 'Zählerstände', 'Schlüssel'])
        erledige_pendenzen_fuer(self.v, ['Schlussabrechnung', 'Kaution'])
        fall = self._fall()
        self.assertEqual(fall.status, Fall.OFFEN, 'Ohne Nachmieter sind Ausschreibung und Vertrag noch offen.')
        m2 = Mieter.objects.create(typ='person', vorname='N', nachname='M')
        Mietvertrag.objects.create(mieter=m2, einheit=self.e, beginn=self.heute + timedelta(days=121),
                                   status='aktiv', netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                                   kautions_betrag=Decimal('4500'))
        fall.refresh_from_db()
        # Noch offen: Die Kaution des Nachfolgers ist weder leer noch einbezahlt.
        self.assertEqual(fall.status, Fall.OFFEN)
        from core.services.mieterwechsel_fall import kaution_einbezahlt
        nachfolger = Mietvertrag.objects.get(mieter=m2)
        nachfolger.kautions_einbezahlt_am = self.heute; nachfolger.save()
        kaution_einbezahlt(nachfolger)
        fall.refresh_from_db()
        offen = [s.bezeichnung for s in fall.schritte.filter(pflicht=True, erledigt_am__isnull=True)]
        self.assertEqual(fall.status, Fall.ABGESCHLOSSEN, f'Noch offen: {offen}')
        self.assertIsNotNone(fall.abgeschlossen_am)

    def test_abgeschlossener_fall_erscheint_nicht_mehr_offen(self):
        from core.services.automation import erledige_pendenzen_fuer
        from faelle.models import Fall
        self._kuendigen()
        for s in self._fall().schritte.exclude(bezeichnung__startswith='Kaution abrechnen'):
            if s.erledigt_am is None:
                s.erledigen()
        erledige_pendenzen_fuer(self.v, ['Kaution'])      # letzter Pflichtschritt
        self.assertFalse(Fall.objects.offen().filter(fallart__schluessel='mieterwechsel').exists())

    def test_hoehere_miete_des_nachfolgers_laesst_die_anfangsmietzins_pruefung_offen(self):
        from crm.models import Mieter
        from rentals.models import Mietvertrag
        self._kuendigen()
        m2 = Mieter.objects.create(typ='person', vorname='N', nachname='M')
        Mietvertrag.objects.create(mieter=m2, einheit=self.e, beginn=self.heute + timedelta(days=121),
                                   status='aktiv', netto_mietzins=Decimal('1650'), nebenkosten=Decimal('200'))
        offen = {s.bezeichnung for s in self._fall().schritte.filter(erledigt_am__isnull=True)}
        self.assertIn('Anfangsmietzins prüfen', offen,
                      'Bei einer Erhöhung gegenüber dem Vormieter prüft ein Mensch die Formularpflicht.')
