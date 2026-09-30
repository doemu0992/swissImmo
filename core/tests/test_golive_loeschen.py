"""Go-Live-Härtetest, Schritt 2: Löschlogik, Löschsperren und verwaiste Daten."""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user


class LoeschschutzTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.v.status = 'archiviert'; self.v.aktiv = False; self.v.save()
        self.c = Client(); self.c.force_login(_team_user('Verwalter'))

    def _rechnung(self, status='offen'):
        from finance.models import DebitorenRechnung
        return DebitorenRechnung.objects.create(
            vertrag=self.v, liegenschaft=self.lg, einheit=self.e, betrag=Decimal('500'),
            datum=date(2024, 3, 1), faellig_am=date(2024, 3, 31), status=status, titel='Miete')

    def _ticket(self, status='neu'):
        from tickets.models import SchadenMeldung
        return SchadenMeldung.objects.create(liegenschaft=self.lg, betroffene_einheit=self.e,
                                             titel='Leck', status=status)

    def test_mieter_mit_offener_rechnung_wird_nicht_geloescht(self):
        from crm.models import Mieter
        from core.loeschschutz import LoeschSperre
        r = self._rechnung()
        resp = self.c.post(f'/neu/personen/{self.m.id}/loeschen/', secure=True)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Mieter.objects.filter(pk=self.m.pk).exists(), 'Mieter trotz offener Rechnung gelöscht.')
        with self.assertRaises(LoeschSperre):
            self.m.delete()
        r.refresh_from_db()
        self.assertEqual(r.vertrag_id, self.v.id)

    def test_mieter_ohne_offene_posten_wird_geloescht_die_buchhaltung_bleibt(self):
        from crm.models import Mieter
        from finance.models import DebitorenRechnung
        r = self._rechnung('bezahlt')
        self.c.post(f'/neu/personen/{self.m.id}/loeschen/', secure=True)
        self.assertFalse(Mieter.objects.filter(pk=self.m.pk).exists())
        self.assertTrue(DebitorenRechnung.objects.filter(pk=r.pk).exists(), 'Beleg muss bleiben (Art. 958f OR).')

    def test_gekuendigter_vertrag_sperrt_das_loeschen_der_person(self):
        from crm.models import Mieter
        self.v.status = 'gekuendigt'; self.v.save()
        self.c.post(f'/neu/personen/{self.m.id}/loeschen/', secure=True)
        self.assertTrue(Mieter.objects.filter(pk=self.m.pk).exists())

    def test_vertrag_mit_offener_rechnung_wird_nicht_geloescht(self):
        from rentals.models import Mietvertrag
        self._rechnung()
        self.c.post(f'/neu/vertraege/{self.v.id}/loeschen/', secure=True)
        self.assertTrue(Mietvertrag.objects.filter(pk=self.v.pk).exists())

    def test_liegenschaft_mit_offener_rechnung_oder_ticket_wird_nicht_geloescht(self):
        from portfolio.models import Liegenschaft
        r = self._rechnung()
        self.c.post(f'/neu/liegenschaften/{self.lg.id}/loeschen/', secure=True)
        self.assertTrue(Liegenschaft.objects.filter(pk=self.lg.pk).exists(), 'offene Rechnung')
        r.status = 'bezahlt'; r.save()
        t = self._ticket()
        self.c.post(f'/neu/liegenschaften/{self.lg.id}/loeschen/', secure=True)
        self.assertTrue(Liegenschaft.objects.filter(pk=self.lg.pk).exists(), 'offenes Ticket')

    def test_einheit_mit_offener_rechnung_wird_nicht_geloescht(self):
        from core.loeschschutz import LoeschSperre
        self._rechnung()
        with self.assertRaises(LoeschSperre):
            self.e.delete()

    def test_saubere_liegenschaft_hinterlaesst_keine_verwaisten_daten(self):
        from portfolio.models import Einheit, Zaehler
        from rentals.models import Mietvertrag
        from tickets.models import SchadenMeldung
        self._rechnung('bezahlt')
        self._ticket('erledigt')
        self.c.post(f'/neu/liegenschaften/{self.lg.id}/loeschen/', secure=True)
        self.assertEqual(Einheit.objects.filter(pk=self.e.pk).count(), 0)
        self.assertEqual(Mietvertrag.objects.filter(pk=self.v.pk).count(), 0)
        self.assertEqual(SchadenMeldung.objects.count(), 0)

    def test_fall_geht_mit_dem_vertrag(self):
        from django.contrib.contenttypes.models import ContentType
        from django.core.management import call_command
        from faelle.models import Fall, Fallart
        call_command('fallarten_anlegen', verbosity=0)
        art = Fallart.objects.first()
        Fall.objects.create(fallart=art, akte_typ=ContentType.objects.get_for_model(self.v), akte_id=self.v.pk)
        self.assertEqual(Fall.objects.count(), 1)
        self.v.delete()
        self.assertEqual(Fall.objects.count(), 0, 'Fall ohne Akte bleibt zurück.')
