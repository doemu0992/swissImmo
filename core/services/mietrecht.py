"""Zentrale mietrechtliche Referenzen (Schweizer OR / VMWG).

Single Source of Truth für alle Gesetzeszitate in der App: Dokumente (PDF),
UI-Hinweise und Validierungen greifen hierauf zu, damit die Artikel überall
konsistent und wartbar sind. Angaben nach bestem Wissen — juristisch prüfen.
"""

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
# Die Regeln stehen in `core/services/mietzinsmodell.py`. Die beiden Funktionen
# hier bleiben für Altaufrufer (Vertragsassistent, Tests) und liefern wie bisher
# Warntexte. Bis 27.10.2026 rechnete eine eigene `_monate_zwischen` nach
# Kalendermonaten und ignorierte den Tag: Ein Vertrag vom 1.1.2026 bis
# 31.12.2030 (genau fünf Jahre) galt mit «59 Monaten» als zu kurz.
def pruefe_mietzinsmodell(modell, beginn, ende, ist_befristet=None, verzicht_bis=None):
    """Warntexte zur Dauer von Index- (Art. 269b OR) und Staffelmiete (Art. 269c OR);
    leer = keine Beanstandung. Ohne `ist_befristet` gilt ein gesetztes `ende` als Befristung.
    """
    from core.services.mietzinsmodell import dauer_befund
    befund = dauer_befund(modell, beginn, ende, ist_befristet, verzicht_bis)
    return [befund.volltext] if befund else []


def runde_mietzins(betrag, schritt=None):
    """Rundet einen Mietzinsvorschlag kaufmännisch auf 5 Rappen.

    Stresstest 30.09.2026: Der Vorschlag lautete 1699.08 — ein Betrag, den weder
    die Bank-Dauerauftragsmaske noch eine Mitteilung im üblichen Sinn kennt, und
    der sich nicht auf 5 Rappen zahlen lässt. Wie im Skill schweizer-fachlogik:
    Decimal, auf 5 Rappen, wo der Zahlungsverkehr es verlangt. Die Prozentangabe
    bleibt die errechnete; gerundet wird nur der Franken-Betrag.
    """
    from decimal import ROUND_HALF_UP, Decimal
    schritt = schritt or Decimal('0.05')
    return ((Decimal(str(betrag)) / schritt).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            * schritt).quantize(Decimal('0.01'))


def index_anpassung_vorschlag(vertrag, aktuell_lik=None, wirksam_ab=None):
    """Berechnet die fällige Indexmiet-Anpassung (Art. 269b OR) für die amtliche
    Index-Mitteilung (Art. 269d): neuer Nettomietzins aus der LIK-Entwicklung
    seit der letzten Anpassung, anteilig zur vereinbarten Weitergabe.

    Seit 26.10.2026 in BEIDE Richtungen (Befund N): Sinkt der Index, folgt der
    Mietzins ihm ebenso — die Rechnung ist dieselbe, nur mit negativem Vorzeichen.
    Bis hierher gab die Funktion bei sinkendem LIK schlicht None zurück, und die
    Senkung kam nirgends vor.

    Ausgangspunkt ist der Stand unmittelbar vor `wirksam_ab`
    (`rentals.services.bisheriger_stand`) — nicht `netto_mietzins` und
    `basis_lik_punkte` des Vertragsbeginns. Sonst rechnete die zweite
    Indexanpassung den bereits weitergegebenen Anstieg ein zweites Mal.

    Rückgabe-Dict oder None (kein Indexvertrag / keine Basis / LIK unverändert):
      neu_netto, alt_netto, basis_lik, aktuell_lik, delta_prozent, richtung
      ('erhoehung' | 'senkung'), begruendung.
    """
    from decimal import Decimal
    from rentals.services import bisheriger_stand
    if getattr(vertrag, 'mietzins_modell', 'fest') != 'index':
        return None
    alt_netto, _ref, basis_lik = bisheriger_stand(vertrag, wirksam_ab)
    basis_lik = Decimal(str(basis_lik or 0))
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
    if aktuell_lik == basis_lik:
        return None   # LIK unverändert → nichts anzupassen
    weiter = (vertrag.index_weitergabe_prozent or Decimal('100')) / Decimal('100')
    faktor = Decimal('1') + (aktuell_lik - basis_lik) / basis_lik * weiter
    alt_netto = Decimal(str(alt_netto or 0))
    neu_netto = runde_mietzins(alt_netto * faktor)
    if neu_netto == alt_netto:
        return None
    richtung = 'erhoehung' if neu_netto > alt_netto else 'senkung'
    delta_prozent = ((neu_netto - alt_netto) / alt_netto * Decimal('100')).quantize(Decimal('0.01')) \
        if alt_netto > 0 else Decimal('0')
    weiter_txt = '' if weiter == Decimal('1') else f" (Weitergabe {vertrag.index_weitergabe_prozent}%)"
    wort = 'Indexanpassung' if richtung == 'erhoehung' else 'Indexanpassung (Senkung)'
    begruendung = (f"{wort} an den Landesindex der Konsumentenpreise (Art. 269b OR){weiter_txt}: "
                   f"LIK {basis_lik} → {aktuell_lik} Punkte. Nettomietzins CHF {alt_netto} → CHF {neu_netto}.")
    return {
        'neu_netto': neu_netto, 'alt_netto': alt_netto,
        'basis_lik': basis_lik, 'aktuell_lik': aktuell_lik,
        'delta_prozent': delta_prozent, 'richtung': richtung, 'begruendung': begruendung,
    }


def staffel_pruefung(stufen):
    """Warntexte, wenn zwei Staffelstufen (mit .ab_datum) weniger als zwölf Monate auseinanderliegen
    (Art. 269c OR, höchstens eine Erhöhung pro Jahr). Der Abstand zum Mietbeginn gehört zu
    `core.services.mietzinsmodell.pruefe`."""
    from core.services import mietzinsmodell as regeln
    befunde = regeln.abstand_befunde(None, regeln.stufen_normieren(stufen))
    return [b.volltext for b in befunde[:1]]
