"""Wer betreut das? — die Betreuung der Liegenschaft, von überall her.

DIE FRAGE, DIE DAHINTER STEHT

«Diese Information muss auf alles vererbt und angezeigt werden, was mit der
Liegenschaft zu tun hat. Person, Objekt, Schadenfälle etc.»

Die Betreuung steht an genau einer Stelle — `Liegenschaft.betreut_von`. Sie an
jeder Akte zu speichern wäre die schnellere Lösung und die schlechtere: Beim
Wechsel müsste jemand alle Kopien nachziehen, und wer es vergisst, hat zwei
Antworten auf dieselbe Frage.

DESHALB WIRD SIE AUFGELÖST, NICHT KOPIERT.

Dieser Baustein geht von einem beliebigen Datensatz aus die Kette hoch, bis er
eine Liegenschaft findet:

    Einheit    → liegenschaft
    Vertrag    → einheit → liegenschaft
    Schaden    → einheit → liegenschaft
    Fall       → akte → (einer der obigen)
    Mieter     → über den aktiven Vertrag

Findet er keine, gibt er `None` zurück — und `None` heisst «nicht zugeteilt»,
was eine Aussage ist: Eine Liegenschaft ohne Betreuung soll auffallen.
"""
from django import template

register = template.Library()

#: Wie tief die Kette verfolgt wird. Fünf Glieder decken jeden heutigen Weg
#: (Fall → Vertrag → Einheit → Liegenschaft sind vier); die Grenze verhindert
#: eine Endlosschleife, falls jemand später einen Ringbezug baut.
MAX_TIEFE = 5


def _liegenschaft_von(objekt, tiefe=0):
    """Die Liegenschaft hinter einem beliebigen Datensatz — oder `None`."""
    if objekt is None or tiefe > MAX_TIEFE:
        return None
    if objekt.__class__.__name__ == 'Liegenschaft':
        return objekt

    # Der direkte Weg zuerst: Die meisten Modelle tragen `liegenschaft`.
    naechst = getattr(objekt, 'liegenschaft', None)
    if naechst is not None:
        return _liegenschaft_von(naechst, tiefe + 1)

    # Dann die bekannten Umwege. `akte` steht am Fall und kann alles sein.
    for feld in ('einheit', 'akte', 'vertrag', 'mietverhaeltnis'):
        naechst = getattr(objekt, feld, None)
        if naechst is not None and naechst is not objekt:
            treffer = _liegenschaft_von(naechst, tiefe + 1)
            if treffer is not None:
                return treffer

    # EIN MIETER HAT KEINE LIEGENSCHAFT — ER HAT EINEN VERTRAG.
    #
    # Der aktive zuerst: Wer ausgezogen ist und einen alten Vertrag hat, wird
    # nicht mehr von dessen Liegenschaft betreut. Gibt es keinen aktiven,
    # zaehlt der juengste — bei einem ehemaligen Mieter ist das die letzte
    # bekannte Zustaendigkeit, und die ist besser als keine.
    vertraege = getattr(objekt, 'vertraege', None)
    if vertraege is not None:
        vertrag = (vertraege.filter(status='aktiv').first()
                   or vertraege.order_by('-beginn').first())
        if vertrag is not None:
            return _liegenschaft_von(vertrag, tiefe + 1)
    return None


@register.simple_tag
def betreut_von(objekt):
    """Die betreuende Person — oder `None`.

    Ein Fehler hier darf keine Seite kosten: Die Betreuung ist eine Angabe am
    Rand, nicht der Inhalt. Bei einem kaputten Verweis bleibt das Feld leer,
    statt die Akte mitzureissen.
    """
    try:
        lg = _liegenschaft_von(objekt)
        return getattr(lg, 'betreut_von', None) if lg else None
    except Exception:  # pragma: no cover - Schutz, kein Verhalten
        import logging

        logging.getLogger(__name__).exception('Betreuung nicht auflösbar')
        return None
