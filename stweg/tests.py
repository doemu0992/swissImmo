"""Tests des STWEG-Moduls."""
from decimal import Decimal

from django.test import TestCase

from core.tests._helfer import _test_organisation
from portfolio.models import Einheit, Liegenschaft
from stweg.validierung import WertquotenFehler, pruefe_wertquoten


def neue_stweg(name='Sonnenblick', quoten=(200, 300, 500), total=1000, status='entwurf'):
    """STWEG als Entwurf mit Einheiten; Status wird erst danach gesetzt."""
    lg = Liegenschaft.objects.create(
        strasse=f'{name}weg 1', plz='8000', ort='Zürich', typ='STWEG',
        status='entwurf', wertquote_total=total, organisation=_test_organisation())
    einheiten = [
        Einheit.objects.create(liegenschaft=lg, bezeichnung=f'Whg {i + 1}', typ='stwe',
                               wertquote=Decimal(q))
        for i, q in enumerate(quoten)]
    if status != 'entwurf':
        lg.status = status
        lg.save()
    return lg, einheiten


class WertquotenValidierungTests(TestCase):
    def test_999_von_1000_blockiert_aktivierung(self):
        lg, _ = neue_stweg(quoten=(200, 300, 499))
        lg.status = 'aktiv'
        with self.assertRaises(WertquotenFehler) as ctx:
            lg.save()
        self.assertIn('999/1000', str(ctx.exception))
        lg.refresh_from_db()
        self.assertEqual(lg.status, 'entwurf')      # nichts gespeichert

    def test_1001_von_1000_blockiert_ebenfalls(self):
        lg, _ = neue_stweg(quoten=(200, 300, 501))
        lg.status = 'aktiv'
        with self.assertRaises(WertquotenFehler):
            lg.save()

    def test_exakt_1000_wird_aktiv(self):
        lg, _ = neue_stweg(quoten=(200, 300, 500))
        lg.status = 'aktiv'
        lg.save()
        lg.refresh_from_db()
        self.assertEqual(lg.status, 'aktiv')

    def test_anderer_nenner_100(self):
        lg, _ = neue_stweg(quoten=(20, 30, 50), total=100)
        lg.status = 'aktiv'
        lg.save()

    def test_neue_stweg_nicht_direkt_aktiv(self):
        with self.assertRaises(WertquotenFehler):
            Liegenschaft.objects.create(
                strasse='X 1', plz='8000', ort='Zürich', typ='STWEG', status='aktiv',
                organisation=_test_organisation())

    def test_mietliegenschaft_wird_nicht_geprueft(self):
        lg = Liegenschaft.objects.create(
            strasse='Miete 1', plz='8000', ort='Zürich', organisation=_test_organisation())
        Einheit.objects.create(liegenschaft=lg, bezeichnung='A', typ='whg')   # Quote Default 10
        lg.save()
        pruefe_wertquoten(lg)                       # wirft nicht
        self.assertEqual((lg.typ, lg.status), ('MIETE', 'aktiv'))

    def test_entwurf_darf_unvollstaendig_sein(self):
        lg, _ = neue_stweg(quoten=(200, 300))
        lg.save()                                   # Entwurf: keine Prüfung


class VerteilungTests(TestCase):
    def test_summe_ist_exakt(self):
        from stweg.verteilung import verteile_nach_quoten
        r = verteile_nach_quoten(Decimal('100.00'), {1: 1, 2: 1, 3: 1})
        self.assertEqual(sum(r.values()), Decimal('100.00'))
        self.assertEqual(sorted(r.values()), [Decimal('33.33'), Decimal('33.33'), Decimal('33.34')])

    def test_proportional(self):
        from stweg.verteilung import verteile_nach_quoten
        r = verteile_nach_quoten(Decimal('4000'), {1: 200, 2: 300, 3: 500})
        self.assertEqual(r, {1: Decimal('800.00'), 2: Decimal('1200.00'), 3: Decimal('2000.00')})


class ErneuerungsfondsTests(TestCase):
    def setUp(self):
        self.lg, self.einheiten = neue_stweg(quoten=(200, 300, 500), status='aktiv')

    def test_einlage_nach_wertquoten_und_als_passivum(self):
        from finance.models import Buchung, Buchungskonto
        from stweg.fonds import jahreseinlage_belasten
        r = jahreseinlage_belasten(self.lg, 2026, Decimal('10000'))
        self.assertEqual([r[e] for e in self.einheiten],
                         [Decimal('2000.00'), Decimal('3000.00'), Decimal('5000.00')])
        fonds = self.lg.erneuerungsfonds
        self.assertEqual(fonds.bestand, Decimal('10000.00'))
        # Passivum, kein Ertrag, kein Aufwand
        k2800 = Buchungskonto.objects.get(nummer='2800')
        self.assertEqual(k2800.typ, 'passiv')
        b = Buchung.objects.filter(liegenschaft=self.lg)
        self.assertEqual(b.count(), 3)
        self.assertTrue(all(x.haben_konto.nummer == '2800' and x.soll_konto.nummer == '1110' for x in b))
        self.assertFalse(b.filter(soll_konto__typ__in=['aufwand', 'ertrag']).exists())
        self.assertFalse(b.filter(haben_konto__typ__in=['aufwand', 'ertrag']).exists())

    def test_einlage_nur_einmal_pro_jahr(self):
        from stweg.fonds import FondsFehler, jahreseinlage_belasten
        jahreseinlage_belasten(self.lg, 2026, Decimal('1000'))
        with self.assertRaises(FondsFehler):
            jahreseinlage_belasten(self.lg, 2026, Decimal('1000'))

    def test_einlage_bei_falschen_quoten_blockiert(self):
        from stweg.fonds import jahreseinlage_belasten
        e = self.einheiten[0]
        e.wertquote = Decimal(199)
        e.save()
        with self.assertRaises(WertquotenFehler):
            jahreseinlage_belasten(self.lg, 2026, Decimal('1000'))

    def test_entnahme_und_saldo(self):
        from stweg.fonds import FondsFehler, entnahme_buchen, jahreseinlage_belasten
        jahreseinlage_belasten(self.lg, 2026, Decimal('1000'))
        entnahme_buchen(self.lg, 2026, Decimal('400'), 'Dach')
        self.lg.erneuerungsfonds.refresh_from_db()
        self.assertEqual(self.lg.erneuerungsfonds.bestand, Decimal('600.00'))
        with self.assertRaises(FondsFehler):
            entnahme_buchen(self.lg, 2026, Decimal('601'), 'zu viel')

    def test_miet_job_ueberspringt_stweg(self):
        from core.services.automation import run_erneuerungsfonds_einlage
        from stweg.fonds import fonds_von
        f = fonds_von(self.lg)
        f.jaehrliche_einlage = Decimal('500')
        f.save()
        self.assertEqual(run_erneuerungsfonds_einlage(2026)[0], 0)


def rechnung(lg, betrag, datum, status='freigegeben', **kw):
    from finance.models import KreditorenRechnung
    return KreditorenRechnung.objects.create(
        liegenschaft=lg, lieferant=kw.pop('lieferant', 'Lieferant AG'),
        betrag=Decimal(betrag), datum=datum, status=status, **kw)


class StwegAbrechnungServiceTests(TestCase):
    def setUp(self):
        from datetime import date
        self.lg, self.e = neue_stweg(quoten=(200, 300, 500), status='aktiv')
        self.d = date(2026, 6, 15)

    def service(self):
        from stweg.services import StwegAbrechnungService
        return StwegAbrechnungService(self.lg)

    def test_nur_allgemeine_kosten_des_jahres_ohne_neu_und_storniert(self):
        from datetime import date
        rechnung(self.lg, 1000, self.d)
        rechnung(self.lg, 500, date(2026, 1, 2), status='bezahlt')
        rechnung(self.lg, 999, self.d, status='neu')
        rechnung(self.lg, 999, self.d, status='storniert')
        rechnung(self.lg, 999, date(2025, 12, 31))                   # Vorjahr
        rechnung(self.lg, 999, self.d, einheit=self.e[0])            # nur eine Einheit
        self.assertEqual(self.service().allgemeine_kosten(2026), Decimal('1500.00'))

    def test_aufgeteilte_rechnung_zaehlt_nur_positionen_dieser_liegenschaft(self):
        from finance.models import Buchungskonto, KreditorPosition
        lg2, _ = neue_stweg(name='Andere')
        r = rechnung(self.lg, 1000, self.d)
        konto = Buchungskonto.objects.create(nummer='4000', bezeichnung='Unterhalt', typ='aufwand')
        KreditorPosition.objects.create(rechnung=r, konto=konto, liegenschaft=self.lg, betrag=Decimal('300'))
        KreditorPosition.objects.create(rechnung=r, konto=konto, liegenschaft=lg2, betrag=Decimal('700'))
        self.assertEqual(self.service().allgemeine_kosten(2026), Decimal('300.00'))

    def test_keine_abrechnung_bei_falschen_quoten(self):
        from stweg.services import StwegAbrechnungService
        rechnung(self.lg, 1000, self.d)
        Einheit.objects.filter(pk=self.e[0].pk).update(wertquote=Decimal(199))   # umgeht save()
        with self.assertRaises(WertquotenFehler):
            StwegAbrechnungService(self.lg).abrechnen(2026)

    def test_keine_abrechnung_im_entwurf_oder_fuer_miete(self):
        from stweg.services import AbrechnungsFehler, StwegAbrechnungService
        lg, _ = neue_stweg(name='Entwurf')
        with self.assertRaises(AbrechnungsFehler):
            StwegAbrechnungService(lg).abrechnen(2026)
        miete = Liegenschaft.objects.create(strasse='M 1', plz='8000', ort='Z',
                                            organisation=_test_organisation())
        with self.assertRaises(AbrechnungsFehler):
            StwegAbrechnungService(miete)

    def test_rappen_gehen_auf(self):
        lg, e = neue_stweg(name='Drittel', quoten=(333, 333, 334), status='aktiv')
        rechnung(lg, '100.00', self.d)
        from stweg.services import StwegAbrechnungService
        a = StwegAbrechnungService(lg).abrechnen(2026)
        self.assertEqual(sum(p.kostenanteil for p in a.positionen.all()), Decimal('100.00'))

    def test_neuberechnung_ersetzt_entwurf_nicht_abgeschlossene(self):
        from stweg.models import StwegAbrechnung
        from stweg.services import AbrechnungsFehler
        rechnung(self.lg, 1000, self.d)
        s = self.service()
        s.abrechnen(2026)
        rechnung(self.lg, 1000, self.d)
        a = s.abrechnen(2026)
        self.assertEqual(a.gesamtkosten, Decimal('2000.00'))
        self.assertEqual(StwegAbrechnung.objects.filter(liegenschaft=self.lg).count(), 1)
        s.abschliessen(a)
        with self.assertRaises(AbrechnungsFehler):
            s.abrechnen(2026)

    def test_fremde_organisation_fliesst_nicht_ein(self):
        """Kosten und Akonto einer anderen Verwaltung dürfen nie mitgezählt werden."""
        from core.tenancy import organisation_kontext
        from crm.models import Organisation
        from stweg.models import StwegAkonto
        rechnung(self.lg, 1000, self.d)
        fremd = Organisation.objects.create(firma='Fremd AG', strasse='X 1', plz='9000', ort='St. Gallen')
        with organisation_kontext(fremd):
            flg = Liegenschaft.objects.create(strasse='F 1', plz='9000', ort='SG', typ='STWEG',
                                              status='entwurf', organisation=fremd)
            rechnung(flg, 7777, self.d)
            fe = Einheit.objects.create(liegenschaft=flg, bezeichnung='F', typ='stwe', wertquote=1000)
            StwegAkonto.objects.create(einheit=fe, betrag=Decimal('5555'), datum=self.d)
        a = self.service().abrechnen(2026)
        self.assertEqual(a.gesamtkosten, Decimal('1000.00'))
        self.assertEqual(sum(p.akonto for p in a.positionen.all()), Decimal('0.00'))


class SonnenblickSimulationTests(TestCase):
    """End-to-End: Gemeinschaft «Sonnenblick», 3 Eigentümer, Jahresabrechnung 2026."""

    def test_sonnenblick(self):
        from datetime import date

        from crm.models import Eigentuemer
        from stweg.models import StwegAkonto
        from stweg.services import StwegAbrechnungService

        # 1. Gemeinschaft mit 3 Eigentümern, Wertquoten 200 / 300 / 500
        lg = Liegenschaft.objects.create(
            strasse='Sonnenblick 1', plz='6003', ort='Luzern', typ='STWEG',
            status='entwurf', wertquote_total=1000, organisation=_test_organisation())
        einheiten = []
        for name, quote in (('Anna', 200), ('Bruno', 300), ('Carla', 500)):
            eig = Eigentuemer.objects.create(firma_oder_name=name)
            einheiten.append(Einheit.objects.create(
                liegenschaft=lg, bezeichnung=f'Whg {name}', typ='stwe',
                wertquote=Decimal(quote), stockwerkeigentuemer=eig))
        lg.status = 'aktiv'
        lg.save()                                   # 1000/1000 → erlaubt

        # 2. Alle zahlen 1'000 CHF Akonto (als Quartalsraten à 250)
        for e in einheiten:
            for monat in (3, 6, 9, 12):
                StwegAkonto.objects.create(einheit=e, betrag=Decimal('250'), datum=date(2026, monat, 1))

        # 3. Allgemeine Kosten 4'000 CHF
        rechnung(lg, 1500, date(2026, 2, 1), lieferant='Gebäudeversicherung')
        rechnung(lg, 1000, date(2026, 5, 1), lieferant='Gartenpflege')
        rechnung(lg, 1500, date(2026, 8, 1), lieferant='Liftwartung')

        # 4. Abrechnung
        abrechnung = StwegAbrechnungService(lg).abrechnen(2026)

        # 5. Mathematik
        self.assertEqual(abrechnung.gesamtkosten, Decimal('4000.00'))
        p1, p2, p3 = abrechnung.positionen.order_by('einheit_id')
        self.assertEqual((p1.kostenanteil, p1.akonto, p1.saldo),
                         (Decimal('800.00'), Decimal('1000.00'), Decimal('-200.00')))
        self.assertEqual(p1.guthaben, Decimal('200.00'))
        self.assertEqual((p2.kostenanteil, p2.saldo), (Decimal('1200.00'), Decimal('200.00')))
        self.assertEqual((p3.kostenanteil, p3.akonto, p3.saldo),
                         (Decimal('2000.00'), Decimal('1000.00'), Decimal('1000.00')))
        self.assertEqual(p3.zahllast, Decimal('1000.00'))
        # Nichts geht verloren: Kosten verteilt = Kosten angefallen
        self.assertEqual(sum(p.kostenanteil for p in abrechnung.positionen.all()), Decimal('4000.00'))
        self.assertEqual(p3.eigentuemer.firma_oder_name, 'Carla')


class FormularTests(TestCase):
    def test_einheitsformular_speichert_stockwerkeigentuemer_und_behaelt_ihn(self):
        from crm.models import Eigentuemer
        from portfolio.forms import EinheitForm
        lg, einheiten = neue_stweg()
        eig = Eigentuemer.objects.create(firma_oder_name='Anna')
        e = einheiten[0]
        daten = {'bezeichnung': e.bezeichnung, 'typ': 'stwe', 'wertquote': '200',
                 'stockwerkeigentuemer': str(eig.pk)}
        form = EinheitForm(daten, instance=e)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        e.refresh_from_db()
        self.assertEqual(e.stockwerkeigentuemer, eig)
        # Feld fehlt im POST ganz → bleibt stehen
        form = EinheitForm({'bezeichnung': e.bezeichnung, 'typ': 'stwe', 'wertquote': '200'}, instance=e)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        e.refresh_from_db()
        self.assertEqual(e.stockwerkeigentuemer, eig)

    def test_fremder_eigentuemer_nicht_waehlbar(self):
        from core.tenancy import organisation_kontext
        from crm.models import Eigentuemer, Organisation
        from portfolio.forms import EinheitForm
        lg, einheiten = neue_stweg()
        fremd = Organisation.objects.create(firma='Fremd AG', strasse='X 1', plz='9000', ort='SG')
        with organisation_kontext(fremd):
            f_eig = Eigentuemer.objects.create(firma_oder_name='Fremder')
        form = EinheitForm({'bezeichnung': 'X', 'typ': 'stwe', 'wertquote': '1',
                            'stockwerkeigentuemer': str(f_eig.pk)}, instance=einheiten[0])
        self.assertFalse(form.is_valid())
        self.assertIn('stockwerkeigentuemer', form.errors)

    def test_wertquote_total_im_liegenschaftsformular(self):
        from portfolio.forms import LiegenschaftForm
        lg, _ = neue_stweg()
        basis = {'strasse': lg.strasse, 'plz': '8000', 'ort': 'Zürich'}
        f = LiegenschaftForm({**basis, 'wertquote_total': '100'}, instance=lg)
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.save().wertquote_total, 100)
        f = LiegenschaftForm(basis, instance=lg)            # leer → unverändert
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.save().wertquote_total, 100)


class ArtUndStatusImFormularTests(TestCase):
    """Die Art «STWEG» und der Status lassen sich im Liegenschaftsformular setzen."""

    BASIS = {'strasse': 'Formularweg 1', 'plz': '8000', 'ort': 'Zürich'}

    def form(self, daten, instanz=None):
        from portfolio.forms import LiegenschaftForm
        return LiegenschaftForm({**self.BASIS, **daten}, instance=instanz or Liegenschaft(organisation=_test_organisation()))

    def test_neue_stweg_wird_als_entwurf_gespeichert_auch_wenn_aktiv_gewaehlt(self):
        f = self.form({'typ': 'STWEG', 'status': 'aktiv', 'wertquote_total': '1000'})
        self.assertTrue(f.is_valid(), f.errors)
        lg = f.save()
        self.assertEqual((lg.typ, lg.status), ('STWEG', 'entwurf'))

    def test_ohne_felder_bleibt_alles_wie_gehabt(self):
        lg, _ = neue_stweg()
        f = self.form({}, instanz=lg)
        self.assertTrue(f.is_valid(), f.errors)
        lg = f.save()
        self.assertEqual((lg.typ, lg.status), ('STWEG', 'entwurf'))
        neu = self.form({}).save()
        self.assertEqual((neu.typ, neu.status), ('MIETE', 'aktiv'))

    def test_aktivieren_mit_falschen_quoten_ist_ein_formularfehler(self):
        lg, _ = neue_stweg(quoten=(200, 300, 499))
        f = self.form({'typ': 'STWEG', 'status': 'aktiv'}, instanz=lg)
        self.assertFalse(f.is_valid())
        self.assertIn('999/1000', ' '.join(f.errors['status']))

    def test_aktivieren_mit_passenden_quoten_geht(self):
        lg, _ = neue_stweg()
        f = self.form({'typ': 'STWEG', 'status': 'aktiv'}, instanz=lg)
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.save().status, 'aktiv')

    def test_stweg_mit_versammlung_wird_nicht_zur_miete(self):
        from datetime import timedelta

        from django.utils import timezone

        from stweg.models import Versammlung
        lg, _ = neue_stweg()
        Versammlung.objects.create(liegenschaft=lg, titel='V', datum=timezone.now() + timedelta(days=30))
        f = self.form({'typ': 'MIETE'}, instanz=lg)
        self.assertFalse(f.is_valid())
        self.assertIn('typ', f.errors)

    def test_ueber_die_oberflaeche(self):
        from core.tests._helfer import _team_user
        self.client.force_login(_team_user('Verwaltung'))
        r = self.client.post('/neu/liegenschaften/neu/', {**self.BASIS, 'typ': 'STWEG', 'status': 'aktiv'})
        self.assertIn(r.status_code, (302, 200))
        lg = Liegenschaft.objects.get(strasse='Formularweg 1')
        self.assertEqual((lg.typ, lg.status), ('STWEG', 'entwurf'))
        self.assertContains(self.client.get('/neu/stweg/'), 'Formularweg 1')


class NebenraeumeTests(TestCase):
    """Parkplätze und Keller (`gehoert_zu`) haben weder Quote noch Stimme."""

    def test_nebenraeume_zaehlen_nicht_in_der_quotensumme(self):
        from stweg.validierung import stimm_einheiten, wertquoten_summe
        lg, e = neue_stweg(quoten=(200, 300, 500), status='aktiv')
        pp = Einheit.objects.create(liegenschaft=lg, bezeichnung='Parkplatz 1', typ='pp', gehoert_zu=e[0])
        self.assertEqual(pp.wertquote, Decimal('10.00'))              # die Vorgabe aus dem Mietmodul
        self.assertEqual(wertquoten_summe(lg), Decimal('1000'))
        self.assertEqual(set(stimm_einheiten(lg)), set(e))
        pruefe_wertquoten(lg)                                         # wirft nicht

    def test_selbstaendige_einheit_ohne_gehoert_zu_zaehlt(self):
        lg, e = neue_stweg(quoten=(200, 300, 400), status='entwurf')
        Einheit.objects.create(liegenschaft=lg, bezeichnung='Garage', typ='gar', wertquote=Decimal(100))
        lg.status = 'aktiv'
        lg.save()                                                     # 200+300+400+100

    def test_nebenraum_ohne_eigentuemer_blockiert_keine_einladung_und_keine_abstimmung(self):
        from stweg.test_versammlung import sonnenblick, versammlung
        from stweg.versammlung import einladung_pruefen
        lg, e, _ = sonnenblick()
        Einheit.objects.create(liegenschaft=lg, bezeichnung='Keller', typ='bas', gehoert_zu=e[0])
        self.assertEqual(einladung_pruefen(versammlung(lg)), [])
        from stweg import beschluss
        from stweg.validierung import stimm_einheiten
        z = beschluss.zaehlen(list(stimm_einheiten(lg)), {}, 'einstimmig', 1000)
        self.assertEqual(z['total_koepfe'], 3)

    def test_fondseinlage_und_abrechnung_verteilen_nur_auf_hauptobjekte(self):
        from stweg.fonds import jahreseinlage_belasten
        lg, e = neue_stweg(quoten=(200, 300, 500), status='aktiv')
        Einheit.objects.create(liegenschaft=lg, bezeichnung='Keller', typ='bas', gehoert_zu=e[1])
        verteilt = jahreseinlage_belasten(lg, 2026, Decimal('1000'))
        self.assertEqual(len(verteilt), 3)
        self.assertEqual(sum(verteilt.values()), Decimal('1000.00'))
