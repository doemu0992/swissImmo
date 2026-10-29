"""Kündigungsschutz nach Art. 271a OR: Sperrfristen bei der Vermieterkündigung (Audit MIET-06).

DER TEXT (Art. 271a Abs. 1 lit. d und e, Abs. 2 und 3 OR, Fedlex)

    Die Kündigung durch den Vermieter ist insbesondere anfechtbar, wenn sie ausgesprochen wird:
    d. während eines mit dem Mietverhältnis zusammenhängenden Schlichtungs- oder Gerichtsverfahrens, ausser wenn
       der Mieter das Verfahren missbräuchlich eingeleitet hat;
    e. vor Ablauf von drei Jahren nach Abschluss eines mit dem Mietverhältnis zusammenhängenden Schlichtungs-
       oder Gerichtsverfahrens, in dem der Vermieter: 1. zu einem erheblichen Teil unterlegen ist; 2. seine
       Forderung oder Klage zurückgezogen oder erheblich eingeschränkt hat; 3. auf die Anrufung des Richters
       verzichtet hat; 4. mit dem Mieter einen Vergleich geschlossen oder sich sonstwie geeinigt hat;
    Abs. 2: Buchstabe e gilt auch, wenn der Mieter durch Schriftstücke nachweisen kann, dass er sich mit dem
       Vermieter ausserhalb eines Verfahrens über eine Forderung aus dem Mietverhältnis geeinigt hat.
    Abs. 3: Buchstaben d und e gelten nicht bei Kündigungen wegen dringenden Eigenbedarfs, wegen Zahlungsrückstands
       (Art. 257d), wegen schwerer Verletzung der Sorgfaltspflicht (Art. 257f Abs. 3 und 4), infolge Veräusserung
       (Art. 261), aus wichtigen Gründen (Art. 266g) und wegen Konkurs des Mieters (Art. 266h).

(Der Auftrag nannte «lit. d–f». Lit. f betrifft Änderungen in der familiären Situation des Mieters und ist kein
Verfahrensschutz; hier umgesetzt sind lit. d, lit. e und Abs. 2. Lit. a–c — Kündigung wegen geltend gemachter
Ansprüche, wegen einer Mietzinsanpassung, um zum Kauf zu bewegen — hängen an der Absicht des Vermieters und
lassen sich nicht aus Daten ablesen.)

WAS DAS SYSTEM WEISS

· `rentals.Mietverfahren` — am Vertrag erfasste Verfahren und Einigungen, mit Beginn, Abschluss und Ausgang.
· `rentals.MietzinsAnpassung` im Status «angefochten» — eine angefochtene Mietzinsanpassung ist ein Schlichtungs-
  verfahren, das läuft. Seit wann, weiss nur das Versanddatum; der Abschluss ist nirgends erfasst, darum gilt es
  als hängig, bis der Status wechselt. Wer es abschliesst, erfasst es als `Mietverfahren`, damit die drei Jahre
  des lit. e nicht verloren gehen.

WAS DAS SYSTEM TUT

Eine Vermieterkündigung, die in eine Sperrfrist fällt, wird **nicht** stillschweigend angenommen: Die Erfassung hält
an und nennt den Grund. Sie bleibt möglich, wenn der Erfasser ausdrücklich bestätigt, dass eine Ausnahme nach
Abs. 3 vorliegt (etwa dringender Eigenbedarf, Veräusserung); die Bestätigung steht in der Kündigung (Bemerkung) und
im Protokoll. Eine Sperre, die nichts mehr zuliesse, wäre falsch: Die Kündigung ist anfechtbar, nicht nichtig.
Ausserordentliche Kündigungen aus den Gründen des Abs. 3 (257d, 257f, 266g, 266h) lösen nichts aus.

Das Kündigungsdatum ist das Datum, an dem die Kündigung ausgesprochen wird. Geprüft werden Versand und
(vermuteter) Zugang: Fällt eines davon in eine Sperrfrist, wird gewarnt — die sichere Seite.
"""
from dataclasses import dataclass
from datetime import date

from django.utils.translation import gettext

#: Ausserordentliche Gründe, für die Art. 271a Abs. 3 die Buchstaben d und e ausnimmt (Art. 257d, 257f, 266g,
#: 266h; die übrigen Ausnahmen — Eigenbedarf, Veräusserung — kennt die Erfassung nicht als Grund).
AUSNAHME_ARTEN = frozenset({'257d', '257f', '266g', '266h'})


@dataclass(frozen=True)
class Sperrfrist:
    #: 'd' (während eines Verfahrens) oder 'e' (drei Jahre danach)
    lit: str
    #: Meldung, übersetzt
    text: str
    #: Letzter geschützter Tag (nur lit. e), sonst None
    bis: date = None


def drei_jahre_nach(tag: date) -> date:
    """Derselbe Tag drei Jahre später; fehlt er im Zielmonat (29. Februar), der letzte Tag des Monats
    (Art. 77 Abs. 1 Ziff. 3 OR)."""
    try:
        return tag.replace(year=tag.year + 3)
    except ValueError:
        return date(tag.year + 3, tag.month, 28)


def _gegenstand(verfahren) -> str:
    return str(verfahren.get_gegenstand_display())


def sperrfristen(vertrag, daten, *, ausserordentlich_art='') -> list:
    """Alle Sperrfristen nach Art. 271a Abs. 1 lit. d und e, in die eines der `daten` fällt.

    `daten`: die Tage, an denen die Kündigung ausgesprochen wird (Versand, vermuteter Zugang).
    `ausserordentlich_art`: Grund einer ausserordentlichen Kündigung ('' = ordentlich); die Gründe des Abs. 3
    (`AUSNAHME_ARTEN`) lösen nichts aus."""
    if ausserordentlich_art in AUSNAHME_ARTEN:
        return []
    daten = [d for d in daten if d is not None]
    if not daten or vertrag is None or not vertrag.pk:
        return []
    from rentals.models import Mietverfahren

    treffer = []
    gesehen = set()

    def melden(sperre):
        if (sperre.lit, sperre.text) not in gesehen:
            gesehen.add((sperre.lit, sperre.text))
            treffer.append(sperre)

    for vf in vertrag.verfahren.all():
        # Missbräuchlich eingeleitet: lit. d entfällt ausdrücklich; lit. e greift mangels Unterliegen nicht.
        if vf.ausgang == 'missbraeuchlich':
            continue
        beginn, ende = vf.eingeleitet_am, vf.abgeschlossen_am
        # lit. d — während des Verfahrens
        for d in daten:
            if beginn <= d and (ende is None or d <= ende) and vf.art != Mietverfahren.ART_EINIGUNG:
                melden(Sperrfrist('d', gettext(
                    'Verfahren «%(art)s» (%(gegenstand)s), eingeleitet am %(beginn)s: %(zustand)s. Eine Kündigung des '
                    'Vermieters während eines Verfahrens um die Mietsache ist anfechtbar (Art. 271a Abs. 1 lit. d OR).'
                ) % {'art': str(vf.get_art_display()), 'gegenstand': _gegenstand(vf),
                     'beginn': f'{beginn:%d.%m.%Y}',
                     'zustand': (gettext('läuft') if ende is None
                                 else gettext('lief bis %(ende)s') % {'ende': f'{ende:%d.%m.%Y}'})}))
        # lit. e (und Abs. 2) — drei Jahre nach dem Abschluss, wenn der Vermieter nicht obsiegt hat
        if ende is not None and vf.ausgang in Mietverfahren.AUSGAENGE_NACHFRIST:
            bis = drei_jahre_nach(ende)
            for d in daten:
                if ende <= d <= bis:
                    melden(Sperrfrist('e', gettext(
                        'Das Verfahren (%(gegenstand)s) wurde am %(ende)s abgeschlossen: %(ausgang)s. Eine Kündigung '
                        'des Vermieters vor Ablauf von drei Jahren, also bis und mit %(bis)s, ist anfechtbar '
                        '(Art. 271a Abs. 1 lit. e OR).'
                    ) % {'gegenstand': _gegenstand(vf), 'ende': f'{ende:%d.%m.%Y}',
                         'ausgang': str(vf.get_ausgang_display()), 'bis': f'{bis:%d.%m.%Y}'}, bis=bis))

    # Eine angefochtene Mietzinsanpassung ist ein laufendes Schlichtungsverfahren (lit. d).
    for anp in vertrag.anpassungen.filter(status='angefochten'):
        beginn = anp.versand_am
        for d in daten:
            if beginn is None or beginn <= d:
                melden(Sperrfrist('d', gettext(
                    'Die Mietzinsanpassung per %(wirksam)s ist angefochten (Status «angefochten»): Ein '
                    'Schlichtungsverfahren läuft. Eine Kündigung des Vermieters während eines Verfahrens um die '
                    'Mietsache ist anfechtbar (Art. 271a Abs. 1 lit. d OR). Ist das Verfahren abgeschlossen, den '
                    'Ausgang unter «Verfahren» erfassen.') % {'wirksam': f'{anp.wirksam_ab:%d.%m.%Y}'}))
    return treffer


def ausnahmen_hinweis() -> str:
    """Die Ausnahmen des Abs. 3, die die Erfassung nicht aus Daten erkennt — der Erfasser bestätigt sie."""
    return gettext(
        'Ausnahmen (Art. 271a Abs. 3 OR): dringender Eigenbedarf des Vermieters oder naher Verwandter, '
        'Zahlungsrückstand (Art. 257d), schwere Verletzung der Sorgfaltspflicht (Art. 257f), Veräusserung der '
        'Sache (Art. 261), wichtige Gründe (Art. 266g), Konkurs des Mieters (Art. 266h).')
