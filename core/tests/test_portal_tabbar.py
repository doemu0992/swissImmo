"""Untere Leiste der Portale am Telefon (`core/templatetags/portal_tabs.py`): Belegung, aktive Seite, nichts nur in der Leiste."""
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from core.templatetags.portal_tabs import portal_tabbar, portal_zeichen


def _kontext(pfad):
    return {'request': SimpleNamespace(path=pfad, user=AnonymousUser())}


class PortalTabbarTests(SimpleTestCase):
    def _hier(self, pfad):
        d = portal_tabbar(_kontext(pfad))
        return [t['text'] for t in d['tabs'] if t['hier']], d['mehr_hier']

    def test_je_portal_vier_ziele_und_hoechstens_ein_plus(self):
        for pfad in ('/mieter/', '/portal/', '/betreiber/'):
            tabs = portal_tabbar(_kontext(pfad))['tabs']
            self.assertEqual(len(tabs), 4, pfad)
            self.assertLessEqual(sum(t['plus'] for t in tabs), 1, pfad)

    def test_aktiv_ist_die_seite_und_unterseiten_zaehlen_mit(self):
        self.assertEqual(self._hier('/mieter/'), (['Übersicht'], False))
        self.assertEqual(self._hier('/mieter/tickets/7/'), (['Meldungen'], False))
        self.assertEqual(self._hier('/portal/abrechnungen/'), (['Abrechnung'], False))
        self.assertEqual(self._hier('/betreiber/protokoll/'), (['Protokoll'], False))

    def test_seite_ohne_eigenen_tab_markiert_mehr_und_nicht_die_uebersicht(self):
        # «Meine Daten» liegt unter /mieter/, hat aber keinen Tab: Die Übersicht darf nicht als aktiv erscheinen.
        self.assertEqual(self._hier('/mieter/daten/'), ([], True))
        self.assertEqual(self._hier('/betreiber/3/abo/'), ([], True))

    def test_ausserhalb_der_portale_gibt_es_keine_leiste(self):
        self.assertEqual(portal_tabbar(_kontext('/neu/heute/'))['tabs'], [])
        self.assertNotIn('pTabbar', render_to_string('core/_portal_tabbar.html', portal_tabbar(_kontext('/neu/heute/'))))

    def test_kein_ziel_steht_nur_in_der_unteren_leiste(self):
        """Absolute Regel «nichts geht verloren»: Jedes Ziel der Leiste steht auch in der vollständigen Liste (`#pSidebar`)."""
        from django.urls import reverse
        vorlagen = Path(settings.BASE_DIR) / 'core' / 'templates' / 'core'
        mieter = (vorlagen / '_mieter_nav.html').read_text()
        for t in portal_tabbar(_kontext('/mieter/'))['tabs']:
            self.assertIn(f'href="{t["ziel"]}"', mieter)
        eig = (vorlagen / '_eig_nav.html').read_text()
        for name in ('portal', 'portal_abrechnungen', 'portal_liegenschaften', 'portal_dokumente'):
            self.assertIn("{% url '" + name + "' %}", eig)
            self.assertIn(reverse(name), [t['ziel'] for t in portal_tabbar(_kontext('/portal/'))['tabs']])
        betreiber = (vorlagen / 'betreiber_base.html').read_text()
        for name in ('betreiber', 'fw_betreiber_protokoll', 'fw_betreiber_lik'):
            self.assertIn("{% url '" + name + "' %}", betreiber)

    def test_gerendert_mehr_oeffnet_die_leiste_und_plus_traegt_einen_namen(self):
        html = render_to_string('core/_portal_tabbar.html', portal_tabbar(_kontext('/mieter/')))
        self.assertIn('id="pTabbar"', html)
        self.assertIn('data-bei-klick="pOpenNav"', html)
        self.assertIn('aria-label="Schaden melden"', html)
        self.assertEqual(html.count('aria-current="page"'), 1)

    def test_markenzeichen_je_portal(self):
        self.assertEqual([portal_zeichen(_kontext(p)) for p in ('/mieter/', '/portal/', '/betreiber/')],
                         ['schluessel', 'liegenschaft', 'gesperrt'])
