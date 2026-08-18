"""Zeitbasierte Einmalcodes nach RFC 6238 (TOTP) — ohne zusätzliche Bibliothek.

WARUM SELBST GESCHRIEBEN UND NICHT `pyotp`

Weil es hier nichts zu erfinden gibt. RFC 4226 (HOTP) und RFC 6238 (TOTP)
beschreiben eine HMAC-Rechnung von rund zwanzig Zeilen — und, das ist der
eigentliche Grund, sie liefern **amtliche Testvektoren** mit: bekannte
Zeitpunkte mit bekannten Codes, für SHA-1, SHA-256 und SHA-512. Diese
Umsetzung ist damit gegen den Standard prüfbar, nicht bloss gegen sich selbst
(siehe `core/tests/test_totp.py`).

Der Gegenwert einer Abhängigkeit wäre gering, ihr Preis nicht: ein weiteres
Paket, das aktuell gehalten werden muss, in einem Projekt, dessen
Sicherheitsfläche gerade der Anmeldevorgang ist.

DEN QR-CODE ZEICHNET `segno` — das steht bereits in `requirements.txt` für die
Schweizer QR-Rechnung und muss nicht neu aufgenommen werden.

WAS HIER BEWUSST NICHT STEHT

Kein Zustand. Dieses Modul rechnet, es speichert nichts. Der Wiedergabeschutz
(ein Code darf nur EINMAL gelten) braucht Gedächtnis und gehört deshalb ins
Modell — siehe `core.models.ZweiterFaktor.pruefen`.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

#: Schrittweite in Sekunden. 30 ist der Wert, den Google Authenticator, 1Password,
#: Aegis und alle übrigen gängigen Apps voraussetzen — er ist nicht frei wählbar,
#: wenn fremde Apps die Codes erzeugen sollen.
SCHRITT = 30

#: Stellen des Codes. Ebenfalls durch die Apps vorgegeben.
STELLEN = 6

#: Wie viele Schritte Abweichung erlaubt sind, in beide Richtungen.
#: 1 bedeutet: Der Code des vorangehenden und des folgenden Fensters gilt auch
#: — zusammen also bis zu 90 Sekunden. Ohne diese Toleranz scheitert jeder
#: Nutzer, dessen Telefonuhr ein paar Sekunden abweicht, und zwar ohne dass
#: ihm jemand sagen könnte warum.
TOLERANZ = 1


def geheimnis_erzeugen(bytes_anzahl: int = 20) -> str:
    """Ein neues Geheimnis als Base32 (ohne Füllzeichen).

    20 Bytes = 160 Bit ist die Länge, die RFC 4226 für HMAC-SHA-1 nennt, und
    die Länge, die die Authenticator-Apps erwarten.
    """
    return base64.b32encode(secrets.token_bytes(bytes_anzahl)).decode('ascii').rstrip('=')


def _hotp(geheimnis_bytes: bytes, zaehler: int, stellen: int, hashfunktion) -> str:
    """HOTP nach RFC 4226, Abschnitt 5.3 — die Rechnung, auf der TOTP aufsitzt."""
    nachricht = struct.pack('>Q', zaehler)
    abzug = hmac.new(geheimnis_bytes, nachricht, hashfunktion).digest()
    # «Dynamic Truncation»: Die letzten vier Bit zeigen an, ab welchem Byte
    # gelesen wird. Das oberste Bit wird ausmaskiert, damit die Zahl auf jeder
    # Plattform gleich vorzeichenlos gelesen wird.
    versatz = abzug[-1] & 0x0F
    ausschnitt = struct.unpack('>I', abzug[versatz:versatz + 4])[0] & 0x7FFFFFFF
    return str(ausschnitt % (10 ** stellen)).zfill(stellen)


def _geheimnis_bytes(geheimnis: str) -> bytes:
    """Base32 zurück in Bytes — nachsichtig gegenüber der Schreibweise.

    Nutzer tippen Geheimnisse in Gruppen ab und lassen Füllzeichen weg. Wer
    hier streng ist, produziert Fehlermeldungen bei richtigen Eingaben.
    """
    # Vorhandene Füllzeichen erst entfernen: Sonst hängt die Ergänzung unten
    # weitere an ein bereits vollständiges Geheimnis und `b32decode` wirft
    # «Incorrect padding» — bei einer völlig richtigen Eingabe.
    sauber = geheimnis.strip().replace(' ', '').replace('-', '').upper().rstrip('=')
    sauber += '=' * (-len(sauber) % 8)
    return base64.b32decode(sauber, casefold=True)


def code(geheimnis: str, zeitpunkt: float | None = None, *,
         schritt: int = SCHRITT, stellen: int = STELLEN,
         hashfunktion=hashlib.sha1) -> str:
    """Der zum Zeitpunkt gültige Code."""
    jetzt = time.time() if zeitpunkt is None else zeitpunkt
    return _hotp(_geheimnis_bytes(geheimnis), int(jetzt // schritt), stellen, hashfunktion)


def zaehler_fuer(zeitpunkt: float | None = None, *, schritt: int = SCHRITT) -> int:
    """Die Fensternummer eines Zeitpunkts — der Wert, den der Wiedergabeschutz merkt."""
    jetzt = time.time() if zeitpunkt is None else zeitpunkt
    return int(jetzt // schritt)


def passendes_fenster(geheimnis: str, eingabe: str, zeitpunkt: float | None = None, *,
                      toleranz: int = TOLERANZ, schritt: int = SCHRITT,
                      stellen: int = STELLEN) -> int | None:
    """Nummer des Fensters, in dem `eingabe` gilt — oder `None`.

    Zurückgegeben wird die **Fensternummer**, nicht `True`: Nur damit kann der
    Aufrufer verhindern, dass derselbe Code ein zweites Mal durchgeht. Ein
    blosses «stimmt» würde einen abgefangenen Code 90 Sekunden lang gültig
    lassen.

    Verglichen wird mit `hmac.compare_digest`, also in gleichbleibender Zeit.
    Ein `==` auf Zeichenketten bricht beim ersten Unterschied ab und verrät
    über die Laufzeit, wie viele Stellen stimmten.
    """
    eingabe = (eingabe or '').strip().replace(' ', '')
    if not eingabe.isdigit() or len(eingabe) != stellen:
        return None
    jetzt = zaehler_fuer(zeitpunkt, schritt=schritt)
    roh = _geheimnis_bytes(geheimnis)
    for versatz in range(-toleranz, toleranz + 1):
        fenster = jetzt + versatz
        if fenster < 0:
            continue
        if hmac.compare_digest(_hotp(roh, fenster, stellen, hashlib.sha1), eingabe):
            return fenster
    return None


def einrichtungs_url(geheimnis: str, konto: str, herausgeber: str = 'swissImmo') -> str:
    """Die `otpauth://`-Adresse, die die Authenticator-App einliest.

    Das Format ist nicht in einer RFC festgehalten, sondern eine Festlegung
    von Google, der sich alle Apps angeschlossen haben. Der Herausgeber steht
    absichtlich **zweimal** darin — einmal im Pfad, einmal als Parameter:
    ältere Apps lesen nur das eine, neuere nur das andere.
    """
    label = quote(f'{herausgeber}:{konto}', safe='')
    return (f'otpauth://totp/{label}?secret={geheimnis}'
            f'&issuer={quote(herausgeber, safe="")}'
            f'&algorithm=SHA1&digits={STELLEN}&period={SCHRITT}')


def qr_svg(daten: str, *, groesse: int = 6) -> str:
    """Den QR-Code als SVG-Zeichenkette — zum direkten Einbetten ins Template.

    Bewusst SVG und keine Bilddatei: Das Geheimnis steckt im QR-Code. Als Datei
    auf der Platte läge es unverschlüsselt herum und wäre über die
    Medienauslieferung erreichbar; im Antwortkörper lebt es nur so lange wie
    die Seite.
    """
    import io

    import segno

    # `segno` schreibt SVG als Bytes, auch in einen Textpuffer — deshalb
    # BytesIO und einmal dekodieren, statt einen TypeError zu ernten.
    puffer = io.BytesIO()
    segno.make(daten, error='m').save(puffer, kind='svg', scale=groesse,
                                      xmldecl=False, svgns=True, omitsize=True)
    return puffer.getvalue().decode('utf-8')
