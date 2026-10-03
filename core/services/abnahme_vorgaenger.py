"""Abnahmen bauen aufeinander auf: Auszug → späterer Einzug und umgekehrt.

Ein Protokoll gehört zur Einheit, nicht zum Mieter. Wer eine Wohnung monate
nach dem Auszug wieder übergibt, beginnt deshalb nicht bei null, sondern beim
letzten abgeschlossenen Protokoll dieser Einheit — mit dem Zustand von damals
als Vorzustand neben jedem Bauteil.
"""


def durchgefuehrt(qs):
    """Protokolle, die als «Abnahme erfolgt» zählen.

    Abgeschlossen — oder aus dem klassischen Formular (ohne Bauteile; dort ist
    «abgeschlossen» nur ein Häkchen, das oft fehlt). Ein offener Vor-Ort-Entwurf
    zählt nicht: Er entsteht schon beim Einrichten und ist noch keine Abnahme.
    Ohne diese Unterscheidung stünde der Mieterwechsel nach dem ersten Tippen
    auf «Rücknahme erfolgt»."""
    from django.db.models import Q
    return qs.filter(Q(abgeschlossen=True) | Q(positionen__isnull=True)).distinct()


def vorgaenger_fuer(einheit, datum, ausser=None):
    """Das letzte abgeschlossene Abnahmeprotokoll der Einheit bis zum Datum.

    Unabhängig von Art und Mieter: Die Kette läuft chronologisch durch die
    Einheit. Offene Entwürfe zählen nicht, sie sind noch kein Zustand."""
    from rentals.models import Abnahmeprotokoll
    qs = Abnahmeprotokoll.objects.filter(einheit=einheit, abgeschlossen=True, datum__lte=datum)
    if ausser is not None and ausser.pk:
        qs = qs.exclude(pk=ausser.pk)
    return qs.select_related('vertrag__mieter').order_by('-datum', '-id').first()


def nachmieter_vertrag(vertrag):
    """Der nächste Vertrag auf derselben Einheit nach diesem — für Aus- und
    Einzug in einem Termin. Dieselbe Regel wie in der Mieterwechsel-Übersicht."""
    from rentals.models import Mietvertrag
    return (Mietvertrag.objects.filter(einheit=vertrag.einheit)
            .exclude(id=vertrag.id).exclude(status='inaktiv')
            .filter(beginn__gte=(vertrag.ende or vertrag.beginn))
            .select_related('mieter').order_by('beginn').first())


def vorgaenger_vertrag(vertrag):
    """Der letzte andere Vertrag auf derselben Einheit, der vor diesem beginnt —
    der Mieter, der dort auszieht, wenn dieser einzieht."""
    from rentals.models import Mietvertrag
    return (Mietvertrag.objects.filter(einheit=vertrag.einheit)
            .exclude(id=vertrag.id).exclude(status='inaktiv')
            .filter(beginn__lte=vertrag.beginn)
            .select_related('mieter').order_by('-beginn', '-id').first())


def andere_vertraege(vertrag):
    """Alle anderen Verträge auf derselben Einheit, in zeitlicher Reihenfolge —
    unabhängig von Status und Daten. Wer die Einheit kennt, soll den Partner
    für Aus- und Einzug wählen können, auch wenn die Daten nicht lückenlos
    anschliessen."""
    from rentals.models import Mietvertrag
    return list(Mietvertrag.objects.filter(einheit=vertrag.einheit).exclude(id=vertrag.id)
                .select_related('mieter').order_by('beginn', 'id'))


def aus_und_einzug_paar(vertrag, partner_id=None):
    """`(ausziehender, einziehender)` Vertrag für Aus- und Einzug in einem
    Termin — von beiden Seiten aus erreichbar — oder None, wenn die Einheit
    keinen zweiten Vertrag hat.

    Der Partner ist der gewählte (`partner_id`, nur ein Vertrag derselben
    Einheit) oder der naheliegende: bei gekündigtem/archiviertem Vertrag der
    Nachmieter, sonst der Vorgänger, sonst der Nachmieter, zuletzt der zeitlich
    nächste. Wer früher beginnt, zieht aus."""
    andere = andere_vertraege(vertrag)
    if not andere:
        return None
    partner = next((a for a in andere if a.id == partner_id), None) if partner_id else None
    if partner is None:
        nach, vor = nachmieter_vertrag(vertrag), vorgaenger_vertrag(vertrag)
        partner = (nach or vor) if vertrag.status in ('gekuendigt', 'archiviert') else (vor or nach)
    if partner is None:
        partner = min(andere, key=lambda a: abs((a.beginn - vertrag.beginn).days))
    return tuple(sorted((vertrag, partner), key=lambda c: (c.beginn, c.id)))


def einzug_vorbereiten(auszug):
    """Legt aus einem abgeschlossenen Auszugsprotokoll das Einzugsprotokoll des
    Nachmieters an (Aus- und Einzug in einem Termin).

    Der Zustand beim Auszug ist der Zustand bei Übergabe: Bewertungen,
    Kommentare und Fotos werden übernommen und das Auszugsprotokoll ist der
    Vorgänger. Das Einzugsprotokoll bleibt ein Entwurf — der Einziehende
    prüft und unterschreibt selbst."""
    from rentals.models import Abnahmeprotokoll, AbnahmePosition
    einzug = Abnahmeprotokoll.objects.create(
        vertrag=auszug.folge_vertrag, typ='einzug', datum=auszug.datum, vorgaenger=auszug,
        verwalter_name=auszug.verwalter_name, zaehler_strom=auszug.zaehler_strom,
        zaehler_wasser=auszug.zaehler_wasser, zaehler_gas=auszug.zaehler_gas)
    for p in auszug.positionen.all():
        neu = AbnahmePosition(protokoll=einzug, raum=p.raum, bezeichnung=p.bezeichnung,
                              ausstattung=p.ausstattung, zustand=p.zustand, kommentar=p.kommentar,
                              sortierung=p.sortierung, vorgaenger_position=p)
        if p.foto:
            neu.foto = p.foto.name         # dieselbe Datei, keine zweite Kopie
        neu.save()
        neu.mangel_abgleichen()
        neu.save()
    # Schlüsselverzeichnis: Was zurückgegeben wurde, wird übergeben (Soll und Ist übernommen)
    from rentals.models import AbnahmeSchluessel
    for z in auszug.schluessel.all():
        AbnahmeSchluessel.objects.create(protokoll=einzug, bezeichnung=z.bezeichnung, anlage=z.anlage,
                                         soll=z.soll, ist=z.ist, sortierung=z.sortierung)
    return einzug
