"""Die Rolle «Buchhaltung» (Etappe 2, FUNK-08): nur Finanzen.

Debitoren, Kreditoren, Buchungen, Berichte. Keine Stammdaten, keine Verträge,
keine Personen ausser dem, was für Buchungen nötig ist (Mieterkonto). Standard
ist «nein»: Eine View, die die Rolle nicht ausdrücklich nennt, antwortet mit 403.

Aufbau, eine Gruppe je Frage:

* Die Positivliste (`BUCHHALTUNG_DARF`) hält fest, welche Views die Rolle nennen.
  Kommt eine dazu oder fällt eine weg, ist der Test rot und sagt, welche.
* Je Routengruppe: Buchhaltung kommt hinein (Finanzen) bzw. nicht (Stammdaten,
  Verträge, Personen, Einstellungen, Team), mit der Gegenprobe, dass die Seite
  für die Verwaltung existiert (sonst wäre ein 403 ein Tippfehler in der URL).
* Navigation, Palette, Suche, Startseite, Exporte, Portale, API, Mediendateien.
* Mandantentrennung bleibt: fremde IDs ergeben 404.

Gegenprobe der Positivliste: einer View `*FINANZ_LESE_ROLLEN` wegnehmen oder
einer Stammdaten-View hinzufügen, dann nennt `test_positivliste` die Abweichung.
"""
import inspect
import os
import re
import tempfile

from django.test import override_settings
from django.urls import URLResolver, get_resolver

from ._rollen import RollenBasis

#: Alle Views, die die Rolle nennen (Name der Funktion). Absichtlich ausgeschrieben.
BUCHHALTUNG_DARF = {
    # Startseite und Cockpit
    'fw_dashboard', 'fw_finanzen', 'fw_palette_suche',
    # Debitoren
    'fw_debitoren', 'fw_debitor_neu', 'fw_debitor_stornieren', 'fw_debitor_qr_pdf',
    'fw_mieterkonten', 'fw_mieterkonto', 'fw_mieterkonto_pdf', 'fw_kautionen',
    # Kreditoren
    'fw_kreditoren', 'fw_kreditor_neu', 'fw_kreditor_scan', 'fw_kreditor_bearbeiten',
    'fw_kreditor_adresse', 'fw_kreditor_freigeben', 'fw_kreditor_position_add',
    'fw_kreditor_position_del', 'fw_kreditor_bezahlen', 'fw_zahllauf',
    'fw_kreditor_zahlung_zuruecksetzen', 'fw_kreditor_zahlung_stornieren',
    'fw_kreditor_zahlung_vorlegen', 'fw_kreditor_zahlung_zuruecknehmen',
    'fw_lieferantenkonten', 'fw_lieferantenkonto', 'fw_weiterverrechnung',
    # Buchungen und Konten
    'fw_buchhaltung', 'fw_buchhaltung_export', 'fw_buchhaltung_pdf', 'fw_kontoblatt',
    'fw_kontenplan', 'fw_buchung_neu', 'fw_buchung_stornieren', 'fw_anlagen',
    'fw_hypotheken', 'fw_bankkonten', 'fw_mwst', 'fw_mwst_estv_export', 'fw_mwst_verbuchen',
    # Bank und Zahlungen
    'fw_bankabgleich', 'fw_bankabgleich_verbuchen', 'fw_camt_import',
    'fw_bankbewegung_zuordnen', 'fw_zahlung_zuordnen', 'fw_zahlungen_sammel_zuordnen',
    'fw_zahler_zuordnungen', 'fw_zahler_zuordnung_speichern', 'fw_zahlung_aufteilen',
    'fw_zahlung_kaution', 'fw_zahlung_notiz', 'fw_guthaben_verwendung',
    'fw_verrechnung_rueckgaengig', 'fw_zuordnung_aufheben', 'fw_guthaben_wiederherstellen',
    'fw_zahlung_stornieren', 'fw_kontoauszug_rueckgaengig',
    # Läufe der Finanzen und Mahnwesen (lesen, Mahngebühr erfassen)
    'fw_sollstellung', 'fw_sollstellung_run', 'fw_mahnwesen', 'fw_debitoren_aging',
    'fw_mahnung_erfassen',
    # Berichte
    'fw_berichte', 'fw_auswertung', 'fw_betriebsrechnung_pdf',
    # Einstellungen «Daten» (FUNK-13): Buchungsjournal für Banana/Abacus. Der Mandatsexport (alle Personendaten) und der
    # Import bleiben bei Inhaber und Verwalter und stehen deshalb NICHT hier.
    'fw_daten', 'fw_daten_export', 'fw_daten_export_format', 'fw_daten_export_journal',
}

#: Seiten ausserhalb der Finanzen: für die Buchhaltung gesperrt, für die Verwaltung offen.
GESPERRT_GET = [
    '/neu/personen/', '/neu/vertraege/', '/neu/liegenschaften/', '/neu/objekte/', '/neu/mandate/',
    '/neu/dienstleister/', '/neu/dokumente/', '/neu/kommunikation/', '/neu/schaeden/',
    '/neu/bewerbungen/', '/neu/mietzins/', '/neu/nebenkosten/', '/neu/stweg/', '/neu/team/',
    '/neu/benutzer/', '/neu/einstellungen/', '/neu/logbuch/', '/neu/vorlagen/',
    '/neu/integrationen/', '/neu/abonnement/', '/neu/regelwerk/', '/neu/account/',
    '/neu/pendenzen/', '/neu/termine/', '/neu/laeufe/', '/neu/zulauf/',
    '/neu/termine/kalender/', '/neu/portfolio/', '/neu/leerstand/',
    '/neu/mieterwechsel/', '/neu/vermarktung/', '/neu/berichte/betriebskostenspiegel/',
    '/neu/berichte/leerstand-verlauf/', '/neu/suche/', '/neu/betreibungen/neu/{debitor}/',
    '/neu/mahnstufen/', '/neu/mahnwesen/lauf/', '/neu/postfaecher/', '/neu/arbeit/',
    '/neu/personen/{mieter}/', '/neu/vertraege/{vertrag}/',
    '/neu/liegenschaften/{liegenschaft}/', '/neu/objekte/{einheit}/', '/neu/mandate/{eigentuemer}/',
    '/neu/mandate/{eigentuemer}/abrechnung/', '/neu/mandate/{eigentuemer}/auszahlung/',
    '/neu/nebenkosten/{periode}/', '/neu/schaeden/{schaden}/', '/dossier/mieter/{mieter}/',
    '/vertrag/{vertrag}/pdf/', '/abrechnung/{periode}/pdf/', '/neu/vertraege/{vertrag}/kaution-beleg/einzahlung/',
]


def _alle_views():
    """(Muster, Funktionsname, benoetigte_rollen) aller URL-Muster."""
    treffer = []

    def lauf(res, prefix=''):
        for p in res.url_patterns:
            if isinstance(p, URLResolver):
                lauf(p, prefix + str(p.pattern))
            else:
                f = inspect.unwrap(p.callback)
                name = getattr(f, '__name__', None) or f.func.__name__
                treffer.append((prefix + str(p.pattern), name,
                                getattr(p.callback, 'benoetigte_rollen', None)))
    lauf(get_resolver())
    return treffer


class BuchhaltungPositivlisteTests(RollenBasis):

    def test_positivliste(self):
        """Genau diese Views nennen die Buchhaltung — keine mehr, keine weniger."""
        gefunden = {name for _m, name, rollen in _alle_views() if rollen and 'Buchhaltung' in rollen}
        self.assertEqual(
            gefunden, BUCHHALTUNG_DARF,
            f'zu viel: {sorted(gefunden - BUCHHALTUNG_DARF)}; fehlt: {sorted(BUCHHALTUNG_DARF - gefunden)}')

    def test_nur_finanzviews_im_bereich_der_stammdaten(self):
        """Kein Dekorator mit Buchhaltung auf Views von Personen, Verträgen, Objekten."""
        verboten = ('person', 'vertrag', 'liegenschaft', 'objekt', 'mandat', 'eigentuemer',
                    'dienstleister', 'dokument', 'benutzer', 'schaden', 'bewerb', 'betreibung',
                    'kuendigung', 'abnahme', 'stweg', 'vorlage', 'regel', 'einstellung')
        for muster, name, rollen in _alle_views():
            if rollen and 'Buchhaltung' in rollen:
                with self.subTest(view=name):
                    if name in ('fw_mieterkonto_pdf', 'fw_weiterverrechnung'):
                        continue    # Kontoauszug und Weiterverrechnung heissen so, sind aber Finanzen
                    self.assertFalse(any(w in name for w in verboten), muster)


class BuchhaltungZugriffTests(RollenBasis):

    def _ersetze(self, pfad):
        a = self.a
        return pfad.format(debitor=a.debitor.pk, mieter=a.mieter.pk, vertrag=a.vertrag.pk,
                           liegenschaft=a.liegenschaft.pk, einheit=a.einheit.pk,
                           eigentuemer=a.eigentuemer.pk, periode=a.periode.pk, schaden=a.schaden.pk)

    def test_stammdaten_vertraege_personen_sind_gesperrt(self):
        c = self.client_von('buchhaltung')
        v = self.client_von('verwalter')
        for roh in GESPERRT_GET:
            pfad = self._ersetze(roh)
            with self.subTest(pfad=pfad):
                self.assertEqual(c.get(pfad).status_code, 403)
                # Gegenprobe: Für die Verwaltung gibt es die Seite (kein Tippfehler in der URL).
                self.assertNotIn(v.get(pfad).status_code, (403, 404), pfad)

    def test_schreibende_stammdaten_routen_aendern_nichts(self):
        from core.tenancy import organisation_kontext
        from crm.models import Eigentuemer, Mieter
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Mietvertrag

        def stand():
            with organisation_kontext(self.org):
                return tuple(m.objects.count() for m in (Mieter, Liegenschaft, Einheit, Mietvertrag, Eigentuemer))

        c = self.client_von('buchhaltung')
        vorher = stand()
        a = self.a
        for pfad in ('/neu/personen/neu/', '/neu/liegenschaften/neu/', '/neu/objekte/neu/',
                     '/neu/mandate/neu/', '/neu/vertraege/neu/speichern/',
                     f'/neu/personen/{a.mieter.pk}/loeschen/', f'/neu/liegenschaften/{a.liegenschaft.pk}/loeschen/',
                     f'/neu/vertraege/{a.vertrag.pk}/loeschen/', f'/neu/mandate/{a.eigentuemer.pk}/loeschen/',
                     f'/neu/vertraege/{a.vertrag.pk}/kuendigen/', '/neu/benutzer/neu/',
                     f'/neu/personen/{a.mieter.pk}/bearbeiten/', '/neu/datenreset/'):
            with self.subTest(pfad=pfad):
                self.assertEqual(c.post(pfad, {'vorname': 'X', 'nachname': 'Y'}).status_code, 403)
        self.assertEqual(stand(), vorher)

    def test_finanzseiten_sind_offen(self):
        c = self.client_von('buchhaltung')
        a = self.a
        seiten = [
            '/neu/finanzen/', '/neu/debitoren/', '/neu/kreditoren/', '/neu/zahllauf/', '/neu/buchhaltung/',
            '/neu/kontenplan/', '/neu/bankabgleich/', '/neu/bankkonten/', '/neu/mahnwesen/',
            '/neu/mahnwesen/aging/', '/neu/sollstellung/', '/neu/mwst/', '/neu/anlagen/',
            '/neu/hypotheken/', '/neu/kautionen/', '/neu/berichte/', '/neu/auswertung/',
            '/neu/mieterkonten/', f'/neu/mieterkonten/{a.mieter.pk}/', '/neu/lieferantenkonten/',
            '/neu/bankabgleich/zahler/', '/neu/buchhaltung/export/', '/neu/buchhaltung/pdf/',
            f'/neu/buchhaltung/konto/{a.konto_soll.nummer}/',
        ]
        for pfad in seiten:
            with self.subTest(pfad=pfad):
                self.assertEqual(c.get(pfad).status_code, 200, pfad)

    def test_finanz_schreibwege_sind_offen_fuer_buchhaltung_und_zu_fuer_lesezugriff(self):
        """Gegenprobe zum Lesen: Schreibwege nehmen die Buchhaltung an, den Lesezugriff nicht."""
        a = self.a
        wege = [f'/neu/kreditoren/{a.kreditor.pk}/bearbeiten/', '/neu/debitoren/neu/',
                '/neu/buchhaltung/buchung/', '/neu/kreditoren/bezahlen/', '/neu/zahllauf/']
        b, l = self.client_von('buchhaltung'), self.client_von('lesezugriff')
        for pfad in wege:
            with self.subTest(pfad=pfad):
                self.assertNotEqual(b.post(pfad, {}).status_code, 403, pfad)
                self.assertEqual(l.post(pfad, {}).status_code, 403, pfad)

    def test_hauswart_und_sachbearbeiter_gegenprobe_der_finanzseiten(self):
        """Die Rolle wird nicht versehentlich anderen geöffnet/geschlossen."""
        self.assertEqual(self.client_von('hauswart').get('/neu/debitoren/').status_code, 403)
        self.assertEqual(self.client_von('sachbearbeiter').get('/neu/debitoren/').status_code, 200)
        self.assertEqual(self.client_von('lesezugriff').get('/neu/kreditoren/').status_code, 200)

    def test_flags_der_vorlagen(self):
        from core.tenancy import organisation_kontext
        from core.views.fw._basis import _global_filter
        from django.test import RequestFactory

        for rolle, schreiben, finanz, team in (('buchhaltung', False, True, False),
                                               ('sachbearbeiter', True, True, True),
                                               ('lesezugriff', False, False, True)):
            req = RequestFactory().get('/neu/')
            req.user = self.benutzer[rolle]
            with organisation_kontext(self.org):
                ctx = _global_filter(req)
                with self.subTest(rolle=rolle):
                    self.assertEqual(
                        (bool(ctx['kann_schreiben']), bool(ctx['kann_finanz_schreiben']), bool(ctx['ist_team'])),
                        (schreiben, finanz, team))


class BuchhaltungNavigationTests(RollenBasis):

    def test_startseite_ist_das_finanzcockpit(self):
        antwort = self.client_von('buchhaltung').get('/neu/')
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort['Location'], '/neu/finanzen/')

    def test_login_weiche(self):
        antwort = self.client_von('buchhaltung').get('/nach-login/')
        self.assertRedirects(antwort, '/neu/finanzen/', fetch_redirect_response=False)

    def test_navigation_nennt_nur_oeffenbare_ziele(self):
        antwort = self.client_von('buchhaltung').get('/neu/finanzen/')
        self.assertEqual(antwort.status_code, 200)
        gruppen = antwort.context['fw_nav_gruppen']
        schluessel = [g['key'] for g in gruppen]
        self.assertIn('finanzen', schluessel)
        self.assertNotIn('akten', schluessel)
        self.assertNotIn('heute', schluessel)
        c = self.client_von('buchhaltung')
        ziele = [g['ziel'] for g in gruppen] + [it['ziel'] for g in gruppen for it in g['items']]
        ziele += [p['url'] for p in antwort.context['fw_palette']]
        self.assertTrue(ziele)
        for ziel in set(ziele):
            with self.subTest(ziel=ziel):
                self.assertNotEqual(c.get(ziel).status_code, 403, ziel)

    def test_kopfzeile_ohne_werkzeuge_des_teams(self):
        antwort = self.client_von('buchhaltung').get('/neu/finanzen/')
        self.assertTrue(antwort.context['fw_kopf_reduziert'])
        self.assertEqual(antwort.context['fw_kopf_start'], '/neu/finanzen/')
        self.assertNotContains(antwort, '/neu/faelle/neu/')
        self.assertNotContains(antwort, 'href="/neu/einstellungen/')

    def test_gegenprobe_team_sieht_alle_bereiche(self):
        antwort = self.client_von('verwalter').get('/neu/finanzen/')
        schluessel = [g['key'] for g in antwort.context['fw_nav_gruppen']]
        self.assertEqual(schluessel, ['heute', 'akten', 'laeufe', 'finanzen', 'berichte'])
        self.assertFalse(antwort.context.get('fw_kopf_reduziert', False))

    def test_finanzseiten_haben_keine_toten_links(self):
        """Jeder /neu/-Link auf den Finanzseiten ist für die Buchhaltung offen."""
        c = self.client_von('buchhaltung')
        a = self.a
        seiten = ['/neu/finanzen/', '/neu/debitoren/', '/neu/kreditoren/', '/neu/zahllauf/',
                  '/neu/buchhaltung/', '/neu/kontenplan/', '/neu/bankabgleich/', '/neu/bankkonten/',
                  '/neu/mahnwesen/', '/neu/sollstellung/', '/neu/mwst/', '/neu/berichte/',
                  '/neu/kautionen/', '/neu/hypotheken/', f'/neu/mieterkonten/{a.mieter.pk}/',
                  '/neu/mieterkonten/', '/neu/lieferantenkonten/']
        tot = {}
        for seite in seiten:
            html = c.get(seite).content.decode()
            for ziel in set(re.findall(r'href="(/neu/[^"#?]*)', html)):
                if ziel in tot:
                    continue
                status = c.get(ziel).status_code
                if status == 403:
                    tot[ziel] = seite
        self.assertEqual(tot, {}, f'Links in die 403: {tot}')

    def test_gegenprobe_team_behaelt_seine_links(self):
        """Die Links, die der Buchhaltung fehlen, stehen für das Team weiter da."""
        c = self.client_von('verwalter')
        for seite in ('/neu/zahllauf/', '/neu/bankabgleich/', '/neu/mahnwesen/', '/neu/sollstellung/', '/neu/mwst/'):
            with self.subTest(seite=seite):
                self.assertContains(c.get(seite), 'href="/neu/laeufe/')
        self.assertContains(c.get('/neu/mahnwesen/'), 'href="/neu/betreibungen/"')
        self.assertContains(c.get('/neu/mahnwesen/'), 'action="/neu/mahnwesen/lauf/"')
        self.assertNotContains(self.client_von('buchhaltung').get('/neu/mahnwesen/'), 'action="/neu/mahnwesen/lauf/"')

    def test_bericht_ohne_mandatsliste(self):
        html = self.client_von('buchhaltung').get('/neu/berichte/').content.decode()
        self.assertNotIn('/neu/mandate/', html)
        self.assertNotIn(self.a.eigentuemer.firma_oder_name, html)
        team = self.client_von('verwalter').get('/neu/berichte/').content.decode()
        self.assertIn('/neu/mandate/', team)


class BuchhaltungSucheTests(RollenBasis):

    def test_palette_sucht_nur_in_der_buchhaltung(self):
        antwort = self.client_von('buchhaltung').get('/neu/palette/?q=Mieter')
        self.assertEqual(antwort.status_code, 200)
        daten = antwort.json()
        self.assertEqual(set(daten['zahlen']), {'buchhaltung'})
        self.assertTrue(all(t['gruppe'] == 'buchhaltung' for t in daten['treffer']))

    def test_gegenprobe_verwaltung_findet_auch_personen(self):
        daten = self.client_von('verwalter').get('/neu/palette/?q=Mieter').json()
        self.assertIn('personen', daten['zahlen'])

    def test_sicht_und_suchseite(self):
        from core.services.palette_suche import sicht_von
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.org):
            sicht = sicht_von(self.benutzer['buchhaltung'])
        self.assertEqual(sicht.gruppen, ('buchhaltung',))
        self.assertEqual(sicht.suchseite, '/neu/debitoren/')
        self.assertFalse(sicht.nur_hauswart)

    def test_treffer_zeigen_nur_fremdmandant_nicht(self):
        daten = self.client_von('buchhaltung').get(f'/neu/palette/?q={self.b.mieter.nachname}x').json()
        self.assertEqual(daten['treffer'], [])
        namen = ' '.join(t['label'] + t['zusatz'] for t in self.client_von('buchhaltung')
                         .get('/neu/palette/?q=Handwerk').json()['treffer'])
        self.assertIn('Handwerk A', namen)
        self.assertNotIn('Handwerk B', namen)


class BuchhaltungExportUndPortalTests(RollenBasis):

    def test_buchhaltungsexport_geht(self):
        antwort = self.client_von('buchhaltung').get('/neu/buchhaltung/export/')
        self.assertEqual(antwort.status_code, 200)

    def test_personen_und_vertragsexporte_sind_gesperrt(self):
        c = self.client_von('buchhaltung')
        for pfad in ('/neu/personen/?export=csv', '/neu/mieterspiegel/?export=csv',
                     '/neu/vertraege/?export=csv', '/neu/dokumente/?export=csv',
                     '/neu/logbuch/?export=csv', '/neu/fristen/export.ics',
                     f'/neu/kommunikation/serienbrief/'):
            with self.subTest(pfad=pfad):
                self.assertEqual(c.get(pfad).status_code, 403)

    def test_portale_geben_der_buchhaltung_nichts(self):
        c = self.client_von('buchhaltung')
        for pfad in ('/portal/', '/mieter/'):
            with self.subTest(pfad=pfad):
                antwort = c.get(pfad)
                self.assertEqual(antwort.status_code, 302)
                self.assertEqual(antwort['Location'], '/neu/')
        for pfad in ('/portal/report/', '/portal/steuerauszug/', '/portal/kontokorrent/',
                     '/mieter/rechnungen/', '/mieter/dokumente/', '/mieter/konto/'):
            with self.subTest(pfad=pfad):
                antwort = c.get(pfad)
                self.assertNotEqual(antwort.status_code, 200, pfad)

    def test_api_ist_gesperrt(self):
        from django.test import RequestFactory

        from core.auth import auth_lesen, auth_schreiben, auth_verwaltung
        from core.tenancy import organisation_kontext

        for auth in (auth_lesen, auth_schreiben, auth_verwaltung):
            req = RequestFactory().get('/api/x')
            req.user = self.benutzer['buchhaltung']
            with organisation_kontext(self.org):
                with self.subTest(auth=auth.rollen):
                    self.assertIsNone(auth.authenticate(req, None))
        # Gegenprobe: Die Lesepruefung nimmt ein Mitglied des Teams an.
        req = RequestFactory().get('/api/x')
        req.user = self.benutzer['lesezugriff']
        with organisation_kontext(self.org):
            self.assertIsNotNone(auth_lesen.authenticate(req, None))


class BuchhaltungMedienTests(RollenBasis):
    """Kreditorenbelege ja, Ausweise und Verträge nein."""

    def test_belege_ja_vertragsdokumente_nein(self):
        from core.tenancy import organisation_kontext
        from finance.models import KreditorenRechnung
        from rentals.models import Dokument

        with tempfile.TemporaryDirectory() as wurzel, override_settings(MEDIA_ROOT=wurzel):
            oid = self.org.pk
            beleg = f'organisation/{oid}/kreditoren_belege/beleg.pdf'
            vertrag = f'organisation/{oid}/dokumente/vertrag.pdf'
            for rel in (beleg, vertrag):
                os.makedirs(os.path.dirname(os.path.join(wurzel, rel)), exist_ok=True)
                with open(os.path.join(wurzel, rel), 'wb') as f:
                    f.write(b'%PDF-1.4 test')
            with organisation_kontext(self.org):
                k = self.kreditor()
                KreditorenRechnung.objects.filter(pk=k.pk).update(beleg_scan=beleg)
                Dokument.objects.filter(pk=self.a.dokument_rentals.pk).update(datei=vertrag)
            c = self.client_von('buchhaltung')
            self.assertEqual(c.get(f'/media/{beleg}').status_code, 200)
            self.assertEqual(c.get(f'/media/{vertrag}').status_code, 404)
            # Gegenprobe: das Team sieht beides.
            v = self.client_von('verwalter')
            self.assertEqual(v.get(f'/media/{vertrag}').status_code, 200)
            # Ein Beleg der anderen Verwaltung bleibt zu.
            fremd = f'organisation/{self.b.organisation.pk}/kreditoren_belege/beleg.pdf'
            os.makedirs(os.path.dirname(os.path.join(wurzel, fremd)), exist_ok=True)
            with open(os.path.join(wurzel, fremd), 'wb') as f:
                f.write(b'%PDF-1.4 fremd')
            self.assertEqual(c.get(f'/media/{fremd}').status_code, 404)


class BuchhaltungMandantenTests(RollenBasis):
    """Die Buchhaltung von A sieht und ändert nichts von B."""

    def test_fremde_ids_ergeben_404(self):
        c = self.client_von('buchhaltung')
        b = self.b
        for pfad, methode in ((f'/neu/mieterkonten/{b.mieter.pk}/', 'get'),
                              (f'/neu/personen/{b.mieter.pk}/kontoauszug/', 'get'),
                              (f'/neu/kreditoren/{b.kreditor.pk}/bearbeiten/', 'post'),
                              (f'/neu/kreditoren/{b.kreditor.pk}/freigeben/', 'post'),
                              (f'/neu/kreditoren/{b.kreditor.pk}/adresse/', 'get'),
                              (f'/neu/debitoren/{b.debitor.pk}/qr-pdf/', 'get'),
                              (f'/neu/debitoren/{b.debitor.pk}/stornieren/', 'post'),
                              (f'/neu/buchhaltung/buchung/{b.buchung.pk}/stornieren/', 'post')):
            with self.subTest(pfad=pfad):
                antwort = getattr(c, methode)(pfad) if methode == 'get' else c.post(pfad, {})
                self.assertEqual(antwort.status_code, 404, pfad)

    def test_fremde_rechnung_im_body_wird_nicht_bezahlt(self):
        from core.tenancy import organisation_kontext
        from finance.models import KreditorenRechnung
        with organisation_kontext(self.b.organisation):
            fremd = KreditorenRechnung.objects.create(
                lieferant='Fremd', betrag=100, status='freigegeben', liegenschaft=self.b.liegenschaft)
        antwort = self.client_von('buchhaltung').post('/neu/kreditoren/bezahlen/', {'rechnung_id': fremd.pk})
        self.assertEqual(antwort.status_code, 404)
        with organisation_kontext(self.b.organisation):
            fremd.refresh_from_db()
        self.assertEqual(fremd.status, 'freigegeben')


class BuchhaltungRolleVerwaltenTests(RollenBasis):

    def test_inhaber_vergibt_die_rolle(self):
        from crm.models import Mitgliedschaft
        ziel = self.benutzer['lesezugriff']
        c = self.client_von('inhaber')
        c.post(f'/neu/benutzer/{ziel.pk}/bearbeiten/', {'username': ziel.username, 'rolle': 'Buchhaltung'})
        self.assertEqual(Mitgliedschaft.alle_organisationen.get(
            benutzer=ziel, organisation=self.org).rolle, 'Buchhaltung')

    def test_verwalter_darf_keine_rollen_vergeben(self):
        from crm.models import Mitgliedschaft
        ziel = self.benutzer['lesezugriff']
        antwort = self.client_von('verwalter').post(
            f'/neu/benutzer/{ziel.pk}/bearbeiten/', {'username': ziel.username, 'rolle': 'Buchhaltung'})
        self.assertEqual(antwort.status_code, 403)
        self.assertEqual(Mitgliedschaft.alle_organisationen.get(
            benutzer=ziel, organisation=self.org).rolle, 'Lesezugriff')

    def test_formular_bietet_die_rolle_an_und_liste_zeigt_sie(self):
        c = self.client_von('inhaber')
        self.assertContains(c.get('/neu/benutzer/neu/'), '<option value="Buchhaltung"')
        liste = c.get('/neu/benutzer/')
        self.assertContains(liste, 'a_buchhaltung')
        zeile = [r for r in liste.context['rows'] if r['u'].username == 'a_buchhaltung'][0]
        self.assertEqual(zeile['rolle'], 'Buchhaltung')

    def test_rolle_gilt_je_organisation(self):
        """Buchhaltung in A heisst nichts in B (kein Rückfall auf eine globale Gruppe)."""
        from core.auth import hat_rolle
        from core.tenancy import organisation_kontext
        u = self.benutzer['buchhaltung']
        with organisation_kontext(self.org):
            self.assertTrue(hat_rolle(u, ('Buchhaltung',)))
        with organisation_kontext(self.b.organisation):
            self.assertFalse(hat_rolle(u, ('Buchhaltung',)))
