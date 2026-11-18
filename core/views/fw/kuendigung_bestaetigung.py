# core/views/fw/kuendigung_bestaetigung.py
#
# Kuendigung zuruecknehmen, bestaetigen, amtliches Formular.
# Aus kuendigung.py herausgeloest (reiner Umzug ohne Aenderung am Code).


from django.utils.translation import gettext
from django.shortcuts import get_object_or_404, render

from core.auth import (rolle_erforderlich, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)

from ._basis import _global_filter
from core.services.dokumentsprache import auf_deutsch
from core.services.unterschrift import UNTERSCHRIFT_HINWEIS_KUENDIGUNG
from .kuendigung_erfassen import _auszugscheckliste_anlegen


# Siehe fw_kuendigung_erfassen: Kündigen ist Inhaber und Verwaltern vorbehalten.
@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_kuendigung_zuruecknehmen(request, pk):
    """Nimmt eine Kündigung zurück und reaktiviert den Vertrag."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Kuendigung
    from core.auth import log_aktion
    k = get_object_or_404(Kuendigung, id=pk)
    v = k.vertrag
    if request.method == 'POST':
        k.status = 'zurueckgezogen'
        k.save(update_fields=['status'])
        # Vertrag reaktivieren, wenn keine andere aktive Kündigung besteht
        andere = v.kuendigungen.exclude(id=k.id).exclude(status='zurueckgezogen').exists()
        if not andere:
            v.status = 'aktiv'
            v.aktiv = True
            # Vertragsende wiederherstellen. Ein UNbefristeter Vertrag läuft nach
            # der Rücknahme wieder auf unbestimmte Zeit (ende = None). Bei einem
            # BEFRISTETEN Vertrag wird die ursprünglich vereinbarte Laufzeit aus dem
            # Snapshot (`ende_vorher`, bei Kündigungserfassung gesichert) restauriert
            # — sonst bliebe der bei einer ausserordentlichen Kündigung gesetzte
            # frühere Termin stehen und die vereinbarte Dauer wäre verloren (QS-Befund).
            if not v.ist_befristet:
                v.ende = None
            elif k.ende_vorher is not None:
                v.ende = k.ende_vorher
            # (befristet ohne Snapshot = Alt-Kündigung: `ende` unverändert lassen —
            #  nicht auf None, der Vertrag ist befristet.)
            v.save(update_fields=['status', 'aktiv', 'ende'])
        log_aktion(request, "Kündigung zurückgezogen", str(v.mieter), '', ziel=v)
        messages.success(request, '✅ ' + gettext('Kündigung zurückgezogen, Vertrag reaktiviert.'))
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_kuendigung_bestaetigen(request, pk):
    """Bestätigt eine (i.d.R. über das Mieterportal eingegangene) Kündigung:
    setzt den Vertrag auf 'gekuendigt' und legt die Auszugs-Pendenzen an."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Kuendigung
    from core.auth import log_aktion
    k = get_object_or_404(Kuendigung.objects.select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    v = k.vertrag
    if request.method != 'POST':
        return redirect(f'/neu/vertraege/{v.id}/')
    if k.status == 'zurueckgezogen':
        messages.error(request, gettext('Zurückgezogene Kündigung kann nicht bestätigt werden.'))
        return redirect(f'/neu/vertraege/{v.id}/')
    # Art. 266m OR: Die Mieterkündigung einer Familienwohnung wird erst mit der
    # ausdrücklichen Zustimmung des Ehegatten/Partners bestätigt. Die Zustimmung
    # kann hier nachgetragen werden.
    felder = ['status']
    if k.absender == 'mieter' and v.familienwohnung and not k.zustimmung_ehegatte:
        if request.POST.get('zustimmung_ehegatte') != 'on':
            messages.error(request, '⛔ ' + gettext(
                'Familienwohnung: Bestätigung erst mit der ausdrücklichen Zustimmung des '
                'Ehegatten/Partners (Art. 266m OR).'))
            return redirect(f'/neu/vertraege/{v.id}/')
        k.zustimmung_ehegatte = True
        felder.append('zustimmung_ehegatte')
        from core.services.automation import erledige_pendenzen_fuer
        erledige_pendenzen_fuer(v, ['Art. 266m'], user=request.user)

    per = k.per_datum or k.berechneter_termin
    # Eine Erstreckung verschiebt das Vertragsende (und damit die Sollstellung).
    ende = k.erstreckung_bis if (k.erstreckung_bis and per and k.erstreckung_bis > per) else per
    k.status = 'bestaetigt'
    k.save(update_fields=felder)
    v.status = 'gekuendigt'
    v.aktiv = False
    v.ende = ende
    v.save(update_fields=['status', 'aktiv', 'ende'])

    n_pendenzen = _auszugscheckliste_anlegen(v, k, ende, request.user, mit_leerstand=False)
    from core.services.mieterwechsel_fall import eroeffnen as _mw_eroeffnen
    _mw_eroeffnen(v, benutzer=request.user if request.user.is_authenticated else None)
    # Bestätigung erfolgt → 'Kündigung schriftlich bestätigen' abhaken
    from core.services.automation import erledige_pendenzen_fuer
    erledige_pendenzen_fuer(v, ['schriftlich', 'Kündigungsformular'], user=request.user)
    log_aktion(request, "Kündigung bestätigt", str(v.mieter),
               f"per {ende.strftime('%d.%m.%Y') if ende else '—'}, {n_pendenzen} Pendenzen", ziel=v)
    messages.success(request, '✅ ' + gettext('Kündigung bestätigt — Vertragsende %(wert)s · %(n_pendenzen)s Auszugs-Pendenzen erstellt.') % {'wert': ende.strftime('%d.%m.%Y') if ende else '—', 'n_pendenzen': n_pendenzen})
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kuendigung_formular(request, pk):
    """Amtliches Kündigungsformular (PDF) — Original des zuständigen Kantons ausfüllen.
    Art. 266n OR: Kündigt der Vermieter eine Familienwohnung, werden zwei separat an
    Mieter UND Ehegatte adressierte Kopien erzeugt (sonst ist die Kündigung nichtig).

    GET ist die VORSCHAU und schreibt nichts (ROUTE-01): Abgelegt und die Pendenz
    «Formular versenden» abgehakt wird erst beim ausdrücklichen «Erstellen» (POST,
    nur Schreib-Rollen). Das Formular gelangt erst mit der Zustellung ins Portal."""
    from django.http import HttpResponse
    from django.contrib import messages
    from django.core.exceptions import PermissionDenied
    from core.auth import hat_rolle
    from rentals.models import Kuendigung
    from crm.models import Organisation
    from django.shortcuts import redirect
    k = get_object_or_404(Kuendigung.objects.select_related(
        'vertrag__mieter', 'vertrag__mitmieter', 'vertrag__einheit__liegenschaft'), id=pk)
    vw = k.organisation      # Briefkopf der Kuendigung, nicht der aeltesten Verwaltung
    from core.services.formular_fill import kuendigung_zustellkopien, mit_wasserzeichen
    from core.services.formular_status import formular_status, kanton_fehlt_meldung
    from core.services.ablage import ablegen
    lg = k.vertrag.einheit.liegenschaft if k.vertrag.einheit_id else None
    zurueck = f'/neu/vertraege/{k.vertrag_id}/'

    # Kein Formular ohne erfassten Kanton, keine Nachbildung ohne Bestätigung
    # (Befunde G und J, 26.10.2026). Bestätigt wird über eine Zwischenseite —
    # der Aufruf ist ein Link (GET), kein Formular.
    formular = formular_status(lg, 'kuendigung')
    if formular['kanton_fehlt']:
        messages.error(request, '⛔ ' + kanton_fehlt_meldung(lg))
        return redirect(zurueck)
    if not formular['original'] and request.GET.get('nachbildung') != 'bestaetigt':
        return render(request, 'fw/formular_nachbildung.html', {
            **_global_filter(request), 'nav': 'vertraege',
            'titel': f"Kündigung {k.vertrag.mieter.display_name}",
            'warnung': formular['warnung'], 'zurueck': zurueck,
            'weiter': f'/neu/kuendigung/{k.id}/formular/?nachbildung=bestaetigt'})

    erstellen = request.method == 'POST'
    if erstellen and not hat_rolle(request.user, SCHREIB_ROLLEN):
        raise PermissionDenied
    kopien = kuendigung_zustellkopien(k.vertrag, k, verwaltung=vw)
    if formular['original']:
        if erstellen:
            for empf_name, pdf in kopien:
                suffix = f" — Zustellung an {empf_name}" if empf_name else ""
                ablegen(pdf, f"Kündigung {auf_deutsch(k.get_absender_display)} {k.eingang_datum:%d.%m.%Y}{suffix}",
                        kategorie='vertrag', vertrag=k.vertrag, dedup=True)
            # Amtliches Formular erstellt → 'schriftlich bestätigen / Formular versenden' abhaken.
            # Bei einer Nachbildung NICHT: Mit ihr ist das amtliche Formular nicht erstellt.
            from core.services.automation import erledige_pendenzen_fuer
            erledige_pendenzen_fuer(k.vertrag, ['schriftlich', 'Kündigungsformular'],
                                    user=request.user)
    else:
        kopien = [(n, mit_wasserzeichen(pdf)) for n, pdf in kopien]

    if len(kopien) > 1:
        # Art. 266n: alle Kopien in EIN PDF bündeln (jede Seite separat versenden).
        from pypdf import PdfReader, PdfWriter
        import io as _io
        writer = PdfWriter()
        for _n, pdf in kopien:
            for page in PdfReader(_io.BytesIO(pdf)).pages:
                writer.add_page(page)
        out = _io.BytesIO(); writer.write(out); pdf_bytes = out.getvalue()
        messages.info(request, "Familienwohnung (Art. 266n OR): Es wurden zwei separat adressierte "
                               "Kopien erstellt — je Ehegatte einzeln und mit separater Post zustellen, "
                               "sonst ist die Kündigung nichtig.")
    else:
        pdf_bytes = kopien[0][1]

    if k.absender == 'vermieter':
        # Versandschritt: Das PDF trägt kein Unterschriftsbild (Audit MIET-03).
        messages.warning(request, UNTERSCHRIFT_HINWEIS_KUENDIGUNG)
    resp = HttpResponse(bytes(pdf_bytes), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Kuendigung_{k.vertrag.mieter.nachname}.pdf"'
    return resp
