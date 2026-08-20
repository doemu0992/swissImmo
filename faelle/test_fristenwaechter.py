"""Der Fristenwächter — die Bedienung des Regelwerks.

Geprüft wird nicht die Rechnung (das leistet `test_regelwerk.py`), sondern der
**Anschluss**: dass die Kündigungserfassung die Regel anwendet, dass eine
geprüfte Sperre wirklich sperrt, dass jede Anwendung eine Spur hinterlässt und
dass niemand die Regeln einer anderen Verwaltung sieht.

Der Anlass ist der Befund vom 20.08.2026: `faelle/regelwerk.py` war seit Phase
4a vollständig gebaut und getestet — und hatte **keinen einzigen Aufrufer**.
Alle Tests waren grün. Ein grüner Modelltest sagt nichts darüber, ob die Logik
je läuft.
"""
from datetime import date

from django.test import Client, TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture


class _Basis(TestCase):
    """Zwei vollständige Bestände, A und B.

    ACHTUNG BEIM LESEN DIESER TESTS: `MandantenFixture` legt je Organisation
    **bereits einen Regelsatz** mit einer Kündigungstermin-Regel an (Stand
    19.08.2026, ungeprüft, Warnung). Wer «ohne Regelsatz» prüfen will, muss ihn
    ausdrücklich entfernen — sonst prüft der Test nicht, was sein Name sagt.
    Genau diese Verwechslung ist beim Schreiben dieser Datei zuerst passiert.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.a.benutzer)

    # -- Hilfen -------------------------------------------------------------

    def _ohne_regelsatz(self, fixture=None):
        """Entfernt den vom Fixture mitgelieferten Regelsatz."""
        from faelle.regelwerk_models import Regelsatz
        f = fixture or self.a
        Regelsatz.alle_organisationen.filter(organisation=f.organisation).delete()

    def _regelsatz(self, fixture=None, geprueft=False, sperre=False,
                   kanton='', termine=None, frist=3):
        """Ersetzt den Fixture-Regelsatz durch einen mit bekannten Werten."""
        from faelle.regelwerk_models import Regel, Regelsatz
        f = fixture or self.a
        self._ohne_regelsatz(f)
        with mandant(f.organisation):
            satz = Regelsatz.objects.create(
                bezeichnung='Grundsatz Wohnräume', kanton=kanton,
                geprueft=geprueft, stand=date(2026, 8, 1), aktiv=True)
            Regel.objects.create(
                regelsatz=satz, art=Regel.KUENDIGUNGSTERMIN,
                verbindlichkeit=Regel.SPERRE if sperre else Regel.WARNUNG,
                parameter={'frist_monate': frist,
                           'termine': (termine if termine is not None
                                       else ['31.03', '30.06', '30.09'])},
                aktiv=True)
        return satz

    def _pruefen(self, vertrag, *args, **kwargs):
        """Prüft im Mandantenkontext — so, wie es in einer Anfrage geschieht.

        `regel_holen` liest über `Regel.objects`, den mandantengefilterten
        Manager. In einer Anfrage setzt die Middleware den Kontext; ausserhalb
        wirft er. Den Filter für den Test zu lockern hiesse, die Isolation zum
        Testen zu schwächen — stattdessen bildet der Test die Anfrage nach.
        """
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        with mandant(vertrag.organisation):
            return pruefung_zum_vertrag(vertrag, *args, **kwargs)


    def _vertrag_mit(self, termine='31. März, 30. Juni, 30. September', frist=3):
        v = self.a.vertrag
        v.kuendigungstermine = termine
        v.kuendigungsfrist_monate = frist
        v.save()
        return v


class BrueckeZumVertragTests(_Basis):
    """`termine_aus_vertrag` — die einzige Übersetzung Freitext → Termine."""

    def test_freitext_wird_zu_terminen(self):
        from rentals.services import termine_aus_vertrag
        self.a.vertrag.kuendigungstermine = 'Ende jedes Monats ausser Dezember'
        termine = termine_aus_vertrag(self.a.vertrag)
        self.assertEqual(len(termine), 11)
        self.assertIn('31.01', termine)
        self.assertNotIn('31.12', termine)

    def test_genannte_monate_werden_uebernommen(self):
        from rentals.services import termine_aus_vertrag
        self.a.vertrag.kuendigungstermine = '31. März, 30. Juni, 30. September'
        self.assertEqual(termine_aus_vertrag(self.a.vertrag),
                         ['31.03', '31.06', '31.09'])

    def test_der_tag_31_wird_auf_die_monatslaenge_geklemmt(self):
        """'31.02' darf nicht als 31. Februar gelesen werden.

        Ein hier fest verdrahteter 28. wäre in Schaltjahren falsch — deshalb
        steht überall 31 und `termine_als_daten` klemmt.
        """
        from faelle.regelwerk import termine_als_daten
        daten = termine_als_daten(['31.02'], date(2028, 1, 1), jahre=0)
        self.assertEqual(daten[0], date(2028, 2, 29))   # Schaltjahr
        daten = termine_als_daten(['31.02'], date(2027, 1, 1), jahre=0)
        self.assertEqual(daten[0], date(2027, 2, 28))


class PruefungAmVertragTests(_Basis):

    def test_ohne_regelsatz_ist_der_befund_in_ordnung_mit_hinweis(self):
        """Eine fehlende Regel darf nicht wie eine verletzte aussehen."""
        self._ohne_regelsatz()
        befund, anwendung, regel = self._pruefen(
            self.a.vertrag, date(2026, 8, 18), date(2026, 11, 30))
        self.assertTrue(befund.ok)
        self.assertIsNone(regel)
        self.assertIsNone(anwendung)
        self.assertIn('keine Regel', befund.meldung)

    def test_zu_frueher_termin_wird_beanstandet(self):
        """Das Rechenbeispiel des Prototyps.

        Zugang 18.08.2026 + drei Monate = 18.11.2026. Nächster Vertragstermin
        aus 31.03/30.06/30.09 ist der 31.03.2027.
        """
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        self._regelsatz()
        self.a.vertrag.kuendigungstermine = '31. März, 30. Juni, 30. September'
        self.a.vertrag.kuendigungsfrist_monate = 3
        self.a.vertrag.save()
        befund, _a, _r = self._pruefen(
            self.a.vertrag, date(2026, 8, 18), date(2026, 9, 30),
            protokollieren=False)
        self.assertFalse(befund.ok)
        self.assertEqual(befund.vorschlag, date(2027, 3, 31))

    def test_der_vertrag_hat_vorrang_vor_dem_vorgabewert_der_regel(self):
        """Eine vereinbarte längere Frist gilt, auch wenn die Regel drei sagt."""
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        self._regelsatz(frist=3)
        self.a.vertrag.kuendigungsfrist_monate = 6
        self.a.vertrag.kuendigungstermine = 'Ende jedes Monats'
        self.a.vertrag.save()
        befund, _a, _r = self._pruefen(
            self.a.vertrag, date(2026, 8, 18), None, protokollieren=False)
        self.assertEqual(befund.rechnung['frist_monate'], 6)

    def test_jede_anwendung_wird_protokolliert_auch_die_gute(self):
        """Sonst ist «welche Fälle wurden unter der alten Fassung geprüft»
        nicht beantwortbar."""
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        from faelle.regelwerk_models import Regelanwendung
        self._regelsatz()
        vorher = Regelanwendung.alle_organisationen.count()
        befund, anwendung, _r = self._pruefen(
            self.a.vertrag, date(2026, 8, 18), None)
        self.assertTrue(befund.ok)
        self.assertIsNotNone(anwendung)
        self.assertEqual(Regelanwendung.alle_organisationen.count(), vorher + 1)
        self.assertEqual(anwendung.regel_stand, date(2026, 8, 1))
        self.assertFalse(anwendung.geprueft_war)

    def test_die_vorschau_protokolliert_nicht(self):
        """Wer tippt und verwirft, hat keine Regel angewendet."""
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        from faelle.regelwerk_models import Regelanwendung
        self._regelsatz()
        vorher = Regelanwendung.alle_organisationen.count()
        self._pruefen(self.a.vertrag, date(2026, 8, 18), None,
                             protokollieren=False)
        self.assertEqual(Regelanwendung.alle_organisationen.count(), vorher)


class FolgekostenTests(_Basis):

    def test_die_zahl_steht_nur_bei_einer_beanstandung(self):
        from core.views.fw.regelwerk import folgekosten, pruefung_zum_vertrag
        self._regelsatz()
        self.a.vertrag.kuendigungstermine = 'Ende jedes Monats'
        self.a.vertrag.save()
        befund, _a, _r = self._pruefen(
            self.a.vertrag, date(2026, 8, 18), None, protokollieren=False)
        self.assertTrue(befund.ok)
        self.assertIsNone(folgekosten(befund, self.a.vertrag))

    def test_monate_und_betrag_werden_gerechnet(self):
        from core.views.fw.regelwerk import folgekosten, pruefung_zum_vertrag
        self._regelsatz()
        self.a.vertrag.kuendigungstermine = '31. März, 30. Juni, 30. September'
        self.a.vertrag.kuendigungsfrist_monate = 3
        self.a.vertrag.save()
        befund, _a, _r = self._pruefen(
            self.a.vertrag, date(2026, 8, 18), date(2026, 9, 30),
            protokollieren=False)
        kosten = folgekosten(befund, self.a.vertrag)
        self.assertIsNotNone(kosten)
        self.assertEqual(kosten['monate'], 6)          # 30.09.26 → 31.03.27
        self.assertEqual(kosten['betrag'],
                         self.a.vertrag.brutto_mietzins * 6)


class SperreTests(_Basis):
    """Der einzige Fall, in dem das Regelwerk den Betrieb anhält."""

    def test_ungepruefte_regel_sperrt_nie(self):
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        from faelle.regelwerk import sperrt
        self._regelsatz(geprueft=False, sperre=True)
        self.a.vertrag.kuendigungstermine = '31. März'
        self.a.vertrag.save()
        befund, _a, regel = self._pruefen(
            self.a.vertrag, date(2026, 8, 18), date(2026, 9, 30),
            protokollieren=False)
        self.assertFalse(befund.ok)
        self.assertFalse(sperrt(regel, befund),
                         'Eine ungeprüfte Regel darf warnen, nicht sperren.')

    def test_gepruefte_regel_mit_verbindlichkeit_sperre_sperrt(self):
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        from faelle.regelwerk import sperrt
        self._regelsatz(geprueft=True, sperre=True)
        self.a.vertrag.kuendigungstermine = '31. März'
        self.a.vertrag.save()
        befund, _a, regel = self._pruefen(
            self.a.vertrag, date(2026, 8, 18), date(2026, 9, 30),
            protokollieren=False)
        self.assertTrue(sperrt(regel, befund))

    def test_gepruefte_regel_mit_verbindlichkeit_warnung_sperrt_nicht(self):
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        from faelle.regelwerk import sperrt
        self._regelsatz(geprueft=True, sperre=False)
        self.a.vertrag.kuendigungstermine = '31. März'
        self.a.vertrag.save()
        befund, _a, regel = self._pruefen(
            self.a.vertrag, date(2026, 8, 18), date(2026, 9, 30),
            protokollieren=False)
        self.assertFalse(sperrt(regel, befund))


class KuendigungserfassungTests(_Basis):
    """Der Anschluss selbst — die Stelle, die vier Etappen lang fehlte."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.a.benutzer)
        self.a.vertrag.kuendigungstermine = '31. März, 30. Juni, 30. September'
        self.a.vertrag.kuendigungsfrist_monate = 3
        self.a.vertrag.status = 'aktiv'
        self.a.vertrag.aktiv = True
        self.a.vertrag.save()

    def _erfassen(self, ende, ausserordentlich=False):
        daten = {'absender': 'mieter', 'eingang_datum': '2026-08-18',
                 'zustellung': 'einschreiben', 'gewuenschtes_ende': ende}
        if ausserordentlich:
            daten['ausserordentlich'] = 'on'
        return self.client.post(
            f'/neu/vertraege/{self.a.vertrag.id}/kuendigen/', daten)

    def test_erfassung_wendet_die_regel_an_und_protokolliert(self):
        from faelle.regelwerk_models import Regelanwendung
        self._regelsatz()
        vorher = Regelanwendung.alle_organisationen.count()
        self._erfassen('2027-03-31')
        self.assertEqual(Regelanwendung.alle_organisationen.count(), vorher + 1,
                         'Die Erfassung hat die Regel nicht angewendet.')

    def test_gepruefte_sperre_verhindert_das_speichern(self):
        from rentals.models import Kuendigung
        self._regelsatz(geprueft=True, sperre=True)
        vorher = Kuendigung.alle_organisationen.count()
        antwort = self._erfassen('2026-09-30')
        self.assertEqual(Kuendigung.alle_organisationen.count(), vorher,
                         'Trotz geprüfter Sperre wurde eine Kündigung angelegt.')
        self.assertEqual(antwort.status_code, 302)
        self.a.vertrag.refresh_from_db()
        self.assertEqual(self.a.vertrag.status, 'aktiv',
                         'Der Vertrag wurde trotz Sperre auf gekündigt gesetzt.')

    def test_warnung_verhindert_das_speichern_nicht(self):
        from rentals.models import Kuendigung
        self._regelsatz(geprueft=False, sperre=True)   # ungeprüft → warnt nur
        vorher = Kuendigung.alle_organisationen.count()
        self._erfassen('2026-09-30')
        self.assertEqual(Kuendigung.alle_organisationen.count(), vorher + 1,
                         'Eine ungeprüfte Regel hat das Speichern verhindert.')

    def test_ausserordentliche_kuendigung_laeuft_nicht_durch_die_regel(self):
        """Art. 257d, 266g und 271a haben eigene Fristen.

        Eine Regel auf einen Fall anzuwenden, für den sie nicht gemacht ist,
        wäre schlechter als keine Regel.
        """
        from faelle.regelwerk_models import Regelanwendung
        self._regelsatz(geprueft=True, sperre=True)
        vorher = Regelanwendung.alle_organisationen.count()
        antwort = self._erfassen('2026-09-30', ausserordentlich=True)
        self.assertEqual(Regelanwendung.alle_organisationen.count(), vorher,
                         'Die ausserordentliche Kündigung wurde geprüft.')
        self.assertEqual(antwort.status_code, 302)

    def test_die_vorschau_liefert_die_rechnung(self):
        self._regelsatz()
        antwort = self.client.get(
            f'/neu/vertraege/{self.a.vertrag.id}/kuendigen/pruefen/'
            f'?zugang=2026-08-18&termin=2026-09-30')
        self.assertEqual(antwort.status_code, 200)
        html = antwort.content.decode()
        self.assertIn('Rechnung anzeigen', html)
        self.assertIn('31.03', html)      # zulässige Termine stehen drin

    def test_das_formular_bindet_den_fristenwaechter_ein(self):
        """Ohne diesen Behälter läuft die Prüfung, aber niemand sieht sie."""
        antwort = self.client.get(
            f'/neu/vertraege/{self.a.vertrag.id}/kuendigen/')
        self.assertContains(antwort, 'id="regel-befund"')


class SeitenTests(_Basis):

    def test_uebersicht_nennt_den_ungeprueften_stand(self):
        antwort = self.client.get('/neu/regelwerk/')
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'nicht juristisch geprüft')

    def test_regelsatz_anlegen_und_regel_fuehren(self):
        from faelle.regelwerk_models import Regel, Regelsatz
        self._ohne_regelsatz()
        antwort = self.client.post('/neu/regelwerk/neu/', {
            'bezeichnung': 'Grundsatz ZH', 'kanton': 'zh', 'aktiv': 'on',
            'aktiv_kuendigungstermin': 'on',
            'kuendigungstermin__frist_monate': '3',
            'kuendigungstermin__termine': '31.03, 30.06, 30.09',
            'begruendung_kuendigungstermin': 'Art. 266c OR',
        })
        self.assertEqual(antwort.status_code, 302)
        satz = Regelsatz.alle_organisationen.get(bezeichnung='Grundsatz ZH')
        self.assertEqual(satz.kanton, 'ZH')
        self.assertFalse(satz.geprueft)
        self.assertEqual(satz.stand, timezone.localdate())
        regel = satz.regeln.all().get(art=Regel.KUENDIGUNGSTERMIN)
        self.assertEqual(regel.parameter['frist_monate'], 3)
        self.assertEqual(regel.parameter['termine'], ['31.03', '30.06', '30.09'])

    def test_leeres_parameterfeld_wird_weggelassen_nicht_als_null_abgelegt(self):
        """Fehlender Parameter heisst «es gilt der Vertrag», Null hiesse
        «keine Frist». Die beiden zu verwechseln liesse eine Kündigung ohne
        Frist durch."""
        from faelle.regelwerk_models import Regelsatz
        self._ohne_regelsatz()
        self.client.post('/neu/regelwerk/neu/', {
            'bezeichnung': 'Ohne Frist', 'aktiv': 'on',
            'aktiv_kuendigungstermin': 'on',
            'kuendigungstermin__frist_monate': '',
            'kuendigungstermin__termine': '',
        })
        regel = Regelsatz.alle_organisationen.get(bezeichnung='Ohne Frist').regeln.first()
        self.assertNotIn('frist_monate', regel.parameter)
        self.assertNotIn('termine', regel.parameter)

    def test_unsinnige_termine_werden_verworfen(self):
        from faelle.regelwerk_models import Regelsatz
        self._ohne_regelsatz()
        self.client.post('/neu/regelwerk/neu/', {
            'bezeichnung': 'Mit Unsinn', 'aktiv': 'on',
            'aktiv_kuendigungstermin': 'on',
            'kuendigungstermin__termine': '31.03, Ende März, 45.99, 30.06',
        })
        regel = Regelsatz.alle_organisationen.get(bezeichnung='Mit Unsinn').regeln.first()
        self.assertEqual(regel.parameter['termine'], ['31.03', '30.06'])

    def test_stand_wandert_bei_jeder_aenderung(self):
        satz = self._regelsatz()
        self.assertEqual(satz.stand, date(2026, 8, 1))
        self.client.post(f'/neu/regelwerk/{satz.id}/', {
            'bezeichnung': satz.bezeichnung, 'aktiv': 'on'})
        satz.refresh_from_db()
        self.assertEqual(satz.stand, timezone.localdate())

    def test_protokoll_laesst_sich_nach_stand_filtern(self):
        """Der eigentliche Zweck der Seite: nach einer Berichtigung die
        betroffenen Fälle finden."""
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        self._regelsatz()
        self._pruefen(self.a.vertrag, date(2026, 8, 18), None)
        antwort = self.client.get('/neu/regelwerk/protokoll/?stand=2026-08-01')
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.context['gesamt'], 1)
        leer = self.client.get('/neu/regelwerk/protokoll/?stand=2020-01-01')
        self.assertEqual(leer.context['gesamt'], 0)

    def test_uebersteuern_ohne_begruendung_wird_abgewiesen(self):
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        self._regelsatz()
        self.a.vertrag.kuendigungstermine = '31. März'
        self.a.vertrag.save()
        _b, anwendung, _r = self._pruefen(
            self.a.vertrag, date(2026, 8, 18), date(2026, 9, 30))
        self.client.post(
            f'/neu/regelwerk/anwendung/{anwendung.id}/uebersteuern/',
            {'begruendung': '   '})
        anwendung.refresh_from_db()
        self.assertFalse(anwendung.uebersteuert)

    def test_uebersteuern_mit_begruendung_wird_festgehalten(self):
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        self._regelsatz()
        self.a.vertrag.kuendigungstermine = '31. März'
        self.a.vertrag.save()
        _b, anwendung, _r = self._pruefen(
            self.a.vertrag, date(2026, 8, 18), date(2026, 9, 30))
        self.client.post(
            f'/neu/regelwerk/anwendung/{anwendung.id}/uebersteuern/',
            {'begruendung': 'Aufhebungsvertrag im gegenseitigen Einvernehmen.'})
        anwendung.refresh_from_db()
        self.assertTrue(anwendung.uebersteuert)
        self.assertEqual(anwendung.uebersteuert_von, self.a.benutzer)
        self.assertIn('Einvernehmen', anwendung.uebersteuert_begruendung)


class MandantentrennungTests(_Basis):
    """Aktive Versuche über die Mandantengrenze. Jeder muss scheitern."""

    def test_fremder_regelsatz_gibt_404_nicht_403(self):
        """403 bestätigt die Existenz und erlaubt, über fortlaufende IDs den
        Bestand des Wettbewerbers abzuzählen."""
        fremd = self._regelsatz(fixture=self.b)
        antwort = self.client.get(f'/neu/regelwerk/{fremd.id}/')
        self.assertEqual(antwort.status_code, 404)

    def test_fremder_regelsatz_laesst_sich_nicht_loeschen(self):
        from faelle.regelwerk_models import Regelsatz
        fremd = self._regelsatz(fixture=self.b)
        antwort = self.client.post(f'/neu/regelwerk/{fremd.id}/loeschen/')
        self.assertEqual(antwort.status_code, 404)
        self.assertTrue(
            Regelsatz.alle_organisationen.filter(pk=fremd.pk).exists())

    def test_die_uebersicht_zeigt_nur_eigene_regelsaetze(self):
        eigen = self._regelsatz()
        fremd = self._regelsatz(fixture=self.b)
        fremd.bezeichnung = 'Nur fuer die andere Verwaltung'
        fremd.save()
        antwort = self.client.get('/neu/regelwerk/')
        gezeigt = [s['satz'].pk for s in antwort.context['saetze']]
        self.assertIn(eigen.pk, gezeigt)
        self.assertNotIn(fremd.pk, gezeigt)
        self.assertNotContains(antwort, 'Nur fuer die andere Verwaltung')

    def test_fremde_regelanwendung_laesst_sich_nicht_uebersteuern(self):
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        with mandant(self.b.organisation):
            self._regelsatz(fixture=self.b)
            _b, fremde_anwendung, _r = pruefung_zum_vertrag(
                self.b.vertrag, date(2026, 8, 18), date(2026, 9, 30))
        antwort = self.client.post(
            f'/neu/regelwerk/anwendung/{fremde_anwendung.id}/uebersteuern/',
            {'begruendung': 'Versuch über die Grenze.'})
        self.assertEqual(antwort.status_code, 404)
        fremde_anwendung.refresh_from_db()
        self.assertFalse(fremde_anwendung.uebersteuert)

    def test_vorschau_zu_fremdem_vertrag_gibt_404(self):
        antwort = self.client.get(
            f'/neu/vertraege/{self.b.vertrag.id}/kuendigen/pruefen/'
            f'?zugang=2026-08-18')
        self.assertEqual(antwort.status_code, 404)

    def test_das_protokoll_zeigt_nur_eigene_anwendungen(self):
        from core.views.fw.regelwerk import pruefung_zum_vertrag
        with mandant(self.b.organisation):
            self._regelsatz(fixture=self.b)
            _b, fremde, _r = pruefung_zum_vertrag(
                self.b.vertrag, date(2026, 8, 18), None)
        antwort = self.client.get('/neu/regelwerk/protokoll/')
        # NICHT gegen eine Gesamtzahl pruefen: Das Fixture legt je Organisation
        # bereits eine eigene Regelanwendung an, A hat also von sich aus eine.
        # Eine Zaehlung auf 0 wuerde entweder immer scheitern oder — schlimmer —
        # zufaellig aufgehen und nichts aussagen. Geprueft wird das konkrete
        # fremde Objekt.
        gezeigt = [z.pk for z in antwort.context['zeilen']]
        self.assertNotIn(fremde.pk, gezeigt,
                         'Das Protokoll zeigt eine Anwendung einer fremden Verwaltung.')
        self.assertIn(self.a.regelanwendung.pk, gezeigt,
                      'Die eigene Anwendung fehlt — dann prueft der Test die '
                      'Isolation nicht, sondern eine leere Liste.')

    def test_die_regel_einer_fremden_organisation_greift_nicht(self):
        """`regel_holen` darf nie einen fremden Regelsatz zurückgeben —
        sonst gälten die Fristen der anderen Verwaltung."""
        from faelle.regelwerk import regel_holen
        self._regelsatz(fixture=self.b)
        self._ohne_regelsatz(self.a)
        with mandant(self.a.organisation):
            self.assertIsNone(regel_holen(self.a.organisation, 'kuendigungstermin'))


class GrundsatzBefehlTests(_Basis):
    """`manage.py regelwerk_grundsatz` — der Weg zum ersten Regelsatz."""

    def _laufen(self, **optionen):
        from io import StringIO

        from django.core.management import call_command
        aus = StringIO()
        call_command('regelwerk_grundsatz', stdout=aus, **optionen)
        return aus.getvalue()

    def test_legt_je_organisation_einen_ungepruesten_satz_an(self):
        from faelle.regelwerk_models import Regelsatz
        self._ohne_regelsatz(self.a)
        self._ohne_regelsatz(self.b)
        self._laufen()
        for f in (self.a, self.b):
            satz = Regelsatz.alle_organisationen.get(
                organisation=f.organisation, kanton='')
            self.assertFalse(satz.geprueft,
                             'Ein von selbst angelegter Regelsatz darf nie als '
                             'geprüft gelten.')

    def test_ohne_termine_gilt_der_vertrag(self):
        """Die wichtigste Entscheidung des Befehls.

        Ortsübliche Termine sind kantonal verschieden. Ein hier eingetragenes
        31.03/30.06/30.09 wäre für einen Teil der Schweiz falsch — und sähe
        aus wie eine geprüfte Angabe.
        """
        from faelle.regelwerk_models import Regelsatz
        self._ohne_regelsatz(self.a)
        self._ohne_regelsatz(self.b)
        self._laufen(organisation=self.a.organisation.pk)
        regel = Regelsatz.alle_organisationen.get(
            organisation=self.a.organisation).regeln.all().first()
        self.assertEqual(regel.parameter, {'frist_monate': 3})
        self.assertNotIn('termine', regel.parameter)

    def test_der_befund_stuetzt_sich_dann_auf_den_vertrag(self):
        """Ohne Termine in der Regel: Die Prüfung nimmt die des Vertrags."""
        self._ohne_regelsatz(self.a)
        self._ohne_regelsatz(self.b)
        self._laufen(organisation=self.a.organisation.pk)
        self._vertrag_mit('31. März, 30. Juni, 30. September')
        befund, _a, _r = self._pruefen(
            self.a.vertrag, date(2026, 8, 18), date(2026, 9, 30),
            protokollieren=False)
        self.assertFalse(befund.ok)
        self.assertEqual(befund.rechnung['zulaessige_termine'],
                         ['31.03', '31.06', '31.09'])

    def test_wiederholter_lauf_aendert_nichts(self):
        from faelle.regelwerk_models import Regelsatz
        self._ohne_regelsatz(self.a)
        self._ohne_regelsatz(self.b)
        self._laufen()
        vorher = Regelsatz.alle_organisationen.count()
        ausgabe = self._laufen()
        self.assertEqual(Regelsatz.alle_organisationen.count(), vorher)
        self.assertIn('unverändert', ausgabe)

    def test_probe_schreibt_nichts(self):
        from faelle.regelwerk_models import Regelsatz
        self._ohne_regelsatz(self.a)
        self._ohne_regelsatz(self.b)
        vorher = Regelsatz.alle_organisationen.count()
        ausgabe = self._laufen(probe=True)
        self.assertEqual(Regelsatz.alle_organisationen.count(), vorher)
        self.assertIn('würde angelegt', ausgabe)
