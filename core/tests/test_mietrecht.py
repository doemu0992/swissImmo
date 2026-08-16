"""Testmodul mietrecht — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 19 Klassen, unveraendert uebernommen."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (_test_organisation,
    _team_user, _basis_objekte, Mieter, Organisation, Liegenschaft, Einheit,
    Mietvertrag, User)



class MieterKuendigungTests(TestCase):
    def _login(self):
        lg, e, m, v = _basis_objekte()
        u = User.objects.create_user(username='kuend_mieter', password='x')
        m.benutzer = u; m.save()
        return lg, e, m, v, u

    def test_nur_eigene_objekte(self):
        lg, e, m, v, u = self._login()
        # Fremdes Objekt + fremder aktiver Vertrag
        fremd_m = Mieter.objects.create(typ='person', nachname='Fremd')
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='FREMD-Whg', typ='wohnung')
        Mietvertrag.objects.create(mieter=fremd_m, einheit=e2, beginn=date(2020, 1, 1),
                                   netto_mietzins=Decimal('1'), nebenkosten=Decimal('0'), status='aktiv')
        c = Client(); c.force_login(u)
        r = c.get('/mieter/kuendigung/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '3.5 Zi')       # eigenes Objekt
        self.assertNotContains(r, 'FREMD-Whg')  # fremdes Objekt NICHT

    def test_erfassen_erzeugt_kuendigung_ohne_status_wechsel(self):
        from rentals.models import Kuendigung
        lg, e, m, v, u = self._login()
        c = Client(); c.force_login(u)
        r = c.post('/mieter/kuendigung/', {'vertrag_id': str(v.id)})
        self.assertEqual(r.status_code, 302)
        k = Kuendigung.objects.filter(vertrag=v).first()
        self.assertIsNotNone(k)
        self.assertEqual(k.absender, 'mieter')
        self.assertEqual(k.status, 'erfasst')
        self.assertEqual(k.zustellung, 'einschreiben')
        self.assertIsNotNone(k.per_datum)
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')  # Verwaltung bestätigt -> noch nicht gekündigt

    def test_brief_pdf_und_isolation(self):
        from rentals.models import Kuendigung
        lg, e, m, v, u = self._login()
        c = Client(); c.force_login(u)
        c.post('/mieter/kuendigung/', {'vertrag_id': str(v.id)})
        k = Kuendigung.objects.get(vertrag=v)
        r = c.get(f'/mieter/kuendigung/{k.id}/brief/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        # Fremder Mieter kommt nicht an den Brief
        m2 = Mieter.objects.create(typ='person', nachname='Andere')
        u2 = User.objects.create_user(username='andere', password='x'); m2.benutzer = u2; m2.save()
        c2 = Client(); c2.force_login(u2)
        self.assertEqual(c2.get(f'/mieter/kuendigung/{k.id}/brief/').status_code, 404)

    def test_verwalter_bestaetigt_portal_kuendigung(self):
        from rentals.models import Kuendigung
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        u = User.objects.create_user(username='kuend_mieter2', password='x'); m.benutzer = u; m.save()
        c = Client(); c.force_login(u)
        c.post('/mieter/kuendigung/', {'vertrag_id': str(v.id)})
        k = Kuendigung.objects.get(vertrag=v)
        # Verwalter bestätigt
        team = _team_user()
        tc = Client(); tc.force_login(team)
        r = tc.post(f'/neu/kuendigung/{k.id}/bestaetigen/')
        self.assertEqual(r.status_code, 302)
        k.refresh_from_db(); v.refresh_from_db()
        self.assertEqual(k.status, 'bestaetigt')
        self.assertEqual(v.status, 'gekuendigt')
        self.assertIsNotNone(v.ende)
        self.assertGreater(Pendenz.objects.filter(vertrag=v).count(), 0)  # Auszugs-Pendenzen

    def test_familienwohnung_zwei_unterschriften(self):
        from rentals.models import Kuendigung
        from core.services.kuendigung_brief import generate_kuendigung_mieter_pdf
        lg, e, m, v, u = self._login()
        v.familienwohnung = True; v.mitmieter_name = 'Anna Muster'; v.save()
        k = Kuendigung.objects.create(vertrag=v, absender='mieter', eingang_datum=date.today(),
                                      berechneter_termin=date(2025, 6, 30), per_datum=date(2025, 6, 30),
                                      status='erfasst')
        pdf = generate_kuendigung_mieter_pdf(v, k)
        self.assertTrue(pdf.startswith(b'%PDF'))
        # Text prüfen via pdf-Rohbytes (Namen im Content-Stream)
        try:
            import fitz
            doc = fitz.open(stream=pdf, filetype='pdf')
            txt = doc[0].get_text()
            self.assertIn('Anna Muster', txt)
            self.assertIn('266m', txt)
        except ImportError:
            pass


class KautionRueckzahlungTests(TestCase):
    def test_rueckzahlung_mit_einbehalt(self):
        _lg, _e, _m, v = _basis_objekte()   # kautions_betrag 4500
        team = _team_user()
        c = Client(); c.force_login(team)
        # Kaution zuerst einzahlen — zurückbezahlt werden kann nur, was auch
        # bilanziert ist (sonst würde eine nie geleistete Kaution ausbezahlt).
        c.post(f'/neu/vertraege/{v.id}/kaution/',
               {'aktion': 'einzahlung', 'einbezahlt_am': '2024-01-05'})
        r = c.post(f'/neu/vertraege/{v.id}/kaution/', {
            'aktion': 'rueckzahlung', 'abzug_betrag': '500', 'abzug_grund': 'Reinigung',
            'zurueckbezahlt_am': '2025-01-31'})
        self.assertEqual(r.status_code, 302)
        v.refresh_from_db()
        self.assertEqual(v.kautions_abzug_betrag, Decimal('500'))
        self.assertEqual(v.kautions_rueckzahlung_betrag, Decimal('4000'))   # 4500 - 500
        self.assertEqual(v.kautions_status, 'zurueckbezahlt')

    def test_einzahlung_setzt_status(self):
        _lg, _e, _m, v = _basis_objekte()
        team = _team_user()
        c = Client(); c.force_login(team)
        c.post(f'/neu/vertraege/{v.id}/kaution/', {'aktion': 'einzahlung', 'einbezahlt_am': '2024-01-05'})
        v.refresh_from_db()
        self.assertEqual(v.kautions_status, 'einbezahlt')
        self.assertIsNotNone(v.kautions_einbezahlt_am)


class KuendigungModalTests(TestCase):
    def test_vertragsliste_zeigt_kuendigen_aktion(self):
        lg, e, m, v = _basis_objekte()   # v ist aktiv
        team = _team_user(); c = Client(); c.force_login(team)
        body = c.get('/neu/vertraege/').content.decode()
        self.assertIn(f'/neu/vertraege/{v.id}/kuendigen/', body)
        self.assertIn("fwModalOpen(this,'Kündigung erfassen')", body)

    def test_kuendigung_form_live_pruefung(self):
        """Das Kündigungsformular enthält die mietrechtliche Live-Prüfung."""
        lg, e, m, v = _basis_objekte()   # Wohnung → geschützt
        team = _team_user(); c = Client(); c.force_login(team)
        body = c.get(f'/neu/vertraege/{v.id}/kuendigen/').content.decode()
        self.assertIn('function kuendigungCheck', body)
        self.assertIn('id="k-warn"', body)
        self.assertIn('IST_GESCHUETZT = true', body)
        self.assertIn('Art. 266l OR', body)

    def test_kuendigung_embed_schliesst_und_legt_pendenzen_an(self):
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        team = _team_user(); c = Client(); c.force_login(team)
        r = c.post(f'/neu/vertraege/{v.id}/kuendigen/', {
            'embed': '1', 'absender': 'mieter', 'eingang_datum': date.today().isoformat(),
            'zustellung': 'einschreiben'})
        self.assertEqual(r.status_code, 200)
        self.assertIn("fwModal: 'done'", r.content.decode())
        v.refresh_from_db()
        self.assertEqual(v.status, 'gekuendigt')
        self.assertTrue(Pendenz.objects.filter(vertrag=v, erledigt=False).exists())


class MietrechtReferenzTests(TestCase):
    """Zentrale Gesetzesreferenzen + Validierungen (analysis → software)."""

    def test_artikel_referenzen(self):
        from core.services import mietrecht
        self.assertEqual(mietrecht.ref('kaution'), 'Art. 257e OR')
        self.assertEqual(mietrecht.ref('verzug'), 'Art. 257d OR')
        self.assertEqual(mietrecht.kuendigung_ref('wohnen'), 'Art. 266c OR')
        self.assertEqual(mietrecht.kuendigung_ref('gewerbe'), 'Art. 266d OR')
        self.assertEqual(mietrecht.kuendigung_ref('nebenobjekt', ist_einstellplatz=True), 'Art. 266e OR')
        self.assertEqual(mietrecht.kuendigung_ref('nebenobjekt', ist_einstellplatz=False), 'Art. 266b OR')

    def test_template_tag(self):
        from django.template import Template, Context
        out = Template("{% load mietrecht_tags %}{% art 'indexmiete' %}|{{ 'staffelmiete'|artikel }}").render(Context({}))
        self.assertEqual(out, 'Art. 269b OR|Art. 269c OR')

    def test_pruefe_mietzinsmodell(self):
        from core.services.mietrecht import pruefe_mietzinsmodell
        from datetime import date as d
        # Index ohne Ende → Warnung
        self.assertTrue(pruefe_mietzinsmodell('index', d(2024, 1, 1), None))
        # Index < 5 Jahre → Warnung
        self.assertTrue(pruefe_mietzinsmodell('index', d(2024, 1, 1), d(2027, 1, 1)))
        # Index ≥ 5 Jahre → ok
        self.assertFalse(pruefe_mietzinsmodell('index', d(2024, 1, 1), d(2029, 1, 1)))
        # Staffel < 3 Jahre → Warnung
        self.assertTrue(pruefe_mietzinsmodell('staffel', d(2024, 1, 1), d(2025, 6, 1)))
        # Staffel ≥ 3 Jahre → ok
        self.assertFalse(pruefe_mietzinsmodell('staffel', d(2024, 1, 1), d(2027, 6, 1)))
        # Fest → nie Warnung
        self.assertFalse(pruefe_mietzinsmodell('fest', d(2024, 1, 1), None))

    def test_staffel_max_eine_erhoehung_pro_jahr(self):
        from core.services.mietrecht import staffel_pruefung
        from datetime import date as d
        class S:
            def __init__(self, dt): self.ab_datum = dt
        # zwei Stufen < 1 Jahr auseinander → Warnung
        self.assertTrue(staffel_pruefung([S(d(2025, 1, 1)), S(d(2025, 8, 1))]))
        # jährlich → ok
        self.assertFalse(staffel_pruefung([S(d(2025, 1, 1)), S(d(2026, 1, 1)), S(d(2027, 1, 1))]))

    def test_kuendigungsbestaetigung_pdf_mit_zitaten(self):
        """Die Kündigungsbestätigung rendert (nutzt die Template-Tags)."""
        from rentals.models import Mietvertrag as MV, Kuendigung
        from core.services.dokument_service import generate_dokument_pdf_bytes
        lg, e, m, v = _basis_objekte()
        Kuendigung.objects.create(vertrag=v, absender='vermieter', eingang_datum=date.today(),
                                  per_datum=date.today() + timedelta(days=90),
                                  berechneter_termin=date.today() + timedelta(days=90), status='bestaetigt')
        pdf = generate_dokument_pdf_bytes(v, 'kuendigungsbestaetigung')
        self.assertTrue(pdf.startswith(b'%PDF'))


class EinstellplatzFristTests(TestCase):
    """Vertretbare Anpassung: Einstellplatz-Kündigung nach Art. 266e (2 Wochen)."""

    def _platz(self, typ='pp', monate=None):
        # Einstellplatz (pp/gar): gesetzliche 2-Wochen-Frist = monate 0; sonst 3
        if monate is None:
            monate = 0 if typ in ('pp', 'gar') else 3
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Platz 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('500000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='PP 12', typ=typ,
                                   nettomiete_aktuell=Decimal('120'))
        m = Mieter.objects.create(typ='person', nachname='Halter')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal('120'), nebenkosten=Decimal('0'),
                                       status='aktiv', kuendigungsfrist_monate=monate)
        return lg, e, m, v

    def test_termin_zwei_wochen_auf_monatsende(self):
        from rentals.services import berechne_kuendigungstermin
        _lg, _e, _m, v = self._platz('pp')
        # Eingang 5. März → +14 Tage = 19. März → nächstes Monatsende = 31. März
        t = berechne_kuendigungstermin(v, date(2025, 3, 5))
        self.assertEqual(t, date(2025, 3, 31))
        # Eingang 20. März → +14 Tage = 3. April → 30. April
        t2 = berechne_kuendigungstermin(v, date(2025, 3, 20))
        self.assertEqual(t2, date(2025, 4, 30))

    def test_anzeige_einstellplatz_vs_bastelraum(self):
        _lg, _e, _m, v = self._platz('gar')
        self.assertIn('2 Wochen', v.kuendigungsfrist_anzeige)
        self.assertIn('266e', v.kuendigungsfrist_anzeige)
        # Bastelraum ist kein Einstellplatz → Monatsanzeige
        _lg, _e, _m, vb = self._platz('bas')
        self.assertIn('Monate', vb.kuendigungsfrist_anzeige)
        self.assertNotIn('266e', vb.kuendigungsfrist_anzeige)

    def test_einstellplatz_laengere_frist(self):
        from rentals.services import berechne_kuendigungstermin
        # Vereinbarte längere Frist (1 Monat auf Monatsende) statt gesetzlicher 2 Wochen
        _lg, _e, _m, v = self._platz('pp', monate=1)
        self.assertIn('1 Monat auf Ende eines Monats', v.kuendigungsfrist_anzeige)
        # nicht mehr die 2-Wochen-Regel (Eingang 5. März → nicht 31. März)
        self.assertNotEqual(berechne_kuendigungstermin(v, date(2025, 3, 5)), date(2025, 3, 31))

    def test_wohnung_frist_unveraendert(self):
        from rentals.services import berechne_kuendigungstermin
        lg, e, m, v = _basis_objekte()   # Wohnung, 3 Monate
        t = berechne_kuendigungstermin(v, date(2025, 1, 15))
        # 3 Monate ab Januar → April-Ende (regulär), nicht 2-Wochen-Logik
        self.assertEqual(t.month, 4)


class ReferenzzinsSenkungTests(TestCase):
    """Art. 270a: sinkt der Referenzzins unter die Vertragsbasis, wird eine
    informative Pendenz (Herabsetzung möglich) angelegt."""

    def _setup(self, basis, aktuell):
        from crm.models import Organisation
        Organisation.objects.create(firma='V AG', aktueller_referenzzinssatz=Decimal(str(aktuell)))
        lg, e, m, v = _basis_objekte()
        v.basis_referenzzinssatz = Decimal(str(basis))
        v.mietzins_modell = 'fest'
        v.save()
        return v

    def test_pendenz_bei_senkung(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        v = self._setup(basis='2.00', aktuell='1.50')
        generate_auto_pendenzen(horizont_tage=90)
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='Referenzzinssenkung').first()
        self.assertIsNotNone(p)
        self.assertIn('Art. 270a', p.beschreibung)

    def test_keine_pendenz_wenn_gleich_oder_hoeher(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        v = self._setup(basis='1.50', aktuell='1.75')   # aktuell höher → kein Anspruch
        generate_auto_pendenzen(horizont_tage=90)
        self.assertFalse(Pendenz.objects.filter(vertrag=v, titel__icontains='Referenzzinssenkung').exists())

    def test_keine_pendenz_bei_indexvertrag(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        v = self._setup(basis='2.00', aktuell='1.50')
        v.mietzins_modell = 'index'; v.save()
        generate_auto_pendenzen(horizont_tage=90)
        self.assertFalse(Pendenz.objects.filter(vertrag=v, titel__icontains='Referenzzinssenkung').exists())


class Verzug257dTests(TestCase):
    """Zahlungsverzug Art. 257d: Fristansetzung erzeugt Dokument + Fristen-Pendenz,
    Live-Prüfung der Mindestfrist, Kündigungs-Prefill."""

    def _setup_offen(self):
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        heute = date.today()
        DebitorenRechnung.objects.create(
            vertrag=v, titel='Miete', datum=heute - timedelta(days=40),
            faellig_am=heute - timedelta(days=35), betrag=Decimal('1700'), status='offen')
        return lg, e, m, v

    def test_form_zeigt_offenen_betrag_und_min_frist(self):
        lg, e, m, v = self._setup_offen()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vertraege/{v.id}/verzug/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Art. 257d')
        self.assertContains(r, 'MIN_FRIST = 30')   # Wohnung → geschützt → 30 Tage

    def test_frist_ansetzen_legt_dokument_und_pendenz_an(self):
        from core.models import Pendenz, AktivitaetsLog
        from rentals.models import Dokument
        lg, e, m, v = self._setup_offen()
        c = Client(); c.force_login(_team_user())
        frist = (date.today() + timedelta(days=30)).isoformat()
        r = c.post(f'/neu/vertraege/{v.id}/verzug/', {'frist_bis': frist})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Pendenz.objects.filter(vertrag=v, titel__icontains='257d').exists())
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__icontains='257d').exists())
        self.assertTrue(AktivitaetsLog.objects.filter(aktion__icontains='257d', ziel_typ='vertrag',
                                                      ziel_id=v.id).exists())

    def test_kuendigung_prefill_bei_verzug(self):
        lg, e, m, v = self._setup_offen()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vertraege/{v.id}/kuendigen/?grund=257d')
        self.assertContains(r, 'Zahlungsverzug (Art. 257d OR)')
        # Ausserordentlicher 257d-Termin wird berechnet und angezeigt
        self.assertContains(r, 'Ausserordentlich wegen Zahlungsverzug')
        self.assertContains(r, 'Art. 257d Abs. 2 OR')

    def test_termin_257d_berechnung(self):
        from rentals.services import termin_257d
        # 10.01. + 30 Tage = 09.02. → Ende Februar
        self.assertEqual(termin_257d(date(2026, 1, 10)), date(2026, 2, 28))
        # 05.03. + 30 Tage = 04.04. → Ende April
        self.assertEqual(termin_257d(date(2026, 3, 5)), date(2026, 4, 30))

    def test_einschreiben_erfasst_provisorische_frist(self):
        """Mit Sendungsnummer + Versanddatum: Pendenz speichert die Tracking-Felder,
        faellig_am ist PROVISORISCH = Versand + Postweg(1) + 30 (strikte Empfangstheorie)."""
        from core.models import Pendenz
        lg, e, m, v = self._setup_offen()
        c = Client(); c.force_login(_team_user())
        versand = date.today() - timedelta(days=2)
        r = c.post(f'/neu/vertraege/{v.id}/verzug/', {
            'frist_bis': (date.today() + timedelta(days=40)).isoformat(),
            'sendungsnummer': '98.00.123456.00000001',
            'versand_am': versand.isoformat(),
        })
        self.assertEqual(r.status_code, 302)
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='257d').latest('id')
        self.assertEqual(p.sendungsnummer, '98.00.123456.00000001')
        self.assertEqual(p.versand_am, versand)
        self.assertEqual(p.frist_tage, 30)
        self.assertIsNone(p.zugang_am)
        # PROVISORISCH: Versand + 1 (Postweg) + 30, NICHT das Formular-frist_bis (+40).
        self.assertEqual(p.faellig_am, versand + timedelta(days=31))
        self.assertIn('PROVISORISCH', p.beschreibung)
        # Fristen-Center zeigt Track & Trace + «Zugang bestätigen» für dieses Einschreiben.
        rf = c.get('/neu/fristen/', secure=True)
        self.assertEqual(rf.status_code, 200)
        self.assertContains(rf, 'swisspost-tracking')
        self.assertContains(rf, '98.00.123456.00000001')
        self.assertContains(rf, 'Zugang bestätigen')

    def test_zugang_bestaetigen_zieht_frist_nach(self):
        """Strikte Empfangstheorie: «Zugang bestätigen» setzt zugang_am und rechnet
        faellig_am = zugang + frist_tage — unabhängig von der provisorischen Frist."""
        from core.models import Pendenz, AktivitaetsLog
        lg, e, m, v = self._setup_offen()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/verzug/', {
            'sendungsnummer': '99.11.222333.00000009',
            'versand_am': (date.today() - timedelta(days=5)).isoformat(),
        })
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='257d').latest('id')
        alt_frist = p.faellig_am
        zugang = date.today() - timedelta(days=3)
        r = c.post(f'/neu/fristen/verzug/{p.id}/zugang/', {'zugang_am': zugang.isoformat()})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.zugang_am, zugang)
        self.assertEqual(p.faellig_am, zugang + timedelta(days=30))
        self.assertNotEqual(p.faellig_am, alt_frist)
        self.assertIn('Zugang bestätigt', p.beschreibung)
        self.assertTrue(AktivitaetsLog.objects.filter(aktion__icontains='Zugang').exists())

    def test_frist_sichtbar_bei_vertrag_und_kontakt(self):
        """Die 257d-Einschreiben-Frist erscheint mit «Zugang bestätigen» sowohl auf der
        Vertrags- als auch auf der Kontakt-Detailseite (nicht nur im Fristen-Center)."""
        from core.models import Pendenz
        lg, e, m, v = self._setup_offen()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/verzug/',
               {'sendungsnummer': '98.00.123456.00000001',
                'versand_am': date.today().isoformat()}, secure=True)
        # Vertrag-Detail: Frist steht in BEIDEN Tabs (Pendenzen UND Finanzen) → 2×.
        rv = c.get(f'/neu/vertraege/{v.id}/', secure=True)
        self.assertEqual(rv.status_code, 200)
        self.assertContains(rv, 'swisspost-tracking', count=2)
        self.assertContains(rv, 'Zugang bestätigen', count=2)
        # Kontakt-Detail
        rp = c.get(f'/neu/personen/{m.id}/', secure=True)
        self.assertEqual(rp.status_code, 200)
        self.assertContains(rp, 'swisspost-tracking')
        self.assertContains(rp, 'Zugang bestätigen')

    def test_zugang_next_springt_zurueck(self):
        """«Zugang bestätigen» mit next-Param springt zur aufrufenden Seite zurück,
        ein fremdes (open-redirect) Ziel wird verworfen → Fristen-Center."""
        from core.models import Pendenz
        lg, e, m, v = self._setup_offen()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/verzug/', {'sendungsnummer': '55.00.000000.00000001'}, secure=True)
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='257d').latest('id')
        r = c.post(f'/neu/fristen/verzug/{p.id}/zugang/',
                   {'zugang_am': date.today().isoformat(), 'next': f'/neu/vertraege/{v.id}/?tab=pendenzen'}, secure=True)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], f'/neu/vertraege/{v.id}/?tab=pendenzen')
        # Open-Redirect-Versuch → ignoriert, Fallback Fristen-Center
        r2 = c.post(f'/neu/fristen/verzug/{p.id}/zugang/',
                    {'zugang_am': date.today().isoformat(), 'next': 'https://evil.example/x'}, secure=True)
        self.assertEqual(r2['Location'], '/neu/fristen/')

    def test_sendungsnummer_korrigieren(self):
        """Vertippte Sendungsnummer kann nachträglich korrigiert werden; ein neues
        Versanddatum rechnet die provisorische Frist neu (Versand+1+30)."""
        from core.models import Pendenz
        lg, e, m, v = self._setup_offen()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/verzug/',
               {'sendungsnummer': '98.00.000000.00000000',
                'versand_am': (date.today() - timedelta(days=3)).isoformat()}, secure=True)
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='257d').latest('id')
        neu_versand = date.today() - timedelta(days=1)
        r = c.post(f'/neu/fristen/verzug/{p.id}/sendung/',
                   {'sendungsnummer': '99.11.222333.44445555',
                    'versand_am': neu_versand.isoformat(),
                    'next': f'/neu/vertraege/{v.id}/?tab=finanzen'}, secure=True)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], f'/neu/vertraege/{v.id}/?tab=finanzen')
        p.refresh_from_db()
        self.assertEqual(p.sendungsnummer, '99.11.222333.44445555')
        self.assertEqual(p.versand_am, neu_versand)
        self.assertEqual(p.faellig_am, neu_versand + timedelta(days=31))
        # Fremdes Redirect-Ziel wird verworfen.
        r2 = c.post(f'/neu/fristen/verzug/{p.id}/sendung/',
                    {'sendungsnummer': '99.11.222333.44445555', 'next': 'https://evil.example/x'}, secure=True)
        self.assertEqual(r2['Location'], '/neu/fristen/')

    def test_zugang_kein_zukunftsdatum(self):
        """Ein Zugang in der Zukunft ist unmöglich → auf heute geklemmt."""
        from core.models import Pendenz
        lg, e, m, v = self._setup_offen()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/verzug/', {'sendungsnummer': '77.00.000000.00000001'})
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='257d').latest('id')
        c.post(f'/neu/fristen/verzug/{p.id}/zugang/',
               {'zugang_am': (date.today() + timedelta(days=10)).isoformat()})
        p.refresh_from_db()
        self.assertEqual(p.zugang_am, date.today())
        self.assertEqual(p.faellig_am, date.today() + timedelta(days=30))


class AnfechtungsfristTests(TestCase):
    """Anfechtungsfristen als Pendenz: Vermieterkündigung (Art. 271/273) und
    Mietzinserhöhung (Art. 270b) — je 30 Tage."""

    def test_vermieterkuendigung_legt_anfechtungsfrist_an(self):
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()   # Wohnung → geschützt
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/kuendigen/',
               {'absender': 'vermieter', 'eingang_datum': date.today().isoformat(), 'bestaetigen': 'on'})
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='Anfechtungsfrist Kündigung').first()
        self.assertIsNotNone(p)
        self.assertIn('Art. 271', p.beschreibung)
        self.assertEqual(p.faellig_am, date.today() + timedelta(days=30))

    def test_mieterkuendigung_ohne_anfechtungsfrist(self):
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/kuendigen/',
               {'absender': 'mieter', 'eingang_datum': date.today().isoformat(), 'bestaetigen': 'on'})
        self.assertFalse(Pendenz.objects.filter(vertrag=v, titel__icontains='Anfechtungsfrist').exists())

    def test_mietzinserhoehung_legt_anfechtungsfrist_an(self):
        from crm.models import Organisation
        from core.models import Pendenz
        Organisation.objects.create(firma='V AG', aktueller_referenzzinssatz=Decimal('1.50'))
        lg, e, m, v = _basis_objekte()   # netto 1500
        v.basis_referenzzinssatz = Decimal('1.75'); v.basis_lik_punkte = Decimal('100'); v.save()
        from rentals.services import naechster_anpassungstermin
        wirksam = naechster_anpassungstermin(v, date.today())  # frühester gültiger Termin (269d inkl. Zustellpuffer)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mietzins/{v.id}/anpassung/', {
            'aktion': 'speichern', 'neu_netto': '1600', 'neu_zins': '1.50', 'neu_lik': '100',
            'basis_zins': '1.75', 'basis_lik': '100', 'kosten_pct': '0',
            'wirksam_ab': wirksam.isoformat(),
        })
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='Anfechtungsfrist Mietzins').first()
        self.assertIsNotNone(p)
        self.assertIn('Art. 270b', p.beschreibung)


class RechtsgrundlagenTests(TestCase):
    """In-App-Übersicht der angewandten Rechtsgrundlagen."""

    def test_seite_rendert_artikel(self):
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/rechtsgrundlagen/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Rechtsgrundlagen')
        self.assertContains(r, 'Art. 257d OR')     # Verzug
        self.assertContains(r, 'Art. 269d OR')     # Mietzinserhöhung
        self.assertContains(r, 'Obligationenrecht')
        self.assertContains(r, 'fedlex.admin.ch')  # amtliche Quelle

    def test_suche(self):
        from core.services import gesetzestexte
        # Stichwort
        rows = gesetzestexte.suche('kaution')
        self.assertTrue(any(r['art'] == '257e' for r in rows))
        # Artikelnummer
        rows = gesetzestexte.suche('269c')
        self.assertTrue(any('staffel' in ' '.join(r['stichworte']) for r in rows))
        # Mehrwortsuche
        self.assertTrue(gesetzestexte.suche('referenzzins senkung'))
        # leere Query → alle
        self.assertEqual(len(gesetzestexte.suche('')), len(gesetzestexte.REGISTER))

    def test_suche_view(self):
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/rechtsgrundlagen/?q=kaution')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Art. 257e OR')
        self.assertNotContains(r, 'Art. 266d OR')   # Geschäftsraum-Frist – nicht Treffer

    def test_anwendung_overlay(self):
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/rechtsgrundlagen/?q=257d')
        self.assertContains(r, 'In swissImmo')      # Anwendungshinweis am Artikel


class KautionFreigabeTests(TestCase):
    """Art. 257e Abs. 3: nach 1 Jahr seit Mietende ohne Ansprüche → Freigabe-Pendenz."""

    def test_pendenz_nach_einem_jahr(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        v.ende = date.today() - timedelta(days=366)
        v.status = 'beendet'; v.save()
        generate_auto_pendenzen(horizont_tage=90)
        p = Pendenz.objects.filter(vertrag=v, quelle__startswith='auto:kautionfreigabe').first()
        self.assertIsNotNone(p)
        self.assertIn('Art. 257e Abs. 3', p.beschreibung)
        self.assertEqual(p.kategorie, 'frist')

    def test_keine_pendenz_wenn_zurueckbezahlt(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        v.ende = date.today() - timedelta(days=366)
        v.kautions_zurueckbezahlt_am = date.today(); v.save()
        generate_auto_pendenzen(horizont_tage=90)
        self.assertFalse(Pendenz.objects.filter(quelle__startswith='auto:kautionfreigabe').exists())

    def test_keine_pendenz_bei_versicherung(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        v.ende = date.today() - timedelta(days=366)
        v.kautions_art = 'versicherung'; v.save()
        generate_auto_pendenzen(horizont_tage=90)
        self.assertFalse(Pendenz.objects.filter(quelle__startswith='auto:kautionfreigabe').exists())


class LegalBatchTests(TestCase):
    """ZH-Amtsformulare kreuzen die Objekt-Art datengetrieben; 269d-Frist serverseitig."""

    def test_zh_formulare_objektart_datengetrieben(self):
        src = open('core/services/formular_fill.py', encoding='utf-8').read()
        # Mietzins-Formular: Wohnung(1)/Geschäftsräume(2) aus mietrecht_kategorie
        self.assertRegex(src, r"obj_cb\s*=\s*'Kontrollkästchen 1'\s+if\s+vertrag\.mietrecht_kategorie\s*==\s*'wohnen'\s+else\s+'Kontrollkästchen 2'")
        # Kündigungs-Formular: Wohnung(6)/Geschäftsräume(7)
        self.assertRegex(src, r"obj_cb\s*=\s*'Kontrollkästchen 6'\s+if\s+vertrag\.mietrecht_kategorie\s*==\s*'wohnen'\s+else\s+'Kontrollkästchen 7'")
        self.assertNotRegex(src, r"cbs = \['Kontrollkästchen 1', 'Kontrollkästchen 3'\]")

    def test_269d_zu_fruehes_datum_wird_abgelehnt(self):
        from rentals.models import MietzinsAnpassung
        lg, e, m, v = _basis_objekte()
        v.basis_referenzzinssatz = Decimal('1.25'); v.basis_lik_punkte = Decimal('100.0')
        v.kuendigungsfrist_monate = 3; v.save()
        c = Client(); c.force_login(_team_user())
        # Erhöhung mit Wirksamkeit morgen — deutlich vor dem nächsten Termin.
        r = c.post(f'/neu/mietzins/{v.id}/anpassung/', {
            'aktion': 'speichern', 'neu_netto': '1600', 'neu_zins': '1.50',
            'neu_lik': '105.0', 'wirksam_ab': (date.today() + timedelta(days=1)).isoformat(),
            'begruendung': 'Referenzzins', 'formular': 'generisch'})
        self.assertEqual(r.status_code, 302)
        # Kein Datensatz angelegt — die Frist wurde serverseitig durchgesetzt.
        self.assertEqual(MietzinsAnpassung.objects.filter(vertrag=v).count(), 0)


class Art266nDoppelzustellungTests(TestCase):
    """Art. 266n OR: Vermieter-Kündigung einer Familienwohnung → je Ehegatte eine
    separat adressierte Kopie (sonst nichtig)."""

    def _familienvertrag(self):
        from crm.models import Mieter
        lg, e, m, v = _basis_objekte()
        gatte = Mieter.objects.create(typ='person', vorname='Petra', nachname='Muster',
                                      email='petra@example.ch', strasse='Seeweg 3', plz='8000', ort='Zürich')
        v.familienwohnung = True; v.mitmieter = gatte; v.save()
        return lg, e, m, v, gatte

    def test_vermieter_familienwohnung_zwei_kopien(self):
        from core.services.formular_fill import kuendigung_zustellkopien
        from rentals.models import Kuendigung
        _lg, _e, _m, v, gatte = self._familienvertrag()
        k = Kuendigung.objects.create(vertrag=v, absender='vermieter', per_datum=date(2027, 3, 31))
        kopien = kuendigung_zustellkopien(v, k)
        self.assertEqual(len(kopien), 2)
        namen = {n for n, _ in kopien}
        self.assertIn('Hans Muster', namen)
        self.assertIn(gatte.display_name, namen)
        for _n, pdf in kopien:
            self.assertTrue(pdf.startswith(b'%PDF'))

    def test_mieterkuendigung_nur_eine_kopie(self):
        from core.services.formular_fill import kuendigung_zustellkopien
        from rentals.models import Kuendigung
        _lg, _e, _m, v, _g = self._familienvertrag()
        k = Kuendigung.objects.create(vertrag=v, absender='mieter', per_datum=date(2027, 3, 31))
        # Nur die Vermieter-Kündigung braucht die getrennte Zustellung.
        self.assertEqual(len(kuendigung_zustellkopien(v, k)), 1)

    def test_keine_familienwohnung_eine_kopie(self):
        from core.services.formular_fill import kuendigung_zustellkopien
        from rentals.models import Kuendigung
        lg, e, m, v = _basis_objekte()   # familienwohnung=False
        k = Kuendigung.objects.create(vertrag=v, absender='vermieter', per_datum=date(2027, 3, 31))
        self.assertEqual(len(kuendigung_zustellkopien(v, k)), 1)

    def test_view_liefert_pdf_und_legt_zwei_kopien_ab(self):
        from rentals.models import Kuendigung
        from rentals.models import Dokument
        _lg, _e, _m, v, _g = self._familienvertrag()
        k = Kuendigung.objects.create(vertrag=v, absender='vermieter', per_datum=date(2027, 3, 31))
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/kuendigung/{k.id}/formular/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        # Zwei separat adressierte Kopien abgelegt.
        n = Dokument.objects.filter(vertrag=v, bezeichnung__contains='Zustellung an').count()
        self.assertEqual(n, 2)


class Art270AnfangsmietzinsTests(TestCase):
    """Art. 270 OR: Anfangsmietzins-Formular mit Vormiete + Anfechtungshinweis."""

    def test_pdf_generierung(self):
        from core.services.amtliche_formulare_so import anfangsmietzins_so_pdf
        _lg, _e, _m, v = _basis_objekte()
        daten = {'anfang_netto': Decimal('1500'), 'anfang_nk': Decimal('200'),
                 'vormiete_netto': Decimal('1350'), 'vormiete_nk': Decimal('180'),
                 'beginn': date(2026, 1, 1), 'grund_choice': 'referenz', 'begruendung': ''}
        pdf = anfangsmietzins_so_pdf(v, daten)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 1500)

    def test_view_get_und_post(self):
        from rentals.models import Dokument
        _lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        # GET zeigt das Formular
        g = c.get(f'/neu/mietzins/{v.id}/anfangsmietzins/')
        self.assertEqual(g.status_code, 200)
        self.assertIn('Anfangsmietzins', g.content.decode())
        # POST erzeugt das PDF + legt es ab
        p = c.post(f'/neu/mietzins/{v.id}/anfangsmietzins/', {
            'anfang_netto': '1500', 'anfang_nk': '200',
            'vormiete_netto': '1350', 'vormiete_nk': '180', 'grund_choice': 'referenz'})
        self.assertEqual(p.status_code, 200)
        self.assertEqual(p['Content-Type'], 'application/pdf')
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Anfangsmietzins').exists())


class FormularpflichtTests(TestCase):
    """Verzeichnis der Formularpflicht (Art. 270 Abs. 2 OR) — inkl. Kanton Bern."""

    def test_bern_hat_formularpflicht(self):
        from core.services.formularpflicht import formularpflicht_fuer_kanton
        p, info = formularpflicht_fuer_kanton('BE')
        self.assertEqual(p, 'ja')
        self.assertIn('135a', info['gesetz'])
        self.assertEqual(info['kanton_name'], 'Bern')

    def test_wallis_keine_pflicht_und_unbekannt(self):
        from core.services.formularpflicht import formularpflicht_fuer_kanton
        self.assertEqual(formularpflicht_fuer_kanton('VS')[0], 'nein')
        self.assertEqual(formularpflicht_fuer_kanton('XX')[0], 'unbekannt')

    def test_bern_pdf_zeigt_pflicht_grundlage(self):
        from core.services.amtliche_formulare_so import anfangsmietzins_so_pdf
        from core.services.formularpflicht import formularpflicht_fuer_kanton
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        _p, info = formularpflicht_fuer_kanton('BE')
        daten = {'anfang_netto': Decimal('1500'), 'anfang_nk': Decimal('200'),
                 'vormiete_netto': Decimal('1350'), 'vormiete_nk': Decimal('180'),
                 'beginn': date(2026, 1, 1), 'grund_choice': 'referenz',
                 'begruendung': '', 'pflicht_info': info}
        pdf = anfangsmietzins_so_pdf(v, daten)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 1500)

    def test_view_zeigt_pflicht_banner_bern(self):
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        c = Client(); c.force_login(_team_user())
        g = c.get(f'/neu/mietzins/{v.id}/anfangsmietzins/')
        self.assertEqual(g.status_code, 200)
        self.assertIn('Formularpflicht', g.content.decode())
        self.assertIn('Bern', g.content.decode())

    def test_auto_ablage_bei_pflicht_wohnraum(self):
        from core.views.fw import anfangsmietzins_auto_ablegen
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        erzeugt, pflicht = anfangsmietzins_auto_ablegen(v)
        self.assertTrue(erzeugt)
        self.assertEqual(pflicht, 'ja')
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Anfangsmietzins').exists())

    def test_kein_auto_ohne_pflicht(self):
        from core.views.fw import anfangsmietzins_auto_ablegen
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'VS'; lg.plz = '1950'; lg.ort = 'Sion'; lg.save()  # keine Formularpflicht
        erzeugt, grund = anfangsmietzins_auto_ablegen(v)
        self.assertFalse(erzeugt)
        self.assertEqual(grund, 'keine_pflicht')
        self.assertFalse(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Anfangsmietzins').exists())

    def test_kein_auto_bei_gewerbe(self):
        from core.views.fw import anfangsmietzins_auto_ablegen
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        e.typ = 'gew'; e.save()   # Gewerbe → mietrecht_kategorie 'gewerbe'
        erzeugt, grund = anfangsmietzins_auto_ablegen(v)
        self.assertFalse(erzeugt)
        self.assertEqual(grund, 'kein_wohnraum')

    def test_anfangsmiete_aus_sollmietzins_vorbefuellt(self):
        from portfolio.models import Sollmietzins
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        # datierte Sollmietzins-Zeile gültig ab Vertragsbeginn mit abweichendem Wert
        Sollmietzins.objects.create(einheit=e, gueltig_ab=v.beginn,
                                    netto_mietzins=Decimal('1777'), nebenkosten=Decimal('222'))
        c = Client(); c.force_login(_team_user())
        g = c.get(f'/neu/mietzins/{v.id}/anfangsmietzins/')
        self.assertEqual(g.status_code, 200)
        html = g.content.decode()
        self.assertIn('1777', html)   # aus Sollmietzins, nicht 1500 vom Vertrag
        self.assertIn('gültig ab', html)

    def test_dispatcher_faellt_auf_reportlab_zurueck(self):
        from core.services.formular_fill import fill_anfangsmietzins, hat_original
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'ZH'; lg.plz = '8000'; lg.ort = 'Zürich'; lg.save()
        self.assertFalse(hat_original('ZH', 'anfangsmietzins'))  # ZH: kein Original → Fallback
        daten = {'anfang_netto': Decimal('1500'), 'anfang_nk': Decimal('200'),
                 'vormiete_netto': Decimal('0'), 'vormiete_nk': Decimal('0'),
                 'beginn': v.beginn, 'grund_choice': 'referenz', 'begruendung': ''}
        pdf = fill_anfangsmietzins(v, daten)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_bern_nutzt_original_acroform(self):
        from core.services.formular_fill import fill_anfangsmietzins, hat_original
        from pypdf import PdfReader
        import io
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        self.assertTrue(hat_original('BE', 'anfangsmietzins'))  # Original hinterlegt
        daten = {'anfang_netto': Decimal('1650'), 'anfang_nk': Decimal('250'),
                 'vormiete_netto': Decimal('1500'), 'vormiete_nk': Decimal('230'),
                 'beginn': v.beginn, 'grund_choice': 'anpassung', 'begruendung': 'Referenzzins',
                 'basis_ref': Decimal('1.75'), 'basis_lik': Decimal('107.1'),
                 'basis_lik_basis': 'Dezember 2020'}
        pdf = fill_anfangsmietzins(v, daten, kanton='BE')
        self.assertTrue(pdf.startswith(b'%PDF'))
        # Es ist das amtliche Original (AcroForm mit den Textfeld-Namen), gefüllt.
        flds = PdfReader(io.BytesIO(pdf)).get_fields() or {}
        self.assertIn('Textfeld 16', flds)                       # Feldname aus dem Original
        self.assertEqual(flds['Textfeld 5'].get('/V'), f"{m.vorname} {m.nachname}")
        self.assertEqual(flds['Textfeld 16'].get('/V'), "1'650.00")   # Anfangsmiete netto
        # Berechnungsgrundlagen (Referenzzinssatz / LIK / Basis)
        self.assertEqual(flds['Textfeld 21'].get('/V'), '1.75')
        self.assertEqual(flds['Textfeld 22'].get('/V'), '107.1')
        self.assertEqual(flds['Textfeld 22a'].get('/V'), 'Dez. 2020')   # gekürzt (schmales Feld)

    def test_view_fuellt_berechnungsgrundlagen(self):
        # Der View muss Referenzzinssatz/LIK aus dem Vertrag in die daten geben.
        lg, e, m, v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        v.basis_referenzzinssatz = Decimal('1.75'); v.basis_lik_punkte = Decimal('107.1'); v.save()
        c = Client(); c.force_login(_team_user())
        g = c.get(f'/neu/mietzins/{v.id}/anfangsmietzins/')
        self.assertEqual(g.status_code, 200)
        html = g.content.decode()
        self.assertIn('Berechnungsgrundlagen', html)
        self.assertIn('1.75', html)
        self.assertIn('107.1', html)

    def test_aktivierung_erzeugt_formular_automatisch(self):
        from rentals.models import Dokument
        lg, e, m, _v = _basis_objekte()
        lg.kanton = 'BE'; lg.plz = '3000'; lg.ort = 'Bern'; lg.save()
        # frisches Objekt ohne bestehenden Vertrag für saubere Aktivierung
        e2 = Einheit.objects.create(liegenschaft=lg, bezeichnung='2.5 Zi', typ='wohnung',
                                    nettomiete_aktuell=Decimal('1400'), nebenkosten_aktuell=Decimal('180'))
        c = Client(); c.force_login(_team_user())
        beginn = date.today().replace(day=1)
        r = c.post('/neu/vertraege/neu/speichern/', {
            'mieter_id': str(m.id), 'einheit_id': str(e2.id),
            'beginn': beginn.isoformat(), 'netto_mietzins': '1400', 'nebenkosten': '180',
            'mietzins_modell': 'fest', 'kautions_betrag': '4200', 'aktiv_setzen': 'on',
        })
        self.assertIn(r.status_code, (200, 302))
        v = Mietvertrag.objects.filter(einheit=e2).latest('id')
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Anfangsmietzins').exists())


class SchlichtungRegisterTests(TestCase):
    """Schlichtungsbehörden-Register: SO/BE/ZH exakt, sonst ehrlicher Fallback."""

    class _LG:
        def __init__(self, kanton, plz, ort):
            self.kanton, self.plz, self.ort = kanton, plz, ort

    def test_bern_vier_regionen_exakt(self):
        from core.services.kantone import schlichtung_block
        kt, name, beh, exakt = schlichtung_block(self._LG('BE', '3011', 'Bern'))
        self.assertEqual(kt, 'BE')
        self.assertTrue(exakt)
        self.assertEqual(len(beh), 4)
        self.assertIn('Bern-Mittelland', beh[0][0])

    def test_zuerich_stadt_exakt(self):
        from core.services.kantone import schlichtung_block
        _kt, _name, beh, exakt = schlichtung_block(self._LG('ZH', '8004', 'Zürich'))
        self.assertTrue(exakt)
        self.assertIn('Zürich', beh[0][1])

    def test_zuerich_unbekannte_plz_faellt_auf_generisch(self):
        from core.services.kantone import schlichtung_block
        _kt, _name, _beh, exakt = schlichtung_block(self._LG('ZH', '8620', 'Wetzikon'))
        self.assertFalse(exakt)

    def test_nicht_hinterlegter_kanton_generisch(self):
        from core.services.kantone import schlichtung_block
        _kt, name, beh, exakt = schlichtung_block(self._LG('AG', '5000', 'Aarau'))
        self.assertFalse(exakt)
        self.assertIn('Aargau', beh[0][0])


class IndexMitteilungTests(TestCase):
    """Index-Mitteilung (Art. 269b/269d): Anpassungsvorschlag aus LIK-Entwicklung."""

    def _index_vertrag(self):
        lg, e, m, v = _basis_objekte()
        v.mietzins_modell = 'index'
        v.basis_lik_punkte = Decimal('100.0')
        v.index_weitergabe_prozent = Decimal('100.0')
        v.netto_mietzins = Decimal('1000.00')
        v.ist_befristet = True
        v.ende = date(2030, 1, 1)
        v.save()
        return v

    def test_vorschlag_steigt_mit_lik(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        v = self._index_vertrag()
        r = index_anpassung_vorschlag(v, aktuell_lik=Decimal('105.0'))
        self.assertIsNotNone(r)
        self.assertEqual(r['neu_netto'], Decimal('1050.00'))   # +5%
        self.assertEqual(r['delta_prozent'], Decimal('5.00'))
        self.assertIn('Art. 269b', r['begruendung'])

    def test_teilweise_weitergabe(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        v = self._index_vertrag()
        v.index_weitergabe_prozent = Decimal('80.0'); v.save()
        r = index_anpassung_vorschlag(v, aktuell_lik=Decimal('110.0'))
        # +10% LIK × 80% Weitergabe = +8%
        self.assertEqual(r['neu_netto'], Decimal('1080.00'))

    def test_kein_vorschlag_wenn_lik_nicht_gestiegen(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        v = self._index_vertrag()
        self.assertIsNone(index_anpassung_vorschlag(v, aktuell_lik=Decimal('100.0')))
        self.assertIsNone(index_anpassung_vorschlag(v, aktuell_lik=Decimal('95.0')))

    def test_kein_vorschlag_fuer_festmiete(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        _lg, _e, _m, v = _basis_objekte()  # mietzins_modell default 'fest'
        self.assertIsNone(index_anpassung_vorschlag(v, aktuell_lik=Decimal('110.0')))

    def test_anpassung_view_zeigt_index_banner(self):
        from crm.models import Organisation
        Organisation.objects.create(firma='V AG', aktueller_referenzzinssatz=Decimal('1.50'),
                                  aktueller_lik_punkte=Decimal('106.0'))
        v = self._index_vertrag()
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.get(f'/neu/mietzins/{v.id}/anpassung/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.context.get('index_vorschlag'))
        self.assertIn('Indexmiete (Art. 269b OR)', r.content.decode())


class NachtN2JuristTests(TestCase):
    """Nacht-Audit N2: 257d-Doppelzustellung (266n), Rückgabe-Mängelrüge 267a,
    Verjährungsüberwachung (Art. 128 Ziff. 1)."""

    def test_257d_doppelzustellung_familienwohnung(self):
        from finance.models import DebitorenRechnung
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()
        v.familienwohnung = True; v.mitmieter_name = 'Erika Muster'; v.save()
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete',
                                         betrag=Decimal('1500'),
                                         datum=date.today() - timedelta(days=40),
                                         faellig_am=date.today() - timedelta(days=35), status='offen')
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post(f'/neu/vertraege/{v.id}/verzug/', {'frist_bis': (date.today() + timedelta(days=40)).isoformat()})
        self.assertEqual(r.status_code, 302)
        # Neu: je Empfänger ein separat adressiertes 257d-Schreiben (statt eines
        # Sammel-Dokuments «2 Zustellungen») — direkter Nachweis der Doppelzustellung.
        doks = Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Zahlungsaufforderung 257d')
        self.assertEqual(doks.count(), 2)                  # Mieter + Ehegatte separat (Art. 266n)
        _namen = ' | '.join(d.bezeichnung for d in doks)
        self.assertIn('Hans Muster', _namen)               # Mieter
        self.assertIn('Erika Muster', _namen)              # Ehegatte separat

    def test_257d_einzelzustellung_ohne_familienwohnung(self):
        from finance.models import DebitorenRechnung
        from rentals.models import Dokument
        lg, e, m, v = _basis_objekte()   # keine Familienwohnung, kein Mitmieter
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete',
                                         betrag=Decimal('1500'),
                                         datum=date.today() - timedelta(days=40),
                                         faellig_am=date.today() - timedelta(days=35), status='offen')
        u = _team_user(); c = Client(); c.force_login(u)
        c.post(f'/neu/vertraege/{v.id}/verzug/', {'frist_bis': (date.today() + timedelta(days=40)).isoformat()})
        dok = Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Zahlungsaufforderung 257d').first()
        self.assertIsNotNone(dok)
        self.assertNotIn('Zustellungen', dok.bezeichnung)

    def test_auszugscheckliste_enthaelt_267a_pendenz(self):
        from core.views.fw import _auszugscheckliste_anlegen
        from core.models import Pendenz
        _lg, _e, _m, v = _basis_objekte()
        per = date.today() + timedelta(days=60)
        _auszugscheckliste_anlegen(v, None, per, None)
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='267a').first()
        self.assertIsNotNone(p)
        self.assertEqual(p.faellig_am, per + timedelta(days=2))   # sofort nach Abnahme
        self.assertEqual(p.kategorie, 'frist')

    def test_rueckgabe_ruege_pdf_und_view(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel, Dokument
        _lg, _e, _m, v = _basis_objekte()
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        AbnahmeMangel.objects.create(protokoll=prot, raum='Küche', beschreibung='Kochfeld gesprungen',
                                     verursacher='mieter', kostenschaetzung=Decimal('400'))
        AbnahmeMangel.objects.create(protokoll=prot, raum='Bad', beschreibung='Normale Abnutzung',
                                     verursacher='abnutzung')
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post(f'/neu/abnahme/{prot.id}/ruege-267a/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertTrue(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Mängelrüge Art. 267a').exists())

    def test_rueckgabe_ruege_ohne_mieter_maengel(self):
        from rentals.models import Abnahmeprotokoll
        _lg, _e, _m, v = _basis_objekte()
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        u = _team_user(); c = Client(); c.force_login(u)
        r = c.post(f'/neu/abnahme/{prot.id}/ruege-267a/')
        self.assertEqual(r.status_code, 302)   # kein PDF, Redirect mit Hinweis

    def test_verjaehrungs_pendenz_und_mahnlauf_skip(self):
        from core.services.automation import generate_auto_pendenzen, run_mahnlauf
        from finance.models import DebitorenRechnung
        from core.models import Pendenz
        lg, e, m, v = _basis_objekte()
        alt = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete Uralt', betrag=Decimal('1000'),
            datum=date.today() - timedelta(days=1700),
            faellig_am=date.today() - timedelta(days=1700), status='offen')  # ~4.7 Jahre
        generate_auto_pendenzen()
        p = Pendenz.objects.filter(quelle=f'auto:verjaehrung:{alt.id}').first()
        self.assertIsNotNone(p)
        self.assertIn('Art. 128', p.beschreibung)
        # Verjährte Forderung (> 5 J) wird im Mahnlauf übersprungen
        alt.faellig_am = date.today() - timedelta(days=5 * 365 + 10)
        alt.save(update_fields=['faellig_am'])
        res = run_mahnlauf(send_email=False)
        self.assertEqual(alt.mahnungen.count(), 0)


class RechtstexteITests(TestCase):
    """Live-Test I: Korrektheit der Rechtstexte/-verweise."""

    def _text(self, pdf):
        import io
        from pdfminer.high_level import extract_text
        return extract_text(io.BytesIO(pdf))

    def test_i_bern_formularpflicht_zitiert_eg_zgb(self):
        from core.services.formularpflicht import _REGISTER
        g = _REGISTER['BE']['gesetz']
        self.assertIn('EG ZGB', g)
        self.assertNotIn('Kantonsverfassung', g)

    def test_i_mietzinsanpassung_wirksam_ab_monatserster(self):
        from rentals.services import naechster_anpassungstermin, berechne_kuendigungstermin
        import datetime as _dt
        lg, e, m, v = _basis_objekte()
        termin = naechster_anpassungstermin(v, date(2026, 1, 15))
        self.assertEqual(termin.day, 1, 'Anpassung nicht auf Monatserster')
        # Es ist der Tag NACH dem ordentlichen Kündigungstermin (Monatsende).
        roh = berechne_kuendigungstermin(v, date(2026, 1, 15) + _dt.timedelta(days=17))
        self.assertEqual(termin, roh + _dt.timedelta(days=1))

    def test_i_anpassungstermin_immer_monatserster_auch_bei_mittemonat(self):
        # Robustheit: liegt der frühestmögliche Termin via erstmals_kuendbar_auf
        # ausnahmsweise mitten im Monat, muss die Anpassung trotzdem auf den
        # Monatsersten fallen (nicht Mitte-Monat + 1 Tag). Review-Härtung.
        from rentals.services import naechster_anpassungstermin
        lg, e, m, v = _basis_objekte()
        v.erstmals_kuendbar_auf = date(2030, 6, 15); v.save()   # Nicht-Monatsende
        termin = naechster_anpassungstermin(v, date(2030, 1, 1))
        self.assertEqual(termin.day, 1)
        self.assertEqual(termin, date(2030, 7, 1))

    def test_i_257d_frist_mindestens_30_tage_geschuetzt(self):
        from finance.booking import ensure_kontenplan
        from finance.models import DebitorenRechnung
        from core.models import Pendenz
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()   # Wohnung → geschützt
        self.assertTrue(v.ist_geschuetzt)
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
            titel='Miete', datum=date(2024, 1, 1), faellig_am=date(2024, 1, 5),
            betrag=Decimal('1500'), status='offen')
        c = Client(); c.force_login(_team_user('Verwaltung'))
        heute = date.today()
        # Zu kurze Frist (5 Tage) einreichen → Server erzwingt ≥ 30 Tage
        c.post(f'/neu/vertraege/{v.id}/verzug/',
               {'frist_bis': (heute + timedelta(days=5)).isoformat()})
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='257d').first()
        self.assertIsNotNone(p)
        self.assertGreaterEqual((p.faellig_am - heute).days, 30)

    def test_i_maengelruege_zitiert_257f_nicht_259(self):
        from core.services.mietprozess_briefe import maengelruege_pdf
        lg, e, m, v = _basis_objekte()
        pdf = maengelruege_pdf(v, "Beschädigte Küchenfront durch unsachgemässen Gebrauch.")
        txt = self._text(pdf)
        self.assertIn('257f', txt)
        self.assertNotIn('259', txt)

    def test_i_257d_brief_hat_nur_eine_grussformel(self):
        from finance.booking import ensure_kontenplan
        from finance.models import DebitorenRechnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
            titel='Miete', datum=date(2024, 1, 1), faellig_am=date(2024, 1, 5),
            betrag=Decimal('1500'), status='offen')
        c = Client(); c.force_login(_team_user('Verwaltung'))
        heute = date.today()
        r = c.post(f'/neu/vertraege/{v.id}/verzug/',
                   {'frist_bis': (heute + timedelta(days=40)).isoformat(), 'als_pdf': '1'})
        self.assertEqual(r['Content-Type'], 'application/pdf')
        txt = self._text(r.content)
        self.assertEqual(txt.count('Freundliche Grüsse'), 1, 'Grussformel doppelt/fehlend')


class KuendigungSchlussabrechnungQSTests(TestCase):
    """QS Kündigung/Schlussabrechnung: Anzeige-Kaution = Buchung; befristetes Ende
    überlebt Kündigung + Rücknahme."""

    def test_schlussabrechnung_gutschrift_hoechstens_bilanziert(self):
        # Anzeige/PDF dürfen nur die BILANZIERTE Kaution gutschreiben, nicht die
        # nominale — sonst verspricht das PDF mehr Rückzahlung als gebucht wird.
        from core.services.schlussabrechnung import berechne_schlussabrechnung
        lg, e, m, v = _basis_objekte()
        v.kautions_betrag = Decimal('3000'); v.kautions_art = 'sperrkonto'; v.save()
        # Nur CHF 2000 tatsächlich bilanziert
        daten = berechne_schlussabrechnung(v, date(2024, 6, 30), [],
                                           kaution_verrechnen=True, kaution_bilanziert=Decimal('2000'))
        self.assertEqual(daten['kaution'], Decimal('2000'))
        self.assertEqual(daten['rueckzahlung'], Decimal('2000.00'))   # nicht 3000
        # Ohne den Parameter (Alt-Verhalten) bliebe es beim vereinbarten Betrag:
        alt = berechne_schlussabrechnung(v, date(2024, 6, 30), [], kaution_verrechnen=True)
        self.assertEqual(alt['kaution'], Decimal('3000'))

    def test_befristetes_ende_ueberlebt_ausserordentliche_kuendigung_und_ruecknahme(self):
        from rentals.models import Kuendigung
        lg, e, m, v = _basis_objekte()
        v.ist_befristet = True; v.ende = date(2030, 12, 31); v.save()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        # Ausserordentliche Kündigung per 30.09.2026 → Vertrag endet früher
        c.post(f'/neu/vertraege/{v.id}/kuendigen/',
               {'eingang_datum': '2026-06-01', 'ausserordentlich': 'on',
                'gewuenschtes_ende': '2026-09-30', 'bestaetigen': 'on'})
        v.refresh_from_db()
        self.assertEqual(v.ende, date(2026, 9, 30))
        self.assertEqual(v.status, 'gekuendigt')
        k = Kuendigung.objects.filter(vertrag=v).latest('id')
        self.assertEqual(k.ende_vorher, date(2030, 12, 31))   # Snapshot
        # Rücknahme → ursprüngliche Laufzeit wieder da
        c.post(f'/neu/kuendigung/{k.id}/zuruecknehmen/', {})
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')
        self.assertEqual(v.ende, date(2030, 12, 31))          # nicht 2026-09-30, nicht None
