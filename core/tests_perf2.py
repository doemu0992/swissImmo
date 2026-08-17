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

from django.contrib.auth import get_user_model

from django.contrib.auth.models import Group

User = get_user_model()

def _mitgliedschaft(benutzer, rolle='Verwalter'):
    """Rolle je Organisation (Etappe 4.3).

    Diese drei Perf-Module bauen ihren Benutzer selbst, statt `_team_user` aus
    `core/tests/_helfer.py` zu nehmen. Seit `hat_rolle()` die Mitgliedschaft
    liest, reicht die Django-Gruppe nicht mehr — ohne diese Zeilen antwortet
    jede gemessene View mit 403, und die Messung misst die Fehlerseite.
    """
    from crm.models import Mitgliedschaft, Organisation
    organisation = Organisation.objects.order_by('pk').first()
    if organisation is None:
        organisation = Organisation.objects.create(
            firma='Perf AG', strasse='Perfstrasse 1', plz='8000', ort='Zürich')
    # `alle_organisationen`: Die Mitgliedschaft wird angelegt, BEVOR ein
    # Mandantenkontext existiert — sie ist ja gerade das, woraus die
    # Middleware ihn später ableitet. Über `objects` wäre das ein Henne-Ei
    # und seit Etappe 6.2 ein OrganisationsFehler.
    Mitgliedschaft.alle_organisationen.get_or_create(
        benutzer=benutzer, organisation=organisation, defaults={'rolle': rolle})
    # Kontext fuer die Abfragen des Tests selbst setzen — dieselbe Rolle, die
    # `_helfer._test_organisation()` fuer die uebrigen Tests spielt. In den
    # gemessenen Views setzt ihn die Middleware je Anfrage; was der Test
    # DANEBEN abfragt (`DebitorenRechnung.objects.count()` als Referenzwert)
    # laeuft ohne Anfrage und braucht ihn hier.
    #
    # NICHT als allgemeine Bequemlichkeit verstehen: Genau dieser beilaeufig
    # gesetzte Kontext hat am 17.08.2026 acht kaputte Scheduler-Befehle
    # verdeckt. Wer einen Management-Command testet, benutzt `MandantenFixture`
    # und setzt NICHTS.
    from core.tenancy import setze_organisation
    setze_organisation(organisation)
    return organisation

from django.test import Client, TestCase
from unittest import skipUnless
from django.test.utils import CaptureQueriesContext
from django.db import connection

from core.tests_perf import _seed

VERDAECHTIG = ['/neu/debitoren/', '/neu/bankabgleich/', '/neu/', '/neu/assets/',
               '/neu/mahnwesen/', '/neu/finanzen/', '/neu/objekte/']


def _login():
    grp, _ = Group.objects.get_or_create(name='Verwalter')
    u = User.objects.create_user(username='perf2', password='x')
    u.groups.add(grp)
    _mitgliedschaft(u)
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
