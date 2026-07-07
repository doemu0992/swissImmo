# core/auth.py
"""
Zentrales Rollen- & Berechtigungskonzept für swissImmo.

Vier Rollen (Django-Groups, werden per Migration angelegt):

| Rolle           | Darf                                                          |
|-----------------|---------------------------------------------------------------|
| Verwaltung      | Alles: Buchungsläufe, Löschen, Mahnungen, Verträge senden      |
| Sachbearbeitung | Erfassen & Bearbeiten (Mieter, Tickets, Belege, Zahlungen)     |
| Lesend          | Nur Ansicht & PDFs (Treuhand / Revision)                       |
| Eigentümer      | Nur das Eigentümer-Portal (/portal/), KEIN SPA-/API-Zugriff    |

Superuser haben immer alle Rechte (Notfall-Zugang).

Verwendung API (django-ninja):
    @router.post(..., auth=auth_schreiben)   # Verwaltung + Sachbearbeitung
    @router.delete(..., auth=auth_verwaltung) # nur Verwaltung
    # GET-Endpoints erben auth_lesen aus NinjaAPI(auth=auth_lesen)

Verwendung klassische Views:
    @rolle_erforderlich(ROLLE_VERWALTUNG)
    def send_mahnung_email_view(request, ...):
"""
from django.contrib.auth.decorators import user_passes_test
from ninja.security import SessionAuth

ROLLE_VERWALTUNG = "Verwaltung"
ROLLE_SACHBEARBEITUNG = "Sachbearbeitung"
ROLLE_LESEND = "Lesend"
ROLLE_EIGENTUEMER = "Eigentümer"

# Team-Rollen = dürfen ins SPA und die API lesen (Eigentümer bewusst NICHT —
# sie würden sonst die Daten ALLER Mandanten sehen).
TEAM_ROLLEN = (ROLLE_VERWALTUNG, ROLLE_SACHBEARBEITUNG, ROLLE_LESEND)
SCHREIB_ROLLEN = (ROLLE_VERWALTUNG, ROLLE_SACHBEARBEITUNG)
VERWALTUNGS_ROLLEN = (ROLLE_VERWALTUNG,)


def hat_rolle(user, rollen):
    """True wenn der User (eingeloggt) eine der Rollen hat. Superuser: immer True."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=rollen).exists()


def ist_eigentuemer(user):
    """True wenn der User ein Eigentümer-Login ist (Mandant-Verknüpfung oder Gruppe)."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'mandant_profil', None) is not None:
        return True
    return user.groups.filter(name=ROLLE_EIGENTUEMER).exists()


# ==========================================
# API-AUTH (django-ninja, Session-basiert)
# ==========================================

class RollenAuth(SessionAuth):
    """Session-Auth + Rollenprüfung. Kein Treffer → 401."""

    def __init__(self, rollen):
        super().__init__()
        self.rollen = rollen

    def authenticate(self, request, key):
        user = super().authenticate(request, key)
        if user is not None and hat_rolle(user, self.rollen):
            return user
        return None


auth_lesen = RollenAuth(TEAM_ROLLEN)             # Standard: alle GET-Endpoints
auth_schreiben = RollenAuth(SCHREIB_ROLLEN)      # Erfassen / Bearbeiten
auth_verwaltung = RollenAuth(VERWALTUNGS_ROLLEN) # Löschen, Buchungsläufe, Versand


# ==========================================
# VIEW-DECORATOR (klassische Django-Views)
# ==========================================

def rolle_erforderlich(*rollen):
    """Wie login_required, prüft zusätzlich die Rolle. Ersatz für staff_member_required."""
    return user_passes_test(lambda u: hat_rolle(u, rollen), login_url='/login/')


# ==========================================
# AUDIT-TRAIL
# ==========================================

def log_aktion(request, aktion, objekt="", details=""):
    """
    Schreibt einen Eintrag ins Aktivitätslog (wer hat wann was getan).
    Darf NIE den Geschäftsprozess brechen — Fehler werden geschluckt.
    """
    from core.models import AktivitaetsLog
    try:
        user = request.user if request.user.is_authenticated else None
        AktivitaetsLog.objects.create(
            benutzer=user,
            aktion=str(aktion)[:100],
            objekt=str(objekt)[:200],
            details=str(details)[:2000],
        )
    except Exception:
        pass
