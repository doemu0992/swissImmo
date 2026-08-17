"""Etappe 6.2 — der `TenantManager`, bevor er an ein Modell gehängt wird.

Die Anbindung ist zweimal gebaut, gemessen und zurückgenommen worden (65 bzw.
922 Fehlschläge). Beide Male lagen die Ursachen nicht am Filter selbst, sondern
an zwei Nebenwirkungen, die erst im Betrieb auffielen. Dieser Testsatz hält sie
fest, damit sie beim dritten Anlauf nicht wieder überraschen — und damit sie
später niemand versehentlich zurückbaut.

Geprüft wird an einem Modell, das eigens für den Test angelegt wird, statt an
einem echten. Grund: Der Manager muss auch dann noch beweisbar richtig sein,
wenn sich die echten Modelle ändern.
"""
from django.db import connection, models
from django.test import TestCase

from core.tenancy import (AlleOrganisationenManager, OrganisationsFehler,
                          TenantManager, ohne_organisation, organisation_kontext)
from crm.models import Organisation


class Haus(models.Model):
    """Ein Elternobjekt mit eigener Organisationsspalte."""
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        app_label = 'core'


class Zimmer(models.Model):
    """Ein Kind, dessen Organisation aus der Kette stammt (wie seit Etappe 5)."""
    haus = models.ForeignKey(Haus, on_delete=models.CASCADE, related_name='zimmer')
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        app_label = 'core'


class TenantManagerBasis(TestCase):
    @classmethod
    def setUpClass(cls):
        # VOR `super()`: Dessen `setUpClass` ruft `setUpTestData` auf, und das
        # legt bereits Zeilen an. Umgekehrt gaebe es die Tabellen zu spaet.
        with connection.schema_editor() as schema:
            schema.create_model(Haus)
            schema.create_model(Zimmer)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as schema:
            schema.delete_model(Zimmer)
            schema.delete_model(Haus)

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organisation.objects.create(firma='A AG', strasse='A 1', plz='8000', ort='Zürich')
        cls.org_b = Organisation.objects.create(firma='B AG', strasse='B 2', plz='3000', ort='Bern')
        cls.haus_a = Haus.objects.create(organisation=cls.org_a, name='Haus A')
        cls.haus_b = Haus.objects.create(organisation=cls.org_b, name='Haus B')
        for haus in (cls.haus_a, cls.haus_b):
            for i in (1, 2):
                Zimmer.objects.create(haus=haus, organisation=haus.organisation,
                                      name=f'{haus.name} Zi {i}')


class FilterTests(TenantManagerBasis):
    """Das Grundversprechen: `objects` zeigt nur die eigene Organisation."""

    def test_im_kontext_nur_eigene(self):
        with organisation_kontext(self.org_b):
            self.assertEqual([h.name for h in Haus.objects.all()], ['Haus B'])

    def test_gegenprobe_anderer_kontext_anderer_bestand(self):
        # Ohne diese Gegenprobe wäre nicht belegt, dass gefiltert und nicht
        # bloss eine feste Zeile zurückgegeben wird.
        with organisation_kontext(self.org_a):
            self.assertEqual([h.name for h in Haus.objects.all()], ['Haus A'])

    def test_ohne_kontext_wirft_statt_alles_zu_zeigen(self):
        # Die Alternative — im Zweifel alles herausgeben — ist genau das Leck,
        # das diese Etappe schliesst.
        with self.assertRaises(OrganisationsFehler):
            list(Haus.objects.all())

    def test_alle_organisationen_ist_der_benannte_weg_vorbei(self):
        self.assertEqual(Haus.alle_organisationen.count(), 2)


class RueckbezugTests(TenantManagerBasis):
    """Klippe 1 aus zwei gescheiterten Anläufen: Rückbezüge erben den Filter.

    Django baut den Manager eines Rückbezugs aus
    `related_model._default_manager.__class__`. Ohne Vorkehrung liefe damit
    jedes `haus.zimmer.all()` durch den Filter — und bräche in Services,
    Commands und der PDF-Erzeugung ab, wo gar kein Kontext gesetzt ist.
    """

    def test_rueckbezug_funktioniert_ohne_kontext(self):
        # Der Fall, der 65 Fehlschläge erzeugte.
        self.assertEqual(self.haus_b.zimmer.count(), 2)

    def test_rueckbezug_liefert_nur_die_kinder_dieses_objekts(self):
        # Das ist der eigentliche Grund, warum der Filter hier entbehrlich ist:
        # Die Beziehung selbst schränkt schon ein, und seit Etappe 5 leitet das
        # Kind seine Organisation aus genau dieser Kette ab.
        namen = sorted(z.name for z in self.haus_b.zimmer.all())
        self.assertEqual(namen, ['Haus B Zi 1', 'Haus B Zi 2'])
        self.assertNotIn('Haus A Zi 1', namen)

    def test_der_einstieg_bleibt_gefiltert(self):
        # Die Grenze wird am Einstieg gezogen, nicht in der Traversierung.
        # Wäre auch der gefiltert weggefallen, wäre die Isolation weg.
        with organisation_kontext(self.org_b):
            self.assertEqual(Zimmer.objects.count(), 2)
        with self.assertRaises(OrganisationsFehler):
            Zimmer.objects.count()

    def test_vorwaerts_fremdschluessel_bleibt_erreichbar(self):
        # Vorwärts nutzt Django `_base_manager` — ein gewöhnlicher Manager.
        # Belegt hier, weil die Isolation sonst am falschen Ort gesucht würde.
        zimmer = Zimmer.alle_organisationen.filter(haus=self.haus_b).first()
        self.assertEqual(zimmer.haus.name, 'Haus B')


class SchreibwegeTests(TenantManagerBasis):
    """Klippe 2: Was liest, muss filtern. Was nur schreibt, braucht es nicht."""

    def test_create_braucht_keinen_kontext(self):
        # `create` gibt nichts heraus — es kann über keine fremde Organisation
        # etwas verraten, weil es nichts liest.
        haus = Haus.objects.create(organisation=self.org_b, name='Neubau')
        self.assertIsNotNone(haus.pk)

    def test_get_or_create_filtert_jetzt(self):
        # Bis 6.2 stand `get_or_create` neben `create` in der Ausnahmeliste —
        # aus Gewohnheit, nicht aus Gründen. Es LIEST aber zuerst und gäbe ohne
        # Filter die Zeile eines fremden Mandanten zurück.
        with self.assertRaises(OrganisationsFehler):
            Haus.objects.get_or_create(name='Haus A', defaults={'organisation': self.org_a})

    def test_get_or_create_findet_fremde_zeile_nicht(self):
        # Im Kontext von B ist die Zeile von A unsichtbar — es entsteht also
        # eine EIGENE, statt dass A's Datensatz zurückgegeben wird.
        with organisation_kontext(self.org_b):
            haus, neu = Haus.objects.get_or_create(
                name='Haus A', defaults={'organisation': self.org_b})
        self.assertTrue(neu, 'Der Datensatz der anderen Organisation wurde zurückgegeben.')
        self.assertEqual(haus.organisation_id, self.org_b.pk)
        self.assertNotEqual(haus.pk, self.haus_a.pk)

    def test_update_or_create_aktualisiert_keine_fremde_zeile(self):
        with organisation_kontext(self.org_b):
            Haus.objects.update_or_create(name='Haus A', defaults={'organisation': self.org_b})
        self.haus_a.refresh_from_db()
        self.assertEqual(self.haus_a.organisation_id, self.org_a.pk,
                         'Die Zeile der anderen Organisation wurde überschrieben.')


class OhneOrganisationTests(TenantManagerBasis):
    """`ohne_organisation()` ist der ausdrückliche, sichtbare Ausstieg."""

    def test_kontextfrei_wirft_weiterhin(self):
        # Bewusst: `ohne_organisation()` hebt den Kontext auf, es macht den
        # Manager aber nicht blind. Wer alles will, nimmt `alle_organisationen`.
        with ohne_organisation():
            with self.assertRaises(OrganisationsFehler):
                list(Haus.objects.all())


class KontextLebensdauerTests(TestCase):
    """Der Testläufer begrenzt den Kontext auf den einzelnen Test.

    Die beiden Tests hängen absichtlich voneinander ab — und dürfen es genau
    deshalb NICHT. `aaa_` und `zzz_` erzwingen die Reihenfolge (unittest sortiert
    alphabetisch): Der erste setzt einen Kontext, der zweite prüft, dass er weg
    ist. Ohne `core.test_runner.MandantenTestRunner` schlägt der zweite fehl.

    Warum das eigens geprüft wird: Ein übergelaufener Kontext erzeugt Tests, die
    grün sind, weil ein anderer Test vorher etwas gesetzt hat — und rot, sobald
    jemand sie einzeln laufen lässt. Das ist die Sorte Fehler, die man erst
    Monate später und dann in der falschen Datei sucht.
    """

    def test_aaa_setzt_einen_kontext(self):
        from core.tenancy import aktuelle_organisation, setze_organisation
        organisation = Organisation.objects.create(
            firma='Leck AG', strasse='Weg 1', plz='8000', ort='Zürich')
        setze_organisation(organisation)
        self.assertIsNotNone(aktuelle_organisation())

    def test_zzz_der_kontext_des_vorigen_tests_ist_weg(self):
        from core.tenancy import aktuelle_organisation
        self.assertIsNone(
            aktuelle_organisation(),
            'Der Mandantenkontext ist aus einem anderen Test übergelaufen — '
            'ab hier hängt jedes Ergebnis von der Reihenfolge ab.')
