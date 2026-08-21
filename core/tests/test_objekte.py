"""Testmodul objekte — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 15 Klassen, unveraendert uebernommen."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (_test_organisation,
    _team_user, _basis_objekte, _heute, Mieter, Organisation, Liegenschaft,
    Einheit, Wartungsfrist)



class WartungsfristTests(TestCase):
    def test_pendenz_und_rollover(self):
        from core.services.automation import generate_auto_pendenzen, _plus_monate
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        wf = Wartungsfrist.objects.create(liegenschaft=lg, art='versicherung', bezeichnung='Police',
                                          naechste_faelligkeit=date.today() + timedelta(days=10),
                                          intervall_monate=12)
        generate_auto_pendenzen(horizont_tage=90)
        self.assertTrue(Pendenz.objects.filter(quelle__startswith=f'auto:wartung:{wf.id}').exists())
        # Rollover
        wf.naechste_faelligkeit = date.today() - timedelta(days=400); wf.save()
        generate_auto_pendenzen(horizont_tage=90)
        wf.refresh_from_db()
        self.assertGreaterEqual(wf.naechste_faelligkeit, date.today())
        self.assertEqual(_plus_monate(date(2026, 1, 31), 1), date(2026, 2, 28))


class ExposeTests(TestCase):
    """Exposé/Inserat-PDF für ausgeschriebene Objekte."""

    def test_titel_zimmerwohnung(self):
        from core.services.expose import objekt_titel
        lg, e, m, v = _basis_objekte()
        e.typ = 'whg'; e.zimmer = Decimal('3.5'); e.save()
        self.assertEqual(objekt_titel(e), '3.5-Zimmer-Wohnung')
        e.zimmer = Decimal('4.0'); e.save()
        self.assertEqual(objekt_titel(e), '4-Zimmer-Wohnung')

    def test_expose_pdf_view(self):
        from crm.models import Organisation
        _test_organisation(firma='Verwaltung AG', strasse='Weg 1', plz='8000', ort='Zürich',
                                  telefon='044 000 00 00', email='info@vw.ch')
        lg, e, m, v = _basis_objekte()
        e.typ = 'whg'; e.zimmer = Decimal('3.5'); e.zur_ausschreibung = True
        e.ausschreibung_notiz = 'Helle Wohnung mit Balkon und Seesicht.'
        e.save()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vermarktung/{e.id}/expose/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertGreater(len(r.content), 1200)

    def test_expose_button_in_liste(self):
        lg, e, m, v = _basis_objekte()
        e.zur_ausschreibung = True; e.save()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/vermarktung/')
        self.assertContains(r, f'/neu/vermarktung/{e.id}/expose/')


class ObjektFotoTests(TestCase):
    """Objekt-Fotos: Upload, Exposé-Titelbild, Portal-Feed-Bilder, Listen-Thumbnail."""

    def _bild(self, name='obj.png'):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        buf = io.BytesIO()
        Image.new('RGB', (12, 10), (60, 120, 200)).save(buf, 'PNG')
        return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')

    def _objekt(self):
        lg, e, m, v = _basis_objekte()
        e.typ = 'whg'; e.zimmer = Decimal('3.5'); e.zur_ausschreibung = True; e.save()
        return lg, e

    def test_upload_und_loeschen(self):
        from portfolio.models import EinheitFoto
        lg, e = self._objekt()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/objekte/{e.id}/foto/', {'fotos': [self._bild('a.png'), self._bild('b.png')]})
        self.assertEqual(EinheitFoto.objects.filter(einheit=e).count(), 2)
        f = EinheitFoto.objects.filter(einheit=e).first()
        c.post(f'/neu/objekte/foto/{f.id}/loeschen/')
        self.assertEqual(EinheitFoto.objects.filter(einheit=e).count(), 1)

    def test_feed_enthaelt_bilder(self):
        from crm.models import Organisation
        from portfolio.models import EinheitFoto
        _test_organisation(firma='VW AG', strasse='', plz='', ort='', portal_feed_token='t')
        lg, e = self._objekt()
        EinheitFoto.objects.create(einheit=e, bild=self._bild())
        c = Client()
        r = c.get('/neu/vermarktung/feed.json?token=t')
        o = r.json()['objekte'][0]
        self.assertEqual(len(o['bilder']), 1)
        self.assertTrue(o['bilder'][0].startswith('http'))

    def test_vermarktung_zeigt_thumbnail(self):
        from portfolio.models import EinheitFoto
        lg, e = self._objekt()
        EinheitFoto.objects.create(einheit=e, bild=self._bild())
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/vermarktung/')
        row = r.context['rows'][0]
        self.assertIsNotNone(row['titelbild'])
        self.assertEqual(row['fotos_n'], 1)

    def test_expose_mit_titelbild(self):
        from portfolio.models import EinheitFoto
        lg, e = self._objekt()
        EinheitFoto.objects.create(einheit=e, bild=self._bild())
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vermarktung/{e.id}/expose/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))


class PortalFeedTests(TestCase):
    """Token-gesicherter Vermarktungs-Objekt-Feed für Immobilien-Portale."""

    def _objekt(self):
        lg, e, m, v = _basis_objekte()
        e.typ = 'whg'; e.zimmer = Decimal('3.5'); e.zur_ausschreibung = True
        e.ausschreibung_notiz = 'Helle Wohnung'
        e.save()
        return lg, e

    def test_feed_ohne_token_verboten(self):
        from crm.models import Organisation
        _test_organisation(firma='VW AG', strasse='', plz='', ort='', portal_feed_token='geheim123')
        self._objekt()
        c = Client()   # kein Login nötig (öffentlich, aber token-gated)
        self.assertEqual(c.get('/neu/vermarktung/feed.json').status_code, 403)
        self.assertEqual(c.get('/neu/vermarktung/feed.json?token=falsch').status_code, 403)

    def test_feed_json_mit_token(self):
        from crm.models import Organisation
        _test_organisation(firma='VW AG', strasse='', plz='', ort='', portal_feed_token='geheim123')
        lg, e = self._objekt()
        c = Client()
        r = c.get('/neu/vermarktung/feed.json?token=geheim123')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['anzahl'], 1)
        o = data['objekte'][0]
        self.assertEqual(o['typ'], 'apartment')
        self.assertEqual(o['zimmer'], 3.5)
        self.assertEqual(o['miete']['brutto'], 1700.0)
        self.assertIn('/neu/vermarktung/', o['expose_url'])

    def test_feed_csv(self):
        from crm.models import Organisation
        _test_organisation(firma='VW AG', strasse='', plz='', ort='', portal_feed_token='t')
        self._objekt()
        c = Client()
        r = c.get('/neu/vermarktung/feed.json?token=t&format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        self.assertIn(b'referenz;typ', r.content)

    def test_token_erzeugen_und_entfernen(self):
        from crm.models import Organisation
        _test_organisation(firma='VW AG', strasse='', plz='', ort='')
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/integrationen/portal-token/')
        vw = Organisation.objects.first()
        self.assertTrue(vw.portal_feed_token)
        c.post('/neu/integrationen/portal-token/', {'aktion': 'entfernen'})
        vw.refresh_from_db()
        self.assertEqual(vw.portal_feed_token, '')

    def test_integrationen_zeigt_portal_karte(self):
        from crm.models import Organisation
        _test_organisation(firma='VW AG', strasse='', plz='', ort='', portal_feed_token='abc')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/integrationen/')
        self.assertContains(r, 'Immobilien-Portale')
        self.assertContains(r, 'feed.json')


class AusstattungRaumbuchTests(TestCase):
    """Assets/Raumbuch Phase 1: Ausstattungselemente je Objekt (Raum entsteht
    aus den Assets), Katalog-Vorlagen, Zeitwert nach Lebensdauertabelle."""

    def test_lebensdauer_geseedet(self):
        """Die Standardwerte entstehen jetzt JE VERWALTUNG, nicht mehr global.

        Bis Etappe 5 legte die Data-Migration `0019_seed_lebensdauer` sie an —
        ohne Bezug, weil es zur Migrationszeit keine Organisation gibt. Solche
        herrenlosen Zeilen loescht `0037`, und `fw_lebensdauer` legt sie beim
        ersten Aufruf fuer die eigene Verwaltung neu an.
        """
        from portfolio.models import Lebensdauer
        c = Client(); c.force_login(_team_user())
        c.get('/neu/lebensdauer/')
        self.assertTrue(
            Lebensdauer.objects.filter(kategorie='Backofen',
                                       organisation=_test_organisation()).exists())

    def test_effektive_lebensdauer_fallback_tabelle(self):
        from portfolio.models import Ausstattung, Lebensdauer
        _lg, e, _m, _v = _basis_objekte()
        # Mit `organisation`: ohne den Bezug suchte `update_or_create` quer
        # ueber alle Verwaltungen und traefe die Zeile einer fremden.
        Lebensdauer.objects.update_or_create(
            kategorie='Backofen', organisation=_test_organisation(),
            defaults={'jahre': 15})
        a = Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Backofen')
        # kein manueller Wert → aus Tabelle
        self.assertEqual(a.effektive_lebensdauer(), 15)
        a.lebensdauer_jahre = 20
        self.assertEqual(a.effektive_lebensdauer(), 20)

    def test_zeitwert_berechnung(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        # Neuwert 2000, 10 J Lebensdauer, 5 J alt → Zeitwert ~1000
        einbau = date.today() - timedelta(days=int(365.25 * 5))
        a = Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Kochherd',
                                       neuwert=Decimal('2000'), einbau_datum=einbau,
                                       lebensdauer_jahre=10)
        zw = a.zeitwert()
        self.assertIsNotNone(zw)
        self.assertTrue(Decimal('950') <= zw <= Decimal('1050'))

    def test_zeitwert_null_ohne_daten(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        a = Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='WC')
        self.assertIsNone(a.zeitwert())

    def test_zeitwert_nie_negativ(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        # 20 J altes Element bei 10 J Lebensdauer → Rest 0, nicht negativ
        einbau = date.today() - timedelta(days=int(365.25 * 20))
        a = Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Herd',
                                       neuwert=Decimal('1000'), einbau_datum=einbau,
                                       lebensdauer_jahre=10)
        self.assertEqual(a.zeitwert(), Decimal('0.00'))

    def test_element_erfassen_view(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/objekte/{e.id}/ausstattung/', {
            'raum': 'Küche', 'kategorie': 'Geschirrspüler', 'marke': 'V-Zug',
            'neuwert': '1800', 'einbau_datum': '2022-01-01', 'zustand': 'gut', 'menge': '1'})
        self.assertEqual(r.status_code, 302)
        a = Ausstattung.objects.get(einheit=e, kategorie='Geschirrspüler')
        self.assertEqual(a.raum, 'Küche')
        self.assertEqual(a.marke, 'V-Zug')
        self.assertEqual(a.neuwert, Decimal('1800'))

    def test_element_erfassen_pflichtfeld(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/objekte/{e.id}/ausstattung/', {'raum': '', 'kategorie': ''})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Ausstattung.objects.filter(einheit=e).exists())

    def test_katalog_laden(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/objekte/{e.id}/ausstattung/katalog/', {'raumtyp': 'Küche'})
        self.assertEqual(r.status_code, 302)
        kueche = Ausstattung.objects.filter(einheit=e, raum='Küche')
        self.assertGreater(kueche.count(), 5)
        # Lebensdauer aus Katalog übernommen
        herd = kueche.filter(kategorie='Kochherd / Glaskeramik').first()
        self.assertIsNotNone(herd)
        self.assertEqual(herd.lebensdauer_jahre, 15)

    def test_katalog_dedupliziert(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/objekte/{e.id}/ausstattung/katalog/', {'raumtyp': 'Küche'})
        n1 = Ausstattung.objects.filter(einheit=e, raum='Küche').count()
        c.post(f'/neu/objekte/{e.id}/ausstattung/katalog/', {'raumtyp': 'Küche'})
        n2 = Ausstattung.objects.filter(einheit=e, raum='Küche').count()
        self.assertEqual(n1, n2)

    def test_element_loeschen(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        a = Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='Lavabo')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/ausstattung/{a.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Ausstattung.objects.filter(id=a.id).exists())

    def test_objekt_detail_zeigt_raumbuch(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Backofen',
                                   neuwert=Decimal('1200'), einbau_datum=date(2021, 1, 1),
                                   lebensdauer_jahre=15)
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/objekte/{e.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Raumbuch')
        self.assertContains(r, 'Backofen')

    # 4b.20: Die beiden folgenden Prüfungen waren eine — `/neu/assets/`.
    # Diese Seite listete portfolioweit auf und rechnete nichts; sie ist
    # aufgelöst. Ihre zwei Aufgaben hatten schon vorher je ein besseres
    # Zuhause, und dort werden sie jetzt geprüft: die portfolioweite Sicht auf
    # der Ersatzplanung (die dieselben Elemente RECHNET), die Gruppierung nach
    # Raum in der Akte des Objekts, zu dem die Räume gehören.
    #
    # Zusammen decken sie ab, was die alte Prüfung abdeckte. Was sie NICHT
    # mehr fordern, ist das portfolioweite Objekt-Akkordeon — das war die
    # Doppelung.

    def test_die_ausstattung_steht_in_der_ersatzplanung(self):
        """Auch ohne Einbaudatum und Lebensdauer: Ein Element, das nirgends
        auftaucht, ist so gut wie nicht erfasst. Es steht dort als «Keine
        Datenbasis» — das ist der Befund, nicht das Weglassen."""
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='Dusche', zustand='defekt')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/ersatzplanung/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Dusche')
        # Raum und Standort über den Context, nicht über `assertContains`:
        # «Bad» ist Teilstring von «Badge» und stünde auf fast jeder Seite.
        zeile = next(z for z in r.context['rows'] if z['bezeichnung'] == 'Dusche')
        self.assertEqual(zeile['detail'], 'Bad')
        self.assertIn(e.bezeichnung, zeile['standort'])
        self.assertEqual(zeile['status'], 'unbekannt')

    def test_das_raumbuch_gruppiert_in_der_objektakte_nach_raum(self):
        """Die Gruppierung gehört in die Akte des Objekts — dort steht der
        Raum, zu dem das Element gehört.

        GEPRÜFT WIRD DER CONTEXT, NICHT DAS HTML. Eine erste Fassung suchte
        «Bad» in der gerenderten Seite und blieb grün, als die
        Raum-Überschrift entfernt wurde: Das Wort steht auch im
        Erfassungsformular darunter (`<input name="raum" value="…">`). Ein
        Wächter, der seinen Fund woanders macht, prüft nichts. Die
        Gruppenstruktur ist im Context eindeutig.
        """
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='Dusche', zustand='defekt')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/objekte/{e.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Raumbuch')
        gruppen = {g['raum']: g for g in r.context['raeume']}
        self.assertIn('Bad', gruppen)
        self.assertEqual([z['a'].kategorie for z in gruppen['Bad']['elemente']],
                         ['Dusche'])


class AbnahmeLebensdauerTests(TestCase):
    """Assets/Raumbuch Phase 2: Abnahme rechnet Zeitwert/Mieteranteil je Mangel
    nach der Lebensdauertabelle → Schlussabrechnung."""

    def _element(self, e, jahre=10, alter_jahre=5, neuwert='2000'):
        from portfolio.models import Ausstattung
        einbau = date.today() - timedelta(days=int(365.25 * alter_jahre))
        return Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Kochherd',
                                          neuwert=Decimal(neuwert), einbau_datum=einbau,
                                          lebensdauer_jahre=jahre)

    def test_mieteranteil_zeitwert(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        el = self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        mangel = AbnahmeMangel(protokoll=prot, raum='Küche', beschreibung='Glaskeramik gesprungen',
                               verursacher='mieter', ausstattung=el, neuwert=Decimal('2000'))
        anteil = mangel.berechne_mieteranteil()
        # 5 von 10 Jahren verbraucht → ~50% Restwert → ~1000
        self.assertTrue(Decimal('950') <= anteil <= Decimal('1050'))

    def test_mieteranteil_abgeschrieben_null(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        el = self._element(e, jahre=10, alter_jahre=12, neuwert='2000')
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        mangel = AbnahmeMangel(protokoll=prot, beschreibung='defekt',
                               verursacher='mieter', ausstattung=el)
        # vollständig abgeschrieben → Mieter zahlt nichts
        self.assertEqual(mangel.berechne_mieteranteil(), Decimal('0.00'))

    def test_mieteranteil_ohne_element_voller_betrag(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        mangel = AbnahmeMangel(protokoll=prot, beschreibung='Loch in Wand',
                               verursacher='mieter', kostenschaetzung=Decimal('300'))
        self.assertEqual(mangel.berechne_mieteranteil(), Decimal('300.00'))

    def test_mieteranteil_nur_mieter(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        mangel = AbnahmeMangel(protokoll=prot, beschreibung='Abnutzung',
                               verursacher='abnutzung', kostenschaetzung=Decimal('300'))
        self.assertEqual(mangel.berechne_mieteranteil(), Decimal('0.00'))

    def test_abnahme_view_speichert_mieteranteil(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        el = self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/vertraege/{v.id}/abnahme/neu/', {
            'typ': 'auszug', 'datum': date.today().isoformat(),
            'm_raum': ['Küche'], 'm_beschreibung': ['Glaskeramik gesprungen'],
            'm_verursacher': ['mieter'], 'm_kosten': [''],
            'm_ausstattung': [str(el.id)], 'm_neuwert': ['2000']})
        self.assertEqual(r.status_code, 302)
        mangel = AbnahmeMangel.objects.get(beschreibung='Glaskeramik gesprungen')
        self.assertEqual(mangel.ausstattung_id, el.id)
        self.assertIsNotNone(mangel.mieteranteil)
        self.assertTrue(Decimal('950') <= mangel.mieteranteil <= Decimal('1050'))

    def test_kosten_mieter_total_nutzt_mieteranteil(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        el = self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        AbnahmeMangel.objects.create(protokoll=prot, beschreibung='x', verursacher='mieter',
                                     ausstattung=el, mieteranteil=Decimal('1000'),
                                     kostenschaetzung=Decimal('2000'))
        # nutzt mieteranteil (1000), nicht kostenschaetzung (2000)
        self.assertEqual(prot.kosten_mieter_total, Decimal('1000'))

    def test_schlussabrechnung_prefill_mieteranteil(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        el = self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        AbnahmeMangel.objects.create(protokoll=prot, raum='Küche', beschreibung='Glaskeramik',
                                     verursacher='mieter', ausstattung=el,
                                     mieteranteil=Decimal('1000'), kostenschaetzung=Decimal('2000'))
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vertraege/{v.id}/schlussabrechnung/?abnahme={prot.id}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Zeitwert')

    def test_lebensdauer_seite(self):
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/lebensdauer/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Lebensdauertabelle')

    def test_lebensdauer_hinzufuegen_und_bearbeiten(self):
        from portfolio.models import Lebensdauer
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/lebensdauer/', {'aktion': 'neu', 'kategorie': 'Testgerät', 'jahre': '12'})
        self.assertEqual(r.status_code, 302)
        row = Lebensdauer.objects.get(kategorie='Testgerät')
        self.assertEqual(row.jahre, 12)
        c.post('/neu/lebensdauer/', {'aktion': 'speichern', f'jahre_{row.id}': '18',
                                     f'bemerkung_{row.id}': 'angepasst'})
        row.refresh_from_db()
        self.assertEqual(row.jahre, 18)
        self.assertEqual(row.bemerkung, 'angepasst')

    def test_lebensdauer_loeschen(self):
        from portfolio.models import Lebensdauer
        row = Lebensdauer.objects.create(kategorie='Weg', jahre=5,
                                         organisation=_test_organisation())
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/lebensdauer/', {'aktion': 'loeschen', 'id': str(row.id)})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Lebensdauer.objects.filter(id=row.id).exists())


class AusstattungLebenszyklusTests(TestCase):
    """Assets/Raumbuch Phase 3: Element ↔ Schaden (Reparaturhistorie/Lebens-
    zykluskosten) + Garantie-/Ersatzplanung."""

    def _element(self, e, jahre=10, alter_jahre=5, neuwert='2000'):
        from portfolio.models import Ausstattung
        einbau = date.today() - timedelta(days=int(365.25 * alter_jahre))
        return Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Kochherd',
                                          neuwert=Decimal(neuwert), einbau_datum=einbau,
                                          lebensdauer_jahre=jahre)

    def _schaden_mit_kosten(self, lg, e, el, kosten):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        hw = Handwerker.objects.create(firma='Muster GmbH')
        s = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=e,
                                          titel='Defekt', beschreibung='x', ausstattung=el)
        HandwerkerAuftrag.objects.create(ticket=s, handwerker=hw,
                                         kosten_effektiv=Decimal(kosten))
        return s

    def test_rest_jahre(self):
        _lg, e, _m, _v = _basis_objekte()
        el = self._element(e, jahre=10, alter_jahre=4)
        self.assertTrue(5.5 <= el.rest_jahre() <= 6.5)

    def test_ersatz_status(self):
        _lg, e, _m, _v = _basis_objekte()
        self.assertEqual(self._element(e, jahre=10, alter_jahre=4).ersatz_status(), 'ok')
        self.assertEqual(self._element(e, jahre=10, alter_jahre=9).ersatz_status(), 'bald')
        self.assertEqual(self._element(e, jahre=10, alter_jahre=12).ersatz_status(), 'faellig')
        from portfolio.models import Ausstattung
        blank = Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='WC')
        self.assertEqual(blank.ersatz_status(), 'unbekannt')

    def test_reparatur_kosten_und_lebenszyklus(self):
        lg, e, _m, _v = _basis_objekte()
        el = self._element(e, neuwert='2000')
        self._schaden_mit_kosten(lg, e, el, '300')
        self._schaden_mit_kosten(lg, e, el, '150')
        self.assertEqual(el.reparatur_kosten_total(), Decimal('450'))
        self.assertEqual(el.lebenszyklus_kosten(), Decimal('2450'))

    def test_schaden_verknuepfen_view(self):
        from tickets.models import SchadenMeldung
        lg, e, _m, _v = _basis_objekte()
        el = self._element(e)
        s = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=e,
                                          titel='x', beschreibung='y')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/schaeden/{s.id}/ausstattung/', {'ausstattung_id': str(el.id)})
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.ausstattung_id, el.id)
        # aufheben
        c.post(f'/neu/schaeden/{s.id}/ausstattung/', {'ausstattung_id': ''})
        s.refresh_from_db()
        self.assertIsNone(s.ausstattung_id)

    def test_schaden_verknuepfen_nur_eigenes_objekt(self):
        from tickets.models import SchadenMeldung
        from portfolio.models import Einheit
        lg, e, _m, _v = _basis_objekte()
        andere = Einheit.objects.create(liegenschaft=lg, bezeichnung='Andere', typ='wohnung')
        el_fremd = self._element(andere)
        s = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=e,
                                          titel='x', beschreibung='y')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/schaeden/{s.id}/ausstattung/', {'ausstattung_id': str(el_fremd.id)})
        s.refresh_from_db()
        # Element eines anderen Objekts wird nicht verknüpft
        self.assertIsNone(s.ausstattung_id)

    def test_ersatzplanung_view(self):
        lg, e, _m, _v = _basis_objekte()
        self._element(e, jahre=10, alter_jahre=12)  # fällig
        self._element(e, jahre=10, alter_jahre=4)   # ok
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/ersatzplanung/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Ersatzplanung')
        self.assertContains(r, 'Ersatz fällig')

    def test_ersatzplanung_filter(self):
        lg, e, _m, _v = _basis_objekte()
        self._element(e, jahre=10, alter_jahre=12)  # fällig
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/ersatzplanung/?status=faellig')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Kochherd')

    def test_raumbuch_zeigt_reparaturhistorie(self):
        lg, e, _m, _v = _basis_objekte()
        el = self._element(e)
        self._schaden_mit_kosten(lg, e, el, '250')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/objekte/{e.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Reparatur')


class AusstattungEditKatalogTests(TestCase):
    """Ausstattung bearbeiten (Katalog-Elemente mit Daten ergänzen) + Katalog-
    Vollständigkeit/Konsistenz."""

    def test_element_bearbeiten(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        a = Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Backofen',
                                       lebensdauer_jahre=15)
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/ausstattung/{a.id}/bearbeiten/', {
            'raum': 'Küche', 'kategorie': 'Backofen', 'marke': 'V-Zug', 'modell': 'Combair',
            'neuwert': '1600', 'einbau_datum': '2021-06-01', 'zustand': 'gut',
            'garantie_bis': '2026-06-01', 'menge': '1', 'lebensdauer_jahre': '15'})
        self.assertEqual(r.status_code, 302)
        a.refresh_from_db()
        self.assertEqual(a.marke, 'V-Zug')
        self.assertEqual(a.modell, 'Combair')
        self.assertEqual(a.neuwert, Decimal('1600'))
        self.assertEqual(a.einbau_datum, date(2021, 6, 1))

    def test_bearbeiten_pflichtfeld(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        a = Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='WC')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/ausstattung/{a.id}/bearbeiten/', {'raum': '', 'kategorie': ''})
        self.assertEqual(r.status_code, 302)
        a.refresh_from_db()
        self.assertEqual(a.kategorie, 'WC')  # unverändert

    def test_katalog_alle_raeume_vollstaendig(self):
        """Jeder Raumtyp enthält die gemeinsamen Bauteile (Wände, Beleuchtung,
        Lichtschalter, Steckdosen) — Katalog konsistent aufgebaut."""
        from core.services.raumkatalog import RAUM_KATALOG
        for raum, elemente in RAUM_KATALOG.items():
            kats = [k for k, _ in elemente]
            # Mindestgrösse
            self.assertGreaterEqual(len(kats), 7, f"{raum} zu wenige Elemente")
            # keine Duplikate innerhalb eines Raums
            self.assertEqual(len(kats), len(set(kats)), f"{raum} hat Duplikate")
            # Elektro-Basis überall (ausser reine Aussen-/Technikräume)
            if raum not in ('Balkon / Terrasse', 'Heizung / Technik', 'Keller / Estrich'):
                self.assertIn('Beleuchtung', kats, f"{raum} ohne Beleuchtung")
                self.assertIn('Steckdosen', kats, f"{raum} ohne Steckdosen")

    def test_katalog_lebensdauern_positiv(self):
        from core.services.raumkatalog import RAUM_KATALOG
        for raum, elemente in RAUM_KATALOG.items():
            for kat, jahre in elemente:
                self.assertTrue(jahre and jahre > 0, f"{raum}/{kat} ohne Lebensdauer")

    def test_katalog_laden_neue_raeume(self):
        from portfolio.models import Ausstattung
        from core.services.raumkatalog import RAUMTYPEN
        _lg, e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        # Alle Raumtypen laden lassen (auch neue: Heizung/Technik, Reduit/Waschküche)
        for rt in RAUMTYPEN:
            r = c.post(f'/neu/objekte/{e.id}/ausstattung/katalog/', {'raumtyp': rt})
            self.assertEqual(r.status_code, 302)
        self.assertGreater(Ausstattung.objects.filter(einheit=e).count(), 50)


class ErsatzplanungBudgetTests(TestCase):
    """Ersatz- & Budgetplanung: Jahres-Budget-Projektion + PDF-Export."""

    def _element(self, e, jahre, alter_jahre, neuwert):
        from portfolio.models import Ausstattung
        einbau = date.today() - timedelta(days=int(365.25 * alter_jahre))
        return Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Gerät',
                                          neuwert=Decimal(neuwert), einbau_datum=einbau,
                                          lebensdauer_jahre=jahre)

    def test_budget_projektion(self):
        from core.services.ersatzplanung import berechne_ersatzplanung
        _lg, e, _m, _v = _basis_objekte()
        heute = date.today()
        # Ersatz in ~5 Jahren (10 J Lebensdauer, 5 J alt), Neuwert 2000
        self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        # überfällig (12 J alt) → laufendes Jahr, Neuwert 1000
        self._element(e, jahre=10, alter_jahre=12, neuwert='1000')
        d = berechne_ersatzplanung(heute=heute)
        self.assertEqual(d['budget_total'], Decimal('3000'))
        # überfälliges Element landet im laufenden Jahr
        jahre = {b['jahr']: b['summe'] for b in d['jahres_budget']}
        self.assertIn(heute.year, jahre)
        self.assertEqual(jahre[heute.year], Decimal('1000'))
        self.assertIn(heute.year + 5, jahre)

    def test_budget_ohne_neuwert_ignoriert(self):
        from core.services.ersatzplanung import berechne_ersatzplanung
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        # kein Neuwert → kein Budget, aber Zeile existiert
        Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='WC',
                                   einbau_datum=date.today(), lebensdauer_jahre=10)
        d = berechne_ersatzplanung()
        self.assertEqual(d['budget_total'], Decimal('0.00'))
        self.assertEqual(len(d['rows']), 1)

    def test_budget_horizont(self):
        from core.services.ersatzplanung import berechne_ersatzplanung
        _lg, e, _m, _v = _basis_objekte()
        # Ersatz erst in ~25 Jahren → ausserhalb 10-Jahres-Horizont
        self._element(e, jahre=30, alter_jahre=5, neuwert='5000')
        d = berechne_ersatzplanung(horizont_jahre=10)
        self.assertEqual(d['budget_total'], Decimal('0.00'))
        self.assertEqual(d['jahres_budget'], [])

    def test_ersatzplanung_pdf_view(self):
        _lg, e, _m, _v = _basis_objekte()
        self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/ersatzplanung/?pdf=1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_ersatzplanung_zeigt_budget(self):
        _lg, e, _m, _v = _basis_objekte()
        self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/ersatzplanung/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Ersatzbudget je Jahr')


class ErneuerungsfondsDeckungTests(TestCase):
    """Ersatzplanung ↔ Erneuerungsfonds: Deckungsgrad + empfohlene Rückstellung."""

    def _setup(self, bestand, einlage, neuwert='2000', jahre=10, alter=5):
        from portfolio.models import Ausstattung
        from finance.models import Erneuerungsfonds
        lg, e, _m, _v = _basis_objekte()
        Erneuerungsfonds.objects.create(liegenschaft=lg, bestand=Decimal(bestand),
                                        jaehrliche_einlage=Decimal(einlage))
        einbau = date.today() - timedelta(days=int(365.25 * alter))
        Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Gerät',
                                   neuwert=Decimal(neuwert), einbau_datum=einbau,
                                   lebensdauer_jahre=jahre)
        return lg, e

    def test_deckung_gedeckt(self):
        from core.services.ersatzplanung import berechne_ersatzplanung, fonds_deckung
        lg, e = self._setup(bestand='5000', einlage='0', neuwert='2000')
        d = berechne_ersatzplanung(aktive_lg=lg)
        deck = fonds_deckung(lg, d['budget_total'], d['horizont_jahre'])
        self.assertTrue(deck['gedeckt'])
        self.assertEqual(deck['bestand'], Decimal('5000'))
        # Empfehlung = Budget / Horizont = 2000/10 = 200
        self.assertEqual(deck['empfohlen'], Decimal('200.00'))

    def test_deckung_unterdeckung_und_mehrbedarf(self):
        from core.services.ersatzplanung import berechne_ersatzplanung, fonds_deckung
        lg, e = self._setup(bestand='0', einlage='50', neuwert='2000')
        d = berechne_ersatzplanung(aktive_lg=lg)
        deck = fonds_deckung(lg, d['budget_total'], d['horizont_jahre'])
        # Projektion 0 + 50*10 = 500 < 2000 → Unterdeckung
        self.assertFalse(deck['gedeckt'])
        self.assertEqual(deck['projiziert'], Decimal('500'))
        # empfohlen 200, Einlage 50 → Mehrbedarf 150
        self.assertEqual(deck['mehrbedarf'], Decimal('150.00'))

    def test_deckung_none_ohne_fonds(self):
        from core.services.ersatzplanung import fonds_deckung
        _lg, _e, _m, _v = _basis_objekte()
        self.assertIsNone(fonds_deckung(None, Decimal('1000'), 10))

    def test_view_zeigt_deckung(self):
        lg, e = self._setup(bestand='5000', einlage='300')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/ersatzplanung/?lg={lg.id}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Erneuerungsfonds-Deckung')

    def test_pdf_mit_deckung(self):
        lg, e = self._setup(bestand='5000', einlage='300')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/ersatzplanung/?lg={lg.id}&pdf=1')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))


class ObjekteGruppierungTests(TestCase):
    """Objekte-Übersicht nach Liegenschaft gruppiert (Akkordeon)."""

    def test_gruppierung_nach_liegenschaft(self):
        from portfolio.models import Einheit
        lg1, e1, _m, _v = _basis_objekte()
        lg2 = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Andere Gasse 5', plz='3000', ort='Bern',
                                          versicherungswert=Decimal('500000'))
        Einheit.objects.create(liegenschaft=lg2, bezeichnung='2 Zi', typ='whg',
                               nettomiete_aktuell=Decimal('1000'))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/objekte/')
        self.assertEqual(r.status_code, 200)
        gruppen = r.context['gruppen']
        self.assertEqual(len(gruppen), 2)
        ids = {g['lg'].id for g in gruppen}
        self.assertEqual(ids, {lg1.id, lg2.id})
        # Überschrift der Liegenschaft erscheint
        self.assertContains(r, 'Andere Gasse 5')
        self.assertContains(r, 'Teststrasse 1')

    def test_gruppe_zaehlt_belegt_leer(self):
        from portfolio.models import Einheit
        lg, e, _m, _v = _basis_objekte()   # e ist vermietet (aktiver Vertrag)
        Einheit.objects.create(liegenschaft=lg, bezeichnung='Leer 1', typ='whg')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/objekte/')
        g = r.context['gruppen'][0]
        self.assertEqual(g['anzahl'], 2)
        self.assertEqual(g['belegt'], 1)
        self.assertEqual(g['leer'], 1)


class HypothekenTests(TestCase):
    """Hypotheken je Liegenschaft: Zinskosten, Fälligkeiten, Gruppierung, CRUD."""

    def test_jaehrlicher_zins(self):
        from finance.models import Hypothek
        lg, _e, _m, _v = _basis_objekte()
        hy = Hypothek.objects.create(liegenschaft=lg, betrag=Decimal('500000'),
                                     zinssatz=Decimal('1.500'))
        self.assertEqual(hy.jaehrlicher_zins, Decimal('7500.00'))

    def test_view_kpi_und_gruppierung(self):
        from finance.models import Hypothek
        lg, _e, _m, _v = _basis_objekte()
        Hypothek.objects.create(liegenschaft=lg, betrag=Decimal('400000'), zinssatz=Decimal('2.000'))
        Hypothek.objects.create(liegenschaft=lg, betrag=Decimal('100000'), zinssatz=Decimal('1.000'))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/hypotheken/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['total_schuld'], Decimal('500000'))
        self.assertEqual(r.context['total_zins'], Decimal('9000.00'))  # 8000 + 1000
        self.assertEqual(len(r.context['gruppen']), 1)
        self.assertEqual(r.context['gruppen'][0]['schuld'], Decimal('500000'))

    def test_erfassen_und_loeschen(self):
        from finance.models import Hypothek
        lg, _e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/hypotheken/', {
            'aktion': 'neu', 'liegenschaft_id': str(lg.id), 'bank': 'ZKB',
            'betrag': '350000', 'zinssatz': '1.750', 'typ': 'saron', 'ablauf': '2030-06-30'})
        self.assertEqual(r.status_code, 302)
        hy = Hypothek.objects.get(liegenschaft=lg)
        self.assertEqual(hy.bank, 'ZKB')
        self.assertEqual(hy.betrag, Decimal('350000'))
        r2 = c.post('/neu/hypotheken/', {'aktion': 'loeschen', 'id': str(hy.id)})
        self.assertEqual(r2.status_code, 302)
        self.assertFalse(Hypothek.objects.filter(id=hy.id).exists())

    def test_ablauf_warnung(self):
        from finance.models import Hypothek
        lg, _e, _m, _v = _basis_objekte()
        Hypothek.objects.create(liegenschaft=lg, betrag=Decimal('100000'),
                                ablauf=date.today() + timedelta(days=60))  # < 180 T
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/hypotheken/')
        self.assertEqual(r.context['n_ablaufend'], 1)
        self.assertContains(r, 'bald fällig')

    def test_belehnung_gegen_versicherungswert(self):
        from finance.models import Hypothek
        lg, _e, _m, _v = _basis_objekte()  # versicherungswert 1'000'000
        Hypothek.objects.create(liegenschaft=lg, betrag=Decimal('600000'))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/hypotheken/')
        self.assertEqual(r.context['gruppen'][0]['belehnung'], 60)


class LiegenschaftDokumenteGruppenTests(TestCase):
    """Liegenschaft-Dokumente nach Objekt gruppiert (Akkordeon)."""

    def _doc(self, **kw):
        from rentals.models import Dokument
        from django.core.files.base import ContentFile
        d = Dokument(kategorie='sonstiges', **kw)
        d.datei.save('x.pdf', ContentFile(b'%PDF-1'), save=False)
        d.save()
        return d

    def test_gruppierung_objekt_und_allgemein(self):
        from portfolio.models import Einheit
        lg, e, _m, _v = _basis_objekte()
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='2 Zi', typ='whg')
        # 1 Dokument allgemein (nur Liegenschaft), 1 auf Objekt e, 1 auf e2
        self._doc(liegenschaft=lg, bezeichnung='Allgemein-Doc')
        self._doc(liegenschaft=lg, einheit=e, bezeichnung='Objekt-e-Doc')
        self._doc(liegenschaft=lg, einheit=e2, bezeichnung='Objekt-e2-Doc')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/liegenschaften/{lg.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['dok_total'], 3)
        gruppen = r.context['dok_gruppen']
        # Allgemein zuerst, dann je Objekt
        self.assertIsNone(gruppen[0]['einheit'])
        labels = [g['label'] for g in gruppen]
        self.assertIn('3.5 Zi', labels)
        self.assertIn('2 Zi', labels)
        self.assertContains(r, 'Objekt-e-Doc')

    def test_vertragsdokument_nicht_in_liegenschaftsablage(self):
        lg, e, _m, v = _basis_objekte()
        # Vertragsgebundene Dokumente leben am Mietverhältnis (Objekt → «Verhältnisse»)
        # und bei der Person — NICHT mehr in der gebäudeweiten Liegenschafts-Ablage.
        self._doc(vertrag=v, bezeichnung='Vertrags-Doc')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/liegenschaften/{lg.id}/')
        self.assertEqual(r.context['dok_total'], 0)
        self.assertNotContains(r, 'Vertrags-Doc')

    def test_keine_dokumente(self):
        lg, _e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/liegenschaften/{lg.id}/')
        self.assertEqual(r.context['dok_total'], 0)
        self.assertContains(r, 'Keine Dokumente hinterlegt')


class GeraetZaehlerTests(TestCase):
    """Geräte + Zähler erfassen — auf Objekt- und Liegenschaftsebene (allgemein)."""

    def test_objekt_geraet_add_und_del(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/geraet/', {'einheit_id': str(e.id), 'kategorie': 'Waschmaschine',
                                    'marke': 'V-Zug', 'modell': 'Adora'})
        self.assertEqual(r.status_code, 302)
        g = Geraet.objects.get(einheit=e)
        self.assertEqual(g.kategorie, 'Waschmaschine')
        self.assertEqual(g.marke, 'V-Zug')
        c.post(f'/neu/geraet/{g.id}/loeschen/')
        self.assertFalse(Geraet.objects.filter(id=g.id).exists())

    def test_objekt_zaehler_add(self):
        from portfolio.models import Zaehler
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/zaehler/', {'einheit_id': str(e.id), 'typ': 'Strom',
                                     'zaehler_nummer': 'ABC-123', 'aktueller_stand': '1234.5'})
        self.assertEqual(r.status_code, 302)
        z = Zaehler.objects.get(einheit=e)
        self.assertEqual(z.typ, 'Strom')
        self.assertEqual(z.zaehler_nummer, 'ABC-123')

    def test_zaehler_bearbeiten(self):
        from portfolio.models import Zaehler
        lg, e, m, v = _basis_objekte()
        z = Zaehler.objects.create(einheit=e, typ='Strom', zaehler_nummer='A1',
                                   aktueller_stand=Decimal('100'))
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/zaehler/{z.id}/bearbeiten/', {
            'typ': 'Wasser kalt', 'zaehler_nummer': 'W-9', 'standort': 'Keller',
            'aktueller_stand': '250.75'})
        self.assertEqual(r.status_code, 302)
        z.refresh_from_db()
        self.assertEqual(z.typ, 'Wasser kalt')
        self.assertEqual(z.zaehler_nummer, 'W-9')
        self.assertEqual(z.standort, 'Keller')
        self.assertEqual(z.aktueller_stand, Decimal('250.75'))

    def test_geraet_bearbeiten(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        g = Geraet.objects.create(einheit=e, kategorie='Boiler', marke='Alt')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/geraet/{g.id}/bearbeiten/', {
            'kategorie': 'Wärmepumpe', 'marke': 'Neu', 'modell': 'X2'})
        self.assertEqual(r.status_code, 302)
        g.refresh_from_db()
        self.assertEqual(g.kategorie, 'Wärmepumpe')
        self.assertEqual(g.marke, 'Neu')
        self.assertEqual(g.modell, 'X2')

    def test_geraet_technische_felder(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/geraet/', {'liegenschaft_id': str(lg.id), 'kategorie': 'Boiler',
                                    'seriennummer': 'SN-4711', 'kapazitaet': '300 L',
                                    'standort': 'Keller', 'notiz': 'entkalkt 2025'})
        self.assertEqual(r.status_code, 302)
        g = Geraet.objects.get(liegenschaft=lg, kategorie='Boiler')
        self.assertEqual(g.seriennummer, 'SN-4711')
        self.assertEqual(g.kapazitaet, '300 L')
        self.assertEqual(g.standort, 'Keller')
        self.assertEqual(g.notiz, 'entkalkt 2025')

    def test_liegenschaft_allgemeines_geraet(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/geraet/', {'liegenschaft_id': str(lg.id), 'kategorie': 'Heizung',
                                    'marke': 'Viessmann'})
        self.assertEqual(r.status_code, 302)
        g = Geraet.objects.get(liegenschaft=lg)
        self.assertEqual(g.kategorie, 'Heizung')
        self.assertIsNone(g.einheit_id)

    def test_liegenschaft_allgemeinstrom_zaehler(self):
        from portfolio.models import Zaehler
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/zaehler/', {'liegenschaft_id': str(lg.id), 'typ': 'Allgemeinstrom',
                                     'zaehler_nummer': 'AS-9'})
        self.assertEqual(r.status_code, 302)
        z = Zaehler.objects.get(liegenschaft=lg)
        self.assertEqual(z.typ, 'Allgemeinstrom')
        self.assertIsNone(z.einheit_id)

    def test_liegenschaft_technik_sichtbar(self):
        """Technik steht seit 4b.3 im Reiter «Stammdaten», nicht mehr eigenstaendig.

        Der Test hiess `..._technik_tab_sichtbar` und suchte die Panel-ID
        `lg-technik`. Sie gibt es nicht mehr: Das Aktenregister
        (`faelle/akten.py`) bildet `technik` auf `stammdaten` ab — Geraete und
        Zaehler beschreiben die Anlage, sie sind kein eigener Vorgang. Geprueft
        wird weiterhin dasselbe: dass die Geraeteliste auf der Seite ankommt.
        """
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        Geraet.objects.create(liegenschaft=lg, kategorie='Boiler')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/liegenschaften/{lg.id}/')
        self.assertContains(r, 'lg-stammdaten')
        self.assertContains(r, 'Allgemeine Geräte')
        self.assertContains(r, 'Boiler')

    def test_objekt_merkmale_speichern_und_anzeige(self):
        from portfolio.models import Einheit
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/objekte/{e.id}/merkmale/', {
            'merkmale': ['Balkon', 'Lift'], 'merkmale_eigene': 'Weinkeller, Sauna'})
        self.assertEqual(r.status_code, 302)
        e.refresh_from_db()
        self.assertIn('Balkon', e.merkmale)
        self.assertIn('Lift', e.merkmale)
        self.assertIn('Weinkeller', e.merkmale)
        self.assertIn('Sauna', e.merkmale)
        # Im Objekt-Detail sichtbar (Badges) + eigene Merkmale in der Optionsliste
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('Merkmale', body)
        self.assertIn('Weinkeller', body)

    def test_objekt_raumbuch_accordion(self):
        from portfolio.models import Ausstattung
        lg, e, m, v = _basis_objekte()
        Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Backofen')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/objekte/{e.id}/')
        # Raum als <details>-Akkordeon dargestellt
        self.assertContains(r, 'group-open:rotate-90')
        self.assertContains(r, 'Küche')


class NachtN7SchluesselTests(TestCase):
    """Nacht-Audit N7: Schlüsselregister mit Ausgabe/Rücknahme je Objekt."""

    def _heute(self):
        from django.utils import timezone as tz
        return tz.localdate()

    def _setup(self):
        lg, e, m, v = _basis_objekte()
        u = _team_user()
        c = Client(); c.force_login(u)
        return lg, e, m, v, c

    def test_schluessel_erfassen_und_tab(self):
        from portfolio.models import Schluessel
        lg, e, m, v, c = self._setup()
        r = c.post('/neu/schluessel/', {'einheit_id': e.id, 'typ': 'Wohnung',
                                        'schluessel_nummer': 'W-101', 'anzahl': '3'})
        self.assertEqual(r.status_code, 302)
        sch = Schluessel.objects.get(einheit=e)
        self.assertEqual(sch.schluessel_nummer, 'W-101')
        self.assertEqual(sch.anzahl, 3)
        self.assertEqual(sch.liegenschaft_id, lg.id)
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('Schlüssel', body)
        self.assertIn('W-101', body)

    def test_ausgabe_und_rueckgabe(self):
        from portfolio.models import Schluessel, SchluesselAusgabe
        lg, e, m, v, c = self._setup()
        sch = Schluessel.objects.create(liegenschaft=lg, einheit=e, typ='Wohnung',
                                        schluessel_nummer='W-1', anzahl=2)
        r = c.post(f'/neu/schluessel/{sch.id}/ausgabe/', {'empfaenger': f'mieter:{m.id}'})
        self.assertEqual(r.status_code, 302)
        a = SchluesselAusgabe.objects.get(schluessel=sch)
        self.assertEqual(a.mieter_id, m.id)
        self.assertIsNone(a.rueckgabe_am)
        c.post(f'/neu/schluessel/ausgabe/{a.id}/rueckgabe/')
        a.refresh_from_db()
        self.assertEqual(a.rueckgabe_am, self._heute())

    def test_ausgabe_blockiert_wenn_alle_weg(self):
        from portfolio.models import Schluessel, SchluesselAusgabe
        lg, e, m, v, c = self._setup()
        sch = Schluessel.objects.create(liegenschaft=lg, einheit=e, typ='Keller',
                                        schluessel_nummer='K-1', anzahl=1)
        c.post(f'/neu/schluessel/{sch.id}/ausgabe/', {'empfaenger': f'mieter:{m.id}'})
        c.post(f'/neu/schluessel/{sch.id}/ausgabe/', {'empfaenger': f'mieter:{m.id}'})
        self.assertEqual(SchluesselAusgabe.objects.filter(schluessel=sch).count(), 1)

    def test_loeschen_blockiert_bei_offener_ausgabe(self):
        from portfolio.models import Schluessel, SchluesselAusgabe
        lg, e, m, v, c = self._setup()
        sch = Schluessel.objects.create(liegenschaft=lg, einheit=e, typ='Wohnung',
                                        schluessel_nummer='W-2', anzahl=1)
        SchluesselAusgabe.objects.create(schluessel=sch, mieter=m)
        c.post(f'/neu/schluessel/{sch.id}/loeschen/')
        self.assertTrue(Schluessel.objects.filter(id=sch.id).exists())
        # Nach Rücknahme klappt das Löschen
        a = sch.ausgaben.first(); a.rueckgabe_am = self._heute(); a.save()
        c.post(f'/neu/schluessel/{sch.id}/loeschen/')
        self.assertFalse(Schluessel.objects.filter(id=sch.id).exists())

    def test_handwerker_ausgabe(self):
        from portfolio.models import Schluessel, SchluesselAusgabe
        from crm.models import Handwerker
        lg, e, m, v, c = self._setup()
        hw = Handwerker.objects.create(firma='Sanitär AG')
        sch = Schluessel.objects.create(liegenschaft=lg, einheit=e, typ='Haustüre',
                                        schluessel_nummer='H-9', anzahl=5)
        c.post(f'/neu/schluessel/{sch.id}/ausgabe/', {'empfaenger': f'handwerker:{hw.id}'})
        a = SchluesselAusgabe.objects.get(schluessel=sch)
        self.assertEqual(a.handwerker_id, hw.id)
        self.assertIsNone(a.mieter_id)
