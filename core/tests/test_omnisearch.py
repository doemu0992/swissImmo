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

NACHTRAG (27.10.2026): Verträge tragen den aktuellen Netto-Mietzins, Objekte
ihren Belegungsstand, Debitoren die Mahnstufe, und die Hauswartung sucht
eingeschränkt (nur Schäden, nur eigene Liegenschaften). Dazu die Gegenproben
je Rolle: Wer was findet, steht in `RollenTests`.
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
        # Das Objekt ist vermietet (aktiver Vertrag ohne Ende, Fixture).
        self.assertEqual(t['Objekt']['status'], {'text': 'Vermietet', 'ton': 'good'})
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
        # Der AKTUELLE Netto-Mietzins: Das Fixture hat eine gebuchte Anpassung auf
        # 1550 (ab 01.04.2025); der Vertragswert (1500) und der Brutto (1750) sind es nicht.
        self.assertEqual(t[0]['betrag'], "CHF 1'550.00")

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
        # Die Fälligkeit (28.02.2024) liegt in der Vergangenheit, Status «offen»,
        # und das Fixture führt dazu eine offene Betreibung (Stand «Begehren»).
        self.assertEqual(t[0]['status'], {'text': 'Betreibung', 'ton': 'crit'})
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

    def test_ohne_team_oder_hauswart_rolle_403(self):
        """Lesezugriff darf (alle Gruppen); wer keine der beiden Rollen hat, nicht.
        Die Hauswartung steht in `RollenTests`."""
        from django.contrib.auth import get_user_model
        from crm.models import Mitgliedschaft
        u = get_user_model().objects.create_user(username='rolle_lesend', password='x')
        Mitgliedschaft.objects.create(
            benutzer=u, organisation=self.a.organisation,
            rolle=Mitgliedschaft.ROLLE_LESEZUGRIFF)
        c = Client()
        c.force_login(u)
        self.assertEqual(c.get('/neu/palette/', {'q': 'Mieter'}).status_code, 200)
        ohne = get_user_model().objects.create_user(username='rolle_keine', password='x')
        c.force_login(ohne)
        self.assertEqual(c.get('/neu/palette/', {'q': 'Mieter'}).status_code, 403)


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
    """Je Gruppe zwei Abfragen (Treffer und Zahl), dazu die des Requests, dazu
    je ein fester Stapel für Verträge und Objekte, wenn es solche Treffer gibt.

    Die Zahl ist fest: Sie hängt weder von der Trefferzahl noch von der Zahl
    der Wörter ab. Ein Test auf Gleichheit, nicht auf eine Obergrenze — eine
    Reserve machte ihn rot, ohne dass etwas kaputt wäre.
    """

    #: 4 Abfragen des Requests (Sitzung, Benutzer, Mitgliedschaft samt Organisation,
    #: Rollenprüfung) + 1 Rollenlesung im Dienst (`sicht_von`: Er prüft die Rolle
    #: selbst, nicht nur der Dekorator) + 6 Gruppen × 2.
    GRUNDZAHL = 17
    #: Vertrag samt Objekt + Anpassungen, Staffelstufen, Komponenten und
    #: Objekt-Sollmietzinse (`_nachladen_vertraege`): nur mit Vertragstreffern.
    STAPEL_VERTRAEGE = 5
    #: Objekte + Verträge der Objekte + Verträge mit Nebenobjekten (`_nachladen_objekte`):
    #: nur mit Objekttreffern. (Gibt es zu den Treffern einen Vertrag mit Nebenobjekten,
    #: kommt deren Vorladung hinzu: eine weitere Abfrage, wieder unabhängig von der Anzahl.)
    STAPEL_OBJEKTE = 3

    def _erwartet(self, treffer):
        arten = {t['art'] for t in treffer}
        return (self.GRUNDZAHL
                + (self.STAPEL_VERTRAEGE if 'Mietverhältnis' in arten else 0)
                + (self.STAPEL_OBJEKTE if 'Objekt' in arten else 0))

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
        gesehen = set()
        for q in ('Vieltreffer',                  # 30 Treffer, begrenzt auf 5
                  'Weg 7',                        # Treffer in fünf Gruppen, mit Vertrag und Objekt
                  'zzzqqq',                       # keine Treffer
                  'Mieter A Wasserschaden Bad',   # vier Wörter
                  'Kündigungsschreiben'):         # nur Dokumente
            with self.subTest(q=q):
                anzahl, daten = self._messen(c, q)
                gesehen |= {t['art'] for t in daten['treffer']}
                self.assertEqual(anzahl, self._erwartet(daten['treffer']))
        # Die Fälle haben beide Stapel wirklich ausgelöst — sonst prüfte die
        # Schleife nur die Grundzahl.
        self.assertTrue({'Mietverhältnis', 'Objekt'} <= gesehen, gesehen)

    def test_assertNumQueries(self):
        c = Client()
        c.force_login(self.a.benutzer)
        c.get('/neu/palette/', {'q': 'Mi'})
        # «Mieter» trifft einen Vertrag, kein Objekt.
        with self.assertNumQueries(self.GRUNDZAHL + self.STAPEL_VERTRAEGE):
            c.get('/neu/palette/', {'q': 'Mieter'})
        # «Sanitaer» trifft nur einen Dienstleister: Grundzahl.
        with self.assertNumQueries(self.GRUNDZAHL):
            c.get('/neu/palette/', {'q': 'Sanitaer'})

    def test_die_zahl_haengt_nicht_von_der_trefferzahl_der_stapel_ab(self):
        """Ein Vertrag oder fünf: dieselbe Zahl. Der Stapel ist das Gegenmittel
        zu vier Abfragen JE Vertrag, und diese Zahl ist sein Beleg."""
        from crm.models import Mieter
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        c = Client()
        c.force_login(self.a.benutzer)
        c.get('/neu/palette/', {'q': 'Mi'})
        ein, daten_ein = self._messen(c, 'Reihe')       # noch kein Treffer
        self.assertEqual(daten_ein['treffer'], [])
        with self._kontext(self.a):
            for n in range(5):
                e = Einheit.objects.create(liegenschaft=self.a.liegenschaft, bezeichnung=f'Reihe {n}',
                                           typ='whg', nettomiete_aktuell=Decimal('1000'))
                m = Mieter.objects.create(typ='person', vorname='Reihe', nachname=f'Mieter{n}')
                Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                           netto_mietzins=Decimal('1000') + n,
                                           nebenkosten=Decimal('100'), status='aktiv')
        anzahl_fuenf, daten = self._messen(c, 'Reihe')
        vertraege = [t for t in daten['treffer'] if t['gruppe'] == 'vertraege']
        objekte = [t for t in daten['treffer'] if t['art'] == 'Objekt']
        self.assertEqual((len(vertraege), len(objekte)), (5, 5))
        # Mit einem einzigen Treffer je Modell
        with self._kontext(self.a):
            Mietvertrag.objects.filter(mieter__vorname='Reihe').exclude(
                mieter__nachname='Mieter0').delete()
            Einheit.objects.filter(bezeichnung__startswith='Reihe').exclude(
                bezeichnung='Reihe 0').delete()
        anzahl_eins, daten_eins = self._messen(c, 'Reihe')
        self.assertEqual(len([t for t in daten_eins['treffer'] if t['gruppe'] == 'vertraege']), 1)
        self.assertEqual(anzahl_fuenf, anzahl_eins)
        self.assertEqual(anzahl_eins, self._erwartet(daten_eins['treffer']))

    def test_die_messung_sieht_eine_abfrage_je_vertrag(self):
        """Gegenprobe: Würde der Betrag je Vertrag einzeln gerechnet (ohne Stapel),
        wüchse die Zahl mit der Trefferzahl — und dieser Aufbau müsste es zeigen."""
        from crm.models import Mieter
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        with self._kontext(self.a):
            for n in range(5):
                e = Einheit.objects.create(liegenschaft=self.a.liegenschaft, bezeichnung=f'Reihe {n}',
                                           typ='whg', nettomiete_aktuell=Decimal('1000'))
                m = Mieter.objects.create(typ='person', vorname='Reihe', nachname=f'Mieter{n}')
                Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                           netto_mietzins=Decimal('1000'),
                                           nebenkosten=Decimal('100'), status='aktiv')
        c = Client()
        c.force_login(self.a.benutzer)
        c.get('/neu/palette/', {'q': 'Mi'})
        stapel, _daten = self._messen(c, 'Reihe')
        original = palette_suche._NACHLADEN['vertrag']

        def einzeln(zeilen, heute):
            from rentals.models import Mietvertrag as MV
            for z in zeilen:
                v = MV.objects.select_related('einheit').get(pk=z.pk)       # keine Stapel
                z.betrag = v.effektiver_netto_mietzins(heute)
        palette_suche._NACHLADEN['vertrag'] = einzeln
        try:
            einzeln_anzahl, _daten = self._messen(c, 'Reihe')
        finally:
            palette_suche._NACHLADEN['vertrag'] = original
        self.assertGreater(einzeln_anzahl, stapel + 5)

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
        self.assertEqual(anzahl, self.GRUNDZAHL + self.STAPEL_VERTRAEGE + 1)

    def test_mahnstufe_und_betreibung_kosten_keine_abfrage(self):
        """Sie stehen als Unterabfragen in der Zeile der Rechnung. Fünf Rechnungen
        mit Mahnung und Betreibung kosten dieselbe Zahl wie fünf ohne."""
        from finance.models import Betreibung, DebitorenRechnung, Mahnung
        c = Client()
        c.force_login(self.a.benutzer)
        c.get('/neu/palette/', {'q': 'Mi'})
        with self._kontext(self.a):
            rechnungen = [DebitorenRechnung.objects.create(
                vertrag=self.a.vertrag, titel=f'Stapelprobe {n}', betrag=Decimal('100'),
                datum=date(2024, 3, 1), faellig_am=date(2024, 3, 31), status='offen')
                for n in range(5)]
        ohne, daten_ohne = self._messen(c, 'Stapelprobe')
        self.assertEqual({t['status']['text'] for t in daten_ohne['treffer']}, {'Überfällig'})
        with self._kontext(self.a):
            for r in rechnungen:
                Mahnung.objects.create(debitoren_rechnung=r, vertrag=self.a.vertrag, stufe=2,
                                       datum=date(2024, 5, 1), betrag_offen=Decimal('100'))
            Betreibung.objects.create(debitoren_rechnung=rechnungen[0], vertrag=self.a.vertrag,
                                      forderung=Decimal('100'), begehren_am=date(2024, 6, 1))
        mit, daten_mit = self._messen(c, 'Stapelprobe')
        self.assertEqual({t['status']['text'] for t in daten_mit['treffer']},
                         {'2. Mahnung', 'Betreibung'})
        self.assertEqual(ohne, mit)


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
        from finance.models import DebitorenRechnung
        with self._kontext(self.a):
            DebitorenRechnung.objects.create(
                vertrag=self.a.vertrag, titel='Nur überfällig', betrag=Decimal('100'),
                datum=date(2024, 3, 1), faellig_am=date(2024, 3, 31), status='offen')
            with translation.override('fr'):
                treffer, _zahlen = palette_suche.suche('Nur überfällig', self.a.benutzer)
        self.assertNotEqual(treffer[0]['status']['text'], 'Überfällig')

    def test_mahnstufe_und_betreibung_sind_uebersetzt(self):
        """Beides sind neue Texte der Omnisearch; ungeprüft bliebe einer deutsch."""
        from finance.models import DebitorenRechnung, Mahnung
        with self._kontext(self.a):
            r = DebitorenRechnung.objects.create(
                vertrag=self.a.vertrag, titel='Gemahnt', betrag=Decimal('100'),
                datum=date(2024, 3, 1), faellig_am=date(2024, 3, 31), status='offen')
            Mahnung.objects.create(debitoren_rechnung=r, vertrag=self.a.vertrag, stufe=2,
                                   datum=date(2024, 5, 1), betrag_offen=Decimal('100'))
            for sprache in ('fr', 'it', 'en'):
                with self.subTest(sprache=sprache), translation.override(sprache):
                    stufe, _ = palette_suche.suche('Gemahnt', self.a.benutzer)
                    betreibung, _ = palette_suche.suche('Miete 02/2024', self.a.benutzer)
                    self.assertIn('2', stufe[0]['status']['text'])
                    self.assertNotEqual(stufe[0]['status']['text'], '2. Mahnung')
                    self.assertNotEqual(betreibung[0]['status']['text'], 'Betreibung')

    def test_objektstatus_und_vertragsbetrag_sind_uebersetzt(self):
        with self._kontext(self.a):
            for sprache in ('fr', 'it', 'en'):
                with self.subTest(sprache=sprache), translation.override(sprache):
                    treffer, _ = palette_suche.suche('3.5 Zi A', self.a.benutzer)
                    objekt = [t for t in treffer if t['url'].startswith('/neu/objekte/')]
                    self.assertEqual(len(objekt), 1, treffer)
                    self.assertNotEqual(objekt[0]['status']['text'], 'Vermietet')


# ---------------------------------------------------------------------------
# Nachtrag 27.10.2026
# ---------------------------------------------------------------------------

def _vertrag_mit_objekt(m, bezeichnung, **vertrag):
    """Ein Objekt mit eigenem Vertrag im Bestand von `m` (Hauptmieter: der des Fixtures)."""
    from portfolio.models import Einheit
    from rentals.models import Mietvertrag
    felder = dict(beginn=date(2024, 1, 1), netto_mietzins=Decimal('1000'),
                  nebenkosten=Decimal('100'), status='aktiv')
    felder.update(vertrag)
    with organisation_kontext(m.organisation):
        e = Einheit.objects.create(liegenschaft=m.liegenschaft, bezeichnung=bezeichnung,
                                   typ='whg', nettomiete_aktuell=Decimal('1000'))
        v = Mietvertrag.objects.create(mieter=m.mieter, einheit=e, **felder)
    return e, v


class VertragBetragTests(Basis):
    """Der Betrag eines Vertrags ist der AKTUELL GELTENDE Netto-Mietzins.

    Die Regel steht im Modell (`Mietvertrag.effektiver_netto_mietzins`); hier
    wird geprüft, dass die Suche ihr folgt und keine zweite erfindet: Anpassung,
    Komponente, Staffel, Ende des Vertrags. Der Betrag ohne Nebenkosten.

    Das Fixture führt für seinen Vertrag eine gebuchte Anpassung auf 1550
    (ab 01.04.2025) — der Vertragswert 1500 ist also gerade NICHT der aktuelle.
    Wo ein Test den Vertragswert braucht, legt er einen eigenen Vertrag an.
    """

    def _betrag(self, q, m=None):
        t = self._gruppe(m or self.a, q, 'vertraege')
        self.assertEqual(len(t), 1, t)
        return t[0]['betrag']

    def test_der_vertragswert_ohne_nebenkosten_ohne_anpassung(self):
        _vertrag_mit_objekt(self.a, 'Wertprobe', netto_mietzins=Decimal('1234.50'),
                            nebenkosten=Decimal('99'))
        self.assertEqual(self._betrag('Wertprobe'), "CHF 1'234.50")

    def test_die_gebuchte_anpassung_geht_dem_vertragswert_vor(self):
        """Das Fixture: Vertragswert 1500, Anpassung auf 1550 — gezeigt wird 1550."""
        from rentals.models import Mietvertrag
        with self._kontext(self.a):
            self.assertEqual(Mietvertrag.objects.get(pk=self.a.vertrag.pk).netto_mietzins,
                             Decimal('1500.00'))
        self.assertEqual(self._betrag('Mieter A'), "CHF 1'550.00")

    def test_die_juengste_wirksame_anpassung_gilt(self):
        from rentals.models import MietzinsAnpassung
        with self._kontext(self.a):
            MietzinsAnpassung.objects.create(
                vertrag=self.a.vertrag, wirksam_ab=date(2025, 6, 1),
                neuer_netto_mietzins=Decimal('1620.50'))
        self.assertEqual(self._betrag('Mieter A'), "CHF 1'620.50")

    def test_eine_kuenftige_oder_entworfene_anpassung_zaehlt_nicht(self):
        from rentals.models import MietzinsAnpassung
        with self._kontext(self.a):
            MietzinsAnpassung.objects.create(
                vertrag=self.a.vertrag, wirksam_ab=date.today() + timedelta(days=30),
                neuer_netto_mietzins=Decimal('1999.00'))
            MietzinsAnpassung.objects.create(
                vertrag=self.a.vertrag, wirksam_ab=date(2025, 8, 1),
                neuer_netto_mietzins=Decimal('1888.00'), status=MietzinsAnpassung.STATUS_ENTWURF)
        self.assertEqual(self._betrag('Mieter A'), "CHF 1'550.00")

    def test_staffelstufe_gilt_ab_ihrem_datum(self):
        from rentals.models import Staffelstufe
        _e, v = _vertrag_mit_objekt(self.a, 'Staffelprobe', mietzins_modell='staffel')
        with self._kontext(self.a):
            Staffelstufe.objects.create(vertrag=v, ab_datum=date(2025, 1, 1),
                                        netto_mietzins=Decimal('1800'))
            Staffelstufe.objects.create(vertrag=v, ab_datum=date.today() + timedelta(days=60),
                                        netto_mietzins=Decimal('2100'))
        self.assertEqual(self._betrag('Staffelprobe'), "CHF 1'800.00")

    def test_gratismonat_aendert_die_auskunft_nicht(self):
        """Der Rabatt mindert die Verrechnung, nicht den Mietzins: Der Betrag bleibt der Referenzwert."""
        from rentals.models import VertragMietzins
        _e, v = _vertrag_mit_objekt(self.a, 'Gratisprobe')
        with self._kontext(self.a):
            VertragMietzins.objects.create(
                vertrag=v, gueltig_ab=date(2024, 1, 1),
                netto_mietzins=Decimal('1700'), rabatt_netto=Decimal('1700'))
        self.assertEqual(self._betrag('Gratisprobe'), "CHF 1'700.00")

    def test_ein_beendeter_vertrag_nennt_den_mietzins_an_seinem_ende(self):
        """Eine Anpassung NACH dem Ende (etwa des Nachmieters) darf ihm keinen Betrag setzen."""
        from rentals.models import MietzinsAnpassung
        _e, v = _vertrag_mit_objekt(self.a, 'Endeprobe', status='archiviert',
                                    ende=date(2025, 6, 30))
        with self._kontext(self.a):
            MietzinsAnpassung.objects.create(
                vertrag=v, wirksam_ab=date(2025, 3, 1), neuer_netto_mietzins=Decimal('1100'))
            MietzinsAnpassung.objects.create(
                vertrag=v, wirksam_ab=date(2025, 7, 15), neuer_netto_mietzins=Decimal('1999'))
        t = self._gruppe(self.a, 'Endeprobe', 'vertraege')[0]
        self.assertEqual(t['betrag'], "CHF 1'100.00")
        self.assertEqual(t['status']['text'], 'Beendet')

    def test_der_betrag_gehoert_dem_eigenen_mandanten(self):
        from rentals.models import MietzinsAnpassung
        with self._kontext(self.b):
            MietzinsAnpassung.objects.filter(vertrag=self.b.vertrag).update(
                neuer_netto_mietzins=Decimal('1777'))
        self.assertEqual(self._betrag('Mieter A', self.a), "CHF 1'550.00")
        self.assertEqual(self._betrag('Mieter B', self.b), "CHF 1'777.00")

    def test_betrag_tragen_nur_vertraege_und_rechnungen(self):
        daten = self._antwort(self.a, 'Mieter')
        mit = {t['gruppe'] for t in daten['treffer'] if t['betrag']}
        self.assertEqual(mit, {'vertraege', 'buchhaltung'})


class ObjektStatusTests(Basis):
    """Der Status eines Objekts ist sein Belegungsstand — nach der Regel der
    Objektliste (`faelle.objekte`), nicht nach einer eigenen."""

    def _status(self, q, m=None):
        m = m or self.a
        t = [x for x in self._gruppe(m, q, 'immobilien') if x['art'] == 'Objekt']
        self.assertEqual(len(t), 1, t)
        return t[0]['status']

    def test_vermietet(self):
        self.assertEqual(self._status('3.5 Zi A'), {'text': 'Vermietet', 'ton': 'good'})

    def test_gekuendigt_ohne_nachmieter_wird_frei(self):
        from rentals.models import Mietvertrag
        with self._kontext(self.a):
            Mietvertrag.objects.filter(pk=self.a.vertrag.pk).update(
                status='gekuendigt', ende=date.today() + timedelta(days=60))
        self.assertEqual(self._status('3.5 Zi A'), {'text': 'Wird frei', 'ton': 'warn'})

    def test_ein_fernes_ende_ist_noch_vermietet(self):
        from rentals.models import Mietvertrag
        with self._kontext(self.a):
            Mietvertrag.objects.filter(pk=self.a.vertrag.pk).update(
                status='gekuendigt', ende=date.today() + timedelta(days=400))
        self.assertEqual(self._status('3.5 Zi A'), {'text': 'Vermietet', 'ton': 'good'})

    def test_abgelaufener_vertrag_heisst_leer(self):
        from rentals.models import Mietvertrag
        with self._kontext(self.a):
            Mietvertrag.objects.filter(pk=self.a.vertrag.pk).update(
                status='archiviert', ende=date.today() - timedelta(days=20))
        self.assertEqual(self._status('3.5 Zi A'), {'text': 'Leer', 'ton': 'warn'})

    def test_ein_objekt_ohne_jeden_vertrag_ist_leer(self):
        from portfolio.models import Einheit
        with self._kontext(self.a):
            Einheit.objects.create(liegenschaft=self.a.liegenschaft, bezeichnung='Leerprobe',
                                   typ='whg', nettomiete_aktuell=Decimal('900'))
        self.assertEqual(self._status('Leerprobe'), {'text': 'Leer', 'ton': 'warn'})

    def test_nachmieter_ab_datum(self):
        """Heute leer, aber der Vertrag beginnt bald: kein Leerstand, an dem jemand arbeiten muss."""
        ab = date.today() + timedelta(days=30)
        _vertrag_mit_objekt(self.a, 'Nachmieterprobe', beginn=ab)
        self.assertEqual(self._status('Nachmieterprobe'),
                         {'text': f'Vermietet ab {ab:%d.%m.%Y}', 'ton': 'good'})

    def test_nebenobjekt_gilt_mit_dem_hauptvertrag_als_vermietet(self):
        from portfolio.models import Einheit
        with self._kontext(self.a):
            pp = Einheit.objects.create(liegenschaft=self.a.liegenschaft,
                                        bezeichnung='Parkplatzprobe', typ='pp',
                                        nettomiete_aktuell=Decimal('120'))
            self.a.vertrag.nebenobjekte.add(pp)
        self.assertEqual(self._status('Parkplatzprobe'), {'text': 'Vermietet', 'ton': 'good'})

    def test_der_stand_folgt_der_objektliste(self):
        """Die Suche und die Objektliste urteilen über dieselben Objekte gleich:
        'leer' hier heisst 'nicht versorgt' dort."""
        from faelle.objekte import zeilen
        from portfolio.models import Einheit
        ab = date.today() + timedelta(days=20)
        _vertrag_mit_objekt(self.a, 'Folgeprobe 1', beginn=ab)
        _vertrag_mit_objekt(self.a, 'Folgeprobe 2', status='archiviert',
                            ende=date.today() - timedelta(days=5))
        _vertrag_mit_objekt(self.a, 'Folgeprobe 3', status='gekuendigt',
                            ende=date.today() + timedelta(days=45))
        with self._kontext(self.a):
            Einheit.objects.create(liegenschaft=self.a.liegenschaft, bezeichnung='Folgeprobe 4',
                                   typ='whg', nettomiete_aktuell=Decimal('900'))
            liste = {z['e'].bezeichnung: z for z in zeilen(
                Einheit.objects.filter(bezeichnung__startswith='Folgeprobe'))}
        self.assertEqual(len(liste), 4)
        texte = {}
        for bezeichnung, z in liste.items():
            status = self._status(bezeichnung)
            texte[bezeichnung] = status['text']
            with self.subTest(objekt=bezeichnung, status=status['text']):
                self.assertEqual(status['text'] == 'Leer', not z['versorgt'])
                self.assertEqual(status['text'] == 'Wird frei',
                                 any(b['text'] == 'Wird frei' for b in z['befunde']))
        self.assertEqual(texte, {'Folgeprobe 1': f'Vermietet ab {ab:%d.%m.%Y}',
                                 'Folgeprobe 2': 'Leer', 'Folgeprobe 3': 'Wird frei',
                                 'Folgeprobe 4': 'Leer'})

    def test_die_belegung_gehoert_dem_eigenen_mandanten(self):
        from rentals.models import Mietvertrag
        with self._kontext(self.b):
            Mietvertrag.objects.filter(pk=self.b.vertrag.pk).update(
                status='archiviert', ende=date.today() - timedelta(days=20))
        self.assertEqual(self._status('Zi A', self.a)['text'], 'Vermietet')
        self.assertEqual(self._status('Zi B', self.b)['text'], 'Leer')

    def test_liegenschaften_bleiben_bei_ihrem_status(self):
        t = [x for x in self._gruppe(self.a, 'A-Weg', 'immobilien') if x['art'] == 'Liegenschaft']
        self.assertEqual(t[0]['status'], {'text': 'Entwurf', 'ton': 'mut'})


class MahnstufeTests(Basis):
    """«Überfällig» wird zur Mahnstufe oder zur Betreibung, wo es sie gibt."""

    def _rechnung(self, m, titel, **felder):
        from finance.models import DebitorenRechnung
        werte = dict(vertrag=m.vertrag, titel=titel, betrag=Decimal('100'),
                     datum=date(2024, 3, 1), faellig_am=date(2024, 3, 31), status='offen')
        werte.update(felder)
        with organisation_kontext(m.organisation):
            return DebitorenRechnung.objects.create(**werte)

    def _mahnung(self, m, rechnung, stufe):
        from finance.models import Mahnung
        with organisation_kontext(m.organisation):
            return Mahnung.objects.create(
                debitoren_rechnung=rechnung, vertrag=m.vertrag, stufe=stufe,
                datum=date(2024, 4, stufe), betrag_offen=Decimal('100'))

    def _betreibung(self, m, rechnung, status='begehren', weitere=()):
        from finance.models import Betreibung
        with organisation_kontext(m.organisation):
            b = Betreibung.objects.create(
                debitoren_rechnung=rechnung, vertrag=m.vertrag, forderung=Decimal('100'),
                begehren_am=date(2024, 6, 1), status=status)
            b.weitere_rechnungen.set(weitere)
            return b

    def _status(self, titel, m=None):
        t = self._gruppe(m or self.a, titel, 'buchhaltung')
        self.assertEqual(len(t), 1, t)
        return t[0]['status']

    def test_ohne_mahnung_bleibt_es_ueberfaellig(self):
        self._rechnung(self.a, 'Ohnemahnung')
        self.assertEqual(self._status('Ohnemahnung'), {'text': 'Überfällig', 'ton': 'crit'})

    def test_die_hoechste_erfasste_mahnung_gilt(self):
        r = self._rechnung(self.a, 'Gemahnt')
        for stufe, text in ((1, '1. Mahnung'), (2, '2. Mahnung'), (3, '3. Mahnung')):
            self._mahnung(self.a, r, stufe)
            with self.subTest(stufe=stufe):
                self.assertEqual(self._status('Gemahnt'), {'text': text, 'ton': 'crit'})

    def test_eine_offene_betreibung_geht_der_mahnung_vor(self):
        r = self._rechnung(self.a, 'Betrieben')
        self._mahnung(self.a, r, 3)
        self._betreibung(self.a, r)
        self.assertEqual(self._status('Betrieben'), {'text': 'Betreibung', 'ton': 'crit'})

    def test_eine_abgeschlossene_betreibung_zaehlt_nicht(self):
        from finance.models import Betreibung
        for i, stand in enumerate(Betreibung.ABGESCHLOSSEN):
            with self.subTest(stand=stand):
                titel = f'Abgeschlossen{i}x'
                r = self._rechnung(self.a, titel)
                self._mahnung(self.a, r, 2)
                self._betreibung(self.a, r, status=stand)
                self.assertEqual(self._status(titel), {'text': '2. Mahnung', 'ton': 'crit'})

    def test_jeder_offene_stand_der_betreibung_zaehlt(self):
        from finance.models import Betreibung
        offen = [c for c, _l in Betreibung.STATUS_CHOICES if c not in Betreibung.ABGESCHLOSSEN]
        self.assertGreaterEqual(len(offen), 5)
        for i, stand in enumerate(offen):
            with self.subTest(stand=stand):
                titel = f'Offenstand{i}x'
                r = self._rechnung(self.a, titel)
                self._betreibung(self.a, r, status=stand)
                self.assertEqual(self._status(titel)['text'], 'Betreibung')

    def test_weitere_rechnung_einer_betreibung_zaehlt_mit(self):
        haupt = self._rechnung(self.a, 'Hauptforderung')
        weitere = self._rechnung(self.a, 'Weiterforderung')
        self._rechnung(self.a, 'Andereforderung')
        self._betreibung(self.a, haupt, weitere=[weitere])
        self.assertEqual(self._status('Hauptforderung')['text'], 'Betreibung')
        self.assertEqual(self._status('Weiterforderung')['text'], 'Betreibung')
        self.assertEqual(self._status('Andereforderung')['text'], 'Überfällig')

    def test_nur_offene_und_ueberfaellige_rechnungen_werden_verfeinert(self):
        morgen = date.today() + timedelta(days=10)
        faelle = [
            # (Status, fällig, soll)
            ('bezahlt', date(2024, 3, 31), 'Bezahlt'),
            ('storniert', date(2024, 3, 31), 'Storniert'),
            ('offen', morgen, 'Offen'),
            ('teilbezahlt', date(2024, 3, 31), '2. Mahnung'),
        ]
        for i, (status, faellig, soll) in enumerate(faelle):
            titel = f'Verfeinerprobe{i}x'
            r = self._rechnung(self.a, titel, status=status, faellig_am=faellig)
            self._mahnung(self.a, r, 2)
            if status == 'storniert':
                self._betreibung(self.a, r)
            with self.subTest(status=status, faellig=faellig):
                self.assertEqual(self._status(titel)['text'], soll)

    def test_jeder_mandant_sieht_den_stand_seiner_rechnung(self):
        self._rechnung(self.a, 'Gleichtitel')
        rb = self._rechnung(self.b, 'Gleichtitel')
        self._mahnung(self.b, rb, 3)
        self.assertEqual(self._status('Gleichtitel', self.a)['text'], 'Überfällig')
        self.assertEqual(self._status('Gleichtitel', self.b)['text'], '3. Mahnung')

    def test_betreibung_und_mahnung_eines_anderen_mandanten_faerben_nichts(self):
        """Die Unterabfragen laufen über `objects`.

        Die Unterabfrage hängt an der Primärschlüsselnummer der Rechnung, ein fremder
        Datensatz käme also nur über eine Verknüpfung über die Grenze hinein: eine
        Betreibung und eine Mahnung, die Mandant B führt und die auf die Rechnung von
        A zeigen (so ein Datensatz entsteht nur durch einen Fehler anderswo — genau
        dann soll die Suche von A ihn nicht auswerten).
        """
        from finance.models import Betreibung, Mahnung
        ra = self._rechnung(self.a, 'Fremdgeführt')
        rb = self._rechnung(self.b, 'Fremdgeführt')
        with organisation_kontext(self.b.organisation):
            betreibung = Betreibung.objects.create(
                debitoren_rechnung=rb, vertrag=self.b.vertrag, forderung=Decimal('100'),
                begehren_am=date(2024, 6, 1))
            betreibung.weitere_rechnungen.add(ra)
            mahnung = Mahnung.objects.create(
                debitoren_rechnung=rb, vertrag=self.b.vertrag, stufe=3,
                datum=date(2024, 4, 3), betrag_offen=Decimal('100'))
        # Die Mahnung wird (wie durch einen Fehler anderswo) auf A's Rechnung umgebogen,
        # bleibt aber im Bestand von B.
        Mahnung.alle_organisationen.filter(pk=mahnung.pk).update(debitoren_rechnung=ra)
        self.assertEqual(Mahnung.alle_organisationen.get(pk=mahnung.pk).organisation_id,
                         self.b.organisation.pk)
        self.assertEqual(self._status('Fremdgeführt', self.a), {'text': 'Überfällig', 'ton': 'crit'})
        # Gegenprobe: Im Bestand von B zählt dieselbe Betreibung.
        self.assertEqual(self._status('Fremdgeführt', self.b)['text'], 'Betreibung')
        self.assertTrue(Betreibung.alle_organisationen.filter(weitere_rechnungen=ra).exists())


class RollenTests(Basis):
    """Gegenprobe je Rolle: Wer findet was — und was nie.

    Das Team sucht in allen sechs Gruppen. Die Hauswartung nur in den Schäden
    ihrer Liegenschaften. Alle anderen bekommen 403.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from django.contrib.auth import get_user_model
        from crm.models import Mitgliedschaft
        from portfolio.models import Liegenschaft
        from tickets.models import SchadenMeldung
        User = get_user_model()
        cls.benutzer = {}
        for rolle in (Mitgliedschaft.ROLLE_INHABER, Mitgliedschaft.ROLLE_VERWALTER,
                      Mitgliedschaft.ROLLE_SACHBEARBEITER, Mitgliedschaft.ROLLE_LESEZUGRIFF,
                      Mitgliedschaft.ROLLE_HAUSWART):
            u = User.objects.create_user(username=f'rt_{rolle}', password='x')
            Mitgliedschaft.objects.create(benutzer=u, organisation=cls.a.organisation, rolle=rolle)
            cls.benutzer[rolle] = u
        cls.hauswart = cls.benutzer[Mitgliedschaft.ROLLE_HAUSWART]
        # Ein zweiter Hauswart ohne zugeordnete Liegenschaft
        cls.hauswart_leer = User.objects.create_user(username='rt_hauswart_leer', password='x')
        Mitgliedschaft.objects.create(benutzer=cls.hauswart_leer, organisation=cls.a.organisation,
                                      rolle=Mitgliedschaft.ROLLE_HAUSWART)
        # Portal-Konten und ein Konto ohne jede Rolle
        cls.keine = User.objects.create_user(username='rt_keine', password='x')
        cls.mieter_portal = User.objects.create_user(username='rt_mieter', password='x')
        cls.eigentuemer_portal = User.objects.create_user(username='rt_eigentuemer', password='x')
        with organisation_kontext(cls.a.organisation):
            type(cls.a.mieter).objects.filter(pk=cls.a.mieter.pk).update(benutzer=cls.mieter_portal)
            type(cls.a.eigentuemer).objects.filter(pk=cls.a.eigentuemer.pk).update(
                benutzer=cls.eigentuemer_portal)
            # Eine zweite Liegenschaft in A, dem Hauswart NICHT zugeordnet, mit eigenem Schaden
            cls.lg_neben = Liegenschaft.objects.create(
                strasse='A-Nebenweg 9', plz='8000', ort='Zürich', eigentuemer=cls.a.eigentuemer,
                organisation=cls.a.organisation, versicherungswert=Decimal('500000'))
            cls.schaden_neben = SchadenMeldung.objects.create(
                liegenschaft=cls.lg_neben, titel='Wasserschaden Nebenhaus', beschreibung='tropft')
            cls.a.liegenschaft.hauswarte.add(cls.hauswart)
        # Der Hauswart ist (fälschlich) auch einer Liegenschaft von B zugeordnet:
        # Der Mandantenfilter, nicht die Zuordnung, hält B draussen.
        cls.b.liegenschaft.hauswarte.add(cls.hauswart)

    def _von(self, benutzer, q):
        c = Client()
        c.force_login(benutzer)
        antwort = c.get('/neu/palette/', {'q': q})
        return antwort.status_code, (json.loads(antwort.content) if antwort.status_code == 200 else None)

    # ---- Team: alle sechs Gruppen ----------------------------------------
    def test_jede_team_rolle_durchsucht_alle_sechs_gruppen(self):
        from crm.models import Mitgliedschaft
        for rolle in (Mitgliedschaft.ROLLE_INHABER, Mitgliedschaft.ROLLE_VERWALTER,
                      Mitgliedschaft.ROLLE_SACHBEARBEITER, Mitgliedschaft.ROLLE_LESEZUGRIFF):
            with self.subTest(rolle=rolle):
                status, daten = self._von(self.benutzer[rolle], 'Mieter')
                self.assertEqual(status, 200)
                self.assertEqual(list(daten['zahlen']), GRUPPEN)
                self.assertTrue({'personen', 'vertraege', 'buchhaltung'}
                                <= {t['gruppe'] for t in daten['treffer']})

    def test_superuser_durchsucht_alle_gruppen(self):
        from django.contrib.auth import get_user_model
        from crm.models import Mitgliedschaft
        u = get_user_model().objects.create_superuser(username='rt_super', password='x')
        Mitgliedschaft.objects.create(benutzer=u, organisation=self.a.organisation,
                                      rolle=Mitgliedschaft.ROLLE_LESEZUGRIFF)
        status, daten = self._von(u, 'Mieter')
        self.assertEqual((status, list(daten['zahlen'])), (200, GRUPPEN))

    # ---- Hauswartung: nur Schäden der eigenen Liegenschaften ---------------
    def test_hauswart_findet_nur_schaeden_seiner_liegenschaften(self):
        status, daten = self._von(self.hauswart, 'Wasserschaden')
        self.assertEqual(status, 200)
        self.assertEqual(daten['zahlen'], {'tickets': 1})
        self.assertEqual([t['url'] for t in daten['treffer']],
                         [f'/neu/schaeden/{self.a.schaden.id}/'])
        self.assertEqual({t['gruppe'] for t in daten['treffer']}, {'tickets'})
        # Gegenprobe: Das Team findet beide Schäden von A, den Schaden der
        # Nebenliegenschaft gibt es also wirklich.
        _s, team = self._von(self.benutzer['Verwalter'], 'Wasserschaden')
        self.assertEqual({t['url'] for t in team['treffer']},
                         {f'/neu/schaeden/{self.a.schaden.id}/',
                          f'/neu/schaeden/{self.schaden_neben.id}/'})

    def test_hauswart_findet_keine_personen_vertraege_buchhaltung_dokumente_objekte(self):
        for q in ('Mieter', 'Sanitaer', 'Miete 02/2024', 'Handwerk', 'Kündigungsschreiben',
                  '3.5 Zi', 'A-Weg', 'mieter-a@example.ch'):
            with self.subTest(q=q):
                status, daten = self._von(self.hauswart, q)
                self.assertEqual(status, 200)
                self.assertEqual(list(daten['zahlen']), ['tickets'])
                self.assertLessEqual({t['gruppe'] for t in daten['treffer']}, {'tickets'})
                text = json.dumps(daten, ensure_ascii=False)
                for tabu in ('CHF', 'Mietverhältnis', 'Debitorenrechnung', 'Kreditorenrechnung',
                             'Dienstleister', '/neu/personen/', '/neu/vertraege/',
                             '/neu/liegenschaften/', '/neu/objekte/', '/neu/dokument',
                             '/neu/debitoren/', '/neu/kreditoren/'):
                    self.assertNotIn(tabu, text)
        # Gegenprobe: Das Team findet dieselben Begriffe in diesen Gruppen.
        for q, gruppe in (('Mieter', 'personen'), ('Sanitaer', 'personen'),
                          ('Miete 02/2024', 'buchhaltung'), ('Kündigungsschreiben', 'dokumente'),
                          ('A-Weg', 'immobilien'), ('Mieter', 'vertraege')):
            with self.subTest(team=q, gruppe=gruppe):
                _s, team = self._von(self.benutzer['Verwalter'], q)
                self.assertGreater(team['zahlen'][gruppe], 0)

    def test_hauswart_ohne_zugeordnete_liegenschaft_findet_nichts(self):
        status, daten = self._von(self.hauswart_leer, 'Wasserschaden')
        self.assertEqual((status, daten['treffer'], daten['zahlen']), (200, [], {'tickets': 0}))

    def test_hauswart_findet_den_schaden_auch_ueber_seine_nummer(self):
        _s, daten = self._von(self.hauswart, f'#{self.a.schaden.id}')
        self.assertEqual([t['url'] for t in daten['treffer']],
                         [f'/neu/schaeden/{self.a.schaden.id}/'])
        _s, daten = self._von(self.hauswart, f'#{self.schaden_neben.id}')
        self.assertEqual(daten['treffer'], [])
        _s, daten = self._von(self.hauswart, f'#{self.b.schaden.id}')
        self.assertEqual(daten['treffer'], [])

    def test_hauswart_sieht_nie_den_mandanten_b_auch_bei_zuordnung(self):
        """Die Zuordnung zu einer Liegenschaft von B ändert nichts: Der Mandantenfilter greift zuerst."""
        self.assertTrue(self.b.liegenschaft.hauswarte.filter(pk=self.hauswart.pk).exists())
        _status, daten = self._von(self.hauswart, 'Wasserschaden')
        text = json.dumps(daten, ensure_ascii=False)
        self.assertNotIn('Wasserschaden B', text)
        self.assertNotIn('B-Weg', text)
        self.assertNotIn(f'/neu/schaeden/{self.b.schaden.id}/', text)
        _s, nummer = self._von(self.hauswart, f'#{self.b.schaden.id}')
        self.assertEqual(nummer['treffer'], [])
        # Gegenprobe: Im Bestand von B gibt es den Schaden, und B's Team findet ihn.
        _s, b = self._von(self.b.benutzer, 'Wasserschaden B')
        self.assertEqual(len(b['treffer']), 1)

    def test_hauswart_liest_die_tabellen_der_anderen_gruppen_nicht(self):
        """Nicht nur ausgeblendet: Für die gesperrten Gruppen läuft gar keine Abfrage."""
        tabellen = [apps.get_model(a, n)._meta.db_table for a, n in (
            ('crm', 'Handwerker'), ('rentals', 'Mietvertrag'), ('rentals', 'Dokument'),
            ('finance', 'DebitorenRechnung'), ('finance', 'KreditorenRechnung'))]
        c = Client()
        c.force_login(self.hauswart)
        c.get('/neu/palette/', {'q': 'Mi'})
        with CaptureQueriesContext(connection) as hauswart:
            c.get('/neu/palette/', {'q': 'Weg 7'})
        for q in hauswart.captured_queries:
            for tabelle in tabellen:
                self.assertNotIn(f'"{tabelle}"', q['sql'])
        # Gegenprobe: Dieselbe Eingabe beim Team liest diese Tabellen.
        t = Client()
        t.force_login(self.benutzer['Verwalter'])
        t.get('/neu/palette/', {'q': 'Mi'})
        with CaptureQueriesContext(connection) as team:
            t.get('/neu/palette/', {'q': 'Weg 7'})
        sql = ' '.join(q['sql'] for q in team.captured_queries)
        self.assertTrue(all(f'"{tabelle}"' in sql for tabelle in tabellen))

    def test_hauswart_hat_eine_feste_abfragezahl(self):
        """4 des Requests + 1 Rollenlesung im Dienst + 2 für die eine Gruppe."""
        c = Client()
        c.force_login(self.hauswart)
        c.get('/neu/palette/', {'q': 'Mi'})
        for q in ('Wasserschaden', 'zzzqqq', 'Wasserschaden Bad Heizung'):
            with self.subTest(q=q), self.assertNumQueries(7):
                c.get('/neu/palette/', {'q': q})

    # ---- alle anderen: 403 ---------------------------------------------------
    def test_ohne_rolle_und_portalkonten_403(self):
        for name, u in (('ohne Rolle', self.keine), ('Mieter-Portal', self.mieter_portal),
                        ('Eigentümer-Portal', self.eigentuemer_portal)):
            with self.subTest(konto=name):
                status, _daten = self._von(u, 'Wasserschaden')
                self.assertEqual(status, 403)
                # auch ohne Suchbegriff: die Rolle entscheidet, nicht die Eingabe
                c = Client()
                c.force_login(u)
                self.assertEqual(c.get('/neu/palette/').status_code, 403)

    def test_anonym_wird_zur_anmeldung_geleitet(self):
        antwort = Client().get('/neu/palette/', {'q': 'Wasserschaden'})
        self.assertEqual(antwort.status_code, 302)
        self.assertIn('/login/', antwort['Location'])

    def test_hauswart_mit_kurzer_eingabe_bekommt_die_leere_antwort(self):
        status, daten = self._von(self.hauswart, 'W')
        self.assertEqual((status, daten), (200, {'treffer': [], 'q': 'W'}))

    # ---- der Dienst selbst ---------------------------------------------------
    def test_der_dienst_prueft_die_rolle_selbst(self):
        """Nicht nur der Dekorator der Ansicht: Wer `suche` ohne Rolle aufruft, bekommt `PermissionDenied`."""
        from django.core.exceptions import PermissionDenied
        for u in (self.keine, self.mieter_portal, self.eigentuemer_portal):
            with self.subTest(konto=u.username), self._kontext(self.a):
                with self.assertRaises(PermissionDenied):
                    palette_suche.suche('Wasserschaden', u)

    def test_sicht_je_rolle(self):
        with self._kontext(self.a):
            self.assertEqual(palette_suche.sicht_von(self.benutzer['Lesezugriff']).gruppen,
                             tuple(GRUPPEN))
            hauswart = palette_suche.sicht_von(self.hauswart)
            self.assertEqual((hauswart.gruppen, hauswart.nur_hauswart, hauswart.suchseite),
                             (('tickets',), True, '/neu/schaeden/'))
            team = palette_suche.sicht_von(self.benutzer['Verwalter'])
            self.assertEqual((team.nur_hauswart, team.suchseite), (False, '/neu/suche/'))
            # Beide Rollen: das Team gewinnt (wie `ist_nur_hauswart`).
            beide = palette_suche.sicht_von(self.hauswart, rollen={'Hauswart', 'Verwalter'})
            self.assertEqual((beide.gruppen, beide.nur_hauswart), (tuple(GRUPPEN), False))

    def test_hauswart_gruppen_sind_offen(self):
        """Die Hauswartung sucht nur, was sie öffnen darf — und die übrigen Gruppen sind gesperrt.

        Dieser Test hält die Liste `HAUSWART_GRUPPEN` an den Rechten der Ansichten fest:
        Jeder Treffer einer erlaubten Gruppe öffnet sich für die Hauswartung, jeder Treffer
        einer nicht erlaubten führt in ein 403. Öffnet jemand eine weitere Ansicht für sie,
        wird der zweite Teil rot — das ist der Hinweis, die Gruppe aufzunehmen.
        """
        erlaubt = set(palette_suche.HAUSWART_GRUPPEN)
        self.assertEqual(erlaubt, {'tickets'})
        c = Client()
        c.force_login(self.hauswart)
        beispiele = {
            'personen': ('Mieter A', 'Sanitaer A'), 'immobilien': ('A-Weg',),
            'vertraege': ('Mieter A',), 'buchhaltung': ('Miete 02/2024 A', 'Handwerk A'),
            'tickets': ('#{}'.format(self.a.schaden.id),), 'dokumente': ('Kündigungsschreiben A',),
        }
        gesehen = set()
        for gruppe, begriffe in beispiele.items():
            for q in begriffe:
                _s, daten = self._von(self.benutzer['Verwalter'], q)
                for t in (x for x in daten['treffer'] if x['gruppe'] == gruppe):
                    gesehen.add(gruppe)
                    with self.subTest(gruppe=gruppe, url=t['url']):
                        antwort = c.get(t['url'])
                        self.assertEqual(antwort.status_code, 200 if gruppe in erlaubt else 403)
        self.assertEqual(gesehen, set(GRUPPEN), 'Eine Gruppe lieferte keinen Beispieltreffer.')
