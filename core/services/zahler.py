"""Auftraggeber einer Bankzahlung: auslesen und wiedererkennen.

Zwei Dinge, die im Bankabgleich immer wieder Handarbeit erzeugt haben:

1. Viele Bank-Exporte haben keine eigene Auftraggeber-Spalte, sondern packen
   «Name;Strasse;PLZ Ort; Land» in den Buchungstext (real gesehen:
   «Narrezauber Soledurn;4500 Solothurn; CH»). Der Name steht da, nur nicht
   als Feld — `aus_bewegung()` holt ihn heraus.

2. Zahlt derselbe Absender jeden Monat ohne QR-Referenz, landete die Zahlung
   jeden Monat neu auf dem Durchlaufkonto und musste jeden Monat von Hand
   zugeordnet werden. `lerne()` merkt sich die einmal getroffene Zuordnung,
   `finde_vertrag()` wendet sie beim nächsten Import an.
"""
import re


def normalisiere(name):
    """Vergleichsform eines Namens: nur Kleinbuchstaben und Ziffern.

    So stören Rechtschreib-/Formatunterschiede der Bank nicht («Muster AG»,
    «MUSTER  AG.», «Muster-AG» → dasselbe).
    """
    return ''.join(ch for ch in (name or '').lower() if ch.isalnum())


def aus_text(text):
    """Zerlegt einen Buchungstext in (Name, Rest).

    Nur bei mehreren Segmenten: «Miete Juli» ist eine Mitteilung und wird
    nicht zu einem Auftraggeber umgedeutet — lieber kein Name als ein
    erfundener.
    """
    teile = [t.strip() for t in re.split(r'[;|]', text or '') if t.strip()]
    if len(teile) > 1:
        return teile[0][:160], ' · '.join(teile[1:])
    return '', (teile[0] if teile else '')


def aus_bewegung(gegenpartei, text):
    """(Name, Rest-Text, geraten) für eine Auszugszeile.

    `geraten=True` heisst: Die Bank hat kein Auftraggeber-Feld geliefert, der
    Name stammt aus dem Buchungstext. Die Oberfläche schreibt das dazu, damit
    niemand die Herkunft für gesichert hält.
    """
    name = (gegenpartei or '').strip()
    if name:
        return name, (text or '').strip(), False
    geraten_name, rest = aus_text(text)
    return geraten_name, rest, bool(geraten_name)


def lerne(name, vertrag):
    """Merkt sich «dieser Absender gehört zu diesem Vertrag».

    Wird nach jeder manuellen Zuordnung aufgerufen. Ein bestehender Eintrag
    wird auf den neuen Vertrag umgebogen — die letzte Entscheidung des
    Menschen gilt, nicht die erste.
    """
    from finance.models import ZahlerZuordnung
    schluessel = normalisiere(name)
    if not schluessel or vertrag is None:
        return None
    eintrag, _neu = ZahlerZuordnung.objects.update_or_create(
        name_norm=schluessel[:160],
        defaults={'vertrag': vertrag, 'name_anzeige': (name or '')[:160]})
    return eintrag


def finde_vertrag(name):
    """Gelernter Vertrag zu einem Absendernamen — None, wenn unbekannt."""
    from finance.models import ZahlerZuordnung
    schluessel = normalisiere(name)
    if not schluessel:
        return None
    eintrag = (ZahlerZuordnung.objects
               .filter(name_norm=schluessel[:160])
               .select_related('vertrag__einheit__liegenschaft', 'vertrag__mieter')
               .first())
    return eintrag.vertrag if eintrag else None


def zaehle_treffer(name):
    """Protokolliert, dass die gelernte Zuordnung wieder gegriffen hat."""
    from django.db.models import F
    from django.utils import timezone
    from finance.models import ZahlerZuordnung
    schluessel = normalisiere(name)
    if schluessel:
        (ZahlerZuordnung.objects.filter(name_norm=schluessel[:160])
         .update(treffer=F('treffer') + 1, zuletzt=timezone.now()))
