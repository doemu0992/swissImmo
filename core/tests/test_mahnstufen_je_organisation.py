"""Mahnstufen je Organisation — dynamisch aus der Datenbank, nie aus dem Code.

Der Kernbeweis (`MahnlaufZweiOrganisationenTests`): Dieselbe Forderung, 25 Tage
überfällig, wird von zwei Verwaltungen verschieden behandelt, weil ihre
Einstellungen verschieden sind.

- Verwaltung A behält die Standardwerte 14/30/60 → 25 Tage = Stufe 1.
- Verwaltung B hat auf 10/20/40 gestellt → 25 Tage = Stufe 2.

Gegenproben (protokolliert, nicht behauptet):
- In `core/services/mahnstufen.py::stufen_der_organisation` die Zeile
  `.filter(organisation=organisation)` entfernen → `test_a_aendert_nur_a`,
  `test_stufen_gehoeren_der_organisation` und der Kernbeweis werden rot.
- In `core/views/fw/mahnstufen.py::fw_mahnstufe_loeschen` `MahnStufe` durch
  `MahnStufe.alle_organisationen` ersetzen und die ID einer fremden Stufe nehmen →
  `test_fremde_stufe_nicht_loeschbar` wird rot (404 wird zu 302).
- `standard_mahnstufen_anlegen` in `Organisation.save` auskommentieren →
  `test_neue_organisation_bekommt_standardstufen` wird rot.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext
from core.tests._isolation import MandantenFixture


def _ueberfaellige_rechnung(fixture, tage):
    """Eine offene Miete, die `tage` Tage überfällig ist — in der Organisation des Fixtures.
    Die Fixture-eigene (alte) Rechnung wird zuvor erledigt, damit nur diese zählt."""
    from finance.models import DebitorenRechnung
    with organisation_kontext(fixture.organisation):
        DebitorenRechnung.objects.filter(pk=fixture.debitor.pk).update(status='bezahlt')
        faellig = timezone.localdate() - timedelta(days=tage)
        return DebitorenRechnung.objects.create(
            vertrag=fixture.vertrag, liegenschaft=fixture.liegenschaft, titel='Miete Simulation',
            betrag=Decimal('1700'), datum=faellig, faellig_am=faellig, status='offen')


def _stufen_setzen(organisation, tage_je_stufe):
    """Stellt die Fristen einer Organisation um — so wie es die Verwaltung auf der Seite täte."""
    from crm.models import MahnStufe
    with organisation_kontext(organisation):
        for stufe, tage in tage_je_stufe.items():
            MahnStufe.objects.filter(stufe=stufe).update(ab_tage=tage)


class MahnlaufZweiOrganisationenTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        # A bleibt auf dem Startwert 14/30/60. B mahnt früher: 10/20/40.
        _stufen_setzen(cls.b.organisation, {1: 10, 2: 20, 3: 40})
        cls.rechnung_a = _ueberfaellige_rechnung(cls.a, 25)
        cls.rechnung_b = _ueberfaellige_rechnung(cls.b, 25)

    def _mahnstufe_von(self, fixture, rechnung):
        from finance.models import Mahnung
        with organisation_kontext(fixture.organisation):
            m = Mahnung.objects.filter(debitoren_rechnung=rechnung).first()
            return m.stufe if m else None

    def test_25_tage_a_stufe_1_b_stufe_2(self):
        """Der Kernbeweis — ein Mahnlauf wie der Scheduler ihn fährt (je Organisation)."""
        from core.services.automation import run_mahnlauf
        from core.tenancy import je_organisation

        ergebnisse, fehler = je_organisation(
            lambda org: run_mahnlauf(send_email=False, mit_zins=False))
        self.assertEqual(fehler, [])
        self.assertEqual(len(ergebnisse), 2)

        self.assertEqual(self._mahnstufe_von(self.a, self.rechnung_a), 1,
                         'A (14/30/60): 25 Tage überfällig = erst Stufe 1')
        self.assertEqual(self._mahnstufe_von(self.b, self.rechnung_b), 2,
                         'B (10/20/40): 25 Tage überfällig = schon Stufe 2')

    def test_gebuehr_stammt_aus_der_stufe_der_organisation(self):
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung
        with organisation_kontext(self.b.organisation):
            run_mahnlauf(send_email=False)
            self.assertEqual(Mahnung.objects.get(debitoren_rechnung=self.rechnung_b).gebuehr,
                             Decimal('20.00'))
        with organisation_kontext(self.a.organisation):
            run_mahnlauf(send_email=False)
            self.assertEqual(Mahnung.objects.get(debitoren_rechnung=self.rechnung_a).gebuehr,
                             Decimal('0.00'))

    def test_lauf_einer_organisation_fasst_die_andere_nicht_an(self):
        from core.services.automation import run_mahnlauf
        with organisation_kontext(self.a.organisation):
            res = run_mahnlauf(send_email=False)
        self.assertEqual(res['gemahnt'], 1)
        self.assertIsNone(self._mahnstufe_von(self.b, self.rechnung_b))

    def test_aendern_wirkt_sofort(self):
        """Stellt B seine Frist auf 30 Tage, ist die 25 Tage alte Forderung wieder nicht fällig."""
        from core.services.automation import run_mahnlauf
        _stufen_setzen(self.b.organisation, {1: 30, 2: 45, 3: 70})
        with organisation_kontext(self.b.organisation):
            res = run_mahnlauf(send_email=False)
        self.assertEqual(res['gemahnt'], 0)


class MahnstufenDienstTests(TestCase):

    def test_neue_organisation_bekommt_standardstufen(self):
        from crm.models import MahnStufe, Organisation
        org = Organisation.objects.create(firma='Neu AG', strasse='x 1', plz='8000', ort='Zürich')
        with organisation_kontext(org):
            stufen = list(MahnStufe.objects.order_by('stufe').values_list(
                'stufe', 'bezeichnung', 'ab_tage', 'gebuehr', 'art_257d'))
        self.assertEqual(stufen, [
            (1, '1. Mahnung - Erste Zahlungserinnerung', 14, Decimal('0.00'), False),
            (2, '2. Mahnung - Zweite schriftliche Erinnerung', 30, Decimal('20.00'), False),
            (3, '3. Mahnung - Letzte Mahnung (Fristansetzung nach Art. 257d OR)', 60,
             Decimal('40.00'), True),
        ])

    def test_seeding_ueberschreibt_nichts(self):
        """Wer Stufe 1 angepasst hat, bekommt sie bei einem zweiten Aufruf nicht zurückgesetzt."""
        from core.services.mahnstufen import standard_mahnstufen_anlegen
        from crm.models import MahnStufe, Organisation
        org = Organisation.objects.create(firma='Neu AG', strasse='x 1', plz='8000', ort='Zürich')
        with organisation_kontext(org):
            MahnStufe.objects.filter(stufe=1).update(ab_tage=7)
            standard_mahnstufen_anlegen(org)
            self.assertEqual(MahnStufe.objects.get(stufe=1).ab_tage, 7)
            self.assertEqual(MahnStufe.objects.count(), 3)

    def test_stufen_gehoeren_der_organisation(self):
        from core.services.mahnstufen import mahnstufen_config
        a = MandantenFixture('A', '8000', 'Zürich')
        b = MandantenFixture('B', '3000', 'Bern')
        _stufen_setzen(b.organisation, {1: 10})
        self.assertEqual(min(s['ab_tage'] for s in mahnstufen_config(organisation=a.organisation)), 14)
        self.assertEqual(min(s['ab_tage'] for s in mahnstufen_config(organisation=b.organisation)), 10)

    def test_vierte_stufe_wird_gelebt(self):
        """Die Zahl der Stufen ist Sache der Verwaltung — nicht auf drei festgeschrieben."""
        from core.services.mahnstufen import stufe_fuer_tage
        from crm.models import MahnStufe, Organisation
        org = Organisation.objects.create(firma='Vier AG', strasse='x 1', plz='8000', ort='Zürich')
        with organisation_kontext(org):
            MahnStufe.objects.create(stufe=4, bezeichnung='Inkasso-Androhung', ab_tage=90)
            self.assertEqual(stufe_fuer_tage(95)['stufe'], 4)
            self.assertEqual(stufe_fuer_tage(95)['name'], 'Inkasso-Androhung')

    def test_ohne_stufen_wird_nicht_gemahnt(self):
        from core.services.mahnstufen import stufe_fuer_tage
        from crm.models import MahnStufe, Organisation
        org = Organisation.objects.create(firma='Leer AG', strasse='x 1', plz='8000', ort='Zürich')
        with organisation_kontext(org):
            MahnStufe.objects.all().delete()
            self.assertIsNone(stufe_fuer_tage(500))

    def test_eindeutige_stufennummer_je_organisation(self):
        from django.db import IntegrityError, transaction
        from crm.models import MahnStufe, Organisation
        org = Organisation.objects.create(firma='Doppelt AG', strasse='x 1', plz='8000', ort='Zürich')
        with organisation_kontext(org), self.assertRaises(IntegrityError), transaction.atomic():
            MahnStufe.objects.create(stufe=1, bezeichnung='noch eine', ab_tage=5)


class MahnstufenSeiteTests(TestCase):
    """Eine Verwaltung bearbeitet, ergänzt und löscht ihre Stufen — und nur ihre."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def _stufen(self, fixture):
        from crm.models import MahnStufe
        with organisation_kontext(fixture.organisation):
            return {s.stufe: s for s in MahnStufe.objects.all()}

    def _formular(self, fixture, **ersetze):
        daten = {}
        for s in self._stufen(fixture).values():
            daten[f'bezeichnung_{s.pk}'] = s.bezeichnung
            daten[f'ab_tage_{s.pk}'] = str(s.ab_tage)
            daten[f'gebuehr_{s.pk}'] = str(s.gebuehr)
            if s.art_257d:
                daten[f'art_257d_{s.pk}'] = 'on'
        daten.update(ersetze)
        return daten

    def test_seite_zeigt_die_eigenen_stufen(self):
        antwort = self.c.get('/neu/mahnstufen/')
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, '1. Mahnung - Erste Zahlungserinnerung')
        self.assertContains(antwort, 'value="14"')

    def test_a_aendert_nur_a(self):
        """«Ich mahne schon nach 10 Tagen» — gilt für A, B bleibt bei 14."""
        s1 = self._stufen(self.a)[1]
        antwort = self.c.post('/neu/mahnstufen/', self._formular(self.a, **{f'ab_tage_{s1.pk}': '10'}))
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(self._stufen(self.a)[1].ab_tage, 10)
        self.assertEqual(self._stufen(self.b)[1].ab_tage, 14)

    def test_reihenfolge_wird_geprueft(self):
        """Stufe 2 darf nicht vor Stufe 1 greifen — nichts wird gespeichert."""
        stufen = self._stufen(self.a)
        daten = self._formular(self.a, **{f'ab_tage_{stufen[2].pk}': '5'})
        self.c.post('/neu/mahnstufen/', daten)
        self.assertEqual(self._stufen(self.a)[2].ab_tage, 30)

    def test_ungueltige_eingabe_wird_abgelehnt(self):
        s1 = self._stufen(self.a)[1]
        self.c.post('/neu/mahnstufen/', self._formular(self.a, **{f'ab_tage_{s1.pk}': 'abc'}))
        self.assertEqual(self._stufen(self.a)[1].ab_tage, 14)

    def test_stufe_hinzufuegen(self):
        antwort = self.c.post('/neu/mahnstufen/neu/', {
            'bezeichnung': '4. Mahnung - Betreibungsandrohung', 'ab_tage': '90', 'gebuehr': '50,00'})
        self.assertEqual(antwort.status_code, 302)
        vierte = self._stufen(self.a)[4]
        self.assertEqual((vierte.ab_tage, vierte.gebuehr, vierte.art_257d),
                         (90, Decimal('50.00'), False))
        self.assertNotIn(4, self._stufen(self.b))

    def test_stufe_loeschen(self):
        s3 = self._stufen(self.a)[3]
        self.assertEqual(self.c.post(f'/neu/mahnstufen/{s3.pk}/loeschen/').status_code, 302)
        self.assertNotIn(3, self._stufen(self.a))
        self.assertIn(3, self._stufen(self.b))

    def test_fremde_stufe_nicht_loeschbar(self):
        """404 — nicht 403: Ein 403 verriete, dass die ID existiert."""
        fremd = self._stufen(self.b)[1]
        self.assertEqual(self.c.post(f'/neu/mahnstufen/{fremd.pk}/loeschen/').status_code, 404)
        self.assertIn(1, self._stufen(self.b))

    def test_nur_verwaltungsrollen(self):
        from core.tests._helfer import _team_user
        c = Client()
        c.force_login(_team_user('Hauswart'))
        self.assertEqual(c.get('/neu/mahnstufen/').status_code, 403)


class VerzugsbeginnTests(TestCase):
    """Der Fälligkeitstag ist Tag 0 — und wann der Verzug beginnt, stellt jede Verwaltung ein."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _gemahnt(self, fixture, rechnung):
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung
        with organisation_kontext(fixture.organisation):
            run_mahnlauf(send_email=False)
            return Mahnung.objects.filter(debitoren_rechnung=rechnung).first()

    def test_heute_faellige_miete_erscheint_bei_stufe_ab_0_tagen(self):
        """«1. des Monats ist Fälligkeitstag»: Mit einer Stufe ab 0 Tagen ist sie am 1. dabei."""
        from crm.models import MahnStufe
        with organisation_kontext(self.a.organisation):
            MahnStufe.objects.filter(stufe=1).update(ab_tage=0)
        r = _ueberfaellige_rechnung(self.a, 0)
        m = self._gemahnt(self.a, r)
        self.assertIsNotNone(m)
        self.assertEqual(m.stufe, 1)

    def test_standard_mahnt_heute_faellige_miete_noch_nicht(self):
        """Mit den Standardstufen (ab 14 Tagen) ist sie sichtbar, aber nicht mahnbar."""
        r = _ueberfaellige_rechnung(self.a, 0)
        self.assertIsNone(self._gemahnt(self.a, r))

    def test_verzugsbeginn_je_organisation(self):
        """A: Verzug ab Tag 0, B: erst ab Tag 1 — dieselbe heute fällige Miete, zwei Antworten."""
        from crm.models import MahnStufe, Organisation
        for fx, ab_tag in ((self.a, 0), (self.b, 1)):
            Organisation.objects.filter(pk=fx.organisation.pk).update(mahn_verzug_ab_tag=ab_tag)
            with organisation_kontext(fx.organisation):
                MahnStufe.objects.filter(stufe=1).update(ab_tage=0)
        ra = _ueberfaellige_rechnung(self.a, 0)
        rb = _ueberfaellige_rechnung(self.b, 0)
        self.assertIsNotNone(self._gemahnt(self.a, ra))
        self.assertIsNone(self._gemahnt(self.b, rb))

    def test_mindestabstand_je_organisation(self):
        """Mahnt A nach 14 Tagen und nach 30: Mit Mindestabstand 7 geht die 2. Mahnung nicht
        schon am Folgetag, mit 0 schon."""
        from core.services.automation import run_mahnlauf
        from crm.models import Organisation
        from finance.models import Mahnung
        r = _ueberfaellige_rechnung(self.a, 30)
        with organisation_kontext(self.a.organisation):
            Mahnung.objects.create(debitoren_rechnung=r, vertrag=r.vertrag, stufe=1,
                                   datum=timezone.localdate() - timedelta(days=3),
                                   betrag_offen=Decimal('1700'))
            run_mahnlauf(send_email=False)
            self.assertEqual(Mahnung.objects.filter(debitoren_rechnung=r).count(), 1)
        Organisation.objects.filter(pk=self.a.organisation.pk).update(mahn_mindestabstand_tage=0)
        with organisation_kontext(self.a.organisation):
            run_mahnlauf(send_email=False)
            self.assertEqual(Mahnung.objects.filter(debitoren_rechnung=r).count(), 2)

    def test_verzugszins_satz_je_organisation(self):
        from core.services.automation import run_mahnlauf
        from crm.models import Organisation
        from finance.models import Mahnung
        Organisation.objects.filter(pk=self.a.organisation.pk).update(verzugszins_prozent=Decimal('8.00'))
        r = _ueberfaellige_rechnung(self.a, 36)
        with organisation_kontext(self.a.organisation):
            run_mahnlauf(send_email=False, mit_zins=True)
            zins = Mahnung.objects.get(debitoren_rechnung=r).zins
        # 1700 × 8 % × 36 / 360 = 13.60  (bei 5 % wären es 8.50)
        self.assertEqual(zins, Decimal('13.60'))

    def test_mahnschreiben_nimmt_den_text_der_verwaltung(self):
        from core.services.mahnbrief import _eigener_brief, _eigener_text
        from crm.models import MahnStufe
        with organisation_kontext(self.a.organisation):
            MahnStufe.objects.filter(stufe=1).update(
                brief_titel='Zahlungserinnerung Miete', brief_text='Guten Tag {mieter}\n\n{monat}: CHF {betrag} offen. {unbekannt}')
        eigene = _eigener_brief(self.a.vertrag, 1)
        self.assertEqual(eigene.brief_titel, 'Zahlungserinnerung Miete')
        zeilen = _eigener_text(eigene.brief_text, monat='Oktober 2026', betrag='1700.00',
                               gebuehr='0.00', mieter='Hans Muster')
        self.assertEqual(zeilen, ['Guten Tag Hans Muster', '',
                                  'Oktober 2026: CHF 1700.00 offen. {unbekannt}'])
        # und die andere Verwaltung hat ihren eigenen (leeren) Text
        self.assertEqual(_eigener_brief(self.b.vertrag, 1).brief_text, '')


class MahnwesenEinstellungenSeiteTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def test_speichern_nur_fuer_die_eigene_organisation(self):
        from crm.models import Organisation
        antwort = self.c.post('/neu/mahnstufen/einstellungen/', {
            'mahn_verzug_ab_tag': '1', 'mahn_mindestabstand_tage': '3', 'verzugszins_prozent': '6,5'})
        self.assertEqual(antwort.status_code, 302)
        a = Organisation.objects.get(pk=self.a.organisation.pk)
        b = Organisation.objects.get(pk=self.b.organisation.pk)
        self.assertEqual((a.mahn_verzug_ab_tag, a.mahn_mindestabstand_tage, a.verzugszins_prozent),
                         (1, 3, Decimal('6.50')))
        self.assertEqual((b.mahn_verzug_ab_tag, b.mahn_mindestabstand_tage, b.verzugszins_prozent),
                         (0, 7, Decimal('5.00')))

    def test_ungueltige_werte_werden_abgelehnt(self):
        from crm.models import Organisation
        self.c.post('/neu/mahnstufen/einstellungen/', {
            'mahn_verzug_ab_tag': 'x', 'mahn_mindestabstand_tage': '3', 'verzugszins_prozent': '5'})
        self.assertEqual(Organisation.objects.get(pk=self.a.organisation.pk).mahn_mindestabstand_tage, 7)

    def test_brieftext_wird_mit_den_stufen_gespeichert(self):
        from crm.models import MahnStufe
        with organisation_kontext(self.a.organisation):
            daten = {}
            for s in MahnStufe.objects.all():
                daten.update({f'bezeichnung_{s.pk}': s.bezeichnung, f'ab_tage_{s.pk}': str(s.ab_tage),
                              f'gebuehr_{s.pk}': str(s.gebuehr)})
            s1 = MahnStufe.objects.get(stufe=1)
        daten[f'brief_titel_{s1.pk}'] = 'Freundliche Erinnerung'
        daten[f'brief_text_{s1.pk}'] = 'Bitte zahlen: {betrag}'
        self.c.post('/neu/mahnstufen/', daten)
        with organisation_kontext(self.a.organisation):
            s1 = MahnStufe.objects.get(stufe=1)
        self.assertEqual((s1.brief_titel, s1.brief_text), ('Freundliche Erinnerung', 'Bitte zahlen: {betrag}'))
