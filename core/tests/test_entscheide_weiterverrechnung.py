"""Entscheide vom 30.09.2026: MWST je Vertrag, Leerstand beim Eigentümer, Nutzungsentschädigung mit MWST."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user, _test_organisation


def _saldo(nummer, **filter):
    from finance.models import Buchung, Buchungskonto
    k = Buchungskonto.objects.filter(nummer=nummer).first()
    if k is None:          # Konto wurde nie bebucht
        return Decimal('0.00')
    soll = sum((b.betrag for b in Buchung.objects.filter(soll_konto=k, **filter)), Decimal('0'))
    haben = sum((b.betrag for b in Buchung.objects.filter(haben_konto=k, **filter)), Decimal('0'))
    return soll - haben


class MwstWeiterverrechnungTests(TestCase):

    def setUp(self):
        _seed_konten()
        from finance.booking import konto
        from finance.models import KreditorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.k = KreditorenRechnung.objects.create(
            lieferant='Sanitär AG', betrag=Decimal('1081.00'), status='bezahlt', liegenschaft=self.lg,
            konto=konto('4000'), mwst_satz=Decimal('8.1'))
        self.c = Client(); self.c.force_login(_team_user('Verwalter'))

    def _wv(self, **extra):
        d = {'vertrag_id': self.v.id, 'betrag': '1081.00', 'zuschlag': '0'}
        d.update(extra)
        return self.c.post(f'/neu/kreditoren/{self.k.id}/weiterverrechnen/', d, secure=True)

    def test_wohnraum_bucht_keine_ausgangssteuer_sondern_korrigiert_die_vorsteuer(self):
        self.assertFalse(self.v.mwst_pflichtig)
        self._wv()
        self.assertEqual(_saldo('2200'), Decimal('0.00'), 'Ausgangssteuer auf nicht steuerbare Leistung.')
        self.assertEqual(_saldo('1170'), Decimal('-81.00'), 'Vorsteuer ist nicht zurückgebucht.')

    def test_steuerpflichtiger_vertrag_bucht_ausgangssteuer(self):
        self.e.typ = 'gew'; self.e.save()  # MWST-Option nur bei Geschäftsraum (Art. 22 Abs. 2 lit. b MWSTG)
        self.v.mwst_pflichtig = True; self.v.mwst_satz = Decimal('8.1'); self.v.save()
        self._wv()
        self.assertEqual(_saldo('2200'), Decimal('-81.00'))
        self.assertEqual(_saldo('1170'), Decimal('0.00'))

    def test_zuschlag_traegt_mwst_bei_steuerpflichtigem_vertrag(self):
        from finance.models import DebitorenRechnung
        self.e.typ = 'gew'; self.e.save()  # MWST-Option nur bei Geschäftsraum (Art. 22 Abs. 2 lit. b MWSTG)
        self.v.mwst_pflichtig = True; self.v.mwst_satz = Decimal('8.1'); self.v.save()
        self._wv(zuschlag='100.00')
        r = DebitorenRechnung.objects.get(quell_kreditor=self.k)
        self.assertEqual(r.betrag, Decimal('1081.00') + Decimal('100.00') + Decimal('8.10'))
        self.assertEqual(r.weiterverrechnung_zuschlag, Decimal('108.10'))
        self.assertEqual(self.k.weiterverrechnet_betrag, Decimal('1081.00'),
                         'Der Zuschlag samt Steuer zählt nicht als durchgereichte Kosten.')
        self.assertEqual(_saldo('2200'), Decimal('-89.10'))

    def test_zuschlag_ohne_mwst_bei_wohnraum(self):
        from finance.models import DebitorenRechnung
        self._wv(zuschlag='100.00')
        self.assertEqual(DebitorenRechnung.objects.get(quell_kreditor=self.k).betrag, Decimal('1181.00'))

    def test_nutzungsentschaedigung_mit_mwst_bei_steuerpflichtigem_vertrag(self):
        from core.services import nutzungsentschaedigung as ne
        self.v.status = 'gekuendigt'; self.v.ende = date(2026, 2, 28)
        self.v.netto_mietzins = Decimal('1300.00'); self.v.nebenkosten = Decimal('180.00')
        self.e.typ = 'gew'; self.e.save()  # MWST-Option nur bei Geschäftsraum (Art. 22 Abs. 2 lit. b MWSTG)
        self.v.mwst_pflichtig = True; self.v.mwst_satz = Decimal('8.1'); self.v.save()
        r = ne.stelle(self.v, 2026, 3)
        self.assertEqual(r.betrag, Decimal('1480.00') + Decimal('119.88'))
        self.assertEqual(_saldo('2200', debitoren_rechnung=r), Decimal('-119.88'))

    def test_nutzungsentschaedigung_ohne_mwst_bei_wohnraum(self):
        from core.services import nutzungsentschaedigung as ne
        self.v.status = 'gekuendigt'; self.v.ende = date(2026, 2, 28)
        self.v.netto_mietzins = Decimal('1300.00'); self.v.nebenkosten = Decimal('180.00'); self.v.save()
        self.assertEqual(ne.stelle(self.v, 2026, 3).betrag, Decimal('1480.00'))


class LeerstandVerteilenTests(TestCase):

    def setUp(self):
        _seed_konten()
        from crm.models import Mieter
        from finance.booking import konto
        from finance.models import KreditorenRechnung
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Mietvertrag
        self.lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Verteil 1',
                                              plz='4500', ort='SO', versicherungswert=Decimal('1'))
        heute = date.today()
        self.vertraege = []
        for i in range(4):
            e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung=f'W{i}', typ='whg',
                                       flaeche_m2=Decimal('100'))
            if i == 3:
                continue          # W3 steht leer
            m = Mieter.objects.create(typ='person', vorname='M', nachname=str(i), strasse='X', plz='4500', ort='SO')
            status = 'gekuendigt' if i == 2 else 'aktiv'       # W2: gekündigt, wohnt aber noch
            ende = heute + timedelta(days=60) if i == 2 else None
            self.vertraege.append(Mietvertrag.objects.create(
                mieter=m, einheit=e, beginn=date(2024, 1, 1), ende=ende, status=status,
                netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0')))
        self.k = KreditorenRechnung.objects.create(
            lieferant='Gartenbau AG', betrag=Decimal('400.00'), status='bezahlt', liegenschaft=self.lg,
            konto=konto('4000'), datum=heute)
        self.c = Client(); self.c.force_login(_team_user('Verwalter'))

    def _verteilen(self):
        return self.c.post(f'/neu/kreditoren/{self.k.id}/weiterverrechnen/',
                           {'modus': 'verteilen', 'schluessel': 'm2'}, secure=True)

    def test_leerstand_bleibt_beim_eigentuemer_und_gekuendigte_zahlen_mit(self):
        from finance.models import DebitorenRechnung
        self._verteilen()
        rechnungen = DebitorenRechnung.objects.filter(quell_kreditor=self.k)
        self.assertEqual(rechnungen.count(), 3, 'Auch der gekündigte Mieter trägt mit.')
        self.assertEqual({r.betrag for r in rechnungen}, {Decimal('100.00')},
                         'Jeder der drei Mieter zahlt 25 %, nicht 33 %.')
        self.k.refresh_from_db()
        self.assertEqual(self.k.weiterverrechnung_eigentuemer, Decimal('100.00'))

    def test_eigentuemeranteil_haelt_die_rechnung_nicht_offen(self):
        self._verteilen()
        self.k.refresh_from_db()
        self.assertEqual(self.k.offen_weiterzuverrechnen, Decimal('0.00'))

    def test_ohne_leerstand_zahlen_die_mieter_alles(self):
        from portfolio.models import Einheit
        from crm.models import Mieter
        from rentals.models import Mietvertrag
        e = Einheit.objects.get(liegenschaft=self.lg, bezeichnung='W3')
        m = Mieter.objects.create(typ='person', vorname='M', nachname='3', strasse='X', plz='4500', ort='SO')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1), status='aktiv',
                                   netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'))
        self._verteilen()
        from finance.models import DebitorenRechnung
        self.assertEqual(sum(r.betrag for r in DebitorenRechnung.objects.filter(quell_kreditor=self.k)),
                         Decimal('400.00'))
        self.k.refresh_from_db()
        self.assertEqual(self.k.weiterverrechnung_eigentuemer, Decimal('0.00'))

    def test_beendeter_mieter_zaehlt_am_stichtag_nicht_mehr(self):
        """Vertrag, der vor dem Rechnungsdatum endete, trägt nicht mit: sein Anteil ist Leerstand."""
        v = self.vertraege[2]
        v.ende = date.today() - timedelta(days=5); v.save()
        from finance.models import DebitorenRechnung
        self._verteilen()
        self.assertEqual(DebitorenRechnung.objects.filter(quell_kreditor=self.k).count(), 2)
