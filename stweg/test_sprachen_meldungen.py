"""Meldungen, Fehlertexte und Bezeichnungen der Verwaltung erscheinen in der gewählten Sprache;
Rechtsdokumente (PDF) bleiben deutsch (D11)."""
import io
from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone, translation
from django.utils.html import escape
from pypdf import PdfReader

from core.tests._helfer import _team_user
from stweg import budget as bd
from stweg.beschluss import BeschlussFehler, feststellen
from stweg.models import StwegBudget, Traktandum, Versammlung
from stweg.pdf import protokoll_pdf
from stweg.schluessel import standard_schluessel
from stweg.test_budget import haus_mit_eigentuemern


class MeldungenSprachenTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.client.force_login(_team_user('Verwaltung'))
        self.base = f'/neu/stweg/{self.lg.pk}'

    def sprache(self, code):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = code

    def test_flash_meldung_in_drei_sprachen(self):
        for code, erwartet in (('de', 'Jahr und eine Ratenzahl'), ('fr', "Une année et un nombre d'acomptes"),
                               ('it', 'Sono necessari un anno e un numero di rate'),
                               ('en', 'A year and a number of instalments')):
            self.sprache(code)
            r = self.client.post(f'{self.base}/budget/neu/', {'jahr': '2026', 'raten': '5'}, follow=True)
            self.assertContains(r, escape(erwartet), msg_prefix=code)

    def test_meldung_mit_platzhalter_wird_ersetzt(self):
        b = StwegBudget.objects.create(liegenschaft=self.lg, jahr=2026)
        self.sprache('fr')
        r = self.client.post(f'{self.base}/budget/neu/', {'jahr': '2026', 'raten': '4'}, follow=True)
        self.assertContains(r, 'Il existe déjà un budget pour 2026.')
        self.assertNotContains(r, '%(jahr)s')
        self.assertEqual(StwegBudget.objects.count(), 1)
        self.assertEqual(b.pk, StwegBudget.objects.get().pk)

    def test_service_fehler_folgt_der_aktiven_sprache(self):
        b = StwegBudget.objects.create(liegenschaft=self.lg, jahr=2026)
        for code, erwartet in (('de', 'muss grösser 0 sein'), ('fr', 'doit être supérieur à 0'),
                               ('it', 'deve essere maggiore di 0'), ('en', 'must be greater than 0')):
            with translation.override(code), self.assertRaisesRegex(bd.BudgetFehler, erwartet):
                bd.position_setzen(b, 'x', standard_schluessel(self.lg), -5)

    def test_mehrheitsarten_und_status_sind_uebersetzt(self):
        v = Versammlung.objects.create(liegenschaft=self.lg, titel='OV', datum=timezone.now() + timedelta(days=20))
        self.sprache('fr')
        seite = self.client.get(f'/neu/stweg/versammlung/{v.pk}/').content.decode()
        self.assertIn('Majorité des propriétaires présents ET plus de la moitié de toutes les quotes-parts', seite)
        self.assertNotIn('Mehrheit der anwesenden Eigentümer', seite)
        self.assertIn('Assemblée ordinaire', seite)

    def test_beschlussfehler_auf_franzoesisch_mit_platzhalter(self):
        v = Versammlung.objects.create(liegenschaft=self.lg, titel='OV', datum=timezone.now(), status='durchgefuehrt')
        t = Traktandum.objects.create(versammlung=v, nr=1, titel='X')
        with translation.override('fr'), self.assertRaises(BeschlussFehler) as ctx:
            feststellen(t, 'quatsch')
        self.assertEqual(str(ctx.exception), 'Résultat invalide « quatsch ».')

    def test_pdf_bleibt_deutsch_auch_in_franzoesischer_sitzung(self):
        v = Versammlung.objects.create(liegenschaft=self.lg, titel='OV', datum=timezone.now(), status='durchgefuehrt')
        Traktandum.objects.create(versammlung=v, nr=1, titel='X', mehrheitsart='doppelt_anwesende')
        with translation.override('fr'):
            text = ''.join(p.extract_text() for p in PdfReader(io.BytesIO(protokoll_pdf(v))).pages)
        self.assertIn('Protokoll der Ordentliche Versammlung', text)
        self.assertNotIn('Assemblée', text)
