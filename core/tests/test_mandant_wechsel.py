"""Der Mandantenwechsel — und warum er der gefährlichste Knopf der Anwendung ist.

WARUM ES IHN GIBT (E1.2)

`crm.Mitgliedschaft` erlaubt seit Etappe 4.1 mehrere Organisationen je Person,
und `core.middleware_tenancy` liest dafür längst einen Sessionwert. Was fehlte,
war die Auswahl: Wer für zwei Verwaltungen arbeitet, landete immer in der
ältesten — die Middleware protokollierte das bei jeder Anfrage, und niemand
liest Protokolle.

WARUM DIESE DATEI SO GENAU HINSCHAUT

`/neu/mandant/` setzt den Wert, an dem die **gesamte** Mandantentrennung hängt.
Prüft er nur «gibt es diese Organisation?» statt «ist diese Person dort
Mitglied?», lässt sich die Trennung mit einem Formularfeld aushebeln: ein POST
mit fremder ID, und die Verwaltung sieht die Daten der Konkurrenz.

Der Test unten versucht genau das — mit der ID von Mandant B, angemeldet als A.

ZWEI SCHICHTEN, BEIDE GEPRÜFT
-----------------------------
Die obere ist der View. Die untere ist `middleware_tenancy._organisation_fuer`:
Sie ehrt den Sessionwert nur, wenn er zu einer echten Mitgliedschaft passt.
`test_ein_untergeschobener_sessionwert_wirkt_nicht` greift an der oberen vorbei
und setzt den Wert direkt in die Session — denn die obere Schicht umgeht
irgendwann jemand, und dann muss die untere halten.
"""
from django.test import Client, TestCase

from core.middleware_tenancy import SESSION_SCHLUESSEL

from ._isolation import MandantenFixture


class MandantWechselTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _angemeldet(self):
        c = Client()
        c.force_login(self.a.benutzer)
        return c

    def test_ein_fremder_mandant_wird_nicht_uebernommen(self):
        """Der eigentliche Grund für diese Datei."""
        c = self._angemeldet()
        antwort = c.post('/neu/mandant/', {'organisation': self.b.organisation.id})

        self.assertNotEqual(
            c.session.get(SESSION_SCHLUESSEL), self.b.organisation.id,
            'Ein POST mit fremder Organisations-ID hat den Mandanten gewechselt. '
            'Damit ist die Mandantentrennung mit einem Formularfeld aushebelbar.')
        self.assertIn(antwort.status_code, (302, 303))

        # Und die Daten von B bleiben unsichtbar.
        html = c.get('/neu/liegenschaften/').content.decode()
        self.assertNotIn(self.b.liegenschaft.strasse, html,
                         'Nach dem versuchten Wechsel sind fremde Daten sichtbar.')

    def _mit_zwei_mitgliedschaften(self):
        """Benutzer A zusätzlich in einen dritten Mandanten aufnehmen.

        NOTWENDIG, NICHT KOSMETIK: `_organisation_fuer` liest den Sessionwert
        NUR, wenn jemand mehr als eine Mitgliedschaft hat — bei genau einer
        gibt sie diese zurück und schaut gar nicht in die Session.

        Eine erste Fassung von `test_ein_untergeschobener_sessionwert_wirkt_nicht`
        arbeitete mit dem gewöhnlichen Benutzer (eine Mitgliedschaft). Die
        Gegenprobe — Middleware übernimmt den Wert ungeprüft — blieb GRÜN: Der
        Test hatte den geprüften Zweig nie betreten. Er bestätigte die zweite
        Schicht, ohne sie zu berühren.
        """
        from crm.models import Mitgliedschaft, Organisation
        dritte = Organisation.objects.create(
            firma='Verwaltung C AG', strasse='C-Weg 1', plz='6000', ort='Luzern')
        Mitgliedschaft.alle_organisationen.create(
            benutzer=self.a.benutzer, organisation=dritte,
            rolle=Mitgliedschaft.ROLLE_VERWALTER)
        return dritte

    def test_ein_untergeschobener_sessionwert_wirkt_nicht(self):
        """Die zweite Schicht, am View vorbei geprüft.

        Wer den Sessionwert auf anderem Weg setzt — ein anderer View, ein
        Fehler, eine spätere Änderung —, darf damit trotzdem nichts sehen.
        Die Middleware gleicht den Wert gegen die echten Mitgliedschaften ab.
        Ohne diesen Test wäre nur die obere Schranke geprüft.
        """
        self._mit_zwei_mitgliedschaften()      # sonst liest die Middleware gar nicht
        c = self._angemeldet()
        sitzung = c.session
        sitzung[SESSION_SCHLUESSEL] = self.b.organisation.id
        sitzung.save()

        html = c.get('/neu/liegenschaften/').content.decode()
        self.assertNotIn(
            self.b.liegenschaft.strasse, html,
            'Ein von Hand gesetzter Sessionwert hat den Mandanten gewechselt — '
            'die Middleware gleicht ihn nicht gegen die Mitgliedschaften ab.')

    def test_die_middleware_prueft_den_sessionwert_selbst(self):
        """Die zweite Schicht DIREKT, nicht durch die Anwendung hindurch.

        WARUM NICHT ÜBER EINEN SEITENAUFRUF

        `test_ein_untergeschobener_sessionwert_wirkt_nicht` ruft
        `/neu/liegenschaften/` auf und prüft, dass keine fremden Daten
        erscheinen. Das ist richtig, isoliert aber die Schicht nicht: Beim
        Gegenprobieren — Prüfung aus der Middleware entfernt — blieb der Test
        GRÜN. Es greift offenbar noch etwas anderes (die Rollenprüfung), und
        welche Schranke gehalten hat, war nicht zu erkennen.

        Ein Test, der drei Schichten auf einmal misst, sagt beim Ausfall einer
        einzelnen nichts. Deshalb hier die Funktion selbst, mit einer Session
        als einfaches Wörterbuch.
        """
        from core.middleware_tenancy import _organisation_fuer
        dritte = self._mit_zwei_mitgliedschaften()

        # Fremde ID untergeschoben: muss ignoriert werden.
        ergebnis = _organisation_fuer(self.a.benutzer,
                                      {SESSION_SCHLUESSEL: self.b.organisation.id})
        self.assertNotEqual(
            ergebnis.id, self.b.organisation.id,
            'Die Middleware übernimmt einen Sessionwert, zu dem es keine '
            'Mitgliedschaft gibt. Damit hängt die gesamte Trennung allein an '
            'dem View, der den Wert setzt.')

        # Eigene ID: muss wirken — sonst prüft die Zeile darüber nur, dass die
        # Funktion den Wert grundsätzlich ignoriert.
        ergebnis = _organisation_fuer(self.a.benutzer,
                                      {SESSION_SCHLUESSEL: dritte.id})
        self.assertEqual(ergebnis.id, dritte.id,
                         'Die Middleware ignoriert auch den eigenen Mandanten.')

    def test_die_gegenprobe_zur_zweiten_schicht(self):
        """Ohne sie wäre der Test darüber auch dann grün, wenn die Middleware
        den Sessionwert grundsätzlich ignorierte.

        Ein EIGENER Mandant in der Session muss wirken — sonst prüft der Test
        oben nur, dass nie etwas gewechselt wird.
        """
        dritte = self._mit_zwei_mitgliedschaften()
        c = self._angemeldet()
        sitzung = c.session
        sitzung[SESSION_SCHLUESSEL] = dritte.id
        sitzung.save()

        html = c.get('/neu/').content.decode()
        self.assertIn(dritte.firma, html,
                      'Der eigene Mandant aus der Session wirkt nicht — die '
                      'Middleware liest den Wert gar nicht.')

    def test_unsinnige_eingaben_aendern_nichts(self):
        for wert in ('', '0', '-1', 'abc', '999999', None):
            with self.subTest(wert=wert):
                c = self._angemeldet()
                daten = {} if wert is None else {'organisation': wert}
                c.post('/neu/mandant/', daten)
                self.assertIsNone(
                    c.session.get(SESSION_SCHLUESSEL),
                    f'Die Eingabe {wert!r} hat etwas in der Session hinterlassen.')

    def test_der_eigene_mandant_wird_uebernommen(self):
        """Die Gegenprobe: Ohne sie wäre ein View, der NIE etwas setzt, grün."""
        c = self._angemeldet()
        c.post('/neu/mandant/', {'organisation': self.a.organisation.id})
        self.assertEqual(c.session.get(SESSION_SCHLUESSEL), self.a.organisation.id)

    def test_die_leiste_nennt_den_mandanten(self):
        """Wer für zwei Verwaltungen arbeitet, muss sehen, in welcher er steht."""
        html = self._angemeldet().get('/neu/').content.decode()
        self.assertIn(self.a.organisation.firma, html,
                      'Der Name des aktiven Mandanten steht nirgends auf der Seite.')
        self.assertNotIn(self.b.organisation.firma, html,
                         'Die Leiste nennt eine Organisation, in der diese Person '
                         'nicht Mitglied ist.')

    def test_ohne_anmeldung_kein_wechsel(self):
        antwort = Client().post('/neu/mandant/',
                                {'organisation': self.a.organisation.id})
        self.assertIn(antwort.status_code, (302, 403))
        self.assertNotEqual(
            Client().session.get(SESSION_SCHLUESSEL), self.a.organisation.id)
