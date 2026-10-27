"""Server-seitiger Assistent im Standard (27.10.2026): Rahmen, Zustände, NK-Wizard, Einstieg.

Der NK-Wizard hatte eigene Klassen (`fw-nkw-*`), erledigte Schritte grün statt im Akzent und
im Fuss weder «Schritt i von n» noch «Abbrechen». Die Einstiegsseite sagte im Untertitel
«Schritt 1 von 6» und in der Leiste «Schritt 1 von 2». Diese Tests halten fest, dass beides
vorbei ist: dieselben Klassen wie der client-seitige Assistent, eine Schrittzahl je Seite.

Die Farben selbst misst e2e/tests/nk-wizard.spec.ts im Browser.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

from core.services.assistent import ZUSTAENDE, server_assistent

from .test_nk_wizard import SCHRITTE, _Basis

WURZEL = pathlib.Path(settings.BASE_DIR)


def _leiste(html):
    """Nur die Schrittleiste: die <li> mit Klasse und Inhalt."""
    nav = re.search(r'<nav class="fw-assistent-leiste".*?</nav>', html, re.S)
    assert nav, 'keine Leiste'
    return re.findall(r'<li class="([^"]*)">(.*?)</li>', nav.group(0), re.S)


class ServerAssistentTests(SimpleTestCase):
    SCHRITTE = [{'nr': 1, 'titel': 'Eins', 'zustand': 'fertig', 'url': '/1/'},
                {'nr': 2, 'titel': 'Zwei', 'zustand': 'warnung', 'url': '/2/', 'info': '1 Hinweis'},
                {'nr': 3, 'titel': 'Drei', 'zustand': 'gesperrt', 'url': '/3/'}]

    def test_aktuell_nachbarn_und_stand(self):
        a = server_assistent(self.SCHRITTE, 2, abbrechen_url='/liste/')
        self.assertEqual((a['i'], a['n'], a['schritt']['titel']), (2, 3, 'Zwei'))
        self.assertEqual((a['zurueck']['nr'], a['weiter']['nr']), (1, 3))
        self.assertEqual([s['hier'] for s in a['schritte']], [False, True, False])
        erster = server_assistent(self.SCHRITTE, 1, abbrechen_url='/liste/')
        self.assertIsNone(erster['zurueck'])
        self.assertIsNone(server_assistent(self.SCHRITTE, 3, abbrechen_url='/liste/')['weiter'])

    def test_unbekannter_zustand_wird_abgewiesen(self):
        """`erledigt` ist der Zustand der Prozessleiste, nicht des Assistenten — still als
        «offen» gezeichnet wäre er der Fehler aus den bekannten Fallen, Nr. 9."""
        self.assertEqual(ZUSTAENDE, ('offen', 'fertig', 'warnung', 'gesperrt', 'entfaellt'))
        with self.assertRaises(ValueError):
            server_assistent([{**self.SCHRITTE[0], 'zustand': 'erledigt'}], 1, abbrechen_url='/')

    def test_aktueller_schritt_muss_in_der_leiste_stehen(self):
        with self.assertRaises(ValueError):
            server_assistent(self.SCHRITTE, 7, abbrechen_url='/')


class NkWizardImStandardTests(_Basis):
    def test_jeder_schritt_nutzt_den_rahmen_des_standards(self):
        for i, teil in enumerate(SCHRITTE, 1):
            with self.subTest(schritt=teil):
                r = self.c.get(self.basis + teil + '/')
                self.assertEqual(r.status_code, 200)
                html = r.content.decode()
                self.assertIn('class="fw-assistent an"', html)
                for klasse in ('fw-assistent-leiste', 'fw-assistent-schritt-kopf', 'fw-assistent-fuss'):
                    self.assertIn(f'class="{klasse}"', html)
                self.assertNotIn('fw-nkw', html)
                # Kein `data-assistent`: fw-bausteine.js soll die Seite nicht umbauen.
                self.assertNotIn('data-assistent ', html)
                # Überzeile, Stand unter der Leiste und Fuss sagen dasselbe.
                self.assertEqual(html.count(f'Schritt {i} von 6'), 3)
                self.assertRegex(html, r'<a href="/neu/nebenkosten/" class="fw-btn fw-geist">Abbrechen</a>')
                lis = _leiste(html)
                self.assertEqual(len(lis), 6)
                hier = [n for n, (klasse, _) in enumerate(lis, 1) if 'hier' in klasse.split()]
                self.assertEqual(hier, [i])
                self.assertIn(f'href="{self.basis}{teil}/" aria-current="step"', lis[i - 1][1])
                if i > 1:
                    self.assertIn(f'<a href="{self.basis}{SCHRITTE[i - 2]}/" class="fw-btn">', html)
                if i < 6:
                    self.assertIn(f'<a href="{self.basis}{SCHRITTE[i]}/" class="fw-btn fw-primary">', html)

    def test_zustaende_in_der_leiste(self):
        """Kosten da → «Kosten» fertig (✓); ohne HKVO entfällt «Heizung & Zähler» (–), bleibt aber
        ein Link, denn dort schaltet man sie ein."""
        lis = _leiste(self.c.get(self.basis + 'periode/').content.decode())
        kosten, heizung = lis[1], lis[3]
        self.assertEqual(kosten[0].split(), ['fertig'])
        self.assertIn('<span class="nr" aria-hidden="true">✓</span>', kosten[1])
        self.assertEqual(heizung[0].split(), ['entfaellt'])
        self.assertIn('<span class="nr" aria-hidden="true">–</span>', heizung[1])
        self.assertIn(f'href="{self.basis}heizung/"', heizung[1])
        for klasse, _ in lis:
            self.assertTrue(set(klasse.split()) <= set(ZUSTAENDE) | {'hier'}, klasse)

    def test_ohne_kosten_ist_verteilung_gesperrt_und_kein_link(self):
        self.p.belege.all().delete()
        html = self.c.get(self.basis + 'kosten/').content.decode()
        verteilung = _leiste(html)[2]
        self.assertEqual(verteilung[0].split(), ['gesperrt'])
        self.assertNotIn('href=', verteilung[1])
        self.assertIn('Verteilung: erst nach den Kosten möglich', html)
        self.assertNotIn(f'<a href="{self.basis}verteilung/" class="fw-btn fw-primary">', html)

    def test_schritt_sechs_hat_die_aktion_im_fuss(self):
        html = self.c.get(self.basis + 'abschluss/').content.decode()
        fuss = html[html.index('class="fw-assistent-fuss"'):]
        self.assertIn('<button form="nk-verbuchen" class="fw-btn fw-primary">', fuss)
        self.assertIn(f'action="/neu/nebenkosten/{self.p.id}/verbuchen/" id="nk-verbuchen"', html)
        # Nach dem Verbuchen: keine Aktion mehr im Fuss, «Schliessen» statt «Abbrechen».
        self.verbuchen()
        html = self.c.get(self.basis + 'abschluss/').content.decode()
        fuss = html[html.index('class="fw-assistent-fuss"'):]
        self.assertNotIn('nk-verbuchen', html)
        self.assertNotIn('fw-primary', fuss[:fuss.index('</div>\n    </div>')])
        self.assertIn('class="fw-btn fw-geist">Schliessen</a>', fuss)


class EinstiegImStandardTests(_Basis):
    def test_einstieg_zeigt_sechs_schritte_und_ueberall_eins_von_sechs(self):
        r = self.c.get('/neu/nebenkosten/neu/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('class="fw-assistent an"', html)
        self.assertNotIn('fw-nkw', html)
        self.assertNotIn('data-assistent ', html)
        # Untertitel, Überzeile, Stand unter der Leiste, Fuss — und nirgends «von 2».
        self.assertEqual(html.count('Schritt 1 von 6'), 4)
        self.assertNotRegex(html, r'Schritt \d+ von [^6]')
        lis = _leiste(html)
        self.assertEqual([k for k, _ in lis], ['offen hier'] + ['gesperrt'] * 5)
        for _, inhalt in lis[1:]:
            self.assertNotIn('href=', inhalt)
        self.assertIn('<button type="button" class="fw-btn" disabled>', html)
        self.assertIn('<form method="post" action="/neu/nebenkosten/neu/" id="nk-neu">', html)
        self.assertIn('<button form="nk-neu" class="fw-btn fw-primary">', html)

    def test_absenden_legt_an_und_fuehrt_zu_schritt_eins(self):
        """Wie vor der Umstellung: nach /periode/ — dort geht Schritt 1 mit den Objekten weiter."""
        from finance.models import AbrechnungsPeriode
        r = self.c.post('/neu/nebenkosten/neu/', {'liegenschaft_id': self.lg.id, 'bezeichnung': 'NK 2026',
                                                  'start_datum': '2026-01-01', 'ende_datum': '2026-12-31'})
        p = AbrechnungsPeriode.objects.get(bezeichnung='NK 2026')
        self.assertRedirects(r, f'/neu/nebenkosten/{p.id}/periode/', fetch_redirect_response=False)
        self.assertContains(self.c.get(f'/neu/nebenkosten/{p.id}/periode/'), 'Schritt 1 von 6')

    def test_fehler_bleiben_im_rahmen(self):
        r = self.c.post('/neu/nebenkosten/neu/', {'liegenschaft_id': '', 'bezeichnung': '',
                                                  'start_datum': '', 'ende_datum': ''})
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, 'class="fw-assistent an"', status_code=400)
        self.assertContains(r, 'aria-invalid="true"', status_code=400)


class KeineNkwKlassenTests(SimpleTestCase):
    def test_fw_nkw_ist_aus_vorlagen_quelle_und_erzeugnis_verschwunden(self):
        dateien = list((WURZEL / 'core' / 'templates').rglob('*.html'))
        dateien += [WURZEL / 'static' / 'css' / n for n in ('schicht.css', 'schicht.src.css')]
        dateien += list((WURZEL / 'static' / 'js').glob('*.js'))
        treffer = [str(d.relative_to(WURZEL)) for d in dateien if 'fw-nkw' in d.read_text(encoding='utf-8')]
        self.assertEqual(treffer, [])
