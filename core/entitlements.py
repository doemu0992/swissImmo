"""Welche Funktion ab welcher Abo-Stufe — die eine Stelle, die es weiss.

WAS DIESE DATEI IST UND WAS NOCH NICHT

Schritt 1 aus `docs/PHASE-3-ENTITLEMENTS.md`: die Tabellen als Code, dazu die
Abfragen darauf. **Noch keine einzige Sperre.** Keine Ansicht ruft das hier
auf, kein Lauf, keine Vorlage — gemessen und im Test festgehalten.

Das ist Absicht. Eine Tabelle, die stimmt, ist die Voraussetzung dafür, dass
Sperren überhaupt richtig sein können; sie zusammen einzuführen hiesse, zwei
Fehlerquellen gleichzeitig zu öffnen.

DIE QUELLE IST `docs/MARKT.md`, NICHT DIESE DATEI

Die Zuschnitte stehen dort, kaufmännisch begründet. Hier stehen sie ein
zweites Mal, weil Code keine Markdown-Tabellen liest — und genau deshalb
prüft `core/tests/test_entitlements.py` beide gegeneinander. Zwei Quellen für
dieselbe Zahl sind die Stelle, an der Preisseite und Programm auseinander-
laufen; die Prüfung macht daraus eine Stelle, an der es auffällt.

WAS HIER BEWUSST FEHLT

- **Die Preise.** Sie sind laut MARKT.md aus Wettbewerbspreisen abgeleitet
  und nicht aus Kostenrechnung; der Entscheid steht aus. Der Code braucht sie
  nicht: Welche Funktion ab welcher Stufe gilt, entscheidet ihn — ob Team 119
  oder 139 kostet, nicht.
- **Die Speichergrenze.** Sie steht in der Tabelle, weil sie zur Struktur
  gehört, wird aber nicht durchgesetzt: Es gibt keine Speicher-Buchhaltung im
  Bestand. Eine Grenze ohne Zählung ist ein Versprechen ohne Deckung.
- **Die Zuordnung der heutigen drei Stufen auf diese vier.** `abo_plan` kennt
  `start`/`pro`/`premium`; `pro` und `premium` gibt es hier nicht. Offen, und
  `darf()` sagt es laut statt zu raten — siehe dort.
"""
from __future__ import annotations

#: Die vier Stufen, AUFSTEIGEND. Die Reihenfolge ist die Aussage: `team`
#: enthält alles aus `start`, `professional` alles aus `team`.
STUFEN: tuple[str, ...] = ('start', 'team', 'professional', 'enterprise')

#: Merkmal -> (ab welcher Stufe, Bezeichnung in `docs/MARKT.md`).
#:
#: Die zweite Hälfte ist kein Kommentar, sondern der Schlüssel, über den
#: `test_entitlements` diese Tabelle gegen MARKT.md prüft. Wer hier etwas
#: ändert, ohne es dort zu ändern, wird rot.
#:
#: NICHT AUFGEFÜHRT ist die Enterprise-Zeile «SLA, Premium-Support, Onboarding
#: inklusive». Sie ist organisatorisch — es gibt nichts zu sperren, und ein
#: Merkmal, hinter dem kein Code steht, wäre eine Zusage an eine Prüfstelle,
#: die sie nicht halten kann.
MERKMALE: dict[str, tuple[str, str]] = {
    'eigenes_logo':       ('team', 'Eigenes Logo, Vorlagenverwaltung'),
    'eigentuemerportal':  ('team', 'Eigentümerportal'),
    'mieterportal':       ('team', 'Mieterportal'),
    'laeufe':             ('team', 'Automatischer Mietenlauf, Mahnlauf'),
    'ki_belegerkennung':  ('team', 'KI-Belegerkennung mit Kontingent'),
    'mandatsabrechnung':  ('professional', 'Mandatsabrechnung, Verwaltungshonorar'),
    'konsolidierung':     ('professional', 'Konsolidierung über Mandate'),
    'pain001':            ('professional', 'pain.001-Zahlungsaufträge'),
    'branding':           ('professional', 'Mandantenspezifisches Branding'),
}

#: Grenze -> Wert je Stufe. `None` heisst unbegrenzt.
GRENZEN: dict[str, dict[str, int | None]] = {
    'einheiten': {'start': 25, 'team': 150, 'professional': 500, 'enterprise': 2000},
    'nutzer':    {'start': 2,  'team': 5,   'professional': 15,  'enterprise': None},
    'speicher':  {'start': 5,  'team': 50,  'professional': 150, 'enterprise': 300},
}

#: Grenzen, die es gibt, die aber NICHT durchgesetzt werden können.
#:
#: `speicher` in Gigabyte: Im Bestand existiert keine Stelle, die den
#: Speicherverbrauch je Organisation zählt. Solange das so ist, steht die Zahl
#: hier als Struktur und nirgends als Sperre — `grenze()` gibt sie heraus,
#: `grenze_durchsetzbar()` sagt nein.
NICHT_DURCHGESETZT: frozenset[str] = frozenset({'speicher'})


class UnbekannteStufe(ValueError):
    """Der Plan der Organisation steht nicht in `STUFEN`."""


class UnbekanntesMerkmal(KeyError):
    """Gefragt wurde nach etwas, das die Tabelle nicht kennt."""


def _stufe_von(organisation) -> str:
    """Die Stufe einer Organisation — oder eine deutliche Absage.

    WARUM HIER GEWORFEN UND NICHT GERATEN WIRD

    `crm.Organisation.abo_plan` kennt heute `start`/`pro`/`premium`. Von
    diesen dreien steht nur `start` auch in `STUFEN`; die Zuordnung der
    übrigen ist ein offener kaufmännischer Entscheid (siehe
    `docs/PHASE-3-ENTITLEMENTS.md`, Abschnitt 7).

    Zu raten wäre hier beides falsch: «im Zweifel alles erlauben» verschenkt
    den Ertrag stillschweigend, «im Zweifel sperren» sperrt einen zahlenden
    Kunden aus. Solange diese Datei von keiner Ansicht aufgerufen wird, kann
    ein Fehler niemandem schaden — und dann ist er das ehrlichste Ergebnis.

    Sobald die Zuordnung entschieden ist, wird dieser Zweig unerreichbar.
    """
    stufe = getattr(organisation, 'abo_plan', None)
    if stufe not in STUFEN:
        raise UnbekannteStufe(
            f'«{stufe}» ist keine der vier Stufen {STUFEN}. Die Zuordnung der '
            f'heutigen Pläne (start/pro/premium) auf die neue Struktur ist ein '
            f'offener Entscheid — siehe docs/PHASE-3-ENTITLEMENTS.md, '
            f'Abschnitt 7, Punkt 2.')
    return stufe


def stufe_mindestens(stufe: str, mindestens: str) -> bool:
    """Ist `stufe` mindestens so hoch wie `mindestens`?

    Reine Ordnung auf `STUFEN`, ohne Organisation und ohne Datenbank — damit
    sie sich einzeln prüfen lässt.
    """
    for name in (stufe, mindestens):
        if name not in STUFEN:
            raise UnbekannteStufe(f'«{name}» ist keine der vier Stufen {STUFEN}.')
    return STUFEN.index(stufe) >= STUFEN.index(mindestens)


def darf(organisation, merkmal: str) -> bool:
    """Trägt die Stufe dieser Organisation das Merkmal?

    Ein Merkmal, das die Tabelle nicht kennt, ist FREI — aber nicht
    stillschweigend: `UnbekanntesMerkmal` sagt, dass gefragt wurde, was es
    nicht gibt. Ein Tippfehler im Merkmalsnamen soll nicht als «erlaubt»
    durchgehen; genau so entsteht eine Sperre, die nie greift.
    """
    if merkmal not in MERKMALE:
        raise UnbekanntesMerkmal(
            f'«{merkmal}» steht nicht in MERKMALE. Frei ist, was dort fehlt — '
            f'aber ein Tippfehler soll nicht als «erlaubt» durchgehen.')
    ab_stufe, _bezeichnung = MERKMALE[merkmal]
    return stufe_mindestens(_stufe_von(organisation), ab_stufe)


def grenze(organisation, art: str) -> int | None:
    """Der Grenzwert dieser Organisation für `art`. `None` heisst unbegrenzt."""
    if art not in GRENZEN:
        raise UnbekanntesMerkmal(f'«{art}» steht nicht in GRENZEN.')
    return GRENZEN[art][_stufe_von(organisation)]


def grenze_durchsetzbar(art: str) -> bool:
    """Lässt sich diese Grenze überhaupt messen?

    Siehe `NICHT_DURCHGESETZT`. Wer eine Grenze prüft, ohne das hier zu
    fragen, baut eine Sperre auf eine Zahl, die niemand erhebt.
    """
    if art not in GRENZEN:
        raise UnbekanntesMerkmal(f'«{art}» steht nicht in GRENZEN.')
    return art not in NICHT_DURCHGESETZT
