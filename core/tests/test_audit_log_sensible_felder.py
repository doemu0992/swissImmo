"""Sensible Werte stehen nie im Audit-Log.

Befund (Analysebericht 06.11.2026): `snapshot_model` liest jedes Feld über das Attribut, bei der AHV-Nummer also den
ENTSCHLÜSSELTEN Wert, und `diff_text` schrieb «Feld: alt → neu» ins Log. Die verschlüsselt gespeicherte AHV-Nummer
stand dort im Klartext, dazu IBAN und der Token des Portal-Feeds. Das Log ist die Revisionsspur und hat mehr Leser als
der Datensatz.

Gegenproben: `SENSIBLE_FELDER` in `diff_text` leeren (`verbergen=frozenset()`) -> `test_iban_*` und der Ansichtstest rot;
die Erkennung von `VerschluesseltesCharField` in `diff_model` entfernen -> `test_verschluesselte_felder_*` rot.
"""
from unittest import mock

from django.test import Client, TestCase

from core.auth import SENSIBLE_FELDER, diff_model, diff_text, snapshot_model
from core.models import AktivitaetsLog
from core.tenancy import organisation_kontext

from ._isolation import MandantenFixture

AHV = '756.1234.5678.97'
IBAN = 'CH93 0076 2011 6238 5295 7'


class DiffTextTests(TestCase):
    def test_sensible_werte_erscheinen_nur_als_geaendert(self):
        text = diff_text({'iban': 'CH11 AAAA', 'ort': 'Bern'}, {'iban': 'CH22 BBBB', 'ort': 'Thun'},
                         {'iban': 'IBAN', 'ort': 'Ort'})
        self.assertIn('IBAN: geändert', text)
        self.assertNotIn('CH11', text)
        self.assertNotIn('CH22', text)
        self.assertIn('Ort: Bern → Thun', text)               # gewöhnliche Felder wie bisher

    def test_unveraenderte_sensible_felder_fehlen(self):
        self.assertEqual(diff_text({'iban': 'X'}, {'iban': 'X'}), '')

    def test_die_liste_nennt_die_bekannten_geheimnisse(self):
        for name in ('ahv_nummer', 'iban', 'zahler_iban', 'portal_feed_token', 'password', 'geheimnis'):
            self.assertIn(name, SENSIBLE_FELDER)


class DiffModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _diff(self, **neu):
        with organisation_kontext(self.a.organisation):
            m = type(self.a.mieter).objects.get(pk=self.a.mieter.pk)
            alt = snapshot_model(m)
            for k, v in neu.items():
                setattr(m, k, v)
            m.save()
            return diff_model(alt, snapshot_model(m), m)

    def test_ahv_nummer_steht_nicht_im_text(self):
        text = self._diff(ahv_nummer=AHV)
        self.assertIn('geändert', text)
        self.assertNotIn('756', text)
        self.assertNotIn('1234', text)

    def test_iban_steht_nicht_im_text(self):
        text = self._diff(iban=IBAN, vorname='Neu')
        self.assertNotIn('9300', text.replace(' ', ''))
        self.assertIn('Neu', text)                             # der Vorname schon

    def test_verschluesselte_felder_sind_auch_ohne_listeneintrag_verborgen(self):
        """Ein künftiges `VerschluesseltesCharField` ist ohne Handarbeit mit dabei."""
        with mock.patch('core.auth.SENSIBLE_FELDER', frozenset()):
            text = self._diff(ahv_nummer='756.9999.8888.77')
        self.assertIn('geändert', text)
        self.assertNotIn('9999', text)


class AnsichtTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_personenformular_schreibt_keine_ahv_oder_iban_ins_log(self):
        m = self.a.mieter
        c = Client()
        c.force_login(self.a.benutzer)
        r = c.post(f'/neu/personen/{m.pk}/bearbeiten/', {
            'typ': 'person', 'vorname': 'Neuer', 'nachname': m.nachname or 'Muster',
            'ahv_nummer': AHV, 'zahler_iban': 'CH9300762011623852957'})
        self.assertIn(r.status_code, (200, 302))
        with organisation_kontext(self.a.organisation):
            m.refresh_from_db()
            self.assertEqual(m.ahv_nummer, AHV, 'die AHV-Nummer wurde gar nicht gespeichert: Test prüft nichts')
            eintraege = list(AktivitaetsLog.objects.values_list('aktion', 'details', 'objekt'))
        alles = ' '.join(' '.join(map(str, e)) for e in eintraege)
        self.assertNotIn('756.1234', alles)
        self.assertNotIn('1234.5678', alles)
        self.assertNotIn('9300', alles.replace(' ', ''))
        self.assertIn('Neuer', alles, 'der Vorname fehlt: es wurde nichts protokolliert, Test prüft nichts')
