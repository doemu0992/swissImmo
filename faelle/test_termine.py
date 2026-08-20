"""Termine und Abwesenheiten — die beiden zuletzt gebauten Bausteine.

WARUM SIE ÜBERHAUPT ENTSTANDEN SIND

Der Prototyp (`mockups/konzept-struktur.html`, Screen «Heute») führt fünf
Abschnitte. Drei liessen sich aus dem Bestand rechnen; für «Termine» fehlte
das Eigentümergespräch und für «Vertretung» fehlte alles — `crm.Mitgliedschaft`
führt Benutzer, Organisation und Rolle, kein Abwesenheitsfeld.

Bis 4b.7 stand deshalb in beiden Abschnitten eine ehrliche Lücke. Diese Tests
halten fest, dass die Lücke geschlossen ist **und** dass beim Schliessen nichts
Falsches dazukam: keine doppelten Termine, keine erfundene Vertretung, keine
Abwesenheit über die Mandantengrenze.

WAS HIER BESONDERS SCHARF SEIN MUSS

Zwei neue Modelle heisst zwei neue Wege, versehentlich fremde Daten zu zeigen.
Der Skill `mandantentrennung` verlangt für jede Änderung mindestens einen Test,
der den Zugriff über die Grenze **aktiv versucht** und fehlschlagen muss — mit
404, nicht 403: Ein 403 bestätigt, dass die ID existiert.
"""
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.arbeitsvorrat import termine, vertretung
from faelle.termin_models import Abwesenheit, Termin


class TerminModellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_organisation_kommt_aus_dem_kontext(self):
        """Ein Termin ohne Organisation wäre ein Termin, den jeder sieht."""
        with mandant(self.a.organisation):
            t = Termin(titel='Begehung', beginn=timezone.now() + timedelta(days=1))
            t.save()
            self.assertEqual(t.organisation_id, self.a.organisation.id)

    def test_die_akte_schlaegt_den_kontext(self):
        """Dieselbe Reihenfolge wie bei `Fall`: Die Akte weiss es genauer."""
        with mandant(self.a.organisation):
            t = Termin(titel='Abnahme', art=Termin.ABNAHME,
                       beginn=timezone.now() + timedelta(days=1),
                       akte=self.a.vertrag)
            t.save()
            self.assertEqual(t.organisation_id, self.a.vertrag.organisation_id)

    def test_fremder_aktentyp_wird_abgelehnt(self):
        from django.contrib.contenttypes.models import ContentType
        from django.core.exceptions import ValidationError

        from core.models import Pendenz
        with mandant(self.a.organisation):
            t = Termin(titel='Unsinn', beginn=timezone.now(),
                       akte_typ=ContentType.objects.get_for_model(Pendenz),
                       akte_id=1)
            with self.assertRaises(ValidationError):
                t.clean()

    def test_ende_folgt_aus_dauer(self):
        with mandant(self.a.organisation):
            beginn = timezone.now() + timedelta(days=1)
            t = Termin(titel='X', beginn=beginn, dauer_minuten=90)
            self.assertEqual(t.ende, beginn + timedelta(minutes=90))

    def test_abgesagter_termin_ist_nicht_offen(self):
        with mandant(self.a.organisation):
            t = Termin(titel='Fällt aus', beginn=timezone.now() + timedelta(days=1),
                       status=Termin.ABGESAGT)
            t.save()
            self.assertNotIn(t.pk, [x.pk for x in Termin.objects.offen()])


class AbwesenheitModellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_laufend_schliesst_den_letzten_tag_ein(self):
        """«bis 25.08.» heisst: am 25. ist die Person noch weg.

        Ein exklusives Ende ist die häufigste stille Fehlerquelle bei
        Zeiträumen — deshalb ein eigener Test dafür und nicht nur ein
        Kommentar.
        """
        heute = timezone.localdate()
        with mandant(self.a.organisation):
            a = Abwesenheit(benutzer=self.a.benutzer, von=heute - timedelta(days=2),
                            bis=heute)
            a.save()
            self.assertIn(a.pk, [x.pk for x in Abwesenheit.objects.laufend(heute)])
            self.assertNotIn(a.pk, [x.pk for x in Abwesenheit.objects.laufend(
                heute + timedelta(days=1))])

    def test_ende_vor_beginn_wird_abgelehnt(self):
        from django.core.exceptions import ValidationError
        heute = timezone.localdate()
        with mandant(self.a.organisation):
            a = Abwesenheit(benutzer=self.a.benutzer, von=heute,
                            bis=heute - timedelta(days=1))
            with self.assertRaises(ValidationError):
                a.clean()

    def test_niemand_vertritt_sich_selbst(self):
        from django.core.exceptions import ValidationError
        heute = timezone.localdate()
        with mandant(self.a.organisation):
            a = Abwesenheit(benutzer=self.a.benutzer, von=heute, bis=heute,
                            vertreten_durch=self.a.benutzer)
            with self.assertRaises(ValidationError):
                a.clean()


class VertretungsabschnittTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_ohne_abwesenheit_kein_abschnitt(self):
        """Gegenprobe: kein Dauerlärm, wenn niemand weg ist.

        Das Fixture legt selbst eine laufende Abwesenheit an — sie wird
        deshalb erst beendet. Eine Zählung ohne diesen Schritt wäre falsch;
        genau diese Falle hat in vier Anläufen schon dreimal zugeschlagen.
        """
        with mandant(self.a.organisation):
            Abwesenheit.objects.all().update(
                bis=timezone.localdate() - timedelta(days=1))
            self.assertEqual(vertretung(), [])

    def test_abwesenheit_ohne_vertretung_wird_als_ungedeckt_gemeldet(self):
        """Kein Fehler, aber eine Aussage — und eine, die auffallen soll."""
        heute = timezone.localdate()
        with mandant(self.a.organisation):
            Abwesenheit.objects.all().delete()
            Abwesenheit(benutzer=self.a.benutzer, von=heute,
                        bis=heute + timedelta(days=3)).save()
            zeilen = vertretung(heute)
            self.assertEqual(len(zeilen), 1)
            self.assertTrue(zeilen[0]['ungedeckt'])
            self.assertIsNone(zeilen[0]['vertreter'])

    def test_mit_vertretung_steht_der_name_da(self):
        from benutzer.models import Benutzer
        heute = timezone.localdate()
        with mandant(self.a.organisation):
            Abwesenheit.objects.all().delete()
            zweiter = Benutzer.objects.create_user(
                username='vertreter-a', password='x', first_name='Silvia',
                last_name='Roux')
            Abwesenheit(benutzer=self.a.benutzer, von=heute, bis=heute,
                        vertreten_durch=zweiter).save()
            zeile = vertretung(heute)[0]
            self.assertFalse(zeile['ungedeckt'])
            self.assertIn('Silvia', zeile['vertreter'])


class TermineImVorratTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_erfasster_termin_erscheint(self):
        with mandant(self.a.organisation):
            Termin(titel='Eigentümergespräch Blattner', art=Termin.GESPRAECH,
                   beginn=timezone.now() + timedelta(days=2),
                   ort='Büro').save()
            titel = [t['titel'] for t in termine()]
            self.assertIn('Eigentümergespräch Blattner', titel)

    def test_termin_jenseits_des_fensters_erscheint_nicht(self):
        with mandant(self.a.organisation):
            Termin(titel='Weit weg', beginn=timezone.now() + timedelta(days=20)).save()
            self.assertNotIn('Weit weg', [t['titel'] for t in termine()])

    def test_abgesagter_termin_erscheint_nicht(self):
        with mandant(self.a.organisation):
            Termin(titel='Fällt aus', beginn=timezone.now() + timedelta(days=1),
                   status=Termin.ABGESAGT).save()
            self.assertNotIn('Fällt aus', [t['titel'] for t in termine()])

    def test_abgeleitete_termine_werden_nicht_dupliziert(self):
        """Eine Abnahme kommt aus dem Vertrag, nicht aus `Termin`.

        Würde das Erfassen einer Abnahme zusätzlich einen `Termin` anlegen,
        stünde dieselbe Wohnungsabnahme zweimal im Tag — derselbe Fehler wie
        bei der Inbox-Doppelung in 4b.5, nur eine Ebene tiefer.
        """
        from rentals.models import Abnahmeprotokoll
        with mandant(self.a.organisation):
            # Erst aufräumen: Das Fixture bringt selbst Abnahmen mit, und eine
            # Zählung über alle wäre prompt falsch. Genau diese Falle hat in
            # dieser Sitzung schon dreimal zugeschlagen — deshalb hier gegen
            # den EIGENEN Datensatz geprüft, nicht gegen eine Gesamtzahl.
            Abnahmeprotokoll.objects.all().delete()
            Abnahmeprotokoll(vertrag=self.a.vertrag, typ='auszug',
                             datum=timezone.localdate() + timedelta(days=2)).save()
            abnahmen = [t for t in termine() if t['art'] == 'abnahme']
            self.assertEqual(len(abnahmen), 1,
                             'Die Abnahme steht mehrfach im Tag.')
            self.assertEqual(Termin.objects.filter(art=Termin.ABNAHME).count(), 0,
                             'Das Erfassen einer Abnahme hat zusätzlich einen '
                             'Termin angelegt — das ist die Doppelung.')

    def test_sortierung_nach_zeitpunkt(self):
        """Abgeleitete Termine tragen teils keine Uhrzeit (eine Abnahme hat
        nur ein Datum). Der Vergleich muss deshalb dieselbe Ersatzzeit
        einsetzen wie die Sortierung selbst — sonst scheitert er an `None`
        statt an der Reihenfolge."""
        from datetime import time
        with mandant(self.a.organisation):
            Termin(titel='Spät', beginn=timezone.now() + timedelta(days=3)).save()
            Termin(titel='Früh', beginn=timezone.now() + timedelta(hours=2)).save()
            zeilen = [(t['datum'], t['zeit'] or time.min) for t in termine()]
            self.assertEqual(zeilen, sorted(zeilen))


class SeitenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _hole(self, adresse):
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            return c.get(adresse)

    def test_terminseite_zeigt_den_termin(self):
        with mandant(self.a.organisation):
            Termin(titel='Begehung Dachstock',
                   beginn=timezone.now() + timedelta(days=1)).save()
        antwort = self._hole('/neu/termine/')
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'Begehung Dachstock')

    def test_termin_laesst_sich_erfassen(self):
        c = Client()
        c.force_login(self.a.benutzer)
        beginn = (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        with mandant(self.a.organisation):
            antwort = c.post('/neu/termine/neu/', {
                'titel': 'Neuer Termin', 'beginn': beginn, 'art': 'begehung'})
            self.assertEqual(antwort.status_code, 302)
            self.assertTrue(Termin.objects.filter(titel='Neuer Termin').exists())

    def test_termin_ohne_titel_meldet_sich(self):
        """Kein stiller Abbruch — wer nichts passieren sieht, schickt nochmal."""
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            antwort = c.post('/neu/termine/neu/', {'titel': '', 'beginn': ''},
                             follow=True)
            self.assertContains(antwort, 'Titel und Beginn sind nötig')

    def test_termin_absagen(self):
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            t = Termin(titel='Weg damit', beginn=timezone.now() + timedelta(days=1))
            t.save()
            c.post(f'/neu/termine/{t.id}/status/', {'status': 'abgesagt'})
            t.refresh_from_db()
            self.assertEqual(t.status, Termin.ABGESAGT)

    def test_abwesenheitsseite_zeigt_die_vertretung(self):
        from benutzer.models import Benutzer
        heute = timezone.localdate()
        with mandant(self.a.organisation):
            Abwesenheit.objects.all().delete()
            zweiter = Benutzer.objects.create_user(
                username='vertreter-b', password='x', first_name='Silvia',
                last_name='Roux')
            Abwesenheit(benutzer=self.a.benutzer, von=heute, bis=heute,
                        vertreten_durch=zweiter).save()
        antwort = self._hole('/neu/abwesenheiten/')
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'vertreten durch')

    def test_abwesenheit_mit_ende_vor_beginn_wird_gemeldet(self):
        c = Client()
        c.force_login(self.a.benutzer)
        heute = timezone.localdate()
        with mandant(self.a.organisation):
            antwort = c.post('/neu/abwesenheiten/neu/', {
                'benutzer': self.a.benutzer.id,
                'von': heute.isoformat(),
                'bis': (heute - timedelta(days=1)).isoformat()}, follow=True)
            self.assertContains(antwort, 'Ende liegt vor dem Beginn')

    def test_die_heute_seite_fuehrt_beide_abschnitte(self):
        heute = timezone.localdate()
        with mandant(self.a.organisation):
            Termin(titel='Eigentümergespräch Blattner', art=Termin.GESPRAECH,
                   beginn=timezone.now() + timedelta(days=1)).save()
            Abwesenheit.objects.all().delete()
            Abwesenheit(benutzer=self.a.benutzer, von=heute,
                        bis=heute + timedelta(days=2)).save()
        antwort = self._hole('/neu/')
        self.assertContains(antwort, 'Eigentümergespräch Blattner')
        self.assertContains(antwort, 'Vertretung')
        self.assertContains(antwort, 'ohne Vertretung')


class MandantentrennungTests(TestCase):
    """Zwei neue Modelle heisst zwei neue Wege, fremde Daten zu zeigen."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_b_sieht_den_termin_von_a_nicht(self):
        with mandant(self.a.organisation):
            Termin(titel='Streng vertraulich A',
                   beginn=timezone.now() + timedelta(days=1)).save()
        c = Client()
        c.force_login(self.b.benutzer)
        with mandant(self.b.organisation):
            antwort = c.get('/neu/termine/')
        self.assertNotContains(antwort, 'Streng vertraulich A')

    def test_a_sieht_den_eigenen_sehr_wohl(self):
        """Gegenprobe — eine durchweg leere Seite bestünde sonst alles."""
        with mandant(self.a.organisation):
            Termin(titel='Streng vertraulich A',
                   beginn=timezone.now() + timedelta(days=1)).save()
            c = Client()
            c.force_login(self.a.benutzer)
            antwort = c.get('/neu/termine/')
        self.assertContains(antwort, 'Streng vertraulich A')

    def test_fremde_termin_id_liefert_404_nicht_403(self):
        """404, nicht 403: Ein 403 bestätigt, dass die ID existiert."""
        with mandant(self.a.organisation):
            t = Termin(titel='Nur für A', beginn=timezone.now() + timedelta(days=1))
            t.save()
        c = Client()
        c.force_login(self.b.benutzer)
        with mandant(self.b.organisation):
            antwort = c.post(f'/neu/termine/{t.id}/status/', {'status': 'abgesagt'})
        self.assertEqual(antwort.status_code, 404)
        t.refresh_from_db()
        self.assertEqual(t.status, Termin.GEPLANT, 'Der fremde Termin wurde geändert.')

    def test_b_sieht_die_abwesenheit_von_a_nicht(self):
        heute = timezone.localdate()
        with mandant(self.a.organisation):
            Abwesenheit.objects.all().delete()
            Abwesenheit(benutzer=self.a.benutzer, von=heute, bis=heute,
                        notiz='Kur in Bad Ragaz').save()
        c = Client()
        c.force_login(self.b.benutzer)
        with mandant(self.b.organisation):
            antwort = c.get('/neu/abwesenheiten/')
        self.assertNotContains(antwort, 'Kur in Bad Ragaz')

    def test_die_auswahl_zeigt_nur_die_eigene_belegschaft(self):
        """Sonst stünde im Formular die Belegschaft des Nachbarn."""
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            antwort = c.get('/neu/abwesenheiten/')
        self.assertNotContains(antwort, self.b.benutzer.username)
        self.assertContains(antwort, self.a.benutzer.username)
