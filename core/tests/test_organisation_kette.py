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

ZWEITE GEGENPROBE (PR 2) — die Bedingungen
------------------------------------------
Mit entfernten `CheckConstraint`s und ohne die `UniqueConstraint` im Modell:

    KettenPfadTests.test_alternativpfade_sind_durch_eine_bedingung_gesichert
        FEHLER für portfolio.Dokument, portfolio.Zaehler, portfolio.Geraet
    AbleitungTests.test_ohne_jeden_bezug_weist_die_datenbank_ab        ok
    AbleitungTests.test_lebensdauer_ist_je_organisation_eindeutig      ok

**Die beiden grün gebliebenen beweisen hier weniger, als es aussieht**, und das
soll nicht untergehen: Eine Bedingung aus dem Modell zu nehmen entfernt sie
nicht aus der bereits migrierten Testdatenbank. Sie prüfen also die Datenbank,
und die war unverändert. Eine echte Gegenprobe für sie hiesse, die Migration
zurückzurollen — dann fehlte allerdings auch die Spalte, und sie scheiterten
aus einem anderen Grund.

Ihr Wert liegt darum woanders: Sie belegen, dass die Bedingung in der
**Datenbank** tatsächlich greift und nicht nur im Modell steht. Der
Modell-Test daneben deckt die andere Richtung ab — dass keine neue
Alternativ-Kette ohne Bedingung hinzukommt.
"""
from decimal import Decimal

from django.apps import apps
from django.db import models
from django.test import TestCase

from core.organisation_kette import OrganisationAusKette
from crm.models import Organisation
from portfolio.models import Liegenschaft, Einheit, Schluessel, SchluesselAusgabe, Dokument

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
                pfade = modell.ORGANISATION_PFAD
                self.assertTrue(
                    pfade, f'{modell._meta.label}: ORGANISATION_PFAD ist leer')
                einzelpfad = isinstance(pfade, str)
                if einzelpfad:
                    pfade = (pfade,)

                for pfad in pfade:
                    knoten = modell
                    for glied in pfad.split('__'):
                        feld = knoten._meta.get_field(glied)   # wirft bei Tippfehler
                        # `one_to_one` MUSS mitgeprüft werden. Ein OneToOneField
                        # hat `many_to_one == False`, ist aber genauso eine
                        # einwertige Beziehung zum Träger.
                        #
                        # Derselbe blinde Fleck steckte zuerst im Skript, das die
                        # Modelle in Gruppen einordnet: Es hielt
                        # `finance.Erneuerungsfonds` für „kein Weg" (Gruppe A),
                        # obwohl `liegenschaft` ein pflichtiges OneToOne ist —
                        # also glattes Rezept C. Dass er hier ein zweites Mal
                        # auftrat und dieser Test ihn gefunden hat, ist genau
                        # sein Zweck.
                        self.assertTrue(
                            feld.many_to_one or feld.one_to_one,
                            f'{knoten._meta.label}.{glied} ist keine einwertige '
                            f'Beziehung (weder ForeignKey noch OneToOneField)')
                        if einzelpfad:
                            # Ein EINZELNER Pfad muss pflichtig sein, sonst ist die
                            # Kette nicht geschlossen. Bei mehreren Alternativen ist
                            # gerade das Gegenteil der Fall — sie sind alle optional,
                            # und die CheckConstraint garantiert, dass eine trägt.
                            self.assertFalse(
                                feld.null,
                                f'{knoten._meta.label}.{glied} ist optional. Bei einem '
                                f'einzelnen Pfad heisst das: die Kette ist nicht '
                                f'pflichtig. Entweder gehört hier ein Tupel hin, oder '
                                f'{modell._meta.label} ist nicht Gruppe C.')
                        knoten = feld.related_model

                    self.assertTrue(
                        any(f.name == 'organisation' for f in knoten._meta.concrete_fields),
                        f'{modell._meta.label}: Pfad «{pfad}» endet bei '
                        f'{knoten._meta.label}, und das trägt keine Organisation.')

    def test_alternativpfade_koennen_keine_waise_erzeugen(self):
        """Ein Pfad-Tupel braucht eine Absicherung — es gibt genau zwei gültige.

        Sind alle Alternativen optional und keine davon garantiert, entsteht die
        Waise aus Rezept B: ein Datensatz, von dem kein Weg zur Organisation
        führt und der deshalb niemandem gehört. Dagegen hilft:

        **(a) `CheckConstraint`** — die Datenbank erzwingt, dass mindestens ein
        Weg gesetzt ist. Der stärkere Schutz, aber nur dort setzbar, wo der
        Bestand ihn erfüllt. Bei `portfolio.Dokument`, `Geraet` und `Zaehler`
        waren die Tabellen produktiv leer; die Bedingung war folgenlos zu setzen.

        **(b) `ORGANISATION_RUECKFALL = True`** — trägt kein Weg, kommt der Bezug
        aus dem Mandantenkontext. Für die vier Belegarten der Buchhaltung, bei
        denen „noch nicht zugeordnet" ein regulärer Arbeitszustand ist: Ein
        Zahlungseingang aus dem Bankabgleich hat oft weder Vertrag noch
        Liegenschaft. Eine Bedingung hätte dort echte Daten abgewiesen, deren
        Kombinationen niemand vollständig kennt.

        Beide schliessen dasselbe Loch. **Keines von beiden ist der Fehler**, den
        dieser Test sucht — nicht die Wahl zwischen ihnen.

        Die erste Fassung kannte nur (a) und schlug bei den vier Belegarten an.
        Das war kein Fehlalarm, sondern eine Regel, die einen Fall noch nicht
        kannte: Sie entstand, als es nur leere Tabellen gab.
        """
        for modell in _kettenmodelle():
            if isinstance(modell.ORGANISATION_PFAD, str):
                continue
            with self.subTest(modell=modell._meta.label):
                hat_bedingung = any(isinstance(c, models.CheckConstraint)
                                    for c in modell._meta.constraints)
                hat_rueckfall = modell.ORGANISATION_RUECKFALL
                self.assertTrue(
                    hat_bedingung or hat_rueckfall,
                    f'{modell._meta.label} hat mehrere ORGANISATION_PFADe, aber weder '
                    f'eine CheckConstraint noch ORGANISATION_RUECKFALL. Trägt keiner '
                    f'der Wege, entsteht ein Datensatz ohne Organisation — und der '
                    f'gehört niemandem.')

    def test_rueckfall_nur_wo_kein_weg_garantiert_ist(self):
        """Die Gegenrichtung: `ORGANISATION_RUECKFALL` darf keine Umgehung sein.

        Wo eine Pflicht-Kette besteht oder eine `CheckConstraint` mindestens
        einen Weg erzwingt, würde der Rückfall einen Datensatz retten, der gar
        nicht hätte entstehen dürfen — und die Absicherung wäre still wertlos.
        Der Rückfall gehört genau dorthin, wo es sonst keine gibt.
        """
        for modell in _kettenmodelle():
            if not modell.ORGANISATION_RUECKFALL:
                continue
            with self.subTest(modell=modell._meta.label):
                self.assertFalse(
                    isinstance(modell.ORGANISATION_PFAD, str),
                    f'{modell._meta.label} hat einen EINZELNEN (also pflichtigen) '
                    f'Pfad und trotzdem ORGANISATION_RUECKFALL. Der Rückfall würde '
                    f'hier nie greifen — oder er verdeckt, dass die Kette gebrochen ist.')
                self.assertFalse(
                    any(isinstance(c, models.CheckConstraint)
                        for c in modell._meta.constraints),
                    f'{modell._meta.label} hat eine CheckConstraint UND den Rückfall. '
                    f'Eines von beidem ist zu viel: Die Bedingung garantiert bereits '
                    f'einen Weg.')


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

    def test_entweder_oder_erbt_ueber_beide_wege(self):
        """`Dokument` hängt an einer Einheit ODER an einer Liegenschaft.

        Beide Wege müssen tragen — sonst hätte das Tupel keinen Zweck.
        """
        einheit = Einheit.objects.create(
            liegenschaft=self.liegenschaft, bezeichnung='1.5 Zi', typ='wohnung',
            nettomiete_aktuell=Decimal('900'), nebenkosten_aktuell=Decimal('100'))

        ueber_einheit = Dokument.objects.create(einheit=einheit, titel='Grundriss')
        ueber_liegenschaft = Dokument.objects.create(
            liegenschaft=self.liegenschaft, titel='Gebäudeversicherung')

        self.assertEqual(ueber_einheit.organisation_id, self.organisation.pk)
        self.assertEqual(ueber_liegenschaft.organisation_id, self.organisation.pk)

    def test_ohne_jeden_bezug_weist_die_datenbank_ab(self):
        """Die Bedingung aus Rezept B: „mindestens einer der beiden".

        Ohne sie entstünde ein Dokument ohne Weg zur Organisation — ein
        Datensatz, der niemandem gehört und den deshalb jeder sieht.
        """
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            Dokument.objects.create(titel='Gehört niemandem')

    def test_lebensdauer_ist_je_organisation_eindeutig(self):
        """`kategorie` war global unique — dann könnte B «Küche» nie anlegen.

        Die Eindeutigkeit gilt je Verwaltung. Innerhalb einer bleibt sie
        bestehen, sonst wäre die Tabelle doppelt führbar.
        """
        from django.db import IntegrityError
        from portfolio.models import Lebensdauer
        from core.tenancy import organisation_kontext

        # AUSDRUECKLICH eine zweite Verwaltung — nicht `_test_organisation()`,
        # das ja gerade die vorhandene aktualisieren wuerde. Hier geht es darum,
        # dass zwei nebeneinander bestehen koennen.
        andere = Organisation.objects.create(
            firma='Zweite AG', strasse='Nebenweg 2', plz='3000', ort='Bern')

        with organisation_kontext(self.organisation):
            Lebensdauer.objects.create(kategorie='Testkategorie', jahre=20)
        with organisation_kontext(andere):
            # Dieselbe Kategorie bei einer ANDEREN Verwaltung: muss gehen.
            zweite = Lebensdauer.objects.create(kategorie='Testkategorie', jahre=25)
        self.assertEqual(zweite.organisation_id, andere.pk)

        with organisation_kontext(andere), self.assertRaises(IntegrityError):
            # Zweimal bei DERSELBEN: darf nicht.
            Lebensdauer.objects.create(kategorie='Testkategorie', jahre=30)

    def test_bestehende_organisation_wird_nicht_ueberschrieben(self):
        """Ein ausdrücklich gesetzter Wert bleibt stehen.

        Die Datenmigration setzt die Organisation direkt; würde `save()` sie
        danach aus der Kette überschreiben, wäre jede Korrektur von Hand
        wirkungslos.
        """
        # AUSDRUECKLICH eine zweite Verwaltung — nicht `_test_organisation()`,
        # das ja gerade die vorhandene aktualisieren wuerde. Hier geht es darum,
        # dass zwei nebeneinander bestehen koennen.
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
