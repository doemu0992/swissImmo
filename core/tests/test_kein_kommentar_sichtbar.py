"""Kein Erklärtext darf auf der Seite landen.

WAS PASSIERT IST

Der Kopfkommentar von `fw/_schicht.html` stand als `/* … */` **vor** dem
`<style>`-Tag. Ausserhalb von CSS ist das kein Kommentar, sondern Text — der
Browser hat ihn oben auf jeder Seite ausgegeben:

    /* DIE KOMPONENTENSCHICHT — Tokens und `fw-*`-Bausteine. WARUM SIE SEIT
    E2.10 IN EINER EIGENEN DATEI STEHT Bis hierher lag sie im …

Sichtbar auch auf dem öffentlichen Ticketformular, das Mieter ohne Anmeldung
aufrufen.

WIE ES DAZU KAM

Eine Massenänderung und ihre Rücknahme. Erst wurden alle CSS-Kommentare in
Django-Kommentare umgewandelt (falsch — der schliessende Baustein enthält eine
geschweifte Klammer und zerschneidet `:root{…}` für die Wächter, die dort mit
einem Muster bis zum ersten `}` lesen). Dann alle zurück — und dabei auch
dieser eine, der von Anfang an richtig war.

DIE REGEL

Innerhalb von `<style>` gehören CSS-Kommentare hin, ausserhalb
Django-Kommentare. In einer Vorlage mit Stilblock braucht es beides, und die
Grenze verläuft am `<style>`-Tag.

WAS DIESER TEST PRÜFT

Er rendert die Hüllen und sucht im sichtbaren Text nach Kommentarzeichen. Nicht
im Quelltext — dort dürfen sie stehen —, sondern in dem, was ohne `<style>`,
`<script>` und Tags übrig bleibt. Genau das, was ein Besucher liest.
"""
import re

from django.test import Client, TestCase

#: Zeichenfolgen, die im sichtbaren Text einer Seite nichts zu suchen haben.
VERRAETER = ('/*', '*/', '{% comment', 'endcomment %}')

#: Seiten ohne Anmeldung — die, bei denen ein Fehler am teuersten ist.
#: Feste Pfade; die beiden Formulare mit ID stehen in `_mit_id` weiter unten,
#: weil sie eine Liegenschaft bzw. eine Einheit brauchen.
OEFFENTLICH = ('/schaden/melden/', '/login/')


def _sichtbarer_text(html):
    """Was ein Besucher liest: ohne Stil, ohne Skript, ohne Tags."""
    ohne = re.sub(r'<style.*?</style>|<script.*?</script>', ' ', html, flags=re.S)
    return re.sub(r'<[^>]+>', ' ', ohne)


class KeinKommentarAufDerSeiteTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        from core.tests._isolation import MandantenFixture
        cls.mandant = MandantenFixture('K', '8000', 'Zürich')
        cls.mandant.einheit.zur_ausschreibung = True   # sonst antwortet /bewerben/ mit 410
        cls.mandant.einheit.save()

    def _mit_id(self):
        """Die zwei öffentlichen Formulare, die eine ID im Pfad tragen.

        WARUM SIE NACHGETRAGEN WURDEN

        Die erste Fassung prüfte `/schaden/melden/` und `/login/`. Der Fehler,
        für den dieser Wächter geschrieben wurde, traf aber ausdrücklich auch
        das **öffentliche Ticketformular** — und genau das stand nicht in der
        Liste. Ein Wächter, der seinen eigenen Anlassfall nicht abdeckt, prüft
        die Nachbarschaft des Problems.
        """
        # Die Objekte der Fixture direkt nehmen: `Einheit.objects` wirft
        # ausserhalb einer Anfrage OrganisationsFehler — die Mandantentrennung
        # verlangt einen gesetzten Kontext, und das ist richtig so.
        e = self.mandant.einheit
        return [f'/report/{e.liegenschaft_id}/', f'/bewerben/{e.pk}/']

    def test_oeffentliche_seiten_zeigen_keinen_erklaertext(self):
        c = Client()
        for pfad in list(OEFFENTLICH) + self._mit_id():
            antwort = c.get(pfad, follow=True)
            self.assertEqual(
                antwort.status_code, 200,
                f'{pfad} antwortet {antwort.status_code}. Früher wurde das '
                f'stillschweigend übersprungen — ein Wächter, dessen Seite '
                f'verschwindet, meldet dann nichts mehr und sieht aus wie '
                f'bestanden.')
            text = _sichtbarer_text(antwort.content.decode())
            for zeichen in VERRAETER:
                with self.subTest(pfad=pfad, zeichen=zeichen):
                    self.assertNotIn(
                        zeichen, text,
                        f'Auf {pfad} steht Erklärtext im sichtbaren Bereich. '
                        f'Ein Kommentar vor dem `<style>`-Tag ist kein '
                        f'Kommentar — er wird ausgegeben.')

    def test_die_pruefung_greift_ueberhaupt(self):
        """Gegenprobe: Der Filter darf nicht alles wegwerfen.

        Ohne diesen Test wäre die Prüfung oben grün, wenn
        `_sichtbarer_text()` versehentlich eine leere Zeichenkette liefert —
        die teuerste Art von grün.
        """
        beispiel = ('<html><style>/* unsichtbar */</style>'
                    '<body>Hallo /* sichtbar */ Welt</body></html>')
        text = _sichtbarer_text(beispiel)
        self.assertIn('Hallo', text)
        self.assertIn('/* sichtbar */', text,
                      'Der Filter findet Kommentarzeichen im Text nicht mehr.')
        self.assertNotIn('unsichtbar', text,
                         'Der Filter behält den Inhalt von <style> — dann '
                         'meldet er jeden CSS-Kommentar als Fehler.')

    def test_auch_die_angemeldete_oberflaeche(self):
        """Dieselbe Datei liegt in beiden Hüllen — beide prüfen."""
        from core.tests._helfer import _team_user
        c = Client()
        c.force_login(_team_user())
        text = _sichtbarer_text(c.get('/neu/').content.decode())
        for zeichen in VERRAETER:
            with self.subTest(zeichen=zeichen):
                self.assertNotIn(zeichen, text)
