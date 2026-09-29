"""Etappe 4 aus docs/AUDIT-SAAS-NIVEAU.md: Listen-Werkzeugkasten.

Liegenschaften, Objekte, Mietverhältnisse, Personen. Vorher: alle Zeilen auf
einer Seite, Suche teils nur im Browser, eine feste Reihenfolge, kein Export.
Jetzt: Suche auf dem Server, wählbare Sortierung, Seiten, CSV mit denselben
Filtern und allen Zeilen.
"""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase

from crm.models import Eigentuemer, Mieter
from rentals.models import Mietvertrag
from portfolio.models import Einheit, Liegenschaft

from ._helfer import _team_user, _test_organisation

PFAD = '/neu/liegenschaften/'


def _lg(strasse, ort='Zürich', plz='8000', **felder):
    return Liegenschaft.objects.create(strasse=strasse, plz=plz, ort=ort,
                                       organisation=_test_organisation(), **felder)


def _csv(antwort):
    text = antwort.content.decode('utf-8')
    return list(csv.reader(io.StringIO(text.lstrip('﻿')), delimiter=';'))


class LiegenschaftslisteSeiten(TestCase):

    def setUp(self):
        # 60 Liegenschaften: zwei Seiten zu 50 und 10. In `setUp`, nicht in
        # `setUpTestData`: `_test_organisation` setzt den Mandantenkontext, und
        # nur `setUp` läuft in der Kontextkopie des Test-Runners — auf
        # Klassenebene blieb er für die folgenden Module stehen (gemessen:
        # 14 rote Isolationstests).
        for i in range(60):
            _lg(f'Musterweg {i:02d}')
        self.c = Client()
        self.c.force_login(_team_user())

    def _strassen(self, antwort):
        return [r['lg'].strasse for r in antwort.context['rows']]

    def test_erste_seite_hat_fuenfzig_zeilen(self):
        r = self.c.get(PFAD + '?sort=adresse')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['rows']), 50)
        body = r.content.decode()
        self.assertIn('class="fw-seiten"', body)
        # Sortierung bleibt beim Blättern erhalten.
        self.assertIn('href="?sort=adresse&amp;seite=2"', body)

    def test_zweite_seite_hat_den_rest(self):
        r = self.c.get(PFAD + '?sort=adresse&seite=2')
        self.assertEqual(self._strassen(r), [f'Musterweg {i:02d}' for i in range(50, 60)])

    def test_unsinnige_seite_faellt_nicht_auf_leere_liste(self):
        r = self.c.get(PFAD + '?seite=abc')
        self.assertEqual(r.context['seite'].number, 1)
        r = self.c.get(PFAD + '?seite=999')
        self.assertEqual(r.context['seite'].number, 2)

    def test_csv_enthaelt_alle_zeilen_nicht_nur_die_seite(self):
        r = self.c.get(PFAD + '?sort=adresse&seite=2&export=csv')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment;', r['Content-Disposition'])
        zeilen = _csv(r)
        self.assertEqual(len(zeilen), 61)          # Kopf + 60
        self.assertEqual(zeilen[1][0], 'Musterweg 00')

    def test_kein_sofortfilter_bei_mehreren_seiten(self):
        """Er fände nur die aktuelle Seite und behauptete dann «nichts da»."""
        body = self.c.get(PFAD).content.decode()
        self.assertNotIn('data-suche="#lgListe"', body)

    def test_suche_findet_auch_ausserhalb_der_ersten_seite(self):
        """Der alte Filter im Browser sah nur die aktuelle Seite."""
        r = self.c.get(PFAD + '?suche=Musterweg+57')
        self.assertEqual(self._strassen(r), ['Musterweg 57'])


class LiegenschaftslisteSucheSortierungExport(TestCase):

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user())
        org = _test_organisation()
        self.eig = Eigentuemer.objects.create(organisation=org, firma_oder_name='Anlagestiftung Aare')
        self.bern = _lg('Bahnhofstrasse 1', ort='Bern', plz='3011', kanton='BE', eigentuemer=self.eig)
        self.zuerich = _lg('Bahnhofstrasse 9', ort='Zürich', plz='8001', kanton='ZH')
        self.aarau = _lg('Aeschenweg 3', ort='Aarau', plz='5000', kanton='AG')
        for i in range(3):
            Einheit.objects.create(liegenschaft=self.aarau, bezeichnung=f'W{i}', typ='whg',
                                   nettomiete_aktuell=Decimal('1000'))

    def _ids(self, antwort):
        return [r['lg'].id for r in antwort.context['rows']]

    def test_mehrere_woerter_grenzen_ein(self):
        r = self.c.get(PFAD + '?suche=bahnhof+bern')
        self.assertEqual(self._ids(r), [self.bern.id])

    def test_suche_findet_eigentuemer(self):
        r = self.c.get(PFAD + '?suche=anlagestiftung')
        self.assertEqual(self._ids(r), [self.bern.id])

    def test_leere_suche_zeigt_eigenen_leeren_zustand(self):
        r = self.c.get(PFAD + '?suche=gibtsnicht')
        body = r.content.decode()
        self.assertIn('Keine Liegenschaft gefunden', body)
        self.assertNotIn('Noch keine Liegenschaften', body)

    def test_sortierung_nach_ort(self):
        r = self.c.get(PFAD + '?sort=ort')
        self.assertEqual(self._ids(r), [self.aarau.id, self.bern.id, self.zuerich.id])

    def test_hausnummern_als_zahlen(self):
        neun = _lg('Seeweg 9')
        zehn = _lg('Seeweg 10')
        ids = self._ids(self.c.get(PFAD + '?sort=adresse'))
        self.assertLess(ids.index(neun.id), ids.index(zehn.id))

    def test_sortierung_nach_objekten_absteigend(self):
        r = self.c.get(PFAD + '?sort=objekte')
        self.assertEqual(self._ids(r)[0], self.aarau.id)

    def test_unbekannte_sortierung_faellt_auf_befund(self):
        r = self.c.get(PFAD + '?sort=__class__')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['sort'], 'befund')

    def test_chips_behalten_suche_und_sortierung(self):
        r = self.c.get(PFAD + '?suche=bahnhof&sort=ort&seite=2')
        urls = r.context['filter_urls']
        self.assertEqual(urls['leer'], '?suche=bahnhof&sort=ort&befund=leer')
        # «Alle» hebt nur den Befund auf, nicht die Suche.
        self.assertEqual(urls['alle'], '?suche=bahnhof&sort=ort')

    def test_chipzahlen_folgen_der_suche(self):
        r = self.c.get(PFAD + '?suche=bahnhof')
        self.assertEqual(r.context['gesucht_rows'], 2)
        self.assertEqual(r.context['filter_zaehler']['ohne'], 2)

    def test_csv_folgt_suche_und_sortierung(self):
        r = self.c.get(PFAD + '?suche=bahnhof&sort=ort&export=csv')
        zeilen = _csv(r)
        self.assertEqual([z[0] for z in zeilen[1:]], ['Bahnhofstrasse 1', 'Bahnhofstrasse 9'])
        self.assertEqual(zeilen[1][4], 'Anlagestiftung Aare')

    def test_csv_fuer_excel(self):
        r = self.c.get(PFAD + '?export=csv')
        self.assertTrue(r.content.startswith('﻿'.encode('utf-8')))
        kopf = _csv(r)[0]
        self.assertEqual(kopf[0], 'Strasse')
        zeile = next(z for z in _csv(r)[1:] if z[0] == 'Aeschenweg 3')
        # Zahlen ohne «CHF» und ohne Tausendertrennzeichen — die Spalte rechnet.
        self.assertEqual(zeile[5], '3')
        self.assertRegex(zeile[9], r'^\d+\.\d{2}$')

    def test_csv_entschaerft_formeln(self):
        """Eine Strasse «=HYPERLINK(…)» wäre in Excel ein aktiver Link."""
        _lg('=HYPERLINK("http://x.test","klick")')
        zeilen = _csv(self.c.get(PFAD + '?export=csv'))
        strassen = [z[0] for z in zeilen[1:]]
        self.assertIn('\'=HYPERLINK("http://x.test","klick")', strassen)
        self.assertNotIn('=HYPERLINK("http://x.test","klick")', strassen)

    def test_csv_nur_eigene_liegenschaften(self):
        from core.tenancy import organisation_kontext
        from crm.models import Organisation
        fremd = Organisation.objects.create(firma='Fremdverwaltung AG', strasse='X 1', plz='9000', ort='St. Gallen')
        with organisation_kontext(fremd):
            Liegenschaft.objects.create(strasse='Fremdgasse 7', plz='9000', ort='St. Gallen',
                                        organisation=fremd)
        strassen = [z[0] for z in _csv(self.c.get(PFAD + '?export=csv'))[1:]]
        self.assertNotIn('Fremdgasse 7', strassen)
        self.assertEqual(len(strassen), 3)

    def test_formular_behaelt_befund_beim_suchen(self):
        body = self.c.get(PFAD + '?befund=leer&sort=ort').content.decode()
        form = body[body.index('class="fw-listwerkzeug"'):]
        form = form[:form.index('</form>')]
        self.assertIn('<input type="hidden" name="befund" value="leer">', form)
        # `sort` steht als Auswahl im Formular, nicht zusätzlich verdeckt.
        self.assertNotIn('type="hidden" name="sort"', form)

    def test_eine_seite_zeigt_keine_blaetterleiste(self):
        body = self.c.get(PFAD).content.decode()
        self.assertNotIn('class="fw-seiten"', body)


class LiegenschaftslisteAbfragen(TestCase):
    """Die Zeile zeigt den Eigentümer — ohne `select_related` eine Abfrage
    je Liegenschaft."""

    def test_abfragen_wachsen_nicht_mit_den_eigentuemern(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        c = Client()
        c.force_login(_team_user())
        org = _test_organisation()

        def zaehlen():
            c.get(PFAD)          # Sitzung und Zwischenspeicher warm
            with CaptureQueriesContext(connection) as q:
                c.get(PFAD)
            return len(q)

        _lg('Erste 1', eigentuemer=Eigentuemer.objects.create(organisation=org, firma_oder_name='E1'))
        eine = zaehlen()
        for i in range(4):
            _lg(f'Weitere {i}', eigentuemer=Eigentuemer.objects.create(
                organisation=org, firma_oder_name=f'E{i + 2}'))
        self.assertEqual(zaehlen(), eine)


def _mieter(nachname, **felder):
    return Mieter.objects.create(typ='person', vorname='Vera', nachname=nachname,
                                 organisation=_test_organisation(), **felder)


def _vertrag(mieter, einheit, beginn, **felder):
    werte = {'netto_mietzins': Decimal('1000'), 'nebenkosten': Decimal('100'), 'status': 'aktiv'}
    werte.update(felder)
    return Mietvertrag.objects.create(mieter=mieter, einheit=einheit, beginn=beginn,
                                      organisation=_test_organisation(), **werte)


class Vertragsliste(TestCase):
    PFAD = '/neu/vertraege/'

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user())
        lg = _lg('Hofweg 1')
        self.einheiten = [Einheit.objects.create(liegenschaft=lg, bezeichnung=f'W{i:02d}', typ='whg')
                          for i in range(55)]
        heute = date.today()
        self.vertraege = [
            _vertrag(_mieter(f'Muster{i:02d}'), e, date(2020, 1, 1) + timedelta(days=i))
            for i, e in enumerate(self.einheiten)]
        # Einer gekündigt mit nahem Ende, einer mit höchster Miete.
        self.bald = self.vertraege[3]
        self.bald.status = 'gekuendigt'
        self.bald.ende = heute + timedelta(days=10)
        self.bald.save()
        self.teuer = self.vertraege[7]
        self.teuer.netto_mietzins = Decimal('4000')
        self.teuer.save()

    def _ids(self, r):
        return [z['v'].id for z in r.context['rows']]

    def test_seiten_zu_fuenfzig(self):
        r = self.c.get(self.PFAD)
        self.assertEqual(len(r.context['rows']), 50)
        self.assertEqual(r.context['treffer'], 55)
        r = self.c.get(self.PFAD + '?seite=2')
        self.assertEqual(len(r.context['rows']), 5)

    def test_kopfzahlen_zaehlen_alle_nicht_die_seite(self):
        r = self.c.get(self.PFAD)
        self.assertEqual(r.context['aktiv_count'], 54)
        self.assertIn('55 Verträge', r.content.decode())

    def test_sortierung_naechstes_ende(self):
        r = self.c.get(self.PFAD + '?sort=ende')
        self.assertEqual(self._ids(r)[0], self.bald.id)

    def test_sortierung_hoechste_miete(self):
        r = self.c.get(self.PFAD + '?sort=miete')
        self.assertEqual(self._ids(r)[0], self.teuer.id)

    def test_jede_sortierung_endet_mit_id(self):
        """Ohne `id` als letzten Schlüssel darf die Datenbank Gleichstände
        beliebig ordnen — ein Vertrag stünde dann auf zwei Seiten und ein
        anderer auf keiner. SQLite ordnet sie zufällig gleich, Postgres nicht;
        deshalb wird die Regel geprüft und nicht das Verhalten im Test."""
        from core.views.fw.listen import PERSON_SORTEN, VERTRAG_SORTEN
        for name, sorten in (('Verträge', VERTRAG_SORTEN), ('Personen', PERSON_SORTEN)):
            for key, s in sorten.items():
                self.assertIn(s.felder[-1], ('id', '-id'), f'{name}: Sortierung «{key}»')

    def test_csv_alle_zeilen_mit_filter(self):
        r = self.c.get(self.PFAD + '?status=gekuendigt&export=csv')
        zeilen = _csv(r)
        self.assertEqual(len(zeilen), 2)
        self.assertEqual(zeilen[1][3], self.bald.beginn.strftime('%d.%m.%Y'))
        self.assertEqual(zeilen[1][7], '1100.00')
        self.assertEqual(len(_csv(self.c.get(self.PFAD + '?seite=2&export=csv'))), 56)

    def test_chips_behalten_suche_und_sortierung(self):
        r = self.c.get(self.PFAD + '?q=Muster&sort=ende&seite=2')
        urls = {k: u for k, _l, u in r.context['status_chips']}
        self.assertEqual(urls['aktiv'], '?q=Muster&sort=ende&status=aktiv')

    def test_seite_liest_nur_ihre_zeilen(self):
        """Die Datenbank blättert (LIMIT), und die Vertragszeile löst keine
        Abfrage je Vertrag aus (Mieter und Liegenschaft per select_related)."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.c.get(self.PFAD)
        with CaptureQueriesContext(connection) as q:
            self.c.get(self.PFAD)
        tabelle = f'FROM "{Mietvertrag._meta.db_table}"'
        vertragsabfragen = [x['sql'] for x in q.captured_queries
                            if tabelle in x['sql'] and 'LIMIT 50' in x['sql']]
        self.assertEqual(len(vertragsabfragen), 1)
        self.assertIn(f'"{Mieter._meta.db_table}"', vertragsabfragen[0])
        # Keine zweite Abfrage, die alle Verträge liest (ohne LIMIT, ohne COUNT).
        alle = [x['sql'] for x in q.captured_queries
                if tabelle in x['sql'] and 'LIMIT' not in x['sql'] and 'COUNT(' not in x['sql']]
        self.assertEqual(alle, [])


class Personenliste(TestCase):
    PFAD = '/neu/personen/'

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user())
        self.personen = [_mieter(f'Person{i:02d}', ort='Bern' if i % 2 else 'Aarau',
                                 email=f'p{i}@example.ch', ahv_nummer='756.1234.5678.97',
                                 iban='CH9300762011623852957')
                         for i in range(55)]

    def test_seiten_und_kopfzahl(self):
        r = self.c.get(self.PFAD)
        self.assertEqual(len(r.context['rows']), 50)
        self.assertEqual(r.context['treffer'], 55)
        self.assertIn('class="fw-seiten"', r.content.decode())

    def test_kein_sofortfilter_bei_mehreren_seiten(self):
        self.assertNotIn('data-suche="#personenListe"', self.c.get(self.PFAD).content.decode())

    def test_sofortfilter_auf_einer_seite(self):
        body = self.c.get(self.PFAD + '?q=Person0').content.decode()
        self.assertIn('data-suche="#personenListe"', body)
        self.assertIn('data-zeile', body)

    def test_sortierung_nach_ort(self):
        r = self.c.get(self.PFAD + '?sort=ort')
        self.assertEqual(r.context['rows'][0]['m'].ort, 'Aarau')

    def test_zahl_mit_vertrag_zaehlt_ueber_alle_seiten(self):
        lg = _lg('Zaehlweg 1')
        for m in (self.personen[1], self.personen[54]):     # Seite 1 und Seite 2
            _vertrag(m, Einheit.objects.create(liegenschaft=lg, bezeichnung=f'Z{m.id}', typ='whg'),
                     date(2024, 1, 1))
        self.assertEqual(self.c.get(self.PFAD).context['mit_vertrag_count'], 2)

    def test_csv_nur_kontaktdaten(self):
        """AHV-Nummer und IBAN gehören nicht in eine weitergereichte Liste."""
        r = self.c.get(self.PFAD + '?export=csv')
        text = r.content.decode('utf-8')
        self.assertEqual(len(_csv(r)), 56)
        self.assertIn('p0@example.ch', text)
        self.assertNotIn('756.1234', text)
        self.assertNotIn('CH9300762011623852957', text)

    def test_csv_wird_protokolliert(self):
        from core.models import AktivitaetsLog
        self.c.get(self.PFAD + '?typ=person&export=csv')
        eintrag = AktivitaetsLog.objects.latest('id')
        self.assertIn('Personenliste', eintrag.aktion)
        self.assertIn('55', eintrag.objekt)
        self.assertIn('typ=person', eintrag.details)

    def test_csv_nur_eigene_personen(self):
        from core.tenancy import organisation_kontext
        from crm.models import Organisation
        fremd = Organisation.objects.create(firma='Fremd AG', strasse='X 1', plz='9000', ort='St. Gallen')
        with organisation_kontext(fremd):
            Mieter.objects.create(typ='person', vorname='Fritz', nachname='Fremdling', organisation=fremd)
        text = self.c.get(self.PFAD + '?export=csv').content.decode('utf-8')
        self.assertNotIn('Fremdling', text)


class Objektliste(TestCase):
    PFAD = '/neu/objekte/'

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user())
        for i in range(25):
            lg = _lg(f'Gasse {i:02d}')
            for j in range(2):
                Einheit.objects.create(liegenschaft=lg, bezeichnung=f'G{i:02d}-{j}', typ='whg',
                                       zimmer=Decimal('3.5'), nettomiete_aktuell=Decimal('1200'))

    def test_seiten_in_ganzen_liegenschaften(self):
        r = self.c.get(self.PFAD)
        gruppen = r.context['gruppen']
        self.assertEqual(len(gruppen), 20)
        self.assertTrue(all(g['anzahl'] == 2 for g in gruppen))
        r = self.c.get(self.PFAD + '?seite=2')
        self.assertEqual(len(r.context['gruppen']), 5)

    def test_csv_alle_objekte(self):
        zeilen = _csv(self.c.get(self.PFAD + '?seite=2&export=csv'))
        self.assertEqual(len(zeilen), 51)
        zeile = zeilen[1]
        self.assertEqual(zeile[5], '3.5')
        self.assertEqual(zeile[8], '1200.00')

    def test_kein_zweites_suchfeld(self):
        """Entscheid G9: Die Objektliste sucht über die Kopfzeile."""
        self.assertNotIn('class="fw-listwerkzeug', self.c.get(self.PFAD).content.decode())
