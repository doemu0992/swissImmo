"""Abnahmen bauen aufeinander auf: Auszug → späterer Einzug und umgekehrt.

Ein Protokoll gehört zur Einheit, nicht zum Mieter. Wer eine Wohnung monate
nach dem Auszug wieder übergibt, beginnt deshalb nicht bei null, sondern beim
letzten abgeschlossenen Protokoll dieser Einheit — mit dem Zustand von damals
als Vorzustand neben jedem Bauteil.
"""


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
    return einzug
