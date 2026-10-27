"""Die Palette sucht über alle Module — und nur im eigenen Bestand.

DER AUFTRAG (27.10.2026)

`/neu/palette/` fand Personen, Liegenschaften, Objekte und Verträge, höchstens
15 Treffer. Die Kopfzeile bekommt ein Suchfeld über ALLE Module: Mieter und
Dienstleister, Liegenschaften und Objekte, Verträge, Debitoren- und
Kreditorenrechnungen, Schadenmeldungen und die neueste Fassung der Dokumente.
Jede Gruppe liefert höchstens fünf Treffer samt Status und Betrag, dazu die
Trefferzahl je Gruppe.

WARUM DIESE DATEI NEBEN `test_palette_suche.py` STEHT

Die alte Datei bewacht die vier alten Arten und bleibt unverändert gültig. Hier
steht, was neu ist: jede der sechs Gruppen, der Vertrag der Antwort (`gruppe`,
`status`, `betrag`, `zahlen`), die Obergrenzen, die Abfragezahl — und die
Mandantengrenze für JEDE Gruppe einzeln. «Der Manager filtert» ist eine
Annahme, und neun Modelle sind neun Stellen, an denen sie brechen kann.

WIE DIE GRENZE GEPRÜFT WIRD

Gesucht wird mit einem Begriff, der in BEIDEN Beständen vorkommt («Mieter»,
«Sanitaer», «Wasserschaden» …). Nur der Mandantenfilter entscheidet dann, was
zurückkommt. Eine Suche nach einem Begriff, den nur der fremde Bestand trägt,
wäre auch ohne Filter leer, wenn die Suche selbst schon nichts findet. Dazu die
Gegenprobe: derselbe Begriff liefert dem anderen Mandanten SEINE Daten.
"""
import json
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import quote_plus

from django.apps import apps
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import translation

from core.services import palette_suche
from core.tenancy import organisation_kontext

from ._isolation import MandantenFixture

GRUPPEN = ['personen', 'immobilien', 'vertraege', 'buchhaltung', 'tickets', 'dokumente']
TREFFER_SCHLUESSEL = {'gruppe', 'art', 'label', 'zusatz', 'url', 'status', 'betrag'}


def _dokument_anlegen(m, titel, dateiname, **zusatz):
    """Ein Dokument in der Vertragsablage des Mandanten `m`."""
    from rentals.models import Dokument
    with organisation_kontext(m.organisation):
        return Dokument.objects.create(
            vertrag=m.vertrag, mieter=m.mieter, titel=titel, bezeichnung=titel,
            kategorie='korrespondenz',
            datei=f'organisation/{m.organisation.pk}/korrespondenz/2026-10-14/{dateiname}',
            **zusatz)


class Basis(TestCase):
    """Zwei Mandanten mit je einem Kündigungsschreiben in der Ablage."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        # Der Titel ist der gemeinsame Suchbegriff, der Dateiname trägt die
        # Kennung des Mandanten.
        cls.a.schreiben = _dokument_anlegen(
            cls.a, 'Kündigungsschreiben A', 'kuendigung_seestrasse_a.pdf')
        cls.b.schreiben = _dokument_anlegen(
            cls.b, 'Kündigungsschreiben B', 'kuendigung_seestrasse_b.pdf')

    def _antwort(self, m, q, **kopf):
        c = Client(**kopf)
        c.force_login(m.benutzer)
        antwort = c.get('/neu/palette/', {'q': q})
        self.assertEqual(antwort.status_code, 200)
        return json.loads(antwort.content)

    def _gruppe(self, m, q, gruppe):
        return [t for t in self._antwort(m, q)['treffer'] if t['gruppe'] == gruppe]

    def _kontext(self, m):
        return organisation_kontext(m.organisation)


class VertragDerAntwortTests(Basis):

    def test_form_der_antwort(self):
        daten = self._antwort(self.a, 'Mieter')
        self.assertEqual(set(daten), {'q', 'treffer', 'zahlen'})
        self.assertEqual(daten['q'], 'Mieter')
        # Die Reihenfolge der Gruppen im JSON ist Teil des Vertrags.
        self.assertEqual(list(daten['zahlen']), GRUPPEN)
        self.assertTrue(daten['treffer'], 'Keine Treffer — dann prüft die Form nichts.')
        for t in daten['treffer']:
            with self.subTest(t=t['label']):
                self.assertEqual(set(t), TREFFER_SCHLUESSEL)
                self.assertIn(t['gruppe'], GRUPPEN)
                self.assertTrue(t['url'].startswith('/neu/'), t)
                if t['status'] is not None:
                    self.assertEqual(set(t['status']), {'text', 'ton'})
                    self.assertIn(t['status']['ton'], ('crit', 'warn', 'good', 'mut'))
                    self.assertTrue(t['status']['text'])
                self.assertTrue(t['betrag'] is None or t['betrag'].startswith('CHF '))

    def test_gruppen_stehen_in_der_vereinbarten_reihenfolge(self):
        # «Weg 7» trifft Liegenschaft, Objekt, Vertrag, Kreditor und Ticket.
        folge = [t['gruppe'] for t in self._antwort(self.a, 'Weg 7')['treffer']]
        self.assertGreaterEqual(len(set(folge)), 4, folge)
        self.assertEqual(folge, sorted(folge, key=GRUPPEN.index))

    def test_zahlen_nennen_jede_gruppe_auch_ohne_treffer(self):
        daten = self._antwort(self.a, 'zzzqqq')
        self.assertEqual(daten['treffer'], [])
        self.assertEqual(daten['zahlen'], dict.fromkeys(GRUPPEN, 0))


class GruppenTests(Basis):
    """Jede Gruppe liefert ihre Treffer samt Status und Betrag."""

    def test_personen_mieter(self):
        t = self._gruppe(self.a, 'Mieter A', 'personen')
        self.assertEqual(len(t), 1, t)
        self.assertEqual(t[0]['art'], 'Person')
        self.assertEqual(t[0]['label'], 'Mieter A')
        self.assertEqual(t[0]['url'], f'/neu/personen/{self.a.mieter.id}/')
        # Der Mieter hat einen Vertrag im Status «aktiv» (Fixture).
        self.assertEqual(t[0]['status'], {'text': 'Aktiv', 'ton': 'good'})
        self.assertIsNone(t[0]['betrag'])

    def test_person_ohne_aktiven_vertrag_hat_keinen_status(self):
        """Der Status «aktiv» ist belegt, nicht Standard: Ohne aktiven Vertrag
        kein Status. Gegenprobe zum Test darüber."""
        from rentals.models import Mietvertrag
        with self._kontext(self.a):
            Mietvertrag.objects.filter(pk=self.a.vertrag.pk).update(status='archiviert')
        t = self._gruppe(self.a, 'Mieter A', 'personen')
        self.assertEqual(len(t), 1)
        self.assertIsNone(t[0]['status'])

    def test_personen_mitmieter_gilt_als_aktiv(self):
        """Wie in der Personenliste: auch der Mitmieter eines aktiven Vertrags."""
        from crm.models import Mieter
        from rentals.models import Mietvertrag
        with self._kontext(self.a):
            zweite = Mieter.objects.create(typ='person', vorname='Mitbewohner', nachname='Probe')
            Mietvertrag.objects.filter(pk=self.a.vertrag.pk).update(mitmieter=zweite)
        t = self._gruppe(self.a, 'Mitbewohner', 'personen')
        self.assertEqual(t[0]['status'], {'text': 'Aktiv', 'ton': 'good'})

    def test_personen_dienstleister(self):
        t = self._gruppe(self.a, 'Sanitaer', 'personen')
        self.assertEqual(len(t), 1, t)
        self.assertEqual(t[0]['art'], 'Dienstleister')
        self.assertEqual(t[0]['label'], 'Sanitaer A GmbH')
        self.assertEqual(t[0]['url'], f'/neu/dienstleister/{self.a.handwerker.id}/')
        self.assertIsNone(t[0]['betrag'])

    def test_dienstleister_wird_auch_ueber_die_kontaktperson_gefunden(self):
        from crm.models import Handwerker
        with self._kontext(self.a):
            Handwerker.objects.filter(pk=self.a.handwerker.pk).update(kontaktperson='Frau Wasserhahn')
        self.assertEqual(len(self._gruppe(self.a, 'Wasserhahn', 'personen')), 1)

    def test_immobilien_liegenschaft_und_objekt(self):
        t = {x['art']: x for x in self._gruppe(self.a, 'A-Weg', 'immobilien')}
        self.assertEqual(set(t), {'Liegenschaft', 'Objekt'})
        self.assertEqual(t['Liegenschaft']['label'], 'A-Weg 7')
        self.assertEqual(t['Liegenschaft']['url'], f'/neu/liegenschaften/{self.a.liegenschaft.id}/')
        # Das Fixture setzt die Liegenschaft auf «Entwurf» (STWEG-Daten).
        self.assertEqual(t['Liegenschaft']['status'], {'text': 'Entwurf', 'ton': 'mut'})
        self.assertEqual(t['Objekt']['label'], '3.5 Zi A')
        self.assertEqual(t['Objekt']['url'], f'/neu/objekte/{self.a.einheit.id}/')
        self.assertIsNone(t['Objekt']['status'])
        for x in t.values():
            self.assertIsNone(x['betrag'])

    def test_liegenschaft_aktiv_ist_gut(self):
        from portfolio.models import Liegenschaft
        with self._kontext(self.a):
            Liegenschaft.objects.filter(pk=self.a.liegenschaft.pk).update(status='aktiv')
        t = [x for x in self._gruppe(self.a, 'A-Weg', 'immobilien') if x['art'] == 'Liegenschaft']
        self.assertEqual(t[0]['status'], {'text': 'Aktiv', 'ton': 'good'})

    def test_vertraege(self):
        t = self._gruppe(self.a, 'Mieter A', 'vertraege')
        self.assertEqual(len(t), 1, t)
        self.assertEqual(t[0]['art'], 'Mietverhältnis')
        self.assertEqual(t[0]['label'], 'Mieter A')
        self.assertEqual(t[0]['zusatz'], 'A-Weg 7, 3.5 Zi A')
        self.assertEqual(t[0]['url'], f'/neu/vertraege/{self.a.vertrag.id}/')
        self.assertEqual(t[0]['status'], {'text': 'Aktiv', 'ton': 'good'})
        self.assertIsNone(t[0]['betrag'])

    def test_vertragsstatus_folgt_dem_anzeigestatus(self):
        """Wie die Vertragsliste: gekündigt rot, abgelaufen «Beendet» gedämpft."""
        from rentals.models import Mietvertrag
        gestern = date.today() - timedelta(days=1)
        faelle = [
            ('gekuendigt', None, {'text': 'Gekündigt', 'ton': 'crit'}),
            ('aktiv', gestern, {'text': 'Beendet', 'ton': 'mut'}),
            ('archiviert', None, {'text': 'Beendet', 'ton': 'mut'}),
            ('entwurf', None, {'text': 'Entwurf', 'ton': 'mut'}),
        ]
        for status, ende, soll in faelle:
            with self.subTest(status=status, ende=ende):
                with self._kontext(self.a):
                    Mietvertrag.objects.filter(pk=self.a.vertrag.pk).update(status=status, ende=ende)
                self.assertEqual(self._gruppe(self.a, 'Mieter A', 'vertraege')[0]['status'], soll)

    def test_debitorenrechnung_ueberfaellig_ist_crit(self):
        t = self._gruppe(self.a, 'Miete 02/2024', 'buchhaltung')
        self.assertEqual(len(t), 1, t)
        self.assertEqual(t[0]['art'], 'Debitorenrechnung')
        self.assertEqual(t[0]['label'], 'Miete 02/2024 A')
        self.assertEqual(t[0]['zusatz'], 'Mieter A')
        # Die Fälligkeit (28.02.2024) liegt in der Vergangenheit, Status «offen».
        self.assertEqual(t[0]['status'], {'text': 'Überfällig', 'ton': 'crit'})
        self.assertEqual(t[0]['betrag'], "CHF 1'700.00")
        self.assertIn(quote_plus('Miete 02/2024 A'), t[0]['url'])
        self.assertTrue(t[0]['url'].startswith('/neu/debitoren/?q='))

    def test_debitorenstatus_nach_bestand(self):
        """Offen und nicht fällig: warn. Bezahlt: good. Storniert: mut.
        Teilbezahlt und überfällig: crit — die Fälligkeit entscheidet, nicht
        das Wort «teilbezahlt»."""
        from finance.models import DebitorenRechnung
        morgen = date.today() + timedelta(days=10)
        gestern = date.today() - timedelta(days=10)
        faelle = [
            ('offen', morgen, {'text': 'Offen', 'ton': 'warn'}),
            ('teilbezahlt', morgen, {'text': 'Teilbezahlt', 'ton': 'warn'}),
            ('bezahlt', gestern, {'text': 'Bezahlt', 'ton': 'good'}),
            ('storniert', gestern, {'text': 'Storniert', 'ton': 'mut'}),
            ('abgeschrieben', gestern, {'text': 'Abgeschrieben', 'ton': 'mut'}),
            ('teilbezahlt', gestern, {'text': 'Überfällig', 'ton': 'crit'}),
            ('offen', None, {'text': 'Überfällig', 'ton': 'crit'}),   # Rechnungsdatum 2024
        ]
        with self._kontext(self.a):
            for i, (status, faellig, _soll) in enumerate(faelle):
                DebitorenRechnung.objects.create(
                    vertrag=self.a.vertrag, titel=f'Statusprobe{i}x', betrag=Decimal('250.5'),
                    datum=date(2024, 3, 1), faellig_am=faellig, status=status)
        for i, (status, faellig, soll) in enumerate(faelle):
            with self.subTest(status=status, faellig=faellig):
                t = self._gruppe(self.a, f'Statusprobe{i}x', 'buchhaltung')
                self.assertEqual(len(t), 1, t)
                self.assertEqual(t[0]['status'], soll)
                self.assertEqual(t[0]['betrag'], 'CHF 250.50')

    def test_kreditorenrechnung(self):
        t = self._gruppe(self.a, 'Handwerk', 'buchhaltung')
        self.assertEqual(len(t), 1, t)
        self.assertEqual(t[0]['art'], 'Kreditorenrechnung')
        self.assertEqual(t[0]['label'], 'Handwerk A GmbH')
        self.assertEqual(t[0]['zusatz'], 'A-Weg 7')
        self.assertEqual(t[0]['status'], {'text': 'Neu / Scan', 'ton': 'warn'})
        self.assertEqual(t[0]['betrag'], 'CHF 500.00')
        self.assertTrue(t[0]['url'].startswith('/neu/kreditoren/?q='))

    def test_kreditorenstatus_nach_bestand(self):
        from finance.models import KreditorenRechnung
        morgen = date.today() + timedelta(days=10)
        gestern = date.today() - timedelta(days=10)
        faelle = [
            ('freigegeben', morgen, {'text': 'Freigegeben', 'ton': 'warn'}),
            ('in_zahlung', morgen, {'text': 'In Zahlung', 'ton': 'warn'}),
            ('bezahlt', gestern, {'text': 'Bezahlt', 'ton': 'good'}),
            ('freigegeben', gestern, {'text': 'Überfällig', 'ton': 'crit'}),
        ]
        with self._kontext(self.a):
            for i, (status, faellig, _soll) in enumerate(faelle):
                KreditorenRechnung.objects.create(
                    lieferant=f'Lieferprobe{i}x AG', betrag=Decimal('99'), status=status,
                    liegenschaft=self.a.liegenschaft, faellig_am=faellig)
        for i, (status, faellig, soll) in enumerate(faelle):
            with self.subTest(status=status, faellig=faellig):
                t = self._gruppe(self.a, f'Lieferprobe{i}x', 'buchhaltung')
                self.assertEqual(len(t), 1, t)
                self.assertEqual(t[0]['status'], soll)

    def test_stornierte_kreditorenrechnung_steht_nicht_drin(self):
        """Die Kreditorenliste zeigt Stornierte nicht; der Treffer wäre ein toter Link."""
        from finance.models import KreditorenRechnung
        with self._kontext(self.a):
            KreditorenRechnung.objects.create(
                lieferant='Storno Lieferant AG', betrag=Decimal('10'), status='storniert')
        self.assertEqual(self._gruppe(self.a, 'Storno Lieferant', 'buchhaltung'), [])
        # Gegenprobe: im Bestand ist sie da.
        self.assertTrue(KreditorenRechnung.alle_organisationen.filter(
            lieferant__startswith='Storno').exists())

    def test_ticket(self):
        t = self._gruppe(self.a, 'Wasserschaden', 'tickets')
        self.assertEqual(len(t), 1, t)
        self.assertEqual(t[0]['art'], 'Ticket')
        self.assertEqual(t[0]['label'], f'#{self.a.schaden.id} Wasserschaden A')
        self.assertEqual(t[0]['zusatz'], 'A-Weg 7, 3.5 Zi A')
        self.assertEqual(t[0]['url'], f'/neu/schaeden/{self.a.schaden.id}/')
        self.assertEqual(t[0]['status'], {'text': 'Neu', 'ton': 'crit'})
        self.assertIsNone(t[0]['betrag'])

    def test_ticketstatus_nach_bestand(self):
        from tickets.models import SchadenMeldung
        faelle = {
            'in_bearbeitung': {'text': 'In Bearbeitung', 'ton': 'warn'},
            'warte_auf_handwerker': {'text': 'Warte auf Handwerker', 'ton': 'warn'},
            'erledigt': {'text': 'Erledigt', 'ton': 'good'},
        }
        for status, soll in faelle.items():
            with self.subTest(status=status):
                with self._kontext(self.a):
                    SchadenMeldung.objects.filter(pk=self.a.schaden.pk).update(status=status)
                t = self._gruppe(self.a, 'Wasserschaden', 'tickets')
                self.assertEqual(t[0]['status'], soll)

    def test_dokument_ueber_titel_und_dateiname(self):
        for q in ('Kündigungsschreiben', 'kuendigung_seestrasse_a'):
            with self.subTest(q=q):
                t = self._gruppe(self.a, q, 'dokumente')
                self.assertEqual(len(t), 1, t)
                self.assertEqual(t[0]['art'], 'Dokument')
                self.assertEqual(t[0]['label'], 'Kündigungsschreiben A')
                self.assertTrue(t[0]['zusatz'].startswith('Mieter A · '), t[0]['zusatz'])
                self.assertEqual(t[0]['url'], f'/neu/dokument/{self.a.schreiben.id}/verlauf/')
                self.assertIsNone(t[0]['status'])
                self.assertIsNone(t[0]['betrag'])

    def test_dokument_dateiname_gross_klein_egal(self):
        self.assertEqual(len(self._gruppe(self.a, 'KUENDIGUNG_SEESTRASSE', 'dokumente')), 1)

    def test_dokument_der_ordnerpfad_zaehlt_nicht(self):
        """Der Pfad lautet organisation/<id>/korrespondenz/<datum>/<name>: Er
        gehört in jedes Dokument und taugt nicht als Suchtreffer."""
        for q in ('organisation', 'korrespondenz', '2026-10-14'):
            with self.subTest(q=q):
                self.assertEqual(self._gruppe(self.a, q, 'dokumente'), [])
        # Gegenprobe: der Pfad enthält diese Stücke wirklich.
        self.assertIn('organisation', self.a.schreiben.datei.name)

    def test_dokument_nur_die_neueste_fassung(self):
        from rentals.models import Dokument
        alt = _dokument_anlegen(self.a, 'Mahnschreiben', 'mahnung_v1.pdf')
        with self._kontext(self.a):
            neu = Dokument.objects.create(
                vertrag=self.a.vertrag, mieter=self.a.mieter, titel='Mahnschreiben',
                bezeichnung='Mahnschreiben', kategorie='korrespondenz', version=2, vorgaenger=alt,
                datei=f'organisation/{self.a.organisation.pk}/korrespondenz/2026-10-15/mahnung_v2.pdf')
        daten = self._antwort(self.a, 'Mahnschreiben')
        t = [x for x in daten['treffer'] if x['gruppe'] == 'dokumente']
        self.assertEqual([x['url'] for x in t], [f'/neu/dokument/{neu.id}/verlauf/'])
        self.assertEqual(daten['zahlen']['dokumente'], 1)
        # Auch der Dateiname der alten Fassung führt nicht zu ihr.
        self.assertEqual(self._gruppe(self.a, 'mahnung_v1', 'dokumente'), [])

    def test_dokument_ohne_datei_steht_nicht_drin(self):
        from rentals.models import Dokument
        with self._kontext(self.a):
            Dokument.objects.create(vertrag=self.a.vertrag, titel='Dateiloses Schreiben',
                                    bezeichnung='Dateiloses Schreiben', kategorie='sonstiges',
                                    datei='')
        self.assertEqual(self._gruppe(self.a, 'Dateiloses', 'dokumente'), [])

    def test_ein_dokument_ohne_mieter_zeigt_die_liegenschaft(self):
        from rentals.models import Dokument
        with self._kontext(self.a):
            Dokument.objects.create(
                liegenschaft=self.a.liegenschaft, titel='Gebäudeplan', bezeichnung='Gebäudeplan',
                kategorie='sonstiges',
                datei=f'organisation/{self.a.organisation.pk}/uploads/2026-10-14/plan.pdf')
        t = self._gruppe(self.a, 'Gebäudeplan', 'dokumente')
        self.assertTrue(t[0]['zusatz'].startswith('A-Weg 7 · '), t)


class GrenzenTests(Basis):
    """Höchstens fünf je Gruppe, und `zahlen` stimmt."""

    def _handwerker(self, m, wieviele, praefix):
        from crm.models import Handwerker
        with self._kontext(m):
            for i in range(wieviele):
                Handwerker.objects.create(firma=f'{praefix} {i:03d} AG')

    def test_hoechstens_fuenf_je_gruppe_und_die_zahl_stimmt(self):
        self._handwerker(self.a, 7, 'Zeta')
        self._handwerker(self.b, 3, 'Zeta')       # zählen für A nicht
        daten = self._antwort(self.a, 'Zeta')
        personen = [t for t in daten['treffer'] if t['gruppe'] == 'personen']
        self.assertEqual(len(personen), 5)
        self.assertEqual(daten['zahlen']['personen'], 7)
        # Alphabetisch, nicht zufällig.
        self.assertEqual([t['label'] for t in personen],
                         [f'Zeta {i:03d} AG' for i in range(5)])
        # Und die anderen Gruppen bleiben leer.
        self.assertEqual(sum(daten['zahlen'][g] for g in GRUPPEN if g != 'personen'), 0)

    def test_die_zahl_stoppt_bei_99(self):
        self._handwerker(self.a, 100, 'Massen')
        daten = self._antwort(self.a, 'Massen')
        self.assertEqual(daten['zahlen']['personen'], 99)
        self.assertEqual(len([t for t in daten['treffer'] if t['gruppe'] == 'personen']), 5)

    def test_zahl_genau_99_und_98(self):
        """Die Grenze ist «99», nicht «98 plus eins»."""
        self._handwerker(self.a, 98, 'Knapp')
        self.assertEqual(self._antwort(self.a, 'Knapp')['zahlen']['personen'], 98)
        self._handwerker(self.a, 1, 'Knapp')
        self.assertEqual(self._antwort(self.a, 'Knapp')['zahlen']['personen'], 99)

    def test_die_fuenf_gelten_fuer_die_ganze_gruppe_nicht_je_modell(self):
        """Buchhaltung = Debitoren UND Kreditoren: zusammen höchstens fünf."""
        from finance.models import DebitorenRechnung, KreditorenRechnung
        with self._kontext(self.a):
            for i in range(4):
                DebitorenRechnung.objects.create(
                    vertrag=self.a.vertrag, titel=f'Sammel D{i}', betrag=Decimal('10'),
                    datum=date(2025, 1, 1 + i), faellig_am=date(2025, 2, 1))
                KreditorenRechnung.objects.create(
                    lieferant=f'Sammel K{i}', betrag=Decimal('10'), datum=date(2025, 1, 10 + i))
        daten = self._antwort(self.a, 'Sammel')
        t = [x for x in daten['treffer'] if x['gruppe'] == 'buchhaltung']
        self.assertEqual(len(t), 5)
        self.assertEqual(daten['zahlen']['buchhaltung'], 8)
        # Neueste zuerst: die Kreditoren vom 10.-13. Januar vor den Debitoren
        # vom 1.-4. Januar.
        self.assertEqual([x['label'] for x in t][:4], ['Sammel K3', 'Sammel K2', 'Sammel K1', 'Sammel K0'])

    def test_tickets_zaehlen_und_sortieren_neueste_zuerst(self):
        from tickets.models import SchadenMeldung
        with self._kontext(self.a):
            for i in range(6):
                SchadenMeldung.objects.create(
                    liegenschaft=self.a.liegenschaft, titel=f'Tropft {i}', beschreibung='x')
        daten = self._antwort(self.a, 'Tropft')
        t = [x for x in daten['treffer'] if x['gruppe'] == 'tickets']
        self.assertEqual(len(t), 5)
        self.assertEqual(daten['zahlen']['tickets'], 6)
        ids = [int(x['url'].rstrip('/').split('/')[-1]) for x in t]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_die_gesamtmenge_ist_hoechstens_fuenf_mal_sechs(self):
        daten = self._antwort(self.a, 'Weg 7')
        self.assertLessEqual(len(daten['treffer']), 30)


class MandantentrennungTests(Basis):
    """Jede Gruppe, mit einem zweiten Mandanten und einem Begriff in beiden Beständen."""

    @staticmethod
    def _debitor_url(m):
        return f'/neu/debitoren/?q={quote_plus(m.debitor.titel)}'

    @staticmethod
    def _kreditor_url(m):
        return f'/neu/kreditoren/?q={quote_plus(m.kreditor.lieferant)}'

    def _faelle(self):
        return [
            # (Gruppe, Suchbegriff in BEIDEN Beständen, Adresse des Treffers je Mandant)
            ('personen', 'Mieter', lambda m: f'/neu/personen/{m.mieter.id}/'),
            ('personen', 'Sanitaer', lambda m: f'/neu/dienstleister/{m.handwerker.id}/'),
            ('immobilien', 'Weg 7', lambda m: f'/neu/liegenschaften/{m.liegenschaft.id}/'),
            ('immobilien', 'Weg 7', lambda m: f'/neu/objekte/{m.einheit.id}/'),
            ('vertraege', 'Mieter', lambda m: f'/neu/vertraege/{m.vertrag.id}/'),
            ('buchhaltung', 'Miete 02/2024', self._debitor_url),
            ('buchhaltung', 'Handwerk', self._kreditor_url),
            ('tickets', 'Wasserschaden', lambda m: f'/neu/schaeden/{m.schaden.id}/'),
            ('dokumente', 'Kündigungsschreiben',
             lambda m: f'/neu/dokument/{m.schreiben.id}/verlauf/'),
        ]

    def test_jede_gruppe_zeigt_nur_den_eigenen_bestand(self):
        for gruppe, begriff, adresse in self._faelle():
            for ich, fremd in ((self.a, self.b), (self.b, self.a)):
                with self.subTest(gruppe=gruppe, begriff=begriff, ich=ich.kuerzel,
                                  adresse=adresse(ich)):
                    daten = self._antwort(ich, begriff)
                    urls = [t['url'] for t in daten['treffer'] if t['gruppe'] == gruppe]
                    # Gegenprobe: der EIGENE Treffer ist da, die Suche findet also etwas.
                    self.assertIn(adresse(ich), urls)
                    self.assertNotIn(
                        adresse(fremd), urls,
                        f'Gruppe «{gruppe}»: Mandant {ich.kuerzel} sieht einen Treffer von '
                        f'Mandant {fremd.kuerzel}.')

    def test_die_zahlen_zaehlen_nur_den_eigenen_bestand(self):
        """`zahlen` ist eine eigene Abfrage — und eine eigene Stelle für ein Leck."""
        erwartet = {
            ('personen', 'Mieter'): 1, ('personen', 'Sanitaer'): 1,
            ('immobilien', 'Weg 7'): 2, ('vertraege', 'Mieter'): 1,
            ('buchhaltung', 'Miete 02/2024'): 1, ('buchhaltung', 'Handwerk'): 1,
            ('tickets', 'Wasserschaden'): 1, ('dokumente', 'Kündigungsschreiben'): 1,
        }
        for (gruppe, begriff), anzahl in erwartet.items():
            with self.subTest(gruppe=gruppe, begriff=begriff):
                for ich in (self.a, self.b):
                    self.assertEqual(self._antwort(ich, begriff)['zahlen'][gruppe], anzahl)

    def test_der_begriff_trifft_ohne_mandantenfilter_beide_bestaende(self):
        """Gegenprobe zu den Tests darüber: Ohne den Filter käme B in A's Antwort.

        Sonst wären sie auch dann grün, wenn die Fremddaten den Begriff gar
        nicht trügen.
        """
        from crm.models import Handwerker, Mieter
        from finance.models import DebitorenRechnung, KreditorenRechnung
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Dokument, Mietvertrag
        from tickets.models import SchadenMeldung
        roh = [
            Mieter.alle_organisationen.filter(vorname='Mieter'),
            Handwerker.alle_organisationen.filter(firma__icontains='Sanitaer'),
            Liegenschaft.alle_organisationen.filter(strasse__icontains='Weg 7'),
            Einheit.alle_organisationen.filter(liegenschaft__strasse__icontains='Weg 7'),
            Mietvertrag.alle_organisationen.filter(mieter__vorname='Mieter'),
            DebitorenRechnung.alle_organisationen.filter(titel__icontains='Miete 02/2024'),
            KreditorenRechnung.alle_organisationen.filter(lieferant__icontains='Handwerk'),
            SchadenMeldung.alle_organisationen.filter(titel__icontains='Wasserschaden'),
            Dokument.alle_organisationen.filter(titel__icontains='Kündigungsschreiben'),
        ]
        for qs in roh:
            with self.subTest(modell=qs.model.__name__):
                self.assertEqual(
                    set(qs.values_list('organisation_id', flat=True)),
                    {self.a.organisation.pk, self.b.organisation.pk})

    def test_fremde_kennungen_stehen_nirgends_in_der_antwort(self):
        """Auch nicht in `label` oder `zusatz`: Der Gesamttext der Antwort an A
        enthält keine Kennung von B."""
        for begriff in ('Mieter', 'Weg 7', 'Sanitaer', 'Miete 02/2024', 'Handwerk',
                        'Wasserschaden', 'Kündigungsschreiben'):
            with self.subTest(begriff=begriff):
                text = json.dumps(self._antwort(self.a, begriff), ensure_ascii=False)
                for fremd in ('Mieter B', 'B-Weg', 'Sanitaer B', 'Miete 02/2024 B',
                              'Handwerk B', 'Wasserschaden B', 'Kündigungsschreiben B',
                              'mieter-b@example.ch', '3.5 Zi B'):
                    self.assertNotIn(fremd, text)

    def test_ein_fremdes_dokument_ist_ueber_seinen_dateinamen_nicht_zu_finden(self):
        self.assertEqual(self._gruppe(self.a, 'kuendigung_seestrasse_b', 'dokumente'), [])
        self.assertEqual(len(self._gruppe(self.b, 'kuendigung_seestrasse_b', 'dokumente')), 1)

    def test_ein_fremdes_ticket_ist_ueber_seine_nummer_nicht_zu_finden(self):
        """Die Nummernsuche (`#882`) fragt über den Primärschlüssel — auch dort gilt der Filter."""
        nummer = f'#{self.b.schaden.id}'
        t = [x for x in self._gruppe(self.a, nummer, 'tickets')
             if x['url'] == f'/neu/schaeden/{self.b.schaden.id}/']
        self.assertEqual(t, [])
        self.assertEqual(
            [x['url'] for x in self._gruppe(self.b, nummer, 'tickets')],
            [f'/neu/schaeden/{self.b.schaden.id}/'])

    def test_ohne_anmeldung_kein_zugriff(self):
        antwort = Client().get('/neu/palette/', {'q': 'Mieter'})
        self.assertIn(antwort.status_code, (302, 403))

    def test_die_rolle_bleibt_team(self):
        """Lesezugriff darf, die Hauswartung nicht (`TEAM_ROLLEN`)."""
        from django.contrib.auth import get_user_model
        from crm.models import Mitgliedschaft
        for rolle, status in ((Mitgliedschaft.ROLLE_LESEZUGRIFF, 200),
                              (Mitgliedschaft.ROLLE_HAUSWART, 403)):
            with self.subTest(rolle=rolle):
                u = get_user_model().objects.create_user(username=f'rolle_{rolle}', password='x')
                Mitgliedschaft.objects.create(
                    benutzer=u, organisation=self.a.organisation, rolle=rolle)
                c = Client()
                c.force_login(u)
                self.assertEqual(c.get('/neu/palette/', {'q': 'Mieter'}).status_code, status)


class WortweiseTests(Basis):

    def test_personen_vorname_und_nachname_in_beiden_reihenfolgen(self):
        for q in ('Mieter A', 'A Mieter'):
            with self.subTest(q=q):
                self.assertEqual(len(self._gruppe(self.a, q, 'personen')), 1)

    def test_ticket_titel_und_beschreibung(self):
        """«Wasserschaden» steht im Titel, «Bad» in der Beschreibung ('Leck im Bad (A)')."""
        self.assertEqual(len(self._gruppe(self.a, 'Wasserschaden Bad', 'tickets')), 1)
        self.assertEqual(len(self._gruppe(self.a, 'Bad Wasserschaden', 'tickets')), 1)
        # Gegenprobe: Ein Wort, das nirgends steht, grenzt weiter ein statt mehr zu liefern.
        self.assertEqual(self._gruppe(self.a, 'Wasserschaden Heizung', 'tickets'), [])

    def test_ticket_titel_und_ort(self):
        self.assertEqual(len(self._gruppe(self.a, 'Wasserschaden A-Weg', 'tickets')), 1)

    def test_debitor_titel_und_mieter(self):
        self.assertEqual(len(self._gruppe(self.a, 'Miete Mieter', 'buchhaltung')), 1)
        self.assertEqual(self._gruppe(self.a, 'Miete Blaser', 'buchhaltung'), [])

    def test_dokument_titel_und_dateiname(self):
        """«Kündigungsschreiben» steht im Titel, «seestrasse» nur im Dateinamen."""
        self.assertEqual(len(self._gruppe(self.a, 'Kündigungsschreiben seestrasse', 'dokumente')), 1)
        self.assertEqual(self._gruppe(self.a, 'Kündigungsschreiben bahnhof', 'dokumente'), [])

    def test_dienstleister_firma_und_kontaktperson(self):
        from crm.models import Handwerker
        with self._kontext(self.a):
            Handwerker.objects.filter(pk=self.a.handwerker.pk).update(kontaktperson='Herr Rohrer')
        self.assertEqual(len(self._gruppe(self.a, 'Sanitaer Rohrer', 'personen')), 1)
        self.assertEqual(self._gruppe(self.a, 'Sanitaer Bachmann', 'personen'), [])

    def test_ticketnummer(self):
        for q in (f'#{self.a.schaden.id}', f'Wasser #{self.a.schaden.id}'):
            with self.subTest(q=q):
                self.assertEqual(len(self._gruppe(self.a, q, 'tickets')), 1)

    def test_eine_riesige_zahl_bricht_nichts(self):
        daten = self._antwort(self.a, '#99999999999999999999')
        self.assertEqual(daten['zahlen']['tickets'], 0)

    def test_platzhalterzeichen_sind_woertlich(self):
        for q in ('%%', '__', '%_%', 'a.b', '.*', '\\'):
            with self.subTest(q=q):
                self.assertEqual(self._antwort(self.a, q)['treffer'], [])


class KurzeEingabeTests(Basis):

    def test_weniger_als_zwei_zeichen_ergibt_nichts(self):
        for kurz in ('', 'M', ' ', '  M ', '#'):
            with self.subTest(q=repr(kurz)):
                daten = self._antwort(self.a, kurz)
                self.assertEqual(daten, {'treffer': [], 'q': kurz.strip()})

    def test_weniger_als_zwei_zeichen_fragt_die_fachtabellen_nicht(self):
        tabellen = [apps.get_model(a, n)._meta.db_table for a, n in (
            ('crm', 'Mieter'), ('crm', 'Handwerker'), ('portfolio', 'Liegenschaft'),
            ('portfolio', 'Einheit'), ('rentals', 'Mietvertrag'), ('rentals', 'Dokument'),
            ('finance', 'DebitorenRechnung'), ('finance', 'KreditorenRechnung'),
            ('tickets', 'SchadenMeldung'))]
        c = Client()
        c.force_login(self.a.benutzer)
        c.get('/neu/palette/', {'q': 'Mi'})                         # wärmt Sitzung und Rolle
        with CaptureQueriesContext(connection) as kurz:
            c.get('/neu/palette/', {'q': 'M'})
        with CaptureQueriesContext(connection) as lang:
            c.get('/neu/palette/', {'q': 'Mi'})
        for sql in (q['sql'] for q in kurz.captured_queries):
            for tabelle in tabellen:
                self.assertNotIn(f'"{tabelle}"', sql, 'Eine Eingabe unter zwei Zeichen fragt die Datenbank.')
        # Gegenprobe: Die lange Eingabe tut es.
        self.assertTrue(any(f'"{tabellen[0]}"' in q['sql'] for q in lang.captured_queries))

    def test_zwei_zeichen_reichen(self):
        self.assertTrue(self._antwort(self.a, 'Mi')['treffer'])


class AbfragezahlTests(Basis):
    """Je Gruppe zwei Abfragen (Treffer und Zahl), dazu die vier des Requests.

    Die Zahl ist fest: Sie hängt weder von der Trefferzahl noch von der Zahl
    der Wörter ab. Ein Test auf Gleichheit, nicht auf eine Obergrenze — eine
    Reserve machte ihn rot, ohne dass etwas kaputt wäre.
    """

    #: 4 Abfragen des Requests (Sitzung, Benutzer, Mitgliedschaft samt Organisation,
    #: Rollenprüfung) + 6 Gruppen × 2.
    ERWARTET = 16

    def _messen(self, c, q):
        with CaptureQueriesContext(connection) as ctx:
            antwort = c.get('/neu/palette/', {'q': q})
        self.assertEqual(antwort.status_code, 200)
        return len(ctx), json.loads(antwort.content)

    def test_feste_abfragezahl(self):
        from crm.models import Handwerker
        with self._kontext(self.a):
            for i in range(30):
                Handwerker.objects.create(firma=f'Vieltreffer {i:02d} AG')
        c = Client()
        c.force_login(self.a.benutzer)
        c.get('/neu/palette/', {'q': 'Mi'})                         # Wärmlauf
        for q in ('Vieltreffer',                  # 30 Treffer, begrenzt auf 5
                  'Weg 7',                        # Treffer in fünf Gruppen
                  'zzzqqq',                       # keine Treffer
                  'Mieter A Wasserschaden Bad',   # vier Wörter
                  'Kündigungsschreiben'):         # nur Dokumente
            with self.subTest(q=q):
                anzahl, _daten = self._messen(c, q)
                self.assertEqual(anzahl, self.ERWARTET)

    def test_assertNumQueries(self):
        c = Client()
        c.force_login(self.a.benutzer)
        c.get('/neu/palette/', {'q': 'Mi'})
        with self.assertNumQueries(self.ERWARTET):
            c.get('/neu/palette/', {'q': 'Mieter'})

    def test_die_messung_sieht_eine_zusaetzliche_abfrage(self):
        """Gegenprobe: ein Zähler, der nie anschlägt, beweist nichts. Hier wird
        eine Abfrage je Treffer erzwungen (der N+1, den die Aufgabe ausschliesst),
        und die Zählung muss davon abweichen."""
        c = Client()
        c.force_login(self.a.benutzer)
        c.get('/neu/palette/', {'q': 'Mi'})
        original = palette_suche._dar_mieter

        def mit_nachladen(z, pills):
            from crm.models import Mieter
            Mieter.objects.filter(pk=z.pk).first()        # N+1 absichtlich
            return original(z, pills)
        palette_suche._DARSTELLER['mieter'] = mit_nachladen
        try:
            anzahl, daten = self._messen(c, 'Mieter')
        finally:
            palette_suche._DARSTELLER['mieter'] = original
        self.assertTrue([t for t in daten['treffer'] if t['gruppe'] == 'personen'])
        self.assertEqual(anzahl, self.ERWARTET + 1)


class StatusTonTests(TestCase):
    """Jeder Status des Bestands hat ein Label und einen der vier Töne."""

    def test_jeder_status_hat_einen_ton(self):
        """Kommt ein Status dazu, den die Palette nicht kennt, würde er still
        als «mut» erscheinen. Dieser Test macht daraus eine Meldung."""
        from core.views.fw.kreditoren import KRED_PILL
        from core.views.fw.schaeden import TICKET_PILL
        from core.views.fw._basis import STATUS_PILL, VERTRAG_PILL
        from finance.models import DebitorenRechnung, KreditorenRechnung
        from portfolio.models import Liegenschaft
        from rentals.models import Mietvertrag
        from tickets.models import SchadenMeldung
        faelle = [
            (DebitorenRechnung, STATUS_PILL), (KreditorenRechnung, KRED_PILL),
            (SchadenMeldung, TICKET_PILL), (Mietvertrag, VERTRAG_PILL),
        ]
        for modell, pill in faelle:
            for code, _label in modell._meta.get_field('status').flatchoices:
                with self.subTest(modell=modell.__name__, status=code):
                    self.assertIn(code, pill, 'Kein Eintrag in der Statusfarbtabelle.')
                    status = palette_suche._status(modell, code, pill)
                    self.assertIn(status['ton'], palette_suche.TOENE)
                    self.assertTrue(status['text'])
        for code, _label in Liegenschaft._meta.get_field('status').flatchoices:
            with self.subTest(modell='Liegenschaft', status=code):
                self.assertIn(code, palette_suche._LIEGENSCHAFT_TON)

    def test_ton_aus_klasse(self):
        for klassen, ton in (('fw-krit-flaeche fw-kritisch', 'crit'),
                             ('fw-warn-flaeche fw-warnton', 'warn'),
                             ('fw-info-flaeche fw-info', 'warn'),
                             ('fw-markenflaeche fw-marke', 'warn'),
                             ('fw-gut-flaeche fw-gut', 'good'),
                             ('fw-flaeche2 fw-mutet', 'mut'),
                             ('etwas-anderes', 'mut')):
            self.assertEqual(palette_suche.ton_aus_klasse(klassen), ton, klassen)


class UebersetzungTests(Basis):
    """Statuslabels kommen aus den Modellen und sind übersetzbar."""

    def test_status_text_folgt_der_sprache(self):
        de = self._gruppe(self.a, 'Wasserschaden', 'tickets')[0]['status']['text']
        c = Client(headers={'Accept-Language': 'fr'})
        c.force_login(self.a.benutzer)
        fr = [t for t in json.loads(c.get('/neu/palette/', {'q': 'Wasserschaden'}).content)['treffer']
              if t['gruppe'] == 'tickets'][0]['status']['text']
        self.assertEqual(de, 'Neu')
        self.assertNotEqual(fr, de, 'Der Statustext ist nicht übersetzt.')

    def test_ueberfaellig_ist_uebersetzt(self):
        with self._kontext(self.a), translation.override('fr'):
            treffer, _zahlen = palette_suche.suche('Miete 02/2024')
        self.assertNotEqual(treffer[0]['status']['text'], 'Überfällig')
