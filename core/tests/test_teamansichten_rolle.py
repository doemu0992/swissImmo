"""Jede Ansicht unter /neu/ prüft die Rolle — und eine, die es nicht tat.

BEFUND (Rollen-Rundgang, 28.09.2026)
`fw_wartungsfrist_neu` trug keinen `@rolle_erforderlich`. Die Rolle
«Lesezugriff» konnte damit per POST Wartungs- und Versicherungsfristen an
jeder Liegenschaft ihrer Verwaltung anlegen. Der Dekorator stand stattdessen
DOPPELT über `fw_budget_speichern`, der Funktion davor — dritter Fall von
`bekannte-fallen` Nr. 3 («Ein Dekorator bindet an die nächste Definition»).

Die Register-Prüfung unten ist das Gegenmittel für die ganze Klasse: Sie
liest die Rollen an JEDER aufgelösten URL unter /neu/ ab (`benoetigte_rollen`,
vom Dekorator gesetzt). Ein verrutschter Dekorator fällt dort auf, nicht erst
im Betrieb. `RollentrennungTests` in test_sicherheit.py prüft nur Views, die
den Dekorator schon tragen — diese hier fiel genau durch diese Lücke.

Gegenprobe: Mit dem Dekorator entfernt sind die ersten beiden Tests und die
Register-Prüfung rot.
"""
from datetime import date

from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver

from portfolio.models import Liegenschaft, Wartungsfrist
from core.tests._helfer import _team_user, _test_organisation

#: URLs unter /neu/, die bewusst OHNE Rollenprüfung erreichbar sind.
#: Jeder Eintrag braucht eine Begründung.
OHNE_ROLLE_ERLAUBT = {
    'neu/vermarktung/feed.json':
        'Objekt-Feed für Immobilienportale; ohne Anmeldung, per ?token= der '
        'Organisation abgesichert (fw_vermarktung_feed)',
    'neu/assets/':
        'reine Weiterleitung auf /neu/ersatzplanung/, die ihrerseits prüft',
}


def _alle_muster(muster, praefix=''):
    for m in muster:
        if isinstance(m, URLResolver):
            yield from _alle_muster(m.url_patterns, praefix + str(m.pattern))
        elif isinstance(m, URLPattern):
            yield praefix + str(m.pattern), m.callback


class WartungsfristRolleTests(TestCase):

    def setUp(self):
        org = _test_organisation()
        self.lg = Liegenschaft.objects.create(
            organisation=org, strasse='Bahnhofstrasse 1', plz='8001', ort='Zürich')
        self.url = f'/neu/liegenschaften/{self.lg.pk}/frist/'
        self.daten = {'bezeichnung': 'Liftwartung', 'naechste_faelligkeit': '2027-01-31',
                      'art': 'wartung', 'intervall_monate': '12'}

    def _anzahl(self):
        return Wartungsfrist.objects.filter(liegenschaft=self.lg).count()

    def test_lesezugriff_legt_keine_frist_an(self):
        self.client.force_login(_team_user('Lesezugriff'))
        antwort = self.client.post(self.url, self.daten)
        self.assertEqual(antwort.status_code, 403)
        self.assertEqual(self._anzahl(), 0)

    def test_ohne_anmeldung_zur_anmeldung(self):
        antwort = self.client.post(self.url, self.daten)
        self.assertEqual(antwort.status_code, 302)
        self.assertIn('/login/', antwort['Location'])
        self.assertEqual(self._anzahl(), 0)

    def test_sachbearbeiter_legt_frist_an(self):
        """Gegenstück — sonst bestünden die Prüfungen oben auch dann, wenn
        das Erfassen für niemanden mehr funktioniert."""
        self.client.force_login(_team_user('Sachbearbeiter'))
        self.client.post(self.url, self.daten)
        frist = Wartungsfrist.objects.get(liegenschaft=self.lg)
        self.assertEqual(frist.bezeichnung, 'Liftwartung')
        self.assertEqual(frist.naechste_faelligkeit, date(2027, 1, 31))


class JedeTeamansichtPrueftRolleTests(TestCase):

    def test_jede_url_unter_neu_traegt_eine_rollenpruefung(self):
        geprueft, offen = 0, []
        for route, view in _alle_muster(get_resolver().url_patterns):
            if not route.startswith('neu/'):
                continue
            geprueft += 1
            if getattr(view, 'benoetigte_rollen', None) or route in OHNE_ROLLE_ERLAUBT:
                continue
            offen.append(route)
        # Leser-Kontrolle: Findet er gar nichts, ist er kaputt, nicht die App.
        self.assertGreater(geprueft, 100)
        self.assertEqual(offen, [], 'Ohne @rolle_erforderlich erreichbar: ' + ', '.join(offen))

    def test_die_ausnahmeliste_ist_nicht_verwaist(self):
        """Eine Ausnahme muss auf eine URL zeigen, die es gibt — sonst befreit
        sie beim nächsten gleichnamigen Pfad stillschweigend von der Prüfung."""
        routen = {r for r, _ in _alle_muster(get_resolver().url_patterns)}
        self.assertEqual(sorted(set(OHNE_ROLLE_ERLAUBT) - routen), [])
