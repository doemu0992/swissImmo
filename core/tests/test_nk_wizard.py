"""Nebenkosten-Wizard (Modul 1, 27.10.2026): Seiten, Schreibpfade, Fehler f/g/h, E1,
die 12-Monats-Grenze, der CSV-Import und die Mandantengrenze.

Die Rechnung selbst prüft `test_nk_rechnung.py`; hier geht es um das, was ein Mensch im
Wizard tut und was er dabei nicht tun darf.
"""
import io
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from ._helfer import (Einheit, Liegenschaft, Mieter, Mietvertrag, _seed_konten, _team_user,
                      _test_organisation)
from ._isolation import MandantenFixture

SCHRITTE = ('periode', 'kosten', 'verteilung', 'heizung', 'pruefen', 'abschluss')


def _pdf_text(inhalt):
    from pypdf import PdfReader
    return '\n'.join(seite.extract_text() or '' for seite in PdfReader(io.BytesIO(inhalt)).pages)


class _Basis(TestCase):
    def setUp(self):
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg
        _seed_konten()
        self.org = _test_organisation(nk_honorar_prozent=Decimal('0'))
        self.lg = Liegenschaft.objects.create(organisation=self.org, strasse='Wizardweg 1', plz='8000', ort='Zürich',
                                              versicherungswert=Decimal('1'), iban='CH9300762011623852957')
        self.e1 = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='W1', typ='whg', flaeche_m2=Decimal('60'))
        self.e2 = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='W2', typ='whg', flaeche_m2=Decimal('40'))
        self.m1 = Mieter.objects.create(typ='person', vorname='Anna', nachname='Akonto', email='a@example.ch',
                                        strasse='x', plz='8000', ort='Zürich')
        self.m2 = Mieter.objects.create(typ='person', vorname='Paul', nachname='Pauschal', email='p@example.ch',
                                        strasse='x', plz='8000', ort='Zürich')
        self.v1 = Mietvertrag.objects.create(mieter=self.m1, einheit=self.e1, beginn=date(2024, 1, 1), status='aktiv',
                                             netto_mietzins=Decimal('1000'), nebenkosten=Decimal('10'))
        self.v2 = Mietvertrag.objects.create(mieter=self.m2, einheit=self.e2, beginn=date(2024, 1, 1), status='aktiv',
                                             netto_mietzins=Decimal('1000'), nebenkosten=Decimal('50'),
                                             nk_abrechnungsart='pauschal')
        self.p = AbrechnungsPeriode.objects.create(liegenschaft=self.lg, bezeichnung='NK 2025',
                                                   start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        NebenkostenBeleg.objects.create(periode=self.p, kategorie='hauswart', text='Hauswart',
                                        betrag=Decimal('1000.00'), verteilschluessel='m2', datum=date(2025, 6, 1))
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))
        self.basis = f'/neu/nebenkosten/{self.p.id}/'

    def verbuchen(self):
        r = self.c.post(self.basis + 'verbuchen/')
        self.assertEqual(r.status_code, 302)
        self.p.refresh_from_db()
        self.assertTrue(self.p.abgeschlossen)


class SeitenTests(_Basis):
    def test_jeder_schritt_zeigt_stepper_und_aufgabe(self):
        for teil in SCHRITTE:
            with self.subTest(schritt=teil):
                r = self.c.get(self.basis + teil + '/')
                self.assertEqual(r.status_code, 200)
                html = r.content.decode()
                self.assertIn('class="fw-nkw-leiste"', html)
                self.assertEqual(html.count('<li class="'), 6, 'sechs Schritte im Stepper')
                self.assertIn('aria-current="step"', html)

    def test_offene_periode_oeffnet_den_wizard_beim_aktuellen_schritt(self):
        """Pauschal ohne Fläche-Lücken, Kosten da: Der erste offene Schritt ist «Prüfen»."""
        r = self.c.get(self.basis)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="fw-nkw-leiste"')
        self.assertContains(r, 'Geht die Abrechnung auf')

    def test_schritt_eins_zeigt_die_luecke_der_kachel(self):
        self.e2.flaeche_m2 = None
        self.e2.save()
        r = self.c.get(self.basis + 'periode/')
        self.assertContains(r, 'W2: Fläche fehlt')
        self.assertContains(r, 'name="flaeche_m2"')

    def test_verbuchte_periode_ist_eine_leseansicht(self):
        self.verbuchen()
        r = self.c.get(self.basis)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'class="fw-nkw-leiste"')
        self.assertContains(r, f'/neu/nebenkosten/{self.p.id}/zustellung/')
        # Fehler i: Der Mieter-Link führt auf den Vertrag (vorher `a.v.id` = leer).
        self.assertContains(r, f'href="/neu/vertraege/{self.v1.id}/"')
        self.assertNotContains(r, 'klassischen Ansicht')
        for teil in ('periode', 'kosten', 'verteilung', 'heizung', 'pruefen'):
            self.assertEqual(self.c.get(self.basis + teil + '/').status_code, 302)

    def test_leseansicht_listet_kreditoren_unter_den_positionen(self):
        """Fehler i: Der Belege-Tab zeigte nur manuelle Belege, keine Kreditoren."""
        from finance.booking import konto
        from finance.models import KreditorenRechnung
        KreditorenRechnung.objects.create(lieferant='Strom Werke AG', betrag=Decimal('300.00'), liegenschaft=self.lg,
                                          is_hnk_relevant=True, konto=konto('4130'), status='bezahlt',
                                          datum=date(2025, 3, 1))
        self.verbuchen()
        self.assertContains(self.c.get(self.basis), 'Strom Werke AG')


class PeriodeTests(_Basis):
    def test_neue_periode_ueber_zwoelf_monate_wird_abgewiesen(self):
        from finance.models import AbrechnungsPeriode
        vorher = AbrechnungsPeriode.objects.count()
        r = self.c.post('/neu/nebenkosten/neu/', {'liegenschaft_id': self.lg.id, 'bezeichnung': 'Zu lang',
                                                  'start_datum': '2025-01-01', 'ende_datum': '2026-01-01'})
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, 'höchstens 12 Monate', status_code=400)
        self.assertEqual(AbrechnungsPeriode.objects.count(), vorher)

    def test_heizperiode_genau_zwoelf_monate_geht(self):
        from finance.models import AbrechnungsPeriode
        r = self.c.post('/neu/nebenkosten/neu/', {'liegenschaft_id': self.lg.id, 'bezeichnung': 'HP 25/26',
                                                  'start_datum': '2025-07-01', 'ende_datum': '2026-06-30'})
        p = AbrechnungsPeriode.objects.get(bezeichnung='HP 25/26')
        self.assertRedirects(r, f'/neu/nebenkosten/{p.id}/periode/', fetch_redirect_response=False)

    def test_periode_im_wizard_aendern_prueft_dieselbe_grenze(self):
        r = self.c.post(self.basis + 'periode/', {'aktion': 'periode', 'bezeichnung': 'NK 2025',
                                                  'start_datum': '2025-01-01', 'ende_datum': '2026-01-15'})
        self.assertEqual(r.status_code, 400)
        self.p.refresh_from_db()
        self.assertEqual(self.p.ende_datum, date(2025, 12, 31))

    def test_einstieg_ist_schritt_eins_nicht_mehr_das_ausklappformular(self):
        liste = self.c.get('/neu/nebenkosten/').content.decode()
        self.assertIn('href="/neu/nebenkosten/neu/', liste)
        self.assertNotIn('id="nkform"', liste)
        neu = self.c.get('/neu/nebenkosten/neu/')
        self.assertEqual(neu.status_code, 200)
        self.assertContains(neu, 'name="start_datum"')

    def test_kachel_ergaenzt_flaeche_volumen_und_personen(self):
        r = self.c.post(self.basis + 'periode/', {'aktion': 'einheit', 'einheit_id': self.e2.id,
                                                  'flaeche_m2': "1'040,5", 'volumen_m3': '300',
                                                  f'personen_{self.v2.id}': '3'})
        self.assertEqual(r.status_code, 302)
        self.e2.refresh_from_db()
        self.v2.refresh_from_db()
        self.assertEqual((self.e2.flaeche_m2, self.e2.volumen_m3, self.v2.anzahl_personen),
                         (Decimal('1040.50'), Decimal('300.00'), 3))

    def test_kachel_lehnt_negative_werte_ab(self):
        r = self.c.post(self.basis + 'periode/', {'aktion': 'einheit', 'einheit_id': self.e2.id,
                                                  'flaeche_m2': '-5'})
        self.assertEqual(r.status_code, 400)
        self.e2.refresh_from_db()
        self.assertEqual(self.e2.flaeche_m2, Decimal('40.00'))


class KostenTests(_Basis):
    def test_beleg_erfassen_und_loeschen(self):
        from finance.models import NebenkostenBeleg
        r = self.c.post(self.basis + 'kosten/', {'aktion': 'beleg', 'text': 'Lift Service', 'kategorie': 'lift',
                                                 'verteilschluessel': 'einheit', 'datum': '2025-05-01',
                                                 'betrag': '480.00'})
        self.assertEqual(r.status_code, 302)
        b = NebenkostenBeleg.objects.get(text='Lift Service')
        self.assertEqual((b.periode_id, b.betrag), (self.p.id, Decimal('480.00')))
        self.c.post(self.basis + 'kosten/', {'aktion': 'beleg_loeschen', 'beleg_id': b.id})
        self.assertFalse(NebenkostenBeleg.objects.filter(pk=b.pk).exists())

    def test_beleg_ohne_betrag_bleibt_mit_fehler_am_feld(self):
        r = self.c.post(self.basis + 'kosten/', {'aktion': 'beleg', 'text': 'Ohne', 'kategorie': 'lift',
                                                 'verteilschluessel': 'm2', 'datum': '2025-05-01', 'betrag': ''})
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, 'Bitte einen Betrag über 0 angeben.', status_code=400)

    def test_heizoel_bestand(self):
        self.c.post(self.basis + 'kosten/', {'aktion': 'oel', 'anfangsbestand_liter': '4000',
                                             'anfangsbestand_chf': "3'600.00", 'endbestand_liter': '2500'})
        self.p.refresh_from_db()
        self.assertEqual((self.p.anfangsbestand_liter, self.p.anfangsbestand_chf, self.p.endbestand_liter),
                         (Decimal('4000'), Decimal('3600'), Decimal('2500')))

    def test_kreditorenliste_nutzt_die_abgrenzung_der_engine(self):
        """Fehler c in der Ansicht: Die alte Detailseite filterte nach `datum`. Eine Rechnung vom
        Juli 2024 mit Leistung bis Juni 2025 gehört dazu, eine vom März 2025 mit Leistung 2024 nicht."""
        from finance.booking import konto
        from finance.models import KreditorenRechnung
        KreditorenRechnung.objects.create(lieferant='Jahresvertrag Hauswart', betrag=Decimal('730'), liegenschaft=self.lg,
                                          is_hnk_relevant=True, konto=konto('4120'), status='bezahlt',
                                          datum=date(2024, 7, 5), leistungs_von=date(2024, 7, 1),
                                          leistungs_bis=date(2025, 6, 30))
        KreditorenRechnung.objects.create(lieferant='Nachzügler 2024', betrag=Decimal('100'), liegenschaft=self.lg,
                                          is_hnk_relevant=True, konto=konto('4120'), status='bezahlt',
                                          datum=date(2025, 3, 1), leistungs_von=date(2024, 1, 1),
                                          leistungs_bis=date(2024, 12, 31))
        r = self.c.get(self.basis + 'kosten/')
        self.assertContains(r, 'Jahresvertrag Hauswart')
        self.assertContains(r, 'anteilig 181/365 Tage')
        self.assertNotContains(r, 'Nachzügler 2024')


class VerteilungTests(_Basis):
    def test_segment_setzt_den_schluessel_und_schaltet_die_tabelle_ein(self):
        from core.utils.billing import berechne_abrechnung
        from portfolio.models import LiegenschaftVerteilschluessel
        r = self.c.post(self.basis + 'verteilung/', {'aktion': 'schluessel', 'kostenart': 'hauswartung', 'typ': 'einheit'})
        self.assertEqual(r.status_code, 302)
        s = LiegenschaftVerteilschluessel.objects.get(liegenschaft=self.lg, kostenart='hauswartung')
        self.assertEqual((s.typ, s.gueltig_ab), ('einheit', date(2025, 1, 1)))
        self.lg.refresh_from_db()
        self.assertTrue(self.lg.verteilschluessel_aktiv)
        anteile = {z['einheit']: z['kosten_anteil'] for z in berechne_abrechnung(self.p.id)['abrechnungen']}
        self.assertEqual(anteile, {'W1': Decimal('500.00'), 'W2': Decimal('500.00')})

    def test_frueherer_schluessel_endet_am_vortag(self):
        from portfolio.models import LiegenschaftVerteilschluessel
        alt = LiegenschaftVerteilschluessel.objects.create(liegenschaft=self.lg, kostenart='hauswartung', typ='zimmer',
                                                           gueltig_ab=date(2020, 1, 1))
        self.c.post(self.basis + 'verteilung/', {'aktion': 'schluessel', 'kostenart': 'hauswartung', 'typ': 'm2'})
        alt.refresh_from_db()
        self.assertEqual(alt.gueltig_bis, date(2024, 12, 31))

    def test_ausschluss_am_vertrag(self):
        r = self.c.post(self.basis + 'verteilung/', {'aktion': 'ausschluss', 'kostenart': 'lift',
                                                     'vertrag_id': self.v1.id, 'an': '1'})
        self.assertEqual(r.status_code, 302)
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.ausgeschlossene_kostenarten, ['lift'])
        self.assertEqual(self.v1.ausgeschlossene_kosten, '', 'Der Freitext bleibt unberührt.')

    def test_leerstand_personen_wahl(self):
        self.c.post(self.basis + 'verteilung/', {'aktion': 'leerstand_personen', 'leerstand_personen': 'durchschnitt'})
        self.p.refresh_from_db()
        self.assertEqual(self.p.leerstand_personen, 'durchschnitt')
        self.c.post(self.basis + 'verteilung/', {'aktion': 'leerstand_personen', 'leerstand_personen': 'erfunden'})
        self.p.refresh_from_db()
        self.assertEqual(self.p.leerstand_personen, 'durchschnitt')


class HeizungTests(_Basis):
    def setUp(self):
        super().setUp()
        from portfolio.models import Zaehler
        self.z = Zaehler.objects.create(einheit=self.e1, typ='Wärmezähler', zaehler_nummer='WMZ-1')

    def test_grundkostenanteil_frei_von_null_bis_hundert(self):
        r = self.c.post(self.basis + 'heizung/', {'aktion': 'hkvo', 'hkvo_aktiv': 'on', 'hkvo_grundkosten_prozent': '101'})
        self.assertEqual(r.status_code, 400)
        self.c.post(self.basis + 'heizung/', {'aktion': 'hkvo', 'hkvo_aktiv': 'on', 'hkvo_grundkosten_prozent': '0'})
        self.lg.refresh_from_db()
        self.assertEqual((self.lg.hkvo_aktiv, self.lg.hkvo_grundkosten_prozent), (True, 0))

    def test_raster_speichert_anfang_und_ende(self):
        r = self.c.post(self.basis + 'heizung/', {'aktion': 'staende', 'zaehler_id': self.z.id,
                                                  'anfang_datum': '2025-01-01', 'anfang_wert': '100',
                                                  'ende_datum': '2025-12-31', 'ende_wert': '160'})
        self.assertEqual(r.status_code, 302)
        staende = list(self.z.staende.order_by('datum').values_list('art', 'wert', 'herkunft'))
        self.assertEqual(staende, [('anfang', Decimal('100.000'), 'manuell'), ('ende', Decimal('160.000'), 'manuell')])

    def test_sinkender_stand_wird_abgelehnt(self):
        r = self.c.post(self.basis + 'heizung/', {'aktion': 'staende', 'zaehler_id': self.z.id,
                                                  'anfang_datum': '2025-01-01', 'anfang_wert': '200',
                                                  'ende_datum': '2025-12-31', 'ende_wert': '150'})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.z.staende.exists())

    def test_wechsel_hat_ein_feld_fuer_den_zwischenstand(self):
        self.v1.ende = date(2025, 4, 30)
        self.v1.save()
        r = self.c.get(self.basis + 'heizung/')
        self.assertContains(r, 'name="wechsel_0_wert"')
        self.assertContains(r, 'value="2025-04-30"')


class ImportTests(_Basis):
    def setUp(self):
        super().setUp()
        from portfolio.models import Zaehler, ZaehlerStand
        self.z = Zaehler.objects.create(einheit=self.e1, typ='Wärmezähler', zaehler_nummer='WMZ-1')
        ZaehlerStand.objects.create(zaehler=self.z, datum=date(2025, 1, 1), wert=Decimal('100'))
        self.url = self.basis + 'import/'

    def hochladen(self, text):
        datei = SimpleUploadedFile('staende.csv', text.encode('utf-8'), content_type='text/csv')
        return self.c.post(self.url, {'aktion': 'hochladen', 'datei': datei})

    CSV = ("Geraet;Ablesung;Messwert;Typ\n"
           "WMZ-1;30.04.2025;150,5;zwischen\n"
           "WMZ-1;31.12.2025;210;ende\n"
           "XYZ-9;31.12.2025;10;ende\n"
           "WMZ-1;31.13.2025;300;ende\n"
           "WMZ-1;2025-06-30;90;\n")

    ZUORDNUNG = {'spalte_zaehler': 'Geraet', 'spalte_datum': 'Ablesung', 'spalte_stand': 'Messwert', 'spalte_art': 'Typ'}

    def test_hochladen_zeigt_die_zuordnung(self):
        r = self.hochladen(self.CSV)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="spalte_zaehler"')
        self.assertContains(r, '<option value="Geraet" selected>', html=False)

    def test_vorschau_meldet_fehlerhafte_zeilen_einzeln(self):
        r = self.c.post(self.url, {'aktion': 'vorschau', 'inhalt': self.CSV, **self.ZUORDNUNG})
        self.assertEqual(r.status_code, 200)
        zeilen = {z['nr']: z for z in r.context['zeilen']}
        self.assertEqual(zeilen[2]['fehler'], '')
        self.assertEqual(zeilen[3]['fehler'], '')
        self.assertIn('XYZ-9', zeilen[4]['fehler'])
        self.assertIn('nicht lesbar', zeilen[5]['fehler'])
        self.assertIn('liegt unter', zeilen[6]['fehler'])          # 90 nach 150.5 am 30.04.
        self.assertEqual(r.context['n_ok'], 2)

    def test_uebernehmen_speichert_staende_und_zuordnung(self):
        r = self.c.post(self.url, {'aktion': 'uebernehmen', 'inhalt': self.CSV, **self.ZUORDNUNG})
        self.assertEqual(r.status_code, 302)
        neu = list(self.z.staende.filter(herkunft='import').order_by('datum').values_list('datum', 'wert', 'art'))
        self.assertEqual(neu, [(date(2025, 4, 30), Decimal('150.500'), 'zwischen'),
                               (date(2025, 12, 31), Decimal('210.000'), 'ende')])
        self.lg.refresh_from_db()
        self.assertEqual(self.lg.zaehler_import_zuordnung,
                         {'zaehler': 'Geraet', 'datum': 'Ablesung', 'stand': 'Messwert', 'art': 'Typ'})
        # Zweiter Import: dieselben Zeilen sind «schon erfasst», die Zuordnung wird vorgeschlagen.
        r = self.hochladen(self.CSV)
        self.assertEqual(r.context['zuordnung'], {'zaehler': 'Geraet', 'datum': 'Ablesung', 'stand': 'Messwert', 'art': 'Typ'})
        r = self.c.post(self.url, {'aktion': 'vorschau', 'inhalt': self.CSV, **self.ZUORDNUNG})
        self.assertEqual((r.context['n_ok'], r.context['n_doppelt']), (0, 2))

    def test_pflichtspalte_fehlt(self):
        r = self.c.post(self.url, {'aktion': 'vorschau', 'inhalt': self.CSV, 'spalte_zaehler': 'Geraet',
                                   'spalte_datum': 'Ablesung'})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(r.context['zeilen'])

    def test_datei_ohne_daten(self):
        r = self.hochladen('Nur;Kopf\n')
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, 'mindestens eine Datenzeile', status_code=400)


class RechteTests(_Basis):
    def test_lesend_darf_ansehen_aber_nicht_schreiben(self):
        from finance.models import NebenkostenBeleg
        c = Client(); c.force_login(_team_user('Lesend'))
        self.assertEqual(c.get(self.basis + 'kosten/').status_code, 200)
        r = c.post(self.basis + 'kosten/', {'aktion': 'beleg', 'text': 'X', 'kategorie': 'lift',
                                            'verteilschluessel': 'm2', 'datum': '2025-05-01', 'betrag': '1'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(NebenkostenBeleg.objects.filter(text='X').exists())

    def test_verbuchte_periode_laesst_sich_nicht_mehr_aendern(self):
        from finance.models import NebenkostenBeleg
        self.verbuchen()
        b = NebenkostenBeleg.objects.get(periode=self.p)
        self.c.post(self.basis + 'kosten/', {'aktion': 'beleg_loeschen', 'beleg_id': b.id})
        self.assertTrue(NebenkostenBeleg.objects.filter(pk=b.pk).exists())
        self.c.post(self.basis + 'periode/', {'aktion': 'einheit', 'einheit_id': self.e1.id, 'flaeche_m2': '1'})
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.flaeche_m2, Decimal('60.00'))


class VersandTests(_Basis):
    def test_g_versand_vor_dem_verbuchen_wird_abgewiesen(self):
        from rentals.models import Dokument
        r = self.c.post(self.basis + 'versand/')
        self.assertRedirects(r, self.basis + 'abschluss/', fetch_redirect_response=False)
        self.assertFalse(Dokument.objects.filter(bezeichnung__icontains='Nebenkostenabrechnung').exists())

    def test_f_pauschal_mieter_bekommt_kein_pdf(self):
        from rentals.models import Dokument
        self.verbuchen()
        r = self.c.post(self.basis + 'versand/')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(Dokument.objects.filter(vertrag=self.v1, bezeichnung__icontains='Nebenkostenabrechnung').exists())
        self.assertFalse(Dokument.objects.filter(vertrag=self.v2, bezeichnung__icontains='Nebenkostenabrechnung').exists())
        self.assertNotIn('Pauschal', _pdf_text(r.content))

    def test_f_pauschal_mieter_bekommt_keine_mail(self):
        from django.core import mail
        self.verbuchen()
        mail.outbox = []
        self.c.post(self.basis + 'mail/')
        self.assertEqual([m.to[0] for m in mail.outbox], ['a@example.ch'])

    def test_h_alte_pdf_route_druckt_den_eingefrorenen_stand(self):
        """Nach dem Verbuchen ändert sich der Beleg von 1000 auf 9000. Die alte Route
        rechnete live und druckte 9000 × 60 % = 5400.00; eingefroren sind 600.00."""
        from finance.models import NebenkostenBeleg
        self.verbuchen()
        NebenkostenBeleg.objects.filter(periode=self.p).update(betrag=Decimal('9000.00'))
        r = self.c.get(f'/abrechnung/{self.p.id}/pdf/')
        self.assertEqual(r.status_code, 200)
        text = _pdf_text(r.content)
        self.assertIn('600.00', text)
        self.assertNotIn('5400.00', text)


class AkontoE1Tests(_Basis):
    def test_akonto_route_ueberschreibt_nichts_und_leitet_um(self):
        r = self.c.post(self.basis + 'akonto/', {'vertrag_id': [str(self.v1.id)], f'akonto_{self.v1.id}': '333'})
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.nebenkosten, Decimal('10.00'))
        self.assertRedirects(r, f'/neu/mietzins/{self.v1.id}/anpassung/?nk_periode={self.p.id}&nk=333',
                             fetch_redirect_response=False)

    def test_vorschlag_in_pruefen_zeigt_auf_die_mietzinsanpassung(self):
        """W1 trägt 600.00, Akonto 12 × 10 = 120.00: Bedarf 50/Mt. → Vorschlag 50."""
        r = self.c.get(self.basis + 'pruefen/')
        self.assertContains(r, f'/neu/mietzins/{self.v1.id}/anpassung/?nk=50&amp;nk_periode={self.p.id}')
        self.assertNotContains(r, f'action="/neu/nebenkosten/{self.p.id}/akonto/"')

    def test_ausgezogener_mieter_bekommt_keinen_vorschlag(self):
        self.v1.ende = date(2025, 6, 30)
        self.v1.save()
        r = self.c.get(self.basis + 'pruefen/')
        self.assertNotContains(r, f'/neu/mietzins/{self.v1.id}/anpassung/')

    def test_entwurf_traegt_das_neue_akonto(self):
        from rentals.models import MietzinsAnpassung
        r = self.c.post(f'/neu/mietzins/{self.v1.id}/anpassung/', {
            'aktion': 'entwurf', 'neu_netto': '1000', 'neu_nk': '50', 'wirksam_ab': '2027-04-01'})
        self.assertEqual(r.status_code, 302)
        anp = MietzinsAnpassung.objects.get(vertrag=self.v1)
        self.assertEqual((anp.alte_nebenkosten, anp.neue_nebenkosten), (Decimal('10.00'), Decimal('50.00')))

    def test_akonto_erhoehung_ist_eine_erhoehung_und_wirkt_ab_termin(self):
        """Netto gleich, Akonto 10 → 50: Für Frist und Anfechtung eine Erhöhung (Art. 269d OR);
        nach dem Versand gilt das neue Akonto ab dem Termin, vorher das alte."""
        from core.services import mietzinsanpassung as ablauf
        from rentals.models import MietzinsAnpassung
        anp = MietzinsAnpassung.objects.create(
            vertrag=self.v1, wirksam_ab=date(2026, 4, 1), neuer_netto_mietzins=Decimal('1000'),
            alter_netto_mietzins=Decimal('1000'), alte_nebenkosten=Decimal('10'), neue_nebenkosten=Decimal('50'),
            status=MietzinsAnpassung.STATUS_VERSANDT, versand_am=date(2025, 11, 1))
        self.assertTrue(ablauf.ist_erhoehung(anp))
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.effektive_nebenkosten(date(2026, 3, 31)), Decimal('10.00'))
        self.assertEqual(self.v1.effektive_nebenkosten(date(2026, 4, 1)), Decimal('50.00'))

    def test_mietzinsanpassung_ist_mit_dem_neuen_akonto_vorbelegt(self):
        r = self.c.get(f'/neu/mietzins/{self.v1.id}/anpassung/?nk=50&nk_periode={self.p.id}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="neu_nk"')
        self.assertContains(r, 'value="50"')


class IsolationTests(TestCase):
    """Fremde Periode, fremder Zähler, fremder Import: 404, und nichts ändert sich."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        from core.tenancy import organisation_kontext
        from portfolio.models import Zaehler
        with organisation_kontext(cls.b.organisation):
            cls.zaehler_b = Zaehler.objects.create(einheit=cls.b.einheit, typ='Wärmezähler', zaehler_nummer='WMZ-B')
        with organisation_kontext(cls.a.organisation):
            cls.zaehler_a = Zaehler.objects.create(einheit=cls.a.einheit, typ='Wärmezähler', zaehler_nummer='WMZ-A')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.a.benutzer)

    def test_fremde_periode_gibt_404_in_jedem_schritt(self):
        for teil in SCHRITTE + ('import',):
            with self.subTest(schritt=teil):
                self.assertEqual(self.client.get(f'/neu/nebenkosten/{self.b.periode.id}/{teil}/').status_code, 404)
                self.assertEqual(self.client.post(f'/neu/nebenkosten/{self.b.periode.id}/{teil}/',
                                                  {'aktion': 'beleg'}).status_code, 404)

    def test_fremder_zaehler_gibt_404(self):
        from portfolio.models import ZaehlerStand
        r = self.client.post(f'/neu/nebenkosten/{self.a.periode.id}/heizung/', {
            'aktion': 'staende', 'zaehler_id': self.zaehler_b.id,
            'anfang_datum': '2024-01-01', 'anfang_wert': '1'})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(ZaehlerStand.alle_organisationen.filter(zaehler_id=self.zaehler_b.id).exists())

    def test_fremder_import_gibt_404(self):
        datei = SimpleUploadedFile('s.csv', b'Zaehler;Datum;Stand\nWMZ-B;31.12.2024;5\n', content_type='text/csv')
        r = self.client.post(f'/neu/nebenkosten/{self.b.periode.id}/import/', {'aktion': 'hochladen', 'datei': datei})
        self.assertEqual(r.status_code, 404)

    def test_import_findet_keinen_fremden_zaehler(self):
        """Dieselbe Nummer bei B ist für A kein Zähler — die Zeile wird abgelehnt, nichts geschrieben."""
        from portfolio.models import ZaehlerStand
        inhalt = 'Zaehler;Datum;Stand\nWMZ-B;31.12.2024;5\n'
        r = self.client.post(f'/neu/nebenkosten/{self.a.periode.id}/import/', {
            'aktion': 'uebernehmen', 'inhalt': inhalt,
            'spalte_zaehler': 'Zaehler', 'spalte_datum': 'Datum', 'spalte_stand': 'Stand'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ZaehlerStand.alle_organisationen.filter(zaehler_id=self.zaehler_b.id).exists())

    def test_fremde_einheit_und_fremder_vertrag_geben_404(self):
        a = f'/neu/nebenkosten/{self.a.periode.id}/'
        self.assertEqual(self.client.post(a + 'periode/', {'aktion': 'einheit', 'einheit_id': self.b.einheit.id,
                                                           'flaeche_m2': '1'}).status_code, 404)
        self.assertEqual(self.client.post(a + 'verteilung/', {'aktion': 'ausschluss', 'kostenart': 'lift',
                                                              'vertrag_id': self.b.vertrag.id, 'an': '1'}).status_code, 404)
