"""Mandantenwechsel und «Zuletzt geöffnet» stehen im Profilmenü (28.10.2026).

WARUM

Beide standen nur in der Schublade `#fwSidebar`. Die ist ab 1024 px aus; bis
1023 px erreichte man sie über «Menü öffnen» im Profilmenü, am PC gar nicht.
Wer für zwei Verwaltungen arbeitet, konnte dort den Mandanten nicht wechseln.

WAS DIESE DATEI HÄLT

Die Struktur und die Bindungen, die kein Browsertest einzeln sieht: dieselben
Ziele und Bedingungen wie in der Schublade, die Ids, die das Skript füllt, die
Wirkung des Wechsels über das Formular des Profilmenüs. Wie es bei 1280 und
390 px aussieht, misst `e2e/tests/profilmenue-mandant.spec.ts`.
"""
import pathlib
import re

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase

from core.middleware_tenancy import SESSION_SCHLUESSEL

from ._isolation import MandantenFixture
from .test_kopfzeile_omnisearch import baum, eines, finde

WURZEL = pathlib.Path(settings.BASE_DIR)
BASIS = (WURZEL / 'core' / 'templates' / 'fw' / 'base.html').read_text(encoding='utf-8')
SCHICHT = (WURZEL / 'core' / 'templates' / 'fw' / '_schicht.html').read_text(encoding='utf-8')


def _steht_in(knoten, id):
    return any(v.attrs.get('id') == id for v in knoten.vorfahren())


def _optionen(auswahl):
    return [(k.attrs.get('value'), 'selected' in k.attrs) for k in auswahl.alle() if k.tag == 'option']


class ProfilmenueMandantTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    @classmethod
    def tearDownClass(cls):
        from core.tenancy import loesche_organisation
        loesche_organisation()
        super().tearDownClass()

    def _zweite_mitgliedschaft(self, firma='Verwaltung C AG'):
        from crm.models import Mitgliedschaft, Organisation
        org = Organisation.objects.create(firma=firma, strasse='C-Weg 1', plz='6000', ort='Luzern')
        Mitgliedschaft.alle_organisationen.create(
            benutzer=self.a.benutzer, organisation=org, rolle=Mitgliedschaft.ROLLE_VERWALTER)
        return org

    def _seite(self, pfad='/neu/', client=None):
        c = client or Client()
        c.force_login(self.a.benutzer)
        r = c.get(pfad)
        self.assertEqual(r.status_code, 200, pfad)
        return baum(r.content.decode('utf-8'))

    # ---- Wer ihn sieht -------------------------------------------------

    def test_mit_einer_organisation_gibt_es_keinen_wechsel_weder_im_profilmenue_noch_in_der_schublade(self):
        wurzel = self._seite()
        profil = eines(wurzel, id='fwProfil')
        self.assertEqual(finde(profil, tag='select'), [], 'Das Profilmenü bietet einen Wechsel ohne Auswahl an')
        self.assertEqual(finde(profil, id='fwMandantWahlProfil'), [])
        self.assertEqual(finde(wurzel, id='fwMandantWahl'), [], 'Die Schublade zeigt ihn dort auch nicht')
        formulare = [k for k in profil.alle() if k.tag == 'form' and k.attrs.get('action') == '/neu/mandant/']
        self.assertEqual(formulare, [])

    def test_mit_mehreren_organisationen_steht_der_wechsel_im_profilmenue(self):
        dritte = self._zweite_mitgliedschaft()
        wurzel = self._seite()
        profil = eines(wurzel, id='fwProfil')

        form = [k for k in profil.alle() if k.tag == 'form' and k.attrs.get('action') == '/neu/mandant/']
        self.assertEqual(len(form), 1, 'Das Profilmenü braucht genau ein Formular zum Wechseln')
        self.assertEqual(form[0].attrs['method'], 'post')
        csrf = [k for k in form[0].alle() if k.tag == 'input' and k.attrs.get('name') == 'csrfmiddlewaretoken']
        self.assertEqual(len(csrf), 1, 'Ein POST ohne CSRF-Token würde abgewiesen')

        auswahl = eines(form[0], tag='select')
        self.assertEqual(auswahl.attrs['name'], 'organisation')
        self.assertEqual(auswahl.attrs['id'], 'fwMandantWahlProfil')
        self.assertIn('submit', auswahl.attrs['onchange'])
        self.assertTrue(auswahl.attrs.get('aria-label'))
        self.assertIn('fw-feld', auswahl.klassen)
        # Eine sichtbare Beschriftung gehört zur Auswahl
        beschriftung = [k for k in form[0].alle() if k.tag == 'label' and k.attrs.get('for') == 'fwMandantWahlProfil']
        self.assertEqual(len(beschriftung), 1)

        # Genau die eigenen Organisationen, die aktive ist gewählt — nicht die fremde
        optionen = _optionen(auswahl)
        eigene = {str(self.a.organisation.id), str(dritte.id)}
        self.assertEqual({w for w, _ in optionen}, eigene)
        self.assertNotIn(str(self.b.organisation.id), {w for w, _ in optionen})
        self.assertEqual([w for w, s in optionen if s], [str(self.a.organisation.id)])

    def test_profilmenue_und_schublade_bieten_dieselben_organisationen_an(self):
        self._zweite_mitgliedschaft()
        wurzel = self._seite()
        schublade = _optionen(eines(wurzel, id='fwMandantWahl'))
        profil = _optionen(eines(wurzel, id='fwMandantWahlProfil'))
        self.assertEqual(profil, schublade)
        self.assertTrue(_steht_in(eines(wurzel, id='fwMandantWahl'), 'fwSidebar'))
        self.assertTrue(_steht_in(eines(wurzel, id='fwMandantWahlProfil'), 'fwProfil'))
        self.assertFalse(_steht_in(eines(wurzel, id='fwMandantWahlProfil'), 'fwSidebar'))

    def test_der_wechsel_ueber_das_formular_des_profilmenues_wirkt(self):
        """Den Wert nehmen, den die Seite selbst anbietet — und danach prüfen, was die Seite zeigt."""
        dritte = self._zweite_mitgliedschaft('Verwaltung C AG')
        c = Client()
        c.force_login(self.a.benutzer)
        wurzel = self._seite(client=c)
        form = [k for k in eines(wurzel, id='fwProfil').alle() if k.tag == 'form' and k.attrs.get('action') == '/neu/mandant/'][0]
        anderer = [w for w, s in _optionen(eines(form, tag='select')) if not s]
        self.assertEqual(anderer, [str(dritte.id)])

        antwort = c.post(form.attrs['action'], {'organisation': anderer[0]})
        self.assertIn(antwort.status_code, (302, 303))
        self.assertEqual(c.session.get(SESSION_SCHLUESSEL), dritte.id)

        danach = self._seite(client=c)
        gewaehlt = [w for w, s in _optionen(eines(danach, id='fwMandantWahlProfil')) if s]
        self.assertEqual(gewaehlt, [str(dritte.id)], 'Nach dem Wechsel steht im Profilmenü noch der alte Mandant')

    def test_der_firmenname_wird_maskiert(self):
        self._zweite_mitgliedschaft('Müller & <b>Söhne</b> AG')
        c = Client()
        c.force_login(self.a.benutzer)
        html = c.get('/neu/').content.decode('utf-8')
        profil = html[html.index('id="fwProfil"'):]
        self.assertNotIn('<b>Söhne</b>', profil[:profil.index('id="fwZuletztProfil"')])
        self.assertIn('Müller &amp; &lt;b&gt;Söhne&lt;/b&gt; AG', profil)

    # ---- Zuletzt geöffnet ---------------------------------------------

    def test_zuletzt_geoeffnet_hat_einen_abschnitt_im_profilmenue(self):
        wurzel = self._seite()
        profil = eines(wurzel, id='fwProfil')
        abschnitt = eines(profil, id='fwZuletztProfilAbschnitt')
        self.assertIn('hidden', abschnitt.attrs, 'Ohne Einträge zeigt das Menü keine leere Überschrift')
        self.assertEqual(abschnitt.attrs['role'], 'group')
        titel = eines(abschnitt, id='fwZuletztProfilTitel')
        self.assertEqual(abschnitt.attrs['aria-labelledby'], titel.attrs['id'])
        liste = eines(abschnitt, id='fwZuletztProfil')
        self.assertIn('fw-profil-zuletzt', liste.klassen)

    def test_die_liste_im_profilmenue_traegt_nicht_die_klasse_der_schublade(self):
        """`.fw-zuletzt` wird bei zugeklappter Leiste (`html._sbc`) ausgeblendet — das Profilmenü bliebe leer."""
        wurzel = self._seite()
        self.assertNotIn('fw-zuletzt', eines(wurzel, id='fwZuletztProfil').klassen)
        self.assertIn('fw-zuletzt', eines(wurzel, id='fwZuletzt').klassen)

    def test_die_schublade_behaelt_ihre_liste(self):
        wurzel = self._seite()
        self.assertTrue(_steht_in(eines(wurzel, id='fwZuletzt'), 'fwSidebar'))
        self.assertTrue(_steht_in(eines(wurzel, id='fwZuletztTitel'), 'fwSidebar'))

    def test_jede_id_die_das_skript_fuellt_gibt_es_genau_einmal(self):
        """Das Skript füllt beide Listen aus einer Tabelle; eine Id, die es nicht gibt, überspringt es still."""
        paare = re.findall(r"\['(fwZuletzt\w*)', '(fwZuletzt\w*)'\]", BASIS)
        self.assertEqual(len(paare), 2, 'Das Skript füllt nicht genau zwei Listen')
        wurzel = self._seite()
        for liste, titel in paare:
            with self.subTest(liste=liste):
                eines(wurzel, id=liste)
                eines(wurzel, id=titel)
        # Und es füllt aus EINER Datenquelle, nicht aus zwei Kopien
        self.assertEqual(BASIS.count("localStorage.getItem('fw-zuletzt')"), 1)
        self.assertEqual(BASIS.count('document.createElement(\'a\')'), 1, 'Der Code zum Füllen steht doppelt')

    def test_das_skript_kuerzt_die_liste_auf_drei_eintraege(self):
        self.assertIn('.slice(0, 3)', BASIS)

    def test_ids_im_profilmenue_sind_eindeutig(self):
        """Zwei Auswahlen und zwei Listen auf einer Seite: keine Id darf doppelt vorkommen."""
        self._zweite_mitgliedschaft()
        wurzel = self._seite()
        ids = [k.attrs['id'] for k in wurzel.alle() if 'id' in k.attrs]
        doppelt = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(doppelt, [])


class ProfilmenueSchichtTests(SimpleTestCase):
    """Die Regeln stehen in der Schicht, im eigenen Block vor dem Kopfzeilenblock."""

    def test_eigener_modulblock_steht_vor_dem_kopfzeilenblock(self):
        anfang = '/* ===== MODUL Profilmenue Mandant (28.10.2026) ===== */'
        ende = '/* ===== Ende MODUL Profilmenue Mandant ===== */'
        kopf = '/* ===== MODUL Kopfzeile und Omnisearch (27.10.2026) ===== */'
        self.assertEqual(SCHICHT.count(anfang), 1)
        self.assertLess(SCHICHT.index(anfang), SCHICHT.index(ende))
        self.assertLess(SCHICHT.index(ende), SCHICHT.index(kopf))

    def test_jede_neue_klasse_hat_eine_regel(self):
        anfang = SCHICHT.index('/* ===== MODUL Profilmenue Mandant')
        block = SCHICHT[anfang:SCHICHT.index('/* ===== Ende MODUL Profilmenue Mandant')]
        for klasse in ('fw-profil-mandant', 'fw-profil-zuletzt'):
            with self.subTest(klasse=klasse):
                self.assertRegex(block, rf'\.{klasse}[\s{{.:]')
        # Das Menü kann nicht quer scrollen, Namen werden gekürzt
        self.assertRegex(block, r'\.fw-profil\{overflow-x:hidden\}')
        self.assertRegex(block, r'\.fw-profil-mandant select\{[^}]*text-overflow:ellipsis')
        self.assertRegex(block, r'\.fw-profil-zuletzt[^{]*\.truncate\{[^}]*text-overflow:ellipsis')

    def test_der_block_nutzt_nur_tokens_fuer_farben(self):
        anfang = SCHICHT.index('/* ===== MODUL Profilmenue Mandant')
        block = SCHICHT[anfang:SCHICHT.index('/* ===== Ende MODUL Profilmenue Mandant')]
        code = re.sub(r'/\*.*?\*/', ' ', block, flags=re.S)
        self.assertIsNone(re.search(r'#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(', code), 'Eine Farbe steht ausserhalb der Tokens')
