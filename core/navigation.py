"""Zentrale Navigationsstruktur der /neu/-Oberfläche.

6 Bereiche ("Türen") statt 34 flacher Menüpunkte — mit zwei Modi:
  - 'einfach' (Standard): Klartext-Labels, Profi-Module hinter «Erweitert»
  - 'profi':  volle Tiefe mit Fachbegriffen, thematisch gruppiert

Die Struktur wird per Context-Processor (fw_navigation) an base.html geliefert
und dort generisch gerendert. Jede Seite meldet weiterhin ihren `nav`-Key —
`keys` pro Eintrag verbindet die bestehenden Keys mit der neuen Struktur
(kein View muss angepasst werden).
"""

UI_MODI = ('einfach', 'profi')
UI_MODUS_DEFAULT = 'einfach'
SESSION_KEY = 'ui_modus'

# nav-Keys von Seiten, die den Einstellungen-Link (Sidebar-Fuss) aktiv schalten
EINSTELLUNGEN_KEYS = ['einstellungen', 'account', 'abonnement', 'benutzer',
                      'logbuch', 'vorlagen', 'integrationen', 'rechtsgrundlagen']


def _g(key, label, icon, ziel, items=None, badge=None, extra_keys=None):
    """Gruppe ("Tür"): klick auf den Kopf navigiert zu `ziel`,
    `items` klappen darunter aus. `extra_keys`: weitere nav-Keys von Seiten,
    die diese Gruppe aktiv schalten (z.B. 'dashboard' → Heute)."""
    items = items or []
    alle_keys = [key] + list(extra_keys or []) + [k for it in items for k in it['keys']]
    return {'key': key, 'label': label, 'icon': icon, 'ziel': ziel,
            'items': items, 'alle_keys': alle_keys, 'badge': badge}


def _i(label, ziel, keys, section=None):
    """Untereintrag; `section` rendert davor eine kleine Zwischenüberschrift."""
    return {'label': label, 'ziel': ziel, 'keys': keys, 'section': section}


def nav_gruppen(modus):
    """Die 6 Bereiche für den gegebenen Modus (+ «Erweitert» im Einfachmodus)."""
    if modus == 'profi':
        return [
            _g('heute', 'Heute', 'fa-inbox', '/neu/', [
                _i('Pendenzen', '/neu/pendenzen/', ['pendenzen']),
                _i('Fristen-Center', '/neu/fristen/', ['fristen']),
            ], extra_keys=['dashboard']),
            _g('portfolio', 'Portfolio', 'fa-building', '/neu/liegenschaften/', [
                _i('Liegenschaften', '/neu/liegenschaften/', ['liegenschaften']),
                _i('Objekte', '/neu/objekte/', ['objekte']),
                _i('Schadensfälle', '/neu/schaeden/', ['schadensfaelle'], ),
                _i('Assets & Ausstattung', '/neu/assets/', ['assets']),
                _i('Hypotheken', '/neu/hypotheken/', ['hypotheken']),
            ], badge='schaeden'),
            _g('vermietung', 'Vermietung', 'fa-key', '/neu/vertraege/', [
                _i('Vermarktung', '/neu/vermarktung/', ['vermarktung']),
                _i('Bewerbungen', '/neu/bewerbungen/', ['bewerbungen']),
                _i('Verträge', '/neu/vertraege/', ['vertraege']),
                _i('Mieterwechsel', '/neu/mieterwechsel/', ['mieterwechsel']),
                _i('Mietzins', '/neu/mietzins/', ['mietzins']),
            ]),
            _g('finanzen', 'Finanzen', 'fa-coins', '/neu/finanzen/', [
                _i('Finanz-Cockpit', '/neu/finanzen/', ['finanzen']),
                _i('Bankabgleich', '/neu/bankabgleich/', ['bankabgleich'], section='Zahlungsverkehr'),
                _i('Bankkonten', '/neu/bankkonten/', ['bankkonten']),
                _i('Sollstellung', '/neu/sollstellung/', ['sollstellung'], section='Mieten'),
                _i('Debitoren', '/neu/debitoren/', ['debitoren']),
                _i('Mieterkonten', '/neu/mieterkonten/', ['mieterkonten']),
                _i('Mahnwesen', '/neu/mahnwesen/', ['mahnwesen']),
                _i('Kautionen', '/neu/kautionen/', ['kautionen']),
                _i('Kreditoren', '/neu/kreditoren/', ['kreditoren'], section='Rechnungen'),
                _i('Lieferantenkonten', '/neu/lieferantenkonten/', ['lieferantenkonten']),
                _i('Buchhaltung', '/neu/buchhaltung/', ['buchhaltung'], section='Abschluss'),
                _i('Nebenkosten', '/neu/nebenkosten/', ['nebenkosten']),
                _i('MWST', '/neu/mwst/', ['mwst']),
                _i('Anlagen & Abschluss', '/neu/anlagen/', ['anlagen']),
            ]),
            _g('berichte', 'Berichte', 'fa-chart-pie', '/neu/berichte/', [
                _i('Berichte-Hub', '/neu/berichte/', ['berichte']),
                _i('Auswertung', '/neu/auswertung/', ['auswertung']),
            ]),
            _g('kontakte', 'Kontakte', 'fa-user-group', '/neu/personen/', [
                _i('Personen', '/neu/personen/', ['personen']),
                _i('Dienstleister', '/neu/dienstleister/', ['dienstleister']),
                _i('Eigentümer & Mandate', '/neu/mandate/', ['mandate']),
            ]),
        ]
    # ── Einfachmodus: Klartext, weniger Tiefe, Rest unter «Erweitert» ──
    return [
        _g('heute', 'Heute', 'fa-inbox', '/neu/', extra_keys=['dashboard']),
        _g('portfolio', 'Meine Immobilien', 'fa-building', '/neu/liegenschaften/', [
            _i('Häuser', '/neu/liegenschaften/', ['liegenschaften']),
            _i('Wohnungen', '/neu/objekte/', ['objekte']),
            _i('Schäden', '/neu/schaeden/', ['schadensfaelle']),
        ], badge='schaeden'),
        _g('vermietung', 'Vermieten', 'fa-key', '/neu/vertraege/', [
            _i('Mieter & Verträge', '/neu/vertraege/', ['vertraege']),
            _i('Wohnung ausschreiben', '/neu/vermarktung/', ['vermarktung']),
            _i('Bewerbungen', '/neu/bewerbungen/', ['bewerbungen']),
            _i('Mieterwechsel', '/neu/mieterwechsel/', ['mieterwechsel']),
            _i('Miete anpassen', '/neu/mietzins/', ['mietzins']),
        ]),
        _g('finanzen', 'Geld', 'fa-coins', '/neu/mieterkonten/', [
            _i('Wer hat bezahlt?', '/neu/mieterkonten/', ['mieterkonten']),
            _i('Mahnungen', '/neu/mahnwesen/', ['mahnwesen']),
            _i('Rechnungen bezahlen', '/neu/kreditoren/', ['kreditoren']),
            _i('Nebenkosten', '/neu/nebenkosten/', ['nebenkosten']),
        ]),
        _g('berichte', 'Übersichten', 'fa-chart-pie', '/neu/berichte/', [
            _i('Berichte', '/neu/berichte/', ['berichte']),
            _i('Auswertung', '/neu/auswertung/', ['auswertung']),
        ]),
        _g('kontakte', 'Personen & Handwerker', 'fa-user-group', '/neu/personen/', [
            _i('Personen', '/neu/personen/', ['personen']),
            _i('Handwerker', '/neu/dienstleister/', ['dienstleister']),
        ]),
        # Profi-Module bleiben erreichbar, aber eingeklappt und optisch zurückgenommen.
        _g('erweitert', 'Erweitert', 'fa-toolbox', '', [
            _i('Finanz-Cockpit', '/neu/finanzen/', ['finanzen']),
            _i('Buchhaltung', '/neu/buchhaltung/', ['buchhaltung']),
            _i('Sollstellung', '/neu/sollstellung/', ['sollstellung']),
            _i('Debitoren', '/neu/debitoren/', ['debitoren']),
            _i('Bankabgleich', '/neu/bankabgleich/', ['bankabgleich']),
            _i('Bankkonten', '/neu/bankkonten/', ['bankkonten']),
            _i('Lieferantenkonten', '/neu/lieferantenkonten/', ['lieferantenkonten']),
            _i('Kautionen', '/neu/kautionen/', ['kautionen']),
            _i('MWST', '/neu/mwst/', ['mwst']),
            _i('Anlagen & Abschluss', '/neu/anlagen/', ['anlagen']),
            _i('Hypotheken', '/neu/hypotheken/', ['hypotheken']),
            _i('Assets & Ausstattung', '/neu/assets/', ['assets']),
            _i('Eigentümer & Mandate', '/neu/mandate/', ['mandate']),
            _i('Pendenzen', '/neu/pendenzen/', ['pendenzen']),
            _i('Fristen-Center', '/neu/fristen/', ['fristen']),
        ]),
    ]


def aktueller_modus(request):
    """UI-Modus aus der Session (Default: einfach)."""
    m = request.session.get(SESSION_KEY) if hasattr(request, 'session') else None
    return m if m in UI_MODI else UI_MODUS_DEFAULT


def fw_navigation(request):
    """Context-Processor: Navigationsstruktur + Modus für base.html.
    Nur für eingeloggte Team-Mitglieder (Portal-Nutzer sehen die Sidebar nicht)."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    try:
        from core.auth import hat_rolle, TEAM_ROLLEN
        if not hat_rolle(user, TEAM_ROLLEN):
            return {}
    except Exception:
        return {}
    modus = aktueller_modus(request)
    gruppen = nav_gruppen(modus)
    # Flache Liste für die ⌘K-Palette (Label → URL, inkl. Untereinträge)
    palette = []
    for g in gruppen:
        if g['ziel']:
            palette.append({'label': g['label'], 'url': g['ziel']})
        for it in g['items']:
            palette.append({'label': it['label'], 'url': it['ziel'], 'gruppe': g['label']})
    palette += [
        {'label': 'Dokumente', 'url': '/neu/dokumente/'},
        {'label': 'Kommunikation', 'url': '/neu/kommunikation/'},
        {'label': 'Einstellungen', 'url': '/neu/einstellungen/'},
    ]
    return {'ui_modus': modus, 'fw_nav_gruppen': gruppen, 'fw_palette': palette,
            'fw_einstellungen_keys': EINSTELLUNGEN_KEYS}
