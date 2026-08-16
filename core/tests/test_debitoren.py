"""Testmodul debitoren — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 15 Klassen, unveraendert uebernommen."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from ._helfer import (_test_organisation,
    _team_user, _basis_objekte, _seed_konten, _sig_bytes, _heute, Mieter,
    Eigentuemer, Organisation, Liegenschaft, Einheit, Mietvertrag, User)



class MieterkontoTests(TestCase):
    def test_saldo_und_reihenfolge(self):
        from finance.models import DebitorenRechnung, Zahlungseingang
        from core.services.mieterkonto import berechne_mieterkonto
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(vertrag=v, titel='Miete Jan', betrag=Decimal('1700'),
                                         datum=date(2025, 1, 1), status='offen')
        DebitorenRechnung.objects.create(vertrag=v, titel='Miete Feb', betrag=Decimal('1700'),
                                         datum=date(2025, 2, 1), status='offen')
        Zahlungseingang.objects.create(vertrag=v, betrag=Decimal('1700'),
                                       datum_eingang=date(2025, 1, 15), status='verbucht')
        zeilen, saldo = berechne_mieterkonto(m)
        self.assertEqual(len(zeilen), 3)
        self.assertEqual(saldo, Decimal('1700'))  # 1700+1700-1700
        # laufender Saldo nach der Zahlung = 0
        self.assertEqual(zeilen[1]['saldo'], Decimal('0'))

    def test_pdf_view_team_und_mieter(self):
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(vertrag=v, titel='Miete', betrag=Decimal('1700'),
                                         datum=date(2025, 1, 1), status='offen')
        # Team
        tu = _team_user()
        tc = Client(); tc.force_login(tu)
        r = tc.get(f'/neu/personen/{m.id}/kontoauszug/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        # Mieter
        u = User.objects.create_user(username='mk_mieter', password='x')
        m.benutzer = u; m.save()
        mc = Client(); mc.force_login(u)
        r2 = mc.get('/mieter/kontoauszug/')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2['Content-Type'], 'application/pdf')


class SollstellungTests(TestCase):
    def test_gekuendigter_vertrag_wird_bis_ende_fakturiert(self):
        """Ein gekündigter Vertrag schuldet Miete bis zum Vertragsende. Der
        status='aktiv'-Filter liess ihn durchfallen — die Miete der
        Kündigungsfrist wurde nie gestellt (stiller Geldverlust)."""
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _lg, _e, _m, v = _basis_objekte()   # Vertrag ab 2024-01-01
        v.status = 'gekuendigt'
        v.ende = date(2024, 3, 31)          # Ende im Stellungsmonat
        v.save()
        # März: Ende >= Monatsanfang → volle Miete geschuldet
        self.assertEqual(run_sollstellung(2024, 3), 1)
        self.assertTrue(DebitorenRechnung.objects.filter(
            titel='Miete & NK 03/2024', vertrag=v).exists())
        # April: Vertrag ist beendet → nichts mehr
        self.assertEqual(run_sollstellung(2024, 4), 0)

    def test_entwurf_und_archiviert_werden_nicht_fakturiert(self):
        """Gegenstück: Nur aktiv/gekündigt zählen — ein Entwurf oder ein
        archivierter Vertrag darf keine Rechnung erzeugen."""
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _lg, _e, _m, v = _basis_objekte()
        for status in ('entwurf', 'archiviert'):
            v.status = status; v.ende = None; v.save()
            DebitorenRechnung.objects.all().delete()
            self.assertEqual(run_sollstellung(2024, 5), 0,
                             f'Status «{status}» wurde fakturiert')

    def test_erstellt_und_idempotent(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _basis_objekte()  # Vertrag ab 2024-01-01, 1500+200
        n1 = run_sollstellung(2024, 3)
        self.assertEqual(n1, 1)
        r = DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')
        self.assertEqual(r.betrag, Decimal('1700.00'))
        # zweiter Lauf erzeugt nichts Neues
        n2 = run_sollstellung(2024, 3)
        self.assertEqual(n2, 0)
        self.assertEqual(DebitorenRechnung.objects.filter(titel='Miete & NK 03/2024').count(), 1)

    def test_pro_rata_bei_einzug_mitte_monat(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='PR 1', plz='8000', ort='ZH', versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='2 Zi', typ='wohnung')
        m = Mieter.objects.create(typ='person', nachname='Prorata')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 3, 16),
                                   netto_mietzins=Decimal('3100'), nebenkosten=Decimal('0'), status='aktiv')
        run_sollstellung(2024, 3)   # März = 31 Tage, ab 16. -> 16/31
        r = DebitorenRechnung.objects.get(vertrag__mieter=m)
        self.assertEqual(r.betrag, Decimal('1600.00'))   # 3100 * 16/31 = 1600.00


class MahnlaufTests(TestCase):
    def test_verzugszins_art104(self):
        from core.services.automation import verzugszins
        # 12'000 × 5% × 360/360 = 600.00
        self.assertEqual(verzugszins(Decimal('12000'), 360), Decimal('600.00'))
        # 10'000 × 5% × 90/360 = 125.00
        self.assertEqual(verzugszins(Decimal('10000'), 90), Decimal('125.00'))
        self.assertEqual(verzugszins(Decimal('1000'), 0), Decimal('0.00'))

    def test_mahnstufe_nach_tagen(self):
        from core.services.automation import _stufe_fuer_tage
        self.assertIsNone(_stufe_fuer_tage(13))
        self.assertEqual(_stufe_fuer_tage(14), 1)
        self.assertEqual(_stufe_fuer_tage(30), 2)
        self.assertEqual(_stufe_fuer_tage(60), 3)

    def _ueberfaellig(self, tage):
        from django.utils import timezone
        from finance.models import DebitorenRechnung
        _lg, _e, _m, v = _basis_objekte()
        faellig = timezone.localdate() - timedelta(days=tage)
        return DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=v.einheit.liegenschaft, titel='Miete 01',
            betrag=Decimal('1700'), datum=faellig, faellig_am=faellig, status='offen')

    def test_mahnung_und_gebuehr(self):
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung, DebitorenRechnung
        r = self._ueberfaellig(40)   # -> Stufe 2, Gebühr 20
        res = run_mahnlauf(send_email=False)
        self.assertEqual(res['gemahnt'], 1)
        m = Mahnung.objects.get(debitoren_rechnung=r)
        self.assertEqual(m.stufe, 2)
        self.assertEqual(m.gebuehr, Decimal('20.00'))
        # Mahngebühr als eigener Debitor
        self.assertTrue(DebitorenRechnung.objects.filter(titel__icontains='Mahngebühr').exists())

    def test_idempotent_gleiche_stufe(self):
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung
        self._ueberfaellig(40)
        run_mahnlauf(send_email=False)
        res2 = run_mahnlauf(send_email=False)
        self.assertEqual(res2['gemahnt'], 0)
        self.assertEqual(Mahnung.objects.count(), 1)

    def test_mit_verzugszins(self):
        from core.services.automation import run_mahnlauf
        from finance.models import DebitorenRechnung
        self._ueberfaellig(90)   # 90 Tage überfällig -> Stufe 3
        res = run_mahnlauf(send_email=False, mit_zins=True)
        self.assertGreater(res['zins'], Decimal('0.00'))
        self.assertTrue(DebitorenRechnung.objects.filter(titel__icontains='Verzugszins').exists())

    # ---------- Mahnung gehört in die Vertrags-Akte ----------
    # Gemeldet: «Vertrag → Dokumente → Mahnung erstellt aber nirgends
    # dokumentiert.» Historie und Gebühr wurden gebucht, das Schreiben selbst
    # existierte nur als Download im Moment des Klicks. Bei Art. 257d OR hängt
    # an der Mahnung die Kündigungsandrohung — ohne Beleg ist im Streitfall
    # nicht nachweisbar, WAS zugestellt wurde.

    def _mahn_dokumente(self, vertrag=None):
        from rentals.models import Dokument
        qs = Dokument.objects.filter(bezeichnung__icontains='Mahnung')
        return list(qs.filter(vertrag=vertrag) if vertrag else qs)

    def test_mahnlauf_legt_die_mahnung_in_die_akte(self):
        from core.services.automation import run_mahnlauf
        r = self._ueberfaellig(40)
        run_mahnlauf(send_email=False)
        dok = self._mahn_dokumente(r.vertrag)
        self.assertEqual(len(dok), 1, "Mahnlauf legte kein Dokument am Vertrag ab")
        self.assertIn('2. Mahnung', dok[0].bezeichnung)
        self.assertTrue(dok[0].datei)

    def test_mahnung_erfassen_legt_die_mahnung_in_die_akte(self):
        r = self._ueberfaellig(40)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': r.id, 'stufe': 1}, follow=True)
        dok = self._mahn_dokumente(r.vertrag)
        self.assertEqual(len(dok), 1, "«Erfassen» legte kein Dokument am Vertrag ab")
        self.assertIn('1. Mahnung', dok[0].bezeichnung)

    def test_mahnung_pdf_button_legt_die_mahnung_in_die_akte(self):
        r = self._ueberfaellig(40)
        c = Client(); c.force_login(_team_user())
        antwort = c.get(f'/vertrag/{r.vertrag_id}/mahnung/')
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(len(self._mahn_dokumente(r.vertrag)), 1)

    def test_mahnung_wird_am_selben_tag_nicht_dupliziert(self):
        """Zweimal klicken darf die Akte nicht aufblähen — dieselbe Stufe am
        selben Tag überschreibt (dedup), eine höhere Stufe bekommt ein eigenes
        Dokument."""
        r = self._ueberfaellig(40)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': r.id, 'stufe': 1}, follow=True)
        c.get(f'/vertrag/{r.vertrag_id}/mahnung/')
        c.get(f'/vertrag/{r.vertrag_id}/mahnung/')
        c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': r.id, 'stufe': 2}, follow=True)
        titel = sorted(d.bezeichnung for d in self._mahn_dokumente(r.vertrag))
        # «1. Mahnung», «2. Mahnung» und die stufenlose «Mahnung» des PDF-Buttons
        self.assertEqual(len(titel), 3, f"unerwartete Dokumente: {titel}")

    def test_ablage_scheitert_lautlos_und_bricht_den_mahnlauf_nicht(self):
        """Die Ablage ist Beiwerk: Geht die PDF-Erzeugung schief, muss der
        gebuchte Mahnschritt trotzdem stehen bleiben."""
        from unittest.mock import patch
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung
        r = self._ueberfaellig(40)
        with patch('core.services.ablage.ablage_mahnung', side_effect=RuntimeError('kaputt')):
            res = run_mahnlauf(send_email=False)
        self.assertEqual(res['gemahnt'], 1)
        self.assertTrue(Mahnung.objects.filter(debitoren_rechnung=r).exists())


class FinanzCockpitTests(TestCase):
    """Finanz-Cockpit: EIN Arbeitskorb in Prozessreihenfolge + Monatsabschluss-Checkliste."""

    def test_leerer_arbeitskorb(self):
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/finanzen/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Finanz-Cockpit')
        self.assertContains(r, 'Arbeitskorb')
        self.assertContains(r, 'Alle Finanzaufgaben erledigt')

    def test_offene_debitoren_und_kreditoren_im_korb(self):
        from finance.models import DebitorenRechnung, KreditorenRechnung
        from finance.booking import konto as _k
        lg, e, m, v = _basis_objekte()
        # überfällige Forderung
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete alt', betrag=Decimal('1700'),
            datum=date(2024, 1, 1), faellig_am=date(2024, 1, 1), status='offen')
        # Kreditor neu (zur Freigabe) + freigegeben (zur Zahlung)
        KreditorenRechnung.objects.create(lieferant='Neu AG', betrag=Decimal('200'),
                                          status='neu', liegenschaft=lg, konto=_k('4000'))
        KreditorenRechnung.objects.create(lieferant='Frei AG', betrag=Decimal('300'),
                                          status='freigegeben', liegenschaft=lg, konto=_k('4000'))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/finanzen/')
        self.assertContains(r, 'Zahlungseingänge abgleichen')
        self.assertContains(r, 'Eingangsrechnungen freigeben')
        self.assertContains(r, 'Zahllauf ausführen')
        self.assertContains(r, 'dringend')                    # überfällige Debitoren
        self.assertContains(r, 'Überfällige Forderungen mahnen')
        self.assertNotContains(r, 'Alle Finanzaufgaben erledigt')

    def test_nur_angefangene_weiterverrechnung_ist_todo(self):
        """Eine unberührte Kreditorenrechnung darf NICHT als Weiterverrechnungs-Todo erscheinen;
        eine teilweise weiterverrechnete schon."""
        from finance.models import KreditorenRechnung
        from finance.booking import konto as _k
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('500'),
                                              status='bezahlt', liegenschaft=lg, konto=_k('4000'))
        c = Client(); c.force_login(_team_user())
        # noch nichts weiterverrechnet → Anzahl 0 (Kachel zeigt "erledigt")
        r = c.get('/neu/finanzen/')
        self.assertEqual(r.context['arbeitskorb'][3]['key'], 'weiterverrechnung')
        self.assertEqual(r.context['arbeitskorb'][3]['anzahl'], 0)
        # 300 von 500 weiterverrechnen → jetzt offener Rest = Todo
        c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/',
               {'vertrag_id': v.id, 'betrag': '300', 'zuschlag': '0'})
        r2 = c.get('/neu/finanzen/')
        self.assertEqual(r2.context['arbeitskorb'][3]['anzahl'], 1)

    def test_checkliste_sollstellung_ampel(self):
        from core.services.automation import run_sollstellung
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        heute = date.today()
        r = c.get('/neu/finanzen/')
        # vor Sollstellung: der Sollstellungs-Schritt ist offen (ok=False)
        soll = next(x for x in r.context['checkliste'] if x['titel'].startswith('Sollstellung'))
        self.assertIs(soll['ok'], False)
        # Sollstellung für aktuellen Monat laufen lassen
        run_sollstellung(heute.year, heute.month)
        r2 = c.get('/neu/finanzen/')
        soll2 = next(x for x in r2.context['checkliste'] if x['titel'].startswith('Sollstellung'))
        self.assertIs(soll2['ok'], True)

    def test_durchlaufkonto_saldo_sichtbar(self):
        from finance.booking import buche
        lg, e, m, v = _basis_objekte()
        # geparkte Position auf 1190 (Soll) — noch nicht geklärt
        buche('1190', '1020', Decimal('120'), 'Unklare Gutschrift', liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/finanzen/')
        self.assertEqual(r.context['durchlauf_saldo'], Decimal('120.00'))
        self.assertContains(r, 'geparkte Positionen klären')


class MieterkontoblattTests(TestCase):
    """Mieterkontoblatt (on-screen): Forderungen + Zahlungen mit laufendem Saldo."""

    def _konto(self):
        from finance.models import DebitorenRechnung, Zahlungseingang
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete 01/2025',
                                         betrag=Decimal('1700'), datum=date(2025, 1, 1),
                                         faellig_am=date(2025, 1, 1), status='offen')
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, titel='Miete 02/2025',
                                         betrag=Decimal('1700'), datum=date(2025, 2, 1),
                                         faellig_am=date(2025, 2, 1), status='bezahlt')
        Zahlungseingang.objects.create(vertrag=v, betrag=Decimal('1700'),
                                       datum_eingang=date(2025, 2, 3), status='verbucht',
                                       bemerkung='Zahlung Februar')
        return lg, e, m, v

    def test_kontoblatt_saldo_und_bewegungen(self):
        lg, e, m, v = self._konto()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mieterkonten/{m.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Kontoblatt')
        self.assertContains(r, 'Miete 01/2025')
        self.assertContains(r, 'Zahlung Februar')
        # Soll 3400, Haben 1700, Endsaldo 1700 (Mieter schuldet)
        self.assertEqual(r.context['total_soll'], Decimal('3400.00'))
        self.assertEqual(r.context['total_haben'], Decimal('1700.00'))
        self.assertEqual(r.context['endsaldo'], Decimal('1700.00'))
        # laufender Saldo der letzten Bewegung = Endsaldo
        self.assertEqual(r.context['zeilen'][-1]['saldo'], Decimal('1700.00'))

    def test_offene_posten_liste(self):
        lg, e, m, v = self._konto()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mieterkonten/{m.id}/')
        # nur die noch offene Rechnung erscheint als OP
        self.assertEqual(len(r.context['op_rows']), 1)
        self.assertEqual(r.context['op_total'], Decimal('1700.00'))

    def test_datumsfilter(self):
        lg, e, m, v = self._konto()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/mieterkonten/{m.id}/?von=2025-02-01')
        # nur Februar-Bewegungen (Rechnung + Zahlung), Januar ausgeblendet
        texte = [z['text'] for z in r.context['zeilen']]
        self.assertIn('Miete 02/2025', texte)
        self.assertNotIn('Miete 01/2025', texte)

    def test_uebersicht_listet_mieter_mit_saldo(self):
        lg, e, m, v = self._konto()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterkonten/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, m.display_name)
        self.assertEqual(r.context['total_offen'], Decimal('1700.00'))
        self.assertEqual(r.context['offen_n'], 1)
        # Filter "nur offen"
        r2 = c.get('/neu/mieterkonten/?filter=offen')
        self.assertEqual(len(r2.context['rows']), 1)

    def test_suche_filtert_nach_mieter_und_objekt(self):
        """Gemeldet: «lange Liste, man kann die Mieter kaum unterscheiden» —
        ohne Suche bleibt nur Scrollen."""
        lg, e, m, v = self._konto()
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterkonten/?q=' + (m.nachname or '')[:4])
        self.assertEqual(len(r.context['rows']), 1)
        self.assertContains(r, 'Treffer für')
        # Objektsuche findet denselben Mieter über die Adresse
        r2 = c.get('/neu/mieterkonten/?q=' + lg.strasse[:5])
        self.assertEqual(len(r2.context['rows']), 1)
        # Kein Treffer → leere Liste, Seite bleibt bedienbar
        r3 = c.get('/neu/mieterkonten/?q=zzzznichtvorhanden')
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(len(r3.context['rows']), 0)

    def test_alle_zaehler_bleibt_in_der_gefilterten_ansicht_korrekt(self):
        """«Alle (N)» zählte die bereits gefilterten Zeilen — in der Ansicht
        «nur offen» stand am Alle-Knopf also die falsche Zahl."""
        from crm.models import Mieter
        lg, e, m, v = self._konto()
        m2 = Mieter.objects.create(vorname='Ohne', nachname='Ausstand')
        Mietvertrag.objects.create(mieter=m2, einheit=e, status='aktiv',
                                   beginn=date(2025, 1, 1),
                                   netto_mietzins=Decimal('100'), nebenkosten=Decimal('0'))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mieterkonten/?filter=offen')
        self.assertEqual(r.context['anzahl'], 2)        # alle Mieter
        self.assertEqual(len(r.context['rows']), 1)     # angezeigt: nur der offene

    def test_erste_zelle_wird_zur_ueberschrift_der_karte(self):
        """Auf dem Handy ist «MIETER» als Beschriftung Rauschen — der Name ist
        die Überschrift. Ohne das verschwimmen die Einträge ineinander."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/mieterkonten/').content.decode('utf-8')
        self.assertIn('data-stack-titel', html)         # Skript setzt das Attribut
        self.assertIn("td[data-stack-titel]::before { content: none; }", html)

    def test_trennband_auch_in_den_handgebauten_kartenlisten(self):
        """Liegenschaften, Personen, Verträge und Debitoren sind keine gestapelten
        Tabellen, sondern eigene Karten-Listen — dort fehlte das Band, nebeneinander
        sah das aus wie zwei verschiedene Regeln."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/liegenschaften/').content.decode('utf-8')
        self.assertIn(r'.md\:hidden.divide-y > * + * { border-top: 8px solid #f1f5f9 !important; }',
                      html)
        # und der Strassenname wird nicht mehr abgeschnitten
        self.assertNotIn('font-semibold text-slate-900 truncate">{{ row.lg.strasse', html)

    def test_aufklappgruppen_bekommen_mobil_ein_trennband(self):
        """Auf /neu/objekte/ sitzen die Liegenschafts-Gruppen zu mehreren in
        EINER Karte, getrennt nur durch die Haarlinie von «border-b» — gemeldet
        als «Keine Trennlinie» zwischen zwei Liegenschaften.

        Eine Stufe dunkler (#e2e8f0) als das Band zwischen einzelnen Einträgen
        (#f1f5f9): sonst wäre die Gruppengrenze nicht von der Trennung ihrer
        eigenen Zeilen zu unterscheiden, sobald eine Gruppe offen ist.

        Gemessen bei iPhone-Breite: 36 Gruppen je 8px rgb(226,232,240),
        letzte Gruppe 0px."""
        _basis_objekte()          # sonst rendert die Seite gar keine Gruppe
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/objekte/').content.decode('utf-8')
        self.assertIn('main details.group.border-b { border-bottom: 8px solid #e2e8f0 !important; }',
                      html)
        self.assertIn('main details.group.border-b:last-child { border-bottom-width: 0 !important; }',
                      html)
        # Die Gruppen tragen die Klassen, auf die die Regel zielt
        self.assertIn('<details class="group border-b border-slate-100 last:border-0">', html)

    def test_truncate_bricht_nicht_mitten_im_wort(self):
        """`overflow-wrap: anywhere` senkt auch die min-content-Breite auf ein
        Zeichen — der Titel brach dann mitten im Wort («überfälli/ge
        Forderun/gen») und die Inbox-Kachel wurde turmhoch. `break-word` hält
        das längste Wort als Untergrenze.

        Gemessen bei 390 px auf /neu/fristen/: höchste Zeile 760 px → 133 px,
        Median 760 px → 76 px."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/liegenschaften/').content.decode('utf-8')
        block = html.split('main .truncate {', 1)[1].split('}', 1)[0]
        self.assertIn('overflow-wrap: break-word;', block)
        # Die Deklaration selbst darf nicht mehr vorkommen (das Wort steht noch
        # in der Begründung darüber).
        self.assertNotIn('overflow-wrap: anywhere', block)

    def test_inbox_titel_bekommt_mobil_die_volle_breite(self):
        """Betrag und CTA sind nowrap und geben keine Breite ab — die
        Titelspalte blieb auf 55–95 px und die Zeile wurde bis 321 px hoch.

        Gemessen bei 390 px: Titelbreite 55–95 px → durchgehend 246 px,
        höchste Zeile 321 px → 174 px."""
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        # Eine überfällige Forderung erzeugt den Inbox-Eintrag «… mahnen».
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete Januar',
            betrag=Decimal('1500.00'), datum=date(2026, 1, 1),
            faellig_am=date(2026, 1, 5), status='offen')
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/').content.decode('utf-8')
        self.assertIn('class="min-w-0 basis-full sm:basis-0 flex-1', html)

    def test_truncate_wird_mobil_zentral_aufgehoben(self):
        """«truncate» schneidet auf dem Handy genau das weg, was die Zeile
        identifiziert («Selzacherstras…», «B..»). Statt in ~30 Templates einzeln
        zu flicken hebt base.html es mobil im Inhaltsbereich auf.

        Gemessen bei 390 px (Playwright, Utilities injiziert): pendenzen 3,
        fristen 12, kommunikation 16, finanzen 6 abgeschnittene Elemente vorher
        — nachher 0."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/liegenschaften/').content.decode('utf-8')
        self.assertIn('main .truncate {', html)
        for regel in ('white-space: normal !important;',
                      'overflow: visible !important;',
                      'text-overflow: clip !important;'):
            self.assertIn(regel, html)

    def test_truncate_bleibt_in_topbar_und_seitenleiste(self):
        """Die Regel ist auf <main> begrenzt: Benutzername und Menü-Labels
        brauchen ihre feste Zeilenhöhe, dort ist truncate richtig."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/liegenschaften/').content.decode('utf-8')
        self.assertNotIn('\n            .truncate {', html)
        # Der Benutzername in der Topbar trägt weiterhin truncate
        self.assertIn('text-sm font-semibold text-slate-900 truncate', html)

    def test_trennband_gilt_fuer_jede_karte_nicht_nur_die_erste(self):
        """Tailwinds «divide-y» setzt auf jeder Zeile ausser der ersten
        border-bottom-width: 0. Ohne Vorrang bekam nur die erste Karte ein
        Trennband — gemeldet als «Trennstrich nur bei anderer Liegenschaft»,
        was aber nur zufällig zum Datenbild passte."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/mieterkonten/').content.decode('utf-8')
        self.assertIn('border-bottom: 8px solid #f1f5f9 !important', html)


class DebitorenAgingTests(TestCase):
    """Debitoren-Altersstruktur (OP-Aging) nach Fälligkeits-Buckets."""

    def _rechnung(self, v, lg, betrag, faellig, status='offen'):
        from finance.models import DebitorenRechnung
        return DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete', betrag=Decimal(betrag),
            datum=faellig, faellig_am=faellig, status=status)

    def test_buckets_pro_mieter(self):
        from django.utils import timezone as _tz
        lg, e, m, v = _basis_objekte()
        # timezone.localdate() (Europe/Zurich) wie die View — date.today() (UTC)
        # weicht um Mitternacht herum um einen Tag ab (Flake um 00:00 Lokalzeit).
        heute = _tz.localdate()
        self._rechnung(v, lg, '100', heute + timedelta(days=10))    # nicht fällig
        self._rechnung(v, lg, '200', heute - timedelta(days=15))    # 1–30
        self._rechnung(v, lg, '300', heute - timedelta(days=45))    # 31–60
        self._rechnung(v, lg, '400', heute - timedelta(days=120))   # >90
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mahnwesen/aging/')
        self.assertEqual(r.status_code, 200)
        t = r.context['total']
        self.assertEqual(t['nicht_faellig'], Decimal('100.00'))
        self.assertEqual(t['d30'], Decimal('200.00'))
        self.assertEqual(t['d60'], Decimal('300.00'))
        self.assertEqual(t['d90plus'], Decimal('400.00'))
        self.assertEqual(t['summe'], Decimal('1000.00'))
        self.assertEqual(r.context['ueberfaellig_summe'], Decimal('900.00'))
        # ein Mieter, ältester = 120 Tage
        self.assertEqual(len(r.context['rows']), 1)
        self.assertEqual(r.context['rows'][0]['aeltester'], 120)

    def test_bezahlte_ignoriert(self):
        lg, e, m, v = _basis_objekte()
        self._rechnung(v, lg, '500', date.today() - timedelta(days=40), status='bezahlt')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mahnwesen/aging/')
        self.assertEqual(r.context['total']['summe'], Decimal('0.00'))
        self.assertEqual(len(r.context['rows']), 0)


class DebitorVorschauTests(TestCase):
    """Live-Vorschau bei der Ad-hoc-Debitorenrechnung (wie im Vertragsassistenten)."""

    def test_debitoren_seite_hat_vorschau(self):
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Dv 1', plz='8000', ort='Zürich',
                                         versicherungswert=Decimal('1'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Dv-Whg', typ='whg',
                                   nettomiete_aktuell=Decimal('1500'))
        m = Mieter.objects.create(typ='person', vorname='Vor', nachname='Schau',
                                  strasse='Weg 2', plz='8000', ort='Zürich')
        Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2025, 1, 1),
                                   netto_mietzins=Decimal('1500'), nebenkosten=Decimal('0'),
                                   status='aktiv')
        c = Client(); c.force_login(_team_user())
        body = c.get('/neu/debitoren/').content.decode()
        # Vorschau-Gerüst + Datenquellen vorhanden
        self.assertIn('id="deb-pv"', body)
        self.assertIn('function debPreview', body)
        self.assertIn('vd-data', body)
        self.assertIn('abs-data', body)
        # Empfängerdaten des aktiven Vertrags im JSON
        self.assertIn('Vor Schau', body)


class MoneyBugBatchTests(TestCase):
    """Geld-Funde aus «Komplet alles umsetzen» — jeder Test sichert eine
    korrekt ausgeglichene Buchung / Idempotenz dauerhaft ab."""

    def _saldo(self, nummer):
        from finance.models import Buchung, Buchungskonto
        from django.db.models import Sum
        k = Buchungskonto.objects.filter(nummer=nummer).first()
        if not k:
            return Decimal('0.00'), Decimal('0.00')
        s = Buchung.objects.filter(soll_konto=k, ist_storno=False).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        h = Buchung.objects.filter(haben_konto=k, ist_storno=False).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        return s, h

    def test_weiterverrechnung_spaltet_mwst_und_zuschlag(self):
        # F1: Der Aufwand wurde nur netto gebucht (Vorsteuer separat). Die
        # Weiterverrechnung darf ihn deshalb nur NETTO entlasten; der MWST-Anteil
        # ist Ausgangs-Umsatzsteuer (2200), der Zuschlag ein Ertrag (3600).
        from finance.booking import ensure_kontenplan, konto
        from finance.models import KreditorenRechnung, DebitorenRechnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        k = KreditorenRechnung.objects.create(
            lieferant='Sanitär AG', betrag=Decimal('1081.00'), mwst_satz=Decimal('8.1'),
            status='freigegeben', liegenschaft=lg, konto=konto('4000'),
            datum=date(2024, 6, 1), faellig_am=date(2024, 6, 30))
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/kreditoren/{k.id}/weiterverrechnen/', {
            'vertrag_id': str(v.id), 'betrag': '1081.00', 'zuschlag': '100.00',
            'titel': 'Rohrbruch Küche'})
        self.assertIn(r.status_code, (200, 302))
        rech = DebitorenRechnung.objects.get(quell_kreditor=k)
        self.assertEqual(rech.betrag, Decimal('1181.00'))              # grund + zuschlag
        self.assertEqual(rech.weiterverrechnung_zuschlag, Decimal('100.00'))
        # Aufwand (4000) nur um NETTO 1000 entlastet, 81 als 2200 Umsatzsteuer.
        s4000, h4000 = self._saldo('4000')
        self.assertEqual(h4000 - s4000, Decimal('1000.00'))
        s2200, h2200 = self._saldo('2200')
        self.assertEqual(h2200 - s2200, Decimal('81.00'))
        s3600, h3600 = self._saldo('3600')
        self.assertEqual(h3600 - s3600, Decimal('100.00'))            # Zuschlag = Ertrag
        # Durchlaufkonto 1190 geht exakt auf null auf.
        s1190, h1190 = self._saldo('1190')
        self.assertEqual(s1190 - h1190, Decimal('0.00'))
        # Kreditor gilt als voll (nur netto-relevant) weiterverrechnet — Zuschlag zählt nicht.
        self.assertEqual(k.weiterverrechnet_betrag, Decimal('1081.00'))
        self.assertEqual(k.offen_weiterzuverrechnen, Decimal('0.00'))

    def test_kaution_einbehalt_ist_ausgeglichen_und_ertrag(self):
        # Kaution-Auflösung: Sperrkonto-Freigabe 1020/1015, Rückzahlung 2010/1020,
        # Einbehalt 2010/3600 (Ertrag). Früher: gefälschter «bezahlter» Debitor ohne Buchung.
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()   # Kaution 4500
        v.kautions_art = 'sperrkonto'; v.kautions_konto = 'CH00'
        v.kautions_einbezahlt_am = date(2024, 1, 1); v.save()
        # Depot bei Einzahlung: 1015 Sperrkonto an 2010 Verbindlichkeit.
        buche('1015', '2010', Decimal('4500'), 'Kaution Einzahlung', datum=date(2024, 1, 1), liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/vertraege/{v.id}/kaution/', {
            'aktion': 'rueckzahlung', 'abzug_betrag': '500', 'abzug_grund': 'Reinigung',
            'zurueckbezahlt_am': '2024-07-01'})
        self.assertEqual(r.status_code, 302)
        # 2010 vollständig ausgeglankt (Soll 4500 = Haben 4500).
        s2010, h2010 = self._saldo('2010')
        self.assertEqual(s2010, Decimal('4500.00'))
        self.assertEqual(h2010, Decimal('4500.00'))
        # 1015 Sperrkonto wieder auf null (4500 rein, 4500 raus).
        s1015, h1015 = self._saldo('1015')
        self.assertEqual(h1015 - s1015, Decimal('0.00'))
        # Einbehalt 500 als Ertrag auf 3600.
        s3600, h3600 = self._saldo('3600')
        self.assertEqual(h3600 - s3600, Decimal('500.00'))

    def test_kaution_einbehalt_idempotent(self):
        from finance.booking import ensure_kontenplan, buche
        from finance.models import Buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        v.kautions_art = 'sperrkonto'; v.kautions_einbezahlt_am = date(2024, 1, 1); v.save()
        buche('1015', '2010', Decimal('4500'), 'Kaution Einzahlung', datum=date(2024, 1, 1), liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        for _ in range(2):
            c.post(f'/neu/vertraege/{v.id}/kaution/', {
                'aktion': 'rueckzahlung', 'abzug_betrag': '500',
                'zurueckbezahlt_am': '2024-07-01'})
        # Zweiter Klick bucht nicht erneut (beleg_text-Idempotenz). Der Belegtext
        # trägt die Vertrags-ID, damit die Saldo-Prüfung diese Auflösung erkennt
        # und die Schlussabrechnung dieselbe Kaution nicht nochmals freigibt.
        n = Buchung.objects.filter(beleg_text__startswith=f"Kaution Auflösung [V{v.pk}]",
                                   ist_storno=False).count()
        self.assertEqual(n, 3)   # Freigabe + Rückzahlung + Einbehalt, genau einmal

    def test_mietzins_anpassung_pdf_ist_idempotent(self):
        # Mehrfaches PDF-Generieren darf keine doppelte Anpassung + Anfechtungs-Pendenz erzeugen.
        from rentals.models import MietzinsAnpassung
        from rentals.services import naechster_anpassungstermin
        from core.models import Pendenz
        from django.utils import timezone
        lg, e, m, v = _basis_objekte()
        v.basis_referenzzinssatz = Decimal('1.25'); v.basis_lik_punkte = Decimal('100.0'); v.save()
        wirksam = naechster_anpassungstermin(v, timezone.localdate())  # gültiger Termin (Art. 269d)
        c = Client(); c.force_login(_team_user())
        payload = {'aktion': 'pdf', 'neu_netto': '1600', 'neu_zins': '1.50',
                   'neu_lik': '105.0', 'wirksam_ab': wirksam.isoformat(),
                   'begruendung': 'Referenzzins', 'formular': 'generisch'}
        for _ in range(3):
            c.post(f'/neu/mietzins/{v.id}/anpassung/', payload)
        self.assertEqual(MietzinsAnpassung.objects.filter(vertrag=v, wirksam_ab=wirksam).count(), 1)
        self.assertEqual(Pendenz.objects.filter(vertrag=v, kategorie='frist').count(), 1)

    def test_schlussabrechnung_teilbezahlt_bleibt_op(self):
        # Verhaltenstest (ersetzt die frühere Quellcode-Prüfung): eine teilbezahlte
        # Mietforderung bleibt mit ihrem Restbetrag als OP bestehen und wird von der
        # Schlussabrechnung weder storniert noch ein zweites Mal als Ertrag gebucht.
        from finance.models import DebitorenRechnung, Zahlungseingang, Buchung
        from finance.booking import buche, ensure_kontenplan
        from django.db.models import Sum
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        alt = DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                               titel='Miete 05/2024', datum=date(2024, 5, 1),
                                               faellig_am=date(2024, 5, 5), betrag=Decimal('1700'),
                                               status='teilbezahlt')
        buche('1100', '3000', Decimal('1700'), 'Miete 05/2024', datum=date(2024, 5, 1),
              liegenschaft=lg, debitor=alt)
        Zahlungseingang.objects.create(vertrag=v, betrag=Decimal('700'),
                                       datum_eingang=date(2024, 5, 10),
                                       buchungs_monat=date(2024, 5, 1),
                                       debitoren_rechnung=alt, status='verbucht')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen'})
        alt.refresh_from_db()
        self.assertEqual(alt.status, 'teilbezahlt')
        self.assertEqual(alt.offener_betrag, Decimal('1000'))
        # Mietertrag wurde nur EINMAL gebucht (kein Doppelertrag durch Neubuchung)
        ertrag_3000 = (Buchung.objects.filter(haben_konto__nummer='3000')
                       .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        self.assertEqual(ertrag_3000, Decimal('1700'))


class FinanzUIP5Tests(TestCase):
    """Fallen, die still Geld oder Arbeit kosten: der Tausender-Apostroph, eine
    Sollstellung über das falsche Portfolio, eine wirkungslose Paginierung."""

    def _saldo(self, nummer):
        from finance.models import Buchung
        from django.db.models import Sum
        soll = (Buchung.objects.filter(soll_konto__nummer=nummer, ist_storno=False)
                .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        haben = (Buchung.objects.filter(haben_konto__nummer=nummer, ist_storno=False)
                 .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        return soll - haben

    # ---------- Tausender-Apostroph ----------
    def test_num_normalisiert_schweizer_betragsformate(self):
        from core.views.fw import _num
        self.assertEqual(_num("12'500.00"), '12500.00')
        self.assertEqual(_num("1’200,50"), '1200.50')      # typografischer Apostroph
        self.assertEqual(_num(" CHF 3 400.00 "), '3400.00')
        self.assertEqual(_num('8.1'), '8.1')
        self.assertEqual(_num(''), '')
        self.assertEqual(_num(None), '')

    def test_eigentuemer_auszahlung_akzeptiert_apostroph_betrag(self):
        """Das Feld ist mit dem `chf`-Filter vorbelegt (12'500.00) — genau dieser
        Wert kam zurück und liess `Decimal()` scheitern."""
        from crm.models import Eigentuemer
        from finance.models import EigentuemerAuszahlung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        md = Eigentuemer.objects.create(firma_oder_name='Muster Immobilien AG')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/mandate/{md.id}/auszahlung/',
               {'betrag': "12'500.00", 'datum': '2024-05-01'})
        a = EigentuemerAuszahlung.objects.get(eigentuemer=md)
        self.assertEqual(a.betrag, Decimal('12500.00'))
        self.assertEqual(self._saldo('2850'), Decimal('12500.00'))
        self.assertEqual(self._saldo('1020'), Decimal('-12500.00'))

    def test_kreditor_zahlung_akzeptiert_apostroph_betrag(self):
        from finance.models import KreditorenRechnung, KreditorenZahlung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        kr = KreditorenRechnung.objects.create(
            lieferant='Grossbau AG', betrag=Decimal('12500.00'),
            datum=date(2024, 5, 1), liegenschaft=lg, status='freigegeben')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': kr.id, 'betrag': "12'500.00"})
        z = KreditorenZahlung.objects.get(kreditor=kr)
        self.assertEqual(z.betrag, Decimal('12500.00'))

    # ---------- Sollstellung folgt dem Filter ----------
    def test_sollstellung_beachtet_den_liegenschaftsfilter(self):
        """Die Vorschau war gefiltert, der Lauf nicht — ein Klick stellte dem
        ganzen Portfolio Rechnung."""
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        from portfolio.models import Liegenschaft, Einheit
        from crm.models import Mieter
        from rentals.models import Mietvertrag
        ensure_kontenplan()
        lg1, e1, m1, v1 = _basis_objekte()
        lg2 = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Andergasse 9', plz='3000', ort='Bern')
        e2 = Einheit.objects.create(liegenschaft=lg2, bezeichnung='2. OG', typ='whg',
                                    zimmer=Decimal('3.5'), flaeche_m2=80)
        m2 = Mieter.objects.create(vorname='Rita', nachname='Zweitmieter')
        Mietvertrag.objects.create(einheit=e2, mieter=m2, beginn=date(2024, 1, 1),
                                   status='aktiv', netto_mietzins=Decimal('1500.00'),
                                   nebenkosten=Decimal('150.00'))
        c = Client(); c.force_login(_team_user())
        c.post('/neu/sollstellung/starten/', {'jahr': 2024, 'monat': 5, 'lg': lg1.id})
        titel = 'Miete & NK 05/2024'
        self.assertTrue(DebitorenRechnung.objects.filter(vertrag=v1, titel=titel).exists())
        self.assertFalse(DebitorenRechnung.objects.filter(vertrag__einheit=e2,
                                                          titel=titel).exists())

    def test_sollstellung_ohne_filter_deckt_das_portfolio_ab(self):
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        from portfolio.models import Liegenschaft, Einheit
        from crm.models import Mieter
        from rentals.models import Mietvertrag
        ensure_kontenplan()
        lg1, e1, m1, v1 = _basis_objekte()
        lg2 = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Andergasse 9', plz='3000', ort='Bern')
        e2 = Einheit.objects.create(liegenschaft=lg2, bezeichnung='2. OG', typ='whg',
                                    zimmer=Decimal('3.5'), flaeche_m2=80)
        m2 = Mieter.objects.create(vorname='Rita', nachname='Zweitmieter')
        Mietvertrag.objects.create(einheit=e2, mieter=m2, beginn=date(2024, 1, 1),
                                   status='aktiv', netto_mietzins=Decimal('1500.00'),
                                   nebenkosten=Decimal('150.00'))
        c = Client(); c.force_login(_team_user())
        c.post('/neu/sollstellung/starten/', {'jahr': 2024, 'monat': 5})
        titel = 'Miete & NK 05/2024'
        self.assertEqual(DebitorenRechnung.objects.filter(titel=titel).count(), 2)

    # ---------- Paginierung ----------
    def test_debitorenliste_liefert_nur_die_angeforderte_seite(self):
        """Der Fuss zeigte «Seite 1/2», die Tabelle rendert(e) trotzdem alles."""
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        for i in range(60):
            DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=lg, einheit=e, titel=f'Position {i}',
                betrag=Decimal('100.00'), datum=date(2024, 5, 1),
                faellig_am=date(2024, 5, 31), status='offen')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/debitoren/')
        self.assertEqual(r.context['rows_gesamt'], 60)
        self.assertEqual(len(r.context['page'].object_list), 50)
        r2 = c.get('/neu/debitoren/?seite=2')
        self.assertEqual(len(r2.context['page'].object_list), 10)

    def test_debitorenliste_hat_spaltensummen_ueber_den_ganzen_filter(self):
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        for i in range(60):
            DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=lg, einheit=e, titel=f'Position {i}',
                betrag=Decimal('100.00'), datum=date(2024, 5, 1),
                faellig_am=date(2024, 5, 31), status='offen')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/debitoren/')
        # Summe über ALLE 60, nicht nur die 50 der ersten Seite
        self.assertEqual(r.context['total_betrag'], Decimal('6000.00'))
        self.assertEqual(r.context['total_offen'], Decimal('6000.00'))

    def test_blaettern_behaelt_den_liegenschaftsfilter(self):
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        for i in range(60):
            DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=lg, einheit=e, titel=f'Position {i}',
                betrag=Decimal('100.00'), datum=date(2024, 5, 1),
                faellig_am=date(2024, 5, 31), status='offen')
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/debitoren/?lg={lg.id}')
        self.assertContains(r, f'seite=2&status=&q=&lg={lg.id}'.replace('status=&q=&', ''))

    # ---------- Apostroph im Namen bricht keinen Bestätigungsdialog ----------
    def test_apostroph_im_lieferantennamen_bricht_den_dialog_nicht(self):
        """Ein unmaskierter Name beendete den JS-String — der onsubmit-Handler
        wurde gar nicht erst installiert und die Aktion lief ohne Rückfrage."""
        from finance.models import KreditorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        KreditorenRechnung.objects.create(
            lieferant="O'Brien & Co AG", betrag=Decimal('100.00'),
            datum=date(2024, 5, 1), liegenschaft=lg, status='freigegeben')
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/kreditoren/').content.decode('utf-8')
        self.assertIn("confirm('Zahlung an O\\u0027Brien", html)
        self.assertNotIn("confirm('Zahlung an O&#x27;Brien", html)

    # ---------- Buchhaltung auf dem Handy ----------
    # ---------- Erfolgsrechnung & Bilanz als PDF ----------
    # Gemeldet: «Erfolgsrechnung Bilanz sind nicht als PDF verfügbar.» Der
    # Berichte-Hub trug für diesen Bericht ein PDF-Abzeichen, dahinter lag aber
    # nur ein CSV-Journal-Export — das Abzeichen war ein leeres Versprechen.

    def _buchungen_fuer_abschluss(self):
        from django.utils import timezone as _tz
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        heute = _tz.localdate()
        buche('1100', '3000', Decimal('5000.00'), 'Miete', datum=heute, liegenschaft=lg)
        buche('4000', '1020', Decimal('1200.00'), 'Reparatur', datum=heute, liegenschaft=lg)
        return lg, heute

    def test_abschluss_pdf_wird_ausgeliefert(self):
        lg, heute = self._buchungen_fuer_abschluss()
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/buchhaltung/pdf/?jahr={heute.year}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF-'))

    def test_abschluss_pdf_zeigt_dieselben_zahlen_wie_der_bildschirm(self):
        """Ein Abschluss, der je nach Ausgabeweg anders aussieht, ist wertlos —
        beide Wege rechnen deshalb über `_erfolg_bilanz`."""
        from core.views.fw import _erfolg_bilanz
        lg, heute = self._buchungen_fuer_abschluss()
        daten = _erfolg_bilanz(None, heute.year)
        self.assertEqual(daten['total_ertrag'], Decimal('5000.00'))
        self.assertEqual(daten['total_aufwand'], Decimal('1200.00'))
        self.assertEqual(daten['erfolg'], Decimal('3800.00'))
        # und die Bilanz geht auf
        self.assertEqual(daten['bilanz_differenz'], Decimal('0.00'))

    def test_buchhaltung_seite_bietet_den_pdf_abzug_an(self):
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/buchhaltung/').content.decode('utf-8')
        self.assertIn('/neu/buchhaltung/pdf/', html)
        self.assertIn('Erfolgsrechnung &amp; Bilanz (PDF)', html)

    def test_berichte_hub_pdf_abzeichen_ist_kein_leeres_versprechen(self):
        """Das Abzeichen im Hub muss zu einem echten PDF führen."""
        lg, heute = self._buchungen_fuer_abschluss()
        c = Client(); c.force_login(_team_user())
        self.assertContains(c.get('/neu/berichte/'), 'Erfolgsrechnung &amp; Bilanz')
        self.assertEqual(c.get('/neu/buchhaltung/pdf/').status_code, 200)

    def test_jedes_pdf_abzeichen_im_hub_liefert_auch_ein_pdf(self):
        """Das PDF-Abzeichen im Berichte-Hub ist ein reines Anzeige-Flag —
        nichts prüfte, ob dahinter wirklich ein PDF liegt. Bei «Erfolgsrechnung
        & Bilanz» war es deshalb ein leeres Versprechen (gemeldet).

        Dieser Test pinnt die vier versprochenen Ausgaben. Verschwindet eine,
        fällt es hier auf statt beim Nutzer."""
        from crm.models import Eigentuemer
        lg, _heute = self._buchungen_fuer_abschluss()
        mieter = Mieter.objects.first()
        md = Eigentuemer.objects.create(firma_oder_name='Eigentümer AG')
        lg.eigentuemer = md; lg.save(update_fields=['eigentuemer'])
        c = Client(); c.force_login(_team_user())
        ziele = [
            ('Erfolgsrechnung & Bilanz', '/neu/buchhaltung/pdf/'),
            ('Mieterkonten', f'/neu/personen/{mieter.id}/kontoauszug/'),
            ('Mieterspiegel', f'/neu/mieterspiegel/?pdf=1&lg={lg.id}'),
            ('Mandatsabrechnung', f'/neu/mandate/{md.id}/abrechnung/?pdf=1'),
            ('Kontokorrent', f'/neu/mandate/{md.id}/kontokorrent/?pdf=1'),
        ]
        for name, url in ziele:
            r = c.get(url)
            self.assertEqual(r.status_code, 200, f"{name}: {url} -> {r.status_code}")
            self.assertIn('pdf', r.get('Content-Type', ''),
                          f"{name} liefert kein PDF ({r.get('Content-Type')})")

    def test_abschluss_pdf_vertraegt_alle_jahre_und_unsinn(self):
        c = Client(); c.force_login(_team_user())
        self.assertEqual(c.get('/neu/buchhaltung/pdf/?jahr=alle').status_code, 200)
        self.assertEqual(c.get('/neu/buchhaltung/pdf/?jahr=xyz').status_code, 200)

    def test_erfolgsrechnung_erzwingt_keine_mindestbreite(self):
        """min-w-max schob den Betrag aus dem Bild: auf dem Handy sah man
        entweder Kontonummer+Name ODER den Betrag, nie beides."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/buchhaltung/').content.decode('utf-8')
        erfolg = html.split('id="bh-erfolg"')[1].split('id="bh-bilanz"')[0]
        self.assertNotIn('min-w-max', erfolg)
        bilanz = html.split('id="bh-bilanz"')[1].split('id="bh-journal"')[0]
        self.assertNotIn('min-w-max', bilanz)

    # ---------- Tabellen am PC: keine Querscroll-Pflicht ----------
    # «min-w-max» machte die Tabelle so breit wie ihr Inhalt; auf
    # /neu/debitoren/ waren das 1412 px in einer 1134 px breiten Spalte
    # (1440 px Fenster), also lagen Mahnstufe und Aktionen ausserhalb des
    # Bildes. Gelöst über eine zentrale Regel in base.html, die linksbündige
    # Textspalten umbrechen lässt.

    def _debitoren_tabelle(self):
        """Der Desktop-Teil der Debitoren-Seite als HTML-Ausschnitt."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/debitoren/').content.decode('utf-8')
        return html.split('<!-- Desktop: Tabelle -->')[1].split('</table>')[0]

    def test_geldspalten_bleiben_rechtsbuendig(self):
        """Die Umbruch-Regel unterscheidet Text von Zahl allein an
        `text-right`. Verliert eine Betragsspalte diese Klasse, fängt der
        Betrag an umzubrechen («1'450.» / «00») — die Zahlenkolonne wäre
        nicht mehr lesbar. Diese Konvention wird hier gepinnt."""
        import re
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete & NK 08/2026',
            betrag=Decimal('1450.00'), status='offen',
            faellig_am=date(2026, 8, 1))
        tabelle = self._debitoren_tabelle()
        zellen = re.findall(r'<td\b([^>]*)>(.*?)</td>', tabelle, re.S)
        self.assertTrue(zellen, 'keine Tabellenzeilen gerendert — Test wäre wertlos')
        # Eine Betragszelle enthält NUR den Betrag. Über den Zellinhalt statt
        # über ein Muster im Fliesstext, sonst zählt «01.08.2026» als Betrag.
        def nur_betrag(inhalt):
            txt = re.sub(r'<[^>]+>', '', inhalt)
            txt = txt.replace('&nbsp;', ' ').strip()
            return re.fullmatch(r"-?[\d'\u2019]{1,15}\.\d{2}", txt) is not None
        betrags_zellen = [(a, i) for a, i in zellen if nur_betrag(i)]
        self.assertTrue(betrags_zellen, 'kein Betrag in der Tabelle gefunden')
        for attr, inhalt in betrags_zellen:
            self.assertIn('text-right', attr,
                          f'Betragszelle ohne text-right: {inhalt.strip()[:60]}')

    def test_base_laesst_breite_tabellen_am_pc_umbrechen(self):
        """Ohne diese Regel scrollt jede Tabelle mit vielen Spalten quer.
        Sie steht zentral in base.html, damit sie auch für neue Tabellen
        gilt — und ist deshalb leicht versehentlich zu entfernen."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/debitoren/').content.decode('utf-8')
        self.assertIn('@media (min-width: 768px)', html)
        self.assertIn('main table.min-w-max td:not(.text-right):not(.text-center)', html)
        # Der Wrapper bleibt scrollbar — sehr breite Tabellen (Spalte je
        # Bewerber) brauchen ihn weiterhin.
        self.assertIn('overflow-x-auto', html)

    def test_journal_hat_kartenansicht_fuers_handy(self):
        """Sieben Spalten passen auf kein Telefon — mobil als Karten."""
        lg, e, m, v = _basis_objekte()
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        buche('1020', '3000', Decimal('1500.00'), 'Miete August', datum=date(2026, 8, 1),
              liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/buchhaltung/?tab=journal').content.decode('utf-8')
        journal = html.split('id="bh-journal"')[1]
        self.assertIn('md:hidden', journal)          # Karten nur mobil
        self.assertIn('hidden md:block', journal)    # Tabelle nur ab Tablet
        # Beleg UND Betrag stehen in der Kartenansicht
        karten = journal.split('hidden md:block')[0]
        self.assertIn('Miete August', karten)
        self.assertIn("1'500.00", karten)

    def test_liegenschaft_detail_mit_dokument_stuerzt_nicht_ab(self):
        """Dokument.datum ist ein DateField — das Template formatierte es mit
        «H:i» und riss beim ersten abgelegten Dokument die ganze Seite in einen
        500er (TypeError: format for date objects may not contain 'H')."""
        import tempfile
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from portfolio.models import Dokument
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        ov = override_settings(MEDIA_ROOT=tmp.name); ov.enable()
        self.addCleanup(ov.disable)
        lg, e, m, v = _basis_objekte()
        Dokument.objects.create(
            liegenschaft=lg, titel='Hausordnung', kategorie='Allgemein',
            datum=date(2026, 5, 4),
            datei=SimpleUploadedFile('ho.pdf', b'%PDF-1.4', content_type='application/pdf'))
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/liegenschaften/{lg.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '04.05.2026')

    def test_tabellen_stapeln_sich_mobil_zentral(self):
        """Statt ~40 Templates einzeln: base.html stapelt jede Tabelle mit
        Kopfzeile unter 768 px zu «Spaltenname — Wert» pro Zeile."""
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/kreditoren/').content.decode('utf-8')
        self.assertIn('fwTabellenStapeln', html)                 # Skript ausgeliefert
        self.assertIn("table[data-stack]", html)                 # CSS vorhanden
        self.assertIn('@media (max-width: 767px)', html)         # nur mobil
        # display:block auf der Tabelle selbst — sonst misst der Browser die
        # Breite über eine anonyme Tabellenzelle wieder am Inhalt.
        self.assertIn('table[data-stack] { display: block;', html)

    def test_kontoblatt_hat_kartenansicht_fuers_handy(self):
        """Das Kontoblatt ist der nächste Klick aus der Erfolgsrechnung."""
        lg, e, m, v = _basis_objekte()
        from finance.booking import buche, ensure_kontenplan
        ensure_kontenplan()
        buche('1020', '3000', Decimal('1500.00'), 'Miete August', datum=date(2026, 8, 1),
              liegenschaft=lg)
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/buchhaltung/konto/3000/?jahr=2026').content.decode('utf-8')
        karten = html.split('hidden md:block')[0]
        self.assertIn('md:hidden', karten)
        self.assertIn('Miete August', karten)
        self.assertIn("1'500.00", karten)


# ============================================================
# Digitale Unterschrift auf den Brief-PDFs
# ============================================================

def _sig_bytes():
    """Kleines PNG als Ersatz für einen echten Unterschriften-Scan."""
    import io as _io
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (400, 120), "white")
    d = ImageDraw.Draw(img)
    d.line([(20, 90), (90, 30), (150, 95), (220, 35), (300, 80), (370, 45)],
           fill="black", width=6)
    b = _io.BytesIO(); img.save(b, format="PNG")
    return b.getvalue()


class GratismonatSichtbarTests(TestCase):
    """Ein voller Mietzins-Erlass darf nicht unbemerkt entstehen.

    Gemeldet: Eine Sollmietzins-Zeile zeigte «−500.00» Rabatt, obwohl kein
    Rabatt gewährt worden war. Die Zahl war echt (rabatt_netto = 500 in den
    Daten) — nur konnte niemand nachvollziehen, woher sie kam:

      - Anklickbar war das ganze, formularbreite Band über «Speichern». Ein
        Tipper, der knapp zu hoch landet, setzte einen 100-%-Erlass.
      - Sichtbar änderte sich dabei nichts: Das Rabatt-Feld blieb leer.
      - Die Bestätigung nannte nur eine Summe, in der der Erlass schon
        verrechnet war.
      - Die fertige Zeile sagte «−500.00» und sonst nichts.
    """

    def _erfassen(self, client, einheit, **extra):
        daten = {'einheit_id': einheit.id, 'gueltig_ab': '2026-01-01',
                 'netto_mietzins': '500', 'nebenkosten': '50'}
        daten.update(extra)
        return client.post('/neu/sollmietzins/', daten, follow=True)

    def test_ohne_ankreuzen_kein_rabatt(self):
        """Der Normalfall — sonst wäre alles Weitere sinnlos."""
        from portfolio.models import Sollmietzins
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._erfassen(c, e)
        s = Sollmietzins.objects.filter(einheit=e).order_by('-id').first()
        self.assertEqual(s.rabatt_netto, Decimal('0.00'))
        self.assertFalse(s.hat_rabatt)
        self.assertFalse(s.ist_voller_erlass)

    def test_voller_erlass_wird_als_solcher_erkannt(self):
        from portfolio.models import Sollmietzins
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._erfassen(c, e, mietzinsfrei='1')
        s = Sollmietzins.objects.filter(einheit=e).order_by('-id').first()
        self.assertEqual(s.rabatt_netto, Decimal('500.00'))
        self.assertTrue(s.ist_voller_erlass)
        self.assertEqual(s.verrechnet_brutto, Decimal('50.00'))

    def test_teilrabatt_ist_kein_voller_erlass(self):
        """Ein ausgehandelter Rabatt und ein Gratismonat sind nicht dasselbe."""
        from portfolio.models import Sollmietzins
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._erfassen(c, e, rabatt_netto='100')
        s = Sollmietzins.objects.filter(einheit=e).order_by('-id').first()
        self.assertTrue(s.hat_rabatt)
        self.assertFalse(s.ist_voller_erlass)

    def test_bestaetigung_benennt_den_vollen_erlass(self):
        """Die Meldung nannte bisher nur «zu zahlen CHF 50» — die Zahl allein
        verrät nicht, dass 500 erlassen wurden."""
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        html = self._erfassen(c, e, mietzinsfrei='1').content.decode('utf-8')
        self.assertIn('VOLLST', html.upper())
        self.assertIn('Gratismonat', html)

    def test_zeile_zeigt_woher_der_rabatt_kommt(self):
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._erfassen(c, e, mietzinsfrei='1')
        html = c.get(f'/neu/objekte/{e.id}/?tab=mietzins').content.decode('utf-8')
        self.assertIn('Gratismonat', html)

    def test_klickflaeche_umfasst_nicht_mehr_die_ganze_formularbreite(self):
        """Die Ursache selbst: Das Kästchen sass in einem <label>, das über die
        volle Formularbreite ging und direkt über «Speichern» lag."""
        import re
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/objekte/{e.id}/?tab=mietzins').content.decode('utf-8')
        # das <label> um das Kästchen herum finden
        stelle = html.find('name="mietzinsfrei"')
        self.assertGreater(stelle, -1, 'Gratismonat-Kästchen nicht gefunden')
        label = html.rfind('<label', 0, stelle)
        auf = html[label:stelle]
        self.assertNotIn('col-span-4', auf,
                         'Klickfläche geht wieder über die ganze Formularbreite')


class GeldKaestchenTests(TestCase):
    """Dieselbe Falle wie beim Gratismonat, an den übrigen Geld-Kästchen.

    Ein <label> mit `col-span` macht die ganze Formularzeile anklickbar. Liegt
    sie neben oder über dem Speichern-Knopf, schaltet ein danebengegangener
    Tipper eine Geld-Entscheidung um — ohne dass sich sichtbar etwas ändert.
    Betroffen waren:

      Anlagen     «Aktivierung buchen» (bucht 1500 an Gegenkonto)
      Kreditoren  «In Nebenkostenabrechnung einbeziehen» (3×) — entscheidet,
                  ob eine Rechnung den Mietern weiterverrechnet wird
    """

    def _kaestchen_mit_breiter_klickflaeche(self):
        import re, pathlib
        LABEL = re.compile(r'<label\b([^>]*)>(.*?)</label>', re.S | re.I)
        treffer = []
        for p in sorted(pathlib.Path('core/templates/fw').rglob('*.html')):
            s = p.read_text(encoding='utf-8')
            for m in LABEL.finditer(s):
                attrs, inner = m.group(1), m.group(2)
                if 'type="checkbox"' not in inner:
                    continue
                if 'col-span' not in attrs:
                    continue
                name = re.search(r'name="([^"]+)"', inner)
                treffer.append(f"{p}:{s[:m.start()].count(chr(10)) + 1} "
                               f"[{name.group(1) if name else '?'}]")
        return treffer

    def test_kein_geld_kaestchen_mit_formularbreiter_klickflaeche(self):
        breit = self._kaestchen_mit_breiter_klickflaeche()
        self.assertEqual(breit, [], "Kästchen mit formularbreiter Klickfläche:\n  " +
                                    "\n  ".join(breit))

    def test_pruefung_findet_eine_eingebaute_breite_klickflaeche(self):
        """Gegenprobe — eine Suche, die nie etwas findet, bestätigt jede Vorlage."""
        import pathlib, os
        pfad = pathlib.Path('core/templates/fw/_test_breites_kaestchen.html')
        pfad.write_text('<label class="sm:col-span-4 flex">'
                        '<input type="checkbox" name="probe"></label>\n', encoding='utf-8')
        try:
            self.assertTrue(any('probe' in t for t in self._kaestchen_mit_breiter_klickflaeche()))
        finally:
            os.remove(pfad)

    def test_aktivierung_wird_gebucht(self):
        """Die Buchung hing an `POST.get('aktivieren') == 'on'` — dem Wert, den
        der Browser nur ohne value-Attribut sendet. Hier wird geprüft, dass die
        Buchung an der Anwesenheit hängt, nicht an dieser Zeichenkette."""
        from finance.models import Buchung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        for wert, kennzeichen in (('1', 'value-Attribut'), ('on', 'ohne value')):
            Buchung.objects.all().delete()
            c.post('/neu/anlagen/', {
                'aktion': 'anlage_neu', 'bezeichnung': f'Heizung {kennzeichen}',
                'liegenschaft_id': lg.id, 'anschaffungswert': '12000',
                'anschaffungsdatum': '2026-01-15', 'nutzungsdauer_jahre': '10',
                'gegenkonto': '2000', 'aktivieren': wert}, follow=True)
            self.assertTrue(
                Buchung.objects.filter(soll_konto__nummer='1500').exists(),
                f'Aktivierung wurde bei «{kennzeichen}» nicht gebucht')

    def test_ohne_haekchen_keine_aktivierung(self):
        """Der Gegenfall — sonst könnte die Prüfung oben auch dann bestehen,
        wenn immer gebucht würde."""
        from finance.models import Buchung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/anlagen/', {
            'aktion': 'anlage_neu', 'bezeichnung': 'Lift',
            'liegenschaft_id': lg.id, 'anschaffungswert': '9000',
            'anschaffungsdatum': '2026-01-15', 'nutzungsdauer_jahre': '20',
            'gegenkonto': '2000'}, follow=True)
        self.assertFalse(Buchung.objects.filter(soll_konto__nummer='1500').exists())

    def test_hnk_steht_an_der_rechnungszeile(self):
        """Ob eine Rechnung den Mietern weiterverrechnet wird, stand nur an den
        Teilpositionen — an der Rechnung selbst war es unsichtbar."""
        from finance.models import KreditorenRechnung
        lg, e, m, v = _basis_objekte()
        r = KreditorenRechnung.objects.create(
            lieferant='Heizöl AG', liegenschaft=lg, betrag=Decimal('4000'),
            datum=date(2026, 1, 10), status='neu', is_hnk_relevant=False)
        c = Client(); c.force_login(_team_user())
        # Auf das Abzeichen prüfen, nicht auf die Zeichenkette «HNK» — die steht
        # ohnehin im Erfassungsformular, der Test wäre sonst immer grün.
        abzeichen = 'title="Wird in die Nebenkostenabrechnung einbezogen'
        ohne = c.get('/neu/kreditoren/').content.decode('utf-8')
        self.assertNotIn(abzeichen, ohne)
        r.is_hnk_relevant = True
        r.save(update_fields=['is_hnk_relevant'])
        mit = c.get('/neu/kreditoren/').content.decode('utf-8')
        self.assertIn(abzeichen, mit)


class DebitorenStatusETests(TestCase):
    """Live-Test E: Statusprüfungen im Debitoren-/Mahnwesen.

    - Gratismonat (Netto-Schuld 0) darf keinen offenen 0.00-Posten erzeugen.
    - Bezahlte/stornierte Forderung nicht mahnen; kein Mahnstufen-Rückschritt.
    - Mahngebühr wird mit der Hauptforderung mitstorniert.
    - Kein QR-Einzahlungsschein für eine nicht mehr offene Forderung.
    """

    def _offene_rechnung(self, lg, v, betrag='1500.00', mit_buchung=True):
        from finance.models import DebitorenRechnung
        from finance.booking import buche
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete 05/2024',
            datum=date(2024, 5, 1), faellig_am=date(2024, 5, 5),
            betrag=Decimal(betrag), status='offen')
        if mit_buchung:
            buche('1100', '3000', Decimal(betrag), 'Miete 05/2024',
                  datum=date(2024, 5, 1), liegenschaft=lg, debitor=r)
        return r

    def test_e_gratismonat_erzeugt_keinen_offenen_posten(self):
        from finance.booking import ensure_kontenplan
        from finance.models import DebitorenRechnung
        from rentals.models import VertragMietzins
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        # Gratismonat: Referenz 1500/200, voller Erlass → Verrechnung 0
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2024, 1, 1),
                                       netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                                       rabatt_netto=Decimal('1500'), rabatt_nk=Decimal('200'))
        from core.services.automation import run_sollstellung
        run_sollstellung(2024, 6)
        r = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 06/2024')
        self.assertEqual(r.betrag, Decimal('0.00'))
        self.assertEqual(r.status, 'bezahlt')          # kein offener Posten
        self.assertEqual(r.offener_betrag, Decimal('0.00'))

    def test_e_mahnung_nicht_auf_bezahlte_forderung(self):
        from finance.booking import ensure_kontenplan
        from finance.models import Mahnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = self._offene_rechnung(lg, v)
        r.status = 'bezahlt'; r.save(update_fields=['status'])
        c = Client(); c.force_login(_team_user('Verwaltung'))
        resp = c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': str(r.id), 'stufe': '1'}, follow=True)
        self.assertEqual(Mahnung.objects.filter(debitoren_rechnung=r).count(), 0)
        self.assertContains(resp, 'nicht (mehr) offen')

    def test_e_kein_mahnstufen_rueckschritt(self):
        from finance.booking import ensure_kontenplan
        from finance.models import Mahnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = self._offene_rechnung(lg, v)
        Mahnung.objects.create(debitoren_rechnung=r, vertrag=v, stufe=2, datum=date(2024, 6, 1))
        c = Client(); c.force_login(_team_user('Verwaltung'))
        c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': str(r.id), 'stufe': '1'})
        # Keine neue (niedrigere) Mahnung erfasst — Stufe 2 bleibt die einzige.
        self.assertEqual(Mahnung.objects.filter(debitoren_rechnung=r).count(), 1)
        self.assertEqual(Mahnung.objects.filter(debitoren_rechnung=r).first().stufe, 2)

    def test_e_mahngebuehr_wird_mit_hauptforderung_storniert(self):
        from finance.booking import ensure_kontenplan
        from finance.models import DebitorenRechnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r = self._offene_rechnung(lg, v)
        c = Client(); c.force_login(_team_user('Verwaltung'))
        # 2. Mahnung → Mahngebühr CHF 20 als eigene Debitorenrechnung mit stammrechnung=r
        c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': str(r.id), 'stufe': '2'})
        geb = DebitorenRechnung.objects.get(stammrechnung=r)
        self.assertEqual(geb.status, 'offen')
        # Hauptforderung stornieren → Mahngebühr wird mitstorniert
        c.post(f'/neu/debitoren/{r.id}/stornieren/', {})
        r.refresh_from_db(); geb.refresh_from_db()
        self.assertEqual(r.status, 'storniert')
        self.assertEqual(geb.status, 'storniert')

    def test_e_qr_beleg_nicht_fuer_nicht_offene_rechnung(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        # Liegenschaft/Verwaltung ohne IBAN würde ohnehin 400 geben — Status-Gate
        # muss VORHER greifen (409), sonst wäre der Test nicht aussagekräftig.
        lg.iban = 'CH9300762011623852957'; lg.save()
        r = self._offene_rechnung(lg, v, mit_buchung=False)
        r.status = 'bezahlt'; r.save(update_fields=['status'])
        c = Client(); c.force_login(_team_user('Verwaltung'))
        resp = c.get(f'/neu/debitoren/{r.id}/qr-pdf/')
        self.assertEqual(resp.status_code, 409)


class KostenkontrolleAddJTests(TestCase):
    """Live-Test J: |add coerct Decimals nach int und schnitt die Rappen ab."""

    def test_j_kostensumme_behaelt_rappen(self):
        from tickets.models import SchadenMeldung, HandwerkerAuftrag
        from crm.models import Handwerker
        lg, e, m, v = _basis_objekte()
        hw = Handwerker.objects.create(firma='Sanitär AG')
        s = SchadenMeldung.objects.create(liegenschaft=lg, titel='Leck', beschreibung='x')
        HandwerkerAuftrag.objects.create(ticket=s, handwerker=hw, kosten_effektiv=Decimal('10.50'))
        HandwerkerAuftrag.objects.create(ticket=s, handwerker=hw, kosten_geschaetzt=Decimal('5.25'))  # offen
        c = Client(); c.force_login(_team_user('Verwaltung'))
        r = c.get('/neu/schaeden/kosten/')
        self.assertEqual(r.context['total']['gesamt'], Decimal('15.75'))
        self.assertEqual(r.context['rows'][0]['gesamt'], Decimal('15.75'))
        # Und im gerenderten HTML stehen die Rappen (nicht auf 15 abgeschnitten)
        self.assertContains(r, "15.75")


class InboxMahnenTests(TestCase):
    """Die «Mahnen»-Aufgabe der Inbox verschwindet, sobald die für die
    Überfälligkeit fällige Mahnstufe erfasst ist."""

    def test_gemahnte_forderung_faellt_aus_mahnen(self):
        from finance.models import DebitorenRechnung, Mahnung
        from core.services.inbox import sammle_inbox
        lg, e, m, v = _basis_objekte()
        heute = date.today()
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete',
            datum=heute - timedelta(days=65), faellig_am=heute - timedelta(days=65),
            betrag=Decimal('1700'), status='offen')
        # Ohne Mahnung: die Forderung erscheint als «mahnen».
        eintraege, _, _ = sammle_inbox()
        self.assertTrue(any('mahnen' in x['titel'].lower() for x in eintraege))
        # 3. Mahnung erfasst (Default-Config: Stufe 3 ab 60 Tagen fällig) → weg.
        Mahnung.objects.create(debitoren_rechnung=r, vertrag=v, stufe=3, datum=heute,
                               betrag_offen=Decimal('1700'))
        eintraege2, _, _ = sammle_inbox()
        self.assertFalse(any('mahnen' in x['titel'].lower() for x in eintraege2))


class MahngebuehrStornoTests(TestCase):
    """Storno einer Mahngebühr-Forderung nullt die Gebühr auch in der Mahn-Historie
    (finance.Mahnung.gebuehr) — sonst zeigt die Historie weiter z.B. 40.-."""

    def _stale(self):
        from finance.models import DebitorenRechnung, Mahnung
        lg, e, m, v = _basis_objekte()
        heute = date.today()
        orig = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Miete',
            datum=heute - timedelta(days=60), faellig_am=heute - timedelta(days=60),
            betrag=Decimal('1700'), status='offen')
        mn = Mahnung.objects.create(debitoren_rechnung=orig, vertrag=v, stufe=3,
                                    datum=heute, betrag_offen=Decimal('1700'),
                                    gebuehr=Decimal('40.00'))
        fee = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, titel='Mahngebühr 3. Mahnung',
            datum=heute, faellig_am=heute, betrag=Decimal('40.00'),
            status='offen', stammrechnung=orig)
        return v, orig, mn, fee

    def test_storno_nullt_historien_gebuehr(self):
        v, orig, mn, fee = self._stale()
        c = Client(); c.force_login(_team_user())
        r = c.post(f'/neu/debitoren/{fee.id}/stornieren/', secure=True)
        self.assertEqual(r.status_code, 302)
        fee.refresh_from_db(); mn.refresh_from_db()
        self.assertEqual(fee.status, 'storniert')
        self.assertEqual(mn.gebuehr, Decimal('0.00'))
        self.assertIn('storniert', mn.bemerkung)

    def test_migration_bereinigt_altbestand(self):
        """Bereits stornierte Gebühr, Historie noch 40.- → Reconcile-Migration nullt sie;
        eine noch offene Gebühr bleibt unangetastet."""
        import importlib
        recon = importlib.import_module(
            'finance.migrations.0032_reconcile_stornierte_mahngebuehr')
        from django.apps import apps as _apps
        # Fall A: Gebühr storniert → Historie muss auf 0.
        v, orig, mn, fee = self._stale()
        fee.status = 'storniert'; fee.save(update_fields=['status'])
        # Fall B: gültige, offene Gebühr → bleibt.
        from finance.models import DebitorenRechnung, Mahnung
        lg2, e2, m2, v2 = _basis_objekte()
        heute = date.today()
        orig2 = DebitorenRechnung.objects.create(
            vertrag=v2, liegenschaft=lg2, titel='Miete',
            datum=heute - timedelta(days=60), betrag=Decimal('1700'), status='offen')
        mn2 = Mahnung.objects.create(debitoren_rechnung=orig2, vertrag=v2, stufe=3,
                                     datum=heute, betrag_offen=Decimal('1700'),
                                     gebuehr=Decimal('40.00'))
        DebitorenRechnung.objects.create(
            vertrag=v2, liegenschaft=lg2, titel='Mahngebühr 3. Mahnung',
            datum=heute, betrag=Decimal('40.00'), status='offen', stammrechnung=orig2)
        recon.reconcile(_apps, None)
        mn.refresh_from_db(); mn2.refresh_from_db()
        self.assertEqual(mn.gebuehr, Decimal('0.00'))     # storniert → bereinigt
        self.assertEqual(mn2.gebuehr, Decimal('40.00'))   # gültig → unangetastet
