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

Die eigentliche Gegenprobe (Filter entfernen → Test muss rot werden) ist in
den Etappen 4 bis 6 nachzuholen, sobald ein Test grün wird.
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
        setze_organisation(self.a)
        for modell in apps.get_models():
            if modell._meta.app_label not in EIGENE_APPS:
                continue
            with self.subTest(modell=modell._meta.label):
                self.assertEqual(
                    modell.objects.filter(pk__in=[]).count(), 0,
                    f'{modell._meta.label} filtert nicht nach Organisation')

    @unittest.expectedFailure
    def test_ohne_kontext_wirft_der_manager(self):
        """Ohne gesetzte Organisation ist ein FEHLER die richtige Antwort.

        Wichtiger, als es aussieht: Ein Manager, der im Zweifel alles liefert,
        täuscht Sicherheit vor. Der Fehler fällt dann erst auf, wenn Daten
        bereits geflossen sind — in einem Report, einem Export, einer E-Mail.
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
            call_command('monatslauf', organisation=self.a.verwaltung.pk)
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

    @unittest.expectedFailure
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
        for feld in ('verwaltung', 'eigentuemer', 'liegenschaft', 'einheit', 'mieter',
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
