"""Abnahmen gehören zur Einheit und bauen aufeinander auf.

Auszug → Einzug Monate später und umgekehrt: Das neue Protokoll beginnt beim
letzten abgeschlossenen Protokoll der Einheit, mit dem Zustand von damals als
Vorzustand. Was schon beim Einzug beanstandet war, belastet der Verwalter dem
Mieter beim Auszug nur nach ausdrücklicher Bestätigung.
"""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user
from ._isolation import MandantenFixture


def _vertrag_nachher(einheit, beginn=date(2026, 9, 1), name='Neu'):
    from crm.models import Mieter
    from rentals.models import Mietvertrag
    m = Mieter.objects.create(typ='person', vorname=name, nachname='Mieter', email=f'{name}@example.ch',
                              strasse='Weg 1', plz='8000', ort='Zürich')
    return Mietvertrag.objects.create(mieter=m, einheit=einheit, beginn=beginn, status='aktiv',
                                      netto_mietzins=Decimal('1600'), nebenkosten=Decimal('200'))


def _protokoll(vertrag, typ, datum, positionen, abgeschlossen=True):
    """positionen: [(raum, bauteil, zustand, kommentar)]"""
    from rentals.models import Abnahmeprotokoll, AbnahmePosition
    prot = Abnahmeprotokoll.objects.create(vertrag=vertrag, typ=typ, datum=datum, abgeschlossen=abgeschlossen)
    for nr, (raum, bauteil, zustand, kommentar) in enumerate(positionen):
        AbnahmePosition.objects.create(protokoll=prot, raum=raum, bezeichnung=bauteil, zustand=zustand,
                                       kommentar=kommentar, sortierung=nr)
    return prot


class KetteBasis(TestCase):
    def setUp(self):
        self.lg, self.einheit, self.mieter, self.v1 = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def _wizard(self, vertrag, **daten):
        return self.c.post(f'/neu/vertraege/{vertrag.id}/abnahme/vorort/', daten)


class AblageBeiDerEinheitTests(KetteBasis):

    def test_einheit_wird_aus_dem_vertrag_abgeleitet_und_sammelt_alle_mieter(self):
        v2 = _vertrag_nachher(self.einheit)
        p1 = _protokoll(self.v1, 'auszug', date(2026, 6, 30), [('Küche', 'Boden', 'io', '')])
        p2 = _protokoll(v2, 'einzug', date(2026, 9, 1), [('Küche', 'Boden', 'io', '')])
        self.assertEqual(p1.einheit_id, self.einheit.id)
        self.assertEqual(set(self.einheit.abnahmen.values_list('id', flat=True)), {p1.id, p2.id})

    def test_einheit_akte_listet_die_abnahmen_aller_mieter(self):
        v2 = _vertrag_nachher(self.einheit)
        _protokoll(self.v1, 'auszug', date(2026, 6, 30), [('Küche', 'Boden', 'io', '')])
        _protokoll(v2, 'einzug', date(2026, 9, 1), [('Küche', 'Boden', 'io', '')])
        r = self.c.get(f'/neu/objekte/{self.einheit.id}/')
        self.assertContains(r, 'Hans Muster')       # Mieter 1
        self.assertContains(r, 'Neu Mieter')        # Mieter 2
        self.assertContains(r, '30.06.2026')

    def test_vertrag_mit_protokoll_wird_nicht_geloescht(self):
        from rentals.models import Mietvertrag
        _protokoll(self.v1, 'auszug', date(2026, 6, 30), [('Küche', 'Boden', 'io', '')])
        r = self.c.post(f'/neu/vertraege/{self.v1.id}/loeschen/', follow=True)
        self.assertContains(r, 'Abnahmeprotokolle')
        self.assertTrue(Mietvertrag.objects.filter(id=self.v1.id).exists())
        self.assertEqual(self.einheit.abnahmen.count(), 1)

    def test_vertrag_ohne_protokoll_laesst_sich_weiter_loeschen(self):
        from rentals.models import Mietvertrag
        self.c.post(f'/neu/vertraege/{self.v1.id}/loeschen/')
        self.assertFalse(Mietvertrag.objects.filter(id=self.v1.id).exists())


class VorgaengerTests(KetteBasis):

    def test_letztes_abgeschlossenes_protokoll_der_einheit_ueber_alle_vertraege(self):
        from core.services.abnahme_vorgaenger import vorgaenger_fuer
        alt = _protokoll(self.v1, 'einzug', date(2021, 3, 1), [('Küche', 'Boden', 'io', '')])
        neu = _protokoll(self.v1, 'auszug', date(2026, 6, 30), [('Küche', 'Boden', 'normal', '')])
        _protokoll(self.v1, 'auszug', date(2026, 7, 5), [('Küche', 'Boden', 'io', '')], abgeschlossen=False)  # Entwurf
        self.assertEqual(vorgaenger_fuer(self.einheit, date(2026, 9, 1)).id, neu.id)
        self.assertEqual(vorgaenger_fuer(self.einheit, date(2022, 1, 1)).id, alt.id)   # nicht aus der Zukunft
        self.assertIsNone(vorgaenger_fuer(self.einheit, date(2020, 1, 1)))
        # `ausser` schliesst das Protokoll selbst aus (Bearbeiten eines abgeschlossenen Protokolls)
        self.assertEqual(vorgaenger_fuer(self.einheit, date(2026, 9, 1), ausser=neu).id, alt.id)

    def test_nur_auszug_und_monate_spaeter_einzug_baut_auf_dem_auszug(self):
        v2 = _vertrag_nachher(self.einheit)
        auszug = _protokoll(self.v1, 'auszug', date(2026, 3, 31), [
            ('Küche', 'Backofen', 'uebermaessig', 'Brandfleck'), ('Küche', 'Boden', 'normal', ''),
            ('Bad', 'Dusche', 'io', '')])
        r = self.c.get(f'/neu/vertraege/{v2.id}/abnahme/vorort/?typ=einzug')
        self.assertContains(r, 'Aus letzter Abnahme')
        self._wizard(v2, typ='einzug', datum='2026-09-01', vorlage='vorgaenger', raum=['Küche', 'Bad'])
        from rentals.models import Abnahmeprotokoll
        ein = Abnahmeprotokoll.objects.get(vertrag=v2)
        self.assertEqual(ein.vorgaenger_id, auszug.id)
        self.assertEqual([(p.bezeichnung, p.vorgaenger_position.zustand) for p in ein.positionen.all()],
                         [('Backofen', 'uebermaessig'), ('Boden', 'normal'), ('Dusche', 'io')])
        self.assertEqual({p.zustand for p in ein.positionen.all()}, {''})     # neu zu bewerten
        seite = self.c.get(f'/neu/abnahme/{ein.id}/vorort/?r=0')
        self.assertContains(seite, 'Brandfleck')                              # Vorzustand sichtbar
        self.assertContains(seite, '31.03.2026')

    def test_nur_einzug_und_spaeter_auszug_baut_auf_dem_einzug_und_umgekehrt(self):
        einzug = _protokoll(self.v1, 'einzug', date(2021, 3, 1), [('Küche', 'Boden', 'io', 'wie neu')])
        self._wizard(self.v1, typ='auszug', datum='2026-06-30', vorlage='vorgaenger', raum=['Küche'])
        from rentals.models import Abnahmeprotokoll
        aus = Abnahmeprotokoll.objects.get(typ='auszug')
        self.assertEqual(aus.vorgaenger_id, einzug.id)
        seite = self.c.get(f'/neu/abnahme/{aus.id}/vorort/?r=0')
        self.assertContains(seite, 'wie neu')
        self.assertContains(seite, 'data-wie-vor')

    def test_ohne_vorgaenger_keine_vorlage_und_keine_vorzustandszeile(self):
        r = self.c.get(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/')
        self.assertNotContains(r, 'Aus letzter Abnahme')

    def test_andere_vorlage_waehlen_verknuepft_nicht(self):
        _protokoll(self.v1, 'einzug', date(2021, 3, 1), [('Küche', 'Boden', 'io', '')])
        self._wizard(self.v1, typ='auszug', datum='2026-06-30', vorlage='standard', raum=['Küche'])
        from rentals.models import Abnahmeprotokoll
        self.assertIsNone(Abnahmeprotokoll.objects.get(typ='auszug').vorgaenger_id)


class VorbestandTests(KetteBasis):
    """Schon beim Einzug beanstandet → beim Auszug nur mit Bestätigung belastet."""

    def _auszug(self, einzug_zustand):
        _protokoll(self.v1, 'einzug', date(2021, 3, 1), [('Küche', 'Backofen', einzug_zustand, '')])
        self._wizard(self.v1, typ='auszug', datum='2026-06-30', vorlage='vorgaenger', raum=['Küche'])
        from rentals.models import Abnahmeprotokoll
        prot = Abnahmeprotokoll.objects.get(typ='auszug')
        return prot, prot.positionen.get()

    def _speichern(self, prot, pos, **d):
        return self.c.post(f'/neu/abnahme/{prot.id}/vorort/position/', {'position': pos.id, **d})

    def test_warnung_wenn_schon_beim_einzug_uebermaessig(self):
        prot, pos = self._auszug('uebermaessig')
        r = self._speichern(prot, pos, zustand='uebermaessig', kosten='500')
        self.assertTrue(r.json()['vorbestand_warnung'])
        self.assertEqual(r.json()['vorbestand_offen'], 1)

    def test_keine_warnung_bei_normal_oder_io_im_vorgaenger(self):
        prot, pos = self._auszug('normal')
        r = self._speichern(prot, pos, zustand='uebermaessig', kosten='500')
        self.assertFalse(r.json()['vorbestand_warnung'])
        self.assertEqual(r.json()['vorbestand_offen'], 0)

    def test_abschluss_ist_gesperrt_bis_entschieden(self):
        prot, pos = self._auszug('uebermaessig')
        self._speichern(prot, pos, zustand='uebermaessig', kosten='500')
        r = self.c.post(f'/neu/abnahme/{prot.id}/vorort/abschliessen/', {}, follow=True)
        self.assertContains(r, 'schon im Vorgänger-Protokoll beanstandet')
        prot.refresh_from_db()
        self.assertFalse(prot.abgeschlossen)

    def test_vorbestehend_belastet_den_mieter_nicht(self):
        prot, pos = self._auszug('uebermaessig')
        self._speichern(prot, pos, zustand='uebermaessig', kosten='500')
        self._speichern(prot, pos, vorbestand='vorbestehend')
        pos.refresh_from_db()
        self.assertEqual((pos.mangel.verursacher, pos.mangel.mieteranteil), ('vermieter', Decimal('0.00')))
        self.c.post(f'/neu/abnahme/{prot.id}/vorort/abschliessen/', {})
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)
        self.assertEqual(prot.kosten_mieter_total, Decimal('0.00'))

    def test_bestaetigt_belasten_bleibt_beim_mieter(self):
        prot, pos = self._auszug('uebermaessig')
        self._speichern(prot, pos, zustand='uebermaessig', kosten='500')
        self._speichern(prot, pos, vorbestand='mieter')
        pos.refresh_from_db()
        self.assertEqual((pos.mangel.verursacher, pos.mangel.mieteranteil), ('mieter', Decimal('500.00')))
        self.c.post(f'/neu/abnahme/{prot.id}/vorort/abschliessen/', {})
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)

    def test_entscheid_faellt_weg_wenn_nicht_mehr_uebermaessig(self):
        prot, pos = self._auszug('uebermaessig')
        self._speichern(prot, pos, zustand='uebermaessig', kosten='500')
        self._speichern(prot, pos, vorbestand='vorbestehend')
        self._speichern(prot, pos, zustand='normal')
        pos.refresh_from_db()
        self.assertEqual(pos.vorbestand_entscheid, '')
        self._speichern(prot, pos, zustand='uebermaessig')
        pos.refresh_from_db()
        self.assertEqual(pos.mangel.verursacher, 'mieter')      # nicht stillschweigend weiter entschieden

    def test_ungueltiger_entscheid_wird_abgelehnt(self):
        prot, pos = self._auszug('uebermaessig')
        self.assertEqual(self._speichern(prot, pos, vorbestand='egal').status_code, 400)

    def test_beim_einzug_gibt_es_keine_warnung(self):
        _protokoll(self.v1, 'auszug', date(2021, 3, 1), [('Küche', 'Backofen', 'uebermaessig', '')])
        v2 = _vertrag_nachher(self.einheit, beginn=date(2021, 4, 1))
        self._wizard(v2, typ='einzug', datum='2021-04-01', vorlage='vorgaenger', raum=['Küche'])
        from rentals.models import Abnahmeprotokoll
        prot = Abnahmeprotokoll.objects.get(vertrag=v2)
        r = self._speichern(prot, prot.positionen.get(), zustand='uebermaessig', kosten='100')
        self.assertFalse(r.json()['vorbestand_warnung'])


class AusUndEinzugTests(KetteBasis):

    def test_art_aus_und_einzug_nur_mit_nachmieter(self):
        r = self.c.get(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/')
        self.assertContains(r, 'value="beides" disabled')       # sichtbar, aber nicht wählbar
        self.assertContains(r, f'/neu/vertraege/neu/?einheit={self.einheit.id}')   # und der Weg zum Folgevertrag
        _vertrag_nachher(self.einheit)
        r = self.c.get(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/')
        self.assertContains(r, 'value="beides"')
        self.assertNotContains(r, 'value="beides" disabled')

    def test_aus_und_einzug_auch_vom_vertrag_des_einziehenden_aus(self):
        """Wer den neuen Vertrag öffnet (Standard: Einzug), muss Aus- und Einzug
        ebenfalls wählen können; das Auszugsprotokoll gehört dem Vorgänger."""
        from rentals.models import Abnahmeprotokoll
        v2 = _vertrag_nachher(self.einheit)
        r = self.c.get(f'/neu/vertraege/{v2.id}/abnahme/vorort/')
        self.assertContains(r, 'value="beides"')
        self.assertNotContains(r, 'value="beides" disabled')
        self.assertContains(r, 'name="partner"')
        self.assertContains(r, f'<option value="{self.v1.id}" selected>')     # der Vorgänger ist vorgewählt
        self.c.post(f'/neu/vertraege/{v2.id}/abnahme/vorort/',
                    {'typ': 'beides', 'datum': '2026-08-31', 'raum': ['Keller']})
        aus = Abnahmeprotokoll.objects.get(typ='auszug')
        self.assertEqual((aus.vertrag_id, aus.folge_vertrag_id), (self.v1.id, v2.id))
        self.c.post(f'/neu/abnahme/{aus.id}/vorort/abschliessen/', {})
        ein = Abnahmeprotokoll.objects.get(typ='einzug')
        self.assertEqual((ein.vertrag_id, ein.vorgaenger_id), (v2.id, aus.id))

    def test_gekuendigter_vertrag_ist_immer_der_ausziehende(self):
        from core.services.abnahme_vorgaenger import aus_und_einzug_paar
        v2 = _vertrag_nachher(self.einheit)
        self.v1.status = 'gekuendigt'
        self.v1.save()
        self.assertEqual(aus_und_einzug_paar(self.v1), (self.v1, v2))
        self.assertEqual(aus_und_einzug_paar(v2), (self.v1, v2))

    def test_paar_auch_wenn_die_daten_nicht_lueckenlos_anschliessen(self):
        """Der Nachmieter beginnt vor dem Ende des alten Vertrags (Überlappung) oder
        der alte hat gar kein Ende: Die Kombination bleibt wählbar."""
        from core.services.abnahme_vorgaenger import aus_und_einzug_paar
        self.v1.ende = date(2026, 12, 31)
        self.v1.save()
        v2 = _vertrag_nachher(self.einheit, beginn=date(2026, 10, 1))        # beginnt vor dem Ende von v1
        self.assertEqual(aus_und_einzug_paar(self.v1), (self.v1, v2))
        self.assertEqual(aus_und_einzug_paar(v2), (self.v1, v2))
        r = self.c.get(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/')
        self.assertNotContains(r, 'value="beides" disabled')

    def test_partner_waehlbar_und_fremde_einheit_wird_ignoriert(self):
        from core.services.abnahme_vorgaenger import aus_und_einzug_paar
        from portfolio.models import Einheit
        v2 = _vertrag_nachher(self.einheit, beginn=date(2026, 9, 1), name='Zwei')
        v3 = _vertrag_nachher(self.einheit, beginn=date(2027, 3, 1), name='Drei')
        # Mittlerer Vertrag, aktiv: Vorgänger ist der Partner, gewählt werden kann auch der Nachfolger
        self.assertEqual(aus_und_einzug_paar(v2), (self.v1, v2))
        self.assertEqual(aus_und_einzug_paar(v2, v3.id), (v2, v3))
        # ein Vertrag einer anderen Einheit ist kein gültiger Partner
        andere = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='Andere', typ='whg')
        fremd = _vertrag_nachher(andere, beginn=date(2026, 1, 1), name='Fremd')
        self.assertEqual(aus_und_einzug_paar(v2, fremd.id), (self.v1, v2))

    def test_gewaehlter_partner_bestimmt_das_protokoll(self):
        from rentals.models import Abnahmeprotokoll
        v2 = _vertrag_nachher(self.einheit, beginn=date(2026, 9, 1), name='Zwei')
        v3 = _vertrag_nachher(self.einheit, beginn=date(2027, 3, 1), name='Drei')
        self.c.post(f'/neu/vertraege/{v2.id}/abnahme/vorort/',
                    {'typ': 'beides', 'partner': v3.id, 'datum': '2027-02-28', 'raum': ['Keller']})
        aus = Abnahmeprotokoll.objects.get(typ='auszug')
        self.assertEqual((aus.vertrag_id, aus.folge_vertrag_id), (v2.id, v3.id))

    def test_ohne_zweiten_vertrag_gibt_es_kein_paar(self):
        from core.services.abnahme_vorgaenger import aus_und_einzug_paar
        self.assertIsNone(aus_und_einzug_paar(self.v1))

    def test_ohne_nachmieter_wird_beides_zu_standard(self):
        self.c.post(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/', {'typ': 'beides', 'raum': ['Küche']})
        from rentals.models import Abnahmeprotokoll
        self.assertIsNone(Abnahmeprotokoll.objects.get().folge_vertrag_id)

    def test_abschluss_bereitet_das_einzugsprotokoll_des_nachmieters_vor(self):
        from rentals.models import Abnahmeprotokoll
        v2 = _vertrag_nachher(self.einheit)
        self.c.post(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/',
                    {'typ': 'beides', 'datum': '2026-08-31', 'raum': ['Keller']})      # 5 Bauteile
        aus = Abnahmeprotokoll.objects.get(typ='auszug')
        self.assertEqual(aus.folge_vertrag_id, v2.id)
        for p, z, k in zip(aus.positionen.all(), ['uebermaessig', 'normal', 'io', 'io', 'io'],
                           ['Kratzer', '', '', '', '']):
            self.c.post(f'/neu/abnahme/{aus.id}/vorort/position/',
                        {'position': p.id, 'zustand': z, 'kommentar': k, 'kosten': '200'})
        r = self.c.post(f'/neu/abnahme/{aus.id}/vorort/abschliessen/', {'zaehler_strom': '777'})
        ein = Abnahmeprotokoll.objects.get(typ='einzug')
        self.assertRedirects(r, f'/neu/abnahme/{ein.id}/vorort/?r=1', fetch_redirect_response=False)
        self.assertEqual((ein.vertrag_id, ein.vorgaenger_id, ein.datum), (v2.id, aus.id, date(2026, 8, 31)))
        self.assertFalse(ein.abgeschlossen)                               # der Einziehende prüft selbst
        self.assertEqual(ein.zaehler_strom, '777')
        self.assertEqual([p.zustand for p in ein.positionen.all()], ['uebermaessig', 'normal', 'io', 'io', 'io'])
        erster = ein.positionen.first()
        self.assertEqual(erster.kommentar, 'Kratzer')
        self.assertEqual(erster.vorgaenger_position.protokoll_id, aus.id)
        self.assertEqual(erster.mangel.verursacher, 'vermieter')          # beim Einzug kein Mieterschaden
        self.assertEqual(ein.kosten_mieter_total, Decimal('0.00'))
        # derselbe Zustand liegt bei der Einheit: beide Protokolle
        self.assertEqual(self.einheit.abnahmen.count(), 2)

    def test_zweiter_abschluss_legt_kein_zweites_einzugsprotokoll_an(self):
        from rentals.models import Abnahmeprotokoll
        _vertrag_nachher(self.einheit)
        self.c.post(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/', {'typ': 'beides', 'raum': ['Küche']})
        aus = Abnahmeprotokoll.objects.get(typ='auszug')
        self.c.post(f'/neu/abnahme/{aus.id}/vorort/abschliessen/', {})
        self.c.post(f'/neu/abnahme/{aus.id}/vorort/abschliessen/', {})
        self.assertEqual(Abnahmeprotokoll.objects.filter(typ='einzug').count(), 1)

    def test_einzugsprotokoll_kann_abgeschlossen_werden(self):
        from rentals.models import Abnahmeprotokoll
        _vertrag_nachher(self.einheit)
        self.c.post(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/', {'typ': 'beides', 'raum': ['Küche']})
        aus = Abnahmeprotokoll.objects.get(typ='auszug')
        self.c.post(f'/neu/abnahme/{aus.id}/vorort/abschliessen/', {})
        ein = Abnahmeprotokoll.objects.get(typ='einzug')
        self.c.post(f'/neu/abnahme/{ein.id}/vorort/abschliessen/', {'unterschrift_mieter': 'Neu Mieter'})
        ein.refresh_from_db()
        self.assertTrue(ein.abgeschlossen)


class KetteMandantenTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from core.tenancy import organisation_kontext
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        with organisation_kontext(cls.b.organisation):
            cls.prot_b = _protokoll(cls.b.vertrag, 'auszug', date(2026, 6, 30), [('Küche', 'Boden', 'io', '')])

    def test_vorgaenger_kommt_nie_aus_einer_fremden_verwaltung(self):
        from core.services.abnahme_vorgaenger import vorgaenger_fuer
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.a.organisation):
            self.assertIsNone(vorgaenger_fuer(self.b.einheit, date(2026, 12, 31)))
        with organisation_kontext(self.b.organisation):
            self.assertEqual(vorgaenger_fuer(self.b.einheit, date(2026, 12, 31)).id, self.prot_b.id)

    def test_fremde_einheit_zeigt_die_abnahmen_nicht(self):
        c = Client(); c.force_login(self.a.benutzer)
        self.assertEqual(c.get(f'/neu/objekte/{self.b.einheit.id}/').status_code, 404)
