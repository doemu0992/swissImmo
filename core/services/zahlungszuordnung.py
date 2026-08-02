"""Eine geparkte Zahlung einer offenen Debitorenrechnung zuordnen.

Die Buchungslogik lag bisher nur in der Einzelzuordnung (fw_zahlung_zuordnen).
Für die Sammelzuordnung braucht es dieselbe Logik ein zweites Mal — und zwei
Kopien von Buchungscode driften garantiert auseinander. Darum hier einmal.

Gebucht wird Parkkonto (1190 ungeklärt / 2030 Mieterguthaben) an 1100
Debitoren; der Zahlungseingang wird mit Vertrag und Rechnung verknüpft, der
OP-Status nachgeführt. Zahlt jemand mehr als offen ist, bleibt der Überschuss
als Mieterguthaben (2030) stehen — er verfällt nicht.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone


class ZuordnungsFehler(Exception):
    """Fachlicher Grund, warum diese Zuordnung nicht zulässig ist."""


def zuordnen(zahlung, rechnung, user=None, heute=None):
    """Bucht `zahlung` auf `rechnung`. Gibt (betrag, rest) zurück.

    Erwartet Objekte, die bereits per select_for_update gesperrt sind, wenn der
    Aufrufer nebenläufige Zugriffe erwartet — die Buchung selbst läuft in einer
    eigenen Transaktion.

    Wirft ZuordnungsFehler bei fachlich unzulässigen Zuordnungen und
    PermissionError aus der Periodensperre (vom Aufrufer zu behandeln).
    """
    from finance.booking import buche
    from finance.models import Zahlungseingang
    from core.services import zahler as _zahler

    heute = heute or timezone.localdate()
    park_nr = zahlung.konto.nummer if zahlung.konto_id else ''
    if park_nr not in ('1190', '2030') or zahlung.status != 'verbucht':
        raise ZuordnungsFehler("Diese Zahlung liegt nicht auf einem Park-/Guthabenkonto.")
    if rechnung.status not in ('offen', 'teilbezahlt') or not rechnung.vertrag_id:
        raise ZuordnungsFehler("Zielrechnung ist nicht offen oder hat keinen Vertrag.")
    # Ein Mieterguthaben (2030) gehört einem bestimmten Mieter — es darf nicht die
    # Forderung eines anderen tilgen. Nur wirklich ungeklärtes Geld (1190, ohne
    # bekannten Zahler) ist frei zuordenbar.
    if zahlung.vertrag_id and zahlung.vertrag_id != rechnung.vertrag_id:
        raise ZuordnungsFehler("Dieses Guthaben gehört einem anderen Mieter und kann "
                               "diese Forderung nicht tilgen.")

    offen = rechnung.offener_betrag
    betrag = min(zahlung.betrag, offen)
    rest = zahlung.betrag - betrag
    vertrag = rechnung.vertrag
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None

    with transaction.atomic():
        # zahlung= mitgeben, sonst hängt die Buchung an keinem Beleg und ein
        # späteres Storno der Zahlung würde sie stehen lassen.
        buche(park_nr, "1100", betrag,
              f"Zuordnung {('Durchlaufkonto' if park_nr == '1190' else 'Guthaben')} → "
              f"{vertrag.mieter} - {rechnung.titel}",
              datum=heute, liegenschaft=lg, zahlung=zahlung, user=user)
        # Geparkten Eingang in eine echte Mieterzahlung umwandeln
        zahlung.vertrag = vertrag
        zahlung.debitoren_rechnung = rechnung
        zahlung.konto = None
        zahlung.betrag = betrag
        zahlung.liegenschaft = lg or zahlung.liegenschaft
        zahlung.bemerkung = (f"{zahlung.bemerkung} → zugeordnet {rechnung.titel}")[:255]
        zahlung.save()
        if rest > 0:
            # Der Zahler ist jetzt bekannt — der Überschuss ist ein Mieterguthaben
            # (2030) und kein ungeklärter Durchlaufposten mehr. Lag er vorher auf
            # 1190, wird er umgebucht, sonst bliebe er dauerhaft «ungeklärt».
            #
            # Reihenfolge ist hier kein Stil, sondern Pflicht: erst den
            # Zahlungseingang anlegen, DANN mit `zahlung=z_rest` buchen. Das
            # Storno hebt nur Buchungen auf, die an einem Zahlungseingang hängen
            # (`Buchung.objects.filter(zahlungseingang=…)`). Ohne diese
            # Verknüpfung blieb das Guthaben nach dem Storno stehen — der Mieter
            # behielt ein Guthaben aus einer Zahlung, die es buchhalterisch nicht
            # mehr gibt, und 1190/2030 waren dauerhaft falsch. Der Import-Pfad
            # für Überzahlungen macht es seit jeher so.
            z_rest = Zahlungseingang.objects.create(
                vertrag=vertrag, betrag=rest, datum_eingang=zahlung.datum_eingang,
                buchungs_monat=zahlung.buchungs_monat,
                bemerkung=f"Rest-Guthaben aus Zuordnung ({rechnung.titel})"[:255],
                bank_referenz=(f"{zahlung.bank_referenz}:rest"[:140] if zahlung.bank_referenz else ''),
                konto=_park_konto('2030'), liegenschaft=lg or zahlung.liegenschaft,
                erstellt_von=user, status='verbucht')
            if park_nr != '2030':
                buche('1190', '2030', rest,
                      f"Rest-Guthaben {vertrag.mieter} aus Zuordnung {rechnung.titel}",
                      datum=heute, liegenschaft=lg, zahlung=z_rest, user=user)
        rechnung.status = 'bezahlt' if rechnung.offener_betrag <= 0 else 'teilbezahlt'
        rechnung.save()

        # Absender merken: zahlt derselbe jeden Monat ohne QR-Referenz, musste
        # die Zahlung bisher jeden Monat neu von Hand zugeordnet werden.
        bew = zahlung.bankbewegungen.first()
        gelernt = ''
        if bew is not None:
            gelernt, _rest_txt, _geraten = _zahler.aus_bewegung(bew.gegenpartei, bew.text)
            if gelernt:
                _zahler.lerne(gelernt, vertrag)

    return betrag, rest, gelernt


def _park_konto(nummer):
    from finance.models import Buchungskonto
    konto, _ = Buchungskonto.objects.get_or_create(
        nummer=nummer,
        defaults={'bezeichnung': 'Guthaben Mieter' if nummer == '2030'
                  else 'Durchlaufkonto (ungeklärte Zahlungen)', 'typ': 'bilanz'})
    return konto


def offene_rechnungen(vertrag):
    """Offene Rechnungen eines Vertrags, älteste zuerst.

    Reihenfolge ist hier kein Detail: Bei mehreren offenen Monatsmieten wird die
    älteste Forderung zuerst getilgt — sonst mahnt man einen Mieter für einen
    Monat, den er längst bezahlt hat.
    """
    from finance.models import DebitorenRechnung
    return list(DebitorenRechnung.objects
                .filter(vertrag=vertrag, status__in=['offen', 'teilbezahlt'])
                .order_by('faellig_am', 'datum', 'id'))


def sammel_zuordnen(zahlungen, vertrag, user=None):
    """Ordnet mehrere geparkte Zahlungen einem Vertrag zu — älteste Forderung
    zuerst. Gibt (anzahl, summe, rest_guthaben, fehler) zurück.

    Jede Zahlung wird einzeln gebucht: Bricht eine an der Periodensperre ab,
    bleiben die übrigen gültig, statt dass der ganze Lauf verloren geht.
    """
    anzahl = 0
    summe = Decimal('0.00')
    rest_total = Decimal('0.00')
    fehler = []
    gelernt = ''
    for zahlung in sorted(zahlungen, key=lambda z: (z.datum_eingang, z.id)):
        offene = [r for r in offene_rechnungen(vertrag) if r.offener_betrag > 0]
        if not offene:
            fehler.append(f"CHF {zahlung.betrag}: keine offene Rechnung mehr — "
                          f"Zahlung bleibt ungeklärt")
            continue
        try:
            betrag, rest, name = zuordnen(zahlung, offene[0], user=user)
        except ZuordnungsFehler as e:
            fehler.append(f"CHF {zahlung.betrag}: {e}")
            continue
        except PermissionError as e:
            fehler.append(f"CHF {zahlung.betrag}: {e}")
            continue
        anzahl += 1
        summe += betrag
        rest_total += rest
        gelernt = gelernt or name
    return anzahl, summe, rest_total, fehler, gelernt
