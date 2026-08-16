"""Testmodul audits — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 15 Klassen, unveraendert uebernommen."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client, RequestFactory
from ._helfer import (_test_organisation,
    _team_user, _basis_objekte, _seed_konten, Mieter, Eigentuemer,
    Organisation, Liegenschaft, Einheit, Mietvertrag)



class PrueferFundeTests(TestCase):
    """Funde aus dem Herz-und-Nieren-Test durch Buchhalter + Immobilienvermarkter.
    Jeder Test sichert einen behobenen Fehler dauerhaft ab."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def _camt(self, ref, betrag, acct_ref='BANKTX1'):
        return (
            '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt><Ntry>'
            '<CdtDbtInd>CRDT</CdtDbtInd>'
            f'<Amt Ccy="CHF">{betrag}</Amt><BookgDt><Dt>2024-03-20</Dt></BookgDt>'
            '<NtryDtls><TxDtls>'
            f'<Refs><AcctSvcrRef>{acct_ref}</AcctSvcrRef></Refs>'
            f'<RmtInf><Strd><CdtrRefInf><Ref>{ref}</Ref></CdtrRefInf></Strd></RmtInf>'
            '</TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>'
        ).encode('utf-8')

    def _saldo(self, nummer):
        from finance.models import Buchung, Buchungskonto
        from django.db.models import Sum
        k = Buchungskonto.objects.filter(nummer=nummer).first()
        if not k:
            return Decimal('0.00'), Decimal('0.00')
        s = Buchung.objects.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        h = Buchung.objects.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        return s, h

    # ---- Buchhalter ----
    def test_camt_ueberzahlung_geht_nicht_verloren(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        r = DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')  # brutto 1700
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('camt.xml', self._camt(r.qr_referenz, '1900.00'),
                               content_type='application/xml')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        # Voller Bankeingang 1900 auf 1020 (nicht auf 1700 gekappt) …
        s1020, h1020 = self._saldo('1020')
        self.assertEqual(s1020 - h1020, Decimal('1900.00'))
        # … Überschuss 200 als Mieterguthaben (Haben) auf 2030 — der Mieter ist über
        # die QRR bekannt, das ist eine echte Verbindlichkeit, kein Durchlaufposten.
        s2030, h2030 = self._saldo('2030')
        self.assertEqual(h2030 - s2030, Decimal('200.00'))
        s1190, h1190 = self._saldo('1190')
        self.assertEqual(h1190 - s1190, Decimal('0.00'))

    def test_mahnlauf_bucht_gebuehr_ins_hauptbuch(self):
        from core.services.automation import run_mahnlauf
        from finance.models import DebitorenRechnung
        _seed_konten()
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, einheit=e, titel='Miete 12/2023',
            datum=date(2023, 12, 1), faellig_am=date(2023, 12, 5),
            betrag=Decimal('1700'), status='offen')
        vor_s, vor_h = self._saldo('3600')
        res = run_mahnlauf(mit_zins=True, send_email=False)
        self.assertGreater(res['gebuehren'] + res['zins'], Decimal('0'))
        nach_s, nach_h = self._saldo('3600')
        # Gebühr + Zins als Ertrag auf 3600 gebucht (Haben-Zuwachs = zusatz).
        self.assertEqual((nach_h - vor_h), res['gebuehren'] + res['zins'])

    def test_mwst_estv_umsatz_stimmt_mit_steuer(self):
        from core.services.automation import run_sollstellung
        _seed_konten()
        lg, e, m, v = _basis_objekte()
        v.mwst_pflichtig = True; v.mwst_satz = Decimal('8.1'); v.save()
        run_sollstellung(2024, 3)
        c = Client(); c.force_login(_team_user())
        resp = c.get('/neu/mwst/?jahr=2024')
        ust = resp.context['umsatzsteuer']
        umsatz = resp.context['umsatz_steuerbar']
        self.assertGreater(ust, Decimal('0'))
        # Ziffer 289 × Normalsatz muss die geschuldete Steuer (399) ergeben (Abstimmung).
        self.assertEqual((umsatz * Decimal('8.1') / Decimal('100')).quantize(Decimal('0.01')), ust)

    def test_honorar_zieht_ertragsminderung_ab(self):
        from finance.booking import buche, ensure_kontenplan
        from crm.models import Eigentuemer
        from core.services.verwaltungshonorar import honorar_vorschau
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        md = Eigentuemer.objects.create(firma_oder_name='Eigentümer AG', honorar_prozent=Decimal('5'))
        lg.eigentuemer = md; lg.save()
        # Voller Referenzertrag 1000, davon 400 Erlass (Option B) → Ist-Ertrag 600.
        buche('1100', '3000', Decimal('1000'), 'Miete', datum=date(2024, 6, 1), liegenschaft=lg)
        buche('3090', '1100', Decimal('400'), 'Erlass', datum=date(2024, 6, 1), liegenschaft=lg)
        zeilen, _total, _pz = honorar_vorschau(md, 2024)
        zeile = next(z for z in zeilen if z['lg'].id == lg.id)
        self.assertEqual(zeile['mietertrag'], Decimal('600.00'))
        self.assertEqual(zeile['honorar'], Decimal('30.00'))   # 5% von 600

    # ---- Immobilienvermarkter ----
    def test_mieterspiegel_ist_nutzt_vertragsmiete(self):
        from core.services.mieterspiegel import berechne_mieterspiegel
        lg, e, m, v = _basis_objekte()   # Vertrag 1500 + 200
        e.nettomiete_aktuell = Decimal('1800'); e.nebenkosten_aktuell = Decimal('250'); e.save()
        block = berechne_mieterspiegel([lg])[0]
        t = block['totals']
        self.assertEqual(t['soll_brutto'], Decimal('2050.00'))   # Objekt-Sollmiete
        self.assertEqual(t['ist_brutto'], Decimal('1700.00'))    # tatsächliche Vertragsmiete

    def test_parse_einkommen_robust(self):
        from core.services.bewerber_scoring import parse_einkommen
        self.assertEqual(parse_einkommen("90000, Bonus 2024"), 90000)
        self.assertEqual(parse_einkommen("seit 2019: 90000"), 90000)
        self.assertEqual(parse_einkommen("80'000.50"), 80000)
        self.assertEqual(parse_einkommen("ca. 7500 pro Monat (90000/Jahr)"), 90000)
        self.assertEqual(parse_einkommen("80'000 – 100'000"), 80000)  # untere Grenze
        self.assertIsNone(parse_einkommen("keine Angabe"))

    def test_bewerber_entscheid_idempotent(self):
        from unittest.mock import patch
        from mietprozess.models import Mietbewerbung
        lg, e, m, v = _basis_objekte()
        b = Mietbewerbung.objects.create(einheit=e, vorname='Anna', nachname='Test',
                                         email='anna@example.ch', status='neu',
                                         geburtsdatum=date(1990, 5, 1))
        c = Client(); c.force_login(_team_user())
        with patch('core.utils.email_service.send_ticket_email', return_value=True) as mock_mail:
            c.post(f'/neu/bewerbungen/{b.id}/entscheid/', {'entscheid': 'zusage'})
            c.post(f'/neu/bewerbungen/{b.id}/entscheid/', {'entscheid': 'zusage'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'zugesagt')
        self.assertEqual(mock_mail.call_count, 1)   # zweite Zusage schickt KEINE Mail

    def test_bewerbung_zu_vertrag_idempotent_und_nimmt_aus_vermarktung(self):
        from mietprozess.models import Mietbewerbung
        lg, e, m, v_bestand = _basis_objekte()
        e.zur_ausschreibung = True; e.save()
        b = Mietbewerbung.objects.create(einheit=e, vorname='Beat', nachname='Neu',
                                         email='beat@example.ch', status='neu',
                                         geburtsdatum=date(1988, 3, 12))
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        c.post(f'/neu/bewerbungen/{b.id}/vertrag/')   # zweiter Klick
        entwuerfe = Mietvertrag.objects.filter(einheit=e, status='entwurf').count()
        self.assertEqual(entwuerfe, 1)   # kein Doppel-Entwurf
        e.refresh_from_db()
        self.assertFalse(e.zur_ausschreibung)   # Objekt aus der Vermarktung genommen


class PrueferRunde2Tests(TestCase):
    """Funde aus dem 2. Prüfdurchgang (Anwalt/Buchhalter/Bewirtschafter/Verwaltung)."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def _req(self, rolle='Verwaltung'):
        from django.test import RequestFactory
        r = RequestFactory().post('/')
        r.user = _team_user(rolle)
        return r

    # --- Buchhalter: pay_kreditor darf Teilzahlungen nicht ignorieren ---
    def test_pay_kreditor_keine_doppelzahlung(self):
        # Bis E1c über finance.api.pay_kreditor geprüft; die API ist weg, die
        # Zusicherung gilt unverändert für fw_kreditor_bezahlen in /neu/.
        from finance.models import KreditorenRechnung, KreditorenZahlung, Buchung, Buchungskonto
        from finance.booking import ensure_kontenplan, konto as _k
        from django.db.models import Sum
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(lieferant='Elektro AG', betrag=Decimal('1000'),
                                              status='freigegeben', liegenschaft=lg, konto=_k('4000'))
        KreditorenZahlung.objects.create(kreditor=k, betrag=Decimal('300'), datum=date(2024, 5, 1))
        self.assertEqual(k.offener_betrag, Decimal('700'))
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.id})
        k.refresh_from_db()
        self.assertEqual(k.status, 'bezahlt')
        self.assertEqual(k.bezahlt_betrag, Decimal('1000'))   # 300 + 700, NICHT 1300
        bank = Buchungskonto.objects.get(nummer='1020')
        h = Buchung.objects.filter(haben_konto=bank).aggregate(s=Sum('betrag'))['s'] or Decimal('0')
        self.assertEqual(h, Decimal('700'))   # nur der offene Betrag wurde abgebucht

    # --- Verwaltung/Security: DocuSeal-Webhook ohne Secret ablehnen ---
    def test_docuseal_webhook_ohne_secret_403(self):
        from rentals.api import docuseal_webhook
        from django.test import RequestFactory, override_settings
        req = RequestFactory().post('/', data='{}', content_type='application/json')
        with override_settings(DOCUSEAL_WEBHOOK_SECRET=None):
            self.assertEqual(docuseal_webhook(req).status_code, 403)
        with override_settings(DOCUSEAL_WEBHOOK_SECRET='geheim'):
            req2 = RequestFactory().post('/', data='{}', content_type='application/json')
            self.assertEqual(docuseal_webhook(req2).status_code, 403)   # ohne Header
            req3 = RequestFactory().post('/', data='{}', content_type='application/json',
                                         HTTP_X_WEBHOOK_SECRET='geheim')
            self.assertEqual(docuseal_webhook(req3).status_code, 200)   # korrektes Secret

    # --- Verwaltung/Security: Legacy-Finance-API weist negative Beträge ab ---
    def test_legacy_zahlung_negativ_abgewiesen(self):
        # Bis E1c über die Legacy-Finance-API (create_zahlung) geprüft. Die API
        # ist weg; derselbe Schutz sitzt in /neu/ in fw_bankabgleich_verbuchen.
        from finance.models import Zahlungseingang, DebitorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(vertrag=v, titel='Miete 05/2024', betrag=Decimal('1500'),
                                             datum=date(2024, 5, 1), faellig_am=date(2024, 5, 1),
                                             status='offen')
        c = Client(); c.force_login(_team_user('Sachbearbeitung'))
        c.post('/neu/bankabgleich/verbuchen/', {'rechnung_id': r.id, 'betrag': '-5000'})
        self.assertEqual(Zahlungseingang.objects.count(), 0)

    # --- Bewirtschafter: Mieterportal-Dok-Leck Vormieter → Nachmieter ---
    def test_portal_kein_vormieter_dokumentenleck(self):
        from core.views.portal import _mieter_dok_gruppen
        from rentals.models import Dokument as RDokument
        from django.core.files.base import ContentFile
        lg, e, m_alt, v_alt = _basis_objekte()
        m_neu = Mieter.objects.create(typ='person', vorname='Rita', nachname='Neu',
                                      email='rita@example.ch')
        v_neu = Mietvertrag.objects.create(mieter=m_neu, einheit=e, beginn=date(2025, 1, 1),
                                           netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                                           status='aktiv')
        d = RDokument.objects.create(vertrag=v_alt, einheit=e, mieter=m_alt, kategorie='vertrag',
                                     bezeichnung='Schlussabrechnung Vormieter', im_portal_sichtbar=True)
        d.datei.save('x.pdf', ContentFile(b'%PDF-1.4'), save=True)
        gruppen = _mieter_dok_gruppen(m_neu, [v_neu])
        titel_alle = [doc['titel'] for g in gruppen for doc in g['docs']]
        self.assertNotIn('Schlussabrechnung Vormieter', titel_alle)

    # --- Bewirtschafter: Schlussabrechnung belastet offene Forderungen nicht doppelt ---
    def test_schlussabrechnung_keine_doppelforderung(self):
        # Seit dem Buchhalter-Audit (K2) werden bestehende Mietforderungen NICHT mehr
        # storniert und auf 3000 neu gebucht (das vernichtete die MWST-Abgrenzung und
        # verschob Schadenersatz in den Mietertrag). Sie bleiben bestehen; die
        # Schlussabrechnung bucht nur die NEUEN Positionen. Invariante bleibt:
        # der Mieter wird nicht doppelt belastet.
        from finance.models import DebitorenRechnung
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        alt = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                               titel='Miete 05/2024', datum=date(2024, 5, 1),
                                               faellig_am=date(2024, 5, 5), betrag=Decimal('1700'),
                                               status='offen')
        buche('1100', '3000', Decimal('1700'), 'Miete 05/2024', datum=date(2024, 5, 1),
              liegenschaft=lg, debitor=alt)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen'})
        alt.refresh_from_db()
        self.assertEqual(alt.status, 'offen')        # Originalforderung bleibt (MWST intakt)
        offene = DebitorenRechnung.objects.filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
        self.assertEqual(sum((r.offener_betrag for r in offene), Decimal('0')), Decimal('1700'))


class PrueferRunde2QuickTests(TestCase):
    """Weitere Quick-Fixes aus dem 2. Prüfdurchgang."""

    def test_kaution_obergrenze_serverseitig(self):
        # Art. 257e: max. 3 Monatsmieten bei Wohnräumen — serverseitig geklemmt.
        lg, e, m, v = _basis_objekte()   # Wohnung, netto 1500 + NK 200 → max 5100
        v.kautions_betrag = Decimal('10000')
        v.save()
        v.refresh_from_db()
        self.assertEqual(v.kautions_betrag, Decimal('5100.00'))

    def test_serienbrief_adressiert_mitmieter(self):
        lg, e, m, v = _basis_objekte()
        m2 = Mieter.objects.create(typ='person', vorname='Petra', nachname='Partner',
                                   email='petra@example.ch')
        v.mitmieter = m2
        v.status = 'aktiv'
        v.save()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/kommunikation/')
        self.assertEqual(r.status_code, 200)
        namen = [e['name'] for e in r.context['empfaenger']]
        self.assertIn(m2.display_name, namen)   # Mitmieter erscheint als Empfänger
        self.assertIn(m.display_name, namen)


class Paket1DatenUITests(TestCase):
    """Paket 1: bisher tote Model-Felder sind im UI erfassbar/sichtbar."""

    def test_liegenschaft_form_speichert_neue_felder(self):
        from portfolio.models import Liegenschaft
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Prüfweg 1', plz='3000', ort='Bern')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/liegenschaften/{lg.id}/bearbeiten/', {
            'strasse': 'Prüfweg 1', 'plz': '3000', 'ort': 'Bern', 'kanton': 'BE',
            'versicherungswert': '1250000', 'grundstuecksflaeche_m2': '640',
            'gebaeudevolumen_m3': '2100', 'sanitaer_name': 'Meier AG',
            'sanitaer_telefon': '0313334455', 'elektriker_name': 'Volt GmbH',
            'elektriker_telefon': '0316667788', 'gwr_import': ''})
        self.assertEqual(r.status_code, 302)
        lg.refresh_from_db()
        self.assertEqual(lg.versicherungswert, Decimal('1250000'))
        self.assertEqual(lg.grundstuecksflaeche_m2, Decimal('640'))
        self.assertEqual(lg.sanitaer_name, 'Meier AG')
        self.assertEqual(lg.elektriker_name, 'Volt GmbH')

    def test_objekt_form_speichert_neue_felder_und_gehoert_zu(self):
        from portfolio.models import Liegenschaft, Einheit
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Prüfweg 2', plz='3000', ort='Bern')
        haupt = Einheit.objects.create(liegenschaft=lg, bezeichnung='Haupt 3.5', typ='whg')
        pp = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 1', typ='pp')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/objekte/{pp.id}/bearbeiten/', {
            'liegenschaft_id': str(lg.id), 'bezeichnung': 'PP 1', 'typ': 'pp',
            'wertquote': '25', 'volumen_m3': '40', 'estrich': 'nein', 'oto_dose': 'A12',
            'bodenbelag': 'Beton', 'letzte_renovation': '2019',
            'standard_kautionsmonate': '2', 'gehoert_zu_id': str(haupt.id)})
        self.assertEqual(r.status_code, 302)
        pp.refresh_from_db()
        self.assertEqual(pp.wertquote, Decimal('25'))
        self.assertEqual(pp.volumen_m3, Decimal('40'))
        self.assertEqual(pp.bodenbelag, 'Beton')
        self.assertEqual(pp.letzte_renovation, 2019)
        self.assertEqual(pp.standard_kautionsmonate, 2)
        self.assertEqual(pp.gehoert_zu_id, haupt.id)

    def test_person_detail_zeigt_sprache_notizen_firma(self):
        m = Mieter.objects.create(typ='firma', firmen_name='Bau AG', uid_nummer='CHE-123.456.789',
                                  kontaktperson='Frau Muster', sprache='fr',
                                  notizen='Zahlt immer pünktlich.')
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertIn('Firma / Organisation', html)
        self.assertIn('CHE-123.456.789', html)
        self.assertIn('Frau Muster', html)
        self.assertIn('Zahlt immer pünktlich.', html)

    def test_person_form_speichert_land(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {
            'typ': 'person', 'vorname': 'Jean', 'nachname': 'Dupont',
            'strasse': 'Rue 1', 'plz': '68000', 'ort': 'Colmar', 'land': 'Frankreich'})
        self.assertIn(r.status_code, (200, 302))
        m = Mieter.objects.get(nachname='Dupont')
        self.assertEqual(m.land, 'Frankreich')


class Paket2PlatzierungTests(TestCase):
    """Paket 2: Formulare/Reports am richtigen Ort erreichbar."""

    def test_objekt_verhaeltnis_zeigt_schnellaktionen(self):
        _lg, e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn(f'/neu/mietzins/{v.id}/anfangsmietzins/', html)
        self.assertIn(f'/neu/mietzins/{v.id}/anpassung/', html)
        self.assertIn(f'/neu/vertraege/{v.id}/kuendigen/', html)

    def test_liegenschaft_detail_verlinkt_berichte(self):
        lg, _e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/liegenschaften/{lg.id}/').content.decode()
        self.assertIn(f'/neu/mieterspiegel/?lg={lg.id}', html)

    def test_vertrag_finanzen_verlinkt_nebenkosten(self):
        lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/vertraege/{v.id}/').content.decode()
        self.assertIn(f'/neu/nebenkosten/?lg={lg.id}', html)

    def test_mandate_in_sidebar_verwaltung(self):
        # Neue 6-Türen-Sidebar: Mandate liegen unter «Kontakte» (Profi) bzw.
        # «Erweitert» (Einfach) — in beiden Modi als Link auf /neu/mandate/.
        _lg, _e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        for modus in ('einfach', 'profi'):
            c.post('/neu/modus/', {'modus': modus})
            html = c.get('/neu/personen/').content.decode()
            self.assertIn('/neu/mandate/', html)
            self.assertIn('Mandate', html)


class Paket3ZahlungBonitaetTests(TestCase):
    """Paket 3: Zahlungsverkehr, Bonität, Vorvermieter-Referenz, Vertretung, Mahnsperre."""

    def test_person_form_speichert_zahlung_und_bonitaet(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {
            'typ': 'person', 'vorname': 'Zora', 'nachname': 'Zahler',
            'zahlungsart': 'lsv', 'ebill_email': 'zora@ebill.ch', 'mahnsperre': 'on',
            'zahler_name': 'Sozialamt Bern', 'zahler_iban': 'CH..',
            'betreibung_ergebnis': 'keine',
            'ref_vermieter_name': 'Alt AG', 'ref_vermieter_telefon': '0310001122',
            'vertretung_art': 'beistand', 'vertretung_name': 'KESB Bern'})
        self.assertIn(r.status_code, (200, 302))
        m = Mieter.objects.get(nachname='Zahler')
        self.assertEqual(m.zahlungsart, 'lsv')
        self.assertTrue(m.mahnsperre)
        self.assertEqual(m.zahler_name, 'Sozialamt Bern')
        self.assertEqual(m.betreibung_ergebnis, 'keine')
        self.assertEqual(m.ref_vermieter_name, 'Alt AG')
        self.assertEqual(m.vertretung_art, 'beistand')

    def test_person_detail_zeigt_zahlung_und_vertretung(self):
        m = Mieter.objects.create(typ='person', vorname='A', nachname='B',
                                  zahlungsart='ebill', ebill_email='a@b.ch',
                                  vertretung_art='kesb', vertretung_name='KESB Thun')
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertIn('Zahlungsverkehr', html)
        self.assertIn('eBill', html)
        self.assertIn('KESB Thun', html)

    def test_mahnsperre_ueberspringt_mahnlauf(self):
        from core.services.automation import run_mahnlauf
        from finance.models import DebitorenRechnung
        _lg, _e, m, v = _basis_objekte()
        m.mahnsperre = True; m.save()
        DebitorenRechnung.objects.create(
            vertrag=v, titel='Miete', betrag=Decimal('1700'), datum=date(2025, 1, 1),
            faellig_am=date(2025, 1, 1), status='offen')
        res = run_mahnlauf(send_email=False)
        self.assertEqual(res['gemahnt'], 0)   # Mahnsperre → nicht gemahnt

    def test_dsg_scrub_loescht_zahlungsfelder(self):
        from core.services.dsg import anonymisiere_person
        _lg, _e, m, v = _basis_objekte()
        v.status = 'archiviert'; v.save()
        m.zahlungsart = 'lsv'; m.zahler_name = 'X'; m.ref_vermieter_name = 'Y'
        m.vertretung_name = 'Z'; m.save()
        ok, _ = anonymisiere_person(m, grund='Test')
        self.assertTrue(ok)
        m.refresh_from_db()
        self.assertEqual(m.zahlungsart, '')
        self.assertEqual(m.zahler_name, '')
        self.assertEqual(m.ref_vermieter_name, '')
        self.assertEqual(m.vertretung_name, '')


class Paket4ProzesseTests(TestCase):
    """Paket 4: Kautions-Belege PDF + Mängelrüge (Art. 259)."""

    def test_kaution_belege_pdf(self):
        from rentals.models import Dokument
        _lg, _e, m, v = _basis_objekte()
        v.kautions_art = 'sperrkonto'; v.kautions_konto = 'CH93 0076…'
        v.kautions_einbezahlt_am = date(2024, 1, 5); v.save()
        c = Client(); c.force_login(_team_user())
        for art in ('hinterlegung', 'freigabe'):
            r = c.get(f'/neu/vertraege/{v.id}/kaution-beleg/{art}/')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Kaution').exists())

    def test_maengelruege_pdf_und_pendenz(self):
        from rentals.models import Dokument
        from core.models import Pendenz
        _lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        g = c.get(f'/neu/vertraege/{v.id}/maengelruege/')
        self.assertEqual(g.status_code, 200)
        r = c.post(f'/neu/vertraege/{v.id}/maengelruege/', {'mangel': 'Tropfender Wasserhahn im Bad', 'frist_tage': '10'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Mängelrüge').exists())
        self.assertTrue(Pendenz.objects.filter(vertrag=v, titel__startswith='Mängelbehebung').exists())


class Paket4RestTests(TestCase):
    """Paket 4 Rest: Untermiete-Zustimmung, Versicherungsregister, Betriebskostenspiegel."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def test_untermiete_pdf(self):
        _lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self.assertEqual(c.get(f'/neu/vertraege/{v.id}/untermiete/').status_code, 200)
        r = c.post(f'/neu/vertraege/{v.id}/untermiete/', {
            'untermieter': 'Peter Muster', 'entscheid': 'zustimmung', 'bedingungen': 'befristet bis Ende Jahr'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_versicherung_crud(self):
        from portfolio.models import Versicherung
        lg, _e, _m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/liegenschaften/{lg.id}/versicherung/', {
            'art': 'gebaeude', 'gesellschaft': 'GVB', 'policennummer': 'P-123',
            'versicherungssumme': '1200000', 'jahrespraemie': '3400', 'ablauf_datum': '2027-01-01'})
        self.assertEqual(r.status_code, 302)
        vs = Versicherung.objects.get(liegenschaft=lg)
        self.assertEqual(vs.gesellschaft, 'GVB')
        self.assertEqual(vs.jahrespraemie, Decimal('3400'))
        # Anzeige auf der Detailseite
        html = c.get(f'/neu/liegenschaften/{lg.id}/').content.decode()
        self.assertIn('GVB', html)
        # Löschen
        r2 = c.post(f'/neu/versicherung/{vs.id}/loeschen/')
        self.assertEqual(r2.status_code, 302)
        self.assertFalse(Versicherung.objects.filter(id=vs.id).exists())

    def test_betriebskostenspiegel_rechnet_pro_m2(self):
        from finance.models import Buchung, Buchungskonto
        lg, e, _m, _v = _basis_objekte()
        e.flaeche_m2 = Decimal('100'); e.save()
        aufwand, _ = Buchungskonto.objects.get_or_create(nummer='4000', defaults={'bezeichnung': 'Unterhalt', 'typ': 'aufwand'})
        bank, _ = Buchungskonto.objects.get_or_create(nummer='1020', defaults={'bezeichnung': 'Bank', 'typ': 'bilanz'})
        Buchung.objects.create(datum=date(date.today().year, 6, 1), liegenschaft=lg,
                               soll_konto=aufwand, haben_konto=bank, betrag=Decimal('2500'),
                               beleg_text='Test-Aufwand')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/berichte/betriebskostenspiegel/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Betriebskostenspiegel', html)
        self.assertIn('25,00', html)   # 2500 / 100 m² = CHF 25.00/m² (de-Lokalisierung)


class QualitaetscheckFixTests(TestCase):
    """Fixes aus dem Abschluss-Qualitätscheck: cancel_umzug-Scoping,
    Betriebsrechnung ohne Doppelzählung von Erfolgsumbuchungen."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def test_betriebsrechnung_keine_doppelzaehlung_erfolgsumbuchung(self):
        from core.services.rendite import betriebsrechnung
        from finance.models import Buchungskonto, Buchung
        lg, e, m, v = _basis_objekte()
        Buchungskonto.objects.get_or_create(nummer='3000', defaults={'bezeichnung': 'Ertrag', 'typ': 'ertrag'})
        Buchungskonto.objects.get_or_create(nummer='6000', defaults={'bezeichnung': 'Aufwand', 'typ': 'aufwand'})
        auf = Buchungskonto.objects.get(nummer='6000')
        ert = Buchungskonto.objects.get(nummer='3000')
        jahr = date.today().year
        # Reine Aufwand→Ertrag-Umbuchung: darf weder Ertrag- noch Aufwand-Total aufblähen
        Buchung.objects.create(datum=date(jahr, 5, 1), liegenschaft=lg,
                               soll_konto=auf, haben_konto=ert, betrag=Decimal('500'))
        d = betriebsrechnung(lg, jahr)
        self.assertEqual(d['ertrag_total'], Decimal('0.00'))
        self.assertEqual(d['aufwand_total'], Decimal('0.00'))

    # `test_cancel_umzug_schont_manuelle_adresse` ist mit E1c ersatzlos entfallen.
    # Es prüfte crm.api.cancel_umzug: beim Stornieren eines Umzugs müssen aus dem
    # Vertrag stammende Adresszeilen weichen, manuell erfasste aber bleiben.
    # In /neu/ gibt es kein Umzug-Stornieren — der API-Endpunkt war der einzige
    # Weg, und erreichbar war er nur über die in E1b entfernte Vue-Oberfläche.
    # Die Fähigkeit ist damit seit E1b weg, nicht erst jetzt. Kommt sie nach
    # /neu/, gehört dieser Test wieder her.


class NachtN1KritischeBugsTests(TestCase):
    """Nacht-Audit N1: Storno-Kette, Verzugszins-Delta, 266a-Klemme,
    269d-Zustellpuffer, Zusage-Idempotenz, Telefonsuche."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def _konten(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()

    def test_storno_kette_verkettet_und_markiert(self):
        from finance.services import erstelle_storno_buchung
        from finance.booking import buche
        _lg, _e, _m, _v = _basis_objekte()
        self._konten()
        b = buche('1100', '3000', Decimal('1500'), 'Miete Test')
        gegen = erstelle_storno_buchung(b)
        b.refresh_from_db()
        self.assertIsNotNone(b.storniert_am)          # Original markiert
        self.assertEqual(gegen.storno_von_id, b.id)   # Kette verkettet
        self.assertTrue(gegen.ist_storno)
        # Doppel-Storno verhindert
        with self.assertRaises(ValueError):
            erstelle_storno_buchung(b)

    def test_betriebsrechnung_nettoiert_nach_storno(self):
        from core.services.rendite import betriebsrechnung
        from finance.booking import buche, storniere_buchung
        lg, _e, _m, _v = _basis_objekte()
        self._konten()
        from finance.models import Buchungskonto
        Buchungskonto.objects.get_or_create(nummer='6000', defaults={'bezeichnung': 'Unterhalt', 'typ': 'aufwand'})
        b = buche('6000', '1020', Decimal('800'), 'Reparatur', datum=date.today(), liegenschaft=lg)
        storniere_buchung(b)
        d = betriebsrechnung(lg, date.today().year)
        self.assertEqual(d['aufwand_total'], Decimal('0.00'))   # storniert zählt nicht

    def test_verzugszins_delta_statt_kumulativ(self):
        from core.services.automation import run_mahnlauf, verzugszins
        from finance.models import DebitorenRechnung, Mahnung
        lg, e, m, v = _basis_objekte()
        self._konten()
        # 65 Tage überfällig → würde direkt Stufe 3 erreichen; wir simulieren
        # zwei Läufe: erst Stufe 2 (31 Tage), dann Stufe 3 (65 Tage).
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete Januar', betrag=Decimal('1000'),
            datum=date.today() - timedelta(days=70),
            faellig_am=date.today() - timedelta(days=31), status='offen')
        run_mahnlauf(send_email=False, mit_zins=True)
        m1 = r.mahnungen.order_by('-id').first()
        self.assertEqual(m1.zins, verzugszins(Decimal('1000'), 31))
        # Fälligkeit zurückdatieren → nächste Stufe wird fällig
        r.faellig_am = date.today() - timedelta(days=65)
        r.save(update_fields=['faellig_am'])
        run_mahnlauf(send_email=False, mit_zins=True)
        m2 = r.mahnungen.order_by('-id').first()
        self.assertGreater(m2.stufe, m1.stufe)
        # Stufe 2 fakturiert nur das DELTA: voller Zins(65) − bereits Zins(31)
        erwartet = verzugszins(Decimal('1000'), 65) - m1.zins
        self.assertEqual(m2.zins, erwartet)
        total = sum(x.zins for x in r.mahnungen.all())
        self.assertEqual(total, verzugszins(Decimal('1000'), 65))  # nie mehr als 1×

    def test_266a_zu_fruehes_ende_geklemmt(self):
        from rentals.services import berechne_kuendigungstermin
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        heute = date.today()
        zu_frueh = heute + timedelta(days=5)   # weit vor Frist+Termin
        c.post(f'/neu/vertraege/{v.id}/kuendigen/', {
            'absender': 'mieter', 'eingang_datum': heute.isoformat(),
            'gewuenschtes_ende': zu_frueh.isoformat(),
        })
        v.refresh_from_db()
        termin = berechne_kuendigungstermin(v, heute)
        self.assertEqual(v.ende, termin)   # geklemmt auf ordentlichen Termin
        k = v.kuendigungen.first()
        self.assertEqual(k.per_datum, termin)
        self.assertEqual(k.gewuenschtes_ende, zu_frueh)  # Wunsch bleibt dokumentiert

    def test_269d_zustellpuffer(self):
        from rentals.services import naechster_anpassungstermin, berechne_kuendigungstermin, ZUSTELL_PUFFER_TAGE
        _lg, _e, _m, v = _basis_objekte()
        heute = date.today()
        # Die Erhöhung wird auf den ERSTEN des Folgemonats wirksam (Monatserster),
        # nicht auf den Monatsende-Kündigungstermin selbst (Live-Test I).
        termin = berechne_kuendigungstermin(v, heute + timedelta(days=ZUSTELL_PUFFER_TAGE + 10))
        self.assertEqual(naechster_anpassungstermin(v, heute), termin + timedelta(days=1))
        self.assertGreaterEqual(ZUSTELL_PUFFER_TAGE, 7)

    def test_zusage_nach_vergleich_blockiert_umwandlung_nicht(self):
        from mietprozess.models import Mietbewerbung
        lg, e, m, v = _basis_objekte()
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='1.5 Zi', typ='wohnung',
                                    nettomiete_aktuell=Decimal('900'))
        b = Mietbewerbung.objects.create(einheit=e2, vorname='Nina', nachname='Neu',
                                         email='nina@example.ch', status='zugesagt',
                                         geburtsdatum=date(1992, 3, 1))  # via Vergleich zugesagt, OHNE Entwurf
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        self.assertEqual(r.status_code, 302)
        entwurf = Mietvertrag.objects.filter(einheit=e2, status='entwurf',
                                             mieter__nachname='Neu').first()
        self.assertIsNotNone(entwurf)   # Entwurf wurde trotz Status 'zugesagt' erstellt
        # Zweiter Aufruf: idempotent, kein zweiter Entwurf
        c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        self.assertEqual(Mietvertrag.objects.filter(einheit=e2, status='entwurf').count(), 1)

    def test_telefonsuche(self):
        _lg, _e, m, _v = _basis_objekte()
        m.mobile = '079 123 45 67'; m.save()
        u = _team_user(); c = Client(); c.force_login(u)
        # Personenliste: Teilstring
        r = c.get('/neu/personen/?q=079 123')
        self.assertIn('Muster', r.content.decode())
        # Globale Suche: formatfremde Schreibweise (ohne Leerzeichen)
        r2 = c.get('/neu/suche/?q=0791234567')
        self.assertIn('Muster', r2.content.decode())


class NachtN6BewirtschafterTests(TestCase):
    """Nacht-Audit N6: E-Mail-Versand im Kommunikations-Journal +
    Mietzins-Massenanpassung."""

    def test_rundschreiben_landet_im_journal(self):
        from crm.models import Kommunikation
        lg, e, m, v = _basis_objekte()
        m.email = 'hans@example.ch'; m.save()
        u = _team_user(); c = Client(); c.force_login(u)
        c.post('/neu/kommunikation/senden/', {
            'betreff': 'Heizungsablesung', 'text': 'Am Dienstag kommt die Ablesung.',
            'empfaenger_id': [str(m.id)],
        })
        k = Kommunikation.objects.filter(mieter=m, typ='email', richtung='ausgehend').first()
        self.assertIsNotNone(k)
        self.assertEqual(k.betreff, 'Heizungsablesung')
        self.assertIn('hans@example.ch', k.inhalt)

    def test_mahnlauf_landet_im_journal(self):
        from crm.models import Kommunikation
        from core.services.automation import run_mahnlauf
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        m.email = 'hans@example.ch'; m.save()
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete', betrag=Decimal('1500'),
            datum=date.today() - timedelta(days=40),
            faellig_am=date.today() - timedelta(days=35), status='offen')
        res = run_mahnlauf(send_email=True)
        self.assertGreaterEqual(res['emails'], 1)
        k = Kommunikation.objects.filter(mieter=m, typ='email', betreff__icontains='Zahlungserinnerung').first()
        self.assertIsNotNone(k)
        self.assertEqual(k.vertrag_id, v.id)

    def test_bewerber_absage_landet_im_journal(self):
        from crm.models import Kommunikation
        from mietprozess.models import Mietbewerbung
        lg, e, m, v = _basis_objekte()
        b = Mietbewerbung.objects.create(
            einheit=e, vorname='Anna', nachname='Muster', email='anna@example.ch',
            geburtsdatum=date(1990, 5, 1), status='neu')
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/bewerbungen/{b.id}/entscheid/', {'entscheid': 'absage'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'abgelehnt')
        k = Kommunikation.objects.filter(typ='email', inhalt__icontains='anna@example.ch').first()
        self.assertIsNotNone(k)
        self.assertIn('Bewerbung', k.inhalt)

    def test_kommunikation_mieter_preselect(self):
        lg, e, m, v = _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        body = c.get(f'/neu/kommunikation/?mieter={m.id}').content.decode()
        self.assertIn(f'value="{m.id}" onchange="aktualisiere()" checked', body)

    def test_person_detail_email_button(self):
        lg, e, m, v = _basis_objekte()
        m.email = 'hans@example.ch'; m.save()
        u = _team_user(); c = Client(); c.force_login(u)
        body = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertIn(f'/neu/kommunikation/?mieter={m.id}', body)

    def test_mietzins_liste_hat_massen_checkboxen(self):
        _basis_objekte()
        u = _team_user(); c = Client(); c.force_login(u)
        body = c.get('/neu/mietzins/').content.decode()
        self.assertIn('name="vertrag_id"', body)
        self.assertIn('/neu/mietzins/massenanpassung/', body)

    def _vertrag_mit_potenzial(self):
        from crm.models import Organisation
        _test_organisation(firma='V AG', aktueller_referenzzinssatz=Decimal('1.75'),
                                  aktueller_lik_punkte=Decimal('100'))
        lg, e, m, v = _basis_objekte()   # netto 1500
        # Basis-Zins tiefer als aktuell → Erhöhungspotenzial (+2 Stufen à 3 %)
        v.basis_referenzzinssatz = Decimal('1.25'); v.basis_lik_punkte = Decimal('100'); v.save()
        return lg, m, v

    def test_massenanpassung_vorschau(self):
        lg, m, v = self._vertrag_mit_potenzial()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post('/neu/mietzins/massenanpassung/', {'aktion': 'vorschau', 'vertrag_id': [str(v.id)]})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('Wird angepasst', body)
        self.assertIn('Anpassung(en) erfassen', body)

    def test_massenanpassung_ausfuehren_und_idempotent(self):
        from rentals.models import MietzinsAnpassung
        from core.models import Pendenz
        lg, m, v = self._vertrag_mit_potenzial()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post('/neu/mietzins/massenanpassung/', {'aktion': 'ausfuehren', 'vertrag_id': [str(v.id)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertEqual(MietzinsAnpassung.objects.filter(vertrag=v).count(), 1)
        anp = MietzinsAnpassung.objects.get(vertrag=v)
        self.assertGreater(anp.neuer_netto_mietzins, Decimal('1500'))
        self.assertTrue(Pendenz.objects.filter(vertrag=v, titel__icontains='Anfechtungsfrist').exists())
        # Zweiter Lauf mit denselben Verträgen: keine Duplikate
        c.post('/neu/mietzins/massenanpassung/', {'aktion': 'ausfuehren', 'vertrag_id': [str(v.id)]})
        self.assertEqual(MietzinsAnpassung.objects.filter(vertrag=v).count(), 1)
        self.assertEqual(Pendenz.objects.filter(vertrag=v, titel__icontains='Anfechtungsfrist').count(), 1)

    def test_massenanpassung_ohne_basis_uebersprungen(self):
        from crm.models import Organisation
        from rentals.models import MietzinsAnpassung
        _test_organisation(firma='V AG', aktueller_referenzzinssatz=Decimal('1.75'))
        lg, e, m, v = _basis_objekte()
        # Alt-/Importvertrag ohne Basisdaten (Modell-Default liefert sonst aktuelle Werte)
        v.basis_referenzzinssatz = Decimal('0'); v.basis_lik_punkte = Decimal('0'); v.save()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post('/neu/mietzins/massenanpassung/', {'aktion': 'vorschau', 'vertrag_id': [str(v.id)]})
        self.assertIn('Basis fehlt', r.content.decode())
        r2 = c.post('/neu/mietzins/massenanpassung/', {'aktion': 'ausfuehren', 'vertrag_id': [str(v.id)]})
        self.assertEqual(r2.status_code, 302)   # nichts machbar → zurück mit Fehlermeldung
        self.assertEqual(MietzinsAnpassung.objects.filter(vertrag=v).count(), 0)


class NachtN9BuchhalterTests(TestCase):
    """Nacht-Audit N9: Debitorenverluste (Konto 3805), Mieterkonto-Filter,
    konfigurierbares NK-Verwaltungshonorar."""
    def setUp(self):
        _test_organisation()   # bucht ohne eigene Liegenschaft — Verwaltung muss existieren


    def test_forderungsverlust_abschreiben(self):
        from finance.models import DebitorenRechnung, Zahlungseingang, Buchung
        from finance.booking import ensure_kontenplan
        from core.services.mieterkonto import berechne_mieterkonto
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete Januar', betrag=Decimal('1500'),
            datum=date.today() - timedelta(days=120),
            faellig_am=date.today() - timedelta(days=115), status='teilbezahlt')
        Zahlungseingang.objects.create(vertrag=v, debitoren_rechnung=r,
                                       betrag=Decimal('500'), status='verbucht',
                                       datum_eingang=date.today() - timedelta(days=100))
        self.assertEqual(r.offener_betrag, Decimal('1000.00'))
        u = _team_user(); c = Client(); c.force_login(u)
        resp = c.post(f'/neu/debitoren/{r.id}/abschreiben/', {'grund': 'Verlustschein Betreibungsamt'})
        self.assertEqual(resp.status_code, 302)
        r.refresh_from_db()
        self.assertEqual(r.status, 'abgeschrieben')
        b = Buchung.objects.filter(soll_konto__nummer='3805', haben_konto__nummer='1100',
                                   debitoren_rechnung=r).first()
        self.assertIsNotNone(b)
        self.assertEqual(b.betrag, Decimal('1000.00'))
        self.assertIn('Verlustschein', b.beleg_text)
        # Mieterkonto: der Mieter schuldet die abgeschriebene Forderung nicht mehr
        _bewegungen, endsaldo = berechne_mieterkonto(m)
        # Rechnung raus, die geleisteten 500 bleiben als Haben → Guthaben 500
        self.assertEqual(endsaldo, Decimal('-500.00'))
        # Debitoren-Liste zählt sie nicht mehr als offen
        body = c.get('/neu/debitoren/').content.decode()
        self.assertIn('Abgeschrieben', body)

    def test_abschreiben_nur_offene(self):
        from finance.models import DebitorenRechnung, Buchung
        lg, e, m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete', betrag=Decimal('1500'),
            datum=date.today(), faellig_am=date.today(), status='bezahlt')
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/debitoren/{r.id}/abschreiben/', {'grund': 'x'})
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertFalse(Buchung.objects.filter(soll_konto__nummer='3805').exists())

    def _nk_setup(self, honorar_pct):
        from crm.models import Organisation
        from finance.models import AbrechnungsPeriode, KreditorenRechnung, Buchungskonto
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _test_organisation(firma='V AG', strasse='X', plz='1', ort='Y',
                                  nk_honorar_prozent=Decimal(str(honorar_pct)))
        lg, e, m, v = _basis_objekte()
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='NK Test',
                                              start_datum=date(2025, 1, 1),
                                              ende_datum=date(2025, 12, 31))
        KreditorenRechnung.objects.create(lieferant='Hauswart AG', betrag=Decimal('200.00'),
                                          liegenschaft=lg, is_hnk_relevant=True,
                                          konto=Buchungskonto.objects.get(nummer='4120'),
                                          status='freigegeben', datum=date(2025, 6, 1))
        return p

    def test_nk_honorar_konfigurierbar(self):
        from core.utils.billing import berechne_abrechnung
        p = self._nk_setup(2)
        r = berechne_abrechnung(p.id)
        honorar = [d for d in r['belege_details'] if d['kategorie'] == 'Verwaltung']
        self.assertEqual(len(honorar), 1)
        self.assertIn('2', honorar[0]['text'])
        self.assertEqual(Decimal(str(honorar[0]['betrag'])), Decimal('4.00'))   # 2% von 200

    def test_nk_honorar_null_kein_posten(self):
        from core.utils.billing import berechne_abrechnung
        p = self._nk_setup(0)
        r = berechne_abrechnung(p.id)
        honorar = [d for d in r['belege_details'] if d['kategorie'] == 'Verwaltung']
        self.assertEqual(honorar, [])


class ReviewNachbesserungTests(TestCase):
    """Nachbesserungen aus dem Code-Review der QS-Umsetzung.

    Sechs Fehler in der eigenen Arbeit, zwei davon schlimmer als der
    Ausgangszustand: Das Formular schickte nach dem Entfernen des Feldes
    weiterhin «ledig» mit (erfundene Angabe statt gar keiner), und die
    Bewerber-Bewertung konnte nach dem Wegfall der beiden Uploads für
    niemanden mehr die volle Punktzahl erreichen.
    """

    def _bewerbung(self, **kw):
        from mietprozess.models import Mietbewerbung
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Prüfweg 1', plz='3000', ort='Bern')
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='3.5 Zi', typ='wohnung',
                                   nettomiete_aktuell=Decimal('1500'),
                                   nebenkosten_aktuell=Decimal('200'))
        vorgabe = dict(einheit=e, vorname='Anna', nachname='Muster',
                       geburtsdatum=date(1990, 1, 1), mobilnummer='079', email='a@example.ch',
                       beruf='Kauffrau', einkommen_jahr="120'000", erwerbsstatus='angestellt',
                       ist_unbefristet=True, hat_betreibungen=False,
                       digitaler_betreibungsauszug=True, arbeitgeber='Muster AG')
        vorgabe.update(kw)
        return Mietbewerbung.objects.create(**vorgabe)

    def test_formular_schickt_keinen_erfundenen_zivilstand(self):
        """Das Feld wurde aus der Anzeige entfernt, das Vue-Modell sendete aber
        weiter 'ledig' — jede Bewerbung hätte eine Angabe gespeichert, die
        niemand gemacht hat. «Nicht erhoben» muss leer bleiben."""
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Inserat 2', plz='3000', ort='Bern')
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='2 Zi', typ='wohnung',
                                   zur_ausschreibung=True)
        html = Client().get(f'/bewerben/{e.id}/').content.decode()
        self.assertNotIn("zivilstand: 'ledig'", html)
        self.assertIn("zivilstand: ''", html)

    def test_zivilstand_darf_leer_bleiben(self):
        b = self._bewerbung()
        self.assertEqual(b.zivilstand, '', 'Modell erfindet weiterhin einen Zivilstand')

    def test_volle_punktzahl_bleibt_erreichbar(self):
        """Mit dem alten Massstab (3 Dokumente) hätte niemand mehr über 90 von
        100 kommen können — die fehlenden Punkte sähen nach einem Mangel der
        Bewerberin aus, obwohl WIR die Unterlagen nicht mehr wollen."""
        from core.services.bewerber_scoring import bewerte_bewerbung
        ergebnis = bewerte_bewerbung(self._bewerbung(), Decimal('1700'))
        self.assertEqual(ergebnis['score'], 100,
                         f"Bestmögliche Bewerbung erreicht nur {ergebnis['score']} Punkte")

    def test_fehlender_betreibungsauszug_kostet_punkte(self):
        """Gegenstück: Der Massstab darf nicht einfach immer volle Punkte geben."""
        from core.services.bewerber_scoring import bewerte_bewerbung
        b = self._bewerbung(digitaler_betreibungsauszug=False)
        self.assertLess(bewerte_bewerbung(b, Decimal('1700'))['score'], 100)

    def test_zweite_stufe_kann_unterlagen_nachtragen(self):
        """Das Formular verspricht «fragen wir später an» — dieser Weg muss
        also existieren, sonst ist es eine leere Zusage."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        b = self._bewerbung()
        c = Client(); c.force_login(_team_user('Sachbearbeitung'))
        c.post(f'/neu/bewerbungen/{b.id}/unterlagen/', {
            'lohnausweis': SimpleUploadedFile('lohn.pdf', b'%PDF-1.4', content_type='application/pdf')})
        b.refresh_from_db()
        self.assertTrue(b.lohnausweis, 'Nachgetragener Einkommensnachweis wurde nicht abgelegt')

    def test_lesende_rolle_kann_keine_unterlagen_nachtragen(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        b = self._bewerbung()
        c = Client(); c.force_login(_team_user('Lesend'))
        r = c.post(f'/neu/bewerbungen/{b.id}/unterlagen/', {
            'lohnausweis': SimpleUploadedFile('l.pdf', b'%PDF', content_type='application/pdf')})
        self.assertEqual(r.status_code, 403)
        b.refresh_from_db()
        self.assertFalse(b.lohnausweis)

    def test_marktdaten_zeitstempel_haelt_die_pruefung_fest(self):
        """Der Stempel muss bei JEDER erfolgreichen Prüfung gesetzt werden.
        War er an eine Wertänderung gekoppelt, galten die Daten dazwischen
        dauernd als veraltet — die Frischeprüfung lief damit ins Leere."""
        from unittest import mock
        from django.utils import timezone
        from crm.models import Organisation
        from core.utils import market_data
        vw = _test_organisation(firma='T AG', strasse='W 1', plz='3000', ort='Bern',
                                       aktueller_referenzzinssatz=Decimal('1.25'))
        vw.letztes_update_marktdaten = None
        vw.save()
        with mock.patch.object(market_data, 'fetch_market_rates',
                               return_value=({'ref_zins': Decimal('1.25')}, [])):
            market_data.update_verwaltung_rates()
        vw.refresh_from_db()
        self.assertIsNotNone(vw.letztes_update_marktdaten,
                             'Unveränderter Wert → Zeitstempel bleibt leer → Prüfung wirkungslos')

    def test_qr_ohne_schuldneradresse_laesst_den_block_leer(self):
        """Ein «S»-Block ohne Postleitzahl und Ort ist ein ungültiger
        Einzahlungsschein. Ist der Schuldner unbekannt (Leerstand), verlangt
        die Spezifikation sieben LEERE Felder."""
        from core.utils.qr_code import adressblock
        self.assertEqual(adressblock({'name': '—', 'line1': '', 'line2': ''}, pflicht=False),
                         ['', '', '', '', '', '', ''])
        # Mit vollständiger Adresse bleibt es ein normaler strukturierter Block
        voll = adressblock({'name': 'Anna', 'plz': '3000', 'ort': 'Bern'}, pflicht=False)
        self.assertEqual(voll[0], 'S')

    def test_deploy_warnt_wenn_das_webhook_secret_fehlt(self):
        """Die Härtung hat eine Kehrseite: Wer DocuSeal bisher OHNE Secret
        betrieben hat, verliert den Rücklauf — lautlos. Der Deploy muss das
        sagen, sonst fällt es erst auf, wenn jemand einen unterschriebenen
        Vertrag sucht."""
        import io
        from django.core.management import call_command
        from django.test import override_settings
        raus, fehler = io.StringIO(), io.StringIO()
        with override_settings(DOCUSEAL_API_KEY='vorhanden', DOCUSEAL_WEBHOOK_SECRET=None):
            call_command('pruefe_webhook_secrets', stdout=raus, stderr=fehler)
        text = raus.getvalue() + fehler.getvalue()
        self.assertIn('DOCUSEAL_WEBHOOK_SECRET', text)
        self.assertIn('nicht abgelegt', text, 'Die Folge wird nicht benannt')

    def test_deploy_schweigt_wenn_alles_gesetzt_ist(self):
        import io
        from django.core.management import call_command
        from django.test import override_settings
        raus = io.StringIO()
        with override_settings(DOCUSEAL_API_KEY='vorhanden', DOCUSEAL_WEBHOOK_SECRET='geheim'):
            call_command('pruefe_webhook_secrets', stdout=raus, stderr=io.StringIO())
        self.assertIn('nichts offen', raus.getvalue())

    def test_deploy_ruft_die_pruefung_auf(self):
        import os
        from django.conf import settings
        with open(os.path.join(settings.BASE_DIR, 'deploy.sh')) as fh:
            self.assertIn('pruefe_webhook_secrets', fh.read())


class StilleDatenverlusteTests(TestCase):
    """Ein Fehler in EINEM Feld darf keine andere, gültige Angabe wegräumen —
    und schon gar nicht mit grüner Erfolgsmeldung. Drei belegte Fälle."""

    def _team(self):
        c = Client(); c.force_login(_team_user()); return c

    def test_iban_fehler_loescht_die_korrespondenzadresse_nicht(self):
        """Korrespondenzadresse erfassen → speichern. Dann IBAN vertippen →
        Fehler. Auf der Fehlerseite die IBAN korrigieren → speichern. Die
        Korrespondenzadresse muss erhalten bleiben (sie steuert, wohin
        Mahnungen zugestellt werden)."""
        from crm.models import Mieter, MieterAdresse
        m = Mieter.objects.create(typ='person', vorname='Eva', nachname='Muster',
                                  email='eva@example.ch', strasse='Weg 1', plz='3000', ort='Bern')
        c = self._team()
        basis = {'typ': 'person', 'vorname': 'Eva', 'nachname': 'Muster',
                 'email': 'eva@example.ch', 'strasse': 'Weg 1', 'plz': '3000', 'ort': 'Bern',
                 'k_strasse': 'Postfach 4711', 'k_plz': '6000', 'k_ort': 'Luzern'}
        c.post(f'/neu/personen/{m.id}/bearbeiten/', basis)
        self.assertTrue(MieterAdresse.objects.filter(mieter=m, art='korrespondenz').exists(),
                        'Korrespondenzadresse wurde gar nicht erst gespeichert')
        # Jetzt mit ungültiger IBAN — Fehler. Das gerenderte Formular muss die
        # k_*-Felder zurückgeben, sonst kommen sie beim nächsten Speichern leer.
        r = c.post(f'/neu/personen/{m.id}/bearbeiten/', {**basis, 'iban': 'CH00 0000'})
        self.assertContains(r, 'Postfach 4711',
                            msg_prefix='Fehlerseite gibt die Korrespondenzadresse nicht zurück')
        # Zweiter Speichern mit korrekter IBAN + zurückgegebenen k_*-Feldern
        c.post(f'/neu/personen/{m.id}/bearbeiten/',
               {**basis, 'iban': '', 'k_strasse': 'Postfach 4711', 'k_plz': '6000', 'k_ort': 'Luzern'})
        korr = MieterAdresse.objects.filter(mieter=m, art='korrespondenz').first()
        self.assertIsNotNone(korr, 'Korrespondenzadresse wurde still gelöscht')
        self.assertEqual(korr.ort, 'Luzern')

    def test_kuendigung_zuruecknehmen_behaelt_befristetes_ende(self):
        """Befristeter Vertrag, ausserordentlich gekündigt, dann Kündigung
        zurückgenommen: das vereinbarte Zeitablauf-Ende muss bleiben. Vorher
        wurde ende hart auf None gesetzt → Vertrag lief unbegrenzt weiter."""
        from rentals.models import Kuendigung
        _lg, _e, _m, v = _basis_objekte()
        v.ist_befristet = True
        v.beginn = date(2026, 9, 1); v.ende = date(2027, 8, 31)
        v.status = 'gekuendigt'; v.save()
        k = Kuendigung.objects.create(vertrag=v, eingang_datum=date(2026, 8, 1),
                                      per_datum=date(2026, 12, 31), status='bestaetigt')
        self._team().post(f'/neu/kuendigung/{k.id}/zuruecknehmen/')
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')
        self.assertEqual(v.ende, date(2027, 8, 31),
                         'Befristetes Enddatum wurde bei der Rücknahme gelöscht')

    def test_kuendigung_zuruecknehmen_unbefristet_loescht_ende(self):
        """Gegenstück: Ein UNbefristeter Vertrag verliert sein Ende zu Recht —
        er läuft nach der Rücknahme wieder auf unbestimmte Zeit."""
        from rentals.models import Kuendigung
        _lg, _e, _m, v = _basis_objekte()
        v.ist_befristet = False
        v.ende = date(2026, 12, 31); v.status = 'gekuendigt'; v.save()
        k = Kuendigung.objects.create(vertrag=v, eingang_datum=date(2026, 8, 1),
                                      per_datum=date(2026, 12, 31), status='bestaetigt')
        self._team().post(f'/neu/kuendigung/{k.id}/zuruecknehmen/')
        v.refresh_from_db()
        self.assertIsNone(v.ende)

    def test_entwurf_bearbeiten_behaelt_staffelstufen(self):
        """Einen Staffel-Entwurf am Nettomietzins bearbeiten (das Formular
        sendet keine Staffeldaten zurück): die Stufen dürfen nicht verschwinden,
        sonst stünde der Vertrag auf «Staffel» ohne eine einzige Stufe."""
        from rentals.models import Staffelstufe
        _lg, e, m, v = _basis_objekte()
        v.mietzins_modell = 'staffel'; v.status = 'entwurf'; v.save()
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2027, 1, 1),
                                    netto_mietzins=Decimal('2100'))
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2028, 1, 1),
                                    netto_mietzins=Decimal('2200'))
        c = self._team()
        # Bearbeiten OHNE staffel_ab/staffel_netto (wie das Entwurf-Formular postet)
        c.post('/neu/vertraege/neu/speichern/', {
            'edit_id': str(v.id), 'einheit_id': str(e.id), 'mieter_id': str(m.id),
            'beginn': '2026-01-01', 'unbefristet': '1',
            'netto_mietzins': '2150', 'nebenkosten': '200',
            'mietzins_modell': 'staffel'})
        self.assertEqual(Staffelstufe.objects.filter(vertrag=v).count(), 2,
                         'Staffelstufen wurden beim Bearbeiten still gelöscht')


class VertragMieterspiegelFTests(TestCase):
    """Live-Test F: Vertrags-Validierung (serverseitig) + Mieterspiegel nach Datum."""

    def _post_vertrag(self, c, einheit, **overrides):
        data = {
            'einheit_id': str(einheit.id),
            'mieter_typ': 'person', 'vorname': 'Anna', 'nachname': 'Beispiel',
            'beginn': '2026-01-01', 'netto_mietzins': '1500', 'nebenkosten': '200',
        }
        data.update(overrides)
        return c.post('/neu/vertraege/neu/speichern/', data)

    def test_f_negative_miete_wird_abgewiesen(self):
        from rentals.models import Mietvertrag
        from crm.models import Mieter
        lg, e, m, v = _basis_objekte()
        e2 = e.__class__.objects.create(liegenschaft=lg, bezeichnung='Neu', typ='wohnung',
                                        nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
        n_vor = Mietvertrag.objects.count(); m_vor = Mieter.objects.count()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        self._post_vertrag(c, e2, netto_mietzins='-100')
        self.assertEqual(Mietvertrag.objects.count(), n_vor)   # kein Vertrag
        self.assertEqual(Mieter.objects.count(), m_vor)        # kein Waisen-Mieter

    def test_f_ende_vor_beginn_wird_abgewiesen(self):
        from rentals.models import Mietvertrag
        lg, e, m, v = _basis_objekte()
        e2 = e.__class__.objects.create(liegenschaft=lg, bezeichnung='Neu2', typ='wohnung',
                                        nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
        n_vor = Mietvertrag.objects.count()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        self._post_vertrag(c, e2, beginn='2026-06-01', ende='2026-03-01', ist_befristet='1')
        self.assertEqual(Mietvertrag.objects.count(), n_vor)

    def test_f_leerer_nachname_wird_abgewiesen(self):
        from rentals.models import Mietvertrag
        from crm.models import Mieter
        lg, e, m, v = _basis_objekte()
        e2 = e.__class__.objects.create(liegenschaft=lg, bezeichnung='Neu3', typ='wohnung',
                                        nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
        n_vor = Mietvertrag.objects.count(); m_vor = Mieter.objects.count()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        self._post_vertrag(c, e2, nachname='', vorname='Nurvorname')
        self.assertEqual(Mietvertrag.objects.count(), n_vor)
        self.assertEqual(Mieter.objects.count(), m_vor)

    def test_f_unbefristet_mit_altem_ende_wird_akzeptiert(self):
        # Ende < Beginn, aber NICHT befristet → Ende wird beim Speichern verworfen;
        # die Anlage darf nicht an einer Ende-vor-Beginn-Prüfung scheitern (Review).
        from rentals.models import Mietvertrag
        lg, e, m, v = _basis_objekte()
        e2 = e.__class__.objects.create(liegenschaft=lg, bezeichnung='Unbef', typ='wohnung',
                                        nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
        n_vor = Mietvertrag.objects.count()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        # ende in der Vergangenheit, ist_befristet NICHT gesetzt
        self._post_vertrag(c, e2, beginn='2026-06-01', ende='2020-01-01')
        self.assertEqual(Mietvertrag.objects.count(), n_vor + 1)
        neu = Mietvertrag.objects.exclude(id=v.id).filter(einheit=e2).first()
        self.assertIsNone(neu.ende, 'Ende wurde bei unbefristetem Vertrag nicht verworfen')

    def test_f_gueltiger_vertrag_wird_gespeichert(self):
        # Gegenstück: ein sauberer Vertrag muss weiterhin durchgehen.
        from rentals.models import Mietvertrag
        lg, e, m, v = _basis_objekte()
        e2 = e.__class__.objects.create(liegenschaft=lg, bezeichnung='OK', typ='wohnung',
                                        nettomiete_aktuell=Decimal('1000'), nebenkosten_aktuell=Decimal('100'))
        n_vor = Mietvertrag.objects.count()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        self._post_vertrag(c, e2)
        self.assertEqual(Mietvertrag.objects.count(), n_vor + 1)

    def test_f_mieterspiegel_gekuendigter_laufender_vertrag_ist_belegt(self):
        from core.services.mieterspiegel import berechne_mieterspiegel
        lg, e, m, v = _basis_objekte()
        # gekündigt, aber läuft bis Ende 2026 → am Stichtag 06/2026 in Kraft
        v.status = 'gekuendigt'; v.beginn = date(2024, 1, 1); v.ende = date(2026, 12, 31); v.save()
        spiegel = berechne_mieterspiegel([lg], stichtag=date(2026, 6, 1))
        zeile = next(z for z in spiegel[0]['zeilen'] if z['einheit'].id == e.id)
        self.assertTrue(zeile['belegt'], 'gekündigter aber laufender Vertrag fehlt im Mieterspiegel')
        self.assertEqual(spiegel[0]['totals']['leer'], 0)

    def test_f_mieterspiegel_zukuenftiger_vertrag_zaehlt_nicht(self):
        from core.services.mieterspiegel import berechne_mieterspiegel
        lg, e, m, v = _basis_objekte()
        # aktiv, aber Beginn erst 09/2026 → am Stichtag 06/2026 noch nicht in Kraft
        v.status = 'aktiv'; v.beginn = date(2026, 9, 1); v.ende = None; v.save()
        spiegel = berechne_mieterspiegel([lg], stichtag=date(2026, 6, 1))
        zeile = next(z for z in spiegel[0]['zeilen'] if z['einheit'].id == e.id)
        self.assertFalse(zeile['belegt'], 'künftiger Vertrag erscheint zu früh als belegt')
        self.assertEqual(spiegel[0]['totals']['leer'], 1)
