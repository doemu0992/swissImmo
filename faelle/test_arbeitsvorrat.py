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
        """Der Test, der den Feldfehler gefunden hätte."""
        with mandant(self.a.organisation):
            _fall, schritt = _fall_mit_frist(self.a.organisation, -3)
            treffer = [e for e in was_reisst() if e['art'] == 'fall']
            self.assertEqual(len(treffer), 1)
            self.assertEqual(treffer[0]['titel'], schritt.bezeichnung)
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

        Beim Umbau wäre sie es beinahe: Der Arbeitsvorrat nimmt nur datierte
        Vorgänge, und der alte Inbox-Block, der sie führte, ist entfernt. Sie
        steht jetzt als Sammelposten in der Inbox.
        """
        from core.models import Pendenz
        from core.services.inbox import sammle_inbox
        with mandant(self.a.organisation):
            Pendenz(organisation=self.a.organisation, titel='Irgendwann mal',
                    vertrag=self.a.vertrag, faellig_am=None).save()
            inbox, _mehr, _typen = sammle_inbox()
            self.assertTrue(any('ohne Frist' in e['titel'] for e in inbox),
                            'Undatierte Aufgaben tauchen nirgends mehr auf.')


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
        self.assertContains(antwort, 'Was reisst')
        self.assertContains(antwort, 'Antwort verfassen')
        self.assertContains(antwort, 'Tage über')

    def test_ohne_anlass_steht_der_leerzustand_da(self):
        """Gegenprobe: kein Dauerlärm, wenn nichts ansteht."""
        antwort = self._hole('/neu/')
        self.assertContains(antwort, 'Nichts überfällig')

    def test_arbeit_kennt_alle_fuenf_ansichten(self):
        """Konzept 3.1 nennt genau diese fünf."""
        antwort = self._hole('/neu/arbeit/')
        self.assertEqual(antwort.status_code, 200)
        for bezeichnung in ('Heute', 'Diese Woche', 'Wartet auf Dritte',
                            'Liegengeblieben', 'Alle'):
            with self.subTest(ansicht=bezeichnung):
                self.assertContains(antwort, bezeichnung)

    def test_arbeit_zeigt_keine_kennzahlen(self):
        """Konzept 3.1, wörtlich: «**Keine Kennzahlen.**»

        `'fw-kpis' in html` genügt NICHT: base.html liefert das Stylesheet
        inline aus, der Klassenname steht also auf jeder Seite. Genau diese
        Blindheit hatte schon `AktenkopfTests` (Gegenprobe vom 20.08.2026).
        Geprüft wird deshalb die VERWENDUNG — `class="fw-kpis"`.
        """
        inhalt = self._hole('/neu/arbeit/').content.decode()
        self.assertNotIn('class="fw-kpis"', inhalt)
        self.assertNotIn('Leerstandsquote', inhalt)
        # Gegenprobe zur Gegenprobe: Auf der Startseite stehen Kennzahlen
        # sehr wohl — sonst prüfte die Zusicherung oben nur einen Tippfehler.
        self.assertIn('class="fw-kpis"', self._hole('/neu/').content.decode())

    def test_liegengebliebener_fall_erscheint_unter_liegengeblieben(self):
        with mandant(self.a.organisation):
            fall, _s = _fall_mit_frist(self.a.organisation, -30, 'Vergessen')
            fall.letzte_bewegung = timezone.now() - timedelta(days=20)
            fall.save(update_fields=['letzte_bewegung'])
        antwort = self._hole('/neu/arbeit/?ansicht=liegen')
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
