"""Datenreset (SICH-03, Audit 28.10.2026): atomar, vollständig, gesichert, bestätigt.

Der Befund: Der Reset löschte Buchungen, Zahlungen UND das Audit-Log, liess aber
Debitorenrechnungen und Fälle stehen (inkonsistenter Rest), lief ohne
Transaktion, ohne Sicherung und ohne erneute Anmeldung. `DatenResetTests` in
`test_plattform.py` prüft die Grundfunktion (mit Passwort und Sicherungs-Stub);
hier steht, was SICH-03 verlangt.

GEGENPROBEN (28.10.2026, je einzeln eingebaut, rot gesehen, zurückgebaut):
  * Passwortprüfung in `fw_datenreset` entfernt   → `test_falsches_passwort…` rot
  * Prüfung des zweiten Faktors entfernt          → `test_zweiter_faktor…` rot
  * Aufruf von `sicherung_erstellen` entfernt     → `test_ohne_gelungene_sicherung…` rot
  * `transaction.atomic()` um `setze_zurueck` entfernt → `test_fehler_mitten_im_reset…` rot
  * `'faelle'` aus `EIGENE_APPS` genommen         → `test_kein_inkonsistenter_rest` rot
  * `'core.AktivitaetsLog'` aus `BEHALTEN` genommen → `test_audit_log_bleibt` rot
"""
from unittest.mock import patch

from django.apps import apps
from django.core.cache import cache
from django.core.management.base import CommandError
from django.test import Client, TestCase
from django.utils import timezone

from ._isolation import MandantenFixture


class DatenresetBasis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        cache.clear()               # der Reset zählt Versuche je Benutzer
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def reset(self, passwort='geheim-egal', sicherung='ok', **extra):
        """POST an den Reset. `sicherung`: 'ok' | 'fehler' | 'echt' (ruft den Dienst)."""
        daten = {'bestaetigung': 'LÖSCHEN', 'passwort': passwort, **extra}
        if sicherung == 'echt':
            return self.c.post('/neu/datenreset/', daten)
        ziel = 'core.services.datenreset.sicherung_erstellen'
        if sicherung == 'fehler':
            from core.services.datenreset import ResetFehler
            with patch(ziel, side_effect=ResetFehler('Platte voll')):
                return self.c.post('/neu/datenreset/', daten)
        with patch(ziel, return_value='') as stub:
            antwort = self.c.post('/neu/datenreset/', daten)
            self.stub = stub
            return antwort

    def zeilen(self, fx):
        """Zeilen je Modell für eine Organisation — nur Modelle, die der Reset leert."""
        from core.services.datenreset import betroffene_modelle
        return {m._meta.label: m._base_manager.filter(organisation=fx.organisation).count()
                for m in betroffene_modelle()}

    def meldungen(self, antwort):
        from django.contrib.messages import get_messages
        return [str(m) for m in get_messages(antwort.wsgi_request)]


class ErneuteAnmeldungTests(DatenresetBasis):

    def test_falsches_passwort_loescht_nichts(self):
        antwort = self.reset(passwort='falsch')
        self.assertEqual(antwort.status_code, 302)
        self.assertGreater(self.zeilen(self.a)['portfolio.Liegenschaft'], 0,
                           'Der Reset lief trotz falschem Passwort.')
        self.assertIn('Passwort', ' '.join(self.meldungen(antwort)))

    def test_ohne_passwort_loescht_nichts(self):
        self.reset(passwort='')
        self.assertGreater(self.zeilen(self.a)['portfolio.Liegenschaft'], 0)

    def test_richtiges_passwort_loescht(self):
        """Gegenprobe zu den Tests oben: Sonst wäre jeder Reset-Stopp grün."""
        self.reset()
        self.assertEqual(self.zeilen(self.a)['portfolio.Liegenschaft'], 0)

    def test_zu_viele_versuche_sperren(self):
        for _ in range(5):
            self.reset(passwort='falsch')
        self.reset(passwort='geheim-egal')              # das sechste: auch mit richtigem Passwort gesperrt
        self.assertGreater(self.zeilen(self.a)['portfolio.Liegenschaft'], 0,
                           'Der Reset ist ein Passwort-Orakel ohne Versuchsgrenze.')

    def _faktor(self):
        from core.models import ZweiterFaktor
        from core.services import totp
        geheimnis = totp.geheimnis_erzeugen()
        ZweiterFaktor.objects.create(benutzer=self.a.benutzer, geheimnis=geheimnis,
                                     bestaetigt_am=timezone.now())
        return geheimnis

    def test_zweiter_faktor_ohne_code_loescht_nichts(self):
        self._faktor()
        self.reset()
        self.assertGreater(self.zeilen(self.a)['portfolio.Liegenschaft'], 0,
                           'Der Reset lief ohne den zweiten Faktor.')

    def test_zweiter_faktor_mit_falschem_code_loescht_nichts(self):
        self._faktor()
        self.reset(code='000000')
        self.assertGreater(self.zeilen(self.a)['portfolio.Liegenschaft'], 0)

    def test_zweiter_faktor_mit_richtigem_code_loescht(self):
        from core.services import totp
        geheimnis = self._faktor()
        self.reset(code=totp.code(geheimnis))
        self.assertEqual(self.zeilen(self.a)['portfolio.Liegenschaft'], 0)

    def test_formular_verlangt_das_passwort(self):
        """Die Gefahrenzone zeigt die Felder, die der Reset verlangt."""
        html = self.c.get('/neu/account/').content.decode()
        self.assertIn('name="passwort"', html)
        self.assertNotIn('name="code"', html)
        self._faktor()
        self.assertIn('name="code"', self.c.get('/neu/account/').content.decode())


class SicherungVorDemResetTests(DatenresetBasis):

    def test_ohne_gelungene_sicherung_wird_nichts_geloescht(self):
        antwort = self.reset(sicherung='fehler')
        self.assertEqual(antwort.status_code, 302)
        self.assertGreater(self.zeilen(self.a)['portfolio.Liegenschaft'], 0)
        meldung = ' '.join(self.meldungen(antwort))
        self.assertIn('Sicherung', meldung)
        self.assertIn('Platte voll', meldung)

    def test_die_sicherung_laeuft_vor_dem_loeschen(self):
        """Reihenfolge: Beim Aufruf der Sicherung ist noch alles da."""
        stand = {}

        def sicherung():
            stand.update(self.zeilen(self.a))
            return ''

        with patch('core.services.datenreset.sicherung_erstellen', side_effect=sicherung):
            self.c.post('/neu/datenreset/', {'bestaetigung': 'LÖSCHEN', 'passwort': 'geheim-egal'})
        self.assertGreater(stand['portfolio.Liegenschaft'], 0, 'Die Sicherung lief erst NACH dem Löschen.')
        self.assertEqual(self.zeilen(self.a)['portfolio.Liegenschaft'], 0)

    def test_der_dienst_ruft_den_sicherungsbefehl(self):
        from core.services import datenreset
        with patch.object(datenreset, 'call_command') as aufruf:
            datenreset.sicherung_erstellen()
        self.assertEqual(aufruf.call_args.args[0], 'sicherung')
        self.assertTrue(aufruf.call_args.kwargs.get('ohne_medien'))

    def test_ein_fehlgeschlagener_befehl_wird_zum_reset_fehler(self):
        from core.services import datenreset
        with patch.object(datenreset, 'call_command', side_effect=CommandError('pg_dump fehlgeschlagen')):
            with self.assertRaises(datenreset.ResetFehler) as ctx:
                datenreset.sicherung_erstellen()
        self.assertIn('pg_dump', str(ctx.exception))

    def test_der_echte_befehl_erzeugt_eine_gelesene_sicherung(self):
        """Ohne Stub: der Dienst ruft `manage.py sicherung` wirklich auf.

        Läuft nur, wo die Testdatenbank eine Datei ist; unter SQLite im Speicher
        fehlt dem Befehl die Quelle, unter PostgreSQL braucht er `pg_dump`.
        """
        import shutil
        import tempfile
        from pathlib import Path

        from django.db import connection

        from core.services import datenreset

        if connection.vendor == 'sqlite':
            self.skipTest('SQLite im Speicher: nichts zu sichern (siehe test_sicherung.py)')
        if not shutil.which('pg_dump'):
            self.skipTest('pg_dump fehlt')
        ziel = tempfile.mkdtemp()
        try:
            with patch.object(Path, 'home', return_value=Path(ziel)):
                datenreset.sicherung_erstellen()
            self.assertTrue(list((Path(ziel) / 'sicherungen').glob('*-db.dump')))
        finally:
            shutil.rmtree(ziel, ignore_errors=True)


class AtomarUndVollstaendigTests(DatenresetBasis):

    def test_fehler_mitten_im_reset_rollt_alles_zurueck(self):
        """Wirft das Neuaufsetzen, bleibt der GANZE Bestand erhalten.

        Vorher: ein `logger.warning` je Fehler, der Rest wurde trotzdem gelöscht.
        """
        vorher = self.zeilen(self.a)
        with patch('core.services.raumkatalog.seed_lebensdauer', side_effect=RuntimeError('kaputt')):
            antwort = self.reset()
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(self.zeilen(self.a), vorher, 'Der Reset hat halb gelöscht.')
        self.assertIn('zurückgerollt', ' '.join(self.meldungen(antwort)))

    def test_ein_loeschfehler_rollt_zurueck(self):
        vorher = self.zeilen(self.a)
        from django.db.models.query import QuerySet
        echtes = QuerySet.delete
        zaehler = {'n': 0}

        def wirft_beim_dritten(qs):
            zaehler['n'] += 1
            if zaehler['n'] == 3:
                raise RuntimeError('Plattenfehler')
            return echtes(qs)

        with patch.object(QuerySet, 'delete', wirft_beim_dritten):
            self.reset()
        self.assertEqual(self.zeilen(self.a), vorher)

    def test_kein_inkonsistenter_rest(self):
        """Nach dem Reset trägt KEIN Modell mit Organisationsspalte mehr eine Zeile von A.

        Der Befund: Debitorenrechnung und Fall blieben stehen, Buchungen waren weg.
        """
        self.reset()
        rest = {k: n for k, n in self.zeilen(self.a).items() if n}
        # Zeilen der Grunddaten (Kontenplan, Lebensdauer, Mahnstufen) sind neu aufgesetzt, nicht Rest.
        grunddaten = {'finance.Buchungskonto', 'portfolio.Lebensdauer', 'crm.MahnStufe'}
        self.assertEqual({k: n for k, n in rest.items() if k not in grunddaten}, {},
                         f'Der Reset hat Daten stehen lassen: {rest}')

    def test_alle_betriebs_apps_sind_im_reset(self):
        from core.services.datenreset import betroffene_modelle
        apps_im_reset = {m._meta.app_label for m in betroffene_modelle()}
        for erwartet in ('core', 'crm', 'finance', 'portfolio', 'rentals', 'tickets',
                         'mietprozess', 'faelle', 'stweg'):
            self.assertIn(erwartet, apps_im_reset, f'{erwartet} fehlt im Reset')

    def test_jedes_modell_mit_organisation_ist_entweder_im_reset_oder_begruendet_behalten(self):
        """Wächter: Ein neues Modell fällt nicht stumm aus dem Reset.

        Wer ein Modell mit `organisation` anlegt, ist automatisch im Reset. Wer es
        ausnimmt, trägt es mit Grund in `BEHALTEN` ein — und dieser Test sieht es.
        """
        from django.db import connection

        from core.services.datenreset import BEHALTEN, EIGENE_APPS, betroffene_modelle
        im_reset = {m._meta.label for m in betroffene_modelle()}
        vorhanden = set(connection.introspection.table_names())
        offen = []
        for m in apps.get_models():
            if m._meta.app_label not in EIGENE_APPS or m._meta.proxy or m._meta.db_table not in vorhanden:
                continue
            if not any(f.name == 'organisation' for f in m._meta.concrete_fields):
                continue
            if m._meta.label not in im_reset and m._meta.label not in BEHALTEN:
                offen.append(m._meta.label)
        self.assertEqual(offen, [])
        for label, grund in BEHALTEN.items():
            self.assertGreater(len(grund), 15, f'{label} steht ohne Begründung in BEHALTEN')
            apps.get_model(label)

    def test_der_bestand_von_b_bleibt_unberuehrt(self):
        vorher = self.zeilen(self.b)
        self.reset()
        self.assertEqual(self.zeilen(self.b), vorher, 'Der Reset von A hat Daten von B verändert.')
        # und die Gegenprobe: A ist leer
        self.assertEqual(self.zeilen(self.a)['rentals.Mietvertrag'], 0)

    def test_die_geschuetzten_verknuepfungen_blockieren_den_reset_nicht(self):
        """Verträge, Rechnungen, Abschlüsse sind PROTECT (FUNK-03): Die Reihenfolge stimmt."""
        self.assertGreater(self.zeilen(self.a)['finance.DebitorenRechnung'], 0)
        self.assertGreater(self.zeilen(self.a)['rentals.Mietvertrag'], 0)
        self.reset()
        self.assertEqual(self.zeilen(self.a)['finance.DebitorenRechnung'], 0)
        self.assertEqual(self.zeilen(self.a)['rentals.Mietvertrag'], 0)

    def test_systemvorlagen_ohne_organisation_bleiben(self):
        """`Vorlage.objects` liefert auch die Systemvorlagen (organisation IS NULL).

        Das alte `modell.objects.all().delete()` löschte sie mit — für ALLE Verwaltungen.
        """
        from crm.models import Vorlage
        system = Vorlage.alle_organisationen.create(name='Systemvorlage', organisation=self.a.organisation)
        # `save()` weist neue Vorlagen der Verwaltung des Kontexts zu; die Systemvorlage entsteht über die Migration.
        Vorlage.alle_organisationen.filter(pk=system.pk).update(organisation=None)
        self.reset()
        self.assertTrue(Vorlage.alle_organisationen.filter(pk=system.pk).exists(),
                        'Der Reset hat eine Systemvorlage gelöscht.')

    def test_konten_zwei_faktor_und_mitgliedschaft_bleiben(self):
        from core.models import ZweiterFaktor
        from crm.models import Mitgliedschaft
        ZweiterFaktor.objects.create(benutzer=self.b.benutzer, geheimnis='ABC', bestaetigt_am=timezone.now())
        self.reset()
        self.assertTrue(ZweiterFaktor.objects.filter(benutzer=self.b.benutzer).exists(),
                        'Der Reset hat den zweiten Faktor eines Kontos gelöscht.')
        self.assertTrue(Mitgliedschaft.alle_organisationen.filter(
            benutzer=self.a.benutzer, organisation=self.a.organisation).exists())
        self.assertEqual(self.c.get('/neu/account/').status_code, 200)

    def test_grunddaten_sind_neu_aufgesetzt(self):
        from crm.models import MahnStufe
        from finance.models import Buchungskonto
        from portfolio.models import Lebensdauer
        self.reset()
        for modell in (Buchungskonto, Lebensdauer, MahnStufe):
            self.assertTrue(modell.alle_organisationen.filter(organisation=self.a.organisation).exists(),
                            f'{modell.__name__} nach dem Reset leer')

    def test_die_fallmaschine_behaelt_ihre_konfiguration(self):
        from faelle.models import Fall, Fallart
        self.reset()
        self.assertTrue(Fallart.alle_organisationen.filter(organisation=self.a.organisation).exists(),
                        'Fallarten sind Konfiguration: ohne sie schlagen Mahnlauf und Mieterwechsel stumm fehl.')
        self.assertFalse(Fall.alle_organisationen.filter(organisation=self.a.organisation).exists())


class AuditLogBleibtTests(DatenresetBasis):

    def test_audit_log_bleibt(self):
        from core.models import AktivitaetsLog
        AktivitaetsLog.objects.create(organisation=self.a.organisation, benutzer=self.a.benutzer,
                                      aktion='Vertrag erstellt', objekt='V1')
        vorher = AktivitaetsLog.alle_organisationen.filter(organisation=self.a.organisation).count()
        self.assertGreater(vorher, 0)
        self.reset()
        spaeter = AktivitaetsLog.alle_organisationen.filter(organisation=self.a.organisation)
        self.assertGreaterEqual(spaeter.count(), vorher, 'Der Reset hat das Audit-Log gelöscht.')
        self.assertTrue(spaeter.filter(aktion='Vertrag erstellt').exists())
        self.assertTrue(spaeter.filter(aktion='Datenbank zurückgesetzt').exists(),
                        'Der Reset hinterlässt keine Spur im Audit-Log.')

    def test_abgelehnte_und_fehlgeschlagene_resets_stehen_im_log(self):
        from core.models import AktivitaetsLog
        self.reset(passwort='falsch')
        self.reset(sicherung='fehler')
        aktionen = set(AktivitaetsLog.alle_organisationen.filter(
            organisation=self.a.organisation).values_list('aktion', flat=True))
        self.assertIn('Datenreset abgelehnt', aktionen)
