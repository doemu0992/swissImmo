"""Sonderrecht oder Gemeinschaftseigentum? Welche Bauteile zwingend der Gemeinschaft gehören (Art. 712b ZGB).

Art. 712b Abs. 2 ZGB nimmt Bauteile vom Sonderrecht aus, die für Bestand, konstruktive Gliederung und Festigkeit des
Gebäudes oder für die Räume anderer Stockwerke wichtig sind, ebenso Anlagen und Einrichtungen, die auch den anderen
dienen. Ihre Kosten sind Kosten der Gemeinschaft (Jahresabrechnung), nie die eines einzelnen Eigentümers. Daran ändert
weder der Eigentümer noch ein Ticket noch ein Reglement etwas — es ist zwingend.

DER KATALOG (`BAUTEILE`) ist die EINE Stelle, an der eine Zuordnung steht. Er folgt dem Auftrag und den üblichen
Beispielen (Dach, Fassade, Fenster aussen, tragende Teile, Hauptleitungen, Anlagen für alle); die Einordnung eines
Bauteils im Einzelfall richtet sich nach dem Begründungsakt und dem Reglement. «Sonstiges» ist NICHT zwingend
gemeinschaftlich — es ist ein Hinweis, die Einordnung zu prüfen. Wer ein Bauteil falsch ablegt, kann die Sperre
umgehen: Der Katalog ersetzt keine rechtliche Prüfung.

DIE REGEL. Bei einem Schaden in einer STWEG müssen BAUTEIL und KOSTENTRÄGER deklariert sein, bevor ein Auftrag vergeben
oder das Ticket erledigt wird. «Sonderrecht» auf einem zwingend gemeinschaftlichen Bauteil ist ein Fehler und wird
nicht gespeichert. Rechnungen eines Tickets, das gemeinschaftlich ist oder ein zwingend gemeinschaftliches Bauteil
betrifft, werden in der Jahresabrechnung nie einer einzelnen Einheit belastet.
"""
from django.utils.translation import gettext, gettext_lazy as _

GEMEINSCHAFTLICH, SONDERRECHT = 'gemeinschaftlich', 'sonderrecht'
KOSTENTRAEGER_CHOICES = [(GEMEINSCHAFTLICH, _('Gemeinschaftlich (Kosten gehen in die STWEG-Jahresrechnung)')),
                         (SONDERRECHT, _('Sonderrecht (Kosten trägt der Eigentümer direkt)'))]

# key: (Bezeichnung, zwingend gemeinschaftlich)
BAUTEILE = {
    'dach': (_('Dach'), True),
    'fassade': (_('Fassade'), True),
    'fenster_aussen': (_('Fenster (Aussenseite)'), True),
    'tragend': (_('Tragende Wände, Decken, Fundament'), True),
    'hauptleitung': (_('Hauptleitungen (Wasser, Abwasser, Strom, Heizung)'), True),
    'treppenhaus': (_('Treppenhaus, Eingang, gemeinschaftliche Räume'), True),
    'anlage': (_('Lift, Heizung und andere Anlagen für alle'), True),
    'aussenbereich': (_('Grundstück, Umgebung, Zufahrt'), True),
    'fenster_innen': (_('Fenster (Innenseite: Beschläge, Anstrich)'), False),
    'innenwand': (_('Nichttragende Innenwand'), False),
    'bodenbelag': (_('Bodenbelag in der Einheit'), False),
    'oberflaeche': (_('Verputz, Tapete, Anstrich innen'), False),
    'kueche_sanitaer': (_('Küche, Bad und Sanitärapparate der Einheit'), False),
    'leitung_einheit': (_('Leitungen innerhalb der Einheit'), False),
    'tuer_innen': (_('Innentüren der Einheit'), False),
    'sonstiges': (_('Sonstiges (Einordnung rechtlich prüfen)'), False),
}
BAUTEIL_CHOICES = [(k, b) for k, (b, _z) in BAUTEILE.items()]


def ist_zwingend(bauteil):
    return bool(bauteil) and bauteil in BAUTEILE and BAUTEILE[bauteil][1]


def bezeichnung(bauteil):
    return str(BAUTEILE[bauteil][0]) if bauteil in BAUTEILE else ''


def auswahl():
    """Für die Oberfläche: [(key, Bezeichnung, zwingend)]."""
    return [(k, b, z) for k, (b, z) in BAUTEILE.items()]


def sperre(bauteil, kostentraeger):
    """Der Fehler, wenn ein zwingend gemeinschaftliches Bauteil als Sonderrecht deklariert wird — sonst None."""
    if kostentraeger == SONDERRECHT and ist_zwingend(bauteil):
        return gettext('«%(bauteil)s» ist zwingend gemeinschaftliches Eigentum (Art. 712b Abs. 2 ZGB): Die Kosten können '
                       'nicht einem einzelnen Eigentümer als Sonderrecht belastet werden. Bitte «gemeinschaftlich» '
                       'wählen.') % {'bauteil': bezeichnung(bauteil)}
    return None


def probleme(ticket):
    """Was an der Deklaration eines STWEG-Tickets fehlt oder falsch ist (leer = in Ordnung, auch ausserhalb STWEG)."""
    if ticket.liegenschaft_id is None or not ticket.liegenschaft.ist_stweg:
        return []
    fehler = []
    if ticket.bauteil not in BAUTEILE:
        fehler.append(gettext('Bitte das betroffene Bauteil angeben.'))
    if ticket.kostentraeger not in (GEMEINSCHAFTLICH, SONDERRECHT):
        fehler.append(gettext('Bitte erklären: «Sonderrecht» (der Eigentümer trägt die Kosten) oder «Gemeinschaftlich» '
                              '(Kosten der Jahresrechnung).'))
    s = sperre(ticket.bauteil, ticket.kostentraeger)
    if s:
        fehler.append(s)
    if ticket.kostentraeger == SONDERRECHT and ticket.betroffene_einheit_id is None:
        fehler.append(gettext('Bei Sonderrecht die betroffene Einheit angeben — sie bestimmt, wer die Kosten trägt.'))
    return fehler


def gemeinschaftlich_zu_belasten(ticket):
    """Gehen die Kosten dieses Tickets zwingend in die Jahresrechnung (nie auf eine einzelne Einheit)?"""
    return ticket.kostentraeger == GEMEINSCHAFTLICH or ist_zwingend(ticket.bauteil)
