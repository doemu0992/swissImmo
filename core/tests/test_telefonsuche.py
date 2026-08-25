"""Die Telefonsuche muss jede übliche Schreibweise finden.

DER BEFUND

`+41 79 123 45 67` fand eine als `079 123 45 67` gespeicherte Nummer nicht —
auch im eigenen Bestand. Der Kommentar in `fw_suche` nannte genau dieses
Format als Ziel:

    «Nummern werden in vielen Formaten erfasst (»079 123 45 67«,
     »+41791234567«) — Query UND Feldwerte auf reine Ziffern normalisieren,
     damit der Anrufer vom Display direkt gefunden wird.»

Die Absicht stand da, die Umsetzung reichte nicht: »Nur die Ziffern behalten«
macht aus der Eingabe `41791234567` und aus dem Feld `0791234567`. Die
Landesvorwahl **ersetzt** die führende Null, sie ergänzt sie nicht.

WARUM DAS IM ALLTAG WIEGT

Der genannte Fall ist der häufigste: Ein Anruf kommt herein, das Display zeigt
die internationale Schreibweise, der Sachbearbeiter tippt sie ab — und findet
seine eigene Mieterin nicht. Er sucht dann von Hand oder ruft zurück, ohne zu
wissen, mit wem er spricht.

WAS GEPRÜFT WIRD

`telefon_kern()` als reine Funktion — über alle Schreibweisen, die in der
Schweiz vorkommen, und über die Fälle, in denen sie NICHT kürzen darf. Dazu
ein Test über die ganze Kette, damit die Funktion nicht richtig ist, während
die Suche sie falsch benutzt.
"""
from django.test import Client, TestCase

from core.views.fw.liegenschaft_crud import telefon_kern

from ._isolation import MandantenFixture


class TelefonKernTest(TestCase):
    """Die Rechnung allein — ohne Datenbank, ohne Ansicht."""

    def test_alle_schreibweisen_derselben_nummer_sind_gleich(self):
        """Der Kern des Befunds.

        Fünf Schreibweisen einer einzigen Nummer. Wer eine davon eintippt,
        muss die anderen finden — das ist der ganze Zweck.
        """
        formen = ('079 123 45 67', '0791234567', '+41 79 123 45 67',
                  '+41791234567', '0041791234567')
        kerne = {telefon_kern(f) for f in formen}
        self.assertEqual(
            len(kerne), 1,
            f'Dieselbe Nummer ergibt {len(kerne)} verschiedene Kerne: {kerne}. '
            f'Damit findet eine Schreibweise die andere nicht.')
        self.assertEqual(kerne.pop(), '791234567')

    def test_die_festnetznummer_ebenso(self):
        formen = ('044 123 45 67', '+41 44 123 45 67', '0041441234567')
        self.assertEqual(len({telefon_kern(f) for f in formen}), 1)

    def test_auslaendische_nummern_bleiben_unterscheidbar(self):
        """Sonst würde die Suche Nummern verwechseln.

        `+49 30 12345678` darf nicht auf dieselbe Weise gekürzt werden — sonst
        fiele die deutsche Vorwahl weg und die Nummer wäre von einer
        Schweizer nicht mehr zu trennen.
        """
        self.assertNotEqual(telefon_kern('+49 30 12345678'),
                            telefon_kern('030 12345678'))

    def test_luzern_verliert_seine_vorwahl_nicht(self):
        """Der Fall, für den die Längenprüfung wirklich da ist.

        Luzern und Zug haben die Vorwahl **041**. Wer die Nummer ohne
        führende Null schreibt — `41 123 45 67` —, beginnt mit denselben
        zwei Ziffern wie die Landesvorwahl, ohne dass eine da wäre.

        Ohne die Prüfung auf elf Ziffern würde daraus `1234567`: eine
        andere, kürzere Nummer, die dann auf fremde Einträge passt. Mit ihr
        bleiben alle sieben Schreibweisen derselben Luzerner Nummer gleich —
        nachgemessen, samt der internationalen Form, in der «41» dann
        zweimal hintereinander steht (`+41 41 …`).

        (Eine frühere Fassung nannte hier «41 22 …, eine Genfer Nummer ohne
        Null» — Genf hat 022, und `4122333` ist keine vollständige Nummer.
        Der Fall war ausgedacht, die Prüfung ist es nicht.)
        """
        formen = ('041 123 45 67', '0411234567', '41 123 45 67', '411234567',
                  '+41 41 123 45 67', '+41411234567', '0041411234567')
        kerne = {telefon_kern(f) for f in formen}
        self.assertEqual(
            kerne, {'411234567'},
            f'Die Luzerner Nummer zerfällt in {len(kerne)} Kerne: {kerne}. '
            'Entweder wurde die führende «41» als Landesvorwahl gestrichen '
            '(dann fehlt die Ortsvorwahl), oder die internationale Form wird '
            'nicht mehr erkannt.')

    def test_jede_schweizer_vorwahl_faellt_zusammen(self):
        """Nicht nur die eine Nummer aus dem Befund.

        Vier Vorwahlen quer durch die Schweiz, je fünf Schreibweisen. Ein
        Test mit einer einzigen Beispielnummer sagt wenig über eine
        Normalisierung aus.
        """
        for vorwahl, ort in (('41', 'Luzern'), ('22', 'Genf'),
                             ('31', 'Bern'), ('91', 'Tessin')):
            with self.subTest(ort=ort):
                formen = (f'0{vorwahl} 123 45 67', f'0{vorwahl}1234567',
                          f'+41 {vorwahl} 123 45 67', f'+41{vorwahl}1234567',
                          f'0041{vorwahl}1234567')
                self.assertEqual(
                    {telefon_kern(f) for f in formen}, {f'{vorwahl}1234567'},
                    f'Die Schreibweisen einer {ort}er Nummer (0{vorwahl}) '
                    'fallen nicht zusammen.')

    def test_leere_eingabe_stuerzt_nicht_ab(self):
        for wert in ('', None, '   ', '---'):
            with self.subTest(wert=wert):
                self.assertEqual(telefon_kern(wert), '')


class TelefonsucheTest(TestCase):
    """Die ganze Kette — damit die Funktion nicht richtig, die Suche aber
    falsch ist."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.a.mieter.mobile = '079 123 45 67'
        self.a.mieter.save(update_fields=['mobile'])

    def _treffer(self, q):
        c = Client()
        c.force_login(self.a.benutzer)
        html = c.get('/neu/suche/', {'q': q}).content.decode()
        rumpf = html.split('</main>')[0]
        i = rumpf.find('Personen (')
        return rumpf[i:] if i >= 0 else ''

    def test_findet_ueber_jede_schreibweise(self):
        for form in ('079 123 45 67', '0791234567', '+41 79 123 45 67',
                     '+41791234567', '0041791234567'):
            with self.subTest(form=form):
                self.assertIn(
                    self.a.liegenschaft.ort, self._treffer(form),
                    f'Die eigene Mieterin wird über «{form}» nicht gefunden.')

    def test_kein_treffer_ueber_die_feldgrenze(self):
        """Der Fehler, den E2.26 nebenbei behoben hat — und der unbewacht war.

        Die alte Fassung klebte die drei Telefonfelder mit `|` zusammen und
        filterte DANACH die Ziffern heraus. Das Trennzeichen fiel dabei weg,
        die Nummern standen ohne Grenze nebeneinander — und eine Suche über
        die Nahtstelle traf.

        Beispiel: Mobil `079 123 45 67`, Festnetz `044 987 65 43` ergaben
        zusammen `...45670449...`. Wer «45670449» suchte, bekam diese Person,
        obwohl diese Ziffernfolge in keiner ihrer Nummern vorkommt. Bei 500
        durchsuchten Datensätzen ist das kein theoretischer Fall.

        Nachgemessen: Ohne diesen Test blieb die Suite grün, als das
        Zusammenkleben versuchsweise wiederhergestellt wurde. Ein behobener
        Fehler ohne Prüfung ist ein Fehler auf Bewährung.
        """
        m = self.a.mieter
        m.mobile = '079 123 45 67'
        m.telefon_privat = '044 987 65 43'
        m.telefon_geschaeft = ''
        m.save(update_fields=['mobile', 'telefon_privat', 'telefon_geschaeft'])

        for naht in ('45670449', '4567044', '567044987'):
            with self.subTest(naht=naht):
                self.assertNotIn(
                    self.a.liegenschaft.ort, self._treffer(naht),
                    f'«{naht}» liegt über der Grenze zwischen Mobil- und '
                    'Festnetznummer und trifft trotzdem — die Felder werden '
                    'wieder zusammengeklebt.')

        # Und die echten Nummern müssen weiterhin treffen, sonst wäre die
        # Prüfung oben auch mit einer kaputten Suche zu bestehen.
        for echt in ('0791234567', '+41791234567',
                     '0449876543', '+41449876543'):
            with self.subTest(echt=echt):
                self.assertIn(
                    self.a.liegenschaft.ort, self._treffer(echt),
                    f'«{echt}» findet die Person nicht mehr.')

    def test_auch_ueber_die_schreibweise_nicht_ueber_die_mandantengrenze(self):
        """Die Verbesserung darf die Grenze nicht aufweichen.

        Eine grosszügigere Normalisierung findet mehr — auch mehr Fremdes,
        wenn die Isolation nicht hielte.
        """
        self.b.mieter.mobile = '078 999 88 77'
        self.b.mieter.save(update_fields=['mobile'])
        for form in ('+41789998877', '078 999 88 77'):
            with self.subTest(form=form):
                self.assertNotIn(self.b.liegenschaft.ort, self._treffer(form))
