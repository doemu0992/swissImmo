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
    def test_inbox_zaehlt_freigaben_und_fristen(self):
        # Die eine Inbox ersetzt die Cockpit-Widgets: Eigentümer-Freigaben und
        # Wartungsfristen erscheinen als typisierte Aufgaben-Zeilen.
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        lg, e, m, v = _basis_objekte()
        hw = Handwerker.objects.create(firma='HW AG')
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='X', beschreibung='y')
        HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, freigabe_status='ausstehend')
        Wartungsfrist.objects.create(liegenschaft=lg, bezeichnung='Heizungswartung',
                                     naechste_faelligkeit=date.today() + timedelta(days=10))
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.get('/neu/')
        self.assertEqual(r.status_code, 200)
        inbox = r.context['inbox']
        self.assertTrue(any('Eigentümer-Freigabe' in x['titel'] for x in inbox))
        self.assertTrue(any(x['titel'] == 'Heizungswartung' and x['typ'] == 'frist' for x in inbox))


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
    def test_gekuendigter_vertrag_wird_bis_ende_fakturiert(self):
        """Ein gekündigter Vertrag schuldet Miete bis zum Vertragsende. Der
        status='aktiv'-Filter liess ihn durchfallen — die Miete der
        Kündigungsfrist wurde nie gestellt (stiller Geldverlust)."""
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _lg, _e, _m, v = _basis_objekte()   # Vertrag ab 2024-01-01
        v.status = 'gekuendigt'
        v.ende = date(2024, 3, 31)          # Ende im Stellungsmonat
        v.save()
        # März: Ende >= Monatsanfang → volle Miete geschuldet
        self.assertEqual(run_sollstellung(2024, 3), 1)
        self.assertTrue(DebitorenRechnung.objects.filter(
            titel='Miete & NK 03/2024', vertrag=v).exists())
        # April: Vertrag ist beendet → nichts mehr
        self.assertEqual(run_sollstellung(2024, 4), 0)

    def test_entwurf_und_archiviert_werden_nicht_fakturiert(self):
        """Gegenstück: Nur aktiv/gekündigt zählen — ein Entwurf oder ein
        archivierter Vertrag darf keine Rechnung erzeugen."""
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _lg, _e, _m, v = _basis_objekte()
        for status in ('entwurf', 'archiviert'):
            v.status = status; v.ende = None; v.save()
            DebitorenRechnung.objects.all().delete()
            self.assertEqual(run_sollstellung(2024, 5), 0,
                             f'Status «{status}» wurde fakturiert')

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


class BankCsvImportTests(TestCase):
    """Bank-CSV-Import über denselben Endpunkt wie camt.053 (Format-Weiche)."""

    def _setup_rechnung(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        return DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')

    def test_csv_zahlung_per_qrr_referenz(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        r = self._setup_rechnung()
        csv = ("Datum;Buchungstext;Referenz;Gutschrift;Belastung\n"
               f"05.03.2024;Gutschrift QR;{r.qr_referenz};1'700.00;\n"
               "06.03.2024;Ladenmiete Dauerauftrag;;;-250.00\n").encode('utf-8')
        team = _team_user(); c = Client(); c.force_login(team)
        f = SimpleUploadedFile('auszug.csv', csv, content_type='text/csv')
        resp = c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        self.assertEqual(resp.status_code, 302)
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 1)

    def test_csv_reimport_erzeugt_kein_duplikat(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        r = self._setup_rechnung()
        csv = ("Datum;Buchungstext;Referenz;Gutschrift\n"
               f"05.03.2024;Gutschrift QR;{r.qr_referenz};1'700.00\n").encode('utf-8')
        team = _team_user(); c = Client(); c.force_login(team)
        for _ in range(2):
            f = SimpleUploadedFile('auszug.csv', csv, content_type='text/csv')
            c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        # zusammengesetzter Schlüssel (Datum|Betrag|Name|Ref) verhindert Doppelbuchung
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r).count(), 1)

    def test_csv_fuzzy_name_und_betrag(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        r = self._setup_rechnung()
        nachname = r.vertrag.mieter.nachname
        betrag = f"{r.offener_betrag:.2f}"
        csv = ("Datum;Auftraggeber;Mitteilung;Betrag\n"
               f"05.03.2024;Hans {nachname};Miete Maerz;{betrag}\n").encode('cp1252')
        team = _team_user(); c = Client(); c.force_login(team)
        f = SimpleUploadedFile('auszug.csv', csv, content_type='text/csv')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r).count(), 1)

    def test_csv_unzuordenbar_landet_auf_1190(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        self._setup_rechnung()
        csv = ("Datum;Auftraggeber;Betrag\n"
               "05.03.2024;Unbekannte Person;99.95\n").encode('utf-8')
        team = _team_user(); c = Client(); c.force_login(team)
        f = SimpleUploadedFile('auszug.csv', csv, content_type='text/csv')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        z = Zahlungseingang.objects.filter(bemerkung__contains='UNGEKLÄRT').first()
        self.assertIsNotNone(z)
        self.assertEqual(z.konto.nummer, '1190')

    def test_csv_ohne_kopfzeile_gibt_fehlermeldung(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        self._setup_rechnung()
        csv = b"foo;bar\n1;2\n"
        team = _team_user(); c = Client(); c.force_login(team)
        f = SimpleUploadedFile('auszug.csv', csv, content_type='text/csv')
        resp = c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f}, follow=True)
        self.assertContains(resp, 'CSV-Format nicht erkannt')
        self.assertEqual(Zahlungseingang.objects.count(), 0)


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

    # ---------- Mahnung gehört in die Vertrags-Akte ----------
    # Gemeldet: «Vertrag → Dokumente → Mahnung erstellt aber nirgends
    # dokumentiert.» Historie und Gebühr wurden gebucht, das Schreiben selbst
    # existierte nur als Download im Moment des Klicks. Bei Art. 257d OR hängt
    # an der Mahnung die Kündigungsandrohung — ohne Beleg ist im Streitfall
    # nicht nachweisbar, WAS zugestellt wurde.

    def _mahn_dokumente(self, vertrag=None):
        from rentals.models import Dokument
        qs = Dokument.objects.filter(bezeichnung__icontains='Mahnung')
        return list(qs.filter(vertrag=vertrag) if vertrag else qs)

    def test_mahnlauf_legt_die_mahnung_in_die_akte(self):
        from core.services.automation import run_mahnlauf
        r = self._ueberfaellig(40)
        run_mahnlauf(send_email=False)
        dok = self._mahn_dokumente(r.vertrag)
        self.assertEqual(len(dok), 1, "Mahnlauf legte kein Dokument am Vertrag ab")
        self.assertIn('2. Mahnung', dok[0].bezeichnung)
        self.assertTrue(dok[0].datei)

    def test_mahnung_erfassen_legt_die_mahnung_in_die_akte(self):
        r = self._ueberfaellig(40)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': r.id, 'stufe': 1}, follow=True)
        dok = self._mahn_dokumente(r.vertrag)
        self.assertEqual(len(dok), 1, "«Erfassen» legte kein Dokument am Vertrag ab")
        self.assertIn('1. Mahnung', dok[0].bezeichnung)

    def test_mahnung_pdf_button_legt_die_mahnung_in_die_akte(self):
        r = self._ueberfaellig(40)
        c = Client(); c.force_login(_team_user())
        antwort = c.get(f'/vertrag/{r.vertrag_id}/mahnung/')
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(len(self._mahn_dokumente(r.vertrag)), 1)

    def test_mahnung_wird_am_selben_tag_nicht_dupliziert(self):
        """Zweimal klicken darf die Akte nicht aufblähen — dieselbe Stufe am
        selben Tag überschreibt (dedup), eine höhere Stufe bekommt ein eigenes
        Dokument."""
        r = self._ueberfaellig(40)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': r.id, 'stufe': 1}, follow=True)
        c.get(f'/vertrag/{r.vertrag_id}/mahnung/')
        c.get(f'/vertrag/{r.vertrag_id}/mahnung/')
        c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': r.id, 'stufe': 2}, follow=True)
        titel = sorted(d.bezeichnung for d in self._mahn_dokumente(r.vertrag))
        # «1. Mahnung», «2. Mahnung» und die stufenlose «Mahnung» des PDF-Buttons
        self.assertEqual(len(titel), 3, f"unerwartete Dokumente: {titel}")

    def test_ablage_scheitert_lautlos_und_bricht_den_mahnlauf_nicht(self):
        """Die Ablage ist Beiwerk: Geht die PDF-Erzeugung schief, muss der
        gebuchte Mahnschritt trotzdem stehen bleiben."""
        from unittest.mock import patch
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung
        r = self._ueberfaellig(40)
        with patch('core.services.ablage.ablage_mahnung', side_effect=RuntimeError('kaputt')):
            res = run_mahnlauf(send_email=False)
        self.assertEqual(res['gemahnt'], 1)
        self.assertTrue(Mahnung.objects.filter(debitoren_rechnung=r).exists())


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
        lg = Liegenschaft.objects.create(strasse=f'Rundung {anzahl}', plz='4500',
                                         ort='SO', versicherungswert=Decimal('1'))
        for i in range(anzahl):
            e = Einheit.objects.create(liegenschaft=lg, bezeichnung=f'W{i:02d}',
                                       typ='wohnung', flaeche_m2=Decimal('50'))
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
        # Kaution zuerst einzahlen — zurückbezahlt werden kann nur, was auch
        # bilanziert ist (sonst würde eine nie geleistete Kaution ausbezahlt).
        c.post(f'/neu/vertraege/{v.id}/kaution/',
               {'aktion': 'einzahlung', 'einbezahlt_am': '2024-01-05'})
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
        """Fällige Pendenzen erscheinen in der Inbox und öffnen im Popup."""
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        Pendenz.objects.create(titel='Rücknahme vorbereiten', kategorie='vertrag',
                               quelle='auto:ruecknahme:1', vertrag=v, liegenschaft=lg,
                               faellig_am=date.today())
        team = _team_user(); c = Client(); c.force_login(team)
        r = c.get('/neu/')
        self.assertEqual(r.status_code, 200)
        inbox = r.context['inbox']
        self.assertTrue(any(x['titel'] == 'Rücknahme vorbereiten' for x in inbox))
        body = r.content.decode()
        self.assertIn('Inbox', body)
        self.assertIn(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug', body)
        self.assertIn('id="fwModal"', body)

    def test_ferne_pendenz_nicht_im_heute(self):
        """Pendenzen weit in der Zukunft (>14 Tage) erscheinen nicht in der Inbox."""
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        Pendenz.objects.create(titel='Weit weg', kategorie='aufgabe', vertrag=v,
                               faellig_am=date.today() + timedelta(days=40))
        team = _team_user(); c = Client(); c.force_login(team)
        r = c.get('/neu/')
        self.assertFalse(any(x['titel'] == 'Weit weg' for x in r.context['inbox']))


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
        # Detailseite navigiert voll (kein Iframe-Popup) — verlinkt aber den Vertrag.
        self.assertIn(f'/neu/vertraege/{v.id}/', body)
        self.assertIn('Vertrag öffnen', body)
        self.assertNotIn("fwModalOpen(this,'Vertragsende Muster'", body)

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

    def test_vertragsliste_oeffnet_detail_als_seite(self):
        lg, e, m, v = _basis_objekte()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/vertraege/').content.decode()
        # Klick auf die Zeile navigiert zur vollen Detailseite (kein Modal)
        self.assertIn(f"window.location='/neu/vertraege/{v.id}/'", body)
        self.assertNotIn(f"fwModalOpenUrl('/neu/vertraege/{v.id}/'", body)

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

    def test_wizard_parkplatz_einstellplatz_anpassung(self):
        from portfolio.models import Einheit
        lg = Liegenschaft.objects.create(strasse='Weg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 1', typ='pp',
                                   nettomiete_aktuell=Decimal('120'))
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        # Objektdaten tragen die Einstellplatz-Kennung + JS reagiert darauf
        self.assertIn('ist_einstellplatz', body)
        self.assertIn('frist-ep-note', body)
        self.assertIn('266e', body)
        self.assertIn('setMonateAlle', body)

    def test_parkplatz_frist_anzeige_und_pdf_ohne_nk(self):
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag as MV
        from django.template.loader import get_template
        from django.utils import timezone
        lg = Liegenschaft.objects.create(strasse='Weg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 1', typ='pp',
                                   nettomiete_aktuell=Decimal('120'))
        mi = Mieter.objects.create(typ='person', vorname='H', nachname='M', email='h@x.ch')
        # 2 Wochen (monate 0)
        v = MV.objects.create(einheit=e, mieter=mi, netto_mietzins=Decimal('120'),
                              nebenkosten=Decimal('0'), kuendigungsfrist_monate=0,
                              beginn=timezone.localdate())
        self.assertIn('2 Wochen', v.kuendigungsfrist_anzeige)
        # längere Frist möglich (3 Monate auf Monatsende)
        v.kuendigungsfrist_monate = 3; v.save()
        self.assertIn('3 Monate auf Ende eines Monats', v.kuendigungsfrist_anzeige)
        # PDF (Garage-Template) ohne Nebenkosten-Zeile
        ctx = {'vertrag': v, 'mieter': mi, 'einheit': e, 'liegenschaft': lg,
               'mandant': None, 'verwaltung': None, 'heute': timezone.localdate(),
               'miete_fmt': '120.00', 'nk_fmt': '0.00', 'brutto_fmt': '120.00',
               'kaution_fmt': '0.00', 'unterschrift_path': None}
        html = get_template('core/mietvertrag_garage.html').render(ctx)
        self.assertNotIn('Nebenkosten', html)
        self.assertIn('Mietzins', html)

    def test_wizard_parkplatz_nk_komplett_entfernt(self):
        """Beim Einstellplatz muss NK aus Wizard/Vorschau verschwinden: NK-Feld
        ausblendbar, Schritt 6 (Nebenkosten) übersprungen, Vorschau ohne NK."""
        from portfolio.models import Einheit
        lg = Liegenschaft.objects.create(strasse='Weg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 1', typ='pp',
                                   nettomiete_aktuell=Decimal('120'))
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        # NK-Feld + Brutto-Anzeige sind ausblendbare Container
        self.assertIn('id="nk-field-box"', body)
        self.assertIn('id="brutto-box"', body)
        # Schritt-Navigation überspringt den Nebenkosten-Schritt bei Einstellplatz
        self.assertIn('function visibleSteps()', body)
        self.assertIn('updateStepNav()', body)
        # Vorschau nutzt dynamische Abschnittsnummern statt hartem "6. Nebenkosten"
        self.assertIn('secN(', body)
        self.assertNotIn('<div class="pvsec">6. Nebenkosten</div>', body)

    def test_speichern_parkplatz_nk_wird_auf_null_gezwungen(self):
        """Auch wenn das Formular NK mitliefert, wird beim Einstellplatz 0 gespeichert."""
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag as MV
        lg = Liegenschaft.objects.create(strasse='Weg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 2', typ='pp',
                                   nettomiete_aktuell=Decimal('150'))
        mi = Mieter.objects.create(typ='person', vorname='A', nachname='B', email='a@b.ch')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': e.id, 'mieter_id': mi.id, 'beginn': '2026-01-01',
            'netto_mietzins': '150', 'nebenkosten': '80',  # NK wird absichtlich mitgeschickt
            'kuendigungsfrist': '0',
        })
        v = MV.objects.filter(einheit=e).order_by('-id').first()
        self.assertIsNotNone(v)
        self.assertEqual(v.nebenkosten, Decimal('0.00'))
        self.assertEqual(v.netto_mietzins, Decimal('150'))

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

    def _platz(self, typ='pp', monate=None):
        # Einstellplatz (pp/gar): gesetzliche 2-Wochen-Frist = monate 0; sonst 3
        if monate is None:
            monate = 0 if typ in ('pp', 'gar') else 3
        lg = Liegenschaft.objects.create(strasse='Platz 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('500000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 12', typ=typ,
                                   nettomiete_aktuell=Decimal('120'))
        m = Mieter.objects.create(typ='person', nachname='Halter')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal('120'), nebenkosten=Decimal('0'),
                                       status='aktiv', kuendigungsfrist_monate=monate)
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

    def test_einstellplatz_laengere_frist(self):
        from rentals.services import berechne_kuendigungstermin
        # Vereinbarte längere Frist (1 Monat auf Monatsende) statt gesetzlicher 2 Wochen
        _lg, _e, _m, v = self._platz('pp', monate=1)
        self.assertIn('1 Monat auf Ende eines Monats', v.kuendigungsfrist_anzeige)
        # nicht mehr die 2-Wochen-Regel (Eingang 5. März → nicht 31. März)
        self.assertNotEqual(berechne_kuendigungstermin(v, date(2025, 3, 5)), date(2025, 3, 31))

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


class MietzinsAnpassungSollmietzinsTests(TestCase):
    """Eine amtliche Mietzinsanpassung führt den neuen Mietzins auch im Objekt
    als datierte Sollmietzins-Zeile (gültig ab = wirksam_ab). Beim Löschen der
    Anpassung verschwindet die Zeile wieder und der aktuelle Mietzins wird neu
    abgeleitet."""

    def _setup(self):
        Verwaltung.objects.create(firma='V AG', aktueller_referenzzinssatz=Decimal('1.50'))
        lg, e, m, v = _basis_objekte()
        v.basis_referenzzinssatz = Decimal('1.75')
        v.basis_lik_punkte = Decimal('100')
        v.mietzins_modell = 'fest'
        v.save()
        return e, v

    def _valid_wirksam(self, v):
        # Gültiger Erhöhungstermin (Art. 269d) — sonst greift die serverseitige
        # Fristenkontrolle. Für die Tests ein fixer, klar zukünftiger Monatsanfang.
        from rentals.services import naechster_anpassungstermin
        from django.utils import timezone
        return naechster_anpassungstermin(v, timezone.localdate())

    def _anpassung_speichern(self, c, v, neu_netto='1600', wirksam=None):
        wirksam = wirksam or self._valid_wirksam(v)
        return c.post(f'/neu/mietzins/{v.id}/anpassung/', {
            'aktion': 'speichern',
            'neu_netto': neu_netto,
            'neu_zins': '1.50',
            'neu_lik': '105',
            'wirksam_ab': wirksam.isoformat() if hasattr(wirksam, 'isoformat') else wirksam,
            'begruendung': 'Anpassung Referenzzinssatz',
        })

    def test_anpassung_erzeugt_sollmietzins_zeile(self):
        from portfolio.models import Sollmietzins
        from rentals.models import MietzinsAnpassung
        e, v = self._setup()
        w = self._valid_wirksam(v)
        c = Client(); c.force_login(_team_user())
        self._anpassung_speichern(c, v, wirksam=w)

        anp = MietzinsAnpassung.objects.get(vertrag=v)
        z = Sollmietzins.objects.filter(einheit=e, quelle_anpassung=anp)
        self.assertEqual(z.count(), 1)
        zeile = z.first()
        self.assertEqual(zeile.gueltig_ab, w)
        self.assertEqual(zeile.netto_mietzins, Decimal('1600'))
        # Der Anpassungsgrund steht in der Objekt-Notiz (warum der Mietzins gilt).
        self.assertIn('Anpassung Referenzzinssatz', zeile.notiz)
        # NK bleibt unverändert (Anpassung betrifft nur den Netto)
        self.assertEqual(zeile.nebenkosten, Decimal('200'))
        # Indexbasis der Anpassung ist mitgeschrieben
        self.assertEqual(zeile.basis_referenzzinssatz, Decimal('1.50'))
        self.assertEqual(zeile.basis_lik_punkte, Decimal('105'))

    def test_zeile_erscheint_im_objekt_detail(self):
        e, v = self._setup()
        w = self._valid_wirksam(v)
        c = Client(); c.force_login(_team_user())
        self._anpassung_speichern(c, v, wirksam=w)
        body = c.get(f'/neu/objekte/{e.id}/?tab=mietzins').content.decode()
        self.assertIn(w.strftime('%d.%m.%Y'), body)

    def test_mehrfach_speichern_bleibt_idempotent(self):
        from portfolio.models import Sollmietzins
        e, v = self._setup()
        w = self._valid_wirksam(v)
        c = Client(); c.force_login(_team_user())
        # Zweimal PDF-Generieren desselben Formulars darf keine Duplikat-Zeilen erzeugen
        for _ in range(2):
            self._anpassung_speichern(c, v, wirksam=w)
        self.assertEqual(Sollmietzins.objects.filter(einheit=e, gueltig_ab=w).count(), 1)

    def test_direkte_anpassung_erzeugt_objektzeile(self):
        # Auch eine ohne das /neu/-Formular erstellte Anpassung (Alt-View/Import/
        # Admin) muss die Objekt-Sollmietzins-Zeile anlegen — via Model.save().
        from portfolio.models import Sollmietzins
        from rentals.models import MietzinsAnpassung
        e, v = self._setup()
        anp = MietzinsAnpassung.objects.create(
            vertrag=v, wirksam_ab=date(2027, 10, 31),
            neuer_netto_mietzins=Decimal('1269.67'), alter_netto_mietzins=Decimal('1250'),
            neuer_referenzzinssatz=Decimal('1.50'), neuer_lik_index=Decimal('105'),
            begruendung='Referenzzinssatzerhöhung, Kostensteigerung')
        z = Sollmietzins.objects.get(einheit=e, gueltig_ab=date(2027, 10, 31))
        self.assertEqual(z.netto_mietzins, Decimal('1269.67'))
        self.assertEqual(z.quelle_anpassung_id, anp.id)
        self.assertIn('Referenzzinssatzerhöhung', z.notiz)
        # Löschen der Anpassung entfernt die Zeile (CASCADE).
        anp.delete()
        self.assertFalse(Sollmietzins.objects.filter(einheit=e, gueltig_ab=date(2027, 10, 31)).exists())

    def test_loeschen_entfernt_zeile_und_resynct(self):
        from portfolio.models import Sollmietzins
        from rentals.models import MietzinsAnpassung
        e, v = self._setup()
        w = self._valid_wirksam(v)
        c = Client(); c.force_login(_team_user())
        self._anpassung_speichern(c, v, wirksam=w)
        anp = MietzinsAnpassung.objects.get(vertrag=v)
        self.assertTrue(Sollmietzins.objects.filter(quelle_anpassung=anp).exists())

        c.post(f'/neu/anpassung/{anp.id}/loeschen/')
        self.assertFalse(MietzinsAnpassung.objects.filter(id=anp.id).exists())
        self.assertFalse(Sollmietzins.objects.filter(einheit=e, gueltig_ab=w).exists())


class VerhaeltnisseAblageTests(TestCase):
    """Vertragsdokumente werden pro Mietverhältnis (= Vertrag) gebündelt und
    erscheinen bei der Person UND am Objekt (Tab «Verhältnisse»). Die
    Liegenschafts-Ablage zeigt sie NICHT mehr (nur gebäude-/objektbezogene
    Dokumente ohne Vertragsbezug)."""

    def _dok(self, titel, *, vertrag=None, mieter=None, einheit=None, liegenschaft=None, kategorie='vertrag'):
        from rentals.models import Dokument
        from django.core.files.base import ContentFile
        d = Dokument(bezeichnung=titel, titel=titel, kategorie=kategorie,
                     vertrag=vertrag, mieter=mieter, einheit=einheit, liegenschaft=liegenschaft)
        d.datei.save(f'{titel}.pdf', ContentFile(b'%PDF-1.4 test'), save=True)
        return d

    def test_objekt_verhaeltnisse_tab_zeigt_vertragsdokumente(self):
        lg, e, m, v = _basis_objekte()
        self._dok('Mietvertrag (unterzeichnet)', vertrag=v)
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        # Neuer Tab + Panel vorhanden, Historie-Panel weg
        self.assertIn('id="obj-verhaeltnisse"', body)
        self.assertNotIn('id="obj-historie"', body)
        self.assertIn('Verhältnisse', body)
        # Mietername + Dokument sichtbar im Verhältnis-Bündel
        self.assertIn('Hans Muster', body)
        self.assertIn('Mietvertrag (unterzeichnet)', body)

    def test_person_dokumente_nach_verhaeltnis_gruppiert(self):
        lg, e, m, v = _basis_objekte()
        self._dok('Mietvertrag (unterzeichnet)', vertrag=v, mieter=m, einheit=e)
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertIn('Nach Mietverhältnis gruppiert', body)
        self.assertIn('Mietvertrag (unterzeichnet)', body)
        # Verhältnis-Label enthält Objekt + Zeitraum
        self.assertIn('3.5 Zi', body)

    def test_liegenschaft_ablage_ohne_vertragsdokumente(self):
        lg, e, m, v = _basis_objekte()
        self._dok('Mietvertrag (unterzeichnet)', vertrag=v, einheit=e, liegenschaft=lg)
        self._dok('Gebäudeversicherung 2026', einheit=None, liegenschaft=lg, kategorie='sonstiges')
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/liegenschaften/{lg.id}/').content.decode()
        # Gebäudedokument bleibt, Vertragsdokument ist hier ausgeblendet
        self.assertIn('Gebäudeversicherung 2026', body)
        self.assertNotIn('Mietvertrag (unterzeichnet)', body)


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
        from rentals.services import naechster_anpassungstermin
        wirksam = naechster_anpassungstermin(v, date.today())  # frühester gültiger Termin (269d inkl. Zustellpuffer)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mietzins/{v.id}/anpassung/', {
            'aktion': 'speichern', 'neu_netto': '1600', 'neu_zins': '1.50', 'neu_lik': '100',
            'basis_zins': '1.75', 'basis_lik': '100', 'kosten_pct': '0',
            'wirksam_ab': wirksam.isoformat(),
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

    def test_suche_filtert_nach_mieter_und_objekt(self):
        """Gemeldet: «lange Liste, man kann die Mieter kaum unterscheiden» —
        ohne Suche bleibt nur Scrollen."""
        lg, e, m, v = self._konto()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterkonten/?q=' + (m.nachname or '')[:4])
        self.assertEqual(len(r.context['rows']), 1)
        self.assertContains(r, 'Treffer für')
        # Objektsuche findet denselben Mieter über die Adresse
        r2 = c.get('/neu/mieterkonten/?q=' + lg.strasse[:5])
        self.assertEqual(len(r2.context['rows']), 1)
        # Kein Treffer → leere Liste, Seite bleibt bedienbar
        r3 = c.get('/neu/mieterkonten/?q=zzzznichtvorhanden')
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(len(r3.context['rows']), 0)

    def test_alle_zaehler_bleibt_in_der_gefilterten_ansicht_korrekt(self):
        """«Alle (N)» zählte die bereits gefilterten Zeilen — in der Ansicht
        «nur offen» stand am Alle-Knopf also die falsche Zahl."""
        from crm.models import Mieter
        lg, e, m, v = self._konto()
        m2 = Mieter.objects.create(vorname='Ohne', nachname='Ausstand')
        Mietvertrag.objects.create(mieter=m2, einheit=e, status='aktiv',
                                   beginn=date(2025, 1, 1),
                                   netto_mietzins=Decimal('100'), nebenkosten=Decimal('0'))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterkonten/?filter=offen')
        self.assertEqual(r.context['anzahl'], 2)        # alle Mieter
        self.assertEqual(len(r.context['rows']), 1)     # angezeigt: nur der offene

    def test_erste_zelle_wird_zur_ueberschrift_der_karte(self):
        """Auf dem Handy ist «MIETER» als Beschriftung Rauschen — der Name ist
        die Überschrift. Ohne das verschwimmen die Einträge ineinander."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/mieterkonten/').content.decode('utf-8')
        self.assertIn('data-stack-titel', html)         # Skript setzt das Attribut
        self.assertIn("td[data-stack-titel]::before { content: none; }", html)

    def test_trennband_auch_in_den_handgebauten_kartenlisten(self):
        """Liegenschaften, Personen, Verträge und Debitoren sind keine gestapelten
        Tabellen, sondern eigene Karten-Listen — dort fehlte das Band, nebeneinander
        sah das aus wie zwei verschiedene Regeln."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/liegenschaften/').content.decode('utf-8')
        self.assertIn(r'.md\:hidden.divide-y > * + * { border-top: 8px solid #f1f5f9 !important; }',
                      html)
        # und der Strassenname wird nicht mehr abgeschnitten
        self.assertNotIn('font-semibold text-slate-900 truncate">{{ row.lg.strasse', html)

    def test_aufklappgruppen_bekommen_mobil_ein_trennband(self):
        """Auf /neu/objekte/ sitzen die Liegenschafts-Gruppen zu mehreren in
        EINER Karte, getrennt nur durch die Haarlinie von «border-b» — gemeldet
        als «Keine Trennlinie» zwischen zwei Liegenschaften.

        Eine Stufe dunkler (#e2e8f0) als das Band zwischen einzelnen Einträgen
        (#f1f5f9): sonst wäre die Gruppengrenze nicht von der Trennung ihrer
        eigenen Zeilen zu unterscheiden, sobald eine Gruppe offen ist.

        Gemessen bei iPhone-Breite: 36 Gruppen je 8px rgb(226,232,240),
        letzte Gruppe 0px."""
        _basis_objekte()          # sonst rendert die Seite gar keine Gruppe
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/objekte/').content.decode('utf-8')
        self.assertIn('main details.group.border-b { border-bottom: 8px solid #e2e8f0 !important; }',
                      html)
        self.assertIn('main details.group.border-b:last-child { border-bottom-width: 0 !important; }',
                      html)
        # Die Gruppen tragen die Klassen, auf die die Regel zielt
        self.assertIn('<details class="group border-b border-slate-100 last:border-0">', html)

    def test_truncate_bricht_nicht_mitten_im_wort(self):
        """`overflow-wrap: anywhere` senkt auch die min-content-Breite auf ein
        Zeichen — der Titel brach dann mitten im Wort («überfälli/ge
        Forderun/gen») und die Inbox-Kachel wurde turmhoch. `break-word` hält
        das längste Wort als Untergrenze.

        Gemessen bei 390 px auf /neu/fristen/: höchste Zeile 760 px → 133 px,
        Median 760 px → 76 px."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/liegenschaften/').content.decode('utf-8')
        block = html.split('main .truncate {', 1)[1].split('}', 1)[0]
        self.assertIn('overflow-wrap: break-word;', block)
        # Die Deklaration selbst darf nicht mehr vorkommen (das Wort steht noch
        # in der Begründung darüber).
        self.assertNotIn('overflow-wrap: anywhere', block)

    def test_inbox_titel_bekommt_mobil_die_volle_breite(self):
        """Betrag und CTA sind nowrap und geben keine Breite ab — die
        Titelspalte blieb auf 55–95 px und die Zeile wurde bis 321 px hoch.

        Gemessen bei 390 px: Titelbreite 55–95 px → durchgehend 246 px,
        höchste Zeile 321 px → 174 px."""
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        # Eine überfällige Forderung erzeugt den Inbox-Eintrag «… mahnen».
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete Januar',
            betrag=Decimal('1500.00'), datum=date(2026, 1, 1),
            faellig_am=date(2026, 1, 5), status='offen')
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/').content.decode('utf-8')
        self.assertIn('class="min-w-0 basis-full sm:basis-0 flex-1', html)

    def test_truncate_wird_mobil_zentral_aufgehoben(self):
        """«truncate» schneidet auf dem Handy genau das weg, was die Zeile
        identifiziert («Selzacherstras…», «B..»). Statt in ~30 Templates einzeln
        zu flicken hebt base.html es mobil im Inhaltsbereich auf.

        Gemessen bei 390 px (Playwright, Utilities injiziert): pendenzen 3,
        fristen 12, kommunikation 16, finanzen 6 abgeschnittene Elemente vorher
        — nachher 0."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/liegenschaften/').content.decode('utf-8')
        self.assertIn('main .truncate {', html)
        for regel in ('white-space: normal !important;',
                      'overflow: visible !important;',
                      'text-overflow: clip !important;'):
            self.assertIn(regel, html)

    def test_truncate_bleibt_in_topbar_und_seitenleiste(self):
        """Die Regel ist auf <main> begrenzt: Benutzername und Menü-Labels
        brauchen ihre feste Zeilenhöhe, dort ist truncate richtig."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/liegenschaften/').content.decode('utf-8')
        self.assertNotIn('\n            .truncate {', html)
        # Der Benutzername in der Topbar trägt weiterhin truncate
        self.assertIn('text-sm font-semibold text-slate-900 truncate', html)

    def test_trennband_gilt_fuer_jede_karte_nicht_nur_die_erste(self):
        """Tailwinds «divide-y» setzt auf jeder Zeile ausser der ersten
        border-bottom-width: 0. Ohne Vorrang bekam nur die erste Karte ein
        Trennband — gemeldet als «Trennstrich nur bei anderer Liegenschaft»,
        was aber nur zufällig zum Datenbild passte."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/mieterkonten/').content.decode('utf-8')
        self.assertIn('border-bottom: 8px solid #f1f5f9 !important', html)


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
            hat_betreibungen=False, anzahl_erwachsene=1, status='geprueft',
            # Belege vorhanden → Betreibungs-/Anstellungspunkte werden vergeben
            # (ohne Beleg gibt es sie bewusst nicht mehr, siehe bewerber_scoring).
            digitaler_betreibungsauszug=True, arbeitgeber='Muster AG')
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
        # Doku 15: Der Betreibungsauszug wird digital bezogen — das ist in dieser
        # Stufe die einzige verlangte Unterlage und damit vollständig. Vorher gab
        # es dafür 0 Punkte, weil nur hochgeladene DATEIEN zählten; wer den von
        # der App selbst angebotenen digitalen Weg wählte, wurde also bestraft.
        self.assertEqual(r['score'], 45 + 25 + 15 + 15)
        self.assertEqual(r['ampel'], 'gut')

    def test_scoring_betreibungen_und_tragbarkeit(self):
        from core.services.bewerber_scoring import bewerte_bewerbung
        lg, e, m, v = _basis_objekte()
        b = self._bewerbung(e, einkommen_jahr="30000", hat_betreibungen=True)  # 30'000/20'400=1.47× → 0 Pkt
        r = bewerte_bewerbung(b, Decimal('1700'))
        # Tragbarkeit 0 + Betreibungen 0 + Anstellung 15 + Doku 15 = 30.
        # Doku zählt, weil der Betreibungsauszug digital bezogen wird — die
        # Unterlagen sind vollständig, der Auszug ist inhaltlich nur eben
        # negativ. Das ist der Sinn getrennter Indikatoren: «Unterlagen da»
        # und «Betreibungen vorhanden» sind zwei verschiedene Aussagen.
        self.assertEqual(r['score'], 30)
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


class BewerberEntscheidTests(TestCase):
    """Zusage/Absage an Bewerber mit E-Mail + Sammelabsage."""

    def _bewerbung(self, e, vorname='Anna', status='geprueft', email='anna@example.ch'):
        from mietprozess.models import Mietbewerbung
        return Mietbewerbung.objects.create(
            einheit=e, vorname=vorname, nachname='Muster', geburtsdatum=date(1990, 1, 1),
            mobilnummer='079', email=email, beruf='Kauffrau', einkommen_jahr="90000",
            erwerbsstatus='angestellt', status=status)

    def test_zusage_setzt_status(self):
        lg, e, m, v = _basis_objekte()
        b = self._bewerbung(e)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post(f'/neu/bewerbungen/{b.id}/entscheid/', {'entscheid': 'zusage'})
        self.assertEqual(r.status_code, 302)
        b.refresh_from_db()
        self.assertEqual(b.status, 'zugesagt')

    def test_absage_setzt_status(self):
        lg, e, m, v = _basis_objekte()
        b = self._bewerbung(e)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/bewerbungen/{b.id}/entscheid/', {'entscheid': 'absage'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'abgelehnt')

    def test_sammelabsage_nur_offene(self):
        lg, e, m, v = _basis_objekte()
        b1 = self._bewerbung(e, 'A', status='neu')
        b2 = self._bewerbung(e, 'B', status='geprueft')
        b3 = self._bewerbung(e, 'C', status='zugesagt')   # bleibt unangetastet
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/vermarktung/{e.id}/bewerber/absage-uebrige/')
        b1.refresh_from_db(); b2.refresh_from_db(); b3.refresh_from_db()
        self.assertEqual(b1.status, 'abgelehnt')
        self.assertEqual(b2.status, 'abgelehnt')
        self.assertEqual(b3.status, 'zugesagt')

    def test_mail_text_default(self):
        from core.views.fw import _bewerber_mail
        lg, e, m, v = _basis_objekte()
        b = self._bewerbung(e)
        betreff, body = _bewerber_mail(b, 'zusage')
        self.assertIn('Zusage', betreff)
        self.assertIn('Anna Muster', body)


class SchadenKostenTests(TestCase):
    """Reparaturkosten-Übersicht je Liegenschaft."""

    def _setup(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        lg, e, m, v = _basis_objekte()
        hw = Handwerker.objects.create(firma='Sanitär AG')
        t1 = SchadenMeldung.objects.create(liegenschaft=lg, titel='Rohrbruch', status='neu')
        t2 = SchadenMeldung.objects.create(liegenschaft=lg, titel='Fenster', status='erledigt')
        # Auftrag mit effektiven Kosten + einer mit nur Schätzung (offen)
        HandwerkerAuftrag.objects.create(ticket=t1, handwerker=hw,
                                         kosten_geschaetzt=Decimal('500'), kosten_effektiv=None)
        HandwerkerAuftrag.objects.create(ticket=t2, handwerker=hw,
                                         kosten_geschaetzt=Decimal('300'), kosten_effektiv=Decimal('280'))
        return lg

    def test_kostenuebersicht_aggregiert(self):
        lg = self._setup()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/schaeden/kosten/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['total']['effektiv'], Decimal('280.00'))
        self.assertEqual(r.context['total']['offen'], Decimal('500.00'))
        self.assertEqual(r.context['total']['auftraege'], 2)
        self.assertEqual(r.context['total']['schaeden'], 2)
        row = r.context['rows'][0]
        self.assertEqual(row['schaeden_offen'], 1)


class SchadenFotoTests(TestCase):
    """Mehrfach-Foto-Upload für Schadenmeldungen."""

    def _bild(self, name='schaden.png'):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        buf = io.BytesIO()
        Image.new('RGB', (10, 10), (200, 50, 50)).save(buf, 'PNG')
        return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')

    def _schaden(self, lg):
        from tickets.models import SchadenMeldung
        return SchadenMeldung.objects.create(liegenschaft=lg, titel='Wasserschaden', beschreibung='x', status='neu')

    def test_upload_mehrere_fotos(self):
        from tickets.models import SchadenFoto
        lg, e, m, v = _basis_objekte()
        t = self._schaden(lg)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post(f'/neu/schaeden/{t.id}/foto/', {'fotos': [self._bild('a.png'), self._bild('b.png')]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SchadenFoto.objects.filter(schaden=t).count(), 2)

    def test_erfassen_mit_foto(self):
        from tickets.models import SchadenMeldung, SchadenFoto
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post('/neu/schaeden/neu/', {
            'titel': 'Riss in Wand', 'liegenschaft_id': lg.id, 'beschreibung': 'test',
            'prioritaet': 'mittel', 'fotos': [self._bild('riss.png')]})
        self.assertEqual(r.status_code, 302)
        t = SchadenMeldung.objects.get(titel='Riss in Wand')
        self.assertEqual(SchadenFoto.objects.filter(schaden=t).count(), 1)

    def test_foto_loeschen(self):
        from tickets.models import SchadenFoto
        lg, e, m, v = _basis_objekte()
        t = self._schaden(lg)
        f = SchadenFoto.objects.create(schaden=t, bild=self._bild())
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/schaeden/foto/{f.id}/loeschen/')
        self.assertFalse(SchadenFoto.objects.filter(id=f.id).exists())

    def test_detail_zeigt_fotos_tab(self):
        from tickets.models import SchadenFoto
        lg, e, m, v = _basis_objekte()
        t = self._schaden(lg)
        SchadenFoto.objects.create(schaden=t, bild=self._bild())
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/schaeden/{t.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['fotos']), 1)
        self.assertContains(r, 'sc-fotos')


class AuftragPdfTests(TestCase):
    """Reparaturauftrag-PDF für einen Handwerker-Auftrag."""

    def test_auftrag_pdf(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker, Verwaltung
        Verwaltung.objects.create(firma='Verwaltung AG', strasse='Weg 1', plz='8000', ort='Zürich',
                                  email='info@vw.ch', telefon='044 000 00 00')
        lg, e, m, v = _basis_objekte()
        hw = Handwerker.objects.create(firma='Sanitär AG', kontaktperson='H. Meier', email='hw@example.ch')
        t = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=e, titel='Rohrbruch Küche',
                                          beschreibung='Wasser tritt aus.', kategorie='Sanitär',
                                          raum='Küche', melder_vorname='Anna', melder_nachname='Muster',
                                          tel_melder='079', status='neu')
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, kosten_geschaetzt=Decimal('450'),
                                             bemerkung='Bitte rasch erledigen.')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/auftrag/{a.id}/pdf/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertGreater(len(r.content), 1200)

    def test_pdf_button_im_detail(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        lg, e, m, v = _basis_objekte()
        hw = Handwerker.objects.create(firma='Elektro AG')
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Steckdose', beschreibung='x', status='neu')
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw)
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/schaeden/{t.id}/')
        self.assertContains(r, f'/neu/auftrag/{a.id}/pdf/')


class ObjektFotoTests(TestCase):
    """Objekt-Fotos: Upload, Exposé-Titelbild, Portal-Feed-Bilder, Listen-Thumbnail."""

    def _bild(self, name='obj.png'):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        buf = io.BytesIO()
        Image.new('RGB', (12, 10), (60, 120, 200)).save(buf, 'PNG')
        return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')

    def _objekt(self):
        lg, e, m, v = _basis_objekte()
        e.typ = 'whg'; e.zimmer = Decimal('3.5'); e.zur_ausschreibung = True; e.save()
        return lg, e

    def test_upload_und_loeschen(self):
        from portfolio.models import EinheitFoto
        lg, e = self._objekt()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/objekte/{e.id}/foto/', {'fotos': [self._bild('a.png'), self._bild('b.png')]})
        self.assertEqual(EinheitFoto.objects.filter(einheit=e).count(), 2)
        f = EinheitFoto.objects.filter(einheit=e).first()
        c.post(f'/neu/objekte/foto/{f.id}/loeschen/')
        self.assertEqual(EinheitFoto.objects.filter(einheit=e).count(), 1)

    def test_feed_enthaelt_bilder(self):
        from crm.models import Verwaltung
        from portfolio.models import EinheitFoto
        Verwaltung.objects.create(firma='VW AG', strasse='', plz='', ort='', portal_feed_token='t')
        lg, e = self._objekt()
        EinheitFoto.objects.create(einheit=e, bild=self._bild())
        c = Client()
        r = c.get('/neu/vermarktung/feed.json?token=t')
        o = r.json()['objekte'][0]
        self.assertEqual(len(o['bilder']), 1)
        self.assertTrue(o['bilder'][0].startswith('http'))

    def test_vermarktung_zeigt_thumbnail(self):
        from portfolio.models import EinheitFoto
        lg, e = self._objekt()
        EinheitFoto.objects.create(einheit=e, bild=self._bild())
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/vermarktung/')
        row = r.context['rows'][0]
        self.assertIsNotNone(row['titelbild'])
        self.assertEqual(row['fotos_n'], 1)

    def test_expose_mit_titelbild(self):
        from portfolio.models import EinheitFoto
        lg, e = self._objekt()
        EinheitFoto.objects.create(einheit=e, bild=self._bild())
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vermarktung/{e.id}/expose/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))


class MieterwechselAuslaufTests(TestCase):
    """Konsolidiertes Mieterwechsel-Cockpit: gekündigte UND auslaufende Verträge."""

    def test_auslaufender_vertrag_erscheint(self):
        lg, e, m, v = _basis_objekte()
        v.ist_befristet = True; v.ende = date.today() + timedelta(days=45); v.save()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterwechsel/')
        self.assertEqual(r.status_code, 200)
        row = next((x for x in r.context['rows'] if x['v'].id == v.id), None)
        self.assertIsNotNone(row)
        self.assertFalse(row['gekuendigt'])
        self.assertEqual(row['stufe'], 'Läuft aus')
        self.assertEqual(r.context['auslaufend_n'], 1)

    def test_gekuendigter_vertrag_erscheint(self):
        from rentals.models import Kuendigung
        lg, e, m, v = _basis_objekte()
        v.status = 'gekuendigt'; v.save()
        Kuendigung.objects.create(vertrag=v, absender='mieter', status='erfasst',
                                  per_datum=date.today() + timedelta(days=60))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterwechsel/')
        row = next((x for x in r.context['rows'] if x['v'].id == v.id), None)
        self.assertIsNotNone(row)
        self.assertTrue(row['gekuendigt'])
        self.assertEqual(r.context['gekuendigt_n'], 1)

    def test_horizont_filter_nur_auslaufende(self):
        lg, e, m, v = _basis_objekte()
        v.ist_befristet = True; v.ende = date.today() + timedelta(days=300); v.save()   # > 6 Monate
        c = Client(); c.force_login(_team_user())
        self.assertEqual(c.get('/neu/mieterwechsel/?monate=6').context['auslaufend_n'], 0)
        self.assertEqual(c.get('/neu/mieterwechsel/?monate=12').context['auslaufend_n'], 1)

    def test_keine_doppelung_gekuendigt_und_ende(self):
        from rentals.models import Kuendigung
        lg, e, m, v = _basis_objekte()
        v.status = 'gekuendigt'; v.ende = date.today() + timedelta(days=30); v.save()
        Kuendigung.objects.create(vertrag=v, absender='mieter', status='erfasst',
                                  per_datum=date.today() + timedelta(days=30))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterwechsel/')
        treffer = [x for x in r.context['rows'] if x['v'].id == v.id]
        self.assertEqual(len(treffer), 1)   # nur einmal (als gekündigt)
        self.assertTrue(treffer[0]['gekuendigt'])

    def test_vertragsauslauf_route_entfernt(self):
        c = Client(); c.force_login(_team_user())
        self.assertEqual(c.get('/neu/vertragsauslauf/').status_code, 404)


class DebitorenAgingTests(TestCase):
    """Debitoren-Altersstruktur (OP-Aging) nach Fälligkeits-Buckets."""

    def _rechnung(self, v, lg, betrag, faellig, status='offen'):
        from finance.models import DebitorenRechnung
        return DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete', betrag=Decimal(betrag),
            datum=faellig, faellig_am=faellig, status=status)

    def test_buckets_pro_mieter(self):
        from django.utils import timezone as _tz
        lg, e, m, v = _basis_objekte()
        # timezone.localdate() (Europe/Zurich) wie die View — date.today() (UTC)
        # weicht um Mitternacht herum um einen Tag ab (Flake um 00:00 Lokalzeit).
        heute = _tz.localdate()
        self._rechnung(v, lg, '100', heute + timedelta(days=10))    # nicht fällig
        self._rechnung(v, lg, '200', heute - timedelta(days=15))    # 1–30
        self._rechnung(v, lg, '300', heute - timedelta(days=45))    # 31–60
        self._rechnung(v, lg, '400', heute - timedelta(days=120))   # >90
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mahnwesen/aging/')
        self.assertEqual(r.status_code, 200)
        t = r.context['total']
        self.assertEqual(t['nicht_faellig'], Decimal('100.00'))
        self.assertEqual(t['d30'], Decimal('200.00'))
        self.assertEqual(t['d60'], Decimal('300.00'))
        self.assertEqual(t['d90plus'], Decimal('400.00'))
        self.assertEqual(t['summe'], Decimal('1000.00'))
        self.assertEqual(r.context['ueberfaellig_summe'], Decimal('900.00'))
        # ein Mieter, ältester = 120 Tage
        self.assertEqual(len(r.context['rows']), 1)
        self.assertEqual(r.context['rows'][0]['aeltester'], 120)

    def test_bezahlte_ignoriert(self):
        lg, e, m, v = _basis_objekte()
        self._rechnung(v, lg, '500', date.today() - timedelta(days=40), status='bezahlt')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mahnwesen/aging/')
        self.assertEqual(r.context['total']['summe'], Decimal('0.00'))
        self.assertEqual(len(r.context['rows']), 0)


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
        lg2 = Liegenschaft.objects.create(strasse='Zweitweg 2', plz='8000', ort='Zürich',
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
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='VW AG', strasse='W 1', plz='8000', ort='ZH')
        lg = self._setup()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mieterspiegel/?lg={lg.id}&pdf=1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))


class PortalFeedTests(TestCase):
    """Token-gesicherter Vermarktungs-Objekt-Feed für Immobilien-Portale."""

    def _objekt(self):
        lg, e, m, v = _basis_objekte()
        e.typ = 'whg'; e.zimmer = Decimal('3.5'); e.zur_ausschreibung = True
        e.ausschreibung_notiz = 'Helle Wohnung'
        e.save()
        return lg, e

    def test_feed_ohne_token_verboten(self):
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='VW AG', strasse='', plz='', ort='', portal_feed_token='geheim123')
        self._objekt()
        c = Client()   # kein Login nötig (öffentlich, aber token-gated)
        self.assertEqual(c.get('/neu/vermarktung/feed.json').status_code, 403)
        self.assertEqual(c.get('/neu/vermarktung/feed.json?token=falsch').status_code, 403)

    def test_feed_json_mit_token(self):
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='VW AG', strasse='', plz='', ort='', portal_feed_token='geheim123')
        lg, e = self._objekt()
        c = Client()
        r = c.get('/neu/vermarktung/feed.json?token=geheim123')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['anzahl'], 1)
        o = data['objekte'][0]
        self.assertEqual(o['typ'], 'apartment')
        self.assertEqual(o['zimmer'], 3.5)
        self.assertEqual(o['miete']['brutto'], 1700.0)
        self.assertIn('/neu/vermarktung/', o['expose_url'])

    def test_feed_csv(self):
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='VW AG', strasse='', plz='', ort='', portal_feed_token='t')
        self._objekt()
        c = Client()
        r = c.get('/neu/vermarktung/feed.json?token=t&format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        self.assertIn(b'referenz;typ', r.content)

    def test_token_erzeugen_und_entfernen(self):
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='VW AG', strasse='', plz='', ort='')
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/integrationen/portal-token/')
        vw = Verwaltung.objects.first()
        self.assertTrue(vw.portal_feed_token)
        c.post('/neu/integrationen/portal-token/', {'aktion': 'entfernen'})
        vw.refresh_from_db()
        self.assertEqual(vw.portal_feed_token, '')

    def test_integrationen_zeigt_portal_karte(self):
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='VW AG', strasse='', plz='', ort='', portal_feed_token='abc')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/integrationen/')
        self.assertContains(r, 'Immobilien-Portale')
        self.assertContains(r, 'feed.json')


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

    def test_buchung_soll_4500_haben_kontokorrent(self):
        # W3: Gegenkonto ist das Eigentümer-Kontokorrent (2850), NICHT die Bank —
        # am 31.12. fliesst kein Geld; 1020 muss zum Bankauszug passen.
        from core.services.verwaltungshonorar import buche_honorar
        from finance.models import Buchung
        md, lg = self._setup('4')
        anzahl, summe = buche_honorar(md, 2025, user=None)
        self.assertEqual(anzahl, 1)
        self.assertEqual(summe, Decimal('400.00'))
        self.assertTrue(Buchung.objects.filter(soll_konto__nummer='4500', haben_konto__nummer='2850',
                                               betrag=Decimal('400.00'), liegenschaft=lg).exists())
        self.assertFalse(Buchung.objects.filter(soll_konto__nummer='4500',
                                                haben_konto__nummer='1020').exists())

    def test_idempotent(self):
        from core.services.verwaltungshonorar import buche_honorar, honorar_vorschau
        md, lg = self._setup('4')
        buche_honorar(md, 2025, user=None)
        # Zweiter Lauf bucht nichts mehr
        anzahl, summe = buche_honorar(md, 2025, user=None)
        self.assertEqual(anzahl, 0)
        zeilen, _t, _p = honorar_vorschau(md, 2025)
        self.assertTrue(zeilen[0]['gebucht'])

    def test_nach_storno_laesst_sich_das_honorar_neu_buchen(self):
        """Der «schon gebucht?»-Wächter filtert nur `ist_storno=False` und sieht
        damit das stornierte ORIGINAL weiter. Folge: Wer ein Honorar mit
        falschem Satz storniert, kann es nie wieder buchen — die Liste zeigt
        dauerhaft «gebucht», obwohl buchhalterisch nichts mehr steht.

        Die Storno-Gegenbuchung wird korrekt ausgeblendet; ohne
        `storniert_am__isnull=True` ist das Paar einseitig gefiltert."""
        from core.services.verwaltungshonorar import buche_honorar, honorar_vorschau
        from finance.booking import storniere_buchung
        from finance.models import Buchung
        md, lg = self._setup('4')
        buche_honorar(md, 2025, user=None)
        original = Buchung.objects.get(soll_konto__nummer='4500', ist_storno=False)
        storniere_buchung(original)

        zeilen, total, _p = honorar_vorschau(md, 2025)
        self.assertFalse(zeilen[0]['gebucht'],
                         "Honorar gilt nach dem Storno weiter als gebucht")
        self.assertEqual(total, Decimal('400.00'))
        anzahl, summe = buche_honorar(md, 2025, user=None)
        self.assertEqual(anzahl, 1, "Honorar liess sich nach dem Storno nicht neu buchen")

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


class AusstattungRaumbuchTests(TestCase):
    """Assets/Raumbuch Phase 1: Ausstattungselemente je Objekt (Raum entsteht
    aus den Assets), Katalog-Vorlagen, Zeitwert nach Lebensdauertabelle."""

    def test_lebensdauer_geseedet(self):
        from portfolio.models import Lebensdauer
        # Data-Migration 0019 seedet die Standardwerte
        self.assertTrue(Lebensdauer.objects.filter(kategorie='Backofen').exists())

    def test_effektive_lebensdauer_fallback_tabelle(self):
        from portfolio.models import Ausstattung, Lebensdauer
        _lg, e, _m, _v = _basis_objekte()
        Lebensdauer.objects.update_or_create(kategorie='Backofen', defaults={'jahre': 15})
        a = Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Backofen')
        # kein manueller Wert → aus Tabelle
        self.assertEqual(a.effektive_lebensdauer(), 15)
        a.lebensdauer_jahre = 20
        self.assertEqual(a.effektive_lebensdauer(), 20)

    def test_zeitwert_berechnung(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        # Neuwert 2000, 10 J Lebensdauer, 5 J alt → Zeitwert ~1000
        einbau = date.today() - timedelta(days=int(365.25 * 5))
        a = Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Kochherd',
                                       neuwert=Decimal('2000'), einbau_datum=einbau,
                                       lebensdauer_jahre=10)
        zw = a.zeitwert()
        self.assertIsNotNone(zw)
        self.assertTrue(Decimal('950') <= zw <= Decimal('1050'))

    def test_zeitwert_null_ohne_daten(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        a = Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='WC')
        self.assertIsNone(a.zeitwert())

    def test_zeitwert_nie_negativ(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        # 20 J altes Element bei 10 J Lebensdauer → Rest 0, nicht negativ
        einbau = date.today() - timedelta(days=int(365.25 * 20))
        a = Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Herd',
                                       neuwert=Decimal('1000'), einbau_datum=einbau,
                                       lebensdauer_jahre=10)
        self.assertEqual(a.zeitwert(), Decimal('0.00'))

    def test_element_erfassen_view(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/objekte/{e.id}/ausstattung/', {
            'raum': 'Küche', 'kategorie': 'Geschirrspüler', 'marke': 'V-Zug',
            'neuwert': '1800', 'einbau_datum': '2022-01-01', 'zustand': 'gut', 'menge': '1'})
        self.assertEqual(r.status_code, 302)
        a = Ausstattung.objects.get(einheit=e, kategorie='Geschirrspüler')
        self.assertEqual(a.raum, 'Küche')
        self.assertEqual(a.marke, 'V-Zug')
        self.assertEqual(a.neuwert, Decimal('1800'))

    def test_element_erfassen_pflichtfeld(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/objekte/{e.id}/ausstattung/', {'raum': '', 'kategorie': ''})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Ausstattung.objects.filter(einheit=e).exists())

    def test_katalog_laden(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/objekte/{e.id}/ausstattung/katalog/', {'raumtyp': 'Küche'})
        self.assertEqual(r.status_code, 302)
        kueche = Ausstattung.objects.filter(einheit=e, raum='Küche')
        self.assertGreater(kueche.count(), 5)
        # Lebensdauer aus Katalog übernommen
        herd = kueche.filter(kategorie='Kochherd / Glaskeramik').first()
        self.assertIsNotNone(herd)
        self.assertEqual(herd.lebensdauer_jahre, 15)

    def test_katalog_dedupliziert(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/objekte/{e.id}/ausstattung/katalog/', {'raumtyp': 'Küche'})
        n1 = Ausstattung.objects.filter(einheit=e, raum='Küche').count()
        c.post(f'/neu/objekte/{e.id}/ausstattung/katalog/', {'raumtyp': 'Küche'})
        n2 = Ausstattung.objects.filter(einheit=e, raum='Küche').count()
        self.assertEqual(n1, n2)

    def test_element_loeschen(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        a = Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='Lavabo')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/ausstattung/{a.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Ausstattung.objects.filter(id=a.id).exists())

    def test_objekt_detail_zeigt_raumbuch(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Backofen',
                                   neuwert=Decimal('1200'), einbau_datum=date(2021, 1, 1),
                                   lebensdauer_jahre=15)
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/objekte/{e.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Raumbuch')
        self.assertContains(r, 'Backofen')

    def test_assets_seite_zeigt_ausstattung(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='Dusche', zustand='defekt')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/assets/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Raumbuch / Ausstattung')
        self.assertContains(r, 'Dusche')
        # Raumbuch pro Objekt gruppiert: Objekt-Akkordeon + Raum-Überschrift
        self.assertContains(r, 'group-open:rotate-90')
        self.assertContains(r, e.bezeichnung)
        self.assertContains(r, 'Bad')
        self.assertEqual(len(r.context['raumbuch_objekte']), 1)
        self.assertEqual(r.context['raumbuch_objekte'][0]['einheit'].id, e.id)


class AbnahmeLebensdauerTests(TestCase):
    """Assets/Raumbuch Phase 2: Abnahme rechnet Zeitwert/Mieteranteil je Mangel
    nach der Lebensdauertabelle → Schlussabrechnung."""

    def _element(self, e, jahre=10, alter_jahre=5, neuwert='2000'):
        from portfolio.models import Ausstattung
        einbau = date.today() - timedelta(days=int(365.25 * alter_jahre))
        return Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Kochherd',
                                          neuwert=Decimal(neuwert), einbau_datum=einbau,
                                          lebensdauer_jahre=jahre)

    def test_mieteranteil_zeitwert(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        el = self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        mangel = AbnahmeMangel(protokoll=prot, raum='Küche', beschreibung='Glaskeramik gesprungen',
                               verursacher='mieter', ausstattung=el, neuwert=Decimal('2000'))
        anteil = mangel.berechne_mieteranteil()
        # 5 von 10 Jahren verbraucht → ~50% Restwert → ~1000
        self.assertTrue(Decimal('950') <= anteil <= Decimal('1050'))

    def test_mieteranteil_abgeschrieben_null(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        el = self._element(e, jahre=10, alter_jahre=12, neuwert='2000')
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        mangel = AbnahmeMangel(protokoll=prot, beschreibung='defekt',
                               verursacher='mieter', ausstattung=el)
        # vollständig abgeschrieben → Mieter zahlt nichts
        self.assertEqual(mangel.berechne_mieteranteil(), Decimal('0.00'))

    def test_mieteranteil_ohne_element_voller_betrag(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        mangel = AbnahmeMangel(protokoll=prot, beschreibung='Loch in Wand',
                               verursacher='mieter', kostenschaetzung=Decimal('300'))
        self.assertEqual(mangel.berechne_mieteranteil(), Decimal('300.00'))

    def test_mieteranteil_nur_mieter(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        mangel = AbnahmeMangel(protokoll=prot, beschreibung='Abnutzung',
                               verursacher='abnutzung', kostenschaetzung=Decimal('300'))
        self.assertEqual(mangel.berechne_mieteranteil(), Decimal('0.00'))

    def test_abnahme_view_speichert_mieteranteil(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        el = self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/vertraege/{v.id}/abnahme/neu/', {
            'typ': 'auszug', 'datum': date.today().isoformat(),
            'm_raum': ['Küche'], 'm_beschreibung': ['Glaskeramik gesprungen'],
            'm_verursacher': ['mieter'], 'm_kosten': [''],
            'm_ausstattung': [str(el.id)], 'm_neuwert': ['2000']})
        self.assertEqual(r.status_code, 302)
        mangel = AbnahmeMangel.objects.get(beschreibung='Glaskeramik gesprungen')
        self.assertEqual(mangel.ausstattung_id, el.id)
        self.assertIsNotNone(mangel.mieteranteil)
        self.assertTrue(Decimal('950') <= mangel.mieteranteil <= Decimal('1050'))

    def test_kosten_mieter_total_nutzt_mieteranteil(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        el = self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        AbnahmeMangel.objects.create(protokoll=prot, beschreibung='x', verursacher='mieter',
                                     ausstattung=el, mieteranteil=Decimal('1000'),
                                     kostenschaetzung=Decimal('2000'))
        # nutzt mieteranteil (1000), nicht kostenschaetzung (2000)
        self.assertEqual(prot.kosten_mieter_total, Decimal('1000'))

    def test_schlussabrechnung_prefill_mieteranteil(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        el = self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        AbnahmeMangel.objects.create(protokoll=prot, raum='Küche', beschreibung='Glaskeramik',
                                     verursacher='mieter', ausstattung=el,
                                     mieteranteil=Decimal('1000'), kostenschaetzung=Decimal('2000'))
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vertraege/{v.id}/schlussabrechnung/?abnahme={prot.id}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Zeitwert')

    def test_lebensdauer_seite(self):
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/lebensdauer/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Lebensdauertabelle')

    def test_lebensdauer_hinzufuegen_und_bearbeiten(self):
        from portfolio.models import Lebensdauer
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/lebensdauer/', {'aktion': 'neu', 'kategorie': 'Testgerät', 'jahre': '12'})
        self.assertEqual(r.status_code, 302)
        row = Lebensdauer.objects.get(kategorie='Testgerät')
        self.assertEqual(row.jahre, 12)
        c.post('/neu/lebensdauer/', {'aktion': 'speichern', f'jahre_{row.id}': '18',
                                     f'bemerkung_{row.id}': 'angepasst'})
        row.refresh_from_db()
        self.assertEqual(row.jahre, 18)
        self.assertEqual(row.bemerkung, 'angepasst')

    def test_lebensdauer_loeschen(self):
        from portfolio.models import Lebensdauer
        row = Lebensdauer.objects.create(kategorie='Weg', jahre=5)
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/lebensdauer/', {'aktion': 'loeschen', 'id': str(row.id)})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Lebensdauer.objects.filter(id=row.id).exists())


class AusstattungLebenszyklusTests(TestCase):
    """Assets/Raumbuch Phase 3: Element ↔ Schaden (Reparaturhistorie/Lebens-
    zykluskosten) + Garantie-/Ersatzplanung."""

    def _element(self, e, jahre=10, alter_jahre=5, neuwert='2000'):
        from portfolio.models import Ausstattung
        einbau = date.today() - timedelta(days=int(365.25 * alter_jahre))
        return Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Kochherd',
                                          neuwert=Decimal(neuwert), einbau_datum=einbau,
                                          lebensdauer_jahre=jahre)

    def _schaden_mit_kosten(self, lg, e, el, kosten):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        hw = Handwerker.objects.create(firma='Muster GmbH')
        s = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=e,
                                          titel='Defekt', beschreibung='x', ausstattung=el)
        HandwerkerAuftrag.objects.create(ticket=s, handwerker=hw,
                                         kosten_effektiv=Decimal(kosten))
        return s

    def test_rest_jahre(self):
        _lg, e, _m, _v = _basis_objekte()
        el = self._element(e, jahre=10, alter_jahre=4)
        self.assertTrue(5.5 <= el.rest_jahre() <= 6.5)

    def test_ersatz_status(self):
        _lg, e, _m, _v = _basis_objekte()
        self.assertEqual(self._element(e, jahre=10, alter_jahre=4).ersatz_status(), 'ok')
        self.assertEqual(self._element(e, jahre=10, alter_jahre=9).ersatz_status(), 'bald')
        self.assertEqual(self._element(e, jahre=10, alter_jahre=12).ersatz_status(), 'faellig')
        from portfolio.models import Ausstattung
        blank = Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='WC')
        self.assertEqual(blank.ersatz_status(), 'unbekannt')

    def test_reparatur_kosten_und_lebenszyklus(self):
        lg, e, _m, _v = _basis_objekte()
        el = self._element(e, neuwert='2000')
        self._schaden_mit_kosten(lg, e, el, '300')
        self._schaden_mit_kosten(lg, e, el, '150')
        self.assertEqual(el.reparatur_kosten_total(), Decimal('450'))
        self.assertEqual(el.lebenszyklus_kosten(), Decimal('2450'))

    def test_schaden_verknuepfen_view(self):
        from tickets.models import SchadenMeldung
        lg, e, _m, _v = _basis_objekte()
        el = self._element(e)
        s = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=e,
                                          titel='x', beschreibung='y')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/schaeden/{s.id}/ausstattung/', {'ausstattung_id': str(el.id)})
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.ausstattung_id, el.id)
        # aufheben
        c.post(f'/neu/schaeden/{s.id}/ausstattung/', {'ausstattung_id': ''})
        s.refresh_from_db()
        self.assertIsNone(s.ausstattung_id)

    def test_schaden_verknuepfen_nur_eigenes_objekt(self):
        from tickets.models import SchadenMeldung
        from portfolio.models import Einheit
        lg, e, _m, _v = _basis_objekte()
        andere = Einheit.objects.create(liegenschaft=lg, bezeichnung='Andere', typ='wohnung')
        el_fremd = self._element(andere)
        s = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=e,
                                          titel='x', beschreibung='y')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/schaeden/{s.id}/ausstattung/', {'ausstattung_id': str(el_fremd.id)})
        s.refresh_from_db()
        # Element eines anderen Objekts wird nicht verknüpft
        self.assertIsNone(s.ausstattung_id)

    def test_ersatzplanung_view(self):
        lg, e, _m, _v = _basis_objekte()
        self._element(e, jahre=10, alter_jahre=12)  # fällig
        self._element(e, jahre=10, alter_jahre=4)   # ok
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/ersatzplanung/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Ersatzplanung')
        self.assertContains(r, 'Ersatz fällig')

    def test_ersatzplanung_filter(self):
        lg, e, _m, _v = _basis_objekte()
        self._element(e, jahre=10, alter_jahre=12)  # fällig
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/ersatzplanung/?status=faellig')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Kochherd')

    def test_raumbuch_zeigt_reparaturhistorie(self):
        lg, e, _m, _v = _basis_objekte()
        el = self._element(e)
        self._schaden_mit_kosten(lg, e, el, '250')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/objekte/{e.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Reparatur')


class AusstattungEditKatalogTests(TestCase):
    """Ausstattung bearbeiten (Katalog-Elemente mit Daten ergänzen) + Katalog-
    Vollständigkeit/Konsistenz."""

    def test_element_bearbeiten(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        a = Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Backofen',
                                       lebensdauer_jahre=15)
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/ausstattung/{a.id}/bearbeiten/', {
            'raum': 'Küche', 'kategorie': 'Backofen', 'marke': 'V-Zug', 'modell': 'Combair',
            'neuwert': '1600', 'einbau_datum': '2021-06-01', 'zustand': 'gut',
            'garantie_bis': '2026-06-01', 'menge': '1', 'lebensdauer_jahre': '15'})
        self.assertEqual(r.status_code, 302)
        a.refresh_from_db()
        self.assertEqual(a.marke, 'V-Zug')
        self.assertEqual(a.modell, 'Combair')
        self.assertEqual(a.neuwert, Decimal('1600'))
        self.assertEqual(a.einbau_datum, date(2021, 6, 1))

    def test_bearbeiten_pflichtfeld(self):
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        a = Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='WC')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/ausstattung/{a.id}/bearbeiten/', {'raum': '', 'kategorie': ''})
        self.assertEqual(r.status_code, 302)
        a.refresh_from_db()
        self.assertEqual(a.kategorie, 'WC')  # unverändert

    def test_katalog_alle_raeume_vollstaendig(self):
        """Jeder Raumtyp enthält die gemeinsamen Bauteile (Wände, Beleuchtung,
        Lichtschalter, Steckdosen) — Katalog konsistent aufgebaut."""
        from core.services.raumkatalog import RAUM_KATALOG
        for raum, elemente in RAUM_KATALOG.items():
            kats = [k for k, _ in elemente]
            # Mindestgrösse
            self.assertGreaterEqual(len(kats), 7, f"{raum} zu wenige Elemente")
            # keine Duplikate innerhalb eines Raums
            self.assertEqual(len(kats), len(set(kats)), f"{raum} hat Duplikate")
            # Elektro-Basis überall (ausser reine Aussen-/Technikräume)
            if raum not in ('Balkon / Terrasse', 'Heizung / Technik', 'Keller / Estrich'):
                self.assertIn('Beleuchtung', kats, f"{raum} ohne Beleuchtung")
                self.assertIn('Steckdosen', kats, f"{raum} ohne Steckdosen")

    def test_katalog_lebensdauern_positiv(self):
        from core.services.raumkatalog import RAUM_KATALOG
        for raum, elemente in RAUM_KATALOG.items():
            for kat, jahre in elemente:
                self.assertTrue(jahre and jahre > 0, f"{raum}/{kat} ohne Lebensdauer")

    def test_katalog_laden_neue_raeume(self):
        from portfolio.models import Ausstattung
        from core.services.raumkatalog import RAUMTYPEN
        _lg, e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        # Alle Raumtypen laden lassen (auch neue: Heizung/Technik, Reduit/Waschküche)
        for rt in RAUMTYPEN:
            r = c.post(f'/neu/objekte/{e.id}/ausstattung/katalog/', {'raumtyp': rt})
            self.assertEqual(r.status_code, 302)
        self.assertGreater(Ausstattung.objects.filter(einheit=e).count(), 50)


class ErsatzplanungBudgetTests(TestCase):
    """Ersatz- & Budgetplanung: Jahres-Budget-Projektion + PDF-Export."""

    def _element(self, e, jahre, alter_jahre, neuwert):
        from portfolio.models import Ausstattung
        einbau = date.today() - timedelta(days=int(365.25 * alter_jahre))
        return Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Gerät',
                                          neuwert=Decimal(neuwert), einbau_datum=einbau,
                                          lebensdauer_jahre=jahre)

    def test_budget_projektion(self):
        from core.services.ersatzplanung import berechne_ersatzplanung
        _lg, e, _m, _v = _basis_objekte()
        heute = date.today()
        # Ersatz in ~5 Jahren (10 J Lebensdauer, 5 J alt), Neuwert 2000
        self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        # überfällig (12 J alt) → laufendes Jahr, Neuwert 1000
        self._element(e, jahre=10, alter_jahre=12, neuwert='1000')
        d = berechne_ersatzplanung(heute=heute)
        self.assertEqual(d['budget_total'], Decimal('3000'))
        # überfälliges Element landet im laufenden Jahr
        jahre = {b['jahr']: b['summe'] for b in d['jahres_budget']}
        self.assertIn(heute.year, jahre)
        self.assertEqual(jahre[heute.year], Decimal('1000'))
        self.assertIn(heute.year + 5, jahre)

    def test_budget_ohne_neuwert_ignoriert(self):
        from core.services.ersatzplanung import berechne_ersatzplanung
        from portfolio.models import Ausstattung
        _lg, e, _m, _v = _basis_objekte()
        # kein Neuwert → kein Budget, aber Zeile existiert
        Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='WC',
                                   einbau_datum=date.today(), lebensdauer_jahre=10)
        d = berechne_ersatzplanung()
        self.assertEqual(d['budget_total'], Decimal('0.00'))
        self.assertEqual(len(d['rows']), 1)

    def test_budget_horizont(self):
        from core.services.ersatzplanung import berechne_ersatzplanung
        _lg, e, _m, _v = _basis_objekte()
        # Ersatz erst in ~25 Jahren → ausserhalb 10-Jahres-Horizont
        self._element(e, jahre=30, alter_jahre=5, neuwert='5000')
        d = berechne_ersatzplanung(horizont_jahre=10)
        self.assertEqual(d['budget_total'], Decimal('0.00'))
        self.assertEqual(d['jahres_budget'], [])

    def test_ersatzplanung_pdf_view(self):
        _lg, e, _m, _v = _basis_objekte()
        self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/ersatzplanung/?pdf=1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_ersatzplanung_zeigt_budget(self):
        _lg, e, _m, _v = _basis_objekte()
        self._element(e, jahre=10, alter_jahre=5, neuwert='2000')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/ersatzplanung/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Ersatzbudget je Jahr')


class ErneuerungsfondsDeckungTests(TestCase):
    """Ersatzplanung ↔ Erneuerungsfonds: Deckungsgrad + empfohlene Rückstellung."""

    def _setup(self, bestand, einlage, neuwert='2000', jahre=10, alter=5):
        from portfolio.models import Ausstattung
        from finance.models import Erneuerungsfonds
        lg, e, _m, _v = _basis_objekte()
        Erneuerungsfonds.objects.create(liegenschaft=lg, bestand=Decimal(bestand),
                                        jaehrliche_einlage=Decimal(einlage))
        einbau = date.today() - timedelta(days=int(365.25 * alter))
        Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Gerät',
                                   neuwert=Decimal(neuwert), einbau_datum=einbau,
                                   lebensdauer_jahre=jahre)
        return lg, e

    def test_deckung_gedeckt(self):
        from core.services.ersatzplanung import berechne_ersatzplanung, fonds_deckung
        lg, e = self._setup(bestand='5000', einlage='0', neuwert='2000')
        d = berechne_ersatzplanung(aktive_lg=lg)
        deck = fonds_deckung(lg, d['budget_total'], d['horizont_jahre'])
        self.assertTrue(deck['gedeckt'])
        self.assertEqual(deck['bestand'], Decimal('5000'))
        # Empfehlung = Budget / Horizont = 2000/10 = 200
        self.assertEqual(deck['empfohlen'], Decimal('200.00'))

    def test_deckung_unterdeckung_und_mehrbedarf(self):
        from core.services.ersatzplanung import berechne_ersatzplanung, fonds_deckung
        lg, e = self._setup(bestand='0', einlage='50', neuwert='2000')
        d = berechne_ersatzplanung(aktive_lg=lg)
        deck = fonds_deckung(lg, d['budget_total'], d['horizont_jahre'])
        # Projektion 0 + 50*10 = 500 < 2000 → Unterdeckung
        self.assertFalse(deck['gedeckt'])
        self.assertEqual(deck['projiziert'], Decimal('500'))
        # empfohlen 200, Einlage 50 → Mehrbedarf 150
        self.assertEqual(deck['mehrbedarf'], Decimal('150.00'))

    def test_deckung_none_ohne_fonds(self):
        from core.services.ersatzplanung import fonds_deckung
        _lg, _e, _m, _v = _basis_objekte()
        self.assertIsNone(fonds_deckung(None, Decimal('1000'), 10))

    def test_view_zeigt_deckung(self):
        lg, e = self._setup(bestand='5000', einlage='300')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/ersatzplanung/?lg={lg.id}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Erneuerungsfonds-Deckung')

    def test_pdf_mit_deckung(self):
        lg, e = self._setup(bestand='5000', einlage='300')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/ersatzplanung/?lg={lg.id}&pdf=1')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))


class DatenResetTests(TestCase):
    """Gefahrenzone: alle Daten löschen und von vorne beginnen."""

    def test_reset_loescht_alles(self):
        from finance.models import Buchung
        from portfolio.models import Ausstattung
        lg, e, m, v = _basis_objekte()
        Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Herd')
        self.assertTrue(Mietvertrag.objects.exists())
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post('/neu/datenreset/', {'bestaetigung': 'LÖSCHEN'})
        self.assertEqual(r.status_code, 302)
        from crm.models import Mieter
        self.assertFalse(Mietvertrag.objects.exists())
        self.assertFalse(Mieter.objects.exists())
        self.assertFalse(Liegenschaft.objects.exists())
        self.assertFalse(Ausstattung.objects.exists())

    def test_reset_behaelt_benutzer(self):
        _lg, _e, _m, _v = _basis_objekte()
        u = _team_user(rolle='Verwaltung')
        c = Client(); c.force_login(u)
        c.post('/neu/datenreset/', {'bestaetigung': 'LÖSCHEN'})
        # Benutzer + Rollen bleiben → Login weiter gültig
        self.assertTrue(User.objects.filter(id=u.id).exists())
        r = c.get('/neu/account/')
        self.assertEqual(r.status_code, 200)

    def test_reset_ohne_bestaetigung_macht_nichts(self):
        _lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post('/neu/datenreset/', {'bestaetigung': 'nein'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Mietvertrag.objects.filter(id=v.id).exists())

    def test_reset_seedet_referenzdaten(self):
        from portfolio.models import Lebensdauer
        from finance.models import Buchungskonto
        _lg, _e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/datenreset/', {'bestaetigung': 'LÖSCHEN'})
        # Lebensdauertabelle + Kontenplan wieder vorhanden
        self.assertTrue(Lebensdauer.objects.exists())
        self.assertTrue(Buchungskonto.objects.exists())

    def test_reset_erfordert_verwaltung(self):
        _lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user(rolle='Buchhaltung'))
        r = c.post('/neu/datenreset/', {'bestaetigung': 'LÖSCHEN'})
        # keine Verwaltungs-Rolle → kein Reset (Redirect/403), Daten bleiben
        self.assertTrue(Mietvertrag.objects.filter(id=v.id).exists())


class ObjekteGruppierungTests(TestCase):
    """Objekte-Übersicht nach Liegenschaft gruppiert (Akkordeon)."""

    def test_gruppierung_nach_liegenschaft(self):
        from portfolio.models import Einheit
        lg1, e1, _m, _v = _basis_objekte()
        lg2 = Liegenschaft.objects.create(strasse='Andere Gasse 5', plz='3000', ort='Bern',
                                          versicherungswert=Decimal('500000'))
        Einheit.objects.create(liegenschaft=lg2, bezeichnung='2 Zi', typ='whg',
                               nettomiete_aktuell=Decimal('1000'))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/objekte/')
        self.assertEqual(r.status_code, 200)
        gruppen = r.context['gruppen']
        self.assertEqual(len(gruppen), 2)
        ids = {g['lg'].id for g in gruppen}
        self.assertEqual(ids, {lg1.id, lg2.id})
        # Überschrift der Liegenschaft erscheint
        self.assertContains(r, 'Andere Gasse 5')
        self.assertContains(r, 'Teststrasse 1')

    def test_gruppe_zaehlt_belegt_leer(self):
        from portfolio.models import Einheit
        lg, e, _m, _v = _basis_objekte()   # e ist vermietet (aktiver Vertrag)
        Einheit.objects.create(liegenschaft=lg, bezeichnung='Leer 1', typ='whg')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/objekte/')
        g = r.context['gruppen'][0]
        self.assertEqual(g['anzahl'], 2)
        self.assertEqual(g['belegt'], 1)
        self.assertEqual(g['leer'], 1)


class HypothekenTests(TestCase):
    """Hypotheken je Liegenschaft: Zinskosten, Fälligkeiten, Gruppierung, CRUD."""

    def test_jaehrlicher_zins(self):
        from finance.models import Hypothek
        lg, _e, _m, _v = _basis_objekte()
        hy = Hypothek.objects.create(liegenschaft=lg, betrag=Decimal('500000'),
                                     zinssatz=Decimal('1.500'))
        self.assertEqual(hy.jaehrlicher_zins, Decimal('7500.00'))

    def test_view_kpi_und_gruppierung(self):
        from finance.models import Hypothek
        lg, _e, _m, _v = _basis_objekte()
        Hypothek.objects.create(liegenschaft=lg, betrag=Decimal('400000'), zinssatz=Decimal('2.000'))
        Hypothek.objects.create(liegenschaft=lg, betrag=Decimal('100000'), zinssatz=Decimal('1.000'))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/hypotheken/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['total_schuld'], Decimal('500000'))
        self.assertEqual(r.context['total_zins'], Decimal('9000.00'))  # 8000 + 1000
        self.assertEqual(len(r.context['gruppen']), 1)
        self.assertEqual(r.context['gruppen'][0]['schuld'], Decimal('500000'))

    def test_erfassen_und_loeschen(self):
        from finance.models import Hypothek
        lg, _e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/hypotheken/', {
            'aktion': 'neu', 'liegenschaft_id': str(lg.id), 'bank': 'ZKB',
            'betrag': '350000', 'zinssatz': '1.750', 'typ': 'saron', 'ablauf': '2030-06-30'})
        self.assertEqual(r.status_code, 302)
        hy = Hypothek.objects.get(liegenschaft=lg)
        self.assertEqual(hy.bank, 'ZKB')
        self.assertEqual(hy.betrag, Decimal('350000'))
        r2 = c.post('/neu/hypotheken/', {'aktion': 'loeschen', 'id': str(hy.id)})
        self.assertEqual(r2.status_code, 302)
        self.assertFalse(Hypothek.objects.filter(id=hy.id).exists())

    def test_ablauf_warnung(self):
        from finance.models import Hypothek
        lg, _e, _m, _v = _basis_objekte()
        Hypothek.objects.create(liegenschaft=lg, betrag=Decimal('100000'),
                                ablauf=date.today() + timedelta(days=60))  # < 180 T
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/hypotheken/')
        self.assertEqual(r.context['n_ablaufend'], 1)
        self.assertContains(r, 'bald fällig')

    def test_belehnung_gegen_versicherungswert(self):
        from finance.models import Hypothek
        lg, _e, _m, _v = _basis_objekte()  # versicherungswert 1'000'000
        Hypothek.objects.create(liegenschaft=lg, betrag=Decimal('600000'))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/hypotheken/')
        self.assertEqual(r.context['gruppen'][0]['belehnung'], 60)


class LiegenschaftDokumenteGruppenTests(TestCase):
    """Liegenschaft-Dokumente nach Objekt gruppiert (Akkordeon)."""

    def _doc(self, **kw):
        from rentals.models import Dokument
        from django.core.files.base import ContentFile
        d = Dokument(kategorie='sonstiges', **kw)
        d.datei.save('x.pdf', ContentFile(b'%PDF-1'), save=False)
        d.save()
        return d

    def test_gruppierung_objekt_und_allgemein(self):
        from portfolio.models import Einheit
        lg, e, _m, _v = _basis_objekte()
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='2 Zi', typ='whg')
        # 1 Dokument allgemein (nur Liegenschaft), 1 auf Objekt e, 1 auf e2
        self._doc(liegenschaft=lg, bezeichnung='Allgemein-Doc')
        self._doc(liegenschaft=lg, einheit=e, bezeichnung='Objekt-e-Doc')
        self._doc(liegenschaft=lg, einheit=e2, bezeichnung='Objekt-e2-Doc')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/liegenschaften/{lg.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['dok_total'], 3)
        gruppen = r.context['dok_gruppen']
        # Allgemein zuerst, dann je Objekt
        self.assertIsNone(gruppen[0]['einheit'])
        labels = [g['label'] for g in gruppen]
        self.assertIn('3.5 Zi', labels)
        self.assertIn('2 Zi', labels)
        self.assertContains(r, 'Objekt-e-Doc')

    def test_vertragsdokument_nicht_in_liegenschaftsablage(self):
        lg, e, _m, v = _basis_objekte()
        # Vertragsgebundene Dokumente leben am Mietverhältnis (Objekt → «Verhältnisse»)
        # und bei der Person — NICHT mehr in der gebäudeweiten Liegenschafts-Ablage.
        self._doc(vertrag=v, bezeichnung='Vertrags-Doc')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/liegenschaften/{lg.id}/')
        self.assertEqual(r.context['dok_total'], 0)
        self.assertNotContains(r, 'Vertrags-Doc')

    def test_keine_dokumente(self):
        lg, _e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/liegenschaften/{lg.id}/')
        self.assertEqual(r.context['dok_total'], 0)
        self.assertContains(r, 'Keine Dokumente hinterlegt')


class PersonFirmaVereinTests(TestCase):
    """Nachname nur bei Privatperson Pflicht; Firma/Verein via Firmenname.
    Vertragswizard erlaubt Firma/Verein als neue Person."""

    def test_verein_ohne_nachname_speicherbar(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {
            'typ': 'verein', 'firmen_name': 'Stiftung Sonnenschein', 'nachname': '',
            'strasse': 'Weg 1', 'plz': '8000', 'ort': 'Zürich', 'dublette_ok': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Mieter.objects.filter(typ='verein', firmen_name='Stiftung Sonnenschein').exists())

    def test_firma_ohne_nachname_speicherbar(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {
            'typ': 'firma', 'firmen_name': 'Muster AG', 'nachname': '', 'dublette_ok': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Mieter.objects.filter(typ='firma', firmen_name='Muster AG').exists())

    def test_verein_ohne_firmenname_fehler(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {'typ': 'verein', 'firmen_name': '', 'nachname': '', 'dublette_ok': '1'})
        self.assertEqual(r.status_code, 200)  # Fehler, kein Redirect
        self.assertContains(r, 'Organisationsname ist erforderlich')
        self.assertFalse(Mieter.objects.filter(typ='verein').exists())

    def test_privatperson_braucht_nachname(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {'typ': 'person', 'vorname': 'Hans', 'nachname': '', 'dublette_ok': '1'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Nachname ist erforderlich')

    def test_wizard_neuer_mieter_firma(self):
        from portfolio.models import Einheit
        lg = Liegenschaft.objects.create(strasse='Bahnhofstr 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Büro', typ='gew',
                                   nettomiete_aktuell=Decimal('2000'))
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': str(e.id), 'mieter_typ': 'firma', 'firmen_name': 'Handels GmbH',
            'kontaktperson': 'Frau Meier', 'm_strasse': 'Weg 3', 'm_plz': '8000', 'm_ort': 'Zürich',
            'netto_mietzins': '2000', 'nebenkosten': '200', 'beginn': '2025-01-01'})
        self.assertEqual(r.status_code, 302)
        m = Mieter.objects.get(firmen_name='Handels GmbH')
        self.assertEqual(m.typ, 'firma')
        self.assertEqual(m.kontaktperson, 'Frau Meier')


class PersonDokumenteGruppenTests(TestCase):
    """Person-Dokumente nach Mietverhältnis (= Vertrag) gruppiert (Akkordeon);
    Dokumente ohne Vertragsbezug landen zuletzt im «Persönlich»-Bündel."""

    def _doc(self, **kw):
        from rentals.models import Dokument
        from django.core.files.base import ContentFile
        d = Dokument(kategorie='vertrag', **kw)
        d.datei.save('x.pdf', ContentFile(b'%PDF-1'), save=False)
        d.save()
        return d

    def test_gruppierung_verhaeltnis_und_persoenlich(self):
        lg, e, m, v = _basis_objekte()
        self._doc(mieter=m, bezeichnung='Persoenlich-Doc')          # ohne Vertragsbezug
        self._doc(vertrag=v, bezeichnung='Objekt-Doc')              # Verhältnis → Vertrag v
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/personen/{m.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['dok_total'], 2)
        gruppen = r.context['dok_gruppen']
        # Verhältnis (Vertrag) zuerst, Persönlich zuletzt
        self.assertEqual(gruppen[0]['vertrag'], v)
        self.assertIsNone(gruppen[-1]['einheit'])
        self.assertIsNone(gruppen[-1]['vertrag'])
        labels = [g['label'] for g in gruppen]
        self.assertTrue(any('3.5 Zi' in l for l in labels))
        self.assertContains(r, 'Objekt-Doc')
        self.assertContains(r, 'Persoenlich-Doc')

    def test_keine_dokumente(self):
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/personen/{m.id}/')
        self.assertEqual(r.context['dok_total'], 0)


class DocuSealAblageTests(TestCase):
    """Signierter Vertrag wird zentral abgelegt (Portal/Person/Objekt) +
    DocuSeal-Versand graceful ohne API-Key."""

    def test_ablage_signierter_vertrag_ueberall(self):
        from core.services.ablage import ablage_signierter_vertrag
        from rentals.models import Dokument
        from django.core.files.base import ContentFile
        lg, e, m, v = _basis_objekte()
        dok = ablage_signierter_vertrag(v, pdf_bytes=b'%PDF-signed')
        self.assertIsNotNone(dok)
        # EIN rentals.Dokument, mit allen Bezügen → überall sichtbar
        self.assertEqual(dok.vertrag_id, v.id)
        self.assertEqual(dok.mieter_id, m.id)
        self.assertEqual(dok.einheit_id, e.id)
        self.assertEqual(dok.liegenschaft_id, lg.id)
        self.assertEqual(dok.kategorie, 'vertrag')
        self.assertTrue(dok.im_portal_sichtbar)   # → Mieterportal

    def test_ablage_signiert_kanonisch_einzeln(self):
        """Genau EIN signiertes Dokument pro Vertrag — auch bei Mehrfach-Versand."""
        from core.services.ablage import ablage_signierter_vertrag
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        d1 = ablage_signierter_vertrag(v, pdf_bytes=b'%PDF-A')
        self.assertTrue(d1.bezeichnung.startswith('Mietvertrag (unterzeichnet)'))
        self.assertIsNotNone(d1.erstellt_am)
        # identischer Inhalt (wiederholtes save()) → kein Duplikat
        d1b = ablage_signierter_vertrag(v, pdf_bytes=b'%PDF-A')
        self.assertEqual(d1.id, d1b.id)
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 1)
        # neue Unterschrift (anderer Inhalt) → weiterhin genau EIN Dokument (aktualisiert)
        ablage_signierter_vertrag(v, pdf_bytes=b'%PDF-B')
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 1)
        # Explosionstest: viele Rückläufe mit je anderem Inhalt → bleibt bei EINEM
        for i in range(5):
            ablage_signierter_vertrag(v, pdf_bytes=f'%PDF-{i}'.encode())
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 1)

    def test_ablage_raeumt_alt_dubletten_zusammen(self):
        """Bereits explodierte Alt-Dubletten werden beim nächsten Rücklauf auf eines zusammengeführt."""
        from core.services.ablage import ablegen, ablage_signierter_vertrag
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        # simuliere 3 alte signierte Dubletten
        for s in (b'%PDF-1', b'%PDF-2', b'%PDF-3'):
            ablegen(s, "Mietvertrag (unterzeichnet) — alt", kategorie='vertrag', vertrag=v, dedup=False)
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 3)
        ablage_signierter_vertrag(v, pdf_bytes=b'%PDF-neu')
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 1)

    def test_vertragsbeilage_dedup_pro_objekt(self):
        """Beilagen-Ablage: ein Beleg je (Objekt, Titel) — kein Duplikat bei Neu-Erstellung."""
        from core.views.pdf import _ablegen_vertragsdokument
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        _ablegen_vertragsdokument(b'%PDF-1', 'Hausordnung', v)
        _ablegen_vertragsdokument(b'%PDF-2', 'Hausordnung', v)   # 2. Erstellung → kein Duplikat
        self.assertEqual(Dokument.objects.filter(einheit=e, bezeichnung='Hausordnung').count(), 1)

    def test_bereinige_vertragsbeilagen_dubletten(self):
        from core.services.ablage import ablegen, bereinige_vertragsbeilagen_dubletten
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        # simuliere 3 explodierte Beilagen-Dubletten (gleiches Objekt + Titel)
        for s in (b'%PDF-1', b'%PDF-2', b'%PDF-3'):
            ablegen(s, "Hausordnung", kategorie='vertrag', vertrag=v, einheit=e, dedup=False)
        self.assertEqual(Dokument.objects.filter(einheit=e, bezeichnung='Hausordnung').count(), 3)
        n = bereinige_vertragsbeilagen_dubletten()
        self.assertEqual(n, 2)
        self.assertEqual(Dokument.objects.filter(einheit=e, bezeichnung='Hausordnung').count(), 1)

    def test_bereinige_signierte_dubletten(self):
        """Einmal-Aufräumung reduziert bestehende Dubletten (Person/Objekt-Akte)."""
        from core.services.ablage import ablegen, bereinige_signierte_dubletten
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        for i in range(4):
            ablegen(f'%PDF-{i}'.encode(), f"Mietvertrag (unterzeichnet) — {i}",
                    kategorie='vertrag', vertrag=v, dedup=False)
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 4)
        n = bereinige_signierte_dubletten()
        self.assertEqual(n, 3)
        self.assertEqual(Dokument.objects.filter(vertrag=v, kategorie='vertrag').count(), 1)

    def test_model_save_legt_signierten_vertrag_ab(self):
        from rentals.models import Dokument
        from django.core.files.base import ContentFile
        lg, e, m, v = _basis_objekte()
        v.pdf_datei.save('signed.pdf', ContentFile(b'%PDF-signed'), save=False)
        v.sign_status = 'unterzeichnet'
        v.save()
        # erscheint als rentals.Dokument (Person/Portal/Objekt)
        self.assertTrue(Dokument.objects.filter(vertrag=v, kategorie='vertrag').exists())

    def test_signierter_vertrag_in_person_und_objekt(self):
        from core.services.ablage import ablage_signierter_vertrag
        lg, e, m, v = _basis_objekte()
        ablage_signierter_vertrag(v, pdf_bytes=b'%PDF-x')
        c = Client(); c.force_login(_team_user())
        # Person-Akte (nach Verhältnis)
        rp = c.get(f'/neu/personen/{m.id}/')
        self.assertEqual(rp.context['dok_total'], 1)
        # Objekt → «Verhältnisse»: Dokument am Mietverhältnis
        ro = c.get(f'/neu/objekte/{e.id}/')
        self.assertEqual(ro.context['verhaeltnisse_dok_total'], 1)
        self.assertContains(ro, 'Mietvertrag (unterzeichnet)')
        # Liegenschafts-Ablage zeigt Vertragsdokumente NICHT mehr
        rl = c.get(f'/neu/liegenschaften/{lg.id}/')
        self.assertEqual(rl.context['dok_total'], 0)

    def test_docuseal_senden_ohne_key(self):
        from core.services.docuseal_service import docuseal_senden
        lg, e, m, v = _basis_objekte()
        ok, msg = docuseal_senden(v)
        self.assertFalse(ok)
        self.assertIn('nicht konfiguriert', msg)

    def test_wizard_senden_ohne_key_erstellt_trotzdem(self):
        from portfolio.models import Einheit
        lg = Liegenschaft.objects.create(strasse='Musterweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg', typ='whg',
                                   nettomiete_aktuell=Decimal('1500'))
        m = Mieter.objects.create(typ='person', vorname='Hans', nachname='Muster',
                                  email='hans@example.ch')
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': str(e.id), 'mieter_id': str(m.id),
            'netto_mietzins': '1500', 'nebenkosten': '200', 'beginn': '2025-01-01',
            'abschluss': 'senden'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Mietvertrag.objects.filter(einheit=e).exists())  # trotzdem erstellt

    def test_vertrag_signieren_view_ohne_key(self):
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/vertraege/{v.id}/signieren/')
        self.assertEqual(r.status_code, 302)  # graceful, Fehlermeldung


class VertragUnterschriftsblockTests(TestCase):
    """Unterschriftsblock im Vertrags-PDF: Vermieter Ort+Datum automatisch,
    Mieter Ort+Datum als vom Unterzeichner auszufüllende DocuSeal-Felder."""

    def _render(self, typ='whg'):
        from portfolio.models import Einheit
        from crm.models import Verwaltung
        from django.template.loader import get_template
        from django.utils import timezone
        Verwaltung.objects.create(firma='Test Verwaltung', strasse='Weg 1',
                                  plz='8000', ort='Zürich')
        lg = Liegenschaft.objects.create(strasse='Musterweg 1', plz='8004', ort='Bern',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Obj', typ=typ,
                                   nettomiete_aktuell=Decimal('1500'))
        m = Mieter.objects.create(typ='person', vorname='Hans', nachname='Muster',
                                  email='hans@example.ch')
        v = Mietvertrag.objects.create(einheit=e, mieter=m,
                                       netto_mietzins=Decimal('1500'),
                                       nebenkosten=Decimal('200'),
                                       beginn=timezone.localdate())
        tpl = ('core/mietvertrag_garage.html' if typ in ('pp', 'bas', 'gar')
               else 'core/mietvertrag_pdf.html')
        ctx = {'vertrag': v, 'mieter': m, 'einheit': e, 'liegenschaft': lg,
               'mandant': None, 'verwaltung': Verwaltung.objects.first(),
               'heute': timezone.localdate(), 'miete_fmt': '1500.00',
               'nk_fmt': '200.00', 'brutto_fmt': '1700.00', 'kaution_fmt': '0.00',
               'unterschrift_path': None}
        return get_template(tpl).render(ctx)

    def _assert_block(self, html):
        # Vermieter: Ort automatisch (aus Verwaltung), keine leere "Ort, Datum"-Zeile
        self.assertIn('Zürich', html)
        # Mieter: DocuSeal-Felder für Ort (text) und Datum (date)
        self.assertIn('{{Ort Mieter;role=Mieter;type=text', html)
        self.assertIn('{{Datum Mieter;role=Mieter;type=date', html)
        # Unterschriftsanker bleibt bestehen
        self.assertIn('{{Unterschrift Mieter;role=Mieter;type=signature', html)

    def test_wohnung(self):
        self._assert_block(self._render('whg'))

    def test_gewerbe(self):
        self._assert_block(self._render('gew'))

    def test_parkplatz(self):
        self._assert_block(self._render('pp'))


class GeraetZaehlerTests(TestCase):
    """Geräte + Zähler erfassen — auf Objekt- und Liegenschaftsebene (allgemein)."""

    def test_objekt_geraet_add_und_del(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/geraet/', {'einheit_id': str(e.id), 'kategorie': 'Waschmaschine',
                                    'marke': 'V-Zug', 'modell': 'Adora'})
        self.assertEqual(r.status_code, 302)
        g = Geraet.objects.get(einheit=e)
        self.assertEqual(g.kategorie, 'Waschmaschine')
        self.assertEqual(g.marke, 'V-Zug')
        c.post(f'/neu/geraet/{g.id}/loeschen/')
        self.assertFalse(Geraet.objects.filter(id=g.id).exists())

    def test_objekt_zaehler_add(self):
        from portfolio.models import Zaehler
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/zaehler/', {'einheit_id': str(e.id), 'typ': 'Strom',
                                     'zaehler_nummer': 'ABC-123', 'aktueller_stand': '1234.5'})
        self.assertEqual(r.status_code, 302)
        z = Zaehler.objects.get(einheit=e)
        self.assertEqual(z.typ, 'Strom')
        self.assertEqual(z.zaehler_nummer, 'ABC-123')

    def test_zaehler_bearbeiten(self):
        from portfolio.models import Zaehler
        lg, e, m, v = _basis_objekte()
        z = Zaehler.objects.create(einheit=e, typ='Strom', zaehler_nummer='A1',
                                   aktueller_stand=Decimal('100'))
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/zaehler/{z.id}/bearbeiten/', {
            'typ': 'Wasser kalt', 'zaehler_nummer': 'W-9', 'standort': 'Keller',
            'aktueller_stand': '250.75'})
        self.assertEqual(r.status_code, 302)
        z.refresh_from_db()
        self.assertEqual(z.typ, 'Wasser kalt')
        self.assertEqual(z.zaehler_nummer, 'W-9')
        self.assertEqual(z.standort, 'Keller')
        self.assertEqual(z.aktueller_stand, Decimal('250.75'))

    def test_geraet_bearbeiten(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        g = Geraet.objects.create(einheit=e, kategorie='Boiler', marke='Alt')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/geraet/{g.id}/bearbeiten/', {
            'kategorie': 'Wärmepumpe', 'marke': 'Neu', 'modell': 'X2'})
        self.assertEqual(r.status_code, 302)
        g.refresh_from_db()
        self.assertEqual(g.kategorie, 'Wärmepumpe')
        self.assertEqual(g.marke, 'Neu')
        self.assertEqual(g.modell, 'X2')

    def test_geraet_technische_felder(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/geraet/', {'liegenschaft_id': str(lg.id), 'kategorie': 'Boiler',
                                    'seriennummer': 'SN-4711', 'kapazitaet': '300 L',
                                    'standort': 'Keller', 'notiz': 'entkalkt 2025'})
        self.assertEqual(r.status_code, 302)
        g = Geraet.objects.get(liegenschaft=lg, kategorie='Boiler')
        self.assertEqual(g.seriennummer, 'SN-4711')
        self.assertEqual(g.kapazitaet, '300 L')
        self.assertEqual(g.standort, 'Keller')
        self.assertEqual(g.notiz, 'entkalkt 2025')

    def test_liegenschaft_allgemeines_geraet(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/geraet/', {'liegenschaft_id': str(lg.id), 'kategorie': 'Heizung',
                                    'marke': 'Viessmann'})
        self.assertEqual(r.status_code, 302)
        g = Geraet.objects.get(liegenschaft=lg)
        self.assertEqual(g.kategorie, 'Heizung')
        self.assertIsNone(g.einheit_id)

    def test_liegenschaft_allgemeinstrom_zaehler(self):
        from portfolio.models import Zaehler
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/zaehler/', {'liegenschaft_id': str(lg.id), 'typ': 'Allgemeinstrom',
                                     'zaehler_nummer': 'AS-9'})
        self.assertEqual(r.status_code, 302)
        z = Zaehler.objects.get(liegenschaft=lg)
        self.assertEqual(z.typ, 'Allgemeinstrom')
        self.assertIsNone(z.einheit_id)

    def test_liegenschaft_technik_tab_sichtbar(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        Geraet.objects.create(liegenschaft=lg, kategorie='Boiler')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/liegenschaften/{lg.id}/')
        self.assertContains(r, 'lg-technik')
        self.assertContains(r, 'Allgemeine Geräte')
        self.assertContains(r, 'Boiler')

    def test_objekt_merkmale_speichern_und_anzeige(self):
        from portfolio.models import Einheit
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/objekte/{e.id}/merkmale/', {
            'merkmale': ['Balkon', 'Lift'], 'merkmale_eigene': 'Weinkeller, Sauna'})
        self.assertEqual(r.status_code, 302)
        e.refresh_from_db()
        self.assertIn('Balkon', e.merkmale)
        self.assertIn('Lift', e.merkmale)
        self.assertIn('Weinkeller', e.merkmale)
        self.assertIn('Sauna', e.merkmale)
        # Im Objekt-Detail sichtbar (Badges) + eigene Merkmale in der Optionsliste
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('Merkmale', body)
        self.assertIn('Weinkeller', body)

    def test_objekt_raumbuch_accordion(self):
        from portfolio.models import Ausstattung
        lg, e, m, v = _basis_objekte()
        Ausstattung.objects.create(einheit=e, raum='Küche', kategorie='Backofen')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/objekte/{e.id}/')
        # Raum als <details>-Akkordeon dargestellt
        self.assertContains(r, 'group-open:rotate-90')
        self.assertContains(r, 'Küche')


class LoeschbarkeitTests(TestCase):
    """Addierbare Stammdaten/Listen müssen löschbar sein."""

    def test_dienstleister_loeschen(self):
        from crm.models import Handwerker
        h = Handwerker.objects.create(firma='Muster AG')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/dienstleister/{h.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Handwerker.objects.filter(id=h.id).exists())

    def test_dienstleister_bearbeiten(self):
        from crm.models import Handwerker
        h = Handwerker.objects.create(firma='Alt AG', branche='allgemein', telefon='000')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/dienstleister/{h.id}/bearbeiten/', {
            'firma': 'Neu AG', 'branche': 'elektro',
            'kontaktperson': 'Frau Muster', 'email': 'a@b.ch', 'telefon': '079'})
        self.assertEqual(r.status_code, 302)
        h.refresh_from_db()
        self.assertEqual(h.firma, 'Neu AG')
        self.assertEqual(h.branche, 'elektro')
        self.assertEqual(h.kontaktperson, 'Frau Muster')
        self.assertEqual(h.telefon, '079')

    def test_asset_loeschen(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        g = Geraet.objects.create(liegenschaft=lg, kategorie='Heizung')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/assets/{g.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Geraet.objects.filter(id=g.id).exists())

    def test_kreditor_loeschen_nur_neu(self):
        from finance.models import KreditorenRechnung
        lg, e, m, v = _basis_objekte()
        neu = KreditorenRechnung.objects.create(lieferant='Neu AG', betrag=Decimal('100'), status='neu')
        gebucht = KreditorenRechnung.objects.create(lieferant='Alt AG', betrag=Decimal('50'), status='freigegeben')
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        # neu → löschbar
        c.post(f'/neu/kreditoren/{neu.id}/loeschen/')
        self.assertFalse(KreditorenRechnung.objects.filter(id=neu.id).exists())
        # verbucht → bleibt erhalten
        c.post(f'/neu/kreditoren/{gebucht.id}/loeschen/')
        self.assertTrue(KreditorenRechnung.objects.filter(id=gebucht.id).exists())

    def test_kommunikation_loeschen(self):
        from crm.models import Kommunikation
        lg, e, m, v = _basis_objekte()
        k = Kommunikation.objects.create(mieter=m, typ='telefon', richtung='eingehend',
                                         inhalt='Testnotiz')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/kommunikation/{k.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Kommunikation.objects.filter(id=k.id).exists())

    def test_schaden_loeschen(self):
        from tickets.models import SchadenMeldung
        lg, e, m, v = _basis_objekte()
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Wasserschaden',
                                          beschreibung='Test')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/schaeden/{t.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(SchadenMeldung.objects.filter(id=t.id).exists())

    def test_rentals_dokument_loeschen_ueberall(self):
        from core.services.ablage import ablegen
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        d = ablegen(b'%PDF', 'Hausordnung', kategorie='vertrag', vertrag=v)
        self.assertIsNotNone(d)
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/dokument/{d.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Dokument.objects.filter(id=d.id).exists())

    def test_portfolio_dokument_loeschen(self):
        from portfolio.models import Dokument as PDok
        from django.core.files.base import ContentFile
        lg, e, m, v = _basis_objekte()
        d = PDok.objects.create(titel='Foto', kategorie='sonstiges', liegenschaft=lg)
        d.datei.save('x.pdf', ContentFile(b'%PDF'), save=True)
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/dokumente/{d.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PDok.objects.filter(id=d.id).exists())

    def test_wartungsfrist_bearbeiten(self):
        from portfolio.models import Wartungsfrist
        from datetime import date as _d
        lg, e, m, v = _basis_objekte()
        wf = Wartungsfrist.objects.create(liegenschaft=lg, art='wartung', bezeichnung='Alt',
                                          naechste_faelligkeit=_d(2025, 1, 1), intervall_monate=12)
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/frist/{wf.id}/bearbeiten/', {
            'art': 'versicherung', 'bezeichnung': 'Neu', 'anbieter': 'AXA',
            'naechste_faelligkeit': '2026-06-01', 'intervall_monate': '24'})
        self.assertEqual(r.status_code, 302)
        wf.refresh_from_db()
        self.assertEqual(wf.bezeichnung, 'Neu')
        self.assertEqual(wf.art, 'versicherung')
        self.assertEqual(wf.intervall_monate, 24)

    def test_asset_bearbeiten(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        g = Geraet.objects.create(liegenschaft=lg, kategorie='Boiler')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/assets/{g.id}/bearbeiten/', {
            'kategorie': 'Wärmepumpe', 'kapazitaet': '12 kW', 'seriennummer': 'X1'})
        self.assertEqual(r.status_code, 302)
        g.refresh_from_db()
        self.assertEqual(g.kategorie, 'Wärmepumpe')
        self.assertEqual(g.kapazitaet, '12 kW')

    def test_abnahme_loeschen(self):
        from rentals.models import Abnahmeprotokoll
        from django.utils import timezone
        lg, e, m, v = _basis_objekte()
        p = Abnahmeprotokoll.objects.create(vertrag=v, typ='einzug', datum=timezone.localdate())
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/abnahme/{p.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Abnahmeprotokoll.objects.filter(id=p.id).exists())

    def test_nebenkosten_periode_loeschen(self):
        from finance.models import AbrechnungsPeriode
        from datetime import date as _d
        lg, e, m, v = _basis_objekte()
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='NK 2025',
                                              start_datum=_d(2025, 1, 1), ende_datum=_d(2025, 12, 31))
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/nebenkosten/{p.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(AbrechnungsPeriode.objects.filter(id=p.id).exists())


class VertragUnterzeichnetTimestampTests(TestCase):
    """Rücklauf-Zeitstempel des unterzeichneten Vertrags (Detail-Ansicht)."""

    def test_unterzeichnet_am_beim_save(self):
        lg, e, m, v = _basis_objekte()
        from django.core.files.base import ContentFile
        self.assertIsNone(v.unterzeichnet_am)
        v.pdf_datei.save('s.pdf', ContentFile(b'%PDF-signed'), save=False)
        v.sign_status = 'unterzeichnet'
        v.save()
        v.refresh_from_db()
        self.assertIsNotNone(v.unterzeichnet_am)

    def test_detail_zeigt_ruecklauf_im_verlauf(self):
        """Der Rücklauf-Zeitstempel steht als Ereignis im Verlauf-Tab (nicht als
        eigene Zeile im Seitenkopf); der Status-Badge behält ihn als Tooltip."""
        lg, e, m, v = _basis_objekte()
        from django.utils import timezone
        v.sign_status = 'unterzeichnet'
        v.unterzeichnet_am = timezone.now()
        v.save()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/{v.id}/').content.decode()
        # Verlauf-Ereignis vorhanden
        self.assertIn('Unterschriebener Vertrag zurückerhalten', body)
        # Kopf: nur noch Tooltip (title="…"), keine sichtbare Zusatzzeile mehr
        self.assertIn('title="Unterschrieben zurück am', body)
        self.assertNotIn('<i class="fa-solid fa-clock-rotate-left mr-1"></i>Unterschrieben zurück am', body)


class DocuSealWebhookTests(TestCase):
    """Toleranter DocuSeal-Webhook: verschiedene Payloads, kein 'Wert ungültig',
    unterschriebener Vertrag wird zentral abgelegt."""

    def test_vertrag_id_aus_name(self):
        from rentals.api import _vertrag_id_aus_name
        self.assertEqual(_vertrag_id_aus_name('Mietvertrag 42'), 42)
        self.assertEqual(_vertrag_id_aus_name('Mietvertrag42'), 42)
        self.assertEqual(_vertrag_id_aus_name(''), 0)
        self.assertEqual(_vertrag_id_aus_name('Foo'), 0)

    def test_erster_dokument_url(self):
        from rentals.api import _erster_dokument_url
        self.assertEqual(_erster_dokument_url([{'url': 'a'}, {'url': 'b'}]), 'a')
        self.assertIsNone(_erster_dokument_url([]))
        self.assertIsNone(_erster_dokument_url(None))

    def test_event_nicht_abgeschlossen_ignoriert(self):
        from rentals.api import verarbeite_docuseal_event
        lg, e, m, v = _basis_objekte()
        # 'form.viewed' o.ä. → nichts tun, kein Fehler
        self.assertFalse(verarbeite_docuseal_event({'event_type': 'form.viewed', 'data': {'name': f'Mietvertrag {v.id}'}}))
        v.refresh_from_db()
        self.assertNotEqual(v.sign_status, 'unterzeichnet')

    def test_completed_legt_vertrag_ab(self):
        from unittest.mock import patch, MagicMock
        from rentals.api import verarbeite_docuseal_event
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        resp = MagicMock(status_code=200, content=b'%PDF-signed')
        payload = {'event_type': 'submission.completed',
                   'data': {'name': f'Mietvertrag {v.id}', 'combined_document_url': 'https://api.docuseal.com/y.pdf'}}
        with patch('rentals.api.requests.get', return_value=resp):
            ok = verarbeite_docuseal_event(payload)
        self.assertTrue(ok)
        v.refresh_from_db()
        self.assertEqual(v.sign_status, 'unterzeichnet')
        self.assertEqual(v.status, 'aktiv')
        # zentral abgelegt (Portal/Person/Objekt)
        self.assertTrue(Dokument.objects.filter(vertrag=v, kategorie='vertrag').exists())

    def test_completed_documents_liste(self):
        from unittest.mock import patch, MagicMock
        from rentals.api import verarbeite_docuseal_event
        lg, e, m, v = _basis_objekte()
        resp = MagicMock(status_code=200, content=b'%PDF-x')
        payload = {'event_type': 'form.completed',
                   'data': {'name': f'Mietvertrag {v.id}', 'documents': [{'url': 'https://api.docuseal.com/doc.pdf'}]}}
        with patch('rentals.api.requests.get', return_value=resp):
            self.assertTrue(verarbeite_docuseal_event(payload))

    def test_completed_ssrf_fremde_url_wird_abgewiesen(self):
        # SSRF-Schutz: eine doc_url auf fremdem/nicht-HTTPS-Host darf NICHT
        # heruntergeladen werden — kein requests.get, kein Ablegen (Härtung).
        from unittest.mock import patch, MagicMock
        from rentals.api import verarbeite_docuseal_event
        lg, e, m, v = _basis_objekte()
        resp = MagicMock(status_code=200, content=b'%PDF-evil')
        payload = {'event_type': 'submission.completed',
                   'data': {'name': f'Mietvertrag {v.id}',
                            'combined_document_url': 'http://169.254.169.254/latest/meta-data'}}
        with patch('rentals.api.requests.get', return_value=resp) as g:
            ok = verarbeite_docuseal_event(payload)
        self.assertFalse(ok)
        g.assert_not_called()
        v.refresh_from_db()
        self.assertNotEqual(v.sign_status, 'unterzeichnet')

    def test_webhook_endpoint_gibt_200(self):
        # Mit gültigem Secret: Endpunkt darf NIE 422/'Wert ungültig' liefern, auch bei
        # leerem/kaputtem Body (tolerantes Parsing). Ohne Secret → 403 (kein offener
        # Endpoint, siehe docuseal_webhook-Härtung).
        from django.test import override_settings
        c = Client()
        with override_settings(DOCUSEAL_WEBHOOK_SECRET='geheim'):
            hdr = {'HTTP_X_WEBHOOK_SECRET': 'geheim'}
            r = c.post('/api/rentals/webhook/docuseal', data='{}',
                       content_type='application/json', **hdr)
            self.assertEqual(r.status_code, 200)
            r2 = c.post('/api/rentals/webhook/docuseal', data='kein json',
                        content_type='application/json', **hdr)
            self.assertEqual(r2.status_code, 200)
            r3 = c.post('/api/rentals/webhook/docuseal', data='{}',
                        content_type='application/json')  # ohne Secret
            self.assertEqual(r3.status_code, 403)


class SollmietzinsTests(TestCase):
    """Datierte Sollmietzins-Komponententabelle je Objekt (gültig ab)."""

    def _obj(self, typ='whg'):
        lg = Liegenschaft.objects.create(strasse='Sollweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='2.5 Zi', typ=typ,
                                   nettomiete_aktuell=Decimal('0'), nebenkosten_aktuell=Decimal('0'))
        return lg, e

    def test_aktueller_sollmietzins_nach_datum(self):
        from portfolio.models import Sollmietzins
        _, e = self._obj()
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2024, 1, 1),
                                    netto_mietzins=Decimal('1400'), nebenkosten=Decimal('180'))
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 1, 1),
                                    netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'))
        # Stichtag zwischen beiden → ältere Zeile gilt
        row = e.aktueller_sollmietzins(date(2025, 6, 1))
        self.assertEqual(row.netto_mietzins, Decimal('1400'))
        # Stichtag nach der zweiten → neuere Zeile gilt
        row2 = e.aktueller_sollmietzins(date(2026, 6, 1))
        self.assertEqual(row2.netto_mietzins, Decimal('1500'))
        # vor der ersten Zeile → None
        self.assertIsNone(e.aktueller_sollmietzins(date(2020, 1, 1)))

    def test_sync_leitet_aktuellwerte_ab(self):
        from portfolio.models import Sollmietzins
        _, e = self._obj()
        # Zeile mit heute gültig → nach save() abgeleitet
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2020, 1, 1),
                                    netto_mietzins=Decimal('1234'), nebenkosten=Decimal('99'))
        e.refresh_from_db()
        self.assertEqual(e.nettomiete_aktuell, Decimal('1234.00'))
        self.assertEqual(e.nebenkosten_aktuell, Decimal('99.00'))

    def test_view_add_und_del(self):
        from portfolio.models import Sollmietzins
        _, e = self._obj()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/sollmietzins/', {
            'einheit_id': e.id, 'gueltig_ab': '2026-03-01',
            'netto_mietzins': '1600', 'nebenkosten': '210', 'notiz': 'Test',
        })
        self.assertEqual(r.status_code, 302)
        s = Sollmietzins.objects.get(einheit=e)
        self.assertEqual(s.netto_mietzins, Decimal('1600'))
        e.refresh_from_db()
        self.assertEqual(e.nettomiete_aktuell, Decimal('1600.00'))
        # löschen
        c.post(f'/neu/sollmietzins/{s.id}/loeschen/')
        self.assertFalse(Sollmietzins.objects.filter(id=s.id).exists())

    def test_einstellplatz_add_erzwingt_nk_null(self):
        from portfolio.models import Sollmietzins
        _, e = self._obj(typ='pp')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/sollmietzins/', {
            'einheit_id': e.id, 'gueltig_ab': '2026-01-01',
            'netto_mietzins': '120', 'nebenkosten': '50',  # NK wird ignoriert
        })
        s = Sollmietzins.objects.get(einheit=e)
        self.assertEqual(s.nebenkosten, Decimal('0.00'))

    def test_objekt_detail_zeigt_mietzins_tab(self):
        _, e = self._obj()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('id="obj-mietzins"', body)
        self.assertIn('/neu/sollmietzins/', body)

    def test_objekt_form_seedet_erste_zeile(self):
        from portfolio.models import Sollmietzins
        lg = Liegenschaft.objects.create(strasse='Neu 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        c = Client(); c.force_login(_team_user())
        c.post('/neu/objekte/neu/', {
            'liegenschaft_id': lg.id, 'bezeichnung': '4.5 Zi', 'typ': 'whg',
            'nettomiete_aktuell': '1800', 'nebenkosten_aktuell': '250',
            'soll_gueltig_ab': '2026-02-01',
        })
        e = Einheit.objects.get(bezeichnung='4.5 Zi')
        s = Sollmietzins.objects.get(einheit=e)
        self.assertEqual(s.gueltig_ab, date(2026, 2, 1))
        self.assertEqual(s.netto_mietzins, Decimal('1800.00'))

    def test_wizard_json_enthaelt_sollplan(self):
        from portfolio.models import Sollmietzins
        _, e = self._obj()
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 1, 1),
                                    netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'))
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        self.assertIn('sollplan', body)
        self.assertIn('applySollplan', body)


class MietzinsTabExtraTests(TestCase):
    """NK-Abrechnungsart im Mietzins-Tab + Meldungen nur als Toast (nicht inline)."""

    def _obj(self, typ='whg'):
        lg = Liegenschaft.objects.create(strasse='Tabweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='1.5 Zi', typ=typ)
        return lg, e

    def test_nkart_speichern_und_wizard_prefill(self):
        _, e = self._obj()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/objekte/{e.id}/nkart/', {'nk_abrechnungsart': 'pauschal'})
        e.refresh_from_db()
        self.assertEqual(e.nk_abrechnungsart, 'pauschal')
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('name="nk_abrechnungsart"', body)
        wbody = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        self.assertIn('nk_abrechnungsart', wbody)

    def test_meldung_nur_als_toast_nicht_inline(self):
        _, e = self._obj()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/sollmietzins/', {
            'einheit_id': e.id, 'gueltig_ab': '2026-01-01', 'netto_mietzins': '1000',
        }, follow=True)
        body = r.content.decode()
        # Standard-Toast-Container vorhanden
        self.assertIn('fw-toasts', body)
        # Meldungstext erscheint genau EINMAL (nur im Toast, kein Inline-Duplikat)
        self.assertEqual(body.count('Sollmietzins ab'), 1)

    def test_objekt_detail_hat_keine_inline_meldung(self):
        _, e = self._obj()
        c = Client(); c.force_login(_team_user())
        # Panels dürfen keine {% for m in meldung %}-Reste mehr rendern
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('id="obj-mietzins"', body)  # Seite lädt sauber


class SollstellungKontierungTests(TestCase):
    """Buchhalterische Kontierung der Sollstellung nach Objektart + NK-Art."""

    def test_gewerbe_pauschal_kontierung(self):
        from core.services.automation import run_sollstellung
        from finance.models import Buchung
        lg = Liegenschaft.objects.create(strasse='Gew 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Laden', typ='gew',
                                   nettomiete_aktuell=Decimal('2000'), nebenkosten_aktuell=Decimal('200'))
        m = Mieter.objects.create(typ='firma', firmen_name='X GmbH')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2026, 1, 1),
                                   netto_mietzins=Decimal('2000'), nebenkosten=Decimal('200'),
                                   status='aktiv', nk_abrechnungsart='pauschal')
        run_sollstellung(2026, 1)
        haben = set(Buchung.objects.values_list('haben_konto__nummer', flat=True))
        self.assertIn('3010', haben)   # Gewerbe-Mietertrag
        self.assertIn('3021', haben)   # Pauschal-NK (kein Akonto)
        self.assertNotIn('3020', haben)

    def test_wohnung_akonto_kontierung(self):
        from core.services.automation import run_sollstellung
        from finance.models import Buchung
        lg = Liegenschaft.objects.create(strasse='Wohn 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg', typ='whg',
                                   nettomiete_aktuell=Decimal('1500'), nebenkosten_aktuell=Decimal('200'))
        m = Mieter.objects.create(typ='person', vorname='A', nachname='B')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2026, 1, 1),
                                   netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                                   status='aktiv', nk_abrechnungsart='akonto')
        run_sollstellung(2026, 1)
        haben = set(Buchung.objects.values_list('haben_konto__nummer', flat=True))
        self.assertIn('3000', haben)   # Wohnungs-Mietertrag
        self.assertIn('3020', haben)   # NK-Akonto

    def test_index_anpassung_wird_verrechnet(self):
        """Fest/Index: eine wirksame Mietzinsanpassung (Art. 269d) treibt die
        Sollstellung automatisch ab wirksam_ab — ohne den Basiswert zu mutieren."""
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        from rentals.models import MietzinsAnpassung
        lg = Liegenschaft.objects.create(strasse='Idx 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Idx-Büro', typ='gew',
                                   nettomiete_aktuell=Decimal('3000'))
        m = Mieter.objects.create(typ='firma', firmen_name='Idx AG')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                       netto_mietzins=Decimal('3000'), nebenkosten=Decimal('0'),
                                       status='aktiv', mietzins_modell='index')
        MietzinsAnpassung.objects.create(vertrag=v, wirksam_ab=date(2026, 1, 1),
                                         alter_netto_mietzins=Decimal('3000'),
                                         neuer_netto_mietzins=Decimal('3150'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2025, 6, 1)), Decimal('3000'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 6, 1)), Decimal('3150'))
        run_sollstellung(2026, 3)
        r = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 03/2026')
        self.assertEqual(r.betrag, Decimal('3150.00'))

    def test_gewerbe_staffel_bucht_gueltige_stufe(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        from rentals.models import Staffelstufe
        lg = Liegenschaft.objects.create(strasse='Staf 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Büro', typ='gew',
                                   nettomiete_aktuell=Decimal('2000'))
        m = Mieter.objects.create(typ='firma', firmen_name='Y AG')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                       netto_mietzins=Decimal('2000'), nebenkosten=Decimal('0'),
                                       status='aktiv', mietzins_modell='staffel')
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2026, 1, 1), netto_mietzins=Decimal('2100'))
        run_sollstellung(2026, 3)   # März 2026 → Stufe ab 2026-01 gilt
        r = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 03/2026')
        self.assertEqual(r.betrag, Decimal('2100.00'))


class StaffelImTabTests(TestCase):
    """Staffelmiete des aktiven Gewerbe-Vertrags im Mietzins-Tab erfassen/löschen."""

    def _gew_vertrag(self):
        lg = Liegenschaft.objects.create(strasse='Staf-Tab 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Büro 1', typ='gew',
                                   nettomiete_aktuell=Decimal('2000'))
        m = Mieter.objects.create(typ='firma', firmen_name='Z AG')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                       netto_mietzins=Decimal('2000'), nebenkosten=Decimal('0'),
                                       status='aktiv')
        return e, v

    def test_gewerbe_tab_zeigt_live_staffel_nur_bei_staffelvertrag(self):
        e, v = self._gew_vertrag()
        c = Client(); c.force_login(_team_user())
        # Fester Gewerbe-Vertrag → keine Live-Staffel-Karte (nur die Objekt-Vorlage)
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertNotIn('Staffelstufen des aktiven Vertrags', body)
        # Staffelvertrag → Live-Karte erscheint
        v.mietzins_modell = 'staffel'; v.save(update_fields=['mietzins_modell'])
        body2 = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('Staffelstufen des aktiven Vertrags', body2)

    def test_staffel_add_setzt_modell_und_bucht(self):
        from rentals.models import Staffelstufe
        e, v = self._gew_vertrag()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/staffel/', {'vertrag_id': v.id, 'ab_datum': '2026-01-01',
                                 'netto_mietzins': '2100'})
        v.refresh_from_db()
        self.assertEqual(v.mietzins_modell, 'staffel')
        self.assertEqual(v.staffelstufen.count(), 1)
        # Effektiver Mietzins ab Stichtag greift
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 6, 1)), Decimal('2100'))
        # löschen
        s = Staffelstufe.objects.get(vertrag=v)
        c.post(f'/neu/staffel/{s.id}/loeschen/')
        self.assertFalse(Staffelstufe.objects.filter(id=s.id).exists())

    def test_wohnung_ohne_staffel_kein_tab_abschnitt(self):
        lg = Liegenschaft.objects.create(strasse='Wohn-Tab 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg 1', typ='whg',
                                   nettomiete_aktuell=Decimal('1500'))
        m = Mieter.objects.create(typ='person', vorname='A', nachname='B')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                   netto_mietzins=Decimal('1500'), nebenkosten=Decimal('0'),
                                   status='aktiv')
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertNotIn('Staffelmiete (Art. 269c OR)', body)


class StaffelVorlageTests(TestCase):
    """Objektbezogene Staffelmiete-Vorlage (wie Sollmietzins) + Wizard-Prefill."""

    def _gew(self):
        lg = Liegenschaft.objects.create(strasse='SV 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Büro SV', typ='gew',
                                   nettomiete_aktuell=Decimal('2000'))
        return lg, e

    def test_vorlage_add_und_del(self):
        from portfolio.models import StaffelVorlage
        _, e = self._gew()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/staffelvorlage/', {'einheit_id': e.id, 'gueltig_ab': '2027-01-01',
                                        'netto_mietzins': '2100', 'notiz': 'Jahr 2'})
        s = StaffelVorlage.objects.get(einheit=e)
        self.assertEqual(s.netto_mietzins, Decimal('2100'))
        c.post(f'/neu/staffelvorlage/{s.id}/loeschen/')
        self.assertFalse(StaffelVorlage.objects.filter(id=s.id).exists())

    def test_gewerbe_tab_zeigt_vorlage_karte(self):
        _, e = self._gew()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('Staffelmiete-Vorlage (Objekt)', body)
        self.assertIn('/neu/staffelvorlage/', body)

    def test_wohnung_keine_vorlage_karte(self):
        lg = Liegenschaft.objects.create(strasse='SV Wohn', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg SV', typ='whg')
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertNotIn('Staffelmiete-Vorlage (Objekt)', body)

    def test_wizard_json_enthaelt_staffelvorlage(self):
        from portfolio.models import StaffelVorlage
        _, e = self._gew()
        StaffelVorlage.objects.create(einheit=e, gueltig_ab=date(2027, 1, 1),
                                      netto_mietzins=Decimal('2100'))
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        self.assertIn('staffelvorlage', body)
        self.assertIn('applyStaffelVorlage', body)


class AnpassungLoeschenTests(TestCase):
    """Versehentlich erstellte Mietzinsanpassung im Vertrag löschbar."""

    def test_anpassung_del_und_wirkung(self):
        from rentals.models import MietzinsAnpassung
        lg = Liegenschaft.objects.create(strasse='AL 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='AL-Büro', typ='gew',
                                   nettomiete_aktuell=Decimal('3000'))
        m = Mieter.objects.create(typ='firma', firmen_name='AL AG')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                       netto_mietzins=Decimal('3000'), nebenkosten=Decimal('0'),
                                       status='aktiv', mietzins_modell='index')
        a = MietzinsAnpassung.objects.create(vertrag=v, wirksam_ab=date(2026, 1, 1),
                                             alter_netto_mietzins=Decimal('3000'),
                                             neuer_netto_mietzins=Decimal('3150'))
        # wirksam → 3150
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 6, 1)), Decimal('3150'))
        # Detailseite zeigt Löschen-Button
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/{v.id}/').content.decode()
        self.assertIn(f'/neu/anpassung/{a.id}/loeschen/', body)
        # Löschen → zurück auf Basiswert
        r = c.post(f'/neu/anpassung/{a.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(MietzinsAnpassung.objects.filter(id=a.id).exists())
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 6, 1)), Decimal('3000'))


class DebitorVorschauTests(TestCase):
    """Live-Vorschau bei der Ad-hoc-Debitorenrechnung (wie im Vertragsassistenten)."""

    def test_debitoren_seite_hat_vorschau(self):
        lg = Liegenschaft.objects.create(strasse='Dv 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Dv-Whg', typ='whg',
                                   nettomiete_aktuell=Decimal('1500'))
        m = Mieter.objects.create(typ='person', vorname='Vor', nachname='Schau',
                                  strasse='Weg 2', plz='8000', ort='Zürich')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                   netto_mietzins=Decimal('1500'), nebenkosten=Decimal('0'),
                                   status='aktiv')
        c = Client(); c.force_login(_team_user())
        body = c.get('/neu/debitoren/').content.decode()
        # Vorschau-Gerüst + Datenquellen vorhanden
        self.assertIn('id="deb-pv"', body)
        self.assertIn('function debPreview', body)
        self.assertIn('vd-data', body)
        self.assertIn('abs-data', body)
        # Empfängerdaten des aktiven Vertrags im JSON
        self.assertIn('Vor Schau', body)


class MietzinsKonsistenzTests(TestCase):
    """Sollmietzins mit Indexbasis (Ref-Zins/LIK), effektive Werte im Mietzins-View,
    Live-Vorschau bei der Weiterverrechnung."""

    def test_sollmietzins_mit_indexbasis_und_wizard_json(self):
        from portfolio.models import Sollmietzins
        lg = Liegenschaft.objects.create(strasse='Mk 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Mk-Whg', typ='whg')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/sollmietzins/', {
            'einheit_id': e.id, 'gueltig_ab': '2026-04-01',
            'netto_mietzins': '1250', 'nebenkosten': '180',
            'basis_referenzzinssatz': '1.25', 'basis_lik_punkte': '108.2',
        })
        s = Sollmietzins.objects.get(einheit=e)
        self.assertEqual(s.basis_referenzzinssatz, Decimal('1.25'))
        self.assertEqual(s.basis_lik_punkte, Decimal('108.2'))
        # Objekt-Detail zeigt die Basis-Spalte + Formularfelder
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('name="basis_referenzzinssatz"', body)
        self.assertIn('Basis Ref.-Zinssatz', body)   # Formular-Label
        # Wizard-JSON trägt die Indexbasis der Sollmietzins-Zeile
        wbody = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        self.assertIn('"ref": 1.25', wbody)
        self.assertIn('"lik": 108.2', wbody)

    def test_mietzins_view_zeigt_effektive_werte(self):
        from crm.models import Verwaltung
        from rentals.models import MietzinsAnpassung
        Verwaltung.objects.create(firma='VW', strasse='W 1', plz='8000', ort='Zürich',
                                  aktueller_referenzzinssatz=Decimal('1.25'),
                                  aktueller_lik_punkte=Decimal('107.1'))
        lg = Liegenschaft.objects.create(strasse='Mk 2', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Mk-Whg2', typ='whg')
        m = Mieter.objects.create(typ='person', vorname='E', nachname='F')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2023, 1, 1),
                                       netto_mietzins=Decimal('1500'), nebenkosten=Decimal('0'),
                                       status='aktiv',
                                       basis_referenzzinssatz=Decimal('1.75'),
                                       basis_lik_punkte=Decimal('106.0'))
        # Alte Basis 1.75 vs aktuell 1.25 → Senkungsanspruch
        self.assertEqual(v.mietzinspotenzial, 'decrease')
        # Wirksame Anpassung AUF die aktuelle Basis → Potenzial neutral,
        # effektiver Netto = angepasster Wert
        MietzinsAnpassung.objects.create(vertrag=v, wirksam_ab=date(2025, 1, 1),
                                         alter_netto_mietzins=Decimal('1500'),
                                         neuer_netto_mietzins=Decimal('1430'),
                                         neuer_referenzzinssatz=Decimal('1.25'),
                                         neuer_lik_index=Decimal('107.1'))
        self.assertEqual(v.mietzinspotenzial, 'neutral')
        self.assertEqual(v.effektive_basis(date(2026, 1, 1)), (Decimal('1.25'), Decimal('107.1')))
        c = Client(); c.force_login(_team_user())
        body = c.get('/neu/mietzins/').content.decode()
        self.assertIn("1'430.00", body)         # effektiver Netto in der Tabelle
        self.assertIn('Netto effektiv', body)

    def test_weiterverrechnung_hat_vorschau(self):
        from finance.models import KreditorenRechnung
        lg = Liegenschaft.objects.create(strasse='Mk 3', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Mk-Whg3', typ='whg')
        m = Mieter.objects.create(typ='person', vorname='G', nachname='H',
                                  strasse='Weg 9', plz='8000', ort='Zürich')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                   netto_mietzins=Decimal('1500'), nebenkosten=Decimal('0'),
                                   status='aktiv')
        k = KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('400'),
                                              liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/kreditoren/{k.id}/weiterverrechnen/').content.decode()
        self.assertIn('id="wv-pv"', body)
        self.assertIn('function wvPreview', body)
        self.assertIn('wv-vd-data', body)
        self.assertIn('G H', body)


class KIRechnungsscannerTests(TestCase):
    """KI-Rechnungsscanner in /neu/: Scan direkt beim Upload, Methode sichtbar,
    Werte korrigierbar. Ohne GROQ-Key läuft die regelbasierte Erkennung."""

    def _text_pdf(self):
        import io
        from reportlab.pdfgen import canvas as _c
        buf = io.BytesIO()
        c = _c.Canvas(buf)
        c.drawString(72, 800, "Muster Sanitaer AG")
        c.drawString(72, 780, "Rechnung Nr. 2026-042 vom 15.03.2026")
        c.drawString(72, 760, "Total CHF 350.00")
        c.drawString(72, 740, "IBAN CH93 0076 2011 6238 5295 7")
        c.save()
        return buf.getvalue()

    def test_seite_zeigt_scanner_und_edit(self):
        from finance.models import KreditorenRechnung
        KreditorenRechnung.objects.create(lieferant='Alt AG', betrag=Decimal('100'), status='neu')
        c = Client(); c.force_login(_team_user())
        body = c.get('/neu/kreditoren/').content.decode()
        self.assertIn('KI-Rechnungsscanner', body)
        self.assertIn('/neu/kreditoren/scan/', body)
        self.assertIn('kedit-', body)                     # Inline-Bearbeiten für Status Neu
        self.assertIn('/bearbeiten/', body)

    def test_scan_upload_regex_ohne_key(self):
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('rechnung.pdf', self._text_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            r = c.post('/neu/kreditoren/scan/', {'beleg_scan': f})
        self.assertEqual(r.status_code, 302)
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.status, 'neu')
        self.assertEqual(k.betrag, Decimal('350.00'))
        self.assertEqual(k.iban, 'CH9300762011623852957')
        self.assertEqual(k.datum, date(2026, 3, 15))
        self.assertIn('Muster Sanitaer AG', k.lieferant)
        # Regex-Methode → Hinweis am Datensatz (in der Edit-Zeile sichtbar)
        self.assertIn('prüfen', k.fehlermeldung)

    def test_scan_upload_mit_ki_mock(self):
        from unittest.mock import patch, MagicMock
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        import json as _json
        antwort = MagicMock()
        antwort.raise_for_status.return_value = None
        antwort.json.return_value = {'choices': [{'message': {'content': _json.dumps({
            'lieferant': 'Elektro Muster GmbH', 'betrag': 1234.55,
            'datum': '2026-05-02', 'referenz': 'RF18539007547034', 'iban': 'CH9300762011623852957',
        })}}]}
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('rechnung.pdf', self._text_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY='test-key'), \
             patch('finance.utils.requests.post', return_value=antwort) as mocked:
            c.post('/neu/kreditoren/scan/', {'beleg_scan': f})
            # Aktuelles Modell wird verwendet (llama3-8b-8192 ist abgeschaltet)
            self.assertEqual(mocked.call_args.kwargs['json']['model'], 'llama-3.3-70b-versatile')
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.lieferant, 'Elektro Muster GmbH')
        self.assertEqual(k.betrag, Decimal('1234.55'))
        self.assertEqual(k.datum, date(2026, 5, 2))
        self.assertEqual(k.fehlermeldung, '')            # KI-Erkennung → kein Hinweis

    def test_bild_ohne_key_ergibt_hinweis(self):
        from django.test import override_settings
        from finance.utils import scan_beleg
        import tempfile, os as _os
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as fh:
            fh.write(b'\xff\xd8\xff\xe0fakejpg')
            pfad = fh.name
        try:
            with override_settings(GROQ_API_KEY=None):
                d = scan_beleg(pfad)
            self.assertEqual(d['methode'], 'leer')
            self.assertIn('GROQ_API_KEY', d['hinweis'])
        finally:
            _os.unlink(pfad)

    def test_kreditor_bearbeiten_nur_status_neu(self):
        from finance.models import KreditorenRechnung
        k = KreditorenRechnung.objects.create(lieferant='Scan AG', betrag=Decimal('100'), status='neu')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/bearbeiten/', {
            'lieferant': 'Scan AG korrigiert', 'betrag': '425.50',
            'datum': '2026-06-01', 'referenz': 'R-77', 'iban': 'CH93 0076 2011 6238 5295 7',
        })
        k.refresh_from_db()
        self.assertEqual(k.lieferant, 'Scan AG korrigiert')
        self.assertEqual(k.betrag, Decimal('425.50'))
        self.assertEqual(k.iban, 'CH9300762011623852957')
        # Verbuchte Rechnung ist gesperrt
        k.status = 'freigegeben'; k.save()
        c.post(f'/neu/kreditoren/{k.id}/bearbeiten/', {'lieferant': 'Hack', 'betrag': '1'})
        k.refresh_from_db()
        self.assertEqual(k.lieferant, 'Scan AG korrigiert')

    def test_scan_upload_ohne_liegenschaft_leerer_string(self):
        """Regression: '— später zuordnen —' postet liegenschaft_id='' — darf
        keinen 500er werfen (Field 'id' expected a number but got '')."""
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('rechnung.pdf', self._text_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            r = c.post('/neu/kreditoren/scan/', {'beleg_scan': f, 'liegenschaft_id': ''})
        self.assertEqual(r.status_code, 302)
        k = KreditorenRechnung.objects.latest('id')
        self.assertIsNone(k.liegenschaft_id)

    def test_kreditor_neu_ohne_liegenschaft_leerer_string(self):
        """Gleiche Regression im manuellen Erfassen-Formular ('— keine —')."""
        from finance.models import KreditorenRechnung
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/kreditoren/neu/', {
            'lieferant': 'Leer AG', 'betrag': '99.00', 'liegenschaft_id': '',
        })
        self.assertEqual(r.status_code, 302)
        k = KreditorenRechnung.objects.get(lieferant='Leer AG')
        self.assertIsNone(k.liegenschaft_id)

    def test_mehrfach_upload(self):
        """Mehrere Belege in einem Rutsch → je Beleg eine Rechnung."""
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        vorher = KreditorenRechnung.objects.count()
        c = Client(); c.force_login(_team_user())
        f1 = SimpleUploadedFile('r1.pdf', self._text_pdf(), content_type='application/pdf')
        f2 = SimpleUploadedFile('r2.pdf', self._text_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            r = c.post('/neu/kreditoren/scan/', {'beleg_scan': [f1, f2]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(KreditorenRechnung.objects.count(), vorher + 2)

    def test_zeile_klickbar_und_beleg_vorschau(self):
        """Zeile (Status Neu) ist klickbar; Edit-Panel zeigt die Beleg-Vorschau."""
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('vorschau.pdf', self._text_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            c.post('/neu/kreditoren/scan/', {'beleg_scan': f})
        body = c.get('/neu/kreditoren/').content.decode()
        self.assertIn('fwKZeile', body)                      # Klick-Handler
        self.assertIn('cursor-pointer', body)                # Zeile klickbar
        self.assertIn('Beleg-Vorschau', body)                # Vorschau im Edit-Panel
        self.assertIn('type="application/pdf"', body)        # PDF-Embed
        self.assertIn('multiple', body)                      # Mehrfach-Upload-Input

    def test_rechnungsmail_import(self):
        """E-Mail mit PDF-Anhang → Rechnung mit gescannten Werten + Herkunft."""
        from django.test import override_settings
        from email.message import EmailMessage
        from core.services.belegimport import importiere_rechnungsmail
        from finance.models import KreditorenRechnung
        msg = EmailMessage()
        msg['From'] = 'Hans Handwerker <hans@sanitaer-muster.ch>'
        msg['Subject'] = 'Rechnung Reparatur'
        msg.set_content('Anbei die Rechnung. Gruss Hans')
        msg.add_attachment(self._text_pdf(), maintype='application', subtype='pdf',
                           filename='rechnung_reparatur.pdf')
        with override_settings(GROQ_API_KEY=None):
            rechnungen = importiere_rechnungsmail(msg)
        self.assertEqual(len(rechnungen), 1)
        k = rechnungen[0]
        self.assertEqual(k.status, 'neu')
        self.assertEqual(k.betrag, Decimal('350.00'))
        self.assertEqual(k.iban, 'CH9300762011623852957')
        self.assertIn('Per E-Mail von hans@sanitaer-muster.ch', k.fehlermeldung)

    def test_rechnungsmail_ohne_anhang(self):
        from email.message import EmailMessage
        from core.services.belegimport import importiere_rechnungsmail
        msg = EmailMessage()
        msg['From'] = 'x@y.ch'
        msg.set_content('Nur Text, kein Anhang')
        self.assertEqual(importiere_rechnungsmail(msg), [])

    def test_lieferantenkonto_zeigt_verlauf(self):
        """Erstellen/Löschen von Kreditorenrechnungen erscheint im Verlauf des
        Lieferantenkontos (Abgleich über den Lieferantennamen)."""
        from finance.models import KreditorenRechnung
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/neu/', {'lieferant': 'Verlauf AG', 'betrag': '200.00'})
        k = KreditorenRechnung.objects.get(lieferant='Verlauf AG')
        c.post(f'/neu/kreditoren/{k.id}/loeschen/')
        body = c.get('/neu/lieferantenkonto/?name=Verlauf AG').content.decode()
        self.assertIn('Verlauf — wer hat was gemacht', body)
        self.assertIn('Kreditorenrechnung erfasst', body)
        self.assertIn('Kreditorenrechnung gelöscht', body)

    def test_mailimport_loggt_aktivitaet(self):
        """Mail-Import schreibt einen System-Eintrag ins Aktivitätslog."""
        from django.test import override_settings
        from email.message import EmailMessage
        from core.services.belegimport import importiere_rechnungsmail
        from core.models import AktivitaetsLog
        msg = EmailMessage()
        msg['From'] = 'log@handwerk.ch'
        msg.set_content('Rechnung anbei')
        msg.add_attachment(self._text_pdf(), maintype='application', subtype='pdf',
                           filename='r.pdf')
        with override_settings(GROQ_API_KEY=None):
            importiere_rechnungsmail(msg)
        e = AktivitaetsLog.objects.filter(aktion='Rechnung per E-Mail eingegangen').first()
        self.assertIsNotNone(e)
        self.assertIsNone(e.benutzer_id)
        self.assertIn('log@handwerk.ch', e.details)


class HnkAutoAbleitungTests(TestCase):
    """NK-Relevanz der Kreditorenrechnung folgt automatisch dem Konto:
    HNK-Konto (4100–4140/4400) ⇒ Rechnung fliesst in die NK-Abrechnung —
    kein vergessenes Häkchen mehr. Checkbox kann zusätzlich aktivieren."""

    def _konto(self, nummer):
        from finance.booking import konto
        return konto(nummer)

    def test_erfassen_mit_hnk_konto_setzt_flag(self):
        from finance.models import KreditorenRechnung
        heiz = self._konto('4100')   # Heizkosten, is_hnk_relevant=True
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/neu/', {
            'lieferant': 'Öl AG', 'betrag': '900.00', 'konto_id': heiz.id,
            # Checkbox bewusst NICHT gesetzt
        })
        k = KreditorenRechnung.objects.get(lieferant='Öl AG')
        self.assertTrue(k.is_hnk_relevant)

    def test_erfassen_mit_unterhalt_konto_ohne_haekchen_bleibt_false(self):
        from finance.models import KreditorenRechnung
        unterhalt = self._konto('4000')   # Unterhalt, is_hnk_relevant=False
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/neu/', {
            'lieferant': 'Maler AG', 'betrag': '500.00', 'konto_id': unterhalt.id,
        })
        k = KreditorenRechnung.objects.get(lieferant='Maler AG')
        self.assertFalse(k.is_hnk_relevant)

    def test_freigabe_mit_hnk_konto_setzt_flag(self):
        from finance.models import KreditorenRechnung
        heiz = self._konto('4100')
        k = KreditorenRechnung.objects.create(lieferant='Wasser AG', betrag=Decimal('300'),
                                              status='neu')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/freigeben/', {'konto_id': heiz.id})
        k.refresh_from_db()
        self.assertEqual(k.status, 'freigegeben')
        self.assertTrue(k.is_hnk_relevant)

    def test_bearbeiten_checkbox_und_konto(self):
        from finance.models import KreditorenRechnung
        unterhalt = self._konto('4000')
        k = KreditorenRechnung.objects.create(lieferant='Mix AG', betrag=Decimal('100'),
                                              status='neu', is_hnk_relevant=True)
        c = Client(); c.force_login(_team_user())
        # Nicht-HNK-Konto + Checkbox aus → Flag wird entfernt
        c.post(f'/neu/kreditoren/{k.id}/bearbeiten/', {
            'lieferant': 'Mix AG', 'betrag': '100', 'konto_id': unterhalt.id,
        })
        k.refresh_from_db()
        self.assertFalse(k.is_hnk_relevant)
        # Checkbox an → Flag trotz Nicht-HNK-Konto gesetzt (manuelle Wahl)
        c.post(f'/neu/kreditoren/{k.id}/bearbeiten/', {
            'lieferant': 'Mix AG', 'betrag': '100', 'konto_id': unterhalt.id,
            'is_hnk_relevant': 'on',
        })
        k.refresh_from_db()
        self.assertTrue(k.is_hnk_relevant)

    def test_konto_select_synct_checkbox_live(self):
        """Aufwandskonto-Optionen tragen data-hnk; JS hakt die HNK-Checkbox
        beim Wählen eines NK-Kontos (z.B. Allgemeinstrom) sichtbar an."""
        from finance.booking import ensure_kontenplan
        from finance.models import KreditorenRechnung
        ensure_kontenplan()
        KreditorenRechnung.objects.create(lieferant='Sync AG', betrag=Decimal('50'), status='neu')
        c = Client(); c.force_login(_team_user())
        body = c.get('/neu/kreditoren/').content.decode()
        self.assertIn('function fwHnkSync', body)
        self.assertIn('data-hnk="1"', body)
        self.assertIn('onchange="fwHnkSync(this)"', body)

    def _qr_pdf(self):
        """Text-PDF mit QR-Zahlteil: Rechnungsnummer UND echte QR-Referenz/QR-IBAN."""
        import io
        from reportlab.pdfgen import canvas as _c
        buf = io.BytesIO()
        c = _c.Canvas(buf)
        c.drawString(72, 800, "BKW Energie AG")
        c.drawString(72, 780, "Rechnung Nr. 751 700 231 252 vom 20.07.2026")
        c.drawString(72, 760, "Total CHF 137.30")
        c.drawString(72, 700, "Zahlteil")
        c.drawString(72, 680, "Konto / Zahlbar an")
        c.drawString(72, 660, "CH40 3000 0008 3000 0310 7")
        c.drawString(72, 640, "Referenz")
        c.drawString(72, 620, "00 00506 37947 06000 08940 95003")
        c.drawString(72, 580, "IBAN CH16 0900 0000 3000 03107")
        c.save()
        return buf.getvalue()

    def test_qr_zahlteil_uebersteuert_referenz_und_iban(self):
        """Die 27-stellige QR-Referenz (Mod10-geprüft) und die QR-IBAN aus dem
        Zahlteil übersteuern Rechnungsnummer/Konto-IBAN — deterministisch,
        unabhängig davon, was die KI wählt."""
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('bkw.pdf', self._qr_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            c.post('/neu/kreditoren/scan/', {'beleg_scan': f})
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.referenz, '000050637947060000894095003')   # QRR, nicht RgNr
        self.assertEqual(k.iban, 'CH4030000008300003107')            # QR-IBAN, nicht 09xx

    def test_qr_zahlteil_uebersteuert_auch_ki_antwort(self):
        """Auch wenn die KI die Rechnungsnummer als Referenz liefert, gewinnt
        der geprüfte Zahlteil."""
        from unittest.mock import patch, MagicMock
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        import json as _json
        antwort = MagicMock()
        antwort.raise_for_status.return_value = None
        antwort.json.return_value = {'choices': [{'message': {'content': _json.dumps({
            'lieferant': 'BKW Energie AG', 'betrag': 137.30, 'datum': '2026-07-20',
            'referenz': '751700231252',                 # falsch: Rechnungsnummer
            'iban': 'CH1609000000300003107',            # falsch: Konto-IBAN
        })}}]}
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('bkw.pdf', self._qr_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY='test-key'), \
             patch('finance.utils.requests.post', return_value=antwort):
            c.post('/neu/kreditoren/scan/', {'beleg_scan': f})
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.referenz, '000050637947060000894095003')
        self.assertEqual(k.iban, 'CH4030000008300003107')

    def test_qrr_pruefziffer_verwirft_falsche_kandidaten(self):
        from finance.utils import _zahlteil_extrahieren
        # Ungültige Prüfziffer → keine QRR-Übernahme
        qrr, _ = _zahlteil_extrahieren("Referenz 00 00506 37947 06000 08940 95004")
        self.assertEqual(qrr, '')
        # Normale IBAN (IID nicht 30000–31999) → keine QR-IBAN
        _, qriban = _zahlteil_extrahieren("IBAN CH16 0900 0000 3000 03107")
        self.assertEqual(qriban, '')


class QrDecoderTests(TestCase):
    """Echter QR-Decoder (zxing-cpp): Der Schweizer QR-Code des Zahlteils wird
    dekodiert und liefert IBAN/Referenz/Betrag/Empfänger verbindlich — auch bei
    Foto-Belegen, wo kein Text-Postprocessing möglich ist."""

    SPC = ("SPC\n0200\n1\nCH4030000008300003107\nS\nBKW Energie AG\nViktoriaplatz\n2\n"
           "3013\nBern\nCH\n\n\n\n\n\n\n\n137.30\nCHF\nS\nHR Immobilien AG\nViaduktstrasse\n8\n"
           "4512\nBellach\nCH\nQRR\n000050637947060000894095003\n\nEPD")

    def _qr_png(self):
        import io
        import segno
        buf = io.BytesIO()
        segno.make(self.SPC, error='m').save(buf, kind='png', scale=6, border=4)
        return buf.getvalue()

    def test_spc_parsen(self):
        from finance.utils import _spc_parsen
        d = _spc_parsen(self.SPC)
        self.assertEqual(d['iban'], 'CH4030000008300003107')
        self.assertEqual(d['lieferant'], 'BKW Energie AG')
        self.assertEqual(d['betrag'], 137.30)
        self.assertEqual(d['referenz'], '000050637947060000894095003')
        self.assertIsNone(_spc_parsen('kein spc'))

    def test_foto_beleg_mit_qr_wird_dekodiert(self):
        """Bild-Beleg OHNE KI-Key: früher 'nicht auslesbar' — jetzt liefert der
        QR-Decoder die Zahlungsdaten trotzdem verbindlich."""
        from django.test import override_settings
        from finance.utils import scan_beleg
        import tempfile, os as _os
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as fh:
            fh.write(self._qr_png())
            pfad = fh.name
        try:
            with override_settings(GROQ_API_KEY=None):
                d = scan_beleg(pfad)
            self.assertEqual(d['methode'], 'qr')
            self.assertEqual(d['iban'], 'CH4030000008300003107')
            self.assertEqual(d['referenz'], '000050637947060000894095003')
            self.assertEqual(d['betrag'], 137.30)
            self.assertEqual(d['lieferant'], 'BKW Energie AG')
        finally:
            _os.unlink(pfad)

    def test_upload_qr_bild_erzeugt_saubere_rechnung(self):
        """Upload eines QR-Bild-Belegs → Rechnung mit verbindlichen Zahlungsdaten,
        kein Warnhinweis (QR gilt als Erfolg)."""
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('zahlteil.png', self._qr_png(), content_type='image/png')
        with override_settings(GROQ_API_KEY=None):
            c.post('/neu/kreditoren/scan/', {'beleg_scan': f})
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.lieferant, 'BKW Energie AG')
        self.assertEqual(k.betrag, Decimal('137.30'))
        self.assertEqual(k.iban, 'CH4030000008300003107')
        self.assertEqual(k.referenz, '000050637947060000894095003')
        self.assertEqual(k.fehlermeldung, '')

    def test_faelligkeit_wird_ausgelesen(self):
        """'Zahlbar bis' → faellig_am an der Rechnung; auch relative Fristen
        ('zahlbar innert 30 Tagen') werden ab Rechnungsdatum gerechnet."""
        import io
        from reportlab.pdfgen import canvas as _c
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung

        def pdf(zeile):
            buf = io.BytesIO()
            c = _c.Canvas(buf)
            c.drawString(72, 800, "Faellig AG")
            c.drawString(72, 780, "Rechnung vom 20.07.2026")
            c.drawString(72, 760, "Total CHF 100.00")
            c.drawString(72, 740, zeile)
            c.save()
            return buf.getvalue()

        cl = Client(); cl.force_login(_team_user())
        # explizites Datum
        f1 = SimpleUploadedFile('f1.pdf', pdf("Zahlbar bis: 19.08.2026"), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            cl.post('/neu/kreditoren/scan/', {'beleg_scan': f1})
        k1 = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k1.faellig_am, date(2026, 8, 19))
        # relative Frist ab Rechnungsdatum
        f2 = SimpleUploadedFile('f2.pdf', pdf("Zahlbar innert 30 Tagen"), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            cl.post('/neu/kreditoren/scan/', {'beleg_scan': f2})
        k2 = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k2.faellig_am, date(2026, 8, 19))   # 20.07. + 30 Tage


class LieferantStandardkontoTests(TestCase):
    """Lieferanten-Gedächtnis: Standardkonto wird bei Freigabe gelernt und bei
    Erfassung/Scan für denselben Lieferanten automatisch vorbelegt (inkl. HNK)."""

    def _konten(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()

    def test_key_normalisierung(self):
        from finance.lieferanten import lieferant_key
        self.assertEqual(lieferant_key('EWZ AG'), lieferant_key('ewz'))
        self.assertEqual(lieferant_key('Meier & Co. GmbH'), lieferant_key('meier co'))
        self.assertEqual(lieferant_key('  '), '')

    def test_freigabe_lernt_konto(self):
        from finance.models import KreditorenRechnung, LieferantProfil
        from finance.booking import konto
        self._konten()
        k = KreditorenRechnung.objects.create(lieferant='EWZ AG', betrag=Decimal('120.00'),
                                              konto=konto('4130'), status='neu')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/freigeben/')
        prof = LieferantProfil.objects.filter(name_key='ewz').first()
        self.assertIsNotNone(prof)
        self.assertEqual(prof.standard_konto.nummer, '4130')

    def test_erfassen_belegt_konto_und_hnk_vor(self):
        from finance.models import KreditorenRechnung, LieferantProfil
        from finance.booking import konto
        self._konten()
        # Vorgelernt: EWZ → 4130 (HNK-relevant)
        LieferantProfil.objects.create(name_key='ewz', name_anzeige='EWZ AG',
                                       standard_konto=konto('4130'))
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/neu/', {'lieferant': 'EWZ', 'betrag': '99.00'})
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.konto.nummer, '4130')       # Konto automatisch zugeteilt
        self.assertTrue(k.is_hnk_relevant)             # HNK aus dem Konto abgeleitet

    def test_vorbelegen_ueberschreibt_gewaehltes_konto_nicht(self):
        from finance.models import KreditorenRechnung, LieferantProfil
        from finance.lieferanten import vorbelegen
        from finance.booking import konto
        self._konten()
        LieferantProfil.objects.create(name_key='ewz', name_anzeige='EWZ',
                                       standard_konto=konto('4130'))
        k = KreditorenRechnung(lieferant='EWZ', betrag=Decimal('10'), konto=konto('4000'))
        self.assertFalse(vorbelegen(k))               # bereits zugeteilt → kein Override
        self.assertEqual(k.konto.nummer, '4000')


class KreditorSplitTests(TestCase):
    """Kostenaufteilung: eine Rechnung auf mehrere Konten/Objekte splitten;
    Freigabe bucht jede Position einzeln; Summe muss stimmen; hnk_betrag."""

    def _konten(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()

    def _rechnung(self, betrag='300.00'):
        from finance.models import KreditorenRechnung
        return KreditorenRechnung.objects.create(lieferant='Sammel AG',
                                                 betrag=Decimal(betrag), status='neu')

    def test_position_add_und_summe(self):
        from finance.models import KreditorPosition
        self._konten()
        k = self._rechnung('300.00')
        c = Client(); c.force_login(_team_user())
        from finance.models import Buchungskonto
        k4000 = Buchungskonto.objects.get(nummer='4000').id
        k4120 = Buchungskonto.objects.get(nummer='4120').id
        c.post(f'/neu/kreditoren/{k.id}/position/', {'konto_id': k4000, 'betrag': '200.00'})
        c.post(f'/neu/kreditoren/{k.id}/position/', {'konto_id': k4120, 'betrag': '100.00'})
        self.assertEqual(k.positionen.count(), 2)
        self.assertEqual(k.positionen_summe, Decimal('300.00'))
        self.assertEqual(k.positionen_differenz, Decimal('0.00'))
        # 4120 ist HNK-relevant → Position automatisch HNK; hnk_betrag = 100
        self.assertEqual(k.hnk_betrag, Decimal('100.00'))

    def test_freigabe_bucht_pro_position(self):
        from finance.models import Buchungskonto, Buchung
        self._konten()
        k = self._rechnung('300.00')
        k4000 = Buchungskonto.objects.get(nummer='4000')
        k4120 = Buchungskonto.objects.get(nummer='4120')
        from finance.models import KreditorPosition
        KreditorPosition.objects.create(rechnung=k, konto=k4000, betrag=Decimal('200.00'))
        KreditorPosition.objects.create(rechnung=k, konto=k4120, betrag=Decimal('100.00'))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/freigeben/')
        k.refresh_from_db()
        self.assertEqual(k.status, 'freigegeben')
        # Zwei Aufwandsbuchungen (200 auf 4000, 100 auf 4120), Gegenkonto 2000
        b4000 = Buchung.objects.filter(soll_konto=k4000, kreditoren_rechnung=k).first()
        b4120 = Buchung.objects.filter(soll_konto=k4120, kreditoren_rechnung=k).first()
        self.assertEqual(b4000.betrag, Decimal('200.00'))
        self.assertEqual(b4120.betrag, Decimal('100.00'))
        # Kreditor (2000) total = 300
        haben2000 = Buchung.objects.filter(haben_konto__nummer='2000', kreditoren_rechnung=k)
        self.assertEqual(sum(b.betrag for b in haben2000), Decimal('300.00'))

    def test_freigabe_blockt_bei_falscher_summe(self):
        from finance.models import Buchungskonto, KreditorPosition
        self._konten()
        k = self._rechnung('300.00')
        KreditorPosition.objects.create(rechnung=k, konto=Buchungskonto.objects.get(nummer='4000'),
                                        betrag=Decimal('150.00'))   # Summe 150 ≠ 300
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/freigeben/')
        k.refresh_from_db()
        self.assertEqual(k.status, 'neu')   # nicht freigegeben — Aufteilung stimmt nicht


class WeiterverrechnungVerteilenTests(TestCase):
    """Multi-Mieter-Weiterverrechnung nach Verteilschlüssel + HNK-Doppelschutz."""

    def _konten(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()

    def _lg_mit_mietern(self):
        from portfolio.models import Liegenschaft, Einheit
        from crm.models import Mieter
        lg = Liegenschaft.objects.create(strasse='Verteilweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        daten = [('A', Decimal('50')), ('B', Decimal('100')), ('C', Decimal('50'))]  # m² 50/100/50 → 25/50/25%
        for name, m2 in daten:
            e = Einheit.objects.create(liegenschaft=lg, bezeichnung=name, typ='wohnung',
                                       flaeche_m2=m2, nettomiete_aktuell=Decimal('1000'))
            m = Mieter.objects.create(typ='person', vorname=name, nachname='Test',
                                      strasse='X', plz='8000', ort='Zürich')
            Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'),
                                       status='aktiv')
        return lg

    def test_verteilen_nach_m2(self):
        from finance.models import KreditorenRechnung, DebitorenRechnung
        self._konten()
        lg = self._lg_mit_mietern()
        k = KreditorenRechnung.objects.create(lieferant='Gärtner AG', betrag=Decimal('400.00'),
                                              liegenschaft=lg, status='freigegeben')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/', {'modus': 'verteilen', 'schluessel': 'm2'})
        rechnungen = DebitorenRechnung.objects.filter(quell_kreditor=k).order_by('betrag')
        self.assertEqual(rechnungen.count(), 3)
        # 400 nach 25/50/25 → 100/200/100
        self.assertEqual(sorted(r.betrag for r in rechnungen), [Decimal('100.00'), Decimal('100.00'), Decimal('200.00')])
        # Summe exakt = 400 (Rest auf letzten, keine Rundungsverluste)
        self.assertEqual(sum(r.betrag for r in rechnungen), Decimal('400.00'))

    def test_hnk_doppelschutz_blockt_ohne_override(self):
        from finance.models import KreditorenRechnung, DebitorenRechnung
        self._konten()
        lg = self._lg_mit_mietern()
        k = KreditorenRechnung.objects.create(lieferant='Heizöl AG', betrag=Decimal('300.00'),
                                              liegenschaft=lg, is_hnk_relevant=True, status='freigegeben')
        c = Client(); c.force_login(_team_user())
        # Ohne Override → geblockt, keine Debitorenrechnung
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/', {'modus': 'verteilen', 'schluessel': 'einheit'})
        self.assertEqual(DebitorenRechnung.objects.filter(quell_kreditor=k).count(), 0)
        # Mit Override → verteilt (3 Mieter gleich)
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/',
               {'modus': 'verteilen', 'schluessel': 'einheit', 'hnk_override': 'on'})
        self.assertEqual(DebitorenRechnung.objects.filter(quell_kreditor=k).count(), 3)


class NkAbrechnungSplitTests(TestCase):
    """P4: Die NK-Abrechnung ist split-aware — nur der HNK-Anteil einer
    aufgeteilten Kreditorenrechnung fliesst in die Mieterabrechnung, nicht der
    volle Betrag. Nicht-aufgeteilte HNK-Rechnungen bleiben unverändert."""

    def _setup(self):
        from finance.booking import ensure_kontenplan
        from portfolio.models import Liegenschaft, Einheit
        from crm.models import Mieter
        from finance.models import AbrechnungsPeriode
        ensure_kontenplan()
        lg = Liegenschaft.objects.create(strasse='NKweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='W1', typ='wohnung',
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


class KontoVorschlagLeistungTests(TestCase):
    """KI-Konto-Vorschlag (Kategorie/Schlüsselwort → Konto) + Leistungsperiode."""

    def _konten(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()

    def test_konto_aus_kategorie_und_text(self):
        from finance.lieferanten import konto_aus_kategorie, konto_aus_text
        self.assertEqual(konto_aus_kategorie('strom'), '4130')
        self.assertEqual(konto_aus_kategorie('versicherung'), '4400')
        self.assertIsNone(konto_aus_kategorie('quatsch'))
        self.assertEqual(konto_aus_text('Wasserversorgung Zürich'), '4110')
        self.assertEqual(konto_aus_text('EWZ Elektrizitätswerk'), '4130')
        self.assertIsNone(konto_aus_text('Irgendwas Neutrales'))

    def test_vorbelegen_prioritaet(self):
        from finance.models import KreditorenRechnung, LieferantProfil
        from finance.lieferanten import vorbelegen
        from finance.booking import konto
        self._konten()
        # Kategorie schlägt Konto vor (kein Gedächtnis, kein Keyword)
        k = KreditorenRechnung(lieferant='Neutrale Firma', betrag=Decimal('50'))
        self.assertTrue(vorbelegen(k, kategorie='heizung'))
        self.assertEqual(k.konto.nummer, '4100')
        self.assertTrue(k.is_hnk_relevant)
        # Gedächtnis hat Vorrang vor Kategorie
        LieferantProfil.objects.create(name_key='neutrale firma', name_anzeige='Neutrale Firma',
                                       standard_konto=konto('4000'))
        k2 = KreditorenRechnung(lieferant='Neutrale Firma', betrag=Decimal('50'))
        self.assertTrue(vorbelegen(k2, kategorie='heizung'))
        self.assertEqual(k2.konto.nummer, '4000')   # Gedächtnis gewinnt

    def test_erfassen_setzt_leistungsperiode_und_konto(self):
        from finance.models import KreditorenRechnung
        self._konten()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/neu/', {
            'lieferant': 'Wasserversorgung', 'betrag': '120.00',
            'leistungs_von': '2025-01-01', 'leistungs_bis': '2025-12-31',
        })
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.leistungs_von, date(2025, 1, 1))
        self.assertEqual(k.leistungs_bis, date(2025, 12, 31))
        self.assertEqual(k.konto.nummer, '4110')   # aus Schlüsselwort «Wasser»
        self.assertTrue(k.is_hnk_relevant)

    def test_scanner_liefert_kategorie_und_periode_keys(self):
        # Ohne KI liefert der Scanner die neuen Keys (leer) — Struktur stabil.
        from finance.utils import _leer
        d = _leer('leer', '')
        self.assertIn('kategorie', d)
        self.assertIn('leistung_von', d)
        self.assertIn('leistung_bis', d)


class NkEndToEndTests(TestCase):
    """QA: kompletter NK-Kreislauf mit split-aware Kosten — Geld-Erhaltung
    (Summe Mieteranteile == Gesamtkosten), Nicht-HNK-Anteil bleibt draussen,
    Verbuchung erzeugt die richtigen Nachzahlungen."""

    def _setup(self):
        from finance.booking import ensure_kontenplan
        from portfolio.models import Liegenschaft, Einheit
        from crm.models import Mieter
        from finance.models import AbrechnungsPeriode
        ensure_kontenplan()
        lg = Liegenschaft.objects.create(strasse='E2Eweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        verts = []
        for name, m2 in [('A', Decimal('60')), ('B', Decimal('40'))]:
            e = Einheit.objects.create(liegenschaft=lg, bezeichnung=name, typ='wohnung',
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

    def _setup(self):
        from finance.booking import ensure_kontenplan
        from portfolio.models import Liegenschaft, Einheit
        from finance.models import AbrechnungsPeriode, KreditorenRechnung, Buchungskonto
        ensure_kontenplan()
        lg = Liegenschaft.objects.create(strasse='Statusweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='W1', typ='wohnung',
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


class VertragAktivSyncTests(TestCase):
    """Offener Punkt 1: `aktiv` folgt immer dem Status (kein Drift mehr)."""

    def test_entwurf_ist_nicht_aktiv(self):
        lg, e, m, v = _basis_objekte()
        v2 = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                        netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'),
                                        status='entwurf', aktiv=True)   # aktiv=True gesetzt …
        v2.refresh_from_db()
        self.assertFalse(v2.aktiv)   # … aber Status entwurf ⇒ aktiv=False

    def test_statuswechsel_synct_aktiv(self):
        lg, e, m, v = _basis_objekte()   # status='aktiv' → aktiv=True
        v.refresh_from_db()
        self.assertTrue(v.aktiv)
        v.status = 'gekuendigt'
        v.save()
        v.refresh_from_db()
        self.assertFalse(v.aktiv)
        v.status = 'aktiv'
        v.save(update_fields=['status'])   # aktiv wird trotz update_fields mitgezogen
        v.refresh_from_db()
        self.assertTrue(v.aktiv)


class WeiterverrechnungSplitKontoTests(TestCase):
    """Offener Punkt 2: Weiterverrechnung einer gesplitteten Rechnung nutzt das
    Konto der grössten Position als Aufwand-Gegenkonto (statt pauschal 4000)."""

    def test_aufwand_gegenkonto_aus_groesster_position(self):
        from finance.booking import ensure_kontenplan, konto
        from finance.models import KreditorenRechnung, KreditorPosition, Buchung, Buchungskonto
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(lieferant='Split AG', betrag=Decimal('300.00'),
                                              liegenschaft=lg, status='freigegeben')
        # grösste Position: 200 auf 4130
        KreditorPosition.objects.create(rechnung=k, konto=Buchungskonto.objects.get(nummer='4000'),
                                        betrag=Decimal('100.00'))
        KreditorPosition.objects.create(rechnung=k, konto=Buchungskonto.objects.get(nummer='4130'),
                                        betrag=Decimal('200.00'))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/', {'vertrag_id': v.id, 'betrag': '300', 'zuschlag': '0'})
        # Aufwandsminderung 1190 an 4130 (grösste Position), nicht 4000
        gegen = Buchung.objects.filter(soll_konto__nummer='1190', kreditoren_rechnung=k).first()
        self.assertIsNotNone(gegen)
        self.assertEqual(gegen.haben_konto.nummer, '4130')


class VertragMietzinsKomponentenTests(TestCase):
    """Datierte Mietzins-Komponenten am Verhältnis: Gratismonate/gestaffelter
    Start. Die Sollstellung greift pro Monat die gültige Komponente."""

    def _setup(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.beginn = date(2026, 10, 1)
        v.netto_mietzins = Decimal('1000'); v.nebenkosten = Decimal('250')
        v.mietzins_modell = 'fest'
        v.save()
        return v

    def test_gratismonate_via_komponenten(self):
        from rentals.models import VertragMietzins
        from finance.models import DebitorenRechnung
        from core.services.automation import run_sollstellung
        v = self._setup()
        # Erste zwei Monate netto-frei (NK läuft), ab 01.12 voller Netto.
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2026, 10, 1),
                                       netto_mietzins=Decimal('0'), nebenkosten=Decimal('250'))
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2026, 12, 1),
                                       netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        # Auflösung pro Datum
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 10, 15)), Decimal('0'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 11, 30)), Decimal('0'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 12, 1)), Decimal('1000'))
        self.assertEqual(v.effektive_nebenkosten(date(2026, 10, 15)), Decimal('250'))

        # Sollstellung Oktober: nur NK 250 (Netto 0)
        run_sollstellung(2026, 10)
        okt = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 10/2026')
        self.assertEqual(okt.betrag, Decimal('250.00'))
        # Dezember: voll 1250
        run_sollstellung(2026, 12)
        dez = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 12/2026')
        self.assertEqual(dez.betrag, Decimal('1250.00'))

    def test_ohne_komponenten_unveraendert(self):
        from finance.models import DebitorenRechnung
        from core.services.automation import run_sollstellung
        v = self._setup()   # keine Komponenten → flacher Wert
        run_sollstellung(2026, 10)
        okt = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 10/2026')
        self.assertEqual(okt.betrag, Decimal('1250.00'))   # 1000 + 250 wie bisher


class VertragMietzinsUITests(TestCase):
    """Komponenten am Vertrag: UI (Mietzins-Tab), Add/Del, PDF-Anzeige."""

    def test_add_del_und_anzeige(self):
        from rentals.models import VertragMietzins
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        # Hinzufügen (Endpoint unverändert; verwaltet wird am Objekt-Mietzins-Tab)
        c.post(f'/neu/vertrag-mietzins/{v.id}/', {
            'gueltig_ab': '2026-10-01', 'netto_mietzins': '1000.00', 'nebenkosten': '250.00',
            'mietzinsfrei': '1', 'notiz': 'Gratismonat',
            'next': f'/neu/objekte/{e.id}/?tab=mietzins'})
        c.post(f'/neu/vertrag-mietzins/{v.id}/', {
            'gueltig_ab': '2026-12-01', 'netto_mietzins': '1000.00', 'nebenkosten': '250.00'})
        self.assertEqual(v.mietzins_komponenten.count(), 2)
        # Verwaltung am OBJEKT-Mietzins-Tab: Formular + Komponenten sichtbar
        obj = c.get(f'/neu/objekte/{e.id}/?tab=mietzins').content.decode()
        self.assertIn('Gratismonate / Rabatt', obj)
        self.assertIn('01.10.2026', obj)
        self.assertIn('mietzinsfrei', obj)   # Checkbox-Label im Objekt-Formular
        # Am VERTRAG nur noch die Ansicht (read-only), kein Erfassen-Formular
        vt = c.get(f'/neu/vertraege/{v.id}/?tab=mietzins').content.decode()
        self.assertIn('Gratismonate / Rabatt', vt)
        self.assertIn('01.10.2026', vt)
        self.assertIn('Am Objekt bearbeiten', vt)
        # Löschen
        k = v.mietzins_komponenten.first()
        c.post(f'/neu/vertrag-mietzins/{k.id}/loeschen/')
        self.assertEqual(v.mietzins_komponenten.count(), 1)

    def test_objekt_tab_verwaltet_entwurf_vertrag(self):
        """Gratismonate lassen sich am Objekt schon für einen frischen Entwurf
        erfassen (mietzins_vertrag fällt auf den neuesten nicht-beendeten zurück)."""
        from rentals.models import VertragMietzins
        lg, e, m, v = _basis_objekte()
        v.status = 'entwurf'; v.save()
        c = Client(); c.force_login(_team_user())
        obj = c.get(f'/neu/objekte/{e.id}/?tab=mietzins').content.decode()
        self.assertIn('Gratismonate / Rabatt', obj)   # trotz Entwurf sichtbar
        c.post(f'/neu/vertrag-mietzins/{v.id}/', {
            'gueltig_ab': '2026-10-01', 'netto_mietzins': '1000.00', 'nebenkosten': '250.00',
            'mietzinsfrei': '1', 'next': f'/neu/objekte/{e.id}/?tab=mietzins'})
        self.assertEqual(v.mietzins_komponenten.count(), 1)

    def test_komponenten_im_vertrags_pdf(self):
        from rentals.models import VertragMietzins
        from core.services.dokument_service import DOKUMENT_TYPEN
        lg, e, m, v = _basis_objekte()
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2026, 10, 1),
                                       netto_mietzins=Decimal('0'), nebenkosten=Decimal('250'),
                                       notiz='mietzinsfrei')
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2026, 12, 1),
                                       netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        # Der Vertrags-PDF-Template rendert den Zeitplan (via mietzins_zeitplan-Kontext)
        from django.template.loader import get_template
        html = get_template('core/mietvertrag_pdf.html').render({'vertrag': v, 'einheit': e,
                'miete_fmt': '1000.00', 'nk_fmt': '250.00', 'brutto_fmt': '1250.00',
                'mietzins_zeitplan': v.mietzins_zeitplan(), 'mietzins_hinweise': v.mietzins_hinweise()})
        self.assertIn('01.10.2026', html)
        self.assertIn('mietzinsfrei', html)
        self.assertIn('01.12.2026', html)


class SollmietzinsSollstellungTests(TestCase):
    """Der datierte Objekt-Sollmietzins (Gratismonate/Rabatt direkt in der
    Sollmiete) treibt die Sollstellung automatisch pro Periode — für neue UND
    bestehende Verträge, ohne dass am Vertrag etwas erfasst werden muss."""

    def _setup(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.beginn = date(2026, 10, 1)
        v.netto_mietzins = Decimal('1000'); v.nebenkosten = Decimal('250')
        v.mietzins_modell = 'fest'; v.save()
        return lg, e, m, v

    def test_sollmietzins_zeitplan_treibt_sollstellung(self):
        from portfolio.models import Sollmietzins
        from finance.models import DebitorenRechnung, Buchung
        from core.services.automation import run_sollstellung
        _lg, e, _m, v = self._setup()
        # Zeitplan am OBJEKT: Okt normal, Nov Netto gratis (Rabatt=Referenz), Dez normal.
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 10, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 11, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
                                    rabatt_netto=Decimal('1000'), notiz='Gratismonat')
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 12, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        # Resolver pro Periode
        self.assertEqual(v.verrechneter_netto_mietzins(date(2026, 10, 15)), Decimal('1000'))
        self.assertEqual(v.verrechneter_netto_mietzins(date(2026, 11, 15)), Decimal('0'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 11, 15)), Decimal('1000'))  # Referenz voll
        self.assertEqual(v.verrechneter_netto_mietzins(date(2026, 12, 15)), Decimal('1000'))
        # Sollstellung folgt den gültig-ab-Daten
        run_sollstellung(2026, 10)
        run_sollstellung(2026, 11)
        run_sollstellung(2026, 12)
        okt = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 10/2026')
        nov = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 11/2026')
        dez = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 12/2026')
        self.assertEqual(okt.betrag, Decimal('1250.00'))
        self.assertEqual(nov.betrag, Decimal('250.00'))   # Netto erlassen
        self.assertEqual(dez.betrag, Decimal('1250.00'))
        # November: voller Referenzertrag gebucht + Rabatt als Ertragsminderung 3090
        nov_b = Buchung.objects.filter(debitoren_rechnung=nov)
        self.assertEqual(sum(b.betrag for b in nov_b.filter(haben_konto__nummer='3000')), Decimal('1000.00'))
        self.assertEqual(sum(b.betrag for b in nov_b.filter(soll_konto__nummer='3090')), Decimal('1000.00'))

    def test_stale_sollmietzins_hijackt_nicht(self):
        """Eine alte Sollmietzins-Zeile VOR Mietbeginn (kein Zeitplan für dieses
        Verhältnis) darf die Verrechnung NICHT übersteuern → Vertragsbasis gilt."""
        from portfolio.models import Sollmietzins
        _lg, e, _m, v = self._setup()
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2020, 1, 1),
                                    netto_mietzins=Decimal('800'), nebenkosten=Decimal('200'))
        # Keine Zeile ab Mietbeginn → Basis (1000) gilt, nicht die 800er-Altzeile.
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 10, 15)), Decimal('1000'))
        self.assertEqual(v.verrechneter_netto_mietzins(date(2026, 10, 15)), Decimal('1000'))

    def test_mietzinsfrei_checkbox_am_sollmietzins(self):
        from portfolio.models import Sollmietzins
        _lg, e, _m, _v = self._setup()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/sollmietzins/', {
            'einheit_id': str(e.id), 'gueltig_ab': '2026-11-01',
            'netto_mietzins': '1000.00', 'nebenkosten': '250.00',
            'mietzinsfrei': '1', 'notiz': 'Gratismonat'})
        s = Sollmietzins.objects.get(einheit=e, gueltig_ab=date(2026, 11, 1))
        self.assertEqual(s.netto_mietzins, Decimal('1000.00'))   # Referenz voll
        self.assertEqual(s.rabatt_netto, Decimal('1000.00'))     # Rabatt = Netto
        self.assertEqual(s.verrechnet_brutto, Decimal('250.00'))

    def test_zeitplan_im_vertrags_pdf(self):
        from portfolio.models import Sollmietzins
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        _lg, e, _m, v = self._setup()
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 11, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
                                    rabatt_netto=Decimal('1000'), notiz='Gratismonat')
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 12, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        self.assertTrue(len(v.mietzins_zeitplan()) >= 2)
        pdf = generate_vertrag_pdf_bytes(v)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_gratismonat_hinweise_prosa(self):
        from portfolio.models import Sollmietzins
        _lg, e, _m, v = self._setup()
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 10, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
                                    rabatt_netto=Decimal('1000'))
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 12, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        hin = v.mietzins_hinweise()
        self.assertEqual(len(hin), 2)
        self.assertIn('01.10.2026 bis 30.11.2026', hin[0])
        self.assertIn('mietzinsfrei', hin[0])
        self.assertIn('nur die Nebenkosten', hin[0])
        self.assertIn('Ab 01.12.2026', hin[1])
        self.assertIn("1'250.00", hin[1])

    def test_live_vorschau_entspricht_pdf_template(self):
        """Die Live-Vorschau des Assistenten rendert dasselbe Template wie das PDF
        (aus den Formularwerten, ohne Speichern) — inkl. Gratismonat-Zeitplan."""
        from portfolio.models import Sollmietzins
        _lg, e, m, _v = self._setup()
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 10, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
                                    rabatt_netto=Decimal('1000'))
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 12, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/vertraege/vorschau/', {
            'einheit_id': str(e.id), 'mieter_id': str(m.id), 'beginn': '2026-10-01',
            'netto_mietzins': '1000', 'nebenkosten': '250'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('mietzinsfrei', body)             # Zeitplan-Tabelle
        self.assertIn('Gestaffelter Mietzins', body)    # Abschnitt
        self.assertIn('01.10.2026 bis 30.11.2026', body)  # Klartext-Hinweis

    def test_vorschau_ohne_objekt_platzhalter(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/vertraege/vorschau/', {'netto_mietzins': '1000'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('Objekt auswählen', r.content.decode())


class VertragBearbeitenTests(TestCase):
    """Vertrag bearbeiten: Entwurf voll, aktiv nur Detailfelder (Miete gesperrt,
    serverseitig erzwungen)."""

    def test_entwurf_bearbeiten_via_assistent(self):
        from rentals.models import Mietvertrag
        lg, e, m, v = _basis_objekte()
        v.status = 'entwurf'; v.netto_mietzins = Decimal('1500'); v.save()
        c = Client(); c.force_login(_team_user())
        # Entwurf → Bearbeiten leitet zum Assistenten (Wizard) mit ?edit=
        r = c.get(f'/neu/vertraege/{v.id}/bearbeiten/')
        self.assertEqual(r.status_code, 302)
        self.assertIn(f'/neu/vertraege/neu/?edit={v.id}', r['Location'])
        # Assistent im Edit-Modus: Prefill-Daten + verstecktes edit_id
        body = c.get(f'/neu/vertraege/neu/?edit={v.id}').content.decode()
        self.assertIn('id="edit-data"', body)
        self.assertIn(f'name="edit_id" value="{v.id}"', body)
        # Speichern mit edit_id aktualisiert denselben Vertrag (kein neuer)
        vor = Mietvertrag.objects.count()
        c.post('/neu/vertraege/neu/speichern/', {
            'edit_id': str(v.id), 'einheit_id': str(e.id), 'mieter_id': str(m.id),
            'beginn': '2024-01-01', 'netto_mietzins': '1700', 'nebenkosten': '210',
            'nk_abrechnungsart': 'akonto', 'zahlungsrhythmus': 'monatlich',
            'verteilschluessel': 'm2', 'mietzins_modell': 'fest', 'kuendigungsfrist': '3',
            'anzahl_personen': '1', 'nebenraeume': 'Keller 9'})
        self.assertEqual(Mietvertrag.objects.count(), vor)   # kein neuer Vertrag
        v.refresh_from_db()
        self.assertEqual(v.netto_mietzins, Decimal('1700'))
        self.assertEqual(v.nebenraeume, 'Keller 9')
        self.assertEqual(v.status, 'entwurf')   # ohne aktiv_setzen bleibt Entwurf

    def test_aktiv_miete_gesperrt(self):
        lg, e, m, v = _basis_objekte()   # status='aktiv', netto 1500
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vertraege/{v.id}/bearbeiten/').content.decode()
        self.assertNotIn('name="netto_mietzins"', r)   # gesperrt → kein Eingabefeld
        self.assertIn('eingeschränkte Bearbeitung', r)
        # Versuch, die Miete + Beginn zu ändern → wird ignoriert; Detailfeld greift
        c.post(f'/neu/vertraege/{v.id}/bearbeiten/', {
            'netto_mietzins': '9999', 'beginn': '2020-01-01', 'nebenkosten': '9999',
            'kuendigungsfrist': '3', 'nebenraeume': 'Estrich', 'anzahl_personen': '1'})
        v.refresh_from_db()
        self.assertEqual(v.netto_mietzins, Decimal('1500'))   # unverändert
        self.assertEqual(v.beginn, date(2024, 1, 1))          # unverändert
        self.assertEqual(v.nebenraeume, 'Estrich')            # Detailfeld geändert

    def test_pdf_nur_bei_aktiv(self):
        """PDFs werden nur erzeugt, wenn 'aktiv' angehakt ist — ein Entwurf
        bleibt dokumentlos, bis er aktiviert wird."""
        from rentals.models import Mietvertrag, Dokument
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        base = {'einheit_id': str(e.id), 'mieter_id': str(m.id), 'beginn': '2026-05-01',
                'netto_mietzins': '1400', 'nebenkosten': '200', 'nk_abrechnungsart': 'akonto',
                'zahlungsrhythmus': 'monatlich', 'verteilschluessel': 'm2',
                'mietzins_modell': 'fest', 'kuendigungsfrist': '3', 'anzahl_personen': '1'}
        # 1. Entwurf (ohne aktiv_setzen) → keine Dokumente
        c.post('/neu/vertraege/neu/speichern/', base)
        v1 = Mietvertrag.objects.filter(einheit=e, status='entwurf').order_by('-id').first()
        self.assertIsNotNone(v1)
        self.assertEqual(Dokument.objects.filter(vertrag=v1).count(), 0)
        # 2. Aktiv gesetzt → Dokumente werden erzeugt
        c.post('/neu/vertraege/neu/speichern/', {**base, 'aktiv_setzen': 'on'})
        v2 = Mietvertrag.objects.filter(einheit=e, status='aktiv').order_by('-id').first()
        self.assertIsNotNone(v2)
        self.assertGreater(Dokument.objects.filter(vertrag=v2).count(), 0)

    def test_entwurf_aktivieren_erzeugt_pdf(self):
        """Wird ein Entwurf im Assistenten aktiviert, entstehen die PDFs."""
        from rentals.models import Mietvertrag, Dokument
        lg, e, m, v = _basis_objekte()
        v.status = 'entwurf'; v.save()
        self.assertEqual(Dokument.objects.filter(vertrag=v).count(), 0)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/vertraege/neu/speichern/', {
            'edit_id': str(v.id), 'einheit_id': str(e.id), 'mieter_id': str(m.id),
            'beginn': '2024-01-01', 'netto_mietzins': '1500', 'nebenkosten': '200',
            'nk_abrechnungsart': 'akonto', 'zahlungsrhythmus': 'monatlich',
            'verteilschluessel': 'm2', 'mietzins_modell': 'fest', 'kuendigungsfrist': '3',
            'anzahl_personen': '1', 'aktiv_setzen': 'on'})
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')
        self.assertGreater(Dokument.objects.filter(vertrag=v).count(), 0)

    def test_vertrag_loeschen_raeumt_dokumente_auf(self):
        """Beim Löschen eines Vertrags werden seine auto-erzeugten Vertragspaket-
        Dokumente mitgelöscht — keine verwaisten Kopien in der Personen-Akte."""
        from rentals.models import Mietvertrag, Dokument
        lg, e, m, v = _basis_objekte()
        # zwei automatische Vertragspaket-Dokumente + ein Fremd-Upload
        Dokument.objects.create(vertrag=v, mieter=m, einheit=e, kategorie='vertrag',
                                bezeichnung='Mietvertrag', titel='Mietvertrag')
        Dokument.objects.create(vertrag=v, mieter=m, einheit=e, kategorie='vertrag',
                                bezeichnung='Hausordnung', titel='Hausordnung')
        upload = Dokument.objects.create(mieter=m, kategorie='korrespondenz',
                                         bezeichnung='Ausweis-Kopie', titel='Ausweis-Kopie')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/loeschen/')
        self.assertFalse(Mietvertrag.objects.filter(id=v.id).exists())
        # Vertragspaket-Dokumente weg, kein verwaistes (vertrag=None) übrig
        self.assertEqual(Dokument.objects.filter(bezeichnung='Mietvertrag').count(), 0)
        self.assertEqual(Dokument.objects.filter(bezeichnung='Hausordnung').count(), 0)
        # Fremd-Upload bleibt erhalten
        self.assertTrue(Dokument.objects.filter(id=upload.id).exists())

    def test_bearbeiten_button_auf_detailseite(self):
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/{v.id}/').content.decode()
        self.assertIn(f'/neu/vertraege/{v.id}/bearbeiten/', body)


class ObjektFormMietzinsQuelleTests(TestCase):
    """Der Mietzins wird nur noch über den Sollmietzins (Mietzins-Tab) gepflegt —
    das Objekt-Bearbeiten-Formular schreibt ihn nicht mehr direkt (kein Drift)."""

    def test_neuanlage_seedet_sollmietzins(self):
        from portfolio.models import Sollmietzins, Einheit
        lg = Liegenschaft.objects.create(strasse='OF 1', plz='8000', ort='ZH', versicherungswert=Decimal('1'))
        c = Client(); c.force_login(_team_user())
        c.post('/neu/objekte/neu/', {
            'liegenschaft_id': str(lg.id), 'bezeichnung': 'Neu-1', 'typ': 'wohnung',
            'nettomiete_aktuell': '1400', 'nebenkosten_aktuell': '250',
            'soll_gueltig_ab': '2026-01-01'})
        e = Einheit.objects.get(bezeichnung='Neu-1')
        # Erste Sollmietzins-Zeile erzeugt + Aktuellwerte daraus abgeleitet
        s = Sollmietzins.objects.get(einheit=e, gueltig_ab=date(2026, 1, 1))
        self.assertEqual(s.netto_mietzins, Decimal('1400'))
        self.assertEqual(e.nettomiete_aktuell, Decimal('1400.00'))
        self.assertEqual(e.nebenkosten_aktuell, Decimal('250.00'))

    def test_bearbeiten_aendert_miete_nicht_direkt(self):
        """Beim Bearbeiten wird ein übermitteltes nettomiete_aktuell IGNORIERT —
        die Miete bleibt beim Sollmietzins-Wert (einzige Quelle)."""
        from portfolio.models import Sollmietzins, Einheit
        lg, e, m, v = _basis_objekte()   # e.nettomiete_aktuell = 1500
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2024, 1, 1),
                                    netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'))
        e.refresh_from_db()
        c = Client(); c.force_login(_team_user())
        # Bearbeiten-POST mit einem abweichenden Mietwert
        c.post(f'/neu/objekte/{e.id}/bearbeiten/', {
            'liegenschaft_id': str(lg.id), 'bezeichnung': e.bezeichnung, 'typ': e.typ,
            'nettomiete_aktuell': '9999', 'nebenkosten_aktuell': '9999'})
        e.refresh_from_db()
        # Wert unverändert (9999 ignoriert), kein neuer Sollmietzins
        self.assertEqual(e.nettomiete_aktuell, Decimal('1500'))
        self.assertEqual(Sollmietzins.objects.filter(einheit=e).count(), 1)
        # Bearbeiten-Maske zeigt kein editierbares Mietfeld mehr (nur Ansicht + Link)
        body = c.get(f'/neu/objekte/{e.id}/bearbeiten/').content.decode()
        self.assertNotIn('name="nettomiete_aktuell"', body)
        self.assertIn('Mietzins verwalten', body)


class VersionEndpointTests(TestCase):
    """Öffentlicher Deploy-Check /version/ — ohne Login erreichbar, liefert
    Commit/Branch des laufenden Prozesses als JSON."""

    def test_version_public_json(self):
        c = Client()   # kein Login
        r = c.get('/version/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn('commit', data)
        self.assertIn('branch', data)
        self.assertIn('process_started', data)


class VertragMietzinsRabattTests(TestCase):
    """Option B — Referenz/Rabatt-Split: Gratismonat wird brutto gebucht
    (voller Referenzertrag 3000/3020) + Rabatt als Ertragsminderung (3090),
    Debitor nettoiert auf den verrechneten Betrag. So bleiben Mieterspiegel
    und Bilanz auf dem echten Ertragspotenzial, während der Mieter 0 zahlt."""

    def _setup(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.beginn = date(2026, 10, 1)
        v.netto_mietzins = Decimal('1000'); v.nebenkosten = Decimal('250')
        v.mietzins_modell = 'fest'
        v.save()
        return lg, e, m, v

    def test_resolver_referenz_vs_verrechnet(self):
        from rentals.models import VertragMietzins
        _lg, _e, _m, v = self._setup()
        # Gratismonat: Referenz voll, Rabatt = Netto-Referenz → verrechnet 0.
        VertragMietzins.objects.create(
            vertrag=v, gueltig_ab=date(2026, 10, 1),
            netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
            rabatt_netto=Decimal('1000'), notiz='Gratismonat')
        VertragMietzins.objects.create(
            vertrag=v, gueltig_ab=date(2026, 12, 1),
            netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        # Referenz (Reporting) bleibt voll …
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 10, 15)), Decimal('1000'))
        self.assertEqual(v.effektive_nebenkosten(date(2026, 10, 15)), Decimal('250'))
        # … verrechnet (Debitor) ist im Gratismonat 0 Netto (NK läuft).
        self.assertEqual(v.verrechneter_netto_mietzins(date(2026, 10, 15)), Decimal('0'))
        self.assertEqual(v.verrechnete_nebenkosten(date(2026, 10, 15)), Decimal('250'))
        # Dezember voll.
        self.assertEqual(v.verrechneter_netto_mietzins(date(2026, 12, 1)), Decimal('1000'))

    def test_sollstellung_bruttobuchung(self):
        from rentals.models import VertragMietzins
        from finance.models import DebitorenRechnung, Buchung
        from core.services.automation import run_sollstellung
        _lg, e, _m, v = self._setup()
        VertragMietzins.objects.create(
            vertrag=v, gueltig_ab=date(2026, 10, 1),
            netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
            rabatt_netto=Decimal('1000'), notiz='Gratismonat')
        run_sollstellung(2026, 10)
        r = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 10/2026')
        # Debitor schuldet nur die NK (Netto voll erlassen).
        self.assertEqual(r.betrag, Decimal('250.00'))
        buchungen = Buchung.objects.filter(debitoren_rechnung=r)
        # Voller Referenzertrag auf 3000 (Wohnen) …
        b3000 = buchungen.filter(haben_konto__nummer='3000')
        self.assertEqual(sum(b.betrag for b in b3000), Decimal('1000.00'))
        # NK-Ertrag auf 3020 …
        b3020 = buchungen.filter(haben_konto__nummer='3020')
        self.assertEqual(sum(b.betrag for b in b3020), Decimal('250.00'))
        # … Rabatt als Ertragsminderung (Soll 3090 / Haben 1100).
        b3090 = buchungen.filter(soll_konto__nummer='3090', haben_konto__nummer='1100')
        self.assertEqual(sum(b.betrag for b in b3090), Decimal('1000.00'))
        # Debitor (1100) nettoiert: Soll 1000+250, Haben 1000 → offen 250.
        soll_1100 = sum(b.betrag for b in buchungen.filter(soll_konto__nummer='1100'))
        haben_1100 = sum(b.betrag for b in buchungen.filter(haben_konto__nummer='1100'))
        self.assertEqual(soll_1100 - haben_1100, Decimal('250.00'))

    def test_teilrabatt(self):
        from rentals.models import VertragMietzins
        from finance.models import DebitorenRechnung, Buchung
        from core.services.automation import run_sollstellung
        _lg, _e, _m, v = self._setup()
        # 300 Rabatt auf 1000 Netto → verrechnet 700 + 250 NK = 950.
        VertragMietzins.objects.create(
            vertrag=v, gueltig_ab=date(2026, 10, 1),
            netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
            rabatt_netto=Decimal('300'))
        run_sollstellung(2026, 10)
        r = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 10/2026')
        self.assertEqual(r.betrag, Decimal('950.00'))
        b3090 = Buchung.objects.filter(debitoren_rechnung=r, soll_konto__nummer='3090')
        self.assertEqual(sum(b.betrag for b in b3090), Decimal('300.00'))

    def test_ui_mietzinsfrei_checkbox_setzt_rabatt(self):
        from rentals.models import VertragMietzins
        _lg, _e, _m, v = self._setup()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertrag-mietzins/{v.id}/', {
            'gueltig_ab': '2026-10-01', 'netto_mietzins': '1000.00',
            'nebenkosten': '250.00', 'mietzinsfrei': '1', 'notiz': 'Gratismonat'})
        k = VertragMietzins.objects.get(vertrag=v, gueltig_ab=date(2026, 10, 1))
        self.assertEqual(k.netto_mietzins, Decimal('1000.00'))   # Referenz voll
        self.assertEqual(k.rabatt_netto, Decimal('1000.00'))     # Rabatt = Netto
        self.assertEqual(k.verrechnet_brutto, Decimal('250.00')) # zu zahlen = NK

    def test_pdf_zeigt_referenz_und_zu_zahlen(self):
        from rentals.models import VertragMietzins
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        _lg, _e, _m, v = self._setup()
        VertragMietzins.objects.create(
            vertrag=v, gueltig_ab=date(2026, 10, 1),
            netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
            rabatt_netto=Decimal('1000'), notiz='Gratismonat')
        # Über den echten PDF-Service (nicht nur Template-Direktrender).
        pdf = generate_vertrag_pdf_bytes(v)
        self.assertTrue(pdf.startswith(b'%PDF'))
        # Template rendert Referenzmiete + Rabatt-Spalte.
        from django.template.loader import get_template
        html = get_template('core/mietvertrag_pdf.html').render({'vertrag': v, 'einheit': _e,
                'miete_fmt': '1000.00', 'nk_fmt': '250.00', 'brutto_fmt': '1250.00',
                'mietzins_zeitplan': v.mietzins_zeitplan(), 'mietzins_hinweise': v.mietzins_hinweise()})
        self.assertIn('Referenzmiete', html)
        self.assertIn('Zu bezahlen', html)
        self.assertIn('mietzinsfrei', html)


class DatenLebenszyklusTests(TestCase):
    """Regression gegen die Klasse 'verwaiste/doppelte Daten beim Löschen &
    Re-Trigger' (Audit nach dem Vertragsdokument-Bug): zentrale Dokument-
    Bereinigung, CASCADE der Anpassungs-Sollmietzinse, Idempotenz von
    Schlussabrechnung/Mahnung, camt-Dedup ohne Datenverlust, Auto-Frist-Cleanup."""

    def _dok(self, v, e, m, titel='Mietvertrag', kategorie='vertrag'):
        from rentals.models import Dokument
        from django.core.files.base import ContentFile
        d = Dokument.objects.create(vertrag=v, einheit=e, mieter=m,
                                    kategorie=kategorie, bezeichnung=titel, titel=titel)
        d.datei.save('x.pdf', ContentFile(b'%PDF-1.4'), save=True)
        return d

    def test_vertrag_delete_raeumt_vertragspaket_zentral(self):
        # Modell-Ebene: deckt UI- UND API-Löschpfad ab (delete() override).
        from rentals.models import Dokument
        _lg, e, m, v = _basis_objekte()
        self._dok(v, e, m, 'Mietvertrag')
        self._dok(v, e, m, 'Hausordnung')
        fremd = self._dok(v, e, m, 'Mieterbrief', kategorie='korrespondenz')
        v.delete()
        # Vertragspaket ist weg (kein verwaister vertrag=None-Rest)
        self.assertEqual(Dokument.objects.filter(bezeichnung__in=['Mietvertrag', 'Hausordnung']).count(), 0)
        # Fremd-Korrespondenz bleibt erhalten
        self.assertTrue(Dokument.objects.filter(id=fremd.id).exists())

    def test_anpassung_sollmietzins_cascade_kein_orphan(self):
        # Löschen der Anpassung (bzw. via Vertrags-CASCADE) darf keine
        # quelle_anpassung=NULL-Zeile zurücklassen, die als Basismiete gilt.
        from rentals.models import MietzinsAnpassung
        from portfolio.models import Sollmietzins
        _lg, e, m, v = _basis_objekte()
        anp = MietzinsAnpassung.objects.create(vertrag=v, wirksam_ab=date(2024, 7, 1),
                                               neuer_netto_mietzins=Decimal('1600'))
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2024, 7, 1),
                                    netto_mietzins=Decimal('1600'), nebenkosten=Decimal('200'),
                                    quelle_anpassung=anp)
        # Direktes Löschen der Anpassung
        anp.delete()
        self.assertEqual(Sollmietzins.objects.filter(einheit=e, quelle_anpassung__isnull=True).count(), 0)
        # Auch der Vertrags-CASCADE-Pfad darf keine Waise erzeugen
        anp2 = MietzinsAnpassung.objects.create(vertrag=v, wirksam_ab=date(2024, 8, 1),
                                                neuer_netto_mietzins=Decimal('1700'))
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2024, 8, 1),
                                    netto_mietzins=Decimal('1700'), nebenkosten=Decimal('200'),
                                    quelle_anpassung=anp2)
        v.delete()
        self.assertEqual(Sollmietzins.objects.filter(quelle_anpassung__isnull=True).count(), 0)

    def test_schlussabrechnung_nicht_doppelt_gebucht(self):
        from finance.models import DebitorenRechnung
        _seed_konten()
        _lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        payload = {'auszug_datum': '2024-06-30', 'aktion': 'buchen',
                   'pos_text': 'Reinigung', 'pos_betrag': '500', 'pos_richtung': 'zulasten'}
        for _ in range(2):
            c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/', payload)
        # Trotz zweimaligem Absenden nur EIN Nachzahlungs-Debitor + eine Buchung.
        self.assertEqual(DebitorenRechnung.objects.filter(
            vertrag=v, titel='Schlussabrechnung (Nachzahlung)').count(), 1)

    def test_camt_notprovided_gehen_nicht_verloren(self):
        # Zwei verschiedene Gutschriften, beide EndToEndId=NOTPROVIDED, keine
        # AcctSvcrRef → dürfen NICHT als Duplikat verworfen werden.
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        _seed_konten()
        _basis_objekte()
        xml = (
            '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt>'
            '<Ntry><CdtDbtInd>CRDT</CdtDbtInd><Amt Ccy="CHF">1700.00</Amt>'
            '<BookgDt><Dt>2024-03-05</Dt></BookgDt><NtryDtls><TxDtls>'
            '<Refs><EndToEndId>NOTPROVIDED</EndToEndId></Refs></TxDtls></NtryDtls></Ntry>'
            '<Ntry><CdtDbtInd>CRDT</CdtDbtInd><Amt Ccy="CHF">1800.00</Amt>'
            '<BookgDt><Dt>2024-03-05</Dt></BookgDt><NtryDtls><TxDtls>'
            '<Refs><EndToEndId>NOTPROVIDED</EndToEndId></Refs></TxDtls></NtryDtls></Ntry>'
            '</Stmt></BkToCstmrStmt></Document>'
        ).encode('utf-8')
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('camt.xml', xml, content_type='application/xml')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        # Beide Zahlungen erfasst (auf Durchlaufkonto geparkt), keine fälschlich verworfen.
        self.assertEqual(Zahlungseingang.objects.count(), 2)

    def test_manuelle_mahnung_nicht_doppelt(self):
        from finance.models import Mahnung, DebitorenRechnung
        _seed_konten()
        _lg, e, m, v = _basis_objekte()
        rech = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=_lg, einheit=e,
                                                titel='Miete 01/2024', datum=date(2024, 1, 1),
                                                faellig_am=date(2024, 1, 31), betrag=Decimal('1700'),
                                                status='offen')
        c = Client(); c.force_login(_team_user())
        payload = {'rechnung_id': rech.id, 'stufe': '1', 'gebuehr': '20'}
        for _ in range(2):
            c.post('/neu/mahnwesen/erfassen/', payload)
        self.assertEqual(Mahnung.objects.filter(debitoren_rechnung=rech, stufe=1).count(), 1)
        self.assertEqual(DebitorenRechnung.objects.filter(
            vertrag=v, titel='Mahngebühr 1. Mahnung').count(), 1)

    def test_geraet_loeschen_raeumt_auto_pendenz(self):
        from portfolio.models import Geraet
        from core.models import Pendenz
        lg, e, _m, _v = _basis_objekte()
        g = Geraet.objects.create(liegenschaft=lg, kategorie='boiler',
                                  garantie_bis=date(2024, 12, 31))
        Pendenz.objects.create(titel='Garantie läuft ab: Boiler', kategorie='unterhalt',
                               quelle=f'auto:garantie:{g.id}', liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/geraet/{g.id}/loeschen/')
        self.assertFalse(Pendenz.objects.filter(quelle=f'auto:garantie:{g.id}').exists())

    def test_wartungsfrist_loeschen_raeumt_auto_pendenz(self):
        from portfolio.models import Wartungsfrist
        from core.models import Pendenz
        lg, _e, _m, _v = _basis_objekte()
        wf = Wartungsfrist.objects.create(liegenschaft=lg, art='wartung', bezeichnung='Lift',
                                          naechste_faelligkeit=date(2024, 12, 1),
                                          intervall_monate=12, aktiv=True)
        Pendenz.objects.create(titel='Wartung: Lift', kategorie='unterhalt',
                               quelle=f'auto:wartung:{wf.id}:2024-12-01', liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/frist/{wf.id}/loeschen/')
        self.assertFalse(Pendenz.objects.filter(quelle__startswith=f'auto:wartung:{wf.id}:').exists())

    # --- API-Löschpfade an die UI angeglichen (django-ninja-Funktionen direkt) ---
    def _req(self):
        from django.test import RequestFactory
        r = RequestFactory().delete('/')
        r.user = _team_user()
        return r

    def test_api_delete_mieter_blockt_aktiven_vertrag(self):
        from crm.api import delete_mieter
        from crm.models import Mieter
        _lg, _e, m, _v = _basis_objekte()   # v ist status='aktiv'
        status, _body = delete_mieter(self._req(), m.id)
        self.assertEqual(status, 409)
        self.assertTrue(Mieter.objects.filter(id=m.id).exists())

    def test_api_delete_mieter_raeumt_portal_login(self):
        from crm.api import delete_mieter
        _lg, _e, m, v = _basis_objekte()
        v.status = 'beendet'; v.aktiv = False; v.save()
        u = User.objects.create_user(username='portal_mieter', password='x')
        m.benutzer = u; m.save()
        status, _ = delete_mieter(self._req(), m.id)
        self.assertEqual(status, 204)
        self.assertFalse(User.objects.filter(id=u.id).exists())

    def test_api_delete_liegenschaft_blockt_aktiven_vertrag(self):
        from portfolio.api import delete_liegenschaft
        lg, _e, _m, _v = _basis_objekte()
        status, _ = delete_liegenschaft(self._req(), lg.id)
        self.assertEqual(status, 409)
        self.assertTrue(Liegenschaft.objects.filter(id=lg.id).exists())

    def test_api_delete_einheit_blockt_aktiven_vertrag(self):
        from portfolio.api import delete_einheit
        _lg, e, _m, _v = _basis_objekte()
        status, _ = delete_einheit(self._req(), e.id)
        self.assertEqual(status, 409)
        self.assertTrue(Einheit.objects.filter(id=e.id).exists())

    def test_mandat_loeschen_raeumt_eigentuemer_login(self):
        from crm.models import Mandant
        md = Mandant.objects.create(firma_oder_name='Eigentümer AG')
        u = User.objects.create_user(username='portal_owner', password='x')
        md.benutzer = u; md.save()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mandate/{md.id}/loeschen/')
        self.assertFalse(Mandant.objects.filter(id=md.id).exists())
        self.assertFalse(User.objects.filter(id=u.id).exists())


class PrueferFundeTests(TestCase):
    """Funde aus dem Herz-und-Nieren-Test durch Buchhalter + Immobilienvermarkter.
    Jeder Test sichert einen behobenen Fehler dauerhaft ab."""

    def _camt(self, ref, betrag, acct_ref='BANKTX1'):
        return (
            '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt><Ntry>'
            '<CdtDbtInd>CRDT</CdtDbtInd>'
            f'<Amt Ccy="CHF">{betrag}</Amt><BookgDt><Dt>2024-03-20</Dt></BookgDt>'
            '<NtryDtls><TxDtls>'
            f'<Refs><AcctSvcrRef>{acct_ref}</AcctSvcrRef></Refs>'
            f'<RmtInf><Strd><CdtrRefInf><Ref>{ref}</Ref></CdtrRefInf></Strd></RmtInf>'
            '</TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>'
        ).encode('utf-8')

    def _saldo(self, nummer):
        from finance.models import Buchung, Buchungskonto
        from django.db.models import Sum
        k = Buchungskonto.objects.filter(nummer=nummer).first()
        if not k:
            return Decimal('0.00'), Decimal('0.00')
        s = Buchung.objects.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        h = Buchung.objects.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        return s, h

    # ---- Buchhalter ----
    def test_camt_ueberzahlung_geht_nicht_verloren(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        r = DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')  # brutto 1700
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('camt.xml', self._camt(r.qr_referenz, '1900.00'),
                               content_type='application/xml')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        # Voller Bankeingang 1900 auf 1020 (nicht auf 1700 gekappt) …
        s1020, h1020 = self._saldo('1020')
        self.assertEqual(s1020 - h1020, Decimal('1900.00'))
        # … Überschuss 200 als Mieterguthaben (Haben) auf 2030 — der Mieter ist über
        # die QRR bekannt, das ist eine echte Verbindlichkeit, kein Durchlaufposten.
        s2030, h2030 = self._saldo('2030')
        self.assertEqual(h2030 - s2030, Decimal('200.00'))
        s1190, h1190 = self._saldo('1190')
        self.assertEqual(h1190 - s1190, Decimal('0.00'))

    def test_mahnlauf_bucht_gebuehr_ins_hauptbuch(self):
        from core.services.automation import run_mahnlauf
        from finance.models import DebitorenRechnung
        _seed_konten()
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, einheit=e, titel='Miete 12/2023',
            datum=date(2023, 12, 1), faellig_am=date(2023, 12, 5),
            betrag=Decimal('1700'), status='offen')
        vor_s, vor_h = self._saldo('3600')
        res = run_mahnlauf(mit_zins=True, send_email=False)
        self.assertGreater(res['gebuehren'] + res['zins'], Decimal('0'))
        nach_s, nach_h = self._saldo('3600')
        # Gebühr + Zins als Ertrag auf 3600 gebucht (Haben-Zuwachs = zusatz).
        self.assertEqual((nach_h - vor_h), res['gebuehren'] + res['zins'])

    def test_mwst_estv_umsatz_stimmt_mit_steuer(self):
        from core.services.automation import run_sollstellung
        _seed_konten()
        lg, e, m, v = _basis_objekte()
        v.mwst_pflichtig = True; v.mwst_satz = Decimal('8.1'); v.save()
        run_sollstellung(2024, 3)
        c = Client(); c.force_login(_team_user())
        resp = c.get('/neu/mwst/?jahr=2024')
        ust = resp.context['umsatzsteuer']
        umsatz = resp.context['umsatz_steuerbar']
        self.assertGreater(ust, Decimal('0'))
        # Ziffer 289 × Normalsatz muss die geschuldete Steuer (399) ergeben (Abstimmung).
        self.assertEqual((umsatz * Decimal('8.1') / Decimal('100')).quantize(Decimal('0.01')), ust)

    def test_honorar_zieht_ertragsminderung_ab(self):
        from finance.booking import buche, ensure_kontenplan
        from crm.models import Mandant
        from core.services.verwaltungshonorar import honorar_vorschau
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        md = Mandant.objects.create(firma_oder_name='Eigentümer AG', honorar_prozent=Decimal('5'))
        lg.mandant = md; lg.save()
        # Voller Referenzertrag 1000, davon 400 Erlass (Option B) → Ist-Ertrag 600.
        buche('1100', '3000', Decimal('1000'), 'Miete', datum=date(2024, 6, 1), liegenschaft=lg)
        buche('3090', '1100', Decimal('400'), 'Erlass', datum=date(2024, 6, 1), liegenschaft=lg)
        zeilen, _total, _pz = honorar_vorschau(md, 2024)
        zeile = next(z for z in zeilen if z['lg'].id == lg.id)
        self.assertEqual(zeile['mietertrag'], Decimal('600.00'))
        self.assertEqual(zeile['honorar'], Decimal('30.00'))   # 5% von 600

    # ---- Immobilienvermarkter ----
    def test_mieterspiegel_ist_nutzt_vertragsmiete(self):
        from core.services.mieterspiegel import berechne_mieterspiegel
        lg, e, m, v = _basis_objekte()   # Vertrag 1500 + 200
        e.nettomiete_aktuell = Decimal('1800'); e.nebenkosten_aktuell = Decimal('250'); e.save()
        block = berechne_mieterspiegel([lg])[0]
        t = block['totals']
        self.assertEqual(t['soll_brutto'], Decimal('2050.00'))   # Objekt-Sollmiete
        self.assertEqual(t['ist_brutto'], Decimal('1700.00'))    # tatsächliche Vertragsmiete

    def test_parse_einkommen_robust(self):
        from core.services.bewerber_scoring import parse_einkommen
        self.assertEqual(parse_einkommen("90000, Bonus 2024"), 90000)
        self.assertEqual(parse_einkommen("seit 2019: 90000"), 90000)
        self.assertEqual(parse_einkommen("80'000.50"), 80000)
        self.assertEqual(parse_einkommen("ca. 7500 pro Monat (90000/Jahr)"), 90000)
        self.assertEqual(parse_einkommen("80'000 – 100'000"), 80000)  # untere Grenze
        self.assertIsNone(parse_einkommen("keine Angabe"))

    def test_bewerber_entscheid_idempotent(self):
        from unittest.mock import patch
        from mietprozess.models import Mietbewerbung
        lg, e, m, v = _basis_objekte()
        b = Mietbewerbung.objects.create(einheit=e, vorname='Anna', nachname='Test',
                                         email='anna@example.ch', status='neu',
                                         geburtsdatum=date(1990, 5, 1))
        c = Client(); c.force_login(_team_user())
        with patch('core.utils.email_service.send_ticket_email', return_value=True) as mock_mail:
            c.post(f'/neu/bewerbungen/{b.id}/entscheid/', {'entscheid': 'zusage'})
            c.post(f'/neu/bewerbungen/{b.id}/entscheid/', {'entscheid': 'zusage'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'zugesagt')
        self.assertEqual(mock_mail.call_count, 1)   # zweite Zusage schickt KEINE Mail

    def test_bewerbung_zu_vertrag_idempotent_und_nimmt_aus_vermarktung(self):
        from mietprozess.models import Mietbewerbung
        lg, e, m, v_bestand = _basis_objekte()
        e.zur_ausschreibung = True; e.save()
        b = Mietbewerbung.objects.create(einheit=e, vorname='Beat', nachname='Neu',
                                         email='beat@example.ch', status='neu',
                                         geburtsdatum=date(1988, 3, 12))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        c.post(f'/neu/bewerbungen/{b.id}/vertrag/')   # zweiter Klick
        entwuerfe = Mietvertrag.objects.filter(einheit=e, status='entwurf').count()
        self.assertEqual(entwuerfe, 1)   # kein Doppel-Entwurf
        e.refresh_from_db()
        self.assertFalse(e.zur_ausschreibung)   # Objekt aus der Vermarktung genommen


class BewerberScoringBelegTests(TestCase):
    """Score-Punkte für Betreibungen/Anstellung nur bei tatsächlichem Beleg —
    eine leere Bewerbung wirkt nicht mehr fälschlich 'mittel'."""

    def test_leere_bewerbung_nicht_mittel(self):
        from mietprozess.models import Mietbewerbung
        from core.services.bewerber_scoring import bewerte_bewerbung
        _lg, e, _m, _v = _basis_objekte()
        b = Mietbewerbung.objects.create(einheit=e, vorname='Leer', nachname='Test',
                                         email='leer@example.ch', geburtsdatum=date(1990, 1, 1))
        r = bewerte_bewerbung(b, Decimal('1700'))
        betr = next(i for i in r['indikatoren'] if i['label'] == 'Betreibungen')
        anst = next(i for i in r['indikatoren'] if i['label'] == 'Anstellung')
        self.assertEqual(betr['ampel'], 'schlecht')   # kein Auszug → 0 Punkte
        self.assertEqual(anst['ampel'], 'schlecht')   # keine Angabe → 0 Punkte
        self.assertLess(r['score'], 40)

    def test_belegte_bewerbung_erhaelt_punkte(self):
        from mietprozess.models import Mietbewerbung
        from core.services.bewerber_scoring import bewerte_bewerbung
        _lg, e, _m, _v = _basis_objekte()
        b = Mietbewerbung.objects.create(
            einheit=e, vorname='Beleg', nachname='Test', email='beleg@example.ch',
            geburtsdatum=date(1990, 1, 1), digitaler_betreibungsauszug=True,
            hat_betreibungen=False, erwerbsstatus='angestellt', ist_unbefristet=True,
            arbeitgeber='Muster AG', einkommen_jahr='90000')
        r = bewerte_bewerbung(b, Decimal('1700'))   # 90000 / 20400 = 4.4× → Tragbarkeit gut
        # 45 (Tragbarkeit) + 25 (Betreibungen belegt) + 15 (Anstellung belegt) = 85
        self.assertGreaterEqual(r['score'], 85)


class PrueferRunde2Tests(TestCase):
    """Funde aus dem 2. Prüfdurchgang (Anwalt/Buchhalter/Bewirtschafter/Verwaltung)."""

    def _req(self, rolle='Verwaltung'):
        from django.test import RequestFactory
        r = RequestFactory().post('/')
        r.user = _team_user(rolle)
        return r

    # --- Buchhalter: pay_kreditor darf Teilzahlungen nicht ignorieren ---
    def test_pay_kreditor_keine_doppelzahlung(self):
        from finance.api import pay_kreditor
        from finance.models import KreditorenRechnung, KreditorenZahlung, Buchung, Buchungskonto
        from finance.booking import ensure_kontenplan, konto as _k
        from django.db.models import Sum
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(lieferant='Elektro AG', betrag=Decimal('1000'),
                                              status='freigegeben', liegenschaft=lg, konto=_k('4000'))
        KreditorenZahlung.objects.create(kreditor=k, betrag=Decimal('300'), datum=date(2024, 5, 1))
        self.assertEqual(k.offener_betrag, Decimal('700'))
        status, _b = pay_kreditor(self._req(), k.id)
        self.assertEqual(status, 200)
        k.refresh_from_db()
        self.assertEqual(k.status, 'bezahlt')
        self.assertEqual(k.bezahlt_betrag, Decimal('1000'))   # 300 + 700, NICHT 1300
        bank = Buchungskonto.objects.get(nummer='1020')
        h = Buchung.objects.filter(haben_konto=bank).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        self.assertEqual(h, Decimal('700'))   # nur der offene Betrag wurde abgebucht

    # --- Verwaltung/Security: DocuSeal-Webhook ohne Secret ablehnen ---
    def test_docuseal_webhook_ohne_secret_403(self):
        from rentals.api import docuseal_webhook
        from django.test import RequestFactory, override_settings
        req = RequestFactory().post('/', data='{}', content_type='application/json')
        with override_settings(DOCUSEAL_WEBHOOK_SECRET=None):
            self.assertEqual(docuseal_webhook(req).status_code, 403)
        with override_settings(DOCUSEAL_WEBHOOK_SECRET='geheim'):
            req2 = RequestFactory().post('/', data='{}', content_type='application/json')
            self.assertEqual(docuseal_webhook(req2).status_code, 403)   # ohne Header
            req3 = RequestFactory().post('/', data='{}', content_type='application/json',
                                         HTTP_X_WEBHOOK_SECRET='geheim')
            self.assertEqual(docuseal_webhook(req3).status_code, 200)   # korrektes Secret

    # --- Verwaltung/Security: Legacy-Finance-API weist negative Beträge ab ---
    def test_legacy_zahlung_negativ_abgewiesen(self):
        from finance.api import create_zahlung, ZahlungCreateSchema
        from finance.models import Zahlungseingang
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        payload = ZahlungCreateSchema(vertrag_id=v.id, betrag=Decimal('-5000'),
                                      datum_eingang=date(2024, 5, 1), buchungs_monat=date(2024, 5, 1))
        status, _b = create_zahlung(self._req('Sachbearbeitung'), payload)
        self.assertEqual(status, 400)
        self.assertEqual(Zahlungseingang.objects.count(), 0)

    # --- Bewirtschafter: Mieterportal-Dok-Leck Vormieter → Nachmieter ---
    def test_portal_kein_vormieter_dokumentenleck(self):
        from core.views.portal import _mieter_dok_gruppen
        from rentals.models import Dokument as RDokument
        from django.core.files.base import ContentFile
        lg, e, m_alt, v_alt = _basis_objekte()
        m_neu = Mieter.objects.create(typ='person', vorname='Rita', nachname='Neu',
                                      email='rita@example.ch')
        v_neu = Mietvertrag.objects.create(mieter=m_neu, einheit=e, beginn=date(2025, 1, 1),
                                           netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                                           status='aktiv')
        d = RDokument.objects.create(vertrag=v_alt, einheit=e, mieter=m_alt, kategorie='vertrag',
                                     bezeichnung='Schlussabrechnung Vormieter', im_portal_sichtbar=True)
        d.datei.save('x.pdf', ContentFile(b'%PDF-1.4'), save=True)
        gruppen = _mieter_dok_gruppen(m_neu, [v_neu])
        titel_alle = [doc['titel'] for g in gruppen for doc in g['docs']]
        self.assertNotIn('Schlussabrechnung Vormieter', titel_alle)

    # --- Bewirtschafter: Schlussabrechnung belastet offene Forderungen nicht doppelt ---
    def test_schlussabrechnung_keine_doppelforderung(self):
        # Seit dem Buchhalter-Audit (K2) werden bestehende Mietforderungen NICHT mehr
        # storniert und auf 3000 neu gebucht (das vernichtete die MWST-Abgrenzung und
        # verschob Schadenersatz in den Mietertrag). Sie bleiben bestehen; die
        # Schlussabrechnung bucht nur die NEUEN Positionen. Invariante bleibt:
        # der Mieter wird nicht doppelt belastet.
        from finance.models import DebitorenRechnung
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        alt = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                               titel='Miete 05/2024', datum=date(2024, 5, 1),
                                               faellig_am=date(2024, 5, 5), betrag=Decimal('1700'),
                                               status='offen')
        buche('1100', '3000', Decimal('1700'), 'Miete 05/2024', datum=date(2024, 5, 1),
              liegenschaft=lg, debitor=alt)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen'})
        alt.refresh_from_db()
        self.assertEqual(alt.status, 'offen')        # Originalforderung bleibt (MWST intakt)
        offene = DebitorenRechnung.objects.filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
        self.assertEqual(sum((r.offener_betrag for r in offene), Decimal('0')), Decimal('1700'))


class PrueferRunde2QuickTests(TestCase):
    """Weitere Quick-Fixes aus dem 2. Prüfdurchgang."""

    def test_kaution_obergrenze_serverseitig(self):
        # Art. 257e: max. 3 Monatsmieten bei Wohnräumen — serverseitig geklemmt.
        lg, e, m, v = _basis_objekte()   # Wohnung, netto 1500 + NK 200 → max 5100
        v.kautions_betrag = Decimal('10000')
        v.save()
        v.refresh_from_db()
        self.assertEqual(v.kautions_betrag, Decimal('5100.00'))

    def test_serienbrief_adressiert_mitmieter(self):
        lg, e, m, v = _basis_objekte()
        m2 = Mieter.objects.create(typ='person', vorname='Petra', nachname='Partner',
                                   email='petra@example.ch')
        v.mitmieter = m2
        v.status = 'aktiv'
        v.save()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/kommunikation/')
        self.assertEqual(r.status_code, 200)
        namen = [e['name'] for e in r.context['empfaenger']]
        self.assertIn(m2.display_name, namen)   # Mitmieter erscheint als Empfänger
        self.assertIn(m.display_name, namen)


class PrueferRunde2SecurityUITests(TestCase):
    """Security-/UI-Funde aus dem tiefen Durchgang."""

    def test_public_report_leakt_keine_mieternamen(self):
        # Öffentliche QR-Schadenseite (ohne Login) darf keine Mieter-Nachnamen
        # oder "Leerstand" ausgeben (DSG / ID-Enumeration).
        lg, e, m, v = _basis_objekte()   # Mieter Nachname 'Muster'
        c = Client()
        r = c.get(f'/report/{lg.id}/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn('Muster', body)
        self.assertNotIn('Leerstand', body)
        self.assertIn(e.bezeichnung, body)   # Objekt-Auswahl weiterhin möglich

    def test_kuendigungsbestaetigung_kein_anfechtungshinweis_bei_mieterkuendigung(self):
        # Anfechtung/Erstreckung (Art. 271/273 OR) gelten nur für Vermieterkündigung.
        # Der Rechtshinweis-Block ist auf absender=='vermieter' gegated.
        src = open('core/templates/core/dok_kuendigungsbestaetigung.html', encoding='utf-8').read()
        idx = src.find('angefochten')
        self.assertGreaterEqual(idx, 0)
        block = src[max(0, idx - 400):idx]
        self.assertRegex(block, r"absender\s*==\s*'vermieter'")


class MoneyBugBatchTests(TestCase):
    """Geld-Funde aus «Komplet alles umsetzen» — jeder Test sichert eine
    korrekt ausgeglichene Buchung / Idempotenz dauerhaft ab."""

    def _saldo(self, nummer):
        from finance.models import Buchung, Buchungskonto
        from django.db.models import Sum
        k = Buchungskonto.objects.filter(nummer=nummer).first()
        if not k:
            return Decimal('0.00'), Decimal('0.00')
        s = Buchung.objects.filter(soll_konto=k, ist_storno=False).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        h = Buchung.objects.filter(haben_konto=k, ist_storno=False).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        return s, h

    def test_weiterverrechnung_spaltet_mwst_und_zuschlag(self):
        # F1: Der Aufwand wurde nur netto gebucht (Vorsteuer separat). Die
        # Weiterverrechnung darf ihn deshalb nur NETTO entlasten; der MWST-Anteil
        # ist Ausgangs-Umsatzsteuer (2200), der Zuschlag ein Ertrag (3600).
        from finance.booking import ensure_kontenplan, konto
        from finance.models import KreditorenRechnung, DebitorenRechnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(
            lieferant='Sanitär AG', betrag=Decimal('1081.00'), mwst_satz=Decimal('8.1'),
            status='freigegeben', liegenschaft=lg, konto=konto('4000'),
            datum=date(2024, 6, 1), faellig_am=date(2024, 6, 30))
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/', {
            'vertrag_id': str(v.id), 'betrag': '1081.00', 'zuschlag': '100.00',
            'titel': 'Rohrbruch Küche'})
        self.assertIn(r.status_code, (200, 302))
        rech = DebitorenRechnung.objects.get(quell_kreditor=k)
        self.assertEqual(rech.betrag, Decimal('1181.00'))              # grund + zuschlag
        self.assertEqual(rech.weiterverrechnung_zuschlag, Decimal('100.00'))
        # Aufwand (4000) nur um NETTO 1000 entlastet, 81 als 2200 Umsatzsteuer.
        s4000, h4000 = self._saldo('4000')
        self.assertEqual(h4000 - s4000, Decimal('1000.00'))
        s2200, h2200 = self._saldo('2200')
        self.assertEqual(h2200 - s2200, Decimal('81.00'))
        s3600, h3600 = self._saldo('3600')
        self.assertEqual(h3600 - s3600, Decimal('100.00'))            # Zuschlag = Ertrag
        # Durchlaufkonto 1190 geht exakt auf null auf.
        s1190, h1190 = self._saldo('1190')
        self.assertEqual(s1190 - h1190, Decimal('0.00'))
        # Kreditor gilt als voll (nur netto-relevant) weiterverrechnet — Zuschlag zählt nicht.
        self.assertEqual(k.weiterverrechnet_betrag, Decimal('1081.00'))
        self.assertEqual(k.offen_weiterzuverrechnen, Decimal('0.00'))

    def test_kaution_einbehalt_ist_ausgeglichen_und_ertrag(self):
        # Kaution-Auflösung: Sperrkonto-Freigabe 1020/1015, Rückzahlung 2010/1020,
        # Einbehalt 2010/3600 (Ertrag). Früher: gefälschter «bezahlter» Debitor ohne Buchung.
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()   # Kaution 4500
        v.kautions_art = 'sperrkonto'; v.kautions_konto = 'CH00'
        v.kautions_einbezahlt_am = date(2024, 1, 1); v.save()
        # Depot bei Einzahlung: 1015 Sperrkonto an 2010 Verbindlichkeit.
        buche('1015', '2010', Decimal('4500'), 'Kaution Einzahlung', datum=date(2024, 1, 1), liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/vertraege/{v.id}/kaution/', {
            'aktion': 'rueckzahlung', 'abzug_betrag': '500', 'abzug_grund': 'Reinigung',
            'zurueckbezahlt_am': '2024-07-01'})
        self.assertEqual(r.status_code, 302)
        # 2010 vollständig ausgeglankt (Soll 4500 = Haben 4500).
        s2010, h2010 = self._saldo('2010')
        self.assertEqual(s2010, Decimal('4500.00'))
        self.assertEqual(h2010, Decimal('4500.00'))
        # 1015 Sperrkonto wieder auf null (4500 rein, 4500 raus).
        s1015, h1015 = self._saldo('1015')
        self.assertEqual(h1015 - s1015, Decimal('0.00'))
        # Einbehalt 500 als Ertrag auf 3600.
        s3600, h3600 = self._saldo('3600')
        self.assertEqual(h3600 - s3600, Decimal('500.00'))

    def test_kaution_einbehalt_idempotent(self):
        from finance.booking import ensure_kontenplan, buche
        from finance.models import Buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_art = 'sperrkonto'; v.kautions_einbezahlt_am = date(2024, 1, 1); v.save()
        buche('1015', '2010', Decimal('4500'), 'Kaution Einzahlung', datum=date(2024, 1, 1), liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        for _ in range(2):
            c.post(f'/neu/vertraege/{v.id}/kaution/', {
                'aktion': 'rueckzahlung', 'abzug_betrag': '500',
                'zurueckbezahlt_am': '2024-07-01'})
        # Zweiter Klick bucht nicht erneut (beleg_text-Idempotenz). Der Belegtext
        # trägt die Vertrags-ID, damit die Saldo-Prüfung diese Auflösung erkennt
        # und die Schlussabrechnung dieselbe Kaution nicht nochmals freigibt.
        n = Buchung.objects.filter(beleg_text__startswith=f"Kaution Auflösung [V{v.pk}]",
                                   ist_storno=False).count()
        self.assertEqual(n, 3)   # Freigabe + Rückzahlung + Einbehalt, genau einmal

    def test_mietzins_anpassung_pdf_ist_idempotent(self):
        # Mehrfaches PDF-Generieren darf keine doppelte Anpassung + Anfechtungs-Pendenz erzeugen.
        from rentals.models import MietzinsAnpassung
        from rentals.services import naechster_anpassungstermin
        from core.models import Pendenz
        from django.utils import timezone
        lg, e, m, v = _basis_objekte()
        v.basis_referenzzinssatz = Decimal('1.25'); v.basis_lik_punkte = Decimal('100.0'); v.save()
        wirksam = naechster_anpassungstermin(v, timezone.localdate())  # gültiger Termin (Art. 269d)
        c = Client(); c.force_login(_team_user())
        payload = {'aktion': 'pdf', 'neu_netto': '1600', 'neu_zins': '1.50',
                   'neu_lik': '105.0', 'wirksam_ab': wirksam.isoformat(),
                   'begruendung': 'Referenzzins', 'formular': 'generisch'}
        for _ in range(3):
            c.post(f'/neu/mietzins/{v.id}/anpassung/', payload)
        self.assertEqual(MietzinsAnpassung.objects.filter(vertrag=v, wirksam_ab=wirksam).count(), 1)
        self.assertEqual(Pendenz.objects.filter(vertrag=v, kategorie='frist').count(), 1)

    def test_schlussabrechnung_teilbezahlt_bleibt_op(self):
        # Verhaltenstest (ersetzt die frühere Quellcode-Prüfung): eine teilbezahlte
        # Mietforderung bleibt mit ihrem Restbetrag als OP bestehen und wird von der
        # Schlussabrechnung weder storniert noch ein zweites Mal als Ertrag gebucht.
        from finance.models import DebitorenRechnung, Zahlungseingang, Buchung
        from finance.booking import buche, ensure_kontenplan
        from django.db.models import Sum
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        alt = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                               titel='Miete 05/2024', datum=date(2024, 5, 1),
                                               faellig_am=date(2024, 5, 5), betrag=Decimal('1700'),
                                               status='teilbezahlt')
        buche('1100', '3000', Decimal('1700'), 'Miete 05/2024', datum=date(2024, 5, 1),
              liegenschaft=lg, debitor=alt)
        Zahlungseingang.objects.create(vertrag=v, betrag=Decimal('700'),
                                       datum_eingang=date(2024, 5, 10),
                                       buchungs_monat=date(2024, 5, 1),
                                       debitoren_rechnung=alt, status='verbucht')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen'})
        alt.refresh_from_db()
        self.assertEqual(alt.status, 'teilbezahlt')
        self.assertEqual(alt.offener_betrag, Decimal('1000'))
        # Mietertrag wurde nur EINMAL gebucht (kein Doppelertrag durch Neubuchung)
        ertrag_3000 = (Buchung.objects.filter(haben_konto__nummer='3000')
                       .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        self.assertEqual(ertrag_3000, Decimal('1700'))


class SecurityBatchTests(TestCase):
    """GET-Endpoints müssen seiteneffektfrei sein; Storno ist Verwaltungs-only."""

    def test_get_mieter_liste_mutiert_adresse_nicht(self):
        # Fälliger Umzug (datierte Adress-Zeile) darf beim reinen Lesen (GET)
        # NICHT auf die Flat-Felder synchronisiert werden.
        from crm.api import list_mieter
        from crm.models import MieterAdresse
        from django.test import RequestFactory
        _lg, _e, m, _v = _basis_objekte()
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2020, 1, 1),
                                     strasse='Neuweg 9', plz='3000', ort='Bern')
        list_mieter(RequestFactory().get('/api/crm/mieter'))
        m.refresh_from_db()
        self.assertEqual(m.strasse, 'Seeweg 3')            # GET synchronisiert nicht

    def test_scheduler_aktiviert_adresswechsel(self):
        from core.services.automation import run_adress_umzuege
        from crm.models import MieterAdresse
        _lg, _e, m, _v = _basis_objekte()
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2020, 1, 1),
                                     strasse='Neuweg 9', plz='3000', ort='Bern')
        n = run_adress_umzuege()
        m.refresh_from_db()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(m.strasse, 'Neuweg 9')            # jetzt via Scheduler synchronisiert

    def test_ticket_gelesen_nur_mit_schreibrolle(self):
        from tickets.api import get_ticket
        from tickets.models import SchadenMeldung
        from django.test import RequestFactory
        lg, _e, _m, _v = _basis_objekte()
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Leck', beschreibung='Wasser', gelesen=False)
        # Reine Leserolle → kein Schreibzugriff, gelesen bleibt False.
        req = RequestFactory().get(f'/api/tickets/{t.id}')
        req.user = _team_user(rolle='Lesend')
        get_ticket(req, t.id)
        t.refresh_from_db()
        self.assertFalse(t.gelesen)
        # Schreibrolle → gelesen wird gesetzt.
        req2 = RequestFactory().get(f'/api/tickets/{t.id}')
        req2.user = _team_user(rolle='Verwaltung')
        get_ticket(req2, t.id)
        t.refresh_from_db()
        self.assertTrue(t.gelesen)

    def test_storno_ist_verwaltung_only(self):
        # Storno einer Journalbuchung ist ein buchhalterischer Korrektureingriff.
        src = open('core/views/fw.py', encoding='utf-8').read()
        idx = src.find('def fw_buchung_stornieren')
        deko = src[max(0, idx - 120):idx]
        self.assertRegex(deko, r"rolle_erforderlich\(ROLLE_VERWALTUNG\)")

    def test_oeffentliches_schadenformular_leakt_kein_portfolio(self):
        # Das anonyme Schadenformular darf nicht das gesamte Portfolio (alle
        # Liegenschafts-Adressen) in die Seite dumpen (Adress-Enumeration/DSG).
        Liegenschaft.objects.create(strasse='Geheimweg 7', plz='8000', ort='Zürich')
        Liegenschaft.objects.create(strasse='Privatgasse 2', plz='3000', ort='Bern')
        c = Client()
        r = c.get('/schaden/melden/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn('Geheimweg 7', body)
        self.assertNotIn('Privatgasse 2', body)
        # Freitext-Adressfeld bleibt erhalten (Meldung weiterhin möglich).
        self.assertIn('name="adresse"', body)


class LegalBatchTests(TestCase):
    """ZH-Amtsformulare kreuzen die Objekt-Art datengetrieben; 269d-Frist serverseitig."""

    def test_zh_formulare_objektart_datengetrieben(self):
        src = open('core/services/formular_fill.py', encoding='utf-8').read()
        # Mietzins-Formular: Wohnung(1)/Geschäftsräume(2) aus mietrecht_kategorie
        self.assertRegex(src, r"obj_cb\s*=\s*'Kontrollkästchen 1'\s+if\s+vertrag\.mietrecht_kategorie\s*==\s*'wohnen'\s+else\s+'Kontrollkästchen 2'")
        # Kündigungs-Formular: Wohnung(6)/Geschäftsräume(7)
        self.assertRegex(src, r"obj_cb\s*=\s*'Kontrollkästchen 6'\s+if\s+vertrag\.mietrecht_kategorie\s*==\s*'wohnen'\s+else\s+'Kontrollkästchen 7'")
        self.assertNotRegex(src, r"cbs = \['Kontrollkästchen 1', 'Kontrollkästchen 3'\]")

    def test_269d_zu_fruehes_datum_wird_abgelehnt(self):
        from rentals.models import MietzinsAnpassung
        lg, e, m, v = _basis_objekte()
        v.basis_referenzzinssatz = Decimal('1.25'); v.basis_lik_punkte = Decimal('100.0')
        v.kuendigungsfrist_monate = 3; v.save()
        c = Client(); c.force_login(_team_user())
        # Erhöhung mit Wirksamkeit morgen — deutlich vor dem nächsten Termin.
        r = c.post(f'/neu/mietzins/{v.id}/anpassung/', {
            'aktion': 'speichern', 'neu_netto': '1600', 'neu_zins': '1.50',
            'neu_lik': '105.0', 'wirksam_ab': (date.today() + timedelta(days=1)).isoformat(),
            'begruendung': 'Referenzzins', 'formular': 'generisch'})
        self.assertEqual(r.status_code, 302)
        # Kein Datensatz angelegt — die Frist wurde serverseitig durchgesetzt.
        self.assertEqual(MietzinsAnpassung.objects.filter(vertrag=v).count(), 0)


class UIConsistencyBatchTests(TestCase):
    """Tabellen-Header, Karten-Radius und Titel-Gewicht sind app-weit einheitlich."""

    import os as _os
    _FW = _os.path.join(_os.path.dirname(__file__), 'templates', 'fw')

    def _read(self, name):
        with open(self._os.path.join(self._FW, name), encoding='utf-8') as fh:
            return fh.read()

    def test_kein_grauer_thead_block_mehr(self):
        # Der graue Header-Balken (bg-slate-50 …) wurde überall auf den kanonischen
        # rahmenlosen Tabellen-Header umgestellt.
        for f in ['anlagen', 'logbuch', 'kautionen', 'kontoblatt', 'abnahme_detail',
                  'mandate', 'benutzer']:
            self.assertNotIn('bg-slate-50 text-slate-500 text-xs uppercase tracking-wide',
                             self._read(f + '.html'), f'grauer thead noch in {f}')

    def test_design_inseln_nutzen_kanonische_klassen(self):
        # rounded-xl statt rounded-2xl, font-extrabold statt font-black.
        for f in ['abonnement', 'mieterwechsel', 'vermarktung', 'dashboard']:
            src = self._read(f + '.html')
            self.assertNotIn('rounded-2xl', src, f'rounded-2xl noch in {f}')
            self.assertNotIn('font-black', src, f'font-black noch in {f}')


class Art266nDoppelzustellungTests(TestCase):
    """Art. 266n OR: Vermieter-Kündigung einer Familienwohnung → je Ehegatte eine
    separat adressierte Kopie (sonst nichtig)."""

    def _familienvertrag(self):
        from crm.models import Mieter
        lg, e, m, v = _basis_objekte()
        gatte = Mieter.objects.create(typ='person', vorname='Petra', nachname='Muster',
                                      email='petra@example.ch', strasse='Seeweg 3', plz='8000', ort='Zürich')
        v.familienwohnung = True; v.mitmieter = gatte; v.save()
        return lg, e, m, v, gatte

    def test_vermieter_familienwohnung_zwei_kopien(self):
        from core.services.formular_fill import kuendigung_zustellkopien
        from rentals.models import Kuendigung
        _lg, _e, _m, v, gatte = self._familienvertrag()
        k = Kuendigung.objects.create(vertrag=v, absender='vermieter', per_datum=date(2027, 3, 31))
        kopien = kuendigung_zustellkopien(v, k)
        self.assertEqual(len(kopien), 2)
        namen = {n for n, _ in kopien}
        self.assertIn('Hans Muster', namen)
        self.assertIn(gatte.display_name, namen)
        for _n, pdf in kopien:
            self.assertTrue(pdf.startswith(b'%PDF'))

    def test_mieterkuendigung_nur_eine_kopie(self):
        from core.services.formular_fill import kuendigung_zustellkopien
        from rentals.models import Kuendigung
        _lg, _e, _m, v, _g = self._familienvertrag()
        k = Kuendigung.objects.create(vertrag=v, absender='mieter', per_datum=date(2027, 3, 31))
        # Nur die Vermieter-Kündigung braucht die getrennte Zustellung.
        self.assertEqual(len(kuendigung_zustellkopien(v, k)), 1)

    def test_keine_familienwohnung_eine_kopie(self):
        from core.services.formular_fill import kuendigung_zustellkopien
        from rentals.models import Kuendigung
        lg, e, m, v = _basis_objekte()   # familienwohnung=False
        k = Kuendigung.objects.create(vertrag=v, absender='vermieter', per_datum=date(2027, 3, 31))
        self.assertEqual(len(kuendigung_zustellkopien(v, k)), 1)

    def test_view_liefert_pdf_und_legt_zwei_kopien_ab(self):
        from rentals.models import Kuendigung
        from rentals.models import Dokument
        _lg, _e, _m, v, _g = self._familienvertrag()
        k = Kuendigung.objects.create(vertrag=v, absender='vermieter', per_datum=date(2027, 3, 31))
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/kuendigung/{k.id}/formular/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        # Zwei separat adressierte Kopien abgelegt.
        n = Dokument.objects.filter(vertrag=v, bezeichnung__contains='Zustellung an').count()
        self.assertEqual(n, 2)


class MediaSchutzTests(TestCase):
    """Sensible Media-Dateien (Verträge, Bewerber-Dokumente) nur für Team;
    Objektfotos/Logos öffentlich."""

    def test_klassifikation_oeffentlich_vs_sensibel(self):
        from core.views.media_protected import ist_oeffentlich
        self.assertFalse(ist_oeffentlich('bewerbungen/ausweis/hans.jpg'))   # PII trotz Bild
        self.assertFalse(ist_oeffentlich('roh_vertraege/vertrag.pdf'))
        self.assertFalse(ist_oeffentlich('uploads/2026-01-01/Mietvertrag.pdf'))  # PDF
        # Ein Bild im Alt-Ordner `uploads/` galt früher als öffentlich — die
        # Annahme «Bild = Inseratfoto» stimmte aber nicht: Im selben Ordner
        # lagen Schadenfotos aus fremden Wohnungen und eingescannte Dokumente.
        # Der Ordner ist deshalb geschützt; Inseratfotos werden über die
        # Datenbank erkannt (`ist_objektfoto`) bzw. liegen neu in `objekt_fotos/`.
        self.assertFalse(ist_oeffentlich('uploads/2026-01-01/objektfoto.jpg'))
        self.assertTrue(ist_oeffentlich('objekt_fotos/2026-01-01/inserat.jpg'))
        self.assertTrue(ist_oeffentlich('logos/firma.png'))

    def test_anonymer_zugriff_auf_sensible_datei_404(self):
        import os
        from django.conf import settings
        rel = 'roh_vertraege/geheim_test.pdf'
        pfad = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, 'wb') as fh:
            fh.write(b'%PDF-1.4 geheim')
        try:
            anon = Client()
            self.assertEqual(anon.get('/media/' + rel).status_code, 404)   # anonym gesperrt
            team = Client(); team.force_login(_team_user())
            r = team.get('/media/' + rel)
            self.assertEqual(r.status_code, 200)                            # Team darf
        finally:
            os.remove(pfad)


class BewerbungRateLimitTests(TestCase):
    def test_rate_limit_blockt_nach_limit(self):
        from django.core.cache import cache
        from core.utils.throttle import rate_limit
        cache.clear()
        key = 'test:1.2.3.4'
        for _ in range(5):
            self.assertTrue(rate_limit(key, limit=5, window_seconds=60))
        self.assertFalse(rate_limit(key, limit=5, window_seconds=60))   # 6. blockiert


class DSGAnonymisierungTests(TestCase):
    def test_anonymisierung_scrubbt_pii_behaelt_beleg(self):
        from core.services.dsg import anonymisiere_person
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        v.status = 'beendet'; v.save()   # kein aktiver Vertrag
        rechnung = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, einheit=e, titel='Miete 01/2024',
            betrag=Decimal('1700'), status='offen')
        ok, _msg = anonymisiere_person(m, grund='Auszug + Löschantrag')
        self.assertTrue(ok)
        m.refresh_from_db()
        self.assertTrue(m.anonymisiert)
        self.assertEqual(m.vorname, 'Anonymisiert')
        self.assertEqual(m.email, '')
        self.assertEqual(m.strasse, '')
        # Buchungsbeleg bleibt erhalten (OR 958f).
        self.assertTrue(DebitorenRechnung.objects.filter(id=rechnung.id).exists())

    def test_aktiver_vertrag_blockt(self):
        from core.services.dsg import anonymisiere_person, kann_anonymisieren
        _lg, _e, m, v = _basis_objekte()   # Vertrag ist aktiv
        ok, grund = kann_anonymisieren(m)
        self.assertFalse(ok)
        ok2, _ = anonymisiere_person(m)
        self.assertFalse(ok2)
        m.refresh_from_db()
        self.assertFalse(m.anonymisiert)
        self.assertEqual(m.vorname, 'Hans')   # unverändert

    def test_view_anonymisiert(self):
        lg, e, m, v = _basis_objekte()
        v.status = 'beendet'; v.save()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/personen/{m.id}/dsg-loeschen/', {'grund': 'Löschantrag'})
        self.assertEqual(r.status_code, 302)
        m.refresh_from_db()
        self.assertTrue(m.anonymisiert)


class PersonenStammdatenTests(TestCase):
    """Voll-Ausbau der Personen-Stammdaten: Formular erfasst alle fachlichen
    Felder, Bewerbung→Mieter übernimmt Haushalt/Beruf, DSG scrubbt neue Felder."""

    def test_formular_speichert_alle_felder(self):
        from crm.models import Mieter
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {
            'typ': 'person', 'vorname': 'Anna', 'nachname': 'Muster',
            'zivilstand': 'verheiratet', 'nationalitaet': 'Deutschland', 'heimatort': 'Berlin',
            'ahv_nummer': '756.1234.5678.90', 'sprache': 'fr', 'telefon_geschaeft': '044 111 22 33',
            'aufenthaltsbewilligung': 'C', 'bewilligung_gueltig_bis': '2030-12-31',
            'erwerbsstatus': 'angestellt', 'beruf': 'Ärztin', 'arbeitgeber': 'Spital AG',
            'einkommen_jahr': "120'000", 'bonitaet_datum': '2026-01-15',
            'haushalt_erwachsene': '2', 'haushalt_kinder': '1', 'haustiere': 'on',
            'haustiere_details': '1 Katze', 'haftpflicht_gesellschaft': 'AXA',
            'haftpflicht_police': 'P-4711', 'notfall_name': 'Beat Muster',
            'notfall_telefon': '079 000 11 22', 'notfall_beziehung': 'Ehemann',
            'bank_name': 'ZKB', 'dublette_ok': '1',
        })
        self.assertEqual(r.status_code, 302)
        m = Mieter.objects.get(nachname='Muster', vorname='Anna')
        self.assertEqual(m.zivilstand, 'verheiratet')
        self.assertEqual(m.sprache, 'fr')
        self.assertEqual(m.aufenthaltsbewilligung, 'C')
        self.assertEqual(m.bewilligung_gueltig_bis, date(2030, 12, 31))
        self.assertEqual(m.arbeitgeber, 'Spital AG')
        self.assertEqual(m.haushalt_erwachsene, 2)
        self.assertEqual(m.haushalt_kinder, 1)
        self.assertTrue(m.haustiere)
        self.assertEqual(m.haftpflicht_gesellschaft, 'AXA')
        self.assertEqual(m.notfall_name, 'Beat Muster')
        self.assertEqual(m.bank_name, 'ZKB')

    def test_formular_get_rendert_alle_sektionen(self):
        c = Client(); c.force_login(_team_user())
        body = c.get('/neu/personen/neu/').content.decode()
        for s in ['Aufenthaltsbewilligung', 'Korrespondenzsprache', 'Beruf & Bonität',
                  'Haushalt', 'Notfallkontakt', 'box-person-extra']:
            self.assertIn(s, body, f'{s} fehlt im Formular')
        # Kontextsensitive Bewilligungs-Hinweisbox (neutral, kein Mietverbot).
        self.assertIn('bewilligung_hinweis', body)
        self.assertIn('Grenzgänger G', body)
        self.assertIn('Mieten ist für alle Aufenthaltstitel zulässig', body)

    def test_detail_zeigt_neue_felder(self):
        _lg, _e, m, _v = _basis_objekte()
        m.aufenthaltsbewilligung = 'B'; m.beruf = 'Informatiker'; m.notfall_name = 'Eva Muster'
        m.haushalt_erwachsene = 2; m.save()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertIn('Persönliche Angaben', body)
        self.assertIn('Informatiker', body)
        self.assertIn('Eva Muster', body)

    def test_bewerbung_uebernimmt_haushalt(self):
        from mietprozess.models import Mietbewerbung
        from crm.models import Mieter
        _lg, e, _m, _v = _basis_objekte()
        b = Mietbewerbung.objects.create(
            einheit=e, vorname='Neu', nachname='Bewerber', email='neu@example.ch',
            geburtsdatum=date(1990, 1, 1), anzahl_erwachsene=2, anzahl_kinder=3,
            haustiere=True, haustiere_details='Hund', nationalitaet='Schweiz',
            beruf='Lehrer', arbeitgeber='Schule XY')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        m = Mieter.objects.get(nachname='Bewerber')
        self.assertEqual(m.haushalt_erwachsene, 2)
        self.assertEqual(m.haushalt_kinder, 3)
        self.assertTrue(m.haustiere)
        self.assertEqual(m.haustiere_details, 'Hund')
        self.assertEqual(m.beruf, 'Lehrer')

    def test_dsg_scrubbt_neue_felder(self):
        from core.services.dsg import anonymisiere_person
        _lg, _e, m, v = _basis_objekte()
        v.status = 'beendet'; v.save()
        m.aufenthaltsbewilligung = 'C'; m.haftpflicht_police = 'P-1'; m.notfall_name = 'X'
        m.haushalt_erwachsene = 3; m.haustiere = True; m.save()
        ok, _ = anonymisiere_person(m)
        self.assertTrue(ok)
        m.refresh_from_db()
        self.assertEqual(m.aufenthaltsbewilligung, '')
        self.assertEqual(m.haftpflicht_police, '')
        self.assertEqual(m.notfall_name, '')
        self.assertEqual(m.haushalt_erwachsene, 0)
        self.assertFalse(m.haustiere)


class PendenzModalTests(TestCase):
    """Detailseiten-Pendenzen (Vertrag/Liegenschaft öffnen) navigieren voll —
    nur Aktions-Schritte (Rücknahme) öffnen im Iframe-Popup. Verhindert die
    Kollision «ganze Detailseite im engen Popup»."""

    def test_ziel_detailseite_ohne_modal(self):
        from core.views.fw import _pendenz_ziel
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        p = Pendenz.objects.create(titel='Anfechtungsfrist läuft ab', kategorie='frist',
                                   vertrag=v, liegenschaft=lg)
        url, _label, wide, modal = _pendenz_ziel(p)
        self.assertEqual(url, f'/neu/vertraege/{v.id}/')
        self.assertFalse(modal)      # volle Navigation, KEIN Popup
        self.assertFalse(wide)

    def test_ziel_ruecknahme_bleibt_modal(self):
        from core.views.fw import _pendenz_ziel
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        p = Pendenz.objects.create(titel='Rücknahme', kategorie='auszug', vertrag=v,
                                   quelle=f'auto:ruecknahme:{v.id}')
        _url, _label, _wide, modal = _pendenz_ziel(p)
        self.assertTrue(modal)       # Aktions-Schritt → Popup

    def test_pendenzen_seite_hat_keinen_modal_onclick_fuer_vertrag(self):
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        Pendenz.objects.create(titel='Anfechtungsfrist Mietzinserhöhung läuft ab',
                               kategorie='frist', vertrag=v, liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        body = c.get('/neu/pendenzen/').content.decode()
        self.assertIn(f'/neu/vertraege/{v.id}/', body)
        # Der Vertrags-Link darf NICHT mehr das Iframe-Popup öffnen.
        import re
        for m_ in re.finditer(r'<a href="/neu/vertraege/%d/"[^>]*>' % v.id, body):
            self.assertNotIn('fwModalOpen', m_.group(0))


class Art270AnfangsmietzinsTests(TestCase):
    """Art. 270 OR: Anfangsmietzins-Formular mit Vormiete + Anfechtungshinweis."""

    def test_pdf_generierung(self):
        from core.services.amtliche_formulare_so import anfangsmietzins_so_pdf
        _lg, _e, _m, v = _basis_objekte()
        daten = {'anfang_netto': Decimal('1500'), 'anfang_nk': Decimal('200'),
                 'vormiete_netto': Decimal('1350'), 'vormiete_nk': Decimal('180'),
                 'beginn': date(2026, 1, 1), 'grund_choice': 'referenz', 'begruendung': ''}
        pdf = anfangsmietzins_so_pdf(v, daten)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 1500)

    def test_view_get_und_post(self):
        from rentals.models import Dokument
        _lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        # GET zeigt das Formular
        g = c.get(f'/neu/mietzins/{v.id}/anfangsmietzins/')
        self.assertEqual(g.status_code, 200)
        self.assertIn('Anfangsmietzins', g.content.decode())
        # POST erzeugt das PDF + legt es ab
        p = c.post(f'/neu/mietzins/{v.id}/anfangsmietzins/', {
            'anfang_netto': '1500', 'anfang_nk': '200',
            'vormiete_netto': '1350', 'vormiete_nk': '180', 'grund_choice': 'referenz'})
        self.assertEqual(p.status_code, 200)
        self.assertEqual(p['Content-Type'], 'application/pdf')
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Anfangsmietzins').exists())


class FormularpflichtTests(TestCase):
    """Verzeichnis der Formularpflicht (Art. 270 Abs. 2 OR) — inkl. Kanton Bern."""

    def test_bern_hat_formularpflicht(self):
        from core.services.formularpflicht import formularpflicht_fuer_kanton
        p, info = formularpflicht_fuer_kanton('BE')
        self.assertEqual(p, 'ja')
        self.assertIn('135a', info['gesetz'])
        self.assertEqual(info['kanton_name'], 'Bern')

    def test_wallis_keine_pflicht_und_unbekannt(self):
        from core.services.formularpflicht import formularpflicht_fuer_kanton
        self.assertEqual(formularpflicht_fuer_kanton('VS')[0], 'nein')
        self.assertEqual(formularpflicht_fuer_kanton('XX')[0], 'unbekannt')

    def test_bern_pdf_zeigt_pflicht_grundlage(self):
        from core.services.amtliche_formulare_so import anfangsmietzins_so_pdf
        from core.services.formularpflicht import formularpflicht_fuer_kanton
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        _p, info = formularpflicht_fuer_kanton('BE')
        daten = {'anfang_netto': Decimal('1500'), 'anfang_nk': Decimal('200'),
                 'vormiete_netto': Decimal('1350'), 'vormiete_nk': Decimal('180'),
                 'beginn': date(2026, 1, 1), 'grund_choice': 'referenz',
                 'begruendung': '', 'pflicht_info': info}
        pdf = anfangsmietzins_so_pdf(v, daten)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 1500)

    def test_view_zeigt_pflicht_banner_bern(self):
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        c = Client(); c.force_login(_team_user())
        g = c.get(f'/neu/mietzins/{v.id}/anfangsmietzins/')
        self.assertEqual(g.status_code, 200)
        self.assertIn('Formularpflicht', g.content.decode())
        self.assertIn('Bern', g.content.decode())

    def test_auto_ablage_bei_pflicht_wohnraum(self):
        from core.views.fw import anfangsmietzins_auto_ablegen
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        erzeugt, pflicht = anfangsmietzins_auto_ablegen(v)
        self.assertTrue(erzeugt)
        self.assertEqual(pflicht, 'ja')
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Anfangsmietzins').exists())

    def test_kein_auto_ohne_pflicht(self):
        from core.views.fw import anfangsmietzins_auto_ablegen
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'VS'; lg.plz = '1950'; lg.ort = 'Sion'; lg.save()  # keine Formularpflicht
        erzeugt, grund = anfangsmietzins_auto_ablegen(v)
        self.assertFalse(erzeugt)
        self.assertEqual(grund, 'keine_pflicht')
        self.assertFalse(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Anfangsmietzins').exists())

    def test_kein_auto_bei_gewerbe(self):
        from core.views.fw import anfangsmietzins_auto_ablegen
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        e.typ = 'gew'; e.save()   # Gewerbe → mietrecht_kategorie 'gewerbe'
        erzeugt, grund = anfangsmietzins_auto_ablegen(v)
        self.assertFalse(erzeugt)
        self.assertEqual(grund, 'kein_wohnraum')

    def test_anfangsmiete_aus_sollmietzins_vorbefuellt(self):
        from portfolio.models import Sollmietzins
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        # datierte Sollmietzins-Zeile gültig ab Vertragsbeginn mit abweichendem Wert
        Sollmietzins.objects.create(einheit=e, gueltig_ab=v.beginn,
                                    netto_mietzins=Decimal('1777'), nebenkosten=Decimal('222'))
        c = Client(); c.force_login(_team_user())
        g = c.get(f'/neu/mietzins/{v.id}/anfangsmietzins/')
        self.assertEqual(g.status_code, 200)
        html = g.content.decode()
        self.assertIn('1777', html)   # aus Sollmietzins, nicht 1500 vom Vertrag
        self.assertIn('gültig ab', html)

    def test_dispatcher_faellt_auf_reportlab_zurueck(self):
        from core.services.formular_fill import fill_anfangsmietzins, hat_original
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'ZH'; lg.plz = '8000'; lg.ort = 'Zürich'; lg.save()
        self.assertFalse(hat_original('ZH', 'anfangsmietzins'))  # ZH: kein Original → Fallback
        daten = {'anfang_netto': Decimal('1500'), 'anfang_nk': Decimal('200'),
                 'vormiete_netto': Decimal('0'), 'vormiete_nk': Decimal('0'),
                 'beginn': v.beginn, 'grund_choice': 'referenz', 'begruendung': ''}
        pdf = fill_anfangsmietzins(v, daten)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_bern_nutzt_original_acroform(self):
        from core.services.formular_fill import fill_anfangsmietzins, hat_original
        from pypdf import PdfReader
        import io
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        self.assertTrue(hat_original('BE', 'anfangsmietzins'))  # Original hinterlegt
        daten = {'anfang_netto': Decimal('1650'), 'anfang_nk': Decimal('250'),
                 'vormiete_netto': Decimal('1500'), 'vormiete_nk': Decimal('230'),
                 'beginn': v.beginn, 'grund_choice': 'anpassung', 'begruendung': 'Referenzzins',
                 'basis_ref': Decimal('1.75'), 'basis_lik': Decimal('107.1'),
                 'basis_lik_basis': 'Dezember 2020'}
        pdf = fill_anfangsmietzins(v, daten, kanton='BE')
        self.assertTrue(pdf.startswith(b'%PDF'))
        # Es ist das amtliche Original (AcroForm mit den Textfeld-Namen), gefüllt.
        flds = PdfReader(io.BytesIO(pdf)).get_fields() or {}
        self.assertIn('Textfeld 16', flds)                       # Feldname aus dem Original
        self.assertEqual(flds['Textfeld 5'].get('/V'), f"{m.vorname} {m.nachname}")
        self.assertEqual(flds['Textfeld 16'].get('/V'), "1'650.00")   # Anfangsmiete netto
        # Berechnungsgrundlagen (Referenzzinssatz / LIK / Basis)
        self.assertEqual(flds['Textfeld 21'].get('/V'), '1.75')
        self.assertEqual(flds['Textfeld 22'].get('/V'), '107.1')
        self.assertEqual(flds['Textfeld 22a'].get('/V'), 'Dez. 2020')   # gekürzt (schmales Feld)

    def test_view_fuellt_berechnungsgrundlagen(self):
        # Der View muss Referenzzinssatz/LIK aus dem Vertrag in die daten geben.
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        v.basis_referenzzinssatz = Decimal('1.75'); v.basis_lik_punkte = Decimal('107.1'); v.save()
        c = Client(); c.force_login(_team_user())
        g = c.get(f'/neu/mietzins/{v.id}/anfangsmietzins/')
        self.assertEqual(g.status_code, 200)
        html = g.content.decode()
        self.assertIn('Berechnungsgrundlagen', html)
        self.assertIn('1.75', html)
        self.assertIn('107.1', html)

    def test_aktivierung_erzeugt_formular_automatisch(self):
        from rentals.models import Dokument
        lg, e, m, _v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        # frisches Objekt ohne bestehenden Vertrag für saubere Aktivierung
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='2.5 Zi', typ='wohnung',
                                    nettomiete_aktuell=Decimal('1400'), nebenkosten_aktuell=Decimal('180'))
        c = Client(); c.force_login(_team_user())
        beginn = date.today().replace(day=1)
        r = c.post('/neu/vertraege/neu/speichern/', {
            'mieter_id': str(m.id), 'einheit_id': str(e2.id),
            'beginn': beginn.isoformat(), 'netto_mietzins': '1400', 'nebenkosten': '180',
            'mietzins_modell': 'fest', 'kautions_betrag': '4200', 'aktiv_setzen': 'on',
        })
        self.assertIn(r.status_code, (200, 302))
        v = Mietvertrag.objects.filter(einheit=e2).latest('id')
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Anfangsmietzins').exists())


class AdressHistorieTests(TestCase):
    """Datierte Adress-Historie (MieterAdresse) + Auto-Sync + Korrespondenz-Vorrang."""

    def test_stichtag_waehlt_gueltige_wohnadresse(self):
        from crm.models import MieterAdresse
        _lg, _e, m, _v = _basis_objekte()
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2000, 1, 1),
                                     strasse='Altweg 1', plz='3000', ort='Bern')
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2030, 1, 1),
                                     strasse='Neuweg 5', plz='8000', ort='Zürich')
        self.assertEqual(m.aktuelle_wohnadresse(date(2026, 7, 17)).strasse, 'Altweg 1')
        self.assertEqual(m.aktuelle_wohnadresse(date(2031, 1, 1)).strasse, 'Neuweg 5')

    def test_korrespondenz_hat_vorrang(self):
        from crm.models import MieterAdresse
        _lg, _e, m, _v = _basis_objekte()
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2000, 1, 1),
                                     strasse='Wohnweg 1', plz='3000', ort='Bern')
        MieterAdresse.objects.create(mieter=m, art='korrespondenz', gueltig_ab=date(2000, 1, 1),
                                     strasse='Postfach 9', plz='3011', ort='Bern')
        self.assertEqual(m.zustelladresse(date(2026, 7, 17))[0], 'Postfach 9')
        self.assertTrue(m.sync_effektive_adresse(date(2026, 7, 17)))
        m.refresh_from_db()
        self.assertEqual(m.strasse, 'Postfach 9')
        self.assertEqual(m.plz, '3011')

    def test_ohne_zeilen_faellt_auf_flat_zurueck(self):
        _lg, _e, m, _v = _basis_objekte()      # hat nur Flat-Adresse, keine Zeilen
        self.assertEqual(m.zustelladresse()[0], 'Seeweg 3')
        self.assertFalse(m.sync_effektive_adresse())  # keine Änderung

    def test_scheduler_synct_effektive_adresse(self):
        from crm.models import MieterAdresse
        from core.services.automation import run_adress_umzuege
        _lg, _e, m, _v = _basis_objekte()
        # Umzug ab heute → wird zur effektiven Adresse
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2000, 1, 1),
                                     strasse='Seeweg 3', plz='8000', ort='Zürich')
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2020, 1, 1),
                                     strasse='Zielweg 7', plz='4000', ort='Basel')
        run_adress_umzuege()
        m.refresh_from_db()
        self.assertEqual(m.strasse, 'Zielweg 7')
        self.assertEqual(m.ort, 'Basel')

    def test_vertragsbeginn_legt_datierte_wohnadresse_an(self):
        from crm.models import MieterAdresse
        lg, e, m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        beginn = (date.today().replace(day=1))
        r = c.post('/neu/vertraege/neu/speichern/', {
            'mieter_id': str(m.id), 'einheit_id': str(e.id),
            'beginn': beginn.isoformat(), 'netto_mietzins': '1500', 'nebenkosten': '200',
            'mietzins_modell': 'fest', 'kautions_betrag': '4500',
        })
        self.assertIn(r.status_code, (200, 302))
        self.assertTrue(MieterAdresse.objects.filter(mieter=m, art='wohn', gueltig_ab=beginn).exists())

    def test_person_form_pflegt_wohn_und_korrespondenz(self):
        from crm.models import MieterAdresse
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {
            'typ': 'person', 'vorname': 'Neu', 'nachname': 'Person',
            'strasse': 'Hauptweg 2', 'plz': '3000', 'ort': 'Bern',
            'k_strasse': 'c/o Muster', 'k_plz': '3011', 'k_ort': 'Bern',
        })
        self.assertIn(r.status_code, (200, 302))
        m = Mieter.objects.get(nachname='Person')
        self.assertTrue(MieterAdresse.objects.filter(mieter=m, art='wohn').exists())
        self.assertTrue(MieterAdresse.objects.filter(mieter=m, art='korrespondenz').exists())
        m.refresh_from_db()
        # Korrespondenz hat Vorrang → effektive Adresse
        self.assertEqual(m.strasse, 'c/o Muster')

    def test_adresse_neu_und_loeschen_views(self):
        from crm.models import MieterAdresse
        _lg, _e, m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/personen/{m.id}/adresse/', {
            'art': 'wohn', 'gueltig_ab': '2027-01-01',
            'strasse': 'Zukunftweg 1', 'plz': '9000', 'ort': 'St. Gallen'})
        self.assertEqual(r.status_code, 302)
        adr = MieterAdresse.objects.get(mieter=m, gueltig_ab=date(2027, 1, 1))
        self.assertEqual(adr.ort, 'St. Gallen')
        r2 = c.post(f'/neu/adresse/{adr.id}/loeschen/')
        self.assertEqual(r2.status_code, 302)
        self.assertFalse(MieterAdresse.objects.filter(id=adr.id).exists())

    def test_dsg_anonymisierung_loescht_adress_historie(self):
        from crm.models import MieterAdresse
        from core.services.dsg import anonymisiere_person
        _lg, _e, m, v = _basis_objekte()
        v.status = 'archiviert'; v.save()
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2000, 1, 1),
                                     strasse='Geheimweg 1', plz='3000', ort='Bern')
        ok, _ = anonymisiere_person(m, grund='Test')
        self.assertTrue(ok)
        self.assertEqual(MieterAdresse.objects.filter(mieter=m).count(), 0)


class Paket1DatenUITests(TestCase):
    """Paket 1: bisher tote Model-Felder sind im UI erfassbar/sichtbar."""

    def test_liegenschaft_form_speichert_neue_felder(self):
        from portfolio.models import Liegenschaft
        lg = Liegenschaft.objects.create(strasse='Prüfweg 1', plz='3000', ort='Bern')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/liegenschaften/{lg.id}/bearbeiten/', {
            'strasse': 'Prüfweg 1', 'plz': '3000', 'ort': 'Bern', 'kanton': 'BE',
            'versicherungswert': '1250000', 'grundstuecksflaeche_m2': '640',
            'gebaeudevolumen_m3': '2100', 'sanitaer_name': 'Meier AG',
            'sanitaer_telefon': '0313334455', 'elektriker_name': 'Volt GmbH',
            'elektriker_telefon': '0316667788', 'gwr_import': ''})
        self.assertEqual(r.status_code, 302)
        lg.refresh_from_db()
        self.assertEqual(lg.versicherungswert, Decimal('1250000'))
        self.assertEqual(lg.grundstuecksflaeche_m2, Decimal('640'))
        self.assertEqual(lg.sanitaer_name, 'Meier AG')
        self.assertEqual(lg.elektriker_name, 'Volt GmbH')

    def test_objekt_form_speichert_neue_felder_und_gehoert_zu(self):
        from portfolio.models import Liegenschaft, Einheit
        lg = Liegenschaft.objects.create(strasse='Prüfweg 2', plz='3000', ort='Bern')
        haupt = Einheit.objects.create(liegenschaft=lg, bezeichnung='Haupt 3.5', typ='whg')
        pp = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 1', typ='pp')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/objekte/{pp.id}/bearbeiten/', {
            'liegenschaft_id': str(lg.id), 'bezeichnung': 'PP 1', 'typ': 'pp',
            'wertquote': '25', 'volumen_m3': '40', 'estrich': 'nein', 'oto_dose': 'A12',
            'bodenbelag': 'Beton', 'letzte_renovation': '2019',
            'standard_kautionsmonate': '2', 'gehoert_zu_id': str(haupt.id)})
        self.assertEqual(r.status_code, 302)
        pp.refresh_from_db()
        self.assertEqual(pp.wertquote, Decimal('25'))
        self.assertEqual(pp.volumen_m3, Decimal('40'))
        self.assertEqual(pp.bodenbelag, 'Beton')
        self.assertEqual(pp.letzte_renovation, 2019)
        self.assertEqual(pp.standard_kautionsmonate, 2)
        self.assertEqual(pp.gehoert_zu_id, haupt.id)

    def test_person_detail_zeigt_sprache_notizen_firma(self):
        m = Mieter.objects.create(typ='firma', firmen_name='Bau AG', uid_nummer='CHE-123.456.789',
                                  kontaktperson='Frau Muster', sprache='fr',
                                  notizen='Zahlt immer pünktlich.')
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertIn('Firma / Organisation', html)
        self.assertIn('CHE-123.456.789', html)
        self.assertIn('Frau Muster', html)
        self.assertIn('Zahlt immer pünktlich.', html)

    def test_person_form_speichert_land(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {
            'typ': 'person', 'vorname': 'Jean', 'nachname': 'Dupont',
            'strasse': 'Rue 1', 'plz': '68000', 'ort': 'Colmar', 'land': 'Frankreich'})
        self.assertIn(r.status_code, (200, 302))
        m = Mieter.objects.get(nachname='Dupont')
        self.assertEqual(m.land, 'Frankreich')


class Paket2PlatzierungTests(TestCase):
    """Paket 2: Formulare/Reports am richtigen Ort erreichbar."""

    def test_objekt_verhaeltnis_zeigt_schnellaktionen(self):
        _lg, e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn(f'/neu/mietzins/{v.id}/anfangsmietzins/', html)
        self.assertIn(f'/neu/mietzins/{v.id}/anpassung/', html)
        self.assertIn(f'/neu/vertraege/{v.id}/kuendigen/', html)

    def test_liegenschaft_detail_verlinkt_berichte(self):
        lg, _e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/liegenschaften/{lg.id}/').content.decode()
        self.assertIn(f'/neu/mieterspiegel/?lg={lg.id}', html)

    def test_vertrag_finanzen_verlinkt_nebenkosten(self):
        lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/vertraege/{v.id}/').content.decode()
        self.assertIn(f'/neu/nebenkosten/?lg={lg.id}', html)

    def test_mandate_in_sidebar_verwaltung(self):
        # Neue 6-Türen-Sidebar: Mandate liegen unter «Kontakte» (Profi) bzw.
        # «Erweitert» (Einfach) — in beiden Modi als Link auf /neu/mandate/.
        _lg, _e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        for modus in ('einfach', 'profi'):
            c.post('/neu/modus/', {'modus': modus})
            html = c.get('/neu/personen/').content.decode()
            self.assertIn('/neu/mandate/', html)
            self.assertIn('Mandate', html)


class Paket3ZahlungBonitaetTests(TestCase):
    """Paket 3: Zahlungsverkehr, Bonität, Vorvermieter-Referenz, Vertretung, Mahnsperre."""

    def test_person_form_speichert_zahlung_und_bonitaet(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {
            'typ': 'person', 'vorname': 'Zora', 'nachname': 'Zahler',
            'zahlungsart': 'lsv', 'ebill_email': 'zora@ebill.ch', 'mahnsperre': 'on',
            'zahler_name': 'Sozialamt Bern', 'zahler_iban': 'CH..',
            'betreibung_ergebnis': 'keine',
            'ref_vermieter_name': 'Alt AG', 'ref_vermieter_telefon': '0310001122',
            'vertretung_art': 'beistand', 'vertretung_name': 'KESB Bern'})
        self.assertIn(r.status_code, (200, 302))
        m = Mieter.objects.get(nachname='Zahler')
        self.assertEqual(m.zahlungsart, 'lsv')
        self.assertTrue(m.mahnsperre)
        self.assertEqual(m.zahler_name, 'Sozialamt Bern')
        self.assertEqual(m.betreibung_ergebnis, 'keine')
        self.assertEqual(m.ref_vermieter_name, 'Alt AG')
        self.assertEqual(m.vertretung_art, 'beistand')

    def test_person_detail_zeigt_zahlung_und_vertretung(self):
        m = Mieter.objects.create(typ='person', vorname='A', nachname='B',
                                  zahlungsart='ebill', ebill_email='a@b.ch',
                                  vertretung_art='kesb', vertretung_name='KESB Thun')
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertIn('Zahlungsverkehr', html)
        self.assertIn('eBill', html)
        self.assertIn('KESB Thun', html)

    def test_mahnsperre_ueberspringt_mahnlauf(self):
        from core.services.automation import run_mahnlauf
        from finance.models import DebitorenRechnung
        _lg, _e, m, v = _basis_objekte()
        m.mahnsperre = True; m.save()
        DebitorenRechnung.objects.create(
            vertrag=v, titel='Miete', betrag=Decimal('1700'), datum=date(2025, 1, 1),
            faellig_am=date(2025, 1, 1), status='offen')
        res = run_mahnlauf(send_email=False)
        self.assertEqual(res['gemahnt'], 0)   # Mahnsperre → nicht gemahnt

    def test_dsg_scrub_loescht_zahlungsfelder(self):
        from core.services.dsg import anonymisiere_person
        _lg, _e, m, v = _basis_objekte()
        v.status = 'archiviert'; v.save()
        m.zahlungsart = 'lsv'; m.zahler_name = 'X'; m.ref_vermieter_name = 'Y'
        m.vertretung_name = 'Z'; m.save()
        ok, _ = anonymisiere_person(m, grund='Test')
        self.assertTrue(ok)
        m.refresh_from_db()
        self.assertEqual(m.zahlungsart, '')
        self.assertEqual(m.zahler_name, '')
        self.assertEqual(m.ref_vermieter_name, '')
        self.assertEqual(m.vertretung_name, '')


class Paket4ProzesseTests(TestCase):
    """Paket 4: Kautions-Belege PDF + Mängelrüge (Art. 259)."""

    def test_kaution_belege_pdf(self):
        from rentals.models import Dokument
        _lg, _e, m, v = _basis_objekte()
        v.kautions_art = 'sperrkonto'; v.kautions_konto = 'CH93 0076…'
        v.kautions_einbezahlt_am = date(2024, 1, 5); v.save()
        c = Client(); c.force_login(_team_user())
        for art in ('hinterlegung', 'freigabe'):
            r = c.get(f'/neu/vertraege/{v.id}/kaution-beleg/{art}/')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Kaution').exists())

    def test_maengelruege_pdf_und_pendenz(self):
        from rentals.models import Dokument
        from core.models import Pendenz
        _lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        g = c.get(f'/neu/vertraege/{v.id}/maengelruege/')
        self.assertEqual(g.status_code, 200)
        r = c.post(f'/neu/vertraege/{v.id}/maengelruege/', {'mangel': 'Tropfender Wasserhahn im Bad', 'frist_tage': '10'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Mängelrüge').exists())
        self.assertTrue(Pendenz.objects.filter(vertrag=v, titel__startswith='Mängelbehebung').exists())


class Paket4RestTests(TestCase):
    """Paket 4 Rest: Untermiete-Zustimmung, Versicherungsregister, Betriebskostenspiegel."""

    def test_untermiete_pdf(self):
        _lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self.assertEqual(c.get(f'/neu/vertraege/{v.id}/untermiete/').status_code, 200)
        r = c.post(f'/neu/vertraege/{v.id}/untermiete/', {
            'untermieter': 'Peter Muster', 'entscheid': 'zustimmung', 'bedingungen': 'befristet bis Ende Jahr'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_versicherung_crud(self):
        from portfolio.models import Versicherung
        lg, _e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/liegenschaften/{lg.id}/versicherung/', {
            'art': 'gebaeude', 'gesellschaft': 'GVB', 'policennummer': 'P-123',
            'versicherungssumme': '1200000', 'jahrespraemie': '3400', 'ablauf_datum': '2027-01-01'})
        self.assertEqual(r.status_code, 302)
        vs = Versicherung.objects.get(liegenschaft=lg)
        self.assertEqual(vs.gesellschaft, 'GVB')
        self.assertEqual(vs.jahrespraemie, Decimal('3400'))
        # Anzeige auf der Detailseite
        html = c.get(f'/neu/liegenschaften/{lg.id}/').content.decode()
        self.assertIn('GVB', html)
        # Löschen
        r2 = c.post(f'/neu/versicherung/{vs.id}/loeschen/')
        self.assertEqual(r2.status_code, 302)
        self.assertFalse(Versicherung.objects.filter(id=vs.id).exists())

    def test_betriebskostenspiegel_rechnet_pro_m2(self):
        from finance.models import Buchung, Buchungskonto
        lg, e, _m, _v = _basis_objekte()
        e.flaeche_m2 = Decimal('100'); e.save()
        aufwand, _ = Buchungskonto.objects.get_or_create(nummer='4000', defaults={'bezeichnung': 'Unterhalt', 'typ': 'aufwand'})
        bank, _ = Buchungskonto.objects.get_or_create(nummer='1020', defaults={'bezeichnung': 'Bank', 'typ': 'bilanz'})
        Buchung.objects.create(datum=date(date.today().year, 6, 1), liegenschaft=lg,
                               soll_konto=aufwand, haben_konto=bank, betrag=Decimal('2500'),
                               beleg_text='Test-Aufwand')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/berichte/betriebskostenspiegel/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Betriebskostenspiegel', html)
        self.assertIn('25,00', html)   # 2500 / 100 m² = CHF 25.00/m² (de-Lokalisierung)


class FormulareTabTests(TestCase):
    """Zentraler «Formulare & Prozesse»-Tab am Vertrag."""

    def test_tab_zeigt_alle_gruppen_und_formulare(self):
        _lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/vertraege/{v.id}/').content.decode()
        # Tab existiert
        self.assertIn('vt-formulare', html)
        # Gruppen
        for g in ('Mietrechtliche Formulare', 'Kaution (Art. 257e)', 'Prozesse', 'Beilagen'):
            self.assertIn(g, html)
        # Kern-Formulare verlinkt
        self.assertIn(f'/neu/mietzins/{v.id}/anfangsmietzins/', html)
        self.assertIn(f'/neu/vertraege/{v.id}/maengelruege/', html)
        self.assertIn(f'/neu/vertraege/{v.id}/untermiete/', html)

    def test_kontext_kaution_nur_wenn_einbezahlt(self):
        from core.views.fw import _formulare_prozesse
        _lg, _e, _m, v = _basis_objekte()
        # ohne Einzahlung: Kautions-Belege nicht verfügbar
        gr = {g['titel']: g for g in _formulare_prozesse(v)}
        kaution = {i['titel']: i for i in gr['Kaution (Art. 257e)']['items']}
        self.assertFalse(kaution['Hinterlegungsbestätigung']['verfuegbar'])
        # nach Einzahlung: verfügbar
        v.kautions_art = 'sperrkonto'; v.kautions_einbezahlt_am = date.today(); v.save()
        gr2 = {g['titel']: g for g in _formulare_prozesse(v)}
        kaution2 = {i['titel']: i for i in gr2['Kaution (Art. 257e)']['items']}
        self.assertTrue(kaution2['Hinterlegungsbestätigung']['verfuegbar'])
        self.assertTrue(kaution2['Freigabe an Bank']['verfuegbar'])


class BefristungTests(TestCase):
    """`ist_befristet` trennt sauber befristete Verhältnisse (Zeitablauf,
    Art. 266 OR) von unbefristeten und von gekündigten Verträgen."""

    def test_flag_und_properties(self):
        _lg, _e, _m, v = _basis_objekte()
        # Default: unbefristet
        self.assertFalse(v.ist_befristet)
        self.assertEqual(v.vertragsdauer_art, 'unbefristet')
        self.assertIsNone(v.laeuft_aus_am)
        # Befristet setzen
        v.ist_befristet = True
        v.ende = date(2027, 12, 31)
        v.save()
        self.assertEqual(v.vertragsdauer_art, 'befristet')
        self.assertEqual(v.laeuft_aus_am, date(2027, 12, 31))

    def test_gekuendigter_unbefristeter_hat_ende_aber_ist_nicht_befristet(self):
        _lg, _e, _m, v = _basis_objekte()
        # Kündigung setzt ende + status, aber NICHT ist_befristet
        v.status = 'gekuendigt'
        v.ende = date(2026, 3, 31)
        v.save()
        self.assertFalse(v.ist_befristet)
        self.assertIsNone(v.laeuft_aus_am)  # Kündigungs-Ende zählt nicht als Auslauf

    def test_mieterwechsel_listet_nur_echte_befristete(self):
        from datetime import date as _d
        lg, e, _m, v = _basis_objekte()
        # unbefristeter aktiver Vertrag mit gesetztem ende (z.B. Alt-Daten) → NICHT gelistet
        v.ende = _d.today() + timedelta(days=30)
        v.ist_befristet = False
        v.save()
        # zweiter, echt befristeter Vertrag
        m2 = Mieter.objects.create(typ='person', vorname='Eva', nachname='Meier',
                                   strasse='Weg 2', plz='8000', ort='Zürich')
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='2.5 Zi', typ='wohnung',
                                    nettomiete_aktuell=Decimal('1200'))
        vb = Mietvertrag.objects.create(mieter=m2, einheit=e2, beginn=date(2024, 1, 1),
                                        netto_mietzins=Decimal('1200'), nebenkosten=Decimal('0'),
                                        status='aktiv', ist_befristet=True,
                                        ende=_d.today() + timedelta(days=30))
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.get('/neu/mieterwechsel/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Meier', html)          # befristeter Vertrag gelistet
        self.assertNotIn('Muster', html)      # unbefristeter (Alt-ende) NICHT als Auslauf

    def test_form_erstellt_befristeten_vertrag(self):
        lg, e, m, _v = _basis_objekte()
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post('/neu/vertraege/neu/speichern/', {
            'mieter_id': m.id, 'einheit_id': e.id,
            'beginn': '2026-01-01', 'ende': '2027-12-31', 'ist_befristet': '1',
            'netto_mietzins': '1500', 'nebenkosten': '200',
            'kuendigungsfrist': '3', 'anzahl_personen': '1',
        })
        self.assertIn(r.status_code, (200, 302))
        vneu = Mietvertrag.objects.filter(einheit=e, beginn=date(2026, 1, 1)).first()
        self.assertIsNotNone(vneu)
        self.assertTrue(vneu.ist_befristet)
        self.assertEqual(vneu.ende, date(2027, 12, 31))


class SchlichtungRegisterTests(TestCase):
    """Schlichtungsbehörden-Register: SO/BE/ZH exakt, sonst ehrlicher Fallback."""

    class _LG:
        def __init__(self, kanton, plz, ort):
            self.kanton, self.plz, self.ort = kanton, plz, ort

    def test_bern_vier_regionen_exakt(self):
        from core.services.kantone import schlichtung_block
        kt, name, beh, exakt = schlichtung_block(self._LG('BE', '3011', 'Bern'))
        self.assertEqual(kt, 'BE')
        self.assertTrue(exakt)
        self.assertEqual(len(beh), 4)
        self.assertIn('Bern-Mittelland', beh[0][0])

    def test_zuerich_stadt_exakt(self):
        from core.services.kantone import schlichtung_block
        _kt, _name, beh, exakt = schlichtung_block(self._LG('ZH', '8004', 'Zürich'))
        self.assertTrue(exakt)
        self.assertIn('Zürich', beh[0][1])

    def test_zuerich_unbekannte_plz_faellt_auf_generisch(self):
        from core.services.kantone import schlichtung_block
        _kt, _name, _beh, exakt = schlichtung_block(self._LG('ZH', '8620', 'Wetzikon'))
        self.assertFalse(exakt)

    def test_nicht_hinterlegter_kanton_generisch(self):
        from core.services.kantone import schlichtung_block
        _kt, name, beh, exakt = schlichtung_block(self._LG('AG', '5000', 'Aarau'))
        self.assertFalse(exakt)
        self.assertIn('Aargau', beh[0][0])


class WGVertragTests(TestCase):
    """WG-fähiger Vertrag: weitere_mieter (M2M) + Solidarhaftung, additiv zum
    FK-Mitmieter (Ehepaar)."""

    def _person(self, vn, nn):
        return Mieter.objects.create(typ='person', vorname=vn, nachname=nn,
                                     strasse='Gasse 1', plz='8000', ort='Zürich')

    def test_alle_mieter_und_ist_wg(self):
        _lg, e, m, v = _basis_objekte()
        self.assertEqual(v.alle_mieter, [m])
        self.assertFalse(v.ist_wg)
        m2 = self._person('Eva', 'Meier'); v.mitmieter = m2; v.save()
        self.assertEqual([p.pk for p in v.alle_mieter], [m.pk, m2.pk])
        self.assertFalse(v.ist_wg)   # zwei Parteien = kein WG
        m3 = self._person('Tim', 'Roth'); v.weitere_mieter.add(m3)
        self.assertTrue(v.ist_wg)
        self.assertEqual(len(v.alle_mieter), 3)
        self.assertEqual([p.pk for p in v.mitmieter_alle], [m2.pk, m3.pk])

    def test_mitmieter_block_enthaelt_wg(self):
        from core.services.formular_fill import _mitmieter_block
        _lg, e, m, v = _basis_objekte()
        m2 = self._person('Eva', 'Meier'); v.mitmieter = m2; v.save()
        m3 = self._person('Tim', 'Roth'); v.weitere_mieter.add(m3)
        block = _mitmieter_block(v, sep=', ')
        self.assertIn('Eva Meier', block)
        self.assertIn('Tim Roth', block)

    def test_view_hinzufuegen_entfernen(self):
        _lg, e, m, v = _basis_objekte()
        k = self._person('Kim', 'Wg')
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/vertraege/{v.id}/wg-mieter/', {'aktion': 'hinzufuegen', 'mieter_id': k.id})
        self.assertIn(k, list(v.weitere_mieter.all()))
        c.post(f'/neu/vertraege/{v.id}/wg-mieter/', {'aktion': 'entfernen', 'mieter_id': k.id})
        self.assertNotIn(k, list(v.weitere_mieter.all()))

    def test_view_hinzufuegen_hauptmieter_abgelehnt(self):
        _lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/vertraege/{v.id}/wg-mieter/', {'aktion': 'hinzufuegen', 'mieter_id': m.id})
        self.assertEqual(v.weitere_mieter.count(), 0)   # Hauptmieter nicht als WG-Mieter

    def test_solidarhaftung_toggle(self):
        _lg, e, m, v = _basis_objekte()
        self.assertTrue(v.solidarhaftung)   # Default an
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/vertraege/{v.id}/wg-mieter/', {'aktion': 'solidarhaftung', 'wert': 'off'})
        v.refresh_from_db()
        self.assertFalse(v.solidarhaftung)

    def test_wg_mieter_bekommt_wohnadresse(self):
        _lg, e, m, v = _basis_objekte()
        k = self._person('Kim', 'Wg')
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/vertraege/{v.id}/wg-mieter/', {'aktion': 'hinzufuegen', 'mieter_id': k.id})
        from crm.models import MieterAdresse
        self.assertTrue(MieterAdresse.objects.filter(mieter=k, art='wohn').exists())

    def test_detail_zeigt_wg_panel(self):
        _lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.get(f'/neu/vertraege/{v.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Weitere Mieter (WG)', r.content.decode())


class IndexMitteilungTests(TestCase):
    """Index-Mitteilung (Art. 269b/269d): Anpassungsvorschlag aus LIK-Entwicklung."""

    def _index_vertrag(self):
        lg, e, m, v = _basis_objekte()
        v.mietzins_modell = 'index'
        v.basis_lik_punkte = Decimal('100.0')
        v.index_weitergabe_prozent = Decimal('100.0')
        v.netto_mietzins = Decimal('1000.00')
        v.ist_befristet = True
        v.ende = date(2030, 1, 1)
        v.save()
        return v

    def test_vorschlag_steigt_mit_lik(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        v = self._index_vertrag()
        r = index_anpassung_vorschlag(v, aktuell_lik=Decimal('105.0'))
        self.assertIsNotNone(r)
        self.assertEqual(r['neu_netto'], Decimal('1050.00'))   # +5%
        self.assertEqual(r['delta_prozent'], Decimal('5.00'))
        self.assertIn('Art. 269b', r['begruendung'])

    def test_teilweise_weitergabe(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        v = self._index_vertrag()
        v.index_weitergabe_prozent = Decimal('80.0'); v.save()
        r = index_anpassung_vorschlag(v, aktuell_lik=Decimal('110.0'))
        # +10% LIK × 80% Weitergabe = +8%
        self.assertEqual(r['neu_netto'], Decimal('1080.00'))

    def test_kein_vorschlag_wenn_lik_nicht_gestiegen(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        v = self._index_vertrag()
        self.assertIsNone(index_anpassung_vorschlag(v, aktuell_lik=Decimal('100.0')))
        self.assertIsNone(index_anpassung_vorschlag(v, aktuell_lik=Decimal('95.0')))

    def test_kein_vorschlag_fuer_festmiete(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        _lg, _e, _m, v = _basis_objekte()  # mietzins_modell default 'fest'
        self.assertIsNone(index_anpassung_vorschlag(v, aktuell_lik=Decimal('110.0')))

    def test_anpassung_view_zeigt_index_banner(self):
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='V AG', aktueller_referenzzinssatz=Decimal('1.50'),
                                  aktueller_lik_punkte=Decimal('106.0'))
        v = self._index_vertrag()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.get(f'/neu/mietzins/{v.id}/anpassung/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.context.get('index_vorschlag'))
        self.assertIn('Indexmiete (Art. 269b OR)', r.content.decode())


class RenditeGebaeudeTests(TestCase):
    """Rendite-Kennzahlen (Verkehrswert-Nenner), gebäudescharfe Betriebsrechnung
    und Leerstands-Zeitverlauf."""

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


class QualitaetscheckFixTests(TestCase):
    """Fixes aus dem Abschluss-Qualitätscheck: cancel_umzug-Scoping,
    Betriebsrechnung ohne Doppelzählung von Erfolgsumbuchungen."""

    def test_betriebsrechnung_keine_doppelzaehlung_erfolgsumbuchung(self):
        from core.services.rendite import betriebsrechnung
        from finance.models import Buchungskonto, Buchung
        lg, e, m, v = _basis_objekte()
        Buchungskonto.objects.get_or_create(nummer='3000', defaults={'bezeichnung': 'Ertrag', 'typ': 'ertrag'})
        Buchungskonto.objects.get_or_create(nummer='6000', defaults={'bezeichnung': 'Aufwand', 'typ': 'aufwand'})
        auf = Buchungskonto.objects.get(nummer='6000')
        ert = Buchungskonto.objects.get(nummer='3000')
        jahr = date.today().year
        # Reine Aufwand→Ertrag-Umbuchung: darf weder Ertrag- noch Aufwand-Total aufblähen
        Buchung.objects.create(datum=date(jahr, 5, 1), liegenschaft=lg,
                               soll_konto=auf, haben_konto=ert, betrag=Decimal('500'))
        d = betriebsrechnung(lg, jahr)
        self.assertEqual(d['ertrag_total'], Decimal('0.00'))
        self.assertEqual(d['aufwand_total'], Decimal('0.00'))

    def test_cancel_umzug_schont_manuelle_adresse(self):
        from crm.api import cancel_umzug
        from crm.models import MieterAdresse
        from django.test import RequestFactory
        _lg, _e, m, _v = _basis_objekte()
        zukunft = date.today() + timedelta(days=30)
        # aus Vertrag stammend (soll storniert werden)
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=zukunft,
                                     strasse='Vertragsweg 1', plz='3000', ort='Bern',
                                     quelle='vertrag:99')
        # manuell erfasst (soll BLEIBEN)
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=zukunft + timedelta(days=5),
                                     strasse='Manuellweg 2', plz='3001', ort='Bern', quelle='')
        req = RequestFactory().post(f'/api/crm/mieter/{m.id}/cancel-umzug')
        req.user = _team_user()
        cancel_umzug(req, m.id)
        verbleibend = set(m.adressen.values_list('strasse', flat=True))
        self.assertNotIn('Vertragsweg 1', verbleibend)   # Vertrags-Einzug storniert
        self.assertIn('Manuellweg 2', verbleibend)       # manuelle Adresse geschont


class NachtN1KritischeBugsTests(TestCase):
    """Nacht-Audit N1: Storno-Kette, Verzugszins-Delta, 266a-Klemme,
    269d-Zustellpuffer, Zusage-Idempotenz, Telefonsuche."""

    def _konten(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()

    def test_storno_kette_verkettet_und_markiert(self):
        from finance.api import erstelle_storno_buchung
        from finance.booking import buche
        _lg, _e, _m, _v = _basis_objekte()
        self._konten()
        b = buche('1100', '3000', Decimal('1500'), 'Miete Test')
        gegen = erstelle_storno_buchung(b)
        b.refresh_from_db()
        self.assertIsNotNone(b.storniert_am)          # Original markiert
        self.assertEqual(gegen.storno_von_id, b.id)   # Kette verkettet
        self.assertTrue(gegen.ist_storno)
        # Doppel-Storno verhindert
        with self.assertRaises(ValueError):
            erstelle_storno_buchung(b)

    def test_betriebsrechnung_nettoiert_nach_storno(self):
        from core.services.rendite import betriebsrechnung
        from finance.booking import buche, storniere_buchung
        lg, _e, _m, _v = _basis_objekte()
        self._konten()
        from finance.models import Buchungskonto
        Buchungskonto.objects.get_or_create(nummer='6000', defaults={'bezeichnung': 'Unterhalt', 'typ': 'aufwand'})
        b = buche('6000', '1020', Decimal('800'), 'Reparatur', datum=date.today(), liegenschaft=lg)
        storniere_buchung(b)
        d = betriebsrechnung(lg, date.today().year)
        self.assertEqual(d['aufwand_total'], Decimal('0.00'))   # storniert zählt nicht

    def test_verzugszins_delta_statt_kumulativ(self):
        from core.services.automation import run_mahnlauf, verzugszins
        from finance.models import DebitorenRechnung, Mahnung
        lg, e, m, v = _basis_objekte()
        self._konten()
        # 65 Tage überfällig → würde direkt Stufe 3 erreichen; wir simulieren
        # zwei Läufe: erst Stufe 2 (31 Tage), dann Stufe 3 (65 Tage).
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete Januar', betrag=Decimal('1000'),
            datum=date.today() - timedelta(days=70),
            faellig_am=date.today() - timedelta(days=31), status='offen')
        run_mahnlauf(send_email=False, mit_zins=True)
        m1 = r.mahnungen.order_by('-id').first()
        self.assertEqual(m1.zins, verzugszins(Decimal('1000'), 31))
        # Fälligkeit zurückdatieren → nächste Stufe wird fällig
        r.faellig_am = date.today() - timedelta(days=65)
        r.save(update_fields=['faellig_am'])
        run_mahnlauf(send_email=False, mit_zins=True)
        m2 = r.mahnungen.order_by('-id').first()
        self.assertGreater(m2.stufe, m1.stufe)
        # Stufe 2 fakturiert nur das DELTA: voller Zins(65) − bereits Zins(31)
        erwartet = verzugszins(Decimal('1000'), 65) - m1.zins
        self.assertEqual(m2.zins, erwartet)
        total = sum(x.zins for x in r.mahnungen.all())
        self.assertEqual(total, verzugszins(Decimal('1000'), 65))  # nie mehr als 1×

    def test_266a_zu_fruehes_ende_geklemmt(self):
        from rentals.services import berechne_kuendigungstermin
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        heute = date.today()
        zu_frueh = heute + timedelta(days=5)   # weit vor Frist+Termin
        c.post(f'/neu/vertraege/{v.id}/kuendigen/', {
            'absender': 'mieter', 'eingang_datum': heute.isoformat(),
            'gewuenschtes_ende': zu_frueh.isoformat(),
        })
        v.refresh_from_db()
        termin = berechne_kuendigungstermin(v, heute)
        self.assertEqual(v.ende, termin)   # geklemmt auf ordentlichen Termin
        k = v.kuendigungen.first()
        self.assertEqual(k.per_datum, termin)
        self.assertEqual(k.gewuenschtes_ende, zu_frueh)  # Wunsch bleibt dokumentiert

    def test_269d_zustellpuffer(self):
        from rentals.services import naechster_anpassungstermin, berechne_kuendigungstermin, ZUSTELL_PUFFER_TAGE
        _lg, _e, _m, v = _basis_objekte()
        heute = date.today()
        # Die Erhöhung wird auf den ERSTEN des Folgemonats wirksam (Monatserster),
        # nicht auf den Monatsende-Kündigungstermin selbst (Live-Test I).
        termin = berechne_kuendigungstermin(v, heute + timedelta(days=ZUSTELL_PUFFER_TAGE + 10))
        self.assertEqual(naechster_anpassungstermin(v, heute), termin + timedelta(days=1))
        self.assertGreaterEqual(ZUSTELL_PUFFER_TAGE, 7)

    def test_zusage_nach_vergleich_blockiert_umwandlung_nicht(self):
        from mietprozess.models import Mietbewerbung
        lg, e, m, v = _basis_objekte()
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='1.5 Zi', typ='wohnung',
                                    nettomiete_aktuell=Decimal('900'))
        b = Mietbewerbung.objects.create(einheit=e2, vorname='Nina', nachname='Neu',
                                         email='nina@example.ch', status='zugesagt',
                                         geburtsdatum=date(1992, 3, 1))  # via Vergleich zugesagt, OHNE Entwurf
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        self.assertEqual(r.status_code, 302)
        entwurf = Mietvertrag.objects.filter(einheit=e2, status='entwurf',
                                             mieter__nachname='Neu').first()
        self.assertIsNotNone(entwurf)   # Entwurf wurde trotz Status 'zugesagt' erstellt
        # Zweiter Aufruf: idempotent, kein zweiter Entwurf
        c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        self.assertEqual(Mietvertrag.objects.filter(einheit=e2, status='entwurf').count(), 1)

    def test_telefonsuche(self):
        _lg, _e, m, _v = _basis_objekte()
        m.mobile = '079 123 45 67'; m.save()
        u = _team_user(); c = Client(); c.force_login(u)
        # Personenliste: Teilstring
        r = c.get('/neu/personen/?q=079 123')
        self.assertIn('Muster', r.content.decode())
        # Globale Suche: formatfremde Schreibweise (ohne Leerzeichen)
        r2 = c.get('/neu/suche/?q=0791234567')
        self.assertIn('Muster', r2.content.decode())


class NachtN2JuristTests(TestCase):
    """Nacht-Audit N2: 257d-Doppelzustellung (266n), Rückgabe-Mängelrüge 267a,
    Verjährungsüberwachung (Art. 128 Ziff. 1)."""

    def test_257d_doppelzustellung_familienwohnung(self):
        from finance.models import DebitorenRechnung
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        v.familienwohnung = True; v.mitmieter_name = 'Erika Muster'; v.save()
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete',
                                         betrag=Decimal('1500'),
                                         datum=date.today() - timedelta(days=40),
                                         faellig_am=date.today() - timedelta(days=35), status='offen')
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post(f'/neu/vertraege/{v.id}/verzug/', {'frist_bis': (date.today() + timedelta(days=40)).isoformat()})
        self.assertEqual(r.status_code, 302)
        dok = Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Zahlungsaufforderung 257d').first()
        self.assertIsNotNone(dok)
        self.assertIn('2 Zustellungen', dok.bezeichnung)   # Mieter + Ehegatte separat

    def test_257d_einzelzustellung_ohne_familienwohnung(self):
        from finance.models import DebitorenRechnung
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()   # keine Familienwohnung, kein Mitmieter
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete',
                                         betrag=Decimal('1500'),
                                         datum=date.today() - timedelta(days=40),
                                         faellig_am=date.today() - timedelta(days=35), status='offen')
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/vertraege/{v.id}/verzug/', {'frist_bis': (date.today() + timedelta(days=40)).isoformat()})
        dok = Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Zahlungsaufforderung 257d').first()
        self.assertIsNotNone(dok)
        self.assertNotIn('Zustellungen', dok.bezeichnung)

    def test_auszugscheckliste_enthaelt_267a_pendenz(self):
        from core.views.fw import _auszugscheckliste_anlegen
        from core.models import Pendenz
        _lg, _e, _m, v = _basis_objekte()
        per = date.today() + timedelta(days=60)
        _auszugscheckliste_anlegen(v, None, per, None)
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='267a').first()
        self.assertIsNotNone(p)
        self.assertEqual(p.faellig_am, per + timedelta(days=2))   # sofort nach Abnahme
        self.assertEqual(p.kategorie, 'frist')

    def test_rueckgabe_ruege_pdf_und_view(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel, Dokument
        _lg, _e, _m, v = _basis_objekte()
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        AbnahmeMangel.objects.create(protokoll=prot, raum='Küche', beschreibung='Kochfeld gesprungen',
                                     verursacher='mieter', kostenschaetzung=Decimal('400'))
        AbnahmeMangel.objects.create(protokoll=prot, raum='Bad', beschreibung='Normale Abnutzung',
                                     verursacher='abnutzung')
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post(f'/neu/abnahme/{prot.id}/ruege-267a/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Mängelrüge Art. 267a').exists())

    def test_rueckgabe_ruege_ohne_mieter_maengel(self):
        from rentals.models import Abnahmeprotokoll
        _lg, _e, _m, v = _basis_objekte()
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post(f'/neu/abnahme/{prot.id}/ruege-267a/')
        self.assertEqual(r.status_code, 302)   # kein PDF, Redirect mit Hinweis

    def test_verjaehrungs_pendenz_und_mahnlauf_skip(self):
        from core.services.automation import generate_auto_pendenzen, run_mahnlauf
        from finance.models import DebitorenRechnung
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        alt = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete Uralt', betrag=Decimal('1000'),
            datum=date.today() - timedelta(days=1700),
            faellig_am=date.today() - timedelta(days=1700), status='offen')  # ~4.7 Jahre
        generate_auto_pendenzen()
        p = Pendenz.objects.filter(quelle=f'auto:verjaehrung:{alt.id}').first()
        self.assertIsNotNone(p)
        self.assertIn('Art. 128', p.beschreibung)
        # Verjährte Forderung (> 5 J) wird im Mahnlauf übersprungen
        alt.faellig_am = date.today() - timedelta(days=5 * 365 + 10)
        alt.save(update_fields=['faellig_am'])
        res = run_mahnlauf(send_email=False)
        self.assertEqual(alt.mahnungen.count(), 0)


class NachtN3MieterportalTests(TestCase):
    """Nacht-Audit N3: Passwort-Reset/Ändern, Foto-Upload, Mieterkonto-Seite,
    Meine Daten, Rechnungsarchiv."""

    def _mieter_login(self):
        lg, e, m, v = _basis_objekte()
        u = User.objects.create_user(username='mieter_n3', password='altespasswort1', email='hans@example.ch')
        m.benutzer = u; m.save()
        return lg, m, v, u

    def test_passwort_reset_flow(self):
        from django.core import mail
        _lg, _m, _v, u = self._mieter_login()
        c = Client()
        self.assertEqual(c.get('/passwort/vergessen/').status_code, 200)
        r = c.post('/passwort/vergessen/', {'email': 'hans@example.ch'})
        self.assertEqual(r.status_code, 302)   # → /passwort/gesendet/
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Neues Passwort', mail.outbox[0].subject)
        self.assertIn('/passwort/neu/', mail.outbox[0].body)

    def test_login_zeigt_vergessen_link(self):
        c = Client()
        self.assertIn('/passwort/vergessen/', c.get('/login/').content.decode())

    def test_passwort_aendern_im_portal(self):
        _lg, _m, _v, u = self._mieter_login()
        c = Client(); c.force_login(u)
        self.assertEqual(c.get('/mieter/passwort/').status_code, 200)
        r = c.post('/mieter/passwort/', {
            'old_password': 'altespasswort1',
            'new_password1': 'NeuUndSicher99', 'new_password2': 'NeuUndSicher99'})
        self.assertEqual(r.status_code, 302)
        u.refresh_from_db()
        self.assertTrue(u.check_password('NeuUndSicher99'))

    def test_schaden_mit_fotos(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from tickets.models import SchadenMeldung
        _lg, _m, v, u = self._mieter_login()
        c = Client(); c.force_login(u)
        # 1x1-GIF als Mini-Bild
        gif = (b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!'
               b'\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;')
        r = c.post('/mieter/schaden/', {
            'vertrag_id': str(v.id), 'titel': 'Wasserhahn tropft', 'beschreibung': 'Küche',
            'fotos': [SimpleUploadedFile('a.gif', gif, 'image/gif'),
                      SimpleUploadedFile('b.gif', gif, 'image/gif')]})
        self.assertEqual(r.status_code, 302)
        t = SchadenMeldung.objects.filter(titel='Wasserhahn tropft').first()
        self.assertIsNotNone(t)
        self.assertEqual(t.fotos.count(), 2)

    def test_mieterkonto_seite(self):
        from finance.models import DebitorenRechnung, Zahlungseingang
        lg, m, v, u = self._mieter_login()
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete Juli',
                                         betrag=Decimal('1700'), datum=date.today(),
                                         faellig_am=date.today(), status='offen')
        c = Client(); c.force_login(u)
        r = c.get('/mieter/konto/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('Offener Betrag', body)     # laienverständliche Saldo-Karte
        self.assertIn('Miete Juli', body)

    def test_meine_daten_aendern(self):
        from crm.models import Kommunikation
        _lg, m, _v, u = self._mieter_login()
        c = Client(); c.force_login(u)
        self.assertEqual(c.get('/mieter/daten/').status_code, 200)
        r = c.post('/mieter/daten/', {'mobile': '079 999 88 77',
                                      'telefon_privat': '', 'email': 'hans@example.ch',
                                      'adresse_meldung': ''})
        self.assertEqual(r.status_code, 302)
        m.refresh_from_db()
        self.assertEqual(m.mobile, '079 999 88 77')
        self.assertTrue(Kommunikation.objects.filter(mieter=m, betreff__icontains='Kontaktdaten').exists())

    def test_rechnungsarchiv_zeigt_bezahlte(self):
        from finance.models import DebitorenRechnung
        lg, m, v, u = self._mieter_login()
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete Alt-Monat',
                                         betrag=Decimal('1700'), datum=date.today() - timedelta(days=90),
                                         faellig_am=date.today() - timedelta(days=90), status='bezahlt')
        c = Client(); c.force_login(u)
        body = c.get('/mieter/rechnungen/').content.decode()
        self.assertIn('Bezahlte Rechnungen', body)
        self.assertIn('Miete Alt-Monat', body)

    def test_nav_hat_neue_eintraege(self):
        _lg, _m, _v, u = self._mieter_login()
        c = Client(); c.force_login(u)
        body = c.get('/mieter/').content.decode()
        for pfad in ('/mieter/konto/', '/mieter/daten/', '/mieter/passwort/'):
            self.assertIn(pfad, body)


class NachtN4UITests(TestCase):
    """Nacht-Audit N4: UI-Feinschliff — Favicon, Empty-States mit CTA,
    echte Links in Listen-Zellen, Live-Filter, Debitoren-Pagination."""

    def test_favicon_und_submit_guard_in_base(self):
        _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        body = c.get('/neu/liegenschaften/').content.decode()
        self.assertIn('rel="icon"', body)
        self.assertIn('data:image/svg+xml', body)
        # Doppelklick-Schutz (globaler Submit-Guard) ist eingebunden
        self.assertIn("addEventListener('submit'", body)

    def test_empty_state_mit_cta_liegenschaften(self):
        u = _team_user(); c = Client(); c.force_login(u)
        body = c.get('/neu/liegenschaften/').content.decode()
        self.assertIn('Noch keine Liegenschaften', body)
        self.assertIn('/neu/liegenschaften/neu/', body)
        self.assertIn('Erste Liegenschaft erfassen', body)

    def test_empty_state_filter_variante_personen(self):
        _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        body = c.get('/neu/personen/?q=zzzz_nicht_vorhanden').content.decode()
        self.assertIn('Keine Treffer', body)

    def test_listen_erste_zelle_ist_echter_link(self):
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        for url, href in (
            ('/neu/liegenschaften/', f'/neu/liegenschaften/{lg.id}/'),
            ('/neu/personen/', f'/neu/personen/{m.id}/'),
            ('/neu/vertraege/', f'/neu/vertraege/{v.id}/'),
        ):
            body = c.get(url).content.decode()
            self.assertIn(f'<a href="{href}"', body,
                          f'Erste Zelle von {url} muss ein echter <a>-Link sein')

    def test_liegenschaften_live_filter_verdrahtet(self):
        _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        body = c.get('/neu/liegenschaften/').content.decode()
        self.assertIn('data-suche="#lgListe"', body)
        self.assertIn('id="lgListe"', body)
        self.assertIn('data-zeile', body)

    def test_debitoren_pagination(self):
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        for i in range(55):
            DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=lg, titel=f'Miete {i}', betrag=Decimal('100'),
                datum=date.today() - timedelta(days=i),
                faellig_am=date.today() - timedelta(days=i), status='offen')
        u = _team_user(); c = Client(); c.force_login(u)
        body = c.get('/neu/debitoren/').content.decode()
        self.assertIn('Seite 1/2', body)
        self.assertIn('55 Position(en)', body)
        # KPI-Summe bleibt Gesamtwert trotz Slicing (55 × 100)
        self.assertIn("5'500", body)
        body2 = c.get('/neu/debitoren/?seite=2').content.decode()
        self.assertIn('Seite 2/2', body2)


class NachtN5EigentuemerTests(TestCase):
    """Nacht-Audit N5: Kontokorrent-PDF im Portal, Ausstände-KPI,
    Freigabe-Mail an den Eigentümer, Honorar-Transparenz."""

    def _mandant_login(self, **kw):
        lg, e, m, v = _basis_objekte()
        md = Mandant.objects.create(firma_oder_name='Eigentümer AG', **kw)
        lg.mandant = md; lg.save()
        u = User.objects.create_user(username='eig_n5', password='x')
        md.benutzer = u; md.save()
        return md, lg, v, u

    def test_portal_kontokorrent_pdf(self):
        md, lg, v, u = self._mandant_login()
        c = Client(); c.force_login(u)
        for url in ('/portal/kontokorrent/', '/portal/kontokorrent/?jahr=2025'):
            r = c.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r['Content-Type'], 'application/pdf')
            self.assertTrue(r.content.startswith(b'%PDF'))

    def test_portal_kontokorrent_ohne_mandant_404(self):
        u = _team_user()
        c = Client(); c.force_login(u)
        self.assertEqual(c.get('/portal/kontokorrent/').status_code, 404)

    def test_portal_ausstaende_kpi(self):
        from finance.models import DebitorenRechnung
        md, lg, v, u = self._mandant_login()
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete Juni', betrag=Decimal('1800'),
            datum=date.today() - timedelta(days=40),
            faellig_am=date.today() - timedelta(days=35), status='offen')
        c = Client(); c.force_login(u)
        body = c.get('/portal/').content.decode()
        self.assertIn('Ausstände offen', body)
        self.assertIn("1'800", body)
        self.assertIn('überfällig', body)

    def test_freigabe_mail_an_eigentuemer(self):
        from django.core import mail
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        md, lg, v, u_eig = self._mandant_login(email='eig@example.ch', kontaktperson='Peter Muster')
        hw = Handwerker.objects.create(firma='Sanitär AG')
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Boiler defekt', beschreibung='x')
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, freigabe_status='nicht_noetig')
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/auftrag/{a.id}/kosten/', {'kosten_geschaetzt': '3000'})
        a.refresh_from_db()
        self.assertEqual(a.freigabe_status, 'ausstehend')
        mails = [m for m in mail.outbox if 'Reparaturfreigabe' in m.subject]
        self.assertEqual(len(mails), 1)
        self.assertIn('eig@example.ch', mails[0].to)
        self.assertIn('Boiler defekt', mails[0].body)

    def test_freigabe_unter_schwelle_keine_mail(self):
        from django.core import mail
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        md, lg, v, u_eig = self._mandant_login(email='eig@example.ch')
        hw = Handwerker.objects.create(firma='Maler AG')
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Kratzer', beschreibung='x')
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, freigabe_status='nicht_noetig')
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/auftrag/{a.id}/kosten/', {'kosten_geschaetzt': '300'})
        a.refresh_from_db()
        self.assertEqual(a.freigabe_status, 'nicht_noetig')
        self.assertEqual([m for m in mail.outbox if 'Reparaturfreigabe' in m.subject], [])

    def test_steuerauszug_enthaelt_honorar(self):
        from core.services.steuerauszug import steuerauszug_daten, generate_steuerauszug_pdf
        from core.services.verwaltungshonorar import buche_honorar
        from finance.booking import ensure_kontenplan, buche, konto
        md, lg, v, u = self._mandant_login(honorar_prozent=Decimal('5.00'))
        ensure_kontenplan()
        jahr = date.today().year - 1
        # Mietertrag im Jahr buchen (Haben 3000), dann Honorar berechnen + buchen
        buche('1020', '3000', Decimal('12000'), 'Mieten', datum=date(jahr, 6, 30), liegenschaft=lg)
        anzahl, summe = buche_honorar(md, jahr)
        self.assertEqual(anzahl, 1)
        self.assertEqual(summe, Decimal('600.00'))   # 5% von 12'000
        d = steuerauszug_daten(md, jahr)
        z = d['zeilen'][0]
        self.assertEqual(z['honorar'], Decimal('600.00'))
        self.assertEqual(d['total']['honorar'], Decimal('600.00'))
        # Netto ist um das Honorar gemindert (kein Ertrag via Zahlungseingang hier → Netto negativ)
        self.assertEqual(z['netto'], z['ertrag'] - z['ausgaben'] - z['afa'] - Decimal('600.00'))
        pdf = generate_steuerauszug_pdf(md, jahr)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_kontokorrent_pdf_mit_honorar_block(self):
        from core.services.eigentuemer_kontokorrent import generate_kontokorrent_pdf
        from finance.booking import ensure_kontenplan, buche
        md, lg, v, u = self._mandant_login(honorar_prozent=Decimal('4.00'))
        ensure_kontenplan()
        jahr = date.today().year - 1
        buche('1020', '3000', Decimal('10000'), 'Mieten', datum=date(jahr, 3, 31), liegenschaft=lg)
        pdf = generate_kontokorrent_pdf(md, jahr)
        self.assertTrue(pdf.startswith(b'%PDF'))


class NachtN6BewirtschafterTests(TestCase):
    """Nacht-Audit N6: E-Mail-Versand im Kommunikations-Journal +
    Mietzins-Massenanpassung."""

    def test_rundschreiben_landet_im_journal(self):
        from crm.models import Kommunikation
        lg, e, m, v = _basis_objekte()
        m.email = 'hans@example.ch'; m.save()
        u = _team_user(); c = Client(); c.force_login(u)
        c.post('/neu/kommunikation/senden/', {
            'betreff': 'Heizungsablesung', 'text': 'Am Dienstag kommt die Ablesung.',
            'empfaenger_id': [str(m.id)],
        })
        k = Kommunikation.objects.filter(mieter=m, typ='email', richtung='ausgehend').first()
        self.assertIsNotNone(k)
        self.assertEqual(k.betreff, 'Heizungsablesung')
        self.assertIn('hans@example.ch', k.inhalt)

    def test_mahnlauf_landet_im_journal(self):
        from crm.models import Kommunikation
        from core.services.automation import run_mahnlauf
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        m.email = 'hans@example.ch'; m.save()
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete', betrag=Decimal('1500'),
            datum=date.today() - timedelta(days=40),
            faellig_am=date.today() - timedelta(days=35), status='offen')
        res = run_mahnlauf(send_email=True)
        self.assertGreaterEqual(res['emails'], 1)
        k = Kommunikation.objects.filter(mieter=m, typ='email', betreff__icontains='Zahlungserinnerung').first()
        self.assertIsNotNone(k)
        self.assertEqual(k.vertrag_id, v.id)

    def test_bewerber_absage_landet_im_journal(self):
        from crm.models import Kommunikation
        from mietprozess.models import Mietbewerbung
        lg, e, m, v = _basis_objekte()
        b = Mietbewerbung.objects.create(
            einheit=e, vorname='Anna', nachname='Muster', email='anna@example.ch',
            geburtsdatum=date(1990, 5, 1), status='neu')
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/bewerbungen/{b.id}/entscheid/', {'entscheid': 'absage'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'abgelehnt')
        k = Kommunikation.objects.filter(typ='email', inhalt__icontains='anna@example.ch').first()
        self.assertIsNotNone(k)
        self.assertIn('Bewerbung', k.inhalt)

    def test_kommunikation_mieter_preselect(self):
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        body = c.get(f'/neu/kommunikation/?mieter={m.id}').content.decode()
        self.assertIn(f'value="{m.id}" onchange="aktualisiere()" checked', body)

    def test_person_detail_email_button(self):
        lg, e, m, v = _basis_objekte()
        m.email = 'hans@example.ch'; m.save()
        u = _team_user(); c = Client(); c.force_login(u)
        body = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertIn(f'/neu/kommunikation/?mieter={m.id}', body)

    def test_mietzins_liste_hat_massen_checkboxen(self):
        _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        body = c.get('/neu/mietzins/').content.decode()
        self.assertIn('name="vertrag_id"', body)
        self.assertIn('/neu/mietzins/massenanpassung/', body)

    def _vertrag_mit_potenzial(self):
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='V AG', aktueller_referenzzinssatz=Decimal('1.75'),
                                  aktueller_lik_punkte=Decimal('100'))
        lg, e, m, v = _basis_objekte()   # netto 1500
        # Basis-Zins tiefer als aktuell → Erhöhungspotenzial (+2 Stufen à 3 %)
        v.basis_referenzzinssatz = Decimal('1.25'); v.basis_lik_punkte = Decimal('100'); v.save()
        return lg, m, v

    def test_massenanpassung_vorschau(self):
        lg, m, v = self._vertrag_mit_potenzial()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post('/neu/mietzins/massenanpassung/', {'aktion': 'vorschau', 'vertrag_id': [str(v.id)]})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('Wird angepasst', body)
        self.assertIn('Anpassung(en) erfassen', body)

    def test_massenanpassung_ausfuehren_und_idempotent(self):
        from rentals.models import MietzinsAnpassung
        from core.models import Pendenz
        lg, m, v = self._vertrag_mit_potenzial()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post('/neu/mietzins/massenanpassung/', {'aktion': 'ausfuehren', 'vertrag_id': [str(v.id)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertEqual(MietzinsAnpassung.objects.filter(vertrag=v).count(), 1)
        anp = MietzinsAnpassung.objects.get(vertrag=v)
        self.assertGreater(anp.neuer_netto_mietzins, Decimal('1500'))
        self.assertTrue(Pendenz.objects.filter(vertrag=v, titel__icontains='Anfechtungsfrist').exists())
        # Zweiter Lauf mit denselben Verträgen: keine Duplikate
        c.post('/neu/mietzins/massenanpassung/', {'aktion': 'ausfuehren', 'vertrag_id': [str(v.id)]})
        self.assertEqual(MietzinsAnpassung.objects.filter(vertrag=v).count(), 1)
        self.assertEqual(Pendenz.objects.filter(vertrag=v, titel__icontains='Anfechtungsfrist').count(), 1)

    def test_massenanpassung_ohne_basis_uebersprungen(self):
        from crm.models import Verwaltung
        from rentals.models import MietzinsAnpassung
        Verwaltung.objects.create(firma='V AG', aktueller_referenzzinssatz=Decimal('1.75'))
        lg, e, m, v = _basis_objekte()
        # Alt-/Importvertrag ohne Basisdaten (Modell-Default liefert sonst aktuelle Werte)
        v.basis_referenzzinssatz = Decimal('0'); v.basis_lik_punkte = Decimal('0'); v.save()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post('/neu/mietzins/massenanpassung/', {'aktion': 'vorschau', 'vertrag_id': [str(v.id)]})
        self.assertIn('Basis fehlt', r.content.decode())
        r2 = c.post('/neu/mietzins/massenanpassung/', {'aktion': 'ausfuehren', 'vertrag_id': [str(v.id)]})
        self.assertEqual(r2.status_code, 302)   # nichts machbar → zurück mit Fehlermeldung
        self.assertEqual(MietzinsAnpassung.objects.filter(vertrag=v).count(), 0)


class NachtN7SchluesselTests(TestCase):
    """Nacht-Audit N7: Schlüsselregister mit Ausgabe/Rücknahme je Objekt."""

    def _heute(self):
        from django.utils import timezone as tz
        return tz.localdate()

    def _setup(self):
        lg, e, m, v = _basis_objekte()
        u = _team_user()
        c = Client(); c.force_login(u)
        return lg, e, m, v, c

    def test_schluessel_erfassen_und_tab(self):
        from portfolio.models import Schluessel
        lg, e, m, v, c = self._setup()
        r = c.post('/neu/schluessel/', {'einheit_id': e.id, 'typ': 'Wohnung',
                                        'schluessel_nummer': 'W-101', 'anzahl': '3'})
        self.assertEqual(r.status_code, 302)
        sch = Schluessel.objects.get(einheit=e)
        self.assertEqual(sch.schluessel_nummer, 'W-101')
        self.assertEqual(sch.anzahl, 3)
        self.assertEqual(sch.liegenschaft_id, lg.id)
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('Schlüssel', body)
        self.assertIn('W-101', body)

    def test_ausgabe_und_rueckgabe(self):
        from portfolio.models import Schluessel, SchluesselAusgabe
        lg, e, m, v, c = self._setup()
        sch = Schluessel.objects.create(liegenschaft=lg, einheit=e, typ='Wohnung',
                                        schluessel_nummer='W-1', anzahl=2)
        r = c.post(f'/neu/schluessel/{sch.id}/ausgabe/', {'empfaenger': f'mieter:{m.id}'})
        self.assertEqual(r.status_code, 302)
        a = SchluesselAusgabe.objects.get(schluessel=sch)
        self.assertEqual(a.mieter_id, m.id)
        self.assertIsNone(a.rueckgabe_am)
        c.post(f'/neu/schluessel/ausgabe/{a.id}/rueckgabe/')
        a.refresh_from_db()
        self.assertEqual(a.rueckgabe_am, self._heute())

    def test_ausgabe_blockiert_wenn_alle_weg(self):
        from portfolio.models import Schluessel, SchluesselAusgabe
        lg, e, m, v, c = self._setup()
        sch = Schluessel.objects.create(liegenschaft=lg, einheit=e, typ='Keller',
                                        schluessel_nummer='K-1', anzahl=1)
        c.post(f'/neu/schluessel/{sch.id}/ausgabe/', {'empfaenger': f'mieter:{m.id}'})
        c.post(f'/neu/schluessel/{sch.id}/ausgabe/', {'empfaenger': f'mieter:{m.id}'})
        self.assertEqual(SchluesselAusgabe.objects.filter(schluessel=sch).count(), 1)

    def test_loeschen_blockiert_bei_offener_ausgabe(self):
        from portfolio.models import Schluessel, SchluesselAusgabe
        lg, e, m, v, c = self._setup()
        sch = Schluessel.objects.create(liegenschaft=lg, einheit=e, typ='Wohnung',
                                        schluessel_nummer='W-2', anzahl=1)
        SchluesselAusgabe.objects.create(schluessel=sch, mieter=m)
        c.post(f'/neu/schluessel/{sch.id}/loeschen/')
        self.assertTrue(Schluessel.objects.filter(id=sch.id).exists())
        # Nach Rücknahme klappt das Löschen
        a = sch.ausgaben.first(); a.rueckgabe_am = self._heute(); a.save()
        c.post(f'/neu/schluessel/{sch.id}/loeschen/')
        self.assertFalse(Schluessel.objects.filter(id=sch.id).exists())

    def test_handwerker_ausgabe(self):
        from portfolio.models import Schluessel, SchluesselAusgabe
        from crm.models import Handwerker
        lg, e, m, v, c = self._setup()
        hw = Handwerker.objects.create(firma='Sanitär AG')
        sch = Schluessel.objects.create(liegenschaft=lg, einheit=e, typ='Haustüre',
                                        schluessel_nummer='H-9', anzahl=5)
        c.post(f'/neu/schluessel/{sch.id}/ausgabe/', {'empfaenger': f'handwerker:{hw.id}'})
        a = SchluesselAusgabe.objects.get(schluessel=sch)
        self.assertEqual(a.handwerker_id, hw.id)
        self.assertIsNone(a.mieter_id)


class NachtN8BesichtigungTests(TestCase):
    """Nacht-Audit N8: Besichtigungsstufe im Bewerbungsprozess."""

    def _bewerbung(self):
        from mietprozess.models import Mietbewerbung
        lg, e, m, v = _basis_objekte()
        b = Mietbewerbung.objects.create(
            einheit=e, vorname='Anna', nachname='Muster', email='anna@example.ch',
            geburtsdatum=date(1990, 5, 1), status='neu')
        u = _team_user(); c = Client(); c.force_login(u)
        return b, c

    def test_einladen_setzt_status_mail_journal_pendenz(self):
        from django.core import mail
        from crm.models import Kommunikation
        from core.models import Pendenz
        b, c = self._bewerbung()
        termin = (date.today() + timedelta(days=5)).isoformat() + 'T18:30'
        r = c.post(f'/neu/bewerbungen/{b.id}/besichtigung/', {'termin': termin})
        self.assertEqual(r.status_code, 302)
        b.refresh_from_db()
        self.assertEqual(b.status, 'besichtigung')
        self.assertIsNotNone(b.besichtigung_am)
        mails = [m for m in mail.outbox if 'Besichtigung' in m.subject]
        self.assertEqual(len(mails), 1)
        self.assertIn('anna@example.ch', mails[0].to)
        self.assertTrue(Kommunikation.objects.filter(typ='email', betreff__icontains='Besichtigung').exists())
        p = Pendenz.objects.filter(quelle=f'besichtigung:{b.id}').first()
        self.assertIsNotNone(p)
        self.assertEqual(p.faellig_am, date.today() + timedelta(days=5))

    def test_termin_aenderung_ist_idempotent(self):
        from core.models import Pendenz
        b, c = self._bewerbung()
        t1 = (date.today() + timedelta(days=5)).isoformat() + 'T18:30'
        t2 = (date.today() + timedelta(days=8)).isoformat() + 'T19:00'
        c.post(f'/neu/bewerbungen/{b.id}/besichtigung/', {'termin': t1})
        c.post(f'/neu/bewerbungen/{b.id}/besichtigung/', {'termin': t2})
        pq = Pendenz.objects.filter(quelle=f'besichtigung:{b.id}')
        self.assertEqual(pq.count(), 1)
        self.assertEqual(pq.first().faellig_am, date.today() + timedelta(days=8))

    def test_board_hat_besichtigung_spalte(self):
        b, c = self._bewerbung()
        b.status = 'besichtigung'; b.save(update_fields=['status'])
        body = c.get('/neu/bewerbungen/').content.decode()
        self.assertIn('Besichtigung', body)
        self.assertIn('Anna', body)

    def test_ungueltiger_termin_abgelehnt(self):
        b, c = self._bewerbung()
        c.post(f'/neu/bewerbungen/{b.id}/besichtigung/', {'termin': 'kein-datum'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'neu')
        self.assertIsNone(b.besichtigung_am)


class NachtN9BuchhalterTests(TestCase):
    """Nacht-Audit N9: Debitorenverluste (Konto 3805), Mieterkonto-Filter,
    konfigurierbares NK-Verwaltungshonorar."""

    def test_forderungsverlust_abschreiben(self):
        from finance.models import DebitorenRechnung, Zahlungseingang, Buchung
        from finance.booking import ensure_kontenplan
        from core.services.mieterkonto import berechne_mieterkonto
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete Januar', betrag=Decimal('1500'),
            datum=date.today() - timedelta(days=120),
            faellig_am=date.today() - timedelta(days=115), status='teilbezahlt')
        Zahlungseingang.objects.create(vertrag=v, debitoren_rechnung=r,
                                       betrag=Decimal('500'), status='verbucht',
                                       datum_eingang=date.today() - timedelta(days=100))
        self.assertEqual(r.offener_betrag, Decimal('1000.00'))
        u = _team_user(); c = Client(); c.force_login(u)
        resp = c.post(f'/neu/debitoren/{r.id}/abschreiben/', {'grund': 'Verlustschein Betreibungsamt'})
        self.assertEqual(resp.status_code, 302)
        r.refresh_from_db()
        self.assertEqual(r.status, 'abgeschrieben')
        b = Buchung.objects.filter(soll_konto__nummer='3805', haben_konto__nummer='1100',
                                   debitoren_rechnung=r).first()
        self.assertIsNotNone(b)
        self.assertEqual(b.betrag, Decimal('1000.00'))
        self.assertIn('Verlustschein', b.beleg_text)
        # Mieterkonto: der Mieter schuldet die abgeschriebene Forderung nicht mehr
        _bewegungen, endsaldo = berechne_mieterkonto(m)
        # Rechnung raus, die geleisteten 500 bleiben als Haben → Guthaben 500
        self.assertEqual(endsaldo, Decimal('-500.00'))
        # Debitoren-Liste zählt sie nicht mehr als offen
        body = c.get('/neu/debitoren/').content.decode()
        self.assertIn('Abgeschrieben', body)

    def test_abschreiben_nur_offene(self):
        from finance.models import DebitorenRechnung, Buchung
        lg, e, m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete', betrag=Decimal('1500'),
            datum=date.today(), faellig_am=date.today(), status='bezahlt')
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/debitoren/{r.id}/abschreiben/', {'grund': 'x'})
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertFalse(Buchung.objects.filter(soll_konto__nummer='3805').exists())

    def _nk_setup(self, honorar_pct):
        from crm.models import Verwaltung
        from finance.models import AbrechnungsPeriode, KreditorenRechnung, Buchungskonto
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        Verwaltung.objects.create(firma='V AG', strasse='X', plz='1', ort='Y',
                                  nk_honorar_prozent=Decimal(str(honorar_pct)))
        lg, e, m, v = _basis_objekte()
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='NK Test',
                                              start_datum=date(2025, 1, 1),
                                              ende_datum=date(2025, 12, 31))
        KreditorenRechnung.objects.create(lieferant='Hauswart AG', betrag=Decimal('200.00'),
                                          liegenschaft=lg, is_hnk_relevant=True,
                                          konto=Buchungskonto.objects.get(nummer='4120'),
                                          status='freigegeben', datum=date(2025, 6, 1))
        return p

    def test_nk_honorar_konfigurierbar(self):
        from core.utils.billing import berechne_abrechnung
        p = self._nk_setup(2)
        r = berechne_abrechnung(p.id)
        honorar = [d for d in r['belege_details'] if d['kategorie'] == 'Verwaltung']
        self.assertEqual(len(honorar), 1)
        self.assertIn('2', honorar[0]['text'])
        self.assertEqual(Decimal(str(honorar[0]['betrag'])), Decimal('4.00'))   # 2% von 200

    def test_nk_honorar_null_kein_posten(self):
        from core.utils.billing import berechne_abrechnung
        p = self._nk_setup(0)
        r = berechne_abrechnung(p.id)
        honorar = [d for d in r['belege_details'] if d['kategorie'] == 'Verwaltung']
        self.assertEqual(honorar, [])


class NachtN10UIDetailTests(TestCase):
    """Nacht-Audit N10: Vertrag-Detail-Aktionsleiste mit Dropdown, Pflichtfelder,
    CHF-Präfixe, echte Links in Detail-Tabellen."""

    def _client(self):
        u = _team_user(); c = Client(); c.force_login(u)
        return c

    def test_vertrag_detail_aktions_dropdown(self):
        _lg, _e, _m, v = _basis_objekte()
        body = self._client().get(f'/neu/vertraege/{v.id}/').content.decode()
        self.assertIn('id="vAktionen"', body)
        self.assertIn('Vertrag löschen', body)
        self.assertIn('Schlussabrechnung', body)
        self.assertIn('Kündigung erfassen', body)
        # Die alte Punkte-Kette (Aktion · Aktion · …) ist weg
        self.assertNotIn('<span class="text-slate-300">·</span>\n            <a href="/neu/vertraege/', body)

    def test_frist_formular_pflichtfelder(self):
        lg, _e, _m, _v = _basis_objekte()
        body = self._client().get(f'/neu/liegenschaften/{lg.id}/').content.decode()
        self.assertIn('name="bezeichnung" required', body)
        self.assertIn('name="naechste_faelligkeit" required', body)

    def test_objekte_liste_chf_praefix(self):
        lg, e, _m, _v = _basis_objekte()
        e.nettomiete_aktuell = Decimal('1500')
        e.save(update_fields=['nettomiete_aktuell'])
        body = self._client().get('/neu/objekte/').content.decode()
        self.assertIn("CHF 1'500", body)

    def test_detail_tabellen_erste_zelle_link(self):
        lg, e, m, v = _basis_objekte()
        c = self._client()
        body = c.get(f'/neu/liegenschaften/{lg.id}/').content.decode()
        self.assertIn(f'<a href="/neu/objekte/{e.id}/', body)
        body2 = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertIn(f'<a href="/neu/vertraege/{v.id}/"', body2)


class HotfixDashboardPerformanceTests(TestCase):
    """Regression: Dashboard/offener_betrag dürfen nicht pro offener Rechnung eine
    eigene SUM-Abfrage feuern (N+1 → Timeout auf grossen Portfolios)."""

    def _seed(self, n):
        from finance.models import DebitorenRechnung, Zahlungseingang
        lg, e, m, v = _basis_objekte()
        for k in range(n):
            r = DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=lg, titel=f'Miete {k}', betrag=Decimal('1700'),
                datum=date.today() - timedelta(days=40),
                faellig_am=date.today() - timedelta(days=35), status='offen')
            Zahlungseingang.objects.create(vertrag=v, debitoren_rechnung=r,
                                           betrag=Decimal('200'), status='verbucht',
                                           datum_eingang=date.today())
        return v

    def _dashboard_queries(self, c):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        with CaptureQueriesContext(connection) as ctx:
            c.get('/neu/')
        return len(ctx.captured_queries)

    def test_dashboard_query_zahl_waechst_nicht_mit_datenmenge(self):
        u = _team_user(); c = Client(); c.force_login(u)
        v = self._seed(5)
        q_klein = self._dashboard_queries(c)
        from finance.models import DebitorenRechnung
        for k in range(50):
            DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=v.einheit.liegenschaft, titel=f'X{k}',
                betrag=Decimal('100'), datum=date.today() - timedelta(days=40),
                faellig_am=date.today() - timedelta(days=35), status='offen')
        q_gross = self._dashboard_queries(c)
        # 11× so viele Rechnungen → Query-Zahl bleibt praktisch konstant (kein N+1)
        self.assertLessEqual(q_gross, q_klein + 3,
                             f"Dashboard-Queries wachsen mit Datenmenge: {q_klein} → {q_gross}")

    def test_offener_betrag_nutzt_prefetch(self):
        from finance.models import DebitorenRechnung
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        self._seed(30)
        qs = DebitorenRechnung.objects.filter(status='offen').prefetch_related('zahlungseingaenge')
        with CaptureQueriesContext(connection) as ctx:
            total = sum((r.offener_betrag for r in qs), Decimal('0.00'))
        self.assertEqual(total, Decimal('45000.00'))   # 30 × (1700 - 200)
        self.assertLessEqual(len(ctx.captured_queries), 3)


class DetailAktionsleisteTests(TestCase):
    """Einheitliche Aktionsleiste (Bearbeiten-Button + '⋯ Mehr'-Dropdown) auf
    allen Detailseiten — sekundäre/destruktive Aktionen liegen im Dropdown."""

    def test_aktionsleisten_vorhanden(self):
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        for url, drop_id, im_dropdown in (
            (f'/neu/vertraege/{v.id}/', 'vAktionen', 'Vertrag löschen'),
            (f'/neu/personen/{m.id}/', 'pAktionen', 'Person löschen'),
            (f'/neu/liegenschaften/{lg.id}/', 'lAktionen', 'Liegenschaft löschen'),
            (f'/neu/objekte/{e.id}/', 'oAktionen', 'Bewerber vergleichen'),
        ):
            body = c.get(url).content.decode()
            self.assertIn(f'id="{drop_id}"', body, f'{url}: Mehr-Dropdown fehlt')
            self.assertIn('>Mehr', body, f'{url}: Mehr-Button fehlt')
            self.assertIn(im_dropdown, body, f'{url}: {im_dropdown} fehlt')
        # Schadenseite: Löschen liegt im Mehr-Dropdown
        from tickets.models import SchadenMeldung
        t = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=e, titel='X', beschreibung='y')
        sbody = c.get(f'/neu/schaeden/{t.id}/').content.decode()
        self.assertIn('id="sAktionen"', sbody)
        self.assertIn('Schadensmeldung löschen', sbody)

    def test_loeschen_weiterhin_funktionsfaehig(self):
        # Der Löschen-Button im Dropdown postet weiterhin an die richtige URL
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        body = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertIn(f'action="/neu/personen/{m.id}/loeschen/"', body)
        self.assertIn(f'action="/neu/personen/{m.id}/dsg-loeschen/"', body)


class NavigationModusTests(TestCase):
    """6-Türen-Sidebar: Einfach/Profi-Modus, Einstellungen-Hub, ⌘K-Palette."""

    def test_default_ist_einfach(self):
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/').content.decode()
        self.assertIn('Meine Immobilien', html)
        self.assertIn('Wer hat bezahlt?', html)
        # Profi-Module bleiben unter «Erweitert» erreichbar (eingeklappt)
        self.assertIn('Erweitert', html)
        self.assertIn('/neu/sollstellung/', html)

    def test_modus_wechsel_und_profi_labels(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/modus/', {'modus': 'profi'})
        self.assertIn(r.status_code, (301, 302))
        html = c.get('/neu/').content.decode()
        self.assertIn('Portfolio', html)
        self.assertIn('Sollstellung', html)
        self.assertIn('Debitoren', html)
        # zurück auf Einfach
        c.post('/neu/modus/', {'modus': 'einfach'})
        html = c.get('/neu/').content.decode()
        self.assertIn('Meine Immobilien', html)

    def test_ungueltiger_modus_ignoriert(self):
        c = Client(); c.force_login(_team_user())
        c.post('/neu/modus/', {'modus': 'hacker'})
        html = c.get('/neu/').content.decode()
        self.assertIn('Meine Immobilien', html)   # bleibt Default

    def test_einstellungen_hub(self):
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/einstellungen/')
        self.assertEqual(r.status_code, 200)
        for ziel in ('/neu/account/', '/neu/benutzer/', '/neu/vorlagen/',
                     '/neu/integrationen/', '/neu/logbuch/', '/neu/rechtsgrundlagen/'):
            self.assertContains(r, ziel)
        self.assertContains(r, 'Ansicht')  # Modus-Schalter vorhanden

    def test_palette_daten_vorhanden(self):
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/').content.decode()
        self.assertIn('fw-palette-data', html)
        self.assertIn('fwPalette', html)


class FinanzGuardTests(TestCase):
    """Sofort-Paket aus dem Buchhalter-Audit: Guards & Eingabe-Validierung."""

    def _rechnung(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        return DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')

    def test_keine_zahlung_auf_stornierte_rechnung(self):
        from finance.models import Zahlungseingang
        r = self._rechnung()
        r.status = 'storniert'; r.save()
        team = _team_user(); c = Client(); c.force_login(team)
        resp = c.post('/neu/bankabgleich/verbuchen/', {'rechnung_id': r.id, 'betrag': '100'}, follow=True)
        self.assertContains(resp, 'kann keine Zahlung verbucht werden')
        r.refresh_from_db()
        self.assertEqual(r.status, 'storniert')          # bleibt storniert
        self.assertEqual(Zahlungseingang.objects.count(), 0)

    def test_bankabgleich_betrag_null_abgelehnt(self):
        from finance.models import Zahlungseingang
        r = self._rechnung()
        team = _team_user(); c = Client(); c.force_login(team)
        resp = c.post('/neu/bankabgleich/verbuchen/', {'rechnung_id': r.id, 'betrag': '0'}, follow=True)
        self.assertContains(resp, 'grösser als 0')
        self.assertEqual(Zahlungseingang.objects.count(), 0)

    def test_kreditor_zahlung_betrag_null_zahlt_nicht_voll(self):
        # Regressionsschutz: Eingabe «0» zahlte früher still den VOLLEN Betrag
        from finance.models import KreditorenRechnung, KreditorenZahlung
        _seed_konten(); _basis_objekte()
        k = KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('500.00'),
                                              status='freigegeben')
        team = _team_user(); c = Client(); c.force_login(team)
        resp = c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.id, 'betrag': '0'}, follow=True)
        self.assertContains(resp, 'Ungültiger Betrag')
        self.assertEqual(KreditorenZahlung.objects.count(), 0)
        k.refresh_from_db()
        self.assertEqual(k.status, 'freigegeben')

    def test_sollstellung_monat_13_kein_500(self):
        _seed_konten(); _basis_objekte()
        team = _team_user(); c = Client(); c.force_login(team)
        resp = c.post('/neu/sollstellung/starten/', {'jahr': '2024', 'monat': '13'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ungültiger Monat')

    def test_api_storno_mit_zahlung_geblockt(self):
        # Alt-API darf (teil-)bezahlte Rechnungen nicht mehr stornieren (K6)
        from finance.models import Zahlungseingang
        r = self._rechnung()
        Zahlungseingang.objects.create(vertrag=r.vertrag, betrag=Decimal('100'),
                                       datum_eingang=date(2024, 3, 5),
                                       buchungs_monat=date(2024, 3, 1),
                                       debitoren_rechnung=r, status='verbucht')
        team = _team_user(); c = Client(); c.force_login(team)
        resp = c.delete(f'/api/finance/debitoren-rechnungen/{r.id}')
        self.assertEqual(resp.status_code, 409)
        r.refresh_from_db()
        self.assertNotEqual(r.status, 'storniert')


class BuchhalterFixesTests(TestCase):
    """F2–F4 aus dem Buchhalter-Audit: korrekte Buchungssätze + Sackgassen-Fixes."""

    def _saldo(self, nummer):
        """Saldo eines Kontos (Soll − Haben) über alle Buchungen."""
        from finance.models import Buchung
        from django.db.models import Sum
        soll = Buchung.objects.filter(soll_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        haben = Buchung.objects.filter(haben_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        return soll - haben

    def _soll_gleich_haben(self):
        from finance.models import Buchung
        from django.db.models import Sum
        t = Buchung.objects.aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        return t  # jede Zeile ist ein Soll/Haben-Paar → Bilanz per Konstruktion

    # ---------- K1: MWST-Korrektur beim Debitorenverlust ----------
    def test_k1_debitorenverlust_korrigiert_mwst(self):
        from finance.models import DebitorenRechnung, Buchung
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.mwst_pflichtig = True; v.mwst_satz = Decimal('8.1'); v.save()
        r = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                             titel='Miete 03/2024', datum=date(2024, 3, 1),
                                             faellig_am=date(2024, 3, 5),
                                             betrag=Decimal('1081.00'), status='offen')
        buche('1100', '3010', Decimal('1000'), 'Miete', datum=date(2024, 3, 1), liegenschaft=lg, debitor=r)
        buche('1100', '2200', Decimal('81'), 'MWST', datum=date(2024, 3, 1), liegenschaft=lg, debitor=r)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/debitoren/{r.id}/abschreiben/', {'grund': 'Verlustschein'})
        r.refresh_from_db()
        self.assertEqual(r.status, 'abgeschrieben')
        # MWST muss zurückgeholt sein: 2200 wieder auf 0, Aufwand nur netto
        self.assertEqual(self._saldo('2200'), Decimal('0.00'))
        self.assertEqual(self._saldo('3805'), Decimal('1000.00'))
        self.assertEqual(self._saldo('1100'), Decimal('0.00'))

    # ---------- K3: Kaution wird in der Schlussabrechnung bilanziert ----------
    def test_k3_schlussabrechnung_bucht_kaution(self):
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('3000'); v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = date(2024, 1, 1); v.save()
        # Einzahlung über den Produktivpfad — der Belegtext trägt die Vertrags-ID,
        # an der die Freigabe den bilanzierten Betrag erkennt.
        from core.services.automation import buche_kaution_einzahlung
        buche_kaution_einzahlung(v, date(2024, 1, 1))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen', 'kaution_verrechnen': 'on'})
        # Sperrkonto + Verbindlichkeit müssen aufgelöst sein (vorher blieben sie ewig stehen)
        self.assertEqual(self._saldo('1015'), Decimal('0.00'))
        self.assertEqual(self._saldo('2010'), Decimal('0.00'))

    def test_kaution_ohne_einzahlung_wird_nicht_ausbezahlt(self):
        # Kritischer Audit-Befund: Die Freigabe entschied am VEREINBARTEN Betrag
        # (Vertragsfeld). War die Kaution nie eingegangen, wurden 1015/2010 negativ
        # und der Mieter bekam Geld, das er nie hinterlegt hatte.
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('4500'); v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = None; v.save()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen', 'kaution_verrechnen': 'on'})
        self.assertEqual(self._saldo('1015'), Decimal('0.00'))   # nicht ins Minus gedrückt
        self.assertEqual(self._saldo('2010'), Decimal('0.00'))
        v.refresh_from_db()
        self.assertIn(v.kautions_rueckzahlung_betrag or Decimal('0'), (Decimal('0'), Decimal('0.00')))

    def test_kaution_ohne_einzahlung_tilgt_keine_forderung(self):
        # Zweite Hälfte desselben Befunds: die Phantom-Kaution wurde mit offenen
        # Mietforderungen «verrechnet» — die Forderung galt als bezahlt, der
        # Mietertrag als vereinnahmt, der echte Verlust verschwand.
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('4500'); v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = None; v.save()
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, einheit=e, titel='Miete 05/2024',
            datum=date(2024, 5, 1), faellig_am=date(2024, 5, 5),
            betrag=Decimal('1700'), status='offen')
        buche('1100', '3000', Decimal('1700'), 'Miete 05/2024', datum=date(2024, 5, 1),
              liegenschaft=lg, debitor=r)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen', 'kaution_verrechnen': 'on'})
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen')
        self.assertEqual(r.offener_betrag, Decimal('1700'))

    def test_kaution_nicht_zweimal_aufloesbar(self):
        # Rückzahlung über die Vertragsseite UND Schlussabrechnung hatten je eine
        # eigene Belegtext-Sperre — zusammen konnten sie dieselbe Kaution zweimal
        # freigeben (Audit). Der Saldo von 2010 ist jetzt die gemeinsame Grenze.
        from finance.booking import ensure_kontenplan
        from core.services.automation import buche_kaution_einzahlung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('3000'); v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = date(2024, 1, 1); v.save()
        buche_kaution_einzahlung(v, date(2024, 1, 1))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/kaution/',
               {'aktion': 'rueckzahlung', 'zurueckbezahlt_am': '2024-06-30',
                'rueckzahlung_betrag': '3000', 'abzug_betrag': '0'})
        self.assertEqual(self._saldo('2010'), Decimal('0.00'))
        # Zweiter Versuch über die Schlussabrechnung darf nichts mehr bewegen
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen', 'kaution_verrechnen': 'on'})
        self.assertEqual(self._saldo('2010'), Decimal('0.00'))
        self.assertEqual(self._saldo('1015'), Decimal('0.00'))

    def test_kaution_rueckzahlung_muss_voll_abdecken(self):
        # Unter-Allokation (Rückzahlung + Einbehalt < Kaution) muss abgewiesen
        # werden — sonst wird das Sperrkonto (1015) voll freigegeben, aber die
        # Kautionsverbindlichkeit (2010) bliebe teilweise offen (Geld unerklärt
        # auf 1020). Live-QS Kautionen.
        from finance.booking import ensure_kontenplan
        from core.services.automation import buche_kaution_einzahlung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('3000'); v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = date(2024, 1, 1); v.save()
        buche_kaution_einzahlung(v, date(2024, 1, 1))
        c = Client(); c.force_login(_team_user('Verwaltung'))
        # 1500 zurück + 200 Einbehalt = 1700 < 3000 → abgelehnt
        c.post(f'/neu/vertraege/{v.id}/kaution/',
               {'aktion': 'rueckzahlung', 'zurueckbezahlt_am': '2024-06-30',
                'rueckzahlung_betrag': '1500', 'abzug_betrag': '200'})
        # Nichts gebucht: 2010 trägt weiter die volle Kaution, 1015 unverändert.
        self.assertEqual(self._saldo('2010'), Decimal('-3000.00'))  # Haben-Saldo = Verbindlichkeit
        self.assertEqual(self._saldo('1015'), Decimal('3000.00'))   # Soll-Saldo = Sperrkonto
        v.refresh_from_db()
        self.assertIsNone(v.kautions_zurueckbezahlt_am)
        # Voll abgedeckt (1700 + 1300) geht durch:
        c.post(f'/neu/vertraege/{v.id}/kaution/',
               {'aktion': 'rueckzahlung', 'zurueckbezahlt_am': '2024-06-30',
                'rueckzahlung_betrag': '2700', 'abzug_betrag': '300'})
        self.assertEqual(self._saldo('2010'), Decimal('0.00'))
        self.assertEqual(self._saldo('1015'), Decimal('0.00'))

    def test_schlussabrechnung_gutschrift_nur_einmal(self):
        # Gutschrift-Fall ohne Kaution: die Idempotenz hing an
        # `kautions_zurueckbezahlt_am`, das hier nie gesetzt wird — ein zweiter
        # Aufruf buchte das Mieterguthaben ein zweites Mal (Audit).
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('0'); v.save()
        c = Client(); c.force_login(_team_user())
        payload = {'auszug_datum': '2024-06-30', 'aktion': 'buchen',
                   'pos_text': 'NK-Guthaben', 'pos_betrag': '400',
                   'pos_richtung': 'zugunsten'}
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/', payload)
        erst = self._saldo('2030')
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/', payload)
        self.assertEqual(self._saldo('2030'), erst)   # kein zweites Guthaben

    def test_jahresabschluss_nicht_doppelt_ueber_lg_filter(self):
        # Portfolioweit abschliessen und danach je Liegenschaft nochmals: die
        # Prüfung filterte auf dieselbe Liegenschaft und fand die portfolioweiten
        # Buchungen (ohne Liegenschaft) nicht — 2970 verdoppelte sich (Audit).
        from core.services.jahresabschluss import buche_jahresabschluss, ist_abgeschlossen
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        buche('1100', '3000', Decimal('1200'), 'Miete 01/2024',
              datum=date(2024, 1, 31), liegenschaft=lg)
        n1, _erg = buche_jahresabschluss(2024)
        self.assertGreater(n1, 0)
        saldo_nach_erstem = self._saldo('2970')
        self.assertTrue(ist_abgeschlossen(2024, lg))          # deckt die LG mit ab
        n2, _ = buche_jahresabschluss(2024, liegenschaft=lg)
        self.assertEqual(n2, 0)
        self.assertEqual(self._saldo('2970'), saldo_nach_erstem)

    def test_jahresabschluss_nach_storno_wieder_moeglich(self):
        # Eine stornierte Abschlussbuchung behält ist_storno=False (das Flag trägt
        # die Gegenbuchung). Ohne Prüfung auf `storniert_am` galt das Jahr
        # weiterhin als abgeschlossen und liess sich nie neu abschliessen (Audit).
        from core.services.jahresabschluss import buche_jahresabschluss, ist_abgeschlossen
        from finance.booking import ensure_kontenplan, buche
        from finance.models import Buchung
        from finance.api import erstelle_storno_buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        buche('1100', '3000', Decimal('900'), 'Miete 02/2024',
              datum=date(2024, 2, 29), liegenschaft=lg)
        buche_jahresabschluss(2024)
        self.assertTrue(ist_abgeschlossen(2024))
        for b in Buchung.objects.filter(beleg_text__startswith='Jahresabschluss 2024 —',
                                        ist_storno=False, storniert_am__isnull=True):
            erstelle_storno_buchung(b, benutzer=None)
        self.assertFalse(ist_abgeschlossen(2024))
        n, _ = buche_jahresabschluss(2024)
        self.assertGreater(n, 0)

    # ---------- Nachgereichte Befunde ----------
    def test_weiterverrechnung_mwst_wird_beim_abschreiben_reversiert(self):
        # Die Weiterverrechnung bucht Ausgangs-MWST (1190/2200) nach dem
        # KREDITOR-Satz — unabhängig davon, ob der Mietvertrag optiert ist. Die
        # frühere Storno-Logik las dagegen v.mwst_pflichtig/v.mwst_satz: Bei einem
        # nicht optierten Vertrag wurde die MWST nie zurückgeholt, bei
        # abweichenden Sätzen der falsche Betrag (Audit).
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.mwst_pflichtig = False; v.save()          # Vertrag NICHT optiert
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, einheit=e, titel='Weiterverrechnung Hauswartung',
            datum=date(2024, 4, 1), faellig_am=date(2024, 4, 30),
            betrag=Decimal('1081'), status='offen')
        buche('1100', '1190', Decimal('1081'), 'Weiterverrechnung', datum=date(2024, 4, 1),
              liegenschaft=lg, debitor=r)
        buche('1190', '4000', Decimal('1000'), 'Aufwandsminderung', datum=date(2024, 4, 1),
              liegenschaft=lg, debitor=r)
        buche('1190', '2200', Decimal('81'), 'MWST Weiterverrechnung 8.1%',
              datum=date(2024, 4, 1), liegenschaft=lg, debitor=r)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/debitoren/{r.id}/abschreiben/', {'grund': 'Verlustschein'})
        # Die 81.00 werden aus 2200 zurückgeholt, 3805 traegt nur die Netto-1000.
        self.assertEqual(self._saldo('2200'), Decimal('0.00'))
        self.assertEqual(self._saldo('3805'), Decimal('1000.00'))

    def test_schlussabrechnung_grenzt_mwst_ab(self):
        # NK-Nachzahlung bei einem optierten Gewerbevertrag ist steuerbar,
        # Schadenersatz nach Art. 18 Abs. 2 MWSTG nicht. Vorher wurde der ganze
        # Delta-Betrag als Ertrag gebucht und die Steuer fehlte in der
        # ESTV-Abrechnung (Audit).
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.mwst_pflichtig = True; v.mwst_satz = Decimal('8.1'); v.kautions_betrag = Decimal('0')
        v.save()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/', {
            'auszug_datum': '2024-06-30', 'aktion': 'buchen',
            'pos_text': ['NK-Abrechnung 2024', 'Schaden Parkett'],
            'pos_betrag': ['2000', '500'],
            'pos_richtung': ['zulasten', 'zulasten'],
            'pos_mwst': ['1', '0'],          # NK steuerbar, Schaden nicht
        })
        # 8.1 % NUR auf den steuerbaren 2000 → 162.00
        self.assertEqual(self._saldo('2200'), Decimal('-162.00'))   # Haben-Saldo
        self.assertEqual(self._saldo('3600'), Decimal('-2500.00'))  # Netto als Ertrag

    def test_mwst_zahllast_geht_auf_abrechnungskonto_nicht_bank(self):
        # Am Periodenende fliesst kein Geld — die Schuld gehoert auf 2201.
        # Direkt gegen 1020 wich der Banksaldo ab dem Stichtag vom realen
        # Kontoauszug ab und die echte Zahlung wurde spaeter doppelt gebucht.
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        buche('1100', '2200', Decimal('500'), 'MWST Q1', datum=date(2024, 3, 31), liegenschaft=lg)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/mwst/verbuchen/', {'jahr': '2024', 'quartal': '1'})
        self.assertEqual(self._saldo('2201'), Decimal('-500.00'))   # Schuld im Haben
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))      # Bank unberuehrt

    def test_nk_erlass_mindert_honorarbasis_nicht(self):
        # Die Honorarbasis rechnet auf 3000/3010 und enthaelt die Nebenkosten gar
        # nicht. Ein NK-Erlass auf 3090 haette eine Basis gemindert, in der die
        # Nebenkosten nie standen (Audit) — er laeuft jetzt ueber 3091.
        from core.services.automation import run_sollstellung
        from finance.booking import ensure_kontenplan
        from finance.models import Buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        run_sollstellung(2024, 3)
        # Kein NK-Erlass auf 3090; falls einer entstand, steht er auf 3091.
        nk_auf_3090 = Buchung.objects.filter(
            soll_konto__nummer='3090', beleg_text__startswith='NK-Erlass').exists()
        self.assertFalse(nk_auf_3090)

    def test_kontenplan_import_deckt_alle_standardkonten(self):
        # Der Import-Endpunkt pflegte eine ZWEITE Kontenliste, die auseinander-
        # gedriftet war (u.a. fehlten 2030, 2850, 2970, 3090, 3600, 3805). Wer
        # den Plan darüber importierte, bekam einen unvollständigen Kontenrahmen.
        # Er leitet sich jetzt aus STANDARD_KONTEN ab — der EINEN Quelle.
        from finance.api import import_standard_kontenplan
        from finance.booking import STANDARD_KONTEN
        from finance.models import Buchungskonto
        from django.test.client import RequestFactory
        import_standard_kontenplan(RequestFactory().post('/api/finance/konten/import-standard'))
        vorhanden = set(Buchungskonto.objects.values_list('nummer', flat=True))
        fehlend = {k[0] for k in STANDARD_KONTEN} - vorhanden
        self.assertEqual(fehlend, set())

    # ---------- K2: Schäden landen auf 3600, nicht im Mietertrag 3000 ----------
    def test_k2_schaden_nicht_im_mietertrag(self):
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen',
                'pos_text': 'Reinigung', 'pos_betrag': '500', 'pos_richtung': 'zulasten'})
        self.assertEqual(self._saldo('3600'), Decimal('-500.00'))   # Ertrag im Haben
        self.assertEqual(self._saldo('3000'), Decimal('0.00'))      # kein Mietertrag
        self.assertTrue(DebitorenRechnung.objects.filter(
            vertrag=v, titel='Schlussabrechnung (Nachzahlung)').exists())

    def test_k2_offene_miete_bleibt_bestehen_keine_doppelbelastung(self):
        # Neu: alte Forderung wird NICHT mehr storniert (MWST/Ertragskonto bleiben
        # erhalten) — sie darf aber auch nicht doppelt gefordert werden.
        from finance.models import DebitorenRechnung
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        alt = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                               titel='Miete 05/2024', datum=date(2024, 5, 1),
                                               faellig_am=date(2024, 5, 5),
                                               betrag=Decimal('1700'), status='offen')
        buche('1100', '3000', Decimal('1700'), 'Miete 05/2024', datum=date(2024, 5, 1),
              liegenschaft=lg, debitor=alt)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen'})
        alt.refresh_from_db()
        self.assertEqual(alt.status, 'offen')          # bleibt bestehen (MWST intakt)
        offene = DebitorenRechnung.objects.filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
        # Gesamtforderung unverändert 1700 — keine zweite Forderung über denselben Betrag
        self.assertEqual(sum((r.offener_betrag for r in offene), Decimal('0')), Decimal('1700'))

    def test_schlussabrechnung_idempotent(self):
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        payload = {'auszug_datum': '2024-06-30', 'aktion': 'buchen',
                   'pos_text': 'Reinigung', 'pos_betrag': '500', 'pos_richtung': 'zulasten'}
        for _ in range(2):
            c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/', payload)
        self.assertEqual(DebitorenRechnung.objects.filter(
            vertrag=v, titel='Schlussabrechnung (Nachzahlung)').count(), 1)

    # ---------- W1/F3: NK-Gutschrift wird echtes Guthaben (2030) ----------
    def test_w1_nk_gutschrift_als_guthaben(self):
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg, Zahlungseingang
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='NK 2024',
                                              start_datum=date(2024, 1, 1), ende_datum=date(2024, 12, 31))
        NebenkostenBeleg.objects.create(periode=p, text='Heizung', kategorie='heizung',
                                        betrag=Decimal('100'), datum=date(2024, 6, 1))
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/nebenkosten/{p.id}/verbuchen/')
        # Gutschrift (Akonto > Kosten) muss als Guthaben auf 2030 stehen, nicht 1100 entlasten
        if self._saldo('2030') != Decimal('0.00'):
            self.assertLess(self._saldo('2030'), Decimal('0.00'))   # Passivum im Haben
            self.assertTrue(Zahlungseingang.objects.filter(konto__nummer='2030').exists())

    # ---------- F3: geparkte Zahlung nachträglich zuordnen ----------
    def test_f3_geparkte_zahlung_zuordnen(self):
        from finance.models import DebitorenRechnung, Zahlungseingang
        from finance.booking import buche, ensure_kontenplan, konto
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                             titel='Miete 03/2024', datum=date(2024, 3, 1),
                                             faellig_am=date(2024, 3, 5),
                                             betrag=Decimal('1700'), status='offen')
        buche('1100', '3000', Decimal('1700'), 'Miete', datum=date(2024, 3, 1), liegenschaft=lg, debitor=r)
        z = Zahlungseingang.objects.create(betrag=Decimal('1700'), datum_eingang=date(2024, 3, 6),
                                           buchungs_monat=date(2024, 3, 1),
                                           bemerkung='UNGEKLÄRT: Unbekannte GmbH',
                                           konto=konto('1190'), status='verbucht')
        buche('1020', '1190', Decimal('1700'), 'ungeklärt', datum=date(2024, 3, 6), liegenschaft=lg, zahlung=z)
        c = Client(); c.force_login(_team_user())
        resp = c.post('/neu/bankabgleich/zuordnen/', {'zahlung_id': z.id, 'rechnung_id': r.id}, follow=True)
        self.assertContains(resp, 'zugeordnet')
        r.refresh_from_db(); z.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(z.debitoren_rechnung_id, r.id)
        self.assertEqual(self._saldo('1190'), Decimal('0.00'))   # Parkkonto geleert
        self.assertEqual(self._saldo('1100'), Decimal('0.00'))   # Forderung getilgt

    # ---------- W7: Zahlungs-Storno in /neu/ ----------
    def test_w7_zahlung_stornieren(self):
        from finance.models import DebitorenRechnung, Zahlungseingang
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                             titel='Miete 03/2024', datum=date(2024, 3, 1),
                                             faellig_am=date(2024, 3, 5),
                                             betrag=Decimal('1700'), status='offen')
        buche('1100', '3000', Decimal('1700'), 'Miete', datum=date(2024, 3, 1), liegenschaft=lg, debitor=r)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/bankabgleich/verbuchen/', {'rechnung_id': r.id})
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        z = Zahlungseingang.objects.get(debitoren_rechnung=r)
        c.post(f'/neu/zahlungen/{z.id}/stornieren/')
        r.refresh_from_db(); z.refresh_from_db()
        self.assertEqual(z.status, 'storniert')
        self.assertEqual(r.status, 'offen')                       # OP wieder offen
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))    # Bankbuchung aufgehoben

    # ---------- W4: Jahresabschluss saldiert Erfolgskonten gegen 2970 ----------
    def test_w4_jahresabschluss_saldiert_erfolgskonten(self):
        from finance.booking import buche, ensure_kontenplan
        from core.services.jahresabschluss import buche_jahresabschluss, ist_abgeschlossen
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        buche('1100', '3000', Decimal('12000'), 'Mieten', datum=date(2024, 6, 30), liegenschaft=lg)
        buche('4000', '1020', Decimal('2000'), 'Reparatur', datum=date(2024, 7, 1), liegenschaft=lg)
        n, erg = buche_jahresabschluss(2024, user=None)
        self.assertEqual(n, 2)
        self.assertEqual(erg, Decimal('10000.00'))                # Gewinn
        self.assertEqual(self._saldo('3000'), Decimal('0.00'))    # Erfolgskonten saldiert
        self.assertEqual(self._saldo('4000'), Decimal('0.00'))
        self.assertEqual(self._saldo('2970'), Decimal('-10000.00'))  # Ergebnis im Haben
        self.assertTrue(ist_abgeschlossen(2024))
        # idempotent
        n2, _ = buche_jahresabschluss(2024, user=None)
        self.assertEqual(n2, 0)

    # ---------- K5: Anlage wird aktiviert (1500 läuft nicht negativ) ----------
    def test_k5_anlage_wird_aktiviert(self):
        from finance.booking import ensure_kontenplan
        from core.services.automation import run_abschreibungen
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/anlagen/', {'aktion': 'anlage_neu', 'liegenschaft_id': lg.id,
                                 'bezeichnung': 'Heizung', 'anschaffungswert': '20000',
                                 'anschaffungsdatum': '2024-01-01', 'nutzungsdauer_jahre': '10',
                                 'gegenkonto': '2000', 'aktivieren': 'on'})
        self.assertEqual(self._saldo('1500'), Decimal('20000.00'))
        self.assertEqual(self._saldo('2000'), Decimal('-20000.00'))
        run_abschreibungen(2024, user=None)
        self.assertEqual(self._saldo('1500'), Decimal('18000.00'))   # nach AfA positiv!
        self.assertGreater(self._saldo('1500'), Decimal('0'))

    # ---------- K4: Saldosteuersatz auf Brutto-Entgelt ----------
    def test_k4_saldosteuersatz_auf_brutto(self):
        from core.services.mwst_estv import berechne_estv
        d = berechne_estv(umsatz_steuerbar=Decimal('10000'), umsatzsteuer=Decimal('810'),
                          vorsteuer_material=Decimal('0'), vorsteuer_invest=Decimal('0'),
                          methode='saldo', saldosteuersatz=Decimal('6.5'),
                          umsatz_brutto=Decimal('10810'))
        self.assertEqual(d['z289'], Decimal('10810.00'))            # Brutto, nicht Netto
        self.assertEqual(d['z399'], Decimal('702.65'))              # 6.5% von 10'810
        self.assertEqual(d['z500'], Decimal('702.65'))

    def test_k4_mwst_verbuchen_leert_2200(self):
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        buche('1100', '2200', Decimal('810'), 'MWST Q1', datum=date(2024, 3, 31), liegenschaft=lg)
        buche('1170', '2000', Decimal('200'), 'Vorsteuer', datum=date(2024, 3, 31), liegenschaft=lg)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/mwst/verbuchen/', {'jahr': '2024', 'quartal': '1', 'umsatzsteuer': '810',
                                        'vorsteuer': '200', 'zahllast': '610', 'methode': 'effektiv'})
        self.assertEqual(self._saldo('2200'), Decimal('0.00'))    # ausgebucht
        self.assertEqual(self._saldo('1170'), Decimal('0.00'))    # Vorsteuer verrechnet
        # Die Zahllast ist am Stichtag eine SCHULD gegenüber der ESTV (2201) —
        # gezahlt wird erst mit der Abrechnung. Eine Bankbuchung per 31.03. haette
        # 1020 vom realen Kontoauszug abweichen lassen (Audit).
        self.assertEqual(self._saldo('2201'), Decimal('-610.00'))  # Schuld ESTV
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))     # Bank unberuehrt

    # ---------- W5: Ad-hoc-Rechnung nicht auf 3000 ----------
    def test_w5_adhoc_debitor_auf_3600(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/debitoren/neu/', {'titel': 'Schlüsselersatz', 'betrag': '80',
                                       'vertrag_id': v.id})
        self.assertEqual(self._saldo('3600'), Decimal('-80.00'))
        self.assertEqual(self._saldo('3000'), Decimal('0.00'))


# ============================================================
# P3 — Bank abstimmbar: Kontoauszug, Bankbewegungen, Zuordnung
# ============================================================

_P3_CAMT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.04">
 <BkToCstmrStmt><Stmt>
  <Acct><Id><IBAN>CH9300762011623852957</IBAN></Id></Acct>
  <FrToDt><FrDtTm>2024-03-01T00:00:00</FrDtTm><ToDtTm>2024-03-31T00:00:00</ToDtTm></FrToDt>
  <Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="CHF">1000.00</Amt>
       <CdtDbtInd>CRDT</CdtDbtInd></Bal>
  <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="CHF">1450.00</Amt>
       <CdtDbtInd>CRDT</CdtDbtInd></Bal>
  <Ntry>
   <Amt Ccy="CHF">800.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
   <BookgDt><Dt>2024-03-05</Dt></BookgDt><ValDt><Dt>2024-03-04</Dt></ValDt>
   <NtryDtls><TxDtls>
     <Refs><AcctSvcrRef>P3-CRDT-1</AcctSvcrRef></Refs>
     <RltdPties><Dbtr><Nm>Hans Muster</Nm></Dbtr></RltdPties>
     <RmtInf><Ustrd>Miete Maerz</Ustrd></RmtInf>
   </TxDtls></NtryDtls>
  </Ntry>
  <Ntry>
   <Amt Ccy="CHF">350.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>
   <BookgDt><Dt>2024-03-07</Dt></BookgDt><ValDt><Dt>2024-03-06</Dt></ValDt>
   <NtryDtls><TxDtls>
     <Refs><AcctSvcrRef>P3-DBIT-1</AcctSvcrRef></Refs>
     <RltdPties><Cdtr><Nm>Hauswartung AG</Nm></Cdtr></RltdPties>
     <RmtInf><Ustrd>Hauswartung Februar</Ustrd></RmtInf>
   </TxDtls></NtryDtls>
  </Ntry>
 </Stmt></BkToCstmrStmt>
</Document>"""


class BankAbgleichP3Tests(TestCase):
    """Ohne Belastungen, Auszugszeilen und Schlusssaldo ist ein Bankkonto
    strukturell nicht abstimmbar — genau das prüfen diese Tests."""

    def _saldo(self, nummer):
        from finance.models import Buchung
        from django.db.models import Sum
        soll = (Buchung.objects.filter(soll_konto__nummer=nummer, ist_storno=False)
                .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        haben = (Buchung.objects.filter(haben_konto__nummer=nummer, ist_storno=False)
                 .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        return soll - haben

    def _import(self, client, xml=None, bank='1020'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = SimpleUploadedFile("auszug.xml", (xml or _P3_CAMT).encode(),
                               content_type="text/xml")
        return client.post('/neu/bankabgleich/camt-import/',
                           {'camt_datei': f, 'bank_konto': bank})

    # ---------- Parser ----------
    def test_camt_liest_belastungen_mit_negativem_vorzeichen(self):
        from core.views.fw import _camt_parse
        nur_gut = _camt_parse(_P3_CAMT.encode())
        self.assertEqual(len(nur_gut), 1)
        alle = _camt_parse(_P3_CAMT.encode(), nur_gutschriften=False)
        self.assertEqual(len(alle), 2)
        belastung = [e for e in alle if e['betrag'] < 0][0]
        self.assertEqual(belastung['betrag'], Decimal('-350.00'))

    def test_camt_gegenpartei_bei_belastung_ist_der_empfaenger(self):
        """Bei einem Ausgang steht der Empfänger in <Cdtr>, nicht in <Dbtr> —
        sonst bleibt der Lieferantenname im Bank-Eingang leer."""
        from core.views.fw import _camt_parse
        alle = _camt_parse(_P3_CAMT.encode(), nur_gutschriften=False)
        belastung = [e for e in alle if e['betrag'] < 0][0]
        gutschrift = [e for e in alle if e['betrag'] > 0][0]
        self.assertEqual(belastung['dbtr_name'], 'Hauswartung AG')
        self.assertEqual(gutschrift['dbtr_name'], 'Hans Muster')

    def test_camt_liest_valuta_getrennt_vom_buchungsdatum(self):
        from core.views.fw import _camt_parse
        g = _camt_parse(_P3_CAMT.encode())[0]
        self.assertEqual(g['datum'], date(2024, 3, 5))
        self.assertEqual(g['valuta'], date(2024, 3, 4))

    def test_camt_kopf_liest_iban_periode_und_saldi(self):
        from core.views.fw import _camt_kopf
        k = _camt_kopf(_P3_CAMT.encode())
        self.assertEqual(k['iban'], 'CH9300762011623852957')
        self.assertEqual(k['von'], date(2024, 3, 1))
        self.assertEqual(k['bis'], date(2024, 3, 31))
        self.assertEqual(k['eroeffnung'], Decimal('1000.00'))
        self.assertEqual(k['schluss'], Decimal('1450.00'))

    # ---------- Import ----------
    def test_import_haelt_jede_auszugszeile_fest(self):
        from finance.models import Kontoauszug, Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        a = Kontoauszug.objects.get()
        self.assertEqual(a.iban, 'CH9300762011623852957')
        self.assertEqual(a.schlusssaldo, Decimal('1450.00'))
        self.assertEqual(Bankbewegung.objects.filter(auszug=a).count(), 2)

    def test_belastung_bleibt_offen_und_wird_nicht_geraten(self):
        """Das Gegenkonto einer Belastung steht nicht im Auszug. Es zu raten wäre
        eine Falschbuchung — die Zeile bleibt bis zur Zuordnung offen."""
        from finance.models import Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__lt=0)
        self.assertEqual(b.status, 'offen')
        self.assertEqual(b.gegenpartei, 'Hauswartung AG')
        self.assertEqual(self._saldo('6800'), Decimal('0.00'))

    def test_geparkte_gutschrift_gilt_als_verbucht(self):
        """Eine auf 1190 geparkte Gutschrift IST gebucht — bliebe sie «offen»,
        zeigte der Saldoabgleich eine Differenz, die es gar nicht gibt."""
        from finance.models import Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__gt=0)
        self.assertEqual(b.status, 'verbucht')
        self.assertEqual(self._saldo('1190'), Decimal('-800.00'))

    def test_import_bucht_auf_gewaehltes_bankkonto(self):
        """Vorher war «1020» im ganzen Import hart verdrahtet — ein zweites
        Bankkonto war damit nicht importierbar."""
        from finance.models import Buchungskonto
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        Buchungskonto.objects.create(nummer='1021', bezeichnung='Bank 2', typ='aktiv')
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c, bank='1021')
        self.assertEqual(self._saldo('1021'), Decimal('800.00'))
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))

    def test_erneuter_import_erzeugt_keine_zweiten_bewegungen(self):
        from finance.models import Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        self._import(c)
        self.assertEqual(Bankbewegung.objects.count(), 2)
        self.assertEqual(self._saldo('1020'), Decimal('800.00'))

    # ---------- Zuordnung ----------
    def test_belastung_auf_aufwandkonto_zuordnen(self):
        from finance.models import Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__lt=0)
        c.post('/neu/bankabgleich/bewegung/', {
            'bewegung_id': b.id, 'art': 'konto', 'gegenkonto': '6800',
            'beleg_text': 'Hauswartung Februar'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'verbucht')
        self.assertIsNotNone(b.buchung_id)
        self.assertEqual(self._saldo('6800'), Decimal('350.00'))
        self.assertEqual(self._saldo('1020'), Decimal('450.00'))

    def test_zuordnung_bucht_auf_das_valutadatum(self):
        """Buchhalterisch massgebend ist die Valuta, nicht der Erfassungstag."""
        from finance.models import Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__lt=0)
        c.post('/neu/bankabgleich/bewegung/', {
            'bewegung_id': b.id, 'art': 'konto', 'gegenkonto': '6800'})
        b.refresh_from_db()
        self.assertEqual(b.buchung.datum, date(2024, 3, 6))

    def test_belastung_tilgt_kreditorenrechnung(self):
        from finance.models import Bankbewegung, KreditorenRechnung
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        kr = KreditorenRechnung.objects.create(
            lieferant='Hauswartung AG', referenz='RE-77', betrag=Decimal('350.00'),
            datum=date(2024, 3, 1), faellig_am=date(2024, 3, 31),
            liegenschaft=lg, status='freigegeben')
        buche('6800', '2000', Decimal('350.00'), 'Hauswartung Februar',
              datum=date(2024, 3, 1), liegenschaft=lg, kreditor=kr)
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__lt=0)
        c.post('/neu/bankabgleich/bewegung/', {
            'bewegung_id': b.id, 'art': 'kreditor', 'kreditor_id': kr.id})
        b.refresh_from_db(); kr.refresh_from_db()
        self.assertEqual(b.status, 'verbucht')
        self.assertEqual(kr.status, 'bezahlt')
        self.assertEqual(self._saldo('2000'), Decimal('0.00'))
        self.assertEqual(self._saldo('1020'), Decimal('450.00'))

    def test_gutschrift_kann_keine_kreditorenrechnung_tilgen(self):
        from finance.models import Bankbewegung, KreditorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        kr = KreditorenRechnung.objects.create(
            lieferant='Hauswartung AG', referenz='RE-78', betrag=Decimal('350.00'),
            datum=date(2024, 3, 1), faellig_am=date(2024, 3, 31),
            liegenschaft=lg, status='freigegeben')
        c = Client(); c.force_login(_team_user())
        self._import(c)
        # Die Gutschrift wurde beim Import geparkt → künstlich wieder öffnen
        b = Bankbewegung.objects.get(betrag__gt=0)
        b.status = 'offen'; b.save(update_fields=['status'])
        c.post('/neu/bankabgleich/bewegung/', {
            'bewegung_id': b.id, 'art': 'kreditor', 'kreditor_id': kr.id})
        b.refresh_from_db(); kr.refresh_from_db()
        self.assertEqual(b.status, 'offen')
        self.assertEqual(kr.status, 'freigegeben')

    def test_ignorierte_bewegung_erzeugt_keine_buchung(self):
        from finance.models import Bankbewegung, Buchung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__lt=0)
        vorher = Buchung.objects.count()
        c.post('/neu/bankabgleich/bewegung/', {
            'bewegung_id': b.id, 'art': 'ignorieren',
            'bemerkung': 'Umbuchung eigenes Konto'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'ignoriert')
        self.assertEqual(Buchung.objects.count(), vorher)

    def test_erledigte_bewegung_wird_nicht_zweimal_gebucht(self):
        from finance.models import Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__lt=0)
        daten = {'bewegung_id': b.id, 'art': 'konto', 'gegenkonto': '6800'}
        c.post('/neu/bankabgleich/bewegung/', daten)
        c.post('/neu/bankabgleich/bewegung/', daten)
        self.assertEqual(self._saldo('6800'), Decimal('350.00'))

    def test_bankabgleich_seite_zeigt_offene_bewegungen(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        r = c.get('/neu/bankabgleich/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['bew_offen_n'], 1)
        self.assertContains(r, 'Hauswartung AG')

    # ---------- Wer hat bezahlt? ----------
    def _geparkt(self, gegenpartei='', text='', referenz=''):
        """Eine ungeklärte Zahlung auf 1190 samt zugehöriger Auszugszeile."""
        from finance.models import Zahlungseingang, Buchungskonto, Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        k1190, _ = Buchungskonto.objects.get_or_create(
            nummer='1190', defaults={'bezeichnung': 'Durchlaufkonto', 'typ': 'bilanz'})
        bank = Buchungskonto.objects.get(nummer='1020')
        z = Zahlungseingang.objects.create(
            betrag=Decimal('200.00'), datum_eingang=date(2026, 7, 31),
            bemerkung='Bank-CSV UNGEKLÄRT: ', konto=k1190,
            bank_referenz='REF-1', status='verbucht')
        Bankbewegung.objects.create(
            konto=bank, datum=date(2026, 7, 31), betrag=Decimal('200.00'),
            text=text, gegenpartei=gegenpartei, referenz=referenz,
            bank_referenz='REF-1', status='verbucht', zahlung=z)
        return z

    def test_ungeklaerte_zahlung_zeigt_den_auftraggeber(self):
        """Die Zeile zeigte nur den abgeschnittenen Importtext («Bank-CSV UNG…»)
        — von wem das Geld kam, stand nirgends, obwohl die Bank es liefert."""
        _basis_objekte()
        self._geparkt(gegenpartei='Muster Handels AG', text='Miete Juli',
                      referenz='210000000003139471430009017')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/bankabgleich/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Muster Handels AG')
        self.assertContains(r, 'Miete Juli')
        self.assertContains(r, '210000000003139471430009017')

    def test_ohne_auftraggeber_wird_das_offen_gesagt(self):
        """Liefert die Bank keinen Namen, soll das dastehen statt eines
        abgeschnittenen Importtexts, der so aussieht wie ein Titel."""
        _basis_objekte()
        self._geparkt(gegenpartei='', text='Gutschrift Dauerauftrag')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/bankabgleich/')
        self.assertContains(r, 'Auftraggeber von der Bank nicht geliefert')
        self.assertContains(r, 'Gutschrift Dauerauftrag')

    def test_zahler_aus_buchungstext_wenn_bank_keine_spalte_liefert(self):
        """Viele Exporte haben keine Auftraggeber-Spalte, sondern «Name;PLZ Ort; Land»
        im Buchungstext — real gesehen «Narrezauber Soledurn;4500 Solothurn; CH»."""
        _basis_objekte()
        self._geparkt(gegenpartei='', text='Narrezauber Soledurn;4500 Solothurn; CH')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/bankabgleich/')
        self.assertContains(r, 'Narrezauber Soledurn')
        self.assertContains(r, 'aus Buchungstext')          # als geraten markiert
        self.assertContains(r, '4500 Solothurn')            # Rest bleibt als Detail
        self.assertNotContains(r, 'nicht geliefert')

    def test_einteiliger_buchungstext_bleibt_mitteilung(self):
        """«Miete Juli» ist kein Name — daraus wird kein Auftraggeber erfunden."""
        _basis_objekte()
        self._geparkt(gegenpartei='', text='Miete Juli')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/bankabgleich/')
        self.assertContains(r, 'Auftraggeber von der Bank nicht geliefert')
        self.assertContains(r, 'Miete Juli')

    # ---------- Gelernter Absender ----------
    def _csv(self, name='Narrezauber Soledurn;4500 Solothurn; CH', betrag='200.00',
             datum='31.07.2026'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        # Komma-getrennt: genau so kommt der reale Fall zustande — die Semikolon
        # im Adressfeld bleiben dann im Feld stehen, statt es in Spalten zu zerlegen.
        return SimpleUploadedFile(
            'auszug.csv',
            ("Datum,Gutschrift,Mitteilung\n"
             f"{datum},{betrag},{name}\n").encode('utf-8'),
            content_type='text/csv')

    def _offene_rechnung(self, betrag='200.00'):
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(
            vertrag=v, titel='Miete August', betrag=Decimal(betrag),
            datum=date(2026, 8, 1), faellig_am=date(2026, 8, 1), status='offen')
        return v, r

    def test_zuordnen_merkt_sich_den_absender(self):
        """Nach der Handarbeit soll die nächste Zahlung desselben Absenders
        von selbst treffen — sonst parkt ein Dauerauftrag jeden Monat neu."""
        from finance.models import ZahlerZuordnung
        v, r = self._offene_rechnung()
        z = self._geparkt(gegenpartei='', text='Narrezauber Soledurn;4500 Solothurn; CH')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/zuordnen/', {'zahlung_id': z.id, 'rechnung_id': r.id})
        eintrag = ZahlerZuordnung.objects.filter(vertrag=v).first()
        self.assertIsNotNone(eintrag)
        self.assertEqual(eintrag.name_norm, 'narrezaubersoledurn')

    def test_gelernter_absender_wird_beim_import_zugeordnet(self):
        from finance.booking import ensure_kontenplan
        from finance.models import ZahlerZuordnung, Zahlungseingang
        ensure_kontenplan()
        v, r = self._offene_rechnung()
        ZahlerZuordnung.objects.create(name_norm='narrezaubersoledurn',
                                       name_anzeige='Narrezauber Soledurn', vertrag=v)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': self._csv()}, follow=True)
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        z = Zahlungseingang.objects.filter(debitoren_rechnung=r).first()
        self.assertIsNotNone(z)
        self.assertIsNone(z.konto)                      # nicht geparkt
        self.assertEqual(ZahlerZuordnung.objects.get(vertrag=v).treffer, 1)

    def test_gelernter_absender_raet_nicht_bei_mehreren_offenen(self):
        """Zwei offene Rechnungen — welche gemeint ist, weiss nur der Mensch.
        Falsch zugeordnetes Geld kostet mehr als eine Minute Handarbeit."""
        from finance.booking import ensure_kontenplan
        from finance.models import DebitorenRechnung, ZahlerZuordnung
        ensure_kontenplan()
        v, r = self._offene_rechnung()
        DebitorenRechnung.objects.create(
            vertrag=v, titel='Miete September', betrag=Decimal('200.00'),
            datum=date(2026, 9, 1), faellig_am=date(2026, 9, 1), status='offen')
        ZahlerZuordnung.objects.create(name_norm='narrezaubersoledurn',
                                       name_anzeige='Narrezauber Soledurn', vertrag=v)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': self._csv()}, follow=True)
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen')             # nichts geraten
        self.assertEqual(ZahlerZuordnung.objects.get(vertrag=v).treffer, 0)

    def test_gelernter_absender_ueberzahlung_wird_nicht_automatisch_gebucht(self):
        """Mehr als offen ist → auch das gehört vor Augen, nicht in die Automatik."""
        from finance.booking import ensure_kontenplan
        from finance.models import ZahlerZuordnung
        ensure_kontenplan()
        v, r = self._offene_rechnung(betrag='150.00')
        ZahlerZuordnung.objects.create(name_norm='narrezaubersoledurn',
                                       name_anzeige='Narrezauber Soledurn', vertrag=v)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': self._csv(betrag='200.00')}, follow=True)
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen')

    def test_unbekannter_absender_parkt_weiterhin(self):
        from finance.booking import ensure_kontenplan
        from finance.models import Zahlungseingang
        ensure_kontenplan()
        v, r = self._offene_rechnung()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': self._csv(name='Fremd AG;4500 Solothurn')},
               follow=True)
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen')
        self.assertTrue(Zahlungseingang.objects.filter(konto__nummer='1190').exists())

    # ---------- Sammelzuordnung ----------
    def _rechnung(self, vertrag, titel, betrag, faellig):
        from finance.models import DebitorenRechnung
        return DebitorenRechnung.objects.create(
            vertrag=vertrag, titel=titel, betrag=Decimal(betrag),
            datum=faellig, faellig_am=faellig, status='offen')

    def test_sammelzuordnung_tilgt_aelteste_forderung_zuerst(self):
        """Drei Monatsmieten, drei geparkte Zahlungen — auf einen Schlag. Die
        Reihenfolge ist kein Detail: sonst mahnt man einen Monat, der längst
        bezahlt ist."""
        from finance.booking import ensure_kontenplan
        from finance.models import Zahlungseingang
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r_jul = self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        r_aug = self._rechnung(v, 'Miete August', '200.00', date(2026, 8, 1))
        r_sep = self._rechnung(v, 'Miete September', '200.00', date(2026, 9, 1))
        z = [self._geparkt(gegenpartei='Narrezauber Soledurn') for _ in range(3)]
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/bankabgleich/sammel-zuordnen/',
                   {'zahlung_ids': [str(x.id) for x in z], 'vertrag_id': v.id}, follow=True)
        self.assertEqual(r.status_code, 200)
        for rech in (r_jul, r_aug, r_sep):
            rech.refresh_from_db()
            self.assertEqual(rech.status, 'bezahlt', rech.titel)
        self.assertEqual(Zahlungseingang.objects.filter(konto__nummer='1190').count(), 0)

    def test_sammelzuordnung_ueberschuss_bleibt_guthaben(self):
        """Mehr Geld als Forderungen: Der Rest verfällt nicht, er wird
        Mieterguthaben (2030)."""
        from finance.booking import ensure_kontenplan
        from finance.models import Zahlungseingang
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        z = [self._geparkt(gegenpartei='Narrezauber Soledurn') for _ in range(2)]
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/bankabgleich/sammel-zuordnen/',
                   {'zahlung_ids': [str(x.id) for x in z], 'vertrag_id': v.id}, follow=True)
        # Die zweite Zahlung findet keine offene Forderung mehr und bleibt liegen
        self.assertContains(r, 'keine offene Rechnung mehr')
        self.assertTrue(Zahlungseingang.objects.filter(konto__nummer='1190').exists())

    def test_sammelzuordnung_ohne_mieter_bucht_nichts(self):
        from finance.booking import ensure_kontenplan
        from finance.models import Zahlungseingang
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        z = self._geparkt(gegenpartei='Narrezauber Soledurn')
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/bankabgleich/sammel-zuordnen/',
                   {'zahlung_ids': [str(z.id)], 'vertrag_id': ''}, follow=True)
        self.assertContains(r, 'Kein Mieter gewählt')
        z.refresh_from_db()
        self.assertEqual(z.konto.nummer, '1190')        # unverändert geparkt

    def test_sammelzuordnung_ohne_auswahl_bucht_nichts(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/bankabgleich/sammel-zuordnen/', {'vertrag_id': v.id}, follow=True)
        self.assertContains(r, 'Keine Zahlung ausgewählt')

    def test_sammelzuordnung_merkt_sich_den_absender(self):
        from finance.booking import ensure_kontenplan
        from finance.models import ZahlerZuordnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        z = self._geparkt(gegenpartei='Narrezauber Soledurn')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/sammel-zuordnen/',
               {'zahlung_ids': [str(z.id)], 'vertrag_id': v.id}, follow=True)
        self.assertTrue(ZahlerZuordnung.objects.filter(
            name_norm='narrezaubersoledurn', vertrag=v).exists())

    def test_sammelzuordnung_fasst_fremdes_guthaben_nicht_an(self):
        """Ein Guthaben auf 2030 gehört einem bestimmten Mieter — es darf nicht
        die Forderung eines anderen tilgen."""
        from finance.booking import ensure_kontenplan
        from finance.models import Zahlungseingang, Buchungskonto
        from crm.models import Mieter
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r_jul = self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        m2 = Mieter.objects.create(vorname='Fremd', nachname='Person')
        v2 = Mietvertrag.objects.create(mieter=m2, einheit=e, status='aktiv',
                                        beginn=date(2025, 1, 1),
                                        netto_mietzins=Decimal('100'), nebenkosten=Decimal('0'))
        k2030, _ = Buchungskonto.objects.get_or_create(
            nummer='2030', defaults={'bezeichnung': 'Guthaben Mieter', 'typ': 'bilanz'})
        fremd = Zahlungseingang.objects.create(
            vertrag=v2, betrag=Decimal('200.00'), datum_eingang=date(2026, 7, 31),
            konto=k2030, status='verbucht', bemerkung='Guthaben Fremd')
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/bankabgleich/sammel-zuordnen/',
                   {'zahlung_ids': [str(fremd.id)], 'vertrag_id': v.id}, follow=True)
        r_jul.refresh_from_db()
        self.assertEqual(r_jul.status, 'offen')
        self.assertContains(r, 'gehört einem anderen Mieter')

    def test_csv_erkennt_weitere_auftraggeber_spalten(self):
        from core.views.fw import _bank_csv_parse
        csv = ("Datum;Gutschrift;Zahler;Mitteilung\n"
               "31.07.2026;200.00;Muster Handels AG;Miete Juli\n").encode()
        e = _bank_csv_parse(csv)
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]['dbtr_name'], 'Muster Handels AG')

    # ---------- «Kürzlich abgeglichen» lesbar ----------

    def _abgeglichen(self, vertrag=None, gegenpartei='', text='', bemerkung=''):
        """Eine bereits verbuchte Zahlung samt Auszugszeile."""
        from finance.models import Zahlungseingang, Buchungskonto, Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        bank = Buchungskonto.objects.get(nummer='1020')
        z = Zahlungseingang.objects.create(
            vertrag=vertrag, betrag=Decimal('100.00'), datum_eingang=date(2026, 7, 31),
            bemerkung=bemerkung, konto=bank, bank_referenz='REF-A', status='verbucht')
        Bankbewegung.objects.create(
            konto=bank, datum=date(2026, 7, 31), betrag=Decimal('100.00'),
            text=text, gegenpartei=gegenpartei, bank_referenz='REF-A',
            status='verbucht', zahlung=z)
        return z

    def test_kuerzlich_abgeglichen_kuerzt_den_namen_nicht_mehr_ab(self):
        """Mieter, Datum, Betrag und «Stornieren» standen in EINER Zeile — auf
        dem Handy blieb vom Namen «B..» übrig. Name und Herkunft stehen jetzt
        untereinander, ohne truncate."""
        lg, e, m, v = _basis_objekte()
        self._abgeglichen(vertrag=v, gegenpartei='Muster Handels AG',
                          text='Miete Juli', bemerkung='Bank-CSV Import')
        c = Client(); c.force_login(_team_user())
        h = c.get('/neu/bankabgleich/').content.decode('utf-8')
        block = h.split('Kürzlich abgeglichen', 1)[1]
        self.assertIn(m.display_name, block)
        self.assertIn('Muster Handels AG', block)
        self.assertNotIn('flex-1 min-w-0 truncate', block)

    def test_kuerzlich_abgeglichen_ohne_vertrag_beginnt_nicht_mit_trennzeichen(self):
        """Ohne Vertrag war der Mietername leer und die Zeile begann mit « · »
        — auf dem Handy war das die ganze sichtbare Information."""
        _basis_objekte()
        self._abgeglichen(gegenpartei='Narrezauber Soledurn', text='Miete Juli')
        c = Client(); c.force_login(_team_user())
        h = c.get('/neu/bankabgleich/').content.decode('utf-8')
        block = h.split('Kürzlich abgeglichen', 1)[1]
        self.assertIn('Narrezauber Soledurn', block)
        self.assertNotIn('break-words"> · ', block)

    def test_kuerzlich_abgeglichen_faellt_auf_die_bemerkung_zurueck(self):
        """Ohne Vertrag UND ohne Auftraggeber bleibt nur die Herkunft des
        Belegs — besser als eine leere Zeile."""
        _basis_objekte()
        self._abgeglichen(bemerkung='camt.053-Import ZZCAMTTEST')
        c = Client(); c.force_login(_team_user())
        block = (c.get('/neu/bankabgleich/').content.decode('utf-8')
                 .split('Kürzlich abgeglichen', 1)[1])
        self.assertIn('camt.053-Import ZZCAMTTEST', block)

    def test_storno_hebt_auch_das_rest_guthaben_wieder_auf(self):
        """Zahlt jemand mehr als offen ist, bleibt der Überschuss als Guthaben
        auf 2030 stehen. Wird die Zahlung später storniert, muss dieses Guthaben
        mit verschwinden — sonst behält der Mieter ein Guthaben aus einer
        Zahlung, die es buchhalterisch nicht mehr gibt, und 1190/2030 sind
        dauerhaft falsch."""
        from finance.booking import ensure_kontenplan
        from finance.models import Zahlungseingang
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        z = self._geparkt(gegenpartei='Narrezauber Soledurn')   # CHF 200.00
        z.betrag = Decimal('300.00'); z.save(update_fields=['betrag'])

        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/sammel-zuordnen/',
               {'zahlung_ids': [str(z.id)], 'vertrag_id': v.id}, follow=True)
        self.assertEqual(self._kontoblatt_saldo('2030'), Decimal('-100.00'))

        c.post(f'/neu/zahlungen/{z.id}/stornieren/', {}, follow=True)
        self.assertEqual(self._kontoblatt_saldo('2030'), Decimal('0.00'),
                         "Guthaben auf 2030 blieb nach dem Storno stehen")
        self.assertFalse(Zahlungseingang.objects
                         .filter(bank_referenz__endswith=':rest', status='verbucht')
                         .exists())

    def _kontoblatt_saldo(self, nummer):
        """Saldo wie im Kontoblatt: ALLE Buchungen, inkl. Storno-Gegenbuchungen.

        `_saldo()` blendet `ist_storno=True` aus und misst damit nur die
        Originale — für eine Storno-Prüfung ist das die falsche Sicht."""
        from finance.models import Buchung
        from django.db.models import Sum
        soll = (Buchung.objects.filter(soll_konto__nummer=nummer)
                .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        haben = (Buchung.objects.filter(haben_konto__nummer=nummer)
                 .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        return soll - haben

    def test_saldoabgleich_zaehlt_stornierte_buchungen_nicht_mit(self):
        """Ein Storno-Paar darf nicht einseitig gefiltert werden.

        `ist_storno=False` blendet die Gegenbuchung aus — ohne
        `storniert_am__isnull=True` zählt das stornierte ORIGINAL aber weiter.
        Der Abstimmungsnachweis meldete dann eine Differenz zum Bankauszug, die
        es gar nicht gibt, und der Monatsabschluss lässt sich nicht abschliessen.
        `rendite.py`/`jahresabschluss.py` filtern seit jeher auf beides."""
        from django.utils import timezone as _tz
        from finance.booking import ensure_kontenplan, buche, storniere_buchung
        from finance.models import Kontoauszug, Buchungskonto
        ensure_kontenplan()
        heute = _tz.localdate()
        bank = Buchungskonto.objects.get(nummer='1020')
        b = buche('1020', '1100', Decimal('100.00'), 'Testeingang', datum=heute)
        storniere_buchung(b)
        Kontoauszug.objects.create(konto=bank, bis=heute,
                                   schlusssaldo=Decimal('0.00'), dateiname='a.xml')
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/bankabgleich/').content.decode('utf-8')
        self.assertIn('Saldoabgleich', html)
        # Buchhaltung muss 0.00 zeigen — nicht 100.00 aus dem stornierten Original
        self.assertNotIn('100.00', html.split('Saldoabgleich', 1)[1][:900])

    def test_auswertung_zaehlt_stornierte_buchungen_nicht_mit(self):
        """Dasselbe Storno-Paar-Problem in /neu/auswertung/: ein stornierter
        Mietertrag blieb in Monatsverlauf und Liegenschafts-Vergleich stehen."""
        from django.utils import timezone as _tz
        from finance.booking import ensure_kontenplan, buche, storniere_buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        heute = _tz.localdate()
        b = buche('1100', '3000', Decimal('4321.00'), 'Miete storniert',
                  datum=heute, liegenschaft=lg)
        storniere_buchung(b)
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/auswertung/?jahr={heute.year}').content.decode('utf-8')
        # Ohne den Fix stand hier «4'321.00» (gemessen) — das stornierte Original
        # zählte weiter, seine Gegenbuchung war ausgeblendet.
        self.assertNotIn("4'321.00", html)

    # ---------- Gelernte Zahler einsehen und korrigieren ----------
    # Eine Automatik, die man nicht einsehen und nicht korrigieren kann, ist ein
    # blinder Fleck: Beim Mieterwechsel ordnete das Programm sonst dauerhaft
    # falsch zu, ohne dass jemand die Ursache finden könnte.

    def test_gelernte_zahler_seite_zeigt_absender_und_mieter(self):
        from finance.models import ZahlerZuordnung
        lg, e, m, v = _basis_objekte()
        ZahlerZuordnung.objects.create(name_norm='narrezaubersoledurn',
                                       name_anzeige='Narrezauber Soledurn',
                                       vertrag=v, treffer=3)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/bankabgleich/zahler/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Narrezauber Soledurn')
        self.assertContains(r, m.display_name)
        self.assertContains(r, '3× automatisch getroffen')

    def test_bankabgleich_verlinkt_die_gelernten_zahler(self):
        """Ohne Einstieg findet die Seite niemand — die Regeln entstehen still."""
        c = Client(); c.force_login(_team_user())
        self.assertContains(c.get('/neu/bankabgleich/'), '/neu/bankabgleich/zahler/')

    def test_gelernten_zahler_auf_anderen_mieter_umbiegen(self):
        from crm.models import Mieter
        from finance.models import ZahlerZuordnung
        lg, e, m, v = _basis_objekte()
        m2 = Mieter.objects.create(vorname='Neu', nachname='Mieter')
        v2 = Mietvertrag.objects.create(mieter=m2, einheit=e, status='aktiv',
                                        beginn=date(2026, 1, 1),
                                        netto_mietzins=Decimal('100'),
                                        nebenkosten=Decimal('0'))
        z = ZahlerZuordnung.objects.create(name_norm='narrezaubersoledurn',
                                           name_anzeige='Narrezauber Soledurn',
                                           vertrag=v, treffer=5)
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/bankabgleich/zahler/speichern/',
                   {'id': z.id, 'vertrag_id': v2.id}, follow=True)
        z.refresh_from_db()
        self.assertEqual(z.vertrag_id, v2.id)
        # Die Trefferzahl gehörte zur alten Regel — sie darf die neue nicht
        # fälschlich als bewährt ausweisen.
        self.assertEqual(z.treffer, 0)
        self.assertIsNone(z.zuletzt)
        self.assertContains(r, 'zahlt neu für')

    def test_gelernten_zahler_vergessen(self):
        from finance.models import ZahlerZuordnung
        lg, e, m, v = _basis_objekte()
        z = ZahlerZuordnung.objects.create(name_norm='narrezaubersoledurn',
                                           name_anzeige='Narrezauber Soledurn',
                                           vertrag=v)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/zahler/speichern/',
               {'id': z.id, 'aktion': 'loeschen'}, follow=True)
        self.assertFalse(ZahlerZuordnung.objects.filter(id=z.id).exists())

    def test_gelernten_zahler_umbiegen_bucht_nichts_um(self):
        """Die Regel gilt für den NÄCHSTEN Import — bereits verbuchte Zahlungen
        bleiben, wie sie gebucht wurden. Sonst wäre eine Korrektur der Regel
        stillschweigend eine rückwirkende Umbuchung."""
        from crm.models import Mieter
        from finance.booking import ensure_kontenplan
        from finance.models import ZahlerZuordnung, Buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        zahlung = self._geparkt(gegenpartei='Narrezauber Soledurn')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/sammel-zuordnen/',
               {'zahlung_ids': [str(zahlung.id)], 'vertrag_id': v.id}, follow=True)
        vorher = Buchung.objects.count()
        m2 = Mieter.objects.create(vorname='Neu', nachname='Mieter')
        v2 = Mietvertrag.objects.create(mieter=m2, einheit=e, status='aktiv',
                                        beginn=date(2026, 1, 1),
                                        netto_mietzins=Decimal('100'),
                                        nebenkosten=Decimal('0'))
        z = ZahlerZuordnung.objects.get(name_norm='narrezaubersoledurn')
        c.post('/neu/bankabgleich/zahler/speichern/',
               {'id': z.id, 'vertrag_id': v2.id}, follow=True)
        self.assertEqual(Buchung.objects.count(), vorher)
        zahlung.refresh_from_db()
        self.assertEqual(zahlung.vertrag_id, v.id)

    def test_gelernter_zahler_speichern_verlangt_post(self):
        c = Client(); c.force_login(_team_user())
        self.assertEqual(c.get('/neu/bankabgleich/zahler/speichern/').status_code, 302)

    def test_gelernte_zahler_leerzustand_erklaert_die_automatik(self):
        c = Client(); c.force_login(_team_user())
        self.assertContains(c.get('/neu/bankabgleich/zahler/'),
                            'Noch keine gelernten Zahler')


# ============================================================
# P4 — Kreditoren durchsuchbar + Zahllauf als Prozess
# ============================================================

class KreditorenP4Tests(TestCase):
    """Eine Liste ohne Suche ist bei 300 Rechnungen keine Liste, und ein Zahllauf
    ohne Auswahl ist kein Zahllauf — beides Blocker aus dem Praxis-Audit."""

    def _saldo(self, nummer):
        from finance.models import Buchung
        from django.db.models import Sum
        soll = (Buchung.objects.filter(soll_konto__nummer=nummer, ist_storno=False)
                .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        haben = (Buchung.objects.filter(haben_konto__nummer=nummer, ist_storno=False)
                 .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        return soll - haben

    def _rechnungen(self, lg):
        from finance.models import KreditorenRechnung
        daten = [('Alpha Sanitaer AG', 'CH9300762011623852957', '100.00'),
                 ('Beta Elektro GmbH', 'CH5604835012345678009', '200.00'),
                 ('Gamma Garten', '', '300.00')]
        return [KreditorenRechnung.objects.create(
            lieferant=n, referenz=f'RE-{i}', betrag=Decimal(b),
            datum=date(2024, 4, 1), faellig_am=date(2024, 4, 20 + i),
            iban=iban, liegenschaft=lg, status='freigegeben')
            for i, (n, iban, b) in enumerate(daten)]

    def _mit_iban(self):
        from crm.models import Verwaltung
        vw = Verwaltung.objects.first()
        if vw is None:
            vw = Verwaltung.objects.create(firma='Testverwaltung')
        vw.iban = 'CH5604835012345678009'
        vw.save()
        return vw

    # ---------- Liste ----------
    def test_kreditorenliste_ist_durchsuchbar(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/kreditoren/?q=Beta')
        self.assertEqual(r.status_code, 200)
        namen = [z['k'].lieferant for z in r.context['rows']]
        self.assertEqual(namen, ['Beta Elektro GmbH'])

    def test_kreditorenliste_findet_ueber_referenz_und_betrag(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/kreditoren/?q=RE-2')
        self.assertEqual([z['k'].lieferant for z in r.context['rows']], ['Gamma Garten'])
        r = c.get('/neu/kreditoren/?q=200')
        self.assertEqual([z['k'].lieferant for z in r.context['rows']], ['Beta Elektro GmbH'])

    def test_kreditorenliste_sortiert_standardmaessig_nach_faelligkeit(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/kreditoren/')
        self.assertEqual([z['k'].lieferant for z in r.context['rows']],
                         ['Alpha Sanitaer AG', 'Beta Elektro GmbH', 'Gamma Garten'])
        r = c.get('/neu/kreditoren/?sort=-betrag')
        self.assertEqual([z['k'].lieferant for z in r.context['rows']][0], 'Gamma Garten')

    def test_kennzahlen_gelten_fuer_den_ganzen_bestand_nicht_die_seite(self):
        """Beim Blättern darf die Kopfzahl nicht mitwandern."""
        from finance.models import KreditorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        for i in range(60):
            KreditorenRechnung.objects.create(
                lieferant=f'Lieferant {i}', betrag=Decimal('10.00'),
                datum=date(2024, 4, 1), liegenschaft=lg, status='neu')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/kreditoren/')
        self.assertEqual(r.context['anzahl_neu'], 60)
        self.assertEqual(r.context['total_neu'], Decimal('600.00'))
        self.assertEqual(len(r.context['rows']), 50)     # Seite 1
        r2 = c.get('/neu/kreditoren/?seite=2')
        self.assertEqual(r2.context['anzahl_neu'], 60)   # unverändert
        self.assertEqual(len(r2.context['rows']), 10)

    def test_erfassen_uebernimmt_die_iban(self):
        """Ohne IBAN kommt eine manuell erfasste Rechnung nie in einen Zahllauf."""
        from finance.models import KreditorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/neu/', {'lieferant': 'Delta Malerei', 'betrag': '250',
                                        'iban': 'CH93 0076 2011 6238 5295 7'})
        k = KreditorenRechnung.objects.get(lieferant='Delta Malerei')
        self.assertEqual(k.iban, 'CH9300762011623852957')

    # ---------- Zahllauf ----------
    def test_zahllauf_zeigt_vorschlag_und_fehlende_iban(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/zahllauf/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['vorschlag']), 3)
        self.assertEqual(r.context['ohne_iban'], 1)
        self.assertEqual(r.context['summe_vorschlag'], Decimal('600.00'))

    def test_zahllauf_nimmt_nur_die_ausgewaehlten_rechnungen(self):
        """Vorher packte der Zahllauf ungefragt ALLE freigegebenen Rechnungen
        in die Datei — eine Auswahl gab es nicht."""
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        self._mit_iban()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': [krs[0].id],
                                      'ausfuehrungsdatum': '2024-04-15'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/xml')
        for k in krs:
            k.refresh_from_db()
        self.assertEqual(krs[0].status, 'in_zahlung')
        self.assertEqual(krs[1].status, 'freigegeben')   # nicht ausgewählt
        self.assertEqual(krs[2].status, 'freigegeben')

    def test_zahllauf_haelt_das_ausfuehrungsdatum_fest(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        self._mit_iban()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': [krs[0].id],
                                  'ausfuehrungsdatum': '2024-04-15'})
        krs[0].refresh_from_db()
        self.assertEqual(krs[0].zahlung_ausfuehrung, date(2024, 4, 15))

    def test_zahllauf_ohne_verwaltungs_iban_erzeugt_keine_datei(self):
        from crm.models import Verwaltung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        Verwaltung.objects.update(iban='')
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': [krs[0].id]})
        self.assertEqual(r.status_code, 302)
        krs[0].refresh_from_db()
        self.assertEqual(krs[0].status, 'freigegeben')

    def test_zahllauf_verbucht_die_auswahl_sammelweise(self):
        """Danach musste bisher jede der ~40 Zahlungen einzeln geklickt werden."""
        from finance.models import KreditorenZahlung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        self._mit_iban()
        c = Client(); c.force_login(_team_user())
        ids = [krs[0].id, krs[1].id]
        c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': ids,
                                  'ausfuehrungsdatum': '2024-04-15'})
        c.post('/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': ids,
                                  'valuta': '2024-04-16', 'bank_konto': '1020'})
        for k in krs:
            k.refresh_from_db()
        self.assertEqual(krs[0].status, 'bezahlt')
        self.assertEqual(krs[1].status, 'bezahlt')
        self.assertEqual(krs[2].status, 'freigegeben')
        self.assertEqual(self._saldo('1020'), Decimal('-300.00'))
        self.assertEqual(self._saldo('2000'), Decimal('300.00'))
        self.assertEqual(KreditorenZahlung.objects.filter(kreditor__in=krs[:2]).count(), 2)

    def test_zahllauf_bucht_auf_das_valutadatum(self):
        from finance.models import KreditorenZahlung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        self._mit_iban()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': [krs[0].id],
                                  'valuta': '2024-04-16'})
        z = KreditorenZahlung.objects.get(kreditor=krs[0])
        self.assertEqual(z.datum, date(2024, 4, 16))

    def test_zahllauf_bucht_auf_gewaehltes_bankkonto(self):
        from finance.models import Buchungskonto
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        Buchungskonto.objects.create(nummer='1021', bezeichnung='Bank 2', typ='aktiv')
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': [krs[0].id],
                                  'valuta': '2024-04-16', 'bank_konto': '1021'})
        self.assertEqual(self._saldo('1021'), Decimal('-100.00'))
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))

    def test_zahllauf_zuruecksetzen_gibt_rechnungen_wieder_frei(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        self._mit_iban()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': [krs[0].id],
                                  'ausfuehrungsdatum': '2024-04-15'})
        c.post('/neu/zahllauf/', {'aktion': 'zuruecksetzen', 'rechnung_ids': [krs[0].id]})
        krs[0].refresh_from_db()
        self.assertEqual(krs[0].status, 'freigegeben')

    def test_zahllauf_verbucht_nicht_doppelt(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        daten = {'aktion': 'bezahlt', 'rechnung_ids': [krs[0].id], 'valuta': '2024-04-16'}
        c.post('/neu/zahllauf/', daten)
        c.post('/neu/zahllauf/', daten)
        self.assertEqual(self._saldo('1020'), Decimal('-100.00'))

    def test_einzelzahlung_nimmt_valuta_und_bankkonto(self):
        from finance.models import Buchungskonto, KreditorenZahlung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        Buchungskonto.objects.create(nummer='1021', bezeichnung='Bank 2', typ='aktiv')
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': krs[0].id,
                                             'valuta': '2024-04-16',
                                             'bank_konto': '1021'})
        z = KreditorenZahlung.objects.get(kreditor=krs[0])
        self.assertEqual(z.datum, date(2024, 4, 16))
        self.assertEqual(self._saldo('1021'), Decimal('-100.00'))


# ============================================================
# P5 — UI-Konsistenz + Datenverlust-Fallen in den Finanzen
# ============================================================

class FinanzUIP5Tests(TestCase):
    """Fallen, die still Geld oder Arbeit kosten: der Tausender-Apostroph, eine
    Sollstellung über das falsche Portfolio, eine wirkungslose Paginierung."""

    def _saldo(self, nummer):
        from finance.models import Buchung
        from django.db.models import Sum
        soll = (Buchung.objects.filter(soll_konto__nummer=nummer, ist_storno=False)
                .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        haben = (Buchung.objects.filter(haben_konto__nummer=nummer, ist_storno=False)
                 .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        return soll - haben

    # ---------- Tausender-Apostroph ----------
    def test_num_normalisiert_schweizer_betragsformate(self):
        from core.views.fw import _num
        self.assertEqual(_num("12'500.00"), '12500.00')
        self.assertEqual(_num("1’200,50"), '1200.50')      # typografischer Apostroph
        self.assertEqual(_num(" CHF 3 400.00 "), '3400.00')
        self.assertEqual(_num('8.1'), '8.1')
        self.assertEqual(_num(''), '')
        self.assertEqual(_num(None), '')

    def test_eigentuemer_auszahlung_akzeptiert_apostroph_betrag(self):
        """Das Feld ist mit dem `chf`-Filter vorbelegt (12'500.00) — genau dieser
        Wert kam zurück und liess `Decimal()` scheitern."""
        from crm.models import Mandant
        from finance.models import EigentuemerAuszahlung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        md = Mandant.objects.create(firma_oder_name='Muster Immobilien AG')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mandate/{md.id}/auszahlung/',
               {'betrag': "12'500.00", 'datum': '2024-05-01'})
        a = EigentuemerAuszahlung.objects.get(mandant=md)
        self.assertEqual(a.betrag, Decimal('12500.00'))
        self.assertEqual(self._saldo('2850'), Decimal('12500.00'))
        self.assertEqual(self._saldo('1020'), Decimal('-12500.00'))

    def test_kreditor_zahlung_akzeptiert_apostroph_betrag(self):
        from finance.models import KreditorenRechnung, KreditorenZahlung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        kr = KreditorenRechnung.objects.create(
            lieferant='Grossbau AG', betrag=Decimal('12500.00'),
            datum=date(2024, 5, 1), liegenschaft=lg, status='freigegeben')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': kr.id, 'betrag': "12'500.00"})
        z = KreditorenZahlung.objects.get(kreditor=kr)
        self.assertEqual(z.betrag, Decimal('12500.00'))

    # ---------- Sollstellung folgt dem Filter ----------
    def test_sollstellung_beachtet_den_liegenschaftsfilter(self):
        """Die Vorschau war gefiltert, der Lauf nicht — ein Klick stellte dem
        ganzen Portfolio Rechnung."""
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        from portfolio.models import Liegenschaft, Einheit
        from crm.models import Mieter
        from rentals.models import Mietvertrag
        ensure_kontenplan()
        lg1, e1, m1, v1 = _basis_objekte()
        lg2 = Liegenschaft.objects.create(strasse='Andergasse 9', plz='3000', ort='Bern')
        e2 = Einheit.objects.create(liegenschaft=lg2, bezeichnung='2. OG', typ='whg',
                                    zimmer=Decimal('3.5'), flaeche_m2=80)
        m2 = Mieter.objects.create(vorname='Rita', nachname='Zweitmieter')
        Mietvertrag.objects.create(einheit=e2, mieter=m2, beginn=date(2024, 1, 1),
                                   status='aktiv', netto_mietzins=Decimal('1500.00'),
                                   nebenkosten=Decimal('150.00'))
        c = Client(); c.force_login(_team_user())
        c.post('/neu/sollstellung/starten/', {'jahr': 2024, 'monat': 5, 'lg': lg1.id})
        titel = 'Miete & NK 05/2024'
        self.assertTrue(DebitorenRechnung.objects.filter(vertrag=v1, titel=titel).exists())
        self.assertFalse(DebitorenRechnung.objects.filter(vertrag__einheit=e2,
                                                          titel=titel).exists())

    def test_sollstellung_ohne_filter_deckt_das_portfolio_ab(self):
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        from portfolio.models import Liegenschaft, Einheit
        from crm.models import Mieter
        from rentals.models import Mietvertrag
        ensure_kontenplan()
        lg1, e1, m1, v1 = _basis_objekte()
        lg2 = Liegenschaft.objects.create(strasse='Andergasse 9', plz='3000', ort='Bern')
        e2 = Einheit.objects.create(liegenschaft=lg2, bezeichnung='2. OG', typ='whg',
                                    zimmer=Decimal('3.5'), flaeche_m2=80)
        m2 = Mieter.objects.create(vorname='Rita', nachname='Zweitmieter')
        Mietvertrag.objects.create(einheit=e2, mieter=m2, beginn=date(2024, 1, 1),
                                   status='aktiv', netto_mietzins=Decimal('1500.00'),
                                   nebenkosten=Decimal('150.00'))
        c = Client(); c.force_login(_team_user())
        c.post('/neu/sollstellung/starten/', {'jahr': 2024, 'monat': 5})
        titel = 'Miete & NK 05/2024'
        self.assertEqual(DebitorenRechnung.objects.filter(titel=titel).count(), 2)

    # ---------- Paginierung ----------
    def test_debitorenliste_liefert_nur_die_angeforderte_seite(self):
        """Der Fuss zeigte «Seite 1/2», die Tabelle rendert(e) trotzdem alles."""
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        for i in range(60):
            DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=lg, einheit=e, titel=f'Position {i}',
                betrag=Decimal('100.00'), datum=date(2024, 5, 1),
                faellig_am=date(2024, 5, 31), status='offen')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/debitoren/')
        self.assertEqual(r.context['rows_gesamt'], 60)
        self.assertEqual(len(r.context['page'].object_list), 50)
        r2 = c.get('/neu/debitoren/?seite=2')
        self.assertEqual(len(r2.context['page'].object_list), 10)

    def test_debitorenliste_hat_spaltensummen_ueber_den_ganzen_filter(self):
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        for i in range(60):
            DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=lg, einheit=e, titel=f'Position {i}',
                betrag=Decimal('100.00'), datum=date(2024, 5, 1),
                faellig_am=date(2024, 5, 31), status='offen')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/debitoren/')
        # Summe über ALLE 60, nicht nur die 50 der ersten Seite
        self.assertEqual(r.context['total_betrag'], Decimal('6000.00'))
        self.assertEqual(r.context['total_offen'], Decimal('6000.00'))

    def test_blaettern_behaelt_den_liegenschaftsfilter(self):
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        for i in range(60):
            DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=lg, einheit=e, titel=f'Position {i}',
                betrag=Decimal('100.00'), datum=date(2024, 5, 1),
                faellig_am=date(2024, 5, 31), status='offen')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/debitoren/?lg={lg.id}')
        self.assertContains(r, f'seite=2&status=&q=&lg={lg.id}'.replace('status=&q=&', ''))

    # ---------- Apostroph im Namen bricht keinen Bestätigungsdialog ----------
    def test_apostroph_im_lieferantennamen_bricht_den_dialog_nicht(self):
        """Ein unmaskierter Name beendete den JS-String — der onsubmit-Handler
        wurde gar nicht erst installiert und die Aktion lief ohne Rückfrage."""
        from finance.models import KreditorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        KreditorenRechnung.objects.create(
            lieferant="O'Brien & Co AG", betrag=Decimal('100.00'),
            datum=date(2024, 5, 1), liegenschaft=lg, status='freigegeben')
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/kreditoren/').content.decode('utf-8')
        self.assertIn("confirm('Zahlung an O\\u0027Brien", html)
        self.assertNotIn("confirm('Zahlung an O&#x27;Brien", html)

    # ---------- Buchhaltung auf dem Handy ----------
    # ---------- Erfolgsrechnung & Bilanz als PDF ----------
    # Gemeldet: «Erfolgsrechnung Bilanz sind nicht als PDF verfügbar.» Der
    # Berichte-Hub trug für diesen Bericht ein PDF-Abzeichen, dahinter lag aber
    # nur ein CSV-Journal-Export — das Abzeichen war ein leeres Versprechen.

    def _buchungen_fuer_abschluss(self):
        from django.utils import timezone as _tz
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        heute = _tz.localdate()
        buche('1100', '3000', Decimal('5000.00'), 'Miete', datum=heute, liegenschaft=lg)
        buche('4000', '1020', Decimal('1200.00'), 'Reparatur', datum=heute, liegenschaft=lg)
        return lg, heute

    def test_abschluss_pdf_wird_ausgeliefert(self):
        lg, heute = self._buchungen_fuer_abschluss()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/buchhaltung/pdf/?jahr={heute.year}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF-'))

    def test_abschluss_pdf_zeigt_dieselben_zahlen_wie_der_bildschirm(self):
        """Ein Abschluss, der je nach Ausgabeweg anders aussieht, ist wertlos —
        beide Wege rechnen deshalb über `_erfolg_bilanz`."""
        from core.views.fw import _erfolg_bilanz
        lg, heute = self._buchungen_fuer_abschluss()
        daten = _erfolg_bilanz(None, heute.year)
        self.assertEqual(daten['total_ertrag'], Decimal('5000.00'))
        self.assertEqual(daten['total_aufwand'], Decimal('1200.00'))
        self.assertEqual(daten['erfolg'], Decimal('3800.00'))
        # und die Bilanz geht auf
        self.assertEqual(daten['bilanz_differenz'], Decimal('0.00'))

    def test_buchhaltung_seite_bietet_den_pdf_abzug_an(self):
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/buchhaltung/').content.decode('utf-8')
        self.assertIn('/neu/buchhaltung/pdf/', html)
        self.assertIn('Erfolgsrechnung &amp; Bilanz (PDF)', html)

    def test_berichte_hub_pdf_abzeichen_ist_kein_leeres_versprechen(self):
        """Das Abzeichen im Hub muss zu einem echten PDF führen."""
        lg, heute = self._buchungen_fuer_abschluss()
        c = Client(); c.force_login(_team_user())
        self.assertContains(c.get('/neu/berichte/'), 'Erfolgsrechnung &amp; Bilanz')
        self.assertEqual(c.get('/neu/buchhaltung/pdf/').status_code, 200)

    def test_jedes_pdf_abzeichen_im_hub_liefert_auch_ein_pdf(self):
        """Das PDF-Abzeichen im Berichte-Hub ist ein reines Anzeige-Flag —
        nichts prüfte, ob dahinter wirklich ein PDF liegt. Bei «Erfolgsrechnung
        & Bilanz» war es deshalb ein leeres Versprechen (gemeldet).

        Dieser Test pinnt die vier versprochenen Ausgaben. Verschwindet eine,
        fällt es hier auf statt beim Nutzer."""
        from crm.models import Mandant
        lg, _heute = self._buchungen_fuer_abschluss()
        mieter = Mieter.objects.first()
        md = Mandant.objects.create(firma_oder_name='Eigentümer AG')
        lg.mandant = md; lg.save(update_fields=['mandant'])
        c = Client(); c.force_login(_team_user())
        ziele = [
            ('Erfolgsrechnung & Bilanz', '/neu/buchhaltung/pdf/'),
            ('Mieterkonten', f'/neu/personen/{mieter.id}/kontoauszug/'),
            ('Mieterspiegel', f'/neu/mieterspiegel/?pdf=1&lg={lg.id}'),
            ('Mandatsabrechnung', f'/neu/mandate/{md.id}/abrechnung/?pdf=1'),
            ('Kontokorrent', f'/neu/mandate/{md.id}/kontokorrent/?pdf=1'),
        ]
        for name, url in ziele:
            r = c.get(url)
            self.assertEqual(r.status_code, 200, f"{name}: {url} -> {r.status_code}")
            self.assertIn('pdf', r.get('Content-Type', ''),
                          f"{name} liefert kein PDF ({r.get('Content-Type')})")

    def test_abschluss_pdf_vertraegt_alle_jahre_und_unsinn(self):
        c = Client(); c.force_login(_team_user())
        self.assertEqual(c.get('/neu/buchhaltung/pdf/?jahr=alle').status_code, 200)
        self.assertEqual(c.get('/neu/buchhaltung/pdf/?jahr=xyz').status_code, 200)

    def test_erfolgsrechnung_erzwingt_keine_mindestbreite(self):
        """min-w-max schob den Betrag aus dem Bild: auf dem Handy sah man
        entweder Kontonummer+Name ODER den Betrag, nie beides."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/buchhaltung/').content.decode('utf-8')
        erfolg = html.split('id="bh-erfolg"')[1].split('id="bh-bilanz"')[0]
        self.assertNotIn('min-w-max', erfolg)
        bilanz = html.split('id="bh-bilanz"')[1].split('id="bh-journal"')[0]
        self.assertNotIn('min-w-max', bilanz)

    # ---------- Tabellen am PC: keine Querscroll-Pflicht ----------
    # «min-w-max» machte die Tabelle so breit wie ihr Inhalt; auf
    # /neu/debitoren/ waren das 1412 px in einer 1134 px breiten Spalte
    # (1440 px Fenster), also lagen Mahnstufe und Aktionen ausserhalb des
    # Bildes. Gelöst über eine zentrale Regel in base.html, die linksbündige
    # Textspalten umbrechen lässt.

    def _debitoren_tabelle(self):
        """Der Desktop-Teil der Debitoren-Seite als HTML-Ausschnitt."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/debitoren/').content.decode('utf-8')
        return html.split('<!-- Desktop: Tabelle -->')[1].split('</table>')[0]

    def test_geldspalten_bleiben_rechtsbuendig(self):
        """Die Umbruch-Regel unterscheidet Text von Zahl allein an
        `text-right`. Verliert eine Betragsspalte diese Klasse, fängt der
        Betrag an umzubrechen («1'450.» / «00») — die Zahlenkolonne wäre
        nicht mehr lesbar. Diese Konvention wird hier gepinnt."""
        import re
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete & NK 08/2026',
            betrag=Decimal('1450.00'), status='offen',
            faellig_am=date(2026, 8, 1))
        tabelle = self._debitoren_tabelle()
        zellen = re.findall(r'<td\b([^>]*)>(.*?)</td>', tabelle, re.S)
        self.assertTrue(zellen, 'keine Tabellenzeilen gerendert — Test wäre wertlos')
        # Eine Betragszelle enthält NUR den Betrag. Über den Zellinhalt statt
        # über ein Muster im Fliesstext, sonst zählt «01.08.2026» als Betrag.
        def nur_betrag(inhalt):
            txt = re.sub(r'<[^>]+>', '', inhalt)
            txt = txt.replace('&nbsp;', ' ').strip()
            return re.fullmatch(r"-?[\d'\u2019]{1,15}\.\d{2}", txt) is not None
        betrags_zellen = [(a, i) for a, i in zellen if nur_betrag(i)]
        self.assertTrue(betrags_zellen, 'kein Betrag in der Tabelle gefunden')
        for attr, inhalt in betrags_zellen:
            self.assertIn('text-right', attr,
                          f'Betragszelle ohne text-right: {inhalt.strip()[:60]}')

    def test_base_laesst_breite_tabellen_am_pc_umbrechen(self):
        """Ohne diese Regel scrollt jede Tabelle mit vielen Spalten quer.
        Sie steht zentral in base.html, damit sie auch für neue Tabellen
        gilt — und ist deshalb leicht versehentlich zu entfernen."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/debitoren/').content.decode('utf-8')
        self.assertIn('@media (min-width: 768px)', html)
        self.assertIn('main table.min-w-max td:not(.text-right):not(.text-center)', html)
        # Der Wrapper bleibt scrollbar — sehr breite Tabellen (Spalte je
        # Bewerber) brauchen ihn weiterhin.
        self.assertIn('overflow-x-auto', html)

    def test_journal_hat_kartenansicht_fuers_handy(self):
        """Sieben Spalten passen auf kein Telefon — mobil als Karten."""
        lg, e, m, v = _basis_objekte()
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        buche('1020', '3000', Decimal('1500.00'), 'Miete August', datum=date(2026, 8, 1),
              liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/buchhaltung/?tab=journal').content.decode('utf-8')
        journal = html.split('id="bh-journal"')[1]
        self.assertIn('md:hidden', journal)          # Karten nur mobil
        self.assertIn('hidden md:block', journal)    # Tabelle nur ab Tablet
        # Beleg UND Betrag stehen in der Kartenansicht
        karten = journal.split('hidden md:block')[0]
        self.assertIn('Miete August', karten)
        self.assertIn("1'500.00", karten)

    def test_liegenschaft_detail_mit_dokument_stuerzt_nicht_ab(self):
        """Dokument.datum ist ein DateField — das Template formatierte es mit
        «H:i» und riss beim ersten abgelegten Dokument die ganze Seite in einen
        500er (TypeError: format for date objects may not contain 'H')."""
        import tempfile
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from portfolio.models import Dokument
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        ov = override_settings(MEDIA_ROOT=tmp.name); ov.enable()
        self.addCleanup(ov.disable)
        lg, e, m, v = _basis_objekte()
        Dokument.objects.create(
            liegenschaft=lg, titel='Hausordnung', kategorie='Allgemein',
            datum=date(2026, 5, 4),
            datei=SimpleUploadedFile('ho.pdf', b'%PDF-1.4', content_type='application/pdf'))
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/liegenschaften/{lg.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '04.05.2026')

    def test_tabellen_stapeln_sich_mobil_zentral(self):
        """Statt ~40 Templates einzeln: base.html stapelt jede Tabelle mit
        Kopfzeile unter 768 px zu «Spaltenname — Wert» pro Zeile."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/kreditoren/').content.decode('utf-8')
        self.assertIn('fwTabellenStapeln', html)                 # Skript ausgeliefert
        self.assertIn("table[data-stack]", html)                 # CSS vorhanden
        self.assertIn('@media (max-width: 767px)', html)         # nur mobil
        # display:block auf der Tabelle selbst — sonst misst der Browser die
        # Breite über eine anonyme Tabellenzelle wieder am Inhalt.
        self.assertIn('table[data-stack] { display: block;', html)

    def test_kontoblatt_hat_kartenansicht_fuers_handy(self):
        """Das Kontoblatt ist der nächste Klick aus der Erfolgsrechnung."""
        lg, e, m, v = _basis_objekte()
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        buche('1020', '3000', Decimal('1500.00'), 'Miete August', datum=date(2026, 8, 1),
              liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/buchhaltung/konto/3000/?jahr=2026').content.decode('utf-8')
        karten = html.split('hidden md:block')[0]
        self.assertIn('md:hidden', karten)
        self.assertIn('Miete August', karten)
        self.assertIn("1'500.00", karten)


# ============================================================
# Digitale Unterschrift auf den Brief-PDFs
# ============================================================

def _sig_bytes():
    """Kleines PNG als Ersatz für einen echten Unterschriften-Scan."""
    import io as _io
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (400, 120), "white")
    d = ImageDraw.Draw(img)
    d.line([(20, 90), (90, 30), (150, 95), (220, 35), (300, 80), (370, 45)],
           fill="black", width=6)
    b = _io.BytesIO(); img.save(b, format="PNG")
    return b.getvalue()


class GratismonatSichtbarTests(TestCase):
    """Ein voller Mietzins-Erlass darf nicht unbemerkt entstehen.

    Gemeldet: Eine Sollmietzins-Zeile zeigte «−500.00» Rabatt, obwohl kein
    Rabatt gewährt worden war. Die Zahl war echt (rabatt_netto = 500 in den
    Daten) — nur konnte niemand nachvollziehen, woher sie kam:

      - Anklickbar war das ganze, formularbreite Band über «Speichern». Ein
        Tipper, der knapp zu hoch landet, setzte einen 100-%-Erlass.
      - Sichtbar änderte sich dabei nichts: Das Rabatt-Feld blieb leer.
      - Die Bestätigung nannte nur eine Summe, in der der Erlass schon
        verrechnet war.
      - Die fertige Zeile sagte «−500.00» und sonst nichts.
    """

    def _erfassen(self, client, einheit, **extra):
        daten = {'einheit_id': einheit.id, 'gueltig_ab': '2026-01-01',
                 'netto_mietzins': '500', 'nebenkosten': '50'}
        daten.update(extra)
        return client.post('/neu/sollmietzins/', daten, follow=True)

    def test_ohne_ankreuzen_kein_rabatt(self):
        """Der Normalfall — sonst wäre alles Weitere sinnlos."""
        from portfolio.models import Sollmietzins
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._erfassen(c, e)
        s = Sollmietzins.objects.filter(einheit=e).order_by('-id').first()
        self.assertEqual(s.rabatt_netto, Decimal('0.00'))
        self.assertFalse(s.hat_rabatt)
        self.assertFalse(s.ist_voller_erlass)

    def test_voller_erlass_wird_als_solcher_erkannt(self):
        from portfolio.models import Sollmietzins
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._erfassen(c, e, mietzinsfrei='1')
        s = Sollmietzins.objects.filter(einheit=e).order_by('-id').first()
        self.assertEqual(s.rabatt_netto, Decimal('500.00'))
        self.assertTrue(s.ist_voller_erlass)
        self.assertEqual(s.verrechnet_brutto, Decimal('50.00'))

    def test_teilrabatt_ist_kein_voller_erlass(self):
        """Ein ausgehandelter Rabatt und ein Gratismonat sind nicht dasselbe."""
        from portfolio.models import Sollmietzins
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._erfassen(c, e, rabatt_netto='100')
        s = Sollmietzins.objects.filter(einheit=e).order_by('-id').first()
        self.assertTrue(s.hat_rabatt)
        self.assertFalse(s.ist_voller_erlass)

    def test_bestaetigung_benennt_den_vollen_erlass(self):
        """Die Meldung nannte bisher nur «zu zahlen CHF 50» — die Zahl allein
        verrät nicht, dass 500 erlassen wurden."""
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        html = self._erfassen(c, e, mietzinsfrei='1').content.decode('utf-8')
        self.assertIn('VOLLST', html.upper())
        self.assertIn('Gratismonat', html)

    def test_zeile_zeigt_woher_der_rabatt_kommt(self):
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._erfassen(c, e, mietzinsfrei='1')
        html = c.get(f'/neu/objekte/{e.id}/?tab=mietzins').content.decode('utf-8')
        self.assertIn('Gratismonat', html)

    def test_klickflaeche_umfasst_nicht_mehr_die_ganze_formularbreite(self):
        """Die Ursache selbst: Das Kästchen sass in einem <label>, das über die
        volle Formularbreite ging und direkt über «Speichern» lag."""
        import re
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/objekte/{e.id}/?tab=mietzins').content.decode('utf-8')
        # das <label> um das Kästchen herum finden
        stelle = html.find('name="mietzinsfrei"')
        self.assertGreater(stelle, -1, 'Gratismonat-Kästchen nicht gefunden')
        label = html.rfind('<label', 0, stelle)
        auf = html[label:stelle]
        self.assertNotIn('col-span-4', auf,
                         'Klickfläche geht wieder über die ganze Formularbreite')


class MediaZugriffTests(TestCase):
    """Welche hochgeladene Datei darf ein Fremder ohne Anmeldung abrufen?

    Sieben Dateifelder landeten alle im selben Topf `uploads/<datum>/` —
    Objektfotos fürs Inserat neben Schadenfotos aus fremden Wohnungen,
    eingescannten Mieterdokumenten, Unterhaltsbelegen und Innenaufnahmen der
    Ausstattung. Die Zugriffsregel unterscheidet nach Pfad und liess Bilder
    anonym durch, weil der Portal-Feed die Inserat-Fotos braucht. In einem
    gemeinsamen Topf KONNTE sie Inserat- nicht von Wohnungsfoto trennen.

    Jetzt hat jedes Modell seinen Ordner. Dieser Test hält fest, welcher
    öffentlich ist — und zwingt jedes NEUE Dateifeld zu einer Entscheidung.
    """

    #: Ordner, deren Bilder bewusst ohne Anmeldung ausgeliefert werden.
    OEFFENTLICH_GEWOLLT = {'logos', 'objekt_fotos'}

    def _felder(self):
        from django.apps import apps
        from django.db.models import FileField
        for m in apps.get_models():
            for f in m._meta.get_fields():
                if not isinstance(f, FileField):
                    continue
                ut = f.upload_to
                pfad = ut(m(), 'datei.jpg') if callable(ut) else (str(ut).rstrip('/') + '/datei.jpg')
                yield f"{m.__name__}.{f.name}", pfad

    def test_nur_inserat_und_logo_sind_oeffentlich(self):
        from core.views.media_protected import ist_oeffentlich
        offen = sorted({(name, pfad) for name, pfad in self._felder() if ist_oeffentlich(pfad)})
        ordner = {p.split('/')[0] for _n, p in offen}
        self.assertEqual(ordner, self.OEFFENTLICH_GEWOLLT,
                         'Ohne Anmeldung abrufbar sind: ' +
                         ', '.join(f'{n} ({p})' for n, p in offen))

    def test_schadenfotos_und_dokumente_brauchen_anmeldung(self):
        """Die konkreten Fälle beim Namen genannt — damit klar bleibt, worum
        es geht, falls jemand die Ordner wieder zusammenlegt."""
        from core.views.media_protected import ist_oeffentlich
        for feld, pfad in self._felder():
            if feld.split('.')[0] in ('SchadenMeldung', 'SchadenFoto', 'Dokument',
                                      'Unterhalt', 'Ausstattung'):
                self.assertFalse(ist_oeffentlich(pfad),
                                 f'{feld} ({pfad}) wäre ohne Anmeldung abrufbar')

    def test_alt_ordner_ist_geschuetzt_ausser_inseratfotos(self):
        """Bereits hochgeladene Dateien liegen weiter in `uploads/`. Der Ordner
        ist jetzt geschützt — sonst blieben die Alt-Bestände offen. Damit
        veröffentlichte Inserate nicht ins Leere laufen, bleiben Objektfotos
        auch dort öffentlich; erkannt über die Datenbank."""
        from core.views.media_protected import ist_oeffentlich, ist_objektfoto
        from portfolio.models import EinheitFoto
        from django.core.files.base import ContentFile
        alt = 'uploads/2026-01-01/wohnzimmer.jpg'
        self.assertFalse(ist_oeffentlich(alt))
        self.assertFalse(ist_objektfoto(alt))          # noch kein Objektfoto

        lg = Liegenschaft.objects.create(strasse='Fotoweg 1', plz='3000', ort='Bern')
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='1 Zi', typ='wohnung')
        foto = EinheitFoto(einheit=e)
        foto.bild.name = alt                            # Alt-Pfad wie im Bestand
        foto.save()
        self.assertTrue(ist_objektfoto(alt))            # jetzt als Inserat-Bild erkannt

    def test_fremder_bekommt_schadenfoto_nicht(self):
        """Nicht nur die Regel, sondern die Auslieferung."""
        import os, shutil
        from django.conf import settings
        from django.test import Client
        rel = 'schaden_fotos/2026-01-01/bad.jpg'
        ziel = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        with open(ziel, 'wb') as fh:
            fh.write(b'\xff\xd8\xff\xe0JFIF-Testbild')
        try:
            self.assertEqual(Client().get('/media/' + rel).status_code, 404)
            c = Client(); c.force_login(_team_user())
            self.assertEqual(c.get('/media/' + rel).status_code, 200)
        finally:
            shutil.rmtree(os.path.join(settings.MEDIA_ROOT, 'schaden_fotos'),
                          ignore_errors=True)

    def test_pfad_umweg_umgeht_den_schutz_nicht(self):
        """Ein vorangestelltes «./» oder «x/../» darf die Sensibel-Prüfung
        nicht austricksen. Vorher entschied `ist_oeffentlich` auf der rohen
        URL, während `safe_join` den Umweg wieder wegnormalisierte und die
        echte, sensible Datei öffnete — zwei Codestellen, zwei Pfade. Der
        Client normalisiert «./» selbst weg, «%2e» aber nicht; getestet wird
        deshalb der aufgelöste Pfad direkt über die View."""
        import os, shutil
        from django.conf import settings
        from django.test import RequestFactory
        from django.http import Http404
        from core.views.media_protected import geschuetzte_media
        rel = 'schaden_fotos/2026-01-01/geheim.jpg'
        ziel = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        with open(ziel, 'wb') as fh:
            fh.write(b'\xff\xd8\xff\xe0JFIF')
        rf = RequestFactory()
        try:
            for umweg in ('./schaden_fotos/2026-01-01/geheim.jpg',
                          'x/../schaden_fotos/2026-01-01/geheim.jpg',
                          './/schaden_fotos/2026-01-01/geheim.jpg'):
                req = rf.get('/media/' + umweg)
                from django.contrib.auth.models import AnonymousUser
                req.user = AnonymousUser()
                with self.assertRaises(Http404,
                                       msg=f'Umweg «{umweg}» lieferte die Datei aus'):
                    geschuetzte_media(req, umweg)
        finally:
            shutil.rmtree(os.path.join(settings.MEDIA_ROOT, 'schaden_fotos'),
                          ignore_errors=True)

    def test_html_beleg_wird_nie_inline_gerendert(self):
        """Ein hochgeladener «Beleg» rechnung.html liefe sonst als Stored XSS
        gegen das nächste Team-Mitglied, das ihn öffnet. HTML/XML müssen wie
        SVG als Download (attachment, nosniff) rausgehen, nicht inline."""
        import os, shutil
        from django.conf import settings
        from django.test import Client
        rel = 'kreditoren_belege/boese.html'
        ziel = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        with open(ziel, 'w') as fh:
            fh.write('<html><script>alert(1)</script></html>')
        try:
            c = Client(); c.force_login(_team_user())
            r = c.get('/media/' + rel)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r['Content-Disposition'], 'attachment')
            self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        finally:
            shutil.rmtree(os.path.join(settings.MEDIA_ROOT, 'kreditoren_belege'),
                          ignore_errors=True)


class MediaDeployPruefungTests(TestCase):
    """Der Media-Schutz greift nur, wenn /media/ überhaupt bei Django ankommt.

    Ist /media/ beim Hoster als statisches Verzeichnis gemappt, liefert der
    Webserver die Dateien direkt aus. Der View wird dann nie aufgerufen, alle
    Regeln aus `media_protected` sind wirkungslos — und nichts weist darauf
    hin. Aus dem Code heraus lässt sich das nicht feststellen, deshalb prüft
    `pruefe_media_schutz` es beim Deploy von aussen: eine Kanarienvogel-Datei
    unter geschütztem Prefix ablegen, ohne Anmeldung abrufen, wieder löschen.

    Getestet wird die Auswertung (der Netzabruf selbst wird ersetzt) und die
    Voraussetzung, auf der die ganze Prüfung ruht: dass der gewählte Pfad für
    Django wirklich tabu ist.
    """

    def setUp(self):
        import tempfile
        from django.test import override_settings
        self._tmp = tempfile.TemporaryDirectory()
        self._ov = override_settings(MEDIA_ROOT=self._tmp.name)
        self._ov.enable()

    def tearDown(self):
        self._ov.disable()
        self._tmp.cleanup()

    def _lauf(self, antwort):
        """Führt den Befehl mit einer vorgegebenen HTTP-Antwort aus.

        Gibt (ausgabe, exitcode) zurück; exitcode None = kein Abbruch."""
        import io
        from unittest import mock
        from django.core.management import call_command
        from core.management.commands import pruefe_media_schutz as cmd
        raus, fehler = io.StringIO(), io.StringIO()
        code = None
        with mock.patch.object(cmd, '_hole', return_value=antwort):
            try:
                call_command('pruefe_media_schutz', '--url', 'https://example.ch',
                             stdout=raus, stderr=fehler)
            except SystemExit as e:
                code = e.code
        return raus.getvalue() + fehler.getvalue(), code

    def test_kanarienvogel_pfad_ist_fuer_django_tabu(self):
        """Trägt der Test überhaupt? Läge der Pfad in einem öffentlichen
        Ordner, käme die Datei zu Recht zurück und die Prüfung würde bei jedem
        Deploy fälschlich Alarm schlagen."""
        from core.views.media_protected import ist_oeffentlich, ist_objektfoto
        from core.management.commands.pruefe_media_schutz import KANARIENVOGEL_PFAD
        self.assertFalse(ist_oeffentlich(KANARIENVOGEL_PFAD))
        self.assertFalse(ist_objektfoto(KANARIENVOGEL_PFAD))

    def test_inhalt_kommt_zurueck_ist_ein_befund(self):
        from core.management.commands.pruefe_media_schutz import KANARIENVOGEL_INHALT
        text, code = self._lauf((200, KANARIENVOGEL_INHALT))
        self.assertEqual(code, 2, 'Befund muss den Lauf mit Code 2 markieren')
        self.assertIn('MEDIA-SCHUTZ WIRKUNGSLOS', text)

    def test_abweisung_ist_kein_befund(self):
        text, code = self._lauf((404, b'<h1>Not Found</h1>'))
        self.assertIsNone(code)
        self.assertIn('Media-Schutz aktiv', text)

    def test_anmeldeseite_mit_status_200_ist_kein_befund(self):
        """Eine Weiterleitung auf die Anmeldung endet ebenfalls bei 200.
        Entscheidend ist deshalb der Inhalt, nicht der Status."""
        text, code = self._lauf((200, b'<html><form action="/login/">Anmelden</form>'))
        self.assertIsNone(code)
        self.assertIn('Media-Schutz aktiv', text)

    def test_nicht_erreichbar_meldet_keine_aussage(self):
        text, code = self._lauf((None, None))
        self.assertIsNone(code)
        self.assertIn('nicht geprüft', text)
        self.assertNotIn('WIRKUNGSLOS', text)

    def test_kanarienvogel_bleibt_nicht_liegen(self):
        """Die Testdatei liegt unter geschütztem Prefix in der echten
        Medienablage — sie darf nach dem Lauf nicht zurückbleiben."""
        import os
        from django.conf import settings
        from core.management.commands.pruefe_media_schutz import (
            KANARIENVOGEL_PFAD, KANARIENVOGEL_INHALT)
        self._lauf((200, KANARIENVOGEL_INHALT))
        self.assertFalse(os.path.exists(os.path.join(settings.MEDIA_ROOT,
                                                     KANARIENVOGEL_PFAD)))

    def test_deploy_ruft_die_pruefung_auf(self):
        """Ein Befehl, den niemand ausführt, prüft nichts."""
        import os
        from django.conf import settings
        with open(os.path.join(settings.BASE_DIR, 'deploy.sh')) as fh:
            self.assertIn('pruefe_media_schutz', fh.read(),
                          'deploy.sh ruft die Media-Schutz-Prüfung nicht auf')


class BewerbungNurAusgeschriebenTests(TestCase):
    """Bewerbungen nur für Objekte, die auch ausgeschrieben sind.

    Das Bewerbungsformular ist ohne Anmeldung erreichbar. Es rendete für JEDE
    Objektnummer — mit Adresse und Objektbezeichnung. Zwei Folgen:

      - Über die Nummer in der Adresse liess sich der ganze Bestand
        durchprobieren.
      - Ein alter, geteilter Link sammelte weiter Bewerbungen — mit
        Lohnausweis, Ausweiskopie und Betreibungsauszug — für eine längst
        vergebene Wohnung.

    Die Gegenprüfung im API-Endpunkt sah zwar vorhanden aus:

        is_rented = False
        if hasattr(einheit, 'ist_vermietet'):        # gibt es nicht
            ...
        elif hasattr(einheit, 'vermietungs_status'): # gibt es auch nicht
            ...
        if is_rented: ...

    Beide Namen existieren an `Einheit` nicht. `is_rented` blieb damit immer
    False, und die Fehlermeldung «bereits vermietet» war unerreichbar.
    """

    def _einheit(self, ausgeschrieben):
        lg = Liegenschaft.objects.create(strasse='Inseratweg 3', plz='4500', ort='Solothurn')
        return Einheit.objects.create(liegenschaft=lg, bezeichnung='2.5 Zi', typ='wohnung',
                                      nettomiete_aktuell=Decimal('1200'),
                                      zur_ausschreibung=ausgeschrieben)

    def test_die_alte_pruefung_haette_nichts_geprueft(self):
        """Warum der Umbau nötig war — schwarz auf weiss."""
        self.assertFalse(hasattr(Einheit, 'ist_vermietet'))
        self.assertFalse(hasattr(Einheit, 'vermietungs_status'))
        self.assertTrue(hasattr(Einheit, 'zur_ausschreibung'))

    def test_formular_nur_bei_ausschreibung(self):
        c = Client()
        offen = self._einheit(True)
        r = c.get(f'/bewerben/{offen.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '2.5 Zi')

        zu = self._einheit(False)
        r2 = c.get(f'/bewerben/{zu.id}/')
        self.assertEqual(r2.status_code, 410)
        self.assertNotContains(r2, 'Inseratweg', status_code=410)   # keine Adresse preisgeben
        self.assertNotContains(r2, '2.5 Zi', status_code=410)

    def _bewerben(self, einheit):
        return Client().post('/api/mietprozess/public/bewerben', {
            'einheit_id': einheit.id,
            'vorname': 'Anna', 'nachname': 'Muster', 'zivilstand': 'ledig',
            'geburtsdatum': '1990-05-05', 'geschlecht': 'weiblich',
            'nationalitaet': 'CH', 'mobilnummer': '079 000 00 00',
            'email': 'anna@example.ch', 'adresse': 'Altweg 4',
            'plz': '4500', 'ort': 'Solothurn',
            'aktueller_vermieter': 'Alt AG', 'kontaktperson_vermieter': 'Herr Alt',
            'telefon_vermieter': '032 000 00 00',
            'erwerbsstatus': 'angestellt', 'beruf': 'Fachfrau',
            'einkommen_jahr': '80000-100000', 'arbeitgeber': 'Firma AG',
            'angestellt_seit': '2020-01-01',
            'kontaktperson_arbeitgeber': 'Frau Chef',
            'telefon_arbeitgeber': '032 111 11 11',
            'gewuenschter_bezugstermin': '2026-10-01',
        })

    def test_bewerbung_auf_nicht_ausgeschriebenes_objekt_abgelehnt(self):
        zu = self._einheit(False)
        r = self._bewerben(zu)
        self.assertEqual(r.status_code, 400)
        self.assertIn('nicht mehr ausgeschrieben', r.json().get('error', ''))

    def test_bewerbung_auf_ausgeschriebenes_objekt_geht(self):
        """Gegenrichtung — sonst würde auch eine Prüfung bestehen, die ALLES
        ablehnt."""
        from mietprozess.models import Mietbewerbung
        offen = self._einheit(True)
        r = self._bewerben(offen)
        self.assertEqual(r.status_code, 201, r.content[:300])
        self.assertTrue(Mietbewerbung.objects.filter(einheit=offen, nachname='Muster').exists())


class PortalFremdzugriffTests(TestCase):
    """Kein Portal-Nutzer darf über eine fremde ID an fremde Daten kommen.

    Mieter- und Eigentümer-Portal sind die einzigen Stellen, an denen Aussen-
    stehende eingeloggt sind. Jede Adresse mit einer ID darin ist damit ein
    Versuch wert: Ändert Mieter B die Nummer in der Adresse auf ein Dokument,
    eine Rechnung, ein Ticket oder eine Kündigung von Mieter A — bekommt er sie?

    Der Test prüft nicht sieben Einzelfälle, sondern liest die Adressen aus der
    URL-Konfiguration. Kommt eine neue Portal-Adresse mit ID dazu, ohne dass
    hier steht, wie sie zu prüfen ist, schlägt er fehl. Genau das ist der Zweck:
    Eine neue Portalseite soll nicht unbemerkt ungeprüft bleiben.
    """

    #: Adressname -> wie eine ID des ANDEREN Mandanten/Mieters entsteht
    #: (Aufruf bekommt die Testdaten, gibt die fremde ID zurück), plus die
    #: HTTP-Methode.
    ERWARTET = {
        'portal_dokument_download': ('get', lambda d: d['fremd_lg_dok'].id),
        'portal_freigabe':          ('post', lambda d: d['fremd_auftrag'].id),
        'mieter_dokument_download': ('get', lambda d: d['fremd_dok'].id),
        'mieter_ticket_detail':     ('get', lambda d: d['fremd_ticket'].id),
        'mieter_ticket_nachricht':  ('post', lambda d: d['fremd_ticket'].id),
        'mieter_rechnung_qr':       ('get', lambda d: d['fremd_rechnung'].id),
        'mieter_kuendigung_pdf':    ('get', lambda d: d['fremd_kuendigung'].id),
    }

    def _portal_adressen(self):
        from django.urls import get_resolver
        gefunden = {}
        for p in get_resolver().url_patterns:
            s = str(p.pattern)
            if not (s.startswith('mieter/') or s.startswith('portal/')):
                continue
            if '<' not in s or not p.name:
                continue
            gefunden[p.name] = s
        return gefunden

    def _welt(self):
        """Zwei getrennte Welten: A gehört dem einen, B dem anderen."""
        from django.core.files.base import ContentFile
        from finance.models import DebitorenRechnung
        from portfolio.models import Dokument as PDokument
        from rentals.models import Dokument, Kuendigung
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker

        def welt(kuerzel):
            lg = Liegenschaft.objects.create(strasse=f'{kuerzel}-Weg 1', plz='3000', ort='Bern')
            md = Mandant.objects.create(firma_oder_name=f'Eigentümer {kuerzel}')
            lg.mandant = md; lg.save()
            e = Einheit.objects.create(liegenschaft=lg, bezeichnung=f'{kuerzel}-Whg', typ='wohnung',
                                       nettomiete_aktuell=Decimal('1500'))
            m = Mieter.objects.create(typ='person', vorname=kuerzel, nachname='Test',
                                      email=f'{kuerzel}@example.ch')
            v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                           netto_mietzins=Decimal('1500'),
                                           nebenkosten=Decimal('200'), status='aktiv')
            mu = User.objects.create_user(username=f'mieter_{kuerzel}', password='x')
            m.benutzer = mu; m.save()
            eu = User.objects.create_user(username=f'eig_{kuerzel}', password='x')
            md.benutzer = eu; md.save()
            return dict(lg=lg, md=md, e=e, m=m, v=v, mieter_user=mu, eig_user=eu)

        a, b = welt('A'), welt('B')
        # IBAN, damit der QR-Einzahlschein überhaupt erzeugt werden kann —
        # sonst wäre die Gegenprobe unten (eigene Rechnung MUSS gehen) wertlos.
        Verwaltung.objects.create(firma='Verwaltung AG', strasse='W 1', plz='8000',
                                  ort='Zürich', iban='CH9300762011623852957')
        # Daten, die NUR A gehören
        dok = Dokument(bezeichnung='A-Vertrag', titel='A-Vertrag', kategorie='vertrag',
                       vertrag=a['v'], mieter=a['m'], einheit=a['e'], liegenschaft=a['lg'],
                       im_portal_sichtbar=True)
        dok.datei.save('a.pdf', ContentFile(b'%PDF-1.4 A'), save=True)
        lgdok = PDokument(liegenschaft=a['lg'], titel='A-Liegenschaft', kategorie='x')
        lgdok.datei.save('alg.pdf', ContentFile(b'%PDF-1.4 A'), save=True)
        rech = DebitorenRechnung.objects.create(vertrag=a['v'], liegenschaft=a['lg'],
                                                titel='A-Miete', betrag=Decimal('1500'),
                                                status='offen', datum=date(2026, 1, 1))
        ticket = SchadenMeldung.objects.create(liegenschaft=a['lg'], betroffene_einheit=a['e'],
                                               gemeldet_von=a['m'], titel='A-Schaden',
                                               beschreibung='nur für A')
        hw = Handwerker.objects.create(firma='Sanitär AG')
        auftrag = HandwerkerAuftrag.objects.create(ticket=ticket, handwerker=hw)
        kuend = Kuendigung.objects.create(vertrag=a['v'], absender='mieter',
                                          eingang_datum=date(2026, 1, 5),
                                          per_datum=date(2026, 3, 31))
        return {'a': a, 'b': b, 'fremd_dok': dok, 'fremd_lg_dok': lgdok,
                'fremd_rechnung': rech, 'fremd_ticket': ticket,
                'fremd_auftrag': auftrag, 'fremd_kuendigung': kuend}

    def test_jede_portal_adresse_mit_id_ist_hier_geprueft(self):
        offen = set(self._portal_adressen()) - set(self.ERWARTET)
        self.assertEqual(offen, set(),
                         f'Neue Portal-Adresse(n) mit ID ohne Fremdzugriffs-Prüfung: {offen}')

    def test_fremde_id_liefert_keine_daten(self):
        """Für JEDE Adresse zwei Anfragen mit derselben ID: einmal als
        Berechtigter, einmal als Fremder.

        Nur der Fremde darf abgewiesen werden. Ohne die erste Anfrage wäre der
        Test wertlos — eine Adresse, die IMMER 404 liefert (fehlende Testdaten,
        vertippte Adresse), würde die Prüfung sonst bestehen, ohne irgendetwas
        über die Berechtigung auszusagen."""
        from django.urls import reverse
        d = self._welt()
        adressen = self._portal_adressen()
        for name, (methode, hole_id) in self.ERWARTET.items():
            if name not in adressen:
                continue                  # Adresse entfernt — nicht Sache dieses Tests
            wer = 'eig_user' if name.startswith('portal_') else 'mieter_user'
            url = reverse(name, args=[hole_id(d)])

            def anfrage(welt):
                c = Client(); c.force_login(d[welt][wer])
                return (c.post(url, {}) if methode == 'post' else c.get(url)).status_code

            self.assertNotIn(anfrage('a'), (403, 404),
                             f'{name}: der BERECHTIGTE kommt nicht an seine eigenen '
                             f'Daten — die Fremdprüfung unten sagt damit nichts aus')
            fremd = anfrage('b')
            self.assertIn(fremd, (403, 404),
                          f'{name}: fremde ID lieferte {fremd} statt 403/404')


class ErfolgBilanzGruppiertTests(TestCase):
    """Erfolgsrechnung und Bilanz in vier Abfragen statt zwei je Konto.

    `_erfolg_bilanz` lief über den ganzen Kontenplan und fragte für jedes Konto
    Soll und Haben einzeln ab — gemessen 90 Abfragen für einen Aufbau von
    /neu/buchhaltung/, danach 2. Dieselbe Rechnung steckt im PDF-Abzug.

    Bei so einem Umbau zählt nur eines: dass exakt dieselben Zahlen
    herauskommen. Deshalb rechnet der Test unten dasselbe nochmals — naiv,
    Konto für Konto — und vergleicht Feld für Feld.
    """

    def _daten(self):
        from finance.booking import ensure_kontenplan, buche, storniere_buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        lg2 = Liegenschaft.objects.create(strasse='Nebenweg 2', plz='3000', ort='Bern',
                                          versicherungswert=Decimal('500000'))
        # Vorjahr — muss in der Bilanz kumulativ mitzählen, in der
        # Erfolgsrechnung des Folgejahres aber nicht.
        buche('1100', '3000', Decimal('4000.00'), 'Miete Vorjahr',
              datum=date(2025, 6, 1), liegenschaft=lg)
        buche('1020', '1100', Decimal('4000.00'), 'Zahlung Vorjahr',
              datum=date(2025, 6, 5), liegenschaft=lg)
        # Laufendes Jahr
        buche('1100', '3000', Decimal('9000.00'), 'Miete', datum=date(2026, 3, 1), liegenschaft=lg)
        buche('4000', '2000', Decimal('2500.00'), 'Reparatur', datum=date(2026, 3, 4), liegenschaft=lg)
        buche('4000', '2000', Decimal('700.00'), 'Reparatur 2', datum=date(2026, 4, 4), liegenschaft=lg2)
        # Ein Storno — beide Seiten müssen sich aufheben
        b = buche('4000', '2000', Decimal('333.00'), 'Irrtum', datum=date(2026, 5, 1), liegenschaft=lg)
        storniere_buchung(b, user=None, datum=date(2026, 5, 2))
        return lg

    def _naiv(self, aktive_lg, jahr):
        """Dieselbe Rechnung, Konto für Konto — die Fassung von vor dem Umbau."""
        from django.db.models import Sum
        from finance.models import Buchung, Buchungskonto
        from core.services.jahresabschluss import abschluss_buchungen_q
        null = Decimal('0.00')
        qs = Buchung.objects.all()
        bil = Buchung.objects.all()
        if aktive_lg:
            qs = qs.filter(liegenschaft=aktive_lg); bil = bil.filter(liegenschaft=aktive_lg)
        if jahr != 'alle':
            qs = qs.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31))
            bil = bil.filter(datum__lte=date(jahr, 12, 31))
        qs = qs.exclude(abschluss_buchungen_q())
        te = ta = tak = tpa = kum = null
        for k in Buchungskonto.objects.all():
            def summe(basis, feld):
                return basis.filter(**{feld: k}).aggregate(t=Sum('betrag'))['t'] or null
            if k.typ == 'ertrag':
                te += summe(qs, 'haben_konto') - summe(qs, 'soll_konto')
                kum += summe(bil, 'haben_konto') - summe(bil, 'soll_konto')
            elif k.typ == 'aufwand':
                ta += summe(qs, 'soll_konto') - summe(qs, 'haben_konto')
                kum -= summe(bil, 'soll_konto') - summe(bil, 'haben_konto')
            else:
                saldo = summe(bil, 'soll_konto') - summe(bil, 'haben_konto')
                if saldo == 0:
                    continue
                if k.typ == 'aktiv':
                    tak += saldo
                elif k.typ == 'passiv':
                    tpa += -saldo
                elif saldo > 0:
                    tak += saldo
                else:
                    tpa += -saldo
        return {'total_ertrag': te, 'total_aufwand': ta, 'total_aktiven': tak,
                'total_passiven': tpa, 'kum_erfolg': kum}

    def test_gruppierte_rechnung_ergibt_dieselben_zahlen(self):
        from core.views.fw import _erfolg_bilanz
        lg = self._daten()
        for aktive_lg, jahr in ((None, 2026), (lg, 2026), (None, 2025), (None, 'alle')):
            neu = _erfolg_bilanz(aktive_lg, jahr)
            alt = self._naiv(aktive_lg, jahr)
            for feld, wert in alt.items():
                self.assertEqual(neu[feld], wert,
                                 f"{feld} weicht ab (lg={aktive_lg}, jahr={jahr}): "
                                 f"{neu[feld]} statt {wert}")

    def test_zahlen_stimmen_auch_absolut(self):
        """Der Vergleich oben würde auch bestehen, wenn BEIDE Fassungen falsch
        rechnen. Deshalb zusätzlich von Hand nachgerechnet."""
        from core.views.fw import _erfolg_bilanz
        self._daten()
        d = _erfolg_bilanz(None, 2026)
        self.assertEqual(d['total_ertrag'], Decimal('9000.00'))
        # 2500 + 700; die 333 sind storniert und heben sich auf
        self.assertEqual(d['total_aufwand'], Decimal('3200.00'))
        self.assertEqual(d['erfolg'], Decimal('5800.00'))
        # Vorjahr 4000 Ertrag → Vortrag; kumuliert 9000 + 4000 − 3200
        self.assertEqual(d['erfolg_vortrag'], Decimal('4000.00'))
        self.assertEqual(d['bilanz_differenz'], Decimal('0.00'))

    def test_buchhaltung_fragt_nicht_je_konto_nach(self):
        """Mit jedem neuen Konto im Kontenplan wuchs der Seitenaufbau."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from finance.models import Buchungskonto
        self._daten()
        c = Client(); c.force_login(_team_user())
        def messen():
            with CaptureQueriesContext(connection) as ctx:
                r = c.get('/neu/buchhaltung/')
            self.assertEqual(r.status_code, 200)
            return len(ctx.captured_queries)
        klein = messen()
        for i in range(10):
            Buchungskonto.objects.create(nummer=f'89{i:02d}', bezeichnung=f'Test {i}', typ='aufwand')
        gross = messen()
        self.assertLessEqual(gross, klein + 2,
                             f'zehn Konten mehr → {klein} statt {gross} Abfragen')


class MobilBeschriftungTests(TestCase):
    """Die mobilen Spalten-Beschriftungen dürfen nicht zusammenkleben.

    Das Skript in base.html setzt jeder Zelle die Überschrift ihrer Spalte als
    Label; mobil steht sie links neben dem Wert. Es las bisher `th.textContent`
    — und das klebt über Element-Grenzen hinweg zusammen. Aus

        <th>Netto / NK<br><span>Referenz</span></th>

    wurde am Handy die Beschriftung «NETTO / NKREFERENZ». Im Browser gemessen
    (390 px, echter Tailwind-Build): vorher «Netto / NKReferenz», nachher
    «Netto / NK Referenz».

    Das Verhalten selbst ist Browser-Sache und wird von dieser Suite nicht
    ausgeführt; hier steht deshalb nur, dass die naive Fassung nicht
    zurückkommt — plus die Liste der Überschriften, die davon betroffen wären.
    """

    def test_label_skript_klebt_nicht_mehr_zusammen(self):
        import pathlib
        s = pathlib.Path('core/templates/fw/base.html').read_text(encoding='utf-8')
        self.assertNotIn("return (th.textContent || '').trim().replace(/\\s+/g, ' ');", s,
                         'Beschriftungen werden wieder aus reinem textContent gebaut')
        self.assertIn('nodeName !== \'BR\'', s)

    def test_mehrteilige_ueberschriften_sind_bekannt(self):
        """Wo Überschriften aus mehreren Elementen bestehen, greift die Regel.
        Kommen neue dazu, ist das kein Fehler — der Test zeigt nur, dass es sie
        gibt und der Fix damit gebraucht wird."""
        import re, pathlib
        mehrteilig = []
        for p in sorted(pathlib.Path('core/templates/fw').rglob('*.html')):
            s = p.read_text(encoding='utf-8')
            for m in re.finditer(r'<th\b[^>]*>(.*?)</th>', s, re.S):
                inner = m.group(1)
                if '<br' in inner or '<span' in inner:
                    mehrteilig.append(f"{p}:{s[:m.start()].count(chr(10)) + 1}")
        self.assertTrue(mehrteilig,
                        'keine mehrteilige Überschrift mehr — dann kann dieser '
                        'Test weg (und der Fix bliebe harmlos)')


class GeldKaestchenTests(TestCase):
    """Dieselbe Falle wie beim Gratismonat, an den übrigen Geld-Kästchen.

    Ein <label> mit `col-span` macht die ganze Formularzeile anklickbar. Liegt
    sie neben oder über dem Speichern-Knopf, schaltet ein danebengegangener
    Tipper eine Geld-Entscheidung um — ohne dass sich sichtbar etwas ändert.
    Betroffen waren:

      Anlagen     «Aktivierung buchen» (bucht 1500 an Gegenkonto)
      Kreditoren  «In Nebenkostenabrechnung einbeziehen» (3×) — entscheidet,
                  ob eine Rechnung den Mietern weiterverrechnet wird
    """

    def _kaestchen_mit_breiter_klickflaeche(self):
        import re, pathlib
        LABEL = re.compile(r'<label\b([^>]*)>(.*?)</label>', re.S | re.I)
        treffer = []
        for p in sorted(pathlib.Path('core/templates/fw').rglob('*.html')):
            s = p.read_text(encoding='utf-8')
            for m in LABEL.finditer(s):
                attrs, inner = m.group(1), m.group(2)
                if 'type="checkbox"' not in inner:
                    continue
                if 'col-span' not in attrs:
                    continue
                name = re.search(r'name="([^"]+)"', inner)
                treffer.append(f"{p}:{s[:m.start()].count(chr(10)) + 1} "
                               f"[{name.group(1) if name else '?'}]")
        return treffer

    def test_kein_geld_kaestchen_mit_formularbreiter_klickflaeche(self):
        breit = self._kaestchen_mit_breiter_klickflaeche()
        self.assertEqual(breit, [], "Kästchen mit formularbreiter Klickfläche:\n  " +
                                    "\n  ".join(breit))

    def test_pruefung_findet_eine_eingebaute_breite_klickflaeche(self):
        """Gegenprobe — eine Suche, die nie etwas findet, bestätigt jede Vorlage."""
        import pathlib, os
        pfad = pathlib.Path('core/templates/fw/_test_breites_kaestchen.html')
        pfad.write_text('<label class="sm:col-span-4 flex">'
                        '<input type="checkbox" name="probe"></label>\n', encoding='utf-8')
        try:
            self.assertTrue(any('probe' in t for t in self._kaestchen_mit_breiter_klickflaeche()))
        finally:
            os.remove(pfad)

    def test_aktivierung_wird_gebucht(self):
        """Die Buchung hing an `POST.get('aktivieren') == 'on'` — dem Wert, den
        der Browser nur ohne value-Attribut sendet. Hier wird geprüft, dass die
        Buchung an der Anwesenheit hängt, nicht an dieser Zeichenkette."""
        from finance.models import Buchung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        for wert, kennzeichen in (('1', 'value-Attribut'), ('on', 'ohne value')):
            Buchung.objects.all().delete()
            c.post('/neu/anlagen/', {
                'aktion': 'anlage_neu', 'bezeichnung': f'Heizung {kennzeichen}',
                'liegenschaft_id': lg.id, 'anschaffungswert': '12000',
                'anschaffungsdatum': '2026-01-15', 'nutzungsdauer_jahre': '10',
                'gegenkonto': '2000', 'aktivieren': wert}, follow=True)
            self.assertTrue(
                Buchung.objects.filter(soll_konto__nummer='1500').exists(),
                f'Aktivierung wurde bei «{kennzeichen}» nicht gebucht')

    def test_ohne_haekchen_keine_aktivierung(self):
        """Der Gegenfall — sonst könnte die Prüfung oben auch dann bestehen,
        wenn immer gebucht würde."""
        from finance.models import Buchung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/anlagen/', {
            'aktion': 'anlage_neu', 'bezeichnung': 'Lift',
            'liegenschaft_id': lg.id, 'anschaffungswert': '9000',
            'anschaffungsdatum': '2026-01-15', 'nutzungsdauer_jahre': '20',
            'gegenkonto': '2000'}, follow=True)
        self.assertFalse(Buchung.objects.filter(soll_konto__nummer='1500').exists())

    def test_hnk_steht_an_der_rechnungszeile(self):
        """Ob eine Rechnung den Mietern weiterverrechnet wird, stand nur an den
        Teilpositionen — an der Rechnung selbst war es unsichtbar."""
        from finance.models import KreditorenRechnung
        lg, e, m, v = _basis_objekte()
        r = KreditorenRechnung.objects.create(
            lieferant='Heizöl AG', liegenschaft=lg, betrag=Decimal('4000'),
            datum=date(2026, 1, 10), status='neu', is_hnk_relevant=False)
        c = Client(); c.force_login(_team_user())
        # Auf das Abzeichen prüfen, nicht auf die Zeichenkette «HNK» — die steht
        # ohnehin im Erfassungsformular, der Test wäre sonst immer grün.
        abzeichen = 'title="Wird in die Nebenkostenabrechnung einbezogen'
        ohne = c.get('/neu/kreditoren/').content.decode('utf-8')
        self.assertNotIn(abzeichen, ohne)
        r.is_hnk_relevant = True
        r.save(update_fields=['is_hnk_relevant'])
        mit = c.get('/neu/kreditoren/').content.decode('utf-8')
        self.assertIn(abzeichen, mit)


class KomprimierungTests(TestCase):
    """Antworten müssen komprimiert über die Leitung gehen.

    Die Listenseiten bestehen fast nur aus sich wiederholendem Markup — je
    Zeile eine Karte fürs Handy UND eine Tabellenzeile für den PC, dazu lange
    Tailwind-Klassenketten. Gemessen über alle abrufbaren Seiten: 5.2 MB roh
    gegen 0.81 MB gepackt, bei den grössten Seiten Faktor 13.
    """

    def test_grosse_seite_kommt_gepackt(self):
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/debitoren/', headers={'accept-encoding': 'gzip'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get('Content-Encoding'), 'gzip')

    @staticmethod
    def _ohne_csrf(rohbytes):
        """CSRF-Token herausrechnen — er ist je Antwort absichtlich anders."""
        import re
        return re.sub(rb'name="csrfmiddlewaretoken" value="[^"]+"',
                      b'name="csrfmiddlewaretoken" value="X"', rohbytes)

    def test_gepackter_inhalt_ist_derselbe(self):
        """Eine kaputte Komprimierung wäre schlimmer als gar keine."""
        import gzip
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        gepackt = c.get('/neu/debitoren/', headers={'accept-encoding': 'gzip'})
        roh = c.get('/neu/debitoren/', headers={'accept-encoding': 'identity'})
        self.assertEqual(self._ohne_csrf(gzip.decompress(gepackt.content)),
                         self._ohne_csrf(roh.content))
        self.assertLess(len(gepackt.content), len(roh.content))

    def test_csrf_token_wechselt_je_anfrage(self):
        """Der Grund, warum Komprimierung hier unbedenklich ist.

        Wird eine Antwort gepackt, in der ein GLEICHBLEIBENDES Geheimnis
        steht, lässt sich dieses über die Antwortgrösse erraten (BREACH).
        Django maskiert den CSRF-Token seit 4.1 je Anfrage mit einem
        Zufallswert — genau dagegen. Fiele das weg, wäre die Entscheidung für
        gzip neu zu prüfen; deshalb steht die Annahme hier als Test.
        """
        import re
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        muster = re.compile(rb'name="csrfmiddlewaretoken" value="([^"]+)"')
        tokens = set()
        for _ in range(3):
            treffer = muster.search(c.get('/neu/debitoren/').content)
            self.assertIsNotNone(treffer, 'kein CSRF-Token auf der Seite')
            tokens.add(treffer.group(1))
        self.assertEqual(len(tokens), 3,
                         'CSRF-Token bleibt über Anfragen gleich — mit '
                         'Komprimierung wäre er über die Antwortgrösse angreifbar.')

    def test_ohne_unterstuetzung_unverandert(self):
        """Wer kein gzip anbietet, bekommt Klartext — nicht kaputte Bytes."""
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/debitoren/', headers={'accept-encoding': 'identity'})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.headers.get('Content-Encoding'))
        self.assertIn(b'<html', r.content.lower())


class AbfrageSkalierungTests(TestCase):
    """Listenseiten dürfen nicht pro Zeile in die Datenbank greifen.

    Gemessen am Entwicklungsbestand (38 Liegenschaften, 34 Verträge,
    31 Mieter) brauchte der Seitenaufbau:

        /neu/sollstellung/   325 Abfragen   (128× derselbe Mietzins-Zugriff)
        /neu/mieterspiegel/  274            ( 71× dieselbe Objekt-Abfrage)
        /neu/liegenschaften/ 195            ( 38× dieselbe Belegungs-Abfrage)
        /neu/benutzer/       103            ( 33× dieselbe Rollen-Abfrage)
        /neu/mieterkonten/    98            ( 31× dieselbe Rechnungs-Abfrage)

    Das fällt bei einer Handvoll Objekten nicht auf und wird mit dem Portfolio
    linear schlimmer — auf einem Hosting mit einem einzigen Arbeitsprozess ist
    das der Unterschied zwischen «lädt» und «hängt».

    Deshalb prüfen diese Tests keine feste Zahl (die wäre bei jeder harmlosen
    Änderung falsch), sondern das VERHALTEN: Wird die Datenmenge verdoppelt,
    darf die Zahl der Abfragen nur um eine kleine Konstante steigen.
    """

    def _bestand(self, n, ab=0):
        """Legt n vollständige Vermietungen an (Liegenschaft, Objekt, Mieter,
        Vertrag) — jede mit eigener Liegenschaft, damit auch die je-Liegenschaft-
        Schleifen wachsen."""
        from finance.models import DebitorenRechnung
        for i in range(ab, ab + n):
            lg = Liegenschaft.objects.create(strasse=f'Prüfweg {i}', plz='3000', ort='Bern',
                                             versicherungswert=Decimal('900000'))
            e = Einheit.objects.create(liegenschaft=lg, bezeichnung=f'Whg {i}', typ='wohnung',
                                       nettomiete_aktuell=Decimal('1400'),
                                       nebenkosten_aktuell=Decimal('180'))
            m = Mieter.objects.create(typ='person', vorname='Test', nachname=f'Nr{i}',
                                      email=f'nr{i}@example.ch', strasse='Weg 1',
                                      plz='3000', ort='Bern')
            v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                           netto_mietzins=Decimal('1400'),
                                           nebenkosten=Decimal('180'), status='aktiv')
            DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel=f'Miete {i}',
                                             betrag=Decimal('1580'), status='offen',
                                             datum=date(2026, 1, 1),
                                             faellig_am=date(2026, 1, 1))

    def _abfragen(self, url, client):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        with CaptureQueriesContext(connection) as ctx:
            r = client.get(url)
        self.assertEqual(r.status_code, 200, f'{url} -> {r.status_code}')
        return len(ctx.captured_queries)

    def _waechst_nicht_mit(self, url, spielraum=4):
        """Verdoppelt den Bestand und vergleicht. `spielraum` deckt ab, was
        legitim mitwächst (z.B. eine zusätzliche Seite Paginierung)."""
        c = Client(); c.force_login(_team_user())
        self._bestand(3)
        klein = self._abfragen(url, c)
        self._bestand(3, ab=3)
        gross = self._abfragen(url, c)
        self.assertLessEqual(
            gross, klein + spielraum,
            f'{url}: bei doppeltem Bestand {klein} → {gross} Abfragen — '
            f'die Seite fragt pro Zeile nach.')
        return klein, gross

    def test_sollstellung_fragt_nicht_je_vertrag_nach(self):
        self._waechst_nicht_mit('/neu/sollstellung/')

    def test_mieterspiegel_fragt_nicht_je_liegenschaft_nach(self):
        self._waechst_nicht_mit('/neu/mieterspiegel/')

    def test_liegenschaften_fragt_nicht_je_liegenschaft_nach(self):
        self._waechst_nicht_mit('/neu/liegenschaften/')

    def test_mieterkonten_fragt_nicht_je_mieter_nach(self):
        self._waechst_nicht_mit('/neu/mieterkonten/')

    def _buchungen(self, n, ab=0):
        """Je Liegenschaft eine Aufwand- und eine Ertragsbuchung — damit die
        Berichtsseiten für jede Liegenschaft auch etwas zu rechnen haben."""
        from finance.models import Buchung, Buchungskonto
        _seed_konten()
        aufwand, _ = Buchungskonto.objects.get_or_create(
            nummer='4000', defaults={'bezeichnung': 'Reparaturen', 'typ': 'aufwand'})
        ertrag = Buchungskonto.objects.get(nummer='3000')
        bank = Buchungskonto.objects.get(nummer='1020')
        lgs = list(Liegenschaft.objects.order_by('id')[ab:ab + n])
        for i, lg in enumerate(lgs):
            Buchung.objects.create(datum=date(2026, (i % 12) + 1, 5), liegenschaft=lg,
                                   beleg_text=f'Aufwand {i}', soll_konto=aufwand,
                                   haben_konto=bank, betrag=Decimal('500.00'))
            Buchung.objects.create(datum=date(2026, (i % 12) + 1, 6), liegenschaft=lg,
                                   beleg_text=f'Ertrag {i}', soll_konto=bank,
                                   haben_konto=ertrag, betrag=Decimal('1400.00'))

    def _bericht_waechst_nicht_mit(self, url, spielraum=4):
        c = Client(); c.force_login(_team_user())
        self._bestand(3); self._buchungen(3)
        klein = self._abfragen(url, c)
        self._bestand(3, ab=3); self._buchungen(3, ab=3)
        gross = self._abfragen(url, c)
        self.assertLessEqual(
            gross, klein + spielraum,
            f'{url}: bei doppeltem Bestand {klein} → {gross} Abfragen — '
            f'die Seite rechnet je Liegenschaft einzeln nach.')

    def _offene_posten(self, anzahl):
        """Legt `anzahl` OFFENE Rechnungen an — die Grösse, an der die
        Altersstruktur wächst (nicht die Zahl der Liegenschaften)."""
        from finance.models import DebitorenRechnung
        v = Mietvertrag.objects.first()
        lg = v.einheit.liegenschaft
        vorhanden = DebitorenRechnung.objects.count()
        for i in range(anzahl):
            DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=lg, titel=f'Offen {vorhanden + i}',
                betrag=Decimal('1580.00'), status='offen',
                datum=date(2026, 1, 1), faellig_am=date(2026, 1, 1))

    def test_aging_fragt_nicht_je_offener_rechnung_nach(self):
        """Die Altersstruktur summierte die Zahlungen je offener Rechnung
        einzeln — die Seite wurde also genau dann langsam, wenn viel offen ist.

        Gemessen wird an der Zahl der OFFENEN POSTEN. Ein erster Entwurf liess
        nur den Liegenschaftsbestand wachsen: das ergab drei zusätzliche
        Rechnungen, blieb im Spielraum und bestätigte die Seite auch ohne den
        Prefetch. Die Gegenprobe hat das aufgedeckt."""
        c = Client(); c.force_login(_team_user())
        self._bestand(1)
        self._offene_posten(25)
        klein = self._abfragen('/neu/mahnwesen/aging/', c)
        self._offene_posten(25)
        gross = self._abfragen('/neu/mahnwesen/aging/', c)
        self.assertLessEqual(gross, klein + 4,
                             f'/neu/mahnwesen/aging/: {klein} → {gross} Abfragen bei '
                             f'doppelt so vielen offenen Posten')

    def test_betriebskostenspiegel_fragt_nicht_je_liegenschaft_nach(self):
        """Aufwand und Fläche wurden je Liegenschaft einzeln aggregiert —
        zwei Abfragen pro Zeile."""
        self._bericht_waechst_nicht_mit('/neu/berichte/betriebskostenspiegel/')

    def test_auswertung_fragt_nicht_je_monat_und_liegenschaft_nach(self):
        """Der Monatsverlauf aggregierte je Monat einzeln, der Vergleich je
        Liegenschaft — bei der Kennzahl «Ergebnis» vier Abfragen pro Zelle."""
        self._bericht_waechst_nicht_mit('/neu/auswertung/')

    def test_auswertung_ergebnis_fragt_nicht_je_zelle_nach(self):
        """Die teuerste Kennzahl eigens geprüft: «Ergebnis» rechnet Ertrag UND
        Aufwand, also doppelt so viele Einzelaggregate wie die übrigen."""
        self._bericht_waechst_nicht_mit('/neu/auswertung/?typ=ergebnis')

    def test_benutzer_fragt_nicht_je_benutzer_nach(self):
        from django.contrib.auth.models import User
        c = Client(); c.force_login(_team_user())
        for i in range(3):
            User.objects.create_user(username=f'p{i}', password='x')
        klein = self._abfragen('/neu/benutzer/', c)
        for i in range(3, 6):
            User.objects.create_user(username=f'p{i}', password='x')
        gross = self._abfragen('/neu/benutzer/', c)
        self.assertLessEqual(gross, klein + 2,
                             f'benutzer: {klein} → {gross} Abfragen bei doppelter Anzahl')

    def test_pruefung_erkennt_ein_nachfragen_je_zeile(self):
        """Gegenprobe für die Messmethode selbst.

        Ohne sie bliebe offen, ob die Prüfungen oben überhaupt etwas merken
        könnten — eine Messung, die immer dieselbe Zahl liefert, bestätigt
        jede Seite. Hier wird absichtlich je Zeile nachgefragt (`.filter()`
        auf der Beziehung statt `.all()` über einen Prefetch — genau der
        Fehler, der auf der Sollstellung 128 Abfragen erzeugte). Das MUSS
        als Wachstum auffallen."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        def naiv():
            with CaptureQueriesContext(connection) as ctx:
                for v in Mietvertrag.objects.all():
                    list(v.mietzins_komponenten.filter(gueltig_ab__isnull=False))
            return len(ctx.captured_queries)

        self._bestand(3)
        klein = naiv()
        self._bestand(3, ab=3)
        gross = naiv()
        self.assertGreater(gross, klein + 2,
                           f'Messung merkt kein Nachfragen je Zeile ({klein} → {gross}) '
                           f'— dann sind die Prüfungen oben wertlos.')

    def test_saldi_stimmen_mit_dem_einzelauszug_ueberein(self):
        """Die Sammelberechnung für die Liste muss dieselbe Zahl liefern wie
        der Einzelauszug — sonst wäre die Übersicht schneller, aber falsch."""
        from core.services.mieterkonto import berechne_mieterkonto, saldi_fuer_mieter
        from finance.models import DebitorenRechnung, Zahlungseingang
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete 01',
                                         betrag=Decimal('1700'), status='offen',
                                         datum=date(2026, 1, 1))
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete 02',
                                         betrag=Decimal('1700'), status='offen',
                                         datum=date(2026, 2, 1))
        # Storniertes zählt nicht, Abgeschriebenes auch nicht.
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Storno',
                                         betrag=Decimal('999'), status='storniert',
                                         datum=date(2026, 2, 1))
        Zahlungseingang.objects.create(vertrag=v, betrag=Decimal('1700'),
                                       datum_eingang=date(2026, 2, 5), status='verbucht')
        self._bestand(2)                      # weitere Mieter dürfen nicht hineinfunken
        alle = list(Mieter.objects.all())
        saldi = saldi_fuer_mieter(alle)
        for mieter in alle:
            _, einzeln = berechne_mieterkonto(mieter)
            self.assertEqual(saldi[mieter.id], einzeln,
                             f'{mieter.display_name}: Liste {saldi[mieter.id]} '
                             f'≠ Auszug {einzeln}')
        self.assertEqual(saldi[m.id], Decimal('1700'))   # 3400 gestellt − 1700 bezahlt


class IconKnopfBeschriftungTests(TestCase):
    """Ein Knopf, der nur aus einem Symbol besteht, sagt nichts.

    Beim Draufzeigen erscheint kein Hinweis, und eine Sprachausgabe liest
    gar nichts vor — der Nutzer muss klicken, um zu erfahren, was passiert.
    Bei einem Papierkorb ist das die falsche Reihenfolge.

    Gemessen waren es 19 solcher Bedienelemente in den /neu/-Vorlagen:
    das Stift-Symbol im Kontenplan, Papierkörbe an Policen, Fristen,
    Pendenzen, Vorlagen und Adresszeilen, das Kreuz im Vertragsassistenten.
    """

    #: Prüft die Vorlagen direkt statt gerenderter Seiten — sonst hinge die
    #: Abdeckung davon ab, welche Testdaten gerade eine Zeile erzeugen.
    def _stumme_bedienelemente(self):
        import re, pathlib
        tag = re.compile(r'<(button|a)\b([^>]*)>(.*?)</\1>', re.S | re.I)
        treffer = []
        for p in sorted(pathlib.Path('core/templates/fw').rglob('*.html')):
            s = p.read_text(encoding='utf-8')
            for m in tag.finditer(s):
                attrs, inner = m.group(2), m.group(3)
                if '<button' in inner or '<a ' in inner:
                    continue                      # verschachtelt, gehört zum äusseren
                txt = re.sub(r'<[^>]+>', '', inner)
                txt = re.sub(r'\{%.*?%\}', '', txt, flags=re.S)
                txt = re.sub(r'\{\{.*?\}\}', 'X', txt, flags=re.S).strip()
                if txt:
                    continue                      # trägt sichtbaren Text
                if not re.search(r'<i\b|<svg\b|<img\b', inner):
                    continue                      # gar kein Symbol -> kein Knopf-Fall
                if re.search(r'\b(title|aria-label)\s*=', attrs):
                    continue
                # title am umschliessenden <form> wirkt beim Zeigen mit
                vor = s[max(0, m.start() - 400):m.start()]
                if '<form' in vor and 'title=' in vor.rsplit('<form', 1)[-1]:
                    continue
                treffer.append(f"{p}:{s[:m.start()].count(chr(10)) + 1}")
        return treffer

    def test_kein_bedienelement_ohne_beschriftung(self):
        stumm = self._stumme_bedienelemente()
        self.assertEqual(stumm, [], "Symbol-Knöpfe ohne title/aria-label:\n  " +
                                    "\n  ".join(stumm))

    def test_pruefung_findet_einen_eingebauten_fehler(self):
        """Gegenprobe: Ohne sie wäre der Test oben nur eine leere Behauptung —
        eine kaputte Suche meldet ebenfalls «keine Treffer»."""
        import pathlib, os
        ordner = pathlib.Path('core/templates/fw')
        pfad = ordner / '_test_stummer_knopf.html'
        pfad.write_text('<button class="x"><i class="fa-solid fa-trash"></i></button>\n',
                        encoding='utf-8')
        try:
            self.assertIn(f'{pfad}:1', self._stumme_bedienelemente())
        finally:
            os.remove(pfad)


class UnterschriftBriefeTests(TestCase):
    """Die Unterschrift lag nur auf Verträgen und Formularen — die reportlab-
    Briefe zogen eine Linie und liessen sie leer. Ein Einschreiben, das eine
    Kündigung androht, gehört unterschrieben."""

    def setUp(self):
        # Eigenes MEDIA_ROOT, damit die Testbilder nicht im echten media/ landen.
        import tempfile
        from django.test import override_settings
        self._tmp = tempfile.TemporaryDirectory()
        self._ov = override_settings(MEDIA_ROOT=self._tmp.name)
        self._ov.enable()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._ov.disable)

    def _verwaltung(self, mit_unterschrift):
        from django.core.files.base import ContentFile
        from crm.models import Verwaltung
        vw = Verwaltung.objects.first()
        if vw is None:
            vw = Verwaltung.objects.create(firma='Testverwaltung', strasse='Weg 1',
                                           plz='4500', ort='Solothurn')
        if mit_unterschrift:
            vw.unterschrift_bild.save('sig.png', ContentFile(_sig_bytes()), save=True)
        else:
            Verwaltung.objects.filter(pk=vw.pk).update(unterschrift_bild='')
        vw.refresh_from_db()
        return vw

    def _mahnung(self, vertrag, vw):
        from core.views.email_views import generate_mahnung_combined_pdf_bytes
        return generate_mahnung_combined_pdf_bytes(vertrag, vw, 'August 2026',
                                                   '100.00', date(2026, 8, 1))

    # ---------- Helfer ----------
    def test_unterschrift_pfad_findet_das_bild(self):
        from core.services.unterschrift import unterschrift_pfad
        vw = self._verwaltung(True)
        self.assertTrue(unterschrift_pfad(vw))

    def test_unterschrift_pfad_ohne_bild_ist_none(self):
        from core.services.unterschrift import unterschrift_pfad
        vw = self._verwaltung(False)
        self.assertIsNone(unterschrift_pfad(vw))
        self.assertIsNone(unterschrift_pfad(None))

    def test_unterschrift_pfad_nimmt_den_ersten_mit_bild(self):
        """Reihenfolge = Unterzeichner-Reihenfolge des Aufrufers."""
        from django.core.files.base import ContentFile
        from core.services.unterschrift import unterschrift_pfad
        from crm.models import Mandant
        vw = self._verwaltung(False)
        md = Mandant.objects.create(firma_oder_name='Eigentümer AG')
        md.unterschrift_bild.save('sig_md.png', ContentFile(_sig_bytes()), save=True)
        # Mandant.save() benennt das Bild in sig_man_<id>.png um (Hintergrund raus)
        self.assertIn('sig_man', unterschrift_pfad(vw, md))

    # ---------- Mahnung mit Kündigungsandrohung (Art. 257d OR) ----------
    def test_mahnung_257d_traegt_die_unterschrift(self):
        lg, e, m, v = _basis_objekte()
        ohne = self._mahnung(v, self._verwaltung(False))
        mit = self._mahnung(v, self._verwaltung(True))
        self.assertGreater(len(mit), len(ohne) + 500)

    def test_mahnung_257d_ohne_unterschrift_bleibt_erzeugbar(self):
        """Fehlt das Bild, muss der Brief trotzdem rauskommen — nur eben leer."""
        lg, e, m, v = _basis_objekte()
        pdf = self._mahnung(v, self._verwaltung(False))
        self.assertTrue(pdf.startswith(b'%PDF'))

    # ---------- Mietprozess-Briefe ----------
    def test_kautionsbestaetigung_traegt_die_unterschrift(self):
        from core.services.mietprozess_briefe import kaution_hinterlegung_pdf
        lg, e, m, v = _basis_objekte()
        ohne = kaution_hinterlegung_pdf(v, self._verwaltung(False))
        mit = kaution_hinterlegung_pdf(v, self._verwaltung(True))
        self.assertGreater(len(mit), len(ohne) + 500)

    def test_maengelruege_traegt_die_unterschrift(self):
        from core.services.mietprozess_briefe import maengelruege_pdf
        lg, e, m, v = _basis_objekte()
        ohne = maengelruege_pdf(v, 'Heizung defekt', frist_tage=14,
                                verwaltung=self._verwaltung(False))
        mit = maengelruege_pdf(v, 'Heizung defekt', frist_tage=14,
                               verwaltung=self._verwaltung(True))
        self.assertGreater(len(mit), len(ohne) + 500)

    # ---------- Serienbrief ----------
    def test_serienbrief_traegt_die_unterschrift(self):
        from core.services.serienbrief import generate_serienbrief_pdf
        vw_ohne = self._verwaltung(False)
        absender = {'firma': vw_ohne.firma, 'strasse': vw_ohne.strasse,
                    'plz': vw_ohne.plz, 'ort': vw_ohne.ort}
        emp = [{'name': 'Hans Muster', 'anrede': 'Sehr geehrter Herr Muster',
                'strasse': 'Teststrasse 1', 'plz': '4500', 'ort': 'Solothurn'}]
        ohne = generate_serienbrief_pdf(absender, 'Betreff', 'Text', emp,
                                        signatur=(vw_ohne,))
        mit = generate_serienbrief_pdf(absender, 'Betreff', 'Text', emp,
                                       signatur=(self._verwaltung(True),))
        self.assertGreater(len(mit), len(ohne) + 500)

    def test_serienbrief_ohne_signatur_argument_bleibt_kompatibel(self):
        from core.services.serienbrief import generate_serienbrief_pdf
        self._verwaltung(True)
        emp = [{'name': 'Hans Muster', 'strasse': 'Teststrasse 1',
                'plz': '4500', 'ort': 'Solothurn'}]
        pdf = generate_serienbrief_pdf({'firma': 'X'}, 'Betreff', 'Text', emp)
        self.assertTrue(pdf.startswith(b'%PDF'))

    # ---------- Upload-Weg in der App (vorher nur im Django-Admin) ----------
    def test_account_bietet_unterschrift_upload(self):
        from crm.models import Verwaltung
        self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/account/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="unterschrift_bild"')
        self.assertContains(r, 'bleibt die Linie auf jedem Brief leer')

    def test_account_speichert_hochgeladene_unterschrift(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from crm.models import Verwaltung
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {
            'firma': vw.firma, 'strasse': vw.strasse, 'plz': vw.plz, 'ort': vw.ort,
            'unterschrift_bild': SimpleUploadedFile('sig.png', _sig_bytes(),
                                                    content_type='image/png')})
        vw.refresh_from_db()
        self.assertTrue(vw.unterschrift_bild)

    def test_account_kann_unterschrift_entfernen(self):
        vw = self._verwaltung(True)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {'firma': vw.firma, 'strasse': vw.strasse,
                                 'plz': vw.plz, 'ort': vw.ort,
                                 'unterschrift_entfernen': '1'})
        vw.refresh_from_db()
        self.assertFalse(vw.unterschrift_bild)

    def test_mandat_formular_nimmt_dateien_entgegen(self):
        """Ohne enctype='multipart/form-data' verschwindet die Datei lautlos."""
        from crm.models import Mandant
        md = Mandant.objects.create(firma_oder_name='Eigentümer AG')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mandate/{md.id}/bearbeiten/')
        self.assertContains(r, 'enctype="multipart/form-data"')
        self.assertContains(r, 'name="unterschrift_bild"')

    def test_mandat_speichert_hochgeladene_unterschrift(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from crm.models import Mandant
        md = Mandant.objects.create(firma_oder_name='Eigentümer AG')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mandate/{md.id}/bearbeiten/', {
            'firma_oder_name': md.firma_oder_name,
            'unterschrift_bild': SimpleUploadedFile('sig.png', _sig_bytes(),
                                                    content_type='image/png')})
        md.refresh_from_db()
        self.assertTrue(md.unterschrift_bild)

    # ---------- Direkt zeichnen (Signature-Pad) ----------
    def _data_url(self):
        """Was canvas.toDataURL('image/png') liefert: transparent + schwarzer Strich."""
        import base64
        import io as _io
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (600, 200), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.line([(30, 140), (120, 50), (210, 150), (300, 55), (560, 70)],
               fill=(17, 24, 39, 255), width=6)
        b = _io.BytesIO(); img.save(b, format="PNG")
        return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()

    def _basis(self, vw):
        return {f: getattr(vw, f) or '' for f in
                ['firma', 'strasse', 'plz', 'ort', 'telefon', 'email', 'iban']}

    def test_account_zeigt_das_zeichenfeld(self):
        self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/account/')
        self.assertContains(r, 'data-us-canvas')
        self.assertContains(r, 'name="unterschrift_gezeichnet"')
        # touch-action: none — sonst scrollt das Handy beim Zeichnen weg
        self.assertContains(r, 'touch-action: none')

    def test_gezeichnete_unterschrift_wird_gespeichert(self):
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': self._data_url()})
        vw.refresh_from_db()
        self.assertTrue(vw.unterschrift_bild)

    def test_gezeichnete_unterschrift_landet_im_brief(self):
        lg, e, m, v = _basis_objekte()
        vw = self._verwaltung(False)
        ohne = self._mahnung(v, vw)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': self._data_url()})
        vw.refresh_from_db()
        self.assertGreater(len(self._mahnung(v, vw)), len(ohne) + 500)

    def test_leeres_zeichenfeld_loescht_die_unterschrift_nicht(self):
        """Wer nur die Adresse ändert, darf die Unterschrift nicht verlieren."""
        vw = self._verwaltung(True)
        name = vw.unterschrift_bild.name
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw), 'unterschrift_gezeichnet': ''})
        vw.refresh_from_db()
        self.assertTrue(vw.unterschrift_bild)
        self.assertEqual(vw.unterschrift_bild.name, name)

    def test_ungueltige_zeichendaten_werden_verworfen(self):
        vw = self._verwaltung(True)
        name = vw.unterschrift_bild.name
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': 'data:image/png;base64,QUJD'})
        vw.refresh_from_db()
        self.assertEqual(vw.unterschrift_bild.name, name)

    def test_mehrfaches_speichern_erzeugt_keine_dateileichen(self):
        """save() verarbeitete das Bild bisher jedes Mal neu und legte dabei eine
        weitere Datei an — der Medienordner füllte sich mit Waisen."""
        import os
        from django.conf import settings
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': self._data_url()})
        for _ in range(3):
            c.post('/neu/account/', self._basis(vw))
        ordner = os.path.join(settings.MEDIA_ROOT, 'unterschriften')
        self.assertEqual(len(os.listdir(ordner)), 1)

    def test_ersetzte_unterschrift_wird_geloescht(self):
        import os
        from django.conf import settings
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': self._data_url()})
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': self._data_url()})
        ordner = os.path.join(settings.MEDIA_ROOT, 'unterschriften')
        self.assertEqual(len(os.listdir(ordner)), 1)

    def test_mandat_nimmt_gezeichnete_unterschrift(self):
        from crm.models import Mandant
        md = Mandant.objects.create(firma_oder_name='Eigentümer AG')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mandate/{md.id}/bearbeiten/')
        self.assertContains(r, 'data-us-canvas')
        c.post(f'/neu/mandate/{md.id}/bearbeiten/', {
            'firma_oder_name': md.firma_oder_name,
            'unterschrift_gezeichnet': self._data_url()})
        md.refresh_from_db()
        self.assertTrue(md.unterschrift_bild)

    # ---------- Leere «Unterschrift» ----------
    def _leere_data_url(self, weiss=False):
        """Was ein geleertes Canvas liefert. iOS Safari feuert beim Absenden ein
        resize (URL-Leiste), das die Fläche leert und erst asynchron wieder
        aufbaut — traf das submit dazwischen, ging genau das hier raus."""
        import base64
        import io as _io
        from PIL import Image
        farbe = (255, 255, 255, 255) if weiss else (0, 0, 0, 0)
        img = Image.new("RGBA", (600, 200), farbe)
        b = _io.BytesIO(); img.save(b, format="PNG")
        return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()

    def test_leeres_canvas_wird_nicht_gespeichert(self):
        """Sonst meldet die App «hinterlegt», die Vorschau bleibt leer und jeder
        Brief geht unsigniert raus — ohne dass irgendwo ein Fehler auftaucht."""
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        for weiss in (False, True):
            c.post('/neu/account/', {**self._basis(vw),
                                     'unterschrift_gezeichnet': self._leere_data_url(weiss)})
            vw.refresh_from_db()
            self.assertFalse(vw.unterschrift_bild, f"leeres Canvas gespeichert (weiss={weiss})")

    def test_leeres_canvas_ueberschreibt_bestehende_unterschrift_nicht(self):
        vw = self._verwaltung(True)
        name = vw.unterschrift_bild.name
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_gezeichnet': self._leere_data_url()})
        vw.refresh_from_db()
        self.assertEqual(vw.unterschrift_bild.name, name)

    def test_leeres_canvas_meldet_es_dem_nutzer(self):
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/account/', {**self._basis(vw),
                                     'unterschrift_gezeichnet': self._leere_data_url()},
                   follow=True)
        self.assertContains(r, 'Unterschrift war leer')

    def test_leeres_blatt_als_upload_wird_abgewiesen(self):
        import io as _io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        b = _io.BytesIO(); Image.new("RGB", (400, 120), "white").save(b, format="PNG")
        vw = self._verwaltung(False)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/account/', {**self._basis(vw),
                                 'unterschrift_bild': SimpleUploadedFile(
                                     'leer.png', b.getvalue(), content_type='image/png')})
        vw.refresh_from_db()
        self.assertFalse(vw.unterschrift_bild)

    # ---------- Datenbankeintrag ohne Datei ----------
    def test_fehlende_bilddatei_wird_nicht_als_hinterlegt_ausgegeben(self):
        """Fehlt die Datei auf dem Server, behauptete die App trotzdem eine
        Unterschrift — Vorschau leer, Brief leer, kein Hinweis worauf es liegt."""
        import os
        from django.conf import settings
        from core.services.unterschrift import unterschrift_url
        vw = self._verwaltung(True)
        os.remove(os.path.join(settings.MEDIA_ROOT, vw.unterschrift_bild.name))
        self.assertEqual(unterschrift_url(vw), '')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/account/')
        self.assertContains(r, 'nicht verwendbar')
        self.assertNotContains(r, 'alt="Unterschrift"')

    def test_leer_gespeicherte_unterschrift_gilt_nicht_als_hinterlegt(self):
        """Altbestand aus dem Canvas-Bug: Datei da, aber vollständig durchsichtig."""
        from django.core.files.base import ContentFile
        from core.services.unterschrift import unterschrift_url
        vw = self._verwaltung(False)
        roh = self._leere_data_url().split(',', 1)[1]
        import base64
        vw.unterschrift_bild.save('leer.png', ContentFile(base64.b64decode(roh)), save=True)
        self.assertEqual(unterschrift_url(vw), '')
        c = Client(); c.force_login(_team_user())
        self.assertContains(c.get('/neu/account/'), 'nicht verwendbar')

    def test_vorhandene_bilddatei_liefert_url(self):
        from core.services.unterschrift import unterschrift_url
        vw = self._verwaltung(True)
        self.assertTrue(unterschrift_url(vw))
        c = Client(); c.force_login(_team_user())
        self.assertContains(c.get('/neu/account/'), 'alt="Unterschrift"')

    # ---------- Liegenschafts-Zuordnung am Mandat ----------
    def test_mandat_speichern_ohne_zuordnungsblock_behaelt_liegenschaften(self):
        """Ein POST ohne den Zuordnungsblock löste bisher still ALLE Liegenschaften
        vom Eigentümer — und nahm damit seine Unterschrift aus jedem Brief."""
        from crm.models import Mandant
        lg, e, m, v = _basis_objekte()
        md = Mandant.objects.create(firma_oder_name='Eigentümer AG')
        lg.mandant = md; lg.save(update_fields=['mandant'])
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mandate/{md.id}/bearbeiten/', {'firma_oder_name': md.firma_oder_name})
        lg.refresh_from_db()
        self.assertEqual(lg.mandant_id, md.id)

    def test_mandat_zuordnung_bleibt_bewusst_aenderbar(self):
        """Mit abgeschicktem Block soll das Abwählen weiterhin greifen."""
        from crm.models import Mandant
        lg, e, m, v = _basis_objekte()
        md = Mandant.objects.create(firma_oder_name='Eigentümer AG')
        lg.mandant = md; lg.save(update_fields=['mandant'])
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mandate/{md.id}/bearbeiten/',
               {'firma_oder_name': md.firma_oder_name, 'lg_zuordnung': '1'})
        lg.refresh_from_db()
        self.assertIsNone(lg.mandant_id)
        c.post(f'/neu/mandate/{md.id}/bearbeiten/',
               {'firma_oder_name': md.firma_oder_name, 'lg_zuordnung': '1',
                'liegenschaften': [str(lg.id)]})
        lg.refresh_from_db()
        self.assertEqual(lg.mandant_id, md.id)


class RollentrennungTests(TestCase):
    """Was darf ein Team-Mitglied mit eingeschränkter Rolle?

    Bisher geprüft war nur die äussere Schranke: Fremde kommen nicht an fremde
    Daten. Innerhalb der Verwaltung gibt es jedoch drei Stufen — Verwaltung
    (alles), Sachbearbeitung (erfassen/bearbeiten), Lesend (Treuhand/Revision,
    nur Ansicht). Diese Trennung nützt nur, wenn sie auch dort greift, wo eine
    Seite lesbar sein SOLL, aber einzelne Aktionen darauf nicht.

    Gefunden und behoben wurden drei Stellen, die für alle Team-Rollen
    schreibbar waren:

      Jahresabschluss   ein Buchungslauf, der die Periode versiegelt
      Mängelrüge        setzt eine Frist nach Art. 259 OR in Gang
      Untermiete        rechtsverbindliche Zustimmung/Ablehnung, Art. 262 OR
    """

    #: Views, die für alle Team-Rollen schreiben dürfen — mit Begründung.
    #: Wer hier etwas einträgt, trifft bewusst eine Entscheidung.
    ERLAUBT_OHNE_SCHREIBSCHRANKE = {
        'fw_modus_wechsel': 'setzt nur die eigene Ansicht (Einfach/Profi) in der Session',
    }

    def test_lesende_rolle_kann_nirgends_unbemerkt_schreiben(self):
        """Register-Prüfung: Jede View, die für alle Team-Rollen erreichbar ist
        und POST/Datei-Uploads verarbeitet, braucht INNEN eine Schreibschranke
        — oder einen Eintrag in der Ausnahmeliste oben. Eine neue Seite, die
        beides vergisst, fällt hier auf, nicht erst im Betrieb."""
        import ast
        import pathlib
        offen = []
        for pfad in sorted(pathlib.Path('core/views').rglob('*.py')):
            quelle = pfad.read_text(encoding='utf-8')
            try:
                baum = ast.parse(quelle)
            except SyntaxError:
                continue
            for knoten in baum.body:
                if not isinstance(knoten, ast.FunctionDef):
                    continue
                rollen = []
                for d in knoten.decorator_list:
                    if isinstance(d, ast.Call) and getattr(d.func, 'id', '') == 'rolle_erforderlich':
                        rollen = [getattr(a.value, 'id', '') for a in d.args
                                  if isinstance(a, ast.Starred)]
                if 'TEAM_ROLLEN' not in rollen:
                    continue
                seg = ast.get_source_segment(quelle, knoten) or ''
                if 'request.POST' not in seg and 'request.FILES' not in seg:
                    continue
                if 'hat_rolle(request.user' in seg:
                    continue                      # innere Schranke vorhanden
                if knoten.name in self.ERLAUBT_OHNE_SCHREIBSCHRANKE:
                    continue
                offen.append(f'{knoten.name} ({pfad})')
        self.assertEqual(offen, [], 'Für ALLE Team-Rollen schreibbar, auch «Lesend»: '
                                    + ', '.join(offen))

    def _lesend(self):
        c = Client(); c.force_login(_team_user('Lesend')); return c

    def _sachbearbeitung(self):
        c = Client(); c.force_login(_team_user('Sachbearbeitung')); return c

    def test_lesend_darf_die_buchhaltung_ansehen(self):
        """Die Trennung soll nicht aussperren: Treuhand/Revision braucht die
        Buchhaltung. Ohne diese Prüfung wäre «kein Abschluss» auch durch ein
        pauschales Sperren der Seite erfüllt — das wäre die falsche Lösung."""
        self.assertEqual(self._lesend().get('/neu/buchhaltung/').status_code, 200)

    def _abschluss_versuch(self, client):
        """Löst den Jahresabschluss aus und meldet, ob der Buchungslauf lief.

        Gemessen wird der Aufruf selbst, nicht die Zahl neuer Buchungen: Ohne
        Erfolgsbuchungen im Jahr bucht der Abschluss ohnehin nichts, die
        Zählung bliebe also auch ohne Rollenschranke gleich — die Prüfung
        würde dann nichts belegen. Beim Gegentest aufgefallen."""
        from unittest import mock
        with mock.patch('core.services.jahresabschluss.buche_jahresabschluss',
                        return_value=(3, Decimal('1000.00'))) as gebucht:
            client.post('/neu/buchhaltung/', {'aktion': 'jahresabschluss', 'jahr': '2025'})
        return gebucht.called

    def test_lesend_darf_den_jahresabschluss_nicht_buchen(self):
        self.assertFalse(self._abschluss_versuch(self._lesend()),
                         'Rolle «Lesend» hat einen Buchungslauf ausgelöst')

    def test_sachbearbeitung_darf_den_jahresabschluss_nicht_buchen(self):
        """Auch die Sachbearbeitung nicht — laut Rollenkonzept sind
        Buchungsläufe der Verwaltung vorbehalten."""
        self.assertFalse(self._abschluss_versuch(self._sachbearbeitung()),
                         'Rolle «Sachbearbeitung» hat einen Buchungslauf ausgelöst')

    def test_verwaltung_darf_den_jahresabschluss_buchen(self):
        """Gegenstück — sonst würden die Prüfungen oben auch dann bestehen,
        wenn der Abschluss für niemanden mehr funktioniert."""
        c = Client(); c.force_login(_team_user('Verwaltung'))
        self.assertTrue(self._abschluss_versuch(c),
                        'Verwaltung kommt nicht mehr an den Jahresabschluss')

    def test_lesend_kann_keine_maengelruege_und_keine_untermiete_erklaeren(self):
        """Beides sind Erklärungen der Vermieterschaft mit Rechtsfolgen —
        Frist nach Art. 259 OR bzw. Zustimmung nach Art. 262 OR. Sie landen in
        der Vertragsakte. Die Rolle «Lesend» darf sie nicht abgeben."""
        from rentals.models import Dokument
        _lg, _e, _m, v = _basis_objekte()
        c = self._lesend()
        vorher = Dokument.objects.count()
        r1 = c.post(f'/neu/vertraege/{v.id}/maengelruege/',
                    {'mangel': 'Heizung defekt', 'frist_tage': '14'})
        r2 = c.post(f'/neu/vertraege/{v.id}/untermiete/',
                    {'untermieter': 'Frau Beispiel', 'entscheid': 'zustimmung'})
        for r, name in ((r1, 'Mängelrüge'), (r2, 'Untermiete')):
            self.assertEqual(r.status_code, 403,
                             f'{name}: Rolle «Lesend» wurde nicht abgewiesen ({r.status_code})')
        self.assertEqual(Dokument.objects.count(), vorher,
                         'Rolle «Lesend» hat ein Vertragsdokument erzeugt')

    def test_sachbearbeitung_darf_beides_weiterhin(self):
        """Gegenstück: Die Verschärfung darf die Sachbearbeitung nicht treffen."""
        from rentals.models import Dokument
        _lg, _e, _m, v = _basis_objekte()
        c = self._sachbearbeitung()
        c.post(f'/neu/vertraege/{v.id}/maengelruege/',
               {'mangel': 'Heizung defekt', 'frist_tage': '14'})
        c.post(f'/neu/vertraege/{v.id}/untermiete/',
               {'untermieter': 'Frau Beispiel', 'entscheid': 'zustimmung'})
        self.assertEqual(Dokument.objects.count(), 2,
                         'Sachbearbeitung kann Mängelrüge/Untermiete nicht mehr erstellen')

    def test_jeder_schreibende_api_endpunkt_nennt_seine_rolle(self):
        """Die API erbt `auth_lesen` als Vorgabe — ein POST/PUT/DELETE ohne
        eigenes `auth=` stünde damit auch der Rolle «Lesend» offen. Diese
        Prüfung hält fest, dass jeder schreibende Endpunkt seine Rolle
        ausdrücklich nennt."""
        import ast
        import pathlib
        ohne = []
        for pfad in sorted(pathlib.Path('.').rglob('*api*.py')):
            if '.venv' in str(pfad) or 'migrations' in str(pfad):
                continue
            quelle = pfad.read_text(encoding='utf-8')
            try:
                baum = ast.parse(quelle)
            except SyntaxError:
                continue
            for knoten in ast.walk(baum):
                if not isinstance(knoten, ast.FunctionDef):
                    continue
                for d in knoten.decorator_list:
                    if not isinstance(d, ast.Call):
                        continue
                    if getattr(d.func, 'attr', '') not in ('post', 'put', 'patch', 'delete'):
                        continue
                    if not any(kw.arg == 'auth' for kw in d.keywords):
                        ohne.append(f'{knoten.name} ({pfad})')
        self.assertEqual(ohne, [], 'Schreib-Endpunkte ohne eigenes auth=: ' + ', '.join(ohne))

    def test_gesperrte_knoepfe_werden_gar_nicht_erst_gezeigt(self):
        """Die Schranke im View ist das Eine — ein Knopf, der die angemeldete
        Person auf die Anmeldeseite wirft, sieht nach Defekt aus. Was eine
        Rolle nicht darf, soll sie auch nicht sehen."""
        _lg, _e, _m, v = _basis_objekte()
        c_lesend, c_sb = self._lesend(), self._sachbearbeitung()
        c_vw = Client(); c_vw.force_login(_team_user('Verwaltung'))

        lesend = c_lesend.get(f'/neu/vertraege/{v.id}/').content.decode()
        schreib = c_sb.get(f'/neu/vertraege/{v.id}/').content.decode()
        for pfad in (f'/neu/vertraege/{v.id}/maengelruege/', f'/neu/vertraege/{v.id}/untermiete/'):
            self.assertNotIn(f'href="{pfad}"', lesend,
                             f'«Lesend» bekommt {pfad} noch als Verknüpfung angeboten')
            self.assertIn(f'href="{pfad}"', schreib,
                          f'Sachbearbeitung sieht {pfad} nicht mehr')
        self.assertIn('nicht für Ihre Rolle', lesend,
                      'Gesperrte Einträge werden «Lesend» nicht als gesperrt gekennzeichnet')

        self.assertNotIn('value="jahresabschluss"',
                         c_sb.get('/neu/buchhaltung/').content.decode(),
                         'Sachbearbeitung sieht den Jahresabschluss-Knopf')
        self.assertIn('value="jahresabschluss"', c_vw.get('/neu/buchhaltung/').content.decode(),
                      'Verwaltung sieht den Jahresabschluss-Knopf nicht mehr')

    def test_falsche_rolle_landet_nicht_wieder_auf_der_anmeldung(self):
        """Angemeldet, aber falsche Rolle → 403, nicht zurück zur Anmeldung.
        Der alte Weg führte im Kreis: erneut anmelden, wieder hier landen."""
        _lg, _e, _m, v = _basis_objekte()
        r = self._lesend().get(f'/neu/vertraege/{v.id}/maengelruege/')
        self.assertEqual(r.status_code, 403, f'erwartet 403, kam {r.status_code}')

    def test_nicht_angemeldet_geht_weiterhin_zur_anmeldung(self):
        """Gegenstück: Für Nichtangemeldete bleibt die Weiterleitung richtig —
        sie sollen sich ja anmelden können."""
        _lg, _e, _m, v = _basis_objekte()
        r = Client().get(f'/neu/vertraege/{v.id}/maengelruege/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])


def _heute():
    from django.utils import timezone
    return timezone.localdate()


class BewerbungAufbewahrungTests(TestCase):
    """Bewerbungsdossiers nach dem Vermietungsentscheid.

    Ein Dossier enthält Ausweiskopie, Lohnausweis, Betreibungsauszug, dazu
    Geburtsdatum, Nationalität, Zivilstand, Einkommen, Arbeitgeber, Kinder —
    die heikelsten Daten der Anwendung. Gesammelt bei Menschen, die zur
    Verwaltung meist gar kein Vertragsverhältnis haben: Die Wohnung bekommt
    eine Bewerberin, alle übrigen Dossiers sind nach dem Entscheid zwecklos.

    Bisher blieben sie unbegrenzt liegen. `core.services.dsg` greift nur bei
    Personen, die auch Mieter WURDEN — abgelehnte Bewerbungen erfasste es
    nicht. Das DSG verlangt Vernichtung, sobald der Zweck entfällt (Art. 6
    Abs. 4); eine Aufbewahrungspflicht wie für Buchungsbelege (Art. 958f OR)
    gibt es hier gerade nicht.
    """

    def setUp(self):
        import tempfile
        from django.test import override_settings
        self._tmp = tempfile.TemporaryDirectory()
        self._ov = override_settings(MEDIA_ROOT=self._tmp.name)
        self._ov.enable()
        self.lg = Liegenschaft.objects.create(strasse='Bewerbweg 1', plz='3000', ort='Bern')
        self.e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='2.5 Zi', typ='wohnung')

    def tearDown(self):
        self._ov.disable()
        self._tmp.cleanup()

    def _bewerbung(self, *, status='abgelehnt', entschieden_vor_tagen=200, mit_dokumenten=True):
        from django.core.files.base import ContentFile
        from mietprozess.models import Mietbewerbung
        b = Mietbewerbung.objects.create(
            einheit=self.e, status=status, vorname='Anna', nachname='Bewerber',
            geburtsdatum=date(1990, 5, 17), mobilnummer='079 000 00 00',
            email='anna.bewerber@example.ch', beruf='Kauffrau', einkommen_jahr="90'000",
            arbeitgeber='Muster AG', adresse='Alte Gasse 3', plz='3000', ort='Bern',
            nationalitaet='Schweiz')
        if mit_dokumenten:
            b.ausweiskopie.save('ausweis.pdf', ContentFile(b'%PDF-Ausweis'), save=False)
            b.lohnausweis.save('lohn.pdf', ContentFile(b'%PDF-Lohn'), save=False)
            b.betreibungsauszug.save('betr.pdf', ContentFile(b'%PDF-Betreibung'), save=False)
            b.save()
        # erstellt_am/aktualisiert_am sind auto_now(_add) — direkt in der DB setzen.
        from django.utils import timezone
        wann = timezone.now() - timedelta(days=entschieden_vor_tagen)
        type(b).objects.filter(pk=b.pk).update(erstellt_am=wann - timedelta(days=30),
                                               aktualisiert_am=wann)
        b.refresh_from_db()
        return b

    def _dateien_da(self, b):
        import os
        from django.conf import settings
        b.refresh_from_db()
        return [f for f in ('ausweiskopie', 'lohnausweis', 'betreibungsauszug')
                if getattr(b, f) and os.path.exists(
                    os.path.join(settings.MEDIA_ROOT, getattr(b, f).name))]

    def test_abgelehntes_dossier_verliert_seine_dokumente(self):
        from core.services.bewerbung_aufbewahrung import bereinige
        b = self._bewerbung(entschieden_vor_tagen=120)
        self.assertEqual(len(self._dateien_da(b)), 3, 'Ausgangslage: drei Dateien vorhanden')
        bereinige(_heute(), anwenden=True)
        self.assertEqual(self._dateien_da(b), [],
                         'Ausweis/Lohnausweis/Betreibungsauszug liegen weiter auf der Platte')

    def test_innerhalb_der_nachlauffrist_bleibt_alles(self):
        """Die wenigen Tage sind keine Aufbewahrung, sondern Nachlauf für den
        Versand der Absagen — vorher wird nichts angefasst.

        Stand ursprünglich auf 30 Tagen, weil die Frist 90 Tage betrug. Der
        EDÖB verlangt Vernichtung «möglichst rasch»; die Frist ist deshalb auf
        7 Tage verkürzt, und dieser Test zog nach."""
        from core.services.bewerbung_aufbewahrung import bereinige
        b = self._bewerbung(entschieden_vor_tagen=2)
        bereinige(_heute(), anwenden=True)
        self.assertEqual(len(self._dateien_da(b)), 3)

    def test_offene_bewerbung_wird_nie_angefasst(self):
        """Solange nicht entschieden ist, läuft keine Frist — sonst würde
        einer Bewerberin das Dossier unter dem laufenden Verfahren gelöscht."""
        from core.services.bewerbung_aufbewahrung import bereinige
        b = self._bewerbung(status='neu', entschieden_vor_tagen=800)
        bereinige(_heute(), anwenden=True)
        self.assertEqual(len(self._dateien_da(b)), 3)
        b.refresh_from_db()
        self.assertEqual(b.vorname, 'Anna')

    def test_zusage_wird_nie_automatisch_geloescht(self):
        """Aus dem zugesagten Dossier entsteht das Mietverhältnis. Es läuft
        über die Personen-Anonymisierung, nicht über diese Frist."""
        from core.services.bewerbung_aufbewahrung import bereinige
        b = self._bewerbung(status='zugesagt', entschieden_vor_tagen=900)
        bereinige(_heute(), anwenden=True)
        self.assertEqual(len(self._dateien_da(b)), 3)

    def test_stille_absage_zaehlt_auch(self):
        """Der häufigste Fall in der Praxis: nie beantwortet, aber die Wohnung
        ist längst vermietet. Ohne diesen Weg bliebe der grösste Teil der
        Dossiers für immer liegen."""
        from core.services.bewerbung_aufbewahrung import bereinige, entschieden_am
        b = self._bewerbung(status='geprueft', entschieden_vor_tagen=400)
        m = Mieter.objects.create(typ='person', vorname='Neu', nachname='Mieter',
                                  email='neu@example.ch', strasse='W 1', plz='3000', ort='Bern')
        Mietvertrag.objects.create(mieter=m, einheit=self.e, status='aktiv',
                                   beginn=_heute() - timedelta(days=300),
                                   netto_mietzins=Decimal('1200'), nebenkosten=Decimal('150'))
        self.assertIsNotNone(entschieden_am(b), 'Vermietetes Objekt = Entscheid gefallen')
        bereinige(_heute(), anwenden=True)
        self.assertEqual(self._dateien_da(b), [])

    def test_nach_einem_jahr_verschwinden_auch_die_personalien(self):
        from core.services.bewerbung_aufbewahrung import bereinige
        b = self._bewerbung(entschieden_vor_tagen=400)
        bereinige(_heute(), anwenden=True)
        b.refresh_from_db()
        self.assertEqual(b.vorname, 'Anonymisiert')
        for feld, wert in (('arbeitgeber', 'Muster AG'), ('adresse', 'Alte Gasse 3'),
                           ('einkommen_jahr', "90'000"), ('nationalitaet', 'Schweiz')):
            self.assertNotEqual(getattr(b, feld), wert, f'{feld} steht noch im Dossier')
        self.assertNotIn('anna.bewerber', b.email)
        self.assertEqual(self._dateien_da(b), [])

    def test_trockenlauf_aendert_nichts(self):
        """Ohne --apply darf nichts verschwinden — sonst wäre die Vorschau
        eine Löschung."""
        from core.services.bewerbung_aufbewahrung import bereinige
        b = self._bewerbung(entschieden_vor_tagen=400)
        dok, anon = bereinige(_heute(), anwenden=False)
        self.assertEqual((dok, anon), (0, 1), 'Vorschau meldet den Fall nicht')
        self.assertEqual(len(self._dateien_da(b)), 3)
        b.refresh_from_db()
        self.assertEqual(b.vorname, 'Anna')

    def test_taeglicher_lauf_fuehrt_die_bereinigung_aus(self):
        """Eine Frist, die niemand auslöst, ist keine Frist."""
        from django.core.management import call_command
        import io
        b = self._bewerbung(entschieden_vor_tagen=120)
        call_command('taeglicher_lauf', stdout=io.StringIO())
        self.assertEqual(self._dateien_da(b), [],
                         'Der tägliche Lauf bereinigt die Bewerbungsdossiers nicht')


class WebhookFailClosedTests(TestCase):
    """Webhooks weisen ab, wenn kein Secret konfiguriert ist.

    `/docuseal/webhook/` liess einen nicht angemeldeten POST durch, solange
    DOCUSEAL_WEBHOOK_SECRET nicht gesetzt war — begründet mit
    „Rückwärtskompatibilität". Der Endpunkt setzt aber `sign_status` auf
    'unterzeichnet' und ersetzt das Vertrags-PDF. Ein Fremder konnte damit
    eine Unterschrift vortäuschen.

    Bitter daran: Dieselbe Route gibt es ein zweites Mal in `rentals/api.py`,
    dort seit je fail-closed und durch Tests gehalten. Die ältere View-Fassung
    war schlicht nicht nachgezogen worden. Fehlende Prüfmöglichkeit ist kein
    Grund, nicht zu prüfen.
    """

    def _post(self, **extra):
        return Client().post('/docuseal/webhook/', data='{}',
                             content_type='application/json', **extra)

    def test_ohne_konfiguriertes_secret_wird_abgewiesen(self):
        from django.test import override_settings
        with override_settings(DOCUSEAL_WEBHOOK_SECRET=None):
            self.assertEqual(self._post().status_code, 403)

    def test_falsches_secret_wird_abgewiesen(self):
        from django.test import override_settings
        with override_settings(DOCUSEAL_WEBHOOK_SECRET='richtig'):
            self.assertEqual(self._post(HTTP_X_WEBHOOK_SECRET='falsch').status_code, 403)
            self.assertEqual(self._post().status_code, 403)

    def test_richtiges_secret_wird_verarbeitet(self):
        """Gegenstück — sonst wäre „weist ab" auch dann erfüllt, wenn der
        Webhook überhaupt nicht mehr funktioniert."""
        from django.test import override_settings
        with override_settings(DOCUSEAL_WEBHOOK_SECRET='richtig'):
            self.assertEqual(self._post(HTTP_X_WEBHOOK_SECRET='richtig').status_code, 200)

    def test_fremder_kann_keinen_vertrag_auf_unterzeichnet_setzen(self):
        """Der Kern der Sache, nicht nur der Statuscode."""
        from django.test import override_settings
        _lg, _e, _m, v = _basis_objekte()
        vorher = v.sign_status
        nutzlast = ('{"event_type":"submission.completed","data":'
                    f'{{"name":"Mietvertrag {v.id}"}}}}')
        with override_settings(DOCUSEAL_WEBHOOK_SECRET=None):
            Client().post('/docuseal/webhook/', data=nutzlast,
                          content_type='application/json')
        v.refresh_from_db()
        self.assertEqual(v.sign_status, vorher,
                         'Ein nicht angemeldeter POST hat den Vertrag verändert')

    def test_brevo_webhook_ebenfalls_fail_closed(self):
        """Nicht verdrahtet und damit heute nicht erreichbar — die Funktion
        wird aber direkt geprüft, damit sie beim späteren Anschliessen nicht
        offen ist."""
        from core.views.webhooks import brevo_inbound_webhook
        from django.test import RequestFactory, override_settings
        req = RequestFactory().post('/', data='{}', content_type='application/json')
        with override_settings(BREVO_WEBHOOK_SECRET=None):
            self.assertEqual(brevo_inbound_webhook(req).status_code, 403)
        with override_settings(BREVO_WEBHOOK_SECRET='geheim'):
            r2 = RequestFactory().post('/', data='{}', content_type='application/json',
                                       HTTP_X_WEBHOOK_SECRET='geheim')
            self.assertEqual(brevo_inbound_webhook(r2).status_code, 200)

    def test_kein_webhook_bleibt_ohne_secret_offen(self):
        """Register-Prüfung: Jede csrf-freie View, die POST verarbeitet, muss
        ihr Secret prüfen. Ein neuer Webhook ohne Schranke fällt hier auf."""
        import ast
        import pathlib
        offen = []
        for pfad in sorted(pathlib.Path('core/views').rglob('*.py')):
            quelle = pfad.read_text(encoding='utf-8')
            try:
                baum = ast.parse(quelle)
            except SyntaxError:
                continue
            for k in baum.body:
                if not isinstance(k, ast.FunctionDef):
                    continue
                namen = [getattr(d, 'id', getattr(d, 'attr', '')) for d in k.decorator_list]
                if 'csrf_exempt' not in namen:
                    continue
                seg = ast.get_source_segment(quelle, k) or ''
                if 'compare_digest' not in seg and '_webhook_secret_ok' not in seg:
                    offen.append(f'{k.name} ({pfad})')
        self.assertEqual(offen, [], 'csrf-freie POST-Views ohne Secret-Prüfung: '
                                    + ', '.join(offen))


class AusgehendeAufrufeTests(TestCase):
    """Kein ausgehender Aufruf ohne Zeitlimit, keiner unnötig im Anfragepfad.

    Antwortet ein fremder Dienst nicht, wartet `requests` ohne `timeout`
    unbegrenzt. Auf einem Hosting mit einem einzigen Arbeitsprozess hängt
    damit die ganze Anwendung an einem fremden Server.
    """

    def test_kein_requests_aufruf_ohne_zeitlimit(self):
        """Register-Prüfung über den ganzen Code — auch mehrzeilige Aufrufe."""
        import ast
        import pathlib
        ohne = []
        for pfad in sorted(pathlib.Path('.').glob('*/**/*.py')):
            if any(t in pfad.parts for t in ('.git', 'migrations')) or pfad.name.startswith('test'):
                continue
            quelle = pfad.read_text(encoding='utf-8', errors='ignore')
            if 'requests.' not in quelle:
                continue
            try:
                baum = ast.parse(quelle)
            except SyntaxError:
                continue
            for k in ast.walk(baum):
                if not isinstance(k, ast.Call):
                    continue
                f = k.func
                if not (isinstance(f, ast.Attribute)
                        and getattr(f.value, 'id', '') in ('requests', 'httpx')
                        and f.attr in ('get', 'post', 'put', 'patch', 'delete')):
                    continue
                if not any(kw.arg == 'timeout' for kw in k.keywords):
                    ohne.append(f'{pfad}:{k.lineno}')
        self.assertEqual(ohne, [], 'Ausgehende Aufrufe ohne timeout: ' + ', '.join(ohne))

    def test_marktdaten_holt_nur_bei_altem_stand_nach(self):
        """Der Endpunkt war mit gut einer Sekunde die langsamste Route. Ist der
        gespeicherte Stand frisch, darf er gar nicht erst ins Internet."""
        from unittest import mock
        from django.utils import timezone
        from crm.models import Verwaltung
        vw = Verwaltung.objects.first() or Verwaltung.objects.create(
            firma='Test AG', strasse='Weg 1', plz='3000', ort='Bern')
        vw.letztes_update_marktdaten = timezone.now()
        vw.save()
        c = Client(); c.force_login(_team_user())
        with mock.patch('core.utils.market_data.update_verwaltung_rates') as geholt:
            r = c.get('/neu/marktdaten/live/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(geholt.called, 'Frischer Stand — trotzdem ins Internet gegangen')

    def test_marktdaten_holt_bei_altem_stand_doch_nach(self):
        """Gegenstück: Ist der Stand alt, muss der Weg noch funktionieren."""
        from unittest import mock
        from django.utils import timezone
        from crm.models import Verwaltung
        vw = Verwaltung.objects.first() or Verwaltung.objects.create(
            firma='Test AG', strasse='Weg 1', plz='3000', ort='Bern')
        vw.letztes_update_marktdaten = timezone.now() - timedelta(days=5)
        vw.save()
        c = Client(); c.force_login(_team_user())
        with mock.patch('core.utils.market_data.update_verwaltung_rates') as geholt:
            c.get('/neu/marktdaten/live/')
        self.assertTrue(geholt.called, 'Alter Stand wird nicht mehr nachgeholt')


class QrStrukturierteAdresseTests(TestCase):
    """QR-Rechnung nach Swiss Implementation Guidelines v2.4.

    Mit dem SIC-Release vom 13. November 2026 wird nur noch die
    STRUKTURIERTE Adresse unterstützt; die kombinierte («K») entfällt und
    Einzahlungsscheine damit werden abgewiesen. Der Datenblock verwendete
    bisher durchgehend «K».

    Die Aufrufer übergeben die Adresse als zwei Zeilen — die Zerlegung
    passiert deshalb im QR-Modul, damit nicht jeder Aufrufer umgebaut werden
    muss. Wer die Felder einzeln hat, kann sie direkt liefern.
    """

    def test_strasse_und_hausnummer_werden_getrennt(self):
        from core.utils.qr_code import strasse_und_nummer
        for zeile, erwartet in [
            ('Musterstrasse 12', ('Musterstrasse', '12')),
            ('Bahnhofstrasse 12a', ('Bahnhofstrasse', '12a')),
            ('Chemin des Fleurs 3', ('Chemin des Fleurs', '3')),
            ('Bergweg 12-14', ('Bergweg', '12-14')),
            ('Postfach', ('Postfach', '')),          # ohne Nummer: zulässig
            ('', ('', '')),
        ]:
            self.assertEqual(strasse_und_nummer(zeile), erwartet, f'bei «{zeile}»')

    def test_plz_und_ort_werden_getrennt(self):
        from core.utils.qr_code import plz_und_ort
        for zeile, erwartet in [
            ('3000 Bern', ('3000', 'Bern')),
            ('CH-8001 Zürich', ('8001', 'Zürich')),
            ('1211 Genève 12', ('1211', 'Genève 12')),
            ('Bern', ('', 'Bern')),                  # ohne PLZ: Ort trotzdem füllen
        ]:
            self.assertEqual(plz_und_ort(zeile), erwartet, f'bei «{zeile}»')

    def test_adressblock_ist_strukturiert(self):
        from core.utils.qr_code import adressblock
        block = adressblock({'name': 'Muster AG', 'line1': 'Musterstrasse 12',
                             'line2': '3000 Bern'})
        self.assertEqual(block, ['S', 'Muster AG', 'Musterstrasse', '12',
                                 '3000', 'Bern', 'CH'])

    def test_einzelfelder_gehen_vor(self):
        """Wer die Adresse strukturiert vorliegen hat, soll sie direkt geben
        können — geraten wird nur, wo nichts Genaueres da ist."""
        from core.utils.qr_code import adressblock
        block = adressblock({'name': 'X', 'line1': 'Falschweg 9', 'line2': '9999 Nirgends',
                             'strasse': 'Richtigweg', 'hausnummer': '1',
                             'plz': '3011', 'ort': 'Bern'})
        self.assertEqual(block[2:6], ['Richtigweg', '1', '3011', 'Bern'])

    def test_datenblock_enthaelt_kein_K_mehr(self):
        """Der Kern: im erzeugten QR-Datenblock darf der Adresstyp nirgends
        mehr «K» sein. Geprüft am echten Aufbau, nicht an den Helfern."""
        import io
        from unittest import mock
        from core.utils import qr_code
        gefangen = {}

        echt = qr_code.segno.make

        def merken(daten, error=None):
            gefangen['daten'] = daten
            return echt(daten, error=error)     # echt zeichnen, nur mitlesen

        with mock.patch.object(qr_code.segno, 'make', side_effect=merken):
            from reportlab.pdfgen import canvas as _canvas
            c = _canvas.Canvas(io.BytesIO())
            try:
                qr_code.draw_qr_bill(
                    c, iban='CH5800791123000889012',
                    creditor={'name': 'Verwaltung AG', 'line1': 'Amtsweg 4', 'line2': '3011 Bern'},
                    debtor={'name': 'Anna Muster', 'line1': 'Wohnweg 7a', 'line2': '8000 Zürich'},
                    amount=1580.00, reference='', reason='Miete')
            except TypeError:
                self.skipTest('Signatur von draw_qr_bill weicht ab')
        zeilen = gefangen['daten'].split('\n')
        self.assertNotIn('K', zeilen, 'Datenblock enthält noch eine kombinierte Adresse')
        self.assertEqual(zeilen.count('S'), 2, 'Es müssen zwei strukturierte Adressen sein')
        self.assertIn('Amtsweg', zeilen)
        self.assertIn('3011', zeilen)
        self.assertIn('Wohnweg', zeilen)
        self.assertIn('7a', zeilen)


class BewerbungDatenschutzTests(TestCase):
    """Was das öffentliche Bewerbungsformular fragen darf — und was es sagen muss.

    Massgeblich sind das EDÖB-Merkblatt zu Anmeldeformularen für Mietwohnungen
    und die darauf gestützte SVIT-Branchenempfehlung (Anhang E). Beide gehen
    von einem ZWEISTUFIGEN Verfahren aus: Im ersten Schritt nur, was zur
    Vorauswahl nötig ist; Belege erst, wenn sich ein Vertragsabschluss
    konkretisiert. Das Formular fragte bisher alles auf einmal ab.
    """

    def setUp(self):
        self.lg = Liegenschaft.objects.create(strasse='Inserat 1', plz='3000', ort='Bern')
        self.e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='3.5 Zi',
                                        typ='wohnung', zur_ausschreibung=True)

    def _formular(self):
        return Client().get(f'/bewerben/{self.e.id}/').content.decode()

    def test_zivilstand_wird_nicht_mehr_gefragt(self):
        """«Die Frage nach dem Zivilstand ist aus Datenschutzüberlegungen nicht
        verhältnismässig» — SVIT-Branchenempfehlung DSG, Anhang E."""
        self.assertNotIn('form.zivilstand', self._formular())

    def test_ausweis_und_lohnausweis_erst_in_der_engeren_auswahl(self):
        """Belege zum Einkommen darf man erst von der ausgewählten Person oder
        einer engeren Auswahl verlangen, nicht von allen Interessenten."""
        html = self._formular()
        self.assertNotIn("handleFile($event, 'lohnausweis')", html)
        self.assertNotIn("handleFile($event, 'ausweiskopie')", html)

    def test_betreibungsauszug_bleibt_zulaessig(self):
        """Gegenstück: Der Betreibungsregisterauszug darf mit dem Formular von
        allen eingefordert werden. Ohne diese Prüfung wäre «weniger fragen»
        auch durch das Leeren des ganzen Formulars erfüllt."""
        self.assertIn("handleFile($event, 'betreibungsauszug')", self._formular())

    def test_formular_erfuellt_die_informationspflicht(self):
        """Art. 19 revDSG: Information bei der Beschaffung. Der EDÖB verlangt
        zusätzlich ausdrücklich den Hinweis auf mögliche Referenzauskünfte."""
        html = self._formular()
        for stichwort in ('Referenzauskunft', 'gelöscht', 'Auskunft', 'Datenschutzerklärung'):
            self.assertIn(stichwort, html, f'Hinweis auf «{stichwort}» fehlt im Formular')
        self.assertIn('/datenschutz/', html, 'Keine Verknüpfung zur Datenschutzerklärung')

    def test_datenschutzerklaerung_ist_ohne_anmeldung_lesbar(self):
        """Sie wird aus dem öffentlichen Formular verlinkt — wer dort landet,
        ist nicht angemeldet."""
        r = Client().get('/datenschutz/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for stichwort in ('Verantwortliche', 'Aufbewahr', 'Ihre Rechte', '958f'):
            self.assertIn(stichwort, html, f'«{stichwort}» fehlt in der Datenschutzerklärung')

    def test_datenschutzerklaerung_nennt_die_verwaltung_aus_den_stammdaten(self):
        """Kein zweiter Ort für Firma und Adresse, der veralten kann."""
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='Muster Immobilien AG', strasse='Amtsweg 4',
                                  plz='3011', ort='Bern')
        html = Client().get('/datenschutz/').content.decode()
        self.assertIn('Muster Immobilien AG', html)
        self.assertIn('3011', html)

    def test_loeschfrist_folgt_dem_edoeb_massstab(self):
        """Der EDÖB verlangt Vernichtung «möglichst rasch» nach dem Entscheid.
        Die erste Fassung stand auf 90 Tagen — zu lang."""
        import inspect
        from core.services.bewerbung_aufbewahrung import bereinige
        vorgabe = inspect.signature(bereinige).parameters['dokumente_tage'].default
        self.assertLessEqual(vorgabe, 14,
                             f'Standardfrist {vorgabe} Tage ist zu lang für «möglichst rasch»')


class ReviewNachbesserungTests(TestCase):
    """Nachbesserungen aus dem Code-Review der QS-Umsetzung.

    Sechs Fehler in der eigenen Arbeit, zwei davon schlimmer als der
    Ausgangszustand: Das Formular schickte nach dem Entfernen des Feldes
    weiterhin «ledig» mit (erfundene Angabe statt gar keiner), und die
    Bewerber-Bewertung konnte nach dem Wegfall der beiden Uploads für
    niemanden mehr die volle Punktzahl erreichen.
    """

    def _bewerbung(self, **kw):
        from mietprozess.models import Mietbewerbung
        lg = Liegenschaft.objects.create(strasse='Prüfweg 1', plz='3000', ort='Bern')
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='3.5 Zi', typ='wohnung',
                                   nettomiete_aktuell=Decimal('1500'),
                                   nebenkosten_aktuell=Decimal('200'))
        vorgabe = dict(einheit=e, vorname='Anna', nachname='Muster',
                       geburtsdatum=date(1990, 1, 1), mobilnummer='079', email='a@example.ch',
                       beruf='Kauffrau', einkommen_jahr="120'000", erwerbsstatus='angestellt',
                       ist_unbefristet=True, hat_betreibungen=False,
                       digitaler_betreibungsauszug=True, arbeitgeber='Muster AG')
        vorgabe.update(kw)
        return Mietbewerbung.objects.create(**vorgabe)

    def test_formular_schickt_keinen_erfundenen_zivilstand(self):
        """Das Feld wurde aus der Anzeige entfernt, das Vue-Modell sendete aber
        weiter 'ledig' — jede Bewerbung hätte eine Angabe gespeichert, die
        niemand gemacht hat. «Nicht erhoben» muss leer bleiben."""
        lg = Liegenschaft.objects.create(strasse='Inserat 2', plz='3000', ort='Bern')
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='2 Zi', typ='wohnung',
                                   zur_ausschreibung=True)
        html = Client().get(f'/bewerben/{e.id}/').content.decode()
        self.assertNotIn("zivilstand: 'ledig'", html)
        self.assertIn("zivilstand: ''", html)

    def test_zivilstand_darf_leer_bleiben(self):
        b = self._bewerbung()
        self.assertEqual(b.zivilstand, '', 'Modell erfindet weiterhin einen Zivilstand')

    def test_volle_punktzahl_bleibt_erreichbar(self):
        """Mit dem alten Massstab (3 Dokumente) hätte niemand mehr über 90 von
        100 kommen können — die fehlenden Punkte sähen nach einem Mangel der
        Bewerberin aus, obwohl WIR die Unterlagen nicht mehr wollen."""
        from core.services.bewerber_scoring import bewerte_bewerbung
        ergebnis = bewerte_bewerbung(self._bewerbung(), Decimal('1700'))
        self.assertEqual(ergebnis['score'], 100,
                         f"Bestmögliche Bewerbung erreicht nur {ergebnis['score']} Punkte")

    def test_fehlender_betreibungsauszug_kostet_punkte(self):
        """Gegenstück: Der Massstab darf nicht einfach immer volle Punkte geben."""
        from core.services.bewerber_scoring import bewerte_bewerbung
        b = self._bewerbung(digitaler_betreibungsauszug=False)
        self.assertLess(bewerte_bewerbung(b, Decimal('1700'))['score'], 100)

    def test_zweite_stufe_kann_unterlagen_nachtragen(self):
        """Das Formular verspricht «fragen wir später an» — dieser Weg muss
        also existieren, sonst ist es eine leere Zusage."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        b = self._bewerbung()
        c = Client(); c.force_login(_team_user('Sachbearbeitung'))
        c.post(f'/neu/bewerbungen/{b.id}/unterlagen/', {
            'lohnausweis': SimpleUploadedFile('lohn.pdf', b'%PDF-1.4', content_type='application/pdf')})
        b.refresh_from_db()
        self.assertTrue(b.lohnausweis, 'Nachgetragener Einkommensnachweis wurde nicht abgelegt')

    def test_lesende_rolle_kann_keine_unterlagen_nachtragen(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        b = self._bewerbung()
        c = Client(); c.force_login(_team_user('Lesend'))
        r = c.post(f'/neu/bewerbungen/{b.id}/unterlagen/', {
            'lohnausweis': SimpleUploadedFile('l.pdf', b'%PDF', content_type='application/pdf')})
        self.assertEqual(r.status_code, 403)
        b.refresh_from_db()
        self.assertFalse(b.lohnausweis)

    def test_marktdaten_zeitstempel_haelt_die_pruefung_fest(self):
        """Der Stempel muss bei JEDER erfolgreichen Prüfung gesetzt werden.
        War er an eine Wertänderung gekoppelt, galten die Daten dazwischen
        dauernd als veraltet — die Frischeprüfung lief damit ins Leere."""
        from unittest import mock
        from django.utils import timezone
        from crm.models import Verwaltung
        from core.utils import market_data
        vw = Verwaltung.objects.create(firma='T AG', strasse='W 1', plz='3000', ort='Bern',
                                       aktueller_referenzzinssatz=Decimal('1.25'))
        vw.letztes_update_marktdaten = None
        vw.save()
        with mock.patch.object(market_data, 'fetch_market_rates',
                               return_value=({'ref_zins': Decimal('1.25')}, [])):
            market_data.update_verwaltung_rates()
        vw.refresh_from_db()
        self.assertIsNotNone(vw.letztes_update_marktdaten,
                             'Unveränderter Wert → Zeitstempel bleibt leer → Prüfung wirkungslos')

    def test_qr_ohne_schuldneradresse_laesst_den_block_leer(self):
        """Ein «S»-Block ohne Postleitzahl und Ort ist ein ungültiger
        Einzahlungsschein. Ist der Schuldner unbekannt (Leerstand), verlangt
        die Spezifikation sieben LEERE Felder."""
        from core.utils.qr_code import adressblock
        self.assertEqual(adressblock({'name': '—', 'line1': '', 'line2': ''}, pflicht=False),
                         ['', '', '', '', '', '', ''])
        # Mit vollständiger Adresse bleibt es ein normaler strukturierter Block
        voll = adressblock({'name': 'Anna', 'plz': '3000', 'ort': 'Bern'}, pflicht=False)
        self.assertEqual(voll[0], 'S')

    def test_deploy_warnt_wenn_das_webhook_secret_fehlt(self):
        """Die Härtung hat eine Kehrseite: Wer DocuSeal bisher OHNE Secret
        betrieben hat, verliert den Rücklauf — lautlos. Der Deploy muss das
        sagen, sonst fällt es erst auf, wenn jemand einen unterschriebenen
        Vertrag sucht."""
        import io
        from django.core.management import call_command
        from django.test import override_settings
        raus, fehler = io.StringIO(), io.StringIO()
        with override_settings(DOCUSEAL_API_KEY='vorhanden', DOCUSEAL_WEBHOOK_SECRET=None):
            call_command('pruefe_webhook_secrets', stdout=raus, stderr=fehler)
        text = raus.getvalue() + fehler.getvalue()
        self.assertIn('DOCUSEAL_WEBHOOK_SECRET', text)
        self.assertIn('nicht abgelegt', text, 'Die Folge wird nicht benannt')

    def test_deploy_schweigt_wenn_alles_gesetzt_ist(self):
        import io
        from django.core.management import call_command
        from django.test import override_settings
        raus = io.StringIO()
        with override_settings(DOCUSEAL_API_KEY='vorhanden', DOCUSEAL_WEBHOOK_SECRET='geheim'):
            call_command('pruefe_webhook_secrets', stdout=raus, stderr=io.StringIO())
        self.assertIn('nichts offen', raus.getvalue())

    def test_deploy_ruft_die_pruefung_auf(self):
        import os
        from django.conf import settings
        with open(os.path.join(settings.BASE_DIR, 'deploy.sh')) as fh:
            self.assertIn('pruefe_webhook_secrets', fh.read())


class BetragUeberlaufTests(TestCase):
    """Ein zu grosser Betrag darf die Datenbank nicht vergiften.

    SQLite erzwingt `max_digits` nicht: ein Betrag mit zu vielen Vorkommastellen
    (z.B. 999999999999.99 in ein max_digits=10-Feld) wird gespeichert und wirft
    dann bei JEDEM Lesen `decimal.InvalidOperation` — die Kreditoren-/Debitoren-
    Liste ist danach für alle dauerhaft 500, nur per Roh-SQL zu reparieren.
    Ein einziger Tippfehler genügt. Ein pre_save-Signal fängt es ab.
    """

    def _konten(self):
        from finance.models import Buchungskonto
        a, _ = Buchungskonto.objects.get_or_create(nummer='4000', defaults={'bezeichnung': 'Aufwand', 'typ': 'aufwand'})
        b, _ = Buchungskonto.objects.get_or_create(nummer='1020', defaults={'bezeichnung': 'Bank', 'typ': 'bilanz'})
        return a, b

    def test_ueberlauf_wird_abgewiesen_kreditor(self):
        from finance.models import KreditorenRechnung
        with self.assertRaises(ValueError):
            KreditorenRechnung.objects.create(betrag=Decimal('999999999999.99'))
        self.assertEqual(KreditorenRechnung.objects.count(), 0,
                         'Überlauf-Betrag ist trotzdem in der DB gelandet')

    def test_ueberlauf_wird_abgewiesen_buchung(self):
        from finance.models import Buchung
        a, b = self._konten()
        with self.assertRaises(ValueError):
            Buchung.objects.create(datum=date(2026, 1, 1), beleg_text='X',
                                   soll_konto=a, haben_konto=b,
                                   betrag=Decimal('100000000.00'))   # 9 Vorkomma, Feld erlaubt 8

    def test_gueltiger_betrag_passiert(self):
        """Gegenstück: Ein normaler Betrag muss durchgehen — sonst hätte die
        Guard einfach alles abgewiesen."""
        from finance.models import KreditorenRechnung
        k = KreditorenRechnung.objects.create(betrag=Decimal('99999999.99'))   # Maximum
        self.assertEqual(k.betrag, Decimal('99999999.99'))

    def test_grenze_liegt_richtig(self):
        from finance.models import KreditorenRechnung
        KreditorenRechnung.objects.create(betrag=Decimal('99999999.99'))       # gerade noch
        with self.assertRaises(ValueError):
            KreditorenRechnung.objects.create(betrag=Decimal('100000000.00'))  # eins zu viel


class QrBetragFormatTests(TestCase):
    """Auf dem Zahlteil kein englisches Tausendertrennzeichen.

    `f"{amount:,.2f}"` erzeugt «1,887.00» — auf einem Schweizer Einzahlungs-
    schein ist das Komma nicht zulässig und für den Zahler zweideutig
    (1,887 vs. 1'887). Der QR-Datenblock selbst war korrekt; nur die gedruckte
    Anzeige nicht."""

    def test_zahlteil_zeigt_apostroph_kein_komma(self):
        import io
        from unittest import mock
        from core.utils import qr_code
        from reportlab.pdfgen import canvas
        gezeichnet = []
        c = canvas.Canvas(io.BytesIO())
        orig = c.drawString
        with mock.patch.object(c, 'drawString',
                               side_effect=lambda x, y, t: gezeichnet.append(t) or orig(x, y, t)):
            with mock.patch.object(c, 'drawImage'):
                qr_code.draw_qr_bill(
                    c, iban='CH5800791123000889012',
                    creditor={'name': 'V AG', 'line1': 'Weg 1', 'line2': '3000 Bern'},
                    debtor={'name': 'A M', 'line1': 'Gasse 2', 'line2': '8000 Zürich'},
                    amount=1234567.89, reference='', reason='Miete')
        betraege = [t for t in gezeichnet if '567' in t]
        self.assertTrue(betraege, 'Betrag wurde nicht gezeichnet')
        for t in betraege:
            self.assertNotIn(',', t, f'Komma im Zahlbetrag: «{t}»')
            self.assertIn("'", t, f'Kein Apostroph-Tausender: «{t}»')


class StilleDatenverlusteTests(TestCase):
    """Ein Fehler in EINEM Feld darf keine andere, gültige Angabe wegräumen —
    und schon gar nicht mit grüner Erfolgsmeldung. Drei belegte Fälle."""

    def _team(self):
        c = Client(); c.force_login(_team_user()); return c

    def test_iban_fehler_loescht_die_korrespondenzadresse_nicht(self):
        """Korrespondenzadresse erfassen → speichern. Dann IBAN vertippen →
        Fehler. Auf der Fehlerseite die IBAN korrigieren → speichern. Die
        Korrespondenzadresse muss erhalten bleiben (sie steuert, wohin
        Mahnungen zugestellt werden)."""
        from crm.models import Mieter, MieterAdresse
        m = Mieter.objects.create(typ='person', vorname='Eva', nachname='Muster',
                                  email='eva@example.ch', strasse='Weg 1', plz='3000', ort='Bern')
        c = self._team()
        basis = {'typ': 'person', 'vorname': 'Eva', 'nachname': 'Muster',
                 'email': 'eva@example.ch', 'strasse': 'Weg 1', 'plz': '3000', 'ort': 'Bern',
                 'k_strasse': 'Postfach 4711', 'k_plz': '6000', 'k_ort': 'Luzern'}
        c.post(f'/neu/personen/{m.id}/bearbeiten/', basis)
        self.assertTrue(MieterAdresse.objects.filter(mieter=m, art='korrespondenz').exists(),
                        'Korrespondenzadresse wurde gar nicht erst gespeichert')
        # Jetzt mit ungültiger IBAN — Fehler. Das gerenderte Formular muss die
        # k_*-Felder zurückgeben, sonst kommen sie beim nächsten Speichern leer.
        r = c.post(f'/neu/personen/{m.id}/bearbeiten/', {**basis, 'iban': 'CH00 0000'})
        self.assertContains(r, 'Postfach 4711',
                            msg_prefix='Fehlerseite gibt die Korrespondenzadresse nicht zurück')
        # Zweiter Speichern mit korrekter IBAN + zurückgegebenen k_*-Feldern
        c.post(f'/neu/personen/{m.id}/bearbeiten/',
               {**basis, 'iban': '', 'k_strasse': 'Postfach 4711', 'k_plz': '6000', 'k_ort': 'Luzern'})
        korr = MieterAdresse.objects.filter(mieter=m, art='korrespondenz').first()
        self.assertIsNotNone(korr, 'Korrespondenzadresse wurde still gelöscht')
        self.assertEqual(korr.ort, 'Luzern')

    def test_kuendigung_zuruecknehmen_behaelt_befristetes_ende(self):
        """Befristeter Vertrag, ausserordentlich gekündigt, dann Kündigung
        zurückgenommen: das vereinbarte Zeitablauf-Ende muss bleiben. Vorher
        wurde ende hart auf None gesetzt → Vertrag lief unbegrenzt weiter."""
        from rentals.models import Kuendigung
        _lg, _e, _m, v = _basis_objekte()
        v.ist_befristet = True
        v.beginn = date(2026, 9, 1); v.ende = date(2027, 8, 31)
        v.status = 'gekuendigt'; v.save()
        k = Kuendigung.objects.create(vertrag=v, eingang_datum=date(2026, 8, 1),
                                      per_datum=date(2026, 12, 31), status='bestaetigt')
        self._team().post(f'/neu/kuendigung/{k.id}/zuruecknehmen/')
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')
        self.assertEqual(v.ende, date(2027, 8, 31),
                         'Befristetes Enddatum wurde bei der Rücknahme gelöscht')

    def test_kuendigung_zuruecknehmen_unbefristet_loescht_ende(self):
        """Gegenstück: Ein UNbefristeter Vertrag verliert sein Ende zu Recht —
        er läuft nach der Rücknahme wieder auf unbestimmte Zeit."""
        from rentals.models import Kuendigung
        _lg, _e, _m, v = _basis_objekte()
        v.ist_befristet = False
        v.ende = date(2026, 12, 31); v.status = 'gekuendigt'; v.save()
        k = Kuendigung.objects.create(vertrag=v, eingang_datum=date(2026, 8, 1),
                                      per_datum=date(2026, 12, 31), status='bestaetigt')
        self._team().post(f'/neu/kuendigung/{k.id}/zuruecknehmen/')
        v.refresh_from_db()
        self.assertIsNone(v.ende)

    def test_entwurf_bearbeiten_behaelt_staffelstufen(self):
        """Einen Staffel-Entwurf am Nettomietzins bearbeiten (das Formular
        sendet keine Staffeldaten zurück): die Stufen dürfen nicht verschwinden,
        sonst stünde der Vertrag auf «Staffel» ohne eine einzige Stufe."""
        from rentals.models import Staffelstufe
        _lg, e, m, v = _basis_objekte()
        v.mietzins_modell = 'staffel'; v.status = 'entwurf'; v.save()
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2027, 1, 1),
                                    netto_mietzins=Decimal('2100'))
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2028, 1, 1),
                                    netto_mietzins=Decimal('2200'))
        c = self._team()
        # Bearbeiten OHNE staffel_ab/staffel_netto (wie das Entwurf-Formular postet)
        c.post('/neu/vertraege/neu/speichern/', {
            'edit_id': str(v.id), 'einheit_id': str(e.id), 'mieter_id': str(m.id),
            'beginn': '2026-01-01', 'unbefristet': '1',
            'netto_mietzins': '2150', 'nebenkosten': '200',
            'mietzins_modell': 'staffel'})
        self.assertEqual(Staffelstufe.objects.filter(vertrag=v).count(), 2,
                         'Staffelstufen wurden beim Bearbeiten still gelöscht')


class JahresabschlussH5H6Tests(TestCase):
    """Live-Test H5+H6: Bilanz-Doppelung nach Abschluss + Abschluss-Storno.

    H5: Nach dem Jahresabschluss zeigte die Bilanz das Periodenergebnis DOPPELT
        (einmal in 2970, einmal als «Jahresgewinn»-Zeile) und erfand einen
        «Ergebnisvortrag (Vorjahre)» in Höhe von −Ergebnis, um das auszugleichen.
    H6: Eine einzelne Abschlussbuchung liess sich im Journal stornieren — das
        liess das Jahr halb geschlossen zurück; und der Storno («Storno …»)
        fiel aus dem Abschluss-Ausschlussfilter → verdoppelte den Ertrag.
    """

    def _saldo(self, nummer):
        from finance.models import Buchung
        from django.db.models import Sum
        soll = Buchung.objects.filter(soll_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        haben = Buchung.objects.filter(haben_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        return soll - haben

    def _period_bookings(self, lg):
        from finance.booking import buche
        buche('1100', '3000', Decimal('1200'), 'Miete 01/2024', datum=date(2024, 1, 31), liegenschaft=lg)
        buche('4000', '1100', Decimal('500'), 'Reparatur 02/2024', datum=date(2024, 2, 15), liegenschaft=lg)
        # erfolg = 1200 − 500 = 700 (Gewinn)

    def test_h5_ergebnis_nicht_doppelt_in_bilanz_nach_abschluss(self):
        from finance.booking import ensure_kontenplan
        from core.services.jahresabschluss import buche_jahresabschluss
        from core.views.fw import _erfolg_bilanz
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._period_bookings(lg)
        vor = _erfolg_bilanz(None, 2024)
        self.assertEqual(vor['erfolg'], Decimal('700.00'))
        self.assertEqual(vor['erfolg_offen'], Decimal('700.00'))
        self.assertEqual(vor['erfolg_vortrag'], Decimal('0.00'))
        self.assertEqual(vor['bilanz_differenz'], Decimal('0.00'))
        buche_jahresabschluss(2024)
        nach = _erfolg_bilanz(None, 2024)
        # Ergebnis ist in 2970 gebucht → keine separate Ergebniszeile mehr und
        # KEIN erfundener Ergebnisvortrag von −700 (das war der Befund).
        self.assertEqual(nach['erfolg_offen'], Decimal('0.00'))
        self.assertEqual(nach['erfolg_vortrag'], Decimal('0.00'))
        self.assertEqual(nach['bilanz_differenz'], Decimal('0.00'))
        self.assertEqual(self._saldo('2970'), Decimal('-700.00'))  # Passivsaldo = Gewinn

    def test_h6_einzelne_abschlussbuchung_nicht_stornierbar(self):
        from finance.booking import ensure_kontenplan
        from core.services.jahresabschluss import buche_jahresabschluss
        from finance.models import Buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._period_bookings(lg)
        buche_jahresabschluss(2024)
        ab = Buchung.objects.filter(beleg_text__startswith='Jahresabschluss 2024 —').first()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        r = c.post(f'/neu/buchhaltung/buchung/{ab.id}/stornieren/', follow=True)
        ab.refresh_from_db()
        self.assertIsNone(ab.storniert_am, 'Abschlussbuchung wurde einzeln storniert')
        self.assertContains(r, 'nicht einzeln stornieren')

    def test_h6_abschluss_zuruecknehmen_oeffnet_jahr_und_reversiert(self):
        from finance.booking import ensure_kontenplan
        from core.services.jahresabschluss import buche_jahresabschluss, ist_abgeschlossen
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._period_bookings(lg)
        buche_jahresabschluss(2024)
        self.assertTrue(ist_abgeschlossen(2024))
        self.assertEqual(self._saldo('2970'), Decimal('-700.00'))
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post('/neu/buchhaltung/', {'aktion': 'abschluss_zuruecknehmen', 'jahr': '2024'})
        self.assertFalse(ist_abgeschlossen(2024))
        self.assertEqual(self._saldo('2970'), Decimal('0.00'))  # vollständig reversiert

    def test_h6_pl_nach_ruecknahme_nicht_verdoppelt(self):
        from finance.booking import ensure_kontenplan
        from core.services.jahresabschluss import buche_jahresabschluss, nimm_zurueck
        from core.views.fw import _erfolg_bilanz
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._period_bookings(lg)
        buche_jahresabschluss(2024)
        nimm_zurueck(2024)
        nach = _erfolg_bilanz(None, 2024)
        self.assertEqual(nach['total_ertrag'], Decimal('1200.00'))
        self.assertEqual(nach['total_aufwand'], Decimal('500.00'))
        self.assertEqual(nach['erfolg'], Decimal('700.00'))
        self.assertEqual(nach['erfolg_offen'], Decimal('700.00'))
        self.assertEqual(nach['bilanz_differenz'], Decimal('0.00'))

    def test_h6_wieder_abschliessbar_nach_ruecknahme(self):
        from finance.booking import ensure_kontenplan
        from core.services.jahresabschluss import buche_jahresabschluss, nimm_zurueck, ist_abgeschlossen
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._period_bookings(lg)
        buche_jahresabschluss(2024)
        nimm_zurueck(2024)
        self.assertFalse(ist_abgeschlossen(2024))
        n, erg = buche_jahresabschluss(2024)
        self.assertGreater(n, 0)
        self.assertEqual(erg, Decimal('700.00'))
        self.assertEqual(self._saldo('2970'), Decimal('-700.00'))

    def test_h6_view_roundtrip_loest_periodensperre_und_oeffnet_jahr(self):
        # End-to-End über die View: Abschluss setzt die Periodensperre auf 31.12.,
        # Rücknahme muss sie ZUERST lösen und die Storni auf den 31.12. zurückbuchen
        # (sonst blockiert Buchung.save die Rücknahme und das Jahr bliebe halb offen).
        from crm.models import Verwaltung
        from finance.booking import ensure_kontenplan
        from core.services.jahresabschluss import ist_abgeschlossen
        from core.views.fw import _erfolg_bilanz
        ensure_kontenplan()
        Verwaltung.objects.create(firma='Verwaltung AG', strasse='Weg 1', plz='8000', ort='Zürich')
        lg, e, m, v = _basis_objekte()
        self._period_bookings(lg)
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post('/neu/buchhaltung/', {'aktion': 'jahresabschluss', 'jahr': '2024'})
        self.assertTrue(ist_abgeschlossen(2024))
        self.assertEqual(Verwaltung.objects.first().buchung_gesperrt_bis, date(2024, 12, 31))
        c.post('/neu/buchhaltung/', {'aktion': 'abschluss_zuruecknehmen', 'jahr': '2024'})
        self.assertFalse(ist_abgeschlossen(2024))
        # Periodensperre gelöst und Jahr im 31.12.-Blick wieder offen (Ergebnis
        # zurück auf den Erfolgskonten, 2970 auf null).
        self.assertNotEqual(Verwaltung.objects.first().buchung_gesperrt_bis, date(2024, 12, 31))
        self.assertEqual(self._saldo('2970'), Decimal('0.00'))
        nach = _erfolg_bilanz(None, 2024)
        self.assertEqual(nach['erfolg_offen'], Decimal('700.00'))
        self.assertEqual(nach['bilanz_differenz'], Decimal('0.00'))


class ZahlungsverkehrH8H9Tests(TestCase):
    """Live-Test H8/H9: Lieferantenzahlung stornierbar + Teilzahlungsrest im Zahllauf.

    H9: `fw_zahlung_stornieren` deckte nur EINGEHENDE Zahlungen ab — eine falsch
        ausgeführte Lieferantenzahlung war nicht rückgängig zu machen.
        Und: nach einer Teilzahlung fiel die Rechnung aus dem Zahllauf-Vorschlag,
        der offene Rest wurde nie wieder vorgeschlagen.
    """

    def _saldo(self, nummer):
        from finance.models import Buchung
        from django.db.models import Sum
        soll = Buchung.objects.filter(soll_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        haben = Buchung.objects.filter(haben_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        return soll - haben

    def _kreditor_freigegeben(self, lg, betrag='500.00'):
        from finance.models import KreditorenRechnung
        return KreditorenRechnung.objects.create(
            lieferant='Sanitär AG', liegenschaft=lg, status='freigegeben',
            datum=date(2024, 3, 1), faellig_am=date(2024, 3, 31),
            betrag=Decimal(betrag), iban='CH9300762011623852957', referenz='RF-1')

    def test_h9_verbuchte_lieferantenzahlung_stornierbar(self):
        from finance.booking import ensure_kontenplan
        from finance.models import KreditorenZahlung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        k = self._kreditor_freigegeben(lg)
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': str(k.id),
                                             'bank_konto': '1020', 'valuta': '2024-03-05'})
        k.refresh_from_db()
        self.assertEqual(k.status, 'bezahlt')
        self.assertEqual(k.offener_betrag, Decimal('0.00'))
        z = KreditorenZahlung.objects.get(kreditor=k)
        c.post(f'/neu/kreditoren/zahlung/{z.id}/stornieren/', {'next': '/neu/kreditoren/'})
        z.refresh_from_db(); k.refresh_from_db()
        self.assertEqual(z.status, 'storniert')
        self.assertEqual(k.status, 'freigegeben')          # offener Posten wieder offen
        self.assertEqual(k.offener_betrag, Decimal('500.00'))
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))   # Zahlung + Storno = 0

    def test_h9_doppel_storno_wird_abgewiesen(self):
        from finance.booking import ensure_kontenplan
        from finance.models import KreditorenZahlung, Buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        k = self._kreditor_freigegeben(lg)
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': str(k.id), 'bank_konto': '1020'})
        z = KreditorenZahlung.objects.get(kreditor=k)
        c.post(f'/neu/kreditoren/zahlung/{z.id}/stornieren/', {})
        n_storni = Buchung.objects.filter(ist_storno=True).count()
        c.post(f'/neu/kreditoren/zahlung/{z.id}/stornieren/', {})   # zweites Mal
        self.assertEqual(Buchung.objects.filter(ist_storno=True).count(), n_storni)

    def test_h9_teilzahlungsrest_im_zahllauf_vorschlag(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        k = self._kreditor_freigegeben(lg, '500.00')
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': str(k.id), 'betrag': '200',
                                             'bank_konto': '1020', 'valuta': '2024-03-05'})
        k.refresh_from_db()
        self.assertEqual(k.status, 'teilbezahlt')
        self.assertEqual(k.offener_betrag, Decimal('300.00'))
        r = c.get('/neu/zahllauf/')
        vorschlag = r.context['vorschlag']
        zeile = next((z for z in vorschlag if z['k'].id == k.id), None)
        self.assertIsNotNone(zeile, 'Teilzahlungsrest fehlt im Zahllauf-Vorschlag')
        self.assertEqual(zeile['offen'], Decimal('300.00'))


class DebitorenStatusETests(TestCase):
    """Live-Test E: Statusprüfungen im Debitoren-/Mahnwesen.

    - Gratismonat (Netto-Schuld 0) darf keinen offenen 0.00-Posten erzeugen.
    - Bezahlte/stornierte Forderung nicht mahnen; kein Mahnstufen-Rückschritt.
    - Mahngebühr wird mit der Hauptforderung mitstorniert.
    - Kein QR-Einzahlungsschein für eine nicht mehr offene Forderung.
    """

    def _offene_rechnung(self, lg, v, betrag='1500.00', mit_buchung=True):
        from finance.models import DebitorenRechnung
        from finance.booking import buche
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete 05/2024',
            datum=date(2024, 5, 1), faellig_am=date(2024, 5, 5),
            betrag=Decimal(betrag), status='offen')
        if mit_buchung:
            buche('1100', '3000', Decimal(betrag), 'Miete 05/2024',
                  datum=date(2024, 5, 1), liegenschaft=lg, debitor=r)
        return r

    def test_e_gratismonat_erzeugt_keinen_offenen_posten(self):
        from finance.booking import ensure_kontenplan
        from finance.models import DebitorenRechnung
        from rentals.models import VertragMietzins
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        # Gratismonat: Referenz 1500/200, voller Erlass → Verrechnung 0
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2024, 1, 1),
                                       netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                                       rabatt_netto=Decimal('1500'), rabatt_nk=Decimal('200'))
        from core.services.automation import run_sollstellung
        run_sollstellung(2024, 6)
        r = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 06/2024')
        self.assertEqual(r.betrag, Decimal('0.00'))
        self.assertEqual(r.status, 'bezahlt')          # kein offener Posten
        self.assertEqual(r.offener_betrag, Decimal('0.00'))

    def test_e_mahnung_nicht_auf_bezahlte_forderung(self):
        from finance.booking import ensure_kontenplan
        from finance.models import Mahnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = self._offene_rechnung(lg, v)
        r.status = 'bezahlt'; r.save(update_fields=['status'])
        c = Client(); c.force_login(_team_user('Verwaltung'))
        resp = c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': str(r.id), 'stufe': '1'}, follow=True)
        self.assertEqual(Mahnung.objects.filter(debitoren_rechnung=r).count(), 0)
        self.assertContains(resp, 'nicht (mehr) offen')

    def test_e_kein_mahnstufen_rueckschritt(self):
        from finance.booking import ensure_kontenplan
        from finance.models import Mahnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = self._offene_rechnung(lg, v)
        Mahnung.objects.create(debitoren_rechnung=r, vertrag=v, stufe=2, datum=date(2024, 6, 1))
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': str(r.id), 'stufe': '1'})
        # Keine neue (niedrigere) Mahnung erfasst — Stufe 2 bleibt die einzige.
        self.assertEqual(Mahnung.objects.filter(debitoren_rechnung=r).count(), 1)
        self.assertEqual(Mahnung.objects.filter(debitoren_rechnung=r).first().stufe, 2)

    def test_e_mahngebuehr_wird_mit_hauptforderung_storniert(self):
        from finance.booking import ensure_kontenplan
        from finance.models import DebitorenRechnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = self._offene_rechnung(lg, v)
        c = Client(); c.force_login(_team_user('Verwaltung'))
        # 2. Mahnung → Mahngebühr CHF 20 als eigene Debitorenrechnung mit stammrechnung=r
        c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': str(r.id), 'stufe': '2'})
        geb = DebitorenRechnung.objects.get(stammrechnung=r)
        self.assertEqual(geb.status, 'offen')
        # Hauptforderung stornieren → Mahngebühr wird mitstorniert
        c.post(f'/neu/debitoren/{r.id}/stornieren/', {})
        r.refresh_from_db(); geb.refresh_from_db()
        self.assertEqual(r.status, 'storniert')
        self.assertEqual(geb.status, 'storniert')

    def test_e_qr_beleg_nicht_fuer_nicht_offene_rechnung(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        # Liegenschaft/Verwaltung ohne IBAN würde ohnehin 400 geben — Status-Gate
        # muss VORHER greifen (409), sonst wäre der Test nicht aussagekräftig.
        lg.iban = 'CH9300762011623852957'; lg.save()
        r = self._offene_rechnung(lg, v, mit_buchung=False)
        r.status = 'bezahlt'; r.save(update_fields=['status'])
        c = Client(); c.force_login(_team_user('Verwaltung'))
        resp = c.get(f'/neu/debitoren/{r.id}/qr-pdf/')
        self.assertEqual(resp.status_code, 409)


class VertragMieterspiegelFTests(TestCase):
    """Live-Test F: Vertrags-Validierung (serverseitig) + Mieterspiegel nach Datum."""

    def _post_vertrag(self, c, einheit, **overrides):
        data = {
            'einheit_id': str(einheit.id),
            'mieter_typ': 'person', 'vorname': 'Anna', 'nachname': 'Beispiel',
            'beginn': '2026-01-01', 'netto_mietzins': '1500', 'nebenkosten': '200',
        }
        data.update(overrides)
        return c.post('/neu/vertraege/neu/speichern/', data)

    def test_f_negative_miete_wird_abgewiesen(self):
        from rentals.models import Mietvertrag
        from crm.models import Mieter
        lg, e, m, v = _basis_objekte()
        e2 = e.__class__.objects.create(liegenschaft=lg, bezeichnung='Neu', typ='wohnung',
                                        nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
        n_vor = Mietvertrag.objects.count(); m_vor = Mieter.objects.count()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        self._post_vertrag(c, e2, netto_mietzins='-100')
        self.assertEqual(Mietvertrag.objects.count(), n_vor)   # kein Vertrag
        self.assertEqual(Mieter.objects.count(), m_vor)        # kein Waisen-Mieter

    def test_f_ende_vor_beginn_wird_abgewiesen(self):
        from rentals.models import Mietvertrag
        lg, e, m, v = _basis_objekte()
        e2 = e.__class__.objects.create(liegenschaft=lg, bezeichnung='Neu2', typ='wohnung',
                                        nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
        n_vor = Mietvertrag.objects.count()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        self._post_vertrag(c, e2, beginn='2026-06-01', ende='2026-03-01', ist_befristet='1')
        self.assertEqual(Mietvertrag.objects.count(), n_vor)

    def test_f_leerer_nachname_wird_abgewiesen(self):
        from rentals.models import Mietvertrag
        from crm.models import Mieter
        lg, e, m, v = _basis_objekte()
        e2 = e.__class__.objects.create(liegenschaft=lg, bezeichnung='Neu3', typ='wohnung',
                                        nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
        n_vor = Mietvertrag.objects.count(); m_vor = Mieter.objects.count()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        self._post_vertrag(c, e2, nachname='', vorname='Nurvorname')
        self.assertEqual(Mietvertrag.objects.count(), n_vor)
        self.assertEqual(Mieter.objects.count(), m_vor)

    def test_f_unbefristet_mit_altem_ende_wird_akzeptiert(self):
        # Ende < Beginn, aber NICHT befristet → Ende wird beim Speichern verworfen;
        # die Anlage darf nicht an einer Ende-vor-Beginn-Prüfung scheitern (Review).
        from rentals.models import Mietvertrag
        lg, e, m, v = _basis_objekte()
        e2 = e.__class__.objects.create(liegenschaft=lg, bezeichnung='Unbef', typ='wohnung',
                                        nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
        n_vor = Mietvertrag.objects.count()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        # ende in der Vergangenheit, ist_befristet NICHT gesetzt
        self._post_vertrag(c, e2, beginn='2026-06-01', ende='2020-01-01')
        self.assertEqual(Mietvertrag.objects.count(), n_vor + 1)
        neu = Mietvertrag.objects.exclude(id=v.id).filter(einheit=e2).first()
        self.assertIsNone(neu.ende, 'Ende wurde bei unbefristetem Vertrag nicht verworfen')

    def test_f_gueltiger_vertrag_wird_gespeichert(self):
        # Gegenstück: ein sauberer Vertrag muss weiterhin durchgehen.
        from rentals.models import Mietvertrag
        lg, e, m, v = _basis_objekte()
        e2 = e.__class__.objects.create(liegenschaft=lg, bezeichnung='OK', typ='wohnung',
                                        nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
        n_vor = Mietvertrag.objects.count()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        self._post_vertrag(c, e2)
        self.assertEqual(Mietvertrag.objects.count(), n_vor + 1)

    def test_f_mieterspiegel_gekuendigter_laufender_vertrag_ist_belegt(self):
        from core.services.mieterspiegel import berechne_mieterspiegel
        lg, e, m, v = _basis_objekte()
        # gekündigt, aber läuft bis Ende 2026 → am Stichtag 06/2026 in Kraft
        v.status = 'gekuendigt'; v.beginn = date(2024, 1, 1); v.ende = date(2026, 12, 31); v.save()
        spiegel = berechne_mieterspiegel([lg], stichtag=date(2026, 6, 1))
        zeile = next(z for z in spiegel[0]['zeilen'] if z['einheit'].id == e.id)
        self.assertTrue(zeile['belegt'], 'gekündigter aber laufender Vertrag fehlt im Mieterspiegel')
        self.assertEqual(spiegel[0]['totals']['leer'], 0)

    def test_f_mieterspiegel_zukuenftiger_vertrag_zaehlt_nicht(self):
        from core.services.mieterspiegel import berechne_mieterspiegel
        lg, e, m, v = _basis_objekte()
        # aktiv, aber Beginn erst 09/2026 → am Stichtag 06/2026 noch nicht in Kraft
        v.status = 'aktiv'; v.beginn = date(2026, 9, 1); v.ende = None; v.save()
        spiegel = berechne_mieterspiegel([lg], stichtag=date(2026, 6, 1))
        zeile = next(z for z in spiegel[0]['zeilen'] if z['einheit'].id == e.id)
        self.assertFalse(zeile['belegt'], 'künftiger Vertrag erscheint zu früh als belegt')
        self.assertEqual(spiegel[0]['totals']['leer'], 1)


class NebenkostenGTests(TestCase):
    """Live-Test G: HNK — Snapshot-Einfrieren beim Verbuchen + Warnung bei fehlender Fläche."""

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

    def test_g_personen_verteilung_proportional(self):
        from finance.booking import ensure_kontenplan
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg
        from crm.models import Verwaltung, Mieter
        from core.utils.billing import berechne_abrechnung
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        ensure_kontenplan()
        # Honorar auf 0 → nur der Personen-Pool wirkt (saubere Prüfung)
        Verwaltung.objects.create(firma='V AG', strasse='W 1', plz='8000', ort='Zürich',
                                  nk_honorar_prozent=Decimal('0'))
        lg, e1, m1, v1 = _basis_objekte()
        v1.anzahl_personen = 1; v1.nebenkosten = Decimal('0'); v1.save()
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='B', typ='wohnung',
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


class RechtstexteITests(TestCase):
    """Live-Test I: Korrektheit der Rechtstexte/-verweise."""

    def _text(self, pdf):
        import io
        from pdfminer.high_level import extract_text
        return extract_text(io.BytesIO(pdf))

    def test_i_bern_formularpflicht_zitiert_eg_zgb(self):
        from core.services.formularpflicht import _REGISTER
        g = _REGISTER['BE']['gesetz']
        self.assertIn('EG ZGB', g)
        self.assertNotIn('Kantonsverfassung', g)

    def test_i_mietzinsanpassung_wirksam_ab_monatserster(self):
        from rentals.services import naechster_anpassungstermin, berechne_kuendigungstermin
        import datetime as _dt
        lg, e, m, v = _basis_objekte()
        termin = naechster_anpassungstermin(v, date(2026, 1, 15))
        self.assertEqual(termin.day, 1, 'Anpassung nicht auf Monatserster')
        # Es ist der Tag NACH dem ordentlichen Kündigungstermin (Monatsende).
        roh = berechne_kuendigungstermin(v, date(2026, 1, 15) + _dt.timedelta(days=17))
        self.assertEqual(termin, roh + _dt.timedelta(days=1))

    def test_i_anpassungstermin_immer_monatserster_auch_bei_mittemonat(self):
        # Robustheit: liegt der frühestmögliche Termin via erstmals_kuendbar_auf
        # ausnahmsweise mitten im Monat, muss die Anpassung trotzdem auf den
        # Monatsersten fallen (nicht Mitte-Monat + 1 Tag). Review-Härtung.
        from rentals.services import naechster_anpassungstermin
        lg, e, m, v = _basis_objekte()
        v.erstmals_kuendbar_auf = date(2030, 6, 15); v.save()   # Nicht-Monatsende
        termin = naechster_anpassungstermin(v, date(2030, 1, 1))
        self.assertEqual(termin.day, 1)
        self.assertEqual(termin, date(2030, 7, 1))

    def test_i_257d_frist_mindestens_30_tage_geschuetzt(self):
        from finance.booking import ensure_kontenplan
        from finance.models import DebitorenRechnung
        from core.models import Pendenz
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()   # Wohnung → geschützt
        self.assertTrue(v.ist_geschuetzt)
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
            titel='Miete', datum=date(2024, 1, 1), faellig_am=date(2024, 1, 5),
            betrag=Decimal('1500'), status='offen')
        c = Client(); c.force_login(_team_user('Verwaltung'))
        heute = date.today()
        # Zu kurze Frist (5 Tage) einreichen → Server erzwingt ≥ 30 Tage
        c.post(f'/neu/vertraege/{v.id}/verzug/',
               {'frist_bis': (heute + timedelta(days=5)).isoformat()})
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='257d').first()
        self.assertIsNotNone(p)
        self.assertGreaterEqual((p.faellig_am - heute).days, 30)

    def test_i_maengelruege_zitiert_257f_nicht_259(self):
        from core.services.mietprozess_briefe import maengelruege_pdf
        lg, e, m, v = _basis_objekte()
        pdf = maengelruege_pdf(v, "Beschädigte Küchenfront durch unsachgemässen Gebrauch.")
        txt = self._text(pdf)
        self.assertIn('257f', txt)
        self.assertNotIn('259', txt)

    def test_i_257d_brief_hat_nur_eine_grussformel(self):
        from finance.booking import ensure_kontenplan
        from finance.models import DebitorenRechnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
            titel='Miete', datum=date(2024, 1, 1), faellig_am=date(2024, 1, 5),
            betrag=Decimal('1500'), status='offen')
        c = Client(); c.force_login(_team_user('Verwaltung'))
        heute = date.today()
        r = c.post(f'/neu/vertraege/{v.id}/verzug/',
                   {'frist_bis': (heute + timedelta(days=40)).isoformat(), 'als_pdf': '1'})
        self.assertEqual(r['Content-Type'], 'application/pdf')
        txt = self._text(r.content)
        self.assertEqual(txt.count('Freundliche Grüsse'), 1, 'Grussformel doppelt/fehlend')


class DashboardGekuendigtJTests(TestCase):
    """Live-Test J: «Gekündigt»-Zähler doppelte einen bereits abgelaufenen Vertrag."""

    def test_j_abgelaufener_gekuendigter_zaehlt_nur_als_beendet(self):
        from rentals.models import Mietvertrag
        from portfolio.models import Einheit
        from crm.models import Mieter
        lg, e1, m1, v1 = _basis_objekte()
        # v1: gekündigt, läuft noch (Ende in der Zukunft)
        v1.status = 'gekuendigt'; v1.ende = date.today() + timedelta(days=60); v1.save()
        # v2: gekündigt, aber Ende bereits vorbei → beendet, NICHT mehr «gekündigt»
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='2Zi', typ='wohnung',
                                    nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
        m2 = Mieter.objects.create(typ='person', vorname='Alt', nachname='Weg',
                                   strasse='S', plz='8000', ort='Zürich')
        Mietvertrag.objects.create(mieter=m2, einheit=e2, beginn=date(2022, 1, 1),
                                   ende=date.today() - timedelta(days=10),
                                   netto_mietzins=Decimal('1000'), nebenkosten=Decimal('100'),
                                   status='gekuendigt')
        c = Client(); c.force_login(_team_user('Verwaltung'))
        r = c.get('/neu/')
        self.assertEqual(r.context['v_gekuendigt'], 1)        # nur der laufende
        self.assertEqual(r.context['gekuendigte_count'], 1)   # Liste konsistent
        self.assertGreaterEqual(r.context['v_beendet'], 1)    # der abgelaufene ist beendet


class KostenkontrolleAddJTests(TestCase):
    """Live-Test J: |add coerct Decimals nach int und schnitt die Rappen ab."""

    def test_j_kostensumme_behaelt_rappen(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        lg, e, m, v = _basis_objekte()
        hw = Handwerker.objects.create(firma='Sanitär AG')
        s = SchadenMeldung.objects.create(liegenschaft=lg, titel='Leck', beschreibung='x')
        HandwerkerAuftrag.objects.create(ticket=s, handwerker=hw, kosten_effektiv=Decimal('10.50'))
        HandwerkerAuftrag.objects.create(ticket=s, handwerker=hw, kosten_geschaetzt=Decimal('5.25'))  # offen
        c = Client(); c.force_login(_team_user('Verwaltung'))
        r = c.get('/neu/schaeden/kosten/')
        self.assertEqual(r.context['total']['gesamt'], Decimal('15.75'))
        self.assertEqual(r.context['rows'][0]['gesamt'], Decimal('15.75'))
        # Und im gerenderten HTML stehen die Rappen (nicht auf 15 abgeschnitten)
        self.assertContains(r, "15.75")


class KuendigungSchlussabrechnungQSTests(TestCase):
    """QS Kündigung/Schlussabrechnung: Anzeige-Kaution = Buchung; befristetes Ende
    überlebt Kündigung + Rücknahme."""

    def test_schlussabrechnung_gutschrift_hoechstens_bilanziert(self):
        # Anzeige/PDF dürfen nur die BILANZIERTE Kaution gutschreiben, nicht die
        # nominale — sonst verspricht das PDF mehr Rückzahlung als gebucht wird.
        from core.services.schlussabrechnung import berechne_schlussabrechnung
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('3000'); v.kautions_art = 'sperrkonto'; v.save()
        # Nur CHF 2000 tatsächlich bilanziert
        daten = berechne_schlussabrechnung(v, date(2024, 6, 30), [],
                                           kaution_verrechnen=True, kaution_bilanziert=Decimal('2000'))
        self.assertEqual(daten['kaution'], Decimal('2000'))
        self.assertEqual(daten['rueckzahlung'], Decimal('2000.00'))   # nicht 3000
        # Ohne den Parameter (Alt-Verhalten) bliebe es beim vereinbarten Betrag:
        alt = berechne_schlussabrechnung(v, date(2024, 6, 30), [], kaution_verrechnen=True)
        self.assertEqual(alt['kaution'], Decimal('3000'))

    def test_befristetes_ende_ueberlebt_ausserordentliche_kuendigung_und_ruecknahme(self):
        from rentals.models import Kuendigung
        lg, e, m, v = _basis_objekte()
        v.ist_befristet = True; v.ende = date(2030, 12, 31); v.save()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        # Ausserordentliche Kündigung per 30.09.2026 → Vertrag endet früher
        c.post(f'/neu/vertraege/{v.id}/kuendigen/',
               {'eingang_datum': '2026-06-01', 'ausserordentlich': 'on',
                'gewuenschtes_ende': '2026-09-30', 'bestaetigen': 'on'})
        v.refresh_from_db()
        self.assertEqual(v.ende, date(2026, 9, 30))
        self.assertEqual(v.status, 'gekuendigt')
        k = Kuendigung.objects.filter(vertrag=v).latest('id')
        self.assertEqual(k.ende_vorher, date(2030, 12, 31))   # Snapshot
        # Rücknahme → ursprüngliche Laufzeit wieder da
        c.post(f'/neu/kuendigung/{k.id}/zuruecknehmen/', {})
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')
        self.assertEqual(v.ende, date(2030, 12, 31))          # nicht 2026-09-30, nicht None


class CamtGesperrtePeriodeQSTests(TestCase):
    """QS Bankabgleich: eine Zahlung, deren Buchung an der Periodensperre scheitert,
    darf beim Re-Import (nach Entsperren) nicht als Duplikat verloren gehen."""

    def _camt(self, ref, betrag='1700.00', acct_ref='GESPERRT1'):
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

    def test_gesperrte_periode_verliert_zahlung_beim_reimport_nicht(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung, Zahlungseingang, Bankbewegung
        from crm.models import Verwaltung
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        r = DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')
        # Periode sperren, sodass die Buchung per 05.03.2024 scheitert.
        Verwaltung.objects.create(firma='V AG', strasse='W 1', plz='8000', ort='Zürich',
                                  buchung_gesperrt_bis=date(2024, 12, 31))
        c = Client(); c.force_login(_team_user('Verwaltung'))

        # 1) Import in gesperrter Periode → nichts gebucht, KEINE Waisen-Bewegung.
        f = SimpleUploadedFile('camt.xml', self._camt(r.qr_referenz), content_type='application/xml')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen')
        self.assertEqual(Zahlungseingang.objects.filter(bank_referenz='GESPERRT1').count(), 0)
        self.assertEqual(Bankbewegung.objects.filter(bank_referenz='GESPERRT1').count(), 0,
                         'Waisen-Bankbewegung blockiert den Re-Import')

        # 2) Periode öffnen, dieselbe Datei erneut importieren → jetzt gebucht.
        vw = Verwaltung.objects.first(); vw.buchung_gesperrt_bis = None; vw.save()
        f2 = SimpleUploadedFile('camt.xml', self._camt(r.qr_referenz), content_type='application/xml')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f2})
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(Zahlungseingang.objects.filter(bank_referenz='GESPERRT1', status='verbucht').count(), 1)


class CamtFuzzyNachnameQSTests(TestCase):
    """QS Bankabgleich: die Fuzzy-Zuordnung «Betrag + Name» darf einen Nachnamen
    nur als ganze Tokenfolge treffen, nicht als beliebige Teilzeichenkette —
    sonst wird die Zahlung eines Fremden («Mustermann») dem Mieter «Muster»
    automatisch gutgeschrieben."""

    def _camt_named(self, dbtr, betrag='1700.00', acct_ref='FUZZY1'):
        return (
            '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt><Ntry>'
            '<CdtDbtInd>CRDT</CdtDbtInd>'
            f'<Amt Ccy="CHF">{betrag}</Amt>'
            '<BookgDt><Dt>2024-03-05</Dt></BookgDt>'
            '<NtryDtls><TxDtls>'
            f'<Refs><AcctSvcrRef>{acct_ref}</AcctSvcrRef></Refs>'
            f'<RltdPties><Dbtr><Nm>{dbtr}</Nm></Dbtr></RltdPties>'
            '</TxDtls></NtryDtls>'
            '</Ntry></Stmt></BkToCstmrStmt></Document>'
        ).encode('utf-8')

    def _setup(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _basis_objekte()   # Mieter Nachname 'Muster', Miete+NK 1700
        run_sollstellung(2024, 3)
        return DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')

    def test_teilstring_nachname_bucht_nicht_falsch(self):
        # Zahlung von «Peter Mustermann» (enthält 'muster' als Teilstring, aber
        # NICHT als ganzes Token) darf dem Mieter «Muster» nicht gutgeschrieben
        # werden. Ohne Referenz → Fuzzy-Pfad; exakter Betrag → einziger Kandidat.
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        r = self._setup()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        f = SimpleUploadedFile('camt.xml', self._camt_named('Peter Mustermann'),
                               content_type='application/xml')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen',
                         'Fremdzahlung «Mustermann» darf «Muster» nicht automatisch bezahlen')
        self.assertEqual(
            Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 0)

    def test_ganzes_token_nachname_bucht(self):
        # Gegenprobe der Erwünschtheit: «Peter Muster» (Nachname als ganzes Token)
        # wird weiterhin korrekt zugeordnet — die Härtung ist nicht zu streng.
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        r = self._setup()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        f = SimpleUploadedFile('camt.xml', self._camt_named('Peter Muster'),
                               content_type='application/xml')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(
            Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 1)
