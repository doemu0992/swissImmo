"""Tests des digitalen STWEG-Ablaufs: Einladung, Beschluss, Protokoll, Anfragen, offene Punkte."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from core.models import Pendenz
from crm.models import Eigentuemer
from stweg import aufgaben, anfragen, beschluss
from stweg.models import Anwesenheit, StwegVersand, Traktandum, Versammlung
from stweg.versammlung import (VersammlungsFehler, durchfuehren, einladung_pruefen,
                               einladung_versenden, protokoll_versenden)
from stweg.tests import neue_stweg


def sonnenblick(emails=('a@x.ch', 'b@x.ch', 'c@x.ch')):
    lg, einheiten = neue_stweg(quoten=(200, 300, 500), status='aktiv')
    eigs = []
    for e, name, mail_ in zip(einheiten, ('Anna', 'Bruno', 'Carla'), emails):
        eig = Eigentuemer.objects.create(firma_oder_name=name, email=mail_)
        e.stockwerkeigentuemer = eig
        e.save()
        eigs.append(eig)
    return lg, einheiten, eigs


def versammlung(lg, tage=30, **kw):
    v = Versammlung.objects.create(
        liegenschaft=lg, titel='Ordentliche Versammlung 2026',
        datum=timezone.now() + timedelta(days=tage), ort='Gemeindesaal', **kw)
    Traktandum.objects.create(geschaeftsart='sonstiges', rechtsgrundlage='Reglement (Test)', versammlung=v, nr=1, titel='Jahresrechnung', antrag='Genehmigung')
    return v


class EinladungTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()

    def test_versandbereit(self):
        self.assertEqual(einladung_pruefen(versammlung(self.lg)), [])

    def test_frist_unterschritten(self):
        p = einladung_pruefen(versammlung(self.lg, tage=5))
        self.assertTrue(any('Einladungsfrist' in x for x in p))

    def test_frist_ist_pro_versammlung_einstellbar(self):
        v = versammlung(self.lg, tage=5, einladungsfrist_tage=3)
        self.assertEqual(einladung_pruefen(v), [])

    def test_ohne_traktandum_und_einheit_ohne_eigentuemer(self):
        v = versammlung(self.lg)
        v.traktanden.all().delete()
        self.e[0].stockwerkeigentuemer = None
        self.e[0].save()
        p = '; '.join(einladung_pruefen(v))
        self.assertIn('kein Traktandum', p)
        self.assertIn('hat keinen Stockwerkeigentümer', p)

    def test_falsche_wertquoten_blockieren(self):
        v = versammlung(self.lg)
        self.e[0].wertquote = Decimal(199)
        self.e[0].save()
        self.assertTrue(any('199' in x or '999' in x for x in einladung_pruefen(v)))
        with self.assertRaises(VersammlungsFehler):
            einladung_versenden(v)
        self.assertEqual(len(mail.outbox), 0)

    def test_versand_mit_pdf_und_protokoll_je_empfaenger(self):
        v = versammlung(self.lg)
        neu = einladung_versenden(v)
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual({n.status for n in neu}, {'gesendet'})
        m = mail.outbox[0]
        self.assertTrue(m.attachments and m.attachments[0][1].startswith(b'%PDF'))
        v.refresh_from_db()
        self.assertEqual(v.status, Versammlung.EINGELADEN)
        self.assertIsNotNone(v.einladung_versendet_am)

    def test_wiederholung_sendet_nicht_doppelt_und_versucht_fehler_erneut(self):
        v = versammlung(self.lg)
        with mock.patch('stweg.versammlung.send_via_hoststar', side_effect=[True, False, True]):
            einladung_versenden(v)
        self.assertEqual(StwegVersand.objects.filter(status='fehler').count(), 1)
        with mock.patch('stweg.versammlung.send_via_hoststar', return_value=True) as m:
            einladung_versenden(v)
        self.assertEqual(m.call_count, 1)        # nur der Fehlgeschlagene

    def test_ohne_email_wird_post_vermerkt(self):
        lg, e, _ = sonnenblick(emails=('a@x.ch', '', 'c@x.ch'))
        neu = einladung_versenden(versammlung(lg))
        self.assertEqual(sorted(n.status for n in neu), ['gesendet', 'gesendet', 'post_noetig'])
        self.assertEqual(len(mail.outbox), 2)


class BeschlussTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.v = versammlung(self.lg)
        einladung_versenden(self.v)
        durchfuehren(self.v)
        self.t = self.v.traktanden.get()
        for e in self.e:
            beschluss.anwesenheit_setzen(self.v, e, Anwesenheit.ANWESEND)

    def stimmen(self, *werte):
        for e, w in zip(self.e, werte):
            beschluss.stimme_abgeben(self.t, e, w)

    def test_je_mehrheitsart_anderes_ergebnis(self):
        self.stimmen('ja', 'ja', 'nein')            # Köpfe 2:1, Quoten 500:500
        erwartet = {'einfach_koepfe': 'angenommen', 'einfach_quoten': 'abgelehnt',
                    'doppelt': 'abgelehnt', 'doppelt_aller': 'abgelehnt',
                    'einstimmig': 'abgelehnt'}
        for art, ergebnis in erwartet.items():
            self.t.mehrheitsart = art
            self.assertEqual(beschluss.auswerten(self.t)['vorschlag'], ergebnis, art)

    def test_einstimmig_und_doppelt_aller_angenommen(self):
        self.stimmen('ja', 'ja', 'ja')
        for art in ('einstimmig', 'doppelt_aller', 'doppelt'):
            self.t.mehrheitsart = art
            self.assertEqual(beschluss.auswerten(self.t)['vorschlag'], 'angenommen', art)

    def test_abwesende_zaehlen_bei_aller_nicht(self):
        beschluss.anwesenheit_setzen(self.v, self.e[2], Anwesenheit.ABWESEND)
        self.stimmen('ja', 'ja')
        self.t.mehrheitsart = 'doppelt_aller'       # 2 von 3 Köpfen, 500 von 1000 Quoten
        self.assertEqual(beschluss.auswerten(self.t)['vorschlag'], 'abgelehnt')
        self.t.mehrheitsart = 'einfach_koepfe'
        self.assertEqual(beschluss.auswerten(self.t)['vorschlag'], 'angenommen')

    def test_abwesende_haben_kein_stimmrecht(self):
        beschluss.anwesenheit_setzen(self.v, self.e[2], Anwesenheit.ABWESEND)
        with self.assertRaises(beschluss.BeschlussFehler):
            beschluss.stimme_abgeben(self.t, self.e[2], 'ja')

    def test_enthaltung_zaehlt_nicht(self):
        self.stimmen('ja', 'enthaltung', 'nein')
        z = beschluss.auswerten(self.t)
        self.assertEqual((z['ja_koepfe'], z['nein_koepfe'], z['enthaltung_koepfe']), (1, 1, 1))

    def test_ein_eigentuemer_mehrere_einheiten_ein_kopf(self):
        self.e[1].stockwerkeigentuemer = self.eigs[0]       # Anna besitzt zwei Einheiten
        self.e[1].save()
        self.stimmen('ja', 'ja', 'nein')
        z = beschluss.auswerten(self.t)
        self.assertEqual((z['ja_koepfe'], z['nein_koepfe'], z['total_koepfe']), (1, 1, 2))
        self.assertEqual(z['ja_quoten'], Decimal('500'))

    def test_widerspruch_desselben_eigentuemers_blockiert_feststellung(self):
        self.e[1].stockwerkeigentuemer = self.eigs[0]
        self.e[1].save()
        self.stimmen('ja', 'nein', 'ja')
        self.assertTrue(beschluss.auswerten(self.t)['widerspruch'])
        with self.assertRaises(beschluss.BeschlussFehler):
            beschluss.feststellen(self.t, 'angenommen')

    def test_feststellen_haelt_zahlen_fest_und_erzeugt_einmal_pendenz(self):
        self.t.vollzug_aufgabe = 'Dach sanieren lassen'
        self.t.vollzug_faellig_am = timezone.localdate() + timedelta(days=60)
        self.t.save()
        self.stimmen('ja', 'ja', 'nein')
        beschluss.feststellen(self.t, 'angenommen', beschlusstext='Genehmigt.')
        beschluss.feststellen(self.t, 'angenommen')                      # zweimal: kein Duplikat
        self.t.refresh_from_db()
        self.assertEqual((self.t.ja_koepfe, self.t.nein_koepfe, self.t.ja_quoten), (2, 1, Decimal('500')))
        self.assertIsNotNone(self.t.festgestellt_am)
        p = Pendenz.objects.filter(quelle=f'stweg:beschluss:{self.t.pk}')
        self.assertEqual(p.count(), 1)
        self.assertEqual(p.get().titel, 'Dach sanieren lassen')

    def test_abgelehnt_erzeugt_keine_pendenz(self):
        self.t.vollzug_aufgabe = 'X'
        self.t.save()
        self.stimmen('nein', 'nein', 'nein')
        beschluss.feststellen(self.t, 'abgelehnt')
        self.assertFalse(Pendenz.objects.filter(quelle__startswith='stweg:beschluss').exists())

    def test_ohne_einberufung_kein_beschluss(self):
        v2 = versammlung(self.lg)
        with self.assertRaises(beschluss.BeschlussFehler):
            beschluss.feststellen(v2.traktanden.get(), 'angenommen')


class ProtokollTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.v = versammlung(self.lg)
        einladung_versenden(self.v)
        durchfuehren(self.v)
        mail.outbox.clear()

    def test_protokoll_erst_nach_feststellung(self):
        with self.assertRaises(VersammlungsFehler) as ctx:
            protokoll_versenden(self.v)
        self.assertIn('Jahresrechnung', ctx.exception.probleme[0])
        self.assertEqual(len(mail.outbox), 0)

    def test_protokoll_geht_an_alle_auch_abwesende(self):
        for e in self.e[:2]:
            beschluss.anwesenheit_setzen(self.v, e, Anwesenheit.ANWESEND)
            beschluss.stimme_abgeben(self.v.traktanden.get(), e, 'ja')
        beschluss.feststellen(self.v.traktanden.get(), 'angenommen', beschlusstext='Genehmigt')
        neu = protokoll_versenden(self.v)
        self.assertEqual(len(neu), 3)
        self.assertEqual(len(mail.outbox), 3)
        self.assertTrue(mail.outbox[0].attachments[0][1].startswith(b'%PDF'))
        self.v.refresh_from_db()
        self.assertEqual(self.v.status, Versammlung.PROTOKOLLIERT)
        self.assertEqual(len(protokoll_versenden(self.v)), 0)           # nichts doppelt


class AnfragenUndAufgabenTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()

    def test_anfrage_erzeugt_pendenz_und_antwort_schliesst_sie(self):
        a = anfragen.anfrage_erfassen(self.lg, 'Lift defekt?', 'Seit Montag steht er still',
                                      einheit=self.e[0])
        self.assertEqual(a.eigentuemer, self.eigs[0])
        p = Pendenz.objects.get(quelle=f'stweg:anfrage:{a.pk}')
        self.assertFalse(p.erledigt)
        self.assertTrue(anfragen.beantworten(a, 'Techniker ist bestellt.'))
        p.refresh_from_db(); a.refresh_from_db()
        self.assertTrue(p.erledigt)
        self.assertEqual(a.status, 'beantwortet')
        self.assertEqual(mail.outbox[0].to, ['a@x.ch'])
        self.assertIn('Techniker ist bestellt.', mail.outbox[0].body)

    def test_leere_antwort_wird_abgelehnt(self):
        a = anfragen.anfrage_erfassen(self.lg, 'Frage')
        with self.assertRaises(anfragen.AnfrageFehler):
            anfragen.beantworten(a, '  ')

    def test_nur_stweg_und_nur_eigene_einheit(self):
        miete = type(self.lg).objects.create(strasse='M 1', plz='8000', ort='Z',
                                             organisation=self.lg.organisation)
        with self.assertRaises(anfragen.AnfrageFehler):
            anfragen.anfrage_erfassen(miete, 'x')
        lg2, e2 = neue_stweg(name='Andere')
        with self.assertRaises(anfragen.AnfrageFehler):
            anfragen.anfrage_erfassen(self.lg, 'x', einheit=e2[0])

    def test_offene_punkte_sammeln_alles(self):
        v = versammlung(self.lg)
        einladung_versenden(v)
        durchfuehren(v)
        anfragen.anfrage_erfassen(self.lg, 'Offene Frage')
        aufgaben.aufgabe_erfassen(self.lg, 'Schlüssel nachbestellen')
        op = aufgaben.offene_punkte(self.lg)
        self.assertEqual(len(op['anfragen']), 1)
        self.assertEqual(len(op['aufgaben']), 2)                 # Aufgabe + Anfrage-Pendenz
        self.assertEqual(len(op['unentschiedene_traktanden']), 1)
        self.assertEqual(op['protokoll_ausstehend'], [v])
        aufgaben.erledigen(op['aufgaben'][0])
        self.assertEqual(len(aufgaben.offene_punkte(self.lg)['aufgaben']), 1)


class IsolationTests(TestCase):
    def test_fremde_verwaltung_sieht_keine_versammlung_und_anfrage(self):
        from core.tenancy import organisation_kontext
        from crm.models import Organisation
        from stweg.models import StwegAnfrage
        lg, e, _ = sonnenblick()
        versammlung(lg)
        anfragen.anfrage_erfassen(lg, 'Vertraulich')
        fremd = Organisation.objects.create(firma='Fremd AG', strasse='X 1', plz='9000', ort='SG')
        with organisation_kontext(fremd):
            self.assertEqual(Versammlung.objects.count(), 0)
            self.assertEqual(StwegAnfrage.objects.count(), 0)
            self.assertEqual(Traktandum.objects.count(), 0)
        self.assertEqual(Versammlung.objects.count(), 1)
