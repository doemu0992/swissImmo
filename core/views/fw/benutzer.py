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

from core.auth import (ROLLE_INHABER, ROLLE_LESEZUGRIFF, ROLLE_SACHBEARBEITER,
                       ROLLE_VERWALTER, rolle_erforderlich)

from ._basis import _global_filter


# ============================================================
# BENUTZER CRUD (Django-User + Rollen/Gruppen)
# ============================================================

# Die vier Team-Rollen seit Etappe 4.3. `Inhaber` steht bewusst dabei: Wer
# die Benutzerverwaltung offen hat, ist Verwalter oder Inhaber und muss die
# Nachfolge regeln koennen. Eigentuemer fehlt — das ist eine Portal-Rolle.
_ROLLEN_WAHL = (ROLLE_INHABER, ROLLE_VERWALTER, ROLLE_SACHBEARBEITER, ROLLE_LESEZUGRIFF)


def _team_benutzer_oder_404(request, pk):
    """Ein Benutzer, den DIESE Verwaltung verwalten darf — sonst 404.

    HIER GREIFT DER TenantManager NICHT, und das ist kein Versehen: `Benutzer`
    trägt keine Organisationsspalte, weil ein Mensch in mehreren Verwaltungen
    MITGLIED sein kann (eine Treuhänderin ist EIN Konto mit ZWEI
    Mitgliedschaften). Gefiltert wird darum über `Mitgliedschaft` — und wer
    das an einer Stelle vergisst, hat dort keinen Schutz.

    Vergessen war es an zwei Stellen, gemessen am 17.08.2026: Ein Verwalter
    von A konnte über `/neu/benutzer/<id>/` das Konto eines Menschen aus
    Verwaltung B bearbeiten (die Bearbeitung legte ihm sogar eine
    Mitgliedschaft in A an) und über `…/loeschen/` löschen. Das war kein
    Leseleck, sondern ein Schreib- und Löschzugriff über die Mandantengrenze.

    404 und nicht 403: Ein 403 bestätigt, dass das Konto existiert, und
    erlaubt über fortlaufende IDs das Abzählen fremder Teams.
    """
    from django.contrib.auth import get_user_model
    from django.http import Http404

    from crm.models import Mitgliedschaft

    User = get_user_model()
    organisation = getattr(request, 'organisation', None)
    if organisation is None:
        raise Http404
    ziel = get_object_or_404(User, id=pk)
    if not Mitgliedschaft.objects.filter(benutzer=ziel, organisation=organisation).exists():
        raise Http404
    return ziel


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_benutzer_form(request, pk=None):
    """Team-Benutzer erfassen/bearbeiten (Name, E-Mail, Rolle, Passwort, aktiv)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from core.auth import log_aktion, snapshot_model, diff_model
    from crm.models import Mitgliedschaft

    User = get_user_model()
    ziel = _team_benutzer_oder_404(request, pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
        alt_snap = snapshot_model(User.objects.get(pk=pk)) if pk else {}
        alt_rolle = (next((g for g in ziel.groups.values_list('name', flat=True)
                           if g in _ROLLEN_WAHL), '') if ziel else '')
        username = P.get('username', '').strip()
        rolle = P.get('rolle', ROLLE_LESEZUGRIFF)
        if rolle not in _ROLLEN_WAHL:
            rolle = ROLLE_LESEZUGRIFF
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
        # Rolle setzen — Superuser-Rolle nicht anfassen.
        #
        # Seit Etappe 4.3 traegt die MITGLIEDSCHAFT die Rolle; `hat_rolle()`
        # liest nur noch sie. Ohne diese Zeilen bekaeme ein hier angelegter
        # Benutzer keine einzige Berechtigung und stuende vor einem 403 —
        # die Gruppe allein reicht nicht mehr.
        #
        # Die Gruppe wird trotzdem weitergefuehrt: `ist_eigentuemer()` und die
        # Benutzerliste lesen sie, und ein zweiter Ort, an dem dieselbe
        # Information steht, ist beim Umstellen weniger riskant als ein
        # abrupter Schnitt. Sie abzuloesen gehoert in einen eigenen PR.
        if not ziel.is_superuser:
            grp, _ = Group.objects.get_or_create(name=rolle)
            ziel.groups.set([grp])
            organisation = getattr(request, 'organisation', None)
            if organisation is not None:
                Mitgliedschaft.objects.update_or_create(
                    benutzer=ziel, organisation=organisation,
                    defaults={'rolle': rolle})
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


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_benutzer_loeschen(request, pk):
    """Benutzer löschen — nicht sich selbst, nicht den letzten Verwaltungs-Account."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.contrib.auth import get_user_model
    from core.auth import log_aktion

    User = get_user_model()
    ziel = _team_benutzer_oder_404(request, pk)
    if request.method == 'POST':
        if ziel == request.user:
            messages.error(request, "Du kannst deinen eigenen Account nicht löschen.")
            return redirect('/neu/benutzer/')
        # Lockout-Schutz: den letzten aktiven Verwaltungs-/Superuser DIESER
        # Organisation nicht löschen.
        #
        # Bis Etappe 4.3 zählte diese Prüfung über ALLE Organisationen. Das
        # war kein Leck, aber ein Datenverlust-Risiko aus derselben Wurzel:
        # Verwaltung A hielt sich für abgesichert, weil B noch Admins hat, und
        # konnte ihren letzten Verwalter löschen. Gefunden vom
        # `mandanten-auditor` beim Lauf über Etappe 3.
        from crm.models import Mitgliedschaft
        organisation = getattr(request, 'organisation', None)
        leitend = (Mitgliedschaft.ROLLE_INHABER, Mitgliedschaft.ROLLE_VERWALTER)
        ist_admin = ziel.is_superuser or Mitgliedschaft.objects.filter(
            benutzer=ziel, organisation=organisation, rolle__in=leitend).exists()
        if ist_admin:
            andere_admins = User.objects.filter(is_active=True).filter(
                Q(is_superuser=True)
                | Q(mitgliedschaften__organisation=organisation,
                    mitgliedschaften__rolle__in=leitend)
            ).exclude(id=ziel.id).distinct().count()
            if andere_admins == 0:
                messages.error(request, "Das ist der letzte Verwaltungs-Account — er kann nicht gelöscht werden.")
                return redirect('/neu/benutzer/')
        name = ziel.username
        # GETEILTE KONTEN NICHT GANZ LOESCHEN. Ein Mensch kann in mehreren
        # Verwaltungen Mitglied sein — eine Treuhaenderin ist EIN Konto mit
        # ZWEI Mitgliedschaften. `ziel.delete()` haette es ueberall entfernt:
        # Verwaltung A haette den Zugang von Verwaltung B geloescht, samt
        # deren Logbucheintraegen, und im schlimmsten Fall deren letzten
        # Administrator — ein Aussperren, das A gar nicht bemerkt haette.
        #
        # «Aus meinem Team entfernen» heisst deshalb: DIESE Mitgliedschaft
        # loeschen. Das ganze Konto faellt nur, wenn danach keine einzige
        # Mitgliedschaft mehr uebrig ist.
        Mitgliedschaft.objects.filter(benutzer=ziel, organisation=organisation).delete()
        rest = Mitgliedschaft.alle_organisationen.filter(benutzer=ziel).count()
        if rest == 0:
            log_aktion(request, "Benutzer gelöscht", name, '')
            ziel.delete()
            messages.success(request, f"🗑️ Benutzer {name} gelöscht.")
        else:
            log_aktion(request, "Benutzer aus Team entfernt", name,
                       f"noch in {rest} weiteren Verwaltung(en)")
            messages.success(
                request, f"🗑️ {name} wurde aus deinem Team entfernt. "
                         f"Das Konto bleibt bestehen — es wird in einer anderen "
                         f"Verwaltung genutzt.")
    return redirect('/neu/benutzer/')
