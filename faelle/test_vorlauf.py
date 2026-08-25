"""Ein blockierter Jahreslauf muss früher warnen als ein Monatslauf.

DER BEFUND

Der Arbeitsvorrat blickte 14 Tage voraus — für jeden Lauf gleich. Bei einem
Monatslauf ist das reichlich: Wer zwei Wochen vor der Sollstellung erfährt,
dass etwas fehlt, hat Zeit.

Bei der **Nebenkostenabrechnung** — jährlich — ist es zu spät. Eine fehlende
Verbrauchsablesung zwei Wochen vor Stichtag heisst: Ablesedienst anschreiben,
warten, mahnen, und dann ist die Abrechnung verspätet. Wer denselben Befund
drei Monate früher bekommt, holt ihn nach.

Das ist G7 in seiner eigentlichen Bedeutung: »Eine Fristenliste warnt nicht.«
Eine Warnung, die zu spät kommt, ist eine Liste.

DIE UNTERSCHEIDUNG, AUF DIE ES ANKOMMT

Ein Lauf **ohne** Blockade wird zum Stichtag hin sichtbar — das ist der
normale Rhythmus der Arbeit, und ein Jahreslauf, der 90 Tage vorher im
Tagesvorrat steht, ist genau der zweite Posteingang, vor dem Abschnitt 1 des
Konzepts warnt.

Ein **blockierter** Lauf ist etwas anderes: Dort fehlt etwas, das von aussen
kommen muss, und die Zeit dafür läuft ab sofort. Nur er erscheint früher.

WAS DIE ZAHLEN SIND

Erfahrungswerte, keine Rechnung: Der Vorlauf soll reichen, damit eine
Rückfrage an einen Dritten noch beantwortet werden kann. Bei Quartals- und
Jahresläufen hängt daran regelmässig ein Externer (Ablesedienst, Treuhand,
ESTV).
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.arbeitsvorrat import VORLAUF_JE_RHYTHMUS, _laeufe
from faelle.lauf_models import Blockade, Lauf, Laufart


class VorlaufJeRhythmusTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _lauf(self, rhythmus, tage_bis_faellig, blockiert):
        """Ein Lauf mit Rhythmus, Faelligkeit und wahlweise Blockade.

        Feldnamen aus `faelle/test_laeufe.py` uebernommen — `faellig_am_tag`,
        nicht `stichtag_im_monat`. Ein erster Entwurf hat den Namen geraten.
        """
        org = self.a.organisation
        art = Laufart.objects.create(
            organisation=org, schluessel=f'p-{rhythmus}-{tage_bis_faellig}',
            bezeichnung=f'Pruefung {rhythmus} {tage_bis_faellig}',
            rhythmus=rhythmus, faellig_am_tag=1)
        lauf = Lauf.objects.create(
            organisation=org, laufart=art, periode='2026-08',
            faellig_am=timezone.localdate() + timedelta(days=tage_bis_faellig))
        if blockiert:
            Blockade.objects.create(
                organisation=org, lauf=lauf,
                grund='Verbrauchsablesung Techem fehlt')
        return lauf

    def _sichtbar(self, lauf, fenster=14):
        """Ruft `_laeufe()` im Mandantenkontext.

        `Lauf.objects` ist mandantengefiltert und braucht einen gesetzten
        Kontext — den setzt sonst die Anfrage. Ausserhalb davon scheitert die
        Abfrage, statt still eine leere Liste zu liefern; das ist die
        richtige Richtung, kostet hier aber diese Zeile.
        """
        heute = timezone.localdate()
        with mandant(self.a.organisation):
            zeilen = _laeufe(heute, heute + timedelta(days=fenster))
        return any(lauf.laufart.bezeichnung in z['titel'] for z in zeilen)

    def test_blockierter_jahreslauf_warnt_drei_monate_vorher(self):
        """Der Fall, der den Befund ausgelöst hat."""
        lauf = self._lauf('jaehrlich', 60, blockiert=True)
        self.assertTrue(
            self._sichtbar(lauf),
            'Eine fehlende Ablesung 60 Tage vor der Nebenkostenabrechnung '
            'erreicht den Arbeitsvorrat nicht — dann erfährt es niemand, '
            'solange es noch zu ändern ist.')

    def test_blockierter_monatslauf_nicht_drei_monate_vorher(self):
        """Die Gegenrichtung: Der Vorlauf gilt je Rhythmus, nicht pauschal.

        Wäre er für alle 90 Tage, stünde jede Sollstellung ein Vierteljahr
        im Voraus im Tagesvorrat — der zweite Posteingang, den Abschnitt 1
        des Konzepts beschreibt.
        """
        lauf = self._lauf('monatlich', 60, blockiert=True)
        self.assertFalse(
            self._sichtbar(lauf),
            'Ein blockierter Monatslauf steht 60 Tage im Voraus im '
            'Arbeitsvorrat — das ist zu früh, um zu handeln, und verstopft '
            'die Liste.')

    def test_unblockierter_lauf_erscheint_nicht_frueher(self):
        """Nur die Blockade zieht den Lauf vor, nicht der Rhythmus allein."""
        lauf = self._lauf('jaehrlich', 60, blockiert=False)
        self.assertFalse(
            self._sichtbar(lauf),
            'Ein Jahreslauf ohne Blockade steht 60 Tage vorher im '
            'Arbeitsvorrat. Er wird zum Stichtag hin sichtbar — vorher gibt '
            'es nichts zu tun.')

    def test_im_normalen_fenster_gilt_weiterhin_alles(self):
        """Die Erweiterung darf das Bestehende nicht verengen."""
        lauf = self._lauf('jaehrlich', 5, blockiert=False)
        self.assertTrue(
            self._sichtbar(lauf),
            'Ein Lauf, der in fünf Tagen fällig ist, fehlt im Arbeitsvorrat.')

    def test_die_werte_decken_alle_rhythmen_ab(self):
        """Sonst fiele ein Rhythmus stillschweigend auf den Vorgabewert.

        `VORLAUF_JE_RHYTHMUS.get(..., 14)` fängt einen unbekannten Rhythmus
        ab — richtig als Absicherung, falsch als Zustand: Ein neuer Rhythmus
        bekäme den Monatswert, ohne dass es auffällt.
        """
        from faelle.lauf_models import Laufart

        bekannt = {wert for wert, _ in Laufart.RHYTHMEN}
        fehlend = bekannt - set(VORLAUF_JE_RHYTHMUS)
        self.assertEqual(
            fehlend, set(),
            f'Für diese Rhythmen ist kein Vorlauf hinterlegt: {fehlend}. '
            f'Sie bekämen den Monatswert (14 Tage), ohne dass jemand das '
            f'entschieden hat.')

    def test_die_blockaden_kosten_keine_abfrage_je_lauf(self):
        """Der Preis des weiteren Fensters — gemessen, nicht geschaetzt.

        Der Vorlauf hat die Kandidatenmenge von 20 auf 60 vergroessert, und
        die Blockade wird jetzt fuer JEDEN Kandidaten gebraucht — auch fuer
        die, die gleich wieder wegfallen.

        Ohne Prefetch gemessen: **61 Abfragen, um NULL Zeilen anzuzeigen**.
        Sechzig blockierte Monatslaeufe ausserhalb ihres Vorlaufs, jeder
        einzeln nach seinen Blockaden gefragt, alle verworfen. Vor der
        Etappe waren es hoechstens 21.

        Die Zahl haengt nicht an der Anzahl Laeufe: Zwei Abfragen holen die
        Kandidaten und ihre offenen Blockaden, mehr braucht es nicht.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        heute = timezone.localdate()
        for i in range(30):
            self._lauf('monatlich', 20 + i, blockiert=True)

        with mandant(self.a.organisation):
            with CaptureQueriesContext(connection) as ctx:
                _laeufe(heute, heute + timedelta(days=14))

        self.assertLessEqual(
            len(ctx), 4,
            f'{len(ctx)} Abfragen fuer den Laufteil des Arbeitsvorrats. Die '
            'Blockaden werden je Lauf einzeln geholt statt im Voraus — bei '
            '60 Kandidaten sind das 60 Abfragen, oft fuer Zeilen, die gar '
            'nicht angezeigt werden.\n\n`offene_blockaden` filtert selbst '
            'und geht damit an jedem Prefetch vorbei; es braucht einen '
            'gefilterten `Prefetch(..., to_attr=...)`.')

    def test_die_gegenprobe(self):
        """Der Vorlauf muss sich je Rhythmus wirklich unterscheiden.

        Wären alle Werte gleich, wären die Prüfungen oben teilweise grün,
        ohne etwas zu belegen.
        """
        self.assertGreater(VORLAUF_JE_RHYTHMUS['jaehrlich'],
                           VORLAUF_JE_RHYTHMUS['monatlich'])
        self.assertGreater(VORLAUF_JE_RHYTHMUS['quartalsweise'],
                           VORLAUF_JE_RHYTHMUS['monatlich'])
