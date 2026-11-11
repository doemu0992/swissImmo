# core/views/fw/kommunikation_aktionen.py
#
# Kommunikation senden, Serienbrief-PDF.
# Aus aktionen.py herausgeloest (reiner Umzug ohne Aenderung am Code).

from datetime import date

from django.utils.translation import gettext

from core.auth import (rolle_erforderlich, SCHREIB_ROLLEN)
from crm.models import Mieter
from rentals.models import Mietvertrag


from core.tenancy import aktuelle_organisation


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kommunikation_senden(request):
    """Verschickt die verfasste Mitteilung per E-Mail an die gewählten Mieter."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kommunikation')
    betreff = (request.POST.get('betreff') or 'Mitteilung').strip()
    text = (request.POST.get('text') or '').strip()
    ids = request.POST.getlist('empfaenger_id')
    if not text or not ids:
        messages.error(request, gettext('Text und mindestens ein Empfänger erforderlich.'))
        return redirect('fw_kommunikation')
    from core.utils.email_service import journal_email
    gesendet = 0
    for mid in ids:
        m = Mieter.objects.filter(id=mid).first()
        if m and m.email:
            if send_ticket_email(m.email, betreff, text):
                gesendet += 1
                journal_email(betreff, text, mieter=m, user=request.user, empfaenger=m.email)
    log_aktion(request, "Rundschreiben per E-Mail", betreff, f"{gesendet} Empfänger")
    messages.success(request, ('✅ ' + gettext('%(gesendet)s E-Mail(s) versendet.') % {'gesendet': gesendet}) if gesendet
                     else gettext('Keine E-Mail versendet (fehlende Adressen).'))
    return redirect('fw_kommunikation')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_serienbrief_pdf(request):
    """Erzeugt ein Sammel-PDF (ein Brief pro Empfänger, Fenstercouvert) für
    einen echten postalischen Rundbrief an alle gewählten Mieter."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from crm.models import Organisation
    from core.auth import log_aktion
    from core.services.serienbrief import generate_serienbrief_pdf
    from core.services.ablage import ablegen
    if request.method != 'POST':
        return redirect('fw_kommunikation')
    betreff = (request.POST.get('betreff') or 'Mitteilung').strip()
    text = (request.POST.get('text') or '').strip()
    ids = request.POST.getlist('empfaenger_id')
    if not text or not ids:
        messages.error(request, gettext('Text und mindestens ein Empfänger erforderlich.'))
        return redirect('fw_kommunikation')

    vw = aktuelle_organisation()
    absender = {
        'firma': vw.firma if vw else 'Meine Verwaltung',
        'strasse': vw.strasse if vw else '',
        'plz': vw.plz if vw else '', 'ort': vw.ort if vw else '',
    }

    # Empfänger auflösen (Adresse + Objekt/Liegenschaft aus aktivem Vertrag).
    # Bei 2-Personen-Verträgen werden BEIDE Namen adressiert; sind beide Personen
    # gewählt, entsteht trotzdem nur EIN Brief (Dedup über Vertrag).
    from django.db.models import Q as _Q
    empfaenger = []
    verarbeitete_vertraege = set()
    for mid in ids:
        m = Mieter.objects.filter(id=mid).first()
        if not m:
            continue
        v = (Mietvertrag.objects.filter(_Q(mieter=m) | _Q(mitmieter=m), status='aktiv')
             .select_related('einheit__liegenschaft', 'mieter', 'mitmieter').first())
        if v:
            if v.id in verarbeitete_vertraege:
                continue  # zweite Person desselben Vertrags → kein Doppelbrief
            verarbeitete_vertraege.add(v.id)
            lg = v.einheit.liegenschaft if v.einheit_id else None
            prim = v.mieter or m
            zweit = (v.mitmieter.display_name if v.mitmieter else (v.mitmieter_name or '')).strip()
            name = prim.display_name + (f" & {zweit}" if zweit else '')
            empfaenger.append({
                '_mieter_id': prim.id, '_vertrag_id': v.id,
                'name': name, 'anrede': prim.anrede or '',
                'strasse': prim.strasse or (lg.strasse if lg else ''),
                'plz': prim.plz or (lg.plz if lg else ''),
                'ort': prim.ort or (lg.ort if lg else ''),
                'objekt': (f"{lg.strasse}, {lg.ort} · {v.einheit.bezeichnung}" if lg else ''),
                'liegenschaft': (f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else ''),
            })
        else:
            empfaenger.append({
                '_mieter_id': m.id, '_vertrag_id': None,
                'name': m.display_name, 'anrede': m.anrede or '',
                'strasse': m.strasse or '', 'plz': m.plz or '', 'ort': m.ort or '',
                'objekt': '', 'liegenschaft': '',
            })
    if not empfaenger:
        messages.error(request, gettext('Keine gültigen Empfänger gefunden.'))
        return redirect('fw_kommunikation')

    logo_path = None
    if vw and getattr(vw, 'logo', None):
        try:
            logo_path = vw.logo.path
        except Exception:
            logo_path = None

    pdf = generate_serienbrief_pdf(absender, betreff, text, empfaenger,
                                   logo_path=logo_path, signatur=(vw,))

    # Auto-Ablage: pro Empfänger eine eigene (einseitige) Brief-Kopie in dessen
    # Akte ablegen — erscheint automatisch im Mieterportal (portal-sichtbar).
    abgelegt = 0
    for e in empfaenger:
        m = Mieter.objects.filter(id=e.get('_mieter_id')).first()
        if not m:
            continue
        v = Mietvertrag.objects.filter(id=e.get('_vertrag_id')).first() if e.get('_vertrag_id') else None
        einzel = generate_serienbrief_pdf(absender, betreff, text, [e],
                                          logo_path=logo_path, signatur=(vw,))
        # Titel mit aufgelösten Platzhaltern ({liegenschaft} etc.) — nicht roh.
        from core.services.serienbrief import _ersetze
        betreff_aufgeloest = _ersetze(betreff, e) or betreff
        # Ablage am Vertrag (erscheint im Portal beider Personen) + am Hauptmieter
        if ablegen(einzel, f"Brief: {betreff_aufgeloest}", kategorie='korrespondenz', vertrag=v, mieter=m,
                   im_portal_sichtbar=True):
            abgelegt += 1

    log_aktion(request, "Serienbrief-PDF erzeugt", betreff, f"{len(empfaenger)} Empfänger · {abgelegt} abgelegt")
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="serienbrief_{date.today().isoformat()}.pdf"'
    return resp
