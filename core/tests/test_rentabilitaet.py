"""Die Rentabilitätskarte sagt, worauf sie beruht.

WARUM SIE BIS E2.56 FEHLTE — UND WARUM DIE BEGRÜNDUNG ÜBERHOLT WAR

Der Kopf von `core/views/fw/akten_neu.py` sagte: «Dafür fehlt die
Zeiterfassung pro Fall.» Das galt bis E2.46; seither gibt es
`faelle.Zeiteintrag` mit Fallbezug und Stundensatz. Die Notiz stand an der
Stelle, wo man sie am ehesten glaubt, und war seit zehn Etappen falsch.

DIE FACHLICHE SORGE BLEIBT RICHTIG

Der Prototyp notierte: «Eine Kennzahl aus geschätzten Stunden wäre schlimmer
als keine.» Genau deshalb prüfen diese Tests weniger die Rechnung als das,
was die Karte über ihre eigene Grundlage sagt:

* Ohne Stundensatz oder ohne erfasste Zeit erscheint der GRUND, nicht
  «CHF 0.00» — eine Null wäre eine Aussage, die niemand getroffen hat.
* Die Abdeckung steht daneben: Bei zwei von neunzehn Fällen mit erfasster
  Zeit ist «CHF 340 pro Stunde» kein Ergebnis, sondern ein Zufall.
"""
from decimal import Decimal

from django.test import Client, TestCase

from core.tenancy import organisation_kontext as mandant

from ._isolation import MandantenFixture


class RentabilitaetTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _mandat(self):
        """Der Eigentümer aus der Fixture, mit Honorarsatz."""
        from crm.models import Eigentuemer

        # `TenantManager` verlangt den Kontext; ohne ihn wirft der Zugriff.
        with mandant(self.a.organisation):
            md = Eigentuemer.objects.filter(
                organisation=self.a.organisation).first()
        self.assertIsNotNone(md, 'Die Fixture liefert keinen Eigentümer.')
        md.honorar_prozent = Decimal('5')
        md.save(update_fields=['honorar_prozent'])
        return md

    def _seite(self, md):
        c = Client()
        c.force_login(self.a.benutzer)
        antwort = c.get(f'/neu/mandate/{md.id}/')
        self.assertEqual(antwort.status_code, 200)
        return antwort

    def test_die_karte_steht_auf_der_seite(self):
        html = self._seite(self._mandat()).content.decode()
        self.assertIn('Rentabilität', html)
        self.assertIn('Datenbasis', html)

    def test_ohne_erfasste_zeit_steht_der_grund_da(self):
        """Nicht «CHF 0.00».

        Eine Null sähe aus wie eine gemessene Zahl. «Noch keine Stunde
        erfasst» sagt, warum keine dasteht — dieselbe Unterscheidung wie bei
        `Geraet.neuwert` und beim Stundensatz (E2.46).
        """
        antwort = self._seite(self._mandat())
        rent = antwort.context['rentabilitaet']
        self.assertIsNone(rent['chf_pro_stunde'])
        self.assertEqual(rent['fehlt'], 'Noch keine Stunde erfasst')
        self.assertNotIn('CHF 0.00', antwort.content.decode())

    def test_ohne_honorarsatz_steht_ein_anderer_grund_da(self):
        """Zwei verschiedene Lücken, zwei verschiedene Sätze.

        «Kein Honorarsatz hinterlegt» ist eine andere Aufgabe als «noch keine
        Stunde erfasst» — wer nur «—» sieht, weiss nicht, was zu tun ist.
        """
        md = self._mandat()
        # `honorar_prozent` ist NOT NULL — «kein Satz» ist 0, nicht `None`.
        # Nachgesehen an der Fehlermeldung, nicht geraten.
        md.honorar_prozent = Decimal('0')
        md.save(update_fields=['honorar_prozent'])
        rent = self._seite(md).context['rentabilitaet']
        self.assertEqual(rent['fehlt'], 'Kein Honorarsatz hinterlegt')

    def test_die_abdeckung_wird_gezaehlt(self):
        """Der ehrlichste Teil der Karte.

        Ohne diese Zahl steht «CHF 340 pro Stunde» allein da und sieht aus wie
        ein Ergebnis, auch wenn nur einer von neunzehn Fällen Zeit erfasst hat.
        """
        from faelle.models import Fall, Fallart, Zeiteintrag

        md = self._mandat()
        org = self.a.organisation
        # DIE AKTE IST DER EIGENTÜMER, NICHT DIE LIEGENSCHAFT.
        #
        # `fw_mandat_detail` sammelt `Fall.objects.filter(akte_typ=Eigentuemer,
        # akte_id=md.id)` — nachgesehen in der Ansicht. Ein erster Entwurf
        # hängte die Fälle an die Liegenschaft; die Karte zählte dann null, und
        # der Test war zu Recht rot.
        with mandant(org):
            art = Fallart.objects.create(
                organisation=org, schluessel='rent', bezeichnung='Prüfung')
            fall = Fall(organisation=org, fallart=art, akte=md, betreff='Mit Zeit')
            fall.save()
            ohne = Fall(organisation=org, fallart=art, akte=md, betreff='Ohne Zeit')
            ohne.save()
            Zeiteintrag.objects.create(
                fall=fall, benutzer=self.a.benutzer, minuten=120,
                taetigkeit='sonder')

        rent = self._seite(md).context['rentabilitaet']
        self.assertEqual(rent['faelle_mit_zeit'], 1)
        self.assertGreaterEqual(rent['faelle_gesamt'], 2)
        self.assertEqual(rent['stunden'], Decimal('2.0'))

    def test_unter_der_stunde_keine_kennzahl(self):
        """Aus zwölf Minuten lässt sich kein Stundensatz ableiten.

        Die Hochrechnung wäre rechnerisch möglich und inhaltlich wertlos —
        genau die «Kennzahl aus geschätzten Stunden», vor der der Prototyp
        warnt.
        """
        from faelle.models import Fall, Fallart, Zeiteintrag

        md = self._mandat()
        org = self.a.organisation
        with mandant(org):
            art = Fallart.objects.create(
                organisation=org, schluessel='kurz', bezeichnung='Kurz')
            fall = Fall(organisation=org, fallart=art, akte=md, betreff='Kurz')
            fall.save()
            Zeiteintrag.objects.create(
                fall=fall, benutzer=self.a.benutzer, minuten=12,
                taetigkeit='sonder')

        rent = self._seite(md).context['rentabilitaet']
        self.assertIsNone(rent['chf_pro_stunde'])


class RentabilitaetMandantengrenzeTest(TestCase):
    """Die erfassten Stunden bleiben beim eigenen Mandat.

    E2.56 ergänzt in `fw_mandat_detail` eine neue Abfrage:

        Zeiteintrag.objects.filter(fall_id__in=ident)

    Damit wandert eine Zahl auf eine Seite, die ihre ID aus der URL nimmt.
    Zwei Schutzschichten greifen — `ident` stammt aus den bereits gefilterten
    Fällen, und `Zeiteintrag.objects` ist ein `TenantManager` mit
    `ORGANISATION_PFAD = 'fall'`. Beide sind ungeprüft, solange es keinen Test
    gibt, der über die Grenze GREIFT.

    Was durchsickern könnte, ist kein Detail: Der Aufwand einer anderen
    Verwaltung sagt, wie viel Arbeit sie in ein Mandat steckt — und das Honorar
    daneben, was sie dafür verlangt.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _mit_zeit(self, fix, minuten):
        """Ein Fall mit erfasster Zeit am Eigentümer dieses Mandanten."""
        from crm.models import Eigentuemer
        from faelle.models import Fall, Fallart, Zeiteintrag

        with mandant(fix.organisation):
            md = Eigentuemer.objects.filter(organisation=fix.organisation).first()
            md.honorar_prozent = Decimal('5')
            md.save(update_fields=['honorar_prozent'])
            art = Fallart.objects.create(
                organisation=fix.organisation,
                schluessel=f'z{fix.kuerzel}', bezeichnung='Prüfung')
            fall = Fall(organisation=fix.organisation, fallart=art,
                        akte=md, betreff=f'Fall {fix.kuerzel}')
            fall.save()
            Zeiteintrag.objects.create(fall=fall, benutzer=fix.benutzer,
                                       minuten=minuten, taetigkeit='sonder')
        return md

    def test_fremde_stunden_zaehlen_nicht_mit(self):
        md_a = self._mit_zeit(self.a, 60)
        self._mit_zeit(self.b, 999)

        c = Client()
        c.force_login(self.a.benutzer)
        rent = c.get(f'/neu/mandate/{md_a.id}/').context['rentabilitaet']
        self.assertEqual(
            rent['minuten'], 60,
            'Der Aufwand eines fremden Mandanten ist in die Kennzahl geflossen.')
        self.assertEqual(rent['faelle_mit_zeit'], 1)

    def test_fremdes_mandat_gibt_404(self):
        """Ein 403 verriete, dass die ID existiert."""
        from crm.models import Eigentuemer

        with mandant(self.b.organisation):
            fremd = Eigentuemer.objects.filter(
                organisation=self.b.organisation).first()
        c = Client(raise_request_exception=False)
        c.force_login(self.a.benutzer)
        self.assertEqual(c.get(f'/neu/mandate/{fremd.id}/').status_code, 404)

    def test_die_kette_bindet_den_zeiteintrag_an_den_fall(self):
        """Warum es hier keinen «fremden Zeiteintrag» geben kann.

        DER VERSUCH, DER DAHINTER STEHT

        Zwei Gegenproben zu den Isolationstests blieben grün: Weder das
        Aufheben des Mandantenfilters auf `Zeiteintrag` noch das auf `Fall`
        änderte etwas. Die Ansicht hat zwei Schranken, und eine hält immer.

        WELCHE MUTATION WAS TUT — nachgemessen, weil sich das sonst als
        Widerspruch zur Gegenprobe aus E2.56 liest:

            Zeiteintrag.alle_organisationen.filter(fall_id__in=ident)   grün
            Zeiteintrag.alle_organisationen.all()                       ROT

        Der Manager allein trägt hier nichts: `ident` stammt bereits aus
        gefilterten Fällen. Erst wer AUCH den Filter wegnimmt, hebt beide
        Schranken auf — und genau das tat die Gegenprobe in E2.56. Beide
        Beobachtungen stimmen, sie meinen verschiedene Eingriffe.

        Ein Test, dessen Fehlerfall sich nicht herstellen lässt, beweist
        nichts — also habe ich versucht, den Fall zu bauen, der wirklich
        vorkommen kann: einen Zeiteintrag mit fremder Organisation an einem
        eigenen Fall, wie er durch einen Importfehler entstünde.

        DAS GEHT NICHT, UND DAS IST DAS ERGEBNIS

        `Zeiteintrag.ORGANISATION_PFAD = 'fall'`: Die Organisation wird beim
        Speichern AUS DEM FALL abgeleitet, nicht aus dem Kontext. Ein im
        Kontext B angelegter Eintrag an einem Fall aus A trägt A.

        Ein Zeiteintrag gehört dorthin, wo sein Fall hingehört — nicht dorthin,
        wo jemand ihn gerade anlegt. Das ist keine Prüfung, die man umgehen
        kann, sondern eine Ableitung.

        Dieser Test hält es fest, damit niemand die Kette später durch ein
        eigenes `organisation`-Feld ersetzt und dabei die Bindung verliert.
        """
        from faelle.models import Zeiteintrag

        md = self._mit_zeit(self.a, 60)
        from django.contrib.contenttypes.models import ContentType
        from crm.models import Eigentuemer
        from faelle.models import Fall
        with mandant(self.a.organisation):
            fall = Fall.objects.filter(
                akte_typ=ContentType.objects.get_for_model(Eigentuemer),
                akte_id=md.id).first()

        # Im FREMDEN Kontext angelegt — trägt trotzdem die Organisation des Falls.
        with mandant(self.b.organisation):
            eintrag = Zeiteintrag.objects.create(
                fall=fall, benutzer=self.b.benutzer,
                minuten=999, taetigkeit='sonder')

        self.assertEqual(
            eintrag.organisation_id, fall.organisation_id,
            'Der Zeiteintrag trägt eine andere Organisation als sein Fall — '
            'dann ist die Kette unterbrochen, und Aufwand kann in eine fremde '
            'Rentabilität fliessen.')
