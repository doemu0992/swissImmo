"""Lieferanten-Gedächtnis: normalisiert Lieferantennamen zu einem stabilen
Schlüssel, lernt das Standardkonto bei jeder Kreditor-Freigabe und schlägt es
bei Erfassung/Scan wieder vor. So belegt der Scanner Konto + HNK-Relevanz
automatisch vor — kein manuelles Zuteilen bei bekannten Lieferanten mehr."""
import re

# Gängige Rechtsform-/Zusatzwörter, die für den Vergleich ignoriert werden.
_RECHTSFORMEN = r'\b(ag|gmbh|sa|sàrl|sarl|ltd|inc|co|kg|og|se|ug|llc|plc)\b'


def lieferant_key(name):
    """Normalisiert einen Lieferantennamen zu einem Vergleichsschlüssel:
    klein, ohne Satzzeichen, ohne Rechtsformzusätze, ohne Mehrfach-Leerzeichen.
    «EWZ AG» und «ewz» ergeben denselben Schlüssel."""
    s = (name or '').strip().lower()
    s = re.sub(r'[.,/&+]', ' ', s)
    s = re.sub(_RECHTSFORMEN, ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:200]


def lieferant_vorschlag(name):
    """Gibt das gelernte LieferantProfil für diesen Namen zurück (oder None)."""
    from finance.models import LieferantProfil
    key = lieferant_key(name)
    if not key:
        return None
    return LieferantProfil.objects.filter(name_key=key).first()


def lerne_lieferant(name, konto=None, iban=''):
    """Schreibt das Standardkonto (+ IBAN) für diesen Lieferanten fort.
    Idempotent pro normalisiertem Namen; erhöht den Trefferzähler."""
    from finance.models import LieferantProfil
    key = lieferant_key(name)
    if not key:
        return None
    prof, _ = LieferantProfil.objects.get_or_create(
        name_key=key, defaults={'name_anzeige': (name or '').strip()[:200]})
    if konto is not None:
        prof.standard_konto = konto
    if iban:
        prof.iban = iban[:50]
    if (name or '').strip():
        prof.name_anzeige = (name or '').strip()[:200]
    prof.treffer = (prof.treffer or 0) + 1
    prof.save()
    return prof


# Semantische Kategorie (aus dem KI-Scan) → Standard-Aufwandskonto.
KATEGORIE_KONTO = {
    'strom': '4130', 'wasser': '4110', 'heizung': '4100',
    'hauswartung': '4120', 'kehricht': '4140', 'versicherung': '4400',
    'reparatur': '4000', 'verwaltung': '4500', 'sonstiges': '4000',
}

# Schlüsselwörter → Konto (Fallback ohne KI, aus Lieferantenname/Text).
_KONTO_REGELN = [
    (['strom', 'elektr', 'elektrizit', 'ewz', 'ewb', 'iwb', 'bkw', 'ckw', 'romande energie'], '4130'),
    (['wasser', 'abwasser', 'wasserversorgung'], '4110'),
    (['heiz', 'brennstoff', 'heizöl', 'heizoel', 'erdgas', 'fernwärme', 'fernwaerme'], '4100'),
    (['hauswart', 'reinigung', 'reinig'], '4120'),
    (['kehricht', 'abfall', 'entsorgung'], '4140'),
    (['versicherung', 'assurance', 'mobiliar', 'axa', 'allianz', 'helvetia', 'zurich vers'], '4400'),
    (['verwaltung', 'honorar'], '4500'),
    (['reparatur', 'sanitär', 'sanitaer', 'maler', 'elektriker', 'handwerk', 'service', 'unterhalt', 'garten'], '4000'),
]


def konto_aus_kategorie(kategorie):
    """Kontonummer zu einer KI-Kategorie (oder None)."""
    return KATEGORIE_KONTO.get((kategorie or '').strip().lower())


def konto_aus_text(text):
    """Kontonummer aus Schlüsselwörtern im Text/Lieferantennamen (oder None)."""
    t = (text or '').lower()
    for keys, nr in _KONTO_REGELN:
        if any(k in t for k in keys):
            return nr
    return None


def vorbelegen(kr, kategorie=None):
    """Belegt Konto + HNK-Relevanz einer noch nicht zugeteilten Kreditorenrechnung
    vor — Priorität: (1) Lieferanten-Gedächtnis, (2) KI-Kategorie, (3) Schlüssel-
    wörter im Lieferantennamen. Überschreibt nie eine bereits getroffene Konto-Wahl.
    Gibt True zurück, wenn etwas vorbelegt wurde."""
    if kr.konto_id:
        return False
    from finance.booking import konto as _konto
    ziel = None
    # 1) Gelerntes Standardkonto des Lieferanten (am spezifischsten)
    prof = lieferant_vorschlag(kr.lieferant)
    if prof and prof.standard_konto_id:
        ziel = prof.standard_konto
    # 2) KI-Kategorie aus dem Rechnungsinhalt
    if ziel is None and kategorie:
        nr = konto_aus_kategorie(kategorie)
        if nr:
            ziel = _konto(nr)
    # 3) Schlüsselwörter im Lieferantennamen
    if ziel is None:
        nr = konto_aus_text(kr.lieferant or '')
        if nr:
            ziel = _konto(nr)
    if ziel is None:
        return False
    kr.konto = ziel
    if ziel.is_hnk_relevant:
        kr.is_hnk_relevant = True
    return True
