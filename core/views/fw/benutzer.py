# core/views/fw/benutzer.py
#
# Benutzerverwaltung: Django-User plus Rollen ueber Gruppen. Etappe 1, siehe
# docs/ETAPPE-1-ZERLEGEN.md.
#
# Seit E2 ist das der EINZIGE Schreibpfad fuer Benutzer und Rollen — der
# Unfold-Admin ist lesend, auch fuer auth.User und auth.Group. Entsprechend
# haengt hier mehr dran, als die 93 Zeilen vermuten lassen.

from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from core.auth import rolle_erforderlich, ROLLE_VERWALTUNG

from ._basis import _global_filter


# ============================================================
# BENUTZER CRUD (Django-User + Rollen/Gruppen)
# ============================================================

_ROLLEN_WAHL = ('Verwaltung', 'Sachbearbeitung', 'Lesend')

@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_benutzer_form(request, pk=None):
    """Team-Benutzer erfassen/bearbeiten (Name, E-Mail, Rolle, Passwort, aktiv)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from core.auth import log_aktion, snapshot_model, diff_model

    User = get_user_model()
    ziel = get_object_or_404(User, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
        alt_snap = snapshot_model(User.objects.get(pk=pk)) if pk else {}
        alt_rolle = (next((g for g in ziel.groups.values_list('name', flat=True)
                           if g in _ROLLEN_WAHL), '') if ziel else '')
        username = P.get('username', '').strip()
        rolle = P.get('rolle', 'Lesend')
        if rolle not in _ROLLEN_WAHL:
            rolle = 'Lesend'
        if ziel is None:
            if not username:
                messages.error(request, "Benutzername ist erforderlich.")
                return redirect(request.path)
            if User.objects.filter(username__iexact=username).exists():
                messages.error(request, f"Benutzername '{username}' ist bereits vergeben.")
                return redirect(request.path)
            ziel = User(username=username)
        pw = P.get('passwort', '').strip()
        ziel.first_name = P.get('first_name', '').strip()
        ziel.last_name = P.get('last_name', '').strip()
        ziel.email = P.get('email', '').strip()
        # sich selbst nicht deaktivieren
        if ziel == request.user:
            ziel.is_active = True
        else:
            ziel.is_active = (P.get('is_active') == 'on')
        if pw:
            ziel.set_password(pw)
        ziel.save()
        # Rolle setzen (genau eine Gruppe) — Superuser-Rolle nicht anfassen
        if not ziel.is_superuser:
            grp, _ = Group.objects.get_or_create(name=rolle)
            ziel.groups.set([grp])
        _diff = diff_model(alt_snap, snapshot_model(ziel), ziel) if pk else ''
        if pk and alt_rolle and alt_rolle != rolle:
            _diff = f"Rolle: {alt_rolle} → {rolle}" + (' · ' + _diff if _diff else '')
        log_aktion(request, "Benutzer bearbeitet" if pk else "Benutzer erstellt",
                   ziel.username, _diff or rolle)
        messages.success(request, f"✅ Benutzer {ziel.username} gespeichert.")
        return redirect('/neu/benutzer/')

    aktuelle_rolle = ''
    if ziel:
        aktuelle_rolle = next((g for g in ziel.groups.values_list('name', flat=True) if g in _ROLLEN_WAHL), '')
    return render(request, 'fw/benutzer_form.html', {
        **basis, 'nav': 'benutzer', 'ziel': ziel, 'ist_neu': ziel is None,
        'rollen': _ROLLEN_WAHL, 'aktuelle_rolle': aktuelle_rolle,
        'ist_selbst': ziel == request.user if ziel else False,
    })


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_benutzer_loeschen(request, pk):
    """Benutzer löschen — nicht sich selbst, nicht den letzten Verwaltungs-Account."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.contrib.auth import get_user_model
    from core.auth import log_aktion

    User = get_user_model()
    ziel = get_object_or_404(User, id=pk)
    if request.method == 'POST':
        if ziel == request.user:
            messages.error(request, "Du kannst deinen eigenen Account nicht löschen.")
            return redirect('/neu/benutzer/')
        # Lockout-Schutz: letzten aktiven Verwaltungs-/Superuser nicht löschen
        ist_admin = ziel.is_superuser or ziel.groups.filter(name='Verwaltung').exists()
        if ist_admin:
            andere_admins = User.objects.filter(is_active=True).filter(
                Q(is_superuser=True) | Q(groups__name='Verwaltung')
            ).exclude(id=ziel.id).distinct().count()
            if andere_admins == 0:
                messages.error(request, "Das ist der letzte Verwaltungs-Account — er kann nicht gelöscht werden.")
                return redirect('/neu/benutzer/')
        name = ziel.username
        log_aktion(request, "Benutzer gelöscht", name, '')
        ziel.delete()
        messages.success(request, f"🗑️ Benutzer {name} gelöscht.")
    return redirect('/neu/benutzer/')
