"""Formularpflicht für die Mitteilung des Anfangsmietzinses (Art. 270 Abs. 2 OR).

Einzelne Kantone schreiben beim Neuabschluss eines Mietvertrags die Verwendung
des amtlichen Formulars vor, sofern ein Wohnungsmangel besteht (Leerwohnungs-
ziffer unter einem kantonalen Schwellenwert, meist 1.5 %). Grundlage: das jährlich
aktualisierte «Verzeichnis der Formularpflicht» (Stand hier: Februar 2026,
Leerwohnungsziffern per 1. Juni 2025).

Dieses Modul bildet den Stand als Nachschlagetabelle ab, damit die App beim
Anfangsmietzins-Formular anzeigen kann, ob die Verwendung im Kanton der
Liegenschaft obligatorisch ist. Es ersetzt keine Rechtsberatung — der Verwalter
prüft die aktuelle kantonale Bekanntmachung.
"""
from core.services.kantone import kanton_fuer_liegenschaft, KANTON_NAMEN

# pflicht: 'ja' | 'teilweise' | 'nein' | 'unbekannt'
# Werte gemäss Verzeichnis 2026 (Leerwohnungsziffern per 1.6.2025).
_REGISTER = {
    'BS': dict(pflicht='ja', gesetz='§ 214b EG ZGB (SG 211.100)',
               leerziffer='0.92 %', stand='1.6.2025'),
    'BE': dict(pflicht='ja', gesetz='Art. 135a EG ZGB (BSG 211.1)',
               leerziffer='1.12 %', stand='1.6.2025'),
    'FR': dict(pflicht='ja', gesetz='Art. 27 MPVG (SGF 222.3.1)',
               leerziffer='1.11 %', stand='1.6.2025'),
    'GE': dict(pflicht='ja', gesetz="Art. 207 LaCC (E.1.05)",
               leerziffer='0.34 %', stand='1.6.2025'),
    'LU': dict(pflicht='ja', gesetz='Kantonale Verordnung (Formularpflicht)',
               leerziffer='', stand='1.6.2025'),
    'NE': dict(pflicht='teilweise', gesetz='Formularpflicht für Wohnungen mit 2–5 Zimmern',
               leerziffer='', stand='1.6.2025'),
    'VD': dict(pflicht='teilweise', gesetz='Teilweise Formularpflicht (kantonale Regelung)',
               leerziffer='', stand='1.6.2025'),
    'VS': dict(pflicht='nein', gesetz='Keine Formularpflicht',
               leerziffer='', stand='1.6.2025'),
    'ZG': dict(pflicht='ja', gesetz='Kantonale Verordnung (Formularpflicht)',
               leerziffer='', stand='1.6.2025'),
    'ZH': dict(pflicht='ja', gesetz='§ 12 EG zum Bundesgesetz über Miete/Pacht',
               leerziffer='', stand='1.6.2025'),
}

_STAND_VERZEICHNIS = "Februar 2026"


def formularpflicht_fuer_kanton(kanton):
    """Gibt (pflicht, dict) für einen Kanton-Code zurück. Nicht gelistete Kantone
    → 'unbekannt' (keine bundesweite Pflicht; im Zweifel kantonale Bekanntmachung
    prüfen)."""
    kt = (kanton or '').upper()
    eintrag = _REGISTER.get(kt)
    if not eintrag:
        return 'unbekannt', dict(pflicht='unbekannt', gesetz='', leerziffer='',
                                 stand='', kanton=kt, kanton_name=KANTON_NAMEN.get(kt, ''),
                                 stand_verzeichnis=_STAND_VERZEICHNIS)
    info = dict(eintrag)
    info['kanton'] = kt
    info['kanton_name'] = KANTON_NAMEN.get(kt, '')
    info['stand_verzeichnis'] = _STAND_VERZEICHNIS
    return eintrag['pflicht'], info


def formularpflicht_fuer_liegenschaft(lg):
    """Bequemer Wrapper: ermittelt den Kanton der Liegenschaft und liefert (pflicht, info)."""
    return formularpflicht_fuer_kanton(kanton_fuer_liegenschaft(lg))


def pflicht_label(pflicht):
    """Kurzes Anzeige-Label für die UI."""
    return {
        'ja': 'Formularpflicht',
        'teilweise': 'Teilweise Formularpflicht',
        'nein': 'Keine Formularpflicht',
        'unbekannt': 'Formularpflicht kantonal prüfen',
    }.get(pflicht, 'Formularpflicht kantonal prüfen')
