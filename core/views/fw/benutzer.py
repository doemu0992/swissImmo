# core/views/fw/benutzer.py
#
# Benutzerverwaltung: Django-User plus Rollen ueber Gruppen. Etappe 1, siehe
# docs/ETAPPE-1-ZERLEGEN.md.
#
# Seit E2 ist das der EINZIGE Schreibpfad fuer Benutzer und Rollen — der
# Unfold-Admin ist lesend, auch fuer auth.User und auth.Group. Entsprechend
# haengt hier mehr dran, als die 93 Zeilen vermuten lassen.

from django.db.models import Q
from django.utils.translation import gettext
from django.shortcuts import get_object_or_404, render

from core.auth import (INHABER_ROLLEN, ROLLE_HAUSWART, ROLLE_INHABER, ROLLE_LESEZUGRIFF, ROLLE_SACHBEARBEITER,
                       ROLLE_VERWALTER, rolle_erforderlich)

from ._basis import _global_filter


# ============================================================
# BENUTZER CRUD (Django-User + Rollen/Gruppen)
# ============================================================

# Die vier Team-Rollen seit Etappe 4.3. `Inhaber` steht bewusst dabei: Wer
# die Benutzerverwaltung offen hat, ist Verwalter oder Inhaber und muss die
# Nachfolge regeln koennen. Eigentuemer fehlt — das ist eine Portal-Rolle.
_ROLLEN_WAHL = (ROLLE_INHABER, ROLLE_VERWALTER, ROLLE_SACHBEARBEITER, ROLLE_LESEZUGRIFF,
                ROLLE_HAUSWART)


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


def _konto_gehoert_nicht_allein_uns(ziel, organisation):
    """Ist das Konto auch ausserhalb DIESER Verwaltung in Gebrauch?

    SICH-02 (Audit 28.10.2026). Eine Treuhaenderin ist EIN Konto mit ZWEI
    Mitgliedschaften — und genau dort galt die Pruefung «Mitglied in A» fuer
    das GANZE Konto: Der Inhaber von A konnte Passwort, E-Mail, Aktiv-Flag und
    Gruppe setzen und damit die Inhaber-Rolle der Treuhaenderin bei B
    uebernehmen. Aenderbar ist an so einem Konto nur die EIGENE Mitgliedschaft.

    Ein Superuser zaehlt dazu: Sein Konto ist das des Betreibers, nicht das
    einer Verwaltung.
    """
    from crm.models import Mitgliedschaft

    # `alle_organisationen`: `Mitgliedschaft.objects` filtert auf die eigene
    # Verwaltung und fande die andere nie. Hier ist genau diese gemeint.
    return ziel.is_superuser or Mitgliedschaft.alle_organisationen.filter(
        benutzer=ziel).exclude(organisation=organisation).exists()


def _letzter_verwaltungszugang(ziel, organisation):
    """Waere `ziel` der letzte aktive Verwaltungs-Account DIESER Organisation?

    Bis Etappe 4.3 zaehlte diese Pruefung ueber ALLE Organisationen. Das war
    kein Leck, aber ein Datenverlust-Risiko aus derselben Wurzel: Verwaltung A
    hielt sich fuer abgesichert, weil B noch Admins hat, und konnte ihren
    letzten Verwalter loeschen. Gefunden vom `mandanten-auditor` beim Lauf ueber
    Etappe 3.
    """
    from django.contrib.auth import get_user_model

    from crm.models import Mitgliedschaft

    leitend = (Mitgliedschaft.ROLLE_INHABER, Mitgliedschaft.ROLLE_VERWALTER)
    ist_admin = ziel.is_superuser or Mitgliedschaft.objects.filter(
        benutzer=ziel, organisation=organisation, rolle__in=leitend).exists()
    if not ist_admin:
        return False
    andere_admins = get_user_model().objects.filter(is_active=True).filter(
        Q(is_superuser=True)
        | Q(mitgliedschaften__organisation=organisation,
            mitgliedschaften__rolle__in=leitend)
    ).exclude(id=ziel.id).distinct().count()
    return andere_admins == 0


def _aus_team_entfernen(request, ziel, organisation):
    """Beendet die Mitgliedschaft von `ziel` in DIESER Verwaltung.

    GETEILTE KONTEN NICHT GANZ LOESCHEN. Ein Mensch kann in mehreren
    Verwaltungen Mitglied sein — eine Treuhaenderin ist EIN Konto mit ZWEI
    Mitgliedschaften. `ziel.delete()` haette es ueberall entfernt: Verwaltung A
    haette den Zugang von Verwaltung B geloescht, samt deren Logbucheintraegen,
    und im schlimmsten Fall deren letzten Administrator — ein Aussperren, das A
    gar nicht bemerkt haette.

    «Aus meinem Team entfernen» heisst deshalb: DIESE Mitgliedschaft loeschen.
    Das ganze Konto faellt nur, wenn danach keine einzige Mitgliedschaft mehr
    uebrig ist. Gibt `True` zurueck, wenn entfernt wurde.
    """
    from django.contrib import messages

    from core.auth import log_aktion
    from crm.models import Mitgliedschaft

    if ziel == request.user:
        messages.error(request, gettext('Du kannst deinen eigenen Account nicht löschen.'))
        return False
    if _letzter_verwaltungszugang(ziel, organisation):
        messages.error(request, gettext('Das ist der letzte Verwaltungs-Account — er kann nicht gelöscht werden.'))
        return False
    name = ziel.username
    Mitgliedschaft.objects.filter(benutzer=ziel, organisation=organisation).delete()
    rest = Mitgliedschaft.alle_organisationen.filter(benutzer=ziel).count()
    if rest == 0:
        log_aktion(request, "Benutzer gelöscht", name, '')
        ziel.delete()
        messages.success(request, '🗑️ ' + gettext('Benutzer %(name)s gelöscht.') % {'name': name})
    else:
        log_aktion(request, "Benutzer aus Team entfernt", name,
                   f"noch in {rest} weiteren Verwaltung(en)")
        messages.success(
            request, '🗑️ ' + gettext('%(name)s wurde aus deinem Team entfernt. Das Konto bleibt bestehen — es wird in einer anderen Verwaltung genutzt.') % {'name': name})
    return True


# Mitglieder und Rollen verwalten ist Inhaber-Sache (docs/KONZEPT-UI.md §8).
# Bis 28.09.2026 stand hier ROLLE_VERWALTER — ein Verwalter konnte sich damit
# selbst zum Inhaber machen (`_ROLLEN_WAHL` enthält die Rolle, das eigene Konto
# ist nicht ausgenommen) und das Passwort jedes Kontos setzen, auch des Inhabers.
@rolle_erforderlich(*INHABER_ROLLEN)
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
    organisation = getattr(request, 'organisation', None)
    # Das Konto ist auch anderswo in Gebrauch: dann nur die EIGENE Mitgliedschaft
    # anfassen (SICH-02). Das eigene Konto darf jeder selbst aendern.
    nur_mitgliedschaft = bool(ziel and ziel != request.user
                              and _konto_gehoert_nicht_allein_uns(ziel, organisation))
    # Die Rolle in DIESER Verwaltung steht in der Mitgliedschaft; die Gruppe ist
    # global und gehoert bei einem geteilten Konto nicht uns.
    alt_rolle = ''
    if ziel:
        alt_rolle = (Mitgliedschaft.objects.filter(benutzer=ziel, organisation=organisation)
                     .values_list('rolle', flat=True).first() or '')

    if request.method == 'POST':
        P = request.POST
        alt_snap = snapshot_model(User.objects.get(pk=pk)) if pk else {}
        username = P.get('username', '').strip()
        rolle = P.get('rolle', ROLLE_LESEZUGRIFF)
        if rolle not in _ROLLEN_WAHL:
            rolle = ROLLE_LESEZUGRIFF
        if ziel is None:
            if not username:
                messages.error(request, gettext('Benutzername ist erforderlich.'))
                return redirect(request.path)
            if User.objects.filter(username__iexact=username).exists():
                messages.error(request, gettext("Benutzername '%(username)s' ist bereits vergeben.") % {'username': username})
                return redirect(request.path)
            ziel = User(username=username)
        pw = P.get('passwort', '').strip()
        if nur_mitgliedschaft:
            # Konto mit weiterer Mitgliedschaft: Passwort, E-Mail, Name und
            # Aktiv-Flag gehoeren der Person und ihren anderen Verwaltungen.
            # Wer sie hier trotzdem mitschickt, bekommt es gesagt, statt dass
            # es still verworfen wird.
            versucht = bool(pw) or any(
                (P.get(feld) is not None and P.get(feld).strip() != (getattr(ziel, feld) or ''))
                for feld in ('first_name', 'last_name', 'email'))
            if versucht:
                messages.warning(request, gettext(
                    'Dieses Konto wird auch in einer anderen Verwaltung genutzt. Passwort, E-Mail '
                    'und Name kann nur die Person selbst ändern — gespeichert wurde nur die '
                    'Rolle in deiner Verwaltung.'))
            if P.get('mitgliedschaft_beenden') == 'on':
                # Deaktivieren heisst hier: aus DIESEM Team austreten lassen.
                _aus_team_entfernen(request, ziel, organisation)
                return redirect('/neu/benutzer/')
        else:
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
            if not nur_mitgliedschaft:
                grp, _ = Group.objects.get_or_create(name=rolle)
                ziel.groups.set([grp])
            if organisation is not None:
                Mitgliedschaft.objects.update_or_create(
                    benutzer=ziel, organisation=organisation,
                    defaults={'rolle': rolle})
            # Hauswart: nur die zugeordneten Liegenschaften. Jede andere Rolle
            # verliert eine alte Zuordnung — sonst bliebe sie unsichtbar
            # bestehen und käme bei einem Rollenwechsel zurück.
            from portfolio.models import Liegenschaft
            gewaehlt = P.getlist('hauswart_lg') if rolle == ROLLE_HAUSWART else []
            for lg in Liegenschaft.objects.all():   # TenantManager: nur diese Verwaltung
                if str(lg.pk) in gewaehlt:
                    lg.hauswarte.add(ziel)
                else:
                    lg.hauswarte.remove(ziel)
        _diff = diff_model(alt_snap, snapshot_model(ziel), ziel) if pk else ''
        if pk and alt_rolle and alt_rolle != rolle:
            _diff = f"Rolle: {alt_rolle} → {rolle}" + (' · ' + _diff if _diff else '')
        log_aktion(request, "Benutzer bearbeitet" if pk else "Benutzer erstellt",
                   ziel.username, _diff or rolle)
        messages.success(request, '✅ ' + gettext('Benutzer %(username)s gespeichert.') % {'username': ziel.username})
        return redirect('/neu/benutzer/')

    aktuelle_rolle = alt_rolle if alt_rolle in _ROLLEN_WAHL else ''
    return render(request, 'fw/benutzer_form.html', {
        **basis, 'nav': 'benutzer', 'ziel': ziel, 'ist_neu': ziel is None,
        'nur_mitgliedschaft': nur_mitgliedschaft,
        'rollen': _ROLLEN_WAHL, 'aktuelle_rolle': aktuelle_rolle,
        'ist_selbst': ziel == request.user if ziel else False,
        'hauswart_liegenschaften': basis['alle_liegenschaften'],
        'hauswart_zugeordnet': (set(ziel.hauswart_liegenschaften.values_list('pk', flat=True))
                                if ziel else set()),
    })


@rolle_erforderlich(*INHABER_ROLLEN)
def fw_benutzer_loeschen(request, pk):
    """Benutzer aus dem Team entfernen — nicht sich selbst, nicht den letzten Verwaltungs-Account.

    Das Konto selbst faellt nur, wenn es danach in keiner Verwaltung mehr
    Mitglied ist (`_aus_team_entfernen`).
    """
    from django.shortcuts import redirect

    ziel = _team_benutzer_oder_404(request, pk)
    if request.method == 'POST':
        _aus_team_entfernen(request, ziel, getattr(request, 'organisation', None))
    return redirect('/neu/benutzer/')
