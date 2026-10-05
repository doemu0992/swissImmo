"""Verteilschlüssel: Gewichte je Einheit und exakte Verteilung eines Betrags.

Ein Schlüssel liefert je Einheit ein GEWICHT; der Betrag wird im Verhältnis der Gewichte
verteilt (grösster Rest, auf den Rappen genau — `verteilung.verteile_nach_quoten`).
Gewicht 0 heisst: trägt nichts. Das ist der Weg, wie das Erdgeschoss von den Liftkosten
ausgenommen wird: Es steht mit Anteil 0 im Lift-Schlüssel, nicht «gar nicht» darin.

Fehlende Angaben sind ein Fehler, keine stille Null: Hat eine Einheit keine Fläche
(Schlüssel «Fläche») oder keinen Eintrag (Schlüssel «manuell»), wird nicht verteilt.
Sonst fiele eine Einheit unbemerkt aus der Verteilung und die anderen trügen ihren Teil.
"""
from django.utils.translation import gettext
from decimal import Decimal

from stweg.models import StwegKostenzuordnung, StwegSchluessel, StwegSchluesselAnteil
from stweg.validierung import stimm_einheiten
from stweg.verteilung import verteile_nach_quoten

STANDARD_NAME = 'Allgemeine Wertquote'
#: Schreibweisen des Erdgeschosses im freien Textfeld `Einheit.etage`.
EG_SCHREIBWEISEN = ('eg', 'erdgeschoss', 'parterre', '0')


class SchluesselFehler(ValueError):
    pass


def standard_schluessel(liegenschaft):
    """Der Standardschlüssel; wird beim ersten Zugriff als Wertquote angelegt."""
    s = liegenschaft.stweg_schluessel.filter(ist_standard=True).first()
    if s is None:
        s, _ = StwegSchluessel.objects.get_or_create(
            liegenschaft=liegenschaft, name=STANDARD_NAME,
            defaults={'art': StwegSchluessel.WERTQUOTE, 'ist_standard': True})
        if not s.ist_standard:
            raise SchluesselFehler(gettext('Der Schlüssel «%(STANDARD_NAME)s» existiert, ist aber nicht Standard.') % {'STANDARD_NAME': STANDARD_NAME})
    return s


def schluessel_fuer_konto(liegenschaft, konto):
    """Schlüssel für Kosten auf diesem Konto; ohne Zuordnung der Standardschlüssel."""
    if konto is not None:
        z = (StwegKostenzuordnung.objects.filter(liegenschaft=liegenschaft, konto=konto)
             .select_related('schluessel').first())
        if z is not None:
            return z.schluessel
    return standard_schluessel(liegenschaft)


def gewichte(schluessel, einheiten=None):
    """{einheit_pk: Gewicht} für alle stimmberechtigten Einheiten. Wirft bei Lücken."""
    einheiten = list(einheiten if einheiten is not None else stimm_einheiten(schluessel.liegenschaft))
    art = schluessel.art
    if art == StwegSchluessel.WERTQUOTE:
        g = {e.pk: Decimal(e.wertquote) for e in einheiten}
    elif art in (StwegSchluessel.FLAECHE, StwegSchluessel.VOLUMEN):
        feld, einheit_name = (('flaeche_m2', 'm²') if art == StwegSchluessel.FLAECHE else ('volumen_m3', 'm³'))
        fehlt = [e.bezeichnung for e in einheiten if getattr(e, feld) is None]
        if fehlt:
            raise SchluesselFehler(gettext('Schlüssel «%(name)s»: Angabe in %(einheit_name)s fehlt bei %(wert)s.') % {'name': schluessel.name, 'einheit_name': einheit_name, 'wert': ", ".join(fehlt)})
        g = {e.pk: Decimal(getattr(e, feld)) for e in einheiten}
    elif art == StwegSchluessel.MANUELL:
        vorhanden = {a.einheit_id: Decimal(a.anteil) for a in
                     StwegSchluesselAnteil.objects.filter(schluessel=schluessel)}
        fehlt = [e.bezeichnung for e in einheiten if e.pk not in vorhanden]
        if fehlt:
            raise SchluesselFehler(gettext('Schlüssel «%(name)s»: kein Anteil für %(wert)s (0 eintragen, wenn die Einheit nichts trägt).') % {'name': schluessel.name, 'wert': ", ".join(fehlt)})
        g = {e.pk: vorhanden[e.pk] for e in einheiten}
    else:
        raise SchluesselFehler(gettext('Unbekannte Schlüsselart «%(art)s».') % {'art': art})
    if any(w < 0 for w in g.values()):
        raise SchluesselFehler(gettext('Schlüssel «%(name)s» enthält negative Gewichte.') % {'name': schluessel.name})
    if sum(g.values(), Decimal('0')) <= 0:
        raise SchluesselFehler(gettext('Schlüssel «%(name)s»: die Summe der Gewichte ist 0.') % {'name': schluessel.name})
    return g


def verteile(betrag, schluessel, einheiten=None):
    """Verteilt `betrag` nach dem Schlüssel. Gibt (anteile, gewichte) zurück."""
    g = gewichte(schluessel, einheiten)
    return verteile_nach_quoten(betrag, g), g


def manuellen_schluessel_setzen(liegenschaft, name, anteile, *, bemerkung=''):
    """Legt einen manuellen Schlüssel an bzw. ersetzt dessen Anteile. `anteile`: {Einheit: Gewicht}."""
    s, _ = StwegSchluessel.objects.get_or_create(
        liegenschaft=liegenschaft, name=name, defaults={'art': StwegSchluessel.MANUELL, 'bemerkung': bemerkung})
    if s.art != StwegSchluessel.MANUELL:
        raise SchluesselFehler(gettext('«%(name)s» ist kein Schlüssel mit eigenen Anteilen.') % {'name': name})
    for einheit, gewicht in anteile.items():
        if einheit.liegenschaft_id != liegenschaft.pk:
            raise SchluesselFehler(gettext('Einheit «%(bezeichnung)s» gehört nicht zu dieser Gemeinschaft.') % {'bezeichnung': einheit.bezeichnung})
        if Decimal(gewicht) < 0:
            raise SchluesselFehler(gettext('Anteile dürfen nicht negativ sein.'))
        StwegSchluesselAnteil.objects.update_or_create(schluessel=s, einheit=einheit,
                                                       defaults={'anteil': Decimal(gewicht)})
    return s


def lift_schluessel(liegenschaft, name='Lift', ausgeschlossen=EG_SCHREIBWEISEN):
    """Liftschlüssel: Einheiten auf den Etagen `ausgeschlossen` (Vorgabe: Erdgeschoss) tragen 0,
    alle anderen ihre Wertquote. Ein anderes Verhältnis (z. B. höhere Stockwerke mehr) ist als
    manueller Schlüssel von Hand zu setzen."""
    ausgeschlossen = {str(x).strip().lower() for x in ausgeschlossen}
    anteile = {e: (Decimal('0') if (e.etage or '').strip().lower() in ausgeschlossen else Decimal(e.wertquote))
               for e in stimm_einheiten(liegenschaft)}
    return manuellen_schluessel_setzen(liegenschaft, name, anteile)


def etage_nummer(text):
    """Die Stockwerknummer aus dem freien Textfeld `Einheit.etage`: «EG» → 0, «1. OG» → 1, «2.OG» → 2.
    Alles, was sich nicht eindeutig lesen lässt («Attika», «DG», «Maisonette»), gibt None — das System rät nicht."""
    import re
    t = (text or '').strip().lower()
    if t in EG_SCHREIBWEISEN:
        return 0
    m = re.fullmatch(r'(\d+)\s*\.?\s*(?:og|obergeschoss|stock|etage)?', t)
    if m and not re.search(r'ug|untergeschoss|keller', t):
        return int(m.group(1))
    return None


def lift_nach_stockwerk(liegenschaft, name='Lift', *, etagen=None):
    """Liftschlüssel nach Stockwerk: Gewicht = Stockwerknummer (EG = 0 trägt nichts, 1. OG = 1, 2. OG = 2 …).

    Wer höher wohnt, fährt weiter und trägt mehr. Die Gewichtung nach Stockwerknummer ist eine übliche
    Vereinbarung, aber KEINE Rechtsnorm — das Reglement der Gemeinschaft kann etwas anderes vorsehen; dann einen
    eigenen Schlüssel mit eigenen Anteilen anlegen.

    Lässt sich eine Etage nicht lesen (`etage_nummer` gibt None), wird nichts angelegt: `etagen` ({Einheit: Nummer})
    muss sie ausdrücklich nennen."""
    etagen = etagen or {}
    anteile, unklar = {}, []
    for e in stimm_einheiten(liegenschaft):
        n = etagen.get(e, etagen.get(e.pk))
        if n is None:
            n = etage_nummer(e.etage)
        if n is None:
            unklar.append(f'«{e.bezeichnung}» (Etage «{e.etage or "leer"}»)')
        else:
            anteile[e] = Decimal(n)
    if unklar:
        raise SchluesselFehler('Die Stockwerknummer ist nicht lesbar bei ' + ', '.join(unklar)
                               + ' — bitte in der Einheit eintragen oder ausdrücklich angeben.')
    return manuellen_schluessel_setzen(liegenschaft, name, anteile,
                                       bemerkung='nach Stockwerk (EG = 0)')


def kostenart_zuordnen(liegenschaft, konto, schluessel):
    if schluessel.liegenschaft_id != liegenschaft.pk:
        raise SchluesselFehler(gettext('Der Schlüssel gehört zu einer anderen Gemeinschaft.'))
    return StwegKostenzuordnung.objects.update_or_create(
        liegenschaft=liegenschaft, konto=konto, defaults={'schluessel': schluessel})[0]
