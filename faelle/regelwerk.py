"""Die Prüflogik des Regelwerks.

Hier steht das Rechnen. Die Regeln selbst — Fristlängen, Termine, Kanton —
stehen in der Datenbank (`faelle.regelwerk_models`), damit sie ohne Deployment
berichtigt werden können.

**Die Regeln sind bei Auslieferung nicht juristisch geprüft.** Entscheid vom
19.08.2026: bauen und nachträglich anpassen lassen. Jede Anwendung wird deshalb
protokolliert, inklusive des Stands der Regel, damit eine spätere Berichtigung
die betroffenen Fälle wiederfindet.
"""
from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone


@dataclass
class Befund:
    """Das Ergebnis einer Prüfung.

    `ok=False` heisst beanstandet, nicht verboten. Ob daraus eine Sperre wird,
    entscheidet die `verbindlichkeit` der Regel — nicht diese Rechnung.
    """

    ok: bool
    meldung: str = ''
    vorschlag: date | None = None
    rechnung: dict = field(default_factory=dict)

    def __bool__(self):
        return self.ok


def monate_dazu(ausgangsdatum, monate):
    """Datum plus N Monate, ohne zusätzliche Abhängigkeit.

    Der 31. Januar plus einen Monat ergibt den 28. bzw. 29. Februar — das ist
    die übliche Lesart und die einzige, die nicht in den März springt.
    """
    monat = ausgangsdatum.month - 1 + monate
    jahr = ausgangsdatum.year + monat // 12
    monat = monat % 12 + 1
    tag = min(ausgangsdatum.day, _tage_im_monat(jahr, monat))
    return date(jahr, monat, tag)


def _tage_im_monat(jahr, monat):
    import calendar
    return calendar.monthrange(jahr, monat)[1]


def termine_als_daten(termine, ab_datum, jahre=3):
    """Wandelt Termine der Form 'TT.MM' in konkrete Daten ab einem Stichtag.

    `termine` ist etwa `['31.03', '30.06', '30.09']`. Zurück kommen die
    nächsten Vorkommen dieser Termine, aufsteigend sortiert.
    """
    ergebnis = []
    for jahr in range(ab_datum.year, ab_datum.year + jahre + 1):
        for eintrag in termine:
            tag, monat = (int(t) for t in eintrag.split('.'))
            tag = min(tag, _tage_im_monat(jahr, monat))
            kandidat = date(jahr, monat, tag)
            if kandidat >= ab_datum:
                ergebnis.append(kandidat)
    return sorted(ergebnis)


def kuendigungstermin(zugang, gewuenschter_termin, termine, frist_monate=3):
    """Prüft, ob eine Kündigung auf den genannten Termin wirken kann.

    ``zugang``            Tag, an dem die Kündigung beim Empfänger ankam.
                          Nicht der Poststempel — massgebend ist der Zugang.
    ``gewuenschter_termin`` Der in der Kündigung genannte Termin.
    ``termine``           Zulässige Termine als ['TT.MM', ...], aus Vertrag
                          oder Ortsüblichkeit.
    ``frist_monate``      Kündigungsfrist in Monaten.

    Beanstandet wird, wenn der genannte Termin vor dem Ablauf der Frist liegt
    oder gar kein zulässiger Termin ist. Im Beanstandungsfall steht im
    `vorschlag` der nächste Termin, der trägt.
    """
    if not termine:
        return Befund(
            ok=False,
            meldung='Für diesen Vertrag sind keine Kündigungstermine hinterlegt. '
                    'Ohne Termine lässt sich die Kündigung nicht prüfen.',
            rechnung={'zugang': str(zugang)})

    fristende = monate_dazu(zugang, frist_monate)
    moegliche = termine_als_daten(termine, fristende)
    naechster = moegliche[0] if moegliche else None

    rechnung = {
        'zugang': str(zugang),
        'frist_monate': frist_monate,
        'fristende': str(fristende),
        'zulaessige_termine': list(termine),
        'naechster_moeglicher': str(naechster) if naechster else None,
        'gewuenscht': str(gewuenschter_termin) if gewuenschter_termin else None,
    }

    if gewuenschter_termin is None:
        return Befund(ok=True, vorschlag=naechster, rechnung=rechnung,
                      meldung=f'Nächstmöglicher Termin: {_de(naechster)}.')

    # Ist der genannte Termin überhaupt einer der zulässigen?
    ist_zulaessig = any(
        gewuenschter_termin.day == min(int(e.split('.')[0]),
                                       _tage_im_monat(gewuenschter_termin.year,
                                                      int(e.split('.')[1])))
        and gewuenschter_termin.month == int(e.split('.')[1])
        for e in termine)

    if not ist_zulaessig:
        return Befund(
            ok=False, vorschlag=naechster, rechnung=rechnung,
            meldung=(f'{_de(gewuenschter_termin)} ist kein zulässiger '
                     f'Kündigungstermin. Zulässig sind: {", ".join(termine)}. '
                     f'Nächster möglicher Termin: {_de(naechster)}.'))

    if gewuenschter_termin < fristende:
        monate = _monate_zwischen(gewuenschter_termin, naechster)
        return Befund(
            ok=False, vorschlag=naechster, rechnung=rechnung,
            meldung=(f'Der Termin {_de(gewuenschter_termin)} ist nicht gültig. '
                     f'Bei Zugang am {_de(zugang)} endet die {frist_monate}-monatige '
                     f'Frist am {_de(fristende)}; der genannte Termin liegt davor. '
                     f'Nächster zulässiger Termin: {_de(naechster)} '
                     f'({monate} Monate später).'))

    return Befund(ok=True, vorschlag=gewuenschter_termin, rechnung=rechnung,
                  meldung=f'Termin {_de(gewuenschter_termin)} ist gültig.')


def _monate_zwischen(frueher, spaeter):
    return (spaeter.year - frueher.year) * 12 + (spaeter.month - frueher.month)


def _de(d):
    return d.strftime('%d.%m.%Y') if d else '—'


# ---------------------------------------------------------------------------
# Anbindung an die Datenbank
# ---------------------------------------------------------------------------
#: Welche Parameter eine Regelart erwartet. Wird von den Tests geprüft, damit
#: ein Regelsatz nicht mit falschen Schlüsseln angelegt wird und erst beim
#: Anwenden auffällt.
ERWARTETE_PARAMETER = {
    'kuendigungstermin': {'termine', 'frist_monate'},
    'zahlungsfrist': {'frist_tage', 'kuendigungsfrist_tage'},
    'mietzins_zustellung': {'vorlauf_tage'},
    'kaution_hoechstbetrag': {'monatsmieten'},
}


def regel_holen(organisation, art, kanton=''):
    """Die passende Regel: erst kantonsgenau, sonst allgemein."""
    from faelle.regelwerk_models import Regel

    grund = Regel.objects.filter(
        art=art, aktiv=True, regelsatz__aktiv=True,
        regelsatz__organisation=organisation)
    if kanton:
        treffer = grund.filter(regelsatz__kanton=kanton).first()
        if treffer:
            return treffer
    return grund.filter(regelsatz__kanton='').first()


def kaution_hoechstbetrag(kaution, nettomiete, nebenkosten=None,
                          kategorie='wohnen', hoechst_monate=3,
                          gilt_fuer=('wohnen',)):
    """Prüft, ob eine Kaution die Obergrenze überschreitet (Art. 257e OR).

    ``kaution``        vereinbarter Betrag in Franken.
    ``nettomiete``     monatlicher Nettomietzins.
    ``nebenkosten``    monatliche Nebenkosten — **gehören zur Basis**, siehe
                       unten. ``None`` wird als 0 gerechnet.
    ``kategorie``      mietrechtliche Einordnung des Objekts.
    ``hoechst_monate`` Grenze in Monatszinsen, aus der Regel.
    ``gilt_fuer``      Kategorien, für die die Grenze überhaupt gilt.

    DIE BASIS IST NETTO + NEBENKOSTEN — WEIL SIE ES IM BESTAND IST

    Die erste Fassung dieser Regel rechnete auf dem Nettozins allein, mit der
    Begründung, Art. 257e spreche vom Mietzins und die Nebenkosten seien
    Auslagenersatz. Das mag rechtlich stimmen — aber `Mietvertrag.save()`
    klemmt seit jeher auf **Netto + Nebenkosten**, und zwei Rechnungen für
    eine Vorschrift widersprechen sich.

    Nachgemessen, bei Netto 1'500 und NK 200:

        erfasst 5'000  ->  gespeichert 5'000  ->  Regel BEANSTANDET
        erfasst 6'000  ->  geklemmt   5'100  ->  Regel BEANSTANDET

    Im zweiten Fall beanstandete die Regel einen Betrag, den die Anwendung
    soeben selbst hergestellt hatte. Ein Sachbearbeiter sieht dort eine
    Warnung zu einer Zahl, die er nie eingegeben hat.

    Übernommen ist deshalb der Wert aus dem Bestand — so verlangt es der
    Grundsatz für Fachwerte: nachsehen, übernehmen, und einen Zweifel MELDEN
    statt ihn zu entscheiden. Ob Art. 257e den Netto- oder den Bruttozins
    meint, ist eine Rechtsfrage und hier offen; sie steht auf der Liste.

    ART. 257e ABS. 2 OR GILT NUR FÜR WOHNRÄUME

    Bei Geschäftsräumen ist die Sicherheit frei vereinbar. Eine Regel, die
    dort warnt, wäre schlimmer als keine: Wer bei jedem Gewerbevertrag eine
    unbegründete Warnung wegklickt, klickt sie auch beim Wohnungsvertrag weg.

    WANN SIE ÜBERHAUPT ANSCHLÄGT

    `Mietvertrag.save()` klemmt bereits — ein über die Oberfläche erfasster
    Vertrag kann die Grenze gar nicht überschreiten. Die Regel greift dort,
    wo die Klemme nicht läuft: bei `.update()`, `bulk_create()`, Importen und
    Datenmigrationen. Nachgemessen: Ein per `.update()` gesetzter Betrag von
    9'000 bleibt stehen und wird hier beanstandet.

    WAS SIE NICHT TUT

    Sie sperrt nicht — das tut die Klemme in `save()`, und die ist die
    eigentliche Durchsetzung. Diese Regel macht die Grenze SICHTBAR und
    protokolliert ihre Anwendung.
    """
    if kategorie not in tuple(gilt_fuer):
        return Befund(
            ok=True,
            meldung=(f'Keine gesetzliche Obergrenze: Art. 257e OR gilt für '
                     f'Wohnräume, hier «{kategorie}».'),
            rechnung={'kategorie': kategorie, 'gilt': False})

    basis = (nettomiete or 0) + (nebenkosten or 0)
    if basis <= 0:
        return Befund(
            ok=True,
            meldung='Ohne Mietzins lässt sich die Grenze nicht rechnen.',
            rechnung={'nettomiete': str(nettomiete),
                      'nebenkosten': str(nebenkosten)})

    grenze = basis * hoechst_monate
    rechnung = {
        'nettomiete': str(nettomiete), 'nebenkosten': str(nebenkosten or 0),
        'basis': str(basis), 'hoechst_monate': hoechst_monate,
        'grenze': str(grenze), 'kaution': str(kaution),
        'monate_ist': str(round(kaution / basis, 2)),
    }
    if kaution <= grenze:
        return Befund(
            ok=True,
            meldung=(f'{kaution} liegt innerhalb von {hoechst_monate} '
                     f'Monatszinsen ({grenze}).'),
            rechnung=rechnung)
    return Befund(
        ok=False,
        meldung=(f'{kaution} übersteigt {hoechst_monate} Monatszinse '
                 f'({grenze}) um {kaution - grenze}. Art. 257e Abs. 2 OR — '
                 f'die Vereinbarung ist insoweit nichtig.'),
        rechnung=rechnung)


def pruefen(art, organisation, fall=None, kanton='', protokollieren=True, **eingabe):
    """Wendet eine Regel an und protokolliert die Anwendung.

    Gibt `(Befund, Regelanwendung | None)` zurück. Fehlt die Regel, ist der
    Befund `ok` mit Hinweis — eine fehlende Regel darf nicht wie eine verletzte
    aussehen.
    """
    from faelle.regelwerk_models import Regelanwendung

    regel = regel_holen(organisation, art, kanton)
    if regel is None:
        return Befund(ok=True, meldung='Für diese Prüfung ist keine Regel hinterlegt.'), None

    parameter = dict(regel.parameter or {})
    if art == 'kuendigungstermin':
        befund = kuendigungstermin(
            zugang=eingabe['zugang'],
            gewuenschter_termin=eingabe.get('gewuenschter_termin'),
            termine=eingabe.get('termine') or parameter.get('termine', []),
            frist_monate=eingabe.get('frist_monate')
            or parameter.get('frist_monate', 3))
    elif art == 'kaution_hoechstbetrag':
        befund = kaution_hoechstbetrag(
            kaution=eingabe['kaution'],
            nettomiete=eingabe['nettomiete'],
            # Die Nebenkosten gehoeren zur Basis — dieselbe wie in
            # `Mietvertrag.save()`. Fehlen sie im Aufruf, rechnet die Regel
            # STRENGER als die Klemme und beanstandet Betraege, die die
            # Anwendung selbst zulaesst.
            nebenkosten=eingabe.get('nebenkosten'),
            kategorie=eingabe.get('kategorie', 'wohnen'),
            hoechst_monate=parameter.get('hoechst_monate', 3),
            gilt_fuer=parameter.get('gilt_fuer', ('wohnen',)))
    else:
        raise NotImplementedError(
            f'Die Regelart {art!r} ist als Datenmodell vorhanden, aber noch nicht '
            f'gerechnet. Sie kommt in einer späteren Etappe dazu.')

    anwendung = None
    if protokollieren:
        anwendung = Regelanwendung(
            organisation=organisation, art=art,
            regel_stand=regel.regelsatz.stand,
            geprueft_war=regel.regelsatz.geprueft,
            fall=fall,
            eingabe={k: str(v) for k, v in eingabe.items()},
            ergebnis=befund.rechnung,
            befund=Regelanwendung.OK if befund.ok else Regelanwendung.BEANSTANDET,
            meldung=befund.meldung,
            zeitpunkt=timezone.now())
        anwendung.save()
    return befund, anwendung


def sperrt(regel, befund):
    """Führt dieser Befund zu einer Sperre?

    Nur wenn die Regel als `sperre` gekennzeichnet ist **und** der Regelsatz
    als geprüft gilt. Eine ungeprüfte Regel sperrt nie — sie warnt.
    """
    from faelle.regelwerk_models import Regel as _R
    if befund.ok:
        return False
    return regel.verbindlichkeit == _R.SPERRE and regel.regelsatz.geprueft
