"""Entscheid 30.09.2026: Versicherungsfall mit Police, Selbstbehalt (Eigentümer oder Mieter) und Entschädigung."""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user


def _saldo(nummer):
    from finance.models import Buchung, Buchungskonto
    k = Buchungskonto.objects.filter(nummer=nummer).first()
    if k is None:
        return Decimal('0.00')
    soll = sum((b.betrag for b in Buchung.objects.filter(soll_konto=k)), Decimal('0'))
    haben = sum((b.betrag for b in Buchung.objects.filter(haben_konto=k)), Decimal('0'))
    return soll - haben


class VersicherungsfallTests(TestCase):

    def setUp(self):
        _seed_konten()
        from crm.models import Handwerker
        from finance.booking import konto
        from finance.models import KreditorenRechnung
        from portfolio.models import Versicherung
        from tickets.models import HandwerkerAuftrag, SchadenMeldung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        call_command('fallarten_anlegen', verbosity=0)
        self.police = Versicherung.objects.create(liegenschaft=self.lg, art='gebaeude', gesellschaft='GVZ',
                                                  policennummer='P-77', selbstbehalt=Decimal('500.00'))
        self.t = SchadenMeldung.objects.create(titel='Wasserschaden Bad', liegenschaft=self.lg,
                                               betroffene_einheit=self.e, status='in_bearbeitung')
        kr = KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('1240'), status='freigegeben',
                                               liegenschaft=self.lg, konto=konto('4000'))
        HandwerkerAuftrag.objects.create(ticket=self.t, handwerker=Handwerker.objects.create(firma='Sanitär AG'),
                                         kosten_effektiv=Decimal('1240'), kreditoren_rechnung=kr)
        self.c = Client(); self.c.force_login(_team_user('Verwalter'))
        self.url = f'/neu/schaeden/{self.t.id}/versicherung/'

    def _melden(self, **extra):
        d = {'aktion': 'melden', 'police': self.police.id, 'schadennummer': 'S-2026-1',
             'schadensumme': '1240.00', 'selbstbehalt_traeger': 'eigentuemer'}
        d.update(extra)
        return self.c.post(self.url, d, secure=True)

    def _fall(self):
        from tickets.models import Versicherungsfall
        return Versicherungsfall.objects.get(ticket=self.t)

    def test_melden_uebernimmt_den_selbstbehalt_der_police(self):
        self._melden()
        f = self._fall()
        self.assertEqual(f.selbstbehalt, Decimal('500.00'))
        self.assertEqual(f.schadensumme, Decimal('1240.00'))
        self.assertEqual(f.erwartete_entschaedigung, Decimal('740.00'))
        self.assertEqual(f.police_id, self.police.id)

    def test_melden_eroeffnet_den_fall_und_erledigt_die_pendenz(self):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        from faelle.models import Fall
        generate_auto_pendenzen(horizont_tage=30)
        self.assertTrue(Pendenz.objects.filter(quelle=f'auto:versicherung:{self.t.pk}', erledigt=False).exists())
        self._melden()
        fall = Fall.objects.get(fallart__schluessel='versicherungsfall')
        erledigt = {s.bezeichnung for s in fall.schritte.filter(erledigt_am__isnull=False)}
        self.assertTrue(any('melden' in b for b in erledigt))
        self.assertTrue(any('Schadennummer' in b for b in erledigt))
        self.assertTrue(Pendenz.objects.get(quelle=f'auto:versicherung:{self.t.pk}').erledigt)
        generate_auto_pendenzen(horizont_tage=30)
        self.assertTrue(Pendenz.objects.get(quelle=f'auto:versicherung:{self.t.pk}').erledigt,
                        'Die Pendenz kommt nach der Meldung wieder.')

    def test_entschaedigung_mindert_den_schadenaufwand(self):
        self._melden()
        f = self._fall()
        self.c.post(self.url, {'aktion': 'entschaedigung', 'fall': f.id, 'betrag': '740.00'}, secure=True)
        f.refresh_from_db()
        self.assertEqual(f.status, 'entschaedigt')
        self.assertEqual(_saldo('1020'), Decimal('740.00'))
        self.assertEqual(_saldo('4000'), Decimal('-740.00'), 'Aufwandsminderung auf dem Reparaturkonto.')

    def test_entschaedigung_nur_einmal(self):
        self._melden()
        f = self._fall()
        for _ in range(2):
            self.c.post(self.url, {'aktion': 'entschaedigung', 'fall': f.id, 'betrag': '740.00'}, secure=True)
        self.assertEqual(_saldo('1020'), Decimal('740.00'))

    def test_selbstbehalt_beim_eigentuemer_wird_nicht_ueberwaelzt(self):
        from finance.models import DebitorenRechnung
        self._melden()
        f = self._fall()
        self.c.post(self.url, {'aktion': 'ueberwaelzen', 'fall': f.id, 'vertrag': self.v.id}, secure=True)
        self.assertFalse(DebitorenRechnung.objects.filter(titel__startswith='Selbstbehalt').exists())

    def test_selbstbehalt_ueberwaelzen_stellt_dem_mieter_eine_forderung(self):
        from finance.models import DebitorenRechnung
        self._melden(selbstbehalt_traeger='mieter')
        f = self._fall()
        self.c.post(self.url, {'aktion': 'ueberwaelzen', 'fall': f.id, 'vertrag': self.v.id}, secure=True)
        r = DebitorenRechnung.objects.get(titel__startswith='Selbstbehalt')
        self.assertEqual((r.betrag, r.vertrag_id, r.status), (Decimal('500.00'), self.v.id, 'offen'))
        self.assertEqual(_saldo('1100'), Decimal('500.00'))
        self.assertEqual(_saldo('4000'), Decimal('-500.00'))
        f.refresh_from_db()
        self.assertEqual(f.selbstbehalt_rechnung_id, r.id)
        self.c.post(self.url, {'aktion': 'ueberwaelzen', 'fall': f.id, 'vertrag': self.v.id}, secure=True)
        self.assertEqual(DebitorenRechnung.objects.filter(titel__startswith='Selbstbehalt').count(), 1,
                         'Der Selbstbehalt wurde doppelt in Rechnung gestellt.')

    def test_vertrag_einer_anderen_einheit_wird_abgewiesen(self):
        from crm.models import Mieter
        from finance.models import DebitorenRechnung
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        self._melden(selbstbehalt_traeger='mieter')
        f = self._fall()
        e2 = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='Andere', typ='whg')
        m2 = Mieter.objects.create(typ='person', vorname='A', nachname='B')
        v2 = Mietvertrag.objects.create(mieter=m2, einheit=e2, beginn=date(2024, 1, 1), status='aktiv',
                                        netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'))
        self.c.post(self.url, {'aktion': 'ueberwaelzen', 'fall': f.id, 'vertrag': v2.id}, secure=True)
        self.assertFalse(DebitorenRechnung.objects.filter(titel__startswith='Selbstbehalt').exists())

    def test_geldbuchungen_nur_fuer_verwalter_nicht_fuer_sachbearbeitung(self):
        self._melden()
        f = self._fall()
        c2 = Client(); c2.force_login(_team_user('Sachbearbeiter'))
        c2.post(self.url, {'aktion': 'entschaedigung', 'fall': f.id, 'betrag': '740.00'}, secure=True)
        f.refresh_from_db()
        self.assertEqual(f.status, 'gemeldet')
        self.assertEqual(_saldo('1020'), Decimal('0.00'))

    def test_sachbearbeitung_darf_melden(self):
        from tickets.models import Versicherungsfall
        c2 = Client(); c2.force_login(_team_user('Sachbearbeiter'))
        c2.post(self.url, {'aktion': 'melden', 'police': self.police.id, 'schadensumme': '100'}, secure=True)
        self.assertTrue(Versicherungsfall.objects.filter(ticket=self.t).exists())

    def test_doppelte_meldung_und_fremde_police_werden_abgewiesen(self):
        from portfolio.models import Liegenschaft, Versicherung
        from tickets.models import Versicherungsfall
        self._melden(); self._melden()
        self.assertEqual(Versicherungsfall.objects.filter(ticket=self.t).count(), 1)
        Versicherungsfall.objects.all().delete()
        from core.tests._helfer import _test_organisation
        lg2 = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Fremd 1', plz='8000',
                                          ort='Zürich', versicherungswert=Decimal('1'))
        fremd = Versicherung.objects.create(liegenschaft=lg2, art='gebaeude', gesellschaft='X')
        self._melden(police=fremd.id)
        self.assertFalse(Versicherungsfall.objects.filter(ticket=self.t).exists())

    def test_melden_ohne_police_warnt_und_setzt_selbstbehalt_null(self):
        r = self._melden(police='')
        f = self._fall()
        self.assertEqual(f.selbstbehalt, Decimal('0.00'))
        self.assertIsNone(f.police)

    def test_abgelehnt_haelt_die_pendenz_geschlossen(self):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        self._melden()
        f = self._fall()
        self.c.post(self.url, {'aktion': 'ablehnen', 'fall': f.id}, secure=True)
        f.refresh_from_db()
        self.assertEqual(f.status, 'abgelehnt')
        generate_auto_pendenzen(horizont_tage=30)
        self.assertFalse(Pendenz.objects.filter(quelle=f'auto:versicherung:{self.t.pk}', erledigt=False).exists())

    def test_police_speichert_selbstbehalt_ueber_das_formular(self):
        from portfolio.models import Versicherung
        self.c.post(f'/neu/liegenschaften/{self.lg.id}/versicherung/',
                    {'art': 'wasser', 'gesellschaft': 'Mobiliar', 'selbstbehalt': '1000'}, secure=True)
        self.assertEqual(Versicherung.objects.get(gesellschaft='Mobiliar').selbstbehalt, Decimal('1000'))

    def test_seite_laedt(self):
        self.assertEqual(self.c.get(self.url, secure=True).status_code, 200)
        self._melden()
        self.assertContains(self.c.get(self.url, secure=True), 'S-2026-1')
