"""Automatischer Nachtrag der LIK-Monatswerte vom HEV: speichert nur, was den Abgleich und die Schranken besteht."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from core.models import AbrufStatus, LikWert
from core.services import lik

HEUTE = date(2026, 11, 14)


def seite(werte_2026, werte_2025=None, marke='Dezember 2020 = 100', schnitt=True):
    """Eine Seite in der Form der HEV-Tabelle: Jahr, zwölf Monate, Jahresdurchschnitt; neuestes Jahr zuerst."""
    werte_2025 = werte_2025 if werte_2025 is not None else lik.LIK_DEZ2020[2025]

    def zeile(jahr, werte):
        zellen = ''.join(f'<td>{str(w).replace(".", ",")}</td>' for w in werte)
        zellen += '<td></td>' * (12 - len(werte))
        if schnitt and len(werte) == 12:
            zellen += f'<td>{str(round(sum(werte) / 12, 1)).replace(".", ",")}</td>'
        return f'<tr><td>{jahr}</td>{zellen}</tr>'
    return (f'<h3>Basis {marke}</h3><table>' + zeile(2026, werte_2026) + zeile(2025, werte_2025)
            + '<tr><td>2024</td><td>106,4</td></tr></table>')


BEKANNT = list(lik.LIK_DEZ2020[2026])        # Januar bis September 2026


class NachfuehrenTests(TestCase):
    def setUp(self):
        lik.cache_leeren()
        self.addCleanup(lik.cache_leeren)

    def _lauf(self, html, heute=HEUTE):
        with mock.patch.object(lik, '_hev_html', return_value=html):
            return lik.automatisch_nachfuehren(heute)

    def test_der_naechste_monat_wird_gespeichert_und_gilt_sofort(self):
        self.assertEqual(self._lauf(seite(BEKANNT + [108.7])), [(2026, 10, Decimal('108.7'))])
        w = LikWert.objects.get(jahr=2026, monat=10)
        self.assertIn('HEV, automatischer Abruf vom 14.11.2026', w.quelle)
        self.assertEqual(lik.lik_punkte_fuer(2026, 10), Decimal('108.7'))
        self.assertEqual(AbrufStatus.objects.get(name='lik').fehler_in_folge, 0)

    def test_mehrere_fehlende_monate_werden_lueckenlos_gespeichert(self):
        self.assertEqual(self._lauf(seite(BEKANNT + [108.7, 108.6]), heute=date(2026, 12, 5)),
                         [(2026, 10, Decimal('108.7')), (2026, 11, Decimal('108.6'))])

    def test_ein_zweiter_lauf_speichert_nichts_doppelt(self):
        self._lauf(seite(BEKANNT + [108.7]))
        self.assertEqual(self._lauf(seite(BEKANNT + [108.7])), [])
        self.assertEqual(LikWert.objects.count(), 1)

    def test_nichts_neues_ist_ein_erfolg_ohne_speichern(self):
        self.assertEqual(self._lauf(seite(BEKANNT)), [])
        self.assertEqual(LikWert.objects.count(), 0)
        self.assertEqual(AbrufStatus.objects.get(name='lik').fehler_in_folge, 0)

    def test_stimmen_bekannte_monate_nicht_wird_nichts_gespeichert(self):
        verrutscht = BEKANNT[:-1] + [108.9, 108.7]             # September hier 108.5, Quelle 108.9
        self.assertEqual(self._lauf(seite(verrutscht)), [])
        self.assertEqual(LikWert.objects.count(), 0)
        self.assertIn('Abgleich gescheitert', AbrufStatus.objects.get(name='lik').letzter_fehler)

    def test_ein_zu_grosser_sprung_wird_nicht_gespeichert(self):
        self.assertEqual(self._lauf(seite(BEKANNT + [111.0])), [])
        self.assertEqual(LikWert.objects.count(), 0)
        self.assertIn('weicht', AbrufStatus.objects.get(name='lik').letzter_fehler)

    def test_ein_monat_nach_heute_wird_nie_gespeichert(self):
        self.assertEqual(self._lauf(seite(BEKANNT + [108.7, 108.6]), heute=date(2026, 10, 20)),
                         [(2026, 10, Decimal('108.7'))])

    def test_fehlende_marke_speichert_nichts_und_nennt_den_grund(self):
        self.assertEqual(self._lauf(seite(BEKANNT + [108.7], marke='Dezember 2025 = 100').replace('2020', '2025')), [])
        self.assertEqual(LikWert.objects.count(), 0)
        self.assertIn('2020 = 100', AbrufStatus.objects.get(name='lik').letzter_fehler)

    def test_ein_wert_von_hand_wird_nicht_ueberschrieben(self):
        LikWert.objects.create(jahr=2026, monat=10, punkte=Decimal('108.8'), quelle='BFS, von Hand')
        self.assertEqual(self._lauf(seite(BEKANNT + [108.8, 108.6]), heute=date(2026, 12, 5)),
                         [(2026, 11, Decimal('108.6'))])
        self.assertEqual(LikWert.objects.get(jahr=2026, monat=10).quelle, 'BFS, von Hand')

    def test_verbindungsfehler_speichert_nichts(self):
        with mock.patch.object(lik, '_hev_html', side_effect=lik._AbrufFehler('Verbindung fehlgeschlagen (Timeout)')):
            self.assertEqual(lik.automatisch_nachfuehren(HEUTE), [])
        self.assertIn('Verbindung', AbrufStatus.objects.get(name='lik').letzter_fehler)


class LeserTests(TestCase):
    def test_der_jahresdurchschnitt_wird_nicht_als_monat_gelesen(self):
        werte = lik._monatswerte_aus_html(seite(BEKANNT + [108.7]), HEUTE)
        self.assertEqual(len([w for w in werte if w[0] == 2025]), 12)
        self.assertEqual(werte[-1], (2026, 10, Decimal('108.7')))

    def test_der_live_wert_ist_der_juengste_monat(self):
        with mock.patch.object(lik, '_hev_html', return_value=seite(BEKANNT + [108.7])), \
                mock.patch('datetime.date') as d:
            d.today.return_value = HEUTE
            d.side_effect = date
            self.assertEqual(lik._fetch_live_lik(), (date(2026, 10, 1), Decimal('108.7')))
