"""Die Kopfzeilensuche darf nicht über die Mandantengrenze sehen.

DIE LÜCKE

Es gibt zwei Suchen mit denselben Feldern, aber verschiedenen Grenzen:

  `/neu/palette/`  (⌘K)  je 5 Personen, 4 Liegenschaften — bewacht seit E1.2
                          durch `test_palette_suche.py`
  `/neu/suche/`    (Kopf) je 20 Treffer je Art — **nicht bewacht**

Beide fragen `Mieter.objects.filter(…)`, also den mandantengefilterten
Standardmanager. Das genügt heute. Aber «genügt, weil der Manager filtert» ist
eine Annahme über eine Mandantengrenze, und die gehören geprüft, nicht
angenommen — dieselbe Begründung, mit der `test_palette_suche.py` in E1.2
entstanden ist.

Die Kopfzeilensuche ist dabei die gefährlichere von beiden: Sie liefert
viermal so viele Treffer, sie sucht zusätzlich über Telefonnummern (mit einem
Nachfilter über 500 Datensätze), und sie ist die Suche, die ein Sachbearbeiter
den ganzen Tag benutzt.

WAS GEPRÜFT WIRD

Zwei Organisationen, in jeder eine Person, eine Liegenschaft, eine Einheit und
ein Vertrag mit unterscheidbaren Namen. Dann wird als Mitglied der einen
Organisation nach den Daten der anderen gesucht — über Namen, Adresse und
Telefonnummer.

Die Gegenprobe steht darunter: Ohne die Mandantenbindung müsste der Test rot
werden. Ist er es nicht, prüft er etwas anderes als seinen Namen.
"""
import re

from django.test import Client, TestCase

from ._isolation import MandantenFixture


class KopfzeilensucheMandantengrenzeTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _trefferbereich(self, benutzer, q):
        """Nur die Trefferliste — ohne Seitentitel, Eingabefeld und Meldung.

        WARUM DAS NOETIG IST

        Eine erste Fassung dieses Tests suchte den fremden Wert im GANZEN
        HTML und schlug an. Der Befund sah nach einem Isolationsbruch aus und
        war keiner: Die drei Fundstellen waren der Seitentitel
        («Suche: B-Weg 7»), das Eingabefeld (`value="B-Weg 7"`) und die
        Meldung «0 TREFFER fuer B-Weg 7».

        Alle drei zeigen den Suchbegriff, den der Benutzer selbst eingetippt
        hat — nicht Daten aus der Datenbank. Ein Test, der das nicht trennt,
        meldet jede Suche nach einem fremden Namen als Bruch, und der naechste
        Bearbeiter glaubt ihm nicht mehr.
        """
        c = Client()
        c.force_login(benutzer)
        antwort = c.get('/neu/suche/', {'q': q})
        self.assertEqual(antwort.status_code, 200,
                         'Die Kopfzeilensuche antwortet nicht.')
        html = antwort.content.decode()
        # Ab der Trefferzahl bis zum Seitenfuss: dort stehen die Ergebnisse.
        # An DREI Stellen nennt die Seite den Suchbegriff, ohne dass er aus
        # der Datenbank kaeme: Seitentitel, Eingabefeld und — bei null
        # Treffern — der Leer-Zustand «Keine Treffer fuer …». Alle drei zeigen,
        # was der Benutzer selbst getippt hat.
        #
        # Erst danach beginnt das, was dieser Test meint: die Abschnitte
        # «Personen», «Liegenschaften», «Objekte», «Vertraege».
        rumpf = html.split('</main>')[0]
        for anfang in ('Personen (', 'Liegenschaften (', 'Objekte (', 'Verträge ('):
            i = rumpf.find(anfang)
            if i >= 0:
                return rumpf[i:]
        return ''      # Keine Trefferabschnitte — dann gibt es nichts zu zeigen.

    def test_findet_die_eigenen_daten(self):
        """Ohne diesen Test wäre jede Grenze trivial eingehalten.

        Eine Suche, die nichts findet, verletzt keine Mandantengrenze — und
        prüft auch nichts. Erst wenn belegt ist, dass sie im eigenen Bestand
        etwas findet, sagt ihr Schweigen beim fremden etwas aus.

        Gesucht wird über die STRASSE der eigenen Liegenschaft («A-Weg 7»).
        Nicht über den Namen: Der Vorname ist in beiden Fixtures «Mieter»,
        der Nachname ein einzelnes Zeichen — und Suchen fragen unter zwei
        Zeichen bewusst nicht die Datenbank.

        Dieser Test traegt zugleich die Blindheitsprüfung für
        `_trefferbereich`: Findet die Methode keinen der vier
        Abschnitts-Titel, gibt sie eine leere Zeichenkette zurück, und jedes
        `assertNotIn` darunter wäre für immer grün. Benennt jemand die
        Abschnitte um, fällt zuerst diese Prüfung.
        """
        html = self._trefferbereich(self.a.benutzer, self.a.liegenschaft.strasse)
        self.assertIn(self.a.liegenschaft.strasse, html,
                      'Die Suche findet die eigene Liegenschaft nicht — dann '
                      'ist jede Prüfung unten wertlos, weil sie auf einer '
                      'leeren Trefferliste besteht.')

    def test_findet_nicht_ueber_die_mandantengrenze(self):
        # GESUCHT wird ueber die E-Mail, GEPRUEFT wird auf den Ort — die
        # beiden fallen hier auseinander, und das ist der Punkt:
        #
        # · Der Vorname taugt nicht zum Suchen: Er ist in BEIDEN Fixtures
        #   'Mieter'. Eine erste Fassung suchte damit und war rot, ohne dass
        #   eine Grenze verletzt war.
        # · Die E-Mail taugt nicht zum Pruefen: Die Trefferliste zeigt Name,
        #   Typ, PLZ und Ort — keine E-Mail. Eine Fassung, die darauf prueste,
        #   blieb bei AUSGEHEBELTER Grenze gruen. Ein Test, der einen Wert
        #   erwartet, den die Seite nie anzeigt, sieht keine gefallene Grenze.
        #
        # Also: suchen ueber einen Wert, den die Suche durchsucht (E-Mail),
        # pruefen auf einen Wert, den die Seite anzeigt (Ort).
        html = self._trefferbereich(self.a.benutzer, self.b.mieter.email)
        self.assertNotIn(
            self.b.liegenschaft.ort, html,
            f'Die Kopfzeilensuche zeigt eine Person aus {self.b.liegenschaft.ort} '
            f'— einer fremden Organisation.')

    def test_auch_nicht_ueber_die_adresse(self):
        """Liegenschaften tragen Strassennamen, die sich überschneiden können."""
        html = self._trefferbereich(self.a.benutzer, self.b.liegenschaft.strasse)
        self.assertNotIn(self.b.liegenschaft.strasse, html,
                         'Die Suche zeigt eine fremde Liegenschaft.')

    def test_auch_nicht_ueber_die_telefonnummer(self):
        """Der stillste Weg über die Grenze.

        Die Telefonsuche normalisiert Eingabe und Feldwerte auf reine Ziffern
        und filtert dafür über bis zu 500 Datensätze nach. Dieser Nachfilter
        läuft in Python, nicht in der Datenbank — ist die Grundmenge falsch,
        hilft kein Manager mehr.
        """
        self.b.mieter.mobile = '079 123 45 67'
        self.b.mieter.save(update_fields=['mobile'])
        # NUR die nationalen Schreibweisen — und das ist ein Befund, kein
        # Auslassen: `+41791234567` stand hier zuerst mit dabei und fiel bei
        # der Gegenprobe als EINZIGER Fall NICHT um. Nachgemessen im eigenen
        # Bestand, ohne jede Mandantengrenze: Die Suche findet die Person
        # unter der internationalen Schreibweise ueberhaupt nicht.
        #
        # Grund: Der Nachfilter vergleicht reine Ziffern, «+41 79 123 45 67»
        # ergibt '41791234567' und die gespeicherte Nummer '0791234567' —
        # die Landesvorwahl ersetzt die fuehrende Null, also ist das eine
        # kein Teilstring des anderen. Der Kommentar in `fw_suche` nennt
        # «+41791234567» ausdruecklich als Zielformat; die Absicht steht im
        # Code, die Umsetzung fehlt.
        #
        # Ein Prüffall, der nicht umfallen KANN, gehoert nicht in einen
        # Isolationstest — er taeuscht Abdeckung vor. Die Luecke ist
        # gemeldet und gehoert in eine eigene Etappe, weil sie das Verhalten
        # der Suche aendert, nicht ihre Grenze.
        for form in ('0791234567', '079 123 45 67'):
            with self.subTest(form=form):
                html = self._trefferbereich(self.a.benutzer, form)
                self.assertNotIn(
                    self.b.liegenschaft.ort, html,
                    f'Telefonsuche «{form}» zeigt eine Person aus '
                    f'{self.b.liegenschaft.ort} — einer fremden Organisation.')

    def test_die_gegenprobe(self):
        """Der Test oben muss rot werden, wenn die Grenze fällt.

        Ausgeführt, nicht behauptet: Mit `alle_organisationen` — dem Manager
        ohne Mandantenfilter — MUSS die fremde Person auffindbar sein und in
        einer anderen Organisation liegen. Sonst belegen die Prüfungen darüber
        nichts, und sie wären grün ohne zu prüfen.
        """
        from crm.models import Mieter
        gefunden = Mieter.alle_organisationen.filter(
            email=self.b.mieter.email)
        self.assertTrue(
            gefunden.exists(),
            'Die fremde Person existiert gar nicht — dann belegen die Tests '
            'oben nichts.')
        self.assertNotEqual(
            gefunden.first().organisation_id, self.a.organisation.id,
            'Beide Personen liegen in derselben Organisation — die Fixture '
            'bildet keine Grenze ab.')
