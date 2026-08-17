"""Etappe 6.4 — Vorlagen: eigene UND mitgelieferte, aber keine fremden.

`crm.Vorlage` ist die einzige begründete Ausnahme von „nie `null=True` als
Dauerlösung" (Skill `mandantentrennung`, Regel 1):

    NULL     = mitgelieferte Systemvorlage, für alle Verwaltungen gleich
    gesetzt  = eigene Vorlage dieser Verwaltung

Daraus folgen drei Dinge, die alle schiefgehen können, und dieser Testsatz
prüft jedes einzeln:

1. **Lesen.** Ein gewöhnlicher Mandantenfilter liesse die Systemvorlagen
   verschwinden. In der Oberfläche sähe das wie Datenverlust aus, obwohl
   nichts fehlt.
2. **Anlegen.** Eine im Formular geschriebene Vorlage bekam bisher
   `organisation = NULL` — sie wurde damit zur *System*vorlage und war für
   **alle** Verwaltungen sichtbar. Der eigene Briefkopf im Postfach der
   Konkurrenz.
3. **Ändern und Löschen.** Eine Systemvorlage liess sich über das
   Bearbeiten-Formular direkt überschreiben — ein Schreibzugriff über die
   Mandantengrenze, ausgelöst durch ein gewöhnliches Formular.
"""
from django.test import TestCase
from django.urls import reverse

from crm.models import Organisation, Vorlage

from ._isolation import MandantenFixture


class VorlagenBasis(TestCase):
    """Zwei Verwaltungen, dazu eine mitgelieferte Systemvorlage."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        assert Organisation.objects.order_by('pk').first().pk == cls.a.organisation.pk

        cls.system = Vorlage.objects.create(
            organisation=None, name='System-Mahnung', kategorie='mahnung',
            betreff='Zahlungserinnerung', inhalt='Sehr geehrte {mieter_name}')
        cls.eigene_a = Vorlage.objects.create(
            organisation=cls.a.organisation, name='A-Brief', kategorie='brief',
            betreff='Von A', inhalt='Text A')
        cls.eigene_b = Vorlage.objects.create(
            organisation=cls.b.organisation, name='B-Brief', kategorie='brief',
            betreff='Von B', inhalt='Text B')


class LesenTests(VorlagenBasis):
    def test_eigene_und_mitgelieferte_sind_sichtbar(self):
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.b.organisation):
            namen = sorted(v.name for v in Vorlage.objects.all())
        # `Mahnung B` kommt aus dem Fixture und gehoert seit
        # `Vorlage.save()` korrekt der Verwaltung B.
        self.assertEqual(namen, ['B-Brief', 'Mahnung B', 'System-Mahnung'])

    def test_die_vorlage_der_anderen_verwaltung_ist_unsichtbar(self):
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.b.organisation):
            namen = {v.name for v in Vorlage.objects.all()}
        self.assertNotIn('A-Brief', namen)

    def test_gegenprobe_im_anderen_kontext_die_andere(self):
        # Ohne diese Gegenprobe wäre nicht belegt, dass gefiltert wird und
        # nicht bloss eine feste Auswahl zurückkommt.
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.a.organisation):
            namen = sorted(v.name for v in Vorlage.objects.all())
        self.assertEqual(namen, ['A-Brief', 'Mahnung A', 'System-Mahnung'])

    def test_ohne_kontext_wirft(self):
        from core.tenancy import OrganisationsFehler
        with self.assertRaises(OrganisationsFehler):
            list(Vorlage.objects.all())


class AnlegenTests(VorlagenBasis):
    """Eine selbst geschriebene Vorlage darf keine Systemvorlage werden."""

    def _als_b(self):
        self.b.benutzer.set_password('geheim-123')
        self.b.benutzer.save()
        self.client.force_login(self.b.benutzer)

    def test_neue_vorlage_gehoert_der_eigenen_verwaltung(self):
        # Vorher blieb `organisation` NULL — und damit war jede selbst
        # geschriebene Vorlage für ALLE Verwaltungen sichtbar.
        self._als_b()
        antwort = self.client.post(reverse('fw_vorlage_neu'), {
            'name': 'Ganz eigene', 'kategorie': 'brief',
            'betreff': 'Intern', 'inhalt': 'Nur für B'})
        self.assertIn(antwort.status_code, (302, 200))

        neu = Vorlage.alle_organisationen.filter(name='Ganz eigene').first()
        self.assertIsNotNone(neu, 'Die Vorlage wurde gar nicht angelegt.')
        self.assertEqual(neu.organisation_id, self.b.organisation.pk,
                         'Die neue Vorlage ist eine Systemvorlage geworden — '
                         'sichtbar für jede Verwaltung.')

    def test_und_ist_fuer_die_andere_verwaltung_unsichtbar(self):
        self._als_b()
        self.client.post(reverse('fw_vorlage_neu'), {
            'name': 'Ganz eigene', 'kategorie': 'brief',
            'betreff': 'Intern', 'inhalt': 'Nur für B'})

        from core.tenancy import organisation_kontext
        with organisation_kontext(self.a.organisation):
            namen = {v.name for v in Vorlage.objects.all()}
        self.assertNotIn('Ganz eigene', namen)


class SystemvorlageSchuetzenTests(VorlagenBasis):
    """Die mitgelieferte Vorlage gehört niemandem — und darf niemandem weichen."""

    def _als_b(self):
        self.client.force_login(self.b.benutzer)

    def test_bearbeiten_erzeugt_eine_kopie_statt_zu_ueberschreiben(self):
        self._als_b()
        self.client.post(reverse('fw_vorlage_bearbeiten', args=[self.system.pk]), {
            'name': 'System-Mahnung', 'kategorie': 'mahnung',
            'betreff': 'Geändert durch B', 'inhalt': 'B-Fassung'})

        self.system.refresh_from_db()
        self.assertEqual(self.system.betreff, 'Zahlungserinnerung',
                         'Die mitgelieferte Vorlage wurde überschrieben — '
                         'für JEDE Verwaltung.')

        kopie = Vorlage.alle_organisationen.filter(
            name='System-Mahnung', organisation=self.b.organisation).first()
        self.assertIsNotNone(kopie, 'Es entstand keine eigene Fassung.')
        self.assertEqual(kopie.betreff, 'Geändert durch B')

    def test_die_kopie_ist_fuer_die_andere_verwaltung_unsichtbar(self):
        self._als_b()
        self.client.post(reverse('fw_vorlage_bearbeiten', args=[self.system.pk]), {
            'name': 'System-Mahnung', 'kategorie': 'mahnung',
            'betreff': 'Geändert durch B', 'inhalt': 'B-Fassung'})

        from core.tenancy import organisation_kontext
        with organisation_kontext(self.a.organisation):
            betreffe = {v.betreff for v in Vorlage.objects.all()}
        self.assertNotIn('Geändert durch B', betreffe)
        self.assertIn('Zahlungserinnerung', betreffe,
                      'A sieht die mitgelieferte Vorlage nicht mehr.')

    def test_loeschen_wird_abgelehnt(self):
        self._als_b()
        self.client.post(reverse('fw_vorlage_loeschen', args=[self.system.pk]))
        self.assertTrue(
            Vorlage.alle_organisationen.filter(pk=self.system.pk).exists(),
            'Eine mitgelieferte Vorlage wurde gelöscht — sie fehlt damit allen.')

    def test_gegenprobe_die_eigene_laesst_sich_loeschen(self):
        # Ohne diese Gegenprobe wäre nicht belegt, dass der Schutz die
        # Systemvorlage meint und nicht schlicht jedes Löschen verhindert.
        self._als_b()
        self.client.post(reverse('fw_vorlage_loeschen', args=[self.eigene_b.pk]))
        self.assertFalse(Vorlage.alle_organisationen.filter(pk=self.eigene_b.pk).exists())


class SeedingTests(TestCase):
    """Das Anlegen der Standardvorlagen läuft ohne Kontext — und doppelt nicht."""

    def test_zweimal_seeden_erzeugt_keine_duplikate(self):
        from core.services.vorlagen_defaults import seed_standard_vorlagen
        erste = seed_standard_vorlagen()
        zweite = seed_standard_vorlagen()
        self.assertGreater(erste, 0, 'Es wurde gar nichts angelegt — Test prüft nichts.')
        self.assertEqual(zweite, 0, 'Der zweite Lauf hat Duplikate erzeugt.')

    def test_die_angelegten_sind_systemvorlagen(self):
        from core.services.vorlagen_defaults import seed_standard_vorlagen
        seed_standard_vorlagen()
        eigene = Vorlage.alle_organisationen.filter(organisation__isnull=False).count()
        self.assertEqual(eigene, 0,
                         'Standardvorlagen wurden einer Verwaltung zugeordnet — '
                         'dann sähen die anderen sie nicht.')
