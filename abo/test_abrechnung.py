"""Rechnungsstellung: Betrag, MWST (konfigurierbar), QR-Rechnung, Idempotenz, Fehlerisolation."""
import io
from datetime import date
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings

from abo import dienst
from abo.models import AboRechnung, Abonnement
from core import funktionen as f
from core.tests._isolation import MandantenFixture

STELLER = {'name': 'Plattform AG', 'strasse': 'Bahnhofstrasse 1', 'plz': '8001', 'ort': 'Zürich',
           'iban': 'CH4431999123000889012',            # SIX-Beispiel einer QR-IBAN
           'uid': '', 'email': 'abo@example.ch'}
FESTGELEGT = dict(ABO_PREISE_FESTGELEGT=True, ABO_MWST_SATZ=None, ABO_RECHNUNGSSTELLER=STELLER)


def _verwaltet(bestand, stufe='team', jaehrlich=False, ab=date(2026, 12, 1)):
    org = bestand.organisation
    org.abo_plan, org.abo_jaehrlich = stufe, jaehrlich
    org.save(update_fields=['abo_plan', 'abo_jaehrlich'])
    return Abonnement.alle_organisationen.update_or_create(
        organisation=org, defaults={'uneingeschraenkt': False, 'zusatzmodule': [], 'abrechnung_ab': ab,
                                    'abgerechnet_bis': None})[0]


class Basis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        # Das Isolationsfixture legt je Verwaltung eine Abo-Rechnung an; diese Tests bauen ihre eigenen.
        from abo.models import AboRechnung
        AboRechnung.alle_organisationen.all().delete()

    def org(self, bestand=None):
        return type(self.a.organisation).objects.get(pk=(bestand or self.a).organisation.pk)


@override_settings(**FESTGELEGT)
class BetragTests(Basis):

    def test_monatsrechnung_team_ohne_mwst(self):
        _verwaltet(self.a)
        r = dienst.abrechnen(self.org(), heute=date(2026, 12, 1))
        rechnung = AboRechnung.alle_organisationen.get(organisation=self.a.organisation)
        self.assertEqual(r['rechnung'], rechnung.nummer)
        einheiten = rechnung.einheiten
        self.assertEqual(rechnung.netto, f.monatspreis('team', einheiten))
        self.assertIsNone(rechnung.mwst_satz)
        self.assertEqual(rechnung.mwst_betrag, Decimal('0.00'))
        self.assertEqual(rechnung.brutto, rechnung.netto)
        self.assertEqual((rechnung.periode_von, rechnung.periode_bis), (date(2026, 12, 1), date(2026, 12, 31)))
        self.assertEqual(rechnung.faellig_am, date(2026, 12, 11))       # Periode läuft schon: Zahlungsfrist ab Rechnung
        self.assertFalse(rechnung.platzhalter)

    @override_settings(ABO_MWST_SATZ=Decimal('8.1'))
    def test_mwst_satz_ist_konfigurierbar_und_wird_ausgewiesen(self):
        _verwaltet(self.a)
        dienst.abrechnen(self.org(), heute=date(2026, 12, 1))
        rechnung = AboRechnung.alle_organisationen.get(organisation=self.a.organisation)
        self.assertEqual(rechnung.mwst_satz, Decimal('8.10'))
        self.assertEqual(rechnung.mwst_betrag, (rechnung.netto * Decimal('0.081')).quantize(Decimal('0.01')))
        self.assertEqual(rechnung.brutto, rechnung.netto + rechnung.mwst_betrag)

    def test_jahresrechnung_mit_rabatt_und_zwoelf_monaten(self):
        _verwaltet(self.a, jaehrlich=True)
        dienst.abrechnen(self.org(), heute=date(2026, 12, 1))
        rechnung = AboRechnung.alle_organisationen.get(organisation=self.a.organisation)
        erwartet = (f.monatspreis('team', rechnung.einheiten) * 12 * (1 - f.JAHRESRABATT)).quantize(Decimal('0.01'))
        self.assertEqual(rechnung.netto, erwartet)
        self.assertEqual(rechnung.periode_bis, date(2027, 11, 30))

    def test_bestand_ueber_dem_deckel_wird_zum_deckelpreis_abgerechnet_und_vermerkt(self):
        with mock.patch.dict(f.PREISE['start'], {'deckel': 25}), mock.patch('abo.dienst.zaehle', return_value=40):
            _verwaltet(self.a, stufe='start')
            dienst.abrechnen(self.org(), heute=date(2026, 12, 1))
        rechnung = AboRechnung.alle_organisationen.get(organisation=self.a.organisation)
        self.assertEqual(rechnung.netto, f.PREISE['start']['monat'])
        self.assertIn('übersteigt', rechnung.bemerkung)

    def test_idempotent_und_naechste_periode_folgt(self):
        _verwaltet(self.a)
        dienst.abrechnen(self.org(), heute=date(2026, 12, 1))
        dienst.abrechnen(self.org(), heute=date(2026, 12, 1))
        self.assertEqual(AboRechnung.alle_organisationen.filter(organisation=self.a.organisation).count(), 1)
        dienst.abrechnen(self.org(), heute=date(2026, 12, 15))
        self.assertEqual(AboRechnung.alle_organisationen.filter(organisation=self.a.organisation).count(), 1)
        dienst.abrechnen(self.org(), heute=date(2027, 1, 1))
        self.assertEqual(AboRechnung.alle_organisationen.filter(organisation=self.a.organisation).count(), 2)

    def test_ohne_abrechnungsbeginn_wird_nichts_gestellt(self):
        _verwaltet(self.a, ab=None)
        dienst.abrechnen(self.org(), heute=date(2030, 1, 1))
        self.assertFalse(AboRechnung.alle_organisationen.filter(organisation=self.a.organisation).exists())

    def test_vor_dem_vorlauf_wird_nichts_gestellt(self):
        _verwaltet(self.a, ab=date(2027, 1, 1))
        dienst.abrechnen(self.org(), heute=date(2026, 12, 15))
        self.assertFalse(AboRechnung.alle_organisationen.filter(organisation=self.a.organisation).exists())

    def test_im_voraus_rechnung_im_vorlauf_faellig_am_periodenbeginn(self):
        _verwaltet(self.a, ab=date(2027, 1, 1))
        dienst.abrechnen(self.org(), heute=date(2026, 12, 22))          # 10 Tage vor Beginn
        r = AboRechnung.alle_organisationen.get(organisation=self.a.organisation)
        self.assertEqual((r.periode_von, r.rechnungsdatum, r.faellig_am),
                         (date(2027, 1, 1), date(2026, 12, 22), date(2027, 1, 1)))

    def test_wird_nicht_vor_dem_vorlauf_und_nicht_doppelt_gestellt(self):
        _verwaltet(self.a, ab=date(2027, 1, 1))
        dienst.abrechnen(self.org(), heute=date(2026, 12, 21))          # 11 Tage vorher: zu früh
        self.assertFalse(AboRechnung.alle_organisationen.filter(organisation=self.a.organisation).exists())
        dienst.abrechnen(self.org(), heute=date(2026, 12, 22))
        dienst.abrechnen(self.org(), heute=date(2027, 1, 1))
        self.assertEqual(AboRechnung.alle_organisationen.filter(organisation=self.a.organisation).count(), 1)

    def test_qr_referenz_hat_gueltige_pruefziffer(self):
        from core.services.iban import qrr_pruefziffer_ok
        _verwaltet(self.a)
        dienst.abrechnen(self.org(), heute=date(2026, 12, 1))
        rechnung = AboRechnung.alle_organisationen.get(organisation=self.a.organisation)
        self.assertTrue(qrr_pruefziffer_ok(rechnung.qr_referenz))


class PlatzhalterTests(Basis):

    @override_settings(ABO_PREISE_FESTGELEGT=False)
    def test_ohne_festgelegte_preise_keine_rechnung(self):
        _verwaltet(self.a)
        bericht = dienst.abrechnen(self.org(), heute=date(2026, 12, 1))
        self.assertTrue(bericht['preise_offen'])
        self.assertFalse(AboRechnung.alle_organisationen.filter(organisation=self.a.organisation).exists())

    @override_settings(ABO_PREISE_FESTGELEGT=False)
    def test_probelauf_markiert_die_rechnung_als_platzhalter(self):
        _verwaltet(self.a)
        dienst.abrechnen(self.org(), heute=date(2026, 12, 1), trotz_platzhalter=True)
        self.assertTrue(AboRechnung.alle_organisationen.get(organisation=self.a.organisation).platzhalter)

    @override_settings(ABO_PREISE_FESTGELEGT=False)
    def test_abo_seite_weist_platzhalter_aus(self):
        c = Client()
        c.force_login(self.a.benutzer)
        self.assertContains(c.get('/neu/abonnement/'), 'vom Betreiber festzulegen')

    @override_settings(ABO_PREISE_FESTGELEGT=True, ABO_MWST_SATZ=Decimal('8.1'))
    def test_abo_seite_ohne_platzhalterhinweis_wenn_festgelegt(self):
        c = Client()
        c.force_login(self.a.benutzer)
        self.assertNotContains(c.get('/neu/abonnement/'), 'vom Betreiber festzulegen')


@override_settings(**FESTGELEGT)
class BefehlTests(Basis):

    def test_lauf_isoliert_fehler_je_verwaltung(self):
        _verwaltet(self.a)
        _verwaltet(self.b)
        echt = dienst.rechnung_stellen

        def kaputt_fuer_a(organisation, abo, *args, **kwargs):
            if organisation.pk == self.a.organisation.pk:
                raise RuntimeError('Konto fehlt')
            return echt(organisation, abo, *args, **kwargs)

        with mock.patch('abo.dienst.rechnung_stellen', side_effect=kaputt_fuer_a):
            with self.assertRaises(CommandError) as fehler:
                call_command('abo_abrechnung', heute='2026-12-01', stdout=io.StringIO(), stderr=io.StringIO())
        self.assertIn('Verwaltung A', str(fehler.exception))
        self.assertFalse(AboRechnung.alle_organisationen.filter(organisation=self.a.organisation).exists())
        self.assertTrue(AboRechnung.alle_organisationen.filter(organisation=self.b.organisation).exists(),
                        'Verwaltung B muss trotz des Fehlers bei A abgerechnet sein')

    def test_befehl_stellt_rechnung_und_meldet_sie(self):
        _verwaltet(self.a)
        aus = io.StringIO()
        call_command('abo_abrechnung', heute='2026-12-01', organisation=self.a.organisation.pk, stdout=aus)
        self.assertIn('1 Rechnung(en) gestellt', aus.getvalue())
        self.assertFalse(AboRechnung.alle_organisationen.filter(organisation=self.b.organisation).exists())

    def test_einstellen_zahlung_und_module(self):
        _verwaltet(self.a)
        call_command('abo_abrechnung', heute='2026-12-01', organisation=self.a.organisation.pk, stdout=io.StringIO())
        nummer = AboRechnung.alle_organisationen.get(organisation=self.a.organisation).nummer
        call_command('abo_einstellen', self.a.organisation.pk, module='signatur', zahlung=nummer,
                     datum='2026-12-05', stdout=io.StringIO())
        r = AboRechnung.alle_organisationen.get(organisation=self.a.organisation)
        self.assertEqual((r.status, r.bezahlt_am), ('bezahlt', date(2026, 12, 5)))
        self.assertEqual(Abonnement.alle_organisationen.get(organisation=self.a.organisation).zusatzmodule, ['signatur'])
        with self.assertRaises(CommandError):                 # Rechnung einer anderen Verwaltung
            call_command('abo_einstellen', self.b.organisation.pk, zahlung=nummer, stdout=io.StringIO())

    def test_einstellen_lehnt_tippfehler_im_modul_ab(self):
        with self.assertRaises(f.UnbekannteFunktion):
            call_command('abo_einstellen', self.a.organisation.pk, module='signatu', stdout=io.StringIO())


@override_settings(**FESTGELEGT)
class SeiteUndPdfTests(Basis):

    def _rechnung(self, bestand):
        _verwaltet(bestand)
        dienst.abrechnen(self.org(bestand), heute=date(2026, 12, 1))
        return AboRechnung.alle_organisationen.get(organisation=bestand.organisation)

    def test_pdf_mit_qr_rechnung(self):
        rechnung = self._rechnung(self.a)
        c = Client()
        c.force_login(self.a.benutzer)
        antwort = c.get(f'/neu/abonnement/rechnung/{rechnung.pk}/pdf/')
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort['Content-Type'], 'application/pdf')
        self.assertTrue(antwort.content.startswith(b'%PDF'))

    def test_pdf_einer_fremden_verwaltung_ist_404(self):
        fremd = self._rechnung(self.b)
        c = Client()
        c.force_login(self.a.benutzer)
        self.assertEqual(c.get(f'/neu/abonnement/rechnung/{fremd.pk}/pdf/').status_code, 404)
        # Gegenprobe: der Eigentümer der Rechnung kommt heran.
        c2 = Client()
        c2.force_login(self.b.benutzer)
        self.assertEqual(c2.get(f'/neu/abonnement/rechnung/{fremd.pk}/pdf/').status_code, 200)

    def test_pdf_nur_fuer_den_inhaber(self):
        from crm.models import Mitgliedschaft
        rechnung = self._rechnung(self.a)
        Mitgliedschaft.alle_organisationen.filter(benutzer=self.a.benutzer).update(rolle='Sachbearbeiter')
        c = Client()
        c.force_login(self.a.benutzer)
        self.assertEqual(c.get(f'/neu/abonnement/rechnung/{rechnung.pk}/pdf/').status_code, 403)

    @override_settings(ABO_RECHNUNGSSTELLER={**STELLER, 'iban': ''})
    def test_ohne_iban_des_betreibers_kein_pdf_sondern_hinweis(self):
        rechnung = self._rechnung(self.a)
        c = Client()
        c.force_login(self.a.benutzer)
        antwort = c.get(f'/neu/abonnement/rechnung/{rechnung.pk}/pdf/')
        self.assertEqual(antwort.status_code, 302)

    def test_seite_listet_nur_eigene_rechnungen(self):
        eigene = self._rechnung(self.a)
        fremde = self._rechnung(self.b)
        c = Client()
        c.force_login(self.a.benutzer)
        seite = c.get('/neu/abonnement/')
        self.assertContains(seite, eigene.nummer)
        self.assertNotContains(seite, fremde.nummer)

    def test_seite_zeigt_stufe_nutzung_und_module(self):
        _verwaltet(self.a)
        c = Client()
        c.force_login(self.a.benutzer)
        seite = c.get('/neu/abonnement/')
        self.assertContains(seite, 'Ihr Abonnement')
        self.assertContains(seite, 'Nutzung')
        self.assertContains(seite, 'Funktionen und Module')
        self.assertContains(seite, 'Gesperrt')       # die zubuchbaren Module sind nicht gebucht


class ModulpreisTests(Basis):
    """Zugebuchte Module stehen mit ihrem Preis auf der Rechnung; was im Grundpreis steckt, kostet nichts."""

    def test_preise_und_katalog_passen_zusammen(self):
        self.assertEqual(set(f.MODULPREISE), set(f.MODULE))
        self.assertEqual({k: v['monat'] for k, v in f.MODULPREISE.items()},
                         {'signatur': Decimal('9'), 'belegerkennung': Decimal('15'), 'reporting_erweitert': Decimal('19')})

    def test_modul_inklusive_nach_stufe(self):
        self.assertFalse(f.modul_inklusive('team', 'belegerkennung'))
        self.assertTrue(f.modul_inklusive('professional', 'belegerkennung'))
        self.assertFalse(f.modul_inklusive('enterprise', 'signatur'))
        self.assertEqual(f.modul_monatspreis('team', 'reporting_erweitert'), Decimal('19'))
        self.assertEqual(f.modul_monatspreis('professional', 'reporting_erweitert'), Decimal('0'))

    def test_betrag_mit_modulen(self):
        grund = f.monatspreis('team', 10)
        netto, _b = dienst.betrag_fuer('team', 10, False, ('signatur', 'belegerkennung', 'reporting_erweitert'))
        self.assertEqual(netto, grund + Decimal('9') + Decimal('15') + Decimal('19'))
        # Im Grundpreis enthaltene Module kosten nichts, die Unterschrift schon.
        netto, _b = dienst.betrag_fuer('professional', 10, False, ('signatur', 'belegerkennung'))
        self.assertEqual(netto, f.monatspreis('professional', 10) + Decimal('9'))

    def test_jaehrlich_rabatt_auch_auf_module(self):
        netto, _b, positionen = dienst.positionen_fuer('team', 10, True, ('signatur',))
        brutto_summe = (f.monatspreis('team', 10) + Decimal('9')) * 12
        self.assertEqual(netto, (brutto_summe * (1 - f.JAHRESRABATT)).quantize(Decimal('0.01')))
        self.assertEqual(sum(Decimal(p['betrag']) for p in positionen), netto, 'die Zeilen ergeben das Netto')
        self.assertIn('Jahresrabatt', positionen[-1]['text'])

    def test_rechnung_traegt_die_positionen(self):
        from django.test import override_settings
        abo = _verwaltet(self.a, 'team')
        abo.zusatzmodule = ['signatur']
        abo.save()
        with override_settings(**FESTGELEGT):
            rechnung = dienst.rechnung_stellen(self.org(self.a), abo, heute=date(2026, 12, 1))
        texte = [p['text'] for p in rechnung.positionen]
        self.assertEqual(texte[0], 'Abonnement Team, monatlich')
        self.assertEqual(texte[1], 'Digitale Unterschrift')
        self.assertEqual(rechnung.netto, f.monatspreis('team', rechnung.einheiten) + Decimal('9'))
        # Später geänderte Preise ändern die gestellte Rechnung nicht.
        with mock.patch.dict(f.MODULPREISE, {'signatur': {'monat': Decimal('99'), 'inklusive_ab': None}}):
            rechnung.refresh_from_db()
            self.assertEqual(rechnung.netto, f.monatspreis('team', rechnung.einheiten) + Decimal('9'))

    def test_pdf_zeigt_die_modulzeile(self):
        from django.test import override_settings

        from abo.rechnung_pdf import abo_rechnung_pdf
        abo = _verwaltet(self.a, 'team')
        abo.zusatzmodule = ['signatur']
        abo.save()
        with override_settings(**FESTGELEGT):
            rechnung = dienst.rechnung_stellen(self.org(self.a), abo, heute=date(2026, 12, 1))
            pdf = abo_rechnung_pdf(rechnung)
        self.assertTrue(pdf.startswith(b'%PDF'))
        import io

        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf)) as seite:
            text = seite.pages[0].extract_text()
        self.assertIn('Digitale Unterschrift', text)
        self.assertIn('Abonnement Team, monatlich', text)

    def test_wechsel_auf_team_meldet_den_verlust_der_inklusiven_module(self):
        abo = _verwaltet(self.a, 'professional')
        org = self.org(self.a)
        folgen = dienst.folgen_des_wechsels(org, 'team')
        self.assertIn('belegerkennung', folgen['schliesst'])
        self.assertIn('reporting_erweitert', folgen['schliesst'])
        # Zugebucht bleibt offen: dann schliesst der Wechsel nichts.
        abo.zusatzmodule = ['belegerkennung']
        abo.save()
        folgen = dienst.folgen_des_wechsels(self.org(self.a), 'team')
        self.assertNotIn('belegerkennung', folgen['schliesst'])
        self.assertIn('reporting_erweitert', folgen['schliesst'])

