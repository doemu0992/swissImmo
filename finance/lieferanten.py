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


def vorbelegen(kr):
    """Belegt Konto + HNK-Relevanz einer noch nicht zugeteilten Kreditorenrechnung
    aus dem Lieferanten-Gedächtnis vor. Überschreibt nie eine bereits getroffene
    Konto-Wahl. Gibt True zurück, wenn etwas vorbelegt wurde."""
    if kr.konto_id or not (kr.lieferant or '').strip():
        return False
    prof = lieferant_vorschlag(kr.lieferant)
    if not prof or not prof.standard_konto_id:
        return False
    kr.konto = prof.standard_konto
    if prof.standard_konto.is_hnk_relevant:
        kr.is_hnk_relevant = True
    return True
