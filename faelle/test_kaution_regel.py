"""Die Kaution darf drei Monatszinse nicht übersteigen — bei Wohnräumen.

WAS HIER DAZUKAM

Das Regelwerk kannte vier Regelarten, gerechnet wurde eine (Kündigungstermin).
Die übrigen drei standen als Auswahlwert da, ohne Wirkung — G7 verlangt Regeln,
und eine Regel ohne Rechnung ist eine Liste.

Diese Etappe setzt die zweite um: den Höchstbetrag der Kaution.

DIE RECHTSLAGE UND WARUM SIE HIER ZWEI SEITEN HAT

Art. 257e Abs. 2 OR: Bei **Wohnräumen** darf die Sicherheit drei Monatszinse
nicht übersteigen. Bei **Geschäftsräumen** gilt die Grenze nicht — dort ist sie
frei vereinbar.

Beide Seiten sind gleich wichtig. Eine Regel, die bei Gewerbeverträgen warnt,
wäre schlimmer als keine: Wer eine unbegründete Warnung dreissigmal wegklickt,
klickt sie auch beim dreiunddreissigsten Mal weg — und das ist dann der
Wohnungsvertrag.

MASSGEBEND IST NETTO + NEBENKOSTEN — WEIL DER BESTAND ES SO RECHNET

Die erste Fassung nahm den Nettozins allein, mit der Begründung, Art. 257e
spreche vom Mietzins und die Nebenkosten seien Auslagenersatz. Das mag
rechtlich stimmen — aber `Mietvertrag.save()` klemmt seit jeher auf
**Netto + Nebenkosten**. Zwei Rechnungen für eine Vorschrift widersprechen
sich, und hier taten sie es messbar: Bei Netto 1'500 und NK 200 liess die
Klemme 5'100 zu, die Regel beanstandete ab 4'500. Eine Kaution von 5'000
wurde also gespeichert **und** beanstandet; bei 6'000 klemmte `save()` auf
5'100 — und die Regel beanstandete den Wert, den die Anwendung soeben selbst
hergestellt hatte.

Übernommen ist der Wert aus dem Bestand. Ob Art. 257e den Netto- oder den
Bruttozins meint, ist eine Rechtsfrage; sie ist hier **nicht entschieden**,
sondern gemeldet.

WANN DIE REGEL ÜBERHAUPT ANSCHLÄGT

`Mietvertrag.save()` klemmt bereits — ein über die Oberfläche erfasster
Vertrag kann die Grenze gar nicht überschreiten. Die Regel greift dort, wo
die Klemme nicht läuft: `.update()`, `bulk_create()`, Importe,
Datenmigrationen. Nachgemessen: Ein per `.update()` gesetzter Betrag von
9'000 bleibt stehen und wird beanstandet.

Sie sperrt also nicht — das tut die Klemme, und die ist die eigentliche
Durchsetzung. Diese Regel macht die Grenze sichtbar und protokolliert ihre
Anwendung.
"""
from decimal import Decimal

from django.test import TestCase

from core.tenancy import organisation_kontext
from core.tests._isolation import MandantenFixture
from faelle.regelwerk import kaution_hoechstbetrag


class KautionHoechstbetragTest(TestCase):
    """Die Rechnung allein — ohne Datenbank, ohne Regelsatz."""

    def test_drei_monatszinse_sind_zulaessig(self):
        befund = kaution_hoechstbetrag(
            kaution=Decimal('5100'), nettomiete=Decimal('1500'),
            nebenkosten=Decimal('200'))
        self.assertTrue(befund.ok, befund.meldung)
        self.assertEqual(befund.rechnung['grenze'], '5100')

    def test_die_nebenkosten_gehoeren_zur_basis(self):
        """Der Punkt, an dem Regel und Klemme auseinanderliefen.

        Ohne Nebenkosten in der Basis wäre die Grenze 4'500 und CHF 5'000
        beanstandet — obwohl `Mietvertrag.save()` genau diesen Betrag
        speichert. Die Regel wäre strenger als die Durchsetzung.
        """
        streng = kaution_hoechstbetrag(
            kaution=Decimal('5000'), nettomiete=Decimal('1500'))
        self.assertFalse(streng.ok,
                         'Ohne Nebenkosten muss 5000 über der Grenze liegen — '
                         'sonst prüft der Vergleich unten nichts.')
        mit_nk = kaution_hoechstbetrag(
            kaution=Decimal('5000'), nettomiete=Decimal('1500'),
            nebenkosten=Decimal('200'))
        self.assertTrue(
            mit_nk.ok,
            'CHF 5000 wird beanstandet, obwohl `save()` sie speichert. Die '
            'Regel rechnet auf einer anderen Basis als die Klemme.')

    def test_ein_franken_darueber_wird_beanstandet(self):
        """Die Grenze ist eine Grenze, kein Richtwert."""
        befund = kaution_hoechstbetrag(
            kaution=Decimal('4501'), nettomiete=Decimal('1500'),
            nebenkosten=Decimal('0'))
        self.assertFalse(befund.ok)
        self.assertIn('257e', befund.meldung)
        self.assertIn('nichtig', befund.meldung,
                      'Die Meldung nennt die Folge nicht — dann klingt sie '
                      'nach Empfehlung.')

    def test_geschaeftsraeume_haben_keine_grenze(self):
        """Der Teil, der genauso wichtig ist wie die Grenze selbst.

        Sechs Monatszinse bei einem Ladenlokal sind zulässig. Eine Warnung
        hier würde die Regel entwerten.
        """
        # `gewerbe`, nicht `geschaeft`: Das Vokabular steht in
        # `portfolio.Einheit.MIETRECHT_KATEGORIE` und kennt genau drei Werte —
        # `wohnen`, `gewerbe`, `nebenobjekt`. Die erste Fassung prueste mit
        # einem Wert, den der Bestand nie liefert. Sie war gruen, weil jeder
        # unbekannte Wert in denselben Zweig faellt — also gruen, ohne den
        # wirklichen Fall zu treffen.
        befund = kaution_hoechstbetrag(
            kaution=Decimal('9000'), nettomiete=Decimal('1500'),
            kategorie='gewerbe')
        self.assertTrue(befund.ok, befund.meldung)
        self.assertIn('Wohnräume', befund.meldung)
        self.assertIs(befund.rechnung['gilt'], False)

    def test_ohne_nettomiete_keine_falsche_warnung(self):
        """Eine Rechnung ohne Grundlage darf nicht beanstanden.

        Ein Vertrag in Erfassung hat oft noch keinen Mietzins. Eine Warnung
        wäre dort nicht falsch, sondern sinnlos — und sinnlose Warnungen
        werden weggeklickt.
        """
        for wert in (None, Decimal('0')):
            with self.subTest(nettomiete=wert):
                self.assertTrue(
                    kaution_hoechstbetrag(kaution=Decimal('5000'),
                                          nettomiete=wert).ok)

    def test_die_rechnung_ist_nachvollziehbar(self):
        """Das Protokoll muss zeigen, wie der Befund zustande kam.

        `Regelanwendung.ergebnis` speichert `befund.rechnung`. Steht dort nur
        »zu hoch«, ist die Anwendung im Streitfall wertlos.
        """
        befund = kaution_hoechstbetrag(
            kaution=Decimal('6000'), nettomiete=Decimal('1500'),
            nebenkosten=Decimal('0'))
        #  behaelt die Stellen: 6000/1500 ergibt 4.00, nicht 4.0.
        self.assertEqual(befund.rechnung['monate_ist'], '4.00')
        self.assertEqual(befund.rechnung['grenze'], '4500')
        self.assertEqual(befund.rechnung['basis'], '1500',
                         'Die Basis fehlt im Protokoll — ohne sie ist im '
                         'Streitfall nicht nachvollziehbar, worauf gerechnet '
                         'wurde.')

    def test_die_grenze_kommt_aus_der_regel(self):
        """Der Parameter ist einstellbar — die Zahl steht nicht im Code.

        Eine Verwaltung kann eine strengere Hausregel führen (zwei
        Monatszinse). Das Gesetz nennt eine Obergrenze, kein Gebot.
        """
        befund = kaution_hoechstbetrag(
            kaution=Decimal('4500'), nettomiete=Decimal('1500'),
            nebenkosten=Decimal('0'), hoechst_monate=2)
        self.assertFalse(befund.ok,
                         'Der Parameter wirkt nicht — die Grenze steht fest '
                         'im Code statt in der Regel.')


class RegelwerkAnbindungTest(TestCase):
    """Die Regel muss über `pruefen()` erreichbar sein."""

    def test_die_regelart_ist_nicht_mehr_ungerechnet(self):
        """Bis hierher warf `pruefen()` einen `NotImplementedError`.

        Geprüft am Quelltext, weil der Aufruf sonst eine angelegte Regel und
        eine Organisation braucht — die Aussage ist aber einfacher: Der Zweig
        existiert.
        """
        import inspect

        from faelle import regelwerk
        quelle = inspect.getsource(regelwerk.pruefen)
        self.assertIn(
            "art == 'kaution_hoechstbetrag'", quelle,
            'Die Kautionsregel ist nicht an `pruefen()` angebunden — dann '
            'wird sie angelegt, aber nie gerechnet.')

    def test_der_grundsatz_legt_sie_an(self):
        """Sonst gäbe es die Rechnung, aber keine Regel dazu."""
        import inspect

        from faelle.management.commands import regelwerk_grundsatz
        quelle = inspect.getsource(regelwerk_grundsatz)
        self.assertIn('KAUTION_HOECHSTBETRAG', quelle)
        self.assertIn("'gilt_fuer': ['wohnen']", quelle,
                      'Der Geltungsbereich fehlt — dann warnt die Regel auch '
                      'bei Geschäftsräumen.')


class RegelUndKlemmeStimmenUebereinTest(TestCase):
    """Die Prüfung, die den Widerspruch gefunden hätte.

    Für DIESELBE Vorschrift gibt es zwei Stellen: `Mietvertrag.save()` klemmt,
    `kaution_hoechstbetrag()` beanstandet. Solange beide dieselbe Grenze
    rechnen, ergänzen sie sich. Sobald sie auseinanderlaufen, entsteht der
    schlimmste Fall — die Anwendung stellt einen Betrag her und beanstandet
    ihn im selben Atemzug.

    Genau das war der Zustand: `save()` rechnete auf Netto + Nebenkosten, die
    gelieferte Regel auf dem Nettozins allein. Bei Netto 1'500 und NK 200
    wurde CHF 6'000 auf 5'100 geklemmt und dieser Wert dann beanstandet.

    Beide lesen jetzt `Mietvertrag.kaution_obergrenze`. Dieser Test hält sie
    zusammen — auch für den Fall, dass jemand nur eine der beiden anfasst.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('K', '8000', 'Zürich')

    def test_die_grenze_ist_an_beiden_stellen_dieselbe(self):
        vertrag = self.a.vertrag
        befund = kaution_hoechstbetrag(
            kaution=vertrag.kautions_betrag,
            nettomiete=vertrag.netto_mietzins,
            nebenkosten=vertrag.nebenkosten)
        self.assertEqual(
            Decimal(befund.rechnung['grenze']), vertrag.kaution_obergrenze,
            'Die Regel rechnet eine andere Grenze als `save()` durchsetzt. '
            'Dann beanstandet sie Beträge, die die Anwendung selbst '
            'gespeichert hat — oder sie schweigt zu welchen, die die Klemme '
            'gerade gekappt hat.')

    def test_was_die_klemme_durchlaesst_wird_nicht_beanstandet(self):
        """Über die ganze Kette, mit echtem Speichern.

        Der Fall, der gemessen wurde: CHF 6'000 erfassen, `save()` klemmt auf
        die Obergrenze — und die Regel muss zu genau diesem Wert schweigen.
        """
        vertrag = self.a.vertrag
        with organisation_kontext(self.a.organisation):
            for versuch in ('4500', '5000', '5100', '6000'):
                vertrag.kautions_betrag = Decimal(versuch)
                vertrag.save()
                vertrag.refresh_from_db()
                with self.subTest(erfasst=versuch):
                    befund = kaution_hoechstbetrag(
                        kaution=vertrag.kautions_betrag,
                        nettomiete=vertrag.netto_mietzins,
                        nebenkosten=vertrag.nebenkosten)
                    self.assertTrue(
                        befund.ok,
                        f'Erfasst {versuch}, gespeichert '
                        f'{vertrag.kautions_betrag} — und trotzdem '
                        f'beanstandet: {befund.meldung}')

    def test_was_an_der_klemme_vorbeikommt_wird_beanstandet(self):
        """Und der Fall, für den die Regel überhaupt da ist.

        `.update()` ruft `save()` nicht auf — Importe, Datenmigrationen und
        Massenänderungen gehen so an der Durchsetzung vorbei. Dort ist die
        Regel das einzige, was den Betrag noch sichtbar macht.
        """
        from rentals.models import Mietvertrag

        vertrag = self.a.vertrag
        with organisation_kontext(self.a.organisation):
            Mietvertrag.objects.filter(pk=vertrag.pk).update(
                kautions_betrag=Decimal('9000'))
            vertrag.refresh_from_db()
            self.assertEqual(
                vertrag.kautions_betrag, Decimal('9000'),
                '`.update()` wird jetzt doch geklemmt — dann prüft die Zeile '
                'unten nichts mehr.')
            befund = kaution_hoechstbetrag(
                kaution=vertrag.kautions_betrag,
                nettomiete=vertrag.netto_mietzins,
                nebenkosten=vertrag.nebenkosten)
        self.assertFalse(
            befund.ok,
            'Ein an der Klemme vorbeigeschriebener Betrag von 9000 wird nicht '
            'beanstandet — dann fängt die Regel genau den Fall nicht, für den '
            'es sie gibt.')
