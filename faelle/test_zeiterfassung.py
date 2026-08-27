"""Aufwand lässt sich auf einem Fall erfassen — und rechnet nur, wenn er kann.

WAS BIS E2.46 FEHLTE

`faelle.Zeiteintrag` steht seit der ersten Migration im Modell: Fallbezug,
Datum, Minuten, Tätigkeit, Notiz, `verrechenbar`. Ausser den Migrationen hat
es **niemand benutzt** — es gab keinen Weg, einen Eintrag anzulegen.

`Fall.erfasste_minuten` zeigte deshalb auf jeder Fallakte »0 min«, und
`mandat_detail.html` trägt bis heute die Notiz, dass die Rentabilitätsansicht
»Zeiterfassung pro Fall voraussetzt, die es nicht gibt«.

DER STUNDENSATZ IST FREI — AN ZWEI ORTEN

`Organisation.stundensatz` ist die Vorgabe, `Zeiteintrag.satz` übersteuert
sie. Ein Notfalleinsatz am Sonntag kostet anders als eine Aktennotiz, und eine
Pauschale für ein Mandat wieder anders.

Der Eintrag **kopiert den Satz nicht** beim Erfassen. Ein kopierter Wert
friert ihn zum Erfassungszeitpunkt ein, und niemand sieht später, ob er
bewusst gesetzt oder nur mitgeschrieben wurde.

`null` HEISST »NICHT HINTERLEGT«, NICHT »NULL FRANKEN«

Dieselbe Unterscheidung wie bei `Geraet.neuwert`. Ist weder am Eintrag noch an
der Organisation ein Satz erfasst, gibt `betrag` `None` zurück und die
Oberfläche zeigt einen Strich. »CHF 0.00« wäre eine Aussage, die niemand
getroffen hat.
"""
from decimal import Decimal

from django.test import Client, TestCase

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture


class ZeitErfassenTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _fall(self):
        """Ein Fall im Mandanten A.

        `MandantenFixture` statt eines eigenen Helfers: `faelle` hat kein
        `_helfer`-Modul — derselbe Irrtum wie in E2.31, dort schon einmal
        notiert und hier wiederholt.
        """
        from faelle.models import Fall, Fallart

        org = self.a.organisation
        art = Fallart.objects.create(
            organisation=org, schluessel='pruefung', bezeichnung='Prüfung')
        # `betreff` und `akte=None` — nachgesehen in
        # `faelle/test_arbeitsvorrat.py`, nicht geraten. Ein erster Entwurf
        # nahm `titel` an; das Feld gibt es nicht.
        fall = Fall(organisation=org, fallart=art, akte=None,
                    betreff='Prüffall')
        fall.save()
        return fall

    def test_ein_eintrag_entsteht_und_zaehlt(self):
        """Der Kern: Vorher zeigte jede Fallakte «0 min»."""
        fall = self._fall()
        c = Client()
        c.force_login(self.a.benutzer)
        r = c.post(f'/neu/faelle/{fall.pk}/zeit/',
                   {'minuten': '25', 'taetigkeit': 'sonder',
                    'notiz': 'Telefonat Handwerker'})
        self.assertEqual(r.status_code, 302)
        fall.refresh_from_db()
        self.assertEqual(fall.erfasste_minuten, 25)

    def test_ohne_dauer_entsteht_nichts(self):
        """Ein leeres Formular darf keinen Nulleintrag anlegen.

        Ein Eintrag mit null Minuten sähe aus wie erfasster Aufwand und wäre
        keiner — dieselbe Sorte stiller Falschaussage wie »CHF 0.00«.
        """
        fall = self._fall()
        c = Client()
        c.force_login(self.a.benutzer)
        for wert in ('', '0', 'abc'):
            with self.subTest(minuten=wert):
                c.post(f'/neu/faelle/{fall.pk}/zeit/', {'minuten': wert})
        fall.refresh_from_db()
        self.assertEqual(fall.erfasste_minuten, 0)

    def test_der_betrag_rechnet_mit_dem_satz_der_organisation(self):
        fall = self._fall()
        fall.organisation.stundensatz = Decimal('120.00')
        fall.organisation.save(update_fields=['stundensatz'])
        c = Client()
        c.force_login(self.a.benutzer)
        c.post(f'/neu/faelle/{fall.pk}/zeit/',
               {'minuten': '30', 'taetigkeit': 'sonder', 'verrechenbar': 'on'})
        eintrag = fall.zeiteintraege.get()
        self.assertEqual(eintrag.betrag, Decimal('60.00'))

    def test_ein_eigener_satz_uebersteuert(self):
        """Der Sonntagseinsatz kostet anders."""
        fall = self._fall()
        fall.organisation.stundensatz = Decimal('120.00')
        fall.organisation.save(update_fields=['stundensatz'])
        c = Client()
        c.force_login(self.a.benutzer)
        c.post(f'/neu/faelle/{fall.pk}/zeit/',
               {'minuten': '60', 'taetigkeit': 'sonder',
                'verrechenbar': 'on', 'satz': '180'})
        self.assertEqual(fall.zeiteintraege.get().betrag, Decimal('180.00'))

    def test_ohne_satz_bleibt_der_betrag_leer(self):
        """`None`, nicht `0` — der Unterschied ist die ganze Aussage."""
        fall = self._fall()
        self.assertIsNone(fall.organisation.stundensatz)
        c = Client()
        c.force_login(self.a.benutzer)
        c.post(f'/neu/faelle/{fall.pk}/zeit/',
               {'minuten': '45', 'taetigkeit': 'sonder', 'verrechenbar': 'on'})
        self.assertIsNone(
            fall.zeiteintraege.get().betrag,
            'Ohne hinterlegten Satz entsteht ein Betrag — dann sieht «CHF '
            '0.00» aus wie eine Aussage, die niemand getroffen hat.')

    def test_nicht_verrechenbarer_aufwand_hat_keinen_betrag(self):
        fall = self._fall()
        fall.organisation.stundensatz = Decimal('120.00')
        fall.organisation.save(update_fields=['stundensatz'])
        c = Client()
        c.force_login(self.a.benutzer)
        c.post(f'/neu/faelle/{fall.pk}/zeit/',
               {'minuten': '30', 'taetigkeit': 'sonder'})
        self.assertIsNone(fall.zeiteintraege.get().betrag)

    def test_der_satz_wird_nicht_kopiert(self):
        """Sonst friert er zum Erfassungszeitpunkt ein.

        Wer den Satz der Organisation später ändert, will ihn in aller Regel
        auch für offene Aufwände geändert haben. Ein kopierter Wert verhindert
        das lautlos — und niemand sieht, ob er bewusst gesetzt wurde.
        """
        fall = self._fall()
        fall.organisation.stundensatz = Decimal('120.00')
        fall.organisation.save(update_fields=['stundensatz'])
        c = Client()
        c.force_login(self.a.benutzer)
        c.post(f'/neu/faelle/{fall.pk}/zeit/',
               {'minuten': '60', 'taetigkeit': 'sonder', 'verrechenbar': 'on'})
        eintrag = fall.zeiteintraege.get()
        self.assertIsNone(eintrag.satz,
                          'Der Satz wurde in den Eintrag kopiert.')

        fall.organisation.stundensatz = Decimal('150.00')
        fall.organisation.save(update_fields=['stundensatz'])
        eintrag.refresh_from_db()
        self.assertEqual(eintrag.betrag, Decimal('150.00'))

    def test_das_formular_steht_auf_der_fallakte(self):
        """Sonst gäbe es die Ansicht, aber keinen Weg dorthin."""
        fall = self._fall()
        c = Client()
        c.force_login(self.a.benutzer)
        html = c.get(f'/neu/faelle/{fall.pk}/').content.decode()
        self.assertIn(f'/neu/faelle/{fall.pk}/zeit/', html)
        self.assertIn('Aufwand erfassen', html)

    def test_der_betrag_rundet_auf_rappen(self):
        """Auf `0.01`, wie die 36 anderen Geldstellen im Bestand.

        Die erste Fassung schrieb `quantize(Decimal('0.05'))`. Das liest sich
        wie die 5-Rappen-Rundung des Zahlungsverkehrs, ist es aber nicht: Das
        Argument bestimmt nur den Exponenten, nicht die Schrittweite.
        Nachgerechnet ergeben beide Schreibweisen dasselbe — gleiches
        Ergebnis, irreführende Schreibweise.

        Geprüft wird deshalb ein Betrag, der nicht aufgeht: 100 CHF/h für
        sieben Minuten sind 11.6667.

        DIESER TEST UNTERSCHEIDET DIE BEIDEN SCHREIBWEISEN NICHT — er kann es
        nicht, weil sie dasselbe rechnen. Die Gegenprobe mit `0.05` bleibt
        grün. Er hält das VERHALTEN fest (auf Rappen, kaufmännisch); die
        Änderung an der Schreibweise ist eine Frage der Lesbarkeit, und das
        soll hier nicht als geprüfte Verhaltensänderung dastehen.
        """
        fall = self._fall()
        fall.organisation.stundensatz = Decimal('100.00')
        fall.organisation.save(update_fields=['stundensatz'])
        c = Client()
        c.force_login(self.a.benutzer)
        c.post(f'/neu/faelle/{fall.pk}/zeit/',
               {'minuten': '7', 'taetigkeit': 'sonder', 'verrechenbar': 'on'})
        self.assertEqual(fall.zeiteintraege.get().betrag, Decimal('11.67'))


class ZeitMandantengrenzeTest(TestCase):
    """Ein POST auf einen fremden Fall darf dort keinen Aufwand anlegen.

    Der Sweep in `core/tests/_isolation.py` prüft die Adresse mit, seit sie
    in `NAME_MUSTER` steht — ohne diesen Eintrag hätte er sie stillschweigend
    übersprungen. Dieser Test steht daneben, weil der Sweep die Adresse
    generisch prüft und dieser Test die Sache benennt: **404, nicht 403** (ein
    403 verriete, dass der Fall existiert), und **kein Eintrag**.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _fall_von_b(self):
        from faelle.models import Fall, Fallart

        with mandant(self.b.organisation):
            art = Fallart.objects.create(
                organisation=self.b.organisation, schluessel='pruefung',
                bezeichnung='Prüfung')
            fall = Fall(organisation=self.b.organisation, fallart=art,
                        akte=None, betreff='Fremdfall')
            fall.save()
        return fall

    def test_fremder_fall_bekommt_keinen_aufwand(self):
        from faelle.models import Zeiteintrag

        fall = self._fall_von_b()
        c = Client()
        c.force_login(self.a.benutzer)
        antwort = c.post(f'/neu/faelle/{fall.pk}/zeit/',
                         {'minuten': '30', 'taetigkeit': 'sonder'})
        self.assertEqual(
            antwort.status_code, 404,
            'Ein Benutzer von A erreicht den Fall von B — und 404, nicht '
            '403: Ein 403 verriete, dass die ID existiert.')
        self.assertEqual(
            Zeiteintrag.alle_organisationen.filter(fall=fall).count(), 0,
            'Auf dem fremden Fall ist Aufwand entstanden.')

    def test_die_pruefung_traefe_einen_echten_fall(self):
        """Gegenprobe: Im eigenen Mandanten geht es durch.

        Sonst wäre der Test oben auch grün, wenn die Adresse gar nicht
        funktioniert.
        """
        from faelle.models import Fall, Fallart

        with mandant(self.a.organisation):
            art = Fallart.objects.create(
                organisation=self.a.organisation, schluessel='eigen',
                bezeichnung='Eigen')
            fall = Fall(organisation=self.a.organisation, fallart=art,
                        akte=None, betreff='Eigenfall')
            fall.save()
        c = Client()
        c.force_login(self.a.benutzer)
        antwort = c.post(f'/neu/faelle/{fall.pk}/zeit/',
                         {'minuten': '30', 'taetigkeit': 'sonder'})
        self.assertEqual(antwort.status_code, 302)
        fall.refresh_from_db()
        self.assertEqual(fall.erfasste_minuten, 30)


class ZeitRollenTest(TestCase):
    """Wer nur lesen darf, bucht keinen Aufwand.

    Der erste Entwurf der Ansicht nahm `TEAM_ROLLEN` — dieselbe Zeile wie die
    Ansicht darunter, kopiert. `TEAM_ROLLEN` schliesst den Lesezugriff ein.
    `test_lesende_rolle_kann_nirgends_unbemerkt_schreiben` hat es gemeldet;
    dieser Test hält es an der Sache fest, nicht an der Sammelprüfung.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_lesezugriff_bucht_nichts(self):
        from core.tests._helfer import _team_user
        from faelle.models import Fall, Fallart

        with mandant(self.a.organisation):
            art = Fallart.objects.create(
                organisation=self.a.organisation, schluessel='eigen',
                bezeichnung='Eigen')
            fall = Fall(organisation=self.a.organisation, fallart=art,
                        akte=None, betreff='Eigenfall')
            fall.save()
        c = Client()
        c.force_login(_team_user(rolle='Lesezugriff'))
        antwort = c.post(f'/neu/faelle/{fall.pk}/zeit/',
                         {'minuten': '30', 'taetigkeit': 'sonder'})
        self.assertEqual(antwort.status_code, 403)
        fall.refresh_from_db()
        self.assertEqual(fall.erfasste_minuten, 0)
