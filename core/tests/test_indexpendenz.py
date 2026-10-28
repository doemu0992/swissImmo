"""Die Indexpendenz nennt die Frist der Indexmiete: Art. 17 Abs. 3 VMWG.

DER BEFUND (28.10.2026)

`core/services/automation.py` rechnete die Pendenz «Indexmiete anpassen» mit
`mietzins_zustellung()` aus dem Regelwerk: Beginn der Kündigungsfrist minus
zehn Tage (Art. 269d OR), dazu der Satz «Später zugestellt ist die Erhöhung
nichtig». Für die Indexmiete gilt aber die Verordnung: Ankündigung mit
mindestens 30 Tagen auf ein Monatsende (Art. 17 Abs. 3 VMWG), das amtliche
Formular sinngemäss (Art. 19 Abs. 2 VMWG), und die Mitteilung erst nach der
Bekanntgabe des neuen Indexstandes. Die Pendenz nannte damit einen Tag, der
Monate vom richtigen entfernt lag, und eine Rechtsfolge, die für diesen Weg
nicht belegt ist.

Gerechnet wird jetzt mit derselben Funktion wie im Assistenten
(`core/services/index_anpassung.py`): `spaetester_zugang` ist die Umkehrung von
`frueheste_wirksamkeit`. Die Tests unten lesen die erzeugte Pendenz, nicht den
Quelltext.
"""
import re
from datetime import date, timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from core.services import index_anpassung as ia


def _datum(text):
    tag, monat, jahr = (int(t) for t in text.split('.'))
    return date(jahr, monat, tag)


class SpaetesterZugangTest(SimpleTestCase):
    """Die Umkehrung der Fristrechnung des Assistenten, an Randfällen."""

    def test_umkehrung_fuer_jeden_monatsersten_eines_jahres(self):
        """Wer am spätesten Versandtag verschickt, erreicht den Termin — ein Tag später nicht.

        Gegenprobe im selben Test: der Tag danach führt zu einem späteren Termin.
        Deckt Schaltjahr (2028) und alle Monatslängen ab."""
        for jahr in (2027, 2028):
            for monat in range(1, 13):
                termin = date(jahr, monat, 1)
                versand = ia.spaetester_versand(termin)
                self.assertEqual(ia.frueheste_wirksamkeit(versand), termin, termin)
                self.assertGreater(ia.frueheste_wirksamkeit(versand + timedelta(days=1)), termin, termin)

    def test_zugang_dreissig_tage_vor_dem_monatsende(self):
        # Termin 1.4.2027, Monatsende 31.3.2027: 30 Tage davor ist der 1.3.2027.
        self.assertEqual(ia.spaetester_zugang(date(2027, 4, 1)), date(2027, 3, 1))
        # Der 2.3. wäre zu spät: 30 Tage später liegt im April, das Monatsende am 30.4.
        self.assertEqual(ia.fruehestes_monatsende(date(2027, 3, 2)), date(2027, 4, 30))
        self.assertEqual(ia.fruehestes_monatsende(date(2027, 3, 1)), date(2027, 3, 31))

    def test_februar_und_schaltjahr(self):
        self.assertEqual(ia.spaetester_zugang(date(2027, 3, 1)), date(2027, 1, 29))
        self.assertEqual(ia.spaetester_zugang(date(2028, 3, 1)), date(2028, 1, 30))

    def test_versand_ist_zugang_minus_puffer(self):
        termin = date(2027, 4, 1)
        self.assertEqual(ia.spaetester_versand(termin, puffer_tage=0), ia.spaetester_zugang(termin))
        self.assertEqual(ia.spaetester_versand(termin, puffer_tage=7), date(2027, 2, 22))

    def test_termin_ab(self):
        self.assertEqual(ia.termin_ab(date(2027, 4, 1)), date(2027, 4, 1))
        self.assertEqual(ia.termin_ab(date(2027, 4, 2)), date(2027, 5, 1))
        self.assertEqual(ia.termin_ab(date(2027, 12, 31)), date(2028, 1, 1))


class IndexpendenzWirdErzeugtTest(TestCase):
    """Die Pendenz wird ERZEUGT und gelesen, nicht der Quelltext."""

    def _vertrag(self, letzte_anpassung=None, basis='100.0', frist_monate=3):
        from ._helfer import _basis_objekte

        lg, e, m, v = _basis_objekte()
        v.mietzins_modell = 'index'
        v.basis_lik_punkte = Decimal(basis)
        v.index_intervall_monate = 12
        # Der nächste Termin muss in der ZUKUNFT liegen, sonst klemmt
        # `max(versand_spaet, heute)` die Fälligkeit auf heute.
        v.index_letzte_anpassung = letzte_anpassung or date.today() - timedelta(days=200)
        v.kuendigungsfrist_monate = frist_monate
        v.save()
        return v

    def _pendenz(self, vertrag, praefix='auto:index:'):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen

        generate_auto_pendenzen(horizont_tage=365)
        return Pendenz.objects.filter(quelle__startswith=f'{praefix}{vertrag.id}:').first()

    def _termin(self, pendenz):
        treffer = re.search(r'auf (\d{2}\.\d{2}\.\d{4})', pendenz.beschreibung)
        self.assertIsNotNone(treffer, pendenz.beschreibung)
        return _datum(treffer.group(1))

    def test_der_text_nennt_art_17_abs_3_und_keine_nichtigkeit(self):
        pendenz = self._pendenz(self._vertrag())
        self.assertIsNotNone(pendenz, 'Es entsteht gar keine Indexpendenz — dann prüft der Rest hier nichts.')
        text = pendenz.beschreibung
        self.assertIn('Zugang spätestens bis', text)
        self.assertIn('30 Tage vor dem Monatsende', text)
        self.assertIn('Art. 17 Abs. 3 VMWG', text)
        self.assertIn('Amtliches Formular', text)
        self.assertIn('erst nach Bekanntgabe des neuen Indexstandes', text)
        # Gegenprobe zum Befund: nichts mehr von Art. 269d, Kündigungsfrist, Nichtigkeit.
        for alt in ('nichtig', 'Art. 269d', 'Kündigungsfrist', 'zehn Tage', 'beim Mieter sein'):
            self.assertNotIn(alt, text)

    def test_zugang_und_faelligkeit_sind_die_umkehrung_des_assistenten(self):
        """Das Datum im Text ist `spaetester_zugang(termin)`, die Fälligkeit der späteste Versand.

        Und: Versand an diesem Tag erreicht den Termin nach der Rechnung des
        Assistenten (`frueheste_wirksamkeit`), ein Tag später nicht."""
        pendenz = self._pendenz(self._vertrag())
        termin = self._termin(pendenz)
        self.assertEqual(termin.day, 1)
        zugang = re.search(r'Zugang spätestens bis (\d{2}\.\d{2}\.\d{4})', pendenz.beschreibung)
        self.assertEqual(_datum(zugang.group(1)), ia.spaetester_zugang(termin))
        self.assertEqual(pendenz.faellig_am, ia.spaetester_versand(termin))
        self.assertEqual(ia.frueheste_wirksamkeit(pendenz.faellig_am), termin)
        self.assertGreater(ia.frueheste_wirksamkeit(pendenz.faellig_am + timedelta(days=1)), termin)
        self.assertLess(pendenz.faellig_am, termin)

    def test_die_kuendigungsfrist_des_vertrags_ist_ohne_einfluss(self):
        """Art. 17 Abs. 3 kennt die Kündigungsfrist nicht. Gegenprobe zum alten Verhalten:
        dort verschob sich die Fälligkeit mit `kuendigungsfrist_monate`."""
        ref = date.today() - timedelta(days=200)
        a = self._pendenz(self._vertrag(letzte_anpassung=ref, frist_monate=3))
        faellig_a, text_a = a.faellig_am, a.beschreibung
        b = self._pendenz(self._vertrag(letzte_anpassung=ref, frist_monate=1))
        self.assertEqual(b.faellig_am, faellig_a)
        c = self._pendenz(self._vertrag(letzte_anpassung=ref, frist_monate=-1))
        self.assertEqual(c.faellig_am, faellig_a)
        self.assertEqual(re.sub(r'\d{2}\.\d{2}\.\d{4}', 'D', b.beschreibung), re.sub(r'\d{2}\.\d{2}\.\d{4}', 'D', text_a))

    def test_termin_mitten_im_monat_wird_der_erste_des_folgemonats(self):
        heute = date.today()
        ziel = ia.plus_monate(date(heute.year, heute.month, 15), 5)       # der 15., fünf Monate voraus
        pendenz = self._pendenz(self._vertrag(letzte_anpassung=ia.plus_monate(ziel, -12)))
        self.assertIsNotNone(pendenz)
        self.assertEqual(self._termin(pendenz), ia.termin_ab(ziel))
        self.assertEqual(self._termin(pendenz).day, 1)

    def test_verpasste_frist_faellt_auf_heute_und_nennt_den_fruehesten_termin(self):
        heute = date.today()
        # Termin in zehn Tagen: der späteste Versand liegt Wochen zurück.
        pendenz = self._pendenz(self._vertrag(letzte_anpassung=ia.plus_monate(heute + timedelta(days=10), -12)))
        self.assertIsNotNone(pendenz)
        self.assertEqual(pendenz.faellig_am, heute)
        self.assertIn('reicht die Frist bei Versand heute nicht mehr', pendenz.beschreibung)
        self.assertIn(f"frühester Termin bei Versand heute: {ia.frueheste_wirksamkeit(heute).strftime('%d.%m.%Y')}",
                      pendenz.beschreibung)

    def test_rechtzeitige_pendenz_hat_keinen_verspaetungshinweis(self):
        """Gegenprobe zum vorigen Test."""
        pendenz = self._pendenz(self._vertrag())
        self.assertNotIn('reicht die Frist', pendenz.beschreibung)

    def test_senkung_hat_dieselbe_frist(self):
        pendenz = self._pendenz(self._vertrag(basis='999.0'), praefix='auto:indexsenkung:')
        self.assertIsNotNone(pendenz, 'Bei sinkendem LIK entsteht keine Senkungspendenz.')
        self.assertTrue(pendenz.titel.startswith('Indexmiete senken'))
        termin = self._termin(pendenz)
        self.assertIn('Art. 17 Abs. 2 VMWG', pendenz.beschreibung)
        self.assertIn('Art. 17 Abs. 3 VMWG', pendenz.beschreibung)
        self.assertEqual(pendenz.faellig_am, ia.spaetester_versand(termin))
        self.assertNotIn('Art. 269', pendenz.beschreibung)

    def test_langer_titel_wird_auf_die_feldlaenge_gelegt(self):
        """PostgreSQL lehnt einen Text über `max_length` ab; SQLite schweigt dazu."""
        from core.models import Pendenz

        v = self._vertrag()
        m = v.mieter
        m.typ = 'firma'
        m.firmen_name = 'X' * 200
        m.save()
        pendenz = self._pendenz(v)
        self.assertIsNotNone(pendenz)
        self.assertEqual(len(pendenz.titel), Pendenz._meta.get_field('titel').max_length)

    def test_kein_lik_anstieg_keine_pendenz(self):
        """Gegenprobe: ohne Veränderung des Index entsteht nichts."""
        from core.services.lik import aktueller_lik_wert

        _stand, pkt, _b = aktueller_lik_wert(live=False)
        v = self._vertrag(basis=str(pkt))
        self.assertIsNone(self._pendenz(v))
        self.assertIsNone(self._pendenz(v, praefix='auto:indexsenkung:'))
