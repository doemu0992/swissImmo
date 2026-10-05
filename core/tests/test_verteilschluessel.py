"""Verteilschlüssel der Liegenschaft in der Nebenkostenabrechnung (opt-in).

Die Modelle `LiegenschaftVerteilschluessel` und `Verteilschluessel` existierten, die Engine
las sie nicht. Jetzt wirken sie — aber nur, wenn `Liegenschaft.verteilschluessel_aktiv` gesetzt
ist. Der erste Test ist die Absicherung dagegen, dass vorhandene Zeilen über Nacht bestehende
Abrechnungen verändern.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.tests._helfer import (Einheit, Liegenschaft, Mieter, Mietvertrag, _seed_konten,
                                _test_organisation)

ZIMMER = (Decimal('2.0'), Decimal('3.0'), Decimal('5.0'))


class _Basis(TestCase):
    def setUp(self):
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg
        _seed_konten()
        self.org = _test_organisation()
        self.org.nk_honorar_prozent = Decimal('0')       # keine Honorarzeile: Beträge bleiben glatt
        self.org.save()
        self.lg = Liegenschaft.objects.create(organisation=self.org, strasse='Schluesselweg 1', plz='8000',
                                              ort='Zürich', versicherungswert=Decimal('1'))
        self.einheiten = []
        for i, z in enumerate(ZIMMER):
            e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung=f'W{i}', typ='whg',
                                       flaeche_m2=Decimal('50'), zimmer=z, wertquote=Decimal(str((i + 1) * 100)))
            m = Mieter.objects.create(typ='person', vorname='M', nachname=f'N{i}', strasse='x', plz='8000', ort='Zürich')
            Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1), status='aktiv',
                                       netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'))
            self.einheiten.append(e)
        self.p = AbrechnungsPeriode.objects.create(liegenschaft=self.lg, bezeichnung='NK 2025',
                                                   start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        NebenkostenBeleg.objects.create(periode=self.p, kategorie='hauswart', text='Hauswart',
                                        betrag=Decimal('1000.00'), verteilschluessel='m2')

    def schluessel(self, typ, kostenart='hauswartung', **kw):
        from portfolio.models import LiegenschaftVerteilschluessel
        return LiegenschaftVerteilschluessel.objects.create(
            liegenschaft=self.lg, kostenart=kostenart, typ=typ, gueltig_ab=date(2025, 1, 1), **kw)

    def anteile(self):
        from core.utils.billing import berechne_abrechnung
        r = berechne_abrechnung(self.p.id)
        self.assertNotIn('error', r)
        return r, {z['einheit']: z['kosten_anteil'] for z in r['abrechnungen'] if z['typ'] != 'leerstand'}

    def aktivieren(self):
        self.lg.verteilschluessel_aktiv = True
        self.lg.save(update_fields=['verteilschluessel_aktiv'])


class OhneKennzeichenAendertSichNichts(_Basis):
    def test_vorhandene_schluessel_wirken_nicht_solange_das_kennzeichen_aus_ist(self):
        _, vorher = self.anteile()
        self.schluessel('zimmer')
        for e, w in zip(self.einheiten, ('50', '30', '20')):
            e.verteilschluessel.create(kostenart='hauswartung', typ='prozent', wert=Decimal(w), gueltig_ab=date(2025, 1, 1))
        _, nachher = self.anteile()
        self.assertEqual(vorher, nachher)
        self.assertEqual(set(nachher.values()), {Decimal('333.33'), Decimal('333.34')})   # Fläche, wie bisher


class Zimmer(_Basis):
    def test_kosten_folgen_der_zimmerzahl(self):
        self.schluessel('zimmer')
        self.aktivieren()
        r, a = self.anteile()
        self.assertEqual(a, {'W0': Decimal('200.00'), 'W1': Decimal('300.00'), 'W2': Decimal('500.00')})
        self.assertEqual(r['differenz'], Decimal('0.00'))
        self.assertEqual(r['total_kosten'], Decimal('1000.00'))
        self.assertEqual([b['schluessel'] for b in r['belege_details']], ['zimmer'])

    def test_ohne_zimmerzahl_wird_nach_flaeche_verteilt_und_gewarnt(self):
        self.schluessel('zimmer')
        self.aktivieren()
        for e in self.einheiten:
            e.zimmer = None
            e.save()
        r, a = self.anteile()
        self.assertEqual(sum(a.values()), Decimal('1000.00'))                 # nichts verschwindet
        self.assertTrue(any('nicht anwendbar' in w for w in r['warnungen']))


class Wertquote(_Basis):
    def test_kosten_folgen_der_wertquote(self):
        self.schluessel('anteil')
        self.aktivieren()
        _, a = self.anteile()
        # Wertquoten 100/200/300 → 1/6, 2/6, 3/6 von 1000.00
        self.assertEqual(a, {'W0': Decimal('166.67'), 'W1': Decimal('333.33'), 'W2': Decimal('500.00')})


class ProzentJeEinheit(_Basis):
    def _prozente(self, werte):
        self.schluessel('prozent')
        for e, w in zip(self.einheiten, werte):
            e.verteilschluessel.create(kostenart='hauswartung', typ='prozent', wert=Decimal(w), gueltig_ab=date(2025, 1, 1))
        self.aktivieren()

    def test_prozentanteile_werden_angewendet(self):
        self._prozente(('50', '30', '20'))
        r, a = self.anteile()
        self.assertEqual(a, {'W0': Decimal('500.00'), 'W1': Decimal('300.00'), 'W2': Decimal('200.00')})
        self.assertEqual(r['differenz'], Decimal('0.00'))

    def test_summe_ungleich_100_faellt_auf_flaeche_zurueck(self):
        self._prozente(('50', '30', '10'))
        r, a = self.anteile()
        self.assertEqual(sum(a.values()), Decimal('1000.00'))
        self.assertTrue(any('ergeben 90' in w for w in r['warnungen']))
        self.assertEqual(set(a.values()), {Decimal('333.33'), Decimal('333.34')})


class Abgrenzung(_Basis):
    def test_heizkosten_bleiben_bei_der_heizkostenlogik(self):
        from finance.models import NebenkostenBeleg
        NebenkostenBeleg.objects.create(periode=self.p, kategorie='heizung', text='Gas', betrag=Decimal('900.00'))
        self.schluessel('zimmer', kostenart='heizung')
        self.aktivieren()
        r, a = self.anteile()
        heizung = [b for b in r['belege_details'] if b['kategorie'].startswith('Heizung')][0]
        self.assertNotEqual(heizung['schluessel'], 'zimmer')

    def test_schluessel_ausserhalb_der_gueltigkeit_wirkt_nicht(self):
        self.schluessel('zimmer', gueltig_bis=date(2024, 12, 31))
        self.aktivieren()
        _, a = self.anteile()
        self.assertEqual(set(a.values()), {Decimal('333.33'), Decimal('333.34')})

    def test_pauschal_wird_nicht_geraten(self):
        self.schluessel('pauschal', wert=Decimal('10'))
        self.aktivieren()
        _, a = self.anteile()
        self.assertEqual(set(a.values()), {Decimal('333.33'), Decimal('333.34')})

    def test_schluessel_einer_anderen_liegenschaft_wirkt_nicht(self):
        from portfolio.models import LiegenschaftVerteilschluessel
        fremd = Liegenschaft.objects.create(organisation=self.org, strasse='Anderswo 2', plz='8000', ort='Zürich',
                                            versicherungswert=Decimal('1'))
        LiegenschaftVerteilschluessel.objects.create(liegenschaft=fremd, kostenart='hauswartung', typ='zimmer',
                                                     gueltig_ab=date(2025, 1, 1))
        self.aktivieren()
        _, a = self.anteile()
        self.assertEqual(set(a.values()), {Decimal('333.33'), Decimal('333.34')})


class Oberflaeche(_Basis):
    """Pflege der Schlüssel über die Seite: Fehler am Feld, nichts gespeichert bei Fehler."""

    def setUp(self):
        super().setUp()
        from django.test import Client
        from core.tests._helfer import _team_user
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))
        self.url = f'/neu/liegenschaften/{self.lg.id}/verteilschluessel/'

    def _neu(self, **kw):
        daten = {'aktion': 'neu', 'kostenart': 'hauswartung', 'typ': 'zimmer', 'gueltig_ab': '2025-01-01', 'gueltig_bis': ''}
        daten.update(kw)
        return self.c.post(self.url, daten)

    def test_schluessel_anlegen_und_in_der_abrechnung_wirksam(self):
        from portfolio.models import LiegenschaftVerteilschluessel
        antwort = self._neu()
        self.assertRedirects(antwort, self.url, fetch_redirect_response=False)
        self.assertEqual(LiegenschaftVerteilschluessel.objects.filter(liegenschaft=self.lg).count(), 1)
        self.aktivieren()
        _, a = self.anteile()
        self.assertEqual(a['W2'], Decimal('500.00'))

    def test_fehler_stehen_am_feld_und_es_wird_nichts_gespeichert(self):
        from portfolio.models import LiegenschaftVerteilschluessel
        a = self._neu(kostenart='heizung')
        self.assertContains(a, 'id_kostenart_fehler', status_code=400)
        b = self._neu(typ='pauschal')
        self.assertContains(b, 'id_typ_fehler', status_code=400)
        c = self._neu(gueltig_ab='2025-06-01', gueltig_bis='2025-01-01')
        self.assertContains(c, 'id_gueltig_bis_fehler', status_code=400)
        self.assertEqual(LiegenschaftVerteilschluessel.objects.count(), 0)

    def test_ueberlappender_schluessel_derselben_kostenart_wird_abgelehnt(self):
        self._neu(gueltig_bis='2025-12-31')          # fester Zeitraum: kein offener Vorgänger
        zweiter = self._neu(typ='anteil', gueltig_ab='2025-06-01')
        self.assertContains(zweiter, 'id_gueltig_ab_fehler', status_code=400)

    def test_neuer_schluessel_beendet_den_offenen_vorgaenger_am_vortag(self):
        from portfolio.models import LiegenschaftVerteilschluessel, Verteilschluessel
        self._neu(typ='prozent')
        s = LiegenschaftVerteilschluessel.objects.get()
        self.c.post(self.url, {'aktion': 'prozente', 'id': s.id, **{f'pct_{e.id}': w for e, w in zip(self.einheiten, ('50', '30', '20'))}})
        self.assertEqual(self._neu(typ='anteil', gueltig_ab='2026-01-01').status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.gueltig_bis, date(2025, 12, 31))
        self.assertFalse(Verteilschluessel.objects.filter(kostenart='hauswartung', gueltig_bis__isnull=True).exists())
        # Periode 2025 rechnet weiter mit Prozent, Periode 2026 wäre «Wertquote» (hier nur der Stichtag-Test)
        self.aktivieren()
        _, a = self.anteile()
        self.assertEqual(a['W0'], Decimal('500.00'))

    def test_prozentraster_speichern_und_summe_pruefen(self):
        from portfolio.models import LiegenschaftVerteilschluessel, Verteilschluessel
        self._neu(typ='prozent')
        s = LiegenschaftVerteilschluessel.objects.get()
        felder = {f'pct_{e.id}': w for e, w in zip(self.einheiten, ('60', '30', '10'))}
        ok = self.c.post(self.url, {'aktion': 'prozente', 'id': s.id, **felder})
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(Verteilschluessel.objects.filter(kostenart='hauswartung', typ='prozent').count(), 3)
        self.aktivieren()
        _, a = self.anteile()
        self.assertEqual(a['W0'], Decimal('600.00'))
        # falsche Summe: Fehler, bisherige Werte bleiben
        falsch = {f'pct_{e.id}': w for e, w in zip(self.einheiten, ('60', '30', '20'))}
        antwort = self.c.post(self.url, {'aktion': 'prozente', 'id': s.id, **falsch})
        self.assertContains(antwort, 'ergeben 110', status_code=400)
        self.assertEqual(Verteilschluessel.objects.get(einheit=self.einheiten[2], kostenart='hauswartung').wert, Decimal('10'))
        # keine Zahl: Fehler am Feld
        text = {**felder, f'pct_{self.einheiten[0].id}': 'viel'}
        a2 = self.c.post(self.url, {'aktion': 'prozente', 'id': s.id, **text})
        self.assertContains(a2, f'pct_{self.einheiten[0].id}_{s.id}_fehler', status_code=400)

    def test_loeschen_entfernt_schluessel_und_prozentanteile(self):
        from portfolio.models import LiegenschaftVerteilschluessel, Verteilschluessel
        self._neu(typ='prozent')
        s = LiegenschaftVerteilschluessel.objects.get()
        self.c.post(self.url, {'aktion': 'prozente', 'id': s.id, **{f'pct_{e.id}': w for e, w in zip(self.einheiten, ('50', '30', '20'))}})
        self.c.post(self.url, {'aktion': 'loeschen', 'id': s.id})
        self.assertEqual(LiegenschaftVerteilschluessel.objects.count(), 0)
        self.assertEqual(Verteilschluessel.objects.count(), 0)

    def test_lesezugriff_sieht_die_seite_darf_aber_nichts_aendern(self):
        from django.test import Client
        from core.tests._helfer import _team_user
        from portfolio.models import LiegenschaftVerteilschluessel
        c = Client()
        c.force_login(_team_user('Lesezugriff'))
        self.assertEqual(c.get(self.url).status_code, 200)
        c.post(self.url, {'aktion': 'neu', 'kostenart': 'hauswartung', 'typ': 'zimmer', 'gueltig_ab': '2025-01-01'})
        self.assertEqual(LiegenschaftVerteilschluessel.objects.count(), 0)

    def test_fremde_liegenschaft_ist_nicht_erreichbar(self):
        """Mandantengrenze: Eine Liegenschaft einer anderen Organisation ergibt 404, nicht 403."""
        from crm.models import Organisation
        from core.tenancy import organisation_kontext
        fremd_org = Organisation.objects.create(firma='Fremde Verwaltung AG')
        with organisation_kontext(fremd_org):
            fremd = Liegenschaft.objects.create(organisation=fremd_org, strasse='Fremdweg 9', plz='3000', ort='Bern',
                                                versicherungswert=Decimal('1'))
        self.assertEqual(self.c.get(f'/neu/liegenschaften/{fremd.id}/verteilschluessel/').status_code, 404)
        self.assertEqual(self.c.post(f'/neu/liegenschaften/{fremd.id}/verteilschluessel/', {'aktion': 'neu'}).status_code, 404)
