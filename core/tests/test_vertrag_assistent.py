"""Der Mietvertrag-Assistent läuft über den gemeinsamen Assistenten (27.10.2026).

Vorher hatte `/neu/vertraege/neu/` ein eigenes System: `step-nav`, `vstep`,
`fw-schrittleiste`, `fw-schritt-titel` mit eigenem Skript, eine Rahmenkarte um
Leiste und Inhalt, nur «Weiter» und keine Überzeile «Schritt i von n». Jetzt
dieselbe Komponente wie bei Liegenschaft, Person und Kündigung
(`fw-assistent`, static/js/fw-bausteine.js), mit der Live-Vorschau als
gemeinsamer Ergänzung `.fw-assistent-vorschau`.

Geprüft wird, was der Server ausliefert: die Bausteine, die sieben Schritte,
die Pflichtangaben je Schritt — und dass keine alte Klasse übrig ist, weder in
der Seite noch in der Stilschicht. Ob die Schritte im Browser wirklich
wechseln, prüft `e2e/tests/vertrag-assistent.spec.ts`.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase

from core.tests._helfer import _basis_objekte, _seed_konten, _team_user, _test_organisation

WURZEL = Path(settings.BASE_DIR)

#: Die Klassen des alten Vertrags-Assistenten. Keine davon darf wiederkommen.
ALTE_KLASSEN = ('step-nav', 'vstep', 'fw-schrittleiste', 'fw-schritt-titel', 'fw-schritt-text', 'stepitem')
ALT = re.compile(r'(?<![\w-])(' + '|'.join(re.escape(k) for k in ALTE_KLASSEN) + r')(?![\w-])')

SCHRITTE = ('Objekt', 'Personen', 'Konditionen', 'Mietzins', 'Kaution', 'Nebenkosten', 'Abschluss')


def alte_klassen(text):
    """Die alten Wizard-Namen, die in `text` vorkommen (sortiert, ohne Doppel)."""
    return sorted(set(ALT.findall(text)))


class AlteKlassenErkennung(SimpleTestCase):
    """Gegenprobe der Suche: Eine Erkennung, die nie greift, wäre immer grün."""

    def test_findet_jede_alte_klasse(self):
        for k in ALTE_KLASSEN:
            with self.subTest(k=k):
                self.assertEqual(alte_klassen(f'<div class="flex {k} p-4">'), [k])
                self.assertEqual(alte_klassen(f".{k} li{{display:none}}"), [k])

    def test_kein_fehlalarm_bei_den_neuen_namen(self):
        self.assertEqual(alte_klassen(
            '<div class="fw-assistent fw-assistent-mit-vorschau"><nav class="fw-assistent-leiste">'
            '<div class="fw-assistent-schritt-kopf"></div> data-schritt="Objekt" '
            'data-schritt-text="x" .fw-schritt-texte vstepper'), [])


class VertragAssistentTests(TestCase):
    def setUp(self):
        _seed_konten()
        _test_organisation()
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))

    def seite(self, url, status=200):
        r = self.c.get(url, secure=True)
        self.assertEqual(r.status_code, status, url)
        return r.content.decode()

    def pruefe_standard(self, html):
        # Gemeinsame Komponente: Wurzel mit Vorschau-Ergänzung, Leiste, Kopf je Schritt, Fuss
        self.assertIn('class="fw-assistent fw-assistent-mit-vorschau" id="v-assistent"', html)
        self.assertIn('data-assistent ', html)
        self.assertIn('data-stand="Schritt {i} von {n}"', html)
        self.assertIn('<nav class="fw-assistent-leiste"', html)
        self.assertIn('fw-bausteine.js', html)
        titel = re.findall(r'<section[^>]*\sdata-schritt="([^"]+)"', html)
        self.assertEqual(tuple(titel), SCHRITTE)
        self.assertEqual(html.count('<div class="fw-assistent-schritt-kopf"></div>'), len(SCHRITTE))
        fuss = html[html.index('<div class="fw-assistent-fuss">'):html.index('<aside class="fw-assistent-vorschau')]
        for teil in ('data-assistent-zurueck', 'class="stand"', 'data-assistent-weiter',
                     'data-assistent-absenden', 'Abbrechen', 'Vertrag erstellen'):
            self.assertIn(teil, fuss)
        # Live-Vorschau als Panel rechts, einklappbar, mit dem Vorschau-Rahmen
        vorschau = html[html.index('<aside class="fw-assistent-vorschau'):]
        self.assertIn('data-vorschau-knopf', vorschau)
        self.assertIn('id="pvFrame"', vorschau)
        self.assertIn('id="mietrecht-warn"', vorschau)
        # Keine eigene Schrittsteuerung, keine alten Klassen
        self.assertEqual(alte_klassen(html), [])
        for alt in ('function goStep', 'function stepMove', 'function visibleSteps'):
            self.assertNotIn(alt, html)

    def test_neuer_vertrag_kommt_als_standard_assistent(self):
        html = self.seite('/neu/vertraege/neu/')
        self.pruefe_standard(html)
        # Abbrechen führt zur Liste der Mietverhältnisse
        self.assertRegex(html, r'<a href="/neu/vertraege/[^"]*" class="fw-btn fw-geist">Abbrechen</a>')
        self.assertIn('class="fw-brotkrume', html)

    def test_pflichtangaben_je_schritt(self):
        """«Weiter» hält an, wo der Server ablehnen würde: Objekt; Mieter je nach Art."""
        html = self.seite('/neu/vertraege/neu/')
        for muster in (r'<select id="s_obj"[^>]*data-pflicht="',
                       r'<select id="s_mieter"[^>]*data-pflicht="',
                       r'<input name="nachname"[^>]*data-pflicht="',
                       r'<input name="firmen_name"[^>]*data-pflicht="'):
            self.assertRegex(html, muster)
        # Kein Pflichtzeichen für den zweiten Mieter — der ist freiwillig
        self.assertNotRegex(html, r'name="mit_nachname"[^>]*data-pflicht')

    def test_vorwahl_entwurf_und_fehler_ebenso(self):
        """Vorwahl (?einheit=), Entwurf (?edit=) und der Rückweg mit Fehlern zeigen dieselbe Komponente."""
        from rentals.models import Mietvertrag
        self.pruefe_standard(self.seite(f'/neu/vertraege/neu/?einheit={self.e.id}'))
        entwurf = Mietvertrag.objects.create(mieter=self.m, einheit=self.e, beginn=self.v.beginn,
                                             netto_mietzins=self.v.netto_mietzins, nebenkosten=self.v.nebenkosten,
                                             status='entwurf')
        html = self.seite(f'/neu/vertraege/neu/?edit={entwurf.id}')
        self.pruefe_standard(html)
        self.assertIn(f'href="/neu/vertraege/{entwurf.id}/" class="fw-btn fw-geist">Abbrechen', html)
        r = self.c.post('/neu/vertraege/neu/speichern/', {'einheit_id': '', 'mieter_id': self.m.id}, secure=True)
        self.assertEqual(r.status_code, 400)
        html = r.content.decode()
        self.pruefe_standard(html)
        # Die Meldung öffnet ihren Schritt über die Schnittstelle des Assistenten
        self.assertIn("zeigeFehler('einheit_id')", html)
        self.assertIn('ASSISTENT.fwAssistent.zeigeFeld(el)', html)


class AlteWizardRestlosEntfernt(SimpleTestCase):
    """Das CSS der alten Klassen ist gelöscht, nicht nur unbenutzt."""

    def test_quelle_erzeugnis_und_vorlagen_ohne_alte_klassen(self):
        dateien = [WURZEL / 'core/templates/fw/_schicht.html', WURZEL / 'static/css/schicht.css',
                   WURZEL / 'static/css/schicht.src.css', WURZEL / 'static/js/fw-bausteine.js']
        dateien += sorted((WURZEL / 'core/templates').rglob('*.html'))
        funde = {d.relative_to(WURZEL).as_posix(): alte_klassen(d.read_text(encoding='utf-8'))
                 for d in dateien}
        self.assertEqual({d: k for d, k in funde.items() if k}, {})

    def test_gemeinsame_komponente_kann_was_der_vertrag_braucht(self):
        js = (WURZEL / 'static/js/fw-bausteine.js').read_text(encoding='utf-8')
        for teil in ("'fw-assistent:zeige'", 'zeigeFeld:', "'fw-assistent:vorschau'", '[data-vorschau-knopf]'):
            self.assertIn(teil, js)
        css = (WURZEL / 'static/css/schicht.css').read_text(encoding='utf-8')
        for teil in ('.fw-assistent-vorschau{', '.fw-assistent.an.fw-assistent-mit-vorschau{grid-template-columns:232px'):
            self.assertIn(teil, css)
