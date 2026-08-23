"""Testmodul nebenkosten — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 9 Klassen, unveraendert uebernommen."""
from datetime import date
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (_test_organisation,
    _team_user, _basis_objekte, _seed_konten, Mieter, Organisation,
    Liegenschaft, Einheit, Mietvertrag, User)



class AkontoTests(TestCase):
    def test_akonto_uebernahme(self):
        lg, e, m, v = _basis_objekte()
        from finance.models import AbrechnungsPeriode
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='NK 2025',
                                              start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post(f'/neu/nebenkosten/{p.id}/akonto/', {'vertrag_id': [str(v.id)], f'akonto_{v.id}': '333'})
        self.assertEqual(r.status_code, 302)
        v.refresh_from_db()
        self.assertEqual(v.nebenkosten, Decimal('333'))


class NkRundungTests(TestCase):
    """Die angezeigten Kostenanteile müssen sich auf die Gesamtkosten summieren.

    Jeder Anteil wurde für sich gerundet, die Kontrollzahl summierte dagegen die
    UNGERUNDETEN Werte. Ergebnis: Die Abrechnung meldete «Differenz 0.00»,
    während die gedruckten Zeilen 1 Rappen zu wenig ergaben. Gemessen an 100.00
    auf drei gleiche Einheiten: 3 × 34.33 = 102.99 bei Total 103.00.

    Ein Mieter, der nachrechnet, hatte damit recht und die Abrechnung unrecht —
    und bei vielen Einheiten mit mehreren Kostenarten summieren sich die Rappen.
    """

    def _periode(self, anzahl, betrag, schluessel='m2'):
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse=f'Rundung {anzahl}', plz='4500',
                                         ort='SO', versicherungswert=Decimal('1'))
        for i in range(anzahl):
            e = Einheit.objects.create(liegenschaft=lg, bezeichnung=f'W{i:02d}',
                                       typ='whg', flaeche_m2=Decimal('50'))
            m = Mieter.objects.create(typ='person', vorname='M', nachname=str(i),
                                      strasse='W', plz='4500', ort='SO')
            Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal('1000'),
                                       nebenkosten=Decimal('0'), status='aktiv',
                                       nk_abrechnungsart='akonto')
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='2024',
                                              start_datum=date(2024, 1, 1),
                                              ende_datum=date(2024, 12, 31))
        NebenkostenBeleg.objects.create(periode=p, text='Hauswart', betrag=Decimal(betrag),
                                        datum=date(2024, 6, 1), verteilschluessel=schluessel)
        return p

    def test_anteile_summieren_sich_auf_die_gesamtkosten(self):
        from core.utils.billing import berechne_abrechnung
        for anzahl, betrag in [(3, '100.00'), (7, '1000.00'), (13, '555.55')]:
            with self.subTest(einheiten=anzahl):
                r = berechne_abrechnung(self._periode(anzahl, betrag).id)
                summe = sum((z['kosten_anteil'] for z in r['abrechnungen']), Decimal('0.00'))
                self.assertEqual(summe, r['total_kosten'],
                                 f"{anzahl} Einheiten: Anteile ergeben {summe}, "
                                 f"Total ist {r['total_kosten']}")

    def test_gemeldete_differenz_misst_die_angezeigten_werte(self):
        """Die Kontrollzahl rechnete auf ungerundeten Beträgen und meldete
        «geht auf», obwohl die Zeilen es nicht taten."""
        from core.utils.billing import berechne_abrechnung
        r = berechne_abrechnung(self._periode(3, '100.00').id)
        summe = sum((z['kosten_anteil'] for z in r['abrechnungen']), Decimal('0.00'))
        self.assertEqual(r['kontroll_summe'], summe)
        self.assertEqual(r['differenz'], Decimal('0.00'))

    def test_rundungsausgleich_bleibt_pro_zeile_stimmig(self):
        """Wandert ein Rappen auf eine Zeile, muss der Saldo mitgehen — sonst
        widerspricht die Zeile sich selbst (Kosten − Akonto ≠ Saldo)."""
        from core.utils.billing import berechne_abrechnung
        r = berechne_abrechnung(self._periode(7, '1000.00').id)
        for z in r['abrechnungen']:
            if z['typ'] == 'mieter_akonto':
                self.assertEqual(z['saldo'],
                                 (z['kosten_anteil'] - z['akonto']).quantize(Decimal('0.01')),
                                 f"Saldo passt nicht zu Kosten − Akonto bei {z['name']}")

    def test_ausgleich_verteilt_sich_und_haeuft_nicht_auf_einer_zeile(self):
        """Grösster Rest: die Differenz geht als EIN Rappen je Zeile weg, nicht
        als Klumpen auf die erste."""
        from core.utils.billing import berechne_abrechnung
        r = berechne_abrechnung(self._periode(3, '100.00').id)
        anteile = sorted(z['kosten_anteil'] for z in r['abrechnungen'])
        self.assertLessEqual(max(anteile) - min(anteile), Decimal('0.01'),
                             f"Anteile weichen mehr als einen Rappen ab: {anteile}")


class NkAbrechnungVersandTests(TestCase):
    def _periode(self):
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='NK 1', plz='8000', ort='ZH', versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='3.5 Zi', typ='whg', flaeche_m2=Decimal('80'))
        m = Mieter.objects.create(typ='person', vorname='Nina', nachname='Kosten',
                                  strasse='Weg 2', plz='8000', ort='ZH', email='nk@example.ch')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2023, 1, 1),
                                       netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                                       status='aktiv', nk_abrechnungsart='akonto')
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='NK 2023',
                                              start_datum=date(2023, 1, 1), ende_datum=date(2023, 12, 31))
        NebenkostenBeleg.objects.create(periode=p, text='Heizung', betrag=Decimal('1200'),
                                        datum=date(2023, 6, 1), verteilschluessel='m2')
        return lg, e, m, v, p

    def test_sammel_pdf_und_ablage_ins_portal(self):
        from rentals.models import Dokument
        from django.contrib.auth import get_user_model
        User = get_user_model()
        lg, e, m, v, p = self._periode()
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.post(f'/neu/nebenkosten/{p.id}/versand/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        # Einzel-Abrechnung liegt in der Akte -> Portal
        d = Dokument.objects.filter(vertrag=v, bezeichnung__icontains='Nebenkostenabrechnung').first()
        self.assertIsNotNone(d)
        u = User.objects.create_user(username='nk_mieter', password='x'); m.benutzer = u; m.save()
        mc = Client(); mc.force_login(u)
        self.assertIn('Nebenkostenabrechnung', mc.get('/mieter/dokumente/').content.decode())

    def test_pdf_generator_einzeln(self):
        from core.services.nk_abrechnung import generate_nk_pdf_einzeln
        k = {'verwaltung': None, 'periode': 'NK 2023', 'objekt': 'Weg 2',
             'adresse': ['Nina Kosten', 'Weg 2', '8000 ZH'],
             'positionen': [{'kategorie': 'Heizung', 'betrag': Decimal('1200'), 'schluessel': 'm2'}],
             'total_kosten': Decimal('1200'), 'kosten_anteil': Decimal('1200'),
             'akonto': Decimal('2400'), 'saldo': Decimal('-1200'), 'nachzahlung': False}
        pdf = generate_nk_pdf_einzeln(k)
        self.assertTrue(pdf.startswith(b'%PDF'))
        # Nachzahlungs-Variante (anderer Rechts-/Fristhinweis-Zweig)
        k2 = {**k, 'akonto': Decimal('800'), 'saldo': Decimal('400'), 'nachzahlung': True}
        self.assertTrue(generate_nk_pdf_einzeln(k2).startswith(b'%PDF'))


class NkNachzahlungQrTests(TestCase):
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren

    def test_nachzahlung_wird_offene_qr_rechnung_im_portal(self):
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg, DebitorenRechnung
        from django.contrib.auth import get_user_model
        User = get_user_model()
        _seed_konten()
        # `_test_organisation(**felder)` statt `create`: Es darf nur EINE
        # Verwaltung geben. Der QR-Pfad liest `Organisation.objects.first()`,
        # und eine zweite waere nicht die, die hier konfiguriert wird — der
        # Test bekaeme 404 statt 200, weil die IBAN an der falschen haengt.
        vw = _test_organisation(firma='V AG', strasse='W 1', plz='8000', ort='ZH',
                                iban='CH9300762011623852957')
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='NKQ 1', plz='8000', ort='ZH', versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='3.5 Zi', typ='whg', flaeche_m2=Decimal('80'))
        m = Mieter.objects.create(typ='person', nachname='Nach', email='n@example.ch')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2023, 1, 1),
                                       netto_mietzins=Decimal('1500'), nebenkosten=Decimal('0'),
                                       status='aktiv', nk_abrechnungsart='akonto')
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='NK 2023',
                                              start_datum=date(2023, 1, 1), ende_datum=date(2023, 12, 31))
        NebenkostenBeleg.objects.create(periode=p, text='Heizung', betrag=Decimal('1200'),
                                        datum=date(2023, 6, 1), verteilschluessel='m2')
        team = _team_user()
        c = Client(); c.force_login(team)
        c.post(f'/neu/nebenkosten/{p.id}/verbuchen/')
        r = DebitorenRechnung.objects.filter(vertrag=v, titel__icontains='Nachzahlung').first()
        self.assertIsNotNone(r)
        self.assertEqual(r.status, 'offen')
        self.assertEqual(len(r.qr_referenz), 27)
        # Mieter sieht die Nachzahlung + kann QR-Einzahlschein abrufen
        u = User.objects.create_user(username='nq_mieter', password='x'); m.benutzer = u; m.save()
        mc = Client(); mc.force_login(u)
        self.assertContains(mc.get('/mieter/rechnungen/'), 'Nachzahlung')
        pdf = mc.get(f'/mieter/rechnung/{r.id}/')
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))


class NkAbrechnungSplitTests(TestCase):
    """P4: Die NK-Abrechnung ist split-aware — nur der HNK-Anteil einer
    aufgeteilten Kreditorenrechnung fliesst in die Mieterabrechnung, nicht der
    volle Betrag. Nicht-aufgeteilte HNK-Rechnungen bleiben unverändert."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def _setup(self):
        from finance.booking import ensure_kontenplan
        from portfolio.models import Liegenschaft, Einheit
        from crm.models import Mieter
        from finance.models import AbrechnungsPeriode
        ensure_kontenplan()
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='NKweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='W1', typ='whg',
                                   flaeche_m2=Decimal('100'), nettomiete_aktuell=Decimal('1000'))
        m = Mieter.objects.create(typ='person', vorname='Anna', nachname='NK',
                                  strasse='X', plz='8000', ort='Zürich')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                   netto_mietzins=Decimal('1000'), nebenkosten=Decimal('100'),
                                   status='aktiv')
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='2025',
                                              start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        return lg, e, p

    def test_split_nur_hnk_anteil_in_abrechnung(self):
        from finance.models import KreditorenRechnung, KreditorPosition, Buchungskonto
        from core.utils.billing import berechne_abrechnung
        lg, e, p = self._setup()
        k = KreditorenRechnung.objects.create(lieferant='Handwerk AG', betrag=Decimal('300.00'),
                                              liegenschaft=lg, is_hnk_relevant=True,
                                              status='freigegeben', datum=date(2025, 6, 1))
        # 100 HNK (Hauswartung 4120) + 200 Unterhalt (4000, nicht HNK)
        KreditorPosition.objects.create(rechnung=k, konto=Buchungskonto.objects.get(nummer='4120'),
                                        betrag=Decimal('100.00'), is_hnk_relevant=True)
        KreditorPosition.objects.create(rechnung=k, konto=Buchungskonto.objects.get(nummer='4000'),
                                        betrag=Decimal('200.00'), is_hnk_relevant=False)
        r = berechne_abrechnung(p.id)
        fibu = [d for d in r['belege_details'] if d.get('quelle') == 'FiBu']
        self.assertEqual(sum(Decimal(str(d['betrag'])) for d in fibu), Decimal('100.00'))
        # Gesamtkosten (inkl. Honorar) klar unter 300 → der 200-Anteil fliesst NICHT ein
        self.assertLess(Decimal(str(r['total_kosten'])), Decimal('150.00'))

    def test_ohne_split_voller_betrag(self):
        from finance.models import KreditorenRechnung, Buchungskonto
        from core.utils.billing import berechne_abrechnung
        lg, e, p = self._setup()
        KreditorenRechnung.objects.create(lieferant='Hauswart AG', betrag=Decimal('200.00'),
                                          liegenschaft=lg, is_hnk_relevant=True,
                                          konto=Buchungskonto.objects.get(nummer='4120'),
                                          status='freigegeben', datum=date(2025, 6, 1))
        r = berechne_abrechnung(p.id)
        fibu = [d for d in r['belege_details'] if d.get('quelle') == 'FiBu']
        self.assertEqual(sum(Decimal(str(d['betrag'])) for d in fibu), Decimal('200.00'))

    def test_total_kosten_property_stimmt_mit_engine(self):
        from finance.models import KreditorenRechnung, Buchungskonto
        from core.utils.billing import berechne_abrechnung
        lg, e, p = self._setup()
        KreditorenRechnung.objects.create(lieferant='Hauswart AG', betrag=Decimal('200.00'),
                                          liegenschaft=lg, is_hnk_relevant=True,
                                          konto=Buchungskonto.objects.get(nummer='4120'),
                                          status='freigegeben', datum=date(2025, 6, 1))
        r = berechne_abrechnung(p.id)
        self.assertEqual(p.total_kosten, Decimal(str(r['total_kosten'])))


class NkEndToEndTests(TestCase):
    """QA: kompletter NK-Kreislauf mit split-aware Kosten — Geld-Erhaltung
    (Summe Mieteranteile == Gesamtkosten), Nicht-HNK-Anteil bleibt draussen,
    Verbuchung erzeugt die richtigen Nachzahlungen."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def _setup(self):
        from finance.booking import ensure_kontenplan
        from portfolio.models import Liegenschaft, Einheit
        from crm.models import Mieter
        from finance.models import AbrechnungsPeriode
        ensure_kontenplan()
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='E2Eweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        verts = []
        for name, m2 in [('A', Decimal('60')), ('B', Decimal('40'))]:
            e = Einheit.objects.create(liegenschaft=lg, bezeichnung=name, typ='whg',
                                       flaeche_m2=m2, nettomiete_aktuell=Decimal('1000'))
            m = Mieter.objects.create(typ='person', vorname=name, nachname='E2E',
                                      strasse='X', plz='8000', ort='Zürich')
            v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                           netto_mietzins=Decimal('1000'), nebenkosten=Decimal('50'),
                                           status='aktiv', aktiv=True)
            verts.append(v)
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='2025',
                                              start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        return lg, p, verts

    def test_kreislauf_geld_erhaltung_und_verbuchung(self):
        from finance.models import KreditorenRechnung, KreditorPosition, Buchungskonto, DebitorenRechnung
        from core.utils.billing import berechne_abrechnung
        lg, p, verts = self._setup()
        # Kreditor 1: Hauswartung 1200 (voll HNK, m²)
        KreditorenRechnung.objects.create(lieferant='Hauswart AG', betrag=Decimal('1200.00'),
                                          liegenschaft=lg, is_hnk_relevant=True,
                                          konto=Buchungskonto.objects.get(nummer='4120'),
                                          status='freigegeben', datum=date(2025, 6, 1))
        # Kreditor 2: 500 gesplittet — 300 Allgemeinstrom (HNK) + 200 Unterhalt (nicht HNK)
        k2 = KreditorenRechnung.objects.create(lieferant='Misch AG', betrag=Decimal('500.00'),
                                               liegenschaft=lg, is_hnk_relevant=True,
                                               status='freigegeben', datum=date(2025, 6, 1))
        KreditorPosition.objects.create(rechnung=k2, konto=Buchungskonto.objects.get(nummer='4130'),
                                        betrag=Decimal('300.00'), is_hnk_relevant=True)
        KreditorPosition.objects.create(rechnung=k2, konto=Buchungskonto.objects.get(nummer='4000'),
                                        betrag=Decimal('200.00'), is_hnk_relevant=False)

        r = berechne_abrechnung(p.id)
        total = Decimal(str(r['total_kosten']))
        # HNK 1200 + 300 = 1500, + 3% Honorar = 1545. Die 200 Unterhalt sind NICHT drin.
        self.assertEqual(total, Decimal('1545.00'))
        # Geld-Erhaltung: Summe der Mieteranteile == Gesamtkosten (keine Leerstände hier)
        mieter = [a for a in r['abrechnungen'] if a.get('typ') != 'leerstand']
        summe_anteile = sum(Decimal(str(a['kosten_anteil'])) for a in mieter)
        self.assertEqual(summe_anteile, total)
        # 60/40-Verteilung
        anteile = sorted(Decimal(str(a['kosten_anteil'])) for a in mieter)
        self.assertEqual(anteile, [Decimal('618.00'), Decimal('927.00')])

        # Verbuchung: beide zahlen nach (927/618 > 600 Akonto)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/nebenkosten/{p.id}/verbuchen/')
        p.refresh_from_db()
        self.assertTrue(p.abgeschlossen)
        nachzahlungen = DebitorenRechnung.objects.filter(titel__startswith='NK-Abrechnung Nachzahlung')
        self.assertEqual(nachzahlungen.count(), 2)
        # 927-600=327, 618-600=18 → total 345
        self.assertEqual(sum(d.betrag for d in nachzahlungen), Decimal('345.00'))

    def test_verbuchung_ist_idempotent(self):
        from finance.models import KreditorenRechnung, Buchungskonto, DebitorenRechnung
        lg, p, verts = self._setup()
        KreditorenRechnung.objects.create(lieferant='Hauswart AG', betrag=Decimal('1200.00'),
                                          liegenschaft=lg, is_hnk_relevant=True,
                                          konto=Buchungskonto.objects.get(nummer='4120'),
                                          status='freigegeben', datum=date(2025, 6, 1))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/nebenkosten/{p.id}/verbuchen/')
        n1 = DebitorenRechnung.objects.filter(titel__startswith='NK-Abrechnung').count()
        # Zweiter Versuch darf keine Doppel-Debitoren erzeugen (Periode abgeschlossen)
        c.post(f'/neu/nebenkosten/{p.id}/verbuchen/')
        n2 = DebitorenRechnung.objects.filter(titel__startswith='NK-Abrechnung').count()
        self.assertEqual(n1, n2)


class NkVertragsStatusTests(TestCase):
    """QA-Fund: die NK-Abrechnung muss mitten in der Periode ausgezogene
    (gekündigte) Mieter einbeziehen (sie bewohnten das Objekt) und Entwürfe
    ausschliessen."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def _setup(self):
        from finance.booking import ensure_kontenplan
        from portfolio.models import Liegenschaft, Einheit
        from finance.models import AbrechnungsPeriode, KreditorenRechnung, Buchungskonto
        ensure_kontenplan()
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Statusweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='W1', typ='whg',
                                   flaeche_m2=Decimal('100'), nettomiete_aktuell=Decimal('1000'))
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='2025',
                                              start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        KreditorenRechnung.objects.create(lieferant='Hauswart AG', betrag=Decimal('1000.00'),
                                          liegenschaft=lg, is_hnk_relevant=True,
                                          konto=Buchungskonto.objects.get(nummer='4120'),
                                          status='freigegeben', datum=date(2025, 6, 1))
        return lg, e, p

    def _mieter(self, name):
        from crm.models import Mieter
        return Mieter.objects.create(typ='person', vorname=name, nachname='S',
                                     strasse='X', plz='8000', ort='Zürich')

    def test_gekuendigter_mieter_wird_abgerechnet(self):
        from core.utils.billing import berechne_abrechnung
        lg, e, p = self._setup()
        # Ausgezogen per 30.06.2025 → gekündigt, aktiv=False
        Mietvertrag.objects.create(mieter=self._mieter('Weg'), einheit=e, beginn=date(2024, 1, 1),
                                   ende=date(2025, 6, 30), netto_mietzins=Decimal('1000'),
                                   nebenkosten=Decimal('50'), status='gekuendigt', aktiv=False)
        r = berechne_abrechnung(p.id)
        mieter = [a for a in r['abrechnungen'] if a.get('typ') != 'leerstand']
        # Der gekündigte Mieter muss in der Abrechnung erscheinen (nicht als Leerstand)
        self.assertTrue(any(a.get('mieter') == 'Weg S' or 'Weg' in str(a.get('name', '')) for a in mieter),
                        msg=f"Gekündigter Mieter fehlt: {[a.get('name') for a in mieter]}")

    def test_entwurf_wird_nicht_abgerechnet(self):
        from core.utils.billing import berechne_abrechnung
        lg, e, p = self._setup()
        Mietvertrag.objects.create(mieter=self._mieter('Draft'), einheit=e, beginn=date(2024, 1, 1),
                                   netto_mietzins=Decimal('1000'), nebenkosten=Decimal('50'),
                                   status='entwurf', aktiv=True)   # Entwurf, aber aktiv=True (Default)
        r = berechne_abrechnung(p.id)
        namen = [str(a.get('name', '')) for a in r['abrechnungen']]
        self.assertFalse(any('Draft' in n for n in namen),
                         msg=f"Entwurf fälschlich abgerechnet: {namen}")


class NebenkostenGTests(TestCase):
    """Live-Test G: HNK — Snapshot-Einfrieren beim Verbuchen + Warnung bei fehlender Fläche."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def _periode(self, lg, betrag='1200'):
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg
        p = AbrechnungsPeriode.objects.create(
            liegenschaft=lg, bezeichnung='NK 2024',
            start_datum=date(2024, 1, 1), ende_datum=date(2024, 12, 31))
        b = NebenkostenBeleg.objects.create(
            periode=p, text='Hauswartung', kategorie='hauswart',
            verteilschluessel='m2', betrag=Decimal(betrag), datum=date(2024, 6, 1))
        return p, b

    def test_g_fehlende_flaeche_warnt(self):
        from core.utils.billing import berechne_abrechnung
        lg, e, m, v = _basis_objekte()   # Einheit ohne flaeche_m2 (None)
        p, b = self._periode(lg)
        r = berechne_abrechnung(p.id)
        self.assertTrue(r.get('warnungen'), 'keine Warnung trotz fehlender Fläche')
        self.assertIn('Fläche', r['warnungen'][0])

    def test_g_verbuchte_abrechnung_ist_eingefroren(self):
        from finance.booking import ensure_kontenplan
        from core.utils.billing import hole_abrechnung, berechne_abrechnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        e.flaeche_m2 = Decimal('100'); e.save()
        v.nk_abrechnungsart = 'akonto'; v.nebenkosten = Decimal('50'); v.save()
        p, b = self._periode(lg, '1200')
        vor = Decimal(str(hole_abrechnung(p)['total_kosten']))
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post(f'/neu/nebenkosten/{p.id}/verbuchen/', {})
        p.refresh_from_db()
        self.assertTrue(p.abgeschlossen)
        self.assertTrue(p.snapshot_json.strip())
        # Beleg NACH dem Verbuchen ändern → Snapshot bleibt, Live würde springen.
        b.betrag = Decimal('6000'); b.save()
        nach_snapshot = Decimal(str(hole_abrechnung(p)['total_kosten']))
        nach_live = Decimal(str(berechne_abrechnung(p.id)['total_kosten']))
        self.assertEqual(nach_snapshot, vor, 'Snapshot driftete nach Belegänderung')
        self.assertNotEqual(nach_live, vor, 'Testaufbau: Beleg wurde nicht wirksam geändert')


class NebenkostenPersonenTests(TestCase):
    """Live-Test G: Verteilschlüssel «Personen» — Beleg wird nach Personenzahl × Tage verteilt."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def test_g_personen_verteilung_proportional(self):
        from finance.booking import ensure_kontenplan
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg
        from crm.models import Organisation, Mieter
        from core.utils.billing import berechne_abrechnung
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        ensure_kontenplan()
        # Honorar auf 0 → nur der Personen-Pool wirkt (saubere Prüfung)
        # Siehe oben: nur EINE Verwaltung. Sonst greift das Honorar der
        # ersten (6 %) statt der hier gesetzten 0 % — der Anteil waere 106.00
        # statt 100.00, und der Test pruefte etwas anderes als er meint.
        _test_organisation(firma='V AG', strasse='W 1', plz='8000', ort='Zürich',
                           nk_honorar_prozent=Decimal('0'))
        lg, e1, m1, v1 = _basis_objekte()
        v1.anzahl_personen = 1; v1.nebenkosten = Decimal('0'); v1.save()
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='B', typ='whg',
                                    nettomiete_aktuell=Decimal('1500'), nebenkosten_aktuell=Decimal('0'),
                                    flaeche_m2=Decimal('50'))
        m2 = Mieter.objects.create(typ='person', vorname='Bea', nachname='Zweit',
                                   strasse='S', plz='8000', ort='Zürich')
        v2 = Mietvertrag.objects.create(mieter=m2, einheit=e2, beginn=date(2024, 1, 1),
                                        netto_mietzins=Decimal('1500'), nebenkosten=Decimal('0'),
                                        status='aktiv', anzahl_personen=3)
        e1.flaeche_m2 = Decimal('50'); e1.save()
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='NK 2024',
                                              start_datum=date(2024, 1, 1), ende_datum=date(2024, 12, 31))
        NebenkostenBeleg.objects.create(periode=p, text='Kehricht', kategorie='kehricht',
                                        verteilschluessel='personen', betrag=Decimal('400'),
                                        datum=date(2024, 6, 1))
        r = berechne_abrechnung(p.id)
        anteil = {a['vertrag_id']: Decimal(str(a['kosten_anteil']))
                  for a in r['abrechnungen'] if a.get('vertrag_id')}
        # 1 vs. 3 Personen → 100 / 300 (Pool 400)
        self.assertEqual(anteil[v1.id], Decimal('100.00'))
        self.assertEqual(anteil[v2.id], Decimal('300.00'))
        self.assertEqual(Decimal(str(r['differenz'])), Decimal('0.00'))
