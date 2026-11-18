"""«Import rückgängig» lässt keine Belastungsbuchung stehen, die beim erneuten Import doppelt gebucht würde.

Audit 17.11.2026 (F2): Storniert wurden nur Zahlungseingänge; `auszug.delete()` löschte die Auszugszeilen, deren Buchungen
(Gebühr, Lieferantenzahlung) blieben. Nach dem Re-Import war die Belastung wieder «offen» und wurde ein zweites Mal gebucht.
"""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _seed_konten, _team_user


class ImportRueckgaengigMitBelastungTests(TestCase):

    def setUp(self):
        from finance.booking import buche
        from finance.models import Bankbewegung, Buchungskonto, Kontoauszug
        _seed_konten()
        self.bank = Buchungskonto.objects.get(nummer='1020')
        self.auszug = Kontoauszug.objects.create(konto=self.bank, dateiname='camt.xml')
        self.gebuehr = buche('6800', '1020', Decimal('350.00'), 'Kontoführungsgebühr', datum=date(2026, 7, 31))
        Bankbewegung.objects.create(auszug=self.auszug, konto=self.bank, datum=date(2026, 7, 31),
                                    betrag=Decimal('-350.00'), bank_referenz='B-1', status='verbucht',
                                    buchung=self.gebuehr)
        self.c = Client()
        self.c.force_login(_team_user())

    def _rueckgaengig(self):
        return self.c.post(f'/neu/bankabgleich/auszug/{self.auszug.id}/rueckgaengig/', secure=True)

    def test_import_mit_verbuchter_belastung_bleibt_bestehen(self):
        from finance.models import Buchung, Kontoauszug
        r = self._rueckgaengig()
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Kontoauszug.objects.filter(pk=self.auszug.pk).exists(), 'Der Import wurde trotz Belastung gelöscht')
        self.assertFalse(Buchung.objects.filter(storno_von=self.gebuehr).exists())

    def test_gegenprobe_nach_dem_storno_der_belastung_geht_es(self):
        from finance.booking import storniere_buchung
        from finance.models import Kontoauszug
        storniere_buchung(self.gebuehr)
        self._rueckgaengig()
        self.assertFalse(Kontoauszug.objects.filter(pk=self.auszug.pk).exists())
