"""Hauptbuch-Anbindung der STWEG: Vorschreibung, Zahlung, Abschluss der Jahresabrechnung.

KONTEN (Standard-Kontenplan, `finance.booking.STANDARD_KONTEN`)
  1110 Forderungen Stockwerkeigentümer (aktiv)    2035 Akonto-Beiträge Stockwerkeigentümer (passiv)
  3100 Beiträge Stockwerkeigentümer (Ertrag)      1020 Bank       1190 Durchlaufkonto (ungeklärte Zahlungen)

BUCHUNGEN
  Vorschreibung einer Rate (Genehmigung des Budgets)   Soll 1110 / Haben 2035
  Zahlung, direkt erfasst                              Soll 1020 / Haben 1110  (Kosten und Kapital)
                                                       Soll 1020 / Haben 3120  (Zinsanteil, Art. 85 OR: `stweg.zins`)
  Zahlung aus dem Kontoauszug-Import (auf 1190)        Soll 1190 / Haben 1110   ← kein zweites Mal auf der Bank
  Abschluss der Jahresabrechnung, je Einheit:
      Vorschreibungen des Jahres freigeben             Soll 2035 / Haben 3100
      Abgleich (Kostenanteil − Vorschreibungen)        Soll 1110 / Haben 3100  (Nachzahlung)
                                                       Soll 3100 / Haben 1110  (Guthaben)
  Die Beiträge (3100) ergeben so genau die Kostenanteile; die Aufwandskonten tragen die Kosten, das
  Jahresergebnis der Gemeinschaft ist null. Der Saldo auf 1110 je Einheit entspricht dem Kontokorrent.

Der Erneuerungsfonds bleibt, wie er war: Einlage Soll 1110 / Haben 2800 (`stweg.fonds`). Eine Zahlung dafür
wird mit Zweck «fonds» erfasst; sie deckt nie den Kostenanteil der Abrechnung.

ZAHLUNGEN AUS DEM IMPORT. Der Import legt nicht zuordenbare Eingänge auf 1190 (Soll Bank / Haben 1190). Wer
dieselbe Zahlung zusätzlich direkt erfasste (Soll 1020), buchte die Bank doppelt. Deshalb kann eine Zahlung
mit ihrem geparkten Eingang verknüpft werden: gebucht wird dann nur 1190 → 1110.
"""
from django.utils.translation import gettext
from decimal import Decimal

from django.db import transaction

from finance import booking
from finance.booking import buche, storniere_buchung
from stweg.models import StwegAbrechnungPosition, StwegAkonto, StwegVorschreibung

NULL = Decimal('0.00')


class HauptbuchFehler(ValueError):
    pass


def _gesperrt(fehler):
    return HauptbuchFehler(gettext('Die Buchung ist nicht möglich — Periode abgeschlossen? (%(fehler)s)') % {'fehler': fehler})


def vorschreibung_buchen(v, *, datum=None, user=None):
    """Soll 1110 / Haben 2035 für eine Rate. Wirft `HauptbuchFehler` bei gesperrter Periode."""
    lg = v.budget.liegenschaft
    try:
        v.buchung = buche('1110', '2035', v.betrag,
                          f'Akonto {v.budget.jahr} Rate {v.rate_nr}/{v.rate_total}: {v.einheit.bezeichnung}',
                          datum=datum, liegenschaft=lg, user=user)
    except PermissionError as e:
        raise _gesperrt(e)
    v.save(update_fields=['buchung'])
    return v.buchung


@transaction.atomic
def zahlung_buchen(zahlung, *, user=None):
    """Bucht eine erfasste Zahlung: Soll 1020 (oder 1190 bei Zuordnung eines Importeingangs) / Haben 1110.

    Ist `zahlung.zahlungseingang` gesetzt, muss das ein verbuchter, auf 1190 geparkter Eingang desselben
    Betrags sein, der noch keiner STWEG-Zahlung zugeordnet ist."""
    if zahlung.buchung_id:
        raise HauptbuchFehler(gettext('Diese Zahlung ist schon gebucht.'))
    lg = zahlung.einheit.liegenschaft
    soll = '1020'
    ze = zahlung.zahlungseingang
    if ze is not None:
        if ze.status != 'verbucht' or ze.konto_id is None or ze.konto.nummer != '1190':
            raise HauptbuchFehler(gettext('Der Eingang liegt nicht auf dem Durchlaufkonto 1190 (ungeklärte Zahlungen).'))
        if Decimal(ze.betrag) != Decimal(zahlung.betrag):
            raise HauptbuchFehler(gettext('Der Eingang lautet auf CHF %(betrag)s, die Zahlung auf CHF %(betrag2)s — Teilzuordnungen gibt es nicht.') % {'betrag': ze.betrag, 'betrag2': zahlung.betrag})
        if StwegAkonto.objects.filter(zahlungseingang=ze).exclude(pk=zahlung.pk).exists():
            raise HauptbuchFehler(gettext('Dieser Eingang ist schon einer Zahlung zugeordnet.'))
        soll = '1190'
    text = (f'{"Einlage Fonds" if zahlung.zweck == StwegAkonto.FONDS else "Akonto"}-Zahlung: '
            f'{zahlung.einheit.bezeichnung}')
    try:
        # Kosten und Kapital tilgen die Forderung auf 1110; der Zinsanteil ist Ertrag (3120), kein Kapital.
        b = buche(soll, '1110', zahlung.betrag - zahlung.an_zins, text, datum=zahlung.datum, liegenschaft=lg,
                  user=user, zahlung=ze)
        if zahlung.an_zins > 0:
            zahlung.zins_buchung = buche(soll, '3120', zahlung.an_zins, f'Verzugszins: {zahlung.einheit.bezeichnung}',
                                         datum=zahlung.datum, liegenschaft=lg, user=user, zahlung=ze)
    except PermissionError as e:
        raise _gesperrt(e)
    zahlung.buchung = b
    zahlung.save(update_fields=['buchung', 'zins_buchung'])
    if ze is not None:
        # Der Eingang gehört jetzt der Gemeinschaft und taucht nicht mehr als «geparkt» auf.
        ze.konto = None
        ze.liegenschaft = lg
        ze.bemerkung = f'{ze.bemerkung} → STWEG {zahlung.einheit.bezeichnung}'[:255]
        ze.save()
    return b


@transaction.atomic
def zahlung_erfassen(einheit, betrag, datum, *, zweck=StwegAkonto.AKONTO, vorschreibung=None, zahlungseingang=None,
                     bemerkung='', user=None):
    """Erfasst eine Zahlung und bucht sie (alles oder nichts). `vorschreibung`: die bezahlte Rate (Bestimmung des
    Schuldners); sie muss zu derselben Einheit gehören und gilt nur für Akonto-Zahlungen."""
    betrag = Decimal(betrag)
    if betrag <= 0:
        raise HauptbuchFehler('Der Betrag muss grösser 0 sein.')
    if vorschreibung is not None:
        if vorschreibung.einheit_id != einheit.pk:
            raise HauptbuchFehler('Die Rate gehört zu einer anderen Einheit.')
        if zweck != StwegAkonto.AKONTO:
            raise HauptbuchFehler('Eine Rate kann nur mit einer Akonto-Zahlung bezahlt werden.')
    from stweg import zins
    an_kosten, an_zins, _ = zins.zuordnen(einheit, betrag, datum)        # Art. 85 Abs. 1 OR: Kosten, Zinsen, Kapital
    z = StwegAkonto.objects.create(einheit=einheit, betrag=betrag, datum=datum, zweck=zweck, bemerkung=bemerkung[:200],
                                   vorschreibung=vorschreibung, zahlungseingang=zahlungseingang,
                                   an_kosten=an_kosten, an_zins=an_zins)
    zahlung_buchen(z, user=user)
    return z


@transaction.atomic
def zahlung_stornieren(zahlung, *, user=None):
    """Hebt die Buchung einer Zahlung auf (revisionssicher: Gegenbuchung) und gibt einen
    zugeordneten Importeingang wieder auf 1190 frei. Zahlungen ohne Buchung (Altbestand) bleiben unberührt."""
    b = zahlung.buchung
    if b is None or b.storniert_am is not None:
        return None
    try:
        gegen = storniere_buchung(b, user=user)
        if zahlung.zins_buchung_id and zahlung.zins_buchung.storniert_am is None:
            storniere_buchung(zahlung.zins_buchung, user=user)
    except PermissionError as e:
        raise _gesperrt(e)
    ze = zahlung.zahlungseingang
    if ze is not None and ze.konto_id is None:
        ze.konto = booking.konto('1190')
        ze.bemerkung = ze.bemerkung.split(' → STWEG ')[0]
        ze.save()
    return gegen


@transaction.atomic
def abschluss_buchen(abrechnung, *, user=None):
    """Bucht den Abschluss einer Jahresabrechnung (siehe Moduldoku). Je Einheit zwei Buchungen höchstens;
    die Belege hängen an der Position. Nur einmal je Abrechnung."""
    from datetime import date
    if StwegAbrechnungPosition.objects.filter(abrechnung=abrechnung, buchungen__isnull=False).exists():
        raise HauptbuchFehler(gettext('Der Abschluss dieser Abrechnung ist schon gebucht.'))
    lg = abrechnung.liegenschaft
    datum = date(abrechnung.jahr, 12, 31)
    gebucht = []
    try:
        for p in abrechnung.positionen.select_related('einheit'):
            vorgeschrieben = sum(
                (v.betrag for v in StwegVorschreibung.objects.filter(
                    einheit=p.einheit, budget__jahr=abrechnung.jahr, budget__liegenschaft=lg)), NULL)
            text = f'Abrechnung {abrechnung.jahr}: {p.einheit.bezeichnung}'
            belege = [buche('2035', '3100', vorgeschrieben, f'{text} (Akonto freigegeben)', datum=datum,
                            liegenschaft=lg, user=user)]
            abgleich = p.kostenanteil - vorgeschrieben
            if abgleich > 0:
                belege.append(buche('1110', '3100', abgleich, f'{text} (Nachzahlung)', datum=datum,
                                    liegenschaft=lg, user=user))
            elif abgleich < 0:
                belege.append(buche('3100', '1110', -abgleich, f'{text} (Guthaben)', datum=datum,
                                    liegenschaft=lg, user=user))
            belege = [b for b in belege if b is not None]
            if belege:
                p.buchungen.add(*belege)
                gebucht += belege
    except PermissionError as e:
        raise _gesperrt(e)
    return gebucht
