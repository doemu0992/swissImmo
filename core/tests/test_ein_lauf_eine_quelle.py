"""Ein Lauf hat eine Quelle — und steht nicht zweimal auf einem Bildschirm.

DER BEFUND (B3 aus `docs/UX-ANALYSE-V7.md`)

»Drei Bildschirmaussagen zu denselben drei Läufen«, gemessen an einer echten
Installation am selben Tag:

    Heute      «Sollstellung 08/2026 ausführen»        aus `faelle.Lauf`
    Finanzen   «Sollstellung Miete 08/2026 gebucht»    aus `DebitorenRechnung`
    Läufe      «Sollstellung 2026-08»                  aus `faelle.Lauf`

Und der Zahllauf stand zweimal auf **derselben** Seite: als Aufgabe im
Arbeitskorb, als Zeile im Monatsabschluss darunter.

Die Analyse nennt die Wirkung: »Für eine Buchhalterin ist das ein
Vertrauensbruch; ein 10k-Werkzeug darf sich nicht widersprechen.«

WARUM ZWEI DARSTELLUNGEN RICHTIG SIND, ZWEI QUELLEN ABER NICHT

Der Plan gibt der Buchhaltung einen eigenen Ablauf: »Läufe« ist ein eigener
Bereich mit dem Rahmen *Betroffene → Berechnen → Prüfen*. »Heute« führt laut
Plan »Läufe-**Fristen**« — die Frist, nicht den Lauf. Beides nebeneinander ist
gewollt.

Falsch war die zweite QUELLE. Die alte Ampel erriet den Zustand aus einem
Titelmuster (`f"Miete & NK {m:02d}/{j}"`) — eine Regel als Zeichenkette, und
G7 verlangt Regeln als Daten. Sie konnte nur »gibt es solche Rechnungen?«
beantworten, nicht »abgeschlossen von wem, und was blockiert«.

WAS DIESER TEST PRÜFT

Dass die Läufe im Finanz-Cockpit aus `faelle.Lauf` kommen und nicht aus einem
Titelmuster — und dass derselbe Lauf nicht zweimal auf einer Seite steht.
"""
import re

from django.test import Client, TestCase

from ._helfer import _team_user


class EineQuelleTest(TestCase):
    """Am Quelltext — die Regel gilt auch ohne Daten."""

    def _dashboard(self):
        import inspect

        from core.views.fw import dashboard
        return inspect.getsource(dashboard)

    def test_der_periodenabschluss_liest_die_laeufe(self):
        quelle = self._dashboard()
        self.assertIn(
            'from faelle.lauf_models import Lauf', quelle,
            'Das Cockpit liest die Läufe nicht mehr aus `faelle.Lauf` — dann '
            'errät es ihren Zustand wieder.')

    def test_kein_titelmuster_mehr(self):
        """Die Regel als Zeichenkette darf nicht zurückkommen.

        `filter(titel=f"Miete & NK …")` war die alte Ampel: Sie schloss aus
        der Existenz von Rechnungen auf den Lauf. Das ist keine Regel, das
        ist ein Indiz.
        """
        quelle = self._dashboard()
        # Der Erklärtext nennt das alte Muster — geprüft wird der Code.
        ohne_kommentar = re.sub(r'^\s*#.*$', '', quelle, flags=re.M)
        ohne_kommentar = re.sub(r'"""(?:[^"]|"(?!""))*"""', '', ohne_kommentar,
                                flags=re.S)
        self.assertNotIn(
            'Miete & NK', ohne_kommentar,
            'Das Titelmuster ist zurück. Der Zustand eines Laufs steht in '
            '`Lauf.status`, nicht in den Titeln der Rechnungen, die er '
            'erzeugt hat.')

    def test_der_zahllauf_steht_nicht_im_arbeitskorb(self):
        """Er ist ein Lauf und stand doppelt auf derselben Seite."""
        quelle = self._dashboard()
        korb = quelle[quelle.index('_korb = ['):quelle.index('offene_posten =')]
        self.assertNotIn(
            "'zahllauf'", korb,
            'Der Zahllauf steht wieder im Arbeitskorb — und damit zweimal auf '
            'einer Seite, denn der Periodenabschluss darunter führt ihn '
            'ebenfalls.')


#: Korb-Eintraege, die auf DASSELBE Ziel zeigen wie ein Lauf im
#: Periodenabschluss — und trotzdem stehenbleiben durften.
#:
#: E2.29 hat den Zahllauf aus dem Korb genommen, weil er zweimal auf der Seite
#: stand. Beim Nachmessen zeigte sich: Es waren DREI solche Paare, und die
#: Regel ist auf eines angewendet worden.
#:
#:     Korb «Zahlungseingaenge abgleichen» -> /neu/bankabgleich/
#:     Lauf «Bankabgleich»                 -> /neu/bankabgleich/   IDENTISCH
#:
#:     Korb «Ueberfaellige Forderungen mahnen» -> /neu/mahnwesen/
#:     Lauf «Mahnlauf»                         -> /neu/mahnwesen/  IDENTISCH
#:
#: Der entfernte Zahllauf zeigte dagegen auf `/neu/kreditoren/`, die Laufart
#: auf `/neu/zahllauf/` — die beiden Eintraege, die WIRKLICH auf dieselbe
#: Seite fuehren, stehen also noch.
#:
#: Sie stehen hier als benannte Ausnahme statt still: Ob sie wandern sollen,
#: ist eine fachliche Entscheidung. Der Korb zeigt Anzahl und CHF-Summe, der
#: Abschluss Status und Blockade — beim Wandern geht das Erste verloren. Wer
#: entscheidet, streicht die Zeile hier und verschiebt den Eintrag.
DOPPELT_UND_GEDULDET = {
    '/neu/bankabgleich/': 'bank / bankabgleich',
    '/neu/mahnwesen/': 'mahnen / mahnlauf',
}


class KeineDoppelungAufEinerSeiteTest(TestCase):
    """Die ganze Kette, mit echten Läufen."""

    def setUp(self):
        from django.core.management import call_command
        self.benutzer = _team_user()
        call_command('laeufe_planen', verbosity=0)

    def _antwort(self):
        c = Client()
        c.force_login(self.benutzer)
        return c.get('/neu/finanzen/')

    def test_kein_korb_eintrag_zeigt_aufs_gleiche_ziel_wie_ein_lauf(self):
        """Der Fall, der gemessen wurde — geprüft am ZIEL, nicht am Wort.

        WARUM NICHT AM TEXT

        Die erste Fassung zählte, wie oft `Laufart.bezeichnung` auf der Seite
        steht. Nachgemessen ist das wirkungslos: Gegen den Stand VOR E2.29,
        auf dem der Zahllauf nachweislich zweimal stand («Zahllauf» 2× im
        `<main>`), blieb sie **grün**. Die Laufart heisst «Zahllauf
        Kreditoren», der Korb sagte «Zahllauf ausführen» — dieselbe Sache,
        andere Worte. Eine Textzählung findet nur die wörtliche Wiederholung,
        und die ist der harmloseste Fall.

        Was eine Doppelung wirklich ausmacht, ist das ZIEL: Zwei Einträge, die
        denselben Bildschirm öffnen, sind derselbe Vorgang — gleich wie sie
        beschriftet sind.
        """
        from faelle.lauf_models import Lauf

        antwort = self._antwort()
        korb_ziele = {i['url'].split('?')[0]: i['titel']
                      for i in antwort.context['arbeitskorb']}
        lauf_ziele = {}
        for lauf in Lauf.objects.select_related('laufart'):
            from django.urls import reverse
            try:
                lauf_ziele[reverse(lauf.laufart.ziel_ansicht)] = lauf.laufart.bezeichnung
            except Exception:      # Ansicht (noch) nicht verdrahtet
                continue

        doppelt = []
        for ziel, korb_titel in korb_ziele.items():
            if ziel in lauf_ziele and ziel not in DOPPELT_UND_GEDULDET:
                doppelt.append(f'{ziel}: «{korb_titel}» und Lauf '
                               f'«{lauf_ziele[ziel]}»')

        self.assertEqual(
            doppelt, [],
            'Diese Einträge stehen zweimal auf der Finanzseite — einmal im '
            'Korb, einmal im Periodenabschluss, und beide öffnen dieselbe '
            'Seite:\n  ' + '\n  '.join(doppelt)
            + '\n\n4b.5: Die Blöcke wandern, sie werden nicht kopiert. '
              'Entweder der Eintrag wandert in den Abschluss, oder er kommt '
              'mit Begründung in DOPPELT_UND_GEDULDET.')

    def test_die_geduldeten_doppelungen_gibt_es_wirklich_noch(self):
        """Eine Ausnahmeliste, die ins Leere zeigt, ist Ballast.

        Wandert einer der beiden Einträge doch noch, soll die Zeile hier
        auffallen und verschwinden — sonst steht in fünf Etappen eine
        Begründung für etwas, das es nicht mehr gibt.
        """
        korb_ziele = {i['url'].split('?')[0]
                      for i in self._antwort().context['arbeitskorb']}
        veraltet = sorted(z for z in DOPPELT_UND_GEDULDET
                          if z not in korb_ziele)
        self.assertEqual(
            veraltet, [],
            f'Diese Ziele stehen nicht mehr im Korb: {veraltet}. Die Zeilen '
            'in DOPPELT_UND_GEDULDET gehören weg.')

    def test_die_pruefung_findet_ueberhaupt_laeufe(self):
        """Sonst prüfte der Test darüber eine leere Menge.

        `laeufe_planen` legt sechs Laufarten an; für den laufenden Monat
        entstehen daraus vier Läufe (MWST ist quartalsweise, die
        Nebenkostenabrechnung jährlich). Erscheint keiner davon, ist die
        Prüfung oben trivial erfüllt.
        """
        from faelle.lauf_models import Lauf

        self.assertGreater(
            Lauf.objects.count(), 0,
            '`laeufe_planen` hat keine Läufe angelegt — dann belegt der Test '
            'darüber nichts.')
        zeilen = self._antwort().context['checkliste']
        self.assertTrue(
            zeilen,
            'Der Periodenabschluss ist leer, obwohl Läufe fällig sind — dann '
            'kann dort auch nichts doppelt stehen.')
