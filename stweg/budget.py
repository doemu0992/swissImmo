"""Jahresbudget: aufstellen, der Versammlung vorlegen, genehmigen → Akonto-Vorschreibungen.

Der Ablauf ist an den Beschluss gebunden: Ein Budget wird nur über `budget_genehmigen`
genehmigt, und das verlangt den Status «vorgelegt». Hängt das Budget an einem Traktandum
(`Traktandum.budget`), ruft `beschluss.feststellen` es bei «angenommen» selbst auf.

Der Jahresbetrag einer Einheit ist die Summe ihrer Anteile an den Budgetpositionen, je
Schlüssel einmal rappengenau verteilt (`stweg.schluessel`). Er wird in gleich grosse Raten
geteilt (grösster Rest — die Raten ergeben den Jahresbetrag exakt) und mit Fälligkeit
vorgeschrieben. Die Vorschreibung ist eine Forderung; die Zahlung kommt als `StwegAkonto`.
Gebucht wird hier nichts (siehe docs/STWEG.md, «Hauptbuch»).
"""
import calendar
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.tenancy import organisation_kontext
from stweg.models import StwegBudget, StwegBudgetPosition, StwegVorschreibung
from stweg.schluessel import SchluesselFehler, verteile
from stweg.validierung import WertquotenFehler, pruefe_wertquoten, stimm_einheiten
from stweg.verteilung import verteile_nach_quoten

NULL = Decimal('0.00')


def _plus_monate(d, n):
    """`d` plus `n` Monate; der Tag wird auf das Monatsende begrenzt (31.01. + 1 → 28./29.02.)."""
    monat = d.month - 1 + n
    jahr, monat = d.year + monat // 12, monat % 12 + 1
    return date(jahr, monat, min(d.day, calendar.monthrange(jahr, monat)[1]))


class BudgetFehler(ValueError):
    pass


def position_setzen(budget, bezeichnung, schluessel, betrag):
    """Fügt eine Position hinzu — nur solange das Budget noch nicht genehmigt ist."""
    budget.refresh_from_db(fields=['status'])       # nie nach einem veralteten Stand entscheiden
    if budget.status == StwegBudget.GENEHMIGT:
        raise BudgetFehler('Ein genehmigtes Budget ist abgeschlossen.')
    if schluessel.liegenschaft_id != budget.liegenschaft_id:
        raise BudgetFehler('Der Schlüssel gehört zu einer anderen Gemeinschaft.')
    betrag = Decimal(betrag)
    if betrag <= 0:
        raise BudgetFehler('Der Betrag einer Budgetposition muss grösser 0 sein.')
    p = StwegBudgetPosition.objects.create(budget=budget, bezeichnung=bezeichnung,
                                           schluessel=schluessel, betrag=betrag)
    if budget.status == StwegBudget.VORGELEGT:       # geändert → muss neu vorgelegt werden
        budget.status = StwegBudget.ENTWURF
        budget.save(update_fields=['status'])
    return p


def jahresbetraege(budget):
    """{einheit: {'summe': Decimal, 'aufteilung': [{'schluessel', 'betrag'}…]}} nach den Schlüsseln."""
    einheiten = list(stimm_einheiten(budget.liegenschaft).order_by('pk'))
    je_schluessel = {}
    for p in budget.positionen.select_related('schluessel'):
        je_schluessel.setdefault(p.schluessel_id, [p.schluessel, NULL])[1] += p.betrag
    ergebnis = {e: {'summe': NULL, 'aufteilung': []} for e in einheiten}
    for sl, summe in je_schluessel.values():
        try:
            anteile, _ = verteile(summe, sl, einheiten)
        except SchluesselFehler as e:
            raise BudgetFehler(str(e))
        for e in einheiten:
            ergebnis[e]['summe'] += anteile[e.pk]
            ergebnis[e]['aufteilung'].append({'schluessel': sl.name, 'betrag': str(anteile[e.pk])})
    return ergebnis


def pruefen(budget):
    """Gründe, die dem Vorlegen im Weg stehen (leer = in Ordnung)."""
    probleme = []
    if not budget.positionen.exists():
        probleme.append('Das Budget hat keine Positionen.')
    try:
        pruefe_wertquoten(budget.liegenschaft)
    except WertquotenFehler as e:
        probleme.append(str(e.message))
    if not probleme:
        try:
            jahresbetraege(budget)
        except BudgetFehler as e:
            probleme.append(str(e))
    return probleme


def vorlegen(budget):
    budget.refresh_from_db(fields=['status'])
    if budget.status not in (StwegBudget.ENTWURF, StwegBudget.VORGELEGT):
        raise BudgetFehler(f'Ein Budget im Status «{budget.get_status_display()}» kann nicht vorgelegt werden.')
    probleme = pruefen(budget)
    if probleme:
        raise BudgetFehler(' '.join(probleme))
    budget.status = StwegBudget.VORGELEGT
    budget.save(update_fields=['status'])
    return budget


def _faelligkeiten(budget):
    start = budget.erste_faelligkeit or date(budget.jahr, 1, 1)
    abstand = 12 // budget.raten if 12 % budget.raten == 0 else None
    if abstand is None:
        raise BudgetFehler(f'{budget.raten} Raten lassen sich nicht gleichmässig auf zwölf Monate legen.')
    return [_plus_monate(start, abstand * i) for i in range(budget.raten)]


@transaction.atomic
def budget_genehmigen(budget, *, traktandum=None):
    """Genehmigt das Budget und schreibt die Akonto-Raten vor. Nur einmal, nur aus «vorgelegt»."""
    aufrufer = budget
    budget = StwegBudget.objects.select_for_update().get(pk=budget.pk)
    if budget.status != StwegBudget.VORGELEGT:
        raise BudgetFehler(f'Genehmigt werden kann nur ein vorgelegtes Budget (Status: '
                           f'{budget.get_status_display()}).')
    lg = budget.liegenschaft
    with organisation_kontext(lg.organisation):
        probleme = pruefen(budget)
        if probleme:
            raise BudgetFehler(' '.join(probleme))
        faellig = _faelligkeiten(budget)
        neu = []
        for einheit, d in jahresbetraege(budget).items():
            raten = verteile_nach_quoten(d['summe'], {i: 1 for i in range(budget.raten)})
            for i, datum in enumerate(faellig):
                neu.append(StwegVorschreibung.objects.create(
                    budget=budget, einheit=einheit, eigentuemer=einheit.stockwerkeigentuemer,
                    rate_nr=i + 1, rate_total=budget.raten, faellig_am=datum, betrag=raten[i],
                    jahresbetrag=d['summe'], aufteilung=d['aufteilung']))
        budget.status = StwegBudget.GENEHMIGT
        budget.genehmigt_am = timezone.now()
        budget.save(update_fields=['status', 'genehmigt_am'])
    aufrufer.status, aufrufer.genehmigt_am = budget.status, budget.genehmigt_am     # kein veralteter Stand
    return neu


def budget_ablehnen(budget):
    budget.refresh_from_db(fields=['status'])
    if budget.status != StwegBudget.VORGELEGT:
        raise BudgetFehler('Abgelehnt werden kann nur ein vorgelegtes Budget.')
    budget.status = StwegBudget.ABGELEHNT
    budget.save(update_fields=['status'])
    return budget


def an_traktandum_haengen(traktandum, budget):
    """Das Budget wird unter diesem Traktandum beschlossen. Legt es der Versammlung vor."""
    if traktandum.versammlung.liegenschaft_id != budget.liegenschaft_id:
        raise BudgetFehler('Budget und Traktandum gehören zu verschiedenen Gemeinschaften.')
    if traktandum.ergebnis != traktandum.OFFEN:
        raise BudgetFehler('Das Traktandum ist schon entschieden.')
    vorlegen(budget)
    traktandum.budget = budget
    traktandum.save(update_fields=['budget'])
    return traktandum


def vorschreibungen_versenden(budget):
    """Schickt jedem Eigentümer seine Akonto-Rechnung (PDF mit QR-Zahlteilen) per E-Mail.

    Wiederholbar: wer sie schon hat (`versendet_am`), bekommt keine zweite. Wer keine
    E-Mail-Adresse hat, wird übersprungen und in der Rückgabe als «post» genannt."""
    from core.utils.email_service import send_via_hoststar
    from stweg.models import StwegVorschreibung
    from stweg.pdf import vorschreibung_pdf
    from tickets.workflow import reply_to
    budget.refresh_from_db(fields=['status'])
    if budget.status != StwegBudget.GENEHMIGT:
        raise BudgetFehler('Akonto-Rechnungen gibt es erst nach der Genehmigung des Budgets.')
    org = budget.liegenschaft.organisation
    je_eig = {}
    for v in StwegVorschreibung.objects.filter(budget=budget, versendet_am__isnull=True,
                                                eigentuemer__isnull=False).select_related('eigentuemer'):
        je_eig.setdefault(v.eigentuemer_id, (v.eigentuemer, []))[1].append(v)
    ergebnis = {'gesendet': [], 'post': [], 'fehler': []}
    for eig, vs in je_eig.values():
        if not eig.email:
            ergebnis['post'].append(eig)
            continue
        html = ("<html><body style='font-family:Arial,sans-serif;line-height:1.5'>"
                f"<p>Guten Tag {eig.firma_oder_name}</p>"
                f"<p>die Versammlung hat das Budget {budget.jahr} der Gemeinschaft {budget.liegenschaft} "
                "genehmigt. In der Beilage Ihre Akonto-Rechnung mit Zahlteilen.</p>"
                f"<p>Freundliche Grüsse<br>{org.firma}</p></body></html>")
        ok = send_via_hoststar(eig.email, f'Akonto-Rechnung {budget.jahr}', html,
                               f'Akonto_{budget.jahr}.pdf', vorschreibung_pdf(budget, eig),
                               reply_to=reply_to(budget))
        if ok:
            StwegVorschreibung.objects.filter(pk__in=[v.pk for v in vs]).update(versendet_am=timezone.now())
            ergebnis['gesendet'].append(eig)
        else:
            ergebnis['fehler'].append(eig)
    return ergebnis
