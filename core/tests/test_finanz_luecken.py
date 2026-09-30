"""Finanz-Lücken aus dem Buchhaltungs-Audit (30.09.2026).

Je Befund ein Test, der ohne den Fix rot ist:

· Mahnlauf mahnte Mahngebühren und Zinsrechnungen selbst — Gebühr auf
  Gebühr, Zins auf Zins (Art. 105 Abs. 3 OR).
· Storno einer Zahlung setzte nur die erste Rechnung zurück; eine per
  Überschuss («:ueber») bezahlte zweite blieb «bezahlt».
· «Import rückgängig» öffnete abgeschriebene Rechnungen wieder und liess das
  «:rest»-Guthaben stehen.
· Weiterverrechnung war per direktem POST auch für nicht freigegebene
  Lieferantenrechnungen möglich.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user


def _rechnung(v, titel, betrag, faellig, **extra):
    from finance.models import DebitorenRechnung
    return DebitorenRechnung.objects.create(
        vertrag=v, titel=titel, datum=faellig, faellig_am=faellig,
        betrag=Decimal(betrag), status=extra.pop('status', 'offen'), **extra)


class MahnlaufFolgeforderungTests(TestCase):

    def test_mahngebuehr_wird_nicht_selbst_gemahnt(self):
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung
        _seed_konten()
        lg, e, m, v = _basis_objekte()
        heute = date.today()
        haupt = _rechnung(v, 'Miete', '1700.00', heute - timedelta(days=70))
        gebuehr = _rechnung(v, 'Mahngebühr 2. Mahnung', '20.00',
                            heute - timedelta(days=40), stammrechnung=haupt)

        run_mahnlauf(send_email=False)

        self.assertTrue(Mahnung.objects.filter(debitoren_rechnung=haupt).exists(),
                        'Die Hauptforderung wurde nicht gemahnt — der Test prüft sonst nichts.')
        self.assertFalse(Mahnung.objects.filter(debitoren_rechnung=gebuehr).exists(),
                         'Die Mahngebühr wurde selbst gemahnt (Gebühr auf Gebühr).')
        self.assertFalse(gebuehr.folgeforderungen.exists(),
                         'Auf die Mahngebühr wurde eine weitere Gebühr gestellt.')


class ZahlungStornoGeschwisterTests(TestCase):

    def test_storno_setzt_auch_die_per_ueberschuss_bezahlte_rechnung_zurueck(self):
        from finance.models import Zahlungseingang
        lg, e, m, v = _basis_objekte()
        heute = date.today()
        a = _rechnung(v, 'Miete 08', '1000.00', heute - timedelta(days=40))
        b = _rechnung(v, 'Miete 09', '300.00', heute - timedelta(days=10))
        z = Zahlungseingang.objects.create(vertrag=v, debitoren_rechnung=a,
                                           betrag=Decimal('1000.00'), bank_referenz='REFX1')
        Zahlungseingang.objects.create(vertrag=v, debitoren_rechnung=b,
                                       betrag=Decimal('300.00'), bank_referenz='REFX1:ueber')
        a.status = 'bezahlt'; a.save(update_fields=['status'])
        b.status = 'bezahlt'; b.save(update_fields=['status'])

        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/zahlungen/{z.id}/stornieren/', {})

        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(a.status, 'offen')
        self.assertEqual(b.status, 'offen',
                         'Die über den Überschuss bezahlte Rechnung bleibt «bezahlt», '
                         'obwohl ihre Zahlung storniert ist.')


class ImportRueckgaengigTests(TestCase):

    def test_abgeschriebene_rechnung_bleibt_abgeschrieben_und_rest_verschwindet(self):
        from finance.booking import konto
        from finance.models import Bankbewegung, Kontoauszug, Zahlungseingang
        _seed_konten()
        lg, e, m, v = _basis_objekte()
        heute = date.today()
        r = _rechnung(v, 'Miete', '1700.00', heute - timedelta(days=40))
        bank = konto('1020')
        auszug = Kontoauszug.objects.create(konto=bank, dateiname='camt.xml')
        Bankbewegung.objects.create(auszug=auszug, konto=bank, datum=heute,
                                    betrag=Decimal('1500.00'), bank_referenz='UNDO9')
        Zahlungseingang.objects.create(vertrag=v, debitoren_rechnung=r,
                                       betrag=Decimal('1000.00'), bank_referenz='UNDO9')
        rest = Zahlungseingang.objects.create(vertrag=v, betrag=Decimal('500.00'),
                                              bank_referenz='UNDO9:rest')
        r.status = 'abgeschrieben'; r.save(update_fields=['status'])

        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/bankabgleich/auszug/{auszug.id}/rueckgaengig/', secure=True)

        r.refresh_from_db(); rest.refresh_from_db()
        self.assertEqual(r.status, 'abgeschrieben',
                         'Rückgängig öffnet eine abgeschriebene Rechnung wieder.')
        self.assertEqual(rest.status, 'storniert',
                         'Das «:rest»-Guthaben bleibt nach dem Rückgängig stehen.')


class WeiterverrechnungStatusTests(TestCase):

    def test_nicht_freigegebene_rechnung_wird_nicht_weiterverrechnet(self):
        from finance.booking import konto
        from finance.models import DebitorenRechnung, KreditorenRechnung
        _seed_konten()
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('500'),
                                              status='neu', liegenschaft=lg, konto=konto('4000'))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/',
               {'vertrag_id': v.id, 'betrag': '300', 'zuschlag': '0'})
        self.assertFalse(DebitorenRechnung.objects.filter(quell_kreditor=k).exists(),
                         'Eine nicht freigegebene Lieferantenrechnung wurde weiterverrechnet.')

    def test_freigegebene_rechnung_geht_weiterhin(self):
        from finance.booking import konto
        from finance.models import DebitorenRechnung, KreditorenRechnung
        _seed_konten()
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('500'),
                                              status='bezahlt', liegenschaft=lg, konto=konto('4000'))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/',
               {'vertrag_id': v.id, 'betrag': '300', 'zuschlag': '0'})
        self.assertTrue(DebitorenRechnung.objects.filter(quell_kreditor=k).exists())
