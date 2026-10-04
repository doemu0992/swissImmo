"""Zirkularbeschluss: Antrag, Abstimmung, Feststellung, Ergebnis."""
from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from core.models import Pendenz
from stweg import zirkular
from stweg.beschluss import BeschlussFehler
from stweg.models import Zirkularbeschluss, ZirkularStimme, ZirkularVersand
from stweg.test_versammlung import sonnenblick
from stweg.versammlung import VersammlungsFehler


def neuer_zirkular(lg, tage=14, **kw):
    return Zirkularbeschluss.objects.create(
        liegenschaft=lg, titel='Waschmaschine ersetzen', antrag='Die Waschmaschine wird ersetzt.',
        frist_bis=timezone.localdate() + timedelta(days=tage), **kw)


class ZirkularPruefenUndVersandTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()

    def test_versandbereit(self):
        self.assertEqual(zirkular.pruefen(neuer_zirkular(self.lg)), [])

    def test_gruende_gegen_den_versand(self):
        z = neuer_zirkular(self.lg, tage=-1)
        z.antrag = ' '
        self.e[0].stockwerkeigentuemer = None
        self.e[0].save()
        text = '; '.join(zirkular.pruefen(z))
        for erwartet in ('Antrag fehlt', 'Zukunft', 'hat keinen Stockwerkeigentümer'):
            self.assertIn(erwartet, text)

    def test_falsche_wertquoten_blockieren(self):
        self.e[0].wertquote = Decimal(199)
        self.e[0].save()
        with self.assertRaises(VersammlungsFehler):
            zirkular.versenden(neuer_zirkular(self.lg))
        self.assertEqual(len(mail.outbox), 0)

    def test_versand_an_alle_mit_pdf_und_wiederholung(self):
        z = neuer_zirkular(self.lg)
        neu = zirkular.versenden(z)
        self.assertEqual(len(neu), 3)
        self.assertEqual(len(mail.outbox), 3)
        self.assertTrue(mail.outbox[0].attachments[0][1].startswith(b'%PDF'))
        z.refresh_from_db()
        self.assertEqual(z.status, 'laufend')
        self.assertEqual(len(zirkular.versenden(z)), 0)               # nichts doppelt

    def test_ohne_email_wird_post_vermerkt(self):
        lg, e, _ = sonnenblick(emails=('a@x.ch', '', 'c@x.ch'))
        neu = zirkular.versenden(neuer_zirkular(lg))
        self.assertEqual(sorted(n.status for n in neu), ['gesendet', 'gesendet', 'post_noetig'])


class ZirkularAbstimmungTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.z = neuer_zirkular(self.lg)
        zirkular.versenden(self.z)
        self.z.refresh_from_db()
        self.morgen = timezone.localdate() + timedelta(days=20)        # nach der Frist

    def alle(self, *werte):
        for e, w in zip(self.e, werte):
            zirkular.stimme_abgeben(self.z, e, w)

    def test_stimmen_nur_bei_laufendem_beschluss(self):
        entwurf = neuer_zirkular(self.lg)
        with self.assertRaises(BeschlussFehler):
            zirkular.stimme_abgeben(entwurf, self.e[0], 'ja')

    def test_portal_stimme_nach_der_frist_abgelehnt_verwaltung_darf_nachtragen(self):
        with self.assertRaises(BeschlussFehler):
            zirkular.stimme_abgeben(self.z, self.e[0], 'ja', heute=self.morgen)
        zirkular.stimme_abgeben(self.z, self.e[0], 'ja', kanal='verwaltung', heute=self.morgen)
        self.assertEqual(ZirkularStimme.objects.get().kanal, 'verwaltung')

    def test_stimme_aendern_ersetzt_statt_zu_verdoppeln(self):
        zirkular.stimme_abgeben(self.z, self.e[0], 'ja')
        zirkular.stimme_abgeben(self.z, self.e[0], 'nein')
        self.assertEqual(list(ZirkularStimme.objects.values_list('wert', flat=True)), ['nein'])

    def test_einheit_einer_anderen_gemeinschaft_und_ungueltiger_wert(self):
        from stweg.tests import neue_stweg
        fremd_lg, fremd_e = neue_stweg(name='Andere')
        with self.assertRaises(BeschlussFehler):
            zirkular.stimme_abgeben(self.z, fremd_e[0], 'ja')
        with self.assertRaises(BeschlussFehler):
            zirkular.stimme_abgeben(self.z, self.e[0], 'vielleicht')

    def test_einstimmig_braucht_alle(self):
        self.alle('ja', 'ja')                                          # Carla hat nicht abgestimmt
        self.assertEqual(zirkular.auswerten(self.z)['vorschlag'], 'abgelehnt')
        zirkular.stimme_abgeben(self.z, self.e[2], 'ja')
        self.assertEqual(zirkular.auswerten(self.z)['vorschlag'], 'angenommen')
        zirkular.stimme_abgeben(self.z, self.e[2], 'nein')
        self.assertEqual(zirkular.auswerten(self.z)['vorschlag'], 'abgelehnt')

    def test_einfache_mehrheit_zaehlt_nur_die_abgegebenen(self):
        self.z.mehrheitsart = 'einfach_koepfe'
        self.alle('ja', 'ja')                                          # 2:0, einer ohne Stimme
        self.assertEqual(zirkular.auswerten(self.z)['vorschlag'], 'angenommen')

    def test_feststellen_erst_nach_frist_oder_wenn_alle_abgestimmt_haben(self):
        self.alle('ja', 'ja')
        with self.assertRaises(BeschlussFehler):
            zirkular.feststellen(self.z, 'angenommen')
        zirkular.stimme_abgeben(self.z, self.e[2], 'ja')                # jetzt vollständig
        zirkular.feststellen(self.z, 'angenommen', beschlusstext='Genehmigt')
        self.z.refresh_from_db()
        self.assertEqual((self.z.status, self.z.ergebnis, self.z.ja_koepfe, self.z.ja_quoten),
                         ('abgeschlossen', 'angenommen', 3, Decimal('1000')))

    def test_feststellen_nach_der_frist_mit_unvollstaendigen_stimmen(self):
        self.alle('ja', 'ja')
        zirkular.feststellen(self.z, 'abgelehnt', heute=self.morgen)
        self.z.refresh_from_db()
        self.assertEqual(self.z.ergebnis, 'abgelehnt')

    def test_zweimal_feststellen_und_ungueltiges_ergebnis(self):
        self.alle('ja', 'ja', 'ja')
        with self.assertRaises(BeschlussFehler):
            zirkular.feststellen(self.z, 'offen')
        zirkular.feststellen(self.z, 'angenommen')
        with self.assertRaises(BeschlussFehler):
            zirkular.feststellen(self.z, 'abgelehnt')

    def test_widerspruch_desselben_eigentuemers_blockiert(self):
        self.e[1].stockwerkeigentuemer = self.eigs[0]
        self.e[1].save()
        self.alle('ja', 'nein', 'ja')
        with self.assertRaises(BeschlussFehler):
            zirkular.feststellen(self.z, 'angenommen')

    def test_vollzug_wird_einmal_zur_pendenz(self):
        self.z.vollzug_aufgabe = 'Waschmaschine bestellen'
        self.z.save()
        self.alle('ja', 'ja', 'ja')
        zirkular.feststellen(self.z, 'angenommen')
        self.assertEqual(Pendenz.objects.filter(quelle=f'stweg:zirkular:{self.z.pk}').count(), 1)

    def test_abgelehnt_ohne_pendenz(self):
        self.z.vollzug_aufgabe = 'X'
        self.z.save()
        self.alle('nein', 'nein', 'nein')
        zirkular.feststellen(self.z, 'abgelehnt')
        self.assertFalse(Pendenz.objects.filter(quelle__startswith='stweg:zirkular').exists())

    def test_ergebnis_geht_an_alle_auch_an_nichtstimmende(self):
        with self.assertRaises(VersammlungsFehler):
            zirkular.ergebnis_versenden(self.z)                       # noch nicht festgestellt
        self.alle('ja', 'ja')
        zirkular.feststellen(self.z, 'abgelehnt', heute=self.morgen)
        mail.outbox.clear()
        neu = zirkular.ergebnis_versenden(self.z)
        self.assertEqual((len(neu), len(mail.outbox)), (3, 3))
        self.assertIn('Abgelehnt', mail.outbox[0].body)
        self.assertEqual(len(zirkular.ergebnis_versenden(self.z)), 0)
        self.assertEqual(ZirkularVersand.objects.filter(art='ergebnis').count(), 3)

    def test_pdf_zeigt_antrag_und_ergebnis(self):
        from stweg.pdf import zirkular_pdf
        self.assertTrue(zirkular_pdf(self.z).startswith(b'%PDF'))
        self.alle('ja', 'ja', 'ja')
        zirkular.feststellen(self.z, 'angenommen')
        self.assertTrue(zirkular_pdf(self.z).startswith(b'%PDF'))
