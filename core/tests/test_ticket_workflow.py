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


MAIL = override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')


def _mit_auftrag(**ticket_kw):
    from tickets.workflow import handwerker_zuweisen
    t = _ticket(**ticket_kw)
    return t, handwerker_zuweisen(t, _handwerker())


@MAIL
class AntwortZuordnungTests(TestCase):
    def test_handwerker_antwort_wird_zugeordnet_und_ticket_wieder_offen(self):
        from tickets.workflow import antwort_zuordnen
        t, a = _mit_auftrag(status='warte_auf_handwerker')
        seite = antwort_zuordnen(t, 'Sanitär AG <HW@example.ch>', 'Komme Dienstag')
        t.refresh_from_db()
        self.assertEqual(seite, 'handwerker')
        n = t.nachrichten.get(typ='handwerker_mail', is_von_verwaltung=False)
        self.assertEqual(n.empfaenger_handwerker, a.handwerker)
        self.assertEqual(t.status, 'in_bearbeitung')
        self.assertFalse(t.gelesen)

    def test_mieter_antwort_bei_warte_auf_mieter(self):
        from tickets.workflow import antwort_zuordnen
        t, a = _mit_auftrag()
        t.status = 'warte_auf_mieter'; t.save()
        seite = antwort_zuordnen(t, 'Hans <hans@example.ch>', 'Ja, passt')
        t.refresh_from_db()
        self.assertEqual(seite, 'melder')
        self.assertEqual(t.status, 'in_bearbeitung')
        self.assertTrue(t.nachrichten.filter(typ='mail_antwort').exists())

    def test_fremder_absender_ist_kein_handwerker(self):
        from tickets.workflow import antwort_zuordnen
        t, a = _mit_auftrag(status='warte_auf_handwerker')
        self.assertEqual(antwort_zuordnen(t, 'x@fremd.ch', 'hallo'), 'melder')
        t.refresh_from_db()
        self.assertEqual(t.status, 'warte_auf_handwerker')   # Fremder bewegt den Fluss nicht

    def test_antwort_auf_anderes_ticket_gleicher_adresse_zaehlt_nicht(self):
        from tickets.workflow import antwort_zuordnen
        t1, a1 = _mit_auftrag()
        t2 = _ticket()                         # kein Auftrag am zweiten Ticket
        self.assertEqual(antwort_zuordnen(t2, 'hw@example.ch', 'x'), 'melder')

    def test_abruf_befehl_ordnet_handwerkermail_zu(self):
        from email.message import EmailMessage
        from core.management.commands.fetch_replies import Command
        t, a = _mit_auftrag(status='warte_auf_handwerker')
        m = EmailMessage()
        m['Subject'] = f'Re: Reparatur (Ticket #{t.pk})'
        m['From'] = 'Sanitär AG <hw@example.ch>'
        m.set_content('Termin Montag 8 Uhr')
        Command().verarbeite_mail(m.as_bytes())
        t.refresh_from_db()
        self.assertTrue(t.nachrichten.filter(typ='handwerker_mail', is_von_verwaltung=False).exists())
        self.assertEqual(t.status, 'in_bearbeitung')


@MAIL
class TerminTests(TestCase):
    def _wann(self):
        from datetime import datetime
        return datetime(2026, 11, 3, 8, 30)

    def test_termin_informiert_beide_mit_kalendereintrag(self):
        from tickets.workflow import termin_festlegen
        t, a = _mit_auftrag()
        m_ok, h_ok = termin_festlegen(a, self._wann())
        self.assertTrue(m_ok and h_ok)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox[-2:]), ['hans@example.ch', 'hw@example.ch'])
        for m in mail.outbox[-2:]:
            name, inhalt, mime = m.attachments[0]
            self.assertEqual((name, mime), ('Termin.ics', 'text/calendar'))
            self.assertIn('METHOD:PUBLISH', inhalt)
            self.assertIn('03.11.2026', m.body)
        a.refresh_from_db(); t.refresh_from_db()
        self.assertEqual(a.termin_status, 'vereinbart')
        self.assertEqual(t.status, 'warte_auf_handwerker')

    def test_absage_storniert_kalendereintrag(self):
        from tickets.workflow import termin_festlegen, termin_absagen
        t, a = _mit_auftrag()
        termin_festlegen(a, self._wann())
        mail.outbox.clear()
        termin_absagen(a)
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'abgesagt')
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn('METHOD:CANCEL', mail.outbox[0].attachments[0][1])

    def test_absage_ohne_termin_abgelehnt(self):
        from tickets.workflow import termin_absagen
        t, a = _mit_auftrag()
        with self.assertRaises(ValidationError):
            termin_absagen(a)

    def test_termin_auf_stornierten_auftrag_abgelehnt(self):
        from tickets.workflow import termin_festlegen
        t, a = _mit_auftrag()
        a.status = 'storniert'; a.save()
        with self.assertRaises(ValidationError):
            termin_festlegen(a, self._wann())

    def test_ansicht_setzt_und_sagt_ab(self):
        t, a = _mit_auftrag()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/auftrag/{a.id}/termin/', {'termin': '2026-11-03T08:30'})
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'vereinbart')
        c.post(f'/neu/auftrag/{a.id}/termin/', {'aktion': 'absagen'})
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'abgesagt')

    def test_ansicht_ungueltiges_datum_aendert_nichts(self):
        t, a = _mit_auftrag()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/auftrag/{a.id}/termin/', {'termin': 'morgen'})
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'offen')


@MAIL
class NachrichtAnHandwerkerTests(TestCase):
    def test_freitext_geht_raus_und_steht_im_verlauf(self):
        from tickets.workflow import nachricht_an_handwerker
        t, a = _mit_auftrag()
        mail.outbox.clear()
        self.assertTrue(nachricht_an_handwerker(a, 'Bitte Foto der Armatur senden'))
        self.assertEqual(mail.outbox[0].to, ['hw@example.ch'])
        self.assertIn(f'Ticket #{t.pk}', mail.outbox[0].subject)   # Antwort findet ins Ticket zurück
        self.assertTrue(t.nachrichten.filter(nachricht__contains='Foto der Armatur').exists())

    def test_ohne_adresse_oder_text_nichts(self):
        from crm.models import Handwerker
        from tickets.workflow import nachricht_an_handwerker
        t, a = _mit_auftrag()
        self.assertFalse(nachricht_an_handwerker(a, '   '))
        a.handwerker = Handwerker.objects.create(firma='Ohne Mail'); a.save()
        self.assertFalse(nachricht_an_handwerker(a, 'x'))

    def test_ansicht(self):
        t, a = _mit_auftrag()
        mail.outbox.clear()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/auftrag/{a.id}/nachricht/', {'text': 'Wann können Sie?'})
        self.assertEqual(len(mail.outbox), 1)


@MAIL
class ErinnerungenTests(TestCase):
    def _alt(self, ticket, auftrag=None, tage=0):
        """Wartezeit künstlich zurückdatieren (auto_now/auto_now_add umgehen)."""
        from datetime import timedelta
        from django.utils import timezone
        from tickets.models import HandwerkerAuftrag, SchadenMeldung
        vor = timezone.now() - timedelta(days=tage)
        SchadenMeldung.objects.filter(pk=ticket.pk).update(aktualisiert_am=vor)
        if auftrag:
            HandwerkerAuftrag.objects.filter(pk=auftrag.pk).update(beauftragt_am=vor)

    def _lauf(self, tage_spaeter=0):
        from datetime import timedelta
        from django.utils import timezone
        from tickets.erinnerungen import erinnerungen_senden
        return erinnerungen_senden(timezone.now() + timedelta(days=tage_spaeter))

    def test_auftrag_erinnerung_erst_nach_drei_tagen(self):
        t, a = _mit_auftrag()
        mail.outbox.clear()
        self.assertEqual(self._lauf(2)['auftrag'], 0)
        self.assertEqual(self._lauf(3)['auftrag'], 1)
        self.assertEqual(mail.outbox[-1].to, ['hw@example.ch'])
        self.assertIn('Erinnerung', mail.outbox[-1].subject)

    def test_kein_doppelversand_am_selben_tag_und_deckel_drei(self):
        t, a = _mit_auftrag()
        self.assertEqual(self._lauf(3)['auftrag'], 1)
        self.assertEqual(self._lauf(3)['auftrag'], 0)      # gleicher Tag: nichts
        self.assertEqual(self._lauf(6)['auftrag'], 1)
        self.assertEqual(self._lauf(9)['auftrag'], 1)
        self.assertEqual(self._lauf(12)['auftrag'], 0)     # Deckel erreicht

    def test_keine_erinnerung_wenn_handwerker_geantwortet_hat(self):
        from tickets.workflow import antwort_zuordnen
        t, a = _mit_auftrag()
        antwort_zuordnen(t, 'hw@example.ch', 'Melde mich')
        self.assertEqual(self._lauf(10)['auftrag'], 0)

    def test_keine_erinnerung_bei_vereinbartem_termin(self):
        from datetime import datetime
        from tickets.workflow import termin_festlegen
        t, a = _mit_auftrag()
        termin_festlegen(a, datetime(2026, 11, 3, 8, 30))
        self.assertEqual(self._lauf(10)['auftrag'], 0)

    def test_rechnung_erinnerung_nach_sieben_tagen(self):
        from tickets.workflow import wechsle_status
        t, a = _mit_auftrag()
        wechsle_status(t, 'wartet_auf_rechnung')
        mail.outbox.clear()
        self.assertEqual(self._lauf(6)['rechnung'], 0)
        self.assertEqual(self._lauf(7)['rechnung'], 1)
        self.assertIn('Rechnung', mail.outbox[-1].subject)

    def test_mieter_erinnerung(self):
        from tickets.workflow import wechsle_status
        t = _ticket(status='in_bearbeitung')
        wechsle_status(t, 'warte_auf_mieter')
        mail.outbox.clear()
        self.assertEqual(self._lauf(4)['mieter'], 0)
        self.assertEqual(self._lauf(5)['mieter'], 1)
        self.assertEqual(mail.outbox[-1].to, ['hans@example.ch'])

    def test_erledigtes_ticket_bekommt_nichts(self):
        from tickets.workflow import rechnung_verknuepfen
        t, a = _mit_auftrag()
        rechnung_verknuepfen(a, _rechnung(t))
        mail.outbox.clear()
        self.assertEqual(sum(self._lauf(30).values()), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_pendenz_rechnung_fehlt_und_erledigt_sich(self):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        from tickets.workflow import wechsle_status, rechnung_verknuepfen
        t, a = _mit_auftrag()
        wechsle_status(t, 'wartet_auf_rechnung')
        self._alt(t, a, tage=8)
        generate_auto_pendenzen(horizont_tage=30)
        p = Pendenz.objects.get(quelle=f'auto:rechnung:{t.pk}')
        self.assertFalse(p.erledigt)
        rechnung_verknuepfen(a, _rechnung(t))
        generate_auto_pendenzen(horizont_tage=30)
        p.refresh_from_db()
        self.assertTrue(p.erledigt)


@MAIL
class MandantengrenzeTests(TestCase):
    """Fremde Aufträge/Tickets: 404, keine Mail, keine Änderung.

    Gegenprobe (protokolliert): in `fw_auftrag_termin`/`fw_auftrag_nachricht`
    `HandwerkerAuftrag.objects` durch `.alle_organisationen` ersetzen -> rot.
    """

    def _fremd(self):
        """Ein zweiter Mandant mit eigenem Ticket + Auftrag, daneben der eigene."""
        from core.tests._isolation import MandantenFixture
        eigen_t, eigen_a = _mit_auftrag()
        fremd = MandantenFixture('B', '3000', 'Bern')
        return eigen_t, eigen_a, fremd

    def test_termin_und_nachricht_auf_fremden_auftrag_sind_404(self):
        from core.tenancy import organisation_kontext
        from tickets.models import HandwerkerAuftrag
        eigen_t, eigen_a, fremd = self._fremd()
        with organisation_kontext(fremd.organisation):
            fremder_auftrag = fremd.auftrag
        mail.outbox.clear()
        c = Client(); c.force_login(_team_user())          # Benutzer der EIGENEN Organisation
        r1 = c.post(f'/neu/auftrag/{fremder_auftrag.pk}/termin/', {'termin': '2026-11-03T08:30'})
        r2 = c.post(f'/neu/auftrag/{fremder_auftrag.pk}/nachricht/', {'text': 'hallo'})
        self.assertEqual((r1.status_code, r2.status_code), (404, 404))
        self.assertEqual(len(mail.outbox), 0)
        with organisation_kontext(fremd.organisation):
            a = HandwerkerAuftrag.objects.get(pk=fremder_auftrag.pk)
            self.assertEqual(a.termin_status, 'offen')

    def test_abruf_mit_ticketnummer_eines_fremden_mandanten_legt_nichts_an(self):
        from email.message import EmailMessage
        from core.management.commands.fetch_replies import Command
        from core.tenancy import organisation_kontext
        from tickets.models import TicketNachricht
        eigen_t, eigen_a, fremd = self._fremd()
        with organisation_kontext(fremd.organisation):
            fremdes_ticket = fremd.schaden
            vorher = TicketNachricht.objects.filter(ticket=fremdes_ticket).count()
        m = EmailMessage()
        m['Subject'] = f'Re: Ticket #{fremdes_ticket.pk}'
        m['From'] = 'hw@example.ch'                     # Adresse des EIGENEN Handwerkers
        m.set_content('Antwort')
        Command().verarbeite_mail(m.as_bytes())          # Kontext: eigene Organisation
        with organisation_kontext(fremd.organisation):
            self.assertEqual(TicketNachricht.objects.filter(ticket=fremdes_ticket).count(), vorher)

    def test_erinnerungen_nur_im_kontext_der_laufenden_verwaltung(self):
        from datetime import timedelta
        from django.utils import timezone
        from core.tenancy import organisation_kontext
        from tickets.erinnerungen import erinnerungen_senden
        eigen_t, eigen_a, fremd = self._fremd()
        with organisation_kontext(fremd.organisation):
            fremd.auftrag.handwerker.email = 'fremd-hw@example.ch'
            fremd.auftrag.handwerker.save()
        mail.outbox.clear()
        n = erinnerungen_senden(timezone.now() + timedelta(days=10))   # Kontext: eigene Verwaltung
        self.assertEqual(n['auftrag'], 1)
        self.assertEqual([m.to[0] for m in mail.outbox], ['hw@example.ch'])   # nie die fremde Adresse


@MAIL
class ReplyToTests(TestCase):
    """Antworten gehen an das Antwort-Postfach der Verwaltung des Tickets."""

    def _postfach(self, org, benutzer, aktiv=True):
        from core.models import Postfach
        return Postfach.alle_organisationen.create(
            organisation=org, zweck='antworten', benutzer=benutzer, aktiv=aktiv, server='imap.example.ch')

    def test_reply_to_ist_das_postfach_der_verwaltung(self):
        from tickets.workflow import melder_benachrichtigen
        t = _ticket()
        self._postfach(t.organisation, 'antworten@verwaltung-a.ch')
        mail.outbox.clear()
        self.assertTrue(melder_benachrichtigen(t, 'ticket_melder_status'))
        self.assertEqual(mail.outbox[0].reply_to, ['antworten@verwaltung-a.ch'])

    def test_ohne_postfach_oder_ohne_adresse_gilt_die_globale(self):
        from tickets.workflow import melder_benachrichtigen, reply_to
        t = _ticket()
        self.assertIsNone(reply_to(t))
        self._postfach(t.organisation, 'kein-at-zeichen')
        self.assertIsNone(reply_to(t))
        mail.outbox.clear()
        melder_benachrichtigen(t, 'ticket_melder_status')
        self.assertEqual(len(mail.outbox[0].reply_to), 1)       # die globale Adresse aus der Umgebung
        self.assertNotIn('kein-at-zeichen', mail.outbox[0].reply_to)

    def test_inaktives_postfach_zaehlt_nicht(self):
        from tickets.workflow import reply_to
        t = _ticket()
        self._postfach(t.organisation, 'alt@verwaltung-a.ch', aktiv=False)
        self.assertIsNone(reply_to(t))

    def test_postfach_einer_fremden_verwaltung_wird_nie_benutzt(self):
        from core.tenancy import organisation_kontext
        from core.tests._isolation import MandantenFixture
        from tickets.workflow import reply_to
        t = _ticket()
        fremd = MandantenFixture('B', '3000', 'Bern')
        self._postfach(fremd.organisation, 'antworten@fremd.ch')
        with organisation_kontext(t.organisation):
            self.assertIsNone(reply_to(t))

    def test_alle_ticket_mails_tragen_den_reply_to(self):
        from datetime import datetime
        from tickets.workflow import (auftrag_vergeben, nachricht_an_handwerker, termin_festlegen,
                                      auftrag_stornieren)
        t = _ticket()
        self._postfach(t.organisation, 'antworten@verwaltung-a.ch')
        mail.outbox.clear()
        a = auftrag_vergeben(t, _handwerker())['auftrag']
        nachricht_an_handwerker(a, 'Hallo')
        termin_festlegen(a, datetime(2026, 11, 3, 8, 30))
        auftrag_stornieren(a)
        self.assertGreaterEqual(len(mail.outbox), 7)
        for m in mail.outbox:
            self.assertEqual(m.reply_to, ['antworten@verwaltung-a.ch'], m.subject)


@MAIL
class StornoTests(TestCase):
    def test_storno_informiert_handwerker_und_setzt_ticket_zurueck(self):
        from tickets.workflow import auftrag_stornieren, wechsle_status
        t, a = _mit_auftrag()
        wechsle_status(t, 'warte_auf_handwerker')
        mail.outbox.clear()
        self.assertTrue(auftrag_stornieren(a, 'Mieter hat selbst repariert'))
        a.refresh_from_db(); t.refresh_from_db()
        self.assertEqual(a.status, 'storniert')
        self.assertEqual(t.status, 'in_bearbeitung')
        self.assertEqual([m.to[0] for m in mail.outbox], ['hw@example.ch'])
        self.assertIn('storniert', mail.outbox[0].subject)
        self.assertIn('Mieter hat selbst repariert', mail.outbox[0].body)

    def test_storno_sagt_termin_ab(self):
        from datetime import datetime
        from tickets.workflow import termin_festlegen, auftrag_stornieren
        t, a = _mit_auftrag()
        termin_festlegen(a, datetime(2026, 11, 3, 8, 30))
        mail.outbox.clear()
        auftrag_stornieren(a)
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'abgesagt')
        self.assertTrue(any('METHOD:CANCEL' in m.attachments[0][1] for m in mail.outbox if m.attachments))

    def test_storno_verwirft_offene_freigabe(self):
        from tickets.workflow import auftrag_stornieren
        t, a = _mit_auftrag()
        a.freigabe_status = 'ausstehend'; a.save()
        auftrag_stornieren(a)
        a.refresh_from_db()
        self.assertEqual(a.freigabe_status, 'nicht_noetig')

    def test_zweiter_aktiver_auftrag_haelt_den_status(self):
        from tickets.workflow import auftrag_stornieren, handwerker_zuweisen, wechsle_status
        t, a1 = _mit_auftrag()
        handwerker_zuweisen(t, _handwerker())
        wechsle_status(t, 'warte_auf_handwerker')
        auftrag_stornieren(a1)
        t.refresh_from_db()
        self.assertEqual(t.status, 'warte_auf_handwerker')

    def test_nicht_stornierbar_mit_rechnung_erledigt_oder_schon_storniert(self):
        from tickets.workflow import auftrag_stornieren, rechnung_verknuepfen
        t, a = _mit_auftrag()
        rechnung_verknuepfen(a, _rechnung(t), abschliessen=False)
        with self.assertRaises(ValidationError):
            auftrag_stornieren(a)
        t2, b = _mit_auftrag()
        auftrag_stornieren(b)
        with self.assertRaises(ValidationError):
            auftrag_stornieren(b)
        t3, c = _mit_auftrag()
        c.status = 'erledigt'; c.save()
        with self.assertRaises(ValidationError):
            auftrag_stornieren(c)

    def test_stornierter_auftrag_bekommt_keine_erinnerung(self):
        from datetime import timedelta
        from django.utils import timezone
        from tickets.erinnerungen import erinnerungen_senden
        from tickets.workflow import auftrag_stornieren
        t, a = _mit_auftrag()
        auftrag_stornieren(a)
        mail.outbox.clear()
        self.assertEqual(erinnerungen_senden(timezone.now() + timedelta(days=30))['auftrag'], 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_nur_stornierter_auftrag_ist_kein_auftrag_im_befund(self):
        from datetime import date, timedelta
        from faelle.schaeden import _befunde, OHNE_AUFTRAG_TAGE
        from tickets.models import SchadenMeldung
        from tickets.workflow import auftrag_stornieren
        t, a = _mit_auftrag()
        auftrag_stornieren(a)
        SchadenMeldung.objects.filter(pk=t.pk).update(
            erstellt_am=__import__('django.utils.timezone', fromlist=['now']).now() - timedelta(days=OHNE_AUFTRAG_TAGE + 5))
        t.refresh_from_db()
        texte = [b['text'] for b in _befunde(t, date.today())]
        self.assertIn('Kein Auftrag', texte)

    def test_summen_ohne_stornierte_auftraege(self):
        from decimal import Decimal
        from core.services.versicherungsfall import schadensumme_vorschlag
        from tickets.workflow import auftrag_stornieren, handwerker_zuweisen
        t, a1 = _mit_auftrag()
        a2 = handwerker_zuweisen(t, _handwerker())
        a1.kosten_effektiv = Decimal('1000'); a1.save()
        a2.kosten_effektiv = Decimal('300'); a2.save()
        auftrag_stornieren(a1)
        self.assertEqual(schadensumme_vorschlag(t), Decimal('300.00'))

    def test_ansicht_storno(self):
        t, a = _mit_auftrag()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/auftrag/{a.id}/storno/', {'grund': 'doppelt'})
        a.refresh_from_db()
        self.assertEqual(a.status, 'storniert')


@MAIL
class RechnungVerknuepfenAnsichtTests(TestCase):
    def test_verknuepfen_und_abschliessen(self):
        t, a = _mit_auftrag()
        kr = _rechnung(t)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/auftrag/{a.id}/rechnung/', {'rechnung_id': kr.id, 'abschliessen': 'on'})
        a.refresh_from_db(); t.refresh_from_db()
        self.assertEqual(a.kreditoren_rechnung_id, kr.id)
        self.assertEqual(t.status, 'erledigt')

    def test_verknuepfen_ohne_abschliessen_laesst_ticket_offen(self):
        t, a = _mit_auftrag()
        kr = _rechnung(t)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/auftrag/{a.id}/rechnung/', {'rechnung_id': kr.id})
        t.refresh_from_db()
        self.assertEqual(t.status, 'in_bearbeitung')

    def test_rechnung_an_anderem_auftrag_wird_abgelehnt(self):
        from tickets.workflow import handwerker_zuweisen, rechnung_verknuepfen
        t, a1 = _mit_auftrag()
        a2 = handwerker_zuweisen(t, _handwerker())
        kr = _rechnung(t)
        rechnung_verknuepfen(a1, kr, abschliessen=False)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/auftrag/{a2.id}/rechnung/', {'rechnung_id': kr.id})
        a2.refresh_from_db()
        self.assertIsNone(a2.kreditoren_rechnung_id)

    def test_detailseite_bietet_nur_freie_rechnungen_an(self):
        from tickets.workflow import rechnung_verknuepfen
        t, a = _mit_auftrag()
        _rechnung(t, '111.00')
        belegt = _rechnung(t, '222.00')
        storniert = _rechnung(t, '333.00'); storniert.status = 'storniert'; storniert.save()
        from tickets.workflow import handwerker_zuweisen
        b = handwerker_zuweisen(t, _handwerker())
        rechnung_verknuepfen(b, belegt, abschliessen=False)
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/schaeden/{t.id}/').content.decode()
        # Der Optionstext ist eindeutig; `value="2"` käme auch in anderen Feldern der Seite vor.
        import re
        optionen = re.findall(r'<option value="\d+">#\d+ · [^<]*</option>', body)
        self.assertEqual(len(optionen), 1, optionen)    # nur die freie Rechnung
        self.assertRegex(optionen[0], r'CHF 111[.,]00')

    def test_kosten_mit_kreditor_erstellen_verknuepft_ueber_den_service(self):
        t, a = _mit_auftrag()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/auftrag/{a.id}/kosten/', {'kosten_effektiv': '480', 'kreditor_erstellen': 'on'})
        a.refresh_from_db(); t.refresh_from_db()
        self.assertIsNotNone(a.kreditoren_rechnung_id)
        self.assertTrue(t.nachrichten.filter(nachricht__contains='Handwerkerrechnung').exists())
        self.assertEqual(t.status, 'in_bearbeitung')          # nur verknüpft, nicht abgeschlossen


@MAIL
class MandantengrenzeNeueUrlsTests(TestCase):
    """Rechnung verknüpfen / Storno: fremder Auftrag oder fremde Rechnung -> 404, nichts geändert.

    Gegenprobe (protokolliert): in `fw_auftrag_storno` `HandwerkerAuftrag.objects` durch
    `.alle_organisationen` ersetzen -> rot.
    """

    def test_fremder_auftrag_storno_und_rechnung_sind_404(self):
        from core.tenancy import organisation_kontext
        from core.tests._isolation import MandantenFixture
        from tickets.models import HandwerkerAuftrag
        eigen_t, eigen_a = _mit_auftrag()
        fremd = MandantenFixture('B', '3000', 'Bern')
        with organisation_kontext(fremd.organisation):
            fremder_auftrag = fremd.auftrag
            fremde_rechnung = fremd.kreditor
        mail.outbox.clear()
        c = Client(); c.force_login(_team_user())
        r1 = c.post(f'/neu/auftrag/{fremder_auftrag.pk}/storno/', {})
        r2 = c.post(f'/neu/auftrag/{fremder_auftrag.pk}/rechnung/', {'rechnung_id': fremde_rechnung.pk})
        # eigener Auftrag, FREMDE Rechnung: darf nicht verknüpfbar sein
        r3 = c.post(f'/neu/auftrag/{eigen_a.pk}/rechnung/', {'rechnung_id': fremde_rechnung.pk})
        self.assertEqual((r1.status_code, r2.status_code, r3.status_code), (404, 404, 404))
        self.assertEqual(len(mail.outbox), 0)
        eigen_a.refresh_from_db()
        self.assertIsNone(eigen_a.kreditoren_rechnung_id)
        with organisation_kontext(fremd.organisation):
            a = HandwerkerAuftrag.objects.get(pk=fremder_auftrag.pk)
            self.assertNotEqual(a.status, 'storniert')
            self.assertIsNone(a.kreditoren_rechnung_id)


@MAIL
class EingangsbestaetigungTests(TestCase):
    """`send_ticket_receipt` schickt im Thread — die Antwortadresse wird vorher bestimmt."""

    def _sofort(self):
        """Thread synchron laufen lassen, damit der Test nicht auf einen Hintergrund-Thread wartet."""
        from unittest import mock

        class SofortThread:
            def __init__(self, target=None, args=(), kwargs=None):
                self._t, self._a, self._k = target, args, kwargs or {}
            def start(self):
                self._t(*self._a, **self._k)
        return mock.patch('core.utils.email_service.threading.Thread', SofortThread)

    def test_eingangsbestaetigung_traegt_den_reply_to_der_verwaltung(self):
        from core.models import Postfach
        from core.utils.email_service import send_ticket_receipt
        t = _ticket()
        Postfach.alle_organisationen.create(organisation=t.organisation, zweck='antworten',
                                            benutzer='antworten@verwaltung-a.ch', server='imap.example.ch')
        mail.outbox.clear()
        with self._sofort():
            send_ticket_receipt(t)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, ['antworten@verwaltung-a.ch'])

    def test_im_thread_laeuft_keine_mandanten_query(self):
        """Der Thread bekommt eine fertige Adresse; `send_via_hoststar` selbst fragt die DB nichts."""
        from unittest import mock
        from core.utils.email_service import send_ticket_receipt
        t = _ticket()
        with self._sofort(), mock.patch('core.utils.email_service.send_via_hoststar') as senden:
            send_ticket_receipt(t)
        self.assertIn('reply_to', senden.call_args.kwargs)


@MAIL
class RechnungIdEingabeTests(TestCase):
    def test_nicht_numerische_rechnungs_id_gibt_meldung_statt_500(self):
        t, a = _mit_auftrag()
        c = Client(); c.force_login(_team_user())
        for wert in ('abc', '', '1; DROP'):
            r = c.post(f'/neu/auftrag/{a.id}/rechnung/', {'rechnung_id': wert})
            self.assertIn(r.status_code, (302, 404), wert)      # nie 500
        a.refresh_from_db()
        self.assertIsNone(a.kreditoren_rechnung_id)
