"""Das Aktenregister — ein Reitersatz für alle Aktentypen.

WARUM

Heute definiert jede Detailseite ihre eigenen Reiter, direkt in der View:

    Liegenschaft   objekte · finanzen · technik · unterhalt · fristen · schaeden · dokumente
    Objekt         uebersicht · fotos · raumbuch · verhaeltnisse · mietzins · geraete · zaehler · schluessel
    Mietverhältnis uebersicht · finanzen · mietzins · schaeden · pendenzen · formulare · dokumente · verlauf
    Person         uebersicht · vertraege · finanzen · dokumente · aktivitaet · verlauf
    Schaden        uebersicht · verlauf · handwerker · fotos

Sieben, acht, acht, sechs und vier Reiter — kein Satz deckungsgleich mit einem
anderen. Wer die Vertragsakte bedienen kann, muss die Objektakte neu lernen.

Das Konzept (`docs/KONZEPT-UI.md`, Abschnitt 4) legt dagegen fest: **fünf feste
Reiter überall, dazu höchstens einer je Typ.** Dieses Modul ist die einzige
Stelle, an der das steht.

WIE DER ÜBERGANG FUNKTIONIERT

`aus_alt()` bildet die heutigen Reiter auf die neuen ab. Eine bestehende View
ändert damit **eine Zeile** und behält ihre Zähler. Dass dabei mehrere alte
Reiter auf einen neuen fallen, ist keine Panne, sondern der Zweck: Aus
`mietzins`, `formulare` und `verlauf` werden Abschnitte innerhalb eines
Reiters, keine eigenen Reiter.

Der umgekehrte Fall wäre der gefährliche — ein alter Reiter ohne Ziel. Er fiele
stillschweigend aus der Oberfläche, und der Inhalt dahinter wäre unerreichbar.
`test_jeder_alte_reiter_hat_ein_ziel` schliesst das aus.
"""
from dataclasses import dataclass, field

#: Die fünf festen Reiter, in dieser Reihenfolge, für jeden Aktentyp.
#:
#: **Stammdaten steht vorn, nicht Chronik** (Entscheid 19.08.2026). Der erste
#: Reiter ist zugleich der Landeplatz: Wer eine Akte aufschlägt, will wissen,
#: *was* das ist — Konditionen, Fristen, Beteiligte —, nicht *wer zuletzt was
#: getan hat*. Das Protokoll ist eine Nachschlagefläche und steht deshalb
#: dahinter. `KONZEPT-UI.md` Abschnitt 2 (G6) und 4 sind mitgeändert.
REITER_FIX = ('stammdaten', 'chronik', 'finanzen', 'dokumente', 'faelle')

BEZEICHNUNGEN = {
    'chronik': 'Chronik',
    'stammdaten': 'Stammdaten',
    'finanzen': 'Finanzen',
    'dokumente': 'Dokumente',
    'faelle': 'Fälle',
}

#: Welcher Reiter welchen Funktionsschlüssel braucht. Nicht genannte sind frei.
REITER_ENTITLEMENT = {
    'faelle': 'faelle',
}


@dataclass(frozen=True)
class Aktentyp:
    schluessel: str
    bezeichnung: str
    modell: str                      # 'app_label.Modell'
    eigener_reiter: tuple = ()       # (schluessel, Bezeichnung) oder leer
    #: Abbildung der heutigen Reiter auf die neuen.
    alt: dict = field(default_factory=dict)

    @property
    def reiter(self):
        """Die Reiter dieses Typs: fünf feste, dann höchstens einer eigener."""
        satz = list(REITER_FIX)
        if self.eigener_reiter:
            satz.append(self.eigener_reiter[0])
        return tuple(satz)

    def bezeichnung_von(self, reiter):
        if self.eigener_reiter and reiter == self.eigener_reiter[0]:
            return self.eigener_reiter[1]
        return BEZEICHNUNGEN[reiter]


AKTENTYPEN = {
    'mandat': Aktentyp(
        'mandat', 'Mandat', 'crm.Eigentuemer',
        eigener_reiter=('liegenschaften', 'Liegenschaften'),
        alt={'uebersicht': 'stammdaten', 'abrechnung': 'finanzen',
             'kontokorrent': 'finanzen', 'dokumente': 'dokumente',
             'verlauf': 'chronik'}),

    'liegenschaft': Aktentyp(
        'liegenschaft', 'Liegenschaft', 'portfolio.Liegenschaft',
        eigener_reiter=('einheiten', 'Einheiten'),
        alt={'objekte': 'einheiten', 'finanzen': 'finanzen',
             'technik': 'stammdaten', 'unterhalt': 'stammdaten',
             'fristen': 'faelle', 'schaeden': 'faelle',
             'dokumente': 'dokumente', 'uebersicht': 'stammdaten',
             'verlauf': 'chronik'}),

    'objekt': Aktentyp(
        'objekt', 'Objekt', 'portfolio.Einheit',
        eigener_reiter=('ausstattung', 'Ausstattung'),
        alt={'uebersicht': 'stammdaten', 'fotos': 'dokumente',
             'raumbuch': 'ausstattung', 'geraete': 'ausstattung',
             'zaehler': 'ausstattung', 'schluessel': 'ausstattung',
             'verhaeltnisse': 'chronik', 'mietzins': 'finanzen',
             'dokumente': 'dokumente', 'verlauf': 'chronik'}),

    'mietverhaeltnis': Aktentyp(
        'mietverhaeltnis', 'Mietverhältnis', 'rentals.Mietvertrag',
        eigener_reiter=('nebenkosten', 'Nebenkosten'),
        alt={'uebersicht': 'stammdaten', 'finanzen': 'finanzen',
             'mietzins': 'stammdaten', 'schaeden': 'faelle',
             'pendenzen': 'faelle', 'formulare': 'dokumente',
             'dokumente': 'dokumente', 'verlauf': 'chronik',
             'nebenkosten': 'nebenkosten'}),

    'person': Aktentyp(
        'person', 'Person', 'crm.Mieter',
        eigener_reiter=('rollen', 'Rollen'),
        alt={'uebersicht': 'stammdaten', 'vertraege': 'rollen',
             'finanzen': 'finanzen', 'dokumente': 'dokumente',
             'aktivitaet': 'chronik', 'verlauf': 'chronik'}),

    'dienstleister': Aktentyp(
        'dienstleister', 'Dienstleister', 'crm.Handwerker',
        eigener_reiter=('auftraege', 'Aufträge'),
        alt={'uebersicht': 'stammdaten', 'auftraege': 'auftraege',
             'finanzen': 'finanzen', 'dokumente': 'dokumente',
             'verlauf': 'chronik'}),

    'schaden': Aktentyp(
        'schaden', 'Schaden', 'tickets.SchadenMeldung',
        eigener_reiter=('handwerker', 'Handwerker & Kosten'),
        alt={'uebersicht': 'stammdaten', 'verlauf': 'chronik',
             'handwerker': 'handwerker', 'fotos': 'dokumente'}),
}


def typ_von(schluessel):
    if schluessel not in AKTENTYPEN:
        raise KeyError(
            f'{schluessel!r} ist kein bekannter Aktentyp. '
            f'Bekannt: {", ".join(sorted(AKTENTYPEN))}')
    return AKTENTYPEN[schluessel]


def reiter_fuer(typ_schluessel, zaehler=None, organisation=None):
    """Die Reiterliste eines Typs, im Format der bestehenden Oberfläche.

    Rückgabe: Liste aus `(schluessel, Bezeichnung, Zähler)` — genau das, was
    `fw/_detail_tabs.html` erwartet. Damit lässt sich eine View umstellen, ohne
    ihr Template anzufassen.

    Reiter, die einen Funktionsschlüssel verlangen, fallen weg, wenn die
    Verwaltung ihn nicht hat. Sie werden **nicht** ausgegraut dargestellt: Ein
    Reiter, der da ist und nichts tut, ist ärgerlicher als keiner.
    """
    from core.funktionen import hat_funktion

    typ = typ_von(typ_schluessel)
    zaehler = zaehler or {}
    liste = []
    for r in typ.reiter:
        schluessel = REITER_ENTITLEMENT.get(r)
        if schluessel and organisation is not None and not hat_funktion(
                organisation, schluessel):
            continue
        liste.append((r, typ.bezeichnung_von(r), zaehler.get(r) or None))
    return liste


def aus_alt(typ_schluessel, alte_liste, organisation=None):
    """Bildet eine heutige `tab_liste` auf den neuen Reitersatz ab.

    Zähler mehrerer alter Reiter, die auf denselben neuen fallen, werden
    addiert — sonst verschwände die Zahl des zweiten stillschweigend.
    """
    typ = typ_von(typ_schluessel)
    zaehler = {}
    for eintrag in alte_liste:
        # Beide Formen zulassen: die Views liefern `(schluessel, Label, Zahl)`,
        # eine Aufzaehlung der Schluessel ist beim Pruefen bequemer. Ein
        # Zeichenkettenzugriff `eintrag[0]` haette sonst den ERSTEN BUCHSTABEN
        # als Reiterschluessel genommen — und der Fehler waere erst an der
        # Meldung "Reiter 'u' hat kein Ziel" aufgefallen.
        if isinstance(eintrag, str):
            alt_schluessel, wert = eintrag, None
        else:
            alt_schluessel = eintrag[0]
            wert = eintrag[2] if len(eintrag) > 2 else None
        ziel = typ.alt.get(alt_schluessel)
        if ziel is None:
            raise KeyError(
                f'Der Reiter {alt_schluessel!r} des Typs {typ_schluessel!r} hat '
                f'kein Ziel im neuen Satz. Ohne Ziel fiele sein Inhalt aus der '
                f'Oberfläche — bitte in AKTENTYPEN eintragen.')
        if wert:
            zaehler[ziel] = (zaehler.get(ziel) or 0) + wert
    return reiter_fuer(typ_schluessel, zaehler, organisation)
