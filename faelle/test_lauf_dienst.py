"""Tests: Ausgeführte Läufe verschwinden aus dem Vorrat, der Monat plant sich selbst.

Der Befund (01.10.2026): Läufe für August waren ausgeführt, standen aber weiter
als «nicht ausgelöst, 61 Tage über» im Arbeitsvorrat, und die Läufe für Oktober
fehlten ganz.
"""
from datetime import date
from unittest import mock

from django.test import TestCase

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.arbeitsvorrat import was_reisst
from faelle.lauf_dienst import (
    abgleichen_aus_daten, aktuelle_periode_sicherstellen, lauf_erledigt, planen)
from faelle.lauf_models import Lauf, Laufart

OKTOBER = date(2026, 10, 1)
STANDARD = ('sollstellung', 'bankabgleich', 'mahnlauf', 'zahllauf')


def _titel(zeilen):
    """{(schluessel, periode)} der Lauf-Zeilen — unabhängig von der Beschriftung."""
    return {(z['objekt'].laufart.schluessel, z['objekt'].periode)
            for z in zeilen if z['art'] == 'lauf'}


class _Basis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.org = cls.a.organisation


class AbschlussTests(_Basis):
    def test_ausgefuehrter_august_lauf_verschwindet_aus_dem_vorrat(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            planen(self.org, OKTOBER)
            vorher = _titel(was_reisst(OKTOBER))
            self.assertIn(('sollstellung', '2026-08'), vorher)

            lauf_erledigt('sollstellung', '2026-08', rechnungen=12)

            nachher = _titel(was_reisst(OKTOBER))
            self.assertNotIn(('sollstellung', '2026-08'), nachher)
            lauf = Lauf.objects.get(laufart__schluessel='sollstellung',
                                    periode='2026-08')
            self.assertEqual(lauf.status, Lauf.ABGESCHLOSSEN)
            self.assertEqual(lauf.kennzahlen['rechnungen'], 12)

    def test_wiederholter_abschluss_aendert_nichts(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            erster = lauf_erledigt('mahnlauf', '2026-08')
            am = erster.abgeschlossen_am
            zweiter = lauf_erledigt('mahnlauf', '2026-08')
            self.assertEqual(zweiter.abgeschlossen_am, am)

    def test_offene_blockade_haelt_den_lauf_im_vorrat(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            lauf = Lauf.objects.get(laufart__schluessel='bankabgleich',
                                    periode='2026-08')
            lauf.blockieren('Sieben unzugeordnete Eingänge')
            lauf_erledigt('bankabgleich', '2026-08')
            lauf.refresh_from_db()
            self.assertNotEqual(lauf.status, Lauf.ABGESCHLOSSEN)

    def test_ohne_geplanten_lauf_kein_fehler(self):
        with mandant(self.org):
            self.assertIsNone(lauf_erledigt('mahnlauf', '1999-01'))

    def test_uebersprungener_lauf_zaehlt_nicht_als_offen(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            Lauf.objects.get(laufart__schluessel='zahllauf', periode='2026-08') \
                .ueberspringen('Keine Rechnungen im August.')
            self.assertEqual(
                Lauf.objects.offen().filter(laufart__schluessel='zahllauf').count(), 0)


class MonatsGenerierungTests(_Basis):
    def test_vier_standardlaeufe_fuer_oktober_mit_richtigen_tagen(self):
        with mandant(self.org):
            planen(self.org, OKTOBER)
            tage = {l.laufart.schluessel: l.faellig_am.day
                    for l in Lauf.objects.filter(periode='2026-10')
                    .select_related('laufart')}
            self.assertEqual(tage['sollstellung'], 1)
            self.assertEqual(tage['bankabgleich'], 5)
            self.assertEqual(tage['mahnlauf'], 15)
            self.assertEqual(tage['zahllauf'], 25)

    def test_heute_seite_plant_den_aktuellen_monat_selbst(self):
        """Die Ursache von Bug 2: niemand hat `laeufe_planen` je gestartet."""
        from faelle.arbeitsvorrat import arbeitsvorrat
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))   # eingerichtet, aber nur August
            self.assertEqual(Lauf.objects.filter(periode='2026-10').count(), 0)
            with mock.patch('django.utils.timezone.localdate',
                            return_value=OKTOBER), \
                    mock.patch('core.tenancy.aktuelle_organisation',
                               return_value=self.org):
                ctx = arbeitsvorrat(request=None)
            self.assertEqual(Lauf.objects.filter(periode='2026-10').count(), 4)
            titel = _titel(ctx['av_laeufe'] + ctx['av_reisst'])
            self.assertIn(('sollstellung', '2026-10'), titel)

    def test_verwaltung_ohne_laufarten_bekommt_nichts_geplant(self):
        with mandant(self.org):
            # Fixture-Lauf liegt in 2099 → «nie geplant» im Sinn der Regel.
            self.assertEqual(aktuelle_periode_sicherstellen(self.org, OKTOBER), 0)
            self.assertFalse(Lauf.objects.filter(periode='2026-10').exists())

    def test_planen_ist_idempotent_und_oeffnet_nichts_wieder(self):
        with mandant(self.org):
            planen(self.org, OKTOBER)
            lauf_erledigt('sollstellung', '2026-10')
            self.assertEqual(planen(self.org, OKTOBER)[1], 0)
            self.assertEqual(
                Lauf.objects.get(laufart__schluessel='sollstellung',
                                 periode='2026-10').status, Lauf.ABGESCHLOSSEN)

    def test_aktuelle_periode_sicherstellen_zweiter_aufruf_ohne_neue_laeufe(self):
        with mandant(self.org):
            # 4 Monatsläufe + MWST (Q4 wird im Oktober fällig)
            planen(self.org, date(2026, 8, 1))
            self.assertEqual(aktuelle_periode_sicherstellen(self.org, OKTOBER), 5)
            self.assertEqual(aktuelle_periode_sicherstellen(self.org, OKTOBER), 0)

    def test_alte_offene_laeufe_verdraengen_den_oktober_nicht(self):
        """Gegenprobe zu `[:60]`: 70 alte, offene Läufe vor dem Oktober."""
        with mandant(self.org):
            planen(self.org, OKTOBER)
            art = Lauf.objects.filter(periode='2026-10').first().laufart
            for i in range(70):
                Lauf(laufart=art, periode=f'2019-{i:03d}',
                     faellig_am=date(2019, 1, 1), organisation=self.org).save()
            self.assertIn(('sollstellung', '2026-10'),
                          _titel(was_reisst(OKTOBER)))
            Lauf.objects.filter(periode__startswith='2019-').delete()


class SimulationTests(_Basis):
    def test_august_abschliessen_dann_oktober_korrekt(self):
        """Der Ablauf aus dem Auftrag: alten Lauf schliessen, Oktober prüfen."""
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            for s in STANDARD:
                lauf_erledigt(s, '2026-08')
            planen(self.org, OKTOBER)
            titel = _titel(was_reisst(OKTOBER, grenze=30))
            self.assertFalse([t for t in titel if t[1] == '2026-08'])
            self.assertEqual({t[0] for t in titel if t[1] == '2026-10'},
                             set(STANDARD))


class AbgleichTests(_Basis):
    def test_beleg_schliesst_nur_belegten_lauf(self):
        from finance.models import Mahnung  # noqa: F401  (Modell vorhanden)
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            with mock.patch('finance.models.Mahnung.objects') as m:
                m.filter.return_value.exists.return_value = True
                n = abgleichen_aus_daten(OKTOBER)
            mahn = Lauf.objects.get(laufart__schluessel='mahnlauf', periode='2026-08')
            soll = Lauf.objects.get(laufart__schluessel='sollstellung',
                                    periode='2026-08')
            self.assertEqual(mahn.status, Lauf.ABGESCHLOSSEN)
            self.assertNotEqual(soll.status, Lauf.ABGESCHLOSSEN)
            self.assertEqual(n, 1)


class ViewVerdrahtungTests(_Basis):
    """Der eigentliche Fehler: die Views rechneten, aber meldeten nichts zurück."""

    def _client(self):
        from django.test import Client
        c = Client()
        c.force_login(self.a.benutzer)
        return c

    def _lauf(self, schluessel, periode):
        return Lauf.objects.get(laufart__schluessel=schluessel, periode=periode)

    def test_mahnlauf_post_schliesst_den_lauf_des_monats(self):
        from django.utils import timezone
        heute = timezone.localdate()
        periode = f'{heute.year}-{heute.month:02d}'
        with mandant(self.org):
            planen(self.org, heute)
            self.assertNotEqual(self._lauf('mahnlauf', periode).status,
                                Lauf.ABGESCHLOSSEN)
        antwort = self._client().post('/neu/mahnwesen/lauf/', {'kein_versand': 'on'})
        self.assertEqual(antwort.status_code, 302)
        with mandant(self.org):
            self.assertEqual(self._lauf('mahnlauf', periode).status,
                             Lauf.ABGESCHLOSSEN)

    def test_sollstellung_post_schliesst_august(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
        antwort = self._client().post('/neu/sollstellung/starten/',
                                      {'jahr': 2026, 'monat': 8})
        self.assertEqual(antwort.status_code, 302)
        with mandant(self.org):
            self.assertEqual(self._lauf('sollstellung', '2026-08').status,
                             Lauf.ABGESCHLOSSEN)


class AltlaufTests(_Basis):
    """Gemeldet nach dem Merge: «bereits ausgeführt, werden trotzdem angezeigt»."""

    def test_ausfuehrung_im_oktober_erledigt_auch_den_versaeumten_august(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            planen(self.org, OKTOBER)
            lauf_erledigt('mahnlauf', '2026-10', auch_aeltere=True)
            status = {l.periode: l.status
                      for l in Lauf.objects.filter(laufart__schluessel='mahnlauf')}
            self.assertEqual(status['2026-08'], Lauf.ABGESCHLOSSEN)
            self.assertEqual(status['2026-10'], Lauf.ABGESCHLOSSEN)

    def test_ohne_auch_aeltere_bleibt_august_offen(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            lauf_erledigt('mahnlauf', '2026-10')
            self.assertNotEqual(self._august().status, Lauf.ABGESCHLOSSEN)

    def _august(self):
        return Lauf.objects.get(laufart__schluessel='mahnlauf', periode='2026-08')

    def test_blockierter_altlauf_bleibt_trotz_spaeterem_lauf_offen(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            self._august().blockieren('Sieben unzugeordnete Eingänge')
            lauf_erledigt('mahnlauf', '2026-10', auch_aeltere=True)
            self.assertNotEqual(self._august().status, Lauf.ABGESCHLOSSEN)

    def test_heute_seite_heilt_belegt_ausgefuehrte_altlaeufe(self):
        from faelle.arbeitsvorrat import arbeitsvorrat
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            with mock.patch('django.utils.timezone.localdate',
                            return_value=OKTOBER), \
                    mock.patch('core.tenancy.aktuelle_organisation',
                               return_value=self.org), \
                    mock.patch('finance.models.Mahnung.objects') as m:
                m.filter.return_value.exists.return_value = True
                arbeitsvorrat(request=None)
            self.assertEqual(self._august().status, Lauf.ABGESCHLOSSEN)


class UeberspringenKnopfTests(_Basis):
    def _client(self):
        from django.test import Client
        c = Client()
        c.force_login(self.a.benutzer)
        return c

    def _mahnlauf(self, periode='2026-08'):
        return Lauf.objects.get(laufart__schluessel='mahnlauf', periode=periode)

    def test_knopf_steht_auf_der_laufseite(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            pk = self._mahnlauf().pk
        html = self._client().get('/neu/laeufe/').content.decode()
        self.assertIn(f'/neu/laeufe/{pk}/ueberspringen/', html)

    def test_ueberspringen_mit_begruendung_nimmt_den_lauf_aus_dem_vorrat(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            pk = self._mahnlauf().pk
        antwort = self._client().post(f'/neu/laeufe/{pk}/ueberspringen/',
                                      {'bemerkung': 'Keine offenen Posten.'})
        self.assertEqual(antwort.status_code, 302)
        with mandant(self.org):
            lauf = self._mahnlauf()
            self.assertEqual(lauf.status, Lauf.UEBERSPRUNGEN)
            self.assertEqual(lauf.bemerkung, 'Keine offenen Posten.')
            self.assertNotIn(('mahnlauf', '2026-08'),
                             _titel(was_reisst(OKTOBER)))

    def test_ohne_begruendung_wird_nichts_gespeichert(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            pk = self._mahnlauf().pk
        self._client().post(f'/neu/laeufe/{pk}/ueberspringen/', {'bemerkung': '  '})
        with mandant(self.org):
            self.assertEqual(self._mahnlauf().status, Lauf.OFFEN)

    def test_blockierter_lauf_laesst_sich_nicht_ueberspringen(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            lauf = self._mahnlauf()
            lauf.blockieren('Sieben unzugeordnete Eingänge')
            pk = lauf.pk
        self._client().post(f'/neu/laeufe/{pk}/ueberspringen/',
                            {'bemerkung': 'egal'})
        with mandant(self.org):
            self.assertEqual(self._mahnlauf().status, Lauf.OFFEN)

    def test_get_ist_nicht_erlaubt(self):
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            pk = self._mahnlauf().pk
        self.assertEqual(
            self._client().get(f'/neu/laeufe/{pk}/ueberspringen/').status_code, 405)

    def test_fremder_lauf_ist_nicht_erreichbar(self):
        """Mandantentrennung: Verwaltung B darf den Lauf von A nicht überspringen."""
        from django.test import Client
        b = MandantenFixture('B', '3000', 'Bern')
        with mandant(self.org):
            planen(self.org, date(2026, 8, 1))
            pk = self._mahnlauf().pk
        c = Client()
        c.force_login(b.benutzer)
        antwort = c.post(f'/neu/laeufe/{pk}/ueberspringen/', {'bemerkung': 'x'})
        self.assertEqual(antwort.status_code, 404)
        with mandant(self.org):
            self.assertEqual(self._mahnlauf().status, Lauf.OFFEN)
