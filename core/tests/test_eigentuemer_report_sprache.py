"""Eigentümer-Reports folgen der Korrespondenzsprache (D11).

- Portfolio-Report (PDF) und Begleitmail des Report-Versands in
  `Eigentuemer.sprache` — auch der Objekttyp («Appartement» statt «Wohnung»).
- Der Steuerauszug bleibt deutsch (kantonal festgelegte Steuerbegriffe).
- Noch nicht übersetzte Dokumente (Mieterspiegel-PDF) und der Objekt-Feed an
  die Immobilienportale bleiben fest deutsch, auch bei französischer
  Oberfläche: Der jetzt übersetzbare Objekttyp darf dort nicht umschalten.

Gegenproben:
- in core/services/portfolio_report.py `sprache_von(eigentuemer)` in
  `generate_portfolio_report_fuer` durch `'de'` ersetzen —
  `test_report_franzoesisch` wird rot;
- in send_eigentuemer_reports.py `with in_sprache(sprache_von(md)):` durch
  `with in_sprache('de'):` ersetzen — `test_versand_franzoesisch` wird rot;
- in core/services/portal_feed.py `_typ_de(e)` durch `e.get_typ_display()`
  ersetzen — `test_feed_bleibt_deutsch` wird rot;
- in core/views/fw/listen.py den Block `with in_sprache(STANDARD):` im
  Mieterspiegel entfernen (Inhalt ausrücken) — `test_mieterspiegel_pdf_bleibt_deutsch`
  wird rot.
"""
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase
from django.utils import translation

from core.services import portal_feed, portfolio_report
from core.tests._helfer import _basis_objekte, _team_user
from portfolio.models import Einheit


def _daten():
    """Wie `_portfolio_daten`: der Typ wird beim Lesen beschriftet."""
    return {
        'liegenschaften': [{'adresse': 'Rue 1, Lausanne', 'soll_monat': 1800, 'rendite': 4.2,
                            'einheiten': [{'bezeichnung': '3.5 p.', 'typ': Einheit(typ='whg').get_typ_display(),
                                           'mieter': None, 'brutto': 0}]}],
        'total_einheiten': 1, 'total_vermietet': 0, 'leerquote': 100.0,
        'total_soll': 0, 'jahres_soll': 0, 'bruttorendite': None,
    }


class ReportTests(SimpleTestCase):

    def _texte(self, sprache):
        texte = []
        leinwand = mock.MagicMock()
        leinwand.drawString.side_effect = lambda _x, _y, t: texte.append(t)
        leinwand.drawRightString.side_effect = lambda _x, _y, t: texte.append(t)
        md = SimpleNamespace(firma_oder_name='Dupont SA', sprache=sprache)
        with mock.patch.object(portfolio_report.canvas, 'Canvas', return_value=leinwand), \
                mock.patch('core.views.portal._portfolio_daten', side_effect=lambda _md: _daten()), \
                translation.override('de'):
            portfolio_report.generate_portfolio_report_fuer(md)
        return texte

    def test_report_franzoesisch(self):
        texte = self._texte('fr')
        self.assertIn('Rapport de portefeuille', texte)
        self.assertIn('VACANT', texte)
        self.assertTrue(any('Appartement' in t for t in texte), texte)

    def test_report_deutsch(self):
        texte = self._texte('de')
        self.assertIn('Portfolio-Report', texte)
        self.assertTrue(any('Wohnung' in t for t in texte), texte)


class TypBeschriftungTests(SimpleTestCase):

    def test_typ_folgt_der_sprache_gespeichert_bleibt_der_code(self):
        e = Einheit(typ='whg')
        with translation.override('fr'):
            self.assertEqual(str(e.get_typ_display()), 'Appartement')
        self.assertEqual(e.typ, 'whg')

    def test_feed_bleibt_deutsch(self):
        """Der Feed-Eintrag selbst, nicht nur die Hilfsfunktion."""
        e = Einheit(typ='whg', bezeichnung='3.5 Zi')
        with translation.override('fr'):
            self.assertEqual(portal_feed._typ_de(e), 'Wohnung')
            quelle = open(portal_feed.__file__, encoding='utf-8').read()
            self.assertIn("'typ_label': _typ_de(e)", quelle)


class VersandTests(TestCase):

    def test_versand_franzoesisch(self):
        from crm.models import Eigentuemer
        from core.management.commands import send_eigentuemer_reports  # noqa: F401
        _team_user()   # Organisation und Kontext
        Eigentuemer.objects.create(firma_oder_name='Dupont SA', email='d@example.ch', sprache='fr')
        steuer_sprache = []

        def steuer(_md, _jahr):
            steuer_sprache.append(translation.get_language())
            return b'%PDF'

        with mock.patch('core.services.portfolio_report.generate_portfolio_report_fuer', return_value=b'%PDF'), \
                mock.patch('core.services.steuerauszug.generate_steuerauszug_pdf', side_effect=steuer), \
                mock.patch('core.utils.email_service.send_report_mail', return_value=True) as senden, \
                translation.override('de'):
            call_command('send_eigentuemer_reports', '--jahr', '2025', stdout=mock.MagicMock(), stderr=mock.MagicMock())
        _an, betreff, html, _anhaenge = senden.call_args.args
        self.assertEqual(betreff, 'Votre rapport immobilier 2025')
        self.assertIn('Bonjour Dupont SA', html)
        self.assertNotIn('Liegenschaften', html)
        # Der Steuerauszug bleibt deutsch.
        self.assertEqual(steuer_sprache, ['de'])


class MieterspiegelTests(TestCase):

    def test_mieterspiegel_pdf_bleibt_deutsch(self):
        lg, _e, _m, _v = _basis_objekte()
        c = Client()
        c.force_login(_team_user())
        c.cookies['django_language'] = 'fr'
        typen = []

        def pdf(spiegel, *_a, **_k):
            typen.extend(str(z['typ']) for b in spiegel for z in b['zeilen'])
            return b'%PDF'

        with mock.patch('core.services.mieterspiegel.generate_mieterspiegel_pdf', side_effect=pdf):
            antwort = c.get(f'/neu/mieterspiegel/?lg={lg.id}&pdf=1')
        self.assertEqual(antwort.status_code, 200)
        self.assertIn('Wohnung', typen)
