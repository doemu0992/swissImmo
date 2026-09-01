"""Die Betreuung wird aufgelöst, nicht kopiert.

DIE FRAGE, DIE DAHINTER STEHT

«Diese Information muss auf alles vererbt und angezeigt werden, was mit der
Liegenschaft zu tun hat. Person, Objekt, Schadenfälle etc.»

Sie an jeder Akte zu SPEICHERN wäre die schnellere Lösung und die schlechtere:
Beim Wechsel müsste jemand alle Kopien nachziehen, und wer es vergisst, hat
zwei Antworten auf dieselbe Frage. Deshalb geht ein Baustein von jedem
Datensatz die Kette hoch zur Liegenschaft.

DIESE TESTS PRÜFEN JEDEN WEG EINZELN — sonst bliebe offen, ob die Auflösung
für alle Aktentypen trägt oder nur für den, den ich gerade offen hatte.
"""
from django.test import TestCase

from core.templatetags.betreuung import betreut_von
from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture


class BetreuungAufloesenTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from benutzer.models import Benutzer
        from crm.models import Mitgliedschaft

        cls.a = MandantenFixture('A', '8000', 'Zürich')
        with mandant(cls.a.organisation):
            cls.lea = Benutzer.objects.create_user(
                username='lea-btr', password='x', first_name='Lea',
                last_name='Frey')
            Mitgliedschaft.objects.create(
                benutzer=cls.lea, organisation=cls.a.organisation)

    def _mit_betreuung(self):
        from portfolio.models import Liegenschaft

        with mandant(self.a.organisation):
            lg = Liegenschaft.objects.first()
            lg.betreut_von = self.lea
            lg.save(update_fields=['betreut_von'])
        return lg

    def test_die_liegenschaft_selbst(self):
        self.assertEqual(betreut_von(self._mit_betreuung()), self.lea)

    def test_ueber_die_einheit(self):
        from portfolio.models import Einheit

        self._mit_betreuung()
        with mandant(self.a.organisation):
            einheit = Einheit.objects.first()
        self.assertEqual(betreut_von(einheit), self.lea)

    def test_ueber_den_vertrag(self):
        """Vertrag → Einheit → Liegenschaft, zwei Glieder."""
        from rentals.models import Mietvertrag

        self._mit_betreuung()
        with mandant(self.a.organisation):
            vertrag = Mietvertrag.objects.first()
        if vertrag is None:
            self.skipTest('Die Fixture hat keinen Vertrag.')
        self.assertEqual(betreut_von(vertrag), self.lea)

    def _zweite_liegenschaft(self, betreuer):
        """Eine frühere Wohnung, von jemand anderem betreut."""
        from decimal import Decimal
        from portfolio.models import Einheit, Liegenschaft

        with mandant(self.a.organisation):
            lg = Liegenschaft.objects.create(
                strasse='Alt-Weg 1', plz='8000', ort='Zürich',
                organisation=self.a.organisation, betreut_von=betreuer,
                versicherungswert=Decimal('1000000'))
            return Einheit.objects.create(
                liegenschaft=lg, bezeichnung='Alt 2.5 Zi', typ='whg',
                nettomiete_aktuell=Decimal('1000'),
                nebenkosten_aktuell=Decimal('100'))

    def _frueherer_vertrag(self, einheit, beginn):
        from datetime import date
        from decimal import Decimal
        from rentals.models import Mietvertrag

        with mandant(self.a.organisation):
            return Mietvertrag.objects.create(
                mieter=self.a.mieter, einheit=einheit, beginn=beginn,
                netto_mietzins=Decimal('1000'), nebenkosten=Decimal('100'),
                status='archiviert', kautions_betrag=Decimal('0'))

    def test_beim_mieter_zaehlt_der_aktive_vertrag(self):
        """Wer ausgezogen ist, wird nicht mehr von der alten Liegenschaft betreut.

        Der ausgezogene Vertrag beginnt hier ABSICHTLICH SPÄTER als der
        aktive. Eine Auflösung, die nur nach `-beginn` sortiert, wäre sonst
        zufällig richtig und dieser Test blind für den Unterschied.

        `archiviert` ist ein ECHTER Wert aus `VERTRAG_STATUS`. Die erste
        Fassung schrieb `'beendet'` — ein Status, den es nicht gibt. Django
        prüft `choices` bei `create()` nicht, der Wert landet stumm in der
        Datenbank, und ein Test auf einer Auswahl, die keine Auswertung je
        trifft, misst nichts. `test_auswahlwerte` hat es gemeldet.
        """
        from datetime import date

        from benutzer.models import Benutzer
        from crm.models import Mitgliedschaft

        self._mit_betreuung()                       # aktuelle Wohnung → Lea
        with mandant(self.a.organisation):
            alt = Benutzer.objects.create_user(
                username='alt-btr', password='x', first_name='Alt',
                last_name='Betreuer')
            Mitgliedschaft.objects.create(
                benutzer=alt, organisation=self.a.organisation)
        self._frueherer_vertrag(self._zweite_liegenschaft(alt), date(2025, 6, 1))
        self.assertEqual(betreut_von(self.a.mieter), self.lea)

    def test_ohne_aktiven_vertrag_zaehlt_der_juengste(self):
        """Bei einem ehemaligen Mieter ist das die letzte bekannte
        Zuständigkeit — besser als keine."""
        from datetime import date

        from benutzer.models import Benutzer
        from crm.models import Mitgliedschaft

        with mandant(self.a.organisation):
            alt = Benutzer.objects.create_user(
                username='alt-btr2', password='x', first_name='Alt',
                last_name='Betreuer')
            Mitgliedschaft.objects.create(
                benutzer=alt, organisation=self.a.organisation)
        self._frueherer_vertrag(self._zweite_liegenschaft(alt), date(2025, 6, 1))
        with mandant(self.a.organisation):
            self.a.vertrag.status = 'archiviert'
            self.a.vertrag.save(update_fields=['status'])
        self.assertEqual(betreut_von(self.a.mieter), alt)

    def test_ohne_betreuung_kommt_none(self):
        """`None` heisst «nicht zugeteilt» — eine Aussage, keine Lücke.

        Die Akte zeigt das in Warnfarbe: Eine Liegenschaft ohne Betreuung soll
        auffallen, sonst fällt der nächste Fall wieder dem zu, der ihn
        zufällig öffnet.
        """
        from portfolio.models import Liegenschaft

        with mandant(self.a.organisation):
            lg = Liegenschaft.objects.first()
            lg.betreut_von = None
            lg.save(update_fields=['betreut_von'])
        self.assertIsNone(betreut_von(lg))

    def test_etwas_ohne_liegenschaft_bricht_nicht(self):
        """Ein Eigentümer hat keine Liegenschaft über sich.

        Der Baustein muss `None` liefern, nicht scheitern — sonst reisst eine
        Randangabe die ganze Akte mit.
        """
        from crm.models import Eigentuemer

        with mandant(self.a.organisation):
            md = Eigentuemer.objects.first()
        self.assertIsNone(betreut_von(md))

    def test_none_bricht_nicht(self):
        self.assertIsNone(betreut_von(None))


class BetreuungAufDenSeitenTests(TestCase):
    """Aufgelöst ist nicht angezeigt.

    WARUM ES DIESE KLASSE BRAUCHT

    Die Tests oben prüfen den Baustein. Sie waren grün, während vier der fünf
    Akten die Betreuung gar nicht zeigten:

      · `schaden_detail.html` löste `{% betreut_von s %}` auf — die
        Kontextvariable heisst `t`. Ein unbekannter Name ist in einer Vorlage
        kein Fehler, sondern leer: Auf JEDER Schadenakte stand «nicht
        zugeteilt», auch wenn die Liegenschaft zugeteilt war.
      · Auf drei weiteren Akten stand die Zeile INNERHALB einer fremden
        Bedingung — `{% if lg.eigentuemer %}`, `{% if m.geburtsdatum %}`,
        `{% if kopf_eigentuemer %}`. Eine Liegenschaft ohne Mandat oder ein
        Mieter ohne Geburtsdatum hatte damit keine Betreuung auf der Seite,
        obwohl sie eine hatte.

    Beides ist von aussen unsichtbar: Die Seite lädt, sieht vollständig aus
    und schweigt an der einen Stelle, auf die es ankommt. Ein Test auf den
    Baustein bleibt dabei grün — er ruft die Vorlage nie auf.

    Das Fixture ist deshalb GENAU SO GEBAUT, dass jede dieser Bedingungen
    falsch ist: Liegenschaft ohne Eigentümer, Mieter ohne Geburtsdatum. Wäre
    es «vollständig», liefe der Test an den Fehlern vorbei.
    """

    @classmethod
    def setUpTestData(cls):
        from benutzer.models import Benutzer
        from crm.models import Mitgliedschaft

        cls.a = MandantenFixture('A', '8000', 'Zürich')
        with mandant(cls.a.organisation):
            cls.lea = Benutzer.objects.create_user(
                username='lea-seite', password='x', first_name='Lea',
                last_name='Frey')
            Mitgliedschaft.objects.create(
                benutzer=cls.lea, organisation=cls.a.organisation)
            # Kein Eigentümer, kein Geburtsdatum — siehe Klassendoku.
            cls.a.liegenschaft.eigentuemer = None
            cls.a.liegenschaft.betreut_von = cls.lea
            cls.a.liegenschaft.save(update_fields=['eigentuemer', 'betreut_von'])

    def setUp(self):
        self.client.force_login(self.a.benutzer)

    def _seiten(self):
        return {
            'Liegenschaft': f'/neu/liegenschaften/{self.a.liegenschaft.pk}/',
            'Objekt':       f'/neu/objekte/{self.a.einheit.pk}/',
            'Vertrag':      f'/neu/vertraege/{self.a.vertrag.pk}/',
            'Schaden':      f'/neu/schaeden/{self.a.schaden.pk}/',
            'Person':       f'/neu/personen/{self.a.mieter.pk}/',
        }

    def test_alle_fuenf_akten_nennen_die_betreuung(self):
        for name, pfad in self._seiten().items():
            with self.subTest(akte=name):
                antwort = self.client.get(pfad)
                self.assertEqual(antwort.status_code, 200)
                html = antwort.content.decode()
                self.assertIn('Betreut von', html,
                              f'{name}: Die Zeile fehlt ganz.')
                self.assertIn('Lea Frey', html,
                              f'{name}: Die Zeile steht da, nennt aber niemanden.')

    def test_ohne_zuteilung_steht_es_in_warnfarbe_da(self):
        """«nicht zugeteilt» ist eine Aussage, kein leeres Feld.

        Die Person ist hier ausgenommen: Ein Mieter ohne Vertrag hat keine
        Liegenschaft über sich, und «nicht zugeteilt» wäre dort eine Aussage
        über etwas, das es nicht gibt.
        """
        with mandant(self.a.organisation):
            self.a.liegenschaft.betreut_von = None
            self.a.liegenschaft.save(update_fields=['betreut_von'])
        for name, pfad in self._seiten().items():
            if name == 'Person':
                continue
            with self.subTest(akte=name):
                html = self.client.get(pfad).content.decode()
                self.assertIn('nicht zugeteilt', html,
                              f'{name}: Die fehlende Zuteilung fällt nicht auf.')

    def test_die_person_bekommt_sie_ueber_ihren_vertrag(self):
        """Der eigene Weg — ein Mieter hat keine Liegenschaft, nur einen Vertrag.

        Steht hier zusätzlich zur Sammelprüfung, weil er als einziger nicht
        über `liegenschaft` läuft und deshalb einzeln reissen kann.
        """
        html = self.client.get(
            f'/neu/personen/{self.a.mieter.pk}/').content.decode()
        self.assertIn('Lea Frey', html)

    def test_eine_fremde_akte_bleibt_verschlossen(self):
        """404, nicht 403 — ein 403 bestätigt, dass die ID existiert."""
        b = MandantenFixture('B', '3000', 'Bern')
        for pfad in (f'/neu/liegenschaften/{b.liegenschaft.pk}/',
                     f'/neu/objekte/{b.einheit.pk}/',
                     f'/neu/vertraege/{b.vertrag.pk}/',
                     f'/neu/schaeden/{b.schaden.pk}/',
                     f'/neu/personen/{b.mieter.pk}/'):
            with self.subTest(pfad=pfad):
                self.assertEqual(self.client.get(pfad).status_code, 404)
