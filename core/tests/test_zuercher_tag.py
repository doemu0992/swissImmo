"""SICH-24 / SICH-45: Der Zürcher Kalendertag, nicht der UTC-Tag.

BEFUND (Audit 28.10.2026)
- 13 `DateField`s hatten `default=timezone.now` (UTC-Datum-mit-Uhrzeit im Speicher, Zürcher Datum
  in der Datenbank): `TypeError: can't compare datetime.datetime to datetime.date`, sobald eine
  Buchung ohne Datum in eine gesperrte Periode fiel; zwischen 00:00 und 01:00 (Sommer: 02:00)
  das Datum des Vortags.
- `.date()` auf einem aware Zeitstempel liefert den UTC-Tag: Aufbewahrungsfrist von Bewerbungen,
  «offen seit» im Schadenkopf, Rollenübersicht der Person.

Die Uhr steht in jedem Test fest (`mock.patch` auf `django.utils.timezone.now`), die Tests hängen
also nicht von der Tageszeit des Laufs ab.

Gegenprobe: In `core/zeit.py` `localdate()` durch `now()` ersetzen, bzw. in
`bewerbung_aufbewahrung.entschieden_am` `localtime(...)` entfernen — die Tests werden rot.
"""
from datetime import date, datetime, timezone as utc
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.zeit import datum_heute

# 28.10.2026, 00:30 in Zürich (CET, UTC+1) — in UTC noch der 27.10., 23:30.
NACH_MITTERNACHT = datetime(2026, 10, 27, 23, 30, tzinfo=utc.utc)


def _uhr(jetzt):
    return mock.patch('django.utils.timezone.now', return_value=jetzt)


class DatumVorgabeTests(SimpleTestCase):
    def test_datum_heute_ist_ein_date_und_der_zuercher_tag(self):
        with _uhr(NACH_MITTERNACHT):
            heute = datum_heute()
        self.assertEqual(heute, date(2026, 10, 28))
        self.assertNotIsInstance(heute, datetime)

    def test_alle_datumsfelder_mit_vorgabe_liefern_ein_date(self):
        """Wächter: Kein `DateField` mit `default=timezone.now` — das wäre wieder ein datetime."""
        from django.apps import apps
        from django.db import models
        schlecht = []
        for modell in apps.get_models():
            for feld in modell._meta.get_fields():
                if isinstance(feld, models.DateField) and not isinstance(feld, models.DateTimeField):
                    if feld.default is timezone.now:
                        schlecht.append(f'{modell._meta.label}.{feld.name}')
        self.assertEqual(schlecht, [])

    def test_modellvorgabe_ist_der_zuercher_tag(self):
        from finance.models import Buchung
        with _uhr(NACH_MITTERNACHT):
            vorgabe = Buchung._meta.get_field('datum').get_default()
        self.assertEqual(vorgabe, date(2026, 10, 28))
        self.assertNotIsInstance(vorgabe, datetime)


class UtcTagTests(TestCase):
    """`.date()` auf aware Zeitstempeln im Produktionscode."""

    def setUp(self):
        from core.tests._helfer import _basis_objekte
        self.lg, self.e, self.m, self.v = _basis_objekte()

    def test_aufbewahrung_nimmt_den_zuercher_tag_der_absage(self):
        from core.services.bewerbung_aufbewahrung import entschieden_am
        from mietprozess.models import Mietbewerbung
        b = Mietbewerbung(status='abgelehnt', aktualisiert_am=NACH_MITTERNACHT)
        self.assertEqual(entschieden_am(b), date(2026, 10, 28))     # nicht der 27.

    def test_offen_seit_im_schadenkopf_nimmt_den_zuercher_tag(self):
        from django.test import Client
        from core.tests._helfer import _team_user
        from tickets.models import SchadenMeldung
        t = SchadenMeldung.objects.create(liegenschaft=self.lg, titel='Heizung', beschreibung='x')
        SchadenMeldung.objects.filter(pk=t.pk).update(erstellt_am=NACH_MITTERNACHT)
        c = Client()
        c.force_login(_team_user('Verwalter'))
        # Jetzt: 30.10. mittags. Gemeldet am 28.10. (Zürcher Tag) = vor 2 Tagen, nicht 3.
        with _uhr(datetime(2026, 10, 30, 11, 0, tzinfo=utc.utc)):
            kontext = c.get(f'/neu/schaeden/{t.pk}/').context
        self.assertEqual(kontext['offen_seit'], 2)
