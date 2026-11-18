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
from datetime import date

from core.services.kantone import kanton_fuer_liegenschaft, KANTON_NAMEN

# pflicht: 'ja' | 'teilweise' | 'nein' | 'unbekannt'
# Werte und Rechtsgrundlagen gemäss BWO-Verzeichnis «Formularpflicht für die Mitteilung des Anfangsmietzinses
# (Art. 270 Abs. 2 OR)», Ausgabe September 2026 (Leerwohnungsziffern per 1.6.2026), am 08.11.2026 gegen den Originaltext
# der Verzeichnisse abgeglichen. Pflicht: BS, BE, FR, GE, LU, ZG, ZH; teilweise NE und VD; keine VS.
# Schwelle fast überall «Leerwohnungsbestand höchstens 1,5 %» (FR: unter 1,8 %); gemessen jährlich am 1. Juni, Änderungen
# gelten in BS, BE, LU und ZH ab 1. November. DIESES REGISTER IST JEDES JAHR IM NOVEMBER NEU ZU PRÜFEN (neues Verzeichnis).
# Fehler im Verzeichnis: Es führt Art. 135a «Offenlegung Vormiete» unter der Berner Kantonsverfassung; der Artikel steht
# im EG ZGB (BSG 211.1), geprüft in der Berner Erlass-Sammlung (BELEX).
# NE und VD: das Verzeichnis nennt die betroffenen Gemeinden bzw. Bezirke — hier nicht einzeln abgebildet.
_REGISTER = {
    'BS': dict(pflicht='ja', gesetz='§ 214b EG ZGB (SG 211.100); Pflicht bei Leerwohnungsbestand höchstens 1,5 %',
               leerziffer='0.78 %', stand='1.6.2026'),
    'BE': dict(pflicht='ja', gesetz='Art. 135a EG ZGB (BSG 211.1); Pflicht bei Leerwohnungsbestand höchstens 1,5 % (ganzer Kanton oder einzelne Verwaltungskreise)',
               leerziffer='1.04 %', stand='1.6.2026'),
    'FR': dict(pflicht='ja', gesetz='Art. 27 MPVG (SGF 222.3.1); Wohnungsmangel bei Leerwohnungsbestand unter 1,8 % (Art. 5 MPVV, SGF 222.3.11)',
               leerziffer='1.26 %', stand='1.6.2026'),
    'GE': dict(pflicht='ja', gesetz="Art. 207 LaCC (E.1.05)",
               leerziffer='0.31 %', stand='1.6.2026'),
    'LU': dict(pflicht='ja', gesetz='§ 94 EGZGB (SRL 200) und Beschluss vom 21.9.2021; Pflicht bei Leerwohnungsbestand höchstens 1,5 %',
               leerziffer='0.70 %', stand='1.6.2026'),
    'NE': dict(pflicht='teilweise', gesetz='Art. 4 LI-CO (224.1), Arrêté 224.2 Art. 2 und LVAL (846.0): Formularpflicht gemeindeweise, für Wohnungen mit 2–5 Zimmern',
               leerziffer='1.64 %', stand='1.6.2026'),
    'VD': dict(pflicht='teilweise', gesetz='LFOCL (221.315) Art. 1 und 4, LPPPL (840.15) Art. 2: Formularpflicht bezirksweise (Pénurie unter 1,5 %, Dreijahresmittel)',
               leerziffer='0.87 %', stand='1.6.2026'),
    'VS': dict(pflicht='nein', gesetz='Keine Formularpflicht; der Staatsrat dürfte sie bei Wohnungsnot anordnen (Art. 192 EGZGB)',
               leerziffer='1.04 %', stand='1.6.2026'),
    'ZG': dict(pflicht='ja', gesetz='§ 10e EG OR (BGS 216.1); Pflicht bei Leerwohnungsbestand im ganzen Kanton von höchstens 1,5 %',
               leerziffer='0.20 %', stand='1.6.2026'),
    'ZH': dict(pflicht='ja', gesetz='§ 229b EG ZGB und Regierungsratsbeschluss 235.41; Pflicht bei Leerwohnungsbestand höchstens 1,5 %',
               leerziffer='0.52 %', stand='1.6.2026'),
}

_STAND_VERZEICHNIS = "September 2026"
#: Tag, an dem das Register zuletzt gegen das Verzeichnis geprüft wurde (Kopfkommentar oben) — für die Pflege-Erinnerung
#: (`core/services/datenpflege.py`). Nach jeder Prüfung ändern.
GEPRUEFT_AM = date(2026, 11, 8)


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
