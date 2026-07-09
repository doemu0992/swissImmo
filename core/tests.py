"""Regressionstests für die P1/P2-Features (Serienbrief, Auto-Ablage,
Eigentümer-/Mieterportal, Reparaturfreigabe, Datenqualität, Akonto,
Wartungsfristen, MWST-ESTV). Ziel: die neu gebauten Flows dauerhaft
gegen Regressionen absichern."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.contrib.auth.models import User, Group

from crm.models import Mieter, Mandant, Verwaltung
from portfolio.models import Liegenschaft, Einheit, Wartungsfrist
from rentals.models import Mietvertrag


def _team_user(rolle='Verwaltung'):
    grp, _ = Group.objects.get_or_create(name=rolle)
    u = User.objects.create_user(username=f'team_{rolle}', password='x')
    u.groups.add(grp)
    return u


def _basis_objekte():
    lg = Liegenschaft.objects.create(strasse='Teststrasse 1', plz='8000', ort='Zürich',
                                     versicherungswert=Decimal('1000000'))
    e = Einheit.objects.create(liegenschaft=lg, bezeichnung='3.5 Zi', typ='wohnung',
                               nettomiete_aktuell=Decimal('1500'), nebenkosten_aktuell=Decimal('200'))
    m = Mieter.objects.create(typ='person', vorname='Hans', nachname='Muster',
                              email='hans@example.ch', strasse='Seeweg 3', plz='8000', ort='Zürich')
    v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                   netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                                   status='aktiv', kautions_betrag=Decimal('4500'))
    return lg, e, m, v


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


class EigentuemerPortalTests(TestCase):
    def _mandant_login(self):
        lg, e, m, v = _basis_objekte()
        md = Mandant.objects.create(firma_oder_name='Eigentümer AG')
        lg.mandant = md; lg.save()
        u = User.objects.create_user(username='eig', password='x')
        md.benutzer = u; md.save()
        return md, lg, u

    def test_cockpit_kpis(self):
        md, lg, u = self._mandant_login()
        c = Client(); c.force_login(u)
        r = c.get('/portal/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Leerstandsquote')
        self.assertContains(r, 'Bruttorendite')  # versicherungswert gesetzt

    def test_report_pdf(self):
        md, lg, u = self._mandant_login()
        c = Client(); c.force_login(u)
        r = c.get('/portal/report/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_fremddokument_404(self):
        from portfolio.models import Dokument as PDok
        from django.core.files.base import ContentFile
        md, lg, u = self._mandant_login()
        fremd = Liegenschaft.objects.create(strasse='X', plz='9', ort='Y')
        d = PDok(liegenschaft=fremd, titel='Fremd', kategorie='x')
        d.datei.save('f.pdf', ContentFile(b'%PDF'), save=True)
        c = Client(); c.force_login(u)
        self.assertEqual(c.get(f'/portal/dokument/{d.id}/').status_code, 404)


class ReparaturFreigabeTests(TestCase):
    def test_freigabe_flow(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        lg, e, m, v = _basis_objekte()
        md = Mandant.objects.create(firma_oder_name='Eig AG')
        lg.mandant = md; lg.save()
        u = User.objects.create_user(username='eig2', password='x'); md.benutzer = u; md.save()
        from crm.models import Handwerker
        hw = Handwerker.objects.create(firma='Sanitär AG')
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Heizung', beschreibung='x')
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, freigabe_status='ausstehend', kosten_geschaetzt=Decimal('2000'))
        c = Client(); c.force_login(u)
        self.assertContains(c.get('/portal/'), 'Reparaturen zur Freigabe')
        r = c.post(f'/portal/freigabe/{a.id}/', {'aktion': 'freigeben', 'kommentar': 'ok'})
        self.assertEqual(r.status_code, 302)
        a.refresh_from_db()
        self.assertEqual(a.freigabe_status, 'freigegeben')
        self.assertEqual(a.freigabe_kommentar, 'ok')

    def test_schwelle_automatisch(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        lg, e, m, v = _basis_objekte()
        from crm.models import Handwerker
        hw = Handwerker.objects.create(firma='Elektro AG')
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='X', beschreibung='y')
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, freigabe_status='nicht_noetig')
        u = _team_user()
        c = Client(); c.force_login(u)
        c.post(f'/neu/auftrag/{a.id}/kosten/', {'kosten_geschaetzt': '2500'})
        a.refresh_from_db()
        self.assertEqual(a.freigabe_status, 'ausstehend')


class DatenqualitaetTests(TestCase):
    def test_pflichtfeld_nachname(self):
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post('/neu/personen/neu/', {'typ': 'person', 'vorname': 'Nur Vorname'})
        self.assertContains(r, 'erforderlich')
        self.assertFalse(Mieter.objects.filter(vorname='Nur Vorname').exists())

    def test_dublette_und_override(self):
        Mieter.objects.create(typ='person', vorname='Max', nachname='Zwilling', plz='9000', ort='SG')
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post('/neu/personen/neu/', {'typ': 'person', 'vorname': 'Max', 'nachname': 'Zwilling', 'plz': '9000', 'ort': 'SG'})
        self.assertContains(r, 'Dublette')
        self.assertEqual(Mieter.objects.filter(nachname='Zwilling').count(), 1)
        r2 = c.post('/neu/personen/neu/', {'typ': 'person', 'vorname': 'Max', 'nachname': 'Zwilling', 'plz': '9000', 'ort': 'SG', 'dublette_ok': '1'})
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(Mieter.objects.filter(nachname='Zwilling').count(), 2)


class IbanTests(TestCase):
    def test_validierung(self):
        from core.services.iban import ist_gueltige_iban, formatiere_iban
        self.assertTrue(ist_gueltige_iban('CH9300762011623852957'))
        self.assertTrue(ist_gueltige_iban('CH93 0076 2011 6238 5295 7'))
        self.assertFalse(ist_gueltige_iban('CH9300762011623852958'))
        self.assertFalse(ist_gueltige_iban('HELLO'))
        self.assertEqual(formatiere_iban('CH9300762011623852957'), 'CH93 0076 2011 6238 5295 7')

    def test_person_form_lehnt_falsche_iban_ab(self):
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post('/neu/personen/neu/', {'typ': 'person', 'nachname': 'IbanTest', 'iban': 'CH0000000000000000000'})
        self.assertContains(r, 'IBAN ist ungültig')
        self.assertFalse(Mieter.objects.filter(nachname='IbanTest').exists())

    def test_person_form_speichert_gueltige_iban_formatiert(self):
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post('/neu/personen/neu/', {'typ': 'person', 'nachname': 'IbanOk', 'iban': 'CH9300762011623852957'})
        self.assertEqual(r.status_code, 302)
        m = Mieter.objects.get(nachname='IbanOk')
        self.assertEqual(m.iban, 'CH93 0076 2011 6238 5295 7')


class WartungsfristTests(TestCase):
    def test_pendenz_und_rollover(self):
        from core.services.automation import generate_auto_pendenzen, _plus_monate
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        wf = Wartungsfrist.objects.create(liegenschaft=lg, art='versicherung', bezeichnung='Police',
                                          naechste_faelligkeit=date.today() + timedelta(days=10),
                                          intervall_monate=12)
        generate_auto_pendenzen(horizont_tage=90)
        self.assertTrue(Pendenz.objects.filter(quelle__startswith=f'auto:wartung:{wf.id}').exists())
        # Rollover
        wf.naechste_faelligkeit = date.today() - timedelta(days=400); wf.save()
        generate_auto_pendenzen(horizont_tage=90)
        wf.refresh_from_db()
        self.assertGreaterEqual(wf.naechste_faelligkeit, date.today())
        self.assertEqual(_plus_monate(date(2026, 1, 31), 1), date(2026, 2, 28))


class MwstEstvTests(TestCase):
    def test_effektiv(self):
        from core.services.mwst_estv import berechne_estv
        e = berechne_estv(umsatz_steuerbar=Decimal('120000'), umsatzsteuer=Decimal('9720'),
                          vorsteuer_material=Decimal('3000'), vorsteuer_invest=Decimal('500'))
        self.assertEqual(e['z479'], Decimal('3500.00'))
        self.assertEqual(e['z500'], Decimal('6220.00'))

    def test_guthaben(self):
        from core.services.mwst_estv import berechne_estv
        e = berechne_estv(umsatz_steuerbar=Decimal('10000'), umsatzsteuer=Decimal('810'),
                          vorsteuer_material=Decimal('2000'), vorsteuer_invest=Decimal('0'))
        self.assertEqual(e['z500'], Decimal('0.00'))
        self.assertEqual(e['z510'], Decimal('1190.00'))

    def test_saldosteuersatz(self):
        from core.services.mwst_estv import berechne_estv
        e = berechne_estv(umsatz_steuerbar=Decimal('120000'), umsatzsteuer=Decimal('0'),
                          vorsteuer_material=Decimal('0'), vorsteuer_invest=Decimal('0'),
                          methode='saldo', saldosteuersatz=Decimal('6.5'))
        self.assertEqual(e['z500'], Decimal('7800.00'))


class MieterPortalTests(TestCase):
    def _mieter_login(self):
        lg, e, m, v = _basis_objekte()
        u = User.objects.create_user(username='mieter1', password='x')
        m.benutzer = u; m.save()
        return m, v, u

    def test_portal_zeigt_objekt(self):
        m, v, u = self._mieter_login()
        c = Client(); c.force_login(u)
        r = c.get('/mieter/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Ihr Mietobjekt')
        self.assertContains(r, 'Teststrasse 1')

    def test_nach_login_routing(self):
        m, v, u = self._mieter_login()
        c = Client(); c.force_login(u)
        r = c.get('/nach-login/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.endswith('/mieter/'))

    def test_schaden_melden(self):
        from tickets.models import SchadenMeldung
        m, v, u = self._mieter_login()
        c = Client(); c.force_login(u)
        r = c.post('/mieter/schaden/', {'vertrag_id': str(v.id), 'titel': 'Leck', 'beschreibung': 'tropft'})
        self.assertEqual(r.status_code, 302)
        t = SchadenMeldung.objects.filter(titel='Leck').first()
        self.assertIsNotNone(t)
        self.assertEqual(t.gemeldet_von_id, m.id)
        self.assertEqual(t.betroffene_einheit_id, v.einheit_id)

    def test_offene_rechnung_und_qr(self):
        from finance.models import DebitorenRechnung
        from crm.models import Verwaltung
        m, v, u = self._mieter_login()
        # IBAN für QR-Bill bereitstellen
        Verwaltung.objects.create(firma='Verwaltung AG', strasse='W 1', plz='8000', ort='Zürich',
                                  iban='CH9300762011623852957')
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=v.einheit.liegenschaft,
                                         titel='Miete Januar', betrag=Decimal('1700'),
                                         faellig_am=date.today(), status='offen')
        c = Client(); c.force_login(u)
        r = c.get('/mieter/')
        self.assertContains(r, 'Offene Rechnungen')
        self.assertContains(r, 'Miete Januar')
        rech = DebitorenRechnung.objects.get(titel='Miete Januar')
        pdf = c.get(f'/mieter/rechnung/{rech.id}/')
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')

    def test_fremde_rechnung_404(self):
        from finance.models import DebitorenRechnung
        m, v, u = self._mieter_login()
        # Rechnung eines anderen Mieters
        m2 = Mieter.objects.create(typ='person', nachname='Fremd')
        v2 = Mietvertrag.objects.create(mieter=m2, einheit=v.einheit, beginn=date(2020, 1, 1),
                                        netto_mietzins=Decimal('100'), nebenkosten=Decimal('0'), status='beendet')
        fremd = DebitorenRechnung.objects.create(vertrag=v2, titel='Fremd', betrag=Decimal('50'), status='offen')
        c = Client(); c.force_login(u)
        self.assertEqual(c.get(f'/mieter/rechnung/{fremd.id}/').status_code, 404)

    def test_verwalter_erstellt_zugang(self):
        lg, e, m, v = _basis_objekte()
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post(f'/neu/personen/{m.id}/portal-zugang/', {'aktion': 'erstellen'})
        self.assertEqual(r.status_code, 302)
        m.refresh_from_db()
        self.assertIsNotNone(m.benutzer_id)

    def test_zugangsdaten_werden_gemailt(self):
        from django.core import mail
        lg, e, m, v = _basis_objekte()  # m.email = hans@example.ch
        u = _team_user()
        c = Client(); c.force_login(u)
        c.post(f'/neu/personen/{m.id}/portal-zugang/', {'aktion': 'erstellen'})
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn(m.email, msg.to)
        m.refresh_from_db()
        self.assertIn(m.benutzer.username, msg.body)   # Benutzername in der Mail
        self.assertIn('/login/', msg.body)             # Login-Link in der Mail

    def test_kein_mail_ohne_adresse(self):
        from django.core import mail
        lg, e, m, v = _basis_objekte()
        m.email = ''; m.save()
        u = _team_user()
        c = Client(); c.force_login(u)
        c.post(f'/neu/personen/{m.id}/portal-zugang/', {'aktion': 'erstellen'})
        self.assertEqual(len(mail.outbox), 0)
        m.refresh_from_db()
        self.assertIsNotNone(m.benutzer_id)  # Zugang trotzdem erstellt


class DashboardCockpitTests(TestCase):
    def test_cockpit_zaehlt_freigaben_und_fristen(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        lg, e, m, v = _basis_objekte()
        hw = Handwerker.objects.create(firma='HW AG')
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='X', beschreibung='y')
        HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, freigabe_status='ausstehend')
        Wartungsfrist.objects.create(liegenschaft=lg, bezeichnung='Wartung',
                                     naechste_faelligkeit=date.today() + timedelta(days=10))
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.get('/neu/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['cockpit']['freigaben'], 1)
        self.assertEqual(r.context['cockpit']['fristen'], 1)


class MieterkontoTests(TestCase):
    def test_saldo_und_reihenfolge(self):
        from finance.models import DebitorenRechnung, Zahlungseingang
        from core.services.mieterkonto import berechne_mieterkonto
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(vertrag=v, titel='Miete Jan', betrag=Decimal('1700'),
                                         datum=date(2025, 1, 1), status='offen')
        DebitorenRechnung.objects.create(vertrag=v, titel='Miete Feb', betrag=Decimal('1700'),
                                         datum=date(2025, 2, 1), status='offen')
        Zahlungseingang.objects.create(vertrag=v, betrag=Decimal('1700'),
                                       datum_eingang=date(2025, 1, 15), status='verbucht')
        zeilen, saldo = berechne_mieterkonto(m)
        self.assertEqual(len(zeilen), 3)
        self.assertEqual(saldo, Decimal('1700'))  # 1700+1700-1700
        # laufender Saldo nach der Zahlung = 0
        self.assertEqual(zeilen[1]['saldo'], Decimal('0'))

    def test_pdf_view_team_und_mieter(self):
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(vertrag=v, titel='Miete', betrag=Decimal('1700'),
                                         datum=date(2025, 1, 1), status='offen')
        # Team
        tu = _team_user()
        tc = Client(); tc.force_login(tu)
        r = tc.get(f'/neu/personen/{m.id}/kontoauszug/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        # Mieter
        u = User.objects.create_user(username='mk_mieter', password='x')
        m.benutzer = u; m.save()
        mc = Client(); mc.force_login(u)
        r2 = mc.get('/mieter/kontoauszug/')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2['Content-Type'], 'application/pdf')


class PersonLoeschenTests(TestCase):
    def test_ohne_vertrag_loeschbar(self):
        m = Mieter.objects.create(typ='person', nachname='Weg')
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post(f'/neu/personen/{m.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Mieter.objects.filter(id=m.id).exists())

    def test_aktiver_vertrag_blockiert(self):
        lg, e, m, v = _basis_objekte()  # v ist aktiv
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post(f'/neu/personen/{m.id}/loeschen/', follow=True)
        self.assertTrue(Mieter.objects.filter(id=m.id).exists())
        self.assertContains(r, 'kann nicht gelöscht werden')

    def test_portal_login_wird_mitgeloescht(self):
        m = Mieter.objects.create(typ='person', nachname='PortalWeg')
        pu = User.objects.create_user(username='portalweg@x.ch', password='x')
        m.benutzer = pu; m.save()
        u = _team_user()
        c = Client(); c.force_login(u)
        c.post(f'/neu/personen/{m.id}/loeschen/')
        self.assertFalse(Mieter.objects.filter(id=m.id).exists())
        self.assertFalse(User.objects.filter(id=pu.id).exists())


class BenutzerListeTests(TestCase):
    def test_portalkonten_ausgeblendet_teamkonten_sichtbar(self):
        team = _team_user()  # Gruppe 'Verwaltung'
        # Mieter-Portal-Konto
        mu = User.objects.create_user(username='miet_portal@x.ch')
        m = Mieter.objects.create(typ='person', nachname='PL'); m.benutzer = mu; m.save()
        c = Client(); c.force_login(team)
        r = c.get('/neu/benutzer/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, team.username)
        self.assertNotContains(r, 'miet_portal@x.ch')
        self.assertContains(r, 'Löschen')


class LoginBackendTests(TestCase):
    """Robuste Anmeldung: Gross-/Kleinschreibung, Leerzeichen, Namenskollision."""

    def test_case_insensitiv_und_whitespace(self):
        from django.contrib.auth import authenticate
        User.objects.create_user(username='mieter@example.ch', password='Pass-123')
        self.assertIsNotNone(authenticate(username='mieter@example.ch', password='Pass-123'))
        self.assertIsNotNone(authenticate(username='Mieter@example.ch', password='Pass-123'))
        self.assertIsNotNone(authenticate(username='  mieter@example.ch ', password='Pass-123'))
        self.assertIsNone(authenticate(username='mieter@example.ch', password='falsch'))

    def test_namenskollision_email_trifft_richtiges_konto(self):
        from django.contrib.auth import authenticate
        # Admin belegt die E-Mail bereits als Benutzername
        admin = User.objects.create_user(username='chef@example.ch', email='chef@example.ch', password='AdminPW1')
        # Mieter kollidiert -> abweichender Benutzername, gleiche E-Mail
        mieter = User.objects.create_user(username='chef@example.ch.1', email='chef@example.ch', password='MieterPW9')
        # Login mit reiner E-Mail + Mieter-Passwort -> Mieter-Konto
        u1 = authenticate(username='chef@example.ch', password='MieterPW9')
        self.assertEqual(u1, mieter)
        # Login mit reiner E-Mail + Admin-Passwort -> Admin-Konto
        u2 = authenticate(username='chef@example.ch', password='AdminPW1')
        self.assertEqual(u2, admin)

    def test_login_view_mieter(self):
        lg, e, m, v = _basis_objekte()
        u = User.objects.create_user(username='mieterview@example.ch', password='Geheim-1')
        m.benutzer = u; m.save()
        c = Client()
        # Login mit grossgeschriebener Eingabe (iOS-Verhalten)
        ok = c.login(username='Mieterview@example.ch', password='Geheim-1')
        self.assertTrue(ok)


class MieterKuendigungTests(TestCase):
    def _login(self):
        lg, e, m, v = _basis_objekte()
        u = User.objects.create_user(username='kuend_mieter', password='x')
        m.benutzer = u; m.save()
        return lg, e, m, v, u

    def test_nur_eigene_objekte(self):
        lg, e, m, v, u = self._login()
        # Fremdes Objekt + fremder aktiver Vertrag
        fremd_m = Mieter.objects.create(typ='person', nachname='Fremd')
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='FREMD-Whg', typ='wohnung')
        Mietvertrag.objects.create(mieter=fremd_m, einheit=e2, beginn=date(2020, 1, 1),
                                   netto_mietzins=Decimal('1'), nebenkosten=Decimal('0'), status='aktiv')
        c = Client(); c.force_login(u)
        r = c.get('/mieter/kuendigung/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '3.5 Zi')       # eigenes Objekt
        self.assertNotContains(r, 'FREMD-Whg')  # fremdes Objekt NICHT

    def test_erfassen_erzeugt_kuendigung_ohne_status_wechsel(self):
        from rentals.models import Kuendigung
        lg, e, m, v, u = self._login()
        c = Client(); c.force_login(u)
        r = c.post('/mieter/kuendigung/', {'vertrag_id': str(v.id)})
        self.assertEqual(r.status_code, 302)
        k = Kuendigung.objects.filter(vertrag=v).first()
        self.assertIsNotNone(k)
        self.assertEqual(k.absender, 'mieter')
        self.assertEqual(k.status, 'erfasst')
        self.assertEqual(k.zustellung, 'einschreiben')
        self.assertIsNotNone(k.per_datum)
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')  # Verwaltung bestätigt -> noch nicht gekündigt

    def test_brief_pdf_und_isolation(self):
        from rentals.models import Kuendigung
        lg, e, m, v, u = self._login()
        c = Client(); c.force_login(u)
        c.post('/mieter/kuendigung/', {'vertrag_id': str(v.id)})
        k = Kuendigung.objects.get(vertrag=v)
        r = c.get(f'/mieter/kuendigung/{k.id}/brief/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        # Fremder Mieter kommt nicht an den Brief
        m2 = Mieter.objects.create(typ='person', nachname='Andere')
        u2 = User.objects.create_user(username='andere', password='x'); m2.benutzer = u2; m2.save()
        c2 = Client(); c2.force_login(u2)
        self.assertEqual(c2.get(f'/mieter/kuendigung/{k.id}/brief/').status_code, 404)

    def test_verwalter_bestaetigt_portal_kuendigung(self):
        from rentals.models import Kuendigung
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        u = User.objects.create_user(username='kuend_mieter2', password='x'); m.benutzer = u; m.save()
        c = Client(); c.force_login(u)
        c.post('/mieter/kuendigung/', {'vertrag_id': str(v.id)})
        k = Kuendigung.objects.get(vertrag=v)
        # Verwalter bestätigt
        team = _team_user()
        tc = Client(); tc.force_login(team)
        r = tc.post(f'/neu/kuendigung/{k.id}/bestaetigen/')
        self.assertEqual(r.status_code, 302)
        k.refresh_from_db(); v.refresh_from_db()
        self.assertEqual(k.status, 'bestaetigt')
        self.assertEqual(v.status, 'gekuendigt')
        self.assertIsNotNone(v.ende)
        self.assertGreater(Pendenz.objects.filter(vertrag=v).count(), 0)  # Auszugs-Pendenzen

    def test_familienwohnung_zwei_unterschriften(self):
        from rentals.models import Kuendigung
        from core.services.kuendigung_brief import generate_kuendigung_mieter_pdf
        lg, e, m, v, u = self._login()
        v.familienwohnung = True; v.mitmieter_name = 'Anna Muster'; v.save()
        k = Kuendigung.objects.create(vertrag=v, absender='mieter', eingang_datum=date.today(),
                                      berechneter_termin=date(2025, 6, 30), per_datum=date(2025, 6, 30),
                                      status='erfasst')
        pdf = generate_kuendigung_mieter_pdf(v, k)
        self.assertTrue(pdf.startswith(b'%PDF'))
        # Text prüfen via pdf-Rohbytes (Namen im Content-Stream)
        try:
            import fitz
            doc = fitz.open(stream=pdf, filetype='pdf')
            txt = doc[0].get_text()
            self.assertIn('Anna Muster', txt)
            self.assertIn('266m', txt)
        except ImportError:
            pass


class MieterDokumenteTests(TestCase):
    def _setup(self):
        from django.core.files.base import ContentFile
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        u = User.objects.create_user(username='dok_mieter', password='x'); m.benutzer = u; m.save()
        dv = Dokument(vertrag=v, bezeichnung='Mietvertrag', kategorie='vertrag')
        dv.datei.save('mv.pdf', ContentFile(b'%PDF'), save=True)
        di = Dokument(mieter=m, bezeichnung='Intern', kategorie='sonstiges', im_portal_sichtbar=False)
        di.datei.save('int.pdf', ContentFile(b'%PDF'), save=True)
        return lg, e, m, v, u, dv, di

    def test_vertragsdok_sichtbar_intern_versteckt(self):
        lg, e, m, v, u, dv, di = self._setup()
        c = Client(); c.force_login(u)
        body = c.get('/mieter/').content.decode()
        self.assertIn('Mietvertrag', body)
        self.assertNotIn('Intern', body)
        self.assertEqual(c.get(f'/mieter/dokument/{dv.id}/').status_code, 200)
        self.assertEqual(c.get(f'/mieter/dokument/{di.id}/').status_code, 404)  # versteckt

    def test_verwalter_toggle_versteckt(self):
        lg, e, m, v, u, dv, di = self._setup()
        team = _team_user()
        tc = Client(); tc.force_login(team)
        tc.post(f'/neu/dokument/{dv.id}/portal-sichtbar/')
        dv.refresh_from_db()
        self.assertFalse(dv.im_portal_sichtbar)
        c = Client(); c.force_login(u)
        self.assertNotIn('Mietvertrag', c.get('/mieter/').content.decode())
        self.assertEqual(c.get(f'/mieter/dokument/{dv.id}/').status_code, 404)

    def test_serienbrief_pro_empfaenger_abgelegt(self):
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        team = _team_user()
        c = Client(); c.force_login(team)
        vor = Dokument.objects.filter(mieter=m, kategorie='korrespondenz').count()
        c.post('/neu/kommunikation/serienbrief/', {'betreff': 'Info X', 'text': 'Hallo {name}', 'empfaenger_id': [str(m.id)]})
        nach = Dokument.objects.filter(mieter=m, kategorie='korrespondenz').count()
        self.assertEqual(nach, vor + 1)
        # und im Portal des Mieters sichtbar
        u = User.objects.create_user(username='sb_mieter', password='x'); m.benutzer = u; m.save()
        mc = Client(); mc.force_login(u)
        self.assertIn('Brief: Info X', mc.get('/mieter/').content.decode())


class SicherheitsIsolationTests(TestCase):
    """Stellt sicher, dass Portale strikt isoliert sind (keine Cross-Tenant-Lecks)."""

    def test_mieter_kann_keine_team_seite(self):
        lg, e, m, v = _basis_objekte()
        u = User.objects.create_user(username='miet_iso', password='x')
        m.benutzer = u; m.save()
        c = Client(); c.force_login(u)
        # /neu/ ist team-gated -> Mieter wird ab-/weggeleitet, sieht keine Verwaltungsdaten
        r = c.get('/neu/debitoren/')
        self.assertdenied(r)

    def test_eigentuemer_fremde_freigabe_404(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        lg, e, m, v = _basis_objekte()
        eig_lg = Liegenschaft.objects.create(strasse='Eig 1', plz='3000', ort='Bern')
        md = Mandant.objects.create(firma_oder_name='Eig AG'); eig_lg.mandant = md; eig_lg.save()
        u = User.objects.create_user(username='eig_iso', password='x'); md.benutzer = u; md.save()
        # Freigabe an FREMDER Liegenschaft (nicht dem Mandanten zugeordnet)
        hw = Handwerker.objects.create(firma='HW')
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='X', beschreibung='y')
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, freigabe_status='ausstehend')
        c = Client(); c.force_login(u)
        r = c.post(f'/portal/freigabe/{a.id}/', {'aktion': 'freigeben'})
        self.assertEqual(r.status_code, 404)
        a.refresh_from_db()
        self.assertEqual(a.freigabe_status, 'ausstehend')  # unverändert

    def test_mieter_fremdes_dokument_404(self):
        from rentals.models import Dokument as RDok
        from django.core.files.base import ContentFile
        lg, e, m, v = _basis_objekte()
        u = User.objects.create_user(username='miet_iso2', password='x'); m.benutzer = u; m.save()
        fremd = Mieter.objects.create(typ='person', nachname='Fremd')
        d = RDok(mieter=fremd, bezeichnung='Fremd', titel='Fremd', kategorie='x')
        d.datei.save('f.pdf', ContentFile(b'%PDF'), save=True)
        c = Client(); c.force_login(u)
        self.assertEqual(c.get(f'/mieter/dokument/{d.id}/').status_code, 404)

    def assertdenied(self, r):
        # Team-Guard: entweder Redirect (weg) oder 403 — jedenfalls kein 200 mit Daten
        self.assertIn(r.status_code, (302, 403))


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
