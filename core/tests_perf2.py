"""Tiefen-Profil der langsamsten /neu/-Seiten.

Teil 1 zeigt pro Route, wohin die Zeit geht: Summe der SQL-Zeit gegen die in
Python verbrachte Zeit, plus die teuerste Einzelabfrage. Teil 2 misst dieselbe
Route bei doppelter Datenmenge — wächst die Zeit überproportional, ist es ein
algorithmisches Problem und keine konstante Last.

    python manage.py test core.tests_perf2 -v0
"""
import cProfile
import io
import pstats
import os
import time

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from unittest import skipUnless
from django.test.utils import CaptureQueriesContext
from django.db import connection

from core.tests_perf import _seed

VERDAECHTIG = ['/neu/debitoren/', '/neu/bankabgleich/', '/neu/', '/neu/assets/',
               '/neu/mahnwesen/', '/neu/finanzen/', '/neu/objekte/']


def _login():
    grp, _ = Group.objects.get_or_create(name='Verwaltung')
    u = User.objects.create_user(username='perf2', password='x')
    u.groups.add(grp)
    c = Client()
    c.force_login(u)
    return c


@skipUnless(os.environ.get("PERF"), "Messwerkzeug — mit PERF=1 starten")
class TiefenProfil(TestCase):

    def test_wohin_geht_die_zeit(self):
        _seed()
        c = _login()
        print(f"\n{'='*78}\nZEITVERTEILUNG — SQL gegen Python\n{'='*78}")
        print(f"{'gesamt':>8} {'SQL':>8} {'Python':>8} {'Q':>4}   Route")
        print('-' * 78)
        langsam = []
        for route in VERDAECHTIG:
            with CaptureQueriesContext(connection) as ctx:
                t0 = time.perf_counter()
                c.get(route, secure=True)
                gesamt = (time.perf_counter() - t0) * 1000
            sql_ms = sum(float(q['time']) for q in ctx.captured_queries) * 1000
            py_ms = gesamt - sql_ms
            print(f'{gesamt:>7.0f}ms {sql_ms:>7.0f}ms {py_ms:>7.0f}ms {len(ctx.captured_queries):>4}   {route}')
            teuerste = sorted(ctx.captured_queries, key=lambda q: -float(q['time']))[:2]
            langsam.append((route, teuerste))

        print(f"\n{'-'*78}\nTEUERSTE EINZELABFRAGEN\n{'-'*78}")
        for route, qs in langsam:
            for q in qs:
                ms = float(q['time']) * 1000
                if ms >= 5:
                    print(f'{ms:>7.0f}ms  {route}\n           {q["sql"][:160]}')

    def test_cprofile_langsamste(self):
        _seed()
        c = _login()
        for route in ['/neu/debitoren/', '/neu/bankabgleich/']:
            c.get(route, secure=True)          # warmlaufen (Template-Kompilierung)
            pr = cProfile.Profile()
            pr.enable()
            c.get(route, secure=True)
            pr.disable()
            s = io.StringIO()
            pstats.Stats(pr, stream=s).sort_stats('cumulative').print_stats(18)
            print(f"\n{'='*78}\ncPROFILE  {route}\n{'='*78}")
            for zeile in s.getvalue().splitlines():
                if 'swissImmo' in zeile or 'django/' in zeile or 'ncalls' in zeile:
                    print(zeile[:150])

    def test_skalierung(self):
        """Doppelte Datenmenge: linear (ok) oder überproportional (Problem)?"""
        import core.tests_perf as P
        c = _login()
        print(f"\n{'='*78}\nSKALIERUNG\n{'='*78}")
        messwerte = {}
        for faktor, monate in [(1, 12), (2, 24)]:
            from finance.models import DebitorenRechnung
            from portfolio.models import Liegenschaft
            Liegenschaft.objects.all().delete()
            DebitorenRechnung.objects.all().delete()
            P.MONATE = monate
            _seed()
            n = DebitorenRechnung.objects.count()
            for route in ['/neu/debitoren/', '/neu/mahnwesen/', '/neu/mieterkonten/']:
                # Einzelmessungen schwanken auf geteilter Hardware um Faktor 2–3
                # (Cache, Scheduler). Median aus mehreren Läufen nach einem
                # Warmlauf — sonst misst man Rauschen statt Skalierung.
                c.get(route, secure=True)
                proben = []
                for _ in range(7):
                    t0 = time.perf_counter()
                    c.get(route, secure=True)
                    proben.append((time.perf_counter() - t0) * 1000)
                proben.sort()
                messwerte.setdefault(route, []).append((n, proben[len(proben) // 2]))
        P.MONATE = 12
        print(f"{'Route':<26} {'klein':>16} {'doppelt':>16}   Faktor")
        print('-' * 78)
        for route, werte in messwerte.items():
            (n1, t1), (n2, t2) = werte
            f = t2 / t1 if t1 else 0
            warnung = '  ⚠ überproportional' if f > 2.4 else ''
            print(f'{route:<26} {n1:>6}R {t1:>7.0f}ms {n2:>6}R {t2:>7.0f}ms   {f:>4.1f}×{warnung}')
