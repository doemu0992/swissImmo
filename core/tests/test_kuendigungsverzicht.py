"""Kündigungsverzicht und Befristung sperren die ordentliche Kündigung durch den Vermieter (28.10.2026).

Gesperrt ist nur diese eine Kündigung. Die des Mieters und die ausserordentlichen (Art. 257d, 257f, 266g,
266h OR) bleiben möglich. Jeder Test hat seine Gegenprobe im selben Test: dieselbe Kündigung, einen Tag
später oder von der anderen Partei, wird erfasst. Ohne sie bliebe der Test auch grün, wenn immer abgelehnt würde.
"""
import calendar
from datetime import date, timedelta

from django.test import Client, SimpleTestCase, TestCase
from django.utils import timezone

from core.services.kuendigungsverzicht import fest_bis_von, sperre_text

from ._helfer import _basis_objekte, _team_user


def _monatsende(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _kuendigungsmonat_ende(heute, monate_voraus):
    """Ein Monatsende in `monate_voraus` Monaten, nie Dezember («Ende jedes Monats ausser Dezember»)."""
    m0 = heute.month - 1 + monate_voraus
    jahr, monat = heute.year + m0 // 12, m0 % 12 + 1
    if monat == 12:
        monat = 1
        jahr += 1
    return _monatsende(date(jahr, monat, 1))


class _Stub:
    """Ein Vertrag mit den vier Feldern, die `fest_bis` liest."""
    def __init__(self, beginn=date(2024, 1, 1), ende=None, ist_befristet=False, vermieter_kuendigungsverzicht_bis=None):
        self.beginn, self.ende, self.ist_befristet = beginn, ende, ist_befristet
        self.vermieter_kuendigungsverzicht_bis = vermieter_kuendigungsverzicht_bis


class SperreTextTests(SimpleTestCase):
    def test_ende_inklusive_ein_tag_davor_gesperrt(self):
        v = _Stub(vermieter_kuendigungsverzicht_bis=date(2029, 12, 31))
        gesperrt = sperre_text(v, date(2029, 12, 30), absender='vermieter', ausserordentlich=False)
        self.assertIn('31.12.2029', gesperrt)
        self.assertIn('Art. 17 Abs. 4 VMWG', gesperrt)
        self.assertIn('30.12.2029', gesperrt)
        # Gegenprobe: genau am Datum und danach ist die Kündigung zulässig.
        self.assertEqual(sperre_text(v, date(2029, 12, 31), absender='vermieter', ausserordentlich=False), '')
        self.assertEqual(sperre_text(v, date(2030, 3, 31), absender='vermieter', ausserordentlich=False), '')

    def test_befristet_nennt_ende_und_art_266(self):
        v = _Stub(ende=date(2027, 6, 30), ist_befristet=True)
        text = sperre_text(v, date(2027, 3, 31), absender='vermieter', ausserordentlich=False)
        self.assertIn('30.06.2027', text)
        self.assertIn('Art. 266 OR', text)
        self.assertEqual(sperre_text(v, date(2027, 6, 30), absender='vermieter', ausserordentlich=False), '')

    def test_mieter_und_ausserordentliche_sind_nie_gesperrt(self):
        v = _Stub(vermieter_kuendigungsverzicht_bis=date(2029, 12, 31))
        frueh = date(2026, 12, 31)
        self.assertNotEqual(sperre_text(v, frueh, absender='vermieter', ausserordentlich=False), '')   # Gegenprobe
        self.assertEqual(sperre_text(v, frueh, absender='mieter', ausserordentlich=False), '')
        # Welcher Grund (257d, 257f, 266g, 266h) gilt, ändert nichts: Massgebend ist nur das Kennzeichen
        # `ausserordentlich`; die Gründe selbst prüft `rentals.services.AO_GRUENDE_VERMIETER` beim Erfassen.
        self.assertEqual(sperre_text(v, frueh, absender='vermieter', ausserordentlich=True), '')

    def test_ende_bei_unbefristetem_vertrag_stammt_aus_einer_kuendigung(self):
        """Ein `ende` ohne Befristung macht den Vertrag nicht fest."""
        v = _Stub(ende=date(2030, 1, 31), ist_befristet=False)
        self.assertEqual(fest_bis_von(v), (None, ''))
        self.assertEqual(sperre_text(v, date(2026, 12, 31), absender='vermieter', ausserordentlich=False), '')

    def test_ohne_verzicht_und_vergangener_verzicht_sperren_nichts(self):
        heute = timezone.localdate()
        self.assertEqual(sperre_text(_Stub(), heute, absender='vermieter', ausserordentlich=False), '')
        alt = _Stub(vermieter_kuendigungsverzicht_bis=heute - timedelta(days=30))
        self.assertEqual(sperre_text(alt, heute, absender='vermieter', ausserordentlich=False), '')

    def test_die_meldung_ist_uebersetzt(self):
        """Die Meldungen stehen in fr, it und en im Katalog (sonst bliebe der Text deutsch)."""
        from django.utils import translation
        v = _Stub(vermieter_kuendigungsverzicht_bis=date(2029, 12, 31))
        b = _Stub(ende=date(2027, 6, 30), ist_befristet=True)
        erwartet = {'fr': ('OBLF', 'CO'), 'it': ('OLAL', 'CO'), 'en': ('VMWG', 'CO')}
        for sprache, (marke, _co) in erwartet.items():
            with self.subTest(sprache=sprache), translation.override(sprache):
                text = sperre_text(v, date(2029, 1, 1), absender='vermieter', ausserordentlich=False)
                self.assertIn(marke, text)
                self.assertNotIn('Kündigung', text)
                text = sperre_text(b, date(2027, 1, 1), absender='vermieter', ausserordentlich=False)
                self.assertNotIn('Kündigung', text)

    def test_ohne_wirkungsdatum_nichts_zu_pruefen(self):
        v = _Stub(vermieter_kuendigungsverzicht_bis=date(2029, 12, 31))
        self.assertEqual(sperre_text(v, None, absender='vermieter', ausserordentlich=False), '')


class KuendigungErfassenTests(TestCase):
    def setUp(self):
        _lg, _e, _m, self.v = _basis_objekte()      # Wohnung, 3 Monate, Ende jedes Monats ausser Dezember
        self.c = Client()
        self.c.force_login(_team_user('Verwaltung'))
        self.heute = timezone.localdate()
        self.bis = _kuendigungsmonat_ende(self.heute, 9)
        self.v.vermieter_kuendigungsverzicht_bis = self.bis
        self.v.save()

    def post(self, **daten):
        daten.setdefault('eingang_datum', self.heute.isoformat())
        return self.c.post(f'/neu/vertraege/{self.v.id}/kuendigen/', daten, follow=True)

    def anzahl(self):
        from rentals.models import Kuendigung
        return Kuendigung.objects.filter(vertrag=self.v).count()

    def meldungen(self, antwort):
        return ' '.join(str(m) for m in antwort.context['messages'])

    def test_ordentliche_vermieterkuendigung_vor_dem_verzicht_wird_nicht_erfasst(self):
        antwort = self.post(absender='vermieter')       # frühester Termin: in rund vier Monaten, also vor `bis`
        self.assertEqual(self.anzahl(), 0)
        self.v.refresh_from_db()
        self.assertEqual(self.v.status, 'aktiv')
        text = self.meldungen(antwort)
        self.assertIn(self.bis.strftime('%d.%m.%Y'), text)
        self.assertIn('Art. 17 Abs. 4 VMWG', text)

    def test_wunschdatum_am_verzichtsdatum_ist_zulaessig_ein_tag_davor_nicht(self):
        gestern = self.bis - timedelta(days=1)
        self.post(absender='vermieter', gewuenschtes_ende=gestern.isoformat())
        self.assertEqual(self.anzahl(), 0)
        self.post(absender='vermieter', gewuenschtes_ende=self.bis.isoformat())
        self.assertEqual(self.anzahl(), 1)
        from rentals.models import Kuendigung
        self.assertEqual(Kuendigung.objects.get(vertrag=self.v).per_datum, self.bis)

    def test_kuendigung_durch_den_mieter_bleibt_moeglich(self):
        self.post(absender='mieter')
        self.assertEqual(self.anzahl(), 1)

    def test_ausserordentliche_vermieterkuendigung_bleibt_moeglich(self):
        """266g (wichtige Gründe): Der Verzicht hindert sie nicht. Mit gewünschtem Ende, weil die Anwendung
        für diesen Grund keine Frist rechnet."""
        wunsch = (self.heute + timedelta(days=60)).isoformat()
        self.post(absender='vermieter', ausserordentlich='on', ausserordentlich_art='266g',
                  gewuenschtes_ende=wunsch)
        self.assertEqual(self.anzahl(), 1)

    def test_befristeter_vertrag_sperrt_die_ordentliche_vermieterkuendigung(self):
        self.v.vermieter_kuendigungsverzicht_bis = None
        self.v.ist_befristet = True
        self.v.ende = self.bis
        self.v.save()
        antwort = self.post(absender='vermieter')
        self.assertEqual(self.anzahl(), 0)
        text = self.meldungen(antwort)
        self.assertIn('Art. 266 OR', text)
        self.assertIn(self.bis.strftime('%d.%m.%Y'), text)
        # Gegenprobe: dieselbe Kündigung beim unbefristeten Vertrag ohne Verzicht.
        self.v.ist_befristet = False
        self.v.ende = None
        self.v.save()
        self.post(absender='vermieter')
        self.assertEqual(self.anzahl(), 1)

    def test_vertrag_ohne_verzicht_ist_unberuehrt(self):
        self.v.vermieter_kuendigungsverzicht_bis = None
        self.v.save()
        self.post(absender='vermieter')
        self.assertEqual(self.anzahl(), 1)
