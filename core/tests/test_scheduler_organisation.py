"""Die Scheduler-Befehle laufen je Verwaltung — und laufen überhaupt.

WARUM DIESER TESTSATZ EXISTIERT

Etappe 6.2 hat den `TenantManager` an alle Modelle gehängt. Damit wirft jeder
Zugriff auf `Model.objects` ausserhalb einer Anfrage — richtig so, denn geraten
werden darf die Zugehörigkeit nicht. Nur: Acht der zehn Scheduler-Befehle
hatten keinen Kontext und brachen ab dem Moment ab, in dem 6.2 ausgeliefert
war. Darunter der Mietenlauf. Ein Befehl, der jeden Ersten des Monats die
Sollstellung macht und stattdessen mit einer Ausnahme endet, fällt genau dann
auf, wenn die Mieter keine Rechnung bekommen haben.

Sechs der acht Befehle rief kein Test je auf. Zwei aber schon —
`taeglicher_lauf` und `send_eigentuemer_reports` — und ihre Tests blieben
trotzdem grün. Der Grund steht in `_helfer.py:100`: `_test_organisation()` ruft
`setze_organisation(...)`, also läuft jeder Test mit dem klassischen Helfer mit
gesetztem Kontext. Genau die Bedingung, die im Scheduler nie gilt.

DARAUS FOLGT DIE REGEL FÜR DIESEN TESTSATZ: Er benutzt `MandantenFixture` und
setzt NIRGENDS einen Kontext. Nur so entspricht die Ausgangslage dem
Scheduled Task. Wer hier `_test_organisation()` einbaut, prüft wieder die
falsche Welt — und der Befehl kann erneut tot sein, ohne dass es auffällt.

Zwei Bestände, geprüft wird beides: dass der Lauf durchkommt und dass er den
fremden Bestand nicht anfasst.
"""
from io import StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from crm.models import Organisation

from ._isolation import MandantenFixture


class ZweiBestaende(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def laufen_lassen(self, befehl, **opts):
        """Startet den Befehl und gibt die Ausgabe zurück.

        Schlägt er fehl, ist der Fehler die Aussage des Tests — kein
        `assertRaises`, kein Fangen: Ein Scheduler-Befehl, der wirft, ist
        kaputt, und der Traceback sagt warum.
        """
        raus = StringIO()
        call_command(befehl, stdout=raus, stderr=raus, **opts)
        return raus.getvalue()


class BefehleLaufenUeberhauptTests(ZweiBestaende):
    """Der billigste Test, der die 6.2-Regression gefunden hätte."""

    def test_monatslauf(self):
        self.laufen_lassen('monatslauf', jahr=2026, monat=8)

    def test_mahnlauf(self):
        self.laufen_lassen('mahnlauf', kein_versand=True)

    def test_taeglicher_lauf(self):
        # Marktdaten nicht wirklich abholen — der Befehl fängt Netzfehler
        # ohnehin ab, aber ein Test soll nicht ins Internet greifen.
        with patch('core.utils.market_data.fetch_market_rates', return_value=({}, [])):
            self.laufen_lassen('taeglicher_lauf', digest_weekday=-1)

    def test_jahresabschluss_lauf(self):
        self.laufen_lassen('jahresabschluss_lauf', jahr=2025)

    def test_send_eigentuemer_reports(self):
        self.laufen_lassen('send_eigentuemer_reports', dry_run=True)

    def test_dsg_anonymisieren(self):
        self.laufen_lassen('dsg_anonymisieren')

    def test_bewerbungen_bereinigen(self):
        self.laufen_lassen('bewerbungen_bereinigen')

    def test_sync_contracts(self):
        self.laufen_lassen('sync_contracts')


class JedeVerwaltungKommtDranTests(ZweiBestaende):
    """Der Lauf deckt alle Verwaltungen ab — nicht nur die erste."""

    def test_monatslauf_nennt_beide(self):
        ausgabe = self.laufen_lassen('monatslauf', jahr=2026, monat=8)
        self.assertIn('Verwaltung A AG', ausgabe)
        self.assertIn('Verwaltung B AG', ausgabe)

    def test_jeder_durchgang_hat_den_eigenen_kontext(self):
        """Die eigentliche Zusage: Im Durchgang von B ist B gesetzt.

        Ohne diese Prüfung wäre nur belegt, dass der Befehl zweimal läuft —
        nicht, dass er dabei auf den richtigen Bestand schaut.
        """
        from core.tenancy import aktuelle_organisation, je_organisation

        gesehen = []
        je_organisation(lambda org: gesehen.append(
            (org.pk, getattr(aktuelle_organisation(), 'pk', None))))

        self.assertEqual(len(gesehen), 2, 'Es lief nicht je Verwaltung ein Durchgang.')
        for erwartet, tatsaechlich in gesehen:
            self.assertEqual(tatsaechlich, erwartet,
                             'Im Durchgang einer Verwaltung war eine andere gesetzt.')

    def test_nach_dem_lauf_ist_kein_kontext_mehr_gesetzt(self):
        # Sonst liefe der nächste Befehl im selben Prozess mit dem Kontext der
        # zuletzt bearbeiteten Verwaltung weiter — genau die Art von Fehler,
        # die erst beim zweiten Mandanten auffällt.
        from core.tenancy import aktuelle_organisation, je_organisation

        je_organisation(lambda org: None)
        self.assertIsNone(aktuelle_organisation())


class EinschraenkungTests(ZweiBestaende):
    """`--organisation` holt einen Lauf nach, ohne die übrigen anzufassen."""

    def test_nur_die_gewaehlte_verwaltung(self):
        ausgabe = self.laufen_lassen('monatslauf', jahr=2026, monat=8,
                                     organisation=self.b.organisation.pk)
        self.assertIn('Verwaltung B AG', ausgabe)
        self.assertNotIn('Verwaltung A AG', ausgabe,
                         '--organisation hat trotzdem über alle Verwaltungen gestellt.')

    def test_unbekannte_id_ist_ein_fehler_kein_stiller_leerlauf(self):
        # Ein Tippfehler in der ID darf nicht als „nichts zu tun" durchgehen —
        # sonst meldet der Scheduler Erfolg und es ist nichts gestellt worden.
        from core.tenancy import je_organisation
        with self.assertRaises(ValueError):
            je_organisation(lambda org: None, auswahl=999999)


class FehlerInEinerVerwaltungTests(ZweiBestaende):
    """Ein Abbruch bei A darf B nicht mitnehmen."""

    def test_die_uebrigen_laufen_weiter(self):
        from core.tenancy import je_organisation

        erledigt = []

        def arbeit(organisation):
            if organisation.pk == self.a.organisation.pk:
                raise RuntimeError('Konto fehlt')
            erledigt.append(organisation.pk)

        ergebnisse, fehler = je_organisation(arbeit)

        self.assertEqual(erledigt, [self.b.organisation.pk],
                         'Der Abbruch bei A hat den Lauf von B verhindert.')
        self.assertEqual(len(fehler), 1)
        self.assertEqual(fehler[0][0].pk, self.a.organisation.pk)
        self.assertEqual(ergebnisse, [None], 'B hat kein Ergebnis geliefert.')

    def test_der_befehl_endet_trotzdem_mit_fehler(self):
        # Gegenprobe zum vorigen Test: Weiterlaufen heisst nicht schweigen.
        # Ohne diese Prüfung könnte ein Fehler in einer Verwaltung stillschweigend
        # untergehen, weil die anderen erfolgreich waren.
        # Am Namen IM BEFEHL patchen, nicht am Ursprung: `monatslauf` importiert
        # `run_sollstellung` beim Laden: der Ursprungsname ist dann nicht mehr der,
        # den der Befehl aufruft, und der Test liefe wirkungslos durch.
        with patch('core.management.commands.monatslauf.run_sollstellung',
                   side_effect=RuntimeError('Periode gesperrt')):
            with self.assertRaises(CommandError):
                call_command('monatslauf', jahr=2026, monat=8,
                             stdout=StringIO(), stderr=StringIO())


class KeinDoppelterTeillaufTests(ZweiBestaende):
    """`taeglicher_lauf` darf die selbst-schleifenden Teile nicht n-mal starten.

    `generate_auto_pendenzen`, `update_verwaltung_rates` und `fristen_digest`
    gehen selbst über alle Verwaltungen. Stünden sie zusätzlich in der Schleife,
    liefe jeder n-mal über n Verwaltungen — das Fristen-Mail käme doppelt an,
    und bei zwanzig Verwaltungen zwanzigfach.
    """

    def test_marktdaten_werden_genau_einmal_abgeholt(self):
        self.assertEqual(Organisation.objects.count(), 2, 'Testaufbau kaputt.')
        with patch('core.utils.market_data.fetch_market_rates',
                   return_value=({}, [])) as holen:
            call_command('taeglicher_lauf', digest_weekday=-1,
                         stdout=StringIO(), stderr=StringIO())
        self.assertEqual(holen.call_count, 1,
                         f'Marktdaten {holen.call_count}× abgeholt statt einmal — '
                         'der Teillauf steckt in der Verwaltungsschleife.')

    def test_fristen_mail_wird_genau_einmal_ausgeloest(self):
        with patch('core.utils.market_data.fetch_market_rates', return_value=({}, [])), \
             patch('core.management.commands.taeglicher_lauf.call_command') as unterbefehl:
            call_command('taeglicher_lauf', digest_weekday=-1,
                         stdout=StringIO(), stderr=StringIO())
        self.assertEqual(unterbefehl.call_count, 0, 'digest_weekday=-1 heisst: nie senden.')

    def test_am_richtigen_wochentag_genau_ein_mal(self):
        from django.utils import timezone
        heute = timezone.localdate().weekday()
        with patch('core.utils.market_data.fetch_market_rates', return_value=({}, [])), \
             patch('core.management.commands.taeglicher_lauf.call_command') as unterbefehl:
            call_command('taeglicher_lauf', digest_weekday=heute,
                         stdout=StringIO(), stderr=StringIO())
        self.assertEqual(unterbefehl.call_count, 1,
                         f'Fristen-Mail {unterbefehl.call_count}× ausgelöst statt einmal.')
