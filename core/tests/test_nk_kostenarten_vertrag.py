"""MIET-11: Nebenkosten werden im Vertrag einzeln bezeichnet (Art. 257a Abs. 2 OR, BGE 135 III 591).

Bisher stand im Vertrag nur der Satz «Nebenkosten werden gemäss den Bestimmungen des Mietvertrags
abgerechnet», und die Abrechnung verteilte alle Kostenarten ausser den ausgeschlossenen (Opt-out). Jetzt: Opt-in.
Nennt der Vertrag seine Nebenkostenarten (`Mietvertrag.nk_kostenarten`), sind nur diese verrechenbar; der Assistent
verlangt die Liste für neue Verträge mit Akonto oder Pauschale. Altverträge ohne Liste behalten den Bestand.

Gegenproben stehen im Bericht (Code zurückgebaut -> der genannte Test wird rot).
"""
import io
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import Einheit, Liegenschaft, Mieter, Mietvertrag, _team_user, _test_organisation
from .test_nk_rechnung import _Haus

D = Decimal


class AbrechnungOptInTests(_Haus):
    """W1 60 m², W2 40 m²; Lift 1000 und Hauswartung 500, beide nach m².

    W1 nennt nur «Hauswartung» (Opt-in):   Hauswartung 500 × 0.6 = 300.00; Lift 1000 × 0.6 = 600.00 → Eigentümer.
    W2 ohne Liste (Altvertrag):            Lift 400.00 + Hauswartung 200.00 = 600.00.
    Total 1500.00.
    """

    def _aufbau(self, liste1, **kw):
        w1, w2 = self.einheit('W1', '60'), self.einheit('W2', '40')
        v1 = self.vertrag(w1, 'Eins', nk_kostenarten=liste1, **kw)
        v2 = self.vertrag(w2, 'Zwei')
        self.beleg('1000', kategorie='lift')
        self.beleg('500')
        return v1, v2, self.rechnen()

    def test_nicht_genannte_kostenart_wird_nicht_verrechnet(self):
        v1, v2, r = self._aufbau(['hauswartung'])
        z1 = self.zeile(r, v1)
        self.assertEqual(z1['kosten_anteil'], D('300.00'))
        self.assertEqual(z1['aufschluesselung'], [{'kostenart': 'hauswartung', 'betrag': D('300.00')}])
        self.assertEqual(z1['ausgeschlossen'], ['lift'])
        eig = self.zeile(r, typ='eigentuemer')
        self.assertEqual(eig['kosten_anteil'], D('600.00'), 'Der nicht vereinbarte Lift-Anteil trägt der Vermieter')
        self.assertEqual(r['kontroll_summe'], D('1500.00'), 'Nichts darf verschwinden')

    def test_altvertrag_ohne_liste_behaelt_den_bestand(self):
        v1, v2, r = self._aufbau([])
        self.assertEqual(self.zeile(r, v1)['kosten_anteil'], D('900.00'))
        self.assertEqual(self.zeile(r, v2)['kosten_anteil'], D('600.00'))
        self.assertFalse([z for z in r['abrechnungen'] if z['typ'] == 'eigentuemer'])

    def test_genannte_kostenart_wird_verrechnet(self):
        v1, v2, r = self._aufbau(['hauswartung', 'lift'])
        self.assertEqual(self.zeile(r, v1)['kosten_anteil'], D('900.00'))

    def test_der_alte_ausschluss_gilt_weiter_zusaetzlich_zur_liste(self):
        v1, v2, r = self._aufbau(['hauswartung', 'lift'], ausgeschlossene_kostenarten=['lift'])
        self.assertEqual(self.zeile(r, v1)['kosten_anteil'], D('300.00'))
        self.assertEqual(self.zeile(r, typ='eigentuemer')['kosten_anteil'], D('600.00'))


class VertragstextTests(TestCase):

    def setUp(self):
        org = _test_organisation()
        lg = Liegenschaft.objects.create(organisation=org, strasse='Textweg 1', plz='5000', ort='Aarau', kanton='AG',
                                         versicherungswert=D('1000000'))
        self.e = Einheit.objects.create(liegenschaft=lg, bezeichnung='3.5 Zi', typ='whg', nettomiete_aktuell=D('1500'))
        self.m = Mieter.objects.create(typ='person', vorname='Tim', nachname='Text', email='tim@example.ch')

    def vertrag(self, **kw):
        felder = dict(mieter=self.m, einheit=self.e, beginn=date(2026, 12, 1), netto_mietzins=D('1500'),
                      nebenkosten=D('200'), status='entwurf')
        felder.update(kw)
        return Mietvertrag.objects.create(**felder)

    def test_namen_in_der_reihenfolge_des_katalogs(self):
        v = self.vertrag(nk_kostenarten=['wasser', 'heizung', 'unbekannt'])
        self.assertEqual(v.nk_kostenarten_namen, ['Heizkosten', 'Wasser / Abwasser'])
        self.assertEqual(self.vertrag().nk_kostenarten_namen, [])

    def test_mietvertrag_listet_die_nebenkostenarten_einzeln(self):
        from core.services.pdf_service import render_vertrag_html
        html = render_vertrag_html(self.vertrag(nk_kostenarten=['heizung', 'hauswartung']))
        self.assertIn('Der Mieter trägt folgende Nebenkosten, die hier einzeln bezeichnet sind (Art. 257a Abs. 2 OR)', html)
        self.assertIn('Heizkosten, Hauswartung / Reinigung', html)
        self.assertNotIn('Liftkosten', html, 'Nicht genannte Arten stehen nicht im Vertrag')
        self.assertIn('Nicht aufgeführte Kosten sind nicht vereinbart', html)

    def test_altvertrag_ohne_liste_behaelt_den_bisherigen_text(self):
        from core.services.pdf_service import render_vertrag_html
        html = render_vertrag_html(self.vertrag())
        self.assertNotIn('einzeln bezeichnet', html)
        self.assertIn('Nebenkosten sind das Entgelt', html)

    def test_allgemeine_bedingungen_nennen_die_arten(self):
        from pypdf import PdfReader
        from core.services.dokument_service import generate_dokument_pdf_bytes
        v = self.vertrag(nk_kostenarten=['heizung', 'wasser'])
        text = ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(
            generate_dokument_pdf_bytes(v, 'allgemeine-bedingungen'))).pages)
        text = ' '.join(text.split())
        self.assertIn('verrechenbar sind nur die dort einzeln bezeichneten Nebenkostenarten', text)
        self.assertIn('Heizkosten, Wasser / Abwasser', text)
        ohne = ' '.join(' '.join(p.extract_text() for p in PdfReader(io.BytesIO(
            generate_dokument_pdf_bytes(self.vertrag(), 'allgemeine-bedingungen'))).pages).split())
        self.assertNotIn('verrechenbar sind nur', ohne)


class AssistentTests(TestCase):

    def setUp(self):
        org = _test_organisation()
        lg = Liegenschaft.objects.create(organisation=org, strasse='Listenweg 1', plz='5000', ort='Aarau', kanton='AG',
                                         versicherungswert=D('1000000'))
        self.e = Einheit.objects.create(liegenschaft=lg, bezeichnung='3.5 Zi', typ='whg', nettomiete_aktuell=D('1500'))
        self.pp = Einheit.objects.create(liegenschaft=lg, bezeichnung='Parkplatz', typ='pp', nettomiete_aktuell=D('100'))
        self.m = Mieter.objects.create(typ='person', vorname='Lia', nachname='Liste')
        self.c = Client()
        self.c.force_login(_team_user('Verwaltung'))

    def daten(self, **extra):
        d = {'einheit_id': str(self.e.id), 'mieter_id': str(self.m.id), 'netto_mietzins': '1500',
             'nebenkosten': '200', 'beginn': '2026-12-01'}
        d.update(extra)
        return d

    def speichern(self, daten):
        return self.c.post('/neu/vertraege/neu/speichern/', daten)

    def test_akonto_ohne_liste_wird_abgewiesen(self):
        r = self.speichern(self.daten())
        self.assertEqual(r.status_code, 400)
        self.assertIn('nk_kostenarten', r.context['feld_fehler'])
        self.assertIn('Art. 257a Abs. 2 OR', r.context['feld_fehler']['nk_kostenarten'])
        self.assertFalse(Mietvertrag.objects.exists())

    def test_pauschal_ohne_liste_wird_abgewiesen(self):
        r = self.speichern(self.daten(nk_abrechnungsart='pauschal'))
        self.assertEqual(r.status_code, 400)

    def test_ohne_nebenkosten_inbegriffen_und_direkt_ist_keine_liste_noetig(self):
        for extra in ({'nebenkosten': '0'}, {'nk_abrechnungsart': 'inbegriffen'}, {'nk_abrechnungsart': 'direkt'}):
            r = self.speichern(self.daten(**extra))
            self.assertEqual(r.status_code, 302, extra)
            Mietvertrag.objects.all().delete()

    def test_einstellplatz_hat_keine_nebenkosten_und_keine_liste(self):
        r = self.speichern(self.daten(einheit_id=str(self.pp.id), nk_kostenarten=['heizung']))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Mietvertrag.objects.get().nk_kostenarten, [])

    def test_liste_wird_in_katalogreihenfolge_gespeichert_unbekanntes_faellt_weg(self):
        r = self.speichern(self.daten(nk_kostenarten=['wasser', 'heizung', 'erfunden']))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Mietvertrag.objects.get().nk_kostenarten, ['heizung', 'wasser'])

    def test_der_assistent_bietet_den_katalog_an(self):
        r = self.c.get('/neu/vertraege/neu/')
        schluessel = [k['key'] for k in r.context['nk_katalog']]
        from portfolio.models import Verteilschluessel
        self.assertEqual(schluessel, [k for k, _n in Verteilschluessel.KOSTENART_CHOICES])
        vorgabe = {k['key'] for k in r.context['nk_katalog'] if k['vorgabe']}
        self.assertNotIn('verwaltung', vorgabe)
        self.assertNotIn('sonstiges', vorgabe)
        html = r.content.decode()
        self.assertEqual(html.count('type="checkbox" name="nk_kostenarten"'), len(schluessel))

    def test_entwurf_ohne_liste_wird_nicht_aktiviert_altvertrag_schon(self):
        entwurf = Mietvertrag.objects.create(mieter=self.m, einheit=self.e, beginn=date(2026, 12, 1),
                                             netto_mietzins=D('1500'), nebenkosten=D('200'), status='entwurf')
        self.c.post(f'/neu/vertraege/{entwurf.id}/status/', {'status': 'aktiv'})
        entwurf.refresh_from_db()
        self.assertEqual(entwurf.status, 'entwurf')
        entwurf.nk_kostenarten = ['heizung']
        entwurf.save()
        self.c.post(f'/neu/vertraege/{entwurf.id}/status/', {'status': 'aktiv'})
        entwurf.refresh_from_db()
        self.assertEqual(entwurf.status, 'aktiv')
        # ein bereits laufender Vertrag ohne Liste (Altvertrag) bleibt bei archiviert → aktiv unberührt
        alt = Mietvertrag.objects.create(mieter=self.m, einheit=self.pp, beginn=date(2020, 1, 1),
                                         netto_mietzins=D('100'), nebenkosten=D('50'), status='archiviert')
        self.c.post(f'/neu/vertraege/{alt.id}/status/', {'status': 'aktiv'})
        alt.refresh_from_db()
        self.assertEqual(alt.status, 'aktiv')

    def test_nk_aktivierungssperre_im_versand(self):
        from django.test import override_settings
        from core.services.docuseal_service import docuseal_senden
        m = Mieter.objects.create(typ='person', vorname='Mail', nachname='Haber', email='m@example.ch')
        v = Mietvertrag.objects.create(mieter=m, einheit=self.e, beginn=date(2026, 12, 1), netto_mietzins=D('1500'),
                                       nebenkosten=D('200'), status='entwurf')
        with override_settings(DOCUSEAL_API_KEY='k'):
            ok, text = docuseal_senden(v)
        self.assertFalse(ok)
        self.assertIn('Art. 257a Abs. 2 OR', text)
