"""Mehrere Basisreihen des Landesindex: Die Basis gehört zum Vertrag, gerechnet wird nur in seiner Reihe.

Was hier festgehalten ist (jeder Test mit Gegenprobe im selben Test oder im Nachbartest):
* der Leser liest JE BASIS die richtige Tabelle der HEV-Seite, zellenweise (Spalte = Monat, Ø fällt weg);
* «Reihe einlesen» speichert lückenlos ab dem Basismonat, nie den laufenden Monat, überschreibt nichts;
* der Nachtrag führt jede Reihe in sich nach;
* die Vorgabe eines neuen Vertrags: Liegenschaft → Eigentümer → Organisation → Dezember 2020;
* ein Vertrag der Reihe 2010 liest NIE die Reihe 2020; fehlt der Wert in seiner Reihe, wird das gemeldet;
* die Betreiber-Seite schaltet zwischen den Reihen um, und jede Aktion trifft nur die gewählte.

Die Zahlen der Reihen 2025 und 2010 für 2026 sind aus der HEV-Seite vom 14.11.2026 abgeschrieben; alle anderen
Zeilen der Testseite sind als erfunden gekennzeichnet (`KUNST_…`) und dienen nur der Form.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import AbrufStatus, LikWert, SicherheitsEreignis
from core.services import index_anpassung as ia
from core.services import lik, mietzinsmodell
from crm.models import Eigentuemer
from rentals.models import Mietvertrag, MietzinsAnpassung

from ._helfer import Einheit, Liegenschaft, Mieter, _team_user, _test_organisation

D = Decimal
HEUTE = date(2026, 11, 14)
B2025, B2020, B2010 = 'Dezember 2025', 'Dezember 2020', 'Dezember 2010'

#: HEV-Seite vom 14.11.2026, Januar bis Oktober 2026.
R2025_2026 = [99.9, 100.6, 100.8, 101.1, 101.3, 101.3, 101.1, 101.5, 101.5, 101.7]
R2010_2026 = [104.9, 105.6, 105.8, 106.1, 106.3, 106.3, 106.1, 106.5, 106.5, 106.7]
R2020_2026 = list(lik.LIK_DEZ2020[2026]) + [108.7]
#: ERFUNDEN, nur für die Form der Tabelle (eine kurze «Reihe 2010», die im Dezember 2025 beginnt, gibt es nicht).
KUNST_2010_DEZ_2025 = 105.0


def _tabelle(zeilen, kopf=True):
    """Eine Tabelle in der Form der HEV-Seite: Jahr | Jan. … Dez. | Ø; leere Zellen als `&nbsp;`, davor «---»."""
    html = '<table class="contenttable"><tbody>'
    if kopf:
        html += '<tr><td>\n\t Jahr \n</td>' + ''.join(f'<td>{m}</td>' for m in (
            'Jan.', 'Feb.', 'März', 'April', 'Mai', 'Juni', 'Juli', 'Aug.', 'Sept.', 'Okt.', 'Nov.', 'Dez.', 'Ø')) + '</tr>'
    for jahr, werte, schnitt in zeilen:
        zellen = [('&nbsp;' if w is None else str(w)) for w in werte] + ['&nbsp;'] * (12 - len(werte))
        html += (f'<tr class="tr-odd"><td>\n\t\t{jahr}\n\t</td>' + ''.join(f'<td>\n\t{z}\n</td>' for z in zellen)
                 + f'<td>{schnitt if schnitt is not None else "&nbsp;"}</td></tr>')
    return html + '</tbody></table>'


def seite(r2025=None, r2020=None, r2010=None, ohne=()):
    """Drei Tabellen untereinander wie auf der HEV-Seite: je Basis die Marke im Titel, dann die Tabelle."""
    r2025 = R2025_2026 if r2025 is None else r2025
    r2020 = R2020_2026 if r2020 is None else r2020
    r2010 = R2010_2026 if r2010 is None else r2010
    teile = {
        B2025: _tabelle([(2026, r2025, None), (2025, [None] * 11 + [100.0], None)]),
        B2020: _tabelle([(2026, r2020, None), (2025, lik.LIK_DEZ2020[2025], 107.4)]),
        B2010: _tabelle([(2026, r2010, None), (2025, ['---'] * 11 + [KUNST_2010_DEZ_2025], None)]),
    }
    return '<p>Der Index wird in mehreren Reihen geführt.</p>' + ''.join(
        f'<h2 class="">\n\t {basis} = 100 Punkte \n</h2>{tabelle}' for basis, tabelle in teile.items() if basis not in ohne)


def _reihe_anlegen(basis, werte_2026, dez_2025=100.0):
    """Eine Reihe in `LikWert`: Dezember 2025 und die Monate 2026 (Quelle: Test)."""
    LikWert.objects.create(jahr=2025, monat=12, basis=basis, punkte=D(str(dez_2025)), quelle='Test')
    for monat, wert in enumerate(werte_2026, start=1):
        LikWert.objects.create(jahr=2026, monat=monat, basis=basis, punkte=D(str(wert)), quelle='Test')
    lik.cache_leeren()


class _Basis(TestCase):
    def setUp(self):
        lik.cache_leeren()
        self.addCleanup(lik.cache_leeren)


# ── Leser ────────────────────────────────────────────────────────────────────
class LeserJeBasisTests(_Basis):
    def test_jede_basis_liest_ihre_eigene_tabelle(self):
        html = seite()
        self.assertEqual(lik._monatswerte_aus_html(html, HEUTE, basis=B2025)[-1], (2026, 10, D('101.7')))
        self.assertEqual(lik._monatswerte_aus_html(html, HEUTE, basis=B2010)[-1], (2026, 10, D('106.7')))
        self.assertEqual(lik._monatswerte_aus_html(html, HEUTE, basis=B2020)[-1], (2026, 10, D('108.7')))
        # Gegenprobe: ohne Angabe ist es die Standardreihe, nicht die erste Tabelle der Seite (2025)
        self.assertEqual(lik._monatswerte_aus_html(html, HEUTE)[-1], (2026, 10, D('108.7')))

    def test_werte_unter_100_werden_gelesen(self):
        """Die Reihe 2025 beginnt 2026 mit 99.9: Der frühere Ausdruck `1\\d{2}[.,]\\d` las diesen Monat nicht."""
        werte = lik._tabelle_aus_html(seite(), B2025)
        self.assertEqual(werte[(2026, 1)], D('99.9'))
        self.assertEqual([werte[(2026, m)] for m in range(1, 11)], [D(str(w)) for w in R2025_2026])

    def test_die_spalte_bestimmt_den_monat_auch_nach_leeren_zellen(self):
        werte = lik._tabelle_aus_html(seite(), B2025)
        self.assertEqual(werte[(2025, 12)], D('100.0'))                 # elf leere Zellen davor
        self.assertNotIn((2025, 1), werte)                               # Gegenprobe: nicht nach vorn gerutscht
        self.assertNotIn((2026, 11), werte)
        w2010 = lik._tabelle_aus_html(seite(), B2010)
        self.assertEqual(w2010[(2025, 12)], D(str(KUNST_2010_DEZ_2025)))  # «---» ist kein Wert und verschiebt nichts
        self.assertNotIn((2025, 11), w2010)

    def test_der_durchschnitt_ist_kein_monat(self):
        werte = lik._tabelle_aus_html(seite(), B2020)
        self.assertEqual(len([k for k in werte if k[0] == 2025]), 12)
        self.assertEqual(werte[(2025, 12)], D('106.9'))                   # nicht der Ø 107.4 dahinter

    def test_fehlt_die_tabelle_einer_basis_wird_nicht_die_naechste_genommen(self):
        """Steht die Marke 2020 nur im Text und folgt die Tabelle einer ANDEREN Basis, wird nichts gelesen."""
        html = ('<p>Früher galt Dezember 2020 = 100 Punkte.</p>'
                f'<h2>Dezember 2010 = 100 Punkte</h2>{_tabelle([(2026, R2010_2026, None)])}')
        with self.assertRaises(lik._AbrufFehler) as fehler:
            lik._tabelle_aus_html(html, B2020)
        self.assertIn('Dezember 2020 = 100', str(fehler.exception))
        # Gegenprobe: Die Reihe 2010 derselben Seite wird gelesen
        self.assertEqual(lik._tabelle_aus_html(html, B2010)[(2026, 10)], D('106.7'))

    def test_fehlt_die_marke_wird_die_basis_genannt(self):
        with self.assertRaises(lik._AbrufFehler) as fehler:
            lik._tabelle_aus_html(seite(ohne=(B2010,)), B2010)
        self.assertIn('Dezember 2010 = 100', str(fehler.exception))
        self.assertTrue(lik._tabelle_aus_html(seite(ohne=(B2010,)), B2020))      # Gegenprobe

    def test_eine_zelle_ohne_indexzahl_bricht_ab_statt_zu_verrutschen(self):
        kaputt = seite(r2010=R2010_2026[:3] + ['n.v.'] + R2010_2026[4:])
        with self.assertRaises(lik._AbrufFehler):
            lik._tabelle_aus_html(kaputt, B2010)
        self.assertTrue(lik._tabelle_aus_html(kaputt, B2025))                    # Gegenprobe: andere Tabelle heil

    def test_der_basismonat_muss_bei_100_stehen(self):
        """Die Probe, dass es die Tabelle DIESER Basis ist."""
        falsch = (f'<h2>Dezember 2025 = 100 Punkte</h2>'
                  f'{_tabelle([(2026, R2010_2026, None), (2025, [None] * 11 + [105.0], None)])}')
        with self.assertRaises(lik._AbrufFehler) as fehler:
            lik._tabelle_aus_html(falsch, B2025)
        self.assertIn('Basismonat', str(fehler.exception))
        self.assertEqual(lik._tabelle_aus_html(seite(), B2025)[(2025, 12)], D('100.0'))   # Gegenprobe


# ── Reihen und Cache ─────────────────────────────────────────────────────────
class ReihenTests(_Basis):
    def test_eine_andere_basis_hat_nur_ihre_eigenen_werte(self):
        self.assertEqual(lik.lik_reihen(basis=B2010), {})                 # nichts aus dem Code, nichts aus 2020
        self.assertIsNone(lik.lik_punkte_fuer(2026, 9, basis=B2010))
        self.assertEqual(lik.lik_punkte_fuer(2026, 9), D('108.5'))        # Gegenprobe: die Standardreihe hat ihn
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        self.assertEqual(lik.lik_punkte_fuer(2026, 9, basis=B2010), D('106.5'))
        self.assertEqual(lik.lik_punkte_fuer(2026, 9), D('108.5'))        # und bleibt unberührt
        self.assertIsNone(lik.lik_punkte_fuer(2026, 10))

    def test_der_cache_gilt_je_basis(self):
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        lik.lik_reihen(basis=B2010)
        lik.lik_reihen()
        with self.assertNumQueries(0):
            self.assertEqual(lik.lik_punkte_fuer(2026, 10, basis=B2010), D('106.7'))
            self.assertIsNone(lik.lik_punkte_fuer(2026, 10))              # Gegenprobe: nicht die gemerkte Reihe 2010

    def test_die_lueckenlogik_gilt_je_reihe(self):
        _reihe_anlegen(B2010, R2010_2026[:8], dez_2025=KUNST_2010_DEZ_2025)       # bis August
        LikWert.objects.create(jahr=2026, monat=10, basis=B2010, punkte=D('106.7'), quelle='Test')   # September fehlt
        lik.cache_leeren()
        self.assertEqual(lik.letzter_tabellenmonat(basis=B2010), (2026, 8))
        self.assertIsNone(lik.lik_punkte_fuer(2026, 10, basis=B2010))
        self.assertEqual(lik.lik_reihen(roh=True, basis=B2010)[2026][9], 106.7)   # Gegenprobe: roh steht er da
        self.assertEqual(lik.letzter_tabellenmonat(), (2026, 9))                  # die Standardreihe bleibt

    def test_der_aktuelle_wert_einer_leeren_reihe_ist_kein_wert(self):
        self.assertEqual(lik.aktueller_lik_wert(live=False, basis=B2010), (None, None, B2010))
        self.assertIsNone(lik.aktuell_in_reihe(B2010, D('108.5')))        # der Wert der Standardreihe wird nicht untergeschoben
        self.assertEqual(lik.aktuell_in_reihe(B2020, D('108.5')), D('108.5'))    # Gegenprobe
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        self.assertEqual(lik.aktueller_lik_wert(live=False, basis=B2010), (date(2026, 10, 1), D('106.7'), B2010))

    def test_gefuehrt_wird_was_werte_hat(self):
        self.assertEqual(lik.gefuehrte_basen(), [B2020])
        _reihe_anlegen(B2025, R2025_2026)
        self.assertEqual(lik.gefuehrte_basen(), [B2025, B2020])


# ── Reihe einlesen ───────────────────────────────────────────────────────────
class EinlesenTests(_Basis):
    def _einlesen(self, basis, html=None, heute=HEUTE):
        with mock.patch.object(lik, '_hev_html', return_value=html or seite()):
            return lik.reihe_einlesen(basis, heute)

    def test_die_ganze_reihe_wird_lueckenlos_gespeichert(self):
        erg = self._einlesen(B2025)
        self.assertEqual(erg['fehler'], '')
        self.assertEqual([(j, m) for j, m, _w in erg['gespeichert']], [(2025, 12)] + [(2026, m) for m in range(1, 11)])
        self.assertEqual(lik.lik_punkte_fuer(2026, 1, basis=B2025), D('99.9'))
        self.assertEqual(lik.letzter_tabellenmonat(basis=B2025), (2026, 10))
        self.assertTrue(all(w.quelle.startswith('HEV') for w in LikWert.objects.filter(basis=B2025)))
        # Gegenprobe: in keiner anderen Reihe ist etwas entstanden
        self.assertEqual(LikWert.objects.exclude(basis=B2025).count(), 0)
        self.assertIsNone(lik.lik_punkte_fuer(2026, 10))

    def test_der_laufende_monat_wird_nie_gespeichert(self):
        """Am 20.10.2026 ist der Oktober der laufende Monat — auch wenn er (fälschlich) in der Quelle steht."""
        erg = self._einlesen(B2025, heute=date(2026, 10, 20))
        self.assertEqual(erg['gespeichert'][-1][:2], (2026, 9))
        self.assertFalse(LikWert.objects.filter(basis=B2025, jahr=2026, monat=10).exists())
        # Gegenprobe: einen Monat später ist er veröffentlicht und wird nachgeholt
        self.assertEqual(self._einlesen(B2025)['gespeichert'], [(2026, 10, D('101.7'))])

    def test_vorhandene_werte_werden_nicht_ueberschrieben_abweichungen_gemeldet(self):
        LikWert.objects.create(jahr=2026, monat=3, basis=B2025, punkte=D('100.9'), quelle='von Hand')   # HEV: 100.8
        LikWert.objects.create(jahr=2026, monat=4, basis=B2025, punkte=D('101.1'), quelle='von Hand')   # stimmt
        lik.cache_leeren()
        erg = self._einlesen(B2025)
        self.assertEqual(erg['abweichungen'], [(2026, 3, D('100.9'), D('100.8'))])
        self.assertEqual(LikWert.objects.get(basis=B2025, jahr=2026, monat=3).punkte, D('100.9'))
        self.assertEqual(LikWert.objects.get(basis=B2025, jahr=2026, monat=3).quelle, 'von Hand')
        self.assertEqual(len(erg['gespeichert']), 9)                       # elf Monate, zwei standen schon
        self.assertEqual(LikWert.objects.filter(basis=B2025).count(), 11)

    def test_eine_luecke_in_der_quelle_speichert_nichts(self):
        luecke = seite(r2025=R2025_2026[:4] + [None] + R2025_2026[5:])
        erg = self._einlesen(B2025, html=luecke)
        self.assertIn('05/2026', erg['fehler'])
        self.assertEqual(LikWert.objects.count(), 0)
        self.assertIn('05/2026', AbrufStatus.objects.get(name='lik').letzter_fehler)

    def test_ein_sprung_in_der_quelle_speichert_nichts(self):
        sprung = seite(r2025=R2025_2026[:4] + [111.3] + R2025_2026[5:])
        erg = self._einlesen(B2025, html=sprung)
        self.assertIn('weicht', erg['fehler'])
        self.assertEqual(LikWert.objects.count(), 0)

    def test_ohne_basismonat_bei_100_wird_nichts_gespeichert(self):
        """Die Kunst-Tabelle «2010» beginnt im Dezember 2025 statt im Dezember 2010: kein Basismonat, kein Einlesen."""
        erg = self._einlesen(B2010)
        self.assertIn('Basismonat 12/2010', erg['fehler'])
        self.assertEqual(LikWert.objects.count(), 0)
        self.assertEqual(self._einlesen(B2025)['fehler'], '')              # Gegenprobe: 2025 hat ihn

    def test_eine_unbekannte_basis_wird_abgewiesen(self):
        with mock.patch.object(lik, '_hev_html') as abruf:
            erg = lik.reihe_einlesen('Mai 2000', HEUTE)
        self.assertIn('keine geführte', erg['fehler'])
        abruf.assert_not_called()


# ── Nachführen je Reihe ──────────────────────────────────────────────────────
class NachfuehrenJeReiheTests(_Basis):
    def _lauf(self, basis, html=None, heute=HEUTE):
        with mock.patch.object(lik, '_hev_html', return_value=html or seite()):
            return lik.automatisch_nachfuehren(heute, basis=basis)

    def test_der_naechste_monat_der_gewaehlten_reihe_wird_gespeichert(self):
        _reihe_anlegen(B2025, R2025_2026[:9])                              # bis September
        self.assertEqual(self._lauf(B2025), [(2026, 10, D('101.7'))])
        self.assertEqual(LikWert.objects.get(basis=B2025, jahr=2026, monat=10).punkte, D('101.7'))
        # Gegenprobe: Die Standardreihe wurde von diesem Lauf nicht angefasst
        self.assertFalse(LikWert.objects.filter(basis=B2020).exists())
        self.assertIsNone(lik.lik_punkte_fuer(2026, 10))

    def test_der_abgleich_sperrt_die_falsche_reihe(self):
        """Eigene Reihe 2025, aber unter der Marke 2025 stehen die Werte der Reihe 2010: nichts wird gespeichert."""
        _reihe_anlegen(B2025, R2025_2026[:9])
        self.assertEqual(self._lauf(B2025, html=seite(r2025=R2010_2026)), [])
        self.assertFalse(LikWert.objects.filter(basis=B2025, jahr=2026, monat=10).exists())
        fehler = AbrufStatus.objects.get(name='lik').letzter_fehler
        self.assertIn('Abgleich gescheitert', fehler)
        self.assertIn('Dezember 2025', fehler)

    def test_eine_leere_reihe_wird_nicht_ueber_den_nachtrag_begonnen(self):
        self.assertEqual(self._lauf(B2010), [])
        self.assertEqual(LikWert.objects.count(), 0)
        self.assertIn('Keine eigene Reihe', AbrufStatus.objects.get(name='lik').letzter_fehler)

    def test_eine_junge_reihe_gleicht_bis_zum_basismonat_ab(self):
        """Dezember 2025 und Januar 2026: weniger als drei Monate, aber beide stimmen."""
        _reihe_anlegen(B2025, R2025_2026[:1])
        self.assertEqual(self._lauf(B2025, heute=date(2026, 3, 10)),
                         [(2026, 2, D('100.6')), (2026, 3, D('100.8'))])

    def test_der_tageslauf_fuehrt_alle_reihen_mit_werten_nach(self):
        _reihe_anlegen(B2025, R2025_2026[:9])
        with mock.patch.object(lik, '_hev_html', return_value=seite()) as abruf:
            ergebnis = lik.alle_reihen_nachfuehren(HEUTE)
        self.assertEqual(ergebnis, {B2025: [(2026, 10, D('101.7'))], B2020: [(2026, 10, D('108.7'))]})
        abruf.assert_called_once()                                          # die Seite wird einmal geholt
        self.assertNotIn(B2010, ergebnis)                                   # Gegenprobe: ohne Werte kein Nachtrag
        self.assertFalse(LikWert.objects.filter(basis=B2010).exists())
        self.assertEqual(AbrufStatus.objects.get(name='lik').fehler_in_folge, 0)

    def test_der_fehler_einer_reihe_wird_nicht_vom_erfolg_einer_anderen_ueberdeckt(self):
        _reihe_anlegen(B2025, R2025_2026[:9])
        with mock.patch.object(lik, '_hev_html', return_value=seite(r2025=R2010_2026)):
            ergebnis = lik.alle_reihen_nachfuehren(HEUTE)
        self.assertEqual(ergebnis, {B2020: [(2026, 10, D('108.7'))]})      # 2020 läuft trotzdem
        status = AbrufStatus.objects.get(name='lik')
        self.assertEqual(status.fehler_in_folge, 1)
        self.assertIn('Dezember 2025', status.letzter_fehler)


# ── Vorgabe-Kette ────────────────────────────────────────────────────────────
class VorgabeKetteTests(_Basis):
    def setUp(self):
        super().setUp()
        self.org = _test_organisation(lik_basis=B2020)
        self.eig = Eigentuemer.objects.create(firma_oder_name='Mandat Muster AG')
        self.lg = Liegenschaft.objects.create(organisation=self.org, strasse='Kettenweg 1', plz='8000', ort='Zürich',
                                              kanton='AG', versicherungswert=D('1000000'), eigentuemer=self.eig)
        self.e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='Whg', typ='whg',
                                        nettomiete_aktuell=D('2000'))
        self.m = Mieter.objects.create(typ='person', vorname='Vera', nachname='Vorgabe')

    def _setze(self, liegenschaft='', eigentuemer='', organisation=B2020):
        self.lg.lik_basis, self.eig.lik_basis, self.org.lik_basis = liegenschaft, eigentuemer, organisation
        self.lg.save(update_fields=['lik_basis'])
        self.eig.save(update_fields=['lik_basis'])
        self.org.save(update_fields=['lik_basis'])
        return Liegenschaft.objects.select_related('eigentuemer').get(pk=self.lg.pk)

    def test_ohne_festlegung_gilt_dezember_2020(self):
        self.assertEqual(lik.basis_vorgabe(self._setze()), B2020)
        self.assertEqual(lik.basis_vorgabe(None), B2020)

    def test_die_organisation_gilt_wenn_sonst_nichts_festgelegt_ist(self):
        self.assertEqual(lik.basis_vorgabe(self._setze(organisation='Dezember 2015')), 'Dezember 2015')
        self.assertEqual(lik.basis_vorgabe(self._setze(organisation=B2020)), B2020)       # Gegenprobe

    def test_der_eigentuemer_geht_der_organisation_vor(self):
        self.assertEqual(lik.basis_vorgabe(self._setze(eigentuemer=B2010, organisation='Dezember 2015')), B2010)
        self.assertEqual(lik.basis_vorgabe(self._setze(eigentuemer='', organisation='Dezember 2015')),
                         'Dezember 2015')                                                  # Gegenprobe

    def test_die_liegenschaft_geht_dem_eigentuemer_vor(self):
        self.assertEqual(lik.basis_vorgabe(self._setze(liegenschaft=B2025, eigentuemer=B2010)), B2025)
        self.assertEqual(lik.basis_vorgabe(self._setze(liegenschaft='', eigentuemer=B2010)), B2010)   # Gegenprobe

    def test_die_kette_laeuft_auch_von_einheit_und_vertrag_aus(self):
        self._setze(eigentuemer=B2010)
        einheit = Einheit.objects.get(pk=self.e.pk)
        self.assertEqual(lik.basis_vorgabe(einheit), B2010)
        v = Mietvertrag.objects.create(mieter=self.m, einheit=einheit, beginn=date(2024, 1, 1),
                                       netto_mietzins=D('2000'), nebenkosten=D('0'), status='entwurf')
        self.assertEqual(lik.basis_vorgabe(v), B2010)

    def test_freitext_aus_dem_altbestand_gilt_als_nicht_festgelegt(self):
        self.assertEqual(lik.basis_vorgabe(self._setze(eigentuemer=B2010, organisation='Dez. 2020')), B2010)
        self.assertEqual(lik.basis_vorgabe(self._setze(organisation='Dez. 2020')), B2020)

    def test_ein_spaeter_gesetzter_standard_aendert_keinen_bestehenden_vertrag(self):
        v = Mietvertrag.objects.create(mieter=self.m, einheit=self.e, beginn=date(2024, 1, 1),
                                       netto_mietzins=D('2000'), nebenkosten=D('0'), status='aktiv')
        self.assertEqual(v.lik_basis, B2020)                               # Bestand und Modellvorgabe
        self._setze(liegenschaft=B2025, eigentuemer=B2010)
        v.refresh_from_db()
        self.assertEqual(v.lik_basis, B2020)
        self.assertEqual(lik.basis_von(v), B2020)
        self.assertEqual(lik.basis_vorgabe(v), B2025)                      # Gegenprobe: die VORGABE hat gewechselt

    def test_der_assistent_speichert_die_vorgabe_des_mandats(self):
        """Fester Mietzins, Eigentümer rechnet mit 2010: Basis UND Punkte stammen aus der Reihe 2010."""
        self._setze(eigentuemer=B2010)
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        c = Client()
        c.force_login(_team_user(rolle='Verwaltung'))
        daten = {'einheit_id': str(self.e.id), 'mieter_id': str(self.m.id), 'netto_mietzins': '2000',
                 'nebenkosten': '200', 'beginn': '2026-11-01', 'nk_kostenarten': ['heizung']}
        r = c.post('/neu/vertraege/neu/speichern/', daten)
        self.assertEqual(r.status_code, 302, r.content.decode()[:300])
        v = Mietvertrag.objects.get(einheit=self.e)
        self.assertEqual((v.lik_basis, v.basis_lik_punkte, v.basis_lik_stand), (B2010, D('106.7'), date(2026, 10, 1)))
        self.assertNotEqual(v.basis_lik_punkte, lik.lik_punkte_fuer(2026, 9))       # nicht der Wert der Reihe 2020

    def test_der_assistent_setzt_keinen_wert_der_reihe_2020_ein_wenn_die_reihe_leer_ist(self):
        """Gegenprobe zum Test darüber: dieselbe Eingabe, aber die Reihe 2010 hat keine Werte."""
        self._setze(eigentuemer=B2010)
        c = Client()
        c.force_login(_team_user(rolle='Verwaltung'))
        daten = {'einheit_id': str(self.e.id), 'mieter_id': str(self.m.id), 'netto_mietzins': '2000',
                 'nebenkosten': '200', 'beginn': '2026-11-01', 'nk_kostenarten': ['heizung']}
        r = c.post('/neu/vertraege/neu/speichern/', daten)
        self.assertEqual(r.status_code, 400)
        self.assertIn('Dezember 2010 = 100', r.context['feld_fehler']['lik_basis'])
        self.assertIn('10/2026', r.context['feld_fehler']['lik_basis'])
        self.assertFalse(Mietvertrag.objects.filter(einheit=self.e).exists())

    def test_die_gewaehlte_basis_des_assistenten_geht_der_vorgabe_vor(self):
        self._setze(eigentuemer=B2010)
        c = Client()
        c.force_login(_team_user(rolle='Verwaltung'))
        daten = {'einheit_id': str(self.e.id), 'mieter_id': str(self.m.id), 'netto_mietzins': '2000',
                 'nebenkosten': '200', 'beginn': '2026-11-01', 'nk_kostenarten': ['heizung'], 'lik_basis': B2020}
        self.assertEqual(c.post('/neu/vertraege/neu/speichern/', daten).status_code, 302)
        self.assertEqual(Mietvertrag.objects.get(einheit=self.e).lik_basis, B2020)
        daten['lik_basis'] = 'Mai 2000'                                    # Gegenprobe: nur geführte Reihen
        Mietvertrag.objects.filter(einheit=self.e).delete()
        r = c.post('/neu/vertraege/neu/speichern/', daten)
        self.assertEqual(r.status_code, 400)
        self.assertIn('lik_basis', r.context['feld_fehler'])

    def test_der_assistent_zeigt_auswahl_und_vorgabe_der_liegenschaft(self):
        self._setze(liegenschaft=B2025)
        c = Client()
        c.force_login(_team_user(rolle='Verwaltung'))
        r = c.get('/neu/vertraege/neu/')
        self.assertContains(r, 'name="lik_basis"')
        lg = next(l for l in r.context['liegenschaften'] if l['id'] == self.lg.id)
        self.assertEqual(lg['lik_basis'], B2025)
        self.assertEqual(r.context['mzm_config']['lik_je_basis'][B2025], '')       # die Reihe hat keinen Wert
        self.assertNotEqual(r.context['mzm_config']['lik_je_basis'][B2020], '')    # Gegenprobe


# ── Eingabewege der Standards ────────────────────────────────────────────────
class EingabewegeTests(_Basis):
    def setUp(self):
        super().setUp()
        self.org = _test_organisation(lik_basis=B2020)
        self.c = Client()
        self.c.force_login(_team_user(rolle='Verwaltung'))

    def test_das_mandatsformular_setzt_und_leert_den_standard(self):
        eig = Eigentuemer.objects.create(firma_oder_name='Mandat Muster AG')
        url = reverse('fw_eigentuemer_bearbeiten', args=[eig.pk])
        self.assertContains(self.c.get(url), 'name="lik_basis"')
        self.c.post(url, {'firma_oder_name': 'Mandat Muster AG', 'lik_basis': B2010})
        eig.refresh_from_db()
        self.assertEqual(eig.lik_basis, B2010)
        self.c.post(url, {'firma_oder_name': 'Mandat Muster AG', 'lik_basis': 'Mai 2000'})     # unbekannt: abgelehnt
        eig.refresh_from_db()
        self.assertEqual(eig.lik_basis, B2010)
        self.c.post(url, {'firma_oder_name': 'Mandat Muster AG'})                              # Feld fehlt: bleibt
        eig.refresh_from_db()
        self.assertEqual(eig.lik_basis, B2010)
        self.c.post(url, {'firma_oder_name': 'Mandat Muster AG', 'lik_basis': ''})             # leer: Vorgabe der Verwaltung
        eig.refresh_from_db()
        self.assertEqual(eig.lik_basis, '')

    def test_das_liegenschaftsformular_setzt_den_standard(self):
        lg = Liegenschaft.objects.create(organisation=self.org, strasse='Formweg 1', plz='8000', ort='Zürich',
                                         kanton='AG', versicherungswert=D('1000000'))
        url = reverse('fw_liegenschaft_bearbeiten', args=[lg.pk])
        self.assertContains(self.c.get(url), 'name="lik_basis"')
        daten = {'strasse': 'Formweg 1', 'plz': '8000', 'ort': 'Zürich', 'kanton': 'AG', 'typ': lg.typ,
                 'status': lg.status, 'lik_basis': B2025}
        r = self.c.post(url, daten)
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        lg.refresh_from_db()
        self.assertEqual(lg.lik_basis, B2025)
        r = self.c.post(url, {**daten, 'lik_basis': 'Mai 2000'})           # Gegenprobe: nur geführte Reihen
        self.assertEqual(r.status_code, 400)
        lg.refresh_from_db()
        self.assertEqual(lg.lik_basis, B2025)

    def test_die_einstellungen_nehmen_nur_eine_gefuehrte_reihe(self):
        r = self.c.get(reverse('fw_account'))
        self.assertContains(r, 'name="lik_basis"')
        self.assertContains(r, '<option value="Dezember 2010"')


# ── Indexprüfung und Mietzins in der Reihe des Vertrags ──────────────────────
class VertragInSeinerReiheTests(_Basis):
    def setUp(self):
        super().setUp()
        self.org = _test_organisation(lik_basis=B2020, aktueller_lik_punkte=D('108.5'))
        self.lg = Liegenschaft.objects.create(organisation=self.org, strasse='Reihenweg 1', plz='8000', ort='Zürich',
                                              kanton='AG', versicherungswert=D('1000000'))
        self.e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='Laden', typ='gew',
                                        nettomiete_aktuell=D('2000'))
        self.m = Mieter.objects.create(typ='person', vorname='Ida', nachname='Index')

    def _vertrag(self, basis=B2010, punkte='105.0', modell='index', **felder):
        return Mietvertrag.objects.create(
            mieter=self.m, einheit=self.e, beginn=date(2025, 1, 1), ende=date(2030, 12, 31), ist_befristet=True,
            netto_mietzins=D('2000'), nebenkosten=D('0'), status='aktiv', mietzins_modell=modell, lik_basis=basis,
            basis_lik_punkte=D(punkte), basis_lik_stand=date(2025, 12, 1), **felder)

    def _heute(self):
        return mock.patch('django.utils.timezone.localdate', return_value=HEUTE)

    def test_die_indexlage_liest_die_reihe_des_vertrags_nicht_die_reihe_2020(self):
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        v = self._vertrag()
        lage = ia.lage(v, heute=HEUTE, stand=date(2026, 9, 1))
        self.assertEqual(lage['lik_basis'], B2010)
        self.assertEqual(lage['neu_lik'], D('106.5'))                      # Reihe 2010, September 2026
        self.assertNotEqual(lage['neu_lik'], lik.lik_punkte_fuer(2026, 9))  # 108.5 stünde in der Reihe 2020
        self.assertEqual(lage['rechnung'].neu_lik, D('106.5'))
        self.assertEqual(lage['staende'][0], date(2026, 10, 1))            # Oktober gibt es nur in der Reihe 2010
        # Gegenprobe: derselbe Vertrag in der Standardreihe liest 108.5
        v.lik_basis = B2020
        self.assertEqual(ia.lage(v, heute=HEUTE, stand=date(2026, 9, 1))['neu_lik'], D('108.5'))

    def test_fehlt_der_wert_in_der_reihe_des_vertrags_wird_er_gemeldet_nicht_ersetzt(self):
        """Die Reihe 2010 ist leer, die Reihe 2020 hätte den September: keine Rechnung, eine Meldung mit Reihe und Monat."""
        v = self._vertrag()
        lage = ia.lage(v, heute=HEUTE, stand=date(2026, 9, 1))
        self.assertIsNone(lage['neu_lik'])
        self.assertIsNone(lage['rechnung'])
        self.assertIn('Dezember 2010 = 100', lage['stand_fehler'])
        self.assertIn('09/2026', lage['stand_fehler'])
        meldungen = ia.pruefe(v, heute=HEUTE, stand=date(2026, 9, 1), wirksam_ab=date(2027, 2, 1), neu_netto=D('2010'))
        self.assertTrue(any('Dezember 2010 = 100' in m for m in meldungen))
        # Gegenprobe: mit dem Wert in der Reihe verschwindet die Meldung
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        self.assertEqual(ia.lage(v, heute=HEUTE, stand=date(2026, 9, 1))['stand_fehler'], '')

    def test_der_indexvorschlag_rechnet_in_der_reihe_des_vertrags(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        v = self._vertrag()
        self.assertIsNone(index_anpassung_vorschlag(v, wirksam_ab=date(2027, 2, 1), stand=date(2026, 9, 1)))
        self.assertIsNone(index_anpassung_vorschlag(v, wirksam_ab=date(2027, 2, 1)))     # auch ohne Stand: kein 2020er Wert
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        vorschlag = index_anpassung_vorschlag(v, wirksam_ab=date(2027, 2, 1), stand=date(2026, 9, 1))
        self.assertEqual(vorschlag['aktuell_lik'], D('106.5'))
        self.assertEqual(vorschlag['basis_lik'], D('105.0'))

    def test_das_mietzinspotenzial_vergleicht_nicht_ueber_reihen_hinweg(self):
        """Basis 105.0 in der Reihe 2010; die Verwaltung führt 108.5 (Reihe 2020). 108.5 > 105.0 + 1.5 wäre «Erhöhung»."""
        self.org.aktueller_referenzzinssatz = D('1.25')
        self.org.save(update_fields=['aktueller_referenzzinssatz'])
        v = self._vertrag(modell='fest', basis_referenzzinssatz=D('1.25'))
        self.assertEqual(v.mietzinspotenzial, 'neutral')                   # leere Reihe: kein LIK-Befund
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)    # aktuell 106.7: +1.7 Punkte
        self.assertEqual(Mietvertrag.objects.get(pk=v.pk).mietzinspotenzial, 'increase')
        # Gegenprobe: In der Standardreihe (aktuell 108.5 der Verwaltung) ist derselbe Vertrag sofort «Erhöhung»
        Mietvertrag.objects.filter(pk=v.pk).update(lik_basis=B2020)
        LikWert.objects.all().delete()
        lik.cache_leeren()
        self.assertEqual(Mietvertrag.objects.get(pk=v.pk).mietzinspotenzial, 'increase')
        Mietvertrag.objects.filter(pk=v.pk).update(lik_basis=B2010)
        self.assertEqual(Mietvertrag.objects.get(pk=v.pk).mietzinspotenzial, 'neutral')

    def test_dokumente_und_klausel_weisen_die_basis_des_vertrags_aus(self):
        v = self._vertrag()
        self.assertEqual(lik.vertrag_lik_context(v, self.org)['lik_basis'], B2010)
        self.assertIn('Basis Dezember 2010', lik.vertrag_lik_context(v, self.org)['lik_voll'])
        self.assertEqual(mietzinsmodell.klausel_kontext(v)['lik_basis'], B2010)
        v.lik_basis = B2020                                                # Gegenprobe
        self.assertEqual(lik.vertrag_lik_context(v, self.org)['lik_basis'], B2020)
        self.assertEqual(mietzinsmodell.klausel_kontext(v)['lik_basis'], B2020)

    def test_die_begruendung_nennt_die_reihe_des_vertrags(self):
        rechnung = ia.rechne(D('2000'), D('105.0'), D('106.5'), D('100'))
        self.assertIn('Basis Dezember 2010 = 100', ia.begruendung(rechnung, date(2026, 9, 1), D('2028.55'), basis=B2010))
        self.assertIn('Basis Dezember 2020 = 100', ia.begruendung(rechnung, date(2026, 9, 1), D('2028.55')))

    def test_der_vorschlag_der_basis_kommt_nur_aus_der_gewaehlten_reihe(self):
        self.assertEqual(mietzinsmodell.basis_lik_vorschlag(date(2026, 11, 1), live=False, basis=B2010), (None, None))
        self.assertEqual(mietzinsmodell.basis_lik_vorschlag(date(2026, 10, 1), live=False),
                         (date(2026, 9, 1), D('108.5')))                   # Gegenprobe: die Standardreihe hat einen
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        self.assertEqual(mietzinsmodell.basis_lik_vorschlag(date(2026, 11, 1), live=False, basis=B2010),
                         (date(2026, 10, 1), D('106.7')))

    def test_die_live_pruefung_nennt_reihe_und_fehlenden_monat(self):
        c = Client()
        c.force_login(_team_user(rolle='Verwaltung'))
        q = {'modell': 'index', 'beginn': '2026-11-01', 'lik_basis': B2010}
        j = c.get(reverse('fw_mietzinsmodell_pruefen'), q).json()
        self.assertEqual(j['abgeleitet']['basis_lik'], {'punkte': None, 'stand': None})
        self.assertIn('Dezember 2010 = 100', j['abgeleitet']['basis_lik_fehlt'])
        self.assertIn('10/2026', j['abgeleitet']['basis_lik_fehlt'])
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        j = c.get(reverse('fw_mietzinsmodell_pruefen'), q).json()
        self.assertEqual(j['abgeleitet']['basis_lik'], {'punkte': '106.7', 'stand': '2026-10'})
        self.assertEqual(j['abgeleitet']['basis_lik_fehlt'], '')

    def test_die_anpassungsseite_meldet_die_fehlende_reihe(self):
        v = self._vertrag(modell='fest', basis_referenzzinssatz=D('1.25'))
        c = Client()
        c.force_login(_team_user(rolle='Verwaltung'))
        with self._heute():
            r = c.get(reverse('fw_mietzins_anpassung', args=[v.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['lik_fehlt'])
        self.assertEqual(r.context['lik_basis'], B2010)
        self.assertTrue(any('Dezember 2010 = 100' in str(m) for m in r.context['messages']))
        self.assertEqual(r.context['neu_lik'], D('105.0'))                 # der bisherige Stand, nicht 108.5 der Reihe 2020
        self.assertContains(r, '<option value="Dezember 2010" selected>')
        # Gegenprobe: mit Werten in der Reihe steht ihr aktueller Stand da, ohne Meldung
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        with self._heute():
            r = c.get(reverse('fw_mietzins_anpassung', args=[v.pk]))
        self.assertFalse(r.context['lik_fehlt'])
        self.assertEqual(r.context['neu_lik'], D('106.7'))

    def test_die_basisreihe_wird_nur_mit_passenden_punkten_gewechselt(self):
        """Wechsel 2020 → 2010 auf der Anpassungsseite: Die Punkte müssen in der NEUEN Reihe stehen."""
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        v = self._vertrag(basis=B2020, punkte='106.9', modell='fest', basis_referenzzinssatz=D('1.25'))
        c = Client()
        c.force_login(_team_user(rolle='Verwaltung'))
        url = reverse('fw_mietzins_anpassung', args=[v.pk])
        with self._heute():
            c.post(url, {'aktion': 'entwurf', 'lik_basis': B2010, 'basis_lik': '106.9', 'basis_lik_stand': '2025-12'})
        v.refresh_from_db()
        self.assertEqual((v.lik_basis, v.basis_lik_punkte), (B2020, D('106.9')))     # 106.9 ist der Wert der Reihe 2020
        with self._heute():
            c.post(url, {'aktion': 'entwurf', 'lik_basis': B2010, 'basis_lik': str(KUNST_2010_DEZ_2025),
                         'basis_lik_stand': '2025-12', 'neu_netto': '2000'})
        v.refresh_from_db()
        self.assertEqual((v.lik_basis, v.basis_lik_punkte), (B2010, D(str(KUNST_2010_DEZ_2025))))

    def test_nach_einer_gebuchten_anpassung_ist_die_basisreihe_fest(self):
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        v = self._vertrag(basis=B2020, punkte='106.9', modell='fest', basis_referenzzinssatz=D('1.25'))
        MietzinsAnpassung.objects.create(
            vertrag=v, wirksam_ab=date(2026, 6, 1), neuer_netto_mietzins=D('2010'), alter_netto_mietzins=D('2000'),
            neuer_lik_index=D('108.3'), status=MietzinsAnpassung.STATUS_VERSANDT)
        c = Client()
        c.force_login(_team_user(rolle='Verwaltung'))
        with self._heute():
            r = c.post(reverse('fw_mietzins_anpassung', args=[v.pk]),
                       {'aktion': 'entwurf', 'lik_basis': B2010, 'basis_lik': str(KUNST_2010_DEZ_2025),
                        'basis_lik_stand': '2025-12'}, follow=True)
        v.refresh_from_db()
        self.assertEqual(v.lik_basis, B2020)
        self.assertTrue(any('nicht mehr ändern' in str(m) for m in r.context['messages']))


# ── Betreiber-Seite ──────────────────────────────────────────────────────────
class BetreiberSeiteTests(_Basis):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.betreiber = U.objects.create_superuser('bt', 'bt@example.com', 'x')
        cls.normal = U.objects.create_user('nm', 'nm@example.com', 'x')

    def setUp(self):
        super().setUp()
        self.client.force_login(self.betreiber)
        self.url = reverse('fw_betreiber_lik')
        self.heute = mock.patch('core.views.fw.betreiber.datum_heute', return_value=HEUTE)
        self.heute.start()
        self.addCleanup(self.heute.stop)

    def test_der_umschalter_zeigt_die_gewaehlte_reihe(self):
        _reihe_anlegen(B2010, R2010_2026, dez_2025=KUNST_2010_DEZ_2025)
        r = self.client.get(self.url, {'basis': B2010})
        self.assertEqual(r.context['basis'], B2010)
        self.assertEqual([(z['jahr'], z['monat'], z['punkte']) for z in r.context['zeilen']][0], (2026, 10, 106.7))
        self.assertEqual([b['name'] for b in r.context['basen']], list(lik.LIK_BASEN))
        self.assertContains(r, 'data-testid="lik-basen"')
        self.assertContains(r, 'name="basis" value="Dezember 2010"')
        # Gegenprobe: ohne Angabe (und mit einer unbekannten) die Standardreihe
        standard = self.client.get(self.url)
        self.assertEqual(standard.context['basis'], B2020)
        self.assertEqual([(z['jahr'], z['monat'], z['punkte']) for z in standard.context['zeilen']][0], (2026, 9, 108.5))
        self.assertEqual(self.client.get(self.url, {'basis': 'Mai 2000'}).context['basis'], B2020)

    def test_eine_leere_reihe_sagt_es(self):
        r = self.client.get(self.url, {'basis': B2025})
        self.assertContains(r, 'data-testid="lik-reihe-leer"')
        self.assertEqual(r.context['zeilen'], [])
        self.assertNotContains(self.client.get(self.url), 'data-testid="lik-reihe-leer"')     # Gegenprobe

    def test_einlesen_wirkt_auf_die_gewaehlte_reihe(self):
        with mock.patch.object(lik, '_hev_html', return_value=seite()):
            r = self.client.post(self.url, {'aktion': 'einlesen', 'basis': B2025})
        self.assertRedirects(r, f'{self.url}?basis=Dezember+2025', fetch_redirect_response=False)
        self.assertEqual(LikWert.objects.filter(basis=B2025).count(), 11)
        self.assertEqual(LikWert.objects.exclude(basis=B2025).count(), 0)
        self.assertTrue(SicherheitsEreignis.objects.filter(aktion='LIK-Reihe eingelesen', objekt=B2025).exists())

    def test_einlesen_meldet_den_grund_wenn_nichts_gespeichert_wird(self):
        with mock.patch.object(lik, '_hev_html', return_value=seite()):
            r = self.client.post(self.url, {'aktion': 'einlesen', 'basis': B2010}, follow=True)
        self.assertContains(r, 'nicht eingelesen')
        self.assertContains(r, 'Basismonat 12/2010')
        self.assertEqual(LikWert.objects.count(), 0)

    def test_abrufen_wirkt_auf_die_gewaehlte_reihe(self):
        _reihe_anlegen(B2025, R2025_2026[:9])
        with mock.patch.object(lik, '_hev_html', return_value=seite()):
            self.client.post(self.url, {'aktion': 'abrufen', 'basis': B2025})
        self.assertEqual(LikWert.objects.get(basis=B2025, jahr=2026, monat=10).punkte, D('101.7'))
        self.assertFalse(LikWert.objects.filter(basis=B2020).exists())      # Gegenprobe: 2020 nicht nachgeführt
        ereignis = SicherheitsEreignis.objects.get(aktion='LIK-Wert automatisch nachgetragen')
        self.assertIn('Reihe Dezember 2025', ereignis.details)

    def test_der_nachtrag_von_hand_landet_in_der_gewaehlten_reihe(self):
        _reihe_anlegen(B2025, R2025_2026[:9])
        r = self.client.post(self.url, {'basis': B2025, 'jahr': '2026', 'monat': '10', 'punkte': '101,7',
                                        'quelle': 'BFS, Medienmitteilung'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(LikWert.objects.get(basis=B2025, jahr=2026, monat=10).punkte, D('101.7'))
        self.assertIsNone(lik.lik_punkte_fuer(2026, 10))                    # Gegenprobe: nicht in der Standardreihe

    def test_ein_wert_einer_anderen_reihe_faellt_beim_nachtrag_auf(self):
        """108.7 ist der Oktober der Reihe 2020; in der Reihe 2025 (September 101.5) ist das ein Sprung."""
        _reihe_anlegen(B2025, R2025_2026[:9])
        r = self.client.post(self.url, {'basis': B2025, 'jahr': '2026', 'monat': '10', 'punkte': '108.7',
                                        'quelle': 'BFS'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'anderen Basisreihe')
        self.assertFalse(LikWert.objects.filter(basis=B2025, jahr=2026, monat=10).exists())
        # Gegenprobe: Die feste Grenze der Standardreihe (100 bis 140) gilt hier nicht — 99.9 ist ein gültiger Wert
        LikWert.objects.filter(basis=B2025, jahr=2026).delete()
        lik.cache_leeren()
        r = self.client.post(self.url, {'basis': B2025, 'jahr': '2026', 'monat': '1', 'punkte': '99.9', 'quelle': 'BFS'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(LikWert.objects.get(basis=B2025, jahr=2026, monat=1).punkte, D('99.9'))

    def test_loeschen_trifft_nur_die_gewaehlte_reihe(self):
        _reihe_anlegen(B2025, R2025_2026[:9])
        w = LikWert.objects.get(basis=B2025, jahr=2026, monat=9)
        self.client.post(self.url, {'aktion': 'loeschen', 'pk': w.pk})      # ohne Reihe = Standardreihe: findet nichts
        self.assertTrue(LikWert.objects.filter(pk=w.pk).exists())
        self.client.post(self.url, {'aktion': 'loeschen', 'pk': w.pk, 'basis': B2025})
        self.assertFalse(LikWert.objects.filter(pk=w.pk).exists())
        self.assertIn('Reihe Dezember 2025', SicherheitsEreignis.objects.get(aktion='LIK-Wert gelöscht').details)

    def test_einlesen_darf_nur_der_betreiber(self):
        self.client.force_login(self.normal)
        with mock.patch.object(lik, 'reihe_einlesen') as einlesen:
            r = self.client.post(self.url, {'aktion': 'einlesen', 'basis': B2025})
        self.assertEqual(r.status_code, 403)
        einlesen.assert_not_called()
