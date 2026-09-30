"""Stresstest 30.09.2026, Punkte 11, 12, 14, 15, 16 sowie die Ticket-Eskalation."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from ._helfer import _basis_objekte, _seed_konten, _team_user
from django.contrib.auth import get_user_model

User = get_user_model()


class LeerstandTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()

    def _nachmieter(self, beginn, status='aktiv'):
        from crm.models import Mieter
        from rentals.models import Mietvertrag
        m2 = Mieter.objects.create(typ='person', vorname='Neu', nachname='Mieter')
        return Mietvertrag.objects.create(mieter=m2, einheit=self.e, beginn=beginn, status=status,
                                          netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'))

    def test_aktiver_nachmieter_beendet_den_leerstand(self):
        from rentals.models import Leerstand
        l = Leerstand.objects.create(einheit=self.e, beginn=date(2026, 3, 1), grund='mietersuche')
        self._nachmieter(date(2026, 4, 1))
        l.refresh_from_db()
        self.assertEqual(l.ende, date(2026, 3, 31), 'Leerstand läuft trotz neuem Vertrag weiter.')

    def test_entwurf_beendet_den_leerstand_nicht(self):
        from rentals.models import Leerstand
        l = Leerstand.objects.create(einheit=self.e, beginn=date(2026, 3, 1))
        self._nachmieter(date(2026, 4, 1), status='entwurf')
        l.refresh_from_db()
        self.assertIsNone(l.ende)

    def test_leerstand_ab_mietbeginn_entfaellt(self):
        from rentals.models import Leerstand
        Leerstand.objects.create(einheit=self.e, beginn=date(2026, 4, 1))
        self._nachmieter(date(2026, 4, 1))
        self.assertFalse(Leerstand.objects.filter(einheit=self.e).exists(),
                         'Ein Leerstand ohne Dauer bleibt mit umgekehrten Daten stehen.')

    def test_bereits_beendeter_leerstand_bleibt_unberuehrt(self):
        from rentals.models import Leerstand
        l = Leerstand.objects.create(einheit=self.e, beginn=date(2026, 1, 1), ende=date(2026, 1, 31))
        self._nachmieter(date(2026, 4, 1))
        l.refresh_from_db()
        self.assertEqual(l.ende, date(2026, 1, 31))

    def test_leerstand_anderer_einheit_bleibt(self):
        from portfolio.models import Einheit
        from rentals.models import Leerstand
        e2 = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='Andere', typ='whg')
        l = Leerstand.objects.create(einheit=e2, beginn=date(2026, 3, 1))
        self._nachmieter(date(2026, 4, 1))
        l.refresh_from_db()
        self.assertIsNone(l.ende)


class PendenzenTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = date.today()

    def _kuendigen(self, **extra):
        c = Client(); c.force_login(_team_user('Verwalter'))
        d = {'absender': 'mieter', 'eingang_datum': self.heute.isoformat(), 'bestaetigen': 'on',
             'gewuenschtes_ende': (self.heute + timedelta(days=120)).isoformat(),
             'leerstand_anlegen': 'on'}
        d.update(extra)
        return c.post(f'/neu/vertraege/{self.v.id}/kuendigen/', d, secure=True)

    def test_bestaetigte_kuendigung_schliesst_die_bestaetigungs_pendenz(self):
        from core.models import Pendenz
        self._kuendigen()
        p = Pendenz.objects.get(vertrag=self.v, titel__icontains='schriftlich bestätigen')
        self.assertTrue(p.erledigt, 'Kündigung ist als bestätigt angelegt, die Pendenz bleibt offen.')

    def test_unbestaetigte_kuendigung_laesst_sie_offen(self):
        from core.models import Pendenz
        c = Client(); c.force_login(_team_user('Verwalter'))
        c.post(f'/neu/vertraege/{self.v.id}/kuendigen/',
               {'absender': 'mieter', 'eingang_datum': self.heute.isoformat(),
                'gewuenschtes_ende': (self.heute + timedelta(days=120)).isoformat()}, secure=True)
        p = Pendenz.objects.get(vertrag=self.v, titel__icontains='schriftlich bestätigen')
        self.assertFalse(p.erledigt)

    def test_nachmieter_schliesst_die_nachmieter_pendenz_des_vorgaengers(self):
        from core.models import Pendenz
        from crm.models import Mieter
        from rentals.models import Mietvertrag
        self._kuendigen()
        p = Pendenz.objects.get(vertrag=self.v, titel__icontains='Nachmieter')
        self.assertFalse(p.erledigt)
        m2 = Mieter.objects.create(typ='person', vorname='N', nachname='M')
        Mietvertrag.objects.create(mieter=m2, einheit=self.e, beginn=self.heute + timedelta(days=121),
                                   status='aktiv', netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'))
        p.refresh_from_db()
        self.assertTrue(p.erledigt, 'Die Nachmietersuche steht trotz aktivem Nachmieter offen.')

    def test_auszugs_sammelpendenz_wird_nach_ruecknahme_erledigt(self):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        from rentals.models import Abnahmeprotokoll
        self.v.status = 'gekuendigt'; self.v.ende = self.heute - timedelta(days=2); self.v.save()
        Pendenz.objects.create(titel='Auszug X', quelle=f'auto:auszug:{self.v.pk}', vertrag=self.v,
                               kategorie='vertrag', faellig_am=self.heute)
        Abnahmeprotokoll.objects.create(vertrag=self.v, typ='auszug', datum=self.heute - timedelta(days=2))
        generate_auto_pendenzen(horizont_tage=30)
        self.assertTrue(Pendenz.objects.get(quelle=f'auto:auszug:{self.v.pk}').erledigt)


class AuftragTicketTests(TestCase):

    def setUp(self):
        from crm.models import Handwerker
        from tickets.models import HandwerkerAuftrag, SchadenMeldung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.t = SchadenMeldung.objects.create(titel='Heizung', liegenschaft=self.lg,
                                               betroffene_einheit=self.e, status='in_bearbeitung')
        self.a = HandwerkerAuftrag.objects.create(ticket=self.t, handwerker=Handwerker.objects.create(firma='HLK AG'))

    def test_erledigtes_ticket_schliesst_den_auftrag(self):
        self.assertEqual(self.a.status, 'offen')
        self.t.status = 'erledigt'; self.t.save()
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, 'erledigt', 'Auftrag bleibt «offen» bei erledigtem Ticket.')

    def test_offenes_ticket_laesst_den_auftrag_offen(self):
        self.t.status = 'warte_auf_handwerker'; self.t.save()
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, 'offen')

    def test_ticket_ohne_bewegung_erzeugt_eine_pendenz_und_erledigt_sie_wieder(self):
        """Wasserschaden 83 Tage «in Bearbeitung», keine Warnung."""
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        from tickets.models import SchadenMeldung
        SchadenMeldung.objects.filter(pk=self.t.pk).update(aktualisiert_am=timezone.now() - timedelta(days=83))
        generate_auto_pendenzen(horizont_tage=30)
        p = Pendenz.objects.get(quelle=f'auto:ticket:{self.t.pk}')
        self.assertIn('83 Tagen', p.titel)
        self.assertFalse(p.erledigt)
        self.t.refresh_from_db(); self.t.status = 'erledigt'; self.t.save()
        generate_auto_pendenzen(horizont_tage=30)
        p.refresh_from_db()
        self.assertTrue(p.erledigt)

    def test_junges_ticket_erzeugt_keine_pendenz(self):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        generate_auto_pendenzen(horizont_tage=30)
        self.assertFalse(Pendenz.objects.filter(quelle__startswith='auto:ticket:').exists())


class KautionDatumTests(TestCase):

    def setUp(self):
        _seed_konten()
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client(); self.c.force_login(_team_user('Verwalter'))

    def _einzahlung(self, datum):
        return self.c.post(f'/neu/vertraege/{self.v.id}/kaution/',
                           {'aktion': 'einzahlung', 'einbezahlt_am': datum.isoformat()}, secure=True)

    def test_einzahlung_in_der_zukunft_wird_abgewiesen(self):
        from finance.models import Buchung
        self._einzahlung(date.today() + timedelta(days=3))
        self.assertFalse(Buchung.objects.filter(beleg_text__startswith='Mietkaution').exists())

    def test_einzahlung_heute_geht(self):
        from finance.models import Buchung
        self._einzahlung(date.today())
        self.assertTrue(Buchung.objects.filter(beleg_text__startswith='Mietkaution').exists())

    def test_rueckdatierung_in_den_vormonat_wird_gewarnt_aber_gebucht(self):
        from finance.models import Buchung
        vormonat = date.today().replace(day=1) - timedelta(days=1)
        r = self._einzahlung(vormonat)
        self.assertTrue(Buchung.objects.filter(beleg_text__startswith='Mietkaution').exists())
        texte = [str(m) for m in r.wsgi_request._messages]
        self.assertTrue(any('Vormonat' in t for t in texte), texte)


class PortalGekuendigtTests(TestCase):

    def test_gekuendigter_mieter_kann_einen_schaden_melden(self):
        from tickets.models import SchadenMeldung
        lg, e, m, v = _basis_objekte()
        v.status = 'gekuendigt'; v.ende = date.today() + timedelta(days=60); v.save()
        u = User.objects.create_user(username='gk', password='x')
        m.benutzer = u; m.save()
        c = Client(); c.force_login(u)
        r = c.post('/mieter/schaden/', {'titel': 'Storen klemmt', 'beschreibung': 'Storen am Wohnzimmer'})
        self.assertEqual(r.status_code, 302)
        t = SchadenMeldung.objects.filter(titel='Storen klemmt').first()
        self.assertIsNotNone(t, 'Ein gekündigter Mieter kann keinen Schaden mehr melden.')
        self.assertEqual(t.betroffene_einheit_id, e.pk)
