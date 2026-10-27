"""Drei weitere mehrstufige Seiten im Assistenten-Standard (27.10.2026).

2FA-Einrichtung (server-seitig: Schritte mit eigener Adresse, Zustand in der Datenbank), Serienbrief
(«Mitteilungs-Assistent») und Abnahme vor Ort einrichten (client-seitig: ein Formular bzw. eine
Seite, ein Abschluss). Gleiche Klassen, gleiche Leiste, derselbe Fuss wie bei den anderen
Assistenten (`fw/_assistent_server.html`, `static/js/fw-bausteine.js`).

Was Django sehen kann, prüfen diese Tests: Markup, Reihenfolge der Schritte, was auf welcher Seite
nicht stehen darf (Schlüssel und QR nach Schritt 1), und dass die alten Klassen aus Vorlagen und
Stilschicht verschwunden sind. Ob die Seiten bei 390 px ohne Quer-Scrollen stehen, messen
`e2e/tests/zwei-faktor-assistent.spec.ts`, `serienbrief-assistent.spec.ts` und
`abnahme-neu-assistent.spec.ts` im Browser.
"""
import pathlib
import re

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Wiederherstellungscode, ZweiterFaktor
from core.services import totp
from core.services.assistent import server_assistent

from ._helfer import _basis_objekte, _team_user
from .test_zweifaktor import ZweiFaktorBasis

WURZEL = pathlib.Path(settings.BASE_DIR)
VORLAGEN = WURZEL / 'core' / 'templates'


def _fuss(html):
    """Nur der Fuss des Assistenten (die Seite danach kennt andere «Abbrechen»)."""
    ab = html[html.index('class="fw-assistent-fuss"'):]
    return ab[:ab.index('</div>\n    </div>')]


def _leiste(html):
    nav = re.search(r'<nav class="fw-assistent-leiste".*?</nav>', html, re.S)
    assert nav, 'keine Leiste'
    return re.findall(r'<li class="([^"]*)">(.*?)</li>', nav.group(0), re.S)


class SchrittOhneZielTests(SimpleTestCase):
    """Neu im Rahmen: ein Schritt ohne `url` ist kein Link, ohne dass er «gesperrt» aussieht."""

    SCHRITTE = [{'nr': 1, 'titel': 'Eins', 'zustand': 'fertig'},
                {'nr': 2, 'titel': 'Zwei', 'zustand': 'gesperrt', 'url': '/2/'},
                {'nr': 3, 'titel': 'Drei', 'zustand': 'offen', 'url': '/3/'}]

    def test_link_nur_mit_ziel_und_nie_gesperrt(self):
        a = server_assistent(self.SCHRITTE, 3, abbrechen_url=None)
        self.assertEqual([s['link'] for s in a['schritte']], [False, False, True])

    def test_eigene_seite_ohne_ziel_ist_kein_link_behaelt_aber_hier(self):
        a = server_assistent([{'nr': 1, 'titel': 'Eins'}], 1, abbrechen_url='/')
        self.assertEqual((a['schritte'][0]['link'], a['schritte'][0]['hier']), (False, True))


class EinrichtungImStandardTests(ZweiFaktorBasis):
    """2FA: Code scannen, Code bestätigen, Notfallcodes — server-seitig."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.benutzer)
        self.url = reverse('zweifaktor_einrichten')

    def _faktor(self):
        return ZweiterFaktor.objects.get(benutzer=self.benutzer)

    def test_schritt_eins_im_rahmen_des_standards(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('class="fw-assistent an"', html)
        for klasse in ('fw-assistent-leiste', 'fw-assistent-schritt-kopf', 'fw-assistent-fuss'):
            self.assertIn(f'class="{klasse}"', html)
        # Überzeile, Stand unter der Leiste und Fuss: überall dieselbe Schrittzahl.
        self.assertEqual(html.count('Schritt 1 von 3'), 3)
        self.assertNotRegex(html, r'Schritt \d+ von [^3]')
        lis = _leiste(html)
        self.assertEqual([k for k, _ in lis], ['offen hier', 'offen', 'gesperrt'])
        self.assertIn(f'href="{self.url}?schritt=2"', lis[1][1])
        self.assertNotIn('href=', lis[2][1])
        self.assertIn(f'<a href="{self.url}?schritt=2" class="fw-btn fw-primary">', html)
        self.assertIn(f'<a href="{reverse("zweifaktor_uebersicht")}" class="fw-btn fw-geist">Abbrechen</a>', html)
        self.assertIn('<button type="button" class="fw-btn" disabled>', html)    # kein Zurück im ersten Schritt
        # Die Eigenklassen und der Inline-Stil von früher sind weg.
        self.assertNotIn('style="width:200px"', html)
        self.assertNotIn('max-w-2xl', html)

    def test_schluessel_und_qr_stehen_nur_in_schritt_eins(self):
        """Datenschutz: Das Geheimnis wird nicht öfter angezeigt als nötig — Schritt 2 fragt nur den Code."""
        self.client.get(self.url)
        geheimnis = self._faktor().geheimnis
        eins = self.client.get(self.url)
        self.assertContains(eins, geheimnis)
        self.assertContains(eins, '<svg')
        zwei = self.client.get(self.url + '?schritt=2')
        self.assertNotContains(zwei, geheimnis)
        self.assertNotContains(zwei, 'fw-zf-qr')
        self.assertNotIn('qr', zwei.context)
        self.assertNotIn('geheimnis', zwei.context)

    def test_schritt_zwei_hat_das_codefeld_und_die_aktion_im_fuss(self):
        html = self.client.get(self.url + '?schritt=2').content.decode()
        self.assertEqual(html.count('Schritt 2 von 3'), 3)
        lis = _leiste(html)
        self.assertEqual([k for k, _ in lis], ['fertig', 'offen hier', 'gesperrt'])
        self.assertIn('<span class="nr" aria-hidden="true">✓</span>', lis[0][1])
        self.assertIn('<form method="post" id="zf-code"', html)
        self.assertIn('autocomplete="one-time-code"', html)
        fuss = _fuss(html)
        self.assertIn('<button type="submit" form="zf-code" class="fw-btn fw-primary">', fuss)
        self.assertIn(f'<a href="{self.url}" class="fw-btn">', fuss)          # Zurück zu Schritt 1

    def test_falscher_code_bleibt_in_schritt_zwei_und_aktiviert_nicht(self):
        self.client.get(self.url)
        antwort = self.client.post(self.url, {'code': '000000'})
        self.assertEqual(antwort.status_code, 200)
        html = antwort.content.decode()
        self.assertIn('Der Code stimmt nicht', html)
        self.assertEqual([k for k, _ in _leiste(html)], ['fertig', 'offen hier', 'gesperrt'])
        self.assertFalse(self._faktor().ist_aktiv)
        self.assertEqual(Wiederherstellungscode.objects.filter(benutzer=self.benutzer).count(), 0)

    def test_richtiger_code_aktiviert_und_zeigt_schritt_drei_ohne_weg_zurueck(self):
        self.client.get(self.url)
        faktor = self._faktor()
        antwort = self.client.post(self.url, {'code': totp.code(faktor.geheimnis)})
        faktor.refresh_from_db()
        self.assertTrue(faktor.ist_aktiv)
        self.assertEqual(Wiederherstellungscode.objects.filter(benutzer=self.benutzer).count(), 10)
        html = antwort.content.decode()
        self.assertEqual(html.count('Schritt 3 von 3'), 3)
        lis = _leiste(html)
        self.assertEqual([k for k, _ in lis], ['fertig', 'fertig', 'offen hier'])
        # Die Liste erscheint genau einmal: keine Adresse, also auch kein Link zurück.
        self.assertNotIn('href=', lis[0][1])
        self.assertNotIn('href=', lis[1][1])
        self.assertNotIn('href=', lis[2][1])
        fuss = _fuss(html)
        self.assertNotIn('Abbrechen', fuss)
        self.assertIn('<button type="button" class="fw-btn" disabled>', fuss)
        self.assertIn(f'<a href="{reverse("zweifaktor_uebersicht")}" class="fw-btn fw-primary">', fuss)
        # Alle zehn Codes stehen auf der Seite.
        self.assertEqual(len(re.findall(r'<div class="fw-feld fw-mono select-all">[0-9a-f]{5}-[0-9a-f]{5}</div>', html)), 10)

    def test_keine_seite_der_einrichtung_wird_zwischengespeichert(self):
        """Datenschutz: Geheimnis und Notfallcodes dürfen nicht im Browser-Cache landen."""
        self.client.get(self.url)
        faktor = self._faktor()
        schritt1 = self.client.get(self.url)
        schritt2 = self.client.get(self.url + '?schritt=2')
        codes = self.client.post(self.url, {'code': totp.code(faktor.geheimnis)})
        for name, antwort in (('1', schritt1), ('2', schritt2), ('3', codes)):
            with self.subTest(schritt=name):
                self.assertIn('no-store', antwort['Cache-Control'])

    def test_bei_aktivem_faktor_fuehrt_die_einrichtung_zur_uebersicht(self):
        self.faktor_aktivieren()
        for adresse in (self.url, self.url + '?schritt=2'):
            self.assertRedirects(self.client.get(adresse), reverse('zweifaktor_uebersicht'),
                                 fetch_redirect_response=False)

    def test_notfallcodes_neu_erzeugen_ist_keine_assistentenseite(self):
        self.faktor_aktivieren()
        antwort = self.client.post(reverse('zweifaktor_codes_neu'))
        self.assertTemplateUsed(antwort, 'core/zweifaktor_codes_neu.html')
        self.assertTemplateNotUsed(antwort, 'fw/_assistent_server.html')
        self.assertNotContains(antwort, 'fw-assistent')
        self.assertContains(antwort, 'Ich habe sie gesichert')
        self.assertContains(antwort, 'Diese Liste erscheint genau einmal.')
        self.assertEqual(Wiederherstellungscode.objects.filter(benutzer=self.benutzer).count(), 10)


class AbnahmeNeuImStandardTests(TestCase):

    def setUp(self):
        self.lg, self.einheit, _m, self.vertrag = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())
        self.url = f'/neu/vertraege/{self.vertrag.id}/abnahme/vorort/'

    def test_zwei_schritte_im_client_assistenten(self):
        html = self.c.get(self.url).content.decode()
        self.assertRegex(html, r'<div class="fw-assistent" id="vn" data-assistent ')
        self.assertEqual(html.count('data-schritt="'), 2)
        self.assertIn('data-schritt="Allgemein"', html)
        self.assertIn('data-schritt="Struktur"', html)
        self.assertEqual(html.count('class="fw-assistent-schritt-kopf"'), 2)
        self.assertIn('class="fw-assistent-leiste"', html)
        fuss = html[html.index('class="fw-assistent-fuss"'):]
        self.assertIn('data-assistent-zurueck', fuss)
        self.assertIn('data-assistent-weiter', fuss)
        self.assertIn(f'<a href="/neu/vertraege/{self.vertrag.id}/" class="fw-btn fw-geist">Abbrechen</a>', fuss)
        self.assertRegex(fuss, r'<button type="submit" class="fw-btn fw-primary" data-assistent-absenden>.*Abnahme erstellen')
        # Ohne Skript bleibt es ein Formular mit Textfeldern für die Räume.
        self.assertIn('<form method="post" action="' + self.url + '" id="vnForm" novalidate>', html)
        self.assertGreater(html.count('<input name="raum"'), 3)

    def test_alter_aufbau_ist_weg(self):
        html = self.c.get(self.url).content.decode()
        seite = html[html.index('<form method="post" action="' + self.url):]
        for alt in ('vn-reiter', 'data-seite', 'vn-fuss', 'vn-feld', 'vn-zeile', 'vn-hinweis'):
            self.assertNotIn(alt, seite)
        text = (VORLAGEN / 'fw' / 'abnahme_vorort_neu.html').read_text(encoding='utf-8')
        self.assertNotRegex(text, r'\bvn-[a-z]')
        self.assertNotIn('<style', text)
        self.assertNotIn('data-tab', text)
        for datei in ('schicht.css', 'schicht.src.css'):
            css = (WURZEL / 'static' / 'css' / datei).read_text(encoding='utf-8')
            self.assertNotRegex(css, r'\.vn[ -]', datei)

    def test_ohne_raum_beginnt_der_assistent_beim_schritt_struktur(self):
        """Die Fehlermeldung betrifft die Räume: `aria-invalid` am Raumfeld holt den Assistenten dorthin."""
        r = self.c.post(self.url, {'typ': 'auszug', 'raum': ['', ' ']})
        self.assertContains(r, 'Mindestens ein Raum ist nötig')
        self.assertRegex(r.content.decode(), r'<ul class="fw-abn-liste" id="vnListe" aria-invalid="true">')
        self.assertNotContains(self.c.get(self.url), 'aria-invalid')

    def test_entwurf_wird_als_hinweis_angeboten(self):
        self.c.post(self.url, {'typ': 'auszug', 'raum': ['Küche']})
        html = self.c.get(self.url).content.decode()
        self.assertRegex(html, r'(?s)<div class="fw-hinweis info">(?:(?!</div>).)*Es gibt einen offenen Entwurf.*?Entwurf fortsetzen')


class SerienbriefImStandardTests(TestCase):

    def setUp(self):
        _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def test_drei_schritte_mit_vorschau(self):
        html = self.c.get('/neu/kommunikation/').content.decode()
        self.assertIn('class="fw-assistent fw-assistent-mit-vorschau" id="mk-assistent" data-assistent', html)
        self.assertEqual(re.findall(r'<section data-schritt="([^"]*)"', html), ['Empfänger', 'Mitteilung', 'Versand'])
        self.assertEqual(html.count('class="fw-assistent-schritt-kopf"'), 3)
        # Die Vorschau ist die gemeinsame Ergänzung des Standards und enthält den Brief.
        start = html.index('<aside class="fw-assistent-vorschau')
        aside = html[start:html.index('</aside>', start)]
        for kennung in ('id="brief"', 'id="pv-empfaenger"', 'id="pv-text"', 'data-vorschau-knopf'):
            self.assertIn(kennung, aside)
        fuss = html[html.index('class="fw-assistent-fuss"'):]
        self.assertIn('data-assistent-zurueck', fuss)
        self.assertIn('data-assistent-weiter', fuss)
        self.assertIn('class="fw-btn fw-geist"', fuss)
        self.assertIn('id="mk-los"', fuss)
        self.assertIn('data-assistent-absenden', fuss)

    def test_funktion_bleibt_versandarten_und_ziele(self):
        """Drei Versandarten wie vorher, dieselben zwei Formulare mit denselben Zielen."""
        html = self.c.get('/neu/kommunikation/').content.decode()
        self.assertEqual(re.findall(r'name="mk-art" value="(\w+)"', html), ['pdf', 'mail', 'druck'])
        self.assertIn('id="pdfForm" method="post" action="/neu/kommunikation/serienbrief/"', html)
        self.assertIn('id="mailForm" method="post" action="/neu/kommunikation/senden/"', html)
        for funktion in ('serienbriefPdf()', 'perEmailSenden()', 'druckeVorschau()', 'versandAusfuehren()'):
            self.assertIn(funktion, html)

    def test_weiter_verlangt_einen_empfaenger_und_einen_text(self):
        """Die Pflicht prüft fw-bausteine.js über die Gültigkeit der Felder dieses Schritts."""
        html = self.c.get('/neu/kommunikation/').content.decode()
        self.assertIn("getElementById('emp-search').setCustomValidity(", html)
        self.assertRegex(html, r'<textarea id="nachricht"[^>]*data-pflicht="Bitte einen Text verfassen\."')

    def test_alte_dreikartenseite_ist_weg(self):
        html = self.c.get('/neu/kommunikation/').content.decode()
        self.assertNotIn('fw-avci', html)               # die Nummern der alten Karten
        self.assertNotIn('lg:sticky', html)             # die alte Vorschauspalte
        self.assertNotIn('min-h-[500px]', html)
        text = (VORLAGEN / 'fw' / 'kommunikation.html').read_text(encoding='utf-8')
        self.assertNotIn('<!--', text)            # Vorlagen kommentieren mit {% comment %} (test_kein_kommentar_sichtbar)


class KlassenDefiniertTests(SimpleTestCase):
    """Jede Klasse der drei Seiten mit unserem Präfix steht in der ausgelieferten Stilschicht."""

    SEITEN = ('core/zweifaktor_einrichten.html', 'core/zweifaktor_codes.html', 'core/zweifaktor_codes_neu.html',
              'core/_zweifaktor_codes_karte.html', 'fw/abnahme_vorort_neu.html', 'fw/kommunikation.html')

    def _gebraucht(self):
        klassen = set()
        for seite in self.SEITEN:
            text = (VORLAGEN / seite).read_text(encoding='utf-8')
            for attr in re.findall(r'class="([^"]*)"', text):
                klassen.update(k for k in attr.split() if re.match(r'fw-(zf|abn|mk)-|fw-brief$', k))
        return klassen

    def test_gebrauchte_klassen_sind_definiert(self):
        css = (WURZEL / 'static' / 'css' / 'schicht.css').read_text(encoding='utf-8')
        gebraucht = self._gebraucht()
        self.assertGreater(len(gebraucht), 15)
        # Mit Grenze: `.fw-zf-code` darf nicht durch `.fw-zf-codes` als definiert gelten.
        fehlt = sorted(k for k in gebraucht if not re.search(rf'\.{re.escape(k)}(?![\w-])', css))
        self.assertEqual(fehlt, [])

    def test_eigene_klassen_der_alten_seiten_sind_verschwunden(self):
        quelle = (VORLAGEN / 'fw' / '_schicht.html').read_text(encoding='utf-8')
        self.assertNotRegex(quelle, r'\.vn-')
