"""Die gesetzlichen Quoren für Beschlüsse der Stockwerkeigentümerversammlung — und ihre Prüfung.

DER KATALOG (`GESCHAEFTSARTEN`) bildet die drei Quoren des Auftrags ab; die Artikel stehen als Quelle dabei. Er ist die
EINE Stelle, an der sich das ändert, falls eine Fachperson eine Zuordnung anders liest:

  verwaltung   Gewöhnliche Verwaltungshandlung         einfaches Mehr der Anwesenden (Köpfe)
               (Art. 712m ZGB i.V.m. Vereinsrecht, Art. 67 ZGB)                 → mindestens «einfach_koepfe»
  nuetzlich    Nützliche bauliche Massnahme            Mehrheit ALLER Eigentümer (Köpfe) UND mehr als die Hälfte
               (Art. 647d ZGB i.V.m. Art. 712g Abs. 3 ZGB)      aller Wertquoten   → mindestens «doppelt_aller»
  reglement    Änderung des Reglements                 wie «nuetzlich» (Vorgabe des Auftrags; Artikel zu bestätigen)
  luxurioes    Luxuriöse bauliche Massnahme            Einstimmigkeit aller Eigentümer (alle Köpfe)
               (Art. 647e ZGB i.V.m. Art. 712g Abs. 3 ZGB)                      → «einstimmig»
  kenntnis     Zur Kenntnisnahme                       keine Abstimmung
  sonstiges    Anderes Geschäft / abweichendes Quorum  jede Mehrheitsart — mit ausdrücklicher Rechtsgrundlage
               (Reglement, Artikel), die im Protokoll steht

«Mehrheit der Köpfe» heisst bei den qualifizierten Quoren: Mehrheit ALLER Stockwerkeigentümer, nicht nur der Anwesenden
(«doppelt_aller»). Ein Kopf ist ein Eigentümer, mehrere Einheiten derselben Person zählen einmal (`stweg.beschluss`).

DIE REGEL. Beim Anlegen eines Traktandums MUSS die Verwaltung die Art des Geschäfts UND die Mehrheitsart wählen; es gibt
keine stillen Vorgaben. Eine Mehrheitsart, die SCHWÄCHER ist als das verlangte Minimum, wird abgewiesen (fail closed);
eine strengere ist erlaubt. Wer ein abweichendes Quorum aus dem Reglement anwenden muss, wählt «sonstiges» und nennt
die Rechtsgrundlage. Ohne gültige Angaben wird weder eingeladen noch ein Ergebnis festgestellt.

STRENGE (Rang): einfach (Köpfe oder Quoten) < doppelt (der Stimmenden) < doppelt_anwesende < doppelt_aller < einstimmig.
"""
from django.utils.translation import gettext, gettext_lazy as _

from stweg.models import Traktandum

RANG = {'einfach_koepfe': 1, 'einfach_quoten': 1, 'doppelt': 2, 'doppelt_anwesende': 3, 'doppelt_aller': 4,
        'einstimmig': 5}

# key: (Bezeichnung, Mindestmehrheit, Quelle)
GESCHAEFTSARTEN = {
    'verwaltung': (_('Gewöhnliche Verwaltungshandlung'), 'einfach_koepfe',
                   'Art. 712m ZGB i.V.m. Vereinsrecht (Art. 67 ZGB)'),
    'nuetzlich': (_('Nützliche bauliche Massnahme'), 'doppelt_aller', 'Art. 647d ZGB i.V.m. Art. 712g Abs. 3 ZGB'),
    'reglement': (_('Änderung des Reglements'), 'doppelt_aller', 'Vorgabe des Auftrags (Artikel zu bestätigen)'),
    'luxurioes': (_('Luxuriöse bauliche Massnahme'), 'einstimmig', 'Art. 647e ZGB i.V.m. Art. 712g Abs. 3 ZGB'),
    'kenntnis': (_('Zur Kenntnisnahme (keine Abstimmung)'), 'kenntnisnahme', ''),
    'sonstiges': (_('Anderes Geschäft / abweichendes Quorum (Rechtsgrundlage nötig)'), None, ''),
}


class QuorumFehler(ValueError):
    def __init__(self, probleme):
        self.probleme = probleme if isinstance(probleme, list) else [probleme]
        super().__init__(' '.join(self.probleme))


def auswahl():
    """Für die Oberfläche: [(key, Bezeichnung, Mindestmehrheit)]."""
    return [(k, b, m or '') for k, (b, m, _q) in GESCHAEFTSARTEN.items()]


def mindestens(geschaeftsart):
    """Die gesetzlich mindestens verlangte Mehrheitsart (None bei «sonstiges»)."""
    return GESCHAEFTSARTEN[geschaeftsart][1]


def probleme(geschaeftsart, mehrheitsart, rechtsgrundlage=''):
    """Alle Gründe, warum diese Angaben nicht zulässig sind (leer = in Ordnung)."""
    fehler = []
    if geschaeftsart not in GESCHAEFTSARTEN:
        return [gettext('Bitte die Art des Geschäfts wählen — sie bestimmt die gesetzlich verlangte Mehrheit.')]
    if mehrheitsart not in dict(Traktandum.MEHRHEIT_CHOICES):
        return [gettext('Bitte die Mehrheitsart wählen.')]
    bezeichnung, minimum, quelle = GESCHAEFTSARTEN[geschaeftsart]
    if geschaeftsart == 'kenntnis':
        if mehrheitsart != 'kenntnisnahme':
            fehler.append(gettext('Zur Kenntnisnahme gibt es keine Abstimmung.'))
        return fehler
    if mehrheitsart == 'kenntnisnahme':
        fehler.append(gettext('«%(geschaeft)s» braucht eine Abstimmung: Kenntnisnahme genügt nicht.')
                      % {'geschaeft': bezeichnung})
        return fehler
    if geschaeftsart == 'sonstiges':
        if not (rechtsgrundlage or '').strip():
            fehler.append(gettext('Für ein anderes Geschäft oder ein abweichendes Quorum ist die Rechtsgrundlage '
                                  '(Reglement, Artikel) anzugeben.'))
        return fehler
    if RANG[mehrheitsart] < RANG[minimum]:
        fehler.append(gettext('Für «%(geschaeft)s» verlangt das Gesetz mindestens: %(mindest)s (%(quelle)s). '
                              'Gewählt ist eine schwächere Mehrheit.')
                      % {'geschaeft': bezeichnung, 'mindest': dict(Traktandum.MEHRHEIT_CHOICES)[minimum],
                         'quelle': quelle})
    return fehler


def pruefen(geschaeftsart, mehrheitsart, rechtsgrundlage=''):
    p = probleme(geschaeftsart, mehrheitsart, rechtsgrundlage)
    if p:
        raise QuorumFehler(p)


def traktandum_pruefen(t):
    """Probleme eines gespeicherten Traktandums (leer = in Ordnung)."""
    return probleme(t.geschaeftsart, t.mehrheitsart, t.rechtsgrundlage)


def traktandum_anlegen(versammlung, titel, geschaeftsart, mehrheitsart, **felder):
    """Legt ein Traktandum an — nur mit gültiger Art des Geschäfts und Mehrheitsart (`QuorumFehler` sonst)."""
    pruefen(geschaeftsart, mehrheitsart, felder.get('rechtsgrundlage', ''))
    nr = (versammlung.traktanden.order_by('-nr').values_list('nr', flat=True).first() or 0) + 1
    return Traktandum.objects.create(versammlung=versammlung, nr=nr, titel=titel, geschaeftsart=geschaeftsart,
                                     mehrheitsart=mehrheitsart, **felder)


def geschaeftsart_setzen(t, geschaeftsart, mehrheitsart, rechtsgrundlage=None):
    """Setzt Art des Geschäfts und Mehrheitsart eines noch offenen Traktandums (auch nachträglich für Altbestand)."""
    if t.ergebnis != Traktandum.OFFEN:
        raise QuorumFehler(gettext('Das Ergebnis ist schon festgestellt — die Mehrheitsart lässt sich nicht mehr ändern.'))
    recht = t.rechtsgrundlage if rechtsgrundlage is None else rechtsgrundlage
    pruefen(geschaeftsart, mehrheitsart, recht)
    t.geschaeftsart, t.mehrheitsart, t.rechtsgrundlage = geschaeftsart, mehrheitsart, recht
    t.save(update_fields=['geschaeftsart', 'mehrheitsart', 'rechtsgrundlage'])
    return t
