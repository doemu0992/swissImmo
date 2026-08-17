"""Mandantenkontext und `TenantManager` — das Herzstück der Isolation.

Der Kernsatz dieser Etappe steht in `.claude/agents/chirurg.md` und im Skill
`mandantentrennung`:

    Ohne gesetzte Organisation ist die richtige Antwort ein FEHLER,
    nicht „alles zurückgeben".

Ein Manager, der im Zweifel alles liefert, ist schlechter als keiner. Er
täuscht Sicherheit vor, und der Fehler fällt erst auf, wenn Daten bereits
geflossen sind — in einem Report, einem Export, einer E-Mail. Deshalb wirft
`TenantManager` ohne Kontext `OrganisationsFehler`, statt still den ganzen
Bestand herauszugeben.

WARUM EINE CONTEXTVAR UND KEIN THREAD-LOCAL
-------------------------------------------
`contextvars` folgen dem Ausführungskontext statt dem Betriebssystem-Thread.
Das ist unter async und unter Thread-Pools das Einzige, was trägt: Ein
Thread-Local würde bei wiederverwendeten Worker-Threads den Kontext der
vorigen Anfrage mitschleppen — und genau das wäre ein Datenleck mit
Zeitverzögerung.

AUSSERHALB EINES REQUESTS
-------------------------
Management-Commands, Signals und die Shell haben keine Middleware. Sie setzen
den Kontext ausdrücklich:

    with organisation_kontext(org):
        ...

Ein Systemlauf, der bewusst über ALLE Organisationen geht, benutzt den
benannten Weg `Model.alle_organisationen` — nicht `ohne_organisation()`. Der
Unterschied ist Absicht: `alle_organisationen` steht sichtbar im Code und lässt
sich greppen; ein stiller Kontextverzicht nicht.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models

#: Die Organisation des laufenden Kontexts. `None` heisst „nicht gesetzt" und
#: führt im `TenantManager` zu einem Fehler — nicht zu „alles".
_organisation: ContextVar = ContextVar('swissimmo_organisation', default=None)

#: Ausdrücklich kontextfrei. Nur für den Anmeldevorgang und für Systemläufe,
#: die über `alle_organisationen` gehen. Siehe `ohne_organisation()`.
_kontextfrei: ContextVar = ContextVar('swissimmo_kontextfrei', default=False)


class OrganisationsFehler(RuntimeError):
    """Es wurde auf Mandantendaten zugegriffen, ohne dass eine Organisation feststeht.

    Das ist ein Programmfehler, keine Benutzereingabe: Irgendein Pfad hat die
    Middleware umgangen oder vergessen, den Kontext zu setzen.
    """


def setze_organisation(organisation):
    """Setzt die Organisation des laufenden Kontexts.

    Nimmt eine `crm.Organisation` **oder** irgendein Objekt mit `.organisation`
    (bequem für Fixtures und Tests, die ihren Mandanten als Ganzes reichen).
    """
    org = getattr(organisation, 'organisation', organisation)
    _organisation.set(org)
    _kontextfrei.set(False)
    return org


def aktuelle_organisation():
    """Die Organisation des laufenden Kontexts, oder `None`."""
    return _organisation.get()


def loesche_organisation():
    """Kontext zurücksetzen — am Ende jeder Anfrage."""
    _organisation.set(None)
    _kontextfrei.set(False)


@contextmanager
def organisation_kontext(organisation):
    """Setzt die Organisation für einen Block und stellt danach wieder her.

    Der Weg für Management-Commands, Signals und die Shell.
    """
    vorher_org = _organisation.get()
    vorher_frei = _kontextfrei.get()
    setze_organisation(organisation)
    try:
        yield
    finally:
        _organisation.set(vorher_org)
        _kontextfrei.set(vorher_frei)


@contextmanager
def ohne_organisation():
    """Ausdrücklich ohne Kontext — jeder Zugriff auf Mandantendaten wirft.

    Nicht „alles sehen", sondern „nichts sehen dürfen". Gebraucht wird das
    genau zweimal: im Anmeldevorgang, bevor feststeht, wer da ist, und in
    Tests, die belegen, dass der Manager ohne Kontext wirklich wirft.
    """
    vorher_org = _organisation.get()
    vorher_frei = _kontextfrei.get()
    _organisation.set(None)
    _kontextfrei.set(True)
    try:
        yield
    finally:
        _organisation.set(vorher_org)
        _kontextfrei.set(vorher_frei)


def cache_key(*teile):
    """Cache-Schlüssel mit Organisations-ID.

    Regel 4 des Skills `mandantentrennung`: „Ein geteilter Key ist ein
    Datenleck mit Zeitverzögerung." Der erste Mandant füllt den Cache, der
    zweite liest ihn — und niemandem fällt auf, warum die Zahlen fremd
    aussehen.

    Ohne Kontext wirft die Funktion, aus demselben Grund wie der Manager: Ein
    Schlüssel ohne Organisation wäre genau der geteilte Key.
    """
    org = aktuelle_organisation()
    if org is None:
        raise OrganisationsFehler(
            'cache_key() ohne gesetzte Organisation. Ein Schlüssel ohne '
            'Organisations-ID wird von allen Mandanten geteilt.')
    return ':'.join(['org', str(getattr(org, 'pk', org)), *(str(t) for t in teile)])


class TenantQuerySet(models.QuerySet):
    """QuerySet, das den Organisationsfilter trägt."""

    def fuer_organisation(self, organisation, pfad='organisation'):
        org = getattr(organisation, 'organisation', organisation)
        return self.filter(**{pfad: org})


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Default-Manager, der auf die Organisation des Kontexts filtert.

    `pfad` ist der Lookup von diesem Modell zur Organisation. Für Modelle mit
    eigener Spalte ist das schlicht `'organisation'`; für Modelle, die über
    eine Pflicht-Kette hängen, der Pfad dorthin — etwa
    `'einheit__liegenschaft__organisation'` bei `Mietvertrag`.

    Der Pfad ist bewusst ein Parameter und keine Konvention: Etappe 5 rüstet
    die denormalisierte Spalte nach und ändert dann nur diesen einen Wert,
    ohne dass die Isolation dazwischen je aussetzt.
    """

    #: Wird auf `False` gesetzt für den ausdrücklich ungefilterten Zweitmanager.
    filtert = True

    def __init__(self, pfad='organisation'):
        super().__init__()
        self.pfad = pfad

    # ------------------------------------------------------------------
    # Schreiben braucht keinen Kontext, Lesen schon.
    #
    # Gemessen beim Anbinden (15.08.2026): Von 83 Fehlschlägen in einem
    # einzigen Testmodul waren 75 ein `create` und nur 8 eine Abfrage. Das ist
    # kein Zufall, sondern der Unterschied in der Sache: Ein `create` gibt
    # nichts heraus. Es kann nichts über eine fremde Organisation verraten,
    # weil es nichts liest — es liefert das Objekt zurück, das der Aufrufer
    # gerade selbst beschrieben hat.
    #
    # WAS DAS OFFEN LÄSST, damit es niemand übersieht: Ein `create` ohne
    # Kontext kann einen Datensatz OHNE Organisation anlegen — eine Waise, die
    # nach Regel 1 des Skills `mandantentrennung` niemandem gehört und die
    # folglich jeder sieht. Heute ist das möglich, weil `organisation`
    # `null=True` ist. Etappe 5 setzt `null=False`; ab dann scheitert genau
    # dieser Fall in der Datenbank statt im Manager. Bis dahin ist es eine
    # bewusst offene Flanke und keine übersehene.
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # ZWEI BEFUNDE AUS DEM ZWEITEN ANBINDUNGSVERSUCH (16.08.2026, Etappe 5)
    #
    # Die Anbindung an die zwölf portfolio-Modelle wurde gebaut, gemessen und
    # wieder zurückgenommen — wie schon in 4.2, diesmal mit benannten Ursachen.
    # Wer sie erneut versucht, muss vorher diese beiden lösen:
    #
    # 1. RÜCKBEZÜGE ERBEN DEN FILTER. Django baut den Manager eines Rückbezugs
    #    aus `related_model._default_manager.__class__`. Steht der TenantManager
    #    vorn, ist damit JEDES `liegenschaft.einheiten.all()` gefiltert — in
    #    Services, Management-Commands, PDF-Erzeugung, Signals. `_base_manager`
    #    bleibt ein gewöhnlicher `Manager` (Vorwärts-Fremdschlüssel wie
    #    `ausgabe.schluessel` sind also sicher); die Rückwärtsrichtung ist es
    #    nicht. Gemessen: 65 Fehlschläge in einem einzigen Testblock, drei
    #    weitere Blöcke stürzten unter `--parallel` ganz ab.
    #
    # 2. `update_or_create` IST HIER BEWUSST NICHT AUFGEFÜHRT. Es fehlte beim
    #    Messen und liess `rentals/models.py:697` scheitern
    #    (`_sync_objekt_sollmietzins`). Die naheliegende Korrektur wäre, es zu
    #    den drei Ausnahmen unten zu stellen — sie wäre falsch: `create` gibt
    #    nichts heraus, `update_or_create` liest zuerst und würde ohne Filter
    #    den Datensatz eines FREMDEN Mandanten aktualisieren. Das ist schlimmer
    #    als ein Leseleck.
    #
    #    Dieselbe Kritik trifft `get_or_create` unten, das die Ausnahme heute
    #    schon hat. Auch das gehört beim nächsten Anlauf geprüft, statt aus
    #    Gewohnheit fortgeschrieben zu werden.
    #
    # Der richtige Weg für beide: Der Aufrufer setzt den Kontext
    # (`with organisation_kontext(org):`), statt dass der Manager Ausnahmen
    # sammelt. Das ist Arbeit in Etappe 6 — die Commands, Services und
    # öffentlichen Endpunkte —, nicht in einem Modell-PR.
    # ------------------------------------------------------------------
    def create(self, **kwargs):
        return super(models.Manager, self).get_queryset().create(**kwargs)

    def bulk_create(self, objs, *args, **kwargs):
        return super(models.Manager, self).get_queryset().bulk_create(objs, *args, **kwargs)

    # `get_or_create` HAT HIER BEWUSST KEINE AUSNAHME MEHR (Etappe 6.2).
    #
    # Es stand bis 6.2 neben `create` in der Liste, aus Gewohnheit statt aus
    # Gruenden — der Kommentar oben hatte das schon angemerkt. Der Unterschied
    # ist entscheidend: `create` gibt nichts heraus, `get_or_create` LIEST
    # zuerst. Ohne Filter faende es die Zeile eines fremden Mandanten und gaebe
    # sie zurueck, statt eine eigene anzulegen — ein Leseleck mit dem Anschein
    # eines Schreibvorgangs. Mit Filter ist das Verhalten richtig: Was einer
    # anderen Organisation gehoert, ist unsichtbar, also entsteht eine eigene
    # Zeile. Dasselbe gilt fuer `update_or_create`, das nie eine Ausnahme hatte.
    #
    # Wo ein Aufrufer dadurch ohne Kontext scheitert, ist das die richtige
    # Meldung: Er soll `with organisation_kontext(org):` setzen.

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.filtert:
            return qs

        # RUECKBEZUEGE FILTERN NICHT — die Klippe, an der 4.2 und 5 gescheitert
        # sind (65 bzw. 922 Fehlschlaege).
        #
        # Django baut den Manager eines Rueckbezugs aus
        # `related_model._default_manager.__class__`. Steht der TenantManager
        # vorn, laeuft damit JEDES `liegenschaft.einheiten.all()` durch diese
        # Methode — in Services, Commands, PDF-Erzeugung, Signals, also
        # ueberwiegend ohne Anfrage und damit ohne Kontext. Der Aufruf brach ab,
        # wo gar keine Mandantengrenze im Spiel war.
        #
        # Warum das Weglassen des Filters hier NICHT die Isolation aufgibt:
        # Ein Rueckbezug geht immer von einem bereits geladenen Objekt aus, und
        # seit Etappe 5 leitet das Kind seine Organisation aus genau dieser
        # Kette ab (`ORGANISATION_PFAD`, `null=False`, null Waisen). Die Kinder
        # einer Liegenschaft koennen deshalb gar keiner anderen Organisation
        # gehoeren als die Liegenschaft selbst. Der Filter waere hier
        # tautologisch — er kann nichts ausschliessen, was nicht schon
        # ausgeschlossen ist.
        #
        # Die Grenze wird dort gezogen, wo sie hingehoert: am EINSTIEG
        # (`Model.objects.filter(...)`, `get_object_or_404(Model, pk=…)`). Wer
        # von einem fremden Objekt aus traversiert, hat es vorher ungefiltert
        # geholt — und das ist genau der Aufruf, den diese Methode abfaengt.
        #
        # Erkennungsmerkmal: Django setzt `self.instance` auf dem
        # Rueckbezugs-Manager (`RelatedManager.__init__`); ein gewoehnliches
        # `Model.objects` hat das Attribut nicht.
        if getattr(self, 'instance', None) is not None:
            return qs

        org = aktuelle_organisation()
        if org is None:
            raise OrganisationsFehler(
                f'{self.model._meta.label}.objects ohne gesetzte Organisation. '
                f'Innerhalb einer Anfrage setzt die Middleware sie; ausserhalb '
                f'(Management-Command, Signal, Shell) gehört '
                f'`with organisation_kontext(org):` darum. Wer absichtlich über '
                f'alle Organisationen läuft, nimmt '
                f'`{self.model._meta.object_name}.alle_organisationen`.')
        return qs.filter(**{self.pfad: org})


class AlleOrganisationenManager(models.Manager.from_queryset(TenantQuerySet)):
    """Der benannte Weg an der Isolation vorbei.

    Systemläufe, die über alle Organisationen iterieren sollen, benutzen ihn —
    sichtbar im Code und greppbar. Genau deshalb heisst er so und nicht
    `objects_ungefiltert` oder `all_objects`: Wer ihn liest, weiss sofort, was
    er tut, und wer ihn sucht, findet jede Fundstelle.

    Jede Verwendung trägt einen Kommentar, der erklärt WARUM (Skill
    `mandantentrennung`, Regel 2).
    """
    filtert = False
