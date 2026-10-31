"""Die Mandantenprüfung sieht nur Modelle, von denen B eine Zeile hat (SICH-27e).

BEFUND (Audit 28.10.2026)
`MandantenFixture` legt nur Objekte an, die beim Bau des Fixtures schon bekannt waren. Der Manager-Test
(`ManagerIsolationTests`) überspringt jedes Modell ohne Zeile bei B, und das ist richtig, weil er sonst nichts
beweisen könnte — aber es heisst: Von 123 Modellen mit Mandantenfilter hatten 53 keine Zeile im Fixture,
darunter Mahnung, Hypothek, Jahresabschluss, Zahlungsvereinbarung, Kreditorenzahlung, Eigentümerauszahlung,
Bankbewegung und das ganze Gerüst der STWEG-Abrechnung. Ein Leck dort wäre bei grüner Suite geblieben.

DAS FIXTURE SELBST ZU ERWEITERN IST HIER KEINE OPTION
Rund 100 Testdateien bauen auf `MandantenFixture` und zählen Zeilen, Abfragen und Listeneinträge. Eine Hypothek
mehr im Fixture verschiebt Zahlen in Tests, die davon nichts wissen (so geschehen bei einer zusätzlichen
Liegenschaft, siehe Kommentar in `_isolation.py`). Darum erweitert dieses Modul das Fixture NUR für die Läufe
unten (`ErweiterterBestand`), und die Wächter prüfen den Rest.

WAS DIESES MODUL GARANTIERT
1. Jedes Modell mit Mandantenfilter hat eine Zeile bei A und bei B — oder steht mit Begründung in
   `OHNE_ZEILE`. Ein neues Modell fällt hier auf, bis jemand es anlegt oder begründet.
2. Im Kontext von A liefert `Modell.objects` keine Zeile von B (und umgekehrt), für jedes Modell mit Zeile.
3. Ohne Kontext wirft der Manager auch für diese Modelle.

Gegenprobe: bei einem der Modelle (z. B. `finance.Mahnung`) den `TenantManager` durch `models.Manager()`
ersetzen: `test_manager_zeigt_keine_fremden_zeilen` wird rot. Ein neues Modell mit `organisation`-Feld ohne
Zeile hier: `test_jedes_mandantenmodell_hat_eine_zeile` wird rot.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps
from django.db import connection
from django.test import TestCase

from core.tenancy import ohne_organisation, organisation_kontext

from ._isolation import MandantenFixture
from .test_isolation import EIGENE_APPS, OHNE_MANDANTENFILTER

#: Modelle mit Mandantenfilter, für die dieses Modul bewusst keine Zeile anlegt. Jede Zeile ist eine Entscheidung
#: mit Grund; die Liste wird nie länger, ohne dass jemand den Grund liest.
OHNE_ZEILE = {
}


class ErweiterterBestand(MandantenFixture):
    """`MandantenFixture` plus je eine Zeile für die Modelle, die dort fehlen."""

    def _bestand_anlegen(self, plz, ort):
        super()._bestand_anlegen(plz, ort)
        self.fehlgeschlagen = {}
        self._zusatz()

    def _neu(self, name, bauer):
        """Legt ein Objekt an und merkt es unter `zusatz_<name>` (so findet es `_alle_objekte`)."""
        try:
            setattr(self, f'zusatz_{name}', bauer())
        except Exception as fehler:                       # noqa: BLE001 — wird unten gemeldet, nicht verschluckt
            self.fehlgeschlagen[name] = f'{type(fehler).__name__}: {fehler}'

    def _zusatz(self):
        from crm.models import MieterAdresse, ReferenzzinsStand
        from core.models import AktivitaetsLog, Archiveintrag, DatenExportEinstellung, DatenImportReferenz
        from finance.models import (Abschreibung, Anlage, AuszahlungsFreigabe, Bankbewegung, EigentuemerAuszahlung,
                                    Erneuerungsfonds,
                                    ErneuerungsfondsBewegung, Hypothek, Jahresabschluss, Kontoauszug,
                                    KreditorenZahlung, KreditorPosition, LieferantProfil, Mahnung,
                                    MietzinsKontrolle, NebenkostenBeleg, NebenkostenLernRegel, ZahlerZuordnung,
                                    Zahlungsvereinbarung)
        from portfolio.models import (EinheitFoto, Lebensdauer, LiegenschaftVerteilschluessel, Unterhalt,
                                      Verteilschluessel, ZaehlerStand)
        from rentals.models import (AbnahmeMangel, AbnahmePosition, AbnahmeSchluessel, AbnahmeText, Leerstand,
                                    Mietverfahren, VertragMietzins)
        from tickets.models import SchadenFoto, TicketNachricht, Versicherungsfall

        k = self.kuerzel
        heute = date(2025, 6, 1)
        org = self.organisation

        # --- Geld ---------------------------------------------------------------------------------------
        self._neu('mahnung', lambda: Mahnung.objects.create(organisation=org))
        self._neu('hypothek', lambda: Hypothek.objects.create(organisation=org, liegenschaft=self.liegenschaft))
        self._neu('jahresabschluss', lambda: Jahresabschluss.objects.create(
            organisation=org, liegenschaft=self.liegenschaft))
        self._neu('zahlungsvereinbarung', lambda: Zahlungsvereinbarung.objects.create(
            organisation=org, vertrag=self.vertrag, betrag_total=Decimal('1000'), gedeckt_bis=heute,
            anzahl_raten=4, erste_rate=heute))
        self._neu('kreditorenzahlung', lambda: KreditorenZahlung.objects.create(
            organisation=org, kreditor=self.kreditor, betrag=Decimal('500')))
        self._neu('eigentuemerauszahlung', lambda: EigentuemerAuszahlung.objects.create(
            organisation=org, eigentuemer=self.eigentuemer, betrag=Decimal('800')))
        self._neu('auszahlungsfreigabe', lambda: AuszahlungsFreigabe.objects.create(
            organisation=org, art='eigentuemer', bezug_id=self.eigentuemer.pk, betrag=Decimal('8000')))
        self._neu('bankbewegung', lambda: Bankbewegung.objects.create(
            organisation=org, konto=self.konto_soll, datum=heute, betrag=Decimal('100')))
        self._neu('kontoauszug', lambda: Kontoauszug.objects.create(organisation=org, konto=self.konto_soll))
        self._neu('nebenkostenbeleg', lambda: NebenkostenBeleg.objects.create(organisation=org, periode=self.periode))
        self._neu('mietzinskontrolle', lambda: MietzinsKontrolle.objects.create(
            organisation=org, liegenschaft=self.liegenschaft, monat=heute))
        self._neu('anlage', lambda: Anlage.objects.create(
            organisation=org, liegenschaft=self.liegenschaft, bezeichnung=f'Heizung {k}', anschaffungsdatum=heute))
        self._neu('abschreibung', lambda: Abschreibung.objects.create(
            organisation=org, anlage=self.zusatz_anlage, jahr=2025, datum=heute))
        self._neu('erneuerungsfonds', lambda: Erneuerungsfonds.objects.create(
            organisation=org, liegenschaft=self.liegenschaft))
        self._neu('erneuerungsfondsbewegung', lambda: ErneuerungsfondsBewegung.objects.create(
            organisation=org, fonds=self.zusatz_erneuerungsfonds, art='einlage', betrag=Decimal('100'), jahr=2025))
        self._neu('lieferantprofil', lambda: LieferantProfil.objects.create(
            organisation=org, name_key=f'handwerk-{k.lower()}', name_anzeige=f'Handwerk {k}'))
        self._neu('kreditorposition', lambda: KreditorPosition.objects.create(
            organisation=org, rechnung=self.kreditor, konto=self.konto_soll, betrag=Decimal('500')))
        self._neu('zahlerzuordnung', lambda: ZahlerZuordnung.objects.create(
            organisation=org, name_norm=f'mieter {k.lower()}', vertrag=self.vertrag))
        self._neu('nebenkostenlernregel', lambda: NebenkostenLernRegel.objects.create(
            organisation=org, suchwort=f'hauswart{k.lower()}', kategorie_zuweisung='hauswart'))

        # --- Abonnement (Funktionsfreigabe) --------------------------------------------------------------
        from abo.models import Abonnement
        self._neu('abonnement', lambda: Abonnement.alle_organisationen.create(organisation=org))

        # --- Personen und Verträge ------------------------------------------------------------------------
        self._neu('mieteradresse', lambda: MieterAdresse.objects.create(
            organisation=org, mieter=self.mieter, gueltig_ab=heute))
        self._neu('referenzzinsstand', lambda: ReferenzzinsStand.objects.create(
            organisation=org, stichtag=heute, satz=Decimal('1.25')))
        self._neu('leerstand', lambda: Leerstand.objects.create(organisation=org, einheit=self.einheit, beginn=heute))
        self._neu('mietverfahren', lambda: Mietverfahren.objects.create(organisation=org, vertrag=self.vertrag))
        self._neu('vertragmietzins', lambda: VertragMietzins.objects.create(
            organisation=org, vertrag=self.vertrag, gueltig_ab=heute))
        self._neu('abnahmemangel', lambda: AbnahmeMangel.objects.create(
            organisation=org, protokoll=self.abnahme, beschreibung=f'Kratzer {k}'))
        self._neu('abnahmeposition', lambda: AbnahmePosition.objects.create(
            organisation=org, protokoll=self.abnahme, raum='Bad', bezeichnung=f'Wand {k}'))
        self._neu('abnahmeschluessel', lambda: AbnahmeSchluessel.objects.create(
            organisation=org, protokoll=self.abnahme, bezeichnung=f'Haustür {k}'))
        self._neu('abnahmetext', lambda: AbnahmeText.objects.create(
            organisation=org, schluessel=f'text-{k.lower()}', text=f'Baustein {k}'))

        # --- Objekte und Meldungen --------------------------------------------------------------------------
        self._neu('unterhalt', lambda: Unterhalt.objects.create(
            organisation=org, liegenschaft=self.liegenschaft, titel=f'Fassade {k}'))
        self._neu('zaehlerstand', lambda: ZaehlerStand.objects.create(
            organisation=org, zaehler=self.zaehler, wert=Decimal('123.4')))
        self._neu('lebensdauer', lambda: Lebensdauer.objects.create(
            organisation=org, kategorie=f'kat-{k.lower()}', jahre=15))
        self._neu('verteilschluessel', lambda: Verteilschluessel.objects.create(
            organisation=org, einheit=self.einheit, kostenart='heizung'))
        self._neu('liegenschaftverteilschluessel', lambda: LiegenschaftVerteilschluessel.objects.create(
            organisation=org, liegenschaft=self.liegenschaft, kostenart='wasser'))
        self._neu('einheitfoto', lambda: EinheitFoto.objects.create(
            organisation=org, einheit=self.einheit, bild=f'einheit_fotos/{k}.jpg'))
        self._neu('ticketnachricht', lambda: TicketNachricht.objects.create(
            organisation=org, ticket=self.schaden, absender_name=f'Melder {k}', nachricht=f'Es tropft {k}'))
        self._neu('schadenfoto', lambda: SchadenFoto.objects.create(
            organisation=org, schaden=self.schaden, bild=f'schaden_fotos/{k}.jpg'))
        self._neu('versicherungsfall', lambda: Versicherungsfall.objects.create(
            organisation=org, ticket=self.schaden, gemeldet_am=heute))
        self._neu('aktivitaetslog', lambda: AktivitaetsLog.objects.create(organisation=org, aktion=f'Test {k}'))
        self._neu('archiveintrag', lambda: Archiveintrag.objects.create(
            organisation=org, typ='mieter', objekt_id=self.mieter.pk, archiviert_am=heute,
            aufbewahren_bis=heute + timedelta(days=3650)))
        self._neu('datenimportreferenz', lambda: DatenImportReferenz.objects.create(
            organisation=org, art='mieter', schluessel=f'M-{k}', objekt_id=self.mieter.pk))
        self._neu('datenexporteinstellung', lambda: DatenExportEinstellung.objects.create(organisation=org))

        # --- STWEG ----------------------------------------------------------------------------------------
        from stweg.models import (Anwesenheit, Stimme, StimmeEreignis, StwegAbrechnungAnteil, StwegAbrechnungKosten,
                                  StwegAbrechnungPosition, StwegBudgetPosition, StwegInkassoPosition,
                                  StwegKostenzuordnung, StwegSchluesselAnteil, StwegVersand, StwegVorgaben,
                                  StwegVorschreibung, ZirkularStimme, ZirkularVersand)
        self._neu('stweg_vorgaben', lambda: StwegVorgaben.objects.create(
            organisation=org, liegenschaft=self.liegenschaft))
        self._neu('stweg_anwesenheit', lambda: Anwesenheit.objects.create(
            organisation=org, versammlung=self.stweg_versammlung, einheit=self.einheit))
        self._neu('stweg_stimme', lambda: Stimme.objects.create(
            organisation=org, traktandum=self.stweg_traktandum, einheit=self.einheit, wert='ja'))
        self._neu('stweg_stimmeereignis', lambda: StimmeEreignis.objects.create(
            organisation=org, traktandum=self.stweg_traktandum, einheit=self.einheit, wert='ja', kanal='saal'))
        self._neu('stweg_abrechnungkosten', lambda: StwegAbrechnungKosten.objects.create(
            organisation=org, abrechnung=self.stweg_abrechnung, betrag=Decimal('1000')))
        self._neu('stweg_abrechnungposition', lambda: StwegAbrechnungPosition.objects.create(
            organisation=org, abrechnung=self.stweg_abrechnung, einheit=self.einheit, wertquote=Decimal('100'),
            wertquote_total=Decimal('1000'), kostenanteil=Decimal('100'), akonto=Decimal('90'),
            saldo=Decimal('10')))
        self._neu('stweg_abrechnunganteil', lambda: StwegAbrechnungAnteil.objects.create(
            organisation=org, position=self.zusatz_stweg_abrechnungposition, schluessel_name=f'Schlüssel {k}',
            gewicht=Decimal('1'), gewicht_total=Decimal('10'), kosten_total=Decimal('1000'),
            betrag=Decimal('100')))
        self._neu('stweg_budgetposition', lambda: StwegBudgetPosition.objects.create(
            organisation=org, budget=self.stweg_budget, bezeichnung=f'Hauswart {k}', schluessel=self.stweg_schluessel,
            betrag=Decimal('1200')))
        self._neu('stweg_inkassoposition', lambda: StwegInkassoPosition.objects.create(
            organisation=org, einheit=self.einheit, art='akonto', betrag=Decimal('100'), text=f'Akonto {k}'))
        self._neu('stweg_kostenzuordnung', lambda: StwegKostenzuordnung.objects.create(
            organisation=org, liegenschaft=self.liegenschaft, konto=self.konto_soll, schluessel=self.stweg_schluessel))
        self._neu('stweg_schluesselanteil', lambda: StwegSchluesselAnteil.objects.create(
            organisation=org, schluessel=self.stweg_schluessel, einheit=self.einheit, anteil=Decimal('1')))
        self._neu('stweg_versand', lambda: StwegVersand.objects.create(
            organisation=org, versammlung=self.stweg_versammlung, art='einladung', status='offen'))
        self._neu('stweg_vorschreibung', lambda: StwegVorschreibung.objects.create(
            organisation=org, budget=self.stweg_budget, einheit=self.einheit, rate_nr=1, rate_total=4,
            faellig_am=heute, betrag=Decimal('300'), jahresbetrag=Decimal('1200')))
        self._neu('stweg_zirkularstimme', lambda: ZirkularStimme.objects.create(
            organisation=org, zirkular=self.stweg_zirkular, einheit=self.einheit, wert='ja'))
        self._neu('stweg_zirkularversand', lambda: ZirkularVersand.objects.create(
            organisation=org, zirkular=self.stweg_zirkular, art='einladung', status='offen'))


def _modelle_mit_filter():
    """Alle Modelle der eigenen Apps mit Mandantenfilter UND vorhandener Tabelle.

    Die Tabelle gehört dazu: Im Gesamtlauf tragen Testmodule Modelle in die Registry ein, zu denen es nie eine
    Tabelle gibt (`core.Haus`, `core.Zimmer` aus `test_tenant_manager.py`); eine Abfrage darauf bricht ab
    (PostgreSQL: «relation does not exist»).
    """
    vorhanden = set(connection.introspection.table_names())
    return [m for m in apps.get_models()
            if m._meta.app_label in EIGENE_APPS and m._meta.label not in OHNE_MANDANTENFILTER
            and hasattr(m, 'alle_organisationen') and not m._meta.proxy and m._meta.db_table in vorhanden]


class Basis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = ErweiterterBestand('A', '8000', 'Zürich')
        cls.b = ErweiterterBestand('B', '3000', 'Bern')


class AbdeckungTests(Basis):

    def test_das_erweiterte_fixture_baut_alles(self):
        """Ohne diesen Test verschwänden Modelle still aus der Prüfung, sobald ein Feld Pflicht wird."""
        for bestand in (self.a, self.b):
            self.assertEqual(bestand.fehlgeschlagen, {},
                             'Zusatzobjekte, die sich nicht anlegen liessen (Feld neu Pflicht?): %s' % bestand.fehlgeschlagen)

    def test_jedes_mandantenmodell_hat_eine_zeile(self):
        ohne = []
        for modell in _modelle_mit_filter():
            if modell._meta.label in OHNE_ZEILE:
                continue
            if any(f.name == 'organisation' for f in modell._meta.concrete_fields):
                hat = modell.alle_organisationen.filter(organisation=self.b.organisation).exists()
            else:                                           # Mandant nur über die Kette: das Fixture muss die Zeile halten
                hat = any(isinstance(o, modell) for o in self.b._alle_objekte())
            if not hat:
                ohne.append(modell._meta.label)
        self.assertEqual(ohne, [], 'Modelle mit Mandantenfilter ohne Zeile im Isolationsbestand: Zeile in '
                                   'ErweiterterBestand._zusatz anlegen, oder in OHNE_ZEILE mit Grund eintragen. '
                                   'Sonst prüft die Isolation sie nie.')

    def test_ohne_zeile_gibt_es_noch(self):
        for label, grund in OHNE_ZEILE.items():
            with self.subTest(modell=label):
                apps.get_model(label)
                self.assertGreater(len(grund), 25, 'Begründung fehlt')


class IsolationTests(Basis):

    def test_manager_zeigt_keine_fremden_zeilen(self):
        """Im Kontext von A enthält `Modell.objects` nichts von B, im Kontext von B nichts von A."""
        geprueft = 0
        for modell in _modelle_mit_filter():
            for eigener, fremder in ((self.a, self.b), (self.b, self.a)):
                fremd = {o.pk for o in fremder._alle_objekte() if isinstance(o, modell)}
                eigen = {o.pk for o in eigener._alle_objekte() if isinstance(o, modell)}
                if not fremd:
                    continue
                geprueft += 1
                with self.subTest(modell=modell._meta.label, kontext=eigener.kuerzel):
                    with organisation_kontext(eigener.organisation):
                        sichtbar = set(modell.objects.values_list('pk', flat=True))
                    self.assertFalse(sichtbar & fremd, f'{modell._meta.label}.objects zeigt Zeilen der anderen Verwaltung')
                    self.assertTrue(eigen <= sichtbar, f'{modell._meta.label}.objects zeigt die eigenen Zeilen nicht')
        self.assertGreater(geprueft, 150, 'auffällig wenige Modelle geprüft — trägt der Bestand noch?')

    def test_ohne_kontext_wirft_der_manager_auch_bei_diesen_modellen(self):
        geworfen = 0
        for modell in _modelle_mit_filter():
            if not any(isinstance(o, modell) for o in self.a._alle_objekte()):
                continue
            with self.subTest(modell=modell._meta.label):
                with ohne_organisation():
                    with self.assertRaises(Exception):
                        list(modell.objects.all())
                geworfen += 1
        self.assertGreater(geworfen, 70)
