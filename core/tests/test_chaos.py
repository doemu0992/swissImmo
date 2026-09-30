"""Chaos-Tests: Was passiert, wenn Systeme ausfallen oder Eingaben Unsinn sind?

Drei Gruppen:
  1. Ausfall mitten in einer Sammeloperation (Sollstellung) → sauberer Rollback.
  2. Ausfall der PDF-Erzeugung (RAM voll, Bibliothek stürzt ab) → kontrollierte
     Meldung, kein 500er mit Stacktrace, kein halb abgelegtes Dokument.
  3. Extreme Eingaben (Mietzins 0 / negativ / absurd, Einzug vor Baujahr,
     500-MB-Upload) → wird abgelehnt, bevor die Datenbank etwas sieht.

Jeder Test injiziert den Fehler selbst. Die Gegenprobe steht im PR
(`docs/CHAOS.md`): Schutz ausgebaut → Test rot.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError
from django.http import HttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from ._helfer import (Einheit, Liegenschaft, Mieter, Mietvertrag, _basis_objekte,
                      _seed_konten, _team_user, _test_organisation)


def _viele_vertraege(n):
    """`_basis_objekte` (1 Vertrag) plus n-1 weitere Einheiten mit je einem Vertrag."""
    lg, e, m, v = _basis_objekte()
    for i in range(n - 1):
        ei = Einheit.objects.create(liegenschaft=lg, bezeichnung=f'Whg {i}', typ='whg',
                                    nettomiete_aktuell=Decimal('1000'),
                                    nebenkosten_aktuell=Decimal('100'))
        mi = Mieter.objects.create(typ='person', vorname='M', nachname=f'Mieter{i}',
                                   strasse='x', plz='8000', ort='Zürich')
        Mietvertrag.objects.create(mieter=mi, einheit=ei, beginn=date(2024, 1, 1),
                                   netto_mietzins=Decimal('1000'), nebenkosten=Decimal('100'),
                                   status='aktiv')
    return lg


class SollstellungAusfallTests(TestCase):
    """Datenbank bricht mitten in der Massen-Sollstellung ab."""

    def setUp(self):
        _seed_konten()
        _viele_vertraege(30)

    def _zaehler(self):
        from finance.models import Buchung, DebitorenRechnung
        return DebitorenRechnung.objects.count(), Buchung.objects.count()

    def test_datenbankabbruch_in_der_mitte_rollt_alles_zurueck(self):
        from core.services.automation import run_sollstellung
        import finance.booking as booking
        echt = booking.buche
        aufrufe = {'n': 0}

        def fallend(*a, **kw):
            aufrufe['n'] += 1
            if aufrufe['n'] == 40:       # mitten in Vertrag ~10 von 30
                raise OperationalError('server closed the connection unexpectedly')
            return echt(*a, **kw)

        vorher = self._zaehler()
        with mock.patch.object(booking, 'buche', fallend):
            with self.assertRaises(OperationalError):
                run_sollstellung(2024, 3)
        # Es MUSSTE gebucht worden sein, bevor der Fehler kam — sonst prüft der Test nichts.
        self.assertGreaterEqual(aufrufe['n'], 40)
        # … und danach ist NICHTS davon übrig: keine Rechnung ohne Buchung, keine Buchung ohne Rechnung.
        self.assertEqual(self._zaehler(), vorher)

    def test_nach_abbruch_laeuft_der_zweite_lauf_vollstaendig_und_ohne_doppel(self):
        from core.services.automation import run_sollstellung
        import finance.booking as booking
        echt = booking.buche
        zaehl = {'n': 0}

        def fallend(*a, **kw):
            zaehl['n'] += 1
            if zaehl['n'] == 25:
                raise OperationalError('deadlock detected')
            return echt(*a, **kw)

        with mock.patch.object(booking, 'buche', fallend):
            with self.assertRaises(OperationalError):
                run_sollstellung(2024, 3)
        self.assertEqual(run_sollstellung(2024, 3), 30)
        self.assertEqual(run_sollstellung(2024, 3), 0)     # idempotent
        from finance.models import DebitorenRechnung
        self.assertEqual(DebitorenRechnung.objects.count(), 30)

    def test_fehlerhafter_einzelvertrag_blockiert_die_uebrigen_nicht(self):
        """Ein Vertrag mit unrechenbaren Daten darf 499 andere nicht verhindern."""
        from core.services.automation import run_sollstellung
        from decimal import InvalidOperation
        schlecht = Mietvertrag.objects.order_by('pk')[5]
        echt = Mietvertrag.effektiver_netto_mietzins

        def kaputt(self, *a, **kw):
            if self.pk == schlecht.pk:
                raise InvalidOperation('unrechenbar')
            return echt(self, *a, **kw)

        fehler = []
        with mock.patch.object(Mietvertrag, 'effektiver_netto_mietzins', kaputt):
            n = run_sollstellung(2024, 3, fehler=fehler)
        self.assertEqual(n, 29)
        self.assertEqual([f[0] for f in fehler], [schlecht.pk])
        # Nichts Halbes vom fehlerhaften Vertrag:
        from finance.models import Buchung, DebitorenRechnung
        self.assertFalse(DebitorenRechnung.objects.filter(vertrag=schlecht).exists())
        self.assertFalse(Buchung.objects.filter(debitoren_rechnung__vertrag=schlecht).exists())

    def test_view_zeigt_meldung_statt_500_bei_datenbankausfall(self):
        c = Client()
        c.force_login(_team_user())
        with mock.patch('core.services.automation.run_sollstellung',
                        side_effect=OperationalError('connection lost')):
            r = c.post('/neu/sollstellung/starten/', {'jahr': 2024, 'monat': 3})
        self.assertEqual(r.status_code, 302)
        meldungen = [str(m) for m in r.wsgi_request._messages]
        self.assertTrue(any('nichts wurde gebucht' in m.lower() for m in meldungen), meldungen)

    def test_view_meldet_uebersprungene_vertraege(self):
        from decimal import InvalidOperation
        schlecht = Mietvertrag.objects.order_by('pk')[2]
        echt = Mietvertrag.effektiver_netto_mietzins

        def kaputt(self, *a, **kw):
            if self.pk == schlecht.pk:
                raise InvalidOperation('unrechenbar')
            return echt(self, *a, **kw)

        c = Client()
        c.force_login(_team_user())
        with mock.patch.object(Mietvertrag, 'effektiver_netto_mietzins', kaputt):
            r = c.post('/neu/sollstellung/starten/', {'jahr': 2024, 'monat': 3})
        self.assertEqual(r.status_code, 302)
        meldungen = [str(m) for m in r.wsgi_request._messages]
        self.assertTrue(any('übersprungen' in m for m in meldungen), meldungen)


class PdfAusfallTests(TestCase):
    """PDF-Erzeugung: RAM voll, Bibliothek stürzt ab."""

    def setUp(self):
        _seed_konten()
        _lg, _e, _m, self.vertrag = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def test_speicher_voll_ergibt_pdf_fehler_statt_absturz(self):
        from core.services.pdf_service import PdfFehler, generate_vertrag_pdf_bytes
        with mock.patch('core.services.pdf_service.pisa.CreatePDF', side_effect=MemoryError()):
            with self.assertRaises(PdfFehler) as ctx:
                generate_vertrag_pdf_bytes(self.vertrag)
        # Die Ursache muss benannt sein – ein allgemeiner Renderer-Absturz waere
        # ein anderer Fall (die Gegenprobe ohne MemoryError-Zweig blieb sonst gruen).
        self.assertIn('Arbeitsspeicher', str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, MemoryError)

    def test_bibliothek_meldet_fehler_ergibt_pdf_fehler(self):
        from core.services.pdf_service import PdfFehler, generate_vertrag_pdf_bytes
        antwort = mock.Mock(err=3)
        with mock.patch('core.services.pdf_service.pisa.CreatePDF', return_value=antwort):
            with self.assertRaises(PdfFehler):
                generate_vertrag_pdf_bytes(self.vertrag)

    def test_download_view_antwortet_503_mit_klartext(self):
        with mock.patch('core.services.pdf_service.pisa.CreatePDF', side_effect=MemoryError()):
            r = self.c.get(f'/vertrag/{self.vertrag.pk}/pdf/')
        self.assertEqual(r.status_code, 503)
        self.assertIn('PDF', r.content.decode())
        self.assertNotIn('Traceback', r.content.decode())

    def test_absturz_legt_kein_halbes_dokument_ab(self):
        from rentals.models import Dokument
        vorher = Dokument.alle_organisationen.count()
        with mock.patch('core.services.pdf_service.pisa.CreatePDF', side_effect=MemoryError()):
            self.c.get(f'/vertrag/{self.vertrag.pk}/pdf/')
        self.assertEqual(Dokument.alle_organisationen.count(), vorher)

    def test_paket_meldet_fehlgeschlagene_teile(self):
        from core.views.pdf import erzeuge_und_ablege_vertragspaket
        with mock.patch('core.services.pdf_service.pisa.CreatePDF', side_effect=MemoryError()):
            paket = erzeuge_und_ablege_vertragspaket(self.vertrag)
        self.assertEqual(list(paket), [])
        self.assertTrue(paket.fehler, 'Fehlgeschlagene Dokumente müssen benannt werden')

    def test_zip_view_503_wenn_gar_nichts_entsteht(self):
        with mock.patch('core.services.pdf_service.pisa.CreatePDF', side_effect=MemoryError()):
            r = self.c.get(f'/vertrag/{self.vertrag.pk}/dokumente-zip/')
        self.assertEqual(r.status_code, 503)

    def test_riesiger_freitext_sprengt_den_speicher_nicht(self):
        """50 MB «Besondere Vereinbarungen» dürfen nicht in den PDF-Renderer laufen."""
        from core.services.pdf_service import PdfFehler, generate_vertrag_pdf_bytes
        self.vertrag.besondere_vereinbarungen = 'x' * (50 * 1024 * 1024)
        with mock.patch('core.services.pdf_service.pisa.CreatePDF') as pdf:
            with self.assertRaises(PdfFehler):
                generate_vertrag_pdf_bytes(self.vertrag)
        pdf.assert_not_called()


class VertragEingabeTests(TestCase):
    """Extremwerte im Vertragsassistenten."""

    def setUp(self):
        _seed_konten()
        self.lg, self.einheit, self.mieter, _v = _basis_objekte()
        self.lg.baujahr = 1990
        self.lg.save(update_fields=['baujahr'])
        Mietvertrag.objects.all().delete()
        self.c = Client()
        self.c.force_login(_team_user())

    def _post(self, **ueber):
        daten = {'einheit_id': self.einheit.pk, 'mieter_id': self.mieter.pk,
                 'beginn': '2026-10-01', 'netto_mietzins': '1500', 'nebenkosten': '200'}
        daten.update(ueber)
        return self.c.post('/neu/vertraege/neu/speichern/', daten)

    def _abgelehnt(self, r, feld):
        self.assertEqual(r.status_code, 400, r.content[:300])
        self.assertEqual(Mietvertrag.objects.count(), 0)
        self.assertIn(feld, r.context['feld_fehler'])

    def test_negativer_mietzins(self):
        self._abgelehnt(self._post(netto_mietzins='-500'), 'netto_mietzins')

    def test_absurd_hoher_mietzins_wuerde_postgres_sprengen(self):
        # Feld ist DecimalField(8, 2): SQLite speichert 10^12, PostgreSQL wirft einen Serverfehler.
        self._abgelehnt(self._post(netto_mietzins='1000000000000'), 'netto_mietzins')

    def test_nan_und_unendlich_sind_kein_mietzins(self):
        for wert in ('NaN', 'Infinity', '-Infinity', 'sNaN'):
            with self.subTest(wert=wert):
                self._abgelehnt(self._post(netto_mietzins=wert), 'netto_mietzins')

    def test_exponentenschreibweise_1e999(self):
        self._abgelehnt(self._post(netto_mietzins='1e999'), 'netto_mietzins')

    def test_nebenkosten_negativ_und_absurd(self):
        self._abgelehnt(self._post(nebenkosten='-1'), 'nebenkosten')
        self._abgelehnt(self._post(nebenkosten='99999999'), 'nebenkosten')

    def test_einzug_vor_baujahr_der_liegenschaft(self):
        self._abgelehnt(self._post(beginn='1985-01-01'), 'beginn')

    def test_einzug_im_jahr_1900_oder_9999(self):
        self._abgelehnt(self._post(beginn='0001-01-01'), 'beginn')
        self._abgelehnt(self._post(beginn='9999-12-31'), 'beginn')

    def test_kaution_negativ_und_absurd(self):
        self._abgelehnt(self._post(kautions_betrag='-4500'), 'kautions_betrag')
        self._abgelehnt(self._post(kautions_betrag='1e12'), 'kautions_betrag')

    def test_personenzahl_absurd(self):
        self._abgelehnt(self._post(anzahl_personen='99999999999'), 'anzahl_personen')
        self._abgelehnt(self._post(anzahl_personen='-3'), 'anzahl_personen')

    def test_mietzins_null_wird_gespeichert_aber_gewarnt(self):
        """0 CHF ist ein legitimer Fall (Hauswartwohnung, Gratisparkplatz) — Warnung, kein Verbot."""
        r = self._post(netto_mietzins='0', nebenkosten='0')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Mietvertrag.objects.count(), 1)
        meldungen = [str(m) for m in r.wsgi_request._messages]
        self.assertTrue(any('CHF 0' in m for m in meldungen), meldungen)

    def test_gueltiger_vertrag_geht_durch(self):
        r = self._post()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Mietvertrag.objects.count(), 1)

    def test_neuer_mieter_bleibt_nicht_als_waise_zurueck_wenn_speichern_scheitert(self):
        anzahl = Mieter.objects.count()
        with mock.patch('rentals.models.Mietvertrag.objects.create',
                        side_effect=OperationalError('disk full')):
            r = self._post(mieter_id='', mieter_typ='person', nachname='Neu', vorname='Nina')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Mieter.objects.count(), anzahl, 'Waisen-Mieter nach fehlgeschlagenem Speichern')

    def test_bearbeitungsformular_lehnt_baujahr_und_absurde_werte_ab(self):
        from rentals.forms import VertragBearbeitenForm
        einheit = self.einheit
        form = VertragBearbeitenForm({'beginn': '1985-01-01', 'netto_mietzins': '1500'},
                                     entwurf=True, beginn=date(2026, 1, 1), einheit=einheit)
        self.assertFalse(form.is_valid())
        self.assertIn('beginn', form.errors)
        form = VertragBearbeitenForm({'netto_mietzins': '1e12'}, entwurf=True,
                                     beginn=date(2026, 1, 1), einheit=einheit)
        self.assertFalse(form.is_valid())


class UploadGrenzenTests(TestCase):
    """500-MB-PDF und andere Dateien, die nicht hineingehören."""

    def setUp(self):
        _seed_konten()
        self.lg, self.einheit, _m, self.vertrag = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def _gross(self, name='mangel.pdf', mb=None):
        """Eine Datei mit ECHTEN Bytes über der (im Test gesenkten) Grenze.

        Der Testclient kodiert Dateien neu; ein behauptetes `.size` überlebte
        den Weg durch die View nicht. Darum bleibt die Datei klein und die
        Grenze wird gesenkt (`_grenzen`).
        """
        return SimpleUploadedFile(name, b'%PDF-1.4\n' + b'0' * 4096, content_type='application/pdf')

    def _grenzen(self):
        """Alle Upload-Grenzen auf 1 kB — eine 4-kB-Datei ist dann «zu gross»."""
        from contextlib import ExitStack
        stack = ExitStack()
        for name in ('MAX_BILD_BYTES', 'MAX_DOKUMENT_BYTES', 'MAX_ABLAGE_BYTES'):
            stack.enter_context(mock.patch(f'core.utils.uploads.{name}', 1024))
        return stack

    def test_middleware_weist_500_mb_anfrage_ab_bevor_der_body_gelesen_wird(self):
        from core.middleware_upload import UploadGrenzeMiddleware
        gelesen = {'ja': False}

        def antwort(request):
            gelesen['ja'] = True
            return HttpResponse('ok')

        req = RequestFactory().post('/neu/dokumente/neu/', data={'a': 'b'})
        req.META['CONTENT_LENGTH'] = str(500 * 1024 * 1024)
        r = UploadGrenzeMiddleware(antwort)(req)
        self.assertEqual(r.status_code, 413)
        self.assertFalse(gelesen['ja'], 'Body darf nicht mehr verarbeitet werden')

    def test_middleware_laesst_normale_anfragen_durch(self):
        from core.middleware_upload import UploadGrenzeMiddleware
        req = RequestFactory().post('/x/', data={'a': 'b'})
        r = UploadGrenzeMiddleware(lambda request: HttpResponse('ok'))(req)
        self.assertEqual(r.status_code, 200)

    def test_middleware_ist_eingebunden(self):
        from django.conf import settings
        self.assertIn('core.middleware_upload.UploadGrenzeMiddleware', settings.MIDDLEWARE)

    def test_dokument_upload_lehnt_uebergrosse_datei_ab(self):
        from portfolio.models import Dokument
        vorher = Dokument.alle_organisationen.count()
        with self._grenzen():
            r = self.c.post('/neu/dokumente/neu/', {'datei': self._gross(), 'titel': 'Riese',
                                                    'liegenschaft_id': self.lg.pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Dokument.alle_organisationen.count(), vorher)

    def test_dokument_upload_lehnt_getarnte_datei_ab(self):
        from portfolio.models import Dokument
        vorher = Dokument.alle_organisationen.count()
        falsch = SimpleUploadedFile('vertrag.pdf', b'<?php echo 1; ?>', content_type='application/pdf')
        self.c.post('/neu/dokumente/neu/', {'datei': falsch, 'titel': 'Fake', 'liegenschaft_id': self.lg.pk})
        self.assertEqual(Dokument.alle_organisationen.count(), vorher)

    def test_dokument_upload_ohne_objektbezug_ist_kein_serverfehler(self):
        """Die Datenbank verlangt Liegenschaft ODER Objekt (CHECK) — vorher HTTP 500."""
        from portfolio.models import Dokument
        vorher = Dokument.alle_organisationen.count()
        ok = SimpleUploadedFile('ok.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
        r = self.c.post('/neu/dokumente/neu/', {'datei': ok, 'titel': 'Ohne Bezug'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Dokument.alle_organisationen.count(), vorher)

    def test_dokument_upload_nimmt_echtes_pdf(self):
        from portfolio.models import Dokument
        vorher = Dokument.alle_organisationen.count()
        ok = SimpleUploadedFile('ok.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
        self.c.post('/neu/dokumente/neu/', {'datei': ok, 'titel': 'Echt', 'liegenschaft_id': self.lg.pk})
        self.assertEqual(Dokument.alle_organisationen.count(), vorher + 1)

    def test_schaden_erfassen_prueft_fotos(self):
        from tickets.models import SchadenFoto
        falsch = SimpleUploadedFile('x.jpg', b'kein bild', content_type='image/jpeg')
        r = self.c.post('/neu/schaeden/neu/', {'titel': 'Riss', 'liegenschaft_id': self.lg.pk,
                                                'fotos': [falsch]})
        self.assertIn(r.status_code, (200, 302))
        self.assertEqual(SchadenFoto.objects.count(), 0)

    def test_schaden_erfassen_lehnt_riesenbild_ab(self):
        from tickets.models import SchadenFoto
        riese = self._gross('foto.jpg')
        with self._grenzen():
            self.c.post('/neu/schaeden/neu/', {'titel': 'Riss', 'liegenschaft_id': self.lg.pk,
                                               'fotos': [riese]})
        self.assertEqual(SchadenFoto.objects.count(), 0)

    def test_kautionszertifikat_wird_geprueft(self):
        vorher = Mietvertrag.objects.get(pk=self.vertrag.pk).kautions_zertifikat
        riese = self._gross('police.pdf')
        with self._grenzen():
            self.c.post(f'/neu/vertraege/{self.vertrag.pk}/kaution/',
                        {'aktion': 'versicherung', 'kautions_versicherer': 'X',
                         'kautions_zertifikat': riese})
        self.vertrag.refresh_from_db()
        self.assertEqual(self.vertrag.kautions_zertifikat, vorher)


class UploadValidatorTests(SimpleTestCase):
    def test_pdf_ablage_grenzen(self):
        from core.utils.uploads import validiere_dokument
        f = SimpleUploadedFile('a.pdf', b'%PDF-1.4')
        f.size = 500 * 1024 * 1024
        ok, fehler = validiere_dokument(f)
        self.assertFalse(ok)
        self.assertIn('gross', fehler)

    def test_ablage_erlaubt_office_aber_keine_ausfuehrbaren_dateien(self):
        from core.utils.uploads import validiere_ablage
        self.assertTrue(validiere_ablage(SimpleUploadedFile('a.docx', b'PK\x03\x04...'))[0])
        self.assertFalse(validiere_ablage(SimpleUploadedFile('a.exe', b'MZ'))[0])
        self.assertFalse(validiere_ablage(SimpleUploadedFile('a.html', b'<script>'))[0])
        self.assertFalse(validiere_ablage(SimpleUploadedFile('a.svg', b'<svg onload=1>'))[0])

    def test_dateiname_mit_pfadtrick(self):
        from core.utils.uploads import validiere_ablage
        self.assertFalse(validiere_ablage(SimpleUploadedFile('../../etc/passwd.pdf', b'nix'))[0])
