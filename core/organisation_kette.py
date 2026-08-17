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


def organisation_bestimmen(organisation=None):
    """Die Organisation für einen Datensatz — ausdrücklich, sonst aus dem Kontext.

    ETAPPE 6.3: Diese Funktion hiess `organisation_oder_einzige` und hatte einen
    dritten Schritt, der jetzt weg ist:

        vorher:  Argument → Kontext → **die einzige vorhandene** → Fehler
        jetzt:   Argument → Kontext → Fehler

    Der gestrichene Schritt war ausdrücklich Schuld auf Zeit. Er ratete nicht —
    mit mehreren Organisationen brach er ab —, aber genau darin lag das Problem:
    Er hielt jeden Pfad am Leben, der ohne Mandantenkontext buchte, und beim
    ersten zweiten Mandanten wären sie alle gleichzeitig ausgefallen. Solange
    es eine Organisation gab, sah alles in Ordnung aus.

    Getilgt werden konnte er erst nach 6.1 und 6.2: Erst dort haben die
    öffentlichen Endpunkte, die Management-Commands und die Services ihren
    Kontext bekommen. Die Zahl, die den ersten Versuch gestoppt hatte —
    140 Fehlschläge in drei Testmodulen —, war die Rechnung für genau diese
    fehlende Vorarbeit.

    Ohne Kontext ist ein Fehler die richtige Antwort. Die Alternative wäre, den
    Datensatz irgendwem zuzuschlagen; das fällt niemandem auf, bis er in der
    falschen Bilanz steht.
    """
    from core.tenancy import aktuelle_organisation

    if organisation is not None:
        return organisation
    aus_kontext = aktuelle_organisation()
    if aus_kontext is not None:
        return aus_kontext
    raise ValueError(
        'Kein Mandantenkontext. Wem der Datensatz gehört, ist damit nicht '
        'bestimmt — `with organisation_kontext(org):` setzen. (Bis Etappe 6.3 '
        'wich diese Stelle auf eine einzige vorhandene Organisation aus; das '
        'ging genau so lange gut, wie es nur eine gab.)')


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
        if self.organisation_id is None:
            # Die Kette trug nicht. Das ist bei den meisten Modellen unmoeglich
            # (ihre Glieder sind pflichtig) und bei einigen der Normalfall: Ein
            # Zahlungseingang aus dem Bankabgleich hat oft weder Vertrag noch
            # Liegenschaft — "noch nicht zugeordnet" ist dort ein regulaerer
            # Arbeitszustand.
            #
            # Dann gilt der Mandantenkontext. Bis Etappe 6.3 stand hier
            # stattdessen "die einzige vorhandene Organisation", gesteuert ueber
            # ein Attribut `ORGANISATION_RUECKFALL` an sieben Modellen. Beides
            # ist weg: Der Kontext ist die richtige Quelle, er gilt fuer jedes
            # Modell gleich, und ohne ihn ist ein Fehler die ehrliche Antwort.
            self.organisation_id = organisation_bestimmen().pk

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
