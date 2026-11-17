"""Ein stornierter Handwerkerauftrag bleibt storniert, wenn das Ticket abgeschlossen wird.

Audit 17.11.2026 (B1): Beim Abschluss setzte `SchadenMeldung.save()` ALLE Aufträge ausser «erledigt» auf «erledigt»,
auch die stornierten. Wurde das Ticket später wieder geöffnet, sperrte der einst stornierte Auftrag (jetzt «erledigt»,
ohne Rechnung) den nächsten Abschluss.
"""
from django.test import TestCase

from ._helfer import _basis_objekte


class AbschlussLaesstStornierteInRuheTests(TestCase):

    def setUp(self):
        from crm.models import Handwerker
        from tickets.models import HandwerkerAuftrag, SchadenMeldung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        hw = Handwerker.objects.create(firma='Sanitär AG')
        self.ticket = SchadenMeldung.objects.create(liegenschaft=self.lg, titel='Leck', beschreibung='x')
        self.storniert = HandwerkerAuftrag.objects.create(ticket=self.ticket, handwerker=hw, status='storniert')
        self.offen = HandwerkerAuftrag.objects.create(ticket=self.ticket, handwerker=hw, status='offen',
                                                      ohne_rechnung_grund='kostenlos')

    def test_stornierter_auftrag_bleibt_storniert(self):
        self.ticket.status = 'erledigt'
        self.ticket.save()
        self.storniert.refresh_from_db()
        self.offen.refresh_from_db()
        self.assertEqual(self.storniert.status, 'storniert', 'Der stornierte Auftrag wurde auf «erledigt» gesetzt')
        self.assertEqual(self.offen.status, 'erledigt', 'Gegenprobe: der offene Auftrag schliesst weiter mit')

    def test_wieder_geoeffnetes_ticket_laesst_sich_erneut_abschliessen(self):
        self.ticket.status = 'erledigt'
        self.ticket.save()
        self.ticket.status = 'in_bearbeitung'
        self.ticket.save()
        self.ticket.status = 'erledigt'
        self.ticket.save()                       # wirft AbschlussGesperrt, solange der stornierte Auftrag «erledigt» ist
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'erledigt')
