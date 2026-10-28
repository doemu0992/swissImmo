"""Kündigungsverzicht und Befristung: bis wann der Vermieter nicht ordentlich kündigen kann.

DIE UNTERSCHEIDUNG STEHT HIER, AN EINER STELLE

* **Gesperrt** ist die **ordentliche Kündigung durch den Vermieter** mit Wirkung vor dem Datum, bis zu dem
  der Vertrag fest ist: das Ende eines befristeten Vertrags (Art. 266 OR: endet ohne Kündigung) oder das
  Datum des Kündigungsverzichts (`Mietvertrag.vermieter_kuendigungsverzicht_bis`, Art. 17 Abs. 4 VMWG).
  Das Datum liefert `mietzinsmodell.fest_bis` — dieselbe Rechnung, die die Dauer der Index- und Staffelmiete
  prüft.
* **Nicht gesperrt** bleiben die Kündigung durch den Mieter und jede **ausserordentliche** Kündigung. Wie
  eine Kündigung erfasst ist, steht im Bestand fest: `Kuendigung.absender` ('mieter' | 'vermieter') und
  `Kuendigung.ausserordentlich` (mit `ausserordentlich_art` aus `Kuendigung.AO_ART_CHOICES`: 257d, 257f,
  266g, 266h, 266i, 266k; für den Vermieter gelten die Gründe `rentals.services.AO_GRUENDE_VERMIETER`).
  Der Zahlungsverzug (Art. 257d OR) läuft über denselben Weg mit `ausserordentlich_art='257d'`.

Das Datum ist inklusive: Ein Vertragsende genau am Datum des Verzichts ist zulässig, ein Tag davor nicht.

BEFRISTET OHNE KÜNDIGUNGSRECHT (Audit MIET-07)

Ein befristeter Vertrag endet ohne Kündigung mit Ablauf der Dauer (Art. 266 Abs. 1 OR). Eine ordentliche
Kündigung gibt es dort nur, wenn der Vertrag sie ausdrücklich vorsieht — im Bestand das Feld
`Mietvertrag.erstmals_kuendbar_auf`. Ohne dieses Datum ist eine ordentliche Kündigung, gleich von wem, rechtlich
wirkungslos; erfasst, würde sie das Vertragsende auf einen Termin verschieben, den es nicht gibt (Sollstellung und
Leerstand folgen ihm). Darum:

* Der Vermieter kann sie nicht erfassen (Art. 266 Abs. 1 OR).
* Der Mieter kann nur vorzeitig zurückgeben (Art. 264 OR): Er wird frei, wenn ein zumutbarer, zahlungsfähiger
  Ersatzmieter den Vertrag zu gleichen Bedingungen übernimmt, sonst schuldet er den Mietzins bis zum Ende der
  Vertragsdauer. Das ist keine Kündigung; `termin` ist dort das vereinbarte Vertragsende.
* Ausserordentliche Kündigungen (257d, 257f, 266g …) bleiben möglich, wie schon beim Kündigungsverzicht.
"""
from datetime import date

from django.utils.translation import gettext

#: Artikel, die in der Meldung stehen.
ART_VERZICHT = 'Art. 17 Abs. 4 VMWG'
ART_BEFRISTET = 'Art. 266 OR'


def ist_ordentliche_vermieterkuendigung(absender, ausserordentlich):
    """Nur diese Kündigung unterliegt dem Verzicht bzw. der Befristung."""
    return absender == 'vermieter' and not ausserordentlich


def fest_bis_von(vertrag, ende=None):
    """(Datum, Art) bis zu dem der Vermieter nicht ordentlich kündigen kann, sonst (None, '').

    `Art` ist 'befristet' oder 'verzicht'. `ende` überschreibt `vertrag.ende` (der Stand vor einer
    Kündigung, die `ende` verschoben hat)."""
    from core.services.mietzinsmodell import fest_bis
    ende = vertrag.ende if ende is None else ende
    bis = fest_bis(vertrag.beginn, ende, vertrag.ist_befristet, vertrag.vermieter_kuendigungsverzicht_bis)
    if bis is None:
        return None, ''
    return bis, ('befristet' if (vertrag.ist_befristet and ende) else 'verzicht')


def sperre_text(vertrag, wirkung, *, absender, ausserordentlich, ende=None):
    """Meldung, wenn diese Kündigung nicht erfasst werden darf — sonst ''.

    `wirkung` ist das Datum, an dem das Mietverhältnis durch die Kündigung endet (`Kuendigung.per_datum`)."""
    if not ist_ordentliche_vermieterkuendigung(absender, ausserordentlich) or not isinstance(wirkung, date):
        return ''
    bis, art = fest_bis_von(vertrag, ende)
    if bis is None or wirkung >= bis:
        return ''
    daten = {'datum': bis.strftime('%d.%m.%Y'), 'wirkung': wirkung.strftime('%d.%m.%Y')}
    if art == 'befristet':
        return gettext(
            'Der Vertrag ist befristet und endet am %(datum)s ohne Kündigung (Art. 266 OR). Eine ordentliche '
            'Kündigung durch den Vermieter mit Wirkung auf den %(wirkung)s (vor diesem Datum) kann nicht erfasst '
            'werden. Ausserordentliche Kündigungen, etwa wegen Zahlungsverzugs (Art. 257d OR), bleiben möglich.'
        ) % daten
    return gettext(
        'Der Vermieter hat bis zum %(datum)s auf die Kündigung verzichtet (Kündigungsverzicht, Art. 17 Abs. 4 '
        'VMWG). Eine ordentliche Kündigung mit Wirkung auf den %(wirkung)s (vor diesem Datum) kann nicht '
        'erfasst werden. Ausserordentliche Kündigungen, etwa wegen Zahlungsverzugs (Art. 257d OR), bleiben '
        'möglich.') % daten


def befristet_ohne_kuendigungsrecht(vertrag, ende=None):
    """True bei einem befristeten Vertrag, der keine ordentliche Kündigung vorsieht (`erstmals_kuendbar_auf`
    leer). `ende` überschreibt `vertrag.ende`."""
    ende = vertrag.ende if ende is None else ende
    return bool(vertrag.ist_befristet and ende and not vertrag.erstmals_kuendbar_auf)


def befristung_sperre_text(vertrag, *, ausserordentlich, vorzeitige_rueckgabe, ende=None):
    """Meldung, wenn eine ORDENTLICHE Kündigung eines befristeten Vertrags ohne Kündigungsrecht erfasst werden
    soll — sonst ''.

    `vorzeitige_rueckgabe`: Der Mieter gibt vor dem Vertragsende zurück (Art. 264 OR); das ist erfassbar, sie
    ist aber keine Kündigung und lässt das Vertragsende, wie es ist."""
    if ausserordentlich or vorzeitige_rueckgabe or not befristet_ohne_kuendigungsrecht(vertrag, ende):
        return ''
    ende = vertrag.ende if ende is None else ende
    return gettext(
        'Der Vertrag ist befristet und endet am %(datum)s ohne Kündigung (Art. 266 OR). Eine ordentliche '
        'Kündigung sieht er nicht vor (kein «Erstmals kündbar auf»), sie wäre wirkungslos und kann nicht erfasst '
        'werden. Zieht der Mieter früher aus, das gewünschte Ende vor dem %(datum)s angeben (vorzeitige Rückgabe, '
        'Art. 264 OR); ausserordentliche Kündigungen, etwa wegen Zahlungsverzugs (Art. 257d OR), bleiben möglich. '
        'Einigen sich die Parteien auf ein früheres Ende, ist das ein Aufhebungsvertrag: Das Vertragsende unter '
        '«Vertrag bearbeiten» anpassen.'
    ) % {'datum': ende.strftime('%d.%m.%Y')}
