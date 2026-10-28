"""IBAN-Validierung (Format + Mod-97-Prüfsumme, ISO 13616), QR-IBAN-Kennung und
Prüfziffer der QR-Referenz."""

_LEN = {  # erwartete Gesamtlänge je Land (Auswahl, Schweiz relevant)
    'CH': 21, 'LI': 21, 'DE': 22, 'AT': 20, 'FR': 27, 'IT': 27, 'LU': 20,
}


def normalisiere_iban(iban):
    # `split()` entfernt jede Art Leerraum, auch das geschützte Leerzeichen aus
    # kopierten PDF-Texten.
    return ''.join((iban or '').split()).replace('-', '').upper()


def ist_gueltige_iban(iban):
    """True, wenn die IBAN formal (Länge, Zeichen) und per Mod-97 gültig ist."""
    s = normalisiere_iban(iban)
    # ASCII und höchstens 34 Stellen (ISO 13616): `isalnum`/`isdigit` allein
    # liessen auch «٣» oder «ä» durch.
    if len(s) < 5 or len(s) > 34 or not s.isascii():
        return False
    if not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    if not s.isalnum():
        return False
    land = s[:2]
    if land in _LEN and len(s) != _LEN[land]:
        return False
    # Umstellen: die ersten 4 Zeichen ans Ende
    rearranged = s[4:] + s[:4]
    # Buchstaben in Zahlen (A=10 … Z=35)
    ziffern = ''
    for ch in rearranged:
        if ch.isdigit():
            ziffern += ch
        else:
            ziffern += str(ord(ch) - 55)
    try:
        return int(ziffern) % 97 == 1
    except ValueError:
        return False


def formatiere_iban(iban):
    """Gibt die IBAN in 4er-Gruppen zurück (z.B. 'CH93 0076 2011 …')."""
    s = normalisiere_iban(iban)
    return ' '.join(s[i:i + 4] for i in range(0, len(s), 4))


def ist_qr_iban(iban):
    """QR-IBAN: CH- oder LI-IBAN, deren Institutskennung (Stellen 5-9) im
    Bereich 30000-31999 liegt (QR-Rechnung, Implementation Guidelines).

    Prüft nur die Kennung, nicht die Prüfsumme: Wer wissen will, ob die IBAN
    überhaupt gültig ist, fragt zusätzlich `ist_gueltige_iban`."""
    s = normalisiere_iban(iban)
    if len(s) != 21 or s[:2] not in ('CH', 'LI') or not s[4:9].isdigit():
        return False
    return 30000 <= int(s[4:9]) <= 31999


_QRR_UEBERTRAG = (0, 9, 4, 6, 8, 2, 7, 1, 3, 5)


def qrr_pruefziffer_ok(referenz):
    """QR-Referenz: genau 27 Ziffern, letzte Stelle = Prüfziffer nach Modulo 10
    rekursiv. Leerzeichen (Druckbild «21 00000 00003 …») werden ignoriert."""
    r = ''.join((referenz or '').split())
    if len(r) != 27 or not r.isascii() or not r.isdigit():
        return False
    uebertrag = 0
    for z in r[:-1]:
        uebertrag = _QRR_UEBERTRAG[(uebertrag + int(z)) % 10]
    return (10 - uebertrag) % 10 == int(r[-1])
