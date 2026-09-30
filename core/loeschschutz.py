"""Löschschutz: offene Forderungen und Vorgänge verhindern das Löschen.

WARUM ES DAS GIBT (Go-Live-Härtetest, Schritt 2)

`DebitorenRechnung.vertrag` und `.liegenschaft` sind bewusst SET_NULL — die
Buchhaltung soll ein Löschen überleben (Art. 958f OR, 10 Jahre). Nur verlor eine
OFFENE Forderung dabei ihren Schuldner: Wer einen Mieter oder eine Liegenschaft
löschte, während noch Rechnungen offen waren, hinterliess Forderungen ohne
Vertrag, ohne Person und ohne Objekt — im Mahnwesen und im Mieterkonto nicht
mehr auffindbar, im Hauptbuch aber weiter als Debitorensaldo stehend.
Die Lösch-Views prüften nur «aktiver Vertrag».

Die Prüfung sitzt im Modell (`delete()`), nicht nur in der View: Sie greift
damit auch für Admin und jeden künftigen Löschpfad. Kaskaden und
`QuerySet.delete()` (Datenreset, Organisation löschen) gehen bewusst daran
vorbei — dort ist das Löschen alles gewollt.
"""
from django.db.models import ProtectedError, Q

OFFENE_DEBITOREN = ('offen', 'teilbezahlt')
OFFENE_KREDITOREN = ('neu', 'freigegeben', 'in_zahlung', 'teilbezahlt')


class LoeschSperre(ProtectedError):
    """Löschen verweigert; `.args[0]` ist eine Meldung für Anwender."""

    def __init__(self, msg):
        super().__init__(msg, [])

    def __str__(self):
        return str(self.args[0])


def _debitoren(filter_):
    from finance.models import DebitorenRechnung
    return DebitorenRechnung.objects.filter(filter_, status__in=OFFENE_DEBITOREN)


def sperre_pruefen(*, mieter=None, vertrag=None, liegenschaft=None, einheit=None):
    """Wirft `LoeschSperre`, wenn am Objekt noch Offenes hängt."""
    gruende = []
    if mieter is not None:
        n = _debitoren(Q(vertrag__mieter=mieter)).count()
        if n:
            gruende.append(f'{n} offene Rechnung(en) im Mieterkonto')
    if vertrag is not None:
        n = _debitoren(Q(vertrag=vertrag)).count()
        if n:
            gruende.append(f'{n} offene Rechnung(en) zum Vertrag')
    if liegenschaft is not None or einheit is not None:
        if liegenschaft is not None:
            f = Q(liegenschaft=liegenschaft) | Q(vertrag__einheit__liegenschaft=liegenschaft)
            objekt = {'liegenschaft': liegenschaft}
        else:
            f = Q(einheit=einheit) | Q(vertrag__einheit=einheit)
            objekt = {'einheit': einheit}
        n = _debitoren(f).count()
        if n:
            gruende.append(f'{n} offene Mieterrechnung(en)')
        from finance.models import KreditorenRechnung
        n = KreditorenRechnung.objects.filter(status__in=OFFENE_KREDITOREN, **objekt).count()
        if n:
            gruende.append(f'{n} offene Lieferantenrechnung(en)')
        if liegenschaft is not None:
            from tickets.models import SchadenMeldung
            n = SchadenMeldung.objects.filter(liegenschaft=liegenschaft).exclude(status='erledigt').count()
            if n:
                gruende.append(f'{n} offene(s) Ticket(s)')
    if gruende:
        raise LoeschSperre('Löschen nicht möglich: ' + ', '.join(gruende) + '. Bitte zuerst erledigen.')
