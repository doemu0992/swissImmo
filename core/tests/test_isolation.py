"""Isolationstests — Etappe 2, siehe docs/ETAPPE-2-ISOLATIONSTESTS.md.

Diese Tests beschreiben, was ab Phase 2 gelten MUSS: Kein Benutzer einer
Organisation kommt je an Daten einer anderen. Sie sind absichtlich VOR dem
`Organisation`-Modell entstanden (das ist Etappe 4) und scheitern deshalb
heute alle — jeder mit einer Aussage darüber, was fehlt.

WARUM `expectedFailure` UND NICHT EINFACH ROT
--------------------------------------------
Der Arbeitsauftrag verlangt „alle rot". Vierzig dauerhaft rote Tests würden
aber die CI blockieren, und eine rote CI, die alle für normal halten, ist
schlimmer als gar keine: Sie verdeckt den einundvierzigsten Fehler.

`expectedFailure` löst beides. Die Tests scheitern (das ist der Zweck), die
Suite bleibt benutzbar — und in dem Moment, in dem die Isolation gebaut ist,
meldet unittest einen „unexpected success" und lässt den Lauf fehlschlagen.
Der Marker muss dann entfernt werden. Der Übergang von rot nach grün ist
damit nicht dem Gedächtnis überlassen.

DIE FALLE DABEI, und wie sie entschärft ist
-------------------------------------------
Ein `expectedFailure`-Test, der aus dem FALSCHEN Grund scheitert — Tippfehler,
`AttributeError`, vergessener Import — wird ebenso still als „erwartet"
gezählt. Das wäre genau der Fehler, den diese Etappe verhindern soll, nur in
neuem Gewand.

Zwei Gegenmittel:

1. Jeder Test hier scheitert an einem `assert`, nicht an einer Exception. Die
   Fehlermeldungen wurden vor dem Setzen des Markers einzeln gelesen und im
   PR protokolliert.
2. `IsolationstestsSelbstpruefungTests` (unten, OHNE Marker) prüft, dass das
   Fixture baut und dass die Registry-Läufe überhaupt Fälle erzeugen. Bricht
   das Fixture, wird dieser Test rot — und nicht bloss vierzig weitere
   „erwartete" Fehlschläge mehr.

DIE GEGENPROBE — protokolliert, nicht behauptet
----------------------------------------------
Ein Test, der grün wird, beweist nichts, solange niemand geprüft hat, dass er
für die richtige Sache grün ist. Deshalb gilt ab Etappe 4: Wer einen Marker
entfernt, entfernt vorher den Filter und weist nach, dass der Test dann rot
wird.

Durchgeführt am 15.08.2026 (Etappe 4.2), je einmal Filter raus → rot,
Filter zurück → grün:

| Test | Entfernter Filter |
|---|---|
| `test_globaler_liegenschaftsfilter_nimmt_keine_fremde_id` | Besitzprüfung in `_global_filter` |
| `test_liegenschaftswaehler_zeigt_nur_eigene` | dieselbe |
| `test_registrylauf_ueber_parameterlose_urls` | dieselbe |
| `test_pdf_traegt_absender_der_eigenen_organisation` | `liegenschaft.organisation` in `pdf_service` |

EIN TEST WAR GRÜN UND PRÜFTE NICHTS
-----------------------------------
`test_default_manager_liefert_keine_fremden_daten` verglich
`modell.objects.filter(pk__in=[]).count()` mit 0 — für JEDES Modell trivial
wahr. Er war nur so lange rot, wie `core.tenancy` fehlte, und wurde grün in
dem Moment, in dem das Modul bloss importierbar war. Gefunden beim Anbinden
in 4.2, verschärft: Er prüft jetzt gegen die konkreten Datensätze von B.
"""

import unittest

from django.apps import apps
from django.test import Client, TestCase
from django.urls import NoReverseMatch, get_resolver, reverse

from ._isolation import KEINE_OBJEKT_ID, MandantenFixture

EIGENE_APPS = ('benutzer', 'core', 'crm', 'portfolio', 'rentals', 'finance', 'tickets',
               'mietprozess')

# ---------------------------------------------------------------------------
# Ausnahmen vom Registrylauf — benannt und begründet, nicht ausgefiltert.
#
# Jeder Eintrag ist eine Behauptung, die jemand später prüfen können muss.
# Deshalb steht neben jedem der Grund, nicht nur der Name.
# ---------------------------------------------------------------------------
AUSNAHMEN = {
    'geschuetzte_media':      'Pfad statt ID — wird in Bauform C von Hand geprüft',
    'public_bewerbung':       'bewusst öffentlich (Bewerbungsformular für Interessenten)',
    'public_datenschutz':     'bewusst öffentlich (Datenschutzerklärung, P5)',
    'public_ticket':          'bewusst öffentlich (Schadenmeldung ohne Login)',
    'fw_vermarktung_feed':    'token-gesichert, kein Login — eigener Test in Bauform C',
    'fw_kontoblatt':          'Kontonummer statt Objekt-ID — Bauform C',
    'portal_report':          'Eigentümer-Report, datensatzbezogen bereits isoliert',
}


def _urls_mit_einem_parameter():
    """Alle benannten URLs mit genau einem Parameter, aus der Registry.

    Datengetrieben und nicht abgetippt: Eine neue View ist damit automatisch
    mitgeprüft, ohne dass jemand daran denken muss. Am 15.08.2026 sind es 152.
    """
    gefunden = []
    for name, eintrag in get_resolver().reverse_dict.items():
        if not isinstance(name, str):
            continue
        for _pfad, params in eintrag[0]:
            if len(params) == 1:
                gefunden.append((name, params[0]))
            break
    return sorted(gefunden)


class IsolationsBasis(TestCase):
    """Gemeinsame Grundlage: zwei vollständige Bestände, angemeldet als A."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        # `raise_request_exception=False`: Stuerzt eine View ab, liefert der
        # Client einen 500 statt die Ausnahme durchzureichen. Sonst waere der
        # Registrylauf an der ersten kaputten View mit einem Traceback
        # abgebrochen — und unter `expectedFailure` haette niemand gesehen,
        # dass er die uebrigen 140 URLs nie erreicht hat.
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.a.benutzer)


# ===========================================================================
# Bauform A — Registrylauf über alle objektbezogenen URLs
# ===========================================================================

class FremdeIdUeberUrlsTests(IsolationsBasis):
    """Keine URL gibt ein fremdes Objekt heraus."""

    @unittest.expectedFailure
    def test_keine_fremde_id_ueber_benannte_urls(self):
        """Jede URL mit ID-Parameter liefert für ein fremdes Objekt 404.

        404 und nicht 403: Ein 403 bestätigt, dass der Datensatz existiert,
        und erlaubt über fortlaufende IDs das Abzählen fremder Bestände.
        `core/views/media_protected.py` macht das bereits richtig.
        """
        durchlaufen = 0
        for name, parameter in _urls_mit_einem_parameter():
            if name in AUSNAHMEN or parameter in KEINE_OBJEKT_ID:
                continue
            objekt = self.b.objekt_fuer(parameter, name)
            try:
                pfad = reverse(name, args=[objekt.pk])
            except NoReverseMatch:
                continue
            durchlaufen += 1
            with self.subTest(url=name):
                antwort = self.client.get(pfad)
                self.assertEqual(
                    antwort.status_code, 404,
                    f'{name} gibt ein Objekt von B an einen Benutzer von A heraus '
                    f'(Status {antwort.status_code}, erwartet 404)')
        self.assertGreater(durchlaufen, 100, 'auffällig wenige URLs geprüft')

    @unittest.expectedFailure
    def test_keine_fremde_id_ueber_schreibpfade(self):
        """Auch POST auf fremde IDs muss 404 liefern — nicht nur GET.

        Löschpfade sind erfahrungsgemäss am häufigsten ungeschützt und am
        teuersten, wenn sie es sind: Ein 302 bedeutet hier, dass der fremde
        Datensatz weg ist.
        """
        schreibend = [(n, p) for n, p in _urls_mit_einem_parameter()
                      if n not in AUSNAHMEN and p not in KEINE_OBJEKT_ID
                      and any(w in n for w in ('loeschen', 'stornieren', 'bearbeiten', 'form'))]
        self.assertGreater(len(schreibend), 20, 'Auswahl der Schreibpfade ist leer')
        for name, parameter in schreibend:
            objekt = self.b.objekt_fuer(parameter, name)
            try:
                pfad = reverse(name, args=[objekt.pk])
            except NoReverseMatch:
                continue
            with self.subTest(url=name):
                antwort = self.client.post(pfad, {})
                self.assertEqual(
                    antwort.status_code, 404,
                    f'{name} nimmt einen POST auf ein Objekt von B entgegen '
                    f'(Status {antwort.status_code})')


# ===========================================================================
# Bauform E — Filter aus dem Querystring
# ===========================================================================

#: ID-tragende Querystring-Parameter, am Bestand ausgezählt (15.08.2026).
#: `(URL-Name, Parameter, Fixture-Attribut, Kontextschlüssel, Fundstelle)`
#:
#: Der **URL-Name gehört dazu**. Die erste Fassung dieses Katalogs führte nur
#: den Parameter und prüfte alles gegen `fw_dashboard` — eine View, die
#: `?mieter=` gar nicht liest. Sie scheiterte trotzdem, weil `assertNotContains`
#: die blosse Ziffer „2" in jedem HTML findet (gemessen: 438-mal). Rot aus dem
#: falschen Grund ist derselbe Fehler wie grün aus dem falschen Grund, nur
#: schwerer zu bemerken: Der Test sieht erfolgreich aus, solange man ihn nicht
#: liest. Deshalb wird jetzt die View aufgerufen, die den Parameter wirklich
#: auswertet, und der **Kontextwert** geprüft, nicht der Seitentext.
ID_IM_QUERYSTRING = (
    ('fw_kommunikation', 'mieter',  'mieter',
     'vorwahl_mieter', 'core/views/fw/kommunikation.py:86'),
    ('fw_vertrag_neu',   'einheit', 'einheit',
     'vorwahl_einheit', 'core/views/fw/vertragserstellung.py:58'),
)


def _parameterlose_fw_urls():
    """Alle `fw_`-URLs OHNE Pfadparameter. Am 15.08.2026 sind es 108."""
    gefunden = []
    for name, eintrag in get_resolver().reverse_dict.items():
        if not isinstance(name, str) or not name.startswith('fw_'):
            continue
        for _pfad, params in eintrag[0]:
            if not params:
                gefunden.append(name)
            break
    return sorted(gefunden)


class FremdeIdUeberQuerystringTests(IsolationsBasis):
    """Die Lücke, die Bauform A prinzipbedingt nicht sieht.

    Bauform A sammelt über `_urls_mit_einem_parameter()` nur URLs mit genau
    einem **Pfad**parameter — am 15.08.2026 sind das 152. Daneben stehen 108
    parameterlose `fw_`-URLs, die ihre Filter aus dem **Querystring** lesen.
    Die lagen vollständig ausserhalb der Abdeckung.

    Aufgefallen ist das erst beim `mandanten-auditor`-Lauf über Etappe 3, also
    zwei Etappen nach dem Schreiben der Tests. Der Grund ist lehrreich: Bauform
    A ist datengetrieben und deckt deshalb „alle URLs" ab — aber nur alle URLs
    ihrer eigenen Bauform. Eine Registry-Abfrage sieht nie, wonach sie nicht
    fragt. Wer aus „152 von 152 geprüft" auf Vollständigkeit schliesst, hat die
    Frage mit der Antwort verwechselt.

    Ohne diese Bauform würde Etappe 4 gegen eine Abdeckung abgenommen, die den
    Haupteinstiegspunkt `_global_filter` nicht enthält.

    Gemessen am 15.08.2026: Von 107 geprüften parameterlosen `fw_`-URLs
    übernehmen **61** die Liegenschaft von B, wenn ein Benutzer von A sie mit
    deren `?lg=` aufruft. Die übrigen 46 werten den Filter schlicht nicht aus.
    """

    def test_globaler_liegenschaftsfilter_nimmt_keine_fremde_id(self):
        """`?lg=` einer fremden Liegenschaft darf nicht greifen.

        `_global_filter` liest die ID heute ohne Besitzprüfung
        (`Liegenschaft.objects.filter(id=lg_id).first()`). Er ist der Einstieg
        **aller 33 View-Module** — greift er auf eine fremde Liegenschaft, sind
        Bezeichnung und Adresse in jeder Kopfzeile sichtbar, und jede
        nachgelagerte Auswertung rechnet auf fremdem Bestand.
        """
        antwort = self.client.get(reverse('fw_dashboard'), {'lg': self.b.liegenschaft.pk})
        aktive = (antwort.context or {}).get('aktive_lg')
        self.assertIsNone(
            aktive,
            f'_global_filter übernimmt die Liegenschaft von B (?lg='
            f'{self.b.liegenschaft.pk}) für einen Benutzer von A')

    def test_liegenschaftswaehler_zeigt_nur_eigene(self):
        """Die Auswahlliste selbst ist bereits ein Leck.

        `_global_filter` legt `alle_liegenschaften` ungefiltert in den Kontext
        (`Liegenschaft.objects.all()`). Damit steht die Adresse jeder fremden
        Liegenschaft im Auswahlmenü — ohne dass jemand eine ID raten müsste.
        """
        antwort = self.client.get(reverse('fw_dashboard'))
        sichtbar = {lg.pk for lg in (antwort.context or {}).get('alle_liegenschaften', [])}
        self.assertNotIn(
            self.b.liegenschaft.pk, sichtbar,
            'die Liegenschaft von B steht im Auswahlmenü eines Benutzers von A')

    def test_registrylauf_ueber_parameterlose_urls(self):
        """Keine der 108 parameterlosen `fw_`-URLs übernimmt ein fremdes `?lg=`.

        Datengetrieben wie Bauform A: Eine neue View ist automatisch
        mitgeprüft. Geprüft wird der Kontext, nicht der Statuscode — eine View,
        die 200 liefert und dabei auf fremdem Bestand rechnet, ist der
        gefährlichere Fall.
        """
        durchlaufen = 0
        auffaellig = []
        for name in _parameterlose_fw_urls():
            if name in AUSNAHMEN:
                continue
            try:
                pfad = reverse(name)
            except NoReverseMatch:
                continue
            durchlaufen += 1
            antwort = self.client.get(pfad, {'lg': self.b.liegenschaft.pk})
            aktive = (antwort.context or {}).get('aktive_lg')
            if aktive is not None and aktive.pk == self.b.liegenschaft.pk:
                auffaellig.append(name)
        self.assertGreater(durchlaufen, 90, 'auffällig wenige URLs geprüft')
        self.assertEqual(
            auffaellig, [],
            f'{len(auffaellig)} von {durchlaufen} URLs rechnen auf der '
            f'Liegenschaft von B: {auffaellig[:8]}…')

    @unittest.expectedFailure
    def test_logbuch_filtert_nicht_auf_fremden_benutzer(self):
        """`/neu/logbuch/?benutzer=<B>` darf keine fremden Einträge zeigen.

        `AktivitaetsLog` hat keinen Organisationsbezug, und die ID kommt
        ungeprüft aus `request.GET` in ein `filter()`. Der Audit-Trail ist in
        Regel 4 des Skills `mandantentrennung` ausdrücklich genannt.
        """
        from core.models import AktivitaetsLog
        AktivitaetsLog.objects.create(benutzer=self.b.benutzer, aktion='test',
                                      objekt='B-Vorgang', details='gehört B')
        antwort = self.client.get(reverse('fw_logbuch'), {'benutzer': self.b.benutzer.pk})
        self.assertNotContains(
            antwort, 'B-Vorgang',
            msg_prefix='das Logbuch von A zeigt einen Vorgang von B')

    @unittest.expectedFailure
    def test_csv_export_enthaelt_keine_fremden_daten(self):
        """Der Export zieht heute den gesamten Audit-Trail.

        Regel 4: „Exporte enthalten nur Daten einer Organisation, auch wenn der
        Auslöser Superuser ist." Ein Export ist der Fall, in dem ein Leck nicht
        angesehen, sondern mitgenommen wird.
        """
        from core.models import AktivitaetsLog
        AktivitaetsLog.objects.create(benutzer=self.b.benutzer, aktion='test',
                                      objekt='B-Export', details='gehört B')
        antwort = self.client.get(reverse('fw_logbuch'), {'export': 'csv'})
        inhalt = b''.join(antwort.streaming_content) if antwort.streaming \
            else antwort.content
        self.assertNotIn(
            b'B-Export', inhalt,
            'der CSV-Export von A enthält einen Vorgang von B')

    @unittest.expectedFailure
    def test_uebrige_id_parameter_im_querystring(self):
        """Die restlichen ID-tragenden Querystring-Parameter, gesammelt.

        Nicht einzeln ausgeschrieben, weil die Liste wächst: Wer einen neuen
        `request.GET.get('<etwas>')`-Filter einbaut, der eine ID trägt, ergänzt
        `ID_IM_QUERYSTRING` und bekommt die Prüfung geschenkt.

        Geprüft wird der Kontextwert der View, die den Parameter auswertet —
        nicht der Seitentext. Ein Substring-Vergleich auf eine Ziffer findet in
        jedem HTML einen Treffer und wäre ein Test, der immer rot ist und
        nichts zeigt.
        """
        self.assertTrue(ID_IM_QUERYSTRING, 'Katalog der Querystring-Parameter ist leer')
        for url_name, parameter, attribut, schluessel, fundstelle in ID_IM_QUERYSTRING:
            fremd = getattr(self.b, attribut)
            with self.subTest(url=url_name, parameter=parameter):
                antwort = self.client.get(reverse(url_name), {parameter: fremd.pk})
                self.assertEqual(antwort.status_code, 200,
                                 f'{fundstelle}: unerwarteter Status')
                uebernommen = (antwort.context or {}).get(schluessel)
                # Die Views legen teils die ID, teils das Objekt ab.
                if uebernommen is not None and not isinstance(uebernommen, int):
                    uebernommen = getattr(uebernommen, 'pk', uebernommen)
                self.assertNotEqual(
                    uebernommen, fremd.pk,
                    f'{fundstelle}: ?{parameter}={fremd.pk} von B wird für einen '
                    f'Benutzer von A übernommen (Kontext «{schluessel}»)')


# ===========================================================================
# Bauform B — Registrylauf über alle Modelle
# ===========================================================================

class ManagerIsolationTests(IsolationsBasis):
    """Die Isolation muss im ORM sitzen, nicht erst in der View."""

    @unittest.expectedFailure
    def test_default_manager_liefert_keine_fremden_daten(self):
        """Im Kontext von A enthält `Model.objects.all()` nichts von B.

        Die View-Ebene allein genügt nicht: Ein vergessener Filter in einem
        Report, einem Command oder einem PDF-Bau umgeht sie. Deshalb muss der
        Manager filtern, und die View ist nur die zweite Schicht.
        """
        try:
            from core.tenancy import setze_organisation
        except ImportError:
            self.fail('core.tenancy fehlt — der TenantManager ist Etappe 4. '
                      'Dieser Test beschreibt, was er koennen muss.')
        setze_organisation(self.a.organisation)
        # Die erste Fassung prüfte `modell.objects.filter(pk__in=[]).count() == 0`.
        # Das ist für JEDES Modell trivial wahr — eine leere ID-Liste liefert
        # immer null Treffer. Der Test war rot, solange `core.tenancy` fehlte,
        # und wurde in dem Moment grün, in dem das Modul bloss importierbar
        # war: grün, ohne dass irgendetwas filtert. Genau die Falle, vor der
        # der Arbeitsauftrag warnt, nur diesmal in einem Test, der die Falle
        # selbst finden sollte.
        #
        # Jetzt wird gegen die konkreten Datensätze von B geprüft. Ein Modell
        # ohne Objekt bei B kann nichts beweisen und wird übersprungen —
        # sichtbar über den Zähler unten, nicht stillschweigend.
        geprueft = 0
        for modell in apps.get_models():
            if modell._meta.app_label not in EIGENE_APPS:
                continue
            fremde = [o for o in getattr(self.b, '_alle_objekte', lambda: [])()
                      if isinstance(o, modell)]
            if not fremde:
                continue
            geprueft += 1
            with self.subTest(modell=modell._meta.label):
                sichtbar = set(modell.objects.values_list('pk', flat=True))
                fremd_pks = {o.pk for o in fremde}
                self.assertFalse(
                    sichtbar & fremd_pks,
                    f'{modell._meta.label}.objects zeigt im Kontext von A '
                    f'{len(sichtbar & fremd_pks)} Datensätze von B')
        self.assertGreater(geprueft, 8,
                           'auffällig wenige Modelle geprüft — trägt das Fixture noch?')

    def test_ohne_kontext_wirft_der_manager(self):
        """Ohne gesetzte Organisation ist ein FEHLER die richtige Antwort.

        Wichtiger, als es aussieht: Ein Manager, der im Zweifel alles liefert,
        täuscht Sicherheit vor. Der Fehler fällt dann erst auf, wenn Daten
        bereits geflossen sind — in einem Report, einem Export, einer E-Mail.

        **GRÜN SEIT ETAPPE 6.2 (17.08.2026)** — der erste der dreizehn.
        `expectedFailure` ist entfernt; ab jetzt ist ein Fehlschlag hier ein
        echter Rückschritt und kein bekannter Zustand mehr.

        Gegenprobe durchgeführt: Mit `objects = models.Manager()` in
        `core/organisation_kette.py` (dem Stand vor dem Umlegen) scheitert er
        wieder — `list(...)` liefert dann die Verträge beider Verwaltungen,
        statt zu werfen.
        """
        try:
            from core.tenancy import ohne_organisation
        except ImportError:
            self.fail('core.tenancy fehlt — ohne_organisation() ist Etappe 4.')
        from rentals.models import Mietvertrag
        with ohne_organisation():
            with self.assertRaises(Exception):
                list(Mietvertrag.objects.all())


# ===========================================================================
# Bauform C — handgeschrieben, wo Registry nicht trägt
# ===========================================================================

class UniqueConstraintsProOrganisationTests(IsolationsBasis):
    """Sechs Felder sind heute global eindeutig und müssen es je Organisation sein.

    Gemessen am Bestand: Es gibt zwölf Eindeutigkeits-Zusicherungen, sechs
    davon sind über einen Fremdschlüssel gebunden und deshalb unkritisch.
    Diese sechs sind es nicht — zwei Verwaltungen können heute kein
    gemeinsames Konto 4000 führen.
    """

    #: Feld → welcher fachliche Vorgang daran scheitert
    BETROFFEN = {
        'finance.Buchungskonto.nummer':        'beide Verwaltungen brauchen ein Konto 4000',
        'finance.Buchung.beleg_nr':            'der Belegnummernkreis zählt je Organisation',
        'finance.LieferantProfil.name_key':    'derselbe Lieferant bei zwei Verwaltungen',
        'finance.NebenkostenLernRegel.suchwort': 'dasselbe Suchwort, andere Lernregel',
        'finance.ZahlerZuordnung.name_norm':   'derselbe Zahlername bei zwei Verwaltungen',
        'portfolio.Lebensdauer.kategorie':     'eigene Lebensdauertabelle je Organisation',
    }

    @unittest.expectedFailure
    def test_gleiche_kontonummer_in_beiden_organisationen(self):
        from django.db import IntegrityError, transaction
        from finance.models import Buchungskonto
        Buchungskonto.objects.create(nummer='4000', bezeichnung='Aufwand A', typ='aufwand')
        try:
            with transaction.atomic():
                Buchungskonto.objects.create(nummer='4000', bezeichnung='Aufwand B',
                                             typ='aufwand')
        except IntegrityError:
            self.fail('Buchungskonto.nummer ist global eindeutig — zwei '
                      'Verwaltungen koennen kein gemeinsames Konto 4000 fuehren.')
        self.assertEqual(Buchungskonto.objects.filter(nummer='4000').count(), 2,
                         'Konto 4000 ist global eindeutig — je Organisation muss es gehen')

    @unittest.expectedFailure
    def test_belegnummernkreis_zaehlt_je_organisation(self):
        """Beide Organisationen muessen einen Beleg Nr. 1 fuehren koennen.

        Die erste Fassung dieses Tests verglich nur, ob alle vergebenen
        Belegnummern verschieden sind — das ist trivial wahr, solange
        `beleg_nr` global eindeutig ist. Er war gruen und prueft nichts;
        `expectedFailure` hat ihn als "unexpected success" aufgedeckt.
        Jetzt wird der eigentliche Vorgang versucht.
        """
        from django.db import IntegrityError, transaction
        from finance.models import Buchung
        Buchung.objects.filter(beleg_nr=1).delete()
        self.a.buchung.beleg_nr = 1
        self.a.buchung.save(update_fields=['beleg_nr'])
        try:
            with transaction.atomic():
                self.b.buchung.beleg_nr = 1
                self.b.buchung.save(update_fields=['beleg_nr'])
        except IntegrityError:
            self.fail('Buchung.beleg_nr ist global eindeutig — der '
                      'Belegnummernkreis muss je Organisation zaehlen.')


class HintergrundjobsTests(IsolationsBasis):
    """Ein Lauf für A darf den Bestand von B nicht anfassen.

    18 Management-Commands laufen über den Scheduler. Sie sind der Pfad, der
    beim Bauen am leichtesten vergessen wird, weil kein Benutzer und kein
    Request beteiligt ist — und damit auch keine Middleware, die einen
    Organisationskontext setzen könnte.
    """

    @unittest.expectedFailure
    def test_monatslauf_laesst_fremden_bestand_unberuehrt(self):
        from django.core.management import call_command
        from finance.models import DebitorenRechnung
        vorher = set(DebitorenRechnung.objects.filter(
            vertrag__einheit__liegenschaft=self.b.liegenschaft).values_list('pk', flat=True))
        try:
            call_command('monatslauf', organisation=self.a.organisation.pk)
        except TypeError:
            self.fail('monatslauf kennt keine Option --organisation und laeuft '
                      'damit ueber ALLE Bestaende (Etappe 6).')
        nachher = set(DebitorenRechnung.objects.filter(
            vertrag__einheit__liegenschaft=self.b.liegenschaft).values_list('pk', flat=True))
        self.assertEqual(vorher, nachher,
                         'monatslauf hat Rechnungen im Bestand von B erzeugt oder verändert')


class AbsenderInDokumentenTests(IsolationsBasis):
    """Ein PDF für einen Datensatz von B trägt nie den Absender von A.

    Deckt die `Verwaltung.objects.first()`-Stellen ab: Bei mehreren
    Organisationen versendet die Anwendung sonst alle Dokumente im Namen
    derjenigen Verwaltung mit dem niedrigsten Primärschlüssel.
    """

    def test_pdf_traegt_absender_der_eigenen_organisation(self):
        # Die erste Fassung suchte die Byte-Folge b'Verwaltung A AG' im PDF —
        # und war gruen, weil PDF den Text komprimiert und eine Byte-Suche ihn
        # nie findet. Ein Test, der nur deshalb besteht, weil er nicht
        # hinsieht. Jetzt wird der Text extrahiert.
        import io

        import pdfplumber

        from core.services.pdf_service import generate_vertrag_pdf_bytes
        pdf = generate_vertrag_pdf_bytes(self.b.vertrag)
        with pdfplumber.open(io.BytesIO(pdf)) as dok:
            text = '\n'.join((seite.extract_text() or '') for seite in dok.pages)
        self.assertNotIn('Verwaltung A', text,
                         'Das PDF eines Vertrags von B nennt die Verwaltung von A '
                         'als Absender (Verwaltung.objects.first())')
        self.assertIn('Verwaltung B', text,
                      'Das PDF eines Vertrags von B nennt seine eigene Verwaltung nicht')


class AdminUmgehungTests(IsolationsBasis):
    """Der Admin ist seit E2 lesend — er darf aber auch nichts Fremdes ZEIGEN.

    Django geht im Admin über `_base_manager`, nicht über `objects`. Ein
    `TenantManager` auf `objects` greift dort also nicht. Das ist zu prüfen,
    nicht anzunehmen.
    """

    @unittest.expectedFailure
    def test_admin_zeigt_keine_fremden_datensaetze(self):
        from django.contrib import admin
        from rentals.models import Mietvertrag
        modeladmin = admin.site._registry[Mietvertrag]
        anfrage = self.client.get('/admin/').wsgi_request
        anfrage.user = self.a.benutzer
        sichtbar = modeladmin.get_queryset(anfrage)
        self.assertNotIn(self.b.vertrag, sichtbar,
                         'Der Admin zeigt einem Benutzer von A den Vertrag von B '
                         '(_base_manager umgeht den TenantManager)')


class CacheSchluesselTests(IsolationsBasis):
    """Ein Cache-Key ohne Organisations-ID ist ein Datenleck mit Verzögerung."""

    @unittest.expectedFailure
    def test_cache_schluessel_tragen_die_organisation(self):
        try:
            from core.tenancy import cache_key
        except ImportError:
            self.fail('core.tenancy.cache_key fehlt — Cache-Keys tragen heute '
                      'keine Organisation (Etappe 6).')
        self.assertNotEqual(cache_key('dashboard', self.a), cache_key('dashboard', self.b),
                            'Beide Organisationen benutzen denselben Cache-Key')


# ===========================================================================
# Bauform D — der Wächter
# ===========================================================================

class ModellbezugWaechterTests(TestCase):
    """Jedes Modell braucht einen Weg zur Organisation.

    Dieselbe Bauform wie `AdminNurLesendTests` (E2) und `FwFassadeTests`
    (Etappe 1): Der Test läuft über die Registry, nicht über eine gepflegte
    Liste. Wer in einem Jahr ein Modell hinzufügt und den Bezug vergisst,
    bekommt einen roten Test statt eines Datenlecks.
    """

    #: Modelle ohne eigenen Bezug — jeder Eintrag braucht eine Begründung.
    #: Der Zuschnitt entsteht erst in Etappe 5; eine vorweggenommene
    #: Ausnahmeliste wäre geraten, nicht entschieden. Genau ein Eintrag steht
    #: heute schon fest.
    BEGRUENDETE_AUSNAHMEN: dict = {
        # Der Benutzer gehört keiner Organisation, er ist in mehreren MITGLIED
        # — das ist Etappe 4, Schritt 4 (Rollen je Organisation). Ein Feld
        # `organisation` am Benutzer wäre die falsche Modellierung: Es würde
        # jeden Menschen auf eine Verwaltung festnageln.
        #
        # Der Eintrag steht hier und nicht in `EIGENE_APPS`, weil der Wächter
        # sonst SCHWEIGEND blind wäre. Fehlte `benutzer` in `EIGENE_APPS`,
        # würde dieser Test in Etappe 4 grün — und ausgerechnet das Modell,
        # an dem die Mandantenzugehörigkeit hängt, wäre das einzige, das er
        # nie prüft. Eine benannte Ausnahme kann man beim Lesen widerrufen,
        # eine fehlende Zeile in einem Tupel nicht.
        'benutzer.Benutzer': 'Mitgliedschaft je Organisation statt eigener Spalte — Etappe 4',
    }

    @unittest.expectedFailure
    def test_jedes_modell_hat_einen_weg_zur_organisation(self):
        ohne = []
        for modell in apps.get_models():
            if modell._meta.app_label not in EIGENE_APPS:
                continue
            if modell._meta.label in self.BEGRUENDETE_AUSNAHMEN:
                continue
            felder = {f.name for f in modell._meta.get_fields()}
            if 'organisation' not in felder:
                ohne.append(modell._meta.label)
        self.assertEqual(ohne, [],
                         f'{len(ohne)} Modelle ohne Organisationsbezug: {ohne[:8]}…')


# ===========================================================================
# Selbstprüfung — OHNE expectedFailure
# ===========================================================================

class IsolationstestsSelbstpruefungTests(TestCase):
    """Prüft die Isolationstests selbst — der einzige Test hier, der grün ist.

    Grund: `expectedFailure` zählt auch einen Fehlschlag aus dem FALSCHEN
    Grund als erwartet. Bricht das Fixture oder erzeugt der Registrylauf
    keine Fälle mehr, bliebe der Lauf still grün und diese Etappe wertlos.
    Diese Klasse macht genau das sichtbar.
    """

    def test_fixture_baut_zwei_getrennte_bestaende(self):
        a = MandantenFixture('A', '8000', 'Zürich')
        b = MandantenFixture('B', '3000', 'Bern')
        for feld in ('organisation', 'eigentuemer', 'liegenschaft', 'einheit', 'mieter',
                     'vertrag', 'buchung', 'debitor', 'kreditor', 'zahlung', 'periode',
                     'schaden', 'wartungsfrist', 'benutzer'):
            with self.subTest(feld=feld):
                self.assertNotEqual(getattr(a, feld).pk, getattr(b, feld).pk)

    def test_registrylauf_erzeugt_faelle(self):
        urls = _urls_mit_einem_parameter()
        self.assertGreaterEqual(len(urls), 150,
                                'Die URL-Registry liefert auffällig wenige Parameter-URLs')
        pruefbar = [(n, p) for n, p in urls
                    if n not in AUSNAHMEN and p not in KEINE_OBJEKT_ID]
        self.assertGreater(len(pruefbar), 100)

    def test_jeder_parameter_ist_zugeordnet(self):
        """Kein Parameter und kein URL-Name darf stillschweigend durchfallen.

        Das ist die Zusicherung, an der Bauform A hängt: Ein nicht
        zugeordneter Parameter würde die betroffene URL ungeprüft lassen —
        und der Registrylauf bliebe trotzdem grün.
        """
        b = MandantenFixture('B', '3000', 'Bern')
        ungeklaert = []
        for name, parameter in _urls_mit_einem_parameter():
            if name in AUSNAHMEN or parameter in KEINE_OBJEKT_ID:
                continue
            try:
                b.objekt_fuer(parameter, name)
            except LookupError as fehler:
                ungeklaert.append(f'{name} ({parameter}): {fehler}')
        self.assertEqual(ungeklaert, [],
                         f'{len(ungeklaert)} URLs ohne zuordenbares Objekt:\n' +
                         '\n'.join(ungeklaert[:12]))
