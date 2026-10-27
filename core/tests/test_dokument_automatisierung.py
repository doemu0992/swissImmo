"""Modul 5 — Dokumenten-Automatisierung (27.10.2026).

Platzhalter-Dienst, Vorlagen mit Ereignis/Sprache/Version/«gültig ab»,
Regeln «Ereignis → Dokument», Fassungen in der Ablage, Briefkopf je
Verwaltung — und die Mandantengrenze an jedem neuen Zugang.

Gegenproben stehen je Testklasse im Docstring; sie wurden beim Bauen einzeln
ausgeführt (Code kaputt → Test rot → Code zurück).
"""
import pathlib
import shutil
import tempfile
from datetime import date, timedelta
from unittest import mock

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from core.tenancy import organisation_kontext
from crm.models import Organisation, Vorlage
from rentals.models import Dokument

from ._isolation import MandantenFixture

MEDIA = tempfile.mkdtemp()
HEUTE = date.today()


class PlatzhalterTests(SimpleTestCase):
    """Gegenproben: in `ersetze` die Alias-Auflösung (`_wert`, Zeile `ziel = …`)
    entfernen → `test_aliase_der_alten_systeme` rot; in `unbekannte` die
    Bedingung `not bekannt(name)` durch `False` ersetzen →
    `test_unbekannte_werden_erkannt` rot; in serienbrief._ersetze die alte
    Schleife zurücksetzen → `test_alte_ersetzer_rufen_den_dienst` rot."""

    def test_ersetzen(self):
        from core.services.platzhalter import ersetze
        self.assertEqual(ersetze('Guten Tag {mieter.name}, ab {vertrag.beginn}.',
                                 {'mieter.name': 'Lea Frei', 'vertrag.beginn': '01.01.2027'}),
                         'Guten Tag Lea Frei, ab 01.01.2027.')

    def test_ohne_wert_bleibt_der_platzhalter_stehen(self):
        from core.services.platzhalter import ersetze
        self.assertEqual(ersetze('Ende {vertrag.ende}', {}), 'Ende {vertrag.ende}')

    def test_unbekannte_werden_erkannt(self):
        from core.services.platzhalter import unbekannte
        text = '{mieter.name} {mieter.nmae} {Mieter.name} {mieter.nmae} {Ihr Text} p { color: red }'
        self.assertEqual(unbekannte(text), ['{mieter.nmae}', '{Mieter.name}'])

    def test_alle_alten_schreibweisen_sind_bekannt(self):
        """Bestehende Vorlagen in Kundendaten dürfen beim Speichern nicht abgelehnt werden."""
        from core.services.platzhalter import unbekannte
        from core.services.ticket_workflow import TICKET_PLATZHALTER
        from core.services.vorlagen_defaults import STANDARD_VORLAGEN
        from core.views.fw.profil import PLATZHALTER_HILFE
        alte = ' '.join(c for c, _b in PLATZHALTER_HILFE) + ' '.join(c for c, _b in TICKET_PLATZHALTER)
        alte += ' {name} {anrede} {strasse} {plz} {ort} {adresse} {monat} {betrag} {gebuehr} {mieter} {termin}'
        alte += ' {bewerber_name}'
        self.assertEqual(unbekannte(alte), [])
        for v in STANDARD_VORLAGEN:
            with self.subTest(vorlage=v['name']):
                self.assertEqual(unbekannte(v['betreff'] + v['inhalt']), [])

    def test_aliase_der_alten_systeme(self):
        from core.services.platzhalter import ersetze
        kontext = {'mieter.name': 'Lea Frei', 'mieter.anrede_kurz': 'Frau', 'datum.heute': '27.10.2026',
                   'objekt.strasse': 'Seestrasse 12', 'verwaltung.vermieter': 'Muster AG'}
        self.assertEqual(
            ersetze('{mieter_name}|{name}|{anrede}|{datum}|{liegenschaft}|{vermieter}|{mieter}', kontext),
            'Lea Frei|Lea Frei|Frau|27.10.2026|Seestrasse 12|Muster AG|Lea Frei')

    def test_html_werte_werden_maskiert(self):
        from core.services.platzhalter import ersetze
        self.assertEqual(ersetze('<p>{mieter.name}</p>', {'mieter.name': '<script>x</script>'}, html=True),
                         '<p>&lt;script&gt;x&lt;/script&gt;</p>')

    def test_alte_ersetzer_rufen_den_dienst(self):
        from core.services.serienbrief import _ersetze as serienbrief
        from core.services.ticket_workflow import _ersetze as ticket
        self.assertEqual(serienbrief('{anrede} {name} / {mieter.name}', {'name': 'Lea', 'anrede': 'Frau'}),
                         'Frau Lea / Lea')
        self.assertEqual(ticket('{mieter_name} / {mieter.name} / {unbekannt}', {'mieter_name': 'Lea'}),
                         'Lea / Lea / {unbekannt}')

    def test_html_bereinigung(self):
        from core.services.vorlagen_pdf import bereinige_html
        roh = ('<p onclick="x()">Hallo <b>{mieter.name}</b></p><script>alert(1)</script>'
               '<img src="http://intern/x"><a href="javascript:x">Link</a><td colspan="2">t</td>')
        self.assertEqual(bereinige_html(roh),
                         '<p>Hallo <b>{mieter.name}</b></p>Link<td colspan="2">t</td>')


class KontextTests(TestCase):
    """Gegenprobe: in `kontext_fuer` die Prüfung `!= org.pk` entfernen →
    `test_fremder_datensatz_wirft` rot."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_vertrag_liefert_die_werte_aus_dem_bestand(self):
        from core.services.platzhalter import kontext_fuer
        with organisation_kontext(self.a.organisation):
            k = kontext_fuer(vertrag=self.a.vertrag)
        self.assertEqual(k['mieter.name'], 'Mieter A')
        self.assertEqual(k['mieter.anrede'], 'Sehr geehrter Herr A')
        self.assertEqual(k['objekt.strasse'], 'A-Weg 7')
        self.assertEqual(k['vertrag.mietzins_netto'], "1'500.00")      # Format aus build_vertrag_context
        self.assertEqual(k['vertrag.mietzins_brutto'], "1'700.00")
        self.assertEqual(k['vertrag.beginn'], '01.01.2024')
        self.assertEqual(k['verwaltung.name'], 'Verwaltung A AG')
        self.assertEqual(k['verwaltung.vermieter'], 'Eigentuemer A')

    def test_bewerbung_liefert_angebot_und_anrede(self):
        from core.services.platzhalter import kontext_fuer
        with organisation_kontext(self.a.organisation):
            k = kontext_fuer(bewerbung=self.a.bewerbung, sprache='fr')
        self.assertEqual(k['bewerbung.name'], 'Bewerber A')
        self.assertEqual(k['mieter.anrede_kurz'], 'Frau')                # geschlecht «weiblich»
        from core.services.mietprozess_briefe import _fr
        self.a.einheit.refresh_from_db()
        self.assertEqual(k['vertrag.mietzins_netto'], _fr(self.a.einheit.nettomiete_aktuell))
        self.assertNotIn('vertrag.kaution', k, 'Eine Kaution steht erst im Vertrag fest.')

    def test_fremder_datensatz_wirft(self):
        from core.services.platzhalter import kontext_fuer
        with organisation_kontext(self.a.organisation):
            with self.assertRaises(ValueError):
                kontext_fuer(vertrag=self.b.vertrag, organisation=self.a.organisation)


def _vorlage(org, **kw):
    werte = {'name': 'Begleitbrief', 'kategorie': 'dokument', 'ereignis': 'kuendigung_erfasst',
             'betreff': 'Betreff {mieter.name}', 'inhalt': '{mieter.anrede}\n\nText', 'sprache': 'de'}
    werte.update(kw)
    with organisation_kontext(org) if org is not None else _ohne():
        return Vorlage.objects.create(organisation=org, **werte)


class _ohne:
    def __enter__(self):
        from core.tenancy import ohne_organisation
        self._cm = ohne_organisation()
        return self._cm.__enter__()

    def __exit__(self, *a):
        return self._cm.__exit__(*a)


class AuswahlTests(TestCase):
    """Welche Vorlage gilt. Gegenproben in `_waehle`: die erste Stelle des
    Rangs (eigen vor System) entfernen → `test_eigene_vor_system` rot; die
    zweite (Sprache) → `test_sprache_des_empfaengers_vor_de` rot; `_gilt`
    immer True → `test_gueltig_ab` rot; die Abschalt-Zeile entfernen →
    `test_ausgeschaltete_eigene_schaltet_auch_system_ab` rot; in
    `regel_uebersicht` den Rückfall auf andere Sprachen abschalten →
    `test_kachel_aktiv_auch_ohne_deutsche_fassung` rot."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _gilt(self, **kw):
        from core.services.dokument_regeln import aktive_vorlage
        return aktive_vorlage('kuendigung_erfasst', organisation=self.a.organisation, **kw)

    def test_ohne_vorlage_keine(self):
        self.assertIsNone(self._gilt())

    def test_systemvorlage_gilt_fuer_alle(self):
        system = _vorlage(None, name='System')
        self.assertEqual(self._gilt(), system)

    def test_eigene_vor_system(self):
        _vorlage(None, name='System', sprache='fr')
        eigene = _vorlage(self.a.organisation, name='Eigene')
        self.assertEqual(self._gilt(sprache='fr'), eigene, 'Eigene (de) geht vor System (fr).')

    def test_sprache_des_empfaengers_vor_de(self):
        # FR zuerst: Die jüngere ID gewinnt bei sonst gleichem Rang — so
        # entscheidet hier wirklich die Sprache und nicht die Reihenfolge.
        fr = _vorlage(self.a.organisation, name='FR', sprache='fr')
        de = _vorlage(self.a.organisation, name='DE')
        self.assertEqual(self._gilt(sprache='fr'), fr)
        self.assertEqual(self._gilt(sprache='it'), de, 'Ohne italienische Fassung gilt die deutsche.')
        self.assertEqual(self._gilt(sprache='en'), de)

    def test_gueltig_ab(self):
        alt = _vorlage(self.a.organisation, name='Alt', gueltig_ab=HEUTE - timedelta(days=400))
        jung = _vorlage(self.a.organisation, name='Jung', gueltig_ab=HEUTE - timedelta(days=10))
        _vorlage(self.a.organisation, name='Zukunft', gueltig_ab=HEUTE + timedelta(days=10))
        self.assertEqual(self._gilt(), jung)
        self.assertEqual(self._gilt(stichtag=HEUTE - timedelta(days=100)), alt)

    def test_inaktive_zaehlt_nicht(self):
        aktiv = _vorlage(self.a.organisation, name='Aktiv', gueltig_ab=HEUTE - timedelta(days=30))
        _vorlage(self.a.organisation, name='Aus', aktiv=False, gueltig_ab=HEUTE - timedelta(days=1))
        self.assertEqual(self._gilt(), aktiv)

    def test_ausgeschaltete_eigene_schaltet_auch_system_ab(self):
        _vorlage(None, name='System')
        _vorlage(self.a.organisation, name='Aus', aktiv=False)
        self.assertIsNone(self._gilt())

    def test_fremde_vorlage_gilt_nicht(self):
        _vorlage(self.b.organisation, name='Von B')
        self.assertIsNone(self._gilt())

    def test_regeluebersicht_mit_einer_abfrage(self):
        from core.services.dokument_regeln import regel_uebersicht
        _vorlage(None, name='System')
        _vorlage(self.a.organisation, name='Eigene', ereignis='nk_versandt')
        with self.assertNumQueries(1):
            kacheln = regel_uebersicht(self.a.organisation)
        nach = {k['ereignis']: k for k in kacheln}
        self.assertEqual(len(kacheln), len(Vorlage.EREIGNIS_CHOICES))
        self.assertEqual((nach['kuendigung_erfasst']['status'], nach['kuendigung_erfasst']['herkunft']),
                         ('aktiv', 'system'))
        self.assertEqual((nach['nk_versandt']['status'], nach['nk_versandt']['herkunft']), ('aktiv', 'eigen'))
        self.assertEqual((nach['vertrag_erstellt']['status'], nach['vertrag_erstellt']['herkunft']), ('aus', ''))

    def test_kachel_aktiv_auch_ohne_deutsche_fassung(self):
        """Nur eine französische Vorlage: Die Regel greift für französische
        Empfänger, also ist sie aktiv — nicht «aus»."""
        from core.services.dokument_regeln import regel_uebersicht
        fr = _vorlage(self.a.organisation, name='FR', sprache='fr')
        nach = {k['ereignis']: k for k in regel_uebersicht(self.a.organisation)}
        self.assertEqual((nach['kuendigung_erfasst']['status'], nach['kuendigung_erfasst']['vorlage']), ('aktiv', fr))
        Vorlage.alle_organisationen.filter(pk=fr.pk).update(aktiv=False)
        nach = {k['ereignis']: k for k in regel_uebersicht(self.a.organisation)}
        self.assertEqual(nach['kuendigung_erfasst']['status'], 'aus')


@override_settings(MEDIA_ROOT=MEDIA)
class RegelTests(TestCase):
    """Regel erzeugt Dokument; ohne Regel keines; ein Fehler kostet den
    Hauptablauf nicht. Gegenproben: in `dokument_fuer_ereignis` das
    `try/except` entfernen → `test_fehler_kostet_den_hauptablauf_nicht` rot
    (500 statt 302); `im_portal_sichtbar=(False …)` auf None →
    `test_zusage_erzeugt_begleitdokument` rot; eine der Aufrufzeilen in den
    Views entfernen → `test_alle_ereignisse_sind_verdrahtet` rot."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.client.force_login(self.a.benutzer)

    def _anzahl(self):
        return Dokument.alle_organisationen.filter(organisation=self.a.organisation).count()

    def test_ohne_regel_kein_dokument(self):
        from core.services.dokument_regeln import dokument_fuer_ereignis
        vorher = self._anzahl()
        self.assertIsNone(dokument_fuer_ereignis('kuendigung_erfasst', organisation=self.a.organisation,
                                                 vertrag=self.a.vertrag))
        self.assertEqual(self._anzahl(), vorher)

    def test_regel_erzeugt_dokument(self):
        from core.services.dokument_regeln import dokument_fuer_ereignis
        vl = _vorlage(self.a.organisation)
        with organisation_kontext(self.a.organisation):
            dok = dokument_fuer_ereignis('kuendigung_erfasst', organisation=self.a.organisation,
                                         vertrag=self.a.vertrag)
        self.assertIsNotNone(dok)
        self.assertEqual((dok.vorlage_id, dok.vertrag_id, dok.version), (vl.pk, self.a.vertrag.pk, 1))
        with dok.datei.open('rb') as f:
            self.assertTrue(f.read(5).startswith(b'%PDF'))
        self.assertTrue(dok.datei.name.startswith(f'organisation/{self.a.organisation.pk}/'),
                        dok.datei.name)

    def test_zusage_erzeugt_begleitdokument(self):
        _vorlage(self.a.organisation, ereignis='bewerber_zugesagt', name='Zusage')
        vorher = self._anzahl()
        r = self.client.post(f'/neu/bewerbungen/{self.a.bewerbung.pk}/entscheid/', {'entscheid': 'zusage'})
        self.assertEqual(r.status_code, 302)
        neu = Dokument.alle_organisationen.filter(organisation=self.a.organisation).order_by('-id').first()
        self.assertEqual(self._anzahl(), vorher + 1)
        self.assertEqual(neu.einheit_id, self.a.einheit.pk)
        self.assertTrue(neu.bezeichnung.startswith('Zusage – Bewerber A'), neu.bezeichnung)
        self.assertFalse(neu.im_portal_sichtbar,
                         'Ein Schreiben an eine Bewerberin erschiene sonst im Portal des heutigen Mieters.')

    def test_zusage_ohne_regel_kein_zusaetzliches_dokument(self):
        vorher = self._anzahl()
        self.client.post(f'/neu/bewerbungen/{self.a.bewerbung.pk}/entscheid/', {'entscheid': 'zusage'})
        self.assertEqual(self._anzahl(), vorher)

    def test_fehler_kostet_den_hauptablauf_nicht(self):
        _vorlage(self.a.organisation, ereignis='bewerber_zugesagt', name='Zusage')
        vorher = self._anzahl()
        with mock.patch('core.services.vorlagen_pdf.vorlage_pdf', side_effect=RuntimeError('kaputt')), \
                self.assertLogs('core.services.dokument_regeln', level='ERROR'):
            r = self.client.post(f'/neu/bewerbungen/{self.a.bewerbung.pk}/entscheid/', {'entscheid': 'zusage'})
        self.assertEqual(r.status_code, 302)
        self.a.bewerbung.refresh_from_db()
        self.assertEqual(self.a.bewerbung.status, 'zugesagt')
        self.assertEqual(self._anzahl(), vorher)

    def test_alle_ereignisse_sind_verdrahtet(self):
        """Je Ereignis genau die Stelle aus dem Auftrag — und nur einmal je Ablauf."""
        wurzel = pathlib.Path(settings.BASE_DIR) / 'core' / 'views' / 'fw'
        erwartet = {
            'vertrag_erstellt': ('vertragserstellung.py', 1),
            'bewerber_zugesagt': ('mietprozess.py', 1),
            'kuendigung_erfasst': ('kuendigung.py', 1),
            'mza_versandt': ('mietzins.py', 1),
            'nk_versandt': ('nebenkosten.py', 2),        # Ausdruck und E-Mail
            'abnahme_abgeschlossen': ('abnahme.py', 1),
        }
        self.assertEqual(set(erwartet), {k for k, _l in Vorlage.EREIGNIS_CHOICES})
        for ereignis, (datei, n) in erwartet.items():
            with self.subTest(ereignis=ereignis):
                quelle = (wurzel / datei).read_text(encoding='utf-8')
                self.assertEqual(quelle.count(f"dokument_fuer_ereignis('{ereignis}'"), n)


@override_settings(MEDIA_ROOT=MEDIA)
class FassungenTests(TestCase):
    """`ablegen(dedup=True)` legt eine neue Fassung an. Gegenproben: in
    `ablegen` die Zeile `dok.vorgaenger = vorhanden` entfernen →
    `test_dedup_legt_neue_fassung_an` und `test_listen_zeigen_nur_die_neueste`
    rot; in `fw_dokumente` `.neueste()` entfernen → `test_listen_zeigen_nur_die_neueste` rot;
    in `_gleicher_inhalt` den PDF-Seitenvergleich abschalten →
    `test_wiederoeffnen_legt_keine_neue_fassung_an` rot."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def _ablegen(self, inhalt):
        from core.services.ablage import ablegen
        with organisation_kontext(self.a.organisation):
            return ablegen(inhalt, 'Brief Modul 5', vertrag=self.a.vertrag, dedup=True)

    def test_dedup_legt_neue_fassung_an(self):
        d1 = self._ablegen(b'%PDF-1 eins')
        d2 = self._ablegen(b'%PDF-1 zwei')
        self.assertNotEqual(d1.pk, d2.pk)
        self.assertEqual((d2.vorgaenger_id, d2.version), (d1.pk, 2))
        d1.refresh_from_db()
        with d1.datei.open('rb') as f:
            self.assertEqual(f.read(), b'%PDF-1 eins', 'Die alte Datei wurde überschrieben.')
        self.assertNotEqual(d1.datei.name, d2.datei.name)
        with organisation_kontext(self.a.organisation):
            self.assertEqual(Dokument.objects.filter(bezeichnung='Brief Modul 5').neueste().get(), d2)
        self.assertEqual([d.pk for d in d1.verlauf()], [d2.pk, d1.pk])

    def test_gleicher_inhalt_keine_neue_fassung(self):
        d1 = self._ablegen(b'%PDF-1 gleich')
        d2 = self._ablegen(b'%PDF-1 gleich')
        self.assertEqual(d1.pk, d2.pk)

    def test_wiederoeffnen_legt_keine_neue_fassung_an(self):
        """reportlab schreibt Zeit und Zufalls-ID in jede Datei. Dieselben Seiten
        sind trotzdem dieselbe Fassung — sonst erzeugte jedes Öffnen eines PDF
        (Rechnung, Protokoll) eine neue."""
        import io
        from reportlab.pdfgen import canvas

        def pdf(titel, text='Rechnung 42'):
            puffer = io.BytesIO()
            c = canvas.Canvas(puffer)
            c.setTitle(titel)                  # andere Metadaten, andere Bytes
            c.drawString(100, 700, text)
            c.showPage()
            c.save()
            return puffer.getvalue()
        erst, wieder = pdf('eins'), pdf('zwei')
        self.assertNotEqual(erst, wieder)
        d1 = self._ablegen(erst)
        self.assertEqual(self._ablegen(wieder).pk, d1.pk)
        d3 = self._ablegen(pdf('drei', text='Rechnung 43'))
        self.assertEqual((d3.vorgaenger_id, d3.version), (d1.pk, 2))

    def test_zustellnachweis_und_sichtbarkeit_gehen_mit(self):
        d1 = self._ablegen(b'%PDF-1 eins')
        Dokument.alle_organisationen.filter(pk=d1.pk).update(
            zugang_pflichtig=True, frist_pendenz_id=4711, im_portal_sichtbar=False)
        d2 = self._ablegen(b'%PDF-1 zwei')
        self.assertEqual((d2.zugang_pflichtig, d2.frist_pendenz_id, d2.im_portal_sichtbar), (True, 4711, False))

    def test_listen_zeigen_nur_die_neueste(self):
        d1 = self._ablegen(b'%PDF-1 eins')
        d2 = self._ablegen(b'%PDF-1 zwei')
        self.client.force_login(self.a.benutzer)
        for url in ('/neu/dokumente/', f'/neu/vertraege/{self.a.vertrag.pk}/', f'/neu/personen/{self.a.mieter.pk}/'):
            with self.subTest(url=url):
                inhalt = self.client.get(url).content.decode()
                self.assertIn(d2.datei.url, inhalt)
                self.assertNotIn(d1.datei.url, inhalt)
        self.assertIn(f'/neu/dokument/{d2.pk}/verlauf/', self.client.get('/neu/dokumente/').content.decode())

    def test_verlauf_zeigt_alle_fassungen(self):
        d1 = self._ablegen(b'%PDF-1 eins')
        d2 = self._ablegen(b'%PDF-1 zwei')
        self.client.force_login(self.a.benutzer)
        inhalt = self.client.get(f'/neu/dokument/{d1.pk}/verlauf/').content.decode()
        self.assertIn(d1.datei.url, inhalt)
        self.assertIn(d2.datei.url, inhalt)

    def test_fremder_verlauf_ist_404(self):
        self.client.force_login(self.b.benutzer)
        d1 = self._ablegen(b'%PDF-1 eins')
        self.assertEqual(self.client.get(f'/neu/dokument/{d1.pk}/verlauf/').status_code, 404)


class SpeichernTests(TestCase):
    """Editor: unbekannte Platzhalter abgelehnt, Version zählt, Kopie bei
    System. Gegenproben: in `formular_lesen` die Prüfung `unbekannte(…)`
    entfernen → `test_unbekannter_platzhalter_wird_abgelehnt` rot; in
    `fw_vorlage_form` `obj.version = … + 1` entfernen →
    `test_speichern_erhoeht_die_version` rot; die Bedingung `neue_fassung`
    auf False → `test_spaeteres_gueltig_ab_legt_neue_fassung_an` rot."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.client.force_login(self.a.benutzer)

    def _post(self, url, **kw):
        daten = {'name': 'Zusage', 'kategorie': 'dokument', 'betreff': 'Zusage', 'format': 'text',
                 'sprache': 'de', 'ereignis': 'bewerber_zugesagt', 'gueltig_ab': '', 'aktiv_feld': '1',
                 'aktiv': '1', 'inhalt': '{mieter.anrede}\n\nab {vertrag.beginn}'}
        daten.update(kw)
        return self.client.post(url, daten)

    def test_unbekannter_platzhalter_wird_abgelehnt(self):
        r = self._post('/neu/vorlagen/neu/', inhalt='Hallo {mieter.vorname} {mieter.lieblingsfarbe}')
        self.assertEqual(r.status_code, 200)
        self.assertIn('{mieter.lieblingsfarbe}', r.content.decode())
        self.assertFalse(Vorlage.alle_organisationen.filter(name='Zusage').exists())

    def test_alte_schreibweise_wird_angenommen(self):
        r = self._post('/neu/vorlagen/neu/', inhalt='Sehr geehrte {mieter_name}, {anrede} {name}')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Vorlage.alle_organisationen.filter(name='Zusage', organisation=self.a.organisation).exists())

    def test_speichern_erhoeht_die_version(self):
        vl = _vorlage(self.a.organisation, name='Zusage', ereignis='bewerber_zugesagt')
        self._post(f'/neu/vorlagen/{vl.pk}/bearbeiten/', betreff='Neu')
        vl.refresh_from_db()
        self.assertEqual((vl.version, vl.betreff), (2, 'Neu'))

    def test_systemvorlage_bearbeiten_ergibt_kopie(self):
        system = _vorlage(None, name='Zusage', ereignis='bewerber_zugesagt')
        self.client.get(f'/neu/vorlagen/{system.pk}/bearbeiten/')
        self._post(f'/neu/vorlagen/{system.pk}/bearbeiten/', betreff='Eigene')
        system.refresh_from_db()
        self.assertEqual((system.betreff, system.version), ('Betreff {mieter.name}', 1))
        kopie = Vorlage.alle_organisationen.get(organisation=self.a.organisation, name='Zusage')
        self.assertEqual((kopie.betreff, kopie.version), ('Eigene', 2))

    def test_systemvorlage_ist_in_der_liste_sichtbar(self):
        _vorlage(None, name='Systembrief')
        inhalt = self.client.get('/neu/vorlagen/').content.decode()
        self.assertIn('Systembrief', inhalt)

    def test_spaeteres_gueltig_ab_legt_neue_fassung_an(self):
        vl = _vorlage(self.a.organisation, name='Zusage', ereignis='bewerber_zugesagt')
        spaeter = HEUTE + timedelta(days=30)
        self._post(f'/neu/vorlagen/{vl.pk}/bearbeiten/', betreff='Ab später', gueltig_ab=spaeter.isoformat())
        vl.refresh_from_db()
        self.assertEqual(vl.betreff, 'Betreff {mieter.name}', 'Die geltende Fassung wurde überschrieben.')
        neu = Vorlage.alle_organisationen.get(organisation=self.a.organisation, betreff='Ab später')
        self.assertEqual((neu.version, neu.gueltig_ab), (2, spaeter))

    def test_fehlendes_aktiv_feld_schaltet_nicht_aus(self):
        """Ältere Formulare schicken das Häkchen nicht mit — das heisst nicht «aus»."""
        vl = _vorlage(self.a.organisation, name='Alt', ereignis='')
        self.client.post(f'/neu/vorlagen/{vl.pk}/bearbeiten/',
                         {'name': 'Alt', 'kategorie': 'brief', 'betreff': 'x', 'inhalt': 'y'})
        vl.refresh_from_db()
        self.assertTrue(vl.aktiv)

    def test_fremde_vorlage_bearbeiten_ist_404(self):
        fremd = _vorlage(self.b.organisation, name='Von B')
        self.assertEqual(self.client.get(f'/neu/vorlagen/{fremd.pk}/bearbeiten/').status_code, 404)
        self._post(f'/neu/vorlagen/{fremd.pk}/bearbeiten/', betreff='von A')
        fremd.refresh_from_db()
        self.assertNotEqual(fremd.betreff, 'von A')

    def test_editor_zeigt_chips_sprachen_und_version(self):
        vl = _vorlage(self.a.organisation, name='Zusage', ereignis='bewerber_zugesagt')
        inhalt = self.client.get(f'/neu/vorlagen/{vl.pk}/bearbeiten/').content.decode()
        self.assertIn('data-einfuegen="{mieter.anrede}"', inhalt)
        self.assertIn('data-sprache="fr"', inhalt)
        self.assertIn('Version 1', inhalt)
        self.assertIn(f'/neu/vorlagen/neu/?von={vl.pk}&amp;sprache=fr', inhalt)


@override_settings(MEDIA_ROOT=MEDIA)
class VorschauIsolationTests(TestCase):
    """Vorschau und Probe-PDF nur mit eigenen Datensätzen. Gegenproben: in
    `_quelle` `Mietvertrag.objects` durch `Mietvertrag.alle_organisationen`
    ersetzen → `test_fremder_vertrag_ist_404` rot; in
    `fw_vorlage_regel_umschalten` die Kopie mit `organisation=org` durch ein
    Update der Systemvorlage ersetzen → `test_umschalten_trifft_nur_die_eigene` rot."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.client.force_login(self.a.benutzer)

    def _daten(self, quelle):
        return {'betreff': 'Für {mieter.name}', 'inhalt': '{mieter.anrede}\n\n{objekt.adresse}',
                'format': 'text', 'sprache': 'de', 'quelle': quelle}

    def test_vorschau_mit_eigenem_vertrag(self):
        r = self.client.post('/neu/vorlagen/vorschau/', self._daten(f'v:{self.a.vertrag.pk}'))
        self.assertEqual(r.status_code, 200)
        inhalt = r.content.decode()
        self.assertIn('Für Mieter A', inhalt)
        self.assertIn('A-Weg 7, 8000 Zürich', inhalt)

    def test_vorschau_ohne_datensatz_mit_beispielwerten(self):
        inhalt = self.client.post('/neu/vorlagen/vorschau/', self._daten('')).content.decode()
        self.assertIn('Für Lea Frei', inhalt)
        self.assertIn('Verwaltung A AG', inhalt, 'Der Briefkopf ist der eigene, auch mit Beispielwerten.')

    def test_fremder_vertrag_ist_404(self):
        for url in ('/neu/vorlagen/vorschau/', '/neu/vorlagen/probe-pdf/'):
            with self.subTest(url=url):
                r = self.client.post(url, self._daten(f'v:{self.b.vertrag.pk}'))
                self.assertEqual(r.status_code, 404)
                self.assertNotIn('Mieter B', r.content.decode('utf-8', 'ignore'))

    def test_fremde_bewerbung_ist_404(self):
        r = self.client.post('/neu/vorlagen/vorschau/', self._daten(f'b:{self.b.bewerbung.pk}'))
        self.assertEqual(r.status_code, 404)

    def test_probe_pdf(self):
        r = self.client.post('/neu/vorlagen/probe-pdf/', self._daten(f'v:{self.a.vertrag.pk}'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_vorschau_nur_mit_schreibrolle_und_post(self):
        self.assertEqual(self.client.get('/neu/vorlagen/vorschau/').status_code, 405)

    def test_umschalten_trifft_nur_die_eigene(self):
        from core.services.dokument_regeln import aktive_vorlage
        system = _vorlage(None, name='System')
        self.client.post('/neu/vorlagen/regel/umschalten/', {'ereignis': 'kuendigung_erfasst'})
        self.assertIsNone(aktive_vorlage('kuendigung_erfasst', organisation=self.a.organisation))
        self.assertEqual(aktive_vorlage('kuendigung_erfasst', organisation=self.b.organisation), system)
        system.refresh_from_db()
        self.assertTrue(system.aktiv)
        self.client.post('/neu/vorlagen/regel/umschalten/', {'ereignis': 'kuendigung_erfasst'})
        self.assertIsNotNone(aktive_vorlage('kuendigung_erfasst', organisation=self.a.organisation))


@override_settings(MEDIA_ROOT=MEDIA)
class BriefkopfTests(TestCase):
    """Gegenproben: den Validator `HEX_FARBE` am Feld entfernen →
    `test_farbe_wird_validiert` rot; in `fw_account` den Validatoraufruf
    entfernen → `test_account_lehnt_ungueltige_farbe_ab` rot; in
    `briefkopf_kontext` die Prüfung `_HEX.match` entfernen →
    `test_ungueltige_farbe_kommt_nicht_in_den_stilblock` rot."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_farbe_wird_validiert(self):
        org = Organisation(firma='X', strasse='s', plz='1', ort='o', briefkopf_farbe='rot')
        with self.assertRaises(ValidationError) as fehler:
            org.full_clean()
        self.assertIn('briefkopf_farbe', fehler.exception.message_dict)
        feld = Organisation._meta.get_field('briefkopf_farbe')
        for schlecht in ('rot', '#abc', '#1f6f5cc', '1f6f5c'):
            with self.subTest(farbe=schlecht), self.assertRaises(ValidationError):
                feld.run_validators(schlecht)
        for gut in ('#1f6f5c', '#ABCDEF'):
            feld.run_validators(gut)

    def test_account_speichert_und_lehnt_ungueltige_farbe_ab(self):
        self.client.force_login(self.a.benutzer)
        org = self.a.organisation
        basis = {'firma': org.firma, 'strasse': org.strasse, 'plz': org.plz, 'ort': org.ort}
        self.client.post('/neu/account/', {**basis, 'briefkopf_farbe': '#1f6f5c', 'briefkopf_fusszeile': 'HR CHE-1'})
        org.refresh_from_db()
        self.assertEqual((org.briefkopf_farbe, org.briefkopf_fusszeile), ('#1f6f5c', 'HR CHE-1'))
        self.client.post('/neu/account/', {**basis, 'briefkopf_farbe': 'red;}body{x', 'briefkopf_fusszeile': 'HR CHE-1'})
        org.refresh_from_db()
        self.assertEqual(org.briefkopf_farbe, '#1f6f5c')
        # Das Marktdaten-Formular schickt die Felder nicht mit — nichts geht verloren.
        self.client.post('/neu/account/', {**basis, 'aktueller_referenzzinssatz': '1.25'})
        org.refresh_from_db()
        self.assertEqual((org.briefkopf_farbe, org.briefkopf_fusszeile), ('#1f6f5c', 'HR CHE-1'))

    def test_ungueltige_farbe_kommt_nicht_in_den_stilblock(self):
        from core.services.briefkopf import briefkopf_kontext
        org = self.a.organisation
        org.briefkopf_farbe = 'red;}body{x'
        self.assertEqual(briefkopf_kontext(org)['farbe'], '')

    def test_dokument_traegt_farbe_und_fusszeile(self):
        from django.template.loader import get_template
        from core.services.vorlagen_pdf import dokument_kontext
        org = self.a.organisation
        org.briefkopf_farbe, org.briefkopf_fusszeile = '#1f6f5c', 'Handelsregister CHE-123'
        html = get_template('core/dok_vorlage.html').render(dokument_kontext(
            betreff='B', inhalt='T', format='text', sprache='de', kontext={}, organisation=org))
        self.assertIn('solid #1f6f5c', html)
        self.assertIn('Handelsregister CHE-123', html)
        self.assertIn('class="unterschrift"', html)

    def test_begleitdokumente_zum_vertrag_tragen_den_briefkopf(self):
        from core.services import dokument_service
        org = self.a.organisation
        org.briefkopf_fusszeile = 'Fuss A'
        org.save()
        gesehen = {}
        echt = dokument_service.get_template

        def abfangen(name):
            t = echt(name)
            alt = t.render

            def render(ctx=None, request=None):
                gesehen['html'] = alt(ctx, request)
                return gesehen['html']
            t.render = render
            return t
        with mock.patch.object(dokument_service, 'get_template', abfangen), \
                organisation_kontext(org):
            dokument_service.generate_dokument_pdf_bytes(self.a.vertrag, 'merkblatt-lueften')
        self.assertIn('Fuss A', gesehen['html'])
