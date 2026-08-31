"""Vorschlag und Übernahme im Zulauf.

Der Grundsatz steht in `faelle.zulauf_models`: **nie raten**. Diese Datei setzt
ihn um. Ein Vorschlag entsteht nur aus einem Merkmal, das eindeutig trägt; sonst
ist die Antwort `KEINER`, und das ist die richtige Antwort.

Reihenfolge der Merkmale — vom stärksten zum schwächsten:

1. **Gelernte Regel** auf Referenz. Eine QR-Referenz ist konstruiert, nicht
   geraten; wer sie trifft, meint diesen Vorgang.
2. **Gelernte Regel** auf Absenderadresse. Eine Adresse gehört einem Postfach.
3. **Gelernte Regel** auf Absendername. Schwächer, weil Namen sich wiederholen.
4. **Bekannte Mieteradresse.** Schreibt jemand von der Adresse, die an einem
   laufenden Mietverhältnis hinterlegt ist, ist die Akte bestimmt.

Was hier bewusst NICHT steht: Ähnlichkeitsvergleiche auf Betreff oder Namen.
Sie treffen oft und irren selten sichtbar — genau die Kombination, die Vertrauen
aufbaut und dann teuer wird.
"""
import logging
from dataclasses import dataclass
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

SICHER, KEINER = 'sicher', 'keiner'


@dataclass
class Vorschlag:
    """Was der Zulauf vorschlägt — oder ausdrücklich nicht.

    `sicherheit == KEINER` ist kein Fehler. Es heisst: Die Merkmale tragen
    nicht, und ein Mensch entscheidet.
    """

    sicherheit: str = KEINER
    ziel: Any = None
    fallart: Any = None
    begruendung: str = ''
    regel: Any = None

    def __bool__(self):
        return self.sicherheit == SICHER



def _betreuer_fuer(akte):
    """Wer die Liegenschaft hinter dieser Akte betreut — oder `None`.

    Die Akte kann alles Moegliche sein: Liegenschaft, Einheit, Vertrag,
    Mieter, Eigentuemer. Nur die ersten drei fuehren zu einer Liegenschaft;
    bei den anderen gibt es keine, und dann ist `None` die richtige Antwort.

    Ein Fehler hier darf die Zuordnung nicht kosten — sie ist die
    Hauptsache, die Betreuung eine Verbesserung.
    """
    try:
        lg = getattr(akte, 'liegenschaft', None) or (
            akte if akte.__class__.__name__ == 'Liegenschaft' else None)
        if lg is None:
            einheit = getattr(akte, 'einheit', None)
            lg = getattr(einheit, 'liegenschaft', None) if einheit else None
        return getattr(lg, 'betreut_von', None) if lg else None
    except Exception:
        logging.getLogger(__name__).exception('Betreuer nicht ermittelbar')
        return None

def vorschlagen(eingang):
    """Ermittelt den Zuordnungsvorschlag für einen Eingang."""
    from faelle.zulauf_models import Zuordnungsregel, normalisieren

    regeln = Zuordnungsregel.objects.filter(aktiv=True)

    if eingang.referenz:
        treffer = regeln.filter(
            merkmal=Zuordnungsregel.REFERENZ,
            wert=normalisieren(eingang.referenz)).first()
        if treffer:
            return _aus_regel(treffer, 'Referenz stimmt mit einer gelernten Regel überein.')

    if eingang.absender_email:
        treffer = regeln.filter(
            merkmal=Zuordnungsregel.EMAIL,
            wert=normalisieren(eingang.absender_email)).first()
        if treffer:
            return _aus_regel(treffer, 'Absenderadresse ist gelernt.')

    if eingang.absender_norm:
        treffer = regeln.filter(
            merkmal=Zuordnungsregel.ABSENDER, wert=eingang.absender_norm).first()
        if treffer:
            return _aus_regel(treffer, 'Absendername ist gelernt.')

    if eingang.absender_email:
        vertrag = _vertrag_zur_adresse(eingang.absender_email)
        if vertrag is not None:
            return Vorschlag(
                sicherheit=SICHER, ziel=vertrag,
                begruendung=('Die Absenderadresse ist am laufenden '
                             'Mietverhältnis hinterlegt.'))

    return Vorschlag(
        sicherheit=KEINER,
        begruendung=('Kein Merkmal trägt eindeutig. Bitte von Hand zuordnen — '
                     'die Zuordnung lässt sich dabei als Regel merken.'))


def _aus_regel(regel, begruendung):
    return Vorschlag(sicherheit=SICHER, ziel=regel.akte, fallart=regel.fallart,
                     begruendung=begruendung, regel=regel)


def _vertrag_zur_adresse(adresse):
    """Genau ein laufendes Mietverhältnis zu dieser Adresse, sonst nichts.

    Bei zwei Treffern wird ausdrücklich **keiner** gewählt. Zwei Verträge
    desselben Mieters sind der Normalfall bei einem Umzug innerhalb des
    Portfolios — dort zu raten hiesse, die Post im falschen Dossier abzulegen.
    """
    from rentals.models import Mietvertrag

    treffer = list(
        Mietvertrag.objects.filter(mieter__email__iexact=adresse.strip())[:2])
    return treffer[0] if len(treffer) == 1 else None


def uebernehmen(eingang, ziel=None, fallart=None, benutzer=None,
                regel_lernen=False, merkmal=None):
    """Ordnet einen Eingang zu und eröffnet bei Bedarf einen Fall.

    ``ziel``          Akte, an die der Eingang gehängt wird. Fehlt sie, wird
                      der Vorschlag genommen — gibt es keinen, wirft die
                      Funktion, statt still nichts zu tun.
    ``fallart``       Gesetzt: Es entsteht ein Fall dieser Art.
    ``regel_lernen``  Merkt sich das Merkmal für künftige Eingänge.
    ``merkmal``       Welches Merkmal gelernt wird; ohne Angabe die stärkste
                      vorhandene Angabe des Eingangs.

    Idempotent: Ein bereits zugeordneter Eingang wird nicht erneut verarbeitet.
    """
    from faelle.models import Fall
    from faelle.zulauf_models import Eingang, Zuordnungsregel, normalisieren

    if eingang.status != Eingang.OFFEN:
        return eingang.fall

    if ziel is None:
        vorschlag = vorschlagen(eingang)
        if not vorschlag:
            raise ValueError(
                'Kein tragfähiger Vorschlag — ein Ziel muss angegeben werden. '
                'Raten ist hier ausdrücklich nicht vorgesehen.')
        ziel, fallart = vorschlag.ziel, fallart or vorschlag.fallart
        if vorschlag.regel:
            vorschlag.regel.getroffen()

    fall = None
    if fallart is not None:
        # DIE BETREUUNG DER LIEGENSCHAFT GEHT VOR (E2.70).
        #
        # Bisher bekam der Fall den Benutzer, der GERADE UEBERNIMMT. Das ist
        # bei einer Verwaltung mit mehreren Personen falsch: Wer den
        # Posteingang leert, ist nicht, wer die Liegenschaft betreut.
        #
        # `betreut_von` an der Liegenschaft ist die uebliche Aufteilung («Die
        # Bahnhofstrasse macht Lea»). Fehlt sie, bleibt es beim Uebernehmenden
        # — besser als niemand, und der Fall laesst sich am Fall aendern.
        fall = Fall(fallart=fallart, akte=ziel,
                    zustaendig=_betreuer_fuer(ziel) or benutzer,
                    betreff=eingang.betreff[:200])
        fall.save()
        fall.schritte_anlegen()

    eingang.akte = ziel
    eingang.fall = fall
    eingang.status = Eingang.ZUGEORDNET
    eingang.erledigt_am = timezone.now()
    eingang.erledigt_durch = benutzer
    eingang.save(update_fields=['akte_typ', 'akte_id', 'fall', 'status',
                                'erledigt_am', 'erledigt_durch'])

    if regel_lernen:
        art, wert, anzeige = _merkmal_bestimmen(eingang, merkmal)
        if wert:
            Zuordnungsregel.objects.update_or_create(
                organisation=eingang.organisation, merkmal=art, wert=wert,
                defaults={
                    'wert_anzeige': anzeige,
                    'akte_typ': ContentType.objects.get_for_model(ziel),
                    'akte_id': ziel.pk,
                    'fallart': fallart,
                })
    return fall


def _merkmal_bestimmen(eingang, merkmal):
    from faelle.zulauf_models import Zuordnungsregel, normalisieren

    kandidaten = [
        (Zuordnungsregel.REFERENZ, eingang.referenz),
        (Zuordnungsregel.EMAIL, eingang.absender_email),
        (Zuordnungsregel.ABSENDER, eingang.absender),
    ]
    if merkmal:
        kandidaten = [(a, w) for a, w in kandidaten if a == merkmal]
    for art, wert in kandidaten:
        if wert:
            return art, normalisieren(wert), wert
    return None, '', ''
