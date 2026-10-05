"""Phase-1-Audit: Basis-Strukturen für Ticket-Zuweisung/SLA, NK-Zustellung
(Einsprachefrist) und Betreibung des Mietzinses."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext
from core.tests._helfer import _basis_objekte, _seed_konten, _team_user, _test_organisation


class TicketSlaTests(TestCase):
    def setUp(self):
        _seed_konten()
        self.org = _test_organisation()
        self.lg, self.einheit, self.mieter, self.vertrag = _basis_objekte()

    def _ticket(self, prio, **kw):
        from tickets.models import SchadenMeldung
        return SchadenMeldung.objects.create(liegenschaft=self.lg, titel='Wasser', beschreibung='x',
                                             prioritaet=prio, **kw)

    def test_faelligkeit_folgt_der_prioritaet(self):
        heute = timezone.localdate()
        self.assertEqual(self._ticket('notfall').faellig_bis, heute)
        self.assertEqual(self._ticket('hoch').faellig_bis, heute + timedelta(days=2))
        self.assertEqual(self._ticket('mittel').faellig_bis, heute + timedelta(days=7))
        # Unbekannter Altwert fällt auf «mittel», nicht auf «keine Frist».
        self.assertEqual(self._ticket('irgendwas').faellig_bis, heute + timedelta(days=7))

    def test_manuelle_frist_wird_nicht_ueberschrieben(self):
        t = self._ticket('hoch', faellig_bis=date(2030, 1, 1))
        self.assertEqual(t.faellig_bis, date(2030, 1, 1))

    def test_zuweisung_und_ueberfaellig(self):
        from tickets.sla import ist_ueberfaellig
        u = _team_user('Sachbearbeiter')
        t = self._ticket('mittel', zugewiesen_an=u)
        self.assertEqual(u.zugewiesene_tickets.count(), 1)
        self.assertFalse(ist_ueberfaellig(t))
        self.assertTrue(ist_ueberfaellig(t, heute=t.faellig_bis + timedelta(days=1)))
        t.status = 'erledigt'
        self.assertFalse(ist_ueberfaellig(t, heute=t.faellig_bis + timedelta(days=1)))


class NkZustellungTests(TestCase):
    def setUp(self):
        _seed_konten()
        self.org = _test_organisation()
        self.lg, *_ = _basis_objekte()

    def test_einsprachefrist_beginnt_mit_der_zustellung(self):
        from finance.models import AbrechnungsPeriode
        p = AbrechnungsPeriode.objects.create(liegenschaft=self.lg, bezeichnung='NK 2025',
                                              start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        self.assertIsNone(p.einsprache_bis)        # ohne Zustelldatum keine Frist
        p.versendet_am = date(2026, 3, 1)
        self.assertEqual(p.einsprache_bis, date(2026, 3, 31))


class BetreibungTests(TestCase):
    def setUp(self):
        from finance.models import DebitorenRechnung
        _seed_konten()
        self.org = _test_organisation()
        _lg, _e, _m, self.v = _basis_objekte()
        self.r = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Miete 02/2026', betrag=Decimal('1700'),
            datum=date(2026, 2, 1), faellig_am=date(2026, 2, 28), status='offen')

    def test_fristen_nach_schkg(self):
        from finance.models import Betreibung
        b = Betreibung.objects.create(debitoren_rechnung=self.r, vertrag=self.v, forderung=Decimal('1700'))
        self.assertIsNone(b.rechtsvorschlag_frist_bis)
        b.zahlungsbefehl_am = date(2026, 5, 1)
        self.assertEqual(b.rechtsvorschlag_frist_bis, date(2026, 5, 11))      # Art. 74 SchKG
        self.assertEqual(b.fortsetzung_frist, (date(2026, 5, 21), date(2027, 5, 1)))  # Art. 88 SchKG

    def test_organisation_wird_abgeleitet_und_getrennt(self):
        from crm.models import Organisation
        from finance.models import Betreibung
        b = Betreibung.objects.create(debitoren_rechnung=self.r, forderung=Decimal('1700'))
        self.assertEqual(b.organisation_id, self.org.pk)
        fremd = Organisation.objects.create(firma='Fremde AG')
        with organisation_kontext(fremd):
            self.assertEqual(Betreibung.objects.count(), 0)     # fremder Mandant sieht nichts
        with organisation_kontext(self.org):
            self.assertEqual(Betreibung.objects.count(), 1)
