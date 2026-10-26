"""Die Bento-Reihe der Startseite (Ember-Redesign, faelle/heute_bento.py).

Geprüft wird, was die Karten behaupten: Der Rückstand zählt nur Überfälliges,
der Verzug rechnet ab Fälligkeit und nur 90 Tage zurück, die Balken zeigen
verbuchte Zahlungen im richtigen Monat, das Wochenraster legt einen Termin in
die richtige Zeile, und eine interne Notiz ist keine «Nachricht».
"""
from datetime import datetime, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.tests._helfer import _basis_objekte, _seed_konten, _team_user, _test_organisation
from faelle import heute_bento


class _Basis(TestCase):
    def setUp(self):
        _seed_konten()
        self.org = _test_organisation()
        self.lg, self.einheit, self.mieter, self.vertrag = _basis_objekte()
        self.verwalter = _team_user('Verwalter')
        self.heute = timezone.localdate()

    def rechnung(self, status='offen', tage=-10, betrag='1000'):
        from finance.models import DebitorenRechnung
        faellig = self.heute + timedelta(days=tage)
        return DebitorenRechnung.objects.create(vertrag=self.vertrag, titel='Miete', betrag=Decimal(betrag),
                                                status=status, faellig_am=faellig, datum=faellig)

    def zahlung(self, rechnung, nach_tagen, betrag='1000'):
        from finance.models import Zahlungseingang
        return Zahlungseingang.objects.create(
            vertrag=self.vertrag, debitoren_rechnung=rechnung, betrag=Decimal(betrag), status='verbucht',
            datum_eingang=rechnung.faellig_am + timedelta(days=nach_tagen))


class RueckstandTests(_Basis):
    def test_zaehlt_nur_ueberfaellige_offene_und_teilbezahlte(self):
        self.rechnung('offen', -12, '1200')
        self.rechnung('teilbezahlt', -3, '300')
        self.rechnung('offen', +10, '500')        # noch nicht fällig
        self.rechnung('bezahlt', -40, '900')      # erledigt
        self.rechnung('storniert', -60, '999')    # storniert
        r = heute_bento.rueckstand(self.heute)
        self.assertEqual(r['n'], 2)
        self.assertEqual(r['summe'], Decimal('1500'))


class ZahlungTests(_Basis):
    def test_verzug_ab_faelligkeit_und_nur_neunzig_tage(self):
        self.zahlung(self.rechnung('bezahlt', -30), 2)
        self.zahlung(self.rechnung('bezahlt', -20), 8)
        self.zahlung(self.rechnung('bezahlt', -200), 40)   # Eingang vor 160 Tagen — zählt nicht
        z = heute_bento.zahlung(self.heute)
        self.assertEqual(z['anzahl'], 2)
        self.assertEqual(z['dauer'], 5.0)
        self.assertEqual(z['stufe'], 'warn')

    def test_ohne_zahlung_kein_verzug_statt_null(self):
        z = heute_bento.zahlung(self.heute)
        self.assertIsNone(z['dauer'])
        self.assertEqual(z['stufe'], '')
        self.assertGreaterEqual(z['bogen'], 0.0)
        self.assertLessEqual(z['bogen'], 100.0)


class EinnahmenTests(_Basis):
    def test_sieben_monate_und_der_laufende_ist_der_letzte(self):
        r = self.rechnung('bezahlt', 0)
        from finance.models import Zahlungseingang
        Zahlungseingang.objects.filter(pk=self.zahlung(r, 0, '1700').pk).update(datum_eingang=self.heute)
        e = heute_bento.einnahmen(self.heute)
        self.assertEqual(len(e['reihe']), 7)
        self.assertTrue(e['hat_daten'])
        letzter = e['reihe'][-1]
        self.assertEqual((letzter['monat'].year, letzter['monat'].month), (self.heute.year, self.heute.month))
        self.assertEqual(letzter['summe'], Decimal('1700'))
        self.assertTrue(all(0 <= x['hoehe'] <= 100 for x in e['reihe']))
        self.assertTrue(all(x['summe'] == 0 for x in e['reihe'][:-1]))

    def test_leer_ohne_verbuchte_zahlung(self):
        self.assertFalse(heute_bento.einnahmen(self.heute)['hat_daten'])

    def test_achse_rundet_auf_lesbare_stufen(self):
        self.assertEqual(heute_bento._runde_achse(Decimal('1700')), Decimal('2000'))
        self.assertEqual(heute_bento._runde_achse(Decimal('0')), Decimal('0'))
        self.assertEqual(heute_bento._kurz(Decimal('12400')), '12k')


class WocheTests(_Basis):
    def test_termin_am_nachmittag_liegt_in_der_nachmittagszeile_von_heute(self):
        from faelle.termin_models import Termin
        beginn = timezone.make_aware(datetime.combine(self.heute, datetime.min.time())) + timedelta(hours=14)
        Termin(titel='Wohnungsabnahme', art='abnahme', beginn=beginn, ort='Zürich', zustaendig=self.verwalter).save()
        w = heute_bento.woche(self.heute)
        tag = self.heute.weekday()
        zeilen = {z['name']: z['slots'][tag] for z in w['raster']}
        self.assertEqual(zeilen['Nachmittag']['anzahl'], 1)
        self.assertTrue(zeilen['Nachmittag']['heiss'])
        self.assertEqual(zeilen['Vormittag']['anzahl'], 0)
        self.assertTrue(w['tage'][tag]['heute'])
        self.assertEqual(w['montag'].weekday(), 0)


class PostTests(_Basis):
    def test_mieternachricht_ja_interne_notiz_nein(self):
        from tickets.models import SchadenMeldung, TicketNachricht
        t = SchadenMeldung.objects.create(liegenschaft=self.lg, titel='Heizung kalt', beschreibung='x')
        TicketNachricht.objects.create(ticket=t, nachricht='Interne Notiz', is_intern=True, absender_name='Team')
        self.assertIsNone(heute_bento.post())
        TicketNachricht.objects.create(ticket=t, nachricht='Es ist immer noch kalt', absender_name='Erika')
        p = heute_bento.post()
        self.assertEqual(p['titel'], 'Heizung kalt')
        self.assertEqual(p['url'], f'/neu/schaeden/{t.id}/')


class StartseiteZeigtBentoTests(_Basis):
    def test_karten_mit_echten_zahlen_und_ohne_stilattribut_fuer_daten(self):
        self.rechnung('offen', -12, '1200')
        c = Client()
        c.force_login(self.verwalter)
        r = c.get('/neu/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['bento']['rueckstand']['n'], 1)
        html = r.content.decode()
        self.assertIn('fw-ember-bento', html)
        self.assertIn('CHF 1’200', html.replace("'", '’'))
        # Balkenhöhen kommen als data-h, nicht als style (Stilschuld-Wächter)
        self.assertNotIn('style="--h:', html)
