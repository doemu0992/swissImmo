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
    statt ihn zu entscheiden.

    DIE RECHTSFRAGE IST NACHGESCHLAGEN — UND DER BESTAND HATTE RECHT

    Ob Art. 257e den Netto- oder den Bruttozins meint, stand hier als offen.
    Nachgesehen (E2.33): Die beiden Verbände, die sich sonst gegenüberstehen,
    sagen dasselbe — massgebend ist der Bruttozins einschliesslich der
    monatlichen Nebenkostenbeiträge.

    Wenn Mieter- und Vermieterseite in einer Auslegungsfrage übereinstimmen,
    ist das das stärkste Signal, das ohne Bundesgerichtsentscheid zu haben
    ist — beide hätten ein Interesse an der anderen Lesart.

    WIE WEIT DIE PRÜFUNG REICHT

    Nicht so weit, wie der Absatz darüber klingt. Die Seiten von
    Mieterinnen- und Mieterverband, Hauseigentümerverband und fedlex sind
    aus dieser Umgebung nicht erreichbar (der Egress-Proxy blockiert sie).
    Belegt ist die Aussage durch **zwei unabhängige Suchen**, davon eine auf
    `hev-schweiz.ch` und amtliche Domains eingeschränkt; beide ergaben
    Brutto einschliesslich Nebenkosten.

    Was hier NICHT geprüft wurde: ob einzelne Anbieterseiten im Netz eine
    andere Basis nennen. Auch das wäre unerheblich — eine
    Kautionsvergleichsseite ist keine Rechtsquelle —, aber es steht hier
    nicht als Feststellung, weil es keine ist.

    BLEIBT: Die Regel ist damit besser begründet, aber nicht juristisch
    geprüft, und kein Wortlaut wurde im Original gelesen. Der Regelsatz
    bleibt ungeprüft und warnt deshalb nur. Wer ihn unter /neu/regelwerk/ als
    geprüft kennzeichnet, legt diesen Punkt einer Anwältin vor — mit dem
    Hinweis, dass beide Verbände Brutto sagen.

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


#: Wie lang die Zahlungsfrist nach Art. 257d Abs. 1 OR mindestens ist —
#: je mietrechtlicher Kategorie.
#:
#: DER BESTAND KANNTE DIE ZWEITE ZAHL, DIE ETAPPE NICHT
#:
#: E2.34 kam mit einem festen Wert von dreissig Tagen und der Begruendung:
#: «Anders als bei der Kaution gibt es hier keinen Geltungsbereich: Die Frist
#: gilt fuer Wohn- UND Geschaeftsraeume.» Beide genannten Faelle stimmen —
#: der dritte fehlte.
#:
#: `core/views/fw/kuendigung.py` rechnet seit jeher:
#:
#:     min_frist = 30 if v.ist_geschuetzt else 10   # Art. 257d Abs. 1
#:
#: `ist_geschuetzt` ist `mietrecht_kategorie in ('wohnen', 'gewerbe')`. Fuer
#: ein Nebenobjekt — gesondert vermieteter Parkplatz, Garage, Bastelraum —
#: sind es also ZEHN Tage, nicht dreissig.
#:
#: Ohne diese Unterscheidung haette die Regel bei einem Parkplatzvertrag
#: «zwanzig Tage zu frueh» gemeldet, wo Gesetz und Bestand die Kuendigung
#: zulassen. Das ist genau die unbegruendete Warnung, die dieselbe Etappe bei
#: der Kaution zu Recht vermeidet: Wer sie wegklickt, klickt auch die
#: begruendete weg.
#:
#: Das Vokabular stammt aus `portfolio.Einheit.MIETRECHT_KATEGORIE` — dort
#: gibt es genau diese drei Werte.
ZAHLUNGSFRIST_JE_KATEGORIE = {
    'wohnen': 30,
    'gewerbe': 30,
    'nebenobjekt': 10,
}


def zahlungsfrist(zugang, gekuendigt_am=None, mindest_tage=None,
                  kategorie='wohnen', je_kategorie=None):
    """Prüft die Zahlungsfrist bei Verzug (Art. 257d Abs. 1 OR).

    ``zugang``         Tag, an dem die Mahnung mit Kündigungsandrohung beim
                       Mieter ANKAM. Nicht der Versandtag — massgebend ist
                       der Zugang, wie beim Kündigungstermin.
    ``gekuendigt_am``  Tag der Kündigung. ``None`` = noch nicht gekündigt;
                       dann wird der frühestmögliche Tag vorgeschlagen.
    ``mindest_tage``   Feste Frist aus der Regel. ``None`` = nach Kategorie
                       (Normalfall), sonst hat dieser Wert Vorrang.
    ``kategorie``      `wohnen`, `gewerbe` oder `nebenobjekt`.
    ``je_kategorie``   Abweichende Zuordnung aus der Regel.

    WORUM ES GEHT

    Art. 257d Abs. 1 OR: Ist der Mieter mit einer fälligen Zahlung im
    Rückstand, setzt ihm der Vermieter SCHRIFTLICH eine Zahlungsfrist und
    droht an, bei Nichtzahlung zu kündigen. Bei Wohn- und Geschäftsräumen
    beträgt diese Frist mindestens dreissig Tage.

    Wird zu früh gekündigt, ist die Kündigung NICHTIG — nicht anfechtbar,
    sondern von Anfang an wirkungslos. Der Vermieter merkt das oft erst vor
    der Schlichtungsbehörde, nachdem er das Verfahren schon geführt hat.

    Genau deshalb gehört das zu den Regeln und nicht in eine Fristenliste:
    Die Liste sagt, wann etwas fällig ist. Die Regel sagt, dass dieser
    Kündigungstermin nicht durchgeht.

    ZEHN TAGE BEI NEBENOBJEKTEN

    Die dreissig Tage gelten für Wohn- und Geschäftsräume. Bei einem
    gesondert vermieteten Parkplatz, einer Garage oder einem Bastelraum sind
    es zehn — siehe `ZAHLUNGSFRIST_JE_KATEGORIE` und die dortige Begründung.

    DIE FRIST BEGINNT MIT DEM ZUGANG

    Nicht mit dem Poststempel und nicht mit dem Datum auf der Mahnung.
    Dieselbe Unterscheidung wie beim Kündigungstermin — sie ist der
    häufigste Fehler in beiden Fällen.

    Diese Funktion bekommt den Zugang bereits als Datum. Wer vom Versandtag
    aus rechnet, schlägt vorher den Zustellpuffer auf (Postweg plus
    siebentägige Abholfrist beim Einschreiben); `fw_verzug_257d` macht das
    mit `ZUSTELL_PUFFER = 7`.

    DER TAG DES ZUGANGS ZAEHLT NICHT MIT

    Art. 77 Abs. 1 Ziff. 3 OR: Bei einer nach Tagen bestimmten Frist zählt
    der Tag, an dem sie zu laufen beginnt, nicht mit. Zugang am 1. plus
    dreissig Tage ergibt den 31. als letzten Tag der Frist; gekündigt werden
    darf ab dem 1. des Folgemonats.
    """
    from datetime import timedelta

    tabelle = je_kategorie or ZAHLUNGSFRIST_JE_KATEGORIE
    if mindest_tage is None:
        mindest_tage = tabelle.get(kategorie, 30)

    fruehestens = zugang + timedelta(days=mindest_tage + 1)
    rechnung = {
        'zugang': zugang.isoformat(), 'mindest_tage': mindest_tage,
        'fruehestens': fruehestens.isoformat(), 'kategorie': kategorie,
    }
    if gekuendigt_am is None:
        return Befund(
            ok=True,
            meldung=(f'Frist läuft bis und mit '
                     f'{(fruehestens - timedelta(days=1)).strftime("%d.%m.%Y")}; '
                     f'gekündigt werden darf ab '
                     f'{fruehestens.strftime("%d.%m.%Y")}.'),
            vorschlag=fruehestens, rechnung=rechnung)

    rechnung['gekuendigt_am'] = gekuendigt_am.isoformat()
    if gekuendigt_am >= fruehestens:
        return Befund(
            ok=True,
            meldung=(f'Die Zahlungsfrist von {mindest_tage} Tagen war am '
                     f'{gekuendigt_am.strftime("%d.%m.%Y")} abgelaufen.'),
            rechnung=rechnung)

    zu_frueh = (fruehestens - gekuendigt_am).days
    return Befund(
        ok=False,
        meldung=(f'Gekündigt {zu_frueh} Tag(e) zu früh: Die Frist nach '
                 f'Art. 257d OR läuft bis '
                 f'{(fruehestens - timedelta(days=1)).strftime("%d.%m.%Y")}. '
                 f'Eine vorher ausgesprochene Kündigung ist NICHTIG.'),
        vorschlag=fruehestens, rechnung=rechnung)


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
    elif art == 'zahlungsfrist':
        befund = zahlungsfrist(
            zugang=eingabe['zugang'],
            gekuendigt_am=eingabe.get('gekuendigt_am'),
            # `None` heisst «nach Kategorie» — nicht 30. Ein fester
            # Vorgabewert haette die Zehn-Tage-Frist bei Nebenobjekten
            # ueberschrieben, sobald die Regel keinen Parameter traegt.
            mindest_tage=parameter.get('mindest_tage'),
            kategorie=eingabe.get('kategorie', 'wohnen'),
            je_kategorie=parameter.get('je_kategorie'))
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
