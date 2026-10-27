"""Zahlungsvereinbarung (26.10.2026): Sperre je Forderung, Datenmigration, Schreiben.

Vorher setzte `zahlungsvereinbarung.anlegen` das Häkchen `Mieter.mahnsperre`:
Jede neue Miete während des Ratenplans blieb ungemahnt, und das Mahnwesen nannte
als Grund «laufende Zahlungsvereinbarung» — auch für Mieten, die sie gar nicht
deckt. Jetzt sperrt die Vereinbarung nur die gedeckten Forderungen.
"""
import io
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user


class SperreNurFuerGedeckteForderungenTests(TestCase):

    def setUp(self):
        _seed_konten()
        from core.services import zahlungsvereinbarung as zv
        from finance.models import DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = date.today()
        self.alt = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Miete alt', datum=self.heute - timedelta(days=70),
            faellig_am=self.heute - timedelta(days=70), betrag=Decimal('1000.00'))
        self.vb = zv.anlegen(self.v, 3, self.heute)
        # Die Vereinbarung wurde vor 40 Tagen geschlossen; seither ist eine neue Miete fällig.
        self.vb.gedeckt_bis = self.heute - timedelta(days=40)
        self.vb.save(update_fields=['gedeckt_bis'])
        self.neu = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Miete neu', datum=self.heute - timedelta(days=35),
            faellig_am=self.heute - timedelta(days=35), betrag=Decimal('1700.00'))

    def test_neue_miete_waehrend_des_plans_wird_gemahnt(self):
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung
        res = run_mahnlauf(send_email=False)
        self.assertEqual(res['gemahnt'], 1)
        self.assertEqual(list(Mahnung.objects.values_list('debitoren_rechnung_id', flat=True)), [self.neu.pk])

    def test_mahngebuehr_der_gedeckten_forderung_teilt_die_sperre(self):
        from core.services import zahlungsvereinbarung as zv
        from finance.models import DebitorenRechnung
        gebuehr = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Mahngebühr 1. Mahnung', datum=self.heute, faellig_am=self.heute,
            betrag=Decimal('20.00'), stammrechnung=self.alt)
        gebuehr_neu = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Mahngebühr 1. Mahnung', datum=self.heute, faellig_am=self.heute,
            betrag=Decimal('20.00'), stammrechnung=self.neu)
        self.assertTrue(zv.ist_durch_vereinbarung_gesperrt(gebuehr))
        self.assertFalse(zv.ist_durch_vereinbarung_gesperrt(gebuehr_neu))
        self.assertEqual(zv.gesperrte_rechnung_ids(), {self.alt.pk, gebuehr.pk})

    def test_mahnwesen_nennt_den_grund_und_zeigt_die_neue_miete(self):
        c = Client()
        c.force_login(_team_user('Verwalter'))
        antwort = c.get('/neu/mahnwesen/', secure=True)
        self.assertEqual(antwort.status_code, 200)
        gruende = {z['r'].pk: z['grund'] for z in antwort.context['ohne_mahnfall']}
        self.assertIn('Zahlungsvereinbarung', gruende.get(self.alt.pk, ''))
        self.assertNotIn(self.neu.pk, gruende)
        gezeigt = ({row['r'].pk for row in antwort.context['rows']}
                   | {row['r'].pk for row in antwort.context['vorlauf']})
        self.assertIn(self.neu.pk, gezeigt)
        self.assertNotIn(self.alt.pk, gezeigt)
        self.assertContains(antwort, f'/neu/vertraege/{self.v.id}/zahlungsvereinbarung/')


class HandschalterImMahnwesenTests(TestCase):
    """Der Handschalter `Mieter.mahnsperre` sperrt im Mahnlauf den ganzen Mieter —
    bis 27.10.2026 zeigte die Hauptliste des Mahnwesens dessen Rechnungen trotzdem
    als Mahnfälle."""

    def test_hand_gesperrter_mieter_steht_unter_nicht_im_mahnlauf(self):
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        heute = date.today()
        r = DebitorenRechnung.objects.create(vertrag=v, titel='Miete', datum=heute - timedelta(days=70),
                                             faellig_am=heute - timedelta(days=70), betrag=Decimal('1000.00'))
        m.mahnsperre = True
        m.save(update_fields=['mahnsperre'])
        c = Client()
        c.force_login(_team_user('Verwalter'))
        antwort = c.get('/neu/mahnwesen/', secure=True)
        gezeigt = ({row['r'].pk for row in antwort.context['rows']}
                   | {row['r'].pk for row in antwort.context['vorlauf']})
        self.assertNotIn(r.pk, gezeigt)
        gruende = {z['r'].pk: z['grund'] for z in antwort.context['ohne_mahnfall']}
        self.assertIn('von Hand', gruende.get(r.pk, ''))


class MahnsperreDatenmigrationTests(TestCase):
    """finance 0048: Das Häkchen, das die Vereinbarung gesetzt hatte, wird gelöst."""

    def test_aktive_vereinbarung_loest_das_haekchen_andere_bleiben(self):
        import importlib

        from django.apps import apps as django_apps

        from crm.models import Mieter
        from finance.models import Zahlungsvereinbarung
        _seed_konten()
        _lg, _e, m, v = _basis_objekte()
        heute = date.today()
        Zahlungsvereinbarung.objects.create(vertrag=v, betrag_total=Decimal('500'), gedeckt_bis=heute,
                                            anzahl_raten=2, erste_rate=heute)
        andere = Mieter.objects.create(typ='person', vorname='Ohne', nachname='Plan', mahnsperre=True)
        Mieter.objects.filter(pk=m.pk).update(mahnsperre=True)
        modul = importlib.import_module('finance.migrations.0048_mahnsperre_nur_gedeckte_forderungen')
        modul.mahnsperre_aus_vereinbarung_loesen(django_apps, None)
        self.assertFalse(Mieter.objects.get(pk=m.pk).mahnsperre)
        self.assertTrue(Mieter.objects.get(pk=andere.pk).mahnsperre)


class SchuldanerkennungPdfTests(TestCase):
    """«Zahlungsvereinbarung mit Schuldanerkennung» — Inhalt, Ablage, Grenzen."""

    def setUp(self):
        _seed_konten()
        from core.services import zahlungsvereinbarung as zv
        from finance.models import DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = date.today()
        DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Miete 08', datum=self.heute - timedelta(days=40),
            faellig_am=self.heute - timedelta(days=40), betrag=Decimal('1000.00'))
        self.vb = zv.anlegen(self.v, 2, self.heute)
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))
        self.url = f'/neu/vertraege/{self.v.id}/zahlungsvereinbarung/pdf/'

    def _text(self, pdf):
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf)) as d:
            text = ' '.join(seite.extract_text() or '' for seite in d.pages)
        # Zeilenumbrüche des Briefs sind Layout, nicht Inhalt.
        return ' '.join(text.split())

    def test_pdf_nennt_parteien_forderungen_raten_folgen_und_art_82(self):
        antwort = self.c.get(self.url, {'vb': self.vb.pk}, secure=True)
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort['Content-Type'], 'application/pdf')
        text = self._text(antwort.content)
        for stueck in ('Zahlungsvereinbarung mit Schuldanerkennung', 'Hans Muster', 'Miete 08',
                       '1. Schuldanerkennung', '2. Ratenplan', '3. Folgen eines Zahlungsverzugs',
                       'Art. 82 SchKG', '500.00', 'Mieter: Hans Muster', 'Vermieterin:'):
            self.assertIn(stueck, text)

    def test_pdf_wird_einmal_in_der_vertragsakte_abgelegt(self):
        from rentals.models import Dokument
        self.c.get(self.url, secure=True)
        self.c.get(self.url, secure=True)
        self.assertEqual(Dokument.objects.filter(
            vertrag=self.v, bezeichnung=f'Zahlungsvereinbarung mit Schuldanerkennung #{self.vb.pk}').count(), 1)

    def test_vereinbarung_eines_anderen_vertrags_ist_nicht_erreichbar(self):
        from crm.models import Mieter
        from rentals.models import Mietvertrag
        m2 = Mieter.objects.create(typ='person', vorname='Eva', nachname='Fremd')
        v2 = Mietvertrag.objects.create(mieter=m2, einheit=self.e, beginn=date(2024, 1, 1),
                                        netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'),
                                        status='aktiv', kautions_betrag=Decimal('0'))
        antwort = self.c.get(f'/neu/vertraege/{v2.id}/zahlungsvereinbarung/pdf/', {'vb': self.vb.pk},
                             secure=True)
        self.assertEqual(antwort.status_code, 404)
        self.assertEqual(self.c.get(self.url, {'vb': 'x'}, secure=True).status_code, 404)

    def test_sachbearbeiter_darf_das_schreiben_nicht_erzeugen(self):
        c = Client()
        c.force_login(_team_user('Sachbearbeiter'))
        self.assertEqual(c.get(self.url, secure=True).status_code, 403)

    def test_seite_bietet_das_schreiben_und_die_hilfe_an(self):
        antwort = self.c.get(f'/neu/vertraege/{self.v.id}/zahlungsvereinbarung/', secure=True)
        self.assertContains(antwort, f'zahlungsvereinbarung/pdf/?vb={self.vb.pk}')
        self.assertContains(antwort, 'data-hilfebox="zahlungsvereinbarung"')
