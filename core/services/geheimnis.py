"""Geheimnisse verschlüsselt in der Datenbank ablegen — Fernet, Schlüssel aussen.

WOFÜR DAS DA IST

Postfach-Passwörter und OAuth2-Refresh-Tokens wandern mit dem Umbau «ein
Postfach je Verwaltung» aus Umgebungsvariablen in die Datenbank. Damit stünden
sie in jedem `pg_dump` und in jeder Sicherung. Dieses Modul verschlüsselt sie
vorher.

WAS ES LEISTET — UND WAS NICHT

**Schutz** gegen einen abhandengekommenen Datenbankauszug: eine kopierte
Sicherung, ein `pg_dump` auf einem falschen Datenträger, ein Zugang zur
Datenbank ohne Zugang zum Dateisystem.

**Kein Schutz** gegen jemanden, der auf dem Server ist. Dort liegt der
Schlüssel in der `.env` daneben. Das ist kein Einwand gegen das Verfahren, aber
es steht hier, damit später niemand mehr Sicherheit annimmt, als da ist.

WARUM NICHT AUS DEM `SECRET_KEY` ABGELEITET

Der `SECRET_KEY` signiert Sitzungen und Token; er wird bei Verdacht gewechselt,
und ein Wechsel soll nur Anmeldungen kosten. Wäre er auch der
Verschlüsselungsschlüssel, machte jeder Wechsel sämtliche Postfachzugänge
unlesbar — man wechselte ihn dann im Zweifel nicht.

DER PREIS: SCHLÜSSEL WEG HEISST ZUGÄNGE WEG

Es gibt keine Hintertür, das ist der Sinn. Wer `GEHEIMNIS_SCHLUESSEL` (früher
`IMAP_SCHLUESSEL`) verliert, richtet jedes Postfach neu ein und verliert die AHV-Nummern. Der Schlüssel gehört deshalb an dieselbe Stelle
und in dieselbe Sorgfalt wie das Datenbankpasswort — samt einer Kopie
ausserhalb des Servers.
"""
import os
import re

from django.conf import settings

#: Name der Einstellung/Umgebungsvariablen (seit 07.11.2026). Es dürfen MEHRERE Schlüssel stehen, durch Komma
#: oder Zeilenumbruch getrennt: Der erste verschlüsselt, alle entschlüsseln — so lässt sich ein Schlüssel
#: wechseln, ohne etwas zu verlieren (`manage.py schluessel_wechseln`).
NEUER_NAME = 'GEHEIMNIS_SCHLUESSEL'
#: Alternativ eine Datei, die den Schlüssel (bzw. die Schlüssel) enthält — ausserhalb von `.env` und Webroot,
#: mit Rechten nur für den Betriebsbenutzer (Muster «_FILE» von Docker-Secrets, systemd-Credentials).
DATEINAME = 'GEHEIMNIS_SCHLUESSEL_DATEI'
#: Ohne jede Angabe legt die Anwendung den Schlüssel selbst an (Datei neben der Anwendung, nur für den Betriebsbenutzer
#: lesbar, nicht in Git und nicht in der Datenbank) — wie sie es mit dem `SECRET_KEY` auch tut. Niemand muss ein Terminal
#: öffnen. Abschaltbar mit `GEHEIMNIS_AUTOSCHLUESSEL=False` (dann gilt: Schlüssel fehlt = Fehler).
AUTO_EINSTELLUNG = 'GEHEIMNIS_AUTOSCHLUESSEL'
AUTO_DATEI_EINSTELLUNG = 'GEHEIMNIS_AUTOSCHLUESSEL_DATEI'
#: Der alte Name: gilt weiter, damit nichts bricht. Der Name stammt aus der Zeit, als nur IMAP-Postfächer
#: den Schlüssel brauchten; heute schützt er auch AHV-Nummern (und demnächst die 2FA-Geheimnisse).
UMGEBUNGSNAME = 'IMAP_SCHLUESSEL'


class SchluesselFehlt(Exception):
    """Der Schlüssel ist nicht gesetzt — und ohne ihn geht hier nichts.

    Bewusst eine eigene Ausnahme: Die Aufrufer sollen diesen Fall von einem
    kaputten Geheimtext unterscheiden können. Das eine ist ein Betriebsfehler
    (jemand hat die `.env` nicht ergänzt), das andere ein Datenfehler.
    """


class GeheimtextKaputt(Exception):
    """Der gespeicherte Wert lässt sich mit diesem Schlüssel nicht lesen.

    Häufigster Grund im Betrieb: Der Schlüssel wurde gewechselt, ohne die
    gespeicherten Werte neu zu setzen.
    """


def schluessel_vorhanden() -> bool:
    """Ohne Ausnahme prüfen — für Startchecks und die Oberfläche."""
    return bool(_roh_schluessel())


def _roh_schluessel() -> str:
    """Die Schlüssel als ein Text (mehrere getrennt durch Komma/Zeilenumbruch); leer, wenn keiner gesetzt ist.

    Reihenfolge: `settings` zuerst (Tests setzen ihn per `override_settings`, ohne die Umgebung des laufenden
    Prozesses anzufassen), dann Umgebungsvariable, dann Schlüsseldatei; der neue Name vor dem alten."""
    for name in (NEUER_NAME, UMGEBUNGSNAME):
        wert = getattr(settings, name, None)
        if wert:
            return str(wert).strip()
    wert = os.getenv(NEUER_NAME, '')
    if wert.strip():
        return wert.strip()
    datei = os.getenv(DATEINAME, '').strip()
    if datei:
        try:
            with open(datei, encoding='utf-8') as f:
                inhalt = f.read().strip()
        except OSError as fehler:
            raise SchluesselFehlt(f'{DATEINAME}={datei} lässt sich nicht lesen ({fehler.strerror or fehler}).') from fehler
        if inhalt:
            return inhalt
    alt = (os.getenv(UMGEBUNGSNAME, '') or '').strip()
    return alt or _autoschluessel()


def autoschluessel_pfad():
    from pathlib import Path
    return Path(getattr(settings, AUTO_DATEI_EINSTELLUNG, None) or (Path(settings.BASE_DIR) / '.geheimnis_schluessel'))


def _autoschluessel() -> str:
    """Der selbst angelegte Schlüssel: vorhandene Datei lesen, sonst (falls erlaubt) atomar anlegen.

    `O_CREAT|O_EXCL`: Starten zwei Prozesse gleichzeitig, gewinnt genau einer; der andere liest dessen Datei. So
    entstehen nie zwei verschiedene Schlüssel. Lässt sich die Datei nicht anlegen (schreibgeschütztes Dateisystem),
    bleibt es beim «Schlüssel fehlt» — mit klarer Meldung, nie mit einem Schlüssel, der den nächsten Start nicht überlebt."""
    if not getattr(settings, AUTO_EINSTELLUNG, True):
        return ''                                # abgeschaltet heisst: auch eine vorhandene Datei bleibt aussen vor
    pfad = autoschluessel_pfad()
    try:
        inhalt = pfad.read_text(encoding='utf-8').strip()
        if inhalt:
            return inhalt
    except OSError:
        pass
    from cryptography.fernet import Fernet
    neu = Fernet.generate_key().decode()
    try:
        fd = os.open(str(pfad), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:                      # ein anderer Prozess war schneller: dessen Schlüssel gilt
        try:
            return pfad.read_text(encoding='utf-8').strip()
        except OSError:
            return ''
    except OSError:
        return ''
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(neu + '\n')
    return neu


def schluessel_quelle() -> str:
    """Woher der Schlüssel kommt: 'einstellung', 'umgebung', 'datei', 'automatisch' oder '' (keiner)."""
    for name in (NEUER_NAME, UMGEBUNGSNAME):
        if getattr(settings, name, None):
            return 'einstellung'
    if os.getenv(NEUER_NAME, '').strip() or os.getenv(UMGEBUNGSNAME, '').strip():
        return 'umgebung'
    if os.getenv(DATEINAME, '').strip():
        return 'datei'
    return 'automatisch' if _autoschluessel() else ''


def _schluesselliste() -> list:
    return [s for s in re.split(r'[,\s]+', _roh_schluessel()) if s]


def _fernet():
    """Ein `MultiFernet` über alle Schlüssel: verschlüsselt mit dem ersten, entschlüsselt mit jedem."""
    from cryptography.fernet import Fernet, MultiFernet

    schluessel = _schluesselliste()
    if not schluessel:
        raise SchluesselFehlt(
            f'{NEUER_NAME} (früher {UMGEBUNGSNAME}) ist nicht gesetzt. Ohne diesen Schlüssel lassen sich '
            'Zugangsdaten und AHV-Nummern weder speichern noch lesen. Erzeugen mit:\n'
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"\n'
            f'und als {NEUER_NAME}=… in die .env eintragen (oder als Datei: {DATEINAME}=/pfad), '
            'dann Web-App neu laden.')
    fernets = []
    for i, roh in enumerate(schluessel, start=1):
        try:
            fernets.append(Fernet(roh.encode()))
        except Exception as fehler:                            # noqa: BLE001
            raise SchluesselFehlt(
                f'{NEUER_NAME} (früher {UMGEBUNGSNAME}): Schlüssel {i} ist kein gültiger Fernet-Schlüssel '
                f'({fehler}). Erwartet werden 44 Zeichen Base64 — beim Kopieren geht '
                'gern ein Zeilenumbruch mitten hinein.') from fehler
    return MultiFernet(fernets)


def neu_verschluesseln(geheimtext: str) -> str:
    """Einen Geheimtext, der mit IRGENDEINEM der Schlüssel lesbar ist, mit dem ERSTEN neu verschlüsseln."""
    from cryptography.fernet import InvalidToken
    if not geheimtext:
        return ''
    try:
        return _fernet().rotate(str(geheimtext).encode()).decode()
    except InvalidToken as fehler:
        raise GeheimtextKaputt('Mit keinem der gesetzten Schlüssel lesbar.') from fehler


def mit_erstem_schluessel_lesbar(geheimtext: str) -> bool:
    """True, wenn der Geheimtext schon mit dem ersten (aktuellen) Schlüssel entschlüsselt werden kann."""
    from cryptography.fernet import Fernet, InvalidToken
    liste = _schluesselliste()
    if not geheimtext or not liste:
        return False
    try:
        Fernet(liste[0].encode()).decrypt(str(geheimtext).encode())
        return True
    except (InvalidToken, ValueError):
        return False


def verschluesseln(klartext: str) -> str:
    """Klartext → Geheimtext. Leeres bleibt leer.

    Leer bleibt leer, damit «kein Passwort gesetzt» sich von «Passwort ist der
    leere String» unterscheidet — sonst könnte ein Formular durch bloss
    Absenden ein Geheimnis anlegen, das aussieht wie eines.
    """
    if not klartext:
        return ''
    return _fernet().encrypt(str(klartext).encode()).decode()


def entschluesseln(geheimtext: str) -> str:
    """Geheimtext → Klartext. Leeres bleibt leer."""
    from cryptography.fernet import InvalidToken

    if not geheimtext:
        return ''
    try:
        return _fernet().decrypt(str(geheimtext).encode()).decode()
    except InvalidToken as fehler:
        raise GeheimtextKaputt(
            'Der gespeicherte Wert lässt sich mit dem aktuellen '
            f'{NEUER_NAME} (früher {UMGEBUNGSNAME}) nicht lesen. Häufigster Grund: Der Schlüssel wurde '
            'gewechselt. Die betroffenen Zugangsdaten müssen neu eingegeben '
            'werden — entschlüsseln lassen sie sich nicht mehr.') from fehler
