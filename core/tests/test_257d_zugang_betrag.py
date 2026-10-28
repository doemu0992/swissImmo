"""Art. 257d OR: Zugang der Fristansetzung (MIET-01), verzugsbegründende Forderungen (MIET-02) und das Fristende
auf einem Nicht-Werktag (MIET-10).

DIE RECHTSLAGE, AN DER DIESE TESTS HÄNGEN

* BGE 119 II 147 E. 2: Die Fristansetzung ist eine empfangsbedürftige Willenserklärung. Wird das Einschreiben
  abgeholt, ist der Zugang der Tag der Abholung; wird es nicht abgeholt, gilt es am letzten Tag der siebentägigen
  Abholfrist als zugegangen. Die Frist läuft NICHT ab der Abholeinladung.
* Art. 257d Abs. 1 OR: Genannt und gemahnt werden «fällige Mietzinse oder Nebenkosten», keine anderen Forderungen.
* Art. 78 Abs. 1 OR: Fällt der letzte Tag der Frist auf einen Sonntag oder Feiertag, gilt der nächste Werktag.

Die Uhr steht auf Mittwoch, 4.11.2026 (`bei_stichtag`): Die Tests rechnen mit absoluten Daten, damit sie an keinem
Wochentag anders ausfallen. Jeder Test hat seine Gegenprobe im selben Test (die alte, falsche Lesart oder der
Nachbartag).
"""
import io
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.messages import get_messages
from django.test import Client, SimpleTestCase, TestCase
from pypdf import PdfReader

from core.services import zahlungsverzug as zv
from core.services.fristen import naechster_werktag

from ._helfer import _basis_objekte, _team_user
from ._uhr import bei_stichtag

HEUTE = date(2026, 11, 4)          # Mittwoch


def _text(pdf_bytes):
    return '\n'.join(seite.extract_text() for seite in PdfReader(io.BytesIO(pdf_bytes)).pages)


class FristrechnungTests(SimpleTestCase):
    """Die Rechenfunktionen, ohne Datenbank."""

    def test_vorlaeufiges_fristende_rechnet_vom_spaetestmoeglichen_zugang(self):
        # Versand Mi 4.11. + 1 Tag Postweg + 7 Tage Abholfrist + 30 Tage = Sa 12.12. -> Mo 14.12.
        self.assertEqual(zv.provisorisches_fristende(date(2026, 11, 4)), date(2026, 12, 14))
        # Gegenprobe: die alte Rechnung (Versand + 1 + 30) endete eine Woche früher.
        self.assertLess(date(2026, 11, 4) + timedelta(days=31), zv.provisorisches_fristende(date(2026, 11, 4)))
        # Versand Do 5.11. -> So 13.12. -> Mo 14.12.
        self.assertEqual(zv.provisorisches_fristende(date(2026, 11, 5)), date(2026, 12, 14))
        # Versand Fr 6.11. -> Mo 14.12. (+38 = Mo 14.12.), bleibt
        self.assertEqual(zv.provisorisches_fristende(date(2026, 11, 6)), date(2026, 12, 14))
        # Versand Sa 7.11. -> Di 15.12.
        self.assertEqual(zv.provisorisches_fristende(date(2026, 11, 7)), date(2026, 12, 15))

    def test_fiktiver_zugang_ist_der_letzte_tag_der_abholfrist(self):
        # Abholeinladung Mo 2.11. -> Zugang Mo 9.11.
        self.assertEqual(zv.fiktiver_zugang(date(2026, 11, 2)), date(2026, 11, 9))
        # Gegenprobe: nicht die Abholeinladung selbst und nicht der Tag danach.
        self.assertNotEqual(zv.fiktiver_zugang(date(2026, 11, 2)), date(2026, 11, 2))
        self.assertNotEqual(zv.fiktiver_zugang(date(2026, 11, 2)), date(2026, 11, 3))

    def test_fiktiver_zugang_auf_samstag_oder_sonntag_rueckt_auf_montag(self):
        # Einladung Sa 24.10. + 7 = Sa 31.10. -> Mo 2.11.; So 25.10. + 7 = So 1.11. -> Mo 2.11.
        self.assertEqual(zv.fiktiver_zugang(date(2026, 10, 24)), date(2026, 11, 2))
        self.assertEqual(zv.fiktiver_zugang(date(2026, 10, 25)), date(2026, 11, 2))
        # Gegenprobe: Einladung Fr 23.10. + 7 = Fr 30.10. bleibt.
        self.assertEqual(zv.fiktiver_zugang(date(2026, 10, 23)), date(2026, 10, 30))

    def test_definitives_fristende_schaltjahr_und_wochenende(self):
        # Zugang 30.1.2024 + 30 Tage = 29.2.2024 (Schaltjahr, Donnerstag)
        self.assertEqual(zv.definitives_fristende(date(2024, 1, 30)), date(2024, 2, 29))
        # Zugang Fr 6.11.2026 + 30 = So 6.12. -> Mo 7.12.
        self.assertEqual(zv.definitives_fristende(date(2026, 11, 6)), date(2026, 12, 7))

    def test_fristende_von_hebt_zu_kurze_altdaten_an(self):
        """Eine vor dieser Korrektur angelegte Frist (Versand + 1 + 30) wird für die Sperre nachgerechnet."""
        from core.models import Pendenz
        p = Pendenz(titel='Art. 257d', versand_am=date(2026, 11, 4), faellig_am=date(2026, 12, 5),
                    frist_tage=30)
        self.assertEqual(zv.fristende_von(p), date(2026, 12, 14))
        # Gegenprobe: mit bestätigtem Zugang gilt das gespeicherte Fristende (auf den Werktag gerückt).
        p.zugang_am = date(2026, 11, 4)
        p.faellig_am = date(2026, 12, 4)
        self.assertEqual(zv.fristende_von(p), date(2026, 12, 4))
        # Ohne Fristende gibt es nichts zu rechnen.
        p.faellig_am = None
        self.assertIsNone(zv.fristende_von(p))


@bei_stichtag(HEUTE)
class FristansetzungUndZugangTests(TestCase):
    def setUp(self):
        from finance.models import DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.rechnung = DebitorenRechnung.objects.create(
            vertrag=self.v, liegenschaft=self.lg, einheit=self.e, titel='Miete & NK 10/2026',
            datum=date(2026, 10, 1), faellig_am=date(2026, 10, 1), betrag=Decimal('1700.00'),
            status='offen', forderungsart='miete')
        self.c = Client()
        self.c.force_login(_team_user())

    def _ansetzen(self, **daten):
        from core.models import Pendenz
        antwort = self.c.post(f'/neu/vertraege/{self.v.id}/verzug/', daten)
        self.assertEqual(antwort.status_code, 302)
        return Pendenz.objects.get(vertrag=self.v, quelle=f'257d:{self.v.pk}')

    def _zugang(self, p, **daten):
        return self.c.post(f'/neu/fristen/verzug/{p.pk}/zugang/', daten)

    # -- MIET-01: provisorisches Fristende und Sperre ---------------------------------------------
    def test_versand_setzt_ein_vorlaeufiges_fristende_nach_abholfrist(self):
        p = self._ansetzen(sendungsnummer='98.00.1', versand_am=HEUTE.isoformat())
        self.assertEqual(p.faellig_am, date(2026, 12, 14))
        self.assertNotEqual(p.faellig_am, HEUTE + timedelta(days=31))           # Gegenprobe: die alte Lesart
        self.assertIn('PROVISORISCH', p.beschreibung)
        self.assertIn('Abholfrist', p.beschreibung)

    def test_kuendigung_bleibt_gesperrt_solange_der_zugang_nicht_bestaetigt_ist(self):
        p = self._ansetzen(sendungsnummer='98.00.1', versand_am=HEUTE.isoformat())
        self.assertIsNone(p.zugang_am)
        # Nach der alten Rechnung (Fristende 5.12.) wäre ab dem 6.12. gekündigt worden — jetzt noch nicht.
        for tag in (date(2026, 12, 6), date(2026, 12, 7), date(2026, 12, 14)):
            with self.subTest(tag=tag):
                text = zv.kuendigung_sperre(self.v, tag)
                self.assertIn('14.12.2026', text)
                self.assertIn('nicht bestätigt', text)
        # Gegenprobe: erst nach dem vorläufigen Fristende ist die Kündigung frei.
        self.assertIsNone(zv.kuendigung_sperre(self.v, date(2026, 12, 15)))

    def test_hinweis_wenn_der_zugang_nie_bestaetigt_wurde(self):
        p = self._ansetzen(sendungsnummer='98.00.1', versand_am=HEUTE.isoformat())
        self.assertIn('nie bestätigt', zv.kuendigung_hinweis(self.v, date(2026, 12, 15)))
        self.assertIsNone(zv.kuendigung_hinweis(self.v, date(2026, 12, 10)))     # Frist läuft noch: Sperre, kein Hinweis
        # Gegenprobe: nach der Bestätigung gibt es nichts mehr zu bemerken.
        self._zugang(p, zugang_am=date(2026, 11, 5).isoformat())
        self.assertIsNone(zv.kuendigung_hinweis(self.v, date(2026, 12, 15)))

    def test_ohne_versanddatum_hat_die_vorlaeufige_frist_den_puffer(self):
        """Das Formular schlägt +37 vor, der Server verlangt mindestens 30 Tage ab dem spätestmöglichen Zugang."""
        p = self._ansetzen(frist_bis=(HEUTE + timedelta(days=37)).isoformat())
        self.assertEqual(p.faellig_am, naechster_werktag(HEUTE + timedelta(days=38)))      # Sa 12.12. -> Mo 14.12.
        self.assertGreater(p.faellig_am, HEUTE + timedelta(days=37))                        # Gegenprobe

    def test_vorlaeufiges_fristende_auf_wochenende_rueckt_auf_den_werktag(self):
        p = self._ansetzen(frist_bis=date(2026, 12, 19).isoformat())                        # Samstag
        self.assertEqual(p.faellig_am, date(2026, 12, 21))
        p.delete()
        p2 = self._ansetzen(frist_bis=date(2026, 12, 18).isoformat())                       # Freitag bleibt
        self.assertEqual(p2.faellig_am, date(2026, 12, 18))

    # -- MIET-01: Zugang bestätigen -----------------------------------------------------------------
    def test_abholung_ist_der_zugang_nicht_die_abholeinladung(self):
        p = self._ansetzen(sendungsnummer='98.00.1', versand_am=date(2026, 10, 30).isoformat())
        antwort = self._zugang(p, zugang_am=date(2026, 11, 2).isoformat(), zugang_art='abgeholt')
        self.assertEqual(antwort.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.zugang_am, date(2026, 11, 2))
        self.assertFalse(p.zugang_fingiert)
        self.assertEqual(p.faellig_am, date(2026, 12, 2))                                   # Mo 2.11. + 30 = Mi 2.12.
        self.assertIn('Zugang bestätigt', p.beschreibung)

    def test_nicht_abgeholt_fingiert_den_zugang_am_letzten_tag_der_abholfrist(self):
        p = self._ansetzen(sendungsnummer='98.00.1', versand_am=date(2026, 10, 23).isoformat())
        # Abholeinladung Mo 26.10.; nicht abgeholt; Abholfrist endete Mo 2.11.
        antwort = self._zugang(p, zugang_am=date(2026, 10, 26).isoformat(), zugang_art='nicht_abgeholt')
        self.assertEqual(antwort.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.zugang_am, date(2026, 11, 2))
        self.assertTrue(p.zugang_fingiert)
        self.assertEqual(p.faellig_am, date(2026, 12, 2))
        # Gegenprobe: ab der Abholeinladung gerechnet (der alte Fehler) wäre das Fristende der 25.11.
        self.assertNotEqual(p.faellig_am, naechster_werktag(date(2026, 10, 26) + timedelta(days=30)))
        self.assertIn('fingiert', p.beschreibung)

    def test_zustellung_am_letzten_tag_der_abholfrist_ist_moeglich_einen_tag_frueher_nicht(self):
        p = self._ansetzen(sendungsnummer='98.00.1', versand_am=date(2026, 10, 23).isoformat())
        # Einladung Mi 28.10. + 7 = Mi 4.11. = heute: Die Abholfrist läuft heute ab, der Zugang gilt heute.
        self._zugang(p, zugang_am=date(2026, 10, 28).isoformat(), zugang_art='nicht_abgeholt')
        p.refresh_from_db()
        self.assertEqual(p.zugang_am, HEUTE)
        self.assertTrue(p.zugang_fingiert)
        # Gegenprobe: Einladung Do 29.10. -> Fristende der Abholung 5.11., morgen: noch abholbar, nichts erfasst.
        p2 = self._neue_frist()
        antwort = self._zugang(p2, zugang_am=date(2026, 10, 29).isoformat(), zugang_art='nicht_abgeholt')
        p2.refresh_from_db()
        self.assertIsNone(p2.zugang_am)
        texte = ' '.join(str(m) for m in get_messages(antwort.wsgi_request))
        self.assertIn('Abholfrist läuft noch bis 05.11.2026', texte)

    def _neue_frist(self):
        from core.models import Pendenz
        Pendenz.objects.filter(vertrag=self.v, quelle__startswith='257d:').delete()
        return self._ansetzen(sendungsnummer='98.00.2', versand_am=date(2026, 10, 23).isoformat())

    def test_zugang_vor_dem_versand_wird_abgewiesen(self):
        p = self._ansetzen(sendungsnummer='98.00.1', versand_am=date(2026, 11, 2).isoformat())
        self._zugang(p, zugang_am=date(2026, 11, 1).isoformat())
        p.refresh_from_db()
        self.assertIsNone(p.zugang_am)
        # Gegenprobe: am Versandtag selbst (Abholung am gleichen Tag) ist möglich.
        self._zugang(p, zugang_am=date(2026, 11, 2).isoformat())
        p.refresh_from_db()
        self.assertEqual(p.zugang_am, date(2026, 11, 2))

    def test_zugang_in_der_zukunft_wird_auf_heute_geklemmt(self):
        p = self._ansetzen(sendungsnummer='98.00.1', versand_am=date(2026, 11, 2).isoformat())
        self._zugang(p, zugang_am=date(2026, 11, 20).isoformat())
        p.refresh_from_db()
        self.assertEqual(p.zugang_am, HEUTE)
        self.assertEqual(p.faellig_am, date(2026, 12, 4))                                   # Mi 4.11. + 30 = Fr 4.12.

    # -- Dokument am Mahnwesen-Weg --------------------------------------------------------------------
    def test_zustellung_am_dokument_kennt_die_art_des_zugangs(self):
        from rentals.models import Dokument
        self._ansetzen(sendungsnummer='98.00.1', versand_am=date(2026, 10, 23).isoformat())
        dok = Dokument.objects.filter(vertrag=self.v, bezeichnung__startswith='Zahlungsaufforderung 257d').first()
        self.assertIsNotNone(dok)
        self.c.post(f'/neu/dokument/{dok.pk}/zustellung/',
                    {'zugang_am': date(2026, 10, 26).isoformat(), 'zugang_art': 'nicht_abgeholt'})
        p = zv.aktive_fristen(self.v).get()
        self.assertEqual(p.zugang_am, date(2026, 11, 2))
        self.assertTrue(p.zugang_fingiert)
        self.assertEqual(p.faellig_am, date(2026, 12, 2))


@bei_stichtag(HEUTE)
class FristendeNichtWerktagTests(TestCase):
    """MIET-10: Eine Zahlung am nächsten Werktag nach einem Sonntags-Fristende ist rechtzeitig."""

    def setUp(self):
        from core.models import Pendenz
        from finance.models import DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.rechnung = DebitorenRechnung.objects.create(
            vertrag=self.v, liegenschaft=self.lg, einheit=self.e, titel='Miete & NK 10/2026',
            datum=date(2026, 10, 1), faellig_am=date(2026, 10, 1), betrag=Decimal('1700.00'),
            status='offen', forderungsart='miete')
        # Fristende Sonntag, 6.12.2026 (Zugang Fr 6.11. + 30 Tage).
        self.p = Pendenz.objects.create(
            titel='Art. 257d: Zahlungsfrist läuft ab', kategorie='frist', vertrag=self.v,
            quelle=f'257d:{self.v.pk}', faellig_am=date(2026, 12, 6), zugang_am=date(2026, 11, 6),
            frist_tage=30)

    def _zahlen(self, am):
        from finance.models import Zahlungseingang
        Zahlungseingang.objects.create(vertrag=self.v, debitoren_rechnung=self.rechnung,
                                       betrag=Decimal('1700.00'), datum_eingang=am)
        self.rechnung.status = 'bezahlt'
        self.rechnung.save(update_fields=['status'])
        zv.pruefe_nach_zahlung(self.v)
        self.p.refresh_from_db()

    def test_zahlung_am_montag_nach_dem_sonntags_fristende_wahrt_die_frist(self):
        self._zahlen(date(2026, 12, 7))
        self.assertTrue(self.p.erledigt, 'Zahlung am nächsten Werktag gilt als rechtzeitig (Art. 78 OR).')
        self.assertIn(zv.VERMERK_GEWAHRT, self.p.beschreibung)

    def test_zahlung_am_dienstag_ist_verspaetet(self):
        self._zahlen(date(2026, 12, 8))
        self.assertFalse(self.p.erledigt)
        self.assertIn(zv.VERMERK_LATE, self.p.beschreibung)
        self.assertIn('07.12.2026', self.p.beschreibung)          # das wirksame Fristende, nicht der Sonntag

    def test_zahlung_am_sonntag_selbst_wahrt_die_frist(self):
        self._zahlen(date(2026, 12, 6))
        self.assertTrue(self.p.erledigt)

    def test_sperre_gilt_bis_und_mit_dem_montag(self):
        self.assertIn('07.12.2026', zv.kuendigung_sperre(self.v, date(2026, 12, 7)))
        # Nach dem Sonntag wäre ohne Art. 78 der 7.12. bereits frei gewesen.
        self.assertIsNone(zv.kuendigung_sperre(self.v, date(2026, 12, 8)))

    def test_samstags_fristende_und_feiertag(self):
        from core.models import Pendenz
        self.p.faellig_am = date(2026, 12, 5)                    # Samstag
        self.p.save(update_fields=['faellig_am'])
        self.assertIn('07.12.2026', zv.kuendigung_sperre(self.v, date(2026, 12, 7)))
        # Weihnachten, Freitag 25.12.2026 -> Montag 28.12.
        self.p.faellig_am = date(2026, 12, 25)
        self.p.save(update_fields=['faellig_am'])
        self.assertIn('28.12.2026', zv.kuendigung_sperre(self.v, date(2026, 12, 28)))
        self.assertIsNone(zv.kuendigung_sperre(self.v, date(2026, 12, 29)))
        Pendenz.objects.filter(pk=self.p.pk).update(faellig_am=date(2026, 12, 4))
        self.assertIsNone(zv.kuendigung_sperre(self.v, date(2026, 12, 7)))          # Freitag: am Montag frei


@bei_stichtag(HEUTE)
class VerzugsforderungenTests(TestCase):
    """MIET-02: Die Fristansetzung nennt und summiert nur Mietzinse und Nebenkosten."""

    def setUp(self):
        from finance.models import DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.R = DebitorenRechnung
        self.c = Client()
        self.c.force_login(_team_user())
        self.miete9 = self._r('Miete & NK 09/2026', date(2026, 9, 1), '1700.00', 'miete')
        self.miete10 = self._r('Miete & NK 10/2026', date(2026, 10, 1), '1700.00', 'miete')
        self.weiter = self._r('Weiterverrechnung Reparatur Boiler', date(2026, 10, 5), '500.00', 'sonstige')
        self.selbst = self._r('Selbstbehalt Versicherungsschaden (Ticket #1)', date(2026, 10, 10), '300.00',
                              'sonstige')
        self.gebuehr = self._r('Mahngebühr 1. Mahnung', date(2026, 10, 12), '20.00', 'sonstige',
                               stamm=self.miete9)

    def _r(self, titel, faellig, betrag, art, stamm=None):
        return self.R.objects.create(
            vertrag=self.v, liegenschaft=self.lg, einheit=self.e, titel=titel, datum=faellig, faellig_am=faellig,
            betrag=Decimal(betrag), status='offen', forderungsart=art, stammrechnung=stamm)

    def test_nur_mietzins_und_nebenkosten_sind_verzugsforderungen(self):
        titel = [r.titel for r in zv.verzugsforderungen(self.v, HEUTE)]
        self.assertEqual(titel, ['Miete & NK 09/2026', 'Miete & NK 10/2026'])
        # Gegenprobe: ohne die Art (alle ohne Stammrechnung) wären es vier gewesen.
        self.assertEqual(self.R.objects.filter(vertrag=self.v, stammrechnung__isnull=True).count(), 4)
        self.assertEqual(zv.faelliger_rueckstand(self.v, HEUTE), Decimal('3400.00'))

    def test_seite_zeigt_summe_der_miete_und_nennt_das_ausgenommene(self):
        antwort = self.c.get(f'/neu/vertraege/{self.v.id}/verzug/')
        self.assertEqual(antwort.context['offen_total'], Decimal('3400.00'))
        self.assertEqual(antwort.context['ausgenommen_total'], Decimal('820.00'))
        self.assertEqual(antwort.context['ausgenommen_anzahl'], 3)
        self.assertContains(antwort, 'Nicht Teil der Fristansetzung')
        self.assertContains(antwort, 'Miete &amp; NK 09/2026')

    def test_brief_nennt_jeden_monat_und_nur_die_miete(self):
        antwort = self.c.post(f'/neu/vertraege/{self.v.id}/verzug/',
                              {'frist_bis': (HEUTE + timedelta(days=40)).isoformat(), 'als_pdf': '1'})
        self.assertEqual(antwort.status_code, 200)
        text = _text(antwort.content)
        self.assertIn('Miete & NK 09/2026', text)
        self.assertIn('Miete & NK 10/2026', text)
        self.assertIn('Total: CHF 3400.00', text)
        for fremd in ('Boiler', 'Selbstbehalt', 'Mahngebühr 1', '500.00'):
            self.assertNotIn(fremd, text, f'«{fremd}» gehört nicht in die Androhung (Art. 257d OR).')
        from core.models import Pendenz
        p = Pendenz.objects.get(vertrag=self.v, quelle=f'257d:{self.v.pk}')
        self.assertIn('CHF 3400.00', p.beschreibung)

    def test_viele_monate_stehen_auf_der_beilage(self):
        for monat in (5, 6, 7, 8):
            self._r(f'Miete & NK {monat:02d}/2026', date(2026, monat, 1), '1700.00', 'miete')
        antwort = self.c.post(f'/neu/vertraege/{self.v.id}/verzug/',
                              {'frist_bis': (HEUTE + timedelta(days=40)).isoformat(), 'als_pdf': '1'})
        text = _text(antwort.content)
        self.assertIn('Aufstellung der ausstehenden Beträge', text)
        for monat in (5, 6, 7, 8, 9, 10):
            self.assertIn(f'Miete & NK {monat:02d}/2026', text)
        self.assertIn('10200.00', text)                          # 6 x 1700
        # Gegenprobe: bei drei Monaten bleibt es im Brieftext, ohne Beilage.
        from core.models import Pendenz
        Pendenz.objects.all().delete()
        for r in self.R.objects.filter(titel__in=[f'Miete & NK {m:02d}/2026' for m in (5, 6, 7)]):
            r.status = 'storniert'
            r.save(update_fields=['status'])
        antwort = self.c.post(f'/neu/vertraege/{self.v.id}/verzug/',
                              {'frist_bis': (HEUTE + timedelta(days=40)).isoformat(), 'als_pdf': '1'})
        self.assertNotIn('Aufstellung der ausstehenden Beträge', _text(antwort.content))

    def test_ohne_miete_im_rueckstand_keine_fristansetzung(self):
        from core.models import Pendenz
        from rentals.models import Dokument
        for r in (self.miete9, self.miete10):
            r.status = 'bezahlt'
            r.save(update_fields=['status'])
        antwort = self.c.post(f'/neu/vertraege/{self.v.id}/verzug/', {'frist_bis': '2026-12-20'})
        self.assertEqual(antwort.status_code, 302)
        self.assertFalse(Pendenz.objects.filter(vertrag=self.v, quelle__startswith='257d:').exists())
        self.assertFalse(Dokument.objects.filter(vertrag=self.v, bezeichnung__startswith='Zahlungsaufforderung').exists())
        texte = ' '.join(str(m) for m in get_messages(antwort.wsgi_request))
        self.assertIn('keinen fälligen Rückstand', texte)
        # Gegenprobe: mit einer offenen Miete wird die Frist angesetzt.
        self.miete10.status = 'offen'
        self.miete10.save(update_fields=['status'])
        self.c.post(f'/neu/vertraege/{self.v.id}/verzug/', {'frist_bis': '2026-12-20'})
        self.assertTrue(Pendenz.objects.filter(vertrag=self.v, quelle__startswith='257d:').exists())

    def test_zahlung_der_miete_wahrt_die_frist_auch_wenn_selbstbehalt_offen_bleibt(self):
        from finance.models import Zahlungseingang
        self.c.post(f'/neu/vertraege/{self.v.id}/verzug/', {'frist_bis': '2026-12-20'})
        p = zv.aktive_fristen(self.v).get()
        for r in (self.miete9, self.miete10):
            Zahlungseingang.objects.create(vertrag=self.v, debitoren_rechnung=r, betrag=r.betrag,
                                           datum_eingang=HEUTE + timedelta(days=3))
            r.status = 'bezahlt'
            r.save(update_fields=['status'])
        p.refresh_from_db()
        self.assertTrue(p.erledigt)
        # Gegenprobe: Der Selbstbehalt und die Weiterverrechnung sind weiter offen.
        self.weiter.refresh_from_db()
        self.assertEqual(self.weiter.status, 'offen')

    def test_letzte_mahnstufe_einer_nebenforderung_fuehrt_nicht_zur_androhung(self):
        self.assertIsNone(zv.eskalation_257d(self.weiter))
        self.assertIsNone(zv.eskalation_257d(self.selbst))
        # Gegenprobe: bei der Miete entsteht die Pendenz «Fristansetzung prüfen».
        pendenz = zv.eskalation_257d(self.miete10)
        self.assertIsNotNone(pendenz)
        self.assertIn('Fristansetzung prüfen', pendenz.titel)

    def test_mahnbrief_der_letzten_stufe_droht_nur_bei_miete_mit_der_kuendigung(self):
        from core.services.mahnbrief import mahnbrief_pdf
        org = self.v.organisation
        miete = _text(mahnbrief_pdf(self.v, org, stufe=3, monat='10/2026', betrag='1700.00', datum=HEUTE,
                                    letzte_stufe=True, rechnung=self.miete10))
        self.assertIn('Zahlungsverzug gemäss Art. 257d OR', miete)
        for r in (self.weiter, self.selbst):
            with self.subTest(titel=r.titel):
                text = _text(mahnbrief_pdf(self.v, org, stufe=3, monat='10/2026', betrag=str(r.betrag), datum=HEUTE,
                                           letzte_stufe=True, rechnung=r))
                self.assertNotIn('Zahlungsverzug gemäss Art. 257d OR', text)

    def test_brief_ohne_positionen_bleibt_wie_bisher(self):
        """Die Mahnstufe mit Kündigungsandrohung (eine Forderung) ruft den Brief ohne Positionen."""
        from core.views.email_views import generate_mahnung_combined_pdf_bytes
        pdf = generate_mahnung_combined_pdf_bytes(self.v, self.v.organisation, '09/2026', '1700.00', HEUTE)
        text = _text(pdf)
        self.assertIn('Monat 09/2026 noch ein Betrag von CHF 1700.00', text.replace('\n', ' '))
        self.assertIn('Eigenhändige Unterschrift', text)


class BestandEinordnenTests(TestCase):
    """Die Datenmigration `finance.0054`: nur die beiden bekannten Mietwege bleiben «Mietzins/Nebenkosten»."""

    def test_nur_sollstellung_und_nk_nachzahlung_bleiben_miete(self):
        import importlib

        from django.apps import apps

        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        migration = importlib.import_module('finance.migrations.0054_debitorenrechnung_forderungsart')

        def neu(titel, **kw):
            return DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=lg, einheit=e, titel=titel, betrag=Decimal('100'),
                datum=date(2026, 10, 1), faellig_am=date(2026, 10, 1), forderungsart='miete', **kw)

        sollstellung = neu('Miete & NK 10/2026')
        nk = neu('NK-Abrechnung Nachzahlung - HNK 2025')
        selbst = neu('Selbstbehalt Versicherungsschaden (Ticket #3)')
        schluss = neu('Schlussabrechnung (Nachzahlung)')
        mahn = neu('Mahngebühr 1. Mahnung', stammrechnung=sollstellung)
        frei = neu('Reparatur Dusche')
        migration.bestand_einordnen(apps, None)
        art = {r.pk: r.forderungsart for r in DebitorenRechnung.objects.filter(vertrag=v)}
        self.assertEqual(art[sollstellung.pk], 'miete')
        self.assertEqual(art[nk.pk], 'miete')
        for r in (selbst, schluss, mahn, frei):
            self.assertEqual(art[r.pk], 'sonstige', r.titel)
