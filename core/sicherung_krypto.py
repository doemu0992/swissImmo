"""Verschlüsselung und Aufbewahrung der Ausser-Haus-Sicherung (Roadmap Nr. 12).

VERSCHLÜSSELUNG
    AES-256-GCM in Blöcken von 1 MiB, Schlüssel aus einer Passphrase per scrypt
    (frisches Salz je Datei). Jeder Block ist einzeln authentisiert; die Blocknummer
    und die Kennung «letzter Block» stehen im AAD. So fällt auf, wenn jemand Blöcke
    vertauscht, auslässt oder die Datei abschneidet. Passphrase aus der Umgebung
    (`SICHERUNG_SCHLUESSEL`), nie im Code und nie auf der Kommandozeile.

    Dateiformat: MAGIC | Salz(16) | Nonce-Präfix(8) | { Länge(4) | Block }*

AUFBEWAHRUNG
    Nach OR 958f sind Geschäftsbücher zehn Jahre aufzubewahren. `gfs_behalten`
    wählt aus den Zeitstempeln der Stände aus: die jüngsten N (täglich), je Monat
    der letzte der letzten M Monate, je Jahr der letzte der letzten J Jahre.
    Alles andere darf weg. Gelöscht wird nur, was ein Stempel im Namen trägt.
"""
import os
import struct
from datetime import datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b'SWSB1\n'
BLOCK = 1024 * 1024
_SCRYPT = dict(length=32, n=2 ** 15, r=8, p=1)


class SicherungsFehler(Exception):
    """Falsche Passphrase, beschädigte oder abgeschnittene Datei."""


def _schluessel(passphrase, salz):
    if not passphrase:
        raise SicherungsFehler('Keine Passphrase angegeben.')
    return Scrypt(salt=salz, **_SCRYPT).derive(passphrase.encode('utf-8'))


def _nonce(praefix, zaehler):
    return praefix + struct.pack('>I', zaehler)


def _aad(zaehler, letzter):
    return struct.pack(">I?", zaehler, letzter)


def verschluesseln(quelle, ziel, passphrase):
    """Verschlüsselt die Datei `quelle` nach `ziel`. Gibt die Anzahl Klartext-Bytes zurück."""
    salz, praefix = os.urandom(16), os.urandom(8)
    aes = AESGCM(_schluessel(passphrase, salz))
    gesamt = 0
    with open(quelle, 'rb') as ein, open(ziel, 'wb') as aus:
        aus.write(MAGIC + salz + praefix)
        zaehler = 0
        block = ein.read(BLOCK)
        while True:
            naechster = ein.read(BLOCK)
            letzter = not naechster
            roh = aes.encrypt(_nonce(praefix, zaehler), block, _aad(zaehler, letzter))
            aus.write(struct.pack('>I', len(roh)) + roh)
            gesamt += len(block)
            if letzter:
                break
            block, zaehler = naechster, zaehler + 1
    return gesamt


def entschluesseln(quelle, ziel, passphrase):
    """Entschlüsselt `quelle` nach `ziel`. Wirft `SicherungsFehler` bei falscher Passphrase oder Beschädigung."""
    gesamt = 0
    with open(quelle, 'rb') as ein:
        kopf = ein.read(len(MAGIC) + 24)
        if len(kopf) < len(MAGIC) + 24 or not kopf.startswith(MAGIC):
            raise SicherungsFehler('Keine Sicherungsdatei dieses Formats.')
        salz, praefix = kopf[len(MAGIC):len(MAGIC) + 16], kopf[len(MAGIC) + 16:]
        aes = AESGCM(_schluessel(passphrase, salz))
        try:
            with open(ziel, 'wb') as aus:
                zaehler = 0
                while True:
                    laenge_roh = ein.read(4)
                    if len(laenge_roh) < 4:
                        raise SicherungsFehler('Datei abgeschnitten (letzter Block fehlt).')
                    (laenge,) = struct.unpack('>I', laenge_roh)
                    roh = ein.read(laenge)
                    if len(roh) < laenge:
                        raise SicherungsFehler('Datei abgeschnitten.')
                    letzter = ein.read(1) == b''
                    if not letzter:
                        ein.seek(-1, os.SEEK_CUR)
                    try:
                        klar = aes.decrypt(_nonce(praefix, zaehler), roh, _aad(zaehler, letzter))
                    except InvalidTag:
                        raise SicherungsFehler(
                            'Entschlüsseln fehlgeschlagen: falsche Passphrase oder beschädigte Datei.') from None
                    aus.write(klar)
                    gesamt += len(klar)
                    if letzter:
                        break
                    zaehler += 1
        except SicherungsFehler:
            try:
                os.unlink(ziel)
            except OSError:
                pass
            raise
    return gesamt


def stempel_von(name):
    """Der Zeitstempel (`YYYYMMDD-HHMMSS`) am Anfang eines Dateinamens, sonst None."""
    try:
        return datetime.strptime(name[:15], '%Y%m%d-%H%M%S')
    except ValueError:
        return None


def gfs_behalten(stempel, taeglich=14, monate=12, jahre=10):
    """Welche Stände bleiben? `stempel`: Liste von `datetime`. Gibt die Menge der zu behaltenden zurück.

    Die jüngsten `taeglich` Stände; je Kalendermonat der letzte, soweit der Monat innerhalb der
    letzten `monate` Monate liegt; je Kalenderjahr der letzte, soweit das Jahr innerhalb der letzten
    `jahre` Jahre liegt. Gemessen wird vom NEUESTEN Stand aus, nicht von der Anzahl vorhandener
    Monate/Jahre: Lücken verlängern die Aufbewahrung nicht über die Frist hinaus.
    """
    sortiert = sorted(stempel, reverse=True)
    if not sortiert:
        return set()
    behalten = set(sortiert[:taeglich])
    neuester = sortiert[0]
    je_monat, je_jahr = {}, {}
    for s in sortiert:                              # jüngster zuerst: erster Treffer = letzter Stand
        je_monat.setdefault((s.year, s.month), s)
        je_jahr.setdefault(s.year, s)
    monatsnummer_neu = neuester.year * 12 + neuester.month
    for (jahr, monat), stand in je_monat.items():
        if monatsnummer_neu - (jahr * 12 + monat) < monate:
            behalten.add(stand)
    for jahr, stand in je_jahr.items():
        if neuester.year - jahr < jahre:
            behalten.add(stand)
    return behalten
