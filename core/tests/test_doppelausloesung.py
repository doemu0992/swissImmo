"""Doppelauslösung (Audit B4, B6, B7): Was zweimal abgeschickt wird, wirkt nur einmal.

B4  Mieter-Kündigung im Portal: ein zweiter Klick legt keine zweite Kündigung an und schickt keine zweite Mail.
B6  Besichtigungseinladung: abgelehnte oder bereits vertraglich abgeschlossene Bewerbungen und Termine in der
    Vergangenheit werden abgewiesen, es geht keine Mail hinaus.
B7  Terminbestätigung: der Vorschlag wird unter der Sperre verbraucht; eine zweite Bestätigung scheitert.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.utils import timezone

from ._helfer import _basis_objekte, _team_user
from .test_bewerber_board import _bewerbung

User = get_user_model()


class MieterKuendigungEinmalTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.mu = User.objects.create_user(username='mieter_dk', password='x')
        self.m.benutzer = self.mu
        self.m.save()
        self.c = Client()
        self.c.force_login(self.mu)

    def _senden(self):
        return self.c.post('/mieter/kuendigung/', {'vertrag_id': self.v.id}, follow=True)

    def test_zweiter_klick_legt_keine_zweite_kuendigung_an(self):
        from rentals.models import Kuendigung
        self._senden()
        self.assertEqual(Kuendigung.objects.filter(vertrag=self.v).count(), 1)
        mails = len(mail.outbox)
        r = self._senden()
        self.assertEqual(Kuendigung.objects.filter(vertrag=self.v).count(), 1)
        self.assertEqual(len(mail.outbox), mails)                      # keine zweite Mail an die Verwaltung
        self.assertContains(r, 'bereits eine Kündigung')

    def test_nach_zurueckgezogener_kuendigung_ist_eine_neue_moeglich(self):
        """Gegenprobe: Nur offene Kündigungen sperren."""
        from rentals.models import Kuendigung
        self._senden()
        Kuendigung.objects.filter(vertrag=self.v).update(status='zurueckgezogen')
        self._senden()
        self.assertEqual(Kuendigung.objects.filter(vertrag=self.v).count(), 2)


class BesichtigungsEinladungTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def _einladen(self, b, wann):
        return self.c.post(f'/neu/bewerbungen/{b.pk}/besichtigung/',
                           {'termin': timezone.localtime(wann).strftime('%Y-%m-%dT%H:%M')})

    def test_zukuenftiger_termin_wird_eingeladen(self):
        b = _bewerbung(self.e)
        mail.outbox.clear()
        self._einladen(b, timezone.now() + timedelta(days=3))
        b.refresh_from_db()
        self.assertEqual(b.status, 'besichtigung')
        self.assertEqual(len(mail.outbox), 1)

    def test_abgelehnte_bewerbung_bekommt_keine_einladung(self):
        b = _bewerbung(self.e, status='abgelehnt')
        mail.outbox.clear()
        self._einladen(b, timezone.now() + timedelta(days=3))
        b.refresh_from_db()
        self.assertEqual(b.status, 'abgelehnt')
        self.assertIsNone(b.besichtigung_am)
        self.assertEqual(mail.outbox, [])

    def test_termin_in_der_vergangenheit_wird_abgewiesen(self):
        b = _bewerbung(self.e)
        mail.outbox.clear()
        self._einladen(b, timezone.now() - timedelta(days=1))
        b.refresh_from_db()
        self.assertIsNone(b.besichtigung_am)
        self.assertEqual(mail.outbox, [])


class TerminBestaetigungEinmalTests(TestCase):

    def test_zweite_bestaetigung_scheitert_und_verschickt_nichts(self):
        from tickets import termin_abstimmung
        from .test_direktkanal import _auftrag_einfach, _zeit
        t, a = _auftrag_einfach()
        termin_abstimmung.vorschlagen(a, 'handwerker', _zeit())
        termin_abstimmung.bestaetigen(a, 'mieter')
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'vereinbart')
        mails = len(mail.outbox)
        with self.assertRaises(ValidationError):
            termin_abstimmung.bestaetigen(a, 'mieter')
        self.assertEqual(len(mail.outbox), mails)

    def test_der_vorschlag_ist_nach_der_sperre_verbraucht(self):
        """Der Zustand «vereinbart» steht schon, bevor Mails und Kalendereintrag rausgehen."""
        from tickets import termin_abstimmung
        from tickets.models import HandwerkerAuftrag
        from .test_direktkanal import _auftrag_einfach, _zeit
        t, a = _auftrag_einfach()
        wann = _zeit()
        termin_abstimmung.vorschlagen(a, 'handwerker', wann)
        gesehen = {}
        original = termin_abstimmung.termin_festlegen

        def spaeh(auftrag, zeit):
            f = HandwerkerAuftrag.alle_organisationen.get(pk=auftrag.pk)
            gesehen['status'], gesehen['vorschlag'] = f.termin_status, f.termin_vorschlag_am
            return original(auftrag, zeit)
        termin_abstimmung.termin_festlegen = spaeh
        try:
            termin_abstimmung.bestaetigen(a, 'mieter')
        finally:
            termin_abstimmung.termin_festlegen = original
        self.assertEqual(gesehen['status'], 'vereinbart')
        self.assertIsNone(gesehen['vorschlag'])
