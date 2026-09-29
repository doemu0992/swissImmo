"""Eigentümer haben eine Korrespondenzsprache (D11).

Portal-Zugangsmail und Eigentümerabrechnung (PDF) folgen `Eigentuemer.sprache`,
nicht der Sprache der Sachbearbeitung. Das Formular nimmt nur bekannte Codes an.

Gegenproben:
- in core/utils/email_service.py `with in_sprache(sprache):` in
  `send_eigentuemer_portal_zugang` durch `with in_sprache('de'):` ersetzen —
  `test_portalmail_franzoesisch` wird rot;
- in core/services/mandat_abrechnung.py `sprache_von(eigentuemer)` durch
  `'de'` ersetzen — `test_abrechnung_italienisch` wird rot;
- in core/views/fw/eigentuemer.py `gueltige_sprache(P.get('sprache'))` durch
  `P.get('sprache', 'de')` ersetzen — `test_unbekannter_code_wird_deutsch` wird rot.
"""
import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import Client, SimpleTestCase, TestCase
from django.utils import translation

from core.services import mandat_abrechnung
from core.tests._helfer import _team_user
from core.utils import email_service


class PortalmailTests(SimpleTestCase):

    def _senden(self, sprache):
        with mock.patch.object(email_service, 'send_via_hoststar', return_value=True) as senden, \
                translation.override('de'):
            email_service.send_eigentuemer_portal_zugang(
                'e@example.ch', 'Dupont SA', 'dupont', 'geheim', 'https://x/portal/login/', sprache=sprache)
        _an, betreff, html = senden.call_args.args
        return betreff, html

    def test_portalmail_franzoesisch(self):
        betreff, html = self._senden('fr')
        self.assertEqual(betreff, 'Votre accès au portail propriétaire')
        self.assertIn('Votre portail propriétaire', html)
        self.assertNotIn('Eigentümer-Portal', html)

    def test_portalmail_standard_deutsch(self):
        betreff, html = self._senden('de')
        self.assertEqual(betreff, 'Ihr Zugang zum Eigentümer-Portal')
        self.assertIn('Jetzt einloggen', html)


class AbrechnungTests(SimpleTestCase):

    def _texte(self, sprache):
        """Alle Texte, die auf das PDF gezeichnet werden."""
        texte = []
        leinwand = mock.MagicMock()
        leinwand.drawString.side_effect = lambda _x, _y, t: texte.append(t)
        leinwand.drawRightString.side_effect = lambda _x, _y, t: texte.append(t)
        md = SimpleNamespace(firma_oder_name='Rossi SA', kontaktperson='', strasse='Via 1', plz='6900',
                             ort='Lugano', iban='CH00', sprache=sprache)
        with mock.patch.object(mandat_abrechnung.canvas, 'Canvas', return_value=leinwand), \
                translation.override('de'):
            mandat_abrechnung.generate_mandat_abrechnung_pdf(
                md, 2025, [], {'ertrag': Decimal('0'), 'aufwand': Decimal('0'), 'saldo': Decimal('0')},
                datetime.date(2025, 1, 1), datetime.date(2025, 12, 31))
        return texte

    def test_abrechnung_italienisch(self):
        texte = self._texte('it')
        self.assertIn('Versamento su: CH00', texte)
        self.assertNotIn('Liegenschaft', texte)

    def test_abrechnung_deutsch(self):
        texte = self._texte('de')
        self.assertIn('Eigentümerabrechnung 2025', texte)
        self.assertIn('Auszahlung auf: CH00', texte)


class FormularTests(TestCase):

    def _speichern(self, sprache):
        from crm.models import Eigentuemer
        c = Client()
        c.force_login(_team_user())   # legt die Organisation an und setzt den Kontext
        md = Eigentuemer.objects.create(firma_oder_name='Dupont SA')
        c.post(f'/neu/mandate/{md.id}/bearbeiten/', {'firma_oder_name': 'Dupont SA', 'sprache': sprache})
        md.refresh_from_db()
        return md.sprache

    def test_sprache_wird_gespeichert(self):
        self.assertEqual(self._speichern('fr'), 'fr')

    def test_unbekannter_code_wird_deutsch(self):
        self.assertEqual(self._speichern('xx'), 'de')

    def test_formular_zeigt_auswahl(self):
        from crm.models import Eigentuemer
        c = Client()
        c.force_login(_team_user())
        md = Eigentuemer.objects.create(firma_oder_name='Rossi SA', sprache='it')
        seite = c.get(f'/neu/mandate/{md.id}/bearbeiten/')
        self.assertContains(seite, '<option value="it" selected>', html=False)
