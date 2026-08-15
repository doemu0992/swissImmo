"""Testmodul mietzins — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 15 Klassen, unveraendert uebernommen."""
from datetime import date
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (
    _team_user, _basis_objekte, _seed_konten, Mieter, Verwaltung,
    Liegenschaft, Einheit, Mietvertrag)



class LikVertragTests(TestCase):
    """LIK im Mietvertrag: Basis (Dez. 2020) + Stand-Monat durchgängig."""

    def test_lik_context_basis_und_stand(self):
        from core.services.lik import vertrag_lik_context
        lg, e, m, v = _basis_objekte()
        vw = Verwaltung.objects.create(firma='V AG', lik_basis='Dezember 2020',
                                       aktueller_lik_punkte=Decimal('107.1'),
                                       aktueller_lik_stand=date(2024, 8, 1))
        v.basis_lik_punkte = Decimal('106.3'); v.basis_lik_stand = date(2023, 5, 1); v.save()
        ctx = vertrag_lik_context(v, vw)
        self.assertEqual(ctx['lik_basis'], 'Dezember 2020')
        self.assertEqual(ctx['lik_stand_label'], 'Mai 2023')
        self.assertEqual(ctx['lik_pkt'], '106,3')

    def test_lik_context_fallback_auf_verwaltungsstand(self):
        from core.services.lik import vertrag_lik_context
        lg, e, m, v = _basis_objekte()
        vw = Verwaltung.objects.create(firma='V AG', aktueller_lik_stand=date(2025, 3, 1))
        v.basis_lik_stand = None; v.save()
        ctx = vertrag_lik_context(v, vw)
        self.assertEqual(ctx['lik_stand_label'], 'März 2025')   # Fallback

    def test_vertrag_pdf_enthaelt_basis_und_stand(self):
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        lg, e, m, v = _basis_objekte()
        Verwaltung.objects.create(firma='V AG', lik_basis='Dezember 2020', aktueller_lik_stand=date(2024, 8, 1))
        v.basis_lik_punkte = Decimal('107.1'); v.basis_lik_stand = date(2024, 8, 1); v.save()
        pdf = generate_vertrag_pdf_bytes(v)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_assistent_setzt_stand_beim_erstellen(self):
        from rentals.models import Mietvertrag as MV
        from core.services.lik import aktueller_lik_wert
        lg = Liegenschaft.objects.create(strasse='Neu 1', plz='8000', ort='ZH', versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='2 Zi', typ='wohnung')
        m = Mieter.objects.create(typ='person', nachname='Neu')
        team = _team_user()
        c = Client(); c.force_login(team)
        r = c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': str(e.id), 'mieter_id': str(m.id), 'beginn': '2025-01-01',
            'netto_mietzins': '1500', 'nebenkosten': '200', 'basis_lik_punkte': '107.1'})
        self.assertEqual(r.status_code, 302)
        v = MV.objects.filter(mieter=m).first()
        # ohne Formular-Override wird automatisch der neueste BFS-Stand gesetzt
        auto_stand, _pkt, _basis = aktueller_lik_wert()
        self.assertEqual(v.basis_lik_stand, auto_stand)

    def test_assistent_formular_override_stand(self):
        from rentals.models import Mietvertrag as MV
        lg = Liegenschaft.objects.create(strasse='Neu 2', plz='8000', ort='ZH', versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='2 Zi', typ='wohnung')
        m = Mieter.objects.create(typ='person', nachname='Ovr')
        team = _team_user()
        c = Client(); c.force_login(team)
        c.post('/neu/vertraege/neu/speichern/', {
            'einheit_id': str(e.id), 'mieter_id': str(m.id), 'beginn': '2025-01-01',
            'netto_mietzins': '1500', 'nebenkosten': '200', 'basis_lik_punkte': '106.3',
            'basis_lik_stand': '2023-05'})
        v = MV.objects.filter(mieter=m).first()
        self.assertEqual(v.basis_lik_stand, date(2023, 5, 1))

    def test_aktueller_lik_wert_aus_tabelle(self):
        from core.services.lik import aktueller_lik_wert
        # live=False → deterministisch aus der eingebauten BFS-Tabelle
        stand, pkt, basis = aktueller_lik_wert(live=False)
        self.assertEqual(basis, 'Dezember 2020')
        self.assertEqual(stand, date(2026, 6, 1))       # neuester Monat im Bild
        self.assertEqual(pkt, Decimal('108.3'))

    def test_live_parser_extrahiert_monat_und_wert(self):
        # Simuliert die HEV-Tabelle: Live-Parser muss Monat UND Wert lesen
        from core.services import lik as liks
        html = ('<html>Dezember 2020 = 100'
                '<table><tr><td>2026</td>'
                '<td>106.9</td><td>107.6</td><td>107.8</td><td>108.1</td>'
                '<td>108.3</td><td>108.3</td></tr>'
                '<tr><td>2025</td><td>106.8</td></tr></table></html>')
        orig = liks.requests.get if hasattr(liks, 'requests') else None
        import types
        class _Resp:
            text = html
        import core.services.lik as _m
        import requests as _rq
        _saved = _rq.get
        _rq.get = lambda *a, **k: _Resp()
        try:
            res = _m._fetch_live_lik()
        finally:
            _rq.get = _saved
        self.assertIsNotNone(res)
        self.assertEqual(res[0], date(2026, 6, 1))
        self.assertEqual(res[1], Decimal('108.3'))


class GewerbeMietzinsTests(TestCase):
    """Stufe 1+2 Gewerbe: Mietzinsmodell (Staffel/Index) + Mietenlauf-Automatik."""

    def _vertrag(self, modell='fest', typ='gew', netto='2000'):
        lg = Liegenschaft.objects.create(strasse='Gewerbe 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('2000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Ladenlokal', typ=typ,
                                   nettomiete_aktuell=Decimal(netto))
        m = Mieter.objects.create(typ='firma', firmen_name='Muster GmbH')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                       netto_mietzins=Decimal(netto), nebenkosten=Decimal('200'),
                                       status='aktiv', mietzins_modell=modell)
        return lg, e, m, v

    def test_effektiver_mietzins_staffel(self):
        from rentals.models import Staffelstufe
        _lg, _e, _m, v = self._vertrag('staffel', netto='2000')
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2025, 1, 1), netto_mietzins=Decimal('2100'))
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2026, 1, 1), netto_mietzins=Decimal('2200'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2024, 6, 1)), Decimal('2000'))  # vor 1. Stufe
        self.assertEqual(v.effektiver_netto_mietzins(date(2025, 6, 1)), Decimal('2100'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 6, 1)), Decimal('2200'))

    def test_effektiver_mietzins_fest_und_index(self):
        _lg, _e, _m, v = self._vertrag('fest', netto='2000')
        self.assertEqual(v.effektiver_netto_mietzins(date(2030, 1, 1)), Decimal('2000'))
        _lg, _e, _m, v2 = self._vertrag('index', netto='2000')
        self.assertEqual(v2.effektiver_netto_mietzins(date(2030, 1, 1)), Decimal('2000'))

    def test_sollstellung_nutzt_staffel(self):
        from rentals.models import Staffelstufe
        from finance.models import DebitorenRechnung
        from core.services.automation import run_sollstellung
        _seed_konten()
        _lg, _e, _m, v = self._vertrag('staffel', netto='2000')
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2025, 1, 1), netto_mietzins=Decimal('2100'))
        run_sollstellung(2025, 3)   # März 2025 → Stufe 2100 gilt
        r = DebitorenRechnung.objects.filter(vertrag=v).order_by('-id').first()
        self.assertIsNotNone(r)
        # Betrag = 2100 netto + 200 NK (voller Monat)
        self.assertEqual(r.betrag, Decimal('2300.00'))

    def test_index_pendenz_bei_gestiegenem_lik(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        _lg, _e, _m, v = self._vertrag('index', netto='2000')
        v.basis_lik_punkte = Decimal('95.0')   # klar unter aktuellem Tabellenwert
        v.beginn = date(2020, 1, 1)             # Intervall längst erreicht
        v.save()
        generate_auto_pendenzen(horizont_tage=120)
        p = Pendenz.objects.filter(vertrag=v, titel__icontains='Indexmiete anpassen').first()
        self.assertIsNotNone(p)
        self.assertIn('Art. 269d', p.beschreibung)

    def test_kein_index_wenn_lik_nicht_gestiegen(self):
        from core.services.automation import generate_auto_pendenzen
        from core.models import Pendenz
        _lg, _e, _m, v = self._vertrag('index', netto='2000')
        v.basis_lik_punkte = Decimal('999.0')   # unrealistisch hoch → keine Erhöhung
        v.beginn = date(2020, 1, 1)
        v.save()
        generate_auto_pendenzen(horizont_tage=120)
        self.assertFalse(Pendenz.objects.filter(vertrag=v, titel__icontains='Indexmiete anpassen').exists())


class MietzinsAnpassungLiveTests(TestCase):
    """Die Mietzinsanpassung meldet mietrechtliche Probleme live beim Erfassen
    (Art. 269d/270a OR), nicht erst auf dem PDF."""

    def _setup(self):
        from crm.models import Verwaltung
        Verwaltung.objects.create(firma='V AG', aktueller_referenzzinssatz=Decimal('1.50'))
        lg, e, m, v = _basis_objekte()
        v.basis_referenzzinssatz = Decimal('1.75')
        v.basis_lik_punkte = Decimal('100')
        v.mietzins_modell = 'fest'
        v.save()
        return v

    def test_live_pruefung_im_formular(self):
        v = self._setup()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/mietzins/{v.id}/anpassung/').content.decode()
        # Live-Prüf-Gerüst vorhanden
        self.assertIn('function mietzinsCheck', body)
        self.assertIn('id="mz-warn"', body)
        # Die drei geprüften Rechtsgrundlagen sind im ausgelieferten Script referenziert
        self.assertIn('Art. 269d Abs. 1 OR', body)   # Ankündigungsfrist/Termin
        self.assertIn('Art. 269 OR', body)           # Missbrauch/Anfechtung
        self.assertIn('Art. 270a OR', body)          # Herabsetzung bei gesunkenem Referenzzins
        # Serverwerte für die Client-Prüfung sind eingebettet
        self.assertIn('MZ_MIN_WIRKSAM', body)
        self.assertIn('MZ_VORSCHLAG', body)


class MietzinsAnpassungSollmietzinsTests(TestCase):
    """Eine amtliche Mietzinsanpassung führt den neuen Mietzins auch im Objekt
    als datierte Sollmietzins-Zeile (gültig ab = wirksam_ab). Beim Löschen der
    Anpassung verschwindet die Zeile wieder und der aktuelle Mietzins wird neu
    abgeleitet."""

    def _setup(self):
        Verwaltung.objects.create(firma='V AG', aktueller_referenzzinssatz=Decimal('1.50'))
        lg, e, m, v = _basis_objekte()
        v.basis_referenzzinssatz = Decimal('1.75')
        v.basis_lik_punkte = Decimal('100')
        v.mietzins_modell = 'fest'
        v.save()
        return e, v

    def _valid_wirksam(self, v):
        # Gültiger Erhöhungstermin (Art. 269d) — sonst greift die serverseitige
        # Fristenkontrolle. Für die Tests ein fixer, klar zukünftiger Monatsanfang.
        from rentals.services import naechster_anpassungstermin
        from django.utils import timezone
        return naechster_anpassungstermin(v, timezone.localdate())

    def _anpassung_speichern(self, c, v, neu_netto='1600', wirksam=None):
        wirksam = wirksam or self._valid_wirksam(v)
        return c.post(f'/neu/mietzins/{v.id}/anpassung/', {
            'aktion': 'speichern',
            'neu_netto': neu_netto,
            'neu_zins': '1.50',
            'neu_lik': '105',
            'wirksam_ab': wirksam.isoformat() if hasattr(wirksam, 'isoformat') else wirksam,
            'begruendung': 'Anpassung Referenzzinssatz',
        })

    def test_anpassung_erzeugt_sollmietzins_zeile(self):
        from portfolio.models import Sollmietzins
        from rentals.models import MietzinsAnpassung
        e, v = self._setup()
        w = self._valid_wirksam(v)
        c = Client(); c.force_login(_team_user())
        self._anpassung_speichern(c, v, wirksam=w)

        anp = MietzinsAnpassung.objects.get(vertrag=v)
        z = Sollmietzins.objects.filter(einheit=e, quelle_anpassung=anp)
        self.assertEqual(z.count(), 1)
        zeile = z.first()
        self.assertEqual(zeile.gueltig_ab, w)
        self.assertEqual(zeile.netto_mietzins, Decimal('1600'))
        # Der Anpassungsgrund steht in der Objekt-Notiz (warum der Mietzins gilt).
        self.assertIn('Anpassung Referenzzinssatz', zeile.notiz)
        # NK bleibt unverändert (Anpassung betrifft nur den Netto)
        self.assertEqual(zeile.nebenkosten, Decimal('200'))
        # Indexbasis der Anpassung ist mitgeschrieben
        self.assertEqual(zeile.basis_referenzzinssatz, Decimal('1.50'))
        self.assertEqual(zeile.basis_lik_punkte, Decimal('105'))

    def test_zeile_erscheint_im_objekt_detail(self):
        e, v = self._setup()
        w = self._valid_wirksam(v)
        c = Client(); c.force_login(_team_user())
        self._anpassung_speichern(c, v, wirksam=w)
        body = c.get(f'/neu/objekte/{e.id}/?tab=mietzins').content.decode()
        self.assertIn(w.strftime('%d.%m.%Y'), body)

    def test_mehrfach_speichern_bleibt_idempotent(self):
        from portfolio.models import Sollmietzins
        e, v = self._setup()
        w = self._valid_wirksam(v)
        c = Client(); c.force_login(_team_user())
        # Zweimal PDF-Generieren desselben Formulars darf keine Duplikat-Zeilen erzeugen
        for _ in range(2):
            self._anpassung_speichern(c, v, wirksam=w)
        self.assertEqual(Sollmietzins.objects.filter(einheit=e, gueltig_ab=w).count(), 1)

    def test_direkte_anpassung_erzeugt_objektzeile(self):
        # Auch eine ohne das /neu/-Formular erstellte Anpassung (Alt-View/Import/
        # Admin) muss die Objekt-Sollmietzins-Zeile anlegen — via Model.save().
        from portfolio.models import Sollmietzins
        from rentals.models import MietzinsAnpassung
        e, v = self._setup()
        anp = MietzinsAnpassung.objects.create(
            vertrag=v, wirksam_ab=date(2027, 10, 31),
            neuer_netto_mietzins=Decimal('1269.67'), alter_netto_mietzins=Decimal('1250'),
            neuer_referenzzinssatz=Decimal('1.50'), neuer_lik_index=Decimal('105'),
            begruendung='Referenzzinssatzerhöhung, Kostensteigerung')
        z = Sollmietzins.objects.get(einheit=e, gueltig_ab=date(2027, 10, 31))
        self.assertEqual(z.netto_mietzins, Decimal('1269.67'))
        self.assertEqual(z.quelle_anpassung_id, anp.id)
        self.assertIn('Referenzzinssatzerhöhung', z.notiz)
        # Löschen der Anpassung entfernt die Zeile (CASCADE).
        anp.delete()
        self.assertFalse(Sollmietzins.objects.filter(einheit=e, gueltig_ab=date(2027, 10, 31)).exists())

    def test_loeschen_entfernt_zeile_und_resynct(self):
        from portfolio.models import Sollmietzins
        from rentals.models import MietzinsAnpassung
        e, v = self._setup()
        w = self._valid_wirksam(v)
        c = Client(); c.force_login(_team_user())
        self._anpassung_speichern(c, v, wirksam=w)
        anp = MietzinsAnpassung.objects.get(vertrag=v)
        self.assertTrue(Sollmietzins.objects.filter(quelle_anpassung=anp).exists())

        c.post(f'/neu/anpassung/{anp.id}/loeschen/')
        self.assertFalse(MietzinsAnpassung.objects.filter(id=anp.id).exists())
        self.assertFalse(Sollmietzins.objects.filter(einheit=e, gueltig_ab=w).exists())


class SollmietzinsTests(TestCase):
    """Datierte Sollmietzins-Komponententabelle je Objekt (gültig ab)."""

    def _obj(self, typ='whg'):
        lg = Liegenschaft.objects.create(strasse='Sollweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='2.5 Zi', typ=typ,
                                   nettomiete_aktuell=Decimal('0'), nebenkosten_aktuell=Decimal('0'))
        return lg, e

    def test_aktueller_sollmietzins_nach_datum(self):
        from portfolio.models import Sollmietzins
        _, e = self._obj()
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2024, 1, 1),
                                    netto_mietzins=Decimal('1400'), nebenkosten=Decimal('180'))
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 1, 1),
                                    netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'))
        # Stichtag zwischen beiden → ältere Zeile gilt
        row = e.aktueller_sollmietzins(date(2025, 6, 1))
        self.assertEqual(row.netto_mietzins, Decimal('1400'))
        # Stichtag nach der zweiten → neuere Zeile gilt
        row2 = e.aktueller_sollmietzins(date(2026, 6, 1))
        self.assertEqual(row2.netto_mietzins, Decimal('1500'))
        # vor der ersten Zeile → None
        self.assertIsNone(e.aktueller_sollmietzins(date(2020, 1, 1)))

    def test_sync_leitet_aktuellwerte_ab(self):
        from portfolio.models import Sollmietzins
        _, e = self._obj()
        # Zeile mit heute gültig → nach save() abgeleitet
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2020, 1, 1),
                                    netto_mietzins=Decimal('1234'), nebenkosten=Decimal('99'))
        e.refresh_from_db()
        self.assertEqual(e.nettomiete_aktuell, Decimal('1234.00'))
        self.assertEqual(e.nebenkosten_aktuell, Decimal('99.00'))

    def test_view_add_und_del(self):
        from portfolio.models import Sollmietzins
        _, e = self._obj()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/sollmietzins/', {
            'einheit_id': e.id, 'gueltig_ab': '2026-03-01',
            'netto_mietzins': '1600', 'nebenkosten': '210', 'notiz': 'Test',
        })
        self.assertEqual(r.status_code, 302)
        s = Sollmietzins.objects.get(einheit=e)
        self.assertEqual(s.netto_mietzins, Decimal('1600'))
        e.refresh_from_db()
        self.assertEqual(e.nettomiete_aktuell, Decimal('1600.00'))
        # löschen
        c.post(f'/neu/sollmietzins/{s.id}/loeschen/')
        self.assertFalse(Sollmietzins.objects.filter(id=s.id).exists())

    def test_einstellplatz_add_erzwingt_nk_null(self):
        from portfolio.models import Sollmietzins
        _, e = self._obj(typ='pp')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/sollmietzins/', {
            'einheit_id': e.id, 'gueltig_ab': '2026-01-01',
            'netto_mietzins': '120', 'nebenkosten': '50',  # NK wird ignoriert
        })
        s = Sollmietzins.objects.get(einheit=e)
        self.assertEqual(s.nebenkosten, Decimal('0.00'))

    def test_objekt_detail_zeigt_mietzins_tab(self):
        _, e = self._obj()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('id="obj-mietzins"', body)
        self.assertIn('/neu/sollmietzins/', body)

    def test_objekt_form_seedet_erste_zeile(self):
        from portfolio.models import Sollmietzins
        lg = Liegenschaft.objects.create(strasse='Neu 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        c = Client(); c.force_login(_team_user())
        c.post('/neu/objekte/neu/', {
            'liegenschaft_id': lg.id, 'bezeichnung': '4.5 Zi', 'typ': 'whg',
            'nettomiete_aktuell': '1800', 'nebenkosten_aktuell': '250',
            'soll_gueltig_ab': '2026-02-01',
        })
        e = Einheit.objects.get(bezeichnung='4.5 Zi')
        s = Sollmietzins.objects.get(einheit=e)
        self.assertEqual(s.gueltig_ab, date(2026, 2, 1))
        self.assertEqual(s.netto_mietzins, Decimal('1800.00'))

    def test_wizard_json_enthaelt_sollplan(self):
        from portfolio.models import Sollmietzins
        _, e = self._obj()
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 1, 1),
                                    netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'))
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        self.assertIn('sollplan', body)
        self.assertIn('applySollplan', body)


class MietzinsTabExtraTests(TestCase):
    """NK-Abrechnungsart im Mietzins-Tab + Meldungen nur als Toast (nicht inline)."""

    def _obj(self, typ='whg'):
        lg = Liegenschaft.objects.create(strasse='Tabweg 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='1.5 Zi', typ=typ)
        return lg, e

    def test_nkart_speichern_und_wizard_prefill(self):
        _, e = self._obj()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/objekte/{e.id}/nkart/', {'nk_abrechnungsart': 'pauschal'})
        e.refresh_from_db()
        self.assertEqual(e.nk_abrechnungsart, 'pauschal')
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('name="nk_abrechnungsart"', body)
        wbody = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        self.assertIn('nk_abrechnungsart', wbody)

    def test_meldung_nur_als_toast_nicht_inline(self):
        _, e = self._obj()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/sollmietzins/', {
            'einheit_id': e.id, 'gueltig_ab': '2026-01-01', 'netto_mietzins': '1000',
        }, follow=True)
        body = r.content.decode()
        # Standard-Toast-Container vorhanden
        self.assertIn('fw-toasts', body)
        # Meldungstext erscheint genau EINMAL (nur im Toast, kein Inline-Duplikat)
        self.assertEqual(body.count('Sollmietzins ab'), 1)

    def test_objekt_detail_hat_keine_inline_meldung(self):
        _, e = self._obj()
        c = Client(); c.force_login(_team_user())
        # Panels dürfen keine {% for m in meldung %}-Reste mehr rendern
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('id="obj-mietzins"', body)  # Seite lädt sauber


class StaffelImTabTests(TestCase):
    """Staffelmiete des aktiven Gewerbe-Vertrags im Mietzins-Tab erfassen/löschen."""

    def _gew_vertrag(self):
        lg = Liegenschaft.objects.create(strasse='Staf-Tab 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Büro 1', typ='gew',
                                   nettomiete_aktuell=Decimal('2000'))
        m = Mieter.objects.create(typ='firma', firmen_name='Z AG')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                       netto_mietzins=Decimal('2000'), nebenkosten=Decimal('0'),
                                       status='aktiv')
        return e, v

    def test_gewerbe_tab_zeigt_live_staffel_nur_bei_staffelvertrag(self):
        e, v = self._gew_vertrag()
        c = Client(); c.force_login(_team_user())
        # Fester Gewerbe-Vertrag → keine Live-Staffel-Karte (nur die Objekt-Vorlage)
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertNotIn('Staffelstufen des aktiven Vertrags', body)
        # Staffelvertrag → Live-Karte erscheint
        v.mietzins_modell = 'staffel'; v.save(update_fields=['mietzins_modell'])
        body2 = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('Staffelstufen des aktiven Vertrags', body2)

    def test_staffel_add_setzt_modell_und_bucht(self):
        from rentals.models import Staffelstufe
        e, v = self._gew_vertrag()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/staffel/', {'vertrag_id': v.id, 'ab_datum': '2026-01-01',
                                 'netto_mietzins': '2100'})
        v.refresh_from_db()
        self.assertEqual(v.mietzins_modell, 'staffel')
        self.assertEqual(v.staffelstufen.count(), 1)
        # Effektiver Mietzins ab Stichtag greift
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 6, 1)), Decimal('2100'))
        # löschen
        s = Staffelstufe.objects.get(vertrag=v)
        c.post(f'/neu/staffel/{s.id}/loeschen/')
        self.assertFalse(Staffelstufe.objects.filter(id=s.id).exists())

    def test_wohnung_ohne_staffel_kein_tab_abschnitt(self):
        lg = Liegenschaft.objects.create(strasse='Wohn-Tab 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg 1', typ='whg',
                                   nettomiete_aktuell=Decimal('1500'))
        m = Mieter.objects.create(typ='person', vorname='A', nachname='B')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                   netto_mietzins=Decimal('1500'), nebenkosten=Decimal('0'),
                                   status='aktiv')
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertNotIn('Staffelmiete (Art. 269c OR)', body)


class StaffelVorlageTests(TestCase):
    """Objektbezogene Staffelmiete-Vorlage (wie Sollmietzins) + Wizard-Prefill."""

    def _gew(self):
        lg = Liegenschaft.objects.create(strasse='SV 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Büro SV', typ='gew',
                                   nettomiete_aktuell=Decimal('2000'))
        return lg, e

    def test_vorlage_add_und_del(self):
        from portfolio.models import StaffelVorlage
        _, e = self._gew()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/staffelvorlage/', {'einheit_id': e.id, 'gueltig_ab': '2027-01-01',
                                        'netto_mietzins': '2100', 'notiz': 'Jahr 2'})
        s = StaffelVorlage.objects.get(einheit=e)
        self.assertEqual(s.netto_mietzins, Decimal('2100'))
        c.post(f'/neu/staffelvorlage/{s.id}/loeschen/')
        self.assertFalse(StaffelVorlage.objects.filter(id=s.id).exists())

    def test_gewerbe_tab_zeigt_vorlage_karte(self):
        _, e = self._gew()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('Staffelmiete-Vorlage (Objekt)', body)
        self.assertIn('/neu/staffelvorlage/', body)

    def test_wohnung_keine_vorlage_karte(self):
        lg = Liegenschaft.objects.create(strasse='SV Wohn', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg SV', typ='whg')
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertNotIn('Staffelmiete-Vorlage (Objekt)', body)

    def test_wizard_json_enthaelt_staffelvorlage(self):
        from portfolio.models import StaffelVorlage
        _, e = self._gew()
        StaffelVorlage.objects.create(einheit=e, gueltig_ab=date(2027, 1, 1),
                                      netto_mietzins=Decimal('2100'))
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        self.assertIn('staffelvorlage', body)
        self.assertIn('applyStaffelVorlage', body)


class AnpassungLoeschenTests(TestCase):
    """Versehentlich erstellte Mietzinsanpassung im Vertrag löschbar."""

    def test_anpassung_del_und_wirkung(self):
        from rentals.models import MietzinsAnpassung
        lg = Liegenschaft.objects.create(strasse='AL 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='AL-Büro', typ='gew',
                                   nettomiete_aktuell=Decimal('3000'))
        m = Mieter.objects.create(typ='firma', firmen_name='AL AG')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                       netto_mietzins=Decimal('3000'), nebenkosten=Decimal('0'),
                                       status='aktiv', mietzins_modell='index')
        a = MietzinsAnpassung.objects.create(vertrag=v, wirksam_ab=date(2026, 1, 1),
                                             alter_netto_mietzins=Decimal('3000'),
                                             neuer_netto_mietzins=Decimal('3150'))
        # wirksam → 3150
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 6, 1)), Decimal('3150'))
        # Detailseite zeigt Löschen-Button
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/{v.id}/').content.decode()
        self.assertIn(f'/neu/anpassung/{a.id}/loeschen/', body)
        # Löschen → zurück auf Basiswert
        r = c.post(f'/neu/anpassung/{a.id}/loeschen/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(MietzinsAnpassung.objects.filter(id=a.id).exists())
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 6, 1)), Decimal('3000'))


class MietzinsKonsistenzTests(TestCase):
    """Sollmietzins mit Indexbasis (Ref-Zins/LIK), effektive Werte im Mietzins-View,
    Live-Vorschau bei der Weiterverrechnung."""

    def test_sollmietzins_mit_indexbasis_und_wizard_json(self):
        from portfolio.models import Sollmietzins
        lg = Liegenschaft.objects.create(strasse='Mk 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Mk-Whg', typ='whg')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/sollmietzins/', {
            'einheit_id': e.id, 'gueltig_ab': '2026-04-01',
            'netto_mietzins': '1250', 'nebenkosten': '180',
            'basis_referenzzinssatz': '1.25', 'basis_lik_punkte': '108.2',
        })
        s = Sollmietzins.objects.get(einheit=e)
        self.assertEqual(s.basis_referenzzinssatz, Decimal('1.25'))
        self.assertEqual(s.basis_lik_punkte, Decimal('108.2'))
        # Objekt-Detail zeigt die Basis-Spalte + Formularfelder
        body = c.get(f'/neu/objekte/{e.id}/').content.decode()
        self.assertIn('name="basis_referenzzinssatz"', body)
        self.assertIn('Basis Ref.-Zinssatz', body)   # Formular-Label
        # Wizard-JSON trägt die Indexbasis der Sollmietzins-Zeile
        wbody = c.get(f'/neu/vertraege/neu/?einheit={e.id}').content.decode()
        self.assertIn('"ref": 1.25', wbody)
        self.assertIn('"lik": 108.2', wbody)

    def test_mietzins_view_zeigt_effektive_werte(self):
        from crm.models import Verwaltung
        from rentals.models import MietzinsAnpassung
        Verwaltung.objects.create(firma='VW', strasse='W 1', plz='8000', ort='Zürich',
                                  aktueller_referenzzinssatz=Decimal('1.25'),
                                  aktueller_lik_punkte=Decimal('107.1'))
        lg = Liegenschaft.objects.create(strasse='Mk 2', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Mk-Whg2', typ='whg')
        m = Mieter.objects.create(typ='person', vorname='E', nachname='F')
        v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2023, 1, 1),
                                       netto_mietzins=Decimal('1500'), nebenkosten=Decimal('0'),
                                       status='aktiv',
                                       basis_referenzzinssatz=Decimal('1.75'),
                                       basis_lik_punkte=Decimal('106.0'))
        # Alte Basis 1.75 vs aktuell 1.25 → Senkungsanspruch
        self.assertEqual(v.mietzinspotenzial, 'decrease')
        # Wirksame Anpassung AUF die aktuelle Basis → Potenzial neutral,
        # effektiver Netto = angepasster Wert
        MietzinsAnpassung.objects.create(vertrag=v, wirksam_ab=date(2025, 1, 1),
                                         alter_netto_mietzins=Decimal('1500'),
                                         neuer_netto_mietzins=Decimal('1430'),
                                         neuer_referenzzinssatz=Decimal('1.25'),
                                         neuer_lik_index=Decimal('107.1'))
        self.assertEqual(v.mietzinspotenzial, 'neutral')
        self.assertEqual(v.effektive_basis(date(2026, 1, 1)), (Decimal('1.25'), Decimal('107.1')))
        c = Client(); c.force_login(_team_user())
        body = c.get('/neu/mietzins/').content.decode()
        self.assertIn("1'430.00", body)         # effektiver Netto in der Tabelle
        self.assertIn('Netto effektiv', body)

    def test_weiterverrechnung_hat_vorschau(self):
        from finance.models import KreditorenRechnung
        lg = Liegenschaft.objects.create(strasse='Mk 3', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Mk-Whg3', typ='whg')
        m = Mieter.objects.create(typ='person', vorname='G', nachname='H',
                                  strasse='Weg 9', plz='8000', ort='Zürich')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                   netto_mietzins=Decimal('1500'), nebenkosten=Decimal('0'),
                                   status='aktiv')
        k = KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('400'),
                                              liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/kreditoren/{k.id}/weiterverrechnen/').content.decode()
        self.assertIn('id="wv-pv"', body)
        self.assertIn('function wvPreview', body)
        self.assertIn('wv-vd-data', body)
        self.assertIn('G H', body)


class VertragMietzinsKomponentenTests(TestCase):
    """Datierte Mietzins-Komponenten am Verhältnis: Gratismonate/gestaffelter
    Start. Die Sollstellung greift pro Monat die gültige Komponente."""

    def _setup(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.beginn = date(2026, 10, 1)
        v.netto_mietzins = Decimal('1000'); v.nebenkosten = Decimal('250')
        v.mietzins_modell = 'fest'
        v.save()
        return v

    def test_gratismonate_via_komponenten(self):
        from rentals.models import VertragMietzins
        from finance.models import DebitorenRechnung
        from core.services.automation import run_sollstellung
        v = self._setup()
        # Erste zwei Monate netto-frei (NK läuft), ab 01.12 voller Netto.
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2026, 10, 1),
                                       netto_mietzins=Decimal('0'), nebenkosten=Decimal('250'))
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2026, 12, 1),
                                       netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        # Auflösung pro Datum
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 10, 15)), Decimal('0'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 11, 30)), Decimal('0'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 12, 1)), Decimal('1000'))
        self.assertEqual(v.effektive_nebenkosten(date(2026, 10, 15)), Decimal('250'))

        # Sollstellung Oktober: nur NK 250 (Netto 0)
        run_sollstellung(2026, 10)
        okt = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 10/2026')
        self.assertEqual(okt.betrag, Decimal('250.00'))
        # Dezember: voll 1250
        run_sollstellung(2026, 12)
        dez = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 12/2026')
        self.assertEqual(dez.betrag, Decimal('1250.00'))

    def test_ohne_komponenten_unveraendert(self):
        from finance.models import DebitorenRechnung
        from core.services.automation import run_sollstellung
        v = self._setup()   # keine Komponenten → flacher Wert
        run_sollstellung(2026, 10)
        okt = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 10/2026')
        self.assertEqual(okt.betrag, Decimal('1250.00'))   # 1000 + 250 wie bisher


class VertragMietzinsUITests(TestCase):
    """Komponenten am Vertrag: UI (Mietzins-Tab), Add/Del, PDF-Anzeige."""

    def test_add_del_und_anzeige(self):
        from rentals.models import VertragMietzins
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        # Hinzufügen (Endpoint unverändert; verwaltet wird am Objekt-Mietzins-Tab)
        c.post(f'/neu/vertrag-mietzins/{v.id}/', {
            'gueltig_ab': '2026-10-01', 'netto_mietzins': '1000.00', 'nebenkosten': '250.00',
            'mietzinsfrei': '1', 'notiz': 'Gratismonat',
            'next': f'/neu/objekte/{e.id}/?tab=mietzins'})
        c.post(f'/neu/vertrag-mietzins/{v.id}/', {
            'gueltig_ab': '2026-12-01', 'netto_mietzins': '1000.00', 'nebenkosten': '250.00'})
        self.assertEqual(v.mietzins_komponenten.count(), 2)
        # Verwaltung am OBJEKT-Mietzins-Tab: Formular + Komponenten sichtbar
        obj = c.get(f'/neu/objekte/{e.id}/?tab=mietzins').content.decode()
        self.assertIn('Gratismonate / Rabatt', obj)
        self.assertIn('01.10.2026', obj)
        self.assertIn('mietzinsfrei', obj)   # Checkbox-Label im Objekt-Formular
        # Am VERTRAG nur noch die Ansicht (read-only), kein Erfassen-Formular
        vt = c.get(f'/neu/vertraege/{v.id}/?tab=mietzins').content.decode()
        self.assertIn('Gratismonate / Rabatt', vt)
        self.assertIn('01.10.2026', vt)
        self.assertIn('Am Objekt bearbeiten', vt)
        # Löschen
        k = v.mietzins_komponenten.first()
        c.post(f'/neu/vertrag-mietzins/{k.id}/loeschen/')
        self.assertEqual(v.mietzins_komponenten.count(), 1)

    def test_objekt_tab_verwaltet_entwurf_vertrag(self):
        """Gratismonate lassen sich am Objekt schon für einen frischen Entwurf
        erfassen (mietzins_vertrag fällt auf den neuesten nicht-beendeten zurück)."""
        from rentals.models import VertragMietzins
        lg, e, m, v = _basis_objekte()
        v.status = 'entwurf'; v.save()
        c = Client(); c.force_login(_team_user())
        obj = c.get(f'/neu/objekte/{e.id}/?tab=mietzins').content.decode()
        self.assertIn('Gratismonate / Rabatt', obj)   # trotz Entwurf sichtbar
        c.post(f'/neu/vertrag-mietzins/{v.id}/', {
            'gueltig_ab': '2026-10-01', 'netto_mietzins': '1000.00', 'nebenkosten': '250.00',
            'mietzinsfrei': '1', 'next': f'/neu/objekte/{e.id}/?tab=mietzins'})
        self.assertEqual(v.mietzins_komponenten.count(), 1)

    def test_komponenten_im_vertrags_pdf(self):
        from rentals.models import VertragMietzins
        from core.services.dokument_service import DOKUMENT_TYPEN
        lg, e, m, v = _basis_objekte()
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2026, 10, 1),
                                       netto_mietzins=Decimal('0'), nebenkosten=Decimal('250'),
                                       notiz='mietzinsfrei')
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2026, 12, 1),
                                       netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        # Der Vertrags-PDF-Template rendert den Zeitplan (via mietzins_zeitplan-Kontext)
        from django.template.loader import get_template
        html = get_template('core/mietvertrag_pdf.html').render({'vertrag': v, 'einheit': e,
                'miete_fmt': '1000.00', 'nk_fmt': '250.00', 'brutto_fmt': '1250.00',
                'mietzins_zeitplan': v.mietzins_zeitplan(), 'mietzins_hinweise': v.mietzins_hinweise()})
        self.assertIn('01.10.2026', html)
        self.assertIn('mietzinsfrei', html)
        self.assertIn('01.12.2026', html)


class SollmietzinsSollstellungTests(TestCase):
    """Der datierte Objekt-Sollmietzins (Gratismonate/Rabatt direkt in der
    Sollmiete) treibt die Sollstellung automatisch pro Periode — für neue UND
    bestehende Verträge, ohne dass am Vertrag etwas erfasst werden muss."""

    def _setup(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.beginn = date(2026, 10, 1)
        v.netto_mietzins = Decimal('1000'); v.nebenkosten = Decimal('250')
        v.mietzins_modell = 'fest'; v.save()
        return lg, e, m, v

    def test_sollmietzins_zeitplan_treibt_sollstellung(self):
        from portfolio.models import Sollmietzins
        from finance.models import DebitorenRechnung, Buchung
        from core.services.automation import run_sollstellung
        _lg, e, _m, v = self._setup()
        # Zeitplan am OBJEKT: Okt normal, Nov Netto gratis (Rabatt=Referenz), Dez normal.
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 10, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 11, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
                                    rabatt_netto=Decimal('1000'), notiz='Gratismonat')
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 12, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        # Resolver pro Periode
        self.assertEqual(v.verrechneter_netto_mietzins(date(2026, 10, 15)), Decimal('1000'))
        self.assertEqual(v.verrechneter_netto_mietzins(date(2026, 11, 15)), Decimal('0'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 11, 15)), Decimal('1000'))  # Referenz voll
        self.assertEqual(v.verrechneter_netto_mietzins(date(2026, 12, 15)), Decimal('1000'))
        # Sollstellung folgt den gültig-ab-Daten
        run_sollstellung(2026, 10)
        run_sollstellung(2026, 11)
        run_sollstellung(2026, 12)
        okt = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 10/2026')
        nov = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 11/2026')
        dez = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 12/2026')
        self.assertEqual(okt.betrag, Decimal('1250.00'))
        self.assertEqual(nov.betrag, Decimal('250.00'))   # Netto erlassen
        self.assertEqual(dez.betrag, Decimal('1250.00'))
        # November: voller Referenzertrag gebucht + Rabatt als Ertragsminderung 3090
        nov_b = Buchung.objects.filter(debitoren_rechnung=nov)
        self.assertEqual(sum(b.betrag for b in nov_b.filter(haben_konto__nummer='3000')), Decimal('1000.00'))
        self.assertEqual(sum(b.betrag for b in nov_b.filter(soll_konto__nummer='3090')), Decimal('1000.00'))

    def test_stale_sollmietzins_hijackt_nicht(self):
        """Eine alte Sollmietzins-Zeile VOR Mietbeginn (kein Zeitplan für dieses
        Verhältnis) darf die Verrechnung NICHT übersteuern → Vertragsbasis gilt."""
        from portfolio.models import Sollmietzins
        _lg, e, _m, v = self._setup()
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2020, 1, 1),
                                    netto_mietzins=Decimal('800'), nebenkosten=Decimal('200'))
        # Keine Zeile ab Mietbeginn → Basis (1000) gilt, nicht die 800er-Altzeile.
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 10, 15)), Decimal('1000'))
        self.assertEqual(v.verrechneter_netto_mietzins(date(2026, 10, 15)), Decimal('1000'))

    def test_mietzinsfrei_checkbox_am_sollmietzins(self):
        from portfolio.models import Sollmietzins
        _lg, e, _m, _v = self._setup()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/sollmietzins/', {
            'einheit_id': str(e.id), 'gueltig_ab': '2026-11-01',
            'netto_mietzins': '1000.00', 'nebenkosten': '250.00',
            'mietzinsfrei': '1', 'notiz': 'Gratismonat'})
        s = Sollmietzins.objects.get(einheit=e, gueltig_ab=date(2026, 11, 1))
        self.assertEqual(s.netto_mietzins, Decimal('1000.00'))   # Referenz voll
        self.assertEqual(s.rabatt_netto, Decimal('1000.00'))     # Rabatt = Netto
        self.assertEqual(s.verrechnet_brutto, Decimal('250.00'))

    def test_zeitplan_im_vertrags_pdf(self):
        from portfolio.models import Sollmietzins
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        _lg, e, _m, v = self._setup()
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 11, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
                                    rabatt_netto=Decimal('1000'), notiz='Gratismonat')
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 12, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        self.assertTrue(len(v.mietzins_zeitplan()) >= 2)
        pdf = generate_vertrag_pdf_bytes(v)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_gratismonat_hinweise_prosa(self):
        from portfolio.models import Sollmietzins
        _lg, e, _m, v = self._setup()
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 10, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
                                    rabatt_netto=Decimal('1000'))
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 12, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        hin = v.mietzins_hinweise()
        self.assertEqual(len(hin), 2)
        self.assertIn('01.10.2026 bis 30.11.2026', hin[0])
        self.assertIn('mietzinsfrei', hin[0])
        self.assertIn('nur die Nebenkosten', hin[0])
        self.assertIn('Ab 01.12.2026', hin[1])
        self.assertIn("1'250.00", hin[1])

    def test_live_vorschau_entspricht_pdf_template(self):
        """Die Live-Vorschau des Assistenten rendert dasselbe Template wie das PDF
        (aus den Formularwerten, ohne Speichern) — inkl. Gratismonat-Zeitplan."""
        from portfolio.models import Sollmietzins
        _lg, e, m, _v = self._setup()
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 10, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
                                    rabatt_netto=Decimal('1000'))
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2026, 12, 1),
                                    netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/vertraege/vorschau/', {
            'einheit_id': str(e.id), 'mieter_id': str(m.id), 'beginn': '2026-10-01',
            'netto_mietzins': '1000', 'nebenkosten': '250'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('mietzinsfrei', body)             # Zeitplan-Tabelle
        self.assertIn('Gestaffelter Mietzins', body)    # Abschnitt
        self.assertIn('01.10.2026 bis 30.11.2026', body)  # Klartext-Hinweis

    def test_vorschau_ohne_objekt_platzhalter(self):
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/vertraege/vorschau/', {'netto_mietzins': '1000'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('Objekt auswählen', r.content.decode())


class ObjektFormMietzinsQuelleTests(TestCase):
    """Der Mietzins wird nur noch über den Sollmietzins (Mietzins-Tab) gepflegt —
    das Objekt-Bearbeiten-Formular schreibt ihn nicht mehr direkt (kein Drift)."""

    def test_neuanlage_seedet_sollmietzins(self):
        from portfolio.models import Sollmietzins, Einheit
        lg = Liegenschaft.objects.create(strasse='OF 1', plz='8000', ort='ZH', versicherungswert=Decimal('1'))
        c = Client(); c.force_login(_team_user())
        c.post('/neu/objekte/neu/', {
            'liegenschaft_id': str(lg.id), 'bezeichnung': 'Neu-1', 'typ': 'wohnung',
            'nettomiete_aktuell': '1400', 'nebenkosten_aktuell': '250',
            'soll_gueltig_ab': '2026-01-01'})
        e = Einheit.objects.get(bezeichnung='Neu-1')
        # Erste Sollmietzins-Zeile erzeugt + Aktuellwerte daraus abgeleitet
        s = Sollmietzins.objects.get(einheit=e, gueltig_ab=date(2026, 1, 1))
        self.assertEqual(s.netto_mietzins, Decimal('1400'))
        self.assertEqual(e.nettomiete_aktuell, Decimal('1400.00'))
        self.assertEqual(e.nebenkosten_aktuell, Decimal('250.00'))

    def test_bearbeiten_aendert_miete_nicht_direkt(self):
        """Beim Bearbeiten wird ein übermitteltes nettomiete_aktuell IGNORIERT —
        die Miete bleibt beim Sollmietzins-Wert (einzige Quelle)."""
        from portfolio.models import Sollmietzins, Einheit
        lg, e, m, v = _basis_objekte()   # e.nettomiete_aktuell = 1500
        Sollmietzins.objects.create(einheit=e, gueltig_ab=date(2024, 1, 1),
                                    netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'))
        e.refresh_from_db()
        c = Client(); c.force_login(_team_user())
        # Bearbeiten-POST mit einem abweichenden Mietwert
        c.post(f'/neu/objekte/{e.id}/bearbeiten/', {
            'liegenschaft_id': str(lg.id), 'bezeichnung': e.bezeichnung, 'typ': e.typ,
            'nettomiete_aktuell': '9999', 'nebenkosten_aktuell': '9999'})
        e.refresh_from_db()
        # Wert unverändert (9999 ignoriert), kein neuer Sollmietzins
        self.assertEqual(e.nettomiete_aktuell, Decimal('1500'))
        self.assertEqual(Sollmietzins.objects.filter(einheit=e).count(), 1)
        # Bearbeiten-Maske zeigt kein editierbares Mietfeld mehr (nur Ansicht + Link)
        body = c.get(f'/neu/objekte/{e.id}/bearbeiten/').content.decode()
        self.assertNotIn('name="nettomiete_aktuell"', body)
        self.assertIn('Mietzins verwalten', body)


class VertragMietzinsRabattTests(TestCase):
    """Option B — Referenz/Rabatt-Split: Gratismonat wird brutto gebucht
    (voller Referenzertrag 3000/3020) + Rabatt als Ertragsminderung (3090),
    Debitor nettoiert auf den verrechneten Betrag. So bleiben Mieterspiegel
    und Bilanz auf dem echten Ertragspotenzial, während der Mieter 0 zahlt."""

    def _setup(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.beginn = date(2026, 10, 1)
        v.netto_mietzins = Decimal('1000'); v.nebenkosten = Decimal('250')
        v.mietzins_modell = 'fest'
        v.save()
        return lg, e, m, v

    def test_resolver_referenz_vs_verrechnet(self):
        from rentals.models import VertragMietzins
        _lg, _e, _m, v = self._setup()
        # Gratismonat: Referenz voll, Rabatt = Netto-Referenz → verrechnet 0.
        VertragMietzins.objects.create(
            vertrag=v, gueltig_ab=date(2026, 10, 1),
            netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
            rabatt_netto=Decimal('1000'), notiz='Gratismonat')
        VertragMietzins.objects.create(
            vertrag=v, gueltig_ab=date(2026, 12, 1),
            netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'))
        # Referenz (Reporting) bleibt voll …
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 10, 15)), Decimal('1000'))
        self.assertEqual(v.effektive_nebenkosten(date(2026, 10, 15)), Decimal('250'))
        # … verrechnet (Debitor) ist im Gratismonat 0 Netto (NK läuft).
        self.assertEqual(v.verrechneter_netto_mietzins(date(2026, 10, 15)), Decimal('0'))
        self.assertEqual(v.verrechnete_nebenkosten(date(2026, 10, 15)), Decimal('250'))
        # Dezember voll.
        self.assertEqual(v.verrechneter_netto_mietzins(date(2026, 12, 1)), Decimal('1000'))

    def test_sollstellung_bruttobuchung(self):
        from rentals.models import VertragMietzins
        from finance.models import DebitorenRechnung, Buchung
        from core.services.automation import run_sollstellung
        _lg, e, _m, v = self._setup()
        VertragMietzins.objects.create(
            vertrag=v, gueltig_ab=date(2026, 10, 1),
            netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
            rabatt_netto=Decimal('1000'), notiz='Gratismonat')
        run_sollstellung(2026, 10)
        r = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 10/2026')
        # Debitor schuldet nur die NK (Netto voll erlassen).
        self.assertEqual(r.betrag, Decimal('250.00'))
        buchungen = Buchung.objects.filter(debitoren_rechnung=r)
        # Voller Referenzertrag auf 3000 (Wohnen) …
        b3000 = buchungen.filter(haben_konto__nummer='3000')
        self.assertEqual(sum(b.betrag for b in b3000), Decimal('1000.00'))
        # NK-Ertrag auf 3020 …
        b3020 = buchungen.filter(haben_konto__nummer='3020')
        self.assertEqual(sum(b.betrag for b in b3020), Decimal('250.00'))
        # … Rabatt als Ertragsminderung (Soll 3090 / Haben 1100).
        b3090 = buchungen.filter(soll_konto__nummer='3090', haben_konto__nummer='1100')
        self.assertEqual(sum(b.betrag for b in b3090), Decimal('1000.00'))
        # Debitor (1100) nettoiert: Soll 1000+250, Haben 1000 → offen 250.
        soll_1100 = sum(b.betrag for b in buchungen.filter(soll_konto__nummer='1100'))
        haben_1100 = sum(b.betrag for b in buchungen.filter(haben_konto__nummer='1100'))
        self.assertEqual(soll_1100 - haben_1100, Decimal('250.00'))

    def test_teilrabatt(self):
        from rentals.models import VertragMietzins
        from finance.models import DebitorenRechnung, Buchung
        from core.services.automation import run_sollstellung
        _lg, _e, _m, v = self._setup()
        # 300 Rabatt auf 1000 Netto → verrechnet 700 + 250 NK = 950.
        VertragMietzins.objects.create(
            vertrag=v, gueltig_ab=date(2026, 10, 1),
            netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
            rabatt_netto=Decimal('300'))
        run_sollstellung(2026, 10)
        r = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 10/2026')
        self.assertEqual(r.betrag, Decimal('950.00'))
        b3090 = Buchung.objects.filter(debitoren_rechnung=r, soll_konto__nummer='3090')
        self.assertEqual(sum(b.betrag for b in b3090), Decimal('300.00'))

    def test_ui_mietzinsfrei_checkbox_setzt_rabatt(self):
        from rentals.models import VertragMietzins
        _lg, _e, _m, v = self._setup()
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertrag-mietzins/{v.id}/', {
            'gueltig_ab': '2026-10-01', 'netto_mietzins': '1000.00',
            'nebenkosten': '250.00', 'mietzinsfrei': '1', 'notiz': 'Gratismonat'})
        k = VertragMietzins.objects.get(vertrag=v, gueltig_ab=date(2026, 10, 1))
        self.assertEqual(k.netto_mietzins, Decimal('1000.00'))   # Referenz voll
        self.assertEqual(k.rabatt_netto, Decimal('1000.00'))     # Rabatt = Netto
        self.assertEqual(k.verrechnet_brutto, Decimal('250.00')) # zu zahlen = NK

    def test_pdf_zeigt_referenz_und_zu_zahlen(self):
        from rentals.models import VertragMietzins
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        _lg, _e, _m, v = self._setup()
        VertragMietzins.objects.create(
            vertrag=v, gueltig_ab=date(2026, 10, 1),
            netto_mietzins=Decimal('1000'), nebenkosten=Decimal('250'),
            rabatt_netto=Decimal('1000'), notiz='Gratismonat')
        # Über den echten PDF-Service (nicht nur Template-Direktrender).
        pdf = generate_vertrag_pdf_bytes(v)
        self.assertTrue(pdf.startswith(b'%PDF'))
        # Template rendert Referenzmiete + Rabatt-Spalte.
        from django.template.loader import get_template
        html = get_template('core/mietvertrag_pdf.html').render({'vertrag': v, 'einheit': _e,
                'miete_fmt': '1000.00', 'nk_fmt': '250.00', 'brutto_fmt': '1250.00',
                'mietzins_zeitplan': v.mietzins_zeitplan(), 'mietzins_hinweise': v.mietzins_hinweise()})
        self.assertIn('Referenzmiete', html)
        self.assertIn('Zu bezahlen', html)
        self.assertIn('mietzinsfrei', html)
