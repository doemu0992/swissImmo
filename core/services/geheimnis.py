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

Es gibt keine Hintertür, das ist der Sinn. Wer `IMAP_SCHLUESSEL` verliert,
richtet jedes Postfach neu ein. Der Schlüssel gehört deshalb an dieselbe Stelle
und in dieselbe Sorgfalt wie das Datenbankpasswort — samt einer Kopie
ausserhalb des Servers.
"""
import os

from django.conf import settings

#: Name der Umgebungsvariablen. Auch in `.env.example` und `SICHERUNG.md`.
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
    # `settings` zuerst: Tests setzen ihn per `override_settings`, ohne die
    # Umgebung des laufenden Prozesses anzufassen.
    aus_settings = getattr(settings, UMGEBUNGSNAME, None)
    return (aus_settings or os.getenv(UMGEBUNGSNAME, '') or '').strip()


def _fernet():
    from cryptography.fernet import Fernet

    roh = _roh_schluessel()
    if not roh:
        raise SchluesselFehlt(
            f'{UMGEBUNGSNAME} ist nicht gesetzt. Ohne diesen Schlüssel lassen sich '
            'Postfach-Zugangsdaten weder speichern noch lesen. Erzeugen mit:\n'
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"\n'
            f'und als {UMGEBUNGSNAME}=… in die .env eintragen, dann Web-App neu laden.')
    try:
        return Fernet(roh.encode())
    except Exception as fehler:                                # noqa: BLE001
        raise SchluesselFehlt(
            f'{UMGEBUNGSNAME} ist gesetzt, aber kein gültiger Fernet-Schlüssel '
            f'({fehler}). Erwartet werden 44 Zeichen Base64 — beim Kopieren geht '
            'gern ein Zeilenumbruch mitten hinein.') from fehler


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
            f'{UMGEBUNGSNAME} nicht lesen. Häufigster Grund: Der Schlüssel wurde '
            'gewechselt. Die betroffenen Zugangsdaten müssen neu eingegeben '
            'werden — entschlüsseln lassen sie sich nicht mehr.') from fehler
