"""Der E2E-Seed muss laufen — und alles an seinen Mandanten binden.

WARUM

`seed_e2e` ist der einzige Weg, auf dem die Playwright-Strecke zu Daten kommt
(`e2e/run-server.sh` löscht die Datenbank, migriert, seedet, startet). Seit
Etappe 6.3 die Fachmodelle auf `TenantManager` stellte, brach der Befehl schon
bei `ensure_kontenplan()` ab (`ValueError: Kein Mandantenkontext`): Ein
Management-Command hat keine Middleware, die den Kontext setzt.

Der Ausfall war unsichtbar. Django-Tests fassten den Befehl nicht an, und die
E2E-Tests laufen nicht im selben Durchgang — die Strecke lag still, ohne dass
etwas rot wurde. Genau deshalb steht der Wächter hier und nicht dort.

Der Test prüft vier Dinge, die je einzeln schon einmal gefehlt haben:

1. Der Befehl läuft überhaupt durch (der eigentliche Rückfall).
2. Es entsteht eine `Mitgliedschaft`. Ohne sie bestimmt
   `core.middleware_tenancy` keine Organisation; das Konto käme durch die
   Anmeldung, stünde danach aber ohne Mandanten da — die Oberfläche wäre leer
   und jeder E2E-Test grün aus dem falschen Grund.
3. Jeder erzeugte Datensatz hängt an dieser Organisation.
4. Die gesetzten Auswahlwerte sind gültig. Django prüft `choices` bei
   `create()` NICHT — ein erfundener Wert landet stillschweigend in der
   Datenbank und fällt erst auf, wenn eine Auswertung ihn nicht mehr findet.

KEINE ABSOLUTEN ZAHLEN

Der Test zählt nichts. Er sucht die benannten Objekte des Seeds und lässt alles
andere in der Datenbank in Ruhe — Fixtures anderer Tests dürfen daneben stehen,
ohne diesen hier umzuwerfen.
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from core.tenancy import organisation_kontext
from crm.models import Mieter, Mitgliedschaft, Organisation
from finance.models import DebitorenRechnung, KreditorenRechnung
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag

FIRMA = 'E2E Verwaltung AG'


class SeedE2ETest(TestCase):
    """Der Seed läuft, bindet und wiederholt sich ohne Nebenwirkung."""

    def test_seed_laeuft_und_bindet_an_die_organisation(self):
        call_command('seed_e2e', stdout=StringIO())

        org = Organisation.objects.get(firma=FIRMA)

        benutzer = get_user_model().objects.get(username='e2e')
        self.assertTrue(
            benutzer.check_password('e2e-pass'),
            'Die E2E-Anmeldedaten stehen so in e2e/tests/helpers.ts — ändert '
            'der Seed das Passwort, scheitert die ganze Strecke an der Anmeldung.')

        with organisation_kontext(org):
            mitgliedschaft = Mitgliedschaft.objects.get(benutzer=benutzer)
            self.assertEqual(mitgliedschaft.organisation_id, org.id)

            liegenschaft = Liegenschaft.objects.get(strasse='E2E-Weg 1')
            einheit = Einheit.objects.get(liegenschaft=liegenschaft,
                                          bezeichnung='3.5 Zi E2E')
            mieter = Mieter.objects.get(email='e2e-mieter@example.ch')
            vertrag = Mietvertrag.objects.get(mieter=mieter, einheit=einheit)
            debitor = DebitorenRechnung.objects.get(titel='E2E offene Miete')
            kreditor = KreditorenRechnung.objects.get(referenz='E2E-RF-1')

        for objekt in (liegenschaft, einheit, mieter, vertrag, debitor, kreditor):
            with self.subTest(modell=type(objekt).__name__):
                self.assertEqual(
                    objekt.organisation_id, org.id,
                    f'{type(objekt).__name__} hängt nicht am E2E-Mandanten. '
                    'Ein Datensatz ohne Mandantenbezug ist in der Oberfläche '
                    'unsichtbar — der Test wäre grün, die Seite leer.')

    def test_die_gesetzten_auswahlwerte_sind_gueltig(self):
        """Django prüft `choices` bei `create()` nicht.

        Eine erste Fassung dieses Seeds setzte `Einheit.typ='wohnung'`. Gültig
        sind whg/gew/stwe/pp/gar/bas. Der Wert wäre ohne Fehlermeldung
        gespeichert worden und hätte in keiner Typ-Auswertung mehr
        stattgefunden — die Wohnung wäre in der E2E-Welt weder Wohnung noch
        sonst etwas gewesen.
        """
        call_command('seed_e2e', stdout=StringIO())
        org = Organisation.objects.get(firma=FIRMA)

        with organisation_kontext(org):
            geprueft = [
                (Einheit.objects.get(bezeichnung='3.5 Zi E2E'), 'typ'),
                (Einheit.objects.get(bezeichnung='Keller E2E'), 'typ'),
                (Mieter.objects.get(email='e2e-mieter@example.ch'), 'typ'),
                (Mietvertrag.objects.get(einheit__bezeichnung='3.5 Zi E2E'), 'status'),
                (DebitorenRechnung.objects.get(titel='E2E offene Miete'), 'status'),
                (KreditorenRechnung.objects.get(referenz='E2E-RF-1'), 'status'),
            ]

        for objekt, feldname in geprueft:
            with self.subTest(modell=type(objekt).__name__, feld=feldname):
                erlaubt = [c[0] for c in
                           type(objekt)._meta.get_field(feldname).choices]
                self.assertIn(getattr(objekt, feldname), erlaubt)

    def test_zweiter_lauf_erzeugt_nichts_zusaetzlich(self):
        """Idempotenz: `run-server.sh` und Entwickler rufen den Befehl mehrfach."""
        call_command('seed_e2e', stdout=StringIO())
        org = Organisation.objects.get(firma=FIRMA)

        with organisation_kontext(org):
            vorher = set(Liegenschaft.objects.values_list('pk', flat=True))

        call_command('seed_e2e', stdout=StringIO())

        self.assertEqual(
            Organisation.objects.filter(firma=FIRMA).count(), 1,
            'Der zweite Lauf hat eine zweite Organisation angelegt.')
        with organisation_kontext(org):
            self.assertEqual(
                set(Liegenschaft.objects.values_list('pk', flat=True)), vorher,
                'Der zweite Lauf hat den Bestand dieses Mandanten verändert.')
