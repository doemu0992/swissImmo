"""Zentrale Navigationsstruktur der /neu/-Oberfläche.

FÜNF BEREICHE: Heute · Akten · Läufe · Finanzen · Berichte
(Einstellungen steht im Fuss der Leiste — es ist kein Arbeitsbereich.)

WAS SICH MIT E1.1 GEÄNDERT HAT UND WARUM
========================================

Vorher standen hier sechs Bereiche in ZWEI MODI — «einfach» mit
Klartext-Labels, «profi» mit Fachbegriffen. Beides ist entfallen.

Der Modus löste das falsche Problem. Er fragte «wie viel Wortschatz hat diese
Person?», während die eigentliche Frage lautet «was darf und was tut diese
Person?». Das gehört in die Rolle und ins Entitlement
(`core/funktionen.py`), nicht in einen Sessionschalter. Solange es ihn gab,
hatte jede Seite zwei Namen, jede Änderung zwei Orte, und die Oberfläche zeigte
je nach Schalterstellung ein anderes Produkt.

Gemessen am 21.08.2026: Im Einfachmodus hingen 18 Einträge unter «Erweitert»,
im Profimodus 16 unter «Finanzen». «Erweitert» war keine Kategorie, sondern ein
Sammelbecken — es bedeutete «alles, wofür wir keinen Platz gefunden haben».
Und die Läufe, seit 4b.5 gebaut, hatten im Einfachmodus nicht einmal einen
markierten Menüpunkt.

DIE FÜNF BEREICHE
-----------------
Heute     Was jetzt zu tun ist. Ein Arbeitsvorrat, nicht zwei Listen.
Akten     Die Register: Mandat, Liegenschaft, Objekt, Mietverhältnis, Person,
          Dienstleister — plus die laufenden Vorgänge dazu.
Läufe     Wiederkehrende Verarbeitung mit Zustand: Sollstellung, Bankabgleich,
          Mahnlauf, Zahllauf, Nebenkosten, Mietzins, MWST.
Finanzen  Register und Konten. Bewusst OHNE eigenen Arbeitskorb — was zu tun
          ist, steht unter Heute und Läufe, aus derselben Quelle
          (`faelle.Lauf`). Zwei Arbeitskörbe widersprachen sich: Am 21.08.2026
          meldete «Heute» drei überfällige Läufe, während das Finanz-Cockpit
          auf derselben Datenbank «alles erledigt» sagte.
Berichte  Auswertungen und was der Eigentümer zu sehen bekommt.

Entscheide D1 und D8 (docs/ENTSCHEIDE-V7.md): fünf Bereiche statt der vier aus
G1, weil die Buchhalterin einen anderen Tagesrhythmus hat als die
Bewirtschafterin und 16 gebaute Finanzseiten sonst keinen Ort haben.

WAS DIESE ETAPPE NOCH NICHT TUT
-------------------------------
Sie ordnet die vorhandenen Seiten neu, sie baut keine um. Das Finanz-Cockpit
(`/neu/finanzen/`) ist deshalb weiterhin erreichbar und trägt seinen zweiten
Arbeitskorb noch — es ist die Landeseite des Bereichs. Ihn abzulösen heisst,
die Startseite zur einzigen Quelle zu machen; das ist eine eigene Etappe mit
eigenem Wächter, keine Nebenwirkung einer Menüumstellung.

Die Struktur wird per Context-Processor (`fw_navigation`) an base.html
geliefert und dort generisch gerendert. Jede Seite meldet weiterhin ihren
`nav`-Key; `keys` je Eintrag verbindet die bestehenden Keys mit der neuen
Struktur, damit kein View angefasst werden muss.
"""

#: nav-Keys von Seiten, die den Einstellungen-Link (Fuss der Leiste) aktiv
#: schalten. `regelwerk` steht hier, weil Fristenregeln eine Einstellung sind
#: und keine Tagesarbeit.
EINSTELLUNGEN_KEYS = ['einstellungen', 'account', 'abonnement', 'benutzer',
                      'logbuch', 'vorlagen', 'integrationen', 'rechtsgrundlagen',
                      'regelwerk']

#: Die Seiten des Einstellungs-Bereichs.
#:
#: Sie stehen in keiner der fünf Gruppen, weil Einstellungen kein
#: Arbeitsbereich ist — die Leiste rendert sie in ihrem Fuss, der Hub
#: `/neu/einstellungen/` führt sie auf. Sie sind trotzdem NAVIGATION, und
#: `core/tests/test_erreichbarkeit.py` liest diese Liste mit.
#:
#: Ohne sie wäre `/neu/regelwerk/` beim Umbau auf fünf Bereiche
#: durchgerutscht: Es hing vorher unter «Erweitert», hat jetzt keinen
#: Gruppeneintrag mehr — und genau diese Seite war schon einmal vier Etappen
#: lang unauffindbar (Phase 4a).
EINSTELLUNGEN_ZIELE = [
    '/neu/einstellungen/',
    '/neu/account/',
    '/neu/benutzer/',
    '/neu/abonnement/',
    '/neu/vorlagen/',
    '/neu/integrationen/',
    '/neu/logbuch/',
    '/neu/rechtsgrundlagen/',
    '/neu/regelwerk/',
]


def _g(key, label, icon, ziel, items=None, badge=None, extra_keys=None):
    """Bereich: Klick auf den Kopf führt zu `ziel`, `items` klappen darunter aus.

    `extra_keys`: weitere nav-Keys von Seiten, die diesen Bereich aktiv
    schalten, ohne einen eigenen Menüpunkt zu haben (Detailseiten, Umleitungen).
    """
    items = items or []
    alle_keys = [key] + list(extra_keys or []) + [k for it in items for k in it['keys']]
    return {'key': key, 'label': label, 'icon': icon, 'ziel': ziel,
            'items': items, 'alle_keys': alle_keys, 'badge': badge}


def _i(label, ziel, keys, section=None):
    """Untereintrag; `section` rendert davor eine kleine Zwischenüberschrift."""
    return {'label': label, 'ziel': ziel, 'keys': keys, 'section': section}


def nav_gruppen():
    """Die fünf Bereiche der Anwendung.

    Ohne Argument: Es gibt genau eine Navigation. Bis E1.1 nahm diese Funktion
    einen `modus` entgegen und lieferte zwei verschiedene Strukturen.
    """
    return [
        # ── HEUTE ────────────────────────────────────────────────────────────
        # Der Bereichskopf zeigt auf `/neu/` — die Startseite IST der
        # Arbeitsvorrat (seit 4b.13). Ein zusätzlicher Eintrag «Arbeit» wäre ein
        # zweiter Weg auf dieselbe Seite: keine Auswahl, sondern eine Frage, die
        # der Benutzer nicht beantworten kann.
        _g('heute', 'Heute', 'fa-inbox', '/neu/', [
            _i('Zulauf', '/neu/zulauf/', ['zulauf']),
            _i('Termine', '/neu/termine/', ['termine']),
            _i('Pendenzen', '/neu/pendenzen/', ['pendenzen']),
            _i('Fristen', '/neu/fristen/', ['fristen']),
            # «Vertretung» statt «Abwesenheiten»: Die Seite wird aufgeschlagen,
            # wenn jemand wissen will, wer für wen einspringt — nicht, wenn
            # jemand Ferien einträgt.
            _i('Vertretung', '/neu/abwesenheiten/', ['abwesenheiten']),
        ], extra_keys=['dashboard', 'faelle', 'arbeit']),

        # ── AKTEN ────────────────────────────────────────────────────────────
        # Die Register in der Reihenfolge, in der man sie aufschlägt: vom
        # Auftraggeber über das Haus zur einzelnen Person. Darunter die
        # laufenden Vorgänge, die an diesen Akten hängen.
        _g('akten', 'Akten', 'fa-folder-open', '/neu/liegenschaften/', [
            _i('Mandate', '/neu/mandate/', ['mandate']),
            _i('Liegenschaften', '/neu/liegenschaften/', ['liegenschaften']),
            _i('Objekte', '/neu/objekte/', ['objekte']),
            _i('Mietverhältnisse', '/neu/vertraege/', ['vertraege']),
            _i('Personen', '/neu/personen/', ['personen']),
            _i('Dienstleister', '/neu/dienstleister/', ['dienstleister']),
            # Schaden und Mieterwechsel sind fachlich Fälle, keine Aktentypen.
            # Ihre Listen bleiben, bis die Fallansicht sie ersetzt.
            _i('Schäden', '/neu/schaeden/', ['schadensfaelle'], section='Vorgänge'),
            _i('Mieterwechsel', '/neu/mieterwechsel/', ['mieterwechsel']),
            _i('Vermarktung', '/neu/vermarktung/', ['vermarktung']),
            _i('Bewerbungen', '/neu/bewerbungen/', ['bewerbungen']),
            _i('Ersatz & Ausstattung', '/neu/ersatzplanung/', ['assets']),
        ], badge='schaeden'),

        # ── LÄUFE ────────────────────────────────────────────────────────────
        # Alles, was einen Zustand hat und blockieren kann. Der Bereich fehlte
        # im Einfachmodus vollständig, obwohl die Seiten seit 4b.5 stehen.
        _g('laeufe', 'Läufe', 'fa-arrows-rotate', '/neu/laeufe/', [
            _i('Sollstellung', '/neu/sollstellung/', ['sollstellung'], section='Monat'),
            _i('Bankabgleich', '/neu/bankabgleich/', ['bankabgleich']),
            _i('Mahnwesen', '/neu/mahnwesen/', ['mahnwesen']),
            _i('Zahllauf', '/neu/zahllauf/', ['zahllauf']),
            _i('Nebenkosten', '/neu/nebenkosten/', ['nebenkosten'], section='Periodisch'),
            _i('Mietzins', '/neu/mietzins/', ['mietzins']),
            _i('MWST', '/neu/mwst/', ['mwst']),
        ]),

        # ── FINANZEN ─────────────────────────────────────────────────────────
        # Register und Konten. Handlungen führen in den zugehörigen Lauf.
        _g('finanzen', 'Finanzen', 'fa-coins', '/neu/finanzen/', [
            _i('Mieterkonten', '/neu/mieterkonten/', ['mieterkonten'], section='Forderungen'),
            _i('Debitoren', '/neu/debitoren/', ['debitoren']),
            _i('Kautionen', '/neu/kautionen/', ['kautionen']),
            _i('Kreditoren', '/neu/kreditoren/', ['kreditoren'], section='Verbindlichkeiten'),
            _i('Lieferantenkonten', '/neu/lieferantenkonten/', ['lieferantenkonten']),
            _i('Bankkonten', '/neu/bankkonten/', ['bankkonten'], section='Konten'),
            _i('Buchhaltung', '/neu/buchhaltung/', ['buchhaltung']),
            _i('Kontenplan & Salden', '/neu/kontenplan/', ['kontenplan']),
            _i('Anlagen & Abschluss', '/neu/anlagen/', ['anlagen']),
            _i('Hypotheken', '/neu/hypotheken/', ['hypotheken']),
        ]),

        # ── BERICHTE ─────────────────────────────────────────────────────────
        _g('berichte', 'Berichte', 'fa-chart-pie', '/neu/berichte/', [
            _i('Übersicht', '/neu/berichte/', ['berichte']),
            _i('Auswertung', '/neu/auswertung/', ['auswertung']),
        ]),
    ]


def fw_navigation(request):
    """Context-Processor: Navigationsstruktur für base.html.

    Nur für angemeldete Team-Mitglieder — Portal-Nutzer sehen keine Leiste.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    try:
        from core.auth import hat_rolle, TEAM_ROLLEN
        if not hat_rolle(user, TEAM_ROLLEN):
            return {}
    except Exception:
        return {}

    gruppen = nav_gruppen()

    # Flache Liste für die ⌘K-Palette (Label → URL, inkl. Untereinträge).
    #
    # NOCH NUR SEITEN, KEINE DATENSÄTZE: Wer «Blaser» tippt, findet hier nichts
    # — die Datensatzsuche liegt getrennt in `fw_suche`. Das ist Befund B7 und
    # die Aufgabe von E1.2. Bis dahin bleibt es bei zwei Suchen, und das ist
    # hier vermerkt, damit es nicht als erledigt gilt.
    palette = []
    for g in gruppen:
        if g['ziel']:
            palette.append({'label': g['label'], 'url': g['ziel']})
        for it in g['items']:
            palette.append({'label': it['label'], 'url': it['ziel'], 'gruppe': g['label']})
    palette += [
        {'label': 'Dokumente', 'url': '/neu/dokumente/'},
        {'label': 'Kommunikation', 'url': '/neu/kommunikation/'},
        {'label': 'Regelwerk', 'url': '/neu/regelwerk/', 'gruppe': 'Einstellungen'},
        {'label': 'Einstellungen', 'url': '/neu/einstellungen/'},
        {'label': 'Zwei-Faktor-Anmeldung', 'url': '/konto/zwei-faktor/'},
    ]
    return {'fw_nav_gruppen': gruppen, 'fw_palette': palette,
            'fw_einstellungen_keys': EINSTELLUNGEN_KEYS}
