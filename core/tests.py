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


class EigentuemerZugangTests(TestCase):
    def _mandant(self):
        md = Mandant.objects.create(firma_oder_name='Eig AG', email='eig@example.ch')
        return md

    def test_zugang_erstellen_und_mail(self):
        from django.core import mail
        md = self._mandant()
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.post(f'/neu/mandate/{md.id}/portal-zugang/')
        self.assertEqual(r.status_code, 302)
        md.refresh_from_db()
        self.assertIsNotNone(md.benutzer_id)
        self.assertTrue(md.benutzer.is_active)
        empf = [a for mo in mail.outbox for a in mo.to]
        self.assertIn('eig@example.ch', empf)
        # Login-Link zeigt aufs Portal
        self.assertIn('/portal/login/', mail.outbox[-1].body)

    def test_login_und_routing_ins_portal(self):
        md = self._mandant()
        lg = Liegenschaft.objects.create(strasse='A', plz='1', ort='X', versicherungswert=Decimal('1'))
        lg.mandant = md; lg.save()
        team = _team_user()
        c = Client(); c.force_login(team)
        c.post(f'/neu/mandate/{md.id}/portal-zugang/')
        md.refresh_from_db()
        # Der neue Eigentümer-Login landet nach /nach-login/ auf /portal/
        oc = Client(); oc.force_login(md.benutzer)
        r = oc.get('/nach-login/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.endswith('/portal/'))
        self.assertEqual(oc.get('/portal/').status_code, 200)

    def test_zugang_entfernen(self):
        md = self._mandant()
        team = _team_user()
        c = Client(); c.force_login(team)
        c.post(f'/neu/mandate/{md.id}/portal-zugang/')
        md.refresh_from_db()
        self.assertIsNotNone(md.benutzer_id)
        c.post(f'/neu/mandate/{md.id}/portal-zugang/', {'aktion': 'entfernen'})
        md.refresh_from_db()
        self.assertIsNone(md.benutzer_id)

    def test_button_in_mandatform(self):
        md = self._mandant()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get(f'/neu/mandate/{md.id}/bearbeiten/').content.decode()
        self.assertIn('Eigentümer-Portal-Zugang', body)
        self.assertIn(f'/neu/mandate/{md.id}/portal-zugang/', body)


class EigentuemerReportVersandTests(TestCase):
    def test_command_sendet_mit_anhaengen(self):
        from django.core import mail
        from django.core.management import call_command
        import io
        lg, e, m, v = _basis_objekte()
        md = Mandant.objects.create(firma_oder_name='Eig AG', email='eig@example.ch')
        lg.mandant = md; lg.save()
        out = io.StringIO()
        call_command('send_eigentuemer_reports', '--jahr', '2024', stdout=out)
        self.assertIn('versendet', out.getvalue())
        self.assertTrue(mail.outbox)
        msg = mail.outbox[-1]
        self.assertIn('eig@example.ch', msg.to)
        # zwei PDF-Anhänge (Report + Steuerauszug)
        self.assertEqual(len(msg.attachments), 2)
        namen = [a[0] for a in msg.attachments]
        self.assertTrue(any('Portfolio-Report' in n for n in namen))
        self.assertTrue(any('Steuerauszug' in n for n in namen))

    def test_dry_run_sendet_nicht(self):
        from django.core import mail
        from django.core.management import call_command
        import io
        Mandant.objects.create(firma_oder_name='Eig AG', email='eig@example.ch')
        call_command('send_eigentuemer_reports', '--dry-run', stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 0)

    def test_ohne_email_uebersprungen(self):
        from django.core import mail
        from django.core.management import call_command
        import io
        Mandant.objects.create(firma_oder_name='Ohne Mail')  # keine E-Mail
        call_command('send_eigentuemer_reports', stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 0)


class SerienbriefMitmieterTests(TestCase):
    def _paar(self):
        lg = Liegenschaft.objects.create(strasse='Paar 9', plz='3000', ort='Bern', versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='4.5 Zi', typ='wohnung')
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

    def test_zweitperson_sieht_brief_im_portal(self):
        from django.contrib.auth.models import User
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


class QrrReferenzTests(TestCase):
    def test_referenz_27_stellig_mod10(self):
        from core.utils.qr_code import qrr_referenz
        raw, fmt = qrr_referenz(5, 42)
        self.assertEqual(len(raw), 27)
        self.assertTrue(raw.isdigit())
        # Prüfziffer mit derselben Mod-10-rekursiv-Tabelle verifizieren
        tab = [0, 9, 4, 6, 8, 2, 7, 1, 3, 5]
        u = 0
        for z in raw[:26]:
            u = tab[(u + int(z)) % 10]
        self.assertEqual(int(raw[26]), (10 - u) % 10)

    def test_rechnung_setzt_referenz_automatisch(self):
        from finance.models import DebitorenRechnung
        _lg, _e, _m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(vertrag=v, titel='Test', betrag=Decimal('100'))
        r.refresh_from_db()
        self.assertEqual(len(r.qr_referenz), 27)


class SollstellungTests(TestCase):
    def test_erstellt_und_idempotent(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _basis_objekte()  # Vertrag ab 2024-01-01, 1500+200
        n1 = run_sollstellung(2024, 3)
        self.assertEqual(n1, 1)
        r = DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')
        self.assertEqual(r.betrag, Decimal('1700.00'))
        # zweiter Lauf erzeugt nichts Neues
        n2 = run_sollstellung(2024, 3)
        self.assertEqual(n2, 0)
        self.assertEqual(DebitorenRechnung.objects.filter(titel='Miete & NK 03/2024').count(), 1)

    def test_pro_rata_bei_einzug_mitte_monat(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        lg = Liegenschaft.objects.create(strasse='PR 1', plz='8000', ort='ZH', versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='2 Zi', typ='wohnung')
        m = Mieter.objects.create(typ='person', nachname='Prorata')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 3, 16),
                                   netto_mietzins=Decimal('3100'), nebenkosten=Decimal('0'), status='aktiv')
        run_sollstellung(2024, 3)   # März = 31 Tage, ab 16. -> 16/31
        r = DebitorenRechnung.objects.get(vertrag__mieter=m)
        self.assertEqual(r.betrag, Decimal('1600.00'))   # 3100 * 16/31 = 1600.00


class CamtImportTests(TestCase):
    def _camt(self, ref, betrag='1700.00', acct_ref='BANKTX1'):
        return (
            '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt><Ntry>'
            '<CdtDbtInd>CRDT</CdtDbtInd>'
            f'<Amt Ccy="CHF">{betrag}</Amt>'
            '<BookgDt><Dt>2024-03-05</Dt></BookgDt>'
            '<NtryDtls><TxDtls>'
            f'<Refs><AcctSvcrRef>{acct_ref}</AcctSvcrRef></Refs>'
            f'<RmtInf><Strd><CdtrRefInf><Ref>{ref}</Ref></CdtrRefInf></Strd></RmtInf>'
            '</TxDtls></NtryDtls>'
            '</Ntry></Stmt></BkToCstmrStmt></Document>'
        ).encode('utf-8')

    def test_zahlung_wird_per_referenz_verbucht(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung, Zahlungseingang
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        r = DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')
        team = _team_user()
        c = Client(); c.force_login(team)
        f = SimpleUploadedFile('camt.xml', self._camt(r.qr_referenz), content_type='application/xml')
        resp = c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        self.assertEqual(resp.status_code, 302)
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 1)

    def test_duplikat_wird_nicht_doppelt_verbucht(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung, Zahlungseingang
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        r = DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')
        team = _team_user()
        c = Client(); c.force_login(team)
        for _ in range(2):
            f = SimpleUploadedFile('camt.xml', self._camt(r.qr_referenz, acct_ref='SAMEREF'),
                                   content_type='application/xml')
            c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        # trotz zweifachem Import nur EINE Zahlung (Duplikatschutz über Bank-Referenz)
        self.assertEqual(Zahlungseingang.objects.filter(bank_referenz='SAMEREF').count(), 1)


class MahnlaufTests(TestCase):
    def test_verzugszins_art104(self):
        from core.services.automation import verzugszins
        # 12'000 × 5% × 360/360 = 600.00
        self.assertEqual(verzugszins(Decimal('12000'), 360), Decimal('600.00'))
        # 10'000 × 5% × 90/360 = 125.00
        self.assertEqual(verzugszins(Decimal('10000'), 90), Decimal('125.00'))
        self.assertEqual(verzugszins(Decimal('1000'), 0), Decimal('0.00'))

    def test_mahnstufe_nach_tagen(self):
        from core.services.automation import _stufe_fuer_tage
        self.assertIsNone(_stufe_fuer_tage(13))
        self.assertEqual(_stufe_fuer_tage(14), 1)
        self.assertEqual(_stufe_fuer_tage(30), 2)
        self.assertEqual(_stufe_fuer_tage(60), 3)

    def _ueberfaellig(self, tage):
        from django.utils import timezone
        from finance.models import DebitorenRechnung
        _lg, _e, _m, v = _basis_objekte()
        faellig = timezone.localdate() - timedelta(days=tage)
        return DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=v.einheit.liegenschaft, titel='Miete 01',
            betrag=Decimal('1700'), datum=faellig, faellig_am=faellig, status='offen')

    def test_mahnung_und_gebuehr(self):
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung, DebitorenRechnung
        r = self._ueberfaellig(40)   # -> Stufe 2, Gebühr 20
        res = run_mahnlauf(send_email=False)
        self.assertEqual(res['gemahnt'], 1)
        m = Mahnung.objects.get(debitoren_rechnung=r)
        self.assertEqual(m.stufe, 2)
        self.assertEqual(m.gebuehr, Decimal('20.00'))
        # Mahngebühr als eigener Debitor
        self.assertTrue(DebitorenRechnung.objects.filter(titel__icontains='Mahngebühr').exists())

    def test_idempotent_gleiche_stufe(self):
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung
        self._ueberfaellig(40)
        run_mahnlauf(send_email=False)
        res2 = run_mahnlauf(send_email=False)
        self.assertEqual(res2['gemahnt'], 0)
        self.assertEqual(Mahnung.objects.count(), 1)

    def test_mit_verzugszins(self):
        from core.services.automation import run_mahnlauf
        from finance.models import DebitorenRechnung
        self._ueberfaellig(90)   # 90 Tage überfällig -> Stufe 3
        res = run_mahnlauf(send_email=False, mit_zins=True)
        self.assertGreater(res['zins'], Decimal('0.00'))
        self.assertTrue(DebitorenRechnung.objects.filter(titel__icontains='Verzugszins').exists())


class NkAbrechnungVersandTests(TestCase):
    def _periode(self):
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg
        lg = Liegenschaft.objects.create(strasse='NK 1', plz='8000', ort='ZH', versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='3.5 Zi', typ='wohnung', flaeche_m2=Decimal('80'))
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
        from django.contrib.auth.models import User
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
    def test_nachzahlung_wird_offene_qr_rechnung_im_portal(self):
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg, DebitorenRechnung
        from django.contrib.auth.models import User
        _seed_konten()
        vw = Verwaltung.objects.create(firma='V AG', strasse='W 1', plz='8000', ort='ZH',
                                       iban='CH9300762011623852957')
        lg = Liegenschaft.objects.create(strasse='NKQ 1', plz='8000', ort='ZH', versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='3.5 Zi', typ='wohnung', flaeche_m2=Decimal('80'))
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


class KautionRueckzahlungTests(TestCase):
    def test_rueckzahlung_mit_einbehalt(self):
        _lg, _e, _m, v = _basis_objekte()   # kautions_betrag 4500
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.post(f'/neu/vertraege/{v.id}/kaution/', {
            'aktion': 'rueckzahlung', 'abzug_betrag': '500', 'abzug_grund': 'Reinigung',
            'zurueckbezahlt_am': '2025-01-31'})
        self.assertEqual(r.status_code, 302)
        v.refresh_from_db()
        self.assertEqual(v.kautions_abzug_betrag, Decimal('500'))
        self.assertEqual(v.kautions_rueckzahlung_betrag, Decimal('4000'))   # 4500 - 500
        self.assertEqual(v.kautions_status, 'zurueckbezahlt')

    def test_einzahlung_setzt_status(self):
        _lg, _e, _m, v = _basis_objekte()
        team = _team_user()
        c = Client(); c.force_login(team)
        c.post(f'/neu/vertraege/{v.id}/kaution/', {'aktion': 'einzahlung', 'einbezahlt_am': '2024-01-05'})
        v.refresh_from_db()
        self.assertEqual(v.kautions_status, 'einbezahlt')
        self.assertIsNotNone(v.kautions_einbezahlt_am)


class MwstEstvTests(TestCase):
    def test_effektiv_zahllast(self):
        from core.services.mwst_estv import berechne_estv
        d = berechne_estv(umsatz_steuerbar=Decimal('10000'), umsatzsteuer=Decimal('810'),
                          vorsteuer_material=Decimal('100'), vorsteuer_invest=Decimal('50'))
        self.assertEqual(d['z479'], Decimal('150.00'))   # Total Vorsteuer
        self.assertEqual(d['z500'], Decimal('660.00'))   # 810 - 150 Zahllast
        self.assertEqual(d['z510'], Decimal('0.00'))

    def test_effektiv_guthaben(self):
        from core.services.mwst_estv import berechne_estv
        d = berechne_estv(umsatz_steuerbar=Decimal('1000'), umsatzsteuer=Decimal('100'),
                          vorsteuer_material=Decimal('300'), vorsteuer_invest=Decimal('0'))
        self.assertEqual(d['z500'], Decimal('0.00'))
        self.assertEqual(d['z510'], Decimal('200.00'))   # Guthaben

    def test_saldosteuersatz(self):
        from core.services.mwst_estv import berechne_estv
        d = berechne_estv(umsatz_steuerbar=Decimal('10000'), umsatzsteuer=Decimal('0'),
                          vorsteuer_material=Decimal('0'), vorsteuer_invest=Decimal('0'),
                          methode='saldo', saldosteuersatz=Decimal('5'))
        self.assertEqual(d['z500'], Decimal('500.00'))   # 10000 * 5%


class MieterwechselCockpitTests(TestCase):
    def _kuendigung(self, tage_bis_ende=40):
        from rentals.models import Kuendigung
        lg, e, m, v = _basis_objekte()
        ende = date.today() + timedelta(days=tage_bis_ende)
        k = Kuendigung.objects.create(vertrag=v, absender='mieter', eingang_datum=date.today(),
                                      per_datum=ende, berechneter_termin=ende, status='erfasst')
        return lg, e, m, v, k, ende

    def test_gekuendigt_erscheint(self):
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.get('/neu/mieterwechsel/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Teststrasse 1')
        self.assertContains(r, 'Gekündigt')

    def test_nachmietervertrag_erkannt(self):
        lg, e, m, v, k, ende = self._kuendigung()
        # Nachmieter-Vertrag auf derselben Einheit ab Ende
        nm = Mieter.objects.create(typ='person', nachname='Neu')
        Mietvertrag.objects.create(mieter=nm, einheit=e, beginn=ende + timedelta(days=1),
                                   netto_mietzins=Decimal('1600'), nebenkosten=Decimal('200'), status='entwurf')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('Nachmieter-Vertrag', body)
        self.assertIn('Neu', body)

    def test_vollzogene_kuendigung_nicht_gelistet(self):
        lg, e, m, v, k, ende = self._kuendigung()
        k.status = 'vollzogen'; k.save()
        team = _team_user()
        c = Client(); c.force_login(team)
        self.assertContains(c.get('/neu/mieterwechsel/'), 'Kein laufender Mieterwechsel')

    def test_ruecknahme_aktion_verlinkt_vorgetypt(self):
        """Cockpit verlinkt die Rücknahme direkt auf den vorgetypten Abnahme-Flow."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug', body)
        self.assertIn('Rücknahme starten', body)

    def test_uebergabe_aktion_bei_nachmieter(self):
        """Sobald ein Nachmietervertrag existiert, verlinkt das Cockpit die Übergabe."""
        lg, e, m, v, k, ende = self._kuendigung()
        nm = Mieter.objects.create(typ='person', nachname='Neu')
        nv = Mietvertrag.objects.create(mieter=nm, einheit=e, beginn=ende + timedelta(days=1),
                                        netto_mietzins=Decimal('1600'), nebenkosten=Decimal('200'),
                                        status='entwurf')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn(f'/neu/vertraege/{nv.id}/abnahme/neu/?typ=einzug', body)
        self.assertIn('Übergabe starten', body)

    def test_abnahme_form_uebernimmt_typ_aus_query(self):
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug').content.decode()
        self.assertIn('<option value="auszug" selected>', body)

    def test_auto_pendenz_ruecknahme(self):
        """generate_auto_pendenzen legt eine Wohnungsrücknahme-Pendenz je Kündigung an."""
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        lg, e, m, v, k, ende = self._kuendigung(tage_bis_ende=40)
        generate_auto_pendenzen(horizont_tage=90)
        p = Pendenz.objects.filter(quelle=f'auto:ruecknahme:{k.id}').first()
        self.assertIsNotNone(p)
        self.assertIn('Wohnungsrücknahme planen', p.titel)
        self.assertEqual(p.faellig_am, ende)
        # Idempotent — kein zweiter Eintrag
        generate_auto_pendenzen(horizont_tage=90)
        self.assertEqual(Pendenz.objects.filter(quelle=f'auto:ruecknahme:{k.id}').count(), 1)

    def test_auto_pendenz_ruecknahme_entfaellt_nach_abnahme(self):
        """Ist die Rücknahme bereits protokolliert, wird keine Pendenz erzeugt."""
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        from rentals.models import Abnahmeprotokoll
        lg, e, m, v, k, ende = self._kuendigung(tage_bis_ende=40)
        Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        generate_auto_pendenzen(horizont_tage=90)
        self.assertFalse(Pendenz.objects.filter(quelle=f'auto:ruecknahme:{k.id}').exists())

    def test_schlussabrechnung_nach_ruecknahme(self):
        """Nach der Rücknahme zeigt das Cockpit die Schlussabrechnung (Kaution offen),
        vorbefüllt aus dem Rücknahme-Protokoll."""
        from rentals.models import Abnahmeprotokoll
        lg, e, m, v, k, ende = self._kuendigung()   # v hat kautions_betrag 4500, Status 'erwartet'
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('Schlussabrechnung', body)
        self.assertIn(f'/neu/vertraege/{v.id}/schlussabrechnung/?abnahme={prot.id}', body)

    def test_offene_forderung_erzwingt_schlussabrechnung(self):
        """Auch ohne Kaution: offene Debitoren nach Rücknahme → Schlussabrechnung."""
        from rentals.models import Abnahmeprotokoll
        from finance.models import DebitorenRechnung
        lg, e, m, v, k, ende = self._kuendigung()
        v.kautions_betrag = Decimal('0'); v.save()   # keine Kaution
        Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                         titel='Restmiete', betrag=Decimal('900'),
                                         faellig_am=date.today(), status='offen')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('Schlussabrechnung', body)

    def test_abgerechnet_kein_schlussabrechnung_button(self):
        """Kaution zurückbezahlt und keine offenen Forderungen → keine Schlussabrechnung."""
        from rentals.models import Abnahmeprotokoll
        lg, e, m, v, k, ende = self._kuendigung()
        v.kautions_einbezahlt_am = date(2024, 1, 5)
        v.kautions_zurueckbezahlt_am = date.today()
        v.save()
        Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertNotIn('/schlussabrechnung/', body)

    def test_objekt_ausschreiben_button_und_verfuegbarkeit(self):
        """Cockpit bietet 'Objekt ausschreiben'; POST setzt Ausschreibung + Verfügbarkeit."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn(f'/neu/objekte/{e.id}/ausschreiben/', body)
        self.assertIn('Objekt ausschreiben', body)
        # Ausschreiben
        r = c.post(f'/neu/objekte/{e.id}/ausschreiben/', {'ziel': 'an', 'weiter': '/neu/mieterwechsel/'})
        self.assertEqual(r.status_code, 302)
        e.refresh_from_db()
        self.assertTrue(e.zur_ausschreibung)
        self.assertEqual(e.verfuegbar_ab, ende)   # aus der Kündigung übernommen

    def test_vermarktungsliste_zeigt_ausgeschriebenes_objekt(self):
        lg, e, m, v, k, ende = self._kuendigung()
        e.zur_ausschreibung = True
        e.verfuegbar_ab = ende
        e.save()
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.get('/neu/vermarktung/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Teststrasse 1')
        self.assertContains(r, '3.5 Zi')

    def test_ausschreibung_beenden(self):
        lg, e, m, v, k, ende = self._kuendigung()
        e.zur_ausschreibung = True; e.save()
        team = _team_user()
        c = Client(); c.force_login(team)
        c.post(f'/neu/objekte/{e.id}/ausschreiben/', {'ziel': 'aus', 'weiter': '/neu/vermarktung/'})
        e.refresh_from_db()
        self.assertFalse(e.zur_ausschreibung)
        # Objekt ist nicht mehr in der Vermarktungsliste
        self.assertContains(c.get('/neu/vermarktung/'), 'Kein Objekt in der Vermarktung')

    def test_cockpit_oeffnet_schritte_als_modal(self):
        """Cockpit-Aktionen öffnen die Schritte im Modal (fwModalOpen), nicht per Seitenwechsel."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('fwModalOpen(this', body)
        self.assertIn('id="fwModal"', body)
        self.assertIn("e.data.fwModal === 'done'", body)

    def test_abnahme_embed_ohne_sidebar(self):
        """Embed-Formular rendert ohne Sidebar (base_embed) für das Modal."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        voll = c.get(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug').content.decode()
        embed = c.get(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug&embed=1').content.decode()
        self.assertIn('fwSidebar', voll)          # Vollseite hat Sidebar
        self.assertNotIn('fwSidebar', embed)       # Embed hat keine Sidebar
        self.assertIn('name="embed" value="1"', embed)

    def test_abnahme_embed_post_signalisiert_done(self):
        """POST im Embed-Modus liefert die Modal-Done-Seite (postMessage an Cockpit)."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.post(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug&embed=1', {
            'embed': '1', 'typ': 'auszug', 'datum': date.today().isoformat(),
            'allgemein_zustand': 'gut',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn("fwModal: 'done'", r.content.decode())
        self.assertTrue(v.abnahmen.filter(typ='auszug').exists())

    def test_ausschreiben_form_im_modal(self):
        """'Objekt ausschreiben' öffnet ein Formular im Modal (GET embed), keine stille POST."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        # Cockpit verlinkt per Modal
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn(f"fwModalOpen(this,'Objekt ausschreiben')", body)
        # GET embed rendert das Formular ohne Sidebar, Verfügbarkeit vorbelegt aus Kündigung
        form = c.get(f'/neu/objekte/{e.id}/ausschreiben/?embed=1').content.decode()
        self.assertNotIn('fwSidebar', form)
        self.assertIn('name="verfuegbar_ab"', form)
        self.assertIn(ende.isoformat(), form)

    def test_ausschreiben_embed_post_signalisiert_done(self):
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.post(f'/neu/objekte/{e.id}/ausschreiben/', {
            'embed': '1', 'ziel': 'an', 'verfuegbar_ab': ende.isoformat(),
            'notiz': 'Renoviert 2024',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn("fwModal: 'done'", r.content.decode())
        e.refresh_from_db()
        self.assertTrue(e.zur_ausschreibung)
        self.assertEqual(e.verfuegbar_ab, ende)
        self.assertEqual(e.ausschreibung_notiz, 'Renoviert 2024')

    def test_navigations_schritte_oeffnen_im_modal(self):
        """Bewerbungen / Vertrag erstellen laufen ebenfalls über das Modal."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn("fwModalOpen(this,'Bewerbungen')", body)
        self.assertIn("fwModalOpen(this,'Vertrag erstellen',true)", body)   # breit

    def test_cockpit_vertrag_erstellen_mit_einheit_vorwahl(self):
        """'Vertrag erstellen' übergibt die konkrete Einheit an den Wizard."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn(f'/neu/vertraege/neu/?einheit={e.id}', body)

    def test_wizard_vorwahl_nur_eine_einheit(self):
        """Mit ?einheit=<id> zeigt der Wizard nur diese Liegenschaft/Einheit und
        setzt die Vorwahl — auch wenn der alte Vertrag noch aktiv ist."""
        lg, e, m, v, k, ende = self._kuendigung()   # v ist aktiv auf e
        # zweite Liegenschaft, die NICHT erscheinen darf
        lg2 = Liegenschaft.objects.create(strasse='Andere 9', plz='3000', ort='Bern',
                                          versicherungswert=Decimal('500000'))
        Einheit.objects.create(liegenschaft=lg2, bezeichnung='2 Zi', typ='wohnung',
                               nettomiete_aktuell=Decimal('900'))
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.get(f'/neu/vertraege/neu/?einheit={e.id}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['vorwahl_einheit'], e.id)
        lgs = r.context['liegenschaften']   # nur die Wizard-Daten zählen
        self.assertEqual(len(lgs), 1)
        self.assertEqual(lgs[0]['id'], lg.id)
        self.assertEqual([o['id'] for o in lgs[0]['objekte']], [e.id])

    def test_embed_ueberlebt_redirect_via_iframe_kontext(self):
        """base.html blendet den Chrome auch ohne ?embed=1 aus, sobald im iframe
        geladen (window.self !== window.top) — so bleiben mehrstufige Flows
        (Wizard-Ende, Bewerbung→Vertrag) im Popup chrome-frei."""
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('window.self !== window.top', body)
        self.assertIn("classList.add('_embed')", body)


class TagesstartCockpitTests(TestCase):
    def test_heute_zu_tun_zeigt_dringende_pendenz_mit_popup(self):
        """Fällige Pendenzen erscheinen im 'Heute zu tun' und öffnen im Popup."""
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        Pendenz.objects.create(titel='Rücknahme vorbereiten', kategorie='vertrag',
                               quelle='auto:ruecknahme:1', vertrag=v, liegenschaft=lg,
                               faellig_am=date.today())
        team = _team_user(); c = Client(); c.force_login(team)
        r = c.get('/neu/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['heute_todo']), 1)
        body = r.content.decode()
        self.assertIn('Heute zu tun', body)
        self.assertIn(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug', body)
        self.assertIn('id="fwModal"', body)

    def test_ferne_pendenz_nicht_im_heute(self):
        """Pendenzen weit in der Zukunft (>14 Tage) erscheinen nicht im 'Heute zu tun'."""
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        Pendenz.objects.create(titel='Weit weg', kategorie='aufgabe', vertrag=v,
                               faellig_am=date.today() + timedelta(days=40))
        team = _team_user(); c = Client(); c.force_login(team)
        r = c.get('/neu/')
        self.assertEqual(len(r.context['heute_todo']), 0)


class KuendigungModalTests(TestCase):
    def test_vertragsliste_zeigt_kuendigen_aktion(self):
        lg, e, m, v = _basis_objekte()   # v ist aktiv
        team = _team_user(); c = Client(); c.force_login(team)
        body = c.get('/neu/vertraege/').content.decode()
        self.assertIn(f'/neu/vertraege/{v.id}/kuendigen/', body)
        self.assertIn("fwModalOpen(this,'Kündigung erfassen')", body)

    def test_kuendigung_form_live_pruefung(self):
        """Das Kündigungsformular enthält die mietrechtliche Live-Prüfung."""
        lg, e, m, v = _basis_objekte()   # Wohnung → geschützt
        team = _team_user(); c = Client(); c.force_login(team)
        body = c.get(f'/neu/vertraege/{v.id}/kuendigen/').content.decode()
        self.assertIn('function kuendigungCheck', body)
        self.assertIn('id="k-warn"', body)
        self.assertIn('IST_GESCHUETZT = true', body)
        self.assertIn('Art. 266l OR', body)

    def test_kuendigung_embed_schliesst_und_legt_pendenzen_an(self):
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        team = _team_user(); c = Client(); c.force_login(team)
        r = c.post(f'/neu/vertraege/{v.id}/kuendigen/', {
            'embed': '1', 'absender': 'mieter', 'eingang_datum': date.today().isoformat(),
            'zustellung': 'einschreiben'})
        self.assertEqual(r.status_code, 200)
        self.assertIn("fwModal: 'done'", r.content.decode())
        v.refresh_from_db()
        self.assertEqual(v.status, 'gekuendigt')
        self.assertTrue(Pendenz.objects.filter(vertrag=v, erledigt=False).exists())


class PendenzAktionTests(TestCase):
    def test_ruecknahme_pendenz_verlinkt_abnahme(self):
        """Eine 'Wohnungsrücknahme planen'-Pendenz verlinkt direkt in die Rücknahme (Popup)."""
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        Pendenz.objects.create(titel='Wohnungsrücknahme planen: Muster', kategorie='vertrag',
                               quelle=f'auto:ruecknahme:1', vertrag=v, faellig_am=date.today())
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/pendenzen/').content.decode()
        self.assertIn(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug', body)
        self.assertIn('Rücknahme starten', body)
        self.assertIn('id="fwModal"', body)   # öffnet im Popup

    def test_vertrag_pendenz_verlinkt_vertrag(self):
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        Pendenz.objects.create(titel='Vertragsende Muster', kategorie='vertrag',
                               quelle=f'auto:vertragsende:{v.id}', vertrag=v, faellig_am=date.today())
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/pendenzen/').content.decode()
        self.assertIn(f"fwModalOpen(this,'Vertragsende Muster',true)", body)
        self.assertIn('Vertrag öffnen', body)

    def test_freie_pendenz_ohne_link(self):
        """Eine Pendenz ohne Vertrag/Liegenschaft bleibt ein einfacher Eintrag."""
        from core.models import Pendenz
        Pendenz.objects.create(titel='Büro aufräumen', kategorie='aufgabe', faellig_am=date.today())
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/pendenzen/').content.decode()
        self.assertIn('Büro aufräumen', body)
        self.assertNotIn("fwModalOpen(this,'Büro aufräumen'", body)

    def test_pendenzen_nach_vertrag_gruppiert(self):
        """Auszugs-Pendenzen mehrerer Kündigungen erscheinen unter getrennten
        Überschriften (Objekt), nicht vermischt."""
        from core.models import Pendenz
        lg = Liegenschaft.objects.create(strasse='Bahnhofstrasse 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e1 = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg A', typ='wohnung')
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg B', typ='wohnung')
        m1 = Mieter.objects.create(typ='person', nachname='Alpha')
        m2 = Mieter.objects.create(typ='person', nachname='Beta')
        v1 = Mietvertrag.objects.create(mieter=m1, einheit=e1, beginn=date(2024, 1, 1),
                                        netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                                        status='gekuendigt')
        v2 = Mietvertrag.objects.create(mieter=m2, einheit=e2, beginn=date(2024, 1, 1),
                                        netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                                        status='gekuendigt')
        for v in (v1, v2):
            Pendenz.objects.create(titel='Wohnungsabnahme durchführen', kategorie='aufgabe',
                                   vertrag=v, liegenschaft=lg, faellig_am=date.today())
            Pendenz.objects.create(titel='Kaution abrechnen / freigeben', kategorie='finanzen',
                                   vertrag=v, liegenschaft=lg, faellig_am=date.today())
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.get('/neu/pendenzen/')
        gruppen = r.context['gruppen']
        # Zwei Vertragsgruppen, je 2 Pendenzen
        vertragsgruppen = [g for g in gruppen if g['titel'].startswith('Bahnhofstrasse 1')]
        self.assertEqual(len(vertragsgruppen), 2)
        for g in vertragsgruppen:
            self.assertEqual(len(g['pendenzen']), 2)
        body = r.content.decode()
        self.assertIn('Whg A', body)
        self.assertIn('Whg B', body)

    def test_abnahme_hakt_pendenz_ab(self):
        """Rücknahme-Protokoll erledigt die 'Wohnungsabnahme'-Pendenz automatisch."""
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        p = Pendenz.objects.create(titel='Wohnungsabnahme durchführen (Protokoll)', kategorie='aufgabe',
                                   vertrag=v, liegenschaft=lg, faellig_am=date.today())
        team = _team_user(); c = Client(); c.force_login(team)
        c.post(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug', {
            'typ': 'auszug', 'datum': date.today().isoformat(), 'allgemein_zustand': 'gut'})
        p.refresh_from_db()
        self.assertTrue(p.erledigt)

    def test_schlussabrechnung_hakt_pendenzen_ab(self):
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        p1 = Pendenz.objects.create(titel='Schlussabrechnung erstellen', vertrag=v,
                                    kategorie='finanzen', faellig_am=date.today())
        p2 = Pendenz.objects.create(titel='Kaution abrechnen / freigeben', vertrag=v,
                                    kategorie='finanzen', faellig_am=date.today())
        team = _team_user(); c = Client(); c.force_login(team)
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'aktion': 'buchen', 'auszug_datum': date.today().isoformat()})
        p1.refresh_from_db(); p2.refresh_from_db()
        self.assertTrue(p1.erledigt)
        self.assertTrue(p2.erledigt)

    def test_ausschreiben_hakt_nachmieter_pendenz_ab(self):
        from core.models import Pendenz
        from rentals.models import Kuendigung
        lg, e, m, v = _basis_objekte()
        Kuendigung.objects.create(vertrag=v, absender='mieter', eingang_datum=date.today(),
                                  per_datum=date.today() + timedelta(days=30),
                                  berechneter_termin=date.today() + timedelta(days=30), status='erfasst')
        p = Pendenz.objects.create(titel='Nachmieter suchen / Inserat aufschalten', vertrag=v,
                                   kategorie='aufgabe', faellig_am=date.today())
        team = _team_user(); c = Client(); c.force_login(team)
        c.post(f'/neu/objekte/{e.id}/ausschreiben/', {'ziel': 'an', 'weiter': '/neu/mieterwechsel/'})
        p.refresh_from_db()
        self.assertTrue(p.erledigt)


class SchadenModalTests(TestCase):
    def test_schadenliste_oeffnet_detail_im_modal(self):
        """Die Schadensliste öffnet den Schaden inkl. Workflow im Popup, kein Seitenwechsel."""
        from tickets.models import SchadenMeldung
        lg, e, m, v = _basis_objekte()
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Wasserschaden', beschreibung='x')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/schaeden/').content.decode()
        self.assertIn(f"fwModalOpenUrl('/neu/schaeden/{t.id}/'", body)
        self.assertIn('id="fwModal"', body)
        self.assertNotIn(f"window.location='/neu/schaeden/{t.id}/'", body)

    def test_schaden_detail_im_iframe_chromelos(self):
        """Das Schaden-Detail läuft im Popup chrome-frei (iframe-Kontext-Erkennung)."""
        from tickets.models import SchadenMeldung
        lg, e, m, v = _basis_objekte()
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Wasserschaden', beschreibung='x')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get(f'/neu/schaeden/{t.id}/').content.decode()
        self.assertIn('window.self !== window.top', body)   # Chrome wird im iframe versteckt


class ModalFramingTests(TestCase):
    def test_xframe_options_erlaubt_eigene_iframes(self):
        """X-Frame-Options muss SAMEORIGIN sein — sonst bleiben die Popups leer."""
        lg, e, m, v = _basis_objekte()
        team = _team_user()
        c = Client(); c.force_login(team)
        for url in ('/neu/mieterwechsel/', f'/neu/vertraege/{v.id}/', '/neu/schaeden/'):
            r = c.get(url)
            xf = r.headers.get('X-Frame-Options', '')
            self.assertEqual(xf.upper(), 'SAMEORIGIN', f"{url}: {xf!r}")

    def test_vertragsliste_oeffnet_detail_im_modal(self):
        lg, e, m, v = _basis_objekte()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/vertraege/').content.decode()
        self.assertIn(f"fwModalOpenUrl('/neu/vertraege/{v.id}/'", body)
        self.assertIn('id="fwModal"', body)
        self.assertNotIn(f"window.location='/neu/vertraege/{v.id}/'", body)

    def test_debitorenliste_ansehen_im_modal(self):
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                         titel='Miete', betrag=Decimal('1700'),
                                         faellig_am=date.today(), status='offen')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/debitoren/').content.decode()
        self.assertIn("fwModalOpen(this,'Vertrag',true)", body)   # breit für Vorschau daneben
        self.assertIn('id="fwModal"', body)


class MieterwechselE2ETests(TestCase):
    """Durchgängiger End-to-End-Durchlauf des ganzen Mieterwechsel-Kreislaufs
    über die echten URLs: Kündigen → Pendenzen → Ausschreiben → Nachmieter →
    Rücknahme → Übergabe → Schlussabrechnung → Auto-Abhaken → Cockpit leer."""

    def _konten(self):
        _seed_konten()

    def test_kompletter_kreislauf(self):
        from core.models import Pendenz
        from rentals.models import Kuendigung, Abnahmeprotokoll
        self._konten()
        lg = Liegenschaft.objects.create(strasse='Wechselweg 5', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='4.5 Zi', typ='wohnung',
                                   nettomiete_aktuell=Decimal('1800'), nebenkosten_aktuell=Decimal('250'))
        m = Mieter.objects.create(typ='person', vorname='Alt', nachname='Mieter', email='alt@example.ch')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2023, 1, 1),
                                       netto_mietzins=Decimal('1800'), nebenkosten=Decimal('250'),
                                       status='aktiv', kautions_betrag=Decimal('5400'),
                                       kautions_einbezahlt_am=date(2023, 1, 5))
        team = _team_user()
        c = Client(); c.force_login(team)

        # 1) KÜNDIGEN (im Popup) → Vertrag gekündigt + Auszugs-Pendenzen
        r = c.post(f'/neu/vertraege/{v.id}/kuendigen/', {
            'embed': '1', 'absender': 'mieter', 'eingang_datum': date.today().isoformat(),
            'zustellung': 'einschreiben'})
        self.assertIn("fwModal: 'done'", r.content.decode())
        v.refresh_from_db()
        self.assertEqual(v.status, 'gekuendigt')
        pend_total = Pendenz.objects.filter(vertrag=v, erledigt=False).count()
        self.assertGreaterEqual(pend_total, 5)

        # 1b) Kündigung schriftlich bestätigen → erste Pendenz abgehakt
        kd = Kuendigung.objects.get(vertrag=v)
        c.post(f'/neu/kuendigung/{kd.id}/bestaetigen/')
        self.assertFalse(Pendenz.objects.filter(vertrag=v, erledigt=False,
                                                titel__icontains='schriftlich bestätigen').exists())

        # 2) DASHBOARD zeigt die Aufgaben
        self.assertEqual(c.get('/neu/').status_code, 200)

        # 3) COCKPIT listet den Wechsel als 'Gekündigt' + Ausschreiben-Aktion
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('Wechselweg 5', body)
        self.assertIn(f'/neu/objekte/{e.id}/ausschreiben/', body)

        # 4) OBJEKT AUSSCHREIBEN → Vermarktung + 'Nachmieter'-Pendenz erledigt
        c.post(f'/neu/objekte/{e.id}/ausschreiben/',
               {'embed': '1', 'ziel': 'an', 'verfuegbar_ab': (date.today() + timedelta(days=60)).isoformat()})
        e.refresh_from_db()
        self.assertTrue(e.zur_ausschreibung)
        self.assertContains(c.get('/neu/vermarktung/'), '4.5 Zi')

        # 5) RÜCKNAHME protokollieren → 'Wohnungsabnahme'-Pendenz erledigt
        r = c.post(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug', {
            'embed': '1', 'typ': 'auszug', 'datum': date.today().isoformat(),
            'allgemein_zustand': 'gut', 'schluessel_anzahl': '3', 'zaehler_strom': '12345'})
        self.assertIn("fwModal: 'done'", r.content.decode())
        self.assertTrue(v.abnahmen.filter(typ='auszug').exists())
        self.assertFalse(Pendenz.objects.filter(vertrag=v, erledigt=False,
                                                titel__icontains='Wohnungsabnahme').exists())

        # 6) NACHMIETER-Vertrag anlegen (beginnt nach Auszug)
        nm = Mieter.objects.create(typ='person', vorname='Neu', nachname='Mieter', email='neu@example.ch')
        ende = v.ende or (date.today() + timedelta(days=60))
        nv = Mietvertrag.objects.create(mieter=nm, einheit=e, beginn=ende + timedelta(days=1),
                                        netto_mietzins=Decimal('1850'), nebenkosten=Decimal('250'),
                                        status='entwurf')
        # Nachmieter erkannt → Übergabe-Aktion verfügbar. (Die Stufe zeigt hier
        # bereits 'Schlussabrechnung', weil die Kaution offen ist — der
        # Übergabe-Link ist der Beweis, dass der Nachmieter erkannt wurde.)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('Neu Mieter', body)
        self.assertIn(f'/neu/vertraege/{nv.id}/abnahme/neu/?typ=einzug', body)

        # 7) ÜBERGABE an Nachmieter
        r = c.post(f'/neu/vertraege/{nv.id}/abnahme/neu/?typ=einzug', {
            'embed': '1', 'typ': 'einzug', 'datum': date.today().isoformat(), 'allgemein_zustand': 'gut'})
        self.assertIn("fwModal: 'done'", r.content.decode())
        self.assertTrue(nv.abnahmen.filter(typ='einzug').exists())

        # 8) SCHLUSSABRECHNUNG verbuchen → Schlussabrechnung + Kaution erledigt
        r = c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/', {
            'embed': '1', 'aktion': 'buchen', 'auszug_datum': ende.isoformat(),
            'kaution_verrechnen': 'on'})
        self.assertIn("fwModal: 'done'", r.content.decode())
        v.refresh_from_db()
        self.assertIsNotNone(v.kautions_zurueckbezahlt_am)

        # 9) ERGEBNIS: alle Auszugs-Pendenzen erledigt → Gruppe leer
        offen = Pendenz.objects.filter(vertrag=v, erledigt=False)
        self.assertEqual(offen.count(), 0,
                         f"noch offen: {[p.titel for p in offen]}")


class MietvertragObjektartTests(TestCase):
    """Vertrag richtet sich nach der Objektart (Titel + Mietrecht-Regime)."""

    def _einheit(self, typ):
        lg = Liegenschaft.objects.create(strasse='Artweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Objekt', typ=typ,
                                   nettomiete_aktuell=Decimal('150'))
        m = Mieter.objects.create(typ='person', nachname='Muster')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal('150'), nebenkosten=Decimal('0'),
                                       status='aktiv')
        return lg, e, m, v

    def test_titel_und_kategorie(self):
        faelle = {
            'whg': ('Mietvertrag für Wohnräume', 'wohnen', True),
            'gew': ('Mietvertrag für Geschäftsräume', 'gewerbe', True),
            'pp':  ('Mietvertrag für einen Parkplatz', 'nebenobjekt', False),
            'gar': ('Mietvertrag für eine Garage', 'nebenobjekt', False),
            'bas': ('Mietvertrag für einen Bastel-/Hobbyraum', 'nebenobjekt', False),
        }
        for typ, (titel, kat, geschuetzt) in faelle.items():
            _lg, e, _m, v = self._einheit(typ)
            self.assertEqual(v.vertrag_titel, titel, typ)
            self.assertEqual(v.mietrecht_kategorie, kat, typ)
            self.assertEqual(v.ist_geschuetzt, geschuetzt, typ)
        # Kaution-Obergrenze nur bei Wohnräumen
        _lg, e, _m, v = self._einheit('whg')
        self.assertEqual(v.kaution_max_monate, 3)
        _lg, e, _m, v = self._einheit('pp')
        self.assertIsNone(v.kaution_max_monate)

    def test_pdf_titel_parkplatz(self):
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        _lg, e, _m, v = self._einheit('pp')
        pdf = generate_vertrag_pdf_bytes(v)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_wizard_vorwahl_liefert_titel(self):
        _lg, e, _m, v = self._einheit('pp')
        team = _team_user(); c = Client(); c.force_login(team)
        r = c.get(f'/neu/vertraege/neu/?einheit={e.id}')
        obj = r.context['liegenschaften'][0]['objekte'][0]
        self.assertEqual(obj['vertrag_titel'], 'Mietvertrag für einen Parkplatz')
        self.assertEqual(obj['kategorie'], 'nebenobjekt')

    def test_checkliste_regime_nebenobjekt(self):
        """Vermieterkündigung eines Parkplatzes → KEIN amtliches Formular."""
        from core.models import Pendenz
        _lg, e, _m, v = self._einheit('pp')
        team = _team_user(); c = Client(); c.force_login(team)
        c.post(f'/neu/vertraege/{v.id}/kuendigen/', {
            'absender': 'vermieter', 'eingang_datum': date.today().isoformat(),
            'zustellung': 'einschreiben'})
        titel = list(Pendenz.objects.filter(vertrag=v).values_list('titel', flat=True))
        self.assertIn('Kündigung schriftlich mitteilen', titel)
        self.assertNotIn('Amtliches Kündigungsformular versenden', titel)

    def test_checkliste_regime_wohnung(self):
        """Vermieterkündigung einer Wohnung → amtliches Formular."""
        from core.models import Pendenz
        _lg, e, _m, v = self._einheit('whg')
        team = _team_user(); c = Client(); c.force_login(team)
        c.post(f'/neu/vertraege/{v.id}/kuendigen/', {
            'absender': 'vermieter', 'eingang_datum': date.today().isoformat(),
            'zustellung': 'einschreiben'})
        titel = list(Pendenz.objects.filter(vertrag=v).values_list('titel', flat=True))
        self.assertIn('Amtliches Kündigungsformular versenden', titel)

    def test_kuendigung_note_einstellplatz_vs_bastelraum(self):
        # Parkplatz/Garage = Einstellplatz → Art. 266e (2 Wochen)
        for typ in ('pp', 'gar'):
            _lg, _e, _m, v = self._einheit(typ)
            self.assertIn('Art. 266e', v.nebenobjekt_kuendigung_note, typ)
        # Bastelraum = übrige unbewegliche Sache → Art. 266b (3 Monate)
        _lg, _e, _m, v = self._einheit('bas')
        self.assertIn('Art. 266b', v.nebenobjekt_kuendigung_note)
        self.assertNotIn('266e', v.nebenobjekt_kuendigung_note)
        # Wohnung hat keine Nebenobjekt-Note
        _lg, _e, _m, v = self._einheit('whg')
        self.assertEqual(v.nebenobjekt_kuendigung_note, '')


class GewerbeMietzinsTests(TestCase):
    """Stufe 1+2 Gewerbe: Mietzinsmodell (Staffel/Index) + Mietenlauf-Automatik."""

    def _vertrag(self, modell='fest', typ='gew', netto='2000'):
        lg = Liegenschaft.objects.create(strasse='Gewerbe 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('2000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Ladenlokal', typ=typ,
                                   nettomiete_aktuell=Decimal(netto))
        m = Mieter.objects.create(typ='firma', firmen_name='Muster GmbH')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal(netto), nebenkosten=Decimal('200'),
                                       status='aktiv', mietzins_modell=modell)
        return lg, e, m, v

    def test_effektiver_mietzins_staffel(self):
        from rentals.models import Staffelstufe
        _lg, _e, _m, v = self._vertrag('staffel', netto='2000')
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2025, 1, 1), netto_mietzins=Decimal('2100'))
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2026, 1, 1), netto_mietzins=Decimal('2200'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2024, 6, 1)), Decimal('2000'))  # vor 1. Stufe
        self.assertEqual(v.effektiver_netto_mietzins(date(2025, 6, 1)), Decimal('2100'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 6, 1)), Decimal('2200'))

    def test_effektiver_mietzins_fest_und_index(self):
        _lg, _e, _m, v = self._vertrag('fest', netto='2000')
        self.assertEqual(v.effektiver_netto_mietzins(date(2030, 1, 1)), Decimal('2000'))
        _lg, _e, _m, v2 = self._vertrag('index', netto='2000')
        self.assertEqual(v2.effektiver_netto_mietzins(date(2030, 1, 1)), Decimal('2000'))

    def test_sollstellung_nutzt_staffel(self):
        from rentals.models import Staffelstufe
        from finance.models import DebitorenRechnung
        from core.services.automation import run_sollstellung
        _seed_konten()
        _lg, _e, _m, v = self._vertrag('staffel', netto='2000')
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2025, 1, 1), netto_mietzins=Decimal('2100'))
        run_sollstellung(2025, 3)   # März 2025 → Stufe 2100 gilt
        r = DebitorenRechnung.objects.filter(vertrag=v).order_by('-id').first()
        self.assertIsNotNone(r)
        # Betrag = 2100 netto + 200 NK (voller Monat)
        self.assertEqual(r.betrag, Decimal('2300.00'))

    def test_index_pendenz_bei_gestiegenem_lik(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        _lg, _e, _m, v = self._vertrag('index', netto='2000')
        v.basis_lik_punkte = Decimal('95.0')   # klar unter aktuellem Tabellenwert
        v.beginn = date(2020, 1, 1)             # Intervall längst erreicht
        v.save()
        generate_auto_pendenzen(horizont_tage=120)
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='Indexmiete anpassen').first()
        self.assertIsNotNone(p)
        self.assertIn('Art. 269d', p.beschreibung)

    def test_kein_index_wenn_lik_nicht_gestiegen(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        _lg, _e, _m, v = self._vertrag('index', netto='2000')
        v.basis_lik_punkte = Decimal('999.0')   # unrealistisch hoch → keine Erhöhung
        v.beginn = date(2020, 1, 1)
        v.save()
        generate_auto_pendenzen(horizont_tage=120)
        self.assertFalse(Pendenz.objects.filter(vertrag=v, titel__icontains='Indexmiete anpassen').exists())


class GewerbeWizardTests(TestCase):
    """Etappe D: derselbe Wizard, aber Gewerbe blendet Modell/Staffel ein und
    speichert korrekt (Kündigungsfrist-Default 6, Staffelstufen)."""

    def _gew_einheit(self):
        lg = Liegenschaft.objects.create(strasse='Laden 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('2000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='EG Laden', typ='gew',
                                   nettomiete_aktuell=Decimal('3000'), nebenkosten_aktuell=Decimal('300'))
        m = Mieter.objects.create(typ='firma', firmen_name='Test GmbH')
        return lg, e, m

    def test_wizard_zeigt_gewerbe_felder(self):
        lg, e, m = self._gew_einheit()
        team = _team_user(); c = Client(); c.force_login(team)
        body = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        self.assertIn('id="gewerbe-box"', body)
        self.assertIn('name="mietzins_modell"', body)
        self.assertIn("o.kategorie === 'gewerbe'", body)

    def test_speichern_gewerbe_staffel_und_frist(self):
        from rentals.models import Mietvertrag as MV, Staffelstufe
        lg, e, m = self._gew_einheit()
        team = _team_user(); c = Client(); c.force_login(team)
        c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': e.id, 'mieter_id': m.id, 'beginn': '2024-01-01',
            'netto_mietzins': '3000', 'nebenkosten': '300',
            'mietzins_modell': 'staffel',
            'staffel_ab': ['2025-01-01', '2026-01-01'],
            'staffel_netto': ['3100', '3200'],
            'zweckbestimmung': 'Betrieb einer Bäckerei',
            # kuendigungsfrist bewusst weggelassen → Default 6 (Gewerbe)
        })
        v = MV.objects.filter(einheit=e).order_by('-id').first()
        self.assertIsNotNone(v)
        self.assertEqual(v.mietzins_modell, 'staffel')
        self.assertEqual(v.kuendigungsfrist_monate, 6)
        self.assertEqual(v.zweckbestimmung, 'Betrieb einer Bäckerei')
        self.assertEqual(v.staffelstufen.count(), 2)
        self.assertEqual(v.effektiver_netto_mietzins(date(2025, 6, 1)), Decimal('3100'))

    def test_live_mietrecht_check_im_wizard(self):
        """Der Wizard enthält die Live-Plausibilitätsprüfung (meldet beim Erfassen)."""
        lg, e, m = self._gew_einheit()
        team = _team_user(); c = Client(); c.force_login(team)
        body = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        self.assertIn('function mietrechtCheck', body)
        self.assertIn('id="mietrecht-warn"', body)
        self.assertIn('Art. 257e OR', body)   # Kaution-Prüfung
        self.assertIn('Art. 269b OR', body)   # Index-Dauer-Prüfung

    def test_pdf_gewerbe_index_rendert(self):
        from rentals.models import Mietvertrag as MV
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        lg, e, m = self._gew_einheit()
        v = MV.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                              netto_mietzins=Decimal('3000'), nebenkosten=Decimal('300'),
                              status='aktiv', mietzins_modell='index',
                              zweckbestimmung='Büro')
        pdf = generate_vertrag_pdf_bytes(v)
        self.assertTrue(pdf.startswith(b'%PDF'))


class MietrechtReferenzTests(TestCase):
    """Zentrale Gesetzesreferenzen + Validierungen (analysis → software)."""

    def test_artikel_referenzen(self):
        from core.services import mietrecht
        self.assertEqual(mietrecht.ref('kaution'), 'Art. 257e OR')
        self.assertEqual(mietrecht.ref('verzug'), 'Art. 257d OR')
        self.assertEqual(mietrecht.kuendigung_ref('wohnen'), 'Art. 266c OR')
        self.assertEqual(mietrecht.kuendigung_ref('gewerbe'), 'Art. 266d OR')
        self.assertEqual(mietrecht.kuendigung_ref('nebenobjekt', ist_einstellplatz=True), 'Art. 266e OR')
        self.assertEqual(mietrecht.kuendigung_ref('nebenobjekt', ist_einstellplatz=False), 'Art. 266b OR')

    def test_template_tag(self):
        from django.template import Template, Context
        out = Template("{% load mietrecht_tags %}{% art 'indexmiete' %}|{{ 'staffelmiete'|artikel }}").render(Context({}))
        self.assertEqual(out, 'Art. 269b OR|Art. 269c OR')

    def test_pruefe_mietzinsmodell(self):
        from core.services.mietrecht import pruefe_mietzinsmodell
        from datetime import date as d
        # Index ohne Ende → Warnung
        self.assertTrue(pruefe_mietzinsmodell('index', d(2024, 1, 1), None))
        # Index < 5 Jahre → Warnung
        self.assertTrue(pruefe_mietzinsmodell('index', d(2024, 1, 1), d(2027, 1, 1)))
        # Index ≥ 5 Jahre → ok
        self.assertFalse(pruefe_mietzinsmodell('index', d(2024, 1, 1), d(2029, 1, 1)))
        # Staffel < 3 Jahre → Warnung
        self.assertTrue(pruefe_mietzinsmodell('staffel', d(2024, 1, 1), d(2025, 6, 1)))
        # Staffel ≥ 3 Jahre → ok
        self.assertFalse(pruefe_mietzinsmodell('staffel', d(2024, 1, 1), d(2027, 6, 1)))
        # Fest → nie Warnung
        self.assertFalse(pruefe_mietzinsmodell('fest', d(2024, 1, 1), None))

    def test_staffel_max_eine_erhoehung_pro_jahr(self):
        from core.services.mietrecht import staffel_pruefung
        from datetime import date as d
        class S:
            def __init__(self, dt): self.ab_datum = dt
        # zwei Stufen < 1 Jahr auseinander → Warnung
        self.assertTrue(staffel_pruefung([S(d(2025, 1, 1)), S(d(2025, 8, 1))]))
        # jährlich → ok
        self.assertFalse(staffel_pruefung([S(d(2025, 1, 1)), S(d(2026, 1, 1)), S(d(2027, 1, 1))]))

    def test_kuendigungsbestaetigung_pdf_mit_zitaten(self):
        """Die Kündigungsbestätigung rendert (nutzt die Template-Tags)."""
        from rentals.models import Mietvertrag as MV, Kuendigung
        from core.services.dokument_service import generate_dokument_pdf_bytes
        lg, e, m, v = _basis_objekte()
        Kuendigung.objects.create(vertrag=v, absender='vermieter', eingang_datum=date.today(),
                                  per_datum=date.today() + timedelta(days=90),
                                  berechneter_termin=date.today() + timedelta(days=90), status='bestaetigt')
        pdf = generate_dokument_pdf_bytes(v, 'kuendigungsbestaetigung')
        self.assertTrue(pdf.startswith(b'%PDF'))


class EinstellplatzFristTests(TestCase):
    """Vertretbare Anpassung: Einstellplatz-Kündigung nach Art. 266e (2 Wochen)."""

    def _platz(self, typ='pp'):
        lg = Liegenschaft.objects.create(strasse='Platz 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('500000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 12', typ=typ,
                                   nettomiete_aktuell=Decimal('120'))
        m = Mieter.objects.create(typ='person', nachname='Halter')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal('120'), nebenkosten=Decimal('0'),
                                       status='aktiv', kuendigungsfrist_monate=3)
        return lg, e, m, v

    def test_termin_zwei_wochen_auf_monatsende(self):
        from rentals.services import berechne_kuendigungstermin
        _lg, _e, _m, v = self._platz('pp')
        # Eingang 5. März → +14 Tage = 19. März → nächstes Monatsende = 31. März
        t = berechne_kuendigungstermin(v, date(2025, 3, 5))
        self.assertEqual(t, date(2025, 3, 31))
        # Eingang 20. März → +14 Tage = 3. April → 30. April
        t2 = berechne_kuendigungstermin(v, date(2025, 3, 20))
        self.assertEqual(t2, date(2025, 4, 30))

    def test_anzeige_einstellplatz_vs_bastelraum(self):
        _lg, _e, _m, v = self._platz('gar')
        self.assertIn('2 Wochen', v.kuendigungsfrist_anzeige)
        self.assertIn('266e', v.kuendigungsfrist_anzeige)
        # Bastelraum ist kein Einstellplatz → Monatsanzeige
        _lg, _e, _m, vb = self._platz('bas')
        self.assertIn('Monate', vb.kuendigungsfrist_anzeige)
        self.assertNotIn('266e', vb.kuendigungsfrist_anzeige)

    def test_wohnung_frist_unveraendert(self):
        from rentals.services import berechne_kuendigungstermin
        lg, e, m, v = _basis_objekte()   # Wohnung, 3 Monate
        t = berechne_kuendigungstermin(v, date(2025, 1, 15))
        # 3 Monate ab Januar → April-Ende (regulär), nicht 2-Wochen-Logik
        self.assertEqual(t.month, 4)


class ReferenzzinsSenkungTests(TestCase):
    """Art. 270a: sinkt der Referenzzins unter die Vertragsbasis, wird eine
    informative Pendenz (Herabsetzung möglich) angelegt."""

    def _setup(self, basis, aktuell):
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='V AG', aktueller_referenzzinssatz=Decimal(str(aktuell)))
        lg, e, m, v = _basis_objekte()
        v.basis_referenzzinssatz = Decimal(str(basis))
        v.mietzins_modell = 'fest'
        v.save()
        return v

    def test_pendenz_bei_senkung(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        v = self._setup(basis='2.00', aktuell='1.50')
        generate_auto_pendenzen(horizont_tage=90)
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='Referenzzinssenkung').first()
        self.assertIsNotNone(p)
        self.assertIn('Art. 270a', p.beschreibung)

    def test_keine_pendenz_wenn_gleich_oder_hoeher(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        v = self._setup(basis='1.50', aktuell='1.75')   # aktuell höher → kein Anspruch
        generate_auto_pendenzen(horizont_tage=90)
        self.assertFalse(Pendenz.objects.filter(vertrag=v, titel__icontains='Referenzzinssenkung').exists())

    def test_keine_pendenz_bei_indexvertrag(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        v = self._setup(basis='2.00', aktuell='1.50')
        v.mietzins_modell = 'index'; v.save()
        generate_auto_pendenzen(horizont_tage=90)
        self.assertFalse(Pendenz.objects.filter(vertrag=v, titel__icontains='Referenzzinssenkung').exists())


class MietzinsAnpassungLiveTests(TestCase):
    """Die Mietzinsanpassung meldet mietrechtliche Probleme live beim Erfassen
    (Art. 269d/270a OR), nicht erst auf dem PDF."""

    def _setup(self):
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='V AG', aktueller_referenzzinssatz=Decimal('1.50'))
        lg, e, m, v = _basis_objekte()
        v.basis_referenzzinssatz = Decimal('1.75')
        v.basis_lik_punkte = Decimal('100')
        v.mietzins_modell = 'fest'
        v.save()
        return v

    def test_live_pruefung_im_formular(self):
        v = self._setup()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/mietzins/{v.id}/anpassung/').content.decode()
        # Live-Prüf-Gerüst vorhanden
        self.assertIn('function mietzinsCheck', body)
        self.assertIn('id="mz-warn"', body)
        # Die drei geprüften Rechtsgrundlagen sind im ausgelieferten Script referenziert
        self.assertIn('Art. 269d Abs. 1 OR', body)   # Ankündigungsfrist/Termin
        self.assertIn('Art. 269 OR', body)           # Missbrauch/Anfechtung
        self.assertIn('Art. 270a OR', body)          # Herabsetzung bei gesunkenem Referenzzins
        # Serverwerte für die Client-Prüfung sind eingebettet
        self.assertIn('MZ_MIN_WIRKSAM', body)
        self.assertIn('MZ_VORSCHLAG', body)


class LogbuchTests(TestCase):
    """Audit-Trail / Logbuch: wer hat wann was getan, sichtbar unter /neu/logbuch/,
    mit Filtern, CSV-Export und rollenbasiertem Zugriff."""

    def _log(self, aktion, objekt='', details='', user=None):
        from core.models import AktivitaetsLog
        from core.auth import kategorie_fuer
        return AktivitaetsLog.objects.create(benutzer=user, aktion=aktion, objekt=objekt,
                                             details=details, kategorie=kategorie_fuer(aktion))

    def test_crud_schreibt_logeintraege(self):
        """Person erstellen + Vertrag löschen erzeugen echte Logeinträge mit Benutzer."""
        from core.models import AktivitaetsLog
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        # Person erstellen
        c.post('/neu/personen/neu/', {'typ': 'person', 'vorname': 'Neu', 'nachname': 'Test',
                                      'email': 'neu@test.ch'})
        self.assertTrue(AktivitaetsLog.objects.filter(aktion__icontains='Person erstellt',
                                                      benutzer=u).exists())
        # Vertrag löschen
        c.post(f'/neu/vertraege/{v.id}/loeschen/')
        self.assertTrue(AktivitaetsLog.objects.filter(aktion__icontains='gelöscht').exists())

    def test_logbuch_view_zeigt_eintraege(self):
        u = _team_user(); c = Client(); c.force_login(u)
        self._log('Mietvertrag erstellt (Assistent)', 'Hans Muster', 'CHF 1500', user=u)
        r = c.get('/neu/logbuch/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Mietvertrag erstellt')
        self.assertContains(r, 'Hans Muster')

    def test_filter_freitext_und_art(self):
        u = _team_user(); c = Client(); c.force_login(u)
        self._log('Person gelöscht', 'Alt Kunde', user=u)
        self._log('Dokument hochgeladen', 'Vertrag.pdf', user=u)
        # Freitext
        r = c.get('/neu/logbuch/?q=Kunde')
        self.assertContains(r, 'Person gelöscht')
        self.assertNotContains(r, 'Dokument hochgeladen')
        # Art-Bucket "geloescht"
        r = c.get('/neu/logbuch/?art=geloescht')
        self.assertContains(r, 'Person gelöscht')
        self.assertNotContains(r, 'Dokument hochgeladen')

    def test_csv_export(self):
        u = _team_user(); c = Client(); c.force_login(u)
        self._log('Kaution zurückbezahlt', 'Hans Muster', 'CHF 4500', user=u)
        r = c.get('/neu/logbuch/?export=csv')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        self.assertIn('Kaution zurückbezahlt', r.content.decode('utf-8'))

    def test_pdf_auditbericht(self):
        u = _team_user(); c = Client(); c.force_login(u)
        self._log('Person gelöscht', 'Alt Kunde', user=u)
        r = c.get('/neu/logbuch/?export=pdf')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_statistik_kopf(self):
        u = _team_user(); c = Client(); c.force_login(u)
        self._log('Person gelöscht', 'A', user=u)
        r = c.get('/neu/logbuch/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'davon kritisch')
        self.assertContains(r, 'Aktivste Benutzer')
        self.assertContains(r, 'Art. 958f OR')

    def test_nur_verwaltung_sieht_logbuch(self):
        """Lesend-Rolle darf das Logbuch nicht sehen (rollenbasiert)."""
        u = _team_user(rolle='Lesend'); c = Client(); c.force_login(u)
        r = c.get('/neu/logbuch/')
        self.assertNotEqual(r.status_code, 200)

    def test_eintrag_verweist_auf_objekt(self):
        """Statusänderung verlinkt den Eintrag auf den Vertrag (ziel_typ/ziel_id + ziel_url)."""
        from core.models import AktivitaetsLog
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/vertraege/{v.id}/status/', {'status': 'archiviert'})
        log = AktivitaetsLog.objects.filter(ziel_typ='vertrag', ziel_id=v.id).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.ziel_url, f'/neu/vertraege/{v.id}/')
        # Logbuch rendert den Link
        r = c.get('/neu/logbuch/')
        self.assertContains(r, f'href="/neu/vertraege/{v.id}/"')

    def test_verlauf_tab_auf_vertrag(self):
        """Der Vertrag zeigt seinen eigenen Verlauf (Audit-Einträge)."""
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        self._log('Kaution einbezahlt (Sperrkonto)', str(m), 'CHF 4500', user=u)
        # ziel setzen wie im echten Flow
        from core.models import AktivitaetsLog
        AktivitaetsLog.objects.all().update(ziel_typ='vertrag', ziel_id=v.id)
        r = c.get(f'/neu/vertraege/{v.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="vt-verlauf"')
        self.assertContains(r, 'Kaution einbezahlt')

    # --- #4 Strukturierte Kategorie ---
    def test_kategorie_wird_abgeleitet(self):
        from core.auth import log_aktion, kategorie_fuer
        self.assertEqual(kategorie_fuer('Person gelöscht'), 'geloescht')
        self.assertEqual(kategorie_fuer('Kaution zurückbezahlt'), 'finanzen')
        self.assertEqual(kategorie_fuer('Mietvertrag erstellt'), 'erstellt')
        self.assertEqual(kategorie_fuer('Angemeldet'), 'sicherheit')
        # log_aktion speichert die Kategorie automatisch
        u = _team_user()
        req = type('R', (), {'user': u, 'META': {}})()
        log_aktion(req, 'Dokument hochgeladen', 'x.pdf')
        from core.models import AktivitaetsLog
        self.assertEqual(AktivitaetsLog.objects.latest('id').kategorie, 'erstellt')

    def test_filter_kritisch(self):
        u = _team_user(); c = Client(); c.force_login(u)
        self._log('Person gelöscht', 'A', user=u)          # geloescht → kritisch
        self._log('Kaution zurückbezahlt', 'B', user=u)     # finanzen → kritisch
        self._log('Person bearbeitet', 'C', user=u)         # bearbeitet → nicht kritisch
        r = c.get('/neu/logbuch/?art=kritisch')
        self.assertContains(r, 'Person gelöscht')
        self.assertContains(r, 'Kaution zurückbezahlt')
        self.assertNotContains(r, 'Person bearbeitet')

    # --- #3 Login-/Sicherheits-Events ---
    def test_login_events_protokolliert(self):
        from core.models import AktivitaetsLog
        User.objects.create_user(username='chef', password='geheim123')
        c = Client()
        # erfolgreicher Login
        self.assertTrue(c.login(username='chef', password='geheim123'))
        self.assertTrue(AktivitaetsLog.objects.filter(aktion='Angemeldet',
                                                      kategorie='sicherheit').exists())
        # fehlgeschlagener Login
        c2 = Client(); c2.login(username='chef', password='falsch')
        self.assertTrue(AktivitaetsLog.objects.filter(aktion='Anmeldung fehlgeschlagen',
                                                      kategorie='sicherheit').exists())

    # --- #2 Vorher → Nachher bei Änderungen ---
    def test_person_aenderung_diff(self):
        from core.models import AktivitaetsLog
        lg, e, m, v = _basis_objekte()   # m: Hans Muster
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/personen/{m.id}/bearbeiten/', {
            'typ': 'person', 'vorname': 'Hans', 'nachname': 'Meier',   # Muster → Meier
            'email': 'hans@example.ch',
        })
        log = AktivitaetsLog.objects.filter(aktion='Person bearbeitet').latest('id')
        self.assertIn('Nachname: Muster → Meier', log.details)

    def test_diff_auf_allen_modulen(self):
        """Der Vorher→Nachher-Diff greift generisch — hier für Liegenschaft & Objekt."""
        from core.models import AktivitaetsLog
        lg, e, m, v = _basis_objekte()   # lg: …, Zürich · e: '3.5 Zi'
        u = _team_user(); c = Client(); c.force_login(u)
        # Liegenschaft: Ort Zürich → Bern (GWR-Import deaktiviert)
        c.post(f'/neu/liegenschaften/{lg.id}/bearbeiten/', {
            'strasse': 'Teststrasse 1', 'plz': '8000', 'ort': 'Bern', 'gwr_import': '',
        })
        log = AktivitaetsLog.objects.filter(aktion='Liegenschaft bearbeitet').latest('id')
        self.assertIn('→ Bern', log.details)
        # Objekt: Bezeichnung ändern
        c.post(f'/neu/objekte/{e.id}/bearbeiten/', {
            'liegenschaft_id': lg.id, 'bezeichnung': '4.5 Zi', 'typ': 'whg',
            'nettomiete_aktuell': '1500', 'nebenkosten_aktuell': '200',
        })
        log2 = AktivitaetsLog.objects.filter(aktion='Objekt bearbeitet').latest('id')
        self.assertIn('4.5 Zi', log2.details)


class Verzug257dTests(TestCase):
    """Zahlungsverzug Art. 257d: Fristansetzung erzeugt Dokument + Fristen-Pendenz,
    Live-Prüfung der Mindestfrist, Kündigungs-Prefill."""

    def _setup_offen(self):
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        heute = date.today()
        DebitorenRechnung.objects.create(
            vertrag=v, titel='Miete', datum=heute - timedelta(days=40),
            faellig_am=heute - timedelta(days=35), betrag=Decimal('1700'), status='offen')
        return lg, e, m, v

    def test_form_zeigt_offenen_betrag_und_min_frist(self):
        lg, e, m, v = self._setup_offen()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vertraege/{v.id}/verzug/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Art. 257d')
        self.assertContains(r, 'MIN_FRIST = 30')   # Wohnung → geschützt → 30 Tage

    def test_frist_ansetzen_legt_dokument_und_pendenz_an(self):
        from core.models import Pendenz, AktivitaetsLog
        from rentals.models import Dokument
        lg, e, m, v = self._setup_offen()
        c = Client(); c.force_login(_team_user())
        frist = (date.today() + timedelta(days=30)).isoformat()
        r = c.post(f'/neu/vertraege/{v.id}/verzug/', {'frist_bis': frist})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Pendenz.objects.filter(vertrag=v, titel__icontains='257d').exists())
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__icontains='257d').exists())
        self.assertTrue(AktivitaetsLog.objects.filter(aktion__icontains='257d', ziel_typ='vertrag',
                                                      ziel_id=v.id).exists())

    def test_kuendigung_prefill_bei_verzug(self):
        lg, e, m, v = self._setup_offen()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vertraege/{v.id}/kuendigen/?grund=257d')
        self.assertContains(r, 'Zahlungsverzug (Art. 257d OR)')
        # Ausserordentlicher 257d-Termin wird berechnet und angezeigt
        self.assertContains(r, 'Ausserordentlich wegen Zahlungsverzug')
        self.assertContains(r, 'Art. 257d Abs. 2 OR')

    def test_termin_257d_berechnung(self):
        from rentals.services import termin_257d
        # 10.01. + 30 Tage = 09.02. → Ende Februar
        self.assertEqual(termin_257d(date(2026, 1, 10)), date(2026, 2, 28))
        # 05.03. + 30 Tage = 04.04. → Ende April
        self.assertEqual(termin_257d(date(2026, 3, 5)), date(2026, 4, 30))


class AnfechtungsfristTests(TestCase):
    """Anfechtungsfristen als Pendenz: Vermieterkündigung (Art. 271/273) und
    Mietzinserhöhung (Art. 270b) — je 30 Tage."""

    def test_vermieterkuendigung_legt_anfechtungsfrist_an(self):
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()   # Wohnung → geschützt
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/kuendigen/',
               {'absender': 'vermieter', 'eingang_datum': date.today().isoformat(), 'bestaetigen': 'on'})
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='Anfechtungsfrist Kündigung').first()
        self.assertIsNotNone(p)
        self.assertIn('Art. 271', p.beschreibung)
        self.assertEqual(p.faellig_am, date.today() + timedelta(days=30))

    def test_mieterkuendigung_ohne_anfechtungsfrist(self):
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/kuendigen/',
               {'absender': 'mieter', 'eingang_datum': date.today().isoformat(), 'bestaetigen': 'on'})
        self.assertFalse(Pendenz.objects.filter(vertrag=v, titel__icontains='Anfechtungsfrist').exists())

    def test_mietzinserhoehung_legt_anfechtungsfrist_an(self):
        from crm.models import Verwaltung
        from core.models import Pendenz
        Verwaltung.objects.create(firma='V AG', aktueller_referenzzinssatz=Decimal('1.50'))
        lg, e, m, v = _basis_objekte()   # netto 1500
        v.basis_referenzzinssatz = Decimal('1.75'); v.basis_lik_punkte = Decimal('100'); v.save()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mietzins/{v.id}/anpassung/', {
            'aktion': 'speichern', 'neu_netto': '1600', 'neu_zins': '1.50', 'neu_lik': '100',
            'basis_zins': '1.75', 'basis_lik': '100', 'kosten_pct': '0',
            'wirksam_ab': (date.today() + timedelta(days=120)).isoformat(),
        })
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='Anfechtungsfrist Mietzins').first()
        self.assertIsNotNone(p)
        self.assertIn('Art. 270b', p.beschreibung)


class FristenCenterTests(TestCase):
    """Fristen-Center bündelt datierte Pendenzen chronologisch in Zeitfenster."""

    def _frist(self, titel, tage, besch='', vertrag=None):
        from core.models import Pendenz
        return Pendenz.objects.create(titel=titel, kategorie='frist',
                                      faellig_am=date.today() + timedelta(days=tage),
                                      beschreibung=besch, vertrag=vertrag)

    def test_buckets_und_artikel(self):
        lg, e, m, v = _basis_objekte()
        self._frist('Zahlungsfrist', -3, 'Frist bis … (Art. 257d Abs. 1 OR).', vertrag=v)
        self._frist('Kündigungstermin', 5, vertrag=v)
        self._frist('Wartung Heizung', 20)
        self._frist('Vertragsende', 90)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/fristen/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Überfällig')
        self.assertContains(r, 'Diese Woche')
        self.assertContains(r, 'Art. 257d Abs. 1 OR')   # Artikel aus Beschreibung extrahiert
        self.assertContains(r, '1 überfällig')

    def test_nur_gesetzliche_fristen_filter(self):
        from core.models import Pendenz
        Pendenz.objects.create(titel='Manuelle Aufgabe', kategorie='aufgabe',
                               faellig_am=date.today() + timedelta(days=2))
        self._frist('Anfechtungsfrist', 3, 'Art. 270b OR')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/fristen/?nur=frist')
        self.assertContains(r, 'Anfechtungsfrist')
        self.assertNotContains(r, 'Manuelle Aufgabe')


class BuchungsServiceTests(TestCase):
    """Zentrale Buchungsschicht: Kontenplan garantiert, kein stiller Verlust."""

    def test_ensure_und_konto_autocreate(self):
        from finance.booking import ensure_kontenplan, konto
        from finance.models import Buchungskonto
        Buchungskonto.objects.all().delete()
        n = ensure_kontenplan()
        self.assertGreater(n, 10)
        # bekanntes Konto wird bei Bedarf nachgelegt
        Buchungskonto.objects.filter(nummer='1100').delete()
        k = konto('1100')
        self.assertEqual(k.nummer, '1100')

    def test_buche_schreibt_und_ueberspringt_null(self):
        from finance.booking import buche
        from finance.models import Buchung
        b = buche('1100', '3000', Decimal('1500'), 'Test-Miete')
        self.assertIsNotNone(b)
        self.assertEqual(b.soll_konto.nummer, '1100')
        self.assertEqual(b.haben_konto.nummer, '3000')
        # Nullbetrag → keine Buchung
        self.assertIsNone(buche('1100', '3000', Decimal('0'), 'Null'))
        self.assertIsNone(buche('1100', '3000', None, 'None'))
        self.assertEqual(Buchung.objects.count(), 1)

    def test_unbekanntes_konto_wirft(self):
        from finance.booking import buche
        with self.assertRaises(ValueError):
            buche('9999', '3000', Decimal('10'), 'Ungültig')

    def test_sollstellung_bucht_ueber_service(self):
        """Sollstellung schreibt saubere Buchungen, auch wenn der Kontenplan leer war."""
        from finance.models import Buchungskonto, Buchung, DebitorenRechnung
        from core.services.automation import run_sollstellung
        Buchungskonto.objects.all().delete()   # kein Kontenplan → früher stiller Verlust
        lg, e, m, v = _basis_objekte()
        heute = date.today()
        n = run_sollstellung(heute.year, heute.month)
        self.assertGreaterEqual(n, 1)
        r = DebitorenRechnung.objects.filter(vertrag=v).first()
        self.assertIsNotNone(r)
        # Buchungen existieren (nicht stillschweigend verschluckt)
        self.assertTrue(Buchung.objects.filter(debitoren_rechnung=r, soll_konto__nummer='1100').exists())


class WeiterverrechnungTests(TestCase):
    """Geführte Weiterverrechnung: Verknüpfung + ertragsneutrale Buchung über 1190."""

    def _kreditor(self, betrag='500', konto='4000'):
        from finance.models import KreditorenRechnung
        from finance.booking import konto as _k
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(
            lieferant='Sanitär AG', betrag=Decimal(betrag), status='bezahlt',
            liegenschaft=lg, konto=_k(konto))
        return lg, e, m, v, k

    def test_weiterverrechnung_verknuepft_und_neutral(self):
        from finance.models import DebitorenRechnung, Buchung
        lg, e, m, v, k = self._kreditor('500')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/',
                   {'vertrag_id': v.id, 'betrag': '500', 'zuschlag': '0', 'titel': 'Rohrbruch'})
        self.assertIn(r.status_code, (200, 302))
        deb = DebitorenRechnung.objects.filter(quell_kreditor=k).first()
        self.assertIsNotNone(deb)
        self.assertEqual(deb.betrag, Decimal('500.00'))
        # Ertragsneutral: 1100/1190 + 1190/4000 → 1190 netto 0, Aufwand gemindert
        self.assertTrue(Buchung.objects.filter(debitoren_rechnung=deb, soll_konto__nummer='1100', haben_konto__nummer='1190').exists())
        self.assertTrue(Buchung.objects.filter(debitoren_rechnung=deb, soll_konto__nummer='1190', haben_konto__nummer='4000').exists())
        # Kreditor ist voll weiterverrechnet
        k.refresh_from_db()
        self.assertEqual(k.offen_weiterzuverrechnen, Decimal('0.00'))

    def test_zuschlag_wird_als_ertrag_gebucht(self):
        from finance.models import DebitorenRechnung, Buchung
        lg, e, m, v, k = self._kreditor('500')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/',
               {'vertrag_id': v.id, 'betrag': '500', 'zuschlag': '50'})
        deb = DebitorenRechnung.objects.filter(quell_kreditor=k).first()
        self.assertEqual(deb.betrag, Decimal('550.00'))
        self.assertTrue(Buchung.objects.filter(debitoren_rechnung=deb, soll_konto__nummer='1100', haben_konto__nummer='3600', betrag=Decimal('50.00')).exists())

    def test_begrenzt_auf_offenen_anteil(self):
        from finance.models import DebitorenRechnung
        lg, e, m, v, k = self._kreditor('500')
        c = Client(); c.force_login(_team_user())
        # erst 300 weiterverrechnen
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/', {'vertrag_id': v.id, 'betrag': '300', 'zuschlag': '0'})
        k.refresh_from_db()
        self.assertEqual(k.offen_weiterzuverrechnen, Decimal('200.00'))
        # dann 999 versuchen → auf 200 begrenzt
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/', {'vertrag_id': v.id, 'betrag': '999', 'zuschlag': '0'})
        k.refresh_from_db()
        self.assertEqual(k.offen_weiterzuverrechnen, Decimal('0.00'))


class KreditorZahllaufTests(TestCase):
    """pain.001-Zahllauf: enthaltene Rechnungen → 'in Zahlung' (kein Doppelzahlen)."""

    def _setup(self):
        from crm.models import Verwaltung
        from finance.models import KreditorenRechnung
        from finance.booking import konto as _k
        Verwaltung.objects.create(firma='V AG', iban='CH9300762011623852957')
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(
            lieferant='Elektro AG', betrag=Decimal('800'), status='freigegeben',
            liegenschaft=lg, konto=_k('4000'),
            iban='CH9300762011623852957', referenz='R-1')
        return lg, k

    def test_pain001_markiert_in_zahlung(self):
        from finance.models import KreditorenRechnung
        lg, k = self._setup()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.get('/neu/kreditoren/pain001/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('xml', r['Content-Type'])
        k.refresh_from_db()
        self.assertEqual(k.status, 'in_zahlung')
        # Zweiter Lauf enthält sie NICHT mehr → keine freigegebenen mehr
        r2 = c.get('/neu/kreditoren/pain001/')
        self.assertEqual(r2.status_code, 302)   # keine freigegebenen → Redirect mit Fehler

    def test_bestaetigen_bucht_aus(self):
        from finance.models import KreditorenRechnung, Buchung
        lg, k = self._setup()
        k.status = 'in_zahlung'; k.save()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.id})
        k.refresh_from_db()
        self.assertEqual(k.status, 'bezahlt')
        self.assertTrue(Buchung.objects.filter(kreditoren_rechnung=k, soll_konto__nummer='2000', haben_konto__nummer='1020').exists())

    def test_zuruecksetzen(self):
        from finance.models import KreditorenRechnung
        lg, k = self._setup()
        k.status = 'in_zahlung'; k.save()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/kreditoren/{k.id}/zahlung-zuruecksetzen/')
        k.refresh_from_db()
        self.assertEqual(k.status, 'freigegeben')

    def test_teilzahlung_op(self):
        from finance.models import Buchung, KreditorenZahlung
        lg, k = self._setup()   # betrag 800, freigegeben
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        # Teilzahlung 300
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.id, 'betrag': '300'})
        k.refresh_from_db()
        self.assertEqual(k.status, 'teilbezahlt')
        self.assertEqual(k.offener_betrag, Decimal('500.00'))
        self.assertTrue(Buchung.objects.filter(kreditoren_rechnung=k, betrag=Decimal('300.00'),
                                               soll_konto__nummer='2000', haben_konto__nummer='1020').exists())
        # Restzahlung 500 → bezahlt
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.id, 'betrag': '500'})
        k.refresh_from_db()
        self.assertEqual(k.status, 'bezahlt')
        self.assertEqual(k.offener_betrag, Decimal('0.00'))
        self.assertEqual(KreditorenZahlung.objects.filter(kreditor=k, status='verbucht').count(), 2)

    def test_ueberzahlung_begrenzt(self):
        lg, k = self._setup()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.id, 'betrag': '9999'})
        k.refresh_from_db()
        self.assertEqual(k.status, 'bezahlt')
        self.assertEqual(k.bezahlt_betrag, Decimal('800.00'))   # auf offen begrenzt


class RechtsgrundlagenTests(TestCase):
    """In-App-Übersicht der angewandten Rechtsgrundlagen."""

    def test_seite_rendert_artikel(self):
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/rechtsgrundlagen/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Rechtsgrundlagen')
        self.assertContains(r, 'Art. 257d OR')     # Verzug
        self.assertContains(r, 'Art. 269d OR')     # Mietzinserhöhung
        self.assertContains(r, 'Obligationenrecht')
        self.assertContains(r, 'fedlex.admin.ch')  # amtliche Quelle

    def test_suche(self):
        from core.services import gesetzestexte
        # Stichwort
        rows = gesetzestexte.suche('kaution')
        self.assertTrue(any(r['art'] == '257e' for r in rows))
        # Artikelnummer
        rows = gesetzestexte.suche('269c')
        self.assertTrue(any('staffel' in ' '.join(r['stichworte']) for r in rows))
        # Mehrwortsuche
        self.assertTrue(gesetzestexte.suche('referenzzins senkung'))
        # leere Query → alle
        self.assertEqual(len(gesetzestexte.suche('')), len(gesetzestexte.REGISTER))

    def test_suche_view(self):
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/rechtsgrundlagen/?q=kaution')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Art. 257e OR')
        self.assertNotContains(r, 'Art. 266d OR')   # Geschäftsraum-Frist – nicht Treffer

    def test_anwendung_overlay(self):
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/rechtsgrundlagen/?q=257d')
        self.assertContains(r, 'In swissImmo')      # Anwendungshinweis am Artikel


class KautionFreigabeTests(TestCase):
    """Art. 257e Abs. 3: nach 1 Jahr seit Mietende ohne Ansprüche → Freigabe-Pendenz."""

    def test_pendenz_nach_einem_jahr(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        v.ende = date.today() - timedelta(days=366)
        v.status = 'beendet'; v.save()
        generate_auto_pendenzen(horizont_tage=90)
        p = Pendenz.objects.filter(vertrag=v, quelle__startswith='auto:kautionfreigabe').first()
        self.assertIsNotNone(p)
        self.assertIn('Art. 257e Abs. 3', p.beschreibung)
        self.assertEqual(p.kategorie, 'frist')

    def test_keine_pendenz_wenn_zurueckbezahlt(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        v.ende = date.today() - timedelta(days=366)
        v.kautions_zurueckbezahlt_am = date.today(); v.save()
        generate_auto_pendenzen(horizont_tage=90)
        self.assertFalse(Pendenz.objects.filter(quelle__startswith='auto:kautionfreigabe').exists())

    def test_keine_pendenz_bei_versicherung(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        v.ende = date.today() - timedelta(days=366)
        v.kautions_art = 'versicherung'; v.save()
        generate_auto_pendenzen(horizont_tage=90)
        self.assertFalse(Pendenz.objects.filter(quelle__startswith='auto:kautionfreigabe').exists())


class FristenKalenderTests(TestCase):
    """iCal-Export (Download + Feed) und wöchentliches Fristen-Mail."""

    def _frist(self, titel, tage):
        from core.models import Pendenz
        return Pendenz.objects.create(titel=titel, kategorie='frist',
                                      faellig_am=date.today() + timedelta(days=tage))

    def test_ics_download(self):
        self._frist('Kündigungstermin Muster', 5)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/fristen/export.ics')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/calendar', r['Content-Type'])
        body = r.content.decode('utf-8')
        self.assertIn('BEGIN:VCALENDAR', body)
        self.assertIn('BEGIN:VEVENT', body)
        self.assertIn('Kündigungstermin Muster', body)

    def test_feed_token(self):
        from core.services.ical import feed_token
        self._frist('Frist X', 3)
        c = Client()  # ohne Login
        # gültiger Token
        r = c.get(f'/fristen.ics?token={feed_token()}')
        self.assertEqual(r.status_code, 200)
        self.assertIn('BEGIN:VCALENDAR', r.content.decode('utf-8'))
        # ungültiger Token
        r2 = c.get('/fristen.ics?token=falsch')
        self.assertEqual(r2.status_code, 403)

    def test_fristen_digest_mail(self):
        from django.core.management import call_command
        from django.core import mail
        from django.contrib.auth.models import User, Group
        grp, _ = Group.objects.get_or_create(name='Verwaltung')
        u = User.objects.create_user(username='chef2', password='x', email='chef@example.ch')
        u.groups.add(grp)
        self._frist('Zahlungsfrist läuft ab', 2)
        self._frist('Alte Frist', -5)
        call_command('fristen_digest', '--tage', '7')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('chef@example.ch', mail.outbox[0].to)
        self.assertIn('überfällig', mail.outbox[0].subject)

    def test_fristen_digest_ohne_fristen(self):
        from django.core.management import call_command
        from django.core import mail
        call_command('fristen_digest')
        self.assertEqual(len(mail.outbox), 0)

    def test_taeglicher_lauf_sendet_digest_am_wochentag(self):
        from django.core.management import call_command
        from django.core import mail
        from django.utils import timezone
        from django.contrib.auth.models import User, Group
        grp, _ = Group.objects.get_or_create(name='Verwaltung')
        u = User.objects.create_user('chef3', password='x', email='c3@example.ch'); u.groups.add(grp)
        self._frist('Frist morgen', 2)
        wd = timezone.localdate().weekday()
        call_command('taeglicher_lauf', '--digest-weekday', str(wd))
        self.assertEqual(len(mail.outbox), 1)

    def test_taeglicher_lauf_ohne_digest(self):
        from django.core.management import call_command
        from django.core import mail
        self._frist('Frist morgen', 2)
        call_command('taeglicher_lauf', '--digest-weekday', '-1')
        self.assertEqual(len(mail.outbox), 0)


class DashboardKritischTests(TestCase):
    """Kritische Aktionen erscheinen NICHT auf dem Dashboard, sondern im Logbuch."""

    def test_kein_widget_auf_dashboard(self):
        from core.models import AktivitaetsLog
        from core.auth import kategorie_fuer
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        AktivitaetsLog.objects.create(benutzer=u, aktion='Person gelöscht', objekt='Alt Kunde',
                                      kategorie=kategorie_fuer('Person gelöscht'))
        r = c.get('/neu/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Letzte kritische Aktionen')

    def test_kritische_im_logbuch(self):
        from core.models import AktivitaetsLog
        from core.auth import kategorie_fuer
        u = _team_user(); c = Client(); c.force_login(u)
        AktivitaetsLog.objects.create(benutzer=u, aktion='Person gelöscht', objekt='Alt Kunde',
                                      kategorie=kategorie_fuer('Person gelöscht'))
        r = c.get('/neu/logbuch/?art=kritisch')
        self.assertContains(r, 'Person gelöscht')


class FinanzCockpitTests(TestCase):
    """Finanz-Cockpit: EIN Arbeitskorb in Prozessreihenfolge + Monatsabschluss-Checkliste."""

    def test_leerer_arbeitskorb(self):
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/finanzen/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Finanz-Cockpit')
        self.assertContains(r, 'Arbeitskorb')
        self.assertContains(r, 'Alle Finanzaufgaben erledigt')

    def test_offene_debitoren_und_kreditoren_im_korb(self):
        from finance.models import DebitorenRechnung, KreditorenRechnung
        from finance.booking import konto as _k
        lg, e, m, v = _basis_objekte()
        # überfällige Forderung
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete alt', betrag=Decimal('1700'),
            datum=date(2024, 1, 1), faellig_am=date(2024, 1, 1), status='offen')
        # Kreditor neu (zur Freigabe) + freigegeben (zur Zahlung)
        KreditorenRechnung.objects.create(lieferant='Neu AG', betrag=Decimal('200'),
                                          status='neu', liegenschaft=lg, konto=_k('4000'))
        KreditorenRechnung.objects.create(lieferant='Frei AG', betrag=Decimal('300'),
                                          status='freigegeben', liegenschaft=lg, konto=_k('4000'))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/finanzen/')
        self.assertContains(r, 'Zahlungseingänge abgleichen')
        self.assertContains(r, 'Eingangsrechnungen freigeben')
        self.assertContains(r, 'Zahllauf ausführen')
        self.assertContains(r, 'dringend')                    # überfällige Debitoren
        self.assertContains(r, 'Überfällige Forderungen mahnen')
        self.assertNotContains(r, 'Alle Finanzaufgaben erledigt')

    def test_nur_angefangene_weiterverrechnung_ist_todo(self):
        """Eine unberührte Kreditorenrechnung darf NICHT als Weiterverrechnungs-Todo erscheinen;
        eine teilweise weiterverrechnete schon."""
        from finance.models import KreditorenRechnung
        from finance.booking import konto as _k
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('500'),
                                              status='bezahlt', liegenschaft=lg, konto=_k('4000'))
        c = Client(); c.force_login(_team_user())
        # noch nichts weiterverrechnet → Anzahl 0 (Kachel zeigt "erledigt")
        r = c.get('/neu/finanzen/')
        self.assertEqual(r.context['arbeitskorb'][3]['key'], 'weiterverrechnung')
        self.assertEqual(r.context['arbeitskorb'][3]['anzahl'], 0)
        # 300 von 500 weiterverrechnen → jetzt offener Rest = Todo
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/',
               {'vertrag_id': v.id, 'betrag': '300', 'zuschlag': '0'})
        r2 = c.get('/neu/finanzen/')
        self.assertEqual(r2.context['arbeitskorb'][3]['anzahl'], 1)

    def test_checkliste_sollstellung_ampel(self):
        from core.services.automation import run_sollstellung
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        heute = date.today()
        r = c.get('/neu/finanzen/')
        # vor Sollstellung: der Sollstellungs-Schritt ist offen (ok=False)
        soll = next(x for x in r.context['checkliste'] if x['titel'].startswith('Sollstellung'))
        self.assertIs(soll['ok'], False)
        # Sollstellung für aktuellen Monat laufen lassen
        run_sollstellung(heute.year, heute.month)
        r2 = c.get('/neu/finanzen/')
        soll2 = next(x for x in r2.context['checkliste'] if x['titel'].startswith('Sollstellung'))
        self.assertIs(soll2['ok'], True)

    def test_durchlaufkonto_saldo_sichtbar(self):
        from finance.booking import buche
        lg, e, m, v = _basis_objekte()
        # geparkte Position auf 1190 (Soll) — noch nicht geklärt
        buche('1190', '1020', Decimal('120'), 'Unklare Gutschrift', liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/finanzen/')
        self.assertEqual(r.context['durchlauf_saldo'], Decimal('120.00'))
        self.assertContains(r, 'geparkte Positionen klären')


class MieterkontoblattTests(TestCase):
    """Mieterkontoblatt (on-screen): Forderungen + Zahlungen mit laufendem Saldo."""

    def _konto(self):
        from finance.models import DebitorenRechnung, Zahlungseingang
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete 01/2025',
                                         betrag=Decimal('1700'), datum=date(2025, 1, 1),
                                         faellig_am=date(2025, 1, 1), status='offen')
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete 02/2025',
                                         betrag=Decimal('1700'), datum=date(2025, 2, 1),
                                         faellig_am=date(2025, 2, 1), status='bezahlt')
        Zahlungseingang.objects.create(vertrag=v, betrag=Decimal('1700'),
                                       datum_eingang=date(2025, 2, 3), status='verbucht',
                                       bemerkung='Zahlung Februar')
        return lg, e, m, v

    def test_kontoblatt_saldo_und_bewegungen(self):
        lg, e, m, v = self._konto()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mieterkonten/{m.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Kontoblatt')
        self.assertContains(r, 'Miete 01/2025')
        self.assertContains(r, 'Zahlung Februar')
        # Soll 3400, Haben 1700, Endsaldo 1700 (Mieter schuldet)
        self.assertEqual(r.context['total_soll'], Decimal('3400.00'))
        self.assertEqual(r.context['total_haben'], Decimal('1700.00'))
        self.assertEqual(r.context['endsaldo'], Decimal('1700.00'))
        # laufender Saldo der letzten Bewegung = Endsaldo
        self.assertEqual(r.context['zeilen'][-1]['saldo'], Decimal('1700.00'))

    def test_offene_posten_liste(self):
        lg, e, m, v = self._konto()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mieterkonten/{m.id}/')
        # nur die noch offene Rechnung erscheint als OP
        self.assertEqual(len(r.context['op_rows']), 1)
        self.assertEqual(r.context['op_total'], Decimal('1700.00'))

    def test_datumsfilter(self):
        lg, e, m, v = self._konto()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mieterkonten/{m.id}/?von=2025-02-01')
        # nur Februar-Bewegungen (Rechnung + Zahlung), Januar ausgeblendet
        texte = [z['text'] for z in r.context['zeilen']]
        self.assertIn('Miete 02/2025', texte)
        self.assertNotIn('Miete 01/2025', texte)

    def test_uebersicht_listet_mieter_mit_saldo(self):
        lg, e, m, v = self._konto()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterkonten/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, m.display_name)
        self.assertEqual(r.context['total_offen'], Decimal('1700.00'))
        self.assertEqual(r.context['offen_n'], 1)
        # Filter "nur offen"
        r2 = c.get('/neu/mieterkonten/?filter=offen')
        self.assertEqual(len(r2.context['rows']), 1)


class JournalStornoTests(TestCase):
    """Revisionssichere Gegenbuchung: Original bleibt, Storno kehrt Soll/Haben um."""

    def _buchung(self):
        from finance.booking import buche
        lg, e, m, v = _basis_objekte()
        b = buche('4000', '1020', Decimal('250'), 'Falsche Rechnung', liegenschaft=lg)
        return lg, b

    def test_storno_kehrt_um_und_netzt_auf_null(self):
        from finance.booking import storniere_buchung
        from finance.models import Buchung, Buchungskonto
        from django.db.models import Sum
        lg, b = self._buchung()
        gegen = storniere_buchung(b)
        # Soll/Haben getauscht, gleicher Betrag, als Storno markiert, verknüpft
        self.assertTrue(gegen.ist_storno)
        self.assertEqual(gegen.storno_von_id, b.id)
        self.assertEqual(gegen.soll_konto.nummer, '1020')
        self.assertEqual(gegen.haben_konto.nummer, '4000')
        self.assertEqual(gegen.betrag, Decimal('250.00'))
        # Original als storniert markiert (bleibt aber erhalten)
        b.refresh_from_db()
        self.assertIsNotNone(b.storniert_am)
        self.assertEqual(Buchung.objects.count(), 2)
        # Aufwand 4000 netto = 0 (250 Soll − 250 Haben)
        k = Buchungskonto.objects.get(nummer='4000')
        soll = Buchung.objects.filter(soll_konto=k).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        haben = Buchung.objects.filter(haben_konto=k).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        self.assertEqual(soll - haben, Decimal('0.00'))

    def test_kein_doppelstorno(self):
        from finance.booking import storniere_buchung
        lg, b = self._buchung()
        storniere_buchung(b)
        with self.assertRaises(ValueError):
            storniere_buchung(b)

    def test_storno_von_storno_verboten(self):
        from finance.booking import storniere_buchung
        lg, b = self._buchung()
        gegen = storniere_buchung(b)
        with self.assertRaises(ValueError):
            storniere_buchung(gegen)

    def test_view_storniert_und_zeigt_badge(self):
        from finance.models import Buchung
        lg, b = self._buchung()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/buchhaltung/buchung/{b.id}/stornieren/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Buchung.objects.filter(ist_storno=True).count(), 1)
        # Journal zeigt beide + storniert-Badge
        r2 = c.get('/neu/buchhaltung/')
        self.assertContains(r2, 'storniert')
        self.assertContains(r2, 'Storno Beleg')

    def test_original_bleibt_erhalten_kein_hard_delete(self):
        from finance.models import Buchung
        lg, b = self._buchung()
        with self.assertRaises(PermissionError):
            b.delete()


class EigentuemerKontokorrentTests(TestCase):
    """Mandanten-Kontokorrent: Ergebnis − Auszahlungen, korrekte Passiv-Buchung."""

    def _setup(self):
        from crm.models import Mandant
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        md = Mandant.objects.create(firma_oder_name='Eigentum AG', iban='CH9300762011623852957')
        lg, e, m, v = _basis_objekte()
        lg.mandant = md
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
        self.assertEqual(EigentuemerAuszahlung.objects.filter(mandant=md, status='verbucht').count(), 1)
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


class LieferantenkontenTests(TestCase):
    """Lieferantenkonten (Kreditoren): pro Lieferant offener Betrag + Kontoblatt."""

    def _setup(self):
        from finance.models import KreditorenRechnung, KreditorenZahlung
        from finance.booking import konto as _k
        lg, e, m, v = _basis_objekte()
        # Sanitär AG: 2 Rechnungen (800 offen + 300 bezahlt via Zahlung)
        KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('800'),
                                          status='freigegeben', liegenschaft=lg, konto=_k('4000'),
                                          datum=date(2025, 1, 5))
        k2 = KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('300'),
                                               status='bezahlt', liegenschaft=lg, konto=_k('4000'),
                                               datum=date(2025, 1, 10))
        KreditorenZahlung.objects.create(kreditor=k2, betrag=Decimal('300'), datum=date(2025, 1, 20),
                                         konto=_k('1020'), status='verbucht', bemerkung='Zahlung R2')
        # Elektro AG: 1 offene Rechnung
        KreditorenRechnung.objects.create(lieferant='Elektro AG', betrag=Decimal('500'),
                                          status='neu', liegenschaft=lg, konto=_k('4000'),
                                          datum=date(2025, 1, 8))
        return lg

    def test_uebersicht_gruppiert_und_saldo(self):
        lg = self._setup()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/lieferantenkonten/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Sanitär AG')
        self.assertContains(r, 'Elektro AG')
        # total offen = 800 (Sanitär Rest) + 500 (Elektro) = 1300
        self.assertEqual(r.context['total_offen'], Decimal('1300.00'))
        self.assertEqual(r.context['offen_n'], 2)
        # Sanitär-Zeile: 2 Rechnungen, offen 800
        san = next(g for g in r.context['rows'] if g['name'] == 'Sanitär AG')
        self.assertEqual(san['anzahl'], 2)
        self.assertEqual(san['offen'], Decimal('800.00'))
        self.assertEqual(san['volumen'], Decimal('1100.00'))

    def test_kontoblatt_bewegungen_und_saldo(self):
        lg = self._setup()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/lieferantenkonto/?name=Sanit%C3%A4r+AG')
        self.assertEqual(r.status_code, 200)
        # 2 Rechnungen (800+300) belastung, 1 Zahlung 300 → Endsaldo 800
        self.assertEqual(r.context['total_belastung'], Decimal('1100.00'))
        self.assertEqual(r.context['total_zahlung'], Decimal('300.00'))
        self.assertEqual(r.context['endsaldo'], Decimal('800.00'))
        # laufender Saldo der letzten Bewegung = Endsaldo
        self.assertEqual(r.context['bewegungen'][-1]['saldo'], Decimal('800.00'))
        # 1 offener Posten (die 800er Rechnung)
        self.assertEqual(len(r.context['op_rows']), 1)
        self.assertEqual(r.context['op_total'], Decimal('800.00'))

    def test_filter_nur_offen(self):
        lg = self._setup()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/lieferantenkonten/?filter=offen')
        self.assertEqual(len(r.context['rows']), 2)   # beide haben offene Posten


class ExposeTests(TestCase):
    """Exposé/Inserat-PDF für ausgeschriebene Objekte."""

    def test_titel_zimmerwohnung(self):
        from core.services.expose import objekt_titel
        lg, e, m, v = _basis_objekte()
        e.typ = 'whg'; e.zimmer = Decimal('3.5'); e.save()
        self.assertEqual(objekt_titel(e), '3.5-Zimmer-Wohnung')
        e.zimmer = Decimal('4.0'); e.save()
        self.assertEqual(objekt_titel(e), '4-Zimmer-Wohnung')

    def test_expose_pdf_view(self):
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='Verwaltung AG', strasse='Weg 1', plz='8000', ort='Zürich',
                                  telefon='044 000 00 00', email='info@vw.ch')
        lg, e, m, v = _basis_objekte()
        e.typ = 'whg'; e.zimmer = Decimal('3.5'); e.zur_ausschreibung = True
        e.ausschreibung_notiz = 'Helle Wohnung mit Balkon und Seesicht.'
        e.save()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vermarktung/{e.id}/expose/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertGreater(len(r.content), 1200)

    def test_expose_button_in_liste(self):
        lg, e, m, v = _basis_objekte()
        e.zur_ausschreibung = True; e.save()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/vermarktung/')
        self.assertContains(r, f'/neu/vermarktung/{e.id}/expose/')


class BewerberScoringTests(TestCase):
    """Bewerber-Vergleich mit Eignungs-Score (Tragbarkeit/Betreibungen/Anstellung/Doku)."""

    def _bewerbung(self, e, **kw):
        from mietprozess.models import Mietbewerbung
        defaults = dict(
            einheit=e, vorname='Anna', nachname='Muster', geburtsdatum=date(1990, 1, 1),
            mobilnummer='079 000 00 00', email='anna@example.ch', beruf='Kauffrau',
            einkommen_jahr="90'000", erwerbsstatus='angestellt', ist_unbefristet=True,
            hat_betreibungen=False, anzahl_erwachsene=1, status='geprueft')
        defaults.update(kw)
        return Mietbewerbung.objects.create(**defaults)

    def test_parse_einkommen(self):
        from core.services.bewerber_scoring import parse_einkommen
        self.assertEqual(parse_einkommen("90'000"), 90000)
        self.assertEqual(parse_einkommen("80'000 – 100'000"), 80000)   # untere Grenze
        self.assertEqual(parse_einkommen("CHF 72000"), 72000)
        self.assertIsNone(parse_einkommen("keine Angabe"))

    def test_scoring_guter_bewerber(self):
        from core.services.bewerber_scoring import bewerte_bewerbung
        lg, e, m, v = _basis_objekte()   # Brutto 1700/Mt → 20'400/Jahr
        e.betreibungsauszug = 'x.pdf'; e.save()  # egal
        b = self._bewerbung(e, einkommen_jahr="90000")  # 90'000 / 20'400 = 4.4× → gut
        r = bewerte_bewerbung(b, Decimal('1700'))
        self.assertEqual(r['score'], 45 + 25 + 15 + 0)   # keine Dokumente hochgeladen
        self.assertEqual(r['ampel'], 'gut')

    def test_scoring_betreibungen_und_tragbarkeit(self):
        from core.services.bewerber_scoring import bewerte_bewerbung
        lg, e, m, v = _basis_objekte()
        b = self._bewerbung(e, einkommen_jahr="30000", hat_betreibungen=True)  # 30'000/20'400=1.47× → 0 Pkt
        r = bewerte_bewerbung(b, Decimal('1700'))
        # Tragbarkeit 0 + Betreibungen 0 + Anstellung 15 + Doku 0 = 15
        self.assertEqual(r['score'], 15)
        self.assertEqual(r['ampel'], 'schlecht')

    def test_vergleich_view_sortiert_nach_score(self):
        lg, e, m, v = _basis_objekte()
        self._bewerbung(e, vorname='Schwach', einkommen_jahr="28000", hat_betreibungen=True)
        self._bewerbung(e, vorname='Stark', einkommen_jahr="120000")
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vermarktung/{e.id}/bewerber/')
        self.assertEqual(r.status_code, 200)
        namen = [k['b'].vorname for k in r.context['kandidaten']]
        self.assertEqual(namen, ['Stark', 'Schwach'])   # bester zuerst

    def test_abgelehnte_ausgeblendet(self):
        lg, e, m, v = _basis_objekte()
        self._bewerbung(e, vorname='Aktiv')
        self._bewerbung(e, vorname='Weg', status='abgelehnt')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vermarktung/{e.id}/bewerber/')
        self.assertEqual(len(r.context['kandidaten']), 1)
        r2 = c.get(f'/neu/vermarktung/{e.id}/bewerber/?alle=1')
        self.assertEqual(len(r2.context['kandidaten']), 2)


class VerwaltungshonorarTests(TestCase):
    """Verwaltungshonorar: % der Mieterträge, Buchung Soll 4500 / Haben Bank."""

    def _setup(self, prozent='4'):
        from crm.models import Mandant
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        md = Mandant.objects.create(firma_oder_name='Eigentum AG', honorar_prozent=Decimal(prozent))
        lg, e, m, v = _basis_objekte()
        lg.mandant = md
        lg.save()
        # Mietertrag 10'000 im Jahr 2025 (Konto 3000)
        buche('1020', '3000', Decimal('10000'), 'Miete', datum=date(2025, 6, 1), liegenschaft=lg)
        return md, lg

    def test_vorschau_berechnet_honorar(self):
        from core.services.verwaltungshonorar import honorar_vorschau
        md, lg = self._setup('4')
        zeilen, total, prozent = honorar_vorschau(md, 2025)
        self.assertEqual(prozent, Decimal('4.00'))
        self.assertEqual(zeilen[0]['mietertrag'], Decimal('10000.00'))
        self.assertEqual(zeilen[0]['honorar'], Decimal('400.00'))   # 4 % von 10'000
        self.assertFalse(zeilen[0]['gebucht'])
        self.assertEqual(total, Decimal('400.00'))

    def test_buchung_soll_4500_haben_bank(self):
        from core.services.verwaltungshonorar import buche_honorar
        from finance.models import Buchung
        md, lg = self._setup('4')
        anzahl, summe = buche_honorar(md, 2025, user=None)
        self.assertEqual(anzahl, 1)
        self.assertEqual(summe, Decimal('400.00'))
        self.assertTrue(Buchung.objects.filter(soll_konto__nummer='4500', haben_konto__nummer='1020',
                                               betrag=Decimal('400.00'), liegenschaft=lg).exists())

    def test_idempotent(self):
        from core.services.verwaltungshonorar import buche_honorar, honorar_vorschau
        md, lg = self._setup('4')
        buche_honorar(md, 2025, user=None)
        # Zweiter Lauf bucht nichts mehr
        anzahl, summe = buche_honorar(md, 2025, user=None)
        self.assertEqual(anzahl, 0)
        zeilen, _t, _p = honorar_vorschau(md, 2025)
        self.assertTrue(zeilen[0]['gebucht'])

    def test_honorar_mindert_eigentuemer_ergebnis(self):
        from core.services.verwaltungshonorar import buche_honorar
        from core.services.eigentuemer_kontokorrent import kontokorrent
        md, lg = self._setup('4')
        vorher = kontokorrent(md, jahr=2025)['ergebnis']
        buche_honorar(md, 2025, user=None)
        nachher = kontokorrent(md, jahr=2025)['ergebnis']
        # Honorar (400) ist Aufwand → Ergebnis sinkt um 400
        self.assertEqual(vorher - nachher, Decimal('400.00'))

    def test_view_zeigt_honorar_panel(self):
        md, lg = self._setup('4')
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.get(f'/neu/mandate/{md.id}/kontokorrent/?jahr=2025')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Verwaltungshonorar 2025')
        # Buchen-Aktion
        r2 = c.post(f'/neu/mandate/{md.id}/honorar/', {'jahr': '2025', 'konto_nummer': '1020'})
        self.assertEqual(r2.status_code, 302)
        from finance.models import Buchung
        self.assertTrue(Buchung.objects.filter(soll_konto__nummer='4500', betrag=Decimal('400.00')).exists())
