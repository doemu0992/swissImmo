"""Die ⌘K-Palette findet Datensätze — und nur die eigenen.

DER BEFUND (B7, behoben in E1.2)

Die Palette war die flache Liste der Menü-Labels. Wer «Blaser» tippte, las
«Keine Seite gefunden» und musste die Eingabe mit ↵ an `/neu/suche/`
weiterreichen — eine zweite Suche, eine zweite Ergebnisseite.

Für eine Verwaltung mit 300 Mietverhältnissen ist die Datensatzsuche der
Normalfall und die Seitensuche die Ausnahme: Man sucht Frau Blaser, nicht die
Seite «Mietverhältnisse». Ein Werkzeug hat dafür ein Feld, nicht zwei.

WARUM DIE ISOLATION HIER EIGENS GEPRÜFT WIRD

`/neu/palette/` ist ein neuer Weg an die Daten — und der erste, der über vier
Modelle auf einmal geht. Er enthält absichtlich KEINE eigene
Organisationslogik: Die Trennung kommt allein von den Managern
(`Mieter.objects` &c.). Was er nicht hat, kann er nicht falsch machen.

Genau deshalb steht der Test trotzdem hier. «Wir verlassen uns auf den
Manager» ist eine Annahme, und Annahmen über Mandantengrenzen gehören
geprüft — ein `alle_organisationen` an der falschen Stelle, und die Suche
liefert die Mieter der Konkurrenz. Der Test unten sucht deshalb gezielt nach
den Daten des ANDEREN Mandanten.
"""
import json

from django.test import Client, TestCase

from ._isolation import MandantenFixture


class PaletteSucheTests(TestCase):
    """Der JSON-Endpunkt hinter dem ⌘K-Feld."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _hole(self, benutzer, q):
        c = Client()
        c.force_login(benutzer)
        antwort = c.get('/neu/palette/', {'q': q})
        self.assertEqual(antwort.status_code, 200)
        return json.loads(antwort.content)['treffer']

    def test_findet_die_eigene_mieterin(self):
        # `vorname`, nicht `nachname`: Der Nachname im Fixture ist EIN Zeichen
        # ('A' bzw. 'B'), und der Endpunkt fragt unter zwei Zeichen bewusst
        # nicht die Datenbank. Eine erste Fassung dieses Tests suchte damit und
        # war rot — nicht wegen der Suche, sondern wegen der Eingabe.
        treffer = self._hole(self.a.benutzer, self.a.mieter.vorname)
        self.assertTrue(treffer, 'Die eigene Mieterin wurde nicht gefunden.')
        arten = {t['art'] for t in treffer}
        self.assertIn('Person', arten, f'Keine Person unter {arten}.')
        for t in treffer:
            with self.subTest(art=t['art']):
                self.assertTrue(t['url'].startswith('/neu/'), t)
                self.assertTrue(t['label'], 'Treffer ohne Beschriftung')

    def test_der_volle_name_findet_die_person(self):
        """Wortweise statt am Stück — sonst versagt die Suche genau dann,
        wenn man den vollen Namen kennt.

        Ein `icontains` über die ganze Eingabe fragt «enthält der Vorname die
        Zeichenkette 'Anna Blaser'?» — nein — und «enthält der Nachname sie?»
        — auch nicht. Vorname und Nachname stehen in getrennten Spalten.
        """
        voll = f'{self.a.mieter.vorname} {self.a.mieter.nachname}'
        treffer = self._hole(self.a.benutzer, voll)
        self.assertTrue(
            [t for t in treffer if t['art'] == 'Person'],
            f'«{voll}» findet die Person nicht — die Suche prüft jedes Feld '
            f'gegen die ganze Eingabe statt wortweise.')

        # Und die umgekehrte Reihenfolge ebenso.
        umgekehrt = f'{self.a.mieter.nachname} {self.a.mieter.vorname}'
        self.assertTrue([t for t in self._hole(self.a.benutzer, umgekehrt)
                         if t['art'] == 'Person'], umgekehrt)

    def test_findet_die_eigene_liegenschaft(self):
        treffer = self._hole(self.a.benutzer, self.a.liegenschaft.strasse[:6])
        arten = {t['art'] for t in treffer}
        self.assertIn('Liegenschaft', arten, f'Nur {arten} gefunden.')

    def test_findet_NICHT_ueber_die_mandantengrenze(self):
        """Der eigentliche Grund für diese Datei.

        Gesucht wird mit den Daten von Mandant B, angemeldet ist A. Kommt hier
        etwas zurück, liefert die Suche die Daten einer fremden Verwaltung —
        der schwerste Fehler, den dieses Produkt machen kann.

        Geprüft wird gegen die IDs, nicht gegen Wortbestandteile: Ein Vergleich
        auf «steht ein B im Text» wäre unzuverlässig in beide Richtungen.
        """
        fremde_urls = {
            f'/neu/personen/{self.b.mieter.id}/',
            f'/neu/liegenschaften/{self.b.liegenschaft.id}/',
            f'/neu/objekte/{self.b.einheit.id}/',
            f'/neu/vertraege/{self.b.vertrag.id}/',
        }
        begriffe = [
            self.b.liegenschaft.strasse,
            self.b.mieter.email,
            self.b.liegenschaft.ort,
            # Der schärfste Fall: Beide Mieter heissen mit Vornamen «Mieter».
            # Diese Eingabe trifft in der Datenbank BEIDE — nur der
            # Mandantenfilter entscheidet, was zurückkommt. Ein `objects`, das
            # versehentlich zu `alle_organisationen` würde, fällt genau hier auf.
            self.b.mieter.vorname,
            f'{self.b.mieter.vorname} {self.b.mieter.nachname}',
        ]
        for begriff in begriffe:
            with self.subTest(begriff=begriff):
                treffer = self._hole(self.a.benutzer, begriff)
                fremd = [t for t in treffer if t['url'] in fremde_urls]
                self.assertEqual(
                    fremd, [],
                    f'Die Suche von Mandant A liefert Daten von Mandant B: {fremd}')

    def test_die_gegenprobe_zur_mandantengrenze(self):
        """Ohne sie wäre der Test darüber auch dann grün, wenn die Suche
        grundsätzlich nichts fände.

        Derselbe Begriff, von B aus gesucht, MUSS die Daten von B liefern.
        """
        treffer = self._hole(self.b.benutzer, self.b.mieter.vorname)
        self.assertIn(
            f'/neu/personen/{self.b.mieter.id}/', [t['url'] for t in treffer],
            'B findet die eigene Mieterin nicht — dann prüft der Test darüber '
            'nur, dass die Suche überhaupt nichts liefert.')

    def test_kurze_eingaben_fragen_die_datenbank_nicht(self):
        """Ein einzelner Buchstabe trifft fast alles und kostet vier Abfragen.

        Bei jedem Tastendruck. Die Palette zeigt bis zwei Zeichen die Seiten —
        die liegen ohnehin im Browser.
        """
        for kurz in ('', 'M', ' '):
            with self.subTest(q=repr(kurz)):
                self.assertEqual(self._hole(self.a.benutzer, kurz), [])

    def test_die_treffermenge_bleibt_lesbar(self):
        """Höchstens 15 — die Palette ist eine Abkürzung, keine Liste."""
        treffer = self._hole(self.a.benutzer, self.a.mieter.vorname)
        self.assertTrue(treffer, 'Nichts gefunden — dann sagt die Obergrenze nichts.')
        self.assertLessEqual(len(treffer), 15, f'{len(treffer)} Treffer.')

    def test_ohne_anmeldung_kein_zugriff(self):
        antwort = Client().get('/neu/palette/', {'q': 'Mieter'})
        self.assertIn(antwort.status_code, (302, 403),
                      'Der Endpunkt gibt ohne Anmeldung Daten heraus.')
