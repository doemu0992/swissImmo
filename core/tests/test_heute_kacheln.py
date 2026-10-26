"""Die reduzierte Startseite (Dashboard-Reduktion, 26.10.2026).

Geprüft wird, was die Seite verspricht:

- Höchstens vier Aufgabenkacheln, nur mit Zahl > 0, die dringendste zuerst
  und im Ember-Akzent; ein ruhiger Tag zeigt keine Kachel.
- Der Schwerpunkt folgt ohne Wahl der Rolle (Inhaber → Übersicht, Verwalter →
  Bewirtschaftung), lässt sich je Mitgliedschaft speichern, und ein
  unbekannter Wert wird abgelehnt.
- Buchhaltung: überfällige Rechnungen und Klärungsfälle mit Betrag.
- «Hängt» zeigt wartende und liegengebliebene Fälle, jeden einmal.
- Was weggefallen ist, bleibt weg; die Kopfsuche ist auch auf «Heute» da.
- Eine fremde Verwaltung zählt nicht mit.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture


def _kachel(antwort, schluessel):
    return next((k for k in antwort.context['kacheln'] if k['schluessel'] == schluessel), None)


def _zahl(antwort, schluessel):
    k = _kachel(antwort, schluessel)
    return k['zahl'] if k else 0


class _Basis(TestCase):
    """Die Mandanten-Fixture bringt schon Daten mit (Tickets, Rechnungen,
    Eingänge) — gezählt wird deshalb gegen den Stand vor dem Test."""
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.heute = timezone.localdate()
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def schwerpunkt(self, wert):
        with mandant(self.a.organisation):
            return self.c.post('/neu/schwerpunkt/', {'schwerpunkt': wert})

    def seite(self, pfad='/neu/'):
        with mandant(self.a.organisation):
            return self.c.get(pfad)

    def ticket(self, fixture, **felder):
        from tickets.models import SchadenMeldung
        with mandant(fixture.organisation):
            return SchadenMeldung.objects.create(liegenschaft=fixture.liegenschaft, titel='Heizung kalt',
                                                 beschreibung='x', **felder)


class SchwerpunktTests(_Basis):
    def test_ohne_wahl_folgt_er_der_rolle(self):
        from crm.models import Mitgliedschaft
        self.assertEqual(self.seite().context['schwerpunkt'], 'uebersicht', 'Inhaber → Übersicht')
        with mandant(self.a.organisation):
            Mitgliedschaft.objects.filter(benutzer=self.a.benutzer).update(rolle='Verwalter')
        self.assertEqual(self.seite().context['schwerpunkt'], 'bewirtschaftung', 'Verwalter → Bewirtschaftung')

    def test_wahl_wird_je_mitgliedschaft_gespeichert(self):
        from crm.models import Mitgliedschaft
        antwort = self.schwerpunkt('buchhaltung')
        self.assertEqual(antwort.status_code, 302)
        with mandant(self.a.organisation):
            m = Mitgliedschaft.objects.get(benutzer=self.a.benutzer)
        self.assertEqual(m.schwerpunkt, 'buchhaltung')
        self.assertEqual(self.seite().context['schwerpunkt'], 'buchhaltung')
        # Ein erfundener Wert ändert nichts.
        self.schwerpunkt('chef')
        self.assertEqual(self.seite().context['schwerpunkt'], 'buchhaltung')


class BewirtschaftungTests(_Basis):
    def setUp(self):
        super().setUp()
        self.schwerpunkt('bewirtschaftung')

    def test_ruhiger_tag_zeigt_keine_kachel(self):
        # Eigene, leere Verwaltung: Hier ist wirklich nichts zu tun.
        from crm.models import Organisation
        from faelle.heute_kacheln import kacheln
        leer = Organisation.objects.create(firma='Leer AG', strasse='Leerweg 1', plz='8000', ort='Zürich')
        with mandant(leer):
            for schwerpunkt in ('bewirtschaftung', 'buchhaltung', 'uebersicht'):
                with self.subTest(schwerpunkt=schwerpunkt):
                    self.assertEqual(kacheln(schwerpunkt, self.heute, None, {}, []), [])

    def test_dringlichkeit_bestimmt_die_reihenfolge(self):
        """Eine Freigabe, die über fünf Tage liegt, steht vor dem Posteingang,
        obwohl sie später gesammelt wird — höchstens vier Kacheln."""
        from crm.models import Organisation
        from faelle.heute_kacheln import kacheln
        leer = Organisation.objects.create(firma='Leer AG', strasse='Leerweg 1', plz='8000', ort='Zürich')
        av = {'av_eingaenge_gesamt': 2, 'av_freigaben_gesamt': 1, 'av_liegezeit': 9}
        with mandant(leer):
            liste = kacheln('bewirtschaftung', self.heute, None, av, [])
        self.assertEqual([k['schluessel'] for k in liste], ['freigaben', 'posteingang'])

    def test_ueberfaellige_frist_steht_zuerst_und_im_akzent(self):
        from core.models import Pendenz
        self.ticket(self.a)
        with mandant(self.a.organisation):
            Pendenz.objects.create(titel='Rückruf Mieter', kategorie='aufgabe', vertrag=self.a.vertrag,
                                   faellig_am=self.heute - timedelta(days=3))
        antwort = self.seite()
        kacheln = antwort.context['kacheln']
        self.assertLessEqual(len(kacheln), 4)
        self.assertEqual((kacheln[0]['schluessel'], kacheln[0]['ton']), ('vorgaenge', 'crit'))
        self.assertGreaterEqual(kacheln[0]['zahl'], 1)
        self.assertIsNotNone(_kachel(antwort, 'tickets'))
        html = antwort.content.decode()
        self.assertIn('class="fw-kachel akzent" data-kachel="vorgaenge"', html)
        self.assertIn('href="/neu/schaeden/?zustaendig=niemand"', html)
        self.assertIn('davon überfällig', html)

    def test_nur_offene_nicht_zugewiesene_tickets_zaehlen(self):
        vorher = _zahl(self.seite(), 'tickets')
        self.ticket(self.a, zugewiesen_an=self.a.benutzer)
        self.ticket(self.a, status='erledigt')
        self.assertEqual(_zahl(self.seite(), 'tickets'), vorher)
        self.ticket(self.a)
        self.assertEqual(_zahl(self.seite(), 'tickets'), vorher + 1)

    def test_fremde_verwaltung_zaehlt_nicht(self):
        vorher = _zahl(self.seite(), 'tickets')
        self.ticket(self.b)
        self.assertEqual(_zahl(self.seite(), 'tickets'), vorher)

    def test_haengt_zeigt_wartende_und_liegengebliebene_je_einmal(self):
        from faelle.models import Fall, Fallart
        with mandant(self.a.organisation):
            art = Fallart.objects.create(organisation=self.a.organisation, schluessel='test-h',
                                         bezeichnung='Test')
            wartet = Fall(organisation=self.a.organisation, fallart=art, betreff='Offerte Maler',
                          status=Fall.WARTET)
            wartet.save()
            liegt = Fall(organisation=self.a.organisation, fallart=art, betreff='Mängelrüge')
            liegt.save()
            beides = Fall(organisation=self.a.organisation, fallart=art, betreff='Versicherung',
                          status=Fall.WARTET)
            beides.save()
            alt = timezone.now() - timedelta(days=30)
            Fall.objects.filter(pk__in=[liegt.pk, beides.pk]).update(letzte_bewegung=alt)
        antwort = self.seite('/neu/?ansicht=haengt')
        self.assertEqual(sorted(f.betreff for f in antwort.context['faelle']),
                         ['Mängelrüge', 'Offerte Maler', 'Versicherung'])
        self.assertEqual(dict((k, n) for k, _b, _a, n in antwort.context['ansichten'])['haengt'], 3)


class BuchhaltungTests(_Basis):
    def setUp(self):
        super().setUp()
        self.schwerpunkt('buchhaltung')

    def rechnung(self, tage, status='offen', betrag='1000'):
        from finance.models import DebitorenRechnung
        f = self.heute + timedelta(days=tage)
        with mandant(self.a.organisation):
            return DebitorenRechnung.objects.create(vertrag=self.a.vertrag, titel='Miete', betrag=Decimal(betrag),
                                                    status=status, faellig_am=f, datum=f)

    def test_rueckstand_zaehlt_nur_ueberfaellige_offene_und_teilbezahlte(self):
        from faelle.heute_kacheln import rueckstand
        with mandant(self.a.organisation):
            vorher = rueckstand(self.heute)
        self.rechnung(-12, betrag='1200')
        self.rechnung(-3, 'teilbezahlt', '300')
        self.rechnung(+10, betrag='500')
        self.rechnung(-40, 'bezahlt', '900')
        self.rechnung(-60, 'storniert', '999')
        with mandant(self.a.organisation):
            r = rueckstand(self.heute)
        self.assertEqual((r['n'] - vorher['n'], r['summe'] - vorher['summe']), (2, Decimal('1500')))
        antwort = self.seite()
        k = antwort.context['kacheln'][0]
        self.assertEqual((k['schluessel'], k['zahl'], k['betrag']), ('rueckstand', r['n'], r['summe']))
        self.assertContains(antwort, 'data-kachel="rueckstand"')

    def test_alter_klaerungsfall_ist_dringend(self):
        from finance.booking import konto
        from finance.models import Zahlungseingang
        with mandant(self.a.organisation):
            Zahlungseingang.objects.filter(konto__nummer='1190').update(status='storniert')
            Zahlungseingang.objects.create(betrag=Decimal('100'), datum_eingang=self.heute - timedelta(days=14),
                                           konto=konto('1190'), status='verbucht', bemerkung='camt UNGEKLÄRT')
        k = _kachel(self.seite(), 'klaerung')
        self.assertEqual((k['zahl'], k['ton'], k['betrag']), (1, 'crit', Decimal('100')))
        self.assertIn('länger als 10 Tage', k['text'])


class WasWegfielTests(_Basis):
    def test_keine_ember_reihe_keine_eigene_suche_kein_ausserdem(self):
        html = self.seite().content.decode()
        for weg in ('fw-ember', 'Zahlungsquote', 'Objekte nach Ort', 'Mieteingang', 'Terminplan',
                    'fw-ausserdem', 'fw-top-heute', 'Sollstellung '):
            with self.subTest(weg=weg):
                self.assertNotIn(weg, html)
        # Die Kopfsuche ist auf «Heute» nicht mehr ausgeblendet.
        self.assertIn('name="q"', html)

    def test_uebersicht_zeigt_den_kennzahlenstreifen(self):
        antwort = self.seite()
        self.assertContains(antwort, 'class="fw-lage"')
        self.assertEqual(antwort.context['kacheln'], [])
