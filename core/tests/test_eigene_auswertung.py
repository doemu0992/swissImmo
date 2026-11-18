"""Eigene Auswertungen und Exportvorlagen (Modul «Erweitertes Reporting»).

Das Modul stand auf der Preisseite (CHF 19 je Monat, ab Professional inklusive) und im Katalog, war aber nicht gebaut.
Geprüft wird: anlegen, ausführen, CSV, Rechte, Mandantentrennung und die Sperre nach Stufe.

Gegenprobe (16.11.2026): `funktion_erforderlich('reporting_erweitert')` an der Liste entfernt -> Sperr-Test rot;
`quelle__in=erlaubt` in `_sichtbar` entfernt -> der Test «Finanzquelle nur mit Finanzrolle» rot; in `spalten_von`
unbekannte Schlüssel durchgelassen -> der Test «fremde Spalte» rot.
"""
from datetime import date

from django.test import TestCase, override_settings

from core.models import Auswertungsvorlage
from core.services import eigene_auswertung as dienst
from core.tenancy import organisation_kontext
from crm.models import Mitgliedschaft

from ._isolation import MandantenFixture

LISTE = '/neu/auswertung/eigene/'


@override_settings(SWISSIMMO_VORGABE_STUFE='professional')
class EigeneAuswertungTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _anlegen(self, **felder):
        daten = {'name': 'Zinsliste Quartal', 'quelle': 'debitoren', 'zeitraum': 'alle',
                 'spalten': ['debitoren:datum', 'debitoren:titel', 'debitoren:betrag', 'debitoren:mieter_nachname'],
                 **felder}
        return self.client.post(f'{LISTE}neu/', daten)

    def setUp(self):
        Auswertungsvorlage.alle_organisationen.all().delete()        # die Fixture bringt je Verwaltung eine mit
        self.client.force_login(self.a.benutzer)

    def _vorlage(self):
        return Auswertungsvorlage.alle_organisationen.get(organisation=self.a.organisation)

    def test_anlegen_ausfuehren_und_csv(self):
        antwort = self._anlegen()
        vorlage = self._vorlage()
        self.assertRedirects(antwort, f'{LISTE}{vorlage.pk}/')
        self.assertEqual(vorlage.spalten, ['datum', 'titel', 'betrag', 'mieter_nachname'])
        seite = self.client.get(f'{LISTE}{vorlage.pk}/')
        self.assertEqual(seite.context['kopf'], ['Rechnungsdatum', 'Titel', 'Betrag', 'Mieter Nachname'])
        self.assertEqual(seite.context['zeilen'], [['01.02.2024', 'Miete 02/2024 A', "1'700.00", 'A']])
        csv = self.client.get(f'{LISTE}{vorlage.pk}/?export=csv')
        self.assertEqual(csv['Content-Type'], 'text/csv; charset=utf-8')
        zeilen = csv.content.decode('utf-8-sig').strip().split('\r\n')
        self.assertEqual(zeilen, ['Rechnungsdatum;Titel;Betrag;Mieter Nachname', '01.02.2024;Miete 02/2024 A;1700.00;A'])

    def test_die_reihenfolge_der_spalten_ist_die_der_quelle_und_unbekanntes_faellt_weg(self):
        self._anlegen(spalten=['debitoren:betrag', 'debitoren:gibt_es_nicht', 'debitoren:organisation_id',
                               'debitoren:betrag', 'debitoren:datum'])
        self.assertEqual(self._vorlage().spalten, ['betrag', 'datum'])

    def test_spalten_einer_anderen_quelle_zaehlen_nicht(self):
        antwort = self._anlegen(spalten=['kreditoren:lieferant'])
        self.assertEqual(antwort.status_code, 400)
        self.assertContains(antwort, 'mindestens eine Spalte', status_code=400)
        self.assertFalse(Auswertungsvorlage.alle_organisationen.exists())

    def test_name_ist_pflicht_und_je_verwaltung_eindeutig(self):
        self.assertEqual(self._anlegen(name='').status_code, 400)
        self._anlegen()
        self.assertEqual(self._anlegen().status_code, 400)
        self.assertEqual(Auswertungsvorlage.alle_organisationen.count(), 1)

    def test_zeitraum_und_liegenschaft_schraenken_ein(self):
        self._anlegen(zeitraum='vorjahr', liegenschaft=self.a.liegenschaft.pk)
        vorlage = self._vorlage()
        with organisation_kontext(self.a.organisation):
            self.assertEqual(len(dienst.zeilen(vorlage, heute=date(2025, 6, 1))[1]), 1)     # Rechnung von 2024
            self.assertEqual(len(dienst.zeilen(vorlage, heute=date(2027, 6, 1))[1]), 0)
        self.assertEqual(dienst.zeitraum('monat', date(2026, 2, 10)), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(dienst.zeitraum('alle'), (None, None))

    def test_fremde_liegenschaft_wird_abgewiesen(self):
        antwort = self._anlegen(liegenschaft=self.b.liegenschaft.pk)
        self.assertEqual(antwort.status_code, 400)
        self.assertFalse(Auswertungsvorlage.alle_organisationen.exists())

    def test_mandantentrennung(self):
        self._anlegen()
        vorlage = self._vorlage()
        from django.test import Client
        self.client = Client()                      # frischer Browser: die Erfolgsmeldung von A hängt sonst am Cookie
        self.client.force_login(self.b.benutzer)
        for pfad in (f'{LISTE}{vorlage.pk}/', f'{LISTE}{vorlage.pk}/?export=csv', f'{LISTE}{vorlage.pk}/bearbeiten/'):
            self.assertEqual(self.client.get(pfad).status_code, 404, pfad)
        self.assertEqual(self.client.post(f'{LISTE}{vorlage.pk}/loeschen/').status_code, 404)
        self.assertNotContains(self.client.get(LISTE), 'Zinsliste Quartal')
        # B sieht mit derselben Vorlagenform nur den eigenen Bestand.
        self._anlegen(name='B-Liste')
        b_vorlage = Auswertungsvorlage.alle_organisationen.get(organisation=self.b.organisation, name='B-Liste')
        zeilen = self.client.get(f'{LISTE}{b_vorlage.pk}/').context['zeilen']
        self.assertEqual([z[1] for z in zeilen], ['Miete 02/2024 B'])

    def test_bearbeiten_und_loeschen(self):
        self._anlegen()
        vorlage = self._vorlage()
        self.assertContains(self.client.get(f'{LISTE}{vorlage.pk}/bearbeiten/'), 'Zinsliste Quartal')
        self.client.post(f'{LISTE}{vorlage.pk}/bearbeiten/', {
            'name': 'Mietverträge', 'quelle': 'vertraege', 'zeitraum': 'alle',
            'spalten': ['vertraege:objekt', 'vertraege:status']})
        vorlage.refresh_from_db()
        self.assertEqual((vorlage.name, vorlage.quelle, vorlage.spalten), ('Mietverträge', 'vertraege', ['objekt', 'status']))
        self.client.post(f'{LISTE}{vorlage.pk}/loeschen/')
        self.assertFalse(Auswertungsvorlage.alle_organisationen.exists())

    def test_lesezugriff_fuehrt_aus_darf_aber_nichts_aendern(self):
        self._anlegen()
        vorlage = self._vorlage()
        Mitgliedschaft.alle_organisationen.filter(benutzer=self.a.benutzer).update(rolle=Mitgliedschaft.ROLLE_LESEZUGRIFF)
        self.assertEqual(self.client.get(f'{LISTE}{vorlage.pk}/').status_code, 200)
        self.assertEqual(self.client.post(f'{LISTE}neu/', {'name': 'x'}).status_code, 403)
        self.assertEqual(self.client.post(f'{LISTE}{vorlage.pk}/loeschen/').status_code, 403)
        self.assertNotContains(self.client.get(LISTE), 'data-auswertung-formular')

    def test_finanzquelle_nur_mit_finanzrolle(self):
        """Der Hauswart hat keine Leserolle für Auswertungen; die Quellenliste trennt Finanzdaten ab."""
        self.assertEqual([k for k, _n in dienst.quellen_fuer(False)], ['vertraege', 'objekte', 'schaeden'])
        self.assertIn('debitoren', [k for k, _n in dienst.quellen_fuer(True)])
        Mitgliedschaft.alle_organisationen.filter(benutzer=self.a.benutzer).update(rolle=Mitgliedschaft.ROLLE_HAUSWART)
        self.assertEqual(self.client.get(LISTE).status_code, 403)

    def test_jede_spalte_jeder_quelle_laesst_sich_abfragen(self):
        """Wächter: Ein Tippfehler in einem Pfad fiele sonst erst beim Kunden auf."""
        with organisation_kontext(self.a.organisation):
            for k, q in dienst.QUELLEN.items():
                vorlage = Auswertungsvorlage(quelle=k, spalten=[s[0] for s in q['spalten']], zeitraum='jahr')
                kopf, _zeilen = dienst.zeilen(vorlage)
                self.assertEqual(len(kopf), len(q['spalten']), k)


class SperreNachStufeTests(TestCase):
    """Das Modul ist ab Professional inklusive und darunter zubuchbar."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_team_ohne_modul_sieht_die_sperrseite_und_mit_modul_die_liste(self):
        from abo.models import Abonnement
        self.client.force_login(self.a.benutzer)
        with override_settings(SWISSIMMO_VORGABE_STUFE='team'):
            Abonnement.alle_organisationen.update_or_create(
                organisation=self.a.organisation, defaults={'uneingeschraenkt': False, 'zusatzmodule': []})
            self.assertEqual(self.client.get(LISTE).status_code, 402)
            self.assertEqual(self.client.post(f'{LISTE}neu/', {'name': 'x'}).status_code, 402)
            Abonnement.alle_organisationen.filter(organisation=self.a.organisation).update(
                zusatzmodule=['reporting_erweitert'])
            self.assertEqual(self.client.get(LISTE).status_code, 200)
        with override_settings(SWISSIMMO_VORGABE_STUFE='professional'):
            Abonnement.alle_organisationen.filter(organisation=self.a.organisation).update(zusatzmodule=[])
            self.assertEqual(self.client.get(LISTE).status_code, 200)
