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
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext

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


# ---------------------------------------------------------------------------
# VIER-AUGEN-PRINZIP FÜR ZAHLUNGEN (Etappe 2, SICH-12)
# ---------------------------------------------------------------------------
#
# Eine Kreditorenrechnung ab dem Freigabelimit der Organisation
# (`Organisation.freigabelimit_kreditoren`, Vorgabe CHF 5'000) wird erst bezahlt
# oder in eine Zahlungsdatei genommen, wenn eine ZWEITE Person die Zahlung
# freigegeben hat. Wer sie vorgelegt hat, darf sie nicht selbst freigeben.
#
# MASSGEBEND IST DER RECHNUNGSBETRAG, nicht der einzelne Zahlungsbetrag: Sonst
# liesse sich eine Rechnung über CHF 20'000 in Teilzahlungen zu CHF 4'999
# zerlegen und am Limit vorbeiführen.
#
# DIE FREIGABE GILT FÜR BETRAG UND IBAN, DIE SIE GESEHEN HAT. Ändert jemand nach
# der Freigabe die IBAN (der klassische Betrug) oder den Betrag, ist sie ungültig
# und die Zahlung wieder gesperrt.
#
# Eine Stelle entscheidet (`zahlung_sperre`); Bezahlen, Zahllauf (Datei und
# Sammelbestätigung) fragen alle hier.
class FreigabeFehler(Exception):
    """Die Freigabe ist nicht möglich (Begründung als Text)."""


def _iban(wert):
    return (wert or '').replace(' ', '').upper()


def limit_der(organisation):
    """Das Freigabelimit der Organisation, oder `None` (Vier-Augen-Prinzip aus)."""
    if organisation is None:
        return None
    return getattr(organisation, 'freigabelimit_kreditoren', None)


def braucht_zahlungsfreigabe(kreditor, organisation=None):
    """Verlangt diese Rechnung die Freigabe einer zweiten Person?"""
    if organisation is None:
        from core.tenancy import aktuelle_organisation
        organisation = aktuelle_organisation()
    limit = limit_der(organisation)
    if limit is None:
        return False
    return (kreditor.betrag or Decimal('0.00')) >= limit


def freigabe_gueltig(kreditor):
    """Liegt eine Freigabe vor, die zu Betrag und IBAN der Rechnung passt?"""
    return bool(
        kreditor.zahlung_freigegeben_von_id
        and kreditor.zahlung_freigabe_betrag is not None
        and kreditor.zahlung_freigabe_betrag == (kreditor.betrag or Decimal('0.00'))
        and kreditor.zahlung_freigabe_iban == _iban(kreditor.iban))


def zahlung_sperre(kreditor, organisation=None):
    """Begründung, weshalb die Zahlung (noch) nicht ausgelöst werden darf — oder None."""
    if kreditor is None or not kreditor.pk:
        return None
    if not braucht_zahlungsfreigabe(kreditor, organisation):
        return None
    if freigabe_gueltig(kreditor):
        return None
    if kreditor.zahlung_freigegeben_von_id:
        return gettext('Betrag oder IBAN wurden nach der Freigabe geändert — die Zahlung '
                       'braucht eine neue Freigabe durch eine zweite Person.')
    return gettext('Diese Zahlung braucht die Freigabe einer zweiten Person '
                   '(Rechnungsbetrag ab dem Freigabelimit).')


def vorlegen(kreditor, user):
    """Die Zahlung zur Freigabe vorlegen. Gibt True zurück, wenn neu vorgelegt wurde.

    Wer eine bereits vorgelegte Zahlung vorlegt, ändert nichts (der erste Vorleger
    bleibt, sonst könnte der Freigeber sich durch erneutes Vorlegen «freispielen»)."""
    if freigabe_gueltig(kreditor):
        return False
    if kreditor.zahlung_beantragt_von_id and not kreditor.zahlung_freigegeben_von_id:
        return False
    kreditor.zahlung_beantragt_von = user
    kreditor.zahlung_beantragt_am = timezone.now()
    kreditor.zahlung_freigegeben_von = None
    kreditor.zahlung_freigegeben_am = None
    kreditor.zahlung_freigabe_betrag = None
    kreditor.zahlung_freigabe_iban = ''
    kreditor.save(update_fields=[
        'zahlung_beantragt_von', 'zahlung_beantragt_am', 'zahlung_freigegeben_von',
        'zahlung_freigegeben_am', 'zahlung_freigabe_betrag', 'zahlung_freigabe_iban'])
    return True


def freigeben(kreditor, user):
    """Die vorgelegte Zahlung freigeben — nur eine andere Person als der Vorleger."""
    if not braucht_zahlungsfreigabe(kreditor):
        raise FreigabeFehler(gettext('Diese Rechnung liegt unter dem Freigabelimit — keine Freigabe nötig.'))
    if kreditor.status not in ('freigegeben', 'in_zahlung', 'teilbezahlt'):
        raise FreigabeFehler(gettext('Nur eine freigegebene, noch offene Rechnung lässt sich zur Zahlung freigeben.'))
    if not kreditor.zahlung_beantragt_von_id:
        raise FreigabeFehler(gettext('Die Zahlung wurde noch nicht vorgelegt.'))
    if kreditor.zahlung_beantragt_von_id == user.pk:
        raise FreigabeFehler(gettext('Wer die Zahlung vorgelegt hat, darf sie nicht selbst freigeben '
                                     '(Vier-Augen-Prinzip).'))
    if freigabe_gueltig(kreditor):
        raise FreigabeFehler(gettext('Die Zahlung ist bereits freigegeben.'))
    kreditor.zahlung_freigegeben_von = user
    kreditor.zahlung_freigegeben_am = timezone.now()
    kreditor.zahlung_freigabe_betrag = kreditor.betrag or Decimal('0.00')
    kreditor.zahlung_freigabe_iban = _iban(kreditor.iban)
    kreditor.save(update_fields=[
        'zahlung_freigegeben_von', 'zahlung_freigegeben_am', 'zahlung_freigabe_betrag',
        'zahlung_freigabe_iban'])


def zuruecknehmen(kreditor):
    """Vorlage und Freigabe verwerfen (die Zahlung ist wieder ungeprüft)."""
    for feld in ('zahlung_beantragt_von', 'zahlung_beantragt_am', 'zahlung_freigegeben_von',
                 'zahlung_freigegeben_am', 'zahlung_freigabe_betrag'):
        setattr(kreditor, feld, None)
    kreditor.zahlung_freigabe_iban = ''
    kreditor.save(update_fields=[
        'zahlung_beantragt_von', 'zahlung_beantragt_am', 'zahlung_freigegeben_von',
        'zahlung_freigegeben_am', 'zahlung_freigabe_betrag', 'zahlung_freigabe_iban'])
