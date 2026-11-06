"""Zustandsvergleich: Abnahme und Raumbuch greifen ineinander.

Drei Dinge, ein Grundsatz — der Zustand eines Bauteils wird nicht nur einmal erhoben, sondern über die Mietverhältnisse
hinweg nachvollzogen:

* **Das Raumbuch folgt der Abnahme.** Schliesst eine Abnahme ab, steht der festgestellte Zustand im Raumbuch-Element
  (``raumbuch_aktualisieren``). Was vorher dort stand, merkt sich die Position (``raumbuch_zustand_vorher``): nichts
  geht still verloren, auch kein von Hand gepflegter Wert.
* **Der Vorzustand hat zwei Quellen.** Gibt es ein Vorgänger-Protokoll, gilt dessen Bewertung. Sonst, beim ersten Einzug,
  der Raumbuch-Zustand von damals (``vorzustand``).
* **Der Vergleich** (``vergleich``) sagt: gleich geblieben, schlechter, besser. Nur das «schlechter» ist für die
  Kostenverteilung interessant; die Rechtsfolge (wer zahlt) bleibt bei der Bewertung «übermässig» und dem Entscheid zum
  Vorbestand, wie bisher.

Die beiden Skalen unterscheiden sich: Die Abnahme kennt drei Stufen (neu i.O., normale, übermässige Abnutzung), das
Raumbuch vier (neuwertig, gut, gebraucht, defekt). ``RANG_*`` legt beide auf dieselbe Skala 0 bis 2.
"""
from django.utils.translation import gettext

#: Was die Abnahme ins Raumbuch schreibt: neu i.O. → neuwertig, normale Abnutzung → gebraucht, übermässig → defekt.
ZUSTAND_NACH_RAUMBUCH = {'io': 'neuwertig', 'normal': 'gebraucht', 'uebermaessig': 'defekt'}
#: Beide Skalen auf dieselben drei Stufen (0 = wie neu, 2 = übermässig abgenutzt).
RANG_ABNAHME = {'io': 0, 'normal': 1, 'uebermaessig': 2}
RANG_RAUMBUCH = {'neuwertig': 0, 'gut': 0, 'gebraucht': 1, 'defekt': 2}


def _raumbuch_label(zustand):
    from portfolio.models import Ausstattung
    return str(dict(Ausstattung.ZUSTAND).get(zustand, zustand))


def raumbuch_aktualisieren(prot):
    """Schreibt die bewerteten Bauteile eines abgeschlossenen Protokolls ins Raumbuch.

    Pro Position mit Raumbuch-Element und Bewertung: der bisherige Raumbuch-Zustand wandert in
    ``raumbuch_zustand_vorher``, das Element bekommt den neuen. Eine Position, die schon nachgeführt wurde
    (``raumbuch_zustand_vorher`` gesetzt), bleibt unberührt — ein zweiter Aufruf ändert nichts.
    Gibt die Zahl der nachgeführten Elemente zurück."""
    n = 0
    for pos in prot.positionen.select_related('ausstattung'):
        if not pos.zustand or not pos.ausstattung_id or pos.raumbuch_zustand_vorher:
            continue
        neu = ZUSTAND_NACH_RAUMBUCH.get(pos.zustand)
        if neu is None:
            continue
        element = pos.ausstattung
        pos.raumbuch_zustand_vorher = element.zustand or 'gut'
        pos.save(update_fields=['raumbuch_zustand_vorher'])
        if element.zustand != neu:
            element.zustand = neu
            element.save(update_fields=['zustand'])
        n += 1
    return n


def vorzustand(pos):
    """Der Zustand, an dem dieses Bauteil gemessen wird: ``{'rang', 'text', 'quelle'}`` oder ``None``.

    ``quelle`` ist ``'protokoll'`` (Bewertung im Vorgänger-Protokoll) oder ``'raumbuch'`` (Stand des Raumbuchs vor
    dieser Abnahme; bei einem noch offenen Protokoll der aktuelle Stand)."""
    vp = pos.vorgaenger_position
    if vp is not None and vp.zustand in RANG_ABNAHME:
        return {'rang': RANG_ABNAHME[vp.zustand], 'text': str(vp.get_zustand_display()), 'quelle': 'protokoll'}
    stand = pos.raumbuch_zustand_vorher
    if not stand and pos.ausstattung_id and not pos.protokoll.abgeschlossen:
        stand = pos.ausstattung.zustand
    if stand in RANG_RAUMBUCH:
        return {'rang': RANG_RAUMBUCH[stand], 'text': gettext('Raumbuch: %(zustand)s') % {'zustand': _raumbuch_label(stand)},
                'quelle': 'raumbuch'}
    return None


def vergleich(pos):
    """``'gleich'``, ``'schlechter'``, ``'besser'`` — oder ``None``, wenn es nichts zu vergleichen gibt
    (Bauteil noch nicht bewertet oder ohne Vorzustand)."""
    if pos.zustand not in RANG_ABNAHME:
        return None
    vor = vorzustand(pos)
    if vor is None:
        return None
    jetzt = RANG_ABNAHME[pos.zustand]
    return 'gleich' if jetzt == vor['rang'] else ('schlechter' if jetzt > vor['rang'] else 'besser')


def vergleich_label(art):
    return {'gleich': gettext('gleich geblieben'), 'schlechter': gettext('schlechter'),
            'besser': gettext('besser')}.get(art, '')


def mit_vergleich(positionen):
    """Die Positionen mit ``.vor`` (Vorzustand oder None) und ``.veraenderung`` (Art oder None) — für die Anzeige."""
    liste = list(positionen)
    for p in liste:
        p.vor = vorzustand(p)
        p.veraenderung = vergleich(p)
        p.veraenderung_text = vergleich_label(p.veraenderung)
    return liste


def verlauf_je_element(einheit):
    """Alle Bewertungen aus abgeschlossenen Abnahmen je Raumbuch-Element der Einheit: ``{element_id: [Position, …]}``,
    neueste zuerst. Eine Abfrage für alle Elemente."""
    from rentals.models import AbnahmePosition
    ergebnis = {}
    qs = (AbnahmePosition.objects
          .filter(ausstattung__einheit=einheit, protokoll__abgeschlossen=True)
          .exclude(zustand='')
          .select_related('protokoll__vertrag__mieter')
          .order_by('-protokoll__datum', '-id'))
    for pos in qs:
        ergebnis.setdefault(pos.ausstattung_id, []).append(pos)
    return ergebnis
