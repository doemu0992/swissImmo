"""Schlussbestimmungen der Abnahme (Text im PDF).

QUELLE UND VORBEHALT. Der Wortlaut stammt unverändert aus einem Abnahme-/
Übergabeprotokoll der Praxis (Turmstrasse 5/7, Bellach; HR Immobilien AG) und
ist der Standardtext dieser Verwaltung — nicht eine juristisch geprüfte
Mustervorlage. Er enthält Rechtsfolgen (Mängelrüge nach Art. 267a OR, Haftung,
Auflösung des Mietzinsdepots, Rügefrist von 10 Tagen beim Einzug). Wer das
Protokoll mit eigenem Wortlaut verwenden will, ändert ihn hier; eine Prüfung
durch eine Mietrechtsfachperson ist vor dem produktiven Einsatz ratsam.

Welche Absätze erscheinen, entscheidet `schlussbestimmungen()`:
- die Mängelrüge nur, wenn dem Mieter Mängel zugeordnet sind (sie nimmt Bezug
  auf «oben genannte» Mängel),
- Haftung und Depot beim Auszug, die Rügefrist beim Einzug.
"""

KOSTENUEBERNAHME = (
    "Der/die Vermieter/-in macht oben genannte Mangelhaftigkeiten als Mängelrüge, gestützt auf "
    "Art. 267a OR, ausdrücklich geltend und erklärt, dass im Sinne der erwähnten Gesetzesbestimmung "
    "der/die ausziehende Mieter/-in für diese Mängel einzustehen hat. Mit der Unterzeichnung des "
    "vorliegenden Protokolls anerkennt der/die ausziehende Mieter/-in diese Mängelrüge zur Kenntnis "
    "genommen zu haben und seine/ihre Haftung für die erwähnten Mangelhaftigkeiten. Die Verwaltung "
    "wird ermächtigt, die Instandstellungsarbeiten in Auftrag zu geben und einem allfälligen "
    "Mietzinsdepot direkt zu belasten."
)
HAFTUNG = (
    "Eine vorzeitige Schlüsselrückgabe entbindet nicht aus der Mietzinshaftpflicht, welche bis zum "
    "ordentlichen Mietende dauert."
)
MIETZINSDEPOT = (
    "Der/die ausziehende Mieter/-in ermächtigt den/die Vermieter/-in ausdrücklich, das bei "
    "seiner/ihrer Mietvertragsunterzeichnung vereinbarte und einbezahlte Mietzinsdepot bei der "
    "entsprechenden Bank aufzulösen. Der/die Vermieter/-in verpflichtet sich, das Depot plus Zinsen "
    "abzüglich allfällige Kosten für Mängelbehebungen, Minderwerte, Ausstände etc. innert nützlicher "
    "Frist dem/der Mieter/-in auszubezahlen."
)
MAENGEL_EINZUG = (
    "Der/die einziehende Mieter/-in bescheinigt, das Mietobjekt mit den angeführten Schlüsseln "
    "übernommen zu haben. Bei der Übergabe nicht erkannte und nicht protokollierte Mängel sind "
    "dem/der Vermieter/-in innert 10 Tagen nach Mietbeginn schriftlich zu melden. Für nicht "
    "gemeldete Mängel haftet der/die Mieter/-in."
)


#: Schlüssel → (Überschrift im PDF, Standardtext). Die Reihenfolge ist die der Einstellungsseite.
ABSAETZE = {
    'kosten': ("Kostenübernahme", KOSTENUEBERNAHME),
    'haftung': ("Haftung", HAFTUNG),
    'depot': ("Mietzinsdepot", MIETZINSDEPOT),
    'einzug': ("Mängel", MAENGEL_EINZUG),
}
MAX_LAENGE = 3000


def eigene_texte(organisation):
    """Die abweichenden Texte einer Organisation als `{schluessel: text}`.
    Ausdrücklich über `alle_organisationen` mit Organisation: Das PDF kann auch
    ausserhalb eines Anfragekontexts entstehen."""
    from rentals.models import AbnahmeText
    if organisation is None:
        return {}
    return dict(AbnahmeText.alle_organisationen.filter(organisation=organisation)
                .values_list('schluessel', 'text'))


def schlussbestimmungen(prot):
    """Die Absätze (Überschrift, Text) für dieses Protokoll — mit dem Wortlaut
    der Verwaltung, soweit sie ihn geändert hat, sonst mit dem Standard."""
    eigene = eigene_texte(prot.organisation)

    def absatz(schluessel):
        titel, standard = ABSAETZE[schluessel]
        return (titel, eigene.get(schluessel) or standard)

    if prot.typ == 'einzug':
        return [absatz('einzug')]
    absaetze = []
    if prot.maengel_mieter:
        absaetze.append(absatz('kosten'))
    absaetze.append(absatz('haftung'))
    absaetze.append(absatz('depot'))
    return absaetze
