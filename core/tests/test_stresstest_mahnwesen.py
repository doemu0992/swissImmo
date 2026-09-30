"""Stresstest 30.09.2026, Punkte 5–7: Mahnbriefe und Eskalation zur 257d-Fristansetzung."""
from datetime import date, timedelta
from decimal import Decimal

from django.core import mail
from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user


def _pdf_text(dokument):
    """Text aus dem abgelegten PDF (unkomprimierte Inhaltsströme werden per pypdf gelesen)."""
    from pypdf import PdfReader
    dokument.datei.open('rb')
    try:
        return '\n'.join(p.extract_text() or '' for p in PdfReader(dokument.datei).pages)
    finally:
        dokument.datei.close()


class MahnbriefTests(TestCase):

    def setUp(self):
        _seed_konten()
        from finance.models import DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = date.today()
        # Dezembermiete, heute deutlich später gemahnt
        self.faellig = date(self.heute.year - 1, 12, 1)
        self.r = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Miete & NK 12', datum=self.faellig,
            faellig_am=self.faellig, betrag=Decimal('1700.00'))

    def _dokumente(self):
        from rentals.models import Dokument
        return list(Dokument.objects.filter(vertrag=self.v, bezeichnung__icontains='Mahnung'))

    def test_abgelegte_mahnung_nennt_den_monat_der_forderung_und_keine_androhung(self):
        from core.services.automation import run_mahnlauf
        run_mahnlauf(send_email=False)
        docs = self._dokumente()
        self.assertTrue(docs, 'Keine Mahnung in der Akte.')
        text = _pdf_text(docs[0])
        self.assertIn('Dezember', text, 'Falscher Monat im Mahnbrief.')
        self.assertIn(str(self.faellig.year), text)
        self.assertNotIn('Kündigungsandrohung', text.replace('Kündigung', 'Kündigung'),
                         'Die abgelegte Mahnung behauptet eine 257d-Kündigungsandrohung.')
        self.assertNotIn('30 TAGEN', text)

    def test_letzte_stufe_kuendigt_die_fristansetzung_nur_an(self):
        from core.services.automation import run_mahnlauf
        run_mahnlauf(send_email=False)            # > 60 Tage → Stufe 3
        docs = self._dokumente()
        text = ' '.join(_pdf_text(d) for d in docs)
        self.assertIn('gesonderten', text)
        self.assertIn('eingeschriebenen', text)
        self.assertNotIn('30 TAGEN', text)

    def test_pdf_aus_der_mahnliste_ist_das_schreiben_der_stufe(self):
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/vertrag/{self.v.id}/mahnung/?rechnung={self.r.id}&stufe=1', secure=True)
        self.assertEqual(r.status_code, 200)
        from pypdf import PdfReader
        import io
        text = '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(r.content)).pages)
        self.assertIn('Zahlungserinnerung', text)
        self.assertNotIn('30 TAGEN', text)
        self.assertNotIn('KÜNDIGUNGSANDROHUNG', text)

    def test_vertragsseite_liefert_weiterhin_die_257d_androhung(self):
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/vertrag/{self.v.id}/mahnung/?betrag=1700.00&monat=12/2025', secure=True)
        self.assertEqual(r.status_code, 200)
        from pypdf import PdfReader
        import io
        text = '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(r.content)).pages)
        self.assertIn('30 TAGEN', text)

    def test_email_kopie_mit_betrag_null_wird_abgewiesen(self):
        from django.core import mail
        c = Client(); c.force_login(_team_user())
        c.post(f'/vertrag/{self.v.id}/mahnung/mail/', {}, secure=True)
        self.assertEqual(len(mail.outbox), 0, 'Kündigungsandrohung über CHF 0.00 versendet.')


class EskalationTests(TestCase):

    def setUp(self):
        _seed_konten()
        from django.core.management import call_command
        from finance.models import DebitorenRechnung
        call_command('fallarten_anlegen', verbosity=0)
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = date.today()
        self.r = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Miete', datum=self.heute - timedelta(days=70),
            faellig_am=self.heute - timedelta(days=70), betrag=Decimal('1700.00'))

    def test_letzte_stufe_legt_pendenz_und_fall_an(self):
        from core.models import Pendenz
        from core.services.automation import run_mahnlauf
        from faelle.models import Fall
        run_mahnlauf(send_email=False)
        p = Pendenz.objects.get(vertrag=self.v, quelle=f'257d-vorschlag:{self.v.pk}')
        self.assertFalse(p.erledigt)
        self.assertEqual(Fall.objects.filter(fallart__schluessel='zahlungsverzug',
                                             status=Fall.OFFEN).count(), 1)

    def test_eskalation_ist_idempotent(self):
        from core.models import Pendenz
        from core.services.zahlungsverzug import eskalation_257d
        eskalation_257d(self.r); eskalation_257d(self.r)
        self.assertEqual(Pendenz.objects.filter(quelle__startswith='257d-vorschlag:').count(), 1)

    def test_pendenz_fuehrt_zur_fristansetzung(self):
        from core.models import Pendenz
        from core.services.zahlungsverzug import eskalation_257d
        from core.views.fw._basis import _pendenz_ziel
        eskalation_257d(self.r)
        p = Pendenz.objects.get(quelle__startswith='257d-vorschlag:')
        self.assertEqual(_pendenz_ziel(p)[0], f'/neu/vertraege/{self.v.id}/verzug/')

    def test_zahlung_vor_der_fristansetzung_erledigt_vorschlag_und_fall(self):
        from core.models import Pendenz
        from core.services.zahlungsverzug import eskalation_257d
        from faelle.models import Fall
        from finance.models import Zahlungseingang
        eskalation_257d(self.r)
        Zahlungseingang.objects.create(vertrag=self.v, debitoren_rechnung=self.r,
                                       betrag=Decimal('1700.00'))
        self.r.status = 'bezahlt'; self.r.save(update_fields=['status'])
        p = Pendenz.objects.get(quelle__startswith='257d-vorschlag:')
        self.assertTrue(p.erledigt, 'Die Vorschlags-Pendenz bleibt nach Zahlung offen.')
        self.assertEqual(Fall.objects.get(fallart__schluessel='zahlungsverzug').status,
                         Fall.ABGESCHLOSSEN)

    def test_fristansetzung_erledigt_den_vorschlag(self):
        from core.models import Pendenz
        from core.services.zahlungsverzug import eskalation_257d
        eskalation_257d(self.r)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{self.v.id}/verzug/',
               {'frist_bis': (self.heute + timedelta(days=37)).isoformat()}, secure=True)
        self.assertTrue(Pendenz.objects.get(quelle__startswith='257d-vorschlag:').erledigt)
        self.assertTrue(Pendenz.objects.filter(quelle=f'257d:{self.v.pk}', erledigt=False).exists())

    def test_mahngebuehr_loest_keine_eskalation_aus(self):
        from core.models import Pendenz
        from core.services.zahlungsverzug import eskalation_257d
        from finance.models import DebitorenRechnung
        g = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Mahngebühr', datum=self.heute - timedelta(days=70),
            faellig_am=self.heute - timedelta(days=70), betrag=Decimal('40'),
            stammrechnung=self.r)
        self.assertIsNone(eskalation_257d(g))
        self.assertFalse(Pendenz.objects.filter(quelle__startswith='257d-vorschlag:').exists())


class EinschreibenPflichtTests(TestCase):
    """Entscheid 30.09.2026: Die 257d-E-Mail ist nur die Kopie; das Original geht per Einschreiben."""

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = date.today()
        self.c = Client(); self.c.force_login(_team_user('Verwalter'))

    def _mail(self):
        return self.c.post(f'/vertrag/{self.v.id}/mahnung/mail/',
                           {'monat': '08/2026', 'betrag': '1700.00'}, secure=True)

    def test_mail_ist_als_kopie_beschriftet(self):
        self._mail()
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertIn('Kopie', m.subject)
        self.assertIn('Einschreiben', m.subject)
        html = m.alternatives[0][0]
        self.assertIn('Dies ist eine Kopie per E-Mail', html)
        self.assertIn('erst ab dem', html)

    def test_pendenz_fuer_den_eingeschriebenen_brief_entsteht_einmal(self):
        from core.models import Pendenz
        self._mail(); self._mail()
        p = Pendenz.objects.get(vertrag=self.v, quelle=f'257d-einschreiben:{self.v.pk}')
        self.assertEqual(p.faellig_am, self.heute + timedelta(days=2))
        self.assertEqual(Pendenz.objects.filter(quelle__startswith='257d-einschreiben:').count(), 1)

    def test_pendenz_fuehrt_zur_fristansetzung(self):
        from core.models import Pendenz
        from core.views.fw._basis import _pendenz_ziel
        self._mail()
        p = Pendenz.objects.get(quelle__startswith='257d-einschreiben:')
        self.assertEqual(_pendenz_ziel(p)[0], f'/neu/vertraege/{self.v.id}/verzug/')

    def test_fristansetzung_erledigt_die_einschreiben_pendenz(self):
        from core.models import Pendenz
        from finance.models import DebitorenRechnung
        DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Miete', datum=self.heute - timedelta(days=40),
            faellig_am=self.heute - timedelta(days=40), betrag=Decimal('1700.00'))
        self._mail()
        self.c.post(f'/neu/vertraege/{self.v.id}/verzug/',
                    {'frist_bis': (self.heute + timedelta(days=37)).isoformat(),
                     'sendungsnummer': '98.00.123456.00000001', 'versand_am': self.heute.isoformat()},
                    secure=True)
        self.assertTrue(Pendenz.objects.get(quelle__startswith='257d-einschreiben:').erledigt)
