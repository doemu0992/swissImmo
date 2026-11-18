"""Die Zähler gelten für alle Prozesse (Analysebericht 06.11.2026).

Ohne `CACHES` zählte jeder Worker für sich: Bei vier Workern verdoppelte sich das Login-Limit effektiv, und eine
Sperre griff nur, wenn die nächste Anfrage zufällig beim selben Worker landete. `caches_fuer` legt den Cache im
Betrieb in ein gemeinsames Verzeichnis.

Gegenproben: in `caches_fuer` für `testing=False` wieder `LocMemCache` zurückgeben -> `test_zwei_worker_sehen_denselben_zaehler`
und `test_das_limit_gilt_ueber_worker_hinweg` rot; `testing=True` den Datei-Cache liefern lassen ->
`test_in_tests_bleibt_der_speicher_cache` rot.
"""
import shutil
import tempfile
import uuid
from unittest import mock

from django.core.cache.backends.filebased import FileBasedCache
from django.core.cache.backends.locmem import LocMemCache
from django.test import SimpleTestCase, override_settings

from core.cache_config import caches_fuer


def _worker(conf, name='default'):
    """Ein eigenes Cache-Objekt, wie es ein weiterer Prozess hätte (gleiche Konfiguration, kein gemeinsamer Speicher)."""
    c = conf[name]
    if c['BACKEND'].endswith('FileBasedCache'):
        return FileBasedCache(c['LOCATION'], {'TIMEOUT': c['TIMEOUT'], 'OPTIONS': c.get('OPTIONS', {})})
    return LocMemCache(f'worker-{uuid.uuid4().hex}', {})            # je Prozess eigener Speicher


class CacheKonfigurationTests(SimpleTestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp(prefix='immo-cache-')
        self.addCleanup(shutil.rmtree, self.ordner, ignore_errors=True)

    def test_in_tests_bleibt_der_speicher_cache(self):
        conf = caches_fuer(True, self.ordner)
        self.assertTrue(conf['default']['BACKEND'].endswith('LocMemCache'))

    def test_im_betrieb_liegt_der_cache_in_dateien(self):
        conf = caches_fuer(False, self.ordner)
        self.assertTrue(conf['default']['BACKEND'].endswith('FileBasedCache'))
        self.assertTrue(conf['default']['LOCATION'].startswith(self.ordner))

    def test_das_verzeichnis_laesst_sich_setzen(self):
        conf = caches_fuer(False, self.ordner, verzeichnis='/var/tmp/gemeinsam')
        self.assertEqual(conf['default']['LOCATION'], '/var/tmp/gemeinsam')

    def test_zwei_worker_sehen_denselben_zaehler(self):
        conf = caches_fuer(False, self.ordner)
        a, b = _worker(conf), _worker(conf)
        self.assertTrue(a.add('zaehler', 1, 60))
        self.assertFalse(b.add('zaehler', 1, 60), 'Worker B sieht den Zähler von Worker A nicht')
        self.assertEqual(b.get('zaehler'), 1)

    def test_das_limit_gilt_ueber_worker_hinweg(self):
        """Der Angriff: Versuche verteilen sich auf mehrere Worker. Mit getrennten Zählern käme jeder davon."""
        conf = caches_fuer(False, self.ordner)
        workers = [_worker(conf) for _ in range(4)]
        limit = 5
        gezaehlt = 0
        for i in range(12):
            w = workers[i % 4]                    # reihum, wie ein Lastverteiler
            if not w.add('fehl:1.2.3.4', 1, 60):
                try:
                    gezaehlt = w.incr('fehl:1.2.3.4')
                except ValueError:
                    gezaehlt = 1
            else:
                gezaehlt = 1
        self.assertGreaterEqual(gezaehlt, limit, 'Die Fehlversuche wurden nicht gemeinsam gezählt')
        self.assertEqual(gezaehlt, 12)

    def test_gegenprobe_getrennte_speicher_zaehlen_getrennt(self):
        """Zeigt das Problem selbst: Zwei Speicher-Caches teilen nichts."""
        a, b = _worker(caches_fuer(True, self.ordner)), _worker(caches_fuer(True, self.ordner))
        self.assertTrue(a.add('zaehler', 1, 60))
        self.assertTrue(b.add('zaehler', 1, 60))               # B kennt den Zähler von A nicht


class DrosselTests(SimpleTestCase):
    """`rate_limit` und die Sperre aus `core/utils/throttle.py` laufen auch auf dem Datei-Cache."""

    def setUp(self):
        self.ordner = tempfile.mkdtemp(prefix='immo-cache-')
        self.addCleanup(shutil.rmtree, self.ordner, ignore_errors=True)

    def test_rate_limit_blockiert_ueber_das_limit(self):
        with override_settings(CACHES=caches_fuer(False, self.ordner)):
            from core.utils.throttle import fehlversuch, ist_gesperrt, rate_limit, zuruecksetzen
            self.assertEqual([rate_limit('t:1', 3, 60) for _ in range(5)], [True, True, True, False, False])
            for _ in range(3):
                fehlversuch('f:1', 60)
            self.assertTrue(ist_gesperrt('f:1', 3))
            zuruecksetzen('f:1')
            self.assertFalse(ist_gesperrt('f:1', 3))


class FensterTests(SimpleTestCase):
    """Das Fenster einer Bremse endet, wann es soll — auch auf dem Datei-Cache des Betriebs (Audit 15.11.2026).

    `FileBasedCache.incr` schreibt mit dem Standard-Timeout (300 s) neu. Die Zähler hielten damit im Betrieb fünf Minuten
    nach dem LETZTEN Treffer, egal welches Fenster verlangt war. Die Tests liefen auf `LocMemCache` und merkten nichts.

    Gegenprobe: in `throttle._hochzaehlen` wieder `cache.add` + `cache.incr` verwenden ->
    `test_langes_fenster_ueberlebt_die_fuenf_minuten_des_caches` und `test_kurzes_fenster_endet_trotz_dauerabfrage` rot.
    """

    def setUp(self):
        self.ordner = tempfile.mkdtemp(prefix='immo-cache-')
        self.addCleanup(shutil.rmtree, self.ordner, ignore_errors=True)
        ue = override_settings(CACHES=caches_fuer(False, self.ordner))
        ue.enable()
        self.addCleanup(ue.disable)
        self.jetzt = 1_800_000_000.0
        uhr = mock.patch('time.time', side_effect=lambda: self.jetzt)
        uhr.start()
        self.addCleanup(uhr.stop)

    def test_langes_fenster_ueberlebt_die_fuenf_minuten_des_caches(self):
        """Login-Sperre: 15 Minuten ab dem ERSTEN Fehlversuch, nicht 5 Minuten ab dem letzten."""
        from core.utils.throttle import fehlversuch, ist_gesperrt
        for _ in range(10):
            fehlversuch('login:name:anna', 900)
            self.jetzt += 1
        self.assertTrue(ist_gesperrt('login:name:anna', 10))
        self.jetzt += 400                                   # über die 300 s des Cache-Standards hinaus
        self.assertTrue(ist_gesperrt('login:name:anna', 10), 'Die Sperre endete mit dem Standard-Timeout des Caches.')
        self.jetzt += 500                                   # jetzt sind die 15 Minuten vorbei
        self.assertFalse(ist_gesperrt('login:name:anna', 10))

    def test_stundenfenster_zaehlt_ueber_die_ganze_stunde(self):
        from core.utils.throttle import rate_limit
        ergebnisse = []
        for _ in range(12):                                 # alle fünf Minuten ein Zugriff (Minute 0 bis 55), Limit 10
            ergebnisse.append(rate_limit('schaden:1.2.3.4', 10, 3600))
            self.jetzt += 300
        self.assertEqual(ergebnisse, [True] * 10 + [False, False], 'Das Stundenfenster begann zwischendurch neu.')
        self.assertTrue(rate_limit('schaden:1.2.3.4', 10, 3600))   # Minute 60: neues Fenster

    def test_kurzes_fenster_endet_trotz_dauerabfrage(self):
        """API-Schlüssel: 60 Sekunden. Mit `incr` verlängerte jede Abfrage das Fenster auf 300 s — es lief nie ab."""
        from core.utils.throttle import rate_limit
        for _ in range(5):
            rate_limit('api:token:1', 3, 60)
            self.jetzt += 10
        self.assertFalse(rate_limit('api:token:1', 3, 60))  # Sekunde 50: über dem Limit
        self.jetzt += 15                                    # Sekunde 65: neues Fenster, obwohl laufend abgefragt wurde
        self.assertTrue(rate_limit('api:token:1', 3, 60))

    def test_alte_eintraege_als_nackte_zahl_gelten_als_abgelaufen(self):
        """Nach dem Einspielen liegen noch Zähler im alten Format im Cache: Sie dürfen nichts zum Absturz bringen."""
        from django.core.cache import cache

        from core.utils.throttle import ist_gesperrt, rate_limit, stand
        cache.set('alt:1', 7, 300)
        self.assertEqual(stand('alt:1'), 0)
        self.assertFalse(ist_gesperrt('alt:1', 5))
        self.assertTrue(rate_limit('alt:1', 5, 60))
        self.assertEqual(stand('alt:1'), 1)

    def test_fehlversuch_gibt_die_anzahl_zurueck(self):
        from core.utils.throttle import fehlversuch
        self.assertEqual([fehlversuch('f:2', 60) for _ in range(3)], [1, 2, 3])
