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


def ohne_organisationspraefix(pfad):
    """`organisation/7/schaden_fotos/…` → `schaden_fotos/…`.

    WARUM DAS EINE EIGENE FUNKTION IST: Die Sensibilität wird am ORDNER
    abgelesen (`schaden_fotos/`, `dokumente/`, …). Das Präfix aus Etappe 6.5
    schiebt sich davor — ohne dieses Abziehen begönne kein Pfad mehr mit einem
    sensiblen Ordner, die Prüfung liefe ins Leere, und jedes Bild wäre über
    seine Endung anonym abrufbar. Also auch Wohnungsaufnahmen aus
    Schadenmeldungen.

    Gefunden von `test_fremder_bekommt_schadenfoto_nicht`, unmittelbar nachdem
    das Präfix eingeführt war.
    """
    teile = (pfad or '').lstrip('/').split('/')
    if len(teile) >= 3 and teile[0] == 'organisation' and teile[1].isdigit():
        return '/'.join(teile[2:])
    return (pfad or '').lstrip('/')


def ist_oeffentlich(pfad):
    """True → Datei darf ohne Login ausgeliefert werden."""
    p = ohne_organisationspraefix(pfad).lower()
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
    p = ohne_organisationspraefix(pfad)
    if not p.startswith('uploads/'):
        return False
    # `alle_organisationen`: Die Frage lautet «ist dieser PFAD ein Inseratfoto»,
    # nicht «gehoert er mir» — die Antwort haengt nicht von einer Verwaltung ab,
    # und der Aufrufer ist ein anonymer Besucher ohne Kontext. Ueber `objects`
    # warf die Zeile seit Etappe 6.2, das `except` verschluckte es, und die
    # Funktion sagte fuer JEDES Alt-Bild `False`. Damit lief genau die Zusage
    # ins Leere, die der Docstring gibt (Audit 18.08.2026).
    from portfolio.models import EinheitFoto
    return EinheitFoto.alle_organisationen.filter(bild=p).exists()


#: Modelle, deren Dateifelder geprüft werden müssen — aus der Registry, nicht
#: abgetippt. Ein neues Dateifeld ist damit automatisch mit abgedeckt.
def _dateifelder():
    from django.apps import apps
    from django.db import models as _m
    for modell in apps.get_models():
        for feld in modell._meta.get_fields():
            if isinstance(feld, _m.FileField):
                yield modell, feld.name


def organisation_id_der_datei(rel):
    """Wem gehört diese Datei? Gibt die Organisations-ID zurück oder `None`.

    ZWEI WEGE, und der erste ist der schnelle:

    1. **Am Pfad.** Seit Etappe 6.5 liegen neue Dateien unter
       `organisation/<id>/…`. Das kostet keine Abfrage.
    2. **In der Datenbank.** Für den Alt-Bestand — dieselbe Technik, die
       `ist_objektfoto` schon für Objektfotos benutzt: nachsehen, welcher
       Datensatz auf diese Datei zeigt, und dessen Organisation nehmen.

    `None` heisst „nicht bestimmbar". Der Aufrufer behandelt das als **nicht
    freigegeben** — bei einer Datei, deren Zugehörigkeit niemand kennt, ist
    Verweigern die einzige vertretbare Antwort.
    """
    teile = (rel or '').split('/')
    if len(teile) >= 3 and teile[0] == 'organisation' and teile[1].isdigit():
        return int(teile[1])

    for modell, feldname in _dateifelder():
        try:
            treffer = (modell.alle_organisationen if hasattr(modell, 'alle_organisationen')
                       else modell._base_manager).filter(**{feldname: rel}).first()
        except Exception:
            continue
        if treffer is None:
            continue
        if type(treffer).__name__ == 'Organisation':
            return treffer.pk          # Logo/Unterschrift: sie IST der Mandant
        return getattr(treffer, 'organisation_id', None)
    return None


def gehoert_zur_eigenen_organisation(rel):
    """Darf die aktive Verwaltung diese Datei sehen?"""
    from core.tenancy import aktuelle_organisation

    eigene = aktuelle_organisation()
    if eigene is None:
        return False                   # ohne Kontext kein Zugriff auf Sensibles
    besitzer = organisation_id_der_datei(rel)
    return besitzer is not None and besitzer == eigene.pk


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

        # UND ZWAR AUS DER RICHTIGEN VERWALTUNG (Etappe 6.5).
        #
        # Bis hierher endete die Pruefung eine Zeile weiter oben: „ist im Team".
        # In WELCHEM Team, stand nirgends. Jedes angemeldete Team-Mitglied
        # konnte damit jede geschuetzte Datei abrufen, sofern es den Pfad kannte
        # — und die Pfade sind ratbar (Ordner, Datum, Dateiname). Betroffen sind
        # unter anderem Ausweiskopien, Betreibungsausz'uege und Lohnausweise von
        # Mietbewerbern.
        #
        # 404 statt 403, aus demselben Grund wie oben: Ein 403 bestaetigt, dass
        # die Datei existiert.
        if not gehoert_zur_eigenen_organisation(rel):
            raise Http404

    resp = FileResponse(open(vollpfad, 'rb'))
    endung = os.path.splitext(rel.lower())[1]
    if endung == '.svg':
        resp['Content-Type'] = 'image/svg+xml'
    if endung not in INLINE_ERLAUBT:
        # Nie inline rendern (XSS-Schutz), immer als Download, kein MIME-Sniffing.
        resp['Content-Disposition'] = 'attachment'
        resp['X-Content-Type-Options'] = 'nosniff'
    return resp
