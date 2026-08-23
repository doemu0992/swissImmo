"""Testmodul berichte — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 9 Klassen, unveraendert uebernommen."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (_test_organisation,
    _team_user, _basis_objekte, _seed_konten, Mieter, Eigentuemer,
    Organisation, Liegenschaft, Einheit, Mietvertrag, User)



class SerienbriefTests(TestCase):
    def test_pdf_platzhalter_und_seiten(self):
        from core.services.serienbrief import generate_serienbrief_pdf
        absender = {'firma': 'Verwaltung AG', 'strasse': 'Weg 1', 'plz': '8000', 'ort': 'Zürich'}
        emp = [
            {'name': 'Herr A', 'anrede': 'Sehr geehrter Herr A', 'strasse': 'S 1', 'plz': '8000', 'ort': 'Zürich', 'objekt': 'O1', 'liegenschaft': 'L1'},
            {'name': 'Frau B', 'anrede': 'Sehr geehrte Frau B', 'strasse': 'S 2', 'plz': '8001', 'ort': 'Bern', 'objekt': 'O2', 'liegenschaft': 'L2'},
        ]
        pdf = generate_serienbrief_pdf(absender, 'Betreff {name}', 'Hallo {anrede}, Objekt {objekt}.', emp)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 1000)

    def test_serienbrief_view(self):
        _lg, _e, m, _v = _basis_objekte()
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post('/neu/kommunikation/serienbrief/', {
            'betreff': 'Info', 'text': '{anrede}\n\n{liegenschaft}', 'empfaenger_id': [str(m.id)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')


class AblageTests(TestCase):
    def test_ablegen_dedup(self):
        from core.services.ablage import ablegen
        from rentals.models import Dokument
        _lg, _e, _m, v = _basis_objekte()
        d1 = ablegen(b'%PDF-1', 'Kündigung', vertrag=v, dedup=True)
        d2 = ablegen(b'%PDF-2', 'Kündigung', vertrag=v, dedup=True)
        self.assertIsNotNone(d1)
        self.assertEqual(d1.id, d2.id)
        self.assertEqual(Dokument.objects.filter(vertrag=v, bezeichnung='Kündigung').count(), 1)
        self.assertEqual(d1.mieter_id, v.mieter_id)


class SteuerauszugTests(TestCase):
    """Eigentümer-Steuerauszug: Erträge − Ausgaben − AfA je Liegenschaft."""

    def _setup(self):
        from finance.models import Zahlungseingang, KreditorenRechnung, Anlage, Abschreibung
        from crm.models import Handwerker  # noqa
        lg, e, m, v = _basis_objekte()
        md = Eigentuemer.objects.create(firma_oder_name='Eig AG')
        lg.eigentuemer = md; lg.save()
        u = User.objects.create_user(username='eig_steuer', password='x'); md.benutzer = u; md.save()
        # Ertrag: Zahlungseingang 2024
        Zahlungseingang.objects.create(vertrag=v, betrag=Decimal('20000'),
                                       datum_eingang=date(2024, 6, 1), status='verbucht')
        # Ausgabe: Kreditorenrechnung 2024
        KreditorenRechnung.objects.create(liegenschaft=lg, lieferant='Sanitär',
                                          betrag=Decimal('5000'), datum=date(2024, 3, 1), status='bezahlt')
        # AfA: Anlage + Abschreibung 2024
        anl = Anlage.objects.create(liegenschaft=lg, bezeichnung='Heizung',
                                    anschaffungswert=Decimal('30000'), anschaffungsdatum=date(2020, 1, 1),
                                    nutzungsdauer_jahre=10)
        Abschreibung.objects.create(anlage=anl, jahr=2024, betrag=Decimal('3000'), datum=date(2024, 12, 31))
        return md, lg, u

    def test_daten_rechnen_korrekt(self):
        from core.services.steuerauszug import steuerauszug_daten
        md, lg, u = self._setup()
        d = steuerauszug_daten(md, 2024)
        z = d['zeilen'][0]
        self.assertEqual(z['ertrag'], Decimal('20000'))
        self.assertEqual(z['ausgaben'], Decimal('5000'))
        self.assertEqual(z['afa'], Decimal('3000'))
        self.assertEqual(z['netto'], Decimal('12000'))   # 20000 - 5000 - 3000
        self.assertEqual(d['total']['netto'], Decimal('12000'))

    def test_pdf_und_portal_button(self):
        md, lg, u = self._setup()
        c = Client(); c.force_login(u)
        r = c.get('/portal/steuerauszug/?jahr=2024')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        # Button im Portal sichtbar
        self.assertContains(c.get('/portal/'), 'Steuerauszug')

    def test_fremder_eigentuemer_kein_zugriff(self):
        md, lg, u = self._setup()
        # Anderer Eigentümer sieht die Zahlen nicht in seinem Auszug
        md2 = Eigentuemer.objects.create(firma_oder_name='Andere AG')
        u2 = User.objects.create_user(username='eig_andere', password='x'); md2.benutzer = u2; md2.save()
        from core.services.steuerauszug import steuerauszug_daten
        d = steuerauszug_daten(md2, 2024)
        self.assertEqual(d['total']['ertrag'], Decimal('0'))


class SerienbriefMitmieterTests(TestCase):
    def _paar(self):
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Paar 9', plz='3000', ort='Bern', versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='4.5 Zi', typ='whg')
        m1 = Mieter.objects.create(typ='person', anrede='Herr', vorname='Hans', nachname='Erst',
                                   strasse='Weg 1', plz='3000', ort='Bern')
        m2 = Mieter.objects.create(typ='person', anrede='Frau', vorname='Anna', nachname='Zweit')
        v = Mietvertrag.objects.create(mieter=m1, mitmieter=m2, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal('1200'), nebenkosten=Decimal('150'), status='aktiv')
        return lg, e, m1, m2, v

    def test_beide_namen_und_kein_doppelbrief(self):
        from rentals.models import Dokument
        lg, e, m1, m2, v = self._paar()
        team = _team_user()
        c = Client(); c.force_login(team)
        # beide Personen ausgewählt -> nur EIN Brief, beide Namen adressiert
        r = c.post('/neu/kommunikation/serienbrief/', {
            'betreff': 'Hausordnung', 'text': 'Guten Tag {name}', 'empfaenger_id': [str(m1.id), str(m2.id)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        # genau eine Ablage am Vertrag (nicht zwei)
        docs = Dokument.objects.filter(vertrag=v, kategorie='korrespondenz')
        self.assertEqual(docs.count(), 1)

    def test_kommunikation_lg_auswahl_und_suche(self):
        lg, e, m1, m2, v = self._paar()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/kommunikation/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # Liegenschafts-Schnellwahl + Suche vorhanden, Liegenschaft in Wahlliste
        self.assertIn('lgWaehlen()', body)
        self.assertIn('empSuche()', body)
        self.assertIn('id="emp-search"', body)
        self.assertTrue(len(r.context['liegenschaften_wahl']) >= 1)
        # Empfänger NICHT automatisch vorausgewählt (kein 'checked' am emp-check)
        self.assertNotIn('class="emp-check accent-indigo-600" value="{}" checked'.format(m1.id), body)
        self.assertIn('data-lg="{}"'.format(lg.id), body)

    def test_zweitperson_sieht_brief_im_portal(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        lg, e, m1, m2, v = self._paar()
        team = _team_user()
        tc = Client(); tc.force_login(team)
        tc.post('/neu/kommunikation/serienbrief/', {
            'betreff': 'Info Paar', 'text': 'Hallo {name}', 'empfaenger_id': [str(m1.id)]})
        # Mitmieter (Zweitperson) mit Portal-Login sieht den Brief
        u = User.objects.create_user(username='zweit_portal', password='x'); m2.benutzer = u; m2.save()
        mc = Client(); mc.force_login(u)
        self.assertIn('Brief: Info Paar', mc.get('/mieter/dokumente/').content.decode())


def _seed_konten():
    from finance.models import Buchungskonto
    for nr, bez, typ in [('1020', 'Bank', 'bilanz'), ('1100', 'Debitoren', 'bilanz'),
                         ('3000', 'Mietertrag', 'ertrag'), ('3020', 'NK-Akonto', 'ertrag')]:
        Buchungskonto.objects.get_or_create(nummer=nr, defaults={'bezeichnung': bez, 'typ': typ})


class EigentuemerKontokorrentTests(TestCase):
    """Eigentümer-Kontokorrent: Ergebnis − Auszahlungen, korrekte Passiv-Buchung."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def _setup(self):
        from crm.models import Eigentuemer
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        md = Eigentuemer.objects.create(firma_oder_name='Eigentum AG', iban='CH9300762011623852957')
        lg, e, m, v = _basis_objekte()
        lg.eigentuemer = md
        lg.save()
        buche('1020', '3000', Decimal('2000'), 'Miete', liegenschaft=lg)      # Ertrag 2000
        buche('4000', '1020', Decimal('500'), 'Reparatur', liegenschaft=lg)   # Aufwand 500
        return md, lg

    def test_2850_ist_passivkonto(self):
        from finance.booking import konto
        k = konto('2850')
        self.assertEqual(k.typ, 'passiv')

    def test_kontokorrent_saldo(self):
        from core.services.eigentuemer_kontokorrent import kontokorrent
        md, lg = self._setup()
        kk = kontokorrent(md)
        self.assertEqual(kk['ertrag'], Decimal('2000.00'))
        self.assertEqual(kk['aufwand'], Decimal('500.00'))
        self.assertEqual(kk['ergebnis'], Decimal('1500.00'))
        self.assertEqual(kk['ausbezahlt'], Decimal('0.00'))
        self.assertEqual(kk['offen'], Decimal('1500.00'))

    def test_auszahlung_bucht_und_reduziert_offen(self):
        from finance.models import Buchung, EigentuemerAuszahlung
        from core.services.eigentuemer_kontokorrent import kontokorrent
        md, lg = self._setup()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post(f'/neu/mandate/{md.id}/auszahlung/', {'betrag': '1000', 'konto_nummer': '1020'})
        self.assertEqual(r.status_code, 302)
        # Buchung Soll 2850 / Haben 1020
        self.assertTrue(Buchung.objects.filter(soll_konto__nummer='2850', haben_konto__nummer='1020',
                                               betrag=Decimal('1000.00')).exists())
        self.assertEqual(EigentuemerAuszahlung.objects.filter(eigentuemer=md, status='verbucht').count(), 1)
        kk = kontokorrent(md)
        self.assertEqual(kk['ausbezahlt'], Decimal('1000.00'))
        self.assertEqual(kk['offen'], Decimal('500.00'))

    def test_bilanz_bleibt_ausgeglichen_nach_auszahlung(self):
        """Auszahlung via 2850 (Passiv) mindert das Eigenkapital — die Bilanz muss
        aufgehen (Aktiven == Passiven inkl. Ergebnis)."""
        md, lg = self._setup()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/mandate/{md.id}/auszahlung/', {'betrag': '400', 'konto_nummer': '1020'})
        r = c.get('/neu/buchhaltung/')
        self.assertEqual(r.context['bilanz_differenz'], Decimal('0.00'))
        # 2850 erscheint auf der Passivseite mit negativem Saldo (Eigenkapital-Minderung)
        p2850 = [p for p in r.context['passiven'] if p['nummer'] == '2850']
        self.assertTrue(p2850)
        self.assertEqual(p2850[0]['saldo'], Decimal('-400.00'))

    def test_kontokorrent_view_rendert(self):
        md, lg = self._setup()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.get(f'/neu/mandate/{md.id}/kontokorrent/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Kontokorrent Eigentümer')
        self.assertContains(r, 'Eigentum AG')
        self.assertContains(r, 'Auszahlung erfassen')

    def test_kontokorrent_pdf(self):
        md, lg = self._setup()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.get(f'/neu/mandate/{md.id}/kontokorrent/?pdf=1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertGreater(len(r.content), 1000)


class BerichteHubTests(TestCase):
    """Zentrale Berichte-Seite bündelt alle Reports."""

    def test_seite_zeigt_berichte_und_kennzahlen(self):
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete',
                                         betrag=Decimal('1700'), datum=date(2025, 1, 1),
                                         faellig_am=date(2025, 1, 1), status='offen')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/berichte/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Berichte')
        self.assertContains(r, 'Mieterspiegel')
        self.assertContains(r, 'Debitoren-Altersstruktur')
        self.assertContains(r, '/neu/mahnwesen/aging/')
        self.assertContains(r, '/neu/mieterspiegel/')
        # Kennzahl (offene Forderung) erscheint
        self.assertContains(r, 'offen')


class AuswertungTests(TestCase):
    """Interaktive Auswertung: Monatsverlauf + Liegenschafts-Vergleich, filterbar."""

    def test_mietertrag_monatsverlauf(self):
        from finance.booking import buche
        lg, e, m, v = _basis_objekte()
        buche('1020', '3000', Decimal('1500'), 'Miete Jan', datum=date(2025, 1, 15), liegenschaft=lg)
        buche('1020', '3000', Decimal('1500'), 'Miete Mär', datum=date(2025, 3, 10), liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/auswertung/?typ=mietertrag&jahr=2025')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['total'], Decimal('3000.00'))
        jan = next(x for x in r.context['monate'] if x['m'] == 1)
        self.assertEqual(jan['wert'], Decimal('1500.00'))
        self.assertEqual(jan['pct'], 100)   # Januar = Maximum

    def test_ergebnis_negativ(self):
        from finance.booking import buche
        lg, e, m, v = _basis_objekte()
        buche('1020', '3000', Decimal('1000'), 'Miete', datum=date(2025, 2, 1), liegenschaft=lg)
        buche('4000', '1020', Decimal('1500'), 'Reparatur', datum=date(2025, 2, 5), liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/auswertung/?typ=ergebnis&jahr=2025')
        self.assertEqual(r.context['total'], Decimal('-500.00'))
        feb = next(x for x in r.context['monate'] if x['m'] == 2)
        self.assertTrue(feb['neg'])

    def test_liegenschafts_vergleich(self):
        from finance.booking import buche
        from portfolio.models import Liegenschaft
        lg, e, m, v = _basis_objekte()
        lg2 = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Zweitweg 2', plz='8000', ort='Zürich',
                                          versicherungswert=Decimal('500000'))
        buche('1020', '3000', Decimal('2000'), 'A', datum=date(2025, 1, 1), liegenschaft=lg)
        buche('1020', '3000', Decimal('800'), 'B', datum=date(2025, 1, 1), liegenschaft=lg2)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/auswertung/?typ=mietertrag&jahr=2025')   # ohne LG-Filter
        self.assertEqual(len(r.context['lg_rows']), 2)
        self.assertEqual(r.context['lg_rows'][0]['lg'].id, lg.id)   # grösster zuerst
        self.assertEqual(r.context['lg_rows'][0]['pct'], 100)

    def test_lg_filter_kein_vergleich(self):
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/auswertung/?jahr=2025&lg={lg.id}')
        self.assertEqual(r.context['lg_rows'], [])   # bei LG-Filter kein Vergleich

    def test_pdf_export(self):
        from finance.booking import buche
        lg, e, m, v = _basis_objekte()
        buche('1020', '3000', Decimal('1500'), 'Miete', datum=date(2025, 1, 15), liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/auswertung/?typ=mietertrag&jahr=2025&pdf=1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertGreater(len(r.content), 1200)


class MieterspiegelTests(TestCase):
    """Mieterspiegel (Rent Roll): Soll/Ist/Leerstand je Liegenschaft + PDF."""

    def _setup(self):
        from portfolio.models import Einheit
        lg, e, m, v = _basis_objekte()   # e ist belegt (aktiver Vertrag v), Netto 1500 + NK 200
        # zweite, leere Einheit
        Einheit.objects.create(liegenschaft=lg, bezeichnung='2.5 Zi', typ='whg',
                               nettomiete_aktuell=Decimal('1200'), nebenkosten_aktuell=Decimal('150'))
        return lg

    def test_berechnung_soll_ist_leerstand(self):
        from core.services.mieterspiegel import berechne_mieterspiegel
        from portfolio.models import Liegenschaft
        lg = self._setup()
        spiegel = berechne_mieterspiegel(list(Liegenschaft.objects.all()))
        t = spiegel[0]['totals']
        self.assertEqual(t['anzahl'], 2)
        self.assertEqual(t['belegt'], 1)
        self.assertEqual(t['leer'], 1)
        self.assertEqual(t['soll_brutto'], Decimal('3050.00'))   # 1700 + 1350
        self.assertEqual(t['ist_brutto'], Decimal('1700.00'))    # nur belegte Einheit
        self.assertEqual(t['leer_fr'], Decimal('1350.00'))
        self.assertEqual(t['leerstandsquote'], 50.0)

    def test_auswahl_uebersicht_ohne_lg(self):
        """Ohne Liegenschaftswahl: Auswahl-Übersicht (kein kombiniertes Gesamttotal)."""
        lg = self._setup()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterspiegel/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Mieterspiegel')
        self.assertTemplateUsed(r, 'fw/mieterspiegel_auswahl.html')
        self.assertIn('uebersicht', r.context)
        self.assertNotIn('gesamt', r.context)

    def test_view_pro_liegenschaft(self):
        lg = self._setup()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mieterspiegel/?lg={lg.id}')
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'fw/mieterspiegel.html')
        # Kennzahlen der EINEN Liegenschaft (kein Gesamttotal über alle)
        self.assertEqual(r.context['gesamt']['ist_brutto'], Decimal('1700.00'))
        self.assertEqual(len(r.context['spiegel']), 1)

    def test_pdf_pro_liegenschaft(self):
        from crm.models import Organisation
        _test_organisation(firma='VW AG', strasse='W 1', plz='8000', ort='ZH')
        lg = self._setup()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mieterspiegel/?lg={lg.id}&pdf=1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))


class RenditeGebaeudeTests(TestCase):
    """Rendite-Kennzahlen (Verkehrswert-Nenner), gebäudescharfe Betriebsrechnung
    und Leerstands-Zeitverlauf."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def _konto(self, nummer, bez, typ):
        from finance.models import Buchungskonto
        return Buchungskonto.objects.get_or_create(nummer=nummer, defaults={'bezeichnung': bez, 'typ': typ})[0]

    def test_bruttorendite_aus_verkehrswert(self):
        from core.services.rendite import liegenschaft_rendite
        lg, e, m, v = _basis_objekte()   # netto 1500 → jahr 18000
        lg.verkehrswert = Decimal('500000'); lg.save()
        r = liegenschaft_rendite(lg)
        self.assertEqual(r['wert_quelle'], 'verkehrswert')
        self.assertEqual(r['jahres_netto'], Decimal('18000.00'))
        # 18000 / 500000 = 3.6%
        self.assertAlmostEqual(r['bruttorendite'], 3.6, places=2)

    def test_anlagekosten_fallback(self):
        from core.services.rendite import liegenschaft_rendite
        lg, e, m, v = _basis_objekte()
        lg.anlagekosten = Decimal('600000'); lg.save()  # kein Verkehrswert
        r = liegenschaft_rendite(lg)
        self.assertEqual(r['wert_quelle'], 'anlagekosten')
        self.assertAlmostEqual(r['bruttorendite'], 3.0, places=2)

    def test_keine_rendite_ohne_wert(self):
        from core.services.rendite import liegenschaft_rendite
        lg, e, m, v = _basis_objekte()   # nur Versicherungswert
        r = liegenschaft_rendite(lg)
        self.assertIsNone(r['bruttorendite'])
        self.assertIsNone(r['wert_quelle'])

    def test_nettorendite_zieht_aufwand_ab(self):
        from core.services.rendite import liegenschaft_rendite
        from finance.booking import buche
        lg, e, m, v = _basis_objekte()
        lg.verkehrswert = Decimal('500000'); lg.save()
        self._konto('6000', 'Unterhalt', 'aufwand')
        self._konto('1020', 'Bank', 'bilanz')
        buche('6000', '1020', Decimal('1800'), 'Unterhalt', datum=date.today(), liegenschaft=lg)
        r = liegenschaft_rendite(lg)
        # (18000 - 1800) / 500000 = 3.24%
        self.assertAlmostEqual(r['nettorendite'], 3.24, places=2)

    def test_betriebsrechnung_ertrag_minus_aufwand(self):
        from core.services.rendite import betriebsrechnung
        from finance.booking import buche
        lg, e, m, v = _basis_objekte()
        self._konto('3000', 'Mietertrag', 'ertrag')
        self._konto('6000', 'Unterhalt', 'aufwand')
        self._konto('1020', 'Bank', 'bilanz')
        jahr = date.today().year
        buche('1020', '3000', Decimal('12000'), 'Miete', datum=date(jahr, 3, 1), liegenschaft=lg)
        buche('6000', '1020', Decimal('2000'), 'Reparatur', datum=date(jahr, 4, 1), liegenschaft=lg)
        d = betriebsrechnung(lg, jahr)
        self.assertEqual(d['ertrag_total'], Decimal('12000.00'))
        self.assertEqual(d['aufwand_total'], Decimal('2000.00'))
        self.assertEqual(d['ergebnis'], Decimal('10000.00'))

    def test_betriebsrechnung_pdf(self):
        from core.services.gebaeude_report import betriebsrechnung_pdf
        lg, e, m, v = _basis_objekte()
        pdf = betriebsrechnung_pdf(lg, date.today().year)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_betriebsrechnung_pdf_view(self):
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.get(f'/neu/liegenschaften/{lg.id}/betriebsrechnung/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_leerstand_verlauf(self):
        from core.services.rendite import leerstand_zeitverlauf
        from rentals.models import Leerstand
        lg, e, m, v = _basis_objekte()
        Leerstand.objects.create(einheit=e, beginn=date.today() - timedelta(days=40))
        reihe = leerstand_zeitverlauf(lg=lg, monate=6)
        self.assertEqual(len(reihe), 6)
        self.assertEqual(reihe[-1]['quote'], 100.0)   # 1/1 leer aktuell

    def test_leerstand_verlauf_view(self):
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.get('/neu/berichte/leerstand-verlauf/?monate=12')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Leerstands-Verlauf', r.content.decode())

    def test_form_get_rendert_bewertung_und_energie(self):
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.get(f'/neu/liegenschaften/{lg.id}/bearbeiten/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Verkehrswert', html)
        self.assertIn('GEAK', html)

    def test_form_speichert_verkehrswert_und_energie(self):
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post(f'/neu/liegenschaften/{lg.id}/bearbeiten/', {
            'strasse': lg.strasse, 'plz': lg.plz, 'ort': lg.ort,
            'verkehrswert': "750'000", 'heizsystem': 'waermepumpe',
            'geak_klasse': 'B', 'warmwasser': 'zentral',
        })
        self.assertIn(r.status_code, (200, 302))
        lg.refresh_from_db()
        self.assertEqual(lg.verkehrswert, Decimal('750000'))
        self.assertEqual(lg.heizsystem, 'waermepumpe')
        self.assertEqual(lg.geak_klasse, 'B')
