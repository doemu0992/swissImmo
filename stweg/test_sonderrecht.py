"""Sonderrecht oder Gemeinschaftseigentum (Art. 712b ZGB): Deklaration Pflicht, zwingend Gemeinschaftliches nie auf einen
einzelnen Eigentümer — weder im Ticket noch in der Jahresabrechnung."""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.tests._helfer import _team_user
from crm.models import Handwerker
from finance.models import KreditorenRechnung
from stweg import bauteile, integritaet
from stweg.services import StwegAbrechnungService
from stweg.tests import neue_stweg
from tickets import workflow
from tickets.models import HandwerkerAuftrag, SchadenMeldung

D = Decimal
ZWINGEND = ('dach', 'fassade', 'fenster_aussen', 'tragend', 'hauptleitung', 'treppenhaus', 'anlage', 'aussenbereich')
SONDER = ('fenster_innen', 'innenwand', 'bodenbelag', 'oberflaeche', 'kueche_sanitaer', 'leitung_einheit',
          'tuer_innen', 'sonstiges')


def ticket(lg, einheit=None, **kw):
    return SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=einheit, titel=kw.pop('titel', 'Schaden'),
                                         beschreibung='x', **kw)


class KatalogTests(TestCase):
    def test_zwingend_und_sonderrechtsfaehig(self):
        for b in ZWINGEND:
            self.assertTrue(bauteile.ist_zwingend(b), b)
        for b in SONDER:
            self.assertFalse(bauteile.ist_zwingend(b), b)
        self.assertEqual(set(ZWINGEND) | set(SONDER), set(bauteile.BAUTEILE))
        self.assertFalse(bauteile.ist_zwingend(''))

    def test_die_drei_beispiele_des_auftrags(self):
        for b in ('fenster_aussen', 'dach', 'fassade'):
            self.assertIn('Art. 712b', bauteile.sperre(b, 'sonderrecht'))
            self.assertIsNone(bauteile.sperre(b, 'gemeinschaftlich'))

    def test_sonderrechtsfaehiges_bauteil_darf_sonderrecht_sein(self):
        for b in SONDER:
            self.assertIsNone(bauteile.sperre(b, 'sonderrecht'), b)


class TicketTests(TestCase):
    def setUp(self):
        self.lg, self.e = neue_stweg(status='aktiv')
        self.hw = Handwerker.objects.create(firma='Dach AG', email='d@x.ch')

    def test_zwingendes_bauteil_als_sonderrecht_wird_nicht_gespeichert(self):
        for b in ZWINGEND:
            with self.assertRaises(ValidationError) as ctx:
                ticket(self.lg, self.e[0], bauteil=b, kostentraeger='sonderrecht')
            self.assertIn('zwingend gemeinschaftliches Eigentum', ' '.join(ctx.exception.messages))
        self.assertEqual(SchadenMeldung.objects.count(), 0)

    def test_nachtraeglich_aendern_wird_ebenfalls_gesperrt(self):
        t = ticket(self.lg, self.e[0], bauteil='dach', kostentraeger='gemeinschaftlich')
        t.kostentraeger = 'sonderrecht'
        with self.assertRaises(ValidationError):
            t.save()
        t.refresh_from_db()
        self.assertEqual(t.kostentraeger, 'gemeinschaftlich')

    def test_ohne_deklaration_kein_auftrag_und_kein_abschluss(self):
        t = ticket(self.lg, self.e[0])
        with self.assertRaises(workflow.KostentraegerFehlt):
            workflow.handwerker_zuweisen(t, self.hw)
        t.status = 'erledigt'
        with self.assertRaises(workflow.KostentraegerFehlt):
            t.save()
        self.assertFalse(HandwerkerAuftrag.objects.exists())

    def test_deklariert_darf_beauftragt_werden(self):
        t = ticket(self.lg, self.e[0], bauteil='bodenbelag', kostentraeger='sonderrecht')
        workflow.handwerker_zuweisen(t, self.hw)
        self.assertEqual(HandwerkerAuftrag.objects.count(), 1)

    def test_sonderrecht_braucht_die_betroffene_einheit(self):
        t = ticket(self.lg, None, bauteil='bodenbelag', kostentraeger='sonderrecht')
        self.assertTrue(any('betroffene Einheit' in p for p in bauteile.probleme(t)))
        with self.assertRaises(workflow.KostentraegerFehlt):
            workflow.handwerker_zuweisen(t, self.hw)

    def test_ausserhalb_einer_stweg_aendert_sich_nichts(self):
        from portfolio.models import Liegenschaft
        from stweg.tests import _test_organisation
        lg = Liegenschaft.objects.create(strasse='Mietweg 1', plz='8000', ort='Zürich', typ='MFH',
                                         organisation=_test_organisation())
        t = ticket(lg)
        workflow.handwerker_zuweisen(t, self.hw)                 # keine Deklaration nötig
        self.assertEqual(bauteile.probleme(t), [])


class OberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e = neue_stweg(status='aktiv')
        self.t = ticket(self.lg, self.e[0])
        self.c = self.client_class()
        self.c.force_login(_team_user('Verwaltung'))
        self.url = f'/neu/schaeden/{self.t.pk}/kostentraeger/'

    def test_warnung_und_sperre_bei_dach_als_sonderrecht(self):
        r = self.c.post(self.url, {'bauteil': 'dach', 'kostentraeger': 'sonderrecht'}, follow=True)
        self.assertContains(r, 'zwingend gemeinschaftliches Eigentum')
        self.t.refresh_from_db()
        self.assertEqual(self.t.kostentraeger, '')

    def test_deklarieren_und_anzeigen(self):
        r = self.c.post(self.url, {'bauteil': 'dach', 'kostentraeger': 'gemeinschaftlich'}, follow=True)
        self.assertContains(r, 'Kostenträger gespeichert')
        self.t.refresh_from_db()
        self.assertEqual((self.t.bauteil, self.t.kostentraeger), ('dach', 'gemeinschaftlich'))

    def test_detailseite_zeigt_die_karte_mit_den_bauteilen(self):
        seite = self.c.get(f'/neu/schaeden/{self.t.pk}/')
        self.assertContains(seite, 'Kostenträger (STWEG)')
        self.assertContains(seite, 'Fenster (Aussenseite)')
        self.assertContains(seite, 'zwingend gemeinschaftlich')
        self.assertContains(seite, 'nicht deklariert')

    def test_unvollstaendig_wird_abgewiesen(self):
        self.c.post(self.url, {'bauteil': 'dach', 'kostentraeger': ''})
        self.t.refresh_from_db()
        self.assertEqual(self.t.bauteil, '')

    def test_intern_erfassen_verlangt_die_deklaration(self):
        n = SchadenMeldung.objects.count()
        self.c.post('/neu/schaeden/neu/', {'titel': 'Leck', 'liegenschaft_id': self.lg.pk})
        self.assertEqual(SchadenMeldung.objects.count(), n)
        self.c.post('/neu/schaeden/neu/', {'titel': 'Leck', 'liegenschaft_id': self.lg.pk, 'bauteil': 'dach',
                                           'kostentraeger': 'sonderrecht'})
        self.assertEqual(SchadenMeldung.objects.count(), n)                       # gesperrt
        self.c.post('/neu/schaeden/neu/', {'titel': 'Leck', 'liegenschaft_id': self.lg.pk, 'bauteil': 'dach',
                                           'kostentraeger': 'gemeinschaftlich'})
        self.assertEqual(SchadenMeldung.objects.count(), n + 1)

    def test_nur_schreibende_duerfen_deklarieren(self):
        c = self.client_class()
        c.force_login(_team_user('Lesend'))
        c.post(self.url, {'bauteil': 'dach', 'kostentraeger': 'gemeinschaftlich'})
        self.t.refresh_from_db()
        self.assertEqual(self.t.bauteil, '')


class JahresabrechnungTests(TestCase):
    """Die Rechnung nennt eine Einheit — gehört sie zu einem gemeinschaftlichen Ticket, zahlen trotzdem alle."""

    def setUp(self):
        self.lg, self.e = neue_stweg(quoten=(200, 300, 500), status='aktiv')
        self.hw = Handwerker.objects.create(firma='Dach AG', email='d@x.ch')

    def rechnung_zu_ticket(self, **ticket_felder):
        t = ticket(self.lg, self.e[0], **ticket_felder)
        r = KreditorenRechnung.objects.create(liegenschaft=self.lg, einheit=self.e[0], lieferant='Dach AG',
                                              betrag=D('1000'), datum=date(2026, 6, 1), status='freigegeben')
        HandwerkerAuftrag.objects.create(ticket=t, handwerker=self.hw, kreditoren_rechnung=r)
        return t, r

    def test_dach_wird_nie_einem_einzelnen_eigentuemer_belastet(self):
        self.rechnung_zu_ticket(bauteil='dach', kostentraeger='gemeinschaftlich')
        s = StwegAbrechnungService(self.lg)
        self.assertEqual(s.allgemeine_kosten(2026), D('1000.00'))
        self.assertEqual(s.einzelkosten(2026), [])

    def test_auch_ein_falsch_deklariertes_ticket_schuetzt_bei_zwingendem_bauteil(self):
        t, _ = self.rechnung_zu_ticket(bauteil='fassade', kostentraeger='gemeinschaftlich')
        SchadenMeldung.objects.filter(pk=t.pk).update(kostentraeger='sonderrecht')     # umgeht save() (update)
        s = StwegAbrechnungService(self.lg)
        self.assertEqual(s.einzelkosten(2026), [])
        self.assertEqual(s.allgemeine_kosten(2026), D('1000.00'))

    def test_auch_rechnungen_mit_positionen_werden_geschuetzt(self):
        from finance.booking import konto
        from finance.models import KreditorPosition
        t, r = self.rechnung_zu_ticket(bauteil='dach', kostentraeger='gemeinschaftlich')
        KreditorPosition.objects.create(rechnung=r, konto=konto('4000'), bezeichnung='Ziegel', betrag=D('600'), einheit=self.e[0],
                                        liegenschaft=self.lg)
        KreditorPosition.objects.create(rechnung=r, konto=konto('4000'), bezeichnung='Arbeit', betrag=D('400'), einheit=self.e[0],
                                        liegenschaft=self.lg)
        s = StwegAbrechnungService(self.lg)
        self.assertEqual(s.einzelkosten(2026), [])
        self.assertEqual(s.allgemeine_kosten(2026), D('1000.00'))
        SchadenMeldung.objects.filter(pk=t.pk).update(bauteil='bodenbelag', kostentraeger='sonderrecht')
        self.assertEqual(sorted(z['betrag'] for z in s.einzelkosten(2026)), [D('400.00'), D('600.00')])

    def test_sonderrecht_bleibt_beim_eigentuemer(self):
        self.rechnung_zu_ticket(bauteil='bodenbelag', kostentraeger='sonderrecht')
        s = StwegAbrechnungService(self.lg)
        self.assertEqual(s.allgemeine_kosten(2026), D('0.00'))
        self.assertEqual([z['betrag'] for z in s.einzelkosten(2026)], [D('1000.00')])
        self.assertEqual(s.einzelkosten(2026)[0]['einheit'], self.e[0])

    def test_rechnung_ohne_ticket_wie_bisher(self):
        KreditorenRechnung.objects.create(liegenschaft=self.lg, einheit=self.e[1], lieferant='X', betrag=D('50'),
                                          datum=date(2026, 6, 1), status='freigegeben')
        s = StwegAbrechnungService(self.lg)
        self.assertEqual([z['betrag'] for z in s.einzelkosten(2026)], [D('50.00')])


class AuditTests(TestCase):
    def test_offene_schaeden_ohne_kostentraeger_sind_eine_warnung(self):
        lg, e = neue_stweg(status='aktiv')
        ticket(lg, e[0])
        self.assertTrue(any('ohne Kostenträger' in t for _, t in integritaet.pruefe(lg)))
        SchadenMeldung.objects.update(bauteil='dach', kostentraeger='gemeinschaftlich')
        self.assertFalse(any('ohne Kostenträger' in t for _, t in integritaet.pruefe(lg)))
