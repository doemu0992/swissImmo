"""Die Befunde des Mandanten-Audits vom 18.08.2026 — je Fund ein Test.

Der Auditlauf ging über den Gesamtdiff der Etappe 6 (`d0b5d39..HEAD`, 20
Commits, 102 Dateien) statt über die einzelnen PRs. Die Begründung dafür hat
sich bestätigt: **Lücken entstehen an den Nahtstellen.** Jeder einzelne PR war
für sich geprüft; gefunden wurden Dinge, die erst sichtbar werden, wenn man
Manager, Views, Hintergrundläufe und Dateiablage nebeneinander liest.

Wie in `test_anonyme_einstiegspunkte.py` gilt: `MandantenFixture`, und
NIRGENDS ein beiläufig gesetzter Kontext.
"""
from django.test import Client, TestCase
from django.urls import reverse

from ._isolation import MandantenFixture


class ZweiBestaende(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.client = Client(raise_request_exception=False)


# Der Datenreset-Fund (Leck 1) wird NICHT hier geprüft, sondern in
# `test_plattform.DatenResetTests.test_reset_von_a_laesst_den_bestand_von_b_stehen`
# — bei den übrigen Reset-Tests, wo ihn findet, wer an der View arbeitet.
#
# Hier stand kurzzeitig eine zweite Klasse `DatenresetTests`, die sich vom
# bestehenden `DatenResetTests` nur durch ein kleines r unterschied. Zwei
# fast gleichnamige Klassen für dieselbe Zusage in zwei Dateien sind genau
# die Art Doppelung, bei der später jemand die eine ändert und die andere
# übersieht.


class KeinRatenDerVerwaltungTests(ZweiBestaende):
    """Vier `Organisation.objects.first()` überlebten hinter dem Alias `_Vw`.

    `from crm.models import Organisation as _Vw` … `_Vw.objects.first()`.
    `Organisation` trägt bewusst keinen `TenantManager` — die vier Aufrufe
    ignorierten den Kontext also vollständig und lieferten immer die erste
    Verwaltung der Installation:

    * das **Verwaltungshonorar** auf jeder Nebenkostenabrechnung,
    * der Absenderblock **inklusive IBAN** der Weiterverrechnung,
    * **Referenzzins und LIK** als Basis einer Anpassung nach OR 269a,
    * ein toter `or`-Rückfall in der Vertragserstellung.

    Und der eigentliche Fund: `grep "Organisation.objects.first()"` fand sie
    nicht. Der geplante Abschlussvermerk «von 76 auf 0» wäre falsch gewesen.
    Deshalb prüft der Test unten auf das MUSTER, nicht auf die Zeichenkette.
    """

    def test_kein_objects_first_auf_der_organisation(self):
        import ast
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parent.parent.parent
        treffer = []
        for datei in wurzel.rglob('*.py'):
            teile = set(datei.parts)
            if teile & {'migrations', 'tests', '.venv', 'node_modules'}:
                continue
            if datei.name.startswith('test_'):
                continue
            try:
                baum = ast.parse(datei.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            # Welche lokalen Namen zeigen in dieser Datei auf `Organisation`?
            namen = {'Organisation'}
            for knoten in ast.walk(baum):
                if isinstance(knoten, ast.ImportFrom):
                    for alias in knoten.names:
                        if alias.name == 'Organisation' and alias.asname:
                            namen.add(alias.asname)
            for knoten in ast.walk(baum):
                if (isinstance(knoten, ast.Call)
                        and isinstance(knoten.func, ast.Attribute)
                        and knoten.func.attr == 'first'
                        and isinstance(knoten.func.value, ast.Attribute)
                        and knoten.func.value.attr == 'objects'
                        and isinstance(knoten.func.value.value, ast.Name)
                        and knoten.func.value.value.id in namen):
                    treffer.append(f'{datei.relative_to(wurzel)}:{knoten.lineno}')

        self.assertEqual(treffer, [],
                         'Die Verwaltung wird geraten statt vom Datensatz genommen: '
                         + ', '.join(treffer))

    def test_der_waechter_findet_das_muster_auch_unter_einem_alias(self):
        # Gegenprobe zum Wächter selbst: Ohne sie wäre nicht belegt, dass er
        # den Alias erfasst — und genau daran ist die letzte Zählung
        # gescheitert.
        import ast

        quelle = ('from crm.models import Organisation as _Vw\n'
                  'x = _Vw.objects.first()\n')
        baum = ast.parse(quelle)
        namen = {'Organisation'}
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.ImportFrom):
                for alias in knoten.names:
                    if alias.name == 'Organisation' and alias.asname:
                        namen.add(alias.asname)
        self.assertIn('_Vw', namen, 'Der Wächter erkennt den Alias nicht.')


class FehlversuchProtokollTests(ZweiBestaende):
    """Fehlgeschlagene Anmeldungen hinterliessen keine Spur mehr.

    Eine anonyme Anmeldeseite hat keinen Mandantenkontext, `AktivitaetsLog`
    verlangt aber eine Organisation. Ohne Benutzer fand `log_aktion` keine, das
    Schreiben warf, und `log_aktion` schluckt Ausnahmen bewusst — damit ein
    misslungener Protokolleintrag nicht die eigentliche Aktion abbricht.

    Gemessen im Audit: vor der Etappe 546 → 547 Einträge, danach 546 → 546.
    Brute-Force-Versuche gegen die Installation waren damit unsichtbar, obwohl
    die Kategorie `sicherheit` als revisionsrelevant gilt.
    """

    def test_fehlversuch_auf_ein_bestehendes_konto_wird_protokolliert(self):
        from core.models import AktivitaetsLog

        vorher = AktivitaetsLog.alle_organisationen.count()
        self.client.post(reverse('login'),
                         {'username': self.b.benutzer.username, 'password': 'falsch'})
        nachher = AktivitaetsLog.alle_organisationen.count()

        self.assertGreater(nachher, vorher,
                           'Der Fehlversuch hinterlässt keine Spur im Logbuch.')
        eintrag = AktivitaetsLog.alle_organisationen.order_by('-pk').first()
        self.assertEqual(eintrag.aktion, 'Anmeldung fehlgeschlagen')
        self.assertEqual(eintrag.organisation_id, self.b.organisation.pk,
                         'Der Eintrag landete in der falschen Verwaltung.')


class GeteiltesKontoPortalTests(ZweiBestaende):
    """Portalzugänge reissen fremde Konten nicht mehr mit.

    Dieselbe Wurzel wie bei `fw_benutzer_loeschen`, nur an den Portalpfaden:
    `benutzer.delete()` entfernte das Konto überall — samt Mitgliedschaften
    (CASCADE) und samt der Verknüpfung zu fremden Profilen (SET_NULL).
    """

    def test_konto_mit_fremder_mitgliedschaft_bleibt_bestehen(self):
        from benutzer.models import Benutzer
        from core.auth import konto_freigeben
        from crm.models import Mitgliedschaft

        # Ein Mensch: Portalkonto bei A, Teammitglied bei B.
        konto = Benutzer.objects.create_user(username='doppelt', password='x')
        Mitgliedschaft.alle_organisationen.create(
            benutzer=konto, organisation=self.b.organisation,
            rolle=Mitgliedschaft.ROLLE_VERWALTER)

        geloescht = konto_freigeben(konto, self.a.organisation)

        self.assertFalse(geloescht)
        self.assertTrue(Benutzer.objects.filter(pk=konto.pk).exists(),
                        'Das Konto wurde gelöscht, obwohl B es noch braucht.')
        self.assertTrue(
            Mitgliedschaft.alle_organisationen.filter(
                benutzer=konto, organisation=self.b.organisation).exists())

    def test_gegenprobe_ein_konto_ohne_bezug_wird_geloescht(self):
        from benutzer.models import Benutzer
        from core.auth import konto_freigeben

        konto = Benutzer.objects.create_user(username='allein', password='x')
        self.assertTrue(konto_freigeben(konto, self.a.organisation))
        self.assertFalse(Benutzer.objects.filter(pk=konto.pk).exists())
