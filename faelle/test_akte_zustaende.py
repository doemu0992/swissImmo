"""Die Vertragsakte muss Zustaende zeigen, nicht Felder.

NEBENBEFUND: Ein vierter Hinweis («Referenzzins-Basis fehlt») war zunaechst
eingebaut. Der Test dazu brach mit IntegrityError ab — `basis_referenzzinssatz`
ist NOT NULL mit Vorgabewert. Die Bedingung haette nie zugetroffen; der Hinweis
ist entfernt.

WARUM

Bis zum 19.08.2026 zeigte der Kopf der Vertragsakte den Chip «Aktiv» — das
Datenbankfeld — und in der Kennzahlenleiste Beginn und Ende. Beides beantwortet
die Frage nicht, um die es beim Aufschlagen einer Akte geht: steht sie gut da.

Besonders auffaellig war `Mietvertrag.mietzinspotenzial`: Die Eigenschaft
rechnet den Referenzzinsvergleich seit Langem sauber und wurde auf der
Vertragsakte an **null** Stellen abgefragt. Ein Senkungsanspruch des Mieters
blieb damit unsichtbar, obwohl das Programm ihn kannte.

Diese Tests halten fest, dass die gerechneten Zustaende auch wirklich
erscheinen — und dass sie verschwinden, wenn es nichts zu melden gibt.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture


def _kopf(vertrag, offen=Decimal('0'), posten=(), pendenzen=()):
    from core.views.fw.detailseiten import _akte_kopfzahlen
    return _akte_kopfzahlen(vertrag, offen, list(posten), list(pendenzen))


class ChipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_ohne_besonderheit_nur_der_status(self):
        with mandant(self.a.organisation):
            chips = _kopf(self.a.vertrag)['kopf_chips']
            self.assertEqual([t for _a, t in chips], ['Aktiv'])

    def test_offene_monatsmiete_wird_zum_chip(self):
        with mandant(self.a.organisation):
            v = self.a.vertrag
            brutto = (v.netto_mietzins or 0) + (v.nebenkosten or 0)
            chips = _kopf(v, offen=brutto * 2)['kopf_chips']
            texte = [t for _a, t in chips]
            self.assertIn('2 Monatsmieten offen', texte)
            self.assertIn('crit', [a for a, _t in chips])

    def test_kleiner_rest_ist_eine_warnung_keine_monatsmiete(self):
        """Unter einer Monatsmiete ist es ein Betrag, kein Zahlungsverzug."""
        with mandant(self.a.organisation):
            chips = _kopf(self.a.vertrag, offen=Decimal('40'))['kopf_chips']
            texte = ' '.join(t for _a, t in chips)
            self.assertIn('offen', texte)
            self.assertNotIn('Monatsmiete', texte)

    def test_senkungsanspruch_erscheint_wenn_das_modell_ihn_kennt(self):
        """Der Anschluss, der jahrelang fehlte."""
        with mandant(self.a.organisation):
            v = self.a.vertrag
            org = self.a.organisation
            v.basis_referenzzinssatz = Decimal('1.75')
            v.save()
            org.aktueller_referenzzinssatz = Decimal('1.25')
            org.save()
            self.assertEqual(v.mietzinspotenzial, 'decrease')
            chips = _kopf(v)['kopf_chips']
            self.assertIn('Senkungsanspruch offen', [t for _a, t in chips])

    def test_bei_gleichem_zins_kein_chip(self):
        """Gegenprobe — sonst stuende der Hinweis immer da und hiesse nichts."""
        with mandant(self.a.organisation):
            v = self.a.vertrag
            org = self.a.organisation
            v.basis_referenzzinssatz = org.aktueller_referenzzinssatz
            v.basis_lik_punkte = org.aktueller_lik_punkte
            v.save()
            chips = _kopf(v)['kopf_chips']
            self.assertNotIn('Senkungsanspruch offen', [t for _a, t in chips])


class HinweisTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_vereinbarte_aber_unbestaetigte_kaution_faellt_auf(self):
        with mandant(self.a.organisation):
            v = self.a.vertrag
            v.kautions_art = 'sperrkonto'
            v.kautions_betrag = Decimal('4500')
            v.kautions_einbezahlt_am = None
            v.save()
            titel = [h['titel'] for h in _kopf(v)['kopf_hinweise']]
            self.assertIn('Kaution vereinbart, aber nicht bestätigt', titel)

    def test_nach_bestaetigung_verschwindet_der_hinweis(self):
        with mandant(self.a.organisation):
            v = self.a.vertrag
            v.kautions_art = 'sperrkonto'
            v.kautions_betrag = Decimal('4500')
            v.kautions_einbezahlt_am = date(2026, 1, 5)
            v.save()
            titel = [h['titel'] for h in _kopf(v)['kopf_hinweise']]
            self.assertNotIn('Kaution vereinbart, aber nicht bestätigt', titel)

    def test_jeder_hinweis_fuehrt_zu_einer_handlung(self):
        """Ein Hinweis ohne Ziel ist eine Beschwerde."""
        with mandant(self.a.organisation):
            v = self.a.vertrag
            v.kautions_art = 'sperrkonto'
            v.kautions_betrag = Decimal('4500')
            v.kautions_einbezahlt_am = None
            v.save()
            hinweise = _kopf(v)['kopf_hinweise']
            self.assertTrue(hinweise)
            for h in hinweise:
                with self.subTest(titel=h['titel']):
                    self.assertTrue(h['url'] and h['knopf'])


class KennzahlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_kaution_ohne_vereinbarung_sagt_keine(self):
        with mandant(self.a.organisation):
            v = self.a.vertrag
            v.kautions_betrag = None
            v.save()
            self.assertEqual(_kopf(v)['kopf_kaution_wert'], 'keine')

    def test_kaution_zeigt_monatsmieten(self):
        with mandant(self.a.organisation):
            v = self.a.vertrag
            v.kautions_betrag = ((v.netto_mietzins or 0) + (v.nebenkosten or 0)) * 3
            v.save()
            fuss = _kopf(v)['kopf_kaution_fuss']
            self.assertIn('3.0 Monatsmieten', fuss)

    def test_ohne_pendenz_keine_frist(self):
        with mandant(self.a.organisation):
            self.assertIsNone(_kopf(self.a.vertrag)['kopf_frist'])

    def test_frueheste_datierte_pendenz_gewinnt(self):
        class P:
            def __init__(self, tag):
                self.faellig_am = date(2026, 9, tag)
                self.titel = f'Frist {tag}'
        eintraege = [{'p': P(20), 'ueberfaellig': False},
                     {'p': P(3), 'ueberfaellig': True}]
        with mandant(self.a.organisation):
            frist = _kopf(self.a.vertrag, pendenzen=eintraege)['kopf_frist']
            self.assertEqual(frist['p'].faellig_am, date(2026, 9, 3))


class FristTitelTests(TestCase):
    """Der Titel der naechsten Frist muss ganz dastehen.

    WARUM

    Gemeldet am 20.08.2026 aus dem Browser: In der Kennzahlenleiste stand
    «Art. 257d: Zahlungsfrist läuft ab – B…». Der Titel ist 48 Zeichen lang,
    `truncatechars:38` schnitt ihn ab — ausgerechnet im Namen, also an der
    Stelle, die sagt, um wen es geht.

    Kein Test hatte das bemerkt: Die Zustands-Tests oben pruefen die
    gerechneten Werte, nicht ihre Darstellung. Aufgefallen ist es einem
    Menschen, wie schon beim Statusumschalter und bei den Kommentaren.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('T', '8000', 'Zürich')

    def _seite(self):
        from django.test import Client
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            antwort = c.get(f'/neu/vertraege/{self.a.vertrag.pk}/')
        self.assertEqual(antwort.status_code, 200)
        return antwort.content.decode()

    def test_langer_fristtitel_erscheint_vollstaendig(self):
        from core.models import Pendenz
        titel = 'Art. 257d: Zahlungsfrist läuft ab – Behlül Piskin-Langenamen'
        with mandant(self.a.organisation):
            Pendenz.objects.create(
                organisation=self.a.organisation, vertrag=self.a.vertrag,
                titel=titel, faellig_am=date(2026, 9, 12), erledigt=False)
        html = self._seite()
        self.assertIn(titel, html,
                      'Der Fristtitel steht gekuerzt oder gar nicht auf der Seite.')
        self.assertNotIn('…', html.split('Nächste Frist')[-1][:400],
                         'In der Kennzahlenleiste wird noch gekuerzt.')
        # Zwei Zeilen sind die Obergrenze der CSS-Klammer; laenger als das
        # wird doch abgeschnitten. Dann muss der volle Text wenigstens beim
        # Darueberfahren lesbar bleiben. Ohne diese Zeile blieb eine
        # Gegenprobe gruen, die das title-Attribut entfernte.
        self.assertIn(f'title="{titel}"', html,
                      'Der volle Titel fehlt im title-Attribut — bei mehr als '
                      'zwei Zeilen waere er nicht mehr lesbar.')

    def test_die_kennzahlenleiste_kuerzt_nirgends_per_filter(self):
        """Gegenprobe an der Vorlage: `truncatechars` gehoert hier nicht hin.

        Der Test oben braucht einen Titel, der laenger als die alte Grenze ist —
        wuerde jemand die Grenze auf 80 heraufsetzen, bliebe er gruen und die
        Kuerzung waere trotzdem zurueck.
        """
        import pathlib
        quelle = pathlib.Path(
            'core/templates/fw/vertrag_detail.html').read_text(encoding='utf-8')
        kopf = quelle.split('class="fw-kzn"')[1].split('_detail_tabs.html')[0]
        self.assertNotIn(
            'truncatechars', kopf,
            'In der Kennzahlenleiste wird wieder per Filter gekuerzt — der '
            'Umbruch geschieht in CSS (.fw-kzn .fw-f.fw-lang).')


class PfadTests(TestCase):
    """Jede Angabe im Aktenkopf steht auf einer eigenen Zeile.

    WARUM

    Gemeldet am 20.08.2026: Mandat, Liegenschaft, Objekt, Vertrag und Sprache
    standen als eine Kette in zwei Zeilen, getrennt durch «›» und «·». Bei
    einem langen Objektnamen brach die Kette an beliebiger Stelle um, und
    Beschriftung und Wert waren nicht mehr auseinanderzuhalten.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('P', '8000', 'Zürich')

    def _seite(self):
        from django.test import Client
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            antwort = c.get(f'/neu/vertraege/{self.a.vertrag.pk}/')
        self.assertEqual(antwort.status_code, 200)
        return antwort.content.decode()

    #: `fw-akte-pfad` steht ZWEIMAL auf der Seite: einmal als Brotkrume ganz
    #: oben, einmal im Aktenkopf. Die erste Fassung dieser Tests nahm
    #: `split(...)[1]` und untersuchte damit die Brotkrume — die Zeilenpruefung
    #: fand nichts, und die Trennzeichen-Pruefung bestand auf einem leeren
    #: Ausschnitt, war also wertlos. Deshalb wird hier ueber `fw-pz` gesucht,
    #: das es nur im Aktenkopf gibt.
    def _pfadzeilen(self, html):
        import re
        return re.findall(r'<div class="fw-pz"><span>([^<]+)</span><b>([^<]*)', html)

    def test_jede_angabe_hat_eine_eigene_zeile(self):
        zeilen = dict(self._pfadzeilen(self._seite()))
        self.assertTrue(zeilen, 'Es wurde keine einzige Pfadzeile gefunden.')
        # Mandat nur, wenn ein Eigentuemer hinterlegt ist — die uebrigen immer.
        for angabe in ('Liegenschaft', 'Objekt', 'Vertrag', 'Sprache'):
            with self.subTest(angabe=angabe):
                self.assertIn(angabe, zeilen)

    def test_die_zeilen_tragen_auch_werte(self):
        """Sonst bestuenden fuenf leere Beschriftungen die Pruefung oben."""
        zeilen = dict(self._pfadzeilen(self._seite()))
        for angabe in ('Liegenschaft', 'Objekt', 'Vertrag'):
            with self.subTest(angabe=angabe):
                self.assertTrue(zeilen.get(angabe, '').strip(),
                                f'Die Zeile «{angabe}» hat keinen Wert.')

    def test_keine_trennzeichen_mehr_in_der_kette(self):
        """Gegenprobe: Der alte Aufbau ist an seinen Trennern erkennbar."""
        html = self._seite()
        kopf = html.split('class="fw-aktenkopf"')[1].split('class="fw-kzn"')[0]
        for zeichen in ('›', 'Korrespondenzsprache'):
            with self.subTest(zeichen=zeichen):
                self.assertNotIn(
                    zeichen, kopf,
                    f'{zeichen!r} deutet auf die alte einzeilige Kette hin.')
