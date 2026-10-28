"""Befristete Verträge (MIET-07) und gesetzliche Mindestkündigungsfrist (MIET-08).

MIET-07 — Art. 266 Abs. 1 OR: Ein befristeter Mietvertrag endet ohne Kündigung mit Ablauf der Dauer. Eine ordentliche
Kündigung gibt es nur, wenn der Vertrag sie vorsieht (Feld «Erstmals kündbar auf»). Früher ausziehen kann der Mieter nur
über Art. 264 OR (Ersatzmieter), sonst schuldet er den Mietzins bis zum Vertragsende. Die Kündigung des
Vermieters mit Wirkung VOR dem Ende sperrt schon der Kündigungsverzicht (`kuendigungsverzicht.sperre_text`, PR #139);
neu ist: auch eine Kündigung auf oder nach dem Ende wird nicht erfasst, denn sie würde `Mietvertrag.ende` auf ein
Datum setzen, das es nicht gibt.

MIET-08 — Art. 266a Abs. 1 und 2, 266b–266d OR: Die gesetzlichen Fristen (Wohnungen 3, Geschäftsräume 6 Monate)
sind Mindestfristen; eine kürzere vereinbarte Frist gilt nicht, die Kündigung gilt auf den nächstmöglichen Termin.
Die Terminberechnung rechnet darum mit max(vertraglich, gesetzlich); die Maske für Vertrag erfassen/bearbeiten lehnt
eine zu kurze Frist ab; Altverträge werden nicht blockiert.

Jeder Test hat seine Gegenprobe.
"""
from datetime import date

from django.contrib.messages import get_messages
from django.test import Client, SimpleTestCase, TestCase

from rentals.models import Kuendigung
from rentals.services import (berechne_kuendigungstermin, gesetzliche_frist_fuer_einheit,
                              kuendigungsfrist_fehler)

from ._helfer import _basis_objekte, _team_user
from ._uhr import bei_stichtag

HEUTE = date(2026, 11, 4)      # Mittwoch


class _Einheit:
    def __init__(self, kategorie, einstellplatz=False):
        self.mietrecht_kategorie, self.ist_einstellplatz = kategorie, einstellplatz


class MindestfristFunktionenTests(SimpleTestCase):
    def test_gesetzliche_frist_je_objektart(self):
        self.assertEqual(gesetzliche_frist_fuer_einheit(_Einheit('wohnen')), 3)
        self.assertEqual(gesetzliche_frist_fuer_einheit(_Einheit('gewerbe')), 6)
        self.assertEqual(gesetzliche_frist_fuer_einheit(_Einheit('nebenobjekt')), 3)
        self.assertEqual(gesetzliche_frist_fuer_einheit(_Einheit('nebenobjekt', einstellplatz=True)), 0)

    def test_fehler_unter_der_gesetzlichen_frist(self):
        text = kuendigungsfrist_fehler('2', _Einheit('wohnen'))
        self.assertIn('mindestens 3 Monate', text)
        self.assertIn('Art. 266c OR', text)
        self.assertIn('Art. 266a Abs. 2 OR', text)
        self.assertIn('Art. 266d OR', kuendigungsfrist_fehler(5, _Einheit('gewerbe')))
        # Gegenprobe: genau die gesetzliche Frist und längere sind in Ordnung.
        self.assertEqual(kuendigungsfrist_fehler(3, _Einheit('wohnen')), '')
        self.assertEqual(kuendigungsfrist_fehler(6, _Einheit('gewerbe')), '')
        self.assertEqual(kuendigungsfrist_fehler(12, _Einheit('gewerbe')), '')

    def test_leer_unlesbar_und_einstellplatz_sind_kein_fehler(self):
        self.assertEqual(kuendigungsfrist_fehler('', _Einheit('wohnen')), '')
        self.assertEqual(kuendigungsfrist_fehler(None, _Einheit('wohnen')), '')
        self.assertEqual(kuendigungsfrist_fehler('abc', _Einheit('wohnen')), '')
        self.assertEqual(kuendigungsfrist_fehler(1, _Einheit('nebenobjekt', einstellplatz=True)), '')

    def test_meldung_ist_uebersetzt(self):
        from django.utils import translation
        for sprache in ('fr', 'it', 'en'):
            with self.subTest(sprache=sprache), translation.override(sprache):
                self.assertNotIn('Kündigungsfrist', kuendigungsfrist_fehler(2, _Einheit('wohnen')))


class TerminBerechnungTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()      # Wohnung, 3 Monate, Ende jedes Monats ausser Dezember

    def test_zu_kurze_vertragsfrist_wird_auf_die_gesetzliche_angehoben(self):
        eingang = date(2026, 1, 10)
        normal = berechne_kuendigungstermin(self.v, eingang)
        self.v.kuendigungsfrist_monate = 1
        self.assertEqual(berechne_kuendigungstermin(self.v, eingang), normal)
        # Gegenprobe: eine LÄNGERE vereinbarte Frist gilt (Art. 266a Abs. 1 OR).
        self.v.kuendigungsfrist_monate = 6
        self.assertGreater(berechne_kuendigungstermin(self.v, eingang), normal)

    def test_gewerbe_hat_sechs_monate_auch_bei_vertragswert_drei(self):
        from portfolio.models import Einheit
        gew = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='Laden', typ='gew')
        self.v.einheit = gew
        self.v.kuendigungsfrist_monate = 3
        eingang = date(2026, 1, 10)        # + 6 Monate = 10.7. -> nächster erlaubter Termin: 31.7.
        self.assertEqual(berechne_kuendigungstermin(self.v, eingang), date(2026, 7, 31))
        # Gegenprobe: Wohnung mit drei Monaten -> 10.4. -> 30.4.
        self.v.einheit = self.e
        self.assertEqual(berechne_kuendigungstermin(self.v, eingang), date(2026, 4, 30))

    def test_einstellplatz_behaelt_die_zwei_wochen(self):
        from portfolio.models import Einheit
        pp = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='P1', typ='pp')
        self.v.einheit = pp
        self.v.kuendigungsfrist_monate = 0
        self.assertEqual(berechne_kuendigungstermin(self.v, date(2026, 1, 10)), date(2026, 1, 31))
        # Gegenprobe: eine vereinbarte Monatsfrist gilt weiter.
        self.v.kuendigungsfrist_monate = 2
        self.assertEqual(berechne_kuendigungstermin(self.v, date(2026, 1, 10)), date(2026, 3, 31))

    def test_regelwerk_rechnet_mit_der_gesetzlichen_mindestfrist(self):
        from unittest import mock

        from core.views.fw.regelwerk import pruefung_zum_vertrag
        from faelle.regelwerk import Befund
        with mock.patch('faelle.regelwerk.pruefen', return_value=(Befund(ok=True), None)) as pruefen:
            self.v.kuendigungsfrist_monate = 1
            pruefung_zum_vertrag(self.v, date(2026, 1, 10), protokollieren=False)
            self.assertEqual(pruefen.call_args.kwargs['frist_monate'], 3)
            # Gegenprobe: eine längere Vertragsfrist bleibt.
            self.v.kuendigungsfrist_monate = 4
            pruefung_zum_vertrag(self.v, date(2026, 1, 10), protokollieren=False)
            self.assertEqual(pruefen.call_args.kwargs['frist_monate'], 4)


class VertragsmaskeTests(TestCase):
    """Vertrag bearbeiten (Formular) und Vertrag erfassen (Assistent) lehnen eine zu kurze Frist ab."""

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()

    def _form(self, vertrag, frist):
        from rentals.forms import VertragBearbeitenForm
        return VertragBearbeitenForm({'kuendigungsfrist': str(frist), 'anzahl_personen': '1'},
                                     entwurf=False, beginn=vertrag.beginn, vertrag=vertrag)

    def test_bearbeiten_lehnt_zu_kurze_frist_ab(self):
        form = self._form(self.v, 2)
        self.assertFalse(form.is_valid())
        self.assertIn('mindestens 3 Monate', ' '.join(form.errors['kuendigungsfrist']))
        # Gegenprobe: die gesetzliche Frist und eine längere gehen durch.
        self.assertTrue(self._form(self.v, 3).is_valid())
        self.assertTrue(self._form(self.v, 4).is_valid())

    def test_altvertrag_mit_zu_kurzer_frist_wird_nicht_blockiert_solange_sie_gleich_bleibt(self):
        from rentals.models import Mietvertrag
        Mietvertrag.objects.filter(pk=self.v.pk).update(kuendigungsfrist_monate=2)
        self.v.refresh_from_db()
        self.assertTrue(self._form(self.v, 2).is_valid())
        # Gegenprobe: wer sie ändert, ändert sie auf einen zulässigen Wert.
        self.assertFalse(self._form(self.v, 1).is_valid())

    def test_geschaeftsraum_braucht_sechs_monate(self):
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        gew = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='Laden', typ='gew')
        Mietvertrag.objects.filter(pk=self.v.pk).update(einheit=gew)
        self.v.refresh_from_db()
        self.assertFalse(self._form(self.v, 5).is_valid())
        self.assertTrue(self._form(self.v, 6).is_valid())

    def test_assistent_speichert_keinen_vertrag_mit_zu_kurzer_frist(self):
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        frei = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='4.5 Zi', typ='whg')
        c = Client()
        c.force_login(_team_user())
        daten = {'einheit_id': str(frei.id), 'mieter_id': str(self.m.id), 'netto_mietzins': '1800',
                 'nebenkosten': '250', 'beginn': '2026-12-01', 'kuendigungsfrist': '2'}
        c.post('/neu/vertraege/neu/speichern/', daten)
        self.assertFalse(Mietvertrag.objects.filter(einheit=frei).exists(),
                         'Ein Vertrag mit zwei Monaten Kündigungsfrist wurde gespeichert (Art. 266c OR).')
        # Gegenprobe: dieselbe Eingabe mit drei Monaten wird gespeichert.
        daten['kuendigungsfrist'] = '3'
        c.post('/neu/vertraege/neu/speichern/', daten)
        self.assertTrue(Mietvertrag.objects.filter(einheit=frei, kuendigungsfrist_monate=3).exists())

    def test_assistent_geschaeftsraum_ohne_angabe_nimmt_sechs(self):
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        gew = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='Laden', typ='gew')
        c = Client()
        c.force_login(_team_user())
        c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': str(gew.id), 'mieter_id': str(self.m.id), 'netto_mietzins': '3000',
            'nebenkosten': '300', 'beginn': '2026-12-01'})
        self.assertEqual(Mietvertrag.objects.get(einheit=gew).kuendigungsfrist_monate, 6)
        # ... und fünf Monate werden abgewiesen.
        Mietvertrag.objects.filter(einheit=gew).delete()
        c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': str(gew.id), 'mieter_id': str(self.m.id), 'netto_mietzins': '3000',
            'nebenkosten': '300', 'beginn': '2026-12-01', 'kuendigungsfrist': '5'})
        self.assertFalse(Mietvertrag.objects.filter(einheit=gew).exists())


@bei_stichtag(HEUTE)
class KuendigungErfassenFristTests(TestCase):
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

    def test_zu_kurze_vertragsfrist_wird_gemeldet_und_nicht_verwendet(self):
        from rentals.models import Mietvertrag
        Mietvertrag.objects.filter(pk=self.v.pk).update(kuendigungsfrist_monate=1)
        antwort = self._post(absender='mieter')
        k = Kuendigung.objects.get(vertrag=self.v)
        self.assertEqual(k.berechneter_termin, date(2027, 2, 28))              # 4.11. + 3 Monate = 4.2. -> Termin 28.2.
        text = self._meldungen(antwort)
        self.assertIn('mindestens 3', text)
        self.assertIn('Art. 266a Abs. 2 OR', text)
        # Gegenprobe (neue Sitzung, damit keine alten Meldungen mitkommen): mit der gesetzlichen Frist im Vertrag
        # gibt es die Meldung nicht.
        Kuendigung.objects.all().delete()
        Mietvertrag.objects.filter(pk=self.v.pk).update(kuendigungsfrist_monate=3, status='aktiv', ende=None)
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))
        antwort = self._post(absender='mieter')
        self.assertNotIn('Art. 266a Abs. 2 OR', self._meldungen(antwort))
        self.assertEqual(Kuendigung.objects.get(vertrag=self.v).berechneter_termin, date(2027, 2, 28))


@bei_stichtag(HEUTE)
class BefristeterVertragTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.ende = date(2027, 12, 31)
        self.v.ist_befristet = True
        self.v.ende = self.ende
        self.v.save()
        self.c = Client()
        self.c.force_login(_team_user('Verwaltung'))

    def _post(self, **daten):
        daten.setdefault('eingang_datum', HEUTE.isoformat())
        return self.c.post(f'/neu/vertraege/{self.v.id}/kuendigen/', daten)

    def _meldungen(self, antwort):
        return ' '.join(str(m) for m in get_messages(antwort.wsgi_request))

    def _anzahl(self):
        return Kuendigung.objects.filter(vertrag=self.v).count()

    def _unveraendert(self):
        self.v.refresh_from_db()
        self.assertEqual((self.v.status, self.v.ende), ('aktiv', self.ende))

    def test_ordentliche_kuendigung_des_mieters_wird_nicht_erfasst(self):
        antwort = self._post(absender='mieter')
        self.assertEqual(self._anzahl(), 0)
        self._unveraendert()
        text = self._meldungen(antwort)
        self.assertIn('befristet', text)
        self.assertIn('31.12.2027', text)
        self.assertIn('Art. 266', text)

    def test_ordentliche_kuendigung_des_vermieters_auf_oder_nach_dem_ende_wird_nicht_erfasst(self):
        """Vorher: erfasst, `ende` auf den errechneten Termin gesetzt — ein Termin, den es nicht gibt."""
        self._post(absender='vermieter', gewuenschtes_ende=date(2028, 3, 31).isoformat())
        self.assertEqual(self._anzahl(), 0)
        self._unveraendert()
        self._post(absender='vermieter', gewuenschtes_ende=self.ende.isoformat())
        self.assertEqual(self._anzahl(), 0)
        self._unveraendert()
        # Gegenprobe: derselbe Vertrag unbefristet wird gekündigt.
        self.v.ist_befristet = False
        self.v.ende = None
        self.v.save()
        self._post(absender='vermieter')
        self.assertEqual(self._anzahl(), 1)

    def test_mit_kuendigungsrecht_ist_die_ordentliche_kuendigung_des_mieters_moeglich(self):
        self.v.erstmals_kuendbar_auf = date(2027, 6, 30)
        self.v.save()
        self._post(absender='mieter')
        k = Kuendigung.objects.get(vertrag=self.v)
        # Frühester ordentlicher Termin wäre der 28.2.2027; «erstmals kündbar auf» 30.6.2027 geht vor.
        self.assertEqual(k.berechneter_termin, date(2027, 6, 30))
        self.assertEqual(k.per_datum, date(2027, 6, 30))

    def test_vorzeitige_rueckgabe_mit_angenommenem_ersatzmieter_befreit(self):
        self._post(absender='mieter', gewuenschtes_ende='2027-03-31', ersatzmieter='Frau Muster',
                   ersatzmieter_akzeptiert='on')
        k = Kuendigung.objects.get(vertrag=self.v)
        self.assertEqual(k.per_datum, date(2027, 3, 31))
        self.assertTrue(k.ersatzmieter_akzeptiert)

    def test_vorzeitige_rueckgabe_ohne_ersatzmieter_haftet_bis_zum_vertragsende(self):
        antwort = self._post(absender='mieter', gewuenschtes_ende='2027-03-31')
        k = Kuendigung.objects.get(vertrag=self.v)
        self.assertEqual(k.per_datum, self.ende)              # nicht ein errechneter «ordentlicher Termin»
        self.v.refresh_from_db()
        self.assertEqual(self.v.ende, self.ende)
        text = self._meldungen(antwort)
        self.assertIn('Ende der vereinbarten Vertragsdauer', text)
        self.assertIn('31.12.2027', text)
        self.assertIn('Art. 264', text)

    def test_ausserordentliche_kuendigung_bleibt_moeglich(self):
        self._post(absender='mieter', ausserordentlich='on', ausserordentlich_art='266g',
                   gewuenschtes_ende='2027-03-31')
        self.assertEqual(self._anzahl(), 1)

    def test_meldung_ist_uebersetzt(self):
        from django.utils import translation

        from core.services.kuendigungsverzicht import befristung_sperre_text
        for sprache in ('fr', 'it', 'en'):
            with self.subTest(sprache=sprache), translation.override(sprache):
                text = befristung_sperre_text(self.v, ausserordentlich=False, vorzeitige_rueckgabe=False)
                self.assertNotIn('Kündigung', text)
                self.assertIn('31.12.2027', text)
        # Gegenprobe: ausserordentlich oder vorzeitige Rückgabe: keine Meldung.
        self.assertEqual(befristung_sperre_text(self.v, ausserordentlich=True, vorzeitige_rueckgabe=False), '')
        self.assertEqual(befristung_sperre_text(self.v, ausserordentlich=False, vorzeitige_rueckgabe=True), '')
