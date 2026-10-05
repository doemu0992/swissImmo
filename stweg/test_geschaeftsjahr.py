"""Ein ganzes Geschäftsjahr einer STWEG-Gemeinschaft — von der Gründung bis zum Gemeinschaftspfandrecht.

«Seeblick 12»: drei Einheiten, Quoten 200/300/500 von 1000.
    A  EG     200  Anna     (zahlt alles)
    B  1. OG  300  Bruno    (zahlt alles)
    C  2. OG  500  Carla    (zahlt 2026 pünktlich, schuldet aber seit 2023/2024 Raten und zahlt die Nachzahlung nicht)

Verteilschlüssel: «Allgemeine Wertquote» (Hauswartung) und «Lift» nach Stockwerk (EG 0, 1. OG 1, 2. OG 2).
Budget 2026: Hauswartung 6'000, Lift 1'800 — zwölf Monatsraten. Ist-Kosten: Hauswartung 6'480.55, Lift 2'101.10.
Jede Zahl unten ist von Hand gerechnet; das Programm muss auf denselben Rappen kommen."""
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone
from pypdf import PdfReader

from core.tests._helfer import _team_user, _test_organisation
from crm.models import Eigentuemer
from finance.booking import konto as konto_nr
from finance.models import Buchung, Buchungskonto, KreditorenRechnung
from portfolio.models import Einheit, Liegenschaft
from stweg import budget as bd
from stweg import hauptbuch, inkasso, integritaet
from stweg.beschluss import anwesenheit_setzen, feststellen, stimme_abgeben
from stweg.fonds import jahreseinlage_belasten
from stweg.konto import kontokorrent
from stweg.models import (StwegBudget, StwegKostenzuordnung, StwegPfandrecht, StwegVorschreibung, Traktandum,
                          Versammlung)
from stweg.pdf import mahnung_pdf, pfandrecht_pdf
from stweg.schluessel import kostenart_zuordnen, lift_nach_stockwerk, standard_schluessel
from stweg.services import StwegAbrechnungService
from stweg.validierung import WertquotenFehler

User = get_user_model()
D = Decimal
IBAN = 'CH9300762011623852957'


def saldo(nummer, lg):
    k = konto_nr(nummer)
    qs = Buchung.objects.filter(liegenschaft=lg)
    soll = sum((b.betrag for b in qs.filter(soll_konto=k)), D('0'))
    haben = sum((b.betrag for b in qs.filter(haben_konto=k)), D('0'))
    return soll - haben


def text(pdf):
    return ''.join(p.extract_text() for p in PdfReader(__import__('io').BytesIO(pdf)).pages)


class Geschaeftsjahr2026(TestCase):
    def setUp(self):
        self.org = _test_organisation()
        self.verwalter = _team_user('Verwalter')
        self.zahlungen = D('0')                  # alles, was auf der Bank eingeht (unabhängige Mitschrift)

    # ── Hilfen ────────────────────────────────────────────────────────────────────────────────
    def zahle(self, einheit, betrag, datum, **kw):
        z = hauptbuch.zahlung_erfassen(einheit, D(betrag), datum, user=self.verwalter, **kw)
        self.zahlungen += D(betrag)
        return z

    def rate(self, einheit, jahr, nr):
        return StwegVorschreibung.objects.get(einheit=einheit, budget__jahr=jahr, rate_nr=nr)

    def jahres_budget(self, jahr, *, genehmigen=True):
        b = StwegBudget.objects.create(liegenschaft=self.lg, jahr=jahr, raten=12, erste_faelligkeit=date(jahr, 1, 1))
        bd.position_setzen(b, f'Hauswartung {jahr}', standard_schluessel(self.lg), D('6000'))
        bd.position_setzen(b, f'Liftwartung {jahr}', self.lift, D('1800'))
        bd.vorlegen(b)
        if genehmigen:
            bd.budget_genehmigen(b)
        return b

    # ── Das Jahr ──────────────────────────────────────────────────────────────────────────────
    def test_das_geschaeftsjahr(self):
        # 1 ── Gründung: drei Eigentümer, Quoten 200/300/500 ─────────────────────────────────────
        lg = self.lg = Liegenschaft.objects.create(
            strasse='Seeblick 12', plz='8002', ort='Zürich', kanton='ZH', typ='STWEG', status='entwurf',
            wertquote_total=1000, iban=IBAN, organisation=self.org)
        einheiten = {}
        for kurz, bez, etage, quote, name in (('A', 'Whg EG', 'EG', 200, 'Anna'), ('B', 'Whg 1. OG', '1. OG', 300, 'Bruno'),
                                              ('C', 'Whg 2. OG', '2. OG', 500, 'Carla')):
            e = Einheit.objects.create(liegenschaft=lg, bezeichnung=bez, typ='stwe', etage=etage, wertquote=D(quote))
            e.stockwerkeigentuemer = Eigentuemer.objects.create(
                firma_oder_name=name, email=f'{name.lower()}@x.ch', strasse='Seestrasse 1', plz='8002', ort='Zürich')
            e.save()
            einheiten[kurz] = e
        A, B, C = einheiten['A'], einheiten['B'], einheiten['C']
        C.wertquote = D('499')                                      # 999/1000: die Aktivierung muss scheitern
        C.save()
        lg.status = 'aktiv'
        with self.assertRaises(WertquotenFehler):
            lg.save()
        C.wertquote = D('500')
        C.save()
        lg.refresh_from_db()
        lg.status = 'aktiv'
        lg.save()
        self.assertEqual(integritaet.pruefe(lg), [(integritaet.HINWEIS, 'Es ist noch kein Standardschlüssel angelegt '
                                                   '(entsteht beim ersten Budget).')])

        # 2 ── Verteilschlüssel: Hauswartung nach Wertquote, Lift nach Stockwerk ──────────────────
        self.lift = lift_nach_stockwerk(lg)
        gewichte = {a.einheit_id: a.anteil for a in self.lift.anteile.all()}
        self.assertEqual((gewichte[A.pk], gewichte[B.pk], gewichte[C.pk]), (D('0'), D('1'), D('2')))
        k_hauswart = konto_nr('4120')                                 # Hauswartung & Reinigung (Standardkonto)
        k_lift = Buchungskonto.objects.create(organisation=self.org, nummer='4160', bezeichnung='Liftwartung',
                                              typ='aufwand')
        kostenart_zuordnen(lg, k_lift, self.lift)

        # 3 ── Vorgeschichte: Budgets 2023–2025; Carla zahlt 2023 und 2024 nichts, 2025 alles ──────
        for jahr in (2023, 2024, 2025):
            self.jahres_budget(jahr)
            for e, monat in ((A, D('100')), (B, D('200'))):
                for nr in range(1, 13):
                    self.zahle(e, monat, date(jahr, nr, 3), vorschreibung=self.rate(e, jahr, nr))
        for nr in range(1, 13):
            self.zahle(C, D('350'), date(2025, nr, 3), vorschreibung=self.rate(C, 2025, nr))

        # 4 ── Jahresbudget 2026 und die Versammlung, die es genehmigt (Doppeltes Mehr) ───────────
        b26 = StwegBudget.objects.create(liegenschaft=lg, jahr=2026, raten=12, erste_faelligkeit=date(2026, 1, 1))
        bd.position_setzen(b26, 'Hauswartung 2026', standard_schluessel(lg), D('6000'))
        bd.position_setzen(b26, 'Liftwartung 2026', self.lift, D('1800'))
        jb = {e.bezeichnung: d['summe'] for e, d in bd.jahresbetraege(b26).items()}
        # Hauswartung 6000 nach 200/300/500 = 1200/1800/3000; Lift 1800 nach 0/1/2 = 0/600/1200
        self.assertEqual(jb, {'Whg EG': D('1200.00'), 'Whg 1. OG': D('2400.00'), 'Whg 2. OG': D('4200.00')})
        bd.vorlegen(b26)
        v = Versammlung.objects.create(liegenschaft=lg, titel='Ordentliche Versammlung 2025', art='ordentlich',
                                       datum=timezone.now() - timedelta(days=1), status='durchgefuehrt')
        t = Traktandum.objects.create(versammlung=v, nr=1, titel='Budget 2026', mehrheitsart='doppelt_aller')
        bd.an_traktandum_haengen(t, b26)
        for e in einheiten.values():
            anwesenheit_setzen(v, e, 'anwesend')
            stimme_abgeben(t, e, 'ja' if e is not C else 'nein')       # 500 Nein, 500 Ja → doppelt_aller scheitert
        t.refresh_from_db()
        from stweg.beschluss import auswerten
        self.assertEqual(auswerten(t)['vorschlag'], 'abgelehnt')       # 2 von 3 Köpfen, aber nur 500 von 1000 Quoten
        stimme_abgeben(t, C, 'ja')
        feststellen(t, 'angenommen')
        b26.refresh_from_db()
        self.assertEqual(b26.status, 'genehmigt')
        self.assertEqual(StwegVorschreibung.objects.filter(budget=b26).count(), 36)
        self.assertEqual({(r.einheit.bezeichnung, r.betrag) for r in StwegVorschreibung.objects.filter(budget=b26)},
                         {('Whg EG', D('100.00')), ('Whg 1. OG', D('200.00')), ('Whg 2. OG', D('350.00'))})
        # Eigentümer A zahlt im EG nie einen Rappen Lift:
        for r in StwegVorschreibung.objects.filter(budget=b26, einheit=A):
            self.assertEqual([x['betrag'] for x in r.aufteilung if x['schluessel'] == self.lift.name], ['0.00'])

        # 5 ── Monatliche Akonto-Zahlungen 2026: alle pünktlich ───────────────────────────────────
        for nr in range(1, 13):
            for e, betrag in ((A, '100'), (B, '200'), (C, '350')):
                self.zahle(e, betrag, date(2026, nr, 3), vorschreibung=self.rate(e, 2026, nr))

        # 6 ── Drei Belege: Hauswartung, Liftwartung (Kreditoren, verbucht) und Einlage Erneuerungsfonds ──
        client = Client()
        client.force_login(self.verwalter)
        for lieferant, betrag, kto, datum in (('Hauswart AG', '6480.55', k_hauswart, date(2026, 12, 15)),
                                              ('Lift AG', '2101.10', k_lift, date(2026, 12, 20))):
            r = KreditorenRechnung.objects.create(liegenschaft=lg, lieferant=lieferant, betrag=D(betrag),
                                                  datum=datum, status='neu')
            antwort = client.post(f'/neu/kreditoren/{r.pk}/freigeben/', {'konto_id': kto.pk})
            self.assertEqual(antwort.status_code, 302)
            r.refresh_from_db()
            self.assertEqual(r.status, 'freigegeben')
        einlage = jahreseinlage_belasten(lg, 2026, D('3000'), datum=date(2026, 12, 31), user=self.verwalter)
        self.assertEqual([einlage[A], einlage[B], einlage[C]], [D('600.00'), D('900.00'), D('1500.00')])
        self.assertEqual(saldo('2800', lg), D('-3000.00'))            # Passivum: Schuld der Gemeinschaft gegenüber sich selbst
        self.assertEqual(konto_nr('2800').typ, 'passiv')
        for e, betrag in ((A, '600'), (B, '900'), (C, '1500')):
            self.zahle(e, betrag, date(2027, 1, 10), zweck='fonds')

        # 7 ── Jahresabrechnung: Ist-Kosten nach den Schlüsseln, Akonto abgezogen ───────────────────
        a = StwegAbrechnungService(lg).abrechnen(2026)
        self.assertEqual(a.gesamtkosten, D('8581.65'))
        p = {x.einheit.bezeichnung: x for x in a.positionen.select_related('einheit')}
        # Hauswartung 6480.55 nach 200/300/500: 1296.11 / 1944.17 / 3240.27 (die Rappen gehen an die grössten Reste)
        # Lift 2101.10 nach 0/1/2:             0.00  /  700.37 / 1400.73
        self.assertEqual(p['Whg EG'].kostenanteil, D('1296.11'))
        self.assertEqual(p['Whg 1. OG'].kostenanteil, D('2644.54'))
        self.assertEqual(p['Whg 2. OG'].kostenanteil, D('4641.00'))
        self.assertEqual(sum(x.kostenanteil for x in p.values()), a.gesamtkosten)       # auf den Rappen
        lift_je = {n: x.schluesselanteile.get(schluessel_name=self.lift.name).betrag for n, x in p.items()}
        self.assertEqual(lift_je, {'Whg EG': D('0.00'), 'Whg 1. OG': D('700.37'), 'Whg 2. OG': D('1400.73')})
        self.assertEqual({n: x.akonto for n, x in p.items()},
                         {'Whg EG': D('1200.00'), 'Whg 1. OG': D('2400.00'), 'Whg 2. OG': D('4200.00')})
        self.assertEqual({n: x.saldo for n, x in p.items()},
                         {'Whg EG': D('96.11'), 'Whg 1. OG': D('244.54'), 'Whg 2. OG': D('441.00')})
        StwegAbrechnungService.abschliessen(a, user=self.verwalter)
        a.refresh_from_db()
        self.assertEqual(a.status, 'abgeschlossen')

        # 8 ── Anna und Bruno zahlen ihre Nachzahlung, Carla nicht ─────────────────────────────────
        self.zahle(A, '96.11', date(2027, 2, 10))
        self.zahle(B, '244.54', date(2027, 2, 10))
        stichtag = date(2027, 4, 20)
        for e in (A, B):
            self.assertEqual(inkasso.offener_betrag(e, stichtag), D('0.00'))
            self.assertEqual(kontokorrent(e, heute=stichtag)['saldo_total'], D('0.00'))
        self.assertEqual(inkasso.offener_betrag(C, stichtag), D('8841.00'))   # 2023: 4200, 2024: 4200, Nachzahlung 441

        # 9 ── Inkasso gegen Carla: drei Mahnungen — ohne Kündigungsandrohung ───────────────────────
        mails = []
        for i, heute in enumerate((date(2027, 2, 15), date(2027, 3, 5), date(2027, 3, 25)), start=1):
            m = inkasso.mahnung_erstellen(C, heute=heute)
            self.assertEqual((m.stufe, m.betrag), (i, D('8841.00')))
            with mock.patch('core.utils.email_service.send_via_hoststar', return_value=True) as sende:
                self.assertEqual(inkasso.mahnung_versenden(m), 'email')
            mails.append(sende.call_args[0][2])
            t_pdf = text(mahnung_pdf(m))
            for ausgabe in (t_pdf, mails[-1]):
                self.assertNotIn('ündig', ausgabe)
                self.assertNotIn('257d', ausgabe)
            self.assertIn("8'841.00", t_pdf)
        self.assertIn('Art. 712k ZGB', t_pdf)                             # die dritte nennt Retention und Pfandrecht
        fall = inkasso.offener_fall(C)
        self.assertEqual(inkasso.mahnstufe(fall), 3)

        # 10 ── Retentionsrecht und Gemeinschaftspfandrecht: nur die letzten 36 Monate ───────────────
        inkasso.retention_geltend_machen(fall, 'Möbel und Hausrat in der Wohnung 2. OG', heute=stichtag)
        pf = inkasso.pfandrecht_anmelden(fall, stichtag=stichtag, user=self.verwalter)
        self.assertEqual(pf.stichtag, stichtag)
        # Grenze: 20.04.2024. Pfandberechtigt: Raten 01.05.–01.12.2024 (8 × 350 = 2800) und die Nachzahlung 2026 (441).
        # Nicht pfandberechtigt: 2023 (12 × 350 = 4200) und 01.01.–01.04.2024 (4 × 350 = 1400).
        self.assertEqual(pf.betrag_pfandberechtigt, D('3241.00'))
        self.assertEqual(pf.betrag_ausgeschlossen, D('5600.00'))
        self.assertEqual(pf.betrag_gesamt, D('8841.00'))
        self.assertEqual(pf.betrag_pfandberechtigt + pf.betrag_ausgeschlossen, pf.betrag_gesamt)
        datiert = [(date.fromisoformat(z['datum']), z['pfandberechtigt']) for z in pf.zeilen if z['art'] == 'akonto']
        self.assertEqual(min(d for d, drin in datiert if drin), date(2024, 5, 1))
        self.assertEqual(max(d for d, drin in datiert if not drin), date(2024, 4, 1))
        self.assertEqual(sum(1 for d, drin in datiert if drin), 8)
        self.assertEqual(sum(1 for d, drin in datiert if not drin), 16)
        t_pf = text(pfandrecht_pdf(pf))
        for erwartet in ('Grundbuchamt Zürich (ZH)', 'Art. 712i ZGB', "Pfandsumme: CHF 3'241.00", 'Carla', 'Whg 2. OG',
                         "NICHT in der Pfandsumme: CHF 5'600.00", 'Abrechnung 2026', '20.04.2024', 'Unterschrift'):
            self.assertIn(erwartet, t_pf)
        self.assertNotIn('ündig', t_pf)
        self.assertEqual(StwegPfandrecht.objects.count(), 1)

        # 11 ── Bücher: Hauptbuch und Fachtabellen stimmen auf den Rappen überein ───────────────────
        ab = integritaet.abstimmung_hauptbuch(lg)
        self.assertEqual({k: v['differenz'] for k, v in ab.items()}, {'1110': D('0'), '2035': D('0'), '3100': D('0'),
                                                                      '2800': D('0')})
        self.assertEqual(saldo('3100', lg), D('-8581.65'))                 # Beiträge = Kostenanteile
        self.assertEqual(saldo('4120', lg) + saldo('4160', lg), D('8581.65'))   # Aufwand der Gemeinschaft
        self.assertEqual(saldo('3100', lg) + saldo('4120', lg) + saldo('4160', lg), D('0.00'))  # Jahresergebnis null
        self.assertEqual(saldo('2035', lg), D('-23400.00'))                # Akonto 2023–2025 (3 × 7800), 2026 freigegeben
        self.assertEqual(saldo('1110', lg), D('8841.00'))                  # genau Carlas offene Forderung
        self.assertEqual(saldo('1020', lg), self.zahlungen)                # die Bank hat, was bezahlt wurde
        self.assertEqual(saldo('2800', lg), D('-3000.00'))
        self.assertEqual([b for b in integritaet.pruefe(lg) if b[0] in (integritaet.FEHLER, integritaet.WARNUNG)], [])
        # Und kein Eigentümer dieser Gemeinschaft hat je ein Schreiben mit Kündigungsandrohung erhalten.
        self.assertFalse(any('ündig' in m or '257d' in m for m in mails))
        self.assertEqual(StwegKostenzuordnung.objects.count(), 1)
