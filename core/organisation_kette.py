"""Der Organisationsbezug für Modelle mit geschlossener Pflicht-Kette (Gruppe C).

WARUM EINE SPALTE, OBWOHL DIE KETTE GENÜGEN WÜRDE

`Einheit` erreicht die Organisation über `liegenschaft.organisation`,
`SchluesselAusgabe` über `schluessel.liegenschaft.organisation`. Technisch
liesse sich jede Query so filtern. Zwei Gründe sprechen dagegen:

1. Ein Join über bis zu vier Ebenen bei **jeder** Abfrage ist teuer.
2. Der `TenantManager` filtert über einen festen Pfad. Er kann nicht für jedes
   Modell eine andere Join-Kette kennen, ohne selbst zur Fehlerquelle zu werden.

Also eine denormalisierte Spalte — und damit die Pflicht, sie richtig zu halten.

WARUM ABGELEITET UND NICHT EINGEGEBEN

Die naheliegende Fassung wäre ein gewöhnliches Pflichtfeld. Dann müsste aber
**jede** `Model.objects.create(...)`-Stelle im Bestand die Organisation
mitgeben — es sind mehrere hundert, verteilt über Views, Services, Commands und
Tests. Genau diese Bauform ist in Etappe 4.2 gemessen gescheitert: Die
Anbindung des Managers an alle Modelle liess **922 von 1'072** Tests
scheitern, 638 auch noch mit erlaubtem Schreibzugriff ohne Kontext.

Der Wert ist ohnehin keine Eingabe, sondern eine **Folge**: Eine Einheit gehört
der Organisation ihrer Liegenschaft, und niemand darf etwas anderes wählen. Ein
abgeleitetes Feld bildet das ab, statt es dem Aufrufer zu überlassen —
`editable=False` hält es aus Formularen heraus, `save()` füllt es.

WAS DAS NICHT LEISTET

`queryset.update()` und `bulk_create()` gehen an `save()` vorbei. Beides ist im
Bestand selten und steht bei den betroffenen Modellen nicht in Schreibpfaden,
die neue Objekte anlegen — aber es ist eine echte Lücke, kein theoretischer
Vorbehalt. Der Test `OrganisationKetteTests` prüft deshalb den Bestand als
Ganzes: nach jeder Migration darf **kein** Datensatz ohne Organisation
existieren.
"""
from django.db import models

from core.tenancy import AlleOrganisationenManager, TenantManager


def organisation_aus_kontext():
    """Die ID der Organisation des laufenden Mandantenkontexts, oder `None`.

    Für die **Wurzel** der Kette — `portfolio.Liegenschaft`. Sie kann ihren
    Bezug nirgends herleiten; er steht nur im Kontext, den die Middleware aus
    der Mitgliedschaft setzt.

    Warum das nötig wurde: `core/views/fw/liegenschaft_crud.py` legt eine neue
    Liegenschaft als `Liegenschaft()` an und setzt danach die Formularfelder —
    die Organisation war nie darunter. Solange die Spalte optional war, entstand
    dabei still eine Liegenschaft ohne Mandant. Mit `null=False` wäre daraus ein
    `IntegrityError` beim Speichern über die Oberfläche geworden.

    Der Kontext ist die richtige Quelle und nicht etwa „die einzige vorhandene
    Organisation": Letzteres ginge heute gut und wäre ab dem zweiten Mandanten
    eine Fehlzuordnung — also genau die Art Regel, die erst dann auffällt, wenn
    sie schon Schaden angerichtet hat.

    Gibt es keinen Kontext, wird hier NICHT geraten. Dann schlägt das Speichern
    an der Datenbank fehl, und das ist die ehrliche Antwort: Wer eine
    Liegenschaft ohne Mandant anlegen will, hat etwas übersehen.
    """
    from core.tenancy import aktuelle_organisation      # zirkulärer Import sonst
    return getattr(aktuelle_organisation(), 'pk', None)


def organisation_oder_einzige(organisation=None):
    """Übergangshelfer: Kontext, sonst die EINZIGE Organisation — sonst Fehler.

    WARUM ES DEN GIBT, obwohl „im Zweifel raten" hier sonst verboten ist:

    Der Kontenplan gehört seit Etappe 5 der Verwaltung. `finance/booking.py`
    braucht deshalb bei jedem `konto('1020')` einen Bezug. Verlangt man dafür
    ausnahmslos den Mandantenkontext, ist plötzlich **jeder** Pfad, der etwas
    verbucht, kontextabhängig — Services, Management-Commands, Signale, Tests.
    Gemessen am 16.08.2026: **140 Fehlschläge in nur drei Testmodulen**, mit
    weiteren zu erwarten. Das ist dieselbe Form, die schon die Anbindung des
    `TenantManager` zweimal gestoppt hat, und sie hat dieselbe Lösung: Der
    Aufrufer muss den Kontext setzen, und das ist Etappe 6.

    Bis dahin gilt hier eine Regel, die **kein Raten** ist:

        Gibt es genau EINE Organisation, ist sie eindeutig gemeint.
        Gibt es mehrere und keinen Kontext, ist es ein Fehler.

    Mit einem einzigen Mandanten kann daraus kein mandantenübergreifender
    Zugriff entstehen — es gibt kein „übergreifend". Und in dem Moment, in dem
    einer entstehen könnte, wird daraus eine Ausnahme statt einer stillen
    Fehlzuordnung. Genau dieselbe Regel wenden die Datenmigrationen an
    (`crm/0034`, `portfolio/0037`, `finance/0036`): eine Organisation → zuordnen,
    mehrere → abbrechen.

    Das ist Schuld auf Zeit, keine Lösung. Sie steht in `docs/PHASE-2-PLAN.md`
    unter Etappe 6 und muss dort getilgt werden, BEVOR der zweite Mandant
    angelegt wird.
    """
    from core.tenancy import _kontextfrei, aktuelle_organisation
    from crm.models import Organisation

    if organisation is not None:
        return organisation
    aus_kontext = aktuelle_organisation()
    if aus_kontext is not None:
        return aus_kontext

    # `ohne_organisation()` heisst AUSDRÜCKLICH kontextfrei — dort wird auch
    # dann nicht ausgewichen, wenn es nur eine Organisation gibt. Sonst würde
    # ausgerechnet der Block, der beweisen soll, dass ohne Kontext nichts geht,
    # stillschweigend etwas gehen lassen.
    if _kontextfrei.get():
        raise ValueError(
            'Ausdrücklich ohne Mandantenkontext (`ohne_organisation()`) — hier '
            'wird auch nicht auf eine einzige vorhandene Organisation '
            'ausgewichen.')

    beiden = list(Organisation.objects.order_by('pk')[:2])
    if len(beiden) == 1:
        return beiden[0]
    if not beiden:
        raise ValueError(
            'Kein Mandantenkontext und keine Organisation vorhanden. Ohne beides '
            'ist nicht bestimmt, wem der Datensatz gehört.')
    raise ValueError(
        'Kein Mandantenkontext, aber mehrere Organisationen. Welche gemeint ist, '
        'lässt sich nicht erraten — `with organisation_kontext(org):` setzen.')


class OrganisationAusKette(models.Model):
    """Abstrakte Basis: trägt `organisation` und leitet sie beim Speichern ab.

    Unterklassen setzen `ORGANISATION_PFAD` auf den Weg zur Liegenschaft — in
    Django-Schreibweise, also mit `__` getrennt:

        class Einheit(OrganisationAusKette):
            ORGANISATION_PFAD = 'liegenschaft'

        class SchluesselAusgabe(OrganisationAusKette):
            ORGANISATION_PFAD = 'schluessel__liegenschaft'

    Das letzte Glied des Pfades muss ein Modell sein, das selbst eine
    `organisation` trägt (`Liegenschaft`) — oder eines, das wiederum von dieser
    Basis erbt. Beides wird beim Laden geprüft, nicht erst beim Speichern.
    """

    #: Weg zum Träger der Organisation, `__`-getrennt. Pflicht in Unterklassen.
    #:
    #: Auch ein **Tupel** ist erlaubt, für Modelle mit einem Entweder-oder:
    #: `Dokument`, `Geraet` und `Zaehler` hängen wahlweise an einer Einheit
    #: ODER an einer Liegenschaft, beide Fremdschlüssel `null=True`. Dann gilt
    #: der erste Pfad, der trägt:
    #:
    #:     ORGANISATION_PFAD = ('einheit__liegenschaft', 'liegenschaft')
    #:
    #: Die Einheit steht bewusst vorn — sie ist die genauere Angabe, und beide
    #: führen ohnehin zur selben Organisation, weil eine Einheit ihrer
    #: Liegenschaft gehört.
    #:
    #: Ein Tupel verlangt zusätzlich eine `CheckConstraint`, die mindestens
    #: einen der beiden erzwingt. Ohne sie entstünde genau die Waise, die
    #: Rezept B beschreibt: ein Datensatz, von dem kein Weg zur Organisation
    #: führt — und der deshalb niemandem gehört.
    ORGANISATION_PFAD = ''

    #: Darf der Bezug aus dem Mandantenkontext kommen, wenn KEIN Pfad trägt?
    #:
    #: Nur für Modelle, deren Wege **alle** optional sind und die trotzdem
    #: entstehen dürfen, ohne dass einer davon gesetzt ist. Im Bestand sind das
    #: die vier Belegarten der Buchhaltung: Ein Zahlungseingang aus dem
    #: Bankabgleich hat oft weder Vertrag noch Liegenschaft — „noch nicht
    #: zugeordnet" ist dort ein regulärer Arbeitszustand, kein Fehler.
    #:
    #: `False` überall sonst, und das ist der Normalfall: Wo eine Pflicht-Kette
    #: besteht (`einheit`, `vertrag`, `protokoll`) oder eine `CheckConstraint`
    #: mindestens einen Weg erzwingt, wäre ein Rückfall eine stille Umgehung —
    #: er würde einen Datensatz retten, der gar nicht hätte entstehen dürfen.
    #:
    #: Der Rückfall ist Übergangsschuld, siehe `organisation_oder_einzige`.
    ORGANISATION_RUECKFALL = False

    organisation = models.ForeignKey(
        'crm.Organisation',
        on_delete=models.CASCADE,
        editable=False,
        # `%(app_label)s_%(class)s` — sonst kollidierten die Rückbezüge
        # mehrerer Apps (portfolio.Dokument und rentals.Dokument gibt es beide).
        related_name='%(app_label)s_%(class)s',
        verbose_name='Organisation',
    )

    # DIE ISOLATION — Etappe 6.2, an genau einer Stelle fuer 51 Modelle.
    #
    # `objects` filtert auf die Organisation des Kontexts und wirft, wenn
    # keiner gesetzt ist. Das Werfen ist die Absicht: Die Alternative waere,
    # im Zweifel den ganzen Bestand herauszugeben — genau das Leck, das diese
    # Etappe schliesst. Wer ausdruecklich ueber alle Verwaltungen laufen will,
    # nimmt `alle_organisationen`; das ist im Code lesbar und greppbar.
    #
    # WARUM HIER UND NICHT JE MODELL: Die Basis traegt schon den
    # Fremdschluessel und die Ableitung. Zwei Manager-Zeilen in 51 Klassen zu
    # wiederholen hiesse, 51 Stellen zu haben, an denen eine davon fehlen kann
    # — und ein Modell ohne Manager faellt nicht auf, es zeigt einfach alles.
    #
    # Die Reihenfolge ist bedeutsam: Der zuerst deklarierte Manager wird
    # `_default_manager`. Er muss der filternde sein, denn `_default_manager`
    # ist es, den `get_object_or_404(Model, pk=…)` und das Admin benutzen —
    # also die Einstiege, an denen die Grenze gezogen wird.
    # DIE ISOLATION — Etappe 6.2, an genau einer Stelle fuer 51 Modelle.
    #
    # `objects` filtert auf die Organisation des Kontexts und WIRFT, wenn keiner
    # gesetzt ist. Das Werfen ist die Absicht: Die Alternative — im Zweifel den
    # ganzen Bestand liefern — taeuscht Sicherheit vor, und der Fehler faellt
    # dann erst auf, wenn Daten schon geflossen sind (Report, Export, E-Mail).
    #
    # WARUM HIER UND NICHT JE MODELL: Die Basis traegt schon den Fremdschluessel
    # und die Ableitung. Zwei Manager-Zeilen in 51 Klassen zu wiederholen hiesse,
    # 51 Stellen zu haben, an denen eine fehlen kann — und ein Modell ohne
    # Manager faellt nicht auf, es zeigt einfach alles.
    #
    # DIE REIHENFOLGE IST BEDEUTSAM: Der zuerst deklarierte Manager wird
    # `_default_manager`. Er muss der filternde sein, denn `_default_manager` ist
    # es, den `get_object_or_404(Model, pk=…)` und das Admin benutzen — also die
    # Einstiege, an denen die Grenze ueberhaupt gezogen wird.
    #
    # WAS DAS UMLEGEN GEBRAUCHT HAT (dritter Anlauf, 17.08.2026; die ersten
    # beiden endeten bei 65 bzw. 922 Fehlschlaegen):
    #   · Rueckbezuege duerfen nicht filtern — `core/tenancy.py` erkennt sie an
    #     `self.instance`. Ohne das brach jedes `liegenschaft.einheiten.all()`.
    #   · Die Middleware STELLT den vorherigen Kontext WIEDER HER, statt ihn zu
    #     loeschen. Vorher wischte jede Anfrage den umgebenden Kontext weg.
    #   · Der Testlaeufer gibt jedem Test eine eigene Kontext-Kopie
    #     (`core/test_runner.py`), damit gesetzter Kontext nicht ueberlaeuft.
    #   · Selbstbezogene Zugriffe (`filter(pk=self.pk)`, `filter(vertrag=v)`)
    #     nehmen `alle_organisationen` — dort steht die Grenze schon im Ausdruck.
    objects = TenantManager()

    # DER BENANNTE WEG VORBEI. Systemlaeufe und oeffentliche Endpunkte, die
    # ausdruecklich ueber alle Verwaltungen lesen duerfen, nehmen ihn — sichtbar
    # im Code und greppbar. Jede Verwendung traegt einen Kommentar, der das WARUM
    # nennt (Skill `mandantentrennung`, Regel 2).
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        abstract = True

    def organisation_aus_kette(self):
        """Die Organisation, zu der dieser Datensatz laut Kette gehört.

        Gibt `None` zurück, wenn die Kette unterwegs abreisst. Das ist bei
        Gruppe C nicht vorgesehen (alle Glieder sind pflichtig), kann aber
        vorkommen, solange ein Objekt im Speicher noch unvollständig ist.
        """
        pfade = self.ORGANISATION_PFAD
        if isinstance(pfade, str):
            pfade = (pfade,)

        for pfad in pfade:
            knoten = self
            for glied in pfad.split('__'):
                # `getattr` statt `..._id`, weil unterwegs echte Objekte nötig sind.
                knoten = getattr(knoten, glied, None)
                if knoten is None:
                    break                       # dieser Pfad trägt nicht — nächsten versuchen
            else:
                organisation_id = getattr(knoten, 'organisation_id', None)
                if organisation_id is not None:
                    return organisation_id
        return None

    def save(self, *args, **kwargs):
        # Nur ergänzen, nie überschreiben: Wer die Organisation ausdrücklich
        # gesetzt hat (Datenmigration, Test-Fixture), meint sie so.
        if self.organisation_id is None:
            self.organisation_id = self.organisation_aus_kette()
        if self.organisation_id is None and self.ORGANISATION_RUECKFALL:
            self.organisation_id = organisation_oder_einzige().pk

        # KEIN Sonderfall für `update_fields`, obwohl er sich aufdrängt:
        # `obj.save(update_fields=['bezeichnung'])` schriebe eine hier eben
        # abgeleitete Organisation nicht mit — das Feld stünde nicht in der
        # Liste. Der Fall kann aber nicht eintreten, und zwar aus dem Grund,
        # der diese ganze Migration ausmacht: Die Spalte ist `null=False`.
        # Ein Objekt aus der Datenbank hat sie also immer gefüllt, und beim
        # ersten Speichern verbietet Django `update_fields` ohnehin.
        #
        # Eine erste Fassung hatte die Behandlung trotzdem — mitsamt einem
        # Test, der sie belegen sollte. Der Test scheiterte an
        # `NOT NULL constraint failed`, weil er den Zustand gar nicht mehr
        # herstellen konnte, den er prüfen wollte. Beides ist deshalb weg:
        # ungenutzter Code mit einem Test, der ihn nicht erreicht, ist
        # schlechter als kein Code.
        super().save(*args, **kwargs)
