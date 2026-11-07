"""Etappe 3 aus docs/AUDIT-SAAS-NIVEAU.md: Komponentenschicht und Typografie."""
import re

from pathlib import Path

from django.conf import settings
from django.test import TestCase, Client, SimpleTestCase

from ._helfer import _team_user, _basis_objekte
from .csp_handler_stand import KOMMENTAR

VORLAGEN = Path(settings.BASE_DIR) / 'core' / 'templates'


class EmbedHuelle(SimpleTestCase):
    """Die Iframe-Modals (Abnahme, Ausschreibung, Schlussabrechnung) liefen bis
    29.09.2026 ohne Stilschicht und ohne Icon-Sprite — gemessen mit Chromium:
    keine Karten, keine Knöpfe, 570 px breit bei 384 px Bildschirm."""

    EINBINDUNGEN = ("{% include 'fw/_assets.html' %}", "{% include 'fw/_schicht_link.html' %}",
                    "{% include 'fw/_zeichen.html' %}")

    def test_embed_huelle_laedt_was_base_laedt(self):
        base = (VORLAGEN / 'fw' / 'base.html').read_text(encoding='utf-8')
        embed = (VORLAGEN / 'fw' / 'base_embed.html').read_text(encoding='utf-8')
        for zeile in self.EINBINDUNGEN:
            self.assertIn(zeile, base, zeile)
            self.assertIn(zeile, embed, zeile)


class EmbedSeite(TestCase):

    def test_abnahme_im_modal_hat_schicht_und_symbole(self):
        _lg, _e, _m, v = _basis_objekte()
        c = Client()
        c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/{v.id}/abnahme/neu/?embed=1').content.decode()
        self.assertIn('css/schicht.css', body)
        # Jedes verwendete Symbol muss in der Seite definiert sein.
        benutzt = set(re.findall(r'href="#(z-[a-z0-9-]+)"', body))
        definiert = set(re.findall(r'<symbol id="(z-[a-z0-9-]+)"', body))
        self.assertTrue(benutzt)
        self.assertEqual(benutzt - definiert, set())


class Schriftgrade(SimpleTestCase):
    """Vier kleine Schriftgrade statt acht frei gewählter Pixelwerte, und keine
    Gewichte über 700 — IBM Plex Sans wird nur bis Bold (700) ausgeliefert
    (`static/css/schriften.css`); alles darüber zeichnete der Browser als
    künstliches Fett."""

    def _fw_vorlagen(self):
        for datei in (VORLAGEN / 'fw').rglob('*.html'):
            if datei.name != '_schicht.html':
                yield datei, datei.read_text(encoding='utf-8')

    def test_keine_frei_gewaehlten_pixelgroessen_in_fw(self):
        treffer = [f'{d.relative_to(VORLAGEN)}: {m}' for d, text in self._fw_vorlagen()
                   for m in re.findall(r'(?<![\w:-])text-\[[0-9.]+px\]', text)]
        self.assertEqual(treffer, [], 'Statt text-[Npx]: fw-fs-mikro/klein/fein/text.')

    def test_keine_gewichte_ueber_700(self):
        treffer = [str(d.relative_to(VORLAGEN)) for d, text in self._fw_vorlagen()
                   if re.search(r'\bfont-(black|extrabold)\b|font-weight: *(800|900)', text)]
        self.assertEqual(treffer, [])

    def test_schicht_hat_keine_gewichte_ueber_700_ausser_font_awesome(self):
        schicht = (VORLAGEN / 'fw' / '_schicht.html').read_text(encoding='utf-8')
        for regel in re.findall(r'\{[^{}]*font-weight:(?:800|900)[^{}]*\}', schicht):
            # Font Awesome «Solid» IST das Gewicht 900 — dort ist es die Glyphe.
            self.assertIn('Font Awesome', regel)

    def test_die_skala_ist_definiert(self):
        schicht = (VORLAGEN / 'fw' / '_schicht.html').read_text(encoding='utf-8')
        benutzt = {m for _d, text in self._fw_vorlagen()
                   for m in re.findall(r'\bfw-fs-[a-z]+\b', text)}
        definiert = set(re.findall(r'\.(fw-fs-[a-z]+)\{', schicht))
        self.assertTrue(benutzt)
        self.assertEqual(benutzt - definiert, set())


class Meldungen(TestCase):
    """Toasts: für Screenreader angesagt, ohne doppeltes Emoji."""

    def test_ohne_emoji(self):
        from core.templatetags.zeichen import ohne_emoji
        faelle = {
            '✅ Liegenschaft gespeichert.': 'Liegenschaft gespeichert.',
            '⚠️ EGID konnte nicht ermittelt werden': 'EGID konnte nicht ermittelt werden',
            '🗑️ Abnahmeprotokoll gelöscht.': 'Abnahmeprotokoll gelöscht.',
            '📍 EGID 123 ermittelt.': 'EGID 123 ermittelt.',
            'Ohne Emoji bleibt alles.': 'Ohne Emoji bleibt alles.',
            'CHF 1’250 überwiesen': 'CHF 1’250 überwiesen',
        }
        for vorher, nachher in faelle.items():
            self.assertEqual(ohne_emoji(vorher), nachher)

    def test_toast_ist_live_region_und_ohne_emoji(self):
        from unittest.mock import patch
        lg, _e, _m, _v = _basis_objekte()
        c = Client()
        c.force_login(_team_user())
        with patch('portfolio.services.sync_liegenschaft_with_gwr', return_value={}):
            r = c.post(f'/neu/liegenschaften/{lg.id}/bearbeiten/', {
                'strasse': 'Toastweg 1', 'plz': '8000', 'ort': 'Zürich', 'egid': '1',
                'hkvo_grundkosten_prozent': '40'}, follow=True)
        body = r.content.decode()
        self.assertIn('id="fw-toasts"', body)
        stapel = body[body.index('id="fw-toasts"'):]
        stapel = stapel[:stapel.index('</script>')]
        self.assertIn('aria-live="polite"', stapel)
        self.assertIn('Toastweg 1', stapel)
        self.assertNotIn('✅', stapel)


class Modal(SimpleTestCase):

    def _quelle(self):
        return (VORLAGEN / 'fw' / '_fwmodal.html').read_text(encoding='utf-8')

    def test_ist_ein_dialog(self):
        q = self._quelle()
        self.assertIn('role="dialog"', q)
        self.assertIn('aria-modal="true"', q)
        self.assertIn('aria-labelledby="fwModalTitle"', q)

    def test_laedt_nur_neu_wenn_etwas_geschah(self):
        """Vorher lud jedes Schliessen die Seite neu — auch «Abbrechen»."""
        skript = self._quelle().split('<script nonce="{{ csp_nonce }}">', 1)[1]
        schliessen = skript[skript.index('function fwModalClose'):skript.index("window.addEventListener('message'")]
        self.assertIn('if (neuLaden) { window.location.reload()', schliessen)
        self.assertEqual(schliessen.count('window.location.reload()'), 1)

    def test_fragt_vor_dem_verwerfen_von_eingaben(self):
        self.assertIn('fwModalGetippt', self._quelle())
        self.assertIn('confirm(', self._quelle())


class Bestaetigungsdialog(SimpleTestCase):
    """Gestalteter Dialog statt der Browser-Rückfrage (fw/_bestaetigen.html).

    Das Verhalten wurde in Chromium an gerenderten Seiten geprüft (Personenakte:
    Formular-Rückfrage mit Löschung; Anlagen: Knopf-Rückfrage): Dialog statt
    Browser-Rückfrage, «Abbrechen» schickt nicht ab, «Bestätigen» genau einmal,
    rote Taste und Fokus auf «Abbrechen» bei Löschungen. Diese Tests halten die
    Voraussetzungen fest, die sich ohne Browser prüfen lassen.
    """

    def _baustein(self):
        return (VORLAGEN / 'fw' / '_bestaetigen.html').read_text(encoding='utf-8')

    def test_beide_huellen_binden_den_dialog_ein(self):
        for name in ('base.html', 'base_embed.html'):
            self.assertIn("{% include 'fw/_bestaetigen.html' %}",
                          (VORLAGEN / 'fw' / name).read_text(encoding='utf-8'), name)

    def test_das_skript_liest_das_datenattribut(self):
        """Seit der CSP (Nr. 23) steht die Rückfrage in `data-bestaetigen`, nicht mehr in einem Inline-Handler."""
        b = self._baustein()
        self.assertIn("getAttribute('data-bestaetigen')", b)
        self.assertIn("[data-bestaetigen]:not(form)", b)           # Formulare fragen beim Absenden, nicht beim Klick
        self.assertIn('window.confirm(text)', b)                    # ohne <dialog> fragt der Browser

    def test_keine_rueckfrage_mehr_als_inline_handler(self):
        """Ein `onsubmit/onclick="…confirm(…)"` wäre mit CSP blockiert — und liefe ohne Dialog durch."""
        uebrig = []
        for datei in VORLAGEN.rglob('*.html'):
            text = KOMMENTAR.sub(' ', datei.read_text(encoding='utf-8'))
            for m in re.finditer(r'\b(?:onsubmit|onclick)="((?:[^"{]|\{[{%][\s\S]*?[}%]\})*)"', text):
                if 'confirm(' in m.group(1):
                    uebrig.append(f'{datei.relative_to(VORLAGEN)}: {m.group(1)[:80]}')
        self.assertEqual(uebrig, [])

    def test_jede_rueckfrage_ist_fuer_ein_attribut_gesichert(self):
        """Der Text steht in einem HTML-Attribut und wird vom Skript entschlüsselt: `escapejs` ist Pflicht
        (sonst bricht ein Anführungszeichen im Namen das Attribut oder der Text trägt Markup)."""
        ohne = []
        for datei in VORLAGEN.rglob('*.html'):
            text = KOMMENTAR.sub(' ', datei.read_text(encoding='utf-8'))
            for m in re.finditer(r'\bdata-bestaetigen="((?:[^"{]|\{[{%#][\s\S]*?[}%#]\})*)"', text):
                if 'escapejs' not in m.group(1):
                    ohne.append(f'{datei.relative_to(VORLAGEN)}: {m.group(1)[:80]}')
        self.assertEqual(ohne, [])

    def test_dialogformular_ist_vom_doppelklickschutz_ausgenommen(self):
        """Sonst sperrt der Schutz «Abbrechen» nach dem ersten Mal (gemessen)."""
        self.assertIn('<form method="dialog" data-no-guard>', self._baustein())

    def test_entschluesselt_ohne_eval(self):
        self.assertNotIn('eval(', self._baustein())
        self.assertNotIn('new Function', self._baustein())


class Nachtraege(TestCase):
    """Offene Punkte aus Etappe 3, die ausserhalb von `fw/` lagen."""

    def test_anmeldeseiten_ohne_gewichte_ueber_700(self):
        """IBM Plex kommt nur bis 700; 800 wurde künstlich nachgezeichnet.
        E-Mail-Vorlagen ausgenommen: Mailprogramme nehmen Systemschriften."""
        vorlagen = Path(settings.BASE_DIR) / 'core' / 'templates' / 'core'
        zu_schwer = [f'{p.name}: {m}' for p in sorted(vorlagen.rglob('*.html'))
                     for m in re.findall(r'font-weight:\s*[89]00', p.read_text(encoding='utf-8'))]
        self.assertEqual(zu_schwer, [])

    def test_zweifaktor_qr_hat_hellen_grund(self):
        """Der Rahmen wird im Dunkelmodus dunkel; ohne eigenen Grund stünde der
        schwarze Code auf dunkler Fläche."""
        c = Client()
        c.force_login(_team_user())
        r = c.get('/konto/zwei-faktor/einrichten/')
        qr = r.context['qr']
        self.assertIn('#fff', qr)
        self.assertIn(qr, r.content.decode())

    def test_hausaushang_nimmt_die_oeffentliche_adresse(self):
        """Das Plakat hängt monatelang; der Host der Anfrage kann ein interner
        sein, den kein Mieter erreicht."""
        from unittest.mock import patch
        from django.test import override_settings
        lg, _e, _m, _v = _basis_objekte()
        c = Client()
        c.force_login(_team_user())
        with override_settings(PORTAL_BASE_URL='https://app.beispiel.ch/', ALLOWED_HOSTS=['*']), \
                patch('core.views.ticket_public.generate_qr_poster', return_value=b'%PDF-') as poster:
            c.get(f'/liegenschaft/{lg.id}/poster/', HTTP_HOST='intern.local:8000')
        self.assertEqual(poster.call_args[0][1], 'app.beispiel.ch')
