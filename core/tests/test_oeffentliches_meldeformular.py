"""Öffentliche Meldeformulare (SICH-08, ROUTE-04, SICH-14; Audit 28.10.2026).

`/report/<id>/` (QR-Aushang im Treppenhaus) war die ungeschützteste Schreibstelle:
30 POST in Folge → 30 Tickets, jedes mit Bestätigungsmail an eine frei gewählte
Adresse; ein leeres Formular legte «None ()» an; `einheit_id` einer FREMDEN
Verwaltung wurde übernommen; eine nicht-numerische `einheit_id` ergab 500; ein
Foto wurde ungeprüft gespeichert (eine `.html` unter `schaden_fotos/`); die
Mail setzte Titel und Name als rohes HTML ein.

Die Seite nimmt jetzt Meldungen an, die vollständig sind, in der Länge der
Spalten bleiben und nur auf EINHEITEN DER EIGENEN LIEGENSCHAFT zeigen — und sie
zählt wie die Schwesterseite `/schaden/melden/` (10 je IP und Stunde).

GEGENPROBEN (28.10.2026, je einzeln eingebaut, rot gesehen, zurückgebaut):
  * `rate_limit` in `_qr_formular` entfernt              → `test_die_elfte_meldung…` rot
  * `eigenes_objekt(Einheit, …, liegenschaft=…)` durch die rohe ID ersetzt
                                                          → `test_fremde_einheit…` rot
  * Pflichtfeld-Prüfung (`text(…, pflicht=True)`) entfernt → `test_leeres_formular…` rot
  * `validiere_bild` entfernt                             → `test_html_als_foto…` rot
  * `escape()` in `send_ticket_receipt` entfernt          → `test_die_bestaetigungsmail…` rot
  * Längenprüfung in `public_schaden_melden_view` entfernt → `test_schaden_melden_lange…` rot
"""
import io
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from tickets.models import SchadenMeldung

from ._isolation import MandantenFixture


class MeldeformularBasis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        cache.clear()                       # die Drossel zählt im Cache
        self.anonym = Client()
        self.pfad = f'/report/{self.a.liegenschaft.pk}/'
        patcher = patch('core.utils.email_service.send_via_hoststar', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def gueltig(self, **extra):
        daten = {'titel': 'Schaden: Küche - Kühlschrank', 'beschreibung': 'Kühlt nicht mehr.',
                 'anrede': 'Frau', 'vorname': 'Vera', 'nachname': 'Muster',
                 'email': 'vera@example.ch', 'telefon': '0791234567'}
        daten.update(extra)
        return daten

    def tickets(self, **filter_):
        return SchadenMeldung.alle_organisationen.filter(**filter_)

    def png(self, name='foto.png'):
        from PIL import Image
        puffer = io.BytesIO()
        Image.new('RGB', (4, 4), (200, 30, 30)).save(puffer, 'PNG')
        return SimpleUploadedFile(name, puffer.getvalue(), content_type='image/png')


class AushangFormularTests(MeldeformularBasis):

    def test_eine_vollstaendige_meldung_legt_ein_ticket_an(self):
        antwort = self.anonym.post(self.pfad, self.gueltig(einheit_id=self.a.einheit.pk))
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'Vielen Dank')
        t = self.tickets(titel__startswith='Schaden: Küche').get()
        self.assertEqual(t.organisation_id, self.a.organisation.pk)
        self.assertEqual(t.liegenschaft_id, self.a.liegenschaft.pk)
        self.assertEqual(t.betroffene_einheit_id, self.a.einheit.pk)

    def test_leeres_formular_legt_nichts_an(self):
        """Vorher: Ticket «None ()» mit Beschreibung «None\\n\\n--- KONTAKT ---»."""
        vorher = self.tickets().count()
        antwort = self.anonym.post(self.pfad, {})
        self.assertEqual(antwort.status_code, 400)
        self.assertEqual(self.tickets().count(), vorher)
        self.assertContains(antwort, 'Ihre Meldung wurde noch nicht gesendet', status_code=400)

    def test_jedes_pflichtfeld_wird_verlangt(self):
        for feld in ('titel', 'beschreibung', 'vorname', 'nachname', 'email', 'telefon'):
            with self.subTest(feld=feld):
                daten = self.gueltig()
                daten.pop(feld)
                vorher = self.tickets().count()
                antwort = self.anonym.post(self.pfad, daten)
                self.assertEqual(antwort.status_code, 400)
                self.assertEqual(self.tickets().count(), vorher)

    def test_ungueltige_email_wird_abgelehnt(self):
        vorher = self.tickets().count()
        antwort = self.anonym.post(self.pfad, self.gueltig(email='kein-mail'))
        self.assertEqual(antwort.status_code, 400)
        self.assertEqual(self.tickets().count(), vorher)

    def test_die_eingaben_kommen_nach_einem_fehler_zurueck(self):
        antwort = self.anonym.post(self.pfad, self.gueltig(beschreibung='', vorname='Vera'))
        self.assertContains(antwort, 'value="Vera"', status_code=400)
        self.assertContains(antwort, 'vera@example.ch', status_code=400)

    # -- Drossel -----------------------------------------------------------

    def test_die_elfte_meldung_je_ip_und_stunde_wird_gedrosselt(self):
        for i in range(10):
            antwort = self.anonym.post(self.pfad, self.gueltig(titel=f'Schaden {i}'))
            self.assertEqual(antwort.status_code, 200, f'Meldung {i + 1} sollte durchgehen')
        antwort = self.anonym.post(self.pfad, self.gueltig(titel='Schaden 11'))
        self.assertEqual(antwort.status_code, 429)
        self.assertEqual(self.tickets(titel__startswith='Schaden 11').count(), 0)

    def test_ungueltige_posts_zaehlen_auch(self):
        """Wer 10× Müll schickt, schickt keinen elften — sonst wäre die Drossel umgehbar."""
        for _ in range(10):
            self.anonym.post(self.pfad, {})
        self.assertEqual(self.anonym.post(self.pfad, self.gueltig()).status_code, 429)

    def test_die_drossel_gilt_je_ip(self):
        for _ in range(10):
            self.anonym.post(self.pfad, self.gueltig(), REMOTE_ADDR='203.0.113.5')
        self.assertEqual(self.anonym.post(self.pfad, self.gueltig(), REMOTE_ADDR='203.0.113.5').status_code, 429)
        self.assertEqual(self.anonym.post(self.pfad, self.gueltig(), REMOTE_ADDR='203.0.113.6').status_code, 200)

    def test_get_wird_nicht_gedrosselt(self):
        for _ in range(15):
            self.assertEqual(self.anonym.get(self.pfad).status_code, 200)

    # -- Einheit -----------------------------------------------------------

    def test_fremde_einheit_wird_abgelehnt(self):
        """SICH-08 (b): Das Ticket von A verwies auf eine Einheit von B."""
        vorher = self.tickets().count()
        antwort = self.anonym.post(self.pfad, self.gueltig(einheit_id=self.b.einheit.pk))
        self.assertEqual(antwort.status_code, 400)
        self.assertEqual(self.tickets().count(), vorher)
        self.assertFalse(self.tickets(betroffene_einheit=self.b.einheit, liegenschaft=self.a.liegenschaft).exists())

    def test_einheit_einer_anderen_liegenschaft_derselben_verwaltung_wird_abgelehnt(self):
        from core.tenancy import organisation_kontext
        from portfolio.models import Einheit, Liegenschaft
        with organisation_kontext(self.a.organisation):
            zweite = Liegenschaft.objects.create(strasse='Zweitweg 2', plz='8000', ort='Zürich',
                                                 organisation=self.a.organisation, versicherungswert=1)
            fremd = Einheit.objects.create(liegenschaft=zweite, bezeichnung='Anderes Haus', typ='whg')
        antwort = self.anonym.post(self.pfad, self.gueltig(einheit_id=fremd.pk))
        self.assertEqual(antwort.status_code, 400)

    def test_nicht_numerische_einheit_ist_ein_formularfehler_kein_500(self):
        for wert in ('abc', '1; DROP', '²', '-1', '1.5', '99999999999999999999'):
            with self.subTest(einheit_id=wert):
                antwort = self.anonym.post(self.pfad, self.gueltig(einheit_id=wert))
                self.assertEqual(antwort.status_code, 400)

    def test_ohne_einheit_geht_es(self):
        """Die Einheit ist freiwillig (Gegenprobe zu den Ablehnungen oben)."""
        self.assertEqual(self.anonym.post(self.pfad, self.gueltig(einheit_id='')).status_code, 200)

    def test_die_einheit_des_eigenen_hauses_wird_uebernommen_die_anzeige_zeigt_nur_sie(self):
        html = self.anonym.get(self.pfad).content.decode()
        self.assertIn(f'value="{self.a.einheit.pk}"', html)
        self.assertNotIn(f'value="{self.b.einheit.pk}"', html)

    # -- Foto --------------------------------------------------------------

    def test_html_als_foto_wird_abgelehnt(self):
        """SICH-08 (d): Eine `.html` landete unter `schaden_fotos/`."""
        boese = SimpleUploadedFile('boese.html', b'<script>alert(1)</script>', content_type='text/html')
        vorher = self.tickets().count()
        antwort = self.anonym.post(self.pfad, {**self.gueltig(), 'foto': boese})
        self.assertEqual(antwort.status_code, 400)
        self.assertEqual(self.tickets().count(), vorher)

    def test_ein_bild_mit_falscher_endung_und_ein_text_als_png_wird_abgelehnt(self):
        falsch = SimpleUploadedFile('foto.png', b'das ist kein bild', content_type='image/png')
        antwort = self.anonym.post(self.pfad, {**self.gueltig(), 'foto': falsch})
        self.assertEqual(antwort.status_code, 400)

    def test_ein_echtes_bild_wird_gespeichert(self):
        with patch('django.core.files.storage.FileSystemStorage.save', return_value='organisation/1/schaden_fotos/foto.png'):
            antwort = self.anonym.post(self.pfad, {**self.gueltig(titel='Mit Foto'), 'foto': self.png()})
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(self.tickets(titel__startswith='Mit Foto').get().foto)

    # -- Längen ------------------------------------------------------------

    def test_zu_lange_texte_sind_ein_formularfehler(self):
        """SICH-14: auf PostgreSQL ergab `titel` mit 200+ Zeichen einen 500."""
        grenzen = {'titel': 100, 'nachname': 70, 'vorname': 100, 'telefon': 50, 'beschreibung': 5000,
                   'hersteller': 100, 'seriennummer': 100, 'anrede': 20}
        for feld, grenze in grenzen.items():
            with self.subTest(feld=feld):
                vorher = self.tickets().count()
                antwort = self.anonym.post(self.pfad, self.gueltig(**{feld: 'x' * (grenze + 1)}))
                self.assertEqual(antwort.status_code, 400, f'{feld} mit {grenze + 1} Zeichen')
                self.assertEqual(self.tickets().count(), vorher)

    def test_texte_genau_an_der_grenze_gehen(self):
        antwort = self.anonym.post(self.pfad, self.gueltig(titel='t' * 100, nachname='n' * 70,
                                                           beschreibung='b' * 5000, telefon='1' * 50))
        self.assertEqual(antwort.status_code, 200)
        # «titel (nachname)» passt in die 200 Zeichen der Spalte
        self.assertEqual(len(self.tickets().latest('pk').titel), 100 + 3 + 70)

    def test_sehr_lange_email_ist_ein_formularfehler(self):
        antwort = self.anonym.post(self.pfad, self.gueltig(email='a' * 250 + '@example.ch'))
        self.assertEqual(antwort.status_code, 400)

    # -- Mail --------------------------------------------------------------

    def test_die_bestaetigungsmail_setzt_den_titel_nicht_als_html_ein(self):
        """SICH-08 (e): `<a href=…>` im Titel kam als anklickbarer Link in der Mail an."""
        from core.utils import email_service
        t = SchadenMeldung(titel='<a href="http://evil.example">Klick hier</a>', email_melder='opfer@example.org',
                           liegenschaft=self.a.liegenschaft, beschreibung='x')
        t.save()

        class Sofort:
            def __init__(self, target, args=(), kwargs=None):
                self.target, self.args, self.kwargs = target, args, kwargs or {}

            def start(self):
                self.target(*self.args, **self.kwargs)

        with patch.object(email_service.threading, 'Thread', Sofort), \
                patch.object(email_service, 'send_via_hoststar') as senden:
            email_service.send_ticket_receipt(t)
        html = senden.call_args.args[2]
        self.assertNotIn('<a href="http://evil.example">', html)
        self.assertIn('&lt;a href=', html)

    def test_die_internen_mails_setzen_texte_nicht_als_html_ein(self):
        from core.utils import email_service
        t = SchadenMeldung(titel='<b>fett</b>', beschreibung='<script>x</script>', email_melder='a@b.ch',
                           tel_melder='<i>1</i>', liegenschaft=self.a.liegenschaft)
        t.save()
        with patch.object(email_service, 'send_via_hoststar', return_value=True) as senden:
            email_service.send_neue_meldung_intern(t, ['team@example.ch'])
        html = senden.call_args.args[2]
        self.assertNotIn('<script>', html)
        self.assertNotIn('<b>fett</b>', html)


class SchadenMeldenFormularTests(MeldeformularBasis):
    """Die Schwesterseite `/schaden/melden/`: gleiche Länge-Regeln, keine 500 bei IDs."""

    def setUp(self):
        super().setUp()
        self.pfad = '/schaden/melden/'

    def daten(self, **extra):
        d = {'kategorie': 'Schaden', 'raum': 'Küche', 'objekt': 'Herd', 'beschreibung': 'Defekt',
             'vorname': 'Vera', 'nachname': 'Muster', 'email': 'vera@example.ch', 'telefon': '079',
             'liegenschaft_id': self.a.liegenschaft.pk}
        d.update(extra)
        return d

    def test_eine_normale_meldung_geht(self):
        self.assertEqual(self.anonym.post(self.pfad, self.daten()).status_code, 200)
        self.assertTrue(self.tickets(liegenschaft=self.a.liegenschaft).exists())

    def test_schaden_melden_lange_texte_sind_ein_formularfehler(self):
        for feld, laenge in (('raum', 81), ('objekt', 81), ('vorname', 101), ('nachname', 101),
                             ('telefon', 51), ('kategorie', 101), ('beschreibung', 5001)):
            with self.subTest(feld=feld):
                vorher = self.tickets().count()
                antwort = self.anonym.post(self.pfad, self.daten(**{feld: 'x' * laenge}))
                self.assertEqual(antwort.status_code, 400)
                self.assertEqual(self.tickets().count(), vorher)

    def test_ungueltige_liegenschaft_ist_kein_500(self):
        for wert in ('abc', '²', '99999999999999999999', '-3'):
            with self.subTest(liegenschaft_id=wert):
                antwort = self.anonym.post(self.pfad, self.daten(liegenschaft_id=wert))
                self.assertLess(antwort.status_code, 500)

    def test_die_zehn_je_ip_bleiben(self):
        for _ in range(10):
            self.anonym.post(self.pfad, self.daten())
        self.assertEqual(self.anonym.post(self.pfad, self.daten()).status_code, 429)


class GemeinsamesFormularTests(MeldeformularBasis):
    """Etappe 3: Das Formular sendet Anliegen, Raum und Gegenstand statt eines fertigen Titels.

    Gegenproben (29.10.2026): `titel_aus_wahl` in `_qr_formular` entfernen → `test_der_titel_entsteht…`
    rot; die Zeile `kategorie=…` in `process_public_ticket_form` entfernen → `test_die_wahl_wird_gespeichert`
    rot; `werte=request.POST` aus `_web_formular` entfernen → `test_die_website_behaelt_die_eingaben` rot.
    """

    def wahl(self, **extra):
        daten = {'kategorie': 'Schadensmeldung', 'raum': 'Küche', 'objekt': 'Kühlschrank',
                 'beschreibung': 'Kühlt nicht mehr.', 'anrede': 'Frau', 'vorname': 'Vera',
                 'nachname': 'Muster', 'email': 'vera@example.ch', 'telefon': '0791234567'}
        daten.update(extra)
        return daten

    def test_der_titel_entsteht_aus_der_wahl_nicht_im_browser(self):
        antwort = self.anonym.post(self.pfad, self.wahl())
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'Vielen Dank')
        t = self.tickets().latest('pk')
        self.assertEqual(t.titel, 'Schaden: Küche - Kühlschrank (Muster)')

    def test_die_wahl_wird_gespeichert(self):
        """Bis Etappe 3 behielt der Aushang Raum und Gegenstand nur im Titel; `/schaden/melden/` in Spalten."""
        self.anonym.post(self.pfad, self.wahl())
        t = self.tickets().latest('pk')
        self.assertEqual((t.kategorie, t.raum, t.objekt), ('Schadensmeldung', 'Küche', 'Kühlschrank'))

    def test_andere_anliegen_tragen_ihren_namen_ohne_raum(self):
        self.anonym.post(self.pfad, self.wahl(kategorie='Allgemeine Anfrage', raum='', objekt=''))
        t = self.tickets().latest('pk')
        self.assertEqual(t.titel, 'Allgemeine Anfrage (Muster)')
        self.assertFalse(t.raum)

    def test_ein_gesendeter_titel_gilt_weiter(self):
        """Ältere Formulare und Skripte senden den Titel selbst."""
        self.anonym.post(self.pfad, self.wahl(titel='Eigener Titel'))
        self.assertEqual(self.tickets().latest('pk').titel, 'Eigener Titel (Muster)')

    def test_ohne_anliegen_und_ohne_titel_fehlt_der_titel(self):
        daten = self.wahl()
        daten.pop('kategorie')
        antwort = self.anonym.post(self.pfad, daten)
        self.assertEqual(antwort.status_code, 400)
        self.assertContains(antwort, 'Bitte füllen Sie das Feld «Anliegen» aus.', status_code=400)

    def test_zu_lange_wahl_ist_ein_formularfehler(self):
        for feld in ('kategorie', 'raum', 'objekt'):
            with self.subTest(feld=feld):
                vorher = self.tickets().count()
                antwort = self.anonym.post(self.pfad, self.wahl(**{feld: 'x' * 101}))
                self.assertEqual(antwort.status_code, 400)
                self.assertEqual(self.tickets().count(), vorher)

    def test_nach_einem_fehler_bleibt_die_wahl_stehen_und_das_formular_springt_zur_pruefung(self):
        antwort = self.anonym.post(self.pfad, self.wahl(beschreibung=''))
        self.assertContains(antwort, 'name="raum" value="Küche" checked', status_code=400)
        self.assertContains(antwort, 'name="objekt" value="Kühlschrank" disabled data-geraet="1" checked',
                            status_code=400)
        self.assertContains(antwort, ' data-fehler', status_code=400)
        self.assertContains(antwort, 'value="Vera"', status_code=400)

    def test_die_website_behaelt_die_eingaben_nach_einem_fehler(self):
        antwort = self.anonym.post('/schaden/melden/', {
            'kategorie': 'Schadensmeldung', 'raum': 'Küche', 'objekt': 'Herd', 'beschreibung': 'Defekt',
            'vorname': 'Vera', 'nachname': 'Muster', 'email': 'unbekannt@example.org', 'telefon': '079',
            'adresse': 'Testweg 1'})
        # Die Adresse lässt sich keiner Liegenschaft zuordnen: Fehler, aber nichts muss neu getippt werden.
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'Wir konnten Ihre Meldung keiner Liegenschaft zuordnen.')
        self.assertContains(antwort, 'value="Vera"')
        self.assertContains(antwort, 'value="unbekannt@example.org"')
        self.assertContains(antwort, 'value="Testweg 1"')
        self.assertContains(antwort, ' data-fehler')

    def test_titel_aus_wahl(self):
        from core.views.ticket_public import titel_aus_wahl
        self.assertEqual(titel_aus_wahl('Schadensmeldung', 'Bad', 'WC'), 'Schaden: Bad - WC')
        self.assertEqual(titel_aus_wahl('Schadensmeldung', 'Bad'), 'Schaden: Bad')
        self.assertEqual(titel_aus_wahl('Schadensmeldung'), 'Schaden')
        self.assertEqual(titel_aus_wahl('Schlüsselbestellung', 'Bad', 'WC'), 'Schlüsselbestellung')
        self.assertEqual(titel_aus_wahl('', 'Bad', 'WC'), '')
