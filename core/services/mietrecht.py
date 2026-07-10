"""Zentrale mietrechtliche Referenzen (Schweizer OR / VMWG).

Single Source of Truth für alle Gesetzeszitate in der App: Dokumente (PDF),
UI-Hinweise und Validierungen greifen hierauf zu, damit die Artikel überall
konsistent und wartbar sind. Angaben nach bestem Wissen — juristisch prüfen.
"""
from datetime import date


# ── Artikel-Register (Schlüssel → Zitat + Kurztitel) ─────────────────────────
ARTIKEL = {
    # Grundlagen
    'miete':               ('Art. 253 OR', 'Begriff der Miete'),
    'nebensachen':         ('Art. 253a OR', 'Mitvermietete Nebenräume/-sachen'),
    'uebergabe':           ('Art. 256 OR', 'Übergabe in gebrauchstauglichem Zustand'),
    'nebenkosten':         ('Art. 257a–257b OR', 'Nebenkosten'),
    'zahlungstermin':      ('Art. 257c OR', 'Zahlungstermine des Mietzinses'),
    # Kaution
    'kaution':             ('Art. 257e OR', 'Sicherheitsleistung (Mietzinsdepot)'),
    # Verzug
    'verzug':              ('Art. 257d OR', 'Zahlungsverzug des Mieters'),
    'verzugszins':         ('Art. 104 OR', 'Verzugszins (5 %)'),
    # Mängel / Rückgabe
    'maengel':             ('Art. 259a–259i OR', 'Mängel während der Mietdauer'),
    'rueckgabe':           ('Art. 267 OR', 'Rückgabe der Mietsache'),
    'rueckgabe_pruefung':  ('Art. 267a OR', 'Prüfung der Sache und Mängelrüge'),
    # Kündigung – Form & Fristen
    'kuendigung_form':     ('Art. 266l OR', 'Form der Kündigung (Vermieter: amtl. Formular)'),
    'kuendigung_termine':  ('Art. 266a OR', 'Kündigungsfristen und -termine'),
    'kuendigung_wohnung':  ('Art. 266c OR', 'Kündigungsfrist Wohnungen (3 Monate)'),
    'kuendigung_geschaeft':('Art. 266d OR', 'Kündigungsfrist Geschäftsräume (6 Monate)'),
    'kuendigung_platz':    ('Art. 266e OR', 'Einstellplätze u.ä. (2 Wochen / Monatsende)'),
    'kuendigung_uebrige':  ('Art. 266b OR', 'Übrige unbewegliche Sachen (3 Monate)'),
    'kuendigung_ao':       ('Art. 266g OR', 'Ausserordentliche Kündigung (wichtige Gründe)'),
    'familienwohnung':     ('Art. 266m–266n OR', 'Familienwohnung (Zustimmung/Zustellung)'),
    'kuendigung_nichtig':  ('Art. 266o OR', 'Nichtigkeit fehlerhafter Kündigung'),
    # Kündigungsschutz
    'anfechtung':          ('Art. 271–271a OR', 'Anfechtbarkeit der Kündigung'),
    'anfechtung_frist':    ('Art. 273 OR', 'Anfechtung binnen 30 Tagen an Schlichtungsbehörde'),
    'erstreckung':         ('Art. 272–272d OR', 'Erstreckung des Mietverhältnisses'),
    # Mietzins
    'missbrauch':          ('Art. 269 OR', 'Missbräuchliche Mietzinse'),
    'nicht_missbrauch':    ('Art. 269a OR', 'Nicht missbräuchliche Mietzinse'),
    'indexmiete':          ('Art. 269b OR', 'Indexklausel (feste Dauer ≥ 5 Jahre)'),
    'staffelmiete':        ('Art. 269c OR', 'Staffelmiete (Dauer ≥ 3 Jahre, max. 1×/Jahr)'),
    'mietzinserhoehung':   ('Art. 269d OR', 'Mietzinserhöhung mit amtlichem Formular'),
    'anfangsmietzins':     ('Art. 270 OR', 'Anfechtung des Anfangsmietzinses'),
    'herabsetzung':        ('Art. 270a OR', 'Herabsetzungsbegehren (Referenzzinssenkung)'),
    'referenzzins':        ('Art. 12a VMWG', 'Hypothekarischer Referenzzinssatz'),
}


def ref(key):
    """Gibt das reine Zitat zurück, z.B. 'Art. 266c OR' (leer bei unbekanntem Schlüssel)."""
    eintrag = ARTIKEL.get(key)
    return eintrag[0] if eintrag else ''


def label(key):
    eintrag = ARTIKEL.get(key)
    return eintrag[1] if eintrag else ''


# ── Kategorie-abhängige Kündigungs-Rechtsgrundlage ───────────────────────────
def kuendigung_ref(kategorie, ist_einstellplatz=False):
    """Zitat der massgeblichen Kündigungsfrist-Norm je Objektart."""
    if kategorie == 'wohnen':
        return ref('kuendigung_wohnung')
    if kategorie == 'gewerbe':
        return ref('kuendigung_geschaeft')
    return ref('kuendigung_platz') if ist_einstellplatz else ref('kuendigung_uebrige')


# ── Validierung Mietzinsmodell (Index/Staffel) ───────────────────────────────
def _monate_zwischen(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def pruefe_mietzinsmodell(modell, beginn, ende):
    """Prüft die gesetzlichen Mindestvoraussetzungen für Index-/Staffelmiete und
    gibt eine Liste von Warnhinweisen zurück (leer = keine Beanstandung).

    - Indexmiete (Art. 269b): setzt einen befristeten Vertrag mit fester Dauer
      von mindestens 5 Jahren voraus.
    - Staffelmiete (Art. 269c): Vertragsdauer von mindestens 3 Jahren.
    """
    hinweise = []
    if modell not in ('index', 'staffel'):
        return hinweise
    if not beginn:
        return hinweise
    if modell == 'index':
        if not ende:
            hinweise.append("Indexmiete (Art. 269b OR) setzt einen befristeten Vertrag "
                            "mit fester Dauer von mindestens 5 Jahren voraus — es ist kein Mietende gesetzt.")
        elif _monate_zwischen(beginn, ende) < 60:
            hinweise.append("Indexmiete (Art. 269b OR) ist nur bei fester Vertragsdauer "
                            "von mindestens 5 Jahren zulässig — die erfasste Dauer ist kürzer.")
    elif modell == 'staffel':
        if ende and _monate_zwischen(beginn, ende) < 36:
            hinweise.append("Staffelmiete (Art. 269c OR) setzt eine Vertragsdauer von "
                            "mindestens 3 Jahren voraus — die erfasste Dauer ist kürzer.")
    return hinweise


def staffel_pruefung(stufen):
    """Prüft eine Liste von Staffelstufen (mit .ab_datum) auf die gesetzliche
    Vorgabe: höchstens eine Erhöhung pro Jahr (Art. 269c OR)."""
    hinweise = []
    daten = sorted([s.ab_datum for s in stufen if getattr(s, 'ab_datum', None)])
    for a, b in zip(daten, daten[1:]):
        if _monate_zwischen(a, b) < 12:
            hinweise.append("Staffelmiete (Art. 269c OR): Zwischen zwei Erhöhungen muss "
                            "mindestens ein Jahr liegen — es liegen Stufen näher beieinander.")
            break
    return hinweise
