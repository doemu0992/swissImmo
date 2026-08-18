"""Zwei-Faktor-Anmeldung — die Zusagen, an denen der Schutz hängt.

DIE EINE ZUSAGE, DIE ALLES TRÄGT

Ein zweiter Faktor, der **nach** `login()` abgefragt wird, ist kein zweiter
Faktor. Wer die Zwischenseite überspringt und eine Adresse direkt eintippt, ist
dann bereits angemeldet — das Formular wäre reine Höflichkeit.

`test_mit_richtigem_passwort_ist_man_noch_nicht_angemeldet` prüft genau das:
nach Name und Passwort, aber vor dem Code, muss eine geschützte Seite noch
abweisen. Fällt dieser Test, ist der ganze Umbau wertlos, auch wenn alles
andere grün bleibt.

Die Codes im Test kommen aus demselben Modul, das sie prüft — das ist hier
zulässig, weil `test_totp.py` dieses Modul zuvor gegen die **amtlichen
Testvektoren der RFC 6238** stellt. Ohne diese Verankerung würde sich der
Testsatz nur selbst bestätigen.
"""
from django.test import Client, TestCase
from django.urls import reverse

from core.models import SicherheitsEreignis, Wiederherstellungscode, ZweiterFaktor
from core.services import totp

from ._isolation import MandantenFixture


class ZweiFaktorBasis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def setUp(self):
        self.client = Client()
        self.benutzer = self.a.benutzer
        self.benutzer.set_password('geheim-123')
        self.benutzer.save()

    def faktor_aktivieren(self, benutzer=None):
        from django.utils import timezone
        benutzer = benutzer or self.benutzer
        return ZweiterFaktor.objects.create(
            benutzer=benutzer, geheimnis=totp.geheimnis_erzeugen(),
            bestaetigt_am=timezone.now())

    def passwort_schritt(self, passwort='geheim-123'):
        return self.client.post(reverse('login'),
                                {'username': self.benutzer.get_username(),
                                 'password': passwort})


class OhneFaktorTests(ZweiFaktorBasis):
    def test_ohne_faktor_meldet_das_passwort_direkt_an(self):
        # Der Bestand darf sich durch den Umbau nicht ändern: Wer keinen
        # zweiten Faktor eingerichtet hat, meldet sich an wie zuvor.
        self.passwort_schritt()
        self.assertIn('_auth_user_id', self.client.session)

    def test_falsches_passwort_meldet_nicht_an(self):
        antwort = self.passwort_schritt('falsch')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertContains(antwort, 'stimmt nicht')

    def test_die_meldung_verraet_nicht_welcher_teil_falsch_war(self):
        # Sonst liesse sich über die Fehlermeldung herausfinden, welche
        # Benutzernamen es gibt.
        antwort = self.client.post(reverse('login'),
                                   {'username': 'gibtesnicht', 'password': 'egal'})
        self.assertContains(antwort, 'Benutzername oder Passwort')


class DerEigentlicheSchutzTests(ZweiFaktorBasis):
    def test_mit_richtigem_passwort_ist_man_noch_nicht_angemeldet(self):
        """DIE zentrale Zusage — siehe Kopf dieser Datei."""
        self.faktor_aktivieren()
        antwort = self.passwort_schritt()

        self.assertNotIn('_auth_user_id', self.client.session,
                         'Der Benutzer ist nach dem Passwort bereits angemeldet — '
                         'der zweite Faktor wäre dann nur noch eine Nachfrage.')
        self.assertRedirects(antwort, reverse('zweifaktor_bestaetigen'))

    def test_geschuetzte_seite_bleibt_zwischen_den_schritten_zu(self):
        # Die Gegenprobe zum Test oben: Nicht nur der Sitzungsschlüssel fehlt,
        # es kommt auch tatsächlich niemand durch.
        self.faktor_aktivieren()
        self.passwort_schritt()
        antwort = self.client.get('/neu/', follow=False)
        self.assertIn(antwort.status_code, (301, 302))
        self.assertIn('login', antwort['Location'])

    def test_mit_richtigem_code_ist_man_drin(self):
        faktor = self.faktor_aktivieren()
        self.passwort_schritt()
        self.client.post(reverse('zweifaktor_bestaetigen'),
                         {'code': totp.code(faktor.geheimnis)})
        self.assertIn('_auth_user_id', self.client.session)

    def test_falscher_code_meldet_nicht_an(self):
        self.faktor_aktivieren()
        self.passwort_schritt()
        self.client.post(reverse('zweifaktor_bestaetigen'), {'code': '000000'})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_ohne_passwortschritt_ist_die_codeseite_wirkungslos(self):
        # Wer die Zwischenseite direkt aufruft, ohne das Passwort bestanden zu
        # haben, darf dort nichts erreichen — auch nicht mit einem gültigen Code.
        faktor = self.faktor_aktivieren()
        antwort = self.client.post(reverse('zweifaktor_bestaetigen'),
                                   {'code': totp.code(faktor.geheimnis)})
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertRedirects(antwort, reverse('login'))


class WiedergabeschutzTests(ZweiFaktorBasis):
    def test_derselbe_code_gilt_kein_zweites_mal(self):
        """Ein Code lebt bis zu 90 Sekunden — das reicht für einen Mitleser."""
        faktor = self.faktor_aktivieren()
        code = totp.code(faktor.geheimnis)

        self.passwort_schritt()
        self.client.post(reverse('zweifaktor_bestaetigen'), {'code': code})
        self.assertIn('_auth_user_id', self.client.session)

        zweiter = Client()
        zweiter.post(reverse('login'), {'username': self.benutzer.get_username(),
                                        'password': 'geheim-123'})
        zweiter.post(reverse('zweifaktor_bestaetigen'), {'code': code})
        self.assertNotIn('_auth_user_id', zweiter.session,
                         'Ein bereits verbrauchter Code hat ein zweites Mal gegolten.')

    def test_gegenprobe_ein_frischer_code_gilt_danach_wieder(self):
        # Ohne diese Gegenprobe wäre nicht belegt, dass der Wiedergabeschutz
        # nur den verbrauchten Code sperrt und nicht einfach alles.
        import time

        faktor = self.faktor_aktivieren()
        spaeter = time.time() + 2 * totp.SCHRITT
        faktor.letztes_fenster = totp.zaehler_fuer()
        faktor.save(update_fields=['letztes_fenster'])

        self.assertTrue(faktor.pruefen(totp.code(faktor.geheimnis, spaeter), spaeter))


class VersucheTests(ZweiFaktorBasis):
    def test_nach_fuenf_fehlversuchen_ist_der_vorgang_verbraucht(self):
        # Sechs Stellen sind eine Million Möglichkeiten — für ein Skript kein
        # Hindernis, wenn es unbegrenzt raten darf.
        faktor = self.faktor_aktivieren()
        self.passwort_schritt()
        for _ in range(5):
            self.client.post(reverse('zweifaktor_bestaetigen'), {'code': '000000'})

        antwort = self.client.post(reverse('zweifaktor_bestaetigen'),
                                   {'code': totp.code(faktor.geheimnis)})
        self.assertNotIn('_auth_user_id', self.client.session,
                         'Nach dem Deckel ging ein richtiger Code trotzdem durch.')
        self.assertRedirects(antwort, reverse('login'))

    def test_die_wartefrist_laeuft_ab(self):
        from core.views.zweifaktor import WARTEFRIST

        faktor = self.faktor_aktivieren()
        self.passwort_schritt()
        sitzung = self.client.session
        sitzung['zf_seit'] = sitzung['zf_seit'] - WARTEFRIST - 1
        sitzung.save()

        antwort = self.client.post(reverse('zweifaktor_bestaetigen'),
                                   {'code': totp.code(faktor.geheimnis)})
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertRedirects(antwort, reverse('login'))

    def test_fehlversuche_stehen_im_betreiberlog(self):
        self.faktor_aktivieren()
        vorher = SicherheitsEreignis.objects.count()
        self.passwort_schritt()
        self.client.post(reverse('zweifaktor_bestaetigen'), {'code': '000000'})
        self.assertGreater(SicherheitsEreignis.objects.count(), vorher)


class NotfallcodeTests(ZweiFaktorBasis):
    def codes_erzeugen(self):
        from core.views.zweifaktor import _neue_codes
        return _neue_codes(self.benutzer)

    def test_notfallcode_meldet_an(self):
        self.faktor_aktivieren()
        codes = self.codes_erzeugen()
        self.passwort_schritt()
        self.client.post(reverse('zweifaktor_bestaetigen'), {'code': codes[0]})
        self.assertIn('_auth_user_id', self.client.session)

    def test_notfallcode_gilt_nur_einmal(self):
        self.faktor_aktivieren()
        codes = self.codes_erzeugen()
        self.passwort_schritt()
        self.client.post(reverse('zweifaktor_bestaetigen'), {'code': codes[0]})

        zweiter = Client()
        zweiter.post(reverse('login'), {'username': self.benutzer.get_username(),
                                        'password': 'geheim-123'})
        zweiter.post(reverse('zweifaktor_bestaetigen'), {'code': codes[0]})
        self.assertNotIn('_auth_user_id', zweiter.session)

    def test_codes_stehen_nur_als_hash_in_der_datenbank(self):
        # Ein Datenbankauszug darf die Codes nicht preisgeben.
        self.faktor_aktivieren()
        codes = self.codes_erzeugen()
        roh = codes[0].replace('-', '')
        for eintrag in Wiederherstellungscode.objects.all():
            self.assertNotIn(roh, eintrag.code_hash)
            self.assertNotIn(codes[0], eintrag.code_hash)

    def test_fremder_notfallcode_gilt_nicht(self):
        from benutzer.models import Benutzer
        from core.views.zweifaktor import _neue_codes

        self.faktor_aktivieren()
        self.codes_erzeugen()
        anderer = Benutzer.objects.create_user(username='fremd', password='x')
        fremde_codes = _neue_codes(anderer)

        self.passwort_schritt()
        self.client.post(reverse('zweifaktor_bestaetigen'), {'code': fremde_codes[0]})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_neue_codes_entwerten_die_alten(self):
        self.faktor_aktivieren()
        alte = self.codes_erzeugen()
        self.codes_erzeugen()
        self.passwort_schritt()
        self.client.post(reverse('zweifaktor_bestaetigen'), {'code': alte[0]})
        self.assertNotIn('_auth_user_id', self.client.session)


class EinrichtungTests(ZweiFaktorBasis):
    def test_unbestaetigter_faktor_sperrt_nicht_aus(self):
        """Zwischen «QR angezeigt» und «Code bestätigt» darf nichts greifen.

        Sonst sperrt sich aus, wer die Einrichtung abbricht oder den Code
        falsch abscannt — und niemand könnte ihn wieder hereinlassen.
        """
        ZweiterFaktor.objects.create(benutzer=self.benutzer,
                                     geheimnis=totp.geheimnis_erzeugen())
        self.passwort_schritt()
        self.assertIn('_auth_user_id', self.client.session)

    def test_einrichtung_zeigt_qr_und_schluessel(self):
        self.client.force_login(self.benutzer)
        antwort = self.client.get(reverse('zweifaktor_einrichten'))
        self.assertContains(antwort, '<svg')
        faktor = ZweiterFaktor.objects.get(benutzer=self.benutzer)
        self.assertContains(antwort, faktor.geheimnis)

    def test_richtiger_code_aktiviert_und_zeigt_notfallcodes(self):
        self.client.force_login(self.benutzer)
        self.client.get(reverse('zweifaktor_einrichten'))
        faktor = ZweiterFaktor.objects.get(benutzer=self.benutzer)

        antwort = self.client.post(reverse('zweifaktor_einrichten'),
                                   {'code': totp.code(faktor.geheimnis)})
        faktor.refresh_from_db()
        self.assertTrue(faktor.ist_aktiv)
        self.assertEqual(Wiederherstellungscode.objects.filter(
            benutzer=self.benutzer).count(), 10)
        self.assertContains(antwort, 'Notfallcodes')

    def test_abschalten_verlangt_das_passwort(self):
        # Ein kurz unbeaufsichtigter Bildschirm darf nicht genügen.
        self.faktor_aktivieren()
        self.client.force_login(self.benutzer)
        self.client.post(reverse('zweifaktor_aus'), {'password': 'falsch'})
        self.assertTrue(ZweiterFaktor.objects.filter(benutzer=self.benutzer).exists())

        self.client.post(reverse('zweifaktor_aus'), {'password': 'geheim-123'})
        self.assertFalse(ZweiterFaktor.objects.filter(benutzer=self.benutzer).exists())


class PflichtTests(ZweiFaktorBasis):
    def pflicht_setzen(self):
        org = self.a.organisation
        org.zweifaktor_pflicht = True
        org.save(update_fields=['zweifaktor_pflicht'])

    def test_ohne_pflicht_kommt_man_ohne_faktor_durch(self):
        self.client.force_login(self.benutzer)
        antwort = self.client.get('/neu/')
        self.assertNotIn('zwei-faktor', antwort.get('Location', ''))

    def test_mit_pflicht_wird_zur_einrichtung_umgeleitet(self):
        self.pflicht_setzen()
        self.client.force_login(self.benutzer)
        antwort = self.client.get('/neu/')
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort['Location'], reverse('zweifaktor_einrichten'))

    def test_die_einrichtungsseite_selbst_wird_nicht_umgeleitet(self):
        # Ohne diese Ausnahme dreht sich der Benutzer im Kreis.
        self.pflicht_setzen()
        self.client.force_login(self.benutzer)
        self.assertEqual(
            self.client.get(reverse('zweifaktor_einrichten')).status_code, 200)

    def test_abmelden_bleibt_unter_pflicht_erreichbar(self):
        self.pflicht_setzen()
        self.client.force_login(self.benutzer)
        antwort = self.client.get(reverse('logout'))
        self.assertNotEqual(antwort.get('Location', ''), reverse('zweifaktor_einrichten'))

    def test_mit_aktivem_faktor_greift_die_pflicht_nicht_mehr(self):
        self.pflicht_setzen()
        self.faktor_aktivieren()
        self.client.force_login(self.benutzer)
        antwort = self.client.get('/neu/')
        self.assertNotEqual(antwort.get('Location', ''), reverse('zweifaktor_einrichten'))

    def test_unter_pflicht_laesst_sich_der_faktor_nicht_abschalten(self):
        self.pflicht_setzen()
        self.faktor_aktivieren()
        self.client.force_login(self.benutzer)
        self.client.post(reverse('zweifaktor_aus'), {'password': 'geheim-123'})
        self.assertTrue(ZweiterFaktor.objects.filter(benutzer=self.benutzer).exists())


class ModellTests(ZweiFaktorBasis):
    def test_der_faktor_traegt_keinen_organisationsbezug(self):
        """Er hängt am Konto, nicht an der Verwaltung — bewusst.

        Ein Mensch kann in mehreren Verwaltungen Mitglied sein; sein Telefon
        ist trotzdem dasselbe. Ausserdem entsteht der Datensatz VOR dem
        Anmelden, also ohne jeden Mandantenkontext.
        """
        felder = {f.name for f in ZweiterFaktor._meta.get_fields()}
        self.assertNotIn('organisation', felder)
        self.assertNotIn('organisation',
                         {f.name for f in Wiederherstellungscode._meta.get_fields()})
