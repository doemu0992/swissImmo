"""Ein Auditbericht muss sagen, wenn er unvollständig ist.

DER BEFUND

`/neu/logbuch/?export=pdf` erzeugt einen Bericht, der sich im Kopf selbst als
»unveränderlicher Revisions-Trail« bezeichnet. Er nahm aber nur die ersten
2'000 Einträge — **stillschweigend**.

Wer diesen Bericht einer Revision vorlegt, legt bei mehr als 2'000 Einträgen
einen Ausschnitt vor und weiss es nicht. Der Bericht behauptet dabei
ausdrücklich das Gegenteil.

Die Obergrenze selbst ist richtig: Ein PDF mit 200'000 Zeilen hilft niemandem,
und der Aufbau würde den Server minutenlang beschäftigen. Falsch war nur, sie
zu verschweigen.

WAS JETZT GILT

Bis zur Grenze: »n Einträge · unveränderlicher Revisions-Trail«.
Darüber: »n von m Einträgen · AUSSCHNITT, nach Zeitpunkt absteigend · für den
vollständigen Trail bitte den Zeitraum eingrenzen«.

Der Hinweis nennt auch den Ausweg — das Logbuch lässt sich nach Zeitraum
filtern, und die Filter gelten für den Bericht mit.
"""
import re

from django.test import Client, TestCase

from core.services.logbuch_pdf import _kopfzeile


class KopfzeileTest(TestCase):

    def test_vollstaendiger_bericht_nennt_sich_revisions_trail(self):
        zeile = _kopfzeile(120, 120)
        self.assertIn('120', zeile)
        self.assertIn('Revisions-Trail', zeile)
        self.assertNotIn('AUSSCHNITT', zeile,
                         'Ein vollständiger Bericht darf sich nicht als '
                         'Ausschnitt bezeichnen.')

    def test_abgeschnittener_bericht_sagt_es(self):
        zeile = _kopfzeile(2000, 7431)
        self.assertIn('AUSSCHNITT', zeile,
                      'Der Bericht verschweigt, dass er unvollständig ist — '
                      'genau das war der Befund.')
        self.assertIn('2000', zeile)
        self.assertIn('7431', zeile,
                      'Die Gesamtzahl fehlt. Ohne sie weiss der Leser nicht, '
                      'wie viel ihm fehlt.')
        self.assertNotIn('unveraenderlicher Revisions-Trail', zeile,
                         'Ein Ausschnitt ist kein vollständiger Trail.')

    def test_ohne_angabe_bleibt_es_beim_alten(self):
        """Aufrufe ohne `gesamt` dürfen nicht plötzlich anders aussehen.

        Die PDF-Funktion wird auch anderswo benutzt; ein zusätzliches Argument
        darf dort nichts ändern.
        """
        zeile = _kopfzeile(50, None)
        self.assertIn('Revisions-Trail', zeile)
        self.assertNotIn('AUSSCHNITT', zeile)

    def test_die_gegenprobe(self):
        """Beide Fälle müssen sich unterscheiden.

        Gäbe `_kopfzeile` immer dasselbe zurück, wären die Prüfungen oben
        teilweise grün, ohne etwas zu belegen.
        """
        self.assertNotEqual(
            _kopfzeile(2000, 2000), _kopfzeile(2000, 7431),
            'Vollständiger Bericht und Ausschnitt tragen dieselbe Kopfzeile.')


class CsvVollstaendigTest(TestCase):
    """Die zweite stille Grenze — die, die bei der Gegensuche durchfiel.

    E2.28 hat das PDF ehrlich gemacht und gemeldet, es sei gegengesucht
    worden: «keine weitere stille Obergrenze in Berichten». Vier Zeilen über
    der behobenen Stelle stand `qs[:10000]` — im CSV-Export, der sich im
    Kommentar «revisionssicher für die Ablage» nennt.

    Der ist der gefährlichere von beiden: Ein CSV wandert ins Archiv und hat
    keinen Kopf, in dem ein Hinweis stehen könnte. Und die Begründung für die
    Grenze im PDF — Seitenzahl, Aufbauzeit — gilt für ihn nicht.

    Deshalb keine Ansage, sondern keine Grenze: Der Export streamt und liest
    die Einträge einzeln nach.
    """

    def _quelle(self):
        import inspect

        from core.views.fw import profil
        quelle = inspect.getsource(profil)
        # Erklärtext nennt die alte Grenze — geprüft wird der Code.
        return re.sub(r'^\s*#.*$', '', quelle, flags=re.M)

    def test_der_csv_export_hat_keine_obergrenze_mehr(self):
        self.assertNotIn(
            'qs[:10000]', self._quelle(),
            'Der CSV-Export kürzt wieder still. Ein Bericht «für die Ablage» '
            'darf nicht beim 10 000. Eintrag aufhören, ohne es zu sagen — und '
            'ein CSV hat keinen Kopf, in dem der Hinweis stehen könnte.')

    def test_der_csv_export_streamt(self):
        """Ohne Streaming waere das Entfernen der Grenze ein Tausch.

        Eine unbegrenzte Liste im Speicher aufzubauen verlagert das Problem
        nur: aus «zu wenig Daten» wird «zu viel Speicher». `iterator()` haelt
        den Bedarf konstant.
        """
        quelle = self._quelle()
        self.assertIn('StreamingHttpResponse', quelle,
                      'Der Export baut die ganze Antwort im Speicher auf.')
        self.assertIn('.iterator(', quelle,
                      'Die Einträge werden auf einmal geladen statt einzeln '
                      'nachgelesen.')

    def test_der_export_liefert_alle_zeilen(self):
        """Ausgeführt, nicht am Quelltext gelesen.

        `AktivitaetsLog.objects` verlangt ausserhalb einer Anfrage einen
        gesetzten Mandantenkontext — hier gehört er auch hin: Die Einträge
        sollen der Organisation gehören, deren Benutzer sie später abruft.
        """
        from core.models import AktivitaetsLog
        from core.tenancy import organisation_kontext

        from ._isolation import MandantenFixture

        a = MandantenFixture('L', '8000', 'Zürich')
        with organisation_kontext(a.organisation):
            for i in range(40):
                AktivitaetsLog.objects.create(
                    benutzer=a.benutzer, aktion=f'Testaktion {i}',
                    objekt='X', details='', kategorie='sonstiges')

        c = Client()
        c.force_login(a.benutzer)
        antwort = c.get('/neu/logbuch/', {'export': 'csv', 'tage': '30'})
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(hasattr(antwort, 'streaming_content'),
                        'Die Antwort streamt nicht — dann ist die Grenze nur '
                        'verschoben, nicht weg.')
        text = b''.join(antwort.streaming_content).decode('utf-8')
        fehlend = [i for i in range(40) if f'Testaktion {i}' not in text]
        self.assertEqual(
            fehlend, [],
            f'Diese Einträge fehlen im Export: {fehlend}. Der Bericht ist '
            'unvollständig, ohne es zu sagen.')

    def test_der_export_zeigt_keine_fremden_eintraege(self):
        """Die grosszügigere Ausgabe darf die Mandantengrenze nicht aufweichen.

        Wer alle Zeilen liefert statt der ersten 10 000, liefert auch alle
        fremden, wenn der Filter nicht hält.
        """
        from core.models import AktivitaetsLog
        from core.tenancy import organisation_kontext

        from ._isolation import MandantenFixture

        a = MandantenFixture('L', '8000', 'Zürich')
        b = MandantenFixture('M', '3000', 'Bern')
        for f, marke in ((a, 'EigeneAktion'), (b, 'FremdeAktion')):
            with organisation_kontext(f.organisation):
                AktivitaetsLog.objects.create(
                    benutzer=f.benutzer, aktion=marke, objekt='X',
                    details='', kategorie='sonstiges')

        c = Client()
        c.force_login(a.benutzer)
        text = b''.join(c.get('/neu/logbuch/', {'export': 'csv', 'tage': '30'})
                        .streaming_content).decode('utf-8')
        self.assertIn('EigeneAktion', text,
                      'Der eigene Eintrag fehlt — dann prüft die Zeile '
                      'darunter nichts.')
        self.assertNotIn(
            'FremdeAktion', text,
            'Der Export enthält einen Eintrag aus einer fremden Organisation.')

class ExportTest(TestCase):
    """Die Ansicht muss die Gesamtzahl auch übergeben."""

    def test_die_view_reicht_die_gesamtzahl_durch(self):
        """Sonst wäre die Kopfzeile oben richtig und nutzlos.

        Geprüft am Quelltext, weil der Aufruf sonst nur mit über 2'000
        Testdatensätzen sichtbar würde — die anzulegen kostet mehr, als die
        Prüfung wert ist.
        """
        import inspect

        from core.views.fw import profil
        quelle = inspect.getsource(profil)
        self.assertIn(
            'gesamt=gesamt', quelle,
            'Die Ansicht übergibt die Gesamtzahl nicht — dann meldet der '
            'Bericht nie einen Ausschnitt.')
        self.assertIn(
            'GRENZE = 2000', quelle,
            'Die Obergrenze steht nicht mehr als benannte Zahl da.')
