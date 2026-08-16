"""Testmodul pendenzen — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 9 Klassen, unveraendert uebernommen."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (_test_organisation,
    _team_user, _basis_objekte, Mieter, Organisation, Liegenschaft, Einheit,
    Wartungsfrist, Mietvertrag, User, Group)



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


class PendenzAktionTests(TestCase):
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren

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
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Bahnhofstrasse 1', plz='8000', ort='Zürich',
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


class FristenCenterTests(TestCase):
    """Fristen-Center bündelt datierte Pendenzen chronologisch in Zeitfenster."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


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


class FristenKalenderTests(TestCase):
    """iCal-Export (Download + Feed) und wöchentliches Fristen-Mail."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


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
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        User = get_user_model()
        grp, _ = Group.objects.get_or_create(name='Verwalter')
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
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        User = get_user_model()
        grp, _ = Group.objects.get_or_create(name='Verwalter')
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
