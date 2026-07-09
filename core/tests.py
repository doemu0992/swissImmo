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

    def test_eigene_seiten_laden(self):
        m, v, u = self._mieter_login()
        c = Client(); c.force_login(u)
        # Übersicht verlinkt auf die dedizierten Seiten (keine Sprungmarken)
        body = c.get('/mieter/').content.decode()
        self.assertIn('/mieter/rechnungen/', body)
        self.assertIn('/mieter/dokumente/', body)
        self.assertIn('/mieter/schaden/neu/', body)
        # und jede Seite lädt eigenständig
        self.assertEqual(c.get('/mieter/rechnungen/').status_code, 200)
        self.assertEqual(c.get('/mieter/dokumente/').status_code, 200)
        self.assertContains(c.get('/mieter/schaden/neu/'), 'Schaden / Reparatur melden')

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
        # Übersicht zeigt den Rechnungs-Zähler …
        self.assertContains(c.get('/mieter/'), 'Rechnungen')
        # … die Detailseite die Positionen
        r = c.get('/mieter/rechnungen/')
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

    def test_portal_login_seite_lädt(self):
        c = Client()
        r = c.get('/portal/login/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Portal')
        # postet auf denselben Endpoint
        self.assertContains(r, 'action="/portal/login/"')

    def test_mieterportal_hat_sidebar(self):
        lg, e, m, v = _basis_objekte()
        u = User.objects.create_user(username='sidebar_mieter', password='x')
        m.benutzer = u; m.save()
        c = Client(); c.force_login(u)
        body = c.get('/mieter/').content.decode()
        self.assertIn('id="pSidebar"', body)   # gemeinsame Portal-Shell
        self.assertIn('Übersicht', body)
        self.assertIn('Meine Meldungen', body)


class MitmieterPortalTests(TestCase):
    """2-Personen-Vertrag: auch die Zweitperson (mitmieter) sieht alles."""
    def _setup(self):
        from django.core.files.base import ContentFile
        from rentals.models import Dokument
        lg = Liegenschaft.objects.create(strasse='Paar 1', plz='3000', ort='Bern')
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='4.5 Zi', typ='wohnung')
        m1 = Mieter.objects.create(typ='person', nachname='Erst')
        m2 = Mieter.objects.create(typ='person', nachname='Zweit')
        v = Mietvertrag.objects.create(mieter=m1, mitmieter=m2, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal('1200'), nebenkosten=Decimal('150'),
                                       status='aktiv', familienwohnung=True)
        u2 = User.objects.create_user(username='zweit', password='x'); m2.benutzer = u2; m2.save()
        d = Dokument(vertrag=v, bezeichnung='Mietvertrag', kategorie='vertrag')
        d.datei.save('mv.pdf', ContentFile(b'%PDF'), save=True)
        return lg, e, m1, m2, v, u2, d

    def test_zweitperson_sieht_objekt_und_dokument(self):
        lg, e, m1, m2, v, u2, d = self._setup()
        c = Client(); c.force_login(u2)
        body = c.get('/mieter/').content.decode()
        self.assertIn('Ihr Mietobjekt', body)
        self.assertIn('Paar 1', body)
        self.assertIn('Mietvertrag', c.get('/mieter/dokumente/').content.decode())
        self.assertEqual(c.get(f'/mieter/dokument/{d.id}/').status_code, 200)

    def test_zweitperson_kann_kuendigen(self):
        from rentals.models import Kuendigung
        lg, e, m1, m2, v, u2, d = self._setup()
        c = Client(); c.force_login(u2)
        self.assertContains(c.get('/mieter/kuendigung/'), '4.5 Zi')
        r = c.post('/mieter/kuendigung/', {'vertrag_id': str(v.id)})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Kuendigung.objects.filter(vertrag=v).exists())

    def test_zweitperson_zeigt_mietobjekt_in_personenliste(self):
        lg, e, m1, m2, v, u2, d = self._setup()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/personen/').content.decode()
        # Beide Namen erscheinen mit dem gemieteten Objekt (Strasse der Liegenschaft)
        self.assertIn('Erst', body)
        self.assertIn('Zweit', body)
        self.assertGreaterEqual(body.count('Paar 1'), 2)  # beim Haupt- UND Mitmieter
        # Global-Filter auf die Liegenschaft: Mitmieter bleibt sichtbar
        gefiltert = c.get(f'/neu/personen/?lg={lg.id}').content.decode()
        self.assertIn('Zweit', gefiltert)

    def test_zweitperson_detailseite_zeigt_vertrag(self):
        lg, e, m1, m2, v, u2, d = self._setup()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get(f'/neu/personen/{m2.id}/').content.decode()
        self.assertIn('Paar 1', body)   # gemietetes Objekt beim Mitmieter
        self.assertIn('4.5 Zi', body)

    def test_qr_schuldner_beide_namen(self):
        from core.services.debitor_qr import schuldner_name
        lg, e, m1, m2, v, u2, d = self._setup()
        name = schuldner_name(v)
        self.assertIn(m1.display_name, name)
        self.assertIn(m2.display_name, name)
        self.assertIn('&', name)

    def test_begleitbrief_nennt_beide(self):
        from core.services.dokument_service import generate_dokument_pdf_bytes
        lg, e, m1, m2, v, u2, d = self._setup()
        # smoke: PDF erzeugt sich ohne Fehler bei 2-Personen-Vertrag
        pdf = generate_dokument_pdf_bytes(v, 'begleitbrief')
        self.assertTrue(pdf.startswith(b'%PDF'))
        # Template-Logik direkt prüfen: beide Namen im Adressblock
        from django.template.loader import get_template
        html = get_template('core/dok_begleitbrief.html').render({
            'vertrag': v, 'mieter': m1, 'mitmieter': m2, 'mitmieter_name': m2.display_name,
            'einheit': e, 'liegenschaft': lg, 'heute': date.today(),
            'vermieter_name': 'V AG', 'brutto_fmt': '0.00', 'kaution_fmt': '0.00', 'signed': False,
        })
        self.assertIn(m1.display_name, html)
        self.assertIn(m2.display_name, html)


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
        body = c.get('/mieter/dokumente/').content.decode()
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
        self.assertNotIn('Mietvertrag', c.get('/mieter/dokumente/').content.decode())
        self.assertEqual(c.get(f'/mieter/dokument/{dv.id}/').status_code, 404)

    def test_vertragsdokument_automatisch_abgelegt(self):
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        u = User.objects.create_user(username='vd_mieter', password='x'); m.benutzer = u; m.save()
        team = _team_user()
        tc = Client(); tc.force_login(team)
        r = tc.get(f'/vertrag/{v.id}/pdf/')
        self.assertEqual(r.status_code, 200)
        d = Dokument.objects.filter(vertrag=v, kategorie='vertrag').first()
        self.assertIsNotNone(d)
        self.assertEqual(d.mieter_id, m.id)
        # Dedup: erneute Generierung erzeugt kein Duplikat
        tc.get(f'/vertrag/{v.id}/pdf/')
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 1)
        # im Portal sichtbar
        mc = Client(); mc.force_login(u)
        self.assertIn('Mietvertrag', mc.get('/mieter/dokumente/').content.decode())

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
        self.assertIn('Brief: Info X', mc.get('/mieter/dokumente/').content.decode())

    def test_vertragspaket_zip_download(self):
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.get(f'/vertrag/{v.id}/dokumente-zip/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/zip')
        # Mehrere Dokumente in der Akte (Mietvertrag + Beilagen)
        anzahl = Dokument.objects.filter(vertrag=v, kategorie='vertrag').count()
        self.assertGreaterEqual(anzahl, 2)
        # ZIP enthält mindestens den Mietvertrag
        import io, zipfile
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        self.assertTrue(any('Mietvertrag' in n for n in zf.namelist()))


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


class TicketPortalTests(TestCase):
    """Schadenmeldung aus dem Mieterportal: E-Mails + Sidebar-Badge (gelesen)."""

    def _setup(self):
        lg, e, m, v = _basis_objekte()
        # Verwaltung mit E-Mail für die interne Benachrichtigung
        Verwaltung.objects.create(firma='Verwaltung AG', email='verwaltung@example.ch')
        u = User.objects.create_user(username='ticket_mieter', password='x')
        m.email = 'mieter@example.ch'; m.benutzer = u; m.save()
        return lg, e, m, v, u

    def test_portal_ticket_sendet_mails(self):
        from django.core import mail
        from tickets.models import SchadenMeldung
        lg, e, m, v, u = self._setup()
        c = Client(); c.force_login(u)
        r = c.post('/mieter/schaden/', {'vertrag_id': str(v.id), 'titel': 'Wasserhahn tropft',
                                        'beschreibung': 'Im Bad', 'raum': 'Bad'})
        self.assertEqual(r.status_code, 302)
        t = SchadenMeldung.objects.filter(titel='Wasserhahn tropft').first()
        self.assertIsNotNone(t)
        self.assertFalse(t.gelesen)
        empf = [addr for mailobj in mail.outbox for addr in mailobj.to]
        self.assertIn('mieter@example.ch', empf)       # Bestätigung an Mieter
        self.assertIn('verwaltung@example.ch', empf)   # Benachrichtigung an Verwaltung

    def test_sidebar_badge_und_gelesen(self):
        from tickets.models import SchadenMeldung
        lg, e, m, v, u = self._setup()
        t = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=e,
                                          titel='Neu X', beschreibung='...', status='neu', gelesen=False)
        team = _team_user()
        c = Client(); c.force_login(team)
        # Badge sichtbar (Titel-Attribut des Zählers)
        body = c.get('/neu/').content.decode()
        self.assertIn('neue Schadenmeldung(en)', body)
        # Öffnen markiert als gelesen -> Badge verschwindet
        c.get(f'/neu/schaeden/{t.id}/')
        t.refresh_from_db()
        self.assertTrue(t.gelesen)
        body2 = c.get('/neu/').content.decode()
        self.assertNotIn('neue Schadenmeldung(en)', body2)


class PortalLoginUrlTests(TestCase):
    def test_zugangsmail_nutzt_produktions_url(self):
        from django.core import mail
        lg, e, m, v = _basis_objekte()
        m.email = 'mieter@example.ch'; m.save()
        team = _team_user()
        c = Client(); c.force_login(team)
        c.post(f'/neu/personen/{m.id}/portal-zugang/')
        self.assertTrue(mail.outbox)
        body = mail.outbox[-1].body
        self.assertIn('https://swissimmo.pythonanywhere.com/portal/login/', body)


class MieterTicketPortalTests(TestCase):
    """Mieter sieht seine Meldungen im Portal, Status, und kann antworten."""

    def _setup(self):
        lg, e, m, v = _basis_objekte()
        Verwaltung.objects.create(firma='Verwaltung AG', email='verwaltung@example.ch')
        u = User.objects.create_user(username='tp_mieter', password='x')
        m.email = 'mieter@example.ch'; m.benutzer = u; m.save()
        from tickets.models import SchadenMeldung
        t = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=e,
                                          gemeldet_von=m, titel='Heizung defekt',
                                          beschreibung='Wird nicht warm', status='in_bearbeitung')
        return lg, e, m, v, u, t

    def test_uebersicht_zeigt_ticket_und_status(self):
        lg, e, m, v, u, t = self._setup()
        c = Client(); c.force_login(u)
        body = c.get('/mieter/tickets/').content.decode()
        self.assertIn('Heizung defekt', body)
        self.assertIn('In Bearbeitung', body)   # Status-Label

    def test_detail_und_antwort_sendet_mail(self):
        from django.core import mail
        from tickets.models import TicketNachricht
        lg, e, m, v, u, t = self._setup()
        c = Client(); c.force_login(u)
        self.assertEqual(c.get(f'/mieter/ticket/{t.id}/').status_code, 200)
        r = c.post(f'/mieter/ticket/{t.id}/nachricht/', {'text': 'Wann kommt der Handwerker?'})
        self.assertEqual(r.status_code, 302)
        n = TicketNachricht.objects.filter(ticket=t, is_von_verwaltung=False).first()
        self.assertIsNotNone(n)
        self.assertEqual(n.nachricht, 'Wann kommt der Handwerker?')
        t.refresh_from_db()
        self.assertFalse(t.gelesen)   # Verwalter-Badge wieder aktiv
        empf = [addr for mailobj in mail.outbox for addr in mailobj.to]
        self.assertIn('verwaltung@example.ch', empf)

    def test_fremdes_ticket_404(self):
        lg, e, m, v, u, t = self._setup()
        from tickets.models import SchadenMeldung
        fremd = Mieter.objects.create(typ='person', nachname='Fremd')
        ft = SchadenMeldung.objects.create(liegenschaft=lg, gemeldet_von=fremd, titel='Fremd', beschreibung='x')
        c = Client(); c.force_login(u)
        self.assertEqual(c.get(f'/mieter/ticket/{ft.id}/').status_code, 404)
        self.assertNotIn('Fremd', c.get('/mieter/tickets/').content.decode())

    def test_interne_notiz_nicht_sichtbar(self):
        from tickets.models import TicketNachricht
        lg, e, m, v, u, t = self._setup()
        TicketNachricht.objects.create(ticket=t, absender_name='Team', typ='chat',
                                       nachricht='INTERNE NOTIZ GEHEIM', is_intern=True)
        c = Client(); c.force_login(u)
        body = c.get(f'/mieter/ticket/{t.id}/').content.decode()
        self.assertNotIn('INTERNE NOTIZ GEHEIM', body)


class LikVertragTests(TestCase):
    """LIK im Mietvertrag: Basis (Dez. 2020) + Stand-Monat durchgängig."""

    def test_lik_context_basis_und_stand(self):
        from core.services.lik import vertrag_lik_context
        lg, e, m, v = _basis_objekte()
        vw = Verwaltung.objects.create(firma='V AG', lik_basis='Dezember 2020',
                                       aktueller_lik_punkte=Decimal('107.1'),
                                       aktueller_lik_stand=date(2024, 8, 1))
        v.basis_lik_punkte = Decimal('106.3'); v.basis_lik_stand = date(2023, 5, 1); v.save()
        ctx = vertrag_lik_context(v, vw)
        self.assertEqual(ctx['lik_basis'], 'Dezember 2020')
        self.assertEqual(ctx['lik_stand_label'], 'Mai 2023')
        self.assertEqual(ctx['lik_pkt'], '106,3')

    def test_lik_context_fallback_auf_verwaltungsstand(self):
        from core.services.lik import vertrag_lik_context
        lg, e, m, v = _basis_objekte()
        vw = Verwaltung.objects.create(firma='V AG', aktueller_lik_stand=date(2025, 3, 1))
        v.basis_lik_stand = None; v.save()
        ctx = vertrag_lik_context(v, vw)
        self.assertEqual(ctx['lik_stand_label'], 'März 2025')   # Fallback

    def test_vertrag_pdf_enthaelt_basis_und_stand(self):
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        lg, e, m, v = _basis_objekte()
        Verwaltung.objects.create(firma='V AG', lik_basis='Dezember 2020', aktueller_lik_stand=date(2024, 8, 1))
        v.basis_lik_punkte = Decimal('107.1'); v.basis_lik_stand = date(2024, 8, 1); v.save()
        pdf = generate_vertrag_pdf_bytes(v)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_assistent_setzt_stand_beim_erstellen(self):
        from rentals.models import Mietvertrag as MV
        from core.services.lik import aktueller_lik_wert
        lg = Liegenschaft.objects.create(strasse='Neu 1', plz='8000', ort='ZH', versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='2 Zi', typ='wohnung')
        m = Mieter.objects.create(typ='person', nachname='Neu')
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': str(e.id), 'mieter_id': str(m.id), 'beginn': '2025-01-01',
            'netto_mietzins': '1500', 'nebenkosten': '200', 'basis_lik_punkte': '107.1'})
        self.assertEqual(r.status_code, 302)
        v = MV.objects.filter(mieter=m).first()
        # ohne Formular-Override wird automatisch der neueste BFS-Stand gesetzt
        auto_stand, _pkt, _basis = aktueller_lik_wert()
        self.assertEqual(v.basis_lik_stand, auto_stand)

    def test_assistent_formular_override_stand(self):
        from rentals.models import Mietvertrag as MV
        lg = Liegenschaft.objects.create(strasse='Neu 2', plz='8000', ort='ZH', versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='2 Zi', typ='wohnung')
        m = Mieter.objects.create(typ='person', nachname='Ovr')
        team = _team_user()
        c = Client(); c.force_login(team)
        c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': str(e.id), 'mieter_id': str(m.id), 'beginn': '2025-01-01',
            'netto_mietzins': '1500', 'nebenkosten': '200', 'basis_lik_punkte': '106.3',
            'basis_lik_stand': '2023-05'})
        v = MV.objects.filter(mieter=m).first()
        self.assertEqual(v.basis_lik_stand, date(2023, 5, 1))

    def test_aktueller_lik_wert_aus_tabelle(self):
        from core.services.lik import aktueller_lik_wert
        # live=False → deterministisch aus der eingebauten BFS-Tabelle
        stand, pkt, basis = aktueller_lik_wert(live=False)
        self.assertEqual(basis, 'Dezember 2020')
        self.assertEqual(stand, date(2026, 6, 1))       # neuester Monat im Bild
        self.assertEqual(pkt, Decimal('108.3'))

    def test_live_parser_extrahiert_monat_und_wert(self):
        # Simuliert die HEV-Tabelle: Live-Parser muss Monat UND Wert lesen
        from core.services import lik as liks
        html = ('<html>Dezember 2020 = 100'
                '<table><tr><td>2026</td>'
                '<td>106.9</td><td>107.6</td><td>107.8</td><td>108.1</td>'
                '<td>108.3</td><td>108.3</td></tr>'
                '<tr><td>2025</td><td>106.8</td></tr></table></html>')
        orig = liks.requests.get if hasattr(liks, 'requests') else None
        import types
        class _Resp:
            text = html
        import core.services.lik as _m
        import requests as _rq
        _saved = _rq.get
        _rq.get = lambda *a, **k: _Resp()
        try:
            res = _m._fetch_live_lik()
        finally:
            _rq.get = _saved
        self.assertIsNotNone(res)
        self.assertEqual(res[0], date(2026, 6, 1))
        self.assertEqual(res[1], Decimal('108.3'))


class AbonnementTests(TestCase):
    def test_abo_seite_zeigt_drei_plaene(self):
        Einheit.objects.create(liegenschaft=Liegenschaft.objects.create(
            strasse='A', plz='1', ort='X', versicherungswert=Decimal('1')),
            bezeichnung='W1', typ='wohnung')
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.get('/neu/abonnement/')
        self.assertEqual(r.status_code, 200)
        for name in ('Start', 'Pro', 'Premium'):
            self.assertContains(r, name)

    def test_plan_waehlen_speichert(self):
        Verwaltung.objects.create(firma='V AG')
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.post('/neu/abonnement/', {'plan': 'premium'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Verwaltung.objects.first().abo_plan, 'premium')

    def test_jaehrlich_rabatt(self):
        # 100 Einheiten Pro: monatlich 190, jährlich -15 % -> ~161/Mt
        lg = Liegenschaft.objects.create(strasse='B', plz='1', ort='X', versicherungswert=Decimal('1'))
        for i in range(100):
            Einheit.objects.create(liegenschaft=lg, bezeichnung=f'W{i}', typ='wohnung')
        Verwaltung.objects.create(firma='V AG')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/abonnement/').content.decode()
        self.assertIn('CHF 190', body)                 # Pro monatlich (1.90 * 100)
        body_j = c.post('/neu/abonnement/', {'plan': 'pro', 'jaehrlich': 'on'}, follow=True).content.decode()
        self.assertIn('CHF 162', body_j)               # 190 * 0.85 gerundet


class BackupCommandTests(TestCase):
    def test_backup_db_sqlite(self):
        import io, sqlite3, tempfile
        from pathlib import Path
        from django.test import override_settings
        from django.core.management import call_command
        tmp = Path(tempfile.mkdtemp())
        dbfile = tmp / 'db.sqlite3'
        sqlite3.connect(str(dbfile)).close()   # leere echte DB-Datei
        with override_settings(BASE_DIR=tmp, DATABASES={'default': {
                'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(dbfile)}}):
            out = io.StringIO()
            call_command('backup_db', stdout=out)
            self.assertIn('Backup erstellt', out.getvalue())
            self.assertTrue(list((tmp / 'backups').glob('db-*.sqlite3')))


class SteuerauszugTests(TestCase):
    """Eigentümer-Steuerauszug: Erträge − Ausgaben − AfA je Liegenschaft."""

    def _setup(self):
        from finance.models import Zahlungseingang, KreditorenRechnung, Anlage, Abschreibung
        from crm.models import Handwerker  # noqa
        lg, e, m, v = _basis_objekte()
        md = Mandant.objects.create(firma_oder_name='Eig AG')
        lg.mandant = md; lg.save()
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

    def test_fremder_mandant_kein_zugriff(self):
        md, lg, u = self._setup()
        # Anderer Eigentümer sieht die Zahlen nicht in seinem Auszug
        md2 = Mandant.objects.create(firma_oder_name='Andere AG')
        u2 = User.objects.create_user(username='eig_andere', password='x'); md2.benutzer = u2; md2.save()
        from core.services.steuerauszug import steuerauszug_daten
        d = steuerauszug_daten(md2, 2024)
        self.assertEqual(d['total']['ertrag'], Decimal('0'))
