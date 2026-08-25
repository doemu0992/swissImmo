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
#: LEER SEIT E2.30 — und das war keine Ermessensfrage.
#:
#: Der Plan sagt zur Zeile «Finanzen»: «Register und Konten. HANDLUNGEN
#: (abgleichen, mahnen, zahlen) SPRINGEN IN DEN ZUGEHOERIGEN LAUF.» Alle drei
#: genannten Handlungen. Die Duldung war also nachzuholende Umsetzung, keine
#: offene Entscheidung.
#:
#: Der befuerchtete Verlust ist keiner: Anzahl und CHF-Summe stehen jetzt in
#: der Abschlusszeile, am selben Ort wie Status und Blockade. Sie gehen nicht
#: verloren — sie stehen nur nicht mehr an zwei Orten.
DOPPELT_UND_GEDULDET = {}


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

    def test_jede_abschlusszeile_verweist_auf_eine_echte_seite(self):
        """Der Fehler, den kein Test gefunden hat — nur das Nachsehen.

        E2.30 hat den Verweis der Abschlusszeile von der Laufliste auf die
        jeweilige Ansicht umgestellt und dafuer `Laufart.ziel_ansicht`
        genommen. Das Feld traegt aber den NAMEN einer View, nicht ihre
        Adresse — es sagt das selbst: «Name der bestehenden View, die den
        Lauf tatsaechlich ausfuehrt».

        Im HTML stand danach `href="fw_bankabgleich"`. Der Browser loest das
        relativ auf und landet auf `/neu/fw_bankabgleich` — ein 404 auf
        JEDER Zeile des Periodenabschlusses.

        Gefunden hat es keine Pruefung: Ein Verweis ins Leere sieht im HTML
        aus wie einer, der funktioniert, und die Etappe meldete «im Browser
        geprueft». Deshalb wird hier jede Adresse tatsaechlich AUFGERUFEN.
        """
        antwort = self._antwort()
        zeilen = antwort.context['checkliste']
        self.assertTrue(zeilen, 'Kein Periodenabschluss — nichts zu pruefen.')

        c = Client()
        c.force_login(self.benutzer)
        kaputt = []
        for zeile in zeilen:
            url = zeile['url']
            if not url.startswith('/'):
                kaputt.append(f'{zeile["titel"]}: «{url}» ist keine Adresse')
                continue
            code = c.get(url).status_code
            if code >= 400:
                kaputt.append(f'{zeile["titel"]}: {url} -> {code}')

        self.assertEqual(
            kaputt, [],
            'Diese Zeilen des Periodenabschlusses fuehren ins Leere:\n  '
            + '\n  '.join(kaputt)
            + '\n\n`Laufart.ziel_ansicht` ist ein View-NAME; er gehoert '
              'durch `reverse()`, bevor er in ein `href` kommt.')

    def test_dringend_ist_wer_den_stichtag_ueberschritten_hat(self):
        """Die Regel, die E2.30 eingefuehrt hat — und die keinen Test hatte.

        Bis dahin hing «dringend» an den Korb-Eintraegen: `bool(deb_ueberf)`
        — es GIBT ueberfaellige Forderungen. Mit dem Wandern der Eintraege
        waere die Aussage verschwunden; jetzt haengt sie am Lauf und ist
        genauer: nicht «es gibt Ueberfaellige» (ein Zustand), sondern «der
        Mahnlauf haette am 15. laufen sollen» (eine Handlung).

        Die Regel lautet: dringend ist ein Lauf, der nicht abgeschlossen ist
        UND dessen Stichtag ueberschritten ist ODER der blockiert ist.
        Geprueft werden alle drei Teile — eine Regel mit drei Bedingungen,
        von der nur eine stimmt, ist keine.
        """
        from datetime import timedelta

        from django.utils import timezone
        from faelle.lauf_models import Lauf

        heute = timezone.localdate()
        lauf = Lauf.objects.order_by('id').first()
        self.assertIsNotNone(lauf, 'Kein Lauf angelegt.')

        def _zeile():
            titel = f'{lauf.laufart.bezeichnung} {lauf.periode}'
            treffer = [z for z in self._antwort().context['checkliste']
                       if z['titel'] == titel]
            self.assertTrue(treffer, f'«{titel}» fehlt im Abschluss.')
            return treffer[0]

        # 1. Stichtag ueberschritten, offen -> dringend
        Lauf.objects.filter(id=lauf.id).update(
            faellig_am=heute - timedelta(days=1), status=Lauf.OFFEN)
        self.assertTrue(
            _zeile()['dringend'],
            'Ein offener Lauf mit ueberschrittenem Stichtag gilt nicht als '
            'dringend — dann meldet der Kopf nie etwas.')

        # 2. Stichtag heute, offen -> nicht dringend
        #    «ueberschritten» heisst vorbei, nicht erreicht. Waere schon der
        #    Stichtag selbst dringend, staende jeder Lauf am Faelligkeitstag
        #    in Rot, bevor jemand ihn ueberhaupt starten konnte.
        Lauf.objects.filter(id=lauf.id).update(faellig_am=heute)
        self.assertFalse(
            _zeile()['dringend'],
            'Am Stichtag selbst ist der Lauf schon dringend — die Grenze '
            'liegt einen Tag zu frueh.')

        # 3. Abgeschlossen, Stichtag laengst vorbei -> nicht dringend
        Lauf.objects.filter(id=lauf.id).update(
            faellig_am=heute - timedelta(days=30),
            status=Lauf.ABGESCHLOSSEN, abgeschlossen_am=timezone.now())
        self.assertFalse(
            _zeile()['dringend'],
            'Ein abgeschlossener Lauf gilt weiter als dringend — dann wird '
            'die Zahl im Kopf nie kleiner.')

    def test_eine_blockade_macht_den_lauf_am_stichtag_dringend(self):
        """Der zweite Teil der Regel — und wie weit er reicht.

        `dringend` ist `bool(blockaden) or faellig_am < heute`. Der zweite
        Teil traegt fast alles: Der Abschluss zeigt nur Laeufe mit
        `faellig_am <= heute`, also ist «Stichtag ueberschritten» in aller
        Regel schon erfuellt, bevor die Blockade gefragt wird.

        Es bleibt genau ein Tag, an dem die Blockade den Unterschied macht:
        der Stichtag selbst. Der wird hier geprueft — sonst waere der Zweig
        ungeprueft und niemand merkte sein Verschwinden.

        WAS DAMIT NICHT ERREICHT IST

        Eine Blockade VOR dem Stichtag erreicht das Cockpit gar nicht: Der
        Lauf steht dann noch nicht im Abschluss. Wer auf die
        Verbrauchsablesung wartet, erfaehrt davon frühestens am
        Faelligkeitstag — also zu spaet, um noch etwas zu bewirken.

        Das ist eine bewusste Entscheidung aus E2.29 («der Abschluss einer
        Periode ist erst dann eine Aufgabe») und keine Panne. Aber es steht
        im Widerspruch zu dem, wofuer `Lauf` gebaut wurde: Die alte Ampel
        zeigte ein rotes Haekchen, der Lauf soll «Verbrauchsablesung Techem
        fehlt» zeigen — und das nuetzt vorher mehr als nachher. Gemeldet,
        nicht nebenbei geaendert.
        """
        from django.utils import timezone
        from faelle.lauf_models import Lauf

        lauf = Lauf.objects.order_by('id').first()
        Lauf.objects.filter(id=lauf.id).update(
            faellig_am=timezone.localdate(), status=Lauf.OFFEN)
        titel = f'{lauf.laufart.bezeichnung} {lauf.periode}'

        def _zeile():
            treffer = [z for z in self._antwort().context['checkliste']
                       if z['titel'] == titel]
            self.assertTrue(treffer, f'«{titel}» fehlt im Abschluss.')
            return treffer[0]

        self.assertFalse(
            _zeile()['dringend'],
            'Am Stichtag ohne Blockade darf nichts dringend sein — sonst '
            'zeigt die Pruefung unten nichts.')

        lauf.blockaden.create(grund='Verbrauchsablesung Techem fehlt')

        zeile = _zeile()
        self.assertTrue(
            zeile['dringend'],
            'Ein blockierter Lauf gilt am Stichtag nicht als dringend — dann '
            'ist der Blockade-Zweig der Regel wirkungslos.')
        self.assertIn(
            'Techem', zeile['hinweis'],
            'Der Grund der Blockade steht nicht in der Zeile. Genau das ist '
            'der Unterschied zur alten Ampel: ein rotes Haekchen fuehrt zu '
            'einer Rueckfrage, ein Grund zu einer Handlung.')

    def test_ein_lauf_vor_seinem_stichtag_steht_noch_nicht_im_abschluss(self):
        """Die Grenze der Ansicht, ausdruecklich festgehalten.

        Nicht als Mangel, sondern damit die Regel oben lesbar bleibt: Wer
        sich fragt, warum die Blockade nur am Stichtag zaehlt, findet hier
        den Grund.
        """
        from datetime import timedelta

        from django.utils import timezone
        from faelle.lauf_models import Lauf

        lauf = Lauf.objects.order_by('id').first()
        Lauf.objects.filter(id=lauf.id).update(
            faellig_am=timezone.localdate() + timedelta(days=5),
            status=Lauf.OFFEN)
        lauf.refresh_from_db()
        lauf.blockaden.create(grund='Verbrauchsablesung Techem fehlt')

        titel = f'{lauf.laufart.bezeichnung} {lauf.periode}'
        titel_im_abschluss = [z['titel'] for z in
                              self._antwort().context['checkliste']]
        self.assertNotIn(
            titel, titel_im_abschluss,
            'Ein Lauf vor seinem Stichtag steht jetzt im Abschluss — dann '
            'ist die Erklaerung in der Regel darueber veraltet, und die '
            'Blockade traegt mehr als dort steht.')

    def test_die_kopfzeile_widerspricht_dem_inhalt_nicht(self):
        """Der Widerspruch, den E2.30 gefunden UND behoben hat — ungeprueft.

        Nach dem Wandern der Korb-Eintraege meldete die Kopfzeile «0 offene
        Aufgaben · 3 dringend», darunter stand «Alle Finanzaufgaben erledigt
        — nichts offen», und rechts standen drei ueberfaellige Laeufe.
        `offene_posten` zaehlte nur den Korb.

        Die Etappe schreibt selbst: «Was die Sichtpruefung gefunden hat — und
        kein Test». Nachgemessen stimmte das auch nach der Behebung: Wird die
        Zaehlung wieder auf den Korb allein zurueckgestellt, bleibt die Suite
        gruen. Ein behobener Widerspruch ohne Pruefung kommt beim naechsten
        Umbau zurueck.

        Geprueft wird die Aussage, nicht die Rechnung: Was im Kopf steht, muss
        zu dem passen, was darunter zu sehen ist.
        """
        from faelle.lauf_models import Lauf

        # Zwei Laeufe ueberfaellig, damit es wirklich etwas zu zaehlen gibt.
        from datetime import timedelta

        from django.utils import timezone
        ids = list(Lauf.objects.order_by('id').values_list('id', flat=True)[:2])
        Lauf.objects.filter(id__in=ids).update(
            faellig_am=timezone.localdate() - timedelta(days=3),
            status=Lauf.OFFEN)

        antwort = self._antwort()
        offen_sichtbar = sum(1 for z in antwort.context['checkliste']
                             if z['ok'] is not True)
        offen_sichtbar += sum(1 for i in antwort.context['arbeitskorb']
                              if i['anzahl'])
        dringend_sichtbar = sum(1 for z in antwort.context['checkliste']
                                if z.get('dringend'))
        dringend_sichtbar += sum(1 for i in antwort.context['arbeitskorb']
                                 if i['dringend'])

        self.assertEqual(
            antwort.context['offene_posten'], offen_sichtbar,
            f'Der Kopf meldet {antwort.context["offene_posten"]} offene '
            f'Aufgaben, sichtbar sind {offen_sichtbar}. Die Zahl zaehlt eine '
            'der beiden Quellen nicht mit.')
        self.assertEqual(
            antwort.context['dringend_n'], dringend_sichtbar,
            f'Der Kopf meldet {antwort.context["dringend_n"]} dringend, '
            f'sichtbar sind {dringend_sichtbar}.')

        self.assertGreater(dringend_sichtbar, 0,
                           'Nichts ist dringend — dann prueft die Zeile '
                           'unten nichts.')
        self.assertNotIn(
            'Alle Finanzaufgaben erledigt', antwort.content.decode(),
            'Die Seite meldet «alles erledigt», waehrend darunter '
            f'{offen_sichtbar} offene Aufgaben stehen. Genau dieser '
            'Widerspruch auf einem Bildschirm ist B3 der Analyse: Ein '
            'Werkzeug darf sich nicht selbst widersprechen.')

    def test_die_erfolgsmeldung_erscheint_wenn_wirklich_nichts_offen_ist(self):
        """Die Gegenrichtung — sonst waere die Pruefung oben mit einer Seite
        zu bestehen, die die Meldung nie zeigt.
        """
        from django.utils import timezone
        from faelle.lauf_models import Lauf

        Lauf.objects.all().update(status=Lauf.ABGESCHLOSSEN,
                                  abgeschlossen_am=timezone.now())
        antwort = self._antwort()
        offen = sum(1 for z in antwort.context['checkliste']
                    if z['ok'] is not True)
        offen += sum(1 for i in antwort.context['arbeitskorb'] if i['anzahl'])
        self.assertEqual(offen, 0, 'Es ist noch etwas offen — dann sagt der '
                                   'Test nichts ueber die Erfolgsmeldung.')
        self.assertEqual(antwort.context['offene_posten'], 0)
        self.assertIn(
            'Alle Finanzaufgaben erledigt', antwort.content.decode(),
            'Die Erfolgsmeldung fehlt, obwohl nichts offen ist — dann ist '
            'sie unerreichbar geworden.')

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
