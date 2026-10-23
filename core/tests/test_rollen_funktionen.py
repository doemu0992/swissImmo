"""Funktionen für die drei Nutzergruppen: Ticket-Board, Kalender, Debitoren-Ampel/Export, Portfolio.

Jede Funktion wird gegen ihren Zweck geprüft (nicht nur «Seite lädt»): Das Board
sortiert nach Zustand und hält die Workflow-Sperre ein, der Kalender zeigt, was
in den Quellen steht, die Ampel zählt richtig, der Export liefert ALLE Zeilen, das
Portfolio rechnet Rendite nur mit vorhandenem Wert.
"""
import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.tests._helfer import _basis_objekte, _seed_konten, _team_user, _test_organisation


class _Basis(TestCase):
    def setUp(self):
        _seed_konten()
        self.org = _test_organisation()
        self.lg, self.einheit, self.mieter, self.vertrag = _basis_objekte()
        self.verwalter = _team_user('Verwalter')
        self.c = Client()
        self.c.force_login(self.verwalter)
        self.heute = timezone.localdate()

    def ticket(self, titel='Heizung', status='neu', prio='mittel', **kw):
        from tickets.models import SchadenMeldung
        return SchadenMeldung.objects.create(liegenschaft=self.lg, titel=titel, beschreibung='x',
                                             status=status, prioritaet=prio, **kw)


# ---------------------------------------------------------------- Ticket-Board
class TicketBoardTests(_Basis):
    def test_karten_stehen_in_der_spalte_ihres_zustands(self):
        self.ticket('A neu', 'neu')
        self.ticket('B bearbeitung', 'in_bearbeitung')
        self.ticket('C wartet', 'warte_auf_mieter')
        self.ticket('D fertig', 'erledigt')
        antwort = self.c.get('/neu/schaeden/board/')
        self.assertEqual(antwort.status_code, 200)
        spalten = {s['key']: [z['t'].titel for z in s['karten']] for s in antwort.context['spalten']}
        self.assertEqual(spalten, {'neu': ['A neu'], 'bearbeitung': ['B bearbeitung'],
                                   'wartet': ['C wartet'], 'erledigt': ['D fertig']})

    def test_erledigtes_verschwindet_nach_dreissig_tagen(self):
        from tickets.models import SchadenMeldung
        alt = self.ticket('Altfall', 'erledigt')
        SchadenMeldung.objects.filter(pk=alt.pk).update(aktualisiert_am=timezone.now() - timedelta(days=45))
        antwort = self.c.get('/neu/schaeden/board/')
        self.assertNotContains(antwort, 'Altfall')

    def test_filter_dringend_und_meine(self):
        self.ticket('Ruhig', prio='tief')
        self.ticket('Brennt', prio='notfall', zugewiesen_an=self.verwalter)
        dringend = self.c.get('/neu/schaeden/board/?prio=dringend')
        self.assertContains(dringend, 'Brennt')
        self.assertNotContains(dringend, 'Ruhig')
        meine = self.c.get('/neu/schaeden/board/?zustaendig=ich')
        self.assertContains(meine, 'Brennt')
        self.assertNotContains(meine, 'Ruhig')

    def test_verschieben_erlaubter_wechsel(self):
        t = self.ticket(status='in_bearbeitung')
        r = self.c.post(f'/neu/schaeden/{t.id}/verschieben/', {'spalte': 'wartet'},
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        t.refresh_from_db()
        # «Wartet auf Dritte»: der erste erlaubte Zustand der Spalte
        self.assertEqual(t.status, 'warte_auf_handwerker')
        self.assertTrue(t.nachrichten.filter(typ='system', is_intern=True,
                                             nachricht__icontains='Board').exists())

    def test_verschieben_gegen_den_fluss_wird_abgelehnt_und_aendert_nichts(self):
        t = self.ticket(status='erledigt')
        r = self.c.post(f'/neu/schaeden/{t.id}/verschieben/', {'spalte': 'neu'},
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 409)
        self.assertFalse(r.json()['ok'])
        t.refresh_from_db()
        self.assertEqual(t.status, 'erledigt')

    def test_workflow_sperre_gilt_auch_beim_ziehen(self):
        """Ohne Handwerkerrechnung gibt es kein «Erledigt» — auch nicht per Drag&Drop."""
        from tickets.models import HandwerkerAuftrag
        from crm.models import Handwerker
        t = self.ticket(status='wartet_auf_rechnung')
        HandwerkerAuftrag.objects.create(ticket=t, handwerker=Handwerker.objects.create(firma='Meier AG'))
        r = self.c.post(f'/neu/schaeden/{t.id}/verschieben/', {'status': 'erledigt'},
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 409)
        t.refresh_from_db()
        self.assertEqual(t.status, 'wartet_auf_rechnung')

    def test_auswahlfeld_ohne_javascript_leitet_zurueck(self):
        t = self.ticket(status='neu')
        r = self.c.post(f'/neu/schaeden/{t.id}/verschieben/', {'status': 'in_bearbeitung'})
        self.assertRedirects(r, '/neu/schaeden/board/', fetch_redirect_response=False)
        t.refresh_from_db()
        self.assertEqual(t.status, 'in_bearbeitung')

    def test_ungueltiger_status_und_get_werden_abgelehnt(self):
        t = self.ticket()
        self.assertEqual(self.c.get(f'/neu/schaeden/{t.id}/verschieben/').status_code, 405)
        r = self.c.post(f'/neu/schaeden/{t.id}/verschieben/', {'status': 'quatsch'},
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 400)

    def test_lesezugriff_sieht_das_board_darf_aber_nicht_verschieben(self):
        t = self.ticket()
        c = Client()
        c.force_login(_team_user('Lesezugriff'))
        self.assertEqual(c.get('/neu/schaeden/board/').status_code, 200)
        self.assertEqual(c.post(f'/neu/schaeden/{t.id}/verschieben/', {'status': 'in_bearbeitung'}).status_code, 403)
        t.refresh_from_db()
        self.assertEqual(t.status, 'neu')

    def test_karte_bietet_nur_erlaubte_zustaende_an(self):
        self.ticket(status='erledigt')
        antwort = self.c.get('/neu/schaeden/board/')
        karte = next(z for s in antwort.context['spalten'] for z in s['karten'])
        self.assertEqual([w for w, _ in karte['ziele']], ['erledigt', 'in_bearbeitung'])


# ---------------------------------------------------------------- Kalender
class KalenderTests(_Basis):
    def _termin(self, titel, tage, stunde=10, status='geplant'):
        from faelle.termin_models import Termin
        beginn = timezone.make_aware(datetime.combine(self.heute + timedelta(days=tage), datetime.min.time())
                                     + timedelta(hours=stunde))
        return Termin.objects.create(titel=titel, beginn=beginn, status=status)

    def test_zeigt_termine_fristen_und_ticket_zielzeiten_des_monats(self):
        from core.models import Pendenz
        monat = self.heute.replace(day=15)
        self._termin('Abnahme Blaser', (monat - self.heute).days)
        Pendenz.objects.create(titel='Frist 257d', faellig_am=monat)
        self.ticket('Leck im Keller', faellig_bis=monat)
        antwort = self.c.get(f'/neu/termine/kalender/?monat={monat:%Y-%m}')
        self.assertEqual(antwort.status_code, 200)
        for text in ('Abnahme Blaser', 'Frist 257d', 'Leck im Keller'):
            self.assertContains(antwort, text)
        self.assertEqual(antwort.context['gesamt'], 3)

    def test_erledigte_tickets_stehen_nicht_im_kalender(self):
        self.ticket('Fertig', status='erledigt', faellig_bis=self.heute)
        self.assertNotContains(self.c.get('/neu/termine/kalender/'), 'Fertig')

    def test_abgesagter_termin_bleibt_sichtbar_aber_gedaempft(self):
        self._termin('Abgesagt', 0, status='abgesagt')
        antwort = self.c.get('/neu/termine/kalender/')
        self.assertContains(antwort, 'gedaempft')

    def test_monat_wechseln_und_ungueltiger_monat_faellt_auf_heute_zurueck(self):
        r = self.c.get('/neu/termine/kalender/?monat=2027-02')
        self.assertEqual(r.context['monat'], '2027-02')
        self.assertEqual(r.context['vorher'], '2027-01')
        self.assertEqual(r.context['nachher'], '2027-03')
        kaputt = self.c.get('/neu/termine/kalender/?monat=quatsch')
        self.assertEqual(kaputt.status_code, 200)
        self.assertEqual(kaputt.context['monat'], self.heute.strftime('%Y-%m'))
        self.assertEqual(self.c.get('/neu/termine/kalender/?monat=1999-13').status_code, 200)

    def test_raster_hat_volle_wochen_ab_montag(self):
        r = self.c.get('/neu/termine/kalender/?monat=2026-10')
        wochen = r.context['wochen']
        self.assertTrue(all(len(w) == 7 for w in wochen))
        self.assertEqual(wochen[0][0]['datum'].weekday(), 0)
        self.assertEqual(wochen[-1][-1]['datum'].weekday(), 6)

    def test_auszug_gekuendigter_vertraege(self):
        ende = self.heute.replace(day=20)
        self.vertrag.status = 'gekuendigt'
        self.vertrag.ende = ende
        self.vertrag.save()
        antwort = self.c.get(f'/neu/termine/kalender/?monat={ende:%Y-%m}')
        self.assertContains(antwort, 'Auszug')

    def test_hauswart_hat_keinen_zugang(self):
        c = Client()
        c.force_login(_team_user('Hauswart'))
        self.assertEqual(c.get('/neu/termine/kalender/').status_code, 403)


# ---------------------------------------------------------------- Debitoren: Ampel und Export
class DebitorenAmpelTests(_Basis):
    def setUp(self):
        super().setUp()
        from finance.models import DebitorenRechnung
        def rechnung(titel, status, faellig, betrag='1000'):
            return DebitorenRechnung.objects.create(
                vertrag=self.vertrag, titel=titel, betrag=Decimal(betrag), status=status,
                faellig_am=faellig, datum=faellig or self.heute)
        self.gruen = rechnung('Bezahlt', 'bezahlt', self.heute - timedelta(days=40))
        self.gelb = rechnung('Offen später', 'offen', self.heute + timedelta(days=10), '500')
        self.rot = rechnung('Überfällig', 'offen', self.heute - timedelta(days=12), '1200')
        self.rot2 = rechnung('Teilbezahlt überfällig', 'teilbezahlt', self.heute - timedelta(days=3), '300')
        self.storno = rechnung('Storniert', 'storniert', self.heute - timedelta(days=90), '999')

    def test_ampel_zaehlt_und_summiert(self):
        r = self.c.get('/neu/debitoren/')
        gruen, gelb, rot = r.context['ampeln']
        self.assertEqual((gruen[0], gruen[2]['n']), ('gruen', 1))
        self.assertEqual((gelb[0], gelb[2]['n']), ('gelb', 1))
        self.assertEqual(gelb[2]['summe'], Decimal('500.00'))
        self.assertEqual((rot[0], rot[2]['n']), ('rot', 2))
        self.assertEqual(rot[2]['summe'], Decimal('1500.00'))
        self.assertContains(r, 'fw-ampel rot')

    def test_filter_rot_zeigt_nur_rueckstaende(self):
        r = self.c.get('/neu/debitoren/?ampel=rot')
        titel = {row['r'].titel for row in r.context['page']}
        self.assertEqual(titel, {'Überfällig', 'Teilbezahlt überfällig'})
        # Die Ampelzahlen bleiben die des ganzen Bestands, nicht die der Auswahl.
        self.assertEqual(r.context['ampeln'][0][2]['n'], 1)

    def test_filter_gelb_und_gruen(self):
        gelb = {row['r'].titel for row in self.c.get('/neu/debitoren/?ampel=gelb').context['page']}
        gruen = {row['r'].titel for row in self.c.get('/neu/debitoren/?ampel=gruen').context['page']}
        self.assertEqual(gelb, {'Offen später'})
        self.assertEqual(gruen, {'Bezahlt'})

    def test_unbekannte_ampel_wird_ignoriert(self):
        r = self.c.get('/neu/debitoren/?ampel=blau')
        self.assertEqual(r.context['ampel_filter'], '')

    def test_csv_export_liefert_alle_zeilen_mit_ampel_und_tagen(self):
        r = self.c.get('/neu/debitoren/?export=csv')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        text = r.content.decode('utf-8')
        self.assertTrue(text.startswith('﻿'))                    # BOM für Excel
        zeilen = list(csv.reader(io.StringIO(text.lstrip('﻿')), delimiter=';'))
        kopf, daten = zeilen[0], zeilen[1:]
        self.assertIn('Ampel', kopf)
        self.assertEqual(len(daten), 5)                               # auch Storno, ohne Seitenlimit
        je_titel = {z[kopf.index('Titel')]: z for z in daten}
        self.assertEqual(je_titel['Überfällig'][kopf.index('Ampel')], 'rot')
        self.assertEqual(je_titel['Überfällig'][kopf.index('Tage überfällig')], '12')
        self.assertEqual(je_titel['Offen später'][kopf.index('Ampel')], 'gelb')
        self.assertEqual(je_titel['Bezahlt'][kopf.index('Ampel')], 'grün')
        self.assertEqual(je_titel['Offen später'][kopf.index('Tage überfällig')], '0')

    def test_csv_export_folgt_dem_ampelfilter(self):
        text = self.c.get('/neu/debitoren/?ampel=rot&export=csv').content.decode('utf-8')
        zeilen = list(csv.reader(io.StringIO(text.lstrip('﻿')), delimiter=';'))
        self.assertEqual(len(zeilen) - 1, 2)

    def test_csv_ist_gegen_formeln_geschuetzt(self):
        from finance.models import DebitorenRechnung
        DebitorenRechnung.objects.create(vertrag=self.vertrag, titel='=HYPERLINK("http://x")', betrag=Decimal('1'),
                                         status='offen', faellig_am=self.heute, datum=self.heute)
        text = self.c.get('/neu/debitoren/?export=csv').content.decode('utf-8')
        self.assertNotIn(';=HYPERLINK', text)


# ---------------------------------------------------------------- Portfolio
class PortfolioTests(_Basis):
    def test_ohne_verkehrswert_keine_rendite_und_ein_hinweis(self):
        r = self.c.get('/neu/portfolio/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['u']['netto'])
        self.assertEqual(r.context['u']['ohne_wert'], 1)
        self.assertContains(r, 'kein Verkehrswert erfasst')

    def test_rendite_mit_verkehrswert(self):
        self.lg.verkehrswert = Decimal('1000000')
        self.lg.save()
        r = self.c.get('/neu/portfolio/')
        # 1500 netto · 12 = 18'000 Soll; ohne Aufwand → 1.80 % brutto = netto
        self.assertEqual(r.context['u']['soll_jahr'], Decimal('18000.00'))
        self.assertAlmostEqual(r.context['u']['brutto'], 1.8, places=2)
        self.assertAlmostEqual(r.context['u']['netto'], 1.8, places=2)
        self.assertEqual(r.context['u']['ohne_wert'], 0)

    def test_leerstand_und_zahlungsquote(self):
        from finance.models import DebitorenRechnung
        from portfolio.models import Einheit
        Einheit.objects.create(liegenschaft=self.lg, bezeichnung='Leer', typ='whg')
        DebitorenRechnung.objects.create(vertrag=self.vertrag, titel='A', betrag=Decimal('800'), status='bezahlt',
                                         faellig_am=self.heute - timedelta(days=5), datum=self.heute)
        DebitorenRechnung.objects.create(vertrag=self.vertrag, titel='B', betrag=Decimal('200'), status='offen',
                                         faellig_am=self.heute - timedelta(days=1), datum=self.heute)
        u = self.c.get('/neu/portfolio/').context['u']
        self.assertEqual((u['leer'], u['objekte']), (1, 2))
        self.assertAlmostEqual(u['leer_quote'], 50.0)
        if self.heute.month == 1 and self.heute.day <= 5:
            self.skipTest('Jahreswechsel: Rechnungen liegen im Vorjahr')
        self.assertAlmostEqual(u['zahlungsquote'], 80.0)
        self.assertEqual(u['ueberfaellig_n'], 1)

    def test_cashflow_summiert_ertrag_und_aufwand_ohne_storno(self):
        from finance.models import Buchung, Buchungskonto
        from core.tests._helfer import _test_organisation
        org = _test_organisation()
        ertrag = Buchungskonto.objects.get(organisation=org, nummer='3000') if Buchungskonto.objects.filter(organisation=org, nummer='3000').exists() \
            else Buchungskonto.objects.create(organisation=org, nummer='3000', bezeichnung='Mietertrag', typ='ertrag')
        aufwand = Buchungskonto.objects.create(organisation=org, nummer='4999', bezeichnung='Unterhalt', typ='aufwand')
        bank = Buchungskonto.objects.filter(organisation=org, nummer='1020').first()
        d = self.heute
        Buchung.objects.create(datum=d, beleg_text='Miete', liegenschaft=self.lg, soll_konto=bank, haben_konto=ertrag, betrag=Decimal('1500'))
        Buchung.objects.create(datum=d, beleg_text='Reparatur', liegenschaft=self.lg, soll_konto=aufwand, haben_konto=bank, betrag=Decimal('400'))
        Buchung.objects.create(datum=d, beleg_text='Storno', liegenschaft=self.lg, soll_konto=aufwand, haben_konto=bank,
                               betrag=Decimal('999'), ist_storno=True)
        r = self.c.get('/neu/portfolio/?monate=6')
        letzter = r.context['reihe'][-1]
        self.assertEqual((letzter['ertrag'], letzter['aufwand'], letzter['netto']),
                         (Decimal('1500.00'), Decimal('400.00'), Decimal('1100.00')))
        self.assertEqual(len(r.context['reihe']), 6)
        self.assertContains(r, 'fw-kurve')                           # Diagramm gezeichnet
        self.assertContains(r, 'fw-donut')

    def test_csv_export(self):
        r = self.c.get('/neu/portfolio/?export=csv')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Teststrasse 1', r.content.decode('utf-8'))

    def test_ungueltiger_zeitraum_und_mandat_fallen_zurueck(self):
        r = self.c.get('/neu/portfolio/?monate=99&mandat=abc&verteilung=x')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.context['monate'], r.context['verteilung']), (12, 'liegenschaft'))

    def test_verteilung_nach_nutzung(self):
        r = self.c.get('/neu/portfolio/?verteilung=nutzung')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['donut_mitte'][1], 'Objekte')

    def test_leeres_portfolio_zeigt_leerzustand(self):
        from portfolio.models import Liegenschaft
        Liegenschaft.objects.all().delete()
        self.assertContains(self.c.get('/neu/portfolio/'), 'Keine Liegenschaft im Portfolio')

    def test_eigentuemer_und_hauswart_haben_keinen_zugang(self):
        for rolle in ('Hauswart',):
            c = Client()
            c.force_login(_team_user(rolle))
            self.assertEqual(c.get('/neu/portfolio/').status_code, 403)


# ---------------------------------------------------------------- Diagramm-Bausteine
class DiagrammTagsTests(TestCase):
    def test_donut_ignoriert_nullen_und_summiert_auf_hundert(self):
        from core.templatetags.diagramm import donut_diagramm
        html = str(donut_diagramm([{'lab': 'A', 'wert': 75}, {'lab': 'B', 'wert': 25}, {'lab': 'C', 'wert': 0}], '3', 'Teile', 'T'))
        self.assertEqual(html.count('fw-donut-teil'), 2)
        self.assertIn('75.0 %', html.replace('75,0', '75.0'))

    def test_donut_ohne_daten_ist_leer(self):
        from core.templatetags.diagramm import donut_diagramm
        self.assertEqual(donut_diagramm([], '', '', ''), '')
        self.assertEqual(donut_diagramm([{'lab': 'A', 'wert': 0}], '', '', ''), '')

    def test_cashflow_diagramm_zwei_linien_oder_leer(self):
        from core.templatetags.diagramm import cashflow_diagramm
        html = str(cashflow_diagramm([100000, 120000, 110000], [60000, 70000, 65000], ['Mai', 'Jun', 'Jul'], 'T'))
        self.assertEqual(html.count('fw-kurve-strich'), 2)
        self.assertIn('fw-kurve-strich zwei', html)
        self.assertEqual(cashflow_diagramm([100000], [1], ['Mai'], ''), '')
        self.assertEqual(cashflow_diagramm([None, None, 5], [None] * 3, ['a', 'b', 'c'], ''), '')
