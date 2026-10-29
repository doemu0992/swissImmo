"""Vier-Augen-Prinzip bei Kreditorenzahlungen ab der Freigabelimite (Etappe 2, SICH-12 / FUNK-08).

Der Befund: Ein Verwalter konnte seine eigene Lieferantenrechnung erfassen,
freigeben, bezahlen und in eine Zahlungsdatei nehmen. Jetzt braucht jede Rechnung
ab dem Limit der Organisation (Vorgabe CHF 5'000, Rechnungsbetrag) die Freigabe
einer zweiten Person; wer die Zahlung vorgelegt hat, darf sie nicht freigeben.

Gegenprobe der Kernzusage: In `core/views/fw/kreditoren.py` den Aufruf von
`_vier_augen_pruefen` (Bezahlen, `_auswahl`) entfernen: Die Tests
`test_ab_limit_wird_nicht_bezahlt`, `test_zahllauf_*` und `test_teilzahlung_*`
sind dann rot (genau das war der Befund). In `finance/freigabe.py::freigeben`
die Prüfung `beantragt_von_id == user.pk` entfernen: `test_vorleger_gibt_nicht_selbst_frei`
ist rot.
"""
from decimal import Decimal

from django.contrib.messages import get_messages
from django.utils import timezone

from ._parallel import NUR_POSTGRES, parallel
from ._rollen import RollenBasis, RollenBasisTransaktion

IBAN = 'CH9300762011623852957'


class _VierAugenWerkzeug:
    """Bausteine für beide Basisklassen (mit und ohne umschliessende Transaktion)."""

    def setUp(self):
        super().setUp()
        from core.tenancy import organisation_kontext
        from finance.booking import ensure_kontenplan
        self.org.iban = 'CH5604835012345678009'
        self.org.save(update_fields=['iban'])
        with organisation_kontext(self.org):
            ensure_kontenplan()

    def post(self, rolle, url, daten=None):
        c = self.client_von(rolle)
        antwort = c.post(url, daten or {})
        return antwort, [str(m) for m in get_messages(antwort.wsgi_request)]

    def stand(self, k):
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.org):
            k.refresh_from_db()
        return k

    def zahlungen(self, k):
        from core.tenancy import organisation_kontext
        from finance.models import KreditorenZahlung
        with organisation_kontext(self.org):
            return KreditorenZahlung.objects.filter(kreditor=k, status='verbucht').count()

    def protokoll(self, text):
        from core.models import AktivitaetsLog
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.org):
            return list(AktivitaetsLog.objects.filter(aktion__startswith=text).order_by('id'))

    def bezahlen(self, rolle, k, **extra):
        return self.post(rolle, '/neu/kreditoren/bezahlen/', {'rechnung_id': k.pk, **extra})

    def freigeben_der_zahlung(self, rolle, k):
        return self.post(rolle, f'/neu/kreditoren/{k.pk}/zahlung-freigeben/')

    def vorlegen(self, rolle, k):
        return self.post(rolle, f'/neu/kreditoren/{k.pk}/zahlung-vorlegen/')


class VierAugenBasis(_VierAugenWerkzeug, RollenBasis):
    pass


class LimitTests(VierAugenBasis):

    def test_vorgabe_ist_fuenftausend(self):
        self.org.refresh_from_db()
        self.assertEqual(self.org.freigabelimit_kreditoren, Decimal('5000.00'))

    def test_unter_dem_limit_wird_direkt_bezahlt(self):
        k = self.kreditor('4999.99')
        self.bezahlen('buchhaltung', k)
        self.assertEqual(self.zahlungen(k), 1)
        self.assertEqual(self.stand(k).status, 'bezahlt')

    def test_ab_limit_wird_nicht_bezahlt(self):
        """Genau am Limit (>=) greift die Freigabe."""
        k = self.kreditor('5000.00')
        _antwort, meldungen = self.bezahlen('buchhaltung', k)
        self.assertEqual(self.zahlungen(k), 0)
        self.assertEqual(self.stand(k).status, 'freigegeben')
        self.assertTrue(any('zweite Person' in m for m in meldungen), meldungen)

    def test_sperre_legt_die_zahlung_vor_und_protokolliert(self):
        k = self.kreditor('7500.00')
        self.bezahlen('buchhaltung', k)
        k = self.stand(k)
        self.assertEqual(k.zahlung_beantragt_von, self.benutzer['buchhaltung'])
        self.assertIsNotNone(k.zahlung_beantragt_am)
        self.assertEqual(len(self.protokoll('Zahlung zur Freigabe vorgelegt')), 1)
        self.assertEqual(len(self.protokoll('Zahlung gesperrt')), 1)

    def test_ohne_limit_kein_vier_augen(self):
        self.org.freigabelimit_kreditoren = None
        self.org.save(update_fields=['freigabelimit_kreditoren'])
        k = self.kreditor('90000.00')
        self.bezahlen('verwalter', k)
        self.assertEqual(self.zahlungen(k), 1)

    def test_limit_null_verlangt_fuer_jede_zahlung(self):
        self.org.freigabelimit_kreditoren = Decimal('0.00')
        self.org.save(update_fields=['freigabelimit_kreditoren'])
        k = self.kreditor('10.00')
        self.bezahlen('verwalter', k)
        self.assertEqual(self.zahlungen(k), 0)

    def test_limit_je_organisation(self):
        """Das Limit der anderen Verwaltung gilt hier nicht."""
        from crm.models import Organisation
        Organisation.objects.filter(pk=self.b.organisation.pk).update(freigabelimit_kreditoren=Decimal('1.00'))
        k = self.kreditor('4000.00')
        self.bezahlen('buchhaltung', k)
        self.assertEqual(self.zahlungen(k), 1)

    def test_teilzahlung_umgeht_das_limit_nicht(self):
        """Massgebend ist der Rechnungsbetrag: 4'999 auf eine Rechnung über 20'000 sind gesperrt."""
        k = self.kreditor('20000.00')
        self.bezahlen('buchhaltung', k, betrag='4999.00')
        self.assertEqual(self.zahlungen(k), 0)


class FreigabeTests(VierAugenBasis):

    def test_vorleger_gibt_nicht_selbst_frei(self):
        k = self.kreditor('6000.00')
        self.vorlegen('verwalter', k)
        _a, meldungen = self.freigeben_der_zahlung('verwalter', k)
        self.assertIsNone(self.stand(k).zahlung_freigegeben_von)
        self.assertTrue(any('nicht selbst' in m for m in meldungen), meldungen)
        self.assertEqual(len(self.protokoll('Zahlungsfreigabe abgelehnt')), 1)

    def test_zweite_person_gibt_frei_und_die_zahlung_geht(self):
        k = self.kreditor('6000.00')
        self.bezahlen('buchhaltung', k)                          # sperrt und legt vor
        self.freigeben_der_zahlung('verwalter', k)
        k = self.stand(k)
        self.assertEqual(k.zahlung_freigegeben_von, self.benutzer['verwalter'])
        self.assertEqual(k.zahlung_freigabe_betrag, Decimal('6000.00'))
        self.bezahlen('buchhaltung', k)
        self.assertEqual(self.zahlungen(k), 1)
        self.assertEqual(self.stand(k).status, 'bezahlt')
        eintrag = self.protokoll('Zahlung freigegeben')[0]
        self.assertEqual(eintrag.benutzer, self.benutzer['verwalter'])
        self.assertIn('vorgelegt von', eintrag.details)
        self.assertIn(self.benutzer['buchhaltung'].username, eintrag.details)

    def test_verwalter_der_selbst_ausloesen_will_braucht_eine_zweite_person(self):
        k = self.kreditor('6000.00')
        self.bezahlen('verwalter', k)
        self.assertEqual(self.zahlungen(k), 0)
        self.freigeben_der_zahlung('verwalter', k)
        self.assertEqual(self.zahlungen(k), 0)
        self.freigeben_der_zahlung('verwalter2', k)
        self.bezahlen('verwalter', k)
        self.assertEqual(self.zahlungen(k), 1)

    def test_inhaber_ist_keine_ausnahme(self):
        k = self.kreditor('6000.00')
        self.bezahlen('inhaber', k)
        self.freigeben_der_zahlung('inhaber', k)
        self.assertIsNone(self.stand(k).zahlung_freigegeben_von)
        self.bezahlen('inhaber', k)
        self.assertEqual(self.zahlungen(k), 0)

    def test_buchhaltung_und_sachbearbeiter_geben_nicht_frei(self):
        k = self.kreditor('6000.00')
        self.vorlegen('verwalter', k)
        for rolle in ('buchhaltung', 'sachbearbeiter', 'lesezugriff', 'hauswart'):
            with self.subTest(rolle=rolle):
                antwort, _m = self.freigeben_der_zahlung(rolle, k)
                self.assertEqual(antwort.status_code, 403)
        self.assertIsNone(self.stand(k).zahlung_freigegeben_von)

    def test_nur_buchhaltung_und_verwaltung_legen_vor(self):
        k = self.kreditor('6000.00')
        for rolle in ('sachbearbeiter', 'lesezugriff', 'hauswart'):
            with self.subTest(rolle=rolle):
                antwort, _m = self.vorlegen(rolle, k)
                self.assertEqual(antwort.status_code, 403)
        self.assertIsNone(self.stand(k).zahlung_beantragt_von)
        self.vorlegen('buchhaltung', k)
        self.assertEqual(self.stand(k).zahlung_beantragt_von, self.benutzer['buchhaltung'])

    def test_erneutes_vorlegen_aendert_den_vorleger_nicht(self):
        """Sonst könnte sich der Freigeber durch Vorlegen «freispielen»."""
        k = self.kreditor('6000.00')
        self.vorlegen('buchhaltung', k)
        self.vorlegen('verwalter', k)
        self.assertEqual(self.stand(k).zahlung_beantragt_von, self.benutzer['buchhaltung'])
        self.freigeben_der_zahlung('verwalter', k)
        self.assertEqual(self.stand(k).zahlung_freigegeben_von, self.benutzer['verwalter'])

    def test_freigabe_ohne_vorlage_ist_nicht_moeglich(self):
        k = self.kreditor('6000.00')
        self.freigeben_der_zahlung('verwalter', k)
        self.assertIsNone(self.stand(k).zahlung_freigegeben_von)

    def test_freigabe_unter_dem_limit_ist_unnoetig(self):
        k = self.kreditor('100.00')
        self.vorlegen('buchhaltung', k)
        self.freigeben_der_zahlung('verwalter', k)
        self.assertIsNone(self.stand(k).zahlung_freigegeben_von)

    def test_iban_aenderung_nach_der_freigabe_sperrt_wieder(self):
        """Der klassische Betrug: IBAN tauschen, nachdem jemand freigegeben hat."""
        from core.tenancy import organisation_kontext
        from finance.models import KreditorenRechnung
        k = self.kreditor('6000.00')
        self.vorlegen('buchhaltung', k)
        self.freigeben_der_zahlung('verwalter', k)
        with organisation_kontext(self.org):
            KreditorenRechnung.objects.filter(pk=k.pk).update(iban='CH4431999123000889012')
        self.bezahlen('buchhaltung', k)
        self.assertEqual(self.zahlungen(k), 0)

    def test_betragsaenderung_nach_der_freigabe_sperrt_wieder(self):
        from core.tenancy import organisation_kontext
        from finance.models import KreditorenRechnung
        k = self.kreditor('6000.00')
        self.vorlegen('buchhaltung', k)
        self.freigeben_der_zahlung('verwalter', k)
        with organisation_kontext(self.org):
            KreditorenRechnung.objects.filter(pk=k.pk).update(betrag=Decimal('9000.00'))
        self.bezahlen('buchhaltung', k)
        self.assertEqual(self.zahlungen(k), 0)

    def test_zuruecknehmen_sperrt_wieder(self):
        k = self.kreditor('6000.00')
        self.vorlegen('buchhaltung', k)
        self.freigeben_der_zahlung('verwalter', k)
        self.post('buchhaltung', f'/neu/kreditoren/{k.pk}/zahlung-zuruecknehmen/')
        k = self.stand(k)
        self.assertIsNone(k.zahlung_freigegeben_von)
        self.assertIsNone(k.zahlung_beantragt_von)
        self.bezahlen('buchhaltung', k)
        self.assertEqual(self.zahlungen(k), 0)
        self.assertEqual(len(self.protokoll('Zahlungsfreigabe zurückgenommen')), 1)

    def test_get_aendert_nichts(self):
        k = self.kreditor('6000.00')
        c = self.client_von('verwalter')
        for ende in ('zahlung-vorlegen', 'zahlung-freigeben', 'zahlung-zuruecknehmen'):
            c.get(f'/neu/kreditoren/{k.pk}/{ende}/')
        k = self.stand(k)
        self.assertIsNone(k.zahlung_beantragt_von)

    def test_fremde_rechnung_ergibt_404(self):
        from core.tenancy import organisation_kontext
        from finance.models import KreditorenRechnung
        with organisation_kontext(self.b.organisation):
            fremd = KreditorenRechnung.objects.create(
                lieferant='Fremd', betrag=Decimal('9000'), status='freigegeben', liegenschaft=self.b.liegenschaft)
        for ende in ('zahlung-vorlegen', 'zahlung-freigeben', 'zahlung-zuruecknehmen'):
            with self.subTest(ende=ende):
                antwort, _m = self.post('verwalter', f'/neu/kreditoren/{fremd.pk}/{ende}/')
                self.assertEqual(antwort.status_code, 404)


class ZahllaufTests(VierAugenBasis):

    def _datei(self, rolle, *ks):
        return self.post(rolle, '/neu/zahllauf/', {
            'aktion': 'datei', 'rechnung_ids': [k.pk for k in ks],
            'ausfuehrungsdatum': timezone.localdate().isoformat()})

    def test_zahllauf_nimmt_gesperrte_rechnung_nicht_mit(self):
        klein = self.kreditor('800.00', lieferant='Klein AG')
        gross = self.kreditor('8000.00', lieferant='Gross AG')
        antwort, meldungen = self._datei('buchhaltung', klein, gross)
        self.assertTrue(antwort['Content-Type'].startswith('application/xml'), meldungen)
        xml = antwort.content.decode()
        self.assertIn('Klein AG', xml)
        self.assertNotIn('Gross AG', xml)
        self.assertEqual(self.stand(klein).status, 'in_zahlung')
        gross = self.stand(gross)
        self.assertEqual(gross.status, 'freigegeben')
        self.assertEqual(gross.zahlung_beantragt_von, self.benutzer['buchhaltung'])

    def test_zahllauf_mit_nur_gesperrten_liefert_keine_datei(self):
        gross = self.kreditor('8000.00', lieferant='Gross AG')
        antwort, _m = self._datei('buchhaltung', gross)
        self.assertFalse(antwort.get('Content-Type', '').startswith('application/xml'))
        self.assertEqual(self.stand(gross).status, 'freigegeben')

    def test_zahllauf_mit_freigabe_nimmt_sie_mit(self):
        gross = self.kreditor('8000.00', lieferant='Gross AG')
        self.vorlegen('buchhaltung', gross)
        self.freigeben_der_zahlung('verwalter', gross)
        antwort, meldungen = self._datei('buchhaltung', gross)
        self.assertTrue(antwort['Content-Type'].startswith('application/xml'), meldungen)
        self.assertIn('Gross AG', antwort.content.decode())
        self.assertEqual(self.stand(gross).status, 'in_zahlung')

    def test_zahllauf_sammelbestaetigung_umgeht_die_sperre_nicht(self):
        """Ohne Datei direkt als bezahlt bestätigen darf eine gesperrte Rechnung nicht."""
        gross = self.kreditor('8000.00', lieferant='Gross AG')
        self.post('verwalter', '/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': [gross.pk]})
        self.assertEqual(self.zahlungen(gross), 0)
        self.assertEqual(self.stand(gross).status, 'freigegeben')

    def test_zuruecksetzen_bleibt_moeglich(self):
        """Eine Datei, die nicht ausgeführt wurde, lässt sich zurücknehmen (kein Geldabfluss)."""
        gross = self.kreditor('8000.00', lieferant='Gross AG')
        self.vorlegen('buchhaltung', gross)
        self.freigeben_der_zahlung('verwalter', gross)
        self._datei('buchhaltung', gross)
        self.post('buchhaltung', '/neu/zahllauf/', {'aktion': 'zuruecksetzen', 'rechnung_ids': [gross.pk]})
        self.assertEqual(self.stand(gross).status, 'freigegeben')

    def test_liste_zeigt_den_stand(self):
        gross = self.kreditor('8000.00', lieferant='Gross AG')
        html = self.client_von('buchhaltung').get('/neu/zahllauf/').content.decode()
        self.assertIn('Freigabe einer zweiten Person', html)
        self.vorlegen('buchhaltung', gross)
        html = self.client_von('buchhaltung').get('/neu/zahllauf/').content.decode()
        self.assertIn('vorgelegt von', html)


class ListeTests(VierAugenBasis):

    def test_liste_zeigt_je_rolle_die_richtigen_knoepfe(self):
        k = self.kreditor('6000.00')
        buch = self.client_von('buchhaltung').get('/neu/kreditoren/').content.decode()
        self.assertIn(f'/neu/kreditoren/{k.pk}/zahlung-vorlegen/', buch)
        self.assertNotIn(f'/neu/kreditoren/{k.pk}/zahlung-freigeben/', buch)
        self.assertNotIn('action="/neu/kreditoren/bezahlen/"', buch)
        self.vorlegen('buchhaltung', k)
        verw = self.client_von('verwalter').get('/neu/kreditoren/')
        self.assertContains(verw, f'/neu/kreditoren/{k.pk}/zahlung-freigeben/')
        self.assertContains(verw, 'wartet auf Ihre Freigabe')
        selbst = self.client_von('buchhaltung').get('/neu/kreditoren/').content.decode()
        self.assertNotIn(f'/neu/kreditoren/{k.pk}/zahlung-freigeben/', selbst)
        self.assertIn('wartet auf eine zweite Person', selbst)

    def test_nach_freigabe_erscheint_bezahlen(self):
        k = self.kreditor('6000.00')
        self.vorlegen('buchhaltung', k)
        self.freigeben_der_zahlung('verwalter', k)
        html = self.client_von('buchhaltung').get('/neu/kreditoren/').content.decode()
        self.assertIn('action="/neu/kreditoren/bezahlen/"', html)
        self.assertIn('Freigegeben von', html)


class EinstellungTests(VierAugenBasis):

    def _speichere(self, rolle, **daten):
        return self.post(rolle, '/neu/einstellungen/zahlungsfreigabe/speichern/', daten)

    def _limit(self):
        self.org.refresh_from_db()
        return self.org.freigabelimit_kreditoren

    def test_nur_der_inhaber_aendert(self):
        for rolle in ('verwalter', 'sachbearbeiter', 'buchhaltung', 'lesezugriff', 'hauswart'):
            with self.subTest(rolle=rolle):
                antwort, _m = self._speichere(rolle, freigabelimit='100000')
                self.assertEqual(antwort.status_code, 403)
                self.assertEqual(self._limit(), Decimal('5000.00'))
        self._speichere('inhaber', freigabelimit="12'500.50")
        self.assertEqual(self._limit(), Decimal('12500.50'))

    def test_ausschalten_und_protokoll(self):
        self._speichere('inhaber', ohne_limit='on')
        self.assertIsNone(self._limit())
        eintrag = self.protokoll('Freigabelimite')[0]
        self.assertEqual(eintrag.benutzer, self.benutzer['inhaber'])
        self.assertIn('5000', eintrag.details)
        self.assertEqual(eintrag.kategorie, 'sicherheit')

    def test_ungueltige_eingabe_aendert_nichts(self):
        for roh in ('abc', '-5', '1e999999', '100000000'):
            with self.subTest(roh=roh):
                self._speichere('inhaber', freigabelimit=roh)
                self.assertEqual(self._limit(), Decimal('5000.00'))

    def test_seite_ist_fuer_das_team_lesbar_nicht_fuer_andere(self):
        self.assertEqual(self.client_von('verwalter').get('/neu/einstellungen/zahlungsfreigabe/').status_code, 200)
        for rolle in ('buchhaltung', 'hauswart'):
            self.assertEqual(self.client_von(rolle).get('/neu/einstellungen/zahlungsfreigabe/').status_code, 403)
        seite = self.client_von('verwalter').get('/neu/einstellungen/zahlungsfreigabe/')
        self.assertContains(seite, 'Nur der Inhaber ändert')
        self.assertContains(self.client_von('inhaber').get('/neu/einstellungen/zahlungsfreigabe/'), 'type="submit"')

    def test_aenderung_wirkt_auf_die_zahlung(self):
        self._speichere('inhaber', freigabelimit='100000')
        k = self.kreditor('6000.00')
        self.bezahlen('buchhaltung', k)
        self.assertEqual(self.zahlungen(k), 1)


@NUR_POSTGRES
class ParallelTests(_VierAugenWerkzeug, RollenBasisTransaktion):
    """Echte Threads gegen PostgreSQL (SQLite serialisiert Schreiber und verdeckt Rennen)."""

    def test_gleichzeitiges_vorlegen_zweier_personen_hat_einen_vorleger(self):
        k = self.kreditor('6000.00')
        rollen = ['buchhaltung', 'verwalter']

        def arbeit(i):
            return self.vorlegen(rollen[i], k)[0].status_code

        ergebnisse = parallel(2, arbeit)
        self.assertEqual([e for e in ergebnisse if isinstance(e, BaseException)], [])
        k = self.stand(k)
        self.assertIn(k.zahlung_beantragt_von, (self.benutzer['buchhaltung'], self.benutzer['verwalter']))
        self.assertEqual(len(self.protokoll('Zahlung zur Freigabe vorgelegt')), 1)

    def test_vier_parallele_klicks_auf_eine_freigegebene_zahlung_buchen_einmal(self):
        k = self.kreditor('6000.00')
        self.vorlegen('buchhaltung', k)
        self.freigeben_der_zahlung('verwalter', k)
        ergebnisse = parallel(4, lambda i: self.bezahlen('buchhaltung', k)[0].status_code)
        self.assertEqual([e for e in ergebnisse if isinstance(e, BaseException)], [])
        self.assertEqual(self.zahlungen(k), 1)

    def test_freigabe_und_zuruecknehmen_gleichzeitig_enden_konsistent(self):
        k = self.kreditor('6000.00')
        self.vorlegen('buchhaltung', k)

        def arbeit(i):
            if i == 0:
                return self.freigeben_der_zahlung('verwalter', k)[0].status_code
            return self.post('buchhaltung', f'/neu/kreditoren/{k.pk}/zahlung-zuruecknehmen/')[0].status_code

        ergebnisse = parallel(2, arbeit)
        self.assertEqual([e for e in ergebnisse if isinstance(e, BaseException)], [])
        k = self.stand(k)
        # Entweder ist beides weg (zurückgenommen nach der Freigabe) oder nur die Vorlage
        # ist weg, und die Freigabe scheiterte («nicht vorgelegt») — nie eine Freigabe ohne Vorlage.
        if k.zahlung_freigegeben_von_id:
            self.assertIsNotNone(k.zahlung_beantragt_von_id)
