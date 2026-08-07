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
    # Diese vier lagen bis zur Trennung der Upload-Ordner alle in `uploads/`
    # und damit — als Bilddatei — anonym abrufbar: Fotos aus der Wohnung des
    # Mieters (Schadenmeldung), eingescannte Verträge und Korrespondenz,
    # Unterhaltsbelege, Innenaufnahmen der Ausstattung.
    'schaden_fotos/', 'dokumente/', 'unterhalt_belege/', 'ausstattung_fotos/',
    # Der Alt-Topf: Was da liegt, ist nicht mehr unterscheidbar — deshalb
    # geschützt. Ausnahme sind Objektfotos, siehe `ist_objektfoto`.
    'uploads/',
)
# Öffentliche Bild-Endungen (Objektfotos/Exposé — vom Portal-Feed anonym gebraucht).
# .svg bewusst NICHT enthalten: SVG kann eingebettetes JavaScript ausführen (Stored XSS),
# darf also nie inline und nie anonym ausgeliefert werden.
OEFFENTLICHE_BILD_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'}
OEFFENTLICHE_PREFIXE = ('logos/', 'objekt_fotos/')


def ist_oeffentlich(pfad):
    """True → Datei darf ohne Login ausgeliefert werden."""
    p = (pfad or '').lower().lstrip('/')
    if any(p.startswith(x) for x in SENSIBLE_PREFIXE):
        return False
    if any(p.startswith(x) for x in OEFFENTLICHE_PREFIXE):
        return True
    return os.path.splitext(p)[1] in OEFFENTLICHE_BILD_EXT


def ist_objektfoto(pfad):
    """Gehört dieser Alt-Pfad zu einem Objektfoto? Dann anonym ausliefern.

    Vor der Trennung der Upload-Ordner lagen Inserat-Fotos im selben `uploads/`
    wie Schadenfotos und gescannte Dokumente. Der Ordner ist deshalb jetzt
    geschützt — sonst blieben Wohnungsaufnahmen fremder Mieter frei abrufbar.
    Damit bereits veröffentlichte Inserate nicht ins Leere laufen, wird für
    Alt-Pfade in der Datenbank nachgesehen: Ist die Datei ein `EinheitFoto`,
    ist sie fürs Inserat gedacht und bleibt öffentlich. Eine Abfrage je Bild,
    und nur für den Alt-Ordner."""
    p = (pfad or '').lstrip('/')
    if not p.startswith('uploads/'):
        return False
    try:
        from portfolio.models import EinheitFoto
        return EinheitFoto.objects.filter(bild=p).exists()
    except Exception:
        return False


# Nur diese Endungen werden inline ausgeliefert. Alles andere geht als
# Download (attachment) raus — HTML, XML, SVG können im App-Origin Skript
# ausführen; ein hochgeladener «Beleg» rechnung.html liefe sonst als
# Stored XSS gegen das nächste Team-Mitglied, das ihn öffnet.
INLINE_ERLAUBT = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif', '.pdf'}


def geschuetzte_media(request, pfad):
    """Liefert eine Media-Datei aus — sensible Dateien nur für Team-Mitglieder."""
    try:
        vollpfad = safe_join(settings.MEDIA_ROOT, pfad)
    except (SuspiciousFileOperation, ValueError):
        raise Http404
    if not (os.path.exists(vollpfad) and os.path.isfile(vollpfad)):
        raise Http404

    # KRITISCH: Über die Sensibilität entscheidet der AUFGELÖSTE Pfad, nicht die
    # rohe URL. Sonst reicht ein vorangestelltes «%2e/» (oder «x/../»): Die rohe
    # Zeichenkette beginnt dann nicht mehr mit «schaden_fotos/», die Sensibel-
    # Prüfung greift nicht, die Bildendung gilt als «öffentlich» — und safe_join
    # normalisiert den Umweg gleich wieder weg und öffnet die echte, sensible
    # Datei. Entscheidung und Auslieferung müssen denselben Pfad meinen.
    rel = os.path.relpath(vollpfad, settings.MEDIA_ROOT).replace(os.sep, '/')

    if not (ist_oeffentlich(rel) or ist_objektfoto(rel)):
        u = getattr(request, 'user', None)
        if not (u and u.is_authenticated and hat_rolle(u, TEAM_ROLLEN)):
            raise Http404   # kein Existenz-Leak (404 statt 403)

    resp = FileResponse(open(vollpfad, 'rb'))
    endung = os.path.splitext(rel.lower())[1]
    if endung == '.svg':
        resp['Content-Type'] = 'image/svg+xml'
    if endung not in INLINE_ERLAUBT:
        # Nie inline rendern (XSS-Schutz), immer als Download, kein MIME-Sniffing.
        resp['Content-Disposition'] = 'attachment'
        resp['X-Content-Type-Options'] = 'nosniff'
    return resp
