"""Brief aus einer Vorlage: Einschreiben, Frist (Datum / Tage ab Zugang), Pendenz, Mandantentrennung."""
import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Pendenz
from core.services.brief_aus_vorlage import (brief_erzeugen, frist_vorgabe, ist_brief_pendenz,
                                             sendungsnummer_bereinigt)
from crm.models import Vorlage

from ._isolation import MandantenFixture


class BriefBasis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        cls.heute = timezone.localdate()

    def vorlage(self, **kw):
        werte = dict(name='Abmahnung', kategorie='brief', betreff='Abmahnung', inhalt='{mieter.anrede} Frist {frist}',
                     einschreiben=True, frist_art='datum', frist_tage=14, organisation=self.a.organisation)
        werte.update(kw)
        return Vorlage.objects.create(**werte)

    def mieter_id(self):
        return self.a.vertrag.mieter_id


class ErzeugenTests(BriefBasis):
    def test_festes_datum_legt_brief_und_pendenz_an(self):
        frist = self.heute + datetime.timedelta(days=20)
        erg = brief_erzeugen(self.vorlage(), [self.mieter_id()], self.a.organisation, einschreiben=True,
                             frist_art='datum', frist_datum=frist)
        self.assertEqual(len(erg['briefe']), 1)
        p = erg['briefe'][0]['pendenz']
        self.assertEqual(p.faellig_am, frist)
        self.assertTrue(p.einschreiben)
        self.assertTrue(ist_brief_pendenz(p))
        self.assertTrue(erg['pdf'].startswith(b'%PDF'))

    def test_tage_ab_zugang_ist_provisorisch(self):
        v = self.vorlage(inhalt='{mieter.anrede} in {frist.tage} Tagen', frist_art='zugang', frist_tage=10)
        erg = brief_erzeugen(v, [self.mieter_id()], self.a.organisation, einschreiben=True,
                             frist_art='zugang', frist_tage=10)
        p = erg['briefe'][0]['pendenz']
        self.assertEqual(p.frist_tage, 10)
        self.assertGreater(p.faellig_am, self.heute + datetime.timedelta(days=10))

    def test_ohne_einschreiben_und_frist_keine_pendenz(self):
        v = self.vorlage(inhalt='{mieter.anrede}', einschreiben=False, frist_art='', frist_tage=None)
        erg = brief_erzeugen(v, [self.mieter_id()], self.a.organisation)
        self.assertIsNone(erg['briefe'][0]['pendenz'])

    def test_frist_in_der_vergangenheit_wird_abgelehnt_und_nichts_abgelegt(self):
        vorher = Pendenz.alle_organisationen.count()
        with self.assertRaises(ValidationError):
            brief_erzeugen(self.vorlage(), [self.mieter_id()], self.a.organisation, einschreiben=True,
                           frist_art='datum', frist_datum=self.heute)
        self.assertEqual(Pendenz.alle_organisationen.count(), vorher)

    def test_platzhalter_ohne_wert_wird_abgelehnt(self):
        with self.assertRaises(ValidationError):
            brief_erzeugen(self.vorlage(), [self.mieter_id()], self.a.organisation)   # {frist} ohne Frist

    def test_vorgabe_bei_einschreiben_liegt_nach_dem_postweg(self):
        mit = frist_vorgabe(self.vorlage(), einschreiben=True, heute=self.heute)['datum']
        ohne = frist_vorgabe(self.vorlage(), einschreiben=False, heute=self.heute)['datum']
        self.assertGreater(mit, ohne)

    def test_sendungsnummer_ohne_steuerzeichen(self):
        self.assertEqual(sendungsnummer_bereinigt(' 98.00<x>12\n34 '), '98.00x1234')
        self.assertNotIn('<', sendungsnummer_bereinigt('a<b>'))
        self.assertEqual(len(sendungsnummer_bereinigt('1' * 100)), 40)


class StandardVorlagenTests(TestCase):
    def test_alle_standardbriefe_sind_in_sich_stimmig(self):
        from core.services.platzhalter import unbekannte
        from core.services.vorlagen_briefe import BRIEF_VORLAGEN
        namen = [v['name'] for v in BRIEF_VORLAGEN]
        self.assertEqual(len(namen), len(set(namen)))
        for v in BRIEF_VORLAGEN:
            with self.subTest(v['name']):
                text = v['betreff'] + v['inhalt']
                self.assertEqual(unbekannte(text), [])
                if '{frist}' in text:
                    self.assertEqual(v['frist_art'], 'datum')
                if '{frist.tage}' in text:
                    self.assertTrue(v['frist_art'])

    def test_tierhaltebewilligung_haengt_am_haustierereignis(self):
        from core.services.vorlagen_briefe import BRIEF_VORLAGEN
        t = [v for v in BRIEF_VORLAGEN if v['name'] == 'Tierhaltebewilligung']
        self.assertEqual(t[0]['ereignis'], 'vertrag_haustier')


class AnsichtTests(BriefBasis):
    def test_formular_und_erstellen(self):
        v = self.vorlage()
        self.client.force_login(self.a.benutzer)
        self.assertEqual(self.client.get(reverse('fw_vorlage_brief', args=[v.pk])).status_code, 200)
        frist = (self.heute + datetime.timedelta(days=20)).isoformat()
        r = self.client.post(reverse('fw_vorlage_brief', args=[v.pk]),
                             {'mieter': [self.mieter_id()], 'einschreiben': '1', 'frist_datum': frist})
        self.assertRedirects(r, reverse('fw_vorlage_brief_fertig', args=[v.pk]))
        self.assertContains(self.client.get(reverse('fw_vorlage_brief_fertig', args=[v.pk])), 'Einschreiben')

    def test_fremde_vorlage_ist_nicht_erreichbar(self):
        fremd = Vorlage.objects.create(name='B-Brief', kategorie='brief', inhalt='x',
                                       organisation=self.b.organisation)
        self.client.force_login(self.a.benutzer)
        self.assertEqual(self.client.get(reverse('fw_vorlage_brief', args=[fremd.pk])).status_code, 404)

    def test_fremder_mieter_wird_nicht_beschrieben(self):
        v = self.vorlage(einschreiben=False, frist_art='', frist_tage=None, inhalt='{mieter.anrede}')
        mieter_b = self.b.vertrag.mieter_id
        with self.assertRaises(ValidationError):
            brief_erzeugen(v, [mieter_b], self.a.organisation)
