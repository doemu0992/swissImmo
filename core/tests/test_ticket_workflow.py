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


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class KommunikationTests(TestCase):
    """Das Ticket spricht von selbst: Handwerker bekommt den Auftrag, der Mieter die Info."""

    def test_auftrag_vergeben_sendet_handwerker_und_mieter(self):
        from tickets.workflow import auftrag_vergeben
        t = _ticket()
        res = auftrag_vergeben(t, _handwerker(), 'Dichtung ersetzen')
        self.assertTrue(res['handwerker_versendet'])
        self.assertTrue(res['melder_informiert'])
        an = {m.to[0]: m for m in mail.outbox}
        self.assertEqual(set(an), {'hw@example.ch', 'hans@example.ch'})
        self.assertEqual(an['hw@example.ch'].attachments[0][2], 'application/pdf')
        self.assertIn('Sanitär AG', an['hans@example.ch'].body)   # Mieter erfährt die Firma
        t.refresh_from_db()
        self.assertEqual(t.status, 'in_bearbeitung')
        typen = list(t.nachrichten.values_list('typ', 'is_intern'))
        self.assertIn(('handwerker_mail', True), typen)
        self.assertIn(('email', False), typen)   # für den Mieter im Portal sichtbar

    def test_status_wechsel_informiert_mieter_automatisch(self):
        from tickets.workflow import wechsle_status
        t = _ticket()
        wechsle_status(t, 'in_bearbeitung', melder_informieren=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['hans@example.ch'])

    def test_interner_status_schweigt(self):
        from tickets.workflow import wechsle_status
        t = _ticket(status='in_bearbeitung')
        wechsle_status(t, 'wartet_auf_rechnung', melder_informieren=True)
        self.assertEqual(len(mail.outbox), 0)

    def test_ohne_flag_keine_mail(self):
        from tickets.workflow import wechsle_status
        wechsle_status(_ticket(), 'in_bearbeitung')
        self.assertEqual(len(mail.outbox), 0)

    def test_abschluss_per_rechnung_informiert_mieter(self):
        from tickets.workflow import auftrag_vergeben, rechnung_verknuepfen
        t = _ticket()
        a = auftrag_vergeben(t, _handwerker())['auftrag']
        mail.outbox.clear()
        rechnung_verknuepfen(a, _rechnung(t))
        t.refresh_from_db()
        self.assertEqual(t.status, 'erledigt')
        self.assertEqual([m.to[0] for m in mail.outbox], ['hans@example.ch'])
        self.assertIn('behoben', mail.outbox[0].subject)

    def test_mailfehler_blockiert_nichts(self):
        from unittest import mock
        from tickets.workflow import auftrag_vergeben
        t = _ticket()
        with mock.patch('core.utils.email_service.send_ticket_email', side_effect=RuntimeError('smtp')):
            res = auftrag_vergeben(t, _handwerker())
        self.assertFalse(res['melder_informiert'])
        t.refresh_from_db()
        self.assertEqual(t.status, 'in_bearbeitung')
        self.assertEqual(t.handwerker_auftraege.count(), 1)

    def test_melder_ohne_mail_kein_absturz(self):
        from tickets.workflow import auftrag_vergeben
        t = _ticket()
        t.email_melder = ''; t.save()
        t.gemeldet_von.email = ''; t.gemeldet_von.save()
        res = auftrag_vergeben(t, _handwerker())
        self.assertFalse(res['melder_informiert'])

    def test_handwerker_ohne_mail_wird_im_verlauf_vermerkt(self):
        from crm.models import Handwerker
        from tickets.workflow import auftrag_vergeben
        t = _ticket()
        res = auftrag_vergeben(t, Handwerker.objects.create(firma='Ohne Mail GmbH'))
        self.assertFalse(res['handwerker_versendet'])
        n = t.nachrichten.filter(typ='handwerker_mail').get()
        self.assertIn('NICHT versendet', n.nachricht)

    def test_ansicht_beauftragen_sendet_alles(self):
        t = _ticket()
        hw = _handwerker()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/schaeden/{t.id}/auftrag/', {'handwerker_id': hw.id, 'auftragstext': 'Bitte Termin'})
        t.refresh_from_db()
        self.assertEqual(t.status, 'in_bearbeitung')
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['hans@example.ch', 'hw@example.ch'])

    def test_ansicht_status_erledigt_informiert_per_checkbox(self):
        t = _ticket()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/schaeden/{t.id}/status/', {'status': 'erledigt', 'melder_informieren': 'on'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('behoben', mail.outbox[0].subject)
