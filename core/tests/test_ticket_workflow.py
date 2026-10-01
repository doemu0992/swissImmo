"""Mängel-Workflow: State-Machine, Simulation Mieter -> Handwerker -> Kreditor,
Sicherheitssperre «kein Abschluss ohne Handwerkerrechnung»."""
from decimal import Decimal

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, Client, override_settings

from ._helfer import _team_user, _basis_objekte, _test_organisation


def _ticket(**kw):
    from tickets.models import SchadenMeldung
    lg, e, m, v = _basis_objekte()
    return SchadenMeldung.objects.create(
        liegenschaft=lg, betroffene_einheit=e, gemeldet_von=m,
        titel='Wasserhahn tropft', beschreibung='Küche', email_melder=m.email, **kw)


def _handwerker(**kw):
    from crm.models import Handwerker
    return Handwerker.objects.create(firma='Sanitär AG', email='hw@example.ch', **kw)


def _rechnung(ticket, betrag='480.00'):
    from finance.models import KreditorenRechnung
    return KreditorenRechnung.objects.create(
        liegenschaft=ticket.liegenschaft, lieferant='Sanitär AG',
        betrag=Decimal(betrag), status='neu')


class StateMachineTests(TestCase):
    def test_regelweg(self):
        from tickets.workflow import wechsle_status
        t = _ticket()
        for ziel in ('in_bearbeitung', 'wartet_auf_rechnung', 'erledigt'):
            wechsle_status(t, ziel)
            t.refresh_from_db()
            self.assertEqual(t.status, ziel)

    def test_unerlaubter_uebergang(self):
        from tickets.workflow import wechsle_status, UngueltigerUebergang
        t = _ticket()
        with self.assertRaises(UngueltigerUebergang):
            wechsle_status(t, 'wartet_auf_rechnung')   # neu -> Rechnung: übersprungen
        self.assertEqual(t.status, 'neu')
        with self.assertRaises(UngueltigerUebergang):
            wechsle_status(t, 'quatsch')

    def test_wiedereroeffnen(self):
        from tickets.workflow import wechsle_status
        t = _ticket()
        wechsle_status(t, 'erledigt')
        wechsle_status(t, 'in_bearbeitung')
        self.assertEqual(t.status, 'in_bearbeitung')

    def test_status_ist_wahlmoeglichkeit(self):
        from tickets.models import SchadenMeldung
        self.assertIn('wartet_auf_rechnung', dict(SchadenMeldung.STATUS_CHOICES))


class SimulationTests(TestCase):
    """Der ganze Ablauf, Schritt für Schritt."""

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_mieter_bis_rechnung(self):
        from tickets.workflow import (handwerker_zuweisen, arbeitsauftrag_senden,
                                      rechnung_verknuepfen, wechsle_status)
        # 1. Mieter meldet
        t = _ticket()
        self.assertEqual(t.status, 'neu')
        # 2. Handwerker aus der Kontaktdatenbank zuweisen
        hw = _handwerker()
        a = handwerker_zuweisen(t, hw, 'Dichtung ersetzen')
        t.refresh_from_db()
        self.assertEqual(t.status, 'in_bearbeitung')
        # 3. Arbeitsauftrag (PDF + E-Mail)
        pdf, versendet = arbeitsauftrag_senden(a)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertTrue(versendet)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['hw@example.ch'])
        self.assertEqual(mail.outbox[0].attachments[0][0], f'Reparaturauftrag_{a.id}.pdf')
        # Arbeit gemacht, Rechnung fehlt
        wechsle_status(t, 'wartet_auf_rechnung')
        # 4. Rechnung verknüpfen -> Ticket schliesst
        kr = _rechnung(t)
        rechnung_verknuepfen(a, kr)
        t.refresh_from_db(); a.refresh_from_db()
        self.assertEqual(a.kreditoren_rechnung_id, kr.id)
        self.assertEqual(a.kosten_effektiv, Decimal('480.00'))
        self.assertEqual(t.status, 'erledigt')


class SperreTests(TestCase):
    def _mit_auftrag(self):
        from tickets.workflow import handwerker_zuweisen
        t = _ticket()
        a = handwerker_zuweisen(t, _handwerker())
        return t, a

    def test_erledigt_ohne_rechnung_gesperrt(self):
        from tickets.workflow import wechsle_status, AbschlussGesperrt
        t, a = self._mit_auftrag()
        wechsle_status(t, 'wartet_auf_rechnung')
        with self.assertRaises(AbschlussGesperrt):
            wechsle_status(t, 'erledigt')
        t.refresh_from_db()
        self.assertEqual(t.status, 'wartet_auf_rechnung')

    def test_direktes_save_umgeht_sperre_nicht(self):
        t, a = self._mit_auftrag()
        t.status = 'erledigt'
        with self.assertRaises(ValidationError):
            t.save()
        t.refresh_from_db()
        self.assertEqual(t.status, 'in_bearbeitung')

    def test_ohne_handwerker_darf_erledigt_werden(self):
        from tickets.workflow import wechsle_status
        t = _ticket()
        wechsle_status(t, 'erledigt')
        self.assertEqual(t.status, 'erledigt')

    def test_stornierter_auftrag_zaehlt_nicht(self):
        from tickets.workflow import wechsle_status
        t, a = self._mit_auftrag()
        a.status = 'storniert'; a.save()
        wechsle_status(t, 'erledigt')
        self.assertEqual(t.status, 'erledigt')

    def test_zwei_auftraege_beide_brauchen_rechnung(self):
        from tickets.workflow import handwerker_zuweisen, rechnung_verknuepfen
        t, a1 = self._mit_auftrag()
        a2 = handwerker_zuweisen(t, _handwerker())
        rechnung_verknuepfen(a1, _rechnung(t))
        t.refresh_from_db()
        self.assertNotEqual(t.status, 'erledigt')     # a2 hat noch keine
        rechnung_verknuepfen(a2, _rechnung(t, '90'))
        t.refresh_from_db()
        self.assertEqual(t.status, 'erledigt')

    def test_stornierte_rechnung_nicht_verknuepfbar(self):
        from tickets.workflow import rechnung_verknuepfen
        t, a = self._mit_auftrag()
        kr = _rechnung(t); kr.status = 'storniert'; kr.save()
        with self.assertRaises(ValidationError):
            rechnung_verknuepfen(a, kr)

    def test_ansicht_meldet_sperre(self):
        t, a = self._mit_auftrag()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/schaeden/{t.id}/status/', {'status': 'erledigt'}, follow=True)
        t.refresh_from_db()
        self.assertEqual(t.status, 'in_bearbeitung')
        self.assertContains(r, 'Kreditorenrechnung')

    def test_ansicht_erledigt_nach_verknuepfung(self):
        from tickets.workflow import rechnung_verknuepfen
        t, a = self._mit_auftrag()
        rechnung_verknuepfen(a, _rechnung(t), abschliessen=False)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/schaeden/{t.id}/status/', {'status': 'erledigt'})
        t.refresh_from_db()
        self.assertEqual(t.status, 'erledigt')
