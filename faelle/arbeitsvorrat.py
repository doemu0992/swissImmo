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

#: Symbol je Terminart. Als Tabelle, damit eine neue Art eine Zeile kostet
#: und nicht eine Verzweigung in der Vorlage.
TERMIN_IKON = {
    'abnahme': 'gut',
    'besichtigung': 'schluessel',
    'gespraech': 'person',
    'begehung': 'person',
    'sonstiges': 'termin',
}

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


#: Wie weit ein blockierter Lauf VOR seinem Stichtag sichtbar wird — je
#: Rhythmus verschieden.
#:
#: DER BEFUND, DER DAZU GEFUEHRT HAT
#:
#: Der Arbeitsvorrat blickte 14 Tage voraus, fuer jeden Lauf gleich. Bei einem
#: Monatslauf ist das reichlich: Wer zwei Wochen vor der Sollstellung erfaehrt,
#: dass etwas fehlt, hat Zeit.
#:
#: Bei der Nebenkostenabrechnung — JAEHRLICH — ist es zu spaet. Eine fehlende
#: Verbrauchsablesung zwei Wochen vor Stichtag heisst: Techem anschreiben,
#: warten, mahnen, und dann ist die Abrechnung verspaetet. Wer denselben
#: Befund im Februar bekommt, holt ihn nach.
#:
#: Die Zahlen sind Erfahrungswerte, keine Rechnung: Ein Vorlauf soll so lang
#: sein, dass eine Rueckfrage an einen Dritten noch beantwortet werden kann.
#: Bei Quartals- und Jahreslaeufen haengt daran regelmaessig ein Externer
#: (Ablesedienst, Treuhand, ESTV).
VORLAUF_JE_RHYTHMUS = {
    'monatlich': 14,
    'quartalsweise': 45,
    'jaehrlich': 90,
}


def _laeufe(heute, bis):
    """Läufe, die fällig sind oder blockiert stehen.

    Ein blockierter Lauf zeigt den **Grund** («Verbrauchsablesung Techem
    fehlt»), nicht das Wort «blockiert». Der Grund führt zu einer Handlung,
    das Wort zu einer Rückfrage.

    BLOCKIERTE LAEUFE ERSCHEINEN FRUEHER — JE NACH RHYTHMUS

    Ein Lauf ohne Blockade wird zum Stichtag hin sichtbar; das ist der
    normale Rhythmus der Arbeit. Ein BLOCKIERTER Lauf ist etwas anderes: Dort
    fehlt etwas, das von aussen kommen muss, und die Zeit dafuer beginnt
    sofort zu laufen.

    Deshalb gilt fuer blockierte Laeufe der Vorlauf aus
    `VORLAUF_JE_RHYTHMUS` — 90 Tage bei einem Jahreslauf, 14 bei einem
    Monatslauf. Das ist G7 in seiner eigentlichen Bedeutung: nicht die Liste
    zeigen, sondern rechtzeitig warnen.
    """
    from datetime import timedelta

    from django.db.models import Prefetch

    from faelle.lauf_models import Blockade, Lauf

    # Die Grundmenge muss den WEITESTEN Vorlauf abdecken; gefiltert wird
    # danach je Lauf, weil der Rhythmus an der Laufart haengt.
    weitester = max(VORLAUF_JE_RHYTHMUS.values())

    # BLOCKADEN IM VORAUS HOLEN, NICHT JE LAUF NACHFRAGEN
    #
    # Das weitere Fenster hat die Kandidatenmenge von 20 auf 60 vergroessert,
    # und die Blockade wird jetzt fuer JEDEN Kandidaten gebraucht — auch fuer
    # die, die gleich wieder wegfallen. Gemessen ohne dieses Prefetch:
    # 61 Abfragen, um NULL Zeilen anzuzeigen (60 Monatslaeufe ausserhalb ihres
    # Vorlaufs, jeder einzeln nach seinen Blockaden gefragt, alle verworfen).
    #
    # `to_attr` statt `offene_blockaden`: Die Eigenschaft filtert selbst
    # (`behoben_am__isnull=True`) und ginge damit an jedem Prefetch vorbei —
    # sie wuerde weiter je Lauf fragen. Der gefilterte Prefetch liefert
    # dieselbe Menge in EINER Abfrage.
    kandidaten = (Lauf.objects.offen()
                  .filter(faellig_am__lte=max(bis, heute + timedelta(days=weitester)))
                  .select_related('laufart')
                  .prefetch_related(Prefetch(
                      'blockaden',
                      queryset=Blockade.objects.filter(behoben_am__isnull=True),
                      to_attr='_offene_blockaden'))[:60])

    zeilen = []
    for lauf in kandidaten:
        blockaden_vorab = lauf._offene_blockaden
        if lauf.faellig_am > bis:
            # Noch nicht im normalen Fenster — nur mit Blockade, und nur
            # innerhalb des Vorlaufs fuer seinen Rhythmus.
            if not blockaden_vorab:
                continue
            vorlauf = VORLAUF_JE_RHYTHMUS.get(lauf.laufart.rhythmus, 14)
            if (lauf.faellig_am - heute).days > vorlauf:
                continue
        if len(zeilen) >= 20:
            break
        tage = (lauf.faellig_am - heute).days
        blockaden = blockaden_vorab      # oben schon geholt, nicht zweimal fragen
        zeilen.append({
            'art': 'lauf', 'ikon': 'lauf',
            'titel': f'{lauf.laufart.bezeichnung} {lauf.periode}'
                     + (' nicht ausgelöst' if tage < 0 else ''),
            'zeile': (', '.join(b.grund for b in blockaden) if blockaden
                      else f'Stichtag {lauf.faellig_am.strftime("%d.%m.")}'),
            'datum': lauf.faellig_am, 'tage': tage,
            'dringlichkeit': 'crit' if blockaden else _dringlichkeit(tage),
            'ziel': '/neu/laeufe/', 'knopf': 'Zum Lauf', 'objekt': lauf,
        })
    return zeilen


def _kuerzel(benutzer):
    """«Dominik Muster» -> «DM». Fuer die enge Zeile im Arbeitsvorrat.

    Ohne Vor- und Nachnamen faellt es auf die ersten zwei Zeichen des
    Anmeldenamens zurueck — besser als ein leeres Feld, das aussieht, als
    waere niemand zustaendig.
    """
    vor = (benutzer.first_name or '').strip()
    nach = (benutzer.last_name or '').strip()
    if vor and nach:
        return f'{vor[0]}{nach[0]}'.upper()
    name = vor or nach or benutzer.get_username()
    return name[:2].upper()


def _fallschritte(heute, bis, wer=None, mandat=None):
    """Offene Fallschritte mit Frist.

    Das Fristfeld heisst `frist`, nicht `faellig_am` — nachgesehen, nicht
    geraten. Ein Entwurf nahm `faellig_am` an; der `except`-Zweig unten hätte
    den `FieldError` geschluckt und den Abschnitt **dauerhaft leer** gelassen.
    Das ist hier die gefährlichste Fehlerart: Eine leere Liste sieht aus wie
    ein ruhiger Tag.
    """
    from faelle.models import Fallschritt

    zeilen = []
    # DIE FILTER GREIFEN IN DER ABFRAGE, NICHT AUF DER FERTIGEN LISTE.
    #
    # Konzept v7 zeigt im Kopf «Zustaendigkeit» und «Mandat» — Fragen an die
    # FAELLE. Sie erst auf die fertige Liste anzuwenden waere falsch: Dann
    # zeigte die Kopfzeile «6 faellig heute» weiter alles und nur die
    # sichtbaren Zeilen waeren weniger. Ausserdem schneidet `[:20]` VOR dem
    # Filter — die eigenen Faelle koennten aus dem Fenster fallen, waehrend
    # fremde den Platz belegen.
    schritte = Fallschritt.objects.filter(erledigt_am__isnull=True,
                                          frist__isnull=False, frist__lte=bis)
    if wer is not None:
        schritte = schritte.filter(fall__zustaendig=wer)
    if mandat is not None:
        # NUR UEBER DIE AKTE — `Fall` hat kein `liegenschaft`-Feld.
        #
        # Ein Fall haengt ueber `akte_typ`/`akte_id` an einer beliebigen Akte
        # (Vertrag, Einheit, Liegenschaft, Eigentuemer, Mieter, Schaden). Ein
        # Filter ueber `fall__liegenschaft__eigentuemer` waere beim ersten
        # Aufruf gescheitert; das Feld gibt es nicht.
        #
        # Fuer «Mandat» heisst das: gezaehlt wird, was DIREKT am Eigentuemer
        # haengt. Ein Fall an einer Liegenschaft dieses Eigentuemers erscheint
        # nicht — das ist eine Einschraenkung und keine Luecke: Der Filter
        # sagt «Faelle dieses Mandats», nicht «alles, was ihn beruehrt».
        from django.contrib.contenttypes.models import ContentType

        from crm.models import Eigentuemer
        typ = ContentType.objects.get_for_model(Eigentuemer)
        schritte = schritte.filter(fall__akte_typ=typ, fall__akte_id=mandat.pk)
    # DER FORTSCHRITT KOMMT AUS EINER ANNOTATION, NICHT AUS DER EIGENSCHAFT.
    #
    # `Fall.fortschritt` rechnet mit ZWEI `COUNT`-Abfragen je Aufruf. In dieser
    # Schleife heisst das zwei Abfragen JE ZEILE — gemessen: 16 Zeilen kosteten
    # 36 statt 4 Abfragen, bei der Obergrenze von 20 Zeilen also bis zu 40
    # zusaetzliche auf der meistbesuchten Seite der Anwendung. Genau der
    # Rueckbau «je Datensatz statt je Menge», vor dem der Kopf dieser Datei
    # warnt und den `AbfragezahlTests` abfangen soll.
    #
    # Die Eigenschaft bleibt, wo sie ist — sie ist fuer die Detailansicht
    # richtig, wo sie einmal laeuft.
    from django.db.models import Count

    for s in (schritte
              .select_related('fall', 'fall__fallart', 'fall__zustaendig')
              .annotate(_gesamt=Count('fall__schritte', distinct=True))[:20]):
        tage = (s.frist - heute).days
        # FALLNUMMER, FORTSCHRITT UND ZUSTAENDIGKEIT (E2.62)
        #
        # Konzept v7 zeigt je Zeile: «Mieterwechsel · F-2026-0184» als Kopf,
        # darunter «Schritt 3 von 6 · Ausschreibung» und rechts das Kuerzel
        # der zustaendigen Person.
        #
        # Bis hierher stand nur «Mieterwechsel · Blaser». WAS FEHLTE, IST DIE
        # EINORDNUNG: Ein Fall bei Schritt 3 von 6 ist etwas anderes als einer
        # bei 5 von 6, und wer ihn fuehrt, entscheidet, ob man ihn anfasst
        # oder liegen laesst.
        #
        # DIE NUMMER DES SCHRITTS, NICHT «ERLEDIGTE + 1».
        #
        # Der Entwurf rechnete die Position aus der Zahl der erledigten
        # Schritte. Das stimmt nur, solange in der Reihenfolge abgearbeitet
        # wird: Sind Schritt 1 und 3 erledigt und 2 offen, stuende an der Zeile
        # von Schritt 2 «Schritt 3 von 6». Die Zeile IST ein bestimmter Schritt
        # und traegt seine Nummer — die braucht nicht geschaetzt zu werden.
        zeilen.append({
            'art': 'fall', 'ikon': 'dokument',
            'titel': s.bezeichnung,
            'zeile': (f'{s.fall.fallart.bezeichnung} · {s.fall.betreff}'
                      if s.fall.betreff else s.fall.fallart.bezeichnung),
            'nummer': s.fall.nummer,
            'fortschritt': f'Schritt {s.nr} von {s._gesamt}' if s._gesamt else '',
            # Das Kuerzel, nicht der ganze Name: Die Zeile ist eng, und wer im
            # Buero arbeitet, kennt die Kuerzel. «niemand» ist eine Aussage —
            # ein Fall ohne Zustaendigkeit faellt sonst niemandem auf.
            'wer': (_kuerzel(s.fall.zustaendig) if s.fall.zustaendig_id
                    else 'niemand'),
            'datum': s.frist, 'tage': tage,
            'dringlichkeit': _dringlichkeit(tage),
            # DIE FALLART ALS WERT, NICHT NUR ALS TEXT (E2.61).
            #
            # Bis hierher stand sie nur in `zeile` («Mieterwechsel · Blaser»).
            # Das Filterband aus v7 braucht sie als SCHLUESSEL: Ein Vergleich
            # auf die Anzeigezeichenkette bricht, sobald jemand eine Fallart
            # umbenennt — und Umbenennen ist erlaubt, jede Organisation fuehrt
            # ihre eigenen (siehe `Fallart`-Kopf).
            'fallart': s.fall.fallart.schluessel,
            'fallart_text': s.fall.fallart.bezeichnung,
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
            'art': 'pendenz', 'ikon': 'wartet',
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
            'art': 'wartung', 'ikon': 'arbeit',
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


def was_reisst(heute=None, grenze=VORSCHAU_TAGE, aktive_lg=None,
               wer=None, mandat=None):
    """Überfälliges und bald Fälliges, über alle Quellen gemischt.

    Rückgabe: nach Fälligkeit sortierte Liste. Jede Zeile trägt `art`, damit
    die Oberfläche das passende Ziel verlinken kann, ohne zu raten.
    """
    heute = heute or timezone.localdate()
    bis = heute + timedelta(days=grenze)
    eintraege = []
    for name, funktion, nimmt_lg in QUELLEN:
        try:
            # Nur `_fallschritte` kennt Zustaendigkeit und Mandat: Laeufe,
            # Pendenzen und Wartungsfristen haengen an keinem Fall. Sie
            # ungefiltert zu lassen ist richtig — ein Zahllauf gehoert allen.
            #
            # DER AUFRUF STEHT IM `try`, NICHT DAVOR. Ein erster Entwurf zog
            # ihn mit `continue` vor den Block; damit lief ausgerechnet die
            # gefilterte Abfrage OHNE Ausfallschutz, und ein Fehler dort haette
            # die Startseite mit 500 beendet statt eine Quelle auszulassen.
            # Derselbe Fund wie in E2.59 bei `vertretung()`.
            if funktion is _fallschritte and (wer is not None or mandat is not None):
                eintraege += funktion(heute, bis, wer=wer, mandat=mandat)
                continue
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


def termine(heute=None, tage=7):
    """Was in den nächsten Tagen im Kalender steht.

    Der Prototyp (`mockups/konzept-struktur.html`, Screen «Heute») zeigt drei
    Arten: Wohnungsabnahme, Besichtigung, Eigentümergespräch. Zwei davon sind
    rechenbar:

        Abnahme       `rentals.Abnahmeprotokoll` mit `datum` und
                      `abgeschlossen = False`
        Besichtigung  `mietprozess.Mietbewerbung.besichtigung_am`

    **Das Eigentümergespräch nicht.** Es gibt kein Terminmodell — weder für
    Gespräche noch für sonstige Verabredungen. Eine erfundene Zeile wäre hier
    schlimmer als eine fehlende: Wer einen Kalender sieht, verlässt sich
    darauf.
    """
    from datetime import datetime, time

    heute = heute or timezone.localdate()
    bis = heute + timedelta(days=tage)
    zeilen = []

    try:
        from rentals.models import Abnahmeprotokoll
        for a in (Abnahmeprotokoll.objects
                  .filter(abgeschlossen=False, datum__gte=heute, datum__lte=bis)
                  .select_related('vertrag__einheit__liegenschaft')
                  .order_by('datum')[:20]):
            einheit = getattr(a.vertrag, 'einheit', None)
            zeilen.append({
                'art': 'abnahme', 'ikon': 'gut',
                'titel': 'Wohnungsabnahme' if a.typ == 'auszug' else 'Übergabe',
                'zeile': str(einheit) if einheit else '',
                'datum': a.datum, 'zeit': None,
                'ziel': f'/neu/vertraege/{a.vertrag_id}/', 'knopf': 'Vertrag',
            })
    except Exception:
        log.exception('Termine: Abnahmen konnten nicht geladen werden')

    try:
        from mietprozess.models import Mietbewerbung
        # `besichtigung_am` ist ein DateTimeField — der Vergleich läuft
        # deshalb über den Tagesbeginn, nicht über das nackte Datum.
        von = timezone.make_aware(datetime.combine(heute, time.min))
        nach = timezone.make_aware(datetime.combine(bis, time.max))
        for b in (Mietbewerbung.objects
                  .filter(besichtigung_am__gte=von, besichtigung_am__lte=nach)
                  .select_related('einheit__liegenschaft')
                  .order_by('besichtigung_am')[:20]):
            zeilen.append({
                'art': 'besichtigung', 'ikon': 'schluessel',
                'titel': 'Besichtigung',
                'zeile': f'{b.einheit} · {b.vorname} {b.nachname}',
                'datum': timezone.localtime(b.besichtigung_am).date(),
                'zeit': timezone.localtime(b.besichtigung_am).time(),
                'ziel': '/neu/bewerbungen/', 'knopf': 'Bewerbung',
            })
    except Exception:
        log.exception('Termine: Besichtigungen konnten nicht geladen werden')

    try:
        from faelle.termin_models import Termin
        von = timezone.make_aware(datetime.combine(heute, time.min))
        nach = timezone.make_aware(datetime.combine(bis, time.max))
        for t in (Termin.objects.offen().zeitraum(von, nach)
                  .select_related('zustaendig')[:20]):
            ortszeit = timezone.localtime(t.beginn)
            zeilen.append({
                'art': t.art, 'ikon': TERMIN_IKON.get(t.art, 'termin'),
                'titel': t.titel,
                'zeile': ' · '.join(x for x in (
                    t.ort, str(t.akte) if t.akte_id else '',
                    (t.zustaendig.get_full_name() or t.zustaendig.username)
                    if t.zustaendig_id else '') if x),
                'datum': ortszeit.date(), 'zeit': ortszeit.time(),
                'ziel': '/neu/termine/', 'knopf': 'Termin',
            })
    except Exception:
        log.exception('Termine: erfasste Termine konnten nicht geladen werden')

    zeilen.sort(key=lambda z: (z['datum'], z['zeit'] or time.min))
    return zeilen


def vertretung(heute=None):
    """Wer abwesend ist — und was auf wen läuft.

    Umsetzung von G8 («Zuständigkeit statt Rolle … plus Vertretung»). Bis
    4b.7 war dieser Abschnitt des Prototyps nicht baubar: `Mitgliedschaft`
    führt Benutzer, Organisation und Rolle, kein Abwesenheitsfeld. Jetzt
    trägt `faelle.Abwesenheit` die Angabe.

    **Eine Abwesenheit ohne Vertretung ist kein Fehler, sondern eine
    Aussage** — und eine, die auffallen soll. Sie wird deshalb ausdrücklich
    als ungedeckt gemeldet, statt still wie eine gedeckte auszusehen.
    """
    heute = heute or timezone.localdate()
    # DER SCHUTZ MUSS DIE ABFRAGE UMFASSEN, NICHT NUR DEN IMPORT.
    #
    # Bis E2.59 stand hier nur `from … import Abwesenheit` im `try`. Ein Import
    # aus der eigenen App faellt praktisch nie aus; die ABFRAGE kann es. Damit
    # war der Schutz genau um die Zeile herumgelegt, die ihn nicht braucht —
    # und ein Fehler beim Laden der Abwesenheiten riss die ganze Startseite mit
    # (500 statt eines fehlenden Abschnitts). Gefunden vom Ausfalltest zum
    # Vertretungshinweis im Kopf, der denselben Ausfall herstellt.
    try:
        from faelle.termin_models import Abwesenheit

        zeilen = []
        for a in (Abwesenheit.objects.laufend(heute)
                  .select_related('benutzer', 'vertreten_durch')[:10]):
            name = a.benutzer.get_full_name() or a.benutzer.username
            zeilen.append({
                'abwesenheit': a,
                'wer': name,
                'bis': a.bis,
                'grund': a.get_grund_display(),
                'vertreter': ((a.vertreten_durch.get_full_name()
                               or a.vertreten_durch.username)
                              if a.vertreten_durch_id else None),
                'faelle': a.offene_faelle,
                'ungedeckt': a.vertreten_durch_id is None,
            })
        return zeilen
    except Exception:
        log.exception('Vertretung: Abwesenheiten konnten nicht geladen werden')
        return []


def wartet_auf_freigabe():
    """Was ohne eine Entscheidung nicht weitergeht.

    Der Prototyp zeigt drei Arten, alle drei sind rechenbar: Lieferanten-
    rechnung, Handwerker-Offerte, Mietvertrag zur Unterschrift.

    **Nicht «wartet auf MICH».** Der Prototyp nennt den Abschnitt so; das
    Datenmodell trägt es nicht: Weder `KreditorenRechnung` noch
    `HandwerkerAuftrag` führen einen Freigeber, und `Mitgliedschaft` kennt
    keine Zuständigkeit je Vorgang. In einem Büro mit zwei bis fünf Personen
    ist die Warteschlange ohnehin gemeinsam — aber die Überschrift darf das
    nicht als persönlich ausgeben.
    """
    heute = timezone.localdate()
    zeilen = []

    def _alter(datum):
        if datum is None:
            return None
        if hasattr(datum, 'date'):
            datum = timezone.localtime(datum).date()
        return (heute - datum).days

    try:
        from finance.models import KreditorenRechnung
        for r in (KreditorenRechnung.objects.filter(status='neu')
                  .select_related('liegenschaft').order_by('datum')[:10]):
            zeilen.append({
                'art': 'rechnung', 'ikon': 'rechnung',
                'titel': f'Rechnung {r.lieferant}' if r.lieferant else 'Eingangsrechnung',
                'zeile': str(r.liegenschaft or ''),
                'betrag': r.betrag, 'tage': _alter(r.datum),
                'ziel': '/neu/kreditoren/', 'knopf': 'Freigeben',
            })
    except Exception:
        log.exception('Freigaben: Kreditoren konnten nicht geladen werden')

    try:
        from tickets.models import HandwerkerAuftrag
        for a in (HandwerkerAuftrag.objects.filter(freigabe_status='ausstehend')
                  .select_related('handwerker', 'ticket')[:10]):
            zeilen.append({
                'art': 'offerte', 'ikon': 'vertrag',
                'titel': f'Offerte {a.handwerker}' if a.handwerker_id else 'Offerte',
                'zeile': str(getattr(a.ticket, 'titel', '') or ''),
                'betrag': a.kosten_geschaetzt, 'tage': _alter(a.beauftragt_am),
                'ziel': f'/neu/schaeden/{a.ticket_id}/', 'knopf': 'Entscheiden',
            })
    except Exception:
        log.exception('Freigaben: Handwerker-Offerten konnten nicht geladen werden')

    try:
        from rentals.models import Mietvertrag
        for v in (Mietvertrag.objects.filter(status='entwurf')
                  .select_related('mieter', 'einheit__liegenschaft')
                  .order_by('beginn')[:10]):
            zeilen.append({
                'art': 'vertrag', 'ikon': 'bearbeiten',
                'titel': f'Mietvertrag {v.mieter.display_name}' if v.mieter_id
                         else 'Mietvertrag',
                'zeile': f'{v.einheit} · zur Unterschrift',
                'betrag': None, 'tage': None,
                'ziel': f'/neu/vertraege/{v.id}/signieren/', 'knopf': 'Signatur',
            })
    except Exception:
        log.exception('Freigaben: Vertragsentwürfe konnten nicht geladen werden')

    return zeilen


def liegezeit(zeilen):
    """Durchschnittliche Liegezeit der Freigaben, in Tagen.

    Der Prototyp zeigt sie als Fusszeile («Ø Liegezeit 1.4 Tage»). Sie ist
    die einzige Zahl, die sagt, ob der Stapel bearbeitet wird oder wächst.
    Vorgänge ohne Datum zählen nicht mit — sonst zöge ein fehlendes Feld den
    Schnitt gegen null.
    """
    alter = [z['tage'] for z in zeilen if z.get('tage') is not None]
    return round(sum(alter) / len(alter), 1) if alter else None


def arbeitsvorrat(request, aktive_lg=None, wer=None, mandat=None):
    """Alles, was die Heute-Ansicht braucht — in einem Aufruf."""
    heute = timezone.localdate()
    reisst = was_reisst(heute, aktive_lg=aktive_lg, wer=wer, mandat=mandat)
    eingaenge, eingaenge_gesamt = posteingang()
    termin_zeilen = termine(heute)
    freigaben = wartet_auf_freigabe()
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
        'av_termine': termin_zeilen[:ZEILEN],
        'av_termine_gesamt': len(termin_zeilen),
        'av_freigaben': freigaben[:ZEILEN],
        'av_freigaben_gesamt': len(freigaben),
        'av_liegezeit': liegezeit(freigaben),
        'av_vertretung': vertretung(heute),
    }
