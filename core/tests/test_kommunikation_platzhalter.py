"""Mitteilungs-Assistent: Die Platzhalter der Vorlagen (`{mieter.anrede}`, `{objekt.adresse}`, `{verwaltung.telefon}`, `{frist}`)
lösen sich in Vorschau, Serienbrief-PDF und E-Mail gleich auf.

Anlass (23.11.2026): Die Live-Vorschau kannte nur die alten Kurznamen (`{name}`, `{objekt}`); die Vorlage «Abmahnung» stand mit
allen geschweiften Klammern im Vorschaufeld, das PDF löste nur einen Teil auf, die E-Mail gar nichts.
"""
from datetime import date
from unittest import mock

from django.test import Client, TestCase

from core.tenancy import organisation_kontext

from ._isolation import MandantenFixture

TEXT = ('{mieter.anrede}\n\nwir haben festgestellt, dass Sie Ihre Pflichten aus dem Mietvertrag für {objekt.bezeichnung}, '
        '{objekt.adresse} verletzen.\n\nBis spätestens {frist}. Innert {frist.tage} Tagen.\n\n'
        'Bei Fragen erreichen Sie uns unter {verwaltung.telefon}.\n\nFreundliche Grüsse\n{verwaltung.name}')


class KommunikationPlatzhalterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        cls.a.organisation.telefon = '044 111 22 33'
        cls.a.organisation.save()

    def setUp(self):
        self.c = Client(raise_request_exception=False)
        self.c.force_login(self.a.benutzer)

    def test_vorschau_endpunkt_liefert_die_werte_des_empfaengers(self):
        r = self.c.get('/neu/kommunikation/platzhalter/', {'mieter': self.a.mieter.pk, 'frist_datum': '2026-12-15', 'frist_tage': '10'})
        self.assertEqual(r.status_code, 200)
        k = r.json()
        self.assertEqual(k['mieter.anrede'], 'Sehr geehrter Herr A')
        self.assertEqual(k['objekt.bezeichnung'], '3.5 Zi A')
        self.assertEqual(k['objekt.adresse'], 'A-Weg 7, 8000 Zürich')
        self.assertEqual(k['verwaltung.telefon'], '044 111 22 33')
        self.assertEqual(k['verwaltung.name'], self.a.organisation.firma)
        self.assertEqual(k['frist.datum'], '15.12.2026')
        self.assertEqual(k['frist.datum_lang'], '15. Dezember 2026')
        self.assertEqual(k['frist.tage'], '10')

    def test_vorschau_endpunkt_kennt_keinen_fremden_mieter(self):
        self.assertEqual(self.c.get('/neu/kommunikation/platzhalter/', {'mieter': self.b.mieter.pk}).status_code, 404)
        self.assertEqual(self.c.get('/neu/kommunikation/platzhalter/').status_code, 404)

    def test_seite_liefert_namen_und_aliase_fuer_die_vorschau(self):
        r = self.c.get('/neu/kommunikation/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('mieter.anrede', r.context['platzhalter_namen'])
        self.assertEqual(r.context['platzhalter_aliase']['frist'], 'frist.datum_lang')
        self.assertContains(r, 'id="mk-frist-datum"')

    def test_serienbrief_loest_alle_platzhalter_der_vorlage_auf(self):
        from core.services.serienbrief import _ersetze, empfaenger_kontext
        with organisation_kontext(self.a.organisation):
            _v, ph = empfaenger_kontext(self.a.mieter, self.a.organisation, date(2026, 12, 15), 10)
            aus = _ersetze(TEXT, {'name': 'Mieter A', 'anrede': 'Herr', 'objekt': 'alt', '_ph': ph})
        self.assertNotIn('{', aus)
        self.assertIn('Sehr geehrter Herr A', aus)
        self.assertIn('für 3.5 Zi A, A-Weg 7, 8000 Zürich verletzen', aus)
        self.assertIn('Bis spätestens 15. Dezember 2026.', aus)
        self.assertIn('Innert 10 Tagen.', aus)
        self.assertIn('unter 044 111 22 33.', aus)
        # Die alten Kurznamen behalten ihre Bedeutung (flacher Wert vor dem neuen Kontext)
        with organisation_kontext(self.a.organisation):
            self.assertEqual(_ersetze('{anrede} {name} ({objekt})', {'name': 'Mieter A', 'anrede': 'Herr', 'objekt': 'alt', '_ph': ph}),
                             'Herr Mieter A (alt)')

    def test_ohne_frist_bleibt_der_fristplatzhalter_stehen(self):
        """Kein erfundenes Datum: Ohne Angabe bleibt `{frist}` sichtbar stehen statt leer oder geraten."""
        from core.services.serienbrief import _ersetze, empfaenger_kontext
        with organisation_kontext(self.a.organisation):
            _v, ph = empfaenger_kontext(self.a.mieter, self.a.organisation)
            self.assertEqual(_ersetze('bis {frist}', {'_ph': ph}), 'bis {frist}')

    def test_email_geht_mit_ersetzten_platzhaltern_hinaus(self):
        with mock.patch('core.utils.email_service.send_ticket_email', return_value=True) as senden:
            self.c.post('/neu/kommunikation/senden/', {
                'betreff': 'Abmahnung {objekt.bezeichnung}', 'text': TEXT, 'empfaenger_id': [self.a.mieter.pk],
                'frist_datum': '2026-12-15', 'frist_tage': '10'})
        self.assertEqual(senden.call_count, 1)
        _an, betreff, text = senden.call_args[0][:3]
        self.assertEqual(betreff, 'Abmahnung 3.5 Zi A')
        self.assertNotIn('{', text)
        self.assertIn('Sehr geehrter Herr A', text)
        self.assertIn('15. Dezember 2026', text)

    def test_pdf_versand_laeuft_mit_den_neuen_platzhaltern(self):
        r = self.c.post('/neu/kommunikation/serienbrief/', {
            'betreff': 'Abmahnung', 'text': TEXT, 'empfaenger_id': [self.a.mieter.pk], 'frist_datum': '2026-12-15', 'frist_tage': '10'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
