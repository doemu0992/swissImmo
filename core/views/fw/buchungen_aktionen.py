# core/views/fw/buchungen_aktionen.py
#
# Buchung erfassen und stornieren.
# Aus aktionen.py herausgeloest (reiner Umzug ohne Aenderung am Code).

from datetime import date
from decimal import Decimal

from django.utils.translation import gettext
from django.shortcuts import get_object_or_404
from django.utils import timezone

from core.auth import (rolle_erforderlich)
from core.auth import FINANZ_SCHREIB_ROLLEN, FINANZ_VERWALTUNGS_ROLLEN
from portfolio.models import Liegenschaft


from ._basis import (_num)


@rolle_erforderlich(*FINANZ_SCHREIB_ROLLEN)
def fw_buchung_neu(request):
    """Manuelle Buchung erfassen (Soll an Haben)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_buchhaltung')

    def _konto_aus_post(feld_nummer, feld_id):
        """Akzeptiert die KONTONUMMER (Tastatureingabe) oder die ID (Alt-Formulare).
        Die Nummer ist der Weg, den ein Buchhalter erwartet — vorher gab es nur
        ein <select> über den ganzen Kontenplan (Audit)."""
        nr = (request.POST.get(feld_nummer) or '').strip()
        if nr:
            # Die datalist zeigt «4000 Unterhalt» — nur der führende Zahlenteil zählt.
            nr = nr.split()[0].strip()
            k = Buchungskonto.objects.filter(nummer=nr).first()
            if k:
                return k
        return Buchungskonto.objects.filter(id=request.POST.get(feld_id) or None).first()

    # Serienerfassung: zurück zur Maske statt auf die Übersicht, damit ein Stapel
    # ohne Neuaufklappen und ohne erneutes Tippen von Datum/Konten läuft.
    weiter = request.POST.get('weiter') == '1'

    def _zurueck(fehler=False):
        if not weiter:
            return redirect('fw_buchhaltung')
        # Werte für die nächste Zeile in der Session merken.
        request.session['bu_serie'] = True
        return redirect('/neu/buchhaltung/?tab=journal#buchform')

    soll = _konto_aus_post('soll_konto', 'soll_konto_id')
    haben = _konto_aus_post('haben_konto', 'haben_konto_id')
    try:
        betrag = Decimal((_num(request.POST.get('betrag')) or '0'))
    except Exception:
        betrag = Decimal('0')
    text = (request.POST.get('beleg_text') or '').strip()
    if not soll or not haben or betrag <= 0 or not text:
        messages.error(request, gettext('Soll-, Haben-Konto (gültige Nummer), Betrag (> 0) und Belegtext sind erforderlich.'))
        return _zurueck(fehler=True)
    if soll.id == haben.id:
        messages.error(request, gettext('Soll- und Haben-Konto müssen unterschiedlich sein.'))
        return _zurueck(fehler=True)
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first() if request.POST.get('liegenschaft_id') else None
    bu_datum = (date.fromisoformat(request.POST['datum']) if request.POST.get('datum')
                else timezone.localdate())
    try:
        Buchung.objects.create(
            datum=bu_datum, beleg_text=text, liegenschaft=lg,
            soll_konto=soll, haben_konto=haben,
            betrag=betrag, erstellt_von=request.user)
    except PermissionError as exc:          # Periodensperre
        messages.error(request, f"❌ {exc}")
        return _zurueck(fehler=True)
    log_aktion(request, "Manuelle Buchung", text, f"{soll.nummer}/{haben.nummer} CHF {betrag}")
    messages.success(request, '✅ ' + gettext('Buchung erfasst: %(nummer)s an %(nummer2)s · CHF %(betrag)s.') % {'nummer': soll.nummer, 'nummer2': haben.nummer, 'betrag': betrag})
    # Datum, Konten und Liegenschaft für den nächsten Beleg vorhalten.
    request.session['bu_letzt'] = {
        'datum': bu_datum.isoformat(), 'soll': soll.nummer, 'haben': haben.nummer,
        'lg': lg.id if lg else None,
    }
    return _zurueck()


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_buchung_stornieren(request, pk):
    """Storniert eine Journalbuchung durch eine revisionssichere Gegenbuchung.
    Die Originalbuchung bleibt erhalten (append-only, OR 958f). Nur Verwaltung —
    ein Storno ist ein buchhalterischer Korrektureingriff (nicht Sachbearbeitung)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchung
    from finance.booking import storniere_buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_buchhaltung')
    b = get_object_or_404(Buchung, id=pk)
    # Eine EINZELNE Abschlussbuchung darf nicht im Journal storniert werden — das
    # liesse das Geschäftsjahr halb geschlossen zurück (ein Teil der Erfolgskonten
    # gegen 2970 saldiert, der Rest offen) und verschöbe Vorjahresaufwand ins
    # laufende Jahr. Ein Abschluss wird atomar über «Abschluss zurücknehmen»
    # gelöst (Audit-Befund H6).
    from core.services.jahresabschluss import BELEG_PREFIX as _ABSCHLUSS_PREFIX
    if b.beleg_text.startswith(_ABSCHLUSS_PREFIX):
        messages.error(request, gettext('Abschlussbuchungen lassen sich nicht einzeln stornieren. Bitte den Jahresabschluss gesamthaft über «Abschluss zurücknehmen» aufheben.'))
        return redirect('fw_buchhaltung')
    try:
        gegen = storniere_buchung(b, user=request.user)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('fw_buchhaltung')
    except PermissionError as e:
        messages.error(request, str(e))
        return redirect('fw_buchhaltung')
    log_aktion(request, "Buchung storniert", b.beleg_text,
               f"Beleg #{b.beleg_nr} → Storno #{gegen.beleg_nr} · CHF {b.betrag}")
    messages.success(request, '✅ ' + gettext('Beleg #%(beleg_nr)s storniert (Gegenbuchung #%(beleg_nr2)s).') % {'beleg_nr': b.beleg_nr, 'beleg_nr2': gegen.beleg_nr})
    return redirect('fw_buchhaltung')
