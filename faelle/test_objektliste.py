"""Objektliste nach G9 — Befunde je Objekt, Gruppierung, Filter.

DER BEFUND, DER DIE ETAPPE AUSGELOEST HAT (Bildschirmfoto 21.08.2026)

Beide leeren Wohnungen an der Selzacherstrasse zeigten «Soll-Miete —». Das ist
die eigentliche Nachricht der Seite — zwei Wohnungen stehen leer und haben
keinen Preis hinterlegt, man kann sie also nicht ausschreiben — und sie stand
dort als Gedankenstrich.

`KonsistenzTests` ist der wichtigste Satz in dieser Datei: Er haelt
Liegenschaftsliste und Objektliste nebeneinander und laesst sie ueber dieselben
Faelle urteilen. Solange beide dieselbe Leerstandsregel behaupten, muss das
belegt sein und nicht bloss im Kommentar stehen.
"""
import re
from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.objekte import gruppen, streifen, zeilen

HEUTE = timezone.localdate()

#: `base.html` liefert Skript und CSS inline mit JEDER Seite aus. Ein Waechter,
#: der nach einer Klasse sucht, findet sie deshalb auch in einem Kommentar —
#: `hidden md:block` steht dort in einer JS-Erlaeuterung. Wer nach Markup
#: fragt, schneidet die Bloecke vorher weg. (Sechstes Mal in dieser Phase,
#: dass ein Waechter seine eigene Erklaerung gelesen hat.)
_BLOCK = re.compile(r'<(script|style)\b.*?</\1>', re.DOTALL | re.IGNORECASE)


def _nur_markup(html):
    return _BLOCK.sub('', html)


class _Basis(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    @property
    def lg(self):
        return self.a.einheit.liegenschaft

    def _einheit(self, bez, **felder):
        from portfolio.models import Einheit
        werte = {'liegenschaft': self.lg, 'bezeichnung': bez, 'typ': 'whg',
                 'nettomiete_aktuell': Decimal('1500')}
        werte.update(felder)
        return Einheit.objects.create(**werte)

    def _vertrag(self, einheit, beginn, ende=None, status='aktiv'):
        from rentals.models import Mietvertrag
        return Mietvertrag.objects.create(
            einheit=einheit, mieter=self.a.mieter, beginn=beginn, ende=ende,
            status=status, netto_mietzins=Decimal('1500'),
            nebenkosten=Decimal('0'))

    def _texte(self, einheit):
        return [b['text'] for b in zeilen([einheit])[0]['befunde']]


class BefundTests(_Basis):

    def test_leere_wohnung_ohne_mietzins_ist_kritisch(self):
        """DER BEFUND AUS DEM BILDSCHIRMFOTO. Was keinen Preis hat, laesst sich
        nicht ausschreiben — und die Seite sagte dazu einen Gedankenstrich."""
        with mandant(self.a.organisation):
            e = self._einheit('EG links', nettomiete_aktuell=Decimal('0'))
            zeile = zeilen([e])[0]
        self.assertIn('Kein Mietzins', [b['text'] for b in zeile['befunde']])
        self.assertEqual(zeile['stufe'], 'crit')

    def test_leere_wohnung_mit_zins_aber_ohne_inserat(self):
        with mandant(self.a.organisation):
            texte = self._texte(self._einheit('1. OG', zur_ausschreibung=False))
        self.assertIn('Steht leer', texte)
        self.assertIn('Nicht ausgeschrieben', texte)

    def test_ausgeschriebene_leere_wohnung_meldet_nur_den_leerstand(self):
        """Gegenprobe: Wer inseriert hat, soll nicht dafuer geruegt werden."""
        with mandant(self.a.organisation):
            texte = self._texte(self._einheit('2. OG', zur_ausschreibung=True))
        self.assertIn('Steht leer', texte)
        self.assertNotIn('Nicht ausgeschrieben', texte)
        self.assertNotIn('Kein Mietzins', texte)

    def test_vermietete_wohnung_meldet_nichts(self):
        """Die wichtigste Gegenprobe — sonst stuende an jeder Zeile etwas."""
        with mandant(self.a.organisation):
            zeile = zeilen([self.a.einheit])[0]
        self.assertEqual(zeile['befunde'], [])
        self.assertEqual(zeile['stufe'], 'good')
        self.assertTrue(zeile['belegt'])

    def test_vermietete_wohnung_ohne_sollzins_wird_nicht_geruegt(self):
        """Bei einem laufenden Vertrag ergibt sich der Zins aus dem Vertrag.

        «Kein Mietzins» waere dort eine Beschwerde ueber etwas, das niemanden
        hindert — die Wohnung ist ja vermietet.
        """
        from portfolio.models import Einheit
        with mandant(self.a.organisation):
            Einheit.objects.filter(id=self.a.einheit.id).update(
                nettomiete_aktuell=Decimal('0'))
            e = Einheit.objects.get(id=self.a.einheit.id)
            self.assertNotIn('Kein Mietzins', self._texte(e))

    def test_der_mieter_steht_an_der_zeile(self):
        with mandant(self.a.organisation):
            zeile = zeilen([self.a.einheit])[0]
        self.assertEqual(zeile['mieter'], self.a.mieter.display_name)
        self.assertEqual(zeile['vertrag_id'], self.a.vertrag.id)

    def test_gekuendigte_wohnung_wird_frei_gemeldet(self):
        """Die Vermarktung beginnt beim Kuendigungseingang, nicht beim Auszug."""
        from rentals.models import Mietvertrag
        with mandant(self.a.organisation):
            ende = HEUTE + timedelta(days=60)
            Mietvertrag.objects.filter(id=self.a.vertrag.id).update(
                status='gekuendigt', ende=ende)
            zeile = zeilen([self.a.einheit])[0]
            befund = next(b for b in zeile['befunde'] if b['text'] == 'Wird frei')
        self.assertIn((ende + timedelta(days=1)).strftime('%d.%m.%Y'),
                      befund['titel'])

    def test_ein_nachmieter_hebt_den_befund_auf(self):
        """Per 30.09. gekuendigt und per 01.10. neu vermietet heisst: kein
        Leerstand. Das zu melden waere Rauschen — und Rauschen fuehrt dazu,
        dass die echten Meldungen ueberlesen werden."""
        from rentals.models import Mietvertrag
        with mandant(self.a.organisation):
            ende = HEUTE + timedelta(days=60)
            Mietvertrag.objects.filter(id=self.a.vertrag.id).update(
                status='gekuendigt', ende=ende)
            self.assertIn('Wird frei', self._texte(self.a.einheit))   # Vorzustand

            self._vertrag(self.a.einheit, ende + timedelta(days=1))
            zeile = zeilen([self.a.einheit])[0]
        self.assertEqual(zeile['befunde'], [])
        self.assertEqual(zeile['nachmieter_ab'], ende + timedelta(days=1))

    def test_langer_leerstand_wiegt_schwerer_als_frischer(self):
        """Zehn Monate leer ist etwas anderes als seit letzter Woche."""
        with mandant(self.a.organisation):
            e = self._einheit('Dachwohnung')
            self._vertrag(e, HEUTE - timedelta(days=800),
                          ende=HEUTE - timedelta(days=300), status='archiviert')
            leer = next(b for b in zeilen([e])[0]['befunde']
                        if b['text'] == 'Steht leer')
        self.assertEqual(leer['stufe'], 'crit')
        self.assertIn('Monate', leer['titel'])

    def test_frischer_leerstand_ist_nur_eine_warnung(self):
        with mandant(self.a.organisation):
            e = self._einheit('Studio')
            self._vertrag(e, HEUTE - timedelta(days=400),
                          ende=HEUTE - timedelta(days=10), status='archiviert')
            leer = next(b for b in zeilen([e])[0]['befunde']
                        if b['text'] == 'Steht leer')
        self.assertEqual(leer['stufe'], 'warn')

    def test_nie_vermietet_sagt_das_auch(self):
        """Ein Neubau ohne Vertragshistorie ist kein «seit unbekannt»."""
        with mandant(self.a.organisation):
            leer = next(b for b in zeilen([self._einheit('Neubau')])[0]['befunde']
                        if b['text'] == 'Steht leer')
        self.assertIn('noch nie vermietet', leer['titel'])

    def test_ein_entwurf_belegt_nichts_und_zaehlt_nicht_als_vergangenheit(self):
        """Ein nie in Kraft getretener Vertrag hat die Wohnung nie belegt."""
        with mandant(self.a.organisation):
            e = self._einheit('Entwurfswohnung')
            self._vertrag(e, HEUTE - timedelta(days=400),
                          ende=HEUTE - timedelta(days=100), status='entwurf')
            zeile = zeilen([e])[0]
            leer = next(b for b in zeile['befunde'] if b['text'] == 'Steht leer')
        self.assertFalse(zeile['belegt'])
        self.assertIn('noch nie vermietet', leer['titel'])

    def test_nebenobjekt_am_hauptvertrag_gilt_als_belegt(self):
        """Ein Kellerabteil ohne eigenen Vertrag ist kein Leerstand — man
        vermietet es nicht einzeln."""
        with mandant(self.a.organisation):
            keller = self._einheit('Keller 3', typ='bas',
                                   nettomiete_aktuell=Decimal('0'))
            self.a.vertrag.nebenobjekte.add(keller)
            zeile = zeilen([keller])[0]
        self.assertTrue(zeile['belegt'])
        self.assertEqual(zeile['befunde'], [])

    def test_der_bastelraum_ist_ueber_den_typfilter_erreichbar(self):
        """`bas` stand bis 4b.17 in KEINER Filtergruppe.

        Ein Objekttyp, den kein Filter trifft, ist ueber die Filterleiste
        unsichtbar — man findet ihn nur, indem man alle Filter abwaehlt.
        """
        from faelle.objekte import TYP_GRUPPEN
        alle = {t for gruppe in TYP_GRUPPEN.values() for t in gruppe}
        from portfolio.models import Einheit
        for schluessel, _label in Einheit.TYP_CHOICES:
            with self.subTest(typ=schluessel):
                self.assertIn(schluessel, alle)


class KonsistenzTests(_Basis):
    """Objektliste und Liegenschaftsliste muessen dasselbe sagen.

    Beide behaupten dieselbe Leerstandsregel; die Statuslisten teilen sie sich
    per Import. Der Rest ist zwangslaeufig getrennter Code — `liegenschaften.
    _leerstand` rechnet je Liegenschaft und holt in derselben Schleife die
    Ist-Miete, `objekte._belegung` braucht den Zustand je EINZELNER Einheit.

    Dieser Satz ist der Ersatz fuer das, was man nicht teilen kann: Er stellt
    beide Module vor dieselben Faelle und vergleicht das Urteil. Weicht eines
    ab, wird er rot — und zwar bevor Liste und Akte einem Nutzer
    Verschiedenes ueber dieselbe Wohnung sagen.
    """

    def _vergleich(self):
        from faelle.liegenschaften import zeilen as lg_zeilen
        from portfolio.models import Einheit
        lg_zeile = lg_zeilen([self.lg])[0]
        obj = list(zeilen(Einheit.objects.filter(liegenschaft=self.lg)))
        # Verglichen wird `versorgt`, nicht `belegt`. `belegt` ist die
        # PHYSISCHE Belegung und steuert die Zeilendarstellung; die
        # Leerstandszahl beider Seiten meint «ohne Mieter UND ohne Nachfolge».
        # Der erste Anlauf verglich `belegt` und wurde prompt rot — zu Recht:
        # Eine gekuendigte Wohnung mit Nachmieter ist heute leer, und die
        # Liegenschaftsliste zaehlt sie trotzdem nicht.
        return lg_zeile['leer'], sum(1 for z in obj if not z['versorgt'])

    def test_beide_zaehlen_denselben_leerstand_im_normalfall(self):
        with mandant(self.a.organisation):
            self._einheit('Leer A', nettomiete_aktuell=Decimal('0'))
            self._einheit('Leer B')
            lg_leer, obj_leer = self._vergleich()
        self.assertEqual(lg_leer, obj_leer)
        self.assertEqual(lg_leer, 2)

    def test_beide_behandeln_den_gekuendigten_vertrag_gleich(self):
        """Bis zum Vertragsende belegt — in beiden Modulen."""
        from rentals.models import Mietvertrag
        with mandant(self.a.organisation):
            Mietvertrag.objects.filter(id=self.a.vertrag.id).update(
                status='gekuendigt', ende=HEUTE + timedelta(days=60))
            lg_leer, obj_leer = self._vergleich()
        self.assertEqual(lg_leer, obj_leer)
        self.assertEqual(lg_leer, 0)

    def test_beide_behandeln_den_abgelaufenen_vertrag_gleich(self):
        from rentals.models import Mietvertrag
        with mandant(self.a.organisation):
            Mietvertrag.objects.filter(id=self.a.vertrag.id).update(
                status='gekuendigt', ende=HEUTE - timedelta(days=1))
            lg_leer, obj_leer = self._vergleich()
        self.assertEqual(lg_leer, obj_leer)
        self.assertEqual(lg_leer, 1)

    def test_beide_behandeln_den_nachmieter_gleich(self):
        """In der Liegenschaftsliste hebt ein Nachmieter den Leerstand auf.
        In der Objektliste muss dieselbe Einheit dann ebenfalls belegt sein.
        """
        from rentals.models import Mietvertrag
        with mandant(self.a.organisation):
            leer = self._einheit('Bald wieder voll')
            self._vertrag(leer, HEUTE + timedelta(days=30))
            lg_leer, obj_leer = self._vergleich()
            zeile = zeilen([leer])[0]
        self.assertEqual(lg_leer, obj_leer)
        # Die Objektliste faerbt die Zeile nicht ein — sie zeigt stattdessen,
        # wann der Nachmieter kommt.
        self.assertEqual(zeile['befunde'], [])
        self.assertIsNotNone(zeile['nachmieter_ab'])

    def test_beide_behandeln_das_nebenobjekt_gleich(self):
        with mandant(self.a.organisation):
            keller = self._einheit('Keller 9', typ='bas',
                                   nettomiete_aktuell=Decimal('0'))
            self.a.vertrag.nebenobjekte.add(keller)
            lg_leer, obj_leer = self._vergleich()
        self.assertEqual(lg_leer, obj_leer)
        self.assertEqual(lg_leer, 0)

    def test_die_statuslisten_sind_geteilt_und_nicht_abgeschrieben(self):
        """Waeren sie kopiert, koennte eine Fassung erweitert werden und die
        andere nicht — und niemand merkte es."""
        from faelle import liegenschaften, objekte
        self.assertIs(objekte.BELEGENDE_STATUS, liegenschaften.BELEGENDE_STATUS)
        self.assertIs(objekte.NACHMIETER_STATUS, liegenschaften.NACHMIETER_STATUS)


class GruppenTests(_Basis):
    """Gruppierung nach Liegenschaft bleibt — Ordnung folgt dem Befund."""

    def _zweite_lg(self):
        from portfolio.models import Einheit, Liegenschaft
        laut = Liegenschaft.objects.create(
            organisation=self.a.organisation, strasse='Zeta-Weg 1',
            plz='8000', ort='Zürich', eigentuemer=self.a.eigentuemer)
        Einheit.objects.create(liegenschaft=laut, bezeichnung='Leer 1',
                               typ='whg', nettomiete_aktuell=Decimal('0'))
        return laut

    def _gruppen(self):
        from portfolio.models import Einheit
        return gruppen(zeilen(Einheit.objects.all()))

    def test_die_laute_liegenschaft_steht_oben(self):
        """Trotz «Zeta» im Namen — sortiert wird nach Befund, nicht nach ABC.

        Genau darum geht es: Vorher entschied `strasse` die Reihenfolge, und
        die Liegenschaft mit der leeren Wohnung landete unten, weil sie mit
        einem spaeten Buchstaben beginnt.
        """
        with mandant(self.a.organisation):
            laut = self._zweite_lg()
            g = self._gruppen()
        self.assertEqual(g[0]['lg'].id, laut.id)
        self.assertEqual(g[1]['lg'].id, self.lg.id)

    def test_die_laute_gruppe_ist_offen_die_ruhige_zu(self):
        """Was nichts zu sagen hat, soll keinen Bildschirm beanspruchen."""
        with mandant(self.a.organisation):
            laut = self._zweite_lg()
            g = {x['lg'].id: x for x in self._gruppen()}
        self.assertTrue(g[laut.id]['offen'])
        self.assertFalse(g[self.lg.id]['offen'])

    def test_innerhalb_der_gruppe_steht_der_befund_vorn(self):
        """Sonst stuende der vermietete Parkplatz vor der leeren Wohnung, nur
        weil er «P» heisst. Drei Objekte, damit die Sortierung etwas zu tun
        hat — bei einer Zeile ist jede Reihenfolge richtig.
        """
        with mandant(self.a.organisation):
            self._einheit('Aaa leer', nettomiete_aktuell=Decimal('0'))
            self._einheit('Zzz leer', zur_ausschreibung=True)
            g = self._gruppen()
        bez = [z['e'].bezeichnung for z in g[0]['zeilen']]
        # «Aaa leer» traegt den crit-Befund (kein Zins), «Zzz leer» nur warn,
        # der vermietete Bestand gar keinen.
        self.assertEqual(bez[0], 'Aaa leer')
        self.assertEqual(bez[1], 'Zzz leer')
        self.assertEqual(bez[-1], self.a.einheit.bezeichnung)


class StreifenTests(_Basis):

    def test_die_vier_zahlen(self):
        with mandant(self.a.organisation):
            self._einheit('Leer', nettomiete_aktuell=Decimal('0'))
            from portfolio.models import Einheit
            k = streifen(zeilen(Einheit.objects.filter(liegenschaft=self.lg)))
        self.assertEqual(k['gesamt'], 2)
        self.assertEqual(k['belegt'], 1)
        self.assertEqual(k['leer'], 1)
        self.assertEqual(k['mit_befund'], 1)
        self.assertEqual(k['befund_stufe'], 'crit')

    def test_ohne_befund_keine_markierung(self):
        """Gegenprobe — sonst waere der Streifen dauerhaft eingefaerbt."""
        with mandant(self.a.organisation):
            k = streifen(zeilen([self.a.einheit]))
        self.assertEqual(k['mit_befund'], 0)
        self.assertEqual(k['befund_stufe'], '')
        self.assertEqual(k['leer_stufe'], '')

    def test_leerer_bestand_wirft_nicht(self):
        self.assertEqual(streifen([])['gesamt'], 0)


class AbfragezahlTests(_Basis):
    """Die Objektliste ist eine der meistbesuchten Seiten.

    Die Befundrechnung laeuft ueber ALLE Einheiten in einer festen Zahl von
    Abfragen — nicht je Objekt. Bei 200 Wohnungen waere der Unterschied
    zwischen vier und vierhundert Abfragen der zwischen benutzbar und nicht.
    """

    def test_dreissig_einheiten_kosten_nicht_mehr_als_eine(self):
        """Drei Abfragen: Vertraege, Nebenobjekt-Vertraege, deren Zuordnung.

        Das Nebenobjekt steht bewusst im Aufbau. Ohne eines fuehrt Django den
        Prefetch gar nicht erst aus, und der Waechter stuende bei zwei — er
        wuerde die teuerste der drei Abfragen nie zu Gesicht bekommen.
        """
        from portfolio.models import Einheit
        with mandant(self.a.organisation):
            for i in range(30):
                self._einheit(f'Messwohnung {i}')
            keller = self._einheit('Messkeller', typ='bas')
            self.a.vertrag.nebenobjekte.add(keller)
            liste = list(Einheit.objects.select_related('liegenschaft'))
            with self.assertNumQueries(3):
                rows = zeilen(liste)
        self.assertEqual(len(rows), 32)

    def test_gruppen_und_streifen_kosten_keine_abfrage(self):
        from portfolio.models import Einheit
        with mandant(self.a.organisation):
            rows = zeilen(Einheit.objects.select_related('liegenschaft'))
            with self.assertNumQueries(0):
                gruppen(rows)
                streifen(rows)


class SeitenTests(_Basis):
    """Die gerenderte Seite — nicht nur die Funktionen dahinter.

    Das Entfernen des Sammlers auf der Startseite liess seinerzeit keinen Test
    scheitern, weil alle Tests die Funktion prueften und keiner die Seite.
    """

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def _leere_wohnung(self):
        return self._einheit('Leerstand-Testwohnung',
                             nettomiete_aktuell=Decimal('0'))

    def test_der_befund_erreicht_die_seite(self):
        with mandant(self.a.organisation):
            self._leere_wohnung()
            html = self.c.get('/neu/objekte/').content.decode()
        self.assertIn('Leerstand-Testwohnung', html)
        self.assertIn('Kein Mietzins', html)

    def test_der_kennzahlenstreifen_steht_da(self):
        with mandant(self.a.organisation):
            html = self.c.get('/neu/objekte/').content.decode()
        self.assertIn('class="fw-lage"', html)
        self.assertIn('Mit Befund', html)

    def test_es_gibt_kein_zweites_suchfeld_mehr(self):
        """Die Topbar hat eines. Zwei Suchfelder sind eine Frage zu viel."""
        with mandant(self.a.organisation):
            html = self.c.get('/neu/objekte/').content.decode()
        self.assertNotIn('Objekt oder Strasse suchen', html)

    def test_die_doppelte_darstellung_ist_weg(self):
        """Vorher Karten UND Tabelle nebeneinander — 133 Zeilen doppelte
        Pflege, und die Chips dort liefen an der Petrol-Palette vorbei."""
        with mandant(self.a.organisation):
            html = self.c.get('/neu/objekte/').content.decode()
        # Geprueft wird die TABELLENHAELFTE, nicht die Farbklasse. Erster
        # Anlauf suchte `bg-emerald-50` und war rot — getroffen hat er den
        # Kommentar im Palette-Skript von `base.html`, das auf JEDER Seite
        # mitgeliefert wird. Zum fuenften Mal in dieser Phase las ein Waechter
        # die Erklaerung statt die Sache; `hidden md:block` steht dagegen nur
        # dort, wo wirklich eine zweite Darstellung haengt.
        markup = _nur_markup(html)
        self.assertNotIn('hidden md:block', markup)
        self.assertNotIn('md:hidden', markup)
        self.assertNotIn('<table', markup)
        self.assertIn('fw-zeile', markup)

    def test_der_waechter_wuerde_die_tabelle_auch_wirklich_finden(self):
        """Gegenprobe zur Gegenprobe: `_nur_markup` darf nicht zu viel
        wegnehmen — sonst waere die Pruefung oben immer gruen."""
        self.assertIn('<table', _nur_markup('<script>x</script><table>'))
        self.assertNotIn('weg', _nur_markup('<script>weg</script><div>a</div>'))
        self.assertNotIn('weg', _nur_markup('<style>weg</style><div>a</div>'))

    def test_filter_mit_befund_reduziert(self):
        with mandant(self.a.organisation):
            self._leere_wohnung()
            html = self.c.get('/neu/objekte/?zustand=befund').content.decode()
        self.assertIn('Leerstand-Testwohnung', html)
        self.assertNotIn(self.a.einheit.bezeichnung, html)

    def test_der_kopf_zeigt_trotz_filter_das_ganze_portfolio(self):
        """Sonst stuende dort «2 von 2 mit Befund» und der Streifen waere
        wertlos. Geprueft wird der STREIFEN, nicht die ganze Seite."""
        with mandant(self.a.organisation):
            self._leere_wohnung()
            antwort = self.c.get('/neu/objekte/?zustand=befund')
        self.assertEqual(antwort.context['kopf']['gesamt'], 2)
        self.assertEqual(antwort.context['kopf']['mit_befund'], 1)
        html = antwort.content.decode()
        streif = html[html.index('class="fw-lage"'):html.index('class="fw-filters"')]
        self.assertIn('>2<', streif)

    def test_ein_unbekannter_zustand_zeigt_alles_statt_nichts(self):
        with mandant(self.a.organisation):
            antwort = self.c.get('/neu/objekte/?zustand=unfug')
        self.assertEqual(antwort.context['zustand'], '')
        self.assertFalse(antwort.context['gefiltert'])

    def test_typfilter_wirkt_weiterhin(self):
        with mandant(self.a.organisation):
            pp = self._einheit('Parkplatz Nord', typ='pp',
                               nettomiete_aktuell=Decimal('90'))
            html = self.c.get('/neu/objekte/?typ=parkplatz').content.decode()
        self.assertIn(pp.bezeichnung, html)
        self.assertNotIn(self.a.einheit.bezeichnung, html)

    def test_leerzustand_hat_eine_handlungsaufforderung(self):
        """«Nichts da» heisst «hier anfangen», nicht «Sackgasse»."""
        with mandant(self.a.organisation):
            html = self.c.get('/neu/objekte/?zustand=befund').content.decode()
        self.assertIn('Nichts zu tun', html)
        self.assertIn('Alle Objekte zeigen', html)


class TrennungTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_b_sieht_die_objekte_von_a_nicht(self):
        c = Client()
        c.force_login(self.b.benutzer)
        with mandant(self.b.organisation):
            html = c.get('/neu/objekte/').content.decode()
        self.assertNotIn(self.a.einheit.bezeichnung, html)
        self.assertIn(self.b.einheit.bezeichnung, html)

    def test_der_kopf_zaehlt_nur_den_eigenen_bestand(self):
        """Eine Zaehlung ueber die Mandantengrenze waere der leiseste Weg,
        fremde Daten zu verraten — man saehe die Objekte nicht, wuesste aber,
        wie viele es sind."""
        from portfolio.models import Einheit
        with mandant(self.b.organisation):
            eigene = Einheit.objects.count()
            kopf = streifen(zeilen(Einheit.objects.select_related('liegenschaft')))
        self.assertEqual(kopf['gesamt'], eigene)
        self.assertEqual(eigene, 1)

    def test_ein_fremder_vertrag_belegt_keine_eigene_einheit(self):
        """Die heikelste Stelle: `_belegung` fragt Vertraege ueber Einheit-Ids.

        Liefe sie am Mandantenfilter vorbei, koennte ein Vertrag von A eine
        Einheit von B als belegt ausweisen — und der Leerstand von B waere
        stillschweigend falsch.
        """
        from portfolio.models import Einheit
        with mandant(self.b.organisation):
            zeile = zeilen(Einheit.objects.select_related('liegenschaft'))[0]
        self.assertEqual(zeile['mieter'], self.b.mieter.display_name)
