"""DESIGN-01 / DESIGN-02 / ROUTE-03 / ROUTE-10 / ROUTE-13: Fehlerseiten und Kopfzeile je Rolle.

BEFUND (Audit 28.10.2026)
- Die 403-/404-/500-Seiten führten mit «Zur Übersicht» immer nach `/neu/`. Für die
  Hauswartung, Mieter und Eigentümer ist `/neu/` selbst eine 403-Seite: Die Fehlerseite
  verwies auf sich selbst.
- Die Kopfzeile der Hauswartung bot «+», Glocke, Zahnrad, «Akten» an (alle 403), und
  jede Seite fragte `/neu/leistenzahlen/` ab (403 im Hintergrund).
- «Neuer Fall» im Kopf rief `fwModalOpen` auf, das auf 186 von 205 Seiten nicht geladen
  ist (ReferenceError).

Gegenprobe: In `403.html` das Ziel wieder auf `/neu/` stellen — `test_fehlerseite_fuehrt_nie_
auf_eine_fehlerseite` wird für Hauswart, Mieter und Eigentümer rot.
"""
import re

from django.test import Client

from .test_rbac import RbacBasis


def _ziel(html):
    """Das Ziel der Schaltfläche «Zur Übersicht» einer Fehlerseite."""
    treffer = re.search(r'<a [^>]*href="([^"]+)"[^>]*class="mt-6 fw-btn fw-primary"', html)
    if treffer is None:                      # 500: das Ziel trägt eine Id
        treffer = re.search(r'<a id="fehlerZiel" href="([^"]+)"', html)
    assert treffer, 'Kein Ziel auf der Fehlerseite gefunden'
    return treffer.group(1)


class FehlerseitenZielTests(RbacBasis):

    def _rollen(self):
        # (Name, Benutzer, eine Adresse, die dieser Rolle 403 gibt)
        return [
            ('Verwalter', self.u_verwalter, '/neu/benutzer/neu/'),
            ('Lesezugriff', self.u_lesend, '/neu/benutzer/neu/'),
            ('Hauswart', self.u_hauswart, '/neu/faelle/neu/'),
            ('Mieter', self.u_mieter, '/neu/'),
            ('Eigentümer', self.u_eigentuemer, '/neu/'),
        ]

    def test_fehlerseite_fuehrt_nie_auf_eine_fehlerseite(self):
        """403 und 404, je Rolle: Das Ziel von «Zur Übersicht» ist eine Seite, die diese Rolle öffnen darf."""
        for name, benutzer, verboten in self._rollen():
            for art, adresse, status in (('403', verboten, 403),
                                         ('404', '/diese-adresse-gibt-es-nicht/', 404)):
                with self.subTest(rolle=name, fehler=art):
                    c = Client()
                    c.force_login(benutzer)
                    seite = c.get(adresse)
                    self.assertEqual(seite.status_code, status)
                    ziel = _ziel(seite.content.decode())
                    ende = c.get(ziel, follow=True)
                    self.assertEqual(ende.status_code, 200,
                                     f'{name}: «Zur Übersicht» ({ziel}) endet auf {ende.redirect_chain}')
                    self.assertNotIn('Dafür fehlt Ihrer Rolle die Berechtigung', ende.content.decode())

    def test_ziel_je_rolle(self):
        erwartet = {'Verwalter': '/nach-login/', 'Lesezugriff': '/nach-login/',
                    'Hauswart': '/nach-login/', 'Mieter': '/nach-login/',
                    'Eigentümer': '/nach-login/'}
        endpunkte = {'Verwalter': '/neu/', 'Lesezugriff': '/neu/', 'Hauswart': '/neu/schaeden/',
                     'Mieter': '/mieter/', 'Eigentümer': '/portal/'}
        for name, benutzer, verboten in self._rollen():
            with self.subTest(rolle=name):
                c = Client()
                c.force_login(benutzer)
                ziel = _ziel(c.get(verboten).content.decode())
                self.assertEqual(ziel, erwartet[name])
                # Die Login-Weiche leitet rollengerecht weiter.
                antwort = c.get(ziel)
                self.assertEqual(antwort.status_code, 302)
                self.assertEqual(antwort['Location'], endpunkte[name])

    def test_portalpfade_fuehren_direkt_ins_eigene_portal(self):
        c = Client()
        c.force_login(self.u_mieter)
        self.assertEqual(_ziel(c.get('/mieter/gibt-es-nicht/').content.decode()), '/mieter/')
        c = Client()
        c.force_login(self.u_eigentuemer)
        self.assertEqual(_ziel(c.get('/portal/gibt-es-nicht/').content.decode()), '/portal/')

    def test_gast_landet_bei_der_anmeldung(self):
        c = Client()
        seite = c.get('/diese-adresse-gibt-es-nicht/')
        self.assertEqual(seite.status_code, 404)
        ziel = _ziel(seite.content.decode())
        ende = c.get(ziel, follow=True)
        self.assertEqual(ende.status_code, 200)
        self.assertIn('/login/', ende.redirect_chain[-1][0])

    def test_500_seite_hat_die_login_weiche_als_ziel(self):
        from django.template.loader import render_to_string
        self.assertEqual(_ziel(render_to_string('500.html', {})), '/nach-login/')


class HauswartKopfzeileTests(RbacBasis):

    ZIELE_DES_TEAMS = ('/neu/faelle/neu/', '/neu/zulauf/', '/neu/einstellungen/',
                       '/neu/dokumente/', '/neu/kommunikation/', '/neu/liegenschaften/',
                       '/neu/leistenzahlen/')

    def _seite(self, benutzer, adresse):
        c = Client()
        c.force_login(benutzer)
        antwort = c.get(adresse)
        self.assertEqual(antwort.status_code, 200)
        return antwort.content.decode()

    def test_hauswart_bekommt_nur_ziele_angeboten_die_er_oeffnen_darf(self):
        for adresse in ('/neu/schaeden/', '/neu/schaeden/board/'):
            html = self._seite(self.u_hauswart, adresse)
            kopf = html[html.index('id="fwKopf"'):html.index('<main class="fw-inhalt">')]
            for ziel in self.ZIELE_DES_TEAMS:
                with self.subTest(adresse=adresse, ziel=ziel):
                    self.assertNotIn(ziel, kopf)
            self.assertIn('href="/neu/schaeden/" class="fw-kapsel fw-logo-kapsel"', kopf)
            # Die Brotkrume «Akten /» (Ziel /neu/liegenschaften/) steht nicht mehr da,
            # und die Zähler-Abfrage wird nicht gesendet.
            self.assertNotIn('/neu/liegenschaften/', html)
        # Das Skript bricht vor dem Abruf ab (kein Netzaufruf, kein 403 im Hintergrund).
        self.assertRegex(html, r"classList\.contains\('_embed'\)\) return;\s*return;")

    def test_gegenprobe_das_team_sieht_alles_und_fragt_die_zaehler_ab(self):
        """Ohne diesen Gegenpol wäre der Test oben auch für eine kaputte Seite grün."""
        html = self._seite(self.u_verwalter, '/neu/schaeden/')
        kopf = html[html.index('id="fwKopf"'):html.index('<main class="fw-inhalt">')]
        for ziel in ('/neu/faelle/neu/', '/neu/zulauf/', '/neu/einstellungen/'):
            self.assertIn(ziel, kopf)
        self.assertIn('/neu/liegenschaften/', html)
        self.assertIn("fetch('/neu/leistenzahlen/'", html)
        self.assertNotRegex(html, r"classList\.contains\('_embed'\)\) return;\s*return;")

    def test_hauswart_seite_ist_bis_ins_profilmenue_frei_von_403_zielen(self):
        html = self._seite(self.u_hauswart, '/neu/schaeden/')
        menue = html[html.index('id="fwProfil"'):html.index('<main class="fw-inhalt">')]
        for ziel in ('/neu/dokumente/', '/neu/kommunikation/', '/neu/einstellungen/', '/neu/faelle/neu/'):
            self.assertNotIn(ziel, menue)
        self.assertIn('/logout/', menue)

    def test_zwei_faktor_seite_fuer_mieter_zeigt_die_team_ziele_nicht(self):
        """ROUTE-03(c): Die 2FA-Seite rendert für Portal-Rollen in derselben Hülle."""
        html = self._seite(self.u_mieter, '/konto/zwei-faktor/')
        kopf = html[html.index('id="fwKopf"'):html.index('<main class="fw-inhalt">')]
        for ziel in self.ZIELE_DES_TEAMS:
            self.assertNotIn(ziel, kopf)
        self.assertIn('href="/nach-login/" class="fw-kapsel fw-logo-kapsel"', kopf)


class NeuerFallOhneModalTests(RbacBasis):
    """ROUTE-10: «Neuer Fall» fällt auf den Link zurück, wo die Schublade nicht geladen ist."""

    def test_aufruf_prueft_ob_die_funktion_da_ist(self):
        c = Client()
        c.force_login(self.u_verwalter)
        antwort = c.get('/neu/personen/')
        self.assertEqual(antwort.status_code, 200)
        html = antwort.content.decode()
        self.assertNotIn('function fwModalOpen', html)       # auf dieser Seite nicht geladen
        aufrufe = re.findall(r'onclick="[^"]*fwModalOpen\(this', html)
        self.assertTrue(aufrufe)
        for a in aufrufe:
            self.assertIn('window.fwModalOpen ?', a)         # sonst ReferenceError
