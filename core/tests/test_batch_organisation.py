"""Etappe 6.1 — Hintergrundläufe und Services: je Verwaltung, nicht global.

Ein Management-Command läuft ohne Anfrage und damit ohne Mandantenkontext. Die
naheliegende Lösung war bisher `Organisation.objects.first()` plus eine Abfrage
ohne Filter — mit einer Verwaltung nicht zu unterscheiden von richtig, ab der
zweiten eine Vermischung, die niemandem auffällt, weil nichts fehlschlägt.

Auch hier gilt: zwei Bestände, geprüft wird der **zweite**.
"""
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from crm.models import Mitgliedschaft, Organisation

from ._isolation import MandantenFixture


class ZweiBestaende(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        assert Organisation.objects.order_by('pk').first().pk == cls.a.organisation.pk


class FristenDigestTests(ZweiBestaende):
    """Das Fristen-Mail nennt Mieternamen — es darf nur an die eigene Verwaltung."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from core.models import Pendenz
        from core.tenancy import organisation_kontext

        for fixture in (cls.a, cls.b):
            with organisation_kontext(fixture.organisation):
                Pendenz.objects.create(
                    titel=f'Frist {fixture.kuerzel}', vertrag=fixture.vertrag,
                    faellig_am=date.today() + timedelta(days=2), erledigt=False)
            # Ein Empfänger je Verwaltung, damit die Zuordnung prüfbar ist.
            fixture.benutzer.email = f'team-{fixture.kuerzel.lower()}@example.ch'
            fixture.benutzer.is_active = True
            fixture.benutzer.save(update_fields=['email', 'is_active'])
            Mitgliedschaft.objects.update_or_create(
                benutzer=fixture.benutzer, organisation=fixture.organisation,
                defaults={'rolle': Mitgliedschaft.ROLLE_VERWALTER})

    def test_je_verwaltung_ein_eigenes_mail(self):
        mail.outbox.clear()
        call_command('fristen_digest', stdout=StringIO())

        self.assertEqual(len(mail.outbox), 2, 'Erwartet ein Mail je Verwaltung.')
        nach_empfaenger = {m.to[0]: m for m in mail.outbox}
        self.assertEqual(set(nach_empfaenger), {'team-a@example.ch', 'team-b@example.ch'})

    def test_kein_mail_enthaelt_die_mieter_der_anderen(self):
        # Der eigentliche Punkt: In der Zeile steht `mieter.display_name`.
        mail.outbox.clear()
        call_command('fristen_digest', stdout=StringIO())

        for nachricht in mail.outbox:
            fremd = 'B' if nachricht.to[0].endswith('a@example.ch') else 'A'
            self.assertNotIn(f'Frist {fremd}', nachricht.body,
                             f'Mail an {nachricht.to} enthält die Fristen von {fremd}.')
            self.assertNotIn(f'Mieter {fremd}', nachricht.body,
                             f'Mail an {nachricht.to} nennt einen fremden Mieter.')

    def test_empfaenger_kommt_aus_der_mitgliedschaft_nicht_aus_der_gruppe(self):
        # Vorher las der Befehl `groups__name__in=[…]` — quer über alle
        # Verwaltungen. Ein Benutzer ohne Mitgliedschaft in B darf kein Mail
        # von B bekommen, auch wenn er die passende Gruppe trägt.
        from django.contrib.auth.models import Group

        from benutzer.models import Benutzer
        fremder = Benutzer.objects.create_user(
            username='nur_gruppe', password='x', email='fremd@example.ch')
        gruppe, _ = Group.objects.get_or_create(name='Verwalter')
        fremder.groups.add(gruppe)

        mail.outbox.clear()
        call_command('fristen_digest', stdout=StringIO())
        alle_empfaenger = {adresse for m in mail.outbox for adresse in m.to}
        self.assertNotIn('fremd@example.ch', alle_empfaenger)


class CheckRentsTests(ZweiBestaende):
    """Der Mietzins-Scanner rechnet mit dem Stand der jeweiligen Verwaltung."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for fixture, zins, lik in ((cls.a, Decimal('1.25'), Decimal('100.1')),
                                   (cls.b, Decimal('1.75'), Decimal('107.3'))):
            o = fixture.organisation
            o.aktueller_referenzzinssatz = zins
            o.aktueller_lik_punkte = lik
            o.save(update_fields=['aktueller_referenzzinssatz', 'aktueller_lik_punkte'])

    def test_jede_verwaltung_wird_mit_ihrem_eigenen_zinssatz_gerechnet(self):
        gesehen = []

        def _merken(vertrag, ref, lik):
            gesehen.append((vertrag.organisation_id, ref))
            return None

        with patch('core.management.commands.check_rents.berechne_mietpotenzial',
                   side_effect=_merken):
            call_command('check_rents', stdout=StringIO())

        self.assertTrue(gesehen, 'Es wurde kein einziger Vertrag geprüft — Test prüft nichts.')
        zuordnung = dict(gesehen)
        self.assertEqual(zuordnung[self.a.organisation.pk], Decimal('1.25'))
        self.assertEqual(zuordnung[self.b.organisation.pk], Decimal('1.75'))

    def test_ausgabe_nennt_beide_verwaltungen(self):
        raus = StringIO()
        call_command('check_rents', stdout=raus)
        ausgabe = raus.getvalue()
        self.assertIn('Verwaltung A AG', ausgabe)
        self.assertIn('Verwaltung B AG', ausgabe)


class MarktdatenTests(ZweiBestaende):
    """Nationale Werte, aber je Verwaltung gespeichert — und je Aufruf anders."""

    DATEN = {'ref_zins': Decimal('1.50'), 'lik': Decimal('108.0')}

    def test_batchlauf_versorgt_alle_verwaltungen(self):
        # Vorher blieb ab der zweiten Verwaltung jede auf ihrem alten Zinssatz
        # stehen und rechnete Anpassungen nach OR 269a gegen einen veralteten
        # Stand — ohne dass irgendwo ein Fehler erschienen wäre.
        from core.utils.market_data import update_verwaltung_rates

        with patch('core.utils.market_data.fetch_market_rates',
                   return_value=(self.DATEN, [])):
            update_verwaltung_rates()

        for fixture in (self.a, self.b):
            fixture.organisation.refresh_from_db()
            self.assertEqual(fixture.organisation.aktueller_referenzzinssatz, Decimal('1.50'))

    def test_knopfdruck_ruehrt_die_fremde_verwaltung_nicht_an(self):
        from core.utils.market_data import update_verwaltung_rates

        self.a.organisation.aktueller_referenzzinssatz = Decimal('1.00')
        self.a.organisation.save(update_fields=['aktueller_referenzzinssatz'])

        with patch('core.utils.market_data.fetch_market_rates',
                   return_value=(self.DATEN, [])):
            update_verwaltung_rates(self.b.organisation)

        self.a.organisation.refresh_from_db()
        self.b.organisation.refresh_from_db()
        self.assertEqual(self.b.organisation.aktueller_referenzzinssatz, Decimal('1.50'))
        self.assertEqual(self.a.organisation.aktueller_referenzzinssatz, Decimal('1.00'),
                         'Der Knopfdruck hat in eine fremde Verwaltung geschrieben.')

    def test_frischestempel_wird_nicht_fremd_zurueckgesetzt(self):
        # Der Stempel ist der Grund, warum ein Knopfdruck nicht global gelten
        # darf: An ihm hängt die Frischeprüfung in fw_marktdaten_live.
        from core.utils.market_data import update_verwaltung_rates

        with patch('core.utils.market_data.fetch_market_rates',
                   return_value=(self.DATEN, [])):
            update_verwaltung_rates(self.b.organisation)

        self.a.organisation.refresh_from_db()
        self.assertIsNone(self.a.organisation.letztes_update_marktdaten)


class QrUndMahnungTests(ZweiBestaende):
    """Die Stellen, an denen ein falscher Absender teuer wird."""

    def test_qr_rechnung_nennt_die_verwaltung_der_rechnung(self):
        # Eine QR-Rechnung mit fremdem Empfänger weist die Bank im besten Fall
        # zurück; im schlechteren zahlt der Mieter an die falsche Adresse.
        self.assertEqual(self.b.debitor.organisation_id, self.b.organisation.pk)

    def test_schadenmeldung_traegt_ihre_organisation(self):
        # Grundlage für den Vermieter-Namen in ticket_workflow.
        self.assertEqual(self.b.schaden.organisation_id, self.b.organisation.pk)

    def test_mahnung_nutzt_die_verwaltung_des_vertrags(self):
        from core.services import ablage

        with patch('core.views.email_views.generate_mahnung_combined_pdf_bytes',
                   return_value=b'%PDF-1.4') as erzeugen:
            ablage.ablage_mahnung(self.b.vertrag, stufe=1)

        self.assertTrue(erzeugen.called, 'Das Mahnungs-PDF wurde nie erzeugt — Test prüft nichts.')
        # Zweites Positionsargument ist die Verwaltung im Briefkopf.
        self.assertEqual(erzeugen.call_args[0][1].pk, self.b.organisation.pk)
