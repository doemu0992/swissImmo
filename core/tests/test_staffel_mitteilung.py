"""Staffelmiete: Mitteilung jeder Erhöhung (Art. 269d Abs. 5 OR, Art. 19a VMWG).

Gegenproben stehen im Bericht zur Etappe (Code zurückgebaut -> der genannte Test wird rot).
"""
import io
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase
from pypdf import PdfReader

from core.services import staffel_mitteilung as sm

from ._helfer import _basis_objekte, _team_user, _test_organisation

D = Decimal


def _heute(tag):
    return mock.patch('django.utils.timezone.localdate', return_value=tag)


def _staffel_vertrag(sprache='de', stufen=None):
    """Staffelvertrag, Netto 1500; Stufen 1.6.2027 (+50) und 1.6.2028 (+50)."""
    _test_organisation()
    lg, e, m, v = _basis_objekte()
    m.sprache = sprache
    m.save()
    v.mietzins_modell = 'staffel'
    v.beginn = date(2026, 6, 1)
    v.ist_befristet = True
    v.ende = date(2031, 5, 31)
    v.save()
    from rentals.models import Staffelstufe
    for ab, netto, erhoehung in (stufen or ((date(2027, 6, 1), '1550.00', '50.00'),
                                            (date(2028, 6, 1), '1600.00', '50.00'))):
        Staffelstufe.objects.create(vertrag=v, ab_datum=ab, netto_mietzins=D(netto),
                                    erhoehung_chf=D(erhoehung) if erhoehung else None)
    return v


# ---------------------------------------------------------------------------
# Das Fenster (Art. 19a VMWG)
# ---------------------------------------------------------------------------
class FensterTests(SimpleTestCase):

    def test_genau_vier_monate_vorher(self):
        self.assertEqual(sm.fenster_beginn(date(2027, 6, 1)), date(2027, 2, 1))
        self.assertEqual(sm.fenster_beginn(date(2027, 1, 1)), date(2026, 9, 1))     # über den Jahreswechsel

    def test_ein_tag_vor_dem_fenster_ist_zu_frueh(self):
        eintritt = date(2027, 6, 1)
        self.assertFalse(sm.im_fenster(eintritt, date(2027, 1, 31)))     # ein Tag zu früh
        self.assertTrue(sm.im_fenster(eintritt, date(2027, 2, 1)))       # genau vier Monate
        self.assertTrue(sm.im_fenster(eintritt, date(2027, 5, 31)))

    def test_monatsende_arithmetik(self):
        # Der 31. Mai minus vier Monate ist der 31. Januar.
        self.assertEqual(sm.fenster_beginn(date(2027, 5, 31)), date(2027, 1, 31))
        # 31.3.: Der 30.11. ist vier Monate UND EINEN TAG davor (30.11. + 4 Monate = 30.3.). Der 1.12. gilt.
        self.assertEqual(sm.fenster_beginn(date(2027, 3, 31)), date(2026, 12, 1))
        # 30.6.: Februar hat keinen 30.; der 28.2. wäre 4 Monate und 2 Tage davor.
        self.assertEqual(sm.fenster_beginn(date(2027, 6, 30)), date(2027, 3, 1))
        self.assertEqual(sm.fenster_beginn(date(2028, 6, 30)), date(2028, 3, 1))    # auch im Schaltjahr (29.2. fehlt nicht, ist aber 4 M. + 1 T.)
        # 31.10.: Juni hat keinen 31.
        self.assertEqual(sm.fenster_beginn(date(2027, 10, 31)), date(2027, 7, 1))
        # Letzter Tag eines Monats, der den Tag hat: 28.2. (kein Schaltjahr) und 29.2. (Schaltjahr).
        self.assertEqual(sm.fenster_beginn(date(2027, 2, 28)), date(2026, 10, 28))
        self.assertEqual(sm.fenster_beginn(date(2028, 2, 29)), date(2027, 10, 29))

    def test_31_januar_plus_vier_monate(self):
        """Versand am 31.1.: Erhöhungen bis zum 31.5. sind im Fenster, die vom 1.6. nicht."""
        versand = date(2027, 1, 31)
        self.assertTrue(sm.im_fenster(date(2027, 5, 31), versand))
        self.assertFalse(sm.im_fenster(date(2027, 6, 1), versand))
        # Versand am 31.10.: vier Monate später ist der 28.2. (Februar kürzer).
        self.assertTrue(sm.im_fenster(date(2027, 2, 28), date(2026, 10, 31)))
        self.assertFalse(sm.im_fenster(date(2027, 3, 1), date(2026, 10, 31)))

    def test_fenster_entspricht_der_definition_fuer_jede_kombination(self):
        """Eigenschaft: im Fenster genau dann, wenn Versand + 4 Monate (Tag geklemmt) den Eintritt erreicht.
        Drei Jahre Eintritte × zwei Jahre Versandtage — sonst prüft man nur die Beispiele."""
        eintritt = date(2026, 12, 1)
        n = 0
        while eintritt < date(2029, 12, 1):
            versand = date(2026, 7, 1)
            while versand < date(2028, 12, 1):
                erwartet = sm.plus_monate(versand, 4) >= eintritt
                self.assertEqual(sm.im_fenster(eintritt, versand), erwartet, (eintritt, versand))
                versand += timedelta(days=3)
                n += 1
            eintritt += timedelta(days=5)
        self.assertGreater(n, 50000)

    def test_erinnerung_kommt_vor_dem_fenster(self):
        self.assertEqual(sm.erinnerung_ab(date(2027, 6, 1)), date(2027, 2, 1) - timedelta(days=sm.VORLAUF_TAGE))


# ---------------------------------------------------------------------------
# Die Stufen
# ---------------------------------------------------------------------------
class StufenTests(TestCase):

    def test_status_wechselt_genau_am_fensterbeginn(self):
        v = _staffel_vertrag()
        vorher = sm.stufen_staende(v, date(2027, 1, 31))[0]
        im_fenster = sm.stufen_staende(v, date(2027, 2, 1))[0]
        self.assertEqual((vorher.status, vorher.kann_erstellen, vorher.kann_versenden),
                         ('noch_nicht', False, False))
        self.assertEqual((im_fenster.status, im_fenster.kann_erstellen, im_fenster.kann_versenden),
                         ('faellig', True, True))

    def test_erhoehung_und_bisher_aus_der_stufenfolge(self):
        v = _staffel_vertrag()
        s1, s2 = sm.stufen_staende(v, date(2027, 1, 1))
        self.assertEqual((s1.bisher, s1.erhoehung, s1.neu), (D('1500.00'), D('50.00'), D('1550.00')))
        self.assertEqual((s2.bisher, s2.erhoehung, s2.neu), (D('1550.00'), D('50.00'), D('1600.00')))

    def test_stufe_ohne_erhoehung_chf_nimmt_die_differenz(self):
        v = _staffel_vertrag(stufen=((date(2027, 6, 1), '1550.00', None),))
        s = sm.stufen_staende(v, date(2027, 1, 1))[0]
        self.assertEqual((s.erhoehung, s.problem), (D('50.00'), ''))

    def test_stufe_die_nicht_erhoeht_hat_ein_problem_und_kein_schreiben(self):
        v = _staffel_vertrag(stufen=((date(2027, 6, 1), '1500.00', None),))
        s = sm.stufen_staende(v, date(2027, 3, 1))[0]
        self.assertIn('Art. 269c OR', s.problem)
        self.assertFalse(s.kann_erstellen)
        self.assertFalse(s.kann_versenden)

    def test_widerspruch_zwischen_erhoehung_und_netto_sperrt(self):
        v = _staffel_vertrag(stufen=((date(2027, 6, 1), '1550.00', '40.00'),))
        s = sm.stufen_staende(v, date(2027, 3, 1))[0]
        self.assertIn('stimmen nicht überein', s.problem)
        self.assertFalse(s.kann_erstellen)

    def test_stufe_die_schon_gilt_bekommt_kein_neues_schreiben(self):
        v = _staffel_vertrag()
        s = sm.stufen_staende(v, date(2027, 7, 1))[0]
        self.assertTrue(s.verstrichen)
        self.assertFalse(s.kann_erstellen)
        self.assertIn('bereits', sm.erstellen_fehler(s.stufe, date(2027, 7, 1)))


# ---------------------------------------------------------------------------
# Schreiben erstellen / als versandt markieren
# ---------------------------------------------------------------------------
class AktionenTests(TestCase):

    def _stufe(self, v, nr=0):
        return v.staffelstufen.order_by('ab_datum')[nr]

    def test_schreiben_vor_dem_fenster_wird_abgelehnt(self):
        v = _staffel_vertrag()
        stufe = self._stufe(v)
        with self.assertRaises(ValueError) as f:
            sm.schreiben_erstellen(stufe, date(2027, 1, 31))              # einen Tag zu früh
        self.assertIn('Art. 19a VMWG', str(f.exception))
        self.assertIn('01.02.2027', str(f.exception))
        stufe.refresh_from_db()
        self.assertIsNone(stufe.mitteilung_erstellt_am)

    def test_schreiben_im_fenster_wird_abgelegt_und_vermerkt(self):
        from rentals.models import Dokument
        v = _staffel_vertrag()
        stufe = self._stufe(v)
        dok = sm.schreiben_erstellen(stufe, date(2027, 2, 1))             # genau am Fensterbeginn
        stufe.refresh_from_db()
        self.assertEqual(stufe.mitteilung_erstellt_am, date(2027, 2, 1))
        self.assertEqual(dok.vertrag_id, v.pk)
        self.assertEqual(dok.bezeichnung, 'Staffelmiete – Mitteilung Erhöhung ab 01.06.2027')
        self.assertEqual(Dokument.objects.filter(vertrag=v).count(), 1)

    def test_pdf_nennt_betraege_zeitpunkt_und_staffel(self):
        v = _staffel_vertrag()
        pdf = sm.schreiben_pdf(self._stufe(v), date(2027, 2, 1))
        text = ' '.join(' '.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(pdf)).pages).split())
        self.assertIn("1'500.00", text)           # bisher
        self.assertIn("50.00", text)              # Erhöhung in CHF
        self.assertIn("1'550.00", text)           # neu
        self.assertIn('01.06.2027', text)         # Zeitpunkt
        self.assertIn('Staffelmiete', text)       # Hinweis auf die Vereinbarung im Vertrag
        self.assertIn('269d Abs. 5', text)
        self.assertIn('kein amtliches Formular', text)

    def test_pdf_folgt_der_sprache_des_mieters(self):
        v = _staffel_vertrag(sprache='fr')
        pdf = sm.schreiben_pdf(self._stufe(v), date(2027, 2, 1))
        text = ' '.join(' '.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(pdf)).pages).split())
        self.assertIn('loyer échelonné', text)
        self.assertNotIn('Neuer Nettomietzins', text)
        self.assertIn('1\'550.00', text)

    def _pdf_text(self, sprache):
        v = _staffel_vertrag(sprache=sprache)
        pdf = sm.schreiben_pdf(v.staffelstufen.order_by('ab_datum')[0], date(2027, 2, 1))
        return ' '.join(' '.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(pdf)).pages).split())

    def test_pdf_italienisch(self):
        text = self._pdf_text('it')
        self.assertIn('pigione scalare', text)
        self.assertNotIn('Neuer Nettomietzins', text)

    def test_pdf_englisch(self):
        text = self._pdf_text('en')
        self.assertIn('graduated rent', text)
        self.assertNotIn('Neuer Nettomietzins', text)

    def test_versand_vor_dem_fenster_wird_abgelehnt(self):
        v = _staffel_vertrag()
        stufe = self._stufe(v)
        with self.assertRaises(ValueError) as f:
            sm.als_versandt_markieren(stufe, date(2027, 1, 31), date(2027, 3, 1))
        self.assertIn('Zu früh versandt', str(f.exception))
        stufe.refresh_from_db()
        self.assertIsNone(stufe.mitteilung_versandt_am)

    def test_versand_ab_fensterbeginn_wird_erfasst(self):
        v = _staffel_vertrag()
        stufe = self._stufe(v)
        sm.als_versandt_markieren(stufe, date(2027, 2, 1), date(2027, 3, 1))
        stufe.refresh_from_db()
        self.assertEqual(stufe.mitteilung_versandt_am, date(2027, 2, 1))

    def test_versand_in_der_zukunft_und_doppelt_wird_abgelehnt(self):
        v = _staffel_vertrag()
        stufe = self._stufe(v)
        with self.assertRaises(ValueError):
            sm.als_versandt_markieren(stufe, date(2027, 3, 2), date(2027, 3, 1))
        with self.assertRaises(ValueError):
            sm.als_versandt_markieren(stufe, None, date(2027, 3, 1))
        sm.als_versandt_markieren(stufe, date(2027, 3, 1), date(2027, 3, 1))
        with self.assertRaises(ValueError):
            sm.als_versandt_markieren(stufe, date(2027, 3, 1), date(2027, 3, 1))

    def test_nicht_staffelvertrag(self):
        v = _staffel_vertrag()
        stufe = self._stufe(v)
        v.mietzins_modell = 'fest'
        v.save()
        stufe = type(stufe).objects.get(pk=stufe.pk)
        self.assertIn('keine Staffelmiete', sm.erstellen_fehler(stufe, date(2027, 3, 1)))
        self.assertIn('keine Staffelmiete', sm.versandt_fehler(stufe, date(2027, 3, 1), date(2027, 3, 1)))


# ---------------------------------------------------------------------------
# Pendenz und täglicher Lauf
# ---------------------------------------------------------------------------
class PendenzTests(TestCase):

    def _pendenzen(self, v):
        from core.models import Pendenz
        return Pendenz.objects.filter(vertrag=v, quelle__startswith='staffel:')

    def test_pendenz_entsteht_erst_mit_dem_vorlauf(self):
        v = _staffel_vertrag()
        beginn = sm.erinnerung_ab(date(2027, 6, 1))
        self.assertEqual(sm.pendenzen_erzeugen(beginn - timedelta(days=1)), 0)      # einen Tag zu früh
        self.assertEqual(self._pendenzen(v).count(), 0)
        self.assertEqual(sm.pendenzen_erzeugen(beginn), 1)                           # genau am Erinnerungstag
        p = self._pendenzen(v).get()
        self.assertEqual(p.faellig_am, date(2027, 2, 1))                             # fällig, wenn das Fenster aufgeht
        self.assertIn("1500", p.beschreibung)
        self.assertIn('Art. 19a VMWG', p.beschreibung)

    def test_zweiter_lauf_legt_kein_doppel_an(self):
        v = _staffel_vertrag()
        tag = date(2027, 2, 1)
        self.assertEqual(sm.pendenzen_erzeugen(tag), 1)
        self.assertEqual(sm.pendenzen_erzeugen(tag), 0)
        self.assertEqual(sm.pendenzen_erzeugen(tag + timedelta(days=1)), 0)
        self.assertEqual(self._pendenzen(v).count(), 1)

    def test_erledigte_pendenz_wird_nicht_wieder_geoeffnet(self):
        v = _staffel_vertrag()
        sm.pendenzen_erzeugen(date(2027, 2, 1))
        p = self._pendenzen(v).get()
        p.erledigt = True
        p.save()
        sm.pendenzen_erzeugen(date(2027, 2, 2))
        p.refresh_from_db()
        self.assertTrue(p.erledigt)
        self.assertEqual(self._pendenzen(v).count(), 1)

    def test_versandt_markieren_erledigt_die_pendenz(self):
        v = _staffel_vertrag()
        sm.pendenzen_erzeugen(date(2027, 2, 1))
        stufe = v.staffelstufen.order_by('ab_datum')[0]
        sm.als_versandt_markieren(stufe, date(2027, 2, 3), date(2027, 2, 3))
        p = self._pendenzen(v).get()
        self.assertTrue(p.erledigt)
        self.assertEqual(p.erledigt_am, date(2027, 2, 3))
        self.assertEqual(sm.pendenzen_erzeugen(date(2027, 2, 4)), 0)                 # versandt: keine neue

    def test_keine_pendenz_fuer_eine_eingetretene_stufe(self):
        v = _staffel_vertrag()
        # Am 1.6.2027 gilt die erste Stufe bereits; die zweite hat ihre Erinnerung erst 2028.
        self.assertEqual(sm.pendenzen_erzeugen(date(2027, 6, 1)), 0)
        self.assertEqual(self._pendenzen(v).count(), 0)

    def test_stufe_ohne_erhoehung_bekommt_keine_pendenz(self):
        v = _staffel_vertrag(stufen=((date(2027, 6, 1), '1500.00', None),))
        self.assertEqual(sm.pendenzen_erzeugen(date(2027, 2, 1)), 0)
        self.assertEqual(self._pendenzen(v).count(), 0)

    def test_nur_staffelvertraege(self):
        v = _staffel_vertrag()
        v.mietzins_modell = 'fest'
        v.save()
        self.assertEqual(sm.pendenzen_erzeugen(date(2027, 2, 1)), 0)

    def test_vertrag_der_vor_der_erhoehung_endet(self):
        v = _staffel_vertrag()
        v.ende = date(2027, 5, 31)
        v.save()
        self.assertEqual(sm.pendenzen_erzeugen(date(2027, 2, 1)), 0)

    def test_ohne_mandantenkontext_wirft_der_manager(self):
        """Der Hook läuft nur im Kontext einer Verwaltung (`taeglicher_lauf._je_verwaltung`)."""
        from core.tenancy import setze_organisation
        _staffel_vertrag()
        setze_organisation(None)
        with self.assertRaises(Exception):
            sm.pendenzen_erzeugen(date(2027, 2, 1))


class TaeglicherLaufTests(TestCase):
    """Der Hook im täglichen Lauf: je Verwaltung, idempotent, mandantengetrennt."""

    @classmethod
    def setUpTestData(cls):
        from core.tenancy import organisation_kontext
        from rentals.models import Staffelstufe
        from ._isolation import MandantenFixture
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        for f in (cls.a, cls.b):
            with organisation_kontext(f.organisation):
                f.vertrag.mietzins_modell = 'staffel'
                f.vertrag.save()
                Staffelstufe.objects.filter(vertrag=f.vertrag).delete()      # das Fixture bringt eine eigene mit
                Staffelstufe.objects.create(vertrag=f.vertrag, ab_datum=date(2027, 6, 1),
                                            netto_mietzins=D('1550.00'), erhoehung_chf=D('50.00'))

    def _lauf(self, tag, **opts):
        with _heute(tag), mock.patch('core.utils.market_data.fetch_market_rates', return_value=({}, [])):
            aus = io.StringIO()
            call_command('taeglicher_lauf', digest_weekday=-1, stdout=aus, stderr=aus, **opts)
        self.aus = aus.getvalue()
        return self.aus

    def _erwarte(self, a, b):
        self.assertEqual((self._anzahl(self.a), self._anzahl(self.b)), (a, b), getattr(self, 'aus', ''))

    def _anzahl(self, fixture):
        from core.models import Pendenz
        from core.tenancy import organisation_kontext
        with organisation_kontext(fixture.organisation):
            return Pendenz.objects.filter(quelle__startswith='staffel:').count()

    def test_lauf_legt_je_verwaltung_eine_pendenz_an(self):
        self._lauf(date(2027, 2, 1))
        self._erwarte(1, 1)

    def test_zweiter_lauf_ist_idempotent(self):
        self._lauf(date(2027, 2, 1))
        self._lauf(date(2027, 2, 1))
        self._lauf(date(2027, 2, 2))
        self._erwarte(1, 1)

    def test_lauf_fuer_eine_verwaltung_beruehrt_die_andere_nicht(self):
        """Mandantentrennung: Nachlauf für A (`--organisation`) legt für B nichts an."""
        self._lauf(date(2027, 2, 1), organisation=self.a.organisation.pk)
        self._erwarte(1, 0)

    def test_vor_dem_vorlauf_nichts(self):
        self._lauf(sm.erinnerung_ab(date(2027, 6, 1)) - timedelta(days=1))
        self._erwarte(0, 0)

    def test_pendenz_liegt_in_der_richtigen_verwaltung(self):
        from core.models import Pendenz
        from core.tenancy import organisation_kontext
        self._lauf(date(2027, 2, 1))
        with organisation_kontext(self.a.organisation):
            p = Pendenz.objects.get(quelle__startswith='staffel:')
            self.assertEqual(p.vertrag_id, self.a.vertrag.pk)
        with organisation_kontext(self.b.organisation):
            p = Pendenz.objects.get(quelle__startswith='staffel:')
            self.assertEqual(p.vertrag_id, self.b.vertrag.pk)


# ---------------------------------------------------------------------------
# Die Vertragsakte
# ---------------------------------------------------------------------------
class AkteTests(TestCase):

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user())

    def _akte(self, v, tag):
        with _heute(tag):
            return self.c.get(f'/neu/vertraege/{v.pk}/')

    def _post(self, url, tag, **daten):
        with _heute(tag):
            return self.c.post(url, daten, follow=True)

    def _meldungen(self, r):
        return ' | '.join(str(m) for m in r.context['messages'])

    def test_status_je_stufe(self):
        v = _staffel_vertrag()
        r = self._akte(v, date(2027, 2, 1))
        body = r.content.decode()
        self.assertEqual([z['s'].status for z in r.context['staffel_mitteilungen']], ['faellig', 'noch_nicht'])
        for text in ('Mitteilung fällig', 'noch nicht im Fenster', 'Schreiben erstellen', 'Als versandt markieren'):
            self.assertIn(text, body)

    def test_nur_eine_staffel_zeigt_die_karte(self):
        v = _staffel_vertrag()
        v.mietzins_modell = 'fest'
        v.save()
        self.assertNotIn('vt-staffel-mitteilungen', self._akte(v, date(2027, 2, 1)).content.decode())

    def test_vor_dem_fenster_bietet_die_akte_keine_aktion(self):
        v = _staffel_vertrag()
        body = self._akte(v, date(2027, 1, 31)).content.decode()
        self.assertNotIn('Schreiben erstellen', body)
        self.assertNotIn('Als versandt markieren', body)

    def test_erstellen_ueber_die_ansicht_und_status_erstellt(self):
        v = _staffel_vertrag()
        stufe = v.staffelstufen.order_by('ab_datum')[0]
        r = self._post(f'/neu/staffel/{stufe.pk}/mitteilung/', date(2027, 2, 1))
        self.assertIn('erstellt und in der Akte abgelegt', self._meldungen(r))
        stufe.refresh_from_db()
        self.assertEqual(stufe.mitteilung_erstellt_am, date(2027, 2, 1))
        akte = self._akte(v, date(2027, 2, 1))
        self.assertEqual(akte.context['staffel_mitteilungen'][0]['s'].status, 'erstellt')
        self.assertIsNotNone(akte.context['staffel_mitteilungen'][0]['dokument'])

    def test_erstellen_vor_dem_fenster_wird_abgelehnt(self):
        v = _staffel_vertrag()
        stufe = v.staffelstufen.order_by('ab_datum')[0]
        r = self._post(f'/neu/staffel/{stufe.pk}/mitteilung/', date(2027, 1, 31))
        self.assertIn('Zu früh', self._meldungen(r))
        stufe.refresh_from_db()
        self.assertIsNone(stufe.mitteilung_erstellt_am)

    def test_versandt_ueber_die_ansicht(self):
        v = _staffel_vertrag()
        stufe = v.staffelstufen.order_by('ab_datum')[0]
        r = self._post(f'/neu/staffel/{stufe.pk}/mitteilung/versandt/', date(2027, 2, 10), versandt_am='2027-02-08')
        self.assertIn('als versandt markiert', self._meldungen(r))
        stufe.refresh_from_db()
        self.assertEqual(stufe.mitteilung_versandt_am, date(2027, 2, 8))
        self.assertEqual(self._akte(v, date(2027, 2, 10)).context['staffel_mitteilungen'][0]['s'].status, 'versandt')

    def test_versandt_vor_dem_fenster_ueber_die_ansicht_wird_abgelehnt(self):
        v = _staffel_vertrag()
        stufe = v.staffelstufen.order_by('ab_datum')[0]
        r = self._post(f'/neu/staffel/{stufe.pk}/mitteilung/versandt/', date(2027, 2, 10), versandt_am='2027-01-31')
        self.assertIn('Zu früh versandt', self._meldungen(r))
        stufe.refresh_from_db()
        self.assertIsNone(stufe.mitteilung_versandt_am)

    def test_get_aendert_nichts(self):
        v = _staffel_vertrag()
        stufe = v.staffelstufen.order_by('ab_datum')[0]
        with _heute(date(2027, 2, 1)):
            for url in (f'/neu/staffel/{stufe.pk}/mitteilung/', f'/neu/staffel/{stufe.pk}/mitteilung/versandt/'):
                self.assertEqual(self.c.get(url).status_code, 302)
        stufe.refresh_from_db()
        self.assertIsNone(stufe.mitteilung_erstellt_am)
        self.assertIsNone(stufe.mitteilung_versandt_am)

    def test_lesezugriff_darf_nicht_schreiben(self):
        v = _staffel_vertrag()
        stufe = v.staffelstufen.order_by('ab_datum')[0]
        c = Client()
        c.force_login(_team_user('Lesend'))
        with _heute(date(2027, 2, 1)):
            self.assertEqual(c.post(f'/neu/staffel/{stufe.pk}/mitteilung/').status_code, 403)
            self.assertEqual(c.post(f'/neu/staffel/{stufe.pk}/mitteilung/versandt/').status_code, 403)
        stufe.refresh_from_db()
        self.assertIsNone(stufe.mitteilung_erstellt_am)

    def test_fremde_stufe_ergibt_404(self):
        """Mandantentrennung: Die Stufe einer anderen Verwaltung ist nicht erreichbar."""
        from core.tenancy import organisation_kontext
        from rentals.models import Staffelstufe
        from ._isolation import MandantenFixture
        a = MandantenFixture('A', '8000', 'Zürich')
        b = MandantenFixture('B', '3000', 'Bern')
        with organisation_kontext(b.organisation):
            fremd = Staffelstufe.objects.create(vertrag=b.vertrag, ab_datum=date(2027, 6, 1),
                                                netto_mietzins=D('1550'), erhoehung_chf=D('50'))
        c = Client()
        c.force_login(a.benutzer)
        with _heute(date(2027, 2, 1)):
            self.assertEqual(c.post(f'/neu/staffel/{fremd.pk}/mitteilung/').status_code, 404)
            self.assertEqual(c.post(f'/neu/staffel/{fremd.pk}/mitteilung/versandt/').status_code, 404)
            self.assertEqual(c.get(f'/neu/staffel/{fremd.pk}/mitteilung/').status_code, 404)
        with organisation_kontext(b.organisation):
            fremd.refresh_from_db()
            self.assertIsNone(fremd.mitteilung_erstellt_am)
            self.assertIsNone(fremd.mitteilung_versandt_am)

    def test_allgemeine_dokumentansicht_bietet_das_schreiben_nicht_an(self):
        """Ohne Stufe käme ein leeres Schreiben heraus — die allgemeine Ansicht lehnt den Typ ab."""
        v = _staffel_vertrag()
        self.assertEqual(self.c.get(f'/vertrag/{v.pk}/dokument/staffel-mitteilung/').status_code, 404)
