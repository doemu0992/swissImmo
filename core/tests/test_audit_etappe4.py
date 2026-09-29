"""Etappe 4 aus docs/AUDIT-SAAS-NIVEAU.md: Listen-Werkzeugkasten.

Pilot ist die Liegenschaftsliste. Vorher: alle Zeilen auf einer Seite, Suche
nur im Browser, eine einzige feste Reihenfolge, kein Export. Jetzt: Suche auf
dem Server, wählbare Sortierung, Seiten zu 50, CSV mit denselben Filtern.
"""
import csv
import io
from decimal import Decimal

from django.test import Client, TestCase

from crm.models import Eigentuemer
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

    @classmethod
    def setUpTestData(cls):
        # 60 Liegenschaften: zwei Seiten zu 50 und 10.
        for i in range(60):
            _lg(f'Musterweg {i:02d}')

    def setUp(self):
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
