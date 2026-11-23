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


class KommunikationBriefTests(TestCase):
    """«Als Brief drucken» liefert den formatierten Brief; «Einschreiben» setzt den Vermerk und legt die Pendenz an.

    Anlass (23.11.2026): Der Druck aus dem Browser kam ohne jede Formatierung heraus (Logo in voller Grösse, kein Adressfeld),
    und der Assistent liess Einschreiben nicht wählen."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def setUp(self):
        self.c = Client(raise_request_exception=False)
        self.c.force_login(self.a.benutzer)

    def _post(self, **mehr):
        return self.c.post('/neu/kommunikation/serienbrief/', {
            'betreff': 'Abmahnung', 'text': TEXT, 'empfaenger_id': [self.a.mieter.pk],
            'frist_datum': '2026-12-15', 'frist_tage': '10', **mehr})

    def _text(self, antwort):
        import io

        from pypdf import PdfReader
        return ' '.join((seite.extract_text() or '') for seite in PdfReader(io.BytesIO(antwort.content)).pages)

    def test_drucken_liefert_den_formatierten_brief_und_traegt_die_frist_ein(self):
        """«Als Brief drucken» ist derselbe Brief wie das Serienbrief-PDF, nur im Browser geöffnet: abgelegt, mit Pendenz."""
        from core.models import Pendenz
        from rentals.models import Dokument
        with organisation_kontext(self.a.organisation):
            vorher = Dokument.objects.count()
        r = self._post(anzeigen='1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r['Content-Disposition'].startswith('inline'))
        text = self._text(r)
        self.assertIn('Abmahnung', text)
        self.assertIn('Sehr geehrter Herr A', text)
        with organisation_kontext(self.a.organisation):
            self.assertEqual(Dokument.objects.count(), vorher + 1)
            self.assertEqual(Pendenz.objects.filter(quelle__startswith='brief:').count(), 1)

    def test_frist_im_brief_steht_im_fristen_center(self):
        """Wunsch vom 23.11.2026: Eine Frist, die der Brief setzt, erscheint ohne weiteres Zutun im Fristen-Center."""
        from core.models import Pendenz
        self.assertNotContains(self.c.get('/neu/fristen/'), 'Abmahnung')
        self._post()
        with organisation_kontext(self.a.organisation):
            p = Pendenz.objects.get(quelle__startswith='brief:')
            self.assertEqual(p.kategorie, 'frist')
            self.assertEqual(p.faellig_am.isoformat(), '2026-12-15')
            self.assertFalse(p.einschreiben)
        r = self.c.get('/neu/fristen/')
        self.assertContains(r, 'Frist Mieter A: Abmahnung')
        self.assertContains(self.c.get('/neu/fristen/?nur=frist'), 'Frist Mieter A: Abmahnung')

    def test_einschreiben_setzt_vermerk_und_legt_die_pendenz_an(self):
        from core.models import Pendenz
        r = self._post(einschreiben='1')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Einschreiben', self._text(r))
        with organisation_kontext(self.a.organisation):
            p = Pendenz.objects.get(einschreiben=True)
            self.assertEqual(p.faellig_am.isoformat(), '2026-12-15')      # die Frist aus dem Brief
            self.assertIsNotNone(p.versand_am)
            self.assertTrue(p.quelle.startswith('brief:'))
            self.assertEqual(p.vertrag_id, self.a.vertrag.pk)

    def test_ohne_einschreiben_kein_vermerk(self):
        r = self._post()
        self.assertNotIn('Einschreiben', self._text(r))

    def test_frist_im_formular_ohne_frist_im_text_legt_keine_pendenz_an(self):
        from core.models import Pendenz
        r = self.c.post('/neu/kommunikation/serienbrief/', {
            'betreff': 'Information', 'text': 'Guten Tag {name}', 'empfaenger_id': [self.a.mieter.pk],
            'frist_datum': '2026-12-15', 'frist_tage': '10'})
        self.assertEqual(r.status_code, 200)
        with organisation_kontext(self.a.organisation):
            self.assertEqual(Pendenz.objects.filter(quelle__startswith='brief:').count(), 0)

    def test_seite_bietet_einschreiben_an(self):
        r = self.c.get('/neu/kommunikation/')
        self.assertContains(r, 'id="mk-einschreiben"')
        self.assertContains(r, 'name="anzeigen"')

    def test_grussformel_steht_nur_einmal_im_brief(self):
        """Die Vorlage endet mit «Freundliche Grüsse / {verwaltung.name}»; der Brief setzt Gruss und Absender selbst."""
        self.assertEqual(self._text(self._post()).count('Freundliche Grüsse'), 1)

    def test_langer_brief_laeuft_auf_die_naechste_seite(self):
        import io

        from pypdf import PdfReader
        lang = '\n\n'.join(f'Absatz {i}: ' + 'Text ' * 40 for i in range(1, 31)) + '\n\nSchlusssatz ganz am Ende.'
        r = self.c.post('/neu/kommunikation/serienbrief/', {'betreff': 'Lang', 'text': lang, 'empfaenger_id': [self.a.mieter.pk],
                                                             'anzeigen': '1'})
        seiten = PdfReader(io.BytesIO(r.content)).pages
        self.assertGreater(len(seiten), 1)
        self.assertIn('Schlusssatz ganz am Ende.', ' '.join((s.extract_text() or '') for s in seiten))

    def test_brief_liegt_in_der_mieterakte_und_am_vertrag(self):
        """Wie bei der Mahnung: Der Brief hängt am Mieter und am Vertrag und ist in beiden Akten zu sehen."""
        from rentals.models import Dokument
        for art in ({}, {'anzeigen': '1'}):                     # Serienbrief-PDF und «Als Brief drucken»
            self._post(**art)
        with organisation_kontext(self.a.organisation):
            doks = list(Dokument.objects.filter(titel__startswith='Brief: Abmahnung'))
            self.assertEqual(len(doks), 2)
            for d in doks:
                self.assertEqual(d.mieter_id, self.a.mieter.pk)
                self.assertEqual(d.vertrag_id, self.a.vertrag.pk)
                self.assertEqual(d.kategorie, 'korrespondenz')
                self.assertTrue(d.datei)
        for akte in (f'/neu/personen/{self.a.mieter.pk}/', f'/neu/vertraege/{self.a.vertrag.pk}/'):
            self.assertContains(self.c.get(akte), 'Brief: Abmahnung', msg_prefix=akte)

    def test_email_wird_abgelegt_und_traegt_die_frist_ein(self):
        """Wie beim Brief: Die versandte E-Mail liegt als PDF in der Mieterakte, die Frist steht im Fristen-Center."""
        from core.models import Pendenz
        from rentals.models import Dokument
        with mock.patch('core.utils.email_service.send_ticket_email', return_value=True):
            self.c.post('/neu/kommunikation/senden/', {
                'betreff': 'Abmahnung', 'text': TEXT, 'empfaenger_id': [self.a.mieter.pk],
                'frist_datum': '2026-12-15', 'frist_tage': '10'})
        with organisation_kontext(self.a.organisation):
            d = Dokument.objects.get(titel='E-Mail: Abmahnung')
            self.assertEqual((d.mieter_id, d.vertrag_id, d.kategorie), (self.a.mieter.pk, self.a.vertrag.pk, 'korrespondenz'))
            p = Pendenz.objects.get(quelle=f'brief:{d.pk}')
            self.assertEqual(p.faellig_am.isoformat(), '2026-12-15')
            self.assertFalse(p.einschreiben)
        self.assertContains(self.c.get('/neu/fristen/'), 'Frist Mieter A: Abmahnung')
        self.assertContains(self.c.get(f'/neu/personen/{self.a.mieter.pk}/'), 'E-Mail: Abmahnung')

    def test_email_ohne_frist_wird_abgelegt_aber_ohne_pendenz(self):
        from core.models import Pendenz
        from rentals.models import Dokument
        with mock.patch('core.utils.email_service.send_ticket_email', return_value=True):
            self.c.post('/neu/kommunikation/senden/', {'betreff': 'Info', 'text': 'Guten Tag {name}',
                                                       'empfaenger_id': [self.a.mieter.pk]})
        with organisation_kontext(self.a.organisation):
            self.assertEqual(Dokument.objects.filter(titel='E-Mail: Info').count(), 1)
            self.assertEqual(Pendenz.objects.filter(quelle__startswith='brief:').count(), 0)

    def test_nicht_versandte_email_wird_nicht_abgelegt(self):
        from rentals.models import Dokument
        with mock.patch('core.utils.email_service.send_ticket_email', return_value=False):
            self.c.post('/neu/kommunikation/senden/', {'betreff': 'Info', 'text': 'Guten Tag', 'empfaenger_id': [self.a.mieter.pk]})
        with organisation_kontext(self.a.organisation):
            self.assertEqual(Dokument.objects.filter(titel__startswith='E-Mail:').count(), 0)
