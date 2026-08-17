"""Etappe 6.1 — Öffentliche Endpunkte: die Organisation kommt vom Objekt.

Diese Endpunkte haben **keinen** Mandantenkontext: Mieter und Eigentümer haben
keine `Mitgliedschaft`, und die Bewerbungsseite erreicht man ohne Anmeldung.
Bis hierher zogen sie deshalb `Organisation.objects.first()` — mit genau einer
Verwaltung fällt das nicht auf, ab der zweiten liefert es systematisch die
falsche.

Alle Tests hier arbeiten mit **zwei** Beständen (`MandantenFixture`) und prüfen
gegen den **zweiten**. Mit nur einer Organisation wäre `first()` zufällig
richtig und der Test bewiese nichts — genau die Sorte Test, die in Etappe 5
dreimal überzeugend aussah und nichts prüfte.
"""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from crm.models import Organisation

from ._isolation import MandantenFixture


class ZweiBestaende(TestCase):
    """A zuerst, B danach — B ist damit nie `Organisation.objects.first()`."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        # Der Prüfstein des ganzen Moduls. Fiele er, prüften alle Tests
        # darunter versehentlich gegen die richtige Organisation.
        assert Organisation.objects.order_by('pk').first().pk == cls.a.organisation.pk


class DatenschutzVerantwortlicherTests(ZweiBestaende):
    """Die Erklärung muss den Verantwortlichen der richtigen Verwaltung nennen.

    Nach revDSG Art. 19 hängen Auskunfts- und Löschbegehren an dieser Angabe.
    Eine falsche Firma ist deshalb keine Anzeigefrage.
    """

    def test_mit_objekt_nennt_die_verwaltung_des_objekts(self):
        antwort = self.client.get(
            reverse('public_datenschutz_objekt', args=[self.b.einheit.id]))
        self.assertEqual(antwort.status_code, 200)
        inhalt = antwort.content.decode()
        self.assertIn('Verwaltung B AG', inhalt)
        self.assertNotIn('Verwaltung A AG', inhalt)

    def test_ohne_objekt_wird_bei_mehreren_KEINE_genannt(self):
        # Eine geratene Firma wäre schlimmer als keine.
        antwort = self.client.get(reverse('public_datenschutz'))
        self.assertEqual(antwort.status_code, 200)
        inhalt = antwort.content.decode()
        self.assertNotIn('Verwaltung A AG', inhalt)
        self.assertNotIn('Verwaltung B AG', inhalt)
        self.assertIn('Verwaltung des Objekts', inhalt)

    def test_bewerbungsformular_verlinkt_die_objektbezogene_fassung(self):
        # Ohne diesen Test bliebe die neue Route unbenutzt und die alte,
        # zweideutige weiterhin der Weg, den Bewerber tatsächlich gehen.
        einheit = self.b.einheit
        einheit.zur_ausschreibung = True
        einheit.save(update_fields=['zur_ausschreibung'])
        antwort = self.client.get(reverse('public_bewerbung', args=[einheit.id]))
        self.assertEqual(antwort.status_code, 200)
        self.assertIn(f'/bewerben/{einheit.id}/datenschutz/', antwort.content.decode())


class DatenschutzEinzelneVerwaltungTests(TestCase):
    """Gegenprobe zur Zweideutigkeit: Bei EINER Verwaltung wird sie genannt.

    Ohne diesen Test wäre nicht belegt, dass der Test oben die Mehrdeutigkeit
    misst — er würde auch bestehen, wenn die Seite nie eine Firma nennt.
    """

    def test_ohne_objekt_bei_einer_verwaltung(self):
        Organisation.objects.create(firma='Einzige AG', strasse='Weg 1',
                                    plz='3000', ort='Bern')
        antwort = self.client.get(reverse('public_datenschutz'))
        self.assertEqual(antwort.status_code, 200)
        self.assertIn('Einzige AG', antwort.content.decode())


class KuendigungsMeldungTests(ZweiBestaende):
    """Die Kündigung eines Mieters geht an SEINE Verwaltung."""

    def test_mail_geht_an_die_verwaltung_des_vertrags(self):
        from rentals.models import Kuendigung

        from core.views.portal import _benachrichtige_verwaltung_kuendigung

        organisation = self.b.organisation
        organisation.email = 'b@example.ch'
        organisation.save(update_fields=['email'])
        self.a.organisation.email = 'a@example.ch'
        self.a.organisation.save(update_fields=['email'])

        from core.tenancy import organisation_kontext
        with organisation_kontext(organisation):
            kuendigung = Kuendigung.objects.create(vertrag=self.b.vertrag)

        with patch('core.utils.email_service.send_ticket_email') as senden:
            _benachrichtige_verwaltung_kuendigung(self.b.vertrag, kuendigung)

        self.assertTrue(senden.called, 'Es wurde gar keine Mail versendet — Test prüft nichts.')
        empfaenger = senden.call_args[0][0]
        self.assertEqual(empfaenger, 'b@example.ch')
        self.assertNotEqual(empfaenger, 'a@example.ch')


class PortalBriefkopfTests(ZweiBestaende):
    """Kontoauszug und Kontokorrent tragen den Briefkopf der eigenen Verwaltung."""

    def test_kontoauszug_nutzt_die_organisation_des_mieters(self):
        self.b.mieter.benutzer = self.b.benutzer
        self.b.mieter.save(update_fields=['benutzer'])
        self.client.force_login(self.b.benutzer)

        with patch('core.services.mieterkonto.generate_mieterkonto_pdf',
                   return_value=b'%PDF-1.4') as erzeugen:
            antwort = self.client.get(reverse('mieter_kontoauszug_pdf'))

        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(erzeugen.called, 'PDF wurde nie erzeugt — Test prüft nichts.')
        self.assertEqual(erzeugen.call_args.kwargs['verwaltung'].pk, self.b.organisation.pk)


class AbleitungTests(ZweiBestaende):
    """Die Bezüge, auf die sich die Views oben stützen — einzeln belegt."""

    def test_vertrag_erbt_die_organisation_der_liegenschaft(self):
        self.assertEqual(self.b.vertrag.organisation_id, self.b.organisation.pk)

    def test_mieter_und_eigentuemer_tragen_ihre_organisation(self):
        self.assertEqual(self.b.mieter.organisation_id, self.b.organisation.pk)
        self.assertEqual(self.b.eigentuemer.organisation_id, self.b.organisation.pk)

    def test_liegenschaft_hat_kein_feld_verwaltung(self):
        # `getattr(liegenschaft, 'verwaltung', None) or Organisation.objects.first()`
        # stand in docuseal.py und docuseal_service.py und sah aus wie eine
        # Absicherung. Das Feld gibt es nicht — der Ausdruck fiel IMMER auf die
        # erste Organisation zurück. Dieser Test hält fest, warum er weg ist.
        from portfolio.models import Liegenschaft
        felder = {f.name for f in Liegenschaft._meta.get_fields()}
        self.assertNotIn('verwaltung', felder)
        self.assertIn('organisation', felder)
