"""Sicherheits-Ereignisse (An-/Abmeldung, fehlgeschlagene Logins) ins Logbuch.

Angebunden über Djangos Auth-Signale. Jeder Eintrag bekommt Kategorie
'sicherheit' und die Client-IP, damit im Logbuch nachvollziehbar ist,
wer wann von wo im System war."""
from django.contrib.auth.signals import (
    user_logged_in, user_logged_out, user_login_failed,
)
from django.dispatch import receiver

from core.auth import log_aktion, client_ip


def _ist_portal(user):
    """Reine Mieter-/Eigentümer-Portalkonten nicht mitschreiben — nur Team-Zugänge."""
    return bool(getattr(user, 'mieter_profil', None) or getattr(user, 'eigentuemer_profil', None))


@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    if _ist_portal(user):
        return
    log_aktion(request, "Angemeldet", user.get_full_name() or user.username,
               '', kategorie='sicherheit', ip=client_ip(request) if request else None, user=user)


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    if user is None or _ist_portal(user):
        return
    log_aktion(request, "Abgemeldet", user.get_full_name() or user.username,
               '', kategorie='sicherheit', ip=client_ip(request) if request else None, user=user)


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    """Fehlversuch protokollieren — mit dem Konto, wenn es eines gibt.

    DER GRUND FUER DIE ZWEI ZEILEN MEHR (Audit 18.08.2026): Eine anonyme
    Anmeldeseite hat keinen Mandantenkontext, und `AktivitaetsLog` verlangt
    eine Organisation. Ohne Benutzer fand `log_aktion` keine, das Schreiben
    warf, und die Ausnahme wurde dort geschluckt — gemessen: vor der Etappe
    546 -> 547 Eintraege, danach 546 -> 546. Brute-Force-Versuche gegen die
    Installation hinterliessen damit KEINE Spur, obwohl die Kategorie
    `sicherheit` als revisionsrelevant gilt.

    Der haeufige und wichtige Fall ist der Angriff auf ein BESTEHENDES Konto.
    Dann laesst sich der Benutzer am versuchten Namen finden, und ueber seine
    Mitgliedschaft steht die Verwaltung fest. Nur der Versuch mit einem voellig
    unbekannten Namen bleibt ohne Zuordnung — der gehoert keiner Verwaltung und
    landet im Server-Log (siehe `log_aktion`).
    """
    versucht = (credentials or {}).get('username', '') or '—'
    benutzer = None
    if versucht and versucht != '—':
        from django.contrib.auth import get_user_model
        benutzer = get_user_model().objects.filter(username__iexact=versucht).first()
    log_aktion(request, "Anmeldung fehlgeschlagen", versucht,
               'Falsches Passwort oder unbekannter Benutzer',
               kategorie='sicherheit', ip=client_ip(request) if request else None,
               user=benutzer)


# --- Verwaiste Fälle, Termine und Zuläufe (Go-Live-Härtetest, Schritt 2) -------
# `Fall`, `Termin` und `Eingang` zeigen über (akte_typ, akte_id) auf eine
# beliebige Akte. Das ist ein GenericForeignKey OHNE Kaskade: Wer einen Vertrag,
# eine Liegenschaft oder eine Person löschte, liess den Mieterwechsel-Fall mit
# einer Akte zurück, die es nicht mehr gab. Der Fall ist ohne seine Akte
# bedeutungslos — er geht mit.
def _akte_geloescht(sender, instance, **kwargs):
    from django.contrib.contenttypes.models import ContentType
    from faelle.models import Fall
    ct = ContentType.objects.get_for_model(sender)
    Fall.alle_organisationen.filter(akte_typ=ct, akte_id=instance.pk).delete()
    # Ein Termin steht für sich (Kalender): nur den toten Bezug lösen.
    from faelle.models import Termin
    Termin.alle_organisationen.filter(akte_typ=ct, akte_id=instance.pk).update(
        akte_typ=None, akte_id=None)


def _akte_signale_verbinden():
    from django.db.models.signals import post_delete
    from crm.models import Mieter
    from portfolio.models import Liegenschaft
    from rentals.models import Mietvertrag
    for modell in (Mietvertrag, Liegenschaft, Mieter):
        post_delete.connect(_akte_geloescht, sender=modell,
                            dispatch_uid=f'akte_geloescht_{modell.__name__}')


_akte_signale_verbinden()


# --- Rollen-Zwischenspeicher (`core.auth.hat_rolle`) ---------------------------
def _rollen_cache_verwerfen(sender, **kwargs):
    from core import auth
    auth._rollen_generation[0] += 1


def _rollen_signale_verbinden():
    from django.db.models.signals import post_delete, post_save
    from crm.models import Mitgliedschaft
    for signal in (post_save, post_delete):
        signal.connect(_rollen_cache_verwerfen, sender=Mitgliedschaft,
                       dispatch_uid=f'rollen_cache_{signal.__class__.__name__}_{id(signal)}')


_rollen_signale_verbinden()
