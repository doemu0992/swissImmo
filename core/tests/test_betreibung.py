"""Betreibung (SchKG), 26.10.2026: Fristen, Verzahnung mit Mahnlauf und Zahlungen,
Pendenzen, Kosten, Verlustschein, Assistent und Datenblatt.

Jeder Test prüft eine Wirkung, die vorher fehlte: Bis dahin mahnte der Mahnlauf
betriebene Forderungen weiter, eine Zahlung tilgte die älteste statt der
betriebenen Schuld, und eine bezahlte Betreibung blieb offen stehen.
"""
import io
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from ._helfer import _basis_objekte, _seed_konten, _team_user


def _rechnung(vertrag, titel, tage_her, betrag='1700.00', **kw):
    from finance.models import DebitorenRechnung
    heute = timezone.localdate()
    return DebitorenRechnung.objects.create(
        vertrag=vertrag, titel=titel, datum=heute - timedelta(days=tage_her),
        faellig_am=heute - timedelta(days=tage_her), betrag=Decimal(betrag), status='offen', **kw)


class _Basis(TestCase):
    def setUp(self):
        _seed_konten()
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = timezone.localdate()
        self.r1 = _rechnung(self.v, 'Miete 07', 100)
        self.r2 = _rechnung(self.v, 'Miete 08', 70)
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))

    def _betreibung(self, *rechnungen, **kw):
        from finance.models import Betreibung
        haupt, *weitere = rechnungen or (self.r1,)
        b = Betreibung.objects.create(debitoren_rechnung=haupt, vertrag=self.v,
                                      forderung=sum((r.betrag for r in rechnungen or (self.r1,)), Decimal('0')),
                                      begehren_am=kw.pop('begehren_am', self.heute - timedelta(days=50)), **kw)
        b.weitere_rechnungen.set(weitere)
        return b


class FortsetzungFristTests(TestCase):
    """Art. 88 SchKG: frühestens 20 Tage / nach Rechtsöffnung; spätestens ein Jahr + Stillstand."""

    def _b(self, **kw):
        from finance.models import Betreibung
        return Betreibung(zahlungsbefehl_am=date(2026, 1, 10), **kw)

    def test_ohne_zahlungsbefehl_keine_frist(self):
        from finance.models import Betreibung
        self.assertIsNone(Betreibung().fortsetzung_frist)

    def test_ohne_rechtsvorschlag_20_tage_bis_ein_jahr(self):
        self.assertEqual(self._b().fortsetzung_frist, (date(2026, 1, 30), date(2027, 1, 10)))

    def test_rechtsvorschlag_ohne_rechtsoeffnung_sperrt_die_fortsetzung(self):
        self.assertEqual(self._b(rechtsvorschlag_am=date(2026, 1, 15)).fortsetzung_frist,
                         (None, date(2027, 1, 10)))

    def test_laufendes_rechtsoeffnungsverfahren_laesst_das_ende_offen(self):
        b = self._b(rechtsvorschlag_am=date(2026, 1, 15), rechtsoeffnung_beantragt_am=date(2026, 2, 1))
        self.assertEqual(b.fortsetzung_frist, (None, None))

    def test_entscheid_oeffnet_und_der_stillstand_verlaengert_die_jahresfrist(self):
        b = self._b(rechtsvorschlag_am=date(2026, 1, 15), rechtsoeffnung_beantragt_am=date(2026, 2, 1),
                    rechtsoeffnung_am=date(2026, 3, 3))
        # 30 Tage Stillstand (1.2.–3.3.) hängen an das Jahresende.
        self.assertEqual(b.fortsetzung_frist, (date(2026, 3, 3), date(2027, 2, 9)))

    def test_frueher_entscheid_unterschreitet_die_20_tage_nicht(self):
        b = self._b(rechtsvorschlag_am=date(2026, 1, 12), rechtsoeffnung_beantragt_am=date(2026, 1, 13),
                    rechtsoeffnung_am=date(2026, 1, 20))
        self.assertEqual(b.fortsetzung_frist[0], date(2026, 1, 30))


class MahnlaufUndUebersichtTests(_Basis):
    """Betriebene Forderungen werden nicht mehr gemahnt — weitere Monatsmieten eingeschlossen."""

    def test_mahnlauf_ueberspringt_betriebene_forderungen(self):
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung
        r3 = _rechnung(self.v, 'Miete 09', 40)
        self._betreibung(self.r1, self.r2)
        run_mahnlauf(send_email=False)
        self.assertEqual(set(Mahnung.objects.values_list('debitoren_rechnung_id', flat=True)), {r3.pk})

    def test_abgeschlossene_betreibung_sperrt_nicht_mehr(self):
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung
        self._betreibung(self.r1, status='zurueckgezogen')
        run_mahnlauf(send_email=False)
        self.assertIn(self.r1.pk, set(Mahnung.objects.values_list('debitoren_rechnung_id', flat=True)))

    def test_mahnwesen_nennt_die_betreibung_als_grund(self):
        self._betreibung(self.r1, self.r2)
        antwort = self.c.get('/neu/mahnwesen/')
        gruende = {z['r'].pk: z['grund'] for z in antwort.context['ohne_mahnfall']}
        self.assertIn('Betreibung', gruende[self.r1.pk])
        self.assertIn('Betreibung', gruende[self.r2.pk])
        self.assertNotIn(self.r1.pk, {row['r'].pk for row in antwort.context['rows']})


class AutomatischBezahltTests(_Basis):
    """Sind alle Forderungen bezahlt, steht die Betreibung von selbst auf «Bezahlt»."""

    def _bezahlen(self, r):
        from finance.models import Zahlungseingang
        Zahlungseingang.objects.create(vertrag=self.v, debitoren_rechnung=r, betrag=r.betrag,
                                       datum_eingang=self.heute)
        r.status = 'bezahlt'
        r.save()

    def test_erst_die_letzte_zahlung_schliesst_die_betreibung(self):
        b = self._betreibung(self.r1, self.r2)
        self._bezahlen(self.r1)
        b.refresh_from_db()
        self.assertEqual(b.status, 'begehren')
        self._bezahlen(self.r2)
        b.refresh_from_db()
        self.assertEqual(b.status, 'bezahlt')

    def test_abgeschlossene_betreibung_bleibt_wie_sie_ist(self):
        b = self._betreibung(self.r1, status='zurueckgezogen')
        self._bezahlen(self.r1)
        b.refresh_from_db()
        self.assertEqual(b.status, 'zurueckgezogen')


class TilgungsreihenfolgeTests(_Basis):
    """Art. 87 Abs. 1 OR: zuerst die betriebene Schuld, unter mehreren die zuerst betriebene."""

    def test_betriebene_forderung_geht_der_aelteren_vor(self):
        from core.services.zahlungszuordnung import offene_rechnungen
        self.assertEqual([r.pk for r in offene_rechnungen(self.v)], [self.r1.pk, self.r2.pk])
        self._betreibung(self.r2)
        self.assertEqual([r.pk for r in offene_rechnungen(self.v)], [self.r2.pk, self.r1.pk])

    def test_unter_mehreren_die_zuerst_betriebene(self):
        from core.services.zahlungszuordnung import offene_rechnungen
        r3 = _rechnung(self.v, 'Miete 09', 40)
        self._betreibung(r3, begehren_am=self.heute - timedelta(days=30))
        self._betreibung(self.r2, begehren_am=self.heute - timedelta(days=20))
        self.assertEqual([r.pk for r in offene_rechnungen(self.v)], [r3.pk, self.r2.pk, self.r1.pk])


class PendenzenTests(_Basis):
    """Rechtsvorschlagsfrist und Fortsetzungsbegehren als Pendenzen — nie doppelt."""

    def _speichern(self, b, **kw):
        daten = {'status': b.status, 'betreibungsamt': '', 'betreibungsnummer': '',
                 'forderung': str(b.forderung), 'zinssatz': '5.00', 'kosten': '0',
                 'begehren_am': b.begehren_am.isoformat(), 'bemerkung': '', 'forderungsgrund': ''}
        daten.update({k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in kw.items()})
        return self.c.post(f'/neu/betreibungen/{b.id}/', daten)

    def test_zahlungsbefehl_legt_die_rechtsvorschlag_pendenz_einmal_an(self):
        from core.models import Pendenz
        b = self._betreibung()
        zb = self.heute - timedelta(days=3)
        self._speichern(b, status='zahlungsbefehl', zahlungsbefehl_am=zb)
        self._speichern(b, status='zahlungsbefehl', zahlungsbefehl_am=zb)
        p = Pendenz.objects.get(quelle=f'betreibung:{b.pk}:rechtsvorschlag')
        self.assertEqual(p.faellig_am, zb + timedelta(days=10))
        self.assertFalse(p.erledigt)
        self.assertEqual(Pendenz.objects.filter(quelle__startswith=f'betreibung:{b.pk}:').count(), 2)

    def test_fortsetzungs_pendenz_traegt_frueh_und_spaet(self):
        from core.models import Pendenz
        b = self._betreibung()
        zb = self.heute - timedelta(days=30)
        self._speichern(b, status='zahlungsbefehl', zahlungsbefehl_am=zb)
        p = Pendenz.objects.get(quelle=f'betreibung:{b.pk}:fortsetzung')
        self.assertEqual(p.faellig_am, zb + timedelta(days=20))
        self.assertIn(f'{zb + timedelta(days=365):%d.%m.%Y}', p.beschreibung)

    def test_rechtsvorschlag_verschiebt_die_fortsetzung_bis_zur_rechtsoeffnung(self):
        from core.models import Pendenz
        b = self._betreibung()
        zb = self.heute - timedelta(days=30)
        self._speichern(b, status='rechtsvorschlag', zahlungsbefehl_am=zb, rechtsvorschlag_am=zb + timedelta(days=5))
        self.assertFalse(Pendenz.objects.filter(quelle=f'betreibung:{b.pk}:fortsetzung').exists())
        # Der Rechtsvorschlag ist schon erfasst — eine «Frist prüfen»-Aufgabe bliebe sinnlos offen.
        self.assertFalse(Pendenz.objects.filter(quelle=f'betreibung:{b.pk}:rechtsvorschlag', erledigt=False).exists())
        ro = self.heute - timedelta(days=2)
        self._speichern(b, status='rechtsoeffnung', zahlungsbefehl_am=zb, rechtsvorschlag_am=zb + timedelta(days=5),
                        rechtsoeffnung_beantragt_am=zb + timedelta(days=8), rechtsoeffnung_am=ro)
        self.assertEqual(Pendenz.objects.get(quelle=f'betreibung:{b.pk}:fortsetzung').faellig_am, ro)


class KostenBelastenTests(_Basis):
    """Betreibungskosten (Art. 68 SchKG) als abgeleitete Forderung — einmal, gebucht 1100/3600."""

    def test_kosten_werden_einmal_als_abgeleitete_forderung_belastet(self):
        from core.services.zahlungsverzug import faelliger_rueckstand
        from finance.models import Buchung, DebitorenRechnung
        b = self._betreibung(kosten=Decimal('73.30'))
        vorher = faelliger_rueckstand(self.v)
        self.c.post(f'/neu/betreibungen/{b.id}/kosten/')
        self.c.post(f'/neu/betreibungen/{b.id}/kosten/')
        k = DebitorenRechnung.objects.get(titel='Betreibungskosten (Art. 68 SchKG)')
        self.assertEqual((k.betrag, k.stammrechnung_id, k.vertrag_id), (Decimal('73.30'), self.r1.pk, self.v.pk))
        buchung = Buchung.objects.get(debitoren_rechnung=k)
        self.assertEqual((buchung.soll_konto.nummer, buchung.haben_konto.nummer), ('1100', '3600'))
        b.refresh_from_db()
        self.assertEqual(b.kosten_rechnung_id, k.pk)
        # Abgeleitet: zählt nicht zum Rückstand nach Art. 257d OR.
        self.assertEqual(faelliger_rueckstand(self.v), vorher)

    def test_ohne_kosten_wird_nichts_belastet(self):
        from finance.models import DebitorenRechnung
        b = self._betreibung()
        self.c.post(f'/neu/betreibungen/{b.id}/kosten/')
        self.assertFalse(DebitorenRechnung.objects.filter(titel__startswith='Betreibungskosten').exists())


class VerlustscheinTests(_Basis):
    """Verlustschein: offene Beträge über den bestehenden Abschreibungsdienst auf 3805."""

    def _daten(self, b, **kw):
        d = {'status': 'verlustschein', 'betreibungsamt': '', 'betreibungsnummer': '',
             'forderung': str(b.forderung), 'zinssatz': '5.00', 'kosten': '0', 'forderungsgrund': '',
             'begehren_am': b.begehren_am.isoformat(), 'bemerkung': '',
             'verlustschein_am': self.heute.isoformat()}
        d.update(kw)
        return d

    def test_verwalter_schreibt_mit_dem_verlustschein_ab(self):
        from finance.models import Buchung
        b = self._betreibung(self.r1, self.r2)
        self.c.post(f'/neu/betreibungen/{b.id}/', self._daten(b))
        self.r1.refresh_from_db()
        self.r2.refresh_from_db()
        self.assertEqual((self.r1.status, self.r2.status), ('abgeschrieben', 'abgeschrieben'))
        self.assertEqual(Buchung.objects.filter(soll_konto__nummer='3805').count(), 2)
        # Ein zweites Speichern im selben Stand bucht nichts doppelt.
        self.c.post(f'/neu/betreibungen/{b.id}/', self._daten(b))
        self.assertEqual(Buchung.objects.filter(soll_konto__nummer='3805').count(), 2)

    def test_sachbearbeiter_darf_den_verlustschein_nicht_setzen(self):
        from finance.models import Buchung
        b = self._betreibung(self.r1)
        c = Client()
        c.force_login(_team_user('Sachbearbeiter'))
        antwort = c.post(f'/neu/betreibungen/{b.id}/', self._daten(b))
        self.assertContains(antwort, 'status_fehler', status_code=400)
        b.refresh_from_db()
        self.r1.refresh_from_db()
        self.assertEqual((b.status, self.r1.status), ('begehren', 'offen'))
        self.assertFalse(Buchung.objects.filter(soll_konto__nummer='3805').exists())


class AssistentTests(_Basis):
    """«Betreibung einleiten»: mehrere Mieten, Summe als Vorschlag, nur eigene Forderungen."""

    def _post(self, **kw):
        d = {'betreibungsamt': 'Betreibungsamt Zürich 1', 'betreibungsnummer': '', 'forderung': '',
             'zinssatz': '5.00', 'zins_ab': '', 'forderungsgrund': '', 'begehren_am': self.heute.isoformat(),
             'bemerkung': ''}
        d.update(kw)
        return self.c.post(f'/neu/betreibungen/neu/{self.r1.id}/', d)

    def test_seite_ist_ein_assistent_mit_hilfe(self):
        antwort = self.c.get(f'/neu/betreibungen/neu/{self.r1.id}/')
        self.assertContains(antwort, 'class="fw-assistent"')
        self.assertContains(antwort, 'data-hilfebox="betreibung_einleiten"')
        self.assertContains(antwort, f'name="weitere_rechnungen" value="{self.r2.id}"')

    def test_mehrere_mieten_in_einer_betreibung_mit_summe(self):
        from finance.models import Betreibung
        self._post(weitere_rechnungen=[self.r2.id])
        b = Betreibung.objects.get()
        self.assertEqual(b.forderung, Decimal('3400.00'))
        self.assertEqual([r.pk for r in b.rechnungen()], [self.r1.pk, self.r2.pk])
        self.assertIn('Miete 07', b.forderungsgrund)
        self.assertIn('Miete 08', b.forderungsgrund)

    def test_forderung_eines_anderen_vertrags_ist_nicht_waehlbar(self):
        from crm.models import Mieter
        from finance.models import Betreibung
        from rentals.models import Mietvertrag
        m2 = Mieter.objects.create(typ='person', vorname='Eva', nachname='Fremd')
        v2 = Mietvertrag.objects.create(mieter=m2, einheit=self.e, beginn=date(2024, 1, 1),
                                        netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'),
                                        status='aktiv', kautions_betrag=Decimal('0'))
        fremd = _rechnung(v2, 'Miete fremd', 60)
        antwort = self._post(weitere_rechnungen=[fremd.id])
        self.assertEqual(antwort.status_code, 400)
        self.assertFalse(Betreibung.objects.exists())

    def test_bereits_betriebene_forderung_ist_nicht_einleitbar(self):
        from finance.models import Betreibung
        self._betreibung(self.r1)
        antwort = self._post()
        self.assertRedirects(antwort, '/neu/betreibungen/', fetch_redirect_response=False)
        self.assertEqual(Betreibung.objects.count(), 1)

    def test_einzelne_forderung_schlaegt_den_zinsbeginn_vor(self):
        antwort = self.c.get(f'/neu/betreibungen/neu/{self.r2.id}/')
        self.assertEqual(antwort.context['werte']['zins_ab'],
                         (self.r2.faellig_am + timedelta(days=1)).isoformat())


class DatenblattTests(_Basis):
    """Das PDF ist ausdrücklich eine Vorlage — mit Gläubiger, Vertreter, Schuldner, Zins und Grund."""

    def _text(self, pdf):
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf)) as d:
            return ' '.join(' '.join((s.extract_text() or '') for s in d.pages).split())

    def test_datenblatt_nennt_alle_angaben_und_ist_kein_amtliches_formular(self):
        from crm.models import Eigentuemer
        from rentals.models import Dokument
        eig = Eigentuemer.objects.create(firma_oder_name='Immo Eigentum AG', strasse='Bahnhofstr. 1',
                                         plz='8001', ort='Zürich')
        self.lg.eigentuemer = eig
        self.lg.save(update_fields=['eigentuemer'])
        b = self._betreibung(self.r1, self.r2, zins_ab=date(2026, 7, 15), forderungsgrund='Mietzins Juli und August',
                             betreibungsamt='Betreibungsamt Zürich 1')
        antwort = self.c.get(f'/neu/betreibungen/{b.id}/pdf/')
        self.assertEqual(antwort['Content-Type'], 'application/pdf')
        text = self._text(antwort.content)
        for stueck in ('Vorlage', 'NICHT das amtliche Betreibungsbegehren', 'Immo Eigentum AG',
                       'Vertreter des Gläubigers', 'Hans Muster', 'Seeweg 3', "3'400.00",
                       'Zins: 5 % seit 15.07.2026', 'Mietzins Juli und August', 'Betreibungsamt Zürich 1'):
            self.assertIn(stueck, text)
        self.assertTrue(Dokument.objects.filter(vertrag=self.v, bezeichnung__startswith='Betreibungsbegehren').exists())

    def test_vertragsakte_zeigt_die_betreibung(self):
        b = self._betreibung(self.r1)
        antwort = self.c.get(f'/neu/vertraege/{self.v.id}/')
        self.assertContains(antwort, f'/neu/betreibungen/{b.id}/')
        self.assertEqual([x.pk for x in antwort.context['betreibungen']], [b.pk])

    def test_personenakte_zeigt_betreibung_und_ratenplan(self):
        b = self._betreibung(self.r1)
        antwort = self.c.get(f'/neu/personen/{self.m.id}/')
        self.assertEqual([x.pk for x in antwort.context['person_betreibungen']], [b.pk])
        self.assertContains(antwort, f'/neu/betreibungen/{b.id}/')
        self.assertContains(antwort, f'/neu/vertraege/{self.v.id}/zahlungsvereinbarung/')


class MandantengrenzeTests(TestCase):
    """Fremde Betreibungen: 404 für PDF und Kosten, und es entsteht keine Forderung."""

    @classmethod
    def setUpTestData(cls):
        from ._isolation import MandantenFixture
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_fremde_betreibung_bleibt_unerreichbar(self):
        from finance.models import DebitorenRechnung
        Betreibung = type(self.b.betreibung)
        Betreibung.alle_organisationen.filter(pk=self.b.betreibung.pk).update(kosten=Decimal('50'))
        c = Client()
        c.force_login(self.a.benutzer)
        vorher = DebitorenRechnung.alle_organisationen.count()
        self.assertEqual(c.get(f'/neu/betreibungen/{self.b.betreibung.pk}/pdf/').status_code, 404)
        self.assertEqual(c.post(f'/neu/betreibungen/{self.b.betreibung.pk}/kosten/').status_code, 404)
        self.assertEqual(DebitorenRechnung.alle_organisationen.count(), vorher)
