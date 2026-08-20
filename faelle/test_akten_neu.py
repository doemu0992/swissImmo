"""Mandats- und Dienstleisterakte — die beiden Aktentypen ohne Detailseite.

WARUM SIE ERST JETZT ENTSTEHEN

`faelle/akten.py` führt sieben Aktentypen. Nach 4b.11 hatten fünf davon einen
Aktenkopf und den einheitlichen Reitersatz. Zwei hatten **überhaupt keine
Seite** — das Register beschrieb eine Akte, die es in der Oberfläche nicht gab.
Derselbe Befund wie beim Regelwerk in 4b.10, nur eine Ebene höher.

WAS HIER SCHARF SEIN MUSS

Zwei neue Seiten heisst zwei neue Wege, versehentlich fremde Daten zu zeigen.
Der Skill `mandantentrennung` verlangt für jede Änderung mindestens einen Test,
der den Zugriff über die Grenze **aktiv versucht** und mit 404 scheitert — ein
403 bestätigt, dass die ID existiert.

Und: Beide Seiten rechnen Beträge. Eine Summe, die geschätzte und effektive
Kosten still vermischt, sieht genauer aus, als sie ist — dafür steht
`KostenTests`.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture


class _Basis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.a.benutzer)


class MandatsakteTests(_Basis):

    def test_die_seite_gibt_es_ueberhaupt(self):
        """Bis 4b.12 antwortete diese Adresse mit 404."""
        antwort = self.client.get(f'/neu/mandate/{self.a.eigentuemer.pk}/')
        self.assertEqual(antwort.status_code, 200)

    def test_sie_traegt_den_aktenkopf(self):
        antwort = self.client.get(f'/neu/mandate/{self.a.eigentuemer.pk}/')
        self.assertContains(antwort, 'class="fw-aktenkopf"')
        self.assertContains(antwort, 'Mandat · M-')

    def test_jeder_reiter_findet_sein_panel(self):
        """Sonst blendet ein Klick alle Panels aus und hinterlässt eine leere
        Seite — der Fehler, den `test_reiter_panels` seit Etappe 5a verhindert."""
        import re
        antwort = self.client.get(f'/neu/mandate/{self.a.eigentuemer.pk}/')
        html = antwort.content.decode()
        reiter = re.findall(r'data-tab="md" data-target="([a-z0-9_]+)"', html)
        panels = set(re.findall(r'id="md-([a-z0-9_]+)"', html))
        self.assertTrue(reiter, 'Die Seite rendert keine Reiterleiste.')
        self.assertEqual([r for r in reiter if r not in panels], [])

    def test_genau_ein_panel_ist_offen_und_zwar_das_erste(self):
        import re
        antwort = self.client.get(f'/neu/mandate/{self.a.eigentuemer.pk}/')
        html = antwort.content.decode()
        reiter = re.findall(r'data-tab="md" data-target="([a-z0-9_]+)"', html)
        offen = re.findall(
            r'<div data-panel="md" id="md-([a-z0-9_]+)"(?![^>]*hidden)', html)
        self.assertEqual(offen, reiter[:1])

    def test_die_liegenschaften_stehen_mit_ihrer_sollmiete(self):
        antwort = self.client.get(f'/neu/mandate/{self.a.eigentuemer.pk}/')
        lgs = antwort.context['liegenschaften']
        self.assertTrue(lgs, 'Das Fixture ordnet dem Eigentümer eine Liegenschaft zu.')
        eine = next(l for l in lgs if l['lg'].pk == self.a.liegenschaft.pk)
        self.assertEqual(eine['einheiten'], self.a.liegenschaft.einheiten.count())

    def test_fehlende_iban_erzeugt_einen_hinweis_mit_ziel(self):
        """Konzept 16.3: Jeder Hinweis führt zu einer Handlung — sonst ist er
        eine Beschwerde."""
        self.a.eigentuemer.iban = ''
        self.a.eigentuemer.save()
        antwort = self.client.get(f'/neu/mandate/{self.a.eigentuemer.pk}/')
        hinweise = antwort.context['mandat_hinweise']
        iban = [h for h in hinweise if 'IBAN' in h['titel']]
        self.assertTrue(iban, 'Ohne IBAN fehlt der Hinweis.')
        self.assertTrue(iban[0]['url'] and iban[0]['knopf'])

    def test_erfasste_iban_erzeugt_keinen_hinweis(self):
        """Gegenprobe im Test selbst: Der Hinweis darf nicht immer erscheinen."""
        self.a.eigentuemer.iban = 'CH9300762011623852957'
        self.a.eigentuemer.save()
        antwort = self.client.get(f'/neu/mandate/{self.a.eigentuemer.pk}/')
        self.assertEqual(
            [h for h in antwort.context['mandat_hinweise'] if 'IBAN' in h['titel']], [])

    def test_keine_rentabilitaetskarte(self):
        """Der Prototyp zeigt sie; sie setzt Zeiterfassung pro Fall voraus.

        Sie fehlt absichtlich. Dieser Test hält das fest, damit sie nicht
        eines Tages mit geschätzten Stunden nachgereicht wird — eine Zahl aus
        Schätzungen wäre schlimmer als keine Zahl.
        """
        antwort = self.client.get(f'/neu/mandate/{self.a.eigentuemer.pk}/')
        html = antwort.content.decode()
        self.assertNotIn('Rentabilität', html)
        self.assertNotIn('CHF/Stunde', html)


class DienstleisterakteTests(_Basis):

    def test_die_seite_gibt_es_ueberhaupt(self):
        antwort = self.client.get(f'/neu/dienstleister/{self.a.handwerker.pk}/')
        self.assertEqual(antwort.status_code, 200)

    def test_sie_traegt_den_aktenkopf(self):
        antwort = self.client.get(f'/neu/dienstleister/{self.a.handwerker.pk}/')
        self.assertContains(antwort, 'class="fw-aktenkopf"')
        self.assertContains(antwort, 'Dienstleister · H-')

    def test_jeder_reiter_findet_sein_panel(self):
        import re
        antwort = self.client.get(f'/neu/dienstleister/{self.a.handwerker.pk}/')
        html = antwort.content.decode()
        reiter = re.findall(r'data-tab="dl" data-target="([a-z0-9_]+)"', html)
        panels = set(re.findall(r'id="dl-([a-z0-9_]+)"', html))
        self.assertTrue(reiter)
        self.assertEqual([r for r in reiter if r not in panels], [])

    def test_die_auftraege_stehen_zusammen(self):
        """Der eigentliche Zweck der Seite: Bis 4b.12 hingen sie einzeln an
        ihren Schadensmeldungen."""
        antwort = self.client.get(f'/neu/dienstleister/{self.a.handwerker.pk}/')
        auftraege = antwort.context['auftraege']
        self.assertIn(self.a.auftrag.pk, [a.pk for a in auftraege])

    def test_ein_alter_offener_auftrag_faellt_auf(self):
        from tickets.models import HandwerkerAuftrag
        alt = HandwerkerAuftrag.alle_organisationen.get(pk=self.a.auftrag.pk)
        alt.status = 'ausstehend'
        alt.save(update_fields=['status'])
        HandwerkerAuftrag.alle_organisationen.filter(pk=alt.pk).update(
            beauftragt_am=timezone.now() - timedelta(days=90))
        antwort = self.client.get(f'/neu/dienstleister/{self.a.handwerker.pk}/')
        self.assertGreaterEqual(antwort.context['dl_liegen'], 1)
        titel = [h['titel'] for h in antwort.context['dl_hinweise']]
        self.assertTrue(any('30 Tage' in t for t in titel))

    def test_ein_frischer_auftrag_faellt_nicht_auf(self):
        """Gegenprobe: Die Regel darf nicht auf jeden offenen Auftrag greifen."""
        from tickets.models import HandwerkerAuftrag
        frisch = HandwerkerAuftrag.alle_organisationen.get(pk=self.a.auftrag.pk)
        frisch.status = 'ausstehend'
        frisch.save(update_fields=['status'])
        HandwerkerAuftrag.alle_organisationen.filter(pk=frisch.pk).update(
            beauftragt_am=timezone.now() - timedelta(days=3))
        antwort = self.client.get(f'/neu/dienstleister/{self.a.handwerker.pk}/')
        self.assertEqual(antwort.context['dl_liegen'], 0)


class KostenTests(_Basis):
    """Eine Summe darf nicht genauer aussehen, als sie ist."""

    def _auftrag(self, effektiv=None, geschaetzt=None, jahr=None):
        """Legt einen Auftrag an und setzt sein Datum NACHTRAEGLICH.

        `HandwerkerAuftrag.beauftragt_am` traegt `auto_now_add=True`. Ein beim
        Anlegen mitgegebenes Datum wird von Django stillschweigend durch
        `now()` ersetzt — der erste Entwurf dieses Tests bemerkte das nur,
        weil der Vorjahres-Auftrag trotzdem mitzaehlte.

        Nebenbefund fuer den Betrieb: Damit laesst sich ein nachtraeglich
        erfasster Auftrag NICHT auf sein wirkliches Beauftragungsdatum setzen.
        Fuer die Jahreszahlen dieser Seite heisst das: Sie folgen dem
        Erfassungsdatum, nicht dem Auftragsdatum.
        """
        from tickets.models import HandwerkerAuftrag
        with mandant(self.a.organisation):
            a = HandwerkerAuftrag.objects.create(
                ticket=self.a.schaden, handwerker=self.a.handwerker,
                status='erledigt',
                kosten_effektiv=effektiv, kosten_geschaetzt=geschaetzt)
        wann = timezone.make_aware(
            datetime(jahr or timezone.localdate().year, 3, 1, 9, 0))
        # `update()` umgeht `auto_now_add` — `save()` taete es nicht.
        HandwerkerAuftrag.alle_organisationen.filter(pk=a.pk).update(beauftragt_am=wann)
        a.refresh_from_db()
        return a

    def test_effektive_kosten_zaehlen_voll(self):
        self._auftrag(effektiv=Decimal('1200.00'))
        antwort = self.client.get(f'/neu/dienstleister/{self.a.handwerker.pk}/')
        self.assertGreaterEqual(antwort.context['dl_kosten_jahr'], Decimal('1200.00'))
        self.assertEqual(antwort.context['kosten_geschaetzt_anteil'], Decimal('0.00'))

    def test_geschaetzte_kosten_werden_als_solche_ausgewiesen(self):
        self._auftrag(geschaetzt=Decimal('800.00'))
        antwort = self.client.get(f'/neu/dienstleister/{self.a.handwerker.pk}/')
        self.assertEqual(antwort.context['kosten_geschaetzt_anteil'], Decimal('800.00'))
        self.assertContains(antwort, 'geschätzt')

    def test_effektiv_schlaegt_geschaetzt(self):
        """Sind beide erfasst, gilt der effektive Betrag — sonst würde
        derselbe Auftrag doppelt zählen."""
        self._auftrag(effektiv=Decimal('900.00'), geschaetzt=Decimal('1500.00'))
        antwort = self.client.get(f'/neu/dienstleister/{self.a.handwerker.pk}/')
        self.assertEqual(antwort.context['kosten_geschaetzt_anteil'], Decimal('0.00'))

    def test_ein_auftrag_aus_dem_vorjahr_zaehlt_nicht_mit(self):
        vorher = self.client.get(
            f'/neu/dienstleister/{self.a.handwerker.pk}/').context['dl_kosten_jahr']
        self._auftrag(effektiv=Decimal('5000.00'),
                      jahr=timezone.localdate().year - 1)
        nachher = self.client.get(
            f'/neu/dienstleister/{self.a.handwerker.pk}/').context['dl_kosten_jahr']
        self.assertEqual(vorher, nachher)


class MandantentrennungTests(_Basis):
    """Aktive Versuche über die Grenze. Jeder muss mit 404 scheitern."""

    def test_fremdes_mandat_gibt_404(self):
        antwort = self.client.get(f'/neu/mandate/{self.b.eigentuemer.pk}/')
        self.assertEqual(antwort.status_code, 404)

    def test_fremder_dienstleister_gibt_404(self):
        antwort = self.client.get(f'/neu/dienstleister/{self.b.handwerker.pk}/')
        self.assertEqual(antwort.status_code, 404)

    def test_das_eigene_mandat_zeigt_keine_fremde_liegenschaft(self):
        antwort = self.client.get(f'/neu/mandate/{self.a.eigentuemer.pk}/')
        ids = [l['lg'].pk for l in antwort.context['liegenschaften']]
        self.assertIn(self.a.liegenschaft.pk, ids)
        self.assertNotIn(self.b.liegenschaft.pk, ids)

    def test_der_eigene_dienstleister_zeigt_keinen_fremden_auftrag(self):
        antwort = self.client.get(f'/neu/dienstleister/{self.a.handwerker.pk}/')
        ids = [a.pk for a in antwort.context['auftraege']]
        self.assertIn(self.a.auftrag.pk, ids)
        self.assertNotIn(self.b.auftrag.pk, ids)

    def test_die_kosten_summe_bleibt_beim_eigenen_bestand(self):
        """Ein Leck hier zeigte einer Verwaltung, was die andere ausgibt."""
        from tickets.models import HandwerkerAuftrag
        with mandant(self.b.organisation):
            HandwerkerAuftrag.objects.create(
                ticket=self.b.schaden, handwerker=self.b.handwerker,
                status='erledigt', beauftragt_am=timezone.localdate(),
                kosten_effektiv=Decimal('99999.00'))
        antwort = self.client.get(f'/neu/dienstleister/{self.a.handwerker.pk}/')
        self.assertLess(antwort.context['dl_kosten_jahr'], Decimal('99999.00'))
