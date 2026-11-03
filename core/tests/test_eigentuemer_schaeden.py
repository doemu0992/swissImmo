"""Eigentümerportal v2: Schäden, Aufträge, Freigaben, Verlauf, Reparaturhistorie.

Zwei Eigenschaften zählen: Abgrenzung (nur eigene Liegenschaften; ein zweiter Eigentümer derselben
Verwaltung und eine zweite Verwaltung sehen/erreichen nichts Fremdes) und Datenschutz (nie
Melder-/Mieterdaten, nie Nachrichten, nie IBAN). Jeder Test, der etwas verbirgt, zeigt zuerst, dass
das Eigene sichtbar ist.
"""
from datetime import date, datetime
from decimal import Decimal

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.services import archiv
from core.services import eigentuemer_schaeden as dienst
from core.tenancy import organisation_kontext
from crm.models import Handwerker, Mieter
from finance.models import KreditorenRechnung
from tickets.models import HandwerkerAuftrag, SchadenMeldung, TicketNachricht

from .test_eigentuemer_portal import PortalWelt, _eigentuemer, _liegenschaft, _vertraege_beenden

GEHEIM = ('GEHEIMER-MELDER', 'geheim-melder@example.ch', '079 999 88 77', 'GEHEIMBESCHREIBUNG',
          'GEHEIMNACHRICHT', 'GEHEIMBEMERKUNG', 'CH9300762011623852957', 'Mieterin Namenlos')


def _zeit(jahr, monat=3, tag=4):
    return timezone.make_aware(datetime(jahr, monat, tag, 9, 30))


class SchadenWelt(PortalWelt):
    """A hat einen erledigten Schaden mit Rechnung und einen offenen mit ausstehender Freigabe."""

    def setUp(self):
        super().setUp()
        self.mieter = Mieter.objects.create(typ='person', vorname='Mieterin', nachname='Namenlos',
                                            email='namenlos@example.ch')
        self.hw = Handwerker.objects.create(firma='Sanitär Muster AG', email='hw@example.ch')
        # Erledigt, mit Rechnung.
        self.fertig = SchadenMeldung.objects.create(
            titel='Wasserhahn tropft', liegenschaft=self.lg_a, betroffene_einheit=self.einheit_a,
            kategorie='Sanitär', bauteil='kueche_sanitaer', gemeldet_von=self.mieter,
            melder_vorname='GEHEIMER-MELDER', email_melder='geheim-melder@example.ch',
            tel_melder='079 999 88 77', beschreibung='GEHEIMBESCHREIBUNG', status='in_bearbeitung')
        self.rechnung = KreditorenRechnung.objects.create(
            liegenschaft=self.lg_a, lieferant='Sanitär Muster AG', betrag=Decimal('480.00'), status='neu',
            datum=date(2025, 5, 2), iban='CH9300762011623852957', referenz='RF18GEHEIMREF')
        self.a_fertig = HandwerkerAuftrag.objects.create(
            ticket=self.fertig, handwerker=self.hw, bemerkung='GEHEIMBEMERKUNG',
            kosten_geschaetzt=Decimal('500.00'), kosten_effektiv=Decimal('480.00'),
            kreditoren_rechnung=self.rechnung, freigabe_status='freigegeben',
            freigabe_datum=_zeit(2025, 3, 10), freigabe_kommentar='Bitte zügig.')
        TicketNachricht.objects.create(ticket=self.fertig, absender_name='Verwaltung', typ='chat',
                                       nachricht='GEHEIMNACHRICHT', is_intern=False)
        self.fertig.status = 'erledigt'
        self.fertig.save()
        SchadenMeldung.objects.filter(pk=self.fertig.pk).update(erstellt_am=_zeit(2025, 3, 4))
        # Offen, Freigabe ausstehend.
        self.offen = SchadenMeldung.objects.create(
            titel='Dach undicht', liegenschaft=self.lg_a, kategorie='Dach', status='in_bearbeitung',
            beschreibung='GEHEIMBESCHREIBUNG')
        self.a_offen = HandwerkerAuftrag.objects.create(
            ticket=self.offen, handwerker=self.hw, kosten_geschaetzt=Decimal('3200.00'),
            freigabe_status='ausstehend')
        SchadenMeldung.objects.filter(pk=self.offen.pk).update(erstellt_am=_zeit(2026, 6, 1))
        # Fremd: anderer Eigentümer derselben Verwaltung, und eine andere Verwaltung.
        self.fremd_b = SchadenMeldung.objects.create(titel='FREMDSCHADEN-BETA', liegenschaft=self.lg_b,
                                                     status='neu')
        HandwerkerAuftrag.objects.create(ticket=self.fremd_b, handwerker=self.hw,
                                         kosten_effektiv=Decimal('7654.32'), freigabe_status='ausstehend')
        with organisation_kontext(self.org2):
            self.fremd_c = SchadenMeldung.objects.create(titel='FREMDSCHADEN-GAMMA', liegenschaft=self.lg_c,
                                                         status='neu')

    def seite(self, pfad='/portal/schaeden/', **kw):
        antwort = self.get(pfad, **kw)
        self.assertEqual(antwort.status_code, 200, pfad)
        return antwort.content.decode()


class IsolationTests(SchadenWelt):
    def test_liste_zeigt_nur_eigene(self):
        html = self.seite()
        self.assertIn('Wasserhahn tropft', html)
        self.assertIn('Dach undicht', html)
        self.assertNotIn('FREMDSCHADEN', html)
        self.assertNotIn('7654', html)

    def test_detail_fremder_schaden_ist_404(self):
        self.assertEqual(self.get(f'/portal/schaeden/{self.fremd_b.pk}/').status_code, 404)   # gleiche Verwaltung
        self.assertEqual(self.get(f'/portal/schaeden/{self.fremd_c.pk}/').status_code, 404)   # andere Verwaltung
        self.assertEqual(self.get('/portal/schaeden/999999/').status_code, 404)
        self.assertEqual(self.get(f'/portal/schaeden/{self.fertig.pk}/').status_code, 200)    # Gegenprobe

    def test_filter_auf_fremde_liegenschaft_ergibt_nichts(self):
        html = self.seite(f'/portal/schaeden/?liegenschaft={self.lg_b.pk}')
        self.assertNotIn('FREMDSCHADEN', html)
        self.assertIn('Keine Schäden für diese Auswahl', html)
        self.assertIn('Wasserhahn tropft', self.seite(f'/portal/schaeden/?liegenschaft={self.lg_a.pk}'))

    def test_kennzahlen_ohne_fremdes(self):
        k = dienst.liste(self.a)['kennzahlen']
        self.assertEqual((k['anzahl'], k['offen'], k['effektiv'], k['geschaetzt_offen']),
                         (2, 1, Decimal('480.00'), Decimal('3200.00')))

    def test_zweiter_eigentuemer_sieht_nur_seines(self):
        c = Client()
        c.force_login(self.b.benutzer)
        html = c.get('/portal/schaeden/').content.decode()
        self.assertIn('FREMDSCHADEN-BETA', html)
        self.assertNotIn('Wasserhahn', html)
        self.assertEqual(c.get(f'/portal/schaeden/{self.fertig.pk}/').status_code, 404)

    def test_historie_fremder_liegenschaft_ist_none(self):
        self.assertIsNone(dienst.historie(self.a, self.lg_b.pk))
        self.assertIsNone(dienst.historie(self.a, self.lg_c.pk))
        self.assertEqual(self.get(f'/portal/liegenschaften/{self.lg_b.pk}/').status_code, 404)

    def test_freigabe_fremder_auftrag_bleibt_404(self):
        fremd = HandwerkerAuftrag.objects.get(ticket=self.fremd_b)
        antwort = self.client_a.post(f'/portal/freigabe/{fremd.pk}/', {'aktion': 'freigeben'})
        self.assertEqual(antwort.status_code, 404)
        fremd.refresh_from_db()
        self.assertEqual(fremd.freigabe_status, 'ausstehend')


class ZugangTests(SchadenWelt):
    def test_anonym_zur_anmeldung(self):
        for pfad in ('/portal/schaeden/', f'/portal/schaeden/{self.fertig.pk}/'):
            antwort = Client().get(pfad)
            self.assertEqual(antwort.status_code, 302)
            self.assertIn('login', antwort['Location'])

    def test_konto_ohne_eigentuemerbezug_geht_zur_startseite(self):
        from ._helfer import _team_user
        c = Client()
        c.force_login(_team_user('nur_team'))
        antwort = c.get('/portal/schaeden/')
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort['Location'], '/portal/')


class DatenschutzTests(SchadenWelt):
    def _alles(self):
        return self.seite() + self.seite(f'/portal/schaeden/{self.fertig.pk}/') \
            + self.seite(f'/portal/schaeden/{self.offen.pk}/') + self.seite(f'/portal/liegenschaften/{self.lg_a.pk}/')

    def test_kein_geheimes_feld_erscheint(self):
        html = self._alles()
        self.assertIn('Sanitär Muster AG', html)          # Gegenprobe: das Erlaubte steht da
        for g in GEHEIM:
            self.assertNotIn(g, html, g)
        self.assertNotIn('RF18GEHEIMREF', html)

    def test_service_gibt_keine_modelle_weiter(self):
        d = dienst.detail(self.a, self.fertig.pk)
        for z in d['verlauf'] + d['auftraege']:
            for wert in z.values():
                self.assertNotIsInstance(wert, (SchadenMeldung, HandwerkerAuftrag, TicketNachricht, Mieter))

    def test_interne_nachricht_und_systemeintrag_bleiben_draussen(self):
        TicketNachricht.objects.create(ticket=self.fertig, absender_name='System', typ='system',
                                       nachricht='GEHEIMNACHRICHT intern', is_intern=True)
        self.assertNotIn('GEHEIMNACHRICHT', self.seite(f'/portal/schaeden/{self.fertig.pk}/'))


class DetailUndVerlaufTests(SchadenWelt):
    def test_auftragsdaten(self):
        html = self.seite(f'/portal/schaeden/{self.fertig.pk}/')
        for text in ('Wasserhahn tropft', 'Sanitär', 'Whg Alphaweg 1', 'Küche, Bad',
                     'Sanitär Muster AG', 'CHF 500', 'CHF 480', 'Freigegeben', 'Bitte zügig.', '10.03.2025',
                     'Ja · CHF 480'):
            self.assertIn(text, html, text)

    def test_verlauf_reihenfolge_und_akteure(self):
        d = dienst.detail(self.a, self.fertig.pk)
        self.assertEqual([e['art'] for e in d['verlauf']],
                         ['meldung', 'auftrag', 'freigabe', 'freigabe', 'arbeit', 'rechnung', 'abschluss'])
        rollen = [str(e['akteur']) for e in d['verlauf']]
        self.assertEqual(rollen, ['Mieter', 'Verwaltung', 'Verwaltung', 'Eigentümer',
                                  'Handwerker Sanitär Muster AG', 'Handwerker Sanitär Muster AG', 'Verwaltung'])
        self.assertEqual(d['verlauf'][3]['datum'], _zeit(2025, 3, 10))
        self.assertEqual(d['verlauf'][3]['text'], 'Bitte zügig.')
        self.assertEqual(d['verlauf'][5]['datum'], date(2025, 5, 2))

    def test_melder_ohne_mieterbezug_heisst_melder(self):
        d = dienst.detail(self.a, self.offen.pk)
        self.assertEqual(str(d['verlauf'][0]['akteur']), 'Melder')

    def test_offener_schaden_zeigt_ausstehende_freigabe_ohne_abschluss(self):
        d = dienst.detail(self.a, self.offen.pk)
        self.assertEqual([e['art'] for e in d['verlauf']], ['meldung', 'auftrag', 'freigabe'])
        self.assertEqual(d['ausstehend'], 1)
        self.assertIsNone(d['erledigt_am'])

    def test_termin_und_storno(self):
        self.a_offen.termin_am = _zeit(2026, 7, 8)
        self.a_offen.termin_status = 'vereinbart'
        self.a_offen.save()
        andere = HandwerkerAuftrag.objects.create(ticket=self.offen, handwerker=self.hw, status='storniert',
                                                  kosten_effektiv=Decimal('99999.00'))
        d = dienst.detail(self.a, self.offen.pk)
        arten = [e['art'] for e in d['verlauf']]
        self.assertIn('termin', arten)
        self.assertIn('storno', arten)
        self.assertIsNone(d['effektiv'], 'Stornierter Auftrag zählt in keiner Summe')
        html = self.seite(f'/portal/schaeden/{self.offen.pk}/')
        self.assertIn('08.07.2026 09:30', html)
        self.assertNotIn('99999', html)
        self.assertTrue(andere.pk)

    def test_storniert_rechnung_gilt_nicht_als_vorhanden(self):
        KreditorenRechnung.objects.filter(pk=self.rechnung.pk).update(status='storniert')
        d = dienst.detail(self.a, self.fertig.pk)
        self.assertFalse(d['auftraege'][0]['rechnung'])
        self.assertNotIn('rechnung', [e['art'] for e in d['verlauf']])

    def test_leerer_schaden_ohne_auftraege(self):
        t = SchadenMeldung.objects.create(titel='Nur gemeldet', liegenschaft=self.lg_a, status='neu')
        html = self.seite(f'/portal/schaeden/{t.pk}/')
        self.assertIn('noch kein Handwerker beauftragt', html)


class FreigabeTests(SchadenWelt):
    def test_formular_nur_bei_ausstehend(self):
        self.assertIn('data-block="freigabe"', self.seite(f'/portal/schaeden/{self.offen.pk}/'))
        self.assertNotIn('data-block="freigabe"', self.seite(f'/portal/schaeden/{self.fertig.pk}/'))

    def test_entscheid_von_der_schadensseite_kehrt_dorthin_zurueck_und_zeigt_entschiedenes(self):
        pfad = f'/portal/schaeden/{self.offen.pk}/'
        antwort = self.client_a.post(f'/portal/freigabe/{self.a_offen.pk}/',
                                     {'aktion': 'ablehnen', 'kommentar': 'Zu teuer', 'next': pfad})
        self.assertRedirects(antwort, pfad)
        self.a_offen.refresh_from_db()
        self.assertEqual(self.a_offen.freigabe_status, 'abgelehnt')
        html = self.seite(pfad)
        for text in ('Abgelehnt', 'Zu teuer', 'Freigabe abgelehnt'):
            self.assertIn(text, html)
        self.assertNotIn('data-block="freigabe"', html)

    def test_fremdes_rueckziel_wird_ignoriert(self):
        antwort = self.client_a.post(f'/portal/freigabe/{self.a_offen.pk}/',
                                     {'aktion': 'freigeben', 'next': 'https://boese.example/'})
        self.assertRedirects(antwort, '/portal/', fetch_redirect_response=False)

    def test_ohne_next_wie_bisher_zur_uebersicht(self):
        antwort = self.client_a.post(f'/portal/freigabe/{self.a_offen.pk}/', {'aktion': 'freigeben'})
        self.assertRedirects(antwort, '/portal/', fetch_redirect_response=False)

    def test_uebersicht_verlinkt_den_schaden(self):
        html = self.seite('/portal/')
        self.assertIn(f'/portal/schaeden/{self.offen.pk}/', html)
        self.assertIn('/portal/schaeden/?status=offen', html)

    def test_nach_mandatsende_lesend_ohne_formular(self):
        self.a_offen.freigabe_status = 'ausstehend'
        self.a_offen.save()
        _vertraege_beenden(self.lg_a)
        archiv.archivieren(self.lg_a, grund='Verkauft')
        archiv.archivieren(self.a, grund='Mandat beendet', mandatsende=date(2026, 3, 31))
        html = self.seite(f'/portal/schaeden/{self.offen.pk}/')
        self.assertIn('Dach undicht', html)                      # lesend erreichbar
        self.assertIn('Mandat beendet', html)
        self.assertNotIn('data-block="freigabe"', html)
        self.assertIn('Wasserhahn tropft', self.seite())


class HaertungTests(SchadenWelt):
    """Nach Mandatsende nimmt auch der direkte POST keinen Entscheid mehr an; die Übersicht zeigt keine interne
    Bemerkung der Verwaltung an den Handwerker (Gegenprobe: die Zeile in `portal_freigabe` bzw. die Bemerkung in
    `_offene_freigaben` wieder einsetzen, und der jeweilige Test wird rot)."""

    def test_direkter_post_nach_mandatsende_aendert_nichts(self):
        self.a_offen.freigabe_status = 'ausstehend'
        self.a_offen.save()
        _vertraege_beenden(self.lg_a)
        archiv.archivieren(self.lg_a, grund='Verkauft')
        archiv.archivieren(self.a, grund='Mandat beendet', mandatsende=date(2026, 3, 31))
        self.client_a.post(f'/portal/freigabe/{self.a_offen.pk}/', {'aktion': 'freigeben'})
        self.a_offen.refresh_from_db()
        self.assertEqual(self.a_offen.freigabe_status, 'ausstehend')

    def test_vor_mandatsende_gilt_der_entscheid(self):
        self.client_a.post(f'/portal/freigabe/{self.a_offen.pk}/', {'aktion': 'freigeben'})
        self.a_offen.refresh_from_db()
        self.assertEqual(self.a_offen.freigabe_status, 'freigegeben')

    def test_uebersicht_zeigt_die_interne_bemerkung_nicht(self):
        HandwerkerAuftrag.objects.filter(pk=self.a_offen.pk).update(
            bemerkung='INTERNE-ANWEISUNG-AN-HANDWERKER', freigabe_status='ausstehend')
        self.assertNotIn('INTERNE-ANWEISUNG-AN-HANDWERKER', self.seite('/portal/'))


class FilterTests(SchadenWelt):
    def test_status(self):
        offen = self.seite('/portal/schaeden/?status=offen')
        self.assertIn('Dach undicht', offen)
        self.assertNotIn('Wasserhahn', offen)
        erledigt = self.seite('/portal/schaeden/?status=erledigt')
        self.assertIn('Wasserhahn', erledigt)
        self.assertNotIn('Dach undicht', erledigt)

    def test_jahr(self):
        self.assertNotIn('Dach undicht', self.seite('/portal/schaeden/?jahr=2025'))
        self.assertIn('Wasserhahn', self.seite('/portal/schaeden/?jahr=2025'))
        self.assertIn('Dach undicht', self.seite('/portal/schaeden/?jahr=2026'))

    def test_liegenschaft_und_unsinn(self):
        zweite, _e, _l, _v = _liegenschaft(self.a, 'Zweitweg 2')
        SchadenMeldung.objects.create(titel='Zweitschaden', liegenschaft=zweite, status='neu')
        self.assertNotIn('Zweitschaden', self.seite(f'/portal/schaeden/?liegenschaft={self.lg_a.pk}'))
        self.assertNotIn('Wasserhahn', self.seite(f'/portal/schaeden/?liegenschaft={zweite.pk}'))
        # Unsinnige Werte fallen auf «alle» zurück, kein Fehler.
        html = self.seite('/portal/schaeden/?liegenschaft=abc&status=x&jahr=99999&seite=zz')
        self.assertIn('Wasserhahn', html)

    def test_leerer_bestand(self):
        c = Client()
        leer = _eigentuemer('Leer AG', 'eig_leer')
        c.force_login(leer.benutzer)
        html = c.get('/portal/schaeden/').content.decode()
        self.assertIn('Noch keine Schäden', html)

    def test_seitenweise(self):
        for i in range(30):
            SchadenMeldung.objects.create(titel=f'Massenschaden {i}', liegenschaft=self.lg_a, status='neu')
        html = self.seite()
        self.assertIn('Seite 1 von 2', html)
        self.assertIn('Seite 2 von 2', self.seite('/portal/schaeden/?seite=2'))


class HistorieTests(SchadenWelt):
    def test_summen_je_jahr(self):
        h = dienst.historie(self.a, self.lg_a.pk)
        zeilen = {z['jahr']: z for z in h['zeilen']}
        self.assertEqual(zeilen[2025]['anzahl'], 1)
        self.assertEqual(zeilen[2025]['effektiv'], Decimal('480.00'))
        self.assertEqual(zeilen[2026]['offen'], 1)
        self.assertIsNone(zeilen[2026]['effektiv'], 'Keine effektiven Kosten erfasst ist nicht 0')
        self.assertEqual(zeilen[2026]['geschaetzt_offen'], Decimal('3200.00'))
        self.assertEqual([z['jahr'] for z in h['zeilen']], [2026, 2025])
        self.assertEqual((h['anzahl'], h['offen'], h['effektiv']), (2, 1, Decimal('480.00')))

    def test_seite_der_liegenschaft(self):
        html = self.seite(f'/portal/liegenschaften/{self.lg_a.pk}/')
        self.assertIn('Reparaturhistorie', html)
        self.assertIn('CHF 480', html)
        self.assertIn(f'/portal/schaeden/?liegenschaft={self.lg_a.pk}&amp;jahr=2025', html)
        self.assertNotIn('7654', html)

    def test_liegenschaft_ohne_schaeden(self):
        SchadenMeldung.objects.filter(liegenschaft=self.lg_a).delete()
        html = self.seite(f'/portal/liegenschaften/{self.lg_a.pk}/')
        self.assertIn('kein Schaden gemeldet', html)


class AbfragenTests(SchadenWelt):
    def _zaehle(self, pfad):
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.get(pfad).status_code, 200)
        return len(ctx)

    def test_abfragen_wachsen_nicht_mit_dem_bestand(self):
        seiten = ('/portal/schaeden/', f'/portal/schaeden/{self.fertig.pk}/',
                  f'/portal/liegenschaften/{self.lg_a.pk}/')
        for p in seiten:
            self._zaehle(p)                                       # Aufwärmen
        klein = {p: self._zaehle(p) for p in seiten}
        for i in range(6):
            t = SchadenMeldung.objects.create(titel=f'Zusatz {i}', liegenschaft=self.lg_a,
                                              betroffene_einheit=self.einheit_a, status='in_bearbeitung')
            HandwerkerAuftrag.objects.create(ticket=t, handwerker=Handwerker.objects.create(firma=f'HW {i}'),
                                             kosten_geschaetzt=Decimal('100'), freigabe_status='ausstehend')
        gross = {p: self._zaehle(p) for p in seiten}
        self.assertEqual(gross, klein)

    ERWARTET = {'liste': 20, 'detail': 15}

    def test_tatsaechliche_zahl(self):
        self._zaehle('/portal/schaeden/')
        self.assertEqual(self._zaehle('/portal/schaeden/'), self.ERWARTET['liste'])
        self._zaehle(f'/portal/schaeden/{self.fertig.pk}/')
        self.assertEqual(self._zaehle(f'/portal/schaeden/{self.fertig.pk}/'), self.ERWARTET['detail'])


class SpracheTests(SchadenWelt):
    def test_franzoesisch_und_italienisch(self):
        for sprache, erwartet in (('fr', ('Sinistres et mandats', 'Historique', 'Mandat attribué')),
                                  ('it', ('Danni e incarichi', 'Cronologia', 'Incarico assegnato'))):
            html = ''.join(self.get(p, HTTP_ACCEPT_LANGUAGE=sprache).content.decode()
                           for p in (f'/portal/schaeden/{self.fertig.pk}/', '/portal/schaeden/'))
            for text in erwartet:
                self.assertIn(text, html, (sprache, text))


class AboGuardTests(SchadenWelt):
    def test_neue_seiten_haengen_am_modul_eigentuemerportal(self):
        from abo.zugang import merkmal_der_view
        for pfad in ('/portal/schaeden/', f'/portal/schaeden/{self.fertig.pk}/'):
            self.assertEqual(merkmal_der_view(pfad), 'eigentuemerportal', pfad)
