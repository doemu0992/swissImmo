"""Forderungsverlust: eine uneinbringliche Debitorenrechnung auf 3805 abschreiben.

Die Buchungslogik stand bis 26.10.2026 nur in der Ansicht
`fw_debitor_abschreiben` (core/views/fw/listen.py). Die Betreibung braucht sie
ein zweites Mal — beim Verlustschein werden die offenen Beträge ihrer
Forderungen automatisch abgeschrieben. Zwei Kopien von Buchungscode driften
auseinander (die MWST-Korrektur unten ist genau so ein Teil, der in einer
Kopie gefehlt hätte). Darum hier einmal, und die Ansicht ruft diesen Dienst.

Gebucht wird Aufwand 3805 an Forderungen 1100 über den offenen Betrag.
Teilzahlungen bleiben verbucht — abgeschrieben wird nur der Rest.
"""
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext


class AbschreibungNichtMoeglich(ValueError):
    """Fachlicher Grund, warum diese Forderung nicht abgeschrieben werden kann."""


def forderung_abschreiben(rechnung, grund='', user=None, datum=None):
    """Schreibt den offenen Betrag von `rechnung` als Debitorenverlust ab.

    Erwartet eine per `select_for_update` gesperrte Zeile innerhalb einer
    Transaktion: Ohne Sperre schreiben zwei parallele Aufrufe denselben Betrag
    zweimal ab (Aufwand und MWST-Korrektur doppelt). Gibt den abgeschriebenen
    Betrag zurück. Wirft `AbschreibungNichtMoeglich` bei einer nicht offenen
    Forderung und `PermissionError` aus der Periodensperre (`buche`).
    """
    from django.db.models import Sum

    from finance.booking import buche, ensure_kontenplan
    from finance.models import Buchung

    if rechnung.status not in ('offen', 'teilbezahlt'):
        raise AbschreibungNichtMoeglich(
            gettext('Nur offene oder teilbezahlte Forderungen können abgeschrieben werden.'))
    offen = rechnung.offener_betrag
    if offen <= 0:
        raise AbschreibungNichtMoeglich(gettext('Kein offener Betrag — nichts abzuschreiben.'))
    datum = datum or timezone.localdate()
    r = rechnung
    mieter_name = r.vertrag.mieter.display_name if r.vertrag_id and r.vertrag.mieter_id else ''
    lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
    # MWST-Korrektur (Audit K1, Entgeltsminderung Art. 41 MWSTG): Steckt im
    # offenen Betrag abgegrenzte MWST, die nie vereinnahmt wird, muss sie
    # zurückgeholt werden — sonst wird Steuer abgeliefert, die es nie gab.
    #
    # Massgebend ist, was auf DIESER Rechnung tatsächlich an MWST gebucht
    # wurde, nicht das heutige Flag am Vertrag: Wird ein Vertrag später
    # optiert, hätte das Flag auf alte steuerfreie Rechnungen eine
    # Phantom-Korrektur gebucht — und umgekehrt bei einer De-Option die
    # echte Korrektur unterschlagen.
    #
    # Storno-Paar beidseitig ausblenden: `ist_storno=False` entfernt die
    # Gegenbuchung, `storniert_am__isnull=True` das stornierte Original.
    mw = Buchung.objects.filter(debitoren_rechnung=r, ist_storno=False, storniert_am__isnull=True)
    haben = mw.filter(haben_konto__nummer='2200').aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
    soll = mw.filter(soll_konto__nummer='2200').aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
    mwst_gebucht = haben - soll
    mwst_anteil = Decimal('0.00')
    if mwst_gebucht > 0 and r.betrag > 0:
        # Anteilig auf den noch offenen Teil — Teilzahlungen haben ihren
        # Steueranteil bereits vereinnahmt.
        mwst_anteil = min((mwst_gebucht * offen / r.betrag).quantize(Decimal('0.01')), mwst_gebucht)
    ensure_kontenplan()
    text = f"Forderungsverlust {r.titel} {mieter_name}".strip()
    if grund:
        text += f" ({grund})"
    buche('3805', '1100', offen - mwst_anteil, text, datum=datum,
          liegenschaft=lg, debitor=r, user=user)
    if mwst_anteil > 0:
        buche('2200', '1100', mwst_anteil,
              f"MWST-Korrektur Forderungsverlust {r.titel} (Entgeltsminderung)",
              datum=datum, liegenschaft=lg, debitor=r, user=user)
    r.status = 'abgeschrieben'
    r.save(update_fields=['status'])
    return offen
