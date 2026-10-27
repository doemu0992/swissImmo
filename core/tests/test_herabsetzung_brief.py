"""Herabsetzungsbegehren: Antwortbrief und Weg zur Mietzinsanpassung (Befund M, 26.10.2026)."""
import io
from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone
from pypdf import PdfReader

from ._helfer import _basis_objekte, _team_user


class AntwortbriefTests(TestCase):
    def setUp(self):
        from core.models import Pendenz
        _lg, _e, _m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user('Verwaltung'))
        self.heute = timezone.localdate()
        self.c.post(f'/neu/vertraege/{self.v.id}/herabsetzung/', {
            'aktion': 'eingang', 'eingang_datum': (self.heute - timedelta(days=5)).isoformat()})
        self.p = Pendenz.objects.get(vertrag=self.v, quelle__startswith='270a:')

    def _antwort(self, **extra):
        daten = {'aktion': 'antwort', 'pendenz': self.p.pk, 'ergebnis': 'ablehnung',
                 'antwort_datum': self.heute.isoformat()}
        daten.update(extra)
        return self.c.post(f'/neu/vertraege/{self.v.id}/herabsetzung/', daten)

    def test_brief_wird_abgelegt_und_nennt_die_anrufungsfrist(self):
        from rentals.models import Dokument
        r = self._antwort(brief='1', begruendung='Kosten und Teuerung gleichen die Senkung aus')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        text = ' '.join(s.extract_text() for s in PdfReader(io.BytesIO(r.content)).pages)
        self.assertIn('Art. 270a Abs. 3 OR', text)
        self.assertIn('Kosten und Teuerung', text)
        self.assertIn(self.v.organisation.firma, text)          # Briefkopf der eigenen Verwaltung
        self.assertTrue(Dokument.objects.filter(vertrag=self.v,
                                                bezeichnung__startswith='Antwort Herabsetzungsbegehren').exists())

    def test_zustimmung_nennt_neuen_mietzins_und_bietet_die_anpassung_an(self):
        r = self._antwort(brief='1', ergebnis='zustimmung', neu_netto='1456.35',
                          wirksam_ab=(self.heute + timedelta(days=60)).isoformat())
        text = ' '.join(s.extract_text() for s in PdfReader(io.BytesIO(r.content)).pages)
        self.assertIn("1'456.35", text)
        self.assertNotIn('Art. 270a Abs. 3', text)               # volle Zustimmung: keine Anrufung nötig
        seite = self.c.get(f'/neu/vertraege/{self.v.id}/herabsetzung/').content.decode()
        self.assertIn(f'/neu/mietzins/{self.v.id}/anpassung/', seite)

    def test_ohne_brief_bleibt_es_beim_festhalten(self):
        from rentals.models import Dokument
        r = self._antwort()
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Dokument.objects.filter(vertrag=self.v,
                                                 bezeichnung__startswith='Antwort Herabsetzungsbegehren').exists())
        self.assertEqual(Decimal('1500.00'), self.v.effektiver_netto_mietzins(self.heute))
