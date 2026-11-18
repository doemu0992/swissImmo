"""Ein langer Auftrag läuft nicht doppelt, und ein überholter Lauf überschreibt das Ergebnis nicht.

Audit 17.11.2026 (K2): `_abgestuerzte_wieder_einreihen` reihte jeden Auftrag nach 30 Minuten «läuft» neu ein, auch wenn er
noch arbeitete (Rundschreiben mit über 1000 Empfängern). `beenden` prüfte weder Zustand noch Versuch.
"""
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from core.models import Auftrag
from core.services import auftraege
from core.tests._helfer import _test_organisation


class LangeAuftraegeTests(TestCase):

    def setUp(self):
        self.a = Auftrag.alle_organisationen.create(
            organisation=_test_organisation(), art='test_k2', zustand=Auftrag.ZUSTAND_LAEUFT, versuche=1,
            gestartet_am=timezone.now() - timedelta(minutes=45))
        self.addCleanup(cache.delete, auftraege.LEBENSZEICHEN_SCHLUESSEL.format(pk=self.a.pk))

    def test_auftrag_mit_lebenszeichen_wird_nicht_neu_eingereiht(self):
        auftraege._lebenszeichen_geben(self.a)
        auftraege._abgestuerzte_wieder_einreihen(timezone.now())
        self.a.refresh_from_db()
        self.assertEqual(self.a.zustand, Auftrag.ZUSTAND_LAEUFT, 'Ein arbeitender Auftrag wurde neu eingereiht')

    def test_gegenprobe_ohne_lebenszeichen_wird_neu_eingereiht(self):
        cache.delete(auftraege.LEBENSZEICHEN_SCHLUESSEL.format(pk=self.a.pk))
        auftraege._abgestuerzte_wieder_einreihen(timezone.now())
        self.a.refresh_from_db()
        self.assertEqual(self.a.zustand, Auftrag.ZUSTAND_WARTET)

    def test_ueberholter_lauf_ueberschreibt_das_ergebnis_nicht(self):
        def art(auftrag, fortschritt):
            # Während dieser Lauf arbeitet, wurde der Auftrag neu eingereiht und ein zweites Mal gestartet.
            Auftrag.alle_organisationen.filter(pk=auftrag.pk).update(versuche=2)
            return 'erster Lauf fertig'
        auftraege.ARTEN['test_k2'] = ('Test', art)
        self.addCleanup(auftraege.ARTEN.pop, 'test_k2', None)
        auftraege._ausfuehren(self.a)
        self.a.refresh_from_db()
        self.assertEqual(self.a.zustand, Auftrag.ZUSTAND_LAEUFT, 'Der überholte Lauf hat den Auftrag beendet')
        self.assertEqual(self.a.versuche, 2)
