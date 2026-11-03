"""Ticket abschliessen ohne Handwerkerrechnung: ausdrücklicher Weg mit Begründung.

Die Sperre «kein Abschluss ohne Rechnung» (tickets/workflow.py) bleibt das Standardverhalten.
Neu ist ein bewusster Weg: Begründung aus einer Liste (plus Freitext), festgehalten am Auftrag
(wer, wann, warum), im Verlauf sichtbar. «Rechnung folgt später» legt eine Pendenz an, die das
Verknüpfen der Rechnung erledigt.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from ._helfer import _team_user
from .test_ticket_workflow import _handwerker, _mit_auftrag, _rechnung, _ticket

MAIL = override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')


def _url(t):
    return f'/neu/schaeden/{t.id}/ohne-rechnung/'


def _benutzer_mit_rolle(rolle, name):
    from crm.models import Mitgliedschaft
    from ._helfer import _test_organisation
    u = get_user_model().objects.create_user(username=name, password='x')
    Mitgliedschaft.objects.create(benutzer=u, organisation=_test_organisation(), rolle=rolle)
    return u


class OhneRechnungAnsichtTests(TestCase):
    def setUp(self):
        self.t, self.a = _mit_auftrag()
        self.c = Client()
        self.c.force_login(_team_user())

    def test_ticket_mit_auftrag_ohne_rechnung_laesst_sich_mit_begruendung_abschliessen(self):
        r = self.c.post(_url(self.t), {'grund': 'kostenlos', 'text': 'Garantie, Hersteller tauscht'})
        self.assertEqual(r.status_code, 302)
        self.t.refresh_from_db()
        self.a.refresh_from_db()
        self.assertEqual(self.t.status, 'erledigt')
        self.assertEqual(self.a.ohne_rechnung_grund, 'kostenlos')
        self.assertIn('Garantie', self.a.ohne_rechnung_text)
        self.assertIsNotNone(self.a.ohne_rechnung_von_id)
        self.assertIsNotNone(self.a.ohne_rechnung_am)

    def test_begruendung_steht_im_verlauf_mit_person(self):
        self.c.post(_url(self.t), {'grund': 'eigenleistung', 'text': 'Hauswart hat die Dichtung getauscht'})
        n = self.t.nachrichten.filter(typ='system', nachricht__contains='ohne Rechnung').get()
        self.assertIn('Eigenleistung', n.nachricht)
        self.assertIn('team_Verwaltung', n.nachricht)
        self.assertIn('Dichtung', n.nachricht)

    def test_ohne_grund_bleibt_es_gesperrt(self):
        for grund in ('', 'quatsch'):
            r = self.c.post(_url(self.t), {'grund': grund}, follow=True)
            self.t.refresh_from_db()
            self.assertEqual(self.t.status, 'in_bearbeitung', grund)
            self.assertContains(r, 'Grund')
        self.a.refresh_from_db()
        self.assertEqual(self.a.ohne_rechnung_grund, '')

    def test_anderer_grund_braucht_freitext(self):
        self.c.post(_url(self.t), {'grund': 'anderer', 'text': '  '})
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'in_bearbeitung')
        self.c.post(_url(self.t), {'grund': 'anderer', 'text': 'Vergleich mit dem Eigentümer'})
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'erledigt')

    def test_standardweg_bleibt_gesperrt_und_nennt_die_optionen(self):
        r = self.c.post(f'/neu/schaeden/{self.t.id}/status/', {'status': 'erledigt'}, follow=True)
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'in_bearbeitung')
        self.assertContains(r, 'Ohne Rechnung abschliessen')      # die Meldung nennt den Weg …
        self.assertContains(r, 'id="ohne-rechnung"')              # … und die Seite hat das Formular dafür

    def test_aus_warte_auf_handwerker_ueber_den_ausdruecklichen_weg(self):
        from tickets.workflow import UngueltigerUebergang, wechsle_status
        wechsle_status(self.t, 'warte_auf_handwerker')
        with self.assertRaises(UngueltigerUebergang):              # der gewöhnliche Weg bleibt zu
            wechsle_status(self.t, 'erledigt')
        r = self.c.post(_url(self.t), {'grund': 'nicht_ausgefuehrt'})
        self.assertEqual(r.status_code, 302)
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'erledigt')

    def test_get_aendert_nichts(self):
        r = self.c.get(_url(self.t))
        self.assertEqual(r.status_code, 302)
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'in_bearbeitung')

    def test_ticket_ohne_auftrag_bleibt_ohne_weiteres_abschliessbar(self):
        t = _ticket()
        self.c.post(f'/neu/schaeden/{t.id}/status/', {'status': 'erledigt'})
        t.refresh_from_db()
        self.assertEqual(t.status, 'erledigt')

    @MAIL
    def test_melder_bekommt_die_erledigt_mail(self):
        self.c.post(_url(self.t), {'grund': 'kostenlos', 'melder_informieren': 'on'})
        self.assertEqual([m.to for m in mail.outbox if m.to == ['hans@example.ch']], [['hans@example.ch']])
        mail.outbox.clear()
        t2, _a2 = _mit_auftrag()
        self.c.post(_url(t2), {'grund': 'kostenlos'})              # Haken nicht gesetzt: keine Mail
        self.assertEqual(len(mail.outbox), 0)

    def test_save_sperre_bleibt_fuer_skripte_und_admin(self):
        self.t.status = 'erledigt'
        with self.assertRaises(ValidationError):
            self.t.save()
        from tickets.workflow import ohne_rechnung_freigeben
        ohne_rechnung_freigeben(self.a, 'kostenlos')
        self.t.status = 'erledigt'
        self.t.save()                                             # die Freigabe wird geprüft, nichts umgangen
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'erledigt')


class OhneRechnungRechteTests(TestCase):
    def setUp(self):
        from crm.models import Mitgliedschaft
        self.t, self.a = _mit_auftrag()
        self.hauswart = _benutzer_mit_rolle(Mitgliedschaft.ROLLE_HAUSWART, 'hw1')
        self.t.liegenschaft.hauswarte.add(self.hauswart)
        self.lesend = _benutzer_mit_rolle(Mitgliedschaft.ROLLE_LESEZUGRIFF, 'les1')

    def test_hauswart_und_lesezugriff_duerfen_nicht_ohne_rechnung_abschliessen(self):
        for u in (self.hauswart, self.lesend):
            c = Client()
            c.force_login(u)
            r = c.post(_url(self.t), {'grund': 'kostenlos'})
            self.assertEqual(r.status_code, 403, u.username)
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'in_bearbeitung')

    def test_hauswart_sieht_die_sperre_aber_kein_formular(self):
        c = Client()
        c.force_login(self.hauswart)
        r = c.post(f'/neu/schaeden/{self.t.id}/status/', {'status': 'erledigt'}, follow=True)
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'in_bearbeitung')
        self.assertContains(r, 'nur die Verwaltung')
        self.assertNotContains(r, f'/neu/schaeden/{self.t.id}/ohne-rechnung/')

    def test_hauswart_kann_mit_rechnung_weiter_abschliessen(self):
        """Unverändert: Der Hauswart schliesst ein Ticket, dessen Rechnung verknüpft ist."""
        from tickets.workflow import rechnung_verknuepfen
        rechnung_verknuepfen(self.a, _rechnung(self.t), abschliessen=False)
        c = Client()
        c.force_login(self.hauswart)
        c.post(f'/neu/schaeden/{self.t.id}/status/', {'status': 'erledigt'})
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'erledigt')

    def test_fremde_verwaltung_bekommt_404(self):
        from core.tenancy import organisation_kontext
        from core.tests._isolation import MandantenFixture
        fremd = MandantenFixture('B', '3000', 'Bern')
        with organisation_kontext(fremd.organisation):
            fremdes_ticket = fremd.schaden
        c = Client()
        c.force_login(_team_user())
        r = c.post(_url(fremdes_ticket), {'grund': 'kostenlos'})
        self.assertEqual(r.status_code, 404)
        with organisation_kontext(fremd.organisation):
            fremdes_ticket.refresh_from_db()
            self.assertNotEqual(fremdes_ticket.status, 'erledigt')


class OhneRechnungPendenzTests(TestCase):
    def setUp(self):
        self.t, self.a = _mit_auftrag()
        self.c = Client()
        self.c.force_login(_team_user())

    def _pendenz(self):
        from core.models import Pendenz
        return Pendenz.objects.filter(quelle__startswith='ticket:rechnung_ausstehend:')

    def test_folgt_spaeter_legt_pendenz_mit_gewaehlter_frist_an(self):
        self.c.post(_url(self.t), {'grund': 'folgt_spaeter', 'frist_tage': '14'})
        p = self._pendenz().get()
        self.assertEqual(p.faellig_am, timezone.localdate() + timedelta(days=14))
        self.assertFalse(p.erledigt)
        self.assertIn(f'Ticket #{self.t.id}', p.titel)
        self.assertEqual(p.liegenschaft_id, self.t.liegenschaft_id)

    def test_verknuepfen_der_rechnung_erledigt_die_pendenz(self):
        from tickets.workflow import rechnung_verknuepfen
        self.c.post(_url(self.t), {'grund': 'folgt_spaeter'})
        self.assertFalse(self._pendenz().get().erledigt)
        rechnung_verknuepfen(self.a, _rechnung(self.t))
        p = self._pendenz().get()
        self.assertTrue(p.erledigt)
        self.assertEqual(p.erledigt_am, timezone.localdate())
        self.a.refresh_from_db()
        self.assertIsNotNone(self.a.kreditoren_rechnung_id)

    def test_automatik_raeumt_die_pendenz_nicht_ab(self):
        """`generate_auto_pendenzen` erledigt «auto:rechnung:…»; diese Pendenz darf davon nicht erfasst werden."""
        from core.services.automation import generate_auto_pendenzen
        self.c.post(_url(self.t), {'grund': 'folgt_spaeter'})
        generate_auto_pendenzen(horizont_tage=30)
        self.assertFalse(self._pendenz().get().erledigt)

    def test_andere_gruende_legen_keine_pendenz_an(self):
        self.c.post(_url(self.t), {'grund': 'kostenlos'})
        self.assertFalse(self._pendenz().exists())

    def test_ungueltige_frist_wird_abgelehnt(self):
        self.c.post(_url(self.t), {'grund': 'folgt_spaeter', 'frist_tage': '3650'})
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'in_bearbeitung')
        self.assertFalse(self._pendenz().exists())


class OhneRechnungMehrereAuftraegeTests(TestCase):
    def test_nur_der_auftrag_ohne_rechnung_wird_freigegeben(self):
        from tickets.workflow import handwerker_zuweisen, ohne_rechnung_abschliessen, rechnung_verknuepfen
        t, a1 = _mit_auftrag()
        a2 = handwerker_zuweisen(t, _handwerker())
        rechnung_verknuepfen(a1, _rechnung(t))
        ohne_rechnung_abschliessen(t, 'kostenlos', user=_team_user())
        a1.refresh_from_db()
        a2.refresh_from_db()
        t.refresh_from_db()
        self.assertEqual(t.status, 'erledigt')
        self.assertEqual(a1.ohne_rechnung_grund, '')              # hat eine Rechnung, braucht keine Freigabe
        self.assertEqual(a2.ohne_rechnung_grund, 'kostenlos')

    def test_stornierter_auftrag_wird_nicht_freigegeben(self):
        from tickets.workflow import handwerker_zuweisen, ohne_rechnung_abschliessen
        t, a1 = _mit_auftrag()
        a2 = handwerker_zuweisen(t, _handwerker())
        a1.status = 'storniert'
        a1.save()
        ohne_rechnung_abschliessen(t, 'kostenlos', user=_team_user())
        a1.refresh_from_db()
        a2.refresh_from_db()
        self.assertEqual((a1.ohne_rechnung_grund, a2.ohne_rechnung_grund), ('', 'kostenlos'))

    def test_wiedereroeffnen_und_erneut_abschliessen(self):
        from tickets.workflow import ohne_rechnung_abschliessen, rechnung_verknuepfen, wechsle_status
        t, a = _mit_auftrag()
        ohne_rechnung_abschliessen(t, 'folgt_spaeter', user=_team_user())
        wechsle_status(t, 'in_bearbeitung')
        wechsle_status(t, 'erledigt')                             # Freigabe gilt weiter, kein zweiter Dialog
        rechnung_verknuepfen(a, _rechnung(t))                     # die Rechnung kommt doch noch
        a.refresh_from_db()
        t.refresh_from_db()
        self.assertIsNotNone(a.kreditoren_rechnung_id)
        self.assertEqual(t.status, 'erledigt')


class OhneRechnungStwegTests(TestCase):
    def test_kostentraeger_bleibt_pflicht_und_keine_freigabe_bleibt_zurueck(self):
        from stweg.tests import neue_stweg
        from tickets.models import HandwerkerAuftrag, SchadenMeldung
        from tickets.workflow import KostentraegerFehlt, ohne_rechnung_abschliessen
        lg, einheiten = neue_stweg(status='aktiv')
        t = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=einheiten[0], titel='S',
                                          beschreibung='x', bauteil='bodenbelag', kostentraeger='sonderrecht',
                                          status='in_bearbeitung')
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=_handwerker())
        SchadenMeldung.objects.filter(pk=t.pk).update(kostentraeger='')       # Deklaration fehlt
        t.refresh_from_db()
        with self.assertRaises(KostentraegerFehlt):
            ohne_rechnung_abschliessen(t, 'kostenlos', user=_team_user())
        a.refresh_from_db()
        t.refresh_from_db()
        self.assertEqual(t.status, 'in_bearbeitung')
        self.assertEqual(a.ohne_rechnung_grund, '')               # Transaktion zurückgerollt


class OhneRechnungBoardTests(TestCase):
    def setUp(self):
        from tickets.workflow import wechsle_status
        self.t, self.a = _mit_auftrag()
        wechsle_status(self.t, 'warte_auf_handwerker')
        self.c = Client()
        self.c.force_login(_team_user())

    def test_ziehen_nach_erledigt_ist_gesperrt_und_fuehrt_zur_begruendung(self):
        r = self.c.post(f'/neu/schaeden/{self.t.id}/verschieben/', {'spalte': 'erledigt'},
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 409)
        j = r.json()
        self.assertIn('Ohne Rechnung abschliessen', j['meldung'])
        self.assertTrue(j['weiter'].endswith(f'/neu/schaeden/{self.t.id}/#ohne-rechnung'))
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'warte_auf_handwerker')

    def test_auswahlfeld_bietet_erledigt_an_und_leitet_zur_ticketseite(self):
        r = self.c.get('/neu/schaeden/board/')
        self.assertContains(r, f'id="st-{self.t.id}"')
        self.assertContains(r, '<option value="erledigt">')
        r = self.c.post(f'/neu/schaeden/{self.t.id}/verschieben/', {'status': 'erledigt'})
        self.assertEqual(r.status_code, 302)
        self.assertIn(f'/neu/schaeden/{self.t.id}/', r['Location'])

    def test_board_mit_rechnung_unveraendert(self):
        from tickets.workflow import rechnung_verknuepfen
        rechnung_verknuepfen(self.a, _rechnung(self.t), abschliessen=False)
        r = self.c.post(f'/neu/schaeden/{self.t.id}/verschieben/', {'spalte': 'erledigt'},
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        # warte_auf_handwerker -> erledigt bleibt im Regelweg nicht vorgesehen (nur der ausdrückliche Weg)
        self.assertEqual(r.status_code, 409)
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'warte_auf_handwerker')


class RechnungWegTests(TestCase):
    """Der Weg MIT Rechnung: Grenzfälle."""

    def test_stornierte_rechnung_am_auftrag_sperrt_den_abschluss(self):
        from tickets.workflow import AbschlussGesperrt, rechnung_verknuepfen, wechsle_status
        t, a = _mit_auftrag()
        kr = _rechnung(t)
        rechnung_verknuepfen(a, kr, abschliessen=False)
        kr.status = 'storniert'
        kr.save()
        with self.assertRaises(AbschlussGesperrt):
            wechsle_status(t, 'erledigt')

    def test_neue_rechnung_ersetzt_die_stornierte(self):
        from tickets.workflow import rechnung_verknuepfen
        t, a = _mit_auftrag()
        kr = _rechnung(t)
        rechnung_verknuepfen(a, kr, abschliessen=False)
        kr.status = 'storniert'
        kr.save()
        neu = _rechnung(t, '500')
        rechnung_verknuepfen(a, neu)
        a.refresh_from_db()
        t.refresh_from_db()
        self.assertEqual(a.kreditoren_rechnung_id, neu.pk)
        self.assertEqual(t.status, 'erledigt')

    def test_auftrag_mit_gueltiger_rechnung_wird_nicht_still_ueberschrieben(self):
        from tickets.workflow import rechnung_verknuepfen
        t, a = _mit_auftrag()
        kr = _rechnung(t)
        rechnung_verknuepfen(a, kr, abschliessen=False)
        with self.assertRaises(ValidationError):
            rechnung_verknuepfen(a, _rechnung(t, '90'), abschliessen=False)
        a.refresh_from_db()
        self.assertEqual(a.kreditoren_rechnung_id, kr.pk)

    def test_rechnung_an_anderem_ticket_wird_abgelehnt(self):
        from tickets.workflow import rechnung_verknuepfen
        t1, a1 = _mit_auftrag()
        t2, a2 = _mit_auftrag()
        kr = _rechnung(t1)
        rechnung_verknuepfen(a1, kr, abschliessen=False)
        with self.assertRaises(ValidationError) as ctx:
            rechnung_verknuepfen(a2, kr, abschliessen=False)
        self.assertEqual(ctx.exception.code, 'vergeben')
        a2.refresh_from_db()
        self.assertIsNone(a2.kreditoren_rechnung_id)

    def test_rechnung_einer_anderen_verwaltung_wird_abgelehnt(self):
        from core.tenancy import organisation_kontext
        from core.tests._isolation import MandantenFixture
        from finance.models import KreditorenRechnung
        from tickets.workflow import rechnung_verknuepfen
        t, a = _mit_auftrag()
        fremd = MandantenFixture('B', '3000', 'Bern')
        with organisation_kontext(fremd.organisation):
            fremde = KreditorenRechnung.objects.create(
                liegenschaft=fremd.liegenschaft, lieferant='X', betrag=Decimal('10'), status='neu')
        with self.assertRaises(ValidationError) as ctx:
            rechnung_verknuepfen(a, fremde, abschliessen=False)
        self.assertEqual(ctx.exception.code, 'fremde_organisation')
        # … und über die Ansicht: die fremde Rechnung ist für diese Verwaltung nicht einmal auffindbar (404)
        c = Client()
        c.force_login(_team_user())
        r = c.post(f'/neu/auftrag/{a.pk}/rechnung/', {'rechnung_id': fremde.pk})
        self.assertEqual(r.status_code, 404)

    def test_abschluss_ueber_die_ansicht_mit_melder_mail(self):
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            t, a = _mit_auftrag()
            mail.outbox.clear()
            kr = _rechnung(t)
            c = Client()
            c.force_login(_team_user())
            c.post(f'/neu/auftrag/{a.pk}/rechnung/', {'rechnung_id': kr.pk, 'abschliessen': 'on'})
            t.refresh_from_db()
            self.assertEqual(t.status, 'erledigt')
            self.assertEqual([m.to for m in mail.outbox], [['hans@example.ch']])

    def test_passende_unverknuepfte_rechnung_wird_angeboten(self):
        t, a = _mit_auftrag()
        passend = _rechnung(t, '480')                             # Lieferant 'Sanitär AG' = Firma des Handwerkers
        from finance.models import KreditorenRechnung
        fremd = KreditorenRechnung.objects.create(liegenschaft=t.liegenschaft, lieferant='Elektro GmbH',
                                                  betrag=Decimal('77.00'), status='neu')
        c = Client()
        c.force_login(_team_user())
        r = c.get(f'/neu/schaeden/{t.id}/')
        self.assertContains(r, 'Passende Rechnung gefunden')
        vorschlaege = r.context['auftraege'][0].rechnung_vorschlaege
        self.assertEqual([x.pk for x in vorschlaege], [passend.pk])
        self.assertNotIn(fremd.pk, [x.pk for x in vorschlaege])


class VersicherungsfallTests(TestCase):
    def test_offener_versicherungsfall_blockiert_nicht_und_wird_gemeldet(self):
        from tickets.models import Versicherungsfall
        t, a = _mit_auftrag()
        Versicherungsfall.objects.create(ticket=t, gemeldet_am=timezone.localdate(), status='gemeldet')
        c = Client()
        c.force_login(_team_user())
        r = c.post(_url(t), {'grund': 'kostenlos'}, follow=True)
        t.refresh_from_db()
        self.assertEqual(t.status, 'erledigt')
        self.assertContains(r, 'Versicherungsfall')
