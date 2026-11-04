"""Pendenz «Termin offen» (tickets/termin_pendenz.py): anlegen, nicht doppeln, selbst schliessen, je Verwaltung."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from core.models import Pendenz
from core.services.automation import generate_auto_pendenzen
from core.tenancy import organisation_kontext
from tickets.models import HandwerkerAuftrag, SchadenMeldung, TicketNachricht
from tickets.termin_pendenz import QUELLE, TERMIN_OFFEN_TAGE

from ._helfer import vor_tagen
from ._isolation import MandantenFixture


def _altern(fix, tage, **felder):
    """Den Auftrag der Verwaltung `fix` um `tage` Tage zurückdatieren (auto_now_add) und Felder setzen."""
    with organisation_kontext(fix.organisation):
        HandwerkerAuftrag.objects.filter(pk=fix.auftrag.pk).update(beauftragt_am=vor_tagen(tage), **felder)


def _setze(fix, **felder):
    with organisation_kontext(fix.organisation):
        HandwerkerAuftrag.objects.filter(pk=fix.auftrag.pk).update(**felder)


def _pendenzen(fix):
    with organisation_kontext(fix.organisation):
        return list(Pendenz.objects.filter(quelle__startswith=QUELLE))


def _lauf(fix):
    with organisation_kontext(fix.organisation):
        return generate_auto_pendenzen(horizont_tage=30)


class TerminPendenzTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_junger_auftrag_keine_pendenz(self):
        _altern(self.a, TERMIN_OFFEN_TAGE - 1)
        _lauf(self.a)
        self.assertEqual(_pendenzen(self.a), [])

    def test_nach_x_tagen_eine_pendenz_mit_titel(self):
        _altern(self.a, TERMIN_OFFEN_TAGE + 2)
        _lauf(self.a)
        (p,) = _pendenzen(self.a)
        self.assertTrue(p.titel.startswith(f'Termin offen: #{self.a.schaden.pk} '), p.titel)
        self.assertIn(self.a.handwerker.firma, p.titel)
        self.assertIn(f'(seit {TERMIN_OFFEN_TAGE + 2} Tagen)', p.titel)
        self.assertFalse(p.erledigt)
        self.assertEqual(p.liegenschaft_id, self.a.liegenschaft.pk)

    def test_genau_x_tage_zaehlt(self):
        _altern(self.a, TERMIN_OFFEN_TAGE)
        _lauf(self.a)
        self.assertEqual(len(_pendenzen(self.a)), 1)

    def test_idempotent_kein_doppel(self):
        _altern(self.a, 8)
        _lauf(self.a)
        neu = _lauf(self.a)
        _lauf(self.a)
        self.assertEqual(len(_pendenzen(self.a)), 1)
        self.assertEqual(neu, 0)

    def test_titel_zaehlt_tage_weiter(self):
        _altern(self.a, 6)
        _lauf(self.a)
        _altern(self.a, 7)
        _lauf(self.a)
        (p,) = _pendenzen(self.a)
        self.assertIn('(seit 7 Tagen)', p.titel)

    def test_vereinbarter_termin_schliesst_die_pendenz(self):
        _altern(self.a, 8)
        _lauf(self.a)
        _setze(self.a, termin_status='vereinbart')
        _lauf(self.a)
        (p,) = _pendenzen(self.a)
        self.assertTrue(p.erledigt)
        self.assertIsNotNone(p.erledigt_am)

    def test_vereinbarter_termin_von_anfang_an_keine_pendenz(self):
        _altern(self.a, 20, termin_status='vereinbart')
        _lauf(self.a)
        self.assertEqual(_pendenzen(self.a), [])

    def test_erledigt_oder_storniert_schliesst(self):
        for status in ('erledigt', 'storniert'):
            with self.subTest(status=status):
                _setze(self.a, status='offen', termin_status='offen')
                with organisation_kontext(self.a.organisation):
                    Pendenz.objects.filter(quelle__startswith=QUELLE).delete()
                _altern(self.a, 8)
                _lauf(self.a)
                self.assertEqual(len(_pendenzen(self.a)), 1)
                _setze(self.a, status=status)
                _lauf(self.a)
                self.assertTrue(_pendenzen(self.a)[0].erledigt)

    def test_inaktive_auftraege_bekommen_keine_pendenz(self):
        for felder in ({'status': 'storniert'}, {'status': 'erledigt'},
                       {'freigabe_status': 'ausstehend'}, {'freigabe_status': 'abgelehnt'}):
            with self.subTest(felder=felder):
                _altern(self.a, 20, **felder)
                _lauf(self.a)
                self.assertEqual(_pendenzen(self.a), [])
                _setze(self.a, status='offen', freigabe_status='nicht_noetig')
        _altern(self.a, 20)
        for ticket_status in ('erledigt', 'wartet_auf_rechnung'):
            with self.subTest(ticket=ticket_status):
                with organisation_kontext(self.a.organisation):
                    SchadenMeldung.objects.filter(pk=self.a.schaden.pk).update(status=ticket_status)
                _lauf(self.a)
                self.assertEqual(_pendenzen(self.a), [])

    def test_unbeantworteter_vorschlag_zaehlt_ab_dem_vorschlag(self):
        # Auftrag alt, aber gestern ein Vorschlag: noch keine Pendenz ...
        _altern(self.a, 30, termin_status='vorgeschlagen')
        with organisation_kontext(self.a.organisation):
            n = TicketNachricht.objects.create(
                ticket=self.a.schaden, auftrag=HandwerkerAuftrag.objects.get(pk=self.a.auftrag.pk),
                typ='direkt', seite='mieter', absender_name='M',
                nachricht='Terminvorschlag: Mo 10:00', is_intern=True, gelesen=True)
            TicketNachricht.objects.filter(pk=n.pk).update(erstellt_am=vor_tagen(1))
        _lauf(self.a)
        self.assertEqual(_pendenzen(self.a), [])
        # ... vor sechs Tagen: Pendenz, Frist ab dem Vorschlag.
        with organisation_kontext(self.a.organisation):
            TicketNachricht.objects.filter(pk=n.pk).update(erstellt_am=vor_tagen(6))
        _lauf(self.a)
        (p,) = _pendenzen(self.a)
        self.assertIn('(seit 6 Tagen)', p.titel)
        self.assertIn('unbeantwortet', p.beschreibung)

    def test_abgesagter_termin_zaehlt_als_offen(self):
        _altern(self.a, 9, termin_status='abgesagt')
        _lauf(self.a)
        self.assertEqual(len(_pendenzen(self.a)), 1)

    def test_von_hand_abgehakte_pendenz_bleibt_abgehakt(self):
        _altern(self.a, 8)
        _lauf(self.a)
        with organisation_kontext(self.a.organisation):
            Pendenz.objects.filter(quelle__startswith=QUELLE).update(erledigt=True)
        _lauf(self.a)
        (p,) = _pendenzen(self.a)
        self.assertTrue(p.erledigt)

    def test_langer_ticketname_kuerzt_den_ticketteil_nicht_die_tage(self):
        _altern(self.a, 8)
        with organisation_kontext(self.a.organisation):
            SchadenMeldung.objects.filter(pk=self.a.schaden.pk).update(titel='X' * 190)
        _lauf(self.a)
        (p,) = _pendenzen(self.a)
        self.assertLessEqual(len(p.titel), 200)
        self.assertTrue(p.titel.endswith('(seit 8 Tagen)'))

    def test_kein_mail_an_die_verwaltung(self):
        from django.core import mail
        _altern(self.a, 8)
        _lauf(self.a)
        self.assertEqual(mail.outbox, [])

    def test_pendenz_verlinkt_das_ticket(self):
        from core.views.fw._basis import _pendenz_ziel
        _altern(self.a, 8)
        _lauf(self.a)
        (p,) = _pendenzen(self.a)
        self.assertEqual(_pendenz_ziel(p)[0], f'/neu/schaeden/{self.a.schaden.pk}/')

    # --- Mandantentrennung ---------------------------------------------------

    def test_tageslauf_jede_verwaltung_nur_ihre_pendenz(self):
        _altern(self.a, 8)
        _altern(self.b, 9)
        with mock.patch('core.utils.market_data.fetch_market_rates', return_value=({}, [])):
            call_command('taeglicher_lauf', digest_weekday=-1, stdout=StringIO(), stderr=StringIO())
        (pa,) = _pendenzen(self.a)
        (pb,) = _pendenzen(self.b)
        self.assertIn(self.a.handwerker.firma, pa.titel)
        self.assertIn(self.b.handwerker.firma, pb.titel)
        self.assertEqual(pa.liegenschaft_id, self.a.liegenschaft.pk)
        self.assertEqual(pb.liegenschaft_id, self.b.liegenschaft.pk)
        self.assertEqual(pa.quelle.split(':')[2], str(self.a.auftrag.pk))
        self.assertEqual(pb.quelle.split(':')[2], str(self.b.auftrag.pk))

    def test_nur_die_verwaltung_mit_altem_auftrag_bekommt_eine_pendenz(self):
        _altern(self.a, 8)
        _lauf(self.a)
        _lauf(self.b)
        self.assertEqual(len(_pendenzen(self.a)), 1)
        self.assertEqual(_pendenzen(self.b), [])

    def test_lauf_einer_verwaltung_schliesst_fremde_pendenz_nicht(self):
        _altern(self.a, 8)
        _altern(self.b, 8)
        _lauf(self.a)
        _lauf(self.b)
        _setze(self.a, termin_status='vereinbart')
        _lauf(self.a)
        self.assertTrue(_pendenzen(self.a)[0].erledigt)
        self.assertFalse(_pendenzen(self.b)[0].erledigt)
