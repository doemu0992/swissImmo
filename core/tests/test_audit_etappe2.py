"""Etappe 2 aus docs/AUDIT-SAAS-NIVEAU.md: Formulare, die Fehler zeigen.

Pilot ist die Liegenschaft. Vorher galt: Eine unlesbare Zahl wurde still als
leer gespeichert, eine fremde Betreuungsperson warf per Umleitung alle übrigen
Eingaben weg. Jetzt: Status 400, Meldung am Feld, Eingaben bleiben stehen,
nichts ist gespeichert.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, Client

from portfolio.models import Liegenschaft

from ._helfer import _team_user, _basis_objekte


GUELTIGE_IBAN = 'CH93 0076 2011 6238 5295 7'


# Der GWR-Abgleich fragt beim Bund nach (api3.geo.admin.ch). Ein Test darf das
# nicht — er haengt sonst am Netz und schickt Adressen nach draussen.
@patch('portfolio.services.sync_liegenschaft_with_gwr', return_value={})
class LiegenschaftFormular(TestCase):

    def setUp(self):
        self.lg, _e, _m, _v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())
        self.pfad = f'/neu/liegenschaften/{self.lg.id}/bearbeiten/'

    def _daten(self, **ueber):
        daten = {'strasse': 'Neue Strasse 5', 'plz': '8001', 'ort': 'Zürich', 'kanton': 'ZH',
                 'hkvo_grundkosten_prozent': '40'}
        daten.update(ueber)
        return daten

    def _fehler_am_feld(self, antwort, feld):
        body = antwort.content.decode()
        self.assertIn(f'id="id_{feld}_fehler"', body)
        self.assertIn(f'aria-describedby="id_{feld}_fehler"', body)
        return body

    def test_unlesbares_baujahr_wird_nicht_still_leer_gespeichert(self, _gwr):
        self.lg.baujahr = 1965
        self.lg.save()
        r = self.c.post(self.pfad, self._daten(baujahr='ca. 1970'))
        self.assertEqual(r.status_code, 400)
        body = self._fehler_am_feld(r, 'baujahr')
        # Die Eingabe steht noch da — auch die, die sich nicht speichern liess.
        self.assertIn('value="ca. 1970"', body)
        self.assertIn('value="Neue Strasse 5"', body)
        self.lg.refresh_from_db()
        self.assertEqual(self.lg.baujahr, 1965)
        self.assertEqual(self.lg.strasse, 'Teststrasse 1')

    def test_hkvo_anteil_ueber_100_prozent(self, _gwr):
        """Das Modell kennt keine Grenze; bisher hielt nur `max` im Browser."""
        r = self.c.post(self.pfad, self._daten(hkvo_aktiv='on', hkvo_grundkosten_prozent='140'))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'hkvo_grundkosten_prozent')

    def test_baujahr_tippfehler(self, _gwr):
        r = self.c.post(self.pfad, self._daten(baujahr='198'))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'baujahr')

    def test_keine_zahlenfelder_die_eingaben_verwerfen(self, _gwr):
        """`type="number"` verwirft im Browser jede Nicht-Zahl — nach einem
        Fehler stünde dort ein leeres Feld statt der Eingabe. Gemessen mit
        Chromium bei 390 px, bevor dieser Test entstand."""
        body = self.c.post(self.pfad, self._daten(baujahr='ca. 1970')).content.decode()
        self.assertNotIn('type="number"', body[body.index('<form method="post" class="max-w-3xl'):])
        self.assertIn('inputmode="numeric"', body)

    def test_unlesbarer_betrag_steht_unveraendert_im_feld(self, _gwr):
        """Die Normalisierung («1'250'000» → 1250000) darf die Roheingabe
        nicht umschreiben — sonst stünde nach dem Fehler «ca.2Mio» im Feld."""
        r = self.c.post(self.pfad, self._daten(verkehrswert='ca. 2 Mio'))
        self.assertEqual(r.status_code, 400)
        body = self._fehler_am_feld(r, 'verkehrswert')
        self.assertIn('value="ca. 2 Mio"', body)

    def test_unbekannte_heizart_ist_ein_fehler(self, _gwr):
        r = self.c.post(self.pfad, self._daten(heizsystem='kohleofen-xl'))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'heizsystem')

    def test_ungueltige_iban(self, _gwr):
        r = self.c.post(self.pfad, self._daten(iban='CH93 0076 2011 6238 5295 8'))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'iban')

    def test_plz_muss_vierstellig_sein(self, _gwr):
        r = self.c.post(self.pfad, self._daten(plz='80011'))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'plz')

    def test_pflichtfeld_leer(self, _gwr):
        r = self.c.post(self.pfad, self._daten(strasse=''))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'strasse')
        self.assertIn('role="alert"', r.content.decode())

    def test_fremde_betreuung_behaelt_die_uebrigen_eingaben(self, _gwr):
        """Vorher: Umleitung — und «Neue Strasse 5» war weg."""
        r = self.c.post(self.pfad, self._daten(betreut_von='999999'))
        self.assertEqual(r.status_code, 400)
        body = self._fehler_am_feld(r, 'betreut_von')
        self.assertIn('value="Neue Strasse 5"', body)
        self.lg.refresh_from_db()
        self.assertIsNone(self.lg.betreut_von_id)

    def test_unbekannter_eigentuemer_wird_nicht_still_geloescht(self, _gwr):
        r = self.c.post(self.pfad, self._daten(eigentuemer_id='999999'))
        self.assertEqual(r.status_code, 400)
        self._fehler_am_feld(r, 'eigentuemer_id')

    def test_gueltige_eingaben_werden_gespeichert(self, _gwr):
        r = self.c.post(self.pfad, self._daten(
            kanton='zh', verkehrswert="CHF 1'250'000.50", iban=GUELTIGE_IBAN,
            baujahr='1988', hkvo_grundkosten_prozent='', geak_klasse='c'))
        self.assertEqual(r.status_code, 302, r.content.decode()[:300])
        self.lg.refresh_from_db()
        self.assertEqual(self.lg.strasse, 'Neue Strasse 5')
        self.assertEqual(self.lg.kanton, 'ZH')
        self.assertEqual(self.lg.verkehrswert, Decimal('1250000.50'))
        self.assertEqual(self.lg.baujahr, 1988)
        self.assertEqual(self.lg.hkvo_grundkosten_prozent, 40)
        self.assertEqual(self.lg.geak_klasse, 'C')
        self.assertEqual(self.lg.iban, GUELTIGE_IBAN)
        self.assertEqual(self.lg.egid, '')

    def test_neu_anlegen_und_fehlerfall_legt_nichts_an(self, _gwr):
        vorher = Liegenschaft.objects.count()
        r = self.c.post('/neu/liegenschaften/neu/', self._daten(plz='x', gwr_import=''))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Liegenschaft.objects.count(), vorher)
        r = self.c.post('/neu/liegenschaften/neu/', {**self._daten()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Liegenschaft.objects.count(), vorher + 1)

    def test_betrag_ohne_tausendertrennzeichen_im_feld(self, _gwr):
        """Im Feld steht die Zahl so, wie sie wieder gespeichert werden kann."""
        self.lg.verkehrswert = Decimal('1250000.00')
        self.lg.save()
        body = self.c.get(self.pfad).content.decode()
        self.assertIn('value="1250000.00"', body)


class ObjektFormular(TestCase):
    """Dasselbe Muster an der Objektmaske."""

    def setUp(self):
        self.lg, self.e, _m, _v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())
        self.pfad = f'/neu/objekte/{self.e.id}/bearbeiten/'

    def _daten(self, **ueber):
        daten = {'liegenschaft_id': str(self.lg.id), 'bezeichnung': '4.5 Zi OG', 'typ': 'whg'}
        daten.update(ueber)
        return daten

    def test_unbekannter_typ(self):
        """Vorher übernahm `typ` jeden beliebigen Text."""
        r = self.c.post(self.pfad, self._daten(typ='schloss'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('id="id_typ_fehler"', r.content.decode())
        self.e.refresh_from_db()
        self.assertEqual(self.e.typ, 'whg')

    def test_unlesbare_flaeche_bleibt_stehen(self):
        r = self.c.post(self.pfad, self._daten(flaeche_m2='etwa 80'))
        self.assertEqual(r.status_code, 400)
        body = r.content.decode()
        self.assertIn('id="id_flaeche_m2_fehler"', body)
        self.assertIn('value="etwa 80"', body)
        self.assertIn('value="4.5 Zi OG"', body)

    def test_fremde_liegenschaft_ist_ein_feldfehler_statt_404(self):
        r = self.c.post(self.pfad, self._daten(liegenschaft_id='999999'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('id="id_liegenschaft_id_fehler"', r.content.decode())

    def test_leere_wertquote_und_kaution_bleiben_unveraendert(self):
        self.e.wertquote = Decimal('55.50')
        self.e.standard_kautionsmonate = 2
        self.e.save()
        r = self.c.post(self.pfad, self._daten(wertquote='', standard_kautionsmonate='', zimmer="4,5"))
        self.assertEqual(r.status_code, 302)
        self.e.refresh_from_db()
        self.assertEqual(self.e.wertquote, Decimal('55.50'))
        self.assertEqual(self.e.standard_kautionsmonate, 2)
        self.assertEqual(self.e.zimmer, Decimal('4.5'))
        self.assertEqual(self.e.bezeichnung, '4.5 Zi OG')

    def test_ungueltiges_datum_des_anfangsmietzinses_wird_nicht_heute(self):
        """Vorher wurde ein unlesbares «Gültig ab» still durch heute ersetzt —
        ein Datum, das in die Sollstellung eingeht."""
        from portfolio.models import Einheit, Sollmietzins
        vorher = Einheit.objects.count()
        r = self.c.post('/neu/objekte/neu/', self._daten(
            nettomiete_aktuell='1500', soll_gueltig_ab='31.02.2026'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('id="id_soll_gueltig_ab_fehler"', r.content.decode())
        self.assertEqual(Einheit.objects.count(), vorher)
        r = self.c.post('/neu/objekte/neu/', self._daten(
            nettomiete_aktuell="1'500", nebenkosten_aktuell='200', soll_gueltig_ab='2026-04-01'))
        self.assertEqual(r.status_code, 302)
        neu = Einheit.objects.exclude(pk=self.e.pk).latest('pk')
        soll = Sollmietzins.objects.get(einheit=neu)
        self.assertEqual((soll.gueltig_ab.isoformat(), soll.netto_mietzins, soll.nebenkosten),
                         ('2026-04-01', Decimal('1500.00'), Decimal('200.00')))

    def test_negative_kautionsmonate(self):
        r = self.c.post(self.pfad, self._daten(standard_kautionsmonate='-1'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('id="id_standard_kautionsmonate_fehler"', r.content.decode())


class KreditorFormular(TestCase):
    """Erfassen und Bearbeiten in der Kreditorenliste."""

    def setUp(self):
        self.lg, _e, _m, _v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def _daten(self, **ueber):
        daten = {'lieferant': 'Muster Sanitär AG', 'betrag': "1'234.50", 'mwst_satz': '8.1',
                 'datum': '2026-09-01', 'liegenschaft_id': str(self.lg.id)}
        daten.update(ueber)
        return daten

    def _anzahl(self):
        from finance.models import KreditorenRechnung
        return KreditorenRechnung.objects.count()

    def test_unlesbares_datum_ist_kein_serverfehler_mehr(self):
        """Vorher: `date.fromisoformat` ungeschützt → 500."""
        vorher = self._anzahl()
        r = self.c.post('/neu/kreditoren/neu/', self._daten(datum='31.02.2026'))
        self.assertEqual(r.status_code, 400)
        body = r.content.decode()
        self.assertIn('id="kr-datum_fehler"', body)
        self.assertIn('value="Muster Sanitär AG"', body)
        self.assertEqual(self._anzahl(), vorher)

    def test_unlesbarer_mwst_satz_wird_nicht_null(self):
        """Vorher still 0 % — und damit kein Vorsteuerabzug bei der Freigabe."""
        vorher = self._anzahl()
        r = self.c.post('/neu/kreditoren/neu/', self._daten(mwst_satz='acht'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('id="kr-mwst_fehler"', r.content.decode())
        self.assertEqual(self._anzahl(), vorher)

    def test_mwst_mit_zwei_nachkommastellen_wird_gekuerzt_nicht_abgelehnt(self):
        from finance.models import KreditorenRechnung
        r = self.c.post('/neu/kreditoren/neu/', self._daten(mwst_satz='8.10', iban='CH93 0076 2011 6238 5295 7'))
        self.assertEqual(r.status_code, 302)
        k = KreditorenRechnung.objects.latest('pk')
        self.assertEqual((k.mwst_satz, k.betrag, k.iban),
                         (Decimal('8.1'), Decimal('1234.50'), 'CH9300762011623852957'))

    def test_ungueltige_iban_und_leistungszeitraum(self):
        r = self.c.post('/neu/kreditoren/neu/', self._daten(
            iban='CH93 0076 2011 6238 5295 8', leistungs_von='2026-06-30', leistungs_bis='2026-01-01'))
        self.assertEqual(r.status_code, 400)
        body = r.content.decode()
        self.assertIn('id="kr-iban_fehler"', body)
        self.assertIn('id="kr-leist-bis_fehler"', body)

    def test_bearbeiten_zeigt_fehler_an_der_zeile_auch_ausserhalb_der_seite(self):
        """Die Liste zeigt 50 je Seite; nach einem POST gibt es keinen
        Seitenparameter. Die Zeile mit dem Fehler muss trotzdem sichtbar sein."""
        from finance.models import KreditorenRechnung
        for i in range(55):
            KreditorenRechnung.objects.create(lieferant=f'Füller {i}', betrag=Decimal('10'), status='neu')
        k = KreditorenRechnung.objects.order_by('pk').first()
        k.lieferant, k.betrag = 'Alter Lieferant', Decimal('50.00')
        k.save()
        r = self.c.post(f'/neu/kreditoren/{k.id}/bearbeiten/', {
            'lieferant': 'Neuer Lieferant', 'betrag': 'fünfzig'})
        self.assertEqual(r.status_code, 400)
        body = r.content.decode()
        self.assertIn(f'id="kc-betrag-{k.id}_fehler"', body)
        self.assertIn('value="Neuer Lieferant"', body)
        self.assertIn(f'<tr id="kedit-{k.id}" class="fw-markenflaeche">', body)
        k.refresh_from_db()
        self.assertEqual((k.lieferant, k.betrag), ('Alter Lieferant', Decimal('50.00')))

    def test_bearbeiten_ohne_betrag_bleibt_erlaubt(self):
        """Gescannte Belege kommen oft ohne erkannten Betrag — leer ist beim
        Bearbeiten kein Fehler, nur UNLESBAR ist einer."""
        from finance.models import KreditorenRechnung
        k = KreditorenRechnung.objects.create(lieferant='Scan', betrag=None, status='neu')
        r = self.c.post(f'/neu/kreditoren/{k.id}/bearbeiten/', {'lieferant': 'Scan AG', 'betrag': ''})
        self.assertEqual(r.status_code, 302)
        k.refresh_from_db()
        self.assertEqual(k.lieferant, 'Scan AG')


class PersonFormular(TestCase):
    """Nachtrag Person: Vorher wurden unlesbare Daten still leer, unlesbare
    Personenzahlen still 0, und die Zahler-IBAN blieb ungeprüft."""

    def setUp(self):
        from crm.models import Mieter
        from ._helfer import _test_organisation
        from datetime import date
        self.m = Mieter.objects.create(
            typ='person', vorname='Eva', nachname='Muster', organisation=_test_organisation(),
            bewilligung_gueltig_bis=date(2027, 3, 31), haushalt_erwachsene=2)
        self.c = Client()
        self.c.force_login(_team_user())
        self.pfad = f'/neu/personen/{self.m.id}/bearbeiten/'

    def _daten(self, **ueber):
        daten = {'typ': 'person', 'vorname': 'Eva', 'nachname': 'Muster',
                 'bewilligung_gueltig_bis': '2027-03-31', 'haushalt_erwachsene': '2'}
        daten.update(ueber)
        return daten

    def _fehler_am_feld(self, r, feld):
        self.assertEqual(r.status_code, 400)
        body = r.content.decode()
        self.assertIn(f'id="p-{feld}_fehler"', body)
        self.assertIn(f'aria-describedby="p-{feld}_fehler"', body)
        return body

    def test_unlesbares_bewilligungsende_wird_nicht_still_leer(self):
        """Eine ablaufende Bewilligung fiele sonst aus jeder Frist heraus."""
        from datetime import date
        r = self.c.post(self.pfad, self._daten(bewilligung_gueltig_bis='31.02.2027'))
        self._fehler_am_feld(r, 'bewilligung_gueltig_bis')
        self.m.refresh_from_db()
        self.assertEqual(self.m.bewilligung_gueltig_bis, date(2027, 3, 31))

    def test_geburtsdatum_in_der_zukunft(self):
        r = self.c.post(self.pfad, self._daten(geburtsdatum='2090-01-01'))
        body = self._fehler_am_feld(r, 'geburtsdatum')
        # Die Eingabe steht noch im Feld.
        self.assertIn('value="2090-01-01"', body)

    def test_unlesbare_personenzahl_wird_nicht_null(self):
        r = self.c.post(self.pfad, self._daten(haushalt_erwachsene='zwei'))
        body = self._fehler_am_feld(r, 'haushalt_erwachsene')
        self.assertIn('value="zwei"', body)
        self.m.refresh_from_db()
        self.assertEqual(self.m.haushalt_erwachsene, 2)

    def test_keine_zahlenfelder_die_eingaben_verwerfen(self):
        body = self.c.get(self.pfad).content.decode()
        self.assertNotIn('type="number"', body[body.index('<form method="post" class="max-w-3xl'):])

    def test_personenzahl_mit_tippfehler(self):
        self._fehler_am_feld(self.c.post(self.pfad, self._daten(haushalt_kinder='40')), 'haushalt_kinder')

    def test_zahler_iban_wird_geprueft(self):
        r = self.c.post(self.pfad, self._daten(zahler_iban='CH00 1234'))
        self._fehler_am_feld(r, 'zahler_iban')
        self.m.refresh_from_db()
        self.assertEqual(self.m.zahler_iban, '')

    def test_ebill_adresse_wird_geprueft(self):
        self._fehler_am_feld(self.c.post(self.pfad, self._daten(ebill_email='kein-at')), 'ebill_email')

    def test_schweizer_plz_hat_vier_ziffern(self):
        self._fehler_am_feld(self.c.post(self.pfad, self._daten(plz='80001')), 'plz')

    def test_auslaendische_plz_bleibt_frei(self):
        r = self.c.post(self.pfad, self._daten(plz='10115', ort='Berlin', land='Deutschland'))
        self.assertEqual(r.status_code, 302)
        self.m.refresh_from_db()
        self.assertEqual(self.m.plz, '10115')

    def test_zu_langer_text_ist_kein_serverfehler(self):
        """SQLite schneidet nichts ab, PostgreSQL wirft — im Betrieb ein 500
        mit verlorenen Eingaben."""
        r = self.c.post(self.pfad, self._daten(vorname='E' * 101))
        self._fehler_am_feld(r, 'vorname')

    def test_zusammenfassung_zaehlt_die_fehler(self):
        r = self.c.post(self.pfad, self._daten(plz='1', ebill_email='x'))
        body = self._fehler_am_feld(r, 'plz')
        self.assertIn('class="fw-formfehler"', body)
        self.assertEqual(r.context['anzahl_fehler'], 2)

    def test_gueltige_eingaben_werden_gespeichert(self):
        from datetime import date
        r = self.c.post(self.pfad, self._daten(geburtsdatum='1980-05-17', haushalt_kinder='3',
                                               zahler_iban='CH9300762011623852957'))
        self.assertEqual(r.status_code, 302)
        self.m.refresh_from_db()
        self.assertEqual(self.m.geburtsdatum, date(1980, 5, 17))
        self.assertEqual(self.m.haushalt_kinder, 3)
        self.assertEqual(self.m.zahler_iban, 'CH93 0076 2011 6238 5295 7')

    def test_bearbeiten_zeigt_die_gespeicherten_werte(self):
        body = self.c.get(self.pfad).content.decode()
        self.assertIn('value="2027-03-31"', body)
        self.assertIn('name="haushalt_erwachsene" value="2"', body)


class VertragBearbeiten(TestCase):
    """Nachtrag Mietverhältnis: Vorher wurde ein unlesbares Vertragsende still
    leer (aus befristet wurde unbefristet), eine unlesbare Frist oder
    Personenzahl blieb still beim alten Wert, und im Entwurf wurde ein
    unlesbarer Nettomietzins still CHF 0."""

    def setUp(self):
        from datetime import date
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.v.ende = date(2030, 12, 31)
        self.v.ist_befristet = True
        self.v.kuendigungsfrist_monate = 3
        self.v.anzahl_personen = 2
        self.v.save()
        self.c = Client()
        self.c.force_login(_team_user())
        self.pfad = f'/neu/vertraege/{self.v.id}/bearbeiten/'

    def _daten(self, **ueber):
        daten = {'ende': '2030-12-31', 'erstmals_kuendbar': '', 'kuendigungsfrist': '3',
                 'anzahl_personen': '2', 'kuendigungstermine': ''}
        daten.update(ueber)
        return daten

    def _fehler_am_feld(self, r, feld):
        self.assertEqual(r.status_code, 400)
        body = r.content.decode()
        self.assertIn(f'id="v-{feld}_fehler"', body)
        self.assertIn(f'aria-describedby="v-{feld}_fehler"', body)
        return body

    def test_unlesbares_ende_macht_den_vertrag_nicht_unbefristet(self):
        from datetime import date
        r = self.c.post(self.pfad, self._daten(ende='31.12.2030x'))
        self._fehler_am_feld(r, 'ende')
        self.v.refresh_from_db()
        self.assertEqual(self.v.ende, date(2030, 12, 31))
        self.assertTrue(self.v.ist_befristet)

    def test_ende_vor_beginn(self):
        self._fehler_am_feld(self.c.post(self.pfad, self._daten(ende='2020-01-01')), 'ende')

    def test_unlesbare_frist_wird_gemeldet_statt_ignoriert(self):
        r = self.c.post(self.pfad, self._daten(kuendigungsfrist='drei'))
        body = self._fehler_am_feld(r, 'kuendigungsfrist')
        self.assertIn('value="drei"', body)

    def test_unlesbare_personenzahl_wird_gemeldet(self):
        self._fehler_am_feld(self.c.post(self.pfad, self._daten(anzahl_personen='zwei')), 'anzahl_personen')
        self.v.refresh_from_db()
        self.assertEqual(self.v.anzahl_personen, 2)

    def test_index_weitergabe_null_wird_gemeldet(self):
        self._fehler_am_feld(self.c.post(self.pfad, self._daten(index_weitergabe_prozent='0')),
                             'index_weitergabe_prozent')

    def test_freitext_bleibt_nach_fehler_stehen(self):
        body = self._fehler_am_feld(
            self.c.post(self.pfad, self._daten(ende='x', nebenraeume='Kellerabteil 7')), 'ende')
        self.assertIn('Kellerabteil 7', body)

    def test_keine_zahlenfelder_die_eingaben_verwerfen(self):
        body = self.c.get(self.pfad).content.decode()
        self.assertNotIn('type="number"', body[body.index('<form method="post" class="max-w-3xl'):])

    def test_gueltige_aenderung_wird_gespeichert(self):
        r = self.c.post(self.pfad, self._daten(kuendigungsfrist='6', nebenraeume='Estrich'))
        self.assertEqual(r.status_code, 302)
        self.v.refresh_from_db()
        self.assertEqual(self.v.kuendigungsfrist_monate, 6)
        self.assertEqual(self.v.nebenraeume, 'Estrich')

    def test_entwurf_unlesbarer_mietzins_wird_nicht_null(self):
        self.v.status = 'entwurf'
        self.v.save()
        r = self.c.post(self.pfad, self._daten(netto_mietzins='ca. 1800', nebenkosten='200',
                                               beginn='2024-01-01'))
        body = self._fehler_am_feld(r, 'netto_mietzins')
        self.assertIn('value="ca. 1800"', body)
        self.v.refresh_from_db()
        self.assertEqual(self.v.netto_mietzins, Decimal('1500'))

    def test_entwurf_zu_grosser_betrag_ist_kein_serverfehler(self):
        """Das Modell fasst acht Stellen; PostgreSQL würfe sonst."""
        self.v.status = 'entwurf'
        self.v.save()
        self._fehler_am_feld(self.c.post(self.pfad, self._daten(netto_mietzins='12345678',
                                                                beginn='2024-01-01')), 'netto_mietzins')

    def test_gesperrter_mietzins_wird_nicht_angenommen(self):
        """Aktiver Vertrag: Miete bleibt gesperrt, auch wenn sie mitgeschickt wird."""
        r = self.c.post(self.pfad, self._daten(netto_mietzins='9999'))
        self.assertEqual(r.status_code, 302)
        self.v.refresh_from_db()
        self.assertEqual(self.v.netto_mietzins, Decimal('1500'))


class VertragAssistentLehntUnlesbaresAb(TestCase):
    """Der Assistent ersetzte unlesbare Eingaben still: Referenzzinssatz 1.25 %,
    LIK-Stand 107.1, Mietbeginn heute, Nettomiete 0. Eine unlesbare
    Personenzahl war ein Serverfehler."""

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        from portfolio.models import Einheit
        self.frei = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='4.5 Zi', typ='whg')
        self.c = Client()
        self.c.force_login(_team_user())

    def _speichern(self, **ueber):
        daten = {'einheit_id': str(self.frei.id), 'mieter_id': str(self.m.id),
                 'netto_mietzins': '1800', 'nebenkosten': '250', 'beginn': '2025-04-01'}
        daten.update(ueber)
        return self.c.post('/neu/vertraege/neu/speichern/', daten, follow=True)

    def _nichts_gespeichert(self):
        from rentals.models import Mietvertrag
        self.assertFalse(Mietvertrag.objects.filter(einheit=self.frei).exists())

    def test_referenzzinssatz_wird_nicht_still_ersetzt(self):
        r = self._speichern(basis_referenzzinssatz='1,5%%')
        self._nichts_gespeichert()
        self.assertContains(r, 'Referenzzinssatz')

    def test_lik_stand_wird_nicht_still_ersetzt(self):
        self._speichern(basis_lik_punkte='hundert')
        self._nichts_gespeichert()

    def test_unlesbarer_beginn_wird_nicht_heute(self):
        self._speichern(beginn='1. April')
        self._nichts_gespeichert()

    def test_unlesbare_personenzahl_ist_kein_serverfehler(self):
        r = self._speichern(anzahl_personen='zwei')
        self.assertEqual(r.status_code, 200)
        self._nichts_gespeichert()

    def test_leere_felder_bleiben_erlaubt(self):
        from rentals.models import Mietvertrag
        self._speichern(basis_referenzzinssatz='', basis_lik_punkte='', anzahl_personen='')
        self.assertTrue(Mietvertrag.objects.filter(einheit=self.frei).exists())
