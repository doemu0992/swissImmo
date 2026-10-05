"""Vorgaben der Gemeinschaft: Einladungsfrist, Beschlussfähigkeit, Anfechtungsfrist — nur, was eingetragen ist."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.tests._helfer import _team_user
from stweg import vorgaben
from stweg.beschluss import BeschlussFehler, anwesenheit_setzen, feststellen, stimme_abgeben
from stweg.models import StwegVorgaben, Traktandum, Versammlung
from stweg.test_budget import haus_mit_eigentuemern

D = Decimal


class VorgabenTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()      # Quoten 150/200/250/200/200

    def test_ohne_eintrag_wird_nichts_beurteilt(self):
        v = Versammlung.objects.create(liegenschaft=self.lg, titel='OV', status='durchgefuehrt',
                                       datum=timezone.now())
        self.assertIsNone(vorgaben.beschlussfaehigkeit(v))
        self.assertIsNone(vorgaben.anfechtungsfrist_bis(v))
        self.assertEqual(vorgaben.einladungsfrist_vorgabe(self.lg), 10)
        self.assertFalse(vorgaben.ist_bestaetigt(self.lg))

    def test_speichern_validiert_und_bestaetigt(self):
        with self.assertRaises(vorgaben.VorgabenFehler):
            vorgaben.speichern(self.lg, {'quorum_koepfe_prozent': '120'})
        with self.assertRaises(vorgaben.VorgabenFehler):
            vorgaben.speichern(self.lg, {'einladungsfrist_tage': '-3'})
        with self.assertRaises(vorgaben.VorgabenFehler):
            vorgaben.speichern(self.lg, {'anfechtungsfrist_tage': 'zehn'})
        self.assertFalse(StwegVorgaben.objects.exists())
        v = vorgaben.speichern(self.lg, {'einladungsfrist_tage': '14', 'quorum_koepfe_prozent': '50,5'},
                               bestaetigen=True, user=_team_user('Verwaltung'))
        self.assertEqual((v.einladungsfrist_tage, v.quorum_koepfe_prozent), (14, D('50.5')))
        self.assertTrue(vorgaben.ist_bestaetigt(self.lg))
        self.assertEqual(vorgaben.einladungsfrist_vorgabe(self.lg), 14)

    def test_aenderung_nimmt_die_bestaetigung_zurueck_gleicher_stand_nicht(self):
        vorgaben.speichern(self.lg, {'einladungsfrist_tage': '14'}, bestaetigen=True)
        vorgaben.speichern(self.lg, {'einladungsfrist_tage': '14', 'bemerkung': 'Art. 7'})   # nur die Quelle
        self.assertTrue(vorgaben.ist_bestaetigt(self.lg))
        vorgaben.speichern(self.lg, {'einladungsfrist_tage': '20'})
        self.assertFalse(vorgaben.ist_bestaetigt(self.lg))

    def test_db_erzwingt_prozentbereich(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            StwegVorgaben.objects.create(liegenschaft=self.lg, quorum_quoten_prozent=D('101'))

    def versammlung(self, anwesend):
        v = Versammlung.objects.create(liegenschaft=self.lg, titel='OV', status='durchgefuehrt',
                                       datum=timezone.now())
        for einheit in anwesend:
            anwesenheit_setzen(v, einheit, 'anwesend')
        return v

    def test_beschlussfaehigkeit_koepfe_und_quoten(self):
        vorgaben.speichern(self.lg, {'quorum_koepfe_prozent': '50', 'quorum_quoten_prozent': '50'})
        # A, B, C anwesend: 3/5 Köpfe = 60 %, Quoten 150+200+250 = 600 → ok
        bf = vorgaben.beschlussfaehigkeit(self.versammlung(self.e[:3]))
        self.assertTrue(bf['beschlussfaehig'])
        self.assertEqual(bf['gruende'], [])
        # A, B, D anwesend: 3 Köpfe, aber Quoten 150+200+200 = 550 → ok
        self.assertTrue(vorgaben.beschlussfaehigkeit(self.versammlung([self.e[0], self.e[1], self.e[3]]))['beschlussfaehig'])
        # A, B: 2/5 = 40 % Köpfe, 350 Quoten = 35 % → beides fehlt
        bf = vorgaben.beschlussfaehigkeit(self.versammlung(self.e[:2]))
        self.assertFalse(bf['beschlussfaehig'])
        self.assertEqual(len(bf['gruende']), 2)

    def test_genau_auf_der_grenze_ist_beschlussfaehig(self):
        vorgaben.speichern(self.lg, {'quorum_koepfe_prozent': '40'})
        self.assertTrue(vorgaben.beschlussfaehigkeit(self.versammlung(self.e[:2]))['beschlussfaehig'])   # 2/5 = 40 %
        vorgaben.speichern(self.lg, {'quorum_koepfe_prozent': '40.01'})
        self.assertFalse(vorgaben.beschlussfaehigkeit(self.versammlung(self.e[:2]))['beschlussfaehig'])

    def test_nur_ein_quorum_gesetzt(self):
        vorgaben.speichern(self.lg, {'quorum_quoten_prozent': '60'})
        bf = vorgaben.beschlussfaehigkeit(self.versammlung(self.e[:2]))     # 35 %
        self.assertEqual([g.split(':')[0] for g in bf['gruende']], ['Wertquoten'])

    def traktandum(self, anwesend):
        v = self.versammlung(anwesend)
        t = Traktandum.objects.create(geschaeftsart='sonstiges', rechtsgrundlage='Reglement (Test)', versammlung=v, nr=1, titel='X', mehrheitsart='einfach_koepfe')
        for e in anwesend:
            stimme_abgeben(t, e, 'ja')
        return t

    def test_feststellen_blockiert_ohne_beschlussfaehigkeit(self):
        vorgaben.speichern(self.lg, {'quorum_koepfe_prozent': '60'})
        t = self.traktandum(self.e[:2])
        with self.assertRaisesRegex(BeschlussFehler, 'Nicht beschlussfähig'):
            feststellen(t, 'angenommen')
        t.refresh_from_db()
        self.assertEqual(t.ergebnis, 'offen')
        feststellen(t, 'vertagt')                                  # Vertagen ist keine Entscheidung
        t.refresh_from_db()
        self.assertEqual(t.ergebnis, 'vertagt')

    def test_trotzdem_feststellen_wird_festgehalten_und_steht_im_protokoll(self):
        from stweg.pdf import protokoll_pdf
        import io
        from pypdf import PdfReader
        vorgaben.speichern(self.lg, {'quorum_koepfe_prozent': '60'})
        t = self.traktandum(self.e[:2])
        feststellen(t, 'angenommen', trotzdem=True)
        t.refresh_from_db()
        self.assertTrue(t.ohne_beschlussfaehigkeit)
        text = ''.join(p.extract_text() for p in PdfReader(io.BytesIO(protokoll_pdf(t.versammlung))).pages)
        self.assertIn('trotz fehlender Beschlussf', text)
        self.assertIn('NICHT erf', text)

    def test_beschlussfaehig_oder_nicht_konfiguriert_ohne_markierung(self):
        vorgaben.speichern(self.lg, {'quorum_koepfe_prozent': '40'})
        t = self.traktandum(self.e[:2])
        feststellen(t, 'angenommen', trotzdem=True)                # trotzdem, aber es war nicht nötig
        t.refresh_from_db()
        self.assertFalse(t.ohne_beschlussfaehigkeit)

    def test_ohne_quorum_wird_auch_mit_anderen_vorgaben_nichts_beurteilt(self):
        vorgaben.speichern(self.lg, {'einladungsfrist_tage': '14'})          # kein Quorum eingetragen
        self.assertIsNone(vorgaben.beschlussfaehigkeit(self.versammlung(self.e[:1])))

    def test_markierung_faellt_weg_wenn_erneut_festgestellt_wird_und_es_nicht_mehr_noetig_ist(self):
        vorgaben.speichern(self.lg, {'quorum_koepfe_prozent': '60'})
        t = self.traktandum(self.e[:2])
        feststellen(t, 'angenommen', trotzdem=True)
        t.refresh_from_db()
        self.assertTrue(t.ohne_beschlussfaehigkeit)
        for e in self.e[2:4]:                                               # Anwesenheit korrigiert: 4/5
            anwesenheit_setzen(t.versammlung, e, 'anwesend')
        feststellen(t, 'angenommen')
        t.refresh_from_db()
        self.assertFalse(t.ohne_beschlussfaehigkeit)

    def test_anfechtungsfrist(self):
        vorgaben.speichern(self.lg, {'anfechtungsfrist_tage': '30'})
        v = self.versammlung([])
        self.assertIsNone(vorgaben.anfechtungsfrist_bis(v))        # Protokoll noch nicht versendet
        v.protokoll_versendet_am = timezone.now() - timedelta(days=5)
        v.save()
        self.assertEqual(vorgaben.anfechtungsfrist_bis(v), timezone.localdate() + timedelta(days=25))


class VorgabenOberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.client.force_login(_team_user('Verwaltung'))
        self.base = f'/neu/stweg/{self.lg.pk}'

    def test_banner_bis_zur_bestaetigung(self):
        self.assertContains(self.client.get(f'{self.base}/'), 'Rechtswerte nicht bestätigt')
        self.client.post(f'{self.base}/vorgaben/speichern/', {'einladungsfrist_tage': '14', 'bestaetigt': '1'})
        self.assertNotContains(self.client.get(f'{self.base}/'), 'Rechtswerte nicht bestätigt')

    def test_neue_versammlung_uebernimmt_die_vorgabe(self):
        self.client.post(f'{self.base}/vorgaben/speichern/', {'einladungsfrist_tage': '21'})
        self.assertContains(self.client.get(f'{self.base}/'), 'name="einladungsfrist_tage" inputmode="numeric" value="21"')
        self.client.post(f'{self.base}/versammlung/neu/', {'titel': 'OV', 'datum': '2027-03-01T18:00', 'einladungsfrist_tage': ''})
        self.assertEqual(Versammlung.objects.get().einladungsfrist_tage, 21)

    def test_fehlerhafte_eingabe_wird_gemeldet(self):
        r = self.client.post(f'{self.base}/vorgaben/speichern/', {'quorum_koepfe_prozent': '150'}, follow=True)
        self.assertContains(r, 'erlaubt sind Werte')
        self.assertFalse(StwegVorgaben.objects.exists())

    def test_versammlungsseite_zeigt_beschlussfaehigkeit_und_trotzdem(self):
        vorgaben.speichern(self.lg, {'quorum_koepfe_prozent': '60'})
        v = Versammlung.objects.create(liegenschaft=self.lg, titel='OV', status='durchgefuehrt', datum=timezone.now())
        anwesenheit_setzen(v, self.e[0], 'anwesend')
        Traktandum.objects.create(geschaeftsart='sonstiges', rechtsgrundlage='Reglement (Test)', versammlung=v, nr=1, titel='X', mehrheitsart='einfach_koepfe')
        seite = self.client.get(f'/neu/stweg/versammlung/{v.pk}/')
        self.assertContains(seite, 'nicht beschlussfähig')
        self.assertContains(seite, 'name="trotzdem"')
        t = v.traktanden.get()
        r = self.client.post(f'/neu/stweg/traktandum/{t.pk}/feststellen/', {'ergebnis': 'abgelehnt'}, follow=True)
        self.assertContains(r, 'Nicht beschlussfähig')
        self.client.post(f'/neu/stweg/traktandum/{t.pk}/feststellen/', {'ergebnis': 'abgelehnt', 'trotzdem': '1'})
        t.refresh_from_db()
        self.assertEqual((t.ergebnis, t.ohne_beschlussfaehigkeit), ('abgelehnt', True))

    def test_fremde_verwaltung_404(self):
        from crm.models import Mitgliedschaft, Organisation
        from django.contrib.auth import get_user_model
        from django.test import Client
        fremd = Organisation.objects.create(firma='Fremd AG', strasse='X 1', plz='9000', ort='SG')
        u = get_user_model().objects.get(username='team_Verwaltung')
        Mitgliedschaft.objects.filter(benutzer=u).update(organisation=fremd)
        c = Client()
        c.force_login(u)
        self.assertEqual(c.get(f'{self.base}/vorgaben/').status_code, 404)
        self.assertEqual(c.post(f'{self.base}/vorgaben/speichern/', {'einladungsfrist_tage': '1'}).status_code, 404)
        self.assertFalse(StwegVorgaben.objects.exists())
