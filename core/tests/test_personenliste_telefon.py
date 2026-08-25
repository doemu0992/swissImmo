"""Auch die Personenliste muss Telefonnummern über Schreibweisen finden.

DER BEFUND

`/neu/personen/?q=` suchte mit reinem `icontains` über die Telefonfelder.
Damit fand `0791234567` eine als `079 123 45 67` gespeicherte Nummer **nicht**
— gemessen 5 von 18 Treffern, also weniger als ein Drittel.

Das ist derselbe Mangel wie in der Kopfzeilensuche (E2.26), nur schlimmer:
Dort gab es wenigstens einen Nachfilter über die Ziffern, hier gar keinen.

DIE LÖSUNG IST DIESELBE WIE IN DER KOPFZEILENSUCHE

Zuerst gebaut war eine andere: aus dem Kern die möglichen Speicherformen
erzeugen (`079 123 45 67`, `+41 79 …`, `0791234567`) und danach suchen. Die
Begründung dafür lautete, die Personenliste sei eine Listenansicht — ein
Nachfilter würde aus der Abfrage eine Liste machen und Sortierung und Zählung
verändern.

**Nachgesehen: Das trifft auf diese View nicht zu.** `fw_personen` paginiert
nicht, zählt mit `{{ rows|length }}` aus der fertigen Python-Liste, und die
Abfrage wird nach dem Filtern genau einmal benutzt (`for m in qs`). Es gibt
nichts, dessen Semantik ein Nachfilter ändern könnte.

Und das Raten kostet: Es rät, in welcher Form die Nummer erfasst wurde.
Realistische Formen ausserhalb der geratenen Liste fallen still durch. Über
acht Speicherformate × sieben Suchbegriffe gemessen:

    vorher (reines icontains)   5 von 18 — knapp ein Viertel
    Schreibweisen raten        33 von 56
    Kern vergleichen           56 von 56

`079/123 45 67` und `079.123.45.67` wurden beim Raten von **keiner** der
sieben Suchvarianten gefunden, `079 123 4567` von einer.

Deshalb hier dasselbe Verfahren wie in `fw_suche`: `telefon_kern()` auf beiden
Seiten, Vergleich in Python — aber als **Ids**, die mit `id__in` in die
Bedingung zurückfliessen. Die Abfrage bleibt eine Abfrage.

Zwei Suchen mit unterschiedlichem Verhalten wären dem Benutzer ohnehin nicht
zu erklären.

WAS DAS NICHT LEISTET

Die Grenze liegt jetzt bei `telefon_kern()` selbst: Es entfernt Landesvorwahl
und führende Null, mehr nicht. Eine Nummer mit Buchstaben darin oder eine
ausländische in ungewohnter Form bleibt unauffindbar. Der ganz saubere Weg
wäre eine normalisierte Spalte in der Datenbank — eine Migration und damit
eine eigene Etappe.
"""
from django.test import Client, TestCase

from core.views.fw.liegenschaft_crud import telefon_kern
from core.views.fw.listen import telefon_treffer_ids

from ._isolation import MandantenFixture


class TrefferIdsTest(TestCase):
    """Die Auswahl allein — gegen echte Datensätze, ohne Ansicht."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _mit(self, mobil, privat='', geschaeft=''):
        from crm.models import Mieter
        m = self.a.mieter
        m.mobile, m.telefon_privat, m.telefon_geschaeft = mobil, privat, geschaeft
        m.save(update_fields=['mobile', 'telefon_privat', 'telefon_geschaeft'])
        return Mieter.alle_organisationen.filter(organisation=self.a.organisation)

    def test_jede_speicherform_wird_gefunden(self):
        """Der Punkt, an dem das Formen-Raten scheiterte.

        Acht Schreibweisen, in denen dieselbe Nummer erfasst sein kann —
        einschliesslich der beiden, die beim Raten durchfielen
        (`079/123 45 67`, `079.123.45.67`).
        """
        kern = telefon_kern('+41 79 123 45 67')
        for gespeichert in ('079 123 45 67', '0791234567', '+41 79 123 45 67',
                            '+41791234567', '0041791234567', '079/123 45 67',
                            '079.123.45.67', '079 123 4567'):
            with self.subTest(gespeichert=gespeichert):
                self.assertIn(
                    self.a.mieter.id, telefon_treffer_ids(kern, self._mit(gespeichert)),
                    f'Eine als «{gespeichert}» erfasste Nummer wird über den '
                    'Kern nicht gefunden.')

    def test_eine_andere_nummer_wird_nicht_gefunden(self):
        """Ohne diesen Fall prüfte der Test oben nur «findet immer alles»."""
        kern = telefon_kern('+41 79 123 45 67')
        self.assertEqual(
            telefon_treffer_ids(kern, self._mit('078 999 88 77')), [],
            'Eine fremde Nummer wird mitgeliefert — die Auswahl trifft zu breit.')

    def test_kein_treffer_ueber_die_feldgrenze(self):
        """Derselbe Fehler, den E2.26 in der Kopfzeilensuche behoben hat.

        Mobil `079 123 45 67` und Festnetz `044 987 65 43` ergäben
        zusammengeklebt `...45670449...`. Wer über die Nahtstelle sucht, darf
        die Person nicht bekommen — die Ziffernfolge steht in keiner ihrer
        Nummern.
        """
        grund = self._mit('079 123 45 67', '044 987 65 43')
        for naht in ('45670449', '4567044', '567044987'):
            with self.subTest(naht=naht):
                self.assertEqual(
                    telefon_treffer_ids(naht, grund), [],
                    f'«{naht}» liegt über der Feldgrenze und trifft trotzdem.')
        # Und die echten Nummern müssen weiter treffen.
        for echt in ('791234567', '449876543'):
            with self.subTest(echt=echt):
                self.assertIn(self.a.mieter.id, telefon_treffer_ids(echt, grund))

    def test_personen_ohne_nummer_kosten_nichts(self):
        """Wer keine Nummer hat, wird gar nicht erst gelesen."""
        self.assertEqual(telefon_treffer_ids('791234567', self._mit('')), [])


class PersonenlisteTelefonTest(TestCase):
    """Die ganze Kette."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.a.mieter.mobile = '079 123 45 67'
        self.a.mieter.save(update_fields=['mobile'])

    def _zeilen(self, q):
        """Nur die Tabellenzeilen — ohne die Eingabefelder.

        Die Seite traegt den Suchbegriff an ZWEI Stellen als `value="…"` in
        Eingabefeldern: in der Kopfzeilensuche und im Filterfeld der Liste.
        Beide zeigen, was der Benutzer getippt hat — nicht, was die Datenbank
        geliefert hat.

        Eine erste Fassung suchte im ganzen HTML und meldete einen
        Isolationsbruch, der keiner war. Derselbe Fall wie in
        `test_kopfsuche_grenze.py`; dort kam der Seitentitel dazu.
        """
        c = Client()
        c.force_login(self.a.benutzer)
        html = c.get('/neu/personen/', {'q': q}).content.decode()
        i = html.find('<tbody')
        if i < 0:
            return ''
        return html[i:html.find('</tbody>', i)]

    def test_findet_ueber_jede_schreibweise(self):
        for form in ('079 123 45 67', '0791234567', '+41 79 123 45 67',
                     '+41791234567', '0041791234567'):
            with self.subTest(form=form):
                self.assertIn(
                    self.a.mieter.email, self._zeilen(form),
                    f'Die Personenliste findet die eigene Mieterin über '
                    f'«{form}» nicht.')

    def test_die_mandantengrenze_haelt_weiterhin(self):
        """Die Erweiterung darf die Isolation nicht aufweichen.

        Wer mehr Schreibweisen findet, findet sonst auch mehr Fremdes.
        """
        self.b.mieter.mobile = '078 999 88 77'
        self.b.mieter.save(update_fields=['mobile'])
        for form in ('+41789998877', '078 999 88 77'):
            with self.subTest(form=form):
                html = self._zeilen(form)
                self.assertNotIn(
                    self.b.liegenschaft.ort, html,
                    f'Die Personenliste zeigt über «{form}» eine Person aus '
                    f'einer fremden Organisation.')

    def test_auch_die_suche_ueber_die_e_mail_bleibt_an_der_grenze(self):
        """Nicht nur der Telefonweg über die Mandantengrenze.

        Der Test hiess zuerst «die Suche nach Namen bleibt unverändert» und
        sollte belegen, dass die zusätzliche Telefonbedingung eine
        Namenssuche nicht grosszügiger macht. Gemessen misst er etwas
        anderes: Bei ausgehebeltem Mandantenfilter fällt er um — es ist eine
        Grenzprüfung, keine Aussage über Namen.

        Unter dem richtigen Namen ist er trotzdem nützlich: Er deckt den
        zweiten Weg zur fremden Person ab, den über ein Textfeld, während
        `test_die_mandantengrenze_haelt_weiterhin` den über die Nummer prüft.
        """
        self.assertNotIn(
            self.b.mieter.email, self._zeilen(self.b.mieter.email),
            'Die Personenliste zeigt eine Person aus einer fremden '
            'Organisation, gesucht über ihre E-Mail-Adresse.')

    def test_die_gegenprobe(self):
        """Ohne die Erweiterung müsste eine Schreibweise fehlschlagen.

        Belegt, dass die Prüfungen oben etwas messen: `icontains` allein
        findet die zusammengeschriebene Form nicht, wenn mit Leerzeichen
        gespeichert wurde.
        """
        # `alle_organisationen`, weil ausserhalb einer Anfrage kein
        # Mandantenkontext gesetzt ist — `objects` wuerde hier scheitern.
        # Geprueft wird die Speicherform, nicht die Sichtbarkeit.
        from crm.models import Mieter
        gefunden = Mieter.alle_organisationen.filter(mobile__icontains='0791234567')
        self.assertFalse(
            gefunden.exists(),
            'Die zusammengeschriebene Form wird schon von `icontains` '
            'gefunden — dann belegt der Test oben nichts.')
