"""E-Mails an Mieter folgen der Korrespondenzsprache (D11).

Zahlungserinnerung und Portal-Zugang gehen in `Mieter.sprache` raus, nicht in
der Sprache der Sachbearbeitung. Das Journal (liest die Verwaltung) bleibt
deutsch.

Gegenprobe: in core/utils/email_service.py den Block
`with in_sprache(sprache_von(mieter)):` bzw. `with in_sprache(sprache):` durch
eine feste Sprache ersetzen — die Tests der jeweils anderen Sprache werden rot.
"""
import datetime
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from django.utils import translation

from core.utils import email_service

WURZEL = Path(__file__).resolve().parents[2]


def _vertrag(sprache):
    mieter = SimpleNamespace(id=7, vorname='Anna', nachname='Muster', email='anna@example.ch', sprache=sprache)
    return SimpleNamespace(id=11, mieter=mieter, einheit=SimpleNamespace(bezeichnung='3.5 Zi. EG'))


class ZahlungserinnerungSpracheTests(SimpleTestCase):

    def _senden(self, sprache, oberflaeche):
        with mock.patch.object(email_service.threading, 'Thread') as thread, \
                mock.patch.object(email_service, 'journal_email') as journal, \
                translation.override(oberflaeche):
            email_service.send_payment_reminder(_vertrag(sprache), datetime.date(2024, 5, 1), Decimal('1500'))
        _an, betreff, html = thread.call_args.kwargs['args']
        return betreff, html, journal.call_args.args[1]

    def test_franzoesische_mieterin_deutsche_oberflaeche(self):
        betreff, html, journal = self._senden('fr', 'de')
        self.assertEqual(betreff, 'Rappel de paiement : loyer mai 2024 - 3.5 Zi. EG')
        self.assertIn('Montant dû : CHF 1,500.00', html)
        self.assertNotIn('Zahlungserinnerung', html)
        # Das Journal liest die Verwaltung — deutsch.
        self.assertEqual(journal, 'Zahlungserinnerung Miete Mai 2024 · offen CHF 1,500.00')

    def test_deutsche_mieterin_franzoesische_oberflaeche(self):
        betreff, html, _j = self._senden('de', 'fr')
        self.assertEqual(betreff, 'Zahlungserinnerung: Miete Mai 2024 - 3.5 Zi. EG')
        self.assertNotIn('Rappel', html)


class PortalZugangSpracheTests(SimpleTestCase):

    def test_italienisch(self):
        with mock.patch.object(email_service, 'send_via_hoststar', return_value=True) as senden, \
                translation.override('de'):
            email_service.send_mieter_portal_zugang('a@example.ch', 'Signora Muster', 'amuster', 'geheim',
                                                    'https://x/portal/login/', sprache='it')
        _an, betreff, html = senden.call_args.args
        self.assertEqual(betreff, 'Il suo accesso al portale degli inquilini')
        self.assertIn('Accedi ora', html)
        self.assertNotIn('Jetzt einloggen', html)


class KeinGettextInFStringsTests(SimpleTestCase):
    """xgettext liest das Innere von f-Strings nicht. `{gettext('…')}` in einem
    f-String wird deshalb NIE in den Katalog übernommen — die Übersetzung
    fehlt still, der Text bleibt deutsch. Genau so passiert am 29.09.2026 in
    email_service.py (19 Texte). Gegenprobe: eine Zeile
    `x = f"{gettext('Test')}"` in email_service.py — der Test wird rot."""

    def test_email_service(self):
        text = (WURZEL / 'core/utils/email_service.py').read_text(encoding='utf-8')
        funde = re.findall(r"\{\s*(?:gettext|ngettext|pgettext|_)\(\s*['\"]", text)
        self.assertEqual(funde, [])
