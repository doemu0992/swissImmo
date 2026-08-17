"""Die Nachzählung des Umzugs zählt wirklich — nicht nur Fehler.

`bestand_zaehlen` ist die Kontrolle vor und nach dem Datenbankumzug: zwei
Listen, ein `diff`, und man weiss, ob alles angekommen ist. Der Befehl fängt
Ausnahmen je Modell ab und schreibt `FEHLER:<Typ>` statt einer Zahl — richtig
gedacht, denn eine unlesbare Tabelle soll auffallen und nicht fehlen.

Genau dieser Auffangmechanismus hat aber den eigenen Ausfall verdeckt: Seit
Etappe 6.2 wirft `Model.objects` ohne Mandantenkontext, und ein
Management-Command hat keinen. Der Befehl lief also weiterhin durch, mit einer
Zeile `FEHLER:OrganisationsFehler` je Modell — und ein `diff` zweier solcher
Listen ist grün, obwohl nichts gezählt wurde. Die Absicherung des Umzugs hätte
nichts abgesichert.

Deshalb prüft dieser Testsatz nicht, dass der Befehl LÄUFT, sondern dass er
ZAHLEN liefert.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from ._isolation import MandantenFixture


class NachzaehlungTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def zaehlen(self):
        raus = StringIO()
        call_command('bestand_zaehlen', stdout=raus)
        return raus.getvalue().strip().split('\n')

    def test_keine_zeile_meldet_einen_fehler(self):
        fehlerzeilen = [z for z in self.zaehlen() if 'FEHLER:' in z]
        self.assertEqual(fehlerzeilen, [],
                         'Die Nachzählung meldet Fehler statt Zahlen — ein diff '
                         'zweier solcher Listen wäre grün, ohne etwas zu belegen.')

    def test_mandantendaten_werden_ueber_alle_verwaltungen_gezaehlt(self):
        # Der Umzug bewegt die ganze Datenbank. Zählte der Befehl nur den
        # Bestand einer Verwaltung, fehlte nach dem Umzug alles andere — und
        # der Vergleich wäre trotzdem grün, weil beide Seiten gleich falsch sind.
        from rentals.models import Mietvertrag

        zeilen = {z.rsplit(' ', 1)[0]: z.rsplit(' ', 1)[1] for z in self.zaehlen()}
        self.assertEqual(zeilen['rentals.Mietvertrag'],
                         str(Mietvertrag.alle_organisationen.count()))
        self.assertGreaterEqual(int(zeilen['rentals.Mietvertrag']), 2,
                                'Beide Verwaltungen haben einen Vertrag — es wurde '
                                'nur der Bestand einer gezählt.')

    def test_pruefe_erkennt_eine_abweichung(self):
        # Gegenprobe: Ohne diesen Test wäre nicht belegt, dass `--pruefe`
        # überhaupt vergleicht statt immer Erfolg zu melden.
        import tempfile

        vorher = self.zaehlen()
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False,
                                         encoding='utf-8') as datei:
            datei.write('\n'.join(vorher).replace('rentals.Mietvertrag 2',
                                                  'rentals.Mietvertrag 99'))
            pfad = datei.name

        with self.assertRaises(SystemExit):
            call_command('bestand_zaehlen', pruefe=pfad, stdout=StringIO(), stderr=StringIO())

    def test_pruefe_meldet_erfolg_bei_gleichem_bestand(self):
        import tempfile

        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False,
                                         encoding='utf-8') as datei:
            datei.write('\n'.join(self.zaehlen()))
            pfad = datei.name

        raus = StringIO()
        call_command('bestand_zaehlen', pruefe=pfad, stdout=raus, stderr=StringIO())
        self.assertIn('identisch', raus.getvalue())


class ModellOhneTabelleTests(TestCase):
    """Die Nachzählung bricht an einem Modell ohne Tabelle nicht ab.

    `Model.objects.count()` auf eine fehlende Tabelle warf einen
    `OperationalError`, den der Auffangmechanismus als
    `FEHLER:OperationalError` protokollierte — eine Zeile, die den
    Ausnahmetyp trägt und nicht sagt, WAS fehlt. Jetzt steht dort
    `OHNE-TABELLE`: auf beiden Seiten des Umzugs identisch, solange die
    Tabelle beidseits fehlt, und im `diff` sofort sichtbar, sobald sie nur
    auf einer Seite fehlt.
    """

    def test_meldet_ohne_tabelle_statt_eines_ausnahmetyps(self):
        import core.tests.test_tenant_manager  # noqa: F401  (registriert Haus/Zimmer)
        from django.apps import apps

        self.assertIn('core.Haus', [m._meta.label for m in apps.get_models()],
                      'Testmodell nicht registriert — dieser Test prüft dann nichts.')

        raus = StringIO()
        call_command('bestand_zaehlen', stdout=raus)
        zeilen = raus.getvalue().strip().split('\n')

        self.assertIn('core.Haus OHNE-TABELLE', zeilen)
        self.assertEqual([z for z in zeilen if 'FEHLER:' in z], [],
                         'Ein Modell ohne Tabelle wird als Ausnahmetyp gemeldet '
                         'statt benannt.')
