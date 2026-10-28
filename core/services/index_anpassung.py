"""Indexanpassung (Art. 269b OR, Art. 17 und 19 Abs. 2 VMWG): Rechenkern und Prüfungen.

Eine Stelle für alles, was bei einer Indexmiete gesetzlich begrenzt ist. Der
Assistent (`core/views/fw/mietzins.py`), der Vorschlag
(`mietrecht.index_anpassung_vorschlag`) und die Fristprüfung beim Versand
(`mietzinsanpassung.fristfehler`) rufen diese Funktionen; eine zweite Fassung
der Regeln im Browser gibt es nicht.

WAS HIER GILT

* **Nur der LIK-Stand, der in `core/services/lik.py` steht** (`None` oder
  ausserhalb der Tabelle = nicht veröffentlicht). Keine Anpassung auf einen
  Monat, den es nicht gibt (a).
* **Höchstens Zunahme mal Weitergabe** (Art. 17 Abs. 1 VMWG). Das Mass ist der
  EXAKTE Wert; gerundet wird nur der Vorschlag, und zwar nach unten auf 5
  Rappen, damit er die Grenze nie überschreitet. Gerechnet wird mit `Fraction`,
  nicht mit `Decimal`: 1650 × 106.4 / 105 ist exakt 1672, in `Decimal` aber
  1671.999…, und das Abrunden auf 5 Rappen ergäbe 1671.95 (b).
* **Sinkt der LIK, ist die Anpassung nach unten zwingend** (Art. 17 Abs. 2):
  derselbe Höchstbetrag gilt dann als Obergrenze des neuen Mietzinses — ein
  höherer Betrag wird abgelehnt (b).
* **Frist** (Art. 17 Abs. 3): mindestens 30 Tage, auf ein Monatsende (c).
* **Bekanntgabe** (Art. 19 Abs. 2 VMWG): die Mitteilung darf erst nach der
  öffentlichen Bekanntgabe des neuen Indexstandes erfolgen (d).

ANNAHMEN (nicht aus dem Gesetz, im Schlussbericht gemeldet)

1. **Bekanntgabe = Eintrag in der Tabelle.** Im Bestand gibt es kein
   Veröffentlichungsdatum des BFS; die Monatstabelle ist die einzige Quelle.
   Ein Monat gilt als bekannt gegeben, sobald er dort steht — frühere
   Veröffentlichungstermine werden NICHT erfunden. Zusätzlich gilt: ein Monat,
   der noch nicht begonnen hat, kann nicht bekannt sein.
2. **Die 30 Tage laufen ab Zugang** (Empfangstheorie wie bei Art. 269d OR im
   Bestand): bestätigter Zugang, sonst Versand plus Zustellpuffer
   (`rentals.services.ZUSTELL_PUFFER_TAGE`). Wer den Puffer nicht will, ruft
   mit `puffer_tage=0` auf.
3. **Ein Monatsende als Termin heisst wirksam am Ersten des Folgemonats** —
   wie im übrigen Bestand (`naechster_anpassungstermin`).
4. **Die Weitergabe gilt in beide Richtungen**, wie bisher im Vorschlag. Ob
   eine Teil-Weitergabe auch die Senkung begrenzen darf (Art. 17 Abs. 2:
   «entsprechend anzupassen»), ist eine Fachfrage und offen.

Mindestintervall und letzte Anpassung sind VERTRAGLICHE Grenzen, kein
gesetzlicher Wert; sie werden als solche angezeigt, nicht als Gesetz erzwungen.
"""
import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from math import floor

from django.utils.formats import date_format
from django.utils.translation import gettext

#: Art. 17 Abs. 3 VMWG: Ankündigung mit mindestens dreissig Tagen auf ein Monatsende.
FRIST_TAGE = 30

#: Art. 17 Abs. 1 VMWG: Weitergabe höchstens 100 % der Indexzunahme.
WEITERGABE_MAX = Decimal('100')

_FUENF_RAPPEN = Fraction(5, 100)


# ── Monate und LIK-Tabelle ───────────────────────────────────────────────────
def monatserster(d):
    return date(d.year, d.month, 1)


def monatsende(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def plus_monate(d, monate):
    """`d` plus Monate, der Tag auf die Monatslänge geklemmt."""
    m0 = d.month - 1 + int(monate)
    jahr, monat = d.year + m0 // 12, m0 % 12 + 1
    return date(jahr, monat, min(d.day, calendar.monthrange(jahr, monat)[1]))


def monat_text(d):
    """«Mai 2026» in der aktiven Sprache."""
    return date_format(d, 'F Y') if d else ''


def lik_punkte(stand):
    """LIK-Punkte des Monats `stand` aus `core/services/lik.py`, oder None."""
    from core.services.lik import lik_punkte_fuer
    if not stand:
        return None
    return lik_punkte_fuer(stand.year, stand.month)


def letzter_stand(bis=None):
    """Der jüngste Monat der Tabelle mit Wert (höchstens `bis`), oder None."""
    from core.services.lik import LIK_DEZ2020
    grenze = monatserster(bis) if bis else None
    beste = None
    for jahr in sorted(LIK_DEZ2020):
        for i, wert in enumerate(LIK_DEZ2020[jahr]):
            if wert is None:
                continue
            monat = date(jahr, i + 1, 1)
            if grenze is None or monat <= grenze:
                beste = monat
    return beste


def verfuegbare_staende(anzahl=12, bis=None):
    """Die jüngsten `anzahl` veröffentlichten Monate, der neueste zuerst."""
    from core.services.lik import LIK_DEZ2020
    grenze = monatserster(bis) if bis else None
    monate = [date(j, i + 1, 1)
              for j in sorted(LIK_DEZ2020) for i, w in enumerate(LIK_DEZ2020[j])
              if w is not None and (grenze is None or date(j, i + 1, 1) <= grenze)]
    return list(reversed(monate))[:anzahl]


def stand_aus_text(text):
    """«2026-05» -> date(2026, 5, 1); alles andere -> None."""
    try:
        jahr, monat = str(text or '').strip().split('-')[:2]
        return date(int(jahr), int(monat), 1)
    except (ValueError, TypeError):
        return None


def stand_fehler(stand, heute, alt_stand=None):
    """Meldung, wenn dieser LIK-Stand nicht Grundlage einer Anpassung sein kann."""
    letzter = letzter_stand(bis=heute)
    if stand is None:
        return gettext('Bitte den Monat des neuen LIK-Standes wählen.')
    if stand > monatserster(heute) or lik_punkte(stand) is None:
        # Ein Monat, der noch nicht begonnen hat, kann nicht bekannt gegeben sein.
        return gettext(
            'Der LIK-Stand %(monat)s ist nicht veröffentlicht. Eine Indexanpassung ist erst nach der '
            'Bekanntgabe des neuen Indexstandes möglich (Art. 19 Abs. 2 VMWG). Letzter verfügbarer '
            'Monat: %(letzter)s.') % {'monat': monat_text(stand),
                                      'letzter': monat_text(letzter) if letzter else '—'}
    if alt_stand and stand < monatserster(alt_stand):
        return gettext('Der neue LIK-Stand (%(neu)s) liegt vor dem bisherigen (%(alt)s).') % {
            'neu': monat_text(stand), 'alt': monat_text(alt_stand)}
    return ''


# ── Rundung ──────────────────────────────────────────────────────────────────
def _fraction(x):
    return Fraction(Decimal(str(x)))


def _decimal(bruch, schritt):
    """`bruch` (ein Vielfaches von `schritt` oder darüber) als Decimal mit 2 Stellen, nach unten."""
    einheiten = floor(bruch / schritt)
    return (Decimal(einheiten) * Decimal(schritt.numerator) / Decimal(schritt.denominator)).quantize(
        Decimal('0.01'))


# ── Rechenkern (Art. 17 VMWG) ────────────────────────────────────────────────
@dataclass(frozen=True)
class IndexRechnung:
    """Das Ergebnis der Indexrechnung für einen bestimmten neuen LIK-Stand.

    `hoechst_netto` ist die Grenze: Der neue Nettomietzins darf sie nicht
    überschreiten — bei steigendem Index (Art. 17 Abs. 1) ebenso wie bei
    sinkendem (Abs. 2, dort ist die Anpassung nach unten zwingend)."""
    alt_netto: Decimal
    basis_lik: Decimal
    neu_lik: Decimal
    weitergabe_prozent: Decimal
    richtung: str                 # 'erhoehung' | 'senkung' | 'unveraendert'
    zunahme_prozent: Decimal      # LIK-Veränderung in %, auf 0.01 (nur Anzeige)
    wirkung_prozent: Decimal      # Zunahme mal Weitergabe, auf 0.01 (nur Anzeige)
    hoechst_netto: Decimal        # nach unten auf den Rappen
    vorschlag_netto: Decimal      # nach unten auf 5 Rappen
    _exakt: Fraction = field(repr=False, compare=False)

    @property
    def hoechst_erhoehung_chf(self):
        """Die höchste zulässige Erhöhung in CHF (0, wenn der Index nicht gestiegen ist)."""
        return max(Decimal('0.00'), self.hoechst_netto - self.alt_netto)

    def ueberschreitet(self, neu_netto):
        """Liegt `neu_netto` über der Grenze? Exakter Vergleich, ohne Rundung."""
        return _fraction(neu_netto) > self._exakt


def rechne(alt_netto, basis_lik, neu_lik, weitergabe_prozent=None):
    """Die Indexrechnung. `ValueError`, wenn die Basis fehlt.

    `weitergabe_prozent` leer = 100; über 100 wird auf 100 begrenzt (Art. 17
    Abs. 1: die Erhöhung darf die Zunahme nicht übersteigen). 0 bleibt 0."""
    basis, neu = _fraction(basis_lik or 0), _fraction(neu_lik or 0)
    if basis <= 0:
        raise ValueError('Basis-LIK fehlt')
    w = Decimal(str(WEITERGABE_MAX if weitergabe_prozent is None else weitergabe_prozent))
    w = max(Decimal('0'), min(w, WEITERGABE_MAX))
    alt = _fraction(alt_netto or 0)
    zunahme = (neu - basis) / basis
    exakt = alt * (1 + zunahme * _fraction(w) / 100)
    if exakt > alt:
        richtung = 'erhoehung'
    elif exakt < alt:
        richtung = 'senkung'
    else:
        richtung = 'unveraendert'
    cent = Fraction(1, 100)
    return IndexRechnung(
        alt_netto=Decimal(str(alt_netto or 0)).quantize(Decimal('0.01')),
        basis_lik=Decimal(str(basis_lik)), neu_lik=Decimal(str(neu_lik)),
        weitergabe_prozent=w, richtung=richtung,
        zunahme_prozent=_prozent(zunahme * 100), wirkung_prozent=_prozent(zunahme * _fraction(w)),
        hoechst_netto=_decimal(exakt, cent), vorschlag_netto=_decimal(exakt, _FUENF_RAPPEN),
        _exakt=exakt)


def _prozent(bruch):
    """Ein Bruch in Prozent, kaufmännisch auf 0.01 (nur für die Anzeige)."""
    from decimal import ROUND_HALF_UP
    wert = Decimal(bruch.numerator) / Decimal(bruch.denominator)
    return wert.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def eingabe_fehler(rechnung, neu_netto):
    """Meldung, wenn `neu_netto` mehr ist, als Art. 17 VMWG zulässt — sonst ''."""
    if neu_netto is None or not rechnung.ueberschreitet(neu_netto):
        return ''
    grenze = f'{rechnung.hoechst_netto:.2f}'
    if rechnung.richtung == 'senkung':
        return gettext(
            'Der LIK ist gesunken (%(alt)s → %(neu)s Punkte): Der Mietzins ist nach unten anzupassen '
            '(Art. 17 Abs. 2 VMWG), höchstens CHF %(grenze)s.') % {
                'alt': rechnung.basis_lik, 'neu': rechnung.neu_lik, 'grenze': grenze}
    if rechnung.richtung == 'unveraendert':
        return gettext('Der LIK ist unverändert (%(lik)s Punkte): Eine Erhöhung ist nicht zulässig '
                       '(Art. 17 Abs. 1 VMWG).') % {'lik': rechnung.neu_lik}
    return gettext(
        'Die Erhöhung übersteigt die Indexzunahme mal Weitergabe (%(zunahme)s %% × %(w)s %%): höchstens '
        'CHF %(grenze)s netto (Art. 17 Abs. 1 VMWG).') % {
            'zunahme': rechnung.zunahme_prozent, 'w': _ohne_nullen(rechnung.weitergabe_prozent),
            'grenze': grenze}


def _ohne_nullen(d):
    return format(Decimal(d).normalize(), 'f')


# ── Frist und Termin (Art. 17 Abs. 3 VMWG) ───────────────────────────────────
def zugang_fuer(versand_am, zugang_am=None, puffer_tage=None):
    """Bestätigter Zugang, sonst Versand plus Zustellpuffer (Annahme 2)."""
    if zugang_am:
        return zugang_am
    if puffer_tage is None:
        from rentals.services import ZUSTELL_PUFFER_TAGE
        puffer_tage = ZUSTELL_PUFFER_TAGE
    return versand_am + timedelta(days=puffer_tage)


def fruehestes_monatsende(zugang):
    """Das erste Monatsende, das mindestens 30 Tage nach `zugang` liegt."""
    return monatsende(zugang + timedelta(days=FRIST_TAGE))


def frueheste_wirksamkeit(versand_am, zugang_am=None, puffer_tage=None):
    """Der früheste Tag, ab dem der neue Mietzins gilt: der Erste nach dem frühesten Monatsende."""
    ende = fruehestes_monatsende(zugang_fuer(versand_am, zugang_am, puffer_tage))
    return ende + timedelta(days=1)


def termine_ab(frueh, anzahl=24):
    """Die zulässigen Wirksamkeitsdaten ab `frueh`: jeder Monatserste."""
    termine, d = [], frueh
    for _ in range(anzahl):
        termine.append(d)
        d = plus_monate(d, 1)
    return termine


def termin_fehler(wirksam_ab, versand_am, zugang_am=None, puffer_tage=None):
    """Meldung, wenn `wirksam_ab` die Frist nicht wahrt oder kein Monatswechsel ist — sonst ''."""
    if wirksam_ab is None:
        return gettext('Bitte das Wirksamkeitsdatum angeben.')
    if wirksam_ab.day != 1:
        return gettext('Die Indexanpassung kann nur auf ein Monatsende wirksam werden, also am Ersten des '
                       'Folgemonats (Art. 17 Abs. 3 VMWG).')
    frueh = frueheste_wirksamkeit(versand_am, zugang_am, puffer_tage)
    if wirksam_ab < frueh:
        return gettext(
            'Wirksamkeitsdatum zu früh: Die Ankündigung braucht mindestens 30 Tage bis zum Monatsende. '
            'Bei diesem Versand ist der früheste Termin der %(datum)s (Art. 17 Abs. 3 VMWG).') % {
                'datum': frueh.strftime('%d.%m.%Y')}
    return ''


# ── Vertragliche Grenzen (kein gesetzlicher Wert) ────────────────────────────
def vertragsgrenzen(vertrag):
    """Weitergabe, Mindestintervall und letzte Anpassung — als VERTRAGLICH ausgewiesen.

    `fruehestens` ist das Ende des Mindestintervalls nach der letzten Anpassung
    (leer, wenn eines von beiden fehlt)."""
    intervall = vertrag.index_intervall_monate or 0
    letzte = vertrag.index_letzte_anpassung
    return {
        'weitergabe': vertrag.index_weitergabe_prozent,
        'intervall_monate': intervall,
        'letzte_anpassung': letzte,
        'fruehestens': plus_monate(letzte, intervall) if (letzte and intervall) else None,
    }


def intervall_hinweis(vertrag, wirksam_ab):
    """Warnung (nicht blockierend), wenn das vertragliche Mindestintervall noch läuft."""
    grenzen = vertragsgrenzen(vertrag)
    if grenzen['fruehestens'] and wirksam_ab and wirksam_ab < grenzen['fruehestens']:
        return gettext(
            'Vertragliche Grenze (kein Gesetzeswert): Das Mindestintervall von %(monate)s Monaten seit der '
            'letzten Anpassung (%(letzte)s) läuft bis %(ende)s.') % {
                'monate': grenzen['intervall_monate'],
                'letzte': grenzen['letzte_anpassung'].strftime('%d.%m.%Y'),
                'ende': grenzen['fruehestens'].strftime('%d.%m.%Y')}
    return ''


# ── Kantonales Formular (Art. 19 Abs. 2 VMWG) ────────────────────────────────
def kantone_mit_original(typ='mietzins'):
    """Kürzel der Kantone, für die ein Originalformular hinterlegt ist (BE, SO, ZH)."""
    from core.services.formular_fill import hat_original
    from core.services.kantone import KANTON_NAMEN
    return sorted(kt for kt in KANTON_NAMEN if hat_original(kt, typ))


def formular_luecke(formular):
    """Die ausdrückliche Lücke, wenn für den Kanton kein Original vorliegt — sonst None.

    Es wird nichts überbrückt: kein generisches Formular, auch keine
    Nachbildung. Die Mitteilung geht auf dem Formular der kantonalen Behörde."""
    if formular.get('kanton_fehlt') or formular.get('original'):
        return None
    from core.services.kantone import KANTON_NAMEN
    return {
        'kanton_name': formular.get('kanton_name') or formular.get('kanton') or '',
        'vorhanden': [KANTON_NAMEN.get(kt, kt) for kt in kantone_mit_original()],
    }


# ── Begründung für das Formular ──────────────────────────────────────────────
def begruendung(rechnung, stand, neu_netto, alt_stand=None):
    """Der Begründungssatz für das amtliche Formular (Rechtstext: deutsch, wie das Formular).

    Nennt Rechtsgrundlage, beide LIK-Stände, die Zunahme, die Weitergabe und die
    Beträge — der «genaue Berechnungsgrund»."""
    from core.services.lik import LIK_BASIS, stand_label
    bisher = f" ({stand_label(alt_stand)})" if alt_stand else ''
    w = _ohne_nullen(rechnung.weitergabe_prozent)
    wort = 'Senkung' if rechnung.richtung == 'senkung' else 'Anpassung'
    return (f"Indexmiete (Art. 269b OR, Art. 17 VMWG): {wort} an den Landesindex der Konsumentenpreise. "
            f"LIK {rechnung.basis_lik} Punkte{bisher} auf {rechnung.neu_lik} Punkte ({stand_label(stand)}; "
            f"Basis {LIK_BASIS} = 100), Veränderung {rechnung.zunahme_prozent} %, Weitergabe {w} %. "
            f"Netto CHF {rechnung.alt_netto} auf CHF {Decimal(str(neu_netto)):.2f}.")


_ERZEUGT = re.compile(
    r'^Indexmiete \(Art\. 269b OR, Art\. 17 VMWG\): (?:Anpassung|Senkung) .*?Netto CHF [\d.\']+ auf CHF [\d.\']+\.\s*',
    re.S)


def zusatz_aus(gespeichert):
    """Der eigene Zusatz einer gespeicherten Begründung, ohne den erzeugten Satz davor."""
    return _ERZEUGT.sub('', gespeichert or '', count=1).strip()


# ── Die Lage eines Indexvertrags für den Assistenten ─────────────────────────
def lage(vertrag, *, heute, stand=None, wirksam_ab=None, versand_am=None, zugang_am=None,
         basis_lik=None):
    """Alles, was der Assistent und die Live-Rechnung für einen Indexvertrag brauchen.

    Eine Funktion für beide, damit Seite und Nachrechnung nicht verschieden rechnen.
    Rechnet nichts schön: Fehlt die Basis oder ist der Stand nicht veröffentlicht,
    ist `rechnung` leer und `stand_fehler` / `basis_fehlt` sagen warum.

    `basis_lik` überschreibt die Vertragsbasis nur, wenn noch keine Anpassung
    wirksam ist — sonst gilt der LIK der jüngsten Anpassung (Alt-/Importverträge
    ergänzen ihre Basis im Formular, bevor sie gespeichert ist)."""
    from rentals.services import bisheriger_stand
    versand = versand_am or heute
    frueh = frueheste_wirksamkeit(versand, zugang_am)
    termin = wirksam_ab if (wirksam_ab and wirksam_ab.day == 1 and wirksam_ab >= frueh) else frueh
    alt_netto, _zins, alt_lik = bisheriger_stand(vertrag, termin)
    vortag = termin - timedelta(days=1)
    if basis_lik and vertrag._wirksame_anpassung(vortag) is None:
        alt_lik = basis_lik
    alt_stand = vertrag.effektiver_lik_stand(vortag)
    staende = verfuegbare_staende(12, bis=heute)
    stand = stand or (staende[0] if staende else None)
    fehler = stand_fehler(stand, heute, alt_stand)
    neu_lik = None if fehler else lik_punkte(stand)
    alt_lik = Decimal(str(alt_lik or 0))
    rechnung = None
    if neu_lik and alt_lik > 0:
        rechnung = rechne(alt_netto, alt_lik, neu_lik, vertrag.index_weitergabe_prozent)
    zugang = zugang_fuer(versand, zugang_am)
    return {
        'stand': stand, 'staende': staende, 'stand_fehler': fehler,
        'frueh_text': gettext(
            'Frühestens %(datum)s: mindestens 30 Tage bis zu einem Monatsende (Art. 17 Abs. 3 VMWG), '
            'gerechnet ab Zugang (vermutet %(zugang)s).') % {
                'datum': frueh.strftime('%d.%m.%Y'), 'zugang': zugang.strftime('%d.%m.%Y')},
        'hoechst_text': (gettext('Höchstens CHF %(grenze)s (Art. 17 VMWG). Ein höherer Betrag wird abgelehnt.') % {
            'grenze': f'{rechnung.hoechst_netto:.2f}'} if rechnung else
            gettext('Erst nach einem veröffentlichten LIK-Stand möglich.')),
        'letzter_stand': letzter_stand(bis=heute), 'alt_stand': alt_stand,
        'alt_lik': alt_lik, 'neu_lik': neu_lik, 'basis_fehlt': alt_lik <= 0,
        'alt_netto': Decimal(str(alt_netto or 0)).quantize(Decimal('0.01')),
        'rechnung': rechnung, 'termin': termin, 'frueh': frueh,
        'zugang': zugang,
        'termine': termine_ab(frueh), 'grenzen': vertragsgrenzen(vertrag),
        'intervall_hinweis': intervall_hinweis(vertrag, termin),
    }


def pruefe(vertrag, *, heute, stand, wirksam_ab, neu_netto, versand_am=None, zugang_am=None,
           basis_lik=None):
    """Alle harten Prüfungen für Entwurf, PDF und Versand. Liste von Meldungen (leer = in Ordnung).

    Die Reihenfolge ist die der Gesetzeslage: erst Bekanntgabe und Basis, dann
    der Betrag (Art. 17 Abs. 1 und 2), dann der Termin (Abs. 3). Für Entwurf
    und PDF ist `versand_am` heute — beim Versand prüft `versand_erfassen` mit
    dem echten Datum nach."""
    lg = lage(vertrag, heute=heute, stand=stand, wirksam_ab=wirksam_ab, versand_am=versand_am,
              zugang_am=zugang_am, basis_lik=basis_lik)
    meldungen = []
    if stand is None:
        meldungen.append(gettext('Bitte den Monat des neuen LIK-Standes wählen.'))
    elif lg['stand_fehler']:
        meldungen.append(lg['stand_fehler'])
    if lg['basis_fehlt']:
        meldungen.append(gettext('Der LIK der Vertragsbasis fehlt — bitte die Basis-Punkte ergänzen.'))
    rechnung = lg['rechnung']
    if rechnung is not None and neu_netto is not None:
        fehler = eingabe_fehler(rechnung, neu_netto)
        if fehler:
            meldungen.append(fehler)
    termin = termin_fehler(wirksam_ab, versand_am or heute, zugang_am)
    if termin:
        meldungen.append(termin)
    return meldungen


def lage_json(lg):
    """Die Lage als JSON-fähiges Dict für die Live-Nachrechnung im Assistenten.

    Alles als Text, damit der Browser nichts rechnet — er zeigt, begrenzt die
    Eingabe auf `hoechst_netto` und baut die Terminliste."""
    r = lg['rechnung']

    def text(x):
        return None if x is None else str(x)

    def datum(d):
        return d.isoformat() if d else None
    termine = [{'wert': d.isoformat(), 'text': d.strftime('%d.%m.%Y')} for d in lg['termine']]
    return {
        'index': True, 'alt_netto': text(lg['alt_netto']), 'alt_lik': text(lg['alt_lik']),
        'stand': lg['stand'].strftime('%Y-%m') if lg['stand'] else None,
        'stand_fehler': lg['stand_fehler'], 'neu_lik': text(lg['neu_lik']),
        'basis_fehlt': lg['basis_fehlt'],
        'richtung': r.richtung if r else None,
        'zunahme_prozent': text(r.zunahme_prozent) if r else None,
        'wirkung_prozent': text(r.wirkung_prozent) if r else None,
        'weitergabe_prozent': text(_ohne_nullen(r.weitergabe_prozent)) if r else None,
        'hoechst_netto': text(r.hoechst_netto) if r else None,
        'hoechst_erhoehung': text(r.hoechst_erhoehung_chf) if r else None,
        'vorschlag_netto': text(r.vorschlag_netto) if r else None,
        'zunahme_text': (f"{r.zunahme_prozent} % {gettext('Veränderung')}" if r else ''),
        'hoechst_f_text': (f"{r.zunahme_prozent} % × {_ohne_nullen(r.weitergabe_prozent)} % {gettext('Weitergabe')}"
                           if r else ''),
        'frueh_text': lg['frueh_text'], 'hoechst_text': lg['hoechst_text'],
        'fruehester_termin': datum(lg['frueh']), 'termin': datum(lg['termin']),
        'zugang': datum(lg['zugang']), 'termine': termine,
        'intervall_hinweis': lg['intervall_hinweis'],
    }
