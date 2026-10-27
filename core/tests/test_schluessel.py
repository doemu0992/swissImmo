"""Modul 2 (27.10.2026): Schlüssel und Schliessanlage.

Geprüft wird, was das Modul verspricht:

- Die neuen Modelle tragen die Organisation aus der Kette; die Datenmigration
  übernimmt den Status der bestehenden Ausgaben aus dem Rückgabedatum.
- Ausgabe mit Unterschrift erzeugt eine Quittung als `rentals.Dokument` am
  Vertrag; ohne (lesbare) Unterschrift wird nichts gebucht.
- Rücknahme mit Verlust: Teilmenge «zurück», Rest «verloren», Pendenz
  «Zylinder ersetzen» mit Link zur Debitorenrechnung (E9: keine Verrechnung).
- Die Abnahme bucht: Einzug gibt aus, Auszug nimmt zurück (Soll aus den
  Ausgaben), ein zweiter Abschluss bucht nichts doppelt.
- Die Liste beim Dienstleister zeigt seine Ausgabe (Regression).
- Haustürschlüssel ohne Einheit lassen sich anlegen.
- Kachel «Schlüssel» auf «Heute» und Eintrag in den Fristen.
- Fremde Schlüssel, Ausgaben, Anlagen und Türen ergeben 404 und ändern nichts.

Die Gegenprobe jedes Tests steht im Bericht von Modul 2.
"""
import importlib
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._helfer import abschluss_daten, png_data_url
from core.tests._isolation import MandantenFixture


class _Basis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.heute = timezone.localdate()
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def wohnung(self, fixture=None, bezeichnung='2.5 Zi neu'):
        """Eine eigene Liegenschaft mit Einheit, Mieter und Vertrag — ohne die
        Altausgabe, die das Fixture mitbringt."""
        from crm.models import Mieter
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Mietvertrag
        f = fixture or self.a
        with mandant(f.organisation):
            lg = Liegenschaft.objects.create(strasse=f'Schlossweg {bezeichnung}', plz='8000', ort='Zürich',
                                             organisation=f.organisation, versicherungswert=Decimal('1'))
            e = Einheit.objects.create(liegenschaft=lg, bezeichnung=bezeichnung, typ='whg',
                                       nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
            m = Mieter.objects.create(typ='person', vorname='Anna', nachname='Meier', email='anna@example.ch')
            v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 4, 1), status='aktiv',
                                           netto_mietzins=Decimal('1000'), nebenkosten=Decimal('100'),
                                           kautions_betrag=Decimal('3000'))
        return lg, e, m, v

    def schluessel(self, lg, einheit=None, **felder):
        from portfolio.models import Schluessel
        werte = {'typ': 'Wohnung', 'schluessel_nummer': '31', 'anzahl': 3}
        werte.update(felder)
        with mandant(lg.organisation):
            return Schluessel.objects.create(liegenschaft=lg, einheit=einheit, **werte)

    def ausgeben(self, lg, posten, empfaenger, **mehr):
        daten = {'empfaenger': empfaenger, 'schluessel': [s.id for s, _n in posten],
                 'unterschrift': png_data_url('black'), 'unterschrift_name': 'Anna Meier'}
        for s, n in posten:
            daten[f'anzahl_{s.id}'] = str(n)
        daten.update(mehr)
        return self.c.post(f'/neu/liegenschaften/{lg.id}/schluessel/ausgabe/', daten)

    def ausgaben(self, **filter):
        from portfolio.models import SchluesselAusgabe
        with mandant(self.a.organisation):
            return list(SchluesselAusgabe.objects.filter(**filter).order_by('id'))


class ModellTests(_Basis):

    def test_anlage_und_tuer_tragen_die_organisation_der_liegenschaft(self):
        from portfolio.models import Schliessanlage, Schliesspunkt
        lg, e, _m, _v = self.wohnung()
        with mandant(self.a.organisation):
            an = Schliessanlage.objects.create(liegenschaft=lg, hersteller='Kaba', system='star')
            tuer = Schliesspunkt.objects.create(liegenschaft=lg, anlage=an, bezeichnung='Haustür', einheit=e)
        self.assertEqual((an.organisation_id, tuer.organisation_id), (self.a.organisation.id,) * 2)

    def test_ausgabe_beginnt_als_ausgegeben_mit_einem_stueck(self):
        from portfolio.models import SchluesselAusgabe
        lg, _e, m, _v = self.wohnung()
        sch = self.schluessel(lg)
        with mandant(self.a.organisation):
            a = SchluesselAusgabe.objects.create(schluessel=sch, mieter=m)
        self.assertEqual((a.status, a.anzahl), ('ausgegeben', 1))
        self.assertEqual(sch.art, 'einzel')
        self.assertFalse(sch.archiviert)

    def test_datenmigration_setzt_status_aus_rueckgabedatum(self):
        from portfolio.models import SchluesselAusgabe
        lg, _e, m, _v = self.wohnung()
        sch = self.schluessel(lg)
        with mandant(self.a.organisation):
            zurueck = SchluesselAusgabe.objects.create(schluessel=sch, mieter=m, rueckgabe_am=self.heute,
                                                       status='ausgegeben')
            offen = SchluesselAusgabe.objects.create(schluessel=sch, mieter=m, status='zurueck')
        from django.apps import apps
        modul = importlib.import_module('portfolio.migrations.0048_schluesselausgabe_status_uebernehmen')
        modul.status_uebernehmen(apps, None)
        zurueck.refresh_from_db(); offen.refresh_from_db()
        self.assertEqual((zurueck.status, offen.status), ('zurueck', 'ausgegeben'))


class AusgabeTests(_Basis):

    def test_ausgabe_mit_quittung_legt_ein_dokument_am_vertrag_ab(self):
        from rentals.models import Dokument
        lg, e, m, v = self.wohnung()
        wohnung = self.schluessel(lg, e, typ='Wohnung', schluessel_nummer='31', anzahl=3)
        haustuer = self.schluessel(lg, None, typ='Haustür', schluessel_nummer='10', anzahl=15, art='gruppe')
        bis = self.heute + timedelta(days=14)
        r = self.ausgeben(lg, [(wohnung, 2), (haustuer, 1)], f'vertrag:{v.id}', rueckgabe_bis=bis.isoformat())
        self.assertEqual(r.status_code, 302)
        neu = self.ausgaben(vertrag=v)
        self.assertEqual([(a.schluessel_id, a.anzahl, a.status, a.mieter_id, a.rueckgabe_bis) for a in neu],
                         [(wohnung.id, 2, 'ausgegeben', m.id, bis), (haustuer.id, 1, 'ausgegeben', m.id, bis)])
        self.assertIsNotNone(neu[0].quittung_id)
        self.assertEqual(neu[0].quittung_id, neu[1].quittung_id)       # ein Vorgang, eine Quittung
        with mandant(self.a.organisation):
            dok = Dokument.objects.get(pk=neu[0].quittung_id)
        self.assertEqual((dok.vertrag_id, dok.mieter_id, dok.kategorie), (v.id, m.id, 'protokoll'))
        self.assertTrue(dok.datei.name.startswith(f'organisation/{self.a.organisation.id}/'))
        with dok.datei.open('rb') as f:
            self.assertEqual(f.read(4), b'%PDF')
        # Die Unterschrift liegt einmal unter der Organisation; beide Ausgaben zeigen darauf.
        self.assertTrue(neu[0].unterschrift.name.startswith(f'organisation/{self.a.organisation.id}/'))
        self.assertEqual(neu[0].unterschrift.name, neu[1].unterschrift.name)

    def test_ohne_lesbare_unterschrift_wird_nichts_gebucht(self):
        lg, e, _m, v = self.wohnung()
        sch = self.schluessel(lg, e)
        for unterschrift in ('', 'data:image/png;base64,kaputt', png_data_url('white')):
            with self.subTest(unterschrift=unterschrift[:30]):
                r = self.ausgeben(lg, [(sch, 1)], f'vertrag:{v.id}', unterschrift=unterschrift)
                self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ausgaben(schluessel=sch), [])

    def test_mehr_als_im_buero_geht_nicht(self):
        lg, e, _m, v = self.wohnung()
        sch = self.schluessel(lg, e, anzahl=2)
        self.ausgeben(lg, [(sch, 3)], f'vertrag:{v.id}')
        self.assertEqual(self.ausgaben(schluessel=sch), [])

    def test_hauswart_nur_aus_der_eigenen_verwaltung(self):
        lg, e, _m, _v = self.wohnung()
        sch = self.schluessel(lg, e, anzahl=5)
        lg.hauswarte.add(self.a.benutzer, self.b.benutzer)       # B ist kein Mitglied von A
        self.ausgeben(lg, [(sch, 1)], f'benutzer:{self.b.benutzer.id}')
        self.assertEqual(self.ausgaben(schluessel=sch), [])
        self.ausgeben(lg, [(sch, 1)], f'benutzer:{self.a.benutzer.id}')
        self.assertEqual([a.benutzer_id for a in self.ausgaben(schluessel=sch)], [self.a.benutzer.id])

    def test_seite_zeigt_karten_und_unterschriftsfeld(self):
        lg, e, _m, v = self.wohnung()
        self.schluessel(lg, e, schluessel_nummer='31-33')
        r = self.c.get(f'/neu/liegenschaften/{lg.id}/schluessel/ausgabe/?an=vertrag:{v.id}')
        self.assertContains(r, '31-33')
        self.assertContains(r, 'data-sk-pad')
        self.assertContains(r, f'value="vertrag:{v.id}" selected')


class RuecknahmeTests(_Basis):

    def test_ruecknahme_mit_verlust_erzeugt_pendenz_und_quittung(self):
        from core.models import Pendenz
        from core.views.fw._basis import _pendenz_ziel
        lg, e, _m, v = self.wohnung()
        sch = self.schluessel(lg, e, anzahl=3)
        self.ausgeben(lg, [(sch, 3)], f'vertrag:{v.id}')
        a = self.ausgaben(schluessel=sch)[0]
        r = self.c.post(f'/neu/liegenschaften/{lg.id}/schluessel/ruecknahme/', {
            'an': f'vertrag:{v.id}', f'status_{a.id}': 'zurueck', f'verloren_{a.id}': '1',
            'unterschrift': png_data_url('black')})
        self.assertEqual(r.status_code, 302)
        stand = [(x.status, x.anzahl, x.rueckgabe_am) for x in self.ausgaben(schluessel=sch)]
        self.assertEqual(sorted(stand), [('verloren', 1, self.heute), ('zurueck', 2, self.heute)])
        verloren = self.ausgaben(schluessel=sch, status='verloren')[0]
        self.assertIsNotNone(verloren.quittung_rueckgabe_id)
        with mandant(self.a.organisation):
            p = Pendenz.objects.get(quelle=f'schluessel:verlust:{verloren.id}')
        self.assertTrue(p.titel.startswith('Zylinder ersetzen'))
        self.assertEqual((p.vertrag_id, p.liegenschaft_id, p.erledigt), (v.id, lg.id, False))
        self.assertEqual(_pendenz_ziel(p)[:2], ('/neu/debitoren/', 'Debitorenrechnung erfassen'))

    def test_ganz_verloren_und_hauswart_ohne_debitorenrechnung(self):
        from core.models import Pendenz
        from core.views.fw._basis import _pendenz_ziel
        lg, e, _m, _v = self.wohnung()
        sch = self.schluessel(lg, e, anzahl=2, art='haupt')
        lg.hauswarte.add(self.a.benutzer)
        self.ausgeben(lg, [(sch, 1)], f'benutzer:{self.a.benutzer.id}')
        a = self.ausgaben(schluessel=sch)[0]
        self.c.post(f'/neu/liegenschaften/{lg.id}/schluessel/ruecknahme/', {
            'an': f'benutzer:{self.a.benutzer.id}', f'status_{a.id}': 'verloren',
            'unterschrift': png_data_url('black')})
        a.refresh_from_db()
        self.assertEqual(a.status, 'verloren')
        with mandant(self.a.organisation):
            p = Pendenz.objects.get(quelle=f'schluessel:verlust-intern:{a.id}')
        self.assertNotEqual(_pendenz_ziel(p)[0], '/neu/debitoren/')

    def test_ohne_auswahl_wird_nichts_zurueckgenommen(self):
        lg, e, _m, v = self.wohnung()
        sch = self.schluessel(lg, e)
        self.ausgeben(lg, [(sch, 1)], f'vertrag:{v.id}')
        r = self.c.post(f'/neu/liegenschaften/{lg.id}/schluessel/ruecknahme/', {
            'an': f'vertrag:{v.id}', 'unterschrift': png_data_url('black')})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([a.status for a in self.ausgaben(schluessel=sch)], ['ausgegeben'])


class AbnahmeBuchungTests(_Basis):
    """Einzug gibt aus, Auszug nimmt zurück — einmal, nicht bei jedem Abschluss."""

    def _protokoll(self, v, typ):
        from rentals.models import Abnahmeprotokoll
        self.c.post(f'/neu/vertraege/{v.id}/abnahme/vorort/', {'typ': typ, 'raum': ['Keller']})
        with mandant(self.a.organisation):
            return Abnahmeprotokoll.objects.filter(vertrag=v, typ=typ).latest('id')

    def _abschliessen(self, prot, ist):
        zeilen = list(prot.schluessel.all())
        return self.c.post(f'/neu/abnahme/{prot.id}/vorort/abschliessen/', abschluss_daten(
            s_bezeichnung=[z.bezeichnung for z in zeilen], s_anlage=[z.anlage for z in zeilen],
            s_soll=[str(z.soll) for z in zeilen], s_ist=[str(i) for i in ist]))

    def test_einzug_gibt_aus_und_bucht_beim_zweiten_mal_nichts(self):
        from core.services.schluessel import abnahme_buchen
        lg, e, m, v = self.wohnung()
        wohnung = self.schluessel(lg, e, typ='Wohnung', schluessel_nummer='31', anzahl=3)
        haustuer = self.schluessel(lg, None, typ='Haustür', schluessel_nummer='10', anzahl=9)
        prot = self._protokoll(v, 'einzug')
        self._abschliessen(prot, [3, 1])
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)
        gebucht = [(a.schluessel_id, a.anzahl, a.status, a.mieter_id, a.abnahme_id) for a in self.ausgaben(vertrag=v)]
        self.assertEqual(gebucht, [(wohnung.id, 3, 'ausgegeben', m.id, prot.id),
                                   (haustuer.id, 1, 'ausgegeben', m.id, prot.id)])
        with mandant(self.a.organisation):
            abnahme_buchen(prot)
        self._abschliessen(prot, [3, 1])                 # abgeschlossen: nur Weiterleitung
        self.assertEqual(len(self.ausgaben(vertrag=v)), 2)

    def test_auszug_soll_aus_ausgaben_ruecknahme_und_verlust_ohne_doppelung(self):
        from core.models import Pendenz
        from core.services.schluessel import abnahme_buchen
        lg, e, _m, v = self.wohnung()
        wohnung = self.schluessel(lg, e, typ='Wohnung', schluessel_nummer='31', anzahl=5)
        self.schluessel(lg, None, typ='Velo', schluessel_nummer='V1', anzahl=4)    # nie ausgegeben
        self.ausgeben(lg, [(wohnung, 3)], f'vertrag:{v.id}')
        prot = self._protokoll(v, 'auszug')
        # Soll: die 3 ausgegebenen Wohnungsschlüssel — nicht 5 aus dem Register, kein Veloschlüssel.
        self.assertEqual([(z.bezeichnung, z.anlage, z.soll) for z in prot.schluessel.all()],
                         [('Wohnung', '31', 3)])
        self._abschliessen(prot, [2])
        stand = sorted((a.status, a.anzahl) for a in self.ausgaben(vertrag=v))
        self.assertEqual(stand, [('verloren', 1), ('zurueck', 2)])
        with mandant(self.a.organisation):
            self.assertEqual(Pendenz.objects.filter(quelle__startswith='schluessel:verlust:',
                                                    vertrag=v).count(), 1)
            abnahme_buchen(prot)
            self.assertEqual(Pendenz.objects.filter(quelle__startswith='schluessel:verlust:',
                                                    vertrag=v).count(), 1)
        self.assertEqual(sorted((a.status, a.anzahl) for a in self.ausgaben(vertrag=v)), stand)

    def test_auszug_ohne_ausgaben_nimmt_das_register_und_fuehrt_den_verlust(self):
        lg, e, _m, v = self.wohnung()
        self.schluessel(lg, e, typ='Wohnung', schluessel_nummer='31', anzahl=3)
        prot = self._protokoll(v, 'auszug')
        self.assertEqual([z.soll for z in prot.schluessel.all()], [3])
        self._abschliessen(prot, [2])
        self.assertEqual([(a.status, a.anzahl) for a in self.ausgaben(vertrag=v)], [('verloren', 1)])


class DienstleisterTests(_Basis):

    def test_liste_beim_dienstleister_zeigt_die_ausgabe(self):
        """Regression: `h.schluesselausgabe` gab es nicht, die Liste war immer leer."""
        lg, e, _m, _v = self.wohnung()
        sch = self.schluessel(lg, e, schluessel_nummer='GS-22', anzahl=4)
        self.ausgeben(lg, [(sch, 2)], f'handwerker:{self.a.handwerker.id}')
        r = self.c.get(f'/neu/dienstleister/{self.a.handwerker.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['schluessel_akte']['offen']), 1)
        self.assertContains(r, 'GS-22')
        self.assertContains(r, f'schluessel/ruecknahme/?an=handwerker:{self.a.handwerker.id}')
        self.assertContains(r, 'nicht zurückgegeben')          # Kennzahl im Aktenkopf


class AktenTests(_Basis):

    def test_person_und_vertrag_zeigen_schluessel_mit_verlauf(self):
        lg, e, m, v = self.wohnung()
        sch = self.schluessel(lg, e, schluessel_nummer='31-33')
        self.ausgeben(lg, [(sch, 2)], f'vertrag:{v.id}')
        for pfad in (f'/neu/personen/{m.id}/', f'/neu/vertraege/{v.id}/'):
            with self.subTest(pfad=pfad):
                r = self.c.get(pfad)
                self.assertEqual(len(r.context['schluessel_akte']['offen']), 1)
                self.assertEqual(len(r.context['schluessel_akte']['verlauf']), 1)
                self.assertContains(r, '31-33')
                # Die Liste selbst (nicht bloss ein Protokolleintrag mit der Nummer):
                self.assertContains(r, f'schluessel/ruecknahme/?an=vertrag:{v.id}')

    def test_objekt_zeigt_karten_statt_tabelle(self):
        lg, e, _m, v = self.wohnung()
        sch = self.schluessel(lg, e, schluessel_nummer='W-77')
        self.ausgeben(lg, [(sch, 1)], f'vertrag:{v.id}')
        r = self.c.get(f'/neu/objekte/{e.id}/')
        self.assertContains(r, f'data-schluessel="{sch.id}"')
        self.assertContains(r, 'Anna Meier')
        self.assertNotContains(r, 'name="empfaenger"')          # die alte Tabelle mit Select ist weg


class HaustuerTests(_Basis):

    def test_schluessel_ohne_einheit_mit_tueren(self):
        from portfolio.models import Schliesspunkt, Schluessel
        lg, _e, _m, _v = self.wohnung()
        with mandant(self.a.organisation):
            tuer = Schliesspunkt.objects.create(liegenschaft=lg, bezeichnung='Haustür')
        r = self.c.post(f'/neu/liegenschaften/{lg.id}/schluessel/neu/', {
            'typ': 'Haustür', 'schluessel_nummer': '10-24', 'anzahl': '15', 'art': 'gruppe',
            'einheit_id': '', 'oeffnet': [tuer.id]})
        self.assertEqual(r.status_code, 302)
        with mandant(self.a.organisation):
            sch = Schluessel.objects.get(liegenschaft=lg, schluessel_nummer='10-24')
            self.assertEqual(list(sch.oeffnet.all()), [tuer])
        self.assertIsNone(sch.einheit_id)
        self.assertEqual((sch.art, sch.anzahl), ('gruppe', 15))
        seite = self.c.get(f'/neu/liegenschaften/{lg.id}/?tuer={tuer.id}')
        self.assertEqual([k['s'].id for k in seite.context['sl_karten']], [sch.id])
        self.assertContains(seite, '10-24')

    def test_hauptschluessel_kommt_durch_jede_tuer_der_anlage(self):
        from portfolio.models import Schliessanlage, Schliesspunkt
        lg, e, _m, _v = self.wohnung()
        with mandant(self.a.organisation):
            an = Schliessanlage.objects.create(liegenschaft=lg, hersteller='Kaba')
            keller = Schliesspunkt.objects.create(liegenschaft=lg, anlage=an, bezeichnung='Keller')
        haupt = self.schluessel(lg, None, typ='Haupt', schluessel_nummer='01', art='haupt', schliessanlage=an)
        self.schluessel(lg, e, typ='Wohnung', schluessel_nummer='31')
        seite = self.c.get(f'/neu/liegenschaften/{lg.id}/?tuer={keller.id}')
        self.assertEqual([k['s'].id for k in seite.context['sl_karten']], [haupt.id])

    def test_karten_kosten_drei_abfragen_unabhaengig_von_der_zahl(self):
        from core.services.schluessel import karten
        from portfolio.models import Schluessel
        lg, e, _m, v = self.wohnung()
        for i in range(6):
            sch = self.schluessel(lg, e, schluessel_nummer=f'N{i}')
        self.ausgeben(lg, [(sch, 1)], f'vertrag:{v.id}')
        with mandant(self.a.organisation):
            with self.assertNumQueries(3):
                liste = karten(Schluessel.objects.filter(liegenschaft=lg))
                [a.empfaenger_name for k in liste for a in k['offene']]
        self.assertEqual(len(liste), 6)


class HeuteUndFristenTests(_Basis):

    def test_ueberfaellige_rueckgabe_zeigt_kachel_und_frist(self):
        from faelle.heute_kacheln import kacheln
        from portfolio.models import SchluesselAusgabe
        lg, e, _m, _v = self.wohnung()
        sch = self.schluessel(lg, e)
        with mandant(self.a.organisation):
            SchluesselAusgabe.objects.create(schluessel=sch, handwerker=self.a.handwerker,
                                             rueckgabe_bis=self.heute - timedelta(days=3))
            SchluesselAusgabe.objects.create(schluessel=sch, handwerker=self.a.handwerker,
                                             rueckgabe_bis=self.heute + timedelta(days=3))
            liste = kacheln('bewirtschaftung', self.heute, None, {}, [])
        k = next(k for k in liste if k['schluessel'] == 'schluessel')
        self.assertEqual((k['zahl'], k['ziel']), (1, f'/neu/liegenschaften/{lg.id}/?tab=stammdaten#schliessanlage'))
        # Eine überfällige Ausgabe bei B zählt bei A nicht.
        lg_b, e_b, _mb, _vb = self.wohnung(self.b, 'B-Zimmer')
        sch_b = self.schluessel(lg_b, e_b)
        with mandant(self.b.organisation):
            SchluesselAusgabe.objects.create(schluessel=sch_b, rueckgabe_bis=self.heute - timedelta(days=9))
        with mandant(self.a.organisation):
            k = next(k for k in kacheln('bewirtschaftung', self.heute, None, {}, []) if k['schluessel'] == 'schluessel')
        self.assertEqual(k['zahl'], 1)
        # In den Fristen: beide Ausgaben von A, keine von B (gleiche Nummer, deshalb gezählt).
        fristen = self.c.get('/neu/fristen/')
        titel = [e['titel'] for b in fristen.context['buckets'] for e in b['items']]
        self.assertEqual(sch_b.schluessel_nummer, sch.schluessel_nummer)
        self.assertEqual(titel.count(f'Schlüssel zurück: Wohnung Nr. {sch.schluessel_nummer}'), 2)
        self.assertEqual(self.c.get('/neu/schluessel/faellig/').status_code, 200)


class IsolationTests(_Basis):
    """Fremde IDs: 404 und kein veränderter Bestand — auch versteckt im Formular."""

    def test_fremder_schluessel_ausgabe_anlage_und_tuer_ergeben_404(self):
        b = self.b
        aufrufe = [
            ('post', f'/neu/schluessel/{b.schluessel.id}/bearbeiten/', {'typ': 'X', 'schluessel_nummer': '1'}),
            ('post', f'/neu/schluessel/{b.schluessel.id}/loeschen/', {}),
            ('get', f'/neu/schluessel/{b.schluessel.id}/ausgabe/', {}),
            ('post', f'/neu/schluessel/ausgabe/{b.schluessel_ausgabe.id}/rueckgabe/', {}),
            ('post', f'/neu/schliessanlage/{b.schliessanlage.id}/loeschen/', {}),
            ('post', f'/neu/schliesspunkt/{b.schliesspunkt.id}/loeschen/', {}),
            ('get', f'/neu/liegenschaften/{b.liegenschaft.id}/schluessel/ausgabe/', {}),
            ('get', f'/neu/liegenschaften/{b.liegenschaft.id}/schluessel/ruecknahme/', {}),
            ('post', f'/neu/liegenschaften/{b.liegenschaft.id}/schliessanlage/', {'hersteller': 'X'}),
            ('post', f'/neu/liegenschaften/{b.liegenschaft.id}/schliesspunkt/', {'bezeichnung': 'X'}),
            ('post', f'/neu/liegenschaften/{b.liegenschaft.id}/schluessel/neu/',
             {'typ': 'X', 'schluessel_nummer': '1'}),
        ]
        for art, pfad, daten in aufrufe:
            with self.subTest(pfad=pfad):
                r = getattr(self.c, art)(pfad, daten)
                self.assertEqual(r.status_code, 404)
        with mandant(b.organisation):
            b.schluessel.refresh_from_db()
            self.assertFalse(b.schluessel.archiviert)
            self.assertEqual(b.schluessel.schluessel_nummer, 'S-B-01')
            from portfolio.models import Schliessanlage, Schliesspunkt
            self.assertTrue(Schliessanlage.objects.filter(pk=b.schliessanlage.pk).exists())
            self.assertTrue(Schliesspunkt.objects.filter(pk=b.schliesspunkt.pk).exists())

    def test_fremde_ids_im_formular_der_eigenen_liegenschaft(self):
        lg, e, _m, v = self.wohnung()
        sch = self.schluessel(lg, e)
        # Fremder Schlüssel in der Auswahl: wird nicht angeboten, also nicht gebucht.
        self.ausgeben(lg, [(self.b.schluessel, 1)], f'vertrag:{v.id}')
        # Fremder Vertrag als Empfänger: abgelehnt.
        self.ausgeben(lg, [(sch, 1)], f'vertrag:{self.b.vertrag.id}')
        self.assertEqual(self.ausgaben(schluessel=sch), [])
        # Fremde Tür, fremde Anlage, fremde Einheit am eigenen Schlüssel: 404, nichts geändert.
        for feld, wert in (('oeffnet', self.b.schliesspunkt.id), ('schliessanlage', self.b.schliessanlage.id),
                           ('einheit_id', self.b.einheit.id)):
            with self.subTest(feld=feld):
                r = self.c.post(f'/neu/schluessel/{sch.id}/bearbeiten/',
                                {'typ': 'Wohnung', 'schluessel_nummer': '31', feld: wert})
                self.assertIn(r.status_code, (302, 404))
                sch.refresh_from_db()
                with mandant(self.a.organisation):
                    self.assertEqual(list(sch.oeffnet.all()), [])
                self.assertIsNone(sch.schliessanlage_id)
                self.assertEqual(sch.einheit_id, e.id)
        # Fremde Ausgabe auf der Rücknahmeseite des eigenen Empfängers: bleibt unberührt.
        self.c.post(f'/neu/liegenschaften/{lg.id}/schluessel/ruecknahme/', {
            'an': f'mieter:{self.b.mieter.id}', f'status_{self.b.schluessel_ausgabe.id}': 'zurueck',
            'unterschrift': png_data_url('black')})
        with mandant(self.b.organisation):
            self.b.schluessel_ausgabe.refresh_from_db()
            self.assertEqual(self.b.schluessel_ausgabe.status, 'ausgegeben')
