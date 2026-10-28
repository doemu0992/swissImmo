"""Gemeinsame Konten (SICH-02, Audit 28.10.2026): nur die EIGENE Mitgliedschaft ist änderbar.

Der Befund: Eine Treuhänderin ist EIN Konto mit ZWEI Mitgliedschaften (vom Modell
ausdrücklich vorgesehen). Die Prüfung in `fw_benutzer_form` lautete «Mitglied in
A» und galt für das GANZE Konto: Der Inhaber von A konnte Passwort, E-Mail,
Aktiv-Flag und Gruppe überschreiben und damit die Inhaber-Rolle der Treuhänderin
bei B übernehmen (`probe1.py`).

Jetzt gilt: Ist das Konto auch anderswo in Gebrauch (weitere Mitgliedschaft,
Superuser), ändert der Inhaber einer Verwaltung nur die Rolle in SEINER
Verwaltung — oder beendet die Mitgliedschaft.

GEGENPROBEN (28.10.2026, je einzeln eingebaut, rot gesehen, zurückgebaut):
  * `nur_mitgliedschaft` immer False                    → `test_passwort…`, `…email…`,
                                                          `…aktiv…`, `…gruppe…` rot
  * `ziel.groups.set` ausserhalb von `if not nur_mitgliedschaft` → `test_globale_gruppe…` rot
  * `mitgliedschaft_beenden` ignoriert                  → `test_mitgliedschaft_beenden…` rot
  * `ziel.is_superuser` aus `_konto_gehoert_nicht_allein_uns` genommen → `test_superuser…` rot
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase

from crm.models import Mitgliedschaft

from ._isolation import MandantenFixture

User = get_user_model()


class GeteilteKontenBasis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        # Die Treuhänderin: Sachbearbeiterin bei A, INHABERIN bei B.
        cls.t = User.objects.create_user(username='treuhaenderin', password='ihr-eigenes-passwort',
                                         email='treu@example.ch', first_name='Tina', last_name='Treu')
        cls.t.groups.add(Group.objects.get_or_create(name='Sachbearbeiter')[0])
        Mitgliedschaft.objects.create(benutzer=cls.t, organisation=cls.a.organisation, rolle='Sachbearbeiter')
        Mitgliedschaft.objects.create(benutzer=cls.t, organisation=cls.b.organisation, rolle='Inhaber')
        # Ein Konto, das nur zu A gehört.
        cls.m = User.objects.create_user(username='nur_a', password='nur-a-passwort', email='m@example.ch')
        cls.m.groups.add(Group.objects.get_or_create(name='Sachbearbeiter')[0])
        Mitgliedschaft.objects.create(benutzer=cls.m, organisation=cls.a.organisation, rolle='Sachbearbeiter')

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.a.benutzer)             # Inhaber von A

    def bearbeiten(self, ziel, **felder):
        daten = {'rolle': 'Sachbearbeiter', **felder}
        return self.c.post(f'/neu/benutzer/{ziel.pk}/bearbeiten/', daten)

    def rolle(self, benutzer, fx):
        return Mitgliedschaft.alle_organisationen.get(benutzer=benutzer, organisation=fx.organisation).rolle

    def gruppen(self, benutzer):
        return sorted(benutzer.groups.values_list('name', flat=True))


class GemeinsamesKontoTests(GeteilteKontenBasis):

    def test_passwort_eines_gemeinsamen_kontos_bleibt(self):
        self.bearbeiten(self.t, passwort='uebernommen-123', first_name='Tina', last_name='Treu',
                        email='treu@example.ch')
        self.t.refresh_from_db()
        self.assertTrue(self.t.check_password('ihr-eigenes-passwort'),
                        'Der Inhaber von A hat das Passwort der Treuhänderin überschrieben.')
        self.assertFalse(self.t.check_password('uebernommen-123'))

    def test_email_und_name_eines_gemeinsamen_kontos_bleiben(self):
        self.bearbeiten(self.t, email='angreifer@example.org', first_name='X', last_name='Y',
                        passwort='')
        self.t.refresh_from_db()
        self.assertEqual((self.t.email, self.t.first_name, self.t.last_name),
                         ('treu@example.ch', 'Tina', 'Treu'))

    def test_aktiv_flag_eines_gemeinsamen_kontos_bleibt(self):
        """Ohne Häkchen «Konto aktiv» hiess bisher: global deaktivieren."""
        self.bearbeiten(self.t)                          # kein `is_active` im Formular
        self.t.refresh_from_db()
        self.assertTrue(self.t.is_active, 'Das gemeinsame Konto wurde für beide Verwaltungen deaktiviert.')

    def test_globale_gruppe_eines_gemeinsamen_kontos_bleibt(self):
        self.bearbeiten(self.t, rolle='Lesezugriff')
        self.assertEqual(self.gruppen(self.t), ['Sachbearbeiter'],
                         'Die globale Gruppe des gemeinsamen Kontos wurde überschrieben.')

    def test_die_rolle_in_der_eigenen_verwaltung_ist_aenderbar(self):
        """Gegenprobe: Der Inhaber von A darf, was ihm gehört — sonst wäre alles abgelehnt."""
        antwort = self.bearbeiten(self.t, rolle='Verwalter')
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(self.rolle(self.t, self.a), 'Verwalter')

    def test_die_rolle_bei_der_anderen_verwaltung_bleibt(self):
        self.bearbeiten(self.t, rolle='Lesezugriff')
        self.assertEqual(self.rolle(self.t, self.b), 'Inhaber',
                         'Die Inhaber-Rolle der Treuhänderin bei B wurde verändert.')

    def test_der_versuch_wird_gemeldet(self):
        antwort = self.c.post(f'/neu/benutzer/{self.t.pk}/bearbeiten/',
                              {'rolle': 'Sachbearbeiter', 'passwort': 'neu-123456'}, follow=True)
        texte = ' '.join(str(m) for m in antwort.context['messages'])
        self.assertIn('anderen Verwaltung', texte)

    def test_mitgliedschaft_beenden_statt_deaktivieren(self):
        antwort = self.bearbeiten(self.t, mitgliedschaft_beenden='on')
        self.assertEqual(antwort.status_code, 302)
        self.assertFalse(Mitgliedschaft.alle_organisationen.filter(
            benutzer=self.t, organisation=self.a.organisation).exists())
        self.assertTrue(Mitgliedschaft.alle_organisationen.filter(
            benutzer=self.t, organisation=self.b.organisation, rolle='Inhaber').exists(),
            'Die Mitgliedschaft bei B ging mit verloren.')
        self.t.refresh_from_db()
        self.assertTrue(self.t.is_active)
        self.assertTrue(User.objects.filter(pk=self.t.pk).exists())

    def test_das_formular_zeigt_die_einschraenkung(self):
        html = self.c.get(f'/neu/benutzer/{self.t.pk}/bearbeiten/').content.decode()
        self.assertIn('auch in einer anderen Verwaltung genutzt', html)
        self.assertIn('name="mitgliedschaft_beenden"', html)
        self.assertNotIn('name="is_active"', html)
        # und die Rolle in A steht im Formular, nicht die der globalen Gruppe
        self.assertIn('value="Sachbearbeiter" selected', html)

    def test_die_benutzerliste_zeigt_die_rolle_in_der_eigenen_verwaltung(self):
        """Die Gruppe ist global, die Rolle gehört der Mitgliedschaft.

        Bei einem gemeinsamen Konto stand in der Liste von A sonst die Rolle der
        globalen Gruppe — hier gegen die Mitgliedschaft in A gemessen.
        """
        import re
        self.t.groups.set([Group.objects.get_or_create(name='Inhaber')[0]])
        html = self.c.get('/neu/benutzer/').content.decode()
        zeile = re.search(r'treuhaenderin.*?</tr>', html, re.S).group(0)
        self.assertIn('Sachbearbeiter', zeile)
        self.assertNotIn('Inhaber', zeile)

    def test_das_formular_eines_eigenen_kontos_bleibt_wie_es_war(self):
        html = self.c.get(f'/neu/benutzer/{self.m.pk}/bearbeiten/').content.decode()
        self.assertIn('name="is_active"', html)
        self.assertNotIn('mitgliedschaft_beenden', html)

    def test_ein_superuser_konto_ist_nicht_ueberschreibbar(self):
        """Das Konto des Betreibers gehört keiner Verwaltung."""
        su = User.objects.create_superuser(username='betreiber', password='geheim-betreiber', email='b@x.ch')
        Mitgliedschaft.objects.create(benutzer=su, organisation=self.a.organisation, rolle='Inhaber')
        self.bearbeiten(su, passwort='uebernommen-123', rolle='Inhaber')
        su.refresh_from_db()
        self.assertTrue(su.check_password('geheim-betreiber'))
        self.assertTrue(su.is_superuser)

    def test_das_eigene_konto_darf_der_inhaber_aendern(self):
        """Auch ein gemeinsames Konto: Wer eingeloggt ist, ändert sein eigenes Passwort."""
        Mitgliedschaft.objects.create(benutzer=self.a.benutzer, organisation=self.b.organisation,
                                      rolle='Lesezugriff')
        antwort = self.c.post(f'/neu/benutzer/{self.a.benutzer.pk}/bearbeiten/',
                              {'rolle': 'Inhaber', 'passwort': 'neu-eigenes-pw',
                                'first_name': 'A', 'last_name': 'Chef', 'email': 'chef@example.ch'})
        self.assertEqual(antwort.status_code, 302)
        self.a.benutzer.refresh_from_db()
        self.assertTrue(self.a.benutzer.check_password('neu-eigenes-pw'))
        self.assertEqual(self.a.benutzer.email, 'chef@example.ch')
        self.assertTrue(self.a.benutzer.is_active, 'Das eigene Konto lässt sich nicht deaktivieren.')


class EigenesKontoBleibtVollAenderbarTests(GeteilteKontenBasis):
    """Regression: Wo das Konto nur uns gehört, bleibt alles wie vorher."""

    def test_passwort_email_aktiv_und_gruppe_sind_aenderbar(self):
        self.bearbeiten(self.m, passwort='neues-passwort-1', email='neu@example.ch',
                        first_name='Max', last_name='Muster', rolle='Verwalter')
        self.m.refresh_from_db()
        self.assertTrue(self.m.check_password('neues-passwort-1'))
        self.assertEqual(self.m.email, 'neu@example.ch')
        self.assertFalse(self.m.is_active, 'Ohne Häkchen wird ein eigenes Konto weiterhin deaktiviert.')
        self.assertEqual(self.gruppen(self.m), ['Verwalter'])
        self.assertEqual(self.rolle(self.m, self.a), 'Verwalter')

    def test_ein_konto_das_nur_noch_uns_gehoert_ist_voll_aenderbar(self):
        """Verlässt die Treuhänderin B, gehört das Konto wieder allein A."""
        Mitgliedschaft.alle_organisationen.filter(benutzer=self.t, organisation=self.b.organisation).delete()
        self.bearbeiten(self.t, passwort='neues-passwort-2', is_active='on')
        self.t.refresh_from_db()
        self.assertTrue(self.t.check_password('neues-passwort-2'))

    def test_entfernen_eines_gemeinsamen_kontos_loescht_es_nicht(self):
        antwort = self.c.post(f'/neu/benutzer/{self.t.pk}/loeschen/')
        self.assertEqual(antwort.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.t.pk).exists())
        self.assertTrue(Mitgliedschaft.alle_organisationen.filter(
            benutzer=self.t, organisation=self.b.organisation).exists())

    def test_entfernen_eines_eigenen_kontos_loescht_es(self):
        self.c.post(f'/neu/benutzer/{self.m.pk}/loeschen/')
        self.assertFalse(User.objects.filter(pk=self.m.pk).exists())
