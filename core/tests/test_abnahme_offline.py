"""Abnahme vor Ort ohne Empfang: was der Server dazu beiträgt.

Das Verhalten im Browser (Schlange, Neuladen, Sperre beim Abschluss) prüft
`e2e/tests/abnahme-offline.spec.ts`; hier nur, was ohne Browser prüfbar ist.
"""
from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user


class ServiceWorkerTests(TestCase):

    def test_service_worker_ohne_anmeldung_als_javascript_ohne_cache(self):
        r = Client().get('/abnahme-sw.js')
        self.assertEqual(r.status_code, 200)
        self.assertIn('javascript', r['Content-Type'])
        self.assertEqual(r['Cache-Control'], 'no-cache')      # Updates des Workers kommen an

    def test_nur_vor_ort_seiten_und_static_werden_vorgehalten(self):
        js = Client().get('/abnahme-sw.js').content.decode()
        # Der Ausdruck ist im JS geschrieben; er muss die Vor-Ort-Seite treffen und sonst nichts
        self.assertIn(r'/^\/neu\/abnahme\/\d+\/vorort\/$/', js)
        self.assertIn("startsWith('/static/')", js)
        self.assertNotIn('/media/', js)                       # Fotos von Mietern nicht auf Vorrat
        self.assertIn('MAX_ALTER', js)                        # Mieterdaten bleiben nicht ewig

    def test_seite_meldet_den_worker_an_und_kennt_die_raumzahl(self):
        from rentals.models import Abnahmeprotokoll
        _lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/abnahme/vorort/', {'typ': 'auszug'})
        prot = Abnahmeprotokoll.objects.get(vertrag=v)
        r = c.get(f'/neu/abnahme/{prot.id}/vorort/')
        self.assertContains(r, "register('/abnahme-sw.js'")
        self.assertContains(r, 'data-raeume="')
        self.assertContains(r, 'data-msg-offline=')
