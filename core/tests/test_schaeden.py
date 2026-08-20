"""Testmodul schaeden — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 5 Klassen, unveraendert uebernommen."""
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import _team_user, _basis_objekte, Eigentuemer, Organisation, Liegenschaft, User, _test_organisation



class ReparaturFreigabeTests(TestCase):
    def test_freigabe_flow(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        lg, e, m, v = _basis_objekte()
        md = Eigentuemer.objects.create(firma_oder_name='Eig AG')
        lg.eigentuemer = md; lg.save()
        u = User.objects.create_user(username='eig2', password='x'); md.benutzer = u; md.save()
        from crm.models import Handwerker
        hw = Handwerker.objects.create(firma='Sanitär AG')
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Heizung', beschreibung='x')
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, freigabe_status='ausstehend', kosten_geschaetzt=Decimal('2000'))
        c = Client(); c.force_login(u)
        self.assertContains(c.get('/portal/'), 'Reparaturen zur Freigabe')
        r = c.post(f'/portal/freigabe/{a.id}/', {'aktion': 'freigeben', 'kommentar': 'ok'})
        self.assertEqual(r.status_code, 302)
        a.refresh_from_db()
        self.assertEqual(a.freigabe_status, 'freigegeben')
        self.assertEqual(a.freigabe_kommentar, 'ok')

    def test_schwelle_automatisch(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        lg, e, m, v = _basis_objekte()
        from crm.models import Handwerker
        hw = Handwerker.objects.create(firma='Elektro AG')
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='X', beschreibung='y')
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, freigabe_status='nicht_noetig')
        u = _team_user()
        c = Client(); c.force_login(u)
        c.post(f'/neu/auftrag/{a.id}/kosten/', {'kosten_geschaetzt': '2500'})
        a.refresh_from_db()
        self.assertEqual(a.freigabe_status, 'ausstehend')


class SchadenModalTests(TestCase):
    def test_schadenliste_oeffnet_detail_im_modal(self):
        """Die Schadensliste öffnet den Schaden inkl. Workflow im Popup, kein Seitenwechsel."""
        from tickets.models import SchadenMeldung
        lg, e, m, v = _basis_objekte()
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Wasserschaden', beschreibung='x')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/schaeden/').content.decode()
        self.assertIn(f"fwModalOpenUrl('/neu/schaeden/{t.id}/'", body)
        self.assertIn('id="fwModal"', body)
        self.assertNotIn(f"window.location='/neu/schaeden/{t.id}/'", body)

    def test_schaden_detail_im_iframe_chromelos(self):
        """Das Schaden-Detail läuft im Popup chrome-frei (iframe-Kontext-Erkennung)."""
        from tickets.models import SchadenMeldung
        lg, e, m, v = _basis_objekte()
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Wasserschaden', beschreibung='x')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get(f'/neu/schaeden/{t.id}/').content.decode()
        self.assertIn('window.self !== window.top', body)   # Chrome wird im iframe versteckt


class SchadenKostenTests(TestCase):
    """Reparaturkosten-Übersicht je Liegenschaft."""

    def _setup(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        lg, e, m, v = _basis_objekte()
        hw = Handwerker.objects.create(firma='Sanitär AG')
        t1 = SchadenMeldung.objects.create(liegenschaft=lg, titel='Rohrbruch', status='neu')
        t2 = SchadenMeldung.objects.create(liegenschaft=lg, titel='Fenster', status='erledigt')
        # Auftrag mit effektiven Kosten + einer mit nur Schätzung (offen)
        HandwerkerAuftrag.objects.create(ticket=t1, handwerker=hw,
                                         kosten_geschaetzt=Decimal('500'), kosten_effektiv=None)
        HandwerkerAuftrag.objects.create(ticket=t2, handwerker=hw,
                                         kosten_geschaetzt=Decimal('300'), kosten_effektiv=Decimal('280'))
        return lg

    def test_kostenuebersicht_aggregiert(self):
        lg = self._setup()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/schaeden/kosten/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['total']['effektiv'], Decimal('280.00'))
        self.assertEqual(r.context['total']['offen'], Decimal('500.00'))
        self.assertEqual(r.context['total']['auftraege'], 2)
        self.assertEqual(r.context['total']['schaeden'], 2)
        row = r.context['rows'][0]
        self.assertEqual(row['schaeden_offen'], 1)


class SchadenFotoTests(TestCase):
    """Mehrfach-Foto-Upload für Schadenmeldungen."""

    def _bild(self, name='schaden.png'):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        buf = io.BytesIO()
        Image.new('RGB', (10, 10), (200, 50, 50)).save(buf, 'PNG')
        return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')

    def _schaden(self, lg):
        from tickets.models import SchadenMeldung
        return SchadenMeldung.objects.create(liegenschaft=lg, titel='Wasserschaden', beschreibung='x', status='neu')

    def test_upload_mehrere_fotos(self):
        from tickets.models import SchadenFoto
        lg, e, m, v = _basis_objekte()
        t = self._schaden(lg)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post(f'/neu/schaeden/{t.id}/foto/', {'fotos': [self._bild('a.png'), self._bild('b.png')]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SchadenFoto.objects.filter(schaden=t).count(), 2)

    def test_erfassen_mit_foto(self):
        from tickets.models import SchadenMeldung, SchadenFoto
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post('/neu/schaeden/neu/', {
            'titel': 'Riss in Wand', 'liegenschaft_id': lg.id, 'beschreibung': 'test',
            'prioritaet': 'mittel', 'fotos': [self._bild('riss.png')]})
        self.assertEqual(r.status_code, 302)
        t = SchadenMeldung.objects.get(titel='Riss in Wand')
        self.assertEqual(SchadenFoto.objects.filter(schaden=t).count(), 1)

    def test_foto_loeschen(self):
        from tickets.models import SchadenFoto
        lg, e, m, v = _basis_objekte()
        t = self._schaden(lg)
        f = SchadenFoto.objects.create(schaden=t, bild=self._bild())
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/schaeden/foto/{f.id}/loeschen/')
        self.assertFalse(SchadenFoto.objects.filter(id=f.id).exists())

    def test_detail_zeigt_fotos_tab(self):
        from tickets.models import SchadenFoto
        lg, e, m, v = _basis_objekte()
        t = self._schaden(lg)
        SchadenFoto.objects.create(schaden=t, bild=self._bild())
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/schaeden/{t.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['fotos']), 1)
        # Etappe 4b.3: Das Panel heisst nicht mehr `sc-fotos`, sondern
        # `sc-dokumente` — der Reitersatz ist seither fuer alle Aktentypen
        # gleich. Der Inhalt ist derselbe, nur der Name hat gewechselt.
        # Geprueft wird deshalb das Panel UND das Bild darin; nur den
        # Panelnamen abzufragen bestuende auch bei leerem Reiter.
        self.assertContains(r, 'sc-dokumente')
        self.assertNotContains(r, 'sc-fotos')
        self.assertContains(r, t.fotos.first().bild.url)


class AuftragPdfTests(TestCase):
    """Reparaturauftrag-PDF für einen Handwerker-Auftrag."""

    def test_auftrag_pdf(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker, Organisation
        _test_organisation(firma='Verwaltung AG', strasse='Weg 1', plz='8000', ort='Zürich',
                                  email='info@vw.ch', telefon='044 000 00 00')
        lg, e, m, v = _basis_objekte()
        hw = Handwerker.objects.create(firma='Sanitär AG', kontaktperson='H. Meier', email='hw@example.ch')
        t = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=e, titel='Rohrbruch Küche',
                                          beschreibung='Wasser tritt aus.', kategorie='Sanitär',
                                          raum='Küche', melder_vorname='Anna', melder_nachname='Muster',
                                          tel_melder='079', status='neu')
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, kosten_geschaetzt=Decimal('450'),
                                             bemerkung='Bitte rasch erledigen.')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/auftrag/{a.id}/pdf/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertGreater(len(r.content), 1200)

    def test_pdf_button_im_detail(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        lg, e, m, v = _basis_objekte()
        hw = Handwerker.objects.create(firma='Elektro AG')
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Steckdose', beschreibung='x', status='neu')
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw)
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/schaeden/{t.id}/')
        self.assertContains(r, f'/neu/auftrag/{a.id}/pdf/')
