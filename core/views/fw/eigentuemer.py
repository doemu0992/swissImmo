# core/views/fw/eigentuemer.py
#
# Block 20 der 33 (Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md): Eigentuemer
# anlegen und bearbeiten, Portal-Zugang vergeben, Liegenschaften zuordnen.
#
# Der Blockkommentar sagt noch "MANDATE CRUD" — das Modell hiess bis E3
# crm.Mandant. Der Kommentar bleibt unveraendert stehen: Dieser PR verschiebt
# nur, er formuliert nicht um.
#
# Unveraendert uebernommen. Neu sind nur die Importe hier oben.

import logging
from decimal import Decimal

from django.shortcuts import get_object_or_404, render

from core.auth import rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN
from portfolio.models import Liegenschaft

from ._basis import _global_filter, _num

logger = logging.getLogger(__name__)


# ============================================================
# MANDATE CRUD (Eigentümer) + Liegenschaft-Zuordnung
# ============================================================

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_eigentuemer_form(request, pk=None):
    """Eigentümer erfassen/bearbeiten + Liegenschaften zuordnen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Eigentuemer
    from core.auth import log_aktion, snapshot_model, diff_model
    md = get_object_or_404(Eigentuemer, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
        alt_snap = snapshot_model(Eigentuemer.objects.get(pk=pk)) if pk else {}
        obj = md or Eigentuemer()
        obj.firma_oder_name = P.get('firma_oder_name', '').strip()
        obj.kontaktperson = P.get('kontaktperson', '').strip()
        obj.strasse = P.get('strasse', '').strip()
        obj.plz = P.get('plz', '').strip()
        obj.ort = P.get('ort', '').strip()
        obj.telefon = P.get('telefon', '').strip()
        obj.email = P.get('email', '').strip()
        obj.bank_name = P.get('bank_name', '').strip()
        obj.iban = P.get('iban', '').strip()
        try:
            obj.honorar_prozent = Decimal((_num(P.get('honorar_prozent')) or '0'))
        except Exception:
            obj.honorar_prozent = Decimal('0.00')
        if not obj.firma_oder_name:
            messages.error(request, "Name / Firma ist erforderlich.")
            return redirect(request.path)
        # Digitale Unterschrift des Eigentümers — Briefe, die in seinem Namen
        # rausgehen (Schlussabrechnung, Kautionsbelege), tragen sie.
        from core.services.unterschrift import uebernehme_aus_formular
        uebernehme_aus_formular(obj, request)
        obj.save()
        # Liegenschaften zuordnen: gewählte -> dieser Eigentuemer; abgewählte (bisher dieser) -> ohne Eigentuemer.
        # Nur wenn das Formular den Zuordnungsblock wirklich mitgeschickt hat: Ein POST
        # ohne diesen Block (Teilformular, abgebrochenes Rendering) hätte sonst still
        # ALLE Liegenschaften vom Eigentümer gelöst — und damit u.a. seine Unterschrift
        # aus jedem Brief entfernt, weil die Briefe über die Liegenschaft an ihn kommen.
        if P.get('lg_zuordnung') == '1':
            gewaehlt = set(P.getlist('liegenschaften'))
            for lg in Liegenschaft.objects.all():
                sid = str(lg.id)
                if sid in gewaehlt and lg.eigentuemer_id != obj.id:
                    lg.eigentuemer = obj
                    lg.save(update_fields=['eigentuemer'])
                elif sid not in gewaehlt and lg.eigentuemer_id == obj.id:
                    lg.eigentuemer = None
                    lg.save(update_fields=['eigentuemer'])
        _diff = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
        log_aktion(request, "Eigentuemer bearbeitet" if pk else "Eigentuemer erstellt", obj.firma_oder_name, _diff)
        messages.success(request, f"✅ Eigentuemer {obj.firma_oder_name} gespeichert.")
        return redirect('/neu/mandate/')

    alle_lg = Liegenschaft.objects.all().order_by('strasse')
    zugeordnet = set(Liegenschaft.objects.filter(eigentuemer=md).values_list('id', flat=True)) if md else set()
    from core.services.unterschrift import unterschrift_url as _sig_url
    sig_url = _sig_url(md) if md else ''
    return render(request, 'fw/mandat_form.html', {
        **basis, 'nav': 'mandate', 'md': md, 'ist_neu': md is None,
        'alle_liegenschaften': alle_lg, 'zugeordnet': zugeordnet,
        'unterschrift_url': sig_url,
        'unterschrift_verwaist': bool(md and getattr(md, 'unterschrift_bild', None)) and not sig_url,
        'portal_user': getattr(md, 'benutzer', None) if md else None,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_eigentuemer_portal_zugang(request, pk):
    """Erstellt/entfernt einen Eigentümer-Portal-Login und mailt die Zugangsdaten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.contrib.auth import get_user_model
    from crm.models import Eigentuemer
    from core.auth import log_aktion
    import secrets

    User = get_user_model()
    md = get_object_or_404(Eigentuemer, id=pk)
    ziel = f'/neu/mandate/{md.id}/bearbeiten/'
    if request.method != 'POST':
        return redirect(ziel)

    if request.POST.get('aktion') == 'entfernen':
        if md.benutzer_id:
            u = md.benutzer
            md.benutzer = None
            md.save(update_fields=['benutzer'])
            try:
                u.delete()
            except Exception:
                u.is_active = False
                u.save(update_fields=['is_active'])
        messages.success(request, "Portal-Zugang entfernt.")
        return redirect(ziel)

    basis_name = (md.email or f"eigentuemer{md.id}").strip().lower()
    passwort = secrets.token_urlsafe(9)
    if md.benutzer_id:
        u = md.benutzer
        u.set_password(passwort)
        u.is_active = True
        u.save()
    else:
        username = basis_name
        i = 1
        while User.objects.filter(username=username).exists():
            username = f"{basis_name}.{i}"
            i += 1
        u = User.objects.create_user(username=username, email=md.email or '', password=passwort)
        md.benutzer = u
        md.save(update_fields=['benutzer'])
    log_aktion(request, "Eigentümer-Portal-Zugang erstellt", md.firma_oder_name, u.username)

    mail_ok = False
    if md.email:
        from core.utils.email_service import send_eigentuemer_portal_zugang
        from crm.models import Organisation
        from django.conf import settings as _settings
        # Absender der Zugangsmail: die Verwaltung DIESES Eigentuemers.
        vw = md.organisation
        login_url = _settings.PORTAL_BASE_URL.rstrip('/') + '/portal/login/'
        mail_ok = send_eigentuemer_portal_zugang(
            md.email, md.firma_oder_name, u.username, passwort, login_url,
            absender_firma=(vw.firma if vw else ''))

    if mail_ok:
        messages.success(request, f"✅ Portal-Zugang aktiv. Zugangsdaten wurden an {md.email} gesendet. (Benutzername: {u.username})")
    elif md.email:
        messages.warning(request, f"⚠️ Portal-Zugang aktiv, aber E-Mail-Versand fehlgeschlagen. Benutzername: {u.username} · Passwort: {passwort} — bitte manuell mitteilen.")
    else:
        messages.success(request, f"✅ Portal-Zugang aktiv. Keine E-Mail hinterlegt — Benutzername: {u.username} · Passwort: {passwort} (bitte dem Eigentümer sicher mitteilen, wird nur einmal angezeigt).")
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_eigentuemer_loeschen(request, pk):
    """Löscht einen Eigentümer — NUR wenn keine Liegenschaften zugeordnet sind
    (eigentuemer->liegenschaft ist CASCADE; sonst würden Objekte/Verträge mitgelöscht)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Eigentuemer
    from core.auth import log_aktion
    md = get_object_or_404(Eigentuemer, id=pk)
    if request.method == 'POST':
        anzahl = Liegenschaft.objects.filter(eigentuemer=md).count()
        if anzahl > 0:
            messages.error(request, f"❌ '{md.firma_oder_name}' hat noch {anzahl} zugeordnete Liegenschaft(en). "
                                    "Bitte zuerst die Zuordnung im Bearbeiten-Dialog entfernen, dann löschen.")
            return redirect('/neu/mandate/')
        name = md.firma_oder_name
        # Verknüpften Eigentümer-Portal-Login mitentfernen — sonst bleibt ein
        # Login zurück, dessen eigentuemer_profil ins Leere zeigt.
        if md.benutzer_id:
            try:
                md.benutzer.delete()
            except Exception:
                logger.debug("Fehler bewusst übergangen", exc_info=True)
        log_aktion(request, "Eigentuemer gelöscht", name, '')
        md.delete()
        messages.success(request, f"🗑️ Eigentuemer {name} gelöscht.")
    return redirect('/neu/mandate/')
