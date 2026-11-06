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

from django.core.cache.backends.filebased import FileBasedCache
from django.core.cache.backends.locmem import LocMemCache
from django.test import SimpleTestCase, override_settings

from swiss_immo.cache_config import caches_fuer


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
