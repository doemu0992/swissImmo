"""Grundlage der Isolationstests (Etappe 2, siehe docs/ETAPPE-2-ISOLATIONSTESTS.md).

Zwei VOLLSTÄNDIGE Mandanten, A und B. Das ist die eigentliche Arbeit dieser
Etappe — ohne beide Bestände laufen die Registryläufe ins Leere, weil zu
vielen URL-Parametern kein Objekt existiert, und ein Test, der nichts
aufruft, ist grün und wertlos.

WICHTIG ZUM VERSTÄNDNIS: `Organisation` gibt es noch nicht (das ist Etappe 4).
Die beiden Bestände sind deshalb heute nur *fachlich* getrennt — zwei
Verwaltungen, zwei Eigentümer, zwei Liegenschaften, keine gemeinsamen
Datensätze. Die technische Grenze, die sie trennen wird, fehlt. Genau
deshalb sind alle Tests dieser Etappe rot: Sie beschreiben, was gelten
MUSS, bevor es jemand baut.

Sobald `Organisation` existiert, bekommt `MandantenFixture` je einen
`organisation`-Verweis und sonst nichts — der Rest dieses Moduls und alle
darauf aufbauenden Tests bleiben, wie sie sind.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model

from django.contrib.auth.models import Group

User = get_user_model()


# ---------------------------------------------------------------------------
# Parametername → Modell
#
# Diese Tabelle ist Absicht und keine Bequemlichkeit. Die Alternative wäre
# eine Namensheuristik ("alles, was auf _id endet, ist wohl das gleichnamige
# Modell") — und die schweigt genau dann, wenn sie sich irrt. Ein Parameter,
# der hier fehlt, MUSS auffallen; `objekt_fuer` wirft deshalb einen Fehler,
# statt still zu überspringen.
#
# Gemessen am Bestand (15.08.2026): 152 der 293 benannten URLs haben genau
# einen Parameter, verteilt auf diese zehn Namen.
# ---------------------------------------------------------------------------
PARAMETER_MODELL = {
    'pk':              None,          # uneinheitlich — siehe `objekt_fuer`
    'vertrag_id':      'vertrag',
    'einheit_id':      'einheit',
    'liegenschaft_id': 'liegenschaft',
    'lg_id':           'liegenschaft',
    'mieter_id':       'mieter',
    'periode_id':      'periode',
    'kreditor_id':     'kreditor',
    'nummer':          None,          # Kontonummer, keine Objekt-ID — Bauform C
    'pfad':            None,          # Dateipfad, keine Objekt-ID — Bauform C
    'zweck':           None,          # 'antworten'/'rechnungen' — keine Objekt-ID
}

# Die Parameter ohne Objektbezug. Sie sind KEINE Ausnahme im Sinne von
# „unkritisch": `pfad` ist der Media-Schutz, `nummer` das Kontoblatt und
# `zweck` der Postfach-Zweck — alle drei werden in Bauform C von Hand geprüft.
# Hier stehen sie nur, weil der Registrylauf mit ihnen nichts anfangen kann.
#
# `zweck` ist dabei der harmloseste der drei: Er ist eine feste Auswahl aus
# zwei Werten und trägt gar keine ID. Die Mandantentrennung der Postfächer
# hängt nicht an ihm, sondern am `TenantManager` — `Postfach.objects` liefert
# je Verwaltung höchstens ein Postfach dieses Zwecks. Geprüft in
# `core/tests/test_postfach.py` (PostfachMandantTests) und im Registrylauf
# über das Fixture-Postfach.
KEINE_OBJEKT_ID = {'nummer', 'pfad', 'zweck'}


class MandantenFixture:
    """Legt zwei vollständige, fachlich getrennte Bestände an.

    Wird von `setUpTestData` der Isolationstests aufgerufen. Kein TestCase,
    damit dieselbe Grundlage auch von einem Management-Command-Test oder
    einem ORM-Test benutzt werden kann, ohne von einer Testklasse zu erben.

    REIHENFOLGE IST BEDEUTSAM: A wird vollständig vor B angelegt, B hat
    deshalb durchweg höhere IDs. Ein Test, der `b.vertrag.pk` benutzt, trifft
    damit nie zufällig einen Datensatz von A — das ist erwünscht. Umgekehrt
    darf sich kein Test darauf VERLASSEN, dass B die höheren IDs hat; wer das
    tut, prüft die Reihenfolge des Fixtures statt die Isolation.
    """

    def __init__(self, kuerzel, plz, ort):
        self.kuerzel = kuerzel
        self._anlegen(plz, ort)

    def _anlegen(self, plz, ort):
        """Legt den Bestand an — jeden IM KONTEXT SEINER EIGENEN ORGANISATION.

        Seit Etappe 4.2 wirft der `TenantManager` ohne gesetzten Kontext. Das
        ist hier keine Hürde, sondern die richtige Semantik: Ein Bestand, der
        A gehört, entsteht als A. Würde das Fixture ohne Kontext bauen, wäre
        schon die Erzeugung eine Stelle, an der die Organisation offen bleibt —
        und genau solche Stellen sucht dieser Testsatz.

        Die `Organisation` selbst entsteht ausserhalb: Sie IST der Mandant,
        also kann sie keinen Mandantenkontext voraussetzen.
        """
        from core.tenancy import organisation_kontext
        from crm.models import Organisation as _Organisation

        k = self.kuerzel
        self.organisation = _Organisation.objects.create(
            firma=f'Verwaltung {k} AG', strasse=f'{k}-Strasse 1', plz=plz, ort=ort)
        with organisation_kontext(self.organisation):
            self._bestand_anlegen(plz, ort)

    def _bestand_anlegen(self, plz, ort):
        from crm.models import Eigentuemer, Mieter
        from finance.models import (AbrechnungsPeriode, Buchung, Buchungskonto,
                                    DebitorenRechnung, KreditorenRechnung, Zahlungseingang)
        from portfolio.models import Einheit, Liegenschaft, Wartungsfrist
        from rentals.models import Mietvertrag
        from tickets.models import SchadenMeldung

        k = self.kuerzel

        self.eigentuemer = Eigentuemer.objects.create(
            firma_oder_name=f'Eigentuemer {k}', email=f'eig-{k.lower()}@example.ch')
        self.liegenschaft = Liegenschaft.objects.create(
            strasse=f'{k}-Weg 7', plz=plz, ort=ort, eigentuemer=self.eigentuemer,
            organisation=self.organisation, versicherungswert=Decimal('1000000'))
        self.einheit = Einheit.objects.create(
            liegenschaft=self.liegenschaft, bezeichnung=f'3.5 Zi {k}', typ='wohnung',
            nettomiete_aktuell=Decimal('1500'), nebenkosten_aktuell=Decimal('200'))
        self.mieter = Mieter.objects.create(
            typ='person', vorname='Mieter', nachname=k, email=f'mieter-{k.lower()}@example.ch',
            strasse=f'{k}-Gasse 2', plz=plz, ort=ort)
        self.vertrag = Mietvertrag.objects.create(
            mieter=self.mieter, einheit=self.einheit, beginn=date(2024, 1, 1),
            netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
            status='aktiv', kautions_betrag=Decimal('4500'))

        # Kontenplan: bewusst NICHT über ensure_kontenplan(), weil der global
        # arbeitet. Zwei eigene Konten je Bestand — das ist zugleich die
        # Vorwegnahme des Unique-Constraint-Problems (Buchungskonto.nummer ist
        # heute global eindeutig, also können A und B kein gemeinsames 4000
        # führen; genau das prüft Bauform C).
        # Nummern aus dem 9000er-Bereich: Der erste Entwurf rechnete sie aus dem
        # Kürzel aus und traf damit 3600 — ein Konto aus STANDARD_KONTEN. Sobald
        # eine View `ensure_kontenplan()` aufrief, brach der Test mit einem
        # IntegrityError, der wie ein Isolationsbefund aussah und keiner war.
        self.konto_soll = Buchungskonto.objects.create(
            nummer=f'9{ord(k) - 64}01', bezeichnung=f'Bank {k}', typ='aktiv')
        self.konto_haben = Buchungskonto.objects.create(
            nummer=f'9{ord(k) - 64}02', bezeichnung=f'Ertrag {k}', typ='ertrag')
        self.buchung = Buchung.objects.create(
            beleg_text=f'Testbuchung {k}', soll_konto=self.konto_soll,
            haben_konto=self.konto_haben, betrag=Decimal('1500'), datum=date(2024, 2, 1))

        self.debitor = DebitorenRechnung.objects.create(
            vertrag=self.vertrag, titel=f'Miete 02/2024 {k}', betrag=Decimal('1700'),
            datum=date(2024, 2, 1), faellig_am=date(2024, 2, 28), status='offen')
        self.kreditor = KreditorenRechnung.objects.create(
            lieferant=f'Handwerk {k} GmbH', betrag=Decimal('500'),
            liegenschaft=self.liegenschaft, status='neu')
        self.zahlung = Zahlungseingang.objects.create(
            vertrag=self.vertrag, betrag=Decimal('1700'), datum_eingang=date(2024, 2, 20),
            buchungs_monat=date(2024, 2, 1), debitoren_rechnung=self.debitor)
        self.periode = AbrechnungsPeriode.objects.create(
            liegenschaft=self.liegenschaft, bezeichnung=f'HNK 2024 {k}',
            start_datum=date(2024, 1, 1), ende_datum=date(2024, 12, 31))

        self.schaden = SchadenMeldung.objects.create(
            liegenschaft=self.liegenschaft, betroffene_einheit=self.einheit,
            titel=f'Wasserschaden {k}', beschreibung=f'Leck im Bad ({k})')
        self.wartungsfrist = Wartungsfrist.objects.create(
            liegenschaft=self.liegenschaft, bezeichnung=f'Heizungsservice {k}',
            naechste_faelligkeit=date.today() + timedelta(days=30))

        self._anlegen_weitere(plz, ort)
        self.benutzer = self._benutzer()

    def _anlegen_weitere(self, plz, ort):
        """Die Objekte, die erst der Registrylauf einfordert.

        Die erste Fassung dieses Fixtures hatte 16 Modelle und wirkte
        vollständig. Der Selbstprüfungstest meldete dann 48 URLs, zu denen
        sich kein Objekt zuordnen liess — jede davon wäre ungeprüft geblieben.
        Welches Modell eine View lädt, wurde nicht geraten, sondern aus ihrem
        `get_object_or_404` abgelesen.
        """
        from crm.models import Handwerker, Kommunikation, Vorlage
        from core.models import Pendenz, Postfach
        from faelle.models import Fall, Fallart, Fallschritt, SchrittVorlage, Zeiteintrag
        from faelle.regelwerk_models import Regel, Regelanwendung, Regelsatz
        from faelle.zulauf_models import Eingang, Zuordnungsregel
        from mietprozess.models import Mietbewerbung
        from portfolio.models import (Ausstattung, Dokument as PDokument, Geraet, Schluessel,
                                      SchluesselAusgabe, Sollmietzins, StaffelVorlage,
                                      Versicherung, Zaehler)
        from rentals.models import (Abnahmeprotokoll, Dokument as RDokument, Kuendigung,
                                    MietzinsAnpassung, Staffelstufe)
        from tickets.models import HandwerkerAuftrag

        k = self.kuerzel
        self.abnahme = Abnahmeprotokoll.objects.create(vertrag=self.vertrag)
        self.anpassung = MietzinsAnpassung.objects.create(
            vertrag=self.vertrag, wirksam_ab=date(2025, 4, 1),
            neuer_netto_mietzins=Decimal('1550'))
        self.geraet = Geraet.objects.create(
            liegenschaft=self.liegenschaft, einheit=self.einheit,
            kategorie='sonstiges', sonstiges_bezeichnung=f'Waschmaschine {k}')
        self.ausstattung = Ausstattung.objects.create(
            einheit=self.einheit, raum='Bad', kategorie='sanitaer')
        self.bewerbung = Mietbewerbung.objects.create(
            einheit=self.einheit, vorname='Bewerber', nachname=k,
            geburtsdatum=date(1990, 5, 5), mobilnummer='079 000 00 00',
            email=f'bew-{k.lower()}@example.ch', beruf='Testperson',
            einkommen_jahr=Decimal('90000'))
        self.handwerker = Handwerker.objects.create(firma=f'Sanitaer {k} GmbH')
        self.dokument_portfolio = PDokument.objects.create(
            liegenschaft=self.liegenschaft, titel=f'Police {k}', datei=f'dok/{k}.pdf')
        self.dokument_rentals = RDokument.objects.create(
            vertrag=self.vertrag, datei=f'vertrag/{k}.pdf', kategorie='vertrag')
        self.kommunikation = Kommunikation.objects.create(
            mieter=self.mieter, vertrag=self.vertrag, inhalt=f'Notiz {k}')
        self.kuendigung = Kuendigung.objects.create(vertrag=self.vertrag)
        self.pendenz = Pendenz.objects.create(
            titel=f'Frist {k}', liegenschaft=self.liegenschaft)
        # Ohne Geheimnis angelegt: Der Registrylauf prüft SICHTBARKEIT, und
        # dafür braucht es keinen Schlüssel. Ein verschlüsseltes Passwort
        # hier hiesse, dass das ganze Fixture — und damit jeder Test, der es
        # benutzt — an einer gesetzten Umgebungsvariablen hinge.
        self.postfach = Postfach.objects.create(
            organisation=self.organisation, zweck=Postfach.ZWECK_RECHNUNGEN,
            server=f'imap.{k.lower()}.example.ch', benutzer=f'rechnungen@{k.lower()}.ch')
        self.schluessel = Schluessel.objects.create(
            liegenschaft=self.liegenschaft, schluessel_nummer=f'S-{k}-01')
        self.schluessel_ausgabe = SchluesselAusgabe.objects.create(
            schluessel=self.schluessel, mieter=self.mieter)
        self.sollmietzins = Sollmietzins.objects.create(
            einheit=self.einheit, gueltig_ab=date(2024, 1, 1),
            netto_mietzins=Decimal('1500'))
        self.staffel = Staffelstufe.objects.create(
            vertrag=self.vertrag, ab_datum=date(2026, 1, 1), netto_mietzins=Decimal('1600'))
        self.staffelvorlage = StaffelVorlage.objects.create(
            einheit=self.einheit, gueltig_ab=date(2026, 1, 1),
            netto_mietzins=Decimal('1600'))
        self.versicherung = Versicherung.objects.create(
            liegenschaft=self.liegenschaft, gesellschaft=f'Versicherung {k}')
        self.vorlage = Vorlage.objects.create(name=f'Mahnung {k}')
        self.zaehler = Zaehler.objects.create(
            einheit=self.einheit, liegenschaft=self.liegenschaft,
            typ='strom', zaehler_nummer=f'Z-{k}-1')
        self.auftrag = HandwerkerAuftrag.objects.create(
            ticket=self.schaden, handwerker=self.handwerker)

        # Fallmaschine (Phase 4a, Etappe 1). Ohne diese fünf Objekte laufen die
        # Registryprüfungen zwar über die neue App, finden aber keinen
        # Datensatz von B und überspringen jedes Modell — grün, ohne etwas
        # geprüft zu haben. `_alle_objekte` liest `vars(self)`, deshalb genügt
        # es, sie als Attribute abzulegen.
        self.fallart = Fallart.objects.create(
            organisation=self.organisation, schluessel='mieterwechsel',
            bezeichnung=f'Mieterwechsel {k}')
        self.schrittvorlage = SchrittVorlage.objects.create(
            fallart=self.fallart, nr=1, etappe_nr=1, etappe='Kündigung',
            bezeichnung='Kündigung erfassen')
        self.fall = Fall.objects.create(
            fallart=self.fallart, organisation=self.organisation,
            betreff=f'Mieterwechsel {k}')
        self.fallschritt = Fallschritt.objects.create(
            fall=self.fall, vorlage=self.schrittvorlage, nr=1, etappe_nr=1,
            etappe='Kündigung', bezeichnung='Kündigung erfassen')
        self.zeiteintrag = Zeiteintrag.objects.create(fall=self.fall, minuten=30)

        # Regelwerk (Phase 4a, Etappe 2) — aus demselben Grund wie oben. Die
        # Regelanwendung ist dabei die wichtigste der drei: Sie trägt die
        # geprüften Eingaben eines Mandanten, und ein Leck hier zeigte einer
        # Verwaltung die Kündigungsprüfungen einer anderen.
        self.regelsatz = Regelsatz.objects.create(
            organisation=self.organisation, bezeichnung=f'Regelsatz {k}',
            stand=date(2026, 8, 19))
        self.regel = Regel.objects.create(
            regelsatz=self.regelsatz, art=Regel.KUENDIGUNGSTERMIN,
            parameter={'termine': ['31.03', '30.06', '30.09'], 'frist_monate': 3})
        # Bewusst ein ÄLTERER Stand als der des Regelsatzes: So liegt diese
        # Anwendung nicht in der Kohorte, die ein Test über einen bestimmten
        # Stand abfragt — und sie bildet zugleich den realistischen Fall ab,
        # dass Protokolleinträge aus früheren Regelfassungen stammen.
        # Zulauf (Phase 4a, Etappe 3) — dritte Runde derselben Sache. Ohne
        # Objekte von B ueberspringt die Registry die Modelle und ist gruen,
        # ohne etwas geprueft zu haben. Die Zuordnungsregel ist dabei die
        # heikelste: Griffe sie ueber die Mandantengrenze, landete die Post
        # einer Verwaltung in der Akte einer anderen.
        self.eingang = Eingang.objects.create(
            organisation=self.organisation, quelle=Eingang.MAIL,
            betreff=f'Eingang {k}', absender=f'Absender {k}',
            referenz=f'QR-{k}-0001')
        self.zuordnungsregel = Zuordnungsregel.objects.create(
            organisation=self.organisation, merkmal=Zuordnungsregel.REFERENZ,
            wert=f'qr{k.lower()}0001', wert_anzeige=f'QR-{k}-0001',
            akte=self.vertrag)

        self.regelanwendung = Regelanwendung.objects.create(
            organisation=self.organisation, art=Regel.KUENDIGUNGSTERMIN,
            regel_stand=date(2026, 1, 15), fall=self.fall,
            befund=Regelanwendung.BEANSTANDET, meldung=f'Prüfung {k}')

    def _benutzer(self):
        """Team-Benutzer dieses Mandanten — Gruppe UND Mitgliedschaft.

        Die Gruppe trägt die Rolle (`core/auth.py` liest bis 4.3 weiterhin
        `user.groups`), die Mitgliedschaft trägt die Organisation. Ohne sie
        findet `OrganisationMiddleware` keinen Kontext, `_global_filter`
        filtert nichts — und die Isolationstests wären rot, ohne dass ein
        Isolationsfehler vorläge. Ein Fixture, das den Benutzer nicht
        zuordnet, prüft die eigene Lückenhaftigkeit statt die Anwendung.
        """
        from crm.models import Mitgliedschaft

        grp, _ = Group.objects.get_or_create(name='Verwaltung')
        u = User.objects.create_user(username=f'team_{self.kuerzel.lower()}',
                                     password='geheim-egal', email=f'{self.kuerzel}@example.ch')
        u.groups.add(grp)
        Mitgliedschaft.objects.create(benutzer=u, organisation=self.organisation,
                                      rolle=Mitgliedschaft.ROLLE_VERWALTER)
        return u

    def _alle_objekte(self):
        """Alle im Fixture angelegten Modellinstanzen — für Registryläufe.

        Bewusst über `vars(self)` statt über eine gepflegte Liste: Ein Objekt,
        das oben dazukommt, ist hier automatisch dabei. Eine Liste, die jemand
        nachzupflegen vergisst, wäre eine stille Prüflücke.
        """
        from django.db.models import Model
        return [w for w in vars(self).values() if isinstance(w, Model)]

    # -- Zugriff für die Registryläufe -------------------------------------

    def objekt_fuer(self, parameter, url_name):
        """Liefert das Objekt dieses Bestands, das zum URL-Parameter passt.

        Wirft `LookupError`, wenn ein Parameter nicht zugeordnet werden kann —
        NICHT `None`. Ein stilles Überspringen wäre genau die Lücke, die diese
        Tests verhindern sollen: Der Registrylauf bliebe grün und hätte die
        betroffene URL nie aufgerufen.

        `pk` ist uneinheitlich: 119 URLs benutzen ihn für höchst
        unterschiedliche Modelle. Die Zuordnung erfolgt deshalb über den
        URL-NAMEN, nicht über den Parameternamen.
        """
        if parameter in KEINE_OBJEKT_ID:
            raise LookupError(
                f'{parameter} ({url_name}) ist keine Objekt-ID und gehoert in Bauform C')
        if parameter != 'pk':
            attr = PARAMETER_MODELL.get(parameter)
            if not attr:
                raise LookupError(f'Parameter {parameter!r} ({url_name}) ist in '
                                  f'PARAMETER_MODELL nicht zugeordnet')
            return getattr(self, attr)
        return self._objekt_aus_urlname(url_name)

    #: URL-Namensbestandteil → Attribut dieses Fixtures. Der erste Treffer
    #: gewinnt, deshalb stehen die spezifischeren Muster vorn.
    #: Abgelesen aus dem `get_object_or_404` der jeweiligen View, nicht geraten.
    NAME_MUSTER = (
        ('abnahme',         'abnahme'),
        ('akonto',          'periode'),
        ('anpassung',       'anpassung'),
        ('asset',           'geraet'),
        ('ausstattung_add', 'einheit'),
        ('ausstattung_katalog', 'einheit'),
        ('ausstattung',     'ausstattung'),
        ('betriebsrechnung', 'liegenschaft'),
        ('bewerber',        'bewerbung'),
        ('bewerbung',       'bewerbung'),
        ('dienstleister',   'handwerker'),
        ('rentals_dokument', 'dokument_rentals'),
        ('dokument_portal', 'dokument_rentals'),
        ('portal_dokument', 'dokument_portfolio'),
        ('dokument',        'dokument_portfolio'),
        ('expose',          'einheit'),
        ('geraet',          'geraet'),
        ('kommunikation',   'kommunikation'),
        ('kuendigung',      'kuendigung'),
        ('merkmale',        'einheit'),
        ('verzug',          'pendenz'),
        ('pendenz',         'pendenz'),
        ('portal_freigabe', 'auftrag'),
        ('schluessel_rueckgabe', 'schluessel_ausgabe'),
        ('schluessel',      'schluessel'),
        ('sollmietzins',    'sollmietzins'),
        ('staffelvorlage',  'staffelvorlage'),
        ('staffel',         'staffel'),
        ('versicherung',    'versicherung'),
        ('vorlage',         'vorlage'),
        ('zaehler',         'zaehler'),
        ('kontoauszug',     'zahlung'),
        ('kreditor',        'kreditor'),
        ('debitor',         'debitor'),
        ('zahlung',         'zahlung'),
        ('buchung',         'buchung'),
        ('nebenkosten',     'periode'),
        ('abrechnung',      'periode'),
        ('liegenschaft',    'liegenschaft'),
        ('objekt',          'einheit'),
        ('einheit',         'einheit'),
        ('vertrag',         'vertrag'),
        ('mieter',          'mieter'),
        ('person',          'mieter'),
        ('eigentuemer',     'eigentuemer'),
        ('mandat',          'eigentuemer'),
        ('schaden',         'schaden'),
        ('auftrag',         'schaden'),
        ('wartungsfrist',   'wartungsfrist'),
        ('benutzer',        'benutzer'),
    )

    def _objekt_aus_urlname(self, url_name):
        for muster, attr in self.NAME_MUSTER:
            if muster in url_name:
                return getattr(self, attr)
        raise LookupError(
            f'Zu {url_name!r} (Parameter pk) laesst sich kein Objekt zuordnen. '
            f'Entweder NAME_MUSTER ergaenzen oder die URL begruendet in die '
            f'Ausnahmeliste aufnehmen — nicht stillschweigend ueberspringen.')


def beide_mandanten():
    """A und B, in dieser Reihenfolge. A bekommt die niedrigeren IDs."""
    return MandantenFixture('A', '8000', 'Zürich'), MandantenFixture('B', '3000', 'Bern')
