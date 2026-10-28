"""Formularpflicht für die Mitteilung des Anfangsmietzinses (Art. 270 Abs. 2 OR).

Einzelne Kantone schreiben beim Neuabschluss eines Mietvertrags die Verwendung
des amtlichen Formulars vor, sofern ein Wohnungsmangel besteht (Leerwohnungs-
ziffer unter einem kantonalen Schwellenwert, meist 1.5 %). Grundlage: das jährlich
aktualisierte «Verzeichnis der Formularpflicht» des BWO (Stand hier: Ausgabe
September 2026, vom 16.9.2026; Leerwohnungsziffern per 1. Juni 2026).

Dieses Modul bildet den Stand als Nachschlagetabelle ab, damit die App beim
Anfangsmietzins-Formular anzeigen kann, ob die Verwendung im Kanton der
Liegenschaft obligatorisch ist. Es ersetzt keine Rechtsberatung — der Verwalter
prüft die aktuelle kantonale Bekanntmachung.
"""
from core.services.kantone import kanton_fuer_liegenschaft, KANTON_NAMEN

# pflicht: 'ja' | 'teilweise' | 'nein' | 'unbekannt'
# Werte gemäss BWO-Verzeichnis 2026, Ausgabe September 2026 (Leerwohnungsziffern per 1.6.2026): Pflicht
# BS, BE, FR, GE, LU, ZG, ZH; teilweise NE und VD; keine VS. Die Ziffern und die Kantonsliste stammen aus
# der Lesung des Verzeichnisses im Audit vom 28.10.2026 (Bericht mietrecht, MIET-16); die Gesetzesangaben
# von BS, BE, FR, GE, LU und ZG sind NICHT neu belegt (Fachpunkt: gegen das Verzeichnis prüfen).
# NE und VD: das Verzeichnis nennt die betroffenen Gemeinden bzw. Bezirke — hier nicht abgebildet.
_REGISTER = {
    'BS': dict(pflicht='ja', gesetz='§ 214b EG ZGB (SG 211.100)',
               leerziffer='0.78 %', stand='1.6.2026'),
    'BE': dict(pflicht='ja', gesetz='Art. 135a EG ZGB (BSG 211.1)',
               leerziffer='1.04 %', stand='1.6.2026'),
    'FR': dict(pflicht='ja', gesetz='Art. 27 MPVG (SGF 222.3.1)',
               leerziffer='1.26 %', stand='1.6.2026'),
    'GE': dict(pflicht='ja', gesetz="Art. 207 LaCC (E.1.05)",
               leerziffer='0.31 %', stand='1.6.2026'),
    'LU': dict(pflicht='ja', gesetz='Kantonale Verordnung (Formularpflicht)',
               leerziffer='0.70 %', stand='1.6.2026'),
    'NE': dict(pflicht='teilweise', gesetz='Formularpflicht für Wohnungen mit 2–5 Zimmern',
               leerziffer='', stand='1.6.2026'),
    'VD': dict(pflicht='teilweise', gesetz='Teilweise Formularpflicht (kantonale Regelung)',
               leerziffer='', stand='1.6.2026'),
    'VS': dict(pflicht='nein', gesetz='Keine Formularpflicht',
               leerziffer='', stand='1.6.2026'),
    'ZG': dict(pflicht='ja', gesetz='Kantonale Verordnung (Formularpflicht)',
               leerziffer='0.20 %', stand='1.6.2026'),
    'ZH': dict(pflicht='ja', gesetz='§ 229b EG ZGB',
               leerziffer='0.52 %', stand='1.6.2026'),
}

_STAND_VERZEICHNIS = "September 2026"


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
