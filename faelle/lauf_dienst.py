"""Planung und Abschluss der Läufe — EINE Stelle, die alle Wege benutzen.

WARUM ES DIESE DATEI GIBT

Zwei Befunde (Arbeitsvorrat «Heute», Stand 01.10.2026):

1. **Ausgeführte Läufe blieben «nicht ausgelöst».** Sollstellung, Mahnlauf,
   Bankabgleich und Zahllauf rechnen in ihren Views bzw. Scheduler-Befehlen —
   aber keiner dieser Wege hat je `Lauf.abschliessen()` aufgerufen. Der Lauf
   «August 2026» blieb ewig offen und wurde mit jedem Tag überfälliger.
2. **Der aktuelle Monat tauchte nicht auf.** Perioden entstanden nur, wenn
   jemand von Hand `manage.py laeufe_planen` startete; kein Scheduler und kein
   Seitenaufruf tat es.

Beides gehört zusammen: Wer Läufe plant, muss sie auch abschliessen können.
"""
import calendar
import logging
from datetime import date

from django.utils import timezone

from faelle.lauf_models import Lauf, Laufart

log = logging.getLogger(__name__)

# schluessel: (bezeichnung, rhythmus, faellig_am_tag, reihenfolge, entitlement, ziel)
VORLAGEN = {
    'sollstellung':  ('Sollstellung', Laufart.MONATLICH, 1, 10,
                      'monatslauf', 'fw_sollstellung'),
    'bankabgleich':  ('Bankabgleich', Laufart.MONATLICH, 5, 20,
                      'monatslauf', 'fw_bankabgleich'),
    'mahnlauf':      ('Mahnlauf', Laufart.MONATLICH, 15, 30,
                      'monatslauf', 'fw_mahnwesen'),
    'zahllauf':      ('Zahllauf Kreditoren', Laufart.MONATLICH, 25, 40,
                      'monatslauf', 'fw_zahllauf'),
    'mwst':          ('MWST-Abrechnung', Laufart.QUARTALSWEISE, 28, 50,
                      'monatslauf', 'fw_mwst'),
    'nebenkosten':   ('Nebenkostenabrechnung', Laufart.JAEHRLICH, 30, 60,
                      'nebenkostenlauf', 'fw_nebenkosten'),
}

#: Monate, in denen ein quartalsweiser bzw. jaehrlicher Lauf faellig wird.
QUARTALSMONATE = (1, 4, 7, 10)
JAHRESMONAT = 9          # Abgabe der Nebenkostenabrechnung: September


def periode_fuer(art, stichtag):
    """Periodenschluessel je Rhythmus, oder None wenn jetzt nichts ansteht."""
    if art.rhythmus == Laufart.MONATLICH:
        return f'{stichtag.year}-{stichtag.month:02d}'
    if art.rhythmus == Laufart.QUARTALSWEISE:
        if stichtag.month not in QUARTALSMONATE:
            return None
        return f'{stichtag.year}-Q{(stichtag.month - 1) // 3 + 1}'
    if stichtag.month != JAHRESMONAT:
        return None
    return str(stichtag.year - 1)      # abgerechnet wird das Vorjahr


def faelligkeits_tag(art):
    """Der Tag im Monat, an dem der Lauf fällig ist.

    Beim Mahnlauf folgt er den Mahnstufen der Organisation (erste Stufe + Verzugsbeginn,
    `core.services.mahnstufen.mahnlauf_tag_im_monat`) und nicht der Vorgabe in
    `VORLAGEN` — sonst stünde dort ein fester Tag, der mit den eingestellten
    Fristen nichts zu tun hat. Alle anderen Läufe: der eingestellte Tag.
    """
    if art.schluessel == 'mahnlauf':
        from core.services.mahnstufen import mahnlauf_tag_im_monat
        # alle_organisationen/organisation_id: Die Laufart kennt ihre Organisation;
        # der Lauf läuft auch im Scheduler ohne Anfrage.
        tag = mahnlauf_tag_im_monat(art.organisation)
        if tag is not None:
            return tag
    return art.faellig_am_tag


def faelligkeit(art, stichtag):
    tag = min(faelligkeits_tag(art), calendar.monthrange(stichtag.year, stichtag.month)[1])
    return date(stichtag.year, stichtag.month, tag)


def mahnlauf_termin_nachziehen(organisation, heute=None):
    """Setzt den Fälligkeitstermin der OFFENEN Mahnläufe (ab dem laufenden Monat) neu.

    Nötig, weil ein Lauf sein Fälligkeitsdatum beim Planen bekommt: Ändert die
    Verwaltung die Mahnstufen, müsste sonst der schon geplante Lauf auf dem alten
    Datum stehen bleiben (z. B. 15.10., obwohl Stufe 1 jetzt ab 0 Tagen gilt).
    Abgeschlossene und übersprungene Läufe bleiben unangetastet. Idempotent.
    """
    heute = heute or timezone.localdate()
    ab = f'{heute.year}-{heute.month:02d}'
    geaendert = 0
    laeufe = (Lauf.alle_organisationen
              .filter(laufart__organisation=organisation, laufart__schluessel='mahnlauf',
                      status=Lauf.OFFEN, periode__gte=ab)
              .select_related('laufart'))
    for lauf in laeufe:
        try:
            jahr, monat = (int(x) for x in lauf.periode.split('-'))
        except ValueError:
            continue
        soll = faelligkeit(lauf.laufart, date(jahr, monat, 1))
        tag = faelligkeits_tag(lauf.laufart)
        if lauf.faellig_am != soll:
            Lauf.alle_organisationen.filter(pk=lauf.pk).update(faellig_am=soll)
            geaendert += 1
        if lauf.laufart.faellig_am_tag != tag:
            Laufart.alle_organisationen.filter(pk=lauf.laufart_id).update(faellig_am_tag=tag)
    return geaendert


def planen(organisation, stichtag=None):
    """Legt Laufarten und die Perioden des Stichtag-Monats an — idempotent.

    Rückgabe: (neue Laufarten, neue Läufe). Bestehende Laufarten bleiben
    unverändert (die Verwaltung darf den Fälligkeitstag anpassen), eine
    bereits geplante Periode wird nicht doppelt angelegt, und ein
    abgeschlossener Lauf wird nie wieder geöffnet.
    """
    stichtag = stichtag or timezone.localdate()
    mahnlauf_termin_nachziehen(organisation, stichtag)
    neue_arten = neue_laeufe = 0
    for schluessel, (bez, rhythmus, tag, reihe, ent, ziel) in VORLAGEN.items():
        art, erzeugt = Laufart.alle_organisationen.get_or_create(
            organisation=organisation, schluessel=schluessel,
            defaults={'bezeichnung': bez, 'rhythmus': rhythmus,
                      'faellig_am_tag': tag, 'reihenfolge': reihe,
                      'entitlement': ent, 'ziel_ansicht': ziel})
        neue_arten += int(erzeugt)
        if not art.aktiv:
            continue
        periode = periode_fuer(art, stichtag)
        if periode is None:
            continue
        _lauf, neu = Lauf.alle_organisationen.get_or_create(
            laufart=art, periode=periode,
            defaults={'organisation': organisation,
                      'faellig_am': faelligkeit(art, stichtag)})
        neue_laeufe += int(neu)
    return neue_arten, neue_laeufe


def aktuelle_periode_sicherstellen(organisation, heute=None):
    """Stellt sicher, dass die Läufe des laufenden Monats im Vorrat stehen.

    Billig im Normalfall: Eine einzige Abfrage, wenn alles da ist. Fehlt
    etwas, wird nachgeplant — damit der Arbeitsvorrat auch dann stimmt, wenn
    der Scheduler nie eingerichtet wurde oder einen Monat ausgesetzt hat.
    """
    heute = heute or timezone.localdate()
    if organisation is None:
        return 0
    # Nur Verwaltungen, deren Planung schon einmal gelaufen ist: Es gibt
    # bereits Läufe einer Standard-Laufart mit Periode bis heute. Wer nie
    # geplant hat, bekommt keine: Eine leere Liste ist ehrlicher als Läufe,
    # die niemand bestellt hat. (Eine Verwaltung ohne jede Planung holt der
    # tägliche Lauf bzw. `laeufe_planen` ein.)
    if not (Lauf.alle_organisationen
            .filter(laufart__organisation=organisation,
                    laufart__schluessel__in=list(VORLAGEN),
                    periode__lte=f'{heute.year}-{heute.month:02d}')
            .exists()):
        return 0
    # Ein bereits geplanter Mahnlauf folgt den aktuellen Mahnstufen (siehe Docstring).
    mahnlauf_termin_nachziehen(organisation, heute)
    erwartet = 0
    for schluessel, (_b, rhythmus, *_rest) in VORLAGEN.items():
        if rhythmus == Laufart.MONATLICH:
            erwartet += 1
    periode = f'{heute.year}-{heute.month:02d}'
    vorhanden = (Lauf.alle_organisationen
                 .filter(laufart__organisation=organisation, periode=periode,
                         laufart__rhythmus=Laufart.MONATLICH).count())
    if vorhanden >= erwartet:
        return 0
    return planen(organisation, heute)[1]


def lauf_erledigt(schluessel, periode, benutzer=None, auch_aeltere=False,
                  **kennzahlen):
    """Schliesst den Lauf `schluessel` der Periode ab, falls er geplant ist.

    Aufgerufen von jedem Weg, der den Lauf tatsächlich ausführt. Verhalten:

    * Kein geplanter Lauf (Laufarten nie angelegt) → nichts, kein Fehler. Der
      Arbeitsvorrat zeigt dann ohnehin nichts, das es abzuschliessen gäbe.
    * Bereits abgeschlossen / bewusst übersprungen → unverändert (idempotent).
    * Offene Blockade → bleibt offen, wird protokolliert. Ein Lauf mit
      stehender Ursache darf nicht aus dem Vorrat verschwinden.

    `auch_aeltere=True` für Läufe ohne Periodenwahl (Mahnlauf, Bankabgleich,
    Zahllauf): Sie verarbeiten IMMER den ganzen heutigen Bestand. Ein im
    Oktober ausgeführter Mahnlauf hat damit auch den versäumten August
    erledigt — sonst bliebe «Mahnlauf 2026-08» ewig überfällig.

    Ein Fehler hier darf die Ausführung selbst nie zurückrollen: Die Buchungen
    sind gemacht, die Buchführung darüber ist nachgeordnet.
    """
    try:
        if auch_aeltere:
            for alt in (Lauf.objects.offen().select_related('laufart')
                        .filter(laufart__schluessel=schluessel,
                                laufart__rhythmus=Laufart.MONATLICH,
                                periode__lt=periode,
                                faellig_am__lt=timezone.localdate())):
                lauf_erledigt(schluessel, alt.periode, benutzer=benutzer,
                              quelle='mit späterem Lauf erledigt')
        lauf = (Lauf.objects.select_related('laufart')
                .filter(laufart__schluessel=schluessel, periode=periode).first())
        if lauf is None:
            return None
        if lauf.status in (Lauf.ABGESCHLOSSEN, Lauf.UEBERSPRUNGEN):
            return lauf
        try:
            return lauf.abschliessen(benutzer=benutzer, **kennzahlen)
        except ValueError:
            log.warning('Lauf %s bleibt offen: Blockade steht.', lauf)
            return lauf
    except Exception:
        log.exception('Lauf «%s» %s konnte nicht abgeschlossen werden',
                      schluessel, periode)
        return None


def periode_von(datum):
    return f'{datum.year}-{datum.month:02d}'


def abgleichen_aus_daten(stichtag=None):
    """Schliesst überfällige Monatsläufe, deren Ausführung in den Daten belegt ist.

    Für Läufe, die ausgeführt wurden, bevor die Verdrahtung existierte (Stand
    «August 2026»). Es wird nur geschlossen, was ein Beleg stützt:

        sollstellung   Debitorenrechnung «Miete & NK MM/JJJJ»
        bankabgleich   verbuchter Zahlungseingang im Monat
        mahnlauf       erfasste Mahnung im Monat
        zahllauf       Kreditorenzahlung im Monat

    Rückgabe: Anzahl abgeschlossener Läufe. Offene Blockaden werden respektiert.
    """
    from finance.models import (DebitorenRechnung, KreditorenZahlung, Mahnung,
                                Zahlungseingang)

    stichtag = stichtag or timezone.localdate()
    belege = {
        'sollstellung': lambda j, m: DebitorenRechnung.objects.filter(
            titel=f'Miete & NK {m:02d}/{j}').exists(),
        'bankabgleich': lambda j, m: Zahlungseingang.objects.filter(
            datum_eingang__year=j, datum_eingang__month=m,
            status='verbucht').exists(),
        'mahnlauf': lambda j, m: Mahnung.objects.filter(
            datum__year=j, datum__month=m).exists(),
        'zahllauf': lambda j, m: KreditorenZahlung.objects.filter(
            datum__year=j, datum__month=m).exists(),
    }
    n = 0
    for lauf in (Lauf.objects.ueberfaellig(stichtag).select_related('laufart')
                 .filter(laufart__schluessel__in=belege.keys(),
                         laufart__rhythmus=Laufart.MONATLICH)):
        try:
            jahr, monat = (int(t) for t in lauf.periode.split('-'))
        except ValueError:
            continue
        if belege[lauf.laufart.schluessel](jahr, monat):
            lauf_erledigt(lauf.laufart.schluessel, lauf.periode,
                          quelle='abgleich aus Belegen')
            lauf.refresh_from_db()
            n += int(lauf.status == Lauf.ABGESCHLOSSEN)
    return n
