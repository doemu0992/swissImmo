"""Eine teilbezahlte Kreditorenrechnung kommt mit ihrem OFFENEN Rest in die Zahlungsdatei.

Audit 17.11.2026 (F5): Der Vorschlag zeigte und summierte teilbezahlte Rechnungen, die Datei nahm nur «freigegeben» auf
(still, ohne Meldung), und `pain001` schrieb den vollen Rechnungsbetrag statt des offenen Rests. Der Rest war über den
Zahllauf nie zahlbar, und eine aufgenommene Rechnung hätte die Bank zu viel überweisen lassen.
"""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from ._helfer import _basis_objekte, _seed_konten, _team_user


class ZahllaufTeilbezahltTests(TestCase):

    def setUp(self):
        from crm.models import Organisation
        from finance.models import KreditorenRechnung, KreditorenZahlung
        _seed_konten()
        self.lg, _e, _m, _v = _basis_objekte()
        org = self.lg.organisation
        org.iban = 'CH9300762011623852957'
        org.save()
        heute = timezone.localdate()
        self.kr = KreditorenRechnung.objects.create(
            lieferant='Teil AG', betrag=Decimal('1000.00'), status='freigegeben', iban='CH9300762011623852957',
            datum=heute, faellig_am=heute, liegenschaft=self.lg, referenz='R-T',
            lieferant_ort='Zürich', lieferant_land='CH')
        KreditorenZahlung.objects.create(kreditor=self.kr, betrag=Decimal('400.00'), datum=heute)
        self.kr.status = 'teilbezahlt'
        self.kr.save(update_fields=['status'])
        self.c = Client()
        self.c.force_login(_team_user())

    def _datei(self):
        return self.c.post('/neu/zahllauf/', {'aktion': 'datei', 'rechnung_ids': [self.kr.pk],
                                              'ausfuehrungsdatum': timezone.localdate().isoformat()})

    def test_datei_enthaelt_den_offenen_rest(self):
        r = self._datei()
        self.assertTrue(r.get('Content-Type', '').startswith('application/xml'), 'Die teilbezahlte Rechnung fehlt in der Datei')
        xml = r.content.decode()
        self.assertIn('600.00', xml)
        self.assertNotIn('1000.00', xml, 'Der volle Rechnungsbetrag steht in der Datei')
        self.kr.refresh_from_db()
        self.assertEqual(self.kr.status, 'in_zahlung')

    def test_gegenprobe_bezahlte_rechnung_kommt_nicht_in_die_datei(self):
        from finance.models import KreditorenZahlung
        KreditorenZahlung.objects.create(kreditor=self.kr, betrag=Decimal('600.00'), datum=timezone.localdate())
        self.kr.status = 'bezahlt'
        self.kr.save(update_fields=['status'])
        r = self._datei()
        self.assertFalse(r.get('Content-Type', '').startswith('application/xml'))
