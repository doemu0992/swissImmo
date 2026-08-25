"""Tests des Regelwerks.

Der wichtigste Test ist `test_beispiel_aus_dem_konzept`: Er hält die Rechnung
fest, mit der das Konzept den Fristenwächter begründet hat. Ändert sie sich,
soll das eine bewusste Entscheidung sein und keine Nebenwirkung.

Die Regeln sind bei Auslieferung **nicht juristisch geprüft**. Diese Tests
prüfen deshalb nicht, ob die Regel richtig ist — sie prüfen, ob sie das tut,
was hinterlegt wurde, und ob eine spätere Berichtigung ihre Fälle wiederfindet.
"""
from datetime import date

from django.test import TestCase

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.models import Fall, Fallart
from faelle.regelwerk import (
    ERWARTETE_PARAMETER, Befund, kuendigungstermin, monate_dazu, pruefen,
    regel_holen, sperrt, termine_als_daten,
)
from faelle.regelwerk_models import Regel, Regelanwendung, Regelsatz

TERMINE = ['31.03', '30.06', '30.09']


class MonatsrechnungTests(TestCase):
    def test_einfacher_fall(self):
        self.assertEqual(monate_dazu(date(2026, 8, 18), 3), date(2026, 11, 18))

    def test_jahreswechsel(self):
        self.assertEqual(monate_dazu(date(2026, 11, 30), 3), date(2027, 2, 28))

    def test_monatsende_springt_nicht_in_den_naechsten_monat(self):
        """31.01. plus einen Monat ist der 28.02., nicht der 03.03."""
        self.assertEqual(monate_dazu(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_schaltjahr(self):
        self.assertEqual(monate_dazu(date(2024, 1, 31), 1), date(2024, 2, 29))

    def test_termine_werden_aufsteigend_geliefert(self):
        daten = termine_als_daten(TERMINE, date(2026, 8, 18))
        self.assertEqual(daten[:3],
                         [date(2026, 9, 30), date(2027, 3, 31), date(2027, 6, 30)])
        self.assertEqual(daten, sorted(daten))


class KuendigungsterminTests(TestCase):
    def test_beispiel_aus_dem_konzept(self):
        """Zugang 18.08.2026, gekündigt auf 30.09.2026 — beanstandet.

        Die Rechnung, mit der das Konzept den Fristenwächter begründet: Drei
        Monate ab Zugang enden am 18.11.2026, der 30.09. liegt davor. Der
        nächste vertragliche Termin danach ist der 31.03.2027.
        """
        b = kuendigungstermin(
            zugang=date(2026, 8, 18), gewuenschter_termin=date(2026, 9, 30),
            termine=TERMINE, frist_monate=3)
        self.assertFalse(b.ok)
        self.assertEqual(b.vorschlag, date(2027, 3, 31))
        self.assertEqual(b.rechnung['fristende'], '2026-11-18')
        self.assertIn('31.03.2027', b.meldung)

    def test_gueltiger_termin_wird_bestaetigt(self):
        b = kuendigungstermin(
            zugang=date(2026, 6, 20), gewuenschter_termin=date(2026, 9, 30),
            termine=TERMINE, frist_monate=3)
        self.assertTrue(b.ok)
        self.assertEqual(b.vorschlag, date(2026, 9, 30))

    def test_grenzfall_frist_endet_genau_am_termin(self):
        """Zugang 30.06. + 3 Monate = 30.09. — der Termin trägt gerade noch."""
        b = kuendigungstermin(
            zugang=date(2026, 6, 30), gewuenschter_termin=date(2026, 9, 30),
            termine=TERMINE, frist_monate=3)
        self.assertTrue(b.ok, b.meldung)

    def test_grenzfall_einen_tag_zu_spaet(self):
        b = kuendigungstermin(
            zugang=date(2026, 7, 1), gewuenschter_termin=date(2026, 9, 30),
            termine=TERMINE, frist_monate=3)
        self.assertFalse(b.ok)
        self.assertEqual(b.vorschlag, date(2027, 3, 31))

    def test_termin_ausserhalb_der_zulaessigen(self):
        b = kuendigungstermin(
            zugang=date(2026, 1, 10), gewuenschter_termin=date(2026, 5, 31),
            termine=TERMINE, frist_monate=3)
        self.assertFalse(b.ok)
        self.assertIn('kein zulässiger', b.meldung)

    def test_ohne_gewuenschten_termin_kommt_ein_vorschlag(self):
        b = kuendigungstermin(zugang=date(2026, 8, 18), gewuenschter_termin=None,
                              termine=TERMINE, frist_monate=3)
        self.assertTrue(b.ok)
        self.assertEqual(b.vorschlag, date(2027, 3, 31))

    def test_ohne_hinterlegte_termine_wird_beanstandet(self):
        """Nicht stillschweigend durchwinken — das wäre die gefährliche Antwort."""
        b = kuendigungstermin(zugang=date(2026, 8, 18),
                              gewuenschter_termin=date(2026, 9, 30),
                              termine=[], frist_monate=3)
        self.assertFalse(b.ok)
        self.assertIn('keine Kündigungstermine', b.meldung)

    def test_abweichende_frist_wird_beruecksichtigt(self):
        b = kuendigungstermin(
            zugang=date(2026, 8, 18), gewuenschter_termin=date(2026, 9, 30),
            termine=TERMINE, frist_monate=1)
        self.assertTrue(b.ok, b.meldung)

    def test_befund_ist_wahrheitswertig(self):
        self.assertTrue(bool(Befund(ok=True)))
        self.assertFalse(bool(Befund(ok=False)))


class _Basis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _regelsatz(self, org, kanton='', geprueft=False, verbindlichkeit=Regel.WARNUNG):
        """Den Regelsatz dieser Organisation herrichten.

        Bewusst **anlegen oder anpassen** statt neu anlegen: `(organisation,
        kanton)` ist eindeutig, und das Mandantenfixture bringt für jede
        Organisation bereits einen allgemeinen Regelsatz mit. Das entspricht
        auch der Wirklichkeit — eine Verwaltung hat einen allgemeinen
        Regelsatz, nicht beliebig viele.
        """
        satz, _ = Regelsatz.alle_organisationen.update_or_create(
            organisation=org, kanton=kanton,
            defaults={'bezeichnung': f'Satz {kanton or "allgemein"}',
                      'stand': date(2026, 8, 19), 'geprueft': geprueft,
                      'aktiv': True})
        Regel.alle_organisationen.update_or_create(
            regelsatz=satz, art=Regel.KUENDIGUNGSTERMIN,
            defaults={'verbindlichkeit': verbindlichkeit, 'aktiv': True,
                      'parameter': {'termine': TERMINE, 'frist_monate': 3}})
        return satz


class AnwendungTests(_Basis):
    def test_pruefung_wird_protokolliert(self):
        with mandant(self.a.organisation):
            self._regelsatz(self.a.organisation)
            befund, anwendung = pruefen(
                'kuendigungstermin', self.a.organisation,
                zugang=date(2026, 8, 18), gewuenschter_termin=date(2026, 9, 30))
            self.assertFalse(befund.ok)
            self.assertEqual(anwendung.befund, Regelanwendung.BEANSTANDET)
            self.assertEqual(anwendung.regel_stand, date(2026, 8, 19))
            self.assertFalse(anwendung.geprueft_war)

    def test_auch_ein_sauberer_befund_wird_protokolliert(self):
        """Sonst liesse sich später nicht sagen, welche Fälle geprüft wurden."""
        with mandant(self.a.organisation):
            self._regelsatz(self.a.organisation)
            _, anwendung = pruefen(
                'kuendigungstermin', self.a.organisation,
                zugang=date(2026, 6, 20), gewuenschter_termin=date(2026, 9, 30))
            self.assertEqual(anwendung.befund, Regelanwendung.OK)

    def test_berichtigung_findet_die_betroffenen_faelle(self):
        """Der eigentliche Zweck des Protokolls.

        Wird eine Regel später berichtigt, muss die Menge der unter der alten
        Fassung geprüften Vorgänge abgrenzbar sein.
        """
        with mandant(self.a.organisation):
            satz = self._regelsatz(self.a.organisation)
            # Bewusst KEIN Standardschlüssel: Das Mandantenfixture legt die
            # fünf Standard-Fallarten selbst an, und (organisation, schluessel)
            # ist eindeutig. Ein Test, der sich an einem Produktivschlüssel
            # bedient, kollidiert mit jedem Bestand, der ihn ebenfalls führt.
            art = Fallart(organisation=self.a.organisation,
                          schluessel='regelwerkpruefung', bezeichnung='Prüfung')
            art.save()
            for tag in (10, 11, 12):
                fall = Fall(fallart=art, organisation=self.a.organisation)
                fall.save()
                pruefen('kuendigungstermin', self.a.organisation, fall=fall,
                        zugang=date(2026, 8, tag),
                        gewuenschter_termin=date(2026, 9, 30))

            satz.stand = date(2026, 9, 1)
            satz.save()
            fall = Fall(fallart=art, organisation=self.a.organisation)
            fall.save()
            pruefen('kuendigungstermin', self.a.organisation, fall=fall,
                    zugang=date(2026, 8, 13), gewuenschter_termin=date(2026, 9, 30))

            alt = Regelanwendung.objects.filter(
                art='kuendigungstermin', regel_stand=date(2026, 8, 19))
            self.assertEqual(alt.count(), 3)
            self.assertEqual(
                Regelanwendung.objects.filter(regel_stand=date(2026, 9, 1)).count(), 1)

    def test_fehlende_regel_beanstandet_nicht(self):
        """Keine Regel ist etwas anderes als eine verletzte Regel.

        Die Regel des Fixtures wird hier abgeschaltet statt gelöscht — damit
        prüft der Test zugleich, dass `aktiv=False` wirklich beachtet wird.
        Eine abgeschaltete Regel, die trotzdem greift, wäre der unangenehmere
        Fehler: Sie liesse sich nicht abstellen.
        """
        with mandant(self.a.organisation):
            Regel.objects.update(aktiv=False)
            befund, anwendung = pruefen(
                'kuendigungstermin', self.a.organisation,
                zugang=date(2026, 8, 18), gewuenschter_termin=date(2026, 9, 30))
            self.assertTrue(befund.ok)
            self.assertIsNone(anwendung)

    def test_kantonsregel_geht_der_allgemeinen_vor(self):
        with mandant(self.a.organisation):
            self._regelsatz(self.a.organisation)
            satz_vd = Regelsatz(organisation=self.a.organisation, bezeichnung='VD',
                                kanton='VD', stand=date(2026, 8, 19))
            satz_vd.save()
            Regel(regelsatz=satz_vd, art=Regel.KUENDIGUNGSTERMIN,
                  parameter={'termine': ['31.12'], 'frist_monate': 3}).save()
            self.assertEqual(
                regel_holen(self.a.organisation, 'kuendigungstermin', 'VD')
                .parameter['termine'], ['31.12'])
            self.assertEqual(
                regel_holen(self.a.organisation, 'kuendigungstermin', 'ZH')
                .parameter['termine'], TERMINE)

    def test_nicht_gerechnete_regelart_wirft_klar(self):
        """Eine hinterlegte, aber noch nicht gerechnete Regelart schweigt nicht.

        Die Regelart wird an den bestehenden Regelsatz gehängt statt an einen
        neuen: `(organisation, kanton)` ist eindeutig, und die Organisation hat
        ihren allgemeinen Satz bereits.
        """
        with mandant(self.a.organisation):
            satz = self._regelsatz(self.a.organisation)
            # `MIETZINS_ZUSTELLUNG` statt `ZAHLUNGSFRIST`: Die
            # Zahlungsfrist wird seit E2.34 gerechnet. Dieser Test
            # braucht eine Art, die es NICHT wird — sonst prueft er
            # eine Meldung, die nicht mehr kommt.
            Regel(regelsatz=satz, art=Regel.MIETZINS_ZUSTELLUNG,
                  parameter={'frist_tage': 30}).save()
            with self.assertRaises(NotImplementedError):
                pruefen('mietzins_zustellung', self.a.organisation)


class SperreTests(_Basis):
    def test_ungepruefte_regel_sperrt_nie(self):
        """Entscheid 19.08.2026: bauen und nachträglich prüfen lassen."""
        with mandant(self.a.organisation):
            satz = self._regelsatz(self.a.organisation, geprueft=False,
                                   verbindlichkeit=Regel.SPERRE)
            regel = satz.regeln.first()
            befund = kuendigungstermin(date(2026, 8, 18), date(2026, 9, 30), TERMINE)
            self.assertFalse(befund.ok)
            self.assertFalse(sperrt(regel, befund))

    def test_gepruefte_sperrregel_sperrt(self):
        with mandant(self.a.organisation):
            satz = self._regelsatz(self.a.organisation, geprueft=True,
                                   verbindlichkeit=Regel.SPERRE)
            befund = kuendigungstermin(date(2026, 8, 18), date(2026, 9, 30), TERMINE)
            self.assertTrue(sperrt(satz.regeln.first(), befund))

    def test_sauberer_befund_sperrt_nie(self):
        with mandant(self.a.organisation):
            satz = self._regelsatz(self.a.organisation, geprueft=True,
                                   verbindlichkeit=Regel.SPERRE)
            befund = kuendigungstermin(date(2026, 6, 20), date(2026, 9, 30), TERMINE)
            self.assertFalse(sperrt(satz.regeln.first(), befund))


class UebersteuernTests(_Basis):
    def test_uebersteuern_braucht_eine_begruendung(self):
        with mandant(self.a.organisation):
            self._regelsatz(self.a.organisation)
            _, anwendung = pruefen(
                'kuendigungstermin', self.a.organisation,
                zugang=date(2026, 8, 18), gewuenschter_termin=date(2026, 9, 30))
            for leer in ('', '   ', None):
                with self.subTest(begruendung=leer):
                    with self.assertRaises(ValueError):
                        anwendung.uebersteuern(self.a.benutzer, leer)
            anwendung.refresh_from_db()
            self.assertFalse(anwendung.uebersteuert)

    def test_uebersteuern_wird_festgehalten(self):
        with mandant(self.a.organisation):
            self._regelsatz(self.a.organisation)
            _, anwendung = pruefen(
                'kuendigungstermin', self.a.organisation,
                zugang=date(2026, 8, 18), gewuenschter_termin=date(2026, 9, 30))
            anwendung.uebersteuern(self.a.benutzer, 'Mieter hat schriftlich zugestimmt.')
            anwendung.refresh_from_db()
            self.assertTrue(anwendung.uebersteuert)
            self.assertEqual(anwendung.uebersteuert_von, self.a.benutzer)
            self.assertIn('zugestimmt', anwendung.uebersteuert_begruendung)


class MandantentrennungTests(_Basis):
    """Beide Verwaltungen führen ein Regelwerk — geprüft wird die Trennung.

    Wie bei den Fällen prüfen diese Tests **nicht** «B sieht nichts». Das galt
    nur, solange B kein eigenes Regelwerk hatte, und wäre auch von einem
    Manager erfüllt worden, der grundsätzlich leer zurückgibt. Geprüft wird:
    B sieht die eigenen Regeln und nie die von A.

    Bei der `Regelanwendung` wiegt das am schwersten. Sie enthält die geprüften
    Eingaben eines Mandanten — Zugangsdaten von Kündigungen, genannte Termine,
    Beanstandungen. Ein Leck zeigte einer Verwaltung, welche Kündigungen eine
    andere geprüft hat.
    """

    def test_b_sieht_die_regeln_von_a_nicht(self):
        with mandant(self.a.organisation):
            satz_a = self._regelsatz(self.a.organisation)
            _, anwendung_a = pruefen(
                'kuendigungstermin', self.a.organisation,
                zugang=date(2026, 8, 18), gewuenschter_termin=date(2026, 9, 30))
        with mandant(self.b.organisation):
            self.assertEqual(Regelsatz.objects.filter(pk=satz_a.pk).count(), 0)
            self.assertEqual(
                Regel.objects.filter(regelsatz=satz_a).count(), 0)
            self.assertEqual(
                Regelanwendung.objects.filter(pk=anwendung_a.pk).count(), 0)

    def test_b_sieht_dabei_das_eigene_regelwerk(self):
        """Die Gegenprobe — sonst bestünde ein durchweg leerer Manager alles."""
        with mandant(self.b.organisation):
            self.assertGreater(Regelsatz.objects.count(), 0)
            self.assertGreater(Regel.objects.count(), 0)
            self.assertGreater(Regelanwendung.objects.count(), 0)

    def test_a_sieht_die_eigenen(self):
        with mandant(self.a.organisation):
            satz_a = self._regelsatz(self.a.organisation)
            _, anwendung = pruefen(
                'kuendigungstermin', self.a.organisation,
                zugang=date(2026, 8, 18), gewuenschter_termin=date(2026, 9, 30))
            self.assertEqual(Regelsatz.objects.filter(pk=satz_a.pk).count(), 1)
            self.assertEqual(
                Regelanwendung.objects.filter(pk=anwendung.pk).count(), 1)

    def test_fuer_a_wird_die_regel_von_a_gefunden_und_nie_die_von_b(self):
        """`regel_holen` sucht über den Regelsatz — die Bindung muss halten."""
        with mandant(self.b.organisation):
            satz_b = self._regelsatz(self.b.organisation)
        with mandant(self.a.organisation):
            gefunden = regel_holen(self.a.organisation, 'kuendigungstermin')
            self.assertIsNotNone(gefunden, 'A hat einen eigenen Regelsatz.')
            self.assertNotEqual(gefunden.regelsatz_id, satz_b.pk)
            self.assertEqual(gefunden.regelsatz.organisation_id,
                             self.a.organisation.pk)


class KatalogTests(TestCase):
    def test_jede_regelart_hat_erwartete_parameter(self):
        arten = {a for a, _ in Regel.ARTEN}
        self.assertEqual(
            arten - set(ERWARTETE_PARAMETER), set(),
            'Eine Regelart ohne Parameterbeschreibung — dann weiss niemand, '
            'was beim Anlegen hineingehört.')
