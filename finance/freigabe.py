"""Die Eigentümerfreigabe einer Reparatur sperrt die Rechnung — nicht nur die Anzeige.

Ab CHF 1'000 (oder auf Verlangen) geht ein Handwerkerauftrag zur Freigabe an die
Eigentümerschaft (`HandwerkerAuftrag.freigabe_status`). Im Stresstest vom
30.09.2026 stand die Freigabe auf «ausstehend», und die zugehörige
Kreditorenrechnung liess sich trotzdem freigeben, buchen und bezahlen: Die Regel
war eine Anzeige, keine Sperre.

EINE Stelle entscheidet. Freigeben, bezahlen (einzeln, Zahllauf, Zahlungsdatei)
und Weiterverrechnen fragen alle hier.

Gesperrt ist bei `ausstehend` und `abgelehnt`. `nicht_noetig` und `freigegeben`
lassen durch. Eine Rechnung ohne Auftrag ist nie gesperrt: Die Eigentümerfreigabe
hängt am Auftrag, und eine Lieferantenrechnung, die keinem Auftrag zugeordnet ist
(Strom, Versicherung), hat keinen.
"""
GESPERRT = ('ausstehend', 'abgelehnt')


def freigabe_sperre(kreditor):
    """Begründung, weshalb die Rechnung nicht weiterlaufen darf — oder None."""
    if kreditor is None or not kreditor.pk:
        return None
    for a in kreditor.handwerker_auftraege.all():
        if a.freigabe_status == 'ausstehend':
            return ('Die Reparaturfreigabe der Eigentümerschaft steht noch aus '
                    f'(Auftrag #{a.pk}). Die Rechnung kann erst nach der Freigabe '
                    'freigegeben, bezahlt oder weiterverrechnet werden.')
        if a.freigabe_status == 'abgelehnt':
            return ('Die Eigentümerschaft hat die Reparatur abgelehnt '
                    f'(Auftrag #{a.pk}). Die Rechnung darf nicht freigegeben, '
                    'bezahlt oder weiterverrechnet werden, bevor das geklärt ist.')
    return None
