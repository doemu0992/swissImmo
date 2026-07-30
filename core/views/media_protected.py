"""Zugriffskontrollierte Auslieferung von Media-Dateien.

Ohne Schutz sind alle hochgeladenen Dateien (Verträge, Ausweis-/Lohn-/
Betreibungs-Kopien der Bewerber, Kautionszertifikate, Belege) über ihre
/media/-URL öffentlich abrufbar — ein DSG-Risiko und eine ID-Enumeration.

Regel:
- Sensible Prefixe (Bewerber-Dokumente, Verträge, Belege, Zertifikate,
  Abnahmefotos, Unterschriften) und generell alle Nicht-Bild-Dateien (PDFs)
  werden NUR an eingeloggte Team-Mitglieder ausgeliefert.
- Öffentliche Assets (Logos sowie Objektfotos/Exposé-Bilder — Bilddateien,
  die der Portal-Feed anonym braucht) bleiben frei zugänglich.

Mieter-/Eigentümer-Portale liefern ihre Dokumente über eigene, auf
Eigentümerschaft geprüfte Download-Views (portal_dokument_download,
mieter_dokument_download) aus — nicht über diese /media/-URL. Deshalb genügt
hier die Team-Schranke, ohne die Portale zu brechen.

Hinweis Deployment: Auf PythonAnywhere darf /media/ NICHT als öffentliches
Static-Mapping konfiguriert sein, sonst umgeht der Webserver diesen View.
Sensible Uploads müssen durch Django (diesen View) laufen.
"""
import os
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import Http404, FileResponse
from django.utils._os import safe_join

from core.auth import hat_rolle, TEAM_ROLLEN

# Prefixe mit sensiblen Personendaten/Dokumenten — immer Login-pflichtig.
SENSIBLE_PREFIXE = (
    'bewerbungen/', 'kautions_zertifikate/', 'roh_vertraege/', 'vertraege_pdfs/',
    'nebenkosten_belege/', 'kreditoren_belege/', 'debitoren_rechnungen/',
    'ticket_anhang/', 'unterschriften/', 'abnahme_fotos/',
)
# Öffentliche Bild-Endungen (Objektfotos/Exposé — vom Portal-Feed anonym gebraucht).
# .svg bewusst NICHT enthalten: SVG kann eingebettetes JavaScript ausführen (Stored XSS),
# darf also nie inline und nie anonym ausgeliefert werden.
OEFFENTLICHE_BILD_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'}
OEFFENTLICHE_PREFIXE = ('logos/',)


def ist_oeffentlich(pfad):
    """True → Datei darf ohne Login ausgeliefert werden."""
    p = (pfad or '').lower().lstrip('/')
    if any(p.startswith(x) for x in SENSIBLE_PREFIXE):
        return False
    if any(p.startswith(x) for x in OEFFENTLICHE_PREFIXE):
        return True
    return os.path.splitext(p)[1] in OEFFENTLICHE_BILD_EXT


def geschuetzte_media(request, pfad):
    """Liefert eine Media-Datei aus — sensible Dateien nur für Team-Mitglieder."""
    try:
        vollpfad = safe_join(settings.MEDIA_ROOT, pfad)
    except (SuspiciousFileOperation, ValueError):
        raise Http404
    if not (os.path.exists(vollpfad) and os.path.isfile(vollpfad)):
        raise Http404
    if not ist_oeffentlich(pfad):
        u = getattr(request, 'user', None)
        if not (u and u.is_authenticated and hat_rolle(u, TEAM_ROLLEN)):
            raise Http404   # kein Existenz-Leak (404 statt 403)
    resp = FileResponse(open(vollpfad, 'rb'))
    # SVG kann Skripte enthalten → nie inline rendern (XSS-Schutz), immer als Download
    # und ohne MIME-Sniffing ausliefern.
    if os.path.splitext(pfad.lower())[1] == '.svg':
        resp['Content-Type'] = 'image/svg+xml'
        resp['Content-Disposition'] = 'attachment'
        resp['X-Content-Type-Options'] = 'nosniff'
    return resp
