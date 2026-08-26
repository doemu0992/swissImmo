"""Die Indexpendenz muss den richtigen Zustelltermin nennen.

DER BEFUND

`core/services/automation.py` erzeugte eine Pendenz mit dem Text:

    »Mit amtlichem Formular (Art. 269d) ankündigen, 30 Tage vor Termin.«

Zweifach falsch:

* **dreissig statt zehn Tage** — die dreissig sind die Anfechtungsfrist des
  Mieters nach Art. 270b OR: andere Frist, andere Richtung (ab Empfang);
* **»vor Termin« statt »vor Beginn der Kündigungsfrist«** — und der liegt eine
  ganze Kündigungsfrist früher.

Wer die Pendenz befolgte, stellte bei einer dreimonatigen Frist **drei Monate
zu spät** zu. Eine verspätet zugestellte Erhöhung ist nichtig (Art. 269d
Abs. 2 OR), nicht verschoben.

Das ist der Unterschied zwischen einem ungenauen Kommentar und diesem Fall:
Der Text stand nicht im Code, sondern **in der Aufgabe, die jemand liest und
befolgt**. Er war die Anleitung zum Verlust.

WARUM DIE PENDENZ JETZT FRÜHER FÄLLIG IST

Sie war auf den Termin datiert. An dem Tag ist nichts mehr zu tun — die Frist
ist abgelaufen. Fällig ist sie, wenn zugestellt sein muss.

EINE RECHNUNG, NICHT ZWEI

Gerechnet wird mit `mietzins_zustellung()` aus dem Regelwerk (E2.36) — genau
der Rechnung, die die Regel prüft. Zwei Rechnungen für dieselbe Vorschrift
widersprechen sich früher oder später; das war Befund B3 der Analyse.
"""
import inspect
import re
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from core.services import automation


class IndexpendenzTextTest(TestCase):
    """Am Quelltext — die Pendenz entsteht nur bei gestiegenem LIK."""

    def _quelle(self):
        return inspect.getsource(automation)

    def test_die_dreissig_tage_sind_weg(self):
        quelle = self._quelle()
        ohne_kommentar = re.sub(r'^\s*#.*$', '', quelle, flags=re.M)
        self.assertNotIn(
            '30 Tage vor Termin', ohne_kommentar,
            'Der alte Aufgabentext ist zurück. Er nennt die Anfechtungsfrist '
            'des Mieters statt der Zustellfrist und misst sie ab dem falschen '
            'Tag — wer ihm folgt, stellt zu spät zu.')

    def test_der_zustelltermin_wird_gerechnet(self):
        quelle = self._quelle()
        self.assertIn(
            'mietzins_zustellung', quelle,
            'Die Indexpendenz rechnet den Zustelltermin nicht mehr mit der '
            'Regel — dann gibt es zwei Rechnungen für Art. 269d.')

    def test_die_pendenz_ist_zur_zustellung_faellig(self):
        """Nicht zum Termin — dann wäre sie eine Nachricht, keine Aufgabe."""
        quelle = self._quelle()
        self.assertIn(
            'max(zustellung, heute)', quelle,
            'Die Pendenz ist wieder auf den Termin datiert. An dem Tag ist '
            'nichts mehr zu tun.')

    def test_keine_sonderbehandlung_fuer_nebenobjekte(self):
        """Die Kurzfrist-Verzweigung ist entfallen — und das ist die Antwort
        auf eine Rechtsfrage, nicht eine Vereinfachung.

        Sie fragte: Wie rechnet man die 269d-Frist bei einem Einstellplatz mit
        Zwei-Wochen-Kuendigungsfrist? Die Frage davor war offen und wichtiger:
        Faellt eine Mietzinserhoehung beim GESONDERT VERMIETETEN Einstellplatz
        ueberhaupt unter Art. 269d?

        Art. 269d steht im «Zweiten Abschnitt: Schutz vor missbraeuchlichen
        Mietzinsen ... bei der Miete von WOHN- UND GESCHAEFTSRAEUMEN». Ein
        allein vermieteter Parkplatz ist keines von beidem. Der Bestand zieht
        dieselbe Linie schon bei der Kuendigung.

        WARUM TROTZDEM DIE LANGE FRIST GERECHNET WIRD: Die Folgen sind
        unsymmetrisch. Das Formular zu verwenden, wo es nicht noetig ist,
        kostet ein Blatt Papier. Es wegzulassen, wo es noetig ist, macht die
        Erhoehung NICHTIG. Bei einer Rechtsfrage ohne Bundesgerichtsentscheid
        vermeidet man den teureren Irrtum.
        """
        quelle = self._quelle()
        self.assertNotIn(
            'kurzfrist', quelle,
            'Die Kurzfrist-Verzweigung ist zurueck. Sie beantwortet eine '
            'Frage, die vor ihr geklaert werden muesste — und sie meldet '
            'einen Zustelltermin 24 Tage vor dem Termin, wo drei Monate '
            'noetig waeren.')
        self.assertIn(
            'monate_roh if monate_roh > 0 else 3', quelle,
            'Fehlt die Kuendigungsfrist, muss die gesetzliche Mindestfrist '
            'fuer Wohnraeume gelten — die vorsichtigere Seite. `or 3` reicht '
            'dafuer nicht: Es laesst negative Werte durch.')

    def test_die_regel_liefert_den_erwarteten_tag(self):
        from faelle.regelwerk import mietzins_zustellung

        befund = mietzins_zustellung(termin=date(2027, 3, 31), frist_monate=3)
        self.assertEqual(befund.vorschlag, date(2026, 12, 21))

    def test_und_nicht_dreissig_tage_vor_dem_termin(self):
        """Die Gegenprobe zum Befund.

        Der alte Text hätte auf den 01.03.2027 geführt — mehr als ein
        Vierteljahr zu spät.
        """
        from faelle.regelwerk import mietzins_zustellung

        befund = mietzins_zustellung(termin=date(2027, 3, 31), frist_monate=3)
        self.assertNotEqual(befund.vorschlag, date(2027, 3, 1))
        self.assertLess(befund.vorschlag, date(2027, 1, 1),
                        'Die Zustellung liegt im selben Quartal wie der '
                        'Termin — dann wurde nicht ab Beginn der '
                        'Kündigungsfrist gerechnet.')


class IndexpendenzWirdErzeugtTest(TestCase):
    """Die Pendenz wird ERZEUGT und gelesen — nicht der Quelltext.

    WARUM DIESE KLASSE NÖTIG WAR

    Die Prüfungen oben suchen Zeichenketten im Quelltext. Sie halten fest,
    dass der alte Satz weg ist — aber sie sehen nicht, was in der Pendenz
    steht, die jemand am Morgen liest. Zwei Fehler in der ersten Fassung
    dieser Etappe blieben deshalb grün:

    * Im Kurzfristfall stand »zehn Tage vor Beginn der **3-monatigen**
      Kündigungsfrist«, während das Datum aus zwei Wochen gerechnet war.
      Datum und Begründung widersprachen sich in einem Satz.
    * `kurzfrist` prüfte nur `kuendigungsfrist_monate <= 0`, nicht
      `ist_einstellplatz`. Eine Wohnung mit fehlender Frist hätte einen
      Zustelltermin 24 Tage vor dem Termin bekommen statt gut drei Monate —
      also genau den Fehler, den diese Etappe behebt.

    Ein Test, der den Quelltext liest, kann so etwas nicht finden.
    """

    def _vertrag(self, typ='whg', frist_monate=3):
        from ._helfer import _basis_objekte

        lg, e, m, v = _basis_objekte()
        e.typ = typ
        e.save()
        v.mietzins_modell = 'index'
        v.basis_lik_punkte = Decimal('100.0')     # aktueller Stand liegt darüber
        v.index_intervall_monate = 12
        # Der naechste Anpassungstermin muss in der ZUKUNFT liegen: Bei einem
        # vergangenen Termin klemmt `max(zustellung, heute)` die Faelligkeit
        # richtigerweise auf heute, und der Test unten pruefte dann die
        # Klemme statt die Rechnung.
        v.index_letzte_anpassung = date.today() - timedelta(days=200)
        v.kuendigungsfrist_monate = frist_monate
        v.save()
        return v

    def _pendenz(self, vertrag):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen

        generate_auto_pendenzen(horizont_tage=365)
        return Pendenz.objects.filter(
            quelle__startswith=f'auto:index:{vertrag.id}:').first()

    def test_der_alte_satz_steht_in_keiner_pendenz(self):
        pendenz = self._pendenz(self._vertrag())
        self.assertIsNotNone(pendenz, 'Es entsteht gar keine Indexpendenz — '
                                      'dann prüft der Rest hier nichts.')
        self.assertNotIn('30 Tage vor Termin', pendenz.beschreibung)

    def test_datum_und_begruendung_stimmen_ueberein(self):
        """Der Fehler, der die Quelltextprüfungen nicht erreichte.

        Im Text steht ein Datum und daneben, aus welcher Frist es kommt.
        Beides muss zusammenpassen — sonst rechnet jemand nach, findet den
        Widerspruch und glaubt der Pendenz danach nichts mehr.
        """
        from faelle.regelwerk import mietzins_zustellung

        pendenz = self._pendenz(self._vertrag(frist_monate=3))
        treffer = re.search(r'muss bis (\d{2}\.\d{2}\.\d{4}) beim Mieter sein '
                            r'— zehn Tage vor Beginn der ([\w-]+) '
                            r'Kündigungsfrist', pendenz.beschreibung)
        self.assertIsNotNone(treffer, pendenz.beschreibung)
        self.assertEqual(treffer.group(2), '3-monatigen')

        termin = re.search(r'möglich auf (\d{2}\.\d{2}\.\d{4})',
                           pendenz.beschreibung)
        termin_datum = date(*reversed([int(t) for t in
                                       termin.group(1).split('.')]))
        erwartet = mietzins_zustellung(termin=termin_datum,
                                       frist_monate=3).vorschlag
        self.assertEqual(treffer.group(1), erwartet.strftime('%d.%m.%Y'))

    def test_eine_wohnung_ohne_frist_faellt_nicht_auf_zwei_wochen(self):
        """`kuendigungsfrist_monate = 0` auf einer Wohnung ist eine Datenlücke.

        Der Bestand liest `<= 0` nur beim Einstellplatz als Zwei-Wochen-Frist
        (`Mietvertrag.kuendigungsfrist_anzeige`). Griffe die Kurzfrist auch
        hier, läge der Zustelltermin 24 Tage vor dem Termin statt gut drei
        Monate — zu spät, und die Erhöhung wäre nichtig.
        """
        pendenz = self._pendenz(self._vertrag(typ='whg', frist_monate=0))
        self.assertIn('3-monatigen', pendenz.beschreibung)
        self.assertNotIn('2-wöchigen', pendenz.beschreibung)

    def test_die_pendenz_ist_vor_dem_termin_faellig(self):
        """Nicht am Termin — an dem Tag ist die Frist abgelaufen."""
        pendenz = self._pendenz(self._vertrag(frist_monate=3))
        termin = re.search(r'möglich auf (\d{2}\.\d{2}\.\d{4})',
                           pendenz.beschreibung)
        termin_datum = date(*reversed([int(t) for t in
                                       termin.group(1).split('.')]))
        self.assertLess(
            pendenz.faellig_am, termin_datum,
            'Die Pendenz ist erst am Kündigungstermin fällig — dann ist sie '
            'eine Nachricht und keine Aufgabe.')


    def test_eine_negative_frist_kippt_die_zustellung_nicht_hinter_den_termin(self):
        """Ein `IntegerField` ohne Untergrenze nimmt auch -1 an.

        `or 3` reicht den Wert durch, und `mietzins_zustellung()` rechnet
        dann vorwärts: Zustellung am 20.04.2027 für einen Termin am
        31.03.2027. Die Pendenz nennte damit einen Tag, an dem die Frist
        längst abgelaufen ist — derselbe Fehler wie der alte Text, nur
        anders erzeugt.
        """
        pendenz = self._pendenz(self._vertrag(frist_monate=-1))
        termin = re.search(r'möglich auf (\d{2}\.\d{2}\.\d{4})',
                           pendenz.beschreibung)
        termin_datum = date(*reversed([int(t) for t in
                                       termin.group(1).split('.')]))
        zustell = re.search(r'muss bis (\d{2}\.\d{2}\.\d{4})',
                            pendenz.beschreibung)
        zustell_datum = date(*reversed([int(t) for t in
                                        zustell.group(1).split('.')]))
        self.assertLess(zustell_datum, termin_datum)
        self.assertIn('3-monatigen', pendenz.beschreibung)
