# core/auth.py
"""
Zentrales Rollen- & Berechtigungskonzept für swissImmo.

Rollen (je Organisation an der `Mitgliedschaft`; Eigentümer als Django-Gruppe):

| Rolle           | Darf                                                          |
|-----------------|---------------------------------------------------------------|
| Inhaber         | Alles, dazu Mitglieder, Abo, Zahlungsfreigabe-Limit            |
| Verwalter       | Alles ausser Inhaber-Sachen: Läufe, Löschen, Betreibung        |
| Sachbearbeiter  | Erfassen & Bearbeiten (Mieter, Tickets, Belege, Zahlungen)     |
| Buchhaltung     | NUR Finanzen: Debitoren, Kreditoren, Buchungen, Berichte       |
| Lesezugriff     | Nur Ansicht & PDFs (Treuhand / Revision)                       |
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
import logging
from django.contrib.auth.decorators import user_passes_test
from ninja.security import SessionAuth

logger = logging.getLogger(__name__)


# Team-Rollen der Projektanweisung. Seit Etappe 4.3 hängen sie an der
# `Mitgliedschaft` je Organisation, nicht mehr an globalen Django-Gruppen.
ROLLE_INHABER = "Inhaber"
ROLLE_VERWALTER = "Verwalter"
ROLLE_SACHBEARBEITER = "Sachbearbeiter"
ROLLE_LESEZUGRIFF = "Lesezugriff"

#: Nur Finanzen (Etappe 2, FUNK-08): Debitoren, Kreditoren, Buchungen, Berichte.
#: Bewusst KEINE Team-Rolle, wie die Hauswartung: `TEAM_ROLLEN` ist die Sicht auf
#: Stammdaten, Verträge und Personen, und die sieht die Buchhaltung nicht. Jede
#: View, die nur `TEAM_ROLLEN` verlangt, antwortet ihr mit 403 (Standard ist
#: «nein»). Frei ist sie nur dort, wo `FINANZ_*_ROLLEN` steht.
ROLLE_BUCHHALTUNG = "Buchhaltung"

#: Betriebsrolle für die Hauswartung. Bewusst KEINE Team-Rolle: Sie steht nicht
#: in `TEAM_ROLLEN`, und jede View, die nur `TEAM_ROLLEN` verlangt (Finanzen,
#: Mietzinse, Verträge, Personen, Einstellungen …), antwortet ihr mit 403.
#: Freigeschaltet ist sie ausschliesslich dort, wo `HAUSWART_ROLLEN` steht —
#: heute die Schadensmeldungen (Liste, Detail, Status).
ROLLE_HAUSWART = "Hauswart"

#: Portal-Rolle, KEINE Team-Rolle. Eigentümer bekommen keine Mitgliedschaft;
#: sie hängen über `Eigentuemer.benutzer` an ihrem Datensatz. Deshalb bleibt
#: diese eine Rolle bei den Gruppen — sie beantwortet eine andere Frage.
ROLLE_EIGENTUEMER = "Eigentümer"

# Team-Rollen = dürfen die Oberfläche lesen (Eigentümer bewusst NICHT —
# sie würden sonst die Daten ALLER Eigentümer sehen).
TEAM_ROLLEN = (ROLLE_INHABER, ROLLE_VERWALTER, ROLLE_SACHBEARBEITER, ROLLE_LESEZUGRIFF)
SCHREIB_ROLLEN = (ROLLE_INHABER, ROLLE_VERWALTER, ROLLE_SACHBEARBEITER)
VERWALTUNGS_ROLLEN = (ROLLE_INHABER, ROLLE_VERWALTER)

#: Rollen mit Finanzrechten: Sie dürfen Debitoren, Kreditoren und Buchungen sehen.
BUCHHALTUNG_ROLLEN = (ROLLE_BUCHHALTUNG,)
FINANZ_LESE_ROLLEN = TEAM_ROLLEN + BUCHHALTUNG_ROLLEN
FINANZ_SCHREIB_ROLLEN = SCHREIB_ROLLEN + BUCHHALTUNG_ROLLEN
#: Buchungsläufe, Zahlungen, Stornos: was bisher die Verwaltung allein tat und
#: zum Tagesgeschäft der Buchhaltung gehört. Der Zahlungslauf ab Freigabelimit
#: braucht trotzdem eine zweite Person (`finance/freigabe.py`).
FINANZ_VERWALTUNGS_ROLLEN = VERWALTUNGS_ROLLEN + BUCHHALTUNG_ROLLEN

#: Wer eine Zahlung ab dem Freigabelimit freigeben darf (Vier-Augen-Prinzip).
#: Nur die Verwaltung: Die Buchhaltung erfasst und löst aus, sie gibt nicht frei.
ZAHLUNGSFREIGABE_ROLLEN = VERWALTUNGS_ROLLEN

#: Betreibung leitet nur die Verwaltung ein (Rechtsfolgen, Kosten; Etappe 2,
#: SICH-11, `docs/KONZEPT-UI.md` §8).
BETREIBUNGS_ROLLEN = VERWALTUNGS_ROLLEN

#: Rollen, für die der zweite Faktor immer Pflicht ist, ob die Verwaltung den
#: Schalter gesetzt hat oder nicht: Sie lösen Zahlungen aus oder leiten
#: Betreibungen ein (Etappe 2, SICH-10).
ZWEIFAKTOR_PFLICHT_ROLLEN = (ROLLE_INHABER, ROLLE_VERWALTER, ROLLE_BUCHHALTUNG)

#: Was nur der Inhaber darf: Abo und Rechnung, die Organisation löschen,
#: Mitglieder einladen. Heute noch nirgends verdrahtet — die Konstante steht
#: hier, damit der Unterschied zwischen Inhaber und Verwalter einen Ort hat
#: und nicht beim ersten Bedarf neu erfunden wird.
INHABER_ROLLEN = (ROLLE_INHABER,)

#: Wer Schadensmeldungen ansehen darf: das Team plus die Hauswartung.
HAUSWART_ROLLEN = (ROLLE_HAUSWART,)
TICKET_LESE_ROLLEN = TEAM_ROLLEN + HAUSWART_ROLLEN
#: Wer den Status einer Schadensmeldung ändern darf.
TICKET_SCHREIB_ROLLEN = SCHREIB_ROLLEN + HAUSWART_ROLLEN


def _mit_inhaber(rollen):
    """Der Inhaber darf, was das Team darf (siehe `hat_rolle`)."""
    rollen = tuple(rollen)
    if ROLLE_INHABER not in rollen and any(r in TEAM_ROLLEN for r in rollen):
        rollen += (ROLLE_INHABER,)
    return rollen


def hat_rolle(user, rollen):
    """True wenn der Benutzer in der AKTIVEN Organisation eine der Rollen hat.

    Bis Etappe 4.2 las das `user.groups` — global. Eine Person, die für zwei
    Verwaltungen arbeitet, hatte damit überall dieselbe Rolle, und wer bei A
    „Verwaltung" war, war es bei B auch. Genau das schliesst 4.3.

    STRENG, OHNE RÜCKFALL AUF DIE GRUPPE
    ------------------------------------
    Keine Mitgliedschaft in der aktiven Organisation heisst keine Rechte. Ein
    Rückfall auf die Django-Gruppe wäre bequemer, liesse aber genau den Pfad
    offen, den dieser Schritt schliessen soll — wer in B keine Mitgliedschaft
    hat, behielte dort die Rechte seiner globalen Gruppe.

    Ohne gesetzte Organisation ist die Antwort ebenfalls `False`, nicht
    „alles": derselbe Grundsatz wie im `TenantManager`.

    Superuser bleiben ausgenommen (Notfall-Zugang), wie bisher.

    DER INHABER DARF, WAS DAS TEAM DARF
    -----------------------------------
    Nach der Rollentabelle (`docs/KONZEPT-UI.md`, Abschnitt 8) hat der Inhaber
    jede Befugnis der anderen Team-Rollen. Rund zwanzig Views verlangten aber
    nur `ROLLE_VERWALTER` — der Inhaber einer frisch angelegten Organisation
    stand dort vor einem 403, ausgerechnet auch bei «Benutzer & Rollen», die
    nach der Tabelle ihm allein zusteht. Verlangt eine Prüfung irgendeine
    Team-Rolle, genügt darum auch die Inhaber-Rolle. Portal-Rollen
    (`ROLLE_EIGENTUEMER`) erweitert das bewusst nicht.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    rollen = _mit_inhaber(rollen)

    from core.tenancy import aktuelle_organisation
    from crm.models import Mitgliedschaft

    organisation = aktuelle_organisation()
    if organisation is None:
        return False
    return Mitgliedschaft.objects.filter(
        benutzer=user, organisation=organisation, rolle__in=rollen).exists()


def darf_mit(eigene, user, rollen):
    """Wie `hat_rolle`, aber gegen schon gelesene Rollen (`eigene_rollen`).

    Für Stellen, die mehrere Rollenfragen auf einmal beantworten (die
    Oberflächen-Schalter in `_global_filter`): eine Abfrage statt einer je Frage.
    Gleiche Regeln: Superuser dürfen, der Inhaber darf, was das Team darf."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return bool(set(eigene) & set(_mit_inhaber(rollen)))


def ist_nur_buchhaltung(user):
    """True wenn die Person in der aktiven Organisation Buchhaltung ist und
    KEINE Team-Rolle hat. Sie sieht ausschliesslich die Finanzen (Navigation,
    Suche, Startseite richten sich danach)."""
    return hat_rolle(user, BUCHHALTUNG_ROLLEN) and not hat_rolle(user, TEAM_ROLLEN)


def ist_nur_hauswart(user):
    """True wenn der Benutzer in der aktiven Organisation Hauswart ist und
    KEINE Team-Rolle hat (Superuser und Team gelten nie als «nur Hauswart»).

    Für diese Konten ist jede Sicht auf die zugeordneten Liegenschaften
    (`Liegenschaft.hauswarte`) beschränkt."""
    return hat_rolle(user, HAUSWART_ROLLEN) and not hat_rolle(user, TEAM_ROLLEN)


def hauswart_darf_liegenschaft(user, liegenschaft_id):
    """Darf dieser Benutzer Daten der Liegenschaft sehen/ändern?

    Für alle ausser dem reinen Hauswart `True` (dort greift die Rollenprüfung
    der View). Der Hauswart braucht eine Zuordnung; die Abfrage läuft durch den
    `TenantManager`, eine fremde Organisation findet also nichts."""
    if not ist_nur_hauswart(user):
        return True
    from portfolio.models import Liegenschaft
    return Liegenschaft.objects.filter(pk=liegenschaft_id, hauswarte=user).exists()


def ist_eigentuemer(user):
    """True wenn der User ein Eigentümer-Login ist (Eigentümer-Verknüpfung oder Gruppe)."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'eigentuemer_profil', None) is not None:
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
    """Wie login_required, prüft zusätzlich die Rolle.

    Zwei Fälle, bewusst unterschieden:

    - **Nicht angemeldet** → Weiterleitung auf die Anmeldung (wie bisher).
    - **Angemeldet, aber falsche Rolle** → 403. Früher ging auch dieser Fall
      auf die Anmeldeseite. Für jemanden, der bereits angemeldet ist, sieht
      das nach einem Defekt aus: Er meldet sich erneut an und landet wieder
      am selben Punkt. Eine klare Absage ist ehrlicher — und das, was HTTP
      dafür vorsieht.

    Zusätzlich merkt sich die View ihre Rollen in `benoetigte_rollen`. Damit
    kann die Oberfläche Einträge, die eine Rolle ohnehin nicht öffnen darf,
    von vornherein ausgrauen, statt sie in die Absage laufen zu lassen —
    siehe `darf_oeffnen`.
    """
    from functools import wraps
    from django.contrib.auth.views import redirect_to_login
    from django.core.exceptions import PermissionDenied

    def deko(view):
        @wraps(view)
        def gehuellt(request, *args, **kwargs):
            u = getattr(request, 'user', None)
            if hat_rolle(u, rollen):
                return view(request, *args, **kwargs)
            if not (u and u.is_authenticated):
                return redirect_to_login(request.get_full_path(), '/login/')
            raise PermissionDenied(
                "Für diesen Bereich fehlt die Berechtigung: " + ", ".join(rollen))
        gehuellt.benoetigte_rollen = tuple(rollen)
        return gehuellt
    return deko


def darf_oeffnen(user, pfad, eigene_rollen=None):
    """Darf dieser Benutzer die View hinter `pfad` aufrufen?

    Liest die Rollen direkt an der View ab (`benoetigte_rollen`, vom Dekorator
    gesetzt) — es gibt also keine zweite, von Hand gepflegte Liste, die mit
    den Dekoratoren auseinanderlaufen könnte. Für Aktionslisten in der
    Oberfläche gedacht; ersetzt die Prüfung in der View nicht.
    Unbekannter Pfad → True (nicht ausgrauen, was sich nicht beurteilen lässt).

    `eigene_rollen` (aus `eigene_rollen(user)`): Wer viele Pfade prüft — die
    Navigation prüft jeden Reiter und jeden Palette-Eintrag —, liest die Rollen
    EINMAL statt je Pfad eine Abfrage (UI-Audit 26.10.2026: sonst ~60 Abfragen
    mehr auf jeder Seite)."""
    from django.urls import resolve
    try:
        rollen = getattr(resolve(pfad.split('?')[0]).func, 'benoetigte_rollen', None)
    except Exception:
        return True
    if rollen is None:
        return True
    if eigene_rollen is None:
        return hat_rolle(user, rollen)
    if user.is_superuser:
        return True
    return bool(eigene_rollen & set(_mit_inhaber(rollen)))


def eigene_rollen(user):
    """Die Rollen des Benutzers in der aktiven Organisation — eine Abfrage."""
    from core.tenancy import aktuelle_organisation
    from crm.models import Mitgliedschaft
    if not user or not user.is_authenticated:
        return set()
    organisation = aktuelle_organisation()
    if organisation is None:
        return set()
    return set(Mitgliedschaft.objects.filter(benutzer=user, organisation=organisation)
               .values_list('rolle', flat=True))


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


def _diffbare_felder(obj):
    """Konkrete, sinnvoll vergleichbare Felder eines Modells (keine PK/Relationen/
    auto-Zeitstempel/Datei-/Passwortfelder)."""
    felder = []
    for f in obj._meta.concrete_fields:
        if f.primary_key or f.is_relation:
            continue
        if getattr(f, 'auto_now', False) or getattr(f, 'auto_now_add', False):
            continue
        if f.get_internal_type() in ('FileField', 'ImageField', 'BinaryField'):
            continue
        if f.name in ('password', 'last_login'):
            continue
        felder.append(f)
    return felder


def snapshot_model(obj):
    """Momentaufnahme aller diffbaren Felder eines Modells (für Vorher/Nachher).
    Leer, wenn das Objekt (noch) keine PK hat."""
    if obj is None or not getattr(obj, 'pk', None):
        return {}
    snap = {}
    for f in _diffbare_felder(obj):
        try:
            snap[f.name] = getattr(obj, f.name)
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)
    return snap


def diff_model(alt, neu, obj):
    """Vorher→Nachher-Text mit den verbose_name des Modells als Feldbeschriftung."""
    labels = {f.name: str(getattr(f, 'verbose_name', f.name)) for f in _diffbare_felder(obj)}
    return diff_text(alt, neu, labels)


def konto_freigeben(benutzer, organisation=None):
    """Ein Konto loslassen, ohne fremde Zugaenge mitzureissen.

    `Benutzer` traegt bewusst keinen Organisationsbezug: Ein Mensch kann in
    mehreren Verwaltungen Mitglied sein und in einer weiteren ein Portalkonto
    haben. `benutzer.delete()` entfernte ihn ueberall — samt Mitgliedschaften
    (CASCADE) und samt der Verknuepfung zu fremden Mieter-/Eigentuemerprofilen
    (SET_NULL). Verwaltung A haette so den Zugang von Verwaltung B geloescht,
    ohne es zu bemerken (Audit 18.08.2026, gleiche Wurzel wie in
    `fw_benutzer_loeschen`).

    Deshalb: die Mitgliedschaft DIESER Verwaltung loesen, und das Konto nur
    fallen lassen, wenn danach nichts mehr daran haengt — weder eine
    Mitgliedschaft noch ein Mieter- oder Eigentuemerprofil. Gibt zurueck, ob
    das Konto geloescht wurde.
    """
    if benutzer is None:
        return False
    from crm.models import Mitgliedschaft

    if organisation is not None:
        Mitgliedschaft.alle_organisationen.filter(
            benutzer=benutzer, organisation=organisation).delete()

    haengt_dran = (
        Mitgliedschaft.alle_organisationen.filter(benutzer=benutzer).exists()
        or getattr(benutzer, 'mieter_profil', None) is not None
        or getattr(benutzer, 'eigentuemer_profil', None) is not None
    )
    if haengt_dran:
        return False
    try:
        benutzer.delete()
        return True
    except Exception:
        # Bleibt ein Fremdschluessel haengen, wird das Konto stillgelegt statt
        # geloescht — ein aktiver Zugang ohne Profil waere das Schlimmere.
        benutzer.is_active = False
        benutzer.save(update_fields=['is_active'])
        return False


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
        # DIE ORGANISATION AUSDRÜCKLICH BESTIMMEN — nicht dem Modell überlassen.
        #
        # `AktivitaetsLog.save()` nimmt sonst den Mandantenkontext — und beim
        # LOGIN ist noch keiner gesetzt: Die Middleware liest ihn aus der
        # Mitgliedschaft, und die steht erst fest, wenn der Benutzer angemeldet
        # IST. Genau dort schlüge die Ableitung fehl, und weil diese Funktion
        # alle Fehler schluckt, hörte der Audit-Trail still auf zu schreiben.
        # (Bis Etappe 6.3 wich `save()` auf die einzige vorhandene Organisation
        # aus. Das trug, solange es eine gab.)
        #
        # Und weil diese Funktion jeden Fehler schluckt (zu Recht: Ein
        # Logbucheintrag darf nie einen Geschäftsprozess brechen), wäre die
        # Folge kein Fehler, sondern ein LEERER AUDIT-TRAIL für Anmeldungen.
        # Ein Protokoll, das still aufhört zu protokollieren, ist schlimmer als
        # keines — man verlässt sich darauf.
        #
        # Der Benutzer ist hier bekannt, also kommt die Organisation aus seiner
        # Mitgliedschaft. Bei mehreren gewinnt die älteste; das ist eine
        # Näherung, aber eine sichtbare — und allemal besser als gar kein
        # Eintrag.
        from core.tenancy import aktuelle_organisation
        organisation = aktuelle_organisation()
        if organisation is None and user is not None:
            from crm.models import Mitgliedschaft
            # `alle_organisationen`: Der Zweig laeuft nur, wenn KEIN Kontext
            # gesetzt ist — er sucht die Organisation ja gerade. Mit `objects`
            # wuerde `log_aktion` werfen, und weil die Funktion alle Fehler
            # schluckt, hoerte der Audit-Trail still auf zu schreiben.
            mitgliedschaft = (Mitgliedschaft.alle_organisationen.filter(benutzer=user)
                              .order_by('pk').select_related('organisation').first())
            organisation = mitgliedschaft.organisation if mitgliedschaft else None

        AktivitaetsLog.objects.create(
            benutzer=user,
            # Ohne bestimmte Organisation gar nicht mitgeben: Dann entscheidet
            # `AktivitaetsLog.save()` über den Kontext. Steht auch der nicht,
            # bricht das Schreiben ab — und das ist richtiger, als den Eintrag
            # irgendeiner Verwaltung zuzuschlagen.
            **({'organisation': organisation} if organisation is not None else {}),
            aktion=str(aktion)[:100],
            objekt=str(objekt)[:200],
            details=str(details)[:2000],
            ziel_typ=ziel_typ,
            ziel_id=ziel_id,
            kategorie=kategorie or kategorie_fuer(aktion),
            ip_adresse=ip or (client_ip(request) if request else None),
        )
    except Exception:
        # NICHT mehr stumm. `log_aktion` schluckt Fehler bewusst — ein
        # misslungener Protokolleintrag darf die eigentliche Aktion nicht
        # abbrechen. Aber schweigen darf er nicht: Genau hier verschwanden
        # seit Etappe 6.2 alle fehlgeschlagenen Anmeldungen ohne bestimmbare
        # Organisation, und niemand konnte es sehen (Audit 18.08.2026).
        #
        # Sicherheitsereignisse gehen deshalb mindestens ins Server-Log —
        # eine Spur ausserhalb der Datenbank ist unendlich viel mehr als
        # keine. Alles Uebrige bleibt auf `debug`.
        if (kategorie or '') == 'sicherheit':
            # Kein Mandant bestimmbar — dann gehoert das Ereignis ins
            # Betreiberlog. Ein Anmeldeversuch mit einem Benutzernamen, den es
            # gar nicht gibt, trifft die INSTALLATION, nicht eine Verwaltung.
            # Ohne diese Zeilen verschwand er spurlos (Audit Lueecke 2).
            try:
                from core.models import SicherheitsEreignis
                SicherheitsEreignis.objects.create(
                    aktion=str(aktion)[:100],
                    objekt=str(objekt)[:200],
                    details=str(details)[:2000],
                    ip_adresse=ip or (client_ip(request) if request else None),
                )
            except Exception:
                # Auch das Betreiberlog darf die eigentliche Aktion nicht
                # abbrechen — aber jetzt ist wirklich Schluss, und die Spur
                # geht ins Server-Log.
                logger.warning('Sicherheitsereignis nirgends geschrieben: %s / %s (%s)',
                               aktion, objekt, details, exc_info=True)
        else:
            logger.debug("Fehler bewusst übergangen", exc_info=True)
