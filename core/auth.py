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

# Modellklassen-Name → Ziel-Typ (für anklickbare Logeinträge + Objekt-Verlauf).
_ZIEL_TYP_MAP = {
    'Mietvertrag': 'vertrag',
    'Mieter': 'person',
    'Liegenschaft': 'liegenschaft',
    'Einheit': 'objekt',
    'Ticket': 'ticket',
    'Pendenz': 'pendenz',
}

# Stichwort → Kategorie (Reihenfolge zählt: erste Übereinstimmung gewinnt).
_KATEGORIE_KEYS = [
    ('geloescht',  ['gelöscht', 'storniert', 'zurückgezogen', 'entfernt']),
    ('sicherheit', ['angemeldet', 'abgemeldet', 'login', 'anmeldung', 'passwort']),
    ('finanzen',   ['verbucht', 'bezahlt', 'sollstellung', 'zahlung', 'mahn', 'pain.001',
                    'camt', 'afa', 'abrechnung', 'buchung', 'einlage', 'kaution', 'rechnung']),
    ('versand',    ['versendet', 'versand', 'e-mail', 'serienbrief', 'rundschreiben', 'gesendet']),
    ('erstellt',   ['erstellt', 'erfasst', 'erzeugt', 'hochgeladen', 'angelegt', 'beauftragt']),
    ('bearbeitet', ['bearbeitet', 'geändert', 'angepasst', 'freigegeben', 'zugeordnet', 'bestätigt']),
]


def kategorie_fuer(aktion):
    """Leitet die strukturierte Kategorie aus dem freien Aktionstext ab."""
    a = (aktion or '').lower()
    for kat, keys in _KATEGORIE_KEYS:
        if any(k in a for k in keys):
            return kat
    return 'sonstiges'


def client_ip(request):
    """Ermittelt die Client-IP (berücksichtigt Reverse-Proxy X-Forwarded-For)."""
    try:
        xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if xff:
            return xff.split(',')[0].strip()[:45]
        return (request.META.get('REMOTE_ADDR') or '').strip()[:45] or None
    except Exception:
        return None


def snapshot(obj, felder):
    """Momentaufnahme der angegebenen Felder eines Objekts (für Vorher/Nachher)."""
    snap = {}
    for f in felder:
        try:
            snap[f] = getattr(obj, f)
        except Exception:
            snap[f] = None
    return snap


def diff_text(alt, neu, labels=None):
    """Baut 'Feld: alt → neu'-Zeilen aus zwei Snapshots. Leer, wenn nichts änderte."""
    labels = labels or {}
    zeilen = []
    for f, altwert in (alt or {}).items():
        neuwert = (neu or {}).get(f)
        if str(altwert or '') != str(neuwert or ''):
            name = labels.get(f, f)
            zeilen.append(f"{name}: {altwert or '—'} → {neuwert or '—'}")
    return ' · '.join(zeilen)


def log_aktion(request, aktion, objekt="", details="", ziel=None, kategorie=None, ip=None, user=None):
    """
    Schreibt einen Eintrag ins Aktivitätslog (wer hat wann was getan).
    Optional `ziel` = betroffene Modellinstanz (Mietvertrag/Mieter/…) → der
    Eintrag wird im Logbuch anklickbar und erscheint im Verlauf des Objekts.
    `user` überschreibt den handelnden Benutzer (z. B. bei Login-Signalen, wo
    `request.user` noch nicht gesetzt ist). `kategorie` wird sonst automatisch
    aus der Aktion abgeleitet.
    Darf NIE den Geschäftsprozess brechen — Fehler werden geschluckt.
    """
    from core.models import AktivitaetsLog
    try:
        if user is None:
            ru = getattr(request, 'user', None) if request else None
            if ru is not None and getattr(ru, 'is_authenticated', False):
                user = ru
        ziel_typ, ziel_id = '', None
        if ziel is not None and getattr(ziel, 'pk', None):
            ziel_typ = _ZIEL_TYP_MAP.get(type(ziel).__name__, type(ziel).__name__.lower())
            ziel_id = ziel.pk
        AktivitaetsLog.objects.create(
            benutzer=user,
            aktion=str(aktion)[:100],
            objekt=str(objekt)[:200],
            details=str(details)[:2000],
            ziel_typ=ziel_typ,
            ziel_id=ziel_id,
            kategorie=kategorie or kategorie_fuer(aktion),
            ip_adresse=ip or (client_ip(request) if request else None),
        )
    except Exception:
        pass
