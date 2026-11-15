"""Betreiber-Portal: das Protokoll (alle Quellen auf einer Seite) und die rote Zahl in der Leiste."""
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AbrufStatus, SicherheitsEreignis
from core.services import betreiber_protokoll as protokoll


def _zeile(stufe, logger, text, vor_minuten=5):
    zeit = timezone.localtime(timezone.now() - timedelta(minutes=vor_minuten))
    return f'{zeit:%Y-%m-%d %H:%M:%S},123 {stufe} {logger}: {text}'


class AusLogTests(SimpleTestCase):

    def test_fehler_und_warnungen_info_nicht(self):
        e = protokoll.aus_log([_zeile('ERROR', 'django.request', 'Internal Server Error: /neu/'),
                               _zeile('WARNING', 'tickets', 'Keine Adresse'),
                               _zeile('INFO', 'core', 'Lauf fertig'), 'irgendeine Zeile'])
        self.assertEqual(sorted((x['stufe'], x['ort']) for x in e), [('fehler', 'django.request'), ('warnung', 'tickets')])

    def test_gleiche_meldung_mit_anderer_nummer_ist_ein_eintrag(self):
        e = protokoll.aus_log([_zeile('WARNING', 't', 'Ticket #3: keine Adresse'), _zeile('WARNING', 't', 'Ticket #4: keine Adresse'),
                               _zeile('WARNING', 't', 'etwas anderes')])
        self.assertEqual(sorted(x['anzahl'] for x in e), [1, 2])

    def test_traceback_haengt_am_fehler_und_zeigt_das_ende(self):
        e = protokoll.aus_log([_zeile('ERROR', 'django.request', 'Internal Server Error: /neu/'),
                               'Traceback (most recent call last):', '  File "x.py", line 1', 'ValueError: kaputt',
                               _zeile('INFO', 'core', 'weiter'), 'gehört nicht dazu'])
        self.assertEqual(len(e), 1)
        self.assertIn('ValueError: kaputt', e[0]['detail'])
        self.assertNotIn('gehört nicht dazu', e[0]['detail'])

    def test_abgebrochene_verbindung_ist_eine_warnung_mit_erklaerung(self):
        """«OSError: write error» schreibt der Webserver, wenn der Browser die Verbindung schliesst: kein Fehler der Anwendung."""
        e = protokoll.aus_log([_zeile('ERROR', 'root', 'OSError: write error'), _zeile('ERROR', 'root', 'OSError: write error'),
                               _zeile('ERROR', 'root', 'OSError: etwas anderes')])
        nach_titel = {x['titel']: x for x in e}
        self.assertEqual((nach_titel['OSError: write error']['stufe'], nach_titel['OSError: write error']['anzahl']), ('warnung', 2))
        self.assertIn('Verbindung geschlossen', nach_titel['OSError: write error']['detail'])
        self.assertEqual(nach_titel['OSError: etwas anderes']['stufe'], 'fehler')            # Gegenprobe

    def test_wartungsmodus_beim_einspielen_ist_eine_warnung(self):
        e = protokoll.aus_log([_zeile('ERROR', 'core.wartung', 'WARTUNGSMODUS: 1 Migration(en) nicht angewendet: core.0028_auftrag. '
                                      'Beheben mit: python manage.py migrate'),
                               _zeile('ERROR', 'core.wartung', 'WARTUNGSMODUS: Datenbank nicht erreichbar')])
        stufen = {('Migration' in x['titel']): x['stufe'] for x in e}
        self.assertEqual(stufen[True], 'warnung')
        self.assertEqual(stufen[False], 'fehler')                         # Gegenprobe: anderes aus dem Wartungsmodus bleibt Fehler
        self.assertIn('migrate', next(x['detail'] for x in e if x['stufe'] == 'warnung'))

    def test_csp_meldungen_derselben_ursache_sind_eine_zeile(self):
        def z(seite, zusatz=''):
            return _zeile('WARNING', 'csp', f'CSP-Verstoss: style-src-attr | blockiert=inline | Seite={seite} | Zeile=1{zusatz}')
        probe = ' | Quelle= | Probe=text-overflow:inherit @ select'
        e = protokoll._csp([z('https://x.ch/neu/', probe), z('https://x.ch/neu/', probe), z('https://x.ch/neu/laeufe/', probe),
                            z('https://x.ch/neu/', ' | Quelle= | Probe=color:red @ div')])
        self.assertEqual(sorted((x['detail'], x['anzahl'], x['ort']) for x in e), [
            ('color:red @ div', 1, 'https://x.ch/neu/'), ('text-overflow:inherit @ select', 3, '2 Seiten')])

    def test_csp_zeilen_stehen_nicht_unter_anwendung(self):
        z = _zeile('WARNING', 'csp', 'CSP-Verstoss: style-src-attr | blockiert=inline | Seite=https://x.ch/neu/ | Zeile=1')
        self.assertEqual(protokoll.aus_log([z]), [])


class SeiteTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / 'swissimmo.log'
        ue = override_settings(LOGGING={'handlers': {'file': {'filename': str(self.log)}}})
        ue.enable()
        self.addCleanup(ue.disable)
        self.betreiber = get_user_model().objects.create_superuser('betreiber', 'b@example.ch', 'x' * 12)
        self.c = Client()
        self.c.force_login(self.betreiber)
        self.url = reverse('fw_betreiber_protokoll')

    def _schreiben(self, *zeilen):
        self.log.write_text('\n'.join(zeilen) + '\n', encoding='utf-8')
        cache.delete(f'betreiber-protokoll-zahl:{self.betreiber.pk}')

    def test_nur_der_betreiber(self):
        normal = Client()
        normal.force_login(get_user_model().objects.create_user('nm', 'nm@example.ch', 'x' * 12))
        self.assertEqual(normal.get(self.url).status_code, 403)
        self.assertEqual(Client().get(self.url).status_code, 302)
        self.assertEqual(self.c.get(self.url).status_code, 200)

    def test_alle_quellen_stehen_auf_einer_seite(self):
        self._schreiben(_zeile('ERROR', 'django.request', 'Internal Server Error: /neu/kaputt/'),
                        _zeile('WARNING', 'csp', 'CSP-Verstoss: style-src-attr | blockiert=inline | Seite=https://x.ch/neu/ | Zeile=1'))
        AbrufStatus.objects.create(name='lik', letzter_versuch=timezone.now(), letzter_fehler='HEV nicht erreichbar',
                                   fehler_in_folge=3)
        SicherheitsEreignis.objects.create(aktion='Schlüssel erneuert', objekt='Betreiber')
        r = self.c.get(self.url)
        for text in ('Internal Server Error: /neu/kaputt/', 'style-src-attr', 'HEV nicht erreichbar', 'Schlüssel erneuert'):
            self.assertContains(r, text)
        self.assertEqual({e['quelle'] for e in r.context['eintraege']} >= {'anwendung', 'csp', 'abruf', 'sicherheit'}, True)

    def test_filter_nach_quelle_und_stufe(self):
        self._schreiben(_zeile('ERROR', 'a', 'Fehler eins'), _zeile('WARNING', 'b', 'Warnung zwei'))
        SicherheitsEreignis.objects.create(aktion='Anmeldung', objekt='x')
        nur_fehler = self.c.get(self.url, {'stufe': 'fehler'})
        self.assertContains(nur_fehler, 'Fehler eins')
        self.assertNotContains(nur_fehler, 'Warnung zwei')
        nur_sicherheit = self.c.get(self.url, {'quelle': 'sicherheit'})
        self.assertContains(nur_sicherheit, 'Anmeldung')
        self.assertNotContains(nur_sicherheit, 'Fehler eins')
        self.assertContains(self.c.get(self.url, {'quelle': 'gibtsnicht'}), 'Fehler eins')      # unbekannter Filter = keiner

    def test_export_folgt_dem_filter_und_wird_vermerkt(self):
        self._schreiben(_zeile('ERROR', 'a', '=SUMME(A1) Fehler eins'), _zeile('WARNING', 'b', 'Warnung zwei'))
        self.assertContains(self.c.get(self.url, {'stufe': 'fehler'}), '?export=csv&amp;stufe=fehler')
        r = self.c.get(self.url, {'export': 'csv', 'stufe': 'fehler'})
        self.assertEqual(r['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="protokoll-', r['Content-Disposition'])
        text = r.content.decode('utf-8-sig')
        self.assertTrue(text.startswith('Zuletzt;Stufe;Quelle;Meldung;Ort;Detail;Anzahl'))
        self.assertIn('Fehler eins', text)
        self.assertNotIn('Warnung zwei', text)                                   # der Filter gilt auch für die Datei
        self.assertNotIn(';=SUMME', text)                                        # keine Formel in der Zelle
        e = SicherheitsEreignis.objects.get(aktion='Betreiber-Protokoll exportiert')
        self.assertIn('1 Einträge', e.details)
        self.assertIn('Stufe: fehler', e.details)

    def test_export_nur_fuer_den_betreiber_und_ohne_gesehen(self):
        self._schreiben(_zeile('ERROR', 'a', 'Fehler eins'))
        normal = Client()
        normal.force_login(get_user_model().objects.create_user('nm3', 'nm3@example.ch', 'x' * 12))
        self.assertEqual(normal.get(self.url, {'export': 'csv'}).status_code, 403)
        self.assertEqual(self.c.get(self.url, {'export': 'csv'}).status_code, 200)
        self.assertEqual(protokoll.fehlerzahl(self.betreiber), 1)                # ein Export ist kein Ansehen

    def test_ohne_eintraege_ein_ruhiger_hinweis(self):
        r = self.c.get(self.url, {'stufe': 'fehler'})
        self.assertContains(r, 'data-testid="protokoll-leer"')
        self.assertNotContains(r, 'data-testid="protokoll-tabelle"')

    def test_die_rote_zahl_zaehlt_neue_fehler_und_verschwindet_nach_dem_ansehen(self):
        start = reverse('betreiber')
        self.assertNotContains(self.c.get(start), 'data-testid="protokoll-zahl"')               # nichts los: keine Pille
        self._schreiben(_zeile('ERROR', 'a', 'Fehler eins'), _zeile('ERROR', 'b', 'Fehler zwei'),
                        _zeile('WARNING', 'c', 'nur eine Warnung'))
        r = self.c.get(start)
        self.assertContains(r, 'data-testid="protokoll-zahl"')
        self.assertEqual(protokoll.fehlerzahl(self.betreiber), 2)                               # Warnungen zählen nicht
        self.assertContains(self.c.get(self.url), 'data-testid="protokoll-neu"')                # ansehen …
        self.assertEqual(protokoll.fehlerzahl(self.betreiber), 0)                               # … und die Zahl ist weg
        self.assertNotContains(self.c.get(start), 'data-testid="protokoll-zahl"')

    def test_am_telefon_steht_die_zahl_auch_im_kopf(self):
        """Die Leiste liegt am Telefon hinter dem Menüknopf: Ohne die Zahl im Kopf sähe der Betreiber dort nichts."""
        self._schreiben(_zeile('ERROR', 'a', 'Fehler eins'))
        self.assertContains(self.c.get(reverse('betreiber')), 'data-testid="protokoll-zahl-kopf"')
        self._schreiben(_zeile('WARNING', 'a', 'nur eine Warnung'))
        cache.clear()
        self.assertNotContains(self.c.get(reverse('betreiber')), 'data-testid="protokoll-zahl-kopf"')

    def test_ein_abrufausfall_zaehlt_solange_er_besteht(self):
        s = AbrufStatus.objects.create(name='lik', letzter_versuch=timezone.now() - timedelta(days=30),
                                       letzter_fehler='HEV nicht erreichbar', fehler_in_folge=2)
        self.c.get(self.url)                                                                    # gesehen
        self.assertEqual(protokoll.fehlerzahl(self.betreiber), 1)                               # zählt trotzdem
        s.fehler_in_folge = 0
        s.save()
        cache.delete(f'betreiber-protokoll-zahl:{self.betreiber.pk}')
        self.assertEqual(protokoll.fehlerzahl(self.betreiber), 0)

    def test_alte_logzeilen_fallen_aus_dem_fenster(self):
        self._schreiben(_zeile('ERROR', 'a', 'uralter Fehler', vor_minuten=60 * 24 * (protokoll.FENSTER_TAGE + 2)),
                        _zeile('ERROR', 'b', 'frischer Fehler'))
        r = self.c.get(self.url)
        self.assertContains(r, 'frischer Fehler')
        self.assertNotContains(r, 'uralter Fehler')

    def test_die_leiste_zeigt_anderen_keine_zahl(self):
        self._schreiben(_zeile('ERROR', 'a', 'Fehler eins'))
        from core.templatetags.betreiber_tags import betreiber_fehlerzahl
        normal = get_user_model().objects.create_user('nm2', 'nm2@example.ch', 'x' * 12)
        self.assertEqual(betreiber_fehlerzahl({'request': type('A', (), {'user': normal})()}), 0)
        self.assertEqual(betreiber_fehlerzahl({'request': type('A', (), {'user': self.betreiber})()}), 1)
