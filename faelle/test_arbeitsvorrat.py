"""Tests des Arbeitsvorrats und der Seiten, auf denen Phase 4a sichtbar wird.

WARUM DIESE TESTS SCHARF SEIN MÜSSEN

Der Arbeitsvorrat ist die erste Oberfläche, auf der `Fall`, `Eingang` und
`Lauf` überhaupt erscheinen. Bis hierher hatten sie **keine einzige View** —
vollständig getestet und für niemanden erreichbar. Ein grüner Modelltest sagt
nichts darüber, ob ein Mensch die Sache je zu Gesicht bekommt.

Die gefährlichste Fehlerart ist hier nicht der Absturz, sondern die **stille
Leere**: Ein Abschnitt, der nichts anzeigt, sieht aus wie ein ruhiger Tag.
Beim Bauen ist genau das beinahe passiert — ein Entwurf griff auf `faellig_am`
zu, das Feld heisst `frist`; der `except`-Zweig hätte den Fehler geschluckt.

Deshalb prüft jeder Test hier, dass etwas **erscheint**, und mindestens einer
je Quelle, dass es bei fehlendem Anlass **verschwindet**.
"""
from datetime import timedelta

from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.arbeitsvorrat import (VORSCHAU_TAGE, arbeitsvorrat, posteingang,
                                  was_reisst)
from faelle.lauf_models import Lauf, Laufart
from faelle.models import Fall, Fallart, SchrittVorlage
from faelle.zulauf_models import Eingang, Zuordnungsregel, normalisieren


def _fallart(org, schluessel='arbeitsvorrat'):
    art = Fallart(organisation=org, schluessel=schluessel, bezeichnung='Prüfung')
    art.save()
    SchrittVorlage(fallart=art, nr=1, etappe_nr=1, etappe='E',
                   bezeichnung='Antwort verfassen').save()
    return art


def _fall_mit_frist(org, tage, betreff='Kündigung Blaser'):
    art = _fallart(org, f'av{tage}{betreff[:4]}')
    fall = Fall(organisation=org, fallart=art, akte=None, betreff=betreff)
    fall.save()
    fall.schritte_anlegen()
    s = fall.schritte.first()
    s.frist = timezone.localdate() + timedelta(days=tage)
    s.save()
    return fall, s


def _laeufe_echt():
    """Die echte Lauf-Quelle aus der Tabelle — nicht der private Name."""
    from faelle.arbeitsvorrat import QUELLEN
    return next(f for name, f, _lg in QUELLEN if name == 'Läufe')


def _lauf(org, tage_ueberfaellig, schluessel='mahnlauf'):
    art = Laufart(organisation=org, schluessel=schluessel, bezeichnung='Mahnlauf')
    art.save()
    lauf = Lauf(organisation=org, laufart=art, periode='2026-08',
                faellig_am=timezone.localdate() - timedelta(days=tage_ueberfaellig))
    lauf.save()
    return lauf


class WasReisstTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_ueberfaelliger_fallschritt_erscheint(self):
        """Der Test, der den Feldfehler gefunden hätte.

        SEIT E2.66 IST DER TITEL DER FALL, NICHT DER SCHRITT.

        Vorher stand hier `schritt.bezeichnung`. Konzept v7 zeigt in der
        Vorratszeile den FALL oben («Bahnhofstrasse 12, 3.2 — Blaser») und den
        Schritt darunter — und das ist die richtige Reihenfolge: Wer den
        Vorrat überfliegt, sucht den Fall. Bei zwanzig Zeilen mit «Prüfen»,
        «Nachfassen», «Freigeben» als Überschrift findet man nichts wieder.

        Der Schrittname ist deshalb nicht verschwunden, sondern in `schritt`
        gewandert und steht in der Zeile darunter. Beides wird hier geprüft,
        damit die Umstellung nicht zum Verlust wird.
        """
        with mandant(self.a.organisation):
            fall, schritt = _fall_mit_frist(self.a.organisation, -3)
            treffer = [e for e in was_reisst() if e['art'] == 'fall']
            self.assertEqual(len(treffer), 1)
            self.assertEqual(
                treffer[0]['titel'], fall.betreff or fall.fallart.bezeichnung,
                'Der Titel ist nicht der Fall — dann sucht man in der Liste '
                'nach Schrittnamen statt nach Fällen.')
            self.assertEqual(
                treffer[0]['schritt'], schritt.bezeichnung,
                'Der Schrittname fehlt ganz — die Umstellung hätte ihn '
                'verloren statt verschoben.')
            self.assertEqual(treffer[0]['tage'], -3)
            self.assertEqual(treffer[0]['dringlichkeit'], 'crit')

    def test_schritt_ohne_frist_erscheint_nicht(self):
        """Ein Schritt ohne Frist reisst nichts — er ist Bestand."""
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation)
            fall = Fall(organisation=self.a.organisation, fallart=art, akte=None)
            fall.save()
            fall.schritte_anlegen()
            self.assertEqual([e for e in was_reisst() if e['art'] == 'fall'], [])

    def test_erledigter_schritt_erscheint_nicht(self):
        with mandant(self.a.organisation):
            _fall, schritt = _fall_mit_frist(self.a.organisation, -3)
            schritt.erledigen()
            self.assertEqual([e for e in was_reisst() if e['art'] == 'fall'], [])

    def test_frist_jenseits_der_vorschau_erscheint_nicht(self):
        with mandant(self.a.organisation):
            _fall_mit_frist(self.a.organisation, VORSCHAU_TAGE + 5)
            self.assertEqual([e for e in was_reisst() if e['art'] == 'fall'], [])

    def test_nicht_ausgeloester_lauf_erscheint(self):
        with mandant(self.a.organisation):
            _lauf(self.a.organisation, tage_ueberfaellig=4)
            treffer = [e for e in was_reisst() if e['art'] == 'lauf']
            self.assertEqual(len(treffer), 1)
            self.assertIn('nicht ausgelöst', treffer[0]['titel'])

    def test_blockade_wird_als_grund_gezeigt_nicht_als_wort_blockiert(self):
        """«Verbrauchsablesung fehlt» führt zu einer Handlung, «blockiert» nicht."""
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, tage_ueberfaellig=2)
            lauf.blockieren('Verbrauchsablesung Techem fehlt')
            treffer = [e for e in was_reisst() if e['art'] == 'lauf'][0]
            self.assertIn('Verbrauchsablesung', treffer['zeile'])
            self.assertNotIn('blockiert', treffer['zeile'])
            self.assertEqual(treffer['dringlichkeit'], 'crit')

    def test_abgeschlossener_lauf_erscheint_nicht(self):
        with mandant(self.a.organisation):
            _lauf(self.a.organisation, tage_ueberfaellig=9).abschliessen()
            self.assertEqual([e for e in was_reisst() if e['art'] == 'lauf'], [])

    def test_pendenz_behaelt_ihr_ziel(self):
        """Die 257d-Pendenz muss weiter zur Zugangserfassung führen.

        Sie ist aus der Inbox in den Arbeitsvorrat gewandert. Käme sie hier
        ohne Ziel an, wäre aus einer Umstellung der Anzeige ein
        Funktionsverlust geworden — genau der Fehler, der beim Aktenkopf-Umbau
        dreimal passiert ist.
        """
        from core.models import Pendenz
        with mandant(self.a.organisation):
            Pendenz(organisation=self.a.organisation, titel='Zahlungsfrist 257d',
                    vertrag=self.a.vertrag, kategorie='frist',
                    faellig_am=timezone.localdate() + timedelta(days=2)).save()
            treffer = [e for e in was_reisst() if e['titel'] == 'Zahlungsfrist 257d']
            self.assertEqual(len(treffer), 1)
            self.assertIn(str(self.a.vertrag.id), treffer[0]['ziel'])

    def test_sortierung_nach_faelligkeit(self):
        with mandant(self.a.organisation):
            _fall_mit_frist(self.a.organisation, 5, 'Spaet')
            _fall_mit_frist(self.a.organisation, -2, 'Frueh')
            _lauf(self.a.organisation, tage_ueberfaellig=1)
            daten = [e['datum'] for e in was_reisst()]
            self.assertEqual(daten, sorted(daten))

    def test_dringlichkeit_stuft_ab(self):
        with mandant(self.a.organisation):
            _fall_mit_frist(self.a.organisation, -1, 'Eins')
            _fall_mit_frist(self.a.organisation, 2, 'Zwei')
            _fall_mit_frist(self.a.organisation, 9, 'Neun')
            stufen = {e['tage']: e['dringlichkeit']
                      for e in was_reisst() if e['art'] == 'fall'}
            self.assertEqual(stufen[-1], 'crit')
            self.assertEqual(stufen[2], 'warn')
            self.assertEqual(stufen[9], 'neutral')

    def test_jeder_eintrag_fuehrt_zu_einem_ziel(self):
        """Eine Zeile ohne Ziel ist eine Meldung, keine Arbeit."""
        with mandant(self.a.organisation):
            _fall_mit_frist(self.a.organisation, -1)
            _lauf(self.a.organisation, tage_ueberfaellig=3)
            eintraege = was_reisst()
            self.assertTrue(eintraege)
            for e in eintraege:
                with self.subTest(titel=e['titel']):
                    self.assertTrue(e['ziel'] and e['knopf'])

    def test_eine_kaputte_quelle_nimmt_die_seite_nicht_mit(self):
        """Und sie verschwindet nicht stillschweigend.

        Ein stummer `except` ist in diesem Haus verboten (Befund P6). Hier
        wäre er zusätzlich heimtückisch: Eine leere Liste sieht aus wie ein
        ruhiger Tag.

        Die erste Fassung dieses Tests ersetzte `arbeitsvorrat._fallschritte`
        per `patch`. Das wirkte nicht: `QUELLEN` ist eine Tabelle am
        Modulkopf und hat das Funktionsobjekt beim Import GEFANGEN — den
        Namen zu überschreiben ändert an der Tabelle nichts. Der Test war
        rot und hatte recht. Jetzt wird die Tabelle selbst ersetzt; damit
        prüft er die echte Schleife.
        """
        from unittest.mock import patch

        def kaputt(heute, bis):
            raise RuntimeError('kaputt')

        with mandant(self.a.organisation):
            _lauf(self.a.organisation, tage_ueberfaellig=2)
            tabelle = (('Läufe', _laeufe_echt(), False), ('Fälle', kaputt, False))
            with patch('faelle.arbeitsvorrat.QUELLEN', tabelle):
                with self.assertLogs('faelle.arbeitsvorrat', level='ERROR') as log:
                    eintraege = was_reisst()
            self.assertTrue([e for e in eintraege if e['art'] == 'lauf'],
                            'Die heile Quelle muss die kaputte überleben.')
            self.assertIn('Fälle', '\n'.join(log.output))


class PosteingangTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_offener_eingang_erscheint(self):
        """Geprüft wird der KONKRETE Eingang, nicht die Gesamtzahl.

        Das Mandantenfixture bringt selbst Eingänge mit — eine Zählung wäre
        prompt falsch. Derselbe Fehler ist in den Etappen 4a.1, 4a.2 und 4a.4
        schon unterlaufen.
        """
        with mandant(self.a.organisation):
            e = Eingang(organisation=self.a.organisation, quelle=Eingang.MAIL,
                        betreff='Heizung im Bad wieder kalt')
            e.save()
            zeilen, _gesamt = posteingang()
            self.assertIn(e.pk, [z['eingang'].pk for z in zeilen])

    def test_ohne_merkmal_kein_sicherer_vorschlag(self):
        """«Kein sicherer Vorschlag» ist nach Konzept 6 eine gültige Antwort."""
        with mandant(self.a.organisation):
            e = Eingang(organisation=self.a.organisation, quelle=Eingang.MAIL,
                        betreff='Offerte')
            e.save()
            zeile = next(z for z in posteingang()[0] if z['eingang'].pk == e.pk)
            self.assertFalse(zeile['sicher'])
            self.assertIn('von Hand', zeile['begruendung'])

    def test_gelernte_regel_liefert_einen_vorschlag(self):
        with mandant(self.a.organisation):
            Zuordnungsregel(organisation=self.a.organisation,
                            merkmal=Zuordnungsregel.REFERENZ,
                            wert=normalisieren('QR-4471'), wert_anzeige='QR-4471',
                            akte=self.a.vertrag).save()
            e = Eingang(organisation=self.a.organisation, quelle=Eingang.SCAN,
                        betreff='Rechnung', referenz='QR-4471')
            e.save()
            zeile = next(z for z in posteingang()[0] if z['eingang'].pk == e.pk)
            self.assertTrue(zeile['sicher'])
            self.assertEqual(zeile['ziel'], self.a.vertrag)

    def test_zugeordneter_eingang_verschwindet(self):
        with mandant(self.a.organisation):
            e = Eingang(organisation=self.a.organisation, quelle=Eingang.MAIL,
                        betreff='Erledigt')
            e.save()
            self.assertIn(e.pk, [z['eingang'].pk for z in posteingang()[0]])
            e.ablegen('Werbung')
            self.assertNotIn(e.pk, [z['eingang'].pk for z in posteingang()[0]])


class DoppelungTests(TestCase):
    """G2: «Ein Arbeitsvorrat, nicht zwei Listen.»

    Ein Entwurf stellte «Was reisst» NEBEN die bestehende Inbox. Beide
    sammelten einzelne Pendenzen im 14-Tage-Fenster — dieselbe Pendenz stand
    zweimal auf einem Bildschirm. Die Blöcke sind aus `core/services/inbox.py`
    in den Arbeitsvorrat gewandert; dieser Test hält fest, dass sie dort nicht
    wieder auftauchen.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_keine_doppelung_zwischen_inbox_und_vorrat(self):
        from core.models import Pendenz
        from core.services.inbox import sammle_inbox
        with mandant(self.a.organisation):
            Pendenz(organisation=self.a.organisation, titel='Einmalig sichtbar',
                    vertrag=self.a.vertrag, kategorie='frist',
                    faellig_am=timezone.localdate() + timedelta(days=3)).save()
            im_vorrat = [e['titel'] for e in was_reisst()]
            inbox, _mehr, _typen = sammle_inbox()
            in_inbox = [e['titel'] for e in inbox]
        self.assertIn('Einmalig sichtbar', im_vorrat)
        self.assertNotIn('Einmalig sichtbar', in_inbox,
                         'Die Pendenz steht zweimal auf der Startseite — genau '
                         'das verbietet G2.')

    def test_aufgabe_ohne_frist_geht_nicht_verloren(self):
        """Sie reisst nichts, darf aber auch nicht verschwinden.

        Beim Umbau wäre sie es zweimal beinahe: Der Arbeitsvorrat nimmt nur
        datierte Vorgänge, und der alte Inbox-Block, der sie führte, ist
        entfernt. Sie steht jetzt als Sammelposten in der Inbox.

        DIESER TEST WAR ZU SCHWACH. Er prüfte nur, dass `sammle_inbox()` den
        Sammelposten LIEFERT — nicht, dass ihn jemand SIEHT. Beim
        Zusammenlegen der beiden Startflächen am 21.08.2026 führte der Entwurf
        für die neue Seite die Inbox nicht mehr, und nichts anderes rendert
        sie. Der Test wäre grün geblieben, während die undatierten Aufgaben
        aus der Anwendung verschwunden wären. Er prüft jetzt beides: die
        Funktion UND die Seite.
        """
        from core.models import Pendenz
        from core.services.inbox import sammle_inbox
        with mandant(self.a.organisation):
            Pendenz(organisation=self.a.organisation, titel='Irgendwann mal',
                    vertrag=self.a.vertrag, faellig_am=None).save()
            inbox, _mehr, _typen = sammle_inbox()
            self.assertTrue(any('ohne Frist' in e['titel'] for e in inbox),
                            'Undatierte Aufgaben tauchen nirgends mehr auf.')

            c = Client()
            c.force_login(self.a.benutzer)
            inhalt = c.get('/neu/').content.decode()
        self.assertIn('ohne Frist', inhalt,
                      'Der Sammelposten wird berechnet, aber von keiner Seite '
                      'angezeigt — fuer den Benutzer ist er damit weg.')


class MandantentrennungTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        with mandant(self.a.organisation):
            self.fall_a, _s = _fall_mit_frist(self.a.organisation, -5)
            self.eingang_a = Eingang(organisation=self.a.organisation,
                                     quelle=Eingang.MAIL, betreff='Nur für A')
            self.eingang_a.save()
            _lauf(self.a.organisation, tage_ueberfaellig=6, schluessel='mahnlauf_a')

    def test_b_sieht_nichts_von_a(self):
        with mandant(self.b.organisation):
            titel = [e['titel'] for e in was_reisst()]
            self.assertNotIn('Antwort verfassen', titel)
            self.assertNotIn(self.eingang_a.pk,
                             [z['eingang'].pk for z in posteingang()[0]])

    def test_a_sieht_die_eigenen_sehr_wohl(self):
        """Gegenprobe — ein durchweg leerer Vorrat bestünde sonst alles."""
        with mandant(self.a.organisation):
            self.assertTrue(was_reisst())
            self.assertIn(self.eingang_a.pk,
                          [z['eingang'].pk for z in posteingang()[0]])

    def test_b_sieht_die_eigenen_wenn_es_welche_gibt(self):
        with mandant(self.b.organisation):
            _fall_mit_frist(self.b.organisation, -1)
            self.assertTrue([e for e in was_reisst() if e['art'] == 'fall'])


class ZusammenstellungTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_arbeitsvorrat_liefert_alle_abschnitte(self):
        with mandant(self.a.organisation):
            anfrage = RequestFactory().get('/neu/')
            anfrage.user = self.a.benutzer
            daten = arbeitsvorrat(anfrage)
            for schluessel in ('av_heute', 'av_reisst', 'av_reisst_gesamt',
                               'av_reisst_weitere', 'av_ueberfaellig',
                               'av_eingaenge', 'av_eingaenge_gesamt'):
                with self.subTest(schluessel=schluessel):
                    self.assertIn(schluessel, daten)

    def test_weitere_wird_gerechnet_nicht_verdrahtet(self):
        """Ein Entwurf schrieb im Template `|add:"-5"` neben ein `ZEILEN = 5`.

        Sobald jemand `ZEILEN` ändert, lügt so ein Text. Hier wird gerechnet.
        """
        from faelle.arbeitsvorrat import ZEILEN
        with mandant(self.a.organisation):
            for i in range(ZEILEN + 2):
                _fall_mit_frist(self.a.organisation, i % 5, f'F{i}')
            anfrage = RequestFactory().get('/neu/')
            anfrage.user = self.a.benutzer
            daten = arbeitsvorrat(anfrage)
            self.assertEqual(daten['av_reisst_weitere'],
                             daten['av_reisst_gesamt'] - ZEILEN)
            self.assertEqual(len(daten['av_reisst']), ZEILEN)


class SeitenTests(TestCase):
    """Die Seiten müssen ausgeliefert werden, nicht nur die Funktionen dahinter."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _hole(self, adresse):
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            return c.get(adresse)

    def test_startseite_zeigt_was_reisst(self):
        with mandant(self.a.organisation):
            _fall_mit_frist(self.a.organisation, -3, 'Antwortfrist Blaser')
        antwort = self._hole('/neu/')
        self.assertEqual(antwort.status_code, 200)
        # «ARBEITSVORRAT» SEIT E2.68 — so heisst die Karte im Prototyp.
        #
        # Hier stand «Was reisst». Der Name war treffend für den ersten Reiter,
        # aber «Diese Woche», «Wartet auf Dritte» und «Alle» zeigen auch, was
        # NICHT reisst — er beschrieb einen Reiter, nicht die Karte.
        self.assertContains(antwort, 'Arbeitsvorrat')
        self.assertContains(antwort, 'Antwort verfassen')
        # «3 Tage über» — der Fall ist drei Tage überfällig, also Plural.
        # `Tag` allein zu prüfen wäre schwächer als vorher: Es passte auch auf
        # «1 Tage über», den Fehler, den E2.67 behoben hat.
        self.assertContains(antwort, '3 Tage über')

    def test_ohne_anlass_steht_der_leerzustand_da(self):
        """Gegenprobe: kein Dauerlärm, wenn nichts ansteht.

        Der Wortlaut hat sich mit der Zusammenfuehrung geaendert: Die
        Startseite steht jetzt in der Ansicht «Heute» und sagt entsprechend
        «Heute ist nichts faellig» statt «Nichts ueberfaellig».
        """
        antwort = self._hole('/neu/')
        self.assertContains(antwort, 'nichts fällig')

    def test_arbeit_kennt_alle_fuenf_ansichten(self):
        """Konzept 3.1 nennt genau diese fünf.

        Sie stehen seit der Zusammenfuehrung vom 21.08.2026 auf der
        STARTSEITE; `/neu/arbeit/` leitet dorthin um.
        """
        antwort = self._hole('/neu/')
        self.assertEqual(antwort.status_code, 200)
        for bezeichnung in ('Heute', 'Diese Woche', 'Wartet auf Dritte',
                            'Liegengeblieben', 'Alle'):
            with self.subTest(ansicht=bezeichnung):
                self.assertContains(antwort, bezeichnung)

    def test_die_kennzahlen_sind_ein_schmaler_streifen_und_keine_kacheln(self):
        """AUFGEHOBEN UND ERSETZT — die Begruendung gehoert hierher.

        Konzept 3.1 sagte woertlich «**Keine Kennzahlen**» auf der
        Arbeitsflaeche, und der Test hiess entsprechend
        `test_arbeit_zeigt_keine_kennzahlen`. Die Regel entstand gegen die
        alte Startseite mit Mietertrag-Diagramm, Portfolio-Donut, Belegung
        und Leerstandsliste — vier Kacheln, die den BESTAND zeigten und die
        Arbeit verdraengten.

        Am 21.08.2026 wurde entschieden, Arbeit und Lage auf EINER Seite zu
        fuehren. Die Regel bleibt dem Sinn nach bestehen, aber praeziser:
        Kennzahlen duerfen dort stehen, wenn sie **schmal** sind und einen
        **Vergleich** tragen. Die vier alten Kacheln sind ersatzlos
        entfallen; an ihre Stelle tritt ein vierteiliger Streifen mit
        Vormonatswert.

        `'fw-lage' in html` genuegt als Pruefung NICHT: base.html liefert das
        Stylesheet inline aus, der Klassenname steht also auf jeder Seite.
        Diese Blindheit hatte schon `AktenkopfTests`. Geprueft wird die
        VERWENDUNG — `class="fw-lage"`.
        """
        inhalt = self._hole('/neu/').content.decode()
        self.assertIn('class="fw-lage"', inhalt)
        # Die alten Kacheln, namentlich:
        self.assertNotIn('class="fw-kpis"', inhalt)
        self.assertNotIn('Belegung nach Nutzung', inhalt)
        self.assertNotIn('Soll vs. Ist', inhalt)
        self.assertNotIn('belegung_conic', inhalt)

    def test_liegengebliebener_fall_erscheint_unter_liegengeblieben(self):
        with mandant(self.a.organisation):
            fall, _s = _fall_mit_frist(self.a.organisation, -30, 'Vergessen')
            fall.letzte_bewegung = timezone.now() - timedelta(days=20)
            fall.save(update_fields=['letzte_bewegung'])
        antwort = self._hole('/neu/?ansicht=liegen')
        self.assertContains(antwort, 'Vergessen')

    def test_fallakte_zeigt_schritte_und_verfallsregel(self):
        with mandant(self.a.organisation):
            fall, _s = _fall_mit_frist(self.a.organisation, 2, 'Mieterwechsel Meier')
        antwort = self._hole(f'/neu/faelle/{fall.id}/')
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'Antwort verfassen')
        self.assertContains(antwort, 'meldet sich nach')

    def test_schritt_laesst_sich_erledigen(self):
        with mandant(self.a.organisation):
            fall, schritt = _fall_mit_frist(self.a.organisation, 2, 'Abhaken')
            c = Client()
            c.force_login(self.a.benutzer)
            antwort = c.post(f'/neu/fallschritte/{schritt.id}/erledigen/')
            self.assertEqual(antwort.status_code, 302)
            schritt.refresh_from_db()
            self.assertIsNotNone(schritt.erledigt_am)

    def test_laeufe_zeigen_den_blockadegrund(self):
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, tage_ueberfaellig=2)
            lauf.blockieren('Verbrauchsablesung Techem fehlt')
        antwort = self._hole('/neu/laeufe/')
        self.assertContains(antwort, 'Verbrauchsablesung Techem fehlt')

    def test_zulauf_kennzeichnet_den_unsicheren_vorschlag(self):
        with mandant(self.a.organisation):
            Eingang(organisation=self.a.organisation, quelle=Eingang.MAIL,
                    betreff='Unbekannte Offerte').save()
        antwort = self._hole('/neu/zulauf/')
        self.assertContains(antwort, 'Unbekannte Offerte')
        self.assertContains(antwort, 'von Hand')

    def test_fremder_eingang_steht_nicht_auf_der_startseite(self):
        """Die gefährlichste Variante — fremde Post im eigenen Arbeitsvorrat."""
        b = MandantenFixture('B', '3000', 'Bern')
        with mandant(self.a.organisation):
            Eingang(organisation=self.a.organisation, quelle=Eingang.MAIL,
                    betreff='Streng vertraulich Mandant A').save()
        c = Client()
        c.force_login(b.benutzer)
        with mandant(b.organisation):
            antwort = c.get('/neu/')
        self.assertNotContains(antwort, 'Streng vertraulich Mandant A')


class TermineTests(TestCase):
    """Der dritte Abschnitt des Prototyps.

    Ein Kalender, dem man nicht trauen kann, ist schlimmer als keiner —
    deshalb prüft jeder Test hier, dass ein Termin **erscheint**, und
    mindestens einer, dass ein erledigter oder ferner **verschwindet**.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _abnahme(self, tage, abgeschlossen=False):
        from rentals.models import Abnahmeprotokoll
        p = Abnahmeprotokoll(vertrag=self.a.vertrag, typ='auszug',
                             datum=timezone.localdate() + timedelta(days=tage),
                             abgeschlossen=abgeschlossen)
        p.save()
        return p

    def test_anstehende_abnahme_erscheint(self):
        """Geprüft wird der KONKRETE Termin, nicht die Anzahl.

        `MandantenFixture` legt selbst ein `Abnahmeprotokoll` an (Zeile 199).
        Eine Zählung war hier prompt falsch — derselbe Fehler, vor dem der
        Docstring von `PosteingangTests` warnt und den ich hier trotzdem
        gemacht habe.
        """
        from faelle.arbeitsvorrat import termine
        with mandant(self.a.organisation):
            protokoll = self._abnahme(2)
            treffer = [t for t in termine()
                       if t['ziel'].endswith(f'/{protokoll.vertrag_id}/')
                       and t['datum'] == protokoll.datum]
            self.assertEqual(len(treffer), 1)
            self.assertEqual(treffer[0]['titel'], 'Wohnungsabnahme')

    def _abnahme_zeilen(self, protokoll):
        """Nur die Zeilen DIESER Abnahme.

        Beide Tests darunter filterten anfangs allein auf das Datum. Das ging
        gut, solange am selben Tag nichts anderes lag — bis das Fixture mit
        4b.8 einen eigenen Termin bekam, der zufällig auf denselben Tag fiel.
        Der Test wurde rot und hatte recht: Er prüfte «an diesem Tag steht
        nichts» statt «diese Abnahme steht nicht da».

        Dieselbe Falle wie die Zählungen gegen ein Fixture, das selbst
        Datensätze anlegt — nur über das Datum statt über die Menge.
        """
        from faelle.arbeitsvorrat import termine
        return [t for t in termine()
                if t['ziel'].endswith(f'/{protokoll.vertrag_id}/')
                and t['datum'] == protokoll.datum]

    def test_abgeschlossene_abnahme_erscheint_nicht(self):
        with mandant(self.a.organisation):
            self.assertEqual(
                self._abnahme_zeilen(self._abnahme(2, abgeschlossen=True)), [])

    def test_abnahme_jenseits_der_woche_erscheint_nicht(self):
        with mandant(self.a.organisation):
            self.assertEqual(self._abnahme_zeilen(self._abnahme(20)), [])

    def test_termine_sind_nach_zeit_sortiert(self):
        from faelle.arbeitsvorrat import termine
        with mandant(self.a.organisation):
            self._abnahme(5)
            self._abnahme(1)
            daten = [t['datum'] for t in termine()]
            self.assertEqual(daten, sorted(daten))

    def test_b_sieht_den_termin_von_a_nicht(self):
        """B hat eigene Termine — geprüft wird, dass A's nicht dabei ist."""
        from faelle.arbeitsvorrat import termine
        b = MandantenFixture('B', '3000', 'Bern')
        with mandant(self.a.organisation):
            protokoll = self._abnahme(2)
        with mandant(b.organisation):
            ziele = [t['ziel'] for t in termine()]
        self.assertNotIn(f'/neu/vertraege/{protokoll.vertrag_id}/', ziele)


class FreigabenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _rechnung(self, status='neu', tage_alt=3):
        from finance.models import KreditorenRechnung
        r = KreditorenRechnung(liegenschaft=self.a.liegenschaft, lieferant='Sanitär Meier AG',
                               status=status, betrag=1240,
                               datum=timezone.localdate() - timedelta(days=tage_alt))
        r.save()
        return r

    def test_neue_rechnung_wartet_auf_freigabe(self):
        from faelle.arbeitsvorrat import wartet_auf_freigabe
        with mandant(self.a.organisation):
            self._rechnung()
            # Das Fixture legt selbst eine KreditorenRechnung an — also den
            # konkreten Lieferanten prüfen, nicht die Anzahl.
            treffer = [f for f in wartet_auf_freigabe()
                       if 'Sanitär Meier AG' in f['titel']]
            self.assertEqual(len(treffer), 1)
            self.assertEqual(treffer[0]['tage'], 3)

    def test_freigegebene_rechnung_wartet_nicht_mehr(self):
        from faelle.arbeitsvorrat import wartet_auf_freigabe
        with mandant(self.a.organisation):
            self._rechnung(status='freigegeben')
            self.assertEqual(
                [f for f in wartet_auf_freigabe()
                 if 'Sanitär Meier AG' in f['titel']], [])

    def test_liegezeit_wird_gerechnet(self):
        from faelle.arbeitsvorrat import liegezeit, wartet_auf_freigabe
        with mandant(self.a.organisation):
            self._rechnung(tage_alt=2)
            self._rechnung(tage_alt=4)
            zeilen = [f for f in wartet_auf_freigabe()
                      if 'Sanitär Meier AG' in f['titel']]
            self.assertEqual(liegezeit(zeilen), 3.0)

    def test_liegezeit_ohne_datum_ist_keine_null(self):
        """Sonst zöge ein fehlendes Feld den Schnitt gegen null."""
        from faelle.arbeitsvorrat import liegezeit
        self.assertIsNone(liegezeit([{'tage': None}, {'tage': None}]))
        self.assertEqual(liegezeit([{'tage': None}, {'tage': 4}]), 4.0)

    def test_jede_freigabe_fuehrt_zu_einem_ziel(self):
        from faelle.arbeitsvorrat import wartet_auf_freigabe
        with mandant(self.a.organisation):
            self._rechnung()
            zeilen = wartet_auf_freigabe()
            self.assertTrue(zeilen)
            for f in zeilen:
                with self.subTest(titel=f['titel']):
                    self.assertTrue(f['ziel'] and f['knopf'])

    def test_freigaben_stehen_nicht_mehr_in_der_inbox(self):
        """G2 — dieselbe Rechnung darf nicht zweimal auf der Seite stehen."""
        from core.services.inbox import sammle_inbox
        with mandant(self.a.organisation):
            self._rechnung()
            inbox, _mehr, _typen = sammle_inbox()
        self.assertFalse(
            any('freigeben' in e['titel'].lower() for e in inbox),
            'Die Sammelzeile «Rechnungen prüfen & freigeben» steht wieder in '
            'der Inbox — daneben zeigt «Wartet auf Freigabe» dieselben '
            'Rechnungen einzeln.')

    def test_der_zahllauf_bleibt_in_der_inbox(self):
        """Gegenprobe: Er ist ein LAUF, kein Einzelentscheid — und muss bleiben."""
        from core.services.inbox import sammle_inbox
        with mandant(self.a.organisation):
            self._rechnung(status='freigegeben')
            inbox, _mehr, _typen = sammle_inbox()
        self.assertTrue(any('bezahlen' in e['titel'].lower() for e in inbox),
                        'Der Zahllauf ist mit den Freigaben mitgegangen.')


class ProtoypVollstaendigkeitTests(TestCase):
    """Was der Prototyp auf «Heute» zeigt, muss die Seite führen — oder der
    Grund muss dastehen.

    `mockups/konzept-struktur.html` nennt fünf Abschnitte. Seit 4b.8 sind
    **alle fünf** gebaut.

    Bis dahin fehlte «Vertretung», weil sie nicht rechenbar war:
    `crm.Mitgliedschaft` führt Benutzer, Organisation und Rolle — kein
    Abwesenheitsfeld. `faelle.Abwesenheit` trägt es jetzt.

    `NICHT_GEBAUT` ist deshalb leer und bleibt es hoffentlich. Der Eintrag
    stand für eine benannte Lücke; eine Lücke, die niemand mehr benennt,
    ist eine vergessene.
    """

    NICHT_GEBAUT = set()

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _abschnitte_des_prototyps(self):
        import pathlib
        import re
        q = pathlib.Path('mockups/konzept-struktur.html').read_text(encoding='utf-8')
        # Zwischen den <h1>-ÜBERSCHRIFTEN, nicht zwischen den Navigations-
        # eintraegen: `>Heute<` steht auch im Menue, dort aber ohne Inhalt
        # dahinter — eine erste Fassung schnitt zwei Menuepunkte heraus und
        # las folgerichtig NULL Abschnitte. `test_der_prototyp_fuehrt_wirklich_
        # fuenf` hat das gemeldet.
        def h1(text):
            return re.search(rf'<h1[^>]*>\s*{text}', q).start()

        heute = q[h1('Heute'):h1('Fälle')]
        return [re.sub(r'<[^>]+>', '', m).strip()
                for m in re.findall(r'<h2[^>]*>(.*?)</h2>', heute, re.S)]

    def test_der_prototyp_fuehrt_wirklich_fuenf(self):
        """Gegenprobe: Ohne diesen Test prüfte der nächste eine leere Liste."""
        self.assertEqual(len(self._abschnitte_des_prototyps()), 5)

    def test_jeder_abschnitt_ist_gebaut_oder_benannt(self):
        import pathlib
        vorlagen = '\n'.join(
            pathlib.Path('core/templates/fw', d).read_text(encoding='utf-8')
            for d in ('dashboard.html', '_arbeitsvorrat_abschnitte.html'))
        # Der Prototyp nennt sie so, die Anwendung teils anders — die
        # Zuordnung steht hier, damit sie nachlesbar ist.
        gebaut = {'Was reisst': 'Was reisst',
                  'Posteingang': 'Zulauf',
                  'Termine': 'Termine',
                  'Wartet auf mich': 'Wartet auf Freigabe',
                  'Vertretung': 'Vertretung'}
        for name in self._abschnitte_des_prototyps():
            with self.subTest(abschnitt=name):
                if name in self.NICHT_GEBAUT:
                    self.assertIn(
                        name, vorlagen,
                        f'«{name}» ist nicht gebaut — dann muss in der Vorlage '
                        f'stehen, warum. Eine stumme Lücke liest sich als '
                        f'Versehen.')
                else:
                    self.assertIn(gebaut[name], vorlagen)

    def test_es_gibt_keine_unbenannte_luecke_mehr(self):
        """Die frühere Ausnahme ist aufgelöst — und der Test sagt es.

        Bis 4b.8 stand hier: «Sobald ein Abwesenheitsmodell existiert, gehört
        Vertretung gebaut», geprüft an einem Feld `abwesend_bis` auf
        `crm.Mitgliedschaft`. Gebaut wurde stattdessen ein eigenes Modell,
        `faelle.Abwesenheit` — der alte Test wäre also **grün geblieben und
        bedeutungslos geworden**: Er hätte auf ein Feld gewartet, das nie
        kommt, während die Sache längst erledigt war.

        Diese Fassung prüft die Sache selbst: Das Modell ist da, es trägt
        eine Vertretung, und `NICHT_GEBAUT` ist leer.
        """
        from django.apps import apps

        modell = apps.get_model('faelle', 'Abwesenheit')
        felder = {f.name for f in modell._meta.get_fields()}
        for pflicht in ('benutzer', 'von', 'bis', 'vertreten_durch'):
            with self.subTest(feld=pflicht):
                self.assertIn(pflicht, felder)
        self.assertEqual(
            self.NICHT_GEBAUT, set(),
            'Es steht wieder eine Lücke in NICHT_GEBAUT — dann gehört der '
            'Grund in die Vorlage und in KONZEPT-UI.md 3.1.')
