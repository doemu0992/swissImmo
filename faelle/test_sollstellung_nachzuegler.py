"""Nachzügler-Vertrag nach dem Monatslauf: Die Seite bietet keinen Knopf an, der abgelehnt wird.

Befund aus dem Arbeitstag-Test (e2e/tests/arbeitstag.spec.ts): Der Lauf der Periode war
abgeschlossen, ein neuer Vertrag wartete noch. Die Seite zeigte «Sollstellung starten (1)»,
und `fw_sollstellung_run` lehnte den Klick ab (Sperre gegen Doppelausführung). Die Sperre
bleibt — die Seite nennt jetzt den Grund und den Weg.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import Client
from django.utils import timezone

from faelle.lauf_models import Lauf
from faelle.test_monatsabschluss import PERIODE, _Basis


class NachzueglerTests(_Basis):
    def _seite(self):
        return self.c.get('/neu/sollstellung/', {'jahr': timezone.localdate().year,
                                                 'monat': timezone.localdate().month})

    def test_vor_dem_lauf_gibt_es_den_startknopf(self):
        antwort = self._seite()
        self.assertContains(antwort, '/neu/sollstellung/starten/')
        self.assertNotContains(antwort, 'soll-gesperrt')

    def test_nach_dem_lauf_mit_nachzuegler_steht_der_grund_statt_des_knopfs(self):
        from crm.models import Mieter
        from rentals.models import Mietvertrag
        from portfolio.models import Einheit
        self.sollstellung()
        self.assertEqual(self.lauf('sollstellung').status, Lauf.ABGESCHLOSSEN)
        # Nachzügler: neuer Vertrag, der nach dem Lauf entsteht.
        e2 = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='2.5 Zi', typ='whg',
                                    nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
        m2 = Mieter.objects.create(typ='person', vorname='Nina', nachname='Nachzuegler', email='n@example.ch')
        Mietvertrag.objects.create(mieter=m2, einheit=e2, beginn=timezone.localdate().replace(day=1) - timedelta(days=0),
                                   netto_mietzins=Decimal('1000'), nebenkosten=Decimal('100'), status='aktiv')
        antwort = self._seite()
        self.assertContains(antwort, 'soll-gesperrt')
        self.assertContains(antwort, f'/neu/laeufe/{self.lauf("sollstellung").pk}/#lauf-zuruecksetzen')
        self.assertNotContains(antwort, 'action="/neu/sollstellung/starten/"')

    def test_gegenprobe_die_sperre_selbst_bleibt_bestehen(self):
        self.sollstellung()
        antwort = self.sollstellung()                    # zweiter Start wird weiter abgelehnt
        self.assertIn('bereits abgeschlossen', ' '.join(str(m) for m in antwort.context['messages']))
