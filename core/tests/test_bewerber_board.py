"""Bewerber-Board (Modul 4, 27.10.2026): Spalten, Verschieben, Checkliste,
Vertragsbezug, Upload-Pfad und die Zuordnung des Bestands.

Die Spalten und Übergänge stehen in `mietprozess.workflow`; die Ansichten in
`core/views/fw/mietprozess.py`.
"""
import os
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from ._helfer import _basis_objekte, _team_user, Einheit, Mietvertrag, Mieter

JSON = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest', 'HTTP_ACCEPT': 'application/json'}


def _bewerbung(e, vorname='Anna', status='neu', email=None, **kw):
    from mietprozess.models import Mietbewerbung
    werte = dict(einheit=e, vorname=vorname, nachname='Muster', geburtsdatum=date(1990, 1, 1),
                 mobilnummer='079 000 00 00', email=email or f'{vorname.lower()}@example.ch',
                 beruf='Kauffrau', einkommen_jahr="90'000", status=status)
    werte.update(kw)
    return Mietbewerbung.objects.create(**werte)


def _alt_machen(b, tage):
    """`aktualisiert_am` ist auto_now — direkt in der Datenbank zurückdatieren."""
    wann = timezone.now() - timedelta(days=tage)
    type(b).objects.filter(pk=b.pk).update(aktualisiert_am=wann, erstellt_am=wann - timedelta(days=5))
    b.refresh_from_db()
    return b


def _ids(spalte):
    return {k['b'].id for k in spalte['karten']}


class BewerberBoardSpaltenTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def _spalten(self, **params):
        r = self.c.get('/neu/bewerbungen/', params)
        self.assertEqual(r.status_code, 200)
        return {sp['key']: sp for sp in r.context['spalten']}, r

    def test_vier_spalten_und_zuordnung(self):
        neu = _bewerbung(self.e, 'Neu')
        geprueft = _bewerbung(self.e, 'Geprueft', status='geprueft')
        besichtigung = _bewerbung(self.e, 'Besicht', status='besichtigung',
                                  besichtigung_am=timezone.now() + timedelta(days=2))
        zugesagt = _bewerbung(self.e, 'Zugesagt', status='zugesagt')
        abgelehnt = _bewerbung(self.e, 'Weg', status='abgelehnt')
        mit_vertrag = _bewerbung(self.e, 'Vertrag', status='zugesagt', vertrag=self.v)

        sp, r = self._spalten()
        self.assertEqual(list(sp), ['eingegangen', 'geprueft', 'abgelehnt', 'vertrag'])
        self.assertEqual(_ids(sp['eingegangen']), {neu.id})
        # «zugesagt» OHNE Vertrag gehört nach Geprüft, MIT Vertrag nach Vertrag generiert.
        self.assertEqual(_ids(sp['geprueft']), {geprueft.id, besichtigung.id, zugesagt.id})
        self.assertEqual(_ids(sp['abgelehnt']), {abgelehnt.id})
        self.assertEqual(_ids(sp['vertrag']), {mit_vertrag.id})
        inhalt = r.content.decode()
        self.assertIn('zugesagt · Vertrag noch nicht erzeugt', inhalt)
        self.assertIn(f'Vertrag #{self.v.id}', inhalt)

    def test_karte_zeigt_punkte_und_checkliste(self):
        b = _bewerbung(self.e, status='geprueft', digitaler_betreibungsauszug=True,
                       arbeitgeber='Muster AG',
                       pruefung={'ausweis': {'ok': True, 'von': 'x', 'am': '2026-10-01T10:00:00+00:00'}})
        sp, r = self._spalten()
        karte = sp['geprueft']['karten'][0]
        from core.services.bewerber_scoring import bewerte_bewerbung
        self.assertEqual(karte['score'], bewerte_bewerbung(b, self.e.nettomiete_aktuell
                                                           + self.e.nebenkosten_aktuell)['score'])
        self.assertEqual(karte['pruefung_ok'], 1)
        self.assertIn('Prüfung 1/4', r.content.decode())

    def test_abgelehnte_aelter_als_30_tage_ausgeblendet(self):
        frisch = _alt_machen(_bewerbung(self.e, 'Frisch', status='abgelehnt'), 29)
        alt = _alt_machen(_bewerbung(self.e, 'Alt', status='abgelehnt'), 31)
        sp, r = self._spalten()
        self.assertEqual(_ids(sp['abgelehnt']), {frisch.id})
        self.assertEqual(r.context['ausgeblendet'], 1)
        # Die Liste zeigt beide — sie ist das Archiv bis zur Anonymisierung.
        r2 = self.c.get('/neu/bewerbungen/', {'ansicht': 'liste'})
        self.assertEqual({k['b'].id for k in r2.context['karten']}, {frisch.id, alt.id})

    def test_abgelehnt_zeigt_naechste_loeschfrist(self):
        from core.services.bewerbung_aufbewahrung import naechste_frist
        b = _alt_machen(_bewerbung(self.e, status='abgelehnt'), 3)
        sp, r = self._spalten()
        karte = sp['abgelehnt']['karten'][0]
        self.assertEqual(karte['frist'], naechste_frist(b, timezone.localdate()))
        self.assertIsNotNone(karte['frist'])
        self.assertIn(karte['frist'].strftime('%d.%m.%Y'), r.content.decode())

    def test_filter_einheit(self):
        e2 = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='2 Zi', typ='whg')
        hier = _bewerbung(self.e, 'Hier')
        dort = _bewerbung(e2, 'Dort')
        sp, r = self._spalten(einheit=e2.id)
        self.assertEqual(_ids(sp['eingegangen']), {dort.id})
        self.assertEqual(r.context['aktive_einheit'], e2)
        # Unsinn im Parameter: kein Filter, kein Absturz.
        sp, r = self._spalten(einheit='abc')
        self.assertEqual(_ids(sp['eingegangen']), {hier.id, dort.id})
        self.assertIsNone(r.context['aktive_einheit'])

    def test_leerer_zustand(self):
        sp, r = self._spalten()
        self.assertTrue(all(s['anzahl'] == 0 for s in sp.values()))
        self.assertContains(r, 'Keine neuen Bewerbungen.')
        r2 = self.c.get('/neu/bewerbungen/', {'ansicht': 'liste'})
        self.assertContains(r2, 'Keine Bewerbungen')

    def test_abfragen_haengen_nicht_an_der_kartenzahl(self):
        """Punktezahl, Checkliste und Löschfrist rechnen ohne Abfrage je Karte."""
        def messen():
            from django.db import connection
            from django.test.utils import CaptureQueriesContext
            with CaptureQueriesContext(connection) as q:
                self.assertEqual(self.c.get('/neu/bewerbungen/').status_code, 200)
            return len(q)

        for i, st in enumerate(('neu', 'geprueft', 'abgelehnt')):
            _bewerbung(self.e, f'A{i}', status=st)
        _bewerbung(self.e, 'V0', status='zugesagt', vertrag=self.v)
        messen()        # der erste Aufruf einer Sitzung liest einmalig mehr (Sitzung, Zwischenspeicher)
        wenige = messen()
        for i, st in enumerate(('neu', 'geprueft', 'besichtigung', 'abgelehnt', 'abgelehnt')):
            _bewerbung(self.e, f'B{i}', status=st)
        _bewerbung(self.e, 'V1', status='zugesagt', vertrag=self.v)
        self.assertEqual(messen(), wenige)
        with self.assertNumQueries(20):
            self.c.get('/neu/bewerbungen/')

    def test_lesende_rolle_sieht_kein_auswahlfeld(self):
        _bewerbung(self.e)
        c = Client()
        c.force_login(_team_user(rolle='Lesend'))
        r = c.get('/neu/bewerbungen/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, '/verschieben/" class="fw-karte-form"')
        self.assertNotContains(r, 'draggable="true"')
        self.assertContains(r, 'class="fw-karte')


class BewerberWorkflowTests(TestCase):
    """Die Tabelle in `mietprozess.workflow`, ohne Ansicht."""

    def test_spalten_und_ziele(self):
        from mietprozess.models import Mietbewerbung
        from mietprozess.workflow import erlaubte_spalten, spalte_erlaubt
        b = Mietbewerbung(status='neu')
        self.assertEqual([k for k, _l in erlaubte_spalten(b)], ['geprueft', 'abgelehnt', 'vertrag'])
        b.status = 'geprueft'
        self.assertFalse(spalte_erlaubt(b, 'eingegangen'))
        self.assertFalse(spalte_erlaubt(b, 'geprueft'))           # eigene Spalte ist kein Wechsel
        b.status = 'abgelehnt'
        self.assertEqual([k for k, _l in erlaubte_spalten(b)], ['geprueft'])
        b.status, b.vertrag_id = 'zugesagt', 1
        self.assertEqual(erlaubte_spalten(b), [])


class BewerberVerschiebenTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def _ziehen(self, b, spalte, **extra):
        return self.c.post(f'/neu/bewerbungen/{b.id}/verschieben/', {'spalte': spalte}, **JSON, **extra)

    def test_nach_geprueft(self):
        b = _bewerbung(self.e)
        r = self._ziehen(b, 'geprueft')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        b.refresh_from_db()
        self.assertEqual(b.status, 'geprueft')

    def test_unzulaessig_ergibt_400_und_nichts_aendert_sich(self):
        b = _bewerbung(self.e, status='geprueft')
        r = self._ziehen(b, 'eingegangen')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()['ok'])
        self.assertIn('kein Wechsel vorgesehen', r.json()['meldung'])
        b.refresh_from_db()
        self.assertEqual(b.status, 'geprueft')

    def test_unbekannte_spalte_ergibt_400(self):
        b = _bewerbung(self.e)
        self.assertEqual(self._ziehen(b, 'irgendwo').status_code, 400)

    def test_formular_ohne_js_leitet_zurueck(self):
        b = _bewerbung(self.e, status='geprueft')
        r = self.c.post(f'/neu/bewerbungen/{b.id}/verschieben/',
                        {'spalte': 'eingegangen', 'einheit': str(self.e.id)})
        self.assertRedirects(r, f'/neu/bewerbungen/?einheit={self.e.id}', fetch_redirect_response=False)

    def test_absage_mit_mail_und_zeitstempel(self):
        from core.models import Pendenz
        b = _alt_machen(_bewerbung(self.e, status='besichtigung'), 60)
        Pendenz.objects.create(titel='Besichtigung Anna', quelle=f'besichtigung:{b.id}',
                               liegenschaft=self.lg)
        r = self._ziehen(b, 'abgelehnt')
        self.assertEqual(r.status_code, 200, r.content)
        b.refresh_from_db()
        self.assertEqual(b.status, 'abgelehnt')
        absagen = [m for m in mail.outbox if 'anna@example.ch' in m.to]
        self.assertEqual(len(absagen), 1)
        self.assertIn('Wohnungsbewerbung', absagen[0].subject)
        # Der Entscheid ist heute — daran hängen Löschfrist und die 30 Tage.
        self.assertEqual(b.aktualisiert_am.date(), timezone.localdate())
        self.assertTrue(Pendenz.objects.get(quelle=f'besichtigung:{b.id}').erledigt)

    def test_vertrag_setzt_fk_und_nennt_die_vertragsseite(self):
        self.e.zur_ausschreibung = True
        self.e.save()
        b = _bewerbung(self.e, 'Vera', status='zugesagt')
        r = self._ziehen(b, 'vertrag')
        self.assertEqual(r.status_code, 200, r.content)
        b.refresh_from_db()
        self.assertIsNotNone(b.vertrag_id)
        self.assertEqual(r.json()['weiter'], f'/neu/vertraege/{b.vertrag_id}/')
        self.assertEqual(b.vertrag.status, 'entwurf')
        self.assertEqual(b.vertrag.mieter.nachname, 'Muster')
        self.assertEqual(b.status, 'zugesagt')
        self.e.refresh_from_db()
        self.assertFalse(self.e.zur_ausschreibung)
        # Ein zweites Ablegen legt nichts Neues an.
        self.assertEqual(self._ziehen(b, 'vertrag').status_code, 200)
        self.assertEqual(Mietvertrag.objects.filter(einheit=self.e, status='entwurf').count(), 1)

    def test_vertrag_als_formular_leitet_zum_vertrag(self):
        b = _bewerbung(self.e, status='geprueft')
        r = self.c.post(f'/neu/bewerbungen/{b.id}/verschieben/', {'spalte': 'vertrag'})
        b.refresh_from_db()
        self.assertRedirects(r, f'/neu/vertraege/{b.vertrag_id}/', fetch_redirect_response=False)

    def test_aus_abgelehnt_kein_vertrag(self):
        b = _bewerbung(self.e, status='abgelehnt')
        self.assertEqual(self._ziehen(b, 'vertrag').status_code, 400)
        b.refresh_from_db()
        self.assertIsNone(b.vertrag_id)
        self.assertFalse(Mietvertrag.objects.filter(status='entwurf').exists())

    def test_mit_vertrag_gesperrt(self):
        b = _bewerbung(self.e, status='zugesagt', vertrag=self.v)
        r = self._ziehen(b, 'abgelehnt')
        self.assertEqual(r.status_code, 400)
        self.assertIn('bereits ein Vertrag', r.json()['meldung'])
        b.refresh_from_db()
        self.assertEqual(b.status, 'zugesagt')
        self.assertEqual(len(mail.outbox), 0)

    def test_nur_post_und_nur_schreibende(self):
        b = _bewerbung(self.e)
        self.assertEqual(self.c.get(f'/neu/bewerbungen/{b.id}/verschieben/').status_code, 405)
        c = Client()
        c.force_login(_team_user(rolle='Lesend'))
        r = c.post(f'/neu/bewerbungen/{b.id}/verschieben/', {'spalte': 'geprueft'}, **JSON)
        self.assertIn(r.status_code, (302, 403))
        b.refresh_from_db()
        self.assertEqual(b.status, 'neu')


class BewerbungStatusUndVertragTests(TestCase):
    """Statusformular, Entscheid und Umwandlung lesen dieselben Übergänge."""

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def test_statusformular_nutzt_die_uebergaenge(self):
        b = _bewerbung(self.e, status='abgelehnt')
        self.c.post(f'/neu/bewerbungen/{b.id}/status/', {'status': 'zugesagt'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'abgelehnt')
        self.c.post(f'/neu/bewerbungen/{b.id}/status/', {'status': 'geprueft'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'geprueft')
        self.c.post(f'/neu/bewerbungen/{b.id}/status/', {'status': 'neu'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'geprueft')

    def test_detail_bietet_nur_erlaubte_status(self):
        b = _bewerbung(self.e, status='abgelehnt')
        r = self.c.get(f'/neu/bewerbungen/{b.id}/')
        self.assertEqual([k for k, _l, _c in r.context['status_wahl']], ['geprueft', 'abgelehnt'])

    def test_umwandlung_trifft_keinen_fremden_entwurf_mit_gleichem_namen(self):
        """Die Namenssuche ist weg. Vorher fand sie den Entwurf einer anderen
        Bewerbung derselben Person (gleicher Name, gleiche E-Mail) und leitete
        dorthin um, statt einen eigenen anzulegen."""
        fremd_mieter = Mieter.objects.create(typ='person', vorname='Anna', nachname='Muster',
                                             email='anna@example.ch')
        fremd = Mietvertrag.objects.create(mieter=fremd_mieter, einheit=self.e, status='entwurf',
                                           beginn=date(2026, 12, 1), netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'))
        b = _bewerbung(self.e, status='geprueft')
        r = self.c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        b.refresh_from_db()
        self.assertIsNotNone(b.vertrag_id)
        self.assertNotEqual(b.vertrag_id, fremd.id)
        self.assertRedirects(r, f'/neu/vertraege/{b.vertrag_id}/', fetch_redirect_response=False)

    def test_umwandlung_ist_idempotent_am_verweis(self):
        b = _bewerbung(self.e, status='zugesagt', vertrag=self.v)
        r = self.c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        self.assertRedirects(r, f'/neu/vertraege/{self.v.id}/', fetch_redirect_response=False)
        self.assertFalse(Mietvertrag.objects.filter(status='entwurf').exists())
        from django.contrib.messages import get_messages
        self.assertIn('existiert bereits', ' '.join(str(m) for m in get_messages(r.wsgi_request)))

    def test_helfer_legt_bei_vorhandenem_verweis_nichts_an(self):
        """Board und Detailansicht rufen denselben Helfer; er selbst ist idempotent."""
        from django.test import RequestFactory
        from core.views.fw.mietprozess import _vertrag_aus_bewerbung
        b = _bewerbung(self.e, status='zugesagt', vertrag=self.v)
        request = RequestFactory().post('/')
        request.user = _team_user(rolle='Sachbearbeitung')
        vertrag, neu = _vertrag_aus_bewerbung(request, b)
        self.assertEqual((vertrag, neu), (self.v, False))
        self.assertFalse(Mietvertrag.objects.filter(status='entwurf').exists())

    def test_entscheid_absage_setzt_den_zeitstempel(self):
        b = _alt_machen(_bewerbung(self.e, status='geprueft'), 90)
        self.c.post(f'/neu/bewerbungen/{b.id}/entscheid/', {'entscheid': 'absage'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'abgelehnt')
        self.assertEqual(b.aktualisiert_am.date(), timezone.localdate())


class SammelabsageTests(TestCase):

    def test_besichtigung_gehoert_dazu_vertrag_nicht(self):
        lg, e, m, v = _basis_objekte()
        neu = _bewerbung(e, 'A', status='neu')
        besichtigung = _bewerbung(e, 'B', status='besichtigung')
        zugesagt = _bewerbung(e, 'C', status='zugesagt')
        c = Client()
        c.force_login(_team_user())
        r = c.get(f'/neu/vermarktung/{e.id}/bewerber/')
        self.assertEqual(r.context['offene_n'], 2)
        self.assertContains(r, 'zur Besichtigung eingeladen')
        c.post(f'/neu/vermarktung/{e.id}/bewerber/absage-uebrige/')
        for b in (neu, besichtigung, zugesagt):
            b.refresh_from_db()
        self.assertEqual((neu.status, besichtigung.status, zugesagt.status),
                         ('abgelehnt', 'abgelehnt', 'zugesagt'))
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['a@example.ch', 'b@example.ch'])


class BewerbungPruefungTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.u = _team_user()
        self.u.first_name, self.u.last_name = 'Sara', 'Sachbearbeiterin'
        self.u.save()
        self.c = Client()
        self.c.force_login(self.u)

    def test_abhaken_haelt_wer_und_wann_fest_und_aendert_den_status_nicht(self):
        b = _alt_machen(_bewerbung(self.e, status='neu'), 10)
        vorher = b.aktualisiert_am
        r = self.c.post(f'/neu/bewerbungen/{b.id}/pruefung/', {'pruefung': 'referenz', 'ok': '1'})
        self.assertRedirects(r, f'/neu/bewerbungen/{b.id}/', fetch_redirect_response=False)
        b.refresh_from_db()
        self.assertTrue(b.pruefung['referenz']['ok'])
        self.assertEqual(b.pruefung['referenz']['von'], 'Sara Sachbearbeiterin')
        self.assertIsNotNone(b.pruefpunkte()[2]['am'])
        # E7: kein Riegel, keine Automatik — der Status bleibt.
        self.assertEqual(b.status, 'neu')
        # Löschfrist und 30-Tage-Sicht hängen an `aktualisiert_am`; er bleibt.
        self.assertEqual(b.aktualisiert_am, vorher)
        self.c.post(f'/neu/bewerbungen/{b.id}/pruefung/', {'pruefung': 'referenz', 'ok': '0'})
        b.refresh_from_db()
        self.assertFalse(b.pruefung['referenz']['ok'])
        self.assertEqual(b.pruefung_erledigt(), 0)

    def test_unbekannter_punkt_wird_abgelehnt(self):
        b = _bewerbung(self.e)
        self.c.post(f'/neu/bewerbungen/{b.id}/pruefung/', {'pruefung': 'blockiert', 'ok': '1'})
        b.refresh_from_db()
        self.assertEqual(b.pruefung, {})

    def test_detail_zeigt_die_checkliste(self):
        b = _bewerbung(self.e)
        r = self.c.get(f'/neu/bewerbungen/{b.id}/')
        for label in ('Betreibung', 'Ausweis', 'Referenz', 'Tragbarkeit'):
            self.assertContains(r, label)
        self.assertContains(r, f'action="/neu/bewerbungen/{b.id}/pruefung/"', count=4)

    def test_lesende_rolle_kann_nicht_abhaken(self):
        b = _bewerbung(self.e)
        c = Client()
        c.force_login(_team_user(rolle='Lesend'))
        c.post(f'/neu/bewerbungen/{b.id}/pruefung/', {'pruefung': 'referenz', 'ok': '1'})
        b.refresh_from_db()
        self.assertEqual(b.pruefung, {})


class BewerbungAblageTests(TestCase):
    """Neue Unterlagen unter organisation/<id>/, alte bleiben und bleiben geschützt."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._ov = override_settings(MEDIA_ROOT=self._tmp)
        self._ov.enable()
        self.lg, self.e, self.m, self.v = _basis_objekte()

    def tearDown(self):
        self._ov.disable()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_neue_datei_liegt_unter_der_organisation(self):
        from django.core.files.base import ContentFile
        b = _bewerbung(self.e)
        b.ausweiskopie.save('ausweis.pdf', ContentFile(b'%PDF-1'), save=True)
        self.assertTrue(b.ausweiskopie.name.startswith(
            f'organisation/{b.organisation_id}/bewerbungen/ausweis/'), b.ausweiskopie.name)
        from core.views.media_protected import ist_oeffentlich, organisation_id_der_datei
        self.assertFalse(ist_oeffentlich(b.ausweiskopie.name))
        self.assertEqual(organisation_id_der_datei(b.ausweiskopie.name), b.organisation_id)

    def test_neue_bewerbung_bekommt_den_pfad_schon_beim_ersten_speichern(self):
        """Beim öffentlichen Formular ist die Bewerbung neu; die Organisation
        entsteht erst in `save()` aus der Einheit."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from mietprozess.models import Mietbewerbung
        b = Mietbewerbung(einheit=self.e, vorname='Neu', nachname='Bewerberin',
                          geburtsdatum=date(1990, 1, 1), email='neu@example.ch',
                          weitere_dokumente=SimpleUploadedFile('weitere.pdf', b'%PDF-2'))
        b.save()
        self.assertTrue(b.weitere_dokumente.name.startswith(
            f'organisation/{b.organisation_id}/bewerbungen/weitere/'), b.weitere_dokumente.name)

    def test_alter_und_neuer_pfad_werden_beide_geloescht(self):
        from django.conf import settings
        from django.core.files.base import ContentFile
        from core.services.bewerbung_aufbewahrung import loesche_dokumente
        b = _bewerbung(self.e, status='abgelehnt')
        alt = 'bewerbungen/betreibung/alt.pdf'
        os.makedirs(os.path.join(settings.MEDIA_ROOT, 'bewerbungen', 'betreibung'))
        with open(os.path.join(settings.MEDIA_ROOT, alt), 'wb') as f:
            f.write(b'%PDF-alt')
        b.betreibungsauszug.name = alt
        b.ausweiskopie.save('neu.pdf', ContentFile(b'%PDF-neu'), save=False)
        b.save()
        neu = b.ausweiskopie.name
        self.assertTrue(neu.startswith('organisation/'))
        self.assertEqual(loesche_dokumente(b), 2)
        self.assertFalse(os.path.exists(os.path.join(settings.MEDIA_ROOT, alt)))
        self.assertFalse(os.path.exists(os.path.join(settings.MEDIA_ROOT, neu)))

    def test_alte_datei_bleibt_fuer_das_eigene_team_abrufbar(self):
        from django.conf import settings
        b = _bewerbung(self.e)
        alt = 'bewerbungen/ausweis/alt.jpg'
        os.makedirs(os.path.join(settings.MEDIA_ROOT, 'bewerbungen', 'ausweis'))
        with open(os.path.join(settings.MEDIA_ROOT, alt), 'wb') as f:
            f.write(b'\xff\xd8bild')
        type(b).objects.filter(pk=b.pk).update(ausweiskopie=alt)
        c = Client()
        self.assertEqual(c.get('/media/' + alt).status_code, 404)        # anonym: nein
        c.force_login(_team_user())
        self.assertEqual(c.get('/media/' + alt).status_code, 200)        # eigenes Team: ja


class BewerberBoardIsolationTests(TestCase):
    """Fremde Bewerbungen ergeben 404 — beim Verschieben und beim Abhaken."""

    @classmethod
    def setUpTestData(cls):
        from ._isolation import MandantenFixture
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def _fremde(self):
        from mietprozess.models import Mietbewerbung
        return Mietbewerbung.alle_organisationen.get(pk=self.b.bewerbung.pk)

    def test_fremde_bewerbung_verschieben_ergibt_404(self):
        for spalte in ('geprueft', 'abgelehnt', 'vertrag'):
            r = self.c.post(f'/neu/bewerbungen/{self.b.bewerbung.pk}/verschieben/',
                            {'spalte': spalte}, **JSON)
            self.assertEqual(r.status_code, 404, spalte)
        fremd = self._fremde()
        self.assertEqual(fremd.status, 'neu')
        self.assertIsNone(fremd.vertrag_id)
        self.assertEqual(len(mail.outbox), 0)

    def test_fremde_bewerbung_abhaken_ergibt_404(self):
        r = self.c.post(f'/neu/bewerbungen/{self.b.bewerbung.pk}/pruefung/',
                        {'pruefung': 'referenz', 'ok': '1'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self._fremde().pruefung, {})

    def test_fremdes_objekt_im_filter_greift_nicht(self):
        r = self.c.get('/neu/bewerbungen/', {'einheit': self.b.einheit.pk})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['aktive_einheit'])
        ids = {k['b'].id for sp in r.context['spalten'] for k in sp['karten']}
        self.assertIn(self.a.bewerbung.pk, ids)
        self.assertNotIn(self.b.bewerbung.pk, ids)
        self.assertNotContains(r, 'Bewerber B')


class VertragZuordnungMigrationTests(TestCase):
    """`mietprozess.0010_vertrag_aus_bestand_zuordnen` — nur eindeutige Fälle."""

    def _lauf(self):
        from importlib import import_module
        from django.db import connection
        from django.db.migrations.loader import MigrationLoader
        migration = import_module('mietprozess.migrations.0010_vertrag_aus_bestand_zuordnen')
        apps = MigrationLoader(connection).project_state(
            ('mietprozess', '0010_vertrag_aus_bestand_zuordnen')).apps
        migration.zuordnen(apps, None)

    def _vertrag(self, e, vorname, nachname, email, beginn=date(2026, 12, 1), status='entwurf'):
        m = Mieter.objects.create(typ='person', vorname=vorname, nachname=nachname, email=email)
        return Mietvertrag.objects.create(mieter=m, einheit=e, status=status, beginn=beginn,
                                          netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'))

    def test_nur_eindeutige_treffer_werden_zugeordnet(self):
        lg, e, _m, _v = _basis_objekte()
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='2 Zi', typ='whg')
        e3 = Einheit.objects.create(liegenschaft=lg, bezeichnung='1 Zi', typ='whg')

        # 1) genau ein passender Vertrag → zugeordnet (auch wenn er inzwischen aktiv ist)
        eindeutig = _bewerbung(e, 'Eva', status='zugesagt', email='eva@example.ch')
        v_eva = self._vertrag(e, 'Eva', 'Muster', 'EVA@example.ch', status='aktiv')
        # 2) zwei passende Verträge → offen gelassen
        doppelt = _bewerbung(e2, 'Dora', status='zugesagt', email='dora@example.ch')
        self._vertrag(e2, 'Dora', 'Muster', 'dora@example.ch')
        self._vertrag(e2, 'Dora', 'Muster', 'dora@example.ch')
        # 3) Vertrag beginnt vor der Bewerbung (früheres Mietverhältnis) → offen
        frueher = _bewerbung(e3, 'Fritz', status='zugesagt', email='fritz@example.ch')
        self._vertrag(e3, 'Fritz', 'Muster', 'fritz@example.ch', beginn=date(2000, 1, 1), status='beendet')
        # 4) nicht zugesagt → offen, obwohl ein Vertrag passt
        offen = _bewerbung(e, 'Nora', status='geprueft', email='nora@example.ch')
        self._vertrag(e, 'Nora', 'Muster', 'nora@example.ch')
        # 5) zwei Bewerbungen beanspruchen denselben Vertrag → beide offen
        zwilling1 = _bewerbung(e3, 'Zoe', status='zugesagt', email='zoe@example.ch')
        zwilling2 = _bewerbung(e3, 'Zoe', status='zugesagt', email='zoe@example.ch')
        self._vertrag(e3, 'Zoe', 'Muster', 'zoe@example.ch')

        self._lauf()
        for b in (eindeutig, doppelt, frueher, offen, zwilling1, zwilling2):
            b.refresh_from_db()
        self.assertEqual(eindeutig.vertrag_id, v_eva.id)
        self.assertEqual([b.vertrag_id for b in (doppelt, frueher, offen, zwilling1, zwilling2)],
                         [None] * 5)

    def test_zuordnung_laesst_den_zeitstempel_stehen(self):
        lg, e, _m, _v = _basis_objekte()
        b = _bewerbung(e, 'Eva', status='zugesagt', email='eva@example.ch')
        self._vertrag(e, 'Eva', 'Muster', 'eva@example.ch')
        b = _alt_machen(b, 40)
        vorher = b.aktualisiert_am
        # `_alt_machen` datiert auch `erstellt_am` zurück — der Vertrag beginnt danach.
        self._lauf()
        b.refresh_from_db()
        self.assertIsNotNone(b.vertrag_id)
        self.assertEqual(b.aktualisiert_am, vorher)
