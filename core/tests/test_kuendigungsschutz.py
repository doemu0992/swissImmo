"""Art. 271a OR: Vermieterkündigung während eines Verfahrens und drei Jahre danach (MIET-06).

DER TEXT (Fedlex)

  Abs. 1 lit. d: Kündigung «während eines mit dem Mietverhältnis zusammenhängenden Schlichtungs- oder
  Gerichtsverfahrens, ausser wenn der Mieter das Verfahren missbräuchlich eingeleitet hat»;
  lit. e: «vor Ablauf von drei Jahren nach Abschluss» eines solchen Verfahrens, in dem der Vermieter unterlegen ist,
  Forderung oder Klage zurückgezogen oder erheblich eingeschränkt, auf die Anrufung des Richters verzichtet oder
  sich verglichen hat; Abs. 2: ebenso bei einer schriftlich nachgewiesenen Einigung ausserhalb eines Verfahrens;
  Abs. 3: d und e gelten nicht bei Kündigungen wegen dringenden Eigenbedarfs, Zahlungsrückstands (257d), schwerer
  Pflichtverletzung (257f), Veräusserung (261), aus wichtigen Gründen (266g) und wegen Konkurs (266h).

Die Uhr steht auf Mittwoch, 4.11.2026. Jeder Test hat seine Gegenprobe im selben Test.
"""
from datetime import date
from decimal import Decimal

from django.contrib.messages import get_messages
from django.db.models import ProtectedError
from django.test import Client, TestCase

from core.services.kuendigungsschutz import AUSNAHME_ARTEN, drei_jahre_nach, sperrfristen
from core.tenancy import organisation_kontext
from rentals.models import Kuendigung, Mietverfahren

from ._helfer import _basis_objekte, _team_user
from ._isolation import MandantenFixture
from ._uhr import bei_stichtag

HEUTE = date(2026, 11, 4)


def _verfahren(v, **kw):
    felder = dict(vertrag=v, art='schlichtung', gegenstand='mietzins', eingeleitet_am=date(2026, 9, 1))
    felder.update(kw)
    return Mietverfahren.objects.create(**felder)


class DreiJahreTests(TestCase):
    def test_gleicher_tag_drei_jahre_spaeter(self):
        self.assertEqual(drei_jahre_nach(date(2026, 6, 15)), date(2029, 6, 15))

    def test_schaltjahr_29_februar_faellt_auf_den_28_februar(self):
        # 29.2.2024 + 3 Jahre: den 29.2.2027 gibt es nicht -> letzter Tag des Monats (Art. 77 Abs. 1 Ziff. 3 OR).
        self.assertEqual(drei_jahre_nach(date(2024, 2, 29)), date(2027, 2, 28))
        # Gegenprobe: 28.2.2024 + 3 Jahre = 28.2.2027; 29.2.2028 + 3 = 28.2.2031
        self.assertEqual(drei_jahre_nach(date(2024, 2, 28)), date(2027, 2, 28))
        self.assertEqual(drei_jahre_nach(date(2028, 2, 29)), date(2031, 2, 28))


class SperrfristenTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()

    def lits(self, tage, **kw):
        return sorted(sp.lit for sp in sperrfristen(self.v, tage, **kw))

    # -- lit. d: während des Verfahrens ----------------------------------------------------------
    def test_haengiges_verfahren_sperrt(self):
        _verfahren(self.v)
        self.assertEqual(self.lits({HEUTE}), ['d'])
        text = sperrfristen(self.v, {HEUTE})[0].text
        self.assertIn('Art. 271a Abs. 1 lit. d OR', text)
        self.assertIn('01.09.2026', text)
        # Gegenprobe: vor Beginn des Verfahrens gab es nichts.
        self.assertEqual(self.lits({date(2026, 8, 31)}), [])

    def test_versand_oder_zugang_genuegt(self):
        """Versand vor dem Verfahren, Zugang mitten darin: gewarnt wird, die sichere Seite."""
        _verfahren(self.v, eingeleitet_am=date(2026, 11, 5))
        self.assertEqual(self.lits({date(2026, 11, 4), date(2026, 11, 11)}), ['d'])
        self.assertEqual(self.lits({date(2026, 11, 4)}), [])

    def test_missbraeuchlich_eingeleitet_sperrt_nicht(self):
        _verfahren(self.v, abgeschlossen_am=date(2026, 10, 1), ausgang='missbraeuchlich')
        self.assertEqual(self.lits({date(2026, 9, 15), date(2026, 11, 4)}), [])
        # Gegenprobe: derselbe Zeitraum mit einem Vergleich sperrt (d während, e danach).
        Mietverfahren.objects.all().delete()
        _verfahren(self.v, abgeschlossen_am=date(2026, 10, 1), ausgang='vergleich')
        self.assertEqual(self.lits({date(2026, 9, 15)}), ['d'])
        self.assertEqual(self.lits({date(2026, 11, 4)}), ['e'])

    # -- lit. e: drei Jahre danach ----------------------------------------------------------------
    def test_nach_vergleich_drei_jahre_inklusive_letztem_tag(self):
        _verfahren(self.v, eingeleitet_am=date(2026, 1, 10), abgeschlossen_am=date(2026, 6, 15), ausgang='vergleich')
        self.assertEqual(self.lits({date(2026, 6, 16)}), ['e'])
        self.assertEqual(self.lits({date(2029, 6, 15)}), ['e'])              # letzter geschützter Tag
        self.assertEqual(self.lits({date(2029, 6, 16)}), [])                 # Gegenprobe: danach frei
        text = sperrfristen(self.v, {date(2027, 1, 1)})[0].text
        self.assertIn('bis und mit 15.06.2029', text)

    def test_alle_ausgaenge_zugunsten_des_mieters_loesen_die_nachfrist_aus(self):
        for ausgang in ('vermieter_unterlegen', 'vermieter_zurueckgezogen', 'vermieter_verzicht', 'vergleich'):
            with self.subTest(ausgang=ausgang):
                Mietverfahren.objects.all().delete()
                _verfahren(self.v, abgeschlossen_am=date(2026, 10, 1), ausgang=ausgang)
                self.assertEqual(self.lits({HEUTE}), ['e'])

    def test_ausgang_zulasten_des_mieters_loest_keine_nachfrist_aus(self):
        for ausgang in ('mieter_unterlegen', 'mieter_zurueckgezogen'):
            with self.subTest(ausgang=ausgang):
                Mietverfahren.objects.all().delete()
                _verfahren(self.v, abgeschlossen_am=date(2026, 10, 1), ausgang=ausgang)
                self.assertEqual(self.lits({HEUTE}), [])
                # ... während des Verfahrens galt der Schutz trotzdem (lit. d).
                self.assertEqual(self.lits({date(2026, 9, 15)}), ['d'])

    def test_schriftliche_einigung_ausserhalb_eines_verfahrens_abs_2(self):
        _verfahren(self.v, art='einigung', eingeleitet_am=date(2026, 5, 1), abgeschlossen_am=date(2026, 5, 1),
                   ausgang='vergleich')
        self.assertEqual(self.lits({HEUTE}), ['e'])
        # Gegenprobe: Eine Einigung ist kein laufendes Verfahren: am Tag davor nichts, am Tag selbst lit. e.
        self.assertEqual(self.lits({date(2026, 4, 30)}), [])
        self.assertEqual(self.lits({date(2026, 5, 1)}), ['e'])

    def test_schaltjahr_verfahren_endet_am_29_februar(self):
        _verfahren(self.v, eingeleitet_am=date(2024, 1, 5), abgeschlossen_am=date(2024, 2, 29), ausgang='vergleich')
        self.assertEqual(self.lits({date(2027, 2, 28)}), ['e'])
        self.assertEqual(self.lits({date(2027, 3, 1)}), [])

    # -- Abs. 3: Ausnahmen ---------------------------------------------------------------------------
    def test_die_gruende_des_abs_3_loesen_nichts_aus(self):
        _verfahren(self.v)
        for art in sorted(AUSNAHME_ARTEN):
            with self.subTest(art=art):
                self.assertEqual(self.lits({HEUTE}, ausserordentlich_art=art), [])
        # Gegenprobe: die Menge ist genau die der Ausnahmen — 257d, 257f, 266g, 266h — und eine ordentliche Kündigung
        # (leere Art) sperrt.
        self.assertEqual(AUSNAHME_ARTEN, {'257d', '257f', '266g', '266h'})
        self.assertEqual(self.lits({HEUTE}, ausserordentlich_art=''), ['d'])

    # -- Mietzinsanpassung angefochten ------------------------------------------------------------------
    def test_angefochtene_mietzinsanpassung_zaehlt_als_laufendes_schlichtungsverfahren(self):
        from rentals.models import MietzinsAnpassung
        anp = MietzinsAnpassung.objects.create(
            vertrag=self.v, wirksam_ab=date(2027, 1, 1), neuer_netto_mietzins=Decimal('1600'),
            status='versandt', versand_am=date(2026, 9, 1))
        self.assertEqual(self.lits({HEUTE}), [])                              # nur versandt: kein Verfahren
        anp.status = 'angefochten'
        anp.save(update_fields=['status'])
        self.assertEqual(self.lits({HEUTE}), ['d'])
        self.assertIn('Status «angefochten»', sperrfristen(self.v, {HEUTE})[0].text)
        # Gegenprobe: vor dem Versand der Anpassung gab es keine Anfechtung.
        self.assertEqual(self.lits({date(2026, 8, 1)}), [])

    def test_ohne_vertrag_oder_ohne_daten_nichts(self):
        self.assertEqual(sperrfristen(None, {HEUTE}), [])
        self.assertEqual(sperrfristen(self.v, set()), [])
        self.assertEqual(sperrfristen(self.v, {None}), [])

    def test_meldungen_sind_uebersetzt(self):
        from django.utils import translation
        _verfahren(self.v, abgeschlossen_am=date(2026, 10, 1), ausgang='vergleich')
        for sprache in ('fr', 'it', 'en'):
            with self.subTest(sprache=sprache), translation.override(sprache):
                for sp in sperrfristen(self.v, {HEUTE}):
                    self.assertNotIn('Kündigung', sp.text)
                    self.assertNotIn('Vermieters', sp.text)


@bei_stichtag(HEUTE)
class KuendigungErfassenSperreTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user('Verwaltung'))

    def _post(self, **daten):
        daten.setdefault('eingang_datum', HEUTE.isoformat())
        return self.c.post(f'/neu/vertraege/{self.v.id}/kuendigen/', daten)

    def _meldungen(self, antwort):
        return ' '.join(str(m) for m in get_messages(antwort.wsgi_request))

    def _anzahl(self):
        return Kuendigung.objects.filter(vertrag=self.v).count()

    def test_vermieterkuendigung_im_verfahren_wird_angehalten(self):
        _verfahren(self.v)
        antwort = self._post(absender='vermieter')
        self.assertEqual(self._anzahl(), 0)
        self.v.refresh_from_db()
        self.assertEqual(self.v.status, 'aktiv')
        text = self._meldungen(antwort)
        self.assertIn('Art. 271a Abs. 1 lit. d OR', text)
        self.assertIn('Ausnahmen (Art. 271a Abs. 3 OR)', text)
        self.assertEqual(antwort['Location'], f'/neu/vertraege/{self.v.id}/kuendigen/?sperrfrist=1')
        # Gegenprobe: ohne Verfahren wird dieselbe Kündigung erfasst.
        Mietverfahren.objects.all().delete()
        self._post(absender='vermieter')
        self.assertEqual(self._anzahl(), 1)

    def test_ausnahme_bestaetigt_die_kuendigung_wird_erfasst_und_vermerkt(self):
        _verfahren(self.v, abgeschlossen_am=date(2026, 10, 1), ausgang='vermieter_unterlegen')
        antwort = self._post(absender='vermieter', sperrfrist_ausnahme='on', bemerkung='Eigenbedarf Sohn')
        self.assertEqual(self._anzahl(), 1)
        k = Kuendigung.objects.get(vertrag=self.v)
        self.assertIn('Eigenbedarf Sohn', k.bemerkung)
        self.assertIn('Sperrfrist Art. 271a OR: Ausnahme nach Abs. 3 bestätigt', k.bemerkung)
        self.assertIn('lit. e', k.bemerkung)
        self.assertIn('anfechten', self._meldungen(antwort))
        from core.models import AktivitaetsLog
        self.assertTrue(AktivitaetsLog.objects.filter(aktion='Kündigung erfasst',
                                                      details__contains='Sperrfrist Art. 271a OR').exists())

    def test_kuendigung_des_mieters_ist_nie_betroffen(self):
        _verfahren(self.v)
        self._post(absender='mieter')
        self.assertEqual(self._anzahl(), 1)

    def test_ausserordentliche_gruende_des_abs_3_sind_nie_betroffen(self):
        _verfahren(self.v)
        self._post(absender='vermieter', ausserordentlich='on', ausserordentlich_art='266g',
                   gewuenschtes_ende='2027-03-31')
        self.assertEqual(self._anzahl(), 1)

    def test_kuendigungsformular_zeigt_die_sperre(self):
        seite = self.c.get(f'/neu/vertraege/{self.v.id}/kuendigen/')
        self.assertNotContains(seite, 'sperrfrist_ausnahme')
        _verfahren(self.v)
        seite = self.c.get(f'/neu/vertraege/{self.v.id}/kuendigen/')
        self.assertContains(seite, 'Sperrfrist nach Art. 271a OR')
        self.assertContains(seite, 'name="sperrfrist_ausnahme"')


@bei_stichtag(HEUTE)
class VerfahrenErfassenTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user('Verwaltung'))
        self.url = f'/neu/vertraege/{self.v.id}/verfahren/'

    def _meldungen(self, antwort):
        return ' '.join(str(m) for m in get_messages(antwort.wsgi_request))

    def test_seite_leer_zeigt_den_leeren_zustand(self):
        seite = self.c.get(self.url)
        self.assertContains(seite, 'kein Verfahren erfasst')
        self.assertNotContains(seite, 'Heute gesperrt')

    def test_verfahren_erfassen_und_abschliessen(self):
        self.c.post(self.url, {'aktion': 'neu', 'art': 'schlichtung', 'gegenstand': 'mietzins',
                               'eingeleitet_am': '2026-09-01', 'aktenzeichen': 'SB 12/26'})
        vf = Mietverfahren.objects.get()
        self.assertEqual((vf.art, vf.gegenstand, vf.ausgang, vf.abgeschlossen_am),
                         ('schlichtung', 'mietzins', 'haengig', None))
        self.assertContains(self.c.get(self.url), 'Heute gesperrt')
        antwort = self.c.post(self.url, {'aktion': 'abschluss', 'verfahren': vf.pk, 'ausgang': 'vergleich',
                                         'abgeschlossen_am': '2026-10-20'})
        vf.refresh_from_db()
        self.assertEqual((vf.ausgang, vf.abgeschlossen_am), ('vergleich', date(2026, 10, 20)))
        self.assertIn('bis und mit 20.10.2029', self._meldungen(antwort))

    def test_ausgang_zulasten_des_mieters_sagt_keine_nachfrist(self):
        vf = _verfahren(self.v)
        antwort = self.c.post(self.url, {'aktion': 'abschluss', 'verfahren': vf.pk, 'ausgang': 'mieter_unterlegen',
                                         'abgeschlossen_am': '2026-10-20'})
        self.assertNotIn('bis und mit', self._meldungen(antwort))
        vf.refresh_from_db()
        self.assertEqual(vf.ausgang, 'mieter_unterlegen')

    def test_einigung_ist_sofort_abgeschlossen(self):
        self.c.post(self.url, {'aktion': 'neu', 'art': 'einigung', 'gegenstand': 'nebenkosten',
                               'eingeleitet_am': '2026-10-05'})
        vf = Mietverfahren.objects.get()
        self.assertEqual((vf.abgeschlossen_am, vf.ausgang), (date(2026, 10, 5), 'vergleich'))

    def test_ungueltige_eingaben_erfassen_nichts(self):
        # Unbekannte Art, Zukunft, fehlendes Datum
        for daten in ({'art': 'sonstwas', 'gegenstand': 'mietzins', 'eingeleitet_am': '2026-09-01'},
                      {'art': 'gericht', 'gegenstand': 'unbekannt', 'eingeleitet_am': '2026-09-01'},
                      {'art': 'gericht', 'gegenstand': 'mietzins', 'eingeleitet_am': '2026-11-05'},
                      {'art': 'gericht', 'gegenstand': 'mietzins', 'eingeleitet_am': ''}):
            with self.subTest(daten=daten):
                self.c.post(self.url, {'aktion': 'neu', **daten})
                self.assertEqual(Mietverfahren.objects.count(), 0)
        # Gegenprobe: der gültige Fall am heutigen Tag wird erfasst.
        self.c.post(self.url, {'aktion': 'neu', 'art': 'gericht', 'gegenstand': 'mietzins',
                               'eingeleitet_am': '2026-11-04'})
        self.assertEqual(Mietverfahren.objects.count(), 1)

    def test_abschluss_prueft_datum_ausgang_und_haengigkeit(self):
        vf = _verfahren(self.v)
        for daten in ({'ausgang': 'haengig', 'abgeschlossen_am': '2026-10-20'},          # kein Ausgang
                      {'ausgang': 'vergleich', 'abgeschlossen_am': '2026-08-31'},         # vor dem Beginn
                      {'ausgang': 'vergleich', 'abgeschlossen_am': '2026-11-05'},         # Zukunft
                      {'ausgang': 'vergleich', 'abgeschlossen_am': ''}):
            with self.subTest(daten=daten):
                self.c.post(self.url, {'aktion': 'abschluss', 'verfahren': vf.pk, **daten})
                vf.refresh_from_db()
                self.assertIsNone(vf.abgeschlossen_am)
        self.c.post(self.url, {'aktion': 'abschluss', 'verfahren': vf.pk, 'ausgang': 'vergleich',
                               'abgeschlossen_am': '2026-10-20'})
        # Ein abgeschlossenes Verfahren lässt sich nicht ein zweites Mal abschliessen.
        self.c.post(self.url, {'aktion': 'abschluss', 'verfahren': vf.pk, 'ausgang': 'mieter_unterlegen',
                               'abgeschlossen_am': '2026-10-21'})
        vf.refresh_from_db()
        self.assertEqual((vf.ausgang, vf.abgeschlossen_am), ('vergleich', date(2026, 10, 20)))

    def test_nur_inhaber_und_verwalter(self):
        c = Client()
        c.force_login(_team_user('Sachbearbeitung'))
        self.assertEqual(c.get(self.url).status_code, 403)
        c.post(self.url, {'aktion': 'neu', 'art': 'gericht', 'gegenstand': 'mietzins',
                          'eingeleitet_am': '2026-09-01'})
        self.assertEqual(Mietverfahren.objects.count(), 0)
        # Gegenprobe: der Verwalter darf.
        self.assertEqual(self.c.get(self.url).status_code, 200)

    def test_vertrag_mit_verfahren_laesst_sich_nicht_loeschen(self):
        _verfahren(self.v)
        with self.assertRaises(ProtectedError):
            self.v.delete()

    def test_vertragsakte_verlinkt_die_seite(self):
        seite = self.c.get(f'/neu/vertraege/{self.v.id}/')
        self.assertContains(seite, self.url)


class VerfahrenMandantenTests(TestCase):
    """Zwei Verwaltungen: A sieht und ändert die Verfahren von B nicht — und sie sperren dessen Kündigungen nicht."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        with organisation_kontext(cls.b.organisation):
            cls.fremd = _verfahren(cls.b.vertrag)

    def test_fremder_vertrag_gibt_404_und_nichts_wird_angelegt(self):
        c = Client()
        c.force_login(self.a.benutzer)
        url = f'/neu/vertraege/{self.b.vertrag.pk}/verfahren/'
        self.assertEqual(c.get(url).status_code, 404)
        antwort = c.post(url, {'aktion': 'neu', 'art': 'gericht', 'gegenstand': 'mietzins',
                               'eingeleitet_am': '2026-09-01'})
        self.assertEqual(antwort.status_code, 404)
        antwort = c.post(url, {'aktion': 'abschluss', 'verfahren': self.fremd.pk, 'ausgang': 'vergleich',
                               'abgeschlossen_am': '2026-10-01'})
        self.assertEqual(antwort.status_code, 404)
        with organisation_kontext(self.b.organisation):
            self.assertEqual(Mietverfahren.objects.count(), 1)
            self.assertIsNone(Mietverfahren.objects.get().abgeschlossen_am)

    def test_eigener_vertrag_bleibt_von_fremden_verfahren_unberuehrt(self):
        with organisation_kontext(self.a.organisation):
            self.assertEqual(sperrfristen(self.a.vertrag, {date(2026, 11, 4)}), [])
            self.assertEqual(Mietverfahren.objects.count(), 0)
        # Gegenprobe: der Vertrag von B ist gesperrt.
        with organisation_kontext(self.b.organisation):
            self.assertEqual([sp.lit for sp in sperrfristen(self.b.vertrag, {date(2026, 11, 4)})], ['d'])

    def test_verfahren_von_b_ist_in_a_nicht_ladbar(self):
        with organisation_kontext(self.a.organisation):
            self.assertFalse(Mietverfahren.objects.filter(pk=self.fremd.pk).exists())
        with organisation_kontext(self.b.organisation):
            self.assertTrue(Mietverfahren.objects.filter(pk=self.fremd.pk).exists())
