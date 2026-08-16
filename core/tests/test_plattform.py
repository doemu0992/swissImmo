"""Testmodul plattform — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 5 Klassen, unveraendert uebernommen."""
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (_test_organisation,
    _team_user, _basis_objekte, Mieter, Organisation, Liegenschaft, Einheit,
    Mietvertrag, User)



class AbonnementTests(TestCase):
    def test_abo_seite_zeigt_drei_plaene(self):
        Einheit.objects.create(liegenschaft=Liegenschaft.objects.create(organisation=_test_organisation(), 
            strasse='A', plz='1', ort='X', versicherungswert=Decimal('1')),
            bezeichnung='W1', typ='wohnung')
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.get('/neu/abonnement/')
        self.assertEqual(r.status_code, 200)
        for name in ('Start', 'Pro', 'Premium'):
            self.assertContains(r, name)

    def test_plan_waehlen_speichert(self):
        _test_organisation(firma='V AG')
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.post('/neu/abonnement/', {'plan': 'premium'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Organisation.objects.first().abo_plan, 'premium')

    def test_jaehrlich_rabatt(self):
        # 100 Einheiten Pro: monatlich 190, jährlich -15 % -> ~161/Mt
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='B', plz='1', ort='X', versicherungswert=Decimal('1'))
        for i in range(100):
            Einheit.objects.create(liegenschaft=lg, bezeichnung=f'W{i}', typ='wohnung')
        _test_organisation(firma='V AG')
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


class LogbuchTests(TestCase):
    """Audit-Trail / Logbuch: wer hat wann was getan, sichtbar unter /neu/logbuch/,
    mit Filtern, CSV-Export und rollenbasiertem Zugriff."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


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


class FwFassadeTests(TestCase):
    """Etappe 1: Die Fassade `core.views.fw` muss den Split überleben.

    Während der Zerlegung wandern Views und Helfer zwischen Modulen. Nach
    aussen darf davon nichts sichtbar werden — `swiss_immo/urls.py` und diese
    Testdatei importieren unverändert aus `core.views.fw`. Diese Klasse hält
    das fest, damit ein Block nicht stillschweigend einen Namen mitnimmt.
    """

    # Die privaten Helfer, die ausserhalb des Pakets gebraucht werden. Ein
    # Stern-Import überträgt sie NICHT — sie stehen einzeln im __init__.py und
    # sind damit die Stelle, die beim Verschieben am leichtesten bricht.
    PRIVATE = [
        '_auszugscheckliste_anlegen', '_bank_csv_parse', '_bewerber_mail',
        '_camt_kopf', '_camt_parse', '_erfolg_bilanz', '_formulare_prozesse',
        '_num', '_pendenz_ziel',
    ]

    def test_private_helfer_bleiben_erreichbar(self):
        import core.views.fw as fw
        for name in self.PRIVATE:
            with self.subTest(name=name):
                self.assertTrue(hasattr(fw, name),
                                f"core.views.fw.{name} ist beim Zerlegen verlorengegangen")

    def test_alle_url_views_aufloesbar(self):
        # Jede benannte /neu/-URL muss auf ein aufrufbares Objekt zeigen. Das
        # fängt den Fall ab, dass ein Block umzieht und __init__.py ihn nicht
        # re-exportiert — die URL-Konfiguration importiert dann zwar noch, aber
        # der Name käme aus dem falschen Modul oder gar nicht.
        from django.urls import get_resolver
        aufloesbar = 0
        for muster in get_resolver().url_patterns:
            for name, ziel in [(getattr(muster, 'name', None), getattr(muster, 'callback', None))]:
                if name and name.startswith('fw_'):
                    self.assertTrue(callable(ziel), f"{name} zeigt auf nichts Aufrufbares")
                    aufloesbar += 1
        self.assertGreater(aufloesbar, 200, "auffällig wenige fw_-URLs — Fassade kaputt?")

    def test_kein_view_name_doppelt(self):
        # Zwei Module dürfen nicht denselben View definieren: Beim Stern-Import
        # gewinnt sonst stillschweigend der zuletzt importierte.
        import glob, re as _re, collections
        gefunden = collections.defaultdict(list)
        for datei in glob.glob('core/views/fw/*.py'):
            for zeile in open(datei, encoding='utf-8'):
                treffer = _re.match(r'^def (fw_\w+)', zeile)
                if treffer:
                    gefunden[treffer.group(1)].append(datei.split('/')[-1])
        doppelt = {k: v for k, v in gefunden.items() if len(v) > 1}
        self.assertEqual(doppelt, {}, f"View-Namen mehrfach definiert: {doppelt}")
