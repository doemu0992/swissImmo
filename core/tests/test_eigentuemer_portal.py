"""Eigentümerportal v2 (Etappe 4, Audit FUNK-10/FUNK-11).

Die wichtigste Eigenschaft ist die Abgrenzung: Ein Eigentümer sieht NUR seine eigenen
Liegenschaften, auch wenn die Verwaltung noch einen zweiten Eigentümer führt (derselbe
Mandant!) und wenn es eine zweite Verwaltung gibt. Der Mandantenfilter allein leistet das
nicht — der Eigentümerbezug ist ein eigener Filter. Jeder Test hier, der etwas Fremdes
verbirgt, zeigt zuerst, dass das Eigene sichtbar ist; sonst wäre «nichts zu sehen» auch ein
leerer Bildschirm.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.base import ContentFile
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from core.services import archiv
from core.services import eigentuemer_portal as dienst
from core.tenancy import organisation_kontext
from core.zeit import datum_heute
from crm.models import Eigentuemer, Mieter, Organisation
from finance.booking import buche, ensure_kontenplan
from finance.models import DebitorenRechnung, EigentuemerAuszahlung
from portfolio.models import Dokument, Einheit, Liegenschaft
from rentals.models import Mietvertrag

from ._helfer import _team_user, _test_organisation

User = get_user_model()

FREMDER_BETRAG = Decimal('7777.77')


def _eigentuemer(name, login, **felder):
    e = Eigentuemer.objects.create(firma_oder_name=name, **felder)
    e.benutzer = User.objects.create_user(username=login, password='x')
    e.save()
    return e


def _liegenschaft(eig, strasse, mit_vertrag=True, netto='1500'):
    lg = Liegenschaft.objects.create(strasse=strasse, plz='8000', ort='Zürich', eigentuemer=eig,
                                     organisation=eig.organisation)
    e = Einheit.objects.create(liegenschaft=lg, bezeichnung=f'Whg {strasse}', typ='whg',
                               nettomiete_aktuell=Decimal(netto), nebenkosten_aktuell=Decimal('200'))
    leer = Einheit.objects.create(liegenschaft=lg, bezeichnung=f'Leer {strasse}', typ='whg',
                                  nettomiete_aktuell=Decimal(netto))
    v = None
    if mit_vertrag:
        m = Mieter.objects.create(typ='person', vorname='Mia', nachname=strasse.replace(' ', ''),
                                  email=f'{strasse.replace(" ", "")}@example.ch')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal(netto), nebenkosten=Decimal('200'),
                                       status='aktiv')
    return lg, e, leer, v


def _vertraege_beenden(lg):
    """Archivieren verlangt, dass nichts mehr läuft."""
    Mietvertrag.objects.filter(einheit__liegenschaft=lg).update(status='archiviert')


def _dokument(lg, titel, sichtbar, einheit=None):
    d = Dokument(liegenschaft=None if einheit else lg, einheit=einheit, titel=titel, kategorie='Verwaltung',
                 im_portal_sichtbar=sichtbar)
    d.datei.save(f'{titel}.pdf', ContentFile(b'%PDF-1.4 ' + titel.encode()), save=True)
    return d


class PortalWelt(TestCase):
    """A und B sind zwei Eigentümer DERSELBEN Verwaltung, C gehört einer anderen."""

    def setUp(self):
        self.org = _test_organisation()
        ensure_kontenplan()
        self.a = _eigentuemer('Eigentümer Alpha', 'eig_alpha', email='alpha@example.ch')
        self.lg_a, self.einheit_a, self.leer_a, self.vertrag_a = _liegenschaft(self.a, 'Alphaweg 1')
        self.b = _eigentuemer('Eigentümer Beta', 'eig_beta')
        self.lg_b, self.einheit_b, _l, self.vertrag_b = _liegenschaft(self.b, 'Betaweg 2', netto='2222')
        self.dok_a = _dokument(self.lg_a, 'AlphaVertrag', True)
        self.dok_a_intern = _dokument(self.lg_a, 'AlphaInterneOfferte', False)
        self.dok_b = _dokument(self.lg_b, 'BetaVertrag', True)
        # Gebuchtes Geld: Alpha 3'800 Ertrag, 900 Aufwand; Beta einen unverwechselbaren Betrag.
        jahr = datum_heute().year
        buche('1100', '3000', Decimal('3800'), 'Alpha Miete', datum=date(jahr, 2, 1), liegenschaft=self.lg_a)
        buche('4000', '1020', Decimal('900'), 'Alpha Unterhalt', datum=date(jahr, 3, 1), liegenschaft=self.lg_a)
        buche('1100', '3000', FREMDER_BETRAG, 'Beta Miete', datum=date(jahr, 2, 1), liegenschaft=self.lg_b)
        EigentuemerAuszahlung.objects.create(eigentuemer=self.a, betrag=Decimal('1000'),
                                             datum=date(jahr, 6, 1), bemerkung='AlphaAuszahlung')
        EigentuemerAuszahlung.objects.create(eigentuemer=self.b, betrag=Decimal('4444'),
                                             datum=date(jahr, 6, 2), bemerkung='BetaAuszahlung')
        # Zweite Verwaltung mit eigenem Eigentümer.
        self.org2 = Organisation.objects.create(firma='Andere Verwaltung AG', strasse='X 1', plz='3000',
                                                ort='Bern')
        with organisation_kontext(self.org2):
            self.c = _eigentuemer('Eigentümer Gamma', 'eig_gamma')
            self.lg_c, _e, _l2, _v = _liegenschaft(self.c, 'Gammaweg 3')
            self.dok_c = _dokument(self.lg_c, 'GammaVertrag', True)
        self.client_a = Client()
        self.client_a.force_login(self.a.benutzer)

    def get(self, pfad, **kw):
        return self.client_a.get(pfad, **kw)


class IsolationTests(PortalWelt):
    """Eigentümerbezug UND Mandantentrennung — mit Gegenprobe: das Eigene ist sichtbar."""

    def test_liste_zeigt_nur_eigene_liegenschaften(self):
        r = self.get('/portal/liegenschaften/')
        self.assertContains(r, 'Alphaweg 1')
        self.assertNotContains(r, 'Betaweg 2')            # anderer Eigentümer, gleiche Verwaltung
        self.assertNotContains(r, 'Gammaweg 3')           # andere Verwaltung

    def test_detail_fremder_liegenschaft_ist_404(self):
        self.assertEqual(self.get(f'/portal/liegenschaften/{self.lg_a.pk}/').status_code, 200)
        self.assertEqual(self.get(f'/portal/liegenschaften/{self.lg_b.pk}/').status_code, 404)
        self.assertEqual(self.get(f'/portal/liegenschaften/{self.lg_c.pk}/').status_code, 404)

    def test_detail_zeigt_belegung_nur_der_eigenen(self):
        r = self.get(f'/portal/liegenschaften/{self.lg_a.pk}/')
        self.assertContains(r, 'Whg Alphaweg 1')
        self.assertContains(r, 'Leerstand')
        self.assertContains(r, 'Mia')
        self.assertNotContains(r, 'Betaweg')

    def test_dokumente_nur_freigegebene_eigene(self):
        r = self.get('/portal/dokumente/')
        self.assertContains(r, 'AlphaVertrag')
        self.assertNotContains(r, 'AlphaInterneOfferte')  # nicht freigegeben
        self.assertNotContains(r, 'BetaVertrag')
        self.assertNotContains(r, 'GammaVertrag')

    def test_download_nur_freigegebenes_eigenes(self):
        r = self.get(f'/portal/dokument/{self.dok_a.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'AlphaVertrag', r.content)
        for d in (self.dok_a_intern, self.dok_b, self.dok_c):
            self.assertEqual(self.get(f'/portal/dokument/{d.pk}/').status_code, 404, d.titel)

    def test_download_dokument_am_objekt(self):
        d = _dokument(None, 'AlphaGrundriss', True, einheit=self.einheit_a)
        self.assertEqual(self.get(f'/portal/dokument/{d.pk}/').status_code, 200)
        fremd = _dokument(None, 'BetaGrundriss', True, einheit=self.einheit_b)
        self.assertEqual(self.get(f'/portal/dokument/{fremd.pk}/').status_code, 404)

    def test_archiviertes_dokument_verschwindet(self):
        self.assertEqual(self.get(f'/portal/dokument/{self.dok_a.pk}/').status_code, 200)
        archiv.archivieren(self.dok_a, grund='Test')
        self.assertEqual(self.get(f'/portal/dokument/{self.dok_a.pk}/').status_code, 404)
        self.assertNotContains(self.get('/portal/dokumente/'), 'AlphaVertrag')

    def test_abrechnungen_ohne_fremde_zahlen(self):
        r = self.get('/portal/abrechnungen/')
        self.assertContains(r, 'AlphaAuszahlung')
        self.assertContains(r, "3'800.00")
        for fremd in ("7'777.77", 'BetaAuszahlung', "4'444.00"):
            self.assertNotContains(r, fremd)

    def test_abrechnung_service_nur_eigene_liegenschaften(self):
        zeilen, totals, _von, _bis = dienst.abrechnung_jahr(self.a, datum_heute().year)
        self.assertEqual([z['lg'] for z in zeilen], [self.lg_a])
        self.assertEqual(totals['ertrag'], Decimal('3800.00'))
        self.assertEqual(totals['aufwand'], Decimal('900.00'))

    def test_abrechnung_pdf_eigene_und_ungueltiges_jahr(self):
        jahr = datum_heute().year
        r = self.get(f'/portal/abrechnungen/pdf/?jahr={jahr}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        for schlecht in ('', 'abc', '99999', str(jahr + 1)):
            self.assertEqual(self.get(f'/portal/abrechnungen/pdf/?jahr={schlecht}').status_code, 404, schlecht)

    def test_uebersicht_zahlen_ohne_fremde(self):
        u = dienst.uebersicht(self.a)
        self.assertEqual(u['objekte'], 2)
        self.assertEqual(u['leer'], 1)
        self.assertEqual(u['soll_monat'], Decimal('1500.00'))
        self.assertEqual(u['gebucht_jahr'], Decimal('3800.00'))
        self.assertEqual(u['konto']['guthaben'], Decimal('1900.00'))     # 3800 - 900 - 1000
        r = self.get('/portal/')
        self.assertContains(r, "1'500.00")
        self.assertNotContains(r, "7'777.77")

    def test_offene_posten_nur_eigene(self):
        for lg, v, titel in ((self.lg_a, self.vertrag_a, 'MieteAlpha'), (self.lg_b, self.vertrag_b, 'MieteBeta')):
            DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel=titel, betrag=Decimal('1700'),
                                             datum=date(2024, 1, 1), faellig_am=date(2024, 1, 5), status='offen')
        r = self.get('/portal/abrechnungen/')
        self.assertContains(r, 'MieteAlpha')
        self.assertNotContains(r, 'MieteBeta')
        u = dienst.uebersicht(self.a)
        self.assertEqual((u['offen'], u['ueberfaellig']), (Decimal('1700.00'), Decimal('1700.00')))

    def test_teilzahlung_zaehlt_als_rest(self):
        from finance.models import Zahlungseingang
        d = DebitorenRechnung.objects.create(vertrag=self.vertrag_a, liegenschaft=self.lg_a, titel='Teil',
                                             betrag=Decimal('1700'), datum=date(2024, 1, 1),
                                             faellig_am=date(2024, 1, 5), status='teilbezahlt')
        Zahlungseingang.objects.create(vertrag=self.vertrag_a, betrag=Decimal('700'),
                                       datum_eingang=date(2024, 1, 10), buchungs_monat=date(2024, 1, 1),
                                       debitoren_rechnung=d)
        self.assertEqual(dienst.uebersicht(self.a)['offen'], Decimal('1000.00'))

    def test_mitteilung_an_fremde_liegenschaft_wird_abgewiesen(self):
        from core.models import Pendenz
        r = self.client_a.post('/portal/mitteilungen/', {
            'liegenschaft': self.lg_b.pk, 'art': 'frage', 'betreff': 'Hallo', 'text': 'Text'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Bitte eine Ihrer Liegenschaften wählen.')
        self.assertFalse(Pendenz.objects.filter(quelle__startswith=dienst.ANFRAGE_QUELLE).exists())

    def test_verlauf_zeigt_nur_eigene_anfragen(self):
        dienst.anfrage_senden(self.a, self.a.benutzer, liegenschaft_pk=self.lg_a.pk, art='frage',
                              betreff='FrageAlpha', text='x')
        dienst.anfrage_senden(self.b, self.b.benutzer, liegenschaft_pk=self.lg_b.pk, art='frage',
                              betreff='FrageBeta', text='y')
        r = self.get('/portal/mitteilungen/')
        self.assertContains(r, 'FrageAlpha')
        self.assertNotContains(r, 'FrageBeta')


class ZugangTests(PortalWelt):
    """Wer kein Eigentümer ist, kommt nicht auf die Seiten."""
    SEITEN = ('/portal/liegenschaften/', '/portal/abrechnungen/', '/portal/dokumente/',
              '/portal/mitteilungen/', '/portal/profil/', '/portal/abrechnungen/pdf/?jahr=2025')

    def test_anonym_wird_zur_anmeldung_geleitet(self):
        for pfad in self.SEITEN:
            r = Client().get(pfad)
            self.assertEqual(r.status_code, 302, pfad)
            self.assertIn('login', r.url, pfad)

    def test_team_und_mieter_ohne_verknuepfung_gehen_zur_startseite(self):
        mieter = User.objects.create_user(username='mieter_x', password='x')
        team = _team_user()
        for benutzer in (mieter, team):
            c = Client()
            c.force_login(benutzer)
            for pfad in self.SEITEN:
                r = c.get(pfad)
                self.assertEqual((r.status_code, r.url), (302, '/portal/'), pfad)
            self.assertEqual(c.get(f'/portal/dokument/{self.dok_a.pk}/').status_code, 404)

    def test_eigentuemer_ist_gegenprobe_erreichbar(self):
        for pfad in self.SEITEN[:5]:
            self.assertEqual(self.get(pfad).status_code, 200, pfad)


class LeerzustandTests(TestCase):
    def test_eigentuemer_ohne_liegenschaft_sieht_hinweise_statt_fehler(self):
        _test_organisation()
        e = _eigentuemer('Leer AG', 'eig_leer')
        c = Client()
        c.force_login(e.benutzer)
        for pfad, text in (('/portal/', 'noch keine Liegenschaften zugeordnet'),
                           ('/portal/liegenschaften/', 'noch keine Liegenschaften zugeordnet'),
                           ('/portal/dokumente/', 'Noch keine Dokumente'),
                           ('/portal/mitteilungen/', 'noch keine Liegenschaften zugeordnet'),
                           ('/portal/abrechnungen/', 'Bisher wurde keine Auszahlung verbucht'),
                           ('/portal/profil/', 'Leer AG')):
            r = c.get(pfad)
            self.assertContains(r, text, msg_prefix=pfad)
        u = dienst.uebersicht(e)
        self.assertEqual((u['objekte'], u['offen'], u['konto']['guthaben']), (0, 0, 0))


class MandatsendeTests(PortalWelt):
    def test_ohne_mandatsende_kein_hinweis(self):
        self.assertNotContains(self.get('/portal/'), 'Mandat beendet')

    def test_mandatsende_und_archivierte_liegenschaft_sichtbar(self):
        _vertraege_beenden(self.lg_a)
        archiv.archivieren(self.lg_a, grund='Verkauft')
        archiv.archivieren(self.a, grund='Gekündigt', mandatsende=date(2026, 3, 31))
        for pfad in ('/portal/', '/portal/liegenschaften/', '/portal/abrechnungen/', '/portal/dokumente/'):
            r = self.get(pfad)
            self.assertContains(r, 'Mandat beendet', msg_prefix=pfad)
            self.assertContains(r, '31.03.2026', msg_prefix=pfad)
        liste = self.get('/portal/liegenschaften/')
        self.assertContains(liste, 'Archivierte Liegenschaften')
        self.assertContains(liste, 'Verkauft')
        detail = self.get(f'/portal/liegenschaften/{self.lg_a.pk}/')
        self.assertContains(detail, 'Archivierte Liegenschaft')
        self.assertContains(detail, 'Whg Alphaweg 1')           # lesend weiterhin einsehbar

    def test_archivierte_liegenschaft_zaehlt_nicht_in_den_kennzahlen(self):
        _vertraege_beenden(self.lg_a)
        archiv.archivieren(self.lg_a, grund='Verkauft')
        u = dienst.uebersicht(self.a)
        self.assertEqual((u['aktive'], u['archivierte'], u['objekte'], u['soll_monat']), (0, 1, 0, 0))

    def test_nach_mandatsende_keine_neue_anfrage(self):
        from core.models import Pendenz
        _vertraege_beenden(self.lg_a)
        archiv.archivieren(self.lg_a, grund='Verkauft')
        archiv.archivieren(self.a, grund='Gekündigt', mandatsende=date(2026, 3, 31))
        r = self.client_a.post('/portal/mitteilungen/', {
            'liegenschaft': self.lg_a.pk, 'art': 'frage', 'betreff': 'Hallo', 'text': 'Text'})
        self.assertContains(r, 'Das Mandat ist beendet')
        self.assertFalse(Pendenz.objects.filter(quelle__startswith=dienst.ANFRAGE_QUELLE).exists())

    def test_mandat_ohne_mandatsende_datum_nennt_archivdatum(self):
        _vertraege_beenden(self.lg_a)
        archiv.archivieren(self.lg_a, grund='x')
        archiv.archivieren(self.a, grund='y')
        self.assertContains(self.get('/portal/'), 'wurde am')


class MitteilungenTests(PortalWelt):
    def senden(self, **felder):
        daten = {'liegenschaft': self.lg_a.pk, 'art': 'abrechnung', 'betreff': 'Frage zur Abrechnung',
                 'text': 'Wann kommt die Abrechnung?'}
        daten.update(felder)
        return self.client_a.post('/portal/mitteilungen/', daten)

    def test_anfrage_wird_pendenz_und_mail(self):
        from core.models import Pendenz
        self.org.email = 'verwaltung@example.ch'
        self.org.save(update_fields=['email'])
        r = self.senden()
        self.assertRedirects(r, '/portal/mitteilungen/')
        p = Pendenz.objects.get(quelle=f'{dienst.ANFRAGE_QUELLE}{self.a.pk}')
        self.assertEqual(p.liegenschaft, self.lg_a)
        self.assertEqual(p.erstellt_von, self.a.benutzer)
        self.assertIn('Frage zur Abrechnung', p.titel)
        self.assertIn('Abrechnung oder Auszahlung', p.titel)          # deutsche Fassung für die Verwaltung
        self.assertIn('Wann kommt die Abrechnung?', p.beschreibung)
        self.assertFalse(p.erledigt)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['verwaltung@example.ch'])
        self.assertIn('Eigentümer Alpha', mail.outbox[0].body)
        verlauf = self.get('/portal/mitteilungen/')
        self.assertContains(verlauf, 'Frage zur Abrechnung')
        self.assertContains(verlauf, 'In Bearbeitung')

    def test_erledigte_pendenz_erscheint_als_erledigt(self):
        from core.models import Pendenz
        self.senden()
        Pendenz.objects.filter(quelle__startswith=dienst.ANFRAGE_QUELLE).update(erledigt=True)
        self.assertContains(self.get('/portal/mitteilungen/'), 'Erledigt')

    def test_mailausfall_verliert_die_anfrage_nicht(self):
        from unittest import mock
        from core.models import Pendenz
        self.org.email = 'verwaltung@example.ch'
        self.org.save(update_fields=['email'])
        with mock.patch('django.core.mail.send_mail', side_effect=OSError('kein SMTP')):
            r = self.senden()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Pendenz.objects.filter(quelle__startswith=dienst.ANFRAGE_QUELLE).count(), 1)

    def test_validierung(self):
        from core.models import Pendenz
        faelle = (
            ({'betreff': ''}, 'Bitte einen Betreff angeben.'),
            ({'betreff': '   '}, 'Bitte einen Betreff angeben.'),
            ({'betreff': 'x' * (dienst.BETREFF_MAX + 1)}, 'Der Betreff ist zu lang'),
            ({'text': ''}, 'Bitte Ihre Nachricht eingeben.'),
            ({'text': 'x' * (dienst.TEXT_MAX + 1)}, 'Die Nachricht ist zu lang'),
            ({'art': 'unfug'}, 'Bitte die Art der Anfrage wählen.'),
            ({'liegenschaft': ''}, 'Bitte eine Ihrer Liegenschaften wählen.'),
            ({'liegenschaft': 'abc'}, 'Bitte eine Ihrer Liegenschaften wählen.'),
        )
        for felder, text in faelle:
            r = self.senden(**felder)
            self.assertContains(r, text, msg_prefix=str(felder))
        self.assertFalse(Pendenz.objects.filter(quelle__startswith=dienst.ANFRAGE_QUELLE).exists())
        # Gegenprobe: die gültige Anfrage geht durch.
        self.assertEqual(self.senden().status_code, 302)

    def test_zeilenumbruch_im_betreff_kann_den_mailkopf_nicht_verfaelschen(self):
        self.org.email = 'verwaltung@example.ch'
        self.org.save(update_fields=['email'])
        self.assertEqual(self.senden(betreff='Hallo\nBcc: boese@example.ch').status_code, 302)
        self.assertNotIn('boese@example.ch', ' '.join(mail.outbox[0].bcc))
        self.assertNotIn('\n', mail.outbox[0].subject)

    def test_archivierte_liegenschaft_nicht_waehlbar(self):
        _vertraege_beenden(self.lg_a)
        archiv.archivieren(self.lg_a, grund='Verkauft')
        r = self.senden()
        self.assertContains(r, 'Bitte eine Ihrer Liegenschaften wählen.')


class ProfilTests(PortalWelt):
    def test_korrespondenzsprache_speichern(self):
        r = self.client_a.post('/portal/profil/', {'aktion': 'sprache', 'sprache': 'fr'})
        self.assertRedirects(r, '/portal/profil/')
        self.a.refresh_from_db()
        self.assertEqual(self.a.sprache, 'fr')

    def test_ungueltige_sprache_wird_abgelehnt(self):
        self.client_a.post('/portal/profil/', {'aktion': 'sprache', 'sprache': 'xx'})
        self.a.refresh_from_db()
        self.assertEqual(self.a.sprache, 'de')

    def test_sprache_eines_anderen_bleibt_unberuehrt(self):
        self.client_a.post('/portal/profil/', {'aktion': 'sprache', 'sprache': 'it'})
        self.b.refresh_from_db()
        self.assertEqual(self.b.sprache, 'de')

    def test_passwort_aendern_haelt_die_sitzung(self):
        r = self.client_a.post('/portal/profil/', {
            'aktion': 'passwort', 'old_password': 'x', 'new_password1': 'Sehr-Sicher-4711',
            'new_password2': 'Sehr-Sicher-4711'})
        self.assertRedirects(r, '/portal/profil/')
        self.a.benutzer.refresh_from_db()
        self.assertTrue(self.a.benutzer.check_password('Sehr-Sicher-4711'))
        self.assertEqual(self.get('/portal/profil/').status_code, 200)

    def test_falsches_altes_passwort(self):
        r = self.client_a.post('/portal/profil/', {
            'aktion': 'passwort', 'old_password': 'falsch', 'new_password1': 'Sehr-Sicher-4711',
            'new_password2': 'Sehr-Sicher-4711'})
        self.assertEqual(r.status_code, 200)
        self.a.benutzer.refresh_from_db()
        self.assertTrue(self.a.benutzer.check_password('x'))


class FreigabeImTeamTests(PortalWelt):
    """Das Team entscheidet, was der Eigentümer sieht."""

    def setUp(self):
        super().setUp()
        self.team = Client()
        self.team.force_login(_team_user('Verwaltung'))

    def test_standard_ist_nicht_sichtbar(self):
        d = Dokument(liegenschaft=self.lg_a, titel='Neu', kategorie='x')
        d.datei.save('neu.pdf', ContentFile(b'%PDF'), save=True)
        self.assertFalse(d.im_portal_sichtbar)
        self.assertNotContains(self.get('/portal/dokumente/'), 'Neu')

    def test_team_schaltet_frei_und_aus(self):
        self.assertEqual(self.get(f'/portal/dokument/{self.dok_a_intern.pk}/').status_code, 404)
        self.assertEqual(self.team.post(f'/neu/dokumente/{self.dok_a_intern.pk}/eigentuemerportal/').status_code, 302)
        self.assertEqual(self.get(f'/portal/dokument/{self.dok_a_intern.pk}/').status_code, 200)
        self.team.post(f'/neu/dokumente/{self.dok_a_intern.pk}/eigentuemerportal/')
        self.assertEqual(self.get(f'/portal/dokument/{self.dok_a_intern.pk}/').status_code, 404)

    def test_nur_post_aendert(self):
        self.team.get(f'/neu/dokumente/{self.dok_a_intern.pk}/eigentuemerportal/')
        self.dok_a_intern.refresh_from_db()
        self.assertFalse(self.dok_a_intern.im_portal_sichtbar)

    def test_lesend_darf_nicht(self):
        lesend = Client()
        lesend.force_login(_team_user('Lesend'))
        self.assertEqual(lesend.post(f'/neu/dokumente/{self.dok_a_intern.pk}/eigentuemerportal/').status_code, 403)
        self.dok_a_intern.refresh_from_db()
        self.assertFalse(self.dok_a_intern.im_portal_sichtbar)

    def test_eigentuemer_darf_nicht_freigeben(self):
        r = self.client_a.post(f'/neu/dokumente/{self.dok_a_intern.pk}/eigentuemerportal/')
        self.assertIn(r.status_code, (302, 403))
        self.dok_a_intern.refresh_from_db()
        self.assertFalse(self.dok_a_intern.im_portal_sichtbar)

    def test_dokument_einer_fremden_verwaltung_ist_fuer_das_team_404(self):
        self.assertEqual(self.team.post(f'/neu/dokumente/{self.dok_c.pk}/eigentuemerportal/').status_code, 404)

    def test_upload_mit_haken_ist_sichtbar(self):
        datei = ContentFile(b'%PDF-1.4 hoch', name='hoch.pdf')
        r = self.team.post('/neu/dokumente/neu/', {
            'titel': 'HochgeladenSichtbar', 'kategorie': 'vertrag', 'liegenschaft_id': self.lg_a.pk,
            'datei': datei, 'im_portal_sichtbar': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertContains(self.get('/portal/dokumente/'), 'HochgeladenSichtbar')

    def test_upload_ohne_haken_bleibt_intern(self):
        datei = ContentFile(b'%PDF-1.4 hoch', name='hoch2.pdf')
        self.team.post('/neu/dokumente/neu/', {
            'titel': 'HochgeladenIntern', 'kategorie': 'vertrag', 'liegenschaft_id': self.lg_a.pk, 'datei': datei})
        self.assertNotContains(self.get('/portal/dokumente/'), 'HochgeladenIntern')


class KonsistenzTests(PortalWelt):
    """Die Zahlen des Portals sind dieselben wie die des Kontokorrents und der Abrechnung der Verwaltung."""

    def test_stimmt_mit_kontokorrent_und_mandatsabrechnung_ueberein(self):
        from core.services.eigentuemer_kontokorrent import kontokorrent
        from core.views.fw.eigentuemer_abrechnung import _mandat_abrechnung_daten
        jahr = datum_heute().year
        buche('1100', '3000', Decimal('500'), 'Vorjahr', datum=date(jahr - 1, 5, 1), liegenschaft=self.lg_a)
        kk = kontokorrent(self.a)
        stand = dienst.konto_stand(self.a)
        self.assertEqual((stand['ertrag'], stand['aufwand'], stand['guthaben']),
                         (kk['ertrag'], kk['aufwand'], kk['offen']))
        for j in (jahr - 1, jahr):
            zeilen, totals, _v, _b = _mandat_abrechnung_daten(self.a, j)
            meine, meine_totals, _v2, _b2 = dienst.abrechnung_jahr(self.a, j)
            self.assertEqual(totals, meine_totals, j)
            self.assertEqual([(z['lg'], z['ertrag'], z['aufwand'], z['saldo']) for z in zeilen],
                             [(z['lg'], z['ertrag'], z['aufwand'], z['saldo']) for z in meine], j)

    def test_abschlussbuchungen_zaehlen_nicht(self):
        from core.services.jahresabschluss import abschluss_buchungen_q
        from finance.models import Buchung
        jahr = datum_heute().year
        buche('3000', '2970', Decimal('3800'), f'Jahresabschluss {jahr}', datum=date(jahr, 12, 31),
              liegenschaft=self.lg_a)
        self.assertTrue(Buchung.objects.filter(abschluss_buchungen_q()).exists())
        self.assertEqual(dienst.abrechnung_jahr(self.a, jahr)[1]['ertrag'], Decimal('3800.00'))


class AbfragenTests(PortalWelt):
    """Die Listen laufen mit einer Abfragezahl, die nicht mit dem Bestand wächst."""

    def _zaehle(self, pfad):
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.get(pfad).status_code, 200)
        return len(ctx)

    def test_abfragen_wachsen_nicht_mit_liegenschaften(self):
        seiten = ('/portal/', '/portal/liegenschaften/', '/portal/abrechnungen/', '/portal/dokumente/',
                  f'/portal/liegenschaften/{self.lg_a.pk}/')
        # Eine offene Rechnung gibt es schon im kleinen Bestand: Ohne sie entfiele die Abfrage der
        # Zahlungseingänge und die Zahl stiege beim ersten Posten um eins (nicht je Posten).
        DebitorenRechnung.objects.create(vertrag=self.vertrag_a, liegenschaft=self.lg_a, titel='Offen',
                                         betrag=Decimal('900'), datum=date(2024, 1, 1),
                                         faellig_am=date(2024, 1, 5), status='offen')
        for p in seiten:
            self._zaehle(p)                    # Aufwärmen: Zwischenspeicher füllen, sonst zählt der erste Lauf mehr
        klein = {p: self._zaehle(p) for p in seiten}
        for i in range(4):
            lg, _e, _l, v = _liegenschaft(self.a, f'Zusatzweg {i}')
            _dokument(lg, f'Zusatz{i}', True)
            DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel=f'Offen{i}', betrag=Decimal('900'),
                                             datum=date(2024, 1, 1), faellig_am=date(2024, 1, 5), status='offen')
            buche('1100', '3000', Decimal('100'), f'Zusatz {i}', datum=date(2024, 2, 1), liegenschaft=lg)
        gross = {p: self._zaehle(p) for p in seiten}
        # Die Detailseite ist je Liegenschaft gemessen und darf nicht vom Rest abhängen.
        self.assertEqual(gross, klein)

    def test_liegenschaftsliste_abfragezahl(self):
        # Die tatsächliche Zahl, gleich bleiben muss sie (Gleichheit, keine Obergrenze).
        DebitorenRechnung.objects.create(vertrag=self.vertrag_a, liegenschaft=self.lg_a, titel='Offen',
                                         betrag=Decimal('900'), datum=date(2024, 1, 1),
                                         faellig_am=date(2024, 1, 5), status='offen')
        self._zaehle('/portal/liegenschaften/')
        self.assertEqual(self._zaehle('/portal/liegenschaften/'), self.ERWARTET_LISTE)

    ERWARTET_LISTE = 24
