"""Eine feste Uhr für Tests, die mit absoluten Kalenderdaten rechnen (SICH-45).

Ein Test, der «Abnahme am 01.10.2026, Rüge fällig am 27.10.2026» prüft, ist nur an
einem Tag im Jahr richtig, wenn die Uhr echt läuft: Am 30.06.2026 liegt der Oktober in
der Zukunft (die Ansicht lehnt das Datum ab), am 05.01.2027 ist die Frist längst vorbei.
Solche Tests laufen mit einer Uhr, die auf den Tag stehen bleibt, für den sie geschrieben
wurden — `bei_stichtag(date(2026, 10, 28))` an der Klasse.

Gepatcht wird `django.utils.timezone.now`; `localdate()`, `localtime()` und alle
`auto_now`-/`auto_now_add`-Felder rechnen darauf. Code, der `datetime.date.today()` direkt
ruft, bleibt bei der echten Uhr — dort ist ein Test mit absoluten Daten nicht zu retten und
gehört auf relative Daten umgestellt.

`freezegun` ist nicht Teil der Abhängigkeiten (neue Abhängigkeit = freigabepflichtig).
"""
from datetime import datetime, time
from unittest import mock

from django.utils import timezone


def bei_stichtag(tag, stunde=12):
    """Klassendekorator: Die Uhr steht für alle Tests der Klasse auf `tag`, `stunde` Uhr (Zürich).

    Wirkt schon in `setUpTestData` (Patch in `setUpClass`, vor dem Aufruf der Basis)."""
    jetzt = timezone.make_aware(datetime.combine(tag, time(stunde, 0)))

    def dekorieren(klasse):
        setup_alt = klasse.setUpClass.__func__
        teardown_alt = klasse.tearDownClass.__func__

        @classmethod
        def setUpClass(cls):
            cls._feste_uhr = mock.patch('django.utils.timezone.now', return_value=jetzt)
            cls._feste_uhr.start()
            try:
                setup_alt(cls)
            except BaseException:
                cls._feste_uhr.stop()
                raise

        @classmethod
        def tearDownClass(cls):
            try:
                teardown_alt(cls)
            finally:
                cls._feste_uhr.stop()

        klasse.setUpClass = setUpClass
        klasse.tearDownClass = tearDownClass
        return klasse
    return dekorieren
