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


# ── Wo wird der Artikel in der Software angewandt? (für die Rechtsgrundlagen-Seite) ──
ANWENDUNG = {
    'kaution':             'Vertrags-Wizard (max. 3 Monatsmieten, Live-Prüfung) · Kautions-Cockpit · '
                           'automatische Freigabefrist 1 Jahr nach Mietende (Abs. 3).',
    'verzug':              'Zahlungsverzug-Prozess: Fristansetzung (30 T Wohn-/Geschäft, 10 T übrige) '
                           '→ ausserordentliche Kündigung 30 T auf Monatsende · Mahnwesen.',
    'verzugszins':         'Verzugszins-Berechnung im Debitoren-/Mahnlauf.',
    'kuendigung_form':     'Kündigungs-Erfassung: Vermieterkündigung nur mit amtlichem Formular (Live-Hinweis).',
    'kuendigung_termine':  'Kündigungstermin-Berechnung · Live-Prüfung „Ende vor ordentlichem Termin".',
    'kuendigung_wohnung':  'Frist-Default & Live-Prüfung im Vertrags-Wizard (Objektart Wohnen).',
    'kuendigung_geschaeft':'Frist-Default & Live-Prüfung im Vertrags-Wizard (Objektart Gewerbe).',
    'kuendigung_platz':    'Kündigungstermin-Berechnung für Einstellplätze (2 Wochen / Monatsende).',
    'kuendigung_uebrige':  'Kündigungsfrist für Nebenobjekte (Bastelraum u.ä.).',
    'kuendigung_ao':       'Ausserordentliche Kündigung (Grundauswahl im Kündigungsformular).',
    'familienwohnung':     'Vertrags-Wizard: Hinweis auf getrennte Zustellung an beide Ehegatten.',
    'kuendigung_nichtig':  'Live-Prüfung: unwirksame ordentliche Kündigung auf zu frühen Termin.',
    'anfechtung':          'Automatische Anfechtungsfrist-Pendenz bei Vermieterkündigung.',
    'anfechtung_frist':    'Anfechtungsfrist-Pendenz (30 Tage) · Rechtsbelehrung auf Dokumenten.',
    'erstreckung':         'Hinweis bei Vermieterkündigung geschützter Räume.',
    'missbrauch':          'Mietzinsanpassung: Live-Warnung, wenn Erhöhung das begründbare Mass übersteigt.',
    'indexmiete':          'Vertrags-Wizard/Gewerbe: Index nur bei fester Dauer ≥ 5 J (Live-Prüfung) · Mietenlauf.',
    'staffelmiete':        'Vertrags-Wizard/Gewerbe: Staffel ≥ 3 J, max. 1×/Jahr (Live-Prüfung) · Mietenlauf.',
    'mietzinserhoehung':   'Amtliches Mietzinsanpassungs-Formular · Ankündigungsfrist-Live-Prüfung.',
    'herabsetzung':        'Automatische Pendenz bei Referenzzinssenkung (Herabsetzungsanspruch).',
    'referenzzins':        'Marktdaten (Referenzzinssatz) · Grundlage der Herabsetzungs-/Erhöhungslogik.',
    'anfangsmietzins':     'Hinweis im Mietzins-Kontext.',
    'rueckgabe':           'Wohnungsabnahme/Rücknahme-Protokoll · Schlussabrechnung.',
    'rueckgabe_pruefung':  'Wohnungsabnahme: Mängelrüge bei Rückgabe.',
    'nebenkosten':         'Nebenkosten-Abrechnung (Assistent) · Rechtsgrundlagen im Abrechnungs-PDF.',
    'zahlungstermin':      'Sollstellung Miete · Fälligkeiten.',
    'uebergabe':           'Vertrag/Übergabeprotokoll.',
}


def ref(key):
    """Gibt das reine Zitat zurück, z.B. 'Art. 266c OR' (leer bei unbekanntem Schlüssel)."""
    eintrag = ARTIKEL.get(key)
    return eintrag[0] if eintrag else ''


def label(key):
    eintrag = ARTIKEL.get(key)
    return eintrag[1] if eintrag else ''


# ── Gruppierte Übersicht für die Rechtsgrundlagen-Seite ──────────────────────
GRUPPEN = [
    ('Kaution', 'geld', ['kaution']),
    ('Zahlungsverzug', 'warnung', ['verzug', 'verzugszins']),
    ('Kündigung – Form & Fristen', 'kritisch',
     ['kuendigung_form', 'kuendigung_termine', 'kuendigung_wohnung', 'kuendigung_geschaeft',
      'kuendigung_platz', 'kuendigung_uebrige', 'kuendigung_ao', 'familienwohnung', 'kuendigung_nichtig']),
    ('Kündigungsschutz', 'recht', ['anfechtung', 'anfechtung_frist', 'erstreckung']),
    ('Mietzins', 'bericht',
     ['missbrauch', 'indexmiete', 'staffelmiete', 'mietzinserhoehung', 'herabsetzung',
      'referenzzins', 'anfangsmietzins']),
    ('Rückgabe & Nebenkosten', 'schluessel', ['rueckgabe', 'rueckgabe_pruefung', 'nebenkosten', 'zahlungstermin', 'uebergabe']),
]


def uebersicht():
    """Aufbereitete, gruppierte Liste aller angewandten Rechtsgrundlagen für die UI."""
    gruppen = []
    for titel, icon, keys in GRUPPEN:
        rows = []
        for k in keys:
            if k not in ARTIKEL:
                continue
            rows.append({'ref': ARTIKEL[k][0], 'label': ARTIKEL[k][1],
                         'anwendung': ANWENDUNG.get(k, '')})
        gruppen.append({'titel': titel, 'icon': icon, 'artikel': rows})
    return gruppen


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


def index_anpassung_vorschlag(vertrag, aktuell_lik=None):
    """Berechnet die fällige Indexmiet-Anpassung (Art. 269b OR) für die amtliche
    Index-Mitteilung (Art. 269d): neuer Nettomietzins aus der LIK-Entwicklung
    seit der Vertragsbasis, anteilig zur vereinbarten Weitergabe.

    Rückgabe-Dict oder None (kein Indexvertrag / keine Basis / LIK nicht gestiegen):
      neu_netto, alt_netto, basis_lik, aktuell_lik, delta_prozent, begruendung.
    """
    from decimal import Decimal
    if getattr(vertrag, 'mietzins_modell', 'fest') != 'index':
        return None
    basis_lik = vertrag.basis_lik_punkte or Decimal('0')
    if basis_lik <= 0:
        return None
    if aktuell_lik is None:
        try:
            from core.services.lik import aktueller_lik_wert
            _stand, aktuell_lik, _b = aktueller_lik_wert(live=False)
        except Exception:
            aktuell_lik = None
    if not aktuell_lik:
        return None
    aktuell_lik = Decimal(str(aktuell_lik))
    if aktuell_lik <= basis_lik:
        return None   # LIK nicht gestiegen → keine Erhöhung möglich
    weiter = (vertrag.index_weitergabe_prozent or Decimal('100')) / Decimal('100')
    faktor = Decimal('1') + (aktuell_lik - basis_lik) / basis_lik * weiter
    alt_netto = vertrag.netto_mietzins or Decimal('0')
    neu_netto = (alt_netto * faktor).quantize(Decimal('0.01'))
    if neu_netto <= alt_netto:
        return None
    delta_prozent = ((neu_netto - alt_netto) / alt_netto * Decimal('100')).quantize(Decimal('0.01')) \
        if alt_netto > 0 else Decimal('0')
    weiter_txt = '' if weiter == Decimal('1') else f" (Weitergabe {vertrag.index_weitergabe_prozent}%)"
    begruendung = (f"Indexanpassung an den Landesindex der Konsumentenpreise (Art. 269b OR){weiter_txt}: "
                   f"LIK {basis_lik} → {aktuell_lik} Punkte. Nettomietzins CHF {alt_netto} → CHF {neu_netto}.")
    return {
        'neu_netto': neu_netto, 'alt_netto': alt_netto,
        'basis_lik': basis_lik, 'aktuell_lik': aktuell_lik,
        'delta_prozent': delta_prozent, 'begruendung': begruendung,
    }


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
