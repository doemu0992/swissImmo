"""Doppeltes Mehr und E-Voting."""
import itertools
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from django.test import TestCase
from django.utils import timezone

from crm.models import Eigentuemer
from portfolio.models import Einheit
from stweg import evoting
from stweg.beschluss import BeschlussFehler, auswerten, feststellen, zaehlen
from stweg.models import Anwesenheit, Stimme, StimmeEreignis, Traktandum, Versammlung
from stweg.test_budget import haus_mit_eigentuemern


class _E:
    """Eine Einheit für die reine Rechnung (kein Datenbankzugriff)."""

    def __init__(self, pk, quote, eigentuemer):
        self.pk, self.wertquote, self.stockwerkeigentuemer_id = pk, Decimal(quote), eigentuemer


def orakel(art, einheiten, zustand, total_quoten):
    """Unabhängige Zweitrechnung mit Brüchen — bewusst anders gebaut als `zaehlen`.

    `zustand`: je Einheit 'abwesend' | 'ja' | 'nein' | 'enth' | 'da' (anwesend, keine Stimme)."""
    kopf = {}
    for e, z in zip(einheiten, zustand):
        if z == 'abwesend':
            continue
        kopf.setdefault(e.stockwerkeigentuemer_id, []).append((e, z))
    # Widerspruch (Ja und Nein desselben Eigentümers) ist kein gültiger Fall.
    if any({z for _, z in v} >= {'ja', 'nein'} for v in kopf.values()):
        return None
    ja_k = sum(1 for v in kopf.values() if any(z == 'ja' for _, z in v))
    nein_k = sum(1 for v in kopf.values() if any(z == 'nein' for _, z in v))
    ja_q = sum(Fraction(e.wertquote) for v in kopf.values() for e, z in v if z == 'ja')
    nein_q = sum(Fraction(e.wertquote) for v in kopf.values() for e, z in v if z == 'nein')
    anwesend_k = len(kopf)
    # Köpfe, die nur «da» sind (ohne Stimme), zählen nur als anwesend.
    alle_k = len({e.stockwerkeigentuemer_id for e in einheiten})
    tq = Fraction(total_quoten)
    return {
        'doppelt': ja_k > nein_k and ja_q > nein_q,
        'doppelt_aller': 2 * ja_k > alle_k and 2 * ja_q > tq,
        'doppelt_anwesende': 2 * ja_k > anwesend_k and 2 * ja_q > tq,
        'einfach_koepfe': ja_k > nein_k, 'einfach_quoten': ja_q > nein_q,
        'einstimmig': ja_k == alle_k,
    }[art]


class DoppeltesMehrRechnungTests(TestCase):
    # Fünf Einheiten, Eigentümer 1 hat zwei davon: vier Köpfe, 1000 Quoten.
    EINHEITEN = [_E(1, 150, 1), _E(2, 150, 1), _E(3, 250, 2), _E(4, 200, 3), _E(5, 250, 4)]

    def rechne(self, art, zustand):
        stimmen = {e.pk: {'ja': 'ja', 'nein': 'nein', 'enth': 'enthaltung'}[z]
                   for e, z in zip(self.EINHEITEN, zustand) if z in ('ja', 'nein', 'enth')}
        anwesend = len({e.stockwerkeigentuemer_id for e, z in zip(self.EINHEITEN, zustand) if z != 'abwesend'})
        r = zaehlen(self.EINHEITEN, stimmen, art, 1000, anwesende_koepfe=anwesend)
        return r['vorschlag'] == Traktandum.ANGENOMMEN

    def test_alle_kombinationen_gegen_das_orakel(self):
        pruefungen = 0
        for zustand in itertools.product(('abwesend', 'ja', 'nein', 'enth', 'da'), repeat=5):
            for art in ('doppelt', 'doppelt_aller', 'doppelt_anwesende', 'einfach_koepfe',
                        'einfach_quoten', 'einstimmig'):
                erwartet = orakel(art, self.EINHEITEN, zustand, 1000)
                if erwartet is None:
                    continue
                self.assertEqual(self.rechne(art, zustand), erwartet, (art, zustand))
                pruefungen += 1
        self.assertGreater(pruefungen, 15000)

    def zaehle(self, ja, nein, anwesend_koepfe, **kw):
        """Fünf Eigentümer à eine Einheit; `ja`/`nein` sind Listen von Quoten."""
        einheiten = [_E(i, q, i) for i, q in enumerate(ja + nein + kw.get('rest', []), start=1)]
        stimmen = {e.pk: 'ja' for e in einheiten[:len(ja)]}
        stimmen.update({e.pk: 'nein' for e in einheiten[len(ja):len(ja) + len(nein)]})
        return zaehlen(einheiten, stimmen, kw.get('art', 'doppelt_anwesende'),
                       sum(e.wertquote for e in einheiten), anwesende_koepfe=anwesend_koepfe)['vorschlag']

    def test_knapp_kopfmehrheit_aber_nicht_genug_quote(self):
        # 3 von 5 Köpfen, aber nur 490 von 1000 Quoten → abgelehnt
        self.assertEqual(self.zaehle([160, 165, 165], [260, 250], 5), 'abgelehnt')

    def test_knapp_quote_aber_keine_kopfmehrheit(self):
        # 2 von 5 Köpfen mit 600 Quoten → abgelehnt
        self.assertEqual(self.zaehle([300, 300], [100, 100, 200], 5), 'abgelehnt')

    def test_beides_knapp_erfuellt(self):
        # 3 von 5 Köpfen, 501 von 1000 Quoten → angenommen
        self.assertEqual(self.zaehle([167, 167, 167], [250, 249], 5), 'angenommen')

    def test_genau_fuenfzig_prozent_der_quoten_genuegt_nicht(self):
        self.assertEqual(self.zaehle([166, 167, 167], [250, 250], 5), 'abgelehnt')

    def test_genau_die_haelfte_der_koepfe_genuegt_nicht(self):
        self.assertEqual(self.zaehle([300, 300], [200, 200], 4), 'abgelehnt')

    def test_enthaltungen_und_stille_anwesende_zaehlen_als_anwesend(self):
        # Vier Anwesende, zwei Ja → keine Mehrheit der Anwesenden, auch wenn niemand Nein sagt
        self.assertEqual(self.zaehle([400, 400], [], 4, rest=[100, 100]), 'abgelehnt')
        self.assertEqual(self.zaehle([400, 400, 100], [], 4, rest=[100]), 'angenommen')

    def test_unterschied_zu_den_anderen_doppelten_mehrheiten(self):
        # Ja: 2 Köpfe/700; Nein: 1 Kopf/100; 2 Abwesende. «doppelt» (Stimmende) ja,
        # «doppelt_aller» nein (2 von 5), «doppelt_anwesende» ja (2 von 3).
        e = [_E(i, q, i) for i, q in enumerate([350, 350, 100, 100, 100], start=1)]
        stimmen = {1: 'ja', 2: 'ja', 3: 'nein'}
        r = {art: zaehlen(e, stimmen, art, 1000, anwesende_koepfe=3)['vorschlag']
             for art in ('doppelt', 'doppelt_aller', 'doppelt_anwesende')}
        self.assertEqual(r, {'doppelt': 'angenommen', 'doppelt_aller': 'abgelehnt',
                             'doppelt_anwesende': 'angenommen'})

    def test_anwesende_mehrheit_braucht_die_anwesenheit(self):
        with self.assertRaises(BeschlussFehler):
            zaehlen(self.EINHEITEN, {1: 'ja'}, 'doppelt_anwesende', 1000)


class EVotingTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.v = Versammlung.objects.create(
            liegenschaft=self.lg, titel='OV', datum=timezone.now() + timedelta(days=20),
            status='durchgefuehrt', evoting=True)
        self.t = Traktandum.objects.create(versammlung=self.v, nr=1, titel='Budget',
                                           mehrheitsart='doppelt_anwesende')
        self.k = Traktandum.objects.create(versammlung=self.v, nr=2, titel='Information',
                                           mehrheitsart='kenntnisnahme')
        self.anna, self.bruno = self.eigs[0], self.eigs[1]

    def test_teilnahme_dann_stimme(self):
        evoting.teilnehmen(self.v, self.anna)
        self.assertEqual(evoting.abstimmen(self.v, self.anna, {(self.t.pk, self.e[0].pk): 'ja'}), 1)
        s = Stimme.objects.get(traktandum=self.t, einheit=self.e[0])
        self.assertEqual((s.wert, s.kanal), ('ja', 'portal'))
        self.assertIsNotNone(s.abgegeben_am)
        self.assertEqual(auswerten(self.t)['ja_koepfe'], 1)

    def test_ohne_teilnahme_keine_stimme(self):
        with self.assertRaisesRegex(BeschlussFehler, 'Teilnahme erklären'):
            evoting.abstimmen(self.v, self.anna, {(self.t.pk, self.e[0].pk): 'ja'})
        self.assertFalse(Stimme.objects.exists())

    def test_nur_die_eigene_einheit(self):
        evoting.teilnehmen(self.v, self.anna)
        evoting.teilnehmen(self.v, self.bruno)
        with self.assertRaises(BeschlussFehler):
            evoting.abstimmen(self.v, self.anna, {(self.t.pk, self.e[1].pk): 'ja'})   # Brunos Einheit
        self.assertFalse(Stimme.objects.exists())

    def test_alles_oder_nichts(self):
        evoting.teilnehmen(self.v, self.anna)
        with self.assertRaises(BeschlussFehler):
            evoting.abstimmen(self.v, self.anna, {(self.t.pk, self.e[0].pk): 'ja',
                                                  (self.k.pk, self.e[0].pk): 'ja'})   # Kenntnisnahme
        self.assertFalse(Stimme.objects.exists())
        self.assertFalse(StimmeEreignis.objects.exists())

    def test_miteigentuemer_darf_nicht_handeln(self):
        evoting.teilnehmen(self.v, self.anna)
        misch = Eigentuemer.objects.create(firma_oder_name='Mit', email='m@x.ch')
        self.e[0].miteigentuemer.add(misch)
        with self.assertRaises(BeschlussFehler):
            evoting.teilnehmen(self.v, misch)
        with self.assertRaises(BeschlussFehler):
            evoting.abstimmen(self.v, misch, {(self.t.pk, self.e[0].pk): 'ja'})

    def test_fenster_geschlossen_oder_nicht_vorgesehen(self):
        self.v.evoting_bis = timezone.now() - timedelta(minutes=1)
        self.v.save()
        with self.assertRaises(BeschlussFehler):
            evoting.teilnehmen(self.v, self.anna)
        self.v.evoting_bis = None
        self.v.evoting = False
        self.v.save()
        with self.assertRaises(BeschlussFehler):
            evoting.teilnehmen(self.v, self.anna)
        self.v.evoting, self.v.status = True, 'eingeladen'
        self.v.save()
        with self.assertRaises(BeschlussFehler):
            evoting.teilnehmen(self.v, self.anna)

    def test_nach_der_feststellung_gesperrt(self):
        evoting.teilnehmen(self.v, self.anna)
        evoting.abstimmen(self.v, self.anna, {(self.t.pk, self.e[0].pk): 'ja'})
        feststellen(self.t, 'abgelehnt')
        self.t.refresh_from_db()
        with self.assertRaises(BeschlussFehler):
            evoting.abstimmen(self.v, self.anna, {(self.t.pk, self.e[0].pk): 'nein'})
        self.assertEqual(Stimme.objects.get(traktandum=self.t).wert, 'ja')

    def test_aenderung_steht_im_ereignisprotokoll(self):
        evoting.teilnehmen(self.v, self.anna)
        evoting.abstimmen(self.v, self.anna, {(self.t.pk, self.e[0].pk): 'ja'})
        evoting.abstimmen(self.v, self.anna, {(self.t.pk, self.e[0].pk): 'nein'})
        self.assertEqual(Stimme.objects.get(traktandum=self.t).wert, 'nein')
        log = list(StimmeEreignis.objects.order_by('id').values_list('vorher', 'wert', 'kanal', 'eigentuemer'))
        self.assertEqual(log, [('', 'ja', 'portal', self.anna.pk), ('ja', 'nein', 'portal', self.anna.pk)])

    def test_vollmacht_eigentuemer_kommt_trotzdem_digital(self):
        Anwesenheit.objects.create(versammlung=self.v, einheit=self.e[0], art='vertreten', vertreter='X')
        evoting.teilnehmen(self.v, self.anna)
        a = Anwesenheit.objects.get(einheit=self.e[0])
        self.assertEqual((a.art, a.vertreter), ('anwesend', ''))

    def test_knappes_ergebnis_mit_echten_einheiten(self):
        # Fünf Eigentümer; Quoten 150/200/250/200/200. Ja: Anna(150)+Carla(250)+Dario(200)=600 mit 3 Köpfen
        for eig in self.eigs:
            evoting.teilnehmen(self.v, eig)
        werte = ['ja', 'nein', 'ja', 'ja', 'nein']
        for eig, einheit, w in zip(self.eigs, self.e, werte):
            evoting.abstimmen(self.v, eig, {(self.t.pk, einheit.pk): w})
        z = auswerten(self.t)
        self.assertEqual((z['ja_koepfe'], z['nein_koepfe'], z['ja_quoten'], z['nein_quoten']),
                         (3, 2, Decimal('600.00'), Decimal('400.00')))
        self.assertEqual(z['vorschlag'], 'angenommen')
        # Carla wechselt auf Nein → 2 Köpfe/350 → abgelehnt
        evoting.abstimmen(self.v, self.eigs[2], {(self.t.pk, self.e[2].pk): 'nein'})
        self.assertEqual(auswerten(self.t)['vorschlag'], 'abgelehnt')

    def test_stimmen_loeschen_nach_feststellung_gesperrt(self):
        from stweg.beschluss import stimme_abgeben, stimme_loeschen
        evoting.teilnehmen(self.v, self.anna)
        stimme_abgeben(self.t, self.e[0], 'ja')
        feststellen(self.t, 'angenommen')
        self.t.refresh_from_db()
        with self.assertRaises(BeschlussFehler):
            stimme_loeschen(self.t, self.e[0])
