"""Testmodul portal — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 14 Klassen, unveraendert uebernommen."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import admin
from django.test import TestCase, Client
from ._helfer import (
    _test_organisation,
    _team_user, _basis_objekte, Mieter, Eigentuemer, Organisation,
    Liegenschaft, Einheit, Mietvertrag, User)



class EigentuemerPortalTests(TestCase):
    def _eigentuemer_login(self):
        lg, e, m, v = _basis_objekte()
        md = Eigentuemer.objects.create(firma_oder_name='Eigentümer AG')
        lg.eigentuemer = md; lg.save()
        u = User.objects.create_user(username='eig', password='x')
        md.benutzer = u; md.save()
        return md, lg, u

    def test_cockpit_kpis(self):
        md, lg, u = self._eigentuemer_login()
        c = Client(); c.force_login(u)
        r = c.get('/portal/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Leerstandsquote')
        self.assertContains(r, 'Bruttorendite')  # versicherungswert gesetzt

    def test_report_pdf(self):
        md, lg, u = self._eigentuemer_login()
        c = Client(); c.force_login(u)
        r = c.get('/portal/report/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_fremddokument_404(self):
        from portfolio.models import Dokument as PDok
        from django.core.files.base import ContentFile
        md, lg, u = self._eigentuemer_login()
        fremd = Liegenschaft.objects.create(strasse='X', plz='9', ort='Y')
        d = PDok(liegenschaft=fremd, titel='Fremd', kategorie='x')
        d.datei.save('f.pdf', ContentFile(b'%PDF'), save=True)
        c = Client(); c.force_login(u)
        self.assertEqual(c.get(f'/portal/dokument/{d.id}/').status_code, 404)


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
        from crm.models import Organisation
        m, v, u = self._mieter_login()
        # IBAN für QR-Bill bereitstellen
        _test_organisation(firma='Verwaltung AG', strasse='W 1', plz='8000', ort='Zürich',
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
        md = Eigentuemer.objects.create(firma_oder_name='Eig AG'); eig_lg.eigentuemer = md; eig_lg.save()
        u = User.objects.create_user(username='eig_iso', password='x'); md.benutzer = u; md.save()
        # Freigabe an FREMDER Liegenschaft (nicht dem Eigentümer zugeordnet)
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


class TicketPortalTests(TestCase):
    """Schadenmeldung aus dem Mieterportal: E-Mails + Sidebar-Badge (gelesen)."""

    def _setup(self):
        lg, e, m, v = _basis_objekte()
        # Verwaltung mit E-Mail für die interne Benachrichtigung
        _test_organisation(firma='Verwaltung AG', email='verwaltung@example.ch')
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
        _test_organisation(firma='Verwaltung AG', email='verwaltung@example.ch')
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


class EigentuemerZugangTests(TestCase):
    def _eigentuemer(self):
        md = Eigentuemer.objects.create(firma_oder_name='Eig AG', email='eig@example.ch')
        return md

    def test_zugang_erstellen_und_mail(self):
        from django.core import mail
        md = self._eigentuemer()
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
        md = self._eigentuemer()
        lg = Liegenschaft.objects.create(strasse='A', plz='1', ort='X', versicherungswert=Decimal('1'))
        lg.eigentuemer = md; lg.save()
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
        md = self._eigentuemer()
        team = _team_user()
        c = Client(); c.force_login(team)
        c.post(f'/neu/mandate/{md.id}/portal-zugang/')
        md.refresh_from_db()
        self.assertIsNotNone(md.benutzer_id)
        c.post(f'/neu/mandate/{md.id}/portal-zugang/', {'aktion': 'entfernen'})
        md.refresh_from_db()
        self.assertIsNone(md.benutzer_id)

    def test_button_in_mandatform(self):
        md = self._eigentuemer()
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
        md = Eigentuemer.objects.create(firma_oder_name='Eig AG', email='eig@example.ch')
        lg.eigentuemer = md; lg.save()
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
        Eigentuemer.objects.create(firma_oder_name='Eig AG', email='eig@example.ch')
        call_command('send_eigentuemer_reports', '--dry-run', stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 0)

    def test_ohne_email_uebersprungen(self):
        from django.core import mail
        from django.core.management import call_command
        import io
        Eigentuemer.objects.create(firma_oder_name='Ohne Mail')  # keine E-Mail
        call_command('send_eigentuemer_reports', stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 0)


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


class NachtN5EigentuemerTests(TestCase):
    """Nacht-Audit N5: Kontokorrent-PDF im Portal, Ausstände-KPI,
    Freigabe-Mail an den Eigentümer, Honorar-Transparenz."""

    def _eigentuemer_login(self, **kw):
        lg, e, m, v = _basis_objekte()
        md = Eigentuemer.objects.create(firma_oder_name='Eigentümer AG', **kw)
        lg.eigentuemer = md; lg.save()
        u = User.objects.create_user(username='eig_n5', password='x')
        md.benutzer = u; md.save()
        return md, lg, v, u

    def test_portal_kontokorrent_pdf(self):
        md, lg, v, u = self._eigentuemer_login()
        c = Client(); c.force_login(u)
        for url in ('/portal/kontokorrent/', '/portal/kontokorrent/?jahr=2025'):
            r = c.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r['Content-Type'], 'application/pdf')
            self.assertTrue(r.content.startswith(b'%PDF'))

    def test_portal_kontokorrent_ohne_eigentuemer_404(self):
        u = _team_user()
        c = Client(); c.force_login(u)
        self.assertEqual(c.get('/portal/kontokorrent/').status_code, 404)

    def test_portal_ausstaende_kpi(self):
        from finance.models import DebitorenRechnung
        md, lg, v, u = self._eigentuemer_login()
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
        md, lg, v, u_eig = self._eigentuemer_login(email='eig@example.ch', kontaktperson='Peter Muster')
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
        md, lg, v, u_eig = self._eigentuemer_login(email='eig@example.ch')
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
        md, lg, v, u = self._eigentuemer_login(honorar_prozent=Decimal('5.00'))
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
        md, lg, v, u = self._eigentuemer_login(honorar_prozent=Decimal('4.00'))
        ensure_kontenplan()
        jahr = date.today().year - 1
        buche('1020', '3000', Decimal('10000'), 'Mieten', datum=date(jahr, 3, 31), liegenschaft=lg)
        pdf = generate_kontokorrent_pdf(md, jahr)
        self.assertTrue(pdf.startswith(b'%PDF'))


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

    #: Adressname -> wie eine ID des ANDEREN Eigentümers/Mieters entsteht
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
            md = Eigentuemer.objects.create(firma_oder_name=f'Eigentümer {kuerzel}')
            lg.eigentuemer = md; lg.save()
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
        _test_organisation(firma='Verwaltung AG', strasse='W 1', plz='8000',
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
