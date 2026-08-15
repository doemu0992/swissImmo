"""Testmodul mietprozess — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 11 Klassen, unveraendert uebernommen."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (
    _team_user, _basis_objekte, _seed_konten, _heute, Mieter, Organisation,
    Liegenschaft, Einheit, Mietvertrag)



class MieterwechselCockpitTests(TestCase):
    def _kuendigung(self, tage_bis_ende=40):
        from rentals.models import Kuendigung
        lg, e, m, v = _basis_objekte()
        ende = date.today() + timedelta(days=tage_bis_ende)
        k = Kuendigung.objects.create(vertrag=v, absender='mieter', eingang_datum=date.today(),
                                      per_datum=ende, berechneter_termin=ende, status='erfasst')
        return lg, e, m, v, k, ende

    def test_gekuendigt_erscheint(self):
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.get('/neu/mieterwechsel/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Teststrasse 1')
        self.assertContains(r, 'Gekündigt')

    def test_nachmietervertrag_erkannt(self):
        lg, e, m, v, k, ende = self._kuendigung()
        # Nachmieter-Vertrag auf derselben Einheit ab Ende
        nm = Mieter.objects.create(typ='person', nachname='Neu')
        Mietvertrag.objects.create(mieter=nm, einheit=e, beginn=ende + timedelta(days=1),
                                   netto_mietzins=Decimal('1600'), nebenkosten=Decimal('200'), status='entwurf')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('Nachmieter-Vertrag', body)
        self.assertIn('Neu', body)

    def test_vollzogene_kuendigung_nicht_gelistet(self):
        lg, e, m, v, k, ende = self._kuendigung()
        k.status = 'vollzogen'; k.save()
        team = _team_user()
        c = Client(); c.force_login(team)
        self.assertContains(c.get('/neu/mieterwechsel/'), 'Kein laufender Mieterwechsel')

    def test_ruecknahme_aktion_verlinkt_vorgetypt(self):
        """Cockpit verlinkt die Rücknahme direkt auf den vorgetypten Abnahme-Flow."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug', body)
        self.assertIn('Rücknahme starten', body)

    def test_uebergabe_aktion_bei_nachmieter(self):
        """Sobald ein Nachmietervertrag existiert, verlinkt das Cockpit die Übergabe."""
        lg, e, m, v, k, ende = self._kuendigung()
        nm = Mieter.objects.create(typ='person', nachname='Neu')
        nv = Mietvertrag.objects.create(mieter=nm, einheit=e, beginn=ende + timedelta(days=1),
                                        netto_mietzins=Decimal('1600'), nebenkosten=Decimal('200'),
                                        status='entwurf')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn(f'/neu/vertraege/{nv.id}/abnahme/neu/?typ=einzug', body)
        self.assertIn('Übergabe starten', body)

    def test_abnahme_form_uebernimmt_typ_aus_query(self):
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug').content.decode()
        self.assertIn('<option value="auszug" selected>', body)

    def test_auto_pendenz_ruecknahme(self):
        """generate_auto_pendenzen legt eine Wohnungsrücknahme-Pendenz je Kündigung an."""
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        lg, e, m, v, k, ende = self._kuendigung(tage_bis_ende=40)
        generate_auto_pendenzen(horizont_tage=90)
        p = Pendenz.objects.filter(quelle=f'auto:ruecknahme:{k.id}').first()
        self.assertIsNotNone(p)
        self.assertIn('Wohnungsrücknahme planen', p.titel)
        self.assertEqual(p.faellig_am, ende)
        # Idempotent — kein zweiter Eintrag
        generate_auto_pendenzen(horizont_tage=90)
        self.assertEqual(Pendenz.objects.filter(quelle=f'auto:ruecknahme:{k.id}').count(), 1)

    def test_auto_pendenz_ruecknahme_entfaellt_nach_abnahme(self):
        """Ist die Rücknahme bereits protokolliert, wird keine Pendenz erzeugt."""
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        from rentals.models import Abnahmeprotokoll
        lg, e, m, v, k, ende = self._kuendigung(tage_bis_ende=40)
        Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        generate_auto_pendenzen(horizont_tage=90)
        self.assertFalse(Pendenz.objects.filter(quelle=f'auto:ruecknahme:{k.id}').exists())

    def test_schlussabrechnung_nach_ruecknahme(self):
        """Nach der Rücknahme zeigt das Cockpit die Schlussabrechnung (Kaution offen),
        vorbefüllt aus dem Rücknahme-Protokoll."""
        from rentals.models import Abnahmeprotokoll
        lg, e, m, v, k, ende = self._kuendigung()   # v hat kautions_betrag 4500, Status 'erwartet'
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('Schlussabrechnung', body)
        self.assertIn(f'/neu/vertraege/{v.id}/schlussabrechnung/?abnahme={prot.id}', body)

    def test_offene_forderung_erzwingt_schlussabrechnung(self):
        """Auch ohne Kaution: offene Debitoren nach Rücknahme → Schlussabrechnung."""
        from rentals.models import Abnahmeprotokoll
        from finance.models import DebitorenRechnung
        lg, e, m, v, k, ende = self._kuendigung()
        v.kautions_betrag = Decimal('0'); v.save()   # keine Kaution
        Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                         titel='Restmiete', betrag=Decimal('900'),
                                         faellig_am=date.today(), status='offen')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('Schlussabrechnung', body)

    def test_abgerechnet_kein_schlussabrechnung_button(self):
        """Kaution zurückbezahlt und keine offenen Forderungen → keine Schlussabrechnung."""
        from rentals.models import Abnahmeprotokoll
        lg, e, m, v, k, ende = self._kuendigung()
        v.kautions_einbezahlt_am = date(2024, 1, 5)
        v.kautions_zurueckbezahlt_am = date.today()
        v.save()
        Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date.today())
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertNotIn('/schlussabrechnung/', body)

    def test_objekt_ausschreiben_button_und_verfuegbarkeit(self):
        """Cockpit bietet 'Objekt ausschreiben'; POST setzt Ausschreibung + Verfügbarkeit."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn(f'/neu/objekte/{e.id}/ausschreiben/', body)
        self.assertIn('Objekt ausschreiben', body)
        # Ausschreiben
        r = c.post(f'/neu/objekte/{e.id}/ausschreiben/', {'ziel': 'an', 'weiter': '/neu/mieterwechsel/'})
        self.assertEqual(r.status_code, 302)
        e.refresh_from_db()
        self.assertTrue(e.zur_ausschreibung)
        self.assertEqual(e.verfuegbar_ab, ende)   # aus der Kündigung übernommen

    def test_vermarktungsliste_zeigt_ausgeschriebenes_objekt(self):
        lg, e, m, v, k, ende = self._kuendigung()
        e.zur_ausschreibung = True
        e.verfuegbar_ab = ende
        e.save()
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.get('/neu/vermarktung/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Teststrasse 1')
        self.assertContains(r, '3.5 Zi')

    def test_ausschreibung_beenden(self):
        lg, e, m, v, k, ende = self._kuendigung()
        e.zur_ausschreibung = True; e.save()
        team = _team_user()
        c = Client(); c.force_login(team)
        c.post(f'/neu/objekte/{e.id}/ausschreiben/', {'ziel': 'aus', 'weiter': '/neu/vermarktung/'})
        e.refresh_from_db()
        self.assertFalse(e.zur_ausschreibung)
        # Objekt ist nicht mehr in der Vermarktungsliste
        self.assertContains(c.get('/neu/vermarktung/'), 'Kein Objekt in der Vermarktung')

    def test_cockpit_oeffnet_schritte_als_modal(self):
        """Cockpit-Aktionen öffnen die Schritte im Modal (fwModalOpen), nicht per Seitenwechsel."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('fwModalOpen(this', body)
        self.assertIn('id="fwModal"', body)
        self.assertIn("e.data.fwModal === 'done'", body)

    def test_abnahme_embed_ohne_sidebar(self):
        """Embed-Formular rendert ohne Sidebar (base_embed) für das Modal."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        voll = c.get(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug').content.decode()
        embed = c.get(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug&embed=1').content.decode()
        self.assertIn('fwSidebar', voll)          # Vollseite hat Sidebar
        self.assertNotIn('fwSidebar', embed)       # Embed hat keine Sidebar
        self.assertIn('name="embed" value="1"', embed)

    def test_abnahme_embed_post_signalisiert_done(self):
        """POST im Embed-Modus liefert die Modal-Done-Seite (postMessage an Cockpit)."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.post(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug&embed=1', {
            'embed': '1', 'typ': 'auszug', 'datum': date.today().isoformat(),
            'allgemein_zustand': 'gut',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn("fwModal: 'done'", r.content.decode())
        self.assertTrue(v.abnahmen.filter(typ='auszug').exists())

    def test_ausschreiben_form_im_modal(self):
        """'Objekt ausschreiben' öffnet ein Formular im Modal (GET embed), keine stille POST."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        # Cockpit verlinkt per Modal
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn(f"fwModalOpen(this,'Objekt ausschreiben')", body)
        # GET embed rendert das Formular ohne Sidebar, Verfügbarkeit vorbelegt aus Kündigung
        form = c.get(f'/neu/objekte/{e.id}/ausschreiben/?embed=1').content.decode()
        self.assertNotIn('fwSidebar', form)
        self.assertIn('name="verfuegbar_ab"', form)
        self.assertIn(ende.isoformat(), form)

    def test_ausschreiben_embed_post_signalisiert_done(self):
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.post(f'/neu/objekte/{e.id}/ausschreiben/', {
            'embed': '1', 'ziel': 'an', 'verfuegbar_ab': ende.isoformat(),
            'notiz': 'Renoviert 2024',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn("fwModal: 'done'", r.content.decode())
        e.refresh_from_db()
        self.assertTrue(e.zur_ausschreibung)
        self.assertEqual(e.verfuegbar_ab, ende)
        self.assertEqual(e.ausschreibung_notiz, 'Renoviert 2024')

    def test_navigations_schritte_oeffnen_im_modal(self):
        """Bewerbungen / Vertrag erstellen laufen ebenfalls über das Modal."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn("fwModalOpen(this,'Bewerbungen')", body)
        self.assertIn("fwModalOpen(this,'Vertrag erstellen',true)", body)   # breit

    def test_cockpit_vertrag_erstellen_mit_einheit_vorwahl(self):
        """'Vertrag erstellen' übergibt die konkrete Einheit an den Wizard."""
        lg, e, m, v, k, ende = self._kuendigung()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn(f'/neu/vertraege/neu/?einheit={e.id}', body)

    def test_wizard_vorwahl_nur_eine_einheit(self):
        """Mit ?einheit=<id> zeigt der Wizard nur diese Liegenschaft/Einheit und
        setzt die Vorwahl — auch wenn der alte Vertrag noch aktiv ist."""
        lg, e, m, v, k, ende = self._kuendigung()   # v ist aktiv auf e
        # zweite Liegenschaft, die NICHT erscheinen darf
        lg2 = Liegenschaft.objects.create(strasse='Andere 9', plz='3000', ort='Bern',
                                          versicherungswert=Decimal('500000'))
        Einheit.objects.create(liegenschaft=lg2, bezeichnung='2 Zi', typ='wohnung',
                               nettomiete_aktuell=Decimal('900'))
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.get(f'/neu/vertraege/neu/?einheit={e.id}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['vorwahl_einheit'], e.id)
        lgs = r.context['liegenschaften']   # nur die Wizard-Daten zählen
        self.assertEqual(len(lgs), 1)
        self.assertEqual(lgs[0]['id'], lg.id)
        self.assertEqual([o['id'] for o in lgs[0]['objekte']], [e.id])

    def test_embed_ueberlebt_redirect_via_iframe_kontext(self):
        """base.html blendet den Chrome auch ohne ?embed=1 aus, sobald im iframe
        geladen (window.self !== window.top) — so bleiben mehrstufige Flows
        (Wizard-Ende, Bewerbung→Vertrag) im Popup chrome-frei."""
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('window.self !== window.top', body)
        self.assertIn("classList.add('_embed')", body)


class MieterwechselE2ETests(TestCase):
    """Durchgängiger End-to-End-Durchlauf des ganzen Mieterwechsel-Kreislaufs
    über die echten URLs: Kündigen → Pendenzen → Ausschreiben → Nachmieter →
    Rücknahme → Übergabe → Schlussabrechnung → Auto-Abhaken → Cockpit leer."""

    def _konten(self):
        _seed_konten()

    def test_kompletter_kreislauf(self):
        from core.models import Pendenz
        from rentals.models import Kuendigung, Abnahmeprotokoll
        self._konten()
        lg = Liegenschaft.objects.create(strasse='Wechselweg 5', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='4.5 Zi', typ='wohnung',
                                   nettomiete_aktuell=Decimal('1800'), nebenkosten_aktuell=Decimal('250'))
        m = Mieter.objects.create(typ='person', vorname='Alt', nachname='Mieter', email='alt@example.ch')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2023, 1, 1),
                                       netto_mietzins=Decimal('1800'), nebenkosten=Decimal('250'),
                                       status='aktiv', kautions_betrag=Decimal('5400'),
                                       kautions_einbezahlt_am=date(2023, 1, 5))
        team = _team_user()
        c = Client(); c.force_login(team)

        # 1) KÜNDIGEN (im Popup) → Vertrag gekündigt + Auszugs-Pendenzen
        r = c.post(f'/neu/vertraege/{v.id}/kuendigen/', {
            'embed': '1', 'absender': 'mieter', 'eingang_datum': date.today().isoformat(),
            'zustellung': 'einschreiben'})
        self.assertIn("fwModal: 'done'", r.content.decode())
        v.refresh_from_db()
        self.assertEqual(v.status, 'gekuendigt')
        pend_total = Pendenz.objects.filter(vertrag=v, erledigt=False).count()
        self.assertGreaterEqual(pend_total, 5)

        # 1b) Kündigung schriftlich bestätigen → erste Pendenz abgehakt
        kd = Kuendigung.objects.get(vertrag=v)
        c.post(f'/neu/kuendigung/{kd.id}/bestaetigen/')
        self.assertFalse(Pendenz.objects.filter(vertrag=v, erledigt=False,
                                                titel__icontains='schriftlich bestätigen').exists())

        # 2) DASHBOARD zeigt die Aufgaben
        self.assertEqual(c.get('/neu/').status_code, 200)

        # 3) COCKPIT listet den Wechsel als 'Gekündigt' + Ausschreiben-Aktion
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('Wechselweg 5', body)
        self.assertIn(f'/neu/objekte/{e.id}/ausschreiben/', body)

        # 4) OBJEKT AUSSCHREIBEN → Vermarktung + 'Nachmieter'-Pendenz erledigt
        c.post(f'/neu/objekte/{e.id}/ausschreiben/',
               {'embed': '1', 'ziel': 'an', 'verfuegbar_ab': (date.today() + timedelta(days=60)).isoformat()})
        e.refresh_from_db()
        self.assertTrue(e.zur_ausschreibung)
        self.assertContains(c.get('/neu/vermarktung/'), '4.5 Zi')

        # 5) RÜCKNAHME protokollieren → 'Wohnungsabnahme'-Pendenz erledigt
        r = c.post(f'/neu/vertraege/{v.id}/abnahme/neu/?typ=auszug', {
            'embed': '1', 'typ': 'auszug', 'datum': date.today().isoformat(),
            'allgemein_zustand': 'gut', 'schluessel_anzahl': '3', 'zaehler_strom': '12345'})
        self.assertIn("fwModal: 'done'", r.content.decode())
        self.assertTrue(v.abnahmen.filter(typ='auszug').exists())
        self.assertFalse(Pendenz.objects.filter(vertrag=v, erledigt=False,
                                                titel__icontains='Wohnungsabnahme').exists())

        # 6) NACHMIETER-Vertrag anlegen (beginnt nach Auszug)
        nm = Mieter.objects.create(typ='person', vorname='Neu', nachname='Mieter', email='neu@example.ch')
        ende = v.ende or (date.today() + timedelta(days=60))
        nv = Mietvertrag.objects.create(mieter=nm, einheit=e, beginn=ende + timedelta(days=1),
                                        netto_mietzins=Decimal('1850'), nebenkosten=Decimal('250'),
                                        status='entwurf')
        # Nachmieter erkannt → Übergabe-Aktion verfügbar. (Die Stufe zeigt hier
        # bereits 'Schlussabrechnung', weil die Kaution offen ist — der
        # Übergabe-Link ist der Beweis, dass der Nachmieter erkannt wurde.)
        body = c.get('/neu/mieterwechsel/').content.decode()
        self.assertIn('Neu Mieter', body)
        self.assertIn(f'/neu/vertraege/{nv.id}/abnahme/neu/?typ=einzug', body)

        # 7) ÜBERGABE an Nachmieter
        r = c.post(f'/neu/vertraege/{nv.id}/abnahme/neu/?typ=einzug', {
            'embed': '1', 'typ': 'einzug', 'datum': date.today().isoformat(), 'allgemein_zustand': 'gut'})
        self.assertIn("fwModal: 'done'", r.content.decode())
        self.assertTrue(nv.abnahmen.filter(typ='einzug').exists())

        # 8) SCHLUSSABRECHNUNG verbuchen → Schlussabrechnung + Kaution erledigt
        r = c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/', {
            'embed': '1', 'aktion': 'buchen', 'auszug_datum': ende.isoformat(),
            'kaution_verrechnen': 'on'})
        self.assertIn("fwModal: 'done'", r.content.decode())
        v.refresh_from_db()
        self.assertIsNotNone(v.kautions_zurueckbezahlt_am)

        # 9) ERGEBNIS: alle Auszugs-Pendenzen erledigt → Gruppe leer
        offen = Pendenz.objects.filter(vertrag=v, erledigt=False)
        self.assertEqual(offen.count(), 0,
                         f"noch offen: {[p.titel for p in offen]}")


class BewerberScoringTests(TestCase):
    """Bewerber-Vergleich mit Eignungs-Score (Tragbarkeit/Betreibungen/Anstellung/Doku)."""

    def _bewerbung(self, e, **kw):
        from mietprozess.models import Mietbewerbung
        defaults = dict(
            einheit=e, vorname='Anna', nachname='Muster', geburtsdatum=date(1990, 1, 1),
            mobilnummer='079 000 00 00', email='anna@example.ch', beruf='Kauffrau',
            einkommen_jahr="90'000", erwerbsstatus='angestellt', ist_unbefristet=True,
            hat_betreibungen=False, anzahl_erwachsene=1, status='geprueft',
            # Belege vorhanden → Betreibungs-/Anstellungspunkte werden vergeben
            # (ohne Beleg gibt es sie bewusst nicht mehr, siehe bewerber_scoring).
            digitaler_betreibungsauszug=True, arbeitgeber='Muster AG')
        defaults.update(kw)
        return Mietbewerbung.objects.create(**defaults)

    def test_parse_einkommen(self):
        from core.services.bewerber_scoring import parse_einkommen
        self.assertEqual(parse_einkommen("90'000"), 90000)
        self.assertEqual(parse_einkommen("80'000 – 100'000"), 80000)   # untere Grenze
        self.assertEqual(parse_einkommen("CHF 72000"), 72000)
        self.assertIsNone(parse_einkommen("keine Angabe"))

    def test_scoring_guter_bewerber(self):
        from core.services.bewerber_scoring import bewerte_bewerbung
        lg, e, m, v = _basis_objekte()   # Brutto 1700/Mt → 20'400/Jahr
        e.betreibungsauszug = 'x.pdf'; e.save()  # egal
        b = self._bewerbung(e, einkommen_jahr="90000")  # 90'000 / 20'400 = 4.4× → gut
        r = bewerte_bewerbung(b, Decimal('1700'))
        # Doku 15: Der Betreibungsauszug wird digital bezogen — das ist in dieser
        # Stufe die einzige verlangte Unterlage und damit vollständig. Vorher gab
        # es dafür 0 Punkte, weil nur hochgeladene DATEIEN zählten; wer den von
        # der App selbst angebotenen digitalen Weg wählte, wurde also bestraft.
        self.assertEqual(r['score'], 45 + 25 + 15 + 15)
        self.assertEqual(r['ampel'], 'gut')

    def test_scoring_betreibungen_und_tragbarkeit(self):
        from core.services.bewerber_scoring import bewerte_bewerbung
        lg, e, m, v = _basis_objekte()
        b = self._bewerbung(e, einkommen_jahr="30000", hat_betreibungen=True)  # 30'000/20'400=1.47× → 0 Pkt
        r = bewerte_bewerbung(b, Decimal('1700'))
        # Tragbarkeit 0 + Betreibungen 0 + Anstellung 15 + Doku 15 = 30.
        # Doku zählt, weil der Betreibungsauszug digital bezogen wird — die
        # Unterlagen sind vollständig, der Auszug ist inhaltlich nur eben
        # negativ. Das ist der Sinn getrennter Indikatoren: «Unterlagen da»
        # und «Betreibungen vorhanden» sind zwei verschiedene Aussagen.
        self.assertEqual(r['score'], 30)
        self.assertEqual(r['ampel'], 'schlecht')

    def test_vergleich_view_sortiert_nach_score(self):
        lg, e, m, v = _basis_objekte()
        self._bewerbung(e, vorname='Schwach', einkommen_jahr="28000", hat_betreibungen=True)
        self._bewerbung(e, vorname='Stark', einkommen_jahr="120000")
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vermarktung/{e.id}/bewerber/')
        self.assertEqual(r.status_code, 200)
        namen = [k['b'].vorname for k in r.context['kandidaten']]
        self.assertEqual(namen, ['Stark', 'Schwach'])   # bester zuerst

    def test_abgelehnte_ausgeblendet(self):
        lg, e, m, v = _basis_objekte()
        self._bewerbung(e, vorname='Aktiv')
        self._bewerbung(e, vorname='Weg', status='abgelehnt')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/vermarktung/{e.id}/bewerber/')
        self.assertEqual(len(r.context['kandidaten']), 1)
        r2 = c.get(f'/neu/vermarktung/{e.id}/bewerber/?alle=1')
        self.assertEqual(len(r2.context['kandidaten']), 2)


class BewerberEntscheidTests(TestCase):
    """Zusage/Absage an Bewerber mit E-Mail + Sammelabsage."""

    def _bewerbung(self, e, vorname='Anna', status='geprueft', email='anna@example.ch'):
        from mietprozess.models import Mietbewerbung
        return Mietbewerbung.objects.create(
            einheit=e, vorname=vorname, nachname='Muster', geburtsdatum=date(1990, 1, 1),
            mobilnummer='079', email=email, beruf='Kauffrau', einkommen_jahr="90000",
            erwerbsstatus='angestellt', status=status)

    def test_zusage_setzt_status(self):
        lg, e, m, v = _basis_objekte()
        b = self._bewerbung(e)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        r = c.post(f'/neu/bewerbungen/{b.id}/entscheid/', {'entscheid': 'zusage'})
        self.assertEqual(r.status_code, 302)
        b.refresh_from_db()
        self.assertEqual(b.status, 'zugesagt')

    def test_absage_setzt_status(self):
        lg, e, m, v = _basis_objekte()
        b = self._bewerbung(e)
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/bewerbungen/{b.id}/entscheid/', {'entscheid': 'absage'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'abgelehnt')

    def test_sammelabsage_nur_offene(self):
        lg, e, m, v = _basis_objekte()
        b1 = self._bewerbung(e, 'A', status='neu')
        b2 = self._bewerbung(e, 'B', status='geprueft')
        b3 = self._bewerbung(e, 'C', status='zugesagt')   # bleibt unangetastet
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/vermarktung/{e.id}/bewerber/absage-uebrige/')
        b1.refresh_from_db(); b2.refresh_from_db(); b3.refresh_from_db()
        self.assertEqual(b1.status, 'abgelehnt')
        self.assertEqual(b2.status, 'abgelehnt')
        self.assertEqual(b3.status, 'zugesagt')

    def test_mail_text_default(self):
        from core.views.fw import _bewerber_mail
        lg, e, m, v = _basis_objekte()
        b = self._bewerbung(e)
        betreff, body = _bewerber_mail(b, 'zusage')
        self.assertIn('Zusage', betreff)
        self.assertIn('Anna Muster', body)


class MieterwechselAuslaufTests(TestCase):
    """Konsolidiertes Mieterwechsel-Cockpit: gekündigte UND auslaufende Verträge."""

    def test_auslaufender_vertrag_erscheint(self):
        lg, e, m, v = _basis_objekte()
        v.ist_befristet = True; v.ende = date.today() + timedelta(days=45); v.save()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterwechsel/')
        self.assertEqual(r.status_code, 200)
        row = next((x for x in r.context['rows'] if x['v'].id == v.id), None)
        self.assertIsNotNone(row)
        self.assertFalse(row['gekuendigt'])
        self.assertEqual(row['stufe'], 'Läuft aus')
        self.assertEqual(r.context['auslaufend_n'], 1)

    def test_gekuendigter_vertrag_erscheint(self):
        from rentals.models import Kuendigung
        lg, e, m, v = _basis_objekte()
        v.status = 'gekuendigt'; v.save()
        Kuendigung.objects.create(vertrag=v, absender='mieter', status='erfasst',
                                  per_datum=date.today() + timedelta(days=60))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterwechsel/')
        row = next((x for x in r.context['rows'] if x['v'].id == v.id), None)
        self.assertIsNotNone(row)
        self.assertTrue(row['gekuendigt'])
        self.assertEqual(r.context['gekuendigt_n'], 1)

    def test_horizont_filter_nur_auslaufende(self):
        lg, e, m, v = _basis_objekte()
        v.ist_befristet = True; v.ende = date.today() + timedelta(days=300); v.save()   # > 6 Monate
        c = Client(); c.force_login(_team_user())
        self.assertEqual(c.get('/neu/mieterwechsel/?monate=6').context['auslaufend_n'], 0)
        self.assertEqual(c.get('/neu/mieterwechsel/?monate=12').context['auslaufend_n'], 1)

    def test_keine_doppelung_gekuendigt_und_ende(self):
        from rentals.models import Kuendigung
        lg, e, m, v = _basis_objekte()
        v.status = 'gekuendigt'; v.ende = date.today() + timedelta(days=30); v.save()
        Kuendigung.objects.create(vertrag=v, absender='mieter', status='erfasst',
                                  per_datum=date.today() + timedelta(days=30))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterwechsel/')
        treffer = [x for x in r.context['rows'] if x['v'].id == v.id]
        self.assertEqual(len(treffer), 1)   # nur einmal (als gekündigt)
        self.assertTrue(treffer[0]['gekuendigt'])

    def test_vertragsauslauf_route_entfernt(self):
        c = Client(); c.force_login(_team_user())
        self.assertEqual(c.get('/neu/vertragsauslauf/').status_code, 404)


class BewerberScoringBelegTests(TestCase):
    """Score-Punkte für Betreibungen/Anstellung nur bei tatsächlichem Beleg —
    eine leere Bewerbung wirkt nicht mehr fälschlich 'mittel'."""

    def test_leere_bewerbung_nicht_mittel(self):
        from mietprozess.models import Mietbewerbung
        from core.services.bewerber_scoring import bewerte_bewerbung
        _lg, e, _m, _v = _basis_objekte()
        b = Mietbewerbung.objects.create(einheit=e, vorname='Leer', nachname='Test',
                                         email='leer@example.ch', geburtsdatum=date(1990, 1, 1))
        r = bewerte_bewerbung(b, Decimal('1700'))
        betr = next(i for i in r['indikatoren'] if i['label'] == 'Betreibungen')
        anst = next(i for i in r['indikatoren'] if i['label'] == 'Anstellung')
        self.assertEqual(betr['ampel'], 'schlecht')   # kein Auszug → 0 Punkte
        self.assertEqual(anst['ampel'], 'schlecht')   # keine Angabe → 0 Punkte
        self.assertLess(r['score'], 40)

    def test_belegte_bewerbung_erhaelt_punkte(self):
        from mietprozess.models import Mietbewerbung
        from core.services.bewerber_scoring import bewerte_bewerbung
        _lg, e, _m, _v = _basis_objekte()
        b = Mietbewerbung.objects.create(
            einheit=e, vorname='Beleg', nachname='Test', email='beleg@example.ch',
            geburtsdatum=date(1990, 1, 1), digitaler_betreibungsauszug=True,
            hat_betreibungen=False, erwerbsstatus='angestellt', ist_unbefristet=True,
            arbeitgeber='Muster AG', einkommen_jahr='90000')
        r = bewerte_bewerbung(b, Decimal('1700'))   # 90000 / 20400 = 4.4× → Tragbarkeit gut
        # 45 (Tragbarkeit) + 25 (Betreibungen belegt) + 15 (Anstellung belegt) = 85
        self.assertGreaterEqual(r['score'], 85)


class BewerbungRateLimitTests(TestCase):
    def test_rate_limit_blockt_nach_limit(self):
        from django.core.cache import cache
        from core.utils.throttle import rate_limit
        cache.clear()
        key = 'test:1.2.3.4'
        for _ in range(5):
            self.assertTrue(rate_limit(key, limit=5, window_seconds=60))
        self.assertFalse(rate_limit(key, limit=5, window_seconds=60))   # 6. blockiert


class NachtN8BesichtigungTests(TestCase):
    """Nacht-Audit N8: Besichtigungsstufe im Bewerbungsprozess."""

    def _bewerbung(self):
        from mietprozess.models import Mietbewerbung
        lg, e, m, v = _basis_objekte()
        b = Mietbewerbung.objects.create(
            einheit=e, vorname='Anna', nachname='Muster', email='anna@example.ch',
            geburtsdatum=date(1990, 5, 1), status='neu')
        u = _team_user(); c = Client(); c.force_login(u)
        return b, c

    def test_einladen_setzt_status_mail_journal_pendenz(self):
        from django.core import mail
        from crm.models import Kommunikation
        from core.models import Pendenz
        b, c = self._bewerbung()
        termin = (date.today() + timedelta(days=5)).isoformat() + 'T18:30'
        r = c.post(f'/neu/bewerbungen/{b.id}/besichtigung/', {'termin': termin})
        self.assertEqual(r.status_code, 302)
        b.refresh_from_db()
        self.assertEqual(b.status, 'besichtigung')
        self.assertIsNotNone(b.besichtigung_am)
        mails = [m for m in mail.outbox if 'Besichtigung' in m.subject]
        self.assertEqual(len(mails), 1)
        self.assertIn('anna@example.ch', mails[0].to)
        self.assertTrue(Kommunikation.objects.filter(typ='email', betreff__icontains='Besichtigung').exists())
        p = Pendenz.objects.filter(quelle=f'besichtigung:{b.id}').first()
        self.assertIsNotNone(p)
        self.assertEqual(p.faellig_am, date.today() + timedelta(days=5))

    def test_termin_aenderung_ist_idempotent(self):
        from core.models import Pendenz
        b, c = self._bewerbung()
        t1 = (date.today() + timedelta(days=5)).isoformat() + 'T18:30'
        t2 = (date.today() + timedelta(days=8)).isoformat() + 'T19:00'
        c.post(f'/neu/bewerbungen/{b.id}/besichtigung/', {'termin': t1})
        c.post(f'/neu/bewerbungen/{b.id}/besichtigung/', {'termin': t2})
        pq = Pendenz.objects.filter(quelle=f'besichtigung:{b.id}')
        self.assertEqual(pq.count(), 1)
        self.assertEqual(pq.first().faellig_am, date.today() + timedelta(days=8))

    def test_board_hat_besichtigung_spalte(self):
        b, c = self._bewerbung()
        b.status = 'besichtigung'; b.save(update_fields=['status'])
        body = c.get('/neu/bewerbungen/').content.decode()
        self.assertIn('Besichtigung', body)
        self.assertIn('Anna', body)

    def test_ungueltiger_termin_abgelehnt(self):
        b, c = self._bewerbung()
        c.post(f'/neu/bewerbungen/{b.id}/besichtigung/', {'termin': 'kein-datum'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'neu')
        self.assertIsNone(b.besichtigung_am)


class BewerbungNurAusgeschriebenTests(TestCase):
    """Bewerbungen nur für Objekte, die auch ausgeschrieben sind.

    Das Bewerbungsformular ist ohne Anmeldung erreichbar. Es rendete für JEDE
    Objektnummer — mit Adresse und Objektbezeichnung. Zwei Folgen:

      - Über die Nummer in der Adresse liess sich der ganze Bestand
        durchprobieren.
      - Ein alter, geteilter Link sammelte weiter Bewerbungen — mit
        Lohnausweis, Ausweiskopie und Betreibungsauszug — für eine längst
        vergebene Wohnung.

    Die Gegenprüfung im API-Endpunkt sah zwar vorhanden aus:

        is_rented = False
        if hasattr(einheit, 'ist_vermietet'):        # gibt es nicht
            ...
        elif hasattr(einheit, 'vermietungs_status'): # gibt es auch nicht
            ...
        if is_rented: ...

    Beide Namen existieren an `Einheit` nicht. `is_rented` blieb damit immer
    False, und die Fehlermeldung «bereits vermietet» war unerreichbar.
    """

    def _einheit(self, ausgeschrieben):
        lg = Liegenschaft.objects.create(strasse='Inseratweg 3', plz='4500', ort='Solothurn')
        return Einheit.objects.create(liegenschaft=lg, bezeichnung='2.5 Zi', typ='wohnung',
                                      nettomiete_aktuell=Decimal('1200'),
                                      zur_ausschreibung=ausgeschrieben)

    def test_die_alte_pruefung_haette_nichts_geprueft(self):
        """Warum der Umbau nötig war — schwarz auf weiss."""
        self.assertFalse(hasattr(Einheit, 'ist_vermietet'))
        self.assertFalse(hasattr(Einheit, 'vermietungs_status'))
        self.assertTrue(hasattr(Einheit, 'zur_ausschreibung'))

    def test_formular_nur_bei_ausschreibung(self):
        c = Client()
        offen = self._einheit(True)
        r = c.get(f'/bewerben/{offen.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '2.5 Zi')

        zu = self._einheit(False)
        r2 = c.get(f'/bewerben/{zu.id}/')
        self.assertEqual(r2.status_code, 410)
        self.assertNotContains(r2, 'Inseratweg', status_code=410)   # keine Adresse preisgeben
        self.assertNotContains(r2, '2.5 Zi', status_code=410)

    def _bewerben(self, einheit):
        return Client().post('/api/mietprozess/public/bewerben', {
            'einheit_id': einheit.id,
            'vorname': 'Anna', 'nachname': 'Muster', 'zivilstand': 'ledig',
            'geburtsdatum': '1990-05-05', 'geschlecht': 'weiblich',
            'nationalitaet': 'CH', 'mobilnummer': '079 000 00 00',
            'email': 'anna@example.ch', 'adresse': 'Altweg 4',
            'plz': '4500', 'ort': 'Solothurn',
            'aktueller_vermieter': 'Alt AG', 'kontaktperson_vermieter': 'Herr Alt',
            'telefon_vermieter': '032 000 00 00',
            'erwerbsstatus': 'angestellt', 'beruf': 'Fachfrau',
            'einkommen_jahr': '80000-100000', 'arbeitgeber': 'Firma AG',
            'angestellt_seit': '2020-01-01',
            'kontaktperson_arbeitgeber': 'Frau Chef',
            'telefon_arbeitgeber': '032 111 11 11',
            'gewuenschter_bezugstermin': '2026-10-01',
        })

    def test_bewerbung_auf_nicht_ausgeschriebenes_objekt_abgelehnt(self):
        zu = self._einheit(False)
        r = self._bewerben(zu)
        self.assertEqual(r.status_code, 400)
        self.assertIn('nicht mehr ausgeschrieben', r.json().get('error', ''))

    def test_bewerbung_auf_ausgeschriebenes_objekt_geht(self):
        """Gegenrichtung — sonst würde auch eine Prüfung bestehen, die ALLES
        ablehnt."""
        from mietprozess.models import Mietbewerbung
        offen = self._einheit(True)
        r = self._bewerben(offen)
        self.assertEqual(r.status_code, 201, r.content[:300])
        self.assertTrue(Mietbewerbung.objects.filter(einheit=offen, nachname='Muster').exists())


class BewerbungAufbewahrungTests(TestCase):
    """Bewerbungsdossiers nach dem Vermietungsentscheid.

    Ein Dossier enthält Ausweiskopie, Lohnausweis, Betreibungsauszug, dazu
    Geburtsdatum, Nationalität, Zivilstand, Einkommen, Arbeitgeber, Kinder —
    die heikelsten Daten der Anwendung. Gesammelt bei Menschen, die zur
    Verwaltung meist gar kein Vertragsverhältnis haben: Die Wohnung bekommt
    eine Bewerberin, alle übrigen Dossiers sind nach dem Entscheid zwecklos.

    Bisher blieben sie unbegrenzt liegen. `core.services.dsg` greift nur bei
    Personen, die auch Mieter WURDEN — abgelehnte Bewerbungen erfasste es
    nicht. Das DSG verlangt Vernichtung, sobald der Zweck entfällt (Art. 6
    Abs. 4); eine Aufbewahrungspflicht wie für Buchungsbelege (Art. 958f OR)
    gibt es hier gerade nicht.
    """

    def setUp(self):
        import tempfile
        from django.test import override_settings
        self._tmp = tempfile.TemporaryDirectory()
        self._ov = override_settings(MEDIA_ROOT=self._tmp.name)
        self._ov.enable()
        self.lg = Liegenschaft.objects.create(strasse='Bewerbweg 1', plz='3000', ort='Bern')
        self.e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='2.5 Zi', typ='wohnung')

    def tearDown(self):
        self._ov.disable()
        self._tmp.cleanup()

    def _bewerbung(self, *, status='abgelehnt', entschieden_vor_tagen=200, mit_dokumenten=True):
        from django.core.files.base import ContentFile
        from mietprozess.models import Mietbewerbung
        b = Mietbewerbung.objects.create(
            einheit=self.e, status=status, vorname='Anna', nachname='Bewerber',
            geburtsdatum=date(1990, 5, 17), mobilnummer='079 000 00 00',
            email='anna.bewerber@example.ch', beruf='Kauffrau', einkommen_jahr="90'000",
            arbeitgeber='Muster AG', adresse='Alte Gasse 3', plz='3000', ort='Bern',
            nationalitaet='Schweiz')
        if mit_dokumenten:
            b.ausweiskopie.save('ausweis.pdf', ContentFile(b'%PDF-Ausweis'), save=False)
            b.lohnausweis.save('lohn.pdf', ContentFile(b'%PDF-Lohn'), save=False)
            b.betreibungsauszug.save('betr.pdf', ContentFile(b'%PDF-Betreibung'), save=False)
            b.save()
        # erstellt_am/aktualisiert_am sind auto_now(_add) — direkt in der DB setzen.
        from django.utils import timezone
        wann = timezone.now() - timedelta(days=entschieden_vor_tagen)
        type(b).objects.filter(pk=b.pk).update(erstellt_am=wann - timedelta(days=30),
                                               aktualisiert_am=wann)
        b.refresh_from_db()
        return b

    def _dateien_da(self, b):
        import os
        from django.conf import settings
        b.refresh_from_db()
        return [f for f in ('ausweiskopie', 'lohnausweis', 'betreibungsauszug')
                if getattr(b, f) and os.path.exists(
                    os.path.join(settings.MEDIA_ROOT, getattr(b, f).name))]

    def test_abgelehntes_dossier_verliert_seine_dokumente(self):
        from core.services.bewerbung_aufbewahrung import bereinige
        b = self._bewerbung(entschieden_vor_tagen=120)
        self.assertEqual(len(self._dateien_da(b)), 3, 'Ausgangslage: drei Dateien vorhanden')
        bereinige(_heute(), anwenden=True)
        self.assertEqual(self._dateien_da(b), [],
                         'Ausweis/Lohnausweis/Betreibungsauszug liegen weiter auf der Platte')

    def test_innerhalb_der_nachlauffrist_bleibt_alles(self):
        """Die wenigen Tage sind keine Aufbewahrung, sondern Nachlauf für den
        Versand der Absagen — vorher wird nichts angefasst.

        Stand ursprünglich auf 30 Tagen, weil die Frist 90 Tage betrug. Der
        EDÖB verlangt Vernichtung «möglichst rasch»; die Frist ist deshalb auf
        7 Tage verkürzt, und dieser Test zog nach."""
        from core.services.bewerbung_aufbewahrung import bereinige
        b = self._bewerbung(entschieden_vor_tagen=2)
        bereinige(_heute(), anwenden=True)
        self.assertEqual(len(self._dateien_da(b)), 3)

    def test_offene_bewerbung_wird_nie_angefasst(self):
        """Solange nicht entschieden ist, läuft keine Frist — sonst würde
        einer Bewerberin das Dossier unter dem laufenden Verfahren gelöscht."""
        from core.services.bewerbung_aufbewahrung import bereinige
        b = self._bewerbung(status='neu', entschieden_vor_tagen=800)
        bereinige(_heute(), anwenden=True)
        self.assertEqual(len(self._dateien_da(b)), 3)
        b.refresh_from_db()
        self.assertEqual(b.vorname, 'Anna')

    def test_zusage_wird_nie_automatisch_geloescht(self):
        """Aus dem zugesagten Dossier entsteht das Mietverhältnis. Es läuft
        über die Personen-Anonymisierung, nicht über diese Frist."""
        from core.services.bewerbung_aufbewahrung import bereinige
        b = self._bewerbung(status='zugesagt', entschieden_vor_tagen=900)
        bereinige(_heute(), anwenden=True)
        self.assertEqual(len(self._dateien_da(b)), 3)

    def test_stille_absage_zaehlt_auch(self):
        """Der häufigste Fall in der Praxis: nie beantwortet, aber die Wohnung
        ist längst vermietet. Ohne diesen Weg bliebe der grösste Teil der
        Dossiers für immer liegen."""
        from core.services.bewerbung_aufbewahrung import bereinige, entschieden_am
        b = self._bewerbung(status='geprueft', entschieden_vor_tagen=400)
        m = Mieter.objects.create(typ='person', vorname='Neu', nachname='Mieter',
                                  email='neu@example.ch', strasse='W 1', plz='3000', ort='Bern')
        Mietvertrag.objects.create(mieter=m, einheit=self.e, status='aktiv',
                                   beginn=_heute() - timedelta(days=300),
                                   netto_mietzins=Decimal('1200'), nebenkosten=Decimal('150'))
        self.assertIsNotNone(entschieden_am(b), 'Vermietetes Objekt = Entscheid gefallen')
        bereinige(_heute(), anwenden=True)
        self.assertEqual(self._dateien_da(b), [])

    def test_nach_einem_jahr_verschwinden_auch_die_personalien(self):
        from core.services.bewerbung_aufbewahrung import bereinige
        b = self._bewerbung(entschieden_vor_tagen=400)
        bereinige(_heute(), anwenden=True)
        b.refresh_from_db()
        self.assertEqual(b.vorname, 'Anonymisiert')
        for feld, wert in (('arbeitgeber', 'Muster AG'), ('adresse', 'Alte Gasse 3'),
                           ('einkommen_jahr', "90'000"), ('nationalitaet', 'Schweiz')):
            self.assertNotEqual(getattr(b, feld), wert, f'{feld} steht noch im Dossier')
        self.assertNotIn('anna.bewerber', b.email)
        self.assertEqual(self._dateien_da(b), [])

    def test_trockenlauf_aendert_nichts(self):
        """Ohne --apply darf nichts verschwinden — sonst wäre die Vorschau
        eine Löschung."""
        from core.services.bewerbung_aufbewahrung import bereinige
        b = self._bewerbung(entschieden_vor_tagen=400)
        dok, anon = bereinige(_heute(), anwenden=False)
        self.assertEqual((dok, anon), (0, 1), 'Vorschau meldet den Fall nicht')
        self.assertEqual(len(self._dateien_da(b)), 3)
        b.refresh_from_db()
        self.assertEqual(b.vorname, 'Anna')

    def test_taeglicher_lauf_fuehrt_die_bereinigung_aus(self):
        """Eine Frist, die niemand auslöst, ist keine Frist."""
        from django.core.management import call_command
        import io
        b = self._bewerbung(entschieden_vor_tagen=120)
        call_command('taeglicher_lauf', stdout=io.StringIO())
        self.assertEqual(self._dateien_da(b), [],
                         'Der tägliche Lauf bereinigt die Bewerbungsdossiers nicht')


class BewerbungDatenschutzTests(TestCase):
    """Was das öffentliche Bewerbungsformular fragen darf — und was es sagen muss.

    Massgeblich sind das EDÖB-Merkblatt zu Anmeldeformularen für Mietwohnungen
    und die darauf gestützte SVIT-Branchenempfehlung (Anhang E). Beide gehen
    von einem ZWEISTUFIGEN Verfahren aus: Im ersten Schritt nur, was zur
    Vorauswahl nötig ist; Belege erst, wenn sich ein Vertragsabschluss
    konkretisiert. Das Formular fragte bisher alles auf einmal ab.
    """

    def setUp(self):
        self.lg = Liegenschaft.objects.create(strasse='Inserat 1', plz='3000', ort='Bern')
        self.e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='3.5 Zi',
                                        typ='wohnung', zur_ausschreibung=True)

    def _formular(self):
        return Client().get(f'/bewerben/{self.e.id}/').content.decode()

    def test_zivilstand_wird_nicht_mehr_gefragt(self):
        """«Die Frage nach dem Zivilstand ist aus Datenschutzüberlegungen nicht
        verhältnismässig» — SVIT-Branchenempfehlung DSG, Anhang E."""
        self.assertNotIn('form.zivilstand', self._formular())

    def test_ausweis_und_lohnausweis_erst_in_der_engeren_auswahl(self):
        """Belege zum Einkommen darf man erst von der ausgewählten Person oder
        einer engeren Auswahl verlangen, nicht von allen Interessenten."""
        html = self._formular()
        self.assertNotIn("handleFile($event, 'lohnausweis')", html)
        self.assertNotIn("handleFile($event, 'ausweiskopie')", html)

    def test_betreibungsauszug_bleibt_zulaessig(self):
        """Gegenstück: Der Betreibungsregisterauszug darf mit dem Formular von
        allen eingefordert werden. Ohne diese Prüfung wäre «weniger fragen»
        auch durch das Leeren des ganzen Formulars erfüllt."""
        self.assertIn("handleFile($event, 'betreibungsauszug')", self._formular())

    def test_formular_erfuellt_die_informationspflicht(self):
        """Art. 19 revDSG: Information bei der Beschaffung. Der EDÖB verlangt
        zusätzlich ausdrücklich den Hinweis auf mögliche Referenzauskünfte."""
        html = self._formular()
        for stichwort in ('Referenzauskunft', 'gelöscht', 'Auskunft', 'Datenschutzerklärung'):
            self.assertIn(stichwort, html, f'Hinweis auf «{stichwort}» fehlt im Formular')
        self.assertIn('/datenschutz/', html, 'Keine Verknüpfung zur Datenschutzerklärung')

    def test_datenschutzerklaerung_ist_ohne_anmeldung_lesbar(self):
        """Sie wird aus dem öffentlichen Formular verlinkt — wer dort landet,
        ist nicht angemeldet."""
        r = Client().get('/datenschutz/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for stichwort in ('Verantwortliche', 'Aufbewahr', 'Ihre Rechte', '958f'):
            self.assertIn(stichwort, html, f'«{stichwort}» fehlt in der Datenschutzerklärung')

    def test_datenschutzerklaerung_nennt_die_verwaltung_aus_den_stammdaten(self):
        """Kein zweiter Ort für Firma und Adresse, der veralten kann."""
        from crm.models import Organisation
        Organisation.objects.create(firma='Muster Immobilien AG', strasse='Amtsweg 4',
                                  plz='3011', ort='Bern')
        html = Client().get('/datenschutz/').content.decode()
        self.assertIn('Muster Immobilien AG', html)
        self.assertIn('3011', html)

    def test_loeschfrist_folgt_dem_edoeb_massstab(self):
        """Der EDÖB verlangt Vernichtung «möglichst rasch» nach dem Entscheid.
        Die erste Fassung stand auf 90 Tagen — zu lang."""
        import inspect
        from core.services.bewerbung_aufbewahrung import bereinige
        vorgabe = inspect.signature(bereinige).parameters['dokumente_tage'].default
        self.assertLessEqual(vorgabe, 14,
                             f'Standardfrist {vorgabe} Tage ist zu lang für «möglichst rasch»')
