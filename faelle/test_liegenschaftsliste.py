"""Die Liegenschaftsliste als Befundliste.

Der Kern dieses Testsatzes ist die Leerstandsregel (Entscheid 21.08.2026): ein
Objekt genuegt, leer ab Ende der Kuendigungsfrist, Nachmieter hebt auf. Jede
der drei Festlegungen hat hier einen Test, der rot wird, wenn sie faellt.

DIE GEGENPROBEN STEHEN DABEI, NICHT DANEBEN. Ein Test, der auch ohne die
geprüfte Regel gruen bleibt, prueft nichts — deshalb hat jede Regel zusaetzlich
einen Fall, der die Gegenrichtung festhaelt (belegt bleibt belegt, ein
abgelaufener Vertrag zaehlt, ein Nachmieter in der Vergangenheit hebt nichts
auf).
"""
import re
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.liegenschaften import (RANG, SCHWELLE_LEER, VORSCHAU_TAGE,
                                   streifen, zeilen)

#: `base.html` liefert sein CSS inline mit jeder Seite aus. Ein Waechter, der
#: nach einer Klasse sucht, findet sie deshalb auch in einer Stilregel oder in
#: einem CSS-Kommentar — und meldet einen Bestand, den es im Markup gar nicht
#: gibt. Wer nach Markup fragt, schneidet die Stilbloecke vorher weg.
_STIL = re.compile(r'<style\b.*?</style>', re.DOTALL | re.IGNORECASE)


def _ohne_stil(html):
    return _STIL.sub('', html)


class _Basis(TestCase):
    """Ein Mandant mit einer Liegenschaft und drei Objekten.

    Das `MandantenFixture` bringt bereits eine Liegenschaft mit einer Einheit
    und einem laufenden Vertrag mit; hier kommen zwei weitere Objekte dazu,
    damit sich Leerstand und Belegung ueberhaupt unterscheiden koennen.

    DAS FIXTURE BRINGT ZWEI BEFUNDE MIT: eine offene Schadenmeldung und eine
    in dreissig Tagen faellige Wartungsfrist. Beide werden hier stillgelegt.
    Sonst waere keine Zeile je «ohne Befund», und jede Gegenprobe, die genau
    das prueft, waere aus dem falschen Grund rot — sie wuerde den Bestand des
    Fixtures messen statt die Regel.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.heute = timezone.localdate()
        from portfolio.models import Einheit
        with mandant(cls.a.organisation):
            cls.a.schaden.status = 'erledigt'
            cls.a.schaden.save(update_fields=['status'])
            cls.a.wartungsfrist.aktiv = False
            cls.a.wartungsfrist.save(update_fields=['aktiv'])
            cls.leer = Einheit.objects.create(
                liegenschaft=cls.a.liegenschaft, bezeichnung='2.5 Zi leer',
                typ='whg', nettomiete_aktuell=Decimal('1200'))
            cls.zweit = Einheit.objects.create(
                liegenschaft=cls.a.liegenschaft, bezeichnung='4.5 Zi',
                typ='whg', nettomiete_aktuell=Decimal('1800'))

    def _zeilen(self, stichtag=None):
        from portfolio.models import Liegenschaft
        with mandant(self.a.organisation):
            return zeilen(Liegenschaft.objects.all(), stichtag or self.heute)

    def _erste(self, stichtag=None):
        return self._zeilen(stichtag)[0]

    def _vertrag(self, einheit, beginn, ende=None, status='aktiv', netto='1500'):
        from crm.models import Mieter
        from rentals.models import Mietvertrag
        with mandant(self.a.organisation):
            mieter = Mieter.objects.create(
                typ='person', vorname='Nach', nachname=einheit.bezeichnung[:20],
                strasse='Weg 1', plz='8000', ort='Zürich')
            return Mietvertrag.objects.create(
                mieter=mieter, einheit=einheit, status=status, beginn=beginn,
                ende=ende, netto_mietzins=Decimal(netto),
                nebenkosten=Decimal('0'))


class LeerstandsregelTests(_Basis):

    def test_ein_einziges_leeres_objekt_genuegt(self):
        """Keine Prozentschwelle. Die Zeile meldet, sobald eines leer steht."""
        self.assertEqual(SCHWELLE_LEER, 1)
        row = self._erste()
        self.assertGreaterEqual(row['leer'], 1)
        self.assertEqual(row['stufe'], 'crit')
        self.assertIn('leer', row['kategorien'])

    def test_gegenprobe_voll_belegt_meldet_nichts(self):
        """Ohne die Regel waere auch dieser Fall 'crit' — er ist es nicht."""
        self._vertrag(self.leer, self.heute - timedelta(days=30))
        self._vertrag(self.zweit, self.heute - timedelta(days=30))
        row = self._erste()
        self.assertEqual(row['leer'], 0)
        self.assertTrue(row['ohne_befund'])
        self.assertEqual(row['stufe'], 'good')

    def test_gekuendigter_vertrag_belegt_bis_zum_ende_der_frist(self):
        """Gekuendigt, Ende in zwei Monaten: das Objekt ist heute NICHT leer.

        Massgeblich ist `Mietvertrag.ende` (die `per_datum` der Kuendigung),
        nicht ein Auszugsdatum. Bis dahin ist das Verhaeltnis in Kraft.
        """
        self._vertrag(self.leer, self.heute - timedelta(days=400),
                      ende=self.heute + timedelta(days=60), status='gekuendigt')
        self._vertrag(self.zweit, self.heute - timedelta(days=30))
        row = self._erste()
        self.assertEqual(row['leer'], 0)
        self.assertIn('leer', row['kategorien'])       # aber: «wird frei»
        self.assertEqual([c[1] for c in row['chips']], ['1 wird frei'])
        self.assertEqual(row['stufe'], 'warn')

    def test_gegenprobe_nach_ablauf_der_frist_ist_es_leer(self):
        """Derselbe Vertrag, Ende gestern: jetzt zaehlt das Objekt als leer."""
        self._vertrag(self.leer, self.heute - timedelta(days=400),
                      ende=self.heute - timedelta(days=1), status='gekuendigt')
        self._vertrag(self.zweit, self.heute - timedelta(days=30))
        row = self._erste()
        self.assertEqual(row['leer'], 1)
        self.assertEqual(row['stufe'], 'crit')

    def test_nachmieter_hebt_den_befund_auf(self):
        """Leer, aber ab naechstem Monat vermietet — keine offene Aufgabe."""
        self._vertrag(self.zweit, self.heute - timedelta(days=30))
        self._vertrag(self.leer, self.heute + timedelta(days=30))
        row = self._erste()
        self.assertEqual(row['leer'], 0)
        self.assertTrue(row['ohne_befund'])

    def test_nachmieter_auch_als_entwurf(self):
        """Der Vertrag ist geschrieben, aber noch nicht aktiviert — zaehlt."""
        self._vertrag(self.zweit, self.heute - timedelta(days=30))
        self._vertrag(self.leer, self.heute + timedelta(days=30), status='entwurf')
        self.assertEqual(self._erste()['leer'], 0)

    def test_gegenprobe_ein_beendeter_vertrag_ist_kein_nachmieter(self):
        """Ein Vertrag, der frueher begann und lange vorbei ist, hebt nichts auf."""
        self._vertrag(self.zweit, self.heute - timedelta(days=30))
        self._vertrag(self.leer, self.heute - timedelta(days=800),
                      ende=self.heute - timedelta(days=400), status='archiviert')
        self.assertEqual(self._erste()['leer'], 1)

    def test_nachmieter_unterdrueckt_auch_die_wird_frei_meldung(self):
        """Gekuendigt UND Nachfolger da: die Zeile schweigt zu diesem Objekt."""
        self._vertrag(self.leer, self.heute - timedelta(days=400),
                      ende=self.heute + timedelta(days=60), status='gekuendigt')
        self._vertrag(self.leer, self.heute + timedelta(days=61))
        self._vertrag(self.zweit, self.heute - timedelta(days=30))
        row = self._erste()
        self.assertEqual(row['leer'], 0)
        self.assertTrue(row['ohne_befund'])

    def test_auslauf_ausserhalb_des_horizonts_meldet_noch_nicht(self):
        """Ein Vertragsende in zwei Jahren ist keine Aufgabe fuer diese Liste."""
        self._vertrag(self.leer, self.heute - timedelta(days=400),
                      ende=self.heute + timedelta(days=VORSCHAU_TAGE + 30),
                      status='gekuendigt')
        self._vertrag(self.zweit, self.heute - timedelta(days=30))
        row = self._erste()
        self.assertTrue(row['ohne_befund'], row['chips'])

    def test_nebenobjekt_gilt_als_belegt(self):
        """Ein mitvermieteter Parkplatz steht nicht leer."""
        from portfolio.models import Einheit
        with mandant(self.a.organisation):
            pp = Einheit.objects.create(liegenschaft=self.a.liegenschaft,
                                        bezeichnung='PP 1', typ='pp')
            v = self._vertrag(self.zweit, self.heute - timedelta(days=30))
            v.nebenobjekte.add(pp)
            self._vertrag(self.leer, self.heute - timedelta(days=30))
        row = self._erste()
        self.assertEqual(row['leer'], 0)


class ErtragTests(_Basis):

    def test_gekuendigter_vertrag_zaehlt_zur_ist_miete(self):
        """Er schuldet bis zum Vertragsende Miete (Etappe H4).

        Die Vorgaengerversion filterte auf `status='aktiv'` und liess ihn aus
        dem Ertrag fallen. Dieser Test haelt die Korrektur fest.
        """
        self._vertrag(self.leer, self.heute - timedelta(days=400),
                      ende=self.heute + timedelta(days=60),
                      status='gekuendigt', netto='2000')
        row = self._erste()
        self.assertGreaterEqual(row['ertrag'], Decimal('2000'))

    def test_kuenftiger_vertrag_zaehlt_noch_nicht(self):
        """Ist-Miete ist, was heute laeuft — nicht, was ab naechstem Monat kommt."""
        vorher = self._erste()['ertrag']
        self._vertrag(self.leer, self.heute + timedelta(days=30), netto='9999')
        self.assertEqual(self._erste()['ertrag'], vorher)


class WeitereBefundeTests(_Basis):

    def _voll_belegen(self):
        self._vertrag(self.leer, self.heute - timedelta(days=30))
        self._vertrag(self.zweit, self.heute - timedelta(days=30))

    def test_abgelaufene_gebaeudepolice_ist_kritisch(self):
        from portfolio.models import Versicherung
        self._voll_belegen()
        with mandant(self.a.organisation):
            Versicherung.objects.create(
                liegenschaft=self.a.liegenschaft, art='gebaeude',
                gesellschaft='GVZ', ablauf_datum=self.heute - timedelta(days=5))
        row = self._erste()
        self.assertEqual(row['stufe'], 'crit')
        self.assertIn('frist', row['kategorien'])
        self.assertIn('Gebäudepolice abgelaufen', [c[1] for c in row['chips']])

    def test_police_im_horizont_ist_eine_warnung(self):
        from portfolio.models import Versicherung
        self._voll_belegen()
        with mandant(self.a.organisation):
            Versicherung.objects.create(
                liegenschaft=self.a.liegenschaft, art='gebaeude',
                gesellschaft='GVZ', ablauf_datum=self.heute + timedelta(days=30))
        self.assertEqual(self._erste()['stufe'], 'warn')

    def test_gegenprobe_police_weit_in_der_zukunft_meldet_nichts(self):
        from portfolio.models import Versicherung
        self._voll_belegen()
        with mandant(self.a.organisation):
            Versicherung.objects.create(
                liegenschaft=self.a.liegenschaft, art='gebaeude',
                gesellschaft='GVZ',
                ablauf_datum=self.heute + timedelta(days=VORSCHAU_TAGE + 10))
        self.assertTrue(self._erste()['ohne_befund'])

    def test_nur_die_gebaeudepolice_steht_in_der_zeile(self):
        """Eine abgelaufene Glasbruchpolice ist eine Frage der Zweckmaessigkeit
        und gehoert in die Objektakte, nicht in die Uebersicht."""
        from portfolio.models import Versicherung
        self._voll_belegen()
        with mandant(self.a.organisation):
            Versicherung.objects.create(
                liegenschaft=self.a.liegenschaft, art='glas',
                gesellschaft='Mobiliar', ablauf_datum=self.heute - timedelta(days=5))
        self.assertTrue(self._erste()['ohne_befund'])

    def test_ueberfaellige_wartung_ist_kritisch(self):
        from portfolio.models import Wartungsfrist
        self._voll_belegen()
        with mandant(self.a.organisation):
            Wartungsfrist.objects.create(
                liegenschaft=self.a.liegenschaft, art='wartung',
                bezeichnung='Lift', aktiv=True,
                naechste_faelligkeit=self.heute - timedelta(days=3))
        row = self._erste()
        self.assertEqual(row['stufe'], 'crit')
        self.assertIn('1 Wartung überfällig', [c[1] for c in row['chips']])

    def test_gegenprobe_inaktive_wartung_meldet_nichts(self):
        from portfolio.models import Wartungsfrist
        self._voll_belegen()
        with mandant(self.a.organisation):
            Wartungsfrist.objects.create(
                liegenschaft=self.a.liegenschaft, art='wartung',
                bezeichnung='Stillgelegt', aktiv=False,
                naechste_faelligkeit=self.heute - timedelta(days=3))
        self.assertTrue(self._erste()['ohne_befund'])

    def test_offenes_ticket_ist_eine_warnung(self):
        from tickets.models import SchadenMeldung
        self._voll_belegen()
        with mandant(self.a.organisation):
            SchadenMeldung.objects.create(
                liegenschaft=self.a.liegenschaft, titel='Wasserhahn tropft',
                beschreibung='…', status='neu')
        row = self._erste()
        self.assertEqual(row['stufe'], 'warn')
        self.assertIn('ticket', row['kategorien'])

    def test_gegenprobe_erledigtes_ticket_meldet_nichts(self):
        from tickets.models import SchadenMeldung
        self._voll_belegen()
        with mandant(self.a.organisation):
            SchadenMeldung.objects.create(
                liegenschaft=self.a.liegenschaft, titel='Erledigt',
                beschreibung='…', status='erledigt')
        self.assertTrue(self._erste()['ohne_befund'])


class SortierungTests(TestCase):
    """Die Sortierung IST die Aussage der Seite — deshalb ein eigener Satz."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.heute = timezone.localdate()

    def _lg(self, strasse, leer_objekte, belegte_objekte=0):
        from crm.models import Mieter
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Mietvertrag
        with mandant(self.a.organisation):
            lg = Liegenschaft.objects.create(
                strasse=strasse, plz='8000', ort='Zürich',
                organisation=self.a.organisation, eigentuemer=self.a.eigentuemer)
            for i in range(leer_objekte):
                Einheit.objects.create(liegenschaft=lg, bezeichnung=f'L{i}', typ='whg')
            for i in range(belegte_objekte):
                e = Einheit.objects.create(liegenschaft=lg, bezeichnung=f'B{i}', typ='whg')
                m = Mieter.objects.create(typ='person', vorname='M', nachname=f'{strasse}{i}',
                                          strasse='W 1', plz='8000', ort='Zürich')
                Mietvertrag.objects.create(
                    mieter=m, einheit=e, status='aktiv',
                    beginn=self.heute - timedelta(days=30),
                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'))
            return lg

    def _zeilen(self):
        from portfolio.models import Liegenschaft
        with mandant(self.a.organisation):
            return zeilen(Liegenschaft.objects.all(), self.heute)

    def test_befund_vor_bestand(self):
        """Ein kleines Haus mit Leerstand steht vor einem grossen ohne."""
        self._lg('Zzz-Strasse 1', leer_objekte=0, belegte_objekte=8)
        self._lg('Aaa-Strasse 1', leer_objekte=2)
        # Das Fixture bringt eine dritte Liegenschaft mit belegtem Objekt mit.
        reihe = [r['lg'].strasse for r in self._zeilen()]
        self.assertEqual(reihe[0], 'Aaa-Strasse 1')

    def test_bei_gleichem_befund_zaehlt_die_zahl_der_leeren_objekte(self):
        self._lg('Bbb-Strasse 1', leer_objekte=1)
        self._lg('Aaa-Strasse 1', leer_objekte=3)
        reihe = [r['lg'].strasse for r in self._zeilen()]
        self.assertEqual(reihe[:2], ['Aaa-Strasse 1', 'Bbb-Strasse 1'])

    def test_bei_gleichem_befund_und_gleicher_zahl_die_adresse(self):
        """Sonst sortiert die Liste bei jedem Aufruf anders und wird nicht gelesen."""
        self._lg('Bbb-Strasse 1', leer_objekte=1)
        self._lg('Aaa-Strasse 1', leer_objekte=1)
        reihe = [r['lg'].strasse for r in self._zeilen()]
        self.assertEqual(reihe[:2], ['Aaa-Strasse 1', 'Bbb-Strasse 1'])

    def test_die_rangfolge_ist_kritisch_vor_warnend_vor_ruhig(self):
        self.assertLess(RANG['crit'], RANG['warn'])
        self.assertLess(RANG['warn'], RANG['good'])


class StreifenTests(_Basis):

    def test_streifen_zaehlt_ueber_alle_zeilen(self):
        werte = streifen(self._zeilen())
        self.assertEqual(werte['objekte'], 1)
        self.assertEqual(werte['einheiten'], 3)
        self.assertEqual(werte['leer'], 2)
        self.assertEqual(werte['mit_befund'], 1)

    def test_leerstandsquote_ohne_objekte_ist_null_und_wirft_nicht(self):
        self.assertEqual(streifen([])['leer_quote'], Decimal('0.0'))
        self.assertEqual(streifen([])['objekte'], 0)

    def test_quote_ist_decimal_nicht_float(self):
        """Kennzahlen aus Geld- und Bestandsgroessen sind `Decimal`."""
        werte = streifen(self._zeilen())
        self.assertIsInstance(werte['leer_quote'], Decimal)
        self.assertIsInstance(werte['ertrag'], Decimal)


class AbfragezahlTests(_Basis):
    """Die Liste ist der Einstieg in die Bewirtschaftung und laeuft auf einem
    Ein-Worker-Hosting. Sechs Abfragen fuer das ganze Portfolio, nicht je Zeile.
    """

    def test_zehn_liegenschaften_kosten_nicht_mehr_als_eine(self):
        from crm.models import Mieter
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Mietvertrag
        with mandant(self.a.organisation):
            for i in range(10):
                lg = Liegenschaft.objects.create(
                    strasse=f'Mess-Weg {i}', plz='8000', ort='Zürich',
                    organisation=self.a.organisation, eigentuemer=self.a.eigentuemer)
                e = Einheit.objects.create(liegenschaft=lg, bezeichnung='W', typ='whg')
                m = Mieter.objects.create(typ='person', vorname='M', nachname=f'X{i}',
                                          strasse='W 1', plz='8000', ort='Zürich')
                Mietvertrag.objects.create(
                    mieter=m, einheit=e, status='aktiv',
                    beginn=self.heute - timedelta(days=30),
                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'))

            liste = list(Liegenschaft.objects.all())
            with self.assertNumQueries(6):
                rows = zeilen(liste, self.heute)
        self.assertEqual(len(rows), 11)

    def test_streifen_kostet_keine_abfrage(self):
        rows = self._zeilen()
        with self.assertNumQueries(0):
            streifen(rows)


class MandantentrennungTests(TestCase):
    """Ein Befund aus Organisation B darf in einer Zeile von A nicht auftauchen.

    Der Test muss rot werden, wenn die Isolation faellt: Er legt in B einen
    kritischen Befund an (abgelaufene Police) und prueft, dass A ihn weder
    sieht noch dessen Liegenschaft.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        cls.heute = timezone.localdate()
        from portfolio.models import Versicherung
        with mandant(cls.b.organisation):
            Versicherung.objects.create(
                liegenschaft=cls.b.liegenschaft, art='gebaeude',
                gesellschaft='GVB', ablauf_datum=cls.heute - timedelta(days=10))

    def test_zeilen_von_a_enthalten_keine_liegenschaft_von_b(self):
        from portfolio.models import Liegenschaft
        with mandant(self.a.organisation):
            rows = zeilen(Liegenschaft.objects.all(), self.heute)
        self.assertEqual([r['lg'].pk for r in rows], [self.a.liegenschaft.pk])

    def test_befund_von_b_faerbt_die_zeile_von_a_nicht_ein(self):
        from portfolio.models import Liegenschaft
        with mandant(self.a.organisation):
            rows = zeilen(Liegenschaft.objects.all(), self.heute)
        texte = [c[1] for r in rows for c in r['chips']]
        self.assertNotIn('Gebäudepolice abgelaufen', texte)

    def test_die_fremde_liegenschaft_bleibt_auch_bei_direkter_uebergabe_leer(self):
        """Wer die Liste von B im Kontext von A durchreicht, bekommt keine Daten.

        `zeilen()` rechnet ueber `Einheit.objects`/`Mietvertrag.objects` — beide
        laufen durch den `TenantManager`. Die Zeile entsteht, aber ohne Bestand.
        """
        from portfolio.models import Liegenschaft
        with mandant(self.b.organisation):
            fremde = list(Liegenschaft.objects.all())
        with mandant(self.a.organisation):
            rows = zeilen(fremde, self.heute)
        self.assertEqual([r['einheiten'] for r in rows], [0])
        self.assertEqual([r['ertrag'] for r in rows], [Decimal('0.00')])


class AnsichtTests(TestCase):
    """Was gerechnet wird, muss auch auf der Seite ankommen.

    Die Erfahrung aus Etappe 4b.13: Ein Test gegen die Kontextdaten bleibt
    gruen, wenn das Template die Werte gar nicht ausgibt. Deshalb hier gegen
    das GERENDERTE HTML.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.heute = timezone.localdate()
        from portfolio.models import Einheit
        with mandant(cls.a.organisation):
            Einheit.objects.create(liegenschaft=cls.a.liegenschaft,
                                   bezeichnung='2.5 Zi leer', typ='whg')

    def setUp(self):
        self.client.force_login(self.a.benutzer)

    def test_die_seite_zeigt_die_adresse_und_den_befund(self):
        html = self.client.get('/neu/liegenschaften/').content.decode()
        self.assertIn(self.a.liegenschaft.strasse, html)
        self.assertIn('1 leer', html)

    def test_der_kennzahlenstreifen_steht_auf_der_seite(self):
        html = self.client.get('/neu/liegenschaften/').content.decode()
        self.assertIn('fw-lage', html)
        self.assertIn('Ist-Miete', html)
        self.assertIn('% des Bestands', html)

    def test_die_filterleiste_traegt_die_zahlen(self):
        html = self.client.get('/neu/liegenschaften/').content.decode()
        self.assertIn('befund=leer', html)
        self.assertIn('Leerstand 1', html)
        self.assertIn('Ohne Befund 0', html)

    def test_der_filter_grenzt_die_liste_ein(self):
        antwort = self.client.get('/neu/liegenschaften/?befund=ohne')
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.context['rows'], [])
        self.assertEqual(antwort.context['befund'], 'ohne')
        self.assertIn('Keine Liegenschaft mit diesem Befund',
                      antwort.content.decode())

    def test_der_streifen_zaehlt_trotz_filter_das_ganze_portfolio(self):
        """Sonst zeigte der Filter «ohne Befund» ein Portfolio ohne Objekte."""
        antwort = self.client.get('/neu/liegenschaften/?befund=ohne')
        self.assertEqual(antwort.context['kennzahlen']['objekte'], 1)
        self.assertEqual(antwort.context['alle_rows'], 1)

    def test_ein_unbekannter_filter_zeigt_alles_statt_nichts(self):
        antwort = self.client.get('/neu/liegenschaften/?befund=unfug')
        self.assertEqual(antwort.context['befund'], '')
        self.assertEqual(len(antwort.context['rows']), 1)

    def test_die_alte_kartenansicht_ist_weg(self):
        """Gegenprobe zum Umbau: Bliebe `fw-pcard` stehen, waere die Zeile nur
        danebengestellt statt an ihre Stelle getreten.

        DIE PRUEFUNG FRAGT NUR DAS MARKUP, NICHT DAS STYLESHEET. Erster Anlauf
        suchte `fw-pcard` in der ganzen Seite und war rot — getroffen hat er
        den Kommentar in `base.html`, der erklaert, warum die Regeln entfernt
        wurden. Ein Waechter, der seine eigene Begruendung liest, prueft den
        Text und nicht die Sache; dasselbe Muster hat in dieser Phase schon
        drei andere Pruefungen falsch rot gefaerbt (siehe `{% comment %}` in
        `faelle/test_template_struktur.py`).
        """
        html = _ohne_stil(self.client.get('/neu/liegenschaften/').content.decode())
        self.assertNotIn('fw-pcard', html)
        self.assertIn('fw-zeile', html)

    def test_der_waechter_wuerde_die_karten_auch_wirklich_finden(self):
        """Gegenprobe zur Gegenprobe: `_ohne_stil` darf nicht zu viel wegnehmen.

        Schnitte es den ganzen Rumpf heraus, waere der Test oben immer gruen.
        """
        self.assertIn('fw-pcard', _ohne_stil('<style>x</style><div class="fw-pcard">'))
        self.assertNotIn('kaputt', _ohne_stil('<style>kaputt</style><div>a</div>'))
