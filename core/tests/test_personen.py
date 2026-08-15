"""Testmodul personen — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 10 Klassen, unveraendert uebernommen."""
from datetime import date
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (
    _team_user, _basis_objekte, _seed_konten, Mieter, Eigentuemer,
    Verwaltung, Liegenschaft, Einheit, Wartungsfrist, Mietvertrag, User)



class DatenqualitaetTests(TestCase):
    def test_pflichtfeld_nachname(self):
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post('/neu/personen/neu/', {'typ': 'person', 'vorname': 'Nur Vorname'})
        self.assertContains(r, 'erforderlich')
        self.assertFalse(Mieter.objects.filter(vorname='Nur Vorname').exists())

    def test_dublette_und_override(self):
        Mieter.objects.create(typ='person', vorname='Max', nachname='Zwilling', plz='9000', ort='SG')
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post('/neu/personen/neu/', {'typ': 'person', 'vorname': 'Max', 'nachname': 'Zwilling', 'plz': '9000', 'ort': 'SG'})
        self.assertContains(r, 'Dublette')
        self.assertEqual(Mieter.objects.filter(nachname='Zwilling').count(), 1)
        r2 = c.post('/neu/personen/neu/', {'typ': 'person', 'vorname': 'Max', 'nachname': 'Zwilling', 'plz': '9000', 'ort': 'SG', 'dublette_ok': '1'})
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(Mieter.objects.filter(nachname='Zwilling').count(), 2)


class PersonLoeschenTests(TestCase):
    def test_ohne_vertrag_loeschbar(self):
        m = Mieter.objects.create(typ='person', nachname='Weg')
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post(f'/neu/personen/{m.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Mieter.objects.filter(id=m.id).exists())

    def test_aktiver_vertrag_blockiert(self):
        lg, e, m, v = _basis_objekte()  # v ist aktiv
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post(f'/neu/personen/{m.id}/loeschen/', follow=True)
        self.assertTrue(Mieter.objects.filter(id=m.id).exists())
        self.assertContains(r, 'kann nicht gelöscht werden')

    def test_portal_login_wird_mitgeloescht(self):
        m = Mieter.objects.create(typ='person', nachname='PortalWeg')
        pu = User.objects.create_user(username='portalweg@x.ch', password='x')
        m.benutzer = pu; m.save()
        u = _team_user()
        c = Client(); c.force_login(u)
        c.post(f'/neu/personen/{m.id}/loeschen/')
        self.assertFalse(Mieter.objects.filter(id=m.id).exists())
        self.assertFalse(User.objects.filter(id=pu.id).exists())


class BenutzerListeTests(TestCase):
    def test_portalkonten_ausgeblendet_teamkonten_sichtbar(self):
        team = _team_user()  # Gruppe 'Verwaltung'
        # Mieter-Portal-Konto
        mu = User.objects.create_user(username='miet_portal@x.ch')
        m = Mieter.objects.create(typ='person', nachname='PL'); m.benutzer = mu; m.save()
        c = Client(); c.force_login(team)
        r = c.get('/neu/benutzer/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, team.username)
        self.assertNotContains(r, 'miet_portal@x.ch')
        self.assertContains(r, 'Löschen')


class PersonFirmaVereinTests(TestCase):
    """Nachname nur bei Privatperson Pflicht; Firma/Verein via Firmenname.
    Vertragswizard erlaubt Firma/Verein als neue Person."""

    def test_verein_ohne_nachname_speicherbar(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {
            'typ': 'verein', 'firmen_name': 'Stiftung Sonnenschein', 'nachname': '',
            'strasse': 'Weg 1', 'plz': '8000', 'ort': 'Zürich', 'dublette_ok': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Mieter.objects.filter(typ='verein', firmen_name='Stiftung Sonnenschein').exists())

    def test_firma_ohne_nachname_speicherbar(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {
            'typ': 'firma', 'firmen_name': 'Muster AG', 'nachname': '', 'dublette_ok': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Mieter.objects.filter(typ='firma', firmen_name='Muster AG').exists())

    def test_verein_ohne_firmenname_fehler(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {'typ': 'verein', 'firmen_name': '', 'nachname': '', 'dublette_ok': '1'})
        self.assertEqual(r.status_code, 200)  # Fehler, kein Redirect
        self.assertContains(r, 'Organisationsname ist erforderlich')
        self.assertFalse(Mieter.objects.filter(typ='verein').exists())

    def test_privatperson_braucht_nachname(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {'typ': 'person', 'vorname': 'Hans', 'nachname': '', 'dublette_ok': '1'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Nachname ist erforderlich')

    def test_wizard_neuer_mieter_firma(self):
        from portfolio.models import Einheit
        lg = Liegenschaft.objects.create(strasse='Bahnhofstr 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Büro', typ='gew',
                                   nettomiete_aktuell=Decimal('2000'))
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': str(e.id), 'mieter_typ': 'firma', 'firmen_name': 'Handels GmbH',
            'kontaktperson': 'Frau Meier', 'm_strasse': 'Weg 3', 'm_plz': '8000', 'm_ort': 'Zürich',
            'netto_mietzins': '2000', 'nebenkosten': '200', 'beginn': '2025-01-01'})
        self.assertEqual(r.status_code, 302)
        m = Mieter.objects.get(firmen_name='Handels GmbH')
        self.assertEqual(m.typ, 'firma')
        self.assertEqual(m.kontaktperson, 'Frau Meier')


class PersonDokumenteGruppenTests(TestCase):
    """Person-Dokumente nach Mietverhältnis (= Vertrag) gruppiert (Akkordeon);
    Dokumente ohne Vertragsbezug landen zuletzt im «Persönlich»-Bündel."""

    def _doc(self, **kw):
        from rentals.models import Dokument
        from django.core.files.base import ContentFile
        d = Dokument(kategorie='vertrag', **kw)
        d.datei.save('x.pdf', ContentFile(b'%PDF-1'), save=False)
        d.save()
        return d

    def test_gruppierung_verhaeltnis_und_persoenlich(self):
        lg, e, m, v = _basis_objekte()
        self._doc(mieter=m, bezeichnung='Persoenlich-Doc')          # ohne Vertragsbezug
        self._doc(vertrag=v, bezeichnung='Objekt-Doc')              # Verhältnis → Vertrag v
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/personen/{m.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['dok_total'], 2)
        gruppen = r.context['dok_gruppen']
        # Verhältnis (Vertrag) zuerst, Persönlich zuletzt
        self.assertEqual(gruppen[0]['vertrag'], v)
        self.assertIsNone(gruppen[-1]['einheit'])
        self.assertIsNone(gruppen[-1]['vertrag'])
        labels = [g['label'] for g in gruppen]
        self.assertTrue(any('3.5 Zi' in l for l in labels))
        self.assertContains(r, 'Objekt-Doc')
        self.assertContains(r, 'Persoenlich-Doc')

    def test_keine_dokumente(self):
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/personen/{m.id}/')
        self.assertEqual(r.context['dok_total'], 0)


class LoeschbarkeitTests(TestCase):
    """Addierbare Stammdaten/Listen müssen löschbar sein."""

    def test_dienstleister_loeschen(self):
        from crm.models import Handwerker
        h = Handwerker.objects.create(firma='Muster AG')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/dienstleister/{h.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Handwerker.objects.filter(id=h.id).exists())

    def test_dienstleister_bearbeiten(self):
        from crm.models import Handwerker
        h = Handwerker.objects.create(firma='Alt AG', branche='allgemein', telefon='000')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/dienstleister/{h.id}/bearbeiten/', {
            'firma': 'Neu AG', 'branche': 'elektro',
            'kontaktperson': 'Frau Muster', 'email': 'a@b.ch', 'telefon': '079'})
        self.assertEqual(r.status_code, 302)
        h.refresh_from_db()
        self.assertEqual(h.firma, 'Neu AG')
        self.assertEqual(h.branche, 'elektro')
        self.assertEqual(h.kontaktperson, 'Frau Muster')
        self.assertEqual(h.telefon, '079')

    def test_asset_loeschen(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        g = Geraet.objects.create(liegenschaft=lg, kategorie='Heizung')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/assets/{g.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Geraet.objects.filter(id=g.id).exists())

    def test_kreditor_loeschen_nur_neu(self):
        from finance.models import KreditorenRechnung
        lg, e, m, v = _basis_objekte()
        neu = KreditorenRechnung.objects.create(lieferant='Neu AG', betrag=Decimal('100'), status='neu')
        gebucht = KreditorenRechnung.objects.create(lieferant='Alt AG', betrag=Decimal('50'), status='freigegeben')
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        # neu → löschbar
        c.post(f'/neu/kreditoren/{neu.id}/loeschen/')
        self.assertFalse(KreditorenRechnung.objects.filter(id=neu.id).exists())
        # verbucht → bleibt erhalten
        c.post(f'/neu/kreditoren/{gebucht.id}/loeschen/')
        self.assertTrue(KreditorenRechnung.objects.filter(id=gebucht.id).exists())

    def test_kommunikation_loeschen(self):
        from crm.models import Kommunikation
        lg, e, m, v = _basis_objekte()
        k = Kommunikation.objects.create(mieter=m, typ='telefon', richtung='eingehend',
                                         inhalt='Testnotiz')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/kommunikation/{k.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Kommunikation.objects.filter(id=k.id).exists())

    def test_schaden_loeschen(self):
        from tickets.models import SchadenMeldung
        lg, e, m, v = _basis_objekte()
        t = SchadenMeldung.objects.create(liegenschaft=lg, titel='Wasserschaden',
                                          beschreibung='Test')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/schaeden/{t.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(SchadenMeldung.objects.filter(id=t.id).exists())

    def test_rentals_dokument_loeschen_ueberall(self):
        from core.services.ablage import ablegen
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        d = ablegen(b'%PDF', 'Hausordnung', kategorie='vertrag', vertrag=v)
        self.assertIsNotNone(d)
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/dokument/{d.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Dokument.objects.filter(id=d.id).exists())

    def test_portfolio_dokument_loeschen(self):
        from portfolio.models import Dokument as PDok
        from django.core.files.base import ContentFile
        lg, e, m, v = _basis_objekte()
        d = PDok.objects.create(titel='Foto', kategorie='sonstiges', liegenschaft=lg)
        d.datei.save('x.pdf', ContentFile(b'%PDF'), save=True)
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/dokumente/{d.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PDok.objects.filter(id=d.id).exists())

    def test_wartungsfrist_bearbeiten(self):
        from portfolio.models import Wartungsfrist
        from datetime import date as _d
        lg, e, m, v = _basis_objekte()
        wf = Wartungsfrist.objects.create(liegenschaft=lg, art='wartung', bezeichnung='Alt',
                                          naechste_faelligkeit=_d(2025, 1, 1), intervall_monate=12)
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/frist/{wf.id}/bearbeiten/', {
            'art': 'versicherung', 'bezeichnung': 'Neu', 'anbieter': 'AXA',
            'naechste_faelligkeit': '2026-06-01', 'intervall_monate': '24'})
        self.assertEqual(r.status_code, 302)
        wf.refresh_from_db()
        self.assertEqual(wf.bezeichnung, 'Neu')
        self.assertEqual(wf.art, 'versicherung')
        self.assertEqual(wf.intervall_monate, 24)

    def test_asset_bearbeiten(self):
        from portfolio.models import Geraet
        lg, e, m, v = _basis_objekte()
        g = Geraet.objects.create(liegenschaft=lg, kategorie='Boiler')
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/assets/{g.id}/bearbeiten/', {
            'kategorie': 'Wärmepumpe', 'kapazitaet': '12 kW', 'seriennummer': 'X1'})
        self.assertEqual(r.status_code, 302)
        g.refresh_from_db()
        self.assertEqual(g.kategorie, 'Wärmepumpe')
        self.assertEqual(g.kapazitaet, '12 kW')

    def test_abnahme_loeschen(self):
        from rentals.models import Abnahmeprotokoll
        from django.utils import timezone
        lg, e, m, v = _basis_objekte()
        p = Abnahmeprotokoll.objects.create(vertrag=v, typ='einzug', datum=timezone.localdate())
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/abnahme/{p.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Abnahmeprotokoll.objects.filter(id=p.id).exists())

    def test_nebenkosten_periode_loeschen(self):
        from finance.models import AbrechnungsPeriode
        from datetime import date as _d
        lg, e, m, v = _basis_objekte()
        p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='NK 2025',
                                              start_datum=_d(2025, 1, 1), ende_datum=_d(2025, 12, 31))
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/nebenkosten/{p.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(AbrechnungsPeriode.objects.filter(id=p.id).exists())


class DatenLebenszyklusTests(TestCase):
    """Regression gegen die Klasse 'verwaiste/doppelte Daten beim Löschen &
    Re-Trigger' (Audit nach dem Vertragsdokument-Bug): zentrale Dokument-
    Bereinigung, CASCADE der Anpassungs-Sollmietzinse, Idempotenz von
    Schlussabrechnung/Mahnung, camt-Dedup ohne Datenverlust, Auto-Frist-Cleanup."""

    def _dok(self, v, e, m, titel='Mietvertrag', kategorie='vertrag'):
        from rentals.models import Dokument
        from django.core.files.base import ContentFile
        d = Dokument.objects.create(vertrag=v, einheit=e, mieter=m,
                                    kategorie=kategorie, bezeichnung=titel, titel=titel)
        d.datei.save('x.pdf', ContentFile(b'%PDF-1.4'), save=True)
        return d

    def test_vertrag_delete_raeumt_vertragspaket_zentral(self):
        # Modell-Ebene: deckt UI- UND API-Löschpfad ab (delete() override).
        from rentals.models import Dokument
        _lg, e, m, v = _basis_objekte()
        self._dok(v, e, m, 'Mietvertrag')
        self._dok(v, e, m, 'Hausordnung')
        fremd = self._dok(v, e, m, 'Mieterbrief', kategorie='korrespondenz')
        v.delete()
        # Vertragspaket ist weg (kein verwaister vertrag=None-Rest)
        self.assertEqual(Dokument.objects.filter(bezeichnung__in=['Mietvertrag', 'Hausordnung']).count(), 0)
        # Fremd-Korrespondenz bleibt erhalten
        self.assertTrue(Dokument.objects.filter(id=fremd.id).exists())

    def test_anpassung_sollmietzins_cascade_kein_orphan(self):
        # Löschen der Anpassung (bzw. via Vertrags-CASCADE) darf keine
        # quelle_anpassung=NULL-Zeile zurücklassen, die als Basismiete gilt.
        from rentals.models import MietzinsAnpassung
        from portfolio.models import Sollmietzins
        _lg, e, m, v = _basis_objekte()
        anp = MietzinsAnpassung.objects.create(vertrag=v, wirksam_ab=date(2024, 7, 1),
                                               neuer_netto_mietzins=Decimal('1600'))
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2024, 7, 1),
                                    netto_mietzins=Decimal('1600'), nebenkosten=Decimal('200'),
                                    quelle_anpassung=anp)
        # Direktes Löschen der Anpassung
        anp.delete()
        self.assertEqual(Sollmietzins.objects.filter(einheit=e, quelle_anpassung__isnull=True).count(), 0)
        # Auch der Vertrags-CASCADE-Pfad darf keine Waise erzeugen
        anp2 = MietzinsAnpassung.objects.create(vertrag=v, wirksam_ab=date(2024, 8, 1),
                                                neuer_netto_mietzins=Decimal('1700'))
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2024, 8, 1),
                                    netto_mietzins=Decimal('1700'), nebenkosten=Decimal('200'),
                                    quelle_anpassung=anp2)
        v.delete()
        self.assertEqual(Sollmietzins.objects.filter(quelle_anpassung__isnull=True).count(), 0)

    def test_schlussabrechnung_nicht_doppelt_gebucht(self):
        from finance.models import DebitorenRechnung
        _seed_konten()
        _lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        payload = {'auszug_datum': '2024-06-30', 'aktion': 'buchen',
                   'pos_text': 'Reinigung', 'pos_betrag': '500', 'pos_richtung': 'zulasten'}
        for _ in range(2):
            c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/', payload)
        # Trotz zweimaligem Absenden nur EIN Nachzahlungs-Debitor + eine Buchung.
        self.assertEqual(DebitorenRechnung.objects.filter(
            vertrag=v, titel='Schlussabrechnung (Nachzahlung)').count(), 1)

    def test_camt_notprovided_gehen_nicht_verloren(self):
        # Zwei verschiedene Gutschriften, beide EndToEndId=NOTPROVIDED, keine
        # AcctSvcrRef → dürfen NICHT als Duplikat verworfen werden.
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        _seed_konten()
        _basis_objekte()
        xml = (
            '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt>'
            '<Ntry><CdtDbtInd>CRDT</CdtDbtInd><Amt Ccy="CHF">1700.00</Amt>'
            '<BookgDt><Dt>2024-03-05</Dt></BookgDt><NtryDtls><TxDtls>'
            '<Refs><EndToEndId>NOTPROVIDED</EndToEndId></Refs></TxDtls></NtryDtls></Ntry>'
            '<Ntry><CdtDbtInd>CRDT</CdtDbtInd><Amt Ccy="CHF">1800.00</Amt>'
            '<BookgDt><Dt>2024-03-05</Dt></BookgDt><NtryDtls><TxDtls>'
            '<Refs><EndToEndId>NOTPROVIDED</EndToEndId></Refs></TxDtls></NtryDtls></Ntry>'
            '</Stmt></BkToCstmrStmt></Document>'
        ).encode('utf-8')
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('camt.xml', xml, content_type='application/xml')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        # Beide Zahlungen erfasst (auf Durchlaufkonto geparkt), keine fälschlich verworfen.
        self.assertEqual(Zahlungseingang.objects.count(), 2)

    def test_manuelle_mahnung_nicht_doppelt(self):
        from finance.models import Mahnung, DebitorenRechnung
        _seed_konten()
        _lg, e, m, v = _basis_objekte()
        rech = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=_lg, einheit=e,
                                                titel='Miete 01/2024', datum=date(2024, 1, 1),
                                                faellig_am=date(2024, 1, 31), betrag=Decimal('1700'),
                                                status='offen')
        c = Client(); c.force_login(_team_user())
        payload = {'rechnung_id': rech.id, 'stufe': '1', 'gebuehr': '20'}
        for _ in range(2):
            c.post('/neu/mahnwesen/erfassen/', payload)
        self.assertEqual(Mahnung.objects.filter(debitoren_rechnung=rech, stufe=1).count(), 1)
        self.assertEqual(DebitorenRechnung.objects.filter(
            vertrag=v, titel='Mahngebühr 1. Mahnung').count(), 1)

    def test_geraet_loeschen_raeumt_auto_pendenz(self):
        from portfolio.models import Geraet
        from core.models import Pendenz
        lg, e, _m, _v = _basis_objekte()
        g = Geraet.objects.create(liegenschaft=lg, kategorie='boiler',
                                  garantie_bis=date(2024, 12, 31))
        Pendenz.objects.create(titel='Garantie läuft ab: Boiler', kategorie='unterhalt',
                               quelle=f'auto:garantie:{g.id}', liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/geraet/{g.id}/loeschen/')
        self.assertFalse(Pendenz.objects.filter(quelle=f'auto:garantie:{g.id}').exists())

    def test_wartungsfrist_loeschen_raeumt_auto_pendenz(self):
        from portfolio.models import Wartungsfrist
        from core.models import Pendenz
        lg, _e, _m, _v = _basis_objekte()
        wf = Wartungsfrist.objects.create(liegenschaft=lg, art='wartung', bezeichnung='Lift',
                                          naechste_faelligkeit=date(2024, 12, 1),
                                          intervall_monate=12, aktiv=True)
        Pendenz.objects.create(titel='Wartung: Lift', kategorie='unterhalt',
                               quelle=f'auto:wartung:{wf.id}:2024-12-01', liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/frist/{wf.id}/loeschen/')
        self.assertFalse(Pendenz.objects.filter(quelle__startswith=f'auto:wartung:{wf.id}:').exists())

    # --- Löschpfade: Schutz vor Datenverlust bei aktivem Vertrag ---
    # Diese drei prüften bis E1c die django-ninja-Funktionen direkt. Die API ist
    # weg; dieselben Zusicherungen gelten unverändert für die /neu/-Oberfläche,
    # die sie ebenfalls trägt — deshalb umgeschrieben statt gelöscht.
    def _c(self):
        c = Client(); c.force_login(_team_user()); return c

    def test_person_loeschen_blockt_aktiven_vertrag(self):
        from crm.models import Mieter
        _lg, _e, m, _v = _basis_objekte()   # v ist status='aktiv'
        self._c().post(f'/neu/personen/{m.id}/loeschen/')
        self.assertTrue(Mieter.objects.filter(id=m.id).exists())

    def test_person_loeschen_raeumt_portal_login(self):
        from crm.models import Mieter
        _lg, _e, m, v = _basis_objekte()
        v.status = 'beendet'; v.aktiv = False; v.save()
        u = User.objects.create_user(username='portal_mieter', password='x')
        m.benutzer = u; m.save()
        self._c().post(f'/neu/personen/{m.id}/loeschen/')
        self.assertFalse(Mieter.objects.filter(id=m.id).exists())
        self.assertFalse(User.objects.filter(id=u.id).exists())

    def test_liegenschaft_loeschen_blockt_aktiven_vertrag(self):
        lg, _e, _m, _v = _basis_objekte()
        self._c().post(f'/neu/liegenschaften/{lg.id}/loeschen/')
        self.assertTrue(Liegenschaft.objects.filter(id=lg.id).exists())

    # Der vierte Fall — `delete_einheit` blockt aktiven Vertrag — ist mit E1c
    # ersatzlos entfallen: In /neu/ gibt es überhaupt kein Einheit-Löschen, der
    # API-Endpunkt war der einzige Weg. Erreichbar war er nur über die in E1b
    # entfernte Vue-Oberfläche, die Fähigkeit ist also seit E1b weg und nicht
    # erst jetzt. Kommt sie nach /neu/, gehört dieser Test wieder her.

    def test_mandat_loeschen_raeumt_eigentuemer_login(self):
        from crm.models import Eigentuemer
        md = Eigentuemer.objects.create(firma_oder_name='Eigentümer AG')
        u = User.objects.create_user(username='portal_owner', password='x')
        md.benutzer = u; md.save()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mandate/{md.id}/loeschen/')
        self.assertFalse(Eigentuemer.objects.filter(id=md.id).exists())
        self.assertFalse(User.objects.filter(id=u.id).exists())


class DSGAnonymisierungTests(TestCase):
    def test_anonymisierung_scrubbt_pii_behaelt_beleg(self):
        from core.services.dsg import anonymisiere_person
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        v.status = 'beendet'; v.save()   # kein aktiver Vertrag
        rechnung = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, einheit=e, titel='Miete 01/2024',
            betrag=Decimal('1700'), status='offen')
        ok, _msg = anonymisiere_person(m, grund='Auszug + Löschantrag')
        self.assertTrue(ok)
        m.refresh_from_db()
        self.assertTrue(m.anonymisiert)
        self.assertEqual(m.vorname, 'Anonymisiert')
        self.assertEqual(m.email, '')
        self.assertEqual(m.strasse, '')
        # Buchungsbeleg bleibt erhalten (OR 958f).
        self.assertTrue(DebitorenRechnung.objects.filter(id=rechnung.id).exists())

    def test_aktiver_vertrag_blockt(self):
        from core.services.dsg import anonymisiere_person, kann_anonymisieren
        _lg, _e, m, v = _basis_objekte()   # Vertrag ist aktiv
        ok, grund = kann_anonymisieren(m)
        self.assertFalse(ok)
        ok2, _ = anonymisiere_person(m)
        self.assertFalse(ok2)
        m.refresh_from_db()
        self.assertFalse(m.anonymisiert)
        self.assertEqual(m.vorname, 'Hans')   # unverändert

    def test_view_anonymisiert(self):
        lg, e, m, v = _basis_objekte()
        v.status = 'beendet'; v.save()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/personen/{m.id}/dsg-loeschen/', {'grund': 'Löschantrag'})
        self.assertEqual(r.status_code, 302)
        m.refresh_from_db()
        self.assertTrue(m.anonymisiert)


class PersonenStammdatenTests(TestCase):
    """Voll-Ausbau der Personen-Stammdaten: Formular erfasst alle fachlichen
    Felder, Bewerbung→Mieter übernimmt Haushalt/Beruf, DSG scrubbt neue Felder."""

    def test_formular_speichert_alle_felder(self):
        from crm.models import Mieter
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {
            'typ': 'person', 'vorname': 'Anna', 'nachname': 'Muster',
            'zivilstand': 'verheiratet', 'nationalitaet': 'Deutschland', 'heimatort': 'Berlin',
            'ahv_nummer': '756.1234.5678.90', 'sprache': 'fr', 'telefon_geschaeft': '044 111 22 33',
            'aufenthaltsbewilligung': 'C', 'bewilligung_gueltig_bis': '2030-12-31',
            'erwerbsstatus': 'angestellt', 'beruf': 'Ärztin', 'arbeitgeber': 'Spital AG',
            'einkommen_jahr': "120'000", 'bonitaet_datum': '2026-01-15',
            'haushalt_erwachsene': '2', 'haushalt_kinder': '1', 'haustiere': 'on',
            'haustiere_details': '1 Katze', 'haftpflicht_gesellschaft': 'AXA',
            'haftpflicht_police': 'P-4711', 'notfall_name': 'Beat Muster',
            'notfall_telefon': '079 000 11 22', 'notfall_beziehung': 'Ehemann',
            'bank_name': 'ZKB', 'dublette_ok': '1',
        })
        self.assertEqual(r.status_code, 302)
        m = Mieter.objects.get(nachname='Muster', vorname='Anna')
        self.assertEqual(m.zivilstand, 'verheiratet')
        self.assertEqual(m.sprache, 'fr')
        self.assertEqual(m.aufenthaltsbewilligung, 'C')
        self.assertEqual(m.bewilligung_gueltig_bis, date(2030, 12, 31))
        self.assertEqual(m.arbeitgeber, 'Spital AG')
        self.assertEqual(m.haushalt_erwachsene, 2)
        self.assertEqual(m.haushalt_kinder, 1)
        self.assertTrue(m.haustiere)
        self.assertEqual(m.haftpflicht_gesellschaft, 'AXA')
        self.assertEqual(m.notfall_name, 'Beat Muster')
        self.assertEqual(m.bank_name, 'ZKB')

    def test_formular_get_rendert_alle_sektionen(self):
        c = Client(); c.force_login(_team_user())
        body = c.get('/neu/personen/neu/').content.decode()
        for s in ['Aufenthaltsbewilligung', 'Korrespondenzsprache', 'Beruf & Bonität',
                  'Haushalt', 'Notfallkontakt', 'box-person-extra']:
            self.assertIn(s, body, f'{s} fehlt im Formular')
        # Kontextsensitive Bewilligungs-Hinweisbox (neutral, kein Mietverbot).
        self.assertIn('bewilligung_hinweis', body)
        self.assertIn('Grenzgänger G', body)
        self.assertIn('Mieten ist für alle Aufenthaltstitel zulässig', body)

    def test_detail_zeigt_neue_felder(self):
        _lg, _e, m, _v = _basis_objekte()
        m.aufenthaltsbewilligung = 'B'; m.beruf = 'Informatiker'; m.notfall_name = 'Eva Muster'
        m.haushalt_erwachsene = 2; m.save()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertIn('Stammdaten &amp; Herkunft', body)
        self.assertIn('Informatiker', body)
        self.assertIn('Eva Muster', body)

    def test_bewerbung_uebernimmt_haushalt(self):
        from mietprozess.models import Mietbewerbung
        from crm.models import Mieter
        _lg, e, _m, _v = _basis_objekte()
        b = Mietbewerbung.objects.create(
            einheit=e, vorname='Neu', nachname='Bewerber', email='neu@example.ch',
            geburtsdatum=date(1990, 1, 1), anzahl_erwachsene=2, anzahl_kinder=3,
            haustiere=True, haustiere_details='Hund', nationalitaet='Schweiz',
            beruf='Lehrer', arbeitgeber='Schule XY')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        m = Mieter.objects.get(nachname='Bewerber')
        self.assertEqual(m.haushalt_erwachsene, 2)
        self.assertEqual(m.haushalt_kinder, 3)
        self.assertTrue(m.haustiere)
        self.assertEqual(m.haustiere_details, 'Hund')
        self.assertEqual(m.beruf, 'Lehrer')

    def test_dsg_scrubbt_neue_felder(self):
        from core.services.dsg import anonymisiere_person
        _lg, _e, m, v = _basis_objekte()
        v.status = 'beendet'; v.save()
        m.aufenthaltsbewilligung = 'C'; m.haftpflicht_police = 'P-1'; m.notfall_name = 'X'
        m.haushalt_erwachsene = 3; m.haustiere = True; m.save()
        ok, _ = anonymisiere_person(m)
        self.assertTrue(ok)
        m.refresh_from_db()
        self.assertEqual(m.aufenthaltsbewilligung, '')
        self.assertEqual(m.haftpflicht_police, '')
        self.assertEqual(m.notfall_name, '')
        self.assertEqual(m.haushalt_erwachsene, 0)
        self.assertFalse(m.haustiere)


class AdressHistorieTests(TestCase):
    """Datierte Adress-Historie (MieterAdresse) + Auto-Sync + Korrespondenz-Vorrang."""

    def test_stichtag_waehlt_gueltige_wohnadresse(self):
        from crm.models import MieterAdresse
        _lg, _e, m, _v = _basis_objekte()
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2000, 1, 1),
                                     strasse='Altweg 1', plz='3000', ort='Bern')
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2030, 1, 1),
                                     strasse='Neuweg 5', plz='8000', ort='Zürich')
        self.assertEqual(m.aktuelle_wohnadresse(date(2026, 7, 17)).strasse, 'Altweg 1')
        self.assertEqual(m.aktuelle_wohnadresse(date(2031, 1, 1)).strasse, 'Neuweg 5')

    def test_korrespondenz_hat_vorrang(self):
        from crm.models import MieterAdresse
        _lg, _e, m, _v = _basis_objekte()
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2000, 1, 1),
                                     strasse='Wohnweg 1', plz='3000', ort='Bern')
        MieterAdresse.objects.create(mieter=m, art='korrespondenz', gueltig_ab=date(2000, 1, 1),
                                     strasse='Postfach 9', plz='3011', ort='Bern')
        self.assertEqual(m.zustelladresse(date(2026, 7, 17))[0], 'Postfach 9')
        self.assertTrue(m.sync_effektive_adresse(date(2026, 7, 17)))
        m.refresh_from_db()
        self.assertEqual(m.strasse, 'Postfach 9')
        self.assertEqual(m.plz, '3011')

    def test_ohne_zeilen_faellt_auf_flat_zurueck(self):
        _lg, _e, m, _v = _basis_objekte()      # hat nur Flat-Adresse, keine Zeilen
        self.assertEqual(m.zustelladresse()[0], 'Seeweg 3')
        self.assertFalse(m.sync_effektive_adresse())  # keine Änderung

    def test_scheduler_synct_effektive_adresse(self):
        from crm.models import MieterAdresse
        from core.services.automation import run_adress_umzuege
        _lg, _e, m, _v = _basis_objekte()
        # Umzug ab heute → wird zur effektiven Adresse
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2000, 1, 1),
                                     strasse='Seeweg 3', plz='8000', ort='Zürich')
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2020, 1, 1),
                                     strasse='Zielweg 7', plz='4000', ort='Basel')
        run_adress_umzuege()
        m.refresh_from_db()
        self.assertEqual(m.strasse, 'Zielweg 7')
        self.assertEqual(m.ort, 'Basel')

    def test_vertragsbeginn_legt_datierte_wohnadresse_an(self):
        from crm.models import MieterAdresse
        lg, e, m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        beginn = (date.today().replace(day=1))
        r = c.post('/neu/vertraege/neu/speichern/', {
            'mieter_id': str(m.id), 'einheit_id': str(e.id),
            'beginn': beginn.isoformat(), 'netto_mietzins': '1500', 'nebenkosten': '200',
            'mietzins_modell': 'fest', 'kautions_betrag': '4500',
        })
        self.assertIn(r.status_code, (200, 302))
        self.assertTrue(MieterAdresse.objects.filter(mieter=m, art='wohn', gueltig_ab=beginn).exists())

    def test_person_form_pflegt_wohn_und_korrespondenz(self):
        from crm.models import MieterAdresse
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/personen/neu/', {
            'typ': 'person', 'vorname': 'Neu', 'nachname': 'Person',
            'strasse': 'Hauptweg 2', 'plz': '3000', 'ort': 'Bern',
            'k_strasse': 'c/o Muster', 'k_plz': '3011', 'k_ort': 'Bern',
        })
        self.assertIn(r.status_code, (200, 302))
        m = Mieter.objects.get(nachname='Person')
        self.assertTrue(MieterAdresse.objects.filter(mieter=m, art='wohn').exists())
        self.assertTrue(MieterAdresse.objects.filter(mieter=m, art='korrespondenz').exists())
        m.refresh_from_db()
        # Korrespondenz hat Vorrang → effektive Adresse
        self.assertEqual(m.strasse, 'c/o Muster')

    def test_adresse_neu_und_loeschen_views(self):
        from crm.models import MieterAdresse
        _lg, _e, m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/personen/{m.id}/adresse/', {
            'art': 'wohn', 'gueltig_ab': '2027-01-01',
            'strasse': 'Zukunftweg 1', 'plz': '9000', 'ort': 'St. Gallen'})
        self.assertEqual(r.status_code, 302)
        adr = MieterAdresse.objects.get(mieter=m, gueltig_ab=date(2027, 1, 1))
        self.assertEqual(adr.ort, 'St. Gallen')
        r2 = c.post(f'/neu/adresse/{adr.id}/loeschen/')
        self.assertEqual(r2.status_code, 302)
        self.assertFalse(MieterAdresse.objects.filter(id=adr.id).exists())

    def test_dsg_anonymisierung_loescht_adress_historie(self):
        from crm.models import MieterAdresse
        from core.services.dsg import anonymisiere_person
        _lg, _e, m, v = _basis_objekte()
        v.status = 'archiviert'; v.save()
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2000, 1, 1),
                                     strasse='Geheimweg 1', plz='3000', ort='Bern')
        ok, _ = anonymisiere_person(m, grund='Test')
        self.assertTrue(ok)
        self.assertEqual(MieterAdresse.objects.filter(mieter=m).count(), 0)
