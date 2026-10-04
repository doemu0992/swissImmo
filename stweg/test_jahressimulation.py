"""Ein ganzes STWEG-Jahr, digital: Budget → Einladung → E-Voting (Doppeltes Mehr) → Akonto-Rechnungen →
Zahlungen → Jahresabrechnung → Kontokorrent.

Die Gemeinschaft «Liftweg 5» hat fünf Einheiten, 1000/1000 Wertquoten:
    A  EG       100      D  3. OG   350
    B  1. OG    100      E  Attika  350
    C  2. OG    100
Zwei Verteilschlüssel: «Allgemeine Wertquote» (Versicherung, Hauswart) und «Lift» (EG trägt nichts)."""
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from core.tests._helfer import _team_user, _test_organisation
from crm.models import Eigentuemer
from finance.models import Buchungskonto
from portfolio.models import Einheit, Liegenschaft
from stweg import budget as bd
from stweg import evoting
from stweg.beschluss import auswerten, feststellen
from stweg.konto import kontokorrent
from stweg.models import (StwegAbrechnung, StwegAkonto, StwegBudget, StwegVorschreibung, Traktandum,
                          Versammlung)
from stweg.schluessel import kostenart_zuordnen, lift_schluessel, standard_schluessel
from stweg.services import StwegAbrechnungService
from stweg.tests import rechnung
from stweg.versammlung import VersammlungsFehler, durchfuehren, einladung_versenden, protokoll_versenden

User = get_user_model()
D = Decimal


class DigitalesStwegJahr(TestCase):
    def setUp(self):
        lg = Liegenschaft.objects.create(strasse='Liftweg 5', plz='8000', ort='Zürich', typ='STWEG',
                                         status='entwurf', wertquote_total=1000,
                                         organisation=_test_organisation())
        daten = [('A', 'EG', 100), ('B', '1. OG', 100), ('C', '2. OG', 100), ('D', '3. OG', 350), ('E', 'Attika', 350)]
        self.e, self.eig, self.clients = {}, {}, {}
        for name, etage, q in daten:
            self.e[name] = Einheit.objects.create(liegenschaft=lg, bezeichnung=f'Whg {name}', typ='stwe',
                                                  etage=etage, wertquote=D(q), flaeche_m2=D(80))
            self.eig[name] = Eigentuemer.objects.create(firma_oder_name=f'Eigentümer {name}',
                                                        email=f'{name.lower()}@x.ch')
            self.e[name].stockwerkeigentuemer = self.eig[name]
            self.e[name].save()
            u = User.objects.create_user(username=f'eig_{name}', password='x')
            self.eig[name].benutzer = u
            self.eig[name].save()
            c = Client()
            c.force_login(u)
            self.clients[name] = c
        lg.status = 'aktiv'
        lg.save()
        self.lg = lg
        self.k_allg = Buchungskonto.objects.create(organisation=lg.organisation, nummer='4100',
                                                   bezeichnung='Versicherung/Hauswart', typ='aufwand')
        self.k_lift = Buchungskonto.objects.create(organisation=lg.organisation, nummer='4200',
                                                   bezeichnung='Lift', typ='aufwand')
        self.verwaltung = Client()
        self.verwaltung.force_login(_team_user('Verwaltung'))

    def stimmen(self, versammlung, traktandum, werte):
        """Jeder Eigentümer stimmt über das PORTAL ab, mit seinem eigenen Konto."""
        for name, wert in werte.items():
            antwort = self.clients[name].post(f'/portal/stweg/evoting/{versammlung.pk}/',
                                              {f'stimme_{traktandum.pk}_{self.e[name].pk}': wert})
            self.assertEqual(antwort.status_code, 302)

    def test_das_ganze_jahr(self):
        lg = self.lg
        # ── 1. Budget der Verwaltung ─────────────────────────────────────────────────────────
        lift = lift_schluessel(lg)
        kostenart_zuordnen(lg, self.k_lift, lift)
        b = StwegBudget.objects.create(liegenschaft=lg, jahr=2026, raten=4, erste_faelligkeit=date(2026, 1, 1))
        bd.position_setzen(b, 'Versicherung und Hauswart', standard_schluessel(lg), D('12000'))
        bd.position_setzen(b, 'Liftwartung und -reparaturen', lift, D('4000'))
        jb = {e.bezeichnung: d for e, d in bd.jahresbetraege(b).items()}
        self.assertEqual({k: v['summe'] for k, v in jb.items()},
                         {'Whg A': D('1200.00'), 'Whg B': D('1644.44'), 'Whg C': D('1644.44'),
                          'Whg D': D('5755.56'), 'Whg E': D('5755.56')})
        self.assertEqual(sum(v['summe'] for v in jb.values()), D('16000.00'))

        # ── 2. Digitale Einberufung ──────────────────────────────────────────────────────────
        v = Versammlung.objects.create(liegenschaft=lg, titel='Ordentliche Versammlung 2026', art='ordentlich',
                                       datum=timezone.now() + timedelta(days=5), ort='Gemeindesaal', evoting=True)
        t = Traktandum.objects.create(versammlung=v, nr=1, titel='Budget-Genehmigung 2026',
                                      antrag='Das Budget 2026 über CHF 16\'000 wird genehmigt.',
                                      mehrheitsart='doppelt_anwesende')
        bd.an_traktandum_haengen(t, b)
        with self.assertRaises(VersammlungsFehler) as ctx:              # Frist (10 Tage) unterschritten
            einladung_versenden(v)
        self.assertIn('Einladungsfrist unterschritten', str(ctx.exception))
        v.datum = timezone.now() + timedelta(days=14)
        v.save()
        with mock.patch('stweg.versammlung.send_via_hoststar', return_value=True) as mail:
            versand = einladung_versenden(v)
        self.assertEqual((len(versand), mail.call_count), (5, 5))
        self.assertEqual({x.status for x in versand}, {'gesendet'})
        # Im Portal sieht jeder die Einladung (PDF), die Verwaltung hat das Versandprotokoll.
        self.assertEqual(self.clients['A'].get(f'/portal/stweg/einladung/{v.pk}/')['Content-Type'], 'application/pdf')

        # ── 3. E-Voting ──────────────────────────────────────────────────────────────────────
        durchfuehren(v)
        for name in self.e:
            self.assertEqual(self.clients[name].post(f'/portal/stweg/teilnehmen/{v.pk}/').status_code, 302)
        # Erste Auszählung: drei kleine Eigentümer Ja (3 von 5 Köpfen!), zwei grosse Nein.
        self.stimmen(v, t, {'A': 'ja', 'B': 'ja', 'C': 'ja', 'D': 'nein', 'E': 'nein'})
        z = auswerten(t)
        self.assertEqual((z['ja_koepfe'], z['nein_koepfe'], z['ja_quoten'], z['nein_quoten']),
                         (3, 2, D('300.00'), D('700.00')))
        # Die Kopfmehrheit allein reichte — das DOPPELTE Mehr verlangt auch die Quoten: abgelehnt.
        self.assertEqual(z['vorschlag'], 'abgelehnt')
        t.mehrheitsart = 'einfach_koepfe'
        self.assertEqual(auswerten(t)['vorschlag'], 'angenommen')
        t.mehrheitsart = 'doppelt_anwesende'
        # Nach der Diskussion wechseln C (auf Nein) und E (auf Ja): Ja = A+B+E (3 Köpfe, 550), Nein = C+D (450).
        self.stimmen(v, t, {'C': 'nein', 'E': 'ja'})
        z = auswerten(t)
        self.assertEqual((z['ja_koepfe'], z['nein_koepfe'], z['ja_quoten'], z['nein_quoten']),
                         (3, 2, D('550.00'), D('450.00')))
        self.assertEqual(z['vorschlag'], 'angenommen')
        # Jede Abgabe und jeder Wechsel steht im Ereignisprotokoll: 5 + 2.
        self.assertEqual(t.stimm_ereignisse.count(), 7)
        self.assertEqual(t.stimm_ereignisse.filter(vorher__gt='').count(), 2)

        # ── Die Verwaltung stellt fest: erst DAS löst die Akonto-Rechnungen aus ───────────────
        self.assertFalse(StwegVorschreibung.objects.exists())
        feststellen(t, 'angenommen', beschlusstext='Das Budget 2026 wird genehmigt.')
        b.refresh_from_db()
        self.assertEqual(b.status, 'genehmigt')
        # Nach der Feststellung sind die Stimmen gesperrt.
        antwort = self.clients['C'].post(f'/portal/stweg/evoting/{v.pk}/',
                                         {f'stimme_{t.pk}_{self.e["C"].pk}': 'ja'}, follow=True)
        self.assertContains(antwort, 'gesperrt')
        self.assertEqual(t.stimmen.get(einheit=self.e['C']).wert, 'nein')

        # ── 4. Akonto-Rechnungen nach Budget und zwei Schlüsseln ─────────────────────────────
        self.assertEqual(StwegVorschreibung.objects.count(), 20)
        je_einheit = {n: StwegVorschreibung.objects.filter(einheit=self.e[n]) for n in self.e}
        for n, erwartet in {'A': '300.00', 'B': '411.11', 'C': '411.11', 'D': '1438.89', 'E': '1438.89'}.items():
            self.assertEqual({x.betrag for x in je_einheit[n]}, {D(erwartet)}, n)
        # Das Erdgeschoss trägt in KEINER Rate etwas vom Lift.
        for x in je_einheit['A']:
            lift_teil = [t_ for t_ in x.aufteilung if t_['schluessel'] == 'Lift']
            self.assertEqual([t_['betrag'] for t_ in lift_teil], ['0.00'])
        self.assertEqual(sum(x.betrag for x in StwegVorschreibung.objects.all()), D('16000.00'))
        # Verwaltung verschickt die Akonto-Rechnungen (PDF mit QR-Zahlteil je Rate, falls IBAN).
        with mock.patch('core.utils.email_service.send_via_hoststar', return_value=True) as mail:
            r = bd.vorschreibungen_versenden(b)
        self.assertEqual((len(r['gesendet']), mail.call_count), (5, 5))
        # Im Portal sieht jeder Eigentümer seine Rechnung und sein Kontokorrent.
        s = self.clients['D'].get('/portal/stweg/')
        self.assertContains(s, 'Akonto 2026, Rate 1/4')
        self.assertContains(s, f'/portal/stweg/akonto/{b.pk}/')

        # ── Protokoll ───────────────────────────────────────────────────────────────────────
        with mock.patch('stweg.versammlung.send_via_hoststar', return_value=True):
            protokoll_versenden(v)
        self.assertEqual(self.clients['B'].get(f'/portal/stweg/protokoll/{v.pk}/')['Content-Type'], 'application/pdf')

        # ── Zahlungen, Kosten, Jahresabrechnung ─────────────────────────────────────────────
        for n in ('A', 'B', 'C', 'D', 'E'):
            for rate in je_einheit[n]:
                StwegAkonto.objects.create(einheit=self.e[n], betrag=rate.betrag, datum=rate.faellig_am)
            self.assertEqual(kontokorrent(self.e[n], heute=date(2026, 12, 31))['saldo_faellig'], D('0.00'), n)
        # Die tatsächlichen Kosten weichen vom Budget ab: Versicherung 11'800, Lift 4'600.
        rechnung(lg, 11800, date(2026, 3, 1), konto=self.k_allg)
        rechnung(lg, 4600, date(2026, 9, 1), konto=self.k_lift)
        a = StwegAbrechnungService(lg).abrechnen(2026)
        StwegAbrechnungService.abschliessen(a)
        pos = {p.einheit.bezeichnung: p for p in a.positionen.select_related('einheit')}
        # Allgemein 11'800 nach 100/100/100/350/350 = 1180/1180/1180/4130/4130.
        # Lift 4'600 nach 0/100/100/350/350: 4600/900 · w = 0 / 511.11 / 511.11 / 1788.89 / 1788.89 (Rappen aufgehen).
        self.assertEqual(pos['Whg A'].kostenanteil, D('1180.00'))
        self.assertEqual(sum(p.kostenanteil for p in pos.values()), D('16400.00'))
        lift_je = {n: pos[f'Whg {n}'].schluesselanteile.get(schluessel_name='Lift').betrag for n in self.e}
        self.assertEqual(lift_je['A'], D('0.00'))
        self.assertEqual(sum(lift_je.values()), D('4600.00'))
        # A zahlte 1200 Akonto, schuldet 1180: Guthaben 20. D schuldet 4130 + 1788.89 = 5918.89, zahlte 5755.56.
        self.assertEqual(pos['Whg A'].saldo, D('-20.00'))
        self.assertEqual(pos['Whg D'].saldo, D('163.33'))
        for n in self.e:
            self.assertEqual(kontokorrent(self.e[n], heute=date(2027, 1, 1))['saldo_total'],
                             pos[f'Whg {n}'].saldo, n)
        # Der Eigentümer lädt seine Jahresabrechnung im Portal.
        self.assertEqual(self.clients['D'].get(f'/portal/stweg/abrechnung/{a.pk}/')['Content-Type'], 'application/pdf')
