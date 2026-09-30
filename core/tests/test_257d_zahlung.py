"""Zahlung innert der 257d-Frist beendet Frist und Fall — sofort.

DAS SZENARIO

1. Der Mieter gerät in Zahlungsverzug (Miete seit 35 Tagen fällig, offen).
2. Die Verwaltung setzt die Zahlungsfrist mit Kündigungsandrohung an
   (Art. 257d Abs. 1 OR, 30 Tage bei Wohnräumen). Frist-Pendenz und Fall
   «Zahlungsverzug» sind aktiv.
3. Der Mieter bezahlt den Rückstand innert der Frist vollständig.

Dann MUSS gelten: Frist erledigt, Fall abgeschlossen, keine Anzeige mehr als
laufende Frist, und eine Kündigung wegen Zahlungsverzugs wird abgewiesen.
Eine Frist, die nach der Zahlung weiter «läuft», lädt zu einer Kündigung ein,
die unwirksam wäre (Art. 257d Abs. 2 OR setzt Nichtzahlung voraus).

GEGENPROBE

Ausgeführt am 30.09.2026:

· Signal-Empfänger in `finance/signals.py` abgehängt → 8 von 11 rot
  (alle, die eine Zahlung buchen, ausser der Kündigung, die dann an der noch
  laufenden Frist scheitert — was ebenfalls richtig ist).
· Arbeitsvorrat-Filter auf offene Fälle entfernt, Überwachungsschritt nicht
  erledigt und `kuendigung_sperre` abgeschaltet → die jeweils zugehörigen
  4 Tests rot.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user


class Verzug257dZahlungTests(TestCase):

    def setUp(self):
        from finance.models import DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        call_command('fallarten_anlegen', verbosity=0)
        self.heute = date.today()
        self.rechnung = DebitorenRechnung.objects.create(
            vertrag=self.v, liegenschaft=self.lg, einheit=self.e,
            titel='Miete & NK 08/2026', datum=self.heute - timedelta(days=40),
            faellig_am=self.heute - timedelta(days=35),
            betrag=Decimal('1700.00'), status='offen')
        self.c = Client()
        self.c.force_login(_team_user())

    # -- Hilfen -------------------------------------------------------------
    def _frist_ansetzen(self):
        from core.models import Pendenz
        r = self.c.post(f'/neu/vertraege/{self.v.id}/verzug/', {
            'frist_bis': (self.heute + timedelta(days=37)).isoformat()})
        self.assertEqual(r.status_code, 302)
        return Pendenz.objects.get(vertrag=self.v, quelle=f'257d:{self.v.pk}')

    def _fall(self):
        from django.contrib.contenttypes.models import ContentType
        from faelle.models import Fall
        return Fall.objects.get(
            akte_typ=ContentType.objects.get_for_model(self.v),
            akte_id=self.v.pk, fallart__schluessel='zahlungsverzug')

    def _zahlen(self, betrag, am=None, rechnung=None):
        """Wie der Bankabgleich: Zahlungseingang anlegen, dann Status setzen."""
        from finance.models import Zahlungseingang
        r = rechnung or self.rechnung
        Zahlungseingang.objects.create(
            vertrag=self.v, debitoren_rechnung=r, betrag=Decimal(betrag),
            datum_eingang=am or self.heute, bemerkung='camt.053')
        r.status = 'bezahlt' if r.offener_betrag <= 0 else 'teilbezahlt'
        r.save(update_fields=['status'])

    def _kuendigen_wegen_verzug(self):
        return self.c.post(f'/neu/vertraege/{self.v.id}/kuendigen/', {
            'absender': 'vermieter', 'ausserordentlich': 'on',
            'ausserordentlich_grund': 'Zahlungsverzug (Art. 257d OR)',
            'eingang_datum': self.heute.isoformat(),
            'gewuenschtes_ende': (self.heute + timedelta(days=60)).isoformat(),
        })

    # -- Das Szenario ---------------------------------------------------------
    def test_zahlung_innert_frist_archiviert_frist_und_fall(self):
        from faelle.models import Fall

        # Schritt 2: Frist und Fall sind aktiv.
        p = self._frist_ansetzen()
        self.assertFalse(p.erledigt)
        self.assertGreaterEqual(p.faellig_am, self.heute + timedelta(days=30),
                                'Weniger als 30 Tage — Art. 257d Abs. 1 OR verletzt.')
        fall = self._fall()
        self.assertEqual(fall.status, Fall.OFFEN)
        ueberwachen = fall.schritte.get(bezeichnung='Fristablauf überwachen')
        self.assertEqual(ueberwachen.frist, p.faellig_am)
        self.assertIsNone(ueberwachen.erledigt_am)

        # Schritt 3: vollständige Zahlung innert Frist.
        self._zahlen('1700.00', am=self.heute + timedelta(days=10))

        p.refresh_from_db()
        self.assertTrue(p.erledigt, 'Die 257d-Frist läuft nach vollständiger Zahlung weiter.')
        self.assertEqual(p.erledigt_am, self.heute)
        self.assertIn('ausgeschlossen', p.beschreibung)

        fall.refresh_from_db()
        self.assertEqual(fall.status, Fall.ABGESCHLOSSEN,
                         'Der Zahlungsverzugsfall bleibt nach der Zahlung offen.')
        self.assertIsNotNone(fall.abgeschlossen_am)
        ueberwachen.refresh_from_db()
        self.assertIsNotNone(ueberwachen.erledigt_am,
                             'Der Überwachungsschritt steht weiter mit Frist im Arbeitsvorrat.')

    def test_erledigte_frist_erscheint_nirgends_mehr_als_laufend(self):
        from core.models import Pendenz
        from core.services.zahlungsverzug import aktive_fristen
        from faelle.arbeitsvorrat import _fallschritte, _pendenzen

        p = self._frist_ansetzen()
        bis = p.faellig_am + timedelta(days=1)
        self.assertTrue(any(z['objekt'].pk == p.pk for z in _pendenzen(self.heute, bis)))

        self._zahlen('1700.00')

        self.assertFalse(aktive_fristen(self.v).exists())
        self.assertFalse(Pendenz.objects.filter(pk=p.pk, erledigt=False).exists())
        self.assertFalse(any(z['objekt'].pk == p.pk for z in _pendenzen(self.heute, bis)),
                         'Die erledigte Frist steht weiter im Arbeitsvorrat.')
        self.assertFalse(
            any(getattr(z['objekt'], 'bezeichnung', '') == 'Fristablauf überwachen'
                for z in _fallschritte(self.heute, bis)),
            'Der Schritt des abgeschlossenen Falls steht weiter im Arbeitsvorrat.')
        akte = self.c.get(f'/neu/vertraege/{self.v.id}/')
        self.assertEqual(akte.status_code, 200)
        self.assertNotIn(p, [e['p'] for e in akte.context['vertrag_pendenzen']])

    def test_kuendigung_nach_zahlung_wird_abgewiesen(self):
        from rentals.models import Kuendigung
        self._frist_ansetzen()
        self._zahlen('1700.00')
        r = self._kuendigen_wegen_verzug()
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Kuendigung.objects.filter(vertrag=self.v).exists(),
                         'Nach rechtzeitiger Zahlung wurde trotzdem wegen Verzugs gekündigt.')
        self.v.refresh_from_db()
        self.assertEqual(self.v.status, 'aktiv')

    # -- Die Grenzen --------------------------------------------------------
    def test_teilzahlung_laesst_frist_aktiv(self):
        p = self._frist_ansetzen()
        self._zahlen('1000.00')
        p.refresh_from_db()
        self.assertFalse(p.erledigt, 'Eine Teilzahlung wahrt die Frist nicht.')
        self.assertEqual(self._fall().status, 'offen')
        self._zahlen('700.00')
        p.refresh_from_db()
        self.assertTrue(p.erledigt)

    def test_zahlung_nach_fristablauf_schliesst_nicht_stillschweigend(self):
        """Nach Fristablauf besteht das Kündigungsrecht weiter — Entscheid, kein Automat."""
        p = self._frist_ansetzen()
        type(p).objects.filter(pk=p.pk).update(faellig_am=self.heute - timedelta(days=1))
        self._zahlen('1700.00', am=self.heute)
        p.refresh_from_db()
        self.assertFalse(p.erledigt)
        self.assertIn('Nach Fristablauf bezahlt', p.beschreibung)
        self._zahlen_nochmal_ist_idempotent(p)

    def _zahlen_nochmal_ist_idempotent(self, p):
        self.rechnung.save(update_fields=['status'])
        p.refresh_from_db()
        self.assertEqual(p.beschreibung.count('Nach Fristablauf bezahlt'), 1)

    def test_spaeter_faellige_miete_haelt_die_frist_nicht_offen(self):
        """Die nächste Monatsmiete braucht eine eigene Fristansetzung."""
        from finance.models import DebitorenRechnung
        p = self._frist_ansetzen()
        DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Miete & NK 10/2026', datum=self.heute + timedelta(days=5),
            faellig_am=self.heute + timedelta(days=5), betrag=Decimal('1700.00'), status='offen')
        self._zahlen('1700.00')
        p.refresh_from_db()
        self.assertTrue(p.erledigt)

    def test_offene_mahngebuehr_haelt_die_frist_nicht_offen(self):
        """Art. 257d nennt Mietzinse und Nebenkosten — nicht Mahngebühren."""
        from finance.models import DebitorenRechnung
        DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Mahngebühr', datum=self.heute - timedelta(days=5),
            faellig_am=self.heute - timedelta(days=5), betrag=Decimal('20.00'),
            status='offen', stammrechnung=self.rechnung)
        p = self._frist_ansetzen()
        self._zahlen('1700.00')
        p.refresh_from_db()
        self.assertTrue(p.erledigt)

    def test_kuendigung_waehrend_laufender_frist_wird_abgewiesen(self):
        from rentals.models import Kuendigung
        self._frist_ansetzen()
        self._kuendigen_wegen_verzug()
        self.assertFalse(Kuendigung.objects.filter(vertrag=self.v).exists(),
                         'Kündigung vor Fristablauf wäre unwirksam.')

    def test_kuendigung_nach_unbenuetztem_ablauf_bleibt_moeglich(self):
        """Die Sperre darf den legitimen Fall nicht verhindern."""
        from rentals.models import Kuendigung
        p = self._frist_ansetzen()
        type(p).objects.filter(pk=p.pk).update(faellig_am=self.heute - timedelta(days=1))
        self._kuendigen_wegen_verzug()
        self.assertTrue(Kuendigung.objects.filter(vertrag=self.v).exists())

    def test_storno_der_forderung_beendet_die_frist(self):
        p = self._frist_ansetzen()
        self.rechnung.status = 'storniert'
        self.rechnung.save(update_fields=['status'])
        p.refresh_from_db()
        self.assertTrue(p.erledigt)

    def test_alte_frist_ohne_quelle_wird_ebenfalls_erkannt(self):
        """Vor dieser Änderung angelegte Fristen tragen keine `quelle`."""
        from core.models import Pendenz
        p = Pendenz.objects.create(
            titel=f'Art. 257d: Zahlungsfrist läuft ab – {self.m.display_name}',
            kategorie='frist', faellig_am=self.heute + timedelta(days=20), vertrag=self.v)
        self._zahlen('1700.00')
        p.refresh_from_db()
        self.assertTrue(p.erledigt)
