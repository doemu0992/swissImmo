"""Schadensliste nach G9 — Befunde je Meldung, Sichten, Sortierung.

DER BESTAND AM 21.08.2026 (Bildschirmfoto)

Drei Kacheln uebereinander, jede einen halben Bildschirm hoch, jede mit einer
Null. «0 Offen», «0 In Bearbeitung», «0 Total angezeigt». Danach sieben
Filterchips ueber drei Zeilen und ein zweites Suchfeld. Die Arbeit begann
ausserhalb des Bildschirms.

`EchoTests` und `ProtokollWortlautTests` sind der wichtigste Teil dieser
Datei. Der Befund «Melder ohne Rueckmeldung» misst die Zusage aus dem
Untertitel — «Meldung → Auftrag → automatische Info an Melder» — und ein
falsches Mass bringt ihn zum SCHWEIGEN, statt ihn zu laut zu machen. Das
faellt niemandem auf.
"""
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.schaeden import (LIEGT_TAGE, OHNE_AUFTRAG_TAGE, hat_echo,
                             streifen, zeilen)

HEUTE = timezone.localdate()


class _Basis(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _meldung(self, titel='Wasserhahn tropft', tage_alt=0, **felder):
        """Eine Meldung mit steuerbarem Alter.

        `erstellt_am` ist `auto_now_add` — es laesst sich nur per `update`
        setzen, nicht beim Anlegen. Wer das uebersieht, testet lauter
        taggleiche Meldungen und wundert sich, dass kein Befund erscheint.
        """
        from tickets.models import SchadenMeldung
        werte = {'liegenschaft': self.a.liegenschaft, 'titel': titel,
                 'beschreibung': 'Testmeldung', 'gelesen': True}
        werte.update(felder)
        t = SchadenMeldung.objects.create(**werte)
        if tage_alt:
            wann = timezone.now() - timedelta(days=tage_alt)
            SchadenMeldung.objects.filter(id=t.id).update(
                erstellt_am=wann, aktualisiert_am=wann)
            t.refresh_from_db()
        return t

    def _nachricht(self, t, typ='chat', text='Notiz', intern=False, verwaltung=False):
        from tickets.models import TicketNachricht
        return TicketNachricht.objects.create(
            ticket=t, absender_name='X', typ=typ, nachricht=text,
            is_intern=intern, is_von_verwaltung=verwaltung)

    def _auftrag(self, t, freigabe='nicht_noetig', tage_alt=0):
        from tickets.models import HandwerkerAuftrag
        a = HandwerkerAuftrag.objects.create(
            ticket=t, handwerker=self.a.handwerker, freigabe_status=freigabe)
        if tage_alt:
            HandwerkerAuftrag.objects.filter(id=a.id).update(
                beauftragt_am=timezone.now() - timedelta(days=tage_alt))
            a.refresh_from_db()
        return a

    def _texte(self, t):
        from tickets.models import SchadenMeldung
        frisch = (SchadenMeldung.objects.filter(id=t.id)
                  .prefetch_related('handwerker_auftraege', 'nachrichten'))
        return [b['text'] for b in zeilen(frisch)[0]['befunde']]


class BefundTests(_Basis):

    def test_eine_frische_gelesene_meldung_mit_auftrag_meldet_nichts(self):
        """Die wichtigste Gegenprobe — sonst stuende an jeder Zeile etwas."""
        with mandant(self.a.organisation):
            t = self._meldung(gelesen=True)
            self._auftrag(t)
            self.assertEqual(self._texte(t), [])

    def test_ungelesen_ab_einem_tag(self):
        with mandant(self.a.organisation):
            t = self._meldung(gelesen=False, tage_alt=1)
            self.assertIn('Ungelesen', self._texte(t))

    def test_heute_eingegangen_und_ungelesen_ist_kein_befund(self):
        """Ein Arbeitstag Kulanz — sonst meldet die Liste jeden Posteingang."""
        with mandant(self.a.organisation):
            t = self._meldung(gelesen=False)
            self.assertNotIn('Ungelesen', self._texte(t))

    def test_lange_ungelesen_wiegt_schwerer(self):
        from tickets.models import SchadenMeldung
        with mandant(self.a.organisation):
            t = self._meldung(gelesen=False, tage_alt=5)
            frisch = SchadenMeldung.objects.filter(id=t.id).prefetch_related(
                'handwerker_auftraege', 'nachrichten')
            befund = next(b for b in zeilen(frisch)[0]['befunde']
                          if b['text'] == 'Ungelesen')
        self.assertEqual(befund['stufe'], 'crit')

    def test_kein_auftrag_nach_drei_tagen(self):
        with mandant(self.a.organisation):
            t = self._meldung(tage_alt=OHNE_AUFTRAG_TAGE)
            self.assertIn('Kein Auftrag', self._texte(t))

    def test_mit_auftrag_kein_befund(self):
        """Gegenprobe: Wer beauftragt hat, wird nicht dafuer geruegt."""
        with mandant(self.a.organisation):
            t = self._meldung(tage_alt=10)
            self._auftrag(t)
            self.assertNotIn('Kein Auftrag', self._texte(t))

    def test_freigabe_ausstehend_wird_gemeldet(self):
        with mandant(self.a.organisation):
            t = self._meldung(tage_alt=2)
            self._auftrag(t, freigabe='ausstehend', tage_alt=2)
            self.assertIn('Freigabe ausstehend', self._texte(t))

    def test_wer_auf_freigabe_wartet_hat_seine_arbeit_getan(self):
        """«Kein Auftrag» waere dort eine falsche Anklage — es GIBT einen."""
        with mandant(self.a.organisation):
            t = self._meldung(tage_alt=10)
            self._auftrag(t, freigabe='ausstehend', tage_alt=10)
            texte = self._texte(t)
        self.assertIn('Freigabe ausstehend', texte)
        self.assertNotIn('Kein Auftrag', texte)

    def test_freigegebene_auftraege_melden_nichts(self):
        with mandant(self.a.organisation):
            t = self._meldung(tage_alt=10)
            self._auftrag(t, freigabe='freigegeben', tage_alt=10)
            self.assertNotIn('Freigabe ausstehend', self._texte(t))

    def test_liegenbleiber_beim_handwerker(self):
        from tickets.models import SchadenMeldung
        with mandant(self.a.organisation):
            t = self._meldung(tage_alt=LIEGT_TAGE + 5, status='warte_auf_handwerker')
            self._auftrag(t)
            SchadenMeldung.objects.filter(id=t.id).update(
                aktualisiert_am=timezone.now() - timedelta(days=LIEGT_TAGE + 5))
            self.assertIn('Liegt beim Handwerker', self._texte(t))

    def test_frisches_warten_ist_kein_befund(self):
        """Gegenprobe — sonst waere jeder Wartezustand sofort ein Vorwurf."""
        with mandant(self.a.organisation):
            t = self._meldung(tage_alt=2, status='warte_auf_mieter')
            self._auftrag(t)
            self.assertNotIn('Liegt beim Mieter', self._texte(t))

    def test_erledigte_meldung_schweigt(self):
        """Ein abgeschlossener Fall ohne erfasste Kosten mag buchhalterisch
        unschoen sein — auf der Arbeitsflaeche ist er trotzdem erledigt."""
        with mandant(self.a.organisation):
            t = self._meldung(tage_alt=200, gelesen=False, status='erledigt',
                              email_melder='m@example.ch')
            self.assertEqual(self._texte(t), [])

    def test_hohe_prioritaet_allein_ist_kein_befund(self):
        """Ein Notfall, der heute gemeldet und heute beauftragt wurde, laeuft
        korrekt. Die Prioritaet hebt ihn in der Sortierung, nicht in der
        Anklage."""
        with mandant(self.a.organisation):
            t = self._meldung(prioritaet='hoch')
            self._auftrag(t)
            self.assertEqual(self._texte(t), [])


class EchoTests(_Basis):
    """«Melder ohne Rueckmeldung» — die Zusage aus dem Untertitel.

    Ein falsches Mass bringt diesen Befund zum SCHWEIGEN statt ihn zu laut zu
    machen, und das faellt niemandem auf. Deshalb hat jede Nachrichtenart hier
    einen eigenen Fall.
    """

    def _ohne_echo(self, **felder):
        werte = {'tage_alt': 5, 'email_melder': 'mieter@example.ch'}
        werte.update(felder)
        t = self._meldung(**werte)
        self._auftrag(t)
        return t

    def test_ohne_jede_nachricht_wird_gemeldet(self):
        with mandant(self.a.organisation):
            t = self._ohne_echo()
            self.assertIn('Melder ohne Rückmeldung', self._texte(t))

    def test_eine_echte_antwort_zaehlt(self):
        with mandant(self.a.organisation):
            t = self._ohne_echo()
            self._nachricht(t, typ='antwort_senden', text='Wir kümmern uns.',
                            verwaltung=True)
            self.assertNotIn('Melder ohne Rückmeldung', self._texte(t))

    def test_eine_interne_notiz_zaehlt_nicht_als_rueckmeldung(self):
        """Eine Chatnotiz im Team erreicht den Mieter nicht."""
        with mandant(self.a.organisation):
            t = self._ohne_echo()
            self._nachricht(t, typ='chat', text='Handwerker angerufen', intern=True)
            self.assertIn('Melder ohne Rückmeldung', self._texte(t))

    def test_die_auftragsnotiz_zaehlt_nicht(self):
        """«Auftrag an X vergeben» ist intern — und entsteht bei JEDER
        Beauftragung.

        Wuerde sie zaehlen, schwiege der Befund praktisch immer, sobald ein
        Handwerker im Spiel ist. Genau das tat der erste Entwurf, der auf
        `typ='system'` prueft.
        """
        with mandant(self.a.organisation):
            t = self._ohne_echo()
            self._nachricht(t, typ='system', text='Auftrag an Sanitär AG vergeben.',
                            intern=True)
            self.assertIn('Melder ohne Rückmeldung', self._texte(t))

    def test_die_statusnotiz_zaehlt_nicht(self):
        with mandant(self.a.organisation):
            t = self._ohne_echo()
            self._nachricht(t, typ='system', text='Status geändert: In Bearbeitung.',
                            intern=True)
            self.assertIn('Melder ohne Rückmeldung', self._texte(t))

    def test_eine_eingehende_mieterantwort_zaehlt_nicht(self):
        """`mail_antwort` entsteht, wenn der MIETER schreibt.

        Als Echo gewertet schwiege der Befund ausgerechnet dann, wenn jemand
        geschrieben hat und niemand geantwortet — der Fall, fuer den es ihn
        gibt. Der erste Entwurf zaehlte ihn mit.
        """
        with mandant(self.a.organisation):
            t = self._ohne_echo()
            self._nachricht(t, typ='mail_antwort', text='Wann kommt jemand?')
            self.assertIn('Melder ohne Rückmeldung', self._texte(t))

    def test_die_protokollierte_versandnotiz_zaehlt(self):
        """Diese Notiz entsteht NUR nach erfolgreichem Mailversand."""
        with mandant(self.a.organisation):
            t = self._ohne_echo()
            self._nachricht(t, typ='system', intern=True,
                            text='Melder automatisch informiert (mieter@example.ch).')
            self.assertNotIn('Melder ohne Rückmeldung', self._texte(t))

    def test_ohne_kontaktweg_wird_nicht_geruegt(self):
        """Ohne E-Mail und ohne Mieterbezug laesst sich nichts senden. Das
        Schweigen ist dann eine Tatsache, keine Versaeumnis."""
        with mandant(self.a.organisation):
            t = self._meldung(tage_alt=5)
            self._auftrag(t)
            self.assertNotIn('Melder ohne Rückmeldung', self._texte(t))

    def test_frische_meldung_bekommt_zeit(self):
        with mandant(self.a.organisation):
            t = self._ohne_echo(tage_alt=1)
            self.assertNotIn('Melder ohne Rückmeldung', self._texte(t))

    def test_hat_echo_ist_einzeln_pruefbar(self):
        with mandant(self.a.organisation):
            t = self._ohne_echo()
            self.assertFalse(hat_echo(t))
            self._nachricht(t, typ='antwort_senden', text='Antwort', verwaltung=True)
            t.refresh_from_db()
            self.assertTrue(hat_echo(t))


class ProtokollWortlautTests(TestCase):
    """Der Textabgleich in `ECHO_PROTOKOLL_PRAEFIX` ist zerbrechlich.

    Er ist die einzige Stelle, an der dieser Befund eine Formulierung aus dem
    Produktivcode kennt. Diese Pruefung haelt beide Erzeugerstellen fest:
    Aendert jemand den Wortlaut, wird sie rot — statt dass der Befund
    stillschweigend zu oft meldet.
    """

    def test_beide_erzeugerstellen_beginnen_mit_dem_praefix(self):
        import pathlib
        import re

        from django.conf import settings

        from faelle.schaeden import ECHO_PROTOKOLL_PRAEFIX

        quelle = (pathlib.Path(settings.BASE_DIR)
                  / 'core/views/fw/schaeden.py').read_text()
        treffer = re.findall(r'nachricht=f?"(Melder[^"]*)"', quelle)
        self.assertGreaterEqual(len(treffer), 2, quelle.count('Melder'))
        for text in treffer:
            with self.subTest(text=text):
                self.assertTrue(text.startswith(ECHO_PROTOKOLL_PRAEFIX), text)

    def test_die_pruefung_wuerde_eine_umformulierung_bemerken(self):
        """Gegenprobe zur Gegenprobe: Der Abgleich darf nicht leerlaufen."""
        from faelle.schaeden import ECHO_PROTOKOLL_PRAEFIX
        self.assertFalse('Mieter informiert'.startswith(ECHO_PROTOKOLL_PRAEFIX))
        self.assertTrue('Melder automatisch informiert (a@b.ch).'
                        .startswith(ECHO_PROTOKOLL_PRAEFIX))


class SortierungTests(_Basis):

    def test_der_befund_schlaegt_das_alter(self):
        """Die AELTERE Meldung ist hier die unauffaellige.

        Ohne diesen Aufbau taeuscht der Test: In einem naheliegenden Szenario
        ist die Meldung mit Befund zugleich die aeltere, und reine
        Alterssortierung liefert dieselbe Reihenfolge — der Test waere gruen,
        ohne die Sortierregel zu pruefen.
        """
        from tickets.models import SchadenMeldung
        with mandant(self.a.organisation):
            alt_ruhig = self._meldung('Alt und erledigt beauftragt', tage_alt=40)
            self._auftrag(alt_ruhig)
            jung_laut = self._meldung('Jung ohne Auftrag', tage_alt=OHNE_AUFTRAG_TAGE)
            reihe = zeilen(SchadenMeldung.objects.filter(
                id__in=[alt_ruhig.id, jung_laut.id]).prefetch_related(
                'handwerker_auftraege', 'nachrichten'))
        self.assertEqual(reihe[0]['t'].id, jung_laut.id)
        self.assertEqual(reihe[1]['t'].id, alt_ruhig.id)

    def test_bei_gleichem_befund_zaehlt_die_prioritaet(self):
        from tickets.models import SchadenMeldung
        with mandant(self.a.organisation):
            tief = self._meldung('Tief', tage_alt=10, prioritaet='tief')
            hoch = self._meldung('Hoch', tage_alt=10, prioritaet='hoch')
            reihe = zeilen(SchadenMeldung.objects.filter(
                id__in=[tief.id, hoch.id]).prefetch_related(
                'handwerker_auftraege', 'nachrichten'))
        self.assertEqual(reihe[0]['t'].id, hoch.id)

    def test_bei_gleichem_befund_und_prioritaet_die_aeltere(self):
        from tickets.models import SchadenMeldung
        with mandant(self.a.organisation):
            jung = self._meldung('Jung', tage_alt=5)
            alt = self._meldung('Alt', tage_alt=50)
            reihe = zeilen(SchadenMeldung.objects.filter(
                id__in=[jung.id, alt.id]).prefetch_related(
                'handwerker_auftraege', 'nachrichten'))
        self.assertEqual(reihe[0]['t'].id, alt.id)


class StreifenTests(_Basis):

    def test_die_vier_zahlen(self):
        from tickets.models import SchadenMeldung
        with mandant(self.a.organisation):
            self._meldung('Offen ungelesen', tage_alt=4, gelesen=False)
            self._meldung('Erledigt', status='erledigt')
            k = streifen(zeilen(SchadenMeldung.objects.exclude(id=self.a.schaden.id)
                                .prefetch_related('handwerker_auftraege', 'nachrichten')))
        self.assertEqual(k['offen'], 1)
        self.assertEqual(k['ungelesen'], 1)
        self.assertEqual(k['aeltester'], 4)
        self.assertEqual(k['ungelesen_stufe'], 'crit')

    def test_ohne_offene_meldung_keine_markierung(self):
        from tickets.models import SchadenMeldung
        with mandant(self.a.organisation):
            SchadenMeldung.objects.all().update(status='erledigt')
            k = streifen(zeilen(SchadenMeldung.objects.all().prefetch_related(
                'handwerker_auftraege', 'nachrichten')))
        self.assertEqual(k['offen'], 0)
        self.assertEqual(k['offen_stufe'], '')
        self.assertEqual(k['aeltester'], 0)

    def test_leerer_bestand_wirft_nicht(self):
        self.assertEqual(streifen([])['offen'], 0)


class SeitenTests(_Basis):

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def test_der_befund_erreicht_die_seite(self):
        with mandant(self.a.organisation):
            self._meldung('Vergessene Meldung', tage_alt=10)
            html = self.c.get('/neu/schaeden/').content.decode()
        self.assertIn('Vergessene Meldung', html)
        self.assertIn('Kein Auftrag', html)

    def test_der_kennzahlenstreifen_hat_kein_total_angezeigt_mehr(self):
        """Es zaehlte, was der eigene Filter uebriggelassen hat."""
        with mandant(self.a.organisation):
            html = self.c.get('/neu/schaeden/').content.decode()
        self.assertIn('class="fw-lage"', html)
        self.assertIn('Älteste offen', html)
        self.assertNotIn('Total angezeigt', html)

    def test_es_gibt_kein_zweites_suchfeld_mehr(self):
        with mandant(self.a.organisation):
            html = self.c.get('/neu/schaeden/').content.decode()
        self.assertNotIn('Titel, Kategorie, Objekt…', html)

    def test_die_sicht_reduziert(self):
        with mandant(self.a.organisation):
            self._meldung('Mit Befund', tage_alt=10)
            self._meldung('Ohne Befund frisch')
            html = self.c.get('/neu/schaeden/?sicht=befund').content.decode()
        self.assertIn('Mit Befund', html)
        self.assertNotIn('Ohne Befund frisch', html)

    def test_der_kopf_zeigt_trotz_sicht_den_ganzen_bestand(self):
        """Sonst stuende unter «Mit Befund» immer die Zahl der sichtbaren
        Zeilen, und der Streifen waere wertlos."""
        with mandant(self.a.organisation):
            self._meldung('Ruhig', gelesen=True)
            self._auftrag(self._meldung('Ruhig 2', gelesen=True))
            antwort = self.c.get('/neu/schaeden/?sicht=befund')
        self.assertGreater(antwort.context['kopf']['offen'],
                           len(antwort.context['rows']))

    def test_der_status_feinfilter_bleibt_erreichbar(self):
        """Gespeicherte Adressen aus der Vorfassung duerfen nicht brechen."""
        with mandant(self.a.organisation):
            self._meldung('Wartet', status='warte_auf_mieter')
            antwort = self.c.get('/neu/schaeden/?status=warte_auf_mieter')
        self.assertEqual(antwort.status_code, 200)
        self.assertIn('Wartet', antwort.content.decode())

    def test_eine_unbekannte_sicht_zeigt_alles(self):
        with mandant(self.a.organisation):
            antwort = self.c.get('/neu/schaeden/?sicht=unfug')
        self.assertEqual(antwort.context['sicht'], '')
        self.assertFalse(antwort.context['gefiltert'])

    def test_leerzustand_fuehrt_weiter(self):
        with mandant(self.a.organisation):
            from tickets.models import SchadenMeldung
            SchadenMeldung.objects.all().update(status='erledigt')
            html = self.c.get('/neu/schaeden/?sicht=befund').content.decode()
        self.assertIn('Nichts zu tun', html)


class ViewAbfragezahlTests(_Basis):
    """Geprueft wird die VIEW, nicht ein selbst gebautes Queryset.

    `_befunde` liest je Meldung die Auftraege UND die Nachrichten. Ohne
    `prefetch_related` in der View sind das zwei zusaetzliche Abfragen JE
    ZEILE — und ein Test, der sein Queryset selbst zusammenstellt und das
    Prefetch von Hand setzt, wuerde das nie bemerken.
    """

    def _abfragen(self, client):
        """Wie viele Abfragen ein Seitenaufruf kostet."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            client.get('/neu/schaeden/')
        return len(ctx.captured_queries)

    def test_mehr_meldungen_kosten_die_seite_nicht_mehr_abfragen(self):
        """Geprueft wird KONSTANZ, nicht eine feste Zahl.

        Eine feste Zahl braeche bei jeder unbeteiligten Aenderung an der Seite
        und saegte damit an ihrer eigenen Glaubwuerdigkeit. Die Aussage lautet
        «waechst nicht mit dem Bestand», und genau die wird gemessen.
        """
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            # AUFWAERMEN. Der erste Aufruf einer Testsitzung kostet vier
            # Abfragen mehr — Session und Berechtigungen werden aufgebaut.
            # Ohne diesen Lauf vergleicht die Pruefung kalt gegen warm und
            # meldet einen Rueckgang von 19 auf 15 Abfragen, obwohl sich am
            # Abfrageplan nichts geaendert hat. Genau so ist es beim ersten
            # Anlauf passiert.
            self._abfragen(c)
            erst = self._abfragen(c)
            for i in range(12):
                t = self._meldung(f'Messmeldung {i}', tage_alt=4)
                self._auftrag(t)
                self._nachricht(t, typ='chat', text='Notiz')
            spaeter = self._abfragen(c)
        self.assertEqual(spaeter, erst,
                         f'Die Seite skaliert mit dem Bestand: {erst} -> {spaeter}')


class TrennungTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_b_sieht_die_meldungen_von_a_nicht(self):
        c = Client()
        c.force_login(self.b.benutzer)
        with mandant(self.b.organisation):
            html = c.get('/neu/schaeden/').content.decode()
        self.assertNotIn(self.a.schaden.titel, html)
        self.assertIn(self.b.schaden.titel, html)

    def test_der_kopf_zaehlt_nur_den_eigenen_bestand(self):
        """Eine Zaehlung ueber die Mandantengrenze waere der leiseste Weg,
        fremde Daten zu verraten — man saehe die Meldungen nicht, wuesste aber,
        wie viele es sind."""
        c = Client()
        c.force_login(self.b.benutzer)
        with mandant(self.b.organisation):
            antwort = c.get('/neu/schaeden/')
            from tickets.models import SchadenMeldung
            eigene = SchadenMeldung.objects.count()
        self.assertEqual(antwort.context['kopf']['offen'], eigene)
        self.assertEqual(eigene, 1)
