"""Ein Rahmen für alle E-Mails (Mockup «E-Mails», 23.11.2026).

Vorher drei Aufmachungen (Karte mit Schatten, farbiger Kopf, gar kein Rahmen). Geprüft wird, was eine Empfängerin sieht:
Kopf mit der Verwaltung, Inhalt, Adressfuss — und dass der Rahmen nie einen Text ändert oder doppelt gesetzt wird.
"""
from pathlib import Path

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings

from core.utils import email_service
from core.utils.email_service import INTERN_MARKE, RAHMEN_MARKE, STIL, klartext_html, mail_inhalt, mail_rahmen

from ._helfer import _basis_objekte


class MailRahmenTests(TestCase):

    def _org(self):
        lg, _e, _m, _v = _basis_objekte()
        org = lg.organisation
        org.firma, org.strasse, org.plz, org.ort = 'Rahmen <AG>', 'Testweg 1', '8000', 'Zürich'
        org.email, org.telefon = 'info@rahmen.example', '044 000 00 00'
        org.save()
        return org

    def test_kopf_inhalt_und_adressfuss_der_verwaltung(self):
        org = self._org()
        html = mail_rahmen('<p>Hallo</p>', org)
        self.assertTrue(html.startswith(RAHMEN_MARKE))
        self.assertEqual(mail_inhalt(html), '<p>Hallo</p>')
        kopf, fuss = html.split('<!--mail-inhalt-->')[0], html.split('<!--/mail-inhalt-->')[1]
        self.assertIn('Rahmen &lt;AG&gt;', kopf)                    # maskiert, nie als Markup
        self.assertIn('Testweg 1 · 8000 Zürich', fuss)
        self.assertIn('info@rahmen.example · 044 000 00 00', fuss)

    def test_die_id_der_verwaltung_genuegt(self):
        """Versand aus einem eigenen Thread: dort gibt es keinen Mandantenkontext, nur die ID."""
        org = self._org()
        self.assertIn('Testweg 1', mail_rahmen('<p>x</p>', org.pk))

    def test_ohne_verwaltung_immoswiss_und_kein_adressfuss(self):
        html = mail_rahmen('<p>x</p>', None)
        self.assertIn('immoswiss', html.split('<!--mail-inhalt-->')[0])
        self.assertNotIn('border-top:1px solid', html.split('<!--/mail-inhalt-->')[1])

    def test_nie_doppelt_einrahmen(self):
        org = self._org()
        einmal = mail_rahmen('<p>x</p>', org)
        self.assertEqual(mail_rahmen(einmal, org), einmal)
        self.assertEqual(einmal.count(RAHMEN_MARKE), 1)

    def test_interne_mail_ohne_adressfuss(self):
        org = self._org()
        html = mail_rahmen(INTERN_MARKE + '<p>Neue Meldung</p>', org)
        self.assertNotIn('Testweg 1', html)
        self.assertIn('Rahmen &lt;AG&gt;', html)

    def test_jeder_versand_ueber_den_dienst_traegt_den_rahmen(self):
        org = self._org()
        email_service.send_via_hoststar('x@example.ch', 'Betreff', '<p>Text</p>', organisation=org.pk)
        email_service.send_report_mail('x@example.ch', 'Bericht', '<p>Text</p>', organisation=org)
        self.assertEqual(len(mail.outbox), 2)
        for m in mail.outbox:
            self.assertTrue(m.body.startswith(RAHMEN_MARKE), m.subject)
            self.assertIn('Testweg 1', m.body)
            self.assertEqual(mail_inhalt(m.body), '<p>Text</p>')

    @override_settings(PORTAL_BASE_URL='https://portal.example')
    def test_logo_nur_mit_basisadresse_und_hinterlegtem_logo(self):
        org = self._org()
        self.assertNotIn('<img', mail_rahmen('<p>x</p>', org))      # kein Logo hinterlegt: der Name steht im Kopf
        org.logo.name = 'logos/test.png'
        self.assertIn('<img src="https://portal.example', mail_rahmen('<p>x</p>', org))


class MailBausteineTests(TestCase):

    def test_knopf_ist_eine_pille_in_der_markenfarbe_und_die_adresse_bleibt_lesbar(self):
        link = 'https://example.ch/auftrag/abc/'
        html = klartext_html(f'Guten Tag\n\nTermin bestätigen:\n{link}\n\nDanke', link, 'Termin bestätigen oder ändern')
        self.assertIn('border-radius:999px', html)
        self.assertIn('>Termin bestätigen oder ändern</a>', html)
        self.assertIn(f'>{link}</a>', html)
        # der Text davor und danach bleibt Wort für Wort stehen
        self.assertIn('Guten Tag<br><br>Termin bestätigen:<br>', html)
        self.assertTrue(html.rstrip().endswith('<br><br>Danke</div>'))

    def test_keine_roten_balken_und_keine_alten_rahmen_mehr(self):
        ordner = Path(settings.BASE_DIR) / 'core' / 'templates' / 'emails'
        namen = sorted(p.name for p in ordner.glob('*.html'))
        for alt in ('base_email.html', 'rahmen_karte.html', 'rahmen_schlicht.html'):
            self.assertNotIn(alt, namen)
        for p in ordner.glob('*.html'):
            text = p.read_text()
            self.assertNotIn('border-left', text, p.name)
            self.assertNotIn('box-shadow', text, p.name)
            if p.name != 'rahmen.html':
                self.assertNotIn('<body', text, f'{p.name}: Vorlagen liefern nur den Inhalt, den Rahmen setzt mail_rahmen')

    def test_alle_vorlagen_nutzen_die_gemeinsamen_bausteine(self):
        """Wer in einer Vorlage wieder eigene Farben setzt, fällt hier auf: Stile kommen aus `STIL`."""
        import re
        ordner = Path(settings.BASE_DIR) / 'core' / 'templates' / 'emails'
        for p in ordner.glob('*.html'):
            if p.name == 'rahmen.html':
                continue
            for stil in re.findall(r'style="([^"]*)"', p.read_text()):
                rest = re.sub(r'\{\{ stil\.[a-z_]+ \}\}|\{%.*?%\}', '', stil)
                self.assertNotRegex(rest, r'#[0-9a-fA-F]{3,6}|rgb', f'{p.name}: «{stil}»')
        self.assertIn('border-radius:999px', STIL['knopf'])

    def test_mahnung_wortlaut_unveraendert(self):
        """Die Kopie der Mahnung mit Kündigungsandrohung: Aufmachung neu, Sätze dieselben (Art. 257d OR)."""
        html = email_service.mail_html('email_mahnung', gruss='Guten Tag Frau Muster', objekt_name='3.5 Zi (Testweg 1)',
                                       monat='11/2026', betrag='1700.00', firma_name='V AG')
        from django.utils.html import strip_tags
        text = ' '.join(strip_tags(html).split())
        for satz in ('Mahnung mit Kündigungsandrohung',
                     'Dies ist eine Kopie per E-Mail. Die massgebende Zahlungsaufforderung mit Fristansetzung erhalten Sie '
                     'zusätzlich per Einschreiben. Die Frist nach Art. 257d OR läuft erst ab dem Zugang dieses '
                     'eingeschriebenen Briefes.',
                     'Ausstehender Betrag: CHF 1700.00',
                     'innert der im eingeschriebenen Schreiben gesetzten Frist (mindestens 30 Tage ab Zugang) zu überweisen, '
                     'um eine Kündigung des Mietverhältnisses zu vermeiden.'):
            self.assertIn(satz, text)
