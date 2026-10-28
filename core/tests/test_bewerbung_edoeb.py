"""MIET-13: Das öffentliche Bewerbungsformular fragt Geschlecht, Nationalität und Heimatort nicht mehr.

Der EDÖB hält Nationalität (wie Zivilstand und Konfession) in der Auswahlphase für unzulässig
(Merkblatt Anmeldeformulare für Mietwohnungen, 15.7.2025). Das Formular fragt sie nicht mehr; die API
speichert sie nicht, auch wenn ein altes Formular sie noch schickt; das Modell trägt keine erfundene
Vorgabe («weiblich», «Schweiz») mehr; das Scoring liest sie nie. Bestehende Bewerbungen behalten ihre Werte.

Gegenproben stehen im Bericht (Code zurückgebaut -> der genannte Test wird rot).
"""
import inspect
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import Einheit, Liegenschaft, Mietvertrag, _basis_objekte, _team_user, _test_organisation


def _formular_daten(einheit, **mehr):
    daten = {
        'einheit_id': einheit.id, 'vorname': 'Anna', 'nachname': 'Muster', 'zivilstand': '',
        'geburtsdatum': '1990-05-05', 'mobilnummer': '079 000 00 00', 'email': 'anna@example.ch',
        'adresse': 'Altweg 4', 'plz': '4500', 'ort': 'Solothurn',
        'aktueller_vermieter': 'Alt AG', 'kontaktperson_vermieter': 'Herr Alt',
        'telefon_vermieter': '032 000 00 00', 'erwerbsstatus': 'angestellt', 'beruf': 'Fachfrau',
        'einkommen_jahr': '80000-100000', 'arbeitgeber': 'Firma AG', 'angestellt_seit': '2020-01-01',
        'kontaktperson_arbeitgeber': 'Frau Chef', 'telefon_arbeitgeber': '032 111 11 11',
        'gewuenschter_bezugstermin': '2026-10-01',
    }
    daten.update(mehr)
    return daten


class OeffentlichesFormularTests(TestCase):

    def setUp(self):
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Inseratweg 3',
                                         plz='4500', ort='Solothurn')
        self.einheit = Einheit.objects.create(liegenschaft=lg, bezeichnung='2.5 Zi', typ='whg',
                                              nettomiete_aktuell=Decimal('1200'), zur_ausschreibung=True)

    def test_formular_fragt_die_drei_angaben_nicht(self):
        r = Client().get(f'/bewerben/{self.einheit.id}/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for verboten in ('form.geschlecht', 'form.nationalitaet', 'form.heimatort',
                         'Nationalität</label>', 'Heimatort (für Schweizer)', 'Geschlecht</label>'):
            self.assertNotIn(verboten, html, f'«{verboten}» darf im öffentlichen Formular nicht stehen')
        # Gegenrichtung: Das Formular ist sonst vollständig (Vorname/Geburtsdatum bleiben).
        self.assertIn('form.vorname', html)
        self.assertIn('form.geburtsdatum', html)

    def test_der_abschickende_code_sendet_die_felder_nicht(self):
        """Das Formular schickt `form` als FormData; ein Vorgabewert «Schweiz» im Skript wäre ein Datenfehler."""
        html = Client().get(f'/bewerben/{self.einheit.id}/').content.decode()
        self.assertNotIn("nationalitaet: 'Schweiz'", html)
        self.assertNotIn("geschlecht: 'weiblich'", html)


class ApiTests(TestCase):

    def setUp(self):
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Inseratweg 3',
                                         plz='4500', ort='Solothurn')
        self.einheit = Einheit.objects.create(liegenschaft=lg, bezeichnung='2.5 Zi', typ='whg',
                                              nettomiete_aktuell=Decimal('1200'), zur_ausschreibung=True)

    def _post(self, **mehr):
        return Client().post('/api/mietprozess/public/bewerben', _formular_daten(self.einheit, **mehr))

    def _bewerbung(self):
        from mietprozess.models import Mietbewerbung
        return Mietbewerbung.alle_organisationen.get(einheit=self.einheit)

    def test_bewerbung_ohne_die_drei_felder_wird_angenommen_und_traegt_keine_erfundene_vorgabe(self):
        r = self._post()
        self.assertEqual(r.status_code, 201, r.content[:300])
        b = self._bewerbung()
        self.assertEqual((b.geschlecht, b.nationalitaet, b.heimatort), ('', '', None))

    def test_ein_altes_formular_mit_den_feldern_wird_angenommen_aber_nichts_gespeichert(self):
        r = self._post(geschlecht='weiblich', nationalitaet='Deutschland', heimatort='Luzern')
        self.assertEqual(r.status_code, 201, r.content[:300])
        b = self._bewerbung()
        self.assertEqual(b.geschlecht, '')
        self.assertEqual(b.nationalitaet, '')
        self.assertFalse(b.heimatort)

    def test_modell_traegt_keine_erfundene_vorgabe(self):
        from mietprozess.models import Mietbewerbung
        self.assertEqual(Mietbewerbung._meta.get_field('geschlecht').default, '')
        self.assertEqual(Mietbewerbung._meta.get_field('nationalitaet').default, '')

    def test_bestehende_bewerbungen_behalten_ihre_werte(self):
        """Die Migration ändert nur Vorgaben, keine Daten."""
        from mietprozess.models import Mietbewerbung
        b = Mietbewerbung.objects.create(einheit=self.einheit, vorname='Alt', nachname='Bestand',
                                         email='alt@example.ch', geburtsdatum=date(1980, 1, 1),
                                         geschlecht='maennlich', nationalitaet='Schweiz', heimatort='Bern')
        b.refresh_from_db()
        self.assertEqual((b.geschlecht, b.nationalitaet, b.heimatort), ('maennlich', 'Schweiz', 'Bern'))


class AuswertungTests(TestCase):

    def test_das_scoring_liest_die_felder_nie(self):
        import core.services.bewerber_scoring as scoring
        quelle = inspect.getsource(scoring)
        for feld in ('geschlecht', 'nationalitaet', 'heimatort', 'zivilstand'):
            self.assertNotIn(feld, quelle, f'Das Scoring darf «{feld}» nicht auswerten (EDÖB)')

    def test_uebernahme_zum_mieter_rät_keine_anrede(self):
        """Ohne Angabe zum Geschlecht bleibt die Anrede leer, statt «Herr» zu raten."""
        from mietprozess.models import Mietbewerbung
        lg, e, m, v = _basis_objekte()
        e.zur_ausschreibung = True
        e.save()
        b = Mietbewerbung.objects.create(einheit=e, vorname='Beat', nachname='Neu', email='beat@example.ch',
                                         status='neu', geburtsdatum=date(1988, 3, 12))
        c = Client()
        c.force_login(_team_user())
        c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        from crm.models import Mieter
        self.assertEqual(Mieter.objects.get(nachname='Neu').anrede, '')
        self.assertEqual(Mietvertrag.objects.filter(einheit=e, status='entwurf').count(), 1)

    def test_uebernahme_mit_altem_geschlecht_setzt_die_anrede_weiter(self):
        from mietprozess.models import Mietbewerbung
        lg, e, m, v = _basis_objekte()
        e.zur_ausschreibung = True
        e.save()
        b = Mietbewerbung.objects.create(einheit=e, vorname='Clara', nachname='Alt', email='clara@example.ch',
                                         status='neu', geburtsdatum=date(1988, 3, 12), geschlecht='weiblich')
        c = Client()
        c.force_login(_team_user())
        c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        from crm.models import Mieter
        self.assertEqual(Mieter.objects.get(nachname='Alt').anrede, 'Frau')
