"""Die Zustellfrist einer Mietzinsänderung hat zwei Stufen.

ART. 269D ABS. 1 OR

Der Vermieter muss eine Erhöhung mit **amtlichem Formular** und Begründung
mindestens **zehn Tage vor Beginn der Kündigungsfrist** zustellen, wirksam auf
einen Kündigungstermin.

DER FEHLER, DEN DIESE REGEL VERHINDERT

Die zehn Tage zählen nicht ab dem Termin, sondern ab dem **Beginn der
Kündigungsfrist** — und der liegt seinerseits eine ganze Kündigungsfrist vor
dem Termin.

    Termin                        31.03.2027
    Kündigungsfrist 3 Monate  →   Beginn 31.12.2026
    minus 10 Tage             →   Zustellung bis 21.12.2026

Wer die zehn Tage direkt vom Termin abzieht, landet auf dem 21.03.2027 — drei
Monate zu spät, und die Erhöhung ist nichtig.

NICHT DREISSIG TAGE

Im Bestand stand an einer Stelle »30 Tage Vorlauf« (`automation.py`, zur
Indexanpassung). Das ist die verbreitete Verwechslung mit der Anfechtungsfrist
des Mieters nach Art. 270b OR: Die beträgt dreissig Tage, läuft aber ab
Empfang und in die andere Richtung. Der Gesetzestext im Bestand
(`gesetzestexte.py`) nennt korrekt zehn Tage.

DIE FOLGE

Eine zu spät zugestellte Erhöhung ist **nichtig** (Art. 269d Abs. 2 OR) —
nicht auf den nächsten Termin verschoben. Sie muss neu zugestellt werden, und
bis dahin gilt der alte Mietzins. Bei einer Erhöhung von 150 Franken und einem
Termin pro Jahr sind das 1'800 Franken, die niemand mehr holt.
"""
from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.tests._isolation import MandantenFixture
from core.tenancy import organisation_kontext as mandant
from faelle.regelwerk import mietzins_zustellung, pruefen
from faelle.regelwerk_models import Regel, Regelsatz


class ZustellfristTest(TestCase):

    def test_der_letzte_zulaessige_tag_wird_vorgeschlagen(self):
        befund = mietzins_zustellung(termin=date(2027, 3, 31))
        self.assertTrue(befund.ok)
        self.assertEqual(befund.vorschlag, date(2026, 12, 21))
        self.assertIn('31.12.2026', befund.meldung,
                      'Die Meldung nennt den Beginn der Kündigungsfrist '
                      'nicht — dann ist die Rechnung nicht nachvollziehbar.')

    def test_die_zehn_tage_zaehlen_nicht_ab_dem_termin(self):
        """Der Fehler, um den es geht.

        Direkt vom Termin abgezogen ergäbe es den 21.03.2027 — eine ganze
        Kündigungsfrist zu spät.
        """
        befund = mietzins_zustellung(termin=date(2027, 3, 31))
        self.assertNotEqual(
            befund.vorschlag, date(2027, 3, 21),
            'Die zehn Tage werden vom Termin statt vom Beginn der '
            'Kündigungsfrist gezählt — die Regel schlägt einen Tag vor, an '
            'dem die Erhöhung nichtig wäre.')

    def test_ein_tag_zu_spaet_ist_nichtig(self):
        befund = mietzins_zustellung(termin=date(2027, 3, 31),
                                     zugang=date(2026, 12, 22))
        self.assertFalse(befund.ok)
        self.assertIn('NICHTIG', befund.meldung)
        self.assertIn('269d', befund.meldung)

    def test_am_letzten_tag_ist_es_rechtzeitig(self):
        befund = mietzins_zustellung(termin=date(2027, 3, 31),
                                     zugang=date(2026, 12, 21))
        self.assertTrue(befund.ok, befund.meldung)

    def test_laengere_kuendigungsfrist_verschiebt_alles(self):
        """Geschäftsräume haben oft sechs Monate.

        Dann liegt die Zustellung ein halbes Jahr vor dem Termin — das ist
        der Fall, in dem eine Verwaltung ohne Regel sicher zu spät ist.
        """
        befund = mietzins_zustellung(termin=date(2027, 3, 31), frist_monate=6)
        # Der 20., nicht der 21.: Der 31.03. minus sechs Monate ist der
        # 30.09. — September hat dreissig Tage, und `monate_dazu` klemmt
        # richtig. Meine erste Erwartung war der 21. und damit falsch.
        self.assertEqual(befund.vorschlag, date(2026, 9, 20))

    def test_der_vorlauf_kommt_aus_der_regel(self):
        """Zehn Tage sind eine Untergrenze; länger ist zulässig."""
        befund = mietzins_zustellung(termin=date(2027, 3, 31),
                                     vorlauf_tage=30)
        self.assertEqual(befund.vorschlag, date(2026, 12, 1))

    def test_der_monatswechsel_wird_richtig_gerechnet(self):
        """Der 31. minus drei Monate ist der 30. November, nicht der 31.

        `monate_dazu` klemmt auf den letzten Tag des Zielmonats. Ohne das
        entstünde ein Datum, das es nicht gibt.
        """
        befund = mietzins_zustellung(termin=date(2027, 2, 28))
        self.assertEqual(befund.rechnung['beginn_kuendigungsfrist'],
                         '2026-11-28')

    def test_die_rechnung_zeigt_beide_stufen(self):
        """Im Streitfall muss nachvollziehbar sein, wie gerechnet wurde."""
        befund = mietzins_zustellung(termin=date(2027, 3, 31))
        self.assertEqual(befund.rechnung['beginn_kuendigungsfrist'],
                         '2026-12-31')
        self.assertEqual(befund.rechnung['spaetestens'], '2026-12-21')
        self.assertEqual(befund.rechnung['vorlauf_tage'], 10)


class AlleRegelartenGerechnetTest(TestCase):

    def test_keine_regelart_bleibt_ungerechnet(self):
        """Der Fortschrittstest aus E2.34, jetzt am Ziel.

        Er hielt fest, dass genau eine Art ungerechnet bleibt. Seit E2.36
        sind es keine mehr — und ab hier prüft er die andere Richtung: Wer
        eine fünfte Art einführt, ohne sie zu rechnen, wird rot.
        """
        import inspect

        from faelle import regelwerk
        from faelle.regelwerk_models import Regel

        quelle = inspect.getsource(regelwerk.pruefen)
        fehlend = [wert for wert, _ in Regel.ARTEN
                   if f"art == '{wert}'" not in quelle]
        self.assertEqual(
            fehlend, [],
            f'Diese Regelarten werden nicht gerechnet: {fehlend}. Eine '
            f'Regelart ohne Rechnung ist ein Auswahlwert — G7 verlangt eine '
            f'Regel.')

    def test_der_grundsatz_legt_alle_vier_an(self):
        """Am Quelltext — der billige Teil der Prüfung."""
        import inspect

        from faelle.management.commands import regelwerk_grundsatz
        from faelle.regelwerk_models import Regel

        quelle = inspect.getsource(regelwerk_grundsatz)
        for wert, bezeichnung in Regel.ARTEN:
            with self.subTest(art=wert):
                self.assertIn(
                    wert.upper(), quelle,
                    f'«{bezeichnung}» wird nicht angelegt — dann gibt es die '
                    f'Rechnung, aber keine Regel dazu.')


class GrundsatzErreichtDenBestandTest(TestCase):
    """Der Quelltext-Test oben genügt nicht — er sieht die Platzierung nicht.

    DER FEHLER, DEN ER DURCHGELASSEN HAT (E2.36)

    Die gelieferte Fassung legte die Zustellfrist-Regel mit einem eigenen
    `create()` im ANLEGEPFAD an, neben `_fehlende_nachtragen`. Der Name
    `MIETZINS_ZUSTELLUNG` stand damit im Modul, der Quelltext-Test war grün —
    und die Regel erreichte trotzdem keine Installation, die den Befehl
    schon einmal ausgeführt hatte. Nachgemessen:

        Pfad 1 (Neuanlage)         vier Regeln
        Pfad 2 (Bestand, 2. Lauf)  drei Regeln
        `--probe` meldete dazu     «vollständig»

    Das ist derselbe Fehler, den E2.34 behoben hatte, eine Etappe später
    wieder da — und die falsche Entwarnung von `--probe` macht ihn
    unsichtbar. Dieser Test führt den Befehl deshalb wirklich aus, auf einem
    Bestand, dem die Art fehlt.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _arten(self, satz):
        return set(Regel.alle_organisationen.filter(
            regelsatz=satz).values_list('art', flat=True))

    def _grundsatz(self):
        return Regelsatz.alle_organisationen.filter(
            organisation=self.a.organisation, kanton='').first()

    def test_die_neuanlage_legt_jede_art_an(self):
        Regelsatz.alle_organisationen.filter(
            organisation=self.a.organisation, kanton='').delete()
        call_command('regelwerk_grundsatz', stdout=StringIO())
        self.assertEqual(self._arten(self._grundsatz()),
                         {wert for wert, _ in Regel.ARTEN})

    def test_ein_bestand_bekommt_eine_neue_art_nachgetragen(self):
        """Der Fall, den die gelieferte Fassung nicht traf."""
        Regelsatz.alle_organisationen.filter(
            organisation=self.a.organisation, kanton='').delete()
        call_command('regelwerk_grundsatz', stdout=StringIO())
        satz = self._grundsatz()
        # Bestand von vor der Etappe: die neue Art gab es noch nicht.
        Regel.alle_organisationen.filter(
            regelsatz=satz, art=Regel.MIETZINS_ZUSTELLUNG).delete()

        call_command('regelwerk_grundsatz', stdout=StringIO())
        self.assertIn(
            Regel.MIETZINS_ZUSTELLUNG, self._arten(satz),
            'Die Regel erreicht keine bestehende Installation. Sie muss in '
            '`_regelvorlagen` stehen — nur von dort liest das Nachtragen.')

    def test_probe_meldet_nicht_vollstaendig_wenn_etwas_fehlt(self):
        """Eine falsche Entwarnung ist schlimmer als keine Meldung.

        Wer `--probe` liest und «vollständig» sieht, führt den Befehl nicht
        aus — und die Regel bleibt für immer weg.
        """
        Regelsatz.alle_organisationen.filter(
            organisation=self.a.organisation, kanton='').delete()
        call_command('regelwerk_grundsatz', stdout=StringIO())
        Regel.alle_organisationen.filter(
            regelsatz=self._grundsatz(),
            art=Regel.MIETZINS_ZUSTELLUNG).delete()

        aus = StringIO()
        call_command('regelwerk_grundsatz', '--probe', stdout=aus)
        text = aus.getvalue()
        self.assertNotIn('vollständig', text, text)
        self.assertIn('nachgetragen', text, text)

    def test_ein_angepasster_parameter_bleibt_stehen(self):
        """Nachgetragen wird nur, was fehlt — nichts wird überschrieben."""
        Regelsatz.alle_organisationen.filter(
            organisation=self.a.organisation, kanton='').delete()
        call_command('regelwerk_grundsatz', stdout=StringIO())
        regel = Regel.alle_organisationen.get(
            regelsatz=self._grundsatz(), art=Regel.MIETZINS_ZUSTELLUNG)
        regel.parameter = {'frist_monate': 6, 'vorlauf_tage': 20}
        regel.save()

        call_command('regelwerk_grundsatz', stdout=StringIO())
        regel.refresh_from_db()
        self.assertEqual(regel.parameter,
                         {'frist_monate': 6, 'vorlauf_tage': 20})


class UeberDieGanzeKetteTest(TestCase):
    """Der Weg, den die Anwendung nimmt: `pruefen()`, nicht die Rechnung.

    Die Etappe prüft `mietzins_zustellung()` direkt — gründlich, aber an
    der Verteilung in `pruefen()` vorbei. Dort werden Parameter aus der
    Regel und Eingaben aus dem Aufruf zusammengeführt; ein vertippter
    Schlüssel fällt der direkten Prüfung nicht auf, weil sie ihn nie
    berührt. Dieselbe Lücke hatte E2.34 bei der Zahlungsfrist.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _regel(self, parameter):
        # `(organisation, kanton)` ist eindeutig, und die Vorrichtung legt
        # den allgemeinen Satz bereits an — also daran haengen statt einen
        # zweiten anlegen.
        satz, _neu = Regelsatz.alle_organisationen.get_or_create(
            organisation=self.a.organisation, kanton='',
            defaults={'bezeichnung': 'Prüfsatz', 'stand': date(2026, 1, 1),
                      'geprueft': False, 'aktiv': True})
        Regel.alle_organisationen.filter(
            regelsatz=satz, art=Regel.MIETZINS_ZUSTELLUNG).delete()
        Regel.alle_organisationen.create(
            organisation=self.a.organisation, regelsatz=satz,
            art=Regel.MIETZINS_ZUSTELLUNG, verbindlichkeit=Regel.WARNUNG,
            parameter=parameter, begruendung='Art. 269d Abs. 1 OR.',
            aktiv=True)

    def test_die_regel_rechnet_ueber_pruefen(self):
        self._regel({'frist_monate': 3, 'vorlauf_tage': 10})
        with mandant(self.a.organisation):
            befund, anwendung = pruefen(
                'mietzins_zustellung', self.a.organisation,
                termin=date(2027, 3, 31))
        self.assertTrue(befund.ok)
        self.assertEqual(befund.vorschlag, date(2026, 12, 21))
        self.assertIsNotNone(anwendung,
                             'Die Anwendung wird nicht protokolliert.')

    def test_die_parameter_der_regel_kommen_an(self):
        """Sechs Monate Frist in der Regel müssen die Rechnung verschieben.

        Käme der Parameter nicht an, rechnete die Regel still mit der
        Vorgabe drei — und die Verwaltung wäre drei Monate zu spät.
        """
        self._regel({'frist_monate': 6, 'vorlauf_tage': 10})
        with mandant(self.a.organisation):
            befund, _ = pruefen('mietzins_zustellung', self.a.organisation,
                                termin=date(2027, 3, 31))
        self.assertEqual(befund.vorschlag, date(2026, 9, 20))

    def test_ein_verspaeteter_zugang_wird_beanstandet(self):
        self._regel({'frist_monate': 3, 'vorlauf_tage': 10})
        with mandant(self.a.organisation):
            befund, anwendung = pruefen(
                'mietzins_zustellung', self.a.organisation,
                termin=date(2027, 3, 31), zugang=date(2026, 12, 22))
        self.assertFalse(befund.ok)
        self.assertEqual(anwendung.befund, 'beanstandet')
