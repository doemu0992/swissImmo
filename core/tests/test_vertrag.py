"""Testmodul vertrag — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 13 Klassen, unveraendert uebernommen."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (
    _team_user, _basis_objekte, _sig_bytes, Mieter, Eigentuemer, Organisation,
    Liegenschaft, Einheit, Mietvertrag)



class MietvertragObjektartTests(TestCase):
    """Vertrag richtet sich nach der Objektart (Titel + Mietrecht-Regime)."""

    def _einheit(self, typ):
        lg = Liegenschaft.objects.create(strasse='Artweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Objekt', typ=typ,
                                   nettomiete_aktuell=Decimal('150'))
        m = Mieter.objects.create(typ='person', nachname='Muster')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal('150'), nebenkosten=Decimal('0'),
                                       status='aktiv')
        return lg, e, m, v

    def test_titel_und_kategorie(self):
        faelle = {
            'whg': ('Mietvertrag für Wohnräume', 'wohnen', True),
            'gew': ('Mietvertrag für Geschäftsräume', 'gewerbe', True),
            'pp':  ('Mietvertrag für einen Parkplatz', 'nebenobjekt', False),
            'gar': ('Mietvertrag für eine Garage', 'nebenobjekt', False),
            'bas': ('Mietvertrag für einen Bastel-/Hobbyraum', 'nebenobjekt', False),
        }
        for typ, (titel, kat, geschuetzt) in faelle.items():
            _lg, e, _m, v = self._einheit(typ)
            self.assertEqual(v.vertrag_titel, titel, typ)
            self.assertEqual(v.mietrecht_kategorie, kat, typ)
            self.assertEqual(v.ist_geschuetzt, geschuetzt, typ)
        # Kaution-Obergrenze nur bei Wohnräumen
        _lg, e, _m, v = self._einheit('whg')
        self.assertEqual(v.kaution_max_monate, 3)
        _lg, e, _m, v = self._einheit('pp')
        self.assertIsNone(v.kaution_max_monate)

    def test_pdf_titel_parkplatz(self):
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        _lg, e, _m, v = self._einheit('pp')
        pdf = generate_vertrag_pdf_bytes(v)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_wizard_vorwahl_liefert_titel(self):
        _lg, e, _m, v = self._einheit('pp')
        team = _team_user(); c = Client(); c.force_login(team)
        r = c.get(f'/neu/vertraege/neu/?einheit={e.id}')
        obj = r.context['liegenschaften'][0]['objekte'][0]
        self.assertEqual(obj['vertrag_titel'], 'Mietvertrag für einen Parkplatz')
        self.assertEqual(obj['kategorie'], 'nebenobjekt')

    def test_checkliste_regime_nebenobjekt(self):
        """Vermieterkündigung eines Parkplatzes → KEIN amtliches Formular."""
        from core.models import Pendenz
        _lg, e, _m, v = self._einheit('pp')
        team = _team_user(); c = Client(); c.force_login(team)
        c.post(f'/neu/vertraege/{v.id}/kuendigen/', {
            'absender': 'vermieter', 'eingang_datum': date.today().isoformat(),
            'zustellung': 'einschreiben'})
        titel = list(Pendenz.objects.filter(vertrag=v).values_list('titel', flat=True))
        self.assertIn('Kündigung schriftlich mitteilen', titel)
        self.assertNotIn('Amtliches Kündigungsformular versenden', titel)

    def test_checkliste_regime_wohnung(self):
        """Vermieterkündigung einer Wohnung → amtliches Formular."""
        from core.models import Pendenz
        _lg, e, _m, v = self._einheit('whg')
        team = _team_user(); c = Client(); c.force_login(team)
        c.post(f'/neu/vertraege/{v.id}/kuendigen/', {
            'absender': 'vermieter', 'eingang_datum': date.today().isoformat(),
            'zustellung': 'einschreiben'})
        titel = list(Pendenz.objects.filter(vertrag=v).values_list('titel', flat=True))
        self.assertIn('Amtliches Kündigungsformular versenden', titel)

    def test_kuendigung_note_einstellplatz_vs_bastelraum(self):
        # Parkplatz/Garage = Einstellplatz → Art. 266e (2 Wochen)
        for typ in ('pp', 'gar'):
            _lg, _e, _m, v = self._einheit(typ)
            self.assertIn('Art. 266e', v.nebenobjekt_kuendigung_note, typ)
        # Bastelraum = übrige unbewegliche Sache → Art. 266b (3 Monate)
        _lg, _e, _m, v = self._einheit('bas')
        self.assertIn('Art. 266b', v.nebenobjekt_kuendigung_note)
        self.assertNotIn('266e', v.nebenobjekt_kuendigung_note)
        # Wohnung hat keine Nebenobjekt-Note
        _lg, _e, _m, v = self._einheit('whg')
        self.assertEqual(v.nebenobjekt_kuendigung_note, '')


class GewerbeWizardTests(TestCase):
    """Etappe D: derselbe Wizard, aber Gewerbe blendet Modell/Staffel ein und
    speichert korrekt (Kündigungsfrist-Default 6, Staffelstufen)."""

    def _gew_einheit(self):
        lg = Liegenschaft.objects.create(strasse='Laden 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('2000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='EG Laden', typ='gew',
                                   nettomiete_aktuell=Decimal('3000'), nebenkosten_aktuell=Decimal('300'))
        m = Mieter.objects.create(typ='firma', firmen_name='Test GmbH')
        return lg, e, m

    def test_wizard_zeigt_gewerbe_felder(self):
        lg, e, m = self._gew_einheit()
        team = _team_user(); c = Client(); c.force_login(team)
        body = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        self.assertIn('id="gewerbe-box"', body)
        self.assertIn('name="mietzins_modell"', body)
        self.assertIn("o.kategorie === 'gewerbe'", body)

    def test_wizard_parkplatz_einstellplatz_anpassung(self):
        from portfolio.models import Einheit
        lg = Liegenschaft.objects.create(strasse='Weg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 1', typ='pp',
                                   nettomiete_aktuell=Decimal('120'))
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        # Objektdaten tragen die Einstellplatz-Kennung + JS reagiert darauf
        self.assertIn('ist_einstellplatz', body)
        self.assertIn('frist-ep-note', body)
        self.assertIn('266e', body)
        self.assertIn('setMonateAlle', body)

    def test_parkplatz_frist_anzeige_und_pdf_ohne_nk(self):
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag as MV
        from django.template.loader import get_template
        from django.utils import timezone
        lg = Liegenschaft.objects.create(strasse='Weg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 1', typ='pp',
                                   nettomiete_aktuell=Decimal('120'))
        mi = Mieter.objects.create(typ='person', vorname='H', nachname='M', email='h@x.ch')
        # 2 Wochen (monate 0)
        v = MV.objects.create(einheit=e, mieter=mi, netto_mietzins=Decimal('120'),
                              nebenkosten=Decimal('0'), kuendigungsfrist_monate=0,
                              beginn=timezone.localdate())
        self.assertIn('2 Wochen', v.kuendigungsfrist_anzeige)
        # längere Frist möglich (3 Monate auf Monatsende)
        v.kuendigungsfrist_monate = 3; v.save()
        self.assertIn('3 Monate auf Ende eines Monats', v.kuendigungsfrist_anzeige)
        # PDF (Garage-Template) ohne Nebenkosten-Zeile
        ctx = {'vertrag': v, 'mieter': mi, 'einheit': e, 'liegenschaft': lg,
               'eigentuemer': None, 'verwaltung': None, 'heute': timezone.localdate(),
               'miete_fmt': '120.00', 'nk_fmt': '0.00', 'brutto_fmt': '120.00',
               'kaution_fmt': '0.00', 'unterschrift_path': None}
        html = get_template('core/mietvertrag_garage.html').render(ctx)
        self.assertNotIn('Nebenkosten', html)
        self.assertIn('Mietzins', html)

    def test_wizard_parkplatz_nk_komplett_entfernt(self):
        """Beim Einstellplatz muss NK aus Wizard/Vorschau verschwinden: NK-Feld
        ausblendbar, Schritt 6 (Nebenkosten) übersprungen, Vorschau ohne NK."""
        from portfolio.models import Einheit
        lg = Liegenschaft.objects.create(strasse='Weg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 1', typ='pp',
                                   nettomiete_aktuell=Decimal('120'))
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        # NK-Feld + Brutto-Anzeige sind ausblendbare Container
        self.assertIn('id="nk-field-box"', body)
        self.assertIn('id="brutto-box"', body)
        # Schritt-Navigation überspringt den Nebenkosten-Schritt bei Einstellplatz
        self.assertIn('function visibleSteps()', body)
        self.assertIn('updateStepNav()', body)
        # Vorschau nutzt dynamische Abschnittsnummern statt hartem "6. Nebenkosten"
        self.assertIn('secN(', body)
        self.assertNotIn('<div class="pvsec">6. Nebenkosten</div>', body)

    def test_speichern_parkplatz_nk_wird_auf_null_gezwungen(self):
        """Auch wenn das Formular NK mitliefert, wird beim Einstellplatz 0 gespeichert."""
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag as MV
        lg = Liegenschaft.objects.create(strasse='Weg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 2', typ='pp',
                                   nettomiete_aktuell=Decimal('150'))
        mi = Mieter.objects.create(typ='person', vorname='A', nachname='B', email='a@b.ch')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': e.id, 'mieter_id': mi.id, 'beginn': '2026-01-01',
            'netto_mietzins': '150', 'nebenkosten': '80',  # NK wird absichtlich mitgeschickt
            'kuendigungsfrist': '0',
        })
        v = MV.objects.filter(einheit=e).order_by('-id').first()
        self.assertIsNotNone(v)
        self.assertEqual(v.nebenkosten, Decimal('0.00'))
        self.assertEqual(v.netto_mietzins, Decimal('150'))

    def test_speichern_gewerbe_staffel_und_frist(self):
        from rentals.models import Mietvertrag as MV, Staffelstufe
        lg, e, m = self._gew_einheit()
        team = _team_user(); c = Client(); c.force_login(team)
        c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': e.id, 'mieter_id': m.id, 'beginn': '2024-01-01',
            'netto_mietzins': '3000', 'nebenkosten': '300',
            'mietzins_modell': 'staffel',
            'staffel_ab': ['2025-01-01', '2026-01-01'],
            'staffel_netto': ['3100', '3200'],
            'zweckbestimmung': 'Betrieb einer Bäckerei',
            # kuendigungsfrist bewusst weggelassen → Default 6 (Gewerbe)
        })
        v = MV.objects.filter(einheit=e).order_by('-id').first()
        self.assertIsNotNone(v)
        self.assertEqual(v.mietzins_modell, 'staffel')
        self.assertEqual(v.kuendigungsfrist_monate, 6)
        self.assertEqual(v.zweckbestimmung, 'Betrieb einer Bäckerei')
        self.assertEqual(v.staffelstufen.count(), 2)
        self.assertEqual(v.effektiver_netto_mietzins(date(2025, 6, 1)), Decimal('3100'))

    def test_live_mietrecht_check_im_wizard(self):
        """Der Wizard enthält die Live-Plausibilitätsprüfung (meldet beim Erfassen)."""
        lg, e, m = self._gew_einheit()
        team = _team_user(); c = Client(); c.force_login(team)
        body = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        self.assertIn('function mietrechtCheck', body)
        self.assertIn('id="mietrecht-warn"', body)
        self.assertIn('Art. 257e OR', body)   # Kaution-Prüfung
        self.assertIn('Art. 269b OR', body)   # Index-Dauer-Prüfung

    def test_pdf_gewerbe_index_rendert(self):
        from rentals.models import Mietvertrag as MV
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        lg, e, m = self._gew_einheit()
        v = MV.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                              netto_mietzins=Decimal('3000'), nebenkosten=Decimal('300'),
                              status='aktiv', mietzins_modell='index',
                              zweckbestimmung='Büro')
        pdf = generate_vertrag_pdf_bytes(v)
        self.assertTrue(pdf.startswith(b'%PDF'))


class VerhaeltnisseAblageTests(TestCase):
    """Vertragsdokumente werden pro Mietverhältnis (= Vertrag) gebündelt und
    erscheinen bei der Person UND am Objekt (Tab «Verhältnisse»). Die
    Liegenschafts-Ablage zeigt sie NICHT mehr (nur gebäude-/objektbezogene
    Dokumente ohne Vertragsbezug)."""

    def _dok(self, titel, *, vertrag=None, mieter=None, einheit=None, liegenschaft=None, kategorie='vertrag'):
        from rentals.models import Dokument
        from django.core.files.base import ContentFile
        d = Dokument(bezeichnung=titel, titel=titel, kategorie=kategorie,
                     vertrag=vertrag, mieter=mieter, einheit=einheit, liegenschaft=liegenschaft)
        d.datei.save(f'{titel}.pdf', ContentFile(b'%PDF-1.4 test'), save=True)
        return d

    def test_objekt_verhaeltnisse_tab_zeigt_vertragsdokumente(self):
        lg, e, m, v = _basis_objekte()
        self._dok('Mietvertrag (unterzeichnet)', vertrag=v)
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        # Neuer Tab + Panel vorhanden, Historie-Panel weg
        self.assertIn('id="obj-verhaeltnisse"', body)
        self.assertNotIn('id="obj-historie"', body)
        self.assertIn('Verhältnisse', body)
        # Mietername + Dokument sichtbar im Verhältnis-Bündel
        self.assertIn('Hans Muster', body)
        self.assertIn('Mietvertrag (unterzeichnet)', body)

    def test_person_dokumente_nach_verhaeltnis_gruppiert(self):
        lg, e, m, v = _basis_objekte()
        self._dok('Mietvertrag (unterzeichnet)', vertrag=v, mieter=m, einheit=e)
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertIn('Nach Mietverhältnis gruppiert', body)
        self.assertIn('Mietvertrag (unterzeichnet)', body)
        # Verhältnis-Label enthält Objekt + Zeitraum
        self.assertIn('3.5 Zi', body)

    def test_liegenschaft_ablage_ohne_vertragsdokumente(self):
        lg, e, m, v = _basis_objekte()
        self._dok('Mietvertrag (unterzeichnet)', vertrag=v, einheit=e, liegenschaft=lg)
        self._dok('Gebäudeversicherung 2026', einheit=None, liegenschaft=lg, kategorie='sonstiges')
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/liegenschaften/{lg.id}/').content.decode()
        # Gebäudedokument bleibt, Vertragsdokument ist hier ausgeblendet
        self.assertIn('Gebäudeversicherung 2026', body)
        self.assertNotIn('Mietvertrag (unterzeichnet)', body)


class DocuSealAblageTests(TestCase):
    """Signierter Vertrag wird zentral abgelegt (Portal/Person/Objekt) +
    DocuSeal-Versand graceful ohne API-Key."""

    def test_ablage_signierter_vertrag_ueberall(self):
        from core.services.ablage import ablage_signierter_vertrag
        from rentals.models import Dokument
        from django.core.files.base import ContentFile
        lg, e, m, v = _basis_objekte()
        dok = ablage_signierter_vertrag(v, pdf_bytes=b'%PDF-signed')
        self.assertIsNotNone(dok)
        # EIN rentals.Dokument, mit allen Bezügen → überall sichtbar
        self.assertEqual(dok.vertrag_id, v.id)
        self.assertEqual(dok.mieter_id, m.id)
        self.assertEqual(dok.einheit_id, e.id)
        self.assertEqual(dok.liegenschaft_id, lg.id)
        self.assertEqual(dok.kategorie, 'vertrag')
        self.assertTrue(dok.im_portal_sichtbar)   # → Mieterportal

    def test_ablage_signiert_kanonisch_einzeln(self):
        """Genau EIN signiertes Dokument pro Vertrag — auch bei Mehrfach-Versand."""
        from core.services.ablage import ablage_signierter_vertrag
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        d1 = ablage_signierter_vertrag(v, pdf_bytes=b'%PDF-A')
        self.assertTrue(d1.bezeichnung.startswith('Mietvertrag (unterzeichnet)'))
        self.assertIsNotNone(d1.erstellt_am)
        # identischer Inhalt (wiederholtes save()) → kein Duplikat
        d1b = ablage_signierter_vertrag(v, pdf_bytes=b'%PDF-A')
        self.assertEqual(d1.id, d1b.id)
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 1)
        # neue Unterschrift (anderer Inhalt) → weiterhin genau EIN Dokument (aktualisiert)
        ablage_signierter_vertrag(v, pdf_bytes=b'%PDF-B')
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 1)
        # Explosionstest: viele Rückläufe mit je anderem Inhalt → bleibt bei EINEM
        for i in range(5):
            ablage_signierter_vertrag(v, pdf_bytes=f'%PDF-{i}'.encode())
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 1)

    def test_ablage_raeumt_alt_dubletten_zusammen(self):
        """Bereits explodierte Alt-Dubletten werden beim nächsten Rücklauf auf eines zusammengeführt."""
        from core.services.ablage import ablegen, ablage_signierter_vertrag
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        # simuliere 3 alte signierte Dubletten
        for s in (b'%PDF-1', b'%PDF-2', b'%PDF-3'):
            ablegen(s, "Mietvertrag (unterzeichnet) — alt", kategorie='vertrag', vertrag=v, dedup=False)
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 3)
        ablage_signierter_vertrag(v, pdf_bytes=b'%PDF-neu')
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 1)

    def test_vertragsbeilage_dedup_pro_objekt(self):
        """Beilagen-Ablage: ein Beleg je (Objekt, Titel) — kein Duplikat bei Neu-Erstellung."""
        from core.views.pdf import _ablegen_vertragsdokument
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        _ablegen_vertragsdokument(b'%PDF-1', 'Hausordnung', v)
        _ablegen_vertragsdokument(b'%PDF-2', 'Hausordnung', v)   # 2. Erstellung → kein Duplikat
        self.assertEqual(Dokument.objects.filter(einheit=e, bezeichnung='Hausordnung').count(), 1)

    def test_bereinige_vertragsbeilagen_dubletten(self):
        from core.services.ablage import ablegen, bereinige_vertragsbeilagen_dubletten
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        # simuliere 3 explodierte Beilagen-Dubletten (gleiches Objekt + Titel)
        for s in (b'%PDF-1', b'%PDF-2', b'%PDF-3'):
            ablegen(s, "Hausordnung", kategorie='vertrag', vertrag=v, einheit=e, dedup=False)
        self.assertEqual(Dokument.objects.filter(einheit=e, bezeichnung='Hausordnung').count(), 3)
        n = bereinige_vertragsbeilagen_dubletten()
        self.assertEqual(n, 2)
        self.assertEqual(Dokument.objects.filter(einheit=e, bezeichnung='Hausordnung').count(), 1)

    def test_bereinige_signierte_dubletten(self):
        """Einmal-Aufräumung reduziert bestehende Dubletten (Person/Objekt-Akte)."""
        from core.services.ablage import ablegen, bereinige_signierte_dubletten
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        for i in range(4):
            ablegen(f'%PDF-{i}'.encode(), f"Mietvertrag (unterzeichnet) — {i}",
                    kategorie='vertrag', vertrag=v, dedup=False)
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 4)
        n = bereinige_signierte_dubletten()
        self.assertEqual(n, 3)
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 1)

    def test_model_save_legt_signierten_vertrag_ab(self):
        from rentals.models import Dokument
        from django.core.files.base import ContentFile
        lg, e, m, v = _basis_objekte()
        v.pdf_datei.save('signed.pdf', ContentFile(b'%PDF-signed'), save=False)
        v.sign_status = 'unterzeichnet'
        v.save()
        # erscheint als rentals.Dokument (Person/Portal/Objekt)
        self.assertTrue(Dokument.objects.filter(vertrag=v, kategorie='vertrag').exists())

    def test_signierter_vertrag_in_person_und_objekt(self):
        from core.services.ablage import ablage_signierter_vertrag
        lg, e, m, v = _basis_objekte()
        ablage_signierter_vertrag(v, pdf_bytes=b'%PDF-x')
        c = Client(); c.force_login(_team_user())
        # Person-Akte (nach Verhältnis)
        rp = c.get(f'/neu/personen/{m.id}/')
        self.assertEqual(rp.context['dok_total'], 1)
        # Objekt → «Verhältnisse»: Dokument am Mietverhältnis
        ro = c.get(f'/neu/objekte/{e.id}/')
        self.assertEqual(ro.context['verhaeltnisse_dok_total'], 1)
        self.assertContains(ro, 'Mietvertrag (unterzeichnet)')
        # Liegenschafts-Ablage zeigt Vertragsdokumente NICHT mehr
        rl = c.get(f'/neu/liegenschaften/{lg.id}/')
        self.assertEqual(rl.context['dok_total'], 0)

    def test_docuseal_senden_ohne_key(self):
        from core.services.docuseal_service import docuseal_senden
        lg, e, m, v = _basis_objekte()
        ok, msg = docuseal_senden(v)
        self.assertFalse(ok)
        self.assertIn('nicht konfiguriert', msg)

    def test_wizard_senden_ohne_key_erstellt_trotzdem(self):
        from portfolio.models import Einheit
        lg = Liegenschaft.objects.create(strasse='Musterweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg', typ='whg',
                                   nettomiete_aktuell=Decimal('1500'))
        m = Mieter.objects.create(typ='person', vorname='Hans', nachname='Muster',
                                  email='hans@example.ch')
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': str(e.id), 'mieter_id': str(m.id),
            'netto_mietzins': '1500', 'nebenkosten': '200', 'beginn': '2025-01-01',
            'abschluss': 'senden'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Mietvertrag.objects.filter(einheit=e).exists())  # trotzdem erstellt

    def test_vertrag_signieren_view_ohne_key(self):
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/vertraege/{v.id}/signieren/')
        self.assertEqual(r.status_code, 302)  # graceful, Fehlermeldung


class VertragUnterschriftsblockTests(TestCase):
    """Unterschriftsblock im Vertrags-PDF: Vermieter Ort+Datum automatisch,
    Mieter Ort+Datum als vom Unterzeichner auszufüllende DocuSeal-Felder."""

    def _render(self, typ='whg'):
        from portfolio.models import Einheit
        from crm.models import Organisation
        from django.template.loader import get_template
        from django.utils import timezone
        Organisation.objects.create(firma='Test Verwaltung', strasse='Weg 1',
                                  plz='8000', ort='Zürich')
        lg = Liegenschaft.objects.create(strasse='Musterweg 1', plz='8004', ort='Bern',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Obj', typ=typ,
                                   nettomiete_aktuell=Decimal('1500'))
        m = Mieter.objects.create(typ='person', vorname='Hans', nachname='Muster',
                                  email='hans@example.ch')
        v = Mietvertrag.objects.create(einheit=e, mieter=m,
                                       netto_mietzins=Decimal('1500'),
                                       nebenkosten=Decimal('200'),
                                       beginn=timezone.localdate())
        tpl = ('core/mietvertrag_garage.html' if typ in ('pp', 'bas', 'gar')
               else 'core/mietvertrag_pdf.html')
        ctx = {'vertrag': v, 'mieter': m, 'einheit': e, 'liegenschaft': lg,
               'eigentuemer': None, 'verwaltung': Organisation.objects.first(),
               'heute': timezone.localdate(), 'miete_fmt': '1500.00',
               'nk_fmt': '200.00', 'brutto_fmt': '1700.00', 'kaution_fmt': '0.00',
               'unterschrift_path': None}
        return get_template(tpl).render(ctx)

    def _assert_block(self, html):
        # Vermieter: Ort automatisch (aus Verwaltung), keine leere "Ort, Datum"-Zeile
        self.assertIn('Zürich', html)
        # Mieter: DocuSeal-Felder für Ort (text) und Datum (date)
        self.assertIn('{{Ort Mieter;role=Mieter;type=text', html)
        self.assertIn('{{Datum Mieter;role=Mieter;type=date', html)
        # Unterschriftsanker bleibt bestehen
        self.assertIn('{{Unterschrift Mieter;role=Mieter;type=signature', html)

    def test_wohnung(self):
        self._assert_block(self._render('whg'))

    def test_gewerbe(self):
        self._assert_block(self._render('gew'))

    def test_parkplatz(self):
        self._assert_block(self._render('pp'))


class VertragUnterzeichnetTimestampTests(TestCase):
    """Rücklauf-Zeitstempel des unterzeichneten Vertrags (Detail-Ansicht)."""

    def test_unterzeichnet_am_beim_save(self):
        lg, e, m, v = _basis_objekte()
        from django.core.files.base import ContentFile
        self.assertIsNone(v.unterzeichnet_am)
        v.pdf_datei.save('s.pdf', ContentFile(b'%PDF-signed'), save=False)
        v.sign_status = 'unterzeichnet'
        v.save()
        v.refresh_from_db()
        self.assertIsNotNone(v.unterzeichnet_am)

    def test_detail_zeigt_ruecklauf_im_verlauf(self):
        """Der Rücklauf-Zeitstempel steht als Ereignis im Verlauf-Tab (nicht als
        eigene Zeile im Seitenkopf); der Status-Badge behält ihn als Tooltip."""
        lg, e, m, v = _basis_objekte()
        from django.utils import timezone
        v.sign_status = 'unterzeichnet'
        v.unterzeichnet_am = timezone.now()
        v.save()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/{v.id}/').content.decode()
        # Verlauf-Ereignis vorhanden
        self.assertIn('Unterschriebener Vertrag zurückerhalten', body)
        # Kopf: nur noch Tooltip (title="…"), keine sichtbare Zusatzzeile mehr
        self.assertIn('title="Unterschrieben zurück am', body)
        self.assertNotIn('<i class="fa-solid fa-clock-rotate-left mr-1"></i>Unterschrieben zurück am', body)


class DocuSealWebhookTests(TestCase):
    """Toleranter DocuSeal-Webhook: verschiedene Payloads, kein 'Wert ungültig',
    unterschriebener Vertrag wird zentral abgelegt."""

    def test_vertrag_id_aus_name(self):
        from rentals.services import _vertrag_id_aus_name
        self.assertEqual(_vertrag_id_aus_name('Mietvertrag 42'), 42)
        self.assertEqual(_vertrag_id_aus_name('Mietvertrag42'), 42)
        self.assertEqual(_vertrag_id_aus_name(''), 0)
        self.assertEqual(_vertrag_id_aus_name('Foo'), 0)

    def test_erster_dokument_url(self):
        from rentals.services import _erster_dokument_url
        self.assertEqual(_erster_dokument_url([{'url': 'a'}, {'url': 'b'}]), 'a')
        self.assertIsNone(_erster_dokument_url([]))
        self.assertIsNone(_erster_dokument_url(None))

    def test_event_nicht_abgeschlossen_ignoriert(self):
        from rentals.services import verarbeite_docuseal_event
        lg, e, m, v = _basis_objekte()
        # 'form.viewed' o.ä. → nichts tun, kein Fehler
        self.assertFalse(verarbeite_docuseal_event({'event_type': 'form.viewed', 'data': {'name': f'Mietvertrag {v.id}'}}))
        v.refresh_from_db()
        self.assertNotEqual(v.sign_status, 'unterzeichnet')

    def test_completed_legt_vertrag_ab(self):
        from unittest.mock import patch, MagicMock
        from rentals.services import verarbeite_docuseal_event
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        resp = MagicMock(status_code=200, content=b'%PDF-signed')
        payload = {'event_type': 'submission.completed',
                   'data': {'name': f'Mietvertrag {v.id}', 'combined_document_url': 'https://api.docuseal.com/y.pdf'}}
        with patch('rentals.services.requests.get', return_value=resp):
            ok = verarbeite_docuseal_event(payload)
        self.assertTrue(ok)
        v.refresh_from_db()
        self.assertEqual(v.sign_status, 'unterzeichnet')
        self.assertEqual(v.status, 'aktiv')
        # zentral abgelegt (Portal/Person/Objekt)
        self.assertTrue(Dokument.objects.filter(vertrag=v, kategorie='vertrag').exists())

    def test_completed_documents_liste(self):
        from unittest.mock import patch, MagicMock
        from rentals.services import verarbeite_docuseal_event
        lg, e, m, v = _basis_objekte()
        resp = MagicMock(status_code=200, content=b'%PDF-x')
        payload = {'event_type': 'form.completed',
                   'data': {'name': f'Mietvertrag {v.id}', 'documents': [{'url': 'https://api.docuseal.com/doc.pdf'}]}}
        with patch('rentals.services.requests.get', return_value=resp):
            self.assertTrue(verarbeite_docuseal_event(payload))

    def test_completed_ssrf_fremde_url_wird_abgewiesen(self):
        # SSRF-Schutz: eine doc_url auf fremdem/nicht-HTTPS-Host darf NICHT
        # heruntergeladen werden — kein requests.get, kein Ablegen (Härtung).
        from unittest.mock import patch, MagicMock
        from rentals.services import verarbeite_docuseal_event
        lg, e, m, v = _basis_objekte()
        resp = MagicMock(status_code=200, content=b'%PDF-evil')
        payload = {'event_type': 'submission.completed',
                   'data': {'name': f'Mietvertrag {v.id}',
                            'combined_document_url': 'http://169.254.169.254/latest/meta-data'}}
        with patch('rentals.services.requests.get', return_value=resp) as g:
            ok = verarbeite_docuseal_event(payload)
        self.assertFalse(ok)
        g.assert_not_called()
        v.refresh_from_db()
        self.assertNotEqual(v.sign_status, 'unterzeichnet')

    def test_webhook_endpoint_gibt_200(self):
        # Mit gültigem Secret: Endpunkt darf NIE 422/'Wert ungültig' liefern, auch bei
        # leerem/kaputtem Body (tolerantes Parsing). Ohne Secret → 403 (kein offener
        # Endpoint, siehe docuseal_webhook-Härtung).
        from django.test import override_settings
        c = Client()
        with override_settings(DOCUSEAL_WEBHOOK_SECRET='geheim'):
            hdr = {'HTTP_X_WEBHOOK_SECRET': 'geheim'}
            r = c.post('/api/rentals/webhook/docuseal', data='{}',
                       content_type='application/json', **hdr)
            self.assertEqual(r.status_code, 200)
            r2 = c.post('/api/rentals/webhook/docuseal', data='kein json',
                        content_type='application/json', **hdr)
            self.assertEqual(r2.status_code, 200)
            r3 = c.post('/api/rentals/webhook/docuseal', data='{}',
                        content_type='application/json')  # ohne Secret
            self.assertEqual(r3.status_code, 403)


class VertragAktivSyncTests(TestCase):
    """Offener Punkt 1: `aktiv` folgt immer dem Status (kein Drift mehr)."""

    def test_entwurf_ist_nicht_aktiv(self):
        lg, e, m, v = _basis_objekte()
        v2 = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                        netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'),
                                        status='entwurf', aktiv=True)   # aktiv=True gesetzt …
        v2.refresh_from_db()
        self.assertFalse(v2.aktiv)   # … aber Status entwurf ⇒ aktiv=False

    def test_statuswechsel_synct_aktiv(self):
        lg, e, m, v = _basis_objekte()   # status='aktiv' → aktiv=True
        v.refresh_from_db()
        self.assertTrue(v.aktiv)
        v.status = 'gekuendigt'
        v.save()
        v.refresh_from_db()
        self.assertFalse(v.aktiv)
        v.status = 'aktiv'
        v.save(update_fields=['status'])   # aktiv wird trotz update_fields mitgezogen
        v.refresh_from_db()
        self.assertTrue(v.aktiv)


class VertragBearbeitenTests(TestCase):
    """Vertrag bearbeiten: Entwurf voll, aktiv nur Detailfelder (Miete gesperrt,
    serverseitig erzwungen)."""

    def test_entwurf_bearbeiten_via_assistent(self):
        from rentals.models import Mietvertrag
        lg, e, m, v = _basis_objekte()
        v.status = 'entwurf'; v.netto_mietzins = Decimal('1500'); v.save()
        c = Client(); c.force_login(_team_user())
        # Entwurf → Bearbeiten leitet zum Assistenten (Wizard) mit ?edit=
        r = c.get(f'/neu/vertraege/{v.id}/bearbeiten/')
        self.assertEqual(r.status_code, 302)
        self.assertIn(f'/neu/vertraege/neu/?edit={v.id}', r['Location'])
        # Assistent im Edit-Modus: Prefill-Daten + verstecktes edit_id
        body = c.get(f'/neu/vertraege/neu/?edit={v.id}').content.decode()
        self.assertIn('id="edit-data"', body)
        self.assertIn(f'name="edit_id" value="{v.id}"', body)
        # Speichern mit edit_id aktualisiert denselben Vertrag (kein neuer)
        vor = Mietvertrag.objects.count()
        c.post('/neu/vertraege/neu/speichern/', {
            'edit_id': str(v.id), 'einheit_id': str(e.id), 'mieter_id': str(m.id),
            'beginn': '2024-01-01', 'netto_mietzins': '1700', 'nebenkosten': '210',
            'nk_abrechnungsart': 'akonto', 'zahlungsrhythmus': 'monatlich',
            'verteilschluessel': 'm2', 'mietzins_modell': 'fest', 'kuendigungsfrist': '3',
            'anzahl_personen': '1', 'nebenraeume': 'Keller 9'})
        self.assertEqual(Mietvertrag.objects.count(), vor)   # kein neuer Vertrag
        v.refresh_from_db()
        self.assertEqual(v.netto_mietzins, Decimal('1700'))
        self.assertEqual(v.nebenraeume, 'Keller 9')
        self.assertEqual(v.status, 'entwurf')   # ohne aktiv_setzen bleibt Entwurf

    def test_aktiv_miete_gesperrt(self):
        lg, e, m, v = _basis_objekte()   # status='aktiv', netto 1500
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vertraege/{v.id}/bearbeiten/').content.decode()
        self.assertNotIn('name="netto_mietzins"', r)   # gesperrt → kein Eingabefeld
        self.assertIn('eingeschränkte Bearbeitung', r)
        # Versuch, die Miete + Beginn zu ändern → wird ignoriert; Detailfeld greift
        c.post(f'/neu/vertraege/{v.id}/bearbeiten/', {
            'netto_mietzins': '9999', 'beginn': '2020-01-01', 'nebenkosten': '9999',
            'kuendigungsfrist': '3', 'nebenraeume': 'Estrich', 'anzahl_personen': '1'})
        v.refresh_from_db()
        self.assertEqual(v.netto_mietzins, Decimal('1500'))   # unverändert
        self.assertEqual(v.beginn, date(2024, 1, 1))          # unverändert
        self.assertEqual(v.nebenraeume, 'Estrich')            # Detailfeld geändert

    def test_pdf_nur_bei_aktiv(self):
        """PDFs werden nur erzeugt, wenn 'aktiv' angehakt ist — ein Entwurf
        bleibt dokumentlos, bis er aktiviert wird."""
        from rentals.models import Mietvertrag, Dokument
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        base = {'einheit_id': str(e.id), 'mieter_id': str(m.id), 'beginn': '2026-05-01',
                'netto_mietzins': '1400', 'nebenkosten': '200', 'nk_abrechnungsart': 'akonto',
                'zahlungsrhythmus': 'monatlich', 'verteilschluessel': 'm2',
                'mietzins_modell': 'fest', 'kuendigungsfrist': '3', 'anzahl_personen': '1'}
        # 1. Entwurf (ohne aktiv_setzen) → keine Dokumente
        c.post('/neu/vertraege/neu/speichern/', base)
        v1 = Mietvertrag.objects.filter(einheit=e, status='entwurf').order_by('-id').first()
        self.assertIsNotNone(v1)
        self.assertEqual(Dokument.objects.filter(vertrag=v1).count(), 0)
        # 2. Aktiv gesetzt → Dokumente werden erzeugt
        c.post('/neu/vertraege/neu/speichern/', {**base, 'aktiv_setzen': 'on'})
        v2 = Mietvertrag.objects.filter(einheit=e, status='aktiv').order_by('-id').first()
        self.assertIsNotNone(v2)
        self.assertGreater(Dokument.objects.filter(vertrag=v2).count(), 0)

    def test_entwurf_aktivieren_erzeugt_pdf(self):
        """Wird ein Entwurf im Assistenten aktiviert, entstehen die PDFs."""
        from rentals.models import Mietvertrag, Dokument
        lg, e, m, v = _basis_objekte()
        v.status = 'entwurf'; v.save()
        self.assertEqual(Dokument.objects.filter(vertrag=v).count(), 0)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/vertraege/neu/speichern/', {
            'edit_id': str(v.id), 'einheit_id': str(e.id), 'mieter_id': str(m.id),
            'beginn': '2024-01-01', 'netto_mietzins': '1500', 'nebenkosten': '200',
            'nk_abrechnungsart': 'akonto', 'zahlungsrhythmus': 'monatlich',
            'verteilschluessel': 'm2', 'mietzins_modell': 'fest', 'kuendigungsfrist': '3',
            'anzahl_personen': '1', 'aktiv_setzen': 'on'})
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')
        self.assertGreater(Dokument.objects.filter(vertrag=v).count(), 0)

    def test_vertrag_loeschen_raeumt_dokumente_auf(self):
        """Beim Löschen eines Vertrags werden seine auto-erzeugten Vertragspaket-
        Dokumente mitgelöscht — keine verwaisten Kopien in der Personen-Akte."""
        from rentals.models import Mietvertrag, Dokument
        lg, e, m, v = _basis_objekte()
        # zwei automatische Vertragspaket-Dokumente + ein Fremd-Upload
        Dokument.objects.create(vertrag=v, mieter=m, einheit=e, kategorie='vertrag',
                                bezeichnung='Mietvertrag', titel='Mietvertrag')
        Dokument.objects.create(vertrag=v, mieter=m, einheit=e, kategorie='vertrag',
                                bezeichnung='Hausordnung', titel='Hausordnung')
        upload = Dokument.objects.create(mieter=m, kategorie='korrespondenz',
                                         bezeichnung='Ausweis-Kopie', titel='Ausweis-Kopie')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/loeschen/')
        self.assertFalse(Mietvertrag.objects.filter(id=v.id).exists())
        # Vertragspaket-Dokumente weg, kein verwaistes (vertrag=None) übrig
        self.assertEqual(Dokument.objects.filter(bezeichnung='Mietvertrag').count(), 0)
        self.assertEqual(Dokument.objects.filter(bezeichnung='Hausordnung').count(), 0)
        # Fremd-Upload bleibt erhalten
        self.assertTrue(Dokument.objects.filter(id=upload.id).exists())

    def test_bearbeiten_button_auf_detailseite(self):
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/{v.id}/').content.decode()
        self.assertIn(f'/neu/vertraege/{v.id}/bearbeiten/', body)


class FormulareTabTests(TestCase):
    """Zentraler «Formulare & Prozesse»-Tab am Vertrag."""

    def test_tab_zeigt_alle_gruppen_und_formulare(self):
        _lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/vertraege/{v.id}/').content.decode()
        # Tab existiert
        self.assertIn('vt-formulare', html)
        # Gruppen
        for g in ('Mietrechtliche Formulare', 'Kaution (Art. 257e)', 'Prozesse', 'Beilagen'):
            self.assertIn(g, html)
        # Kern-Formulare verlinkt
        self.assertIn(f'/neu/mietzins/{v.id}/anfangsmietzins/', html)
        self.assertIn(f'/neu/vertraege/{v.id}/maengelruege/', html)
        self.assertIn(f'/neu/vertraege/{v.id}/untermiete/', html)

    def test_kontext_kaution_nur_wenn_einbezahlt(self):
        from core.views.fw import _formulare_prozesse
        _lg, _e, _m, v = _basis_objekte()
        # ohne Einzahlung: Kautions-Belege nicht verfügbar
        gr = {g['titel']: g for g in _formulare_prozesse(v)}
        kaution = {i['titel']: i for i in gr['Kaution (Art. 257e)']['items']}
        self.assertFalse(kaution['Hinterlegungsbestätigung']['verfuegbar'])
        # nach Einzahlung: verfügbar
        v.kautions_art = 'sperrkonto'; v.kautions_einbezahlt_am = date.today(); v.save()
        gr2 = {g['titel']: g for g in _formulare_prozesse(v)}
        kaution2 = {i['titel']: i for i in gr2['Kaution (Art. 257e)']['items']}
        self.assertTrue(kaution2['Hinterlegungsbestätigung']['verfuegbar'])
        self.assertTrue(kaution2['Freigabe an Bank']['verfuegbar'])


class BefristungTests(TestCase):
    """`ist_befristet` trennt sauber befristete Verhältnisse (Zeitablauf,
    Art. 266 OR) von unbefristeten und von gekündigten Verträgen."""

    def test_flag_und_properties(self):
        _lg, _e, _m, v = _basis_objekte()
        # Default: unbefristet
        self.assertFalse(v.ist_befristet)
        self.assertEqual(v.vertragsdauer_art, 'unbefristet')
        self.assertIsNone(v.laeuft_aus_am)
        # Befristet setzen
        v.ist_befristet = True
        v.ende = date(2027, 12, 31)
        v.save()
        self.assertEqual(v.vertragsdauer_art, 'befristet')
        self.assertEqual(v.laeuft_aus_am, date(2027, 12, 31))

    def test_gekuendigter_unbefristeter_hat_ende_aber_ist_nicht_befristet(self):
        _lg, _e, _m, v = _basis_objekte()
        # Kündigung setzt ende + status, aber NICHT ist_befristet
        v.status = 'gekuendigt'
        v.ende = date(2026, 3, 31)
        v.save()
        self.assertFalse(v.ist_befristet)
        self.assertIsNone(v.laeuft_aus_am)  # Kündigungs-Ende zählt nicht als Auslauf

    def test_mieterwechsel_listet_nur_echte_befristete(self):
        from datetime import date as _d
        lg, e, _m, v = _basis_objekte()
        # unbefristeter aktiver Vertrag mit gesetztem ende (z.B. Alt-Daten) → NICHT gelistet
        v.ende = _d.today() + timedelta(days=30)
        v.ist_befristet = False
        v.save()
        # zweiter, echt befristeter Vertrag
        m2 = Mieter.objects.create(typ='person', vorname='Eva', nachname='Meier',
                                   strasse='Weg 2', plz='8000', ort='Zürich')
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='2.5 Zi', typ='wohnung',
                                    nettomiete_aktuell=Decimal('1200'))
        vb = Mietvertrag.objects.create(mieter=m2, einheit=e2, beginn=date(2024, 1, 1),
                                        netto_mietzins=Decimal('1200'), nebenkosten=Decimal('0'),
                                        status='aktiv', ist_befristet=True,
                                        ende=_d.today() + timedelta(days=30))
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.get('/neu/mieterwechsel/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Meier', html)          # befristeter Vertrag gelistet
        self.assertNotIn('Muster', html)      # unbefristeter (Alt-ende) NICHT als Auslauf

    def test_form_erstellt_befristeten_vertrag(self):
        lg, e, m, _v = _basis_objekte()
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post('/neu/vertraege/neu/speichern/', {
            'mieter_id': m.id, 'einheit_id': e.id,
            'beginn': '2026-01-01', 'ende': '2027-12-31', 'ist_befristet': '1',
            'netto_mietzins': '1500', 'nebenkosten': '200',
            'kuendigungsfrist': '3', 'anzahl_personen': '1',
        })
        self.assertIn(r.status_code, (200, 302))
        vneu = Mietvertrag.objects.filter(einheit=e, beginn=date(2026, 1, 1)).first()
        self.assertIsNotNone(vneu)
        self.assertTrue(vneu.ist_befristet)
        self.assertEqual(vneu.ende, date(2027, 12, 31))


class WGVertragTests(TestCase):
    """WG-fähiger Vertrag: weitere_mieter (M2M) + Solidarhaftung, additiv zum
    FK-Mitmieter (Ehepaar)."""

    def _person(self, vn, nn):
        return Mieter.objects.create(typ='person', vorname=vn, nachname=nn,
                                     strasse='Gasse 1', plz='8000', ort='Zürich')

    def test_alle_mieter_und_ist_wg(self):
        _lg, e, m, v = _basis_objekte()
        self.assertEqual(v.alle_mieter, [m])
        self.assertFalse(v.ist_wg)
        m2 = self._person('Eva', 'Meier'); v.mitmieter = m2; v.save()
        self.assertEqual([p.pk for p in v.alle_mieter], [m.pk, m2.pk])
        self.assertFalse(v.ist_wg)   # zwei Parteien = kein WG
        m3 = self._person('Tim', 'Roth'); v.weitere_mieter.add(m3)
        self.assertTrue(v.ist_wg)
        self.assertEqual(len(v.alle_mieter), 3)
        self.assertEqual([p.pk for p in v.mitmieter_alle], [m2.pk, m3.pk])

    def test_mitmieter_block_enthaelt_wg(self):
        from core.services.formular_fill import _mitmieter_block
        _lg, e, m, v = _basis_objekte()
        m2 = self._person('Eva', 'Meier'); v.mitmieter = m2; v.save()
        m3 = self._person('Tim', 'Roth'); v.weitere_mieter.add(m3)
        block = _mitmieter_block(v, sep=', ')
        self.assertIn('Eva Meier', block)
        self.assertIn('Tim Roth', block)

    def test_view_hinzufuegen_entfernen(self):
        _lg, e, m, v = _basis_objekte()
        k = self._person('Kim', 'Wg')
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/vertraege/{v.id}/wg-mieter/', {'aktion': 'hinzufuegen', 'mieter_id': k.id})
        self.assertIn(k, list(v.weitere_mieter.all()))
        c.post(f'/neu/vertraege/{v.id}/wg-mieter/', {'aktion': 'entfernen', 'mieter_id': k.id})
        self.assertNotIn(k, list(v.weitere_mieter.all()))

    def test_view_hinzufuegen_hauptmieter_abgelehnt(self):
        _lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/vertraege/{v.id}/wg-mieter/', {'aktion': 'hinzufuegen', 'mieter_id': m.id})
        self.assertEqual(v.weitere_mieter.count(), 0)   # Hauptmieter nicht als WG-Mieter

    def test_solidarhaftung_toggle(self):
        _lg, e, m, v = _basis_objekte()
        self.assertTrue(v.solidarhaftung)   # Default an
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/vertraege/{v.id}/wg-mieter/', {'aktion': 'solidarhaftung', 'wert': 'off'})
        v.refresh_from_db()
        self.assertFalse(v.solidarhaftung)

    def test_wg_mieter_bekommt_wohnadresse(self):
        _lg, e, m, v = _basis_objekte()
        k = self._person('Kim', 'Wg')
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/vertraege/{v.id}/wg-mieter/', {'aktion': 'hinzufuegen', 'mieter_id': k.id})
        from crm.models import MieterAdresse
        self.assertTrue(MieterAdresse.objects.filter(mieter=k, art='wohn').exists())

    def test_detail_zeigt_wg_panel(self):
        _lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.get(f'/neu/vertraege/{v.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Weitere Mieter (WG)', r.content.decode())


class UnterschriftBriefeTests(TestCase):
    """Die Unterschrift lag nur auf Verträgen und Formularen — die reportlab-
    Briefe zogen eine Linie und liessen sie leer. Ein Einschreiben, das eine
    Kündigung androht, gehört unterschrieben."""

    def setUp(self):
        # Eigenes MEDIA_ROOT, damit die Testbilder nicht im echten media/ landen.
        import tempfile
        from django.test import override_settings
        self._tmp = tempfile.TemporaryDirectory()
        self._ov = override_settings(MEDIA_ROOT=self._tmp.name)
        self._ov.enable()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._ov.disable)

    def _verwaltung(self, mit_unterschrift):
        from django.core.files.base import ContentFile
        from crm.models import Organisation
        vw = Organisation.objects.first()
        if vw is None:
            vw = Organisation.objects.create(firma='Testverwaltung', strasse='Weg 1',
                                           plz='4500', ort='Solothurn')
        if mit_unterschrift:
            vw.unterschrift_bild.save('sig.png', ContentFile(_sig_bytes()), save=True)
        else:
            Organisation.objects.filter(pk=vw.pk).update(unterschrift_bild='')
        vw.refresh_from_db()
        return vw

    def _mahnung(self, vertrag, vw):
        from core.views.email_views import generate_mahnung_combined_pdf_bytes
        return generate_mahnung_combined_pdf_bytes(vertrag, vw, 'August 2026',
                                                   '100.00', date(2026, 8, 1))

    # ---------- Helfer ----------
    def test_unterschrift_pfad_findet_das_bild(self):
        from core.services.unterschrift import unterschrift_pfad
        vw = self._verwaltung(True)
        self.assertTrue(unterschrift_pfad(vw))

    def test_unterschrift_pfad_ohne_bild_ist_none(self):
        from core.services.unterschrift import unterschrift_pfad
        vw = self._verwaltung(False)
        self.assertIsNone(unterschrift_pfad(vw))
        self.assertIsNone(unterschrift_pfad(None))

    def test_unterschrift_pfad_nimmt_den_ersten_mit_bild(self):
        """Reihenfolge = Unterzeichner-Reihenfolge des Aufrufers."""
        from django.core.files.base import ContentFile
        from core.services.unterschrift import unterschrift_pfad
        from crm.models import Eigentuemer
        vw = self._verwaltung(False)
        md = Eigentuemer.objects.create(firma_oder_name='Eigentümer AG')
        md.unterschrift_bild.save('sig_md.png', ContentFile(_sig_bytes()), save=True)
        # Eigentuemer.save() benennt das Bild in sig_man_<id>.png um (Hintergrund raus)
        self.assertIn('sig_man', unterschrift_pfad(vw, md))

    # ---------- Mahnung mit Kündigungsandrohung (Art. 257d OR) ----------
    def test_mahnung_257d_traegt_die_unterschrift(self):
        lg, e, m, v = _basis_objekte()
        ohne = self._mahnung(v, self._verwaltung(False))
        mit = self._mahnung(v, self._verwaltung(True))
        self.assertGreater(len(mit), len(ohne) + 500)

    def test_mahnung_257d_ohne_unterschrift_bleibt_erzeugbar(self):
        """Fehlt das Bild, muss der Brief trotzdem rauskommen — nur eben leer."""
        lg, e, m, v = _basis_objekte()
        pdf = self._mahnung(v, self._verwaltung(False))
        self.assertTrue(pdf.startswith(b'%PDF'))

    # ---------- Mietprozess-Briefe ----------
    def test_kautionsbestaetigung_traegt_die_unterschrift(self):
        from core.services.mietprozess_briefe import kaution_hinterlegung_pdf
        lg, e, m, v = _basis_objekte()
        ohne = kaution_hinterlegung_pdf(v, self._verwaltung(False))
        mit = kaution_hinterlegung_pdf(v, self._verwaltung(True))
        self.assertGreater(len(mit), len(ohne) + 500)

    def test_maengelruege_traegt_die_unterschrift(self):
        from core.services.mietprozess_briefe import maengelruege_pdf
        lg, e, m, v = _basis_objekte()
        ohne = maengelruege_pdf(v, 'Heizung defekt', frist_tage=14,
                                verwaltung=self._verwaltung(False))
        mit = maengelruege_pdf(v, 'Heizung defekt', frist_tage=14,
                               verwaltung=self._verwaltung(True))
        self.assertGreater(len(mit), len(ohne) + 500)

    # ---------- Serienbrief ----------
    def test_serienbrief_traegt_die_unterschrift(self):
        from core.services.serienbrief import generate_serienbrief_pdf
        vw_ohne = self._verwaltung(False)
        absender = {'firma': vw_ohne.firma, 'strasse': vw_ohne.strasse,
                    'plz': vw_ohne.plz, 'ort': vw_ohne.ort}
        emp = [{'name': 'Hans Muster', 'anrede': 'Sehr geehrter Herr Muster',
                'strasse': 'Teststrasse 1', 'plz': '4500', 'ort': 'Solothurn'}]
        ohne = generate_serienbrief_pdf(absender, 'Betreff', 'Text', emp,
                                        signatur=(vw_ohne,))
        mit = generate_serienbrief_pdf(absender, 'Betreff', 'Text', emp,
                                       signatur=(self._verwaltung(True),))
        self.assertGreater(len(mit), len(ohne) + 500)

    def test_serienbrief_ohne_signatur_argument_bleibt_kompatibel(self):
        from core.services.serienbrief import generate_serienbrief_pdf
        self._verwaltung(True)
        emp = [{'name': 'Hans Muster', 'strasse': 'Teststrasse 1',
                'plz': '4500', 'ort': 'Solothurn'}]
        pdf = generate_serienbrief_pdf({'firma': 'X'}, 'Betreff', 'Text', emp)
        self.assertTrue(pdf.startswith(b'%PDF'))

    # ---------- Upload-Weg in der App (vorher nur im Django-Admin) ----------
    def test_account_bietet_unterschrift_upload(self):
        from crm.models import Organisation
        self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/account/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="unterschrift_bild"')
        self.assertContains(r, 'bleibt die Linie auf jedem Brief leer')

    def test_account_speichert_hochgeladene_unterschrift(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from crm.models import Organisation
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {
            'firma': vw.firma, 'strasse': vw.strasse, 'plz': vw.plz, 'ort': vw.ort,
            'unterschrift_bild': SimpleUploadedFile('sig.png', _sig_bytes(),
                                                    content_type='image/png')})
        vw.refresh_from_db()
        self.assertTrue(vw.unterschrift_bild)

    def test_account_kann_unterschrift_entfernen(self):
        vw = self._verwaltung(True)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {'firma': vw.firma, 'strasse': vw.strasse,
                                 'plz': vw.plz, 'ort': vw.ort,
                                 'unterschrift_entfernen': '1'})
        vw.refresh_from_db()
        self.assertFalse(vw.unterschrift_bild)

    def test_mandat_formular_nimmt_dateien_entgegen(self):
        """Ohne enctype='multipart/form-data' verschwindet die Datei lautlos."""
        from crm.models import Eigentuemer
        md = Eigentuemer.objects.create(firma_oder_name='Eigentümer AG')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mandate/{md.id}/bearbeiten/')
        self.assertContains(r, 'enctype="multipart/form-data"')
        self.assertContains(r, 'name="unterschrift_bild"')

    def test_mandat_speichert_hochgeladene_unterschrift(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from crm.models import Eigentuemer
        md = Eigentuemer.objects.create(firma_oder_name='Eigentümer AG')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mandate/{md.id}/bearbeiten/', {
            'firma_oder_name': md.firma_oder_name,
            'unterschrift_bild': SimpleUploadedFile('sig.png', _sig_bytes(),
                                                    content_type='image/png')})
        md.refresh_from_db()
        self.assertTrue(md.unterschrift_bild)

    # ---------- Direkt zeichnen (Signature-Pad) ----------
    def _data_url(self):
        """Was canvas.toDataURL('image/png') liefert: transparent + schwarzer Strich."""
        import base64
        import io as _io
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (600, 200), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.line([(30, 140), (120, 50), (210, 150), (300, 55), (560, 70)],
               fill=(17, 24, 39, 255), width=6)
        b = _io.BytesIO(); img.save(b, format="PNG")
        return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()

    def _basis(self, vw):
        return {f: getattr(vw, f) or '' for f in
                ['firma', 'strasse', 'plz', 'ort', 'telefon', 'email', 'iban']}

    def test_account_zeigt_das_zeichenfeld(self):
        self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/account/')
        self.assertContains(r, 'data-us-canvas')
        self.assertContains(r, 'name="unterschrift_gezeichnet"')
        # touch-action: none — sonst scrollt das Handy beim Zeichnen weg
        self.assertContains(r, 'touch-action: none')

    def test_gezeichnete_unterschrift_wird_gespeichert(self):
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': self._data_url()})
        vw.refresh_from_db()
        self.assertTrue(vw.unterschrift_bild)

    def test_gezeichnete_unterschrift_landet_im_brief(self):
        lg, e, m, v = _basis_objekte()
        vw = self._verwaltung(False)
        ohne = self._mahnung(v, vw)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': self._data_url()})
        vw.refresh_from_db()
        self.assertGreater(len(self._mahnung(v, vw)), len(ohne) + 500)

    def test_leeres_zeichenfeld_loescht_die_unterschrift_nicht(self):
        """Wer nur die Adresse ändert, darf die Unterschrift nicht verlieren."""
        vw = self._verwaltung(True)
        name = vw.unterschrift_bild.name
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw), 'unterschrift_gezeichnet': ''})
        vw.refresh_from_db()
        self.assertTrue(vw.unterschrift_bild)
        self.assertEqual(vw.unterschrift_bild.name, name)

    def test_ungueltige_zeichendaten_werden_verworfen(self):
        vw = self._verwaltung(True)
        name = vw.unterschrift_bild.name
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': 'data:image/png;base64,QUJD'})
        vw.refresh_from_db()
        self.assertEqual(vw.unterschrift_bild.name, name)

    def test_mehrfaches_speichern_erzeugt_keine_dateileichen(self):
        """save() verarbeitete das Bild bisher jedes Mal neu und legte dabei eine
        weitere Datei an — der Medienordner füllte sich mit Waisen."""
        import os
        from django.conf import settings
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': self._data_url()})
        for _ in range(3):
            c.post('/neu/account/', self._basis(vw))
        ordner = os.path.join(settings.MEDIA_ROOT, 'unterschriften')
        self.assertEqual(len(os.listdir(ordner)), 1)

    def test_ersetzte_unterschrift_wird_geloescht(self):
        import os
        from django.conf import settings
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': self._data_url()})
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': self._data_url()})
        ordner = os.path.join(settings.MEDIA_ROOT, 'unterschriften')
        self.assertEqual(len(os.listdir(ordner)), 1)

    def test_mandat_nimmt_gezeichnete_unterschrift(self):
        from crm.models import Eigentuemer
        md = Eigentuemer.objects.create(firma_oder_name='Eigentümer AG')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mandate/{md.id}/bearbeiten/')
        self.assertContains(r, 'data-us-canvas')
        c.post(f'/neu/mandate/{md.id}/bearbeiten/', {
            'firma_oder_name': md.firma_oder_name,
            'unterschrift_gezeichnet': self._data_url()})
        md.refresh_from_db()
        self.assertTrue(md.unterschrift_bild)

    # ---------- Leere «Unterschrift» ----------
    def _leere_data_url(self, weiss=False):
        """Was ein geleertes Canvas liefert. iOS Safari feuert beim Absenden ein
        resize (URL-Leiste), das die Fläche leert und erst asynchron wieder
        aufbaut — traf das submit dazwischen, ging genau das hier raus."""
        import base64
        import io as _io
        from PIL import Image
        farbe = (255, 255, 255, 255) if weiss else (0, 0, 0, 0)
        img = Image.new("RGBA", (600, 200), farbe)
        b = _io.BytesIO(); img.save(b, format="PNG")
        return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()

    def test_leeres_canvas_wird_nicht_gespeichert(self):
        """Sonst meldet die App «hinterlegt», die Vorschau bleibt leer und jeder
        Brief geht unsigniert raus — ohne dass irgendwo ein Fehler auftaucht."""
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        for weiss in (False, True):
            c.post('/neu/account/', {**self._basis(vw),
                                     'unterschrift_gezeichnet': self._leere_data_url(weiss)})
            vw.refresh_from_db()
            self.assertFalse(vw.unterschrift_bild, f"leeres Canvas gespeichert (weiss={weiss})")

    def test_leeres_canvas_ueberschreibt_bestehende_unterschrift_nicht(self):
        vw = self._verwaltung(True)
        name = vw.unterschrift_bild.name
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': self._leere_data_url()})
        vw.refresh_from_db()
        self.assertEqual(vw.unterschrift_bild.name, name)

    def test_leeres_canvas_meldet_es_dem_nutzer(self):
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/account/', {**self._basis(vw),
                                     'unterschrift_gezeichnet': self._leere_data_url()},
                   follow=True)
        self.assertContains(r, 'Unterschrift war leer')

    def test_leeres_blatt_als_upload_wird_abgewiesen(self):
        import io as _io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        b = _io.BytesIO(); Image.new("RGB", (400, 120), "white").save(b, format="PNG")
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_bild': SimpleUploadedFile(
                                     'leer.png', b.getvalue(), content_type='image/png')})
        vw.refresh_from_db()
        self.assertFalse(vw.unterschrift_bild)

    # ---------- Datenbankeintrag ohne Datei ----------
    def test_fehlende_bilddatei_wird_nicht_als_hinterlegt_ausgegeben(self):
        """Fehlt die Datei auf dem Server, behauptete die App trotzdem eine
        Unterschrift — Vorschau leer, Brief leer, kein Hinweis worauf es liegt."""
        import os
        from django.conf import settings
        from core.services.unterschrift import unterschrift_url
        vw = self._verwaltung(True)
        os.remove(os.path.join(settings.MEDIA_ROOT, vw.unterschrift_bild.name))
        self.assertEqual(unterschrift_url(vw), '')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/account/')
        self.assertContains(r, 'nicht verwendbar')
        self.assertNotContains(r, 'alt="Unterschrift"')

    def test_leer_gespeicherte_unterschrift_gilt_nicht_als_hinterlegt(self):
        """Altbestand aus dem Canvas-Bug: Datei da, aber vollständig durchsichtig."""
        from django.core.files.base import ContentFile
        from core.services.unterschrift import unterschrift_url
        vw = self._verwaltung(False)
        roh = self._leere_data_url().split(',', 1)[1]
        import base64
        vw.unterschrift_bild.save('leer.png', ContentFile(base64.b64decode(roh)), save=True)
        self.assertEqual(unterschrift_url(vw), '')
        c = Client(); c.force_login(_team_user())
        self.assertContains(c.get('/neu/account/'), 'nicht verwendbar')

    def test_vorhandene_bilddatei_liefert_url(self):
        from core.services.unterschrift import unterschrift_url
        vw = self._verwaltung(True)
        self.assertTrue(unterschrift_url(vw))
        c = Client(); c.force_login(_team_user())
        self.assertContains(c.get('/neu/account/'), 'alt="Unterschrift"')

    # ---------- Liegenschafts-Zuordnung am Mandat ----------
    def test_mandat_speichern_ohne_zuordnungsblock_behaelt_liegenschaften(self):
        """Ein POST ohne den Zuordnungsblock löste bisher still ALLE Liegenschaften
        vom Eigentümer — und nahm damit seine Unterschrift aus jedem Brief."""
        from crm.models import Eigentuemer
        lg, e, m, v = _basis_objekte()
        md = Eigentuemer.objects.create(firma_oder_name='Eigentümer AG')
        lg.eigentuemer = md; lg.save(update_fields=['eigentuemer'])
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mandate/{md.id}/bearbeiten/', {'firma_oder_name': md.firma_oder_name})
        lg.refresh_from_db()
        self.assertEqual(lg.eigentuemer_id, md.id)

    def test_mandat_zuordnung_bleibt_bewusst_aenderbar(self):
        """Mit abgeschicktem Block soll das Abwählen weiterhin greifen."""
        from crm.models import Eigentuemer
        lg, e, m, v = _basis_objekte()
        md = Eigentuemer.objects.create(firma_oder_name='Eigentümer AG')
        lg.eigentuemer = md; lg.save(update_fields=['eigentuemer'])
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mandate/{md.id}/bearbeiten/',
               {'firma_oder_name': md.firma_oder_name, 'lg_zuordnung': '1'})
        lg.refresh_from_db()
        self.assertIsNone(lg.eigentuemer_id)
        c.post(f'/neu/mandate/{md.id}/bearbeiten/',
               {'firma_oder_name': md.firma_oder_name, 'lg_zuordnung': '1',
                'liegenschaften': [str(lg.id)]})
        lg.refresh_from_db()
        self.assertEqual(lg.eigentuemer_id, md.id)
