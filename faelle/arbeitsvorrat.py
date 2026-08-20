"""Der Arbeitsvorrat — eine Liste, nicht zwei.

WARUM ES DIESE DATEI GIBT

Die Bausteine aus Phase 4a — `Fall`, `Fallschritt`, `Eingang`, `Lauf`,
`Blockade` — hatten nach vier Etappen **keine einzige View und keine URL**.
Vollständig getestet und für niemanden erreichbar. Hier werden sie sichtbar.

DIE ENTSCHEIDUNG, DIE DIESE DATEI PRÄGT

Ein erster Entwurf stellte «Was reisst» als neuen Abschnitt **neben** die
bestehende Inbox. Das wäre eine zweite Arbeitsliste gewesen — und dieselbe
Pendenz hätte zweimal auf derselben Seite gestanden, hundert Pixel
auseinander: `core/services/inbox.py` sammelte einzelne Pendenzen im selben
14-Tage-Fenster und Wartungsfristen im 30-Tage-Fenster.

`KONZEPT-UI.md`, Grundentscheidung **G2**, verbietet das ausdrücklich:

    «Ein Arbeitsvorrat, nicht zwei Listen. ‹Heute› und ‹Fälle› sind dasselbe.»

Deshalb die Arbeitsteilung:

    hier (Arbeitsvorrat)     EINZELNE, datierte Vorgänge — Fallschritt,
                             Pendenz, Wartungsfrist, Lauf. Alles, was ein
                             Datum trägt und liegenbleiben kann.
    core/services/inbox.py   SAMMELPOSTEN — «12 Rechnungen prüfen»,
                             «3 Schäden ungelesen». Zahlen über Stapel,
                             keine Einzelvorgänge.

Die Pendenz- und Wartungsfrist-Blöcke sind aus `inbox.py` **entfernt** und
nicht kopiert. Wer sie dort wieder einbaut, erzeugt die Doppelung neu;
`test_keine_doppelung_zwischen_inbox_und_vorrat` hält das fest.

MANDANTENTRENNUNG

Alle Abfragen laufen über die gefilterten Manager (`objects`, nie
`alle_organisationen`). Ein Arbeitsvorrat, der einen fremden Eingang zeigt,
ist der teuerste denkbare Fehler dieser Anwendung.
"""
import logging
from datetime import timedelta

from django.utils import timezone

log = logging.getLogger(__name__)

#: Wie weit «was reisst» nach vorn schaut. Vierzehn Tage, damit eine
#: zehntägige mietrechtliche Reaktionsfrist auffällt, bevor sie halb
#: abgelaufen ist.
VORSCHAU_TAGE = 14

#: Zeilen je Abschnitt auf der Startseite. Der Rest steht hinter «Alle …» —
#: ein Arbeitsvorrat, den man scrollen muss, ist keiner.
ZEILEN = 5


def _dringlichkeit(tage):
    """Wie ein Eintrag markiert wird. Negativ heisst überfällig."""
    if tage is None:
        return 'neutral'
    if tage < 0:
        return 'crit'
    if tage <= 3:
        return 'warn'
    return 'neutral'


def _laeufe(heute, bis):
    """Läufe, die fällig sind oder blockiert stehen.

    Ein blockierter Lauf zeigt den **Grund** («Verbrauchsablesung Techem
    fehlt»), nicht das Wort «blockiert». Der Grund führt zu einer Handlung,
    das Wort zu einer Rückfrage.
    """
    from faelle.lauf_models import Lauf

    zeilen = []
    for lauf in (Lauf.objects.offen().filter(faellig_am__lte=bis)
                 .select_related('laufart')[:20]):
        tage = (lauf.faellig_am - heute).days
        blockaden = list(lauf.offene_blockaden)
        zeilen.append({
            'art': 'lauf', 'ikon': 'fa-rotate',
            'titel': f'{lauf.laufart.bezeichnung} {lauf.periode}'
                     + (' nicht ausgelöst' if tage < 0 else ''),
            'zeile': (', '.join(b.grund for b in blockaden) if blockaden
                      else f'Stichtag {lauf.faellig_am.strftime("%d.%m.")}'),
            'datum': lauf.faellig_am, 'tage': tage,
            'dringlichkeit': 'crit' if blockaden else _dringlichkeit(tage),
            'ziel': '/neu/laeufe/', 'knopf': 'Zum Lauf', 'objekt': lauf,
        })
    return zeilen


def _fallschritte(heute, bis):
    """Offene Fallschritte mit Frist.

    Das Fristfeld heisst `frist`, nicht `faellig_am` — nachgesehen, nicht
    geraten. Ein Entwurf nahm `faellig_am` an; der `except`-Zweig unten hätte
    den `FieldError` geschluckt und den Abschnitt **dauerhaft leer** gelassen.
    Das ist hier die gefährlichste Fehlerart: Eine leere Liste sieht aus wie
    ein ruhiger Tag.
    """
    from faelle.models import Fallschritt

    zeilen = []
    for s in (Fallschritt.objects.filter(erledigt_am__isnull=True,
                                         frist__isnull=False, frist__lte=bis)
              .select_related('fall', 'fall__fallart')[:20]):
        tage = (s.frist - heute).days
        zeilen.append({
            'art': 'fall', 'ikon': 'fa-folder-open',
            'titel': s.bezeichnung,
            'zeile': (f'{s.fall.fallart.bezeichnung} · {s.fall.betreff}'
                      if s.fall.betreff else s.fall.fallart.bezeichnung),
            'datum': s.frist, 'tage': tage,
            'dringlichkeit': _dringlichkeit(tage),
            'ziel': f'/neu/faelle/{s.fall_id}/', 'knopf': 'Fall öffnen',
            'objekt': s,
        })
    return zeilen


def _pendenzen(heute, bis, aktive_lg=None):
    """Einzelne Pendenzen — bis 4c die Domäne der Inbox.

    Sie sind dorthin gewandert, nicht kopiert. Das Ziel kommt weiterhin aus
    `_pendenz_ziel()`: Sonst verlöre die 257d-Pendenz ihren Weg zur
    Zugangserfassung, und aus einer Umstellung der Anzeige würde ein
    Funktionsverlust.
    """
    from django.db.models import Q

    from core.models import Pendenz
    from core.views.fw._basis import _pendenz_ziel

    pq = (Pendenz.objects.filter(erledigt=False)
          .exclude(quelle__startswith='auto:kautionfreigabe:'))
    if aktive_lg:
        pq = pq.filter(Q(liegenschaft=aktive_lg)
                       | Q(vertrag__einheit__liegenschaft=aktive_lg)
                       | Q(liegenschaft__isnull=True, vertrag__isnull=True))
    zeilen = []
    for p in (pq.filter(faellig_am__isnull=False, faellig_am__lte=bis)
              .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft',
                              'liegenschaft').order_by('faellig_am')[:20]):
        url, knopf, _wide, modal = _pendenz_ziel(p)
        tage = (p.faellig_am - heute).days
        zeilen.append({
            'art': 'pendenz', 'ikon': 'fa-clock',
            'titel': p.titel,
            'zeile': p.beschreibung[:120] or p.get_kategorie_display(),
            'datum': p.faellig_am, 'tage': tage,
            'dringlichkeit': _dringlichkeit(tage),
            'ziel': url or '/neu/pendenzen/', 'knopf': knopf or 'Öffnen',
            'modal': modal, 'objekt': p,
        })
    return zeilen


def _wartungsfristen(heute, bis, aktive_lg=None):
    """Wartungs- und Versicherungsfristen der Liegenschaften."""
    from portfolio.models import Wartungsfrist

    wf = (Wartungsfrist.objects.filter(aktiv=True, naechste_faelligkeit__lte=bis)
          .select_related('liegenschaft'))
    if aktive_lg:
        wf = wf.filter(liegenschaft=aktive_lg)
    zeilen = []
    for w in wf.order_by('naechste_faelligkeit')[:20]:
        tage = (w.naechste_faelligkeit - heute).days
        zeilen.append({
            'art': 'wartung', 'ikon': 'fa-screwdriver-wrench',
            'titel': w.bezeichnung,
            'zeile': (w.liegenschaft.strasse if w.liegenschaft_id else '')
                     + (f' · {w.anbieter}' if w.anbieter else ''),
            'datum': w.naechste_faelligkeit, 'tage': tage,
            'dringlichkeit': _dringlichkeit(tage),
            'ziel': (f'/neu/liegenschaften/{w.liegenschaft_id}/?tab=faelle'
                     if w.liegenschaft_id else '/neu/fristen/'),
            'knopf': 'Zur Frist', 'objekt': w,
        })
    return zeilen


#: Quelle → Funktion. Als Tabelle, damit ein Ausfall EINE Quelle kostet und
#: nicht die Startseite, und damit der Name im Log steht.
QUELLEN = (
    ('Läufe', _laeufe, False),
    ('Fälle', _fallschritte, False),
    ('Pendenzen', _pendenzen, True),
    ('Wartungsfristen', _wartungsfristen, True),
)


def was_reisst(heute=None, grenze=VORSCHAU_TAGE, aktive_lg=None):
    """Überfälliges und bald Fälliges, über alle Quellen gemischt.

    Rückgabe: nach Fälligkeit sortierte Liste. Jede Zeile trägt `art`, damit
    die Oberfläche das passende Ziel verlinken kann, ohne zu raten.
    """
    heute = heute or timezone.localdate()
    bis = heute + timedelta(days=grenze)
    eintraege = []
    for name, funktion, nimmt_lg in QUELLEN:
        try:
            eintraege += (funktion(heute, bis, aktive_lg) if nimmt_lg
                          else funktion(heute, bis))
        except Exception:
            # Ein Abschnitt darf ausfallen, ohne die Startseite mitzunehmen —
            # aber NIEMALS stillschweigend. Ein stummer except-Block ist in
            # diesem Haus verboten (Befund P6); hier wäre er zusätzlich
            # heimtückisch, weil eine leere Liste wie ein ruhiger Tag aussieht.
            log.exception('Arbeitsvorrat: Quelle «%s» konnte nicht geladen werden', name)
    eintraege.sort(key=lambda e: e['datum'])
    return eintraege


def posteingang():
    """Nicht zugeordnete Eingänge mit ihrem Vorschlag.

    «Kein sicherer Vorschlag» ist nach Konzept Abschnitt 6 ausdrücklich eine
    gültige Antwort und keine Lücke: *Ein Vorschlag ohne ausreichende
    Sicherheit wird als solcher gekennzeichnet — nicht geraten.*
    """
    try:
        from faelle.zulauf import vorschlagen
        from faelle.zulauf_models import Eingang
    except Exception:
        log.exception('Arbeitsvorrat: Posteingang konnte nicht geladen werden')
        return [], 0

    offen = list(Eingang.objects.offen()[:20])
    zeilen = []
    for e in offen[:ZEILEN]:
        v = vorschlagen(e)
        zeilen.append({
            'eingang': e,
            # `Vorschlag.__bool__` gibt `sicherheit == SICHER` zurück — der
            # Wahrheitswert ist also die Sicherheit, nicht die Existenz.
            'sicher': bool(v),
            'ziel': v.ziel, 'begruendung': v.begruendung, 'fallart': v.fallart,
        })
    return zeilen, len(offen)


def arbeitsvorrat(request, aktive_lg=None):
    """Alles, was die Heute-Ansicht braucht — in einem Aufruf."""
    heute = timezone.localdate()
    reisst = was_reisst(heute, aktive_lg=aktive_lg)
    eingaenge, eingaenge_gesamt = posteingang()
    return {
        'av_heute': heute,
        'av_reisst': reisst[:ZEILEN],
        'av_reisst_gesamt': len(reisst),
        # Ausgerechnet statt im Template `|add:"-5"` — sonst lügt der Text,
        # sobald jemand ZEILEN ändert.
        'av_reisst_weitere': max(len(reisst) - ZEILEN, 0),
        'av_ueberfaellig': sum(1 for e in reisst if e['tage'] < 0),
        'av_vorschau_tage': VORSCHAU_TAGE,
        'av_eingaenge': eingaenge,
        'av_eingaenge_gesamt': eingaenge_gesamt,
    }
