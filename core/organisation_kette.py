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
    ORGANISATION_PFAD: str = ''

    organisation = models.ForeignKey(
        'crm.Organisation',
        on_delete=models.CASCADE,
        editable=False,
        # `%(app_label)s_%(class)s` — sonst kollidierten die Rückbezüge
        # mehrerer Apps (portfolio.Dokument und rentals.Dokument gibt es beide).
        related_name='%(app_label)s_%(class)s',
        verbose_name='Organisation',
    )

    # Der Filter selbst. `pfad='organisation'` ist die denormalisierte Spalte
    # oben — deshalb gibt es sie: Der Manager filtert ohne Join, auch bei
    # `SchluesselAusgabe`, das drei Glieder von der Liegenschaft entfernt ist.
    #
    # Reihenfolge zählt: Der ERSTE Manager wird `_default_manager` und damit
    # der, den Admin, ModelForms und `dumpdata` nehmen. Der gefilterte gehört
    # also nach vorn.
    #
    # `_base_manager` bleibt unberührt — Django legt dafür still einen
    # gewöhnlichen `Manager` an, solange `Meta.base_manager_name` nicht gesetzt
    # ist. Das ist wichtig und kein Zufall: Fremdschlüssel-Zugriffe wie
    # `ausgabe.schluessel` gehen über `_base_manager`. Wäre der gefiltert,
    # würfe jeder Attributzugriff ausserhalb einer Anfrage — auch dort, wo
    # längst feststeht, dass das Objekt dem Aufrufer gehört.
    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        abstract = True

    def organisation_aus_kette(self):
        """Die Organisation, zu der dieser Datensatz laut Kette gehört.

        Gibt `None` zurück, wenn die Kette unterwegs abreisst. Das ist bei
        Gruppe C nicht vorgesehen (alle Glieder sind pflichtig), kann aber
        vorkommen, solange ein Objekt im Speicher noch unvollständig ist.
        """
        knoten = self
        for glied in self.ORGANISATION_PFAD.split('__'):
            # `getattr` statt `..._id`, weil unterwegs echte Objekte nötig sind.
            knoten = getattr(knoten, glied, None)
            if knoten is None:
                return None
        return getattr(knoten, 'organisation_id', None)

    def save(self, *args, **kwargs):
        # Nur ergänzen, nie überschreiben: Wer die Organisation ausdrücklich
        # gesetzt hat (Datenmigration, Test-Fixture), meint sie so.
        if self.organisation_id is None:
            self.organisation_id = self.organisation_aus_kette()

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
