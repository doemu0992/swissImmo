# core/views/fw/debitor_qr.py
#
# QR-Beleg fuer eine Ad-hoc-Debitorenrechnung (Sonnerie, Ersatzschluessel
# und aehnliches). Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Die QR-Rechnung ist im Skill schweizer-fachlogik geschuetzt: An QR-IBAN
# und Referenz darf nichts geraten werden. Der Blockinhalt ist gegen HEAD
# Zeile fuer Zeile geprueft.

from django.shortcuts import get_object_or_404

from core.auth import rolle_erforderlich, TEAM_ROLLEN
from finance.models import DebitorenRechnung


# ============================================================
# QR-BELEG FÜR AD-HOC-DEBITORENRECHNUNG (z.B. Sonnerie, Ersatz)
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_debitor_qr_pdf(request, pk):
    """QR-Einzahlungsschein (A4) für eine beliebige Debitorenrechnung —
    ermöglicht Ad-hoc-Weiterverrechnungen (Schlüssel, Sonnerie, Ersatz …)
    mit QR-Rechnung inkl. QRR-Referenz."""
    from django.http import HttpResponse
    from core.services.debitor_qr import generate_debitor_qr_pdf

    r = get_object_or_404(DebitorenRechnung.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft'), id=pk)
    # Keinen Einzahlungsschein für eine Forderung ausstellen, die nicht mehr offen
    # ist — ein QR-Beleg für eine bezahlte/stornierte/abgeschriebene Rechnung
    # fordert den Mieter zu einer Zahlung auf, die es nicht (mehr) gibt (Live-Test E).
    if r.status in ('storniert', 'abgeschrieben', 'bezahlt') or r.offener_betrag <= 0:
        from django.http import HttpResponse
        return HttpResponse(
            f"Für diese Rechnung («{r.get_status_display()}») kann kein Einzahlungsschein "
            f"erstellt werden — sie ist nicht mehr offen.", status=409)
    pdf = generate_debitor_qr_pdf(r)
    if pdf is None:
        return HttpResponse("Keine IBAN hinterlegt (Liegenschaft oder Verwaltung).", status=400)
    # Auto-Ablage in die Akte (pro Rechnung eigener Titel) -> Portal
    if r.vertrag_id:
        from core.services.ablage import ablegen
        ablegen(pdf, f"Rechnung: {r.titel} (#{r.id})", kategorie='korrespondenz', vertrag=r.vertrag, dedup=True)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Rechnung_{r.id}.pdf"'
    return resp
