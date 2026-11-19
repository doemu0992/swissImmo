"""Avatar-Kürzel (UI-Zielbild, Phase 0, Befund 13): «DG» statt «Do»."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from core.templatetags.kuerzel import kuerzel


def _p(voll='', username='e2e'):
    return SimpleNamespace(get_full_name=lambda: voll, username=username)


class KuerzelTests(SimpleTestCase):

    def test_vor_und_nachname(self):
        self.assertEqual(kuerzel(_p('Dominic Gerber')), 'DG')

    def test_mehrere_vornamen_erster_und_letzter(self):
        self.assertEqual(kuerzel(_p('Anna Maria von Gunten')), 'AG')

    def test_nur_ein_name(self):
        self.assertEqual(kuerzel(_p('Cher')), 'CH')

    def test_ohne_namen_der_benutzername(self):
        self.assertEqual(kuerzel(_p('', 'e2e')), 'E2')
        self.assertEqual(kuerzel(_p('   ', 'sw')), 'SW')

    def test_kleinbuchstaben_werden_gross(self):
        self.assertEqual(kuerzel(_p('dominic gerber')), 'DG')

    def test_auch_ein_name_als_text(self):
        self.assertEqual(kuerzel('Hans Muster'), 'HM')
        self.assertEqual(kuerzel('  '), '')

    def test_kein_benutzer(self):
        self.assertEqual(kuerzel(None), '')

    def test_gegenprobe_der_alte_weg_gab_den_namensanfang(self):
        """Warum der Filter gebraucht wird: das Alte ergab «Do» für Dominic Gerber."""
        self.assertEqual('Dominic Gerber'[:2].upper(), 'DO')


class KeinNamensanfangAlsKuerzelTests(SimpleTestCase):
    def test_vorlagen_schneiden_namen_nicht_selbst_ab(self):
        """Avatare tragen das Kürzel aus `kuerzel`, nicht die ersten zwei Zeichen eines Namens."""
        import pathlib
        import re
        from django.conf import settings
        treffer = []
        for pfad in (pathlib.Path(settings.BASE_DIR) / 'core/templates').rglob('*.html'):
            if re.search(r'(username|display_name|get_full_name|\.name|\.wer|absender_name)[^}]*slice:":2"\|upper',
                         pfad.read_text(encoding='utf-8')):
                treffer.append(pfad.name)
        self.assertEqual(treffer, [], 'Kürzel von Hand abgeschnitten: stattdessen |kuerzel')
