"""Gesetzliche Quoren: Geschäftsart und Mehrheitsart sind Pflicht, zu schwache Mehrheiten werden abgewiesen, und die
Auszählung entscheidet danach rechtssicher — bis zur Sauna, die an einer einzigen Gegenstimme scheitert."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from core.tests._helfer import _team_user
from crm.models import Eigentuemer
from stweg import beschluss, quorum
from stweg.models import Anwesenheit, Traktandum, Versammlung
from stweg.versammlung import durchfuehren, einladung_pruefen, einladung_versenden
from stweg.tests import neue_stweg

D = Decimal
ALLE = [w for w, _ in Traktandum.MEHRHEIT_CHOICES if w != 'kenntnisnahme']

# Unabhängig vom Code: welche Mehrheitsart für welche Geschäftsart gültig ist (ohne «sonstiges» und «kenntnis»).
ERLAUBT = {
    'verwaltung': {'einfach_koepfe', 'einfach_quoten', 'doppelt', 'doppelt_anwesende', 'doppelt_aller', 'einstimmig'},
    'nuetzlich': {'doppelt_aller', 'einstimmig'},
    'reglement': {'doppelt_aller', 'einstimmig'},
    'luxurioes': {'einstimmig'},
}


class KatalogTests(TestCase):
    def test_die_drei_quoren_des_auftrags(self):
        self.assertEqual(quorum.mindestens('verwaltung'), 'einfach_koepfe')       # einfaches Mehr
        self.assertEqual(quorum.mindestens('nuetzlich'), 'doppelt_aller')         # Köpfe UND Wertquoten
        self.assertEqual(quorum.mindestens('luxurioes'), 'einstimmig')            # alle Köpfe

    def test_jede_kombination(self):
        for geschaeft, erlaubt in ERLAUBT.items():
            for art in ALLE:
                self.assertEqual(not quorum.probleme(geschaeft, art, ''), art in erlaubt, (geschaeft, art))

    def test_keine_stillen_vorgaben(self):
        for geschaeft, art in (('', 'einfach_koepfe'), ('verwaltung', ''), ('', ''), ('erfunden', 'einfach_koepfe'),
                               ('verwaltung', 'erfunden')):
            self.assertTrue(quorum.probleme(geschaeft, art), (geschaeft, art))

    def test_kenntnisnahme_nur_ohne_abstimmung(self):
        self.assertFalse(quorum.probleme('kenntnis', 'kenntnisnahme'))
        self.assertTrue(quorum.probleme('kenntnis', 'einfach_koepfe'))
        for geschaeft in ('verwaltung', 'nuetzlich', 'luxurioes', 'sonstiges'):
            self.assertTrue(quorum.probleme(geschaeft, 'kenntnisnahme', 'Reglement Art. 3'), geschaeft)

    def test_sonstiges_braucht_die_rechtsgrundlage(self):
        self.assertTrue(quorum.probleme('sonstiges', 'einfach_koepfe', ''))
        self.assertTrue(quorum.probleme('sonstiges', 'einfach_koepfe', '   '))
        self.assertFalse(quorum.probleme('sonstiges', 'einfach_koepfe', 'Reglement Art. 12 Abs. 2'))

    def test_die_meldung_nennt_gesetz_und_minimum(self):
        text = ' '.join(quorum.probleme('luxurioes', 'doppelt_aller'))
        self.assertIn('Art. 647e ZGB', text)
        self.assertIn('Einstimmigkeit', text)


class AnlegenTests(TestCase):
    def setUp(self):
        self.lg, self.e = neue_stweg(status='aktiv')
        self.v = Versammlung.objects.create(liegenschaft=self.lg, titel='V', datum=timezone.now() + timedelta(days=30))

    def test_anlegen_mit_gueltigen_angaben(self):
        t = quorum.traktandum_anlegen(self.v, 'Sauna', 'luxurioes', 'einstimmig', antrag='Einbau')
        self.assertEqual((t.nr, t.geschaeftsart, t.mehrheitsart), (1, 'luxurioes', 'einstimmig'))
        self.assertEqual(quorum.traktandum_anlegen(self.v, 'Dach', 'nuetzlich', 'doppelt_aller').nr, 2)

    def test_zu_schwach_oder_fehlend_wird_nicht_angelegt(self):
        for args in (('luxurioes', 'doppelt_aller'), ('nuetzlich', 'einfach_koepfe'), ('', 'einstimmig'),
                     ('verwaltung', '')):
            with self.assertRaises(quorum.QuorumFehler):
                quorum.traktandum_anlegen(self.v, 'X', *args)
        self.assertFalse(self.v.traktanden.exists())

    def test_oberflaeche(self):
        c = self.client_class()
        c.force_login(_team_user('Verwaltung'))
        url = f'/neu/stweg/versammlung/{self.v.pk}/traktandum/neu/'
        c.post(url, {'titel': 'Sauna', 'mehrheitsart': 'einfach_koepfe'})                     # keine Geschäftsart
        c.post(url, {'titel': 'Sauna', 'geschaeftsart': 'luxurioes', 'mehrheitsart': 'doppelt_aller'})   # zu schwach
        self.assertFalse(self.v.traktanden.exists())
        r = c.post(url, {'titel': 'Sauna', 'geschaeftsart': 'luxurioes', 'mehrheitsart': 'einstimmig'}, follow=True)
        self.assertEqual(self.v.traktanden.get().mehrheitsart, 'einstimmig')
        self.assertContains(r, 'Luxuriöse bauliche Massnahme')
        seite = c.get(f'/neu/stweg/versammlung/{self.v.pk}/')
        self.assertContains(seite, 'Art des Geschäfts')

    def test_zu_schwache_wahl_zeigt_die_gruende_in_der_oberflaeche(self):
        c = self.client_class()
        c.force_login(_team_user('Verwaltung'))
        r = c.post(f'/neu/stweg/versammlung/{self.v.pk}/traktandum/neu/',
                   {'titel': 'Sauna', 'geschaeftsart': 'luxurioes', 'mehrheitsart': 'einfach_koepfe'}, follow=True)
        self.assertContains(r, 'verlangt das Gesetz mindestens')


class AltbestandUndFeststellungTests(TestCase):
    def setUp(self):
        self.lg, self.e = neue_stweg(status='aktiv')
        for e, name in zip(self.e, ('Anna', 'Bruno', 'Carla')):
            e.stockwerkeigentuemer = Eigentuemer.objects.create(firma_oder_name=name, email=f'{name.lower()}@x.ch')
            e.save()
        self.v = Versammlung.objects.create(liegenschaft=self.lg, titel='V', datum=timezone.now() + timedelta(days=30))
        self.t = Traktandum.objects.create(versammlung=self.v, nr=1, titel='Alt')          # ohne Geschäftsart

    def test_altbestand_verhindert_die_einladung_bis_es_gesetzt_ist(self):
        self.assertTrue(any('Art des Geschäfts' in p for p in einladung_pruefen(self.v)), einladung_pruefen(self.v))
        quorum.geschaeftsart_setzen(self.t, 'verwaltung', 'einfach_koepfe')
        self.assertEqual(einladung_pruefen(self.v), [])

    def test_ohne_gueltiges_quorum_keine_feststellung_aber_vertagen_geht(self):
        quorum.geschaeftsart_setzen(self.t, 'verwaltung', 'einfach_koepfe')
        einladung_versenden(self.v)
        durchfuehren(self.v)
        for e in self.e:
            beschluss.anwesenheit_setzen(self.v, e, Anwesenheit.ANWESEND)
            beschluss.stimme_abgeben(self.t, e, 'ja')
        Traktandum.objects.filter(pk=self.t.pk).update(geschaeftsart='')            # etwa durch einen Altbestand
        self.t.refresh_from_db()
        with self.assertRaises(beschluss.BeschlussFehler):
            beschluss.feststellen(self.t, 'angenommen')
        beschluss.feststellen(self.t, 'vertagt')                                    # Vertagen braucht kein Quorum

    def test_nach_der_feststellung_nicht_mehr_aenderbar(self):
        quorum.geschaeftsart_setzen(self.t, 'verwaltung', 'einfach_koepfe')
        self.t.ergebnis = 'angenommen'
        with self.assertRaises(quorum.QuorumFehler):
            quorum.geschaeftsart_setzen(self.t, 'verwaltung', 'doppelt_aller')

    def test_nachtragen_ueber_die_oberflaeche(self):
        c = self.client_class()
        c.force_login(_team_user('Verwaltung'))
        c.post(f'/neu/stweg/traktandum/{self.t.pk}/geschaeftsart/', {'geschaeftsart': 'luxurioes',
                                                                      'mehrheitsart': 'doppelt_aller'})
        self.t.refresh_from_db()
        self.assertEqual(self.t.geschaeftsart, '')                                   # zu schwach: nichts gespeichert
        c.post(f'/neu/stweg/traktandum/{self.t.pk}/geschaeftsart/', {'geschaeftsart': 'nuetzlich',
                                                                      'mehrheitsart': 'doppelt_aller'})
        self.t.refresh_from_db()
        self.assertEqual((self.t.geschaeftsart, self.t.mehrheitsart), ('nuetzlich', 'doppelt_aller'))
        self.assertContains(c.get(f'/neu/stweg/versammlung/{self.v.pk}/'), 'Nützliche bauliche Massnahme')


def einheit(pk, quote, kopf):
    return SimpleNamespace(pk=pk, wertquote=D(quote), stockwerkeigentuemer_id=kopf)


class ZaehlenJeQuorumTests(TestCase):
    """Zehn Eigentümer à 100 Quoten; `zaehlen` entscheidet nach der gewählten Mehrheitsart."""

    def setUp(self):
        self.einh = [einheit(i, 100, i) for i in range(1, 11)]

    def vorschlag(self, art, ja, nein=0, abwesend=0):
        stimmen = {}
        for i in range(1, 11 - abwesend):
            stimmen[i] = 'ja' if i <= ja else 'nein'
        return beschluss.zaehlen(self.einh, stimmen, art, 1000, anwesende_koepfe=10 - abwesend)['vorschlag']

    def test_einfaches_mehr_zaehlt_die_anwesenden(self):
        vier = {1: 'ja', 2: 'ja', 3: 'ja', 4: 'nein'}                                        # nur 4 von 10 anwesend
        self.assertEqual(beschluss.zaehlen(self.einh, vier, 'einfach_koepfe', 1000)['vorschlag'], 'angenommen')
        gleich = {1: 'ja', 2: 'ja', 3: 'nein', 4: 'nein'}
        self.assertEqual(beschluss.zaehlen(self.einh, gleich, 'einfach_koepfe', 1000)['vorschlag'], 'abgelehnt')
        enthaltungen = {1: 'ja', 2: 'ja', 3: 'nein', 4: 'enthaltung', 5: 'enthaltung', 6: 'enthaltung'}
        self.assertEqual(beschluss.zaehlen(self.einh, enthaltungen, 'einfach_koepfe', 1000)['vorschlag'], 'angenommen')

    def test_qualifiziertes_mehr_verlangt_die_mehrheit_aller_koepfe(self):
        self.assertEqual(self.vorschlag('doppelt_aller', ja=6), 'angenommen')
        self.assertEqual(self.vorschlag('doppelt_aller', ja=5), 'abgelehnt')                 # genau die Hälfte reicht nicht
        stimmen = {i: 'ja' for i in range(1, 5)}                                              # 4 ja, 6 nicht anwesend
        self.assertEqual(beschluss.zaehlen(self.einh, stimmen, 'doppelt_aller', 1000)['vorschlag'], 'abgelehnt')

    def test_qualifiziertes_mehr_verlangt_auch_die_haelfte_der_wertquoten(self):
        einh = [einheit(1, 400, 1)] + [einheit(i, 100, i) for i in range(2, 8)]            # 6 × 100 + 400 = 1000
        ja_klein = {i: 'ja' for i in range(2, 7)} | {1: 'nein', 7: 'nein'}                  # 5 Köpfe ja (> 3.5), Quote 500
        self.assertEqual(beschluss.zaehlen(einh, ja_klein, 'doppelt_aller', 1000)['vorschlag'], 'abgelehnt')   # = 50 %
        ja_gross = {1: 'ja', 2: 'ja', 3: 'ja', 4: 'ja', 5: 'nein', 6: 'nein', 7: 'nein'}    # 4 Köpfe (> 3.5), Quote 700
        self.assertEqual(beschluss.zaehlen(einh, ja_gross, 'doppelt_aller', 1000)['vorschlag'], 'angenommen')
        nur_koepfe = {2: 'ja', 3: 'ja', 4: 'ja', 5: 'ja', 1: 'nein', 6: 'nein', 7: 'nein'}  # 4 Köpfe, Quote nur 400
        self.assertEqual(beschluss.zaehlen(einh, nur_koepfe, 'doppelt_aller', 1000)['vorschlag'], 'abgelehnt')

    def test_einstimmigkeit_verlangt_alle_koepfe(self):
        self.assertEqual(self.vorschlag('einstimmig', ja=10), 'angenommen')
        self.assertEqual(self.vorschlag('einstimmig', ja=9), 'abgelehnt')
        stimmen = {i: 'ja' for i in range(1, 10)}                                             # einer fehlt ganz
        self.assertEqual(beschluss.zaehlen(self.einh, stimmen, 'einstimmig', 1000)['vorschlag'], 'abgelehnt')


class SaunaSimulation(TestCase):
    def test_9_von_10_ist_bei_einer_luxurioesen_massnahme_abgelehnt(self):
        """Sauna: 9 von 10 Eigentümern (90 % der Köpfe, 950/1000 Quoten) stimmen zu — ohne Einstimmigkeit ist der
        Beschluss abgelehnt; als nützliche Massnahme wäre er mit demselben Ergebnis angenommen."""
        quoten = (105,) * 8 + (110, 50)
        lg, einheiten = neue_stweg(quoten=quoten, status='aktiv')
        for i, e in enumerate(einheiten):
            e.stockwerkeigentuemer = Eigentuemer.objects.create(firma_oder_name=f'Eigentümer {i + 1}',
                                                                email=f'e{i + 1}@x.ch')
            e.save()
        v = Versammlung.objects.create(liegenschaft=lg, titel='Sauna', datum=timezone.now() + timedelta(days=30),
                                       ort='Saal')
        sauna = quorum.traktandum_anlegen(v, 'Einbau einer Sauna', 'luxurioes', 'einstimmig', antrag='Einbau Sauna')
        dach = quorum.traktandum_anlegen(v, 'Dachfenster', 'nuetzlich', 'doppelt_aller', antrag='Dachfenster')
        einladung_versenden(v)
        self.assertEqual(len(mail.outbox), 10)
        durchfuehren(v)
        for e in einheiten:
            beschluss.anwesenheit_setzen(v, e, Anwesenheit.ANWESEND)
        for t in (sauna, dach):
            for e in einheiten[:9]:
                beschluss.stimme_abgeben(t, e, 'ja')
            beschluss.stimme_abgeben(t, einheiten[9], 'nein')                 # der Eigentümer mit Quote 50

        z = beschluss.auswerten(sauna)
        self.assertEqual((z['ja_koepfe'], z['nein_koepfe'], z['total_koepfe']), (9, 1, 10))
        self.assertEqual((z['ja_quoten'], z['total_quoten']), (D('950'), D('1000')))
        self.assertEqual(z['vorschlag'], 'abgelehnt')                          # keine Einstimmigkeit
        self.assertEqual(beschluss.auswerten(dach)['vorschlag'], 'angenommen')  # 90 % der Köpfe, 950/1000 Quoten

        with self.assertRaises(beschluss.BeschlussFehler) as ctx:              # ein «angenommen» wäre ein Rechtsfehler
            beschluss.feststellen(sauna, 'angenommen')
        self.assertIn('Quorum', str(ctx.exception))
        sauna.refresh_from_db()
        self.assertEqual(sauna.ergebnis, 'offen')
        beschluss.feststellen(sauna, beschluss.NACH_ZAEHLUNG)                   # das System stellt «abgelehnt» fest
        sauna.refresh_from_db()
        self.assertEqual((sauna.ergebnis, sauna.ja_koepfe, sauna.nein_koepfe), ('abgelehnt', 9, 1))
        beschluss.feststellen(dach, beschluss.NACH_ZAEHLUNG)
        dach.refresh_from_db()
        self.assertEqual(dach.ergebnis, 'angenommen')


class FeststellenNachZaehlungTests(TestCase):
    def test_sonstiges_darf_vom_vorschlag_abweichen_gesetzliche_arten_nicht(self):
        lg, einheiten = neue_stweg(status='aktiv')
        for e, name in zip(einheiten, ('Anna', 'Bruno', 'Carla')):
            e.stockwerkeigentuemer = Eigentuemer.objects.create(firma_oder_name=name, email=f'{name.lower()}@x.ch')
            e.save()
        v = Versammlung.objects.create(liegenschaft=lg, titel='V', datum=timezone.now() + timedelta(days=30))
        frei = quorum.traktandum_anlegen(v, 'Frei', 'sonstiges', 'einfach_koepfe', rechtsgrundlage='Reglement Art. 9')
        fest = quorum.traktandum_anlegen(v, 'Fest', 'verwaltung', 'einfach_koepfe')
        einladung_versenden(v)
        durchfuehren(v)
        for e in einheiten:
            beschluss.anwesenheit_setzen(v, e, Anwesenheit.ANWESEND)
        for t in (frei, fest):
            beschluss.stimme_abgeben(t, einheiten[0], 'ja')
            beschluss.stimme_abgeben(t, einheiten[1], 'nein')
            beschluss.stimme_abgeben(t, einheiten[2], 'nein')
        beschluss.feststellen(frei, 'angenommen')                                # Leitung weicht ab (Rechtsgrundlage genannt)
        with self.assertRaises(beschluss.BeschlussFehler):
            beschluss.feststellen(fest, 'angenommen')
        beschluss.feststellen(fest, 'abgelehnt')
