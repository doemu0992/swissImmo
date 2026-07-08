"""IBAN-Validierung (Format + Mod-97-Prüfsumme, ISO 13616)."""

_LEN = {  # erwartete Gesamtlänge je Land (Auswahl, Schweiz relevant)
    'CH': 21, 'LI': 21, 'DE': 22, 'AT': 20, 'FR': 27, 'IT': 27, 'LU': 20,
}


def normalisiere_iban(iban):
    return (iban or '').replace(' ', '').replace('-', '').upper()


def ist_gueltige_iban(iban):
    """True, wenn die IBAN formal (Länge, Zeichen) und per Mod-97 gültig ist."""
    s = normalisiere_iban(iban)
    if len(s) < 5 or not s[:2].isalpha() or not s[2:4].isdigit():
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
