"""Roadmap Nr. 24: Mail-HTML steht in Vorlagen (templates/emails), nicht in Python-Strings.

Geprüft wird, was ein Empfänger bekommt: der Inhalt kommt an, Werte sind escaped (vorher setzten die
Zugangs-Mails Benutzername, Passwort und Link ungeschützt ein), die Markenfarbe stammt aus einer Stelle.
"""
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.test import TestCase

from core.services.druckfarben import EMBER
from core.utils import email_service

from ._helfer import _basis_objekte


class _SofortThread:
    """Führt das Ziel sofort aus: Die Mails laufen im Betrieb in einem Thread, der Test will sie lesen."""

    def __init__(self, target=None, args=(), kwargs=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


class ZugangsMailTests(TestCase):

    def _senden(self, funktion):
        funktion('x@example.ch', 'Frau Muster', '<script>alert(1)</script>', 'p&ss"wort',
                 'https://example.ch/login/?a=1&b=2', absender_firma='Muster <AG>')
        return mail.outbox[-1].body

    def test_mieter_zugang_escaped_und_vollstaendig(self):
        html = self._senden(email_service.send_mieter_portal_zugang)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertIn('p&amp;ss&quot;wort', html)
        self.assertIn('Muster &lt;AG&gt;', html)
        self.assertIn('https://example.ch/login/?a=1&amp;b=2', html)
        self.assertIn(EMBER, html)
        self.assertIn('Mieterportal', html)

    def test_eigentuemer_zugang_nutzt_denselben_rahmen(self):
        html = self._senden(email_service.send_eigentuemer_portal_zugang)
        self.assertNotIn('<script>', html)
        self.assertIn('Eigentümer-Portal', html)
        self.assertIn('🏠', html)
        self.assertIn(EMBER, html)


class ZahlungserinnerungTests(TestCase):

    def test_erinnerung_inhalt_und_escaping(self):
        from datetime import date
        lg, einheit, mieter, vertrag = _basis_objekte()
        einheit.bezeichnung = 'Whg <b>3</b>'
        einheit.save()
        mieter.email = 'mieter@example.ch'
        mieter.save()
        with mock.patch.object(email_service.threading, 'Thread', _SofortThread):
            email_service.send_payment_reminder(vertrag, date(2026, 10, 1), Decimal('1700.5'))
        html = mail.outbox[-1].body
        self.assertIn('Whg &lt;b&gt;3&lt;/b&gt;', html)
        self.assertNotIn('Whg <b>3</b>', html)
        self.assertIn('<strong>', html)                       # die Auszeichnung des Textes bleibt
        self.assertIn('1,700.50', html)


class MeldungsMailTests(TestCase):

    def setUp(self):
        from tickets.models import SchadenMeldung
        self.lg, self.einheit, self.mieter, self.vertrag = _basis_objekte()
        self.ticket = SchadenMeldung.objects.create(
            titel='Heizung <i>kalt</i>', liegenschaft=self.lg, betroffene_einheit=self.einheit,
            beschreibung='Zeile 1 <script>x</script>', email_melder='melder@example.ch',
            melder_vorname='Anna', melder_nachname='Muster')

    def test_interne_meldung(self):
        self.assertTrue(email_service.send_neue_meldung_intern(self.ticket, ['v@example.ch']))
        html = mail.outbox[-1].body
        self.assertIn(f'#{self.ticket.id}', html)
        self.assertIn('Heizung &lt;i&gt;kalt&lt;/i&gt;', html)
        self.assertNotIn('<script>', html)
        self.assertIn('Anna Muster', html)
        self.assertIn(EMBER, html)

    def test_eingangsbestaetigung(self):
        with mock.patch.object(email_service.threading, 'Thread', _SofortThread):
            email_service.send_ticket_receipt(self.ticket)
        html = mail.outbox[-1].body
        self.assertIn(f'#{self.ticket.id}', html)
        self.assertIn('Heizung &lt;i&gt;kalt&lt;/i&gt;', html)
        self.assertEqual(mail.outbox[-1].to, ['melder@example.ch'])


class KlartextMitLinkTests(TestCase):

    def test_text_wird_maskiert_und_link_zum_anker(self):
        link = 'https://example.ch/auftrag/abc/?a=1&b=2'
        html = email_service.klartext_html(f'Hallo <script>x</script>\nZeile 2\n{link}', link)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('<br>', html)
        self.assertIn('<a href="https://example.ch/auftrag/abc/?a=1&amp;b=2">https://example.ch/auftrag/abc/?a=1&amp;b=2</a>', html)

    def test_ohne_link_bleibt_text_text(self):
        html = email_service.klartext_html('Nur Text & mehr')
        self.assertIn('Nur Text &amp; mehr', html)
        self.assertNotIn('<a ', html)

    def test_gegenprobe_fremdes_html_im_link_wird_nicht_aktiv(self):
        html = email_service.klartext_html('x', 'javascript:"><script>')
        self.assertNotIn('<script>', html)


class StwegMitteilungTests(TestCase):

    def test_werte_escaped_auszeichnung_bleibt(self):
        from django.utils.html import format_html
        from crm.models import Eigentuemer
        lg, _e, _m, _v = _basis_objekte()          # legt die Verwaltung an; der Eigentümer gehört ihr
        from core.tenancy import organisation_kontext
        with organisation_kontext(lg.organisation):
            eigentuemer = Eigentuemer.objects.create(firma_oder_name='Eigentümer <i>Muster</i>')
        html = email_service.stweg_mail_html(
            eigentuemer, [format_html('Abstimmung «{}» bis <strong>{}</strong>', '<b>X</b>', '01.01.2027'),
                     ('Zeile 1\nZeile 2', True)], 'Muster <AG>')
        self.assertIn('«&lt;b&gt;X&lt;/b&gt;»', html)
        self.assertIn('<strong>01.01.2027</strong>', html)
        self.assertIn('white-space:pre-line', html)
        self.assertIn('Muster &lt;AG&gt;', html)
        self.assertIn('Freundliche Grüsse', html)
        self.assertNotIn('<i>Muster</i>', html)           # auch der Gruss ist maskiert
        self.assertNotIn('Kündigung', html)               # `ohne_kuendigung` darf auf dem Rahmen nie anschlagen
