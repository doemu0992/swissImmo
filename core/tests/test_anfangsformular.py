"""MIET-04 / FUNK-07: Anfangsmietzins-Formular (Art. 270 Abs. 2 OR) und MIET-05: der «bisherige Mietzins».

In den Kantonen mit Formularpflicht ohne hinterlegtes Original (ZH, BS, FR, GE, LU, ZG, teils NE/VD) erzeugte die
Vertragserstellung kein Formular und verwarf den Grund. Ohne Formular ist die Mietzinsvereinbarung nichtig
(BGE 140 III 583). Jetzt: klarer Hinweis im Assistenten und am Vertrag, eine Pendenz, und der Entwurf wird erst
aktiv, wenn der Nachweis steht («Formular extern verwendet», mit Datum). Keine Nachbildung als Ersatz.

Gegenproben stehen im Bericht (Code zurückgebaut -> der genannte Test wird rot).
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.messages import get_messages
from django.test import Client, TestCase, override_settings

from core.services import anfangsformular as af
from core.services.formularpflicht import formularpflicht_fuer_kanton

from ._helfer import Einheit, Liegenschaft, Mieter, Mietvertrag, _team_user, _test_organisation

D = Decimal
PFLICHT_OHNE_ORIGINAL = ('ZH', 'BS', 'FR', 'GE', 'LU', 'ZG')


class _Basis(TestCase):
    kanton = 'ZH'
    plz = '8000'

    def setUp(self):
        self.org = _test_organisation()
        self.lg = Liegenschaft.objects.create(organisation=self.org, strasse='Formularweg 1', plz=self.plz,
                                              ort='Ort', kanton=self.kanton, versicherungswert=D('1000000'))
        self.e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='3.5 Zi', typ='whg',
                                        nettomiete_aktuell=D('1500'))
        self.m = Mieter.objects.create(typ='person', vorname='Mia', nachname='Formular', email='mia@example.ch')
        self.c = Client()
        self.c.force_login(_team_user('Verwaltung'))

    def entwurf(self, einheit=None, **kw):
        felder = dict(mieter=self.m, einheit=einheit or self.e, beginn=date(2026, 12, 1), netto_mietzins=D('1500'),
                      nebenkosten=D('200'), status='entwurf', nk_kostenarten=['heizung', 'wasser'])
        felder.update(kw)
        return Mietvertrag.objects.create(**felder)

    def kanton_setzen(self, kanton, plz=None):
        self.lg.kanton = kanton
        if plz is not None:
            self.lg.plz = plz
        self.lg.save()
        self.e.refresh_from_db()
        self.e = Einheit.objects.get(pk=self.e.pk)

    def meldungen(self, antwort):
        return [str(m) for m in get_messages(antwort.wsgi_request)]


# ---------------------------------------------------------------------------
# Wann ist das Formular nötig, und fehlt der Nachweis?
# ---------------------------------------------------------------------------
class LageTests(_Basis):

    def test_zuerich_ohne_original_verlangt_nachweis_und_nennt_die_rechtsfolge(self):
        lage = af.anfangsformular_lage(self.e)
        self.assertTrue(lage['erforderlich'])
        self.assertTrue(lage['gesperrt'])
        self.assertEqual((lage['pflicht'], lage['grund']), ('ja', 'kein_original'))
        self.assertIn('Anfangsmietzins-Formular erforderlich (Art. 270 Abs. 2 OR, Kanton Zürich)', lage['hinweis'])
        self.assertIn('ohne Formular ist die Mietzinsvereinbarung nichtig (BGE 140 III 583)', lage['hinweis'])

    def test_jeder_pflichtkanton_ohne_original_ist_gesperrt(self):
        for kt in PFLICHT_OHNE_ORIGINAL:
            self.kanton_setzen(kt)
            lage = af.anfangsformular_lage(self.e)
            self.assertTrue(lage['gesperrt'], kt)
            self.assertEqual(lage['pflicht'], 'ja', kt)

    def test_teilweise_pflicht_neuenburg_waadt_ist_auch_gesperrt_mit_vorsichtiger_formulierung(self):
        for kt in ('NE', 'VD'):
            self.kanton_setzen(kt)
            lage = af.anfangsformular_lage(self.e)
            self.assertEqual(lage['pflicht'], 'teilweise', kt)
            self.assertTrue(lage['gesperrt'], kt)
            self.assertIn('möglicherweise erforderlich', lage['hinweis'])

    def test_bern_hat_das_original_keine_sperre(self):
        self.kanton_setzen('BE', plz='3000')
        lage = af.anfangsformular_lage(self.e)
        self.assertTrue(lage['erforderlich'])
        self.assertTrue(lage['original'])
        self.assertFalse(lage['gesperrt'])
        self.assertIn('automatisch in der Akte abgelegt', lage['hinweis'])

    def test_kantone_ohne_pflicht_sind_frei(self):
        for kt, plz in (('AG', '5000'), ('VS', '3920'), ('SG', '9000')):
            self.kanton_setzen(kt, plz=plz)
            lage = af.anfangsformular_lage(self.e)
            self.assertFalse(lage['erforderlich'], kt)
            self.assertFalse(lage['gesperrt'], kt)
            self.assertEqual(lage['hinweis'], '')

    def test_gewerbe_und_einstellplatz_sind_ausgenommen(self):
        for typ in ('gew', 'pp', 'gar'):
            self.e.typ = typ
            self.e.save()
            lage = af.anfangsformular_lage(Einheit.objects.get(pk=self.e.pk))
            self.assertFalse(lage['erforderlich'], typ)
            self.assertEqual(lage['grund'], 'kein_wohnraum', typ)

    def test_kanton_nicht_erfasst_und_plz_in_einem_pflichtkanton_ist_gesperrt(self):
        self.kanton_setzen('', plz='8000')
        lage = af.anfangsformular_lage(self.e)
        self.assertTrue(lage['gesperrt'])
        self.assertEqual(lage['grund'], 'kanton_fehlt')
        self.assertIn('Kanton der Liegenschaft ist nicht erfasst', lage['hinweis'])

    def test_kanton_nicht_erfasst_und_mehrdeutige_plz_mit_pflichtkandidat_ist_gesperrt(self):
        """1201 liegt in den Bereichen von VD und GE, beide mit Pflicht: Im Zweifel gilt die Vorsicht."""
        self.kanton_setzen('', plz='1201')
        lage = af.anfangsformular_lage(self.e)
        self.assertEqual((lage['pflicht'], lage['grund'], lage['gesperrt']), ('unklar', 'kanton_fehlt', True))

    def test_kanton_nicht_erfasst_aber_plz_in_einem_kanton_ohne_pflicht_ist_frei(self):
        self.kanton_setzen('', plz='5000')
        self.assertFalse(af.anfangsformular_lage(self.e)['erforderlich'])
        self.kanton_setzen('', plz='')
        self.assertFalse(af.anfangsformular_lage(self.e)['erforderlich'])

    def test_bestaetigung_am_vertrag_hebt_die_sperre_auf(self):
        v = self.entwurf()
        self.assertTrue(af.anfangsformular_lage(self.e, v)['gesperrt'])
        v.anfangsformular_nachweis = 'extern'
        v.anfangsformular_datum = date(2026, 11, 20)
        v.save()
        lage = af.anfangsformular_lage(self.e, v)
        self.assertTrue(lage['nachweis'])
        self.assertFalse(lage['gesperrt'])

    def test_formular_in_der_akte_gilt_als_nachweis(self):
        from core.services.ablage import ablegen
        v = self.entwurf()
        ablegen(b'%PDF-1.4 formular', 'Anfangsmietzins-Formular 01.12.2026', kategorie='vertrag', vertrag=v)
        self.assertFalse(af.anfangsformular_lage(self.e, v)['gesperrt'])
        # ein anderes Dokument zählt nicht
        v2 = self.entwurf()
        ablegen(b'%PDF-1.4 anderes', 'Hausordnung', kategorie='vertrag', vertrag=v2)
        self.assertTrue(af.anfangsformular_lage(self.e, v2)['gesperrt'])

    def test_warntext_nennt_nichtig_nicht_mangelhaft(self):
        from core.services.formular_status import formular_status
        warnung = formular_status(self.lg, 'anfangsmietzins')['warnung']
        self.assertIn('Mietzinsvereinbarung nichtig', warnung)
        self.assertIn('BGE 140 III 583', warnung)
        self.assertNotIn('mangelhaft', warnung)

    def test_warntext_in_einem_kanton_ohne_pflicht_behauptet_keine_nichtigkeit(self):
        from core.services.formular_status import formular_status
        self.kanton_setzen('AG', plz='5000')
        warnung = formular_status(self.lg, 'anfangsmietzins')['warnung']
        self.assertNotIn('nichtig', warnung)
        self.assertIn('keine Pflicht', warnung)


class RegisterTests(TestCase):
    """Das Verzeichnis der Formularpflicht, Ausgabe September 2026 (BWO)."""

    def test_pflicht_je_kanton(self):
        erwartet = {'BS': 'ja', 'BE': 'ja', 'FR': 'ja', 'GE': 'ja', 'LU': 'ja', 'ZG': 'ja', 'ZH': 'ja',
                    'NE': 'teilweise', 'VD': 'teilweise', 'VS': 'nein'}
        for kt, pflicht in erwartet.items():
            self.assertEqual(formularpflicht_fuer_kanton(kt)[0], pflicht, kt)
        self.assertEqual(formularpflicht_fuer_kanton('AG')[0], 'unbekannt')

    def test_leerwohnungsziffern_und_stand(self):
        ziffern = {'BS': '0.78 %', 'BE': '1.04 %', 'FR': '1.26 %', 'GE': '0.31 %', 'LU': '0.70 %',
                   'ZG': '0.20 %', 'ZH': '0.52 %'}
        for kt, z in ziffern.items():
            info = formularpflicht_fuer_kanton(kt)[1]
            self.assertEqual((info['leerziffer'], info['stand']), (z, '1.6.2026'), kt)
            self.assertEqual(info['stand_verzeichnis'], 'September 2026')


# ---------------------------------------------------------------------------
# Aktivieren: Status ändern, Versand, Unterschrift
# ---------------------------------------------------------------------------
class AktivierenTests(_Basis):

    def _status(self, v, neu='aktiv'):
        return self.c.post(f'/neu/vertraege/{v.id}/status/', {'status': neu}, follow=True)

    def test_entwurf_in_pflichtkanton_ohne_nachweis_wird_nicht_aktiv(self):
        v = self.entwurf()
        r = self._status(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'entwurf')
        text = ' '.join(self.meldungen(r))
        self.assertIn('BGE 140 III 583', text)
        self.assertIn('Der Vertrag bleibt Entwurf', text)

    def test_mit_nachweis_wird_er_aktiv(self):
        v = self.entwurf(anfangsformular_nachweis='extern', anfangsformular_datum=date(2026, 11, 20))
        self._status(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')

    def test_kanton_ohne_pflicht_wird_aktiv(self):
        self.kanton_setzen('AG', plz='5000')
        v = self.entwurf()
        self._status(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')

    def test_der_umweg_ueber_inaktiv_ist_zu(self):
        """Entwurf -> archiviert -> aktiv: dieselbe Sperre wie Entwurf -> aktiv."""
        v = self.entwurf()
        self._status(v, 'archiviert')
        v.refresh_from_db()
        self.assertEqual(v.status, 'archiviert')
        self._status(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'archiviert')
        v.anfangsformular_nachweis, v.anfangsformular_datum = 'extern', date(2026, 11, 20)
        v.save()
        self._status(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')

    def test_archivierter_altvertrag_ohne_nebenkostenliste_wird_nicht_daran_gehindert(self):
        self.kanton_setzen('AG', plz='5000')
        v = self.entwurf(status='archiviert', nk_kostenarten=[])
        self._status(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')

    def test_versand_zur_unterschrift_ist_gesperrt(self):
        from core.services.docuseal_service import docuseal_senden
        v = self.entwurf()
        with override_settings(DOCUSEAL_API_KEY='test-key'):
            ok, text = docuseal_senden(v)
        self.assertFalse(ok)
        self.assertIn('Versand nicht möglich', text)
        self.assertIn('BGE 140 III 583', text)

    def _unterschrieben(self, v):
        from rentals.services import verarbeite_docuseal_event
        antwort = mock.MagicMock(status_code=200, content=b'%PDF-signed')
        payload = {'event_type': 'submission.completed',
                   'data': {'name': f'Mietvertrag {v.id}', 'combined_document_url': 'https://api.docuseal.com/y.pdf'}}
        with mock.patch('rentals.services.requests.get', return_value=antwort):
            self.assertTrue(verarbeite_docuseal_event(payload))
        v.refresh_from_db()

    def test_unterschrift_aktiviert_ohne_nachweis_nicht_und_legt_eine_pendenz_an(self):
        from core.models import Pendenz
        v = self.entwurf()
        self._unterschrieben(v)
        self.assertEqual(v.sign_status, 'unterzeichnet')       # die Unterschrift bleibt eine Tatsache
        self.assertEqual(v.status, 'entwurf')
        p = Pendenz.objects.get(vertrag=v, quelle=f'auto:aktivierungssperre:{v.pk}')
        self.assertIn('BGE 140 III 583', p.beschreibung)

    def test_unterschrift_mit_nachweis_aktiviert(self):
        v = self.entwurf(anfangsformular_nachweis='extern', anfangsformular_datum=date(2026, 11, 20))
        self._unterschrieben(v)
        self.assertEqual(v.status, 'aktiv')


# ---------------------------------------------------------------------------
# Der Assistent
# ---------------------------------------------------------------------------
class AssistentTests(_Basis):

    def daten(self, **extra):
        d = {'einheit_id': str(self.e.id), 'mieter_id': str(self.m.id), 'netto_mietzins': '1500',
             'nebenkosten': '200', 'beginn': '2026-12-01', 'nk_kostenarten': ['heizung', 'wasser']}
        d.update(extra)
        return d

    def speichern(self, daten):
        return self.c.post('/neu/vertraege/neu/speichern/', daten)

    def test_aktiv_setzen_ohne_nachweis_wird_abgewiesen(self):
        r = self.speichern(self.daten(aktiv_setzen='on'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('aktiv_setzen', r.context['feld_fehler'])
        self.assertIn('BGE 140 III 583', r.context['feld_fehler']['aktiv_setzen'])
        self.assertFalse(Mietvertrag.objects.filter(einheit=self.e).exists(), 'Es darf nichts angelegt werden')

    def test_aktiv_setzen_mit_nachweis_speichert_ihn_am_vertrag(self):
        r = self.speichern(self.daten(aktiv_setzen='on', anfangsformular_nachweis='extern',
                                      anfangsformular_datum='2026-11-20', anfangsformular_notiz='ZH-Formular, Einschreiben'))
        self.assertEqual(r.status_code, 302)
        v = Mietvertrag.objects.get(einheit=self.e)
        self.assertEqual(v.status, 'aktiv')
        self.assertEqual((v.anfangsformular_nachweis, v.anfangsformular_datum, v.anfangsformular_notiz),
                         ('extern', date(2026, 11, 20), 'ZH-Formular, Einschreiben'))

    def test_extern_verlangt_das_datum(self):
        r = self.speichern(self.daten(aktiv_setzen='on', anfangsformular_nachweis='extern'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('anfangsformular_datum', r.context['feld_fehler'])

    def test_unlesbares_datum_wird_nicht_ersetzt(self):
        r = self.speichern(self.daten(anfangsformular_nachweis='extern', anfangsformular_datum='morgen'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('anfangsformular_datum', r.context['feld_fehler'])

    def test_entwurf_ohne_nachweis_ist_erlaubt_mit_hinweis_und_pendenz(self):
        from core.models import Pendenz
        r = self.speichern(self.daten())
        self.assertEqual(r.status_code, 302)
        v = Mietvertrag.objects.get(einheit=self.e)
        self.assertEqual(v.status, 'entwurf')
        self.assertIn('BGE 140 III 583', ' '.join(self.meldungen(r)))
        p = Pendenz.objects.get(vertrag=v, quelle=f'auto:anfangsformular:{v.pk}')
        self.assertIn('Anfangsmietzins-Formular beschaffen', p.titel)
        self.assertEqual(p.faellig_am, date(2026, 12, 1))

    def test_nicht_betroffen_gibt_es_nur_bei_teilweiser_pflicht(self):
        r = self.speichern(self.daten(anfangsformular_nachweis='nicht_betroffen', anfangsformular_notiz='Gemeinde ohne Pflicht'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('anfangsformular_nachweis', r.context['feld_fehler'])
        self.kanton_setzen('NE', plz='2000')
        r = self.speichern(self.daten(aktiv_setzen='on', anfangsformular_nachweis='nicht_betroffen',
                                      anfangsformular_notiz='Gemeinde ohne Pflicht'))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Mietvertrag.objects.get(einheit=self.e).status, 'aktiv')
        # ohne Begründung nicht
        self.e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='4.5 Zi', typ='whg')
        r = self.speichern(self.daten(einheit_id=str(self.e.id), anfangsformular_nachweis='nicht_betroffen'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('anfangsformular_notiz', r.context['feld_fehler'])

    def test_kanton_ohne_pflicht_braucht_nichts_und_speichert_keinen_nachweis(self):
        self.kanton_setzen('AG', plz='5000')
        r = self.speichern(self.daten(aktiv_setzen='on', anfangsformular_nachweis='extern',
                                      anfangsformular_datum='2026-11-20'))
        self.assertEqual(r.status_code, 302)
        v = Mietvertrag.objects.get(einheit=self.e)
        self.assertEqual((v.status, v.anfangsformular_nachweis, v.anfangsformular_datum), ('aktiv', '', None))

    def test_der_assistent_zeigt_hinweis_und_nachweis_je_objekt(self):
        r = self.c.get('/neu/vertraege/neu/')
        self.assertEqual(r.status_code, 200)
        objekte = [o for l in r.context['liegenschaften'] for o in l['objekte']]
        af_daten = objekte[0]['af']
        self.assertTrue(af_daten['erforderlich'])
        self.assertFalse(af_daten['original'])
        self.assertIn('BGE 140 III 583', af_daten['hinweis'])
        html = r.content.decode()
        self.assertIn('id="af-hinweis"', html)
        self.assertIn('id="af-nachweis"', html)
        self.assertIn('name="anfangsformular_nachweis"', html)

    def test_bearbeiten_eines_entwurfs_bringt_den_nachweis_zurueck(self):
        v = self.entwurf(anfangsformular_nachweis='extern', anfangsformular_datum=date(2026, 11, 20),
                         anfangsformular_notiz='Einschreiben')
        r = self.c.get(f'/neu/vertraege/neu/?edit={v.id}')
        self.assertEqual(r.context['edit_json']['af_nachweis'], 'extern')
        self.assertEqual(r.context['edit_json']['af_datum'], '2026-11-20')
        self.assertEqual(r.context['edit_json']['nk_kostenarten'], ['heizung', 'wasser'])


# ---------------------------------------------------------------------------
# Nachweis am Vertrag
# ---------------------------------------------------------------------------
class NachweisAnsichtTests(_Basis):

    def url(self, v):
        return f'/neu/vertraege/{v.id}/anfangsformular-nachweis/'

    def test_erfassen_speichert_und_erledigt_die_pendenz(self):
        from core.models import Pendenz
        v = self.entwurf()
        af.pendenz_nachweis_anlegen(v, 'Hinweis')
        r = self.c.post(self.url(v), {'anfangsformular_nachweis': 'extern', 'anfangsformular_datum': '2026-11-20',
                                      'anfangsformular_notiz': 'Einschreiben'})
        self.assertEqual(r.status_code, 302)
        v.refresh_from_db()
        self.assertEqual((v.anfangsformular_nachweis, v.anfangsformular_datum), ('extern', date(2026, 11, 20)))
        self.assertTrue(Pendenz.objects.get(vertrag=v, quelle=f'auto:anfangsformular:{v.pk}').erledigt)

    def test_ohne_datum_wird_nichts_gespeichert(self):
        v = self.entwurf()
        r = self.c.post(self.url(v), {'anfangsformular_nachweis': 'extern'}, follow=True)
        v.refresh_from_db()
        self.assertEqual(v.anfangsformular_nachweis, '')
        self.assertTrue(any('Datum' in m for m in self.meldungen(r)))

    def test_entfernen(self):
        v = self.entwurf(anfangsformular_nachweis='extern', anfangsformular_datum=date(2026, 11, 20))
        self.c.post(self.url(v), {'aktion': 'entfernen'})
        v.refresh_from_db()
        self.assertEqual((v.anfangsformular_nachweis, v.anfangsformular_datum), ('', None))

    def test_wo_kein_nachweis_noetig_ist_wird_nichts_gespeichert(self):
        self.kanton_setzen('AG', plz='5000')
        v = self.entwurf()
        self.c.post(self.url(v), {'anfangsformular_nachweis': 'extern', 'anfangsformular_datum': '2026-11-20'})
        v.refresh_from_db()
        self.assertEqual(v.anfangsformular_nachweis, '')

    def test_lesezugriff_darf_nicht_schreiben(self):
        v = self.entwurf()
        c = Client()
        c.force_login(_team_user('Lesend'))
        r = c.post(self.url(v), {'anfangsformular_nachweis': 'extern', 'anfangsformular_datum': '2026-11-20'})
        self.assertEqual(r.status_code, 403)
        v.refresh_from_db()
        self.assertEqual(v.anfangsformular_nachweis, '')

    def test_fremder_vertrag_ist_404(self):
        from ._isolation import MandantenFixture as Fix
        fremd = Fix('B', '3000', 'Bern')
        r = self.c.post(self.url(fremd.vertrag), {'anfangsformular_nachweis': 'extern',
                                                  'anfangsformular_datum': '2026-11-20'})
        self.assertEqual(r.status_code, 404)
        fremd.vertrag.refresh_from_db()
        self.assertEqual(fremd.vertrag.anfangsformular_nachweis, '')

    def test_get_aendert_nichts(self):
        v = self.entwurf()
        self.assertEqual(self.c.get(self.url(v)).status_code, 302)

    def test_vertragsakte_zeigt_hinweis_chip_und_formular(self):
        v = self.entwurf()
        r = self.c.get(f'/neu/vertraege/{v.id}/')
        html = r.content.decode()
        self.assertIn('Formular-Nachweis fehlt', html)
        self.assertIn('id="vt-anfangsformular-nachweis"', html)
        self.assertIn('BGE 140 III 583', html)
        self.assertIn(self.url(v), html)

    def test_vertragsakte_ohne_pflicht_zeigt_nichts(self):
        self.kanton_setzen('AG', plz='5000')
        v = self.entwurf()
        html = self.c.get(f'/neu/vertraege/{v.id}/').content.decode()
        self.assertNotIn('vt-anfangsformular', html)
        self.assertNotIn('Formular-Nachweis fehlt', html)


# ---------------------------------------------------------------------------
# MIET-05: der bisherige Mietzins
# ---------------------------------------------------------------------------
class VormieteTests(_Basis):
    """Vormieter: Netto 1500 ab 1.1.2020. Staffel +100 am 1.6.2021 und +100 am 1.6.2022 (beides vor dem
    1.10.2025, also ohne Mitteilung wirksam). Der letzte Mietzins ist 1700 — nicht der Wert zu Beginn (1500)."""

    def vormieter(self, **kw):
        from rentals.models import Staffelstufe
        felder = dict(mieter=Mieter.objects.create(typ='person', vorname='Vor', nachname='Mieter'), einheit=self.e,
                      beginn=date(2020, 1, 1), ende=date(2023, 12, 31), netto_mietzins=D('1500'),
                      nebenkosten=D('200'), status='gekuendigt', mietzins_modell='staffel',
                      basis_referenzzinssatz=D('1.50'), basis_lik_punkte=D('100.0'))
        felder.update(kw)
        v = Mietvertrag.objects.create(**felder)
        if felder['mietzins_modell'] == 'staffel':
            for ab in (date(2021, 6, 1), date(2022, 6, 1)):
                Staffelstufe.objects.create(vertrag=v, ab_datum=ab, netto_mietzins=D('0'), erhoehung_chf=D('100'))
        return v

    def test_staffel_in_der_vormiete_der_letzte_stand_gilt(self):
        vor = self.vormieter()
        neu = self.entwurf(beginn=date(2024, 3, 1))
        w = af.vormiete_werte(neu)
        self.assertEqual(w['vertrag'], vor)
        self.assertEqual(w['netto'], D('1700.00'))
        self.assertEqual(w['stichtag'], date(2023, 12, 31), 'Ende der Vormiete, nicht der Tag vor dem neuen Beginn')

    def test_gebuchte_anpassung_in_der_vormiete_zaehlt_mit_basis(self):
        from rentals.models import MietzinsAnpassung
        vor = self.vormieter(mietzins_modell='fest')
        MietzinsAnpassung.objects.create(
            vertrag=vor, wirksam_ab=date(2022, 4, 1), alter_netto_mietzins=D('1500'), neuer_netto_mietzins=D('1450'),
            neuer_referenzzinssatz=D('1.25'), neuer_lik_index=D('104.0'), status='wirksam')
        w = af.vormiete_werte(self.entwurf(beginn=date(2024, 3, 1)))
        self.assertEqual(w['netto'], D('1450'))
        self.assertEqual((w['ref'], w['lik']), (D('1.25'), D('104.0')), 'Basis aus der damals wirksamen Anpassung')

    def test_anpassung_nach_dem_ende_der_vormiete_zaehlt_nicht(self):
        from rentals.models import MietzinsAnpassung
        vor = self.vormieter(mietzins_modell='fest', ende=date(2023, 6, 30))
        MietzinsAnpassung.objects.create(vertrag=vor, wirksam_ab=date(2023, 9, 1), alter_netto_mietzins=D('1500'),
                                         neuer_netto_mietzins=D('1900'), status='wirksam')
        w = af.vormiete_werte(self.entwurf(beginn=date(2024, 3, 1)))
        self.assertEqual(w['netto'], D('1500'))
        self.assertEqual(w['stichtag'], date(2023, 6, 30))

    def test_nahtloser_wechsel_nimmt_den_tag_vor_dem_beginn(self):
        self.vormieter(ende=date(2024, 2, 29))
        w = af.vormiete_werte(self.entwurf(beginn=date(2024, 3, 1)))
        self.assertEqual(w['stichtag'], date(2024, 2, 29))
        self.assertEqual(w['netto'], D('1700.00'))

    def test_entwuerfe_sind_keine_vormiete(self):
        vor = self.vormieter()
        # ein später begonnener, nie in Kraft getretener Entwurf zwischen Vormieter und neuem Vertrag
        self.vormieter(beginn=date(2024, 1, 1), ende=None, status='entwurf', mietzins_modell='fest',
                       netto_mietzins=D('9999'))
        w = af.vormiete_werte(self.entwurf(beginn=date(2024, 3, 1)))
        self.assertEqual(w['vertrag'], vor)

    def test_ohne_vormieter_keine_angabe(self):
        self.assertIsNone(af.vormiete_werte(self.entwurf()))

    def test_formularseite_schlaegt_den_letzten_mietzins_vor(self):
        self.vormieter()
        neu = self.entwurf(beginn=date(2024, 3, 1))
        r = self.c.get(f'/neu/mietzins/{neu.id}/anfangsmietzins/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['vormiete_netto'], D('1700.00'))
        self.assertEqual(r.context['vor_stichtag'], date(2023, 12, 31))
        self.assertContains(r, 'Stand 31.12.2023')

    def test_automatisch_abgelegtes_formular_bekommt_den_letzten_mietzins(self):
        """Bern (Original): `anfangsmietzins_auto_ablegen` reicht den bisherigen Mietzins an das Formular."""
        from core.views.fw.mietzins import anfangsmietzins_auto_ablegen
        self.kanton_setzen('BE', plz='3000')
        self.vormieter()
        neu = self.entwurf(beginn=date(2024, 3, 1), status='aktiv')
        with mock.patch('core.services.formular_fill.fill_anfangsmietzins', return_value=b'%PDF-1.4 x') as fill, \
                mock.patch('core.services.ablage.ablegen'):
            erzeugt, grund = anfangsmietzins_auto_ablegen(neu)
        self.assertTrue(erzeugt, grund)
        daten = fill.call_args[0][1]
        self.assertEqual(daten['vormiete_netto'], D('1700.00'))
        self.assertEqual(daten['vormiete_nk'], D('200'))
        self.assertEqual(daten['grund_choice'], 'anpassung')
