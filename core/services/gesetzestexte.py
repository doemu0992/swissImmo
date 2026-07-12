"""Register der mietrechtlichen Gesetzesartikel (OR / VMWG / ZGB).

Enthält je Artikel: Gesetz, Nummer, amtlicher Randtitel, eine präzise
Kurzfassung (KEIN amtlicher Wortlaut) und Stichworte für die Suche. Der
verbindliche Volltext liegt bei Fedlex — je Artikel wird dorthin verlinkt.

Bewusst als Kurzfassungen gehalten: massgeblich ist der amtliche Text; für den
aktuellen Wortlaut (inkl. Revisionen) immer die Fedlex-Fundstelle konsultieren.
"""

# Amtliche Fedlex-Fundstellen (ELI der konsolidierten Erlasse). Der Anker
# #art_<nr> springt – wo von Fedlex unterstützt – direkt zum Artikel; sonst
# landet der Link auf dem korrekten Erlass.
_ELI = {
    'OR':   'https://www.fedlex.admin.ch/eli/cc/27/317_321_377/de',       # SR 220
    'VMWG': 'https://www.fedlex.admin.ch/eli/cc/1990/835_835_835/de',     # SR 221.213.11
    'ZGB':  'https://www.fedlex.admin.ch/eli/cc/24/233_245_233/de',       # SR 210
}
_FEDLEX_SUCHE = "https://www.fedlex.admin.ch/de/search?query={q}"


def fedlex_url(gesetz, artikel):
    base = _ELI.get(gesetz)
    if base:
        return f"{base}#art_{str(artikel).lower()}"
    from urllib.parse import quote
    return _FEDLEX_SUCHE.format(q=quote(f"Art. {artikel} {gesetz}"))


# (gesetz, artikel, randtitel, kurzfassung, [stichworte])
REGISTER = [
    # ═══════════════ OR — Beginn / Anwendungsbereich ═══════════════
    ('OR', '253', 'Begriff der Miete',
     'Der Vermieter überlässt dem Mieter eine Sache zum Gebrauch, der Mieter zahlt dafür einen Mietzins.',
     ['miete', 'begriff', 'gebrauch', 'mietzins']),
    ('OR', '253a', 'Anwendungsbereich — Wohn-/Geschäftsräume',
     'Die Schutzbestimmungen für Wohn- und Geschäftsräume gelten auch für mitvermietete Sachen (Möbel, Garage usw.).',
     ['wohnräume', 'geschäftsräume', 'anwendungsbereich', 'nebensachen']),
    ('OR', '253b', 'Ausnahmen vom Kündigungs-/Mietzinsschutz',
     'Luxuswohnungen (≥ 6 Zimmer ohne Küche/Bad gezählt) und bestimmte Verhältnisse sind vom Mietzinsschutz teilweise ausgenommen.',
     ['ausnahmen', 'luxuswohnung', 'schutz']),
    ('OR', '254', 'Koppelungsgeschäfte',
     'Ein an den Mietvertrag geknüpftes Zusatzgeschäft ist nichtig, wenn der Abschluss des Mietvertrags davon abhängig gemacht wird.',
     ['koppelung', 'nichtig', 'zusatzgeschäft']),
    ('OR', '255', 'Befristetes/unbefristetes Mietverhältnis',
     'Befristet endet ohne Kündigung mit Zeitablauf; unbefristet läuft bis zur Kündigung.',
     ['befristet', 'unbefristet', 'dauer']),
    # ═══════════════ OR — Übergabe / Pflichten ═══════════════
    ('OR', '256', 'Übergabe in gebrauchstauglichem Zustand',
     'Der Vermieter muss die Sache zum vereinbarten Zeitpunkt in tauglichem Zustand übergeben und erhalten.',
     ['übergabe', 'zustand', 'unterhalt']),
    ('OR', '256a', 'Auskunft über frühere Mietzinse',
     'Auf Verlangen muss der Vermieter den Mietzins des Vormieters bekanntgeben.',
     ['auskunft', 'vormieter', 'anfangsmietzins']),
    ('OR', '256b', 'Abgaben und Lasten',
     'Öffentliche Lasten und Abgaben auf der Sache trägt der Vermieter.',
     ['abgaben', 'lasten']),
    ('OR', '257', 'Mietzins',
     'Der Mietzins ist das Entgelt für den Gebrauch der Sache.',
     ['mietzins', 'entgelt']),
    ('OR', '257a', 'Nebenkosten — Begriff',
     'Nebenkosten sind das Entgelt für Leistungen des Vermieters im Zusammenhang mit dem Gebrauch; sie sind nur geschuldet, wenn besonders vereinbart.',
     ['nebenkosten', 'vereinbarung']),
    ('OR', '257b', 'Nebenkosten Wohn-/Geschäftsräume',
     'Nebenkosten sind die tatsächlichen Aufwendungen (Heizung, Warmwasser, Betrieb); der Mieter darf Belege einsehen.',
     ['nebenkosten', 'heizung', 'einsicht', 'belege']),
    ('OR', '257c', 'Zahlungstermine',
     'Mietzins und Nebenkosten sind Ende jedes Monats, spätestens am Ende der Mietdauer zu zahlen (sofern nichts anderes vereinbart/ortsüblich).',
     ['zahlungstermin', 'fälligkeit']),
    ('OR', '257d', 'Zahlungsrückstand des Mieters',
     'Bei Verzug setzt der Vermieter schriftlich eine Frist (Wohn-/Geschäftsräume mind. 30 Tage) mit Kündigungsandrohung; danach Kündigung mit 30 Tagen auf Monatsende.',
     ['verzug', 'zahlungsrückstand', 'frist', 'kündigung', 'mahnung']),
    ('OR', '257e', 'Sicherheiten des Mieters (Kaution)',
     'Bei Wohn-/Geschäftsräumen max. 3 Monatszinse; Geld/Wertpapiere auf ein Sperrkonto lautend auf den Mieter. Rückgabe: nach 1 Jahr ohne Ansprüche kann der Mieter Freigabe verlangen.',
     ['kaution', 'sicherheit', 'sperrkonto', 'depot', 'freigabe']),
    ('OR', '257f', 'Sorgfalt und Rücksichtnahme',
     'Der Mieter muss sorgfältig gebrauchen und auf Hausbewohner/Nachbarn Rücksicht nehmen; grobe Verletzung erlaubt ausserordentliche Kündigung.',
     ['sorgfalt', 'rücksicht', 'hausordnung', 'lärm', 'kündigung']),
    ('OR', '257g', 'Meldepflicht bei Mängeln',
     'Der Mieter muss Mängel, die er nicht selbst beheben muss, dem Vermieter melden.',
     ['mängel', 'meldepflicht']),
    ('OR', '257h', 'Duldungspflicht',
     'Der Mieter muss Arbeiten und Besichtigungen dulden, soweit nötig; der Vermieter nimmt Rücksicht und entschädigt Nachteile.',
     ['duldung', 'besichtigung', 'arbeiten']),
    # ═══════════════ OR — Mängel ═══════════════
    ('OR', '258', 'Nicht gehörige Erfüllung bei Übergabe',
     'Übergibt der Vermieter mangelhaft, gelten die Regeln über Nichterfüllung/Verzug bzw. Mängelrechte.',
     ['mangel', 'übergabe', 'nichterfüllung']),
    ('OR', '259a', 'Mängel während der Mietdauer — Rechte',
     'Der Mieter kann Beseitigung, Herabsetzung, Schadenersatz, Übernahme des Rechtsstreits verlangen.',
     ['mängel', 'rechte', 'herabsetzung']),
    ('OR', '259d', 'Herabsetzung des Mietzinses',
     'Bei erheblicher Beeinträchtigung des Gebrauchs kann der Mietzins verhältnismässig herabgesetzt werden.',
     ['herabsetzung', 'mangel', 'gebrauch']),
    ('OR', '259g', 'Hinterlegung des Mietzinses',
     'Der Mieter kann bei nicht behobenem Mangel den Mietzins nach schriftlicher Androhung bei einer amtlichen Stelle hinterlegen.',
     ['hinterlegung', 'mangel', 'mietzins']),
    # ═══════════════ OR — Änderungen / Wechsel ═══════════════
    ('OR', '260', 'Erneuerungen/Änderungen durch den Vermieter',
     'Zulässig, wenn dem Mieter zumutbar und keine Kündigung läuft; Rücksicht und Entschädigung für Nachteile.',
     ['renovation', 'sanierung', 'erneuerung']),
    ('OR', '260a', 'Erneuerungen/Änderungen durch den Mieter',
     'Nur mit schriftlicher Zustimmung des Vermieters; bei Mehrwert kann der Mieter unter Umständen Entschädigung verlangen.',
     ['umbau', 'mieter', 'zustimmung', 'mehrwert']),
    ('OR', '261', 'Veräusserung der Sache / Eigenbedarf',
     'Beim Eigentümerwechsel geht das Mietverhältnis auf den Erwerber über; dieser kann bei dringendem Eigenbedarf vorzeitig (gesetzliche Frist) kündigen.',
     ['handänderung', 'eigenbedarf', 'eigentümerwechsel', 'kündigung']),
    ('OR', '262', 'Untermiete',
     'Untervermietung nur mit Zustimmung des Vermieters; verweigern nur bei fehlender Auskunft, missbräuchlichen Bedingungen oder wesentlichen Nachteilen.',
     ['untermiete', 'untervermietung', 'zustimmung']),
    ('OR', '263', 'Übertragung auf einen Dritten (Geschäftsräume)',
     'Geschäftsraummiete kann mit schriftlicher Zustimmung des Vermieters auf einen Dritten übertragen werden; Alt-Mieter haftet solidarisch (befristet).',
     ['übertragung', 'geschäftsräume', 'nachfolger']),
    ('OR', '264', 'Vorzeitige Rückgabe',
     'Gibt der Mieter ohne Einhaltung der Frist zurück, wird er befreit, wenn er einen zumutbaren, zahlungsfähigen Ersatzmieter stellt.',
     ['vorzeitig', 'rückgabe', 'ersatzmieter', 'nachmieter']),
    ('OR', '265', 'Verrechnung',
     'Auf das Recht zur Verrechnung von Forderungen aus dem Mietverhältnis kann nicht zum Voraus verzichtet werden.',
     ['verrechnung']),
    # ═══════════════ OR — Beendigung ═══════════════
    ('OR', '266', 'Ablauf der vereinbarten Dauer',
     'Ein befristetes Mietverhältnis endet ohne Kündigung mit Ablauf der Dauer.',
     ['befristet', 'ablauf', 'ende']),
    ('OR', '266a', 'Kündigung — Fristen und Termine',
     'Unbefristete Verhältnisse werden unter Einhaltung von Frist und Termin gekündigt; sonst gilt der nächstmögliche Termin.',
     ['kündigung', 'frist', 'termin']),
    ('OR', '266b', 'Unbewegliche Sachen / übrige Räume',
     'Kündigungsfrist drei Monate auf einen ortsüblichen Termin oder das Ende der Mietdauer.',
     ['kündigungsfrist', 'nebenobjekt', 'bastelraum']),
    ('OR', '266c', 'Wohnungen',
     'Kündigungsfrist drei Monate auf einen ortsüblichen Termin oder das Ende der Mietdauer.',
     ['kündigungsfrist', 'wohnung', '3 monate']),
    ('OR', '266d', 'Geschäftsräume',
     'Kündigungsfrist sechs Monate auf einen ortsüblichen Termin oder das Ende der Mietdauer.',
     ['kündigungsfrist', 'geschäftsräume', '6 monate']),
    ('OR', '266e', 'Möblierte Zimmer, Einstellplätze u. Ä.',
     'Kündigungsfrist zwei Wochen auf das Ende einer einmonatigen Mietdauer.',
     ['einstellplatz', 'parkplatz', 'garage', 'möbliert', '2 wochen']),
    ('OR', '266g', 'Ausserordentliche Kündigung — wichtige Gründe',
     'Aus wichtigen Gründen, welche die Vertragserfüllung unzumutbar machen, kann mit gesetzlicher Frist gekündigt werden (Entschädigungsfolge möglich).',
     ['ausserordentlich', 'wichtiger grund', 'kündigung']),
    ('OR', '266h', 'Konkurs des Mieters',
     'Bei Zahlungsunfähigkeit kann der Vermieter für künftige Leistungen Sicherheit verlangen; sonst ausserordentliche Kündigung.',
     ['konkurs', 'sicherheit', 'zahlungsunfähig']),
    ('OR', '266i', 'Tod des Mieters',
     'Beim Tod des Mieters können die Erben mit der gesetzlichen Frist auf den nächsten Termin kündigen.',
     ['tod', 'erben', 'kündigung']),
    ('OR', '266l', 'Form der Kündigung (Wohn-/Geschäftsräume)',
     'Kündigung schriftlich; der Vermieter muss ein vom Kanton genehmigtes Formular verwenden.',
     ['form', 'amtliches formular', 'schriftlich', 'vermieterkündigung']),
    ('OR', '266m', 'Familienwohnung — Kündigung durch Mieter',
     'Ein Ehegatte/eingetragener Partner kann die Familienwohnung nur mit ausdrücklicher Zustimmung des andern kündigen.',
     ['familienwohnung', 'ehegatte', 'zustimmung']),
    ('OR', '266n', 'Familienwohnung — Kündigung/Zustellung durch Vermieter',
     'Die Vermieterkündigung ist beiden Ehegatten/Partnern separat zuzustellen.',
     ['familienwohnung', 'zustellung', 'beide ehegatten']),
    ('OR', '266o', 'Nichtige Kündigung',
     'Eine Kündigung, die Form-/Formularvorschriften verletzt, ist nichtig.',
     ['nichtig', 'form', 'ungültig']),
    # ═══════════════ OR — Rückgabe ═══════════════
    ('OR', '267', 'Rückgabe der Sache',
     'Der Mieter gibt die Sache im Zustand zurück, der sich aus vertragsgemässem Gebrauch ergibt; normale Abnutzung geht nicht zu seinen Lasten.',
     ['rückgabe', 'abnahme', 'zustand', 'abnutzung']),
    ('OR', '267a', 'Prüfung der Sache und Meldung an den Mieter',
     'Der Vermieter muss die Sache bei Rückgabe prüfen und Mängel sofort melden, sonst verliert er die Ansprüche (ausser versteckte Mängel).',
     ['mängelrüge', 'prüfung', 'abnahmeprotokoll', 'rückgabe']),
    # ═══════════════ OR — Missbräuchliche Mietzinse ═══════════════
    ('OR', '269', 'Missbräuchliche Mietzinse',
     'Mietzinse sind missbräuchlich, wenn damit ein übersetzter Ertrag erzielt wird oder sie auf einem offensichtlich übersetzten Kaufpreis beruhen.',
     ['missbräuchlich', 'ertrag', 'mietzins', 'anfechtung']),
    ('OR', '269a', 'Nicht missbräuchliche Mietzinse',
     'Nicht missbräuchlich sind u. a. orts-/quartierübliche Mietzinse, Referenzzins-/Teuerungs-/Kostenanpassungen, Mehrleistungen.',
     ['ortsüblich', 'referenzzins', 'teuerung', 'nicht missbräuchlich']),
    ('OR', '269b', 'Indexierte Mietzinse',
     'Indexklausel (LIK) nur zulässig bei fester Vertragsdauer von mindestens fünf Jahren.',
     ['index', 'indexmiete', 'lik', '5 jahre']),
    ('OR', '269c', 'Gestaffelte Mietzinse',
     'Staffelmiete zulässig, wenn der Vertrag mindestens drei Jahre dauert und der Zins höchstens einmal jährlich um einen Frankenbetrag erhöht wird.',
     ['staffel', 'staffelmiete', '3 jahre']),
    ('OR', '269d', 'Mietzinserhöhung / einseitige Vertragsänderung',
     'Erhöhungen sind mit amtlichem Formular und Begründung, mind. 10 Tage vor Beginn der Kündigungsfrist, auf einen Kündigungstermin anzukündigen; sonst nichtig.',
     ['mietzinserhöhung', 'amtliches formular', 'begründung', 'ankündigungsfrist']),
    ('OR', '270', 'Anfechtung des Anfangsmietzinses',
     'Der Mieter kann den Anfangsmietzins innert 30 Tagen anfechten (bei Notlage, erheblicher Erhöhung ggü. Vormieter oder Formularpflicht des Kantons).',
     ['anfangsmietzins', 'anfechtung', '30 tage']),
    ('OR', '270a', 'Herabsetzungsbegehren im Verlauf',
     'Der Mieter kann eine Herabsetzung verlangen, wenn er wegen veränderter Berechnungsgrundlagen (z. B. gesunkener Referenzzins) einen übersetzten Ertrag vermutet.',
     ['herabsetzung', 'referenzzins', 'senkung']),
    ('OR', '270b', 'Anfechtung von Mietzinserhöhungen',
     'Eine Erhöhung/einseitige Vertragsänderung kann innert 30 Tagen nach Empfang bei der Schlichtungsbehörde angefochten werden.',
     ['anfechtung', 'erhöhung', '30 tage', 'schlichtung']),
    # ═══════════════ OR — Kündigungsschutz ═══════════════
    ('OR', '271', 'Anfechtbarkeit der Kündigung — allgemein',
     'Eine Kündigung ist anfechtbar, wenn sie gegen Treu und Glauben verstösst; sie ist auf Verlangen zu begründen.',
     ['anfechtbar', 'treu und glauben', 'missbräuchliche kündigung']),
    ('OR', '271a', 'Anfechtbarkeit — Kündigung durch den Vermieter',
     'Missbräuchlich u. a. wegen Geltendmachung von Ansprüchen, während/nach einem Schlichtungs-/Gerichtsverfahren (Sperrfrist 3 Jahre), bei Handänderung.',
     ['missbräuchlich', 'sperrfrist', 'rache', 'vermieterkündigung']),
    ('OR', '272', 'Erstreckung des Mietverhältnisses',
     'Der Mieter kann eine Erstreckung verlangen, wenn die Beendigung für ihn/seine Familie eine Härte bedeutet, die durch die Vermieterinteressen nicht gerechtfertigt ist.',
     ['erstreckung', 'härte', 'verlängerung']),
    ('OR', '272b', 'Erstreckung — Dauer',
     'Wohnräume höchstens vier Jahre, Geschäftsräume höchstens sechs Jahre (eine oder zwei Erstreckungen).',
     ['erstreckung', 'dauer', '4 jahre', '6 jahre']),
    ('OR', '273', 'Fristen und Verfahren (Anfechtung/Erstreckung)',
     'Kündigung anfechten: 30 Tage. Erstreckung: bis 30 Tage vor Ablauf. Zuständig ist die Schlichtungsbehörde.',
     ['30 tage', 'schlichtungsbehörde', 'frist', 'anfechtung', 'erstreckung']),
    ('OR', '273a', 'Familienwohnung — Verfahrensrechte',
     'Bei Familienwohnungen kann auch der Ehegatte/Partner die Kündigung anfechten und Erstreckung verlangen.',
     ['familienwohnung', 'ehegatte', 'anfechtung']),
    ('OR', '273c', 'Zwingende Bestimmungen',
     'Der Mieter kann auf Rechte aus dem Kündigungsschutz nur verzichten, wenn das Gesetz es ausdrücklich vorsieht.',
     ['zwingend', 'verzicht']),
    # ═══════════════ VMWG ═══════════════
    ('VMWG', '3', 'Nebenkosten — Heizung/Warmwasser',
     'Zu den Heiz-/Warmwasserkosten gehören die tatsächlichen Aufwendungen für Brennstoff, Betrieb, Wartung, Abrechnung usw.',
     ['nebenkosten', 'heizung', 'warmwasser', 'hnk']),
    ('VMWG', '4', 'Nebenkosten — Verteilung',
     'Die Heiz-/Warmwasserkosten werden verursachergerecht bzw. nach anerkannten Grundsätzen verteilt.',
     ['nebenkosten', 'verteilung', 'verteilschlüssel']),
    ('VMWG', '5', 'Nebenkosten — Abrechnung/Einsicht',
     'Der Vermieter erstellt eine Abrechnung; der Mieter kann die Belege einsehen.',
     ['abrechnung', 'einsicht', 'belege']),
    ('VMWG', '11', 'Orts- und quartierübliche Mietzinse',
     'Massgeblich sind Mietzinse vergleichbarer Objekte nach Lage, Grösse, Ausstattung, Zustand und Bauperiode (Vergleichsobjekte).',
     ['ortsüblich', 'quartierüblich', 'vergleich']),
    ('VMWG', '12a', 'Hypothekarischer Referenzzinssatz',
     'Für Mietzinsanpassungen massgebend ist der vom BWO veröffentlichte Referenzzinssatz.',
     ['referenzzins', 'hypothek', 'bwo']),
    ('VMWG', '13', 'Referenzzinssatz — Anpassung',
     'Bei Änderung des Referenzzinssatzes um 0,25 % kann der Mietzins um ca. 3 % (bei hohem Zinsniveau weniger) angepasst werden.',
     ['referenzzins', 'anpassung', '3 prozent']),
    ('VMWG', '14', 'Mehrleistungen des Vermieters',
     'Wertvermehrende Investitionen/Verbesserungen berechtigen zu einer Mietzinserhöhung (energetische Sanierungen gelten als Mehrleistung).',
     ['mehrleistung', 'wertvermehrung', 'sanierung', 'investition']),
    ('VMWG', '16', 'Kostensteigerungen',
     'Allgemeine Kostensteigerungen (Unterhalt, Verwaltung) können über eine Pauschale im Mietzins berücksichtigt werden.',
     ['kostensteigerung', 'unterhalt', 'pauschale']),
    ('VMWG', '19', 'Formular zur Mietzinserhöhung',
     'Das amtliche Formular muss Betrag, Datum des Wirksamwerdens, Begründung und die Anfechtungsmöglichkeit klar angeben.',
     ['formular', 'mietzinserhöhung', 'begründung', 'anfechtung']),
    ('VMWG', '20', 'Verwaltung — Auskunft',
     'Der Vermieter/die Verwaltung gibt auf Verlangen die für die Beurteilung nötigen Auskünfte.',
     ['auskunft', 'verwaltung']),
    ('VMWG', '26', 'Herabsetzung — Verfahren',
     'Für das Herabsetzungsbegehren gelten die gleichen Formvorschriften wie für Erhöhungen sinngemäss.',
     ['herabsetzung', 'verfahren']),
    # ═══════════════ ZGB ═══════════════
    ('ZGB', '169', 'Schutz der Familienwohnung',
     'Ein Ehegatte darf die Familienwohnung nur mit ausdrücklicher Zustimmung des andern kündigen, veräussern oder Rechte daran beschränken.',
     ['familienwohnung', 'ehegatte', 'zustimmung', 'schutz']),
]


def _norm(s):
    return (s or '').lower()


def suche(query=''):
    """Liefert die passenden Artikel (Treffer über Nummer, Randtitel, Kurzfassung,
    Stichworte). Leere Query → alle."""
    q = _norm(query).strip()
    rows = []
    for gesetz, art, titel, kurz, stichworte in REGISTER:
        if q:
            heu = ' '.join([gesetz, art, titel, kurz, ' '.join(stichworte)]).lower()
            if q not in heu:
                # Wortweise (jedes Suchwort muss vorkommen)
                if not all(w in heu for w in q.split()):
                    continue
        rows.append({
            'gesetz': gesetz, 'art': art, 'titel': titel, 'kurz': kurz,
            'stichworte': stichworte, 'url': fedlex_url(gesetz, art),
        })
    return rows


def gesetze_uebersicht(query=''):
    """Nach Gesetz gruppierte Trefferliste für die UI."""
    from collections import OrderedDict
    gruppen = OrderedDict()
    LABEL = {'OR': 'Obligationenrecht (OR) — Miete',
             'VMWG': 'Verordnung über die Miete (VMWG)',
             'ZGB': 'Zivilgesetzbuch (ZGB)'}
    for r in suche(query):
        gruppen.setdefault(r['gesetz'], {'label': LABEL.get(r['gesetz'], r['gesetz']),
                                         'artikel': []})['artikel'].append(r)
    return list(gruppen.values())
