"""Testmodul kreditoren — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 12 Klassen, unveraendert uebernommen."""
from datetime import date
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (_test_organisation,
    _team_user, _basis_objekte, Mieter, Organisation, Liegenschaft, Einheit,
    Mietvertrag)



class WeiterverrechnungTests(TestCase):
    """Geführte Weiterverrechnung: Verknüpfung + ertragsneutrale Buchung über 1190."""

    def _kreditor(self, betrag='500', konto='4000'):
        from finance.models import KreditorenRechnung
        from finance.booking import konto as _k
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(
            lieferant='Sanitär AG', betrag=Decimal(betrag), status='bezahlt',
            liegenschaft=lg, konto=_k(konto))
        return lg, e, m, v, k

    def test_weiterverrechnung_verknuepft_und_neutral(self):
        from finance.models import DebitorenRechnung, Buchung
        lg, e, m, v, k = self._kreditor('500')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/',
                   {'vertrag_id': v.id, 'betrag': '500', 'zuschlag': '0', 'titel': 'Rohrbruch'})
        self.assertIn(r.status_code, (200, 302))
        deb = DebitorenRechnung.objects.filter(quell_kreditor=k).first()
        self.assertIsNotNone(deb)
        self.assertEqual(deb.betrag, Decimal('500.00'))
        # Ertragsneutral: 1100/1190 + 1190/4000 → 1190 netto 0, Aufwand gemindert
        self.assertTrue(Buchung.objects.filter(debitoren_rechnung=deb, soll_konto__nummer='1100', haben_konto__nummer='1190').exists())
        self.assertTrue(Buchung.objects.filter(debitoren_rechnung=deb, soll_konto__nummer='1190', haben_konto__nummer='4000').exists())
        # Kreditor ist voll weiterverrechnet
        k.refresh_from_db()
        self.assertEqual(k.offen_weiterzuverrechnen, Decimal('0.00'))

    def test_zuschlag_wird_als_ertrag_gebucht(self):
        from finance.models import DebitorenRechnung, Buchung
        lg, e, m, v, k = self._kreditor('500')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/',
               {'vertrag_id': v.id, 'betrag': '500', 'zuschlag': '50'})
        deb = DebitorenRechnung.objects.filter(quell_kreditor=k).first()
        self.assertEqual(deb.betrag, Decimal('550.00'))
        self.assertTrue(Buchung.objects.filter(debitoren_rechnung=deb, soll_konto__nummer='1100', haben_konto__nummer='3600', betrag=Decimal('50.00')).exists())

    def test_begrenzt_auf_offenen_anteil(self):
        from finance.models import DebitorenRechnung
        lg, e, m, v, k = self._kreditor('500')
        c = Client(); c.force_login(_team_user())
        # erst 300 weiterverrechnen
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/', {'vertrag_id': v.id, 'betrag': '300', 'zuschlag': '0'})
        k.refresh_from_db()
        self.assertEqual(k.offen_weiterzuverrechnen, Decimal('200.00'))
        # dann 999 versuchen → auf 200 begrenzt
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/', {'vertrag_id': v.id, 'betrag': '999', 'zuschlag': '0'})
        k.refresh_from_db()
        self.assertEqual(k.offen_weiterzuverrechnen, Decimal('0.00'))


class KreditorZahllaufTests(TestCase):
    """pain.001-Zahllauf: enthaltene Rechnungen → 'in Zahlung' (kein Doppelzahlen)."""

    def _setup(self):
        from crm.models import Organisation
        from finance.models import KreditorenRechnung
        from finance.booking import konto as _k
        _test_organisation(firma='V AG', iban='CH9300762011623852957')
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(
            lieferant='Elektro AG', betrag=Decimal('800'), status='freigegeben',
            liegenschaft=lg, konto=_k('4000'),
            iban='CH9300762011623852957', referenz='R-1')
        return lg, k

    def test_pain001_markiert_in_zahlung(self):
        from finance.models import KreditorenRechnung
        lg, k = self._setup()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.get('/neu/kreditoren/pain001/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('xml', r['Content-Type'])
        k.refresh_from_db()
        self.assertEqual(k.status, 'in_zahlung')
        # Zweiter Lauf enthält sie NICHT mehr → keine freigegebenen mehr
        r2 = c.get('/neu/kreditoren/pain001/')
        self.assertEqual(r2.status_code, 302)   # keine freigegebenen → Redirect mit Fehler

    def test_bestaetigen_bucht_aus(self):
        from finance.models import KreditorenRechnung, Buchung
        lg, k = self._setup()
        k.status = 'in_zahlung'; k.save()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.id})
        k.refresh_from_db()
        self.assertEqual(k.status, 'bezahlt')
        self.assertTrue(Buchung.objects.filter(kreditoren_rechnung=k, soll_konto__nummer='2000', haben_konto__nummer='1020').exists())

    def test_zuruecksetzen(self):
        from finance.models import KreditorenRechnung
        lg, k = self._setup()
        k.status = 'in_zahlung'; k.save()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/kreditoren/{k.id}/zahlung-zuruecksetzen/')
        k.refresh_from_db()
        self.assertEqual(k.status, 'freigegeben')

    def test_teilzahlung_op(self):
        from finance.models import Buchung, KreditorenZahlung
        lg, k = self._setup()   # betrag 800, freigegeben
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        # Teilzahlung 300
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.id, 'betrag': '300'})
        k.refresh_from_db()
        self.assertEqual(k.status, 'teilbezahlt')
        self.assertEqual(k.offener_betrag, Decimal('500.00'))
        self.assertTrue(Buchung.objects.filter(kreditoren_rechnung=k, betrag=Decimal('300.00'),
                                               soll_konto__nummer='2000', haben_konto__nummer='1020').exists())
        # Restzahlung 500 → bezahlt
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.id, 'betrag': '500'})
        k.refresh_from_db()
        self.assertEqual(k.status, 'bezahlt')
        self.assertEqual(k.offener_betrag, Decimal('0.00'))
        self.assertEqual(KreditorenZahlung.objects.filter(kreditor=k, status='verbucht').count(), 2)

    def test_ueberzahlung_begrenzt(self):
        lg, k = self._setup()
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.id, 'betrag': '9999'})
        k.refresh_from_db()
        self.assertEqual(k.status, 'bezahlt')
        self.assertEqual(k.bezahlt_betrag, Decimal('800.00'))   # auf offen begrenzt


class LieferantenkontenTests(TestCase):
    """Lieferantenkonten (Kreditoren): pro Lieferant offener Betrag + Kontoblatt."""

    def _setup(self):
        from finance.models import KreditorenRechnung, KreditorenZahlung
        from finance.booking import konto as _k
        lg, e, m, v = _basis_objekte()
        # Sanitär AG: 2 Rechnungen (800 offen + 300 bezahlt via Zahlung)
        KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('800'),
                                          status='freigegeben', liegenschaft=lg, konto=_k('4000'),
                                          datum=date(2025, 1, 5))
        k2 = KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('300'),
                                               status='bezahlt', liegenschaft=lg, konto=_k('4000'),
                                               datum=date(2025, 1, 10))
        KreditorenZahlung.objects.create(kreditor=k2, betrag=Decimal('300'), datum=date(2025, 1, 20),
                                         konto=_k('1020'), status='verbucht', bemerkung='Zahlung R2')
        # Elektro AG: 1 offene Rechnung
        KreditorenRechnung.objects.create(lieferant='Elektro AG', betrag=Decimal('500'),
                                          status='neu', liegenschaft=lg, konto=_k('4000'),
                                          datum=date(2025, 1, 8))
        return lg

    def test_uebersicht_gruppiert_und_saldo(self):
        lg = self._setup()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/lieferantenkonten/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Sanitär AG')
        self.assertContains(r, 'Elektro AG')
        # total offen = 800 (Sanitär Rest) + 500 (Elektro) = 1300
        self.assertEqual(r.context['total_offen'], Decimal('1300.00'))
        self.assertEqual(r.context['offen_n'], 2)
        # Sanitär-Zeile: 2 Rechnungen, offen 800
        san = next(g for g in r.context['rows'] if g['name'] == 'Sanitär AG')
        self.assertEqual(san['anzahl'], 2)
        self.assertEqual(san['offen'], Decimal('800.00'))
        self.assertEqual(san['volumen'], Decimal('1100.00'))

    def test_kontoblatt_bewegungen_und_saldo(self):
        lg = self._setup()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/lieferantenkonto/?name=Sanit%C3%A4r+AG')
        self.assertEqual(r.status_code, 200)
        # 2 Rechnungen (800+300) belastung, 1 Zahlung 300 → Endsaldo 800
        self.assertEqual(r.context['total_belastung'], Decimal('1100.00'))
        self.assertEqual(r.context['total_zahlung'], Decimal('300.00'))
        self.assertEqual(r.context['endsaldo'], Decimal('800.00'))
        # laufender Saldo der letzten Bewegung = Endsaldo
        self.assertEqual(r.context['bewegungen'][-1]['saldo'], Decimal('800.00'))
        # 1 offener Posten (die 800er Rechnung)
        self.assertEqual(len(r.context['op_rows']), 1)
        self.assertEqual(r.context['op_total'], Decimal('800.00'))

    def test_filter_nur_offen(self):
        lg = self._setup()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/lieferantenkonten/?filter=offen')
        self.assertEqual(len(r.context['rows']), 2)   # beide haben offene Posten


class KIRechnungsscannerTests(TestCase):
    """KI-Rechnungsscanner in /neu/: Scan direkt beim Upload, Methode sichtbar,
    Werte korrigierbar. Ohne GROQ-Key läuft die regelbasierte Erkennung."""
    def setUp(self):
        # Seit Etappe 5 (PR 6) gehoert der Kontenplan der Verwaltung. Diese
        # Klasse bucht, ohne vorher eine anzulegen — dann ist nicht bestimmt,
        # wessen Konto 1020 gemeint ist, und `finance.booking` sagt das auch.
        _test_organisation()


    def _text_pdf(self):
        import io
        from reportlab.pdfgen import canvas as _c
        buf = io.BytesIO()
        c = _c.Canvas(buf)
        c.drawString(72, 800, "Muster Sanitaer AG")
        c.drawString(72, 780, "Rechnung Nr. 2026-042 vom 15.03.2026")
        c.drawString(72, 760, "Total CHF 350.00")
        c.drawString(72, 740, "IBAN CH93 0076 2011 6238 5295 7")
        c.save()
        return buf.getvalue()

    def test_seite_zeigt_scanner_und_edit(self):
        from finance.models import KreditorenRechnung
        KreditorenRechnung.objects.create(lieferant='Alt AG', betrag=Decimal('100'), status='neu')
        c = Client(); c.force_login(_team_user())
        body = c.get('/neu/kreditoren/').content.decode()
        self.assertIn('KI-Rechnungsscanner', body)
        self.assertIn('/neu/kreditoren/scan/', body)
        self.assertIn('kedit-', body)                     # Inline-Bearbeiten für Status Neu
        self.assertIn('/bearbeiten/', body)

    def test_scan_upload_regex_ohne_key(self):
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('rechnung.pdf', self._text_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            r = c.post('/neu/kreditoren/scan/', {'beleg_scan': f})
        self.assertEqual(r.status_code, 302)
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.status, 'neu')
        self.assertEqual(k.betrag, Decimal('350.00'))
        self.assertEqual(k.iban, 'CH9300762011623852957')
        self.assertEqual(k.datum, date(2026, 3, 15))
        self.assertIn('Muster Sanitaer AG', k.lieferant)
        # Regex-Methode → Hinweis am Datensatz (in der Edit-Zeile sichtbar)
        self.assertIn('prüfen', k.fehlermeldung)

    def test_scan_upload_mit_ki_mock(self):
        from unittest.mock import patch, MagicMock
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        import json as _json
        antwort = MagicMock()
        antwort.raise_for_status.return_value = None
        antwort.json.return_value = {'choices': [{'message': {'content': _json.dumps({
            'lieferant': 'Elektro Muster GmbH', 'betrag': 1234.55,
            'datum': '2026-05-02', 'referenz': 'RF18539007547034', 'iban': 'CH9300762011623852957',
        })}}]}
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('rechnung.pdf', self._text_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY='test-key'), \
             patch('finance.utils.requests.post', return_value=antwort) as mocked:
            c.post('/neu/kreditoren/scan/', {'beleg_scan': f})
            # Aktuelles Modell wird verwendet (llama3-8b-8192 ist abgeschaltet)
            self.assertEqual(mocked.call_args.kwargs['json']['model'], 'llama-3.3-70b-versatile')
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.lieferant, 'Elektro Muster GmbH')
        self.assertEqual(k.betrag, Decimal('1234.55'))
        self.assertEqual(k.datum, date(2026, 5, 2))
        self.assertEqual(k.fehlermeldung, '')            # KI-Erkennung → kein Hinweis

    def test_bild_ohne_key_ergibt_hinweis(self):
        from django.test import override_settings
        from finance.utils import scan_beleg
        import tempfile, os as _os
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as fh:
            fh.write(b'\xff\xd8\xff\xe0fakejpg')
            pfad = fh.name
        try:
            with override_settings(GROQ_API_KEY=None):
                d = scan_beleg(pfad)
            self.assertEqual(d['methode'], 'leer')
            self.assertIn('GROQ_API_KEY', d['hinweis'])
        finally:
            _os.unlink(pfad)

    def test_kreditor_bearbeiten_nur_status_neu(self):
        from finance.models import KreditorenRechnung
        k = KreditorenRechnung.objects.create(lieferant='Scan AG', betrag=Decimal('100'), status='neu')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/bearbeiten/', {
            'lieferant': 'Scan AG korrigiert', 'betrag': '425.50',
            'datum': '2026-06-01', 'referenz': 'R-77', 'iban': 'CH93 0076 2011 6238 5295 7',
        })
        k.refresh_from_db()
        self.assertEqual(k.lieferant, 'Scan AG korrigiert')
        self.assertEqual(k.betrag, Decimal('425.50'))
        self.assertEqual(k.iban, 'CH9300762011623852957')
        # Verbuchte Rechnung ist gesperrt
        k.status = 'freigegeben'; k.save()
        c.post(f'/neu/kreditoren/{k.id}/bearbeiten/', {'lieferant': 'Hack', 'betrag': '1'})
        k.refresh_from_db()
        self.assertEqual(k.lieferant, 'Scan AG korrigiert')

    def test_scan_upload_ohne_liegenschaft_leerer_string(self):
        """Regression: '— später zuordnen —' postet liegenschaft_id='' — darf
        keinen 500er werfen (Field 'id' expected a number but got '')."""
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('rechnung.pdf', self._text_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            r = c.post('/neu/kreditoren/scan/', {'beleg_scan': f, 'liegenschaft_id': ''})
        self.assertEqual(r.status_code, 302)
        k = KreditorenRechnung.objects.latest('id')
        self.assertIsNone(k.liegenschaft_id)

    def test_kreditor_neu_ohne_liegenschaft_leerer_string(self):
        """Gleiche Regression im manuellen Erfassen-Formular ('— keine —')."""
        from finance.models import KreditorenRechnung
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/kreditoren/neu/', {
            'lieferant': 'Leer AG', 'betrag': '99.00', 'liegenschaft_id': '',
        })
        self.assertEqual(r.status_code, 302)
        k = KreditorenRechnung.objects.get(lieferant='Leer AG')
        self.assertIsNone(k.liegenschaft_id)

    def test_mehrfach_upload(self):
        """Mehrere Belege in einem Rutsch → je Beleg eine Rechnung."""
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        vorher = KreditorenRechnung.objects.count()
        c = Client(); c.force_login(_team_user())
        f1 = SimpleUploadedFile('r1.pdf', self._text_pdf(), content_type='application/pdf')
        f2 = SimpleUploadedFile('r2.pdf', self._text_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            r = c.post('/neu/kreditoren/scan/', {'beleg_scan': [f1, f2]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(KreditorenRechnung.objects.count(), vorher + 2)

    def test_zeile_klickbar_und_beleg_vorschau(self):
        """Zeile (Status Neu) ist klickbar; Edit-Panel zeigt die Beleg-Vorschau."""
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('vorschau.pdf', self._text_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            c.post('/neu/kreditoren/scan/', {'beleg_scan': f})
        body = c.get('/neu/kreditoren/').content.decode()
        self.assertIn('fwKZeile', body)                      # Klick-Handler
        self.assertIn('cursor-pointer', body)                # Zeile klickbar
        self.assertIn('Beleg-Vorschau', body)                # Vorschau im Edit-Panel
        self.assertIn('type="application/pdf"', body)        # PDF-Embed
        self.assertIn('multiple', body)                      # Mehrfach-Upload-Input

    def test_rechnungsmail_import(self):
        """E-Mail mit PDF-Anhang → Rechnung mit gescannten Werten + Herkunft."""
        from django.test import override_settings
        from email.message import EmailMessage
        from core.services.belegimport import importiere_rechnungsmail
        from finance.models import KreditorenRechnung
        msg = EmailMessage()
        msg['From'] = 'Hans Handwerker <hans@sanitaer-muster.ch>'
        msg['Subject'] = 'Rechnung Reparatur'
        msg.set_content('Anbei die Rechnung. Gruss Hans')
        msg.add_attachment(self._text_pdf(), maintype='application', subtype='pdf',
                           filename='rechnung_reparatur.pdf')
        with override_settings(GROQ_API_KEY=None):
            rechnungen = importiere_rechnungsmail(msg)
        self.assertEqual(len(rechnungen), 1)
        k = rechnungen[0]
        self.assertEqual(k.status, 'neu')
        self.assertEqual(k.betrag, Decimal('350.00'))
        self.assertEqual(k.iban, 'CH9300762011623852957')
        self.assertIn('Per E-Mail von hans@sanitaer-muster.ch', k.fehlermeldung)

    def test_rechnungsmail_ohne_anhang(self):
        from email.message import EmailMessage
        from core.services.belegimport import importiere_rechnungsmail
        msg = EmailMessage()
        msg['From'] = 'x@y.ch'
        msg.set_content('Nur Text, kein Anhang')
        self.assertEqual(importiere_rechnungsmail(msg), [])

    def test_lieferantenkonto_zeigt_verlauf(self):
        """Erstellen/Löschen von Kreditorenrechnungen erscheint im Verlauf des
        Lieferantenkontos (Abgleich über den Lieferantennamen)."""
        from finance.models import KreditorenRechnung
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/neu/', {'lieferant': 'Verlauf AG', 'betrag': '200.00'})
        k = KreditorenRechnung.objects.get(lieferant='Verlauf AG')
        c.post(f'/neu/kreditoren/{k.id}/loeschen/')
        body = c.get('/neu/lieferantenkonto/?name=Verlauf AG').content.decode()
        self.assertIn('Verlauf — wer hat was gemacht', body)
        self.assertIn('Kreditorenrechnung erfasst', body)
        self.assertIn('Kreditorenrechnung gelöscht', body)

    def test_mailimport_loggt_aktivitaet(self):
        """Mail-Import schreibt einen System-Eintrag ins Aktivitätslog."""
        from django.test import override_settings
        from email.message import EmailMessage
        from core.services.belegimport import importiere_rechnungsmail
        from core.models import AktivitaetsLog
        msg = EmailMessage()
        msg['From'] = 'log@handwerk.ch'
        msg.set_content('Rechnung anbei')
        msg.add_attachment(self._text_pdf(), maintype='application', subtype='pdf',
                           filename='r.pdf')
        with override_settings(GROQ_API_KEY=None):
            importiere_rechnungsmail(msg)
        e = AktivitaetsLog.objects.filter(aktion='Rechnung per E-Mail eingegangen').first()
        self.assertIsNotNone(e)
        self.assertIsNone(e.benutzer_id)
        self.assertIn('log@handwerk.ch', e.details)


class HnkAutoAbleitungTests(TestCase):
    """NK-Relevanz der Kreditorenrechnung folgt automatisch dem Konto:
    HNK-Konto (4100–4140/4400) ⇒ Rechnung fliesst in die NK-Abrechnung —
    kein vergessenes Häkchen mehr. Checkbox kann zusätzlich aktivieren."""
    def setUp(self):
        # Seit Etappe 5 (PR 6) gehoert der Kontenplan der Verwaltung. Diese
        # Klasse bucht, ohne vorher eine anzulegen — dann ist nicht bestimmt,
        # wessen Konto 1020 gemeint ist, und `finance.booking` sagt das auch.
        _test_organisation()


    def _konto(self, nummer):
        from finance.booking import konto
        return konto(nummer)

    def test_erfassen_mit_hnk_konto_setzt_flag(self):
        from finance.models import KreditorenRechnung
        heiz = self._konto('4100')   # Heizkosten, is_hnk_relevant=True
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/neu/', {
            'lieferant': 'Öl AG', 'betrag': '900.00', 'konto_id': heiz.id,
            # Checkbox bewusst NICHT gesetzt
        })
        k = KreditorenRechnung.objects.get(lieferant='Öl AG')
        self.assertTrue(k.is_hnk_relevant)

    def test_erfassen_mit_unterhalt_konto_ohne_haekchen_bleibt_false(self):
        from finance.models import KreditorenRechnung
        unterhalt = self._konto('4000')   # Unterhalt, is_hnk_relevant=False
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/neu/', {
            'lieferant': 'Maler AG', 'betrag': '500.00', 'konto_id': unterhalt.id,
        })
        k = KreditorenRechnung.objects.get(lieferant='Maler AG')
        self.assertFalse(k.is_hnk_relevant)

    def test_freigabe_mit_hnk_konto_setzt_flag(self):
        from finance.models import KreditorenRechnung
        heiz = self._konto('4100')
        k = KreditorenRechnung.objects.create(lieferant='Wasser AG', betrag=Decimal('300'),
                                              status='neu')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/freigeben/', {'konto_id': heiz.id})
        k.refresh_from_db()
        self.assertEqual(k.status, 'freigegeben')
        self.assertTrue(k.is_hnk_relevant)

    def test_bearbeiten_checkbox_und_konto(self):
        from finance.models import KreditorenRechnung
        unterhalt = self._konto('4000')
        k = KreditorenRechnung.objects.create(lieferant='Mix AG', betrag=Decimal('100'),
                                              status='neu', is_hnk_relevant=True)
        c = Client(); c.force_login(_team_user())
        # Nicht-HNK-Konto + Checkbox aus → Flag wird entfernt
        c.post(f'/neu/kreditoren/{k.id}/bearbeiten/', {
            'lieferant': 'Mix AG', 'betrag': '100', 'konto_id': unterhalt.id,
        })
        k.refresh_from_db()
        self.assertFalse(k.is_hnk_relevant)
        # Checkbox an → Flag trotz Nicht-HNK-Konto gesetzt (manuelle Wahl)
        c.post(f'/neu/kreditoren/{k.id}/bearbeiten/', {
            'lieferant': 'Mix AG', 'betrag': '100', 'konto_id': unterhalt.id,
            'is_hnk_relevant': 'on',
        })
        k.refresh_from_db()
        self.assertTrue(k.is_hnk_relevant)

    def test_konto_select_synct_checkbox_live(self):
        """Aufwandskonto-Optionen tragen data-hnk; JS hakt die HNK-Checkbox
        beim Wählen eines NK-Kontos (z.B. Allgemeinstrom) sichtbar an."""
        from finance.booking import ensure_kontenplan
        from finance.models import KreditorenRechnung
        ensure_kontenplan()
        KreditorenRechnung.objects.create(lieferant='Sync AG', betrag=Decimal('50'), status='neu')
        c = Client(); c.force_login(_team_user())
        body = c.get('/neu/kreditoren/').content.decode()
        self.assertIn('function fwHnkSync', body)
        self.assertIn('data-hnk="1"', body)
        self.assertIn('onchange="fwHnkSync(this)"', body)

    def _qr_pdf(self):
        """Text-PDF mit QR-Zahlteil: Rechnungsnummer UND echte QR-Referenz/QR-IBAN."""
        import io
        from reportlab.pdfgen import canvas as _c
        buf = io.BytesIO()
        c = _c.Canvas(buf)
        c.drawString(72, 800, "BKW Energie AG")
        c.drawString(72, 780, "Rechnung Nr. 751 700 231 252 vom 20.07.2026")
        c.drawString(72, 760, "Total CHF 137.30")
        c.drawString(72, 700, "Zahlteil")
        c.drawString(72, 680, "Konto / Zahlbar an")
        c.drawString(72, 660, "CH40 3000 0008 3000 0310 7")
        c.drawString(72, 640, "Referenz")
        c.drawString(72, 620, "00 00506 37947 06000 08940 95003")
        c.drawString(72, 580, "IBAN CH16 0900 0000 3000 03107")
        c.save()
        return buf.getvalue()

    def test_qr_zahlteil_uebersteuert_referenz_und_iban(self):
        """Die 27-stellige QR-Referenz (Mod10-geprüft) und die QR-IBAN aus dem
        Zahlteil übersteuern Rechnungsnummer/Konto-IBAN — deterministisch,
        unabhängig davon, was die KI wählt."""
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('bkw.pdf', self._qr_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            c.post('/neu/kreditoren/scan/', {'beleg_scan': f})
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.referenz, '000050637947060000894095003')   # QRR, nicht RgNr
        self.assertEqual(k.iban, 'CH4030000008300003107')            # QR-IBAN, nicht 09xx

    def test_qr_zahlteil_uebersteuert_auch_ki_antwort(self):
        """Auch wenn die KI die Rechnungsnummer als Referenz liefert, gewinnt
        der geprüfte Zahlteil."""
        from unittest.mock import patch, MagicMock
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        import json as _json
        antwort = MagicMock()
        antwort.raise_for_status.return_value = None
        antwort.json.return_value = {'choices': [{'message': {'content': _json.dumps({
            'lieferant': 'BKW Energie AG', 'betrag': 137.30, 'datum': '2026-07-20',
            'referenz': '751700231252',                 # falsch: Rechnungsnummer
            'iban': 'CH1609000000300003107',            # falsch: Konto-IBAN
        })}}]}
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('bkw.pdf', self._qr_pdf(), content_type='application/pdf')
        with override_settings(GROQ_API_KEY='test-key'), \
             patch('finance.utils.requests.post', return_value=antwort):
            c.post('/neu/kreditoren/scan/', {'beleg_scan': f})
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.referenz, '000050637947060000894095003')
        self.assertEqual(k.iban, 'CH4030000008300003107')

    def test_qrr_pruefziffer_verwirft_falsche_kandidaten(self):
        from finance.utils import _zahlteil_extrahieren
        # Ungültige Prüfziffer → keine QRR-Übernahme
        qrr, _ = _zahlteil_extrahieren("Referenz 00 00506 37947 06000 08940 95004")
        self.assertEqual(qrr, '')
        # Normale IBAN (IID nicht 30000–31999) → keine QR-IBAN
        _, qriban = _zahlteil_extrahieren("IBAN CH16 0900 0000 3000 03107")
        self.assertEqual(qriban, '')


class LieferantStandardkontoTests(TestCase):
    """Lieferanten-Gedächtnis: Standardkonto wird bei Freigabe gelernt und bei
    Erfassung/Scan für denselben Lieferanten automatisch vorbelegt (inkl. HNK)."""
    def setUp(self):
        # Seit Etappe 5 (PR 6) gehoert der Kontenplan der Verwaltung. Diese
        # Klasse bucht, ohne vorher eine anzulegen — dann ist nicht bestimmt,
        # wessen Konto 1020 gemeint ist, und `finance.booking` sagt das auch.
        _test_organisation()


    def _konten(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()

    def test_key_normalisierung(self):
        from finance.lieferanten import lieferant_key
        self.assertEqual(lieferant_key('EWZ AG'), lieferant_key('ewz'))
        self.assertEqual(lieferant_key('Meier & Co. GmbH'), lieferant_key('meier co'))
        self.assertEqual(lieferant_key('  '), '')

    def test_freigabe_lernt_konto(self):
        from finance.models import KreditorenRechnung, LieferantProfil
        from finance.booking import konto
        self._konten()
        k = KreditorenRechnung.objects.create(lieferant='EWZ AG', betrag=Decimal('120.00'),
                                              konto=konto('4130'), status='neu')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/freigeben/')
        prof = LieferantProfil.objects.filter(name_key='ewz').first()
        self.assertIsNotNone(prof)
        self.assertEqual(prof.standard_konto.nummer, '4130')

    def test_erfassen_belegt_konto_und_hnk_vor(self):
        from finance.models import KreditorenRechnung, LieferantProfil
        from finance.booking import konto
        self._konten()
        # Vorgelernt: EWZ → 4130 (HNK-relevant)
        LieferantProfil.objects.create(organisation=_test_organisation(), name_key='ewz', name_anzeige='EWZ AG',
                                       standard_konto=konto('4130'))
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/neu/', {'lieferant': 'EWZ', 'betrag': '99.00'})
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.konto.nummer, '4130')       # Konto automatisch zugeteilt
        self.assertTrue(k.is_hnk_relevant)             # HNK aus dem Konto abgeleitet

    def test_vorbelegen_ueberschreibt_gewaehltes_konto_nicht(self):
        from finance.models import KreditorenRechnung, LieferantProfil
        from finance.lieferanten import vorbelegen
        from finance.booking import konto
        self._konten()
        LieferantProfil.objects.create(organisation=_test_organisation(), name_key='ewz', name_anzeige='EWZ',
                                       standard_konto=konto('4130'))
        k = KreditorenRechnung(lieferant='EWZ', betrag=Decimal('10'), konto=konto('4000'))
        self.assertFalse(vorbelegen(k))               # bereits zugeteilt → kein Override
        self.assertEqual(k.konto.nummer, '4000')


class KreditorSplitTests(TestCase):
    """Kostenaufteilung: eine Rechnung auf mehrere Konten/Objekte splitten;
    Freigabe bucht jede Position einzeln; Summe muss stimmen; hnk_betrag."""
    def setUp(self):
        # Seit Etappe 5 (PR 6) gehoert der Kontenplan der Verwaltung. Diese
        # Klasse bucht, ohne vorher eine anzulegen — dann ist nicht bestimmt,
        # wessen Konto 1020 gemeint ist, und `finance.booking` sagt das auch.
        _test_organisation()


    def _konten(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()

    def _rechnung(self, betrag='300.00'):
        from finance.models import KreditorenRechnung
        return KreditorenRechnung.objects.create(lieferant='Sammel AG',
                                                 betrag=Decimal(betrag), status='neu')

    def test_position_add_und_summe(self):
        from finance.models import KreditorPosition
        self._konten()
        k = self._rechnung('300.00')
        c = Client(); c.force_login(_team_user())
        from finance.models import Buchungskonto
        k4000 = Buchungskonto.objects.get(nummer='4000').id
        k4120 = Buchungskonto.objects.get(nummer='4120').id
        c.post(f'/neu/kreditoren/{k.id}/position/', {'konto_id': k4000, 'betrag': '200.00'})
        c.post(f'/neu/kreditoren/{k.id}/position/', {'konto_id': k4120, 'betrag': '100.00'})
        self.assertEqual(k.positionen.count(), 2)
        self.assertEqual(k.positionen_summe, Decimal('300.00'))
        self.assertEqual(k.positionen_differenz, Decimal('0.00'))
        # 4120 ist HNK-relevant → Position automatisch HNK; hnk_betrag = 100
        self.assertEqual(k.hnk_betrag, Decimal('100.00'))

    def test_freigabe_bucht_pro_position(self):
        from finance.models import Buchungskonto, Buchung
        self._konten()
        k = self._rechnung('300.00')
        k4000 = Buchungskonto.objects.get(nummer='4000')
        k4120 = Buchungskonto.objects.get(nummer='4120')
        from finance.models import KreditorPosition
        KreditorPosition.objects.create(rechnung=k, konto=k4000, betrag=Decimal('200.00'))
        KreditorPosition.objects.create(rechnung=k, konto=k4120, betrag=Decimal('100.00'))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/freigeben/')
        k.refresh_from_db()
        self.assertEqual(k.status, 'freigegeben')
        # Zwei Aufwandsbuchungen (200 auf 4000, 100 auf 4120), Gegenkonto 2000
        b4000 = Buchung.objects.filter(soll_konto=k4000, kreditoren_rechnung=k).first()
        b4120 = Buchung.objects.filter(soll_konto=k4120, kreditoren_rechnung=k).first()
        self.assertEqual(b4000.betrag, Decimal('200.00'))
        self.assertEqual(b4120.betrag, Decimal('100.00'))
        # Kreditor (2000) total = 300
        haben2000 = Buchung.objects.filter(haben_konto__nummer='2000', kreditoren_rechnung=k)
        self.assertEqual(sum(b.betrag for b in haben2000), Decimal('300.00'))

    def test_freigabe_blockt_bei_falscher_summe(self):
        from finance.models import Buchungskonto, KreditorPosition
        self._konten()
        k = self._rechnung('300.00')
        KreditorPosition.objects.create(rechnung=k, konto=Buchungskonto.objects.get(nummer='4000'),
                                        betrag=Decimal('150.00'))   # Summe 150 ≠ 300
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/freigeben/')
        k.refresh_from_db()
        self.assertEqual(k.status, 'neu')   # nicht freigegeben — Aufteilung stimmt nicht


class WeiterverrechnungVerteilenTests(TestCase):
    """Multi-Mieter-Weiterverrechnung nach Verteilschlüssel + HNK-Doppelschutz."""
    def setUp(self):
        # Seit Etappe 5 (PR 6) gehoert der Kontenplan der Verwaltung. Diese
        # Klasse bucht, ohne vorher eine anzulegen — dann ist nicht bestimmt,
        # wessen Konto 1020 gemeint ist, und `finance.booking` sagt das auch.
        _test_organisation()


    def _konten(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()

    def _lg_mit_mietern(self):
        from portfolio.models import Liegenschaft, Einheit
        from crm.models import Mieter
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Verteilweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        daten = [('A', Decimal('50')), ('B', Decimal('100')), ('C', Decimal('50'))]  # m² 50/100/50 → 25/50/25%
        for name, m2 in daten:
            e = Einheit.objects.create(liegenschaft=lg, bezeichnung=name, typ='whg',
                                       flaeche_m2=m2, nettomiete_aktuell=Decimal('1000'))
            m = Mieter.objects.create(typ='person', vorname=name, nachname='Test',
                                      strasse='X', plz='8000', ort='Zürich')
            Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'),
                                       status='aktiv')
        return lg

    def test_verteilen_nach_m2(self):
        from finance.models import KreditorenRechnung, DebitorenRechnung
        self._konten()
        lg = self._lg_mit_mietern()
        k = KreditorenRechnung.objects.create(lieferant='Gärtner AG', betrag=Decimal('400.00'),
                                              liegenschaft=lg, status='freigegeben')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/', {'modus': 'verteilen', 'schluessel': 'm2'})
        rechnungen = DebitorenRechnung.objects.filter(quell_kreditor=k).order_by('betrag')
        self.assertEqual(rechnungen.count(), 3)
        # 400 nach 25/50/25 → 100/200/100
        self.assertEqual(sorted(r.betrag for r in rechnungen), [Decimal('100.00'), Decimal('100.00'), Decimal('200.00')])
        # Summe exakt = 400 (Rest auf letzten, keine Rundungsverluste)
        self.assertEqual(sum(r.betrag for r in rechnungen), Decimal('400.00'))

    def test_hnk_doppelschutz_blockt_ohne_override(self):
        from finance.models import KreditorenRechnung, DebitorenRechnung
        self._konten()
        lg = self._lg_mit_mietern()
        k = KreditorenRechnung.objects.create(lieferant='Heizöl AG', betrag=Decimal('300.00'),
                                              liegenschaft=lg, is_hnk_relevant=True, status='freigegeben')
        c = Client(); c.force_login(_team_user())
        # Ohne Override → geblockt, keine Debitorenrechnung
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/', {'modus': 'verteilen', 'schluessel': 'einheit'})
        self.assertEqual(DebitorenRechnung.objects.filter(quell_kreditor=k).count(), 0)
        # Mit Override → verteilt (3 Mieter gleich)
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/',
               {'modus': 'verteilen', 'schluessel': 'einheit', 'hnk_override': 'on'})
        self.assertEqual(DebitorenRechnung.objects.filter(quell_kreditor=k).count(), 3)


class KontoVorschlagLeistungTests(TestCase):
    """KI-Konto-Vorschlag (Kategorie/Schlüsselwort → Konto) + Leistungsperiode."""
    def setUp(self):
        # Seit Etappe 5 (PR 6) gehoert der Kontenplan der Verwaltung. Diese
        # Klasse bucht, ohne vorher eine anzulegen — dann ist nicht bestimmt,
        # wessen Konto 1020 gemeint ist, und `finance.booking` sagt das auch.
        _test_organisation()


    def _konten(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()

    def test_konto_aus_kategorie_und_text(self):
        from finance.lieferanten import konto_aus_kategorie, konto_aus_text
        self.assertEqual(konto_aus_kategorie('strom'), '4130')
        self.assertEqual(konto_aus_kategorie('versicherung'), '4400')
        self.assertIsNone(konto_aus_kategorie('quatsch'))
        self.assertEqual(konto_aus_text('Wasserversorgung Zürich'), '4110')
        self.assertEqual(konto_aus_text('EWZ Elektrizitätswerk'), '4130')
        self.assertIsNone(konto_aus_text('Irgendwas Neutrales'))

    def test_vorbelegen_prioritaet(self):
        from finance.models import KreditorenRechnung, LieferantProfil
        from finance.lieferanten import vorbelegen
        from finance.booking import konto
        self._konten()
        # Kategorie schlägt Konto vor (kein Gedächtnis, kein Keyword)
        k = KreditorenRechnung(lieferant='Neutrale Firma', betrag=Decimal('50'))
        self.assertTrue(vorbelegen(k, kategorie='heizung'))
        self.assertEqual(k.konto.nummer, '4100')
        self.assertTrue(k.is_hnk_relevant)
        # Gedächtnis hat Vorrang vor Kategorie
        LieferantProfil.objects.create(organisation=_test_organisation(), name_key='neutrale firma', name_anzeige='Neutrale Firma',
                                       standard_konto=konto('4000'))
        k2 = KreditorenRechnung(lieferant='Neutrale Firma', betrag=Decimal('50'))
        self.assertTrue(vorbelegen(k2, kategorie='heizung'))
        self.assertEqual(k2.konto.nummer, '4000')   # Gedächtnis gewinnt

    def test_erfassen_setzt_leistungsperiode_und_konto(self):
        from finance.models import KreditorenRechnung
        self._konten()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/neu/', {
            'lieferant': 'Wasserversorgung', 'betrag': '120.00',
            'leistungs_von': '2025-01-01', 'leistungs_bis': '2025-12-31',
        })
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.leistungs_von, date(2025, 1, 1))
        self.assertEqual(k.leistungs_bis, date(2025, 12, 31))
        self.assertEqual(k.konto.nummer, '4110')   # aus Schlüsselwort «Wasser»
        self.assertTrue(k.is_hnk_relevant)

    def test_scanner_liefert_kategorie_und_periode_keys(self):
        # Ohne KI liefert der Scanner die neuen Keys (leer) — Struktur stabil.
        from finance.utils import _leer
        d = _leer('leer', '')
        self.assertIn('kategorie', d)
        self.assertIn('leistung_von', d)
        self.assertIn('leistung_bis', d)


class WeiterverrechnungSplitKontoTests(TestCase):
    """Offener Punkt 2: Weiterverrechnung einer gesplitteten Rechnung nutzt das
    Konto der grössten Position als Aufwand-Gegenkonto (statt pauschal 4000)."""
    def setUp(self):
        # Seit Etappe 5 (PR 6) gehoert der Kontenplan der Verwaltung. Diese
        # Klasse bucht, ohne vorher eine anzulegen — dann ist nicht bestimmt,
        # wessen Konto 1020 gemeint ist, und `finance.booking` sagt das auch.
        _test_organisation()


    def test_aufwand_gegenkonto_aus_groesster_position(self):
        from finance.booking import ensure_kontenplan, konto
        from finance.models import KreditorenRechnung, KreditorPosition, Buchung, Buchungskonto
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(lieferant='Split AG', betrag=Decimal('300.00'),
                                              liegenschaft=lg, status='freigegeben')
        # grösste Position: 200 auf 4130
        KreditorPosition.objects.create(rechnung=k, konto=Buchungskonto.objects.get(nummer='4000'),
                                        betrag=Decimal('100.00'))
        KreditorPosition.objects.create(rechnung=k, konto=Buchungskonto.objects.get(nummer='4130'),
                                        betrag=Decimal('200.00'))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/', {'vertrag_id': v.id, 'betrag': '300', 'zuschlag': '0'})
        # Aufwandsminderung 1190 an 4130 (grösste Position), nicht 4000
        gegen = Buchung.objects.filter(soll_konto__nummer='1190', kreditoren_rechnung=k).first()
        self.assertIsNotNone(gegen)
        self.assertEqual(gegen.haben_konto.nummer, '4130')


class KreditorenP4Tests(TestCase):
    """Eine Liste ohne Suche ist bei 300 Rechnungen keine Liste, und ein Zahllauf
    ohne Auswahl ist kein Zahllauf — beides Blocker aus dem Praxis-Audit."""
    def setUp(self):
        # Seit Etappe 5 (PR 6) gehoert der Kontenplan der Verwaltung. Diese
        # Klasse bucht, ohne vorher eine anzulegen — dann ist nicht bestimmt,
        # wessen Konto 1020 gemeint ist, und `finance.booking` sagt das auch.
        _test_organisation()


    def _saldo(self, nummer):
        from finance.models import Buchung
        from django.db.models import Sum
        soll = (Buchung.objects.filter(soll_konto__nummer=nummer, ist_storno=False)
                .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        haben = (Buchung.objects.filter(haben_konto__nummer=nummer, ist_storno=False)
                 .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        return soll - haben

    def _rechnungen(self, lg):
        from finance.models import KreditorenRechnung
        daten = [('Alpha Sanitaer AG', 'CH9300762011623852957', '100.00'),
                 ('Beta Elektro GmbH', 'CH5604835012345678009', '200.00'),
                 ('Gamma Garten', '', '300.00')]
        return [KreditorenRechnung.objects.create(
            lieferant=n, referenz=f'RE-{i}', betrag=Decimal(b),
            datum=date(2024, 4, 1), faellig_am=date(2024, 4, 20 + i),
            iban=iban, liegenschaft=lg, status='freigegeben')
            for i, (n, iban, b) in enumerate(daten)]

    def _mit_iban(self):
        from crm.models import Organisation
        vw = Organisation.objects.first()
        if vw is None:
            vw = _test_organisation(firma='Testverwaltung')
        vw.iban = 'CH5604835012345678009'
        vw.save()
        return vw

    # ---------- Liste ----------
    def test_kreditorenliste_ist_durchsuchbar(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/kreditoren/?q=Beta')
        self.assertEqual(r.status_code, 200)
        namen = [z['k'].lieferant for z in r.context['rows']]
        self.assertEqual(namen, ['Beta Elektro GmbH'])

    def test_kreditorenliste_findet_ueber_referenz_und_betrag(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/kreditoren/?q=RE-2')
        self.assertEqual([z['k'].lieferant for z in r.context['rows']], ['Gamma Garten'])
        r = c.get('/neu/kreditoren/?q=200')
        self.assertEqual([z['k'].lieferant for z in r.context['rows']], ['Beta Elektro GmbH'])

    def test_kreditorenliste_sortiert_standardmaessig_nach_faelligkeit(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/kreditoren/')
        self.assertEqual([z['k'].lieferant for z in r.context['rows']],
                         ['Alpha Sanitaer AG', 'Beta Elektro GmbH', 'Gamma Garten'])
        r = c.get('/neu/kreditoren/?sort=-betrag')
        self.assertEqual([z['k'].lieferant for z in r.context['rows']][0], 'Gamma Garten')

    def test_kennzahlen_gelten_fuer_den_ganzen_bestand_nicht_die_seite(self):
        """Beim Blättern darf die Kopfzahl nicht mitwandern."""
        from finance.models import KreditorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        for i in range(60):
            KreditorenRechnung.objects.create(
                lieferant=f'Lieferant {i}', betrag=Decimal('10.00'),
                datum=date(2024, 4, 1), liegenschaft=lg, status='neu')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/kreditoren/')
        self.assertEqual(r.context['anzahl_neu'], 60)
        self.assertEqual(r.context['total_neu'], Decimal('600.00'))
        self.assertEqual(len(r.context['rows']), 50)     # Seite 1
        r2 = c.get('/neu/kreditoren/?seite=2')
        self.assertEqual(r2.context['anzahl_neu'], 60)   # unverändert
        self.assertEqual(len(r2.context['rows']), 10)

    def test_erfassen_uebernimmt_die_iban(self):
        """Ohne IBAN kommt eine manuell erfasste Rechnung nie in einen Zahllauf."""
        from finance.models import KreditorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/neu/', {'lieferant': 'Delta Malerei', 'betrag': '250',
                                        'iban': 'CH93 0076 2011 6238 5295 7'})
        k = KreditorenRechnung.objects.get(lieferant='Delta Malerei')
        self.assertEqual(k.iban, 'CH9300762011623852957')

    # ---------- Zahllauf ----------
    def test_zahllauf_zeigt_vorschlag_und_fehlende_iban(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/zahllauf/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['vorschlag']), 3)
        self.assertEqual(r.context['ohne_iban'], 1)
        self.assertEqual(r.context['summe_vorschlag'], Decimal('600.00'))

    def test_zahllauf_nimmt_nur_die_ausgewaehlten_rechnungen(self):
        """Vorher packte der Zahllauf ungefragt ALLE freigegebenen Rechnungen
        in die Datei — eine Auswahl gab es nicht."""
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        self._mit_iban()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': [krs[0].id],
                                      'ausfuehrungsdatum': '2024-04-15'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/xml')
        for k in krs:
            k.refresh_from_db()
        self.assertEqual(krs[0].status, 'in_zahlung')
        self.assertEqual(krs[1].status, 'freigegeben')   # nicht ausgewählt
        self.assertEqual(krs[2].status, 'freigegeben')

    def test_zahllauf_haelt_das_ausfuehrungsdatum_fest(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        self._mit_iban()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': [krs[0].id],
                                  'ausfuehrungsdatum': '2024-04-15'})
        krs[0].refresh_from_db()
        self.assertEqual(krs[0].zahlung_ausfuehrung, date(2024, 4, 15))

    def test_zahllauf_ohne_verwaltungs_iban_erzeugt_keine_datei(self):
        from crm.models import Organisation
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        Organisation.objects.update(iban='')
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': [krs[0].id]})
        self.assertEqual(r.status_code, 302)
        krs[0].refresh_from_db()
        self.assertEqual(krs[0].status, 'freigegeben')

    def test_zahllauf_verbucht_die_auswahl_sammelweise(self):
        """Danach musste bisher jede der ~40 Zahlungen einzeln geklickt werden."""
        from finance.models import KreditorenZahlung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        self._mit_iban()
        c = Client(); c.force_login(_team_user())
        ids = [krs[0].id, krs[1].id]
        c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': ids,
                                  'ausfuehrungsdatum': '2024-04-15'})
        c.post('/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': ids,
                                  'valuta': '2024-04-16', 'bank_konto': '1020'})
        for k in krs:
            k.refresh_from_db()
        self.assertEqual(krs[0].status, 'bezahlt')
        self.assertEqual(krs[1].status, 'bezahlt')
        self.assertEqual(krs[2].status, 'freigegeben')
        self.assertEqual(self._saldo('1020'), Decimal('-300.00'))
        self.assertEqual(self._saldo('2000'), Decimal('300.00'))
        self.assertEqual(KreditorenZahlung.objects.filter(kreditor__in=krs[:2]).count(), 2)

    def test_zahllauf_bucht_auf_das_valutadatum(self):
        from finance.models import KreditorenZahlung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        self._mit_iban()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': [krs[0].id],
                                  'valuta': '2024-04-16'})
        z = KreditorenZahlung.objects.get(kreditor=krs[0])
        self.assertEqual(z.datum, date(2024, 4, 16))

    def test_zahllauf_bucht_auf_gewaehltes_bankkonto(self):
        from finance.models import Buchungskonto
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        Buchungskonto.objects.create(nummer='1021', bezeichnung='Bank 2', typ='aktiv',
                                    organisation=_test_organisation())
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': [krs[0].id],
                                  'valuta': '2024-04-16', 'bank_konto': '1021'})
        self.assertEqual(self._saldo('1021'), Decimal('-100.00'))
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))

    def test_zahllauf_zuruecksetzen_gibt_rechnungen_wieder_frei(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        self._mit_iban()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': [krs[0].id],
                                  'ausfuehrungsdatum': '2024-04-15'})
        c.post('/neu/zahllauf/', {'aktion': 'zuruecksetzen', 'rechnung_ids': [krs[0].id]})
        krs[0].refresh_from_db()
        self.assertEqual(krs[0].status, 'freigegeben')

    def test_zahllauf_verbucht_nicht_doppelt(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        daten = {'aktion': 'bezahlt', 'rechnung_ids': [krs[0].id], 'valuta': '2024-04-16'}
        c.post('/neu/zahllauf/', daten)
        c.post('/neu/zahllauf/', daten)
        self.assertEqual(self._saldo('1020'), Decimal('-100.00'))

    def test_einzelzahlung_nimmt_valuta_und_bankkonto(self):
        from finance.models import Buchungskonto, KreditorenZahlung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        Buchungskonto.objects.create(nummer='1021', bezeichnung='Bank 2', typ='aktiv',
                                    organisation=_test_organisation())
        lg, e, m, v = _basis_objekte()
        krs = self._rechnungen(lg)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': krs[0].id,
                                             'valuta': '2024-04-16',
                                             'bank_konto': '1021'})
        z = KreditorenZahlung.objects.get(kreditor=krs[0])
        self.assertEqual(z.datum, date(2024, 4, 16))
        self.assertEqual(self._saldo('1021'), Decimal('-100.00'))


# ============================================================
# P5 — UI-Konsistenz + Datenverlust-Fallen in den Finanzen
# ============================================================


class ZahlungsverkehrH8H9Tests(TestCase):
    """Live-Test H8/H9: Lieferantenzahlung stornierbar + Teilzahlungsrest im Zahllauf.

    H9: `fw_zahlung_stornieren` deckte nur EINGEHENDE Zahlungen ab — eine falsch
        ausgeführte Lieferantenzahlung war nicht rückgängig zu machen.
        Und: nach einer Teilzahlung fiel die Rechnung aus dem Zahllauf-Vorschlag,
        der offene Rest wurde nie wieder vorgeschlagen.
    """
    def setUp(self):
        # Seit Etappe 5 (PR 6) gehoert der Kontenplan der Verwaltung. Diese
        # Klasse bucht, ohne vorher eine anzulegen — dann ist nicht bestimmt,
        # wessen Konto 1020 gemeint ist, und `finance.booking` sagt das auch.
        _test_organisation()


    def _saldo(self, nummer):
        from finance.models import Buchung
        from django.db.models import Sum
        soll = Buchung.objects.filter(soll_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        haben = Buchung.objects.filter(haben_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        return soll - haben

    def _kreditor_freigegeben(self, lg, betrag='500.00'):
        from finance.models import KreditorenRechnung
        return KreditorenRechnung.objects.create(
            lieferant='Sanitär AG', liegenschaft=lg, status='freigegeben',
            datum=date(2024, 3, 1), faellig_am=date(2024, 3, 31),
            betrag=Decimal(betrag), iban='CH9300762011623852957', referenz='RF-1')

    def test_h9_verbuchte_lieferantenzahlung_stornierbar(self):
        from finance.booking import ensure_kontenplan
        from finance.models import KreditorenZahlung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        k = self._kreditor_freigegeben(lg)
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': str(k.id),
                                             'bank_konto': '1020', 'valuta': '2024-03-05'})
        k.refresh_from_db()
        self.assertEqual(k.status, 'bezahlt')
        self.assertEqual(k.offener_betrag, Decimal('0.00'))
        z = KreditorenZahlung.objects.get(kreditor=k)
        c.post(f'/neu/kreditoren/zahlung/{z.id}/stornieren/', {'next': '/neu/kreditoren/'})
        z.refresh_from_db(); k.refresh_from_db()
        self.assertEqual(z.status, 'storniert')
        self.assertEqual(k.status, 'freigegeben')          # offener Posten wieder offen
        self.assertEqual(k.offener_betrag, Decimal('500.00'))
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))   # Zahlung + Storno = 0

    def test_h9_doppel_storno_wird_abgewiesen(self):
        from finance.booking import ensure_kontenplan
        from finance.models import KreditorenZahlung, Buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        k = self._kreditor_freigegeben(lg)
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': str(k.id), 'bank_konto': '1020'})
        z = KreditorenZahlung.objects.get(kreditor=k)
        c.post(f'/neu/kreditoren/zahlung/{z.id}/stornieren/', {})
        n_storni = Buchung.objects.filter(ist_storno=True).count()
        c.post(f'/neu/kreditoren/zahlung/{z.id}/stornieren/', {})   # zweites Mal
        self.assertEqual(Buchung.objects.filter(ist_storno=True).count(), n_storni)

    def test_h9_teilzahlungsrest_im_zahllauf_vorschlag(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        k = self._kreditor_freigegeben(lg, '500.00')
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': str(k.id), 'betrag': '200',
                                             'bank_konto': '1020', 'valuta': '2024-03-05'})
        k.refresh_from_db()
        self.assertEqual(k.status, 'teilbezahlt')
        self.assertEqual(k.offener_betrag, Decimal('300.00'))
        r = c.get('/neu/zahllauf/')
        vorschlag = r.context['vorschlag']
        zeile = next((z for z in vorschlag if z['k'].id == k.id), None)
        self.assertIsNotNone(zeile, 'Teilzahlungsrest fehlt im Zahllauf-Vorschlag')
        self.assertEqual(zeile['offen'], Decimal('300.00'))
