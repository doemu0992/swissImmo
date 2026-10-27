"""Regelquelle für Index- und Staffelmiete (Art. 269b und 269c OR).

EINE Fassung der Regeln. Der Wizard-Endpunkt, `Mietvertrag.clean()`, das
Bearbeiten-Formular, die Staffel-Erfassung am Objekt, der Vertragstext und der
Bestandsbericht rufen alle `pruefe` auf. Eine zweite Fassung (etwa in
JavaScript) gibt es nicht.

Rechtsgrundlage, wie vom Auftraggeber freigegeben (recht.md vom 27.10.2026):

Indexmiete, Art. 269b OR, Art. 17 und 19 VMWG
- Index ist ausschliesslich der Landesindex der Konsumentenpreise (LIK).
- Vertrag für mindestens fünf Jahre; nach Art. 17 Abs. 4 VMWG erfüllt auch ein
  Vertrag, den der Vermieter fünf Jahre nicht kündigen kann.
- Die Erhöhung darf die Zunahme des LIK nicht übersteigen (Weitergabe höchstens
  100 %); sinkt der LIK, folgt der Mietzins.
- Ankündigung mit 30 Tagen auf ein Monatsende, amtliches Formular.

Staffelmiete, Art. 269c OR (Art. 269d Abs. 5 OR, Art. 19a VMWG)
- Vertrag für mindestens drei Jahre, höchstens einmal jährlich erhöht, die
  Erhöhung als Frankenbetrag. Die Auslegung «Vermieter-Unkündbarkeit statt
  Befristung» ist von Art. 17 Abs. 4 VMWG ÜBERNOMMEN (analog); eine eigene
  Verordnungsstelle für die Staffel wurde nicht gefunden. OFFENER FACHPUNKT.

Kombination: Eine Indexklausel darf nicht mit einer Staffelung kombiniert
werden (BGE 124 III 57 E. 3a).

Fachpunkt Schalttag: Für ein Mietbeginn-Datum am 29. Februar fällt der
Jahrestag in einem Nichtschaltjahr auf den 1. März (die strengere Lesart).
Ein Vertrag, der dort einen Tag früher endet, gilt als zu kurz.
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.utils.translation import gettext

#: Mindestdauer in Jahren je Modell (Art. 269b bzw. 269c lit. a OR).
MINDESTJAHRE = {'index': 5, 'staffel': 3}
#: Zwischen Mietbeginn und erster Stufe sowie zwischen zwei Stufen (Art. 269c lit. b OR).
ABSTAND_STUFEN_MONATE = 12
#: Werte, die ein Vertrag OHNE Indexklausel trägt (Modellvorgaben von `Mietvertrag`).
VORGABE_WEITERGABE = Decimal('100')
VORGABE_INTERVALL = 12

MODELLE = ('fest', 'index', 'staffel')

STUFE_SPERRE = 'sperre'
STUFE_HINWEIS = 'hinweis'

ART_INDEX = 'Art. 269b OR'
ART_INDEX_DAUER = 'Art. 269b OR, Art. 17 Abs. 4 VMWG'
ART_INDEX_WEITERGABE = 'Art. 269b OR, Art. 17 Abs. 1 VMWG'
ART_STAFFEL = 'Art. 269c OR'
ART_STAFFEL_DAUER = 'Art. 269c lit. a OR, Art. 17 Abs. 4 VMWG analog'
ART_STAFFEL_ABSTAND = 'Art. 269c lit. b OR'
ART_STAFFEL_FRANKEN = 'Art. 269c lit. c OR'
ART_KOMBINATION = 'Art. 269b und 269c OR, BGE 124 III 57 E. 3a'


@dataclass(frozen=True)
class Befund:
    """Ein Ergebnis der Prüfung.

    `regel` ist der stabile Schlüssel (Tests, Oberfläche, Bericht hängen daran),
    `stufe` 'sperre' (verhindert Speichern/Erstellen) oder 'hinweis'. `text` ist
    übersetzt und enthält den Artikel nicht; der steht in `artikel`. `feld` nennt
    das Formularfeld, `fix` einen Änderungsvorschlag
    `{'feld', 'wert', 'label'}`, `zeile` die Stufenzeile (0-basiert, in der
    Reihenfolge der Eingabe) bei Befunden, die eine einzelne Stufe betreffen.
    """
    regel: str
    stufe: str
    text: str
    artikel: str
    feld: str | None = None
    fix: dict | None = None
    zeile: int | None = None

    @property
    def ist_sperre(self):
        return self.stufe == STUFE_SPERRE

    @property
    def volltext(self):
        """Text mit Artikel, wie ihn Meldungen und Altaufrufer zeigen."""
        return f'{self.text} ({self.artikel})' if self.artikel else self.text

    def als_dict(self):
        return {'regel': self.regel, 'stufe': self.stufe, 'text': self.text,
                'artikel': self.artikel, 'feld': self.feld, 'fix': self.fix,
                'zeile': self.zeile}


@dataclass(frozen=True)
class Stufe:
    """Eine Staffelstufe, wie `pruefe` sie liest. `prozent` gibt es nur, damit eine
    Prozent-Eingabe als Verstoss erkannt wird (Art. 269c lit. c OR)."""
    ab: date | None
    erhoehung_chf: Decimal | None
    prozent: Decimal | None = None


# ── Hilfen ────────────────────────────────────────────────────────────────────
def _dec(wert):
    """Decimal oder None. Leere Eingabe, Unlesbares und float werden nicht erraten."""
    if wert is None or wert == '':
        return None
    if isinstance(wert, Decimal):
        return wert
    try:
        return Decimal(str(wert).strip())
    except (InvalidOperation, ValueError):
        return None


def _zahl(wert):
    """Decimal ohne Exponent und ohne überflüssige Nullen: 80.0 → '80'."""
    text = f'{wert:f}'
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _de(d):
    return d.strftime('%d.%m.%Y')


def _plus_jahre(d, jahre):
    """Gleicher Tag `jahre` später; der 29. Februar wird zum 1. März (siehe Kopf)."""
    ziel = d.year + jahre
    if d.month == 2 and d.day == 29 and not calendar.isleap(ziel):
        return date(ziel, 3, 1)
    return date(ziel, d.month, d.day)


def mindest_ende(beginn, jahre):
    """Frühestes Ende (inklusive) einer festen Dauer von `jahre` Jahren: Beginn + N Jahre - 1 Tag."""
    return _plus_jahre(beginn, jahre) - timedelta(days=1)


def fest_bis(beginn, ende, ist_befristet, verzicht_bis):
    """Bis wann der Vermieter den Vertrag NICHT beenden kann, oder None.

    Befristet: das Enddatum. Unbefristet: das Datum des Kündigungsverzichts. Ein
    `ende` bei einem unbefristeten Vertrag stammt aus einer Kündigung und macht
    ihn nicht fest. Ein Verzicht über das Ende eines befristeten Vertrags hinaus
    verlängert nichts.
    """
    if ist_befristet and ende:
        return ende
    return verzicht_bis


def dauer_erfuellt(beginn, ende, ist_befristet, verzicht_bis, jahre):
    """Ist der Vertrag für mindestens `jahre` Jahre ab `beginn` fest? Das Ende zählt mit."""
    bis = fest_bis(beginn, ende, ist_befristet, verzicht_bis)
    if beginn is None or bis is None:
        return False
    return bis >= mindest_ende(beginn, jahre)


def stufen_normieren(stufen):
    """Liest Stufen aus Objekten (`ab_datum`, `erhoehung_chf`), Dicts (`ab`,
    `erhoehung`/`erhoehung_chf`, `prozent`) oder `Stufe`. Gibt `[(zeile, Stufe)]`
    in der Reihenfolge der Eingabe zurück; vollständig leere Zeilen entfallen,
    behalten aber ihre Zeilennummer."""
    ergebnis = []
    for i, s in enumerate(stufen or []):
        if isinstance(s, Stufe):
            st = s
        else:
            def holen(*namen):
                for n in namen:
                    wert = s.get(n) if isinstance(s, dict) else getattr(s, n, None)
                    if wert not in (None, ''):
                        return wert
                return None
            ab = holen('ab', 'ab_datum')
            if isinstance(ab, str):
                try:
                    ab = date.fromisoformat(ab)
                except ValueError:
                    ab = None
            prozent = _dec(holen('prozent'))
            st = Stufe(ab=ab, erhoehung_chf=_dec(holen('erhoehung_chf', 'erhoehung')),
                       prozent=prozent if prozent else None)
        if st.ab is None and st.erhoehung_chf is None and not st.prozent:
            continue
        ergebnis.append((i, st))
    return ergebnis


def stufen_berechnen(start_netto, stufen):
    """`[(ab, erhoehung_chf, neu_netto)]`, nach Datum sortiert, jede Stufe auf der vorigen.

    Beträge exakt (Decimal), nie gerundet. Zeilen ohne Datum oder ohne Erhöhung
    entfallen. Ist `start_netto` unbekannt, ist `neu_netto` None.
    """
    laufend = _dec(start_netto)
    zeilen = sorted(((st.ab, st.erhoehung_chf) for _i, st in stufen_normieren(stufen)
                     if st.ab is not None and st.erhoehung_chf is not None),
                    key=lambda z: z[0])
    ergebnis = []
    for ab, erh in zeilen:
        if laufend is not None:
            laufend = laufend + erh
        ergebnis.append((ab, erh, laufend))
    return ergebnis


def basis_lik_vorschlag(beginn):
    """`(stand, punkte)`: der neueste veröffentlichte LIK-Stand bis zum Monat VOR dem Mietbeginn.

    Nicht der aktuelle: Die Basis darf nicht nach dem Mietbeginn-Monat liegen.
    Quelle ist ausschliesslich die Tabelle in `core/services/lik.py`; ist für den
    Zeitraum kein Wert veröffentlicht, `(None, None)`.
    """
    from core.services.lik import LIK_DEZ2020, lik_punkte_fuer
    if beginn is None:
        return None, None
    jahr, monat = (beginn.year, beginn.month - 1) if beginn.month > 1 else (beginn.year - 1, 12)
    erstes = min(LIK_DEZ2020)
    while jahr >= erstes:
        punkte = lik_punkte_fuer(jahr, monat)
        if punkte is not None:
            return date(jahr, monat, 1), punkte
        jahr, monat = (jahr, monat - 1) if monat > 1 else (jahr - 1, 12)
    return None, None


def _b(regel, text, artikel, *, stufe=STUFE_SPERRE, feld=None, fix=None, zeile=None):
    return Befund(regel=regel, stufe=stufe, text=text, artikel=artikel, feld=feld, fix=fix, zeile=zeile)


def _fix(feld, wert, label):
    return {'feld': feld, 'wert': wert, 'label': label}


# ── Die Regeln ────────────────────────────────────────────────────────────────
def _dauer_befund(regel, artikel, beginn, ende, ist_befristet, verzicht_bis, jahre):
    if dauer_erfuellt(beginn, ende, ist_befristet, verzicht_bis, jahre):
        return None
    soll = mindest_ende(beginn, jahre)
    bis = fest_bis(beginn, ende, ist_befristet, verzicht_bis)
    if bis is None:
        text = gettext(
            'Die Dauer ist nicht fest: Der Vertrag ist weder befristet, noch verzichtet der Vermieter auf die '
            'Kündigung. Verlangt sind mindestens %(jahre)s Jahre ab Mietbeginn, also bis %(soll)s.'
        ) % {'jahre': jahre, 'soll': _de(soll)}
    else:
        text = gettext(
            'Die feste Dauer endet am %(bis)s. Verlangt sind mindestens %(jahre)s Jahre ab Mietbeginn, '
            'also bis mindestens %(soll)s.'
        ) % {'bis': _de(bis), 'jahre': jahre, 'soll': _de(soll)}
    if regel == 'staffel_dauer':
        text += ' ' + gettext('Für die Staffelmiete gilt die Dauer sinngemäss wie bei der Indexmiete.')
    if ist_befristet:
        feld = 'ende'
        fix = _fix('ende', soll.isoformat(), gettext('Laufzeit auf %(jahre)s Jahre setzen') % {'jahre': jahre})
    else:
        feld = 'vermieter_kuendigungsverzicht_bis'
        fix = _fix('vermieter_kuendigungsverzicht_bis', soll.isoformat(),
                   gettext('Kündigungsverzicht des Vermieters bis %(datum)s eintragen') % {'datum': _de(soll)})
    return _b(regel, text, artikel, feld=feld, fix=fix)


def dauer_befund(modell, beginn, ende=None, ist_befristet=None, verzicht_bis=None):
    """Nur die Dauerregel (`index_dauer` bzw. `staffel_dauer`) oder None. Für Altaufrufer, die nur
    Beginn und Ende kennen; sonst `pruefe`."""
    if modell not in MINDESTJAHRE or beginn is None:
        return None
    if ist_befristet is None:
        ist_befristet = bool(ende)
    regel, artikel = (('index_dauer', ART_INDEX_DAUER) if modell == 'index'
                      else ('staffel_dauer', ART_STAFFEL_DAUER))
    return _dauer_befund(regel, artikel, beginn, ende, ist_befristet, verzicht_bis, MINDESTJAHRE[modell])


def _index_befunde(beginn, ende, ist_befristet, verzicht_bis, stufen, basis_lik_punkte, basis_lik_stand,
                   weitergabe_prozent, intervall_monate, index_art):
    befunde = []
    jahre = MINDESTJAHRE['index']
    if beginn is not None:
        b = _dauer_befund('index_dauer', ART_INDEX_DAUER, beginn, ende, ist_befristet, verzicht_bis, jahre)
        if b:
            befunde.append(b)

    vorschlag_stand, vorschlag_punkte = basis_lik_vorschlag(beginn)
    punkte = _dec(basis_lik_punkte)
    if punkte is None or punkte <= 0:
        from core.services.lik import lik_punkte_fuer
        if basis_lik_stand is not None:
            fix_stand, fix_punkte = basis_lik_stand, lik_punkte_fuer(basis_lik_stand.year, basis_lik_stand.month)
        else:
            fix_stand, fix_punkte = vorschlag_stand, vorschlag_punkte
        fix = (_fix('basis_lik_punkte', str(fix_punkte),
                    gettext('LIK-Stand %(stand)s übernehmen (%(punkte)s Punkte)')
                    % {'stand': fix_stand.strftime('%m.%Y'), 'punkte': fix_punkte})
               if fix_punkte is not None else None)
        befunde.append(_b('index_basis_punkte', gettext('Die Basis des Landesindexes (Punkte) fehlt.'),
                          ART_INDEX, feld='basis_lik_punkte', fix=fix))
    if basis_lik_stand is None:
        fix = (_fix('basis_lik_stand', vorschlag_stand.strftime('%Y-%m'),
                    gettext('Stand %(stand)s eintragen') % {'stand': vorschlag_stand.strftime('%m.%Y')})
               if vorschlag_stand is not None else None)
        befunde.append(_b('index_basis_stand', gettext('Der Stand-Monat der Index-Basis fehlt.'),
                          ART_INDEX, feld='basis_lik_stand', fix=fix))
    elif beginn is not None and (basis_lik_stand.year, basis_lik_stand.month) > (beginn.year, beginn.month):
        fix = (_fix('basis_lik_stand', vorschlag_stand.strftime('%Y-%m'),
                    gettext('Stand %(stand)s eintragen') % {'stand': vorschlag_stand.strftime('%m.%Y')})
               if vorschlag_stand is not None else None)
        befunde.append(_b(
            'index_basis_nach_beginn',
            gettext('Der Stand der Index-Basis (%(stand)s) liegt nach dem Mietbeginn (%(beginn)s).')
            % {'stand': basis_lik_stand.strftime('%m.%Y'), 'beginn': _de(beginn)},
            ART_INDEX, feld='basis_lik_stand', fix=fix))
    if basis_lik_stand is not None and punkte is not None and punkte > 0:
        from core.services.lik import lik_punkte_fuer
        tabelle = lik_punkte_fuer(basis_lik_stand.year, basis_lik_stand.month)
        if tabelle is not None and tabelle != punkte:
            befunde.append(_b(
                'index_basis_abweichung',
                gettext('Für %(stand)s weist die LIK-Tabelle %(tabelle)s Punkte aus, erfasst sind %(punkte)s.')
                % {'stand': basis_lik_stand.strftime('%m.%Y'), 'tabelle': tabelle, 'punkte': punkte},
                ART_INDEX, stufe=STUFE_HINWEIS, feld='basis_lik_punkte',
                fix=_fix('basis_lik_punkte', str(tabelle), gettext('Punkte der Tabelle übernehmen'))))

    w = _dec(weitergabe_prozent)
    if w is None:
        befunde.append(_b('index_weitergabe', gettext('Die Weitergabe der Teuerung in Prozent fehlt.'),
                          ART_INDEX_WEITERGABE, feld='index_weitergabe_prozent',
                          fix=_fix('index_weitergabe_prozent', '100', gettext('Weitergabe eintragen: 100 %'))))
    elif w <= 0:
        befunde.append(_b('index_weitergabe', gettext('Die Weitergabe muss über 0 % liegen.'),
                          ART_INDEX_WEITERGABE, feld='index_weitergabe_prozent'))
    elif w > 100:
        befunde.append(_b('index_weitergabe',
                          gettext('Die Weitergabe darf höchstens 100 Prozent der Teuerung betragen.'),
                          ART_INDEX_WEITERGABE, feld='index_weitergabe_prozent',
                          fix=_fix('index_weitergabe_prozent', '100', gettext('Weitergabe eintragen: 100 %'))))

    if index_art not in (None, '', 'lik'):
        befunde.append(_b('index_art', gettext('Als Index ist nur der Landesindex der Konsumentenpreise zulässig.'),
                          ART_INDEX, feld='index_art',
                          fix=_fix('index_art', 'lik', gettext('Landesindex der Konsumentenpreise wählen'))))

    intervall = _dec(intervall_monate)
    if intervall is not None and intervall < 1:
        befunde.append(_b('index_intervall', gettext('Das Mindestintervall muss mindestens 1 Monat betragen.'),
                          '', feld='index_intervall_monate',
                          fix=_fix('index_intervall_monate', str(VORGABE_INTERVALL),
                                   gettext('Intervall setzen auf 12 Monate'))))

    if stufen:
        befunde.append(_b(
            'index_staffel_kombination',
            gettext('Eine Indexklausel darf nicht mit Staffelstufen kombiniert werden.'),
            ART_KOMBINATION, feld='staffelstufen',
            fix=_fix('staffelstufen', [], gettext('Staffelstufen entfernen'))))

    befunde.append(_b(
        'index_anpassung',
        gettext('Jede Anpassung wird mit dem amtlichen Formular angekündigt, mindestens 30 Tage vor einem '
                'Monatsende und erst nach Veröffentlichung des neuen Indexstandes. Sinkt der Index, '
                'sinkt der Mietzins entsprechend.'),
        'Art. 17 Abs. 2 und 3, Art. 19 Abs. 2 VMWG', stufe=STUFE_HINWEIS))
    return befunde


def abstand_befunde(beginn, stufen):
    """Art. 269c lit. b OR: zwischen Mietbeginn und erster Stufe sowie zwischen zwei Stufen
    mindestens 12 Monate. `beginn` darf fehlen (dann entfällt die erste Strecke); `stufen`
    sind normiert (`stufen_normieren`)."""
    befunde = []
    vorher = beginn
    erste = True
    for zeile, st in sorted(((z, s) for z, s in stufen or [] if s.ab is not None), key=lambda p: (p[1].ab, p[0])):
        fruehestens = _plus_jahre(vorher, ABSTAND_STUFEN_MONATE // 12) if vorher is not None else None
        if fruehestens is not None and st.ab < fruehestens:
            if erste:
                text = gettext('Stufe %(nr)s: Zwischen Mietbeginn und der ersten Erhöhung müssen mindestens '
                               '12 Monate liegen, frühestens am %(datum)s.')
            else:
                text = gettext('Stufe %(nr)s: Zwischen zwei Erhöhungen müssen mindestens 12 Monate liegen, '
                               'frühestens am %(datum)s.')
            befunde.append(_b(
                'staffel_jahresabstand', text % {'nr': zeile + 1, 'datum': _de(fruehestens)},
                ART_STAFFEL_ABSTAND, feld='staffel_ab', zeile=zeile,
                fix={**_fix('staffel_ab', fruehestens.isoformat(),
                            gettext('Stufe auf den %(datum)s legen') % {'datum': _de(fruehestens)}),
                     'zeile': zeile}))
        vorher = st.ab
        erste = False
    return befunde


def _staffel_befunde(beginn, ende, ist_befristet, verzicht_bis, stufen, weitergabe_prozent, intervall_monate,
                     hat_zeitplan):
    befunde = []
    jahre = MINDESTJAHRE['staffel']
    if beginn is not None:
        b = _dauer_befund('staffel_dauer', ART_STAFFEL_DAUER, beginn, ende, ist_befristet, verzicht_bis, jahre)
        if b:
            befunde.append(b)
    bis = fest_bis(beginn, ende, ist_befristet, verzicht_bis)

    if stufen is not None and not stufen:
        befunde.append(_b('staffel_stufen_fehlen', gettext('Eine Staffelmiete braucht mindestens eine Stufe.'),
                          ART_STAFFEL, feld='staffelstufen'))

    for zeile, st in stufen or []:
        nr = zeile + 1
        if st.ab is None:
            befunde.append(_b('staffel_datum', gettext('Stufe %(nr)s: Das Datum fehlt.') % {'nr': nr},
                              ART_STAFFEL, feld='staffel_ab', zeile=zeile))
        if st.prozent:
            befunde.append(_b(
                'staffel_prozent',
                gettext('Stufe %(nr)s: Die Erhöhung muss als Frankenbetrag vereinbart werden, nicht in Prozent.')
                % {'nr': nr},
                ART_STAFFEL_FRANKEN, feld='staffel_prozent', zeile=zeile))
        elif st.erhoehung_chf is None:
            befunde.append(_b('staffel_erhoehung', gettext('Stufe %(nr)s: Die Erhöhung in CHF fehlt.') % {'nr': nr},
                              ART_STAFFEL_FRANKEN, feld='staffel_erhoehung', zeile=zeile))
        elif st.erhoehung_chf <= 0:
            befunde.append(_b(
                'staffel_erhoehung',
                gettext('Stufe %(nr)s: Die Erhöhung muss ein Frankenbetrag über 0 sein.') % {'nr': nr},
                ART_STAFFEL_FRANKEN, feld='staffel_erhoehung', zeile=zeile))

    befunde += abstand_befunde(beginn, stufen)

    if bis is not None:
        for zeile, st in stufen or []:
            if st.ab is not None and st.ab > bis:
                befunde.append(_b(
                    'staffel_nach_ende',
                    gettext('Stufe %(nr)s (%(datum)s) liegt nach dem Ende der festen Dauer (%(bis)s).')
                    % {'nr': zeile + 1, 'datum': _de(st.ab), 'bis': _de(bis)},
                    ART_STAFFEL, feld='staffel_ab', zeile=zeile))

    w = _dec(weitergabe_prozent)
    intervall = _dec(intervall_monate)
    if w is not None and w != VORGABE_WEITERGABE:
        befunde.append(_b(
            'staffel_index_felder',
            gettext('Bei einer Staffelmiete darf keine Indexklausel stehen bleiben (Weitergabe %(w)s %%).')
            % {'w': _zahl(w)},
            ART_KOMBINATION, feld='index_weitergabe_prozent',
            fix=_fix('index_weitergabe_prozent', '100', gettext('Weitergabe zurücksetzen auf 100 %'))))
    elif intervall is not None and intervall != VORGABE_INTERVALL:
        befunde.append(_b(
            'staffel_index_felder',
            gettext('Bei einer Staffelmiete darf keine Indexklausel stehen bleiben (Intervall %(m)s Monate).')
            % {'m': _zahl(intervall)},
            ART_KOMBINATION, feld='index_intervall_monate',
            fix=_fix('index_intervall_monate', str(VORGABE_INTERVALL),
                     gettext('Intervall zurücksetzen auf 12 Monate'))))

    if stufen:
        befunde.append(_b(
            'staffel_mitteilung',
            gettext('Jede Erhöhung wird dem Mieter schriftlich mitgeteilt, frühestens vier Monate vor ihrem '
                    'Eintritt. Das amtliche Formular braucht es dafür nicht.'),
            'Art. 269d Abs. 5 OR, Art. 19a VMWG', stufe=STUFE_HINWEIS))
    if hat_zeitplan:
        befunde.append(_b(
            'staffel_zeitplan',
            gettext('Zu diesem Vertrag bestehen zusätzlich datierte Mietzinskomponenten oder ein Zeitplan '
                    '(etwa Gratismonate). Sie gehen den Staffelstufen vor.'),
            '', stufe=STUFE_HINWEIS))
    return befunde


def pruefe(*, modell, beginn, ende=None, ist_befristet=None, verzicht_bis=None, netto=None, stufen=None,
           basis_lik_punkte=None, basis_lik_stand=None, weitergabe_prozent=None, intervall_monate=None,
           index_art=None, hat_zeitplan=False):
    """Alle Befunde zu einem Mietzinsmodell, Sperren zuerst.

    `stufen`: None = unbekannt (Regeln über Stufen entfallen, etwa bei einem Vertrag, der noch
    keine Primärschlüssel-Beziehung hat), `[]` = bekannt und leer. Elemente siehe `stufen_normieren`.
    `ist_befristet`: None = aus `ende` ableiten (Altaufrufer, die nur das Enddatum kennen).
    `netto` wird für die Regeln nicht gebraucht, gehört aber zur Schnittstelle (`stufen_berechnen`).
    Ohne `beginn` lässt sich nichts beurteilen: leere Liste.
    """
    if modell not in MODELLE or beginn is None:
        return []
    if ist_befristet is None:
        ist_befristet = bool(ende)
    norm = None if stufen is None else stufen_normieren(stufen)
    if modell == 'index':
        befunde = _index_befunde(beginn, ende, ist_befristet, verzicht_bis, norm, basis_lik_punkte,
                                 basis_lik_stand, weitergabe_prozent, intervall_monate, index_art)
    elif modell == 'staffel':
        befunde = _staffel_befunde(beginn, ende, ist_befristet, verzicht_bis, norm, weitergabe_prozent,
                                   intervall_monate, hat_zeitplan)
    else:
        befunde = []
        if norm:
            befunde.append(_b(
                'fest_staffelstufen',
                gettext('Bei festem Mietzins dürfen keine Staffelstufen stehen.'), ART_STAFFEL,
                feld='staffelstufen', fix=_fix('staffelstufen', [], gettext('Staffelstufen entfernen'))))
    return sorted(befunde, key=lambda b: b.stufe != STUFE_SPERRE)


def sperren(befunde):
    """Die Befunde, die das Speichern verhindern."""
    return [b for b in befunde if b.stufe == STUFE_SPERRE]


def abgeleitet(*, modell, beginn, ende=None, ist_befristet=None, verzicht_bis=None, netto=None, stufen=None):
    """Berechnete Werte zur Anzeige: feste Dauer, frühestes Ende, Stufen mit neuem Netto."""
    if ist_befristet is None:
        ist_befristet = bool(ende)
    jahre = MINDESTJAHRE.get(modell)
    return {
        'fest_bis': fest_bis(beginn, ende, ist_befristet, verzicht_bis) if beginn else None,
        'mindest_ende': mindest_ende(beginn, jahre) if (beginn and jahre) else None,
        'stufen': stufen_berechnen(netto, stufen) if modell == 'staffel' else [],
    }


# ── Anbindung an Verträge ─────────────────────────────────────────────────────
def pruefe_vertrag(vertrag, stufen='db', hat_zeitplan=False):
    """`pruefe` für ein `Mietvertrag`-Objekt.

    `stufen='db'`: gespeicherte Stufen lesen; ein Vertrag ohne Primärschlüssel hat keine
    (None = unbekannt). Wer neue Stufen mitprüfen will, übergibt sie ausdrücklich.
    """
    if stufen == 'db':
        stufen = list(vertrag.staffelstufen.all()) if vertrag.pk else None
    return pruefe(
        modell=vertrag.mietzins_modell, beginn=vertrag.beginn, ende=vertrag.ende,
        ist_befristet=vertrag.ist_befristet, verzicht_bis=vertrag.vermieter_kuendigungsverzicht_bis,
        netto=vertrag.netto_mietzins, stufen=stufen, basis_lik_punkte=vertrag.basis_lik_punkte,
        basis_lik_stand=vertrag.basis_lik_stand, weitergabe_prozent=vertrag.index_weitergabe_prozent,
        intervall_monate=vertrag.index_intervall_monate, hat_zeitplan=hat_zeitplan)


# ── Vertragstext ──────────────────────────────────────────────────────────────
def klausel_kontext(vertrag):
    """Die Angaben für die Index- bzw. Staffelklausel im Mietvertrag (Abschnitt 4.4).

    Alles, was die Klausel nennt, kommt aus dem Vertrag selbst; der Kontext der aufrufenden
    Stelle (PDF, DocuSeal, Vorschau) wird nicht gebraucht. Eine Vorschau mit noch nicht
    gespeicherten Stufen setzt `vertrag.vorschau_stufen` (Liste für `stufen_normieren`).
    """
    from core.services.lik import LIK_BASIS, stand_label
    modell = getattr(vertrag, 'mietzins_modell', 'fest')
    if modell not in MINDESTJAHRE:
        return {'modell': modell}
    verzicht = vertrag.vermieter_kuendigungsverzicht_bis
    bis = fest_bis(vertrag.beginn, vertrag.ende, vertrag.ist_befristet, verzicht)
    kontext = {
        'modell': modell, 'jahre': MINDESTJAHRE[modell], 'jahre_wort': {5: 'fünf', 3: 'drei'}[MINDESTJAHRE[modell]],
        'fest_bis': bis,
        'dauer_art': None if bis is None else ('befristet' if (vertrag.ist_befristet and vertrag.ende) else 'verzicht'),
    }
    if modell == 'index':
        verwaltung = getattr(getattr(getattr(vertrag, 'einheit', None), 'liegenschaft', None), 'organisation', None)
        punkte = _dec(vertrag.basis_lik_punkte)
        kontext.update(
            lik_basis=getattr(verwaltung, 'lik_basis', None) or LIK_BASIS,
            lik_stand=stand_label(vertrag.basis_lik_stand),
            lik_punkte=f'{punkte:.1f}'.replace('.', ',') if punkte is not None else '',
            weitergabe=_zahl(_dec(vertrag.index_weitergabe_prozent) or VORGABE_WEITERGABE),
            intervall=vertrag.index_intervall_monate)
    else:
        if getattr(vertrag, 'vorschau_stufen', None) is not None:
            gespeichert = stufen_normieren(vertrag.vorschau_stufen)
            stufen = [st for _z, st in gespeichert]
        else:
            stufen = []
            laufend = _dec(vertrag.netto_mietzins) or Decimal('0')
            vorhanden = list(vertrag.staffelstufen.all()) if vertrag.pk else []
            for s in sorted(vorhanden, key=lambda s: (s.ab_datum, s.id or 0)):
                # Altstufen ohne Erhöhung: die Erhöhung ergibt sich aus dem Betrag der Stufe.
                erh = s.erhoehung_chf if s.erhoehung_chf is not None else s.netto_mietzins - laufend
                stufen.append(Stufe(ab=s.ab_datum, erhoehung_chf=erh))
                laufend += erh
        kontext.update(
            beginn=vertrag.beginn, netto=vertrag.netto_mietzins,
            stufen=[{'ab': ab, 'erhoehung': erh, 'neu': neu}
                    for ab, erh, neu in stufen_berechnen(vertrag.netto_mietzins, stufen)])
    return kontext
