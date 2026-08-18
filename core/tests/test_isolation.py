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
    # Die objektbezogene Fassung MUSS die fremde Verwaltung nennen: Art. 19
    # revDSG verlangt, dass der Verantwortliche erkennbar ist, und
    # verantwortlich ist die Verwaltung DIESES Objekts. Sie hier zu verbergen
    # wäre nicht Datenschutz, sondern sein Gegenteil. Dass die richtige
    # genannt wird, prüft `test_oeffentliche_endpunkte_organisation.py`.
    'public_datenschutz_objekt': 'nennt den Verantwortlichen des Objekts — Art. 19 revDSG',
    'public_ticket':          'bewusst öffentlich (Schadenmeldung ohne Login)',
    # Der QR-Aushang im Treppenhaus. Er zeigt die Adresse des Hauses, in dem
    # er haengt, und nimmt von jedem Vorbeigehenden eine Meldung entgegen —
    # beides ist der Zweck, nicht ein Leck. Bis zum Audit vom 18.08.2026 fiel
    # er nicht auf, weil er seit Etappe 6.2 mit 500 antwortete und darum
    # weder etwas zeigte noch etwas anlegte.
    'public_report':          'QR-Aushang im Haus — oeffentlich by design',
    'fw_vermarktung_feed':    'token-gesichert, kein Login — eigener Test in Bauform C',
    'fw_kontoblatt':          'Kontonummer statt Objekt-ID — Bauform C',
    'portal_report':          'Eigentümer-Report, datensatzbezogen bereits isoliert',
}

# ---------------------------------------------------------------------------
# Die zwei Modelle, die KEINEN Mandantenfilter tragen können — und warum.
#
# Diese Liste ist die heikelste im ganzen Testsatz: Wer ein Modell hier
# einträgt, nimmt es aus der Prüfung. Genau so macht man einen Wächter blind.
# Deshalb steht neben jedem Eintrag der Grund, und deshalb prüft
# `AusnahmenSindBegruendetTests` unten, dass die Liste nicht wächst, ohne dass
# es jemand merkt. Ein drittes Modell hier einzutragen ist eine Entscheidung,
# keine Reparatur.
# ---------------------------------------------------------------------------
OHNE_MANDANTENFILTER = {
    # Der Benutzer gehört keiner Organisation, er ist in mehreren MITGLIED.
    # Ein Feld `organisation` am Benutzer wäre die falsche Modellierung: Es
    # würde jeden Menschen auf eine Verwaltung festnageln. Eine Treuhänderin,
    # die zwei Verwaltungen betreut, ist EIN Benutzer mit ZWEI
    # Mitgliedschaften. Gefiltert wird über `Mitgliedschaft` (Etappe 4.3).
    'benutzer.Benutzer': 'Mitgliedschaft je Organisation statt eigener Spalte',

    # Die Organisation IST der Mandant. Ein Filter `organisation=self` wäre
    # ein Selbstbezug ohne Aussage, und ein Filter auf den Kontext machte die
    # Tabelle unbrauchbar für genau die Läufe, die sie brauchen: Jede
    # Schleife über die Verwaltungen (`je_organisation`) liest sie, BEVOR ein
    # Kontext gesetzt ist. Wäre sie gefiltert, könnte kein Scheduler-Befehl
    # mehr die zweite Verwaltung finden.
    #
    # Das Leseinteresse ist damit nicht geschützt — wer angemeldet ist, kann
    # theoretisch die Firmennamen anderer Verwaltungen lesen. Das ist bewusst
    # in Kauf genommen und liegt auf der Ansichtsebene (die fw-Views zeigen
    # nur die eigene); auf der Modellebene ginge es nicht anders.
    'crm.Organisation': 'ist selbst der Mandant — ein Selbstbezug filtert nichts',

    # Das Betreiberlog. Es nimmt genau die Ereignisse auf, die KEINER
    # Verwaltung gehören: den Anmeldeversuch mit einem Benutzernamen, den es
    # gar nicht gibt. Der trifft die Installation, nicht einen Mandanten.
    #
    # DRITTER EINTRAG SEIT BESTEHEN DIESER LISTE, und er ist eine
    # Entscheidung, keine Reparatur (Entscheid 18.08.2026): Die Alternative
    # wäre gewesen, `AktivitaetsLog.organisation` nullbar zu machen. Dann
    # wäre aber ausgerechnet in der revisionsrelevanten Tabelle wieder
    # unklar, ob NULL «gehört niemandem» oder «wurde vergessen» heisst —
    # genau die Zweideutigkeit, die Etappe 5 aus dem Datenmodell entfernt
    # hat. Eine eigene Tabelle sagt es im Namen.
    'core.SicherheitsEreignis': 'Betreiberlog — Ereignisse ohne bestimmbaren Mandanten',
}


def _bestandszaehlung():
    """Zeilenzahl je Modell — der Vorher/Nachher-Vergleich für Schreibpfade.

    Über `alle_organisationen`, weil hier ausdrücklich der GANZE Bestand
    gemeint ist: Die Frage lautet „hat sich irgendwo etwas verändert", nicht
    „hat sich im eigenen Bestand etwas verändert".
    """
    stand = {}
    for modell in apps.get_models():
        if modell._meta.app_label not in EIGENE_APPS:
            continue
        manager = getattr(modell, 'alle_organisationen', None) or modell._base_manager
        try:
            stand[modell._meta.label] = manager.count()
        except Exception:                                      # noqa: BLE001
            pass
    return stand


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
    """Keine URL gibt ein fremdes Objekt heraus — und keine verändert eines.

    WARUM DIESE TESTS NICHT MEHR AUF 404 BESTEHEN (17.08.2026)

    Die erste Fassung verlangte für jede URL mit fremder ID exakt 404. Damit
    meldete sie 25 Fälle — und eine Messung Fall für Fall zeigte, dass die
    allermeisten davon keine sind: Sehr viele fw-Aktionen beginnen mit
    `if request.method != 'POST': return redirect(...)`. Der GET-Lauf bekommt
    dort 302, ohne dass die View das Objekt je angefasst hätte. Ein
    Portal-Pfad leitet einen Team-Benutzer nach `/mieter/` um, `hallway_poster`
    zur Admin-Anmeldung. Nichts davon gibt etwas heraus.

    Ein Test, der 20 harmlose Weiterleitungen anzeigt, wird irgendwann mit
    einer Ausnahmeliste beruhigt — und eine Ausnahmeliste mit 20 Einträgen ist
    eine Blindstelle mit 20 Einträgen. Deshalb fragen die Tests jetzt nach dem,
    worauf es ankommt:

    * **GET**: Es darf nichts von B im Ergebnis stehen. Ein 302 oder 404 ist
      dabei gleich gut; ein 200 mit fremden Daten ist der Befund. Und ein 500
      ist immer ein Befund, weil niemand weiss, wie weit die View kam.
    * **POST**: Der Bestand darf sich um KEINE ZEILE ändern — über alle
      Modelle gezählt, nicht nur am adressierten Datensatz. Genau daran hing
      der eigentliche Fund: Löschen und Bearbeiten fremder Benutzerkonten
      liefen durch, während beide „nur" ein 302 lieferten.

    So gefunden am 17.08.2026: `fw_benutzer_loeschen` löschte das Konto eines
    Menschen aus Verwaltung B samt seiner Mitgliedschaften,
    `fw_benutzer_bearbeiten` schrieb hinein und legte ihm eine Mitgliedschaft
    in A an. Beide hätten unter der 404-Regel in einer Liste mit 23 anderen
    gestanden.
    """

    #: Kennzeichen aus dem Bestand von B. Tauchen sie in einer Antwort auf,
    #: hat die View fremde Daten herausgegeben.
    #: `'Testgasse'` stand hier bis zum Audit vom 18.08.2026 — die Zeichenkette
    #: kommt im ganzen Projekt nur in dieser Zeile vor. Das Fixture legt B's
    #: Mieter unter `B-Gasse 2` an. Ein Drittel des Detektors konnte also nie
    #: feuern, und niemand haette es gemerkt: Ein Marker, der nichts findet,
    #: sieht genauso aus wie einer, der nichts zu finden hat.
    VERRAETERISCH = ('Verwaltung B', 'Mieter B', 'B-Gasse', 'B-Weg')

    def test_keine_fremde_id_gibt_fremde_daten_heraus(self):
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
                self.assertLess(
                    antwort.status_code, 500,
                    f'{name} stürzt bei einer fremden ID ab (Status '
                    f'{antwort.status_code}) — wie weit die View kam, ist damit offen.')
                if antwort.status_code != 200:
                    continue
                inhalt = antwort.content.decode('utf-8', 'ignore')
                verraten = [m for m in self.VERRAETERISCH if m in inhalt]
                self.assertEqual(
                    verraten, [],
                    f'{name} zeigt einem Benutzer von A Daten von B: {verraten}')
        self.assertGreater(durchlaufen, 100, 'auffällig wenige URLs geprüft')

    def test_kein_post_auf_eine_fremde_id_veraendert_den_bestand(self):
        """Kein Schreibpfad — auch keiner mit harmlos aussehendem 302.

        Gezählt wird über ALLE Modelle. Die erste Messung beobachtete nur den
        adressierten Datensatz und hätte eine Sammelabsage, eine
        Gegenbuchung oder eine angelegte Mitgliedschaft nicht gesehen.
        """
        for name, parameter in _urls_mit_einem_parameter():
            if name in AUSNAHMEN or parameter in KEINE_OBJEKT_ID:
                continue
            objekt = self.b.objekt_fuer(parameter, name)
            try:
                pfad = reverse(name, args=[objekt.pk])
            except NoReverseMatch:
                continue
            with self.subTest(url=name):
                vorher = _bestandszaehlung()
                self.client.post(pfad, {})
                nachher = _bestandszaehlung()
                geaendert = {k: (vorher[k], nachher[k])
                             for k in vorher if vorher[k] != nachher.get(k)}
                self.assertEqual(
                    geaendert, {},
                    f'{name} hat bei einem POST auf ein Objekt von B den Bestand '
                    f'verändert: {geaendert}')


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

    def test_logbuch_filtert_nicht_auf_fremden_benutzer(self):
        """`/neu/logbuch/?benutzer=<B>` darf keine fremden Einträge zeigen.

        `AktivitaetsLog` hat keinen Organisationsbezug, und die ID kommt
        ungeprüft aus `request.GET` in ein `filter()`. Der Audit-Trail ist in
        Regel 4 des Skills `mandantentrennung` ausdrücklich genannt.
        """
        from core.models import AktivitaetsLog
        # Die Organisation wird ausdruecklich gesetzt: `AktivitaetsLog` hat
        # nichts abzuleiten (sein einziger Fremdschluessel ist `benutzer`, und
        # der traegt keinen Bezug). Der Eintrag SOLL B gehoeren — das ist die
        # Voraussetzung des Tests, nicht sein Gegenstand.
        AktivitaetsLog.objects.create(benutzer=self.b.benutzer,
                                      organisation=self.b.organisation,
                                      aktion='test',
                                      objekt='B-Vorgang', details='gehört B')
        antwort = self.client.get(reverse('fw_logbuch'), {'benutzer': self.b.benutzer.pk})
        self.assertNotContains(
            antwort, 'B-Vorgang',
            msg_prefix='das Logbuch von A zeigt einen Vorgang von B')

    def test_csv_export_enthaelt_keine_fremden_daten(self):
        """Der Export darf nur den eigenen Audit-Trail mitnehmen.

        Regel 4: „Exporte enthalten nur Daten einer Organisation, auch wenn der
        Auslöser Superuser ist." Ein Export ist der Fall, in dem ein Leck nicht
        angesehen, sondern mitgenommen wird.

        **GRÜN SEIT ETAPPE 6.2 (17.08.2026)** — seit `AktivitaetsLog` den
        `TenantManager` trägt. Gegenprobe durchgeführt: Ohne ihn steht
        `B-Export` in der CSV von A.
        """
        from core.models import AktivitaetsLog
        AktivitaetsLog.objects.create(benutzer=self.b.benutzer,
                                      organisation=self.b.organisation,
                                      aktion='test',
                                      objekt='B-Export', details='gehört B')
        antwort = self.client.get(reverse('fw_logbuch'), {'export': 'csv'})
        inhalt = b''.join(antwort.streaming_content) if antwort.streaming \
            else antwort.content
        self.assertNotIn(
            b'B-Export', inhalt,
            'der CSV-Export von A enthält einen Vorgang von B')

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
            if modell._meta.label in OHNE_MANDANTENFILTER:
                # Nicht stillschweigend übersprungen: der Grund steht in
                # OHNE_MANDANTENFILTER, und `AusnahmenSindBegruendetTests`
                # merkt, wenn die Liste wächst.
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

    def test_gleiche_kontonummer_in_beiden_organisationen(self):
        """Beide Verwaltungen führen ein Konto 4000.

        Die erste Fassung legte beide Konten OHNE Mandantenkontext an. Seit
        6.2 bestimmt `organisation_bestimmen()` die Zugehörigkeit aus dem
        Kontext und wirft ohne — der Test scheiterte also, bevor er zur
        eigentlichen Frage kam, und sagte über die Eindeutigkeit nichts.
        Jetzt wird angelegt, wie es der Betrieb tut: je Verwaltung im
        eigenen Kontext.
        """
        from django.db import IntegrityError, transaction

        from core.tenancy import organisation_kontext
        from finance.models import Buchungskonto

        with organisation_kontext(self.a.organisation):
            Buchungskonto.objects.create(nummer='4000', bezeichnung='Aufwand A', typ='aufwand')
        try:
            with transaction.atomic(), organisation_kontext(self.b.organisation):
                Buchungskonto.objects.create(nummer='4000', bezeichnung='Aufwand B',
                                             typ='aufwand')
        except IntegrityError:
            self.fail('Buchungskonto.nummer ist global eindeutig — zwei '
                      'Verwaltungen koennen kein gemeinsames Konto 4000 fuehren.')

        self.assertEqual(
            Buchungskonto.alle_organisationen.filter(nummer='4000').count(), 2,
            'Konto 4000 ist global eindeutig — je Organisation muss es gehen')
        # Gegenprobe zur Sichtbarkeit: Jede Verwaltung sieht GENAU EIN 4000.
        # Ohne diese Zeile bewiese der Test nur, dass zwei Zeilen in der
        # Tabelle stehen — nicht, dass sie getrennt sind.
        for fixture, bezeichnung in ((self.a, 'Aufwand A'), (self.b, 'Aufwand B')):
            with organisation_kontext(fixture.organisation):
                treffer = list(Buchungskonto.objects.filter(nummer='4000'))
            self.assertEqual([k.bezeichnung for k in treffer], [bezeichnung])

        # Und die andere Hälfte des Nachweises: INNERHALB einer Verwaltung ist
        # 4000 weiterhin eindeutig. Ohne diese Zeile wäre der Test auch dann
        # grün, wenn die Eindeutigkeit ganz fehlte — dann könnte eine
        # Verwaltung zwei Konten 4000 führen, und die Buchhaltung wüsste bei
        # jeder Buchung nicht, welches gemeint ist.
        with self.assertRaises(IntegrityError), transaction.atomic(), \
                organisation_kontext(self.a.organisation):
            Buchungskonto.objects.create(nummer='4000', bezeichnung='Aufwand A zwei',
                                         typ='aufwand')

    def test_belegnummernkreis_zaehlt_je_organisation(self):
        """Beide Organisationen muessen einen Beleg Nr. 1 fuehren koennen.

        Das ist keine Kosmetik: OR 957a verlangt eine lückenlose,
        nachvollziehbare Belegfolge JE BUCHFÜHRUNG. Wäre `beleg_nr` global
        eindeutig, hätte die zweite Verwaltung eine Buchhaltung, die bei 4711
        beginnt und Lücken hat, wo die erste gebucht hat.

        Die erste Fassung dieses Tests verglich nur, ob alle vergebenen
        Belegnummern verschieden sind — trivial wahr, solange `beleg_nr`
        global eindeutig ist. Er war gruen und prueft nichts;
        `expectedFailure` hat ihn als "unexpected success" aufgedeckt. Die
        zweite Fassung versuchte den richtigen Vorgang, aber ohne
        Mandantenkontext und scheiterte deshalb schon am Manager.
        """
        from django.db import IntegrityError, transaction

        from core.tenancy import organisation_kontext
        from finance.models import Buchung

        # Nummer 1 freiräumen — aber NICHT die beiden Buchungen, die gleich
        # umnummeriert werden. Die erste Fassung löschte sie mit und scheiterte
        # danach an „Save with update_fields did not affect any rows".
        Buchung.alle_organisationen.filter(beleg_nr=1).exclude(
            pk__in=[self.a.buchung.pk, self.b.buchung.pk]).delete()
        with organisation_kontext(self.a.organisation):
            self.a.buchung.beleg_nr = 1
            self.a.buchung.save(update_fields=['beleg_nr'])
        try:
            with transaction.atomic(), organisation_kontext(self.b.organisation):
                self.b.buchung.beleg_nr = 1
                self.b.buchung.save(update_fields=['beleg_nr'])
        except IntegrityError:
            self.fail('Buchung.beleg_nr ist global eindeutig — der '
                      'Belegnummernkreis muss je Organisation zaehlen.')

        self.assertEqual(Buchung.alle_organisationen.filter(beleg_nr=1).count(), 2,
                         'Es steht nur ein Beleg Nr. 1 in der Tabelle.')

        # Andere Hälfte des Nachweises: INNERHALB einer Verwaltung bleibt die
        # Nummer eindeutig. Ohne sie wäre der Test auch bei ganz fehlender
        # Eindeutigkeit grün — und zwei Belege Nr. 1 in derselben Buchführung
        # sind genau das, was OR 957a ausschliesst.
        from datetime import date
        from decimal import Decimal

        with organisation_kontext(self.a.organisation):
            zweite = Buchung.objects.create(
                beleg_text='Zweite Buchung A', soll_konto=self.a.konto_soll,
                haben_konto=self.a.konto_haben, betrag=Decimal('42'), datum=date(2024, 2, 2))
        with self.assertRaises(IntegrityError), transaction.atomic(), \
                organisation_kontext(self.a.organisation):
            zweite.beleg_nr = 1
            zweite.save(update_fields=['beleg_nr'])


class HintergrundjobsTests(IsolationsBasis):
    """Ein Lauf für A darf den Bestand von B nicht anfassen.

    18 Management-Commands laufen über den Scheduler. Sie sind der Pfad, der
    beim Bauen am leichtesten vergessen wird, weil kein Benutzer und kein
    Request beteiligt ist — und damit auch keine Middleware, die einen
    Organisationskontext setzen könnte.
    """

    def test_monatslauf_laesst_fremden_bestand_unberuehrt(self):
        """Ein Lauf für A erzeugt keine Rechnung im Bestand von B.

        Die Abfragen laufen im Kontext von B — der Befehl selbst hat keinen,
        das ist gerade der Punkt. Ohne `organisation_kontext` scheiterte der
        Test schon am Manager und sagte über den Mietenlauf nichts.
        """
        from io import StringIO

        from django.core.management import call_command

        from core.tenancy import organisation_kontext
        from finance.models import DebitorenRechnung

        def bestand_von_b():
            with organisation_kontext(self.b.organisation):
                return set(DebitorenRechnung.objects.filter(
                    vertrag__einheit__liegenschaft=self.b.liegenschaft)
                    .values_list('pk', flat=True))

        vorher = bestand_von_b()
        try:
            call_command('monatslauf', organisation=self.a.organisation.pk,
                         stdout=StringIO(), stderr=StringIO())
        except TypeError:
            self.fail('monatslauf kennt keine Option --organisation und laeuft '
                      'damit ueber ALLE Bestaende (Etappe 6).')

        self.assertEqual(vorher, bestand_von_b(),
                         'monatslauf hat Rechnungen im Bestand von B erzeugt oder verändert')

        # Gegenprobe im Test selbst: Bei A MUSS etwas entstanden sein. Ohne
        # diese Zeile wäre der Test auch grün, wenn der Befehl gar nichts täte
        # — und ein Mietenlauf, der nichts stellt, ist kein Erfolg.
        with organisation_kontext(self.a.organisation):
            neu_bei_a = DebitorenRechnung.objects.filter(
                vertrag__einheit__liegenschaft=self.a.liegenschaft).count()
        self.assertGreater(neu_bei_a, 0,
                           'Der Lauf hat auch bei A nichts erzeugt — der Test '
                           'belegt dann keine Trennung, sondern Untätigkeit.')


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

    def test_admin_zeigt_keine_fremden_datensaetze(self):
        """Die Annahme im Klassennamen stimmt nicht — geprüft statt geglaubt.

        Erwartet war, dass `ModelAdmin.get_queryset` über `_base_manager`
        geht und den `TenantManager` damit umgeht. Django nimmt dort aber
        `_default_manager` (`django/contrib/admin/options.py:436`), also
        genau den gefilterten Manager. Die Umgehung, gegen die dieser Test
        geschrieben wurde, existiert nicht.
        """
        from django.contrib import admin

        from core.tenancy import organisation_kontext
        from rentals.models import Mietvertrag

        modeladmin = admin.site._registry[Mietvertrag]
        anfrage = self.client.get('/admin/').wsgi_request
        anfrage.user = self.a.benutzer

        with organisation_kontext(self.a.organisation):
            sichtbar = set(modeladmin.get_queryset(anfrage).values_list('pk', flat=True))

        # Der eigene Vertrag MUSS drin sein. Ohne diese Zeile wäre der Test
        # auch bei einer leeren Liste grün — und eine leere Liste beweist
        # nichts über Isolation.
        self.assertIn(self.a.vertrag.pk, sichtbar,
                      'Der Admin zeigt dem Benutzer nicht einmal den eigenen Vertrag — '
                      'ein leeres Ergebnis belegt keine Trennung.')
        self.assertNotIn(self.b.vertrag.pk, sichtbar,
                         'Der Admin zeigt einem Benutzer von A den Vertrag von B.')

    def test_admin_wirft_ohne_kontext_statt_alles_zu_zeigen(self):
        """Und ohne Kontext zeigt er gar nichts — er wirft.

        Das ist die schärfere Zusage: Ein Admin, der im Zweifel den ganzen
        Bestand zeigt, sieht funktionierend aus. Einer, der wirft, zwingt zur
        Entscheidung, wessen Daten gemeint sind.
        """
        from django.contrib import admin

        from core.tenancy import OrganisationsFehler, ohne_organisation
        from rentals.models import Mietvertrag

        modeladmin = admin.site._registry[Mietvertrag]
        anfrage = self.client.get('/admin/').wsgi_request
        anfrage.user = self.a.benutzer

        with ohne_organisation(), self.assertRaises(OrganisationsFehler):
            list(modeladmin.get_queryset(anfrage))


class CacheSchluesselTests(IsolationsBasis):
    """Ein Cache-Key ohne Organisations-ID ist ein Datenleck mit Verzögerung."""

    def test_cache_schluessel_tragen_die_organisation(self):
        """Derselbe Schlüsselname ergibt je Verwaltung einen anderen Key.

        Die erste Fassung rief `cache_key('dashboard', self.a)` — sie nahm
        an, die Organisation werde als Argument übergeben. `cache_key(*teile)`
        liest sie stattdessen aus dem Kontext, damit an keiner Aufrufstelle
        jemand vergessen kann, sie mitzugeben. Der Test rief also richtig
        auf, was es nicht gibt, und hängte die Verwaltung als Namensteil an.
        """
        from core.tenancy import cache_key, organisation_kontext

        with organisation_kontext(self.a.organisation):
            key_a = cache_key('dashboard')
        with organisation_kontext(self.b.organisation):
            key_b = cache_key('dashboard')

        self.assertNotEqual(key_a, key_b,
                            'Beide Organisationen benutzen denselben Cache-Key')
        self.assertIn(str(self.a.organisation.pk), key_a)

    def test_cache_key_wirft_ohne_kontext(self):
        # Ein Key ohne Organisations-ID ist genau der geteilte Key — der
        # erste Mandant füllt ihn, der zweite liest ihn. Kein stiller Rückfall
        # auf einen kontextlosen Namen.
        from core.tenancy import OrganisationsFehler, cache_key, ohne_organisation

        with ohne_organisation(), self.assertRaises(OrganisationsFehler):
            cache_key('dashboard')


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
    #:
    #: Seit 6.6 ist das dieselbe Liste, die `ManagerIsolationTests` benutzt.
    #: Zwei getrennte Listen wären zwei Orte, an denen jemand eine Ausnahme
    #: einträgt, und nur einer davon fiele beim Lesen auf.
    #:
    #: Die Einträge stehen dort und nicht in `EIGENE_APPS`, weil der Wächter
    #: sonst SCHWEIGEND blind wäre: Fehlte `benutzer` in `EIGENE_APPS`, wäre
    #: ausgerechnet das Modell, an dem die Mandantenzugehörigkeit hängt, das
    #: einzige, das er nie prüft. Eine benannte Ausnahme kann man beim Lesen
    #: widerrufen, eine fehlende Zeile in einem Tupel nicht.
    BEGRUENDETE_AUSNAHMEN: dict = OHNE_MANDANTENFILTER

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


class AusnahmenSindBegruendetTests(TestCase):
    """Die Ausnahmeliste darf nicht wachsen, ohne dass es jemand merkt.

    `OHNE_MANDANTENFILTER` ist die einzige Stelle, an der ein Modell aus der
    Prüfung fällt. Genau so macht man einen Wächter blind: Ein neues Modell
    ohne Bezug, ein Eintrag in die Liste, Test wieder grün — und niemand hat
    entschieden, nur repariert. Diese Klasse macht das Wachsen sichtbar.
    """

    def test_es_sind_genau_diese_zwei(self):
        self.assertEqual(sorted(OHNE_MANDANTENFILTER),
                         ['benutzer.Benutzer', 'core.SicherheitsEreignis',
                          'crm.Organisation'],
                         'Die Ausnahmeliste hat sich geändert. Das ist eine Entscheidung, '
                         'keine Reparatur: Grund in OHNE_MANDANTENFILTER schreiben und '
                         'diesen Test bewusst nachziehen.')

    def test_jeder_eintrag_traegt_eine_begruendung(self):
        for label, grund in OHNE_MANDANTENFILTER.items():
            self.assertGreater(len(grund), 25,
                               f'{label} steht ohne brauchbare Begründung in der Liste.')

    def test_die_ausgenommenen_modelle_gibt_es_wirklich(self):
        # Ein Tippfehler im Label nähme nichts aus — er täuschte nur vor,
        # etwas sei begründet, während der Wächter das Modell weiter prüft
        # (oder, schlimmer, ein anderes stillschweigend durchliesse).
        for label in OHNE_MANDANTENFILTER:
            apps.get_model(label)


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
