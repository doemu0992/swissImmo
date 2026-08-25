"""Zwei Schwellen, die entscheiden — und bisher niemand gemessen hat.

WORUM ES GEHT

An zwei Stellen entscheidet eine fest verdrahtete Zahl über den Ablauf:

  `core/views/fw/schaeden.py`    CHF 1'000  ab hier braucht ein
                                            Handwerkerauftrag die Freigabe
                                            des Eigentümers
  `core/views/fw/nebenkosten.py` 10 % oder  ab hier wird eine Anpassung des
                                 CHF 10     Akontobetrags empfohlen

Beide sind fachlich vertretbar. Beide hatten **keinen einzigen Test** — sie
standen als Zahl im Code, und niemand hätte gemerkt, wenn jemand eine Null
anhängt oder das `>=` zu einem `>` macht.

WARUM DAS MEHR IST ALS EINE ZAHL

Die Freigabeschwelle steuert, wann ein Eigentümer eine E-Mail bekommt und die
Reparatur wartet. Zu tief: Jede Dichtung braucht eine Unterschrift. Zu hoch:
Der Verwalter gibt Beträge frei, für die er nicht zuständig ist. In beiden
Fällen merkt es niemand aus dem Code heraus, sondern erst der Kunde.

WARUM HIER CODE AUSGEFÜHRT UND NICHT QUELLTEXT GELESEN WIRD

Die erste Fassung dieser Datei las beide Stellen mit `inspect.getsource()` und
suchte die Zahlen mit einem regulären Ausdruck. Das ist verführerisch einfach
und fängt tatsächlich den Zahlendreher — aber es hält nur die **Schreibweise**
fest, nicht das Verhalten.

Nachgemessen, nicht vermutet: Wird in `schaeden.py` aus
`kosten_geschaetzt >= SCHWELLE` ein `>`, und in `nebenkosten.py` aus
`abs(diff) >= schwelle` ein `>`, dann bleiben beide Zuweisungen Zeichen für
Zeichen gleich — und beide Prüfungen blieben **grün**. Genau diesen Fehler
nennt die Etappe als Beispiel für das, was sie verhindern soll.

Eine gekippte Vergleichsrichtung ist auch kein erfundener Fehler: Sie ist die
naheliegendste Verschlimmbesserung an einer Schwelle («ab CHF 1'000» gegen
«über CHF 1'000»), sie sieht im Änderungstext harmlos aus, und sie ändert das
Verhalten für genau den Betrag, der am häufigsten vorkommt — den runden.

Deshalb prüfen beide Klassen jetzt **am Rand**: genau auf der Schwelle, und
einen Rappen darunter. Für die Nebenkosten war dafür ein Eingriff nötig — die
Rechnung stand mitten in einer Schleife über die fertige Abrechnung und war
nur über die ganze Kette erreichbar. Sie ist jetzt `akonto_empfehlung()`,
eine reine Funktion ohne Datenbank.

WAS DIESE TESTS NICHT LEISTEN

Sie sagen nicht, dass CHF 1'000 richtig sind — das ist eine fachliche
Entscheidung, die niemand getroffen hat, soweit die Unterlagen reichen. Sie
halten fest, was heute gilt, und machen eine Änderung sichtbar. Wer die Zahl
bewusst ändert, ändert auch diesen Test; wer sie versehentlich ändert, wird
rot.

DER WEG NACH VORN, FALLS ER GEGANGEN WIRD

Beide Schwellen gehören fachlich zur Verwaltung, nicht zum Programm: Eine
Verwaltung mit fünfzig Liegenschaften hat eine andere Freigabegrenze als eine
mit fünfhundert. Das Muster dafür existiert bereits — `crm.Mandant.mahn_konfig`
ist ein JSON-Feld, in dem die Mahnstufen je Mandant stehen.

Der Weg wäre: ein Feld `schwellen` am Mandanten, Vorgabewerte wie hier, und
die zwei Stellen im Code lesen daraus statt aus einer Konstanten. Das ist eine
Migration und ein Formular, also eine eigene Etappe — nicht etwas, das
nebenbei entsteht.

Bis dahin ist diese Datei der Ort, an dem die Zahlen stehen und ihre Änderung
auffällt.
"""
from decimal import Decimal

from django.test import Client, TestCase

from core.tenancy import organisation_kontext
from core.views.fw.nebenkosten import (AKONTO_ANTEIL, AKONTO_UNTERGRENZE,
                                       akonto_empfehlung)

from ._isolation import MandantenFixture

#: Was heute gilt. Wer sie ändert, ändert eine fachliche Entscheidung — und
#: soll das hier tun müssen, damit es im Änderungstext auftaucht.
FREIGABE_SCHWELLE = Decimal('1000')


class FreigabeschwelleTest(TestCase):
    """CHF 1'000 — ab hier braucht eine Reparatur die Freigabe.

    Geprüft wird über die View, die es entscheidet: `fw_auftrag_kosten`
    setzt beim Erfassen der geschätzten Kosten `freigabe_status` auf
    «ausstehend» und schickt dem Eigentümer eine E-Mail.
    """

    @classmethod
    def setUpTestData(cls):
        from crm.models import Handwerker
        from tickets.models import HandwerkerAuftrag

        cls.a = MandantenFixture('S', '8000', 'Zürich')
        with organisation_kontext(cls.a.organisation):
            cls.handwerker = Handwerker.objects.create(
                firma='Sanitär Muster AG', branche='sanitaer')
            cls.auftrag = HandwerkerAuftrag.objects.create(
                ticket=cls.a.schaden, handwerker=cls.handwerker,
                bemerkung='Dichtung ersetzen')

    def _erfassen(self, betrag):
        """Kosten erfassen und den Freigabestatus zurückgeben.

        Der Auftrag wird vorher zurückgesetzt: Die View schaltet nur aus
        «nicht_noetig»/«abgelehnt» heraus, ein einmal gesetztes «ausstehend»
        bliebe sonst über den nächsten Aufruf stehen und der zweite Fall
        prüfte nichts mehr.
        """
        from tickets.models import HandwerkerAuftrag

        with organisation_kontext(self.a.organisation):
            HandwerkerAuftrag.objects.filter(id=self.auftrag.id).update(
                freigabe_status='nicht_noetig', freigabe_datum=None)

        c = Client()
        c.force_login(self.a.benutzer)
        antwort = c.post(f'/neu/auftrag/{self.auftrag.id}/kosten/',
                         {'kosten_geschaetzt': str(betrag)})
        self.assertEqual(antwort.status_code, 302,
                         'Die View nimmt die Kosten nicht entgegen.')
        with organisation_kontext(self.a.organisation):
            return HandwerkerAuftrag.objects.get(id=self.auftrag.id).freigabe_status

    def test_genau_auf_der_schwelle_wird_freigabe_verlangt(self):
        """Der Fall, den ein `>` statt `>=` still kippen würde.

        CHF 1'000 ist der Betrag, der an einer solchen Grenze am häufigsten
        vorkommt — Schwellen werden rund gewählt, Offerten auch. Wer hier
        das Gleichheitszeichen verliert, verschiebt die Grenze genau für den
        wahrscheinlichsten Betrag, und keine Zahl im Code ändert sich dabei.
        """
        self.assertEqual(
            self._erfassen(FREIGABE_SCHWELLE), 'ausstehend',
            f'Bei genau CHF {FREIGABE_SCHWELLE} wird KEINE Freigabe verlangt. '
            'Entweder ist die Schwelle gestiegen, oder aus dem `>=` ist ein '
            '`>` geworden — dann gibt der Verwalter den runden Betrag jetzt '
            'allein frei.')

    def test_knapp_darunter_wird_keine_freigabe_verlangt(self):
        """Die Gegenrichtung — ohne sie prüfte der Test oben nur «immer».

        Ein View, der bei jedem Betrag Freigabe verlangt, bestünde die
        Prüfung darüber. Erst dieser Fall macht sie zu einer Aussage über
        eine Grenze.
        """
        self.assertEqual(
            self._erfassen(FREIGABE_SCHWELLE - Decimal('0.01')), 'nicht_noetig',
            f'Schon bei CHF {FREIGABE_SCHWELLE - Decimal("0.01")} wird '
            'Freigabe verlangt — dann ist die Schwelle gefallen und jede '
            'Kleinreparatur wartet auf eine Unterschrift.')

    def test_die_schwelle_ist_plausibel(self):
        """Gegen den Zahlendreher, nicht gegen die Entscheidung.

        Eine Null zuviel oder zuwenig ist der wahrscheinlichste Fehler an
        einer solchen Zahl. Diese Spanne fängt ihn, ohne die fachliche
        Entscheidung vorwegzunehmen.
        """
        self.assertGreaterEqual(
            FREIGABE_SCHWELLE, Decimal('100'),
            'Unter CHF 100 wäre praktisch jeder Auftrag freigabepflichtig.')
        self.assertLessEqual(
            FREIGABE_SCHWELLE, Decimal('10000'),
            'Über CHF 10\'000 entscheidet der Verwalter allein über Beträge, '
            'die den Eigentümer sicher interessieren.')


class AkontoempfehlungTest(TestCase):
    """10 % oder CHF 10 — ab hier wird eine Anpassung empfohlen.

    `akonto_empfehlung()` ist eine reine Rechnung ohne Datenbank; geprüft
    wird sie deshalb direkt, mit Werten am Rand.
    """

    def test_genau_auf_der_schwelle_wird_empfohlen(self):
        """Akonto 100, Bedarf 110 — die Abweichung IST die Schwelle.

        Bei einem Akonto von CHF 100 sind 10 % genau CHF 10, also gleich der
        Untergrenze; beide Teile der `max()` liefern denselben Wert. Der
        Bedarf von CHF 110 liegt exakt CHF 10 darüber. Das ist der Fall, den
        ein `>` statt `>=` still verschluckt.
        """
        empfohlen, diff, schwelle, empfehlen = akonto_empfehlung(
            Decimal('110'), Decimal('100'))
        self.assertEqual(schwelle, Decimal('10'))
        self.assertEqual(abs(diff), schwelle,
                         'Der Fall trifft die Schwelle nicht mehr genau — '
                         'dann prüft dieser Test den Rand nicht.')
        self.assertTrue(
            empfehlen,
            'Genau auf der Schwelle wird nichts empfohlen. Aus dem `>=` ist '
            'ein `>` geworden.')
        self.assertEqual(empfohlen, Decimal('110'))

    def test_knapp_darunter_wird_nicht_empfohlen(self):
        """Akonto 100, Bedarf 109 — rundet auf 110, aber knapp gerechnet.

        Der Rundungsschritt auf CHF 5 macht daraus ebenfalls 110; die
        Abweichung ist damit wieder 10. Um wirklich UNTER der Schwelle zu
        liegen, braucht es einen Bedarf, der auf 105 rundet.
        """
        empfohlen, diff, schwelle, empfehlen = akonto_empfehlung(
            Decimal('105'), Decimal('100'))
        self.assertEqual(empfohlen, Decimal('105'))
        self.assertLess(abs(diff), schwelle)
        self.assertFalse(
            empfehlen,
            'Unter der Schwelle wird trotzdem empfohlen — dann meldet die '
            'Abrechnung jede Schwankung.')

    def test_die_untergrenze_greift_bei_kleinen_betraegen(self):
        """Warum es zwei Zahlen braucht, nicht eine — erste Hälfte.

        Bei einem Akonto von CHF 30 sind 10 % gerade CHF 3. Ohne die
        Untergrenze bekäme der Mieter eine Empfehlung, seinen Akonto um drei
        Franken zu ändern.
        """
        _e, _d, schwelle, _v = akonto_empfehlung(Decimal('35'), Decimal('30'))
        self.assertEqual(schwelle, AKONTO_UNTERGRENZE,
                         'Bei kleinen Beträgen muss die Untergrenze gewinnen.')

    def test_der_anteil_greift_bei_grossen_betraegen(self):
        """Zweite Hälfte: Ohne Anteil skaliert die Schwelle nicht mit.

        Bei einem Akonto von CHF 600 wären CHF 10 Abweichung 1,7 % — jede
        normale Schwankung würde gemeldet.
        """
        _e, _d, schwelle, _v = akonto_empfehlung(Decimal('650'), Decimal('600'))
        self.assertEqual(schwelle, Decimal('600') * AKONTO_ANTEIL)
        self.assertGreater(schwelle, AKONTO_UNTERGRENZE)

    def test_kein_vorschlag_auf_null(self):
        """`empfohlen > 0` — ohne diese Bedingung schlägt die Abrechnung vor,
        den Akonto auf null zu setzen, sobald keine Kosten angefallen sind.
        """
        _e, _d, _s, empfehlen = akonto_empfehlung(Decimal('0'), Decimal('200'))
        self.assertFalse(empfehlen)

    def test_die_schwellen_sind_unveraendert(self):
        """Die Zahlen selbst — damit eine Änderung im Änderungstext auftaucht."""
        self.assertEqual(AKONTO_UNTERGRENZE, Decimal('10'),
                         'Die absolute Untergrenze hat sich geändert.')
        self.assertEqual(AKONTO_ANTEIL, Decimal('0.10'),
                         'Der prozentuale Anteil hat sich geändert.')
        self.assertGreater(AKONTO_ANTEIL, Decimal('0'),
                           'Ohne Anteil skaliert die Schwelle nicht mit.')
        self.assertLess(AKONTO_ANTEIL, Decimal('1'),
                        'Ein Anteil über 100 % würde nie greifen.')
