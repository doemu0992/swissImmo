"""Prüft, ob /media/ tatsächlich durch Django läuft.

Hintergrund: `core/views/media_protected.py` liefert sensible Uploads (Fotos aus
Mieterwohnungen, gescannte Verträge, Belege) nur an eingeloggte Team-Mitglieder
aus. Diese Schranke steht und fällt damit, dass die /media/-URL überhaupt bei
Django ankommt. Ist /media/ beim Hoster als statisches Verzeichnis gemappt,
liefert der Webserver die Dateien direkt aus und der View wird nie aufgerufen —
der Schutz ist dann vollständig wirkungslos, ohne dass irgendetwas auffällt.

Aus dem Code heraus lässt sich das nicht feststellen; die Zuordnung steht in der
Hoster-Konfiguration. Deshalb dieser Test von aussen: Es wird kurzzeitig eine
Kanarienvogel-Datei unter einem geschützten Prefix abgelegt und ohne Anmeldung
über ihre öffentliche URL abgerufen. Kommt der Dateiinhalt zurück, umgeht der
Webserver Django.

Aufruf:  python manage.py pruefe_media_schutz
         python manage.py pruefe_media_schutz --url https://example.ch
Läuft automatisch am Ende von deploy.sh.

Rückgabecodes: 0 = geschützt oder nicht prüfbar, 2 = Datei war anonym abrufbar.
"""
import os
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand

# Bewusst unter einem geschützten Prefix und mit Bild-Endung: genau die
# Kombination, die vor der Ordnertrennung anonym abrufbar war. Für Django ist
# der Pfad tabu — wer die Datei trotzdem bekommt, hat Django umgangen.
KANARIENVOGEL_PFAD = 'schaden_fotos/zzz-deploy-kanarienvogel.png'

# Kleinstes gültiges PNG (1×1, transparent) plus eine eindeutige Markierung, an
# der sich der Inhalt zweifelsfrei wiedererkennen lässt.
KANARIENVOGEL_INHALT = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
    b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    b'\n<<swissimmo-media-kanarienvogel>>'
)


def _hole(url, timeout=15):
    """Ruft `url` ohne Anmeldung ab. Gibt (status, koerper) zurück.

    (None, None), wenn die Adresse gar nicht erreichbar war — das ist kein
    Befund, sondern schlicht keine Aussage."""
    anfrage = urllib.request.Request(url, headers={'User-Agent': 'swissimmo-media-check'})
    try:
        with urllib.request.urlopen(anfrage, timeout=timeout) as antwort:
            return antwort.status, antwort.read(4096)
    except urllib.error.HTTPError as fehler:
        # 404/403 sind der erwartete Normalfall — Django hat abgelehnt.
        try:
            koerper = fehler.read(4096)
        except Exception:
            koerper = b''
        return fehler.code, koerper
    except Exception:
        return None, None


def _basis_url(vorgabe=None):
    """Öffentliche Basis-Adresse dieser Installation."""
    if vorgabe:
        return vorgabe.rstrip('/')
    aus_umgebung = os.getenv('MEDIA_CHECK_URL', '').strip()
    if aus_umgebung:
        return aus_umgebung.rstrip('/')
    for host in getattr(settings, 'ALLOWED_HOSTS', []):
        if host in ('127.0.0.1', 'localhost', '*') or host.startswith('.'):
            continue
        return f'https://{host}'
    return None


class Command(BaseCommand):
    help = ("Prüft von aussen, ob geschützte Media-Dateien ohne Anmeldung "
            "abrufbar sind (Webserver umgeht Django).")

    def add_arguments(self, parser):
        parser.add_argument('--url', default=None,
                            help='Basis-Adresse, z.B. https://example.ch '
                                 '(sonst MEDIA_CHECK_URL oder ALLOWED_HOSTS).')
        parser.add_argument('--timeout', type=int, default=15,
                            help='Zeitlimit je Abruf in Sekunden (Standard 15).')

    def handle(self, *args, **opts):
        basis = _basis_url(opts.get('url'))
        if not basis:
            self.stdout.write("⚠ Keine öffentliche Adresse bekannt — Prüfung übersprungen.")
            self.stdout.write("  Mit --url oder MEDIA_CHECK_URL nachreichen.")
            return

        vollpfad = os.path.join(settings.MEDIA_ROOT, KANARIENVOGEL_PFAD)
        os.makedirs(os.path.dirname(vollpfad), exist_ok=True)
        with open(vollpfad, 'wb') as datei:
            datei.write(KANARIENVOGEL_INHALT)

        url = f"{basis}{settings.MEDIA_URL}{KANARIENVOGEL_PFAD}"
        try:
            status, koerper = _hole(url, opts.get('timeout') or 15)
        finally:
            # Die Testdatei darf unter keinen Umständen liegen bleiben.
            try:
                os.remove(vollpfad)
            except OSError:
                pass

        if status is None:
            self.stdout.write(f"⚠ {url} nicht erreichbar — Media-Schutz nicht geprüft.")
            return

        # Entscheidend ist der Inhalt, nicht der Status: Eine Weiterleitung auf
        # die Anmeldeseite endet ebenfalls mit 200, liefert aber etwas anderes.
        if koerper and KANARIENVOGEL_INHALT[:32] in koerper:
            self.stderr.write("")
            self.stderr.write("✗ MEDIA-SCHUTZ WIRKUNGSLOS")
            self.stderr.write(f"  {url}")
            self.stderr.write("  wurde ohne Anmeldung ausgeliefert (HTTP %s)." % status)
            self.stderr.write("  Der Webserver liefert /media/ direkt aus und umgeht Django.")
            self.stderr.write("  Damit sind Schadenfotos aus Mieterwohnungen, gescannte")
            self.stderr.write("  Verträge und Belege für jeden mit der URL abrufbar.")
            self.stderr.write("  → Beim Hoster das statische Mapping für /media/ entfernen,")
            self.stderr.write("    damit die Anfragen wieder durch Django laufen.")
            self.stderr.write("")
            raise SystemExit(2)

        self.stdout.write(f"✓ Media-Schutz aktiv — geschützte Datei blieb verwehrt (HTTP {status}).")
