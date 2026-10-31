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


def braucht_zahlungsfreigabe(kreditor, organisation=None, gruppensumme=None):
    """Verlangt diese Rechnung die Freigabe einer zweiten Person?

    Ja, wenn der Rechnungsbetrag die Limite erreicht, oder wenn die Rechnungen desselben
    Kreditors in einem Zahllauf zusammen sie erreichen (Summenregel, Etappe 4). `gruppensumme`
    ist die Summe des laufenden Zahllaufs; die Summe eines früheren Laufs, der die Rechnung
    deshalb vorgelegt hat, steht an der Rechnung (`zahlung_gruppensumme`) und gilt weiter,
    solange die Limite sie erreicht (hebt der Inhaber die Limite an, fällt sie von selbst)."""
    if organisation is None:
        from core.tenancy import aktuelle_organisation
        organisation = aktuelle_organisation()
    limit = limit_der(organisation)
    if limit is None:
        return False
    massgebend = max(kreditor.betrag or Decimal('0.00'), gruppensumme or Decimal('0.00'),
                     getattr(kreditor, 'zahlung_gruppensumme', None) or Decimal('0.00'))
    return massgebend >= limit


def freigabe_gueltig(kreditor):
    """Liegt eine Freigabe vor, die zu Betrag und IBAN der Rechnung passt?"""
    return bool(
        kreditor.zahlung_freigegeben_von_id
        and kreditor.zahlung_freigabe_betrag is not None
        and kreditor.zahlung_freigabe_betrag == (kreditor.betrag or Decimal('0.00'))
        and kreditor.zahlung_freigabe_iban == _iban(kreditor.iban))


def zahlung_sperre(kreditor, organisation=None, gruppensumme=None):
    """Begründung, weshalb die Zahlung (noch) nicht ausgelöst werden darf — oder None."""
    if kreditor is None or not kreditor.pk:
        return None
    if not braucht_zahlungsfreigabe(kreditor, organisation, gruppensumme):
        return None
    if freigabe_gueltig(kreditor):
        return None
    if kreditor.zahlung_freigegeben_von_id:
        return gettext('Betrag oder IBAN wurden nach der Freigabe geändert — die Zahlung '
                       'braucht eine neue Freigabe durch eine zweite Person.')
    if (kreditor.betrag or Decimal('0.00')) < (limit_der(organisation or _org()) or Decimal('0.00')):
        return gettext('Diese Zahlung braucht die Freigabe einer zweiten Person '
                       '(zusammen mit den übrigen Rechnungen desselben Kreditors im Zahllauf '
                       'erreicht sie das Freigabelimit).')
    return gettext('Diese Zahlung braucht die Freigabe einer zweiten Person '
                   '(Rechnungsbetrag ab dem Freigabelimit).')


def _org():
    from core.tenancy import aktuelle_organisation
    return aktuelle_organisation()


def vorlegen(kreditor, user, gruppensumme=None):
    """Die Zahlung zur Freigabe vorlegen. Gibt True zurück, wenn neu vorgelegt wurde.

    Wer eine bereits vorgelegte Zahlung vorlegt, ändert nichts (der erste Vorleger
    bleibt, sonst könnte der Freigeber sich durch erneutes Vorlegen «freispielen»).
    `gruppensumme`: die Summe des Zahllaufs, falls die Summenregel die Vorlage auslöst."""
    if freigabe_gueltig(kreditor):
        return False
    if gruppensumme is not None and (kreditor.zahlung_gruppensumme or Decimal('0.00')) < gruppensumme:
        kreditor.zahlung_gruppensumme = gruppensumme
        kreditor.save(update_fields=['zahlung_gruppensumme'])
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
                 'zahlung_freigegeben_am', 'zahlung_freigabe_betrag', 'zahlung_gruppensumme'):
        setattr(kreditor, feld, None)
    kreditor.zahlung_freigabe_iban = ''
    kreditor.save(update_fields=[
        'zahlung_beantragt_von', 'zahlung_beantragt_am', 'zahlung_freigegeben_von',
        'zahlung_freigegeben_am', 'zahlung_freigabe_betrag', 'zahlung_freigabe_iban',
        'zahlung_gruppensumme'])


# ---------------------------------------------------------------------------
# SUMMENREGEL JE KREDITOR UND ZAHLLAUF (Etappe 4)
# ---------------------------------------------------------------------------
#
# Fünf Rechnungen à CHF 2'000 desselben Lieferanten in einem Zahllauf sind CHF 10'000 an
# eine IBAN. Jede Einzelrechnung liegt unter der Limite; zusammen erreichen sie sie. Dann
# braucht jede dieser Rechnungen die Freigabe einer zweiten Person (derselbe Weg wie sonst:
# vorlegen, freigeben, Bindung an Betrag und IBAN).
#
# «Derselbe Kreditor» heisst: derselbe Lieferantenname (normalisiert, wie das
# Lieferanten-Gedächtnis ihn vergleicht: «EWZ AG» = «ewz») ODER dieselbe IBAN. Ein Name in
# zwei Schreibweisen auf dieselbe IBAN und eine IBAN unter zwei Namen werden damit nicht
# zur Umgehung. Die Gruppen sind verkettet (A und B teilen den Namen, B und C die IBAN
# ⇒ eine Gruppe).
def summenregel_gruppen(rechnungen, organisation):
    """Gruppen von Rechnungen desselben Kreditors, die zusammen die Limite erreichen.

    Gibt eine Liste von Wörterbüchern zurück: `lieferant`, `rechnungen` (alle der Gruppe),
    `summe`, `limit`. Nur Gruppen ab zwei Rechnungen, deren Summe die Limite erreicht UND in
    der mindestens eine Rechnung einzeln darunter liegt (sonst wirkt die Einzelregel schon)."""
    from finance.lieferanten import lieferant_key
    limit = limit_der(organisation)
    rechnungen = list(rechnungen)
    if limit is None or len(rechnungen) < 2:
        return []
    eltern = list(range(len(rechnungen)))

    def wurzel(i):
        while eltern[i] != i:
            eltern[i] = eltern[eltern[i]]
            i = eltern[i]
        return i

    gesehen = {}
    for i, r in enumerate(rechnungen):
        schluessel = []
        name = lieferant_key(r.lieferant)
        if name:
            schluessel.append(('n', name))
        iban = _iban(r.iban)
        if iban:
            schluessel.append(('i', iban))
        for s in schluessel:
            if s in gesehen:
                eltern[wurzel(i)] = wurzel(gesehen[s])
            else:
                gesehen[s] = i
    gruppen = {}
    for i, r in enumerate(rechnungen):
        gruppen.setdefault(wurzel(i), []).append(r)
    ergebnis = []
    for mitglieder in gruppen.values():
        if len(mitglieder) < 2:
            continue
        summe = sum((m.betrag or Decimal('0.00') for m in mitglieder), Decimal('0.00'))
        if summe >= limit and any((m.betrag or Decimal('0.00')) < limit for m in mitglieder):
            ergebnis.append({'lieferant': mitglieder[0].lieferant or '', 'rechnungen': mitglieder,
                             'summe': summe, 'limit': limit})
    return ergebnis


def gruppensumme_je_rechnung(gruppen):
    """{Rechnungs-Id: Summe der Gruppe} für `braucht_zahlungsfreigabe(..., gruppensumme=)`."""
    return {r.pk: g['summe'] for g in gruppen for r in g['rechnungen']}


# ---------------------------------------------------------------------------
# VIER-AUGEN-PRINZIP FÜR AUSZAHLUNGEN OHNE RECHNUNG (Etappe 4)
# ---------------------------------------------------------------------------
#
# Eigentümerauszahlung, Rückerstattung von Mieterguthaben, Rückzahlung einer Kaution (auch aus der
# Schlussabrechnung): Buchungen ohne Rechnung, an der die Freigabe hängen könnte. Der Antrag ist eine
# eigene Zeile (`AuszahlungsFreigabe`), ein offener je Auszahlung (Art und Gegenstand).
#
# Ablauf, derselbe wie bei Kreditoren:
#   1. Wer auszahlen will, löst die Auszahlung aus wie bisher. Ab der Limite wird NICHT gebucht;
#      die Auszahlung ist vorgelegt (`auszahlung_vorlegen`).
#   2. Eine zweite Person (Inhaber/Verwalter, nie der Vorleger) gibt sie frei (`auszahlung_freigeben`).
#      Sie bestätigt Betrag und IBAN, die sie auf dem Bildschirm sah; stimmen sie nicht mehr, ist
#      die Freigabe nicht gültig.
#   3. Die Auszahlung wird erneut ausgelöst. `auszahlung_pruefen` verbraucht die Freigabe in
#      DERSELBEN Transaktion wie die Buchung: eine Freigabe, eine Auszahlung.
#
# DIE PRÜFUNG STEHT IM DIENST, nicht in der Ansicht: Wer `buche_auszahlung` oder
# `zurueckueberweisen` aus einem Command aufruft, trifft dieselbe Sperre. Massgebend ist die
# Organisation des Gegenstands, nie die des Aufrufers.
class AuszahlungGesperrt(FreigabeFehler):
    """Die Auszahlung braucht (noch) die Freigabe einer zweiten Person.

    Trägt, was zum Vorlegen nötig ist. Die Transaktion der Auszahlung wird mit dieser Ausnahme
    zurückgerollt; vorgelegt wird erst danach (`auszahlung_vorlegen`), ausserhalb."""

    def __init__(self, text, *, art, bezug_id, bezug_text, betrag, iban, organisation):
        super().__init__(text)
        self.art, self.bezug_id, self.bezug_text = art, bezug_id, bezug_text
        self.betrag, self.iban, self.organisation = betrag, _iban(iban), organisation


def auszahlung_braucht_freigabe(betrag, organisation):
    """Erreicht dieser Auszahlungsbetrag die Freigabelimite der Organisation?"""
    limit = limit_der(organisation)
    return limit is not None and Decimal(betrag) >= limit


def _antrag_gueltig(antrag, betrag, iban):
    return bool(antrag.freigegeben_von_id and antrag.freigabe_betrag is not None
                and antrag.freigabe_betrag == Decimal(betrag) and antrag.freigabe_iban == _iban(iban))


def auszahlung_pruefen(art, bezug_id, betrag, iban, *, organisation, bezug_text=''):
    """Prüft die Freigabe und VERBRAUCHT sie. Innerhalb der Transaktion der Auszahlung aufrufen,
    unmittelbar vor der Buchung. Gibt den verbrauchten Antrag zurück (oder `None` unter der Limite),
    wirft `AuszahlungGesperrt`."""
    from finance.models import AuszahlungsFreigabe
    betrag = Decimal(betrag)
    if not auszahlung_braucht_freigabe(betrag, organisation):
        return None
    antrag = (AuszahlungsFreigabe.objects.select_for_update()
              .filter(art=art, bezug_id=bezug_id, verbraucht_am__isnull=True).first())
    if antrag is not None and _antrag_gueltig(antrag, betrag, iban):
        antrag.verbraucht_am = timezone.now()
        antrag.save(update_fields=['verbraucht_am'])
        return antrag
    if antrag is not None and antrag.freigegeben_von_id:
        text = gettext('Betrag oder IBAN wurden nach der Freigabe geändert — die Auszahlung '
                       'braucht eine neue Freigabe durch eine zweite Person.')
    else:
        text = gettext('Diese Auszahlung braucht die Freigabe einer zweiten Person '
                       '(Betrag ab dem Freigabelimit von CHF %(limit)s).') % {'limit': limit_der(organisation)}
    raise AuszahlungGesperrt(text, art=art, bezug_id=bezug_id, bezug_text=bezug_text, betrag=betrag,
                             iban=iban, organisation=organisation)


def auszahlung_vorlegen(gesperrt, user):
    """Legt die gesperrte Auszahlung zur Freigabe vor. Gibt (Antrag, neu_vorgelegt) zurück.

    Der erste Vorleger bleibt (wie bei `vorlegen`): Wer erneut auslöst, ändert nur Betrag und IBAN
    des Antrags, nie den Vorleger. Hat sich nach einer Freigabe etwas geändert, beginnt der Antrag
    neu, mit dem jetzigen Auslöser als Vorleger. Läuft unter einer Zeilensperre; zwei gleichzeitige
    Vorlagen ergeben einen Antrag."""
    from django.db import IntegrityError, transaction

    from finance.models import AuszahlungsFreigabe
    g = gesperrt
    with transaction.atomic():
        suche = dict(art=g.art, bezug_id=g.bezug_id, verbraucht_am__isnull=True)
        antrag = AuszahlungsFreigabe.objects.select_for_update().filter(**suche).first()
        if antrag is None:
            try:
                with transaction.atomic():
                    return AuszahlungsFreigabe.objects.create(
                        organisation=g.organisation, art=g.art, bezug_id=g.bezug_id,
                        bezug_text=(g.bezug_text or '')[:200], betrag=g.betrag, iban=g.iban,
                        beantragt_von=user), True
            except IntegrityError:                      # ein anderer war schneller
                antrag = AuszahlungsFreigabe.objects.select_for_update().get(**suche)
        neu = False
        if antrag.freigegeben_von_id and not _antrag_gueltig(antrag, g.betrag, g.iban):
            antrag.beantragt_von, antrag.beantragt_am = user, timezone.now()
            antrag.freigegeben_von = antrag.freigegeben_am = antrag.freigabe_betrag = None
            antrag.freigabe_iban = ''
            neu = True
        antrag.betrag, antrag.iban, antrag.bezug_text = g.betrag, g.iban, (g.bezug_text or '')[:200]
        antrag.save()
        return antrag, neu


def auszahlung_freigeben(antrag, user, *, gesehen_betrag, gesehen_iban):
    """Gibt einen vorgelegten Antrag frei — nur eine andere Person als der Vorleger, und nur für
    Betrag und IBAN, die sie gesehen hat. Der Aufrufer sperrt die Zeile (`select_for_update`)."""
    org = antrag.organisation
    if antrag.verbraucht_am:
        raise FreigabeFehler(gettext('Diese Auszahlung wurde bereits ausgeführt.'))
    if not auszahlung_braucht_freigabe(antrag.betrag, org):
        raise FreigabeFehler(gettext('Dieser Betrag liegt unter dem Freigabelimit — keine Freigabe nötig.'))
    if not antrag.beantragt_von_id:
        raise FreigabeFehler(gettext('Die Auszahlung wurde noch nicht vorgelegt.'))
    if antrag.beantragt_von_id == user.pk:
        raise FreigabeFehler(gettext('Wer die Auszahlung vorgelegt hat, darf sie nicht selbst freigeben '
                                     '(Vier-Augen-Prinzip).'))
    if _antrag_gueltig(antrag, antrag.betrag, antrag.iban):
        raise FreigabeFehler(gettext('Die Auszahlung ist bereits freigegeben.'))
    try:
        gesehen = Decimal(str(gesehen_betrag))
    except Exception:                                     # noqa: BLE001 — jede unlesbare Eingabe heisst: nicht gesehen
        gesehen = None
    if gesehen != antrag.betrag or _iban(gesehen_iban) != _iban(antrag.iban):
        raise FreigabeFehler(gettext('Betrag oder IBAN haben sich seit dem Öffnen der Seite geändert. '
                                     'Bitte die Seite neu laden und die Angaben erneut prüfen.'))
    antrag.freigegeben_von = user
    antrag.freigegeben_am = timezone.now()
    antrag.freigabe_betrag = antrag.betrag
    antrag.freigabe_iban = _iban(antrag.iban)
    antrag.save(update_fields=['freigegeben_von', 'freigegeben_am', 'freigabe_betrag', 'freigabe_iban'])
