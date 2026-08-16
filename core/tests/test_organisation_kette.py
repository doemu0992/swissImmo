"""Etappe 5, PR 1 — der Organisationsbezug der Gruppe C hält, oder er ist wertlos.

Das Rezept im Skill `phase-2-migration` verlangt zu jeder dieser Migrationen
einen Test, der prüft, dass **kein** Datensatz ohne Organisation existiert. Das
ist hier nicht eine Prüfung, sondern drei — jede fängt einen anderen Weg ab, auf
dem eine Waise entstehen könnte:

1. `WaisenTests` — der Bestand als Ganzes, nach allen Migrationen.
2. `AbleitungTests` — der normale Schreibpfad (`save()` leitet ab).
3. `KettenPfadTests` — die Pfade selbst, gegen die echten Fremdschlüssel.

DIE GEGENPROBE, protokolliert
-----------------------------
Ein Test, der nie rot war, beweist nichts. Vor dem Einchecken wurde die
Ableitung in `core/organisation_kette.py` versuchsweise ausgebaut
(`save()` ohne die drei Zeilen, die `organisation_id` setzen):

    AbleitungTests.test_einheit_erbt_von_liegenschaft            FEHLER
    AbleitungTests.test_schluesselausgabe_ueber_drei_glieder     FEHLER
    AbleitungTests.test_bestehende_organisation_wird_nicht_ueberschrieben  ok

Der dritte blieb grün, und das ist richtig: Er prüft, dass ein ausdrücklich
gesetzter Wert erhalten bleibt — dafür braucht es die Ableitung nicht. Er ist
als Wächter gegen die entgegengesetzte Fehlerrichtung da (Ableitung
überschreibt, was der Aufrufer wollte).

`KettenPfadTests` scheitert bei einem Tippfehler im `ORGANISATION_PFAD` — der
Fall, der sonst erst in der Datenmigration auf der Produktion auffiele.
"""
from decimal import Decimal

from django.apps import apps
from django.test import TestCase

from core.organisation_kette import OrganisationAusKette
from crm.models import Organisation
from portfolio.models import Liegenschaft, Einheit, Schluessel, SchluesselAusgabe

from ._helfer import _test_organisation


def _kettenmodelle():
    """Alle Modelle, die ihren Bezug aus einer Kette ableiten."""
    return [m for m in apps.get_models()
            if issubclass(m, OrganisationAusKette) and not m._meta.abstract]


class WaisenTests(TestCase):
    """Kein Datensatz ohne Organisation — die Kernaussage von Rezept C."""

    def test_kein_datensatz_ohne_organisation(self):
        for modell in _kettenmodelle():
            with self.subTest(modell=modell._meta.label):
                offen = modell.objects.filter(organisation__isnull=True).count()
                self.assertEqual(
                    offen, 0,
                    f'{modell._meta.label}: {offen} Datensätze ohne Organisation. '
                    f'Ein Datensatz ohne Mandant gehört niemandem — und ist damit '
                    f'für jeden sichtbar, der irgendeine Organisation hat.')

    def test_anker_ist_pflichtig(self):
        """`Liegenschaft.organisation` trägt die ganze Kette.

        Wäre sie weiter optional, könnte kein abgeleitetes Modell `null=False`
        sein: Eine Kette ist nur so pflichtig wie ihr schwächstes Glied.
        """
        feld = Liegenschaft._meta.get_field('organisation')
        self.assertFalse(feld.null, 'Liegenschaft.organisation muss pflichtig sein')
        self.assertEqual(
            Liegenschaft.objects.filter(organisation__isnull=True).count(), 0)


class KettenPfadTests(TestCase):
    """Jeder `ORGANISATION_PFAD` muss über echte Fremdschlüssel zur Organisation führen.

    Ein Tippfehler im Pfad fällt sonst erst auf, wenn die Datenmigration auf der
    Produktion läuft — und dort als Datensatz ohne Bezug, nicht als Fehler.
    """

    def test_pfad_ist_gesetzt_und_gueltig(self):
        for modell in _kettenmodelle():
            with self.subTest(modell=modell._meta.label):
                pfad = modell.ORGANISATION_PFAD
                self.assertTrue(
                    pfad, f'{modell._meta.label}: ORGANISATION_PFAD ist leer')

                knoten = modell
                for glied in pfad.split('__'):
                    feld = knoten._meta.get_field(glied)   # wirft bei Tippfehler
                    self.assertTrue(
                        feld.many_to_one,
                        f'{knoten._meta.label}.{glied} ist kein Fremdschlüssel')
                    self.assertFalse(
                        feld.null,
                        f'{knoten._meta.label}.{glied} ist optional — dann ist die '
                        f'Kette nicht pflichtig und {modell._meta.label} gehört '
                        f'nicht in Gruppe C.')
                    knoten = feld.related_model

                self.assertTrue(
                    any(f.name == 'organisation' for f in knoten._meta.concrete_fields),
                    f'{modell._meta.label}: Pfad endet bei {knoten._meta.label}, '
                    f'und das trägt keine Organisation.')


class AbleitungTests(TestCase):
    """Der normale Schreibpfad füllt die Spalte, ohne dass ein Aufrufer daran denkt."""

    def setUp(self):
        self.organisation = _test_organisation()
        self.liegenschaft = Liegenschaft.objects.create(
            strasse='Kettenweg 1', plz='8000', ort='Zürich',
            organisation=self.organisation)

    def test_einheit_erbt_von_liegenschaft(self):
        einheit = Einheit.objects.create(
            liegenschaft=self.liegenschaft, bezeichnung='3.5 Zi', typ='wohnung',
            nettomiete_aktuell=Decimal('1500'), nebenkosten_aktuell=Decimal('200'))
        self.assertEqual(einheit.organisation_id, self.organisation.pk)

    def test_schluesselausgabe_ueber_drei_glieder(self):
        """`schluessel__liegenschaft` — der längste Pfad in portfolio."""
        schluessel = Schluessel.objects.create(
            liegenschaft=self.liegenschaft, schluessel_nummer='H-01', anzahl=2)
        ausgabe = SchluesselAusgabe.objects.create(schluessel=schluessel)
        self.assertEqual(schluessel.organisation_id, self.organisation.pk)
        self.assertEqual(ausgabe.organisation_id, self.organisation.pk)

    def test_bestehende_organisation_wird_nicht_ueberschrieben(self):
        """Ein ausdrücklich gesetzter Wert bleibt stehen.

        Die Datenmigration setzt die Organisation direkt; würde `save()` sie
        danach aus der Kette überschreiben, wäre jede Korrektur von Hand
        wirkungslos.
        """
        andere = Organisation.objects.create(
            firma='Zweite AG', strasse='Nebenweg 2', plz='3000', ort='Bern')
        einheit = Einheit(liegenschaft=self.liegenschaft, bezeichnung='2.5 Zi',
                          typ='wohnung', nettomiete_aktuell=Decimal('1200'),
                          nebenkosten_aktuell=Decimal('150'))
        einheit.organisation = andere
        einheit.save()
        einheit.refresh_from_db()
        self.assertEqual(einheit.organisation_id, andere.pk)

    def test_liegenschaft_nimmt_die_organisation_aus_dem_kontext(self):
        """Die Wurzel der Kette hat keine Kette — sie liest den Mandantenkontext.

        Das ist der Pfad, den `core/views/fw/liegenschaft_crud.py` geht:
        `Liegenschaft()` anlegen, Formularfelder setzen, speichern. Die
        Organisation steht dort nirgends im Formular.
        """
        from core.tenancy import organisation_kontext

        with organisation_kontext(self.organisation):
            neue = Liegenschaft(strasse='Kontextweg 5', plz='4000', ort='Basel')
            neue.save()
        self.assertEqual(neue.organisation_id, self.organisation.pk)

    def test_ohne_kontext_und_ohne_angabe_schlaegt_das_anlegen_fehl(self):
        """Es wird NICHT geraten.

        Die naheliegende Bequemlichkeit wäre, auf „die einzige vorhandene
        Organisation" auszuweichen. Das ginge heute gut und wäre ab dem zweiten
        Mandanten eine stille Fehlzuordnung — die Art Regel, die erst auffällt,
        wenn sie schon Schaden angerichtet hat.
        """
        from django.db import IntegrityError
        from core.tenancy import ohne_organisation

        with ohne_organisation():
            with self.assertRaises(IntegrityError):
                Liegenschaft.objects.create(
                    strasse='Nirgendwo 1', plz='9000', ort='St. Gallen')
