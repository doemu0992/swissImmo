"""Testmodul oberflaeche — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 13 Klassen, unveraendert uebernommen."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (
    _team_user, _basis_objekte, _seed_konten, Mieter, Liegenschaft, Einheit,
    Mietvertrag, User)



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


class UIConsistencyBatchTests(TestCase):
    """Tabellen-Header, Karten-Radius und Titel-Gewicht sind app-weit einheitlich."""

    def _read(self, name):
        # Bis Etappe 1 wurde der Pfad aus `__file__` zusammengesetzt
        # (core/tests.py → core/templates/fw/). Seit die Tests ein Paket sind,
        # liegt die Datei eine Ebene tiefer und der Pfad zeigte ins Leere.
        #
        # Statt den Pfad zu korrigieren, wird die Vorlage jetzt über Djangos
        # eigenen Loader gesucht: Er findet sie, wo immer sie steht — auch
        # wenn die Templates später umziehen. Ein zusammengebauter Pfad bricht
        # bei jedem Umzug erneut, dieser Weg nie.
        from django.template.loader import get_template
        with open(get_template(f'fw/{name}').origin.name, encoding='utf-8') as fh:
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
        from django.contrib.auth import get_user_model
        User = get_user_model()
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


class FehlerseitenTests(TestCase):
    """Produktionsreife: eigene 404-/500-Seiten statt Djangos nackter
    Standardausgabe. Die 500-Seite muss OHNE Template-Kontext rendern (Django
    ruft sie kontextlos auf) — sonst schlägt der Fehlerfall selbst fehl."""

    def test_404_zeigt_eigene_seite(self):
        # Django nutzt 404.html nur bei DEBUG=False (Testlauf ist ohnehin False).
        c = Client()
        r = c.get('/diese-adresse-gibt-es-nicht/')
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, 'Seite nicht gefunden', status_code=404)
        # Kein Debug-Stacktrace nach aussen.
        self.assertNotContains(r, 'Traceback', status_code=404)

    def test_500_template_rendert_ohne_kontext(self):
        # Django rendert 500.html mit leerem Kontext — hier exakt so nachstellen.
        from django.template.loader import render_to_string
        html = render_to_string('500.html', {})
        self.assertIn('Ein Fehler ist aufgetreten', html)

    def test_403_template_vorhanden(self):
        from django.template.loader import render_to_string
        html = render_to_string('403.html', {})
        self.assertIn('Berechtigung', html)


class HealthzTests(TestCase):
    """Produktionsreife: /healthz/ prüft die DB-Verbindung für Uptime-Monitoring.
    Öffentlich (Monitore können sich nicht anmelden), ohne interne Details."""

    def test_healthz_ok_ohne_login(self):
        c = Client()
        r = c.get('/healthz/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get('status'), 'ok')

    def test_healthz_meldet_db_fehler_als_503(self):
        # Wenn die DB-Abfrage scheitert, muss /healthz/ 503 liefern (nicht 200) —
        # sonst schlägt das Monitoring nie Alarm.
        from unittest.mock import patch
        c = Client()
        with patch('django.db.connection.cursor', side_effect=Exception('db weg')):
            r = c.get('/healthz/')
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json().get('status'), 'error')
        # Kein interner Fehlertext nach aussen.
        self.assertNotIn('db weg', r.content.decode())


class FaviconKonsistenzTests(TestCase):
    """Design: die aussenwirksamen Standalone-Seiten (Login, Portale,
    Fehlerseiten) tragen dasselbe Favicon wie das Cockpit — sonst zeigen
    Eigentümer/Mieter einen leeren Browser-Tab ohne Markenbezug.

    Prüft die Template-Quelle direkt (kein Rendern nötig) — so bleibt der Test
    stabil und schlägt an, wenn eine dieser Seiten das Favicon verliert."""

    AUSSEN_TEMPLATES = [
        'core/login.html', 'core/portal_login.html',
        'core/portal_base.html', 'core/portal.html',
        '403.html', '404.html', '500.html',
    ]

    def test_alle_aussen_seiten_haben_favicon(self):
        from django.template.loader import get_template
        for name in self.AUSSEN_TEMPLATES:
            quelle = get_template(name).template.source
            self.assertIn('rel="icon"', quelle, f'{name}: kein Favicon-Link')
            self.assertIn('>si</text>', quelle, f'{name}: nicht das Haus-Favicon')

    def test_login_seite_liefert_favicon(self):
        # End-to-End: die Login-Seite (ohne Anmeldung erreichbar) rendert das Favicon.
        r = Client().get('/login/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'rel="icon"')
